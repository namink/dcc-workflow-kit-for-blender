# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya-shaped Move / Rotate / Scale manipulators.

Blender's transform gizmo (``VIEW3D_GGT_xform_gizmo``) is C and its shape can't be
changed: thick axes, small cones, a white centre
circle. Maya's:

- Move: thin axis lines with cones, a hollow centre square (free move), filled
  plane handles (normal-axis colour), the active handle drawn yellow.
- Rotate: axis rings drawn on their front half only, a larger view ring, a grey trackball outline (a drag
  inside it rotates freely). The handles use fixed red / green / blue axis colours (``AXIS_HEX``).
- Scale: axis lines with cubes at the ends, a yellow centre cube, plane handles.
- Pivot edit mode (D / Insert): Move plus small rings to orient the pivot.
- Constant screen size: 108 px for the Move Y arrow.

``ALLSET_GGT_xform`` draws that and runs Blender's own transform operators from each
handle (``target_set_operator``), so snapping, constraints, numeric input, Smart
Duplicate/Extrude and the active handle keep working. The Scale centre and axis handles run
``allset.manip_scale`` (operators/manip_scale.py), Maya's scale drag on top of Blender's resize. It becomes
the widget of the Move, Rotate and Scale tools in object mode and mesh / lattice / curve / surface edit mode by swapping their
ToolDefs in ``VIEW3D_PT_tools_active._tools`` for copies with another ``widget`` (same
idname, so ``wm.tool_set_by_id`` still finds them); tools already active are set up
again. Everything is put back on unregister.

Code: ``manipulator_shapes`` (handle geometry), ``manipulator_frame`` (position and axes), ``manipulator_tools``
(tool swap, Tool Settings). This module keeps the handle colours, the gizmo classes, the manipulator size and
register / unregister, and re-exports the names the rest of the kit reads from it.
"""

from contextlib import contextmanager

import bpy
from bpy.types import Gizmo, GizmoGroup
from mathutils import Matrix, Vector
from .. import safe_reg
from ..operators import group
from .selection_wire_show import antialiasing

# the split-out parts, also read through this module by operators, other UI and the tests
from .manipulator_shapes import (CENTER_HALF, CONE_LEN, CONE_R, CUBE_AT, CUBE_HALF, PIVOT_RING_R,  # noqa: F401
                                 PLANE_AT, PLANE_HALF, RING_STEPS, _bar, _box, _cone, _disc, _ring, _square,
                                 _square_outline, front_arcs, shapes)
from .manipulator_frame import (SLOT, _axis_rot, _edit_points, _has_selection, _object_points,  # noqa: F401
                                _ring_rot, axes_of, center_of, follow_centre, gimbal_axes, pivot_axes, pivot_edit,
                                pivot_frame, slot_type)
from .manipulator_tools import (GROUP, KINDS, MODES, TOOLS, _ensure_timer, _find_item,  # noqa: F401
                                _on_load_post, active_tool, draw_tool_settings, ensure_tools, patch_tools,
                                refresh_pivot_tool, resetup, stale, tool_kind, unpatch_tools)

GIZMO = "ALLSET_GT_maya_handle"
RING_GIZMO = "ALLSET_GT_maya_ring"

# Arrow length in px at gizmo_size 75 and UI scale 1: Maya's Move Y arrow at a manipulator size of 1.5
#. Shapes are built in "arrow units" (arrow length = 1).
ARROW_PX = 108.0
# Rotate rings in arrow units: the axis rings are 75 px in radius at size 1 (the size Blender's own rotate gizmo has
# at its default gizmo size), the view ring 1.2 times that.
ROTATE_RING_R = 75.0 / 108.0
VIEW_RING = 1.2
ROTATE_LINE = 2.0
TRACKBALL = (0.55, 0.55, 0.55)   # grey outline of the free-rotate sphere
YELLOW = (1.0, 1.0, 0.0)  # hovered handle (displayColor manipCurrent #ffff00)
# Active handle and centre as Maya draws them on screen: #fdff88 for the active handle, the centre
# light blue #64dcff while an axis is active (81 px of #fdff88 / #64dcff in the square).
ACTIVE = (0xfd / 255, 1.0, 0x88 / 255)
CENTER_IDLE = (0x64 / 255, 0xdc / 255, 1.0)
ALPHA = 1.0
PLANE_FILL = 0.65         # fill alpha; the fill colour is the axis colour lightened toward white by PLANE_LIGHTEN
PLANE_LIGHTEN = 0.35

AXES = {'X': Vector((1, 0, 0)), 'Y': Vector((0, 1, 0)), 'Z': Vector((0, 0, 1))}


# Plane handles: local XY plane -> the frame plane; (constraint axes, colour axis = normal).
PLANES = {'XY': ((True, True, False), 'Z', Matrix.Identity(3)),
          'YZ': ((False, True, True), 'X', Matrix(((0, 0, 1), (1, 0, 0), (0, 1, 0)))),
          'XZ': ((True, False, True), 'Y', Matrix(((1, 0, 0), (0, 0, 1), (0, 1, 0))))}


# #76: kit-fixed Maya-style axis colours instead of the user's theme gizmo axes (Blender's #ff3653 /
# #8adb00 / #3b64a5): X #e60000, Y #00e600, Z #0000ff. The active and the hovered handle stay yellow #ffff00. Gizmo
# colours are sRGB like the theme values they replace (the gizmo shaders convert).
AXIS_HEX = {'X': "#e60000", 'Y': "#00e600", 'Z': "#0000ff"}


def _srgb(hex_str):
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def axis_colours():
    """{'X' / 'Y' / 'Z': sRGB (r, g, b)} of the Maya manipulator axes (kit-fixed, whatever the theme is)."""
    return {axis: _srgb(value) for axis, value in AXIS_HEX.items()}


def plane_fill(colour):
    """Fill colour of a plane handle: the rim colour lightened toward white (red rim, pinkish fill)."""
    return tuple(c + (1.0 - c) * PLANE_LIGHTEN for c in colour[:3])


def _active_handle(kind):
    """The remembered handle of ``kind`` (operators/manip.HANDLES): None = centre."""
    from ..operators import manip
    return manip.HANDLES.get(kind)


def _is_active(kind, handle_axes):
    h = _active_handle(kind)
    if h is None:
        return handle_axes is None
    return handle_axes is not None and tuple(h.get("constraint_axis", ())) == handle_axes


@contextmanager
def handle_polyline(width, colour, smooth):
    """Draw visible handle strokes with the viewport's line smoothing setting."""
    import gpu

    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    blend = gpu.state.blend_get()
    try:
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
        shader.uniform_float("lineWidth", width)
        shader.uniform_float("color", colour)
        shader.uniform_bool("lineSmooth", smooth)
        yield shader
    finally:
        shader.uniform_bool("lineSmooth", False)
        gpu.state.blend_set(blend)


