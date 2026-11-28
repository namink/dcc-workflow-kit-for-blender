# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolate Select with components, like Maya.

Maya: Isolate Select (Ctrl+1, Show > Isolate Select > View Selected) with faces selected shows only those faces in
that panel; with vertices or edges selected it shows the faces around them (every face that uses one of their
vertices). Objects selected together with components are shown whole. Show > Isolate Select > Add Selected Objects /
Remove Selected Objects add or take out faces the same way while the panel isolates. The isolate set is not part of
undo: undo changes the scene, not what the panel isolates.

Blender's Isolate Select is the 3D View's local view, which works on whole objects; the kit isolates the edited meshes
there and hides the faces outside the isolate set with Blender's face hide while the view isolates them. Only faces
the kit hides get the face attribute ``ATTR``: leaving Isolate Select (Ctrl+1 again, the Show menu, closing the panel,
the four view) shows exactly those faces again, so faces the user hid stay hidden. The attribute lives in the mesh,
so every undo step agrees with what it hides: after undo / redo the kit hides the faces outside the set again while
the view still isolates, and shows the marked faces again once it doesn't. A file opened with the attribute (saved
while isolating) gets its marked faces back.

Blender's face hide belongs to the mesh, so the faces are hidden in every 3D View while one view isolates them, and
only in Edit Mode (Object Mode draws the whole mesh).
"""

import bmesh
import bpy
from bpy.app.handlers import persistent
from bpy.props import EnumProperty

from .. import i18n

ATTR = "allset_isolate_hidden"     # face attribute (int): 1 = hidden by the kit's Isolate Select

# object name -> {"count": face count, "keep": face indices of the isolate set, "gone": ticks without a local view}
_on = {}
_TICK = 0.25
_GRACE = 3          # ticks without any isolating view before the faces come back (the four view moves the view)


# --- which faces --------------------------------------------------------------------------------------------------

def picked_faces(bm, select_mode):
    """The isolate set of a selection: in face mode the selected faces, else every face using a selected vertex
    (vertices and edges)."""
    v, e, f = select_mode
    if f and not v and not e:
        return {x.index for x in bm.faces if x.select and not x.hide}
    return {x.index for vert in bm.verts if vert.select and not vert.hide for x in vert.link_faces}


def _bm(ob):
    bm = bmesh.from_edit_mesh(ob.data)
    bm.faces.index_update()
    return bm


def _apply(ob, bm, keep):
    """Show the faces ``keep`` the kit hid, hide (and mark) the shown faces outside it; faces the user hid stay."""
    layer = bm.faces.layers.int.get(ATTR) or bm.faces.layers.int.new(ATTR)
    show = []
    for f in bm.faces:
        if f.index in keep:
            if f[layer]:
                show.append(f)
        elif not f.hide:
            f.hide_set(True)          # hides first: a shown face then gives its shared corners back
            f[layer] = 1
    for f in show:
        f.hide_set(False)
        f[layer] = 0
    bm.select_flush_mode()
    bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)


def _release(ob):
    """Show again the faces the kit hid on ``ob`` and drop the attribute (Edit Mode or Object Mode)."""
    me = getattr(ob, "data", None)
    if not isinstance(me, bpy.types.Mesh):
        return
    if ob.mode == 'EDIT' and me.is_editmode:
        bm = _bm(ob)
        layer = bm.faces.layers.int.get(ATTR)
        if layer is None:
            return
        for f in bm.faces:
            if f[layer]:
                f.hide_set(False)
        bm.faces.layers.int.remove(layer)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
        return
    _release_mesh(me)


def _release_mesh(me):
    a = me.attributes.get(ATTR)
    if a is None or me.is_editmode:
        return
    if a.domain == 'FACE' and len(a.data) == len(me.polygons):
        vals = [0] * len(me.polygons)
        a.data.foreach_get("value", vals)
        for i, v in enumerate(vals):
            if not v:
                continue
            p = me.polygons[i]
            p.hide = False
            for vi in p.vertices:
                me.vertices[vi].hide = False
            for li in p.loop_indices:
                me.edges[me.loops[li].edge_index].hide = False
    me.attributes.remove(a)
    me.update()


def _face_count(ob):
    if ob.mode == 'EDIT' and ob.data.is_editmode:
        return len(bmesh.from_edit_mesh(ob.data).faces)
    return len(ob.data.polygons)


# --- state --------------------------------------------------------------------------------------------------------

def active():
    """Names of the objects whose faces Isolate Select shows only in part."""
    return sorted(_on)


def kept(ob):
    """``ob``'s isolate set (sorted face indices); None when it isn't isolated by its faces."""
    rec = _on.get(ob.name)
    return None if rec is None else sorted(rec["keep"])


def start(context, space):
    """Ctrl+1 in Edit Mode, called after the local view is made: an edited mesh with selected components shows only
    their faces, one without leaves the view (Maya isolates the selection). False when nothing is selected (the
    whole edited objects stay, as before)."""
    mode = tuple(context.scene.tool_settings.mesh_select_mode)
    picks = {}
    for ob in context.objects_in_mode_unique_data or ():
        if ob.type == 'MESH' and ob.data.is_editmode:
            picks[ob] = picked_faces(_bm(ob), mode)
    if not any(picks.values()):
        return False
    for ob, keep in picks.items():
        if not keep:
            try:
                ob.local_view_set(space, False)
            except RuntimeError:
                pass
            continue
        _apply(ob, _bm(ob), keep)
        _on[ob.name] = {"count": _face_count(ob), "keep": set(keep), "gone": 0}
    _ensure_timer()
    return True


def stop(names=None):
    """Leave component isolation for ``names`` (default: all): the faces the kit hid come back."""
    for name in list(_on if names is None else names):
        if _on.pop(name, None) is None:
            continue
        ob = bpy.data.objects.get(name)
        if ob is not None:
            try:
                _release(ob)
            except (ReferenceError, RuntimeError):
                pass


def edit(context, space, action):
    """Show > Isolate Select > Add / Remove Selected Objects while ``space`` isolates. Edit Mode: the faces of the
    selected components (Maya's rule) join / leave the set of their mesh; a mesh shown whole stays whole. Object
    Mode: the selected objects (with their children) join / leave the view; an object shown by its faces joins
    whole and is not taken out by Remove. Returns how many objects changed."""
    from . import dag
    changed = 0
    if context.mode == 'EDIT_MESH':
        mode = tuple(context.scene.tool_settings.mesh_select_mode)
        for ob in context.objects_in_mode_unique_data or ():
            if ob.type != 'MESH':
                continue
            bm = _bm(ob)
            faces = picked_faces(bm, mode)
            rec = _on.get(ob.name)
            if not faces:
                continue
            shown = in_view(ob, space)
            if rec is None and shown:
                continue                         # shown whole: adding / removing faces leaves it whole
            if rec is None:
                if action != 'ADD':
                    continue
                try:
                    ob.local_view_set(space, True)
                except RuntimeError:
                    continue
                keep = set(faces)
                _on[ob.name] = {"count": len(bm.faces), "keep": keep, "gone": 0}
            else:
                keep = rec["keep"] | faces if action == 'ADD' else rec["keep"] - faces
                rec["keep"], rec["count"] = keep, len(bm.faces)
            _apply(ob, bm, keep)
            changed += 1
        _ensure_timer()
        return changed
    picked = [ob for ob in dag.hierarchy(list(context.selected_objects))]
    for ob in picked:
        if action == 'ADD':
            if ob.name in _on:
                stop([ob.name])
                changed += 1
            if not in_view(ob, space):
                try:
                    ob.local_view_set(space, True)
                    changed += 1
                except RuntimeError:
                    pass
        elif ob.name not in _on and in_view(ob, space):
            try:
                ob.local_view_set(space, False)
                changed += 1
            except RuntimeError:
                pass
    return changed


def in_view(ob, space):
    try:
        return bool(ob.local_view_get(space))
    except RuntimeError:
        return False


# --- keep it right: views that stop isolating, undo / redo, loading ------------------------------------------------

def _isolating_views():
    wm = bpy.context.window_manager
    out = []
    for win in getattr(wm, "windows", ()):
        screen = win.screen
        for area in screen.areas if screen else ():
            if area.type == 'VIEW_3D':
                sp = area.spaces.active
                if sp is not None and sp.local_view is not None:
                    out.append(sp)
    return out


def _shown(ob, views):
    return any(in_view(ob, sp) for sp in views)


def _reapply(ob, rec, refresh=False):
    """The edited mesh hides what the set leaves out again when its hidden faces were lost (undo to a step made
    before Isolate Select, Edit Mode entered again); ``refresh`` (after undo / redo) also takes the set from a
    step made while isolating."""
    if ob.mode != 'EDIT' or not ob.data.is_editmode:
        return
    bm = bmesh.from_edit_mesh(ob.data)
    layer = bm.faces.layers.int.get(ATTR)
    if layer is not None:                      # made while isolating: that step hides the right faces
        if refresh:
            bm.faces.index_update()
            rec["keep"] = {f.index for f in bm.faces if not f[layer]}
            rec["count"] = len(bm.faces)
        return
    if len(bm.faces) == rec["count"]:
        bm.faces.index_update()
        _apply(ob, bm, rec["keep"])


def _check(refresh=False):
    """Faces come back for objects no view isolates any more; returns True while some stay isolated."""
    views = _isolating_views()
    for name in list(_on):
        rec = _on[name]
        ob = bpy.data.objects.get(name)
        if ob is None or not isinstance(getattr(ob, "data", None), bpy.types.Mesh):
            _on.pop(name, None)
            continue
        if _shown(ob, views):
            rec["gone"] = 0
            try:
                _reapply(ob, rec, refresh)
            except (ReferenceError, RuntimeError):
                pass
            continue
        rec["gone"] += 1
        if rec["gone"] >= _GRACE:
            stop([name])
    return bool(_on)


def _tick():
    try:
        return _TICK if _check() else None
    except Exception:          # restricted context while Blender quits
        return None


def _ensure_timer():
    if _on and not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=_TICK)


def _strays():
    """Meshes that carry the attribute although no isolation is on for their object: show those faces again."""
    seen = set()
    for ob in bpy.data.objects:
        me = getattr(ob, "data", None)
        if ob.name in _on or not isinstance(me, bpy.types.Mesh) or me.name in seen:
            continue
        seen.add(me.name)
        try:
            if ob.mode == 'EDIT' and me.is_editmode:
                if bmesh.from_edit_mesh(me).faces.layers.int.get(ATTR) is not None:
                    _release(ob)
            elif me.attributes.get(ATTR) is not None:
                _release_mesh(me)
        except (ReferenceError, RuntimeError):
            pass
    for me in bpy.data.meshes:
        if me.name not in seen and not me.is_editmode and me.attributes.get(ATTR) is not None:
            _release_mesh(me)


@persistent
def _on_undo(*_args):
    try:
        _check(refresh=True)
        _strays()
    except Exception:
        pass


@persistent
def _on_load(*_args):
    _on.clear()
    try:
        _strays()
    except Exception:
        pass


def _handlers():
    h = bpy.app.handlers
    return ((h.undo_post, _on_undo), (h.redo_post, _on_undo), (h.load_post, _on_load))


# --- Add / Remove Selected Objects ---------------------------------------------------------------------------------

class ALLSET_OT_isolate_edit(bpy.types.Operator):
    """Maya Show > Isolate Select > Add / Remove Selected Objects"""
    bl_idname = "allset.isolate_edit"
    bl_label = "Isolate Select Set"
    bl_options = {'REGISTER'}

    action: EnumProperty(items=(('ADD', "Add Selected Objects", ""), ('REMOVE', "Remove Selected Objects", "")),
                         name="Action", default='ADD', options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return {
            'ADD': "Show the selected objects (or the faces of the selected components) in this isolated view too",
            'REMOVE': "Hide the selected objects (or the faces of the selected components) in this isolated view",
        }[props.action]

    @classmethod
    def poll(cls, context):
        sp = context.space_data
        return sp is not None and sp.type == 'VIEW_3D' and sp.local_view is not None

    def execute(self, context):
        edit(context, context.space_data, self.action)
        if context.area is not None:
            context.area.tag_redraw()
        return {'FINISHED'}


classes = (ALLSET_OT_isolate_edit,)


def register():
    _on.clear()
    for lst, fn in _handlers():
        if fn not in lst:
            lst.append(fn)


def unregister():
    for lst, fn in _handlers():
        if fn in lst:
            lst.remove(fn)
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    try:
        stop()
    except Exception:          # restricted context while Blender quits
        _on.clear()
