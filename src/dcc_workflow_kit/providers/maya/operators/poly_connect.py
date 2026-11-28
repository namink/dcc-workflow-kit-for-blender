# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Edit Mesh / Mesh Tools > Connect: per face the selected vertices and the midpoints of the selected edges are
joined as a cycle (border neighbours and crossing chords skipped); selected faces are cut through their shared edges.
Entry points ``connect`` (``allset.connect``) and ``connect_items`` (segments / slide / pinch, edge loops through a lone
edge's ring), which the interactive Connect Tool (connect_tool.py) also runs. Imported through poly_maya.py.
"""

import bmesh
import bpy

CONNECT_WARNING = "Can't perform polyConnectComponents1 on selection"   # Maya's warning


# --- Connect -----------------------------------------------------------------------------------
# Maya Connect. Per face the points to join
# are its selected vertices and the midpoints of its selected edges; they are joined as a cycle in index order, a
# chord is skipped when its ends are neighbours on the face border or it crosses a chord already made. A selected
# edge whose face gets no chord is left alone (one edge -> nothing). Faces: the edges shared by two selected faces are
# cut at their midpoints; a strip end (one shared edge) whose neighbour has two or more continues to its opposite
# edge (three faces in a row -> a line through the row; two faces -> only the shared edge's midpoint).

def _border_pos(face, el):
    """Position of a vertex (2i) or an edge midpoint (2i + 1) along ``face``'s loop."""
    for i, loop in enumerate(face.loops):
        if loop.vert is el:
            return 2 * i
        if loop.edge is el:
            return 2 * i + 1
    return None


def _chords(face, points):
    """Pairs of ``points`` (BMVert / BMEdge of ``face``) to join, Maya's cycle with the skips above."""
    n2 = 2 * len(face.loops)
    pts = sorted(points, key=lambda p: (isinstance(p, bmesh.types.BMEdge), p.index))
    if len(pts) < 2:
        return []
    pairs = [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts) if len(pts) > 2 else 1)]
    made = []
    for a, b in pairs:
        pa, pb = _border_pos(face, a), _border_pos(face, b)
        d = (pb - pa) % n2
        if d in (1, n2 - 1) or (pa % 2 == 0 and pb % 2 == 0 and d in (2, n2 - 2)):
            continue           # neighbours on the border: Maya adds nothing
        lo, hi = sorted((pa, pb))
        if any((lo < c < hi) != (lo < d2 < hi) and lo not in (c, d2) and hi not in (c, d2) for c, d2 in made):
            continue           # would cross a chord already made
        made.append((lo, hi))
        yield a, b


