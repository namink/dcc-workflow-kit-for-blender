# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya top bar (menu bar) and Status Line.

Maya's menu bar and Status Line groups;
$S\\startup\\bl_ui\\space_topbar.py:14-62.

``TOPBAR_HT_upper_bar.draw_left`` / ``draw_right`` are swapped for Maya
versions while the add-on is enabled and put back on unregister; the
originals still run when the "Maya Menu Bar" preference is off. Maya has the
Status Line on its own row under the menus; one TOPBAR row can't hold both
(at 1600 px), so the Status Line is
drawn first in the tool header of the largest 3D View.

This module: the Status Line draw (groups and collapse handles, editor toggles), the top bar draw (``draw_left`` /
``draw_right``, Workspace field) and registration. Button operators and 3D View lookups: ``status_line_buttons``;
menu bar overflow: ``menu_bar_fit``. The names used elsewhere are importable from here too.
"""

import bpy
from bpy.props import EnumProperty, StringProperty

from . import draw_safe, input_line, menu_sets, own_draw, status_icons
from .. import i18n, safe_reg
# the split-out parts, also read through this module by other UI and the tests
from .status_line_buttons import (ALLSET_MT_symmetry, ALLSET_OT_ipr_toggle, ALLSET_OT_light_editor,  # noqa: F401
                                  ALLSET_OT_render_settings, ALLSET_OT_select_mask, ALLSET_OT_select_mode,
                                  ALLSET_OT_snap_toggle, OBJECT_MASKS, SNAPS, _KEEP_SNAP, _SNAP_ELEMENTS,
                                  _SNAP_UNDO_HANDLERS, _carried, _ipr_on, _masks_after_load, _masks_before_load,
                                  _properties_area, all_view3d_spaces, apply_masks, draw_symmetry,
                                  draw_tool_symmetry, ipr_toggle, main_view3d, mask_on, restore_snap, session_masks,
                                  set_mask, snap_on, toggle_snap, view3d_space)
from .menu_bar_fit import (ALLSET_MT_menu_more, MENU_MORE_UNITS, _menu_set_field, _menus_shown,  # noqa: F401
                           draw_menu_bar_fit, menu_bar_widths, menu_fit, shown_menus)


# --- editor toggles -----------------------------------------------

EDITORS = (
    # Maya order: Modeling Toolkit first
    ("MODELING_TOOLKIT", "Show or hide the Modeling Toolkit", 'EDITMODE_HLT'),
    ("ATTRIBUTE", "Show or hide the Attribute Editor", 'PROPERTIES'),
    ("TOOL_SETTINGS", "Show or hide the Tool Settings of the active tool", 'TOOL_SETTINGS'),
    ("CHANNEL_BOX", "Show or hide the Channel Box / Layer Editor", 'MENU_PANEL'),
)
# Status Line toggle -> Maya panel of the tab stack (ui/maya_dock.py)
DOCK_KINDS = {"MODELING_TOOLKIT": 'MODELING_TOOLKIT', "ATTRIBUTE": 'ATTRIBUTE_EDITOR', "CHANNEL_BOX": 'CHANNEL_BOX'}


def editor_shown(screen, editor, docks=None):
    """``docks``: ``maya_dock_roles.visible_kinds()`` already read for this draw."""
    if editor == "TOOL_SETTINGS":    # the floating window or the dock left of the viewport (ui/tool_dock.py)
        from . import tool_dock
        return tool_dock.shown(screen) or tool_dock.shown_anywhere()
    if docks is not None:
        return DOCK_KINDS[editor] in docks
    from . import maya_dock
    return maya_dock.kind_visible(bpy.context.window_manager, DOCK_KINDS[editor])


class ALLSET_OT_editor_toggle(bpy.types.Operator):
    """Show or hide a Maya editor"""
    bl_idname = "allset.editor_toggle"
    bl_label = "Toggle Editor"
    bl_options = {'INTERNAL'}

    editor: EnumProperty(items=[(e[0], e[0].title(), e[1]) for e in EDITORS])
    show: bpy.props.BoolProperty(options={'SKIP_SAVE'},
                                 description="Only show the editor (Maya toolPropertyWindow), never hide it")

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return next(e[1] for e in EDITORS if e[0] == props.editor)

    def execute(self, context):
        if self.editor == "TOOL_SETTINGS":
            # Maya ToggleToolSettings: a floating window, or the dock once docked (ui/tool_dock.py)
            from . import tool_dock
            tool_dock.toggle(context, show_only=self.show)
            return {'FINISHED'}
        # Maya Windows > UI Elements toggles: a panel tabbed behind another is raised,
        # a shown one hidden (ui/maya_dock_windows.py)
        from . import maya_dock
        maya_dock.toggle(context, DOCK_KINDS[self.editor], show_only=self.show)
        return {'FINISHED'}


# --- drawing --------------------------------------------------------------------

# Maya Status Line groups each start with a collapse handle that hides the group.
# Kept for the
# session only (Maya keeps them in its preferences).
GROUPS = (
    ("FILE", "File: New, Open, Save, Undo, Redo"),
    ("SELECT_MODE", "Selection mode: hierarchy, object, component"),
    ("MASKS", "Selection masks"),
    ("SNAP", "Snap toggles"),
    ("SYMMETRY", "Symmetry"),
    ("HISTORY", "Construction History"),
    ("RENDER", "Render"),
    ("INPUT", "Input line: absolute / relative transform, rename, select by name"),
    ("EDITORS", "Editor toggles"),
)
# Groups Maya shows collapsed on a new Status Line (only the bar
# and arrow between selection modes and snaps, after symmetry and after render).
DEFAULT_COLLAPSED = ("MASKS", "HISTORY", "INPUT")
_collapsed = set(DEFAULT_COLLAPSED)


class ALLSET_OT_status_group(bpy.types.Operator):
    """Show or hide this Status Line group (Maya collapse handle)"""
    bl_idname = "allset.status_group"
    bl_label = "Status Line Group"
    bl_options = {'INTERNAL'}

    group: EnumProperty(items=[(g, g.replace("_", " ").title(), d) for g, d in GROUPS])

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        desc = next(d for g, d in GROUPS if g == props.group)
        return f"{'Show' if props.group in _collapsed else 'Hide'}: {desc}"

    def execute(self, context):
        _collapsed.symmetric_difference_update({self.group})
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
        return {'FINISHED'}


# Maya Status Line icons are 20 px on a 23 px pitch; a Blender
# header button draws its icon at 16 px x UI scale unless the button is scaled.
ICON_SCALE = 1.0


def _flat(layout, op, name, depress=False, text=""):
    """A Maya Status Line button: a kit-drawn glyph without a frame; a pressed button gets the frame (Maya's blue
    square behind an active toggle)."""
    sub = layout.row(align=True)
    sub.scale_x = sub.scale_y = ICON_SCALE
    if not depress:
        sub.emboss = 'NONE'
    return draw_safe.op(sub, op, text=text, icon_value=status_icons.icon(name), depress=depress)


def _grey(layout, name, item):
    _flat(layout, menu_sets.ALLSET_OT_menu_unavailable.bl_idname, name).item = item


def _group(layout, group):
    """Maya group start: the bar, then the filled arrow when the group is collapsed. True when its buttons should be
    drawn (``_group_end`` then adds the open collapse arrow)."""
    bar = layout.row(align=True)
    bar.ui_units_x = 0.5
    bar.label(text="", icon_value=status_icons.icon("bar"))
    if group in _collapsed:
        sub = layout.row(align=True)
        sub.ui_units_x = 0.6
        sub.emboss = 'NONE'
        draw_safe.op(sub, ALLSET_OT_status_group.bl_idname, text="", icon_value=status_icons.icon("closed")).group = group
        return False
    return True


def _group_end(layout, group):
    sub = layout.row(align=True)
    sub.ui_units_x = 0.6
    sub.emboss = 'NONE'
    draw_safe.op(sub, ALLSET_OT_status_group.bl_idname, text="", icon_value=status_icons.icon("open")).group = group


def _field(layout, owner, prop, units):
    sub = layout.row(align=True)
    sub.ui_units_x = units
    sub.prop(owner, prop, text="")


def draw_status_line(layout, context, compact=False):
    """The Maya Status Line, left to right:
    menu set combo, then groups of bar + buttons + collapse arrow, sidebar toggles at the right end. ``compact``
    (the 3D View tool header of other layouts, which overflows): the input line goes after the editor toggles
   ."""
    from .. import preferences
    screen = context.screen
    ts = context.scene.tool_settings
    area, _r = main_view3d(screen)
    space = area.spaces.active if area else None

    sub = layout.row(align=True)
    sub.ui_units_x = 5                       # 100 px combo
    sub.prop(preferences.get(context), "menu_set", text="")

    if _group(layout, "FILE"):
        row = layout.row(align=True)
        _flat(row, "allset.new_maya_scene", "new")       # new scene in the Maya layout
        _flat(row, "allset.open_scene", "open_scene")      # project scenes folder
        _flat(row, "allset.save_scene", "save")
        _flat(row, "ed.undo", "undo")
        _flat(row, "ed.redo", "redo")
        _group_end(layout, "FILE")

    if _group(layout, "SELECT_MODE"):
        editing = context.mode != 'OBJECT' and context.mode.startswith('EDIT')
        row = layout.row(align=True)
        _grey(row, "sel_hierarchy", "Status Line/Select by hierarchy")
        _flat(row, ALLSET_OT_select_mode.bl_idname, "sel_object", depress=not editing).mode = "OBJECT"
        _flat(row, ALLSET_OT_select_mode.bl_idname, "sel_component", depress=editing).mode = "COMPONENT"
        _group_end(layout, "SELECT_MODE")

    if _group(layout, "MASKS"):
        row = layout.row(align=True)
        if context.mode == 'EDIT_MESH':
            for i, name in enumerate(("vertex", "edge", "face")):
                sub = row.row(align=True)
                if not ts.mesh_select_mode[i]:
                    sub.emboss = 'NONE'
                sub.prop(ts, "mesh_select_mode", index=i, text="", icon_value=status_icons.icon(name))
        else:
            for group, desc, _icon, types in OBJECT_MASKS:
                if types is None:
                    _grey(row, "mask_" + group, f"Status Line/{desc}")
                else:
                    _flat(row, ALLSET_OT_select_mask.bl_idname, "mask_" + group,
                          depress=bool(space) and mask_on(space, group)).group = group
        _group_end(layout, "MASKS")

    if _group(layout, "SNAP"):
        row = layout.row(align=True)
        for name, desc, _icon, elements in SNAPS:
            if name == 'LIVE':
                from ..operators import live
                _flat(row, 'allset.make_live', 'snap_LIVE', depress=bool(live.objects(context.scene))).toggle = True
            elif elements is None:
                _grey(row, "snap_" + name, f"Status Line/{desc}")
            else:
                _flat(row, ALLSET_OT_snap_toggle.bl_idname, "snap_" + name, depress=snap_on(ts, name)).snap = name
        # Maya's live surface field: arrow + text field
        row = layout.row(align=True)
        sub = row.row(align=True)
        sub.emboss = 'NONE'
        from ..operators import live
        draw_safe.op(sub, "allset.live_history", text="", icon='DOWNARROW_HLT')
        field = row.row(align=True)
        field.ui_units_x = 6
        draw_safe.op(field, 'allset.live_history', text=live.text(context.scene))
        _group_end(layout, "SNAP")

    if _group(layout, "SYMMETRY"):
        row = layout.row(align=True)
        sub = row.row(align=True)
        sub.emboss = 'NONE'
        sub.menu(ALLSET_MT_symmetry.bl_idname, text="", icon='DOWNARROW_HLT')
        # Maya's symmetry box is a drop-down (Maya Status Line): a click on the text opens the list, it is
        # never a text field (Issue #155: the read-only text property took a text cursor)
        box = row.row(align=True)
        box.ui_units_x = 5
        box.menu(ALLSET_MT_symmetry.bl_idname, text=_symmetry_text(None))
        _group_end(layout, "SYMMETRY")

    if _group(layout, "HISTORY"):   # Maya Status Line; a toggle (input_line.draw_history)
        _flat(layout, input_line.ALLSET_OT_construction_history.bl_idname, "history",
              depress=context.window_manager.allset_construction_history)
        _group_end(layout, "HISTORY")

    if _group(layout, "RENDER"):
        row = layout.row(align=True)
        _flat(row, "render.view_show", "render_view")
        _flat(row, "allset.render", "render")
        _flat(row, ALLSET_OT_ipr_toggle.bl_idname, "ipr", depress=_ipr_on(space))
        _flat(row, ALLSET_OT_render_settings.bl_idname, "render_settings")
        _flat(row, "allset.hypershade", "hypershade")       # ui/hypershade_ops.py
        _grey(row, "render_setup", "Status Line/Render Setup")
        _flat(row, ALLSET_OT_light_editor.bl_idname, "light_editor")
        _grey(row, "pause", "Status Line/Pause Viewport 2.0")
        _group_end(layout, "RENDER")

    if not compact and _group(layout, "INPUT"):     # Maya Status Line input field
        input_line.draw(layout, context)
        _group_end(layout, "INPUT")

    if not compact:
        layout.separator_spacer()            # Maya: the sidebar toggles sit at the right end
    row = layout.row(align=True)
    from . import maya_dock
    docks = maya_dock.visible_kinds(context.window_manager)     # one look at the windows for the three panels
    for editor, _desc, _icon in EDITORS:
        if editor == "TOOL_SETTINGS":         # Maya order: toolkit, character controls, AE, tool settings, CB
            _grey(row, "ed_CHARACTER", "Status Line/Show or hide the Character Controls")
        _flat(row, ALLSET_OT_editor_toggle.bl_idname, "ed_" + editor,
              depress=editor_shown(screen, editor, docks)).editor = editor

    if compact and _group(layout, "INPUT"):
        input_line.draw(layout, context)
        _group_end(layout, "INPUT")


def _live_text(self):
    from ..operators import live
    return live.text(self)


def _symmetry_text(self):
    from ..operators import symmetry
    return symmetry.label(symmetry.state(bpy.context.scene))


def _read_only(self, value):
    pass




def _maya_bar(context):
    from .. import preferences
    try:
        return preferences.get(context).maya_top_bar
    except KeyError:
        return False


# Top bars seen while drawing them, by window pointer: global areas aren't in screen.areas, so
# window.screen.areas tag_redraw never reaches them. A window's global
# areas live as long as the window, so only areas of open windows are tagged.
_top_bars = {}


def redraw_top_bars():
    open_windows = {w.as_pointer() for w in bpy.context.window_manager.windows}
    for key in list(_top_bars):
        if key not in open_windows:
            del _top_bars[key]
            continue
        try:
            _top_bars[key].tag_redraw()
        except ReferenceError:
            del _top_bars[key]


def draw_left(self, context):
    if context.window is not None and context.area is not None:
        _top_bars[context.window.as_pointer()] = context.area
    if not _maya_bar(context):
        return bpy.types.TOPBAR_HT_upper_bar.draw_left(self, context)
    layout = self.layout
    if context.area.show_menus:
        draw_menu_bar_fit(layout.row(align=True), context, menu_set=not status_line_shown(context))
    else:
        layout.menu(menu_sets.ALLSET_MT_menu_bar.bl_idname, text="", icon='COLLAPSEMENU')
    if context.screen.show_fullscreen:
        layout.separator()
        draw_safe.op(layout, "screen.back_to_previous", icon='SCREEN_BACK', text="Back to Previous")


def draw_right(self, context):
    if not _maya_bar(context):
        return bpy.types.TOPBAR_HT_upper_bar.draw_right(self, context)
    layout = self.layout
    window = context.window
    if not context.screen.show_statusbar:  # as space_topbar.py:46-49
        layout.template_reports_banner()
        layout.template_running_jobs()
    # Maya: "Workspace:" and a dropdown at the far right of the menu bar
    # (label 60 px, combo 194 px), not Blender's ID field
    # (screen icon, name, unlink button).
    row = layout.row(align=True)
    row.label(text="Workspace:")
    sub = row.row(align=True)
    sub.ui_units_x = 7
    # the field asks for its items twice and its value once while it is built: one workspace list for all three
    from . import workspaces
    try:
        _ws_rows[:] = [workspaces.entries()]
    except Exception:     # the field's own callbacks read the list (and report the error) as before
        _ws_rows.clear()
    try:
        sub.prop(context.window_manager, "allset_workspace", text="")
    finally:
        _ws_rows.clear()
    if len(bpy.data.scenes) > 1:  # Maya has one scene per file; show only when needed
        row = layout.row()
        row.ui_units_x = 6
        row.template_ID(window, "scene", new="scene.new")


def status_line_shown(context):
    """A Status Line is drawn in this screen: the Maya strip row, or the main 3D View's tool header."""
    from .shelf import strip_area
    screen = context.screen
    if screen is None:
        return False
    strip = strip_area(screen)
    if strip is not None:
        return strip.spaces.active.show_region_header      # hidden: Status Line off (status_line_row)
    from .. import preferences
    try:
        if not preferences.get(context).show_status_line:
            return False
    except KeyError:
        return False
    area, _r = main_view3d(screen)
    return area is not None and area.spaces.active.show_region_tool_header


