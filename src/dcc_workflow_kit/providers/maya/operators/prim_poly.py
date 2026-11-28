# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya polygon primitives as data: ``poly_cube``, ``poly_sphere``, ``poly_cylinder``, ``poly_cone``, ``poly_torus``,
``poly_plane``, ``poly_pyramid``, ``poly_prism`` build a ``Mesh`` (points, faces, UVs, hard edges, Maya's edge order
where known) from a node's attribute values in Maya's Y-up space and units. Also the small vector helpers
(``_rot_to``, ``_apply``, ``_orient``, ``_lerp``) the other prim_* builders share; prim_shapes.build picks a builder."""

import math

from .prim_nodes import ALL, Mesh


# --- small vector helpers ---------------------------------------------------------------------------------

def _rot_to(axis):
    """3x3 rotation taking Maya +Y to ``axis`` (shortest arc)."""
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-12:
        return None
    x, y, z = x / n, y / n, z / n
    if y > 1 - 1e-12:
        return None
    if y < -1 + 1e-12:
        return ((1, 0, 0), (0, -1, 0), (0, 0, -1))
    kx, kz = z, -x   # rotation axis Y x a = (z, 0, -x), angle acos(y)
    s = math.sqrt(kx * kx + kz * kz)
    kx, kz = kx / s, kz / s
    c, sn = y, s
    t = 1 - c
    return ((t * kx * kx + c, -sn * kz, t * kx * kz),
            (sn * kz, c, -sn * kx),
            (t * kx * kz, sn * kx, t * kz * kz + c))


def _apply(m, p):
    return (m[0][0] * p[0] + m[0][1] * p[1] + m[0][2] * p[2],
            m[1][0] * p[0] + m[1][1] * p[1] + m[1][2] * p[2],
            m[2][0] * p[0] + m[2][1] * p[1] + m[2][2] * p[2])


def _orient(verts, a, offset=(0.0, 0.0, 0.0)):
    m = _rot_to((a.get("axisX", 0.0), a.get("axisY", 1.0), a.get("axisZ", 0.0)))
    if m is not None:
        verts = [_apply(m, p) for p in verts]
    if any(offset):
        verts = [(p[0] + offset[0], p[1] + offset[1], p[2] + offset[2]) for p in verts]
    return verts


def _ring(n, r, y):
    """Maya's ring order: vertex i at angle -(i + 1) * 360 / n in (x, z)."""
    out = []
    for i in range(n):
        t = -2 * math.pi * (i + 1) / n
        out.append((r * math.cos(t), y, r * math.sin(t)))
    return out


def _edges_of(faces):
    out = set()
    for f in faces:
        for i in range(len(f)):
            out.add(frozenset((f[i], f[i - 1])))
    return out


def _lerp(p, q, t):
    return tuple(a + (b - a) * t for a, b in zip(p, q))


# --- polygon primitives  ---------------------------------------------------------------------------------

