# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's surface normal and curve tangent at the closest point, in double precision, for the Normal / Tangent
constraints: ``SurfaceData`` holds a mesh's world triangles with corner normals weighted by corner angle x face area
and Maya's quad split (``quad_split``); ``CurveData`` finds the closest curve parameter (``closest_param``) and its
tangent. constrain_199.py moves the helper empties with them.
"""

import math

from mathutils import Vector

QUAD_SPLIT = 0.999                   # Maya splits a quad 0-2 only when d02^2 < 0.999 d13^2


# --- small vector maths (double precision) ------------------------------------------------------------

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def closest_on_triangle(p, a, b, c):
    """(closest point, barycentric (wa, wb, wc)) of p on triangle abc (Ericson, Real-Time Collision Detection 5.1.5)."""
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(p, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return (1.0, 0.0, 0.0)
    bp = _sub(p, b)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return (0.0, 1.0, 0.0)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1 / (d1 - d3)
        return (1 - v, v, 0.0)
    cp = _sub(p, c)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return (0.0, 0.0, 1.0)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        w = d2 / (d2 - d6)
        return (1 - w, 0.0, w)
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return (0.0, 1 - w, w)
    den = 1.0 / (va + vb + vc)
    v, w = vb * den, vc * den
    return (1 - v - w, v, w)


def _point(bc, a, b, c):
    return tuple(bc[0] * a[i] + bc[1] * b[i] + bc[2] * c[i] for i in range(3))


def quad_split(q):
    """Maya's triangles of quad corners 0..3 (MFnMesh.getTriangles)."""
    d02 = _dot(_sub(q[0], q[2]), _sub(q[0], q[2]))
    d13 = _dot(_sub(q[1], q[3]), _sub(q[1], q[3]))
    return ((0, 1, 2), (0, 2, 3)) if d02 < QUAD_SPLIT * d13 else ((0, 1, 3), (1, 2, 3))


# --- Maya surface normal on a Blender mesh ------------------------------------------------------------

