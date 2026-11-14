# SPDX-License-Identifier: GPL-3.0-or-later
"""Joints in Maya display layers.

Maya: a joint picked in a view is a node of its own, so a display layer made from a picked joint holds that joint
only (one node, one layer: adding it to another layer moves it). The layer's state reaches everything below a member:
a hidden layer hides the member joint, every joint below it and the objects under them; Template draws them grey,
Reference black, and neither can be picked. The bone from the member's parent joint stays (a bone belongs to its
parent joint). A parent's Template or Reference wins over a child's Normal layer, and a hidden parent hides a child
whose own layer is visible. Skinned surfaces are not members and keep deforming. A joint's own Visibility works the
same way: off, it hides every joint and object below it, whose own Visibility stays as it was.

Here a joint's layer is ``PoseBone.allset_display_layer`` (the layer collection: a renamed joint or layer keeps it, a
duplicated skeleton copies it, undo takes it back, a deleted layer leaves None). A layer never writes the joint's own
flags (``PoseBone.hide`` is its Visibility channel): ``state(ob)`` = {joint name: HIDDEN / TEMPLATE / REFERENCE} of
every joint a layer reaches and every joint below a joint whose Visibility is off (a bone the panel Show > NURBS
Curves filter hid is no Visibility), kept per skeleton until a layer, a membership, a Visibility, the skeleton,
playback or undo changes it.
The kit's joint drawing, joint picking, Outliner rows and parent rule (``operators/dag.py``) read it; Blender's own
bone drawing (a view with the Bones overlay on) and Blender's bone operators don't know it.
"""

import types

import bpy
from bpy.app.handlers import persistent
from bpy.props import PointerProperty

from .. import depsgraph_filter

PROP = "allset_display_layer"
HIDDEN, TEMPLATE, REFERENCE = "HIDDEN", "TEMPLATE", "REFERENCE"
# drawn colour of a joint in a Template / Reference layer: grey and black lines, like Maya
COLOURS = {TEMPLATE: (0x78 / 255, 0x78 / 255, 0x78 / 255), REFERENCE: (0.0, 0.0, 0.0)}
_EMPTY = types.MappingProxyType({})
SHOW_FILTER = "allset_hidden_by_curves"   # ui/curve_controls.MARK: hidden by a Show filter, not by its Visibility
_REV = [0]          # bumped by every change that can change a skeleton's layer state
_STATES = {}        # skeleton object pointer -> (key, state)
_ROOTS = {}         # kit skeleton object pointer -> (key, first root joint name)
_PLAYING = [False]  # animation playback runs: a layer with Playback off hides its joints
_SIGS = {}          # skeleton object pointer -> ``_signature`` when its state was read
_SIG_DATA = {}      # skeleton object pointer -> its armature data pointer, for the skeletons in ``_SIGS``
# skeleton object / armature data pointers an update touched since their signature was last compared (a pose drag,
# a joint's Visibility set from Python: updates that only move skip the comparison)
_DIRTY = (set(), set())


# --- membership -----------------------------------------------------------------------------------------------------

def _on_set(_self, _context):
    bump()


def layer_of(pb):
    """The display layer (collection) joint ``pb`` belongs to, or None."""
    coll = getattr(pb, PROP, None)
    if coll is None:
        return None
    try:
        return coll if coll.allset_layer.is_layer else None
    except (ReferenceError, AttributeError):
        return None


def set_layer(pb, coll):
    """Put joint ``pb`` in layer ``coll`` (None: in no layer). A joint is in one layer at most, like Maya."""
    if getattr(pb, PROP, None) != coll:
        setattr(pb, PROP, coll)


def members(coll, scene):
    """{skeleton object: [joint names]} of layer ``coll`` among ``scene``'s objects, in bone order."""
    out = {}
    if not hasattr(bpy.types.PoseBone, PROP):
        return out
    for ob in scene.objects:
        if ob is None or ob.type != 'ARMATURE' or ob.pose is None:
            continue
        names = [pb.name for pb in ob.pose.bones if getattr(pb, PROP) == coll]
        if names:
            out[ob] = names
    return out


