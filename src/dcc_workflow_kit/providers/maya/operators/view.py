# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya camera/view feel: ortho tumble lock, Alt+Shift axis-locked tumble/track, framing in all views,
view-change undo (``[`` / ``]``), Space-tap four-view toggle.
"""

import bpy
from mathutils import Vector

from .. import results
from . import framing, units

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
        ops = getattr(window, "modal_operators", None) if window is not None else None
        if ops is not None and not any(op.bl_idname in NAV_MODALS for op in ops):
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


def invert_zoom(context):
    """Blender's Preferences > Input > Invert Zoom Direction (drag zoom), read only (#295)."""
    return bool(getattr(context.preferences.inputs, "invert_mouse_zoom", False))


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
        if rv3d.view_perspective == 'CAMERA':
            camera_navigation(context)           # through a camera: Blender's zoom moves it (#9)
            bpy.ops.view3d.zoom('INVOKE_DEFAULT')
            return {'FINISHED'}
        self._start = (event.mouse_x, event.mouse_y)
        self._d0 = rv3d.view_distance
        # the button that started it: RMB for Alt+RMB, LMB for the Dolly Tool (ui/camera_tools.py)
        self._button = event.type if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE'} else 'RIGHTMOUSE'
        self._ends = {'LEFTMOUSE', 'MIDDLEMOUSE'} if self.chord else {self._button}
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        rv3d = context.region_data
        if event.type == 'MOUSEMOVE':
            dx = event.mouse_x - self._start[0]
            dy = event.mouse_y - self._start[1]
            rv3d.view_distance = dolly_distance(self._d0, dx, dy, context.preferences.system.ui_scale or 1.0,
                                                invert_zoom(context))
            context.area.tag_redraw()
        elif event.type in self._ends and event.value == 'RELEASE':
            return {'FINISHED'}
        elif event.type == 'ESC' and event.value == 'PRESS':
            rv3d.view_distance = self._d0
            context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


# --- Alt+RMB dolly in the UV / Image Editor (B4) ---------------------------------
# Maya dollies 2D panels with Alt+RMB too. IC's image.view_zoom reads the drag axis
# from Blender's Zoom Axis preference (factory Vertical), so like allset.dolly the drag is read here and applied with
# a plain image.view_zoom call with a factor (centred, like Blender's factory "Zoom to Mouse Position" off).
# Maya's UV Editor zooms in with a drag right or down and out with a drag left or up (#325).


def dolly_zoom_factor(dx, dy, ui_scale=1.0, invert=False):
    """Zoom factor for a drag step of (dx, dy) px: the inverse of ``dolly_distance`` (right / up = in,
    reversed with ``invert``)."""
    step = (dx + dy) / (DOLLY_PX_PER_DOUBLING * max(ui_scale, 0.1))
    return 2.0 ** (-step if invert else step)


def dolly_2d_factor(dx, dy, ui_scale=1.0, invert=False):
    """Zoom factor of a UV / Image Editor drag step of (dx, dy) px (y up): right / down = in, left / up = out, so a
    right-and-up drag cancels, like Maya's UV Editor; reversed with ``invert``."""
    return dolly_zoom_factor(dx, -dy, ui_scale, invert)


def dolly_2d_step(context, dx, dy):
    """Zoom the UV / Image Editor of ``context`` by one drag step; the factor applied (1.0 = none)."""
    factor = dolly_2d_factor(dx, dy, context.preferences.system.ui_scale or 1.0, invert_zoom(context))
    if abs(factor - 1.0) <= 1e-6:
        return 1.0
    bpy.ops.image.view_zoom('EXEC_DEFAULT', factor=factor)
    return factor


