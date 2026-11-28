# SPDX-License-Identifier: GPL-3.0-or-later
"""Graph Editor Select > Pre-Select Highlight, like Maya: the curve under the mouse is drawn brighter before you
click it.

Add-on pref ``graph_preselect`` (off by default, like Maya). ``allset.graph_hover`` watches the Graph Editor's mouse
moves (always PASS_THROUGH) and keeps, per editor, the shown curve whose line passes within ``HOVER_PX`` of the
mouse (the nearest one); the editor redraws only when that curve changes. ``_draw`` draws it again over the editor
in a lighter tint of its own colour. Like Maya, the highlight stays when the mouse leaves the curve view (onto the
channel list, another editor or out of the window) until the mouse moves over the curve view again, and it goes
while a drag runs there (moving keys, a marquee, panning): ``allset.graph_hover_drop`` (a left-button drag start,
a middle-button press) drops it and it comes back with the next mouse move after the drag.
``allset.hover_leave`` (a "Window" keymap mouse-move item, so it sees moves over every other area and region) drops
the Time Slider's bookmark name (``ui/time_slider_bookmarks.py``) once the mouse is outside the Time Slider. Pure
rules: ``segment_distance``, ``nearest_curve``, ``lighter``, ``inside``.
"""

import math

import bpy

from . import graph_move

HOVER_PX = 2.5           # how close to a curve line the mouse must be (x UI scale), about as close as in Maya
WIDTH_PX = 2.5           # width of the highlight line (x UI scale)
SAMPLES = 8              # curve samples around the mouse for the pick
STEP_PX = 2.0            # one curve sample every this many pixels when drawing

_hover = {}              # area pointer -> curve pointer
_handles = []


# --- pure rules -------------------------------------------------------------------------------------------------

