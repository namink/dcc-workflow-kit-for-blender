# SPDX-License-Identifier: GPL-3.0-or-later
"""Operators that change shelves: show / step a tab, New / Delete Shelf, Add / Edit / Delete Button, Add Shelf
Button by command type (operator, menu, popup, tool, Python, separator) and Add Last Command. Each saves
``shelves.json`` and redraws every window (``_redraw``; ``schedule_redraw`` forces one more frame).
Related: shelf_store.py, shelf_editor.py."""

import json

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from . import shelf_data, shelf_icons

from .shelf_store import USER_PREFIX, user_data, save_user, user_shelf, editable_buttons, shelves, current, set_current


def _registered_operator(identifier):
    """Return whether Blender currently has this Operator registered, including add-on namespaces."""
    if not isinstance(identifier, str) or "." not in identifier:
        return False
    module, name = identifier.split(".", 1)
    try:
        getattr(getattr(bpy.ops, module), name).get_rna_type()
    except (AttributeError, RuntimeError, TypeError):
        return False
    return True


class ALLSET_OT_shelf_select(bpy.types.Operator):
    """Show this shelf"""
    bl_idname = "allset.shelf_select"
    bl_label = "Select Shelf"
    bl_options = {'INTERNAL'}

    shelf: StringProperty()

    def execute(self, context):
        set_current(context, self.shelf)
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_step(bpy.types.Operator):
    """Previous / next shelf tab"""
    bl_idname = "allset.shelf_step"
    bl_label = "Next Shelf"
    bl_options = {'INTERNAL'}

    forward: BoolProperty(default=True)

    def execute(self, context):
        ids = [s[0] for s in shelves()]
        i = ids.index(current(context)) + (1 if self.forward else -1)
        set_current(context, ids[i % len(ids)])
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_new(bpy.types.Operator):
    """Add an empty shelf (Maya shelf menu > New Shelf)"""
    bl_idname = "allset.shelf_new"
    bl_label = "New Shelf"

    name: StringProperty(name="Name", default="Shelf1")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        name = self.name.strip() or "Shelf"
        base, n = name, 1
        while user_shelf(name) is not None:
            n += 1
            name = f"{base}{n}"
        user_data()["shelves"].append({"name": name, "buttons": []})
        save_user()
        set_current(context, USER_PREFIX + name)
        _redraw(context)
        return {'FINISHED'}


def _current_user_shelf(context):
    cur = current(context)
    return user_shelf(cur[len(USER_PREFIX):]) if cur.startswith(USER_PREFIX) else None


class ALLSET_OT_shelf_delete(bpy.types.Operator):
    """Delete the current user shelf (factory shelves stay)"""
    bl_idname = "allset.shelf_delete"
    bl_label = "Delete Shelf"

    @classmethod
    def poll(cls, context):
        return _current_user_shelf(context) is not None and len(user_data()["shelves"]) > 1

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        s = _current_user_shelf(context)
        user_data()["shelves"].remove(s)
        save_user()
        set_current(context, shelf_data.DEFAULT)
        _redraw(context)
        return {'FINISHED'}


class _ButtonProps:
    label: StringProperty(name="Label", default="Script")
    icon: StringProperty(name="Icon", default="SCRIPT", search=shelf_icons.icon_search,
                         description="Blender, PNG, or Maya Workflow Kit icon identifier")
    script: StringProperty(name="Python", default="print('hello')")
    from_text: BoolProperty(name="From Text Editor",
                            description="Use the text open in a Text Editor instead of the line above")

    def _source(self, context):
        if self.from_text:
            text = next((a.spaces.active.text for a in context.screen.areas
                         if a.type == 'TEXT_EDITOR' and a.spaces.active.text), None)
            if text is None:
                text = bpy.data.texts[0] if bpy.data.texts else None
            return text.as_string() if text is not None else None
        return self.script


def _valid_icon(name):
    """Accept Blender built-in, PNG, and Maya Workflow Kit icon identifiers."""
    name = str(name or "").strip()
    return name if shelf_icons.is_icon_name(name) else 'SCRIPT'


