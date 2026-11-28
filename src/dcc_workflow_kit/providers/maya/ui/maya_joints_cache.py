# SPDX-License-Identifier: GPL-3.0-or-later
"""What changed since the joint lines were built: a generation per depsgraph update / new frame with the skeletons it
can have changed (``_note``, ``_since``, ``changed``), the builds kept per skeleton (``_Build``, ``_BUILDS``,
``_PARTS``, ``_PICK``, ``_JOINED``) and the checks that a joint list or pose reading is still the same.
Related: ``maya_joints`` (handlers, ``_joined``), ``maya_joints_pick``.
"""

import bpy

from .maya_joints_shapes import SHAPE_TYPES
from .maya_joints_views import _LAYER_GEN


_GEN = [0]          # one generation per update or new frame that can change a drawn joint (``_note``, ``changed``)
_EDITS = [0]    # bumped by every change that can change a skeleton's joint list (not by a new frame)
_WIDGETS = {}   # custom shape object session uid -> (its data pointer, its edges' end points in its own space)
_WIDGET_GEN = [0]   # bumped whenever a custom shape is read again (``_widget_plan`` joins them again)


def _drop_widget(uid):
    """Read custom shape ``uid``'s geometry again at its next use."""
    if _WIDGETS.pop(uid, None) is not None:
        _WIDGET_GEN[0] += 1


# --- what changed since the lines were built ------------------------------------------------------------------------
# Every depsgraph update and new frame gets a generation (``_GEN``) and a record of what it can have changed:
# ({skeleton pointer: level}, level of every skeleton or None, the Scene changed). Levels: 'pose' (its pose or place),
# 'light' (its pose, selection, mode, names, display type or shown bone collections: an update that changed none of
# its armature's pose or data), 'frame' (a new frame: its pose, and while nothing plays its joint list too), 'edit'
# (anything about it), 'new' (a control shape's own geometry: build it again from scratch). A generation without a
# record (``changed``, undo) counts as 'edit' for every skeleton.

_LEVELS = {None: 0, 'pose': 1, 'light': 2, 'frame': 3, 'edit': 4, 'new': 5}
_TOUCHED = {}       # generation -> record
_SKEL_EDITS = {}    # skeleton object pointer -> updates that could change its joint list ('edit', 'new')
_SKEL_LIGHT = {}    # skeleton object pointer -> 'light' updates (a selection, the active bone, Object / Pose Mode, ...)
_ALL_EDITS = [0]    # changes that could change every skeleton's joint list (``changed``, undo, load)
_DATA_USERS = {}    # armature data pointer -> pointers of the skeletons built from it
_SHAPE_USERS = {}   # custom shape object session uid -> pointers of the skeletons whose controls draw it
_SHAPE_PTRS = set()   # pointers of those custom shape objects


def _top(a, b):
    return a if _LEVELS[a] >= _LEVELS[b] else b


def _note(levels, every=None, scene=False):
    _GEN[0] += 1
    if len(_TOUCHED) > 256:
        _TOUCHED.clear()                   # no redraw consumed them: a missing record counts as everything
    _TOUCHED[_GEN[0]] = (levels, every, scene)


def edit_stamp(ob):
    """Changes when something may have changed skeleton ``ob``'s joints (not its pose), except a 'light' update
    (``light_stamp``): keys what is derived from them (``operators/joint_labels``)."""
    return _ALL_EDITS[0], _SKEL_EDITS.get(ob.as_pointer(), 0)


def light_stamp(ob):
    """Changes with every 'light' update of skeleton ``ob``: an update of its armature without a pose or data change
    (a selection, the active bone, a switch between Object and Pose Mode, a rename, a bone collection shown or
    hidden, a bone's own hide flag). What is derived from the joints checks the names and flags it reads."""
    return _SKEL_LIGHT.get(ob.as_pointer(), 0)


