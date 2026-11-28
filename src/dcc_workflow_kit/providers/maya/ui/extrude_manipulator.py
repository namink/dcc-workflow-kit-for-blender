# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's extrude manipulator as a 3D gizmo group (``ALLSET_GGT_extrude``): Local Translate arrows, Local Scale cubes,
plane handles and centre square, the Transform Component ring and world / local switch, their hit test for the
pre-selection gizmo (``handles_hit``) and the drag operators (``allset.extrude_drag``, ``allset.tc_space``).
Related: in_view_target.py, manipulator.py (shapes, axis colours), operators/extrude.py (``set_params``).
"""

import math

import bpy
import gpu
from bpy.props import StringProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector, geometry

from . import manipulator
from ..operators import extrude, move_component, units
from .in_view_target import _redraw, _scale, _state, arrow_visible, cap_frame, record, target


# --- the extrude manipulator (3D gizmo) --------------------------------------------------

YELLOW = (1.0, 1.0, 0.0)

# Extrusion manipulator (top face of a cube,
# local mode): lengths in "arrow units" (centre -> scale cube = 1): cone 0.64 -> 0.86 (radius 0.05), cube half 0.07,
# plane handles centred 0.5 / 0.5 between two axes (half 0.08, translucent with a full-colour rim), hollow centre square
# half 0.12 (20 px at an 83 px Z arrow) in #64dcff, screen facing. Axis colours = the kit Move manipulator's
# colours (manipulator.AXIS_HEX). Face extrusions also have the cyan rotate ring and the world / local switch of the
# Transform Component manipulator (``TURN`` below).
CONE_BASE, CONE_TIP, CONE_R = 0.64, 0.86, 0.05
CUBE_AT, CUBE_HALF = 1.0, 0.07
PLANE_AT, PLANE_HALF = 0.5, 0.08
PLANE_FILL = 0.25
CENTER_HALF = 0.12
CENTER_COLOUR = (0x64 / 255, 0xdc / 255, 1.0)
SCALE_PX = 100.0          # px of mouse travel along a scale handle that doubles the scale
# the extrude manipulator is drawn smaller than the Move one: Z arrow to cube 83 px at a ~27 deg persp elevation
# = ~93 px against the Move Y arrow's 108 px (manipulator.ARROW_PX)
SIZE = 0.86

# handle -> (role, axis or plane, the values it drives)
HANDLES = {
    "TX": ('ARROW', 'X', ("local_translate_x",)),
    "TY": ('ARROW', 'Y', ("local_translate_y",)),
    "TZ": ('ARROW', 'Z', ("local_translate_z",)),
    "SX": ('CUBE', 'X', ("local_scale_x",)),
    "SY": ('CUBE', 'Y', ("local_scale_y",)),
    "SZ": ('CUBE', 'Z', ("local_scale_z",)),
    "PXY": ('PLANE', 'XY', ("local_translate_x", "local_translate_y")),
    "PYZ": ('PLANE', 'YZ', ("local_translate_y", "local_translate_z")),
    "PXZ": ('PLANE', 'XZ', ("local_translate_x", "local_translate_z")),
    "S": ('CENTER', None, ("local_scale_x", "local_scale_y", "local_scale_z")),
}
AXIS_INDEX = {'X': 0, 'Y': 1, 'Z': 2}
# Ctrl+drag, like Maya: an arrow moves in the plane of the other two axes, a scale cube scales the other two
CTRL_OTHERS = {
    "TX": "PYZ", "TY": "PXZ", "TZ": "PXY",
    "SX": ("SY", "SZ"), "SY": ("SX", "SZ"), "SZ": ("SX", "SY"),
}

# Transform Component of faces / edges, like Maya's: a light-blue ring past the scale cubes (radius 1.17 arrow units;
# drag = turn about the view axis by the angle the mouse sweeps round the centre), three rotate rings at the cube
# distance shown after a press on it (plane handles and centre square give way to them), and a world / local switch
# up and right of the manipulator (a kit-drawn globe). Polygon vertices have neither (Maya's polyMoveVertex has no
# Local Rotate).
VIEW_RING_R = 1.17
AXIS_RING_R = 1.0
RING_COLOUR = CENTER_COLOUR
RING_ACTIVE = manipulator.ACTIVE     # the ring while the rotate rings show
SPACE_AT = (1.39, 1.42)    # switch centre from the manipulator centre on screen (right, up), in arrow units
SPACE_R = 0.1              # switch radius, arrow units
CLICK_PX = 3.0             # a press on the ring that moves less than this (x UI scale) is a click
LOCAL_ROT = ("local_rotate_x", "local_rotate_y", "local_rotate_z")
WORLD_ROT = ("rotate_x", "rotate_y", "rotate_z")
TURN = {
    "VR": ('VIEW_RING', None, LOCAL_ROT),
    "RX": ('RING', 'X', ("local_rotate_x",)),
    "RY": ('RING', 'Y', ("local_rotate_y",)),
    "RZ": ('RING', 'Z', ("local_rotate_z",)),
}
# world axes: what each handle drives instead (the centre square moves in the view plane)
WORLD_FIELDS = {
    "TX": ("translate_x",), "TY": ("translate_y",), "TZ": ("translate_z",),
    "SX": ("scale_x",), "SY": ("scale_y",), "SZ": ("scale_z",),
    "PXY": ("translate_x", "translate_y"), "PYZ": ("translate_y", "translate_z"), "PXZ": ("translate_x", "translate_z"),
    "S": ("translate_x", "translate_y", "translate_z"),
    "VR": WORLD_ROT, "RX": ("rotate_x",), "RY": ("rotate_y",), "RZ": ("rotate_z",),
}


def turnable(rec):
    """True for a face extrusion and a Transform Component of faces / edges: its manipulator has the ring and the
    world / local switch, like Maya's."""
    return (rec is not None and (rec.spec.full_manip or rec.spec is extrude.FACE)
            and "local_rotate_x" in rec.spec.all_fields)


