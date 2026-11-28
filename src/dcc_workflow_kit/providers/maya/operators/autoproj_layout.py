# SPDX-License-Identifier: GPL-3.0-or-later
"""UV > Automatic "Into square" shell layout (default options), bpy-free.

Behaviour: gives the same result as Maya 2026.

The default UV > Automatic runs the packed layout with Layout 2 (Into square), Scale Mode 1 (Uniform), Shell
stacking 0 (Bounding box = brick rows), sort by size on, back-and-forth rows on, no prescale, rotate mode 1 (a
shell wider than tall turns 90 degrees) and spacing = Percentage Space / 100. Only each shell's bounding box
takes part in the packing, so the input is one bbox per shell.

Which plane each face takes and how faces form shells (``assign_planes``) also match Maya, for every Planes
choice (``PLANE_SETS``; tests/test_step257_uv_auto.py, tests/test_issue488_auto_planes.py).
The planes (``QUADS``) are kept in float32: they decide faces that lie exactly between two planes.

Input bbox = the shell's extent in the projection plane in **Maya units** (object space; Blender lengths divided
by ``units.maya_unit()``). The packer is not scale invariant: the size comparator has an absolute 1e-6 tolerance
and the area sum starts at 1.19e-7, so other units change ties and grid snapping. A common translation of the
projection does not matter. Arithmetic is float32 (numpy), so the 512-column grid snaps the same way.
"""

import functools
import math
import struct

import numpy as np

F = np.float32
FLT_MAX = F(3.4028235e+38)
COLUMNS = 512                 # skyline buffer of 512 columns
SORT_EPS = F(1e-6)            # size comparator tolerance
GAP_STEP = F(1.1)             # 1.1 column gap between shells in a row
AREA_EPS = F(1.1920929e-07)   # start value of the summed bbox area
TRIES = 10                    # first width + 10 refinements
GOOD = F(0.01)                # width / height mismatch always kept below this
STOP = F(0.05)                # refinement stops below this


class _Shell:
    def __init__(self, index, box):
        self.index = index
        self.umin, self.vmin, self.umax, self.vmax = (F(x) for x in box)
        self.rotated = False
        self.centre = (F(0), F(0))
        self.offset = (F(0), F(0))

    @property
    def height(self):
        return F(self.vmax - self.vmin)


def _rotate(s):
    """Rotate mode 1: a bbox wider than tall turns -90 degrees about its centre,
    (u, v) -> (v + cu - cv, cu + cv - u)."""
    if not F(s.vmax - s.vmin) < F(s.umax - s.umin):
        return
    cu = F(F(s.umin + s.umax) * F(0.5))
    cv = F(F(s.vmin + s.vmax) * F(0.5))
    a, b = F(cu - cv), F(cv + cu)
    umin, umax, vmin, vmax = s.umin, s.umax, s.vmin, s.vmax
    s.umin, s.umax = F(a + vmin), F(a + vmax)
    s.vmax, s.vmin = F(b - umin), F(b - umax)
    s.rotated, s.centre = True, (a, b)


def _cmp(a, b):
    """Shell order: taller first, heights within 1e-6 keep the shell order."""
    ha, hb = a.height, b.height
    if F(hb - SORT_EPS) > ha:
        return 1
    if ha > F(hb + SORT_EPS):
        return -1
    return a.index - b.index


def _brick(shells, width, gap, columns=COLUMNS):
    """Brick rows with back-and-forth rows on: bounding boxes in rows on a skyline of ``columns`` cells, the
    first row left to right, the next right to left, and so on. Returns (packed height, {index: offset})."""
    g = F(width * gap)
    fcols = F(columns)
    dx = F(width / fcols)
    step = F(F(width * GAP_STEP) / fcols)
    floor = np.zeros(columns, dtype=F)
    x, back, top, out = F(0), False, F(0), {}
    for s in shells:
        x0, y0 = F(s.umin - g), F(s.vmin - g)
        w, h = F(F(s.umax + g) - x0), F(F(s.vmax + g) - y0)
        if back:
            t = F(x - F(step + w))
            back = t >= 0.0
            x = t if back else F(0)
        elif width < F(w + x):
            x, back = F(0), True
            t = F(step + F(width - w))
            if t >= 0.0:
                x = t
        i0 = int(F(x / dx))
        i1 = min(int(F(F(w + x) / dx)) + 1, columns)
        if i0 < i1:
            y = max(F(0), F(floor[i0:i1].max()))
            h = F(y + h)
            out[s.index] = (F(x - x0), F(y - y0))
            floor[i0:i1] = h
        else:
            out[s.index] = (F(x - x0), F(F(0) - y0))
        top = max(top, h)
        if not back:
            x = F(F(F(i1) + GAP_STEP) * dx)
    return top, out


