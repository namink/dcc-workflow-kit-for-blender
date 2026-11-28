# SPDX-License-Identifier: GPL-3.0-or-later
"""The Shelf Editor's Choose Icon dialog (``allset.shelf_editor_icon_picker``): Blender, PNG and kit icons in a
scrollable grid with a search field and a Recently Used row, a PNG file chooser (``allset.shelf_editor_icon_file``)
and ``allset.shelf_editor_icon_select``, which sets the edited button's icon. Related: shelf_icons.py."""

import json
import os

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from . import shelf
from .shelf_editor_draft import _redraw, _wm


ICON_PICKER_PAGE_SIZE = 90

_ICON_ITEMS = []
_ICON_HISTORY = []


_ICON_PICKER_PAGE_KEY = "_allset_shelf_editor_icon_picker_page"


class ALLSET_OT_shelf_editor_icon_page(bpy.types.Operator):
    """Change the page in the currently open Shelf icon picker."""
    bl_idname = "allset.shelf_editor_icon_page"
    bl_label = "Change Icon Page"
    bl_options = {'INTERNAL'}

    direction: IntProperty(default=0, min=-1, max=1, options={'SKIP_SAVE'})
    page_count: IntProperty(default=1, min=1, options={'SKIP_SAVE'})

    def execute(self, context):
        wm = context.window_manager
        current = int(wm.get(_ICON_PICKER_PAGE_KEY, 1))
        wm[_ICON_PICKER_PAGE_KEY] = min(
            max(current + int(self.direction), 1),
            max(int(self.page_count), 1),
        )
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}



ICON_PICKER_GRID_COLUMNS = 18
ICON_PICKER_GRID_ROWS = 20


class ALLSET_PG_shelf_editor_icon_grid_row(bpy.types.PropertyGroup):
    """One horizontal row of icon buttons inside the scrollable picker."""
    icons_json: StringProperty(options={'SKIP_SAVE'})


def _refresh_icon_picker_rows(self, context):
    """Rebuild icon rows after the source or search query changes."""
    if context is None:
        return
    wm = context.window_manager
    collection = getattr(wm, "allset_se_icon_grid_rows", None)
    if collection is None:
        return

    try:
        names = shelf.shelf_icons.icon_names(self.source)
    except (AttributeError, TypeError, ValueError):
        names = []

    query = (self.query or "").casefold()
    if query:
        names = [name for name in names if query in name.casefold()]

    collection.clear()
    columns = ICON_PICKER_GRID_COLUMNS
    for start in range(0, len(names), columns):
        item = collection.add()
        item.icons_json = json.dumps(names[start:start + columns])

    wm.allset_se_icon_grid_rows_index = 0


class ALLSET_UL_shelf_editor_icon_grid(bpy.types.UIList):
    """Native scrollable list with one horizontal strip of icon buttons per row."""
    bl_idname = "ALLSET_UL_shelf_editor_icon_grid"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index, flt_flag=0):
        try:
            names = json.loads(item.icons_json)
        except (TypeError, ValueError):
            names = []

        # Use grid_flow inside each scrollable UIList row. Unlike a plain
        # horizontal row, even_columns makes the icon cells share the full
        # available list width instead of clustering at the left edge.
        grid = layout.grid_flow(
            row_major=True,
            columns=ICON_PICKER_GRID_COLUMNS,
            even_columns=True,
            even_rows=True,
            align=True,
        )
        grid.operator_context = 'EXEC_DEFAULT'
        selected = _wm(context).allset_se_icon

        for column in range(ICON_PICKER_GRID_COLUMNS):
            if column < len(names):
                icon_name = names[column]
                op = grid.operator(
                    ALLSET_OT_shelf_editor_icon_select.bl_idname,
                    text="",
                    emboss=True,
                    depress=(icon_name == selected),
                    **shelf.shelf_icons.icon_ui_kwargs(icon_name),
                )
                op.icon_name = icon_name
            else:
                grid.label(text="")


