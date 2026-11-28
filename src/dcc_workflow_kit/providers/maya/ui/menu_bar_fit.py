# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's menu bar overflow: how many menus fit the top bar (``menu_fit``, ``menu_bar_widths``), the bar drawn with a
» button for the rest (``draw_menu_bar_fit``) and that button's menu (``ALLSET_MT_menu_more``); ``shown_menus``
tells what the bar showed. Related: status_line.py (``draw_left``, registration), menu_sets.py, option_click.py.
"""

import bpy

from . import menu_sets, status_icons


# --- menu bar overflow (#77) -------------------------------------------------------------------------
# Maya hides the menus that don't fit behind a » button at the menu bar's right end; the
# kit's bar ran under the Workspace field instead ("Deform U", GUI shot at UI scale 1.5). Same pattern as the panel
# toolbar's » (#52, ui/panel_toolbar.py): Blender's header layout can't report where it put an item, so the
# widths follow its layout rules (toolbar_fit.unit; a ``ui_units_x = k`` sub-row is floor(k U) wide).
MENU_LEAD_UNITS = 0.4    # the header region's left padding
LOGO_UNITS = 1.6         # the Blender logo pulldown (icon only)
MENU_SET_UNITS = 5.5     # the menu set dropdown (= menu_sets.draw_menu_bar)
MENU_MORE_UNITS = 1.5    # the » button
MENU_SLACK_UNITS = 0.5   # kept free before the right-hand region
_menus_shown = {}        # window pointer -> (menu names in bar order, how many the bar shows)


def menu_fit(widths, width, fixed, more):
    """How many leading menus (px ``widths``) the bar shows in ``width`` px after ``fixed`` px; when they don't all
    fit, the » button (``more`` px) takes its place at the end."""
    if fixed + sum(widths) <= width:
        return len(widths)
    return fit_beside_more(widths, width, fixed, more)


def fit_beside_more(widths, width, fixed, more):
    """How many leading menus fit in ``width`` px next to the » button."""
    x = fixed + more
    n = 0
    for w in widths:
        if x + w > width:
            break
        x += w
        n += 1
    return n


def _menu_units(context, names):
    """{menu idname: ``menu_sets.menu_width_units`` of its label} for the menus of ``names``."""
    out = {}
    for name in names:
        idname = menu_sets.menu_idname(name)
        cls = getattr(bpy.types, idname, None)
        out[idname] = menu_sets.menu_width_units(cls.bl_label if cls is not None else name, context)
    return out


def menu_bar_widths(context, names, menu_set, units=None):
    """(px width of each menu of ``names``, fixed px: padding, logo, menu set dropdown, slack, » button).
    ``units``: ``_menu_units(context, names)`` already worked out."""
    from .toolbar_fit import unit
    system = context.preferences.system
    u = unit(system.ui_scale or 1.0, system.pixel_size)
    if units is None:
        units = _menu_units(context, names)
    widths = [int(units[menu_sets.menu_idname(name)] * u) for name in names]
    fixed = int((MENU_LEAD_UNITS + LOGO_UNITS + MENU_SLACK_UNITS) * u) + (int(MENU_SET_UNITS * u) if menu_set else 0)
    return widths, fixed, int(MENU_MORE_UNITS * u)


def shown_menus(window):
    """(menu names, how many the menu bar of ``window`` showed when it was last drawn)."""
    return _menus_shown.get(window.as_pointer(), ((), 0)) if window is not None else ((), 0)


def _menu_set_field(layout, prefs):
    sub = layout.row()
    sub.ui_units_x = MENU_SET_UNITS
    sub.prop(prefs, "menu_set", text="")


def draw_menu_bar_fit(layout, context, menu_set=True):
    """``menu_sets.draw_menu_bar`` when every menu fits the region, else the menus that fit and Maya's » overflow."""
    from .. import preferences
    prefs = preferences.get(context)
    names = menu_sets.menus_for_set(prefs.menu_set)
    region = getattr(context, "region", None)
    units = _menu_units(context, names)     # once: the widths below and the menus drawn use them
    widths, fixed, more = menu_bar_widths(context, names, menu_set, units)
    width = region.width if region is not None and region.width > 1 else None
    # other add-ons' top-bar menus follow the Maya menus when there is room for them, else they wait behind »
    funcs = menu_sets.addon_menu_funcs(context)
    reserve = menu_sets.addon_menus_width(context, funcs) if funcs else 0
    inline = width is None or fixed + sum(widths) + reserve <= width
    n = len(names) if inline else menu_fit(widths, width, fixed, more)
    if not inline and n >= len(names):     # the Maya menus fit: only the add-on menus go behind »
        n = fit_beside_more(widths, width, fixed, more)
    if context.window is not None:
        _menus_shown[context.window.as_pointer()] = (tuple(names), n)
    if inline:
        menu_sets.draw_menu_bar(layout, context, menu_set=menu_set, units=units)
        return
    layout.menu("TOPBAR_MT_blender", text="", icon='BLENDER')
    common = len(menu_sets._SET_MENUS[menu_sets.COMMON_SET])    # the menu set dropdown follows these
    for i, name in enumerate(names[:n]):
        idname = menu_sets.menu_idname(name)
        sub = layout.row(align=True)
        sub.ui_units_x = units[idname]
        sub.menu(idname)
        if menu_set and i == common - 1:
            _menu_set_field(layout, prefs)
    if menu_set and n < common:
        _menu_set_field(layout, prefs)
    sub = layout.row(align=True)
    sub.ui_units_x = MENU_MORE_UNITS
    icon = status_icons.icon("pt_more") if "pt_more" in status_icons.EXTRA else 0
    if icon:
        sub.menu(ALLSET_MT_menu_more.bl_idname, text="", icon_value=icon)
    else:
        sub.menu(ALLSET_MT_menu_more.bl_idname, text="\u00bb")


class ALLSET_MT_menu_more(bpy.types.Menu):
    """More Maya menus: the ones that don't fit the menu bar"""
    bl_idname = "ALLSET_MT_menu_more"
    bl_label = "More Menus"

    def draw(self, context):
        names, n = shown_menus(context.window)
        for name in names[n:]:
            self.layout.menu(menu_sets.menu_idname(name))
        if menu_sets.addon_menu_funcs(context):     # other add-ons' top-bar menus, at the end
            if n < len(names):
                self.layout.separator()
            menu_sets.draw_addon_menus(self.layout, context)
