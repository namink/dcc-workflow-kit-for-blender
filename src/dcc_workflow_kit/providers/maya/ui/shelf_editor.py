# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya-style Shelf Editor in the kit's floating editor window.

The editor works on a private draft of the existing shelves.json document.
Only Save Changes writes the draft back; Cancel discards it.

Code: shelf_editor_draft (draft, shelf operators, Save / Discard), shelf_editor_buttons, shelf_editor_commands
(command search and checks), shelf_editor_icon_picker, shelf_editor_document (shelves.json copy / write / merge);
this module opens the window and keeps the panel, its lists, the window-manager properties and register / unregister.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from . import marked_window, shelf, shelf_editor_draft, window_places
from . import shelf_editor_drag
from .shelf_editor_buttons import (ALLSET_MT_shelf_editor_add_action, ALLSET_OT_shelf_editor_add_button,
                                   ALLSET_OT_shelf_editor_apply_button, ALLSET_OT_shelf_editor_create_action,
                                   ALLSET_OT_shelf_editor_delete_button, ALLSET_OT_shelf_editor_move_button,
                                   ALLSET_OT_shelf_editor_select_button)
from .shelf_editor_commands import action_id_search, menu_search, operator_search
from .shelf_editor_document import _merge_documents  # noqa: F401
from .shelf_editor_draft import (KIND, ALLSET_OT_shelf_editor_add_shelf, ALLSET_OT_shelf_editor_cancel,
                                 ALLSET_OT_shelf_editor_delete_shelf, ALLSET_OT_shelf_editor_duplicate_shelf,
                                 ALLSET_OT_shelf_editor_move_shelf, ALLSET_OT_shelf_editor_rename_shelf,
                                 ALLSET_OT_shelf_editor_save, ALLSET_OT_shelf_editor_select_shelf,
                                 _draft_user_shelf, _start_draft, _sync_contents_list, _sync_properties_list,
                                 _sync_shelves_list, _wm)
from .shelf_editor_icon_picker import (ALLSET_OT_shelf_editor_icon_file, ALLSET_OT_shelf_editor_icon_page,
                                       ALLSET_OT_shelf_editor_icon_picker, ALLSET_OT_shelf_editor_icon_select,
                                       ALLSET_PG_shelf_editor_icon_grid_row, ALLSET_UL_shelf_editor_icon_grid)

TITLE = "Shelf Editor"

# Shelf Editor layout settings.
# The property list grows with the available window height, within these limits.
PROPERTY_MIN_ROWS = 10
PROPERTY_MAX_ROWS = 40
PROPERTY_ROW_HEIGHT = 22


