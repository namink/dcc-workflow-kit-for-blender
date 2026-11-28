# SPDX-License-Identifier: GPL-3.0-or-later
"""The Channel Box part of a dock: its fixed share of the dock height above the Layer Editor, equal-height lines
that scroll inside it, and the scroll buttons / wheel step.
Entry points: cb_share, pane_room, Lines, scroll_lines, fill_pane.
Related: cb_panel.py; the wheel watcher is in channel_box.py."""

import bpy
from bpy.props import IntProperty


# Channel Box pane share of the dock, Layer Editor below: about half of the dock below its header, like Maya's
# standard screen.
# The split is fixed: a long Channel Box scrolls inside its part.
CB_SHARE = 0.50
CB_SHARE_MAX = 0.62      # the Layer Editor keeps its tabs, toolbar and a few rows
CB_LINES = 14            # a cube's collapsed Channel Box: 10 channels, SHAPES + shape, INPUTS + polyCube1


def cb_share(region, u):
    """Share of the dock height above the Layer Editor: about half (CB_SHARE), more on a short
    dock so a selected primitive's collapsed Channel Box (CB_LINES) still fits
    without scrolling — fixed for a given dock height, like Maya's split."""
    if region is None or region.height <= 0 or u <= 0:
        return CB_SHARE
    need = (PANE_TOP + 3.0 + 0.3 + CB_LINES * ROW_SCALE) * u    # = pane_room's terms for the menu bar + name line
    return min(CB_SHARE_MAX, max(CB_SHARE, need / region.height))


_hover = {}      # window pointer -> (key, "NAME" / "VALUE") under the mouse, or None


def _round_half_up(x):
    """C roundf for UI sizes (UI_UNIT_Y = roundf(18 x scale) + 2 x pixel size): Python's round(22.5) is 22, Blender's 23,
    so at UI 1.25 the unit was 24 px instead of 25 and every 0.8 U row 0.8 px short (#83)."""
    return int(x + 0.5)


def row_pitch(context):
    """Channel row height in px (ROW_SCALE x Blender's widget unit)."""
    system = context.preferences.system
    unit = _round_half_up(18.0 * system.ui_scale) + 2 * system.pixel_size
    return max(1.0, unit * ROW_SCALE)


def _redraw(window):
    for area in window.screen.areas if window is not None and window.screen else ():
        area.tag_redraw()


ROW_SCALE = 0.8


# --- lines: the Channel Box below its name row is a fixed pane that scrolls (#55) ---------------------------
# Maya keeps the Channel Box / Layer Editor split and scrolls a long Channel Box inside its part.
# Blender can't scroll part of a region, so every Channel Box row
# under the lead's name is one equal line (ROW_SCALE) of one aligned column, and the pane draws the lines that fit.

_scroll = {}    # area pointer -> first line shown
_reveal = {"node": None}    # an INPUTS node key to scroll into view at the next draw (``reveal``)
_last = {}      # area pointer -> (first, total, limit) of the last draw (limit None: every line fits)
_filled = {}    # area pointer -> UI units from the region top that the Channel Box rows use (empty space below)
WHEEL_LINES = 3     # Maya: one notch = 15 px x QApplication.wheelScrollLines 3 = 45 px ~ 3 rows (PR #125 check)
BUTTON_LINES = 3


class Lines:
    """An aligned column of equal rows that shows only rows ``first`` .. ``first + limit`` (``layout`` None: count)."""

    def __init__(self, layout, first=0, limit=None):
        self.layout = layout
        self.first = first
        self.limit = limit
        self.n = 0
        self.shown = 0
        self.marks = {}     # INPUTS node key -> its line index (``reveal``)

    def row(self):
        i = self.n
        self.n += 1
        if self.layout is None or i < self.first or (self.limit is not None and self.shown >= self.limit):
            return None
        self.shown += 1
        return self.layout.row(align=True)


def reveal(node):
    """Scroll the Channel Box to INPUTS node ``node`` at its next draw."""
    _reveal["node"] = node


def as_lines(layout):
    return layout if isinstance(layout, Lines) else Lines(layout)


def window_lines(total, room, first):
    """(first, limit, overflow) for ``total`` lines in a pane of ``room`` lines. The scroll buttons sit on the lead's
    name line (on the last content line they took the place of the node that was just expanded)."""
    if room is None or total <= room:
        return 0, None, False
    limit = max(1, room)
    return max(0, min(first, total - limit)), limit, True


def _unit(context):
    system = context.preferences.system
    return _round_half_up(18.0 * system.ui_scale) + 2 * system.pixel_size


def _split_off(context):
    sdk = getattr(context.window_manager, "allset_sdk", None)
    return sdk is not None and sdk.open    # the Set Driven Key window takes the Layer Editor's place


