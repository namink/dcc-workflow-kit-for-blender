# SPDX-License-Identifier: GPL-3.0-or-later
"""Quad Draw's mesh and screen geometry, no view or tool state (tested headless): the fill polygon around the mouse
(``fill_order``, ``fill_face``), edge / border loops (``edge_loop``, ``border_chain``, ``component_loop``), Tab extend,
inner-corner quad and quad strip (``extend_edges``, ``corner_quad``, ``strip_pairs``, ``strip_faces``), ``relax``,
``delete_at`` / ``delete_loop``, the weld target and the dot layer (``add_dot``, ``dots``, ``clear_dots``).
"""

import itertools
import math

import bmesh
from mathutils import Vector

from . import poly_draw

DOT_LAYER = "allset_dot"   # int vertex layer: 1 = a Quad Draw dot (a loose vertex until a face uses it)
RELAX_STEP = 0.5        # share of the way to the neighbours' average per brush move


# --- pure: fill ---------------------------------------------------------------------------------------

def _inside(poly, p):
    """Point-in-polygon (even-odd) in 2D."""
    x, y = p
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside


def _area(poly):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))


def _simple(poly):
    """No two non-adjacent sides cross."""
    n = len(poly)

    def cross(a, b, c, d):
        def orient(p, q, r):
            return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if cross(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]):
                return False
    return True


def fill_order(xy, mouse, nearest=6, banned=()):
    """Maya Shift+click fill: indices (counter-clockwise on screen) of the 4 points of ``xy`` — else 3 — around
    ``mouse``, chosen among the ``nearest`` closest: the polygon must contain the mouse, be simple, and not be a set in
    ``banned`` (frozensets of indices, e.g. existing faces); the smallest such polygon wins. None if there is none."""
    order = sorted(range(len(xy)), key=lambda i: math.hypot(xy[i][0] - mouse[0], xy[i][1] - mouse[1]))[:nearest]
    for n in (4, 3):
        best = None
        for combo in itertools.combinations(order, n):
            if frozenset(combo) in banned:
                continue
            cx = sum(xy[i][0] for i in combo) / n
            cy = sum(xy[i][1] for i in combo) / n
            ring = sorted(combo, key=lambda i: math.atan2(xy[i][1] - cy, xy[i][0] - cx))
            poly = [tuple(xy[i]) for i in ring]
            area = _area(poly)
            if area <= 1e-6 or not _simple(poly) or not _inside(poly, mouse):
                continue
            if best is None or area < best[0]:
                best = (area, ring)
        if best is not None:
            return best[1]
    return None


def fill_face(bm, ring):
    """The fill polygon: ``ring`` items are BMVerts or local Vectors (new vertices), counter-clockwise as seen by the
    viewer (= Blender's front side). The face is flipped if it runs along a shared edge the same way as its neighbour
    (consistent normals). Returns the face or None."""
    verts = [r if isinstance(r, bmesh.types.BMVert) else bm.verts.new(r) for r in ring]
    if len(set(verts)) < 3 or bm.faces.get(verts) is not None:
        return None
    try:
        face = bm.faces.new(verts)
    except ValueError:
        return None
    flips = keeps = 0
    for loop in face.loops:
        for other in loop.edge.link_loops:
            if other.face is face:
                continue
            if other.vert is loop.vert:
                flips += 1
            else:
                keeps += 1
    if flips > keeps:
        face.normal_flip()
    face.normal_update()
    _indices(bm)
    return face


def _indices(bm):
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    bm.normal_update()


# --- pure: extend / strip -------------------------------------------------------------------------------

def edge_loop(edge):
    """The edge loop through ``edge``: across each 4-edge vertex to the edge that shares no face with the last one
    (stops at borders, poles and where it closes)."""
    out, seen = [edge], {edge}
    for start in edge.verts:
        e, cur = edge, start
        while len(cur.link_edges) == 4:
            if any(f.hide or len(f.verts)!=4 for f in cur.link_faces):break
            faces = set(e.link_faces)
            nxt = [x for x in cur.link_edges if x is not e and not set(x.link_faces) & faces]
            if len(nxt) != 1 or nxt[0] in seen or nxt[0].hide or any(v.hide for v in nxt[0].verts):
                break
            e = nxt[0]
            seen.add(e)
            out.append(e)
            cur = e.other_vert(cur)
    return out