# The workspace dropdown (Maya's "Workspace:" combo) lists Maya's workspaces, then the file's others (ui/workspaces.py,
# #81).


_ws_rows = []    # [workspaces.entries()] while draw_right builds the Workspace field, else empty


def _workspaces(self, context):
    from . import workspaces
    return workspaces.dropdown_items(self, context, _ws_rows[0] if _ws_rows else None)


def _get_workspace(self):
    from . import workspaces
    return workspaces.dropdown_get(self, _ws_rows[0] if _ws_rows else None)


def _set_workspace(self, value):
    from . import workspaces
    workspaces.dropdown_set(self, value)


def draw_tool_header(self, context):
    """Status Line at the start of the main 3D View's tool header row."""
    from .. import preferences, switch
    if not switch._registered[0]:
        # left in the header's draw list by another add-on's own header swap after Maya mode went off (#423)
        return
    try:
        if not preferences.get(context).show_status_line:
            return
    except KeyError:
        return
    area, _r = main_view3d(context.screen)
    if area is None or context.area != area:  # one Status Line, not one per 3D View
        return
    from . import panel_toolbar
    # drawn in the Maya strip; a panel torn off the Maya layout has the panel toolbar there, like Maya
    if panel_toolbar.maya_screen(context):
        return
    draw_status_line(self.layout, context, compact=True)
    self.layout.separator(type='LINE')


