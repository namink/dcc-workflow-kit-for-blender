# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya DAG rules for a parent: what happens to a node's descendants.

Maya: a node is drawn only while it **and every ancestor** are visible —
hiding group1 (h, Ctrl+H, its Visibility channel, its display layer's V) hides pCube1 without touching pCube1's own
Visibility, and showing group1 again leaves a child that was hidden on its own hidden. Delete, Export Selection and
Isolate Select take the selected nodes with everything below them.

Blender: a parent's ``hide_viewport`` / ``hide_set`` never hides its children and
``object.delete`` leaves the children, unparented. So:

- ``sync``: an object whose ancestor is hidden (own Visibility = ``hide_viewport``, or its display layer's V; for an
  object under a joint also the joint's display layer, ``ui/layer_joints.py``) gets the view-layer flag
  (``hide_set``) marked ``MARK``; its own ``hide_viewport`` (Maya's Visibility channel) stays as it was. Objects the
  kit did not hide that way are never touched (a layer's or Blender's own ``hide_set`` stays). A display layer's
  Template / Reference reaches every object below a member the same way (Maya: isTemplated / the drawing override
  are inherited): such objects are marked ``layer_editor.INHERITED`` and drawn / locked like a member, the one
  nearest the root winning.
  Run right after kit visibility edits, and from a depsgraph handler (only writes on change, so it settles). The
  handler walks the scene again only when an update can change what it reads (``_what_changed``): a click that
  selects or changes modes leaves it at a look at the update's few entries.
- ``hierarchy``: the selection with all descendants, for Delete (``allset.delete``), Export Selection
  (``selected_hierarchy``) and Isolate Select (``allset.isolate``).
"""

import bpy
from bpy.app.handlers import persistent

from .. import depsgraph_filter

MARK = "allset_hidden_by_parent"
# a type filter of the panel Show menu hides only that node, never its children (ui/panel_menus.SHOW_HIDDEN)
SHOW_FILTER = "allset_hidden_by_show"


def _below(ob, kids):
    """``Object.children_recursive`` of ``ob`` (depth first, children in ``bpy.data.objects`` order) from the
    parent -> children map ``kids``, without recursion (any depth)."""
    out, stack = [], [iter(kids.get(ob, ()))]
    while stack:
        child = next(stack[-1], None)
        if child is None:
            stack.pop()
            continue
        out.append(child)
        stack.append(iter(kids.get(child, ())))
    return out


def hierarchy(objects):
    """``objects`` plus everything below them, each once, parents first. The parent -> children map is read once for
    all of them (``Object.children_recursive`` reads every object of the file on each call)."""
    objects = list(objects)
    kids = {}
    if objects:
        for child in bpy.data.objects:
            if (parent := child.parent) is not None:
                kids.setdefault(parent, []).append(child)
    out, seen = [], set()
    for ob in objects:
        for o in (ob, *_below(ob, kids)):
            if o.session_uid not in seen:
                seen.add(o.session_uid)
                out.append(o)
    return out


def _layer_hidden(ob, scene):
    from ..ui import layer_editor
    coll = layer_editor.layer_of(ob, scene)
    return coll is not None and not coll.allset_layer.visible


def hidden_self(ob, scene, view_layer=None):
    """Maya: the node's own visibility off, or its display layer hidden (the node's drawOverride). Blender's own
    eye / H hide (``hide_set``) doesn't count: in Blender it never hides the children, and files made in Blender use
    it on helper objects (a hair surface mesh, a rig) whose children must stay visible. The kit's own Hide keys
    (also in the Outliner) set Visibility."""
    return bool(ob.hide_viewport or _layer_hidden(ob, scene))


def hidden_by_ancestor(ob, scene, view_layer=None):
    from ..ui import layer_joints
    child, p = ob, ob.parent
    while p is not None:
        if hidden_self(p, scene, view_layer) or layer_joints.hidden_under(child):
            return True
        child, p = p, p.parent
    return False


class _Walk:
    """``hidden_by_ancestor`` / ``_layer_hidden`` for every object of one ``sync``: the display layers' members are
    read once and each object's answer is kept for the objects below it (a sync runs on every depsgraph update that
    isn't only motion, and walked every object's ancestors, listing the layers at each step)."""

    def __init__(self, scene):
        from ..ui import layer_editor, layer_joints
        self.hidden_under = layer_joints.hidden_under      # looked up once, not once per object
        self.first = {}                        # object name -> its display layer (the first that lists it)
        for coll in layer_editor.layers(scene):
            for o in coll.objects:
                self.first.setdefault(o.name, coll)
        self.memo = {}

    def layer_hidden(self, ob):
        coll = self.first.get(ob.name)
        return coll is not None and not coll.allset_layer.visible

    def by_ancestor(self, ob):
        hidden_under = self.hidden_under
        chain, got, o = [], False, ob
        while o.parent is not None:            # up to the root or to an object already answered
            known = self.memo.get(o.as_pointer())
            if known is not None:
                got = known
                break
            chain.append(o)
            o = o.parent
        for o in reversed(chain):              # then down: hidden above, or hidden by its parent / parent joint
            p = o.parent
            got = bool(got or p.hide_viewport or self.layer_hidden(p) or hidden_under(o))
            self.memo[o.as_pointer()] = got
        return got


def inherited_display(ob, scene, members=None):
    """TEMPLATE / REFERENCE that ``ob`` takes from a node above it: an ancestor object in such a display layer, or the
    joint it hangs from (``layer_joints.kind_under``); the one nearest the root wins. ``members`` = {object name:
    layer} (``layer_editor.layer_of`` when None)."""
    from ..ui import layer_editor, layer_joints
    kind = None
    child, p = ob, ob.parent
    while p is not None:
        joint = layer_joints.kind_under(child)
        if joint is not None:
            kind = joint
        coll = members.get(p.name) if members is not None else layer_editor.layer_of(p, scene)
        own = coll.allset_layer.display_type if coll is not None else "NORMAL"
        if own != "NORMAL":
            kind = own
        child, p = p, p.parent
    return kind


def sync_display(scene, marked=None):
    """Template / Reference inherited from a layer above (``INHERITED``), only written on change. Returns the number
    of changes. ``marked``: the objects of ``scene`` that carry ``INHERITED`` (None: look at every object); while no
    layer is Template / Reference only they can change."""
    from ..ui import layer_editor, layer_joints
    ls = layer_editor.layers(scene)
    active = any(c.allset_layer.display_type != "NORMAL" for c in ls)
    members = {o.name: c for c in ls for o in c.objects} if active else {}
    changed, skeletons = 0, False
    for ob in (scene.objects if active or marked is None else marked):
        mark = ob.get(layer_editor.INHERITED)
        if not active and mark is None:
            continue
        kind = inherited_display(ob, scene, members) if active else None
        if kind != mark:
            if kind is None:
                del ob[layer_editor.INHERITED]
            else:
                ob[layer_editor.INHERITED] = kind
            coll = members.get(ob.name)
            own = coll.allset_layer.display_type if coll is not None else "NORMAL"
            layer_editor.apply_display(ob, kind or (None if own == "NORMAL" else own))
            changed += 1
            skeletons = skeletons or ob.type == 'ARMATURE'
    if skeletons:
        layer_joints.bump()        # the joints of a skeleton below a Template / Reference node take it too
    return changed


def sync(scene=None, view_layer=None):
    """Hide / show descendants of hidden nodes (view-layer flag + ``MARK``), then the inherited Template / Reference
    (``sync_display``). Returns the number of changes."""
    scene = scene or bpy.context.scene
    if scene is None:
        return 0
    view_layer = view_layer or bpy.context.view_layer
    if view_layer is None:
        return 0
    key = (scene.as_pointer(), view_layer.as_pointer())
    _SEEN.pop(key, None)              # a sync that stops half way leaves nothing to skip by
    rev = _joint_rev()                # the joint layer states this walk reads
    from ..ui import layer_editor
    inherited_key = layer_editor.INHERITED
    changed = 0
    walk = _Walk(scene)
    parents, marked, inherited = {}, [], []
    for ob in scene.objects:
        if inherited_key in ob:
            inherited.append(ob)
        p = ob.parent
        if p is None:                 # a root: nothing above it can hide it
            if MARK not in ob:
                continue
            by_parent = False
        else:
            parents[ob.as_pointer()] = (p.as_pointer(), ob.parent_type, ob.parent_bone, ob.name)
            by_parent = walk.by_ancestor(ob)
            if not by_parent and MARK not in ob:
                continue
        want = by_parent or walk.layer_hidden(ob)
        try:
            if ob.hide_get(view_layer=view_layer) != want:
                ob.hide_set(want, view_layer=view_layer)
                changed += 1
        except RuntimeError:          # not in this view layer
            continue
        if by_parent:
            if MARK not in ob:
                ob[MARK] = True
            marked.append((ob.name, ob.session_uid))
        elif MARK in ob:
            del ob[MARK]
    changed += sync_display(scene, inherited)
    if len(_SEEN) > 16:
        _SEEN.clear()
    _SEEN[key] = (rev, parents, marked)
    return changed


# --- the handler: walk again only when an update can change the answer ---------------------------------------------
# What a sync reads and the depsgraph update each edit of it makes (Blender 5.2, ``depsgraph_filter``):
# - an object's parent (pointer, type, bone) or a child's name: the object's own entry (Python, Ctrl+P, Alt+P,
#   rename);
# - an object's own Visibility (``hide_viewport``), a link / unlink / add / delete, a display layer's members:
#   Collection entries;
# - a display layer's Visible / Template / Reference: the layer's update calls ``sync`` itself;
# - a joint's display layer or Visibility, a renamed or re-parented joint (objects under joints): ``layer_joints``
#   bumps its revision (its handler runs first);
# - Blender's eye / H (``hide_set``) on an object the parent rule hides: the Scene alone.
# A selection, an active object, a mode switch, a joint selection, a custom property, a material, a key are none of
# these: their updates hold the Scene, the objects with the same parents, and other data. Undo, redo and a file load
# start over.

_SEEN = {}          # (scene, view layer) pointers -> (joint revision, {child pointer: parent facts},
#                     [(name, session uid) of the objects it marked])
_FULL, _MARKED = "FULL", "MARKED"
_FEW_MARKED = 4     # up to this many marked objects are found by name; more: one pass over the scene


def _joint_rev():
    from ..ui import layer_joints
    rev = getattr(layer_joints, "_REV", None)
    return rev[0] if rev else None


def _what_changed(scene, view_layer, depsgraph):
    """``_FULL``: walk the scene again; ``_MARKED``: only the objects the last walk hid (Blender's eye / H may have
    shown one); None: nothing a sync reads changed. Reads only the update's entries."""
    if depsgraph is None or scene is None or view_layer is None:
        return _FULL
    seen = _SEEN.get((scene.as_pointer(), view_layer.as_pointer()))
    if seen is None:
        return _FULL
    rev, parents, _marked = seen
    if rev is None or rev != _joint_rev():
        return _FULL
    scene_entry = False
    for u in depsgraph.updates:
        id_ = u.id
        if isinstance(id_, bpy.types.Object):
            ob = id_.original
            p = ob.parent
            facts = 0 if p is None else (p.as_pointer(), ob.parent_type, ob.parent_bone, ob.name)
            if parents.get(ob.as_pointer(), 0) != facts:
                return _FULL
        elif isinstance(id_, bpy.types.Collection):
            return _FULL
        elif isinstance(id_, bpy.types.Scene):
            scene_entry = True
    return _MARKED if scene_entry else None


def _keep_marked_hidden(scene, view_layer):
    """Hide again what the last sync hid under a hidden node and was shown since (only ``hide_set`` changed: a
    Scene-only update). Returns the number of changes."""
    seen = _SEEN.get((scene.as_pointer(), view_layer.as_pointer()))
    if seen is None or not seen[2]:
        return 0
    marked = seen[2]
    found = None
    if len(marked) <= _FEW_MARKED:
        found = [bpy.data.objects.get(name) for name, _uid in marked]
        if any(ob is None or ob.session_uid != uid for ob, (_name, uid) in zip(found, marked)):
            found = None              # renamed, or a linked object of the same name: look at every object instead
    if found is None:
        found = (ob for ob in scene.objects if MARK in ob)
    changed = 0
    for ob in found:
        if ob is None or MARK not in ob:
            continue
        try:
            if not ob.hide_get(view_layer=view_layer):
                ob.hide_set(True, view_layer=view_layer)
                changed += 1
        except RuntimeError:          # not in this view layer
            continue
    return changed


_busy = []


@persistent
def _on_depsgraph(scene, _depsgraph=None):
    # #191: visibility only changes with a hide, a parent change or a new / removed node — never with a
    # move or a mesh edit; a sync walks every object's ancestors, so it runs only when the update can change them
    if _busy or depsgraph_filter.only_motion(_depsgraph):
        return
    _busy.append(True)
    try:
        view_layer = bpy.context.view_layer
        try:
            what = _what_changed(scene, view_layer, _depsgraph)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            what = _FULL
        if what == _FULL:
            sync(scene)
        elif what == _MARKED:
            _keep_marked_hidden(scene, view_layer)
    except Exception:          # never break the depsgraph update
        pass
    finally:
        _busy.clear()


@persistent
def _on_undo(*_args):
    _SEEN.clear()               # objects, parents and marks are the undone step's: the next update walks again


@persistent
def _on_load(*_args):
    _SEEN.clear()
    for scene in bpy.data.scenes:
        for vl in scene.view_layers:
            try:
                sync(scene, vl)
            except Exception:
                pass


# --- Delete / Export Selection / Isolate with the hierarchy -----------------------------------------------------

def delete_hierarchy(context, objects):
    """Maya delete of transforms: the nodes and every descendant, with their now unused data. Returns the count."""
    from . import constrain_199, startup_cameras
    # Maya refuses to delete its startup cameras ("Non-deletable node 'persp' cannot be deleted.")
    obs = [ob for ob in hierarchy(objects) if not startup_cameras.is_startup(ob)]
    # Maya's normal / tangent constraint node is a child of the constrained object: its kit helper empty goes too
    # (#109; the helper has no parent — constrain_199.update clears it — so hierarchy() misses it)
    helpers = [h for h in constrain_199.helpers_owned_by(obs) if h not in obs]
    from . import ik_rp
    poles = ik_rp.helpers_of(obs)          # a kit RP handle's pole helper goes with the handle
    from . import spline_twist
    spline_twist.release(obs)              # a kit Spline IK handle takes its twist drivers and constraint
    from . import sweep_mesh
    sweep_mesh.release(context, obs)       # a deleted curve leaves its sweeps as plain meshes, like Maya
    datas = {ob.data for ob in obs if ob.data is not None}
    inputs = bool_inputs_of(obs)           # a Boolean result's hidden inputs go with it, like Maya
    n = len(obs)
    for ob in reversed(obs):              # children first
        bpy.data.objects.remove(ob, do_unlink=True)
    drop_bool_inputs(inputs)
    constrain_199.remove_helpers(helpers)
    ik_rp.drop_orphan_rotations()          # its 3+ bone chain's Copy Rotations and bone helpers too
    for h in poles:
        try:
            bpy.data.objects.remove(h, do_unlink=True)
        except ReferenceError:
            pass
    for data in datas:
        try:
            if data.users == 0:
                getattr(bpy.data, _DATA_COLLECTION.get(type(data).__name__, ""), None).remove(data)
        except (AttributeError, ReferenceError, RuntimeError):
            pass
    return n


_DATA_COLLECTION = {"Mesh": "meshes", "Curve": "curves", "SurfaceCurve": "curves", "TextCurve": "curves",
                    "Lattice": "lattices", "Armature": "armatures", "Camera": "cameras", "Light": "lights",
                    "SpotLight": "lights", "PointLight": "lights", "SunLight": "lights", "AreaLight": "lights",
                    "MetaBall": "metaballs", "GreasePencil": "grease_pencils"}


class selected_hierarchy:
    """``with selected_hierarchy(context):`` the descendants of the selection are selected too (Maya Export
    Selection), and the selection is put back afterwards."""

    def __init__(self, context):
        self.context = context
        self.added = []

    def __enter__(self):
        sel = list(self.context.selected_objects)
        for ob in hierarchy(sel):
            if not ob.select_get():
                try:
                    ob.select_set(True)
                    self.added.append(ob)
                except RuntimeError:      # hidden / not in the view layer
                    pass
        return self

    def __exit__(self, *_exc):
        for ob in self.added:
            try:
                ob.select_set(False)
            except (RuntimeError, ReferenceError):
                pass
        return False


def bool_inputs_of(objects):
    """The kit Boolean inputs (history) that ``objects`` keep and that are not among them."""
    from . import mesh_maya
    keep = {ob.session_uid for ob in objects}
    return [i for ob in objects for i in mesh_maya.bool_inputs(ob) if i.session_uid not in keep]


def drop_bool_inputs(inputs):
    """Delete Boolean inputs whose result is gone (with the inputs they keep themselves); an input another
    object still uses stays."""
    from . import mesh_maya
    for ob in inputs:
        try:
            if ob.name not in bpy.data.objects or mesh_maya.bool_users(ob):
                continue
        except ReferenceError:            # already removed with an earlier input
            continue
        mesh_maya.delete_bool_input(ob)


class ALLSET_OT_delete(bpy.types.Operator):
    """Delete the selected objects and everything below them (Maya Edit > Delete)"""
    bl_idname = "allset.delete"
    bl_label = "Delete"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def execute(self, context):
        from . import startup_cameras
        for ob in context.selected_objects:
            if startup_cameras.is_startup(ob):
                self.report({'WARNING'}, f"Non-deletable node '{ob.name}' cannot be deleted.")
        delete_hierarchy(context, list(context.selected_objects))
        return {'FINISHED'}


class ALLSET_OT_isolate(bpy.types.Operator):
    """Isolate Select: show only the selected objects and everything below them (Maya Ctrl+1); again = back"""
    bl_idname = "allset.isolate"
    bl_label = "Isolate Select"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        space = context.space_data
        if space.local_view is not None:
            return bpy.ops.view3d.localview(frame_selected=False)
        with selected_hierarchy(context):
            return bpy.ops.view3d.localview(frame_selected=False)


class ALLSET_OT_outliner_delete(bpy.types.Operator):
    """Delete the selected objects and everything below them (Maya Edit > Delete)"""
    bl_idname = "allset.outliner_delete"
    bl_label = "Delete"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'OUTLINER'

    def execute(self, context):
        picked = [i for i in getattr(context, "selected_ids", ()) or () if isinstance(i, bpy.types.Object)]
        inputs = bool_inputs_of(hierarchy(picked))
        result = bpy.ops.outliner.delete(hierarchy=True)
        if 'FINISHED' not in result:
            return result
        drop_bool_inputs(inputs)
        return {'FINISHED'}


classes = (ALLSET_OT_delete, ALLSET_OT_outliner_delete, ALLSET_OT_isolate)


def _handlers():
    h = bpy.app.handlers
    return ((h.depsgraph_update_post, _on_depsgraph), (h.load_post, _on_load), (h.undo_post, _on_undo),
            (h.redo_post, _on_undo))


def register_handlers():
    _SEEN.clear()                   # while the handlers were off nothing was followed
    for lst, fn in _handlers():
        if fn not in lst:
            lst.append(fn)


def release_all():
    """Disable: show again what only the kit's parent rule hid and give inherited Template / Reference objects their
    own display (the objects' own flags stay)."""
    from ..ui import layer_editor
    for scene in bpy.data.scenes:
        for ob in scene.objects:
            if layer_editor.INHERITED in ob:
                del ob[layer_editor.INHERITED]
                try:
                    layer_editor.apply_display(ob, layer_editor.display_kind(ob, scene))
                except (AttributeError, ReferenceError):       # the layer settings are gone already
                    layer_editor._restore_display(ob)
            if MARK not in ob:
                continue
            for vl in scene.view_layers:
                try:
                    if not _layer_hidden(ob, scene):
                        ob.hide_set(False, view_layer=vl)
                except RuntimeError:
                    pass
            del ob[MARK]


def unregister_handlers():
    for lst, fn in _handlers():
        if fn in lst:
            lst.remove(fn)
    _SEEN.clear()
    try:
        release_all()
    except Exception:          # restricted context while Blender quits
        pass
