# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya joint lines for many joints at once in numpy arrays: the pose read in one call, joint colours, line index
tables of spheres / bone pyramids / boxes, control shape placement, the painted parts and their join into one buffer
for the GPU. Main entry points: ``_pose_read``, ``_joint_rgba``, ``_paint``, ``_join_view``, ``joined_segments``.
Related: ``maya_joints`` (builds the lines), ``maya_joints_cache``.
"""

from .maya_joints_shapes import AXIS_COLORS, LEAD, SEGMENTS, SELECTED, UNSELECTED, selection


_RING = [None]      # (cos, sin) of the ring points' angles (S + 1, 1)
_RING_INDEX = {}    # sphere count -> ``_sphere_index``


def _sphere_index(n):
    """Int32 line index into ``_sphere_ring`` of ``n`` spheres giving the segments of ``_spheres`` in its order (per
    joint, circle and segment: ring points i and i + 1). Kept per ``n``."""
    import numpy as np
    got = _RING_INDEX.get(n)
    if got is None:
        j = np.arange(n, dtype=np.intc)[:, None, None]
        k = np.arange(3, dtype=np.intc)[None, :, None]
        s = np.arange(SEGMENTS, dtype=np.intc)[None, None, :]
        a = (k * (SEGMENTS + 1) + s) * n + j                                    # (joint, circle, segment)
        got = np.ascontiguousarray(np.stack((a, a + n), axis=3).reshape(-1))
        if len(_RING_INDEX) > 64:
            _RING_INDEX.clear()
        _RING_INDEX[n] = got
    return got


_BONE_SEGMENTS = (0, 1, 0, 4, 1, 2, 1, 4, 2, 3, 2, 4, 3, 0, 3, 4)   # corner i to i + 1 and to the apex, per corner
_BONE_INDEX = {}    # pyramid count -> ``_bone_index``


def _bone_index(k):
    """Int32 line index into ``_bone_array``'s points of ``k`` pyramids: per corner the base edge to the next corner,
    then the edge up to the apex. Kept per ``k``."""
    import numpy as np
    got = _BONE_INDEX.get(k)
    if got is None:
        got = np.ascontiguousarray((np.arange(k, dtype=np.intc)[:, None] * 5
                                    + np.array(_BONE_SEGMENTS, np.intc)[None, :]).reshape(-1))
        if len(_BONE_INDEX) > 64:
            _BONE_INDEX.clear()
        _BONE_INDEX[k] = got
    return got


class JointList:
    """What a pose doesn't change of a skeleton's drawn joints (Object / Pose Mode)."""
    __slots__ = ("js", "names", "rows", "parents", "raw", "turned", "shaped", "plain", "ctrl", "ctrl_src",
                 "ctrl_len", "ctrl_shapes", "bone_par", "bone_child", "widgets", "bone_rows", "shown", "tint",
                 "parent_names", "owners")


def _bone_rows(ob, jl):
    """Row of every joint of ``jl`` in ``ob.data.bones`` (its order can differ from the pose bones')."""
    import numpy as np
    if jl.bone_rows is None:
        index = {b.name: i for i, b in enumerate(ob.data.bones)}
        jl.bone_rows = np.array([index[nm] for nm in jl.names], np.intp)
    return jl.bone_rows


def _pose_raw(ob, scene, jl):
    """What skeleton ``ob``'s drawn lines follow besides its joint list, read in one go: every pose bone's
    armature-space matrix and head (as stored), the world matrix, the drawn radius factor and, with controls, their
    custom shape offset / turn / scale. The same readings draw the same lines."""
    import numpy as np
    from ..operators import joint_display, units
    pbs = ob.pose.bones
    n = len(pbs)
    mw = ob.matrix_world
    k = 0.5 * joint_display.joint_size(scene) * units.radius_unit(scene) * joint_display.skeleton_scale(ob)
    mat = np.empty(n * 16, np.float32)
    pbs.foreach_get("matrix", mat)
    head = mat.reshape(n, 16)[:, 12:15].ravel()      # a pose bone's head is its matrix's translation, bit for bit
    shape = _shape_props(ob, pbs, n) if len(jl.ctrl) else None
    return mat, head, np.array(mw, np.float64), k, shape


_SHAPE_PROPS = {}   # skeleton object pointer -> (edit stamps, custom shape offset / turn / scale / use bone size)


def _shape_props_move(ob):
    """Can the custom shape offset / turn / scale of ``ob``'s pose bones change with the frame or another object?
    Keyed or driven, or an NLA strip plays an action on the object."""
    from .. import compat
    ad = ob.animation_data
    if ad is None:
        return False
    if any(len(t.strips) for t in ad.nla_tracks):
        return True
    return any("custom_shape" in fc.data_path for fc in (*compat.id_fcurves(ob), *ad.drivers))


def _shape_props(ob, pbs, n):
    """[offset, turn, scale (n * 3 float32), use bone size (n bool)] of the custom shapes of every pose bone. Kept
    while nothing updated the skeleton (any update to it reads them again) and nothing keys or drives them."""
    import numpy as np
    from .maya_joints_cache import _ALL_EDITS, _SKEL_EDITS, _SKEL_LIGHT
    ptr = ob.as_pointer()
    key = (n, _ALL_EDITS[0], _SKEL_EDITS.get(ptr, 0), _SKEL_LIGHT.get(ptr, 0))
    got = _SHAPE_PROPS.get(ptr)
    if got is not None and got[0] == key:
        return got[1]
    shape = []
    for prop in ("custom_shape_translation", "custom_shape_rotation_euler", "custom_shape_scale_xyz"):
        a = np.empty(n * 3, np.float32)
        pbs.foreach_get(prop, a)
        shape.append(a)
    use = np.zeros(n, bool)
    pbs.foreach_get("use_custom_shape_bone_size", use)
    shape.append(use)
    if len(_SHAPE_PROPS) > 64:
        _SHAPE_PROPS.clear()
    if _shape_props_move(ob):
        _SHAPE_PROPS.pop(ptr, None)
    else:
        _SHAPE_PROPS[ptr] = (key, shape)
    return shape


def _pose_read(ob, scene, jl, raw=None, only=None):
    """(world matrix (4, 4), every pose bone's armature-space matrix (n, 4, 4), and the drawn joints' centres (N, 3),
    frames (N, 3, 3; columns normalised) and radii (N,)) of skeleton ``ob`` — one read of the pose for all joints.
    ``raw``: its ``_pose_raw`` when already read. ``only``: joint indices: the centres, frames and radii of these
    joints alone (each joint's numbers are worked out from its own bone: the same as among all joints)."""
    import numpy as np
    from ..operators import joints
    mat, head, w, k, _shape = raw if raw is not None else _pose_raw(ob, scene, jl)
    n = len(head) // 3
    allm = mat.reshape(n, 4, 4).transpose(0, 2, 1).astype(np.float64)       # stored by columns
    m3 = w[:3, :3]
    rows = jl.rows if only is None else jl.rows[only]
    centres = head.reshape(n, 3)[rows].astype(np.float64) @ m3.T + w[:3, 3]
    frames = m3 @ allm[rows][:, :3, :3] @ np.array(joints.JOINT_AXES, np.float64)
    if only is None:
        for j, q in jl.turned.items():
            frames[j] = frames[j] @ q
    elif jl.turned:
        for i, j in enumerate(only.tolist()):
            q = jl.turned.get(j)
            if q is not None:
                frames[i] = frames[i] @ q
    norms = np.sqrt(np.einsum('nij,nij->nj', frames, frames))[:, None, :]     # each column's length
    frames = np.divide(frames, norms, out=np.zeros_like(frames), where=norms > 0)
    return w, allm, centres, frames, (jl.raw if only is None else jl.raw[only]) * k


def _joint_selection(ob, jl):
    """``selection`` of ``ob``; in Pose Mode the selected bones are read in one call."""
    import numpy as np
    from ..operators import joint_preview
    if ob.mode != 'POSE' or (joint_preview.running() and joint_preview.STATE.get("ob") == ob.name):
        return selection(ob, jl.js)
    pbs = ob.pose.bones
    flags = np.zeros(len(pbs), bool)
    pbs.foreach_get("select", flags)
    sel = {jl.names[j] for j in np.nonzero(flags[jl.rows])[0]}
    act = ob.data.bones.active
    return sel, (act.name if act is not None and act.name in sel else None)


def _joint_rgba(jl, sel, lead):
    """(N, 4) colour of every joint (``colours``, resolved for all joints at once); nothing selected: all
    unselected."""
    import numpy as np
    n = len(jl.names)
    if not sel:
        rgba = np.tile(np.array((*UNSELECTED, 1.0), np.float32), (n, 1))
        for j, c in jl.tint.items():           # Template / Reference layer colour
            rgba[j] = c
        return rgba
    # each joint's own colour (lead, selected, its layer's), else the nearest joint above it with one
    palette = [(*UNSELECTED, 1.0), (*SELECTED, 1.0), (*LEAD, 1.0)]
    val = np.full(n, -1, np.intp)
    for j, c in jl.tint.items():
        if c not in palette:
            palette.append(c)
        val[j] = palette.index(c)
    val[np.fromiter((nm in sel for nm in jl.names), bool, n)] = 1
    if lead is not None and lead in jl.js:
        val[jl.names.index(lead)] = 2
    up = jl.parents.copy()
    todo = np.flatnonzero((val < 0) & (up >= 0))
    while len(todo):
        got = val[up[todo]]
        have = got >= 0
        val[todo[have]] = got[have]
        rest = todo[~have]
        up[rest] = up[up[rest]]                # the parent has no colour of its own: look past it
        todo = rest[up[rest] >= 0]
    val[val < 0] = 0
    return np.array(palette, np.float32)[val]


# modifiers that only reshape the object's own geometry: unkeyed, their result can't change with the frame
_STILL_MODIFIERS = frozenset({'SUBSURF', 'MULTIRES', 'TRIANGULATE', 'EDGE_SPLIT', 'WELD', 'SOLIDIFY', 'BEVEL',
                              'WIREFRAME'})


def shape_moves(shape):
    """Can custom shape ``shape``'s geometry change with the frame? Shape keys, particles, animated or driven data,
    a modifier that can read the time or other objects, or a keyed / driven modifier setting. A Subdivision Surface
    (Bevel, Solidify ...) modifier alone can't."""
    if getattr(shape, "particle_systems", None):
        return True
    if shape.modifiers and (shape.animation_data is not None
                            or any(m.type not in _STILL_MODIFIERS for m in shape.modifiers)):
        return True
    data = shape.data
    return data is not None and (getattr(data, "shape_keys", None) is not None or data.animation_data is not None)


def _euler_xyz(e):
    """(K, 3) XYZ Euler angles -> (K, 3, 3) rotation matrices (``Euler.to_matrix``)."""
    import numpy as np
    cx, cy, cz = np.cos(e[:, 0]), np.cos(e[:, 1]), np.cos(e[:, 2])
    sx, sy, sz = np.sin(e[:, 0]), np.sin(e[:, 1]), np.sin(e[:, 2])
    m = np.empty((len(e), 3, 3))
    m[:, 0, 0], m[:, 0, 1], m[:, 0, 2] = cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz
    m[:, 1, 0], m[:, 1, 1], m[:, 1, 2] = cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz
    m[:, 2, 0], m[:, 2, 1], m[:, 2, 2] = -sy, sx * cy, cx * cy
    return m


def _distinct_points(segs):
    """(each distinct point of segment end points ``segs`` (2E, 3) once, int32 index of every end point into them):
    points with the same bits are one point."""
    import numpy as np
    if not len(segs):
        return segs, np.zeros(0, np.intc)
    rows = np.ascontiguousarray(segs).view(np.dtype((np.void, segs.dtype.itemsize * 3))).reshape(-1)
    _u, first, inverse = np.unique(rows, return_index=True, return_inverse=True)
    return segs[first], inverse.reshape(-1).astype(np.intc)


def _control_placement(jl, w, allm, props, n, which=None):
    """(linear part (C, 3, 3), offset (C, 3)) of the world matrix every control's shape is drawn with (``_shape_matrix``
    in world space; ``props``: the custom shape offset / turn / scale of the ``n`` pose bones as ``_pose_raw`` read
    them). ``which``: control indices: those controls alone (each from its own bone: the same numbers)."""
    local, offset = _shape_local(jl, props, n)
    ctrl_src = jl.ctrl_src
    if which is not None:
        ctrl_src, local, offset = ctrl_src[which], local[which], offset[which]
    src = allm[ctrl_src]
    a = w[:3, :3] @ src[:, :3, :3]
    lin = a @ local
    off = (a @ offset[:, :, None])[:, :, 0] + src[:, :3, 3] @ w[:3, :3].T + w[:3, 3]
    return lin, off


_LOCAL = {}    # id of a joint list -> (that joint list, the shape readings, local turn x scale (C, 3, 3), offset (C, 3))


def _shape_local(jl, props, n):
    """(turn x scale (C, 3, 3), offset (C, 3)) of every control's custom shape in its bone's space, from ``props``
    (``_pose_raw``). Worked out again only when ``props`` is a new reading (``_shape_props`` hands back the same
    readings while nothing can have changed them)."""
    import numpy as np
    got = _LOCAL.get(id(jl))
    if got is not None and got[0] is jl and got[1] is props:
        return got[2], got[3]
    ctrl_rows = jl.rows[jl.ctrl]
    offset, turn, size = (a.reshape(n, 3)[ctrl_rows].astype(np.float64) for a in props[:3])
    scale = size * np.where(props[3][ctrl_rows], jl.ctrl_len, 1.0)[:, None]
    local = _euler_xyz(turn) * scale[:, None, :]
    if len(_LOCAL) > 64:
        _LOCAL.clear()
    _LOCAL[id(jl)] = (jl, props, local, offset)
    return local, offset


def _control_points(jl, w, allm, props, plan, which):
    """(bool per control shape point, float32 points) of the controls ``which`` (indices, sorted) alone: their points
    in ``_control_lines`` and those points worked out again (each control placed as among all of them: the same
    numbers; every control shown)."""
    import numpy as np
    p, owner = plan[0], plan[1]
    chosen = np.zeros(len(jl.ctrl), bool)
    chosen[which] = True
    at = chosen[owner]
    lin, off = _control_placement(jl, w, allm, props, len(props[3]), which)
    slot = np.cumsum(chosen) - 1                           # position in ``which`` of each chosen control
    if not _by_runs(plan[6], len(jl.ctrl)):
        local = slot[owner[at]]
        return at, (np.einsum('kij,kj->ki', lin[local], p[at]) + off[local]).astype(np.float32)
    lt, off, out = lin.transpose(0, 2, 1).astype(np.float32), off.astype(np.float32), []
    for start, stop, ks, c, one in plan[6]:
        mine = chosen[ks]
        if mine.any():
            k = slot[ks[mine]]
            q = np.empty((len(k) * c, 3), np.float32)
            _place_run(p[start:stop], c, one, mine, lt[k], off[k], q)
            out.append(q)
    return at, np.concatenate(out) if out else np.zeros((0, 3), np.float32)


def _by_runs(runs, k):
    """Place ``k`` controls run by run (``placed_points``): not when there are many short runs (a few controls whose
    shapes have many different point counts), each point with its control's matrix then."""
    return len(runs) * 8 <= k


def placed_points(p, lin, off, runs, owner):
    """float32 points ``p`` of the controls' shapes (``_widget_plan``, ``owner``: control per point) placed by each
    control's linear part ``lin`` (K, 3, 3) and offset ``off`` (K, 3): each run of controls with the same point count
    at once, one float32 matrix product per control (no 3 x 3 matrix copied per point)."""
    import numpy as np
    if not _by_runs(runs, len(lin)):
        return (np.einsum('kij,kj->ki', lin[owner], p) + off[owner]).astype(np.float32)
    lt, off = lin.transpose(0, 2, 1).astype(np.float32), off.astype(np.float32)
    out = np.empty((len(p), 3), np.float32)
    for start, stop, ks, c, one in runs:
        _place_run(p[start:stop], c, one, None, lt[ks], off[ks], out[start:stop])
    return out


def _place_run(q, c, one, mine, lt, off, out):
    """Place the points ``q`` (K * c, 3) of a run of K controls of ``c`` points each (``_widget_plan``), or of its
    controls ``mine`` (bool per control), by their transposed linear parts ``lt`` and offsets ``off`` into ``out``
    (in the run's point order): float32, each point worked out the same way whichever controls are placed with it.
    ``one``: every control of the run shows the same shape, stored point by point (each of its points multiplied by
    the matrix rows of every control at once, no matrix product per control)."""
    import numpy as np
    if not one:
        qq = q.reshape(-1, c, 3)
        o = out.reshape(-1, c, 3)
        np.matmul(qq if mine is None else qq[mine], lt, out=o)
        o += off[:, None, :]
        return
    s = q.reshape(c, -1, 3)[:, 0]
    o = out.reshape(c, -1, 3)
    tmp = np.empty_like(o)
    np.multiply(s[:, 0, None, None], lt[None, :, 0, :], out=o)
    np.multiply(s[:, 1, None, None], lt[None, :, 1, :], out=tmp)
    o += tmp
    np.multiply(s[:, 2, None, None], lt[None, :, 2, :], out=tmp)
    o += tmp
    o += off[None]


def _box_array(frames, corners):
    """``_box_lines`` of many tubes with the same number of rings: frames (K, F, 4, 4) of each ring, corners
    (K, 4, 3) of each tube in its rings' space. Returns (K, 8 + 16 * (F - 1), 3) end points per tube."""
    import numpy as np
    rings = np.einsum('kfij,kcj->kfci', frames[:, :, :3, :3], corners) + frames[:, :, None, :3, 3]
    edges = np.stack((rings, np.roll(rings, -1, axis=2)), axis=3)                 # (K, F, 4, 2, 3)
    k = len(rings)
    first = edges[:, 0].reshape(k, -1, 3)
    if rings.shape[1] < 2:
        return first
    joins = np.stack((rings[:, :-1], rings[:, 1:]), axis=3)                       # (K, F - 1, 4, 2, 3)
    rest = np.stack((edges[:, 1:], joins), axis=3).reshape(k, -1, 3)             # ring edge i, then join i
    return np.concatenate((first, rest), axis=1)


class _Lines:
    """A skeleton's drawn lines without their colours (Object / Pose Mode): centres / frames / radii of the joints,
    the joints with a sphere, the lines before the axes and after them as (points, joint index per point, int32 line
    index into the points or None: the points are segment end points) triples, the lines a click picks (``_parts``
    ``pick``, the same triples) and the control shape lines they were built from."""
    __slots__ = ("centres", "frames", "radii", "plain", "before", "after", "chunks", "plan", "ctrl_at")


def _sphere_owner(jl, plain):
    """(joints with a sphere, joint index per ``_sphere_ring`` point, ``_sphere_index``) of joint list ``jl``, whose
    joints ``plain`` have a sphere; kept on it."""
    import numpy as np
    got = jl.owners.get("spheres")
    if got is None:
        idx = np.flatnonzero(plain)
        got = jl.owners["spheres"] = (idx, np.tile(idx, 3 * (SEGMENTS + 1)), _sphere_index(len(idx)))
    return got


def _owner(jl, part, rows, per, of=None):
    """Joint index per point of ``part``: ``per`` points for each of ``rows`` (indices into ``of``, else joint
    indices). Kept on joint list ``jl`` while ``rows`` stay the same: a part whose points belong to the same joints
    keeps its colours too (``_paint``)."""
    import numpy as np
    got = jl.owners.get(part)
    if got is None or not np.array_equal(got[0], rows):
        got = jl.owners[part] = (rows, np.repeat(rows if of is None else of[rows], per))
    return got[1]


def _paint(jl, g, sel, rgba, prev=None):
    """``_parts`` (before, axes, after) of lines ``g`` in joint colours ``rgba``; the local axes of the selected
    joints ``sel``. ``prev``: (lines, colours, parts) painted before: a part whose lines belong to the same joints in
    the same colours keeps its colour array (a new frame moves the lines, not their colours)."""
    import numpy as np

    def colour(part, k, idx):
        if prev is not None and prev[0] is not None and prev[1] is rgba:
            old = getattr(prev[0], part)
            if k < len(old) and (old[k][1] is idx or (len(old[k][1]) == len(idx) and np.array_equal(old[k][1], idx))):
                return prev[2][0 if part == "before" else 2][1][k]
        return rgba[idx]

    before = ([p for p, _i, _x in g.before], [colour("before", k, i) for k, (_p, i, _x) in enumerate(g.before)],
              [x for _p, _i, x in g.before])
    after = ([p for p, _i, _x in g.after], [colour("after", k, i) for k, (_p, i, _x) in enumerate(g.after)],
             [x for _p, _i, x in g.after])
    axes = ([], [], [])
    if sel:
        key = frozenset(sel)
        got = jl.owners.get("axes")
        if got is None or got[0] != key:             # the selected joints with a sphere and their axes' colours
            plain = g.plain
            picked = np.array([j for j, nm in enumerate(jl.names) if plain[j] and nm in sel], np.intp)
            axis_rgba = np.array([(*rgb, 1.0) for rgb in AXIS_COLORS], np.float32)
            got = jl.owners["axes"] = (key, picked, np.tile(np.repeat(axis_rgba, 2, axis=0), (len(picked), 1)))
        picked = got[1]
        if len(picked):
            c = g.centres[picked]
            ends = c[:, None, :] + g.frames[picked].transpose(0, 2, 1) * g.radii[picked][:, None, None]   # (K, 3, 3)
            axes[0].append(np.stack((np.broadcast_to(c[:, None, :], ends.shape), ends), axis=2)
                           .reshape(-1, 3).astype(np.float32))
            axes[1].append(got[2])
            axes[2].append(None)
    return before, axes, after


def _part_arrays(parts, perspective):
    """([points], [colours], [int32 line index or None]) of the ``_parts`` of several skeletons in drawing order, the
    axes only in perspective."""
    pts, cols, index = [], [], []
    for before, axes, after in parts:
        for part in (before, axes, after) if perspective else (before, after):
            pts += part[0]
            cols += part[1]
            index += part[2]
    return pts, cols, index


def _segments(pts, cols, index):
    """Lists ``pts`` / ``cols`` of points and colours with their line indices ``index`` as segment end points and
    their colours (a piece without an index is one already)."""
    return ([p if x is None else p[x] for p, x in zip(pts, index)],
            [c if x is None else c[x] for c, x in zip(cols, index)])


def _join(parts, perspective):
    """(points, colours) float32 arrays of the segment end points of the ``_parts`` of several skeletons, the axes
    only in perspective."""
    import numpy as np
    pts, cols = _segments(*_part_arrays(parts, perspective))
    if not pts:
        return np.zeros((0, 3), np.float32), np.zeros((0, 4), np.float32)
    return np.concatenate(pts), np.concatenate(cols)


_COLOURS = {}     # (skeletons drawn, perspective) -> [the parts' colour arrays, them joined, their GPU vertex buffer
                  # or None]: kept while the skeletons are drawn in the same colours (a pose or a frame changes points)


def _join_view(shown, parts, persp):
    """[points, colours, None, ``_COLOURS`` entry, int32 line index into the points] of the ``_parts`` of the
    skeletons ``shown`` draws: the points joined again, the colours and the line index kept while every part still
    has the same colour array (``_paint``) and line index."""
    import numpy as np
    pts, cols, index = _part_arrays(parts, persp)
    joined = np.concatenate(pts) if pts else np.zeros((0, 3), np.float32)
    held = _COLOURS.get(shown)
    if (held is None or len(held[0]) != len(cols) or any(a is not b for a, b in zip(held[0], cols))
            or any(a is not b for a, b in zip(held[3], index)) or len(held[1]) != len(joined)):
        if len(_COLOURS) > 16:
            _COLOURS.clear()
        lines, start = [], 0
        for p, x in zip(pts, index):
            lines.append((np.arange(len(p), dtype=np.intc) if x is None else x) + np.intc(start))
            start += len(p)
        held = _COLOURS[shown] = [cols, np.concatenate(cols) if cols else np.zeros((0, 4), np.float32), None, index,
                                  np.concatenate(lines) if lines else np.zeros(0, np.intc), None]
    return [joined, held[1], None, held, held[4]]


def joined_segments(hit):
    """(points, colours) of joined lines ``hit`` (``_joined``) as segment end points (what its line index draws)."""
    return hit[0][hit[4]], hit[1][hit[4]]


_FORMATS = {}       # attribute name -> GPU vertex format of that attribute alone


def _vertex_buffer(name, data):
    """GPU vertex buffer of float32 rows ``data`` as the shader attribute ``name`` alone (filled in one copy)."""
    from gpu.types import GPUVertBuf, GPUVertFormat
    fmt = _FORMATS.get(name)
    if fmt is None:
        fmt = _FORMATS[name] = GPUVertFormat()
        fmt.attr_add(id=name, comp_type='F32', len=data.shape[1], fetch_mode='FLOAT')
    vbo = GPUVertBuf(fmt, len(data))
    vbo.attr_fill(name, data)
    return vbo
