# SPDX-License-Identifier: GPL-3.0-or-later
"""Joints drawn like Maya's in the Maya layout's 3D Views, in place of Blender's bone shapes.

Maya draws a joint as a wire sphere of three great circles in the joint's local XY, YZ and XZ planes, never filled,
1 px lines, at pure world size: the drawn radius is half the joint's Radius times the scene's Joint Size, with no
screen-size limit. Between a joint and each child it draws a wire four-sided pyramid: the square base stands across
the bone on the parent's sphere, turned with the parent's axes, its corners on that sphere; the apex touches the
child's sphere. A joint without children draws no bone.

Colours follow the selection: unselected joints dark violet, selected ones white, the lead (last selected) green; a
joint below a selected one takes that joint's colour, and a bone takes its parent joint's colour. A joint in a Template
display layer draws grey and in a Reference layer black (unless it is selected itself); a joint a display layer hides,
or one below a joint whose Visibility is off, is not drawn, but the bone from its shown parent joint stays (it belongs
to the parent). Joints a layer hides or makes Template / Reference, and joints Blender can't select, are never picked.
Selected joints in a perspective view also show short local axes (X red, Y green, Z blue). A shaded surface hides the
joints behind or inside it; X-Ray Joints, X-Ray and wireframe views draw them through every surface.

Here a skeleton's joints are its bones' heads (pose positions in Object / Pose Mode, edit bones in Edit Mode); in
Object Mode a selected skeleton object counts as its root joints selected. Bones with a custom shape draw that shape
instead. The skeleton's Blender display type picks the look: Octahedral (Blender's default for a new skeleton) draws
Maya joints; Stick or Wire one line per bone and no spheres; B-Bone a wire box per bone (per segment, following the
curve) and Envelope the wire head and tail spheres joined along the bone, both in the joint colours. The kit draws
only in 3D Views of the Maya layout's workspaces where Blender's Bones overlay is off — the kit turns it off once per
screen; a view whose Bones overlay is turned back on shows Blender's bones and no kit joints.

The parts live in their own modules: ``maya_joints_views`` (which views draw), ``maya_joints_shapes`` (one joint's
shapes and colours), ``maya_joints_arrays`` (all joints at once in arrays), ``maya_joints_cache`` (what changed since
the lines were built) and ``maya_joints_pick`` (picking drawn joints); every name of theirs is importable from here
too. This module keeps the build chain, the click entry points, the handlers and the draw together: tests replace or
count functions here (``_parts``, ``skeleton``, ``transforming``, ``region_pick`` ...), and a replaced function is
only seen by callers that look it up in this module.
"""

import math

import bpy
from mathutils import Quaternion

from .maya_joints_views import (armatures, _ARMS, is_maya_view, _LAYER_GEN, maya_workspace, release_all, see_through,
                                settle, SETTLED, _view_skeletons)  # noqa: F401
from .maya_joints_shapes import (AXIS_COLORS, bbone_lines, bone_lines, _box_lines, _coll_hidden, colours, _COS,
                                 drawn_radius, envelope_lines, _HIDDEN, Joint, joint_segments, LEAD, _maya_q,
                                 MAYA_RADIUS, own_shape_lines, _radius_scale, SEGMENTS, SELECTED, selection,
                                 shape_lines, _shape_matrix, SHAPE_TYPES, _shown, _SIN, sphere_lines, STICK_TYPES,
                                 UNSELECTED)  # noqa: F401
from .maya_joints_arrays import (_BONE_INDEX, _bone_index, _bone_rows, _BONE_SEGMENTS, _box_array, _COLOURS,
                                 _control_placement, _control_points, _distinct_points, _euler_xyz,
                                 _FORMATS, _join, _join_view, joined_segments, _joint_rgba, _joint_selection,
                                 JointList, _Lines, _owner, _paint, _part_arrays, placed_points, _pose_raw,
                                 _pose_read, _RING, _RING_INDEX, _segments, shape_moves, _sphere_index, _sphere_owner,
                                 _STILL_MODIFIERS, _vertex_buffer)  # noqa: F401
from .maya_joints_cache import (_ALL_EDITS, _Build, _build_key, _BUILDS, changed, _DATA_USERS, _drop_widget,
                                _edit_signature, edit_stamp, _EDITS, _forget_build, _GEN, _JOINED, _LEVELS, light_stamp,
                                _lines_hold, _mark, _moved_bones, _moved_skeletons, _note, _PARTS, _PICK, _register,
                                _same_list, _same_raw, _SCALE, _SHAPE_PTRS, _SHAPE_USERS, _since, _SKEL_EDITS,
                                _SKEL_LIGHT, _stamp, _top, _TOUCHED, _touched, _WIDGET_GEN, _WIDGETS, _WORLD,
                                _world_key)  # noqa: F401
from .maya_joints_pick import (_box_bounds, _DEPTHS, _drawn_pick_lines, _in_poly, _NEAREST, _nearest, _pick_current,
                               _PICK_MEMO, pick_memo, _PICK_PLAN, _pick_plan, _region_depths, _screen, _seg_cross,
                               _segment_columns, _segment_distances, segments_touch, _touching,
                               _unpickable)  # noqa: F401

from .. import update_summary

LINE_PX = 1.0

_handle = []
_CACHE = {}         # space pointer -> (key, points, colours)


# --- which views ------------------------------------------------------------------------------------------------

def _tick():
    try:
        for window in bpy.context.window_manager.windows:
            settle(window)
    except (ReferenceError, AttributeError, RuntimeError):
        pass
    return 0.5


# --- joints ------------------------------------------------------------------------------------------------------

def skeleton(ob, scene):
    """{name: Joint} of armature object ``ob`` in world space: the joints not hidden by their own flags, with their
    display layer state (a joint a layer hides is kept for its parent's bone, ``joint_segments`` draws nothing for
    it)."""
    from ..operators import joint_display, joints
    from ..operators.joint_edit import local_frame
    from . import layer_joints
    layered = layer_joints.state(ob)
    mw = ob.matrix_world
    m3 = mw.to_3x3()
    s = joint_display.skeleton_scale(ob)
    scale = _radius_scale(scene)
    out = {}
    if ob.mode == 'EDIT':
        for eb in ob.data.edit_bones:
            if eb.hide or _coll_hidden(eb):
                continue
            frame = (m3 @ local_frame(eb)).normalized()
            out[eb.name] = Joint(eb.name, eb.parent.name if eb.parent else None, mw @ eb.head, frame,
                                 drawn_radius(eb, scene, s, scale), state=layered.get(eb.name))
    else:
        shown = _shown(ob)
        for i, pb in enumerate(ob.pose.bones):
            if not shown[i]:
                continue
            bone = pb.bone
            f = m3 @ pb.matrix.to_3x3() @ joints.JOINT_AXES
            q = _maya_q(bone)
            frame = (f @ q if q is not None else f).normalized()
            shape = None
            if pb.custom_shape is not None:
                shape = (pb.custom_shape, mw @ _shape_matrix(pb))
            out[pb.name] = Joint(pb.name, bone.parent.name if bone.parent else None, mw @ pb.head, frame,
                                 drawn_radius(bone, scene, s, scale), shape, layered.get(pb.name))
    for j in out.values():
        if j.parent in out:
            out[j.parent].children.append(j.name)
    return out


