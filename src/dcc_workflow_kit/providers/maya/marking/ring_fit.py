# SPDX-License-Identifier: GPL-3.0-or-later
"""Keeps a marking menu inside the visible region and off the area border bands (``fit_ring``): radial boxes slide
inside, the list goes under / beside / above the ring, list rows flow around the bands into columns
(``_settle_list``, ``_flow``). Geometry only (any layout with ``items`` / ``radial`` / ``params``); called by
``engine.Session`` for the top menu and each submenu."""

import math


def _move(item, dx, dy):
    r = item.rect
    item.rect = (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy)
    if item.opt_rect:
        o = item.opt_rect
        item.opt_rect = (o[0] + dx, o[1] + dy, o[2] + dx, o[3] + dy)


def _bbox(items):
    return (min(i.rect[0] for i in items), min(i.rect[1] for i in items),
            max(i.rect[2] for i in items), max(i.rect[3] for i in items))


def _slide(lo, hi, low, high):
    """Offset that moves [lo, hi] inside [low, high] (towards ``low`` if it can't fit)."""
    if hi - lo > high - low:
        return low - lo
    return max(low - lo, min(0.0, high - hi))


MIN_COLUMN_ROWS = 4


# --- area borders (#56) --------------------------------------------------------------------------------
# ``edges`` = rectangles (x0, y0, x1, y1) where nothing a region draws is seen: the gaps between the window's areas
# and the rim Blender draws over every area edge after all regions (draw.window_edges). A list row or radial box
# overlapping one is cut, so rows go below horizontal bands (one column kept, like
# Maya's list) and whole lists / boxes move sideways off vertical ones.

def _horizontal(band):
    return band[2] - band[0] >= band[3] - band[1]


def _overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _rel_edges(edges, cx, cy):
    return [(e[0] - cx, e[1] - cy, e[2] - cx, e[3] - cy) for e in edges]


def _below_bands(row_top, height, x0, x1, bands):
    """Top of a row (``height`` high, from x0 to x1) moved down until it overlaps no horizontal band."""
    moved = True
    while moved:
        moved = False
        for b in bands:
            if _overlaps((x0, row_top - height, x1, row_top), b):
                row_top = b[1]
                moved = True
    return row_top


def _flow(rows, top, floor, w, gap_unit, edges=(), x_first=None):
    """Lay list rows (in order) out top-down from ``top`` in columns of width ``w`` from ``x_first`` (default: where
    the first row is): a divider = ``gap_unit`` (Layout), a row that would overlap a horizontal band goes below it,
    a row under ``floor`` starts the next column, a column on a vertical band moves right past it (the
    next columns follow). Returns the number of columns."""
    hbands = [b for b in edges if _horizontal(b)]
    vbands = [b for b in edges if not _horizontal(b)]
    xs = [rows[0].rect[0] if x_first is None else x_first]
    for _round in range(len(vbands) + 2):
        col, y, prev = 0, top, None
        for it in rows:
            r = it.rect
            height = r[3] - r[1]
            gap = (it.key - prev - 1) * gap_unit if prev is not None else 0.0
            prev = it.key
            if col >= len(xs):
                xs.append(xs[-1] + w)
            row_top = _below_bands(y - gap, height, xs[col], xs[col] + w, hbands)
            if row_top - height < floor and y != top:
                col += 1
                if col >= len(xs):
                    xs.append(xs[-1] + w)
                row_top = _below_bands(top, height, xs[col], xs[col] + w, hbands)
            _move(it, xs[col] - r[0], row_top - r[3])
            y = row_top - height
        del xs[col + 1:]
        if not vbands:
            break
        moved = False
        for c, (bx0, by0, _bx1, by1) in enumerate(_column_boxes(rows)):
            x = xs[c] if c == 0 else max(xs[c], xs[c - 1] + w)
            hit = True
            while hit:
                hit = next((b for b in vbands if _overlaps((x, by0, x + w, by1), b)), None)
                if hit:
                    x = hit[2]
            moved = moved or x != xs[c]
            xs[c] = x
        if not moved:
            break
    return len(xs)


def _column_boxes(rows):
    """Bounding box of each list column, left to right."""
    cols = {}
    for it in rows:
        cols.setdefault(round(it.rect[0], 3), []).append(it)
    return [_bbox(cols[k]) for k in sorted(cols)]