def border_loop(edge):
    """Border edges connected to border ``edge`` along the border (one open or closed chain)."""
    out, todo = {edge}, [edge]
    while todo:
        e = todo.pop()
        for v in e.verts:
            for e2 in v.link_edges:
                if e2.is_boundary and e2 not in out:
                    out.add(e2)
                    todo.append(e2)
    return list(out)


def border_chain(edge):
    """Boundary edge loop, stopping at corners/poles instead of turning around the entire border."""
    out, seen = [edge], {edge}
    for start in edge.verts:
        cur, previous = start, edge
        while len(cur.link_edges) == 3:
            candidates = [e for e in cur.link_edges if e.is_boundary and e is not previous and not e.hide and not any(v.hide for v in e.verts)]
            if len(candidates) != 1 or candidates[0] in seen:
                break
            previous = candidates[0]
            seen.add(previous)
            out.append(previous)
            cur = previous.other_vert(cur)
    return out


def component_loop(edge):
    """The editable loop: a boundary chain or a regular interior quad loop."""
    if edge.hide or any(v.hide for v in edge.verts) or len(edge.link_faces)>2:return []
    return border_chain(edge) if edge.is_boundary else edge_loop(edge)


def extend_edges(bm, edges, offset, positions=None, created=None):
    """Tab+drag: a quad on each border edge, its far side = the edge's vertices moved by ``offset(co) -> new co``
    (shared between neighbouring edges). Returns the new faces."""
    new = {}
    faces = []
    for e in edges:
        if not e.is_valid or not e.is_boundary:
            continue
        b, a = poly_draw.edge_start(e)       # against the bordering face's winding
        for v in (a, b):
            if v not in new:
                co=positions[v.index] if positions is not None else offset(v.co.copy())
                new[v] = bm.verts.new(co)
                if created is not None:
                    created[v.index]=new[v]
        try:
            faces.append(bm.faces.new((b, a, new[a], new[b])))
        except ValueError:
            pass
    _indices(bm)
    return faces


def corner_neighbours(v):
    """(A, B): the other ends of the two border edges at border vertex ``v`` (in the winding a face appended there
    needs), or None when ``v`` doesn't have exactly two border edges."""
    border = [e for e in v.link_edges if e.is_boundary]
    if len(border) != 2:
        return None
    first, second = border
    start, end = poly_draw.edge_start(first)
    a = first.other_vert(v)
    b = second.other_vert(v)
    # the new face runs along ``first`` as edge_start says: A -> V when it starts at A, else V -> A (then reversed)
    return (a, b) if start is a else (b, a)


def corner_quad(bm, v, co):
    """Tab+drag from border vertex ``v`` (Maya 2026 Quad Draw, Maya's help "Extend edges with Quad Draw": with
    the Edge extend option a vertex can be dragged to create a polygon): the quad A, V, B, N of ``v``, its two border
    neighbours and a new vertex at local ``co``. Only where that quad fills the open side of ``v`` (an inner corner):
    at an outer corner or a straight border it would fold over the faces there, and nothing is made
    (a kit choice). Returns the face or None."""
    pair = corner_neighbours(v)
    if pair is None:
        return None
    a, b = pair
    n = sum((f.normal for f in v.link_faces), Vector())
    if n.length < 1e-9:
        return None
    n.normalize()

    def flat(p):
        d = p - v.co
        return d - n * d.dot(n)
    pa, pb, pn = flat(a.co), flat(b.co), flat(co)
    # N on the far side of A-B from V, and a convex quad A V B N seen along the normal
    ab = pb - pa
    side_v = ab.cross(-pa).dot(n)
    side_n = ab.cross(pn - pa).dot(n)
    if side_v * side_n >= 0:
        return None
    ring = [Vector(), pa, pn, pb]           # V, A, N, B in order around the quad
    turns = [(ring[(i + 1) % 4] - ring[i]).cross(ring[(i + 2) % 4] - ring[(i + 1) % 4]).dot(n) for i in range(4)]
    if not (all(t > 1e-12 for t in turns) or all(t < -1e-12 for t in turns)):
        return None
    if any(f.calc_center_median() is not None and _inside_quad(flat(f.calc_center_median()), ring, n)
           for f in v.link_faces):
        return None                          # the quad would lie over a face at V
    nv = bm.verts.new(co)
    try:
        face = bm.faces.new((a, v, b, nv))
    except ValueError:
        bm.verts.remove(nv)
        return None
    _indices(bm)
    return face


