# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's torn-off menus: the dotted tear-off line at the top of kit menus (``draw_tear_line``,
``ALLSET_OT_menu_tear_off``), a floating window as tall as the menu (``tear_menu``, ``menu_rows``), the menu's items
drawn left-aligned in it (``draw_torn_menu``) and menu windows restored from a file closed (``_close_stale_menus``).
Registered by maya_dock.py, which also re-exports these names.
"""

import bpy
from bpy.props import StringProperty

from .maya_dock_roles import _torn_menus, role, set_role_later
from .maya_dock_windows import _main_view, close_window_later, content_height, main_window, sized_window

TEAR_LINE = "- " * 18        # Maya's tear-off line at the top of a menu (``-to true``)


def menu_rows(context, idname):
    """Rows a torn-off menu window shows: handle + title + the menu's items."""
    from . import layout_measure
    cls = getattr(bpy.types, idname, None)
    if cls is None:
        return None
    _drawing_torn[0] = True           # the torn copy has no tear-off line
    try:
        n = layout_measure.rows(cls.draw, context)
    finally:
        _drawing_torn[0] = False
    return None if n is None else n + 2


def tear_menu(context, idname, label):
    """Maya's menu tear-off: a floating window listing the menu's items, as tall as the menu (issue #4)."""
    window = main_window(context.window_manager) or context.window
    # Maya's torn-off menus are a narrow column: copy a narrow side panel (the tallest, so any menu fits), the
    # viewport only when there is none
    side = [a for a in window.screen.areas if a.type in {'PROPERTIES', 'OUTLINER'} and a.height > 200]
    area = max(side, key=lambda a: a.height) if side else _main_view(window.screen)[0]
    if area is None:
        return None
    with context.temp_override(window=window):
        height = content_height(bpy.context, menu_rows(bpy.context, idname), area.height)

    def then(new):
        _torn_menus[new.as_pointer()] = (idname, label)
        target = new.screen.areas[0]
        target.ui_type = 'PROPERTIES'
        set_role_later(target, 'MENU', new)
    with context.temp_override(window=window):
        return True if sized_window(bpy.context, window, area, height, then) else None


class ALLSET_OT_menu_tear_off(bpy.types.Operator):
    """Tear off this menu into a floating window (Maya's dotted line at the top of a menu)"""
    bl_idname = "allset.menu_tear_off"
    bl_label = "Tear Off"
    bl_options = {'INTERNAL'}

    menu: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        cls = getattr(bpy.types, self.menu, None)
        if cls is None:
            return {'CANCELLED'}
        menu, label = self.menu, cls.bl_label

        def later():   # after the menu has closed
            try:
                tear_menu(bpy.context, menu, label)
            except Exception as ex:
                print("Maya Workflow Kit: menu tear-off failed:", ex)
            return None
        bpy.app.timers.register(later, first_interval=0.0)
        return {'FINISHED'}


def draw_tear_line(layout, idname):
    """Maya's dotted first line of a menu (click = tear off)."""
    if _drawing_torn[0]:
        return
    from . import draw_safe     # the operator may be missing (a half-registered kit): the menu still draws (#199)
    draw_safe.op(layout, ALLSET_OT_menu_tear_off.bl_idname, text=TEAR_LINE, emboss=False).menu = idname


_drawing_torn = [False]


def drawing_torn():
    """True while a torn-off menu window draws its menu's items."""
    return _drawing_torn[0]


def draw_torn_menu(layout, context):
    entry = _torn_menus.get(context.window.as_pointer()) if context.window else None
    if entry is None:
        layout.label(text="This torn-off menu ended with its session")
        return
    cls = getattr(bpy.types, entry[0], None)
    if cls is None:
        return
    layout.label(text=entry[1])
    col = layout.column(align=True)
    col.alignment = 'LEFT'           # items left-aligned like the menu (not centred buttons)
    col.emboss = 'PULLDOWN_MENU'
    _drawing_torn[0] = True
    try:
        cls.draw(_Holder(_LeftItems(col)), context)
    finally:
        _drawing_torn[0] = False


class _Holder:
    def __init__(self, layout):
        self.layout = layout


# Maya's torn-off menu reads like the menu, every item's text from the left edge. Outside a menu Blender
# centres an operator button's text (plain, press-and-hold for the option box, radio choice; sub-menu rows, labels
# and check boxes stay left), and ``column.alignment`` doesn't change that: a row aligned LEFT around the button
# sizes it to its text, which then starts at the left. The hotkey / option box column (``menu_item_text.item_texts``) is
# in the text, so it still lines up; the rows keep their height (``menu_rows``).
_CENTRED = ("operator", "operator_menu_hold", "prop_enum")


class _LeftItems:
    """The torn-off menu's column: each centred button in its own left-aligned row, the rest as drawn."""

    def __init__(self, col):
        object.__setattr__(self, "_col", col)

    def __getattr__(self, name):
        if name not in _CENTRED:
            return getattr(self._col, name)

        def left(*args, **kwargs):
            row = self._col.row(align=True)
            row.alignment = 'LEFT'
            return getattr(row, name)(*args, **kwargs)
        return left

    def __setattr__(self, name, value):
        setattr(self._col, name, value)


def _close_stale_menus():
    """MENU windows restored from a file have no menu to show (the id lives in memory): close them."""
    wm = bpy.context.window_manager
    for window in list(wm.windows):
        if window.as_pointer() in _torn_menus:
            continue
        if len(window.screen.areas) == 1 and role(window.screen.areas[0]) == 'MENU':
            close_window_later(window)
    return None