def tc_state(rec):
    """{"world", "rings"} of the Transform Component manipulator of ``rec``: a display state kept on the record, not
    node values (nothing to undo); a new node starts on local axes without the rotate rings, like Maya."""
    state = getattr(rec, "manip_state", None)
    if state is None:
        state = rec.manip_state = {"world": False, "rings": False}
    return state


def flags(rec):
    """(world axes, rotate rings shown) of the manipulator of ``rec`` (always local, no rings when not turnable)."""
    if not turnable(rec):
        return False, False
    state = tc_state(rec)
    return state["world"], state["rings"]


def handle_entry(handle):
    return HANDLES.get(handle) or TURN.get(handle)


def handle_role(handle, world=False):
    """Drag role of ``handle``: the centre square moves freely ('FREE') on world axes."""
    role = handle_entry(handle)[0]
    return 'FREE' if role == 'CENTER' and world else role


def handle_fields(rec, handle, world=False, rings=False):
    """The values ``handle`` drives on ``rec`` (edge / vertex extrusion, bevel: only "TZ" = their arrow field;
    Transform Component: every handle of its fields; ``world`` / ``rings`` = the manipulator's state)."""
    entry = handle_entry(handle)
    if rec is None or entry is None:
        return ()
    if rec.spec is not extrude.FACE and not rec.spec.full_manip:
        return (rec.spec.arrow,) if handle == "TZ" and rec.spec.arrow is not None else ()
    role = entry[0]
    if not turnable(rec):
        if handle in TURN:
            return ()
        world = rings = False
    elif (role == 'RING' and not rings) or (rings and role in ('PLANE', 'CENTER')):
        return ()
    fields = WORLD_FIELDS[handle] if world else entry[2]
    # Transform Component of vertices: no Local Scale (Maya's polyMoveVertex has none)
    return fields if all(f in rec.spec.all_fields for f in fields) else ()