def draw_handle_line(handle, batch, colour=None):
    import gpu

    if colour is None:
        colour = (*handle.color_highlight, handle.alpha_highlight) if handle.is_highlight else (*handle.color, handle.alpha)
    with gpu.matrix.push_pop(), handle_polyline(handle.line_width, colour, True) as shader:
        gpu.matrix.multiply_matrix(handle.matrix_world)
        batch.draw(shader)


class ALLSET_GT_maya_handle(Gizmo):
    """One Maya manipulator handle: custom shapes, picked with a fatter invisible shape."""
    bl_idname = GIZMO

    __slots__ = ("draw_shapes", "pick_shape", "handle_kind", "handle_role", "handle_axis")

    def build(self, kind):
        self.handle_kind = kind
        draw, pick = shapes(kind)
        self.draw_shapes = [(t, self.new_custom_shape(t, v)) for t, v in draw]
        self.pick_shape = self.new_custom_shape(*pick)

    def draw(self, context):
        smooth = antialiasing(context)
        if getattr(self, "handle_kind", None) == 'PLANE':
            self._draw_plane(smooth)
            return
        for kind, shape in getattr(self, "draw_shapes", ()):
            if smooth and kind == 'LINES':
                draw_handle_line(self, shape[0])
            else:
                self.draw_custom_shape(shape)

    def _draw_plane(self, smooth):
        """Maya plane handle: translucent lightened fill + solid rim (draw_custom_shape takes one colour)."""
        import gpu
        colour = self.color_highlight if self.is_highlight else self.color
        alpha = self.alpha_highlight if self.is_highlight else self.alpha
        fill = plane_fill(colour)
        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(self.line_width)
        for kind, (batch, shader) in getattr(self, "draw_shapes", ()):
            if smooth and kind == 'LINES':
                draw_handle_line(self, batch, (*colour, alpha))
                continue
            shader.bind()
            shader.uniform_float("color", (*fill, alpha * PLANE_FILL) if kind == 'TRIS' else (*colour, alpha))
            with gpu.matrix.push_pop():
                gpu.matrix.multiply_matrix(self.matrix_world)
                batch.draw(shader)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')

    def draw_select(self, context, select_id):
        sh = getattr(self, "pick_shape", None)
        if sh is not None:
            self.draw_custom_shape(sh, select_id=select_id)


