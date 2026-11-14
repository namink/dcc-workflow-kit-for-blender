# SPDX-License-Identifier: GPL-3.0-or-later
"""GPU drawing of the marking menu engine and the hotbox.

POST_PIXEL draw handlers per editor type and region type, added once at register.
Maya's menus float over the whole window: the modal operators work in the
coordinates of the region they were invoked in, and every region of that window draws
the same picture moved by its offset from that region (each region clips its own
part), so menus also cover sidebars, toolbars and neighbouring editors. Other
windows / no menu: a single dictionary lookup.
Drawing: ``draw_handler_add`` + ``gpu`` + ``blf``.
"""

import time
import traceback

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from . import engine
from .. import i18n

# The interaction being drawn: {"region": pointer, "window": pointer, "origin": (x, y) of that region
# in the window, "session": Session} or {..., "hotbox": HotboxLayout, "hover": key, ...}; empty = nothing.
ACTIVE = {}

# Editors the menus open in (marking menus, hotbox) ...
SPACES = (bpy.types.SpaceView3D, bpy.types.SpaceOutliner, bpy.types.SpaceGraphEditor,
          bpy.types.SpaceDopeSheetEditor, bpy.types.SpaceNodeEditor, bpy.types.SpaceImageEditor)
# ... and every editor they may cover.
COVER_SPACES = SPACES + tuple(getattr(bpy.types, n) for n in (
    "SpaceProperties", "SpaceNLA", "SpaceSequenceEditor", "SpaceClipEditor", "SpaceTextEditor",
    "SpaceConsole", "SpaceInfo", "SpaceFileBrowser", "SpaceSpreadsheet", "SpacePreferences")
    if hasattr(bpy.types, n))
# 'HUD' = the Adjust Last Operation panel, drawn over the view: without it the RMB list went under it.
REGION_TYPES = ('WINDOW', 'UI', 'TOOLS', 'HEADER', 'TOOL_HEADER', 'CHANNELS', 'FOOTER', 'HUD')

# Maya-style greys and selection blue #5285A6. Menu boxes and the list body: #525252.
BG = (0x52 / 255, 0x52 / 255, 0x52 / 255, 1.0)
DIVIDER = (0x3a / 255, 0x3a / 255, 0x3a / 255, 1.0)
BG_HOVER = (0.32, 0.52, 0.65, 1.0)
EDGE = (0.12, 0.12, 0.12, 1.0)
TEXT = (0.92, 0.92, 0.92, 1.0)
TEXT_OFF = (0.55, 0.55, 0.55, 1.0)
LINE = (0.95, 0.95, 0.95, 0.9)

_handles = []
_shader = None


def ui_scale():
    return bpy.context.preferences.system.ui_scale


def font_size():
    # Menu text: Segoe UI 11 px = Blender's 11 pt
    # widget text at an effective scale of 1.0.
    # blf font 0 is the interface font, so it is Segoe UI when view.font_path_ui points there.
    return max(8, round(11 * ui_scale()))


# Submenu arrow: drawn as a triangle, not the "▸" glyph. A UI font without it (Segoe UI, the Maya Font
# preference) makes blf.dimensions return millions of pixels (the RMB list spanned the view).
ARROW = " ▸"


def _arrow_w():
    return font_size() * 0.9


def measure(text):
    """Drawn width of a menu text; a label is sized as ``_text`` draws it (in the interface language)."""
    text = i18n.core(text)
    blf.size(0, font_size())
    if text.endswith(ARROW):
        return blf.dimensions(0, text[:-len(ARROW)])[0] + _arrow_w()
    return blf.dimensions(0, text)[0]


# While ``extent`` sizes the picture: [x0, y0, x1, y1] of everything the primitives below would draw (in the
# coordinates the menu draws in), and they draw nothing.
_BOUNDS = [None]