class ALLSET_OT_shelf_editor_icon_picker(bpy.types.Operator):
    """Browse Blender, PNG, and Maya Workflow Kit shelf icons."""
    bl_idname = "allset.shelf_editor_icon_picker"
    bl_label = "Choose Icon"
    bl_description = "Choose Icon"
    bl_options = {'INTERNAL'}

    query: StringProperty(
        name="Search Icons",
        update=_refresh_icon_picker_rows,
        options={'TEXTEDIT_UPDATE', 'SKIP_SAVE'},
    )
    source: EnumProperty(
        name="Icon Source",
        items=(
            ("ALL", "All Icons", "Blender icons, PNG files, and Maya Workflow Kit drawings"),
            ("BLENDER", "Blender Built-in", "Blender's built-in UI icon identifiers"),
            ("PNG", "PNG Files", "Packaged and user Shelf PNG files"),
            ("MWK", "Maya Workflow Kit", "Procedural icons drawn by Maya Workflow Kit"),
        ),
        default="BLENDER",
        update=_refresh_icon_picker_rows,
        options={'SKIP_SAVE'},
    )
    width: IntProperty(default=640, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        context.window_manager[_ICON_PICKER_PAGE_KEY] = 1
        _refresh_icon_picker_rows(self, context)
        dpi = context.preferences.system.dpi
        scale = context.preferences.system.ui_scale
        self.width = min(max(int(680 * dpi / 72 * scale), 420), context.window.width - 32)
        return context.window_manager.invoke_props_dialog(self, width=self.width)

    def draw(self, context):
        layout = self.layout
        header = layout.row(align=True)
        header.prop(self, "source", text="")
        header.prop(self, "query", text="", icon='VIEWZOOM')
        header.operator(
            ALLSET_OT_shelf_editor_icon_file.bl_idname,
            text="Browse PNG File…",
            icon='FILE_FOLDER',
        )
        wm = _wm(context)
        names = shelf.shelf_icons.icon_names(self.source)
        query = self.query.casefold()
        if query:
            names = [name for name in names if query in name.casefold()]

        history = [name for name in reversed(_ICON_HISTORY)
                   if not query or query in name.casefold()]
        history_box = layout.box()
        history_box.label(text="Recently Used")
        self._draw_icon_history_row(history_box, history[:6], context)

        box = layout.box()
        box.label(text=f"{self._source_label()} ({len(names)} icons)")
        box.template_list(
            ALLSET_UL_shelf_editor_icon_grid.__name__,
            "ALLSET_SHELF_ICON_SCROLL_GRID",
            wm,
            "allset_se_icon_grid_rows",
            wm,
            "allset_se_icon_grid_rows_index",
            rows=ICON_PICKER_GRID_ROWS,
            maxrows=ICON_PICKER_GRID_ROWS,
            type='DEFAULT',
        )

    def _source_label(self):
        return {
            "ALL": "All Icons",
            "BLENDER": "Blender Icons",
            "PNG": "PNG Icons",
            "MWK": "Maya Workflow Kit Icons",
        }[self.source]

    def _draw_icon_history_row(self, layout, names, context):
        """Draw one fixed six-cell row of recently used icon buttons."""
        row = layout.row(align=True)
        grid = row.grid_flow(row_major=True, columns=6,
                             even_columns=True, even_rows=True, align=True)
        grid.operator_context = 'EXEC_DEFAULT'
        selected = _wm(context).allset_se_icon
        for index in range(6):
            icon_name = names[index] if index < len(names) else None
            if icon_name:
                op = grid.operator(
                    ALLSET_OT_shelf_editor_icon_select.bl_idname,
                    text="",
                    emboss=True,
                    depress=(icon_name == selected),
                    **shelf.shelf_icons.icon_ui_kwargs(icon_name),
                )
                op.icon_name = icon_name
            else:
                # Empty cells preserve the same six-column footprint.
                grid.label(text="")

    def _draw_icon_grid(self, layout, names, context):
        # A fixed 18 x 5 page uses the available picker width more efficiently.
        # The page size is 90, preserving the same five-row canvas height.
        columns = 18
        grid = layout.grid_flow(row_major=True, columns=columns,
                                even_columns=True, even_rows=True, align=True)
        selected = _wm(context).allset_se_icon
        grid.operator_context = 'EXEC_DEFAULT'
        for name in names:
            op = grid.operator(
                ALLSET_OT_shelf_editor_icon_select.bl_idname,
                text="",
                emboss=True,
                depress=(name == selected),
                **shelf.shelf_icons.icon_ui_kwargs(name),
            )
            op.icon_name = name

    def execute(self, context):
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_icon_select(bpy.types.Operator):
    """Apply the selected icon to the current Shelf button."""
    bl_idname = "allset.shelf_editor_icon_select"
    bl_label = "Select Shelf Icon"
    bl_description = "Select Shelf Icon"
    bl_options = {'INTERNAL'}

    icon_name: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        if self.icon_name in _ICON_HISTORY:
            _ICON_HISTORY.remove(self.icon_name)
        _ICON_HISTORY.append(self.icon_name)
        del _ICON_HISTORY[:-20]
        _wm(context).allset_se_icon = self.icon_name
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_icon_file(bpy.types.Operator, ImportHelper):
    """Use any PNG file as this Shelf button's icon."""
    bl_idname = "allset.shelf_editor_icon_file"
    bl_label = "Choose PNG Shelf Icon"
    bl_description = "Select a PNG file for the current Shelf button"
    bl_options = {'INTERNAL'}

    filter_glob: StringProperty(default="*.png", options={'HIDDEN'})

    def execute(self, context):
        path = os.path.abspath(bpy.path.abspath(self.filepath))
        if not path.lower().endswith(".png") or not os.path.isfile(path):
            self.report({'WARNING'}, "Choose an existing PNG image")
            return {'CANCELLED'}
        _wm(context).allset_se_icon = path
        if path in _ICON_HISTORY:
            _ICON_HISTORY.remove(path)
        _ICON_HISTORY.append(path)
        del _ICON_HISTORY[:-20]
        _redraw(context)
        return {'FINISHED'}
