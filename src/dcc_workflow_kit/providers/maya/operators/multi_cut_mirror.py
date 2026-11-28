# SPDX-License-Identifier: GPL-3.0-or-later
"""Multi-Cut with symmetry on (GitHub #420): like Maya, a cut, a Ctrl+click edge loop and a slice are made on both
sides of the mesh.

``Mirror`` maps the cut points of one side to the other side of a bmesh in the object's local space:

- Object / World symmetry: by position, through the mirror of the chosen axis (``quad_draw_symmetry.reflection``);
- Topology symmetry: by the mesh's topological pairs (``quad_draw_symmetry.topology_mapping``).

A point without a partner (an asymmetric part of the mesh) leaves the mirrored path out; a path that is its own
mirror (a cut across the middle, a loop on the plane) is made once.
"""

from mathutils import Vector
from mathutils.interpolate import poly_3d_calc
from mathutils.kdtree import KDTree

_cache = {}


class Mirror:
    """Partners of the components of ``bm`` on the other side. ``matrix``: the local reflection (Object / World);
    ``pairs``: {BMVert: BMVert} (Topology)."""

    def __init__(self, bm, matrix=None, pairs=None):
        self.bm = bm
        self.matrix = matrix
        self.pairs = pairs
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        coords = [v.co for v in bm.verts]
        span = max((max(c[k] for c in coords) - min(c[k] for c in coords) for k in range(3)), default=0.0) \
            if coords else 0.0
        self.eps = max(span * 1e-5, 1e-7)
        self.kd = None
        if matrix is not None:
            self.kd = KDTree(len(bm.verts))
            for v in bm.verts:
                self.kd.insert(v.co, v.index)
            self.kd.balance()

    # -- components
    def vert(self, v):
        if self.pairs is not None:
            return self.pairs.get(v)
        co, index, dist = self.kd.find(self.matrix @ v.co)
        if co is None or dist > self.eps:
            return None
        return self.bm.verts[index]

    def co(self, face, co):
        """The mirror of the local point ``co`` that lies on ``face``."""
        if self.matrix is not None:
            return self.matrix @ Vector(co)
        verts = list(face.verts)
        weights = poly_3d_calc([v.co for v in verts], Vector(co))
        out = Vector()
        for v, w in zip(verts, weights):
            out += self.pairs[v].co * w
        return out

    def edge(self, e):
        a, b = self.vert(e.verts[0]), self.vert(e.verts[1])
        if a is None or b is None:
            return None, False
        m = self.bm.edges.get((a, b))
        return m, (m is not None and m.verts[0] is a)

    def face(self, f):
        verts = [self.vert(v) for v in f.verts]
        if any(v is None for v in verts):
            return None
        try:
            return self.bm.faces.get(verts)
        except (ValueError, TypeError):
            return None

    # -- cut points: ('VERT', i), ('EDGE', i, t), ('FACE', i, local co)
    def point(self, p):
        kind, index = p[0], p[1]
        if kind == 'VERT':
            v = self.vert(self.bm.verts[index])
            return None if v is None else ('VERT', v.index)
        if kind == 'EDGE':
            m, same = self.edge(self.bm.edges[index])
            if m is None:
                return None
            return ('EDGE', m.index, p[2] if same else 1.0 - p[2])
        f = self.bm.faces[index]
        m = self.face(f)
        if m is None or (self.pairs is not None and any(v not in self.pairs for v in f.verts)):
            return None
        return ('FACE', m.index, tuple(self.co(f, p[2])))

    def path(self, points):
        """The mirrored cut path, or None (a point has no partner, or the path is its own mirror)."""
        out = []
        for p in points:
            q = self.point(p)
            if q is None:
                return None
            out.append(q)
        if _same_set(points, out):
            return None
        return out

    def plane(self, co, no):
        """The mirrored slice plane (local), or None (Topology, or the plane is its own mirror)."""
        if self.matrix is None:
            return None
        co2 = self.matrix @ Vector(co)
        no2 = (self.matrix.to_3x3() @ Vector(no)).normalized()
        n = Vector(no).normalized()
        if no2.cross(n).length < 1e-6 and abs((co2 - Vector(co)).dot(n)) < self.eps:
            return None
        return co2, no2


