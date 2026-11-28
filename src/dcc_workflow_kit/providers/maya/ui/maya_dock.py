# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's docking model: every Maya panel is its own area or window, torn off by its ::::: handle
.

Maya builds every UI element as a dockable ``workspaceControl``; the right column is one tab stack of Channel Box /
Layer Editor, Attribute Editor and Modeling Toolkit, and a panel's
dotted handle tears it off into a floating window. Here:

- **Dock areas.** A Maya panel lives in its own Properties editor on the Tool tab, header and tab column hidden (the
  Tool tab draws 3D View "Tool"-category panels), never in the viewport's sidebar. The area's role is kept
  in the space's hidden tab flags (``ROLE_FLAGS``: Tool tab + one flag), so it survives saving and ``area_dupli``
  (the copy keeps context, flags and the hidden header). The Tool Settings dock (``tool_dock``) is the
  Tool tab with no role flag.
- **Stack.** The ``STACK`` area shows Maya's vertical tab strip on its right edge and the selected tab
  (``WindowManager.allset_dock``); kinds that have a floating window leave the strip.
- **Tear off / dock.** The handle row (``ALLSET_OT_dock_handle``) on a docked panel opens a floating window with only
  that panel (``area_dupli`` + role); on a floating panel it offers Dock (close the window, the panel goes back) and
  Close. A floating window closed by its OS button docks back by itself (the stack only hides kinds that float).
  Cross-window drag and drop isn't possible from Python: a click replaces Maya's drag.
- **Menus.** Kit Maya menus start with Maya's dotted tear-off line: a floating ``MENU`` window draws that menu's items
  as buttons (the menu id per window is kept in memory, ``_torn_menus``; a MENU window loaded from a file closes).

