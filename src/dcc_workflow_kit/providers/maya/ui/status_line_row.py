# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows > UI Elements > Status Line in the kit layouts, like Maya: off closes the Status Line row above the shelf
(the shelf row stays and keeps its height, the viewports below get the room), on puts the row back over the shelf. A
strip that holds the Status Line and the shelf in one area (the Shelf toggle, layouts of older versions) hides or
shows its Status Line header instead.

A screen the kit changed carries ``CLOSED`` (the height the row had): the Status Line of another workspace's screen
follows the preference when that screen is next drawn (``check``), and a row closed some other way stays closed.
The rows are changed from a timer, a step per tick (area rects update a tick after a split or a close);
``screen.area_close`` hangs without a UI, so nothing changes in background mode. Related: shelf_strip.py."""

import bpy

from .. import live_refs

CLOSED = "allset_status_line_closed"

_jobs = {}      # window pointer -> the generator changing that window's rows


def wanted(context=None):
    from .. import preferences
    try:
        return preferences.get(context or bpy.context).show_status_line
    except KeyError:
        return True


def _header(area):
    return next((r for r in area.regions if r.type == 'HEADER'), None)


def needs_change(screen, on):
    """True when ``screen``'s rows don't follow the Status Line preference ``on``."""
    from .shelf_strip import shelf_row_area, strip_area
    strip = strip_area(screen)
    if not on:
        return strip is not None and strip.spaces.active.show_region_header
    if not screen.get(CLOSED):
        return False
    return strip is not None or shelf_row_area(screen) is not None


def _move(window, area, y, delta):
    """Move the horizontal edge at window height ``y`` under / over ``area`` by ``delta`` px (up > 0)."""
    x = area.x + area.width // 2
    with bpy.context.temp_override(window=window, screen=window.screen, area=area):
        if bpy.ops.screen.area_move.poll():
            bpy.ops.screen.area_move(x=x, y=y, delta=int(delta))


def _job(ptr):
    from .shelf_strip import make_strip, shelf_row_area, strip_area
    window = live_refs.window(ptr)
    if window is None:
        return
    screen = window.screen
    on = wanted()
    strip = strip_area(screen)
    row = shelf_row_area(screen)
    if strip is not None and strip.spaces.active.show_region_tool_header:
        # one area: the Status Line in its header, the shelf in its tool header
        space = strip.spaces.active
        if space.show_region_header != on:
            header = _header(strip)
            px = int(screen.get(CLOSED) or 0) if on else (header.height if header is not None else 0)
            with bpy.context.temp_override(window=window, screen=screen, area=strip):
                space.show_region_header = on
            yield
            if px > 0:
                _move(window, strip, strip.y, -px if on else px)
            if not on:
                screen[CLOSED] = px
        if on and CLOSED in screen:
            del screen[CLOSED]
        return
    if not on:
        if strip is None or row is None:
            return
        px, keep = strip.height, row.height
        from .maya_dock_windows import close_area
        if not close_area(bpy.context, window, strip):
            return
        screen[CLOSED] = px
        yield
        row = shelf_row_area(screen)
        if row is not None and row.height - keep > 1:     # the shelf row took the Status Line's room
            _move(window, row, row.y, row.height - keep)
        return
    if strip is not None or row is None or not screen.get(CLOSED):
        if CLOSED in screen and (strip is not None or row is None):
            del screen[CLOSED]
        return
    px, keep = int(screen.pop(CLOSED)), row.height     # cleared first: a failed step is not tried again on redraw
    _move(window, row, row.y, -px)          # room for the Status Line: the viewports below give it
    yield
    row = shelf_row_area(screen)
    if row is None:
        return
    before = {a.as_pointer() for a in screen.areas}
    region = next((r for r in row.regions if r.type == 'WINDOW'), None)
    factor = max(0.05, min(0.95, 1.0 - px / max(row.height, 1)))
    with bpy.context.temp_override(window=window, screen=screen, area=row, region=region):
        if bpy.ops.screen.area_split(direction='HORIZONTAL', factor=factor) != {'FINISHED'}:
            return
    new = next((a for a in screen.areas if a.as_pointer() not in before), None)
    if new is None:
        return
    pieces = (row.as_pointer(), new.as_pointer())
    yield                                   # the two pieces' rects are set a tick after the split
    found = [a for a in screen.areas if a.as_pointer() in pieces]
    if len(found) != 2:
        return
    top, bottom = sorted(found, key=lambda a: -a.y)
    # the top piece is the Status Line row (header only), the bottom one the shelf row (WINDOW only)
    space = top.spaces.active
    make_strip(space)
    space.show_region_tool_header = False
    space.show_gizmo_navigate = False
    with bpy.context.temp_override(window=window, screen=screen, area=top):
        space.show_region_header = True
    shelf = bottom.spaces.active
    from .shelf_strip import SHELF_MARKER
    mask = bpy.data.masks.get(SHELF_MARKER)
    if mask is not None:
        shelf.mask = mask
    shelf.show_region_tool_header = False
    shelf.show_gizmo_navigate = False
    with bpy.context.temp_override(window=window, screen=screen, area=bottom):
        shelf.show_region_header = False
    yield
    strip, row = strip_area(screen), shelf_row_area(screen)
    if strip is None or row is None:
        return
    header = _header(strip)
    extra = strip.height - (header.height if header is not None else strip.height)
    if extra > 1:              # one header high: the rest goes back to the shelf row
        _move(window, strip, strip.y, extra)
        yield
        row = shelf_row_area(screen)
        if row is None:
            return
    if abs(row.height - keep) > 1:
        _move(window, row, row.y, row.height - keep)


def _tick():
    for ptr, job in list(_jobs.items()):
        window = live_refs.window(ptr)
        try:
            if window is None:
                raise StopIteration
            with bpy.context.temp_override(window=window, screen=window.screen):
                next(job)
        except (StopIteration, ReferenceError, RuntimeError, AttributeError):
            _jobs.pop(ptr, None)
            if window is not None:
                for area in window.screen.areas:
                    area.tag_redraw()
            from .status_line import redraw_top_bars
            redraw_top_bars()
    return 0.05 if _jobs else None


def sync(window):
    """Make ``window``'s rows follow the Status Line preference (from a timer, over a few ticks)."""
    if window is None or bpy.app.background:
        return
    ptr = live_refs.pointer(window)
    if ptr in _jobs or not needs_change(window.screen, wanted()):
        return
    _jobs[ptr] = _job(ptr)
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.0)


def sync_main(context):
    """The preference changed: the main window follows now, other screens when drawn (``check``)."""
    from .maya_dock_windows import main_window
    sync(main_window(context.window_manager))


def check(context):
    """From the kit rows' drawing: a screen shown since the preference changed (another workspace) follows it."""
    if context.screen is not None:
        sync(context.window)


def stop():
    _jobs.clear()
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
