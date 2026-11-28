# SPDX-License-Identifier: GPL-3.0-or-later
"""The Shelf Editor's private draft of shelves.json (``_draft``, ``_draft_base``: read them from this module, they
are rebound): lookups of shelves and buttons in it, loading a button into the editor fields (``_load_button``), the
rows of the three lists (``_sync_*_list``), the shelf operators (select, New, Rename, Duplicate, Delete, Move
Shelf) and Save Changes / Discard Changes. Related: shelf_editor_document.py, shelf_editor.py."""

import json

import bpy
from bpy.props import EnumProperty, StringProperty

from . import marked_window, shelf
from .shelf_editor_commands import _operator_props_to_body, _parse_operator_props_body
from .shelf_editor_document import _copy_document, _merge_documents, _write_document_atomic


KIND = "SHELF_EDITOR"

_draft = None
_draft_base = None
_loading = False
_form_kind = "PYTHON"      # the Command Type the form showed last (#441)

DEFAULT_SCRIPT = "import bpy\n\nbpy.ops.mesh.primitive_cube_add()"


def _op_call(idname, props):
    mod, name = idname.split(".", 1)
    args = ", ".join(f"{key}={value!r}" for key, value in props.items())
    return f"bpy.ops.{mod}.{name}({args})"


def python_for(wm, kind):
    """Python that runs what the form's ``kind`` command runs, or None (#441: switching Command Type to Python
    starts from the button's own command, not from an unrelated default)."""
    head = "import bpy\n\n"
    if kind == "MAYA_MENU_ITEM" and wm.allset_se_menu.strip():
        from . import menu_map
        path = wm.allset_se_menu.strip()
        spec = menu_map.spec(path)
        plain = (spec is not None and spec[0] == "op" and spec[1] != "allset.menu_item" and "." in spec[1]
                 and path not in menu_map.EDIT_MODE and path not in menu_map.OBJECT_MODE)
        # a plain operator item: its operator (settings can be added to the call); other items run as the menu does
        return head + (_op_call(spec[1], spec[2]) if plain else f"bpy.ops.allset.menu_item(item={path!r})")
    if kind == "OPERATOR" and "." in wm.allset_se_operator.strip():
        try:
            props = _parse_operator_props_body(wm.allset_se_props)
        except ValueError:
            props = {}
        return head + _op_call(wm.allset_se_operator.strip(), props)
    if kind == "TOOL" and wm.allset_se_action_id.strip():
        return head + f"bpy.ops.wm.tool_set_by_id(name={wm.allset_se_action_id.strip()!r})"
    if kind == "MENU" and wm.allset_se_action_id.strip():
        return head + f"bpy.ops.wm.call_menu(name={wm.allset_se_action_id.strip()!r})"
    return None


def on_type_changed(wm, _context):
    """Command Type switched to Python: fill the Python field with the command the form had."""
    global _form_kind
    previous, _form_kind = _form_kind, wm.allset_se_type
    if _loading or wm.allset_se_type != "PYTHON" or previous == "PYTHON":
        return
    code = python_for(wm, previous)
    if code:
        wm.allset_se_script = code


def _draft_shelves():
    out = [(name, label) for name, label, _buttons in shelf.shelf_data.SHELVES]
    if _draft is not None:
        out.extend((shelf.USER_PREFIX + item["name"], item["name"])
                   for item in _draft.get("shelves", []))
    return out


def _draft_user_shelf(shelf_id):
    if not shelf_id.startswith(shelf.USER_PREFIX) or _draft is None:
        return None
    name = shelf_id[len(shelf.USER_PREFIX):]
    return next((item for item in _draft.get("shelves", []) if item["name"] == name), None)


def _draft_extra(shelf_id, create=False):
    if _draft is None:
        return None
    extra = _draft.get("extra")
    if not isinstance(extra, dict):
        if not create:
            return None
        extra = _draft["extra"] = {}
    if create:
        return extra.setdefault(shelf_id, [])
    return extra.get(shelf_id)


def _draft_buttons(shelf_id, create=False):
    user = _draft_user_shelf(shelf_id)
    if user is not None:
        return user.setdefault("buttons", [])
    if shelf_id.startswith(shelf.USER_PREFIX):
        return None
    if not any(name == shelf_id for name, _label, _buttons in shelf.shelf_data.SHELVES):
        return None
    return _draft_extra(shelf_id, create)


def _factory_rows(shelf_id):
    return shelf.all_buttons(shelf_id) if not shelf_id.startswith(shelf.USER_PREFIX) else []


