# SPDX-License-Identifier: GPL-3.0-or-later
"""Make Live lists/history, reversible viewport selection restrictions and target queries."""
from collections import OrderedDict
import bpy
from bpy.app.handlers import persistent
from mathutils.bvhtree import BVHTree
from .. import i18n

COLOR = (0., 153/255, 84/255)  # sRGB #009954, Maya's live surface wire / Outliner colour
LIMIT = 16
LOCK = '_allset_live_select_before'
_busy = False
_locked = {}          # session_uid -> object name of the objects whose selection Make Live locked
_trees = OrderedDict()
CACHE_BUDGET = 256 * 1024 * 1024  # estimated retained BVH bytes; one oversized surface may occupy the cache alone


class ALLSET_PG_live_ref(bpy.types.PropertyGroup):
    object: bpy.props.PointerProperty(type=bpy.types.Object)


class ALLSET_PG_live_history(bpy.types.PropertyGroup):
    objects: bpy.props.CollectionProperty(type=ALLSET_PG_live_ref)


def objects(scene):
    """Current valid live meshes, including hidden references. Never fall back to other objects."""
    refs = getattr(scene, 'allset_live_objects', ())
    result = [r.object for r in refs if r.object is not None and r.object.type == 'MESH'
              and scene.objects.get(r.object.name) == r.object]
    legacy = getattr(scene, 'allset_live', None)
    if not refs and legacy is not None and legacy.type == 'MESH' and scene.objects.get(legacy.name) == legacy:
        result = [legacy]
    return result


def contains(scene, ob):
    return ob is not None and ob in objects(scene)


def text(scene):
    refs = objects(scene)
    return ('<'+refs[0].name+'...>' if len(refs) > 1 else refs[0].name) if refs else 'No Live Surface'


def redraw():
    wm = getattr(bpy.context, 'window_manager', None)
    for window in wm.windows if wm else ():
        for area in window.screen.areas:
            area.tag_redraw()


def _restore(ob):
    if LOCK in ob:
        ob.hide_select = bool(ob[LOCK])
        del ob[LOCK]


def _gone(ob):
    return ob is None or not ob.users_scene


def _prune(scene):
    """Drop deleted objects from the live list and history: a kept pointer would hold the object (and its mesh) in
    the file after it was deleted."""
    refs = getattr(scene, 'allset_live_objects', None)
    for i in reversed(range(len(refs) if refs is not None else 0)):
        if _gone(refs[i].object):
            refs.remove(i)
    history = getattr(scene, 'allset_live_history', None)
    for i in reversed(range(len(history) if history is not None else 0)):
        entry = history[i].objects
        for j in reversed(range(len(entry))):
            if _gone(entry[j].object):
                entry.remove(j)
        if not len(entry):
            history.remove(i)
    legacy = getattr(scene, 'allset_live', None)
    if legacy is not None and _gone(legacy):
        scene.allset_live = None


def sync():
    """Reconcile the union of live references across scenes, without touching transform locks."""
    global _busy
    if _busy:
        return
    _busy = True
    try:
        wanted = {}
        for scene in bpy.data.scenes:
            _prune(scene)
            refs = objects(scene)
            first = refs[0] if refs else None
            if getattr(scene, 'allset_live', None) != first:
                scene.allset_live = first
            wanted.update((ob.session_uid, ob) for ob in refs)
        for uid, name in list(_locked.items()):
            if uid not in wanted:
                _trees.pop(uid, None)
                ob = bpy.data.objects.get(name)
                if ob is not None and ob.session_uid == uid:
                    _restore(ob)
                del _locked[uid]
        for uid, ob in wanted.items():
            if LOCK not in ob:
                ob[LOCK] = ob.hide_select
            if not ob.hide_select:
                ob.hide_select = True
            _locked[uid] = ob.name
    finally:
        _busy = False


def _remember(scene, targets):
    ids = tuple(o.session_uid for o in targets)
    history = scene.allset_live_history
    for i in reversed(range(len(history))):
        if tuple(r.object.session_uid for r in history[i].objects if r.object is not None) == ids:
            history.remove(i)
    entry = history.add()
    for ob in targets:
        entry.objects.add().object = ob
    while len(history) > LIMIT:
        history.remove(0)


