# SPDX-License-Identifier: GPL-3.0-or-later
"""Paints Maya's Time Slider ruler over the Timeline in the kit layout: background, ticks and frame labels at the
smallest step whose labels fit (``tick_step``), the current-time block, the bookmark strip and the Blue Pencil frame
marks. Shares the row bands (``_rows``) and the cached triangle batches (``_tris_batch``) with the key ticks drawn by
``time_slider``.
"""

from .draw_replay import call
from .time_slider_view import playback_range


# --- Maya ruler -------------------------------------------
# The Maya Workflow Kit layout's Time Slider is painted over Blender's timeline drawing: a dark background, one 2 px
# tick + label per step (the smallest step whose spacing fits the labels, like Maya), the bottom band and the
# translucent current-time block with its white frame number. At UI scale 1.0 (a 32 px tall ruler): rows 1-8 labels
# #757575, ticks rows 13-27 #7c7c7c, rows 29-31 #373737, background #2b2b2b, current time = white at 18.4 % over the
# frame's cell, its number white in rows 16-23.
# Blender draws its own current-frame box in the region overlay after every Python handler (a full-region
# POST_PIXEL fill hides everything else of Blender's) and no RNA / theme-free switch hides it, so that box stays on
# top.
MAYA_RULER_H = 32.0
RULER_BG = (0x2b / 255, 0x2b / 255, 0x2b / 255, 1.0)
RULER_BAND = (0x37 / 255, 0x37 / 255, 0x37 / 255, 1.0)
RULER_TICK = (0x7c / 255, 0x7c / 255, 0x7c / 255, 1.0)
RULER_LABEL = (0x75 / 255, 0x75 / 255, 0x75 / 255, 1.0)
# the current-time block is #525252 over the #2b2b2b ruler = white at (0x52 - 0x2b) / (0xff - 0x2b) = 18.4 %
RULER_CURRENT = (1.0, 1.0, 1.0, (0x52 - 0x2b) / (0xff - 0x2b))
RULER_CURRENT_LABEL = (1.0, 1.0, 1.0, 1.0)
# (top row, bottom row) of the 32 px ruler. With Time Slider bookmarks
# (kit: timeline markers, operators/bookmarks.py) the ruler gets a strip on top and moves labels / ticks down:
# strip #454545 rows 0-8, each bookmark's colour at 80 % over
# it in rows 0-4 with a solid 1 px line at both ends over the strip height.
ROWS = {"label": (1, 8), "tick": (13, 27), "current_label": (16, 23), "band": (29, 31)}
ROWS_BOOKMARKS = {"label": (11, 18), "tick": (23, 27), "current_label": (19, 26), "band": (29, 31),
                  "strip": (0, 8), "bookmark": (0, 4)}
BOOKMARK_STRIP = (0x45 / 255, 0x45 / 255, 0x45 / 255, 1.0)


def _themed(color, field):
    """A ruler colour moved with the Blender theme's Dope Sheet / Timeline colours (ui/theme_follow.py)."""
    from . import theme_follow
    return theme_follow.follow(color, "dopesheet_editor", field)


TICK_PX = 2.0
# Eight-pixel label row in the 32 px ruler, converted to BLF size.
RULER_FONT_SIZE = 8.0 / 0.72
NICE_STEPS = tuple(m * 10 ** e for e in range(8) for m in (1, 2, 5))


# Cases (widget px, first, last frame) where this model picks another step than Maya (tests/test_step186_time_slider.py;
# the default 1-120 and the short ranges match): Maya's threshold also moves with the widget width and the step, and
# it uses steps of 4 / 400 / 4000 with wide labels. "max(a, b x digits)" thresholds with 1-2-4 steps drew 1-120 every
# 4 frames: not taken.
STEP_MATCHES = 32
STEP_DEVIATIONS = ((1292, 1, 10000), (692, 1, 120), (1592, 1, 120), (1592, 1, 60), (1292, 1, 215), (1292, 1, 230),
                   (1292, 1, 250), (1292, 1001, 1100), (1292, 1, 100000), (692, 1, 130), (692, 1, 110))


def label_digits(frame):
    return len(str(abs(int(frame)))) + (1 if frame < 0 else 0)


