# SPDX-License-Identifier: GPL-3.0-or-later
"""polyExtrudeFace on a bmesh: per-vertex move vectors (Thickness, Local Translate, Offset, Local Scale / Rotate,
world Translate / Rotate / Scale), the zero-length extrusion with Divisions / Keep Faces Together
(``extrude_topology``), placing the moved vertices (``place``) and Maya's vertex / edge / face order (``maya_plan``,
``renumber``). Entry point ``extrude``; ``face_axes`` / ``mesh_axes`` give a face's local X / Y. Related:
extrude_spec.py, extrude.py.
"""

import math

import bmesh
from mathutils import Euler, Matrix, Vector

from .extrude_spec import MAYA_Z, WORLD_X


# --- geometry (bmesh only) -------------------------------------------------------------------------

def _thickness_dir(normals):
    """Displacement that moves every face plane in ``normals`` by 1 (Maya Thickness, a shell)."""
    if len(normals) == 1:
        return normals[0].copy()
    if len(normals) == 2:
        n1, n2 = normals
        return (n1 + n2) / max(1.0 + n1.dot(n2), 1e-3)
    m = sum(normals, Vector()).normalized()
    return m / max(sum(m.dot(n) for n in normals) / len(normals), 0.1)


def _inward(face, edge):
    """Unit vector in ``face``'s plane, perpendicular to ``edge``, pointing into the face."""
    for loop in face.loops:
        if loop.edge is edge:
            t = (loop.link_loop_next.vert.co - loop.vert.co).normalized()
            return face.normal.cross(t).normalized()
    return Vector()


def _offset_dir(perps):
    """Offset of a boundary vertex: each of its two boundary edges moves 1 into the face."""
    if len(perps) == 2:
        a, b = perps
        return (a + b) / max(1.0 + a.dot(b), 1e-3)
    if perps:
        return sum(perps, Vector()) / len(perps)
    return Vector()


def face_axes(normal, direction=WORLD_X, fallback=MAYA_Z):
    """Maya's local X / Y of an extruded face (polyExtrudeFace ``localDirection`` 1 0 0): the
    direction projected into the face plane, ``fallback`` (Maya world Z) when the face looks along it; Y = Z x X."""
    n = normal.normalized() if normal.length > 1e-12 else Vector((0.0, 0.0, 1.0))
    for d in (direction, fallback, Vector((0.0, 1.0, 0.0))):
        x = d - n * d.dot(n)
        if x.length > 1e-6:
            x = x.normalized()
            return x, n.cross(x).normalized()
    return Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0))


def _face_parts(f, v, direction, fallback):
    """(X, Y, SX, SY, SZ, (X, Y, Z, R)) of vertex ``v`` in face ``f``: the face's local X / Y, the move of ``v`` per
    unit of Local Scale - 1 along X / Y / Z about the face's vertex mean, and the face's local axes with ``v``'s
    offset R from that mean (what Local Rotate turns)."""
    n = f.normal.normalized()
    x, y = face_axes(n, direction, fallback)
    r = v.co - f.calc_center_median()
    return x, y, x * r.dot(x), y * r.dot(y), n * r.dot(n), (x, y, n, r)


def _translate_dir(v, faces, normals, perps):
    """Local Translate Z of vertex ``v`` per unit (Maya): on the border of the extruded region the mean of its faces'
    normals; inside it (no border edge) the unit normal with each face weighted by its corner angle at ``v``."""
    if perps:
        return sum(normals, Vector()) / len(normals)
    n = Vector()
    for g, gn in zip(faces, normals):
        loop = next((lp for lp in g.loops if lp.vert is v), None)
        if loop is not None:
            n += gn * loop.calc_angle()
    return n.normalized() if n.length > 1e-12 else sum(normals, Vector()) / len(normals)


def _mean(vectors):
    return sum(vectors, Vector()) / len(vectors)


