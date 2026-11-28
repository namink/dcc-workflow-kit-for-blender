# SPDX-License-Identifier: GPL-3.0-or-later
"""Fits the kit layout to the UI scale and window size, only within ``FIT_WINDOW`` seconds of a load / scale change:
Tool Box column, Outliner, shelf row, Status Line row, Time Slider and the right tab stack (``dock_width``,
``tab_changed``). ``fit_columns`` runs from a timer and after load; when ``screen.area_move`` can't poll,
``allset.fit_columns`` puts the cursor on the area edge for a moment. Registered by ``toolbox``.
(Not ui/toolbar_fit.py: header overflow.)"""

import math

import bpy

from .. import switch
from .toolbox_column import GAP_PX, OUTLINER_PX, column_width, is_toolbox, settle

SHELF_PX = 64        # = tools/make_startup.py SHELF_PX
TIME_SLIDER_PX = 36  # = tools/make_startup.py TIME_SLIDER_PX (the Time Slider ruler at scale 1)


def time_slider_area(screen):
    """The Maya Workflow Kit layout's Time Slider: a Timeline with its sidebar shown (Blender 5.x opens the
    template's sidebar 1 px wide and the Time Slider buttons sit in the header; it is the Time Slider all the same)."""
    from .time_slider import has_slider_panel
    return next((a for a in screen.areas if a.type == 'DOPESHEET_EDITOR' and a.ui_type == 'TIMELINE'
                 and has_slider_panel(a.spaces.active)), None)


# Blender 5.x snaps a moved horizontal edge to the height "header + time scrub strip" (23 px x the UI scale) of an
# animation editor below it whenever the edge lands within 0.6 header heights of that height, and keeps edge
# positions on a 4 px grid (Blender's screen.area_move, also from Python). The Time Slider's ruler of
# TIME_SLIDER_PX x the scale always lies in that band, so moving its top edge there snapped back and the Time Slider
# kept the template's height (a 29 px ruler at UI 1.25, 2 px at 2.0). The fit takes the nearest height outside the
# band instead.
AREA_GRID = 4
TIME_SCRUB_PX = 23


def time_slider_goal(scale, hdr):
    """Area height the fit gives the Time Slider whose header is ``hdr`` px at UI ``scale``: its ruler
    TIME_SLIDER_PX x scale over the header, or the nearest height above Blender's edge snap band around
    "header + time scrub strip" when that height lies in it."""
    want = round(TIME_SLIDER_PX * scale) + hdr
    snap = hdr + int(TIME_SCRUB_PX * scale)
    band = int(hdr * 0.6)
    if abs(want - snap) < band + AREA_GRID:
        want = snap + band + AREA_GRID
    return want
_FIT_TICK = 0.5
_fallback = set()   # screens whose main view shows its toolbar because the column is too narrow


# The right tab stack (ui/maya_dock.py STACK area, #60, #78): 280 px with the Channel Box raised (a 260 px
# panel + the vertical tab strip; = tools/make_startup.py's old DOCK_PX 260 + 17), 480 px with the Attribute Editor
# raised (the AE is a wide panel). The kit's tabs are a Maya-style
# vertical strip too (maya_dock_strip.draw_strip), so the stack is as wide as the raised panel needs: the Channel Box / Modeling
# Toolkit stack at least 277 px x the scale (wider when the Channel Box labels need it), the Attribute Editor
# stack 480 px x the scale (Maya resizes the stack when its tab changes, ``tab_changed``).
DOCK_MAYA_PX = 277
DOCK_MAX_PX = 480
WIDE_KINDS = ('ATTRIBUTE_EDITOR', 'TOOL_SETTINGS')   # wide panels (460 px by default)
# the main viewport keeps at least this (x UI scale) after the Tool Box column and Outliner are fitted too: a 1600 px
# window at UI scale 1.5 keeps a 439 px viewport
MIN_VIEW_PX = 280
# the longest channel labels the Channel Box shows by default (polyCube / polyCylinder / polySphere INPUTS)
LONG_LABELS = ("Subdivisions Height", "Subdivisions Width", "Subdivisions Depth", "Subdivisions Axis",
               "Subdivisions Caps")
