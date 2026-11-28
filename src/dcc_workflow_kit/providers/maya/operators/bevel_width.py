# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit Mesh > Bevel: the width and where chain-end vertices go, worked out before ``bmesh.ops.bevel`` runs. Fraction is
a share of the shortest slide edge (``slide_limit``) times 0.9999 (``width``); chain ends (``terminal_moves``,
``end_moves``), long slides with an absolute Offset (``past_ends``) and straight face corners (``corner_moves``). Also
the shared tolerances ``ZERO`` / ``NEAR_LINE`` and the dihedral helpers ``_half_sin`` / ``_slides``. Used by the bevel
driver in ``bevel_maya`` and the other ``bevel_*`` modules.
"""

import math


ZERO = 1e-6           # zero-length slide edges (a zero-length extrusion) don't limit the fraction
FIT = 0.9999          # bevel width = 0.9999 x the asked width (offset 0.1 -> 0.09999, fraction 0.5 -> 0.49995)
NEAR_LINE = 0.9       # |cos| of a slide edge's angle to the bevelled edge above this: it runs near that line


def _slides(e, v):
    """The edges at ``v`` that lie in one of e's faces."""
    return [s for f in e.link_faces for s in v.link_edges if s is not e and f in s.link_faces]


def _half_sin(e, v):
    """sin(alpha / 2) of edge ``e`` at its vertex ``v``: alpha = the angle between its two slide edges at v seen along
    e (the dihedral angle of e's faces there). None when that is not defined."""
    d = e.other_vert(v).co - v.co
    if d.length <= ZERO or len(e.link_faces) != 2:
        return None
    d.normalize()
    slides = _slides(e, v)
    if len(slides) < 2:
        return None
    across = []
    for s in slides[:2]:
        x = s.other_vert(v).co - v.co
        x = x - d * x.dot(d)
        if x.length <= ZERO:
            return None
        across.append(x.normalized())
    half = math.acos(max(-1.0, min(1.0, across[0].dot(across[1])))) / 2.0
    return math.sin(half) if math.sin(half) > ZERO else None


def edge_half_sin(e, sel, corners=None):
    """One sin(alpha / 2) for a whole bevelled edge, like Maya: taken at its end where two or more bevelled edges
    meet (the smallest of theirs there; at a ``corner_pairs`` corner its ``hm``), else at its first vertex (the
    lower index)."""
    ends = sorted(e.verts, key=lambda x: (sum(1 for y in x.link_edges if y in sel) < 2, x.index))
    v = ends[0]
    if corners and v in corners and e in (corners[v]["P"], corners[v]["Q"]):
        return corners[v]["hm"]
    mine = [x for x in v.link_edges if x in sel]
    vals = [h for h in (_half_sin(x, v) for x in (mine if len(mine) >= 2 else [e])) if h is not None]
    return min(vals) if vals else None


def end_scale(e, v, sel, corners=None):
    """At a chain end ``v`` of bevelled edge ``e``: the edge's sin(alpha / 2) over v's own (1 where both agree: planar
    faces, no corner at the first vertex). Every new vertex at v moves out from v by this factor."""
    here, edge = _half_sin(e, v), edge_half_sin(e, sel, corners)
    if here is None or edge is None:
        return 1.0
    return edge / here


