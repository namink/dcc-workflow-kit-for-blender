# SPDX-License-Identifier: GPL-3.0-or-later
"""Shelf Editor operators for the buttons of the selected shelf: select, Add Button, the Add Shelf Button menu that
creates a button by command type (``allset.shelf_editor_create_action``), Apply Button Changes (checks the command,
then writes the record into the draft), Delete and Move Button.
Related: shelf_editor_draft.py, shelf_editor_commands.py."""

import json

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from . import shelf
from .shelf_editor_commands import (_operator_ids, _parse_operator_props_body, _validate_operator_properties,
                                    action_id_search, icon_search)
from .shelf_editor_draft import (_draft_buttons, _load_button, _redraw, _set_message, _sync_contents_list,
                                 _sync_properties_list, _wm)


ADD_MENU_COLUMNS = 2


class ALLSET_OT_shelf_editor_select_button(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_select_button"
    bl_label = "Select Button"
    bl_options = {'INTERNAL'}

    index: IntProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        wm = _wm(context)
        _load_button(context, self.index)

        # Keep the native UIList active row aligned with the selected editable
        # button. Factory rows are read-only and must not retain the active-row
        # highlight when a custom button is selected.
        for row_index, item in enumerate(wm.allset_se_items):
            if not item.is_factory and item.button_index == self.index:
                wm.allset_se_list_index = row_index
                break

        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_add_button(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_add_button"
    bl_label = "Add Button"

    def execute(self, context):
        wm = _wm(context)
        buttons = _draft_buttons(wm.allset_se_shelf, create=True)
        if buttons is None:
            self.report({'WARNING'}, "This shelf does not accept custom buttons")
            return {'CANCELLED'}
        buttons.append({"label": "New Button", "icon": "SCRIPT", "script": "print('Hello')"})
        _load_button(context, len(buttons) - 1)
        _set_message(context, "New button added to the draft; edit its properties")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_MT_shelf_editor_add_action(bpy.types.Menu):
    bl_idname = "ALLSET_MT_shelf_editor_add_action"
    bl_label = "Add Shelf Button"

    def draw(self, context):
        flow = self.layout.column_flow(columns=ADD_MENU_COLUMNS, align=True)
        choices = (
            ("OPERATOR", "Operator", "CONSOLE", "Blender Operator"),
            ("MAYA_MENU_ITEM", "Maya Menu Item", "LINENUMBERS_ON", "Maya Workflow Kit menu path"),
            ("MENU", "Menu", "MENU_PANEL", "Blender native Menu or MayaWorkflow Menu ID"),
            ("TOOL", "Tool", "TOOL_SETTINGS", "Activate a Blender Tool"),
            ("PYTHON", "Python", "CONSOLE", "Python command"),
            ("SEPARATOR", "Separator", "REMOVE", "Visual separator"),
        )
        for kind, label, icon, tip in choices:
            op = flow.operator(
                ALLSET_OT_shelf_editor_create_action.bl_idname,
                text=label,
                icon=icon,
            )
            op.action_type = kind
            op.help_text = tip


class ALLSET_OT_shelf_editor_create_action(bpy.types.Operator):
    """Create a Shelf button using the selected command type."""
    bl_idname = "allset.shelf_editor_create_action"
    bl_label = "Add Shelf Button"
    bl_description = "Create a Shelf button using the selected command type."

    action_type: StringProperty(options={'HIDDEN'})
    help_text: StringProperty(options={'HIDDEN'})
    label: StringProperty(name="Label", default="New Button")
    icon: StringProperty(name="Icon", default="SCRIPT", search=icon_search)
    tooltip: StringProperty(name="Tooltip")
    target: StringProperty(name="Command / ID", search=action_id_search)
    code: StringProperty(
        name="Python",
        default="import bpy\\n\\nbpy.ops.mesh.primitive_cube_add()",
    )
    properties_json: StringProperty(name="Operator Properties", default="{}")

    @classmethod
    def description(cls, context, properties):
        return properties.help_text or "Add a Shelf button using the selected command type."

    def invoke(self, context, event):
        if self.action_type == "OPERATOR":
            self.label = "Add Cube"
            self.icon = "MESH_CUBE"
            self.target = "mesh.primitive_cube_add"
        elif self.action_type == "MAYA_MENU_ITEM":
            self.label = "Create Cube"
            self.target = "Create/Polygon Primitives/Cube"
        elif self.action_type == "MENU":
            self.label = "View Menu"
            self.target = "VIEW3D_MT_view"
        elif self.action_type == "TOOL":
            self.label = "Move Tool"
            self.target = "builtin.move"
        elif self.action_type == "PYTHON":
            self.label = "Python: Add Cube"
            self.code = "import bpy\\n\\nbpy.ops.mesh.primitive_cube_add()"
        return self.execute(context)

    def execute(self, context):
        buttons = _draft_buttons(_wm(context).allset_se_shelf, create=True)
        if buttons is None:
            self.report({'WARNING'}, "This shelf does not accept custom buttons")
            return {'CANCELLED'}

        record = {
            "label": self.label.strip() or "New Button",
            "icon": shelf._valid_icon(self.icon),
            "tooltip": self.tooltip.strip(),
        }
        kind = self.action_type
        if kind == "SEPARATOR":
            record["label"] = "Separator"
            record["icon"] = "NONE"
            record.update(type="separator", action={"type": "separator"})
        elif kind == "OPERATOR":
            record.update(type="action", action={
                "type": "operator",
                "id": self.target.strip() or "mesh.primitive_cube_add",
                "properties": json.loads(self.properties_json or "{}"),
                "space_type": "VIEW_3D",
            })
        elif kind == "MAYA_MENU_ITEM":
            record["menu"] = self.target.strip() or "Create/Polygon Primitives/Cube"
            record["space_type"] = "VIEW_3D"
        elif kind == "MENU":
            record.update(type="action", action={
                "type": "blender_menu",
                "id": self.target.strip() or "VIEW3D_MT_view",
                "space_type": "VIEW_3D",
            })
        elif kind == "TOOL":
            record.update(type="action", action={
                "type": "tool",
                "id": self.target.strip() or "builtin.move",
                "space_type": "VIEW_3D",
            })
        elif kind == "PYTHON":
            code = self.code.strip() or "import bpy\\n\\nbpy.ops.mesh.primitive_cube_add()"
            record.update(type="action", action={"type": "python", "code": code})
        else:
            return {'CANCELLED'}

        buttons.append(record)
        _load_button(context, len(buttons) - 1)
        _set_message(context, f"Added {record['label']} to draft; edit its properties below")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_apply_button(bpy.types.Operator):
    """Apply edited Shelf button properties without changing unrelated button data."""
    bl_idname = "allset.shelf_editor_apply_button"
    bl_label = "Apply Button Changes"

    def execute(self, context):
        wm = _wm(context)
        buttons = _draft_buttons(wm.allset_se_shelf, create=True)
        index = wm.allset_se_index
        if buttons is None or not 0 <= index < len(buttons):
            self.report({'WARNING'}, "Select a custom button first")
            return {'CANCELLED'}

        old = buttons[index]
        record = dict(old)
        label = wm.allset_se_label.strip() or "Button"
        record["label"] = label
        record["icon"] = shelf._valid_icon(wm.allset_se_icon)
        record["tooltip"] = wm.allset_se_tooltip.strip()
        kind = wm.allset_se_type
        space_type = wm.allset_se_space_type

        if kind == "SEPARATOR":
            record["icon"] = "NONE"
            record.pop("menu", None)
            record.pop("script", None)
            record.pop("operator", None)
            record.pop("props", None)
            record.pop("space_type", None)
            record.update(type="separator", action={"type": "separator"})
        elif kind == "MAYA_MENU_ITEM":
            from . import menu_map
            path = wm.allset_se_menu.strip()
            if path not in menu_map.MAP:
                self.report({'WARNING'}, "Choose a valid Maya menu item")
                return {'CANCELLED'}
            record["menu"] = path
            record["space_type"] = space_type
            record["required_mode"] = wm.allset_se_required_mode
            record["object_type"] = wm.allset_se_object_type
            record.pop("script", None)
            record.pop("type", None)
            record.pop("action", None)
            record.pop("operator", None)
            record.pop("props", None)
        elif kind == "MENU":
            target = wm.allset_se_action_id.strip()
            if not target or bpy.types.Menu.bl_rna_get_subclass_py(target) is None:
                self.report({'WARNING'}, "Choose a registered Blender or MayaWorkflow Menu ID")
                return {'CANCELLED'}
            record.pop("menu", None)
            record.pop("script", None)
            record.update(type="action", action={
                "type": "blender_menu",
                "id": target,
                "space_type": space_type,
                "required_mode": wm.allset_se_required_mode,
                "object_type": wm.allset_se_object_type,
            })
        elif kind == "OPERATOR":
            op_id = wm.allset_se_operator.strip()
            if op_id not in _operator_ids():
                self.report({'WARNING'}, "Choose a valid Blender Operator")
                return {'CANCELLED'}
            # Operator parameters are edited as JSON members between UI-supplied braces.
            # An empty field means no explicit overrides: {}.
            try:
                props = _parse_operator_props_body(wm.allset_se_props)
            except (TypeError, ValueError) as ex:
                self.report({'WARNING'}, f"Operator Properties must be valid JSON: {ex}")
                return {'CANCELLED'}
            if not isinstance(props, dict):
                self.report({'WARNING'}, "Operator Properties must be a JSON object, for example {}")
                return {'CANCELLED'}
            problem = _validate_operator_properties(op_id, props)
            if problem:
                self.report({'WARNING'}, problem)
                return {'CANCELLED'}
            record.pop("menu", None)
            record.pop("script", None)
            record.pop("operator", None)
            record.pop("props", None)
            record.update(type="action", action={
                "type": "operator",
                "id": op_id,
                "properties": props,
                "space_type": space_type,
                "required_mode": wm.allset_se_required_mode,
                "object_type": wm.allset_se_object_type,
            })
        elif kind == "PYTHON":
            code = wm.allset_se_script
            if not code.strip():
                self.report({'WARNING'}, "Python command cannot be empty")
                return {'CANCELLED'}
            record.pop("menu", None)
            record.pop("script", None)
            record.pop("operator", None)
            record.pop("props", None)
            record.update(type="action", action={"type": "python", "code": code})
        elif kind == "TOOL":
            target = wm.allset_se_action_id.strip()
            if not target:
                self.report({'WARNING'}, "Enter a Tool ID")
                return {'CANCELLED'}
            record.pop("menu", None)
            record.pop("script", None)
            record.update(type="action", action={
                "type": "tool",
                "id": target,
                "space_type": wm.allset_se_tool_space_type,
                "required_mode": wm.allset_se_tool_mode,
                "object_type": wm.allset_se_object_type,
            })
        else:
            self.report({'WARNING'}, "Unsupported Shelf button type")
            return {'CANCELLED'}

        # Commit the record to the draft before refreshing any transient UI.
        # Keep the selected button index stable and immediately rebuild the
        # visible Shelf Contents rows so the first Apply is reflected at once.
        buttons[index] = record

        # The contents UIList is a cached WindowManager collection. Updating
        # _draft alone does not guarantee that its label/icon rows are refreshed
        # during this operator execution.
        _sync_contents_list(wm, wm.allset_se_shelf)
        _sync_properties_list(wm)

        _set_message(context, f"Updated: {label} (not saved yet)")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_delete_button(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_delete_button"
    bl_label = "Delete Button"

    def execute(self, context):
        wm = _wm(context)
        buttons = _draft_buttons(wm.allset_se_shelf) or []
        index = wm.allset_se_index
        if not 0 <= index < len(buttons):
            return {'CANCELLED'}
        del buttons[index]
        _load_button(context, min(index, len(buttons) - 1))
        _set_message(context, "Button deleted from the draft (not saved yet)")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_move_button(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_move_button"
    bl_label = "Move Button"

    direction: EnumProperty(items=(("UP", "Up", ""), ("DOWN", "Down", "")))

    def execute(self, context):
        wm = _wm(context)
        buttons = _draft_buttons(wm.allset_se_shelf) or []
        index = wm.allset_se_index
        target = index + (-1 if self.direction == "UP" else 1)
        if not 0 <= index < len(buttons) or not 0 <= target < len(buttons):
            return {'CANCELLED'}
        buttons[index], buttons[target] = buttons[target], buttons[index]
        _load_button(context, target)
        _redraw(context)
        return {'FINISHED'}