def manip_frame(ob, rec, world=False):
    """(world centre, 3x3 world unit axes (columns X, Y, Z), world lengths of one mesh unit along X / Y / Z) of the
    extrude manipulator: Z = the faces' normal, X / Y = polyExtrudeFace's local axes of that normal (world X projected
    into the face plane, extrude_face.face_axes); ``world``: the world axes (Transform Component switch). None when there
    is nothing to show."""
    frame = cap_frame(ob, rec)
    if frame is None:
        return None
    centre, nw, kz = frame
    if world:
        return centre, Matrix.Identity(3), (1.0, 1.0, 1.0)
    mw3 = ob.matrix_world.to_3x3()
    inv = mw3.inverted_safe()
    n_obj = (inv @ nw)
    n_obj = n_obj.normalized() if n_obj.length > 1e-12 else Vector((0, 0, 1))
    axes = extrude.mesh_axes(ob)
    x_obj, y_obj = extrude.face_axes(n_obj, axes["direction"], axes["fallback"])
    xw, yw = mw3 @ x_obj, mw3 @ y_obj
    kx, ky = xw.length or 1.0, yw.length or 1.0
    xw, yw = xw / kx, yw / ky
    return centre, Matrix((xw, yw, nw)).transposed(), (kx, ky, kz)


def unit_px(context):
    """Screen px of one arrow unit (wm_gizmo: scale_basis x gizmo_size x UI scale at use_draw_scale)."""
    return (manipulator.scale_basis(context) * SIZE * context.preferences.view.gizmo_size
            * (context.preferences.system.ui_scale or 1.0))


def handles_hit(context, region, rv3d, mouse, reach):
    """True when ``mouse`` (region px) is within ``reach`` px of a shown handle of the extrude manipulator: the
    pre-selection gizmo (operators/preselect.py, a 2D test_select that would win over these 3D-picked handles)
    declines there, like it does on the Move manipulator."""
    ob, rec = record(context)
    world, rings = flags(rec)
    frame = manip_frame(ob, rec, world) if rec is not None else None
    if frame is None:
        return False
    centre, axes, _k = frame
    c2 = view3d_utils.location_3d_to_region_2d(region, rv3d, centre)
    if c2 is None:
        return False
    w = view3d_utils.region_2d_to_location_3d(region, rv3d, c2 + Vector((1.0, 0.0)), centre) - centre
    unit = unit_px(context) * w.length          # world length of one arrow unit at the centre
    m = Vector(mouse)

    def at(vec):
        p = view3d_utils.location_3d_to_region_2d(region, rv3d, centre + vec * unit)
        return p if p is not None else c2

    if turnable(rec):
        at_px, r_px = space_button(context, c2)
        if (Vector(at_px) - m).length <= reach + r_px:
            return True
    for handle in (*HANDLES, *TURN):
        if not handle_fields(rec, handle, world, rings):
            continue
        role, data, _f = handle_entry(handle)
        if role == 'VIEW_RING':
            if abs((m - c2).length - VIEW_RING_R * unit_px(context)) <= reach:
                return True
        elif role == 'RING':
            ring = Matrix.Translation(centre) @ (axes @ manipulator._axis_rot(data)).to_4x4()                 @ Matrix.Scale(AXIS_RING_R * unit, 4)
            view_z = rv3d.view_matrix.inverted_safe().col[2].xyz.normalized()
            for arc in manipulator.front_arcs(ring, view_z):
                pts = [view3d_utils.location_3d_to_region_2d(region, rv3d, p) for p in arc]
                if any(p is not None and (p - m).length <= reach for p in pts):
                    return True
        elif role == 'ARROW':
            a, b = c2, at(axes.col[AXIS_INDEX[data]] * CONE_TIP)
            ab = b - a
            t = 0.0 if ab.length_squared < 1e-9 else max(0.0, min(1.0, (m - a).dot(ab) / ab.length_squared))
            if (a + ab * t - m).length <= reach:
                return True
        elif role == 'CUBE':
            if (at(axes.col[AXIS_INDEX[data]] * CUBE_AT) - m).length <= reach + CUBE_HALF * unit_px(context):
                return True
        elif role == 'PLANE':
            i, j = AXIS_INDEX[data[0]], AXIS_INDEX[data[1]]
            if (at((axes.col[i] + axes.col[j]) * PLANE_AT) - m).length <= reach + PLANE_HALF * unit_px(context):
                return True
        elif (c2 - m).length <= reach + CENTER_HALF * unit_px(context):
            return True
    return False