def terminal_moves(edges, corners=None):
    """#182: the ends of an open chain (or a lone edge) between two faces. At a vertex v that ends exactly
    one bevelled edge e, every other edge t at v that lies in no face of e gets its new vertex at
    d = W x sin(alpha / 2) / s_phi from v (alpha = the angle between e's two slide edges seen along e = the dihedral
    angle of e's faces, phi = the angle between t and e, s_phi = sin phi below 90 degrees, else 1): Maya keeps that
    point at W x sin(alpha / 2) from the bevelled edge. alpha is the edge's one angle (``edge_half_sin``); where it
    differs from v's own, the new vertices on the slide edges move out by the same factor (``end_scale``) — unless
    ``end_moves`` places them. Returns ([(v position, unit(t), k = d / W)], {t: [lengths / k]}, {vertices whose slide
    vertices moved}) — the second is what limits the width (``slide_limit``)."""
    sel = set(edges)
    moves, limits, scaled = [], {}, {}
    near = end_moves(edges, corners)[2]
    for v in {v for e in edges for v in e.verts}:
        mine = [e for e in v.link_edges if e in sel]
        if len(mine) != 1 or len(mine[0].link_faces) != 2:
            continue
        e = mine[0]
        d = (e.other_vert(v).co - v.co)
        if d.length <= ZERO:
            continue
        d.normalize()
        slides = _slides(e, v)
        here = _half_sin(e, v)
        if here is None:
            continue
        sin_half = edge_half_sin(e, sel, corners) or here
        scale = sin_half / here
        # an edge of a ``corner_pairs`` corner: Blender's offset at its far end drifts with the corner, Maya's doesn't
        paired = bool(corners) and any(e in (c["P"], c["Q"]) for c in corners.values())
        if (abs(scale - 1.0) > 1e-9 or paired) and v not in near:
            scaled[v] = scale
            for s in slides:
                off = s.other_vert(v).co - v.co
                u = off.normalized()
                sin_s = u.cross(d).length
                if sin_s > ZERO:
                    moves.append((v.co.copy(), u, scale / sin_s))
        for t in v.link_edges:
            if t is e or t in slides:
                continue
            off = t.other_vert(v).co - v.co
            if off.length <= ZERO:
                continue
            u = off.normalized()
            c = u.dot(d)
            s_phi = math.sqrt(max(0.0, 1.0 - c * c)) if c > 0.0 else 1.0
            if s_phi <= ZERO:
                continue
            k = sin_half / s_phi
            moves.append((v.co.copy(), u, k))
            limits.setdefault(t, []).append(off.length / k)
    return moves, limits, scaled


def _newell(f):
    """The face's normal from all its vertices (a bent face's average plane)."""
    n = f.verts[0].co * 0.0
    loops = [x.vert.co for x in f.loops]
    for a, b in zip(loops, loops[1:] + loops[:1]):
        n += a.cross(b)
    return n.normalized() if n.length > ZERO else None


def offset_end_moves(edges):
    """Absolute Offset, a lone bevelled edge between two faces: like Maya the new edge across each end is as long as
    on a flat bevel whose faces meet at the angle between the two faces' normals, so where an end's own angle differs
    (a twisted side face) its new vertices move out or in by sin(that angle / 2) over the end's sin(alpha / 2).
    Returns [(v position, unit(slide edge), k = distance along it / W, the slide edge's other vertex)]."""
    sel = set(edges)
    moves = []
    near = end_moves(edges)[2]
    for e in edges:
        if len(e.link_faces) != 2 or any(sum(1 for x in v.link_edges if x in sel) != 1 for v in e.verts):
            continue
        n0, n1 = _newell(e.link_faces[0]), _newell(e.link_faces[1])
        if n0 is None or n1 is None:
            continue
        flat = math.cos(n0.angle(n1) / 2.0)
        for v in e.verts:
            here = _half_sin(e, v)
            if here is None or v in near or abs(flat / here - 1.0) <= 1e-9:
                continue
            d = (e.other_vert(v).co - v.co).normalized()
            for s in _slides(e, v):
                u = (s.other_vert(v).co - v.co).normalized()
                sin_s = u.cross(d).length
                if sin_s > ZERO:
                    moves.append((v.co.copy(), u, flat / here / sin_s, s.other_vert(v)))
    return moves


