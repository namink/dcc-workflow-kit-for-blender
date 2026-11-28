# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya NURBS primitives as data: ``nurbs_circle``, ``nurbs_square``, ``nurbs_sphere``, ``nurbs_cylinder``,
``nurbs_cone``, ``nurbs_torus``, ``nurbs_plane``, ``nurbs_cube`` return lists of ``Patch`` (one per Maya shape);
``arc_cvs`` gives circle / arc CVs (periodic cubic circles through the knots, open arcs with Maya's end tangents).
prim_shapes.build picks the builder; prim_history.py makes the Blender curve / surface."""

import math

from .prim_nodes import Patch
from .prim_poly import _apply, _lerp, _orient, _rot_to


# --- NURBS  -----------------------------------------------------------------------------------------------

def _circle_factor(n):
    """Periodic cubic CVs that interpolate a circle at the knots sit at radius 6 / (4 + 2 cos(360/n))."""
    return 6.0 / (4.0 + 2.0 * math.cos(2 * math.pi / n))


def _solve(A, B):
    """Gaussian elimination for small dense systems; B rows are tuples."""
    n = len(A)
    M = [list(A[i]) + list(B[i]) for i in range(n)]
    w = len(B[0])
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        for r in range(n):
            if r != c and M[r][c] != 0.0:
                f = M[r][c] / M[c][c]
                M[r] = [x - f * y for x, y in zip(M[r], M[c])]
    return [tuple(M[i][n + k] / M[i][i] for k in range(w)) for i in range(n)]


def _bspline_row(n, t):
    """Values of the 3 non-zero... all n + 3 cubic basis functions of the clamped uniform knot vector at ``t``."""
    knots = [0] * 4 + list(range(1, n)) + [n] * 4

    def N(i, p, x):
        if p == 0:
            return 1.0 if knots[i] <= x < knots[i + 1] else 0.0
        out = 0.0
        if knots[i + p] != knots[i]:
            out += (x - knots[i]) / (knots[i + p] - knots[i]) * N(i, p - 1, x)
        if knots[i + p + 1] != knots[i + 1]:
            out += (knots[i + p + 1] - x) / (knots[i + p + 1] - knots[i + 1]) * N(i + 1, p - 1, x)
        return out
    return [N(i, 3, t) for i in range(n + 3)]


def _open_fit(points, t0, t1):
    """Open cubic CVs through ``points`` (n + 1, at the knots) with Maya's end rule: the second CV lies on the end
    tangent ``t0`` / ``t1`` (unit) at a third of the first / last chord."""
    n = len(points) - 1
    dim = len(points[0])
    m = n + 3
    P = [None] * m
    P[0], P[-1] = points[0], points[-1]
    c0 = math.dist(points[0], points[1]) / 3
    c1 = math.dist(points[-2], points[-1]) / 3
    P[1] = tuple(points[0][k] + t0[k] * c0 for k in range(dim))
    P[-2] = tuple(points[-1][k] - t1[k] * c1 for k in range(dim))
    unknown = list(range(2, m - 2))
    if not unknown:
        return P
    A, B = [], []
    for j in range(1, n):
        row = _bspline_row(n, j)
        rhs = list(points[j])
        for i in (0, 1, m - 2, m - 1):
            for k in range(dim):
                rhs[k] -= row[i] * P[i][k]
        A.append([row[i] for i in unknown])
        B.append(tuple(rhs))
    for idx, val in zip(unknown, _solve(A, B)):
        P[idx] = val
    return P


def arc_cvs(radius, start, sweep, sections, degree):
    """CVs of a Maya circle / arc in its own plane (x, y), angles in radians. Returns (points, cyclic)."""
    if degree == 1:
        n = max(sections, 1)
        closed = abs(abs(sweep) - 2 * math.pi) < 1e-9
        pts = [(radius * math.cos(start + sweep * i / n), radius * math.sin(start + sweep * i / n)) for i in range(n + 1)]
        return pts, False if not closed else False
    if abs(abs(sweep) - 2 * math.pi) < 1e-9:
        n = max(sections, 4)
        R = radius * _circle_factor(n)
        step = 2 * math.pi / n * (1 if sweep > 0 else -1)
        return [(R * math.cos(start + step * (i - 1)), R * math.sin(start + step * (i - 1))) for i in range(n)], True
    n = max(sections, 1)
    pts = [(radius * math.cos(start + sweep * i / n), radius * math.sin(start + sweep * i / n)) for i in range(n + 1)]
    s = 1 if sweep > 0 else -1
    t0 = (-math.sin(start) * s, math.cos(start) * s)
    e = start + sweep
    t1 = (-math.sin(e) * s, math.cos(e) * s)
    return _open_fit(pts, t0, t1), False


def _frame_to(normal):
    """Rotation taking +Z to ``normal`` (shortest arc), as a function on 3D points."""
    x, y, z = normal
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    x, y, z = x / n, y / n, z / n
    if z > 1 - 1e-12:
        return lambda p: p
    if z < -1 + 1e-12:
        return lambda p: (p[0], -p[1], -p[2])
    kx, ky = -y, x   # Z x n
    s = math.sqrt(kx * kx + ky * ky)
    kx, ky = kx / s, ky / s
    c, sn = z, s
    t = 1 - c
    m = ((t * kx * kx + c, t * kx * ky, sn * ky),
         (t * kx * ky, t * ky * ky + c, -sn * kx),
         (-sn * ky, sn * kx, c))
    return lambda p: _apply(m, p)


def nurbs_circle(a):
    sweep = math.radians(a["sweep"])
    deg = a["degree"]
    # Maya: a cubic circle / arc gets at least 4 sections (s 1 / 2 / 3 -> 4)
    sections = max(a["sections"], 4) if deg == 3 else a["sections"]
    pts, cyclic = arc_cvs(a["radius"], math.pi / 2, sweep, sections, deg)
    rot = _frame_to((a["normalX"], a["normalY"], a["normalZ"]))
    c = (a["centerX"], a["centerY"], a["centerZ"])
    out = [_add(rot((p[0], p[1], 0.0)), c) for p in pts]
    return [Patch("", [out], 2 if deg == 1 else 4, 1, cyclic)]


def _add(p, c):
    return (p[0] + c[0], p[1] + c[1], p[2] + c[2])


def _line(p, q, spans, degree):
    pts = [_lerp(p, q, i / spans) for i in range(spans + 1)]
    if degree == 1:
        return pts
    d = tuple(b - a for a, b in zip(p, q))
    n = math.sqrt(sum(x * x for x in d)) or 1.0
    t = tuple(x / n for x in d)
    return _open_fit(pts, t, t)


def nurbs_square(a):
    w, h, sps, deg = a["sideLength1"], a["sideLength2"], a["spansPerSide"], a["degree"]
    rot = _rot_to((a["normalX"], a["normalY"], a["normalZ"]))
    c = (a["centerX"], a["centerY"], a["centerZ"])
    # Maya's four curves for normal +Y in (x, z): top, left, bottom, right, counter-clockwise from +X+Z
    x, z = w / 2, h / 2
    sides = (("top", (x, z), (-x, z)), ("left", (-x, z), (-x, -z)), ("bottom", (-x, -z), (x, -z)),
             ("right", (x, -z), (x, z)))
    out = []
    for name, p, q in sides:
        pts = [(u, 0.0, v) for u, v in _line(p, q, sps, deg)]
        if rot is not None:
            pts = [_apply(rot, p3) for p3 in pts]
        out.append(Patch(name, [[_add(p3, c) for p3 in pts]], 2 if deg == 1 else 4))
    return out


def _revolve(profile, a, sweep_closed):
    """Surface of revolution about Maya +Y: ``profile`` = list of (radius, y); rows = profile points."""
    deg = a["degree"]
    s0, s1 = math.radians(a["startSweep"]), math.radians(a["endSweep"])
    sweep = s1 - s0
    full = abs(abs(sweep) - 2 * math.pi) < 1e-9
    if full and deg == 3:
        n = max(a["sections"], 4)
        f = _circle_factor(n)
        angles = [s0 + 2 * math.pi / n * (i - 1) for i in range(n)]
        factors = [f] * n
        cyclic = True
    else:
        unit, _c = arc_cvs(1.0, s0, sweep, a["sections"], deg)
        angles = [math.atan2(p[1], p[0]) for p in unit]
        factors = [math.hypot(p[0], p[1]) for p in unit]
        cyclic = False
    rows = []
    for rad, y in profile:
        rows.append([(rad * fct * math.cos(t), y, rad * fct * math.sin(t)) for t, fct in zip(angles, factors)])
    return rows, cyclic


def _finish(rows, a, cyclic_u, cyclic_v, name=""):
    pivot = (a.get("pivotX", 0.0), a.get("pivotY", 0.0), a.get("pivotZ", 0.0))
    flat = [p for row in rows for p in row]
    flat = _orient(flat, a, pivot)
    w = len(rows[0])
    rows = [flat[i * w:(i + 1) * w] for i in range(len(rows))]
    order = 2 if a.get("degree", 3) == 1 else 4
    return Patch(name, rows, order, order, cyclic_u, cyclic_v)


def nurbs_sphere(a):
    r, spans, deg = a["radius"], max(a["spans"], 2), a["degree"]
    prof, _c = arc_cvs(r, -math.pi / 2, math.pi, spans, deg)   # (radius, y) from the bottom pole
    prof = [(p[0], p[1]) for p in prof]
    rows, cyc = _revolve(prof, a, True)
    return [_finish(rows, a, cyc, False)]


def nurbs_cylinder(a):
    r, h = a["radius"], a["heightRatio"] * a["radius"]
    prof = _line((r, -h / 2), (r, h / 2), max(a["spans"], 1), a["degree"])
    rows, cyc = _revolve(prof, a, True)
    return [_finish(rows, a, cyc, False)]


def nurbs_cone(a):
    r, h = a["radius"], a["heightRatio"] * a["radius"]
    prof = _line((r, -h / 2), (0.0, h / 2), max(a["spans"], 1), a["degree"])
    rows, cyc = _revolve(prof, a, True)
    return [_finish(rows, a, cyc, False)]


def nurbs_torus(a):
    R, sr, deg = a["radius"], a["heightRatio"] * a["radius"], a["degree"]
    msw = math.radians(a["minorSweep"])
    spans = max(a["spans"], 2)
    start = math.pi
    if deg == 3 and abs(abs(msw) - 2 * math.pi) < 1e-9:
        start += 2 * math.pi / max(spans, 4)   # periodic CVs: the first one on the inner side
    sec, cyc_minor = arc_cvs(sr, start, msw, spans, deg)
    prof = [(R + p[0], p[1]) for p in sec]
    rows, cyc = _revolve(prof, a, True)
    return [_finish(rows, a, cyc, cyc_minor)]


def _grid(width, length, pu, pv, deg):
    xs = _line((-width / 2,), (width / 2,), pu, deg)
    zs = _line((length / 2,), (-length / 2,), pv, deg)
    return [[(x[0], 0.0, z[0]) for z in zs] for x in xs]


def nurbs_plane(a):
    w = a["width"]
    rows = _grid(w, w * a["lengthRatio"], max(a["patchesU"], 1), max(a["patchesV"], 1), a["degree"])
    return [_finish(rows, a, False, False)]


def nurbs_cube(a):
    w = a["width"]
    L, H = w * a["lengthRatio"], w * a["heightRatio"]
    pu, pv, deg = max(a["patchesU"], 1), max(a["patchesV"], 1), a.get("degree", 3)
    X, Y, Z, nZ = (w, 0, 0), (0, H, 0), (0, 0, L), (0, 0, -L)
    out = []
    # (name, centre, u direction, v direction): Maya's six patches; left / right are the +Z / -Z sides,
    # front / back +X / -X
    faces = (("top", (0, H / 2, 0), X, nZ), ("bottom", (0, -H / 2, 0), nZ, X),
             ("left", (0, 0, L / 2), X, Y), ("right", (0, 0, -L / 2), Y, X),
             ("front", (w / 2, 0, 0), nZ, Y), ("back", (-w / 2, 0, 0), Y, nZ))
    for name, c, du, dv in faces:
        # the face's lower Maya axis (x < y < z) gets patchesU, the higher one patchesV
        au, av = _axis_of(du), _axis_of(dv)
        nu_, nv_ = (pu, pv) if au < av else (pv, pu)
        us = _line((-0.5,), (0.5,), nu_, deg)
        vs = _line((-0.5,), (0.5,), nv_, deg)
        rows = [[tuple(c[k] + du[k] * u[0] + dv[k] * v[0] for k in range(3)) for v in vs] for u in us]
        out.append(_finish(rows, a, False, False, name))
    return out


def _axis_of(v):
    return max(range(3), key=lambda k: abs(v[k]))