FONT_PT = 11         # Blender's widget font (Preferences > Interface > Text Rendering: ui_styles[0].widget.points)


def _unit(scale, pixel_size=1.0):
    """Blender's widget unit UI_UNIT_X in px (= toolbar_fit.unit)."""
    from .toolbar_fit import unit
    return unit(scale, pixel_size)


def text_px(text, scale):
    """Width of ``text`` in the UI font at ``scale`` (blf; about 7 px a character when blf can't measure)."""
    try:
        import blf
        blf.size(0, FONT_PT * scale)
        w = blf.dimensions(0, text)[0]
        if w > 0:
            return w
    except Exception:
        pass
    return len(text) * 7 * scale


def dock_need(scale, pixel_size=1.0, measure=text_px):
    """{"labels", "ae_menu"}: px the tab stack needs at ``scale`` so the Channel Box labels aren't truncated and the
    AE menu bar is one row, both left of the vertical tab strip (``maya_dock_strip.reserved_px``)."""
    from . import attribute_editor, maya_dock
    u = _unit(scale, pixel_size)
    strip = maya_dock.reserved_px(scale)
    label = max(measure(t, scale) for t in LONG_LABELS)
    # the label column is half the content column (the panel margin 0.8 U each side of it)
    labels = 2 * (label + 0.8 * u) + 0.8 * u + strip
    # = attribute_editor.fits: the width at which the AE menu bar is drawn on one row
    ae = (sum(len(text) * 7 + 14 for text, _m in attribute_editor.MENU_BAR) + 20) * scale + strip
    return {"labels": math.ceil(labels), "ae_menu": math.ceil(ae)}


def dock_width(scale, pixel_size=1.0, measure=text_px, kind='CHANNEL_BOX'):
    """The tab stack width at ``scale`` with ``kind`` raised: Maya's Attribute Editor stack for the AE (at least its
    one-row menu bar), else what the Channel Box needs, at least Maya's Channel Box stack (never above the AE's)."""
    need = dock_need(scale, pixel_size, measure)
    top = round(DOCK_MAX_PX * scale)
    if kind in WIDE_KINDS:
        return max(top, need["ae_menu"])
    return min(top, max(round(DOCK_MAYA_PX * scale), need["labels"]))


MAX_WARPS = 3        # cursor-warp fits per screen and file load
_warps = {}          # screen name -> fits started since the last load
_running = [False]
# #53: the fit only resizes a layout as it was loaded (or as it was when the UI scale changed). A move whose poll
# failed used to wait and run the first time the poll passed: right after the next area split (a split clears
# screen.active_region), so opening the Tool Settings dock at UI scale 1.25 moved the Outliner edge 45 px into it
# and closing the dock left the viewport 45 px narrower; later it also
# undid the user's own Outliner / shelf row sizes whenever the mouse crossed an area gap.
_state = {}          # screen name -> [ui scale, area pointers, armed, monotonic time armed]
# #155: a fit that could not run at once (no cursor warp, the mouse over a region) waited
# and ran at the next area split mid-session — after Four View or a dialog the shelf row, Outliner, Channel Box and
# Time Slider jumped under the pointer. The fit is a load-time adjustment: it only runs within FIT_WINDOW seconds
# of the screen being loaded / first seen / the UI scale changing.
FIT_WINDOW = 3.0
# #334: a cursor-warp fit never starts while a window is being dragged or resized. On Windows a pointer warp during a
# title-bar drag moves the dragged window with it, and a window dragged onto a monitor with other display scaling
# changes its UI scale, which arms the fit. The warp waits until every window's place, size and own UI scale are
# what the previous fit tick saw; until then FIT_WINDOW counts from now.
_still = {"snap": None}
# #334: Blender keeps one UI scale for all its windows and sets it to a window's own (the display scaling of the
# monitor the window is on) each time that window is drawn or moved. With windows on monitors of different scaling, a
# timer reads the scale of whichever window was drawn last: a Graph Editor window on a 100 % monitor made the fit
# resize the Maya layout of the main window on a 125 % monitor for 100 % (and back once the main window drew again),
# warping the pointer to the main window for it. Each window's own scale is taken when it draws its 3D View toolbar
# (the Tool Box column; ``note_scale``), and the fit leaves a window alone while the scale is another window's.
_drawn = {}          # window pointer -> (UI scale, pixel size) at its last toolbar draw


