# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared pieces of the NURBS surface maths (bpy-free): the ``Crv`` curve tuple and the ``Surf`` surface (u-major CVs,
Maya knot lists, periodic directions with wrap CVs), 3 x 3 rotations, Greville points and basis rows, U / V swaps,
and the curve rules the commands share: making curves compatible (one degree, one knot list), opening a periodic
curve, re-fitting a curve into a spline space. surfaces_math.py re-exports every name.
"""

import math
from collections import namedtuple

from . import curves_math as cm

# --- small helpers --------------------------------------------------------------------------------

Crv = namedtuple("Crv", "cvs knots degree periodic")
Crv.__new__.__defaults__ = (False,)

add, sub, mul, dot, cross, norm = cm.add, cm.sub, cm.mul, cm.dot, cm.cross, cm.norm
EPS = 1e-9


def unit(a):
    n = norm(a)
    if n < 1e-15:
        raise ValueError("zero-length vector")
    return mul(a, 1.0 / n)


def _dist(a, b):
    return norm(sub(a, b))


def _mv(M, v):
    return tuple(sum(M[i][j] * v[j] for j in range(3)) for i in range(3))


def _mm(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _tr(A):
    return [[A[j][i] for j in range(3)] for i in range(3)]


_I3 = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def axis_rot(k, th):
    """Right-hand rotation by ``th`` radians about the axis ``k`` (Rodrigues)."""
    k = unit(k)
    K = [[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]]
    K2 = _mm(K, K)
    s, c = math.sin(th), 1.0 - math.cos(th)
    return [[_I3[i][j] + s * K[i][j] + c * K2[i][j] for j in range(3)] for i in range(3)]


def rot_between(a, b):
    """Minimal rotation taking direction a onto direction b (opposite directions: half turn about any normal)."""
    a, b = unit(a), unit(b)
    v = cross(a, b)
    s = norm(v)
    if s < 1e-12:
        if dot(a, b) > 0:
            return [r[:] for r in _I3]
        helper = (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)
        return axis_rot(cross(a, helper), math.pi)
    return axis_rot(v, math.atan2(s, dot(a, b)))


def domain(knots, degree):
    """Parameter range of a Maya knot list."""
    return knots[degree - 1], knots[len(knots) - degree]


def greville(knots, degree, n):
    """Greville abscissae of the ``n`` CVs of a Maya knot list."""
    U = cm.full(knots)
    return [sum(U[j + 1:j + degree + 1]) / degree for j in range(n)]


def _basis_row(knots, degree, n, t, der=0):
    """Basis values (or derivative ``der``) of all n CVs at t."""
    U = cm.full(knots)
    i = cm.span(U, degree, t, n)
    d = cm.ders_basis(i, t, degree, U, der)
    row = [0.0] * n
    for j in range(degree + 1):
        row[i - degree + j] = d[der][j]
    return row


def _combine(row, pts):
    out = (0.0, 0.0, 0.0)
    for w, p in zip(row, pts):
        if w:
            out = add(out, mul(p, w))
    return out


def _is_uniform(knots):
    d = [b - a for a, b in zip(knots, knots[1:])]
    return bool(d) and min(d) > 1e-12 and max(d) - min(d) < 1e-7 * max(1.0, abs(knots[-1]))


def _reverse_curve(c):
    a, b = c.knots[0], c.knots[-1]
    return Crv(list(reversed(c.cvs)), [a + b - k for k in reversed(c.knots)], c.degree, c.periodic)


def _crv(c):
    """Anything curve-like (Crv, (cvs, knots, degree[, periodic]) or a JSON dict) -> Crv."""
    if isinstance(c, Crv):
        return Crv([tuple(p) for p in c.cvs], list(c.knots), c.degree, c.periodic)
    if isinstance(c, dict):
        return Crv([tuple(p) for p in c["cvs"]], list(c["knots"]), c["degree"], c.get("form") == "periodic")
    cvs, knots, degree = c[0], c[1], c[2]
    return Crv([tuple(p) for p in cvs], list(knots), degree, bool(c[3]) if len(c) > 3 else False)


def _normalise(knots):
    a, b = knots[0], knots[-1]
    return [(k - a) / (b - a) for k in knots] if b - a > 1e-15 else list(knots)


# --- surface ----------------------------------------------------------------------------------------

class Surf:
    """A non-rational NURBS surface in Maya's conventions (see the module docstring)."""

    __slots__ = ("degree_u", "degree_v", "knots_u", "knots_v", "periodic_u", "periodic_v", "cvs")

    def __init__(self, cvs, knots_u, knots_v, degree_u=3, degree_v=3, periodic_u=False, periodic_v=False):
        self.cvs = [[tuple(p) for p in row] for row in cvs]
        self.knots_u = [float(k) for k in knots_u]
        self.knots_v = [float(k) for k in knots_v]
        self.degree_u, self.degree_v = int(degree_u), int(degree_v)
        self.periodic_u, self.periodic_v = bool(periodic_u), bool(periodic_v)
        nu, nv = len(self.cvs), len(self.cvs[0])
        if len(self.knots_u) != nu + self.degree_u - 1 or len(self.knots_v) != nv + self.degree_v - 1:
            raise ValueError("knot count does not match the CV count (%d x %d, knots %d / %d)"
                             % (nu, nv, len(self.knots_u), len(self.knots_v)))

    def copy(self):
        return Surf(self.cvs, self.knots_u, self.knots_v, self.degree_u, self.degree_v, self.periodic_u,
                    self.periodic_v)

    @property
    def num_cvs(self):
        return len(self.cvs), len(self.cvs[0])

    def domain_u(self):
        return domain(self.knots_u, self.degree_u)

    def domain_v(self):
        return domain(self.knots_v, self.degree_v)

    def point(self, u, v):
        nu, nv = self.num_cvs
        ru = _basis_row(self.knots_u, self.degree_u, nu, u)
        rv = _basis_row(self.knots_v, self.degree_v, nv, v)
        out = (0.0, 0.0, 0.0)
        for i, wu in enumerate(ru):
            if wu:
                out = add(out, mul(_combine(rv, self.cvs[i]), wu))
        return out

    # lines: along U (one per V index) / along V (one per U index)
    def lines_u(self):
        nu, nv = self.num_cvs
        return [[self.cvs[i][j] for i in range(nu)] for j in range(nv)]

    def __repr__(self):
        return "Surf(%dx%d, degree %d/%d, knots_u %s, knots_v %s%s%s)" % (
            len(self.cvs), len(self.cvs[0]), self.degree_u, self.degree_v, self.knots_u, self.knots_v,
            ", periodic u" if self.periodic_u else "", ", periodic v" if self.periodic_v else "")