def label_need_px(digits):
    """Spacing (px at UI scale 1) between two labels of ``digits`` characters (at a 1292 px wide
    ruler: <= 3 digits fit at 25.6 px but not 24.7, 4 digits need more than 25.6 and fit at 32, 5 digits
    need more than 32)."""
    return max(25.0, 7.0 * digits + 3.0)


def _multiples(step, lo, hi):
    import math
    first = math.ceil(lo / step) * step
    return range(int(first), int(hi) + 1, int(step))


def tick_step(start, end, px_per_frame, scale=1.0):
    """Maya Time Slider step (frames between ticks / labels) for the playback range start..end shown at
    ``px_per_frame``: the smallest of 1, 2, 5, 10, 20, 50 ... whose spacing fits the widest label below the end."""
    for step in NICE_STEPS:
        labels = _multiples(step, start, max(start, end - 1))
        widest = max((label_digits(f) for f in (labels[0], labels[-1])), default=1) if len(labels) else 1
        if step * px_per_frame >= label_need_px(widest) * scale:
            return step
    return NICE_STEPS[-1]


def ruler_ticks(step, lo, hi):
    """Frames with a tick and a label in the visible frame range lo..hi."""
    return list(_multiples(step, lo - 1, hi + 1))


# A taller Time Slider (Maya 2026 behaviour, #190): the frame numbers stay at the top in
# their size, the current frame number stays at the bottom, and the ticks keep their bottom end and normal length
# until half the room between the numbers and that end (less this many px) is longer; then they take that half.
TICK_HALF_PAD = 2.33


def label_font_size(h, scale=1.0):
    """BLF size of the frame numbers in a ruler ``h`` px tall: the UI-scaled size, smaller in a ruler shorter than
    Maya's at this scale, like its rows (``_rows``), so the numbers never stand out of the ruler (#292)."""
    return RULER_FONT_SIZE * min(h / MAYA_RULER_H, scale)


def _rows(name, h, rows=None, scale=1.0):
    """(y0, y1) region rows (bottom-up) of a ruler row band at region height ``h``, UI-scaled: the label rows keep
    their place under the top edge, the band and the current frame number theirs above the bottom edge, and the
    ticks grow Maya's way (``TICK_HALF_PAD``)."""
    rows = rows or ROWS
    top, bottom = rows[name]
    k = min(h / MAYA_RULER_H, scale)
    if name == "tick":
        y0 = (MAYA_RULER_H - bottom - 1) * k                     # the bottom end, above the band
        normal = (bottom + 1 - top) * k
        label_low = h - (rows["label"][1] + 1) * k              # the frame numbers' lowest row
        half = (label_low - y0) / 2 - TICK_HALF_PAD * k
        return y0, y0 + max(normal, half)
    if name in ("band", "current_label"):
        return (MAYA_RULER_H - bottom - 1) * k, (MAYA_RULER_H - top) * k
    return h - (bottom + 1) * k, h - top * k


_TRIS = {}      # triangle points -> their GPU batch: the ruler and the key ticks redraw the same shapes every frame


def _tris_batch(shader, tris):
    """The GPU batch of the triangle list ``tris`` (``UNIFORM_COLOR``), made once and drawn again while the same
    shapes are drawn (the Time Slider redraws on every frame change)."""
    key = tuple(tris)
    batch = _TRIS.get(key)
    if batch is None:
        from gpu_extras.batch import batch_for_shader
        batch = batch_for_shader(shader, 'TRIS', {"pos": tris})
        if len(_TRIS) > 256:
            _TRIS.clear()
        _TRIS[key] = batch
    return batch