def _off_bands(rect, edges, x0, y0, x1, y1, others=()):
    """Offset that moves one (radial) box off the bands it overlaps, inside the bounds and clear of ``others`` (the
    boxes already placed): the shortest way, towards the ring centre (0, 0) when two are as short. Candidates put a
    box side against a band side, so a box between two close borders jumps over the nearer one."""
    if not any(_overlaps(rect, b) for b in edges):
        return 0.0, 0.0
    xs, ys = {0.0}, {0.0}
    for b in edges:
        if _horizontal(b):
            ys.update((b[1] - rect[3], b[3] - rect[1]))
        else:
            xs.update((b[0] - rect[2], b[2] - rect[0]))
    for o in others:      # beside / above / below a box already placed (or the list's column)
        xs.update((o[0] - rect[2], o[2] - rect[0]))
        ys.update((o[1] - rect[3], o[3] - rect[1]))
    xs.update((x0 - rect[0], x1 - rect[2]))
    ys.update((y0 - rect[1], y1 - rect[3]))
    mx, my = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2

    def cost(d):
        return (abs(d[0]) + abs(d[1]), math.hypot(mx + d[0], my + d[1]))
    for dx, dy in sorted(((dx, dy) for dx in xs for dy in ys), key=cost):
        r = (rect[0] + dx, rect[1] + dy, rect[2] + dx, rect[3] + dy)
        if (r[0] >= x0 - 1e-6 and r[2] <= x1 + 1e-6 and r[1] >= y0 - 1e-6 and r[3] <= y1 + 1e-6
                and not any(_overlaps(r, b) for b in edges) and not any(_overlaps(r, o) for o in others)):
            return dx, dy
    return 0.0, 0.0


def _lift(rows, top, floor, ceiling, w, gap_unit, edges):
    """Top from which the rows, pushed down by the bands, end above ``floor`` in one column (moved up at most to
    ``ceiling``)."""
    for _round in range(4):
        _flow(rows, top, -math.inf, w, gap_unit, [b for b in edges if _horizontal(b)])
        over = floor - min(it.rect[1] for it in rows)
        higher = min(top + over, ceiling)
        if over <= 0 or higher <= top:
            break
        top = higher
    return top


def _settle_list(rows, top, floor, x0, x1, gap_unit, edges, center=None, lift=None):
    """Re-flow placed list rows around the bands (``_flow``) inside [x0, x1]: ``center`` = x the columns are
    centred on (the list under the ring), ``lift`` = how high the rows may move up to stay in one column (None:
    they stay). The columns start as near as they can to where they would be without vertical bands."""
    w = rows[0].rect[2] - rows[0].rect[0]
    if lift is not None:
        top = _lift(rows, top, floor, lift, w, gap_unit, edges)
    hbands = [b for b in edges if _horizontal(b)]
    xf = rows[0].rect[0]
    _flow(rows, top, floor, w, gap_unit, hbands, xf)
    bx0, _by0, bx1, _by1 = _bbox(rows)
    if center is not None:
        xf += center - (bx0 + bx1) / 2
        bx0, bx1 = bx0 + center - (bx0 + bx1) / 2, bx1 + center - (bx0 + bx1) / 2
    want = xf + _slide(bx0, bx1, x0, x1)

    def place(x):
        n = _flow(rows, top, floor, w, gap_unit, edges, x)
        lo, _y0, hi, _y1 = _bbox(rows)
        return n, lo >= x0 - 1e-6 and hi <= x1 + 1e-6
    n, ok = place(want)
    if ok:
        return
    vbands = [b for b in edges if not _horizontal(b)]
    cands = {x0} | {b[2] for b in vbands} | {b[0] - k * w for b in vbands for k in range(1, n + 2)}
    for x in sorted(cands, key=lambda v: abs(v - want)):
        if place(x)[1]:
            return
    # No place clear of the vertical bands (more columns than the free spans between borders hold): side by side
    # inside the window where the fewest rows cross a vertical border line, nearest to ``want`` among those.
    best = None
    for x in sorted(cands | {want}, key=lambda v: abs(v - want)):
        _flow(rows, top, floor, w, gap_unit, hbands, x)
        lo, _y0, hi, _y1 = _bbox(rows)
        x += _slide(lo, hi, x0, x1)
        _flow(rows, top, floor, w, gap_unit, hbands, x)
        crossed = sum(1 for it in rows if any(_overlaps(it.rect, b) for b in vbands))
        if best is None or crossed < best[0]:
            best = (crossed, x)
    _flow(rows, top, floor, w, gap_unit, hbands, best[1])


def fit_ring(layout, center, bounds, edges=()):
    """Keep a menu's items inside ``bounds`` (region x0, y0, x1, y1). The centre stays the press point the gesture
    directions start from: returns 0.0 (how far the centre moved).

    Radial boxes slide inside; the list goes under the ring (Maya), else beside it in one column (the side with no
    radial submenu on the way), else above it, else is pushed up from under the ring. Maya draws the whole
    menu higher only when the list would run past the *screen* bottom;
    Blender can't draw outside its window, which is smaller, so lifting at the window edge moved the ring
    off the pointer in the middle of the view and killed the radial marks — so only the list moves.
    ``edges`` = area border bands (region pixels): no box or row is left overlapping one."""
    _place(layout, center, bounds, edges)
    return 0.0


