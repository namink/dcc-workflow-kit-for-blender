# SPDX-License-Identifier: GPL-3.0-or-later
"""Mouse operators on the Time Slider: click / drag the time (Shift = red range, middle mouse = keep the pose),
double-click = the whole range, drag the middle / an end of a highlighted range to move / scale its keys. Helpers
``frame_at``, ``set_range``, ``range_rect``, ``range_zone``; the keys behind a range: ``operators/time_range``.
"""

import time

import bpy

from .. import results
from ..operators import taphold
from .time_slider_view import _is_timeline, playback_range


# --- Time Slider hand feel ---------------------------------------------------------------
# Maya: LMB anywhere on the Time Slider moves the time, Shift+LMB drag highlights a range, RMB = the
# Time Slider menu (Maya labels).
# Blender's timeline is a Dope Sheet mode, so these sit first in the "Dopesheet" keymap and pass
# through in the Dope Sheet itself (keys are clicked there in Maya too).

def frame_at(region, x):
    """Whole frame under window x in a timeline WINDOW region."""
    return int(round(region.view2d.region_to_view(x - region.x, 0)[0]))


def set_range(wm, a, b, on=True):
    wm.allset_time_range = (int(a), int(b))
    wm.allset_time_range_on = on


_LAST_PRESS = None   # (time, window x, region pointer) of the last plain Time Slider press


def _second_press(context, event, region, record=True):
    """True for a second plain press within the double-click time near the first: a double-click. Blender's own
    DOUBLE_CLICK event goes to allset.time_range_all before this; simulated events never become one. ``record``
    False only asks (the press is not remembered)."""
    global _LAST_PRESS
    now = time.monotonic()
    last = _LAST_PRESS
    if record:
        _LAST_PRESS = (now, event.mouse_x, region.as_pointer())
    if last is None or last[2] != region.as_pointer():
        return False
    limit = getattr(context.preferences.inputs, "mouse_double_click_time", 350) / 1000.0
    if now - last[0] <= limit and abs(event.mouse_x - last[1]) <= 4 * (context.preferences.system.ui_scale or 1.0):
        if record:
            _LAST_PRESS = None
        return True
    return False


