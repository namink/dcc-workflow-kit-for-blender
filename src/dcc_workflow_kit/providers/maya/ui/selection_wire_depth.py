# SPDX-License-Identifier: GPL-3.0-or-later
"""The depth offset that keeps the selection wire on top of its own shading (no z-fighting) without showing through
other objects: the per-object rule from the evaluated bounds and the view's pixel scale (``depth_bias``) and the same
rule row by row for many objects (``_biases_rows``; ``_corner_array`` keeps the last redraw's corner arrays).
Related: ``selection_wire.depth_biases`` chooses between them.
"""

DEPTH_BIAS = 1e-4          # Legacy limit; retained for dormant, X-ray and native Make Live wires.
DEPTH_BIAS_PIXELS = 1.0    # At most one pixel of the bounds' projected depth change.
DEPTH_BIAS_MAX_SPAN = 1 / 16
DEPTH_BIAS_THIN_RATIO = 1 / 8
DEPTH_BIAS_THIN_SPAN = 1 / 4

_corners = []              # [(bound boxes, their ``_corner_array``)] of the last redraw


def depth_bias(ob, depsgraph, projection, viewport):
    """Conservative NDC offset from evaluated bounds and this view's pixel scale.

    No positive floor is safe for an arbitrarily thin / distant object. An
    unusable projection or bounds therefore returns zero rather than falling
    back to the old fixed offset. Bounds are a heuristic, not an occlusion
    guarantee for closely spaced surfaces or unrelated foreground objects.
    """
    import math
    from mathutils import Vector
    try:
        width, height = viewport
        if not all(math.isfinite(v) and v > 0 for v in (width, height)):
            return 0.0
        bounds = tuple(tuple(c) for c in ob.evaluated_get(depsgraph).bound_box)
        if (len(bounds) != 8 or any(len(c) != 3 for c in bounds)
                or not all(math.isfinite(v) for c in bounds for v in c)):
            return 0.0
        matrix = projection @ ob.matrix_world
        xs, ys, depths = [], [], []
        for corner in bounds:
            clip = matrix @ Vector((*corner, 1.0))
            if (not all(math.isfinite(v) for v in clip) or clip.w <= 1e-8
                    or clip.z <= -clip.w or clip.z >= clip.w):
                return 0.0  # Behind the eye, intersecting a clip plane, or unstable.
            xs.append(clip.x / clip.w)
            ys.append(clip.y / clip.w)
            depths.append(clip.z / clip.w)
        if not all(math.isfinite(v) for values in (xs, ys, depths) for v in values):
            return 0.0
        span = max(depths) - min(depths)
        pixels = max(1.0, (max(xs) - min(xs)) * width * 0.5,
                     (max(ys) - min(ys)) * height * 0.5)
        if not math.isfinite(span) or not math.isfinite(pixels) or span <= 0.0:
            return 0.0
        bias = min(DEPTH_BIAS, span * DEPTH_BIAS_MAX_SPAN, span * DEPTH_BIAS_PIXELS / pixels)

        # For a thin box viewed obliquely, its overall depth span includes the
        # long sides. Cap against the projected separation along each thin axis.
        sizes = [max(c[i] for c in bounds) - min(c[i] for c in bounds) for i in range(3)]
        world = ob.matrix_world
        lengths = [math.sqrt(sum((world[row][i] * sizes[i]) ** 2 for row in range(3))) for i in range(3)]
        if not all(math.isfinite(v) for v in lengths):
            return 0.0
        longest = max(lengths)
        for axis, length in enumerate(lengths):
            if length <= 0.0 or length >= longest * DEPTH_BIAS_THIN_RATIO:
                continue
            other_axes = tuple(i for i in range(3) if i != axis)
            separations = [abs(depths[i] - depths[j])
                           for i in range(8) for j in range(i + 1, 8)
                           if bounds[i][axis] != bounds[j][axis]
                           and all(bounds[i][k] == bounds[j][k] for k in other_axes)]
            if not separations:
                return 0.0
            bias = min(bias, min(separations) * DEPTH_BIAS_THIN_SPAN)
        return bias
    except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError):
        return 0.0


_PAIRS = [(i, j) for i in range(8) for j in range(i + 1, 8)]     # every two corners of a bound box
ARRAY_FROM = 8      # from this many objects on ``depth_biases`` computes in arrays (fewer: one by one is quicker)
_NO_BOX = [0.0] * 24


_WORD_ONES = 0x0101010101010101     # eight numpy booleans read as one 64-bit word, all True


def _all_rows(flags):
    """``flags.all(axis=1)`` of an (n, 8 k) bool array, eight booleans read as one 64-bit word (numpy reduces a short
    axis row by row, a fraction of a millisecond a call for thousands of rows)."""
    import numpy as np
    words = np.ascontiguousarray(flags).reshape(len(flags), -1).view(np.uint64)
    out = words[:, 0] == np.uint64(_WORD_ONES)
    for j in range(1, words.shape[1]):
        out &= words[:, j] == np.uint64(_WORD_ONES)
    return out