def has_members(scene):
    """Some joint of ``scene`` is in a display layer."""
    if not hasattr(bpy.types.PoseBone, PROP):
        return False
    return any(ob is not None and ob.type == 'ARMATURE' and ob.pose is not None
               and any(getattr(pb, PROP) is not None for pb in ob.pose.bones) for ob in scene.objects)


# --- state ----------------------------------------------------------------------------------------------------------

def bump(redraw=True):
    """A layer, a membership or a skeleton changed: every skeleton's state is read again at its next use."""
    _REV[0] += 1
    _STATES.clear()
    _ROOTS.clear()
    _SIGS.clear()
    _SIG_DATA.clear()
    _DIRTY[0].clear()
    _DIRTY[1].clear()
    try:
        from . import maya_joints
        maya_joints.changed()
    except (ImportError, AttributeError):
        pass
    if redraw:
        _redraw()


def _redraw():
    try:
        for w in bpy.context.window_manager.windows:
            for a in w.screen.areas:
                if a.type in {'VIEW_3D', 'OUTLINER'}:
                    a.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError):
        pass


def set_playing(on):
    if _PLAYING[0] != bool(on):
        _PLAYING[0] = bool(on)
        bump()


def _own_hidden(ob, bones, editing):
    """Joints whose own Visibility is off (Edit Mode: the edit bones' hide)."""
    import numpy as np
    seq = bones if editing else ob.pose.bones
    flags = np.zeros(len(seq), bool)
    seq.foreach_get("hide", flags)
    if not flags.any():
        return []
    return [b.name for i, b in enumerate(seq) if flags[i] and (editing or not b.get(SHOW_FILTER))]


def _object_kind(ob):
    """TEMPLATE / REFERENCE of the skeleton object itself: its own display layer (older files) or one above it."""
    from . import layer_editor
    try:
        scene = bpy.context.scene
        return ob.get(layer_editor.INHERITED) or (layer_editor.display_kind(ob, scene) if scene else None)
    except (AttributeError, ReferenceError):
        return None


def _children(bones):
    """{joint name: [child joint names]} of a skeleton, read in one pass over its bones (a bone's
    ``children_recursive`` walks every bone of the skeleton on each call)."""
    kids = {}
    for b in bones:
        p = b.parent
        if p is not None:
            kids.setdefault(p.name, []).append(b.name)
    return kids


def _below(name, kids):
    """``name`` and every joint below it, from a ``_children`` map."""
    out, stack = [name], [name]
    while stack:
        for child in kids.get(stack.pop(), ()):
            out.append(child)
            stack.append(child)
    return out


def _signature(ob):
    """What a depsgraph update can change of skeleton ``ob``'s state and first root without a kit call: its name
    (a kit skeleton is known by it), its joints (names, in order) and their own Visibility with its Show-filter mark
    (a membership, a layer and the skeleton's own type are set through the kit, which calls ``bump``)."""
    import numpy as np
    pbs = ob.pose.bones
    flags = np.zeros(len(pbs), bool)
    pbs.foreach_get("hide", flags)
    hidden = tuple(int(i) for i in np.flatnonzero(flags))
    return ob.name, tuple(pbs.keys()), hidden, tuple(bool(pbs[i].get(SHOW_FILTER)) for i in hidden)