def poly_cube(a):
    w, h, d = a["width"], a["height"], a["depth"]
    sx, sy, sz = a["subdivisionsWidth"], a["subdivisionsHeight"], a["subdivisionsDepth"]
    verts, index = [], {}

    def vid(p):
        key = tuple(round(c, 7) for c in p)
        if key not in index:
            index[key] = len(verts)
            verts.append(p)
        return index[key]

    faces, uvs = [], []
    # Maya's cross layout, menu Create UVs = Normalize Collectively and Preserve Aspect Ratio: 0.25 squares,
    # columns 0.125 / 0.375 / 0.625 / 0.875
    c_, c0, c1, c2 = 0.125, 0.375, 0.625, 0.875
    # side: (origin, u axis, v axis, nu, nv, uv rect (u0, v0, u1, v1))
    sides = (
        ((-w / 2, -h / 2, d / 2), (w, 0, 0), (0, h, 0), sx, sy, (c0, 0.0, c1, 0.25)),        # front +Z
        ((-w / 2, h / 2, d / 2), (w, 0, 0), (0, 0, -d), sx, sz, (c0, 0.25, c1, 0.5)),       # top +Y
        ((-w / 2, h / 2, -d / 2), (w, 0, 0), (0, -h, 0), sx, sy, (c0, 0.5, c1, 0.75)),      # back -Z
        ((-w / 2, -h / 2, -d / 2), (w, 0, 0), (0, 0, d), sx, sz, (c0, 0.75, c1, 1.0)),      # bottom -Y
        ((w / 2, -h / 2, d / 2), (0, 0, -d), (0, h, 0), sz, sy, (c1, 0.0, c2, 0.25)),       # right +X
        ((-w / 2, -h / 2, -d / 2), (0, 0, d), (0, h, 0), sz, sy, (c_, 0.0, c0, 0.25)),      # left -X
    )
    for side, (o, du, dv, nu, nv, (u0, v0, u1, v1)) in enumerate(sides):
        # Maya walks the right side (+X) from the back (15 / 15 polyCube sizes): its interior vertices
        # and faces come back to front
        cols = list(range(nu + 1))[::-1] if side == 4 else list(range(nu + 1))
        grid = [{} for _ in range(nv + 1)]
        for j in range(nv + 1):
            for i in cols:
                grid[j][i] = vid((o[0] + du[0] * i / nu + dv[0] * j / nv, o[1] + du[1] * i / nu + dv[1] * j / nv,
                                  o[2] + du[2] * i / nu + dv[2] * j / nv))
        for j in range(nv):
            for i in cols[1:] if side == 4 else cols[:-1]:
                faces.append([grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]])
                uvs.append([(u0 + (u1 - u0) * i / nu, v0 + (v1 - v0) * j / nv),
                            (u0 + (u1 - u0) * (i + 1) / nu, v0 + (v1 - v0) * j / nv),
                            (u0 + (u1 - u0) * (i + 1) / nu, v0 + (v1 - v0) * (j + 1) / nv),
                            (u0 + (u1 - u0) * i / nu, v0 + (v1 - v0) * (j + 1) / nv)])
    hard = set()
    for f in faces:   # Maya: the cube's 12 box edges are hard, the subdivision edges soft
        for i in range(len(f)):
            p, q = verts[f[i]], verts[f[i - 1]]
            on = sum(1 for k, half in enumerate((w / 2, h / 2, d / 2))
                     if abs(abs(p[k]) - half) < 1e-7 and abs(abs(q[k]) - half) < 1e-7 and p[k] * q[k] > 0)
            if on >= 2:
                hard.add(frozenset((f[i], f[i - 1])))
    return Mesh(_orient(_shifted(verts, _baseline(a, h / 2)), a), faces, uvs, hard,
                _cube_edges(index, w, h, d, sx, sy, sz))


def _cube_edges(index, w, h, d, sx, sy, sz):
    """polyCube's edge ids (15 / 15 sizes edge for edge): the
    2 x (Height + Depth) vertex rows around the front / top / back / bottom, first the Width edges along each row,
    then the edges from each row to the next; then per side cap (+X, then -X) its inner rows (bottom to top, back to
    front), then its inner columns (rows of cells bottom to top, columns back to front)."""
    def at(x, y, z):
        return index[tuple(round(c, 7) for c in (x, y, z))]

    rows = 2 * (sy + sz)
    out = [(r * (sx + 1) + i, r * (sx + 1) + i + 1) for r in range(rows) for i in range(sx)]
    out += [(r * (sx + 1) + i, (r + 1) % rows * (sx + 1) + i) for r in range(rows) for i in range(sx + 1)]
    for x in (w / 2, -w / 2):
        def g(j, k):
            return at(x, -h / 2 + h * j / sy, -d / 2 + d * k / sz)
        out += [(g(j, k), g(j, k + 1)) for j in range(1, sy) for k in range(sz)]
        out += [(g(j, k), g(j + 1, k)) for j in range(sy) for k in range(1, sz)]
    return out