def _from_lines_u(lines, knots_u, s, degree_u=None, periodic_u=None):
    """lines along U (one per V index) -> Surf with s's V side."""
    cvs = [[lines[j][i] for j in range(len(lines))] for i in range(len(lines[0]))]
    return Surf(cvs, knots_u, s.knots_v, s.degree_u if degree_u is None else degree_u, s.degree_v,
                s.periodic_u if periodic_u is None else periodic_u, s.periodic_v)


def transpose(s):
    """Swap U and V (Maya Reverse Direction "Swap")."""
    nu, nv = s.num_cvs
    cvs = [[s.cvs[i][j] for i in range(nu)] for j in range(nv)]
    return Surf(cvs, s.knots_v, s.knots_u, s.degree_v, s.degree_u, s.periodic_v, s.periodic_u)


def _along(s, direction):
    """(surface with the given direction as U, undo function)."""
    if direction.upper() == "U":
        return s, lambda x: x
    if direction.upper() == "V":
        return transpose(s), transpose
    raise ValueError(direction)


# --- curve helpers shared by the commands ------------------------------------------------------------

def project(src, knots, degree):
    """Exact re-representation of curve ``src`` (Crv, already on the target's parameter range) in the spline space
    (knots, degree) that contains it (knot insertion / degree elevation): interpolate at the target's Greville points."""
    n = len(knots) - degree + 1
    g = greville(knots, degree, n)
    A = [_basis_row(knots, degree, n, t) for t in g]
    B = [cm.evaluate(src.cvs, src.knots, src.degree, t) for t in g]
    return cm.solve(A, B)


