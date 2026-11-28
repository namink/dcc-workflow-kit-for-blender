# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the kit tree's rows sit and the shapes drawn in them: row height (``unit``), scroll position per Outliner
(``SCROLL``, ``first_row``; the sideways pan ``SCROLL_X``, ``shift_x``), the search row above the rows (``top``), the
row under a region y (``row_index_at``) and its rectangle (``row_rect``), the scrollbar and the restriction columns
(``scrollbar``, ``eye_x``, ``column_xs``), the node icons and expand arrows added to the draw batches (``_icon``,
``_triangle``) and Blender's column icons (``restrict_texture``, ``_draw_restrict``). The draw itself:
outliner_tree._draw.
"""

import math

import bpy

from .draw_replay import call

SCROLL = {}               # area pointer -> first shown row
SCROLL_X = {}             # area pointer -> pixels the rows are panned left (Alt+middle-drag, #365)


# --- geometry ------------------------------------------------------------------------------------------------------

def unit(prefs=None):
    """Blender's Outliner row height UI_UNIT_Y in pixels."""
    system = (prefs or bpy.context.preferences).system
    return int(int(18.0 * system.ui_scale + 0.5) + 2 * system.pixel_size)


def _font_size(prefs):
    styles = prefs.ui_styles
    points = getattr(styles[0].widget, "points", 11.0) if len(styles) else 11.0
    return points * prefs.system.ui_scale


SEARCH_ROW = 1.3      # x UI unit: Maya's search row above the rows (Blender's Outliner header has one row only)


def top(region, u):
    """Region y of the first row's top edge: the search row lies above it."""
    return region.height - int(SEARCH_ROW * u)