def poly_sphere(a):
    r, sx, sy = a["radius"], a["subdivisionsAxis"], a["subdivisionsHeight"]
    verts = []
    for k in range(1, sy):
        phi = -math.pi / 2 + math.pi * k / sy
        verts += _ring(sx, r * math.cos(phi), r * math.sin(phi))
    bottom, top = len(verts), len(verts) + 1
    verts += [(0.0, -r, 0.0), (0.0, r, 0.0)]
    faces, uvs = [], []
    for k in range(sy - 2):
        for i in range(sx):
            j = (i + 1) % sx
            faces.append([k * sx + i, k * sx + j, (k + 1) * sx + j, (k + 1) * sx + i])
            uvs.append([(i / sx, (k + 1) / sy), ((i + 1) / sx, (k + 1) / sy), ((i + 1) / sx, (k + 2) / sy),
                        (i / sx, (k + 2) / sy)])
    last = (sy - 2) * sx
    for i in range(sx):   # pole fans, "sawtooth" pole UVs (menu Create UVs = 2)
        j = (i + 1) % sx
        faces.append([j, i, bottom])
        uvs.append([((i + 1) / sx, 1 / sy), (i / sx, 1 / sy), ((i + 0.5) / sx, 0.0)])
    for i in range(sx):
        j = (i + 1) % sx
        faces.append([last + i, last + j, top])
        uvs.append([(i / sx, (sy - 1) / sy), ((i + 1) / sx, (sy - 1) / sy), ((i + 0.5) / sx, 1.0)])
    return Mesh(_orient(_shifted(verts, _baseline(a, r)), a), faces, uvs, _soft_by_angle(verts, faces))


def _cap(verts, faces, uvs, rim, centre_y, sc, r, top, uv_c, uv_r, dome=0.0, centre_dv=0.0):
    """A cylinder / cone / pyramid / prism cap on ring ``rim`` (vertex ids): an n-gon (sc 0) or ``sc`` rings with a
    centre fan. ``dome`` > 0: Maya Round Cap (rings on a hemisphere of radius ``dome``). UVs: a circle of
    radius ``uv_r`` around ``uv_c`` (u = x, v = z on the bottom cap and -z on the top one, menu Create UVs = Normalize
    and Preserve Aspect Ratio); Maya puts the centre vertex ``centre_dv`` lower."""
    n = len(rim)
    sign = 1 if top else -1
    rim_r = math.hypot(verts[rim[0]][0], verts[rim[0]][2]) or 1.0

    def cap_uv(p):
        if abs(p[0]) < 1e-12 and abs(p[2]) < 1e-12:
            return (uv_c[0], uv_c[1] - centre_dv)
        k = uv_r / rim_r
        return (uv_c[0] + k * p[0], uv_c[1] - sign * k * p[2])

    if sc == 0:
        f = list(rim) if top else list(reversed(rim))
        if not top:
            f = [rim[0]] + list(reversed(rim[1:]))
        faces.append(f)
        uvs.append([cap_uv(verts[v]) for v in f])
        return
    rings = [list(rim)]
    for c in range(sc - 1, 0, -1):
        if dome:
            ang = math.pi / 2 * (sc - c) / sc
            rr, yy = dome * math.cos(ang), centre_y + sign * dome * math.sin(ang)
        else:
            rr, yy = r * c / sc, centre_y
        start = len(verts)
        verts += _ring(n, rr, yy)
        rings.append(list(range(start, start + n)))
    centre = len(verts)
    verts.append((0.0, centre_y + sign * dome, 0.0))
    for outer, inner in zip(rings, rings[1:]):
        for i in range(n):
            j = (i + 1) % n
            f = [outer[i], outer[j], inner[j], inner[i]] if top else [outer[j], outer[i], inner[i], inner[j]]
            faces.append(f)
            uvs.append([cap_uv(verts[v]) for v in f])
    inner = rings[-1]
    for i in range(n):
        j = (i + 1) % n
        f = [inner[i], inner[j], centre] if top else [inner[j], inner[i], centre]
        faces.append(f)
        uvs.append([cap_uv(verts[v]) for v in f])


