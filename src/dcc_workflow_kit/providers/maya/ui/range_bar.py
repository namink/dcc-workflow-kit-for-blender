# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's Range Slider bar in the timeline header: drag the playback range.

The bar: a dark
track (#373737) spans the animation range, the playback range is a rounded segment (#5d5d5d) on it with
a handle square (#919191) inside each end and the start / end frames next to the handles. Dragging the
segment moves the playback range, dragging a handle moves that end.

Blender has no such widget and Python can't tell where a header layout put an item, so
``time_slider.draw_range_slider`` leaves an empty label where the bar goes (a button would take the
mouse) and the header POST_PIXEL handler here finds that gap by reading one row of the header it has
just drawn (``bar_span``), draws the bar there and remembers the rectangle for
``allset.range_bar_drag`` ("Screen" keymap: a click on an empty label reaches the window keymaps).
Only in timelines whose transport buttons sit in the sidebar (the Maya Workflow Kit layout), where nothing
stretches before the bar.
"""

import bpy

# --- sizes and colours ----------------------------------------------------------------
TRACK_RGB = (0x37 / 255, 0x37 / 255, 0x37 / 255, 1.0)
SEGMENT_RGB = (0x5d / 255, 0x5d / 255, 0x5d / 255, 1.0)
HANDLE_RGB = (0x91 / 255, 0x91 / 255, 0x91 / 255, 1.0)
TEXT_RGB = (0.8, 0.8, 0.8, 1.0)            # light grey of the frame numbers


def _themed(color, field):
    """A Range Slider colour moved with the Blender theme's Timeline colours (ui/theme_follow.py)."""
    from . import theme_follow
    return theme_follow.follow(color, "dopesheet_editor", field)


MAYA_BAR_H = 23.0                          # track height
SEG_INSET = 2.0                            # segment inside the track
HANDLE = (13.0, 14.0)                      # handle square w, h
HANDLE_INSET = 5.0                         # from the segment end
TEXT_PX = 11.0
BAR_UNITS = 18                             # ui_units_x of the placeholder label on a wide header
MIN_BAR_UNITS = 4                          # the label never gets narrower than this (a short header)
MIN_FRAME = 0                              # Blender's frame range
MAX_FRAME = 1048574

_bars = {}       # area pointer -> rectangle and range, region-local (filled while drawing)
_handle = []
# Like Maya the bar fills the header between the playback fields and the right-hand buttons. A header layout has no
# stretching item, so the bar label is BAR_UNITS + the extra units here, and each draw moves the extra toward
# the spare room it sees (the spacer after the end fields).
_extra = {}      # area pointer -> extra ui units of the bar label
_planned = {}    # area pointer -> the label's base ui units this draw (time_slider.row_plan: shorter on a short header)
_gaps = {}       # area pointer -> (header size and bar width, (span, spare)) of the last header row read
row_reads = [0]  # header rows read so far
SPARE_UNITS = 1  # room left in the spacer
SHRINK_UNITS = 4  # step back when the spacer is gone (the header ran out of room)


# --- pure helpers (tests/test_step73_time_slider.py) --------------------------------------------------

def bar_span(row, bg, min_w, skip=2):
    """(x0, x1) of the first run of ``bg`` at least ``min_w`` wide that follows ``skip`` non-``bg`` runs
    in ``row`` (a list of colours), or None."""
    runs, start = [], 0
    for i in range(1, len(row) + 1):
        if i == len(row) or (row[i] == bg) != (row[start] == bg):
            runs.append((start, i, row[start] == bg))
            start = i
    seen = 0
    for a, b, is_bg in runs:
        if not is_bg:
            seen += 1
        elif seen >= skip and b - a >= min_w and b < len(row):
            return a, b
    return None


def spare_after(row, end, bg, skip=2):
    """Width of the ``bg`` run after ``skip`` non-``bg`` runs that start at ``end`` in ``row`` (the spacer after
    the playback end / animation end fields), 0 when there is none (or it runs to the edge)."""
    i, n, seen = end, len(row), 0
    while i < n:
        j = i
        is_bg = row[i] == bg
        while j < n and (row[j] == bg) == is_bg:
            j += 1
        if not is_bg:
            seen += 1
        elif seen >= skip:
            return j - i if j < n else 0
        i = j
    return 0


def row_runs(codes):
    """[(start, end, is background)] runs of a header row given as one number per pixel (``codes``, a numpy array),
    the background being the colour of the row's third pixel (``find_gap``): the runs ``bar_span`` and
    ``spare_after`` walk, found with array operations instead of one Python step per pixel."""
    import numpy as np
    n = len(codes)
    if n == 0:
        return []
    is_bg = codes == codes[min(2, n - 1)]
    cuts = (np.flatnonzero(is_bg[1:] != is_bg[:-1]) + 1).tolist()
    starts = [0] + cuts
    ends = cuts + [n]
    flags = is_bg[starts].tolist()
    return list(zip(starts, ends, flags))


def gap_of_runs(runs, n, min_w, skip=2):
    """(``bar_span``, ``spare_after`` of that span) of a row of ``n`` pixels from its ``row_runs``: the same answer
    as the per-pixel helpers."""
    span, at, seen = None, None, 0
    for k, (a, b, is_bg) in enumerate(runs):
        if not is_bg:
            seen += 1
        elif seen >= skip and b - a >= min_w and b < n:
            span, at = (a, b), k + 1
            break
    if span is None:
        return None, 0
    seen = 0
    for a, b, is_bg in runs[at:]:
        if not is_bg:
            seen += 1
        elif seen >= skip:
            return span, (b - a if b < n else 0)
    return span, 0


def next_extra(extra, spare_px, unit, floor=0):
    """The bar's next extra ui units from the spare room ``spare_px`` in the header this draw. ``floor``: how far
    below the base width the label may shrink (negative) when the header has no room at all."""
    room = spare_px / unit - SPARE_UNITS
    if spare_px <= 0:
        return max(floor, extra - SHRINK_UNITS)
    if room >= 1 or room < 0:
        return max(floor, extra + int(room // 1))
    return extra


def extra_units(area):
    return _extra.get(area.as_pointer(), 0) if area is not None else 0


def plan_units(area, units=None):
    """Remember (``units`` given) or read the label's base width for ``area`` (BAR_UNITS when unknown)."""
    if area is None:
        return float(BAR_UNITS)
    if units is not None:
        _planned[area.as_pointer()] = float(units)
    return _planned.get(area.as_pointer(), float(BAR_UNITS))


def _redraw_later(area_ptr):
    def tick():
        from .. import live_refs
        a = live_refs.area(area_ptr)
        if a is not None:
            a.tag_redraw()
        return None
    bpy.app.timers.register(tick, first_interval=0.0)


def frame_x(f, x0, x1, s, e):
    """x of frame ``f`` on a track x0..x1 that spans the animation range s..e."""
    return x0 + (f - s) / max(e - s, 1) * (x1 - x0)


def segment(bar, ps, pe):
    """(xs, xe) of the playback range on ``bar`` = dict(x0, x1, s, e), kept on the track."""
    x0, x1 = bar["x0"], bar["x1"]
    return tuple(max(x0, min(x1, frame_x(f, x0, x1, bar["s"], bar["e"]))) for f in (ps, pe))


def visual_segment(bar, ps, pe, handle_w, min_gap=2.0):
    """(xs, xe) of the playback segment as drawn: ``segment`` widened to two handle zones plus ``min_gap`` so the
    handles never overlap on a short range (start = end included), kept on the track."""
    xs, xe = segment(bar, ps, pe)
    need = 2.0 * handle_w + min_gap
    if xe - xs >= need:
        return xs, xe
    x0, x1 = bar["x0"], bar["x1"]
    c = (xs + xe) / 2.0
    xs, xe = c - need / 2.0, c + need / 2.0
    if xs < x0:
        xs, xe = x0, min(x1, x0 + need)
    elif xe > x1:
        xs, xe = max(x0, x1 - need), x1
    return xs, xe


def label_positions(xs, xe, handle_w, wa, wb, gap):
    """Left x of the start and end frame labels: inside the segment next to its handles when both fit there,
    otherwise just outside the segment (a short range)."""
    if wa + wb + 3.0 * gap <= xe - xs - 2.0 * handle_w:
        return xs + handle_w + gap, xe - handle_w - gap - wb
    return xs - gap - wa, xe + gap


def zone(x, xs, xe, handle_w):
    """What a press at ``x`` grabs: 'START' / 'END' handle, 'MOVE' the segment, or None."""
    if x < xs - 1 or x > xe + 1:
        return None
    if x <= xs + handle_w:
        return 'START'
    if x >= xe - handle_w:
        return 'END'
    return 'MOVE'


def drag_range(kind, ps, pe, d, s, e):
    """New (start, end) playback range after dragging ``kind`` by ``d`` whole frames inside s..e."""
    if kind == 'MOVE':
        d = max(s - ps, min(e - pe, d))
        return ps + d, pe + d
    if kind == 'START':
        return max(s, min(pe - 1, ps + d)), pe
    if kind == 'END':
        return ps, min(e, max(ps + 1, pe + d))
    return ps, pe


def playback(scene):
    if scene.use_preview_range:
        return scene.frame_preview_start, scene.frame_preview_end
    return scene.frame_start, scene.frame_end


def toggle_whole(scene):
    """Maya double-click on the Range Slider: the whole animation range <-> the playback range.
    Blender keeps the preview range while it is off, so this is the preview range toggle."""
    scene.use_preview_range = not scene.use_preview_range


def set_playback(scene, a, b):
    scene.use_preview_range = True
    # Blender pushes the other end when start > end: order the writes so neither clamps.
    if a > scene.frame_preview_end:
        scene.frame_preview_end = b
        scene.frame_preview_start = a
    else:
        scene.frame_preview_start = a
        scene.frame_preview_end = b


# Maya's playback start / end fields: always the range that plays. With the preview range off that is the
# animation range (Blender keeps its own preview values meanwhile, so the double-click toggle finds them again);
# typing another number turns the preview range on with it. Start past the end pushes the end, like Blender.
def _get_playback_start(scene):
    return playback(scene)[0]


def _set_playback_start(scene, value):
    ps, pe = playback(scene)
    if value != ps:
        set_playback(scene, value, max(value, pe))


def _get_playback_end(scene):
    return playback(scene)[1]


def _set_playback_end(scene, value):
    ps, pe = playback(scene)
    if value != pe:
        set_playback(scene, min(ps, value), value)


# --- drawing -------------------------------------------------------------------------------------------

def active(context):
    from . import time_slider
    space = context.space_data
    # the Maya Workflow Kit layout's timeline (sidebar on; on 5.x it can't open — the bar stays in the header)
    return (space is not None and getattr(space, "mode", None) == 'TIMELINE'
            and time_slider.has_slider_panel(space))


_shapes = {}     # (x0, y0, x1, y1, r) -> GPU batch of that rounded rectangle (the bar redraws the same ones)


def _rounded(x0, y0, x1, y1, r, colour):
    import math
    import gpu
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    key = (x0, y0, x1, y1, r)
    batch = _shapes.get(key)
    if batch is None:
        from gpu_extras.batch import batch_for_shader
        r = max(0.0, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
        pts = []
        for cx, cy, a0 in ((x1 - r, y1 - r, 0.0), (x0 + r, y1 - r, 90.0), (x0 + r, y0 + r, 180.0),
                           (x1 - r, y0 + r, 270.0)):
            for i in range(5):
                a = math.radians(a0 + 22.5 * i)
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        verts = [((x0 + x1) / 2.0, (y0 + y1) / 2.0)] + pts
        n = len(pts)
        batch = batch_for_shader(shader, 'TRIS', {"pos": verts},
                                 indices=[(0, 1 + i, 1 + (i + 1) % n) for i in range(n)])
        if len(_shapes) > 64:
            _shapes.clear()
        _shapes[key] = batch
    shader.uniform_float("color", colour)
    batch.draw(shader)


def _read_row(region, y):
    """One header row as one number per pixel (its RGB bytes, a numpy array; empty outside the region). The
    framebuffer read hands its bytes to numpy directly, instead of one Python colour per pixel."""
    import gpu
    import numpy as np
    fb = gpu.state.active_framebuffer_get()
    from .. import compat
    buf = compat.read_region_row(fb, region, y)
    if buf is None:
        return []
    px = np.frombuffer(buf, dtype=np.uint8).reshape(-1, 4)[:region.width].astype(np.int32)
    return px[:, 0] | (px[:, 1] << 8) | (px[:, 2] << 16)


def _codes(row):
    """A row as one number per pixel: ``_read_row``'s array as it is, a list of colours (``bar_span``'s rows) as
    one number per distinct colour."""
    import numpy as np
    if isinstance(row, np.ndarray):
        return row
    ids = {}
    return np.array([ids.setdefault(c, len(ids)) for c in row], dtype=np.int64)


def find_gap(area, region, unit, playing):
    """(span, spare) of the bar's gap in the header just drawn: ``bar_span`` and ``spare_after`` of one header row
    (``row_reads[0]`` counts the reads). While playback or a transform (a drag) runs the header keeps its layout, so
    the gap found for the same header size and bar width is used again instead of reading the row on every redraw
    (a framebuffer read and a scan of every pixel)."""
    key = (region.width, region.height, unit, plan_units(area), extra_units(area))
    got = _gaps.get(area.as_pointer())
    if playing and got is not None and got[0] == key:
        return got[1]
    row_reads[0] += 1
    row = _read_row(region, region.height // 2)
    if len(row) < 3:
        _gaps.pop(area.as_pointer(), None)
        return None
    codes = _codes(row)
    found = gap_of_runs(row_runs(codes), len(codes), min_w=(key[3] + min(0, key[4])) * unit * 0.6)
    _gaps[area.as_pointer()] = (key, found)
    return found


def draw():
    """POST_PIXEL of Dope Sheet HEADER regions."""
    context = bpy.context
    area, region = context.area, context.region
    if area is None or region is None or not active(context):
        return
    scale = context.preferences.system.ui_scale or 1.0
    unit = round(20 * scale)
    screen = context.screen
    from .maya_joints import scrubbing, transforming
    found = find_gap(area, region, unit, (screen is not None and screen.is_animation_playing) or transforming()
                     or scrubbing())
    if found is None:
        return
    span, spare = found
    if span is None:
        _bars.pop(area.as_pointer(), None)
        if _extra.pop(area.as_pointer(), 0):    # the bar no longer fits: start again from its base width
            _redraw_later(area.as_pointer())
        return
    key = area.as_pointer()
    extra = _extra.get(key, 0)
    planned = plan_units(area)
    grown = next_extra(extra, spare, unit, floor=-max(0, int(planned - MIN_BAR_UNITS)))
    if grown != extra:
        _extra[key] = grown
        _redraw_later(key)
    pad = round(4 * scale)
    x0, x1 = span[0] + pad, span[1] - pad
    y0 = (region.height - unit) / 2.0
    y1 = y0 + unit
    scene = context.scene
    s, e = scene.frame_start, scene.frame_end
    bar = dict(x0=x0, x1=x1, y0=y0, y1=y1, s=s, e=e, window=context.window.as_pointer(),
               region=region.as_pointer())
    _bars[area.as_pointer()] = bar

    import blf
    import gpu
    k = unit / MAYA_BAR_H
    gpu.state.blend_set('ALPHA')
    _rounded(x0, y0, x1, y1, 4 * k, _themed(TRACK_RGB, "back"))
    ps, pe = playback(scene)
    hw, hh = HANDLE[0] * k, HANDLE[1] * k
    bar["handle_w"] = (HANDLE_INSET + HANDLE[0]) * k
    xs, xe = visual_segment(bar, ps, pe, bar["handle_w"])
    inset = SEG_INSET * k
    _rounded(xs, y0 + inset, xe, y1 - inset, 4 * k, _themed(SEGMENT_RGB, "back"))
    hy0 = (y0 + y1 - hh) / 2.0
    hx0, hx1 = xs + HANDLE_INSET * k, xe - HANDLE_INSET * k - hw
    handle = _themed(HANDLE_RGB, "back")
    _rounded(hx0, hy0, hx0 + hw, hy0 + hh, 3 * k, handle)
    _rounded(hx1, hy0, hx1 + hw, hy0 + hh, 3 * k, handle)
    blf.size(0, TEXT_PX * scale)
    blf.color(0, *_themed(TEXT_RGB, "text"))
    ty = (y0 + y1) / 2.0 - TEXT_PX * scale * 0.35
    a_txt, b_txt = f"{ps:g}", f"{pe:g}"
    wa, wb = blf.dimensions(0, a_txt)[0], blf.dimensions(0, b_txt)[0]
    xa, xb = label_positions(xs, xe, bar["handle_w"], wa, wb, 3 * k)
    blf.position(0, xa, ty, 0)
    blf.draw(0, a_txt)
    blf.position(0, xb, ty, 0)
    blf.draw(0, b_txt)
    gpu.state.blend_set('NONE')


# --- the drag -----------------------------------------------------------------------------------------

def hit(context, event):
    """(area, region, bar) of a timeline Range Slider bar under the mouse, or None."""
    window = context.window
    if window is None:
        return None
    for area in window.screen.areas:
        bar = _bars.get(area.as_pointer())
        if bar is None or bar["window"] != window.as_pointer() or area.type != 'DOPESHEET_EDITOR':
            continue
        if area.spaces.active.mode != 'TIMELINE':
            continue
        region = next((r for r in area.regions if r.type == 'HEADER'), None)
        if region is None or region.as_pointer() != bar["region"]:
            continue
        x, y = event.mouse_x - region.x, event.mouse_y - region.y
        if bar["x0"] <= x <= bar["x1"] and bar["y0"] <= y <= bar["y1"] and 0 <= y < region.height:
            return area, region, bar
    return None


class ALLSET_OT_range_bar_drag(bpy.types.Operator):
    """Maya Range Slider: drag the playback range, or one of its ends; double-click toggles the whole
    animation range"""
    bl_idname = "allset.range_bar_drag"
    bl_label = "Range Slider"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def invoke(self, context, event):
        found = hit(context, event)
        if found is None:
            return {'PASS_THROUGH'}
        area, region, bar = found
        scene = context.scene
        if event.value == 'DOUBLE_CLICK':
            toggle_whole(scene)
            area.tag_redraw()
            return {'FINISHED'}
        ps, pe = playback(scene)
        xs, xe = visual_segment(bar, ps, pe, bar.get("handle_w", 18))
        kind = zone(event.mouse_x - region.x, xs, xe, bar.get("handle_w", 18))
        if kind is None:
            return {'PASS_THROUGH'}
        self._kind, self._area, self._x = kind, area, event.mouse_x
        self._old = (scene.use_preview_range, scene.frame_preview_start, scene.frame_preview_end)
        self._range = (ps, pe)
        self._ppf = (bar["x1"] - bar["x0"]) / max(bar["e"] - bar["s"], 1)
        self._bounds = (bar["s"], bar["e"])
        self._moved = False
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        scene = context.scene
        if event.type == 'MOUSEMOVE':
            d = round((event.mouse_x - self._x) / max(self._ppf, 1e-6))
            a, b = drag_range(self._kind, *self._range, d, *self._bounds)
            if (a, b) != playback(scene) or not scene.use_preview_range:
                if d or self._moved:
                    set_playback(scene, a, b)
                    self._moved = True
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return {'FINISHED'} if self._moved else {'CANCELLED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            scene.frame_preview_start, scene.frame_preview_end = self._old[1], self._old[2]
            scene.use_preview_range = self._old[0]
            self._area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


classes = (ALLSET_OT_range_bar_drag,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    from bpy.props import IntProperty
    bpy.types.Scene.allset_playback_start = IntProperty(
        name="Playback Start", description="First frame of the playback range (Maya's Range Slider)",
        min=MIN_FRAME, max=MAX_FRAME, get=_get_playback_start, set=_set_playback_start, options={'HIDDEN'})
    bpy.types.Scene.allset_playback_end = IntProperty(
        name="Playback End", description="Last frame of the playback range (Maya's Range Slider)",
        min=MIN_FRAME, max=MAX_FRAME, get=_get_playback_end, set=_set_playback_end, options={'HIDDEN'})
    _handle.append(bpy.types.SpaceDopeSheetEditor.draw_handler_add(draw, (), 'HEADER', 'POST_PIXEL'))


def unregister():
    while _handle:
        bpy.types.SpaceDopeSheetEditor.draw_handler_remove(_handle.pop(), 'HEADER')
    del bpy.types.Scene.allset_playback_end
    del bpy.types.Scene.allset_playback_start
    _bars.clear()
    _extra.clear()
    _planned.clear()
    _gaps.clear()
    _shapes.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