def _compute(ob):
    pose = ob.pose
    if pose is None or not hasattr(bpy.types.PoseBone, PROP):
        return _EMPTY
    data = ob.data
    editing = data.is_editmode
    bones = data.edit_bones if editing else data.bones
    found = [(pb.name, coll) for pb in pose.bones if (coll := getattr(pb, PROP)) is not None]
    own = _own_hidden(ob, bones, editing)
    whole = _object_kind(ob)
    if not found and not own and whole is None:
        return _EMPTY
    playing = _PLAYING[0]
    ranked = []
    for name in own:
        b = bones.get(name)
        if b is not None:
            ranked.append((-1, name, b, True, None))      # a joint's own Visibility: it and everything below
    for name, coll in found:
        st = getattr(coll, "allset_layer", None)
        b = bones.get(name)
        if st is None or not st.is_layer or b is None:
            continue
        hidden = not st.visible or (playing and not st.playback)
        kind = st.display_type if st.display_type in COLOURS else None
        if not hidden and kind is None:
            continue
        depth, p = 0, b.parent
        while p is not None:
            depth, p = depth + 1, p.parent
        ranked.append((depth, name, b, hidden, kind))
    if not ranked and whole is None:
        return _EMPTY
    ranked.sort(key=lambda r: (r[0], r[1]))     # members nearer the root first: their Template / Reference wins
    out = {}
    if whole is not None:                       # the skeleton object is above every joint: its type wins
        out = {b.name: whole for b in bones}
    kids = _children(bones) if ranked else {}
    for _depth, name, b, hidden, kind in ranked:
        names = _below(name, kids)
        if hidden:
            for n in names:
                out[n] = HIDDEN
        else:
            for n in names:
                out.setdefault(n, kind)
    return out


def kind_under(ob):
    """TEMPLATE / REFERENCE of the joint object ``ob`` hangs from (``parent_joint``), else None."""
    name = parent_joint(ob)
    if name is None:
        return None
    kind = state(ob.parent).get(name)
    return kind if kind in COLOURS else None


def _key(ob):
    pose = ob.pose
    # Object and Pose Mode read the same bones (a click on a joint switches between them); Edit Mode its edit bones
    return ((_REV[0], ob.data.as_pointer(), ob.mode == 'EDIT', len(pose.bones) if pose is not None else 0),
            ob.as_pointer())


def _cached(store, ob, fn):
    try:
        key, ptr = _key(ob)
    except (ReferenceError, AttributeError):
        return None
    got = store.get(ptr)
    if got is not None and got[0] == key:
        return got[1]
    out = fn(ob)
    if len(store) > 64:
        store.clear()
    store[ptr] = (key, out)
    if ptr not in _SIGS and ob.pose is not None and not ob.data.is_editmode:
        if len(_SIGS) > 64:
            _SIGS.clear()
            _SIG_DATA.clear()
        _SIGS[ptr] = _signature(ob)
        _SIG_DATA[ptr] = ob.data.as_pointer()
    return out


def state(ob):
    """{joint name: HIDDEN / TEMPLATE / REFERENCE} of skeleton ``ob``: the joints its display layers reach (members
    and every joint below them). Empty for other objects and skeletons without such joints. Read only."""
    if ob is None or ob.type != 'ARMATURE':
        return _EMPTY
    out = _cached(_STATES, ob, _compute)
    return _EMPTY if out is None else out


def hidden(ob, name):
    """Joint ``name`` of skeleton ``ob`` is hidden by a display layer (its own or one above it)."""
    return state(ob).get(name) == HIDDEN


def pickable(ob, name):
    """No display layer keeps joint ``name`` of skeleton ``ob`` from being picked in a view (hidden, Template or
    Reference)."""
    return name not in state(ob)


def parent_joint(ob):
    """The joint whose layer state object ``ob`` follows: its parent bone, or for an object parented to a kit
    skeleton itself the skeleton's first root joint (where the kit Outliner lists it). None otherwise."""
    p = ob.parent
    if p is None or p.type != 'ARMATURE':
        return None
    if ob.parent_type == 'BONE':
        return ob.parent_bone or None
    if ob.parent_type != 'OBJECT' or not state(p):
        return None
    return _cached(_ROOTS, p, _first_root)


def _first_root(ob):
    from . import outliner_tree
    bones = outliner_tree._Bones(ob)
    return bones.roots[0] if outliner_tree.is_kit_skeleton(ob, bones) else None


def root_layer(ob):
    """The display layer of a kit skeleton's first root joint (the joint its object stands for), else None."""
    if ob is None or ob.type != 'ARMATURE' or ob.pose is None or not hasattr(bpy.types.PoseBone, PROP):
        return None
    root = _cached(_ROOTS, ob, _first_root)
    pb = ob.pose.bones.get(root) if root else None
    return layer_of(pb) if pb is not None else None