class ALLSET_OT_dolly_2d(bpy.types.Operator):
    """Zoom the UV / Image Editor in / out with a left / right drag (Maya Alt+RMB dolly)"""
    bl_idname = "allset.dolly_2d"
    bl_label = "Dolly 2D"
    bl_options = {'GRAB_CURSOR', 'BLOCKING'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'IMAGE_EDITOR'

    def invoke(self, context, event):
        self._last = (event.mouse_x, event.mouse_y)
        # the button that started it ends it (modal() reads this)
        self._button = event.type if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE'} else 'RIGHTMOUSE'
        self._zoom0 = tuple(context.space_data.zoom)
        self.applied = 1.0
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def step(self, context, dx, dy):
        """Zoom by one drag step."""
        factor = dolly_2d_step(context, dx, dy)
        self.applied *= factor
        return factor

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            dx, dy = event.mouse_x - self._last[0], event.mouse_y - self._last[1]
            self._last = (event.mouse_x, event.mouse_y)
            self.step(context, dx, dy)
            context.area.tag_redraw()
        elif event.type == self._button and event.value == 'RELEASE':
            return {'FINISHED'}
        elif event.type == 'ESC' and event.value == 'PRESS':
            zoom = context.space_data.zoom[0] or 1.0     # zoom limits may have kept some steps out
            bpy.ops.image.view_zoom('EXEC_DEFAULT', factor=self._zoom0[0] / zoom if self._zoom0[0] else 1.0)
            context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


# --- Alt+LMB+MMB zoom in the 2D editors (#325) ------------------------------------------------------------
# Maya's 2D editors zoom like their Alt+RMB while Alt+LMB and Alt+MMB are held together, whichever button comes first,
# and pressing a let-go button again zooms again. Letting go of LMB carries on with the MMB pan in the Graph Editor,
# Dope Sheet and NLA editor (like Maya's Trax Editor); the Node Editor and the UV / Image Editor stop there. Letting go
# of MMB leaves LMB alone, which holds the view still (Maya's Alt+LMB does nothing in these editors) until MMB is
# pressed again or LMB is let go. Blender's view2d.pan / view2d.zoom / image.view_pan only end on the release of the
# button that started them, so one kit modal runs the whole drag: Alt+LMB / Alt+MMB start it where those pans did,
# and each mouse step goes through those operators' exec. The zoom of each editor is the one of its Alt+RMB:
# - AXES (Graph Editor, Dope Sheet, NLA): Blender's drag rule, 1 % of the shown range per px on each axis (the rows
#   of the Dope Sheet / NLA never zoom), Invert Zoom Direction and Zoom to Mouse Position read from the preferences.
# - WIDTH (Node Editor): the same rule read from the left / right drag only, on both axes; an up / down drag does
#   nothing, like Maya's Node Editor. The kit's Alt+RMB there runs this modal too (Blender's zoom would read the
#   Zoom Axis preference instead).
# - DOLLY (UV / Image Editor): the kit's 2D dolly (right / down = in, left / up = out).
NAV2D_ZOOM_PER_PX = 0.01
V2D_CLIPPED = 12000            # what View2D.view_to_region(clip=True) gives outside the shown range
# editor: (zoom, MMB alone pans on once both buttons were held)
NAV2D_RULES = {'GRAPH_EDITOR': ('AXES', True), 'DOPESHEET_EDITOR': ('AXES', True), 'NLA_EDITOR': ('AXES', True),
               'NODE_EDITOR': ('WIDTH', False), 'IMAGE_EDITOR': ('DOLLY', False)}


def nav2d_rule(area, region, space):
    """The (zoom, pan on) rule of the editor when the chord applies there: the main region of the Graph Editor (also
    Drivers), Dope Sheet, NLA, Node Editor and UV / Image Editor. None for the Time Slider (a Timeline: Maya's never
    zooms or pans) and the kit's own rows drawn in an Image Editor (Shelf, Status Line)."""
    if area is None or region is None or region.type != 'WINDOW':
        return None
    rule = NAV2D_RULES.get(area.type)
    if rule is None:
        return None
    if area.type == 'DOPESHEET_EDITOR' and getattr(space, "ui_mode", "") == 'TIMELINE':
        return None
    if area.type == 'IMAGE_EDITOR':
        from ..ui import shelf
        if shelf.is_kit_row(space):
            return None
    return rule


def nav2d_editor(area, region, space):
    """True where the chord applies (``nav2d_rule``)."""
    return nav2d_rule(area, region, space) is not None


def nav2d_mode(held, lmb_pans=True, mmb_pans=True):
    """The Alt drag of the held buttons: both = zoom; MMB alone = pan while ``mmb_pans`` (a drag started with Alt+MMB,
    or once both were held where the editor pans on); LMB alone = pan while ``lmb_pans`` (a drag started with Alt+LMB
    alone, which pans as before); otherwise the view holds still; None once both are let go."""
    held = frozenset(held)
    if held == frozenset(CHORD_BUTTONS):
        return 'ZOOM'
    if held == {'MIDDLEMOUSE'}:
        return 'PAN' if mmb_pans else 'HOLD'
    if held == {'LEFTMOUSE'}:
        return 'PAN' if lmb_pans else 'HOLD'
    return None


def nav2d_zoom_delta(dpx, dpy, size_x, size_y, invert=False, uniform=False):
    """view2d.zoom deltax / deltay (view units taken off each side) for a drag step of (dpx, dpy) px over a shown
    range of size_x by size_y: Blender's drag zoom, right / up = in (reversed with ``invert``); ``uniform``: both axes
    from the left / right drag (Node Editor)."""
    if uniform:
        dpy = dpx
    dx = NAV2D_ZOOM_PER_PX * dpx * size_x
    dy = NAV2D_ZOOM_PER_PX * dpy * size_y
    return (-dx, -dy) if invert else (dx, dy)


def view2d_range(region):
    """(xmin, ymin, xmax, ymax) of the view range a View2D region shows, in view units. Blender fits that range
    into the region less its scroll bars, so the edges are found with the region's clip test."""
    v2d = region.view2d
    cx, cy = v2d.region_to_view(region.width * 0.5, region.height * 0.5)
    lo = v2d.region_to_view(-region.width, -region.height)
    hi = v2d.region_to_view(2.0 * region.width, 2.0 * region.height)

    def edge(inside, outside, axis):
        for _ in range(40):
            mid = (inside + outside) * 0.5
            p = (mid, cy) if axis == 0 else (cx, mid)
            if v2d.view_to_region(p[0], p[1], clip=True)[axis] == V2D_CLIPPED:
                outside = mid
            else:
                inside = mid
        return inside
    return edge(cx, lo[0], 0), edge(cy, lo[1], 1), edge(cx, hi[0], 0), edge(cy, hi[1], 1)


class ALLSET_OT_nav_2d(bpy.types.Operator):
    """Pan a 2D editor with Alt+MMB, zoom it with Alt+LMB+MMB (Maya)"""
    bl_idname = "allset.nav_2d"
    bl_label = "Pan / Zoom 2D View"
    bl_options = {'GRAB_CURSOR', 'BLOCKING', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return nav2d_editor(context.area, context.region, context.space_data)

    def invoke(self, context, event):
        rule = nav2d_rule(context.area, context.region, context.space_data)
        if rule is None or event.type not in {*CHORD_BUTTONS, 'RIGHTMOUSE'}:
            return {'PASS_THROUGH'}
        if event.type == 'RIGHTMOUSE' and rule[0] != 'WIDTH':
            return {'PASS_THROUGH'}             # Blender's own Alt+RMB zoom there
        self._rule, self._pan_on = rule
        self._held = frozenset({event.type})
        self._lmb_pans = self._mmb_pans = True
        rmb = event.type == 'RIGHTMOUSE'
        self._mode = 'ZOOM' if rmb else nav2d_mode(self._held)
        self._last = (event.mouse_x, event.mouse_y)
        self._anchor = (event.mouse_region_x, event.mouse_region_y) if rmb else None
        self._carry = [0.0, 0.0]
        context.window.cursor_modal_set('SCROLL_XY')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _end(self, context):
        context.window.cursor_modal_restore()
        return {'FINISHED'}

    def _pan(self, context, dpx, dpy):
        """Move the view by one mouse step (the content follows the mouse)."""
        if self._rule != 'DOLLY':
            bpy.ops.view2d.pan('EXEC_DEFAULT', deltax=-dpx, deltay=-dpy)
            return
        zoom = context.space_data.zoom[0]       # image.view_pan's offset is in image pixels at that zoom
        if zoom > 0.0:
            bpy.ops.image.view_pan('EXEC_DEFAULT', offset=(-dpx / zoom, -dpy / zoom))

    def _zoom(self, context, dpx, dpy):
        if self._rule == 'DOLLY':
            dolly_2d_step(context, dpx, dpy)
            return
        region = context.region
        v2d = region.view2d
        x0, y0, x1, y1 = view2d_range(region)
        zx, zy = nav2d_zoom_delta(dpx, dpy, x1 - x0, y1 - y0, invert_zoom(context), uniform=self._rule == 'WIDTH')
        if not (zx or zy):
            return
        anchor = self._anchor if context.preferences.inputs.use_zoom_to_mouse else None
        before = v2d.region_to_view(*anchor) if anchor else None
        bpy.ops.view2d.zoom('EXEC_DEFAULT', deltax=zx, deltay=zy)
        if before is None:
            return
        # Zoom to Mouse Position: pan the point under the mouse at the zoom's start back under it (view2d.pan
        # moves by whole px of the region's width / height; the rest carries over to the next step)
        after = v2d.region_to_view(*anchor)
        x0, y0, x1, y1 = view2d_range(region)
        for i, (a, b, size, px) in enumerate(((before[0], after[0], x1 - x0, region.width),
                                              (before[1], after[1], y1 - y0, region.height))):
            if size > 0.0 and px > 0:
                self._carry[i] += (a - b) * px / size
        step = [int(c) for c in self._carry]
        self._carry = [c - s for c, s in zip(self._carry, step)]
        if step[0] or step[1]:
            bpy.ops.view2d.pan('EXEC_DEFAULT', deltax=step[0], deltay=step[1])

    def modal(self, context, event):
        if self._held == {'RIGHTMOUSE'}:            # Alt+RMB zoom: until RMB is let go
            if event.type == 'RIGHTMOUSE' and event.value == 'RELEASE':
                return self._end(context)
        else:
            held = chord_held(self._held, event.type, event.value)
            if held is not None:
                self._held = held
                mode = nav2d_mode(held, self._lmb_pans, self._mmb_pans)
                if mode is None:
                    return self._end(context)
                if mode == 'ZOOM':
                    # from now on LMB alone holds the view still, like Maya; MMB alone pans on where Maya's does
                    self._lmb_pans, self._mmb_pans = False, self._pan_on
                    if self._mode != 'ZOOM':
                        self._anchor = (event.mouse_region_x, event.mouse_region_y)
                        self._carry = [0.0, 0.0]
                self._mode = mode
                self._last = (event.mouse_x, event.mouse_y)
                return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            dpx, dpy = event.mouse_x - self._last[0], event.mouse_y - self._last[1]
            self._last = (event.mouse_x, event.mouse_y)
            if dpx or dpy:
                if self._mode == 'PAN':
                    self._pan(context, dpx, dpy)
                elif self._mode == 'ZOOM':
                    self._zoom(context, dpx, dpy)
            return {'RUNNING_MODAL'}
        if event.type == 'ESC' and event.value == 'PRESS':
            return self._end(context)
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


# --- framing ------------------------------------------------------------------


def view3d_window_regions(window):
    """(area, region) for every 3D view WINDOW region (quad views: all four)."""
    for area in window.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type == 'WINDOW':
                yield area, region


# Object types whose evaluated bounding box is framed; others count as a point.
_BOX_TYPES = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES', 'POINTCLOUD', 'VOLUME',
              'GREASEPENCIL', 'LATTICE', 'ARMATURE'}


def _object_points(ob, depsgraph):
    mw = ob.matrix_world
    if ob.type in _BOX_TYPES:
        ev = ob.evaluated_get(depsgraph)
        return [mw @ Vector(c) for c in ev.bound_box]
    return [mw.translation.copy()]


def _visible(ob, view_layer, v3d):
    try:
        return ob.visible_get(view_layer=view_layer) and ob.visible_in_viewport_get(v3d)
    except RuntimeError:   # not in this view layer
        return False


def frame_points(context, v3d, selected, children, exclude=None):
    """World points to frame (Maya F / Ctrl+Shift+F / A), or None if this mode is left to
    Blender's own operator (curve/armature edit, pose, paint and sculpt modes). ``exclude``: an object left out
    (the camera a view looks through)."""
    vl, dg = context.view_layer, context.evaluated_depsgraph_get()
    mode = context.mode
    if not selected:   # A / Shift+A: every visible object, in any mode (Maya Frame All)
        return [p for ob in vl.objects if ob != exclude and _visible(ob, vl, v3d) for p in _object_points(ob, dg)]
    if mode == 'EDIT_MESH':
        pts = []
        objs = list(context.objects_in_mode_unique_data)
        for ob in objs:
            ob.update_from_editmode()
            mw = ob.matrix_world
            pts.extend(mw @ v.co for v in ob.data.vertices if v.select)
        if pts:
            return pts
        # No components selected: frame the objects (Maya frames the whole shape).
        return [p for ob in objs for p in _object_points(ob, dg)] or None
    if mode != 'OBJECT':
        return None
    objs = [ob for ob in vl.objects if ob != exclude and _visible(ob, vl, v3d)]
    sel = [ob for ob in objs if ob.select_get()]
    if children:
        seen = {ob.name for ob in sel}
        for ob in list(sel):
            for ch in ob.children_recursive:
                if ch.name not in seen and _visible(ch, vl, v3d):
                    seen.add(ch.name)
                    sel.append(ch)
    objs = sel or objs    # nothing selected: Maya F frames everything
    return [p for ob in objs for p in _object_points(ob, dg)]


def _others(area, region):
    return [(r.x, r.y, r.width, r.height) for r in area.regions
            if r.type in {'UI', 'TOOLS', 'HEADER', 'TOOL_HEADER', 'ASSET_SHELF',
                          'ASSET_SHELF_HEADER'} and r != region]


def visible_bounds(area, region):
    """Region-local (x0, y0, x1, y1) not covered by the sidebar/toolbar (Region Overlap)."""
    return framing.visible_rect((region.x, region.y, region.width, region.height),
                                _others(area, region))


def frame_region(context, area, region, selected=True, children=False):
    """Frame in one 3D view region the Maya way (fit 0.95 of the part not under the
    sidebar/toolbar). Falls back to Blender's view_selected / view_all."""
    rv3d, v3d = region.data, area.spaces.active
    points = None
    if rv3d is not None and rv3d.view_perspective == 'CAMERA':
        # Maya: F / A in a camera view move that camera (#9); Blender's view_selected would leave the camera view
        cam = view_camera(context, v3d)
        if cam is None:
            return False
        points = frame_points(context, v3d, selected, children, exclude=cam)
        if not points:
            return False
        if not frame_camera(context, cam, points):
            return False
        try:
            bpy.ops.ed.undo_push(message="Frame Camera")
        except RuntimeError:
            pass
        return True
    if rv3d is not None:
        points = frame_points(context, v3d, selected, children)
    if not points:
        with context.temp_override(area=area, region=region):
            if selected:
                return bpy.ops.view3d.view_selected() == {'FINISHED'}
            return bpy.ops.view3d.view_all(center=False) == {'FINISHED'}
    rect = visible_bounds(area, region)
    loc, dist = framing.fit(points, rv3d.view_rotation, rv3d.window_matrix.copy(),
                            rv3d.view_distance, rv3d.view_perspective == 'ORTHO',
                            (region.width, region.height), rect,
                            min_half=framing.MIN_HALF * units.maya_unit(context.scene))
    rv3d.view_location = loc
    rv3d.view_distance = dist
    region.tag_redraw()
    return True


def view_camera(context, v3d):
    """The object a camera view looks through (the view's local camera or the scene camera)."""
    if v3d.use_local_camera and v3d.camera is not None:
        return v3d.camera
    return context.scene.camera


def camera_projection(context, cam):
    """(window matrix, (width, height)) of the camera's frame at the render resolution."""
    r = context.scene.render
    w, h = max(r.resolution_x, 1), max(r.resolution_y, 1)
    win = cam.calc_matrix_camera(context.evaluated_depsgraph_get(), x=w, y=h,
                                 scale_x=r.pixel_aspect_x, scale_y=r.pixel_aspect_y)
    return win, (w, h)


def frame_camera(context, cam, points):
    """Move ``cam`` so ``points`` fill 0.95 of its frame, keeping its orientation (Maya framing in a camera
    view dollies / tracks the camera; an orthographic camera changes its width). A locked camera (Maya Lock Camera,
    ui/panel_menus.camera_locked) stays. Returns True when the camera moved."""
    if all(cam.lock_location):
        return False
    mw = cam.matrix_world
    loc0, rot, scale = mw.decompose()
    rot = rot.normalized()
    ortho = cam.type == 'CAMERA' and cam.data.type == 'ORTHO'
    win, size = camera_projection(context, cam) if cam.type == 'CAMERA' else (None, None)
    if win is None:
        return False
    centre = sum((Vector(p) for p in points), Vector()) / len(points)
    forward = rot @ Vector((0.0, 0.0, -1.0))
    dist0 = max((centre - loc0).dot(forward), 1e-3)
    loc, dist = framing.fit(points, rot, win, dist0, ortho, size, (0.0, 0.0, size[0], size[1]),
                            min_half=framing.MIN_HALF * units.maya_unit(context.scene))
    if ortho:
        cam.data.ortho_scale *= dist / dist0
        dist = dist0
    from mathutils import Matrix
    new = loc + rot @ Vector((0.0, 0.0, dist))
    cam.matrix_world = Matrix.LocRotScale(new, rot, scale)
    return True


class ALLSET_OT_frame(bpy.types.Operator):
    """Frame the selection (or everything) in this view with Maya's fit (F, A, Ctrl+Shift+F)"""
    bl_idname = "allset.frame"
    bl_label = "Frame"

    # SKIP_SAVE: keymap items set only some of these; a remembered children=True from
    # Ctrl+Shift+F must not leak into the next Shift+F.
    selected: bpy.props.BoolProperty(name="Selected", default=True, options={'SKIP_SAVE'})
    children: bpy.props.BoolProperty(name="With Children", default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D' and             context.region is not None and context.region.type == 'WINDOW'

    def execute(self, context):
        ok = frame_region(context, context.area, context.region, self.selected, self.children)
        return {'FINISHED'} if ok else {'CANCELLED'}


class ALLSET_OT_frame_all_views(bpy.types.Operator):
    """Frame the selection (or everything) in every 3D view (Maya Shift+F / Shift+A /
    Ctrl+Shift+F)"""
    bl_idname = "allset.frame_all_views"
    bl_label = "Frame in All Views"

    # SKIP_SAVE: keymap items set only some of these; a remembered children=True from
    # Ctrl+Shift+F must not leak into the next Shift+F.
    selected: bpy.props.BoolProperty(name="Selected", default=True, options={'SKIP_SAVE'})
    children: bpy.props.BoolProperty(name="With Children", default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.window is not None

    def execute(self, context):
        count = 0
        for area, region in view3d_window_regions(context.window):
            count += frame_region(context, area, region, self.selected, self.children)
        return {'FINISHED'} if count else {'CANCELLED'}


# --- view history ---------------------------------------------------------------

_DIGITS = 5


def capture(rv3d):
    """Comparable snapshot of a RegionView3D's view."""
    r = lambda v: round(v, _DIGITS)  # noqa: E731
    return (tuple(map(r, rv3d.view_location)), tuple(map(r, rv3d.view_rotation)),
            r(rv3d.view_distance), rv3d.view_perspective,
            r(rv3d.view_camera_zoom), tuple(map(r, rv3d.view_camera_offset)))


def restore(rv3d, state):
    loc, rot, dist, persp, cam_zoom, cam_offset = state
    rv3d.view_perspective = persp
    rv3d.view_location = loc
    rv3d.view_rotation = rot
    rv3d.view_distance = dist
    rv3d.view_camera_zoom = cam_zoom
    rv3d.view_camera_offset = cam_offset


class ViewHistory:
    """Undo/redo stack of settled view states for one RegionView3D.

    ``observe`` is called periodically with the current state. A change is
    recorded once the view has stayed the same for one more observation
    (navigation or smooth-view animation finished).
    """

    def __init__(self, limit=50):
        self.limit = limit
        self.undo = []
        self.redo = []
        self.stable = None
        self.pending = None

    def _push(self, state):
        self.undo.append(state)
        del self.undo[:-self.limit]
        self.redo.clear()

    def observe(self, state):
        if self.stable is None or state == self.stable:
            self.stable = state
            self.pending = None
            return
        if state != self.pending:
            self.pending = state  # still moving
            return
        self._push(self.stable)
        self.stable = state
        self.pending = None

    def step_back(self, current):
        """State to show for "undo view change", or None."""
        if self.stable is None:  # never observed: nothing to go back to
            self.stable = current
            return None
        if current != self.stable:  # a change not settled/observed yet
            self._push(self.stable)
            self.stable = current
        if not self.undo:
            return None
        self.redo.append(current)
        self.stable = self.undo.pop()
        self.pending = None
        return self.stable

    def step_forward(self, current):
        """State to show for "redo view change", or None."""
        if self.stable is None:
            self.stable = current
            return None
        if current != self.stable:
            self.redo.clear()  # the view moved since the undo: redo is void
            self.observe(current)
            return None
        if not self.redo:
            return None
        self.undo.append(current)
        self.stable = self.redo.pop()
        self.pending = None
        return self.stable


_histories = {}
POLL_INTERVAL = 0.25


def history_for(rv3d):
    key = rv3d.as_pointer()
    h = _histories.get(key)
    if h is None:
        h = _histories[key] = ViewHistory()
    return h


def _all_rv3d():
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            space = area.spaces.active
            yield space.region_3d
            yield from space.region_quadviews


def poll_views():
    """Timer: observe every 3D view; forget views that no longer exist."""
    seen = set()
    for rv3d in _all_rv3d():
        if rv3d is None:
            continue
        seen.add(rv3d.as_pointer())
        history_for(rv3d).observe(capture(rv3d))
    for key in list(_histories):
        if key not in seen:
            del _histories[key]
    return POLL_INTERVAL


class ALLSET_OT_view_history(bpy.types.Operator):
    """Undo or redo a view change (Maya [ and ]); separate from scene undo"""
    bl_idname = "allset.view_history"
    bl_label = "Undo/Redo View Change"

    direction: bpy.props.EnumProperty(items=(("UNDO", "Undo", ""), ("REDO", "Redo", "")))

    @classmethod
    def poll(cls, context):
        return context.region_data is not None

    def execute(self, context):
        rv3d = context.region_data
        h = history_for(rv3d)
        cur = capture(rv3d)
        state = h.step_back(cur) if self.direction == "UNDO" else h.step_forward(cur)
        if state is None:
            results.result(self, "No more view changes")
            return {'CANCELLED'}
        restore(rv3d, state)
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


# --- Space tap: four views <-> single view -------------------------------------


# --- Maya-style ortho cameras ----------------------------------------------------------------------------
# The top / front / side cameras show 30 units across (Maya units). Blender's viewport ortho width along the longer side =
# view_distance x 72 / lens (distance 3 cm with lens 70 = 3.086 units across).
# The four view's panels are real 3D View areas that keep their own camera (ui/four_view.py).
MAYA_ORTHO_WIDTH = 30.0
FOUR_VIEW_NOTE = "each panel has its own camera, shading and Show settings, like Maya's"


def ortho_key(rv3d):
    """'TOP' / 'FRONT' / 'SIDE' (+ '-' for the opposite views) of an axis-aligned ortho pane, else None."""
    if rv3d is None or rv3d.view_perspective != 'ORTHO':
        return None
    d = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))     # view direction
    i = max(range(3), key=lambda k: abs(d[k]))
    if abs(d[i]) < 0.999:
        return None
    return ("SIDE", "FRONT", "TOP")[i] + ("-" if d[i] > 0 else "")


def maya_ortho_distance(space, scene=None):
    """view_distance that shows 30 units across an ortho pane of this 3D View."""
    from .units import maya_unit
    return MAYA_ORTHO_WIDTH * maya_unit(scene or bpy.context.scene) * space.lens / 72.0


class ALLSET_OT_toggle_quad_view(bpy.types.Operator):
    """Toggle the four view; leaving it keeps the panel under the cursor (Maya Space tap). Four real panels, each
    with its own camera, shading and Show settings"""
    bl_idname = "allset.toggle_quad_view"
    bl_label = "Toggle Four Views"

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        from ..ui import four_view
        four = four_view.is_four(context.window.screen)
        got = four_view.tap(context, context.area, context.window)
        if got in ("four", "single"):
            return {'FINISHED'}
        if got == "failed" and four and bpy.app.background:
            self.report({'WARNING'}, "Leaving the four view needs the Blender window")
        elif got == "failed" and not bpy.app.background:
            self.report({'WARNING'}, "This panel can't be split into the four view here")
        return {'CANCELLED'}


def _persp_store():
    # the hotbox's store (marking/modal.py ALLSET_OT_hb_view): one memory of the persp view per area
    from ..marking import modal
    return modal._persp_views


def remember_persp(area, space):
    """Keep the perspective view of a four view before leaving it (the panel under the cursor may be ortho)."""
    for rv3d in (space.region_3d, *space.region_quadviews):
        if rv3d is not None and rv3d.view_perspective == 'PERSP':
            _persp_store()[area.as_pointer()] = (rv3d.view_rotation.copy(), rv3d.view_location.copy(),
                                                 rv3d.view_distance)
            return


def ensure_persp(area, space):
    """Maya Single Perspective / Four View (#8): the single view (or the four view's top right panel) shows the
    persp camera, never an ortho view: an ortho view gets the last persp view of this area back, else the
    default persp, like Maya (Home)."""
    rv3d = space.region_3d
    if rv3d is None or rv3d.view_perspective != 'ORTHO':
        return
    rv3d.is_orthographic_side_view = False
    rv3d.view_perspective = 'PERSP'
    saved = _persp_store().get(area.as_pointer())
    if saved:
        rv3d.view_rotation, rv3d.view_location, rv3d.view_distance = saved
    else:
        home_view(rv3d, units.maya_unit(bpy.context.scene))
    area.tag_redraw()


def home_view(rv3d, k):
    """Maya Home (viewSet -home): the default camera place, no animation.
    Perspective = Maya's new-scene persp (units.PERSP_EYE, Maya units); orthographic keeps
    its direction and goes back to the origin at the same distance."""
    eye = Vector(units.PERSP_EYE) * k
    rv3d.view_location = (0.0, 0.0, 0.0)
    rv3d.view_distance = eye.length
    if rv3d.view_perspective == 'PERSP':
        rv3d.view_rotation = eye.normalized().to_track_quat('Z', 'Y')


class ALLSET_OT_view_home(bpy.types.Operator):
    """Go to the default view (Maya Home)"""
    bl_idname = "allset.view_home"
    bl_label = "Default View"

    @classmethod
    def poll(cls, context):
        rv3d = context.region_data
        return rv3d is not None and context.area is not None and context.area.type == 'VIEW_3D'             and rv3d.view_perspective != 'CAMERA'

    def execute(self, context):
        home_view(context.region_data, units.maya_unit(context.scene))
        context.region.tag_redraw()
        return {'FINISHED'}


classes = (ALLSET_OT_tumble, ALLSET_OT_track_view, ALLSET_OT_nav_chord, ALLSET_OT_emulated_tumble, ALLSET_OT_dolly, ALLSET_OT_dolly_2d, ALLSET_OT_nav_2d, ALLSET_OT_view_axis_lock, ALLSET_OT_frame, ALLSET_OT_frame_all_views, ALLSET_OT_view_history,
           ALLSET_OT_toggle_quad_view, ALLSET_OT_view_home)


def register_timer():
    if not bpy.app.timers.is_registered(poll_views):
        bpy.app.timers.register(poll_views, first_interval=POLL_INTERVAL, persistent=True)


def unregister_timer():
    if bpy.app.timers.is_registered(poll_views):
        bpy.app.timers.unregister(poll_views)
    _histories.clear()