def _vectors(faces, together, direction=WORLD_X, fallback=MAYA_Z):
    """{key: (base co, T, L, O, X, Y, SX, SY, SZ, faces)} per extruded vertex (key = vertex index, or (face index,
    vertex index) for faces extruded one by one; faces = the (X, Y, Z, R) of each extruded face it is on), from the
    faces before the extrusion."""
    sel = set(faces)
    out = {}
    if together:
        for f in faces:
            for v in f.verts:
                if v.index in out:
                    continue
                vf = [g for g in v.link_faces if g in sel]
                normals = [g.normal.copy() for g in vf]
                perps = []
                for e in v.link_edges:
                    ef = [g for g in e.link_faces if g in sel]
                    if len(ef) == 1:              # a border edge of the extruded region
                        perps.append(_inward(ef[0], e))
                parts = [_face_parts(g, v, direction, fallback) for g in vf]
                out[v.index] = (v.co.copy(), _thickness_dir(normals), _translate_dir(v, vf, normals, perps),
                                _offset_dir(perps), *(_mean([p[i] for p in parts]) for i in range(5)),
                                tuple(p[5] for p in parts))
    else:
        for f in faces:
            n = f.normal.copy()
            for v in f.verts:
                perps = [_inward(f, e) for e in v.link_edges if f in e.link_faces]
                *parts, turn = _face_parts(f, v, direction, fallback)
                out[(f.index, v.index)] = (v.co.copy(), n.copy(), n.copy(), _offset_dir(perps), *parts, (turn,))
    return out


def _key(co):
    return tuple(round(c, 6) for c in co)


def _caps(ret_geom):
    verts = {g for g in ret_geom if isinstance(g, bmesh.types.BMVert)}
    return [g for g in ret_geom if isinstance(g, bmesh.types.BMFace) and all(v in verts for v in g.verts)]


def _closed(faces):
    """No edge of ``faces`` borders an unextruded face or the mesh border: the faces are whole closed shells."""
    sel = set(faces)
    return bool(faces) and all(sum(1 for g in e.link_faces if g in sel) == 2 for f in faces for e in f.edges)


def _whole(bm, faces):
    """``faces`` are every face of the mesh: like Maya, their extrusion keeps the old faces, turned inside out, as
    the bottom (a plane becomes a closed slab, an open shell gets its thickness on both sides)."""
    return bool(faces) and len(set(faces)) == len(bm.faces)


def _region(bm, faces, keep=False):
    edges = {e for f in faces for e in f.edges}
    ret = bmesh.ops.extrude_face_region(bm, geom=list(faces) + list(edges))
    caps = _caps(ret["geom"])
    # bmesh keeps (and turns inside out) the old faces of a region with no other face around it
    gone = [f for f in faces if f.is_valid]
    if gone and not keep:
        # Maya moves them: delete them with the inner edges and vertices nothing else uses
        bmesh.ops.delete(bm, geom=gone, context='FACES')
    return caps


