# SPDX-License-Identifier: GPL-3.0-or-later
"""Running a shelf button (``allset.shelf_button``): a factory button runs its Blender action, a menu button its
Maya menu item, a typed action (operator, menu, tool, UI operator, Python) runs in a matching editor after its
mode / object-type check, a script button its Python. Double-click or Ctrl+click = the option box (``option_box``,
``take_back_run``). Also the button tooltips (``button_tooltip``, ``record_tooltip``). Related: shelf_store.py."""

import time

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from .. import i18n, results
from . import shelf_map

from .shelf_store import USER_PREFIX, button_record, all_buttons


class ShelfContextError(RuntimeError):
    """An expected Shelf context mismatch; shown as a warning, not a traceback."""


def _run_in_editor_space(context, space_type, callback):
    """Run a Shelf command in a matching editor area without changing the user's layout."""
    if not space_type or space_type in {"ANY", "AUTO"}:
        return callback(context)

    window = context.window
    screen = context.screen
    if window is None or screen is None:
        if context.area is not None and context.area.type == space_type:
            return callback(context)
        raise ShelfContextError(f"No window is available for Editor Space {space_type}. Open the requested editor and try again.")

    area = context.area if context.area is not None and context.area.type == space_type else None
    if area is None:
        if space_type == 'VIEW_3D':
            from .status_line import main_view3d
            area, _region = main_view3d(screen)
        else:
            area = next((item for item in screen.areas if item.type == space_type), None)
    if area is None:
        raise ShelfContextError(
            f"No {space_type} editor is open in this window. Open the requested editor and try again."
        )
    region = next((item for item in area.regions if item.type == 'WINDOW'), None)
    try:
        with context.temp_override(
            window=window,
            screen=screen,
            area=area,
            **({"region": region} if region is not None else {}),
        ):
            return callback(bpy.context)
    except (AttributeError, TypeError, RuntimeError):
        raise




# --- Shelf execution context validation -----------------------------------------------------------

def _infer_shelf_requirements(kind, target="", menu_path=""):
    """Infer conservative defaults from an action identifier.

    AUTO deliberately resolves to ANY when the action cannot be identified safely.
    It never changes the user's editor, mode, or active object.
    """
    kind = (kind or "").lower()
    target = (target or "").strip()
    menu_path = (menu_path or "").lower()
    module = target.split(".", 1)[0].lower() if "." in target else ""
    name = target.split(".", 1)[-1].lower()

    if kind == "maya_menu":
        if "graph editor" in menu_path:
            return "GRAPH_EDITOR", "ANY", "ANY"
        if "uv editor" in menu_path or "uv toolkit" in menu_path:
            return "IMAGE_EDITOR", "ANY", "ANY"
        if any(token in menu_path for token in ("hypershade", "node editor")):
            return "NODE_EDITOR", "ANY", "ANY"
        if any(token in menu_path for token in ("dope sheet", "timeline")):
            return "DOPESHEET_EDITOR", "ANY", "ANY"
        if any(token in menu_path for token in ("edit mesh", "mesh tools", "vertex", "edge", "face")):
            # any mode: the menu item enters component mode itself (Maya: Insert Edge Loop on a selected object)
            return "VIEW_3D", "ANY", "MESH"
        # Create menu items (primitives, lights, cameras, ...) run from any mode, like the main menu: in component
        # mode they leave it for object mode and make the object (#583)
        return "VIEW_3D", "ANY", "ANY"

    if kind in {"operator", "ui_operator"}:
        if module == "mesh":
            if name.startswith("primitive_") and name.endswith("_add"):
                return "VIEW_3D", "OBJECT", "ANY"
            return "VIEW_3D", "EDIT_MESH", "MESH"
        if module == "curve":
            if name.startswith("primitive_") and name.endswith("_add"):
                return "VIEW_3D", "OBJECT", "ANY"
            return "VIEW_3D", "EDIT_CURVE", "CURVE"
        if module == "armature":
            if name.endswith("_add"):
                return "VIEW_3D", "OBJECT", "ANY"
            return "VIEW_3D", "EDIT_ARMATURE", "ARMATURE"
        if module == "pose":
            return "VIEW_3D", "POSE", "ARMATURE"
        if module == "sculpt":
            return "VIEW_3D", "SCULPT", "MESH"
        if module == "paint":
            if "vertex" in name:
                return "VIEW_3D", "PAINT_VERTEX", "MESH"
            if "weight" in name:
                return "VIEW_3D", "PAINT_WEIGHT", "MESH"
            if "image" in name or "texture" in name:
                return "VIEW_3D", "PAINT_TEXTURE", "MESH"
            return "VIEW_3D", "ANY", "ANY"
        if module in {"object", "transform"}:
            return "VIEW_3D", "ANY", "ANY"
        if module in {"image"}:
            return "IMAGE_EDITOR", "ANY", "ANY"
        if module in {"node"}:
            return "NODE_EDITOR", "ANY", "ANY"
        if module in {"graph"}:
            return "GRAPH_EDITOR", "ANY", "ANY"
        if module in {"sequencer"}:
            return "SEQUENCE_EDITOR", "ANY", "ANY"
        return "ANY", "ANY", "ANY"

    if kind == "tool":
        if "sculpt" in name or name.endswith(".draw"):
            return "VIEW_3D", "SCULPT", "MESH"
        if "uv" in name or "image" in name:
            return "IMAGE_EDITOR", "ANY", "ANY"
        return "VIEW_3D", "ANY", "ANY"

    if kind == "blender_menu":
        lowered = target.lower()
        if "edit_mesh" in lowered or "editmesh" in lowered:
            return "VIEW_3D", "EDIT_MESH", "MESH"
        if "object" in lowered and target.startswith("VIEW3D_"):
            return "VIEW_3D", "OBJECT", "ANY"
        if target.startswith(("VIEW3D_", "VIEW3D_MT_")):
            return "VIEW_3D", "ANY", "ANY"
        if target.startswith(("IMAGE_", "IMAGE_MT_")):
            return "IMAGE_EDITOR", "ANY", "ANY"
        if target.startswith(("NODE_", "NODE_MT_")):
            return "NODE_EDITOR", "ANY", "ANY"
        if target.startswith(("GRAPH_", "GRAPH_MT_")):
            return "GRAPH_EDITOR", "ANY", "ANY"
        return "ANY", "ANY", "ANY"

    return "ANY", "ANY", "ANY"


