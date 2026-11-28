# SPDX-License-Identifier: GPL-3.0-or-later
"""Shape geometry of the Maya manipulator handles in arrow units (arrow length = 1), pure and testable headless: the
handle size constants, triangle / line builders (``_cone``, ``_box``, ``_ring``, ...), each handle's draw and pick
shapes (``shapes``) and the front half of a Rotate ring as the view sees it (``front_arcs``). Used by manipulator.py
(which re-exports these names), extrude_manipulator.py and universal_manip.py.
"""

import math

from mathutils import Vector

# Shape sizes in arrow units (Maya's Move / Scale manipulators).
CENTER_HALF = 0.083      # hollow centre square: 18 px
CONE_LEN, CONE_R = 0.13, 0.045
LINE_START = 0.0
# Plane handles: Maya's YZ / XY squares span 0.52-0.68
# arrow units along both axes: a 1 px rim in the
# axis colour around a translucent fill (pixels over the #767676 top face: red #b6655f, blue #5f63db).
PLANE_AT, PLANE_HALF = 0.60, 0.08
CUBE_AT, CUBE_HALF = 0.85, 0.05
CENTER_CUBE_HALF = 0.06
PIVOT_RING_R = 0.32      # pivot orientation rings
PICK_R = 0.05            # half width of the invisible pick shape around a thin line


# --- shape geometry (pure, testable headless) ---------------------------------------------------

def _square(cx, cy, half, z=0.0):
    a, b, c, d = ((cx - half, cy - half, z), (cx + half, cy - half, z),
                  (cx + half, cy + half, z), (cx - half, cy + half, z))
    return [a, b, c, a, c, d]


def _square_outline(half):
    pts = [(-half, -half, 0), (half, -half, 0), (half, half, 0), (-half, half, 0)]
    out = []
    for i in range(4):
        out += [pts[i], pts[(i + 1) % 4]]
    return out


def _cone(base, tip, r, n=12):
    import math
    tris = []
    ring = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        tris += [(x0, y0, base), (x1, y1, base), (0, 0, tip)]
        tris += [(x0, y0, base), (0, 0, base), (x1, y1, base)]
    return tris


def _box(c, half):
    """Triangles of an axis-aligned cube centred at ``c``."""
    x, y, z = c
    v = [(x + sx * half, y + sy * half, z + sz * half) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    faces = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
    tris = []
    for a, b, cc, d in faces:
        tris += [v[a], v[b], v[cc], v[a], v[cc], v[d]]
    return tris


def _bar(z0, z1, r):
    """Triangles of a thin square bar along +Z (pick shape of a line)."""
    return _box_span((-r, -r, z0), (r, r, z1))


def _box_span(lo, hi):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    v = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    faces = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
    tris = []
    for a, b, c, d in faces:
        tris += [v[a], v[b], v[c], v[a], v[c], v[d]]
    return tris


def _ring(r, n=64):
    import math
    pts = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n), 0.0) for i in range(n)]
    out = []
    for i in range(n):
        out += [pts[i], pts[(i + 1) % n]]
    return out


def _disc(r, n=48):
    import math
    pts = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n), 0.0) for i in range(n)]
    tris = []
    for i in range(n):
        tris += [(0, 0, 0), pts[i], pts[(i + 1) % n]]
    return tris


def _band(r, w, n=64):
    """Flat ring band (pick shape of a ring)."""
    import math
    tris = []
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        p = [((r - w) * math.cos(a0), (r - w) * math.sin(a0), 0), ((r + w) * math.cos(a0), (r + w) * math.sin(a0), 0),
             ((r + w) * math.cos(a1), (r + w) * math.sin(a1), 0), ((r - w) * math.cos(a1), (r - w) * math.sin(a1), 0)]
        tris += [p[0], p[1], p[2], p[0], p[2], p[3]]
    return tris


def shapes(kind):
    """(draw shapes [(type, verts)], pick shape (type, verts)) of a handle in arrow units.

    Axis handles point along local +Z; plane handles lie in the local XY plane; view-facing
    handles (centre, view ring, trackball) are in the local XY plane facing +Z."""
    if kind == 'ARROW':
        base = 1.0 - CONE_LEN
        return ([('LINES', [(0, 0, LINE_START), (0, 0, base)]), ('TRIS', _cone(base, 1.0, CONE_R))],
                ('TRIS', _bar(CENTER_HALF, base, PICK_R) + _cone(base, 1.0, CONE_R * 1.6)))
    if kind == 'SCALE_AXIS':
        return ([('LINES', [(0, 0, LINE_START), (0, 0, CUBE_AT - CUBE_HALF)]),
                 ('TRIS', _box((0, 0, CUBE_AT), CUBE_HALF))],
                ('TRIS', _bar(CENTER_HALF, CUBE_AT, PICK_R) + _box((0, 0, CUBE_AT), CUBE_HALF * 1.6)))
    if kind == 'PLANE':      # fill first, then the rim (ALLSET_GT_maya_handle.draw)
        rim = [(x + PLANE_AT, y + PLANE_AT, z) for x, y, z in _square_outline(PLANE_HALF)]
        return ([('TRIS', _square(PLANE_AT, PLANE_AT, PLANE_HALF)), ('LINES', rim)],
                ('TRIS', _square(PLANE_AT, PLANE_AT, PLANE_HALF * 1.4)))
    if kind == 'CENTER':
        return ([('LINES', _square_outline(CENTER_HALF))], ('TRIS', _square(0, 0, CENTER_HALF * 1.2)))
    if kind == 'CENTER_CUBE':
        return ([('TRIS', _box((0, 0, 0), CENTER_CUBE_HALF))], ('TRIS', _box((0, 0, 0), CENTER_CUBE_HALF * 1.4)))
    if kind == 'PIVOT_CENTER':
        return ([('LINES', _square_outline(CENTER_HALF)), ('LINES', _ring(CENTER_HALF * 0.55, 24))],
                ('TRIS', _square(0, 0, CENTER_HALF * 1.2)))
    if kind == 'PIVOT_RING':
        return ([('LINES', _ring(PIVOT_RING_R))], ('TRIS', _band(PIVOT_RING_R, PICK_R * 0.8)))
    raise ValueError(kind)


RING_STEPS = 72
RING_CLIP_BIAS = 0.02   # in ring radii: a ring facing the view stays whole


def front_arcs(matrix, view_z, steps=RING_STEPS):
    """World polylines of the front half of the unit circle in ``matrix``'s local XY plane: the points on the
    viewer's side of the plane through the ring centre facing ``view_z`` (the view's +Z, toward the viewer)."""
    centre = matrix.translation
    radius = (matrix.to_3x3() @ Vector((1.0, 0.0, 0.0))).length
    bias = -RING_CLIP_BIAS * radius
    arcs, run = [], []
    for i in range(steps + 1):
        a = 6.283185307179586 * i / steps
        p = matrix @ Vector((math.cos(a), math.sin(a), 0.0))
        if (p - centre).dot(view_z) >= bias:
            run.append(p)
        elif run:
            arcs.append(run)
            run = []
    if run:
        if arcs and len(arcs[0]) and (arcs[0][0] - run[-1]).length < 1e-9 * max(radius, 1.0):
            arcs[0] = run[:-1] + arcs[0]       # the run that wraps past angle 0
        else:
            arcs.append(run)
    return [arc for arc in arcs if len(arc) > 1]