def pane_room(context, units):
    """Lines that fit in the Channel Box part (CB_SHARE of the region) under ``units`` of fixed rows; None = no
    split (no region: headless drawing, or the Set Driven Key window)."""
    region = context.region
    if region is None or region.type not in {'UI', 'WINDOW'} or _split_off(context):
        return None
    u = _unit(context)
    if u <= 0 or region.height <= 0:
        return None
    room = (cb_share(region, u) * region.height / u - units - PANE_TOP - 0.3) / ROW_SCALE
    return max(2, int(room + 1e-6))    # 11.2 / 0.8 = 13.999...: don't lose the last line to rounding


def _is_cb_dock(context):
    area, region = context.area, context.region
    if area is None or region is None or area.type != 'PROPERTIES' or region.type != 'WINDOW':
        return False
    from . import maya_dock
    return maya_dock.shown_kind(context) == 'CHANNEL_BOX'


def in_channel_part(context, event):
    """The mouse is over the Channel Box part of a Maya dock (above the Layer Editor), cells or not."""
    if not _is_cb_dock(context):
        return False
    region = context.region
    from_top = region.height - event.mouse_region_y
    return 0 <= from_top <= cb_share(region, _unit(context)) * region.height


def over_pane(context, event):
    """The mouse is over an overflowing Channel Box part of a Maya dock."""
    area, region = context.area, context.region
    if area is None or region is None or area.type != 'PROPERTIES' or region.type != 'WINDOW':
        return False
    from . import maya_dock
    if maya_dock.shown_kind(context) != 'CHANNEL_BOX':
        return False
    if _last.get(area.as_pointer(), (0, 0, None))[2] is None:
        return False
    from_top = region.height - event.mouse_region_y
    return 0 <= from_top <= cb_share(region, _unit(context)) * region.height


def scroll_lines(context, amount):
    """Move only the virtual Channel Box rows, never values or the Layer Editor."""
    area = context.area
    if area is None:
        return False
    ptr = area.as_pointer()
    first, total, limit = _last.get(ptr, (0, 0, None))
    if limit is None:
        return False
    first = _scroll.get(ptr, first)  # several wheel events may arrive before the next redraw
    _scroll[ptr] = max(0, min(first + amount, max(0, total - limit)))
    if _scroll[ptr] != first and context.window is not None:
        # New rows can appear under a stationary cursor; never retain the old
        # channel hit for the next click or drag.
        _hover.pop(context.window.as_pointer(), None)
    area.tag_redraw()
    return True


class ALLSET_OT_cb_scroll(bpy.types.Operator):
    """Scroll the Channel Box (Maya: its own scroll bar; the Layer Editor below stays)"""
    bl_idname = "allset.cb_scroll"
    bl_label = "Scroll Channel Box"
    bl_options = {'INTERNAL'}

    lines: IntProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            if event.ctrl or event.shift or event.alt or not over_pane(context, event):
                return {'PASS_THROUGH'}
            self.lines = WHEEL_LINES if event.type == 'WHEELDOWNMOUSE' else -WHEEL_LINES
        return self.execute(context)

    def execute(self, context):
        return {'FINISHED'} if scroll_lines(context, self.lines) else {'CANCELLED'}


def _scroll_row(col, first, limit, total):
    row = col.row(align=True)
    row.alignment = 'RIGHT'
    for lines, icon, on in ((-BUTTON_LINES, 'TRIA_UP', first > 0), (BUTTON_LINES, 'TRIA_DOWN', first + limit < total)):
        sub = row.row(align=True)
        sub.enabled = on
        sub.operator(ALLSET_OT_cb_scroll.bl_idname, text="", icon=icon, emboss=False).lines = lines


def fill_pane(layout, context, units):
    """Empty space under the Channel Box so the Layer Editor starts at CB_SHARE of the dock height, like Maya's
    fixed split (a longer Channel Box scrolls inside its part, ``Lines``)."""
    region = context.region
    if units is None or region is None or region.type not in {'UI', 'WINDOW'} or _split_off(context):
        return
    u = _unit(context)
    if u <= 0:
        return
    if context.area is not None:
        _filled[context.area.as_pointer()] = units + PANE_TOP
    gap = cb_share(region, u) * region.height / u - units - PANE_TOP
    if gap > 0.25:
        col = layout.column()
        col.scale_y = gap
        col.label(text="")


# panel margins, row spacing and the Layer Editor's splitter, in UI units. The 3D View sidebar draws 2.2;
# the dock's Properties region draws them 0.6-0.7 U shorter (shots at UI 1.0 / 1.25 / 1.5: 4.9 / 4.8 / 4.8 U of
# fixed rows against the 5.5 the model assumed), which cost a line and left 1.5 rows empty above the Layer Editor (#83)
PANE_TOP = 1.6
