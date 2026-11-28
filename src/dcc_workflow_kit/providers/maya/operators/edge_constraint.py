# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's edge transform constraint for the Rotate and Scale tools (Ctrl+Shift+drag on a handle, Ctrl+Shift+middle-drag)
in mesh edit mode: the tool rotates / scales the selection as usual, then every selected vertex is put back on one
of its own edges.

For each selected vertex (``p`` = where it was, ``d`` = how far the plain rotate / scale took it):

1. ``N`` = the vertex normal (corner angle weighted) of the mesh as it was. The line through ``p + d`` along ``N`` is
   met with the mesh as it was (every face, quads cut along their shorter diagonal); the meeting point closest to
   ``p + d`` along the line gives ``q`` (from ``p``). When the line meets no face, ``q`` = the point of the mesh
   nearest to ``p + d``.
2. The edges the vertex may slide along: all of its edges. With vertices or edges selected (not faces), an edge to
   another selected vertex is left out, and so is the edge on the far side of the vertex from it (the edge that
   shares no face corner with it, when there is exactly one); when that leaves one edge or none, all edges stay.
3. The vertex slides along the edge ``e`` with the largest ``q · e`` (unit ``e``), by that amount and at most to the
   edge's other end. It stays where it was when that amount is not positive or ``q`` is more than 85 degrees off
   the edge. Edges that score the same: the first one around the vertex.

Faces, edge loops and single vertices therefore slide the way Maya slides them, and the same rules cover rings,
partial loops and mixed selections.
"""
import math

import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

MAX_ANGLE = 85.0                                  # degrees between q and the chosen edge
_COS_MAX = math.cos(math.radians(MAX_ANGLE)) - 1e-6
_EPS = 1e-9


def _triangles(faces, pos):
    """Every face as triangles (vertex index triples): quads along their shorter diagonal, others as a fan."""
    tris = []
    for f in faces:
        if len(f) == 3:
            tris.append(tuple(f))
        elif len(f) == 4:
            a, b, c, d = f
            if (pos[a] - pos[c]).length <= (pos[b] - pos[d]).length:
                tris += [(a, b, c), (a, c, d)]
            else:
                tris += [(a, b, d), (b, c, d)]
        else:
            tris += [(f[0], f[i], f[i + 1]) for i in range(1, len(f) - 1)]
    return tris


def _face_normal(f, pos):
    n = Vector()
    for i, a in enumerate(f):
        b = f[(i + 1) % len(f)]
        n += pos[a].cross(pos[b])
    return n.normalized() if n.length > _EPS else n


def vertex_normal(v, faces_of, faces, pos):
    """Corner-angle weighted normal of vertex ``v`` (``faces_of[v]`` = indices into ``faces``)."""
    n = Vector()
    for fi in faces_of[v]:
        f = faces[fi]
        i = f.index(v)
        a, b = pos[f[i - 1]] - pos[v], pos[f[(i + 1) % len(f)]] - pos[v]
        if a.length < _EPS or b.length < _EPS:
            continue
        n += a.angle(b) * _face_normal(f, pos)
    return n.normalized() if n.length > _EPS else n


def candidate_edges(v, nbs, faces_of, faces, selected, face_rule):
    """The neighbours of ``v`` it may slide toward (in ``nbs`` order)."""
    if face_rule:
        return list(nbs)
    picked = [u for u in nbs if u in selected]
    if not picked:
        return list(nbs)
    beside = {u: set() for u in nbs}             # neighbours that share a face corner at v with u
    for fi in faces_of[v]:
        f = faces[fi]
        i = f.index(v)
        a, b = f[i - 1], f[(i + 1) % len(f)]
        if a in beside and b in beside:
            beside[a].add(b)
            beside[b].add(a)
    out = set(picked)
    for u in picked:
        far = set(nbs) - {u} - beside[u]
        if len(far) == 1:
            out |= far
    left = [u for u in nbs if u not in out]
    return left if len(left) > 1 else list(nbs)


def slide_point(p, d, normal, cands, pos, bvh):
    """Where the vertex at ``p`` moved by ``d`` ends up (``cands`` = neighbour indices, ``pos`` = original points)."""
    o = p + d
    q = None
    if normal.length > _EPS:
        best = None
        for sign in (1.0, -1.0):
            direction = normal * sign
            hit = bvh.ray_cast(o - direction * 1e-6, direction)
            if hit[0] is not None:
                t = hit[3] - 1e-6
                if best is None or abs(t) < best[0]:
                    best = (abs(t), hit[0])
        if best is not None:
            q = best[1] - p
    if q is None:
        loc = bvh.find_nearest(o)[0]
        q = (loc if loc is not None else o) - p
    best_u, best_s = None, 0.0
    for u in cands:
        e = pos[u] - p
        if e.length < _EPS:
            continue
        s = q.dot(e) / e.length
        if best_u is None or s > best_s:
            best_u, best_s = u, s
    if best_u is None or best_s <= _EPS or q.length < _EPS or best_s / q.length < _COS_MAX:
        return p.copy()
    e = pos[best_u] - p
    return p + e.normalized() * min(best_s, e.length)


class Prepared:
    """One mesh in edit mode, read before the drag changes it: original world points, normals and the face tree."""

    def __init__(self, ob, face_rule):
        self.ob = ob
        bm = bmesh.from_edit_mesh(ob.data)
        bm.verts.ensure_lookup_table()
        mw = ob.matrix_world
        self.inv = mw.inverted_safe()
        self.pos = [mw @ v.co for v in bm.verts]
        self.faces = [[v.index for v in f.verts] for f in bm.faces]
        self.faces_of = [[] for _ in bm.verts]
        for fi, f in enumerate(self.faces):
            for v in f:
                self.faces_of[v].append(fi)
        self.nbs = [[e.other_vert(v).index for e in v.link_edges] for v in bm.verts]
        self.sel = [v.index for v in bm.verts if v.select and not v.hide]
        selected = set(self.sel)
        tris = _triangles(self.faces, self.pos)
        self.bvh = BVHTree.FromPolygons(self.pos, tris, all_triangles=True) if tris else None
        self.normals = {v: vertex_normal(v, self.faces_of, self.faces, self.pos) for v in self.sel}
        self.cands = {v: candidate_edges(v, self.nbs[v], self.faces_of, self.faces, selected, face_rule)
                      for v in self.sel}

    def apply(self):
        """Put every selected vertex of the (rotated / scaled) mesh back on its edge."""
        if self.bvh is None or not self.sel:
            return
        bm = bmesh.from_edit_mesh(self.ob.data)
        bm.verts.ensure_lookup_table()
        if len(bm.verts) != len(self.pos):
            return
        mw = self.ob.matrix_world
        new = {}
        for v in self.sel:
            p = self.pos[v]
            new[v] = slide_point(p, mw @ bm.verts[v].co - p, self.normals[v], self.cands[v], self.pos, self.bvh)
        for v, w in new.items():
            bm.verts[v].co = self.inv @ w
        bm.normal_update()
        bmesh.update_edit_mesh(self.ob.data, loop_triangles=True, destructive=False)


def face_rule(context):
    """Faces selected in face select mode: no edge is left out."""
    return bool(context.tool_settings.mesh_select_mode[2])


def prepare(context):
    """[Prepared] for the meshes in edit mode (call before the drag changes anything)."""
    rule = face_rule(context)
    return [Prepared(ob, rule) for ob in context.objects_in_mode_unique_data or () if ob.type == 'MESH']


def apply(prepared):
    for p in prepared:
        p.apply()