def _touched(depsgraph, updates=None):
    """({skeleton an update touched: 'light' / 'edit'}, the Scene changed, skeletons whose control shapes' own
    geometry it changed), or None when it can have changed anything (objects added, removed, linked: a Collection
    update). ``updates``: the update's entries when the caller has them (``update_summary``)."""
    touched, rebuilt, scene = {}, set(), False
    for u in (depsgraph.updates if updates is None else updates):
        id_ = u.id
        if isinstance(id_, bpy.types.Object):
            ob = id_.original
            if ob.type == 'ARMATURE':
                # a shading-only update (a material, the world, the object's colour or render visibility) changes no
                # joint; a selection, mode, pose or data change comes with other flags or none
                if not (u.is_updated_shading and not u.is_updated_transform and not u.is_updated_geometry):
                    ptr = ob.as_pointer()
                    touched[ptr] = _top(touched.get(ptr), 'light')
            elif u.is_updated_geometry:     # a control's custom shape is read again (a mesh the rig deforms isn't one)
                uid = ob.session_uid
                _drop_widget(uid)
                rebuilt |= _SHAPE_USERS.get(uid, set())
        elif isinstance(id_, bpy.types.Armature):
            # a pose, a joint's Visibility, a custom shape, a custom property: the armature updates with flags; a
            # selection, the active bone, a rename, the display type or a bone collection shown / hidden: without
            level = 'edit' if u.is_updated_transform or u.is_updated_geometry or u.is_updated_shading else 'light'
            for ptr in _DATA_USERS.get(id_.original.as_pointer(), ()):
                touched[ptr] = _top(touched.get(ptr), level)
        elif isinstance(id_, bpy.types.Scene):
            scene = True
        elif isinstance(id_, bpy.types.Collection):
            return None
        elif _WIDGETS:
            # other data: a custom shape's mesh / curve edited (also when the shape object isn't in the scene)
            ptr = id_.original.as_pointer()
            for uid in [uid for uid, got in _WIDGETS.items() if got[0] == ptr]:
                _drop_widget(uid)
                rebuilt |= _SHAPE_USERS.get(uid, set())
    return touched, scene, rebuilt


def _moved_skeletons(depsgraph, updates=None):
    """The skeletons a depsgraph update during a drag touched (those whose pose or place follows the dragged
    control: the dragged one, rigs constrained or parented to it), or None when it touched something else that can
    change drawn lines (a control shape's geometry, data that isn't an object). ``updates`` as in ``_touched``."""
    out = set()
    for u in (depsgraph.updates if updates is None else updates):
        id_ = u.id
        if isinstance(id_, bpy.types.Object):
            if id_.type == 'ARMATURE':
                out.add(id_.original.as_pointer())
                continue
            if id_.original.as_pointer() in _SHAPE_PTRS:
                return None
            continue                    # a mesh deformed by the rig, a prop: not drawn as a joint
        if isinstance(id_, bpy.types.Armature):
            continue                    # comes with its skeleton object
        return None
    return out


def _since(old, key):
    """What changed between the redraws keyed ``old`` and ``key`` (``_world_key``): ({skeleton pointer: level},
    level of every skeleton or None, the Scene changed, a new frame), or None when anything may have (another scene,
    view layer or Joint Tool state, or a generation without a record)."""
    if old is None or old[2:] != key[2:] or key[0] < old[0]:
        return None
    levels, every, scene = {}, None, False
    for gen in range(old[0] + 1, key[0] + 1):
        rec = _TOUCHED.get(gen)
        if rec is None:
            return None
        for p, level in rec[0].items():
            levels[p] = _top(levels.get(p), level)
        every = _top(every, rec[1])
        scene = scene or rec[2]
    return levels, every, scene, old[1] != key[1]


def changed(shapes=False):
    """Something that can change the drawn joints other than a new frame (a Radius typed, a label, a display layer,
    undo): every skeleton checks its joint list again. ``shapes``: the custom shapes' own geometry may have changed
    too (read them again); an edited shape's geometry otherwise reaches the kit as its own update."""
    _GEN[0] += 1
    _EDITS[0] += 1
    _ALL_EDITS[0] += 1
    _LAYER_GEN[0] += 1
    if shapes:
        _WIDGETS.clear()
        _WIDGET_GEN[0] += 1