def extrude_topology(bm, faces, divisions=1, together=True, direction=WORLD_X, fallback=MAYA_Z, keep_bottom=False):
    """Zero-length extrusion of ``faces``, ``divisions`` times. Returns (caps, levels, vectors) where
    levels[k-1] maps a vertex key to the level-k vertex (level ``divisions`` = the caps). The extrusion of the whole
    mesh keeps the old faces as its bottom; ``keep_bottom``: so do faces with no neighbours (Maya's extrusion along
    a curve)."""
    bm.verts.index_update()
    bm.faces.index_update()
    faces = [f for f in faces if f.is_valid]
    # Faces apart: each face is its own extrusion, the whole mesh only when it has one face
    whole = _whole(bm, faces) and (together or len(faces) == 1)
    vectors = _vectors(faces, together, direction, fallback)
    if together:
        by_co = {_key(co): k for k, (co, *_r) in vectors.items()}
    else:
        by_co = {}
        for (fi, vi), (co, *_r) in vectors.items():
            by_co.setdefault(fi, {})[_key(co)] = (fi, vi)
    order = [f.index for f in faces]
    levels = []
    caps = faces
    if together and _closed(faces):
        divisions = 1        # Maya extrudes closed shells once whatever Divisions says
    for level in range(max(1, divisions)):
        if level == 0 and not together and not whole:
            caps = bmesh.ops.extrude_discrete_faces(bm, faces=caps)["faces"]
            gone = [f for f in faces if f.is_valid]
            if gone and not keep_bottom:
                bmesh.ops.delete(bm, geom=gone, context='FACES_ONLY')
        else:
            caps = _region(bm, caps, (keep_bottom or whole) and level == 0)
        found = {}
        if together:
            for f in caps:
                for v in f.verts:
                    k = by_co.get(_key(v.co))
                    if k is not None:
                        found[k] = v
        else:
            # extrude_discrete_faces / later regions keep the face order; match vertices by position per face
            if level == 0:
                caps_by_face = dict(zip(order, caps))
            else:      # the next caps sit where the previous ones were
                caps_by_face = {fi: _match_face(caps, by_co[fi]) for fi in order}
            for fi, cap in caps_by_face.items():
                if cap is None:
                    continue
                for v in cap.verts:
                    k = by_co[fi].get(_key(v.co))
                    if k is not None:
                        found[k] = v
        levels.append(found)
    return caps, levels, vectors


def _match_face(caps, keys):
    want = set(keys)
    return next((c for c in caps if {_key(v.co) for v in c.verts} == want), None)


def moved_vertices(levels, vectors, unit=1.0):
    """[(vertex, P0, T, L, O, X, Y, SX, SY, SZ, fraction, faces)] with the level fraction folded into every vector
    and the Maya unit into the length ones (T, L, O, X, Y; the scale moves SX / SY / SZ are already mesh lengths);
    ``fraction`` = the level's share of the extrusion, ``faces`` = the (X, Y, Z, R) of ``_vectors``."""
    n = len(levels)
    out = []
    for k, found in enumerate(levels, 1):
        frac = k / n
        f = frac * unit
        for key, v in found.items():
            co, t, l, o, x, y, sx, sy, sz, turn = vectors[key]
            out.append((v, co.copy(), t * f, l * f, o * f, x * f, y * f, sx * frac, sy * frac, sz * frac, frac, turn))
    return out


AXES = ("x", "y", "z")
TURN_FIELDS = tuple(f"local_rotate_{a}" for a in AXES)
WORLD_FIELDS = tuple(f"{t}_{a}" for t in ("translate", "rotate", "scale") for a in AXES)


def _rest(field):
    return 1.0 if "scale" in field else 0.0


def _rotation(params, prefix, frac):
    return Euler([math.radians(params.get(prefix + a, 0.0) * frac) for a in AXES], 'XYZ').to_matrix()


def _scaling(params, prefix, frac):
    return Matrix.Diagonal([1.0 + (params.get(prefix + a, 1.0) - 1.0) * frac for a in AXES])


def world_space(moved, matrix, params, unit=1.0):
    """What Translate / Rotate / Scale need in ``position``: (object matrix, its inverse, world pivot, Maya unit), or
    None while they are at rest. Like Maya, the pivot is the centre of the bounding box of the extruded faces, in
    world space."""
    if matrix is None or not moved or all(params.get(f, _rest(f)) == _rest(f) for f in WORLD_FIELDS):
        return None
    points = [matrix @ m[1] for m in moved]
    lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    return matrix, matrix.inverted_safe(), (lo + hi) / 2, unit


