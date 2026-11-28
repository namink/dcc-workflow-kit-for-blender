# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya polyDisc and polyPlatonic as data: ``poly_disc`` (an n-sided disc in Quads / Triangles / Pie / Caps / Circle
subdivision) and ``poly_platonic`` (tetrahedron ... icosahedron, subdivided and inflated towards a sphere) return a
``Mesh``. ``_platonic_base`` is also the Soccer Ball's start (prim_shapes_more.py). Pure Python."""

import math

from .prim_nodes import ALL, Mesh
from .prim_poly import _lerp


# --- polyDisc  ------------------------------------------------------------------------------------------

def _polygon(n, r):
    """polyDisc corners in (x, z): corner i at 90 + 180 / n - 360 i / n degrees (n = 3 -> (-0.866, 0.5),
    (0.866, 0.5), (0, -1))."""
    out = []
    for i in range(n):
        t = math.pi / 2 + math.pi / n - 2 * math.pi * i / n
        out.append((r * math.cos(t), r * math.sin(t)))
    return out


class _Builder:
    def __init__(self):
        self.verts, self.faces, self.index = [], [], {}

    def v(self, p):
        key = tuple(round(c, 7) for c in p)
        if key not in self.index:
            self.index[key] = len(self.verts)
            self.verts.append(tuple(p))
        return self.index[key]


def _disc_2d(n, mode, sub, r):
    """polyDisc in (x, z): list of 2D points and faces."""
    corners = _polygon(n, r)
    b = _Builder()
    centre = (0.0, 0.0)
    if mode in (0, 4):
        if sub == 0:
            b.faces.append([b.v(c) for c in corners])
            return b
        g = 2 ** (sub - 1)
        for i in range(n):
            c, nxt, prv = corners[i], corners[(i + 1) % n], corners[i - 1]
            m1, m0 = _lerp(c, nxt, 0.5), _lerp(prv, c, 0.5)
            # kite c -> m1 -> centre -> m0, bilinear g x g
            for y in range(g):
                for x in range(g):
                    def pt(s, t):
                        a0 = _lerp(m0, c, s)
                        a1 = _lerp(centre, m1, s)
                        return _lerp(a0, a1, t)
                    quad = [pt((x) / g, y / g), pt((x + 1) / g, y / g), pt((x + 1) / g, (y + 1) / g),
                            pt(x / g, (y + 1) / g)]
                    b.faces.append([b.v(p) for p in quad])
        if mode == 4:   # Circle: kites rebuilt as Coons patches between circle arcs and straight spokes
            b = _Builder()
            step = 2 * math.pi / n
            for i in range(n):
                ca = math.atan2(corners[i][1], corners[i][0])
                m0a, m1a = ca + step / 2, ca - step / 2   # corner order runs clockwise: next corner at ca - step

                def arc(t0, t1, u):
                    t = t0 + (t1 - t0) * u
                    return (r * math.cos(t), r * math.sin(t))

                def spoke(t, u):
                    return (r * u * math.cos(t), r * u * math.sin(t))

                c, m1, m0 = corners[i], (r * math.cos(m1a), r * math.sin(m1a)), (r * math.cos(m0a), r * math.sin(m0a))

                def pt(s_, t_):
                    # s_: m0 -> c (bottom) and centre -> m1 (top); t_: bottom -> top
                    bottom = arc(m0a, ca, s_)
                    top = spoke(m1a, s_)
                    left = spoke(m0a, 1 - t_)
                    right = arc(ca, m1a, t_)
                    bl = tuple(m0[k] * (1 - s_) * (1 - t_) + c[k] * s_ * (1 - t_) + 0.0 * (1 - s_) * t_ + m1[k] * s_ * t_
                               for k in range(2))
                    return tuple((1 - t_) * bottom[k] + t_ * top[k] + (1 - s_) * left[k] + s_ * right[k] - bl[k]
                                 for k in range(2))
                for y in range(g):
                    for x in range(g):
                        quad = [pt(x / g, y / g), pt((x + 1) / g, y / g), pt((x + 1) / g, (y + 1) / g),
                                pt(x / g, (y + 1) / g)]
                        b.faces.append([b.v(p) for p in quad])
        return b
    if mode == 3:   # Caps: sub + 1 concentric rings, centre fan
        rings = sub + 1
        for k in range(rings):
            s0, s1 = 1 - k / rings, 1 - (k + 1) / rings
            for i in range(n):
                j = (i + 1) % n
                a0, a1 = _lerp(centre, corners[i], s0), _lerp(centre, corners[j], s0)
                if k == rings - 1:
                    b.faces.append([b.v(a0), b.v(a1), b.v(centre)])
                else:
                    b.faces.append([b.v(a0), b.v(a1), b.v(_lerp(centre, corners[j], s1)),
                                    b.v(_lerp(centre, corners[i], s1))])
        return b
    if mode == 1 and n == 3:   # Triangles on a triangle: the triangle itself on a (sub + 1) grid
        _tri_grid(b, corners[0], corners[1], corners[2], sub + 1)
        return b
    tris = [(corners[i], corners[(i + 1) % n], centre) for i in range(n)]
    if mode == 1:
        for t in tris:
            _tri_grid(b, t[0], t[1], t[2], max(sub, 1))
        return b
    # Pie: fan, then (sub - 1) centroid splits
    for _ in range(max(sub, 1) - 1):
        tris = [s for t in tris for s in _centroid_split(t)]
    for t in tris:
        b.faces.append([b.v(p) for p in t])
    return b


