# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit Mesh > Bevel: the profile shapes for Segments > 1. Maya's circular profile between the two width points
(``arc_points``, ``frame_points``, ``true_arcs``) and profiles meeting where three or more bevelled edges meet
(``hub_profile_frames``, ``flat_corners``: one flat polygon). Chamfer off is Blender's square profile
(``bevel_maya``). Used by the bevel driver in ``bevel_maya``.
"""

import math

import bmesh

from .bevel_width import ZERO


def profile_interior(bm, elay, strip, segments):
    """Segments > 1: the points between the two ends of every profile (both ends of each edge's strip)."""
    rails = {}
    for e in bm.edges:
        if e[elay]:
            rails.setdefault(e[elay], []).append(e)
    out = []
    for tag, rs in rails.items():
        if len(rs) != 2:
            continue
        walk = _strip_chains(rs[0], tag, elay, strip, segments)
        if walk is not None:
            out.extend(walk[0][1:-1] + walk[1][1:-1])
    return out


def arc_points(p0, p1, n0, n1, segments, depth=1.0):
    """Maya's profile between the two width points ``p0`` / ``p1``: the circle touching face normal ``n0`` at p0
    and ``n1`` at p1, cut in equal angle steps; Depth d moves each arc point A from its foot Q on the chord p0-p1:
    Q + d (A - Q) (0 = on the chord, -1 = mirrored). Returns the ``segments - 1`` inner points."""
    chord = p1 - p0
    n0, n1 = n0.normalized(), n1.normalized()
    # the centre = where the lines p0 - t n0 and p1 - s n1 meet; None when they miss each other (a profile at a
    # slant to its edge: Blender's own profile is Maya's there) or the faces are parallel
    b = n0.dot(n1)
    den = 1.0 - b * b
    if den <= 1e-9 or chord.length <= ZERO:
        return None
    w0 = p0 - p1
    t = (w0.dot(n0) - b * w0.dot(n1)) / den
    s = (b * w0.dot(n0) - w0.dot(n1)) / den
    c0, c1 = p0 - n0 * t, p1 - n1 * s
    # a concave edge has its centre on the empty side (t, s < 0): the same circle, a fillet
    if t * s <= 0.0 or (c0 - c1).length > 1e-5 * chord.length:
        return None
    centre = (c0 + c1) / 2
    u0, u1 = p0 - centre, p1 - centre
    angle = u0.angle(u1, 0.0)
    d = chord.normalized()
    depth = max(-1.0, min(1.0, depth))
    out = []
    for k in range(1, segments):
        f = k / segments
        if angle <= 1e-9:
            a = p0.lerp(p1, f)
        else:
            sa = math.sin(angle)
            a = centre + u0 * (math.sin((1 - f) * angle) / sa) + u1 * (math.sin(f * angle) / sa)
        q = p0 + d * (a - p0).dot(d)
        out.append(q + (a - q) * depth)
    return out


def _strip_chains(rail, tag, elay, strip, segments):
    """Walk an edge's strip of bevel quads from its outer edge ``rail`` to the other outer edge (same ``tag``).
    Returns (chain at one end, chain at the other end, first outer edge, last outer edge) or None."""
    va, vb = rail.verts
    chain_a, chain_b = [va], [vb]
    cur, prev = rail, None
    for _ in range(segments):
        f = next((x for x in cur.link_faces if x in strip and x is not prev and len(x.verts) == 4), None)
        if f is None:
            return None
        a2 = next((e.other_vert(va) for e in f.edges if e is not cur and va in e.verts), None)
        b2 = next((e.other_vert(vb) for e in f.edges if e is not cur and vb in e.verts), None)
        nxt = next((e for e in f.edges if a2 in e.verts and b2 in e.verts), None) if a2 and b2 else None
        if nxt is None:
            return None
        va, vb, prev, cur = a2, b2, f, nxt
        chain_a.append(va)
        chain_b.append(vb)
        if cur[elay] == tag:
            return chain_a, chain_b, rail, cur
    return None


def _side_normal(rail, strip):
    """Normal of the old face next to an outer strip edge."""
    f = next((x for x in rail.link_faces if x not in strip), None)
    return f.normal.copy() if f is not None else None


def frame_points(v, e0, e1, segments, depth=1.0):
    """Maya's profile at an edge end with one or two bevelled edges: the arc for the angle e0-v-e1 taken in the
    plane (v, e0, e1), as point = v + a (e0 - v) + b (e1 - v) with (a, b) from the unit profile (a circle touching
    both unit legs at their ends, equal angle steps), Depth toward the chord. Also the join where two bevelled
    edges meet. Returns the ``segments - 1`` inner points or None."""
    u0, u1 = e0 - v, e1 - v
    if u0.length <= ZERO or u1.length <= ZERO:
        return None
    c = max(-1.0, min(1.0, u0.normalized().dot(u1.normalized())))
    theta = math.acos(c)
    if theta <= 1e-6 or theta >= math.pi - 1e-6:
        return None
    # unit legs l0 = (1, 0), l1 = (cos t, sin t); the circle touching both at their ends has its centre at
    # (1, tan(t / 2)); its radius turns from l0's end to l1's end through pi - t
    r = math.tan(theta / 2.0)
    sweep = math.pi - theta
    depth = max(-1.0, min(1.0, depth))
    out = []
    for k in range(1, segments):
        ang = sweep * k / segments
        px = 1.0 - r * math.sin(ang)
        py = r - r * math.cos(ang)
        # chord point (depth): foot on the chord from (1, 0) to (cos t, sin t)
        ax, ay = 1.0, 0.0
        bx, by = c, math.sin(theta)
        dx, dy = bx - ax, by - ay
        dl = math.hypot(dx, dy)
        t = ((px - ax) * dx + (py - ay) * dy) / (dl * dl)
        qx, qy = ax + dx * t, ay + dy * t
        px, py = qx + (px - qx) * depth, qy + (py - qy) * depth
        # back to leg coordinates: p = a l0 + b l1
        b = py / math.sin(theta)
        a = px - b * c
        out.append(v + u0 * a + u1 * b)
    return out


def hub_profile_frames(edges, verts):
    """{(rounded old vertex position, edge tag): (vertex, unit edge direction, mean sine)} where three or more
    bevelled edges meet. There the profile of a bevelled edge lies in the plane through its two ends and the point
    of the edge at width / s from the vertex, s = the mean of sin(angle between the edge and the other edge of the
    face at the vertex) over its two faces (the harmonic mean of where the neighbouring width lines cross it). The
    profile's corner is where the lines from each end along that face's other edge (seen in the plane) meet.
    Tags = index in ``edges`` + 1, as ``true_arcs`` sees them."""
    index = {e: i + 1 for i, e in enumerate(edges)}
    out = {}
    for v in verts:
        if sum(1 for e in v.link_edges if e in index) < 3:
            continue
        for e in v.link_edges:
            if e not in index:
                continue
            d = e.other_vert(v).co - v.co
            if d.length <= ZERO or len(e.link_faces) != 2:
                continue
            d.normalize()
            sines, sides = [], []
            for f in e.link_faces:
                f.normal_update()
                other = next((x for x in v.link_edges if x is not e and f in x.link_faces), None)
                if other is None:
                    break
                u = (other.other_vert(v).co - v.co).normalized()
                sines.append(math.sqrt(max(0.0, 1.0 - u.dot(d) ** 2)))
                sides.append((f.normal.copy(), u))
            if len(sines) == 2 and min(sines) > 1e-6:
                out[(_key(v.co), index[e])] = (v.co.copy(), d, (sines[0] + sines[1]) / 2.0, sides)
    return out


def _corner_in_plane(p0, p1, plane, n0, n1, sides):
    """Where the lines from p0 and p1 along their face's other vertex edge (projected into ``plane``) meet. The face
    of each end is the side whose normal is closest to ``n0`` / ``n1``."""
    def along(n):
        u = max(sides, key=lambda s: s[0].dot(n))[1]
        u = u - plane * u.dot(plane)
        return u if u.length > ZERO else None
    u0, u1 = along(n0), along(n1)
    if u0 is None or u1 is None:
        return None
    # p0 + a u0 = p1 + b u1 (least squares in the plane)
    m00, m01, m11 = u0.dot(u0), -u0.dot(u1), u1.dot(u1)
    r = p1 - p0
    r0, r1 = u0.dot(r), -u1.dot(r)
    det = m00 * m11 - m01 * m01
    if abs(det) <= 1e-12:
        return None
    a = (r0 * m11 - m01 * r1) / det
    return p0 + u0 * a


def _key(co):
    return tuple(round(c, 5) for c in co)


def true_arcs(bm, elay, strip, segments, depth, hubs, hub_frames=None, w=0.0):
    """Segments > 1: Maya's profiles. At an end with one or two bevelled edges ``frame_points`` (the arc in the
    plane of the old vertex and the profile's ends); where three or more meet, the circle touching both faces
    (``arc_points``)."""
    rails = {}
    for e in bm.edges:
        if e[elay]:
            rails.setdefault(e[elay], []).append(e)
    for f in bm.faces:
        f.normal_update()

    def end_of(chain):
        if not hubs:
            return None
        mid = chain[len(chain) // 2].co
        return min(hubs, key=lambda x: (mid - x[0]).length_squared)

    for tag, rs in rails.items():
        if len(rs) != 2:
            continue
        walk = _strip_chains(rs[0], tag, elay, strip, segments)
        if walk is None:
            continue
        chain_a, chain_b, first, last = walk
        if len(chain_a) != segments + 1:
            continue
        n0, n1 = _side_normal(first, strip), _side_normal(last, strip)
        for chain in (chain_a, chain_b):
            p0, p1 = chain[0].co.copy(), chain[-1].co.copy()
            hub = end_of(chain)
            frame = (hub_frames or {}).get((_key(hub[0]), tag)) if hub is not None and hub[1] >= 3 else None
            corner = None
            if frame is not None and n0 is not None and n1 is not None and w > 0.0:
                v0, d, sine, sides = frame
                t_pt = v0 + d * (w / sine)
                plane = (p1 - p0).cross(t_pt - p0)
                if plane.length > ZERO:
                    plane.normalize()
                    corner = _corner_in_plane(p0, p1, plane, n0, n1, sides)
            if hub is not None and hub[1] <= 2:
                pts = frame_points(hub[0], p0, p1, segments, depth)
            elif corner is not None:
                pts = frame_points(corner, p0, p1, segments, depth)
            elif n0 is not None and n1 is not None:
                pts = arc_points(p0, p1, n0, n1, segments, depth)
            else:
                pts = None
            if pts is not None:
                for v, p in zip(chain[1:-1], pts):
                    v.co = p



def _three_planes(a, b, c):
    """The point on three planes (normal, n . x) or None."""
    (na, da), (nb, db), (nc, dc) = a, b, c
    den = na.dot(nb.cross(nc))
    if abs(den) <= 1e-12:
        return None
    return (nb.cross(nc) * da + nc.cross(na) * db + na.cross(nb) * dc) / den


def flat_corners(bm, made, hubs):
    """Where three or more bevelled edges meet, or one bevelled edge ends at a vertex with more edges (a cap's fan
    spokes), Maya closes the corner with one polygon through the ends of the edges' profiles and the spoke points
    (Segments 2 = a hexagon at a box corner, 3 = a 9-gon). Blender fills it with a patch of quads around inner
    vertices, or with triangles: the inner vertices and the edges inside the patch are dissolved. Returns ``made``
    without the dissolved vertices."""
    if not made or not any(n != 2 for _co, n in hubs):
        return made
    made_set = set(made)
    # each new vertex belongs to the bevelled vertex it was made from: the nearest old position
    at = {v: min(range(len(hubs)), key=lambda i: (v.co - hubs[i][0]).length_squared) for v in made}

    def patch_face(f, h):
        return all(x in made_set and at[x] == h for x in f.verts)

    inner = []
    for v in made:
        h = at[v]
        faces = list(v.link_faces)
        if hubs[h][1] != 2 and len(faces) >= 3 and all(patch_face(f, h) for f in faces):
            inner.append(v)
    if inner:
        bmesh.ops.dissolve_verts(bm, verts=inner)
    made = [v for v in made if v.is_valid]
    inside = []
    for e in {e for v in made for e in v.link_edges}:
        a, b = e.verts
        if a not in at or b not in at or at[a] != at[b] or hubs[at[a]][1] == 2 or len(e.link_faces) != 2:
            continue
        if all(patch_face(f, at[a]) for f in e.link_faces):
            inside.append(e)
    if inside:
        bmesh.ops.dissolve_edges(bm, edges=inside, use_verts=False)
    return made