def end_moves(edges, corners=None):
    """Ends of an open chain (or a lone edge) between two faces where a slide edge runs near the bevelled edge's line
    (|cos| of their angle above 0.9: an n-gon cap's rim neighbour, a cone's rim). Each of the two slide edges s gets a
    direction S: the unit vector along s when s runs near the line, else that vector over sin(its angle to e) (the
    point a plain bevel uses, one width from e). Both new vertices go to v + W x c x S with one c for the vertex: the
    chord between the two faces' unit offsets over the distance between the two S seen along e, so the new edge
    across the end is as long as a plain bevel's there. Returns ([(v position, unit(s), k = distance along s / W,
    s's other vertex)], {s: [lengths / k]}, {vertex handled: (k, unit vector of its slide edge near the line)})."""
    sel = set(edges)
    moves, limits, done = [], {}, {}
    for v in {v for e in edges for v in e.verts}:
        mine = [e for e in v.link_edges if e in sel]
        if len(mine) != 1 or len(mine[0].link_faces) != 2:
            continue
        e = mine[0]
        d = e.other_vert(v).co - v.co
        if d.length <= ZERO:
            continue
        d.normalize()
        slides = [s for f in e.link_faces for s in v.link_edges if s is not e and f in s.link_faces]
        if len(slides) != 2 or slides[0] is slides[1]:
            continue
        units = [s.other_vert(v).co - v.co for s in slides]
        if any(u.length <= ZERO for u in units):
            continue
        units = [u.normalized() for u in units]
        across = [u - d * u.dot(d) for u in units]
        sins = [a.length for a in across]
        lines = [abs(u.dot(d)) > NEAR_LINE for u in units]
        if min(sins) <= ZERO or not any(lines):
            continue
        dirs = [u if line else u / sin for u, sin, line in zip(units, sins, lines)]
        gap = ((dirs[0] - d * dirs[0].dot(d)) - (dirs[1] - d * dirs[1].dot(d))).length
        chord = (across[0] / sins[0] - across[1] / sins[1]).length * end_scale(e, v, sel, corners)
        if gap <= ZERO or chord <= ZERO:
            continue
        near = [u for u, line in zip(units, lines) if line]
        done[v] = (chord / gap, near[0] if len(near) == 1 else None)
        for s, u, x in zip(slides, units, dirs):
            k = chord / gap * x.length
            moves.append((v.co.copy(), u, k, s.other_vert(v)))
            limits.setdefault(s, []).append(s.calc_length() / k)
    return moves, limits, done


def strip_limits(edges, ends):
    """A lone bevelled edge whose two ends both have a slide edge near its line, the two running outwards almost
    parallel (|cos| of their angle above 0.9: a rim edge of an n-gon cap with many sides): the width is limited to
    half the edge's length over k at its first vertex (the lower index), like Maya. ``ends`` = ``end_moves``' third
    result."""
    sel = set(edges)
    out = []
    for e in edges:
        if any(sum(1 for x in v.link_edges if x in sel) != 1 for v in e.verts):
            continue
        a, b = sorted(e.verts, key=lambda v: v.index)
        if a not in ends or b not in ends or ends[a][1] is None or ends[b][1] is None:
            continue
        if -ends[a][1].dot(ends[b][1]) > NEAR_LINE and ends[a][0] > ZERO:
            out.append(e.calc_length() / (2.0 * ends[a][0]))
    return out


def _corner(v, f, sel):
    """Two bevelled edges of face ``f`` meet at ``v``: their new corner moves into ``f`` along the bisector, W / sin(half
    the angle) from v. Returns (unit bisector, half the angle, limit): the limit is the distance to where the bisector
    leaves the face x sin(half the angle), halved when it leaves through a vertex whose own corner moves back along
    the same line (a whole n-gon rim). None when the corner is degenerate."""
    a, b = [e for e in v.link_edges if e in sel and f in e.link_faces][:2]
    ua = (a.other_vert(v).co - v.co)
    ub = (b.other_vert(v).co - v.co)
    if ua.length <= ZERO or ub.length <= ZERO:
        return None
    ua.normalize()
    ub.normalize()
    half = math.acos(max(-1.0, min(1.0, ua.dot(ub)))) / 2.0
    ray = ua + ub
    if ray.length <= ZERO or math.sin(half) <= ZERO:
        return None
    ray.normalize()
    side = ua.cross(ub).cross(ray)      # the ray's line in the face plane: points p with (p - v) . side = 0
    if side.length <= ZERO:
        return None
    best = None
    for loop in f.loops:
        p, q = loop.vert, loop.link_loop_next.vert
        if v in (p, q):
            continue
        sp, sq = (p.co - v.co).dot(side), (q.co - v.co).dot(side)
        if (sp > 0) == (sq > 0) and abs(sp) > ZERO and abs(sq) > ZERO:
            continue
        x = sp / (sp - sq) if abs(sp - sq) > ZERO else 0.0
        hit = p.co.lerp(q.co, x)
        t = (hit - v.co).dot(ray)
        if t > ZERO and (best is None or t < best[0]):
            end = p if x < 1e-4 else q if x > 1 - 1e-4 else None
            best = (t, end)
    if best is None:
        return None
    t, end = best
    shared = 2 if end is not None and sum(1 for e in end.link_edges if e in sel and f in e.link_faces) >= 2 else 1
    return ray, half, t * math.sin(half) / shared