def depth(js, name):
    n, p = 0, js[name].parent
    while p in js:
        n, p = n + 1, js[p].parent
    return n


def _shape_points(shape, matrix, depsgraph):
    """``shape_lines`` as one (2E, 3) array, from the edges read once per shape (``_widget_segments``)."""
    import numpy as np
    segs, _moves = _widget_segments(shape, depsgraph)
    if not len(segs):
        return np.zeros((0, 3))
    m = np.array(matrix, np.float64)
    return segs @ m[:3, :3].T + m[:3, 3]


def _pick_lines(context, ob, js):
    """(joint names, (S, 2) screen start points, end points, in-front mask, owner index per segment) of every joint of
    ``js`` that can be picked: the lines ``joint_segments`` draws for each (sphere and bones to its children, or its
    custom shape), built for all joints at once."""
    import numpy as np
    from ..operators.preselect import project
    dg = context.evaluated_depsgraph_get()
    skip = _unpickable(ob, js)
    names = [n for n in js if n not in skip and js[n].state != _HIDDEN]
    plain = [n for n in names if js[n].shape is None]
    rings = {}
    if plain:
        c = np.array([tuple(js[n].centre) for n in plain], np.float64)
        f = np.array([[tuple(r) for r in js[n].frame] for n in plain], np.float64)
        r = np.array([js[n].radius for n in plain], np.float64)
        rings = dict(zip(plain, _spheres(c, f, r).reshape(len(plain), -1, 3)))
    kept, chunks = [], []
    for n in names:
        j = js[n]
        if j.shape is not None:
            pts = _shape_points(j.shape[0], j.shape[1], dg)
        else:
            pts = rings[n]
            more = [tuple(p) for cn in j.children if js[cn].shape is None for p in bone_lines(j, js[cn])]
            if more:
                pts = np.vstack((pts, np.array(more, np.float32)))
        if len(pts):
            kept.append(n)
            chunks.append(np.asarray(pts, np.float64).reshape(-1, 3))
    if not kept:
        return kept, np.zeros((0, 2)), np.zeros((0, 2)), np.zeros(0, bool), np.zeros(0, np.int64)
    owner = np.repeat(np.arange(len(kept)), [len(p) // 2 for p in chunks])
    region, rv3d = context.region, context.region_data
    xy, front = project(np.concatenate(chunks), rv3d.perspective_matrix, region.width, region.height)
    return kept, xy[0::2], xy[1::2], front[0::2] & front[1::2], owner


def screen_distance(context, ob, mouse):
    """{joint: screen distance from ``mouse`` to its drawn lines} of armature ``ob``, for the joints that can be
    picked."""
    memo = _PICK_MEMO[0]
    key = None
    if memo is not None:
        key = (ob.as_pointer(), ob.mode, context.region.as_pointer(), float(mouse[0]), float(mouse[1]))
        got = memo.get(key)
        if got is not None:
            return dict(got)
    out = _screen_distance(context, ob, mouse)
    if key is not None:
        memo[key] = dict(out)
    return out


def _screen_distance(context, ob, mouse):
    import numpy as np
    got = _drawn_pick_lines(context, ob)
    names, a, b, ok, owner = got[:5] if got is not None else _pick_lines(context, ob, skeleton(ob, context.scene))
    if not names:
        return {}
    held = _PICK_PLAN.get(ob.as_pointer()) if got is not None else None
    plan = held[1] if held is not None else None
    if plan is not None and plan.get("a") is a:      # the drawn lines in this view: their columns are kept
        if plan.get("columns") is None:
            plan["columns"] = _segment_columns(a, b)
        columns = plan["columns"]
    else:
        columns = _segment_columns(a, b)
    near = _nearest(owner, len(names), _segment_distances(mouse, columns), ok)
    found = np.flatnonzero(np.isfinite(near))
    return dict(zip([names[i] for i in found.tolist()], near[found].tolist()))


def pick(context, ob, mouse, radius):
    """The joint of ``ob`` whose drawn line is nearest to ``mouse`` within ``radius`` px (Maya: a click hits the wire,
    not the inside of the sphere; a bone hit picks its parent joint), or None."""
    d = screen_distance(context, ob, mouse)
    near = [(v, n) for n, v in d.items() if v <= radius]
    return min(near)[1] if near else None


def region_pick(context, ob, poly):
    """Maya marquee / lasso on a skeleton: the bones whose drawn lines touch ``poly``. Maya joints keep the one
    closest to the root (a box around a whole chain selects its top joint); controls (bones with a custom shape)
    and bones of a skeleton not drawn as Maya joints are each picked, like Maya's curve controls. Joints that can't be
    picked (``_unpickable``) are left out. Returns names."""
    import numpy as np
    maya_drawn = getattr(ob.data, "display_type", 'OCTAHEDRAL') not in STICK_TYPES | SHAPE_TYPES
    got = _drawn_pick_lines(context, ob)
    if got is not None:                        # the drawn lines (``_joined``); a joint list's joints have no shape
        names, a, b, ok, owner, jl = got
        js = jl.js
        control = {jl.names[j] for j in jl.ctrl}
    else:
        js = skeleton(ob, context.scene)
        names, a, b, ok, owner = _pick_lines(context, ob, js)
        control = {n for n, j in js.items() if j.shape is not None}
    joints, each = [], []
    if not names:
        return each
    hit = np.zeros(len(names), bool)
    use = np.flatnonzero(ok)
    hit[owner[use[_touching(a[use], b[use], poly)]]] = True
    for i in np.flatnonzero(hit).tolist():
        n = names[i]
        if maya_drawn and n not in control:
            joints.append(n)
        else:
            each.append(n)
    if not joints:
        return each
    depths, index = _region_depths(js)
    return each + [min((depths[n], index[n], n) for n in joints)[2]]


def _sphere_array(js):
    """(points, joint order) of every sphere's three great circles as one float32 array of segment end points."""
    import numpy as np
    order = [n for n, j in js.items() if j.shape is None and j.state != _HIDDEN]
    if not order:
        return np.zeros((0, 3), np.float32), order
    c = np.array([tuple(js[n].centre) for n in order], np.float64)                  # (N, 3)
    f = np.array([[tuple(r) for r in js[n].frame] for n in order], np.float64)      # (N, 3, 3) rows
    r = np.array([js[n].radius for n in order], np.float64)
    return _spheres(c, f, r), order


def _spheres(c, f, r):
    """Segment end points (float32) of the three great circles of spheres at centres ``c`` (N, 3) with frames ``f``
    (N, 3, 3; columns = the joint's X, Y, Z) and radii ``r`` (N,): per joint, circle and segment its two ends."""
    import numpy as np
    if not len(c):
        return np.zeros((0, 3), np.float32)
    return _sphere_ring(c, f, r)[_sphere_index(len(c))]


def _sphere_ring(c, f, r):
    """The ring points (float32) of the three great circles of spheres at centres ``c`` (N, 3) with frames ``f``
    (N, 3, 3; columns = the joint's X, Y, Z) and radii ``r`` (N,), each point once: (3 * (SEGMENTS + 1) * N, 3) in
    the order circle, ring point, joint. ``_sphere_index`` draws them as the segments of ``_spheres``."""
    import numpy as np
    n = len(c)
    if not n:
        return np.zeros((0, 3), np.float32)
    if _RING[0] is None:
        t = np.arange(SEGMENTS + 1) * (2.0 * math.pi / SEGMENTS)
        _RING[0] = np.cos(t)[:, None], np.sin(t)[:, None]
    cos, sin = _RING[0]
    # ring point i of the circle in the joint's axes a, b: centre + (cos_i * axis a + sin_i * axis b) * radius, each
    # step rounded in this order; worked out for every joint side by side (x, y, z of joint 0, of joint 1, ...)
    axes = f.transpose(2, 0, 1).reshape(3, n * 3)       # frame column a of every joint
    u = np.empty((3, SEGMENTS + 1, n * 3))
    term = np.empty((SEGMENTS + 1, n * 3))
    for k, (a, b) in enumerate(((0, 1), (1, 2), (0, 2))):
        np.multiply(cos, axes[a], out=u[k])
        np.multiply(sin, axes[b], out=term)
        u[k] += term
    u *= np.repeat(r, 3)
    u += c.reshape(-1)
    return u.astype(np.float32).reshape(-1, 3)          # (circle, ring point, joint): x, y, z of each point


def _bone_array(pc, pf, pr, cc, cr):
    """``bone_lines`` for many bones at once: parents' centres / frames / radii (M, 3) (M, 3, 3) (M,) and children's
    centres / radii. Returns (points (K * 5, 3): each pyramid's four base corners and its apex, the K bones that are
    drawn) — a bone whose spheres overlap draws nothing. ``_bone_index`` draws them as ``bone_lines``' segments."""
    import numpy as np
    d = cc - pc
    length = np.linalg.norm(d, axis=1)
    drawn = np.nonzero((length > pr + cr) & (length >= 1e-9))[0]
    if not len(drawn):
        return np.zeros((0, 3), np.float64), drawn
    d, length, pc, pf, pr, cc, cr = d[drawn], length[drawn], pc[drawn], pf[drawn], pr[drawn], cc[drawn], cr[drawn]
    u = d / length[:, None]
    base = pc + u * pr[:, None]
    apex = cc - u * cr[:, None]

    def across(axis):
        v = pf[:, :, axis]
        return v - u * np.sum(v * u, axis=1)[:, None]

    a = across(1)
    flat = np.linalg.norm(a, axis=1) < 1e-6
    if flat.any():
        a[flat] = across(2)[flat]
    n = np.linalg.norm(a, axis=1)[:, None]
    a = np.divide(a, n, out=np.zeros_like(a), where=n > 0)
    b = np.cross(u, a)
    ar, br = a * pr[:, None], b * pr[:, None]
    pts = np.stack((base + ar, base + br, base - ar, base - br, apex), axis=1)          # (K, 5, 3)
    return pts.reshape(-1, 3), drawn


def _joint_list(ob):
    """What a pose doesn't change of skeleton ``ob``'s drawn joints: joints {name: Joint, geometry left out}, names,
    their pose bone rows, parent index per joint (-1: no drawn parent), Radius values, {index: Maya frame turn
    (3, 3)}, {index: custom shape object}; for the controls (bones with a custom shape) the pose bone row their shape
    follows and their rest length; the drawn bones (parent, child) between joints without a custom shape. The bones
    are read in one pass in their own order (a lookup by position or name walks the list)."""
    import numpy as np
    from ..operators import joints
    from . import layer_joints
    layered = layer_joints.state(ob)
    pbs, bones = ob.pose.bones, ob.data.bones
    pose_names = pbs.keys()
    pose_row = {n: i for i, n in enumerate(pose_names)}
    shown = _shown(ob, pose_names, pose_row)
    shapes, transforms = [], []
    for pb in pbs:
        s = pb.custom_shape
        shapes.append(s)
        transforms.append(pb.custom_shape_transform if s is not None else None)
    bone_row = {n: k for k, n in enumerate(bones.keys())}
    parent, frame, radius = [], [], []
    frame_key, radius_key = joints.MAYA_FRAME, joints.RADIUS
    for b in bones:
        p = b.parent
        parent.append(p.name if p is not None else None)
        frame.append(b.get(frame_key))
        radius.append(b.get(radius_key, MAYA_RADIUS))
    lengths = np.empty(len(bones), np.float32)
    bones.foreach_get("length", lengths)
    js, names, keep, raw, turned, shaped, src, blen, parent_names = {}, [], [], [], {}, {}, [], [], []
    for i, name in enumerate(pose_names):
        if not shown[i]:
            continue
        k = bone_row[name]
        shape = shapes[i]
        if shape is not None:
            shaped[len(keep)] = shape
            t = transforms[i]
            row = pose_row.get(t.name, -1) if t is not None else i
            src.append(row if row >= 0 else i)
            blen.append(float(lengths[k]))
        q = frame[k]
        if q is not None:
            turned[len(keep)] = np.array(Quaternion(q).to_matrix(), np.float64)
        js[name] = Joint(name, parent[k], None, None, None, state=layered.get(name))
        names.append(name)
        parent_names.append(parent[k])
        keep.append(i)
        raw.append(float(radius[k]))
    index = {nm: j for j, nm in enumerate(names)}
    jl = JointList()
    jl.js, jl.names, jl.rows, jl.raw = js, names, np.asarray(keep, np.intp), np.asarray(raw, np.float64)
    jl.parent_names = parent_names
    jl.parents = np.array([index.get(js[nm].parent, -1) for nm in names], np.intp)
    jl.turned, jl.shaped = turned, shaped
    jl.plain = np.ones(len(names), bool)
    jl.ctrl = np.fromiter(shaped, np.intp, len(shaped))
    jl.plain[jl.ctrl] = False
    jl.ctrl_src = np.asarray(src, np.intp)
    jl.ctrl_len = np.asarray(blen, np.float64)
    jl.ctrl_shapes = list(shaped.values())
    # a joint a display layer hides draws nothing, but the bone from its shown parent stays (the parent's)
    jl.shown = np.array([js[nm].state != layer_joints.HIDDEN for nm in names], bool)
    jl.tint = {j: (*layer_joints.COLOURS[js[nm].state], 1.0) for j, nm in enumerate(names)
               if js[nm].state in layer_joints.COLOURS}
    child = np.nonzero(jl.parents >= 0)[0]
    child = child[jl.plain[child] & jl.plain[jl.parents[child]] & jl.shown[jl.parents[child]]]
    par = jl.parents[child]
    order = np.lexsort((child, par))           # a bone belongs to its parent joint: parent by parent
    jl.bone_child, jl.bone_par = child[order], par[order]
    jl.widgets = None                          # the controls' shape lines in their own space (``_control_lines``)
    jl.owners = {}                             # joint index per drawn point, kept per part (``_owner``)
    jl.bone_rows = np.array([bone_row[nm] for nm in names], np.intp)      # rows in ``ob.data.bones``
    return jl


_LISTS = {}     # skeleton object pointer -> (key, _joint_list) kept while playback runs


def joint_list(ob, playing=False):
    """``_joint_list`` of ``ob``. While playback runs only the pose changes from frame to frame, so the list read
    on the first frame is used again until something is edited (a depsgraph update, undo, a Radius typed)."""
    key = (_EDITS[0], ob.data.as_pointer(), len(ob.pose.bones))
    got = _LISTS.get(ob.as_pointer())
    if playing and got is not None and got[0] == key:
        return got[1]
    out = _joint_list(ob)
    if playing:
        if len(_LISTS) > 32:
            _LISTS.clear()
        _LISTS[ob.as_pointer()] = (key, out)
    else:
        _LISTS.pop(ob.as_pointer(), None)
    return out


def _pose_arrays(ob, scene, playing=False):
    """The visible joints of ``ob`` in Object / Pose Mode: (joints {name: Joint, geometry left out}, names, parent
    index per joint (-1: no drawn parent), centres (N, 3), frames (N, 3, 3), radii (N,), {index: (custom shape,
    world matrix)}) — the same joints, centres, frames (columns normalised) and radii as ``skeleton``."""
    import numpy as np
    jl = joint_list(ob, playing)
    if not jl.names:
        return jl.js, jl.names, jl.parents, np.zeros((0, 3)), np.zeros((0, 3, 3)), jl.raw, {}
    _w, _allm, centres, frames, radii = _pose_read(ob, scene, jl)
    pbs, mw = ob.pose.bones, ob.matrix_world
    shapes = {j: (shape, mw @ _shape_matrix(pbs[int(jl.rows[j])])) for j, shape in jl.shaped.items()}
    return jl.js, jl.names, jl.parents, centres, frames, radii, shapes


def _read_widget(shape, depsgraph):
    """(2E, 3) end points of the edges of custom shape object ``shape``'s evaluated geometry, in its own space."""
    import numpy as np
    try:
        ev = shape.evaluated_get(depsgraph)
        me = ev.to_mesh()
    except (RuntimeError, AttributeError, ReferenceError):
        return np.zeros((0, 3))
    try:
        if me is None:
            return np.zeros((0, 3))
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        ed = np.empty(len(me.edges) * 2, np.intc)      # C int: an int32 buffer of another kind is copied item by item
        me.edges.foreach_get("vertices", ed)
        return co.reshape(-1, 3).astype(np.float64)[ed]
    finally:
        ev.to_mesh_clear()


def _widget_segments(shape, depsgraph):
    """(``_read_widget`` of ``shape``, changes with the frame). A shape whose geometry can't change with the frame is
    read once and kept until its geometry is edited (``_depsgraph_post``), something is edited (``changed``) or
    undone; one that can (``shape_moves``) is read every time."""
    uid, data = shape.session_uid, shape.data
    dptr = data.as_pointer() if data is not None else 0
    got = _WIDGETS.get(uid)
    if got is not None and got[0] == dptr:
        return got[1], False
    segs = _read_widget(shape, depsgraph)
    if shape_moves(shape):
        return segs, True
    _WIDGETS[uid] = (dptr, segs)
    return segs, False


def _widget_plan(jl, depsgraph):
    """The controls' shape lines joined in their own space: (points, control per point, points per control (in
    control order), the shapes that change with the frame [(shape, start, count)], widget generation, int32 line index
    into the points of every shape's segments, runs [(start, stop, controls, points each, one shared shape)]). The
    controls' points follow one another by their point count (``placed_points`` places each run of equal counts at
    once), control by control; a shape that can't change with the frame and that ``SHARED_SHAPE`` or more controls
    show gets a run of its own, stored point by point (its first point in every control of the run, then its second
    ...). A shape that can't change with the frame keeps each of its points once; one that can keeps its segments' end
    points. Joined
    once per joint list and kept while no shape's own geometry changed; the shapes that change with the frame are read
    again in place."""
    import numpy as np
    plan = jl.widgets
    if plan is not None and plan[4] != _WIDGET_GEN[0]:
        plan = None                                  # a shape's own geometry changed: join them again
    if plan is not None and plan[3]:
        p = plan[0]
        for shape, start, count in plan[3]:          # shapes that change with the frame: read again in place
            segs = _read_widget(shape, depsgraph)
            if len(segs) != count:
                plan = None                          # a new edge count: join every shape again
                break
            p[start:start + count] = segs
    if plan is None:
        shapes, users = [], {}
        for shape in jl.ctrl_shapes:
            s, m = _widget_segments(shape, depsgraph)
            shapes.append((shape, s, None) if m else (shape, *_distinct_points(s)))   # None: read every frame
            if not m:
                users[shape.session_uid] = users.get(shape.session_uid, 0) + 1
        counts = np.fromiter((len(t[1]) for t in shapes), np.intp, len(shapes))
        group = {uid: g for g, uid in enumerate(sorted(u for u, c in users.items() if c >= SHARED_SHAPE), 1)}
        shared = np.fromiter((0 if at is None else group.get(shape.session_uid, 0) for shape, _s, at in shapes),
                             np.intp, len(shapes))
        order = np.lexsort((shared, counts))
        groups = []                                  # [points each, shared shape group, [controls]]
        for k in order.tolist():
            c, g = int(counts[k]), int(shared[k])
            if not c:
                continue
            if groups and groups[-1][0] == c and groups[-1][1] == g:
                groups[-1][2].append(k)
            else:
                groups.append([c, g, [k]])
        pts, index, owners, moving, runs, start = [], [], [], [], [], 0
        for c, g, ks in groups:
            ks = np.array(ks, np.intp)
            n = len(ks)
            if g:                                    # one shape: stored point by point (point i of every control)
                _shape, s, at = shapes[ks[0]]
                pts.append(np.repeat(s, n, axis=0))
                owners.append(np.tile(ks, c))
                index.append((at[None, :] * n + np.arange(n, dtype=np.intc)[:, None]).reshape(-1) + start)
            else:                                    # control by control
                for j, k in enumerate(ks.tolist()):
                    shape, s, at = shapes[k]
                    if at is None:
                        moving.append((shape, start + j * c, c))
                        at = np.arange(c, dtype=np.intc)
                    pts.append(s)
                    index.append(at + (start + j * c))
                owners.append(np.repeat(ks, c))
            runs.append((start, start + n * c, ks, c, bool(g)))
            start += n * c
        p = np.concatenate(pts).astype(np.float32) if start else np.zeros((0, 3), np.float32)   # the shapes' own precision
        index = np.concatenate(index).astype(np.intc) if index else np.zeros(0, np.intc)
        owner = np.concatenate(owners) if owners else np.zeros(0, np.intp)
        plan = jl.widgets = (p, owner, counts, moving, _WIDGET_GEN[0], index, runs)
    return plan


SHARED_SHAPE = 8      # controls showing one unchanging shape that get a run of their own (``_widget_plan``)


def _control_lines(ob, jl, w, allm, depsgraph, props=None):
    """(points, joint index per point, int32 line index into the points) of every control's custom shape
    (``shape_lines`` with ``_shape_matrix``, all controls at once), or None. The shapes' own lines are joined once per
    joint list (``_widget_plan``); the pose and the custom shape offset / turn / scale (they can be keyed; ``props``:
    as ``_pose_raw`` read them) are read every time. The controls a display layer hides keep their points but have
    no lines."""
    import numpy as np
    p, owner, _counts, _moving, _gen, index, runs = _widget_plan(jl, depsgraph)
    if not len(p):
        return None
    pbs = ob.pose.bones
    n = len(pbs)
    if props is None:
        props = []
        for prop in ("custom_shape_translation", "custom_shape_rotation_euler", "custom_shape_scale_xyz"):
            a = np.empty(n * 3, np.float32)
            pbs.foreach_get(prop, a)
            props.append(a)
        use = np.zeros(n, bool)
        pbs.foreach_get("use_custom_shape_bone_size", use)
        props.append(use)
    lin, off = _control_placement(jl, w, allm, props, n)
    pts = placed_points(p, lin, off, runs, owner)
    got = jl.owners.get("ctrl")
    if got is None or got[0] is not owner:
        if not jl.shown.all():                       # controls a display layer hides draw nothing
            pairs = index.reshape(-1, 2)
            index = np.ascontiguousarray(pairs[jl.shown[jl.ctrl][owner][pairs[:, 0]]].reshape(-1))
        got = jl.owners["ctrl"] = (owner, jl.ctrl[owner], index)
    return pts, got[1], got[2]


def _own_lines(ob, jl, w, allm, kind):
    """(points, joint index per point) of Blender's B-Bone / Envelope ``kind`` shape of every drawn joint without a
    custom shape (``bbone_lines`` / ``envelope_lines`` in joint order), or None."""
    import numpy as np
    plain = np.nonzero(jl.plain & jl.shown)[0]
    if not len(plain):
        return None
    pbs, bones = ob.pose.bones, ob.data.bones
    n, nb = len(pbs), len(bones)
    rows, brows = jl.rows[plain], _bone_rows(ob, jl)[plain]
    w3, wt = w[:3, :3], w[:3, 3]
    m = allm[rows]

    def bone_values(prop, dtype=np.float32):
        a = np.empty(nb, dtype)
        bones.foreach_get(prop, a)
        return a[brows].astype(np.float64)

    if kind == 'ENVELOPE':
        hd, tl = np.empty(n * 3, np.float32), np.empty(n * 3, np.float32)
        pbs.foreach_get("head", hd)
        pbs.foreach_get("tail", tl)
        s = max(ob.matrix_world.to_scale())
        f = w3 @ m[:, :3, :3]
        norms = np.linalg.norm(f, axis=1, keepdims=True)
        f = np.divide(f, norms, out=np.zeros_like(f), where=norms > 0)
        h = hd.reshape(n, 3)[rows].astype(np.float64) @ w3.T + wt
        t = tl.reshape(n, 3)[rows].astype(np.float64) @ w3.T + wt
        rh, rt = bone_values("head_radius") * s, bone_values("tail_radius") * s
        k = len(rows)
        ax = np.stack((f[:, :, 0], -f[:, :, 0], f[:, :, 2], -f[:, :, 2]), axis=1)          # (K, 4, 3)
        joins = np.stack((h[:, None] + ax * rh[:, None, None], t[:, None] + ax * rt[:, None, None]), axis=2)
        pts = np.concatenate((_spheres(h, f, rh).reshape(k, -1, 3), _spheres(t, f, rt).reshape(k, -1, 3),
                              joins.reshape(k, -1, 3)), axis=1)
        return pts.reshape(-1, 3).astype(np.float32), np.repeat(plain, pts.shape[1])
    # B-Bone: one box per segment along the bent bone, a straight box for one segment
    x, z, segments = bone_values("bbone_x"), bone_values("bbone_z"), bone_values("bbone_segments", np.intc)
    length = np.empty(n, np.float32)
    pbs.foreach_get("length", length)
    zero = np.zeros_like(x)
    corners = np.stack((np.stack((x, zero, z), 1), np.stack((-x, zero, z), 1), np.stack((-x, zero, -z), 1),
                        np.stack((x, zero, -z), 1)), axis=1)                           # (K, 4, 3)
    base = w @ m
    tip = base.copy()
    tip[:, :3, 3] += base[:, :3, 1] * length[rows][:, None]
    straight = np.stack((base, tip), axis=1)                                            # (K, 2, 4, 4)
    bent = {}
    for k in np.nonzero(segments > 1)[0]:
        pb = pbs[int(rows[k])]
        try:
            bent[int(k)] = np.array([np.array(pb.bbone_segment_matrix(i, rest=False), np.float64)
                                     for i in range(int(segments[k]) + 1)])
        except (RuntimeError, ValueError):
            continue
    if not bent:
        pts = _box_array(straight, corners)
        return pts.reshape(-1, 3).astype(np.float32), np.repeat(plain, pts.shape[1])
    blocks = [None] * len(rows)
    rest = np.array([k for k in range(len(rows)) if k not in bent], np.intp)
    if len(rest):
        for k, b in zip(rest, _box_array(straight[rest], corners[rest])):
            blocks[k] = b
    by_rings = {}
    for k, fr in bent.items():
        by_rings.setdefault(len(fr), []).append(k)
    for ks in by_rings.values():
        frames = base[ks][:, None] @ np.array([bent[k] for k in ks])
        for k, b in zip(ks, _box_array(frames, corners[ks])):
            blocks[k] = b
    sizes = [len(b) for b in blocks]
    return np.concatenate(blocks).astype(np.float32), np.repeat(plain, sizes)


def _lines(ob, scene, depsgraph, jl, kind, raw):
    """``_Lines`` of skeleton ``ob`` drawn as ``kind`` from joint list ``jl`` and pose reading ``raw``."""
    import numpy as np
    stick, own = kind in STICK_TYPES, kind in SHAPE_TYPES
    w, allm, centres, frames, radii = _pose_read(ob, scene, jl, raw)
    g = _Lines()
    g.centres, g.frames, g.radii = centres, frames, radii
    g.plain = plain = jl.plain & jl.shown      # spheres / axes: joints with no custom shape that are shown
    g.before, g.after, g.plan, g.ctrl_at = [], [], None, None
    chunks = None if stick or own else []
    if not (stick or own) and plain.any():
        pts = _sphere_ring(centres[plain], frames[plain], radii[plain])
        got = _sphere_owner(jl, plain)
        g.before.append((pts, got[1], got[2]))
        if chunks is not None:
            chunks.append(g.before[-1])
    if len(jl.ctrl):
        got = _control_lines(ob, jl, w, allm, depsgraph, raw[4])
        g.plan = jl.widgets
        if got is not None:
            g.ctrl_at = len(g.before)
            g.before.append(got)
            if chunks is not None:
                chunks.append(got)
    if own:
        got = _own_lines(ob, jl, w, allm, kind)
        if got is not None:
            g.after.append((got[0], got[1], None))
    elif len(jl.bone_child):
        child, par = jl.bone_child, jl.bone_par
        if stick:
            segs = np.stack((centres[par], centres[child]), axis=1).reshape(-1, 3)
            owner, index = _owner(jl, "sticks", par, 2), None
        else:
            segs, drawn = _bone_array(centres[par], frames[par], radii[par], centres[child], radii[child])
            owner, index = _owner(jl, "bones", drawn, 5, par), _bone_index(len(drawn))
        if len(segs):
            g.after.append((segs.astype(np.float32), owner, index))
            if chunks is not None:
                chunks.append(g.after[-1])
    g.chunks = chunks
    return g


def _lines_moved(ob, scene, jl, kind, raw, g0, old_raw):
    """``_lines`` of pose reading ``raw`` from the lines ``g0`` of ``old_raw`` when a part of the skeleton moved (a
    limb dragged): only the joints whose bones moved are worked out again — each joint's sphere and control shape
    from its own bone, so the numbers are the ones of building every joint — the bones between joints all again.
    None when that isn't the case or not worth it (the object moved, most joints moved, a control shape that changes
    with the frame or hidden, Blender's Stick / B-Bone / Envelope looks)."""
    import numpy as np
    if g0 is None or kind in STICK_TYPES or kind in SHAPE_TYPES:
        return None
    moved = _moved_bones(raw, old_raw)
    if moved is None:
        return None
    ctrl = len(jl.ctrl)
    plan = jl.widgets
    if ctrl and (plan is None or plan is not g0.plan or plan[4] != _WIDGET_GEN[0] or plan[3] or not jl.shown.all()):
        return None
    plain = g0.plain
    joints_moved = np.flatnonzero(moved[jl.rows])
    spheres = joints_moved[plain[joints_moved]]
    controls = np.flatnonzero(moved[jl.ctrl_src]) if ctrl and g0.ctrl_at is not None else np.zeros(0, np.intp)
    if 2 * (len(spheres) + len(controls)) > int(plain.sum()) + ctrl:
        return None                              # most of it moved: build it all
    w, allm, c_moved, f_moved, _r = _pose_read(ob, scene, jl, raw, joints_moved)
    g = _Lines()
    g.centres, g.frames, g.radii, g.plain, g.plan, g.ctrl_at = g0.centres, g0.frames, g0.radii, plain, g0.plan, None
    if len(joints_moved):
        g.centres, g.frames = g0.centres.copy(), g0.frames.copy()
        g.centres[joints_moved], g.frames[joints_moved] = c_moved, f_moved
    g.before, g.after, chunks = [], [], []
    if plain.any():
        pts, owner, index = g0.before[0]
        if len(spheres):
            pts = pts.copy()
            ring = pts.reshape(3, SEGMENTS + 1, -1, 3)        # ``_sphere_ring``: circle, ring point, joint
            ring[:, :, np.cumsum(plain)[spheres] - 1] = _sphere_ring(
                g.centres[spheres], g.frames[spheres], g.radii[spheres]).reshape(3, SEGMENTS + 1, len(spheres), 3)
        g.before.append((pts, owner, index))
        chunks.append(g.before[-1])
    if g0.ctrl_at is not None:
        pts, joint, index = g0.before[g0.ctrl_at]
        if len(controls):
            pts = pts.copy()
            at, new = _control_points(jl, w, allm, raw[4], plan, controls)
            pts[at] = new
        g.ctrl_at = len(g.before)
        g.before.append((pts, joint, index))
        chunks.append(g.before[-1])
    if len(jl.bone_child):
        child, par = jl.bone_child, jl.bone_par
        segs, drawn = _bone_array(g.centres[par], g.frames[par], g.radii[par], g.centres[child], g.radii[child])
        owner = _owner(jl, "bones", drawn, 5, par)
        if len(segs):
            g.after.append((segs.astype(np.float32), owner, _bone_index(len(drawn))))
            chunks.append(g.after[-1])
    g.chunks = chunks
    return g


def _parts(ob, scene, depsgraph, kind=None, playing=False, pick=None, keep=None):
    """Every line of skeleton ``ob`` as three parts (points list, colours list): the joints' spheres and the
    controls' shapes; the local axes of the selected joints (drawn in perspective views only); the bones (pyramids,
    sticks, or Blender's B-Bone / Envelope shapes). ``kind`` = the display type (default: the skeleton's). Object
    and Pose Mode build them in arrays from one read of the pose; Edit Mode joint by joint.
    ``pick``: a list that gets (joint list, [(points, joint index per point or per joint, points per joint)]) — the
    lines a click picks (``_drawn_pick_lines``) — when they are the drawn Maya joints.
    ``keep``: this skeleton's ``_Build`` from an earlier redraw. What can't have changed since (``keep.level``) is
    used again: the joint list when only the pose may have changed (or when it reads the same), the lines when the
    pose reads the same, the colours when the selection is the same; ``keep`` then holds this build."""
    if kind is None:
        kind = getattr(ob.data, "display_type", 'OCTAHEDRAL')
    if ob.mode == 'EDIT':
        return _joint_parts(ob, scene, depsgraph, kind)
    key = _build_key(ob, kind)
    old = keep if keep is not None and keep.key == key and keep.parts is not None and keep.level != 'new' else None
    stamp = old.stamp if old is not None else None
    if keep is None:
        jl = joint_list(ob, playing)
    elif old is not None and old.level in (None, 'pose'):
        jl = old.jl                                   # only the pose may have changed
    elif old is not None and old.level == 'light' and old.stamp == (stamp := _stamp(ob)):
        jl = old.jl                                   # a selection, a mode, the same names and shown bones
    else:
        stamp = _stamp(ob) if keep is not None else None
        jl = _joint_list(ob)
        if old is not None and _same_list(old.jl, jl):
            jl = old.jl
    if not jl.names:
        parts = ([], [], []), ([], [], []), ([], [], [])
        if keep is not None:
            keep.level, keep.key, keep.jl, keep.stamp, keep.raw, keep.lines = None, key, jl, stamp, None, None
            keep.sel, keep.rgba, keep.parts, keep.pick = None, None, parts, None
        return parts
    raw = _pose_raw(ob, scene, jl)
    same_jl = old is not None and jl is old.jl
    g = old.lines if same_jl and _lines_hold(old.lines, jl, kind, raw, old.raw) else None
    if g is None and same_jl:
        g = _lines_moved(ob, scene, jl, kind, raw, old.lines, old.raw)
    if g is None:
        g = _lines(ob, scene, depsgraph, jl, kind, raw)
    sel, lead = _joint_selection(ob, jl)
    sel_key = (frozenset(sel), lead)
    if same_jl and old.sel == sel_key:
        rgba = old.rgba
    else:
        rgba = _joint_rgba(jl, sel, lead)
    if old is not None and g is old.lines and rgba is old.rgba:
        parts = old.parts
    else:
        parts = _paint(jl, g, sel, rgba, (old.lines, old.rgba, old.parts) if old is not None else None)
    if pick is not None and g.chunks is not None:
        pick.append((jl, g.chunks) if old is None or old.pick is None or old.pick[1] is not g.chunks
                    or old.pick[0] is not jl else old.pick)
    if keep is not None:
        keep.level, keep.key, keep.jl, keep.stamp, keep.raw, keep.lines = None, key, jl, stamp, raw, g
        keep.sel, keep.rgba, keep.parts = sel_key, rgba, parts
        keep.pick = pick[-1] if pick else None
    return parts


def _joint_parts(ob, scene, depsgraph, kind):
    """``_parts`` joint by joint (``skeleton``): Edit Mode."""
    import numpy as np
    before, axes, after = ([], [], []), ([], [], []), ([], [], [])
    js = skeleton(ob, scene)
    if not js:
        return before, axes, after
    stick, own = kind in STICK_TYPES, kind in SHAPE_TYPES
    sel, lead = selection(ob, js)
    col = colours(js, sel, lead)

    def add(part, segs, colour):
        if segs:
            part[0].append(np.array([tuple(v) for v in segs], np.float32))
            part[1].append(np.tile(np.array((*colour, 1.0), np.float32), (len(segs), 1)))
            part[2].append(None)

    spheres, order = _sphere_array(js) if not (stick or own) else (None, ())
    if order:
        before[0].append(spheres)
        before[1].append(np.repeat(np.array([(*col[n], 1.0) for n in order], np.float32), 3 * SEGMENTS * 2,
                                   axis=0))
        before[2].append(None)
    bones, bone_cols = [], []
    if own:
        for name, segs in own_shape_lines(ob, kind).items():
            if name in col and js[name].state != _HIDDEN:
                bones += segs
                bone_cols += [col[name]] * len(segs)
    for j in js.values():
        if j.state == _HIDDEN:
            continue                           # hidden by a display layer: only its parent's bone to it stays
        if j.shape is not None:
            add(before, shape_lines(j.shape[0], j.shape[1], depsgraph), col[j.name])
            continue
        for cn in () if own else j.children:
            child = js[cn]
            if child.shape is None:
                segs = [j.centre, child.centre] if stick else bone_lines(j, child)
                bones += segs
                bone_cols += [col[j.name]] * len(segs)
        if j.name in sel:
            for i in range(3):
                add(axes, [j.centre, j.centre + j.frame.col[i] * j.radius], AXIS_COLORS[i])
    if bones:
        after[0].append(np.array([tuple(v) for v in bones], np.float32))
        after[1].append(np.array([(*c, 1.0) for c in bone_cols], np.float32))
        after[2].append(None)
    return before, axes, after


def _fast_lines(ob, scene, perspective, depsgraph, stick, playing=False, kind=None):
    """(points, colours) lists of float32 arrays of segment end points of skeleton ``ob`` drawn as ``kind`` (default:
    Maya joints, or sticks with ``stick``): the same lines and colours as the per-joint geometry, built in arrays."""
    parts = _parts(ob, scene, depsgraph, kind or ('STICK' if stick else 'OCTAHEDRAL'), playing)
    return _segments(*_part_arrays([parts], perspective))


def transform_op():
    """The transform running in some window (move / rotate / scale, a manipulator drag), else None."""
    from ..operators.manip_scale import TRANSFORM_MODALS
    wm = bpy.context.window_manager
    if wm is None:
        return None
    return next((op for w in wm.windows for op in w.modal_operators
                 if op is not None and op.bl_idname.startswith(TRANSFORM_MODALS)), None)


def transforming():
    """A transform runs in some window (move / rotate / scale, a manipulator drag): until it ends only poses and
    object transforms change, so what is kept while playback runs can be kept too."""
    return transform_op() is not None


def _posing():
    """A transform runs in Object or Pose Mode (not Edit Mode: there it moves points and bones)."""
    return getattr(bpy.context, "mode", None) in {'OBJECT', 'POSE'} and transforming()


SCRUB_MODALS = frozenset({"ALLSET_OT_time_scrub", "ANIM_OT_change_frame"})


def scrubbing():
    """The time is being dragged in a Time Slider / timeline (a scrub): until it ends only the frame changes, as
    while playback runs."""
    wm = bpy.context.window_manager
    if wm is None:
        return False
    return any(op is not None and op.bl_idname in SCRUB_MODALS for w in wm.windows for op in w.modal_operators)


def _playing(context):
    """Playback runs, the time is scrubbed or a pose / object is being dragged: the joint lists and control shapes
    read once are used again."""
    screen = getattr(context, "screen", None)
    return (screen is not None and screen.is_animation_playing) or _posing() or scrubbing()


def view_lines(context):
    """(points, colours) float32 arrays of every joint to draw in this view."""
    scene, depsgraph = context.scene, context.view_layer.depsgraph
    playing = _playing(context)
    parts = [_parts(ob, scene, depsgraph, None, playing) for ob in _view_skeletons(context, context.space_data)]
    return _join(parts, context.region_data.is_perspective)


@bpy.app.handlers.persistent
def _depsgraph_post(_scene, depsgraph):
    """Record which skeletons an update can have changed: those it updated (a selection, a pose, an edit) or whose
    control shapes' geometry it changed; a Scene update (selection, visibility) asks every skeleton to check its
    pose and selection. An update that touches no skeleton (a moved mesh, a material) changes no drawn joint. While a
    pose or an object is dragged only poses change: the joint lists and control shapes are kept."""
    try:
        if _posing():
            moved = _moved_skeletons(depsgraph, update_summary.updates(depsgraph, _depsgraph_post))
            if moved is None:
                _LAYER_GEN[0] += 1
                _note({}, 'pose')
            elif moved:
                _note(dict.fromkeys(moved, 'pose'))
            else:
                _note({})
            return
        got = _touched(depsgraph, update_summary.updates(depsgraph, _depsgraph_post))
        if got is None:
            changed(shapes=True)
            return
        touched, scene, rebuilt = got
        if not (touched or scene or rebuilt):
            return
        levels = dict(touched)
        levels.update(dict.fromkeys(rebuilt, 'new'))
        for p, level in levels.items():
            counts = _SKEL_LIGHT if level == 'light' else _SKEL_EDITS
            counts[p] = counts.get(p, 0) + 1
        if levels:
            _EDITS[0] += 1
        if scene:
            _LAYER_GEN[0] += 1
        _note(levels, None, scene)
    except (ReferenceError, AttributeError):
        changed(shapes=True)


@bpy.app.handlers.persistent
def _frame_post(*_args):
    _note({}, 'frame')


def _forget():
    _BUILDS.clear()
    _PARTS.clear()
    _PICK.clear()
    _JOINED.clear()
    _COLOURS.clear()
    _PICK_PLAN.clear()
    _NEAREST[0] = None
    _TOUCHED.clear()
    _DATA_USERS.clear()
    _SHAPE_USERS.clear()
    _SHAPE_PTRS.clear()
    _ARMS.clear()
    _WORLD[0] = None


@bpy.app.handlers.persistent
def _reload(*_args):
    changed(shapes=True)
    _LISTS.clear()
    _forget()


def _joined(context):
    """[points, colours, batch] of this view. The lines of each skeleton are kept until something that can change
    them reaches it (``_depsgraph_post`` / a new frame: only the skeletons concerned are looked at again, and of those
    only what changed is built again) and shared by every 3D View that shows the same skeletons in the same
    projection; a skeleton in Edit Mode is built again when its edit bones read differently."""
    space, scene, layer = context.space_data, context.scene, context.view_layer
    playing = _playing(context)
    key = _world_key(scene, layer)
    if _WORLD[0] != key:
        dirt = _since(_WORLD[0], key)
        scale = _radius_scale(scene)
        if scale != _SCALE[0]:
            dirt = None                        # Joint Size / the unit changed: every joint's size
        _WORLD[0] = key
        _SCALE[0] = scale
        _TOUCHED.clear()
        _mark(dirt, playing)
    obs = _view_skeletons(context, space)
    persp = context.region_data.is_perspective
    shown = (tuple(ob.as_pointer() for ob in obs), persp)
    depsgraph = layer.depsgraph
    fresh = False
    if len(_BUILDS) > 64:
        _forget()
    for ob in obs:
        ptr = ob.as_pointer()
        b = _BUILDS.get(ptr)
        if b is None:
            b = _BUILDS[ptr] = _Build()
        if ob.mode == 'EDIT':
            sig = _edit_signature(ob)
            ekey = ('EDIT', ob.data.as_pointer(), getattr(ob.data, "display_type", 'OCTAHEDRAL'))
            if b.level is not None or b.key != ekey or b.sig != sig or ptr not in _PARTS:
                _forget_build(b)
                b.key, b.sig, b.level = ekey, sig, None
                b.parts = _PARTS[ptr] = _parts(ob, scene, depsgraph, None, playing)
                _PICK[ptr] = None
                fresh = True
            continue
        if b.parts is not _PARTS.get(ptr) or b.key is None or b.key[0] == 'EDIT':
            b.level = 'new'                    # Edit Mode left; lines set by a test
        elif b.level is None:
            continue                           # other data, look or bones come with an update (``_parts`` key)
        before = b.parts
        b.sig = None
        pick = []
        _PARTS[ptr] = _parts(ob, scene, depsgraph, None, playing, pick, b)
        _PICK[ptr] = b.pick
        if b.registered is not b.jl:
            _register(ob, b)
        fresh = fresh or b.parts is not before
    if fresh:
        _JOINED.clear()
    hit = _JOINED.get(shown)
    if hit is None:
        hit = _JOINED[shown] = _join_view(shown, [_PARTS[ob.as_pointer()] for ob in obs], persp)
    if len(_CACHE) > 32:
        _CACHE.clear()
    _CACHE[space.as_pointer()] = (key + (persp,), hit[0], hit[1])
    return hit


def _new_batch(hit):
    """GPU batch of joined lines ``hit`` (``_joined``): the colours' vertex buffer and the line index, made once and
    kept with the colours (``_COLOURS``), and one vertex buffer of the points. The colours come first: Blender draws
    a polyline batch with the colour format of its first vertex buffer (gpu_batch.cc, polyline_draw_workaround). The
    polyline shader reads each segment end through the index, so a point shared by several segments gives each the
    same position and colour as when every segment had its own copy (gpu_batch.cc, GPU_batch_bind_as_resources)."""
    from gpu.types import GPUBatch, GPUIndexBuf
    held = hit[3]
    if held[2] is None:
        held[2] = _vertex_buffer("color", held[1])
    if held[5] is None:
        held[5] = GPUIndexBuf(type='LINES', seq=held[4].reshape(-1, 2))
    batch = GPUBatch(type='LINES', buf=held[2], elem=held[5])
    batch.vertbuf_add(_vertex_buffer("pos", hit[0]))
    return batch


def cached_view_lines(context):
    """``view_lines`` kept until a joint can have changed, shared by the views."""
    return joined_segments(_joined(context))


@bpy.app.handlers.persistent
def _save_pre(*_args):
    try:
        release_all()        # a saved file shows Blender's bones when it opens without the kit
    except (ReferenceError, AttributeError, RuntimeError):
        pass


@bpy.app.handlers.persistent
def _save_post(*_args):
    _tick()


def _draw():
    context = bpy.context
    try:
        if not is_maya_view(context.space_data, context.window.workspace):
            return
        hit = _joined(context)
    except (ReferenceError, AttributeError, KeyError, ValueError, RuntimeError):
        return
    if not len(hit[4]):
        return
    import gpu
    region = context.region
    sh = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
    gpu.state.depth_test_set('NONE' if see_through(context.space_data) else 'LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    gpu.state.blend_set('ALPHA')
    try:
        sh.uniform_float("viewportSize", (region.width, region.height))
        sh.uniform_float("lineWidth", LINE_PX * context.preferences.system.pixel_size)
        if hit[2] is None:          # one batch per set of lines, drawn by every view that shows them
            hit[2] = _new_batch(hit)
        hit[2].draw(sh)
    finally:
        gpu.state.blend_set('NONE')
        gpu.state.depth_test_set('NONE')


def HANDLERS():
    h = bpy.app.handlers
    return ((h.save_pre, _save_pre), (h.save_post, _save_post), (h.depsgraph_update_post, _depsgraph_post),
            (h.frame_change_post, _frame_post), (h.load_post, _reload), (h.undo_post, _reload),
            (h.redo_post, _reload), (h.animation_playback_pre, _reload))


def register():
    if not _handle:
        _handle.append(bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW'))
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.2, persistent=True)
    for lst, fn in HANDLERS():
        if fn not in lst:
            lst.append(fn)


def unregister():
    for lst, fn in HANDLERS():
        if fn in lst:
            lst.remove(fn)
    _CACHE.clear()
    _LISTS.clear()
    _WIDGETS.clear()
    _SKEL_EDITS.clear()
    _SKEL_LIGHT.clear()
    _FORMATS.clear()
    _forget()
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    while _handle:
        bpy.types.SpaceView3D.draw_handler_remove(_handle.pop(), 'WINDOW')
    try:
        release_all()
    except (ReferenceError, AttributeError, RuntimeError):
        pass
