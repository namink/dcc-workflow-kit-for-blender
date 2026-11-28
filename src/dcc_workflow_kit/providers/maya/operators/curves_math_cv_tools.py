# SPDX-License-Identifier: GPL-3.0-or-later
"""CV shape rules of the Curves menu (bpy-free): Bend, Curl and Scale Curvature (each CV leg written in a frame
carried along the curve, edited, then turned back into CVs), CV Hardness, Fit B-spline, Align (position + tangent)
and the kit's Lock Length rule. Entry points ``bend_cvs``, ``curl_cvs``, ``scale_curvature_cvs``, ``harden``,
``fit_bspline``, ``align_ends``, ``keep_leg_lengths``; the operators are in curves_207.py, curves_math.py
re-exports every name.
"""

import math

from .curves_math_eval import add, clamped_uniform, cross, dot, interpolate, mul, norm, sub, unit


# --- Curves > Bend / Curl / Scale Curvature ------------------------------------------------------
# Maya's Curves > Bend / Curl / Scale Curvature commands: the CVs become "deflections" — each CV leg
# expressed in a frame carried along the curve (start frame from the first leg with the twist axis taken from Maya's
# Y-up world, each next frame = the previous one turned onto the next leg by half the angle twice). The
# commands edit deflections (or the points) and rebuild the CVs from them. Points are in Maya's Y-up object space.

def _new_frame(new_dir, frame):
    out0 = new_dir
    c = cross(frame[0], new_dir)
    ln = norm(c)
    if ln > 0.0000001:
        c = mul(c, 1.0 / ln)
        if ln > 1.0:
            ln = 1.0
        a = math.asin(ln) / 2.0
        co, si = math.cos(a), math.sin(a)
        w = cross(c, frame[2])
        out2 = add(add(add(mul(frame[2], co * co), mul(w, 2 * si * co)),
                       mul(c, si * si * dot(frame[2], c))), mul(cross(c, w), si * si))
        out1 = cross(new_dir, out2)
    else:
        out2 = mul(frame[2], -1.0) if dot(frame[0], new_dir) < 0 else frame[2]
        out1 = cross(frame[0], out2)
    return [out0, out1, out2]


def _start_frame(along):
    along = mul(along, 1.0 / norm(along))
    ang = math.atan2(along[0], along[2])
    twist = (-math.cos(ang), 0.0, math.sin(ang))
    cr = cross(twist, along)
    cr = mul(cr, 1.0 / norm(cr))
    return [along, cr, twist]


def deflections(points):
    """Curve -> deflections: [first leg] + every leg i >= 1 in the frame carried from leg i - 1."""
    pts = [tuple(p) for p in points]
    if len(pts) < 3:
        return None
    along = sub(pts[1], pts[0])
    frame = _start_frame(along)
    out = [along]
    last = pts[0]
    for p in pts[1:]:
        dif = sub(p, last)
        out.append((dot(dif, frame[0]), dot(dif, frame[1]), dot(dif, frame[2])))
        ln = norm(dif)
        if ln > 0.0000001:
            frame = _new_frame(mul(dif, 1.0 / ln), frame)
        last = p
    return out


def from_deflections(defl, points):
    """Deflections -> curve: CV 0 stays, every next CV = previous + its deflection in the carried frame."""
    pts = [tuple(p) for p in points]
    frame = _start_frame(defl[0])
    last = pts[0]
    for i in range(1, len(pts)):
        d = defl[i]
        world = add(add(mul(frame[0], d[0]), mul(frame[1], d[1])), mul(frame[2], d[2]))
        pts[i] = add(last, world)
        last = pts[i]
        ln = norm(world)
        if ln > 0.0000001:
            frame = _new_frame(mul(world, 1.0 / ln), frame)
    return pts


def bend_cvs(points, amount=0.2, twist=0.0, count=None):
    """Maya Bend (default amount 0.2, twist 0): deflections of the first ``count`` CVs get amount x (twist, 1 - twist)
    added sideways (ramped in over the first 5 CVs), leg lengths kept."""
    pts = [tuple(p) for p in points]
    n = len(pts) if count is None else count
    defl = deflections(pts)
    if defl is None:
        return pts
    yb, zb = amount * twist, amount * (1.0 - twist)
    for i in range(1, n):
        d = defl[i]
        ln = norm(d)
        y, z = yb, zb
        if i < 5.0:
            y *= i / 5.0
            z *= i / 5.0
        nd = (d[0], d[1] + y, d[2] + z)
        nl = norm(nd)
        if nl > 0.000001:
            defl[i] = mul(nd, ln / nl)
    return from_deflections(defl, pts)


def scale_curvature_cvs(points, factor=1.1, max_curvature=0.8, count=None):
    """Maya Scale Curvature (default 1.1, max 0.8): each leg's bend angle (1 - cos-ish of its deflection) scales by
    ``factor`` up to 2 x max, the sideways part scales by the ratio of sines, leg lengths kept."""
    pts = [tuple(p) for p in points]
    n = len(pts) if count is None else count
    if factor == 1.0:
        return pts
    max_curvature *= 2
    defl = deflections(pts)
    if defl is None:
        return pts
    for i in range(1, n):
        d = defl[i]
        ln = norm(d)
        ang = 1.0 - d[0] / ln
        s = math.sin(ang * 0.5 * 3.141592653589793)
        ang *= factor
        if ang > max_curvature:
            ang = max_curvature
        s2 = math.sin(ang * 0.5 * 3.141592653589793)
        ratio = s2 / s if s > 0.000001 else 1.0
        nd = ((1.0 - ang) * ln, d[1] * ratio, d[2] * ratio)
        nl = norm(nd)
        if nl > 0.000001:
            defl[i] = mul(nd, ln / nl)
    return from_deflections(defl, pts)