def _remap(c, a, b):
    """Curve reparameterised linearly onto [a, b] (its knots mapped, CVs unchanged)."""
    c0, c1 = domain(c.knots, c.degree)
    f = (b - a) / (c1 - c0)
    return Crv(c.cvs, [a + (k - c0) * f for k in c.knots], c.degree, c.periodic)


def compatible(curves):
    """Maya loft compatibility: curves that already share degree and knots stay as they are
    (periodic circles stay periodic); otherwise every curve is reparameterised linearly onto the FIRST curve's domain,
    raised to the highest degree and given the union of the interior knots with the maximum multiplicity (a degree-p
    curve's knots gain p_max - p). Returns (knots, degree, [cvs per curve]), shapes unchanged."""
    curves = [_crv(c) for c in curves]
    c0 = curves[0]
    if all(c.degree == c0.degree and len(c.knots) == len(c0.knots)
           and all(abs(x - y) < EPS for x, y in zip(c.knots, c0.knots)) for c in curves):
        return list(c0.knots), c0.degree, [list(c.cvs) for c in curves]
    if any(c.periodic for c in curves):
        # mixed periodic / open curves unknown: periodic ones are opened over their domain first
        curves = [open_periodic_curve(c) if c.periodic else c for c in curves]
        c0 = curves[0]
    p = max(c.degree for c in curves)
    D0, D1 = domain(c0.knots, c0.degree)
    mult = {}
    for c in curves:
        a, b = domain(c.knots, c.degree)
        local = {}
        for k in c.knots:
            if a + EPS < k < b - EPS:
                kk = round(D0 + (k - a) * (D1 - D0) / (b - a), 9)
                local[kk] = local.get(kk, 0) + 1
        for kk, m in local.items():
            mult[kk] = max(mult.get(kk, 0), m + p - c.degree)
    knots = [D0] * p + sorted(k for k, m in mult.items() for _ in range(m)) + [D1] * p
    return knots, p, [project(_remap(c, D0, D1), knots, p) for c in curves]


def open_periodic_curve(c, at=None):
    """Periodic curve -> the same shape as an open (clamped) curve over one period starting at ``at`` (default the
    domain start): the CV list is unrolled over two periods, ``at`` and ``at`` + period are inserted to multiplicity
    = degree (Boehm), the CVs outside are dropped. Also clamps an unclamped open curve (``at`` ignored)."""
    c = _crv(c)
    d = c.degree
    a, b = domain(c.knots, d)
    cvs, knots = list(c.cvs), list(c.knots)
    if c.periodic:
        per = b - a
        t0 = a if at is None else a + ((at - a) % per)
        if t0 > b - EPS:
            t0 = a
        nu = len(cvs) - d
        cvs = cvs[:nu] * 2 + cvs[:d]
        while len(knots) < len(cvs) + d - 1:
            knots.append(knots[len(knots) - nu] + per)
        lo, hi = t0, t0 + per
    else:
        lo, hi = a, b
    for t in (lo, hi):
        times = d - cm.multiplicity(knots, t)
        if times > 0:
            cvs, knots = cm.insert_knot(cvs, knots, d, t, times)
    i0 = min(i for i, k in enumerate(knots) if abs(k - lo) < EPS)
    i1 = max(i for i, k in enumerate(knots) if abs(k - hi) < EPS)
    k_out = knots[i0:i1 + 1]
    return Crv(cvs[i0:i0 + len(k_out) - d + 1], k_out, d, False)
