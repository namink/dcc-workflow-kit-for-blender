# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Graph Editor Edit > Transformation Tools > Sculpting Tools: Grab, Smooth, Smear and Key Reducer brushes.

The tool stays on in the Graph Editor (like the Retime Tool) until Esc or Q / W / E / R / T. A left drag is one stroke
(one undo step); B + left drag sideways changes the brush size. Like Maya the brush spans a number of frames across
(the same at any zoom of the time axis) and a number of screen pixels up and down (``brush_distance``); its weight
falls off smoothly from 1 in the middle to 0 at the edge (``falloff``), and it acts on the selected keys, or on every
key of the shown curves when none is selected. The brushes change key values only, not their times:

- Grab: the keys under the brush when the stroke starts follow the mouse up and down, each by its weight.
- Smear: the keys under the brush at each mouse move follow that move, so a stroke drags keys along its path.
- Smooth: each key under the brush moves part of the way toward the mean of its two neighbours at each mouse move
  (half the way at full weight).
- Key Reducer: a key under the brush that lies on the line between its neighbours (within a few pixels) is deleted;
  the first and last key of a curve stay.

The maths (``falloff``, ``smooth_target``, ``reducible``) is bpy-free.
"""

import math

import bpy

from .. import live_refs
from .. import i18n

MODES = (
    ('GRAB', "Grab Tool", "Push the keys under the brush up or down as you drag (Maya Sculpting Tools > Grab Tool)"),
    ('SMOOTH', "Smooth Tool", "Soften the keys as the brush moves over them (Maya Sculpting Tools > Smooth Tool)"),
    ('SMEAR', "Smear Tool", "Move the keys the brush passes over along with the drag (Maya Sculpting Tools > Smear "
     "Tool)"),
    ('REDUCE', "Key Reducer Tool", "Delete the keys the brush passes over that the curve can do without (Maya "
     "Sculpting Tools > Key Reducer Tool)"),
)
RADIUS_PX = 50.0                    # brush height radius (screen pixels at UI scale 1)
FRAMES_PER_PX = 3.4 / 50.0          # brush width radius = this × the height radius, in frames: like Maya the brush
                                    # covers the same frames at any zoom of the time axis
STRENGTH = {'GRAB': 1.0, 'SMOOTH': 1.0, 'SMEAR': 1.0, 'REDUCE': 0.1}
SMOOTH_RATE = 0.5                   # Smooth: share of the way to the neighbours' mean per mouse move at full weight
REDUCE_PX = 20.0                    # Key Reducer: a key within strength × this many pixels of the neighbours' line goes
_FALL = ((0.0, 1.0, 0.0), (0.25, 0.9, -1.0), (0.75, 0.1, -1.0), (1.0, 0.0, 0.0))   # (distance, weight, slope)


def falloff(u):
    """Brush weight at ``u`` = distance / radius: 1 in the middle, 0 at the edge and beyond (a smooth curve through
    0.9 at a quarter and 0.1 at three quarters of the radius)."""
    if u <= 0.0:
        return 1.0
    if u >= 1.0:
        return 0.0
    for (x0, y0, m0), (x1, y1, m1) in zip(_FALL, _FALL[1:]):
        if u <= x1:
            h = x1 - x0
            t = (u - x0) / h
            t2, t3 = t * t, t * t * t
            return ((2 * t3 - 3 * t2 + 1) * y0 + (t3 - 2 * t2 + t) * h * m0 + (-2 * t3 + 3 * t2) * y1
                    + (t3 - t2) * h * m1)
    return 0.0


def smooth_target(prev, cur, nxt):
    """Value a Smooth stroke pulls a key toward: the mean of its neighbours (the key itself at a curve end)."""
    if prev is None or nxt is None:
        return cur
    return (prev + nxt) / 2.0


def reducible(p0, p, p1, tol):
    """A key at screen point ``p`` between neighbours ``p0`` and ``p1`` lies on their line within ``tol`` pixels."""
    (x0, y0), (x, y), (x1, y1) = p0, p, p1
    if x1 - x0 <= 1e-9:
        return False
    line = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return abs(y - line) <= tol


# --- curves on screen ---------------------------------------------------------------------------------------------

def _display(context, fcurves):
    """Per curve (scale, offset): display value = value / scale + offset (rotation in degrees, normalized view)."""
    from . import graph_move
    scales = graph_move._value_scales(context, fcurves)
    return [(k or 1.0, graph_move._offset(context, fc) / (k or 1.0)) for fc, k in zip(fcurves, scales)]


def _shown_curves(context):
    return [fc for fc in (getattr(context, "editable_fcurves", None) or ())
            if len(fc.keyframe_points) and not fc.lock and not fc.hide]


def target_keys(context):
    """[(fc, scale, offset, [key index...])]: the selected keys, or every key of the shown curves."""
    fcs = _shown_curves(context)
    disp = _display(context, fcs)
    sel = [(fc, d, [i for i, kp in enumerate(fc.keyframe_points) if kp.select_control_point])
           for fc, d in zip(fcs, disp)]
    if any(ix for _fc, _d, ix in sel):
        return [(fc, d[0], d[1], ix) for fc, d, ix in sel if ix]
    return [(fc, d[0], d[1], list(range(len(fc.keyframe_points)))) for fc, d in zip(fcs, disp)]


def brush_distance(dt_frames, dy_px, radius_px, ui_scale=1.0):
    """Distance of a key from the brush middle as a share of the brush radius: ``dt_frames`` across (the radius spans
    ``radius_px`` / ``ui_scale`` × FRAMES_PER_PX frames), ``dy_px`` up / down (the radius spans ``radius_px``
    pixels)."""
    r = max(radius_px, 1.0)
    return math.hypot(dt_frames / (r / (ui_scale or 1.0) * FRAMES_PER_PX), dy_px / r)


def _ui_scale():
    return bpy.context.preferences.system.ui_scale or 1.0


def _screen(region, t, v, scale, offset):
    return region.view2d.view_to_region(t, v / scale + offset, clip=False)


def _view_y(region, y):
    return region.view2d.region_to_view(0, y)[1]


def _snapshot(fcs):
    return [(fc, [(tuple(kp.co), tuple(kp.handle_left), tuple(kp.handle_right), kp.interpolation,
                   kp.handle_left_type, kp.handle_right_type, kp.select_control_point) for kp in fc.keyframe_points])
            for fc in fcs]


def _restore(snap):
    for fc, pts in snap:
        kps = fc.keyframe_points
        if len(kps) != len(pts):
            while len(kps) > len(pts):
                kps.remove(kps[-1], fast=True)
            for p in pts[len(kps):]:
                kps.insert(p[0][0], p[0][1], options={'FAST'})
        for kp, (co, hl, hr, ip, lt, rt, sel) in zip(kps, pts):
            kp.interpolation, kp.handle_left_type, kp.handle_right_type = ip, lt, rt
            kp.co, kp.handle_left, kp.handle_right = co, hl, hr
            kp.select_control_point = sel
        fc.update()


def _set_value(kp, v):
    dy = v - kp.co.y
    kp.co.y = v
    kp.handle_left.y += dy
    kp.handle_right.y += dy


def _recalc(fc):
    pts = fc.keyframe_points
    if hasattr(pts, "handles_recalc"):
        pts.handles_recalc()
    else:
        fc.update()


# --- drawing --------------------------------------------------------------------------------------------------------

_DRAW = {"handle": None, "area": None, "pos": None, "radius": 0.0, "active": False}


def _draw():
    area = bpy.context.area
    if area is None or area.as_pointer() != _DRAW["area"] or _DRAW["pos"] is None:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    x, y = _DRAW["pos"]
    r = _DRAW["radius"]
    rx = r / _ui_scale() * FRAMES_PER_PX * _DRAW.get("ppf", 1.0)
    pts = [(x + rx * math.cos(2 * math.pi * j / 48), y + r * math.sin(2 * math.pi * j / 48)) for j in range(49)]
    sh = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    sh.bind()
    sh.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    sh.uniform_float("lineWidth", 2.0 if _DRAW["active"] else 1.5)
    sh.uniform_float("color", (1.0, 0.85, 0.35, 0.95) if _DRAW["active"] else (0.95, 0.95, 0.95, 0.8))
    batch_for_shader(sh, 'LINE_STRIP', {"pos": pts}).draw(sh)
    gpu.state.blend_set('NONE')


def _ensure_draw():
    if _DRAW["handle"] is None:
        _DRAW["handle"] = bpy.types.SpaceGraphEditor.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL')


def _remove_draw():
    if _DRAW["handle"] is not None:
        bpy.types.SpaceGraphEditor.draw_handler_remove(_DRAW["handle"], 'WINDOW')
        _DRAW["handle"] = None
    _DRAW.update(area=None, pos=None)


# --- the tool --------------------------------------------------------------------------------------------------------

class ALLSET_OT_graph_sculpt(bpy.types.Operator):
    """Maya Graph Editor sculpting brush: drag over the curves to grab, smooth, smear or reduce their keys (B + drag
    sideways: brush size). Esc or Q / W / E / R / T ends the tool"""
    bl_idname = "allset.graph_sculpt"
    bl_label = "Sculpt Keys"
    bl_options = {'UNDO'}

    mode: bpy.props.EnumProperty(items=MODES, name="Brush", default='GRAB', options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return next(d for k, _l, d in MODES if k == props.mode)

    @classmethod
    def poll(cls, context):
        area = getattr(context, "area", None)
        return area is not None and area.type == 'GRAPH_EDITOR' and context.window is not None

    def invoke(self, context, event):
        return self._start(context)

    def execute(self, context):
        return self._start(context)

    def _start(self, context):
        area = context.area
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None:
            return {'CANCELLED'}
        self._win_ptr = context.window.as_pointer()
        self._area_ptr = area.as_pointer()
        self._region_ptr = region.as_pointer()
        self._stroke = None
        self._resize = None
        self._b = False
        wm = context.window_manager
        s = context.preferences.system.ui_scale or 1.0
        if wm.allset_sculpt_keys_radius <= 0:
            wm.allset_sculpt_keys_radius = RADIUS_PX * s
        _ensure_draw()
        _DRAW.update(area=self._area_ptr, radius=wm.allset_sculpt_keys_radius, active=False, pos=None)
        wm.modal_handler_add(self)
        area.header_text_set(f"{next(l for k, l, _d in MODES if k == self.mode)}: drag over the curves · "
                             "B + drag: brush size · Esc: done")
        return {'RUNNING_MODAL'}

    def _live(self):
        win, area = live_refs.find_area(self._area_ptr, self._win_ptr)
        if area is None:
            return None, None, None
        return win, area, live_refs.region(area, self._region_ptr)

    def _end(self, area=None):
        if self._stroke is not None:
            _restore(self._stroke["snap"])
        self._stroke = None
        _remove_draw()
        if area is not None:
            area.header_text_set(None)
            area.tag_redraw()
        return {'CANCELLED'}

    def modal(self, context, event):
        win, area, region = self._live()
        if region is None:
            return self._end()
        x, y = event.mouse_x - region.x, event.mouse_y - region.y
        inside = 0 <= x < region.width and 0 <= y < region.height
        wm = context.window_manager
        _DRAW["pos"] = (x, y) if inside or self._stroke or self._resize else None
        _DRAW["radius"] = wm.allset_sculpt_keys_radius
        v2d = region.view2d
        _DRAW["ppf"] = v2d.view_to_region(1, 0, clip=False)[0] - v2d.view_to_region(0, 0, clip=False)[0]
        area.tag_redraw()

        if event.type == 'B':
            self._b = event.value != 'RELEASE'
            return {'RUNNING_MODAL'}
        if self._resize is not None:
            if event.type == 'MOUSEMOVE':
                x0, r0 = self._resize
                wm.allset_sculpt_keys_radius = max(4.0, r0 + (x - x0))
            elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                self._resize = None
            return {'RUNNING_MODAL'}
        if self._stroke is not None:
            return self._modal_stroke(context, event, win, area, region, x, y)
        if event.type == 'ESC' and event.value == 'PRESS':
            return self._end(area)
        if event.type in {'Q', 'W', 'E', 'R', 'T'} and event.value == 'PRESS' and not (event.ctrl or event.alt):
            self._end(area)
            return {'CANCELLED', 'PASS_THROUGH'}
        if event.type != 'LEFTMOUSE' or event.value != 'PRESS' or not inside:
            return {'PASS_THROUGH'}
        if event.shift or event.ctrl or event.alt:
            return {'PASS_THROUGH'}
        if self._b:
            self._resize = (x, wm.allset_sculpt_keys_radius)
            return {'RUNNING_MODAL'}
        with bpy.context.temp_override(window=win, area=area, region=region):
            keys = target_keys(bpy.context)
        if not keys:
            return {'RUNNING_MODAL'}
        self._stroke = {"keys": keys, "snap": _snapshot([k[0] for k in keys]), "x": x, "y": y, "last": (x, y),
                        "grab": self._weights(region, keys, x, y) if self.mode == 'GRAB' else None, "changed": False}
        _DRAW["active"] = True
        return {'RUNNING_MODAL'}

    def _weights(self, region, keys, x, y):
        """[(fc, index, base value, weight, scale)] of the keys under the brush at (x, y)."""
        r = bpy.context.window_manager.allset_sculpt_keys_radius
        t = region.view2d.region_to_view(x, y)[0]
        out = []
        for fc, scale, off, ix in keys:
            pts = fc.keyframe_points
            for i in ix:
                kp = pts[i]
                sx, sy = _screen(region, kp.co.x, kp.co.y, scale, off)
                w = falloff(brush_distance(kp.co.x - t, sy - y, r, _ui_scale()))
                if w > 0.0:
                    out.append((fc, i, kp.co.y, w, scale))
        return out

    def _modal_stroke(self, context, event, win, area, region, x, y):
        st = self._stroke
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            _restore(st["snap"])
            self._stroke = None
            _DRAW["active"] = False
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            self._apply(region, x, y)
            st["last"] = (x, y)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self._stroke = None
            _DRAW["active"] = False
            if st["changed"]:
                bpy.ops.ed.undo_push(message="Sculpt Keys")
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    def _apply(self, region, x, y):
        st = self._stroke
        k = STRENGTH[self.mode]
        touched = set()
        if self.mode == 'GRAB':
            dv = _view_y(region, y) - _view_y(region, st["y"])
            for fc, i, base, w, scale in st["grab"]:
                _set_value(fc.keyframe_points[i], base + dv * w * k * scale)
                touched.add(fc)
        elif self.mode == 'SMEAR':
            dv = _view_y(region, y) - _view_y(region, st["last"][1])
            for fc, i, _base, w, scale in self._weights(region, st["keys"], x, y):
                kp = fc.keyframe_points[i]
                _set_value(kp, kp.co.y + dv * w * k * scale)
                touched.add(fc)
        elif self.mode == 'SMOOTH':
            for fc, i, _base, w, _scale in self._weights(region, st["keys"], x, y):
                pts = fc.keyframe_points
                prev = pts[i - 1].co.y if i > 0 else None
                nxt = pts[i + 1].co.y if i + 1 < len(pts) else None
                kp = pts[i]
                goal = smooth_target(prev, kp.co.y, nxt)
                _set_value(kp, kp.co.y + (goal - kp.co.y) * min(1.0, w * k * SMOOTH_RATE))
                touched.add(fc)
        else:
            touched = self._reduce(region, x, y, k)
        for fc in touched:
            _recalc(fc)
        if touched:
            st["changed"] = True

    def _reduce(self, region, x, y, k):
        st = self._stroke
        r = bpy.context.window_manager.allset_sculpt_keys_radius
        t = region.view2d.region_to_view(x, y)[0]
        tol = REDUCE_PX * k * (bpy.context.preferences.system.ui_scale or 1.0)
        touched = set()
        for n, (fc, scale, off, ix) in enumerate(st["keys"]):
            pts = fc.keyframe_points
            for i in sorted(ix, reverse=True):
                if i <= 0 or i >= len(pts) - 1:
                    continue
                p = _screen(region, pts[i].co.x, pts[i].co.y, scale, off)
                if brush_distance(pts[i].co.x - t, p[1] - y, r, _ui_scale()) > 1.0:
                    continue
                p0 = _screen(region, pts[i - 1].co.x, pts[i - 1].co.y, scale, off)
                p1 = _screen(region, pts[i + 1].co.x, pts[i + 1].co.y, scale, off)
                if reducible(p0, p, p1, tol):
                    pts.remove(pts[i])
                    touched.add(fc)
            if fc in touched:          # key indices after a removal
                sel = any(kp.select_control_point for kp in pts)
                new_ix = [j for j, kp in enumerate(pts) if kp.select_control_point] if sel else list(range(len(pts)))
                st["keys"][n] = (fc, scale, off, new_ix)
        return touched


classes = (ALLSET_OT_graph_sculpt,)


def register_props():
    bpy.types.WindowManager.allset_sculpt_keys_radius = bpy.props.FloatProperty(
        name="Brush Size", default=0.0, min=0.0, subtype='PIXEL',
        description="Size of the Graph Editor sculpting brushes: pixels up and down (the frames across follow)")


def unregister():
    _remove_draw()
    if hasattr(bpy.types.WindowManager, "allset_sculpt_keys_radius"):
        del bpy.types.WindowManager.allset_sculpt_keys_radius