_WORLD = [None]   # what the lines in _PARTS / _JOINED were built for: edit generation, frame, scene, view layer, ...
_PARTS = {}       # skeleton object pointer -> its ``_parts``
_PICK = {}        # skeleton object pointer -> the pick lines of its ``_parts`` (``_parts`` ``pick``) or None
_JOINED = {}      # (skeletons drawn, perspective) -> [points, colours, GPU batch or None, its ``_COLOURS`` entry],
                  # shared by the views
_BUILDS = {}      # skeleton object pointer -> its ``_Build`` (what its lines were built from)
_SCALE = [None]   # the scene's (Joint Size, radius unit) the builds used


def _world_key(scene, layer):
    from ..operators import joint_preview
    return (_GEN[0], scene.frame_current, scene.as_pointer(), layer.as_pointer(), joint_preview.running(),
            str(joint_preview.STATE.get("current")))


def _mark(dirt, playing):
    """Mark every kept build with what may have changed since it was built (``_since``)."""
    if dirt is None:
        for b in _BUILDS.values():
            b.level = _top(b.level, 'edit')
        return
    levels, every, scene, frame = dirt
    if scene:
        every = _top(every, 'pose')         # a selection / visibility: selections and places are checked
    if frame:
        every = _top(every, 'frame')
    if every == 'frame':
        every = 'pose' if playing else 'edit'        # a new frame without playback: as an edit (keyed Radius, ...)
    for ptr, b in list(_BUILDS.items()):
        level = _top(levels.get(ptr), every)
        if level == 'new':
            del _BUILDS[ptr]
            _PARTS.pop(ptr, None)
            _PICK.pop(ptr, None)
        elif level is not None:
            b.level = _top(b.level, level)


def _register(ob, b):
    """Remember which armature data and custom shapes the build ``b`` of skeleton ``ob`` reads (``_touched``)."""
    ptr = ob.as_pointer()
    _DATA_USERS.setdefault(ob.data.as_pointer(), set()).add(ptr)
    jl = b.registered = b.jl
    if jl is not None:
        for shape in jl.ctrl_shapes:
            _SHAPE_USERS.setdefault(shape.session_uid, set()).add(ptr)
            _SHAPE_PTRS.add(shape.as_pointer())


def _edit_signature(ob):
    """What skeleton ``ob``'s Edit Mode joints are drawn from that can change without an update reaching the kit:
    the edit bones' matrices, ends, sizes, flags and selection, names and order, Radius and Maya frame values, the
    visible bone collections, the active bone, the world matrix, the display type. (A re-parented bone or a bone
    collection assignment comes with an update.)"""
    import numpy as np
    from ..operators import joints
    data = ob.data
    ebs = data.edit_bones
    n = len(ebs)
    out = [data.display_type, tuple(ebs.keys()), ebs.active.name if ebs.active is not None else None,
           tuple(tuple(r) for r in ob.matrix_world)]
    for prop, size, dtype in (("matrix", 16, np.float32), ("head", 3, np.float32), ("tail", 3, np.float32),
                              ("bbone_x", 1, np.float32), ("bbone_z", 1, np.float32),
                              ("head_radius", 1, np.float32), ("tail_radius", 1, np.float32), ("hide", 1, bool),
                              ("select", 1, bool), ("select_head", 1, bool), ("select_tail", 1, bool)):
        a = np.empty(n * size, dtype)
        ebs.foreach_get(prop, a)
        out.append(a.tobytes())
    colls = data.collections_all
    out.append(tuple(c.is_visible_effectively for c in colls))
    if not all(out[-1]):                       # a hidden bone collection hides its bones: who is in one matters
        out.append(tuple(tuple(eb.collections.keys()) for eb in ebs))
    radius, frame = joints.RADIUS, joints.MAYA_FRAME
    out.append(tuple((eb.get(radius), tuple(q) if (q := eb.get(frame)) is not None else None) for eb in ebs))
    return out


class _Build:
    """What a view drew for one skeleton, kept between redraws: ``level`` says what may have changed since (None:
    nothing; 'pose': its pose; 'light': its pose, selection, names or shown bones; 'edit': anything; 'new': build it
    again from scratch)."""
    __slots__ = ("level", "key", "jl", "stamp", "raw", "lines", "sel", "rgba", "parts", "pick", "sig", "registered")

    def __init__(self):
        _forget_build(self)


