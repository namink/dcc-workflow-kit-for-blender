# SPDX-License-Identifier: GPL-3.0-or-later
"""Conversion between ``Surf`` (Maya knot lists) and Blender's legacy NURBS surface data (bpy-free): orders, cyclic /
endpoint / Bezier flags per direction, the CV grid, and the piecewise-linear Maya -> Blender parameter map. Entry
points ``blender_grid``, ``from_blender_grid``, ``map_param``; used by surfaces_maya.py, re-exported by
surfaces_math.py.
"""

from . import curves_math as cm
from .surfaces_math_base import Crv, EPS, Surf, domain, _is_uniform, _from_lines_u, _along, open_periodic_curve


# --- Blender legacy NURBS representation -----------------------------------

def _direction_mode(knots, degree, periodic, n):
    if degree == 1:
        return "CYCLIC" if periodic else "ENDPOINT"
    if periodic and _is_uniform(knots) and n - degree >= degree + 1:
        return "CYCLIC"
    if not periodic and cm.is_clamped_uniform(knots, degree):
        return "ENDPOINT"
    return "BEZIER"


def _bezier_lines(t):
    """U of ``t`` (open or periodic) Boehm-decomposed to Bezier spans: every interior knot at multiplicity degree."""
    if t.periodic_u or not (cm.multiplicity(t.knots_u, t.knots_u[0]) >= t.degree_u
                            and cm.multiplicity(t.knots_u, t.knots_u[-1]) >= t.degree_u):
        t = _open_any(t)
    d = t.degree_u
    a, b = t.domain_u()
    inner = sorted({round(k, 12) for k in t.knots_u if a + EPS < k < b - EPS})
    lines, knots = [], None
    for line in t.lines_u():
        cvs, kn = list(line), list(t.knots_u)
        for u in inner:
            times = d - cm.multiplicity(kn, u)
            if times > 0:
                cvs, kn = cm.insert_knot(cvs, kn, d, u, times)
        lines.append(cvs)
        knots = kn
    return lines, knots


def _open_any(t):
    """U clamped at its domain ends (periodic or unclamped open)."""
    lines, knots = [], None
    for line in t.lines_u():
        c = open_periodic_curve(Crv(line, t.knots_u, t.degree_u, t.periodic_u))
        lines.append(c.cvs)
        knots = c.knots
    return _from_lines_u(lines, knots, t, periodic_u=False)


def _breaks(knots, degree, mode, n):
    """Piecewise-linear map Maya parameter -> Blender parameter: [(maya_t, blender_t), ...] at the breakpoints."""
    a, b = domain(knots, degree)
    k = degree + 1
    if mode == "CYCLIC":
        nu = n - degree
        if degree == 1:
            pts = sorted(set(knots[degree - 1:len(knots) - degree + 1]))
            return [(t, i + 1.0) for i, t in enumerate(pts)] if len(pts) == nu + 1 else [(a, k - 1.0),
                                                                                       (b, k - 1.0 + nu)]
        return [(a, k - 1.0), (b, k - 1.0 + nu)]
    if mode == "ENDPOINT":
        if degree == 1:
            return [(t, float(i)) for i, t in enumerate(knots)]
        spans = n - degree
        return [(a, 0.0), (b, float(spans))]
    pts = sorted({round(x, 12) for x in knots if a - EPS <= x <= b + EPS})
    return [(t, float(i)) for i, t in enumerate(pts)]


def blender_grid(s):
    """Surf -> Blender legacy NURBS surface data (exact geometry):
    rows[j][i] = CV i along u of row j (Blender row j = Maya V index j, ``spline.points[j * nu + i]``), orders,
    cyclic / endpoint / bezier flags per direction, plus map_u / map_v = [(maya_t, blender_t)] breakpoints of the
    piecewise-linear parameter map. Clamped uniform -> endpoint; periodic uniform -> cyclic with the unique CVs only
    (Maya's and Blender's domains both start on CVs 0..degree); degree 1 -> order 2 endpoint (cyclic when periodic);
    anything else -> Boehm decomposition to Bezier spans + bezier + endpoint (non-uniform periodic opened first)."""
    out = {}
    cur = s
    for direction in ("U", "V"):
        t, back = _along(cur, direction)
        n = t.num_cvs[0]
        mode = _direction_mode(t.knots_u, t.degree_u, t.periodic_u, n)
        if mode == "CYCLIC":
            nu = n - t.degree_u
            lines = [line[:nu] for line in t.lines_u()]
            t2 = _from_lines_u(lines, [float(i) for i in range(nu + t.degree_u - 1)], t, periodic_u=False)
            brk = _breaks(t.knots_u, t.degree_u, mode, n)
        elif mode == "ENDPOINT":
            t2 = t
            brk = _breaks(t.knots_u, t.degree_u, mode, n)
        else:
            lines, knots = _bezier_lines(t)
            t2 = _from_lines_u(lines, knots, t, periodic_u=False)
            brk = _breaks(knots, t.degree_u, mode, len(lines[0]))
        cur = back(t2)
        key = direction.lower()
        out["order_" + key] = t.degree_u + 1
        out["cyclic_" + key] = mode == "CYCLIC"
        out["endpoint_" + key] = mode != "CYCLIC"
        out["bezier_" + key] = mode == "BEZIER"
        out["map_" + key] = brk
    nu, nv = cur.num_cvs
    out["rows"] = [[cur.cvs[i][j] for i in range(nu)] for j in range(nv)]
    if out["order_u"] > nu or out["order_v"] > nv:
        raise ValueError("order larger than the CV count")
    return out


def map_param(brk, t):
    """Maya parameter -> Blender parameter through blender_grid's map_u / map_v (clamped to the domain)."""
    if t <= brk[0][0]:
        return brk[0][1]
    for (a, x), (b, y) in zip(brk, brk[1:]):
        if t <= b:
            return min(y, x + (t - a) * (y - x) / (b - a)) if b > a else x
    return brk[-1][1]


def _knots_from_flags(n, order, cyclic, endpoint, bezier):
    d = order - 1
    if cyclic:
        return [float(i - d + 1) for i in range(n + 2 * d - 1)], True   # curves_maya._periodic_knots
    if bezier and endpoint and d > 1 and (n - 1) % d == 0:
        m = (n - 1) // d
        return [float(x) for x in range(m + 1) for _ in range(d)], False
    if endpoint or d == 1:
        return cm.clamped_uniform(n, d), False
    return [float(i) for i in range(1, n + d)], False       # Blender plain uniform (unclamped)


def from_blender_grid(rows, order_u, order_v, cyclic_u=False, cyclic_v=False, endpoint_u=True, endpoint_v=True,
                      bezier_u=False, bezier_v=False):
    """Blender legacy NURBS surface (rows[j][i], flags) -> Surf with Maya knot lists: endpoint = clamped uniform
    0..spans, cyclic = periodic uniform (wrap CVs added), bezier + endpoint = knots of multiplicity degree."""
    nv, nu = len(rows), len(rows[0])
    du, dv = order_u - 1, order_v - 1
    ku, pu = _knots_from_flags(nu, order_u, cyclic_u, endpoint_u, bezier_u)
    kv, pv = _knots_from_flags(nv, order_v, cyclic_v, endpoint_v, bezier_v)
    cvs = [[tuple(rows[j][i]) for j in range(nv)] for i in range(nu)]
    if pv:
        cvs = [row + row[:dv] for row in cvs]
    if pu:
        cvs = cvs + cvs[:du]
    return Surf(cvs, ku, kv, du, dv, pu, pv)