def open_editor(context):
    _start_draft(context)
    # Open at 800 x 1000, whatever the size of the 3D View it is opened from.
    # A one-time marker migrates older oversized saved rectangles while preserving
    # any user-resized dimensions on subsequent launches.
    from . import window_places
    if context.window is not None:
        place_kind = f"marked:{KIND}"
        size_marker = f"{place_kind}_SIZE_V4"
        if window_places.place(size_marker) is None:
            source = context.window
            width, height = 800, 1000
            x = source.x + max(20, (source.width - width) // 2)
            y = source.y + max(20, (source.height - height) // 2)
            window_places.remember(place_kind, (x, y, width, height))
            window_places.remember(size_marker, (2, 0, 0, 0))
        elif window_places.place(place_kind) is None:
            source = context.window
            width, height = 800, 1000
            x = source.x + max(20, (source.width - width) // 2)
            y = source.y + max(20, (source.height - height) // 2)
            window_places.remember(place_kind, (x, y, width, height))
    window = marked_window.open_window(context, KIND)
    if window is None:
        return None
    for area in window.screen.areas:
        area.tag_redraw()
    return window


class ALLSET_OT_shelf_editor_open(bpy.types.Operator):
    """Open the Maya-style floating Shelf Editor"""
    bl_idname = "allset.shelf_editor_open"
    bl_label = "Shelf Editor"

    shelf_id: StringProperty(options={'SKIP_SAVE'})
    index: IntProperty(default=-1, options={'SKIP_SAVE'})

    def execute(self, context):
        draft = shelf_editor_draft       # its _draft is rebound there: read it from that module
        if self.shelf_id and draft._draft is not None \
                and draft._draft_buttons(self.shelf_id) != shelf.editable_buttons(self.shelf_id):
            self.report({'WARNING'}, "Save or cancel pending shelf edits before editing this button")
            return {'CANCELLED'}
        if open_editor(context) is None:
            # A compact editor area may need to be carved across timer ticks.
            # In that case the opening operator is intentionally re-run later;
            # do not report a failure for this deferred first pass.
            from . import window_places
            if window_places.deferred():
                return {'FINISHED'}
            self.report({'ERROR'}, "Could not open the Shelf Editor window")
            return {'CANCELLED'}
        if self.shelf_id:
            bpy.ops.allset.shelf_editor_select_shelf(shelf_id=self.shelf_id)
            _sync_contents_list(_wm(context), self.shelf_id)
            bpy.ops.allset.shelf_editor_select_button(index=self.index)
        return {'FINISHED'}


class ALLSET_PG_shelf_editor_list_item(bpy.types.PropertyGroup):
    """Transient row data used by the scrollable Shelf Contents list."""
    label: StringProperty()
    icon: StringProperty(default="NONE")
    button_index: IntProperty(default=-1)
    is_factory: BoolProperty(default=False)
    shelf_id: StringProperty()
    field: StringProperty()
    row_kind: StringProperty(default="FIELD")


class ALLSET_UL_shelf_editor_shelves(bpy.types.UIList):
    """Independent scrollable list of shelves."""
    bl_idname = "ALLSET_UL_shelf_editor_shelves"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index=0, flt_flag=0):
        row = layout.row(align=True)
        selected = data.allset_se_shelf == item.shelf_id
        op = row.operator(
            ALLSET_OT_shelf_editor_select_shelf.bl_idname,
            text=item.label,
            icon='RADIOBUT_ON' if selected else 'RADIOBUT_OFF',
            depress=selected,
        )
        op.shelf_id = item.shelf_id


class ALLSET_UL_shelf_editor_properties(bpy.types.UIList):
    """Fixed-height, independently scrollable Button Properties editor."""
    bl_idname = "ALLSET_UL_shelf_editor_properties"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index=0, flt_flag=0):
        if item.row_kind == "INFO":
            layout.label(text=item.label, icon='INFO')
            return
        if item.field and hasattr(data, item.field):
            if item.field == "allset_se_icon":
                row = layout.row(align=True)
                row.prop(data, item.field, text=item.label)
                row.operator(
                    ALLSET_OT_shelf_editor_icon_picker.bl_idname,
                    text="",
                    **shelf.shelf_icons.icon_ui_kwargs(data.allset_se_icon or "SCRIPT"),
                )
                return
            layout.prop(data, item.field, text=item.label)


class ALLSET_UL_shelf_editor_contents(bpy.types.UIList):
    """Keep long Shelf Contents lists scrollable without scrolling the editor footer."""
    bl_idname = "ALLSET_UL_shelf_editor_contents"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index=0, flt_flag=0):
        row = layout.row(align=True)
        if item.is_factory:
            # Factory rows may carry a procedural MWK icon identifier. Blender's
            # ``icon`` argument only accepts built-in enum identifiers, so resolve
            # custom preview icons through the preview collection instead.
            icon_kwargs = shelf.shelf_icons.icon_ui_kwargs(
                item.icon if item.icon != 'NONE' else 'DOT')
            row.label(text=item.label, **icon_kwargs)
            row.label(text="Factory", icon='LOCKED')
            return

        icon_kwargs = shelf.shelf_icons.icon_ui_kwargs(item.icon if item.icon != 'NONE' else 'DOT')
        if shelf_editor_drag.enabled(context):
            shelf_editor_drag.draw_grip(row, item.button_index)
        op = row.operator(
            ALLSET_OT_shelf_editor_select_button.bl_idname,
            text=item.label,
            depress=data.allset_se_index == item.button_index,
            **icon_kwargs,
        )
        op.index = item.button_index
        if data.allset_se_index == item.button_index:
            controls = row.row(align=True)
            move_up = controls.operator(ALLSET_OT_shelf_editor_move_button.bl_idname,
                                        text="", icon='TRIA_UP')
            move_up.direction = "UP"
            move_down = controls.operator(ALLSET_OT_shelf_editor_move_button.bl_idname,
                                          text="", icon='TRIA_DOWN')
            move_down.direction = "DOWN"
            controls.operator(ALLSET_OT_shelf_editor_delete_button.bl_idname,
                              text="", icon='TRASH')


class ALLSET_PT_shelf_editor(bpy.types.Panel):
    """Maya-style Shelf Editor shown in the kit's dedicated floating editor window"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_label = TITLE
    bl_options = {'HIDE_HEADER'}
    bl_order = -310

    @classmethod
    def poll(cls, context):
        return marked_window.context_kind(context) == KIND

    def draw(self, context):
        wm = _wm(context)
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        if shelf_editor_draft._draft is None:
            layout.label(text="Shelf Editor session is not initialized", icon='ERROR')
            layout.operator(ALLSET_OT_shelf_editor_open.bl_idname, text="Reopen Editor")
            return

        header = layout.row(align=True)
        header.label(text="Shelf Editor", icon='TOOL_SETTINGS')

        layout.separator()
        split = layout.split(factor=0.38, align=True)
        left = split.column(align=True)
        left.label(text="Shelves", icon='FILE_FOLDER')
        _sync_shelves_list(wm)
        # A: fixed-height scroll viewport. Match B's framed template_list so
        # both columns have the same visible row count and viewport height.
        shelf_list_box = left.box()
        shelf_list_box.template_list(
            ALLSET_UL_shelf_editor_shelves.bl_idname,
            "shelf_editor_shelves",
            wm,
            "allset_se_shelves",
            wm,
            "allset_se_shelves_index",
            rows=14,
            maxrows=14,
            type='DEFAULT',
        )
        left.separator()
        shelf_tools = left.row(align=True)
        shelf_tools.alignment = 'LEFT'
        shelf_tools.operator(ALLSET_OT_shelf_editor_add_shelf.bl_idname, text="", icon='ADD')
        if _draft_user_shelf(wm.allset_se_shelf) is not None:
            shelf_tools.operator(ALLSET_OT_shelf_editor_rename_shelf.bl_idname, text="", icon='GREASEPENCIL')
            shelf_tools.operator(ALLSET_OT_shelf_editor_duplicate_shelf.bl_idname, text="", icon='DUPLICATE')
            shelf_tools.operator(ALLSET_OT_shelf_editor_delete_shelf.bl_idname, text="", icon='TRASH')
            op = shelf_tools.operator(ALLSET_OT_shelf_editor_move_shelf.bl_idname, text="", icon='TRIA_UP')
            op.direction = "UP"
            op = shelf_tools.operator(ALLSET_OT_shelf_editor_move_shelf.bl_idname, text="", icon='TRIA_DOWN')
            op.direction = "DOWN"

        right = split.column(align=True)
        right.label(text="Shelf Contents", icon='PRESET')
        shelf_id = wm.allset_se_shelf
        _sync_contents_list(wm, shelf_id)
        list_box = right.box()
        list_box.template_list(
            ALLSET_UL_shelf_editor_contents.bl_idname,
            "shelf_contents",
            wm,
            "allset_se_items",
            wm,
            "allset_se_list_index",
            rows=14,
            maxrows=14,
            type='DEFAULT',
        )

        # Native popup menu: selecting a type creates the draft item directly.
        # The popup does not occupy layout space or change A/B/C/D dimensions.
        right.menu(
            ALLSET_MT_shelf_editor_add_action.bl_idname,
            text="Add Button",
            icon='ADD',
        )

        layout.separator()
        help_row = layout.row(align=True)
        help_row.label(text="Quick Add: Ctrl+Shift-click a Maya menu item", icon='INFO')
        help_row.label(text="Add Button opens the visual command chooser")
        # The C viewport fills the remaining editor height, while its own
        # UIList remains independently scrollable. Reserve two UI rows for D:
        # one row of breathing room plus the Save / Discard button row.
        region = context.region
        ui_scale = max(1.0, context.preferences.system.ui_scale)
        has_selection = wm.allset_se_index >= 0
        top_fixed_px = (92 + 16 * 22 + 38) * ui_scale
        help_px = 24 * ui_scale
        message_px = (24 * ui_scale) if wm.allset_se_message else 0.0
        footer_px = 2 * 22 * ui_scale
        property_chrome_px = (28 + 28) * ui_scale if has_selection else 0.0
        bottom_gap_px = 8 * ui_scale
        row_px = PROPERTY_ROW_HEIGHT * ui_scale
        if has_selection:
            property_rows = int((float(region.height) - top_fixed_px - help_px
                                 - message_px - footer_px - property_chrome_px
                                 - bottom_gap_px) / row_px)
            property_rows = max(PROPERTY_MIN_ROWS,
                                min(PROPERTY_MAX_ROWS, property_rows))
            box = layout.box()
            box.label(text="Button Properties", icon='PREFERENCES')
            _sync_properties_list(wm)
            box.template_list(
                ALLSET_UL_shelf_editor_properties.bl_idname,
                "shelf_editor_properties",
                wm,
                "allset_se_properties",
                wm,
                "allset_se_properties_index",
                rows=property_rows,
                maxrows=property_rows,
                type='DEFAULT',
            )
            box.operator(ALLSET_OT_shelf_editor_apply_button.bl_idname,
                         text="Apply to Draft", icon='CHECKMARK')

        if wm.allset_se_message:
            layout.separator()
            layout.label(text=wm.allset_se_message, icon='INFO')

        # Keep D at the bottom with a two-row reserve. C consumes the available
        # height above it instead of remaining a short seven-row panel.
        top_rows = 16
        property_rows_for_footer = property_rows if has_selection else 0
        estimated_content = (92 + top_rows * 22 + 38 + help_px / ui_scale
                             + (56 + property_rows_for_footer * 22 if has_selection else 0)
                             + (message_px / ui_scale) + 2 * 22 + 8) * ui_scale
        available = max(0.0, float(region.height) - estimated_content)
        layout.separator(factor=available / (6.0 * ui_scale))
        footer = layout.row(align=True)
        footer.alignment = 'RIGHT'
        footer.operator(ALLSET_OT_shelf_editor_save.bl_idname, text="Save", icon='FILE_TICK')
        footer.operator(ALLSET_OT_shelf_editor_cancel.bl_idname, text="Discard", icon='LOOP_BACK')


classes = (
    ALLSET_OT_shelf_editor_open,
    ALLSET_OT_shelf_editor_icon_page,
    ALLSET_PG_shelf_editor_icon_grid_row,
    ALLSET_UL_shelf_editor_icon_grid,
    ALLSET_OT_shelf_editor_icon_picker,
    ALLSET_OT_shelf_editor_icon_select,
    ALLSET_OT_shelf_editor_icon_file,
    ALLSET_OT_shelf_editor_select_shelf,
    ALLSET_OT_shelf_editor_select_button,
    ALLSET_OT_shelf_editor_add_shelf,
    ALLSET_OT_shelf_editor_rename_shelf,
    ALLSET_OT_shelf_editor_duplicate_shelf,
    ALLSET_OT_shelf_editor_delete_shelf,
    ALLSET_OT_shelf_editor_move_shelf,
    ALLSET_OT_shelf_editor_add_button,
    ALLSET_MT_shelf_editor_add_action,
    ALLSET_OT_shelf_editor_create_action,
    ALLSET_OT_shelf_editor_apply_button,
    ALLSET_OT_shelf_editor_delete_button,
    ALLSET_OT_shelf_editor_move_button,
    *shelf_editor_drag.classes,
    ALLSET_OT_shelf_editor_save,
    ALLSET_OT_shelf_editor_cancel,
    ALLSET_PG_shelf_editor_list_item,
    ALLSET_UL_shelf_editor_shelves,
    ALLSET_UL_shelf_editor_properties,
    ALLSET_UL_shelf_editor_contents,
    ALLSET_PT_shelf_editor,
)

_WM_PROPS = (
    "allset_se_shelf", "allset_se_index", "allset_se_label", "allset_se_icon",
    "allset_se_type", "allset_se_script", "allset_se_menu", "allset_se_operator",
    "allset_se_props", "allset_se_tooltip", "allset_se_message",
    "allset_se_action_id", "allset_se_action_code", "allset_se_space_type",
    "allset_se_tool_space_type", "allset_se_tool_mode",
    "allset_se_required_mode", "allset_se_object_type",
    "allset_se_items", "allset_se_items_signature", "allset_se_list_index",
    "allset_se_shelves", "allset_se_shelves_signature", "allset_se_shelves_index",
    "allset_se_properties", "allset_se_properties_signature", "allset_se_properties_index",
    "allset_se_icon_grid_rows", "allset_se_icon_grid_rows_index",
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.allset_se_shelf = StringProperty(options={'SKIP_SAVE'})
    wm.allset_se_index = IntProperty(default=-1, options={'SKIP_SAVE'})
    wm.allset_se_label = StringProperty(name="Label", options={'SKIP_SAVE'})
    wm.allset_se_icon = StringProperty(name="Icon", search=shelf.shelf_icons.icon_search, options={'SKIP_SAVE'})
    wm.allset_se_type = EnumProperty(
        name="Command Type",
        items=(
            ("OPERATOR", "Blender Operator", "Run a Blender Operator"),
            ("MAYA_MENU_ITEM", "Maya Menu Item", "Run a Maya Workflow Kit menu item"),
            ("MENU", "Menu", "Open a Blender native or MayaWorkflow Menu by Menu ID"),
            ("TOOL", "Tool", "Activate a Blender Tool"),
            ("PYTHON", "Python", "Run a Python command"),
            ("SEPARATOR", "Separator", "Visual separator"),
        ),
        options={'SKIP_SAVE'},
        update=shelf_editor_draft.on_type_changed,
    )
    wm.allset_se_script = StringProperty(name="Python", options={'SKIP_SAVE'})
    wm.allset_se_menu = StringProperty(name="Maya Menu Item", search=menu_search, options={'SKIP_SAVE'})
    wm.allset_se_operator = StringProperty(name="Blender Operator", search=operator_search, options={'SKIP_SAVE'})
    wm.allset_se_props = StringProperty(name="Operator Properties", default="", options={'SKIP_SAVE'})
    wm.allset_se_tooltip = StringProperty(name="Tooltip", options={'SKIP_SAVE'})
    wm.allset_se_message = StringProperty(options={'SKIP_SAVE'})
    wm.allset_se_action_id = StringProperty(
        name="Menu / Tool ID",
        search=action_id_search,
        description="Menu: Blender native Menu or MayaWorkflow Menu, e.g. XXX_MT_xxx",
        options={'SKIP_SAVE'},
    )
    wm.allset_se_action_code = StringProperty(name="Action Code", options={'SKIP_SAVE'})
    wm.allset_se_space_type = EnumProperty(
        name="Editor Space",
        items=(
            ("AUTO", "Auto", "Infer the appropriate editor from the selected action"),
            ("ANY", "Any Editor", "Do not require a specific editor"),
            ("VIEW_3D", "3D View", "Execute in a 3D View"),
            ("IMAGE_EDITOR", "Image / UV Editor", "Execute in an Image or UV Editor"),
            ("NODE_EDITOR", "Node Editor", "Execute in a Node Editor"),
            ("GRAPH_EDITOR", "Graph Editor", "Execute in a Graph Editor"),
            ("DOPESHEET_EDITOR", "Dope Sheet", "Execute in a Dope Sheet"),
            ("NLA_EDITOR", "NLA Editor", "Execute in an NLA Editor"),
            ("SEQUENCE_EDITOR", "Video Sequencer", "Execute in the Video Sequencer"),
            ("CLIP_EDITOR", "Movie Clip Editor", "Execute in a Movie Clip Editor"),
            ("TEXT_EDITOR", "Text Editor", "Execute in a Text Editor"),
            ("CONSOLE", "Python Console", "Execute in the Python Console"),
            ("OUTLINER", "Outliner", "Execute in the Outliner"),
        ),
        default="AUTO",
        options={'SKIP_SAVE'},
    )
    wm.allset_se_tool_space_type = EnumProperty(
        name="Editor",
        items=(
            ("AUTO", "Auto", "Infer the appropriate editor from the Tool ID"),
            ("VIEW_3D", "3D View", "Activate the tool in the 3D View"),
            ("IMAGE_EDITOR", "UV Editor", "Activate the tool in the UV Editor"),
        ),
        default="AUTO",
        options={'SKIP_SAVE'},
    )
    wm.allset_se_tool_mode = EnumProperty(
        name="Required Mode",
        description="Infer the required mode automatically, or explicitly restrict execution",
        items=(
            ("AUTO", "Auto", "Infer the mode from the Tool ID"),
            ("ANY", "Any Mode", "Do not require a specific mode"),
            ("OBJECT", "Object Mode", "Require Object Mode"),
            ("EDIT_MESH", "Mesh Edit Mode", "Require Mesh Edit Mode"),
            ("SCULPT", "Sculpt Mode", "Require Sculpt Mode"),
            ("PAINT_VERTEX", "Vertex Paint", "Require Vertex Paint Mode"),
            ("PAINT_WEIGHT", "Weight Paint", "Require Weight Paint Mode"),
            ("PAINT_TEXTURE", "Texture Paint", "Require Texture Paint Mode"),
            ("EDIT_CURVE", "Curve Edit Mode", "Require Curve Edit Mode"),
            ("SCULPT_CURVES", "Curves Sculpt Mode", "Require Curves Sculpt Mode"),
            ("EDIT_ARMATURE", "Armature Edit Mode", "Require Armature Edit Mode"),
            ("POSE", "Pose Mode", "Require Pose Mode"),
            ("EDIT_LATTICE", "Lattice Edit Mode", "Require Lattice Edit Mode"),
            ("EDIT_METABALL", "Metaball Edit Mode", "Require Metaball Edit Mode"),
            ("EDIT_SURFACE", "Surface Edit Mode", "Require Surface Edit Mode"),
            ("EDIT_TEXT", "Text Edit Mode", "Require Text Edit Mode"),
            ("PARTICLE", "Particle Edit Mode", "Require Particle Edit Mode"),
            ("EDIT_GREASE_PENCIL", "Grease Pencil Edit Mode", "Require Grease Pencil Edit Mode"),
            ("SCULPT_GREASE_PENCIL", "Grease Pencil Sculpt", "Require Grease Pencil Sculpt Mode"),
            ("PAINT_GREASE_PENCIL", "Grease Pencil Draw", "Require Grease Pencil Draw Mode"),
            ("WEIGHT_GREASE_PENCIL", "Grease Pencil Weight Paint", "Require Grease Pencil Weight Paint Mode"),
            ("VERTEX_GREASE_PENCIL", "Grease Pencil Vertex Paint", "Require Grease Pencil Vertex Paint Mode"),
        ),
        default="AUTO",
        options={'SKIP_SAVE'},
    )
    wm.allset_se_required_mode = EnumProperty(
        name="Required Mode",
        description="Infer the required mode from the selected action, or set a specific mode",
        items=(
            ("AUTO", "Auto", "Infer a compatible mode from the action"),
            ("ANY", "Any Mode", "Do not require a specific mode"),
            ("OBJECT", "Object Mode", "Require Object Mode"),
            ("EDIT_MESH", "Mesh Edit Mode", "Require Mesh Edit Mode"),
            ("SCULPT", "Sculpt Mode", "Require Sculpt Mode"),
            ("PAINT_VERTEX", "Vertex Paint", "Require Vertex Paint Mode"),
            ("PAINT_WEIGHT", "Weight Paint", "Require Weight Paint Mode"),
            ("PAINT_TEXTURE", "Texture Paint", "Require Texture Paint Mode"),
            ("EDIT_CURVE", "Curve Edit Mode", "Require Curve Edit Mode"),
            ("SCULPT_CURVES", "Curves Sculpt Mode", "Require Curves Sculpt Mode"),
            ("EDIT_ARMATURE", "Armature Edit Mode", "Require Armature Edit Mode"),
            ("POSE", "Pose Mode", "Require Pose Mode"),
            ("EDIT_LATTICE", "Lattice Edit Mode", "Require Lattice Edit Mode"),
            ("EDIT_METABALL", "Metaball Edit Mode", "Require Metaball Edit Mode"),
            ("EDIT_SURFACE", "Surface Edit Mode", "Require Surface Edit Mode"),
            ("EDIT_TEXT", "Text Edit Mode", "Require Text Edit Mode"),
            ("PARTICLE", "Particle Edit Mode", "Require Particle Edit Mode"),
            ("EDIT_GREASE_PENCIL", "Grease Pencil Edit Mode", "Require Grease Pencil Edit Mode"),
            ("SCULPT_GREASE_PENCIL", "Grease Pencil Sculpt", "Require Grease Pencil Sculpt Mode"),
            ("PAINT_GREASE_PENCIL", "Grease Pencil Draw", "Require Grease Pencil Draw Mode"),
            ("WEIGHT_GREASE_PENCIL", "Grease Pencil Weight Paint", "Require Grease Pencil Weight Paint Mode"),
            ("VERTEX_GREASE_PENCIL", "Grease Pencil Vertex Paint", "Require Grease Pencil Vertex Paint Mode"),
        ),
        default="AUTO",
        options={'SKIP_SAVE'},
    )
    wm.allset_se_object_type = EnumProperty(
        name="Object Type",
        description="Infer the compatible object type, or restrict execution to a specific type",
        items=(
            ("AUTO", "Auto", "Infer a compatible object type from the action"),
            ("ANY", "Any Object", "Do not require a specific active object type"),
            ("MESH", "Mesh", "Require an active Mesh object"),
            ("CURVE", "Curve", "Require an active Curve object"),
            ("SURFACE", "Surface", "Require an active Surface object"),
            ("META", "Metaball", "Require an active Metaball object"),
            ("FONT", "Text", "Require an active Text object"),
            ("ARMATURE", "Armature", "Require an active Armature object"),
            ("LATTICE", "Lattice", "Require an active Lattice object"),
            ("GPENCIL", "Grease Pencil (Legacy)", "Require a legacy Grease Pencil object"),
            ("GREASEPENCIL", "Grease Pencil", "Require a Grease Pencil object"),
            ("EMPTY", "Empty", "Require an Empty object"),
        ),
        default="AUTO",
        options={'SKIP_SAVE'},
    )
    wm.allset_se_items = bpy.props.CollectionProperty(type=ALLSET_PG_shelf_editor_list_item,
                                                       options={'SKIP_SAVE'})
    wm.allset_se_items_signature = StringProperty(options={'SKIP_SAVE'})
    wm.allset_se_list_index = IntProperty(default=0, options={'SKIP_SAVE'})
    wm.allset_se_shelves = bpy.props.CollectionProperty(type=ALLSET_PG_shelf_editor_list_item,
                                                         options={'SKIP_SAVE'})
    wm.allset_se_shelves_signature = StringProperty(options={'SKIP_SAVE'})
    wm.allset_se_shelves_index = IntProperty(default=0, options={'SKIP_SAVE'})
    wm.allset_se_properties = bpy.props.CollectionProperty(type=ALLSET_PG_shelf_editor_list_item,
                                                            options={'SKIP_SAVE'})
    wm.allset_se_properties_signature = StringProperty(options={'SKIP_SAVE'})
    wm.allset_se_properties_index = IntProperty(default=0, options={'SKIP_SAVE'})
    wm.allset_se_icon_grid_rows = bpy.props.CollectionProperty(
        type=ALLSET_PG_shelf_editor_icon_grid_row,
        options={'SKIP_SAVE'},
    )
    wm.allset_se_icon_grid_rows_index = IntProperty(default=0, options={'SKIP_SAVE'})
    marked_window.KINDS[KIND] = ("show_properties_scene", "show_properties_data")
    window_places.STRICT.add(f"marked:{KIND}")


def unregister():
    shelf_editor_draft._draft = None
    shelf_editor_draft._draft_base = None
    marked_window.KINDS.pop(KIND, None)
    window_places.STRICT.discard(f"marked:{KIND}")
    for name in _WM_PROPS:
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
