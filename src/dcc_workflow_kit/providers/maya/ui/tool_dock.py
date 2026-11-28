# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Tool Settings: a floating window, or a docked column left of the viewport.

Maya's Tool Settings opens as a floating window at the top left of the main window (a double-click on a Tool Box
tool, Windows > General Editors > Tool Settings, the Status Line button, a tool's option box). Docked, it is a column
left of the viewport — left of the whole four view, never inside one of its panels — and it opens again where it was
last. The kit's Tool Settings is a Properties editor on its Tool tab with its header and navigation bar hidden: the
Tool tab draws the 3D View "Tool" panels, i.e. ``tool_settings.ALLSET_PT_tool_settings`` (Maya sections) and, for
tools without Maya sections, Blender's own tool panels. It is recognised by its state (Tool tab and no header), so a
dock survives saving and reloading the file.

- Floating (``open_floating``): a window of its own, at the place it had when it was last closed (else the top left
  of the viewport), carved out of a viewport panel and given back afterwards (``window_places``), so no panel of the
  layout changes.
- Docked (``open_dock``): split off the left edge of the main 3D View. In the four view the four panels are folded
  into one first, the dock is split off it and the four view comes back in the rest (``four_view.in_one_panel``;
  the panels keep their settings). Closing gives the dock's width back to the panel right of it.
- The window's handle docks it (``maya_dock.dock``), the dock's handle tears it off (``maya_dock.tear_off``); the
  next opening follows (``set_docked``). ToggleToolSettings shows / hides it (Maya: visible -> hidden -> visible).