class SurfaceData:
    """World-space triangles of a mesh with Maya's corner normals (face normals weighted by corner angle x face
    area over each smooth fan; hard edges / flat faces split the fans)."""

    def __init__(self, mesh, matrix):
        import numpy as np
        from mathutils.bvhtree import BVHTree
        n = len(mesh.vertices)
        co = np.empty(n * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", co)
        co = co.reshape(n, 3).astype(np.float64)
        m = np.array(matrix, dtype=np.float64)
        co = co @ m[:3, :3].T + m[:3, 3]
        self.co = [tuple(v) for v in co.tolist()]
        polys = mesh.polygons
        starts = [p.loop_start for p in polys]
        totals = [p.loop_total for p in polys]
        lv = [lp.vertex_index for lp in mesh.loops]
        le = [lp.edge_index for lp in mesh.loops]
        sharp_e = mesh.attributes.get("sharp_edge")
        sharp_e = [d.value for d in sharp_e.data] if sharp_e is not None and sharp_e.domain == 'EDGE' else None
        sharp_f = mesh.attributes.get("sharp_face")
        sharp_f = [d.value for d in sharp_f.data] if sharp_f is not None and sharp_f.domain == 'FACE' else None
        # face normals: Newell's method, unit length; face area = half the Newell length
        fn, area = [], []
        for s, t in zip(starts, totals):
            x = y = z = 0.0
            for k in range(t):
                a = self.co[lv[s + k]]
                b = self.co[lv[s + (k + 1) % t]]
                x += (a[1] - b[1]) * (a[2] + b[2])
                y += (a[2] - b[2]) * (a[0] + b[0])
                z += (a[0] - b[0]) * (a[1] + b[1])
            ln = math.sqrt(x * x + y * y + z * z) or 1.0
            fn.append((x / ln, y / ln, z / ln))
            area.append(ln / 2)
        # smooth fans: (vertex, face) pairs joined across smooth edges
        parent = {}

        def find(k):
            while parent.setdefault(k, k) != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k

        edge_faces = {}
        for f, (s, t) in enumerate(zip(starts, totals)):
            for k in range(t):
                edge_faces.setdefault(le[s + k], []).append(f)
        edges = mesh.edges
        for e, faces in edge_faces.items():
            if len(faces) < 2 or (sharp_e and sharp_e[e]):
                continue
            if sharp_f and any(sharp_f[f] for f in faces):
                continue
            for v in edges[e].vertices:
                for f in faces[1:]:
                    a, b = find((v, faces[0])), find((v, f))
                    if a != b:
                        parent[a] = b
        # Maya's mesh vertexNormalMethod default "Angle and Area Weighted": corner angle x face area
        fan = {}
        for f, (s, t) in enumerate(zip(starts, totals)):
            for k in range(t):
                v = self.co[lv[s + k]]
                e1 = _sub(self.co[lv[s + (k + 1) % t]], v)
                e2 = _sub(self.co[lv[s + (k - 1) % t]], v)
                l1, l2 = math.sqrt(_dot(e1, e1)), math.sqrt(_dot(e2, e2))
                cosa = _dot(e1, e2) / (l1 * l2) if l1 * l2 > 0 else 1.0
                w = math.acos(max(-1.0, min(1.0, cosa))) * area[f]
                key = find((lv[s + k], f))
                acc = fan.setdefault(key, [0.0, 0.0, 0.0])
                for i in range(3):
                    acc[i] += fn[f][i] * w
        for acc in fan.values():
            ln = math.sqrt(_dot(acc, acc)) or 1.0
            acc[:] = [c / ln for c in acc]
        # Maya triangulation; n-gons use Blender's triangles (Maya's n-gon rule is unknown)
        tris, tri_normals, tri_faces = [], [], []
        ngon_tris = {}
        if any(t > 4 for t in totals):
            mesh.calc_loop_triangles()
            for lt in mesh.loop_triangles:
                ngon_tris.setdefault(lt.polygon_index, []).append(tuple(lt.loops))
        for f, (s, t) in enumerate(zip(starts, totals)):
            if t == 3:
                corner_sets = [(s, s + 1, s + 2)]
            elif t == 4:
                q = [self.co[lv[s + k]] for k in range(4)]
                corner_sets = [tuple(s + k for k in tri) for tri in quad_split(q)]
            else:
                corner_sets = ngon_tris.get(f, [])
            for corners in corner_sets:
                tris.append(tuple(lv[c] for c in corners))
                tri_normals.append(tuple(tuple(fan[find((lv[c], f))]) for c in corners))
                tri_faces.append(f)
        self.tris, self.tri_normals, self.tri_faces = tris, tri_normals, tri_faces
        self.bvh = BVHTree.FromPolygons(self.co, tris, all_triangles=True) if tris else None

    def normal(self, p):
        """Maya's interpolated normal at the closest point of the surface to world point ``p`` (None without faces)."""
        if self.bvh is None:
            return None
        hit = self.bvh.find_nearest(Vector(p))
        if hit[2] is None:
            return None
        cands = {hit[2]}
        for h in self.bvh.find_nearest_range(Vector(p), hit[3] * (1 + 1e-5) + 1e-6):
            cands.add(h[2])
        found = []
        for i in cands:             # BVH distances are single precision: settle near ties in double
            a, b, c = (self.co[v] for v in self.tris[i])
            bc = closest_on_triangle(p, a, b, c)
            q = _point(bc, a, b, c)
            found.append((_dot(_sub(p, q), _sub(p, q)), i, bc))
        dmin = min(f[0] for f in found)
        # a point on a shared edge / corner: Maya took the higher face index (hard sphere ridge)
        _d, i, bc = max((f for f in found if f[0] <= dmin * (1 + 1e-9) + 1e-18),
                        key=lambda f: (self.tri_faces[f[1]], -f[0]))
        ns = self.tri_normals[i]
        n = [bc[0] * ns[0][k] + bc[1] * ns[1][k] + bc[2] * ns[2][k] for k in range(3)]
        ln = math.sqrt(_dot(n, n))
        return tuple(c / ln for c in n) if ln > 1e-15 else None


# --- Maya curve tangent on a Blender curve ------------------------------------------------------------

def _domain(c):
    k, d = c.knots, c.degree
    return k[d - 1], k[len(k) - d]


def _curve_ders(c, u):
    from . import curves_math as cm
    cvs, knots, deg, w = c.math()
    if w is None:
        return (cm.evaluate(cvs, knots, deg, u), cm.evaluate(cvs, knots, deg, u, deriv=1),
                cm.evaluate(cvs, knots, deg, u, deriv=2) if deg > 1 else (0.0, 0.0, 0.0))
    h = 1e-5
    a, b = _domain(c)
    lo, hi = max(a, u - h), min(b, u + h)
    p0, p, p1 = (cm.evaluate(cvs, knots, deg, x, w) for x in (lo, u, hi))
    d1 = tuple((p1[i] - p0[i]) / (hi - lo) for i in range(3))
    d2 = tuple((p1[i] - 2 * p[i] + p0[i]) / ((hi - lo) / 2) ** 2 for i in range(3))
    return p, d1, d2


def closest_param(c, p):
    """Maya parameter of the closest point of MCurve ``c`` to ``p`` (coarse samples + Newton, clamped / wrapped)."""
    a, b = _domain(c)
    spans = max(1, len(c.cvs) - c.degree)
    n = 48 * spans
    coarse = []
    for i in range(n + 1):
        u = a + (b - a) * i / n
        q = _curve_ders(c, u)[0]
        coarse.append((_dot(_sub(q, p), _sub(q, p)), u))
    coarse.sort()
    best = None
    for _d0, u in coarse[:4]:
        for _it in range(60):
            q, d1, d2 = _curve_ders(c, u)
            r = _sub(q, p)
            f = _dot(r, d1)
            fp = _dot(d1, d1) + _dot(r, d2)
            if abs(fp) < 1e-300:
                break
            du = -f / fp
            nu = u + du
            if c.periodic:
                nu = a + (nu - a) % (b - a)
            else:
                nu = min(b, max(a, nu))
            if abs(nu - u) < 1e-14:
                u = nu
                break
            u = nu
        q = _curve_ders(c, u)[0]
        d = _dot(_sub(q, p), _sub(q, p))
        if best is None or d < best[0]:
            best = (d, u)
    return best[1]


class CurveData:
    def __init__(self, ob):
        from . import curves_maya
        self.curves = [curves_maya.read_spline(sp, ob.matrix_world) for sp in ob.data.splines
                       if len(sp.points) + len(sp.bezier_points) >= 2]

    def tangent(self, p):
        best = None
        for c in self.curves:
            u = closest_param(c, p)
            q, d1, _d2 = _curve_ders(c, u)
            d = _dot(_sub(q, p), _sub(q, p))
            if best is None or d < best[0]:
                best = (d, d1)
        if best is None:
            return None
        t = best[1]
        ln = math.sqrt(_dot(t, t))
        return tuple(x / ln for x in t) if ln > 1e-15 else None