def _corner_reach(v, f, sel, half):
    """An acute or right corner of face ``f`` at ``v``: its new corner (W / sin(half the angle) along the bisector) never
    reaches past the far end of either bevelled edge: its foot on each edge (W / tan(half)) stays within the edge,
    half of it when the edge's other end is a corner of ``f`` too. Returns the width limit for each edge (none for
    a wider corner, where the bisector leaves the face first)."""
    out = []
    if math.tan(half) <= ZERO or half > math.pi / 4.0 + 1e-9:
        return out
    for e in [x for x in v.link_edges if x in sel and f in x.link_faces][:2]:
        end = e.other_vert(v)
        shared = 2 if sum(1 for x in end.link_edges if x in sel and f in x.link_faces) >= 2 else 1
        out.append(e.calc_length() * math.tan(half) / shared)
    return out


def corners_of(edges):
    """{(vertex, face)} where two bevelled edges of the face meet."""
    sel = set(edges)
    out = set()
    for e in edges:
        for v in e.verts:
            for s in v.link_edges:
                if s is not e and s in sel:
                    out.update((v, f) for f in set(e.link_faces).intersection(s.link_faces))
    return out


def corner_moves(edges):
    """Corners of a face where two bevelled edges meet almost straight (|cos| of the angle above 0.9: an n-gon cap with
    many sides): Blender leaves the new corner on the old vertex, Maya moves it W / sin(half the angle) along the
    bisector like any other corner. [(v position, unit bisector, k = 1 / sin(half the angle))]."""
    sel = set(edges)
    out = []
    for v, f in corners_of(edges):
        got = _corner(v, f, sel)
        if got is not None and math.cos(2.0 * got[1]) < -NEAR_LINE:
            out.append((v.co.copy(), got[0], 1.0 / math.sin(got[1])))
    return out


