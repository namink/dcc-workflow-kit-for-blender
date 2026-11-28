# SPDX-License-Identifier: GPL-3.0-or-later
"""The Hypershade window's areas: panes are Properties editors marked by hidden tab flags (``MARK`` +
``PANE_FLAGS``; ``pane``, ``context_pane``, ``set_pane``), the Graph and the menu strip are its Shader Editors
(``graph_area``, ``menu_area``), ``is_hypershade`` / ``hypershade_windows`` find the windows, and ``build_later``
splits a new window into the layout one step per timer tick (the proportions are hypershade_layout.py).
"""

import bpy

from .. import compat, live_refs
from . import hypershade_layout

HS = "Hypershade"


# --- the Hypershade window: panes, menu strip, Graph ---------------------------------------------------------
# A pane = a Properties editor on the Tool tab (header hidden) with both MARK flags and one PANE_FLAGS flag. Two of
# maya_dock's role flags make ``maya_dock_roles.role`` None and ``tool_dock.is_dock`` False, so neither the Maya dock panel
# nor Tool Settings draw there; the flags are saved with the file and copied by ``area_dupli``.
MARK = ("show_properties_world", "show_properties_texture")
PANE_FLAGS = {"BROWSER": "show_properties_render", "CREATE": "show_properties_output",
              "VIEWER": "show_properties_view_layer", "PROPERTY": "show_properties_scene"}
PANE_LABELS = {"BROWSER": "Browser", "CREATE": "Create", "VIEWER": "Material Viewer", "PROPERTY": "Property Editor"}


def _flags(space):
    return [p.identifier for p in space.bl_rna.properties if p.identifier.startswith("show_properties_")]


def pane(area):
    """'BROWSER' / 'CREATE' / 'VIEWER' / 'PROPERTY' for a Hypershade pane, else None."""
    if area is None or area.type != 'PROPERTIES':
        return None
    space = area.spaces.active
    if space.show_region_header or not space.show_properties_tool or not all(getattr(space, f) for f in MARK):
        return None
    on = [name for name, flag in PANE_FLAGS.items() if getattr(space, flag, False)]
    if len(on) != 1:
        return None
    allowed = {"show_properties_tool", *MARK, PANE_FLAGS[on[0]], *compat.LATER_PROPERTIES_TABS}
    if any(getattr(space, f) for f in _flags(space) if f not in allowed):
        return None
    return on[0]


def context_pane(context):
    return pane(getattr(context, "area", None))


def set_pane(area, name, window=None):
    """Make the Properties editor ``area`` the Hypershade pane ``name``. False while its space can't take the Tool
    tab yet (a new Properties space has an empty tab list until it has drawn: retry next tick)."""
    space = area.spaces.active
    try:
        space.context = 'TOOL'
    except TypeError:
        return False
    for flag in _flags(space):
        setattr(space, flag, flag in ("show_properties_tool", *MARK, PANE_FLAGS[name]))
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


def is_hypershade(screen):
    try:
        return screen is not None and any(pane(a) is not None for a in screen.areas)
    except ReferenceError:
        return False


def _node_areas(screen):
    return [a for a in screen.areas if a.type == 'NODE_EDITOR' and a.ui_type == 'ShaderNodeTree']


def graph_area(screen):
    """The Hypershade Graph of ``screen`` (its tallest Shader Editor), else None."""
    if not is_hypershade(screen):
        return None
    areas = _node_areas(screen)
    return max(areas, key=lambda a: a.height, default=None)


def menu_area(screen):
    """The Hypershade menu strip of ``screen`` (its lowest Shader Editor when there are two or more), else None."""
    if not is_hypershade(screen):
        return None
    areas = _node_areas(screen)
    if len(areas) < 2:
        return None
    return min(areas, key=lambda a: a.height)


def hypershade_windows(wm=None):
    wm = wm or bpy.context.window_manager
    return [w for w in wm.windows if is_hypershade(w.screen)]


def _largest_area(context):
    return max(context.window.screen.areas, key=lambda a: a.width * a.height, default=None)


def _header_px(area):
    """Height for the menu strip: a header (Blender's HEADERY = 26 px x UI scale) plus the area border; an area
    shorter than its header collapses the header to 1 px and shows the main region instead."""
    header = next((r for r in area.regions if r.type == 'HEADER'), None)
    scale = bpy.context.preferences.system.ui_scale or 1.0
    h = header.height if header is not None and header.height > 1 else round(26 * scale)
    return max(h, round(26 * scale)) + 3


def build_later(window, graph, tries=200):
    """Split ``window`` (its only area ``graph``, a Shader Editor) into Maya's Hypershade layout, one split per tick
    (area rects update one tick after a split), then turn the panes into Properties editors and mark them. Window and
    areas are kept as pointers (live_refs, #36)."""
    win_ptr = window.as_pointer()
    roles = {"GRAPH": graph.as_pointer()}
    state = {"steps": None, "i": 0, "n": tries, "typed": False}

    def area_of(role):
        return live_refs.area(roles.get(role), win_ptr)

    def tick():
        win = live_refs.window(win_ptr)
        state["n"] -= 1
        if win is None or state["n"] <= 0:
            return None
        try:
            return _tick(win)
        except ReferenceError:
            return None

    def _tick(win):
        screen = win.screen
        if state["steps"] is None:
            g = area_of("GRAPH")
            if g is None:
                return None
            if g.height <= 1 or g.width <= 1:
                return 0.02
            state["steps"] = hypershade_layout.plan(g.height, _header_px(g))
        steps = state["steps"]
        if state["i"] < len(steps):
            src, direction, factor, new = steps[state["i"]]
            area = area_of(src)
            if area is None:
                return None
            if area.width <= 1 or area.height <= 1:
                return 0.02
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            before = {a.as_pointer() for a in screen.areas}
            with bpy.context.temp_override(window=win, screen=screen, area=area, region=region):
                bpy.ops.screen.area_split(direction=direction, factor=factor)
            made = next((a for a in screen.areas if a.as_pointer() not in before), None)
            if made is None:
                return 0.02
            roles[new] = made.as_pointer()
            state["i"] += 1
            return 0.02
        if not state["typed"]:
            for role in ("MENU", "GRAPH"):
                a = area_of(role)
                if a is not None:
                    sp = a.spaces.active
                    sp.show_region_toolbar = False
                    sp.show_region_ui = False
            for role in PANE_FLAGS:
                a = area_of(role)
                if a is not None:
                    a.ui_type = 'PROPERTIES'
            state["typed"] = True
            return 0.02
        done = True
        for role in PANE_FLAGS:
            a = area_of(role)
            if a is not None and pane(a) != role:
                with bpy.context.temp_override(window=win):
                    done = set_pane(a, role, win) and done
        if not done:
            return 0.05
        for a in screen.areas:
            a.tag_redraw()
        return None
    bpy.app.timers.register(tick, first_interval=0.0)