def _forget_build(b):
    b.level, b.key, b.jl, b.stamp, b.raw, b.lines = 'new', None, None, None, None, None
    b.sel, b.rgba, b.parts, b.pick, b.sig, b.registered = None, None, None, None, None, None


def _build_key(ob, kind):
    """What a build of skeleton ``ob`` in Object / Pose Mode is for: its armature data, look and number of bones."""
    return ob.data.as_pointer(), kind, len(ob.pose.bones)


def _stamp(ob):
    """What of skeleton ``ob``'s joint list an update without a pose or data change can change (a rename, a bone
    collection shown or hidden, a joint's Visibility): its joints' names, hidden flags and shown bone collections."""
    import numpy as np
    pbs = ob.pose.bones
    hide = np.zeros(len(pbs), bool)
    pbs.foreach_get("hide", hide)
    return tuple(pbs.keys()), hide.tobytes(), tuple(c.is_visible_effectively for c in ob.data.collections_all)


def _same_list(a, b):
    """Joint lists ``a`` and ``b`` hold the same joints, hierarchy, Radius values, Maya frames, controls, display
    layer states and drawn bones (what a pose doesn't change is unchanged)."""
    import numpy as np
    if a.names != b.names or a.parent_names != b.parent_names:
        return False
    for x, y in ((a.rows, b.rows), (a.parents, b.parents), (a.raw, b.raw), (a.ctrl, b.ctrl), (a.ctrl_src, b.ctrl_src),
                 (a.ctrl_len, b.ctrl_len), (a.shown, b.shown), (a.bone_rows, b.bone_rows)):
        if not np.array_equal(x, y):
            return False
    if a.tint != b.tint or a.turned.keys() != b.turned.keys():
        return False
    if any(not np.array_equal(a.turned[j], b.turned[j]) for j in a.turned):
        return False
    try:
        return [s.as_pointer() for s in a.ctrl_shapes] == [s.as_pointer() for s in b.ctrl_shapes]
    except ReferenceError:                     # a shape object removed since ``a`` was read
        return False


def _same_raw(a, b):
    """Two ``_pose_raw`` readings are the same."""
    import numpy as np
    if a is None or b is None or a[3] != b[3] or (a[4] is None) != (b[4] is None):
        return False
    if not all(np.array_equal(x, y) for x, y in zip(a[:3], b[:3])):
        return False
    return a[4] is None or all(np.array_equal(x, y) for x, y in zip(a[4], b[4]))


def _moved_bones(raw, old_raw):
    """Bool per pose bone: its matrix or head reads differently (any bit) in pose reading ``raw`` than in
    ``old_raw``; None when something else the lines follow changed (the object's matrix, the joint size, a custom
    shape offset / turn / scale)."""
    import numpy as np
    if (old_raw is None or len(raw[1]) != len(old_raw[1]) or (raw[4] is None) != (old_raw[4] is None)
            or np.float64(raw[3]).tobytes() != np.float64(old_raw[3]).tobytes()
            or raw[2].tobytes() != old_raw[2].tobytes()):
        return None
    if raw[4] is not None and any(x.tobytes() != y.tobytes() for x, y in zip(raw[4], old_raw[4])):
        return None
    n = len(raw[1]) // 3
    return (np.any(raw[0].view(np.uint32).reshape(n, 16) != old_raw[0].view(np.uint32).reshape(n, 16), axis=1)
            | np.any(raw[1].view(np.uint32).reshape(n, 3) != old_raw[1].view(np.uint32).reshape(n, 3), axis=1))


def _lines_hold(g, jl, kind, raw, old_raw):
    """Lines ``g`` (built from ``jl`` and ``old_raw``) are still the lines of pose reading ``raw``: the same
    readings, the control shapes joined from the same, unchanged geometry and none of them changing with the frame,
    and a look built from the pose and the joint list alone (not Blender's B-Bone / Envelope shapes)."""
    if g is None or kind in SHAPE_TYPES or not _same_raw(raw, old_raw):
        return False
    if len(jl.ctrl):
        plan = jl.widgets
        if plan is None or plan is not g.plan or plan[4] != _WIDGET_GEN[0] or plan[3]:
            return False
    return True