def _move_to_square(shells, gap):
    """Square fit: first width = sqrt(summed bbox area); then the next width is sqrt(width * packed height)
    until width and height agree within 5 % (at most 11 packings). The packing with the smallest
    |width - height| / (width + height) is kept (any under 1 % replaces the kept one)."""
    area = AREA_EPS
    for s in shells:
        area = F(area + F(F(s.vmax - s.vmin) * F(s.umax - s.umin)))
    best, kept, tries = FLT_MAX, None, TRIES
    while True:
        width = F(np.sqrt(area))
        height, offsets = _brick(shells, width, gap)
        if not height > 0.0:
            break
        miss = F(abs(F(width - height)) / F(height + width))
        if miss < GOOD or miss < best:
            best, kept = miss, offsets
        area = F(width * height)
        if tries == 0:
            break
        tries -= 1
        if miss < STOP:
            break
    return kept or {}


class Layout:
    """Result of ``layout``: one uniform ``scale`` and, per input shell, whether it turned and its offset."""

    def __init__(self, shells, scale, shift):
        self.shells = shells
        self.scale = scale
        self.shift = shift

    def rotated(self, i):
        return self.shells[i].rotated

    def transform(self, i, u, v):
        """Final UV of the projected point (u, v) (Maya units, same frame as the bbox) of shell ``i``."""
        s = self.shells[i]
        u, v = F(u), F(v)
        if s.rotated:
            a, b = s.centre
            u, v = F(a + v), F(b - u)
        return (float(F(F(F(u + s.offset[0]) + self.shift[0]) * self.scale)),
                float(F(F(F(v + s.offset[1]) + self.shift[1]) * self.scale)))

    def bbox(self, i):
        """Final UV bbox (u0, v0, u1, v1) of shell ``i``."""
        s = self.shells[i]
        lo = (F(F(F(s.umin + s.offset[0]) + self.shift[0]) * self.scale),
              F(F(F(s.vmin + s.offset[1]) + self.shift[1]) * self.scale))
        hi = (F(F(F(s.umax + s.offset[0]) + self.shift[0]) * self.scale),
              F(F(F(s.vmax + s.offset[1]) + self.shift[1]) * self.scale))
        return float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])


def bbox_of(points):
    """(umin, vmin, umax, vmax) of 2D points, in float32."""
    us = [F(p[0]) for p in points]
    vs = [F(p[1]) for p in points]
    return min(us), min(vs), max(us), max(vs)


def layout(boxes, spacing=0.2):
    """Into-square layout of UV shells given by their projected bboxes (umin, vmin, umax, vmax).

    ``boxes`` must be in shell order = ascending lowest face index of each shell (the order only
    decides between shells of equal height). ``spacing`` = Percentage Space (default 0.2). Returns a ``Layout``; ``Layout.transform(i, u, v)`` maps a projected point of shell i to its final UV."""
    gap = F(F(spacing) / F(100.0))
    shells = [_Shell(i, b) for i, b in enumerate(boxes)]
    if not shells:
        return Layout(shells, F(1.0), (F(0), F(0)))
    for s in shells:
        _rotate(s)
    order = sorted(shells, key=functools.cmp_to_key(_cmp)) if len(shells) > 1 else list(shells)
    offsets = _move_to_square(order, gap)
    for s in shells:
        s.offset = offsets.get(s.index, (F(0), F(0)))
    lo_u = min(F(s.umin + s.offset[0]) for s in shells)
    lo_v = min(F(s.vmin + s.offset[1]) for s in shells)
    hi_u = max(F(s.umax + s.offset[0]) for s in shells)
    hi_v = max(F(s.vmax + s.offset[1]) for s in shells)
    wu, wv = F(hi_u - lo_u), F(hi_v - lo_v)
    lo_u, lo_v = F(lo_u - F(wu * gap)), F(lo_v - F(wv * gap))
    grow = F(F(gap + gap) + F(1.0))
    wu, wv = F(wu * grow), F(wv * grow)
    scales = [F(F(1.0) / w) for w in (wu, wv) if w > 0.0]
    scale = min(scales) if scales else F(1.0)
    return Layout(shells, scale, (F(F(F(0) / scale) - lo_u), F(F(F(0) / scale) - lo_v)))