def _draw_ruler(context, region):
    import blf
    import gpu
    scene = context.scene
    s = context.preferences.system.ui_scale or 1.0
    w, h = region.width, region.height
    v2d = region.view2d

    def x_of(f):
        return v2d.view_to_region(f, 0, clip=False)[0]
    pxf = x_of(1.0) - x_of(0.0)
    if pxf <= 0:
        return
    start, end = playback_range(scene)
    step = tick_step(start, end, pxf, s)
    lo, hi = v2d.region_to_view(0, 0)[0], v2d.region_to_view(w, 0)[0]
    frames = ruler_ticks(step, lo, hi)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')

    def rects(rs, colour):
        tris = []
        for x0, y0, x1, y1 in rs:
            tris += [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]
        if tris:
            call(shader.uniform_float, "color", colour)
            call(_tris_batch(shader, tris).draw, shader)
    from ..operators import bookmarks
    marks = bookmarks.shown(context)
    rows = ROWS_BOOKMARKS if marks else ROWS
    call(gpu.state.blend_set, 'ALPHA')
    rects([(0, 0, w, h)], _themed(RULER_BG, "back"))
    b0, b1 = _rows("band", h, rows, s)
    rects([(0, b0, w, b1)], _themed(RULER_BAND, "back"))
    if marks:
        s0, s1 = _rows("strip", h, rows, s)
        rects([(0, s0, w, s1)], _themed(BOOKMARK_STRIP, "back"))
        m0, m1 = _rows("bookmark", h, rows, s)
        for m in marks:      # each bookmark in its own colour, later starts over earlier ones
            a, b = bookmarks.bookmark_range(scene, m)
            x0, x1 = round(x_of(a - 0.5)), round(x_of(b + 0.5))
            rgb = bookmarks.color(m)
            rects([(x0, m0, x1, m1)], (*rgb, 0.8))
            edge = max(1.0, round(s))      # a line down the strip at both ends, like Maya
            rects([(x0, s0, x0 + edge, s1), (x1 - edge, s0, x1, s1)], (*rgb, 1.0))
    tw = max(1.0, round(TICK_PX * s))
    t0, t1 = _rows("tick", h, rows, s)
    lefts = {f: round(x_of(f - 0.5)) for f in frames}
    rects([(x, t0, x + tw, t1) for x in lefts.values()], _themed(RULER_TICK, "text"))
    cur = scene.frame_current
    cx0, cx1 = x_of(cur - 0.5), x_of(cur + 0.5)
    rects([(round(cx0), 0, max(round(cx0) + 1, round(cx1)), h)], _themed(RULER_CURRENT, "text"))
    # labels: 2 px + a fifth of a frame right of the tick
    l0, _l1 = _rows("label", h, rows, s)
    # The same UI-scaled font is used for the current-frame number.
    call(blf.size, 0, label_font_size(h, s))
    off = 2 * s + 0.2 * pxf
    call(blf.color, 0, *_themed(RULER_LABEL, "text"))
    for f, x in lefts.items():
        call(blf.position, 0, x + off, l0, 0)
        call(blf.draw, 0, str(f))
    c0, _c1 = _rows("current_label", h, rows, s)
    call(blf.color, 0, *_themed(RULER_CURRENT_LABEL, "text"))
    call(blf.position, 0, round(cx0) + off, c0, 0)
    call(blf.draw, 0, str(cur))
    call(gpu.state.blend_set, 'NONE')


def blue_pencil_marks(region, frames, y0, scale):
    """Triangles (x, y) of Maya's Blue Pencil frame marks: one per frame, its upright edge ``MARK_GAP`` right of the
    frame's tick, standing on ``y0`` (the ticks' bottom end)."""
    from . import blue_pencil as bp
    w, h, gap = bp.MARK_W * scale, bp.MARK_H * scale, bp.MARK_GAP * scale
    tris = []
    for f in frames:
        x = round(region.view2d.view_to_region(f - 0.5, 0, clip=False)[0]) + gap
        if x + w < 0 or x > region.width:
            continue
        tris += [(x, y0), (x + w, y0), (x, y0 + h)]
    return tris


def _draw_blue_pencil(context, region):
    """Maya Time Slider: a light blue triangle on every Blue Pencil (annotation) frame (ui/blue_pencil.py)."""
    from . import blue_pencil as bp
    frames = bp.frame_numbers(context.scene)
    if not frames:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    from ..operators import bookmarks
    s = context.preferences.system.ui_scale or 1.0
    rows = ROWS_BOOKMARKS if bookmarks.shown(context) else ROWS
    y0 = _rows("tick", region.height, rows, s)[0]
    k = min(region.height / MAYA_RULER_H, s)
    tris = blue_pencil_marks(region, frames, y0, k)
    if not tris:
        return
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    call(shader.uniform_float, "color", bp.FRAME_RGB)
    call(batch_for_shader(shader, 'TRIS', {"pos": tris}).draw, shader)