# Menu UV layout (Create UVs = Normalize and Preserve Aspect Ratio): sides in u 0.375..0.625,
# v 0.3125..0.68844; caps circles of radius 0.15625 around v 0.15625 / 0.84375
SIDE_U, SIDE_V = (0.375, 0.625), (0.3125, 0.68844)
CAP_R, CAP_V, CAP_DV = 0.15625, (0.15625, 0.84375), 0.00625


def cylinder_heights(a):
    """(side height, y shift) of polyCylinder: Round Cap Height Compensation keeps the round caps inside Height
    (the side gets 2 x radius shorter); Height Baseline moves the shape by -baseline x half its whole height
    (-1 = bottom on the origin, 1 = top on the origin)."""
    h, sc = a["height"], a["subdivisionsCaps"]
    dome = a["radius"] if a.get("roundCap") and sc > 0 else 0.0
    if dome and a.get("roundCapHeightCompensation"):
        h = max(h - 2.0 * dome, 0.0)
    return h, -a.get("heightBaseline", 0.0) * (h + 2.0 * dome) / 2.0


def _baseline(a, half):
    """Height Baseline shift along the build axis: -baseline x ``half`` (half the shape's extent on that axis)."""
    return -a.get("heightBaseline", 0.0) * half


def _shifted(verts, dy):
    return verts if not dy else [(x, y + dy, z) for x, y, z in verts]


def poly_cylinder(a):
    r, sx, sy, sc = a["radius"], a["subdivisionsAxis"], a["subdivisionsHeight"], a["subdivisionsCaps"]
    h, dy = cylinder_heights(a)
    dome = r if a.get("roundCap") and sc > 0 else 0.0
    if sc == 0:
        return _cylinder_ngon_caps(a, r, h, sx, sy, dy)
    # Maya stacks every ring from the bottom cap's innermost up the side to the top cap's innermost, then the two
    # centres (24 / 24 polyCylinder sizes with Subdivisions Caps >= 1, round caps 4 / 4)
    rings = []          # (radius, y, part): part -1 bottom cap, 0 side, 1 top cap
    for c in range(1, sc):
        rings.append(_cap_ring(r, -h / 2, sc, c, -1, dome) + (-1,))
    rings += [(r, -h / 2 + h * j / sy, 0) for j in range(sy + 1)]
    for c in range(sc - 1, 0, -1):
        rings.append(_cap_ring(r, h / 2, sc, c, 1, dome) + (1,))
    verts = []
    for rr, yy, _part in rings:
        verts += _ring(sx, rr, yy)
    c0, c1 = len(verts), len(verts) + 1
    verts += [(0.0, -h / 2 - dome, 0.0), (0.0, h / 2 + dome, 0.0)]
    rim0, rim1 = sc - 1, sc - 1 + sy          # the rim rings
    uv_bottom = _cap_uv(r, False, (0.5, CAP_V[0]), CAP_R, CAP_DV)
    uv_top = _cap_uv(r, True, (0.5, CAP_V[1]), CAP_R, CAP_DV)
    faces, uvs, side = [], [], []
    for q in range(len(rings) - 1):
        for i in range(sx):
            k = (i + 1) % sx
            f = [q * sx + i, q * sx + k, (q + 1) * sx + k, (q + 1) * sx + i]
            if rim0 <= q < rim1:
                j = q - rim0
                side.append(len(faces))
                uvs.append([_side_uv(i, j, sx, sy), _side_uv(i + 1, j, sx, sy), _side_uv(i + 1, j + 1, sx, sy),
                            _side_uv(i, j + 1, sx, sy)])
            else:
                uvs.append([(uv_bottom if q < rim0 else uv_top)(verts[v]) for v in f])
            faces.append(f)
    last = (len(rings) - 1) * sx
    for i in range(sx):
        f = [(i + 1) % sx, i, c0]
        faces.append(f)
        uvs.append([uv_bottom(verts[v]) for v in f])
    for i in range(sx):
        f = [last + i, last + (i + 1) % sx, c1]
        faces.append(f)
        uvs.append([uv_top(verts[v]) for v in f])
    hard = set()
    if not dome:
        for i in range(sx):   # the cap rims are hard, the sides soft unless facetted
            hard.add(frozenset((rim0 * sx + i, rim0 * sx + (i + 1) % sx)))
            hard.add(frozenset((rim1 * sx + i, rim1 * sx + (i + 1) % sx)))
    hard |= _soft_by_angle(verts, [faces[i] for i in side])
    return Mesh(_orient(_shifted(verts, dy), a), faces, uvs, hard, _cylinder_edges(len(rings), sx, (c0, c1)))