def hidden_under(ob):
    """Object ``ob`` hangs from a joint a display layer hides."""
    name = parent_joint(ob)
    return name is not None and hidden(ob.parent, name)


# --- handlers -------------------------------------------------------------------------------------------------------

def _same_skeletons(scene, obs):
    """Every skeleton whose state is kept and that an update touched since its last comparison (``_DIRTY``) reads
    the same as when it was read (``_signature``); the others weren't touched, so they read the same too. ``obs``:
    {pointer: skeleton object} of the current update; a touched skeleton it doesn't hold (touched by an earlier
    update that only moved) is looked up in the scene."""
    dirty_obs, dirty_data = _DIRTY
    want = {p for p in _SIGS if p in dirty_obs or _SIG_DATA.get(p) in dirty_data}
    if not want:
        return True
    try:
        found = [obs[p] for p in want if p in obs]
        if len(found) < len(want):
            missing = want.difference(obs)
            found += [ob for ob in scene.objects if ob.type == 'ARMATURE' and ob.as_pointer() in missing]
        for ob in found:
            if ob.data.is_editmode or _SIGS.get(ob.as_pointer()) != _signature(ob):
                return False
    except (ReferenceError, AttributeError, TypeError):
        return False
    return True


def _touched(look):
    """({pointer: skeleton object}, {armature data pointer}) of an update (``depsgraph_filter.Look``), and whether it
    holds an Armature in Edit Mode."""
    obs, data = {}, set()
    editing = False
    for id_, _moved in look.entries:
        if isinstance(id_, bpy.types.Armature):
            editing = editing or id_.is_editmode
            data.add(id_.original.as_pointer())
        elif isinstance(id_, bpy.types.Object) and id_.type == 'ARMATURE':
            ob = id_.original
            obs[ob.as_pointer()] = ob
    return obs, data, editing


@persistent
def _on_depsgraph(scene, depsgraph=None):
    """Skeleton changes other than motion: renamed, re-parented, added or removed joints / objects, a membership
    written; in Edit Mode every bone edit (a re-parented edit bone is a geometry update). A joint selection (a
    skeleton update that changes none of this) keeps the states. One pass over the update; only the skeletons it
    (or an earlier update that only moved) touched are compared."""
    if not _STATES and not _ROOTS:
        return
    try:
        if depsgraph is not None:
            look = depsgraph_filter.Look(depsgraph)
            if look.scene_only:
                return
            obs, data, editing = _touched(look)
            if editing:
                bump(redraw=False)
                return
            _DIRTY[0].update(obs)
            _DIRTY[1].update(data)
            if look.motion:
                return
            if not look.collection and scene is not None and _same_skeletons(scene, obs):
                _DIRTY[0].clear()
                _DIRTY[1].clear()
                return
    except (ReferenceError, AttributeError):
        pass
    bump(redraw=False)


@persistent
def _on_reload(*_args):
    bump()


def _handlers():
    h = bpy.app.handlers     # playback start / end: layer_editor.on_playback_pre / _post call set_playing
    return ((h.undo_post, _on_reload), (h.redo_post, _on_reload), (h.load_post, _on_reload))


def register():
    bpy.types.PoseBone.allset_display_layer = PointerProperty(type=bpy.types.Collection, update=_on_set,
                                                              options={'HIDDEN'})
    lst = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph not in lst:
        lst.insert(0, _on_depsgraph)       # before the parent rule (operators/dag.py) reads the state
    for lst, fn in _handlers():
        if fn not in lst:
            lst.append(fn)


def unregister():
    for lst, fn in ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph), *_handlers()):
        if fn in lst:
            lst.remove(fn)
    _STATES.clear()
    _ROOTS.clear()
    _SIGS.clear()
    _SIG_DATA.clear()
    _DIRTY[0].clear()
    _DIRTY[1].clear()
    _PLAYING[0] = False
    del bpy.types.PoseBone.allset_display_layer