def handle_shapes(role):
    """(draw shapes [(type, verts, fill)], pick shape (type, verts)) of a handle in arrow units: arrows / cubes point
    along local +Z, plane handles lie in the local XY plane, the centre square faces +Z. Pure (tests run it headless)."""
    m = manipulator
    if role == 'ARROW':
        return ([('LINES', [(0, 0, 0), (0, 0, CONE_BASE)], False), ('TRIS', m._cone(CONE_BASE, CONE_TIP, CONE_R), False)],
                ('TRIS', m._bar(CENTER_HALF, CONE_BASE, 0.04) + m._cone(CONE_BASE, CONE_TIP, CONE_R * 1.6)))
    if role == 'CUBE':
        return ([('LINES', [(0, 0, CONE_TIP), (0, 0, CUBE_AT - CUBE_HALF)], False),
                 ('TRIS', m._box((0, 0, CUBE_AT), CUBE_HALF), False)],
                ('TRIS', m._box((0, 0, CUBE_AT), CUBE_HALF * 1.6)))
    if role == 'PLANE':
        rim = [(x + PLANE_AT, y + PLANE_AT, z) for x, y, z in m._square_outline(PLANE_HALF)]
        return ([('TRIS', m._square(PLANE_AT, PLANE_AT, PLANE_HALF), True), ('LINES', rim, False)],
                ('TRIS', m._square(PLANE_AT, PLANE_AT, PLANE_HALF * 1.3)))
    if role == 'CENTER':
        return ([('LINES', m._square_outline(CENTER_HALF), False)], ('TRIS', m._square(0, 0, CENTER_HALF * 1.3)))
    raise ValueError(role)


class ALLSET_GT_extrude_handle(bpy.types.Gizmo):
    """One handle of the Maya extrude manipulator (custom shapes; plane handles: translucent fill + rim)."""
    bl_idname = "ALLSET_GT_extrude_handle"
    __slots__ = ("draw_shapes", "pick_shape", "handle")

    def build(self, handle):
        self.handle = handle
        draw, pick = handle_shapes(HANDLES[handle][0])
        self.draw_shapes = [(t, self.new_custom_shape(t, v), fill) for t, v, fill in draw]
        self.pick_shape = self.new_custom_shape(*pick)

    def draw(self, context):
        colour = self.color_highlight if self.is_highlight else self.color
        alpha = self.alpha_highlight if self.is_highlight else self.alpha
        smooth = manipulator.antialiasing(context)
        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(self.line_width)
        for kind, (batch, shader), fill in getattr(self, "draw_shapes", ()):
            if smooth and kind == 'LINES':
                manipulator.draw_handle_line(self, batch, (*colour, alpha))
                continue
            shader.bind()
            shader.uniform_float("color", (*colour, alpha * PLANE_FILL if fill else alpha))
            with gpu.matrix.push_pop():
                gpu.matrix.multiply_matrix(self.matrix_world)
                batch.draw(shader)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')

    def draw_select(self, context, select_id):
        sh = getattr(self, "pick_shape", None)
        if sh is not None:
            self.draw_custom_shape(sh, select_id=select_id)


def space_button(context, c2=None):
    """((x, y) region px, radius px) of the world / local switch of the shown Transform Component manipulator, or
    ((0, 0), -1) when there is none. ``c2`` = the manipulator centre on screen when the caller has it."""
    if c2 is None:
        ob, rec = record(context)
        frame = cap_frame(ob, rec) if turnable(rec) else None
        if frame is None or context.region_data is None:
            return (0.0, 0.0), -1.0
        c2 = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, frame[0])
        if c2 is None:
            return (0.0, 0.0), -1.0
    u = unit_px(context)
    return (c2[0] + SPACE_AT[0] * u, c2[1] + SPACE_AT[1] * u), SPACE_R * u


