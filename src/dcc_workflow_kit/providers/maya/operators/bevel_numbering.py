# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit Mesh > Bevel: Maya's numbering around a bevel. Maya edge ids (``maya_edge_ids``), Maya's vertex -> edge order
(``vertex_edges``), the planned order of kept and new vertices and faces (``_plan``) and the sort of the bevelled mesh
into that order (``_renumber``). Used by the bevel driver in ``bevel_maya`` and by ``bevel_corners``.
"""


# --- Maya numbering -----------------------------------------------------------------------------------

def maya_edge_ids(bm):
    """{BMEdge: Maya edge id}: the mesh's edge index (kit design). It is Maya's id wherever
    the kit made the edges: kit polyCube / polyCylinder are built with Maya's edge order (prim_shapes ``edges``) and
    kit extrusions sort their result into polyExtrudeFacet's order (extrude_face.renumber),
    Maya numbers a mesh made from a face list in face-corner order; bmesh's
    ``faces.new`` doesn't (it makes a face's closing edge first), so such a mesh needs its edges made in that order
    first. Elsewhere (other primitives, Blender's own tools, imports) Maya's ids are not known."""
    bm.edges.index_update()
    return {e: e.index for e in bm.edges}


def vertex_edges(v, ids):
    """Maya's vertex -> edge order (MItMeshVertex.getConnectedEdges): start at the edge with the highest Maya id (on
    a border: the border edge the face winding leaves v along), then each next edge = the edge coming into v in the
    face the current edge leaves v in. 477 / 477 vertices of 24 meshes match Maya.
    None for a vertex that isn't a single fan of faces."""
    nxt = {}
    for loop in v.link_loops:
        if loop.edge in nxt:
            return None
        nxt[loop.edge] = loop.link_loop_prev.edge
    edges = list(v.link_edges)
    if not edges:
        return None
    heads = [e for e in nxt if e not in set(nxt.values())]
    if len(heads) > 1:
        return None
    cur = heads[0] if heads else max(edges, key=lambda e: ids[e])
    out = [cur]
    while len(out) < len(edges):
        cur = nxt.get(cur)
        if cur is None or cur in out:
            return None
        out.append(cur)
    return out


def _face_between(v, e_out, e_in):
    for loop in v.link_loops:
        if loop.edge is e_out and loop.link_loop_prev.edge is e_in:
            return loop.face
    return None


def _slots(v, sel, ids):
    """The new vertices of bevelled vertex ``v`` in Maya's order, each as the set of old face indices it lies in;
    None where the order is unknown (two or more bevelled edges at a border vertex, one bevelled edge at a two-edge
    vertex)."""
    E = vertex_edges(v, ids)
    if E is None or any(e.is_wire for e in E):
        return None
    n = len(E)
    marks = [k for k in range(n) if E[k] in sel]
    if len(marks) == 1:
        if n < 3 or E[marks[0]].is_boundary:
            return None
        # one bevelled edge: a new vertex on every other edge at v (the two next to it, and at a chain end with more
        # edges the terminal ones too; on a border vertex its border edges), in E(v)'s list order
        return [frozenset(f.index for f in E[j].link_faces) for j in range(n) if j != marks[0]]
    if any(e.is_boundary for e in E):
        return None
    between = [_face_between(v, E[k], E[(k + 1) % n]) for k in range(n)]
    if None in between:
        return None
    out = []
    for i, k in enumerate(marks):      # one new vertex per wedge, the wedge after each bevelled edge in E(v)'s order
        span = (marks[(i + 1) % len(marks)] - k) % n or n
        out.append(frozenset(between[(k + j) % n].index for j in range(span)))
    return out


def _end_faces(v, sel):
    """At a vertex that ends one bevelled edge: the old faces that go after the other untouched faces, like Maya —
    those whose vertex list starts at ``v`` and that don't hold v's bevelled edge."""
    return [f for f in v.link_faces if f.loops[0].vert is v and not any(x in sel for x in f.edges if v in x.verts)]