def _inside_quad(p, ring, n):
    signs = [(ring[(i + 1) % 4] - ring[i]).cross(p - ring[i]).dot(n) for i in range(4)]
    return all(x > 0 for x in signs) or all(x < 0 for x in signs)


def strip_pairs(path, width):
    """Tab+drag in empty space: (left, right) screen points every ``width`` pixels along ``path`` (a list of screen
    points), ``width`` apart across the path. Needs a path at least ``width`` long."""
    pts = [path[0]]
    acc = 0.0
    for a, b in zip(path, path[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if seg < 1e-9:
            continue
        t = 0.0
        while acc + (seg - t) >= width:
            t += width - acc
            acc = 0.0
            pts.append((a[0] + (b[0] - a[0]) * t / seg, a[1] + (b[1] - a[1]) * t / seg))
        acc += seg - t
    if len(pts) < 2:
        return []
    out = []
    for k, p in enumerate(pts):
        q0 = pts[max(0, k - 1)]
        q1 = pts[min(len(pts) - 1, k + 1)]
        dx, dy = q1[0] - q0[0], q1[1] - q0[1]
        n = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n * width / 2, dx / n * width / 2
        out.append(((p[0] + nx, p[1] + ny), (p[0] - nx, p[1] - ny)))
    return out


def width_preview(center, width, count=3):
    """Tab+MMB drag in empty space: the screen line segments of a preview strip of ``count`` quads ``width`` pixels
    wide, running up from ``center`` (the quads a Tab+LMB stroke of that width would make)."""
    x, y = center
    pairs = strip_pairs([(x, y), (x, y + width * count)], width)
    segs = []
    for k, (left, right) in enumerate(pairs):
        segs += [left, right]
        if k:
            segs += [pairs[k - 1][0], left, pairs[k - 1][1], right]
    return segs


def strip_faces(bm, pairs):
    """Quads between consecutive (left, right) local points; winding: counter-clockwise for a path seen from the
    viewer going left to right on screen with left = +normal side (callers pass screen-ordered pairs)."""
    faces = []
    prev = None
    for left, right in pairs:
        cur = (bm.verts.new(left), bm.verts.new(right))
        if prev is not None:
            faces.append(bm.faces.new((prev[1], cur[1], cur[0], prev[0])))
        prev = cur
    _indices(bm)
    return faces


# --- pure: relax / delete -------------------------------------------------------------------------------

def relax(bm, verts, mode='AUTO_LOCK', step=RELAX_STEP, project=None):
    """Maya Quad Draw relax on ``verts``: each moves ``step`` of the way to its neighbours' average (border vertices
    along the border only). ``mode``: AUTO_LOCK = border vertices stay when an inner one is among ``verts``,
    INTERIOR = only inner vertices, BORDER = only border ones. ``project(co) -> co`` puts them back on the surface.
    Returns the moved vertices."""
    verts = [v for v in verts if v.is_valid and v.link_edges]
    inner = [v for v in verts if not v.is_boundary]
    border = [v for v in verts if v.is_boundary]
    if mode == 'INTERIOR' or (mode == 'AUTO_LOCK' and inner):
        moving = inner
    elif mode == 'ALL':
        moving = verts
    elif mode == 'BORDER':
        moving = border
    else:
        moving = border
    targets = {}
    for v in moving:
        if v.is_boundary and mode != 'ALL':
            nb = [e.other_vert(v) for e in v.link_edges if e.is_boundary]
        else:
            nb = [e.other_vert(v) for e in v.link_edges]
        if not nb:
            continue
        avg = sum((u.co for u in nb), Vector()) / len(nb)
        targets[v] = v.co.lerp(avg, step)
    for v, co in targets.items():
        v.co = project(co) if project else co
    return list(targets)


def delete_at(bm, kind, index):
    """Ctrl+Shift+click: delete the face; an edge (inside: dissolved into one face; on the border: its face goes);
    a vertex (inside: dissolved; on the border: with its faces). True if something went."""
    seq = {'VERT': bm.verts, 'EDGE': bm.edges, 'FACE': bm.faces}[kind]
    seq.ensure_lookup_table()
    if index >= len(seq):
        return False
    el = seq[index]
    if kind == 'FACE':
        bmesh.ops.delete(bm, geom=[el], context='FACES')
    elif kind == 'EDGE':
        if len(el.link_faces) == 2:
            bmesh.ops.dissolve_edges(bm, edges=[el], use_verts=True)
        elif el.link_faces:
            bmesh.ops.delete(bm, geom=list(el.link_faces), context='FACES')
        else:
            bmesh.ops.delete(bm, geom=[el], context='EDGES')
    else:
        if el.link_faces and not el.is_boundary and len(el.link_edges) > 2:
            bmesh.ops.dissolve_verts(bm, verts=[el])
        else:
            bmesh.ops.delete(bm, geom=[el], context='VERTS')
    _indices(bm)
    return True


def delete_loop(bm, edge_index):
    """Ctrl+Shift+click an edge: its edge loop goes (inner edges dissolve; a border edge takes its faces)."""
    bm.edges.ensure_lookup_table()
    edge = bm.edges[edge_index]
    if edge.hide or any(v.hide for v in edge.verts) or len(edge.link_faces)>2:return False
    if edge.is_boundary:
        faces={f for e in component_loop(edge) for f in e.link_faces if not f.hide}
        if not faces:return False
        bmesh.ops.delete(bm,geom=list(faces),context='FACES');_indices(bm)
        return True
    if len(edge.link_faces) != 2:
        return delete_at(bm, 'EDGE', edge_index)
    loop = [e for e in component_loop(edge) if len(e.link_faces) == 2]
    bmesh.ops.dissolve_edges(bm, edges=loop, use_verts=True)
    _indices(bm)
    return True


def weld_target(xy, moved, mouse_xy, radius, exclude=()):
    """Index of the vertex whose screen point is within ``radius`` of ``mouse_xy`` (closest), not ``moved`` and not
    in ``exclude``; None if none (Auto-weld)."""
    best = None
    for i, p in enumerate(xy):
        if i == moved or i in exclude or p is None:
            continue
        d = math.hypot(p[0] - mouse_xy[0], p[1] - mouse_xy[1])
        if d <= radius and (best is None or d < best[0]):
            best = (d, i)
    return best[1] if best else None


# --- dots -----------------------------------------------------------------------------------------------

def dot_layer(bm, create=False):
    """The int vertex layer that marks Quad Draw dots (made first: a new layer invalidates element references)."""
    lay = bm.verts.layers.int.get(DOT_LAYER)
    if lay is None and create:
        lay = bm.verts.layers.int.new(DOT_LAYER)
    return lay


def dots(bm):
    """Maya's dots: loose vertices Quad Draw placed (no edge yet). Being vertices, they undo with the mesh."""
    lay = dot_layer(bm)
    if lay is None:
        return []
    return [v for v in bm.verts if v[lay] and not v.link_edges]


def add_dot(bm, co):
    """A dot at local ``co``; returns the vertex."""
    lay = dot_layer(bm, create=True)
    v = bm.verts.new(co)
    v[lay] = 1
    v.select = False
    _indices(bm)
    return v


def clear_dots(bm):
    """Remove every dot (Clear Dots, leaving the tool). Returns how many went."""
    gone = dots(bm)
    for v in gone:
        bm.verts.remove(v)
    if gone:
        _indices(bm)
    return len(gone)


def fill_candidates(bm):
    """Vertices a fill can use: dots, border vertices and vertices on no face yet."""
    return [v for v in bm.verts if not v.hide and (v.is_boundary or not v.link_faces)]