def _key(p):
    if p[0] == 'EDGE':
        return (p[0], p[1], round(p[2], 6))
    if p[0] == 'FACE':
        return (p[0], p[1], tuple(round(c, 6) for c in p[2]))
    return p


def _same_set(a, b):
    return {_key(p) for p in a} == {_key(p) for p in b}


def for_object(context, ob, bm):
    """The Mirror of ``ob``'s edit mesh while symmetry is on, else None. Topology pairs are kept while the mesh does
    not change."""
    from . import symmetry, quad_draw_symmetry as qds
    sym = symmetry.state(context.scene)
    if not sym.on:
        return None
    axis = "XYZ".index(sym.axis)
    if sym.about == 'TOPOLOGY':
        key = (ob.name, ob.data.as_pointer(), id(bm), len(bm.verts), len(bm.edges), len(bm.faces), axis)
        pairs = _cache.get(key)
        if pairs is None:
            try:
                bm.verts.ensure_lookup_table()
                found = qds.topology_mapping(ob, bm, sym)
            except (ValueError, AttributeError, ReferenceError):
                found = {}
            pairs = {a.index: b.index for a, b in found.items()}
            _cache.clear()
            _cache[key] = pairs
        if not pairs:
            return None
        bm.verts.ensure_lookup_table()
        return Mirror(bm, pairs={bm.verts[a]: bm.verts[b] for a, b in pairs.items()})
    return Mirror(bm, matrix=qds.reflection(ob, sym.about, axis))


def clear():
    _cache.clear()


def edge_at(bm, a, b, co, eps):
    """After an edge a-b was split, the piece of it that holds the local point ``co`` and the factor there from that
    piece's first vertex; (None, 0) when ``co`` is a vertex of the chain already (nothing to insert)."""
    seg = b.co - a.co
    if seg.length_squared < 1e-20:
        return None, 0.0

    def on_line(v):
        u = (v.co - a.co).dot(seg) / seg.length_squared
        return -1e-9 <= u <= 1 + 1e-9 and (a.co + seg * u - v.co).length <= eps

    chain = {a, b}
    stack = [a]
    while stack:
        v = stack.pop()
        for e in v.link_edges:
            w = e.other_vert(v)
            if w not in chain and on_line(w):
                chain.add(w)
                stack.append(w)
    for v in chain:
        if (v.co - co).length <= eps:
            return None, 0.0
    for e in {e for v in chain for e in v.link_edges if e.other_vert(v) in chain}:
        p, q = e.verts[0].co, e.verts[1].co
        d = q - p
        if d.length_squared < 1e-20:
            continue
        u = (co - p).dot(d) / d.length_squared
        if 0.0 < u < 1.0 and (p + d * u - co).length <= eps:
            return e, u
    return None, 0.0


def loop_partner(bm, mirror, edge_index, t):
    """Before an edge loop at ``t`` on edge ``edge_index`` is inserted: what the mirrored loop needs afterwards
    (vertex indices of the mirrored edge, the local point on it), or None (no partner / the loop is its own
    mirror)."""
    e = bm.edges[edge_index]
    m, same = mirror.edge(e)
    if m is None:
        return None
    u = t if same else 1.0 - t
    co = m.verts[0].co.lerp(m.verts[1].co, u)
    if m is e and abs(u - t) < 1e-6:
        return None
    return m.verts[0].index, m.verts[1].index, co.copy()


def insert_partner(bm, partner, eps, insert):
    """Insert the mirrored loop recorded by ``loop_partner`` with ``insert(bm, edge, t)`` (vertex indices stay valid:
    the loop only adds vertices). Returns its new edges."""
    if partner is None:
        return []
    bm.verts.ensure_lookup_table()
    ia, ib, co = partner
    if max(ia, ib) >= len(bm.verts):
        return []
    e, u = edge_at(bm, bm.verts[ia], bm.verts[ib], co, eps)
    if e is None:
        return []
    return insert(bm, e, u)

