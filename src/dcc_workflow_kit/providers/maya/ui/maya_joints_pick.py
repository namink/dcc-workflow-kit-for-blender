# SPDX-License-Identifier: GPL-3.0-or-later
"""Picking drawn Maya joints on screen: distances from the mouse to the drawn segments, the nearest segment per joint,
box / lasso touch tests, joint depths for a marquee, and reuse of the lines last drawn for a click
(``_drawn_pick_lines``). Main entry points: ``pick_memo``, ``_drawn_pick_lines``, ``_touching``, ``_nearest``.
Related: ``maya_joints`` (``pick``, ``screen_distance``, ``region_pick``).
"""

import bpy

from .maya_joints_shapes import _radius_scale
from .maya_joints_arrays import _bone_rows
from .maya_joints_cache import _BUILDS, _PICK, _SCALE, _WORLD, _since, _world_key


def _screen(context, pts):
    """(a, b, ok) screen end points of segments ``pts`` (pairs) in the context region; ok = both in front."""
    from ..operators.preselect import project
    region, rv3d = context.region, context.region_data
    xy, front = project([tuple(p) for p in pts], rv3d.perspective_matrix, region.width, region.height)
    return xy[0::2], xy[1::2], front[0::2] & front[1::2]


def _unpickable(ob, js):
    """Joints of ``js`` that can't be picked: hidden / Template / Reference by a display layer, or Blender's
    unselectable bones."""
    bones = ob.data.edit_bones if ob.mode == 'EDIT' else ob.data.bones
    return {n for n, j in js.items() if j.state is not None or (n in bones and bones[n].hide_select)}


_PICK_PLAN = {}   # skeleton object pointer -> (its ``_PICK`` entry, what clicks reuse of it: ``_pick_plan``)


def _pick_current(context, ob):
    """The lines kept for skeleton ``ob`` (``_PICK``) are still its drawn lines: nothing that can move them reached
    it since they were built (a selection or a change to another skeleton doesn't)."""
    layer = getattr(context, "view_layer", None) or bpy.context.view_layer
    ptr = ob.as_pointer()
    key = _world_key(context.scene, layer)
    if _WORLD[0] != key:
        dirt = _since(_WORLD[0], key)
        if dirt is None or dirt[1] is not None or dirt[3] or ptr in dirt[0]:
            return False
        if _radius_scale(context.scene) != _SCALE[0]:
            return False
    b = _BUILDS.get(ptr)
    return b is None or b.level is None


def _pick_plan(ptr, got):
    """What every click reuses of pick lines ``got`` (``_PICK``): the segments joined once, their joints; per set of
    pickable joints the kept segments, per view their screen ends."""
    import numpy as np
    held = _PICK_PLAN.get(ptr)
    if held is not None and held[0] is got:
        return held[1]
    jl, chunks = got
    pts, owner = [], []
    for p, who, index in chunks:
        if index is not None:
            p, who = p[index], who[index]
        if len(p):
            pts.append(p)
            owner.append(who)
    plan = None
    if pts:
        pts, owner = np.concatenate(pts), np.concatenate(owner)
        plan = {"pts": pts.reshape(-1, 2, 3), "seg": owner[0::2], "pickable": None, "view": None,
                "state": np.array([jl.js[n].state is None for n in jl.names], bool)}
    if len(_PICK_PLAN) > 32:
        _PICK_PLAN.clear()
    _PICK_PLAN[ptr] = (got, plan)
    return plan


