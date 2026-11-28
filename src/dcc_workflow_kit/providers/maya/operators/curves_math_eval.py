# SPDX-License-Identifier: GPL-3.0-or-later
"""NURBS curve evaluation core of the curve maths (bpy-free): 3-vector helpers, Maya knot lists and the full knot
vector, basis functions and their derivatives, curve points and derivatives, a linear solver and the cubic through
given points (EP Curve rule). Entry points ``evaluate``, ``interpolate``, ``clamped_uniform``; curves_math.py
re-exports every name, surfaces_math.py builds on them.
"""

import math

# --- small vector helpers --------------------------------------------------------------------------


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def mul(a, s):
    return tuple(x * s for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    return mul(a, 1.0 / n) if n > 1e-15 else a


def lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


# --- knots / evaluation -------------------------------------------------------------------------------

def full(knots):
    """Maya knots -> the full knot vector (phantom first / last knot added)."""
    return [knots[0]] + list(knots) + [knots[-1]]


def maya(full_knots):
    return list(full_knots[1:-1])


def clamped_uniform(n_cvs, degree):
    """Maya's knots of an open uniform curve: 0 (degree times), 1 .. spans - 1, spans (degree times)."""
    spans = n_cvs - degree
    return [0.0] * degree + [float(i) for i in range(1, spans)] + [float(spans)] * degree


def is_clamped_uniform(knots, degree):
    k = list(knots)
    if len(k) < 2 * degree:
        return False
    a, b = k[0], k[-1]
    if any(abs(x - a) > 1e-9 for x in k[:degree]) or any(abs(x - b) > 1e-9 for x in k[-degree:]):
        return False
    inner = [a] + k[degree:len(k) - degree] + [b]
    if len(inner) < 2:
        return False
    step = (b - a) / (len(inner) - 1)
    return step > 1e-12 and all(abs(inner[i] - (a + step * i)) < 1e-7 * max(1.0, abs(b)) for i in range(len(inner)))


def span(U, p, u, n):
    """Index i with U[i] <= u < U[i+1] (n = number of CVs)."""
    if u >= U[n]:
        return n - 1
    if u <= U[p]:
        return p
    lo, hi = p, n
    mid = (lo + hi) // 2
    while u < U[mid] or u >= U[mid + 1]:
        if u < U[mid]:
            hi = mid
        else:
            lo = mid
        mid = (lo + hi) // 2
    return mid


def ders_basis(i, u, p, U, nd):
    """Basis functions and their derivatives up to ``nd`` at u (Piegl & Tiller A2.3)."""
    ndu = [[0.0] * (p + 1) for _ in range(p + 1)]
    ndu[0][0] = 1.0
    left = [0.0] * (p + 1)
    right = [0.0] * (p + 1)
    for j in range(1, p + 1):
        left[j] = u - U[i + 1 - j]
        right[j] = U[i + j] - u
        saved = 0.0
        for r in range(j):
            ndu[j][r] = right[r + 1] + left[j - r]
            temp = ndu[r][j - 1] / ndu[j][r] if ndu[j][r] else 0.0
            ndu[r][j] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        ndu[j][j] = saved
    ders = [[0.0] * (p + 1) for _ in range(nd + 1)]
    for j in range(p + 1):
        ders[0][j] = ndu[j][p]
    for r in range(p + 1):
        s1, s2 = 0, 1
        a = [[0.0] * (p + 1) for _ in range(2)]
        a[0][0] = 1.0
        for k in range(1, nd + 1):
            d = 0.0
            rk, pk = r - k, p - k
            if r >= k:
                a[s2][0] = a[s1][0] / ndu[pk + 1][rk] if ndu[pk + 1][rk] else 0.0
                d = a[s2][0] * ndu[rk][pk]
            j1 = 1 if rk >= -1 else -rk
            j2 = k - 1 if r - 1 <= pk else p - r
            for j in range(j1, j2 + 1):
                a[s2][j] = (a[s1][j] - a[s1][j - 1]) / ndu[pk + 1][rk + j] if ndu[pk + 1][rk + j] else 0.0
                d += a[s2][j] * ndu[rk + j][pk]
            if r <= pk:
                a[s2][k] = -a[s1][k - 1] / ndu[pk + 1][r] if ndu[pk + 1][r] else 0.0
                d += a[s2][k] * ndu[r][pk]
            ders[k][r] = d
            s1, s2 = s2, s1
    r = p
    for k in range(1, nd + 1):
        for j in range(p + 1):
            ders[k][j] *= r
        r *= (p - k)
    return ders


def evaluate(cvs, knots, degree, u, weights=None, deriv=0):
    """Point (deriv 0) or derivative of the curve at Maya parameter u (rational with ``weights``)."""
    U = full(knots)
    n = len(cvs)
    i = span(U, degree, u, n)
    nd = deriv if weights is None else max(deriv, 0)
    ders = ders_basis(i, u, degree, U, nd)
    if weights is None:
        out = (0.0, 0.0, 0.0)
        for j in range(degree + 1):
            out = add(out, mul(cvs[i - degree + j], ders[deriv][j]))
        return out
    if deriv:
        raise ValueError("rational derivatives not needed")
    w = 0.0
    out = (0.0, 0.0, 0.0)
    for j in range(degree + 1):
        k = i - degree + j
        out = add(out, mul(cvs[k], ders[0][j] * weights[k]))
        w += ders[0][j] * weights[k]
    return mul(out, 1.0 / w)


def samples(cvs, knots, degree, count=50, weights=None):
    a, b = knots[0], knots[-1]
    return [evaluate(cvs, knots, degree, a + (b - a) * i / (count - 1), weights) for i in range(count)]


# --- linear solve -----------------------------------------------------------------------------------

def solve(A, B):
    """Gauss-Jordan with partial pivoting; B is a list of 3-vectors (one right-hand side per row)."""
    n = len(A)
    M = [list(A[r]) + list(B[r]) for r in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        pv = M[c][c]
        if abs(pv) < 1e-14:
            raise ValueError("singular system")
        M[c] = [x / pv for x in M[c]]
        for r in range(n):
            if r != c and M[r][c]:
                f = M[r][c]
                M[r] = [x - f * y for x, y in zip(M[r], M[c])]
    return [tuple(M[r][n:]) for r in range(n)]


def _row(U, p, n, u, d):
    i = span(U, p, u, n)
    ders = ders_basis(i, u, p, U, d)
    row = [0.0] * n
    for j in range(p + 1):
        row[i - p + j] = ders[d][j]
    return row


def interpolate(points, params, knots, degree=3, d0=None, d1=None):
    """CVs of the cubic through ``points`` at ``params`` with ``knots``; end conditions = given first derivatives
    (d0, d1) or natural (second derivative 0) — Maya's EP Curve Tool."""
    U = full(knots)
    n = len(points) + 2
    A, B = [], []
    for pnt, u in zip(points, params):
        A.append(_row(U, degree, n, u, 0))
        B.append(tuple(pnt))
    a, b = params[0], params[-1]
    A.append(_row(U, degree, n, a, 1 if d0 is not None else 2))
    B.append(tuple(d0) if d0 is not None else (0.0, 0.0, 0.0))
    A.append(_row(U, degree, n, b, 1 if d1 is not None else 2))
    B.append(tuple(d1) if d1 is not None else (0.0, 0.0, 0.0))
    return solve(A, B)