def _resolve_shelf_requirements(kind, target="", menu_path="", editor_space="AUTO",
                                required_mode="AUTO", object_type="AUTO"):
    inferred = _infer_shelf_requirements(kind, target, menu_path)
    if required_mode == "UV":
        required_mode = "ANY"
        if editor_space in (None, "", "AUTO"):
            editor_space = "IMAGE_EDITOR"
    values = (editor_space, required_mode, object_type)
    return tuple(
        inferred[i] if value in (None, "", "AUTO") else value
        for i, value in enumerate(values)
    )


def _validate_shelf_context(context, required_mode="ANY", object_type="ANY"):
    """Return (ok, warning); this function never changes Blender context."""
    if object_type not in (None, "", "ANY", "AUTO"):
        obj = context.active_object
        if obj is None or obj.type != object_type:
            return False, f"This action requires an active {object_type} object."

    if required_mode not in (None, "", "ANY", "AUTO"):
        current_mode = getattr(context, "mode", "OBJECT")
        if current_mode != required_mode:
            return False, f"This action requires {required_mode}. Switch mode and try again."

    return True, ""


def _run_operator_checked(context, target, properties, option=False):
    """Run an Operator only after its own Blender poll accepts this context."""
    try:
        module, name = target.split(".", 1)
        operator = getattr(getattr(bpy.ops, module), name)
        if not operator.poll():
            raise ShelfContextError(
                f"Operator {target} is not available in the current editor, mode, or selection."
            )
    except ShelfContextError:
        raise
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as ex:
        raise ShelfContextError(f"Cannot validate Operator {target}: {ex}") from ex

    from ..marking.modal import run_action
    return run_action(
        context, (target, properties or {}), option=option
    )


def _run_menu_checked(context, target, option=False):
    """Validate a registered Menu and let Blender handle Menu display/polling."""
    menu_type = bpy.types.Menu.bl_rna_get_subclass_py(target)
    if menu_type is None:
        raise ShelfContextError(f"Menu {target} is not registered.")

    # Blender Menu types do not all define a poll() method. In particular,
    # built-in menus such as VIEW3D_MT_view rely on Blender's own call_menu
    # handling and must not be rejected for lacking that optional method.
    menu_poll = getattr(menu_type, "poll", None)
    if callable(menu_poll):
        try:
            available = menu_poll(context)
        except TypeError:
            # Keep compatibility with custom Menu classes using poll(self).
            available = menu_poll()
        if not available:
            raise ShelfContextError(
                f"Menu {target} is not available in the current editor or mode."
            )

    from ..marking.modal import run_action
    return run_action(context, ("menu", target), option=option)


