# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the ViewCube, its corner controls, the camera label and the axis triad go in a 3D View, without drawing:
sizes and colours, the cube's projection (``faces_2d``, ``cube_size``, ``layout``, ``triad``), control places and
hit tests (``control_layout``, ``hit_face``, ``_control_at``) and the camera label text (``label_for``).
Drawn by view_furniture_draw.py; view_furniture.py (the ViewCube gizmo) re-exports these names.
"""

import math

import bpy
from mathutils import Vector

# --- Maya sizes and colours -----------------------------------------------------
CUBE_PX = 65.0                 # ViewCube box in a 612 px tall Maya view
CUBE_INSET = (26.0, 27.0)      # from the right, from the top
MAYA_VIEW_H = 612.0
SMALL_EXP = 0.42               # 65 px in the 612 px view, 48 px in a four-view panel
LABEL_BASELINE = 9.0
LABEL_SHIFT = -9.0
LABEL_PX = 11.0
LABEL_RGB = (0.89, 0.89, 0.89)
TRIAD_INSET = 26.0
TRIAD_LEN = 13.0
CUBE_ALPHA = (0.5, 1.0)        # resting, under the mouse
CUBE_EYE = 3.5526315789473686  # 5% gentler perspective; independent of scene focal length
MAYA_PERSP_DIR = Vector((-28.0, 28.0, -21.0)).normalized()   # Maya persp looking direction, Blender axes

# face -> (normal, text u axis, text v axis), Blender axes; names = view3d.view_axis types
FACES = {
    "TOP": ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    "BOTTOM": ((0, 0, -1), (1, 0, 0), (0, -1, 0)),
    "FRONT": ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
    "BACK": ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
    "RIGHT": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "LEFT": ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
}
FACE_NAMES = tuple(FACES)
CONTROL_NAMES = ('HOME', 'ROLL_LEFT', 'ROLL_RIGHT', 'MENU')
ORBIT_CONTROLS = ('ORBIT_UP', 'ORBIT_DOWN', 'ORBIT_LEFT', 'ORBIT_RIGHT')

# Orthographic side views (key = the direction the view looks, Blender axes): Maya camera name + that direction
# in Maya's Y-up axes, as Maya prints it ("top -Y", "front -Z", "side -X";
# Blender X/Y/Z = Maya X/-Z/Y). Maya's own words, not Blender's axes.
SIDE_LABELS = {(0, 0, -1): "top -Y", (0, 0, 1): "bottom +Y", (0, 1, 0): "front -Z", (0, -1, 0): "back +Z",
               (-1, 0, 0): "side -X", (1, 0, 0): "left +X"}


# --- maths (mathutils only, no bpy) ---------------------------------------------------------

def _to_view(q, p):
    """World direction/point -> view space of a view whose rotation is ``q`` (view_rotation)."""
    return q.inverted() @ Vector(p)


def _project_cube_point(p, centre, k):
    """Project a view-space cube point; return screen coordinates and its perspective weight."""
    weight = CUBE_EYE - p.z
    factor = (CUBE_EYE - .5) / weight
    return (centre[0] + p.x * k * factor, centre[1] + p.y * k * factor), weight


def _extent(q):
    pts = [_project_cube_point(_to_view(q, (x, y, z)), (0, 0), 1)[0]
           for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)]
    return max(max(p[0] for p in pts) - min(p[0] for p in pts),
               max(p[1] for p in pts) - min(p[1] for p in pts))


def _maya_extent():
    return _extent(MAYA_PERSP_DIR.to_track_quat('-Z', 'Y'))


_PX_PER_UNIT = 1.0 / _maya_extent()   # cube scale that makes its box CUBE_PX tall in Maya's persp


def cube_size(width, height, scale=1.0):
    """ViewCube box size (px) for a view region: 65 px, smaller in small panels."""
    m = min(width, height) / (MAYA_VIEW_H * scale)
    return CUBE_PX * scale * min(1.0, m ** SMALL_EXP)


def faces_2d(q, centre, size):
    """Visible cube faces, back to front: [(name, polygon, facing, u2d, v2d)]."""
    k = size * _PX_PER_UNIT
    out = []
    for name, (n, u, v) in FACES.items():
        nv = _to_view(q, n)
        # Eye is at (0, 0, CUBE_EYE); the face centre is .5 along its normal.
        if nv.z * CUBE_EYE <= .5:
            continue
        nvec, uvec, vvec = Vector(n), Vector(u), Vector(v)
        poly = []
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            p = _to_view(q, nvec * .5 + uvec * .5 * su + vvec * .5 * sv)
            poly.append(_project_cube_point(p, centre, k)[0])
        u2, v2 = _to_view(q, u), _to_view(q, v)
        out.append((name, poly, nv.z, (u2.x, u2.y), (v2.x, v2.y)))
    out.sort(key=lambda f: f[2])
    return out


def _cube_rotation(rv3d):
    """Use the visible camera orientation in Camera View and the usual viewport rotation elsewhere."""
    if rv3d.view_perspective == 'CAMERA':
        return rv3d.view_matrix.inverted().to_quaternion()
    return rv3d.view_rotation


def _face_aligned(rv3d):
    """A roll is offered only when the visible view looks straight at a cube face."""
    forward = _cube_rotation(rv3d) @ Vector((0.0, 0.0, 1.0))
    return max(abs(forward.x), abs(forward.y), abs(forward.z)) >= 1.0 - 1e-5


def point_in_poly(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def hit_face(faces, x, y):
    """Front-most face under (x, y), or None."""
    for name, poly, *_rest in reversed(faces):
        if point_in_poly(x, y, poly):
            return name
    return None


def label_camera(space, scene):
    """The camera a view looks through: its own camera (a kit Look Through), else the scene camera."""
    return space.camera if space.use_local_camera else scene.camera


def label_for(perspective, side_view, view_dir, camera_name=None):
    """Maya camera label of a view: camera name, "top -Y" ... for side views, else "persp"."""
    if perspective == 'CAMERA' and camera_name:
        return camera_name
    if perspective == 'ORTHO' and side_view:
        key = tuple(int(round(c)) for c in view_dir)
        if key in SIDE_LABELS:
            return SIDE_LABELS[key]
    return "persp"


def layout(bounds, scale, size):
    """Region-local positions in a visible rect (x0, y0, x1, y1): cube centre, label (x centre,
    baseline y), triad origin."""
    x0, y0, x1, y1 = bounds
    cube = (x1 - CUBE_INSET[0] * scale - size / 2, y1 - CUBE_INSET[1] * scale - size / 2)
    label = ((x0 + x1) / 2 + LABEL_SHIFT * scale, y0 + LABEL_BASELINE * scale)
    triad = (x0 + TRIAD_INSET * scale, y0 + TRIAD_INSET * scale)
    return cube, label, triad


def triad(q, origin, length):
    """Axis lines on screen, back to front: [(axis index, end (x, y), depth)]."""
    out = []
    for i in range(3):
        d = [0.0, 0.0, 0.0]
        d[i] = 1.0
        p = _to_view(q, d)
        out.append((i, (origin[0] + p.x * length, origin[1] + p.y * length), p.z))
    out.sort(key=lambda a: a[2])
    return out


def _bounds(context):
    """Visible part of the region (sidebar / toolbar excluded), region-local."""
    from ..operators import view
    return view.visible_bounds(context.area, context.region)   # already region-local


def _scale():
    return bpy.context.preferences.system.ui_scale or 1.0


def _arc_arrow(centre, radius, start, end, length, half_width):
    """Circular shaft with a separate, tangent-aligned triangular arrowhead."""
    direction = 1 if end > start else -1
    theta = math.radians(end)
    tx, ty = -direction * math.sin(theta), direction * math.cos(theta)
    x, y = centre
    tip = (x + radius * math.cos(theta), y + radius * math.sin(theta))
    base = (tip[0] - tx * length, tip[1] - ty * length)
    head = (tip, (base[0] - ty * half_width, base[1] + tx * half_width),
            (base[0] + ty * half_width, base[1] - tx * half_width))
    # Stop inside the triangle's base; no round stroke cap crosses its point.
    shaft_end = end - direction * math.degrees(length * .8 / radius)
    steps = max(12, math.ceil(abs(shaft_end - start) / 4))
    shaft = [(x + radius * math.cos(a), y + radius * math.sin(a))
             for a in (math.radians(start + (shaft_end-start)*i/steps) for i in range(steps+1))]
    return shaft, head


def _roll_arrows(context, centre, size):
    """Two separated arcs of one circle around the projected face's upper-right corner."""
    faces = faces_2d(_cube_rotation(context.region_data), centre, size)
    points = [p for face in faces for p in face[1]]
    if not points:
        return {}
    x0, x1 = min(p[0] for p in points), max(p[0] for p in points)
    y0, y1 = min(p[1] for p in points), max(p[1] for p in points)
    radius = min(x1-x0, y1-y0) * .48
    s = _scale()
    length, width = min(4.5*s, radius*.22), min(2.6*s, radius*.13)
    return {'ROLL_LEFT': _arc_arrow((x1,y1), radius, 55, 100, length, width),
            'ROLL_RIGHT': _arc_arrow((x1,y1), radius, 32, -5, length, width)}