def globe_lines(x, y, r, n=32):
    """Line pairs of the switch's globe (outline, equator, one meridian) around region px (x, y). Pure."""
    out = []
    for rx in (r, r * 0.45):            # outline and meridian
        pts = [(x + rx * math.cos(2 * math.pi * i / n), y + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
        for i in range(n):
            out += [pts[i], pts[(i + 1) % n]]
    out += [(x - r, y), (x + r, y)]
    return out


class ALLSET_GT_tc_space(bpy.types.Gizmo):
    """The world / local switch of the Transform Component manipulator, drawn and picked in region pixels"""
    bl_idname = "ALLSET_GT_tc_space"

    def draw(self, context):
        (x, y), r = space_button(context)
        region = context.region
        if r <= 0 or region is None:
            return
        colour = self.color_highlight if self.is_highlight else self.color
        ortho = Matrix(((2 / region.width, 0, 0, -1), (0, 2 / region.height, 0, -1), (0, 0, -1, 0), (0, 0, 0, 1)))
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(ortho)
            gpu.state.blend_set('ALPHA')
            if flags(record(context)[1])[0]:        # world axes: the globe is filled
                fan = [(x, y)] + [(x + r * math.cos(2 * math.pi * i / 32), y + r * math.sin(2 * math.pi * i / 32))
                                  for i in range(33)]
                sh = gpu.shader.from_builtin('UNIFORM_COLOR')
                sh.uniform_float("color", (*colour[:3], 0.35))
                batch_for_shader(sh, 'TRI_FAN', {"pos": fan}).draw(sh)
            width = 1.5 * (_scale() or 1.0)
            with manipulator.handle_polyline(width, (*colour[:3], 1.0), manipulator.antialiasing(context)) as sh:
                batch_for_shader(sh, 'LINES', {"pos": globe_lines(x, y, r)}).draw(sh)
            gpu.state.blend_set('NONE')

    def test_select(self, context, location):
        (x, y), r = space_button(context)
        if r <= 0:
            return -1
        return 0 if (Vector(location) - Vector((x, y))).length <= r + 3 * (_scale() or 1.0) else -1


def _no_tooltip(gz):
    """Maya manipulators have no tooltips; Blender would show the target operator's description (#98)."""
    if hasattr(gz, "use_tooltip"):
        gz.use_tooltip = False


class ALLSET_GGT_extrude(bpy.types.GizmoGroup):
    bl_idname = "ALLSET_GGT_extrude"
    bl_label = "Maya Extrude Manipulator"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and space.type == 'VIEW_3D' and space.show_gizmo and arrow_visible(context)

    def setup(self, context):
        self.handles = {}
        for handle in HANDLES:
            gz = self.gizmos.new(ALLSET_GT_extrude_handle.bl_idname)
            gz.build(handle)
            gz.target_set_operator(ALLSET_OT_extrude_drag.bl_idname).handle = handle
            gz.color_highlight = YELLOW
            gz.alpha = gz.alpha_highlight = 1.0
            gz.line_width = 1.5
            gz.use_draw_scale = True
            gz.use_draw_modal = True
            _no_tooltip(gz)
            self.handles[handle] = gz
        self.arrow = self.handles["TZ"]
        # Transform Component: made after the handles, so the rings win where they cross an arrow or a cube (the
        # first hit runs from the last made gizmo), the switch last
        for handle, (role, _data, _f) in TURN.items():
            gz = self.gizmos.new(manipulator.RING_GIZMO if role == 'RING' else "GIZMO_GT_dial_3d")
            if role == 'RING':
                gz.handle_role, gz.handle_axis = role, _data
            else:
                gz.draw_options = set()
            gz.target_set_operator(ALLSET_OT_extrude_drag.bl_idname).handle = handle
            gz.color_highlight = YELLOW
            gz.alpha = gz.alpha_highlight = 1.0
            gz.line_width = 1.5
            gz.use_draw_scale = True
            gz.use_draw_modal = True
            _no_tooltip(gz)
            self.handles[handle] = gz
        gz = self.gizmos.new(ALLSET_GT_tc_space.bl_idname)
        gz.target_set_operator(ALLSET_OT_tc_space.bl_idname)
        gz.color, gz.color_highlight = RING_COLOUR, YELLOW
        gz.alpha = gz.alpha_highlight = 1.0
        _no_tooltip(gz)
        self.space = gz

    def draw_prepare(self, context):
        ob, rec = record(context)
        if rec is None:
            return
        world, rings = flags(rec)
        frame = manip_frame(ob, rec, world)
        rv3d = context.region_data
        view = rv3d.view_rotation.to_matrix() if rv3d is not None else Matrix.Identity(3)
        colours = manipulator.axis_colours()
        s = manipulator.scale_basis(context) * SIZE
        self.space.hide = frame is None or not turnable(rec)
        for handle, gz in self.handles.items():
            gz.hide = frame is None or not handle_fields(rec, handle, world, rings)
            if gz.hide:
                continue
            centre, axes, _k = frame
            role, data, _fields = handle_entry(handle)
            gz.scale_basis = s
            if role in ('ARROW', 'CUBE', 'RING'):
                rot = axes @ manipulator._axis_rot(data)
                gz.color = colours[data]
                if role == 'RING':
                    gz.scale_basis = s * AXIS_RING_R
            elif role == 'PLANE':
                _c, normal, local = manipulator.PLANES[data]
                rot = axes @ local
                gz.color = colours[normal]
            elif role == 'VIEW_RING':
                rot = view
                gz.color = RING_ACTIVE if rings else RING_COLOUR
                gz.scale_basis = s * VIEW_RING_R
            else:
                rot = view
                gz.color = CENTER_COLOUR
            gz.matrix_basis = Matrix.Translation(centre) @ rot.to_4x4()


class ALLSET_OT_extrude_drag(bpy.types.Operator):
    """Drag a handle of the extrude manipulator (Maya polyExtrudeFace Local Translate / Local Scale; Local
    Translate Z of an edge extrusion, Length of a vertex extrusion)"""
    bl_idname = "allset.extrude_drag"
    bl_label = "Extrude Manipulator"
    bl_options = {'INTERNAL'}

    handle: StringProperty(default="TZ", options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        rec = target(context)[1]
        return rec is not None and rec.spec.arrow is not None and context.region_data is not None

    def _ray(self, context, event):
        region, rv3d = context.region, context.region_data
        co = (event.mouse_region_x, event.mouse_region_y)
        return (view3d_utils.region_2d_to_origin_3d(region, rv3d, co),
                view3d_utils.region_2d_to_vector_3d(region, rv3d, co))

    def _along(self, context, event, axis):
        o, d = self._ray(context, event)
        hit = geometry.intersect_line_line(self._c, self._c + axis, o, o + d)
        return None if hit is None else (hit[0] - self._c).dot(axis)

    def _on_plane(self, context, event, normal):
        o, d = self._ray(context, event)
        return geometry.intersect_line_plane(o, o + d, self._c, normal)

    def _screen_dir(self, context, axis):
        region, rv3d = context.region, context.region_data
        p0 = view3d_utils.location_3d_to_region_2d(region, rv3d, self._c)
        p1 = view3d_utils.location_3d_to_region_2d(region, rv3d, self._c + axis * 1e-3)
        if p0 is None or p1 is None or (p1 - p0).length < 1e-9:
            return Vector((1.0, 0.0))
        return (p1 - p0).normalized()

    def _ring_tangent(self, context, data):
        """Screen tangent (px per radian of turn) of the rotate ring of axis ``data`` at its point nearest the press."""
        region, rv3d = context.region, context.region_data
        c2 = view3d_utils.location_3d_to_region_2d(region, rv3d, self._c)
        if c2 is None:
            return Vector((0.0, 0.0))
        w = view3d_utils.region_2d_to_location_3d(region, rv3d, c2 + Vector((1.0, 0.0)), self._c) - self._c
        r = AXIS_RING_R * unit_px(context) * w.length
        rot = self._frame3 @ manipulator._axis_rot(data)       # columns: two ring directions, the axis

        def at(a):
            return view3d_utils.location_3d_to_region_2d(
                region, rv3d, self._c + (rot.col[0] * math.cos(a) + rot.col[1] * math.sin(a)) * r)
        best = None
        for i in range(72):
            a = 2 * math.pi * i / 72
            p = at(a)
            if p is not None and (best is None or (p - self._mouse0).length < best[0]):
                best = ((p - self._mouse0).length, a, p)
        if best is None:
            return Vector((0.0, 0.0))
        p1 = at(best[1] + 1e-3)
        return Vector((0.0, 0.0)) if p1 is None else (p1 - best[2]) / 1e-3

    def _sweep(self, event):
        """Angle (radians, counter-clockwise on screen) the mouse has swept round the manipulator centre so far."""
        v = Vector((event.mouse_region_x, event.mouse_region_y)) - self._c2
        if v.length > 1e-6 and self._prev.length > 1e-6:
            self._swept += math.atan2(self._prev.cross(v), self._prev.dot(v))
            self._prev = v
        return self._swept

    def invoke(self, context, event):
        ob, rec = target(context)
        world, rings = flags(rec)
        handle, others = self.handle, None
        fields = handle_fields(rec, handle, world, rings)
        alt = CTRL_OTHERS.get(handle) if event.ctrl else None
        if isinstance(alt, str) and handle_fields(rec, alt, world, rings):
            handle = alt            # Ctrl on an arrow: the plane of the other two axes
            fields = handle_fields(rec, handle, world, rings)
        elif alt is not None and not isinstance(alt, str):
            more = tuple(f for h in alt for f in handle_fields(rec, h, world, rings))
            if len(more) == len(alt):       # Ctrl on a scale cube: the other two cubes, by this cube's drag
                others, fields = alt, more
        frame = manip_frame(ob, rec, world) if fields else None
        if frame is None:
            return {'CANCELLED'}
        self._ob, self._rec, self._fields = ob, rec, fields
        self._c, axes, self._k = frame
        self._frame3 = axes.copy()
        self._axes = [axes.col[i].copy() for i in range(3)]
        self._world = world
        self._role = handle_role(handle, world)
        data = handle_entry(handle)[1]
        self._idx = [AXIS_INDEX[a] for a in data] if data else []
        self._start = dict(extrude.DEFAULTS, **rec.params)
        self._unit = units.maya_unit(context.scene)
        self._mouse0 = Vector((event.mouse_region_x, event.mouse_region_y))
        self._moved = False
        rv3d = context.region_data
        if self._role in ('VIEW_RING', 'RING'):
            self._rot = WORLD_ROT if world else LOCAL_ROT
        if self._role == 'VIEW_RING':
            # about the view axis (toward the viewer), by the angle swept round the centre; a press shows the rings
            self._axis = (rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))).normalized()
            self._c2 = view3d_utils.location_3d_to_region_2d(context.region, rv3d, self._c) or self._mouse0.copy()
            self._prev, self._swept = self._mouse0 - self._c2, 0.0
            state = tc_state(rec)
            self._rings_before, state["rings"] = state["rings"], True
        elif self._role == 'RING':
            self._axis = self._axes[self._idx[0]]
            self._tan = self._ring_tangent(context, data)
        elif self._role == 'FREE':          # world centre square: free move in the view plane
            self._normal = (rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))).normalized()
            self._h0 = self._on_plane(context, event, self._normal)
        if self._role == 'ARROW':
            self._t0 = self._along(context, event, self._axes[self._idx[0]])
        elif self._role == 'PLANE':
            normal = self._axes[self._idx[0]].cross(self._axes[self._idx[1]])
            self._normal = normal
            self._h0 = self._on_plane(context, event, normal)
        elif self._role == 'CUBE':
            self._sdir = self._screen_dir(context, self._axes[self._idx[0]])
            if others:
                self._idx = [AXIS_INDEX[handle_entry(h)[1]] for h in others]
        self._last = {}
        self._button = event.type if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE'} else 'LEFTMOUSE'
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def values(self, context, event):
        """{field: value} for the mouse at ``event`` (the press values while the drag has no reading yet)."""
        start, out = self._start, {}
        if self._role == 'ARROW':
            i = self._idx[0]
            t = self._along(context, event, self._axes[i])
            if t is None or self._t0 is None:
                return dict(self._last)
            out[self._fields[0]] = round(start[self._fields[0]] + (t - self._t0) / self._k[i] / self._unit, 4)
        elif self._role in ('PLANE', 'FREE'):
            h = self._on_plane(context, event, self._normal)
            if h is None or self._h0 is None:
                return dict(self._last)
            d = h - self._h0
            for field, i in zip(self._fields, self._idx or range(3)):
                out[field] = round(start[field] + d.dot(self._axes[i]) / self._k[i] / self._unit, 4)
        elif self._role in ('VIEW_RING', 'RING'):
            if self._role == 'VIEW_RING':
                angle = self._sweep(event)
            else:       # along the ring's tangent at the pressed point
                mouse = Vector((event.mouse_region_x, event.mouse_region_y))
                n2 = self._tan.length_squared
                angle = 0.0 if n2 < 1e-9 else (mouse - self._mouse0).dot(self._tan) / n2
            axis = self._axis if self._world else self._frame3.transposed() @ self._axis
            out.update(zip(self._rot, move_component.turned([start[f] for f in self._rot], axis, angle)))
        else:
            mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            if self._role == 'CUBE':
                dist = (mouse - self._mouse0).dot(self._sdir)
            else:   # centre: Maya's uniform scale follows the horizontal drag
                dist = mouse.x - self._mouse0.x
            factor = 1.0 + dist / (SCALE_PX * (_scale() or 1.0))      # ui_scale reads 0 in background
            for field in self._fields:
                out[field] = round(start[field] * factor, 4)
        self._last = out
        return dict(out)

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            self._moved = self._moved or (mouse - self._mouse0).length > CLICK_PX * (_scale() or 1.0)
            params = dict(self._rec.params, **self.values(context, event))
            extrude.preview(self._ob, self._rec, params, self._unit)
            if self._fields[0] in self._rec.spec.view_fields:
                _state["hot"] = self._rec.spec.view_fields.index(self._fields[0])
            _redraw(context)
            return {'RUNNING_MODAL'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            extrude.preview(self._ob, self._rec, {k: self._start[k] for k in self._rec.params}, self._unit)
            self._rec.live = False
            _redraw(context)
            return {'CANCELLED'}
        if event.type == self._button and event.value == 'RELEASE':
            changes = self.values(context, event)
            if self._role in ('VIEW_RING', 'RING') and not self._moved:
                changes = {}        # a click on a ring changes no value
                if self._role == 'VIEW_RING':       # it shows / hides the rotate rings
                    tc_state(self._rec)["rings"] = not self._rings_before
            if changes:
                extrude.set_params(context, **changes)
            else:
                extrude.preview(self._ob, self._rec, {k: self._start[k] for k in self._rec.params}, self._unit)
                self._rec.live = False
            _redraw(context)
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


class ALLSET_OT_tc_space(bpy.types.Operator):
    """Put the Transform Component manipulator on world or local axes"""
    bl_idname = "allset.tc_space"
    bl_label = "World / Local Axes"
    bl_options = {'INTERNAL'}       # a display state of the manipulator: no undo step, like Maya

    @classmethod
    def poll(cls, context):
        return turnable(target(context)[1])

    def execute(self, context):
        _ob, rec = target(context)
        state = tc_state(rec)
        state["world"] = not state["world"]
        _redraw(context)
        return {'FINISHED'}
