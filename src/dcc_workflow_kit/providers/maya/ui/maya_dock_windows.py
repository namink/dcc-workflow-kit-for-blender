# SPDX-License-Identifier: GPL-3.0-or-later
"""Opens, closes and moves Maya panels between the layout and floating windows: the main window and viewport, side
splits and the tab stack (``open_stack``), Maya's Windows menu raise / toggle (``show``, ``toggle``,
``open_floating``), bringing a floating panel to the front (``to_front``), windows sized to their content (``content_height``, ``sized_window``), docking a floating panel
back (``dock``) and closing kit windows on a switch to Blender (``close_floating``). maya_dock.py re-exports these.
"""

import bpy

from .. import live_refs
from .maya_dock_roles import (KINDS, WIDTH, _torn_menus, find_stack, floating_kinds, is_floating, kind_visible,
                              redraw, role, set_role, set_role_later)


def _main_view(screen):
    from .status_line import main_view3d
    return main_view3d(screen)


def main_window(wm=None):
    """The window with the main Maya viewport (the first non-floating window)."""
    wm = wm or bpy.context.window_manager
    for window in wm.windows:
        if not is_floating(window, wm) and _main_view(window.screen)[0] is not None:
            return window
    return wm.windows[0] if wm.windows else None


def split_side(context, window, side, width, ui_type, then=None, max_share=0.4):
    """Split ``window``'s main viewport and return the new area on ``side`` ('LEFT' / 'RIGHT') of ``width`` unscaled
    px, at most ``max_share`` of the viewport (VERTICAL factor < 0.5 = new area left, factor > 0.5 = new area right,
    ``1 - factor`` wide); ``then(new)`` finishes it. In the four view the area goes beside the whole view, never
    inside one of its panels: it comes on a later tick (``four_view.in_one_panel``) and True is returned."""
    screen = window.screen
    from . import four_view
    if four_view.is_four(screen) and not bpy.app.background:
        done = four_view.in_one_panel(
            context, window,
            lambda ctx, win, _panel: split_side(ctx, win, side, width, ui_type, then, max_share))
        return True if done else None
    area, region = _main_view(screen)
    if area is None or region is None:
        return None
    scale = context.preferences.system.ui_scale or 1.0
    share = min(max_share, width * scale / max(area.width, 1))
    factor = share if side == 'LEFT' else 1.0 - share
    before = {a.as_pointer() for a in screen.areas}
    with context.temp_override(window=window, screen=screen, area=area, region=region):
        if bpy.ops.screen.area_split(direction='VERTICAL', factor=factor) != {'FINISHED'}:
            return None
    new = next((a for a in screen.areas if a.as_pointer() not in before), None)
    if new is not None:
        new.ui_type = ui_type
        if then is not None:
            then(new)
    return new


def stack_width(context, window):
    """(unscaled px, share of the viewport at most) for a new tab stack: the width the tab it raises needs, like
    Maya (the Attribute Editor's stack is wider than the Channel Box's; layout_fit.dock_width), leaving the viewport
    at least layout_fit.MIN_VIEW_PX like a tab change's resize does, so a later tab change resizes it the same way."""
    from . import layout_fit
    system = context.preferences.system
    scale = system.ui_scale or 1.0
    kind = getattr(context.window_manager, "allset_dock", 'CHANNEL_BOX')
    want = layout_fit.dock_width(scale, system.pixel_size, kind=kind)
    area = _main_view(window.screen)[0]
    if area is None or area.width - round(layout_fit.MIN_VIEW_PX * scale) < want:
        return want / scale, 0.4         # a small window: the stack takes at most 40 % of the viewport
    return want / scale, 1.0


def open_stack(context, window=None):
    """The stack area right of ``window``'s viewport (made if missing), as wide as its raised tab needs."""
    window = window or main_window(context.window_manager)
    if window is None:
        return None
    stack = find_stack(window.screen)
    if stack is not None:
        return stack
    width, max_share = stack_width(context, window)
    win_ptr = live_refs.pointer(window)
    return split_side(context, window, 'RIGHT', width, 'PROPERTIES',
                      then=lambda new: set_role_later(new, 'STACK', live_refs.window(win_ptr) or window),
                      max_share=max_share)


def close_area(context, window, area):
    """``screen.area_close`` (GUI only: it hangs in background). A column beside the whole four view (the tab stack)
    is closed with the four view folded into one panel, which takes the column's place: the four view stays four
    equal panels."""
    if bpy.app.background or area is None:
        return False
    from . import four_view
    if four_view.beside(window.screen, area):
        ptr = area.as_pointer()

        def act(ctx, win, _panel):
            column = next((a for a in win.screen.areas if a.as_pointer() == ptr), None)
            if column is not None:
                close_area(ctx, win, column)
        return four_view.in_one_panel(context, window, act)
    with context.temp_override(window=window, screen=window.screen, area=area):
        return bpy.ops.screen.area_close() == {'FINISHED'}


