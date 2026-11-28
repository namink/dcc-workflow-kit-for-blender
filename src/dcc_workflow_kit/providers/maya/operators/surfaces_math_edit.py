# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit NURBS rules on ``Surf`` (bpy-free): Reverse Direction, Attach, Insert Isoparms, Detach, Duplicate NURBS
Patches, Rebuild, opening a periodic direction, and Duplicate Surface Curves (``isoparm``, ``visible_isoparms``).
Shared pieces: surfaces_math_base.py; the operators: surfaces_maya.py and curves_207.py; re-exported by
surfaces_math.py.
"""

from . import curves_math as cm
from .surfaces_math_base import (Crv, EPS, add, mul, _dist, _from_lines_u, transpose, _along, _remap, project,
                                 open_periodic_curve)


# --- Attach ------------------------------------------------------------------------------------------------------

def _edges(s):
    """(name, CV line) of the four edges: U start / end run along V, V start / end run along U."""
    nu, nv = s.num_cvs
    return [("U0", list(s.cvs[0])), ("U1", list(s.cvs[-1])),
            ("V0", [s.cvs[i][0] for i in range(nu)]), ("V1", [s.cvs[i][-1] for i in range(nu)])]


def reverse(s, mode="U"):
    """Maya Reverse Direction: "U" (default) = CV rows reversed, U knots mirrored; "V";
    "BOTH"; "SWAP" = transpose (knots swapped)."""
    mode = mode.upper()
    if mode == "SWAP":
        return transpose(s)
    out = s.copy()
    if mode in ("U", "BOTH"):
        a, b = out.knots_u[0], out.knots_u[-1]
        out.cvs = out.cvs[::-1]
        out.knots_u = [a + b - k for k in reversed(out.knots_u)]
    if mode in ("V", "BOTH"):
        a, b = out.knots_v[0], out.knots_v[-1]
        out.cvs = [row[::-1] for row in out.cvs]
        out.knots_v = [a + b - k for k in reversed(out.knots_v)]
    if mode not in ("U", "V", "BOTH"):
        raise ValueError(mode)
    return out


def _orient(s, edge, to_end):
    """s turned so ``edge`` becomes its U end (to_end) or its U start."""
    if edge[0] == "V":
        s = transpose(s)
    at_end = edge[1] == "1"
    if at_end != to_end:
        s = reverse(s, "U")
    return s


def _join_line(ca, ka, cb, kb, degree, method, bias):
    """The curve Attach (cm.attach) with the ends already chosen: A's end meets B's start."""
    shift = ka[-1] - kb[0]
    if method == "CONNECT":
        return list(ca) + list(cb[1:]), list(ka) + [k + shift for k in kb[degree:]]
    drop_a, drop_b = (degree + 1) // 2, degree // 2 + 1
    blend = add(mul(ca[-1], bias), mul(cb[0], 1.0 - bias))
    return (list(ca[:len(ca) - drop_a]) + [blend] + list(cb[drop_b:]),
            list(ka[:len(ka) - (degree - 1)]) + [k + shift for k in kb[degree:]])


def attach(a, b, method="BLEND", bias=0.5):
    """Maya Attach: the pair of edges (a's vs b's) whose CV lines are nearest (mean CV distance,
    either line direction) joins; copies are turned so a's U end meets b's U start, then the curve rule
    (Blend: bias, joint knot multiplicity 1; Connect: full multiplicity) runs on every CV line along U."""
    best = None
    for ea in _edges(a):
        for eb in _edges(b):
            if len(ea[1]) != len(eb[1]):
                continue
            for flip in (False, True):
                lb = eb[1][::-1] if flip else eb[1]
                dmean = sum(_dist(p, q) for p, q in zip(ea[1], lb)) / len(lb)
                if best is None or dmean < best[0] - 1e-12:
                    best = (dmean, ea[0], eb[0], flip)
    if best is None:
        raise ValueError("no edges with the same CV count")
    _d, e_a, e_b, flip = best
    A = _orient(a, e_a, True)
    B = _orient(b, e_b, False)
    if flip:
        B = reverse(B, "V")
    if A.degree_u != B.degree_u or A.num_cvs[1] != B.num_cvs[1]:
        raise ValueError("surfaces not compatible along the joined edge")
    lines, knots = [], None
    for la, lb in zip(A.lines_u(), B.lines_u()):
        cvs, knots = _join_line(la, A.knots_u, lb, B.knots_u, A.degree_u, method.upper(), bias)
        lines.append(cvs)
    return _from_lines_u(lines, knots, A, periodic_u=False)


# --- Insert / Detach / patch -------------------------------------------------------------------------------------

def open_periodic(s, direction, at=None):
    """A periodic direction re-written as an open (clamped) one over one period starting at ``at`` (default its
    domain start), same shape."""
    t, back = _along(s, direction)
    if not t.periodic_u:
        return s.copy()
    lines, knots = [], None
    for line in t.lines_u():
        c = open_periodic_curve(Crv(line, t.knots_u, t.degree_u, True), at)
        lines.append(c.cvs)
        knots = c.knots
    return back(_from_lines_u(lines, knots, t, periodic_u=False))


def insert_knot(s, direction, t, times=1):
    """Maya Insert Isoparms (Boehm insertion, shape unchanged). A periodic direction is opened first (Maya's
    periodic insert keeps the form)."""
    if times < 1:
        return s.copy()
    w, back = _along(s, direction)
    if w.periodic_u:
        w = open_periodic(w, "U")
    lines, knots = [], None
    for line in w.lines_u():
        cvs, knots = cm.insert_knot(line, w.knots_u, w.degree_u, t, times)
        lines.append(cvs)
    return back(_from_lines_u(lines, knots, w))


def detach(s, direction, t):
    """Maya Detach at the isoparm ``t``: insertion to full multiplicity, split; the pieces keep
    the original parameters. A periodic direction is opened at ``t`` instead: returns (that open surface, None)."""
    w, back = _along(s, direction)
    if w.periodic_u:
        return back(open_periodic(w, "U", t)), None
    firsts, seconds, k1, k2 = [], [], None, None
    for line in w.lines_u():
        (c1, k1), (c2, k2) = cm.split(line, w.knots_u, w.degree_u, t)
        firsts.append(c1)
        seconds.append(c2)
    return back(_from_lines_u(firsts, k1, w)), back(_from_lines_u(seconds, k2, w))


def sub_patch(s, u0, u1, v0, v1):
    """Maya Duplicate NURBS Patches on the patch [u0, u1] x [v0, v1]: detach twice per direction, the original
    parameters kept."""
    out = s
    for direction, a, b in (("U", u0, u1), ("V", v0, v1)):
        w, _back = _along(out, direction)
        if w.periodic_u:
            out = open_periodic(out, direction)
        lo, hi = (out.domain_u() if direction == "U" else out.domain_v())
        if a > lo + EPS:
            out = detach(out, direction, a)[1]
        if b < hi - EPS:
            out = detach(out, direction, b)[0]
    return out


# --- Rebuild ---------------------------------------------------------------------------------------------------

def rebuild(s, spans_u=4, spans_v=4, degree_u=3, degree_v=3):
    """Maya Rebuild (default Uniform, 4 x 4 spans, cubic, range 0..1, keep ends; the kit's own algorithm): per
    direction, every CV line is mapped linearly onto 0..1 and interpolated at the Greville points of the default knots (clamped
    uniform over 0..1, exact). Exact when the new space contains the old one (e.g. 2 -> 4 spans); otherwise
    an approximation (the curve model, equal-arc-length least squares per line, fits worse: per-line arc
    lengths disagree)."""
    out = s
    for direction, spans, deg in (("U", spans_u, degree_u), ("V", spans_v, degree_v)):
        w, _back = _along(out, direction)
        if w.periodic_u:
            out = open_periodic(out, direction)
            w, _back = _along(out, direction)
        deg = max(1, int(deg))
        spans = max(1, int(spans))
        knots = [k / spans for k in cm.clamped_uniform(spans + deg, deg)]
        lines = [project(_remap(Crv(line, w.knots_u, w.degree_u), 0.0, 1.0), knots, deg) for line in w.lines_u()]
        out = _back(_from_lines_u(lines, knots, w, degree_u=deg, periodic_u=False))
    return out


# --- Duplicate Surface Curves --------------------------------------------------------------------

def isoparm(s, direction, t):
    """The isoparm of ``s`` as a curve: direction "U" = Maya ``u[t]`` (runs along V: CV j = column j's U-curve at t,
    knots / degree of V), "V" = ``v[t]`` (runs along U). Exact for non-rational surfaces."""
    nu = len(s.cvs)
    nv = len(s.cvs[0])
    if direction == "U":
        cvs = [cm.evaluate([s.cvs[i][j] for i in range(nu)], s.knots_u, s.degree_u, t) for j in range(nv)]
        return Crv(cvs, list(s.knots_v), s.degree_v, s.periodic_v)
    cvs = [cm.evaluate(list(s.cvs[i]), s.knots_v, s.degree_v, t) for i in range(nu)]
    return Crv(cvs, list(s.knots_u), s.degree_u, s.periodic_u)


def visible_isoparms(s):
    """Maya "Visible surface isoparms" (default) with the surface selected: every span boundary, ends included, U first."""
    out = []
    for direction, knots, degree in (("U", s.knots_u, s.degree_u), ("V", s.knots_v, s.degree_v)):
        lo, hi = knots[degree - 1], knots[len(knots) - degree]
        for t in sorted({round(k, 12) for k in knots if lo - 1e-12 <= k <= hi + 1e-12}):
            out.append((direction, t))
    return out