def note_scale(context):
    """Called while a window draws a 3D View toolbar: remember that window's own UI scale."""
    window = context.window
    if window is not None:
        system = context.preferences.system
        _drawn[window.as_pointer()] = (system.ui_scale, system.pixel_size)


def _scale_is_own(window, system):
    """False while Blender's UI scale is not the one ``window`` last drew with (another window on a monitor with
    other display scaling drew after it). A window that never drew a toolbar counts as current."""
    own = _drawn.get(window.as_pointer())
    return own is None or own == (system.ui_scale, system.pixel_size)


def _windows_still(context):
    """True when the place, size and own UI scale of every window seen by the previous call (a fit tick) are
    unchanged (a window that opened or closed meanwhile doesn't count)."""
    windows = {w.as_pointer(): w for w in context.window_manager.windows}
    for ptr in [p for p in _drawn if p not in windows]:     # closed (a new window may reuse the pointer)
        del _drawn[ptr]
    snap = {ptr: (w.x, w.y, w.width, w.height, _drawn.get(ptr)) for ptr, w in windows.items()}
    prev = _still["snap"]
    _still["snap"] = snap
    if prev is None:
        return True
    return all(prev[ptr] == rect for ptr, rect in snap.items() if ptr in prev)


def _armed(screen, scale):
    """True while ``screen`` may still be fitted: same areas as when it was first seen / loaded / the UI scale
    changed, not fitted yet and within FIT_WINDOW seconds of that. Once its areas change (split, close, dock,
    tear-off) it stays off for this scale."""
    import time
    # the viewport panels don't count — the four view (ui/four_view.py) splits / joins them without
    # touching the columns
    areas = frozenset(a.as_pointer() for a in screen.areas
                      if not (a.type == 'VIEW_3D' and not is_toolbox(a.spaces.active)))
    state = _state.get(screen.name)
    now = time.monotonic()
    if state is None or state[0] != scale:
        _state[screen.name] = [scale, areas, True, now]
        return True
    if state[2] and (state[1] != areas or now - state[3] > FIT_WINDOW):
        state[2] = False
    return state[2]


_sizes = {}          # window pointer -> [(width, height), monotonic time the size last changed]


def _resized(window):
    """True within FIT_WINDOW seconds of a change of the window's size (#305): Blender scales every area with the
    window, so the one-header Status Line row and the shelf row grow with it and leave empty strips."""
    import time
    now = time.monotonic()
    size = (window.width, window.height)
    rec = _sizes.get(window.as_pointer())
    if rec is None:
        _sizes[window.as_pointer()] = [size, -math.inf]     # first seen: the load-time fit covers it
        return False
    if rec[0] != size:
        rec[0], rec[1] = size, now
        _warps.clear()        # a new size may use its own cursor-warp fits
    return now - rec[1] <= FIT_WINDOW


def _disarm(screen):
    state = _state.get(screen.name)
    if state is not None:
        state[2] = False


def _move_edge(window, area, x, y, delta, edge, pending):
    """Move the edge through (x, y) by ``delta``; when the poll fails, remember ``edge`` (a window point in the
    gap between the areas) for ALLSET_OT_fit_columns."""
    with bpy.context.temp_override(window=window, screen=window.screen, area=area):
        if not bpy.ops.screen.area_move.poll():
            pending.setdefault(window.as_pointer(), (window, edge))
            return False
        return bpy.ops.screen.area_move(x=x, y=y, delta=delta) == {'FINISHED'}