OPTIONS_TIP = i18n.mark("Double-click or Ctrl+click: options")


def record_tooltip(b):
    """Tooltip of a user-made button, including legacy and typed action records."""
    path = b.get("menu")
    if b.get("type") == "action":
        action = b.get("action") or {}
        return b.get("tooltip") or f"{b.get('label', 'Shelf Button')}\n{action.get('type', 'custom action')}: {action.get('id', '')}"
    if b.get("type") == "separator":
        return "Shelf Separator"
    if not path:
        return b.get("tooltip") or f"{b.get('label', 'Shelf Button')}\n{b.get('script', '')[:200]}"
    from . import menu_map
    where = i18n.compose("Maya menu: {path}", path=i18n.path(path.split("#")[0], i18n.tip).replace("/", " > "))
    label = i18n.tip(b['label'])
    if path not in menu_map.MAP:
        return i18n.compose("{label} (greyed: no Blender equivalent in Maya Workflow Kit)", label=label) + "\n" + where
    return f"{label}\n{where}\n" + i18n.tip(OPTIONS_TIP)


def button_notice(shelf, label):
    """(Blender substitute, line) of a factory button: its own, else its Maya menu item's."""
    from . import notices
    own = shelf_map.NOTICES.get(f"{shelf}/{label}")
    if own is not None:
        return own
    path = shelf_map.menu_path(shelf, label)
    return notices.greyed_notice(path) if path else None


def button_tooltip(shelf, label, mapped):
    """Tooltip of a factory button; a greyed one (or one whose Blender result differs) shows its notice and puts
    the line in the Help Line, like greyed menu items."""
    from . import notices
    path = shelf_map.menu_path(shelf, label)
    n = button_notice(shelf, label) if not mapped else (notices.NOTICES.get(path) if path else None)
    name = i18n.tip(label)
    if n is None:
        text = i18n.compose("{label} (Maya shelf)", label=name)
        return f"{text}\n" + i18n.tip(OPTIONS_TIP) if mapped else text
    substitute, line = i18n.tip(n[0]), i18n.tip(n[1])
    notices.show(f"{name}: {line}")
    if mapped:
        head = i18n.compose("{label} (Maya shelf)  →  Blender: {substitute}", label=name, substitute=substitute)
        return f"{head}\n{line}\n" + i18n.tip(OPTIONS_TIP)
    head = i18n.compose("{label} (Maya shelf, greyed)  →  {substitute}", label=name, substitute=substitute)
    return f"{head}\n{line}"


def run_script(context, label, script):
    """Run a user shelf button's Python script with Blender's Run Script (``runner.run``: a temporary Text named after
    the button, the Command Line's names, its variables not kept); returns (ok, message)."""
    from ..command_line import runner
    res = runner.run(script, name=f".allset_shelf {label}", persist=False, remember=False)
    if res.error:                       # a user script: report, don't break the UI
        return False, f"{label}: {res.text.removeprefix('# Error: ')}"
    return True, ""


# --- operators -------------------------------------------------------------------------------------

DOUBLE_CLICK_S = 0.35     # Blender's default double-click time (Preferences > Input)
_last_click = {}