RING_PICK_PX = 10.0     # a press this close to a drawn ring (x UI scale) grabs it, about as far as Blender's rings


class ALLSET_GT_maya_ring(Gizmo):
    """A Rotate axis ring: only its front half is drawn and picked (picked on screen, ahead of the trackball)."""
    bl_idname = RING_GIZMO

    __slots__ = ("handle_role", "handle_axis")

    def _arcs(self, context):
        rv3d = context.region_data
        if rv3d is None:
            return []
        view_z = rv3d.view_matrix.inverted_safe().col[2].xyz.normalized()
        return front_arcs(self.matrix_world, view_z)

    def draw(self, context):
        from gpu_extras.batch import batch_for_shader
        colour = self.color_highlight if self.is_highlight else self.color
        alpha = self.alpha_highlight if self.is_highlight else self.alpha
        width = self.line_width * context.preferences.system.ui_scale
        with handle_polyline(width, (*colour[:3], alpha), antialiasing(context)) as shader:
            for arc in self._arcs(context):
                batch_for_shader(shader, 'LINE_STRIP', {"pos": [tuple(p) for p in arc]}).draw(shader)

    def test_select(self, context, location):
        from bpy_extras.view3d_utils import location_3d_to_region_2d
        region, rv3d = context.region, context.region_data
        if rv3d is None:
            return -1
        limit = RING_PICK_PX * context.preferences.system.ui_scale
        mouse = Vector((location[0], location[1]))
        for arc in self._arcs(context):
            pts = [location_3d_to_region_2d(region, rv3d, p) for p in arc]
            for a, b in zip(pts, pts[1:]):
                if a is None or b is None:
                    continue
                ab = b - a
                t = 0.0 if ab.length_squared < 1e-12 else max(0.0, min(1.0, (mouse - a).dot(ab) / ab.length_squared))
                if (a + ab * t - mouse).length <= limit:
                    return 0
        return -1


# Maya = / - (operators/manip.ALLSET_OT_manip_size): the kit manipulator's own size factor for this session. Not
# Blender's gizmo_size preference, which the kit never writes.
SIZE = [1.0]
PIVOT_RING_CACHE = {}  # region pointer -> (plain numeric signature, projected ring paths)
_PIVOT_RING_POINTS = tuple(Vector(p) for p in _ring(1.0, 48)[::2])


def _cache_pivot_rings(context, handles, editing):
    """Share the rendered ring strokes with preselect; keep no live UI references."""
    key = context.region.as_pointer()
    if not editing:
        PIVOT_RING_CACHE.pop(key, None)
        return
    matrices = [gz.matrix_world.copy() for gz, role, _axis in handles if role == 'PIVOT_RING']
    region, projection = context.region, context.region_data.perspective_matrix
    signature = (region.width, region.height, tuple(v for row in projection for v in row),
                 tuple(v for matrix in matrices for row in matrix for v in row))
    previous = PIVOT_RING_CACHE.get(key)
    if previous is not None and previous[0] == signature:
        return
    from ..operators import preselect
    paths = []
    for matrix in matrices:
        xy, front = preselect.project([matrix @ p for p in _PIVOT_RING_POINTS], projection, region.width, region.height)
        if front.all():
            paths.append(xy)
    PIVOT_RING_CACHE[key] = (signature, paths)


def scale_basis(context):
    """World size of one arrow unit is set by the draw scale; this is the px factor."""
    return ARROW_PX / 75.0 * context.preferences.view.gizmo_size * SIZE[0] / BASE_PX_PER_UNIT