def position(p0, vecs, params, world=None):
    """Where a moved vertex goes for ``params`` (vecs = T, L, O, X, Y, SX, SY, SZ[, fraction, faces] of
    ``moved_vertices``; ``world`` = ``world_space``). Like Maya's polyExtrudeFace, the local values (Local
    Translate / Rotate / Scale, Offset) and the world ones (Translate, then Rotate and Scale about the pivot, on the
    point after Thickness) each give a move and the vertex takes both; a level of a divided extrusion takes its
    share of every value (angles and scale steps too). Local Scale and Local Rotate act in each extruded face's
    local frame about the face's centre; a vertex on several faces moves by the mean."""
    t, l, o, x, y, sx, sy, sz = vecs[:8]
    frac, turn = (vecs[8], vecs[9]) if len(vecs) > 9 else (1.0, ())
    g = params.get
    thick = p0 + t * g("thickness", 0.0)
    p = (thick + l * g("local_translate_z", 0.0) + o * g("offset", 0.0)
         + x * g("local_translate_x", 0.0) + y * g("local_translate_y", 0.0))
    if turn and any(g(f, 0.0) for f in TURN_FIELDS):
        rot, scale = _rotation(params, "local_rotate_", frac), _scaling(params, "local_scale_", frac)
        move = Vector()
        for fx, fy, fz, r in turn:
            frame = Matrix((fx, fy, fz)).transposed()          # local -> mesh (columns X, Y, Z)
            move += frame @ (rot @ (scale @ (frame.transposed() @ r))) - r
        p = p + move / len(turn)
    else:
        p = (p + sx * (g("local_scale_x", 1.0) - 1.0) + sy * (g("local_scale_y", 1.0) - 1.0)
             + sz * (g("local_scale_z", 1.0) - 1.0))
    if world is not None:
        mw, inv, pivot, unit = world
        shift = Vector([g(f"translate_{a}", 0.0) for a in AXES]) * (unit * frac)
        turned = _rotation(params, "rotate_", frac) @ _scaling(params, "scale_", frac)
        base = mw @ thick
        p = p + inv.to_3x3() @ (pivot + turned @ (base + shift - pivot) - base)
    return p


def place(moved, thickness=0.0, ltz=0.0, offset=0.0, matrix=None, unit=1.0, **manip):
    params = dict(manip, thickness=thickness, local_translate_z=ltz, offset=offset)
    world = world_space(moved, matrix, params, unit)
    for v, p0, *vecs in moved:
        v.co = position(p0, vecs, params, world)


def extrude(bm, faces, thickness=0.0, local_translate_z=0.0, offset=0.0, divisions=1, keep_faces_together=True,
            unit=1.0, direction=WORLD_X, fallback=MAYA_Z, history_id=None, matrix=None, **manip):
    """Maya polyExtrudeFace on ``faces`` (bmesh). Returns (caps, moved); the caps end up selected. ``manip`` =
    the manipulator values (MANIP_FIELDS); ``direction`` / ``fallback`` = world X / Z in mesh space (the faces'
    local X); ``matrix`` = the object's world matrix (Translate / Rotate / Scale act in world space)."""
    lineage = None
    if history_id:
        from . import history_references as references
        handles = references.layers(bm)
        bm.verts.index_update()
        bm.faces.index_update()
        # Refresh after adding custom data layers, which invalidates BMesh element wrappers.
        faces = [face for face in bm.faces if face.select]
        parents = {v.index: references.identity(v, handles) for face in faces for v in face.verts}
        face_keys = {face.index: sorted(references.identity(v, handles) for v in face.verts) for face in faces}
        lineage = (history_id, parents, face_keys, handles)
    bm.faces.index_update()
    picked = sorted({f.index for f in faces if f.is_valid})
    plan = maya_plan(bm, picked, divisions, keep_faces_together)
    src = bm.verts.layers.int.new(".allset_extrude_src")     # added before elements are collected again
    for v in bm.verts:
        v[src] = v.index + 1
    bm.faces.ensure_lookup_table()
    faces = [bm.faces[i] for i in picked]
    caps, levels, vectors = extrude_topology(bm, faces, divisions, keep_faces_together, direction, fallback)
    # an inner vertex of a middle level is gone once the next level is extruded (Maya has only the cap's)
    levels = [{key: v for key, v in found.items() if v.is_valid} for found in levels]
    moved = moved_vertices(levels, vectors, unit)
    place(moved, thickness, local_translate_z, offset, matrix, unit, **manip)
    for f in bm.faces:
        f.select = False
    for e in bm.edges:
        e.select = False
    for v in bm.verts:
        v.select = False
    for f in caps:
        f.select_set(True)
    caps, moved = renumber(bm, plan, levels, src, caps, moved, lineage)
    bm.verts.index_update()
    bm.faces.index_update()
    cap_ids = [f.index for f in caps]
    moved_ids = [(v.index, rest) for v, *rest in moved]
    bm.verts.layers.int.remove(src)     # removing a layer invalidates element references too
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    caps = [bm.faces[i] for i in cap_ids]
    moved = [(bm.verts[i], *rest) for i, rest in moved_ids]
    bm.select_flush_mode()
    bm.normal_update()
    return caps, moved


