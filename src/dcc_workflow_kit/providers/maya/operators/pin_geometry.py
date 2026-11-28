# SPDX-License-Identifier: GPL-3.0-or-later
"""Surface frames on a mesh for UV Pin / Proximity Pin: ``Geo`` reads a mesh's triangles, UVs and its original and
deformed points, finds a location (face + corner weights) by UV (``at_uv``) or by closest point (``closest``) and
builds the pin frame there (``frame``: position, Maya vertex normal, tangent dP/du). Used by pin_update.py and
pin_create.py.
"""

import numpy as np
from mathutils import Vector


# --- geometry: original and deformed points of one mesh -------------------------------------------------------
#
# The pin surface frame:
# a location is (face, weights over its corners) — on a quad the bilinear (s, t) of its corners f0 f1 f2 f3, found
# from the UV (UV Pin) or the closest point (Proximity Pin); position = the same blend of the corner points, normal =
# the same blend of Maya vertex normals (normalised sum of the unit face normals around the vertex), tangent = dP/du
# of the face's FIRST Maya triangle (f0, f1, f[-1]) made orthogonal to the normal; the normal / tangent go to the
# chosen axes and the third axis completes a right-handed frame. N-gons / triangles use the triangle barycentrics.

def _vec_array(coll, attr, n, dim=3):
    a = np.empty(n * dim, dtype=np.float64)
    coll.foreach_get(attr, a)
    return a.reshape(n, dim)


def _int_array(coll, attr, n):
    a = np.empty(n, dtype=np.int64)
    coll.foreach_get(attr, a)
    return a


def _unit_rows(a):
    n = np.linalg.norm(a, axis=1)
    return a / np.where(n > 1e-30, n, 1.0)[:, None]


def _inv_bilinear(q, x):
    """(s, t) in [0, 1]² with (1-s)(1-t)q0 + s(1-t)q1 + st q2 + (1-s)t q3 closest to ``x`` (Gauss-Newton; exact on a
    UV rectangle / planar quad)."""
    s = t = 0.5
    for _i in range(40):
        b = (1 - s) * (1 - t) * q[0] + s * (1 - t) * q[1] + s * t * q[2] + (1 - s) * t * q[3]
        bs = (1 - t) * (q[1] - q[0]) + t * (q[2] - q[3])
        bt = (1 - s) * (q[3] - q[0]) + s * (q[2] - q[1])
        j = np.stack([bs, bt], axis=1)
        jtj = j.T @ j
        if abs(np.linalg.det(jtj)) < 1e-30:
            break
        d = np.linalg.solve(jtj, j.T @ (x - b))
        s, t = s + d[0], t + d[1]
        if abs(d[0]) + abs(d[1]) < 1e-15:
            break
    return min(max(s, 0.0), 1.0), min(max(t, 0.0), 1.0)


