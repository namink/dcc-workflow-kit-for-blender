# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya NURBS surface maths, bpy-free.

Conventions (Maya's):
- knot lists are Maya lists (no phantom end knots: len = CVs + degree - 1);
- ``Surf.cvs[u][v]`` is u-major like Maya ``.cv[u][v]`` (cvs[i] = the CV row of U index i, running along V);
- periodic directions carry the ``degree`` wrapping CVs (the last ``degree`` CVs repeat the first ones);
- every rule is rotation-free, so it works in any right-handed frame (Y-up coordinates as in Maya, or Blender's
  Z-up ones: Maya (X, Y, Z) -> Blender (X, -Z, Y) is a rotation). Revolve takes its axis, Extrude Distance its
  direction, as vectors in the caller's frame.
Outputs are non-rational (Maya's outputs here all have weight 1).

Code: surfaces_math_base (Crv, Surf, rotations, compatible curves), surfaces_math_edit (Reverse, Attach, Insert,
Detach, Patches, Rebuild, isoparms), surfaces_math_blender (Blender NURBS surface data); this module keeps Loft,
Revolve, Extrude, Birail 1 and Boundary / Square, and re-exports the other modules' names.
"""

import math

from . import curves_math as cm
from .surfaces_math_base import (Crv, add, sub, mul, dot, cross, norm, EPS, unit, _dist, _mv, _mm, _tr, _I3,
                                 axis_rot, rot_between, domain, greville, _basis_row, _combine, _is_uniform,
                                 _reverse_curve, _crv, _normalise, Surf, _from_lines_u, transpose, _along, project,
                                 _remap, compatible, open_periodic_curve)  # noqa: F401
from .surfaces_math_edit import (_edges, reverse, _orient, _join_line, attach, open_periodic, insert_knot, detach,
                                 sub_patch, rebuild, isoparm, visible_isoparms)  # noqa: F401
from .surfaces_math_blender import (_direction_mode, _bezier_lines, _open_any, _breaks, blender_grid, map_param,
                                    _knots_from_flags, from_blender_grid)  # noqa: F401


# --- Loft ----------------------------------------------------------------------------------------------

def _circle_tangent(P0, P1, P2, at=0):
    a, b = sub(P1, P0), sub(P2, P0)
    n = cross(a, b)
    if norm(n) < 1e-12:
        return unit(sub(P2, P0))
    c = add(P0, mul(add(mul(cross(n, a), dot(b, b)), mul(cross(b, n), dot(a, a))), 1.0 / (2 * dot(n, n))))
    return unit(cross(n, sub((P0, P1, P2)[at], c)))


def _lagrange_d0(ts, P):
    """Derivative at ts[0] of the polynomial through P at ts."""
    m = len(P)
    out = (0.0, 0.0, 0.0)
    for i in range(m):
        others = [ts[j] for j in range(m) if j != i]
        den = 1.0
        for o in others:
            den *= ts[i] - o
        dn = 0.0
        for a in range(len(others)):
            pr = 1.0
            for b in range(len(others)):
                if b != a:
                    pr *= ts[0] - others[b]
            dn += pr
        out = add(out, mul(P[i], dn / den))
    return out


def end_direction(P, at_end=False):
    """Loft interpolation end tangent (direction of travel): 3 points = the circle through them, >= 4 points = the
    derivative of the cubic through the first (last) 4 points with chord-length parameters."""
    if len(P) == 3:
        return _circle_tangent(P[0], P[1], P[2], 2 if at_end else 0)
    Q = P[-4:][::-1] if at_end else P[:4]
    ts = [0.0]
    for i in range(1, 4):
        ts.append(ts[-1] + _dist(Q[i], Q[i - 1]))
    d = unit(_lagrange_d0(ts, Q))
    return mul(d, -1.0) if at_end else d


def _interp_open(P, params, knots):
    n = len(P)
    if n == 2:
        return [P[0], cm.lerp(P[0], P[1], 1 / 3.0), cm.lerp(P[0], P[1], 2 / 3.0), P[1]]
    if _dist(P[1], P[0]) < 1e-15 and all(_dist(p, P[0]) < 1e-15 for p in P):
        return [P[0]] * (n + 2)          # a collapsed CV column (all curves share the point)
    d0 = mul(end_direction(P), _dist(P[1], P[0]) / (params[1] - params[0]))
    d1 = mul(end_direction(P, True), _dist(P[-1], P[-2]) / (params[-1] - params[-2]))
    return cm.interpolate(P, params, knots, 3, d0, d1)


def _interp_periodic(P, knots):
    """Periodic uniform cubic through P at v = domain start + k (Maya periodic list), n unique CVs + 3 wrap."""
    n = len(P)
    t0 = knots[2]
    rows = []
    for k in range(n):
        b = _basis_row(knots, 3, n + 3, t0 + k)
        row = [0.0] * n
        for i, w in enumerate(b):
            row[i % n] += w
        rows.append(row)
    c = cm.solve(rows, [tuple(p) for p in P])
    return list(c) + list(c[:3])


def _auto_reverse(curves):
    """Auto reverse (on by default; the kit's criterion): flip a curve whose ends are nearer the previous curve's
    opposite ends."""
    out = [curves[0]]
    for c in curves[1:]:
        a0, a1 = out[-1].cvs[0], out[-1].cvs[-1]
        b0, b1 = c.cvs[0], c.cvs[-1]
        if _dist(a0, b1) + _dist(a1, b0) < _dist(a0, b0) + _dist(a1, b1):
            c = _reverse_curve(c)
        out.append(c)
    return out


def loft(curves, uniform=True, close=False, degree=3, section_spans=1, auto_reverse=True):
    """Maya Loft. U = the compatible curves, V = across them (curve k = iso v_k)."""
    curves = [_crv(c) for c in curves]
    if len(curves) < 2:
        raise ValueError("loft needs 2 or more curves")
    if auto_reverse:
        curves = _auto_reverse(curves)
    knots_u, p, cc = compatible(curves)
    periodic_u = curves[0].periodic and all(c.periodic for c in curves) and knots_u == list(curves[0].knots)
    n, ncv = len(cc), len(cc[0])
    ss = max(1, int(section_spans))
    if degree == 1:
        if close:       # unknown: the first curve again at the end (closed form)
            cc = cc + [cc[0]]
            n += 1
        chord = [0.0]
        for k in range(1, n):
            chord.append(chord[-1] + sum(_dist(cc[k][i], cc[k - 1][i]) for i in range(ncv)) / ncv)
        kv = []
        for k in range(n - 1):
            for s in range(ss):
                kv.append(chord[k] + (chord[k + 1] - chord[k]) * s / ss)
        kv.append(chord[-1])
        cols = []
        for i in range(ncv):
            col = []
            for k in range(n - 1):
                for s in range(ss):
                    col.append(cm.lerp(cc[k][i], cc[k + 1][i], s / float(ss)))
            col.append(cc[-1][i])
            cols.append(col)
        return Surf(cols, knots_u, kv, p, 1, periodic_u, False)
    if degree != 3:
        raise ValueError("loft degree 1 or 3")
    if uniform:
        params = [float(k) for k in range(n)]
    else:
        params = [0.0]
        for k in range(1, n):
            params.append(params[-1] + sum(_dist(cc[k][i], cc[k - 1][i]) for i in range(ncv)) / ncv)
    if close:
        if n < 3:
            raise ValueError("a closed loft needs 3 or more curves")
        kv = [float(k) for k in range(n + 5)]
        cols = [_interp_periodic([cc[k][i] for k in range(n)], kv) for i in range(ncv)]
        # section spans on a closed loft unknown: ignored
        return Surf(cols, knots_u, kv, p, 3, periodic_u, True)
    kv = [params[0]] * 3 + [params[1]] * 3 if n == 2 else [params[0]] * 2 + params + [params[-1]] * 2
    cols = [_interp_open([cc[k][i] for k in range(n)], params, kv) for i in range(ncv)]
    s = Surf(cols, knots_u, kv, p, 3, periodic_u, False)
    if ss > 1:
        for k in range(n - 1):
            for j in range(1, ss):
                s = insert_knot(s, "V", params[k] + (params[k + 1] - params[k]) * j / ss)
    return s


# --- Revolve --------------------------------------------------------------------------------------------

def revolve(profile, axis=(0.0, 1.0, 0.0), pivot=(0.0, 0.0, 0.0), start=0.0, end=360.0, segments=8, degree=3):
    """Maya Revolve. U = the profile, V = around ``axis`` through ``pivot``; the point at sweep
    angle a = the profile point turned by -a about the axis (right-hand rule). Angles in degrees."""
    pr = _crv(profile)
    s = max(1, int(segments))
    k_ax = unit(axis)
    pivot = tuple(pivot)
    sweep = end - start
    if abs(sweep) < 1e-12:
        raise ValueError("revolve sweep is 0")
    full_turn = abs(abs(sweep) - 360.0) < 1e-9
    d = math.radians(sweep) / s
    a0 = math.radians(start)

    def turn(q, a):
        return add(pivot, _mv(axis_rot(k_ax, -a), sub(q, pivot)))

    def foot(q):
        return add(pivot, mul(k_ax, dot(sub(q, pivot), k_ax)))

    rows = []
    if degree == 1:
        for q in pr.cvs:
            rows.append([turn(q, a0 + k * d) for k in range(s + 1)])
        kv = [k * 2.0 * math.sin(abs(d) / 2.0) for k in range(s + 1)]      # chord of a unit circle
        return Surf(rows, pr.knots, kv, pr.degree, 1, pr.periodic, False)
    if degree != 3:
        raise ValueError("revolve degree 1 or 3")
    if full_turn:
        f = 6.0 / (4.0 + 2.0 * math.cos(d))
        for q in pr.cvs:
            fq = foot(q)
            ring = [add(fq, mul(sub(turn(q, a0 + (k - 1) * d), fq), f)) for k in range(s)]
            rows.append(ring + ring[:3])
        kv = [float(i - 2) for i in range(s + 5)]
        return Surf(rows, pr.knots, kv, pr.degree, 3, pr.periodic, True)
    kv = [0.0] * 3 + [float(k) for k in range(1, s)] + [float(s)] * 3
    params = [float(k) for k in range(s + 1)]
    sgn = 1.0 if sweep > 0 else -1.0
    for q in pr.cvs:
        fq = foot(q)
        r = _dist(q, fq)
        pts = [turn(q, a0 + k * d) for k in range(s + 1)]
        if r < 1e-12:
            rows.append([pts[0]] * (s + 3))
            continue
        chord = 2.0 * r * math.sin(abs(d) / 2.0)

        def tangent(a):         # d/da of turn(q, a) = -k x (point - foot), times the sweep direction
            return mul(unit(cross(k_ax, sub(turn(q, a), fq))), -sgn)
        rows.append(cm.interpolate(pts, params, kv, 3, mul(tangent(a0), chord), mul(tangent(a0 + s * d), chord)))
    return Surf(rows, pr.knots, kv, pr.degree, 3, pr.periodic, False)


# --- Extrude --------------------------------------------------------------------------------------------

def newell(P):
    """Unit Newell normal of the polygon P (right-hand rule)."""
    n = (0.0, 0.0, 0.0)
    m = len(P)
    for a in range(m):
        p, q = P[a], P[(a + 1) % m]
        n = add(n, ((p[1] - q[1]) * (p[2] + q[2]), (p[2] - q[2]) * (p[0] + q[0]), (p[0] - q[0]) * (p[1] + q[1])))
    return unit(n)


def _unique(c):
    return c.cvs[:len(c.cvs) - c.degree] if c.periodic else c.cvs


def _smallest_axis(P):
    """Unit normal of the least-squares plane through the points P (eigenvector of the smallest eigenvalue of
    their covariance; cyclic Jacobi sweeps on the symmetric 3 x 3 matrix)."""
    m = len(P)
    c = [sum(p[k] for p in P) / m for k in range(3)]
    A = [[sum((p[i] - c[i]) * (p[j] - c[j]) for p in P) for j in range(3)] for i in range(3)]
    V = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for _sweep in range(50):
        off = abs(A[0][1]) + abs(A[0][2]) + abs(A[1][2])
        if off < 1e-30:
            break
        for p, q in ((0, 1), (0, 2), (1, 2)):
            if abs(A[p][q]) < 1e-300:
                continue
            theta = (A[q][q] - A[p][p]) / (2.0 * A[p][q])
            t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
            cs = 1.0 / math.sqrt(t * t + 1.0)
            sn = t * cs
            for k in range(3):          # A <- J^T A J, V <- V J
                akp, akq = A[k][p], A[k][q]
                A[k][p], A[k][q] = cs * akp - sn * akq, sn * akp + cs * akq
            for k in range(3):
                apk, aqk = A[p][k], A[q][k]
                A[p][k], A[q][k] = cs * apk - sn * aqk, sn * apk + cs * aqk
            for k in range(3):
                vkp, vkq = V[k][p], V[k][q]
                V[k][p], V[k][q] = cs * vkp - sn * vkq, sn * vkp + cs * vkq
    i = min(range(3), key=lambda k: A[k][k])
    return unit((V[0][i], V[1][i], V[2][i]))


def profile_normal(profile):
    """Profile normal: the least-squares plane of the CVs (periodic: the unique CVs), turned like the Newell
    normal of the CV polygon (equal for a planar profile); None for a straight profile."""
    P = _unique(_crv(profile))
    try:
        n = newell(P)
    except ValueError:
        return None
    fit = _smallest_axis(P)
    return fit if dot(fit, n) >= 0.0 else mul(fit, -1.0)


def _path_dirs(P):
    out = [unit(sub(P[1], P[0]))]
    for j in range(1, len(P) - 1):
        out.append(unit(add(unit(sub(P[j + 1], P[j])), unit(sub(P[j], P[j - 1])))))
    out.append(unit(sub(P[-1], P[-2])))
    return out


def extrude_tube(profile, path, pivot=(0.0, 0.0, 0.0), at_path=False, component_pivot=False):
    """Maya Extrude, style Tube. U = profile, V = path; every CV ring is a rigid copy of the
    profile CVs carried by the discrete parallel transport of the path CV directions. ``pivot`` = the profile
    transform's world rotate pivot (used At path only). A straight profile (no Newell normal) is not turned onto
    the path. Exact on cubic paths; along a degree-1 path Maya's interior ring directions are not the
    control-polygon bisectors used here (an approximation there). Rotation / Scale are not modelled."""
    pr, pa = _crv(profile), _crv(path)
    P = pa.cvs
    dirs = _path_dirs(P)
    n_prof = profile_normal(pr)
    if n_prof is not None and dot(n_prof, dirs[0]) < 0.0:
        n_prof = mul(n_prof, -1.0)      # like Maya: the profile faces along the path start, whatever its CV order
    R0 = rot_between(n_prof, dirs[0]) if n_prof is not None else [r[:] for r in _I3]
    frames, acc = [], [r[:] for r in _I3]
    for j in range(len(P)):
        if j:
            acc = _mm(rot_between(dirs[j - 1], dirs[j]), acc)
        frames.append(_mm(acc, R0))
    R0t = _tr(R0)
    pivot = tuple(pivot)
    P0 = P[0]       # the profile turns about the path's start point (Maya's closest end point pivot)
    rows = []
    for q in pr.cvs:
        row = []
        for j in range(len(P)):
            if not at_path:
                x = add(P0, _mv(R0t, add(sub(P[j], P0), _mv(frames[j], sub(q, P0)))))
            elif component_pivot:
                x = add(P[j], _mv(frames[j], sub(q, pivot)))
            else:
                x = sub(add(add(P[j], _mv(frames[j], sub(q, P0))), P0), pivot)
            row.append(x)
        rows.append(row)
    return Surf(rows, pr.knots, pa.knots, pr.degree, pa.degree, pr.periodic, pa.periodic)


def extrude_flat(profile, path):
    """Maya Extrude, style Flat: U = path, V = profile (swapped); the profile translated along the path CVs."""
    pr, pa = _crv(profile), _crv(path)
    rows = [[add(q, sub(p, pa.cvs[0])) for q in pr.cvs] for p in pa.cvs]
    return Surf(rows, pa.knots, pr.knots, pa.degree, pr.degree, pa.periodic, pr.periodic)


def extrude_distance(profile, direction=None, length=1.0):
    """Maya Extrude, style Distance: U = profile, V degree 1 (knots 0 1): q and q + unit(direction) * length.
    ``direction`` None = the profile normal (a straight profile then raises ValueError)."""
    pr = _crv(profile)
    if direction is None:
        direction = profile_normal(pr)
        if direction is None:
            raise ValueError("a straight profile has no normal: give a direction")
    off = mul(unit(direction), length)
    rows = [[q, add(q, off)] for q in pr.cvs]
    return Surf(rows, pr.knots, [0.0, 1.0], pr.degree, 1, pr.periodic, False)


# --- Birail 1 ----------------------------------------------------------------------------------------------

def birail1(profile, rail1, rail2, proportional=True):
    """Maya Birail 1: U = rails (knots normalised 0..1), V = profile (normalised). At each rail Greville
    parameter the profile is mapped by the transform taking (profile start, profile end) onto (rail1 point, rail2
    point): minimal rotation of the chord, scale uniform (proportional) or along the chord only; the CV rows then
    interpolate those mapped profiles. Exact for rails whose chords stay in one plane; twisted rails are an
    approximation. Rails with different knots are made compatible (loft rule) first; periodic rails map their CV
    pairs directly."""
    pr = _crv(profile)
    r1, r2 = _crv(rail1), _crv(rail2)
    knots_u, du, (c1, c2) = compatible([r1, r2])
    Q = pr.cvs
    a0 = Q[0]
    ch0 = sub(Q[-1], a0)
    L0 = norm(ch0)
    if L0 < 1e-12:
        raise ValueError("the profile's ends meet")
    e = mul(ch0, 1.0 / L0)

    def mapped(A, B):
        c = sub(B, A)
        R = rot_between(ch0, c) if norm(c) > 1e-12 else [r[:] for r in _I3]
        k = norm(c) / L0
        row = []
        for q in Q:
            v = sub(q, a0)
            v = mul(v, k) if proportional else add(v, mul(e, dot(v, e) * (k - 1.0)))
            row.append(add(A, _mv(R, v)))
        return row

    periodic_u = r1.periodic and r2.periodic and knots_u == list(r1.knots)
    if r1.periodic or r2.periodic:
        rows = [mapped(A, B) for A, B in zip(c1, c2)]
    else:
        n = len(c1)
        g = greville(knots_u, du, n)
        at = [mapped(cm.evaluate(c1, knots_u, du, t), cm.evaluate(c2, knots_u, du, t)) for t in g]
        M = [_basis_row(knots_u, du, n, t) for t in g]
        cols = [cm.solve(M, [at[j][i] for j in range(n)]) for i in range(len(Q))]
        rows = [[cols[i][j] for i in range(len(Q))] for j in range(n)]
    return Surf(rows, _normalise(knots_u), _normalise(pr.knots), du, pr.degree, periodic_u, pr.periodic)


# --- Boundary / Square ----------------------------------------------------------------------------------------

def order_boundary(curves):
    """Maya "Automatic" curve ordering: start with curves[0] as drawn, then chain the remaining curves
    head to tail by the nearest end point (reversing a curve whose end is the nearer one)."""
    rest = [_crv(c) for c in curves]
    chain = [rest.pop(0)]
    while rest:
        tail = chain[-1].cvs[-1]
        best = min(((min(_dist(tail, c.cvs[0]), _dist(tail, c.cvs[-1])), i) for i, c in enumerate(rest)))
        c = rest.pop(best[1])
        if _dist(tail, c.cvs[-1]) < _dist(tail, c.cvs[0]):
            c = _reverse_curve(c)
        chain.append(c)
    return chain


def coons(edge_v0, edge_v1, edge_u0, edge_u1, gu, gv):
    """Bilinearly blended Coons patch of four compatible CV nets: edge_v0[i] / edge_v1[i] = the v = 0 / 1 edges (over
    U), edge_u0[j] / edge_u1[j] = the u = 0 / 1 edges (over V); gu / gv = the normalised Greville parameters. Exact:
    the linear blends are reproduced by Greville weights (multi-span sides)."""
    c00, c10, c01, c11 = edge_v0[0], edge_v0[-1], edge_v1[0], edge_v1[-1]
    out = []
    for i, u in enumerate(gu):
        row = []
        for j, v in enumerate(gv):
            p = add(add(mul(edge_v0[i], 1 - v), mul(edge_v1[i], v)), add(mul(edge_u0[j], 1 - u), mul(edge_u1[j], u)))
            b = add(add(mul(c00, (1 - u) * (1 - v)), mul(c10, u * (1 - v))),
                    add(mul(c01, (1 - u) * v), mul(c11, u * v)))
            row.append(sub(p, b))
        out.append(row)
    return out


def _domain(c):
    return c.knots[-1] - c.knots[0]


def boundary(curves, square=False):
    """Maya Boundary / Square (default, no neighbouring surfaces): 3 or 4 curves head to tail in the order given
    (c1..c4). 4 curves: v = 0 edge = c1, u = 1 edge = c2, v = 1 edge = c3 reversed, u = 0 edge = c4 reversed.
    3 curves: v = 0 edge = c1, v = 1 edge = c2 reversed, u = 0 edge = c3 reversed, u = 1 edge collapsed to the
    c1-end corner. Opposite sides are made compatible (loft rule), CVs = Coons blend. Knot range of a direction =
    the mean of its two sides' domains (0..1 and 0..2 -> 0..1.5); ``square`` (Maya Square) keeps U at 0..1."""
    cs = [_crv(c) for c in curves]
    if any(c.periodic for c in cs):
        raise ValueError("boundary curves must be open")
    if len(cs) == 4:
        sv0, sv1 = cs[0], _reverse_curve(cs[2])
        su0, su1 = _reverse_curve(cs[3]), cs[1]
    elif len(cs) == 3:
        sv0, sv1, su0 = cs[0], _reverse_curve(cs[1]), _reverse_curve(cs[2])
        su1 = None
    else:
        raise ValueError("boundary needs 3 or 4 curves")
    ku, du, (ev0, ev1) = compatible([sv0, sv1])
    ku = _normalise(ku)
    span_u = 1.0 if square else (_domain(sv0) + _domain(sv1)) / 2.0
    if su1 is None:
        kv, dv = _normalise(su0.knots), su0.degree
        span_v = _domain(su0)
        eu0 = list(su0.cvs)
        eu1 = [ev0[-1]] * len(eu0)
    else:
        kv, dv, (eu0, eu1) = compatible([su0, su1])
        kv = _normalise(kv)
        span_v = (_domain(su0) + _domain(su1)) / 2.0
    gu = greville(ku, du, len(ev0))          # Coons blend on the 0..1 parameters
    gv = greville(kv, dv, len(eu0))
    return Surf(coons(ev0, ev1, eu0, eu1, gu, gv), [k * span_u for k in ku], [k * span_v for k in kv], du, dv)
