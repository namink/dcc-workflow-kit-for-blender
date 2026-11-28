# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya navigation in the 3D views: Alt+LMB tumble (not in axis-aligned ortho views), Alt+MMB track, Alt+RMB dolly,
Alt+LMB+MMB dolly that carries on as tumble / track when one button is let go (``allset.nav_chord``), Alt+LMB
tumble under Emulate 3 Button Mouse, and Alt+Shift drags locked to one axis. Entry points ``start_tumble``,
``start_track``, ``chord_held`` / ``chord_mode``, ``dolly_distance``; the 2D editors are in view_nav_2d.
"""

import bpy
from mathutils import Vector

from .. import live_refs

# --- tumble -------------------------------------------------------------------


def tumble_locked(rv3d, lock):
    """Maya top/front/side views do not tumble."""
    return bool(lock) and rv3d.view_perspective == 'ORTHO' and rv3d.is_orthographic_side_view


def camera_navigation(context):
    """Maya: tumbling a view that looks through a camera moves that camera (#9). Blender leaves the camera view
    unless the view's Lock Camera to View is on, so turn it on there; a Maya-locked camera (locked channels) stays
    put because Blender's camera lock keeps locked channels."""
    space, rv3d = context.space_data, context.region_data
    if space is not None and space.type == 'VIEW_3D' and rv3d is not None and rv3d.view_perspective == 'CAMERA':
        space.lock_camera = True


class ALLSET_OT_tumble(bpy.types.Operator):
    """Tumble the view (Maya Alt+LMB); locked in axis-aligned ortho views"""
    bl_idname = "allset.tumble"
    bl_label = "Tumble"

    @classmethod
    def poll(cls, context):
        return context.region_data is not None

    def invoke(self, context, event):
        start_tumble(context, chord=event.type == 'LEFTMOUSE')
        return {'FINISHED'}


class ALLSET_OT_track_view(bpy.types.Operator):
    """Track the view (Maya Alt+MMB); pressing LMB as well dollies"""
    bl_idname = "allset.track_view"
    bl_label = "Track"

    @classmethod
    def poll(cls, context):
        return context.region_data is not None

    def invoke(self, context, event):
        start_track(context, chord=event.type == 'MIDDLEMOUSE')
        return {'FINISHED'}


# --- Alt+LMB+MMB dolly (#325, #343) ------------------------------------------------------------------
# Maya dollies while both the left and the middle button are held with Alt (handy on a tablet pen), and letting go of
# one of them carries on with the button still held: LMB tumbles, MMB tracks. Blender's tumble / track modals run on;
# a watcher sits in front of the running navigation and, on each press / release of these two buttons, starts the
# navigation of the buttons now held with a new watcher in front of it, then passes the event on: the modal keymaps
# end Blender's tumble / track / zoom on it ("View3D Rotate / Move / Zoom Modal" CONFIRM items) and the chord dolly
# ends on either release.
NAV_MODALS = {"VIEW3D_OT_rotate", "VIEW3D_OT_move", "VIEW3D_OT_zoom", "ALLSET_OT_dolly"}
CHORD_BUTTONS = ('LEFTMOUSE', 'MIDDLEMOUSE')
CHORD_MODES = {frozenset({'LEFTMOUSE'}): 'TUMBLE', frozenset({'MIDDLEMOUSE'}): 'TRACK',
               frozenset(CHORD_BUTTONS): 'DOLLY'}


def chord_held(held, event_type, value):
    """The navigation buttons held after a mouse event, or None when the event does not change them (a quick
    second press can arrive as a double click)."""
    held = frozenset(held)
    if event_type not in CHORD_BUTTONS:
        return None
    if value in {'PRESS', 'DOUBLE_CLICK'} and event_type not in held:
        return held | {event_type}
    if value == 'RELEASE' and event_type in held:
        return held - {event_type}
    return None


def chord_mode(held):
    """Maya's Alt navigation for the held buttons: LMB tumble, MMB track, both dolly; None once both are let go."""
    return CHORD_MODES.get(frozenset(held))


def start_tumble(context, chord=False):
    """Start Blender's tumble (not in a locked ortho view); ``chord``: LMB is held, watch the middle button."""
    from .. import preferences
    if tumble_locked(context.region_data, preferences.get(context).lock_ortho_tumble):
        return
    camera_navigation(context)
    started = bpy.ops.view3d.rotate('INVOKE_DEFAULT')
    if chord and 'RUNNING_MODAL' in started:
        bpy.ops.allset.nav_chord('INVOKE_DEFAULT', held={'LEFTMOUSE'})


def start_track(context, chord=False):
    """Start Blender's track; ``chord``: MMB is held, watch the left button."""
    started = bpy.ops.view3d.move('INVOKE_DEFAULT')
    if chord and 'RUNNING_MODAL' in started:
        bpy.ops.allset.nav_chord('INVOKE_DEFAULT', held={'MIDDLEMOUSE'})


def start_chord_dolly(context):
    """Start the dolly of both buttons and watch for either release."""
    bpy.ops.allset.dolly('INVOKE_DEFAULT', chord=True)
    bpy.ops.allset.nav_chord('INVOKE_DEFAULT', held=set(CHORD_BUTTONS))


CHORD_STARTS = {'TUMBLE': lambda context: start_tumble(context, chord=True),
                'TRACK': lambda context: start_track(context, chord=True),
                'DOLLY': start_chord_dolly}


class ALLSET_OT_nav_chord(bpy.types.Operator):
    """Turn a running tumble / track into a dolly when the other mouse button is pressed too"""
    bl_idname = "allset.nav_chord"
    bl_label = "Navigation Chord"
    bl_options = {'INTERNAL'}

    held: bpy.props.EnumProperty(items=[(b, b, "") for b in CHORD_BUTTONS], default={'LEFTMOUSE'},
                                 options={'ENUM_FLAG', 'SKIP_SAVE'})

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        window = context.window
        if window is not None and not any(op.bl_idname in NAV_MODALS for op in live_refs.running_modals(window)):
            return {'FINISHED', 'PASS_THROUGH'}      # the navigation ended some other way
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            return {'FINISHED', 'PASS_THROUGH'}
        held = chord_held(self.held, event.type, event.value)
        if held is None:
            return {'PASS_THROUGH'}
        mode = chord_mode(held)
        if mode is not None:
            CHORD_STARTS[mode](context)
        return {'FINISHED', 'PASS_THROUGH'}


def emulated_alt_drag(context):
    """True when a middle press is really Alt+LMB turned into a middle drag by Blender's Emulate 3 Button Mouse
    (with Alt as its modifier): the converted press carries no Alt, but the Alt key is still held. None-safe: an
    OS that can't tell whether Alt is held gives False, so a real middle drag is never taken."""
    inputs = context.preferences.inputs
    if not getattr(inputs, "use_mouse_emulate_3_button", False):
        return False
    if getattr(inputs, "mouse_emulate_3_button_modifier", 'ALT') != 'ALT':
        return False
    from . import keystate
    return bool(keystate.is_down('LEFT_ALT') or keystate.is_down('RIGHT_ALT'))


class ALLSET_OT_emulated_tumble(bpy.types.Operator):
    """Alt+LMB tumble while Emulate 3 Button Mouse is on (Blender delivers that drag as a middle drag)"""
    bl_idname = "allset.emulated_tumble"
    bl_label = "Tumble (Emulated Middle Mouse)"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.region_data is not None

    def invoke(self, context, event):
        if event.alt or not emulated_alt_drag(context):
            return {'PASS_THROUGH'}
        return ALLSET_OT_tumble.invoke(self, context, event)


# --- Alt+RMB dolly (#51) -----------------------------------------------------------------
# Maya dollies with a left / right drag. Blender's view3d.zoom reads the drag axis from the
# user preferences (Vertical by default), which the kit no longer writes (#40), so the drag is read here.
DOLLY_PX_PER_DOUBLING = 150.0     # px of drag (at UI scale 1) that halve / double the view distance


def dolly_distance(distance0, dx, dy, ui_scale=1.0, invert=False):
    """View distance after a dolly drag of (dx, dy) px from ``distance0``: right (or up) = in,
    left (or down) = in with ``invert`` (Blender's Invert Zoom Direction preference)."""
    step = (dx + dy) / (DOLLY_PX_PER_DOUBLING * max(ui_scale, 0.1))
    return distance0 * (2.0 ** (step if invert else -step))


def drag_jump(region, dx, dy):
    """True when one mouse step of (dx, dy) px is a cursor warp (GRAB_CURSOR wrap at the edge, a pen tablet's
    absolute position) rather than a hand move: over half the region in one event. Such a step is dropped, or the
    dolly snaps the wrong way."""
    w = getattr(region, "width", 0) or 1000
    h = getattr(region, "height", 0) or 1000
    return abs(dx) > w / 2 or abs(dy) > h / 2


def invert_zoom(context):
    """Blender's Preferences > Input > Invert Zoom Direction (drag zoom), read only (#295)."""
    return bool(getattr(context.preferences.inputs, "invert_mouse_zoom", False))


class CameraDolly:
    """Alt+RMB in a view that looks through a camera, or through a light (Look Through Selected), moves that object
    like the dolly of the perspective view (#371): along its view axis toward the point the view turns around, by the
    same left / right or up / down drag. An orthographic camera changes its width instead (Maya Orthographic Width).
    Its top parent moves when the camera's Camera Parent Lock is on, locked Translate channels stay. Every step is
    taken from the press, so Esc puts it back exactly."""

    def __init__(self, context, ob):
        rv = context.region_data
        self.view = (rv.view_location.copy(), rv.view_distance)
        self.d0 = max(rv.view_distance, 1e-4)
        self.ortho = ob.type == 'CAMERA' and ob.data.type == 'ORTHO'
        self.camera = ob.name
        self.width0 = ob.data.ortho_scale if self.ortho else None
        m = ob.matrix_world.normalized()
        self.forward = (m.to_quaternion() @ Vector((0.0, 0.0, -1.0))).normalized()
        self.pivot = m.translation + self.forward * self.d0
        target = ob
        if ob.use_camera_lock_parent:
            while target.parent is not None:
                target = target.parent
        self.name = target.name
        self.location = target.location.copy()
        # world -> the target's own Translate channels (parents, parent inverse)
        above = target.matrix_world @ target.matrix_basis.inverted_safe()
        self.to_local = above.to_3x3().inverted_safe()

    def apply(self, context, distance):
        """The camera (or its width) for the view distance ``distance`` (``dolly_distance`` of the drag)."""
        ob = bpy.data.objects.get(self.camera)
        if ob is None:
            return
        if self.ortho:
            ob.data.ortho_scale = self.width0 * distance / self.d0
            return
        target = bpy.data.objects.get(self.name)
        if target is None:
            return
        step = self.to_local @ (self.forward * (self.d0 - distance))
        for i in range(3):
            if not target.lock_location[i]:
                target.location[i] = self.location[i] + step[i]
        # the point the view turns around stays where it was (Alt+LMB after the dolly turns around it)
        rv = context.region_data
        rv.view_location, rv.view_distance = self.pivot, distance

    def moved(self):
        ob = bpy.data.objects.get(self.camera)
        if ob is None:
            return False
        if self.ortho:
            return ob.data.ortho_scale != self.width0
        target = bpy.data.objects.get(self.name)
        return target is not None and target.location != self.location

    def cancel(self, context):
        ob = bpy.data.objects.get(self.camera)
        if ob is not None and self.ortho:
            ob.data.ortho_scale = self.width0
        target = bpy.data.objects.get(self.name)
        if target is not None and not self.ortho:
            target.location = self.location
        rv = context.region_data
        rv.view_location, rv.view_distance = self.view


class ALLSET_OT_dolly(bpy.types.Operator):
    """Dolly the view in / out with a left / right drag (Maya Alt+RMB)"""
    bl_idname = "allset.dolly"
    bl_label = "Dolly"
    bl_options = {'GRAB_CURSOR', 'BLOCKING'}

    # started from Alt+LMB+MMB: letting go of either button ends it
    chord: bpy.props.BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.region_data is not None

    def invoke(self, context, event):
        rv3d = context.region_data
        self._camera = None
        if rv3d.view_perspective == 'CAMERA':
            # through a camera: Maya's dolly moves it, with the same drag as in the perspective view (#9, #371)
            from .view_frame import view_camera
            camera_navigation(context)
            ob = view_camera(context, context.space_data)
            if ob is None:
                return {'CANCELLED'}
            self._camera = CameraDolly(context, ob)
        self._last = (event.mouse_x, event.mouse_y)
        self._drag = [0, 0]
        self._d0 = self._camera.d0 if self._camera is not None else rv3d.view_distance
        # the button that started it: RMB for Alt+RMB, LMB for the Dolly Tool (ui/camera_tools.py)
        self._button = event.type if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE'} else 'RIGHTMOUSE'
        self._ends = {'LEFTMOUSE', 'MIDDLEMOUSE'} if self.chord else {self._button}
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        rv3d = context.region_data
        if event.type == 'MOUSEMOVE':
            dx = event.mouse_x - self._last[0]
            dy = event.mouse_y - self._last[1]
            self._last = (event.mouse_x, event.mouse_y)
            if not drag_jump(context.region, dx, dy):
                self._drag[0] += dx
                self._drag[1] += dy
            distance = dolly_distance(self._d0, self._drag[0], self._drag[1],
                                      context.preferences.system.ui_scale or 1.0, invert_zoom(context))
            if self._camera is not None:
                self._camera.apply(context, distance)
            else:
                rv3d.view_distance = distance
            context.area.tag_redraw()
        elif event.type in self._ends and event.value == 'RELEASE':
            if self._camera is not None and self._camera.moved() and not context.mode.startswith('EDIT'):
                bpy.ops.ed.undo_push(message="Dolly")      # one undo step for the camera move, like Alt+LMB
            return {'FINISHED'}
        elif event.type == 'ESC' and event.value == 'PRESS':
            if self._camera is not None:
                self._camera.cancel(context)
            else:
                rv3d.view_distance = self._d0
            context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


# --- Alt+Shift drag: tumble / track locked to one axis ---------------------
# Maya : the first dominant drag direction (horizontal or
# vertical) is kept for the whole drag.

AXIS_THRESHOLD = 4   # px of movement before the axis is chosen


def choose_axis(dx, dy, threshold=AXIS_THRESHOLD):
    """'H', 'V' or None (not moved far enough yet)."""
    if max(abs(dx), abs(dy)) < threshold:
        return None
    return 'H' if abs(dx) >= abs(dy) else 'V'


def locked_offset(axis, dx, dy):
    """The drag offset kept for ``axis``."""
    return (dx, 0) if axis == 'H' else (0, dy)


def tumble_rotation(axis, dx, dy, rotation0, sensitivity):
    """Blender turntable rotation (view3d_navigate_rotate: Z by x, view right axis by y),
    one axis only. Returns the new ``view_rotation``."""
    from mathutils import Quaternion
    if axis == 'H':
        return Quaternion((0.0, 0.0, 1.0), -sensitivity * dx) @ rotation0
    right = rotation0 @ Vector((1.0, 0.0, 0.0))
    return Quaternion(right, sensitivity * dy) @ rotation0


class ALLSET_OT_view_axis_lock(bpy.types.Operator):
    """Tumble or track the view along one axis only (Maya Alt+Shift+drag)"""
    bl_idname = "allset.view_axis_lock"
    bl_label = "Axis-Locked Tumble/Track"
    bl_options = {'BLOCKING'}

    mode: bpy.props.EnumProperty(items=(("TUMBLE", "Tumble", ""), ("TRACK", "Track", "")))

    @classmethod
    def poll(cls, context):
        return context.region_data is not None and context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        from .. import preferences
        rv3d = context.region_data
        if self.mode == "TUMBLE" and tumble_locked(rv3d, preferences.get(context).lock_ortho_tumble):
            return {'FINISHED'}
        self._button = event.type
        self._start = (event.mouse_region_x, event.mouse_region_y)
        self._rot0 = rv3d.view_rotation.copy()
        self._loc0 = rv3d.view_location.copy()
        self._axis = None
        inputs = context.preferences.inputs
        self._sens = inputs.view_rotate_sensitivity_turntable / max(context.preferences.system.ui_scale, 0.1)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _apply(self, context, x, y):
        rv3d = context.region_data
        dx, dy = x - self._start[0], y - self._start[1]
        if self._axis is None:
            self._axis = choose_axis(dx, dy)
            if self._axis is None:
                return
        ox, oy = locked_offset(self._axis, dx, dy)
        if self.mode == "TUMBLE":
            rv3d.view_rotation = tumble_rotation(self._axis, ox, oy, self._rot0, self._sens)
            return
        from bpy_extras.view3d_utils import region_2d_to_location_3d
        sx, sy = self._start
        a = region_2d_to_location_3d(context.region, rv3d, (sx, sy), self._loc0)
        b = region_2d_to_location_3d(context.region, rv3d, (sx + ox, sy + oy), self._loc0)
        rv3d.view_location = self._loc0 - (b - a)

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self._apply(context, event.mouse_region_x, event.mouse_region_y)
            context.area.tag_redraw()
        elif event.type == self._button and event.value == 'RELEASE':
            return {'FINISHED'}
        elif event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            rv3d = context.region_data
            rv3d.view_rotation, rv3d.view_location = self._rot0, self._loc0
            context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}