def _cylinder_ngon_caps(a, r, h, sx, sy, dy=0.0):
    verts = []
    for j in range(sy + 1):
        verts += _ring(sx, r, -h / 2 + h * j / sy)
    faces, uvs = [], []
    for j in range(sy):
        for i in range(sx):
            k = (i + 1) % sx
            faces.append([j * sx + i, j * sx + k, (j + 1) * sx + k, (j + 1) * sx + i])
            uvs.append([_side_uv(i, j, sx, sy), _side_uv(i + 1, j, sx, sy), _side_uv(i + 1, j + 1, sx, sy),
                        _side_uv(i, j + 1, sx, sy)])
    side = len(faces)
    _cap(verts, faces, uvs, list(range(sx)), -h / 2, 0, r, False, (0.5, CAP_V[0]), CAP_R, 0.0, CAP_DV)
    _cap(verts, faces, uvs, list(range(sy * sx, sy * sx + sx)), h / 2, 0, r, True, (0.5, CAP_V[1]), CAP_R, 0.0,
         CAP_DV)
    hard = set()
    for i in range(sx):   # the cap rims are hard, the sides soft unless facetted
        hard.add(frozenset((i, (i + 1) % sx)))
        hard.add(frozenset((sy * sx + i, sy * sx + (i + 1) % sx)))
    hard |= _soft_by_angle(verts, faces[:side])
    return Mesh(_orient(_shifted(verts, dy), a), faces, uvs, hard, _cylinder_edges(sy + 1, sx, None))


def _cap_ring(r, centre_y, sc, c, sign, dome):
    """(radius, y) of cap ring ``c`` (sc - c rings in from the rim), as ``_cap`` places it."""
    if dome:
        ang = math.pi / 2 * (sc - c) / sc
        return dome * math.cos(ang), centre_y + sign * dome * math.sin(ang)
    return r * c / sc, centre_y


def _cap_uv(rim_r, top, uv_c, uv_r, centre_dv):
    """``_cap``'s UV rule as a function of the position (``rim_r`` = the rim's radius)."""
    sign = 1 if top else -1
    rim_r = rim_r or 1.0

    def uv(p):
        if abs(p[0]) < 1e-12 and abs(p[2]) < 1e-12:
            return (uv_c[0], uv_c[1] - centre_dv)
        k = uv_r / rim_r
        return (uv_c[0] + k * p[0], uv_c[1] - sign * k * p[2])
    return uv


def _cylinder_edges(nrings, sx, centres):
    """polyCylinder's edge ids (36 / 36 sizes + 4 round caps, edge for edge): every ring's edges ring by
    ring, then the edges from each ring to the next, then the bottom centre's spokes (centre first) and the top
    centre's (centre last)."""
    out = [(q * sx + i, q * sx + (i + 1) % sx) for q in range(nrings) for i in range(sx)]
    out += [(q * sx + i, (q + 1) * sx + i) for q in range(nrings - 1) for i in range(sx)]
    if centres:
        out += [(centres[0], i) for i in range(sx)]
        out += [((nrings - 1) * sx + i, centres[1]) for i in range(sx)]
    return out


def _side_uv(i, j, n, rows):
    return (SIDE_U[0] + (SIDE_U[1] - SIDE_U[0]) * i / n, SIDE_V[0] + (SIDE_V[1] - SIDE_V[0]) * j / rows)


