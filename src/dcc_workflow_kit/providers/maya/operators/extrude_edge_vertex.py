# SPDX-License-Identifier: GPL-3.0-or-later
"""polyExtrudeEdge and polyExtrudeVertex on a bmesh (``extrude_edges``, ``extrude_vertices``: edges / vertices extrude
at once, no drag), the edge frame of an extruded edge (``edge_frame``), ``deselect_all`` and the specs ``EDGE`` /
``VERTEX``. Related: extrude_spec.py, extrude_face.py, extrude.py.
"""

import bmesh
from mathutils import Vector

from .extrude_face import _offset_dir
from .extrude_spec import LABELS, Spec, add_spec


# --- polyExtrudeEdge / polyExtrudeVertex ------------

def deselect_all(bm):
    for seq in (bm.faces, bm.edges, bm.verts):
        for el in seq:
            el.select = False


def _unit_or(vec, fallback):
    return vec.normalized() if vec.length > 1e-9 else Vector(fallback)


def edge_frame(e):
    """Maya's local frame of an extruded edge: X along the edge, Z = mean of the adjacent face normals (Local
    Translate Z / Thickness), Y = Z x X. A border edge (one face) runs against its face's winding, so Y points out
    of the face (Offset); an edge between faces runs a -> b (its vertex order)."""
    a, b = _edge_ends(e)
    x = _unit_or(b.co - a.co, (1.0, 0.0, 0.0))
    z = _unit_or(sum((f.normal for f in e.link_faces), Vector()), (0.0, 0.0, 1.0))
    y = _unit_or(z.cross(x), (0.0, 1.0, 0.0))
    return x, y, z


def _edge_ends(e):
    """(a, b) of an edge in Maya's X order: against the winding of its only face, else the vertex order."""
    if len(e.link_faces) == 1:
        loop = next(lp for lp in e.link_loops)
        return loop.link_loop_next.vert, loop.vert
    return e.verts[0], e.verts[1]


def extrude_edges(bm, edges, thickness=0.0, local_translate_z=0.0, offset=0.0, divisions=1, keep_faces_together=True,
                  unit=1.0, levels=None, **_unused):
    """Maya polyExtrudeEdge: every edge gets ``divisions`` quads ``(a, b, b', a')``. Keep Faces Together on (like
    Maya's Edit Mesh > Extrude) = connected edges share their new vertices; off = every edge alone.
    A new vertex moves by Local Translate Z x the mean Z of its edges + Thickness x the unit mean Z + Offset out of
    the face (border edges only, mitred at a corner; an edge between two faces gets none), in Maya units.
    The outer edges end up selected. Returns the new vertices; ``levels`` (a dict) gets {new vertex: (division,
    vertex it comes from)}."""
    bm.normal_update()
    edges = [e for e in edges if e.is_valid]
    k = max(1, int(divisions))
    plan = []
    for e in edges:
        a, b = _edge_ends(e)
        _x, y, z = edge_frame(e)
        plan.append((e, a, b, y if len(e.link_faces) == 1 else None, z))

    def move(zs, ys):
        mean_z = sum(zs, Vector()) / len(zs)
        d = mean_z * local_translate_z + _unit_or(mean_z, zs[0]) * thickness
        if ys and offset:
            d += _offset_dir(ys) * offset      # each border edge moves out by Offset
        return d * unit

    if keep_faces_together:
        zs, ys = {}, {}
        for _e, a, b, y, z in plan:
            for v in (a, b):
                zs.setdefault(v, []).append(z)
                if y is not None:
                    ys.setdefault(v, []).append(y)
        disp = {v: move(zs[v], ys.get(v, [])) for v in zs}
        cols = {v: [v] + [bm.verts.new(v.co + disp[v] * (j / k)) for j in range(1, k + 1)] for v in zs}
        new = [c for col in cols.values() for c in col[1:]]
        if levels is not None:
            levels.update({c: (j, col[0]) for col in cols.values() for j, c in enumerate(col[1:], 1)})
        ends = [(cols[a], cols[b], e) for e, a, b, _y, _z in plan]
    else:
        new, ends = [], []
        for e, a, b, y, z in plan:
            d = move([z], [y] if y is not None else [])
            ca = [a] + [bm.verts.new(a.co + d * (j / k)) for j in range(1, k + 1)]
            cb = [b] + [bm.verts.new(b.co + d * (j / k)) for j in range(1, k + 1)]
            new += ca[1:] + cb[1:]
            ends.append((ca, cb, e))
            if levels is not None:
                levels.update({c: (j, col[0]) for col in (ca, cb) for j, c in enumerate(col[1:], 1)})
    outer = []
    for ca, cb, e in ends:
        example = e.link_faces[0] if e.link_faces else None
        for j in range(k):
            bm.faces.new((ca[j], cb[j], cb[j + 1], ca[j + 1]), example)
        outer.append(bm.edges.get((ca[k], cb[k])))
    deselect_all(bm)
    for e in outer:
        if e is not None:
            e.select_set(True)
    bm.select_flush_mode()
    bm.normal_update()
    return new