def _dock_target(window, scale, pixel_size, kind):
    """(stack area, fitted width with ``kind`` raised) for the layout's stack right of the main viewport, or None
    (torn off, a user layout)."""
    from . import maya_dock
    from .status_line import main_view3d
    screen = window.screen
    dock = maya_dock.find_stack(screen)
    main, _r = main_view3d(screen)
    if dock is None or main is None or abs(main.x + main.width - dock.x) > GAP_PX or dock.x <= 2:
        return None
    want = dock_width(scale, pixel_size, kind=kind)
    # never squeeze the viewport below MIN_VIEW_PX once the column and Outliner left of it are fitted as well (a small
    # window keeps a narrower dock)
    left = 0
    column = next((a for a in screen.areas if a.type == 'VIEW_3D' and is_toolbox(a.spaces.active)), None)
    if column is not None:
        left += column_width() - column.width
        outl = next((a for a in screen.areas if a.type == 'OUTLINER' and abs(a.x - (column.x + column.width)) <= GAP_PX
                     and abs(a.x + a.width - main.x) <= GAP_PX), None)
        if outl is not None:
            left += round(OUTLINER_PX * scale) - outl.width
    return dock, min(want, dock.width + max(0, main.width - left - round(MIN_VIEW_PX * scale)))


def _fit_dock(window, scale, pixel_size, pending, kind=None):
    """Move the left edge of the Maya tab stack right of the main viewport to ``dock_width`` for the raised tab
    (#60, #78). True while it is off its fitted place (moved now or pending)."""
    from . import maya_dock
    target = _dock_target(window, scale, pixel_size, kind or maya_dock.current_tab())
    if target is None:
        return False
    dock, want = target
    if abs(dock.width - want) <= 2:
        return False
    y = dock.y + dock.height // 2
    _move_edge(window, dock, dock.x, y, dock.width - want, (dock.x - 1, y), pending)
    return True


# Maya resizes its tab stack when another tab is raised (280 px Channel Box, 480 px Attribute Editor; #78). The kit
# does the same once per tab change, only while the stack still has the kit's width for the tab it showed (a stack the
# user resized keeps its size) and only right away: the edge moves now when area_move polls, else through the cursor
# fit (ALLSET_OT_fit_columns) while ``_tab_target`` names the tab, never later (#53).
_tab_target = {}     # screen name -> kind the stack is being fitted to


def tab_changed(window, old, new):
    """The stack area of ``window`` drew ``new`` after ``old`` (maya_dock_strip.tab_drawn, called while drawing: the
    resize runs from a timer)."""
    if (old in WIDE_KINDS) == (new in WIDE_KINDS):
        return
    from .. import live_refs
    ptr = live_refs.pointer(window)

    def later():
        try:
            _tab_fit(live_refs.window(ptr), old, new)
        except Exception:
            import traceback
            traceback.print_exc()
        return None
    bpy.app.timers.register(later, first_interval=0.0)


def _tab_fit(window, old, new):
    """Resize the stack of ``window`` from the width for ``old`` to the width for ``new`` (see ``tab_changed``)."""
    if window is None or _running[0]:
        return
    context = bpy.context
    system = context.preferences.system
    if not _scale_is_own(window, system):
        return
    scale, pixel = system.ui_scale, system.pixel_size
    before = _dock_target(window, scale, pixel, old)
    if before is None or abs(before[0].width - before[1]) > 3:
        return            # not the layout's stack, or the user sized it
    pending = {}
    if not _fit_dock(window, scale, pixel, pending, new) or not pending or not auto_warp():
        return
    _tab_target[window.screen.name] = new
    _w, edge = pending[window.as_pointer()]
    with context.temp_override(window=window, screen=window.screen):
        bpy.ops.allset.fit_columns('INVOKE_DEFAULT', x=edge[0], y=edge[1])