class Geo:
    """A mesh's faces / triangles (original topology), UVs and its original (local) / deformed (local) points."""

    def __init__(self, ob, depsgraph):
        me = ob.data
        if ob.mode == 'EDIT':
            # the original mesh's loop data is empty while the edit BMesh owns it (foreach_get raised on every
            # update): the pin waits where it is and follows again when edit mode ends
            self.ok = False
            return
        tris = me.loop_triangles
        nt = len(tris)
        self.ok = nt > 0
        if not self.ok:
            return
        self.tv = _int_array(tris, "vertices", nt * 3).reshape(nt, 3)
        self.tl = _int_array(tris, "loops", nt * 3).reshape(nt, 3)
        self.tp = _int_array(tris, "polygon_index", nt)
        npoly, nl = len(me.polygons), len(me.loops)
        self.ls = _int_array(me.polygons, "loop_start", npoly)
        self.lt = _int_array(me.polygons, "loop_total", npoly)
        self.lv = _int_array(me.loops, "vertex_index", nl)
        uvl = me.uv_layers.active
        self.luv = _vec_array(uvl.uv, "vector", nl, 2) if uvl is not None else None
        self.tuv = self.luv[self.tl] if self.luv is not None else None
        nv = len(me.vertices)
        self.co0 = _vec_array(me.vertices, "co", nv)
        ev = ob.evaluated_get(depsgraph) if depsgraph is not None else ob
        self.mw = np.array(ev.matrix_world, dtype=np.float64)
        em = ev.data
        if len(em.vertices) == nv and len(em.polygons) == npoly:
            self.co = _vec_array(em.vertices, "co", nv)
        elif len(em.vertices) > nv:
            # a subdivided result (the kit's smooth preview): Blender's subdivision writes the mesh's own vertices
            # first, at their smoothed place — the pin rides the displayed surface. Maya's preview is
            # display only (the pin keeps the unsmoothed shape): Blender can't give the deformed,
            # unsubdivided points here (BMesh.from_object(cage=True) applies deform modifiers twice).
            self.co = _vec_array(em.vertices, "co", len(em.vertices))[:nv]
        else:
            self.co = self.co0
        self._normals = {}

    def world_points(self):
        m = self.mw
        return self.co @ m[:3, :3].T + m[:3, 3]

    def normals(self, deformed=True):
        """Vertex normals (local): normalised sum of the unit (Newell) face normals around each vertex."""
        got = self._normals.get(deformed)
        if got is None:
            co = self.co if deformed else self.co0
            npoly, nl = len(self.ls), len(self.lv)
            poly = np.repeat(np.arange(npoly), self.lt)
            nxt = np.arange(1, nl + 1)
            nxt[self.ls + self.lt - 1] = self.ls
            fn = np.zeros((npoly, 3))
            np.add.at(fn, poly, np.cross(co[self.lv], co[self.lv[nxt]]))
            vn = np.zeros_like(co)
            np.add.at(vn, self.lv, _unit_rows(fn)[poly])
            got = self._normals[deformed] = _unit_rows(vn)
        return got

    def _loc(self, t, bw, coords):
        """Location (face, corner weights) from triangle t / barycentric bw; quads get Maya's bilinear (s, t) of the
        point ``coords[corners]`` blend (UVs or points)."""
        p = int(self.tp[t])
        ls, lt = int(self.ls[p]), int(self.lt[p])
        if lt == 4:
            q = coords[ls:ls + 4]
            s, tt = _inv_bilinear(q, np.asarray(bw) @ coords[self.tl[t]])
            return p, np.array([(1 - s) * (1 - tt), s * (1 - tt), s * tt, (1 - s) * tt])
        w = np.zeros(lt)
        for k in range(3):
            w[int(self.tl[t][k]) - ls] += bw[k]
        return p, w

    def closest(self, p, original=False, world=True):
        """Location of the closest point to ``p`` on the deformed (world) / original (local) mesh."""
        from mathutils.bvhtree import BVHTree
        pts = self.co0 if original else (self.world_points() if world else self.co)
        bvh = BVHTree.FromPolygons([tuple(x) for x in pts.tolist()], self.tv.tolist())
        hit = bvh.find_nearest(Vector(p))
        if hit is None or hit[2] is None:
            return None
        t = int(hit[2])
        return self._loc(t, _bary(np.array(hit[0], dtype=np.float64), pts[self.tv[t]]), pts[self.lv])

    def at_uv(self, uv):
        """Location of ``uv`` (the triangle whose UVs contain it, else the nearest one, clamped)."""
        if self.tuv is None:
            return None
        a, b, c = self.tuv[:, 0], self.tuv[:, 1], self.tuv[:, 2]
        p = np.asarray(uv, dtype=np.float64)
        v0, v1, v2 = b - a, c - a, p - a
        d00 = (v0 * v0).sum(1)
        d01 = (v0 * v1).sum(1)
        d11 = (v1 * v1).sum(1)
        d20 = (v2 * v0).sum(1)
        d21 = (v2 * v1).sum(1)
        den = d00 * d11 - d01 * d01
        good = np.abs(den) > 1e-18
        den = np.where(good, den, 1.0)
        w1 = (d11 * d20 - d01 * d21) / den
        w2 = (d00 * d21 - d01 * d20) / den
        w0 = 1.0 - w1 - w2
        worst = np.minimum(np.minimum(w0, w1), w2)
        worst = np.where(good, worst, -1e30)
        t = int(np.argmax(worst))
        w = np.clip(np.array([w0[t], w1[t], w2[t]]), 0.0, None)
        s = w.sum()
        return self._loc(t, w / s if s > 0 else np.array([1 / 3, 1 / 3, 1 / 3]), self.luv)

    def uv_at(self, loc):
        if self.luv is None or loc is None:
            return None
        p, w = loc
        ls = int(self.ls[p])
        return tuple((self.luv[ls:ls + len(w)] * np.asarray(w)[:, None]).sum(0))

    def frame(self, loc, axes=(0, 1), deformed=True, world=True):
        """4x4 Maya pin frame (numpy, column vectors) at ``loc``: deformed points in world space, or original local."""
        p, w = loc
        ls, lt = int(self.ls[p]), int(self.lt[p])
        vs = self.lv[ls:ls + lt]
        P = (self.co if deformed else self.co0)[vs]
        N = self.normals(deformed)[vs]
        if world:
            m3, tr = self.mw[:3, :3], self.mw[:3, 3]
            P = P @ m3.T + tr
            try:
                N = N @ np.linalg.inv(m3)
            except np.linalg.LinAlgError:
                pass
        w = np.asarray(w, dtype=np.float64)
        pos = w @ P
        n = w @ N
        if np.linalg.norm(n) < 1e-12:
            n = np.cross(P[1] - P[0], P[-1] - P[0])
        n = n / (np.linalg.norm(n) or 1.0)
        tan = None
        e = np.stack([P[1] - P[0], P[-1] - P[0]], axis=1)          # the first Maya triangle f0, f1, f[-1]
        if self.luv is not None:
            uv = self.luv[ls:ls + lt]
            a = np.stack([uv[1] - uv[0], uv[-1] - uv[0]], axis=1)
            if abs(np.linalg.det(a)) > 1e-18:
                tan = (e @ np.linalg.inv(a))[:, 0]                  # dP/du
        if tan is None:
            tan = e[:, 0]                                           # no UVs: the edge f0 -> f1
        tan = tan - n * float(np.dot(tan, n))
        if np.linalg.norm(tan) < 1e-12:
            tan = np.cross(n, (1.0, 0.0, 0.0))
            if np.linalg.norm(tan) < 1e-9:
                tan = np.cross(n, (0.0, 1.0, 0.0))
        tan = tan / np.linalg.norm(tan)
        na, ta = axes
        cols = [None, None, None]
        cols[na % 3] = n * (1.0 if na < 3 else -1.0)
        cols[ta % 3] = tan * (1.0 if ta < 3 else -1.0)
        r = 3 - na % 3 - ta % 3
        cols[r] = np.cross(cols[(r + 1) % 3], cols[(r + 2) % 3])
        m = np.identity(4)
        for i in range(3):
            m[:3, i] = cols[i]
        m[:3, 3] = pos
        return m


def _bary(p, tri):
    a, b, c = tri
    v0, v1, v2 = b - a, c - a, p - a
    d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
    d20, d21 = v2 @ v0, v2 @ v1
    den = d00 * d11 - d01 * d01
    if abs(den) < 1e-30:
        return np.array([1 / 3, 1 / 3, 1 / 3])
    w1 = (d11 * d20 - d01 * d21) / den
    w2 = (d00 * d21 - d01 * d20) / den
    return np.array([1.0 - w1 - w2, w1, w2])