# Pixels one gizmo unit spans with use_draw_scale and scale_basis 1 at gizmo_size 75.
BASE_PX_PER_UNIT = 75.0


class ALLSET_GGT_xform(GizmoGroup):
    bl_idname = GROUP
    bl_label = "Maya Manipulator"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    # TOOL_FALLBACK_KEYMAP like Blender's transform gizmo: without it the tool loses its select
    # fallback (a marquee in empty space does nothing).
    bl_options = {'3D', 'PERSISTENT', 'TOOL_FALLBACK_KEYMAP'}

    @classmethod
    def setup_keymap(cls, keyconfig):
        # Same keymap as Blender's transform gizmo: the Maya keyconfig's Smart Duplicate / Extrude
        # and active-handle items sit in front of gizmo_tweak there.
        return keyconfig.keymaps.new(name="Generic Gizmo Maybe Drag", space_type='EMPTY', region_type='WINDOW')

    @classmethod
    def poll(cls, context):
        space = context.space_data
        if space is None or space.type != 'VIEW_3D' or not space.show_gizmo or not space.show_gizmo_tool:
            return False
        if tool_kind(context) is None or not _has_selection(context):
            return False
        from . import channel_box
        from .. import preferences
        if (channel_box._slider['armed'] and channel_box._view3d_tool(context) == channel_box._slider['tool']
                and preferences.get(context).cb_manipulators in {'INVISIBLE', 'NONE'}):
            return False
        from . import in_view
        return not in_view.manip_visible(context)   # Maya: the extrude manipulator replaces it

    def setup(self, context):
        self.handles = []      # (gizmo, role, data)
        self._built_for = None

    def _clear(self):
        for gz, _role, _data in self.handles:
            self.gizmos.remove(gz)
        self.handles = []

    def _new(self, kind, role=None, axis=None):
        gz = self.gizmos.new(GIZMO)
        gz.build(kind)
        gz.handle_role, gz.handle_axis = role, axis       # read by operators/manip.py Ctrl+LMB
        gz.use_draw_scale = True
        gz.use_draw_modal = True
        gz.use_tooltip = False                           # Maya manipulators show no tooltip (#98)
        gz.line_width = 1.5
        gz.color_highlight = YELLOW
        gz.alpha = gz.alpha_highlight = ALPHA
        return gz

    def _ring(self, axis):
        gz = self.gizmos.new(RING_GIZMO)
        gz.handle_role, gz.handle_axis = 'RING', axis
        gz.use_draw_scale = True
        gz.use_draw_modal = True
        gz.use_tooltip = False
        gz.line_width = ROTATE_LINE
        gz.color_highlight = YELLOW
        gz.alpha = gz.alpha_highlight = ALPHA
        return gz

    def _dial(self, options=None, line_width=1.5):
        gz = self.gizmos.new("GIZMO_GT_dial_3d")
        if options is not None:
            gz.draw_options = options
        gz.use_draw_scale = True
        gz.use_draw_modal = True
        gz.use_tooltip = False                           # Maya manipulators show no tooltip (#98)
        gz.line_width = line_width
        gz.color_highlight = YELLOW
        gz.alpha = gz.alpha_highlight = ALPHA
        return gz

    def _build(self, context, kind, pivot):
        self._clear()
        if kind == 'TRANSLATE':
            for ax in 'XYZ':
                self.handles.append((self._new('ARROW', 'AXIS', ax), 'AXIS', ax))
            for pl in PLANES:
                self.handles.append((self._new('PLANE', 'PLANE', pl), 'PLANE', pl))
            self.handles.append((self._new('PIVOT_CENTER' if pivot else 'CENTER', 'CENTER'), 'CENTER', None))
            if pivot:
                for ax in 'XYZ':
                    self.handles.append((self._dial(), 'PIVOT_RING', ax))
        elif kind == 'ROTATE':
            # the trackball (outline drawn, whole disc picked where nothing else is), the view ring, then the axis
            # rings drawn and picked on their front half only. Blender keeps the first hit of its gizmo list,
            # which runs from the last made gizmo: the rings are made last.
            ball = self._dial({'FILL_SELECT'}, 1.0)
            ball.use_select_background = True
            self.handles.append((ball, 'TRACKBALL', None))
            self.handles.append((self._dial(set(), ROTATE_LINE), 'VIEW_RING', None))
            for ax in 'XYZ':
                self.handles.append((self._ring(ax), 'RING', ax))
        elif kind == 'RESIZE':
            for ax in 'XYZ':
                self.handles.append((self._new('SCALE_AXIS', 'AXIS', ax), 'AXIS', ax))
            for pl in PLANES:
                self.handles.append((self._new('PLANE', 'PLANE', pl), 'PLANE', pl))
            self.handles.append((self._new('CENTER_CUBE', 'CENTER'), 'CENTER', None))
        self._built_for = (kind, pivot)
        self._ops_for = None

    def _bind_ops(self, kind, otype, frame=None, clamp=False, live_move=False, slide=False, groups=False):
        """Point each handle at Blender's transform with its constraint and orientation."""
        op = {'TRANSLATE': "transform.translate", 'ROTATE': "transform.rotate", 'RESIZE': "transform.resize"}[kind]
        if frame is None:
            frame = Matrix.Identity(3)
        editing = getattr(self, "_built_for", None) == ('TRANSLATE', True)
        if editing:
            op = "allset.pivot_translate"
        for gz, role, data in self.handles:
            if kind == 'RESIZE' and role in ('AXIS', 'PLANE', 'CENTER'):
                # #200: Maya's scale drag (operators/manip_scale.py)
                props = gz.target_set_operator("allset.manip_scale")
                props.mode = role
                if role == 'AXIS':
                    props.axis = data
                elif role == 'PLANE':
                    props.plane = data
                props.orient_type = otype
            elif slide and kind == 'TRANSLATE' and not editing and role in ('AXIS', 'PLANE', 'CENTER'):
                # Maya Transform Constraint Edge / Surface: every Move handle slides the components
                props = gz.target_set_operator("allset.component_slide")
                if role in ('AXIS', 'PLANE'):
                    props.constraint_axis = (tuple(a == data for a in 'XYZ') if role == 'AXIS'
                                             else PLANES[data][0])
                    builtin = {'GLOBAL', 'LOCAL', 'NORMAL', 'GIMBAL', 'VIEW', 'CURSOR', 'PARENT'}
                    props.orient_type = otype if otype in builtin else 'GLOBAL'
                    props.orient_matrix = Matrix.Identity(3) if otype in builtin else frame
            elif role == 'AXIS':
                axes = tuple(a == data for a in 'XYZ')
                props = gz.target_set_operator("allset.component_scale" if clamp and kind == 'RESIZE' else op)
                props.constraint_axis = axes
                if not editing:
                    ALLSET_GGT_xform._orient(props, otype, frame)
                    props.release_confirm = True
            elif role == 'PLANE':
                props = gz.target_set_operator('allset.live_translate' if live_move else op)
                props.constraint_axis = PLANES[data][0]
                if not editing:
                    ALLSET_GGT_xform._orient(props, otype, frame)
                    props.release_confirm = True
            elif role == 'CENTER':
                props = gz.target_set_operator('allset.live_translate' if live_move else op)
                if not editing:
                    props.release_confirm = True
            elif role == 'PIVOT_RING':
                props = gz.target_set_operator("allset.pivot_rotate")
                props.axis = data
            elif role == 'RING':
                props = gz.target_set_operator(op)
                props.constraint_axis = tuple(a == data for a in 'XYZ')
                props.orient_axis = data
                ALLSET_GGT_xform._orient(props, otype, frame)
                props.release_confirm = True
            elif role == 'VIEW_RING':
                props = gz.target_set_operator(op)
                props.orient_type = 'VIEW'      # about the view axis
                props.orient_axis = 'Z'
                props.release_confirm = True
            elif role == 'TRACKBALL':
                props = gz.target_set_operator("transform.trackball")
                props.release_confirm = True
            if groups and props.bl_rna.identifier in {'TRANSFORM_OT_translate', 'TRANSFORM_OT_rotate',
                                                     'TRANSFORM_OT_trackball'}:
                operation = props.bl_rna.identifier.split('_OT_')[1]
                kwargs = {name: getattr(props, name) for name in props.keys()}
                if 'constraint_axis' in kwargs:
                    kwargs['constraint_axis'] = tuple(kwargs['constraint_axis'])
                if 'orient_matrix' in kwargs:
                    kwargs['orient_matrix'] = kwargs['orient_matrix'].copy()
                props = gz.target_set_operator("allset.group_transform")
                props.operation = operation
                for name, value in kwargs.items():
                    setattr(props, name, value)
        self._ops_for = (kind, otype, tuple(v for row in frame for v in row), clamp, live_move, slide, groups)

    @staticmethod
    def _orient(props, otype, frame):
        # Gizmo operator properties expose built-in enum values on Blender 5.2.
        # Supply the picked component axes explicitly for custom orientations.
        builtin = {'GLOBAL', 'LOCAL', 'NORMAL', 'GIMBAL', 'VIEW', 'CURSOR', 'PARENT'}
        props.orient_type = otype if otype in builtin else 'GLOBAL'
        props.orient_matrix_type = 'GLOBAL'
        props.orient_matrix = Matrix.Identity(3) if otype in builtin else frame

    def _slide_label(self, context):
        """The slide label follows the handle highlight: off when the mouse leaves the handle, on when it comes onto a
        Move handle with Ctrl+Shift already held (component mode, the pivot not edited)."""
        from ..operators import manip
        region = context.region
        if region is None:
            return
        ptr = region.as_pointer()
        if manip.SLIDE_HINT["drag"]:
            return                              # a slide drag: the label stays until it ends
        highlighted = any(gz.is_highlight and getattr(gz, "handle_role", None) for gz in self.gizmos)
        if manip.SLIDE_HINT["region"] == ptr:
            if not highlighted:
                manip.slide_hint_clear()        # the mouse left the handle
        elif (highlighted and manip.MOUSE["held"] and manip.MOUSE["region"] == ptr and context.mode == 'EDIT_MESH'
              and tool_kind(context) == 'TRANSLATE' and self._built_for != ('TRANSLATE', True)
              and not any(gz.is_modal for gz in self.gizmos)
              and not manip.slide_hint_stale(context)):
            manip.slide_hint_show(region, manip.MOUSE["pos"])

    def draw_prepare(self, context):
        self._slide_label(context)
        kind = tool_kind(context)
        if kind is None:
            return
        pivot = kind == 'TRANSLATE' and pivot_edit(context)
        if self._built_for != (kind, pivot):
            self._build(context, kind, pivot)
        scene = context.scene
        otype = slot_type(scene, kind)
        rv3d = context.region_data
        frame = axes_of(context, otype, rv3d)
        rings = frame
        if kind == 'ROTATE' and otype == 'GIMBAL' and context.view_layer.objects.active is not None:
            rings = gimbal_axes(context.view_layer.objects.active)
        if pivot and context.active_object is not None:
            from ..operators import pivot as pivot_ops
            frame, otype = pivot_axes(context), pivot_ops.ORIENT_NAME
        from ..operators import component_scale
        scale_drag = component_scale.DRAG if kind == 'RESIZE' else None
        if scale_drag is not None:
            frame, otype = scale_drag._frame, 'GLOBAL'
        clamp = kind == 'RESIZE' and component_scale.enabled(context)
        from ..operators import live_translate
        live_move = kind == 'TRANSLATE' and not pivot and live_translate.enabled(context)
        from ..operators import xform_constraint
        slide = kind == 'TRANSLATE' and not pivot and xform_constraint.active(context)
        groups = context.mode == 'OBJECT' and bool(group.hidden_groups(context))
        signature = (kind, otype, tuple(v for row in frame for v in row), clamp, live_move, slide, groups)
        if self._ops_for != signature and not any(gz.is_modal for gz, _role, _data in self.handles):
            self._bind_ops(kind, otype, frame=frame, clamp=clamp, live_move=live_move, slide=slide, groups=groups)
        if context.mode != 'OBJECT':
            pts, act = _edit_points(context)
        else:
            pts, act = _object_points(context)
        center = follow_centre(context, center_of(pts, act, scene.tool_settings.transform_pivot_point,
                                                  scene.cursor.location))
        if scale_drag is not None:
            center = scale_drag._centre
        hide = center is None
        view = rv3d.view_rotation.to_matrix() if rv3d is not None else Matrix.Identity(3)
        colours = axis_colours()
        s = scale_basis(context)
        for gz, role, data in self.handles:
            gz.hide = hide
            if hide:
                continue
            gz.scale_basis = s
            if role == 'AXIS':
                rot = frame @ _axis_rot(data)
                active = _is_active(kind, tuple(a == data for a in 'XYZ'))
                gz.color = ACTIVE if active else colours[data]
            elif role == 'PLANE':
                axes, normal, local = PLANES[data]
                rot = frame @ local
                gz.color = ACTIVE if _is_active(kind, axes) else colours[normal]
            elif role == 'RING':
                rot = _ring_rot(rings, data)
                gz.color = ACTIVE if _is_active(kind, tuple(a == data for a in 'XYZ')) else colours[data]
                gz.scale_basis = s * ROTATE_RING_R
            elif role in ('VIEW_RING', 'TRACKBALL'):
                rot = view
                if role == 'VIEW_RING':     # light blue, #fdff88 while it is the active handle
                    h = _active_handle(kind)
                    gz.color = ACTIVE if h is not None and h.get("orient_type") == 'VIEW' else CENTER_IDLE
                else:
                    gz.color = TRACKBALL
                gz.scale_basis = s * ROTATE_RING_R * (VIEW_RING if role == 'VIEW_RING' else 1.0)
            elif role == 'CENTER':
                # Maya: the centre (free move / uniform scale) is the active handle by default, drawn #fdff88;
                # light blue while an axis or plane is active
                rot = frame if kind == 'RESIZE' else view
                gz.color = ACTIVE if _is_active(kind, None) else CENTER_IDLE
            else:   # PIVOT_RING
                rot = frame @ _axis_rot(data)
                gz.color = colours[data]
                gz.scale_basis = s * PIVOT_RING_R
            gz.matrix_basis = Matrix.Translation(center) @ rot.to_4x4()
        _cache_pivot_rings(context, self.handles, pivot and not hide)


