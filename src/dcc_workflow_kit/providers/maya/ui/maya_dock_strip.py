# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's vertical tab strip on the tab stack's right edge: its geometry (``strip_px``, ``reserved_px``,
``strip_tabs``, ``strip_hit``), the stack content kept left of it (``content_layout``), the strip drawn with rotated
text (``draw_strip``), a click on a tab (``ALLSET_OT_dock_strip_click``) and the drawn tab remembered for the dock
width (``tab_drawn``). Drawn and registered by maya_dock.py, which also re-exports these names.
"""

import math

import bpy
from bpy.props import StringProperty

from .. import i18n
from .draw_replay import call
from .maya_dock_roles import LABELS, area_role, current_tab, redraw, role, stack_tabs
from .maya_dock_tint import _fill, dock_lift


# --- vertical tab strip (#78) ----------------------------------------------------------------------------
# Maya's stack tabs are a vertical strip on the stack's right edge, so the stack is only as wide as its panel
# (tabs from the content top, the text + a small margin at each end, close together, reading top to bottom; the
# raised tab in the panel colour, lowered tabs and the strip darker). Blender can't lay a button out rotated, so the
# strip is drawn here
# (POST_PIXEL, blf rotation) in a column the panel content keeps clear of (``content_layout``), and a click on it goes
# to ``ALLSET_OT_dock_strip_click`` (first in "View2D Buttons List"). Chosen over
# a width that follows the raised tab with horizontal tabs: the tab row alone needed 466 px at UI scale 1.
STRIP_PX = 18          # strip width at UI scale 1 (Blender's UI font is a little taller)
STRIP_GAP_PX = 6       # between the content and the strip
STRIP_TOP_PX = 4       # first tab below the region's top
TAB_END_PX = 11        # around a tab's text
TAB_GAP_PX = 2
STRIP_SHADE = 0.63     # strip background x the region background
TAB_SHADE = 0.81       # lowered tab x the region background
TEXT_LOWERED = 0.62    # lowered tab text x the theme text colour
PANEL_MARGIN_U = 0.4   # Blender's panel margin on each side of a Properties region, in widget units

_drawn = {}            # stack area pointer -> the tab drawn last (draw -> tab change -> dock width, toolbox)


def _ui_unit(scale, pixel_size=1.0):
    from .toolbar_fit import unit
    return unit(scale, pixel_size)


def strip_px(scale):
    return round(STRIP_PX * scale)


def reserved_px(scale):
    """Region px the stack's content leaves free at the right for the strip (strip + gap)."""
    return strip_px(scale) + round(STRIP_GAP_PX * scale)


def content_factor(width, scale, pixel_size=1.0):
    """Split factor of the stack's content column so it ends ``STRIP_GAP_PX`` left of the strip, for a region
    ``width`` px wide (the panel layout spans the region minus Blender's margin on each side)."""
    margin = PANEL_MARGIN_U * _ui_unit(scale, pixel_size)
    span = width - 2 * margin
    if span <= 1:
        return 1.0
    return max(0.0, min(1.0, (width - reserved_px(scale) - margin) / span))


class StripClear:
    """The stack panel's root layout kept left of the strip: every item drawn into it goes into its own split
    (content | an empty strip column). One split column for everything would move every row: a nested column spaces
    its items by the style's ``buttonspacey``, the panel's root by ``templatespace`` (the Channel Box rows
    came 4 px closer each at UI scale 1.5, and the GUI tests' row offsets missed). Attributes go to the root."""

    __slots__ = ("_root", "_factor")

    def __init__(self, root, factor):
        object.__setattr__(self, "_root", root)
        object.__setattr__(self, "_factor", factor)

    def __getattr__(self, name):
        value = getattr(self._root, name)
        if not callable(value):
            return value

        def call(*args, **kw):
            split = self._root.split(factor=self._factor)
            col = split.column()
            split.column()             # the strip's column: empty, drawn over by draw_strip
            return getattr(col, name)(*args, **kw)
        return call

    def __setattr__(self, name, value):
        setattr(self._root, name, value)


def content_layout(layout, context):
    """The layout the stack's panel draws into: left of the strip."""
    region = context.region
    if region is None or region.width <= 1:
        return layout
    system = context.preferences.system
    f = content_factor(region.width, system.ui_scale or 1.0, system.pixel_size)
    if f <= 0.2 or f >= 1.0:
        return layout
    return StripClear(layout, f)


# Blender's layout.panel header takes a click anywhere across the region at its height, before the strip's keymap
# item, so in the stack a section header over a tab swallowed the tab click. There a section is a plain disclosure
# row inside the content column instead (open state kept for the session).
_sections_open = {}      # section idname -> open