def _grow(points, pad):
    b = _BOUNDS[0]
    for x, y in points:
        b[0], b[1] = min(b[0], x - pad), min(b[1], y - pad)
        b[2], b[3] = max(b[2], x + pad), max(b[3], y + pad)


def _sh():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _shader


def _rect(r, color, ox=0.0, oy=0.0):
    x0, y0, x1, y1 = r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy
    if _BOUNDS[0] is not None:
        _grow(((x0, y0), (x1, y1)), 1.0)
        return
    sh = _sh()
    batch = batch_for_shader(sh, 'TRI_FAN', {"pos": ((x0, y0), (x1, y0), (x1, y1), (x0, y1))})
    sh.uniform_float("color", color)
    batch.draw(sh)


def _outline(r, color, ox=0.0, oy=0.0):
    x0, y0, x1, y1 = r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy
    if _BOUNDS[0] is not None:
        _grow(((x0, y0), (x1, y1)), 1.0)
        return
    sh = _sh()
    batch = batch_for_shader(sh, 'LINE_LOOP', {"pos": ((x0, y0), (x1, y0), (x1, y1), (x0, y1))})
    sh.uniform_float("color", color)
    batch.draw(sh)


def _line(points, color, width=1.0):
    if len(points) < 2:
        return
    if _BOUNDS[0] is not None:
        _grow(points, width + 1.0)
        return
    gpu.state.line_width_set(width)
    sh = _sh()
    batch = batch_for_shader(sh, 'LINE_STRIP', {"pos": points})
    sh.uniform_float("color", color)
    batch.draw(sh)
    gpu.state.line_width_set(1.0)


def _text(x, y, s, color):
    if _BOUNDS[0] is not None:
        k = font_size()
        _grow(((x, y - 0.5 * k), (x + measure(s) + 0.5 * k, y + 1.5 * k)), 1.0)
        return
    s = i18n.core(s)
    blf.size(0, font_size())
    arrow = s.endswith(ARROW)
    if arrow:
        s = s[:-len(ARROW)]
    blf.color(0, *color)
    blf.position(0, x, y, 0)
    blf.draw(0, s)
    if arrow:   # a small right-pointing triangle after the text
        k = font_size()
        ax = x + blf.dimensions(0, s)[0] + k * 0.35
        ay = y + k * 0.35
        sh = _sh()
        batch = batch_for_shader(sh, 'TRIS', {"pos": ((ax, ay - k * 0.25), (ax, ay + k * 0.25), (ax + k * 0.3, ay))})
        sh.uniform_float("color", color)
        batch.draw(sh)


def _ring_arrow(rect, color, k, ox, oy):
    """Maya's submenu triangle of a radial box: in the right padding, base 13 px and tip 9 px left of the
    box's right side, 7 px tall, tip on the box's vertical centre."""
    x1 = rect[2] + ox
    yc = (rect[1] + rect[3]) / 2 + oy
    if _BOUNDS[0] is not None:
        _grow(((x1 - 13 * k, yc - 3.5 * k), (x1 - 9 * k, yc + 3.5 * k)), 1.0)
        return
    sh = _sh()
    batch = batch_for_shader(sh, 'TRIS', {"pos": ((x1 - 13 * k, yc - 3.5 * k), (x1 - 13 * k, yc + 3.5 * k),
                                                  (x1 - 9 * k, yc))})
    sh.uniform_float("color", color)
    batch.draw(sh)


def _circle(cx, cy, r, color, segments=24):
    import math
    pts = [(cx + r * math.cos(2 * math.pi * i / segments), cy + r * math.sin(2 * math.pi * i / segments))
           for i in range(segments + 1)]
    _line(pts, color, 1.5)


def _arc(cx, cy, r, progress, color, segments=48):
    """A clockwise arc from twelve o'clock over ``progress`` (0..1) of the circle."""
    import math
    progress = max(0.0, min(1.0, progress))
    if progress <= 0.0:
        return
    count = max(2, int(segments * progress))
    # y is up: from +90 degrees, a falling angle runs clockwise
    pts = [(cx + r * math.cos(math.pi / 2 - 2 * math.pi * progress * i / count),
            cy + r * math.sin(math.pi / 2 - 2 * math.pi * progress * i / count)) for i in range(count + 1)]
    _line(pts, color, 2.5)