def set_objects(scene, targets, remember=True):
    global _busy
    targets = list(dict.fromkeys(targets))
    if any(o.type != 'MESH' or o.mode == 'EDIT' or scene.objects.get(o.name) != o for o in targets):
        raise ValueError('Make Live needs mesh objects outside Edit Mode')
    _busy = True
    try:
        if targets and remember:
            _remember(scene, targets)
        scene.allset_live_objects.clear()
        for ob in targets:
            scene.allset_live_objects.add().object = ob
            vl = getattr(bpy.context, 'view_layer', None)
            if vl and vl.objects.get(ob.name) == ob:
                ob.select_set(False)
        scene.allset_live = targets[0] if targets else None
        # An active-but-deselected live reference must not become an Edit Mode target.
        vl = getattr(bpy.context, 'view_layer', None)
        if vl and vl.objects.active in targets:
            vl.objects.active = next((ob for ob in vl.objects if ob is not None and ob.select_get() and ob not in targets),
                                      None)
    finally:
        _busy = False
    sync()
    redraw()


def compatibility_changed(scene, _context):
    """Keep scripts/old files that set Scene.allset_live working with the live list."""
    if not _busy and hasattr(scene, 'allset_live_objects'):
        target = scene.allset_live
        try:
            set_objects(scene, [target] if target else [])
        except ValueError:
            pass


def recent(scene):
    for entry in reversed(scene.allset_live_history):
        refs = [r.object for r in entry.objects if r.object is not None
                and scene.objects.get(r.object.name) == r.object and r.object.type == 'MESH']
        if refs:
            return refs
    return []


def selected(context, outliner=False):
    """Outliner tree selection also identifies viewport-restricted objects for list management."""
    result = list(context.selected_objects)
    if result and not outliner and getattr(context.area, 'type', '') != 'OUTLINER':
        return result
    result.extend(o for o in getattr(context, 'selected_ids', ()) if isinstance(o, bpy.types.Object))
    from ..ui import outliner_tree
    for area in context.screen.areas if context.screen else ():
        if area.type != 'OUTLINER':
            continue
        if outliner_tree.is_tree(area.spaces.active):         # the kit's rows: its picks of locked objects
            result.extend(outliner_tree.picked_unselectable(context))
            continue
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region:
            with context.temp_override(area=area, region=region):
                result.extend(o for o in getattr(bpy.context, 'selected_ids', ()) if isinstance(o, bpy.types.Object))
    # an Outliner row stays highlighted after the viewport selection is cleared: only rows the viewport can't select
    # (live objects are selection-restricted) count from there, so an empty selection still turns Make Live off
    picked = set(context.selected_objects)
    return list(dict.fromkeys(o for o in result if context.scene.objects.get(o.name) == o
                              and (o in picked or o.hide_select)))


class ALLSET_OT_live_history(bpy.types.Operator):
    """Live surface history; middle-click to toggle the most recent live list"""
    bl_idname = 'allset.live_history'
    bl_label = 'Make Live History'
    bl_options = {'INTERNAL'}

    @classmethod
    @i18n.translated
    def description(cls, context, _props):
        names = ', '.join(ob.name for ob in objects(context.scene))
        return ('Live: '+names+'. ' if names else '')+'Choose a previous live surface; middle-click to toggle the latest'

    def invoke(self, context, event):
        if event.type == 'MIDDLEMOUSE':
            return bpy.ops.allset.live_list('EXEC_DEFAULT', True, action='RECENT')
        return self.execute(context)

    def execute(self, context):
        bpy.ops.wm.call_menu(name='ALLSET_MT_live_history')
        return {'FINISHED'}