# --- Plane assignment and shells  -------------------

# Every Planes choice (Maya axes, Y up): each plane is given by three of its corners A, B, D (float32
# values). The plane's frame is U = B - A, V = D - A and it faces U x V; UVs are
# u = U'.p + 0.25 + start - U'.A with U' = U / (2 |U|^2), v likewise. ``OFFSETS`` = each plane's start (u, v)
# when the shells are laid out afterwards (Layout on); without layout every plane starts at 0. All frame arithmetic
# is float32 in a fixed order, so faces that lie exactly between two planes and folds right at a shell's
# border come out the same as in Maya.
QUADS = {
    3: (
        ((-0.25, 1, 0.25), (0.25, 1, 0.25), (-0.25, 1, -0.25)),
        ((1, -0.25, 0.25), (1, -0.25, -0.25), (1, 0.25, 0.25)),
        ((-0.25, -0.25, 1), (0.25, -0.25, 1), (-0.25, 0.25, 1)),
    ),
    4: (
        ((-0.493734, -0.672159, -0.655308), (-0.160401, -0.960834, -0.419606), (-0.782409, -0.672159, -0.24706)),
        ((-0.782409, 0.672159, -0.24706), (-0.449076, 0.960834, -0.011357), (-0.493734, 0.672159, -0.655308)),
        ((1.026142, -0.25, -0.097631), (0.859476, -0.25, -0.569035), (1.026142, 0.25, -0.097631)),
        ((-0.25, -0.25, 1), (0.25, -0.25, 1), (-0.25, 0.25, 1)),
    ),
    5: (
        ((-0.25, 0.25, -1), (0.25, 0.25, -1), (-0.25, -0.25, -1)),
        ((-0.579247, -0.820272, -0.341506), (-0.204247, -1.036778, -0.091506), (-0.795753, -0.695272, 0.091506)),
        ((-0.795753, 0.695272, 0.091506), (-0.420753, 0.911778, 0.341506), (-0.579247, 0.820272, -0.341506)),
        ((1, -0.25, 0.25), (1, -0.25, -0.25), (1, 0.25, 0.25)),
        ((-0.25, -0.25, 1), (0.25, -0.25, 1), (-0.25, 0.25, 1)),
    ),
    6: (
        ((-1, -0.25, -0.25), (-1, -0.25, 0.25), (-1, 0.25, -0.25)),
        ((1, -0.25, 0.25), (1, -0.25, -0.25), (1, 0.25, 0.25)),
        ((-0.25, -1, -0.25), (0.25, -1, -0.25), (-0.25, -1, 0.25)),
        ((-0.25, 1, 0.25), (0.25, 1, 0.25), (-0.25, 1, -0.25)),
        ((-0.25, 0.25, -1), (0.25, 0.25, -1), (-0.25, -0.25, -1)),
        ((-0.25, -0.25, 1), (0.25, -0.25, 1), (-0.25, 0.25, 1)),
    ),
    8: (
        ((-0.721688, -0.721688, 0.288675), (-0.32735, -0.82735, 0.57735), (-0.82735, -0.32735, 0.57735)),
        ((0.721688, 0.721688, -0.288675), (0.82735, 0.32735, -0.57735), (0.32735, 0.82735, -0.57735)),
        ((-0.433013, -0.433013, -0.866025), (-0.32735, -0.82735, -0.57735), (-0.82735, -0.32735, -0.57735)),
        ((0.433013, 0.433013, 0.866025), (0.82735, 0.32735, 0.57735), (0.32735, 0.82735, 0.57735)),
        ((-0.82735, 0.32735, -0.57735), (-0.721688, 0.721688, -0.288675), (-0.433013, 0.433013, -0.866025)),
        ((0.32735, -0.82735, 0.57735), (0.721688, -0.721688, 0.288675), (0.433013, -0.433013, 0.866025)),
        ((-0.82735, 0.32735, 0.57735), (-0.433013, 0.433013, 0.866025), (-0.721688, 0.721688, 0.288675)),
        ((0.32735, -0.82735, -0.57735), (0.433013, -0.433013, -0.866025), (0.721688, -0.721688, -0.288675)),
    ),
    12: (
        ((-0.25, -0.719218, -0.738394), (0.25, -0.719218, -0.738394), (-0.25, -0.982084, -0.313068)),
        ((-0.25, 0.982084, -0.313068), (0.25, 0.982084, -0.313068), (-0.25, 0.719218, -0.738394)),
        ((-0.25, 0.719218, 0.738394), (0.25, 0.719218, 0.738394), (-0.25, 0.982084, 0.313068)),
        ((-0.25, -0.982084, 0.313068), (0.25, -0.982084, 0.313068), (-0.25, -0.719218, 0.738394)),
        ((-0.313068, -0.25, -0.982084), (-0.738394, -0.25, -0.719218), (-0.313068, 0.25, -0.982084)),
        ((-0.738394, -0.25, 0.719218), (-0.313068, -0.25, 0.982084), (-0.738394, 0.25, 0.719218)),
        ((0.313068, -0.25, 0.982084), (0.738394, -0.25, 0.719218), (0.313068, 0.25, 0.982084)),
        ((0.738394, -0.25, -0.719218), (0.313068, -0.25, -0.982084), (0.738394, 0.25, -0.719218)),
        ((-0.807946, -0.594829, -0.344095), (-0.669749, -0.818436, 0.08123), (-1.031553, -0.233026, -0.08123)),
        ((0.669749, -0.818436, 0.08123), (0.807946, -0.594829, -0.344095), (0.893356, -0.456633, 0.344095)),
        ((0.893356, 0.456633, 0.344095), (1.031553, 0.233026, -0.08123), (0.669749, 0.818436, 0.08123)),
        ((-1.031553, 0.233026, -0.08123), (-0.893356, 0.456633, 0.344095), (-0.807946, 0.594829, -0.344095)),
    ),
}
OFFSETS = {
    3: ((0, 1), (1, 0), (0, 0)),
    4: ((0, -1), (0, 1), (1, 0), (0, 0)),
    5: ((0, 2), (0, -1), (0, 1), (1, 0), (0, 0)),
    6: ((-1, 0), (1, 0), (0, -1), (0, 1), (0, 2), (0, 0)),
    8: ((0, 0), (1, 2), (0, -1), (1, 1), (0, 2), (1, 0), (0, 1), (1, -1)),
    12: ((0, -2), (0, 2), (0, 1), (0, -1), (3, 1), (0, 0), (1, 0), (3, -1), (-1, -1), (2, -1), (2, 1), (-1, 1)),
}