@own_draw.kit_draw("TOPBAR_HT_upper_bar")
def draw_upper_bar(self, context):
    """The top bar's own draw while the kit is on (as space_topbar.py TOPBAR_HT_upper_bar.draw, with the kit's
    left / right): Blender's ``draw_left`` / ``draw_right`` methods stay untouched."""
    if context.region.alignment == 'RIGHT':
        draw_right(self, context)
    else:
        draw_left(self, context)


def patch_topbar():
    own_draw.swap("TOPBAR_HT_upper_bar", draw_upper_bar)


def unpatch_topbar():
    own_draw.restore("TOPBAR_HT_upper_bar", draw_upper_bar)


classes = (ALLSET_OT_select_mask, ALLSET_OT_select_mode, ALLSET_OT_snap_toggle, ALLSET_MT_symmetry, ALLSET_MT_menu_more,
           ALLSET_OT_render_settings, ALLSET_OT_light_editor, ALLSET_OT_ipr_toggle,
           ALLSET_OT_editor_toggle, ALLSET_OT_status_group)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.allset_live_text = StringProperty(
        name="Live Surface", description="The live surface (Make Live); No Live Surface when none",
        get=_live_text, set=_read_only, options={'SKIP_SAVE'})
    bpy.types.Scene.allset_symmetry_text = StringProperty(
        name="Symmetry", description="Symmetric modeling: the current mode (the arrow opens the list)",
        get=_symmetry_text, set=_read_only, options={'SKIP_SAVE'})
    bpy.types.WindowManager.allset_workspace = EnumProperty(
        name="Workspace", description="Maya workspace: switch to another workspace of this file",
        items=_workspaces, get=_get_workspace, set=_set_workspace, options={'SKIP_SAVE'})
    patch_topbar()
    bpy.types.VIEW3D_HT_tool_header.prepend(draw_tool_header)
    safe_reg.blender_class("VIEW3D_PT_active_tool").append(draw_tool_symmetry)
    bpy.app.handlers.load_pre.append(_masks_before_load)
    bpy.app.handlers.load_post.append(_masks_after_load)
    for name, fn in _SNAP_UNDO_HANDLERS:
        getattr(bpy.app.handlers, name).append(fn)


def unregister():
    for name, fn in _SNAP_UNDO_HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn in handlers:
            handlers.remove(fn)
    if bpy.app.timers.is_registered(restore_snap):
        bpy.app.timers.unregister(restore_snap)
    _KEEP_SNAP.clear()
    for handlers, fn in ((bpy.app.handlers.load_pre, _masks_before_load),
                         (bpy.app.handlers.load_post, _masks_after_load)):
        if fn in handlers:
            handlers.remove(fn)
    _carried.clear()
    safe_reg.blender_class("VIEW3D_PT_active_tool").remove(draw_tool_symmetry)
    bpy.types.VIEW3D_HT_tool_header.remove(draw_tool_header)
    unpatch_topbar()
    del bpy.types.WindowManager.allset_workspace
    del bpy.types.Scene.allset_live_text
    del bpy.types.Scene.allset_symmetry_text
    _collapsed.clear()
    _collapsed.update(DEFAULT_COLLAPSED)
    _top_bars.clear()
    _menus_shown.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