def _opposite_edge(face, edge):
    loops = list(face.loops)
    i = next(k for k, lp in enumerate(loops) if lp.edge is edge)
    return loops[(i + len(loops) // 2) % len(loops)].edge


def _loop_neighbour(v, e):
    """The vertex before ``v`` along the edge loop through edge ``e`` (the edge at ``v`` sharing no face with ``e``);
    None at poles / borders."""
    faces = set(e.link_faces)
    cand = [x for x in v.link_edges if x is not e and not faces & set(x.link_faces)]
    return cand[0].other_vert(v) if len(cand) == 1 else None


def _flow_point(a, b, t, adjust, pa=None, pb=None):
    """A point at ``t`` from ``a`` to ``b`` (BMVerts); with ``adjust`` (Maya Insert with edge flow) it follows a cubic
    through the loop neighbours: Hermite tangents 0.7 x (next - previous), the deviation from the straight edge times
    Adjust Edge Flow, like Maya."""
    p1, p2 = a.co.copy(), b.co.copy()
    lin = p1.lerp(p2, t)
    if not adjust:
        return lin
    p0 = pa.co if pa is not None else 2 * p1 - p2
    p3 = pb.co if pb is not None else 2 * p2 - p1
    m1, m2 = 0.7 * (p2 - p0), 0.7 * (p3 - p1)
    t2, t3 = t * t, t * t * t
    h = (2 * t3 - 3 * t2 + 1) * p1 + (t3 - 2 * t2 + t) * m1 + (-2 * t3 + 3 * t2) * p2 + (t3 - t2) * m2
    return lin + (h - lin) * adjust


def _orient(jobs, split):
    """A start vertex per split edge so that the chords of a face pair points from the same side (Connect tool
    Slide / Segments): in face order, the end of the first edge faces the start of the second."""
    start, todo = {}, list(jobs)
    pending = True
    while pending:
        pending = False
        for f, a, b in todo:
            if not (isinstance(a, bmesh.types.BMEdge) and isinstance(b, bmesh.types.BMEdge)):
                continue
            la = next(lp for lp in f.loops if lp.edge is a)
            lb = next(lp for lp in f.loops if lp.edge is b)
            pairs = ((la.link_loop_next.vert, lb.vert), (la.vert, lb.link_loop_next.vert))
            if a in start and b not in start:
                start[b] = pairs[0][1] if start[a] is pairs[0][0] else pairs[1][1]
                pending = True
            elif b in start and a not in start:
                start[a] = pairs[0][0] if start[b] is pairs[0][1] else pairs[1][0]
                pending = True
            elif a not in start and b not in start:
                start[a] = a.verts[0]
                start[b] = pairs[0][1] if start[a] is pairs[0][0] else pairs[1][1]
                pending = True
    for e in split:
        start.setdefault(e, e.verts[0])
    return start


def connect(bm, mode, edge_flow=0.0, segments=1, slide=0.5, pinch=0.0):
    """Maya Connect on the selection (``mode`` 'VERT' / 'EDGE' / 'FACE'). Returns the number of new edges (0 = nothing
    to connect); the new edges end up selected. Options: ``edge_flow`` = Adjust Edge Flow with Insert with
    edge flow on (0 = off); Connect tool ``segments`` / ``slide`` / ``pinch`` (selected edges: n points per edge,
    centred on Slide, pulled together by Pinch)."""
    if mode == 'FACE':
        sel = {f for f in bm.faces if f.select}
        inner = {e for f in sel for e in f.edges if len(e.link_faces) == 2 and all(x in sel for x in e.link_faces)}
        count = {f: sum(e in inner for e in f.edges) for f in sel}
        per_face = {}      # face -> points (BMEdge)
        for f in sel:
            pts = [e for e in f.edges if e in inner]
            if len(pts) == 1:
                other = next(x for x in pts[0].link_faces if x is not f)
                if count[other] >= 2:
                    pts.append(_opposite_edge(f, pts[0]))
            per_face[f] = pts
        jobs = [(f, a, b) for f, pts in per_face.items() for a, b in _chords(f, pts)]
        split = set(inner) | {p for _f, a, b in jobs for p in (a, b)}    # inner (and opposite) edges, midpoints
        out = _connect(bm, jobs, split, edge_flow, 1, 0.5, 0.0)
    else:
        items = [v for v in bm.verts if v.select] if mode == 'VERT' else [e for e in bm.edges if e.select]
        out = connect_items(bm, items, edge_flow, segments if mode == 'EDGE' else 1, slide, pinch, select=False)
    if out["made"]:
        _select_new(bm, out["edges"])
    return out["made"]


def connect_items(bm, items, edge_flow=0.0, segments=1, slide=0.5, pinch=0.0, ring_lonely=False, select=True):
    """Connect ``items`` (BMVerts / BMEdges) across the faces they share, like Maya's Connect Tool: two points of
    one face get a chord, an edge is cut at ``segments`` points centred on ``slide`` and pulled together by
    ``pinch`` (%). With ``ring_lonely`` an edge that shares no chord with another item gets edge loops through its
    ring instead (``segments`` loops), as the tool does with one edge alone. Returns ``{"made": number of new
    edges, "edges": the chords and loops, "mids": {cut edge: its new vertices in chord order}}``; with ``select``
    the chords and loops end up selected."""
    per_face = {}      # face -> points (BMVert / BMEdge)
    for it in items:
        for f in it.link_faces:
            pts = per_face.setdefault(f, [])
            if it not in pts:
                pts.append(it)
    jobs = [(f, a, b) for f, pts in per_face.items() for a, b in _chords(f, pts)]
    split = {p for _f, a, b in jobs for p in (a, b) if isinstance(p, bmesh.types.BMEdge)}
    lonely = [e for e in items if ring_lonely and isinstance(e, bmesh.types.BMEdge) and e not in split]
    out = _connect(bm, jobs, split, edge_flow, segments, slide, pinch)
    if lonely:
        before = len(bm.edges)
        chords = _edge_keys(bm, out["edges"])            # the loop operators invalidate the wrappers
        loops = _ring_loops(bm, lonely, _fractions(segments, slide, pinch))
        out["edges"] = _edges_from_keys(bm, chords) + loops
        out["made"] += len(bm.edges) - before
    if select and out["made"]:
        _select_new(bm, out["edges"])
    return out


def _fractions(segments, slide, pinch=0.0):
    """Where ``segments`` points cut an edge: evenly around ``slide``, their spread scaled by Pinch (100 = all at
    Slide, -100 = twice as far apart), kept inside the edge and in order."""
    n = max(1, int(segments))
    spread = max(0.02, 1.0 - pinch / 100.0)
    out = [min(0.98, max(0.02, slide + ((k + 1) / (n + 1) - 0.5) * spread)) for k in range(n)]
    gap = min(1e-3, 0.02 / n)
    for k in range(1, n):
        out[k] = max(out[k], out[k - 1] + gap)
    return out


def _select_new(bm, edges):
    for el in (*bm.verts, *bm.edges, *bm.faces):
        el.select = False
    for e in edges:
        if e.is_valid:
            e.select = True
    bm.select_flush_mode()


def _edge_keys(bm, edges):
    """Edges as (vertex index, vertex index) pairs: vertex indexes survive the bmesh operators that invalidate the
    Python wrappers (vertices are only ever added)."""
    bm.verts.index_update()
    return [(e.verts[0].index, e.verts[1].index) for e in edges if e.is_valid]


def _edges_from_keys(bm, keys):
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    out = []
    for ia, ib in keys:
        if ia < len(bm.verts) and ib < len(bm.verts):
            va = bm.verts[ia]
            e = next((x for x in va.link_edges if x.other_vert(va).index == ib), None)
            if e is not None:
                out.append(e)
    return out


def _ring_loops(bm, edges, fracs):
    """Edge loops through the rings of ``edges``, one at each of ``fracs`` (from each edge's first vertex). Returns
    the new edges. Works by vertex index: ``bmesh.ops.subdivide_edges`` invalidates the vertex wrappers."""
    from .mesh_tools import insert_loop
    made = []           # (vertex index, vertex index) per new edge
    for si, fi in _edge_keys(bm, edges):
        pieces = _edges_from_keys(bm, [(si, fi)])
        if not pieces:
            continue    # cut by an earlier loop
        bm.verts.ensure_lookup_table()
        start_co, far_co = bm.verts[si].co.copy(), bm.verts[fi].co.copy()
        line = far_co - start_co
        if line.length_squared < 1e-20:
            continue
        cur, last_i, done = pieces[0], si, 0.0
        for t in fracs:
            tt = (t - done) / (1.0 - done)
            if cur.verts[0].index != last_i:
                tt = 1.0 - tt
            new = insert_loop(bm, cur, tt)
            if not new:
                break
            made.extend(_edge_keys(bm, new))
            done = t
            bm.verts.ensure_lookup_table()
            far = bm.verts[fi]
            best = None             # the piece left between the new vertex and the far end
            for x in far.link_edges:
                o = x.other_vert(far)
                u = (o.co - start_co).dot(line) / line.length_squared
                off = (o.co - start_co - line * u).length_squared
                if 0.0 < u < 1.0 and off < 1e-10 * line.length_squared and (best is None or u > best[0]):
                    best = (u, x, o.index)
            if best is None:
                break
            cur, last_i = best[1], best[2]
    return _edges_from_keys(bm, made)


def _connect(bm, jobs, split, edge_flow, segments, slide, pinch):
    """Cut the ``split`` edges and make the chords of ``jobs`` (face, point a, point b)."""
    before = len(bm.edges)
    fracs = _fractions(segments, slide, pinch)
    n_pts = len(fracs)
    start = _orient(jobs, split)
    sides = []          # per job: the vertices of a and b on the same side of the face (before any split)
    for f, a, b in jobs:
        if isinstance(a, bmesh.types.BMEdge) and isinstance(b, bmesh.types.BMEdge):
            la = next(lp for lp in f.loops if lp.edge is a)
            lb = next(lp for lp in f.loops if lp.edge is b)
            near_a, near_b = la.link_loop_next.vert, lb.vert
            if start[a] is not near_a:
                near_a, near_b = la.vert, lb.link_loop_next.vert
            sides.append((near_a, near_b))
        else:
            sides.append(None)
    mids = {}
    for e in sorted(split, key=lambda e: e.index):
        a = start[e]
        b = e.other_vert(a)
        pa, pb = _loop_neighbour(a, e), _loop_neighbour(b, e)
        cos = [_flow_point(a, b, t, edge_flow, pa, pb) for t in fracs]
        pts, cur, done = [], e, 0.0
        for t, co in zip(fracs, cos):
            _ne, nv = bmesh.utils.edge_split(cur, a if not pts else pts[-1], (t - done) / (1.0 - done))
            nv.co = co
            pts.append(nv)
            cur = next(x for x in nv.link_edges if x.other_vert(nv) is b)
            done = t
        mids[e] = pts           # from the oriented start to the end
    new_edges = []
    mid = n_pts // 2
    for (f, a, b), side in zip(jobs, sides):
        if side is not None:
            pa_, pb_ = mids[a], mids[b]
            pairs = list(zip(pa_ if side[0] is start[a] else pa_[::-1], pb_ if side[1] is start[b] else pb_[::-1]))
        else:
            pairs = [(mids[a][mid] if isinstance(a, bmesh.types.BMEdge) else a,
                      mids[b][mid] if isinstance(b, bmesh.types.BMEdge) else b)]
        for va, vb in pairs:
            faces = [x for x in set(va.link_faces) & set(vb.link_faces)
                     if not any(vb in e.verts for e in va.link_edges if e in x.edges)]
            if not faces:
                continue
            _nf, loop = bmesh.utils.face_split(faces[0], va, vb)
            if loop is not None:
                new_edges.append(loop.edge)
    return {"made": len(bm.edges) - before, "edges": new_edges, "mids": mids}


class ALLSET_OT_connect(bpy.types.Operator):
    """Connect the selected edges through their midpoints, the selected vertices across their faces, or the
    selected faces through their middles (Maya Edit Mesh / Mesh Tools > Connect)"""
    bl_idname = "allset.connect"
    bl_label = "Connect"
    bl_options = {'REGISTER', 'UNDO'}

    # Maya Connect Components Options  and the Mesh Tools > Connect
    # tool's Slide / Segments; default values
    insert_with_edge_flow: bpy.props.BoolProperty(name="Insert with edge flow", default=False, options={'SKIP_SAVE'})
    adjust_edge_flow: bpy.props.FloatProperty(name="Adjust Edge Flow", default=1.0, soft_min=-1.0, soft_max=2.0,
                                              options={'SKIP_SAVE'})
    segments: bpy.props.IntProperty(name="Segments", default=1, min=1, soft_max=10, max=100, options={'SKIP_SAVE'})
    slide: bpy.props.FloatProperty(name="Slide", default=0.5, min=0.0, max=1.0, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        v, e, f = context.tool_settings.mesh_select_mode
        mode = 'VERT' if v else ('EDGE' if e else 'FACE')
        made = 0
        for ob in context.objects_in_mode:
            bm = bmesh.from_edit_mesh(ob.data)
            made += connect(bm, mode, self.adjust_edge_flow if self.insert_with_edge_flow else 0.0,
                            self.segments, self.slide)
            bmesh.update_edit_mesh(ob.data)
        if not made:
            self.report({'WARNING'}, CONNECT_WARNING)
            return {'CANCELLED'}
        return {'FINISHED'}