def _f3(x, y, z):
    """float32 x + y + z, added left to right."""
    return F(F(F(x) + F(y)) + F(z))


def _frame(a, b, d):
    """(normal, U', V', A) of a plane from its corners, in float32: the normal is U x V times the float32
    reciprocal of its length; U' = U / (2 |U|^2), V' likewise."""
    a, b, d = (np.array(p, dtype=F) for p in (a, b, d))
    u, v = (b - a).astype(F), (d - a).astype(F)
    c = np.array([F(u[1] * v[2]) - F(u[2] * v[1]), F(u[2] * v[0]) - F(u[0] * v[2]),
                  F(u[0] * v[1]) - F(u[1] * v[0])], dtype=F)
    n = c * F(F(1) / F(np.sqrt(_f3(c[0] * c[0], c[1] * c[1], c[2] * c[2]))))

    def scaled(w):
        sq = _f3(w[0] * w[0], w[1] * w[1], w[2] * w[2])
        sq = F(sq + sq)
        return (w * F(F(1) / sq)).astype(F) if abs(sq) > 1e-05 else w
    return (tuple(float(x) for x in n), tuple(float(x) for x in scaled(u)), tuple(float(x) for x in scaled(v)),
            tuple(float(x) for x in a))


class PlaneSet:
    """One Planes choice of Automatic: its planes' frames (normal, U', V'; Maya axes) and corners A, the
    "Fewer pieces" candidate threshold, whether a plane takes faces on both sides (3 planes = the three axes,
    both ways) and the pairs of opposite planes (mirrored seed groups)."""

    def __init__(self, count, threshold, both_sides=False, pairs=()):
        made = [_frame(*q) for q in QUADS[count]]
        self.frames = tuple(m[:3] for m in made)
        self.corners = tuple(m[3] for m in made)
        self.offsets = OFFSETS[count]
        self.threshold = F(threshold)
        self.both_sides = both_sides
        self.pairs = pairs

    def dots(self, normal, best_first=False):
        """float32 dot of a face normal with every plane normal (y, x, z order; with ``best_first`` the last plane,
        where the best-plane scan starts, adds x, y, z), absolute with ``both_sides``."""
        x, y, z = (F(c) for c in normal)
        out = [float(_f3(F(b) * y, F(a) * x, F(c) * z)) for a, b, c in (fr[0] for fr in self.frames)]
        if best_first:
            a, b, c = self.frames[-1][0]
            out[-1] = float(_f3(F(a) * x, F(b) * y, F(c) * z))
        return [abs(d) for d in out] if self.both_sides else out

    def uv_maps(self, layout=True):
        """Per plane (U', u0, V', v0): u = U'.p + u0 in float32 (y, x, z order, then u0)."""
        out = []
        for (_n, u, v), a, (su, sv) in zip(self.frames, self.corners, self.offsets):
            if not layout:
                su = sv = 0
            u0 = F(F(F(su) + F(0.25)) - _f3(F(a[1]) * F(u[1]), F(a[0]) * F(u[0]), F(a[2]) * F(u[2])))
            v0 = F(F(F(sv) + F(0.25)) - _f3(F(a[0]) * F(v[0]), F(a[1]) * F(v[1]), F(a[2]) * F(v[2])))
            out.append((u, float(u0), v, float(v0)))
        return out


