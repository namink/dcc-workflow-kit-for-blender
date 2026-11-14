# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya 2D Pan/Zoom: the \\ key and View > Camera Tools > 2D Pan/Zoom Tool.

Maya pans / zooms a view's picture in 2D: the picture moves (the film), the camera and the render don't. 2D Pan/Zoom can
be turned off (the whole picture again) and on (the same 2D pan / zoom back); it is kept per view.

- \\ tapped (pressed and let go within 0.25 s, whatever happened in between) turns it on / off; a longer hold never
  does. While \\ is held a middle drag pans (the picture follows the mouse), a right drag zooms (right / down in,
  left / up out, so a diagonal cancels; one view width of drag zooms by e), a left drag does nothing; a drag turns
  2D Pan/Zoom on and it stays on. Alt+MMB / Alt+RMB keep moving the camera.
- 2D Pan/Zoom Tool: LMB / MMB drag pans (Mode 2D Pan) or zooms (Mode 2D Zoom; Zoom scale multiplies the rate),
  Ctrl+LMB drag a box zooms into it.

Blender: a view that looks through a camera has its own 2D pan / zoom (``RegionView3D.view_camera_offset`` /
``view_camera_zoom``: the camera and the render stay). Blender's own views (the persp / top / front / side panels) have
none, so the kit keeps their 2D pan / zoom here and shows it by moving the view: an orthographic view moves in its
plane and changes its size (the same picture as a film pan / zoom), the perspective view turns about its eye and
changes its lens (the picture point in the middle follows the mouse exactly; Blender's view lens ends at 250 mm).
Off puts the view back exactly, on shows the 2D pan / zoom again. Kept per view and per kind (camera / perspective /
orthographic) for the session: a new session starts with every view off.
"""

import math
import time

import bpy
import gpu
from bpy.props import EnumProperty, FloatProperty
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Quaternion, Vector

from . import keystate

TAP_SECONDS = 0.25          # a \\ press let go within this is a tap
VIEW_SENSOR = 72.0          # Blender's own views: the lens on a 72 mm film (key_batch.VIEW_SENSOR)
LENS_MIN, LENS_MAX = 1.0, 250.0         # Blender's view lens range
POLL = 0.05
MIN_BOX = 6                 # px: a smaller box is a click, not a box zoom
_clock = time.monotonic


# --- rules ----------------------------------------------------------------------------------------------------------

def is_tap(seconds):
    """A \\ press let go after ``seconds`` toggles 2D Pan/Zoom (Maya: whatever happened while it was down)."""
    return seconds <= TAP_SECONDS + 1e-9


def zoom_factor(dx, dy, width, scale=1.0):
    """The 2D zoom of a drag of (dx, dy) px (dy up): below 1 zooms in (right / down), above 1 zooms out (left / up);
    one view width of drag zooms by e. ``scale`` = the tool's Zoom scale."""
    return math.exp(-scale * (dx - dy) / max(float(width), 1.0))


def key_button(event_type, alt=False):
    """What a mouse button does while \\ is held: 'PAN' (MMB), 'ZOOM' (RMB), 'NOTHING' (LMB: used up), None (not the
    key's business: Alt+drags keep moving the camera)."""
    if alt:
        return None
    return {'MIDDLEMOUSE': 'PAN', 'RIGHTMOUSE': 'ZOOM', 'LEFTMOUSE': 'NOTHING'}.get(event_type)


def _zoom_to_fac(zoom):
    from .camera_overscan import zoom_to_fac
    return zoom_to_fac(zoom)


def camera_pan(offset, zoom, dx, dy, width, height):
    """``view_camera_offset`` after a drag of (dx, dy) px in a camera view of ``width`` x ``height`` px: the picture
    follows the mouse (Blender's camera view offset is in frame widths along x and frame heights along y)."""
    f = 2.0 * _zoom_to_fac(zoom)
    return offset[0] - dx / (f * max(width, 1)), offset[1] - dy / (f * max(height, 1))


def camera_zoom(zoom, factor):
    """``view_camera_zoom`` showing ``factor`` times as much of the picture (below 1 = zoomed in); the middle stays."""
    from .camera_overscan import ZOOM_MAX, ZOOM_MIN, fac_to_zoom
    fac = _zoom_to_fac(zoom) / max(factor, 1e-12)
    return min(ZOOM_MAX, max(ZOOM_MIN, fac_to_zoom(fac)))


def box_factor(rect, size):
    """The zoom that makes box ``rect`` (xmin, ymin, xmax, ymax px) fill a view of ``size`` px."""
    return max(abs(rect[2] - rect[0]) / max(size[0], 1), abs(rect[3] - rect[1]) / max(size[1], 1), 1e-6)


def _turn(pan):
    """The turn that points a perspective view at film point ``pan`` (x right, y up, at focal length 1): pan, then
    tilt (no roll)."""
    u, v = pan
    return Matrix.Rotation(-math.atan(u), 3, 'Y') @ Matrix.Rotation(math.atan2(v, math.sqrt(1.0 + u * u)), 3, 'X')


def focal_px(lens, size):
    """Focal length in pixels of Blender's own perspective view (72 mm film fitted to the longer side)."""
    return lens * max(size) / VIEW_SENSOR


def ortho_px(distance, lens, size):
    """World units per pixel of Blender's own orthographic view."""
    return distance * VIEW_SENSOR / (lens * max(max(size), 1))


# --- per-view state -------------------------------------------------------------------------------------------------

# RegionView3D pointer -> {kind: {"on", "pan", "zoom", "memo", "base", "shown"}}. Camera views: the values live in the
# view; "memo" = the (zoom, offset) the view had when turned off. Blender's own views: "pan" (perspective: film point at
# focal length 1; orthographic: world units along the view's x / y) and "zoom" (the share of the picture shown), shown
# on "base" while "on".
_views = {}
_NONE = {"pan": (0.0, 0.0), "zoom": 1.0}


def kind(rv3d):
    p = rv3d.view_perspective
    return 'CAMERA' if p == 'CAMERA' else 'ORTHO' if p == 'ORTHO' else 'PERSP'


def _state(rv3d, make=False):
    per = _views.get(rv3d.as_pointer())
    k = kind(rv3d)
    st = per.get(k) if per else None
    if st is None and make:
        st = {"on": False, "pan": (0.0, 0.0), "zoom": 1.0, "memo": None}
        _views.setdefault(rv3d.as_pointer(), {})[k] = st
    return st


def is_on(rv3d):
    """The view's 2D Pan/Zoom is on (the panel toolbar's 2D Pan/Zoom button)."""
    st = _state(rv3d) if rv3d is not None else None
    return bool(st and st["on"])


def mark_on(rv3d):
    """A camera view's offset / zoom was set from outside (a 2D bookmark): 2D Pan/Zoom is on."""
    if rv3d is not None and kind(rv3d) == 'CAMERA':
        st = _state(rv3d, make=True)
        st["on"], st["memo"] = True, None


def forget(rv3d):
    """The camera frame was fitted to the view again (another camera, Overscan): no 2D pan / zoom to bring back."""
    if rv3d is not None:
        per = _views.get(rv3d.as_pointer())
        if per:
            per.pop('CAMERA', None)


def clear():
    _views.clear()


def snapshot(space, rv3d):
    """Everything a 2D drag changes, for a cancel."""
    per = _views.get(rv3d.as_pointer())
    return (rv3d.view_location.copy(), rv3d.view_rotation.copy(), rv3d.view_distance, space.lens,
            rv3d.view_camera_zoom, tuple(rv3d.view_camera_offset),
            {k: dict(v) for k, v in per.items()} if per is not None else None)


def restore(space, rv3d, snap):
    loc, rot, dist, lens, czoom, coffset, per = snap
    rv3d.view_location, rv3d.view_rotation, rv3d.view_distance, space.lens = loc, rot, dist, lens
    rv3d.view_camera_zoom, rv3d.view_camera_offset = czoom, coffset
    if per is None:
        _views.pop(rv3d.as_pointer(), None)
    else:
        _views[rv3d.as_pointer()] = per


# --- showing Blender's own views ------------------------------------------------------------------------------------
# Each such view keeps its "base" (the view without its 2D pan / zoom: location, rotation, distance, lens) and what the
# kit showed last; the view shown = base + 2D values, so turning off gives the base back exactly. When the view no
# longer shows what the kit showed (the user tumbled / tracked / dollied it), its base is taken again from the view.

def _read(space, rv3d):
    return (tuple(rv3d.view_location), tuple(rv3d.view_rotation), rv3d.view_distance, space.lens)


def _base_of(space, rv3d, st):
    """(location, rotation, distance, lens) of the view without the 2D pan / zoom it shows now."""
    loc, rot, dist, lens = rv3d.view_location.copy(), rv3d.view_rotation.copy(), rv3d.view_distance, space.lens
    if st["on"]:
        pan, zoom = st["pan"], st["zoom"]
        if kind(rv3d) == 'ORTHO':
            loc = loc - rot @ Vector((pan[0], pan[1], 0.0))
            dist = dist / zoom
        else:
            if pan != (0.0, 0.0):
                eye = loc + rot @ Vector((0.0, 0.0, dist))
                base = (rot.to_matrix() @ _turn(pan).transposed()).to_quaternion()
                if base.dot(rot) < 0.0:
                    base.negate()
                loc, rot = eye - base @ Vector((0.0, 0.0, dist)), base
            lens = lens * zoom
    return (tuple(loc), tuple(rot), dist, lens)


def _show(space, rv3d, st, new):
    """Blender's own view: show 2D values ``new`` (pan, zoom) on the view's base and keep them in ``st`` (the zoom
    really shown: a perspective view's lens stops at Blender's range)."""
    if st.get("base") is None or st.get("shown") != _read(space, rv3d):
        st["base"] = _base_of(space, rv3d, st)
    loc, rot, dist, lens = st["base"]
    loc, rot = Vector(loc), Quaternion(rot)
    pan, zoom = (float(new["pan"][0]), float(new["pan"][1])), float(new["zoom"])
    if kind(rv3d) == 'ORTHO':
        rv3d.view_location = loc + rot @ Vector((pan[0], pan[1], 0.0)) if pan != (0.0, 0.0) else loc
        rv3d.view_distance = dist * zoom if zoom != 1.0 else dist
    else:
        if pan == (0.0, 0.0):
            rv3d.view_rotation, rv3d.view_location = rot, loc
        else:
            q = (rot.to_matrix() @ _turn(pan)).to_quaternion()       # turned about the eye
            if q.dot(rot) < 0.0:
                q.negate()
            eye = loc + rot @ Vector((0.0, 0.0, dist))
            rv3d.view_rotation = q
            rv3d.view_location = eye - q @ Vector((0.0, 0.0, dist))
        space.lens = min(LENS_MAX, max(LENS_MIN, lens / zoom)) if zoom != 1.0 else lens
        zoom = lens / space.lens
    st["pan"], st["zoom"] = pan, zoom
    st["shown"] = _read(space, rv3d)


def _fit(where, rv3d):
    """The whole camera frame in the view (fitted by the camera's Overscan); without a window at least no pan."""
    done = False
    window, area = where if where else (None, None)
    if window is not None and area is not None and getattr(area, "type", None) == 'VIEW_3D':
        from . import camera_overscan
        try:
            done = camera_overscan.apply_view(window, area)
        except (RuntimeError, ReferenceError, AttributeError, TypeError):    # a view Blender can't fit now
            done = False
    if not done:
        rv3d.view_camera_offset = (0.0, 0.0)


def set_on(space, rv3d, on, where=None):
    """Turn the view's 2D Pan/Zoom on (its 2D pan / zoom back) or off (the whole picture); ``where`` = (window, area)
    to fit a camera frame in."""
    if rv3d is None:
        return False
    st = _state(rv3d, make=True)
    if st["on"] == on:
        return True
    if kind(rv3d) == 'CAMERA':
        if on:
            if st["memo"] is not None:
                rv3d.view_camera_zoom, rv3d.view_camera_offset = st["memo"]
            st["on"], st["memo"] = True, None
        else:
            memo = (rv3d.view_camera_zoom, tuple(rv3d.view_camera_offset))
            _fit(where, rv3d)                         # forgets the camera state: make it again
            st = _state(rv3d, make=True)
            st["on"], st["memo"] = False, memo
        return True
    if on:
        _show(space, rv3d, st, {"pan": st["pan"], "zoom": st["zoom"]})
        st["on"] = True
    else:
        kept = (st["pan"], st["zoom"])
        _show(space, rv3d, st, _NONE)
        st["pan"], st["zoom"] = kept
        st["on"] = False
    return True


def toggle(space, rv3d, where=None):
    """The \\ tap / the panel toolbar's 2D Pan/Zoom button."""
    return rv3d is not None and set_on(space, rv3d, not is_on(rv3d), where)


def _on(space, rv3d, where):
    """A 2D drag: 2D Pan/Zoom on (the kept 2D pan / zoom first, like Maya)."""
    set_on(space, rv3d, True, where)
    return _state(rv3d, make=True)


def pan(space, rv3d, dx, dy, size, where=None):
    """Pan the view's picture by (dx, dy) px (dy up): it follows the mouse."""
    if rv3d is None:
        return False
    st = _on(space, rv3d, where)
    k = kind(rv3d)
    if k == 'CAMERA':
        rv3d.view_camera_offset = camera_pan(tuple(rv3d.view_camera_offset), rv3d.view_camera_zoom, dx, dy, *size)
    elif k == 'ORTHO':
        step = ortho_px(rv3d.view_distance, space.lens, size)
        _show(space, rv3d, st, {"pan": (st["pan"][0] - dx * step, st["pan"][1] - dy * step), "zoom": st["zoom"]})
    else:
        f = focal_px(space.lens, size)
        d = _turn(st["pan"]) @ Vector((-dx / f, -dy / f, -1.0))     # what was at -(dx, dy) comes to the middle
        if d.z < -1e-6:
            _show(space, rv3d, st, {"pan": (d.x / -d.z, d.y / -d.z), "zoom": st["zoom"]})
    return True


def zoom(space, rv3d, factor, size, where=None):
    """Zoom the view's picture: show ``factor`` times as much (below 1 = in); the middle stays."""
    if rv3d is None:
        return False
    st = _on(space, rv3d, where)
    if kind(rv3d) == 'CAMERA':
        rv3d.view_camera_zoom = camera_zoom(rv3d.view_camera_zoom, factor)
    else:
        _show(space, rv3d, st, {"pan": st["pan"], "zoom": st["zoom"] * factor})
    return True


def box(space, rv3d, rect, size, where=None):
    """Zoom into box ``rect`` (xmin, ymin, xmax, ymax region px): its centre comes to the middle, it fills the view."""
    if rv3d is None:
        return False
    cx, cy = (rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0
    pan(space, rv3d, size[0] / 2.0 - cx, size[1] / 2.0 - cy, size, where)
    return zoom(space, rv3d, box_factor(rect, size), size, where)


# --- operators ------------------------------------------------------------------------------------------------------

def _view_at(window, x, y):
    """(area, region) of the 3D View region under window position (x, y), else None."""
    screen = getattr(window, "screen", None)
    for area in (screen.areas if screen is not None else ()):
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type == 'WINDOW' and region.data is not None and \
                    region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
                return area, region
    return None


def _drag(window, area, region, what, dx, dy, scale=1.0):
    """One step of a 2D drag in ``region``: 'PAN' or 'ZOOM'."""
    space, rv3d, size = area.spaces.active, region.data, (region.width, region.height)
    if what == 'PAN':
        pan(space, rv3d, dx, dy, size, (window, area))
    else:
        zoom(space, rv3d, zoom_factor(dx, dy, region.width, scale), size, (window, area))
    area.tag_redraw()


def _poll(context):
    return context.area is not None and context.area.type == 'VIEW_3D' and context.region_data is not None


class ALLSET_OT_pan_zoom_hold(bpy.types.Operator):
    """Tap: 2D Pan/Zoom on / off. Hold: middle drag pans, right drag zooms the picture in 2D (Maya \\)"""
    bl_idname = "allset.pan_zoom_hold"
    bl_label = "2D Pan/Zoom"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        if event.value != 'PRESS':
            return {'CANCELLED'}
        self._key, self._t0, self._window = event.type, _clock(), context.window
        self._view = (context.area, context.region)       # the view a tap toggles: the last one dragged in
        self._drag = None             # (what, button, area, region, (x, y), snapshot)
        self._eaten = set()           # buttons used up while the key is down (their release too)
        self._let_go = False
        self._timer = context.window_manager.event_timer_add(POLL, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _release(self):
        """The key is up: a tap toggles 2D Pan/Zoom of the view."""
        if self._let_go:
            return
        self._let_go = True
        if not is_tap(_clock() - self._t0):
            return
        area, region = self._view
        try:
            toggle(area.spaces.active, region.data, (self._window, area))
            area.tag_redraw()
        except (ReferenceError, AttributeError):
            pass

    def _finish(self, context):
        context.window_manager.event_timer_remove(self._timer)
        return {'FINISHED'}

    def modal(self, context, event):
        t = event.type
        if t == self._key:
            if event.value == 'RELEASE':
                self._release()
                return self._finish(context) if self._drag is None and not self._eaten else {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}                 # key repeat
        if self._drag is not None:
            what, button, area, region, last, snap = self._drag
            try:
                if t in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
                    self._drag = (what, button, area, region, (event.mouse_x, event.mouse_y), snap)
                    _drag(self._window, area, region, what, event.mouse_x - last[0], event.mouse_y - last[1])
                elif t == 'ESC' and event.value == 'PRESS':
                    restore(area.spaces.active, region.data, snap)
                    area.tag_redraw()
                    self._drag = None
                    self._eaten.add(button)
            except (ReferenceError, AttributeError):
                self._drag = None
            if self._drag is not None and t == button and event.value == 'RELEASE':
                self._drag = None
                return self._finish(context) if self._let_go else {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'} if self._drag is not None or not self._let_go else self._finish(context)
        if t in self._eaten and event.value == 'RELEASE':
            self._eaten.discard(t)
            return self._finish(context) if self._let_go and not self._eaten else {'RUNNING_MODAL'}
        if not self._let_go and event.value == 'PRESS':
            what = key_button(t, alt=event.alt)
            if what == 'NOTHING':
                self._eaten.add(t)
                return {'RUNNING_MODAL'}
            if what is not None:
                found = _view_at(self._window, event.mouse_x, event.mouse_y)
                if found is not None:
                    area, region = found
                    self._view = found
                    self._drag = (what, t, area, region, (event.mouse_x, event.mouse_y),
                                  snapshot(area.spaces.active, region.data))
                    return {'RUNNING_MODAL'}
        if t in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'} and self._eaten:
            return {'RUNNING_MODAL'}                 # a left drag while \\ is down does nothing
        if t == 'TIMER' and self._drag is None:
            if not self._let_go and keystate.is_down(self._key) is False:
                self._release()                      # the key's release went elsewhere
            if self._let_go:
                self._eaten = {b for b in self._eaten if keystate.is_down(b) is not False}
                if not self._eaten:
                    return self._finish(context)
        return {'PASS_THROUGH'}


class ALLSET_OT_pan_zoom_drag(bpy.types.Operator):
    """Drag to pan the picture in 2D (2D Pan) or to zoom it (2D Zoom); the camera stays (Maya 2D Pan/Zoom Tool)"""
    bl_idname = "allset.pan_zoom_drag"
    bl_label = "2D Pan/Zoom"
    bl_options = {'INTERNAL'}

    mode: EnumProperty(
        name="Mode", default='PAN',
        items=(('PAN', "2D Pan", "A drag pans the picture: it follows the mouse"),
               ('ZOOM', "2D Zoom", "A drag zooms the picture: right / down zooms in, left / up zooms out")))
    zoom_scale: FloatProperty(name="Zoom scale", description="How fast a 2D Zoom drag zooms", default=1.0,
                              min=0.01, soft_max=10.0)

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        self._button, self._last = event.type, (event.mouse_x, event.mouse_y)
        self._window, self._area, self._region = context.window, context.area, context.region
        self._snap = snapshot(context.space_data, context.region_data)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        try:
            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
                dx, dy = event.mouse_x - self._last[0], event.mouse_y - self._last[1]
                self._last = (event.mouse_x, event.mouse_y)
                _drag(self._window, self._area, self._region, self.mode, dx, dy, self.zoom_scale)
                return {'RUNNING_MODAL'}
            if event.type == self._button and event.value == 'RELEASE':
                return {'FINISHED'}
            if event.type == 'ESC' and event.value == 'PRESS':
                restore(self._area.spaces.active, self._region.data, self._snap)
                self._area.tag_redraw()
                return {'CANCELLED'}
        except (ReferenceError, AttributeError):
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class ALLSET_OT_pan_zoom_box(bpy.types.Operator):
    """Drag a box to zoom the picture into it in 2D; the camera stays (Maya 2D Pan/Zoom Tool, Ctrl+drag)"""
    bl_idname = "allset.pan_zoom_box"
    bl_label = "2D Box Zoom"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _poll(context) and context.region is not None and context.region.type == 'WINDOW'

    def invoke(self, context, event):
        self._button = event.type
        self._start = self._end = (event.mouse_region_x, event.mouse_region_y)
        self._window, self._area, self._region = context.window, context.area, context.region
        self._handle = context.space_data.draw_handler_add(self._draw, (), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _draw(self):
        if bpy.context.region != self._region:
            return
        (x0, y0), (x1, y1) = self._start, self._end
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINE_LOOP', {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]})
        gpu.state.blend_set('ALPHA')
        shader.uniform_float("color", (1.0, 1.0, 1.0, 0.8))
        batch.draw(shader)
        gpu.state.blend_set('NONE')

    def _end_box(self):
        try:
            self._area.spaces.active.draw_handler_remove(self._handle, 'WINDOW')
            self._region.tag_redraw()
        except (ReferenceError, AttributeError, ValueError):
            pass

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._end = (event.mouse_x - self._region.x, event.mouse_y - self._region.y)
            self._region.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'ESC' and event.value == 'PRESS':
            self._end_box()
            return {'CANCELLED'}
        if event.type == self._button and event.value == 'RELEASE':
            self._end = (event.mouse_x - self._region.x, event.mouse_y - self._region.y)
            self._end_box()
            (x0, y0), (x1, y1) = self._start, self._end
            if abs(x1 - x0) < MIN_BOX and abs(y1 - y0) < MIN_BOX:
                return {'CANCELLED'}
            region = self._region
            box(self._area.spaces.active, region.data, (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)),
                (region.width, region.height), (self._window, self._area))
            self._area.tag_redraw()
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


classes = (ALLSET_OT_pan_zoom_hold, ALLSET_OT_pan_zoom_drag, ALLSET_OT_pan_zoom_box)