def _place(layout, center, bounds, edges):
    """fit_ring's placement around a fixed centre."""
    cx, cy = center
    x0, y0, x1, y1 = bounds[0] - cx, bounds[1] - cy, bounds[2] - cx, bounds[3] - cy  # centre-relative
    edges = _rel_edges(edges, cx, cy)
    placed = []
    rows = [it for it in layout.items if it.kind == "list"]
    if rows and edges:
        # Maya's ring is compact (radius 55): a box moved off a border must not land in the column the
        # list takes under the ring, or the list is drawn over it.
        lx0, _ly0, lx1, ly1 = _bbox(rows)
        placed.append((lx0, y0 - 1.0, lx1, ly1))
    for it in layout.radial.values():
        _move(it, _slide(it.rect[0], it.rect[2], x0, x1), _slide(it.rect[1], it.rect[3], y0, y1))
        if edges:
            _move(it, *_off_bands(it.rect, edges, x0, y0, x1, y1, placed))
            placed.append(it.rect)
    rows = [it for it in layout.items if it.kind == "list"]
    if not rows:
        return
    gap_unit = layout.params.list_gap / 2
    lx0, ly0, lx1, ly1 = _bbox(rows)
    floor, lift = y0, y1
    if not layout.radial:
        dx, dy = _slide(lx0, lx1, x0, x1), _slide(ly0, ly1, y0, y1)
    else:
        gap = layout.params.list_gap
        r = layout.params.radius
        rx0, ry0, rx1, ry1 = _bbox(list(layout.radial.values()))
        rx0, ry0, rx1, ry1 = min(rx0, -r), min(ry0, -r), max(rx1, r), max(ry1, r)
        h, w = ly1 - ly0, lx1 - lx0
        # Maya keeps the list in one column under the ring (it runs off a
        # small window) and moves it when the screen ends; it never wraps into columns. A
        # column that doesn't fit under the ring goes beside it (the side with no radial submenu on the way, else
        # right; moved up it would cover the ring's S boxes and the gestures), then above it; only a list taller than the window gets more columns,
        # still under the ring.
        if h > y1 - y0 and ly1 - y0 >= MIN_COLUMN_ROWS * layout.params.item_h:
            if edges:
                _settle_list(rows, ly1, y0, x0, x1, gap_unit, edges, center=0.0)
                return
            _flow(rows, ly1, y0, w, gap_unit)
            bx0, _by0, bx1, _by1 = _bbox(rows)
            dx = -(bx0 + bx1) / 2
            dx += _slide(bx0 + dx, bx1 + dx, x0, x1)
            for it in rows:
                _move(it, dx, 0.0)
            return
        floor = y0
        below = (0.0, 0.0)                                    # as laid out (under the ring)
        above = (0.0, ry1 + gap - ly0)
        # beside the ring with the list gap, or nearer to it (never on it) when the gap would put the column past
        # the window side
        right_x = rx1 + gap if rx1 + gap + w <= x1 or x1 - w < rx1 else x1 - w
        left_x = rx0 - gap if rx0 - gap - w >= x0 or x0 + w > rx0 else x0 + w
        right = (right_x - lx0, -h / 2 - ly0)
        left = (left_x - lx1, -h / 2 - ly0)
        dx = dy = None
        lift = y1           # how high re-flowed rows may go: not into the ring when under it
        if ly0 >= y0 and ly1 <= y1:
            dx, dy = _slide(lx0, lx1, x0, x1), 0.0
            lift = None
        else:
            # the way to the column crosses the ring's E (or W) side: take the side without a radial submenu there
            # (RMB on a mesh: E = UV opens on the way, W = Vertex doesn't)
            def opens(names):
                return any(layout.radial.get(n) is not None and layout.radial[n].sub is not None for n in names)
            sides = (left, right) if opens(("E", "NE", "SE")) and not opens(("W", "NW", "SW")) else (right, left)
            boxes = [it.rect for it in layout.radial.values()]
            start = [(it.rect, it.opt_rect) for it in rows]
            for cdx, cdy in sides:
                if lx0 + cdx >= x0 and lx1 + cdx <= x1 and h <= y1 - y0:
                    ddy = cdy + _slide(ly0 + cdy, ly1 + cdy, y0, y1)
                    for it in rows:
                        _move(it, cdx, ddy)
                    if edges:   # moved off an area border, the column must still stand clear of the ring
                        _settle_list(rows, max(it.rect[3] for it in rows), y0, x0, x1, gap_unit, edges, lift=y1)
                    if not any(_overlaps(it.rect, b) for it in rows for b in boxes):
                        return
                    for it, (r, o) in zip(rows, start):
                        it.rect, it.opt_rect = r, o
            if ly0 + above[1] >= y0 and ly1 + above[1] <= y1:
                dx, dy = _slide(lx0, lx1, x0, x1), above[1]
                floor = ry1 + gap
            else:
                dx, dy = _slide(lx0, lx1, x0, x1), _slide(ly0, ly1, y0, y1)
        if w > x1 - x0:
            dx = x0 - lx0
    for it in rows:
        _move(it, dx, dy)
    if edges:
        _settle_list(rows, max(it.rect[3] for it in rows), floor, x0, x1, gap_unit, edges, lift=lift)