def _drawn_pick_lines(context, ob):
    """``_pick_lines`` of skeleton ``ob`` (Object / Pose Mode, drawn as Maya joints) from the lines last drawn for it,
    when nothing has changed them since they were built (``_joined``), + its joint list; else None. A click then
    projects the drawn lines instead of reading the skeleton again; the lines joined, the pickable ones and their
    screen ends in a view are kept for the next click."""
    import numpy as np
    from ..operators.preselect import project
    ptr = ob.as_pointer()
    got = _PICK.get(ptr)
    if got is None or ob.mode == 'EDIT' or not _pick_current(context, ob):
        return None
    plan = _pick_plan(ptr, got)
    if plan is None:
        return None
    jl = got[0]
    bones = ob.data.bones
    hide_select = np.zeros(len(bones), bool)
    bones.foreach_get("hide_select", hide_select)
    # ``_unpickable``: a display layer's state (hidden / Template / Reference) or Blender's unselectable bones
    pickable = plan["state"] & ~hide_select[_bone_rows(ob, jl)]
    if plan["pickable"] is None or not np.array_equal(plan["pickable"], pickable):
        seg = plan["seg"]
        keep = pickable[seg]
        kept, owner = np.unique(seg[keep], return_inverse=True)
        plan.update(pickable=pickable, view=None, kept=[jl.names[i] for i in kept], owner=owner.astype(np.int64),
                    ends=plan["pts"][keep].reshape(-1, 3).astype(np.float64))
    if not len(plan["owner"]):
        return [], np.zeros((0, 2)), np.zeros((0, 2)), np.zeros(0, bool), np.zeros(0, np.int64), jl
    region, rv3d = context.region, context.region_data
    persp = rv3d.perspective_matrix
    view = (tuple(tuple(r) for r in persp), region.width, region.height)
    if plan["view"] != view:
        xy, front = project(plan["ends"], persp, region.width, region.height)
        plan.update(view=view, a=np.ascontiguousarray(xy[0::2]), b=np.ascontiguousarray(xy[1::2]),
                    ok=front[0::2] & front[1::2], columns=None)
    return list(plan["kept"]), plan["a"], plan["b"], plan["ok"], plan["owner"], jl


_PICK_MEMO = [None]     # while one click is picked (``pick_memo``): {(skeleton, mode, region, mouse): distances}


class pick_memo:
    """Within one click nothing moves between the coarse object test and the joint pick: ``screen_distance`` reads
    each skeleton once (a skeleton read costs milliseconds per hundred joints). Nests; the outermost one ends it."""

    def __enter__(self):
        self._outer = _PICK_MEMO[0] is not None
        if not self._outer:
            _PICK_MEMO[0] = {}
        return self

    def __exit__(self, *_exc):
        if not self._outer:
            _PICK_MEMO[0] = None


def _segment_columns(a, b):
    """What ``preselect.segment_distance`` works out of the screen segments a[i]-b[i] ((S, 2) each) before it looks
    at the mouse, one array per coordinate: start x, start y, direction x, y, long enough, squared length (1 where
    not)."""
    import numpy as np
    ax, ay = np.ascontiguousarray(a[:, 0], np.float64), np.ascontiguousarray(a[:, 1], np.float64)
    dx, dy = b[:, 0] - ax, b[:, 1] - ay
    ll = dx * dx + dy * dy
    long_ = ll > 1e-12
    return ax, ay, dx, dy, long_, np.where(long_, ll, 1.0)


def _segment_distances(p, columns):
    """``preselect.segment_distance`` (its distances) from point ``p`` to the segments of ``_segment_columns``: the
    same steps in the same order, one coordinate array at a time."""
    import numpy as np
    ax, ay, dx, dy, long_, ll = columns
    t = np.where(long_, ((p[0] - ax) * dx + (p[1] - ay) * dy) / ll, 0.0)
    t = np.clip(t, 0.0, 1.0)
    return np.hypot(ax + dx * t - p[0], ay + dy * t - p[1])


_NEAREST = [None]   # (segment owners, joint count, segment order by joint, first segment of each joint) of a click


def _nearest(owner, n, d, ok):
    """The smallest ``d`` of the ``ok`` segments of each of ``n`` joints (``owner``: joint per segment), inf where it
    has none. The segments sorted by joint are kept for the owners of the drawn lines (every click uses them)."""
    import numpy as np
    got = _NEAREST[0]
    if got is None or got[0] is not owner or got[1] != n:
        cnt = np.bincount(owner, minlength=n) if len(owner) else np.zeros(n, np.intp)
        order = starts = None
        if len(cnt) == n and n and cnt.all():           # every joint has a segment: one minimum per run
            order = np.argsort(owner, kind='stable')
            starts = np.concatenate(([0], np.cumsum(cnt)[:-1]))
        got = _NEAREST[0] = (owner, n, order, starts)
    if got[2] is None:
        near = np.full(n, np.inf)
        np.minimum.at(near, owner[ok], d[ok])
        return near
    return np.minimum.reduceat(np.where(ok, d, np.inf)[got[2]], got[3])