def close_window_later(window):
    """Close a window from a timer (closing the window an operator runs in would pull the context away)."""
    ptr = live_refs.pointer(window)

    def tick():
        window = live_refs.window(ptr)
        try:
            if window is not None:
                with bpy.context.temp_override(window=window):
                    bpy.ops.wm.window_close()
        except (ReferenceError, RuntimeError):
            pass
        return None
    bpy.app.timers.register(tick, first_interval=0.0)


def floating_window(kind, wm=None):
    """The floating window showing only ``kind``, or None."""
    wm = wm or bpy.context.window_manager
    for window in wm.windows:
        if is_floating(window, wm) and role(window.screen.areas[0]) == kind:
            return window
    return None


def to_front(context, window, any_editor=False):
    """Bring the floating panel ``window`` to the front, like Maya raises a floating panel that is asked for.

    Blender has no call that raises a window, but a window it opens comes on top of the others: the panel's area is
    copied into a new window (``screen.area_dupli`` gives it the place and size of the area, which fills the old
    window, and keeps the editor's state, so the panel and its role are the same) and the old window is closed.
    Nothing happens to a window the command runs in (it is in front already). Returns the window showing the panel.
    The kit's editor windows (Shelf Editor, Hotkey Editor, ...: ``marked_window`` kinds) come to the front the same
    way; ``any_editor``: also a one-editor window of no kit kind (a floating UV Editor).
    """
    if window is None or bpy.app.background or window == context.window:
        return window
    from . import marked_window, tool_dock, window_places
    wm = context.window_manager
    if not is_floating(window, wm):
        return window
    area = window.screen.areas[0]
    kind = role(area)
    marked = marked_window.kind_of(area) if kind is None else None     # a kit editor (its Tool tab is no dock)
    tool = kind is None and marked is None and tool_dock.is_dock(area)
    if kind is None and not tool and marked is None and not any_editor:
        return window
    old_area = area.as_pointer()
    try:
        new = window_places.dupli(context, window, area)
    except RuntimeError:
        new = None
    if new is None or not new.screen.areas:
        return window
    window_places.handed_on(window, new)       # its place is remembered under the same name
    target = new.screen.areas[0]
    if kind is not None:
        if role(target) != kind:
            set_role_later(target, kind, new)
    elif marked is not None:
        if marked_window.kind_of(target) != marked:
            marked_window.set_kind_later(new, target, marked)
        marked_window.handed_on(old_area, target)
    elif tool:
        if not tool_dock.is_dock(target):
            tool_dock.configure_later(target, new)
    try:
        with context.temp_override(window=window):
            bpy.ops.wm.window_close()
    except (RuntimeError, ReferenceError):
        close_window_later(window)
    redraw()
    return new


def show(context, kind):
    """Maya Windows > ... : raise the panel (stack tab, or its floating window to the front), else open it floating
    when the layout has no stack."""
    wm = context.window_manager
    wm.allset_dock = kind          # the stack's tab (also when the panel floats: it comes back there)
    if kind in floating_kinds(wm):
        to_front(context, floating_window(kind, wm))
        return 'FLOATING'
    window = main_window(wm)
    if window is not None and find_stack(window.screen) is not None:
        redraw()
        return 'DOCKED'
    # No tab stack in this layout: one floating dock window switches between the panels (Ctrl+A flips it between
    # Attribute Editor and Channel Box instead of opening a window per press)
    for w in wm.windows:
        if is_floating(w, wm) and role(w.screen.areas[0]) in KINDS:
            set_role(w.screen.areas[0], kind, w)
            to_front(context, w)
            redraw()
            return 'FLOATING'
    return 'FLOATING' if open_floating(context, kind) is not None else None


def toggle(context, kind, show_only=False):
    """Maya Windows > UI Elements toggle: a hidden or tabbed-behind panel is raised; a shown one is hidden (its
    floating window closed, or the tab stack closed when it is the stack's tab). Returns True = shown after."""
    wm = context.window_manager
    if kind_visible(wm, kind):
        if show_only:
            to_front(context, floating_window(kind, wm))
            return True
        for window in list(wm.windows):
            if is_floating(window, wm) and role(window.screen.areas[0]) == kind:
                close_window_later(window)
                return False
        window = main_window(wm)
        stack = find_stack(window.screen) if window is not None else None
        if stack is not None:
            close_area(context, window, stack)
        return False
    window = main_window(wm)
    if window is not None and find_stack(window.screen) is None and _main_view(window.screen)[0] is not None:
        wm.allset_dock = kind
        with context.temp_override(window=window):
            open_stack(bpy.context, window)
        return True
    return show(context, kind) is not None


def open_floating(context, kind):
    """A floating window with only ``kind`` (no stack to raise it in)."""
    from ..operators.menu_extras import open_window
    window = context.window or main_window(context.window_manager)
    if window is None:
        return None
    area = max(window.screen.areas, key=lambda a: a.width * a.height, default=None)
    if area is None:
        return None
    new = open_window(context, area)
    if new is None:
        return None
    target = new.screen.areas[0]
    target.ui_type = 'PROPERTIES'
    set_role_later(target, kind, new)
    return new