def _tri_grid(b, p0, p1, p2, g):
    def pt(i, j):   # i along p0->p1, j along p0->p2
        return tuple(p0[k] + (p1[k] - p0[k]) * i / g + (p2[k] - p0[k]) * j / g for k in range(len(p0)))
    for j in range(g):
        for i in range(g - j):
            b.faces.append([b.v(pt(i, j)), b.v(pt(i + 1, j)), b.v(pt(i, j + 1))])
            if i + j + 1 < g:
                b.faces.append([b.v(pt(i + 1, j)), b.v(pt(i + 1, j + 1)), b.v(pt(i, j + 1))])


def _centroid_split(t):
    c = tuple(sum(p[k] for p in t) / 3 for k in range(len(t[0])))
    return [(t[0], t[1], c), (t[1], t[2], c), (t[2], t[0], c)]


def poly_disc(a):
    n, mode, sub, r = a["sides"], a["subdivisionMode"], a["subdivisions"], a["radius"]
    b = _disc_2d(n, mode, sub, r)
    verts = [(x, 0.0, z) for x, z in b.verts]
    faces = [list(reversed(f)) if _facing_down(verts, f) else f for f in b.faces]
    uvs = [[(0.5 + verts[v][0] / (2 * r or 1), 0.5 - verts[v][2] / (2 * r or 1)) for v in f] for f in faces]
    return Mesh(verts, faces, uvs, ())


def _facing_down(verts, f):
    s = 0.0
    for i in range(len(f)):
        p, q = verts[f[i - 1]], verts[f[i]]
        s += p[2] * q[0] - p[0] * q[2]
    return s < 0


# --- polyPlatonic  ----------------------------------------------------------------------------------------

def _platonic_base(kind):
    phi = (1 + math.sqrt(5)) / 2
    if kind == 0:   # tetrahedron, apex on +Z
        # Maya's tetrahedron: apex +Z, base ring at z = -0.5 (radius 0.866), not the regular -1/3
        k = math.sqrt(0.75)
        v = [(0, 0, 1)] + [(k * math.cos(t), k * math.sin(t), -0.5) for t in (0, 2 * math.pi / 3, -2 * math.pi / 3)]
        f = [[0, 1, 2], [1, 3, 2], [0, 2, 3], [0, 3, 1]]
    elif kind == 1:
        s = 1 / math.sqrt(3)
        v = [(s, s, s), (s, -s, s), (-s, -s, s), (-s, s, s), (s, s, -s), (s, -s, -s), (-s, -s, -s), (-s, s, -s)]
        f = [[0, 3, 2, 1], [7, 4, 5, 6], [2, 6, 5, 1], [0, 4, 7, 3], [2, 3, 7, 6], [1, 5, 4, 0]]
    elif kind == 2:
        v = [(0, 0, 1), (1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0), (0, 0, -1)]
        f = [[1, 2, 0], [2, 3, 0], [3, 4, 0], [0, 4, 1], [5, 2, 1], [5, 3, 2], [5, 4, 3], [5, 1, 4]]
    elif kind == 4:   # icosahedron, poles on Z
        z = 1 / math.sqrt(5)
        rr = 2 / math.sqrt(5)
        v = [(0, 0, -1)]
        v += [(rr * math.cos(math.radians(36 + 72 * k)), rr * math.sin(math.radians(36 + 72 * k)), -z) for k in range(5)]
        v += [(rr * math.cos(math.radians(72 * k)), rr * math.sin(math.radians(72 * k)), z) for k in range(5)]
        v += [(0, 0, 1)]
        f = [[0, 2, 1], [0, 3, 2], [0, 4, 3], [0, 5, 4], [0, 1, 5], [1, 2, 7], [2, 3, 8], [3, 4, 9], [4, 5, 10],
             [5, 1, 6], [1, 7, 6], [2, 8, 7], [3, 9, 8], [4, 10, 9], [5, 6, 10], [6, 7, 11], [7, 8, 11], [8, 9, 11],
             [9, 10, 11], [10, 6, 11]]
    else:   # dodecahedron: (+-1, +-1, +-1) and (0, +-1/phi, +-phi) cycles over sqrt(3), Maya's order
        q, g = 1 / phi, phi
        raw = [(0, -q, -g), (-q, -g, 0), (-g, 0, -q), (-1, -1, -1), (-1, -1, 1), (0, -q, g), (-q, g, 0), (-g, 0, q),
               (-1, 1, -1), (-1, 1, 1), (0, q, -g), (q, -g, 0), (g, 0, -q), (1, -1, -1), (1, -1, 1), (0, q, g),
               (q, g, 0), (g, 0, q), (1, 1, -1), (1, 1, 1)]
        s3 = math.sqrt(3)
        v = [(x / s3, y / s3, z / s3) for x, y, z in raw]
        f = []
        for nrm in [(0, g, 1), (0, g, -1), (0, -g, 1), (0, -g, -1), (g, 1, 0), (g, -1, 0), (-g, 1, 0), (-g, -1, 0),
                    (1, 0, g), (1, 0, -g), (-1, 0, g), (-1, 0, -g)]:
            five = sorted(range(20), key=lambda i: -sum(v[i][k] * nrm[k] for k in range(3)))[:5]
            cx = [sum(v[i][k] for i in five) / 5 for k in range(3)]
            ref = [v[five[0]][k] - cx[k] for k in range(3)]
            ref2 = (nrm[1] * ref[2] - nrm[2] * ref[1], nrm[2] * ref[0] - nrm[0] * ref[2],
                    nrm[0] * ref[1] - nrm[1] * ref[0])

            def ang(i, ref=ref, ref2=ref2, cx=cx):
                d = [v[i][k] - cx[k] for k in range(3)]
                return math.atan2(sum(d[k] * ref2[k] for k in range(3)), sum(d[k] * ref[k] for k in range(3)))
            f.append(sorted(five, key=ang))
    return [tuple(float(c) for c in p) for p in v], f