# --- Maya's numbering of the result (#149) ---------------------------------------------------------------
# polyExtrudeFacet (Maya 2026): vertices, edges and faces by index, with a border, for closed shells and
# for the whole mesh. The mesh's edge index is taken as Maya's edge id: kit
# primitives (polyCube / polyCylinder) and kit extrusions keep it so (bevel_numbering.maya_edge_ids).

def maya_plan(bm, picked, divisions=1, together=True):
    """What Maya's polyExtrudeFacet of faces ``picked`` (indices) leaves, in Maya's order, as descriptors:
    ("o", i) = old vertex i, ("n", key, j) = the new vertex of ``key`` at level j (key = old vertex index, or
    (face index, vertex index) for faces apart; j = 0 for the one new vertex of an inner vertex).
    Returns {"verts", "edges", "faces", "div"} or None (no faces)."""
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    sel = sorted(set(picked))
    if not sel:
        return None
    F = [[v.index for v in f.verts] for f in bm.faces]
    E = [(e.verts[0].index, e.verts[1].index) for e in bm.edges]
    eid = {frozenset(p): i for i, p in enumerate(E)}
    efaces = {}
    for fi, f in enumerate(F):
        for k in range(len(f)):
            efaces.setdefault(frozenset((f[k], f[(k + 1) % len(f)])), []).append(fi)

    def corner_edges(fi):
        f = F[fi]
        return [(f[k], f[(k + 1) % len(f)]) for k in range(len(f))]
    div = max(1, int(divisions))
    picked_set = set(sel)
    closed = together and all(len([x for x in efaces[frozenset(c)] if x in picked_set]) == 2
                              for fi in sel for c in corner_edges(fi))
    if closed:
        div = 1
    # the whole mesh extruded as one: the old faces stay (turned inside out), no old vertex or edge goes
    keep = len(sel) == len(F) and (together or len(sel) == 1)
    groups = [sel] if together else [[fi] for fi in sel]
    new_verts, new_edges, side_faces, removed, gone = [], [], [], set(), set()
    out_faces = [[("o", v) for v in f] for f in F]
    for grp in groups:
        g = set(grp)

        def border(key):
            return len([x for x in efaces[key] if x in g]) == 1
        bverts = set()
        for fi in grp:
            for c in corner_edges(fi):
                if border(frozenset(c)):
                    bverts |= set(c)
        chain, done = {}, set()

        def tag(x):
            return x if together else (grp[0], x)

        def lev(x, j):
            if j == 0:
                return ("o", x)
            c = chain[x]
            return c[j - 1] if len(c) > 1 else c[0]
        for fi in grp:
            for a, b in corner_edges(fi):
                key = frozenset((a, b))
                v0, v1 = E[eid[key]]
                for x in (v0, v1):          # new vertices in the order the walk meets them, edge ends in edge order
                    if x in chain:
                        continue
                    if x in bverts:         # a chain of Divisions vertices up from x
                        chain[x] = [("n", tag(x), j) for j in range(1, div + 1)]
                        new_verts += chain[x]
                        new_edges += list(zip([("o", x)] + chain[x][:-1], chain[x]))
                    else:                   # an inner (or closed-shell) vertex: one new vertex, the old one goes
                        chain[x] = [("n", tag(x), 0)]
                        new_verts.append(chain[x][0])
                        if not keep:
                            gone.add(x)
                if key not in done:
                    done.add(key)
                    if border(key):
                        new_edges += [(lev(v0, j), lev(v1, j)) for j in range(1, div + 1)]
                    else:
                        if not keep:
                            removed.add(eid[key])
                        new_edges.append((lev(v0, div), lev(v1, div)))
                if border(key):
                    side_faces += [[lev(a, j), lev(b, j), lev(b, j + 1), lev(a, j + 1)] for j in range(div)]
        for fi in grp:
            out_faces[fi] = [lev(v, div) for v in F[fi]]
    if keep:      # the old faces, turned inside out, come before the side faces
        side_faces = [[("o", F[fi][0])] + [("o", v) for v in reversed(F[fi][1:])] for fi in sel] + side_faces
    return {"verts": [("o", v) for v in range(len(bm.verts)) if v not in gone] + new_verts,
            "edges": [(("o", p[0]), ("o", p[1])) for i, p in enumerate(E) if i not in removed] + new_edges,
            "faces": out_faces + side_faces, "div": div}