def _seg_cross(p1, p2, q1, q2):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def _in_poly(pt, poly):
    x, y = pt
    inside = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def segments_touch(a, b, poly):
    """Does any segment a[i]-b[i] touch the closed polygon ``poly`` (screen points)?"""
    edges = [(poly[i - 1], poly[i]) for i in range(len(poly))]
    for p, q in zip(a, b):
        if _in_poly(p, poly) or _in_poly(q, poly):
            return True
        if any(_seg_cross(p, q, e0, e1) for e0, e1 in edges):
            return True
    return False


_DEPTHS = {}    # id(joints) -> (joints, {name: ``depth``}, {name: position}): ``region_pick`` of the same joints


def _region_depths(js):
    """{name: ``depth(js, name)``} and {name: position in ``js``} of every joint, kept while ``js`` is the same (a
    drawn skeleton's joint list lasts until the skeleton changes)."""
    held = _DEPTHS.get(id(js))
    if held is not None and held[0] is js:
        return held[1], held[2]
    depths = {}
    for name in js:
        chain, p = [], name
        while p not in depths:
            chain.append(p)
            p = js[p].parent
            if p not in js:              # the top: no parent among the joints
                d = 0
                break
        else:
            d = depths[p] + 1
        for n in reversed(chain):
            depths[n] = d
            d += 1
    if len(_DEPTHS) > 8:
        _DEPTHS.clear()
    index = {n: i for i, n in enumerate(js)}
    _DEPTHS[id(js)] = (js, depths, index)
    return depths, index


def _box_bounds(pg):
    """(x min, x max, y min, y max) of a polygon that is an upright rectangle given corner by corner (a box select's
    region), else None."""
    if len(pg) != 4:
        return None
    (ax, ay), (bx, by), (cx, cy), (dx, dy) = pg.tolist()
    if not ((ay == by and bx == cx and cy == dy and dx == ax) or (ax == bx and by == cy and cx == dx and dy == ay)):
        return None
    return min(ax, cx), max(ax, cx), min(ay, cy), max(ay, cy)


def _touching(a, b, poly):
    """``segments_touch`` for each segment a[i]-b[i] ((S, 2) arrays) at once: a bool per segment."""
    import numpy as np
    pg = np.asarray(poly, np.float64).reshape(-1, 2)
    box = _box_bounds(pg)

    def inside(p):
        x, y = p[:, 0], p[:, 1]
        if box is not None:
            # the crossing rule below on an upright rectangle: only its two upright sides count, each at its own x
            # for any y, so a point is inside from the low side up to (not including) the high side
            x0, x1, y0, y1 = box
            return (x >= x0) & (x < x1) & (y >= y0) & (y < y1)
        res = np.zeros(len(p), bool)
        for i in range(len(pg)):
            (x1, y1), (x2, y2) = pg[i], pg[i - 1]
            if y1 != y2:              # a level edge never crosses the ray
                res ^= ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1)
        return res

    out = inside(a) | inside(b)
    rest = np.flatnonzero(~out)          # a segment with an end inside touches already: the crossings of the others
    if not len(rest):
        return out
    a, b = a[rest], b[rest]
    ax, ay, bx, by = a[:, 0], a[:, 1], b[:, 0], b[:, 1]
    cross = np.zeros(len(rest), bool)
    for i in range(len(pg)):
        (ex0, ey0), (ex1, ey1) = pg[i - 1], pg[i]
        d1 = (ex1 - ex0) * (ay - ey0) - (ey1 - ey0) * (ax - ex0)
        d2 = (ex1 - ex0) * (by - ey0) - (ey1 - ey0) * (bx - ex0)
        d3 = (bx - ax) * (ey0 - ay) - (by - ay) * (ex0 - ax)
        d4 = (bx - ax) * (ey1 - ay) - (by - ay) * (ex1 - ax)
        cross |= (d1 * d2 < 0) & (d3 * d4 < 0)
    out[rest] = cross
    return out