def _split_edges_at(bm, verts, width):
    """Split every edge of ``verts`` at ``width`` x its length from the vertex (Maya width = a fraction of each
    edge, on a 4 x 1 x 2 box). Returns {vertex: [base vertices]}."""
    vset = set(verts)
    base = {v: [] for v in verts}
    edges = sorted({e for v in verts for e in v.link_edges}, key=lambda e: e.index)
    plan = []
    for e in edges:
        a, b = e.verts
        plan.append((e, a, b, {x: x.co + (e.other_vert(x).co - x.co) * width for x in (a, b) if x in vset}))
    for e, a, b, targets in plan:
        cur = e
        if a in targets:
            _ne, nv = bmesh.utils.edge_split(cur, a, 0.5)
            nv.co = targets[a]
            base[a].append(nv)
            cur = bm.edges.get((nv, b))
        if b in targets and cur is not None:
            _ne, nv = bmesh.utils.edge_split(cur, b, 0.5)
            nv.co = targets[b]
            base[b].append(nv)
    return base


def _cut_corner(bm, v):
    """Cut every face around ``v`` between its two neighbours: ``v`` keeps only triangles (Maya's cone)."""
    for f in list(v.link_faces):
        if len(f.verts) <= 3:
            continue
        loop = next(lp for lp in f.loops if lp.vert is v)
        p, q = loop.link_loop_prev.vert, loop.link_loop_next.vert
        if bm.edges.get((p, q)) is None:
            bmesh.utils.face_split(f, p, q)


def _rings(bm, v, k):
    """``k`` - 1 rings on the cone of ``v`` (Maya divisions: rings at j/k from the base ring to the tip)."""
    tris = [f for f in v.link_faces if len(f.verts) == 3]
    ring = {}

    def at(b, j):
        if j == 0:
            return b
        if j == k:
            return v
        key = (b, j)
        if key not in ring:
            ring[key] = bm.verts.new(b.co + (v.co - b.co) * (j / k))
        return ring[key]

    rebuild = []
    for f in tris:
        loop = next(lp for lp in f.loops if lp.vert is v)
        rebuild.append((loop.link_loop_next.vert, loop.link_loop_next.link_loop_next.vert, f))
    spokes = list(v.link_edges)
    for p, q, f in rebuild:
        for j in range(k - 1):
            bm.faces.new((at(p, j), at(q, j), at(q, j + 1), at(p, j + 1)), f)
        bm.faces.new((v, at(p, k - 1), at(q, k - 1)), f)
    bmesh.ops.delete(bm, geom=[f for _p, _q, f in rebuild], context='FACES_ONLY')
    bmesh.ops.delete(bm, geom=[e for e in spokes if e.is_valid and not e.link_faces], context='EDGES')
    return list(ring.values())


def extrude_vertices(bm, verts, width=0.5, length=1.0, divisions=1, unit=1.0, **_unused):
    """Maya polyExtrudeVertex: the vertex becomes the tip of a cone, ``length`` (Maya units) along the mean normal
    of its faces; the base ring sits at ``width`` x each edge from it; ``divisions`` rings in between. The tip
    vertices end up selected. Returns the new / moved vertices."""
    bm.normal_update()
    verts = [v for v in verts if v.is_valid and v.link_faces]
    tips = {v: v.co + _unit_or(sum((f.normal for f in v.link_faces), Vector()), (0.0, 0.0, 1.0)) * (length * unit)
            for v in verts}
    base = _split_edges_at(bm, verts, width)
    k = max(1, int(divisions))
    out = []
    for v in verts:
        _cut_corner(bm, v)
    for v in verts:
        v.co = tips[v]
        out.append(v)
        out += base[v]
        if k > 1:
            out += _rings(bm, v, k)
    deselect_all(bm)
    for v in verts:
        v.select_set(True)
    bm.select_flush_mode()
    bm.normal_update()
    return out


def _build_edges(bm, params, unit):
    return extrude_edges(bm, [e for e in bm.edges if e.select], unit=unit, **params)


def _build_vertices(bm, params, unit):
    return extrude_vertices(bm, [v for v in bm.verts if v.select], unit=unit, **params)


EDGE_FIELDS = ("thickness", "local_translate_z", "offset", "divisions", "keep_faces_together")
EDGE = add_spec(Spec('EDGE', "polyExtrudeEdge", EDGE_FIELDS, {k: LABELS[k] for k in EDGE_FIELDS},
                     {"thickness": 0.0, "local_translate_z": 0.0, "offset": 0.0, "divisions": 1,
                      "keep_faces_together": True},
                     {"thickness": "NONE", "local_translate_z": "NONE", "offset": "NONE", "divisions": "INT",
                      "keep_faces_together": "BOOL"},
                     "local_translate_z", "extrude_edge_edit", _build_edges))
VERTEX = add_spec(Spec('VERTEX', "polyExtrudeVertex", ("width", "length", "divisions"),
                       {"width": "Width", "length": "Length", "divisions": "Divisions"},
                       {"width": 0.5, "length": 1.0, "divisions": 1},
                       {"width": "NONE", "length": "NONE", "divisions": "INT"},
                       "length", "extrude_vertex_edit", _build_vertices))
