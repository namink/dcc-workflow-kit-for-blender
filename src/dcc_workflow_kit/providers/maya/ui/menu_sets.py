# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya main menu bar and menu sets (Modeling/Rigging/Animation/FX/Rendering).

Maya's menu sets: the common menus are always shown,
the menu set dropdown swaps the menus after them. Structure from
``menu_data`` (Maya's menu structure), Blender actions from
``menu_map``; unmapped items are drawn greyed out.

One ``Menu`` class per Maya menu and submenu is built from the data at import
time. ``menu_idname(maya_name)`` is the public name for other UI (hotbox).
This module: the menu classes (``_menu_classes``), the menu bar draw and its widths (``draw_menu_bar``,
``menu_width_units``) and registration. Menu sets and item paths: ``menu_tree``; item drawing: ``menu_item_draw``;
item operators: ``menu_item_ops``; option boxes: ``menu_option_box``; hotkey column: ``menu_item_text``; other
add-ons' top-bar menus: ``menu_bar_addons``.
"""

import bpy

from .. import compat, i18n  # noqa: F401  (compat also read through this module by tests)
from . import draw_safe, editor_menu_data, menu_data, menu_icons, menu_map, option_click
# the split-out parts, also read through this module by other UI and the tests
from .menu_bar_addons import (ADDON_MENU_UNITS, ALLSET_MT_addon_menus, addon_menu_funcs,  # noqa: F401
                              addon_menus_width, draw_addon_menus)
from .menu_item_draw import (_PROXY_CLASSES, _draw_boxed, _menu_targets, _proxies, draw_item,  # noqa: F401
                             draw_spec, register_proxies, unregister_proxies)
from .menu_item_ops import (COMPONENT_TWIN, ALLSET_OT_component_command, ALLSET_OT_menu_item,  # noqa: F401
                            ALLSET_OT_menu_run, ALLSET_OT_menu_set_value, ALLSET_OT_menu_tool,
                            ALLSET_OT_menu_unavailable, ALLSET_OT_menu_whole_mesh, _no_equivalent,
                            add_to_shelf_if_asked, op_polls, prop_owner, register_whole_mesh_options, set_prop,
                            unregister_whole_mesh_options)
from .menu_item_text import HAIR, font_size, hotkey, item_texts, text_width  # noqa: F401
from .menu_option_box import (BOX_TIP, HOLD_ROW_SCALE, LAST_WARP, ALLSET_MT_option_box,  # noqa: F401
                              ALLSET_OT_menu_option_box, ALLSET_OT_option_box_point, modifier_held, option_kind)
from .menu_tree import (BOX_MARK, COMMON_SET, DEFAULT_SET, OPTION_BOXES, SET_ITEMS, _ALWAYS_MENUS,  # noqa: F401
                        _SET_MENUS, children, current_set, editor_menu_idname, iter_items, menu_idname,
                        menus_for_set, sub_items)


def _dynamic_label(path, label):
    """The label a menu row shows, in the interface language. Maya labels built when the menu opens:
    Edit > Repeat = 'Repeat "<last command>"' (Maya Edit menu)."""
    if path == "Edit/Repeat":
        from ..operators import repeat_maya
        try:
            return repeat_maya.label(bpy.context)
        except (AttributeError, ReferenceError):
            pass
    return i18n.iface(label)


def menu_rows(items, prefix):
    """(path, item) rows of a Maya menu with each item's label as shown (``_dynamic_label``); separators as they
    are. Shared with ``option_click``, which models the drawn widths."""
    return [(path, ((_dynamic_label(path, it[0]),) + tuple(it[1:])) if path is not None else it)
            for path, it in children(items, prefix)]


def _draw_items(layout, items, prefix, submenus):
    kids = menu_rows(items, prefix)
    texts = item_texts([(path, it[0], path in OPTION_BOXES) for path, it in kids
                        if path is not None and not menu_map.is_submenu(path, sub_items(path, it))])
    for path, it in kids:
        if path is None:
            layout.separator()
            if it[1]:
                # Maya section titles are small; a lower row also keeps File inside a
                # 900 px window at 125 %
                _section_label(layout, it[1])
            continue
        iv = menu_icons.icon_value(path)
        if menu_map.is_submenu(path, sub_items(path, it)):
            layout.menu(submenus[path], text=it[0] + (BOX_MARK if path in OPTION_BOXES else ""), icon_value=iv,
                        translate=False)
        elif path in OPTION_BOXES:
            _draw_boxed(layout, path, texts[path], iv)
        else:
            draw_item(layout, path, texts[path], iv, translate=False)


def _section_label(layout, text):
    """A Maya section title, on a lower row than an item (Maya draws them small)."""
    row = layout.row()
    if row is None:      # a minimal stand-in layout (tests)
        layout.label(text=text)
        return
    row.scale_y = 0.8
    row.label(text=text)


# Menu class of every Maya submenu path (e.g. "Graph Editor/Tangents/Default In Tangent"), for buttons that open one
SUBMENU_IDS = {}


def _make_menu(idname, label, prefix, items, top_label=None):
    submenus = {}
    classes = []
    for path, it in iter_items(items, prefix):
        if path not in submenus and menu_map.is_submenu(path, sub_items(path, it)):
            submenus[path] = f"{idname}_{len(submenus)}"
    # Build the submenu classes (each draws its own children).
    SUBMENU_IDS.update(submenus)
    for path, sub_id in submenus.items():
        node = _find(items, prefix, path)
        classes.append(_menu_class(sub_id, node[0], path, sub_items(path, node), submenus))
    classes.insert(0, _menu_class(idname, label, prefix, items, submenus, top_label))
    return classes


def _find(items, prefix, path):
    for p, it in iter_items(items, prefix):
        if p == path:
            return it
    raise KeyError(path)


def _menu_class(idname, label, prefix, items, submenus, top_label=None):
    blender = menu_map.BLENDER_MENU.get(top_label) if top_label else None

    def draw(self, context):
        layout = self.layout
        from . import maya_dock
        maya_dock.draw_tear_line(layout, idname)    # Maya's dotted tear-off line
        if top_label:
            option_click.note_draw(context, top_label)    # opened from the Maya menu bar?
        _draw_items(layout, items, prefix, submenus)
        if blender:
            layout.separator()
            layout.menu(blender[0], text=blender[1], icon='BLENDER')

    return type(idname, (bpy.types.Menu,), {
        "bl_idname": idname, "bl_label": label, "draw": draw,
        # the tooltip: the menu's name (a composed "Maya menu: path" would stay English: Blender translates
        # a menu's description from its tables, and a path is in none); the docstring keeps the path
        "bl_description": label,
        "__doc__": f"Maya menu: {prefix}"})


class ALLSET_MT_ui_elements(bpy.types.Menu):
    """Maya Windows > UI Elements"""
    bl_idname = "ALLSET_MT_ui_elements"
    bl_label = "UI Elements"

    def draw(self, context):
        from .. import preferences
        prefs = preferences.get(context)
        layout = self.layout
        layout.prop(prefs, "maya_top_bar")
        layout.prop(prefs, "maya_panel_menus")
        layout.prop(prefs, "show_status_line")
        from .shelf import shelf_row_area, strip_area
        draw_safe.op(layout, "allset.shelf_strip_toggle", text="Shelf",
                     icon='CHECKBOX_HLT' if strip_area(context.screen) or shelf_row_area(context.screen)
                     else 'CHECKBOX_DEHLT')
        layout.prop(prefs, "show_command_line")
        layout.prop(prefs, "show_help_line")
        from .toolbox_layouts import toolbox_shown
        draw_safe.op(layout, "allset.toolbox_toggle", text="Tool Box",
                     icon='CHECKBOX_HLT' if toolbox_shown(context.screen) else 'CHECKBOX_DEHLT')


class ALLSET_MT_menu_bar(bpy.types.Menu):
    """The Maya menu bar folded into one menu (header menus collapsed)"""
    bl_idname = "ALLSET_MT_menu_bar"
    bl_label = "Menus"

    def draw(self, context):
        draw_menu_bar(self.layout, context, collapsed=True)


# Maya-style menu bar items are their text plus a small padding; Blender's header pulldowns add about a UI unit, so
# the bar overflowed a 1600 px window at 125 %. Each item gets its blf text width plus this padding.
MENU_PAD_PX = 11


def menu_width_units(text, context):
    """``ui_units_x`` of a header pulldown showing ``text`` at Maya's spacing. ``text`` is the English label; it is
    taken as the interface shows it, so translated labels (Japanese, #249) are not cut off."""
    import blf
    prefs = context.preferences
    scale = prefs.system.ui_scale or 1.0
    blf.size(0, prefs.ui_styles[0].widget.points * scale)
    w = blf.dimensions(0, bpy.app.translations.pgettext_iface(text))[0]
    return (w + MENU_PAD_PX * scale) / (20.0 * scale)


def _menu(layout, context, idname, collapsed, units=None):
    if collapsed:
        layout.menu(idname)
        return
    label = getattr(bpy.types, idname).bl_label
    sub = layout.row(align=True)
    got = units.get(idname) if units else None
    sub.ui_units_x = menu_width_units(label, context) if got is None else got
    sub.menu(idname)


def draw_menu_bar(layout, context, collapsed=False, menu_set=True, units=None):
    """Blender logo menu, Maya common menus, set menus, Cache, Help. ``menu_set``: the menu set dropdown after the
    common menus (only when no Status Line shows it: Maya keeps it at the Status Line's left end). ``units``:
    {menu idname: ``menu_width_units`` of its label} already worked out for this draw."""
    from .. import preferences
    prefs = preferences.get(context)
    if collapsed:
        layout.menu("TOPBAR_MT_blender", text="Blender")
    else:
        layout.menu("TOPBAR_MT_blender", text="", icon='BLENDER')
    set_id = prefs.menu_set
    for name in _SET_MENUS[COMMON_SET]:
        _menu(layout, context, menu_idname(name), collapsed, units)
    if collapsed:
        layout.separator()
        layout.prop(prefs, "menu_set", text="")
    elif menu_set:
        sub = layout.row()
        sub.ui_units_x = 5.5
        sub.prop(prefs, "menu_set", text="")
    for name in _SET_MENUS.get(set_id, ()) + _ALWAYS_MENUS:
        _menu(layout, context, menu_idname(name), collapsed, units)
    draw_addon_menus(layout, context)


_menu_classes = []
for _name, (_label, _set, _src, _items) in menu_data.MENUS.items():
    _menu_classes.extend(_make_menu(menu_idname(_name), _label, _label, _items, top_label=_label))
for _editor, _menus in editor_menu_data.EDITORS.items():
    for _i, (_title, _items) in enumerate(_menus):
        _menu_classes.extend(_make_menu(editor_menu_idname(_editor, _i), _title, f"{_editor}/{_title}", _items))

classes = (ALLSET_OT_menu_unavailable, ALLSET_OT_menu_set_value, ALLSET_OT_menu_item, ALLSET_OT_menu_whole_mesh,
           ALLSET_OT_component_command, ALLSET_MT_option_box, ALLSET_OT_option_box_point,
           ALLSET_OT_menu_option_box, ALLSET_OT_menu_run, ALLSET_OT_menu_tool,
           ALLSET_MT_ui_elements, ALLSET_MT_addon_menus, ALLSET_MT_menu_bar, *option_click.classes, *_menu_classes)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_whole_mesh_options()
    register_proxies()
    menu_icons.register()


def unregister():
    menu_icons.unregister()
    unregister_proxies()
    unregister_whole_mesh_options()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