def slide_limit(edges, corners=None, triples=None, splits=None):
    """Maya's fraction base (a perpendicular width): the smallest of
    (a) slide edges — an edge at an end of a bevelled edge that lies in one of its faces: length x sin(angle to the
        bevelled edge) / (number of its ends a bevel slides along); at a chain end where a slide edge runs near the
        bevelled edge's line (``end_moves``) length / k there instead; the third edge of a ``corner_pairs`` corner
        length / k_u3 (where the new vertex on it sits);
    (b) terminal edges at the end of an open chain (``terminal_moves``): length x s_phi / sin(alpha / 2) / (number of
        its ends that are such chain ends);
    (c) corners where two bevelled edges of one face meet (``_corner``): the new corner slides along the bisector
        (at a ``corner_triples`` corner it sits k widths from the edges, so its limit is over k; at a ``corner_splits``
        corner both limits use the placed point).

    #124: a cylinder cap's border ring
    has no face holding two ring edges, so Maya slides along the side / cap fan edges (length 1) — and the width is
    perpendicular, so the fan edges at 81 degrees to the ring give 0.49995 x sin 81 = 0.49379 (the side ring lands at
    y 1.5062, the cap ring at radius 0.5); an n-gon cap gives the same through (c). An edge in no face of the
    bevelled edge is no slide edge; at a chain end it is a terminal edge (part of a cap rim: the unbevelled rim
    neighbour)."""
    sel = set(edges)
    used = {}
    _moves, near, near_ends = end_moves(edges, corners)
    _moves, term, scaled = terminal_moves(edges, corners)
    for e in edges:
        faces = set(e.link_faces)
        d = (e.verts[1].co - e.verts[0].co).normalized()
        for v in e.verts:
            if v in near_ends:
                continue
            for s in v.link_edges:
                if s is e or s in sel or not faces.intersection(s.link_faces):
                    continue
                t = (s.other_vert(v).co - v.co)
                if corners and v in corners and s is corners[v]["rest"]:
                    # the new vertex on the third edge of a paired corner sits k_u3 widths along it
                    sin = 1.0 / corners[v]["k_u3"]
                else:
                    sin = t.normalized().cross(d).length / scaled.get(v, 1.0) if t.length > ZERO else 0.0
                ent = used.setdefault(s, [set(), math.inf])
                ent[0].add(v)
                ent[1] = min(ent[1], sin)
    caps = []
    for v, f in corners_of(edges):
        c = _corner(v, f, sel)
        if c is not None and c[2] > ZERO:
            if splits and v in splits and f in splits[v]["faces"]:
                # an approximate split corner: the same two limits, taken at the placed point
                offset, feet, angle, _ray = splits[v]["faces"][f]
                k = offset.length * math.sin(c[1])
                caps.append(c[2] / k if k > ZERO else c[2])
                if angle <= math.pi / 2.0 + 1e-9:
                    for e in [x for x in v.link_edges if x in sel and f in x.link_faces][:2]:
                        end = e.other_vert(v)
                        shared = 2 if sum(1 for x in end.link_edges if x in sel and f in x.link_faces) >= 2 else 1
                        if feet.get(e, 0.0) > ZERO:
                            caps.append(e.calc_length() / shared / feet[e])
                continue
            k = triples[v]["faces"].get(f, (None, None, 1.0))[2] if triples and v in triples else 1.0
            caps.append(c[2] / k)
            caps += [x / k for x in _corner_reach(v, f, sel, c[1])]
    for s in set(used) | set(near):
        if s.calc_length() <= ZERO:
            continue
        ends, sin = used.get(s, (set(), 1.0))
        lengths = near.get(s, []) + ([s.calc_length() * sin] if ends else [])
        caps.append(min(lengths) / (len(ends) + len(near.get(s, []))))
    caps += strip_limits(edges, near_ends)
    caps += [min(ls) / len(ls) for ls in term.values()]
    if caps:
        return min(caps)
    return min((e.calc_length() for e in sel), default=0.0)


def profile(depth):
    t = 0.5 + max(-1.0, min(1.0, depth)) * (math.sqrt(0.5) - 0.5)
    return max(0.0, min(1.0, t * t))


def width(edges, fraction=0.5, offset_as_fraction=True, offset=0.2, unit=1.0, corners=None, triples=None, splits=None):
    if offset_as_fraction:
        return max(0.0, min(1.0, fraction)) * slide_limit(edges, corners, triples, splits) * FIT
    return max(0.0, offset) * unit * FIT


def past_ends(edges, w, spokes=False):
    """Absolute Offset, slides longer than their side edge: Blender stops the new vertex at the side edge's far vertex, Maya goes on
    along that edge's line by width / sin(angle to the bevelled edge), past the mesh. With ``spokes`` (an absolute
    Offset) the new vertex on an edge in neither of the bevelled edge's faces (a cap fan's spoke) is always put at the
    width along it. Only at an
    end with one bevelled edge. Returns [(far vertex position, origin, unit direction, slide)]."""
    sel = set(edges)
    out = []
    for e in edges:
        for v in e.verts:
            if sum(1 for x in v.link_edges if x in sel) != 1:
                continue
            d = (e.other_vert(v).co - v.co)
            if d.length <= ZERO:
                continue
            d.normalize()
            sides = _slides(e, v)
            others = [x for x in v.link_edges if x is not e and x not in sides] if spokes else []
            for s in sides + others:
                if s in sel:
                    continue
                u = s.other_vert(v).co - v.co
                length = u.length
                if length <= ZERO:
                    continue
                u.normalize()
                if s in sides and abs(u.dot(d)) > NEAR_LINE:
                    continue      # a side edge near the bevelled edge's line: end_moves places that vertex
                sin = math.sqrt(max(0.0, 1.0 - u.dot(d) ** 2)) if s in sides else 1.0
                slide = w / sin
                # a spoke's vertex is always at the width (Blender moves it with a negative Depth)
                if slide > length * (1.0 + 1e-6) or s not in sides:
                    out.append((s.other_vert(v).co.copy(), v.co.copy(), u, slide))
    return out