def _smooth_pass(pts, count):
    if count < 3 or len(pts) < count:
        return
    prev, cur = pts[0], pts[1]
    for i in range(1, count - 1):
        nxt = pts[i + 1]
        pts[i] = add(mul(cur, 0.4), mul(add(nxt, prev), 0.3))
        prev, cur = cur, nxt


def curl_cvs(points, amount=0.3, frequency=1.0, count=None):
    """Maya Curl (default amount 0.3, frequency 1): the CVs of a 4-pass smoothed copy carry the frame; each CV i
    moves by amount x (sin(f i) side + cos(f i) twist axis), ramped in while f i < 2."""
    pts = [tuple(p) for p in points]
    n = len(pts) if count is None else count
    if amount == 0.0 or n < 3 or len(pts) < n:
        return pts
    sm = list(pts)
    for _ in range(4):
        _smooth_pass(sm, len(sm))
    frame = _start_frame(sub(sm[1], sm[0]))
    last = sm[0]
    out = list(pts)
    for i in range(1, n):
        dif = sub(sm[i], last)
        ln = norm(dif)
        param = frequency * float(i)
        curl = amount * (param * 0.5 if param < 2.0 else 1.0)
        off = mul(add(mul(frame[1], math.sin(param)), mul(frame[2], math.cos(param))), curl)
        out[i] = add(pts[i], off)
        if ln > 0.0000001:
            frame = _new_frame(mul(dif, 1.0 / ln), frame)
        last = sm[i]
    # CVs after the range keep their place (Maya leaves them where they are)
    return out


# --- CV Hardness (hardenPointCurve) ----------------------------------------------------------

def harden(knots, degree, cv):
    """Full multiplicity at CV ``cv``: Maya knots cv .. cv + degree - 1 all become knot cv + degree - 1, but only when
    none of them is an end knot (otherwise nothing changes); CVs unchanged."""
    k = list(knots)
    lo, hi = cv, cv + degree - 1
    if lo < 0 or hi >= len(k):
        return k
    if any(abs(k[j] - k[0]) < 1e-12 or abs(k[j] - k[-1]) < 1e-12 for j in range(lo, hi + 1)):
        return k
    for j in range(lo, hi + 1):
        k[j] = k[hi]
    return k


# --- Fit B-spline (fitBspline on a degree-1 curve) ------------------------------------------

def fit_bspline(points):
    """The cubic through the polyline's CVs: chord-length parameters, natural ends, knots scaled to 0 .. n - 1 (the
    polyline's own domain)."""
    pts = [tuple(p) for p in points]
    if len(pts) < 3:
        return pts, clamped_uniform(len(pts), 1), 1
    t = [0.0]
    for a, b in zip(pts, pts[1:]):
        t.append(t[-1] + norm(sub(b, a)))
    span_ = float(len(pts) - 1)
    params = [x / t[-1] * span_ for x in t]
    knots = [params[0]] * 3 + params[1:-1] + [params[-1]] * 3
    return interpolate(pts, params, knots, 3), knots, 3


# --- Align (alignCurve, default position + tangent continuity) ------------------------------------

def align_ends(a, b):
    """Maya Align with the first selected curve ``a`` moving: the closest pair of ends (a start / end, b start / end)
    is joined by translating all of ``a``; a's end leg then points away from b's end leg (tangent continuity), keeping
    its length. ``b`` doesn't change. Returns a's new CVs."""
    a = [tuple(p) for p in a]
    b = [tuple(p) for p in b]
    ends = [(i, j) for i in (0, -1) for j in (0, -1)]
    ia, ib = min(ends, key=lambda e: (norm(sub(a[e[0]], b[e[1]])), ends.index(e)))
    t = sub(b[ib], a[ia])
    a = [add(p, t) for p in a]
    nxt_a = 1 if ia == 0 else -2
    nxt_b = 1 if ib == 0 else -2
    inward_b = unit(sub(b[nxt_b], b[ib]))
    leg = norm(sub(a[nxt_a], a[ia]))
    a[nxt_a] = sub(a[ia], mul(inward_b, leg))
    return a


# --- Lock Length (kit rule) ----------------------------------------------------------

def keep_leg_lengths(old, new):
    """After CVs of a length-locked curve moved (``old`` -> ``new``), the moved CVs stay and every other CV follows
    its neighbour towards the moved ones so each CV leg keeps its old length (Maya's locked curve keeps its length
    under the CV manipulator; this solver is the kit's own)."""
    old = [tuple(p) for p in old]
    new = [tuple(p) for p in new]
    if len(old) != len(new) or len(old) < 2:
        return new
    moved = [i for i, (p, q) in enumerate(zip(old, new)) if norm(sub(p, q)) > 1e-9]
    if not moved:
        return new
    out = list(new)
    legs = [norm(sub(old[i + 1], old[i])) for i in range(len(old) - 1)]
    lo, hi = moved[0], moved[-1]
    for i in range(hi + 1, len(out)):
        d = sub(out[i], out[i - 1])
        out[i] = add(out[i - 1], mul(unit(d) if norm(d) > 1e-12 else unit(sub(old[i], old[i - 1])), legs[i - 1]))
    for i in range(lo - 1, -1, -1):
        d = sub(out[i], out[i + 1])
        out[i] = add(out[i + 1], mul(unit(d) if norm(d) > 1e-12 else unit(sub(old[i], old[i + 1])), legs[i]))
    return out