def _unique_name(base, exclude=None):
    base = (base or "Shelf").strip() or "Shelf"
    names = {item["name"] for item in (_draft or {}).get("shelves", [])
             if item is not exclude}
    if base not in names:
        return base
    index = 2
    while f"{base}{index}" in names:
        index += 1
    return f"{base}{index}"


def _wm(context):
    return context.window_manager


def _set_message(context, message):
    _wm(context).allset_se_message = message


def _load_button(context, index):
    """Load one draft button into the transient editor fields.

    Reset every field first so values from a previously selected button can
    never leak into the next button's editor state.
    """
    global _loading, _form_kind
    wm = _wm(context)
    shelf_id = wm.allset_se_shelf
    buttons = _draft_buttons(shelf_id) or []
    _loading = True
    try:
        # Reset the complete transient form, not only fields used by the
        # incoming button type. All of these properties are SKIP_SAVE data.
        wm.allset_se_index = -1
        wm.allset_se_label = ""
        wm.allset_se_icon = "SCRIPT"
        wm.allset_se_type = "PYTHON"
        wm.allset_se_script = DEFAULT_SCRIPT
        wm.allset_se_menu = ""
        wm.allset_se_operator = "mesh.primitive_cube_add"
        wm.allset_se_props = ""
        wm.allset_se_tooltip = ""
        wm.allset_se_action_id = "VIEW3D_MT_view"
        wm.allset_se_action_code = ""
        wm.allset_se_space_type = "AUTO"
        wm.allset_se_required_mode = "AUTO"
        wm.allset_se_object_type = "AUTO"
        wm.allset_se_tool_space_type = "AUTO"
        wm.allset_se_tool_mode = "AUTO"

        if not 0 <= index < len(buttons):
            return

        button = buttons[index]
        action = button.get("action") or {}
        wm.allset_se_index = index
        wm.allset_se_label = button.get("label", "Button")
        wm.allset_se_icon = button.get("icon", "SCRIPT")
        wm.allset_se_tooltip = button.get("tooltip", "")
        wm.allset_se_space_type = action.get(
            "space_type", button.get("space_type", "AUTO")
        )
        wm.allset_se_required_mode = action.get(
            "required_mode", action.get("mode", button.get("required_mode", "AUTO"))
        )
        wm.allset_se_object_type = action.get(
            "object_type", button.get("object_type", "AUTO")
        )
        if button.get("type") == "separator" or action.get("type") == "separator":
            wm.allset_se_type = "SEPARATOR"
        elif button.get("menu"):
            wm.allset_se_type = "MAYA_MENU_ITEM"
            wm.allset_se_menu = button["menu"]
        elif button.get("operator"):
            wm.allset_se_type = "OPERATOR"
            wm.allset_se_operator = button["operator"]
            wm.allset_se_props = _operator_props_to_body(button.get("props", {}))
        elif button.get("type") == "action":
            kind = action.get("type", "operator")
            wm.allset_se_action_id = action.get("id", "")
            wm.allset_se_action_code = action.get("code", "")
            wm.allset_se_props = _operator_props_to_body(action.get("properties", {}))
            if kind == "operator":
                wm.allset_se_type = "OPERATOR"
                wm.allset_se_operator = action.get("id", "")
            elif kind == "maya_menu":
                wm.allset_se_type = "MAYA_MENU_ITEM"
                wm.allset_se_menu = action.get("id", "")
            elif kind == "python":
                wm.allset_se_type = "PYTHON"
                wm.allset_se_script = action.get("code", "")
            elif kind == "tool":
                wm.allset_se_type = "TOOL"
                wm.allset_se_tool_space_type = action.get("space_type", "AUTO")
                wm.allset_se_tool_mode = action.get(
                    "required_mode", action.get("mode", "AUTO")
                )
            elif kind in {"blender_menu", "pie_menu"}:
                wm.allset_se_type = "MENU"
            elif kind == "ui_operator":
                # Legacy UI Operator records remain editable as ordinary Operators.
                wm.allset_se_type = "OPERATOR"
                wm.allset_se_operator = action.get("id", "")
            else:
                wm.allset_se_type = "PYTHON"
                wm.allset_se_script = action.get("code", "")
        else:
            # Legacy script buttons remain readable; Apply writes action.python.
            wm.allset_se_type = "PYTHON"
            wm.allset_se_script = button.get("script", "")
    finally:
        _loading = False
        _form_kind = wm.allset_se_type