GUI facts: ``screen.area_split(direction='VERTICAL', factor=f)`` with f < 0.5 puts
the new area on the left with width f x the old width; ``SpaceProperties.context`` can only be set the tick after the
area became a Properties editor (its enum is empty before); ``screen.region_toggle(region_type='NAVIGATION_BAR')``
hides the tab column. ``screen.area_close`` gives a closing area to any neighbour sharing its edge (the Outliner
column too) and hangs in background mode, so closing joins the dock into the panel right of it, GUI only.
"""

import bpy

from .. import live_refs

WIDTH = 280          # unscaled px (Maya's narrow panels are 260 by default; its Tool Settings 460)
MAX_SHARE = 0.35     # of the main viewport's width
ROWS = 24            # rows of the Move / Rotate / Scale settings (the floating window's height)
KIND = "tool_settings"      # the floating window's name for its remembered place (window_places)
_pending = {}        # area pointer -> True while a new dock / window waits for its first tick
_where = {"docked": False}      # where the Tool Settings opens next: Maya's floating window, or the dock once docked


def is_dock(area):
    if area is None or area.type != 'PROPERTIES':
        return False
    space = area.spaces.active
    if space.show_region_header or space.context != 'TOOL':
        return False
    from .maya_dock import ROLE_FLAGS     # a Maya panel's dock area is a Tool tab too: role flag set
    return not any(getattr(space, flag, False) for flag in ROLE_FLAGS.values())


def find(screen):
    """The Tool Settings area of ``screen`` (or None)."""
    for area in (screen.areas if screen else ()):
        if is_dock(area) or area.as_pointer() in _pending:
            return area
    return None


def shown(screen):
    return find(screen) is not None


def find_any(wm=None):
    """(window, area) of the Tool Settings in any window (docked or floating), (None, None) when it is closed."""
    wm = wm or bpy.context.window_manager
    for window in wm.windows:
        area = find(window.screen)
        if area is not None:
            return window, area
    return None, None


def shown_anywhere(wm=None):
    return find_any(wm)[1] is not None


def set_docked(on):
    """Remember where the Tool Settings was put last (docked or floating): it opens there next time."""
    _where["docked"] = bool(on)


def _main_view(screen):
    from .status_line import main_view3d
    return main_view3d(screen)


def configure(area, window=None):
    """Make ``area`` (already a Properties editor) the Tool Settings. True when done."""
    space = area.spaces.active
    try:
        space.context = 'TOOL'
    except TypeError:          # the space hasn't been initialised yet
        return False
    for prop in space.bl_rna.properties:
        ident = prop.identifier
        if ident.startswith("show_properties_") and ident != "show_properties_tool":
            setattr(space, ident, False)
    # Changing the visible context flags can make Blender fall back to Object.
    # Select Tool again after those updates so the new dock opens on its content.
    space.context = 'TOOL'
    space.show_region_header = False
    nav = next((r for r in area.regions if r.type == 'NAVIGATION_BAR'), None)
    if nav is not None and nav.width > 1 and window is not None:
        try:
            with bpy.context.temp_override(window=window, area=area):
                bpy.ops.screen.region_toggle(region_type='NAVIGATION_BAR')
        except (RuntimeError, TypeError):
            pass
    area.tag_redraw()
    return True


def configure_later(area, window):
    """``configure`` from a timer (a Properties editor made in this call has no tabs yet)."""
    key = area.as_pointer()
    win_ptr = live_refs.pointer(window)
    _pending[key] = True

    def later(tries=[20]):
        # pointers, looked up each tick: a closed window's area must not be touched (#36)
        win, area = live_refs.find_area(key, win_ptr or None)
        try:
            if area is None:       # area or window gone
                done = True
            else:
                with bpy.context.temp_override(window=win):
                    done = configure(area, win)
        except ReferenceError:
            done = True
        tries[0] -= 1
        if done or tries[0] <= 0:
            _pending.pop(key, None)
            return None
        return 0.05
    bpy.app.timers.register(later, first_interval=0.0)


# --- docked ---------------------------------------------------------------------------------------------------------

def open_dock(context, window=None, width=None):
    """Split the main viewport and put the dock on its left. Returns the new area, True when it comes on a later
    tick (the four view), or None."""
    window = window or context.window
    screen = window.screen if window is not None else context.screen
    if find(screen) is not None:
        return find(screen)
    from . import four_view
    if four_view.is_four(screen) and not bpy.app.background:
        # Maya docks beside the whole four view, never inside one of its panels (#367)
        return True if four_view.in_one_panel(context, window,
                                              lambda ctx, win, _panel: open_dock(ctx, win, width)) else None
    area, region = _main_view(screen)
    if area is None or region is None:
        return None
    scale = context.preferences.system.ui_scale or 1.0      # 0 in background
    factor = min(MAX_SHARE, (width or WIDTH) * scale / max(area.width, 1))
    before = {a.as_pointer() for a in screen.areas}
    with context.temp_override(window=window, screen=screen, area=area, region=region):
        if bpy.ops.screen.area_split(direction='VERTICAL', factor=factor) != {'FINISHED'}:
            return None
    new = next((a for a in screen.areas if a.as_pointer() not in before), None)
    if new is None:
        return None
    new.ui_type = 'PROPERTIES'
    if not configure(new, window):
        configure_later(new, window)
    return new


def _right_neighbour(screen, area):
    """The area right of ``area`` that is exactly as tall (the viewport beside the dock), or None."""
    from .four_view import border_gap
    gap = border_gap()
    x1 = area.x + area.width
    return next((a for a in screen.areas if a.as_pointer() != area.as_pointer() and abs(a.x - x1) <= gap
                 and abs(a.y - area.y) <= gap and abs(a.height - area.height) <= gap), None)


def _join_into_view(context, window, dock):
    """The panel right of ``dock`` takes the dock's place (``screen.area_join``); False when no area there is as tall
    as the dock."""
    right = _right_neighbour(window.screen, dock)
    if right is None:
        return False
    keep = (right.x + right.width // 2, right.y + right.height // 2)
    gone = (dock.x + dock.width // 2, dock.y + dock.height // 2)
    with context.temp_override(window=window, screen=window.screen):
        try:
            return bpy.ops.screen.area_join(source_xy=keep, target_xy=gone) == {'FINISHED'}
        except RuntimeError:
            return False


def _area_close(context, window, area):
    with context.temp_override(window=window, screen=window.screen, area=area):
        try:
            bpy.ops.screen.area_close()
        except RuntimeError:
            pass


def close_dock(context, window=None):
    """Close the dock (GUI only): the viewport right of it gets its width back. True when there was one."""
    window = window or context.window
    screen = window.screen if window is not None else context.screen
    area = find(screen)
    if area is None:
        return False
    _pending.pop(area.as_pointer(), None)
    if bpy.app.background:      # screen.area_close / area_join need the Blender window
        return False
    if _join_into_view(context, window, area):
        return True
    from . import four_view
    if four_view.is_four(screen):
        # the dock is left of the four view: the four panels are one panel again first, which takes the dock's place
        ptr = area.as_pointer()

        def give_back(ctx, win, _panel):
            dock = next((a for a in win.screen.areas if a.as_pointer() == ptr), None)
            if dock is not None and not _join_into_view(ctx, win, dock):
                _area_close(ctx, win, dock)
        if four_view.in_one_panel(context, window, give_back):
            return True
    _area_close(context, window, area)
    return True


# --- floating -------------------------------------------------------------------------------------------------------

def _floating_opened(new):
    """The new window (a copy of a viewport piece) becomes the Tool Settings. Its area, or None."""
    if new is None:
        return None
    try:
        area = new.screen.areas[0]
        area.ui_type = 'PROPERTIES'
    except (ReferenceError, IndexError, TypeError):
        return None
    if not configure(area, new):
        configure_later(area, new)
    return area


def open_floating(context, window=None, width=None):
    """Maya's Tool Settings window: at the place it had when it was last closed, else at the top left of the
    viewport (of the four view's top panel), ``width`` unscaled px wide and as tall as its settings. Returns the
    window's area, True when it opens on a later tick (its place is carved out of the panel first), None when it
    can't open (background mode, no viewport)."""
    from . import four_view, maya_dock, window_places
    wm = context.window_manager
    window = window or context.window
    if window is None or maya_dock.is_floating(window, wm):
        window = maya_dock.main_window(wm)
    if window is None or bpy.app.background:
        return None
    four = four_view.block(window.screen)
    area = four.get("top") if four else _main_view(window.screen)[0]
    if area is None:
        return None
    scale = context.preferences.system.ui_scale or 1.0
    w = min(round((width or WIDTH) * scale), area.width)
    h = maya_dock.content_height(context, ROWS, area.height)
    default = (window.x + area.x, window.y + area.y + area.height - h, w, h)
    window_places.STRICT.add(KIND)          # never a copy of the whole panel
    with context.temp_override(window=window, screen=window.screen, area=area):
        new = window_places.open_at(bpy.context, area, KIND, default=default, then=_floating_opened,
                                    piece_type='PROPERTIES')
        later = window_places.deferred()
    if new is not None:
        return _floating_opened(new)
    return True if later else None


def open_tool_settings(context, window=None, width=None):
    """Open the Tool Settings where it was last: floating (Maya's first place) or docked."""
    if _where["docked"]:
        got = open_dock(context, window, width)
        if got is not None:
            return got
    return open_floating(context, window, width) or open_dock(context, window, width)


def close(context, window, area):
    """Hide the Tool Settings shown in ``area`` of ``window``: its floating window closes, the dock gives its width
    back."""
    from . import maya_dock
    if maya_dock.is_floating(window, context.window_manager):
        if window != context.window:      # closing the window an operator runs in would pull its context away
            try:
                with context.temp_override(window=window):
                    bpy.ops.wm.window_close()
                return
            except (RuntimeError, ReferenceError):
                pass
        maya_dock.close_window_later(window)
        return
    close_dock(context, window)


def _to_front(context, window, area):
    """The Tool Settings shown in ``area`` of ``window``: a floating window is brought to the front
    (``maya_dock.to_front``), a dock redrawn. Its area now."""
    from . import maya_dock
    if maya_dock.is_floating(window, context.window_manager):
        new = maya_dock.to_front(context, window)
        if new is not None and new != window and new.screen.areas:
            return new.screen.areas[0]
    area.tag_redraw()
    return area


def show(context, width=None):
    """Maya Tool Settings from a Tool Box double-click (#3): the Tool Settings open in any window (docked or
    floating) is shown (a floating window comes to the front, ``_to_front``), else it opens where it was last (Maya:
    a floating window). Returns its area, True while it opens on a later tick, None when it can't open."""
    window, area = find_any(context.window_manager)
    if area is not None:
        return _to_front(context, window, area)
    from . import maya_dock
    main = maya_dock.main_window(context.window_manager)
    if 'TOOL_SETTINGS' in maya_dock.tab_kinds() and (
            'TOOL_SETTINGS' in maya_dock.floating_kinds() or (main is not None and maya_dock.find_stack(main.screen))):
        maya_dock.show(context, 'TOOL_SETTINGS')      # the Tool Settings Tab preference: a tab of the right dock
        return maya_dock.find_stack(main.screen) if main is not None else None
    return open_tool_settings(context, width=width)


def toggle(context, show_only=False):
    """Maya ToggleToolSettings (``show_only``: open without closing). True = shown after."""
    window, area = find_any(context.window_manager)
    if area is not None:
        if show_only:
            _to_front(context, window, area)
            return True
        close(context, window, area)
        return False
    return open_tool_settings(context) is not None
