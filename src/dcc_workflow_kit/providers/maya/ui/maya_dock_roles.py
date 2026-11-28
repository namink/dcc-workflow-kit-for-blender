# SPDX-License-Identifier: GPL-3.0-or-later
"""Which Maya panel a dock area shows: the role kept in a Properties editor's hidden tab flags (``ROLE_FLAGS``,
``role``, ``set_role`` / ``set_role_later``), the tab stack's tabs and selected tab (``stack_tabs``, ``current_tab``,
``find_stack``), floating panels (``is_floating``, ``floating_kinds``) and what shows anywhere (``kind_visible``,
``visible_kinds``). Also ``redraw`` (every Properties area) and the torn-off menu ids. Used by the other maya_dock_*
modules; maya_dock.py re-exports these names.
"""

import bpy

from .. import live_refs

KINDS = ('CHANNEL_BOX', 'ATTRIBUTE_EDITOR', 'MODELING_TOOLKIT', 'TOOL_SETTINGS')   # the right dock's panels
LABELS = {'CHANNEL_BOX': "Channel Box / Layer Editor", 'ATTRIBUTE_EDITOR': "Attribute Editor",
          'MODELING_TOOLKIT': "Modeling Toolkit", 'TOOL_SETTINGS': "Tool Settings", 'OUTLINER': "Outliner"}
# Role marker = Tool tab + exactly one of these hidden tab flags (invisible: the tab column is hidden).
ROLE_FLAGS = {'STACK': "show_properties_world", 'CHANNEL_BOX': "show_properties_physics",
              'ATTRIBUTE_EDITOR': "show_properties_effects", 'MODELING_TOOLKIT': "show_properties_particles",
              'TOOL_SETTINGS': "show_properties_constraints",
              'MENU': "show_properties_texture"}
WIDTH = 260                  # unscaled px: Maya-style narrow panels

_torn_menus = {}             # window pointer -> (menu idname, label)
_pending = {}                # area pointer -> role it waits for (a new Properties space has no tab list yet)


# --- roles ---------------------------------------------------------------------------------------------------------

def _flags(space):
    from . import marked_window      # the tab flags of the space's type, read once
    return marked_window._flag_names(space)[0]


_MARK_FLAGS = {}      # space class -> its tab flags that can mark a kind (fixed per space type)


def _mark_flags(space):
    """``marked_window._flag_names(space)[1]`` kept per space class: ``role`` runs dozens of times per dock redraw
    (panel polls, the tab list of every area) and reading the space's RNA description each time was most of it."""
    flags = _MARK_FLAGS.get(type(space))
    if flags is None:
        from . import marked_window
        flags = _MARK_FLAGS[type(space)] = marked_window._flag_names(space)[1]
    return flags


def role(area):
    """'STACK' / a KINDS member / 'MENU' for a kit dock area, else None (the Tool Settings dock has no role)."""
    if area is None or area.type != 'PROPERTIES':
        return None
    space = area.spaces.active
    if space.show_region_header or not space.show_properties_tool:
        return None
    on = [name for name, flag in ROLE_FLAGS.items() if getattr(space, flag, False)]
    if len(on) != 1:
        return None
    keep = ("show_properties_tool", ROLE_FLAGS[on[0]])
    if any(getattr(space, f) for f in _mark_flags(space) if f not in keep):
        return None
    return on[0]


def set_role(area, name, window=None):
    """Make ``area`` (a Properties editor) a kit dock area with role ``name``. True when done; a space that hasn't
    drawn yet can't take the Tool tab, so callers retry (``set_role_later``)."""
    space = area.spaces.active
    try:
        space.context = 'TOOL'
    except TypeError:
        return False
    for flag in _flags(space):
        setattr(space, flag, flag == "show_properties_tool" or flag == ROLE_FLAGS.get(name))
    space.show_region_header = False
    nav = next((r for r in area.regions if r.type == 'NAVIGATION_BAR'), None)
    if nav is not None and nav.width > 1 and window is not None and not bpy.app.background:
        try:
            with bpy.context.temp_override(window=window, area=area):
                bpy.ops.screen.region_toggle(region_type='NAVIGATION_BAR')
        except (RuntimeError, TypeError):
            pass
    area.tag_redraw()
    return True