class ALLSET_OT_shelf_add_button(_ButtonProps, bpy.types.Operator):
    """Add a Python script button to the current user shelf"""
    bl_idname = "allset.shelf_add_button"
    bl_label = "Add Button"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _current_user_shelf(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        source = self._source(context)
        if not source:
            self.report({'WARNING'}, "No script")
            return {'CANCELLED'}
        _current_user_shelf(context)["buttons"].append(
            {"label": self.label, "icon": _valid_icon(self.icon), "script": source})
        save_user()
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_edit_button(_ButtonProps, bpy.types.Operator):
    """Change a button of the current user shelf"""
    bl_idname = "allset.shelf_edit_button"
    bl_label = "Edit Button"
    bl_options = {'REGISTER'}

    index: IntProperty()

    def invoke(self, context, event):
        buttons = editable_buttons(current(context)) or []
        if not 0 <= self.index < len(buttons):
            return {'CANCELLED'}
        b = buttons[self.index]
        self.label = b.get("label", "Button")
        self.icon = b.get("icon", "SCRIPT")
        self.script = b.get("script", "")
        action = b.get("action") or {}
        if action.get("type") == "python":
            self.script = action.get("code", self.script)
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        buttons = editable_buttons(current(context)) or []
        if not 0 <= self.index < len(buttons):
            return {'CANCELLED'}
        source = self._source(context)
        old = buttons[self.index]
        new = dict(old)
        new["label"] = self.label
        new["icon"] = _valid_icon(self.icon)
        action = dict(old.get("action") or {})
        if action.get("type") == "python":
            if source:
                action["code"] = source
            new["action"] = action
        elif "script" in old and source:
            new["script"] = source
        buttons[self.index] = new
        save_user()
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_remove_button(bpy.types.Operator):
    """Delete a button from the current user shelf"""
    bl_idname = "allset.shelf_remove_button"
    bl_label = "Delete Button"
    bl_options = {'REGISTER'}

    index: IntProperty()
    shelf: StringProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.shelf = self.shelf or current(context)
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        buttons = editable_buttons(self.shelf or current(context)) or []
        if not 0 <= self.index < len(buttons):
            return {'CANCELLED'}
        del buttons[self.index]
        save_user()
        _redraw(context)
        return {'FINISHED'}


class ALLSET_MT_shelf_add_action(bpy.types.Menu):
    """Maya-style visual chooser for the kind of command a Shelf Button runs."""
    bl_idname = "ALLSET_MT_shelf_add_action"
    bl_label = "Add Shelf Button"

    def draw(self, context):
        layout = self.layout
        # Explicit split columns keep the submenu compact and predictable.
        split = layout.split(factor=0.5, align=True)
        columns = (split.column(align=True), split.column(align=True))
        choices = (
            ("OPERATOR", "Operator", "CONSOLE", "Run a Blender Operator and optionally set its RNA properties"),
            ("MENU", "Menu", "LINENUMBERS_ON", "Open a Maya Workflow Kit menu item or Blender menu"),
            ("POPUP", "Popup / UI", "WINDOW", "Open a Blender popup, pie menu, or custom UI operator"),
            ("TOOL", "Tool", "TOOL_SETTINGS", "Activate a Blender or Maya Workflow Kit tool"),
            ("PYTHON", "Python", "CONSOLE", "Run a custom Python command"),
            ("SEPARATOR", "Separator", "REMOVE", "Insert a visual separator in the Shelf"),
        )
        for index, (kind, label, icon, description) in enumerate(choices):
            column = columns[index % 2]
            op = column.operator(ALLSET_OT_shelf_add_action.bl_idname, text=label, icon=icon)
            op.action_type = kind
            op.help_text = description


class ALLSET_OT_shelf_add_action(bpy.types.Operator):
    """Add a Shelf Button using a selected command type."""
    bl_idname = "allset.shelf_add_action"
    bl_label = "Add Shelf Button"
    bl_options = {'REGISTER'}

    action_type: StringProperty(options={'HIDDEN'})
    help_text: StringProperty(options={'HIDDEN'})
    label: StringProperty(name="Label", default="New Button")
    icon: StringProperty(name="Icon", default="SCRIPT", search=shelf_icons.icon_search,
                         description="Blender, PNG, or Maya Workflow Kit icon identifier")
    tooltip: StringProperty(name="Tooltip")
    operator_id: StringProperty(name="Operator", description="Operator identifier, e.g. mesh.bevel")
    properties_json: StringProperty(name="Properties (JSON)", default="{}",
                                     description="Optional Operator properties as a JSON object")
    menu_kind: bpy.props.EnumProperty(name="Menu Type", items=(
        ('MAYA', "Maya Menu Item", "Use a Maya Workflow Kit menu path"),
        ('BLENDER', "Blender Menu", "Call a registered Blender Menu class"),
        ('PIE', "Blender Pie Menu", "Call a registered Blender Pie Menu class"),
        ('CUSTOM_UI', "Custom UI Operator", "Invoke an add-on Operator that opens its own UI"),
    ), default='MAYA')
    menu_id: StringProperty(name="Menu Path / ID",
                            description="Maya menu path or Blender Menu bl_idname")
    ui_operator_id: StringProperty(name="UI Operator ID", description="Operator that opens the custom interface")
    tool_id: StringProperty(name="Tool ID", description="Tool identifier, e.g. builtin.move")
    space_type: bpy.props.EnumProperty(name="Editor", items=(
        ('VIEW_3D', "3D View", "Activate the tool in the 3D View"),
        ('IMAGE_EDITOR', "UV Editor", "Activate the tool in the UV Editor"),
    ), default='VIEW_3D')
    python_code: StringProperty(name="Python", default="print('Hello')", options={'TEXTEDIT_UPDATE'})

    @classmethod
    def description(cls, context, properties):
        return properties.help_text or "Add a Shelf button using the selected command type."

    def invoke(self, context, event):
        if self.action_type == 'SEPARATOR':
            return self.execute(context)
        if self.action_type == 'OPERATOR' and not self.operator_id:
            self.operator_id = "mesh.primitive_cube_add"
            self.properties_json = '{"size": 2.0}'
            if self.label == "New Button":
                self.label = "Add Cube"
            if self.icon == "SCRIPT":
                self.icon = "MESH_CUBE"
        elif self.action_type == 'MENU' and not self.menu_id:
            self.menu_id = "Create/Polygon Primitives/Cube"
            if self.label == "New Button":
                self.label = "Create Cube"
        elif self.action_type == 'POPUP' and not self.menu_id and not self.ui_operator_id:
            self.menu_kind = 'BLENDER'
            self.menu_id = "VIEW3D_MT_view"
            if self.label == "New Button":
                self.label = "View Menu"
        elif self.action_type == 'TOOL' and not self.tool_id:
            self.tool_id = "builtin.move"
            if self.label == "New Button":
                self.label = "Move Tool"
        elif self.action_type in {'PYTHON', 'LEGACY_PYTHON'} and self.python_code == "print('Hello')":
            self.python_code = "import bpy\n\nbpy.ops.mesh.primitive_cube_add(size=2.0)"
            if self.label == "New Button":
                self.label = "Python: Add Cube"
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        layout = self.layout
        header = layout.row()
        header.label(text=self.help_text or self.action_type.title(), icon={
            'OPERATOR': 'CONSOLE', 'MENU': 'LINENUMBERS_ON', 'POPUP': 'WINDOW',
            'TOOL': 'TOOL_SETTINGS', 'PYTHON': 'CONSOLE',
            'LEGACY_PYTHON': 'FILE_SCRIPT', 'SEPARATOR': 'REMOVE'
        }.get(self.action_type, 'SCRIPT'))
        layout.prop(self, "label")
        layout.prop(self, "icon")
        layout.prop(self, "tooltip")
        if self.action_type == 'OPERATOR':
            layout.prop(self, "operator_id")
            layout.prop(self, "properties_json")
            layout.label(text="Tip: use {} to run the Operator with its default values", icon='INFO')
        elif self.action_type == 'MENU':
            layout.prop(self, "menu_kind", expand=True)
            layout.prop(self, "menu_id", text="Menu")
        elif self.action_type == 'POPUP':
            layout.prop(self, "menu_kind", expand=True)
            if self.menu_kind == 'CUSTOM_UI':
                layout.prop(self, "ui_operator_id")
            else:
                layout.prop(self, "menu_id", text="Menu ID")
        elif self.action_type == 'TOOL':
            layout.prop(self, "tool_id")
            layout.prop(self, "space_type")
        elif self.action_type in {'PYTHON', 'LEGACY_PYTHON'}:
            layout.prop(self, "python_code", text="")
            if self.action_type == 'LEGACY_PYTHON':
                layout.label(text="Creates the original legacy script button format.", icon='INFO')
            else:
                layout.label(text="Advanced: Python runs with the kit command-line environment.", icon='INFO')

    def execute(self, context):
        buttons = editable_buttons(current(context), create=True)
        if buttons is None:
            self.report({'ERROR'}, "The selected Shelf cannot accept custom buttons")
            return {'CANCELLED'}
        kind = self.action_type
        label = "Separator" if kind == 'SEPARATOR' else (self.label.strip() or "New Button")
        record = {"label": label, "icon": "NONE" if kind == 'SEPARATOR' else _valid_icon(self.icon),
                  "tooltip": self.tooltip.strip()}
        if kind == 'SEPARATOR':
            record.update(type="separator", action={"type": "separator"})
        elif kind == 'OPERATOR':
            op_id = self.operator_id.strip()
            if "." not in op_id:
                self.report({'ERROR'}, "Enter an Operator ID such as mesh.bevel")
                return {'CANCELLED'}
            if not _registered_operator(op_id):
                self.report({'ERROR'}, "Choose a registered Blender Operator ID")
                return {'CANCELLED'}
            try:
                props = json.loads(self.properties_json or "{}")
            except ValueError as exc:
                self.report({'ERROR'}, f"Invalid properties JSON: {exc}")
                return {'CANCELLED'}
            if not isinstance(props, dict):
                self.report({'ERROR'}, "Operator properties must be a JSON object")
                return {'CANCELLED'}
            record.update(type="action", action={"type": "operator", "id": op_id, "properties": props})
        elif kind == 'MENU':
            target = self.menu_id.strip()
            if not target:
                self.report({'ERROR'}, "Enter a menu path or ID")
                return {'CANCELLED'}
            if self.menu_kind == 'MAYA':
                from . import menu_map
                if target not in menu_map.MAP:
                    self.report({'ERROR'}, "Choose a valid Maya Workflow Kit menu item")
                    return {'CANCELLED'}
                record["menu"] = target
                record["script"] = ""
            else:
                if self.menu_kind in {'BLENDER', 'PIE'} and bpy.types.Menu.bl_rna_get_subclass_py(target) is None:
                    self.report({'ERROR'}, "Choose a registered Blender Menu ID")
                    return {'CANCELLED'}
                if self.menu_kind == 'CUSTOM_UI' and not _registered_operator(target):
                    self.report({'ERROR'}, "Choose a registered Blender Operator ID")
                    return {'CANCELLED'}
                action_type = {'BLENDER': 'blender_menu', 'PIE': 'pie_menu',
                               'CUSTOM_UI': 'ui_operator'}[self.menu_kind]
                record.update(type="action", action={"type": action_type, "id": target})
        elif kind == 'POPUP':
            if self.menu_kind == 'CUSTOM_UI':
                target = self.ui_operator_id.strip()
                action_type = 'ui_operator'
            else:
                target = self.menu_id.strip()
                action_type = {'MAYA': 'maya_menu', 'BLENDER': 'blender_menu', 'PIE': 'pie_menu'}[self.menu_kind]
            if not target:
                self.report({'ERROR'}, "Enter a registered Menu or UI Operator ID")
                return {'CANCELLED'}
            if action_type == 'maya_menu':
                from . import menu_map
                if target not in menu_map.MAP:
                    self.report({'ERROR'}, "Choose a valid Maya Workflow Kit menu item")
                    return {'CANCELLED'}
                record["menu"] = target
                record["script"] = ""
            else:
                if action_type in {'blender_menu', 'pie_menu'} and bpy.types.Menu.bl_rna_get_subclass_py(target) is None:
                    self.report({'ERROR'}, "Choose a registered Blender Menu ID")
                    return {'CANCELLED'}
                if action_type == 'ui_operator' and not _registered_operator(target):
                    self.report({'ERROR'}, "Choose a registered Blender Operator ID")
                    return {'CANCELLED'}
                record.update(type="action", action={"type": action_type, "id": target, "popup": True})
        elif kind == 'TOOL':
            if not self.tool_id.strip():
                self.report({'ERROR'}, "Enter a Tool ID")
                return {'CANCELLED'}
            record.update(type="action", action={"type": "tool", "id": self.tool_id.strip(),
                                                   "space_type": self.space_type})
        elif kind in {'PYTHON', 'LEGACY_PYTHON'}:
            if not self.python_code.strip():
                self.report({'ERROR'}, "Python command is empty")
                return {'CANCELLED'}
            if kind == 'LEGACY_PYTHON':
                # Keep the original JSON shape for compatibility with existing Shelf scripts.
                record["script"] = self.python_code
            else:
                record.update(type="action", action={"type": "python", "code": self.python_code})
        else:
            self.report({'ERROR'}, "Unsupported Shelf action type")
            return {'CANCELLED'}
        buttons.append(record)
        save_user()
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_add_last_command(bpy.types.Operator):
    """Add the last command-line command as a button (Maya: drag a script to the shelf)"""
    bl_idname = "allset.shelf_add_last_command"
    bl_label = "Add Last Command"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        from ..command_line import runner
        return _current_user_shelf(context) is not None and bool(runner.history)

    def execute(self, context):
        from ..command_line import runner
        cmd = runner.history[-1]
        _current_user_shelf(context)["buttons"].append(
            {"label": cmd.split("(")[0][-24:] or "Command", "icon": 'CONSOLE', "script": cmd})
        save_user()
        _redraw(context)
        return {'FINISHED'}


# Material buttons run allset.shelf_material (operators/material.py).


def _redraw(context):
    # The shelf is drawn in the main Blender window while Shelf Editor can be
    # open in a separate window. Tag every window so a save in the editor
    # refreshes the actual shelf immediately, including on the first save.
    wm = getattr(context, "window_manager", None)
    windows = getattr(wm, "windows", ()) if wm else ()
    for window in windows:
        screen = getattr(window, "screen", None)
        for area in (screen.areas if screen else ()):
            area.tag_redraw()


def _deferred_redraw():
    """Force a real window redraw on a fresh frame.

    Merely tagging areas with ``tag_redraw`` after the first save of a session
    does not guarantee the main window processes the shelf draw on that frame
    (the editor runs in a separate floating window). Re-tagging alone was
    verified insufficient on a real machine. ``wm.redraw_timer`` with
    DRAW_WIN_SWAP synchronously redraws every window and swaps the buffers, so
    the rebuilt GPU textures reach the actual shelf on the first change too.
    """
    try:
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    except (AttributeError, RuntimeError, SystemError):
        # Fall back to tagging every area if the redraw operator is unavailable
        # (e.g. a headless context).
        wm = bpy.context.window_manager
        for window in getattr(wm, "windows", ()):
            for area in window.screen.areas:
                area.tag_redraw()
    return None


def schedule_redraw():
    """Force a guaranteed second redraw frame after a save (idempotent)."""
    if not bpy.app.timers.is_registered(_deferred_redraw):
        bpy.app.timers.register(_deferred_redraw, first_interval=0.0)
