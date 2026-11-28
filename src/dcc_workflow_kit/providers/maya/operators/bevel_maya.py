# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya polyBevel3 (Edit Mesh > Bevel, Ctrl+B) at once, as an editable history node like the kit's extrusion
(#16).

- Defaults: Fraction 0.5, Offset As Fraction on, Offset 0.2, Segments 1, Depth 1 (Chamfer on, Mitering auto).
- World Space (on, like Maya): Fraction, Offset and the profile work on the mesh as it stands in the world, so a cube
  scaled differently per axis gets the same width on every edge (``world_shape``); off: on the object-space mesh.
- On an object selection (Ctrl+B, Edit Mesh > Bevel) every edge of each selected mesh, still in object mode, and the
  In-View Editor shows the new node (operators/component.py).
- Fraction is relative to one length for the whole selection: the shortest "slide" edge (an edge touching an end of a
  beveled edge), halved when both of its ends are used (two shells of different size get the same width). The width
  applied is 0.9999 x that (both modes).
- The profile: the circle touching both faces at the profile's ends, in equal angle steps; Depth moves each point
  toward the chord between the ends (1 = the arc, 0 = on the chord, -1 = mirrored), also on concave edges
  (``arc_points``). Blender's superellipse (``profile = t^2``, t = 0.5 + Depth x (sqrt(1/2) - 1/2)) stays where
  the profile runs at a slant to its edge, where two bevelled edges meet, and for Segments 1.
- Three or more bevelled edges at a corner: one polygon through the profiles' ends (``flat_corners``).
- Chamfer off: Blender's square profile keeps the original surface; the step count is Segments rounded up to an
  even number, like Maya (2 segments give the 1-segment shape, 4 the 3-segment one), so the old corner is a point.
- Zero-length slide edges don't count, and what the bevel makes is merged within 0.0001 (Merge Vertices): the
  cap of a zero-length extrusion bevels into an inset (12/20/10, cap at 0.25), Fraction 1 merges (6/9/5).
- Faces bevel their edges; Maya leaves nothing selected afterwards. Vertex mode = Chamfer Vertex (Maya's Bevel
  on vertices chamfers them: 0.25 of each edge, no editable node here).
- Numbering (#149): kept vertices first in their old
  order, then the new vertices of each bevelled vertex, the bevelled vertices taken in the order the selected edges
  reach them (ascending Maya edge id, ends by ascending vertex id) and each one's new vertices in Maya's vertex ->
  edge order (``vertex_edges``; at a vertex that ends one bevelled edge, one new vertex on each of its other edges).
  Faces: old faces at no vertex that ends two or more bevelled edges, the bevel faces, old faces at such a vertex,
  corner and chain-end faces; in each group of old faces, a face whose vertex list starts at a chain end (and that
  doesn't hold that end's bevelled edge) comes last. Maya's edge ids = the mesh's edge index (``maya_edge_ids``)
  unless the caller passes them. A new vertex that Merge Vertices joins to an old one keeps the old one's number.
  Not renumbered: Segments > 1.
- Border edges (one face) are left out, like Maya.
- Hard edges: new edges, and edges of faces holding profile points between a profile's ends, are hard when their
  faces meet at more than the Smoothing angle (30 degrees); the rest keep their hardness (``set_hardness``).
- UVs: the new points in old faces get that face's UV map at their place, the strip's outer rows the UVs of the
  faces next to the edge (``set_uvs``).

Code: ``bevel_width`` (width, chain ends), ``bevel_corners`` (corner vertices), ``bevel_numbering`` (Maya's numbering),
``bevel_profiles`` (Segments > 1 profiles), ``bevel_hardness_uvs`` (hard edges, UVs). This module keeps the bevel driver
(``bevel_edges``), Merge Vertices (``merge_groups``), Chamfer Vertex and the polyBevel history kind (``BEVEL``); the
names used elsewhere are importable from here too.
"""

import math
from contextlib import contextmanager

import bmesh
from mathutils import Matrix

from . import extrude
# the split-out parts, also read through this module by other operators and the tests
from .bevel_width import (FIT, NEAR_LINE, ZERO, _corner, _corner_reach, _half_sin, corner_moves,  # noqa: F401
                          corners_of, end_moves, offset_end_moves, past_ends, profile, slide_limit, terminal_moves,
                          width)
from .bevel_corners import (CORNER_SPLIT, TRIPLE_SPLIT, corner_offsets, corner_pairs, corner_splits,  # noqa: F401
                            corner_triples, gap_merges)
from .bevel_numbering import _plan, _renumber, maya_edge_ids, vertex_edges  # noqa: F401
from .bevel_profiles import (flat_corners, hub_profile_frames, profile_interior, true_arcs)  # noqa: F401
from .bevel_hardness_uvs import face_uv_maps, input_hardness, is_hard, set_hardness, set_uvs  # noqa: F401

MERGE = 1e-4          # polyBevel3 Merge Vertices on, tolerance 0.0001 (default), in Maya lengths
SMOOTHING_ANGLE = 30.0  # Edit Mesh > Bevel: new edges whose faces meet at more than this many degrees are hard
CHAMFER = 25.0        # Chamfer Vertex: 0.25 of each edge (unit cube and 4 x 1 x 2 box)


def bevel_edges(bm, edges, fraction=0.5, offset_as_fraction=True, offset=0.2, segments=1, depth=1.0, unit=1.0,
                edge_ids=None, chamfer=True, smoothing_angle=SMOOTHING_ANGLE, **_unused):
    """polyBevel3 on ``edges`` (bmesh). Returns the vertices the bevel made (empty: nothing done). ``edge_ids``
    ({BMEdge: Maya edge id}) replaces ``maya_edge_ids`` for a mesh whose Maya edge numbering the caller knows.
    ``smoothing_angle`` (degrees) decides which new edges are hard (``set_hardness``)."""
    edges = [e for e in edges if e.is_valid and len(e.link_faces) == 2]      # like Maya: border edges stay
    ids = edge_ids if edge_ids is not None else maya_edge_ids(bm)
    pairs2 = corner_pairs(edges, ids) if chamfer and int(segments) == 1 and offset_as_fraction else {}
    triples = corner_triples(edges, ids) if chamfer and int(segments) == 1 and offset_as_fraction else {}
    splits = corner_splits(edges, ids) if chamfer and int(segments) == 1 and offset_as_fraction else {}
    w = width(edges, fraction, offset_as_fraction, offset, unit, pairs2, triples, splits)
    if not edges or w <= 0.0:
        return []
    hard_in = input_hardness(bm, edges)
    uv_maps = face_uv_maps(bm, {f for e in edges for v in e.verts for f in v.link_faces})
    uv_maps["beside"] = {f.index for e in edges for f in e.link_faces}
    # Chamfer off: the square profile keeps the original surface (#368); like Maya the step count is even, so the
    # old corner is one of its points
    bseg = max(1, int(segments))
    if not chamfer:
        bseg += bseg % 2
    plan = _plan(bm, edges, ids) if ids is not None and int(segments) == 1 and chamfer else None
    bm.edges.index_update()
    picked = [e.index for e in edges]
    # face source indices ride along as custom data (bevel copies them onto what it makes); added before elements are
    # collected again, since adding a layer can invalidate element references
    tlay = bm.verts.layers.int.new(".allset_bevel_made")
    ilay = bm.verts.layers.int.new(".allset_bevel_inner")       # profile points between a profile's two ends
    mlay = bm.faces.layers.int.new(".allset_bevel_new")         # faces the bevel made (strips, corners)
    flay = bm.faces.layers.int.new(".allset_bevel_src")
    # Segments > 1: an edge layer finds each edge's strip afterwards (an edge layer invalidates edge references, so
    # the Maya edge ids are carried over by index)
    elay = None
    if bseg > 1:
        by_index = {e.index: i for e, i in ids.items()} if ids is not None else None
        elay = bm.edges.layers.int.new(".allset_bevel_edge")
        bm.edges.ensure_lookup_table()
        if by_index is not None:
            ids = {bm.edges[k]: i for k, i in by_index.items()}
    bm.verts.index_update()
    old_verts = {v: v.index for v in bm.verts}
    for f in bm.faces:
        f[flay] = f.index + 1
    bm.edges.ensure_lookup_table()
    edges = [bm.edges[i] for i in picked]
    if elay is not None:
        for i, e in enumerate(edges):
            e[elay] = i + 1      # bevel copies it onto the two outer edges of the edge's strip
    verts = {v for e in edges for v in e.verts}
    # old positions of the bevelled vertices with the number of bevelled edges there
    hubs = [(v.co.copy(), sum(1 for e in v.link_edges if e in edges)) for v in verts]
    hub_frames = hub_profile_frames(edges, verts)
    overs = [] if offset_as_fraction else past_ends(edges, w, spokes=True)
    # Offset As Fraction only: with an absolute Offset Maya leaves that vertex at W along the edge, as Blender does
    pairs2 = corner_pairs(edges, ids) if pairs2 else {}      # the elements were collected again
    triples = corner_triples(edges, ids) if triples else {}
    splits = corner_splits(edges, ids) if splits else {}
    moves = ([m + (None,) for m in terminal_moves(edges, pairs2)[0]]
             if chamfer and int(segments) == 1 and offset_as_fraction else [])
    moves += (offset_end_moves(edges)
              if chamfer and int(segments) == 1 and not offset_as_fraction else [])
    # an end whose slide edge runs near the bevelled edge's line: Maya's offsets there, in both modes
    moves += end_moves(edges, pairs2)[0] if chamfer and int(segments) == 1 else []
    offsets = corner_offsets(edges, ids) if chamfer and int(segments) == 1 and not offset_as_fraction else {}
    moves += [m + (None,) for c in offsets.values() for m in c["ends"]]
    pair_moves = [(c["origin"], c["ray"], c["k_ray"], c["u3"], c["k_u3"])
                  for c in list(pairs2.values()) + list(offsets.values())]
    corners = corner_moves(edges) if chamfer and int(segments) == 1 else []
    merges = [(p, {f[flay] for f in fs}) for p, fs in gap_merges(edges, w)]   # gap faces by their source id
    ret = bmesh.ops.bevel(bm, geom=list(edges) + list(verts), offset=w, offset_type='OFFSET',
                          segments=bseg, profile=profile(depth) if chamfer else 1.0, affect='EDGES',
                          clamp_overlap=False, loop_slide=True)
    made = [v for v in ret["verts"] if v.is_valid]
    for f in ret["faces"]:
        if f.is_valid:
            f[mlay] = 1
    # Blender puts a chain end's new vertex on a terminal edge at W along it; Maya (Fraction) at W x k. The
    # new vertex is the one on that edge's line next to its far vertex (Blender doesn't put it on the edge when the
    # edge runs almost along the bevelled one), else the nearest made vertex on the line
    made_set = set(made)
    for origin, unit_dir, k, far in moves:
        best = None
        if far is not None and far.is_valid and far not in verts:
            for x in (e.other_vert(far) for e in far.link_edges):
                if x in made_set:
                    off = x.co - origin
                    gap = (off - unit_dir * off.dot(unit_dir)).length
                    if best is None or gap < best[0]:
                        best = (gap, x)
        if best is None:
            for v in made:
                off = v.co - origin
                s = off.dot(unit_dir)
                if s > 1e-7 and (off - unit_dir * s).length < 1e-5 and (best is None or s < best[0]):
                    best = (s, v)
        if best is not None:
            best[1].co = origin + unit_dir * (w * k)
    for origin, ray, k in corners:
        target = origin + ray * (w * k)
        best = min(made, key=lambda x: (x.co - target).length_squared, default=None)
        if best is not None and (best.co - origin).length < 1e-6:
            best.co = target
    for origin, ray, k_ray, u3, k_u3 in pair_moves:
        # the new corner = the made vertex nearest the bisector; the new vertex on u3 = the one nearest that line
        for line, k in ((ray, k_ray), (u3, k_u3)):
            def gap(x, line=line, k=k):
                off = x.co - origin
                near = 0.0 < off.dot(line) < 3.0 * w * max(1.0, k)
                return (off - line * off.dot(line)).length if near else math.inf
            best = min(made, key=gap, default=None)
            if best is not None and gap(best) < 0.5 * w:
                best.co = origin + line * (w * k)
    for c in triples.values():
        # each face's new corner = the made vertex nearest its bisector
        origin = c["origin"]
        for ray, k_ray, _k in c["faces"].values():
            def gap(x, ray=ray, origin=origin, k_ray=k_ray):
                off = x.co - origin
                near = 0.0 < off.dot(ray) < 3.0 * w * max(1.0, k_ray)
                return (off - ray * off.dot(ray)).length if near else math.inf
            best = min(made, key=gap, default=None)
            if best is not None and gap(best) < 0.5 * w:
                best.co = origin + ray * (w * k_ray)
    for c in splits.values():
        # each face's new corner = the made vertex nearest that face's bisector (where Blender puts it)
        origin = c["origin"]
        for offset, _feet, angle, ray in c["faces"].values():
            k_ray = 1.0 / math.sin(angle / 2.0)
            def gap(x, ray=ray, origin=origin, k_ray=k_ray):
                off = x.co - origin
                near = 0.0 < off.dot(ray) < 3.0 * w * k_ray
                return (off - ray * off.dot(ray)).length if near else math.inf
            best = min(made, key=gap, default=None)
            if best is not None and gap(best) < 0.5 * w:
                best.co = origin + offset * w
    for target, sources in merges:
        # the made vertex that every face of the gap holds
        for x in made:
            if x.is_valid and sources <= {f[flay] for f in x.link_faces}:
                x.co = target
                break
    for far, origin, unit_dir, slide in overs:
        # the made vertex on that edge's line, at or near its far vertex
        def off_line(x, origin=origin, unit_dir=unit_dir):
            o = x.co - origin
            t = o.dot(unit_dir)
            return (o - unit_dir * t).length if t > 1e-6 else math.inf
        hit = min(made, key=lambda x: (off_line(x), (x.co - far).length_squared), default=None)
        if hit is not None and off_line(hit) < 1e-5:
            hit.co = origin + unit_dir * slide
    if chamfer and bseg > 1:
        true_arcs(bm, elay, {f for f in ret["faces"] if f.is_valid}, bseg, depth, hubs, hub_frames, w)
    if bseg > 1:
        for v in profile_interior(bm, elay, {f for f in ret["faces"] if f.is_valid}, bseg):
            v[ilay] = 1
    if chamfer and bseg > 1:
        made = flat_corners(bm, made, hubs)
    near = set(made)
    for v in made:
        near.update(e.other_vert(v) for e in v.link_edges)
    # Maya merges what the bevel made onto coincident vertices (a zero-length extrusion's sides, Fraction 1): every
    # group of vertices linked by gaps within the tolerance becomes one vertex at the group's mean (Fraction 1:
    # 0.49995 between 0.5 and 0.4999; four inner corners 0.0001 apart meet in the middle). The tolerance is a Maya
    # length: in a centimetre scene 0.0001 cm, not 0.0001 m (#321: small bevels lost their edges)
    made_set = set(made)
    pairs = merge_groups(list(near), made_set, MERGE * unit * 1.001)
    if pairs:
        bmesh.ops.weld_verts(bm, targetmap=pairs)
    for v in near:
        if v.is_valid:
            v[tlay] = 1
    if plan is not None:
        _renumber(bm, plan, old_verts, flay, {f for f in ret["faces"] if f.is_valid}, {v for v in made if v.is_valid},
                  merged=bool(pairs))
    bm.verts.index_update()
    set_hardness(bm, hard_in, {v for v in bm.verts if v[ilay]}, {v for v in bm.verts if v[tlay]}, smoothing_angle)
    set_uvs(bm, uv_maps, flay, mlay, ilay, tlay)
    tracked = [v.index for v in bm.verts if v[tlay]]
    bm.verts.layers.int.remove(tlay)
    bm.verts.layers.int.remove(ilay)
    bm.faces.layers.int.remove(flay)
    bm.faces.layers.int.remove(mlay)
    if elay is not None:
        bm.edges.layers.int.remove(elay)
    bm.verts.ensure_lookup_table()
    extrude.deselect_all(bm)
    bm.select_flush_mode()
    bm.normal_update()
    return [bm.verts[i] for i in tracked]


def merge_groups(verts, made_set, dist):
    """{vertex: target} for weld_verts: vertices linked by gaps <= ``dist`` (through each other) form one group,
    moved to the group's mean; the target is an old vertex when the group has one (it keeps its number)."""
    verts = [v for v in verts if v.is_valid]
    parent = {v: v for v in verts}

    def root(v):
        while parent[v] is not v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v

    for i, a in enumerate(verts):
        for b in verts[i + 1:]:
            if (a.co - b.co).length <= dist:
                ra, rb = root(a), root(b)
                if ra is not rb:
                    parent[rb] = ra
    groups = {}
    for v in verts:
        groups.setdefault(root(v), []).append(v)
    out = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        mean = sum((v.co for v in group), group[0].co * 0.0) / len(group)
        target = next((v for v in group if v not in made_set), group[0])
        for v in group:
            v.co = mean
            if v is not target:
                out[v] = target
    return out


def chamfer_vertices(bm, verts):
    """Maya Chamfer Vertex (Ctrl+B in vertex mode): a face where each vertex was, 0.25 of each edge in."""
    verts = [v for v in verts if v.is_valid]
    if not verts:
        return []
    ret = bmesh.ops.bevel(bm, geom=verts, offset=CHAMFER, offset_type='PERCENT', segments=1, profile=0.5,
                          affect='VERTICES', clamp_overlap=False)
    extrude.deselect_all(bm)      # Maya selects only the polyChamfer node
    bm.select_flush_mode()
    bm.normal_update()
    return list(ret["verts"])


def world_scale(ob):
    """Object scale for World Space (Maya: the Offset in world units): the mean axis scale of the object."""
    if ob is None:
        return 1.0
    m = ob.matrix_world.to_3x3()
    s = abs(m.determinant()) ** (1.0 / 3.0)
    return s if s > ZERO else 1.0


def shape_matrix(ob):
    """The object's 3 x 3 transform when it changes shapes (a scale that differs per axis, or a shear), else None
    (no object, a flat one, or only rotation / mirroring / one scale for all axes). A mirroring transform gets one more
    mirror in the object's X, so the faces keep their winding; lengths and angles stay the world ones."""
    if ob is None:
        return None
    m = ob.matrix_world.to_3x3()
    det = m.determinant()
    if abs(det) <= ZERO:
        return None
    g = m.transposed() @ m
    mean = (g[0][0] + g[1][1] + g[2][2]) / 3.0       # mathutils matrices are single precision: 1e-6
    if all(abs(g[i][j] - (mean if i == j else 0.0)) <= 1e-6 * mean for i in range(3) for j in range(3)):
        return None
    if det < 0.0:
        m = m @ Matrix.Diagonal((-1.0, 1.0, 1.0))
    return m


@contextmanager
def world_shape(bm, ob):
    """World Space on a mesh whose object scale differs per axis: ``bm`` in its world shape while the block runs
    (Maya takes Fraction, Offset and the profile from the world shape), back in object space afterwards. Yields
    True when it changed the mesh."""
    m = shape_matrix(ob)
    if m is None:
        yield False
        return
    bm.transform(m.to_4x4())
    try:
        yield True
    finally:
        bm.transform(m.inverted().to_4x4())
        bm.normal_update()


def _build(bm, params, unit, ob=None):
    params = dict(params)
    world = params.pop("world_space", False)
    with world_shape(bm, ob if world else None) as shaped:
        if world and not shaped and not params.get("offset_as_fraction", True):
            unit = unit / world_scale(ob)
        made = bevel_edges(bm, [e for e in bm.edges if e.select], unit=unit, **params)
    if made and getattr(ob, "type", None) == 'MESH' and _soft(bm):
        from . import display
        display.ensure_maya_normals(ob)      # Maya's smooth normals on the soft edges the bevel made
    return made


def _soft(bm):
    return any(e.smooth and len(e.link_faces) == 2 and all(f.smooth for f in e.link_faces) for e in bm.edges)


BEVEL = extrude.add_spec(extrude.Spec(
    'BEVEL', "polyBevel", ("fraction", "offset_as_fraction", "offset", "segments", "depth", "chamfer"),
    {"fraction": "Fraction", "offset_as_fraction": "Offset As Fraction", "offset": "Offset", "segments": "Segments",
     "depth": "Depth", "chamfer": "Chamfer"},
    {"fraction": 0.5, "offset_as_fraction": True, "offset": 0.2, "segments": 1, "depth": 1.0, "chamfer": True,
     "world_space": True, "smoothing_angle": SMOOTHING_ANGLE},
    {"fraction": "NONE", "offset_as_fraction": "BOOL", "offset": "NONE", "segments": "INT", "depth": "NONE",
     "chamfer": "BOOL"},
    None, "bevel_edit", _build, node_type="polyBevel3", hidden=("world_space", "smoothing_angle"), with_object=True))