def _fold_rows(fn, values):
    """``values.max(axis=1)`` / ``values.min(axis=1)`` (``fn``: ``np.maximum`` / ``np.minimum``) of an (n, m) array,
    one column at a time. The same value, NaN included; only the sign of a zero result can differ from numpy's
    reduction, and the depth offset never depends on it (a zero span or size gives the same result either way)."""
    out = values[:, 0].copy()
    for j in range(1, values.shape[1]):
        fn(out, values[:, j], out=out)
    return out


def _corner_array(boxes):
    """(corners, unread, homogeneous corners, finite, sizes) of ``boxes`` (24 floats each, None = unreadable): (n, 8, 3)
    float64 corners, the indices of the unreadable boxes, the corners with a fourth coordinate 1, which boxes are
    finite, and each box's size along x, y and z. The same box tuples as last time (the same objects with unchanged
    geometry, e.g. every redraw of an orbit) give the arrays made last time."""
    import operator
    from itertools import chain
    import numpy as np
    last = _corners[0] if _corners else None
    if last is not None and len(last[0]) == len(boxes) and all(map(operator.is_, last[0], boxes)):
        return last[1]
    n = len(boxes)
    corners = np.fromiter(chain.from_iterable(_NO_BOX if box is None else box for box in boxes),
                          np.float64, n * 24).reshape(n, 8, 3)
    unread = [k for k, box in enumerate(boxes) if box is None]
    with np.errstate(all='ignore'):
        sizes = np.stack([_fold_rows(np.maximum, corners[:, :, i]) - _fold_rows(np.minimum, corners[:, :, i])
                          for i in range(3)], axis=1)
    got = (corners, unread, np.concatenate((corners, np.ones((n, 8, 1))), axis=2),
           _all_rows(np.isfinite(corners).reshape(n, 24)), sizes)
    _corners[:] = [(list(boxes), got)]
    return got


def _biases_rows(worlds, ok, corners, homogeneous, finite, sizes, projection, width, height):
    """The depth offsets of the rows given (``ok``: readable so far, changed in place). Every operation works row by
    row, so the offsets of some rows alone are the ones the whole set gives them."""
    import numpy as np
    n = len(worlds)
    with np.errstate(all='ignore'):
        ok &= finite & _all_rows(np.isfinite(worlds).reshape(n, 16))
        clip = np.einsum('nij,nkj->nki', np.array(projection, np.float64) @ worlds, homogeneous)
        w, z = clip[..., 3], clip[..., 2]
        # behind the eye, intersecting a clip plane, or unstable
        ok &= (_all_rows(np.isfinite(clip).reshape(n, 32)) & _all_rows(w > 1e-8) & _all_rows(z > -w)
               & _all_rows(z < w))
        xs, ys, depths = clip[..., 0] / w, clip[..., 1] / w, z / w
        ok &= _all_rows(np.isfinite(xs)) & _all_rows(np.isfinite(ys)) & _all_rows(np.isfinite(depths))
        span = _fold_rows(np.maximum, depths) - _fold_rows(np.minimum, depths)
        pixels = np.maximum(np.maximum(1.0, (_fold_rows(np.maximum, xs) - _fold_rows(np.minimum, xs)) * width * 0.5),
                            (_fold_rows(np.maximum, ys) - _fold_rows(np.minimum, ys)) * height * 0.5)
        ok &= np.isfinite(span) & np.isfinite(pixels) & (span > 0.0)
        bias = np.minimum(np.minimum(DEPTH_BIAS, span * DEPTH_BIAS_MAX_SPAN), span * DEPTH_BIAS_PIXELS / pixels)
        # a thin box viewed obliquely: cap against the projected separation along each thin axis
        lengths = np.sqrt(((worlds[:, :3, :3] * sizes[:, None, :]) ** 2).sum(axis=1))
        finite_lengths = np.isfinite(lengths)
        ok &= finite_lengths[:, 0] & finite_lengths[:, 1] & finite_lengths[:, 2]
        longest = _fold_rows(np.maximum, lengths)
        a = np.array([p[0] for p in _PAIRS])
        b = np.array([p[1] for p in _PAIRS])
        for axis in range(3):
            thin = np.flatnonzero((lengths[:, axis] > 0.0) & (lengths[:, axis] < longest * DEPTH_BIAS_THIN_RATIO))
            if not thin.size:      # no thin box along this axis: nothing to cap
                continue
            others = [i for i in range(3) if i != axis]
            c, d = corners[thin], depths[thin]
            along = ((c[:, a, axis] != c[:, b, axis])
                     & (c[:, a, others[0]] == c[:, b, others[0]])
                     & (c[:, a, others[1]] == c[:, b, others[1]]))
            found = along.any(1)
            ok[thin] &= found
            least = np.where(along, np.abs(d[:, a] - d[:, b]), np.inf).min(1)
            bias[thin] = np.where(found, np.minimum(bias[thin], least * DEPTH_BIAS_THIN_SPAN), bias[thin])
    return np.where(ok, bias, 0.0)