# --- marking menu -------------------------------------------------------------------

# On = filled light blue: the earlier selection blue (0.32, 0.52, 0.65) hardly differed from the
# empty box in screenshots.
CHECK = (0.45, 0.72, 0.95, 1.0)


def checked(action):
    """On/off state of a toggle item (None for other items)."""
    if not engine.is_toggle(action):
        return None
    op, props = action
    try:
        if op == "wm.context_toggle":
            return bool(bpy.context.path_resolve(props["data_path"]))
        if op == "allset.prevent_negative_scale":
            from .. import preferences
            return preferences.get(bpy.context).prevent_negative_scale
        if op == "allset.xform_constraint":
            from ..operators import xform_constraint
            return xform_constraint.mode(bpy.context) == props["mode"]
        if op == "allset.symmetry":
            from ..operators import symmetry
            return symmetry.item_state(props["mode"])
        if op == "allset.pivot_option":          # pivot edit menu check boxes
            from ..operators import pivot_menu
            return pivot_menu.option(props["option"])
        if op == "allset.mm_camera_based":        # Camera-Based Selection = select-through off
            from .. import preferences
            return not preferences.get(bpy.context).select_through
        if op == "allset.component_mask":        # Shift+Q check boxes = the mesh select modes
            mask = bpy.context.scene.tool_settings.mesh_select_mode
            return bool(mask[engine.MASK_CHECKS.index(props["kind"])])
        from ..operators import manip
        return manip.option_state(props["option"])
    except (ValueError, KeyError, AttributeError):
        return None

ANCHOR = (0.95, 0.95, 0.95, 0.55)    # the line from a radial submenu to the centre it opened from
RETURN = (0.30, 0.72, 1.0, 1.0)      # that centre's ring and arc while the pointer rests there
ROUTE = (0.72, 0.84, 0.96, 0.92)     # Quick Gestures: a hidden mark's route and its menu names
ROUTE_SHADE = (0.12, 0.22, 0.34, 0.42)
ROUTE_LIVE = (0.34, 0.70, 1.0, 0.98)
ROUTE_DIM = (0.78, 0.86, 0.94, 0.78)
ROUTE_BG = (0.035, 0.055, 0.075, 0.88)
ROUTE_RIM = (0.42, 0.52, 0.62, 0.72)
ROUTE_TEXT = (0.82, 0.88, 0.94, 0.95)


def _draw_route(s):
    """Quick Gestures option, while a mark is hidden: a straight line through the centres of the menus the mark
    passed (the press point, each submenu it entered) to the pointer, a dot and the name at each, and the radial
    item it would pick at the pointer. Not the raw stroke."""
    import math
    points = [tuple(p) for p, _name in s.route] + [tuple(s.pos)]
    _line(points, ROUTE_SHADE, 4.0)
    _line(points, ROUTE, 2.0)
    nodes = [(tuple(p), name) for p, name in s.route]
    item = s.hover[0]
    if item is not None and item.sub is None and item.enabled and item.label:
        nodes.append((tuple(s.pos), item.label))
    merged = []        # a name too near the previous one replaces it
    for point, name in nodes:
        if merged and math.hypot(point[0] - merged[-1][0][0], point[1] - merged[-1][0][1]) < 18.0:
            merged[-1] = (point, name)
        else:
            merged.append((point, name))
    k = ui_scale()
    fs = font_size()
    for i, ((px, py), name) in enumerate(merged):
        last = i == len(merged) - 1
        colour = ROUTE_LIVE if last else ROUTE_DIM
        _circle(px, py, (7.0 if last else 3.5) * k, colour, segments=20)
        _circle(px, py, 1.5 * k, colour, segments=12)
        if not name:
            continue
        pad_x, pad_y = max(5.0, fs * 0.45), max(3.0, fs * 0.24)
        lx = px + 10.0 * k
        ly = py + (8.0 * k if i % 2 == 0 else -fs - 5.0 * k)      # alternate sides off the route line
        box = (lx - pad_x, ly - pad_y, lx + measure(name) + pad_x, ly + fs + pad_y * 0.5)
        _rect(box, ROUTE_BG)
        _outline(box, ROUTE_LIVE if last else ROUTE_RIM)
        _text(lx, ly, name, (1.0, 1.0, 1.0, 1.0) if last else ROUTE_TEXT)
    _circle(*s.pos, 5.0 * k, ROUTE_LIVE, segments=20)