def segment_distance(p, a, b):
    """Distance from point ``p`` to the segment ``a``-``b`` (2D)."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0.0 if n < 1e-12 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / n))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def nearest_curve(p, polylines, tol):
    """Key of the polyline (``{key: [(x, y), ...]}``) passing nearest to ``p`` within ``tol``, None if none."""
    best, best_d = None, tol
    for key, pts in polylines.items():
        if len(pts) == 1:
            d = math.hypot(p[0] - pts[0][0], p[1] - pts[0][1])
        else:
            d = min((segment_distance(p, pts[i], pts[i + 1]) for i in range(len(pts) - 1)), default=math.inf)
        if d <= best_d:
            best, best_d = key, d
    return best


def inside(x, y, rect):
    """True when window (x, y) lies in ``rect`` = (x, y, width, height)."""
    rx, ry, rw, rh = rect
    return rx <= x < rx + rw and ry <= y < ry + rh


def lighter(rgb, amount=0.6):
    """``rgb`` mixed toward white by ``amount``."""
    return tuple(c + (1.0 - c) * amount for c in rgb)


# --- the Graph Editor ---------------------------------------------------------------------------------------------

def enabled(context=None):
    from .. import preferences
    try:
        return bool(preferences.get(context).graph_preselect)
    except (KeyError, AttributeError):
        return False


def _curves(context):
    fcs = [fc for fc in (getattr(context, "visible_fcurves", None) or ()) if not fc.hide]
    return fcs, (graph_move._value_scales(context, fcs) if fcs else [])


def _mapping(region):
    """Region pixels = (a x frame + b, c x display value + d). From the region's corners (``region_to_view`` gives
    floats; ``view_to_region`` rounds to whole pixels, too coarse over one unit of a centimetre value axis)."""
    w, h = max(region.width, 2), max(region.height, 2)
    t0, v0 = region.view2d.region_to_view(0, 0)
    t1, v1 = region.view2d.region_to_view(w, h)
    if abs(t1 - t0) < 1e-12 or abs(v1 - v0) < 1e-12:
        return 0.0, 0.0, 0.0, 0.0
    a, c = w / (t1 - t0), h / (v1 - v0)
    return a, -a * t0, c, -c * v0


def _polyline(fc, scale, off, frames, m):
    a, b, c, d = m
    return [(a * t + b, c * ((fc.evaluate(t) + off) / scale) + d) for t in frames]


def pick(context, x, y):
    """Pointer of the shown curve whose line passes nearest to region (x, y), None if none is close."""
    region = context.region
    ui = context.preferences.system.ui_scale or 1.0
    tol = HOVER_PX * ui
    m = _mapping(region)
    if abs(m[0]) < 1e-9 or abs(m[2]) < 1e-9:
        return None
    t = (x - m[1]) / m[0]
    half = tol / abs(m[0])
    frames = [t - half + 2 * half * k / (SAMPLES - 1) for k in range(SAMPLES)]
    fcs, scales = _curves(context)
    lines = {fc.as_pointer(): _polyline(fc, scale, graph_move._offset(context, fc), frames, m)
             for fc, scale in zip(fcs, scales)}
    return nearest_curve((x, y), lines, tol)


def hovered(context):
    area = getattr(context, "area", None)
    return _hover.get(area.as_pointer()) if area is not None else None


class ALLSET_OT_graph_hover(bpy.types.Operator):
    """Graph Editor: remember the curve under the mouse for the pre-selection highlight"""
    bl_idname = "allset.graph_hover"
    bl_label = "Graph Editor Hover"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        area = context.area
        if area is None or area.type != 'GRAPH_EDITOR':
            return {'PASS_THROUGH'}
        key = area.as_pointer()
        before = _hover.get(key)
        now = None
        if enabled(context) and graph_move._graph_window(context):
            try:
                now = pick(context, event.mouse_region_x, event.mouse_region_y)
            except (AttributeError, ReferenceError, RuntimeError, ValueError):
                now = None
        if now is None:
            _hover.pop(key, None)
        else:
            _hover[key] = now
        if now != before:
            area.tag_redraw()
        return {'PASS_THROUGH'}


class ALLSET_OT_hover_leave(bpy.types.Operator):
    """Drop the Time Slider's bookmark name once the mouse is outside the Time Slider (the Graph Editor's
    pre-selection highlight stays, like Maya)"""
    bl_idname = "allset.hover_leave"
    bl_label = "Hover Leave"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        from ..ui import time_slider_bookmarks as tsb
        if tsb._hover:
            try:
                for area in tsb.forget_outside(context.window_manager, context.window, event.mouse_x, event.mouse_y):
                    area.tag_redraw()
            except (AttributeError, ReferenceError):
                tsb._hover.clear()
        return {'PASS_THROUGH'}


class ALLSET_OT_graph_hover_drop(bpy.types.Operator):
    """Graph Editor: a drag starts (a key move, a marquee, a pan): no pre-selection highlight until the next mouse
    move after it, like Maya"""
    bl_idname = "allset.graph_hover_drop"
    bl_label = "Graph Editor Hover Drop"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        area = context.area
        if area is not None and _hover.pop(area.as_pointer(), None) is not None:
            area.tag_redraw()
        return {'PASS_THROUGH'}


def _draw():
    context = bpy.context
    try:
        ptr = hovered(context)
        if ptr is None or not enabled(context) or not graph_move._graph_window(context):
            return
        fcs, scales = _curves(context)
        hit = next(((fc, s) for fc, s in zip(fcs, scales) if fc.as_pointer() == ptr), None)
        if hit is None:
            return
        fc, scale = hit
        region = context.region
        m = _mapping(region)
        if abs(m[0]) < 1e-9:
            return
        n = max(2, int(region.width / STEP_PX) + 2)
        t0 = (0 - m[1]) / m[0]
        t1 = (region.width - m[1]) / m[0]
        frames = [t0 + (t1 - t0) * k / (n - 1) for k in range(n)]
        pts = _polyline(fc, scale, graph_move._offset(context, fc), frames, m)
        rgb = lighter(tuple(fc.color))
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    ui = context.preferences.system.ui_scale or 1.0
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_float("lineWidth", WIDTH_PX * ui)
    shader.uniform_float("color", (*rgb, 0.95))
    batch_for_shader(shader, 'LINE_STRIP', {"pos": pts}).draw(shader)
    gpu.state.blend_set('NONE')


classes = (ALLSET_OT_graph_hover, ALLSET_OT_hover_leave, ALLSET_OT_graph_hover_drop)


def register_handlers():
    _handles.append(bpy.types.SpaceGraphEditor.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL'))


def unregister_handlers():
    while _handles:
        bpy.types.SpaceGraphEditor.draw_handler_remove(_handles.pop(), 'WINDOW')
    _hover.clear()