def poly_cone(a):
    r, h, sx, sy, sc = a["radius"], a["height"], a["subdivisionsAxis"], a["subdivisionsHeight"], a["subdivisionsCap"]
    dome = r if a.get("roundCap") and sc > 0 else 0.0
    verts = []
    for j in range(sy):
        verts += _ring(sx, r * (1 - j / sy), -h / 2 + h * j / sy)
    faces, uvs = [], []

    def side_uv(i, j):   # menu UVs: side fan u 0.25..0.75 at the base, apex (0.5, 1); base circle r 0.25
        return (0.5 + (i / sx - 0.5) * 0.5 * (1 - j / sy), 0.5 + 0.5 * j / sy)

    for j in range(sy - 1):
        for i in range(sx):
            k = (i + 1) % sx
            faces.append([j * sx + i, j * sx + k, (j + 1) * sx + k, (j + 1) * sx + i])
            uvs.append([side_uv(i, j), side_uv(i + 1, j), side_uv(i + 1, j + 1), side_uv(i, j + 1)])
    _cap(verts, faces, uvs, list(range(sx)), -h / 2, sc, r, False, (0.5, 0.25), 0.25, dome)
    apex = len(verts)
    verts.append((0.0, h / 2, 0.0))
    last = (sy - 1) * sx
    for i in range(sx):
        k = (i + 1) % sx
        faces.append([last + i, last + k, apex])
        uvs.append([side_uv(i, sy - 1), side_uv(i + 1, sy - 1), (0.5, 1.0)])
    hard = set() if dome else {frozenset((i, (i + 1) % sx)) for i in range(sx)}
    hard |= {frozenset((last + i, apex)) for i in range(sx)}   # Maya keeps the apex edges hard
    return Mesh(_orient(_shifted(verts, _baseline(a, h / 2)), a), faces, uvs, hard)


def poly_torus(a):
    R, sr, tw = a["radius"], a["sectionRadius"], math.radians(a["twist"])
    sx, sy = a["subdivisionsAxis"], a["subdivisionsHeight"]
    verts = []
    for j in range(sy):
        phi = tw + 2 * math.pi * j / sy
        verts += _ring(sx, R - sr * math.cos(phi), sr * math.sin(phi))
    faces, uvs = [], []
    for j in range(sy):
        jn = (j + 1) % sy
        for i in range(sx):
            k = (i + 1) % sx
            faces.append([j * sx + k, j * sx + i, jn * sx + i, jn * sx + k])
            uvs.append([((i + 1) / sx, 1 - j / sy), (i / sx, 1 - j / sy), (i / sx, 1 - (j + 1) / sy),
                        ((i + 1) / sx, 1 - (j + 1) / sy)])
    return Mesh(_orient(_shifted(verts, _baseline(a, sr)), a), faces, uvs, _soft_by_angle(verts, faces))


def poly_plane(a):
    w, h, sx, sy = a["width"], a["height"], a["subdivisionsWidth"], a["subdivisionsHeight"]
    verts = [(-w / 2 + w * i / sx, 0.0, h / 2 - h * j / sy) for j in range(sy + 1) for i in range(sx + 1)]
    faces, uvs = [], []
    big = max(w, h) or 1.0
    su, sv = w / big, h / big   # menu Create UVs = Normalize and Preserve Aspect Ratio
    for j in range(sy):
        for i in range(sx):
            v0 = j * (sx + 1) + i
            faces.append([v0, v0 + 1, v0 + sx + 2, v0 + sx + 1])
            uvs.append([(su * i / sx, sv * j / sy), (su * (i + 1) / sx, sv * j / sy),
                        (su * (i + 1) / sx, sv * (j + 1) / sy), (su * i / sx, sv * (j + 1) / sy)])
    dz = -_baseline(a, h / 2)   # the plane's Height runs along Z: -1 puts its -Z edge on the origin
    if dz:
        verts = [(x, y, z + dz) for x, y, z in verts]
    return Mesh(_orient(verts, a), faces, uvs, ())