def _plan(bm, edges, ids):
    """Maya's order of what the bevel will leave, as keys the result is matched to (None: unknown here)."""
    sel = set(edges)
    bm.verts.index_update()
    bm.faces.index_update()
    order, seen = [], set()
    for e in sorted(edges, key=lambda e: ids[e]):
        for v in sorted(e.verts, key=lambda v: v.index):
            if v not in seen:
                seen.add(v)
                order.append(v)
    slots, edge_faces, met, corners, moved = [], [], set(), [], []
    for v in order:
        s = _slots(v, sel, ids)
        if s is None or len(set(s)) != len(s):
            return None
        slots += [(v.index, key) for key in s]
        for e in vertex_edges(v, ids):      # a bevel face comes when its edge is first met in this walk
            if e in sel and e not in met:
                met.add(e)
                edge_faces.append(frozenset(x.index for x in e.verts))
        deg = sum(1 for e in v.link_edges if e in sel)
        if deg >= 3 or deg == 1:
            corners.append(v.index)
        if deg == 1:
            moved += sorted(f.index for f in _end_faces(v, sel) if f.index not in moved)
    # old faces at a vertex that ends two or more bevelled edges (along a bevelled edge, or only touching one: a
    # plane's faces round a loop)
    along = sorted({f.index for v in order if sum(1 for e in v.link_edges if e in sel) >= 2 for f in v.link_faces})
    return {"kept": [v.index for v in bm.verts if v not in seen], "slots": slots, "edge_faces": edge_faces,
            "corners": corners, "along": along, "moved": moved, "faces": len(bm.faces),
            "co": {v.index: v.co.copy() for v in order}}


def _renumber(bm, plan, old_verts, flay, made, new_verts, merged=False):
    """Sort the bevelled mesh into Maya's order. Vertices only when every one is matched; faces only when every face
    is (else they keep Blender's order). A kept vertex is the same BMVert as before (``old_verts``: BMVert -> old
    index); a new vertex is matched by the old faces it lies in, and among bevelled vertices with a wedge of the same
    faces by the nearest old position (bevel copies a neighbour's custom data onto new vertices, and sometimes onto
    vertices it doesn't touch, so vertex custom data carries no reliable source index)."""
    kept = {i: n for n, i in enumerate(plan["kept"])}
    by_key = {}
    for n, (v, key) in enumerate(plan["slots"]):
        by_key.setdefault(key, []).append((v, len(kept) + n))
    rank, owner = {}, {}
    for v in bm.verts:
        if v not in new_verts:
            src = old_verts.get(v)
            r = kept.get(src)
        else:
            cands = by_key.get(frozenset(f[flay] - 1 for f in v.link_faces if f not in made), ())
            if not cands:
                return
            src, r = min(cands, key=lambda c: (plan["co"][c[0]] - v.co).length_squared)
        if r is None:
            return
        rank[v] = r
        owner[v] = src
    if merged:      # Merge Vertices removed some new vertices: the rest close up in the same order
        if len(set(rank.values())) != len(rank):
            return
        rank = {v: n for n, v in enumerate(sorted(rank, key=lambda v: rank[v]))}
    if sorted(rank.values()) != list(range(len(bm.verts))):
        return
    made_owners = {f: frozenset(owner[v] for v in f.verts if owner[v] in plan["co"]) for f in made}
    bm.verts.sort(key=lambda v: rank[v])
    bm.verts.index_update()
    # old faces: those at no vertex that ends two or more bevelled edges, then (after the bevel faces) those at one;
    # in each group the faces listed in plan["moved"] come last, in that order
    late = {i: n for n, i in enumerate(plan["moved"])}
    along = {i: n for n, i in enumerate(sorted(plan["along"], key=lambda i: (i in late, late.get(i, i))))}
    plain = {i: n for n, i in enumerate(sorted((i for i in range(plan["faces"]) if i not in along),
                                               key=lambda i: (i in late, late.get(i, i))))}
    edge_rank = {key: n for n, key in enumerate(plan["edge_faces"])}
    corner_rank = {v: n for n, v in enumerate(plan["corners"])}
    frank = {}
    for f in bm.faces:
        if f in made:
            srcs = made_owners[f]
            if srcs in edge_rank:
                frank[f] = (1, edge_rank[srcs])
            elif len(srcs) == 1 and next(iter(srcs)) in corner_rank:
                frank[f] = (3, corner_rank[next(iter(srcs))])
            else:
                return
        else:
            i = f[flay] - 1
            frank[f] = (2, along[i]) if i in along else (0, plain[i])
    if len(set(frank.values())) != len(frank):
        return
    bm.faces.sort(key=lambda f: frank[f][0] * 1000000 + frank[f][1])
    bm.faces.index_update()