class ALLSET_OT_live_list(bpy.types.Operator):
    """Recall, add, remove or clear Make Live surfaces"""
    bl_idname = 'allset.live_list'
    bl_label = 'Live Surfaces'
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=[(s, s.title(), '') for s in ('CLEAR', 'RECALL', 'RECENT', 'ADD', 'REMOVE')],
                                  options={'HIDDEN'})
    index: bpy.props.IntProperty(default=0, options={'HIDDEN'})
    object_name: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        scene = context.scene
        current = objects(scene)
        if self.action == 'CLEAR':
            targets = []
        elif self.action == 'RECENT':
            targets = [] if current else recent(scene)
        elif self.action == 'RECALL':
            if not 0 <= self.index < len(scene.allset_live_history):
                return {'CANCELLED'}
            targets = [r.object for r in scene.allset_live_history[self.index].objects if r.object is not None
                       and scene.objects.get(r.object.name) == r.object]
            if not targets:
                self.report({'WARNING'}, 'These live surfaces no longer exist in this scene')
                return {'CANCELLED'}
        elif self.action == 'ADD':
            targets = current + selected(context)
        else:
            remove = [o for o in current if o.name == self.object_name] if self.object_name else selected(context, outliner=True)
            targets = [o for o in current if o not in remove]
        try:
            set_objects(scene, targets)
        except ValueError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_MT_live_history(bpy.types.Menu):
    bl_label = 'Make Live History'

    def draw(self, context):
        lay = self.layout
        lay.operator('allset.live_list', text='No Live Surface').action = 'CLEAR'
        lay.separator()
        for i in reversed(range(len(context.scene.allset_live_history))):
            refs = [r.object for r in context.scene.allset_live_history[i].objects if r.object is not None]
            if refs:
                op = lay.operator('allset.live_list', text=', '.join(o.name for o in refs), icon='SNAP_FACE')
                op.action, op.index = 'RECALL', i
        lay.separator()
        lay.operator('allset.live_list', text='Add Selected').action = 'ADD'
        lay.operator('allset.live_list', text='Remove Selected').action = 'REMOVE'
        for ob in objects(context.scene):
            op = lay.operator('allset.live_list', text='Remove '+ob.name)
            op.action, op.object_name = 'REMOVE', ob.name


class SurfaceTree:
    """World-space queries over a native local BVH for similarity transforms."""
    def __init__(self, bvh, triangles, matrix=None):
        self.bvh, self.triangles, self.matrix = bvh, triangles, matrix
        if matrix is not None:
            self.inverse = matrix.inverted()
            self.normals = self.inverse.to_3x3().transposed()
            if matrix.determinant() < 0:
                self.normals *= -1

    def _world(self, hit, source):
        point, normal, face, distance = hit
        if point is None or self.matrix is None:
            return hit
        point = self.matrix @ point
        return point, (self.normals @ normal).normalized(), face, (point-source).length

    def ray_cast(self, origin, direction):
        if self.matrix is None:
            return self.bvh.ray_cast(origin, direction)
        hit = self.bvh.ray_cast(self.inverse @ origin, (self.inverse.to_3x3() @ direction).normalized())
        return self._world(hit, origin)

    def find_nearest(self, point):
        return self._world(self.bvh.find_nearest(self.inverse @ point), point) if self.matrix is not None else self.bvh.find_nearest(point)


def _similarity(matrix):
    """Local nearest distance is valid only for orthogonal axes of equal nonzero length."""
    axes = matrix.to_3x3().col
    lengths = [axis.length_squared for axis in axes]
    scale = max(lengths)
    return (min(lengths) > 1e-20 and max(lengths)-min(lengths) <= scale*1e-6
            and all(abs(axes[i].dot(axes[j])) <= scale*1e-6 for i, j in ((0, 1), (0, 2), (1, 2))))


def tree(context, ob):
    """Cache evaluated surfaces without expanding uniform-scale meshes into Python vertex/face lists."""
    mw = ob.matrix_world.copy()
    signature = tuple(map(tuple, mw))
    cached = _trees.get(ob.session_uid)
    if cached and cached[0] == signature:
        _trees.move_to_end(ob.session_uid)
        return cached[2]
    depsgraph = context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(depsgraph)
    mesh = ev.data
    triangles = max(0, len(mesh.loops)-2*len(mesh.polygons))
    if _similarity(mw):
        result = SurfaceTree(BVHTree.FromObject(ev, depsgraph), triangles, mw)
    else:
        # Anisotropic scale/shear needs world-space geometry for correct nearest
        # distances. Keep this path exact rather than approximating its metric.
        import numpy as np
        co = np.empty(len(mesh.vertices)*3, dtype=np.float32)
        mesh.vertices.foreach_get('co', co)
        world = co.reshape(-1, 3) @ np.array(mw.to_3x3(), dtype=np.float32).T + np.array(mw.translation, dtype=np.float32)
        result = SurfaceTree(BVHTree.FromPolygons(world.tolist(), [tuple(p.vertices) for p in mesh.polygons]), triangles)
    cost = triangles*128 + len(mesh.vertices)*12
    _trees[ob.session_uid] = (signature, ob.data.session_uid, result, cost)
    _trees.move_to_end(ob.session_uid)
    while len(_trees) > 1 and (len(_trees) > 64 or sum(value[3] for value in _trees.values()) > CACHE_BUDGET):
        _trees.popitem(last=False)
    return result


