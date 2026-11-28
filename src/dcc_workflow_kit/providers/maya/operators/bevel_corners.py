# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit Mesh > Bevel: where the new vertices go at corners, worked out before the bevel runs. Box corners with two
bevelled edges (``corner_pairs``; ``corner_offsets`` for an absolute Offset), three bevelled edges (``corner_triples``,
``corner_splits``; ``CORNER_SPLIT`` / ``TRIPLE_SPLIT`` pick the rule) and gaps of unbevelled edges between two bevelled
ones (``gap_merges``). Used by the bevel driver in ``bevel_maya``.
"""

import math

from .bevel_numbering import vertex_edges
from .bevel_width import NEAR_LINE, ZERO, _half_sin, _newell, _slides


CORNER_SPLIT = 10.93  # degrees: two-edge corners whose dihedral angles differ less than this use ``corner_pairs``
TRIPLE_SPLIT = 1.0 / 1.1  # three-edge corners whose smallest / largest sin(dihedral / 2) is at least this use
                          # ``corner_triples``


def corner_pairs(edges, ids):
    """Corners like a box corner: vertex v has three edges, two of them bevelled (sharing face F) and one not (u3),
    and the dihedral angles of the two bevelled edges differ by less than ``CORNER_SPLIT``. P = the first bevelled
    edge in Maya's vertex -> edge order at v, Q the other; h = sin(dihedral / 2), s = sin(angle to u3);
    k_P = min(1, sqrt(s_P / s_Q)), k_Q = min(1, sqrt(s_Q / s_P)), hm = the smallest of h_P k_P, h_Q at Q's far end
    and the value that puts the new vertex on u3 exactly W below F. Like Maya:
    - each edge's width at its far end = W hm / h (``edge_half_sin`` gives hm);
    - the new corner in F lies on the bisector, W hm / (h_P k_P) from both edge lines;
    - the new vertex on u3 = the mean of where the two side faces' offset lines (W hm k / h from the edge) cross u3.
    Returns {v: {...}}; ids = {BMEdge: Maya edge id}."""
    sel = set(edges)
    out = {}
    if ids is None:
        return out
    for v in {v for e in edges for v in e.verts}:
        if len(v.link_edges) != 3 or any(len(e.link_faces) != 2 for e in v.link_edges):
            continue
        mine = [e for e in v.link_edges if e in sel]
        if len(mine) != 2:
            continue
        faces = set(mine[0].link_faces).intersection(mine[1].link_faces)
        order = vertex_edges(v, ids)
        if len(faces) != 1 or order is None:
            continue
        p, q = [e for e in order if e in sel]
        rest = [e for e in v.link_edges if e not in sel][0]
        units = [e.other_vert(v).co - v.co for e in (p, q, rest)]
        if any(u.length <= ZERO for u in units):
            continue
        up, uq, u3 = [u.normalized() for u in units]
        hp, hq = _half_sin(p, v), _half_sin(q, v)
        sp, sq = up.cross(u3).length, uq.cross(u3).length
        if hp is None or hq is None or sp <= ZERO or sq <= ZERO:
            continue
        if abs(math.degrees(2.0 * (math.asin(min(1.0, hp)) - math.asin(min(1.0, hq))))) >= CORNER_SPLIT:
            continue
        kp, kq = min(1.0, math.sqrt(sp / sq)), min(1.0, math.sqrt(sq / sp))
        half = math.acos(max(-1.0, min(1.0, up.dot(uq)))) / 2.0
        ray = up + uq
        normal = up.cross(uq)
        if ray.length <= ZERO or math.sin(half) <= ZERO or normal.length <= ZERO:
            continue
        # Q's angle at its far end (differs from v's when Q's side face is bent), and the new vertex on u3 never
        # goes deeper than W below F
        hq_far = _half_sin(q, q.other_vert(v)) or hq
        depth = (kp / (hp * sp) + kq / (hq * sq)) / 2.0 * abs(u3.dot(normal.normalized()))
        hm = min(hp * kp, hq_far, 1.0 / depth if depth > ZERO else hq_far)
        out[v] = {"P": p, "Q": q, "rest": rest, "hm": hm, "origin": v.co.copy(), "ray": ray.normalized(),
                  "k_ray": hm / (hp * kp) / math.sin(half), "u3": u3,
                  "k_u3": (hm / hp * kp / sp + hm / hq * kq / sq) / 2.0}
    return out


def corner_triples(edges, ids):
    """Corners where three bevelled edges meet (a box corner bevelled on all three edges) and their sin(dihedral / 2)
    values h stay close (smallest / largest at least ``TRIPLE_SPLIT``). Like Maya, each face's new corner lies on its
    bisector, W hm / h_first from both edge lines: hm = the smallest h, h_first = h of the face's edge that comes
    first in Maya's vertex -> edge order at v. Returns {v: {"origin", "faces": {face: (unit bisector, k_ray, k)}}}
    (k = hm / h_first: how far that corner sits, in widths; k_ray = k / sin(half the corner angle))."""
    sel = set(edges)
    out = {}
    if ids is None:
        return out
    for v in {v for e in edges for v in e.verts}:
        if len(v.link_edges) != 3 or any(e not in sel or len(e.link_faces) != 2 for e in v.link_edges):
            continue
        order = vertex_edges(v, ids)
        if order is None:
            continue
        hs = {e: _half_sin(e, v) for e in order}
        if any(h is None for h in hs.values()):
            continue
        hm = min(hs.values())
        if hm / max(hs.values()) < TRIPLE_SPLIT:
            continue
        faces = {}
        for i, a in enumerate(order):
            for b in order[i + 1:]:
                shared = set(a.link_faces).intersection(b.link_faces)
                if len(shared) != 1:
                    continue
                ua, ub = (a.other_vert(v).co - v.co), (b.other_vert(v).co - v.co)
                if ua.length <= ZERO or ub.length <= ZERO:
                    continue
                ua.normalize()
                ub.normalize()
                half = math.acos(max(-1.0, min(1.0, ua.dot(ub)))) / 2.0
                ray = ua + ub
                if ray.length <= ZERO or math.sin(half) <= ZERO:
                    continue
                k = hm / hs[a]
                faces[shared.pop()] = (ray.normalized(), k / math.sin(half), k)
        if len(faces) == 3:
            out[v] = {"origin": v.co.copy(), "faces": faces}
    return out


SPLIT_D = 0.90        # the face of a split corner whose edges' h are this close sits on its bisector
SPLIT_WEIGHTS_C = (0.41205, 0.41471, 0.1779)    # approximate split-corner sizes (see ``corner_splits``)
SPLIT_WEIGHTS_D = (0.40481, 0.18657, 0.42296)
SPLIT_SKIP = 0.86                              # see ``corner_splits``


def _split_rho(q):
    return 2.0 * q / math.sqrt(1.0 + 3.0 * q * q)


def corner_splits(edges, ids):
    """Three-edge corners that ``corner_triples`` leaves out (their
    h values differ more than ``TRIPLE_SPLIT``). Each face's new corner is placed from its two edges (f comes first in
    Maya's vertex -> edge order, s second, t is the third edge at v): size r = w0 + w1 g(h_f / h_t) + w2 g(h_s / h_t),
    g(q) = 2q / sqrt(1 + 3q^2), in units of the far-end width W hm (hm = the smallest h).
    - the face whose two h are closest (ratio at least ``SPLIT_D``) sits on its bisector, r / mean(h_f, h_s) from both
      edge lines (``SPLIT_WEIGHTS_D``);
    - every other face sits on the line from v through the point W hm / h_f, W hm / h_s from the two edge lines, r times
      that point (``SPLIT_WEIGHTS_C``).
    Returns {v: {"origin", "hm", "faces": {face: (offset per unit W, {edge: foot per unit W}, angle,
    unit bisector)}}}."""
    sel = set(edges)
    out = {}
    if ids is None:
        return out
    for v in {v for e in edges for v in e.verts}:
        if len(v.link_edges) != 3 or any(e not in sel or len(e.link_faces) != 2 for e in v.link_edges):
            continue
        order = vertex_edges(v, ids)
        if order is None:
            continue
        hs = {e: _half_sin(e, v) for e in order}
        if any(h is None for h in hs.values()):
            continue
        hm = min(hs.values())
        if hm / max(hs.values()) >= TRIPLE_SPLIT:
            continue
        units = {e: e.other_vert(v).co - v.co for e in order}
        if any(u.length <= ZERO for u in units.values()):
            continue
        units = {e: u.normalized() for e, u in units.items()}
        pairs = []
        for i, f in enumerate(order):
            for s in order[i + 1:]:
                shared = set(f.link_faces).intersection(s.link_faces)
                if len(shared) == 1:
                    pairs.append((shared.pop(), f, s))
        if len(pairs) != 3:
            continue
        ratio = {face: min(hs[f], hs[s]) / max(hs[f], hs[s]) for face, f, s in pairs}
        d_face = max(ratio, key=ratio.get)
        if ratio[d_face] >= SPLIT_D and hm / max(hs.values()) >= SPLIT_SKIP:
            # nearly unsplit corners whose bisector face is acute and holds the two smaller h keep Blender's corner
            _face, f, s = [x for x in pairs if x[0] is d_face][0]
            t = [e for e in order if e not in (f, s)][0]
            if hs[t] > max(hs[f], hs[s]) and units[f].dot(units[s]) > ZERO:
                continue
        faces = {}
        for face, f, s in pairs:
            t = [e for e in order if e not in (f, s)][0]
            uf, us = units[f], units[s]
            angle = math.acos(max(-1.0, min(1.0, uf.dot(us))))
            sn = math.sin(angle)
            if sn <= ZERO:
                break
            weights = SPLIT_WEIGHTS_D if face is d_face and ratio[face] >= SPLIT_D else SPLIT_WEIGHTS_C
            r = weights[0] + weights[1] * _split_rho(hs[f] / hs[t]) + weights[2] * _split_rho(hs[s] / hs[t])
            if weights is SPLIT_WEIGHTS_D:
                offset = (uf + us).normalized() * (r / ((hs[f] + hs[s]) / 2.0) / math.sin(angle / 2.0))
            else:
                offset = (uf / (hs[s] * sn) + us / (hs[f] * sn)) * r
            offset *= hm
            faces[face] = (offset, {f: offset.dot(uf), s: offset.dot(us)}, angle, (uf + us).normalized())
        if len(faces) == 3:
            out[v] = {"origin": v.co.copy(), "hm": hm, "faces": faces}
    return out


def _flat(f):
    """Every vertex of face ``f`` lies in its plane."""
    n, c = f.normal, f.calc_center_median()
    size = max((v.co - c).length for v in f.verts)
    return all(abs((v.co - c).dot(n)) <= 1e-6 * max(1.0, size) for v in f.verts)


def corner_offsets(edges, ids):
    """Absolute Offset (Offset As Fraction off): the same box corners as ``corner_pairs`` (any dihedral angles) with
    a flat F, not almost straight. P, Q, s as there; a side face may be bent: each edge's width at an end is
    W n_e / h there, n_e = sin(dihedral / 2) between the face normals of F and e's side face (1 for flat faces).
    Like Maya:
    - the new corner in F lies on the bisector, W c n_P / h_P from both edge lines,
      c = max(1, sqrt(2 / (1 + (s_P / s_Q)^2)));
    - the new vertex on u3 lies 4 W / (3 max(s_P, s_Q) + min(s_P, s_Q)) from v, times the mean of n / h of P and Q.
    Returns {v: {...}} with the keys ``bevel_edges`` moves by."""
    sel = set(edges)
    out = {}
    if ids is None:
        return out
    for v in {v for e in edges for v in e.verts}:
        if len(v.link_edges) != 3 or any(len(e.link_faces) != 2 for e in v.link_edges):
            continue
        mine = [e for e in v.link_edges if e in sel]
        if len(mine) != 2:
            continue
        faces = set(mine[0].link_faces).intersection(mine[1].link_faces)
        order = vertex_edges(v, ids)
        if len(faces) != 1 or order is None or not _flat(next(iter(faces))):
            continue
        p, q = [e for e in order if e in sel]
        top = next(iter(faces))
        scales = [_face_half_sin(e, top) for e in (p, q)]
        heres = [_half_sin(e, v) for e in (p, q)]
        if None in scales or None in heres:
            continue
        rest = [e for e in v.link_edges if e not in sel][0]
        units = [e.other_vert(v).co - v.co for e in (p, q, rest)]
        if any(u.length <= ZERO for u in units):
            continue
        up, uq, u3 = [u.normalized() for u in units]
        sp, sq = up.cross(u3).length, uq.cross(u3).length
        half = math.acos(max(-1.0, min(1.0, up.dot(uq)))) / 2.0
        ray = up + uq
        if sp <= ZERO or sq <= ZERO or ray.length <= ZERO or math.sin(half) <= ZERO or up.dot(uq) < -NEAR_LINE:
            continue       # an almost straight corner is ``corner_moves``' (an n-gon cap rim)
        c = max(1.0, math.sqrt(2.0 / (1.0 + (sp / sq) ** 2)))
        wp, wq = scales[0] / heres[0], scales[1] / heres[1]
        out[v] = {"origin": v.co.copy(), "ray": ray.normalized(), "k_ray": c * wp / math.sin(half), "u3": u3,
                  "k_u3": 4.0 / (3.0 * max(sp, sq) + min(sp, sq)) * (wp + wq) / 2.0,
                  "ends": _far_ends((p, q), v, sel, scales)}
    return out


def _face_half_sin(e, top):
    """sin(dihedral / 2) of edge ``e`` from the normals of face ``top`` and e's other face."""
    other = [f for f in e.link_faces if f is not top]
    if len(other) != 1:
        return None
    a, b = _newell(top), _newell(other[0])
    if a is None or b is None:
        return None
    return math.cos(math.acos(max(-1.0, min(1.0, a.dot(b)))) / 2.0)