def _pairs(count):
    return tuple((i, i + 1) for i in range(0, count, 2))


PLANE_SETS = {
    3: PlaneSet(3, 0.5, both_sides=True),
    4: PlaneSet(4, 0.3),
    5: PlaneSet(5, 0.4),
    6: PlaneSet(6, 0.5, pairs=_pairs(6)),
    8: PlaneSet(8, 0.55, pairs=_pairs(8)),
    12: PlaneSet(12, 0.7, pairs=_pairs(12)),
}
CROSS_EPS = 1e-06             # |side| below this counts as touching, not crossing
FAILED = 0x80000000           # a face that would make the shell overlap itself


def face_normals(points, faces):
    """Polygon normals in float32, times the float32 reciprocal of the length."""
    p = np.asarray(points, dtype=F)
    n = len(faces)
    out = np.zeros((n, 3), dtype=F)
    if not n:
        return out
    sizes = np.array([len(f) for f in faces])
    idx = np.zeros((n, int(sizes.max())), dtype=np.int64)
    for i, f in enumerate(faces):
        idx[i, :len(f)] = f
    rows = np.arange(n)
    for k in range(idx.shape[1]):
        a = p[idx[:, k]]
        b = p[idx[rows, np.where(k + 1 < sizes, k + 1, 0)]]
        t = np.stack([(a[:, 1] - b[:, 1]) * (a[:, 2] + b[:, 2]),
                      (a[:, 2] - b[:, 2]) * (a[:, 0] + b[:, 0]),
                      (a[:, 0] - b[:, 0]) * (a[:, 1] + b[:, 1])], axis=1)
        out = np.where((k < sizes)[:, None], out + t, out)
    length = np.sqrt((out[:, 0] * out[:, 0] + out[:, 1] * out[:, 1]) + out[:, 2] * out[:, 2])
    safe = np.where(length != 0, length, F(1))
    inv = np.where(length != 0, F(1) / safe, F(0)).astype(F)
    return (out * inv[:, None]).astype(F)


def _side(x):
    return 0 if abs(x) < CROSS_EPS else (1 if x > 0.0 else -1)


_F32 = struct.Struct("f")


def _f(x):
    """Round a Python float to float32 (segment test arithmetic)."""
    return _F32.unpack(_F32.pack(x))[0]