def _apex_uv(i, j, n, rows):
    """Cone / pyramid side UVs (menu layout): a fan from u 0.25..0.75 at v 0.5 to the apex (0.5, 1)."""
    return (0.5 + (i / n - 0.5) * 0.5 * (1 - j / rows), 0.5 + 0.5 * j / rows)


def _ngon_solid(a, n, side, length, sh, sc, apex):
    """Pyramid (``apex``) / prism: Maya side-length based polygons."""
    R = side / (2 * math.sin(math.pi / n))
    verts, faces, uvs = [], [], []
    rows = sh if apex else sh + 1
    for j in range(rows):
        f = j / sh
        verts += _ring(n, R * (1 - f) if apex else R, -length / 2 + length * f)
    for j in range(rows - 1):
        for i in range(n):
            k = (i + 1) % n
            faces.append([j * n + i, j * n + k, (j + 1) * n + k, (j + 1) * n + i])
            if apex:
                uvs.append([_apex_uv(i, j, n, sh), _apex_uv(i + 1, j, n, sh), _apex_uv(i + 1, j + 1, n, sh),
                            _apex_uv(i, j + 1, n, sh)])
            else:
                uvs.append([_side_uv(i, j, n, sh), _side_uv(i + 1, j, n, sh), _side_uv(i + 1, j + 1, n, sh),
                            _side_uv(i, j + 1, n, sh)])
    if apex:
        _cap(verts, faces, uvs, list(range(n)), -length / 2, sc, R, False, (0.5, 0.25), 0.25)
        top = len(verts)
        verts.append((0.0, length / 2, 0.0))
        last = (rows - 1) * n
        for i in range(n):
            k = (i + 1) % n
            faces.append([last + i, last + k, top])
            uvs.append([_apex_uv(i, rows - 1, n, sh), _apex_uv(i + 1, rows - 1, n, sh), (0.5, 1.0)])
    else:
        _cap(verts, faces, uvs, list(range(n)), -length / 2, sc, R, False, (0.5, CAP_V[0]), CAP_R, 0.0, CAP_DV)
        _cap(verts, faces, uvs, list(range(sh * n, sh * n + n)), length / 2, sc, R, True, (0.5, CAP_V[1]), CAP_R,
             0.0, CAP_DV)
    return Mesh(_orient(verts, a), faces, uvs, ALL)


def poly_pyramid(a):
    n, s = a["numberOfSides"], a["sideLength"]
    R = s / (2 * math.sin(math.pi / n))
    height = math.sqrt(max(s * s - R * R, 0.0))   # equilateral side triangles
    return _ngon_solid(a, n, s, height, a["subdivisionsHeight"], a["subdivisionsCaps"], True)


def poly_prism(a):
    return _ngon_solid(a, a["numberOfSides"], a["sideLength"], a["length"], a["subdivisionsHeight"],
                       a["subdivisionsCaps"], False)


def _soft_by_angle(verts, faces, limit=55.0):
    """Edges Maya leaves hard on facetted round primitives: normals more than ~55 degrees apart (6-sided
    cylinders / spheres hard at 60, 20-sided soft, cone sides soft at 53)."""
    normals = []
    for f in faces:
        nx = ny = nz = 0.0
        for i in range(len(f)):
            p, q = verts[f[i - 1]], verts[f[i]]
            nx += (p[1] - q[1]) * (p[2] + q[2])
            ny += (p[2] - q[2]) * (p[0] + q[0])
            nz += (p[0] - q[0]) * (p[1] + q[1])
        n = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        normals.append((nx / n, ny / n, nz / n))
    owner = {}
    for fi, f in enumerate(faces):
        for i in range(len(f)):
            owner.setdefault(frozenset((f[i], f[i - 1])), []).append(fi)
    c = math.cos(math.radians(limit))
    hard = set()
    for e, fs in owner.items():
        if len(fs) == 2:
            a, b = normals[fs[0]], normals[fs[1]]
            if a[0] * b[0] + a[1] * b[1] + a[2] * b[2] < c:
                hard.add(e)
    return hard