def _draw_anchors(s, now):
    """Submenu Return Ring option, in-place radial submenus: a line back to the centre each opened from and a ring
    there. Resting on that centre goes back to its menu (``engine.Session._dwell_back``): the ring turns blue and
    an arc fills clockwise until it does."""
    resting = s.dwell_progress(now)
    r = s.params.dead * 1.75
    for (px, py), (qx, qy) in s.anchors():
        _line([(px, py), (qx, qy)], ANCHOR, 1.5)
        if resting is not None and resting[0] == (px, py):
            _circle(px, py, r, RETURN, segments=32)
            _arc(px, py, r + s.params.dead * 0.25, resting[1], RETURN)
        else:
            _circle(px, py, r, LINE, segments=32)


def _near_centre(s, cx, cy):
    """Submenu Return Ring option: the line from the centre to the pointer shows only near the menu's centre
    or, in a radial submenu, near it or the centre it opened from."""
    import math
    x, y = s.pos
    anchors = s.anchors()
    if not anchors:
        return math.hypot(x - cx, y - cy) <= max(32.0, s.params.dead * 2.0)
    reach = max(24.0, s.params.dead * 2.5)
    return any(math.hypot(x - px, y - py) <= reach or math.hypot(x - qx, y - qy) <= reach
               for (px, py), (qx, qy) in anchors)


def draw_session(s, now, shown=None):
    """``shown``: draw the menu (True) or a hidden mark's stroke / route (False) whatever ``s.visible`` says."""
    if not (s.visible(now) if shown is None else shown):
        if s.params.quick_gestures:
            _draw_route(s)
        else:
            _line(s.trail, LINE, 2.0)  # a quick mark: only the stroke
        return
    layers = s.layers()   # a list row's open cascade is drawn over the menu it hangs from
    _lay, (cx, cy), _hover = layers[0]
    guides = s.params.submenu_guides
    if guides:
        _draw_anchors(s, now)
    _circle(cx, cy, s.params.dead, LINE)
    if not guides or _near_centre(s, cx, cy):
        _line([(cx, cy), s.pos], LINE, 1.5)
    for lay, (cx, cy), hover in layers:
        _draw_layout(lay, cx, cy, hover)