def renumber(bm, plan, levels, src, caps, moved, lineage=None):
    """Sort the extruded mesh's vertices, edges and faces into ``plan``'s (Maya's) order; caps / moved come back as
    fresh references (a bmesh sort moves the data under existing ones). Left as it is when the kit's result doesn't
    match the plan element for element."""
    if plan is None:
        return caps, moved
    elem, newer = {}, set()
    for j, found in enumerate(levels, 1):
        for key, v in found.items():
            if v.is_valid:
                elem[("n", key, j)] = v
                newer.add(v)
    if len(levels) == plan["div"]:
        for key, v in levels[-1].items():      # inner vertices: the cap level's
            if v.is_valid:
                elem.setdefault(("n", key, 0), v)
    for v in bm.verts:
        if v not in newer:
            elem[("o", v[src] - 1)] = v
    try:
        vrank = {elem[d]: i for i, d in enumerate(plan["verts"])}
        edge_of = {frozenset(e.verts): e for e in bm.edges}
        face_of = {frozenset(f.verts): f for f in bm.faces}
        erank = {edge_of[frozenset((elem[a], elem[b]))]: i for i, (a, b) in enumerate(plan["edges"])}
        frank = {face_of[frozenset(elem[d] for d in f)]: i for i, f in enumerate(plan["faces"])}
    except KeyError:
        return caps, moved
    if not (len(vrank) == len(bm.verts) == len(plan["verts"]) and len(erank) == len(bm.edges) == len(plan["edges"])
            and len(frank) == len(bm.faces) == len(plan["faces"])):
        return caps, moved
    if lineage is not None:
        from . import history_references as references
        node_id, parents, face_keys, handles = lineage
        for descriptor in plan['verts']:
            if descriptor[0] != 'n':
                continue
            _kind, source, level = descriptor
            if isinstance(source, tuple):
                face_index, vertex_index = source
                parent = (face_keys[face_index], parents[vertex_index])
            else:
                parent = parents[source]
            part = references.fraction(level/plan['div']) if level else (1, 1)
            references.assign(elem[descriptor], handles,
                              references.generated(node_id, ('FACE', parent, part)))
    cap_ids = [frank[f] for f in caps]
    moved_ids = [(vrank[v], rest) for v, *rest in moved]
    bm.verts.sort(key=lambda v: vrank[v])
    bm.edges.sort(key=lambda e: erank[e])
    bm.faces.sort(key=lambda f: frank[f])
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    return [bm.faces[i] for i in cap_ids], [(bm.verts[i], *rest) for i, rest in moved_ids]


def mesh_axes(ob):
    """Maya world X / Z in ``ob``'s mesh space (Maya takes ``localDirection`` in world space)."""
    m = ob.matrix_world.to_3x3().inverted_safe()
    return {"direction": m @ WORLD_X, "fallback": m @ MAYA_Z}