def crosses(a, b, c, d):
    """Segment test (float32): AB and CD cross properly, i.e. C and D strictly on
    opposite sides of AB and A and B strictly on opposite sides of CD (|side| < 1e-6 = touching)."""
    ax, ay = a
    bx, by = b
    cx, cy = c
    dx, dy = d
    du, dv = _f(bx - ax), _f(by - ay)
    eu, ev = _f(dx - cx), _f(dy - cy)
    k_ab = _f(_f(by * ax) - _f(bx * ay))
    k_cd = _f(_f(dy * cx) - _f(dx * cy))
    c_ab = _side(_f(_f(_f(cy * du) - _f(cx * dv)) + k_ab))
    d_ab = _side(_f(_f(_f(dy * du) - _f(dx * dv)) + k_ab))
    a_cd = _side(_f(_f(_f(ay * eu) - _f(ax * ev)) + k_cd))
    b_cd = _side(_f(_f(_f(by * eu) - _f(bx * ev)) + k_cd))
    return c_ab * d_ab == -1 and a_cd * b_cd == -1


class _Border:
    """The shell's open border edges in order, plus a grid so the crossing scan only tests edges whose
    box meets the new edge (same result as a full scan: a proper crossing needs overlapping boxes)."""

    def __init__(self, uv, cell):
        self.uv = uv
        self.cell = cell
        self.edges = []          # (a, b) in border order
        self.pos = {}            # edge key -> index in ``edges``
        self.grid = {}           # cell -> set of edge keys

    def _cells(self, a, b):
        (ax, ay), (bx, by) = self.uv[a], self.uv[b]
        c = self.cell
        for i in range(int(min(ax, bx) // c), int(max(ax, bx) // c) + 1):
            for j in range(int(min(ay, by) // c), int(max(ay, by) // c) + 1):
                yield i, j

    def append(self, a, b):
        key = (a, b) if a < b else (b, a)
        self.pos[key] = len(self.edges)
        self.edges.append((a, b))
        for c in self._cells(a, b):
            self.grid.setdefault(c, set()).add(key)

    def truncate(self, size):
        for a, b in self.edges[size:]:
            key = (a, b) if a < b else (b, a)
            del self.pos[key]
            for c in self._cells(a, b):
                self.grid[c].discard(key)
        del self.edges[size:]

    def drop(self, lo, hi):
        """Remove positions lo .. hi-1, keeping the order of the rest."""
        tail = self.edges[hi:]
        self.truncate(lo)
        for a, b in tail:
            self.append(a, b)

    def swap(self, i, j):
        e = self.edges
        e[i], e[j] = e[j], e[i]
        for k in (i, j):
            a, b = e[k]
            self.pos[(a, b) if a < b else (b, a)] = k

    def scan(self, a, b, start):
        """Scan of positions start-1 .. 0 for edge (a, b): (index of the same edge or -1, crossed?).
        A crossing counts only before the scan reaches the same edge."""
        key = (a, b) if a < b else (b, a)
        hit = self.pos.get(key, -1)
        if hit >= start:
            hit = -1
        pa, pb = self.uv[a], self.uv[b]
        room = 1e-5 + 1e-6 * max(abs(pa[0]), abs(pa[1]), abs(pb[0]), abs(pb[1]))
        lo_u, hi_u = min(pa[0], pb[0]) - room, max(pa[0], pb[0]) + room
        lo_v, hi_v = min(pa[1], pb[1]) - room, max(pa[1], pb[1]) + room
        seen = set()
        for c in self._cells(a, b):
            for other in self.grid.get(c, ()):
                if other in seen or other == key:
                    continue
                seen.add(other)
                t = self.pos[other]
                if t <= hit or t >= start:
                    continue
                c0, d0 = self.edges[t]
                if a in (c0, d0) or b in (c0, d0):
                    continue
                pc, pd = self.uv[c0], self.uv[d0]
                # boxes apart (with room for float32 rounding): no proper crossing, skip the exact test
                if min(pc[0], pd[0]) > hi_u or max(pc[0], pd[0]) < lo_u or                         min(pc[1], pd[1]) > hi_v or max(pc[1], pd[1]) < lo_v:
                    continue
                if crosses(pa, pb, pc, pd):
                    return hit, True
        return hit, False


def _mirrored(key, mask, pairs):
    """Mirror test: the masks differ in both planes of at least one opposite pair (X-/X+, Y-/Y+, Z-/Z+ for 6)."""
    x = key ^ mask
    return any((x >> i) & 1 and (x >> j) & 1 for i, j in pairs)


def assign_planes(points, faces, optimize=True, planes=6, layout=True):
    """Projection shells of UV > Automatic.

    ``points`` = vertex positions in Maya object space and Maya units (Y up); ``faces`` = vertex index lists of the
    faces to project, in face order (only these take part; others block the flood like unselected faces).
    ``optimize`` = Fewer pieces (default 1); ``planes`` = a ``PLANE_SETS`` key; ``layout`` = the shells are laid
    out afterwards (Layout other than None: each plane's UVs start at its ``OFFSETS`` place, which can move a fold
    across the 1e-6 touching limit). Returns ``[(plane, [face positions])]`` in creation order; ``plane`` indexes
    ``PLANE_SETS[planes].frames``: every face lands in the same shell as in Maya."""
    pset = PLANE_SETS[planes]
    count = len(pset.frames)
    n = len(faces)
    normals = face_normals(points, faces)
    mask = [0] * n
    for fi in range(n):
        if optimize:
            mask[fi] = sum(1 << i for i, d in enumerate(pset.dots(normals[fi])) if F(d) > pset.threshold)
        else:                       # the best plane; scanning from the last plane down, a tie keeps the later one
            dots = pset.dots(normals[fi], best_first=True)
            best = count - 1
            for i in range(count - 2, -1, -1):
                if dots[best] < dots[i]:
                    best = i
            mask[fi] = 1 << best
    maps = pset.uv_maps(layout)
    edge_faces = {}
    for fi, f in enumerate(faces):
        for k in range(len(f)):
            a, b = f[k], f[(k + 1) % len(f)]
            edge_faces.setdefault((a, b) if a < b else (b, a), []).append(fi)
    pts = [tuple(float(c) for c in q) for q in np.asarray(points, dtype=F)]
    spans = sorted(max(abs(pts[f[k]][i] - pts[f[k - 1]][i]) for i in range(3)) for f in faces for k in range(len(f)))
    cell = max((spans[len(spans) // 2] if spans else 1.0) * 2.0, 1e-6)
    shells = []

    def project(fi, allowed, frame, uv, border):
        if not mask[fi] & allowed:
            return False
        U, u0, V, v0 = frame
        f = faces[fi]
        added = [v for v in dict.fromkeys(f) if v not in uv]
        for v in added:
            q = pts[v]
            uv[v] = (float(F(_f3(F(U[1]) * F(q[1]), F(U[0]) * F(q[0]), F(U[2]) * F(q[2])) + F(u0))),
                     float(F(_f3(F(V[1]) * F(q[1]), F(V[0]) * F(q[0]), F(V[2]) * F(q[2])) + F(v0))))
        start = live = len(border.edges)
        for k in range(len(f)):
            a, b = f[k], f[(k + 1) % len(f)]
            hit, crossed = border.scan(a, b, start)
            if crossed:                 # undo: the border keeps its swaps, the new UVs go
                border.truncate(start)
                for v in added:
                    del uv[v]
                mask[fi] |= FAILED
                return False
            if hit >= 0:                # the edge is now inside the shell
                live -= 1
                border.swap(hit, live)
            else:
                border.append(a, b)
        border.drop(live, start)
        mask[fi] = 0
        return True

    def propagate(seed):
        allowed = mask[seed]
        plane = (allowed & -allowed).bit_length() - 1
        frame = maps[plane]
        uv = {}
        border = _Border(uv, cell)
        if not project(seed, allowed, frame, uv, border):
            return
        group, queue, seen, head = [seed], [seed], {seed}, 0
        while head < len(queue):        # breadth first, edges in corner order
            f = faces[queue[head]]
            for k in range(len(f)):
                a, b = f[k], f[(k + 1) % len(f)]
                for h in edge_faces[(a, b) if a < b else (b, a)]:
                    if h in seen:
                        continue
                    seen.add(h)
                    if project(h, allowed, frame, uv, border):
                        queue.append(h)
                        group.append(h)
            head += 1
        shells.append((plane, group))

    # Seeds: faces grouped by candidate count, then by mask (a mask mirrored to an earlier key joins that key),
    # each group in face order (symmetry kept).
    groups = {}
    for fi in range(n):
        m = mask[fi]
        if not m:
            continue
        inner = groups.setdefault(bin(m & 0xffff).count("1"), {})
        key = next((k for k in sorted(inner) if _mirrored(k, m, pset.pairs)), m)
        inner.setdefault(key, []).append(fi)
    for count in sorted(groups):
        for key in sorted(groups[count]):
            for fi in groups[count][key]:
                if mask[fi]:
                    propagate(fi)
    return shells