def section(layout, idname, label, default_closed=False):
    """A collapsible section: ``layout.panel`` outside the tab stack, a strip-safe row in it. Returns the body or None."""
    if area_role(bpy.context) != 'STACK':
        header, body = layout.panel(idname, default_closed=default_closed)
        header.label(text=label)
        return body
    is_open = _sections_open.setdefault(idname, not default_closed)
    row = layout.row()
    row.alignment = 'LEFT'
    row.operator(ALLSET_OT_dock_section.bl_idname, text=label, emboss=False,
                 icon='DISCLOSURE_TRI_DOWN' if is_open else 'DISCLOSURE_TRI_RIGHT').section = idname
    return layout.column() if is_open else None


class ALLSET_OT_dock_section(bpy.types.Operator):
    """Open or close this section"""
    bl_idname = "allset.dock_section"
    bl_label = "Toggle Section"
    bl_options = {'INTERNAL'}

    section: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        _sections_open[self.section] = not _sections_open.get(self.section, True)
        redraw()
        return {'FINISHED'}


def strip_tabs(kinds, width, height, scale, measure=None):
    """[(kind, x0, y0, x1, y1)] region rects of the strip's tabs (y up, first tab at the top)."""
    if measure is None:
        from .toolbox import text_px as measure
    x1 = width
    x0 = width - strip_px(scale)
    y = height - round(STRIP_TOP_PX * scale)
    out = []
    for kind in kinds:
        length = math.ceil(measure(i18n.iface(LABELS[kind]), scale) + 2 * TAB_END_PX * scale)
        out.append((kind, x0, y - length, x1, y))
        y -= length + round(TAB_GAP_PX * scale)
    return out


def strip_hit(kinds, width, height, scale, x, y, measure=None):
    """(inside the strip, kind of the tab at region point (x, y) or None)."""
    if x < width - strip_px(scale) or x > width:
        return False, None
    for kind, _x0, y0, _x1, y1 in strip_tabs(kinds, width, height, scale, measure):
        if y0 <= y <= y1:
            return True, kind
    return True, None


def tab_drawn(context, kind):
    """Remember the tab a stack area drew; a change resizes the stack Maya's way (layout_fit.tab_changed)."""
    area = context.area
    if area is None or kind is None:
        return
    key = area.as_pointer()
    old = _drawn.get(key)
    _drawn[key] = kind
    if old is not None and old != kind and context.window is not None:
        from . import toolbox
        toolbox.tab_changed(context.window, old, kind)


def _strip_colours(context):
    th = context.preferences.themes[0]
    try:
        back = tuple(th.properties.space.back)[:3]
        text = tuple(th.properties.space.text)[:3]
    except AttributeError:
        back, text = (0.19, 0.19, 0.19), (0.9, 0.9, 0.9)
    lift = dock_lift(context)
    return tuple(min(1.0, c + lift) for c in back), text


def draw_strip():
    context = bpy.context
    area, region = context.area, context.region
    if region is None or region.type != 'WINDOW' or role(area) != 'STACK':
        return
    import blf
    import gpu
    scale = context.preferences.system.ui_scale or 1.0
    current = current_tab(context.window_manager)
    tabs = strip_tabs(stack_tabs(context.window_manager), region.width, region.height, scale)
    back, text = _strip_colours(context)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    call(gpu.state.blend_set, 'ALPHA')
    x0 = region.width - strip_px(scale)
    _fill(shader, x0, 0, region.width, region.height, (*(c * STRIP_SHADE for c in back), 1.0))
    call(blf.size, 0, 11.0 * scale)
    cap = blf.dimensions(0, "X")[1]
    call(blf.enable, 0, blf.ROTATION)
    call(blf.rotation, 0, -math.pi / 2)     # clockwise: reads top to bottom, letter tops to the right (Maya)
    try:
        for kind, tx0, ty0, tx1, ty1 in tabs:
            raised = kind == current
            _fill(shader, tx0, ty0, tx1, ty1, (*(back if raised else tuple(c * TAB_SHADE for c in back)), 1.0))
            colour = text if raised else tuple(c * TEXT_LOWERED for c in text)
            call(blf.color, 0, *colour, 1.0)
            call(blf.position, 0, round((tx0 + tx1) / 2 - cap / 2), ty1 - round(TAB_END_PX * scale), 0)
            call(blf.draw, 0, i18n.iface(LABELS[kind]))
    finally:
        call(blf.disable, 0, blf.ROTATION)
        call(gpu.state.blend_set, 'NONE')


class ALLSET_OT_dock_strip_click(bpy.types.Operator):
    """Maya tab strip of the dock: click a tab to raise that panel"""
    bl_idname = "allset.dock_strip_click"
    bl_label = "Dock Tab Strip"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.region is not None and context.region.type == 'WINDOW' and area_role(context) == 'STACK'

    def invoke(self, context, event):
        region = context.region
        wm = context.window_manager
        inside, kind = strip_hit(stack_tabs(wm), region.width, region.height,
                                 context.preferences.system.ui_scale or 1.0,
                                 event.mouse_region_x, event.mouse_region_y)
        if not inside:
            return {'PASS_THROUGH'}
        if kind is not None and kind != current_tab(wm):
            wm.allset_dock = kind
            redraw()
        return {'FINISHED'}
