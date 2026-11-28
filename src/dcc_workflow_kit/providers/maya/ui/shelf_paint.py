# SPDX-License-Identifier: GPL-3.0-or-later
"""GPU drawing for the shelf row: cached shaders and batches (``_draw_rect``, ``_triangle``; their calls go through
``draw_replay.call``, so a redraw while a window moves draws them again as they were), colours from the
user's Image Editor header theme, the tab strip (``tab_rects``, ``_draw_tabs``, gear glyph) and the dimmed tab-row
header (``draw_tab_row``). ``_hover`` / ``_tab_rects`` are shared with the gizmos in shelf.py."""

import bpy

from .. import compat
from .draw_replay import call
from .shelf_strip import is_shelf_row, TAB_PX, TAB_LEFT_PX, TAB_PAD_PX, TAB_FONT_PX
from .shelf_store import shelves, current


_SHELF_SHADERS = {}

def _shelf_shader(name):
    """Reuse built-in shaders across shelf redraws instead of resolving them for every icon/rectangle."""
    shader = _SHELF_SHADERS.get(name)
    if shader is None:
        import gpu
        shader = _SHELF_SHADERS[name] = gpu.shader.from_builtin(name)
    return shader

_SHELF_BATCHES = {}     # (shader, primitive, points) -> GPU batch: the row redraws the same rectangles every time


def _shelf_batch(name, prim, coords, tex_coords=None):
    """The GPU batch of ``coords`` for built-in shader ``name``, made once and drawn again on later redraws (the
    row redraws on every frame and selection change with the same shapes)."""
    key = (name, prim, coords)
    batch = _SHELF_BATCHES.get(key)
    if batch is None:
        from gpu_extras.batch import batch_for_shader
        attrs = {"pos": coords} if tex_coords is None else {"pos": coords, "texCoord": tex_coords}
        batch = batch_for_shader(_shelf_shader(name), prim, attrs)
        if len(_SHELF_BATCHES) > 1024:
            _SHELF_BATCHES.clear()
        _SHELF_BATCHES[key] = batch
    return batch


_TEX_COORDS = ((0, 0), (1, 0), (1, 1), (0, 1))


def _draw_rect(x, y, w, h, colour, texture=None):
    """A rectangle in region pixels (POST_PIXEL draw handler)."""
    import gpu
    coords = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
    call(gpu.state.blend_set, 'ALPHA')
    if texture is None:
        sh = _shelf_shader('UNIFORM_COLOR')
        batch = _shelf_batch('UNIFORM_COLOR', 'TRI_FAN', coords)
        call(sh.uniform_float, "color", colour)
    else:
        sh = _shelf_shader(compat.LINEAR_IMAGE_SHADER)
        batch = _shelf_batch(compat.LINEAR_IMAGE_SHADER, 'TRI_FAN', coords, _TEX_COORDS)
        call(sh.uniform_sampler, "image", texture)
    call(batch.draw, sh)
    call(gpu.state.blend_set, 'NONE')


def _theme_colour(context):
    """The shelf row background = the user's Image Editor header colour (read only; the kit ships no
    theme, #40), so the shelf sits in the same colour as the Status Line row in any theme."""
    c = context.preferences.themes[0].image_editor.space.header
    return (c[0], c[1], c[2], 1.0)