def _start_draft(context):
    global _draft, _draft_base
    if _draft is None:
        shelf.reload_user()
        _draft = _copy_document()
        _draft_base = _copy_document()
    elif marked_window.find_window(context, KIND) is None:
        # Closing the native floating window must not silently discard the in-memory draft.
        # Reconcile any Shelf changes made through the gear menu while the editor was closed.
        shelf.reload_user()
        latest = _copy_document()
        if _draft != (_draft_base or latest):
            _draft = _merge_documents(_draft_base or latest, _draft, latest)
        else:
            # Independent copy: never alias _draft to the document that becomes _draft_base,
            # otherwise a later Apply would mutate the base and the first Save's three-way
            # merge would revert the just-applied change.
            _draft = json.loads(json.dumps(latest))
        _draft_base = json.loads(json.dumps(latest))
    wm = _wm(context)
    current = shelf.current(context)
    valid = {identifier for identifier, _label in _draft_shelves()}
    wm.allset_se_shelf = current if current in valid else _draft_shelves()[0][0]
    wm.allset_se_message = ""
    _load_button(context, -1)


def _redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


class ALLSET_OT_shelf_editor_select_shelf(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_select_shelf"
    bl_label = "Select Shelf"
    bl_options = {'INTERNAL'}

    shelf_id: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        wm = _wm(context)
        if self.shelf_id not in {identifier for identifier, _label in _draft_shelves()}:
            return {'CANCELLED'}
        wm.allset_se_shelf = self.shelf_id
        wm.allset_se_shelves_index = next(
            (index for index, (shelf_id, _label) in enumerate(_draft_shelves())
             if shelf_id == self.shelf_id),
            wm.allset_se_shelves_index,
        )
        _load_button(context, -1)
        _set_message(context, "")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_add_shelf(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_add_shelf"
    bl_label = "New Shelf"

    name: StringProperty(name="Shelf Name", default="Custom")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300)

    def execute(self, context):
        global _draft
        if _draft is None:
            return {'CANCELLED'}
        name = _unique_name(self.name)
        _draft.setdefault("shelves", []).append({"name": name, "buttons": []})
        _wm(context).allset_se_shelf = shelf.USER_PREFIX + name
        _load_button(context, -1)
        _set_message(context, f"Created shelf: {name} (not saved yet)")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_rename_shelf(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_rename_shelf"
    bl_label = "Rename Shelf"

    name: StringProperty(name="New Name")

    @classmethod
    def poll(cls, context):
        return _draft_user_shelf(_wm(context).allset_se_shelf) is not None

    def invoke(self, context, event):
        self.name = _wm(context).allset_se_shelf[len(shelf.USER_PREFIX):]
        return context.window_manager.invoke_props_dialog(self, width=300)

    def execute(self, context):
        wm = _wm(context)
        item = _draft_user_shelf(wm.allset_se_shelf)
        if item is None:
            return {'CANCELLED'}
        old_id = wm.allset_se_shelf
        name = _unique_name(self.name, exclude=item)
        item["name"] = name
        wm.allset_se_shelf = shelf.USER_PREFIX + name
        _set_message(context, f"Renamed {old_id} to {name} (not saved yet)")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_duplicate_shelf(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_duplicate_shelf"
    bl_label = "Duplicate Shelf"

    def execute(self, context):
        item = _draft_user_shelf(_wm(context).allset_se_shelf)
        if item is None:
            self.report({'WARNING'}, "Only user shelves can be duplicated")
            return {'CANCELLED'}
        duplicate = json.loads(json.dumps(item))
        duplicate["name"] = _unique_name(item["name"] + " Copy")
        _draft["shelves"].append(duplicate)
        _wm(context).allset_se_shelf = shelf.USER_PREFIX + duplicate["name"]
        _load_button(context, -1)
        _set_message(context, f"Duplicated shelf: {duplicate['name']} (not saved yet)")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_delete_shelf(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_delete_shelf"
    bl_label = "Delete Shelf"

    @classmethod
    def poll(cls, context):
        return (_draft_user_shelf(_wm(context).allset_se_shelf) is not None
                and len((_draft or {}).get("shelves", [])) > 1)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        wm = _wm(context)
        item = _draft_user_shelf(wm.allset_se_shelf)
        if item is None:
            return {'CANCELLED'}
        _draft["shelves"].remove(item)
        wm.allset_se_shelf = _draft_shelves()[0][0]
        _load_button(context, -1)
        _set_message(context, "Shelf deleted from the draft (not saved yet)")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_move_shelf(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_move_shelf"
    bl_label = "Move Shelf"

    direction: EnumProperty(items=(("UP", "Up", ""), ("DOWN", "Down", "")))

    def execute(self, context):
        wm = _wm(context)
        item = _draft_user_shelf(wm.allset_se_shelf)
        if item is None:
            return {'CANCELLED'}
        items = _draft["shelves"]
        index = items.index(item)
        target = index + (-1 if self.direction == "UP" else 1)
        if not 0 <= target < len(items):
            return {'CANCELLED'}
        items[index], items[target] = items[target], items[index]
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_save(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_save"
    bl_label = "Save Changes"

    def execute(self, context):
        global _draft, _draft_base
        if _draft is None:
            return {'CANCELLED'}

        wm = _wm(context)
        active = wm.allset_se_shelf

        # Save must commit the currently visible form into the in-memory draft
        # first. The editor fields are transient WindowManager properties and
        # are intentionally not written by _write_document_atomic(). Reuse the
        # same validation and record-building path as the explicit Apply button
        # so icons, labels, tooltips, command data and Operator properties all
        # follow identical rules.
        if 0 <= wm.allset_se_index < len(_draft_buttons(active) or []):
            apply_result = bpy.ops.allset.shelf_editor_apply_button()
            if 'CANCELLED' in apply_result:
                _set_message(context, "Save cancelled: current button changes were not applied")
                _redraw(context)
                return {'CANCELLED'}

        # Freeze the editor state before touching the live shelf cache.  The
        # draft is deliberately independent from shelf_store._user, but keeping an
        # immutable snapshot here also prevents a refresh from replacing the
        # only copy of newly added factory-shelf extras.
        draft_snapshot = json.loads(json.dumps(_draft))
        base_snapshot = json.loads(json.dumps(_draft_base or {}))

        try:
            # Read the latest on-disk document.  When nobody changed the file
            # outside this editor, persist the draft verbatim; only invoke the
            # three-way merge when a genuine external change is detected.
            shelf.reload_user()
            latest = _copy_document()
            if latest == base_snapshot:
                merged = draft_snapshot
            else:
                merged = _merge_documents(base_snapshot, draft_snapshot, latest)

            saved = _write_document_atomic(merged)

            # Verify the editor's changed factory extras survived the merge
            # and disk round-trip before replacing the in-memory draft.
            draft_extra = draft_snapshot.get("extra", {}) or {}
            base_extra = base_snapshot.get("extra", {}) or {}
            saved_extra = saved.get("extra", {}) or {}
            for shelf_id, buttons in draft_extra.items():
                if buttons != base_extra.get(shelf_id, []):
                    if saved_extra.get(shelf_id, []) != merged.get("extra", {}).get(shelf_id, []):
                        raise ValueError(
                            f"Factory shelf '{shelf_id}' extras failed save verification"
                        )

            # Update the existing cache object in place because other shelf
            # UI callbacks may already hold references to it.
            shelf._user.clear()
            shelf._user.update(saved)

        except Exception as ex:
            # Keep the editor draft and its visible list intact on failure.
            self.report({'ERROR'}, f"Could not save Shelf data: {ex}")
            _set_message(context, f"Save failed; draft kept: {ex}")
            _redraw(context)
            return {'CANCELLED'}

        # Only after the verified write succeeds may the draft be replaced.
        _draft = json.loads(json.dumps(saved))
        _draft_base = json.loads(json.dumps(saved))

        valid = {identifier for identifier, _label in shelf.shelves()}
        if active in valid:
            shelf.set_current(context, active)

        # Rebuild the transient UIList from the committed document now, rather
        # than relying on a later draw to notice a stale signature.
        _sync_shelves_list(wm)
        _sync_contents_list(wm, active)
        if 0 <= wm.allset_se_index < len(_draft_buttons(active) or []):
            _load_button(context, wm.allset_se_index)
        else:
            _load_button(context, -1)

        saved_count = len(_draft_buttons(active) or [])
        _set_message(context, f"Shelf changes saved ({saved_count} custom button(s) on this shelf)")
        shelf.shelf_icons.invalidate_gpu_textures()
        _redraw(context)
        # The first save of a session needs a second redraw frame once the
        # operator has returned (GPU texture release/create lifecycle); harmless
        # on every later save.
        shelf.schedule_redraw()
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_cancel(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_cancel"
    bl_label = "Discard Changes"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        global _draft, _draft_base
        shelf.reload_user()
        _draft = _copy_document()
        _draft_base = _copy_document()
        wm = _wm(context)
        valid = {identifier for identifier, _label in _draft_shelves()}
        wm.allset_se_shelf = shelf.current(context) if shelf.current(context) in valid else _draft_shelves()[0][0]
        _load_button(context, -1)
        _set_message(context, "Unsaved changes discarded")
        _redraw(context)
        return {'FINISHED'}


def _sync_contents_list(wm, shelf_id):
    """Refresh transient UIList data only when the visible rows actually change."""
    rows = []
    if shelf_id.startswith(shelf.USER_PREFIX):
        for index, button in enumerate(_draft_buttons(shelf_id) or []):
            rows.append((button.get("label", "Button"),
                         shelf._valid_icon(button.get("icon", "SCRIPT")),
                         index, False))
    else:
        for index, label, _action, icon in _factory_rows(shelf_id):
            if shelf.shelf_icons.icon_for(label, shelf_id, index) is not None:
                icon = f"MWK:{shelf_id}/{label}#{index}"
            rows.append((label, icon, -1, True))
        for index, button in enumerate(_draft_buttons(shelf_id) or []):
            rows.append((button.get("label", "Button"),
                         shelf._valid_icon(button.get("icon", "SCRIPT")),
                         index, False))

    signature = repr((shelf_id, rows))
    current_rows = [(item.label, item.icon, item.button_index, item.is_factory)
                    for item in wm.allset_se_items]
    if wm.allset_se_items_signature == signature and current_rows == rows:
        return
    collection = wm.allset_se_items
    collection.clear()
    for label, icon, button_index, is_factory in rows:
        item = collection.add()
        item.label = label
        item.icon = icon
        item.button_index = button_index
        item.is_factory = is_factory
    wm.allset_se_items_signature = signature
    wm.allset_se_list_index = min(wm.allset_se_list_index, max(0, len(rows) - 1))


def _sync_shelves_list(wm):
    """Refresh shelf rows while preserving the independent scroll position."""
    rows = _draft_shelves()
    signature = repr(rows)
    if wm.allset_se_shelves_signature == signature:
        return
    collection = wm.allset_se_shelves
    collection.clear()
    for shelf_id, label in rows:
        item = collection.add()
        item.shelf_id = shelf_id
        item.label = label
        item.icon = 'RADIOBUT_OFF'
    wm.allset_se_shelves_signature = signature
    selected_index = next((index for index, (shelf_id, _label) in enumerate(rows)
                           if shelf_id == wm.allset_se_shelf), 0)
    wm.allset_se_shelves_index = min(selected_index, max(0, len(rows) - 1))


def _sync_properties_list(wm):
    """Build the fixed editor fields; Operator Properties remain plain JSON."""
    rows = [
        ("FIELD", "allset_se_label", "Label"),
        ("FIELD", "allset_se_icon", "Icon"),
        ("FIELD", "allset_se_type", "Command Type"),
    ]
    kind = wm.allset_se_type
    if kind == "PYTHON":
        rows.append(("FIELD", "allset_se_script", "Python"))
    elif kind == "MAYA_MENU_ITEM":
        rows.extend((
            ("FIELD", "allset_se_menu", "Maya Menu Item"),
            ("FIELD", "allset_se_space_type", "Editor Space"),
        ))
    elif kind == "MENU":
        rows.extend((
            ("FIELD", "allset_se_action_id", "Menu ID"),
            ("INFO", "", "Blender native Menu or MayaWorkflow Menu · XXX_MT_xxx"),
            ("FIELD", "allset_se_space_type", "Editor Space"),
            ("FIELD", "allset_se_required_mode", "Required Mode"),
            ("FIELD", "allset_se_object_type", "Object Type"),
        ))
    elif kind == "OPERATOR":
        rows.extend((
            ("FIELD", "allset_se_operator", "Operator ID"),
            ("FIELD", "allset_se_props", "Operator Properties (JSON)"),
            ("INFO", "", "Leave empty to use the Operator default properties."),
            ("FIELD", "allset_se_space_type", "Editor Space"),
            ("FIELD", "allset_se_required_mode", "Required Mode"),
            ("FIELD", "allset_se_object_type", "Object Type"),
        ))
    elif kind == "TOOL":
        rows.extend((
            ("FIELD", "allset_se_action_id", "Tool ID"),
            ("INFO", "", "Built-in tools and registered custom Workspace Tools are searchable; other IDs can be entered manually."),
            ("FIELD", "allset_se_tool_space_type", "Tool Editor"),
            ("FIELD", "allset_se_tool_mode", "Required Mode"),
            ("FIELD", "allset_se_object_type", "Object Type"),
        ))

    rows.append(("FIELD", "allset_se_tooltip", "Tooltip"))
    signature = repr((wm.allset_se_index, kind, wm.allset_se_operator,
                      wm.allset_se_action_id, rows))
    if wm.allset_se_properties_signature == signature:
        return

    collection = wm.allset_se_properties
    collection.clear()
    for row_kind, field, label in rows:
        item = collection.add()
        item.row_kind = row_kind
        item.field = field
        item.label = label

    wm.allset_se_properties_signature = signature
    wm.allset_se_properties_index = 0