def control_layout(context, centre, size):
    """Corner controls and the four small arrows around an aligned face."""
    s = _scale()
    x, y = centre
    radius = min(9 * s, size * .14)
    controls = {'HOME': (x - size * .57, y + size * .72, radius),
            'ROLL_LEFT': (x + size * .40, y + size * .78, radius),
            'ROLL_RIGHT': (x + size * .54, y + size * .48, radius),
            'MENU': (x + size * .67, y - size * .55, radius),
            'ORBIT_UP': (x, y + size * .52, radius * .72),
            'ORBIT_DOWN': (x, y - size * .52, radius * .72),
            'ORBIT_LEFT': (x - size * .52, y, radius * .72),
            'ORBIT_RIGHT': (x + size * .52, y, radius * .72)}
    for name, (shaft, head) in _roll_arrows(context, centre, size).items():
        vertices = [*shaft, *head]
        left, right = min(p[0] for p in vertices), max(p[0] for p in vertices)
        bottom, top = min(p[1] for p in vertices), max(p[1] for p in vertices)
        controls[name] = ((left+right)/2, (bottom+top)/2, max(radius,(right-left)/2,(top-bottom)/2))
    return controls


def _control_at(centre, controls, location, face_aligned):
    """Hit visible control targets or the narrow path leading from the cube to each target."""
    eligible = [(name, data) for name, data in controls.items()
                if not name.startswith(('ROLL', 'ORBIT')) or face_aligned]
    px, py = location
    # A control's own circular target wins over another control's approach path.
    for name, (x, y, radius) in eligible:
        if (px - x) ** 2 + (py - y) ** 2 <= radius ** 2:
            return name
    for name, (x, y, radius) in eligible:
        dx, dy = x - centre[0], y - centre[1]
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-12:
            continue
        t = ((px - centre[0]) * dx + (py - centre[1]) * dy) / length_sq
        if 0.0 <= t <= 1.0:
            ex, ey = centre[0] + t * dx, centre[1] + t * dy
            if (px - ex) ** 2 + (py - ey) ** 2 <= (radius * .45) ** 2:
                return name
    return None