def page_rows(region, u):
    return max(1, top(region, u) // u)


def first_row(area, region, n, u):
    """First shown row of ``area`` (scroll), clamped so the last page is full."""
    top = max(0, n - page_rows(region, u))
    first = min(max(0, SCROLL.get(area.as_pointer(), 0)), top)
    SCROLL[area.as_pointer()] = first
    return first


def row_index_at(area, region, y, u, n):
    """Row under region y, or None (below the last row)."""
    if y < 0 or y >= top(region, u):
        return None
    k = first_row(area, region, n, u) + int((top(region, u) - 1 - y) // u)
    return k if 0 <= k < n else None


def row_rect(area, region, k, u, n):
    """(y0, y1) region pixels of row ``k`` (it may lie outside the region)."""
    j = k - first_row(area, region, n, u)
    y1 = top(region, u) - j * u
    return y1 - u, y1


def shift_x(area, rows, u):
    """Pixels the rows of ``area`` are panned left, clamped so the deepest row's arrow can reach the left edge."""
    key = area.as_pointer()
    sx = SCROLL_X.get(key, 0)
    if sx:
        sx = SCROLL_X[key] = min(max(0, sx), max((r.depth for r in rows), default=0) * u)
    return sx


SCROLLBAR = 0.35      # x UI unit: the scrollbar width at the right edge


def scrollbar(region, u, n, first):
    """(x0, x1, thumb y0, thumb y1) of the scrollbar, or None when every row fits."""
    page = page_rows(region, u)
    if n <= page:
        return None
    h = top(region, u)
    thumb = max(u, h * page / n)
    y1 = h - (h - thumb) * first / max(1, n - page)
    x1 = region.width - 2
    return x1 - max(4, round(SCROLLBAR * u)), x1, y1 - thumb, y1


# --- drawing -------------------------------------------------------------------------------------------------------

def _quad(pos, col, x0, y0, x1, y1, rgba):
    pos.extend(((x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)))
    col.extend((rgba,) * 6)


_ICON_PARTS = {}          # (kind, cx, cy, r, rgba) -> the icon's (tris, tcol, lines, lcol) made by ``_icon_parts``


def _icon(tris, tcol, lines, lcol, kind, cx, cy, r, rgba):
    """Add a node icon's shapes; an icon drawn at the same place and colour before reuses the points made then."""
    key = (kind, cx, cy, r, rgba)
    got = _ICON_PARTS.get(key)
    if got is None:
        made = ([], [], [], [])
        _icon_parts(*made, kind, cx, cy, r, rgba)
        if len(_ICON_PARTS) > 1024:
            _ICON_PARTS.clear()
        got = _ICON_PARTS[key] = tuple(tuple(m) for m in made)
    tris.extend(got[0])
    tcol.extend(got[1])
    lines.extend(got[2])
    lcol.extend(got[3])


def _icon_parts(tris, tcol, lines, lcol, kind, cx, cy, r, rgba):
    from .hypergraph_layout import icon_shapes
    for prim in icon_shapes(kind):
        name, a = prim[0], prim[1:]
        if name == "rect":
            _quad(tris, tcol, cx + a[0] * r, cy + a[1] * r, cx + a[2] * r, cy + a[3] * r, rgba)
        elif name == "frame":
            x0, y0, x1, y1 = cx + a[0] * r, cy + a[1] * r, cx + a[2] * r, cy + a[3] * r
            lines.extend(((x0, y0), (x1, y0), (x1, y0), (x1, y1), (x1, y1), (x0, y1), (x0, y1), (x0, y0)))
            lcol.extend((rgba,) * 8)
        elif name == "line":
            lines.extend(((cx + a[0] * r, cy + a[1] * r), (cx + a[2] * r, cy + a[3] * r)))
            lcol.extend((rgba,) * 2)
        elif name in ("ring", "disc"):
            ox, oy, rr = cx + a[0] * r, cy + a[1] * r, a[2] * r
            pts = [(ox + rr * math.cos(2 * math.pi * i / 12), oy + rr * math.sin(2 * math.pi * i / 12))
                   for i in range(12)]
            for i in range(12):
                p, q = pts[i], pts[(i + 1) % 12]
                if name == "ring":
                    lines.extend((p, q))
                    lcol.extend((rgba,) * 2)
                else:
                    tris.extend(((ox, oy), p, q))
                    tcol.extend((rgba,) * 3)
        elif name == "tri":
            tris.extend(((cx + a[0] * r, cy + a[1] * r), (cx + a[2] * r, cy + a[3] * r),
                         (cx + a[4] * r, cy + a[5] * r)))
            tcol.extend((rgba,) * 3)


def _triangle(tris, tcol, cx, cy, r, down, rgba):
    if down:
        pts = ((cx - r, cy + r * 0.5), (cx + r, cy + r * 0.5), (cx, cy - r * 0.7))
    else:
        pts = ((cx - r * 0.5, cy + r), (cx - r * 0.5, cy - r), (cx + r * 0.7, cy))
    tris.extend(pts)
    tcol.extend((rgba,) * 3)


ICON_RGB = (0.741, 0.741, 0.741)      # kit icon grey
JOINT_RGB = (0.282, 0.667, 0.710)     # kit icon teal
CHILD_SELECTED = 0.33                 # share of the selection highlight on a row with a selected node below it
INSTANCE_RGB = (0.78, 0.58, 1.0)      # soft purple: an instance copy or an instance group (preference)


def eye_x(region, u, n, first):
    """Centre x of the last restriction column, left of the scrollbar."""
    bar = scrollbar(region, u, n, first)
    right = bar[0] if bar is not None else region.width
    return right - u        # where Blender centres its last restriction column


_restrict_textures = {}


def restrict_texture(u, col, on, rgb, alpha=1.0):
    """(size, GPU texture) of Blender's own column icon for row height ``u`` (``blender_restrict_icons``: Blender's
    Outliner icon at that height; the nearest one for a height not there), in the theme text colour."""
    from .blender_restrict_icons import CELLS
    have = min({k[0] for k in CELLS}, key=lambda k: (abs(k - u), k))
    key = (have, col, on, rgb, alpha)
    hit = _restrict_textures.get(key)
    if hit is None:
        import base64
        import zlib
        import gpu
        import numpy as np
        cov = np.frombuffer(zlib.decompress(base64.b64decode(CELLS[(have, col, on)])), np.uint8)
        px = np.empty((have, have, 4), np.float32)
        px[..., :3] = rgb
        px[..., 3] = cov.reshape(have, have)[::-1] * (alpha / 255.0)        # stored top row first
        buf = gpu.types.Buffer('FLOAT', have * have * 4, px.ravel().tolist())
        hit = _restrict_textures[key] = (have, gpu.types.GPUTexture((have, have), format='RGBA32F', data=buf))
    return hit


def _draw_restrict(icons, rgb, u):
    import gpu
    from gpu_extras.batch import batch_for_shader
    sh = gpu.shader.from_builtin('IMAGE')
    quads = {}      # one batch per texture, not per icon
    for col, on, x0, y0, alpha in icons:
        pos, uv = quads.setdefault((col, on, alpha), ([], []))
        a, b, c, d = (x0, y0), (x0 + u, y0), (x0 + u, y0 + u), (x0, y0 + u)
        pos.extend((a, b, c, a, c, d))
        uv.extend(((0, 0), (1, 0), (1, 1), (0, 0), (1, 1), (0, 1)))
    for (col, on, alpha), (pos, uv) in quads.items():
        call(sh.uniform_sampler, "image", restrict_texture(u, col, on, rgb, alpha)[1])
        call(batch_for_shader(sh, 'TRIS', {"pos": pos, "texCoord": uv}).draw, sh)


# Blender's restriction columns, left to right (Display menu, kit preference); EYE is the kit's visibility
COLUMNS = (('SELECT', "show_restrict_column_select", "outliner_select_column"),
           ('EYE', "show_restrict_column_hide", "outliner_eye_column"),
           ('RENDER', "show_restrict_column_render", "outliner_render_column"))


def column_xs(space, region, u, n, first):
    """{column: centre x} of the shown columns, the last one at ``eye_x``. With the Outliner Column Icons preference
    off only the kit's visibility column (Display > Visibility Column); on, each column that is on in the Display
    menu and in the kit preferences."""
    from .. import preferences
    prefs = preferences.get()
    shown = [c for c, prop, pref in COLUMNS
             if getattr(space, prop) and (getattr(prefs, pref) if prefs.outliner_columns else c == 'EYE')]
    right = eye_x(region, u, n, first)
    return {c: right - (len(shown) - 1 - i) * u for i, c in enumerate(shown)}