def poly_platonic(a):
    kind, mode, sub, r, infl = (a["primitive"], a["subdivisionMode"], a["subdivisions"], a["radius"],
                                a["sphericalInflation"])
    base_v, base_f = _platonic_base(kind)
    b = _Builder()
    polys = [[base_v[i] for i in f] for f in base_f]
    if mode == 3:   # Caps: sub + 1 rings per face, centre fan
        for p in polys:
            n = len(p)
            c = tuple(sum(q[k] for q in p) / n for k in range(3))
            rings = sub + 1
            for k in range(rings):
                s0, s1 = 1 - k / rings, 1 - (k + 1) / rings
                for i in range(n):
                    j = (i + 1) % n
                    a0, a1 = _lerp(c, p[i], s0), _lerp(c, p[j], s0)
                    if k == rings - 1:
                        b.faces.append([b.v(a0), b.v(a1), b.v(c)])
                    else:
                        b.faces.append([b.v(a0), b.v(a1), b.v(_lerp(c, p[j], s1)), b.v(_lerp(c, p[i], s1))])
    elif sub == 0:
        for p in polys:
            b.faces.append([b.v(q) for q in p])
    elif mode == 0:   # Quads: each n-gon -> n quads, then each quad -> 4 per further level
        quads = []
        for p in polys:
            n = len(p)
            c = tuple(sum(q[k] for q in p) / n for k in range(3))
            for i in range(n):
                quads.append([p[i], _lerp(p[i], p[(i + 1) % n], 0.5), c, _lerp(p[i - 1], p[i], 0.5)])
        for _ in range(sub - 1):
            nq = []
            for q in quads:
                c = tuple(sum(x[k] for x in q) / 4 for k in range(3))
                m = [_lerp(q[i], q[(i + 1) % 4], 0.5) for i in range(4)]
                for i in range(4):
                    nq.append([q[i], m[i], c, m[i - 1]])
            quads = nq
        for q in quads:
            b.faces.append([b.v(x) for x in q])
    elif mode == 1:   # Triangles: n-gons fan first, then midpoint splits
        tris, levels = [], sub
        for p in polys:
            if len(p) == 3:
                tris.append(tuple(p))
            else:
                c = tuple(sum(q[k] for q in p) / len(p) for k in range(3))
                tris += [(p[i], p[(i + 1) % len(p)], c) for i in range(len(p))]
        if any(len(p) > 3 for p in polys):
            levels -= 1
        for _ in range(levels):
            nt = []
            for t in tris:
                m = [_lerp(t[i], t[(i + 1) % 3], 0.5) for i in range(3)]
                nt += [(t[0], m[0], m[2]), (m[0], t[1], m[1]), (m[2], m[1], t[2]), (m[0], m[1], m[2])]
            tris = nt
        for t in tris:
            b.faces.append([b.v(x) for x in t])
    else:   # Pie: centroid fan, then centroid splits
        tris = []
        for p in polys:
            c = tuple(sum(q[k] for q in p) / len(p) for k in range(3))
            tris += [(p[i], p[(i + 1) % len(p)], c) for i in range(len(p))]
        for _ in range(sub - 1):
            tris = [s for t in tris for s in _centroid_split(t)]
        for t in tris:
            b.faces.append([b.v(x) for x in t])
    verts = []
    for p in b.verts:
        n = math.sqrt(sum(x * x for x in p)) or 1.0
        s = (1 - infl) + infl / n
        verts.append(tuple(x * s * r for x in p))
    uvs = [[(0.5 + math.atan2(verts[v][2], verts[v][0]) / (2 * math.pi),
             0.5 + math.asin(max(-1.0, min(1.0, verts[v][1] / (r or 1)))) / math.pi) for v in f] for f in b.faces]
    return Mesh(verts, b.faces, uvs, ALL if sub == 0 else ())