def _luma(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _text_colours(context):
    """(current tab text, other tab text, glyph) from the user's header text colours: Maya's light current tab and
    dimmer other tabs, readable on a dark or a light header."""
    sp = context.preferences.themes[0].image_editor.space
    base = _theme_colour(context)
    text, hi = compat.header_text_colours(sp)
    other = tuple(t * 0.7 + b * 0.3 for t, b in zip(text, base))
    return (*hi, 1.0), (*other, 1.0), (*text, 1.0)


def _separator_colours(base):
    """Maya's raised vertical rule (dark line + light line) relative to the row colour."""
    dark = tuple(c * 0.55 for c in base[:3])
    light = tuple(c + (1.0 - c) * 0.18 for c in base[:3])
    return (*dark, 1.0), (*light, 1.0)


CHECKED_COLOUR = (0.32, 0.52, 0.65, 1.0)   # Maya's highlight blue (#5285A6)


def _checked(context, record):
    """A user button's optional "checked" kit preference (``"select_through"``, or ``"not select_through"``; a
    leading ``prefs.`` is accepted) is on: frame it like Maya's checked shelf icons. Unknown names count as off."""
    name = (record.get("checked") if record else None) or ""
    negate = name.startswith("not ")
    name = name.removeprefix("not ").strip().removeprefix("prefs.")
    if not name.isidentifier() or name.startswith("_"):
        return False
    from .. import preferences
    value = getattr(preferences.get(context), name, None)
    return value is not None and bool(value) != negate


def _hover_colour(base, mapped):
    """A hover box that shows on dark and light rows: white over dark, black over light."""
    ink = 1.0 if _luma(base) < 0.5 else 0.0
    return (ink, ink, ink, (0.18 if mapped else 0.08) if ink else (0.12 if mapped else 0.05))


# The shelf tab row (and inactive tabs, #373737) is darker than the icon row, the active tab and the Status Line
# (#444444), but both rows share the Image Editor header colour. The tab row's header is dimmed by this black
# overlay (ratio #444444 -> #373737, applied to whatever header colour the user's theme has).
TAB_DIM = 1.0 - 0x37 / 0x44


def draw_tab_row():
    """POST_PIXEL of image editor headers: dim the shelf tab row (``TAB_DIM``)."""
    context = bpy.context
    if not is_shelf_row(context.space_data):
        return
    region = context.region
    _draw_rect(0, 0, region.width, region.height, (0.0, 0.0, 0.0, TAB_DIM))


_hover = {}   # region pointer -> slot under the mouse (set by the gizmos' test_select)
_tab_rects = {}   # region pointer -> [(x0, y0, x1, y1, action)] of the tab strip, drawn last ("menu", "gear", shelf id)


def tab_rects(context, region, tabs=None):
    """Rects of the shelf menu glyph, the editor gear and the tabs in region pixels, left to right (``tabs``: the
    ``shelves()`` list already read)."""
    import blf
    s = context.preferences.system.ui_scale or 1.0
    h = region.height
    th = round(TAB_PX * s)
    out = [(round(14 * s), h - th, round(32 * s), h, "menu"),
           (round(14 * s), round(4 * s), round(32 * s), h - th - round(4 * s), "gear")]
    blf.size(0, TAB_FONT_PX * s)
    x = TAB_LEFT_PX * s
    for shelf_id, label in (shelves() if tabs is None else tabs):
        w = blf.dimensions(0, label)[0] + 2 * TAB_PAD_PX * s
        out.append((round(x), h - th, round(x + w), h, shelf_id))
        x += w + round(2 * s)
    return out


def _text(x, y, text, colour, size):
    import blf
    call(blf.size, 0, size)
    call(blf.color, 0, *colour)
    call(blf.position, 0, x, y, 0)
    call(blf.draw, 0, text)


def _draw_tabs(context, region, base, cur=None):
    """The shelf tab strip: #373737 strip, flat tabs, the current one
    in the row colour with light text, the others dim; the shelf menu glyph left of the tabs, the shelf editor gear
    left of the icons."""
    s = context.preferences.system.ui_scale or 1.0
    h = region.height
    th = round(TAB_PX * s)
    dim = (base[0] * (1 - TAB_DIM), base[1] * (1 - TAB_DIM), base[2] * (1 - TAB_DIM), 1.0)
    _draw_rect(0, h - th, region.width, th, dim)
    tabs = shelves()
    rects = _tab_rects[region.as_pointer()] = tab_rects(context, region, tabs)
    cur = current(context) if cur is None else cur
    labels = dict(tabs)
    hover = _hover.get(region.as_pointer())
    text_on, text_off, grey = _text_colours(context)
    for x0, y0, x1, y1, action in rects:
        if action == "menu":
            for k in range(3):
                _draw_rect(x0 + 2 * s, y0 + (5 + 4 * k) * s, (x1 - x0) - 4 * s, max(1.0, 1.5 * s), grey)
            continue
        if action == "gear":
            cy = (y0 + y1) / 2
            _draw_rect(x0 + 2 * s, cy - 6 * s, (x1 - x0) - 4 * s, 12 * s, None,
                       shelf_icons_gear())
            continue
        on = action == cur
        if on:
            _draw_rect(x0, y0, x1 - x0, y1 - y0 - s, base)
        elif hover == ("tab", action):
            _draw_rect(x0, y0, x1 - x0, y1 - y0 - s, _hover_colour(dim, False))
        _text(x0 + TAB_PAD_PX * s, y0 + 5 * s, labels.get(action, action),
              text_on if on else text_off, TAB_FONT_PX * s)


_gear_tex = []


def shelf_icons_gear():
    if not _gear_tex:
        import gpu
        import numpy as np
        from . import status_icons
        cv = status_icons.Canvas(32)
        status_icons.gear(cv, 0.5, 0.5, 0.40, status_icons.GREY)
        px = cv.pixels().reshape(32, 32, 4).copy()
        rgb = px[..., :3]
        px[..., :3] = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        buf = gpu.types.Buffer('FLOAT', 32 * 32 * 4, px.ravel().tolist())
        _gear_tex.append(gpu.types.GPUTexture((32, 32), format='RGBA32F', data=buf))
    return _gear_tex[0]


def _triangle(cx, cy, half, up, colour):
    import gpu
    pts = ((cx - half, cy - half / 2), (cx + half, cy - half / 2), (cx, cy + half / 2)) if up else \
        ((cx - half, cy + half / 2), (cx + half, cy + half / 2), (cx, cy - half / 2))
    sh = _shelf_shader('UNIFORM_COLOR')
    batch = _shelf_batch('UNIFORM_COLOR', 'TRIS', pts)
    call(gpu.state.blend_set, 'ALPHA')
    call(sh.uniform_float, "color", colour)
    call(batch.draw, sh)
    call(gpu.state.blend_set, 'NONE')