The code is split by responsibility: ``maya_dock_roles`` (roles, tab stack), ``maya_dock_windows`` (open / close /
dock windows), ``maya_dock_menus`` (torn-off menus), ``maya_dock_strip`` (vertical tab strip), ``maya_dock_tint``
(dock grey). This module keeps the Maya panel, its handle row and operators, tearing a panel off, the Properties draw
callback, the load handler and register / unregister; the names used elsewhere are importable from here too.
"""

import math

import bpy
from bpy.props import EnumProperty

from .. import i18n
from . import draw_replay, window_motion
# the split-out parts, also read through this module by other UI, tools and the tests
from .maya_dock_roles import (KINDS, LABELS, ROLE_FLAGS, WIDTH, _MARK_FLAGS, _flags, _mark_flags,  # noqa: F401
                              _pending, _torn_menus, area_role, current_tab, find_stack, floating_kinds,
                              is_floating, kind_visible, redraw, role, set_role, set_role_later, shown_kind,
                              stack_tabs, tab_kinds, visible_kinds)
from .maya_dock_windows import (MIN_KEEP_PX, MIN_ROWS, PAD_ROWS, _main_view, close_area,  # noqa: F401
                                close_floating, close_window_later, content_height, dock, main_window,
                                floating_window, open_floating, open_stack, show, sized_window, split_side,
                                to_front, toggle)
from .maya_dock_menus import (ALLSET_OT_menu_tear_off, TEAR_LINE, _CENTRED, _Holder, _LeftItems,  # noqa: F401
                              _close_stale_menus, _drawing_torn, draw_tear_line, draw_torn_menu, drawing_torn,
                              menu_rows, tear_menu)
from .maya_dock_tint import (MAYA_DOCK_GREY, TINTED_ROLES, _around, _fill, _hole_kept, _hole_row,  # noqa: F401
                             _kept_hole, _list_hole, _rects, dark_span, dark_top, dock_lift, draw_tint)
from .maya_dock_strip import (PANEL_MARGIN_U, STRIP_GAP_PX, STRIP_PX, STRIP_SHADE, STRIP_TOP_PX,  # noqa: F401
                              TAB_END_PX, TAB_GAP_PX, TAB_SHADE, TEXT_LOWERED, ALLSET_OT_dock_section,
                              ALLSET_OT_dock_strip_click, StripClear, _drawn, _sections_open, _strip_colours,
                              _ui_unit, content_factor, content_layout, draw_strip, reserved_px, section, strip_hit,
                              strip_px, strip_tabs, tab_drawn)

HANDLE = ":" * 8            # Maya's dotted grip on a workspaceControl (plain ASCII: every UI font has it)


def panel_rows(context, area=None):
    """Rows the Maya panel in ``area`` draws now (estimated for the Outliner / Tool Settings), or None."""
    from . import layout_measure
    area = area or context.area
    if area is not None and area.type == 'OUTLINER':
        n = sum(1 for _ in context.scene.objects) + 7       # objects + the startup rows Maya lists + header
        return min(n, 40)
    if role(area) is None:
        from . import tool_dock
        return 24 if tool_dock.is_dock(area) else None     # Tool Settings: Move / Rotate / Scale settings
    return layout_measure.rows(ALLSET_PT_maya_dock.draw, context)


def _area_by_pointer(window, ptr):
    try:
        return next((a for a in window.screen.areas if a.as_pointer() == ptr), None)
    except ReferenceError:
        return None


def tear_off(context, area=None):
    """Tear the panel in ``area`` off into a floating window sized to the panel (issue #4). Returns True when the
    window is (being) made, None when this area can't be torn off."""
    from . import tool_dock
    area = area or context.area
    window = context.window
    wm = context.window_manager
    r = role(area)
    if r != 'STACK' and not (area is not None and (tool_dock.is_dock(area) or area.type == 'OUTLINER')):
        return None
    height = content_height(context, panel_rows(context, area), area.height)
    area_ptr = area.as_pointer()
    if r == 'STACK':
        kind = current_tab(wm)
        if kind is None:
            return None
        rest = [k for k in stack_tabs(wm) if k != kind]

        def then(new):
            set_role_later(new.screen.areas[0], kind, new)
            if rest:
                bpy.context.window_manager.allset_dock = rest[0]
            else:                                   # an empty tab stack goes away, like Maya's
                close_area(bpy.context, window, _area_by_pointer(window, area_ptr))
            redraw()
        return True if sized_window(context, window, area, height, then) else None
    outliner = area.type == 'OUTLINER'

    def then(new):
        if outliner:
            from . import maya_outliner
            maya_outliner.setup(new.screen.areas[0].spaces.active)
            close_area(bpy.context, window, _area_by_pointer(window, area_ptr))
            return
        tool_dock.set_docked(False)                # Tool Settings opens floating next time, like Maya's window
        tool_dock.close_dock(bpy.context, window)  # the viewport (the four view) gets the dock's width back
    return True if sized_window(context, window, area, height, then) else None


# --- operators -----------------------------------------------------------------------------------------------------

class ALLSET_OT_dock_handle(bpy.types.Operator):
    """Maya panel handle: click to tear this panel off into a floating window; on a floating panel, dock it back"""
    bl_idname = "allset.dock_handle"
    bl_label = "Panel Handle"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if is_floating(context.window, context.window_manager):
            context.window_manager.popup_menu(_draw_float_menu, title=_float_title(context))
            return {'FINISHED'}
        return self.execute(context)

    def execute(self, context):
        if tear_off(context) is None:
            self.report({'WARNING'}, "This panel can't be torn off")
            return {'CANCELLED'}
        return {'FINISHED'}


def _float_title(context):
    from . import editor_panels
    editor = editor_panels.floating_editor(context)
    if editor:
        return editor
    r = area_role(context)
    if r in LABELS:
        return LABELS[r]
    if r == 'MENU':
        return _torn_menus.get(context.window.as_pointer(), ("", "Menu"))[1]
    return LABELS['OUTLINER'] if context.area and context.area.type == 'OUTLINER' else LABELS['TOOL_SETTINGS']


def _draw_float_menu(self, context):
    layout = self.layout
    from . import editor_panels
    if editor_panels.floating_editor(context):
        editor_panels.draw_dock_items(layout)     # a Graph Editor / Dope Sheet / UV Editor window (#319)
    elif area_role(context) != 'MENU':
        layout.operator(ALLSET_OT_dock_back.bl_idname, text="Dock", icon='DOCUMENTS').action = 'DOCK'
    layout.operator(ALLSET_OT_dock_back.bl_idname, text="Close", icon='X').action = 'CLOSE'


class ALLSET_OT_dock_back(bpy.types.Operator):
    """Dock this floating panel again (or close it)"""
    bl_idname = "allset.dock_back"
    bl_label = "Dock Panel"
    bl_options = {'INTERNAL'}

    action: EnumProperty(items=(('DOCK', "Dock", ""), ('CLOSE', "Close", "")), options={'SKIP_SAVE'})

    def execute(self, context):
        if self.action == 'CLOSE':
            _torn_menus.pop(context.window.as_pointer(), None)
            close_window_later(context.window)   # a closed panel window docks back by itself (stack tabs)
            return {'FINISHED'}
        return {'FINISHED'} if dock(context) else {'CANCELLED'}


class ALLSET_OT_dock_tab(bpy.types.Operator):
    """Show this panel in the tab stack"""
    bl_idname = "allset.dock_tab"
    bl_label = "Dock Tab"
    bl_options = {'INTERNAL'}

    kind: EnumProperty(items=[(k, LABELS[k], "") for k in KINDS])

    def execute(self, context):
        context.window_manager.allset_dock = self.kind
        redraw()
        return {'FINISHED'}


class ALLSET_OT_panel_show(bpy.types.Operator):
    """Show this Maya panel: raise it where it is docked, else open it as a floating window (Maya Windows menu)"""
    bl_idname = "allset.panel_show"
    bl_label = "Show Panel"
    bl_options = {'INTERNAL'}

    panel: EnumProperty(items=[(k, LABELS[k], "") for k in (*KINDS, 'OUTLINER')])

    def execute(self, context):
        if self.panel in tab_kinds():       # Tool Settings: a stack tab only with the Tool Settings Tab preference
            return {'FINISHED'} if show(context, self.panel) else {'CANCELLED'}
        wm = context.window_manager
        if self.panel == 'TOOL_SETTINGS':
            from . import tool_dock
            tool_dock.toggle(context, show_only=True)       # shown already: a floating window comes to the front
            return {'FINISHED'}
        # Outliner: docked in this layout or already floating = shown; else a floating Maya Outliner
        if any(a.type == 'OUTLINER' for w in wm.windows for a in w.screen.areas):
            return {'FINISHED'}
        return bpy.ops.allset.open_editor(ui_type='OUTLINER')


# --- panel ---------------------------------------------------------------------------------------------------------

def draw_handle(layout, context=None, tabs=False):
    """The top row of a Maya panel: Maya's dotted grip (click = tear off / dock) and, in the tab stack, the tabs
    (Maya's title / tab row above the editor's menu bar)."""
    row = layout.row(align=True)
    grip = row.row(align=True)
    grip.alignment = 'LEFT'
    if tabs and context is not None:
        # Blender splits an expanded row into equal tabs ("Channel Box / Layer Editor" was cut while "Attribute
        # Editor" got twice its text): each tab gets its text's width (the same rule sizes the dock,
        # ui/layout_fit.dock_need)
        row.alignment = 'LEFT'
        grip.ui_units_x = text_units(context, HANDLE, GRIP_PAD)
    grip.operator(ALLSET_OT_dock_handle.bl_idname, text=HANDLE, emboss=False)
    if tabs and context is not None:
        current = current_tab(context.window_manager)
        for kind in stack_tabs(context.window_manager):
            tab = row.row(align=True)
            tab.ui_units_x = text_units(context, i18n.iface(LABELS[kind]), TAB_PAD)
            tab.operator(ALLSET_OT_dock_tab.bl_idname, text=LABELS[kind], depress=(kind == current)).kind = kind


TAB_PAD = 1.0       # UI units around a tab's text
GRIP_PAD = 1.5


def text_units(context, text, pad):
    """Width of ``text`` in Blender's UI font (11 pt x UI scale) in UI units, plus ``pad`` units."""
    import blf
    system = context.preferences.system
    s = system.ui_scale or 1.0
    u = math.floor(18.0 * s + 0.5) + 2 * system.pixel_size
    blf.size(0, 11.0 * s)
    return blf.dimensions(0, text)[0] / max(u, 1) + pad


def area_reserved_px(context):
    """``reserved_px`` in a tab-stack area, else 0 (what a content width rule subtracts from ``region.width``)."""
    if area_role(context) != 'STACK':
        return 0
    return reserved_px(context.preferences.system.ui_scale or 1.0)


_strip_handle = []


def _strip_callback():
    from . import channel_box
    channel_box.region_drawn()      # the region's buttons are drawn: the Channel Box's draw-time lead ends here
    try:
        context = bpy.context
        region = context.region
        if region is None:
            return
        key = ("dock draw", region.as_pointer())
        sig = (region.width, region.height, context.preferences.system.ui_scale)
        if draw_replay.again(key, sig):     # a window moves: the tint and the tab strip as drawn last
            return
        with draw_replay.recording(key, sig):
            draw_tint()
            draw_strip()
    except Exception:     # a draw error would repeat every redraw
        import traceback
        traceback.print_exc()


class ALLSET_PT_maya_dock(bpy.types.Panel):
    """A Maya panel in its own dock area or floating window (Channel Box / Layer Editor, Attribute Editor, Modeling
    Toolkit, torn-off menus)"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"           # = drawn by the Properties Tool tab (like Tool Settings)
    bl_label = "Maya Panel"
    bl_options = {'HIDE_HEADER'}
    bl_order = -200

    @classmethod
    def poll(cls, context):
        return area_role(context) is not None

    def draw(self, context):
        layout = self.layout
        r = area_role(context)
        if r == 'MENU':
            draw_handle(layout)
            draw_torn_menu(layout, context)
            return
        if r == 'STACK':
            # #78: Maya's tabs are the vertical strip on the stack's right edge (draw_strip); the content
            # keeps clear of it
            layout = content_layout(layout, context)
        draw_handle(layout, context)
        kind = shown_kind(context)
        if r == 'STACK':
            tab_drawn(context, kind)
        if kind is None:
            layout.label(text="Every panel of this tab stack is in its own window")
            return
        from . import channel_box
        if kind == 'CHANNEL_BOX':
            units = channel_box.ALLSET_PT_channel_box.body(layout, context)
            channel_box.fill_pane(layout, context, units)
            from . import set_driven_key    # its lists fit the room the Channel Box leaves (#77)
            set_driven_key.remember_room(context, units)
            from . import layer_editor      # Maya's Layer Editor under the Channel Box (or the Set Driven Key window)
            layer_editor.ALLSET_PT_layer_editor.draw(_Holder(layout), context)
        elif kind == 'ATTRIBUTE_EDITOR':
            from . import attribute_editor
            attribute_editor.draw_panel(layout, context)
        elif kind == 'MODELING_TOOLKIT':
            from . import modeling_toolkit
            modeling_toolkit.draw(layout, context)
        elif kind == 'TOOL_SETTINGS':
            from . import tool_settings
            tool_settings.draw_dock(layout, context)


@bpy.app.handlers.persistent
def _on_load(*_args):
    _torn_menus.clear()
    _drawn.clear()          # area pointers of the old file may be reused
    _hole_kept.clear()
    if not bpy.app.background:
        bpy.app.timers.register(_close_stale_menus, first_interval=0.2)


classes = (ALLSET_OT_dock_handle, ALLSET_OT_dock_back, ALLSET_OT_dock_tab, ALLSET_OT_panel_show,
           ALLSET_OT_menu_tear_off, ALLSET_OT_dock_strip_click, ALLSET_OT_dock_section, ALLSET_PT_maya_dock)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_post.append(_on_load)
    _strip_handle.append(bpy.types.SpaceProperties.draw_handler_add(_strip_callback, (), 'WINDOW', 'POST_PIXEL'))


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if bpy.app.timers.is_registered(_close_stale_menus):
        bpy.app.timers.unregister(_close_stale_menus)
    while _strip_handle:
        bpy.types.SpaceProperties.draw_handler_remove(_strip_handle.pop(), 'WINDOW')
    _drawn.clear()
    _hole_kept.clear()
    _rects.clear()
    window_motion.forget()
    _MARK_FLAGS.clear()
    _torn_menus.clear()
    _pending.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