def _far_ends(pair, v, sel, scales=None):
    """At the other end of each edge of a corner (when it ends only that bevelled edge) Maya keeps both new vertices
    one width from the edge (times n / h there for a bent side face, ``scales`` = n per edge); Blender's drift with
    the corner. [(position, unit slide edge, k = 1 / sin)]."""
    out = []
    for i, e in enumerate(pair):
        w = e.other_vert(v)
        here = _half_sin(e, w) if scales else None
        f = scales[i] / here if here else 1.0
        if sum(1 for x in w.link_edges if x in sel) != 1:
            continue
        d = (v.co - w.co)
        if d.length <= ZERO:
            continue
        d.normalize()
        for s in _slides(e, w):
            u = s.other_vert(w).co - w.co
            if u.length <= ZERO:
                continue
            u.normalize()
            if u.cross(d).length > ZERO:
                out.append((w.co.copy(), u, f / u.cross(d).length))
    return out


def _fan(v):
    """[(edge, face after it)] around ``v`` in order, or None when an edge there doesn't have exactly two faces."""
    if not v.link_edges or any(len(e.link_faces) != 2 for e in v.link_edges):
        return None
    e = v.link_edges[0]
    f = e.link_faces[0]
    out = []
    for _ in range(len(v.link_edges)):
        out.append((e, f))
        nxt = next((x for x in v.link_edges if x is not e and f in x.link_faces), None)
        if nxt is None:
            return None
        e = nxt
        f = e.link_faces[0] if e.link_faces[1] is f else e.link_faces[1]
    return out if out[0][0] is e and len({x for x, _ in out}) == len(out) else None