# --- tear off / dock -----------------------------------------------------------------------------------------------
# Issue #4: Blender has no API to size or place a window, and ``screen.area_dupli`` opens a window of the copied
# area's size. So the source area is first split (``area_split`` HORIZONTAL, factor > 0.5 = the new area on top,
# 1 - factor tall) to the content height computed by ``layout_measure``; that top piece is
# copied a tick later (a split area has no size before the screen refreshed: a copy in the same call opened a
# default-size window) and closed again, which gives the source its height back.

MIN_ROWS = 6                 # a torn-off window is never shorter than this ...
PAD_ROWS = 1.5               # ... and gets the region's top / bottom margins on top of its content
MIN_KEEP_PX = 40             # Blender keeps a split's other part at least about a header high


def content_height(context, n_rows, limit):
    """Window height (px) for ``n_rows`` rows of content, clamped to [MIN_ROWS rows, ``limit``]."""
    from . import layout_measure
    rows = max(MIN_ROWS, (n_rows or 0) + PAD_ROWS)
    return min(layout_measure.px(rows, context), limit)


def sized_window(context, window, area, height, then, tries=20):
    """Open a window copying ``area`` about ``height`` px tall (the area's full height when it isn't taller), then
    call ``then(new_window)`` (now or from a timer). Returns True when a window is (being) made."""
    from ..operators.menu_extras import open_window
    if bpy.app.background or area is None:
        return False
    full = area.height
    if height >= full - MIN_KEEP_PX:
        with context.temp_override(window=window):
            new = open_window(bpy.context, area)
        if new is None:
            return False
        then(new)
        return True
    screen = window.screen
    before = {a.as_pointer() for a in screen.areas}
    factor = 1.0 - height / max(full, 1)
    with context.temp_override(window=window, screen=screen, area=area):
        if bpy.ops.screen.area_split(direction='HORIZONTAL', factor=factor) != {'FINISHED'}:
            return False
    piece_ptr = next((a.as_pointer() for a in screen.areas if a.as_pointer() not in before), None)
    if piece_ptr is None:
        return False
    state = {"n": tries}
    win_ptr = window.as_pointer()

    def tick():
        try:
            wm = bpy.context.window_manager
            win = next((w for w in wm.windows if w.as_pointer() == win_ptr), None)
            if win is None:
                return None
            piece = next((a for a in win.screen.areas if a.as_pointer() == piece_ptr), None)
            if piece is None:
                return None
            if piece.height <= 1 and state["n"] > 0:    # the screen hasn't refreshed the split yet
                state["n"] -= 1
                return 0.02
            with bpy.context.temp_override(window=win):
                new = open_window(bpy.context, piece)
            close_area(bpy.context, win, piece)          # the source gets its height back
            if new is not None:
                then(new)
        except ReferenceError:
            pass
        return None
    bpy.app.timers.register(tick, first_interval=0.02)
    return True


def dock(context, window=None):
    """Put the floating panel in ``window`` back into the main window's layout and close the window."""
    window = window or context.window
    area = window.screen.areas[0] if window and window.screen.areas else None
    if area is None:
        return False
    r = role(area)
    main = main_window(context.window_manager)
    main_ptr = live_refs.pointer(main)
    if r == 'MENU':
        _torn_menus.pop(window.as_pointer(), None)
    elif r in KINDS:
        close_window_later(window)

        def back():
            main = live_refs.window(main_ptr)
            try:
                bpy.context.window_manager.allset_dock = r
                if main is not None:
                    with bpy.context.temp_override(window=main):
                        open_stack(bpy.context, main)
                redraw()
            except ReferenceError:
                pass
            return None
        bpy.app.timers.register(back, first_interval=0.05)
        return True
    else:
        from . import tool_dock
        kind = 'TOOL_SETTINGS' if tool_dock.is_dock(area) else ('OUTLINER' if area.type == 'OUTLINER' else None)
        if kind is None or main is None:
            return False
        close_window_later(window)
        if kind == 'TOOL_SETTINGS':
            tool_dock.set_docked(True)          # it opens docked again next time, like a docked Maya panel

        def back():
            main = live_refs.window(main_ptr)
            if main is None:
                return None
            try:
                with bpy.context.temp_override(window=main):
                    if kind == 'TOOL_SETTINGS':
                        tool_dock.open_dock(bpy.context, main)
                    elif not any(a.type == 'OUTLINER' for a in main.screen.areas):
                        from . import maya_outliner
                        split_side(bpy.context, main, 'LEFT', WIDTH, 'OUTLINER',
                                   then=lambda new: maya_outliner.setup(new.spaces.active))
            except ReferenceError:
                pass
            return None
        bpy.app.timers.register(back, first_interval=0.05)
        return True
    close_window_later(window)
    return True


def close_floating():
    """Switch to Blender: close windows whose only area is a kit role or the Tool Settings (they would show Blender's
    Tool tab)."""
    from . import tool_dock
    wm = bpy.context.window_manager
    for window in list(wm.windows):
        if is_floating(window, wm) and (role(window.screen.areas[0]) is not None
                                        or tool_dock.is_dock(window.screen.areas[0])):
            close_window_later(window)
    _torn_menus.clear()