def set_role_later(area, name, window=None, tries=40):
    if set_role(area, name, window):
        return
    key = area.as_pointer()
    win_ptr = live_refs.pointer(window)
    _pending[key] = name
    state = {"n": tries}

    def tick():
        # pointers, looked up each tick: a closed window's area must not be touched (#36)
        win, area_ = live_refs.find_area(key, win_ptr or None)
        try:
            if area_ is None:
                done = True
            elif win_ptr:
                with bpy.context.temp_override(window=win):
                    done = set_role(area_, name, win)
            else:
                done = set_role(area_, name, None)
        except ReferenceError:
            done = True
        state["n"] -= 1
        if done or state["n"] <= 0:
            _pending.pop(key, None)
            return None
        return 0.05
    bpy.app.timers.register(tick, first_interval=0.0)


def area_role(context):
    return role(getattr(context, "area", None))


def is_floating(window, wm=None):
    """A window holding a single area (Maya's floating panel), not the first window."""
    wm = wm or bpy.context.window_manager
    return window is not None and len(window.screen.areas) == 1 and wm.windows[0] != window


# --- stack ---------------------------------------------------------------------------------------------------------

def floating_kinds(wm=None):
    wm = wm or bpy.context.window_manager
    out = set()
    for window in wm.windows:
        for area in window.screen.areas:
            r = role(area)
            if r in KINDS:
                out.add(r)
    return out


def tab_kinds():
    """The panels the tab stack can show: Tool Settings only with the Tool Settings Tab preference (off: the kit's
    Tool Settings window or dock, ``tool_dock``)."""
    from .. import preferences
    if preferences.get().tool_settings_tab:
        return KINDS
    return tuple(k for k in KINDS if k != 'TOOL_SETTINGS')


def stack_tabs(wm=None):
    floating = floating_kinds(wm)
    return [k for k in tab_kinds() if k not in floating]


def current_tab(wm=None):
    wm = wm or bpy.context.window_manager
    tabs = stack_tabs(wm)
    want = getattr(wm, "allset_dock", 'CHANNEL_BOX')
    return want if want in tabs else (tabs[0] if tabs else None)


def shown_kind(context):
    """The Maya panel this dock area shows (None: nothing)."""
    r = area_role(context)
    if r == 'STACK':
        return current_tab(context.window_manager)
    return r


def find_stack(screen):
    """The tab-stack area of ``screen`` (also one made this tick whose role is still pending)."""
    return next((a for a in (screen.areas if screen else ())
                 if role(a) == 'STACK' or _pending.get(a.as_pointer()) == 'STACK'), None)


def kind_visible(wm, kind):
    """The panel shows somewhere: the selected tab of a stack, or a floating window of its own."""
    if kind in floating_kinds(wm):
        return True
    if current_tab(wm) != kind:
        return False
    return any(find_stack(w.screen) is not None for w in wm.windows)


def visible_kinds(wm=None):
    """The kinds ``kind_visible`` is True for, from one look at the windows (the Status Line asks for each of its
    editor toggles on every redraw)."""
    wm = wm or bpy.context.window_manager
    floating = floating_kinds(wm)
    tabs = [k for k in tab_kinds() if k not in floating]
    want = getattr(wm, "allset_dock", 'CHANNEL_BOX')
    current = want if want in tabs else (tabs[0] if tabs else None)
    out = set(floating)
    if current is not None and any(find_stack(w.screen) is not None for w in wm.windows):
        out.add(current)
    return out


def redraw():
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'PROPERTIES':
                    area.tag_redraw()
    except (AttributeError, ReferenceError):
        pass