classes = (ALLSET_GT_maya_handle, ALLSET_GT_maya_ring, ALLSET_GGT_xform)

SLIDE_LABEL = "slide"
_slide_draw = []


def _draw_slide_label():
    """The "slide" label under the mouse while Ctrl+Shift is held over a Move handle in component mode (Maya's
    slide cursor)."""
    from ..operators import manip
    region = bpy.context.region
    if not manip.SLIDE_HINT["region"] or region is None or manip.SLIDE_HINT["region"] != region.as_pointer():
        return
    if bpy.context.mode != 'EDIT_MESH' or (not manip.SLIDE_HINT["drag"] and manip.slide_hint_stale(bpy.context)):
        manip.SLIDE_HINT["region"] = 0      # a drag, a slide or a marking menu took over
        return
    import blf
    s = bpy.context.preferences.system.ui_scale
    x, y = manip.SLIDE_HINT["pos"]
    font = 0
    blf.size(font, 11 * s)
    w, h = blf.dimensions(font, SLIDE_LABEL)
    tx, ty = x + 6 * s - w / 2, y - 22 * s - h
    blf.enable(font, blf.SHADOW)
    blf.shadow(font, 3, 0.0, 0.0, 0.0, 1.0)
    blf.shadow_offset(font, 1, -1)
    blf.color(font, 1.0, 1.0, 1.0, 1.0)
    blf.position(font, tx, ty, 0)
    blf.draw(font, SLIDE_LABEL)
    blf.disable(font, blf.SHADOW)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    _slide_draw.append(bpy.types.SpaceView3D.draw_handler_add(_draw_slide_label, (), 'WINDOW', 'POST_PIXEL'))
    safe_reg.blender_class("VIEW3D_PT_active_tool").append(draw_tool_settings)
    patch_tools()
    bpy.app.timers.register(_ensure_timer, first_interval=0.1, persistent=True)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    SIZE[0] = 1.0
    PIVOT_RING_CACHE.clear()
    while _slide_draw:
        bpy.types.SpaceView3D.draw_handler_remove(_slide_draw.pop(), 'WINDOW')
    from ..operators import manip
    manip.SLIDE_HINT["region"] = 0
    manip.SLIDE_HINT["drag"] = False
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if bpy.app.timers.is_registered(_ensure_timer):
        bpy.app.timers.unregister(_ensure_timer)
    unpatch_tools()
    try:
        ensure_tools(False)
    except (ReferenceError, AttributeError):
        pass
    safe_reg.blender_class("VIEW3D_PT_active_tool").remove(draw_tool_settings)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