def _draw_layout(lay, cx, cy, hover):
    hover, hover_opt = hover
    pad = lay.params.pad
    _draw_list_body(lay, cx, cy)
    for it in lay.items:
        on = it is hover
        if it.kind == "radial" or (on and not hover_opt and it.enabled):
            _rect(it.rect, BG_HOVER if on and not hover_opt and it.enabled else BG, cx, cy)
        color = TEXT if it.enabled else TEXT_OFF
        radial = it.kind == "radial"
        if radial:
            # the 1 px border on the box's outer pixels: a line on the rect's sides drew a box 1 px too tall / wide
            # (22 px instead of 21)
            r = it.rect
            _outline((r[0] + 0.5, r[1] + 0.5, r[2] - 0.5, r[3] - 0.5), EDGE, cx, cy)
            text = engine.Layout.ring_text(it.label, it.action)
            if engine.Layout.has_arrow(it.action):
                _ring_arrow(it.rect, color, lay.params.ring_pad / 25.0, cx, cy)
        else:
            text = engine.Layout._text(it.label, it.action)
        tpad = lay.params.ring_pad if radial else pad
        _text(cx + it.rect[0] + tpad, cy + it.rect[1] + (it.rect[3] - it.rect[1]) * 0.3, text, color)
        state = checked(it.action)
        if state is not None:
            right = it.opt_rect[0] if it.opt_rect else it.rect[2]
            size = (it.rect[3] - it.rect[1]) * 0.42
            x1 = right - tpad
            y0 = it.rect[1] + (it.rect[3] - it.rect[1] - size) / 2
            box = (x1 - size, y0, x1, y0 + size)
            _outline(box, TEXT if it.enabled else TEXT_OFF, cx, cy)
            if state:
                _rect((box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1), CHECK, cx, cy)
        if it.opt_rect:
            if on and hover_opt:
                _rect(it.opt_rect, BG_HOVER, cx, cy)
            inner = (it.opt_rect[0] + 4, it.opt_rect[1] + 4, it.opt_rect[2] - 4, it.opt_rect[3] - 4)
            _outline(inner, TEXT if it.enabled else TEXT_OFF, cx, cy)


def _draw_list_body(lay, cx, cy):
    """The list under the ring as one menu body per column with divider lines (like Maya's)."""
    columns = {}
    for it in lay.items:
        if it.kind == "list":
            columns.setdefault(round(it.rect[0], 3), []).append(it)
    for rows in columns.values():
        body = (rows[0].rect[0], min(it.rect[1] for it in rows), rows[0].rect[2], max(it.rect[3] for it in rows))
        _rect(body, BG, cx, cy)
        _outline(body, EDGE, cx, cy)
        for a, b in zip(rows, rows[1:]):
            # a Maya divider sits between the rows (their list indices skip it); a gap where a row only stepped over an
            # area border gets no line
            if isinstance(a.key, int) and isinstance(b.key, int) and b.key - a.key > 1:
                y = (a.rect[1] + b.rect[3]) / 2 + cy
                _line([(body[0] + cx + 4, y), (body[2] + cx - 4, y)], DIVIDER, 1.0)


# --- hotbox ---------------------------------------------------------------------------

# Maya hotbox: no dimming; each row is one translucent strip (#444444 at 70 % = #4c4c4c over
# a #5c5c5c view), the hovered menu name lights up, the centre box
# shows "Maya", four short white diagonal lines mark the zones (no zone names).
ROW_BG = (0x44 / 255, 0x44 / 255, 0x44 / 255, 0.7)
ROW_TEXT = (0xbb / 255, 0xbb / 255, 0xbb / 255, 1.0)
ZONE_LINE = (0.95, 0.95, 0.95, 0.9)


def draw_hotbox(state, region, own=True):
    lay = state["hotbox"]
    cx, cy = lay.center
    p = lay.params
    for band in lay.bands:
        _rect(band, ROW_BG)
    for rect, key, label in lay.labels:
        hover = key == state.get("hover")
        if hover:
            _rect(rect, BG_HOVER)
        _text(rect[0] + p.pad, rect[1] + (rect[3] - rect[1]) * 0.3, label, TEXT if hover else ROW_TEXT)
    _rect(lay.center_rect, ROW_BG)
    title = lay.title
    w = measure(title)
    r = lay.center_rect
    _text(cx - w / 2, r[1] + (r[3] - r[1]) * 0.3, title, ROW_TEXT)
    for a, b in lay.zone_lines:
        _line([a, b], ZONE_LINE, 1.0)


def _overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


# --- handler -----------------------------------------------------------------------------

_window = {"ptr": None}     # the last window drawn into (redraw after ACTIVE is cleared)