def ray_hit(context, origin, direction, targets=None, backfaces=True):
    best = None
    for ob in objects(context.scene) if targets is None else targets:
        bvh = tree(context, ob)
        point, normal, _face, distance = bvh.ray_cast(origin, direction)
        for _ in range(bvh.triangles+1):
            if point is None or backfaces or normal.dot(direction) <= 0:
                break
            previous = point
            epsilon = max(1e-7, max(abs(c) for c in point)*2**-23)
            cursor = point+direction*epsilon
            if (cursor-point).dot(direction) <= 0:
                point = None
                break
            point, normal, _face, _d = bvh.ray_cast(cursor, direction)
            if point is not None:
                if (point-previous).dot(direction) <= 0:
                    point = None
                    break
                distance = (point-origin).length
        if point is not None and (backfaces or normal.dot(direction) <= 0) and (best is None or distance < best[0]):
            best = distance, point, normal, ob
    return best[1:] if best else None


def nearest(context, point, targets=None):
    best = None
    for ob in objects(context.scene) if targets is None else targets:
        location, normal, _face, distance = tree(context, ob).find_nearest(point)
        if location is not None and (best is None or distance < best[0]):
            best = distance, location, normal, ob
    return best[1:] if best else None


@persistent
def changed(_scene=None, depsgraph=None):
    if depsgraph is not None:
        for update in depsgraph.updates:
            if update.is_updated_geometry or update.is_updated_transform:
                block = update.id.original
                if isinstance(block, bpy.types.Object):
                    _trees.pop(block.session_uid, None)
                elif isinstance(block, bpy.types.Mesh):
                    for uid in [uid for uid, val in _trees.items() if val[1] == block.session_uid]:
                        del _trees[uid]
    sync()


@persistent
def reload(*_args):
    _trees.clear()
    _locked.clear()
    wanted = {ob for scene in bpy.data.scenes for ob in objects(scene)}
    for ob in bpy.data.objects:
        if LOCK in ob and ob not in wanted:
            _restore(ob)
    sync()
    redraw()


@persistent
def frame_changed(*_args):
    _trees.clear()


HANDLERS = (('depsgraph_update_post', changed), ('load_post', reload), ('undo_post', reload),
            ('redo_post', reload), ('frame_change_post', frame_changed))


def register():
    bpy.types.Scene.allset_live_objects = bpy.props.CollectionProperty(type=ALLSET_PG_live_ref)
    bpy.types.Scene.allset_live_history = bpy.props.CollectionProperty(type=ALLSET_PG_live_history)
    for name, fn in HANDLERS:
        getattr(bpy.app.handlers, name).append(fn)
    # Saved Maya mode registers while Blender exposes _RestrictData. The
    # load_post handler will reconcile the startup scene once it is available.
    # Switching Maya mode on in an already open file can reconcile immediately.
    if hasattr(bpy.data, 'scenes'):
        reload()


def unregister():
    for name, fn in HANDLERS:
        lst = getattr(bpy.app.handlers, name)
        if fn in lst:
            lst.remove(fn)
    for ob in bpy.data.objects:
        _restore(ob)
    _locked.clear()
    _trees.clear()
    del bpy.types.Scene.allset_live_history
    del bpy.types.Scene.allset_live_objects


classes = (ALLSET_PG_live_ref, ALLSET_PG_live_history, ALLSET_OT_live_history, ALLSET_OT_live_list, ALLSET_MT_live_history)
