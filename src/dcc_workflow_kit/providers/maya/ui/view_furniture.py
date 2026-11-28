# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya view furniture in the 3D View: ViewCube (top right), axis triad (bottom left), camera name label
(bottom centre), in place of Blender's navigation gizmo and text info.

The kit's views: ViewCube 65 px, 26 px from the view's right and 27 px from its top, white faces at
opacity 0.5 (FRONT/RIGHT/TOP readable in the default persp), only in the active panel of a four view;
label "persp" / "top -Y" ... 11 px #e3e3e3, baseline 9 px above the bottom, centred 9 px left of the
middle; axis triad origin 26 px from the left and bottom, 13 px lines, lower-case letters.

A view gets these when Blender's navigation gizmo is off in it (``show_gizmo_navigate``; the Maya Workflow Kit
template turns it and ``overlay.show_text`` off): the Maya furniture replaces Blender's. What is shown is
global like Maya's HUD / ViewCube preferences (add-on preferences ``maya_viewcube``,
``maya_camera_names``, ``maya_view_axis``). ``view_navigation`` = 'BLENDER' (#209) shows Blender's navigation gizmo
in those views instead of the ViewCube.

The triad shows Blender's axes (Z up): Maya's Y-up cannot be had and the
letters have to match the Channel Box channels. The camera labels are Maya's camera names with Maya's
Y-up view direction ("top -Y", "front -Z"): they name Maya's cameras, not axes.

Code: view_furniture_geometry (sizes, projection, hit tests), view_furniture_state (Maya views, navigation
gizmo choice, asset shelf strip), view_furniture_draw (GPU drawing); this module keeps the ViewCube gizmo, its
operators and menu, the drag tumble, register / unregister and re-exports.
"""

import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from .view_furniture_geometry import (CONTROL_NAMES, CUBE_ALPHA, CUBE_EYE, CUBE_INSET, CUBE_PX,  # noqa: F401
                                      FACE_NAMES, FACES, LABEL_BASELINE, LABEL_PX, LABEL_RGB, LABEL_SHIFT,
                                      MAYA_PERSP_DIR, MAYA_VIEW_H, ORBIT_CONTROLS, SIDE_LABELS, SMALL_EXP,
                                      TRIAD_INSET, TRIAD_LEN, _PX_PER_UNIT, _arc_arrow, _bounds, _control_at,
                                      _cube_rotation, _extent, _face_aligned, _maya_extent, _project_cube_point,
                                      _roll_arrows, _scale, _to_view, control_layout, cube_size, faces_2d,
                                      hit_face, label_camera, label_for, layout, point_in_poly, triad)
from .view_furniture_state import (_APPLY_LATER, _HANDLERS, _HIDDEN, _PENDING, _SAVING, _SHOWN,  # noqa: F401
                                   _apply_later, _apply_tick, _check_strip, _handle, _hideable, _load_post,
                                   _load_pre, _prefs, _remove_handler, _save_post, _save_pre, _show_strips,
                                   _spaces, _strip_later, _toggle_strip, apply_navigation, blender_gizmo_wanted,
                                   cube_wanted, maya_view, strip_action)
from .view_furniture_draw import (_batches, _cached_batch, _cube_face_batch, _cube_plan, _draw_controls,  # noqa: F401
                                  _draw_hud, _draw_strip, _face_label, _face_label_matrix, _fill, _hud_callback,
                                  _lines, _plan,
                                  _plans, _sh, _shader, _strip_batch, _text, _triad_plan, draw_cube, hud_lens,
                                  hud_lines, timecode)

# Four view: the ViewCube shows in one panel only (Maya: the active panel), the last one the mouse was in.
_ACTIVE = {"region": None}
_PREPARED = {}      # gizmo group pointer -> the button settings it last wrote (draw_prepare)


def _note_panel(area):
    from . import playback_redraw
    playback_redraw.note_panel(area)


def _cube_here(context):
    space, region = context.space_data, context.region
    if not space.region_quadviews:
        return True
    if _ACTIVE["region"] is None:
        return region.data == space.region_3d
    return region.as_pointer() == _ACTIVE["region"]


# --- ViewCube gizmo -------------------------------------------------------------------------

# Dragging the ViewCube tumbles the view like Maya: the same way round as Alt+LMB, CUBE_TUMBLE_RATIO times as far
# for the same mouse distance (a 60 px drag turns the view about 35 degrees where Alt+LMB turns it 24), and nothing
# snaps on release. A press that doesn't move past Blender's drag threshold is a click on the face.
CUBE_TUMBLE_RATIO = 35.36 / 24.0


def tumble_rate(context):
    """Radians per pixel of a ViewCube drag: Blender's turntable sensitivity (the speed of Alt+LMB) x the ratio."""
    prefs = context.preferences
    return prefs.inputs.view_rotate_sensitivity_turntable / (prefs.system.ui_scale or 1.0) * CUBE_TUMBLE_RATIO


def turntable(q, dx, dy, rate):
    """``q`` (a view rotation) turned by a drag of (dx, dy) px: around the world Z axis by dx and around the view's
    own X axis by dy, the way Blender's turntable Alt+LMB turns it (sideways reversed while the view is upside
    down)."""
    reverse = -1.0 if (q @ Vector((0.0, 1.0, 0.0))).z < 0.0 else 1.0
    x_axis = q @ Vector((1.0, 0.0, 0.0))
    turned = Quaternion((0.0, 0.0, 1.0), -dx * rate * reverse) @ Quaternion(x_axis, dy * rate) @ q
    turned.normalize()
    return turned


def _view_camera(context):
    """The camera object a camera view looks through, else None."""
    rv, space = context.region_data, context.space_data
    if rv is None or rv.view_perspective != 'CAMERA' or space is None:
        return None
    return space.camera or context.scene.camera


class CameraTumble:
    """A ViewCube drag in a camera view moves the camera as Alt+LMB does there (Lock Camera to View): the camera
    turns like ``turntable`` around the point on its axis at the depth of the view centre, its top parent moves
    instead when the camera's Camera Parent Lock is on, and locked channels stay. Every step is taken from the
    press, so the drag can be put back exactly."""

    def __init__(self, context, camera):
        rv = context.region_data
        m = camera.matrix_world.normalized()
        self.rotation = m.to_quaternion()
        eye = m.translation
        forward = self.rotation @ Vector((0.0, 0.0, -1.0))
        depth = forward.dot(rv.view_location - eye)
        if depth < 1e-6:                           # the view centre behind the camera
            depth = 1.0
        self.pivot = eye + forward * depth
        self.view = (rv.view_location.copy(), rv.view_distance)
        rv.view_location, rv.view_distance = self.pivot, depth     # the view centre on the camera's axis
        target = camera
        if camera.use_camera_lock_parent:
            while target.parent is not None:
                target = target.parent
        self.name = target.name
        self.world = target.matrix_world.copy()
        self.basis = target.matrix_basis.copy()
        self.channels = (target.location.copy(), target.rotation_euler.copy(), target.rotation_quaternion.copy(),
                         tuple(target.rotation_axis_angle), target.scale.copy())

    def turn(self, dx, dy, rate):
        """The camera after a drag of (dx, dy) px from the press."""
        ob = bpy.data.objects.get(self.name)
        if ob is None:
            return
        spin = (turntable(self.rotation, dx, dy, rate) @ self.rotation.inverted()).to_matrix().to_4x4()
        ob.matrix_world = Matrix.Translation(self.pivot) @ spin @ Matrix.Translation(-self.pivot) @ self.world
        loc, eul, quat, axis_angle, scale = self.channels
        if ob.rotation_mode not in {'QUATERNION', 'AXIS_ANGLE'}:     # the Euler angles nearest the old ones
            ob.rotation_euler = ob.rotation_euler.to_matrix().to_euler(ob.rotation_mode, eul)
        for i in range(3):
            if ob.lock_location[i]:
                ob.location[i] = loc[i]
            if ob.lock_rotation[i]:
                ob.rotation_euler[i] = eul[i]
                ob.rotation_quaternion[i + 1] = quat[i + 1]
                ob.rotation_axis_angle[i + 1] = axis_angle[i + 1]
            if ob.lock_scale[i]:
                ob.scale[i] = scale[i]
        if ob.lock_rotations_4d and ob.lock_rotation_w:
            ob.rotation_quaternion[0] = quat[0]
            ob.rotation_axis_angle[0] = axis_angle[0]

    def cancel(self, context):
        ob = bpy.data.objects.get(self.name)
        if ob is not None:
            ob.matrix_basis = self.basis
        rv = context.region_data
        rv.view_location, rv.view_distance = self.view


def _drag_threshold(context):
    prefs = context.preferences
    return max(1.0, prefs.inputs.drag_threshold_mouse * (prefs.system.ui_scale or 1.0))


def _tumble_locked(context):
    """Maya's top / front / side views don't tumble (the kit's ortho lock, as for Alt+LMB)."""
    from ..operators import view
    p = _prefs()
    return view.tumble_locked(context.region_data, getattr(p, "lock_ortho_tumble", True))


class ALLSET_OT_view_cube_face(bpy.types.Operator):
    """Look at the view from this side; a perspective view stays perspective, like Maya's persp camera"""
    # a drag from a face tumbles the view instead (invoke / modal)
    bl_idname = 'allset.view_cube_face'
    bl_label = 'ViewCube Face'
    bl_options = {'INTERNAL'}

    type: bpy.props.EnumProperty(items=[(name, name.title(), '') for name in FACE_NAMES])

    @classmethod
    def poll(cls, context):
        return bpy.ops.view3d.view_axis.poll()

    def execute(self, context):
        rv = context.region_data
        previous = rv.view_perspective if rv is not None else None
        result = bpy.ops.view3d.view_axis('INVOKE_DEFAULT', type=self.type)
        if previous == 'PERSP' and rv.view_perspective == 'ORTHO':
            rv.view_perspective = 'PERSP'
        return result

    def invoke(self, context, event):
        rv = context.region_data
        if rv is None or event.type != 'LEFTMOUSE' or event.value != 'PRESS':
            return self.execute(context)
        self._start = self._last = (event.mouse_x, event.mouse_y)
        self._dragging = self._locked = False
        self._before = self._camera = None
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _begin_drag(self, context):
        rv = context.region_data
        self._dragging = True
        if _tumble_locked(context):
            self._locked = True
            return
        self._locked = False
        camera = _view_camera(context)
        if camera is not None:
            # Looking through a camera: the camera moves, as with Alt+LMB (which turns the view's Lock Camera to
            # View on); the view stays the camera's
            from ..operators import view
            view.camera_navigation(context)
            self._camera = CameraTumble(context, camera)
            return
        self._before = (rv.view_perspective, rv.view_rotation.copy())
        if rv.view_perspective == 'CAMERA':      # no camera object to move: the free view from the visible one
            visible = _cube_rotation(rv)
            rv.view_perspective = 'PERSP'
            rv.view_rotation = visible

    def modal(self, context, event):
        rv = context.region_data
        if rv is None:
            return {'CANCELLED'}
        if event.type == 'MOUSEMOVE':
            x, y = event.mouse_x, event.mouse_y
            if not self._dragging:
                if math.hypot(x - self._start[0], y - self._start[1]) < _drag_threshold(context):
                    return {'RUNNING_MODAL'}
                self._begin_drag(context)
                self._last = self._start            # the whole drag counts, from the press
            if self._camera is not None:
                self._camera.turn(x - self._start[0], y - self._start[1], tumble_rate(context))
                context.area.tag_redraw()
            elif not self._locked:
                rv.view_rotation = turntable(rv.view_rotation, x - self._last[0], y - self._last[1],
                                             tumble_rate(context))
                context.area.tag_redraw()
            self._last = (x, y)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if self._dragging:
                if self._camera is not None and not context.mode.startswith('EDIT'):
                    bpy.ops.ed.undo_push(message="Rotate View")     # one undo step for the move, like Alt+LMB
                return {'FINISHED'}                 # a drag: no snap to a face
            return self.execute(context)
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            if self._camera is not None:
                self._camera.cancel(context)
                context.area.tag_redraw()
            elif self._before is not None:
                rv.view_rotation = self._before[1]
                if self._before[0] == 'CAMERA':
                    rv.view_perspective = 'CAMERA'
                context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class ALLSET_OT_view_cube_control(bpy.types.Operator):
    """Navigate the current viewport without moving the scene camera"""
    bl_idname = 'allset.view_cube_control'
    bl_label = 'ViewCube Navigation'
    bl_options = {'INTERNAL'}

    action: bpy.props.EnumProperty(items=[(name, name.replace('_', ' ').title(), '')
                                         for name in CONTROL_NAMES])

    @classmethod
    def poll(cls, context):
        return (context.area is not None and context.area.type == 'VIEW_3D'
                and context.region is not None and context.region.type == 'WINDOW'
                and context.region_data is not None)

    def execute(self, context):
        rv = context.region_data
        if self.action == 'MENU':
            bpy.ops.wm.call_menu('INVOKE_DEFAULT', name=ALLSET_MT_view_cube.__name__)
            return {'FINISHED'}
        if self.action == 'HOME':
            previous = rv.view_perspective
            if previous == 'CAMERA':
                rv.view_perspective = 'PERSP'
            try:
                result = bpy.ops.allset.view_home('EXEC_DEFAULT', True) if bpy.ops.allset.view_home.poll() else {'CANCELLED'}
            except RuntimeError:
                result = {'CANCELLED'}
            if result != {'FINISHED'} and previous == 'CAMERA':
                rv.view_perspective = previous
            return result
        if self.action not in {'ROLL_LEFT', 'ROLL_RIGHT'} or not _face_aligned(rv):
            return {'CANCELLED'}
        if not bpy.ops.view3d.view_roll.poll():
            return {'CANCELLED'}
        previous = rv.view_perspective
        if previous == 'CAMERA':
            visible_rotation = _cube_rotation(rv)
            previous_rotation = rv.view_rotation.copy()
            rv.view_perspective = 'PERSP'
            rv.view_rotation = visible_rotation
        try:
            result = bpy.ops.view3d.view_roll('EXEC_DEFAULT', True, type='ANGLE',
                        angle=(1 if self.action == 'ROLL_LEFT' else -1) * math.pi / 2)
        except RuntimeError:
            result = {'CANCELLED'}
        if result != {'FINISHED'} and previous == 'CAMERA':
            rv.view_rotation = previous_rotation
            rv.view_perspective = previous
        context.area.tag_redraw()
        return result

    def invoke(self, context, event):
        # Open the popup after release so the click that opened it cannot choose an item.
        if self.action == 'MENU' and event.value == 'PRESS':
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        return self.execute(context)

    def modal(self, context, event):
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return self.execute(context)
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class ALLSET_MT_view_cube(bpy.types.Menu):
    bl_label = 'ViewCube'

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_REGION_WIN'
        layout.operator('allset.view_cube_control', text='Home View').action = 'HOME'
        layout.operator('view3d.view_persportho', text='Perspective / Orthographic')
        layout.separator()
        for name in FACE_NAMES:
            layout.operator('allset.view_cube_face', text=name.title()).type = name


def _ensure_cube_controls(gizmo):
    if getattr(gizmo, '_view_controls_ready', False) == 2:
        return
    for i, name in enumerate(CONTROL_NAMES + ORBIT_CONTROLS, len(FACE_NAMES)):
        if name in ORBIT_CONTROLS:
            op = gizmo.target_set_operator('view3d.view_orbit', index=i)
            op.type = name.replace('_', '')
            op.angle = math.pi / 2
        else:
            op = gizmo.target_set_operator('allset.view_cube_control', index=i)
            op.action = name
    gizmo._view_controls_ready = 2


class ALLSET_GT_view_cube(bpy.types.Gizmo):
    bl_idname = "ALLSET_GT_view_cube"

    def setup(self):
        self.hover = None
        self.use_tooltip = False          # like the kit's other gizmos: no Blender operator tooltip
        # one face operator per face: test_select returns the face's index as the part
        for i, name in enumerate(FACE_NAMES):
            op = self.target_set_operator("allset.view_cube_face", index=i)
            op.type = name

    def draw(self, context):
        if not _cube_here(context):
            return
        _ensure_cube_controls(self)
        import gpu
        from mathutils import Matrix
        region = context.region
        w, h = region.width, region.height
        ortho = Matrix(((2 / w, 0, 0, -1), (0, 2 / h, 0, -1), (0, 0, -1, 0), (0, 0, 0, 1)))
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(ortho)
            gpu.state.blend_set('ALPHA')
            gpu.state.depth_test_set('NONE')
            draw_cube(context, self.hover if self.is_highlight else None,
                      CUBE_ALPHA[1] if self.is_highlight else CUBE_ALPHA[0])
            gpu.state.blend_set('NONE')

    def test_select(self, context, location):
        _ensure_cube_controls(self)
        space, region = context.space_data, context.region
        _note_panel(context.area)          # the mouse is in this panel: Update View: Active redraws it
        if space.region_quadviews and _ACTIVE["region"] != region.as_pointer():
            _ACTIVE["region"] = region.as_pointer()
            context.area.tag_redraw()
        s = _scale()
        size = cube_size(region.width, region.height, s)
        centre, _l, _t = layout(_bounds(context), s, size)
        faces = faces_2d(_cube_rotation(context.region_data), centre, size)
        controls = control_layout(context, centre, size)
        # Preserve every existing face target even where a control's radius overlaps it.
        name = hit_face(faces, *location)
        if name is None:
            name = _control_at(centre, controls, location, _face_aligned(context.region_data))
        if name != self.hover:
            self.hover = name
            context.area.tag_redraw()
        names = FACE_NAMES + CONTROL_NAMES + ORBIT_CONTROLS
        return names.index(name) if name else -1


class ALLSET_GGT_view_cube(bpy.types.GizmoGroup):
    bl_idname = "ALLSET_GGT_view_cube"
    bl_label = "Maya ViewCube"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT', 'SCALE'}

    @classmethod
    def poll(cls, context):
        prefs = _prefs()
        space = context.space_data
        return prefs is not None and cube_wanted(prefs) and maya_view(space) and space.show_gizmo \
            and context.region_data is not None

    def setup(self, context):
        self.gizmos.new(ALLSET_GT_view_cube.bl_idname)
        self.camera_button = self.gizmos.new('GIZMO_GT_button_2d')
        self.projection_button = self.gizmos.new('GIZMO_GT_button_2d')
        for button, operator in ((self.camera_button, 'view3d.view_camera'),
                                 (self.projection_button, 'view3d.view_persportho')):
            button.draw_options = {'OUTLINE', 'BACKDROP'}
            button.show_drag = False
            button.color = (0.0, 0.0, 0.0)
            button.alpha = 0.0
            button.color_highlight = (0.5, 0.5, 0.5)
            button.alpha_highlight = 0.5
            button.target_set_operator(operator)

    def draw_prepare(self, context):
        s = _scale()
        region, rv = context.region, context.region_data
        size = cube_size(region.width, region.height, s)
        centre, _label, _triad = layout(_bounds(context), s, size)
        hide = not _cube_here(context) or not _prefs().show_view_cube_buttons
        icons = ('VIEW_CAMERA' if rv.view_perspective == 'CAMERA' else 'VIEW_CAMERA_UNSELECTED',
                 'VIEW_PERSPECTIVE' if rv.is_perspective else 'VIEW_ORTHO')
        places = tuple((centre[0] + size * .5, centre[1] - size * .8 - (18 + 30 * i) * s) for i in range(2))
        state = (hide, 14 * s, places, icons)
        key = self.as_pointer() if hasattr(self, "as_pointer") else id(self)
        if _PREPARED.get(key) == state:
            return          # every redraw of a playing view: the same settings, each gizmo write costs Python time
        if len(_PREPARED) > 32:
            _PREPARED.clear()
        _PREPARED[key] = state
        for button, (x, y), icon in zip((self.camera_button, self.projection_button), places, icons):
            button.hide = hide
            button.scale_basis = 14 * s
            button.matrix_basis.translation = (x, y, 0)
            button.icon = icon


classes = (ALLSET_OT_view_cube_face, ALLSET_OT_view_cube_control, ALLSET_MT_view_cube, ALLSET_GT_view_cube, ALLSET_GGT_view_cube)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    _handle.append(bpy.types.SpaceView3D.draw_handler_add(_hud_callback, (), 'WINDOW', 'POST_PIXEL'))
    for name, fn in _HANDLERS:
        getattr(bpy.app.handlers, name).append(fn)
    try:
        apply_navigation()
    except AttributeError:               # Blender start: restricted bpy.data while add-ons register
        _apply_later()


def unregister():
    for name, fn in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn in handlers:
            handlers.remove(fn)
    if _APPLY_LATER and bpy.app.timers.is_registered(_apply_tick):
        bpy.app.timers.unregister(_apply_tick)
    _APPLY_LATER.clear()
    _SAVING.clear()
    try:
        apply_navigation(False)
    except AttributeError:               # restricted bpy.data (quit): nothing of this session is saved any more
        pass
    finally:
        _SHOWN.clear()
    _remove_handler()
    _show_strips()
    _ACTIVE["region"] = None
    _shader.clear()
    _batches.clear()
    _plans.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