class ALLSET_OT_time_scrub(bpy.types.Operator):
    """Maya Time Slider: click or drag to move the time (Shift: highlight a range, middle mouse: keep the pose)"""
    bl_idname = "allset.time_scrub"
    bl_label = "Time Slider Scrub"
    bl_options = {'INTERNAL'}

    range: bpy.props.BoolProperty(name="Range", description="Shift-drag: highlight a time range",
                                  options={'SKIP_SAVE'})
    hold: bpy.props.BoolProperty(name="Hold", description="Move the time without updating the scene, so the "
                                 "current pose can be keyed at another frame", options={'SKIP_SAVE'})

    def invoke(self, context, event):
        region = context.region
        if not _is_timeline(context) or region is None or region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        self._region = region
        self._button = event.type
        self._held = None
        if self.hold:
            # Maya MMB: every animated channel keeps the value it has now while the time moves
            from ..operators import time_hold
            self._held = time_hold.snapshot()
        wm, scene = context.window_manager, context.scene
        self._old = (scene.frame_current, tuple(wm.allset_time_range), wm.allset_time_range_on)
        f = frame_at(region, event.mouse_x)
        if self.range:
            self._anchor = f
            set_range(wm, f, f)
        elif not self.hold and _second_press(context, event, region):
            # a double-click: the whole visible range; the time stays where the first click put it
            set_range(wm, *playback_range(scene))
            _tag(context)
            return {'FINISHED'}
        else:
            wm.allset_time_range_on = False   # a plain click drops the highlighted range (Maya)
            self._set_frame(scene, f)
        _tag(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _set_frame(self, scene, f):
        if self._held is None:
            scene.frame_current = f
        else:
            from ..operators import time_hold
            time_hold.move_time(scene, f, self._held)

    def modal(self, context, event):
        wm, scene = context.window_manager, context.scene
        if event.type == 'MOUSEMOVE':
            f = frame_at(self._region, event.mouse_x)
            if self.range:
                set_range(wm, self._anchor, f)
            elif (f if self._held is not None else taphold.kept_frame(f)) != scene.frame_current:
                # MMB evaluates the frame as asked; the plain write keeps 0 below frame 0 (see kept_frame)
                self._set_frame(scene, f)
            _tag(context)
            return {'RUNNING_MODAL'}
        if event.type == self._button and event.value == 'RELEASE':
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._set_frame(scene, self._old[0])
            set_range(wm, *self._old[1], on=self._old[2])
            _tag(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class ALLSET_OT_time_range_all(bpy.types.Operator):
    """Maya Time Slider: a double-click highlights the whole visible range"""
    bl_idname = "allset.time_range_all"
    bl_label = "Time Slider Range All"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        global _LAST_PRESS
        region = context.region
        if not _is_timeline(context) or region is None or region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        _LAST_PRESS = None
        set_range(context.window_manager, *playback_range(context.scene))
        _tag(context)
        return {'FINISHED'}


RANGE_EDGE_PX = 8          # end-arrow zone of a highlighted range (x UI scale)


def range_zone(context, region, x):
    """'LEFT' / 'RIGHT' / 'MOVE' when window x is on the highlighted range of this timeline, else None."""
    from ..operators import time_range
    wm = context.window_manager
    if not getattr(wm, "allset_time_range_on", False):
        return None
    x0, x1 = range_rect(region, *wm.allset_time_range)
    edge = RANGE_EDGE_PX * (context.preferences.system.ui_scale or 1.0)
    return time_range.zone(x - region.x, x0, x1, edge)


class ALLSET_OT_time_range_drag(bpy.types.Operator):
    """Maya Time Slider range: drag the middle to move its keys, an end arrow to scale them"""
    bl_idname = "allset.time_range_drag"
    bl_label = "Move / Scale Range Keys"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def invoke(self, context, event):
        from ..operators import time_keys, time_range
        region = context.region
        if not _is_timeline(context) or region is None or region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        mode = range_zone(context, region, event.mouse_x)
        if mode is None:
            return {'PASS_THROUGH'}
        wm = context.window_manager
        a, b = sorted(wm.allset_time_range)
        curves, seen = [], set()
        for node in time_keys.nodes(context):
            for fc in time_keys.slider_fcurves(node):
                if fc.as_pointer() in seen:
                    continue
                seen.add(fc.as_pointer())
                idx = [i for i, kp in enumerate(fc.keyframe_points) if time_keys._in(kp, a, b)]
                if idx:
                    curves.append((fc, idx))
        self._drag = time_range.Drag(curves, a, b)
        self._region, self._mode, self._range = region, ('MOVE' if a == b else mode), (a, b)
        self._f0 = frame_at(region, event.mouse_x)
        self._f, self._moved = self._f0, False
        self._x0 = event.mouse_x
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _update(self, context, f):
        from ..operators import time_range
        wm = context.window_manager
        self._f = f
        self._drag.apply(self._mode, self._f0, f)
        set_range(wm, *time_range.new_range(*self._range, self._mode, self._f0, f))
        _tag(context)
        for area in context.screen.areas:
            if area.type in {'GRAPH_EDITOR', 'VIEW_3D'}:
                area.tag_redraw()

    def modal(self, context, event):
        wm, scene = context.window_manager, context.scene
        if event.type == 'MOUSEMOVE':
            f = frame_at(self._region, event.mouse_x)
            if abs(event.mouse_x - self._x0) >= 3:
                self._moved = True
            if self._moved and f != self._f:
                self._update(context, f)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if not self._moved:
                # a click on the range = a plain Time Slider click: drop the range, go to that frame (no undo step)
                wm.allset_time_range_on = False
                scene.frame_current = self._f0
                _tag(context)
                return {'CANCELLED'}
            n = self._drag.finish(self._mode, self._f0, self._f)
            scene.frame_set(scene.frame_current)          # re-evaluate at the current time
            results.result(self, f"{'Moved' if self._mode == 'MOVE' else 'Scaled'} {n} key(s)")
            _tag(context)
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._drag.cancel()
            set_range(wm, *self._range)
            _tag(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


def _tag(context):
    for area in context.screen.areas if context.screen else ():
        if area.type == 'DOPESHEET_EDITOR':
            area.tag_redraw()


def range_rect(region, a, b):
    """Window-region x0, x1 of frames a..b (whole frames: half a frame either side)."""
    lo, hi = min(a, b) - 0.5, max(a, b) + 0.5
    x0 = region.view2d.view_to_region(lo, 0, clip=False)[0]
    x1 = region.view2d.view_to_region(hi, 0, clip=False)[0]
    return x0, x1