class ALLSET_OT_shelf_button(bpy.types.Operator):
    """Run this shelf button (double-click or Ctrl+click: its options)"""
    bl_idname = "allset.shelf_button"
    bl_label = "Shelf Button"
    bl_options = {'INTERNAL'}

    shelf: StringProperty()
    index: IntProperty()
    option: BoolProperty(options={'SKIP_SAVE'})
    double: BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})     # the option box of a double-click (first click ran)

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        for i, label, action, _icon in all_buttons(props.shelf):
            if i == props.index:
                return button_tooltip(props.shelf, label, action is not None)
        b = button_record(props.shelf, props.index)
        if b is not None:
            return record_tooltip(b)
        return "Shelf button"

    def invoke(self, context, event):
        key = (self.shelf, self.index)
        now = time.monotonic()
        last = _last_click.get("key"), _last_click.get("time", -1.0)
        _last_click.update(key=key, time=now)
        limit = getattr(context.preferences.inputs, "mouse_double_click_time", DOUBLE_CLICK_S * 1000) / 1000.0
        second = last[0] == key and now - last[1] <= limit
        if event.value == 'DOUBLE_CLICK' or second:
            # Maya doubleClickCommand = the item's option box; the first click
            # already ran the command once (was screen.redo_last, which shows nothing since shelf runs
            # are not registered). The gizmo may see two presses instead of a double click.
            _last_click.clear()
            self.option = True
            self.double = True
            return self.execute(context)
        if event.ctrl:
            self.option = True          # Ctrl+click: the option box without running first
        return self.execute(context)

    def execute(self, context):
        b = button_record(self.shelf, self.index)
        if b is not None and b.get("menu"):
            editor_space, required_mode, object_type = _resolve_shelf_requirements(
                "maya_menu", b.get("menu", ""),
                menu_path=b.get("menu", ""),
                editor_space=b.get("space_type", "AUTO"),
                required_mode=b.get("required_mode", "AUTO"),
                object_type=b.get("object_type", "AUTO"),
            )
            ok, warning = _validate_shelf_context(context, required_mode, object_type)
            if not ok:
                self.report({'WARNING'}, warning)
                return {'CANCELLED'}
            try:
                return _run_in_editor_space(
                    context, editor_space,
                    lambda ctx: self._run_menu(ctx, b),
                )
            except ShelfContextError as ex:
                self.report({'WARNING'}, str(ex))
                return {'CANCELLED'}
        if b is not None and b.get("type") == "action":
            return self._run_user_action(context, b)
        if b is not None and b.get("type") == "separator":
            return {'CANCELLED'}
        if b is not None:
            if self.option:
                return {'CANCELLED'}     # a script button has no double-click command (Maya: nothing more runs)
            ok, msg = run_script(context, b["label"], b["script"])
            if not ok:
                self.report({'ERROR'}, msg)
                return {'CANCELLED'}
            return {'FINISHED'}
        if self.shelf.startswith(USER_PREFIX):
            return {'CANCELLED'}
        for i, label, action, _icon in all_buttons(self.shelf):
            if i == self.index and action is None:
                # Greyed: Maya's button has no Blender counterpart; say what Blender has instead.
                from . import notices
                n = button_notice(self.shelf, label)
                text = f"{label}: {n[1]}" if n else f"{label}: not in Blender"
                notices.show(text)
                results.result(self, text)
                return {'CANCELLED'}
            if i == self.index:
                from ..marking.modal import run_action
                try:
                    if self.option:
                        return option_box(context, self.shelf, label, action, self.double)
                    run_action(context, action, False)
                except RuntimeError as ex:
                    from ..operators import maya_errors
                    maya_errors.report_nested(self, ex)
                    return {'CANCELLED'}
                return {'FINISHED'}
        return {'CANCELLED'}

    def _run_user_action(self, context, button):
        """Run a custom Shelf action through the canonical context and undo path."""
        action = button.get("action") or {}
        kind = action.get("type")
        target = action.get("id", "")
        menu_path = target if kind == "maya_menu" else ""
        editor_space, required_mode, object_type = _resolve_shelf_requirements(
            kind, target, menu_path=menu_path,
            editor_space=action.get("space_type", "AUTO"),
            required_mode=action.get("required_mode", action.get("mode", "AUTO")),
            object_type=action.get("object_type", "AUTO"),
        )
        ok, warning = _validate_shelf_context(context, required_mode, object_type)
        if not ok:
            self.report({'WARNING'}, warning)
            return {'CANCELLED'}
        try:
            from ..marking.modal import run_action
            if kind == "operator":
                if "." not in target:
                    raise RuntimeError(f"Invalid Operator ID: {target}")
                return _run_in_editor_space(
                    context,
                    editor_space,
                    lambda ctx: _run_operator_checked(
                        ctx, target, action.get("properties", {}),
                        option=bool(self.option),
                    ),
                )
            if kind == "maya_menu":
                menu_button = {
                    "label": button.get("label", "Shelf Button"),
                    "menu": target,
                    "space_type": editor_space,
                    "required_mode": required_mode,
                    "object_type": object_type,
                }
                return _run_in_editor_space(
                    context, menu_button["space_type"],
                    lambda ctx: self._run_menu(ctx, menu_button),
                )
            if kind == "blender_menu":
                return _run_in_editor_space(
                    context,
                    editor_space,
                    lambda ctx: _run_menu_checked(ctx, target, option=bool(self.option)),
                )
            if kind == "pie_menu":
                # Legacy records remain executable; new Menu buttons use blender_menu.
                return _run_in_editor_space(
                    context,
                    editor_space,
                    lambda ctx: run_action(ctx, ("pie", target), option=bool(self.option)),
                )
            if kind == "tool":
                space_type = editor_space
                return _run_in_editor_space(
                    context,
                    space_type,
                    lambda ctx: run_action(
                        ctx,
                        ("tool", target, {
                            "edit": False,
                            "space_type": space_type,
                            "mode": required_mode,
                            "object_type": object_type,
                        }),
                        option=bool(self.option),
                    ),
                )
            if kind == "ui_operator":
                if "." not in target:
                    raise RuntimeError(f"Invalid UI Operator ID: {target}")
                return _run_in_editor_space(
                    context,
                    editor_space,
                    lambda ctx: run_action(ctx, (target, {}), option=bool(self.option)),
                )
            if kind == "python":
                code = action.get("code", "")
                if not code.strip():
                    raise RuntimeError("Python command is empty")
                ok, message = run_script(context, button.get("label", "Shelf Button"), code)
                if not ok:
                    raise RuntimeError(message)
                return {'FINISHED'}
            raise RuntimeError(f"Unsupported Shelf action type: {kind}")
        except ShelfContextError as ex:
            self.report({'WARNING'}, f"{button.get('label', 'Shelf Button')}: {ex}")
            return {'CANCELLED'}
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError) as ex:
            self.report({'ERROR'}, f"{button.get('label', 'Shelf Button')}: {ex}")
            return {'CANCELLED'}

    def _run_menu(self, context, b):
        """A menu button: the Maya menu item run like the menu (``allset.menu_item`` rules, saved option
        window values, one undo step named after it); Ctrl+click = its option box."""
        from . import menu_map
        from ..marking.modal import run_action
        path = b["menu"]
        if path not in menu_map.MAP:
            from . import notices
            text = f"{b['label']}: no Blender equivalent in Maya Workflow Kit"
            notices.show(text)
            results.result(self, text)
            return {'CANCELLED'}
        try:
            if self.option:                 # the menu's option box, as Shift / Ctrl+click in the menu
                if self.double:
                    take_back_run(path)
                bpy.ops.allset.menu_option_box('INVOKE_DEFAULT', True, item=path)
            else:
                run_action(context, ("item", path))
        except RuntimeError as ex:
            from ..operators import maya_errors
            maya_errors.report_nested(self, ex)
            return {'CANCELLED'}
        return {'FINISHED'}