def activate(window, region, **state):
    """Start drawing ``state`` (session / hotbox ...) for ``region`` over all of ``window``."""
    ACTIVE.clear()
    _LAST[0] = None
    ACTIVE.update(state, region=region.as_pointer(), window=window.as_pointer(), origin=(region.x, region.y))
    _window["ptr"] = window.as_pointer()
    _draw_last()


def _draw_last():
    """Move the handlers to the end of every region's draw list (#56): Blender draws a region's
    POST_PIXEL handlers in the order they were added, and kit handlers registered after ``marking`` (Time Slider
    numbers / key ticks, Range Slider, shelf, Outliner set rows) drew over the open menu
    (Time Slider frame numbers on the list)."""
    if _handles:
        unregister_handlers()
        register_handlers()


# Area borders (#56): Blender draws them after every region (ED_screen_draw_edges), so no POST_PIXEL
# handler can draw over them. In the Maya Workflow Kit layout at UI scale 1.0 and 1.25
# areas are 3 px apart and a 2 px rim is drawn over each area's
# edge at both scales (the border width preference is in pixels, it does not follow the UI scale). +1 px for the
# rim's anti-aliasing.
BORDER_RIM = 2
AREA_GAP_MAX = 8


def window_edges(window, region):
    """Area border bands of ``window`` in ``region`` pixels: (x0, y0, x1, y1) rectangles, the gaps between areas
    and the rims around them, including the window's outer edge (engine.fit_ring ``edges``)."""
    areas = list(window.screen.areas) if window and window.screen else []
    if not areas:
        return ()
    px = bpy.context.preferences.system.pixel_size
    m = BORDER_RIM * px + 1
    gap = AREA_GAP_MAX * px
    rx, ry = region.x, region.y
    bands = []
    for a in areas:
        ax1, ay1 = a.x + a.width, a.y + a.height
        for b in areas:
            if b is a:
                continue
            bx1, by1 = b.x + b.width, b.y + b.height
            if 0 <= b.y - ay1 <= gap:                  # b right above a
                lo, hi = max(a.x, b.x), min(ax1, bx1)
                if hi > lo:
                    bands.append((lo - m, ay1 - m, hi + m, b.y + m))
            if 0 <= b.x - ax1 <= gap:                  # b right of a
                lo, hi = max(a.y, b.y), min(ay1, by1)
                if hi > lo:
                    bands.append((ax1 - m, lo - m, b.x + m, hi + m))
    # the window's outer edge has the rim too
    x0, y0 = min(a.x for a in areas), min(a.y for a in areas)
    x1, y1 = max(a.x + a.width for a in areas), max(a.y + a.height for a in areas)
    bands += [(x0, y0, x1, y0 + m), (x0, y1 - m, x1, y1), (x0, y0, x0 + m, y1), (x1 - m, y0, x1, y1)]
    return tuple((b[0] - rx, b[1] - ry, b[2] - rx, b[3] - ry) for b in _merge(bands))


def _merge(bands):
    """Join bands on one line whose ends meet (the pieces of one border between several areas)."""
    out = []
    for b in sorted(set(bands)):
        horizontal = b[2] - b[0] >= b[3] - b[1]
        for i, o in enumerate(out):
            if horizontal and (o[1], o[3]) == (b[1], b[3]) and o[2] - o[0] >= o[3] - o[1] and b[0] <= o[2]:
                out[i] = (min(o[0], b[0]), o[1], max(o[2], b[2]), o[3])
                break
            if not horizontal and (o[0], o[2]) == (b[0], b[2]) and o[2] - o[0] < o[3] - o[1] and b[1] <= o[3]:
                out[i] = (o[0], min(o[1], b[1]), o[2], max(o[3], b[3]))
                break
        else:
            out.append(b)
    return out


def window_bounds(window, region):
    """The window's editors (not its global top bar / status bar) in ``region`` pixels."""
    areas = window.screen.areas if window and window.screen else ()
    if not areas:
        return (0, 0, region.width, region.height)
    x0 = min(a.x for a in areas)
    y0 = min(a.y for a in areas)
    x1 = max(a.x + a.width for a in areas)
    y1 = max(a.y + a.height for a in areas)
    return (x0 - region.x, y0 - region.y, x1 - region.x, y1 - region.y)