def gap_merges(edges, w):
    """Vertices where two bevelled edges in a row around the vertex have two or more unbevelled edges between them:
    like Maya (Auto miter), all the faces of that gap meet at one new vertex. It lies on the bisector of the gap's
    faces laid flat around the vertex (their angles there added up to ``theta``), at W from both bevelled edges in
    that flat layout: W / sin(theta / 2) from the vertex, in the gap face that holds the bisector.
    Returns [(target position, [the gap's faces])]."""
    sel = set(edges)
    out = []
    for v in {x for e in edges for x in e.verts}:
        if sum(1 for e in v.link_edges if e in sel) < 2:
            continue
        fan = _fan(v)
        if fan is None:
            continue
        n = len(fan)
        bev = [i for i, (e, _f) in enumerate(fan) if e in sel]
        for a, b in zip(bev, bev[1:] + bev[:1]):
            gap = [(a + k) % n for k in range(((b - a) % n) or n)]       # fan slots from edge a to edge b
            if len(gap) < 3:                                              # fewer than two unbevelled edges between
                continue
            dirs, angles = [], []
            for i in gap + [b]:
                d = fan[i][0].other_vert(v).co - v.co
                if d.length <= ZERO:
                    break
                dirs.append(d.normalized())
            else:
                angles = [math.acos(max(-1.0, min(1.0, p.dot(q)))) for p, q in zip(dirs, dirs[1:])]
            theta = sum(angles)
            if not angles or not 1e-4 < theta < 2.0 * math.pi - 1e-4 or math.sin(theta / 2.0) <= 1e-4:
                continue
            rest = theta / 2.0
            for p, q, ang in zip(dirs, dirs[1:], angles):
                if rest <= ang + 1e-12:
                    perp = q - p * p.dot(q)
                    if perp.length <= ZERO:
                        break
                    ray = p * math.cos(rest) + perp.normalized() * math.sin(rest)
                    out.append((v.co + ray * (w / math.sin(theta / 2.0)), [fan[i][1] for i in gap]))
                    break
                rest -= ang
    return out