def fit_columns(start_fit=True):
    """Tool Box column = one toolbar column at the current UI scale (or the main view's toolbar); the
    shelf row = 64 px times the UI scale. Returns {window pointer: (window, edge point)} of the moves whose
    poll failed; with ``start_fit`` a ALLSET_OT_fit_columns is started for the first of them."""
    from .status_line import main_view3d
    context = bpy.context
    still = _windows_still(context) if start_fit else True
    if not still:
        import time
        now = time.monotonic()
        for state in _state.values():      # armed fits wait: their window counts from when the windows stand still
            if state[2]:
                state[3] = now
    want = column_width(context)
    pending = {}
    from .shelf import shelf_row_area, strip_area
    scale = context.preferences.system.ui_scale
    for window in context.window_manager.windows:
        if not _scale_is_own(window, context.preferences.system):
            continue         # the scale is another window's now: fit this one at a tick where it is its own
        screen = window.screen
        loaded = _armed(screen, scale)
        resized = _resized(window)
        user = window.workspace is not None and switch.USER_KEY in window.workspace
        # a workspace the user saved keeps the sizes it was saved with
        armed = loaded and not user
        needed = False       # an edge of this screen is off its fitted place
        row = shelf_row_area(screen)
        if row is not None and row.spaces.active.show_region_header:
            # the shelf row draws its tab strip in the WINDOW region (layouts saved before carry a header)
            with context.temp_override(window=window, screen=screen, area=row):
                row.spaces.active.show_region_header = False
        # the Status Line row is one header high (#305): a taller one shows an empty strip above the shelf. Its
        # extra height goes to the viewport under the shelf row (the shelf row keeps its height).
        strip = strip_area(screen)
        strip_fitted = False
        if strip is not None and row is not None and (loaded or resized) \
                and 0 <= strip.y - (row.y + row.height) <= round(GAP_PX * max(scale, 1.0)):
            hdr = next((r.height for r in strip.regions if r.type == 'HEADER'), 0)
            extra = strip.height - hdr
            if hdr > 0 and extra > 1:
                needed = strip_fitted = True
                x = strip.x + strip.width // 2
                if _move_edge(window, strip, x, strip.y, extra, (x, strip.y - 1), pending):
                    _move_edge(window, row, x, row.y, extra, (x, row.y - 1), pending)
        # the Maya shelf row (tab row + icon row, 64 px at scale 1): grow it downwards
        if row is not None and not strip_fitted:
            d = round(SHELF_PX * scale) - row.height
            if abs(d) > 2 and (armed or (resized and not user)):
                needed = True
                _move_edge(window, row, row.x + row.width // 2, row.y, -d,
                           (row.x + row.width // 2, row.y - 1), pending)
        # the Time Slider (#109): its ruler keeps 36 px times the UI scale. The template area has a
        # fixed height, so at UI 1.25 the taller header left a 29 px ruler that Blender's current-frame box filled:
        # grow it upwards (to time_slider_goal: a height Blender's edge snap doesn't pull back)
        slider = time_slider_area(screen)
        if slider is not None:
            hdr = next((r.height for r in slider.regions if r.type == 'HEADER'), 0)
            off = abs(round(TIME_SLIDER_PX * scale) + hdr - slider.height) >= AREA_GRID
            d = time_slider_goal(scale, hdr) - slider.height if off else 0
            if abs(d) >= AREA_GRID and armed:
                needed = True
                top = slider.y + slider.height
                _move_edge(window, slider, slider.x + slider.width // 2, top, d,
                           (slider.x + slider.width // 2, top + 1), pending)
        tab = _tab_target.get(screen.name)
        if tab is not None:      # a tab-change resize under way (only while its cursor fit runs)
            if not _fit_dock(window, scale, context.preferences.system.pixel_size, pending, tab):
                _tab_target.pop(screen.name, None)
        elif armed and _fit_dock(window, scale, context.preferences.system.pixel_size, pending):
            needed = True
        column = next((a for a in screen.areas if a.type == 'VIEW_3D' and is_toolbox(a.spaces.active)), None)
        if column is None:
            if armed and not needed:
                _disarm(screen)
            continue
        if settle(column.spaces.active, context.preferences):
            column.tag_redraw()
        if not armed:
            pass
        elif abs(column.width - want) > 1 and column.x + column.width < window.width - 2:
            needed = True
            _move_edge(window, column, column.x + column.width, column.y + column.height // 2,
                       want - column.width, (column.x + column.width + 1, column.y + column.height // 2), pending)
        elif abs(column.width - want) <= 1:
            # the layout Outliner right of the column keeps Maya's panel width at this scale (widening the column
            # took its pixels)
            outl = next((a for a in screen.areas if a.type == 'OUTLINER' and abs(a.x - (column.x + column.width)) <= GAP_PX
                         and a.height >= column.height - 4), None)
            wo = round(OUTLINER_PX * scale)
            if outl is not None and abs(outl.width - wo) > 2 and outl.x + outl.width < window.width - 2:
                needed = True
                _move_edge(window, outl, outl.x + outl.width, outl.y + outl.height // 2, wo - outl.width,
                           (outl.x + outl.width + 1, outl.y + outl.height // 2), pending)
        if armed and not needed:
            _disarm(screen)      # fitted: the user's own edge moves stay
        narrow = column.width < want - 1
        main, _r = main_view3d(screen)
        if main is None or main == column:
            continue
        key = screen.name
        # The property update re-inits the area through the context window: a timer runs with the last active
        # window, which may just have been closed (crash in WM_window_get_active_workspace) — so set it
        # with this window in the context. Only the kit's own fallback is undone: a toolbar the user showed (T)
        # stays (PR #125 synced it to the column width every fit).
        if narrow and key not in _fallback and not main.spaces.active.show_region_toolbar:
            with context.temp_override(window=window, screen=screen, area=main):
                main.spaces.active.show_region_toolbar = True
            _fallback.add(key)
        elif not narrow and key in _fallback:
            with context.temp_override(window=window, screen=screen, area=main):
                main.spaces.active.show_region_toolbar = False
            _fallback.discard(key)
    if start_fit and still and pending and not _running[0] and auto_warp():
        window, edge = next(iter(pending.values()))
        key = window.screen.name
        if _warps.get(key, 0) < MAX_WARPS:
            _warps[key] = _warps.get(key, 0) + 1
            with context.temp_override(window=window, screen=window.screen):
                bpy.ops.allset.fit_columns('INVOKE_DEFAULT', x=edge[0], y=edge[1])
    return pending


def auto_warp():
    """The cursor fit runs by itself except in event-simulated sessions (GUI tests, dogfood): they own the mouse,
    and a warp in the middle of a scripted step closes its menus. ALLSET_FIT_WARP=1 turns it on there."""
    import os
    return not bpy.app.use_event_simulate or os.environ.get("ALLSET_FIT_WARP") == "1"


def _warp(window, x, y):
    window.cursor_warp(x, y)
    if bpy.app.use_event_simulate:   # event simulation drops the OS mouse move a warp makes
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)


class ALLSET_OT_fit_columns(bpy.types.Operator):
    """Resize the Tool Box column / shelf row: the cursor sits on the area edge (where screen.area_move polls)
    for a few timer ticks, then goes back"""
    bl_idname = "allset.fit_columns"
    bl_label = "Fit Maya Layout Columns"
    bl_options = {'INTERNAL'}

    x: bpy.props.IntProperty(options={'SKIP_SAVE'})
    y: bpy.props.IntProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self._back = (event.mouse_x, event.mouse_y)
        self._n = 0
        self._window = context.window
        self._at = (self.x, self.y)
        _warp(context.window, self.x, self.y)
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        _running[0] = True
        return {'RUNNING_MODAL'}

    def _finish(self, context, event):
        context.window_manager.event_timer_remove(self._timer)
        _running[0] = False
        _tab_target.clear()        # a tab-change fit is done or given up: never applied later (#53)
        if (event.mouse_x, event.mouse_y) == self._at:   # the user didn't move the mouse meanwhile
            _warp(self._window, *self._back)
        return {'FINISHED'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        self._n += 1
        try:
            left = fit_columns(start_fit=False)
        except Exception:
            left = {}
        item = left.get(self._window.as_pointer())
        if item is None or self._n > 24:
            return self._finish(context, event)
        if item[1] != self._at:   # the next edge (column, then Outliner, then shelf row)
            if (event.mouse_x, event.mouse_y) != self._at:   # the user moved the mouse: stop here
                return self._finish(context, event)
            self._at = item[1]
            _warp(self._window, *item[1])
        return {'PASS_THROUGH'}


def _fit_tick():
    try:
        fit_columns()
    except Exception:   # a timer that raises is dropped: keep it running
        pass
    return _FIT_TICK


@bpy.app.handlers.persistent
def _fit_after_load(*_args):
    _warps.clear()
    _state.clear()       # a loaded layout may be fitted again: its areas as loaded, before any split (#53)
    try:
        scale = bpy.context.preferences.system.ui_scale
        for window in bpy.context.window_manager.windows:
            _armed(window.screen, scale)
    except (AttributeError, ReferenceError):
        pass
    if not bpy.app.background:
        bpy.app.timers.register(lambda: _fit_tick() and None, first_interval=0.0)