_by_action = {}


def menu_path_of(shelf, label, action):
    """The Maya main-menu item a factory button runs: ``shelf_map.MENU``, else the first main menu item mapped to the
    same action (Create > Polygon Primitives > Cube for the Cube button), else None."""
    path = shelf_map.menu_path(shelf, label)
    if path:
        return path
    if not _by_action:
        from . import menu_map, menu_data
        main = {m[0] for m in menu_data.MENUS.values()}
        for p, a in menu_map.MAP.items():
            if p.split("/", 1)[0] in main:
                _by_action.setdefault(repr(a), p)
    return _by_action.get(repr(action))


def take_back_run(path):
    """Undo the first click of a double-click when the option box runs the command again with its settings
    ("redo" kind: run + Adjust Last Operation); option windows / tools / dialogs don't run it again."""
    from . import menu_sets
    if (menu_sets.option_kind(path) if path else "redo") == "redo":
        try:
            bpy.ops.ed.undo()
        except RuntimeError:
            pass


def option_box(context, shelf, label, action, double=False):
    """A factory button's option box = its menu item's (``allset.menu_option_box``, like Shift / Ctrl+click in the
    menu): an option window, the tool + Tool Settings, or run + Adjust Last Operation. After a double-click the first
    click already ran the command, so a "run + settings" box takes that run back first (one result, like Maya)."""
    from ..marking.modal import run_action
    path = menu_path_of(shelf, label, action)
    if double:
        take_back_run(path)
    if path:
        return bpy.ops.allset.menu_option_box('INVOKE_DEFAULT', True, item=path)
    run_action(context, action, True)
    return {'FINISHED'}