def menu_up():
    """True while a marking menu or the hotbox is drawn (#104): kit overlays that Maya's hotbox covers
    (in-view messages, the In-View Editor box) skip their draw then."""
    return bool(ACTIVE)


_LAST = [None]      # window-pixel bounds of the picture at the last ``redraw`` (None: unknown)
EXTENT_PAD = 4.0    # px around the picture's bounds (anti-aliased edges)


def extent():
    """Window-pixel bounds (x0, y0, x1, y1) of what the open menu draws now: the same drawing code run without
    drawing. A marking menu counts its menu and a hidden mark's stroke / route both (it can turn visible before the
    next redraw). None: nothing open or nothing drawn."""
    if not ACTIVE or "origin" not in ACTIVE:
        return None
    inf = float("inf")
    _BOUNDS[0] = [inf, inf, -inf, -inf]
    try:
        if "hotbox" in ACTIVE:
            draw_hotbox(ACTIVE, None)
        if "session" in ACTIVE:
            now = time.monotonic()
            draw_session(ACTIVE["session"], now, shown=True)
            draw_session(ACTIVE["session"], now, shown=False)
        b = _BOUNDS[0]
    finally:
        _BOUNDS[0] = None
    if b[0] > b[2]:
        return None
    ox, oy = ACTIVE["origin"]
    pad = EXTENT_PAD * ui_scale()
    return (b[0] + ox - pad, b[1] + oy - pad, b[2] + ox + pad, b[3] + oy + pad)


def redraw():
    """Redraw the editors of the menu's window that the picture covers now or covered at the last redraw (the
    picture spans regions; an editor it never reaches keeps its pixels, every editor when that isn't known)."""
    ptr = ACTIVE.get("window", _window["ptr"])
    try:
        now = extent()
    except Exception:         # never let a sizing error keep the menu from drawing
        traceback.print_exc()
        now = None
    boxes = [b for b in (now, _LAST[0]) if b is not None]
    everything = now is None and ACTIVE or not boxes
    _LAST[0] = now
    for window in bpy.context.window_manager.windows:
        if window.as_pointer() == ptr and window.screen:
            for area in window.screen.areas:
                rect = (area.x, area.y, area.x + area.width, area.y + area.height)
                if everything or any(_overlaps(rect, b) for b in boxes):
                    area.tag_redraw()


def _callback():
    if not ACTIVE:
        return
    context = bpy.context
    region, window = context.region, context.window
    if region is None or window is None or window.as_pointer() != ACTIVE.get("window"):
        return
    ox, oy = ACTIVE["origin"]
    own = region.as_pointer() == ACTIVE.get("region")
    try:
        gpu.state.blend_set('ALPHA')
        gpu.matrix.push()
        gpu.matrix.translate((ox - region.x, oy - region.y))
        if "hotbox" in ACTIVE:
            draw_hotbox(ACTIVE, region, own)
        if "session" in ACTIVE:
            draw_session(ACTIVE["session"], time.monotonic())
    except Exception:  # never let a draw error repeat every frame
        traceback.print_exc()
        ACTIVE.clear()
    finally:
        gpu.matrix.pop()
        gpu.state.blend_set('NONE')


def register_handlers():
    for space in COVER_SPACES:
        for region_type in REGION_TYPES:
            try:
                _handles.append((space, region_type,
                                 space.draw_handler_add(_callback, (), region_type, 'POST_PIXEL')))
            except (TypeError, ValueError, RuntimeError):
                pass   # this editor has no such region


def unregister_handlers():
    while _handles:
        space, region_type, handle = _handles.pop()
        space.draw_handler_remove(handle, region_type)


def register():
    register_handlers()


def unregister():
    ACTIVE.clear()
    unregister_handlers()
