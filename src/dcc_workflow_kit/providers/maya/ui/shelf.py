# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Shelf: factory shelves as Blender operator buttons, user shelves of Python
scripts, drawn under the Status Line in a thin "Maya strip" area.

Maya's shelf behaviour, tab order and buttons.

- The strip is an Image Editor area marked by the hidden Mask ``.AllsetStrip``
  (``space.mask``): its header row draws the Status Line, its tool header row the
  shelf. The Maya Workflow Kit template uses two header-only areas instead, the strip
  without its tool header and a shelf row marked ``.AllsetShelf`` whose header draws
  the shelf: Blender keeps every area at least one header high, so both rows follow
  the UI scale (a two-row area of fixed height lost its tool header at scale 1.25).
- The shelf row is a 64 px shelf: its header = the shelf
  tabs, its WINDOW region = 32 px kit-made colour icons (``shelf_icons``) drawn and clicked as gizmos
  (``ALLSET_GGT_shelf``: a gizmo map runs before the image editor's tool keymap, gives hover and the
  operator's tooltip). Click = command; a second click within the double-click time or Ctrl+click =
  options (Adjust Last Operation), like Maya's doubleClickCommand. ``IMAGE_HT_header.draw`` / ``IMAGE_HT_tool_header.draw`` are swapped while
  the add-on is enabled and restored on unregister; unmarked Image Editors draw as
  usual.
- Factory buttons: ``shelf_data`` (generated) + ``shelf_map`` (Blender action, icon),
  run with ``marking.modal.run_action``. Click = command, double-click (or Ctrl+click)
  = options (Adjust Last Operation of that run), like Maya's doubleClickCommand.
- User shelves: ``shelves.json`` in the extension's user directory; a button runs
  its Python script (Maya ``-sourceType python``).
- Every factory button keeps its Maya slot. Buttons without a
  Blender action are drawn greyed; their tooltip and a click show the notice (``button_notice``) in the
  Help Line, like greyed Maya menu items.
- Ctrl+Shift+click on a Maya menu item adds a button for it to the shelf shown (as Maya does),
  factory tabs included. A menu button is ``{"label", "icon", "script": "", "menu":
  <Maya menu path>}`` and runs that path like the menu; on a factory tab it is stored in ``shelves.json``
  ``"extra"[<shelf id>]`` and drawn after the factory slots, so every factory button keeps its Maya slot.
"""

import json
import os
import time
import traceback

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from .. import i18n, results
from . import own_draw, shelf_data, shelf_icons, shelf_map

MARKER = ".AllsetStrip"
SHELF_MARKER = ".AllsetShelf"   # the template's shelf row
USER_PREFIX = "USER:"
DEFAULT_USER = {"shelves": [{"name": "Custom", "buttons": []}]}
STRIP_PX = 68          # header + tool header rows at UI scale 1
_user = {}             # cached shelves.json content


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
            return "VIEW_3D", "EDIT_MESH", "MESH"
        if any(token in menu_path for token in ("polygon primitives", "create polygon", "create/")):
            return "VIEW_3D", "OBJECT", "ANY"
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


# --- storage -------------------------------------------------------------------------------------

def _package():
    from ....identity import package_id
    return package_id()


def store_path():
    """``shelves.json`` in the extension's user directory (legacy add-on build: a folder inside the add-on's own
    folder — nothing is written to the user's Blender config, #42)."""
    try:
        base = bpy.utils.extension_path_user(_package(), create=True)
    except (ValueError, AttributeError):
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_data")
        os.makedirs(base, exist_ok=True)
    return os.path.join(base, "maya_shelves.json")


def user_data():
    if not _user:
        data = None
        path = store_path()
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                traceback.print_exc()
        if not isinstance(data, dict) or not isinstance(data.get("shelves"), list):
            data = json.loads(json.dumps(DEFAULT_USER))
        _user.update(data)
    return _user


def save_user():
    with open(store_path(), "w", encoding="utf-8") as fh:
        json.dump(user_data(), fh, indent=1)


def reload_user():
    _user.clear()
    return user_data()


def user_shelf(name):
    return next((s for s in user_data()["shelves"] if s["name"] == name), None)


def factory_extras(shelf_id, create=False):
    """Buttons added to factory shelf ``shelf_id`` (after its Maya slots); None if there are none and
    ``create`` is off."""
    extra = user_data().get("extra")
    if not isinstance(extra, dict):
        if not create:
            return None
        extra = user_data()["extra"] = {}
    if create:
        return extra.setdefault(shelf_id, [])
    return extra.get(shelf_id)


def editable_buttons(shelf_id, create=False):
    """The list of user-made buttons of a shelf: a user shelf's buttons, or a factory shelf's added ones."""
    if shelf_id.startswith(USER_PREFIX):
        s = user_shelf(shelf_id[len(USER_PREFIX):])
        return s["buttons"] if s is not None else None
    if not any(name == shelf_id for name, _l, _b in shelf_data.SHELVES):
        return None
    return factory_extras(shelf_id, create)


def button_record(shelf_id, index):
    """The stored dict of the user-made button at ``index`` in the shelf's slot order (None for a factory one)."""
    buttons = editable_buttons(shelf_id) or []
    if not buttons:
        return None
    if not shelf_id.startswith(USER_PREFIX):
        index -= factory_count(shelf_id)
    return buttons[index] if 0 <= index < len(buttons) else None


def factory_count(shelf_id):
    """Number of Maya slots of factory shelf ``shelf_id`` (= ``len(all_buttons(shelf_id))`` without building the
    buttons); 0 for any other id."""
    for name, _label, buttons in shelf_data.SHELVES:
        if name == shelf_id:
            return len(buttons)
    return 0


def menu_label(path):
    """The Maya menu item's label (the path's last part, without a "#n" duplicate suffix)."""
    return path.split("#")[0].rsplit("/", 1)[-1]


def add_menu_item(context, path, shelf_id=None):
    """Append a button that runs Maya menu item ``path`` to the shelf shown (as Maya does); saved at once.
    Returns (shelf id, tab label, button)."""
    shelf_id = shelf_id or current(context)
    buttons = editable_buttons(shelf_id, create=True)
    if buttons is None:                       # a stale id: the shelf Maya shows by default
        shelf_id = shelf_data.DEFAULT
        buttons = editable_buttons(shelf_id, create=True)
    button = {"label": menu_label(path), "icon": 'SCRIPT', "script": "", "menu": path}
    buttons.append(button)
    save_user()
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()
    return shelf_id, dict(shelves()).get(shelf_id, shelf_id), button


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


# --- shelves and buttons -------------------------------------------------------------------------

def shelves():
    """[(id, tab label)] in Maya order: factory tabs (labels in the interface language), then the user shelves
    ("Custom" first, named by the user)."""
    out = [(name, i18n.iface(label)) for name, label, _b in shelf_data.SHELVES]
    out += [(USER_PREFIX + s["name"], s["name"]) for s in user_data()["shelves"]]
    return out


def all_buttons(name):
    """[(index, label, action or None, icon)] of every button of a factory shelf, in Maya order."""
    for shelf, _label, buttons in shelf_data.SHELVES:
        if shelf == name:
            out = []
            for i, (label, command) in enumerate(buttons):
                hit = shelf_map.lookup(shelf, label, command)
                out.append((i, label, hit[0], hit[1]) if hit is not None else (i, label, None, 'NONE'))
            return out
    return []


def button_labels(shelf_id):
    """[(index, label)] of every button of a shelf in slot order: a factory shelf's Maya slots then its added buttons,
    or a user shelf's buttons (the Marking Menu Editor's Shelf Button items)."""
    if shelf_id.startswith(USER_PREFIX):
        s = user_shelf(shelf_id[len(USER_PREFIX):])
        return [(i, b["label"]) for i, b in enumerate(s["buttons"])] if s is not None else []
    out = [(i, label) for i, label, _action, _icon in all_buttons(shelf_id)]
    return out + [(len(out) + k, b["label"]) for k, b in enumerate(factory_extras(shelf_id) or ())]


def button_index(shelf_id, label):
    """Slot index of the button ``label`` on shelf ``shelf_id`` (the first one of that label), or None."""
    return next((i for i, lab in button_labels(shelf_id) if lab == label), None)


def factory_buttons(name):
    """[(index, label, action, icon)] of the mapped buttons of a factory shelf."""
    return [b for b in all_buttons(name) if b[2] is not None]


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


def current(context=None):
    from .. import preferences
    try:
        cur = preferences.get(context).shelf_current
    except KeyError:
        cur = ""
    ids = [s[0] for s in shelves()]
    return cur if cur in ids else shelf_data.DEFAULT


def set_current(context, shelf_id):
    from .. import preferences
    preferences.get(context).shelf_current = shelf_id


def run_script(context, label, script):
    """Run a user shelf button's Python script with Blender's Run Script (``runner.run``: a temporary Text named after
    the button, the Command Line's names, its variables not kept); returns (ok, message)."""
    from ..command_line import runner
    res = runner.run(script, name=f".allset_shelf {label}", persist=False, remember=False)
    if res.error:                       # a user script: report, don't break the UI
        return False, f"{label}: {res.text.removeprefix('# Error: ')}"
    return True, ""


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
                bpy.ops.allset.menu_option_box('INVOKE_DEFAULT', item=path)
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
        return bpy.ops.allset.menu_option_box('INVOKE_DEFAULT', item=path)
    run_action(context, action, True)
    return {'FINISHED'}


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

    def execute(self, context):
        buttons = editable_buttons(current(context)) or []
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


# --- the strip area ----------------------------------------------------------------------------------

def is_strip(space):
    mask = getattr(space, "mask", None)
    return space is not None and space.type == 'IMAGE_EDITOR' and mask is not None and mask.name == MARKER


def is_shelf_row(space):
    mask = getattr(space, "mask", None)
    return space is not None and space.type == 'IMAGE_EDITOR' and mask is not None and mask.name == SHELF_MARKER


def is_kit_row(space):
    """The Status Line strip or the Shelf row: kit chrome in an Image Editor, never an editor of its own."""
    return is_strip(space) or is_shelf_row(space)


def strip_area(screen):
    for area in (screen.areas if screen else ()):
        if area.type == 'IMAGE_EDITOR' and is_strip(area.spaces.active):
            return area
    return None


def shelf_row_area(screen):
    for area in (screen.areas if screen else ()):
        if area.type == 'IMAGE_EDITOR' and is_shelf_row(area.spaces.active):
            return area
    return None


def marker_mask():
    mask = bpy.data.masks.get(MARKER)
    if mask is None:
        mask = bpy.data.masks.new(MARKER)
        mask.use_fake_user = True
    return mask


def make_strip(space):
    """Turn an Image Editor space into the Maya strip."""
    space.mask = marker_mask()
    space.mode = 'VIEW'
    space.show_region_tool_header = True
    space.show_region_ui = False
    space.show_region_toolbar = False


class ALLSET_OT_shelf_strip_toggle(bpy.types.Operator):
    """Show or hide the Status Line + Shelf strip above the largest 3D View"""
    bl_idname = "allset.shelf_strip_toggle"
    bl_label = "Shelf"

    def execute(self, context):
        from .status_line import main_view3d
        screen = context.screen
        win = context.window
        area = strip_area(screen)
        if area is not None:
            for area in (area, shelf_row_area(screen)):
                if area is None:
                    continue
                region = next(r for r in area.regions if r.type == 'WINDOW')
                with context.temp_override(window=win, screen=screen, area=area, region=region):
                    bpy.ops.screen.area_close()
            return {'FINISHED'}
        view3d, region = main_view3d(screen)
        if view3d is None:
            self.report({'WARNING'}, "No 3D View to put the shelf over")
            return {'CANCELLED'}
        before = {a.as_pointer() for a in screen.areas}
        px = STRIP_PX * context.preferences.system.ui_scale
        factor = max(0.5, 1.0 - px / max(view3d.height, 1))
        with context.temp_override(window=win, screen=screen, area=view3d, region=region):
            bpy.ops.screen.area_split(direction='HORIZONTAL', factor=factor)
        new = next((a for a in screen.areas if a.as_pointer() not in before), None)
        if new is None:
            return {'CANCELLED'}
        new.type = 'IMAGE_EDITOR'
        make_strip(new.spaces.active)
        return {'FINISHED'}


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


# --- drawing --------------------------------------------------------------------------------------------

class ALLSET_MT_shelf_tabs(bpy.types.Menu):
    """Choose the shelf (Maya shelf tabs)"""
    bl_idname = "ALLSET_MT_shelf_tabs"
    bl_label = "Shelves"

    def draw(self, context):
        cur = current(context)
        for shelf_id, label in shelves():
            if shelf_id.startswith(USER_PREFIX) and shelf_id == USER_PREFIX + user_data()["shelves"][0]["name"]:
                self.layout.separator()
            op = self.layout.operator(ALLSET_OT_shelf_select.bl_idname, text=label,
                                      icon='RADIOBUT_ON' if shelf_id == cur else 'RADIOBUT_OFF')
            op.shelf = shelf_id


class ALLSET_MT_shelf_settings(bpy.types.Menu):
    """Maya shelf menu: new/delete shelf, add/edit/delete buttons"""
    bl_idname = "ALLSET_MT_shelf_settings"
    bl_label = "Shelf"

    def draw(self, context):
        layout = self.layout
        layout.operator(ALLSET_OT_shelf_new.bl_idname, icon='ADD')
        layout.operator("allset.shelf_editor_open", icon='WINDOW', text="Shelf Editor")
        layout.operator(ALLSET_OT_shelf_delete.bl_idname, icon='TRASH')
        layout.separator()
        layout.menu(ALLSET_MT_shelf_add_action.bl_idname, icon='ADD', text="Add Shelf Button...")
        layout.operator(ALLSET_OT_shelf_add_last_command.bl_idname, icon='CONSOLE')
        buttons = editable_buttons(current(context))      # a factory tab's added menu buttons too
        if buttons:
            layout.separator()
            for i, b in enumerate(buttons):
                row = layout.row()
                row.operator(ALLSET_OT_shelf_edit_button.bl_idname, text=f"Edit {b['label']}",
                             icon='GREASEPENCIL').index = i
            layout.separator()
            for i, b in enumerate(buttons):
                layout.operator(ALLSET_OT_shelf_remove_button.bl_idname, text=f"Delete {b['label']}",
                                icon='X').index = i


def draw_shelf(layout, context):
    """Shelf row: settings menu, tab dropdown with < >, then the current shelf's buttons."""
    cur = current(context)
    label = dict(shelves()).get(cur, cur)
    row = layout.row(align=True)
    row.menu(ALLSET_MT_shelf_settings.bl_idname, text="", icon='PREFERENCES')
    row = layout.row(align=True)
    row.operator(ALLSET_OT_shelf_step.bl_idname, text="", icon='TRIA_LEFT').forward = False
    row.menu(ALLSET_MT_shelf_tabs.bl_idname, text=label)
    row.operator(ALLSET_OT_shelf_step.bl_idname, text="", icon='TRIA_RIGHT').forward = True
    layout.separator(type='LINE')
    row = layout.row(align=True)
    if cur.startswith(USER_PREFIX):
        s = user_shelf(cur[len(USER_PREFIX):]) or {"buttons": []}
        if not s["buttons"]:
            row.operator(ALLSET_OT_shelf_add_button.bl_idname, text="Add Button", icon='ADD')
        for i, b in enumerate(s["buttons"]):
            if b.get("type") == "separator" or (b.get("action") or {}).get("type") == "separator":
                row.separator(factor=0.45)
                continue
            icon_kwargs = shelf_icons.icon_ui_kwargs(b.get("icon", "SCRIPT"))
            op = row.operator(
                ALLSET_OT_shelf_button.bl_idname,
                text=b.get("label", "Button") if b.get("icon", "SCRIPT") == 'SCRIPT' else "",
                **icon_kwargs,
            )
            op.shelf, op.index = cur, i
        return
    # Factory shelves have immutable Maya slots plus user-added records stored
    # in shelves.json under ``extra``. Draw both groups in slot order so buttons
    # added by Shelf Editor are visible in the real Image Editor tool header.
    for i, _label, _action, icon in factory_buttons(cur):
        op = row.operator(ALLSET_OT_shelf_button.bl_idname, text="", icon=icon)
        op.shelf, op.index = cur, i

    factory_slot_count = len(all_buttons(cur))
    for offset, button in enumerate(factory_extras(cur) or ()):
        if button.get("type") == "separator" or (button.get("action") or {}).get("type") == "separator":
            row.separator(factor=0.45)
            continue
        icon_kwargs = shelf_icons.icon_ui_kwargs(button.get("icon", "SCRIPT"))
        op = row.operator(
            ALLSET_OT_shelf_button.bl_idname,
            text=button.get("label", "Button") if button.get("icon", "SCRIPT") == 'SCRIPT' else "",
            **icon_kwargs,
        )
        op.shelf, op.index = cur, factory_slot_count + offset


def draw_shelf_tabs(layout, context):
    """Maya shelf tab row: settings, then one flat tab per shelf,
    the current one raised."""
    cur = current(context)
    layout.menu(ALLSET_MT_shelf_settings.bl_idname, text="", icon='PREFERENCES')
    row = layout.row(align=True)
    for shelf_id, label in shelves():
        row.operator(ALLSET_OT_shelf_select.bl_idname, text=label, emboss=shelf_id == cur).shelf = shelf_id


_factory_cache = {}


def icon_buttons(context, cur=None):
    """(shelf id, [(button index, label, shelf colour key, mapped)]) of the current shelf (``cur``: the current shelf
    id already read), in Maya order (greyed buttons keep their slot)."""
    cur = current(context) if cur is None else cur
    if cur.startswith(USER_PREFIX):
        s = user_shelf(cur[len(USER_PREFIX):]) or {"buttons": []}
        return cur, [(i, b["label"], None, _record_mapped(b)) for i, b in enumerate(s["buttons"])]
    if cur not in _factory_cache:
        _factory_cache[cur] = [(i, label, cur, action is not None) for i, label, action, _icon in all_buttons(cur)]
    extras = factory_extras(cur)
    if not extras:
        return cur, _factory_cache[cur]
    n = len(_factory_cache[cur])          # added buttons after the Maya slots
    return cur, _factory_cache[cur] + [(n + k, b["label"], None, _record_mapped(b)) for k, b in enumerate(extras)]


def _record_mapped(b):
    if not b.get("menu"):
        return True
    from . import menu_map
    return b["menu"] in menu_map.MAP


def slot_button(context, slot):
    cur, buttons = icon_buttons(context)
    return (cur, buttons[slot]) if 0 <= slot < len(buttons) else (cur, None)


class ALLSET_OT_shelf_slot(bpy.types.Operator):
    """Shelf icon"""
    bl_idname = "allset.shelf_slot"
    bl_label = "Shelf Button"
    bl_options = {'INTERNAL'}

    slot: IntProperty()

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        cur, b = slot_button(context, props.slot)
        if b is None:
            return ""
        rec = button_record(cur, b[0])
        if rec is not None and (rec.get("menu") or rec.get("type") in {"action", "separator"}):
            return record_tooltip(rec)
        if cur.startswith(USER_PREFIX) or rec is not None:
            return f"{b[1]} (shelf)"
        return button_tooltip(cur, b[1], b[3])

    def invoke(self, context, event):
        cur, b = slot_button(context, self.slot)
        if b is None:
            return {'CANCELLED'}
        return bpy.ops.allset.shelf_button('INVOKE_DEFAULT', shelf=cur, index=b[0])


# Shelf buttons are 35x34 with 32 px icons.
ICON_PX = 32
PITCH_PX = 35
LEFT_PX = 6
# Maya's shelf: the shelf row is one 64 px block — an
# 18 px tab strip at the top (tabs from x 37, Segoe UI 11 px), the shelf menu / editor glyphs in a 16 px column at
# x 16, icons from x 43 at y 24 under the row's top, 12 px separators between Maya's button groups
# (``shelf_data.GAPS``). The kit draws that whole block in the shelf row's WINDOW region when the row has no
# header (the Maya Workflow Kit template); with a header (older files) the header keeps the tab buttons.
TAB_PX = 19
TAB_LEFT_PX = 37
TAB_PAD_PX = 10
TAB_FONT_PX = 11
STRIP_LEFT_PX = 43
SEP_PX = 12


def _space_of(region):
    """The space of the area holding ``region`` (gizmo / draw contexts give it directly; tests pass bare regions)."""
    space = getattr(bpy.context, "space_data", None)
    area = getattr(bpy.context, "area", None)
    if area is not None and any(r == region for r in area.regions):
        return space
    for window in bpy.context.window_manager.windows:
        for a in window.screen.areas:
            if any(r == region for r in a.regions):
                return a.spaces.active
    return None


def tabs_in_window(space):
    """The shelf row draws its tab strip itself (no header region)."""
    return space is not None and is_shelf_row(space) and not space.show_region_header


def _gaps(cur=None):
    cur = current(bpy.context) if cur is None else cur
    return () if cur.startswith(USER_PREFIX) else shelf_data.GAPS.get(cur, ())


# Maya's shelf is a flow of rows one row high — buttons that don't fit wrap to the next row, a 12 px
# vertical scroll bar with up / down arrows sits at the right, the wheel over the icons moves one row
# (Maya: scroll bar page = single row 35 px, wheel = 1 row).
SCROLL_PX = 12
SCROLL_RIGHT_PX = 16     # gap between the scroll bar and the area's right edge
_row = {}      # shelf id -> first row shown


def row_layout(width, count, scale, gaps=(), left=STRIP_LEFT_PX, separators=()):
    """[(row, x)] for ``count`` slots in a row ``width`` px wide (scroll bar excluded): Maya's flow — a slot that
    would cross the right edge starts the next row; a separator gap before it counts only inside a row."""
    out = []
    x0 = left * scale
    limit = width - (SCROLL_PX + SCROLL_RIGHT_PX + 2) * scale
    row, x = 0, x0
    gaps = set(gaps)
    separators = set(separators)
    for slot in range(count):
        if slot in gaps and x > x0:
            x += SEP_PX * scale
        is_separator = slot in separators
        slot_width = 8 if is_separator else ICON_PX
        pitch = 12 if is_separator else PITCH_PX
        if x > x0 and x + slot_width * scale > limit:
            row, x = row + 1, x0
        out.append((row, x))
        x += pitch * scale
    return out


def _is_separator(record):
    return bool(record and (record.get("type") == "separator"
                            or (record.get("action") or {}).get("type") == "separator"))


def _separator_slots(cur, buttons):
    """Slots of ``buttons`` (``icon_buttons``) that are separators: only user-made buttons can be, so the stored
    records are read once (the Maya slots of a factory shelf have none)."""
    records = editable_buttons(cur) or []
    if not records:
        return frozenset()
    first = 0 if cur.startswith(USER_PREFIX) else factory_count(cur)
    out = set()
    for slot, (index, _label, _colour, _mapped) in enumerate(buttons):
        k = index - first
        if 0 <= k < len(records) and _is_separator(records[k]):
            out.add(slot)
    return frozenset(out)


def _plan(region, scale, cur=None):
    """(shelf id, tabs in the window, [(row, x)] per slot, buttons, separator slots) of the current shelf in
    ``region`` (``cur``: the current shelf id already read): read once and used for every slot of one redraw or one
    pick."""
    space = _space_of(region)
    tabs = tabs_in_window(space)
    cur, buttons = icon_buttons(bpy.context, cur)
    separator_slots = _separator_slots(cur, buttons)
    lay = row_layout(getattr(region, "width", 10 ** 6), len(buttons), scale, _gaps(cur) if tabs else (),
                     STRIP_LEFT_PX if tabs else LEFT_PX, separators=separator_slots)
    return cur, tabs, lay, buttons, separator_slots


def _layout(region, scale):
    return _plan(region, scale)[:3]


def rows_of(region, scale, plan=None):
    """(rows, first row shown) of the current shelf in ``region`` (``plan``: a ``_plan`` already read)."""
    cur, _tabs, lay = plan[:3] if plan is not None else _layout(region, scale)
    rows = (lay[-1][0] + 1) if lay else 1
    first = max(0, min(_row.get(cur, 0), rows - 1))
    return rows, first


def scroll_shelf(context, delta):
    """Move the current shelf ``delta`` rows (clamped); True when it moved."""
    region = context.region
    cur = current(context)
    rows, first = rows_of(region, context.preferences.system.ui_scale or 1.0)
    new = max(0, min(first + delta, rows - 1))
    _row[cur] = new
    region.tag_redraw()
    return new != first


def icon_rect(region, slot, scale):
    """(x, y, size) of ``slot`` in region pixels; a slot on another row than the one shown is placed past the right
    edge (not drawn, not picked)."""
    cur, tabs, lay = _layout(region, scale)
    _cur, buttons = icon_buttons(bpy.context)
    return _plan_rect((cur, tabs, lay, buttons, _separator_slots(cur, buttons)), region, slot, scale)


def _plan_rect(plan, region, slot, scale):
    """``icon_rect`` from a layout ``_plan`` already read."""
    cur, tabs, lay, buttons, separators = plan
    top = round(TAB_PX * scale) if tabs else 0
    is_separator = 0 <= slot < len(buttons) and slot in separators
    size = min((8 if is_separator else ICON_PX) * scale, region.height - top - 4)
    y = (region.height - top - size) / 2
    off = getattr(region, "width", 0) + 10 ** 6
    if slot >= len(lay):           # past the last button (tests ask for empty slots)
        return off, y, size
    row, x = lay[slot]
    rows = lay[-1][0] + 1
    if row != max(0, min(_row.get(cur, 0), rows - 1)):
        return off, y, size
    return x, y, size


def scroll_rects(region, scale, plan=None):
    """(up, down) rects (x0, y0, x1, y1) of the scroll bar's arrows, or () when every button fits in one row
    (``plan``: a ``_plan`` already read)."""
    rows, _first = rows_of(region, scale, plan)
    if rows <= 1:
        return ()
    tabs = plan[1] if plan is not None else tabs_in_window(_space_of(region))
    top = round(TAB_PX * scale) if tabs else 0
    # off the area's top-right corner: Blender's split / join action zone there takes the click before any region
    # (with --debug-handlers only "Screen Editing" sees the press)
    x1 = region.width - round(SCROLL_RIGHT_PX * scale)
    x0 = x1 - round(SCROLL_PX * scale)
    y0, y1 = round(2 * scale), region.height - top - round(2 * scale)
    mid = (y0 + y1) // 2
    return ((x0, mid, x1, y1), (x0, y0, x1, mid))


_SHELF_SHADERS = {}

def _shelf_shader(name):
    """Reuse built-in shaders across shelf redraws instead of resolving them for every icon/rectangle."""
    shader = _SHELF_SHADERS.get(name)
    if shader is None:
        import gpu
        shader = _SHELF_SHADERS[name] = gpu.shader.from_builtin(name)
    return shader

_SHELF_BATCHES = {}     # (shader, primitive, points) -> GPU batch: the row redraws the same rectangles every time


def _shelf_batch(name, prim, coords, tex_coords=None):
    """The GPU batch of ``coords`` for built-in shader ``name``, made once and drawn again on later redraws (the
    row redraws on every frame and selection change with the same shapes)."""
    key = (name, prim, coords)
    batch = _SHELF_BATCHES.get(key)
    if batch is None:
        from gpu_extras.batch import batch_for_shader
        attrs = {"pos": coords} if tex_coords is None else {"pos": coords, "texCoord": tex_coords}
        batch = batch_for_shader(_shelf_shader(name), prim, attrs)
        if len(_SHELF_BATCHES) > 1024:
            _SHELF_BATCHES.clear()
        _SHELF_BATCHES[key] = batch
    return batch


_TEX_COORDS = ((0, 0), (1, 0), (1, 1), (0, 1))


def _draw_rect(x, y, w, h, colour, texture=None):
    """A rectangle in region pixels (POST_PIXEL draw handler)."""
    import gpu
    coords = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
    gpu.state.blend_set('ALPHA')
    if texture is None:
        sh = _shelf_shader('UNIFORM_COLOR')
        batch = _shelf_batch('UNIFORM_COLOR', 'TRI_FAN', coords)
        sh.uniform_float("color", colour)
    else:
        from .. import compat
        sh = _shelf_shader(compat.LINEAR_IMAGE_SHADER)
        batch = _shelf_batch(compat.LINEAR_IMAGE_SHADER, 'TRI_FAN', coords, _TEX_COORDS)
        sh.uniform_sampler("image", texture)
    batch.draw(sh)
    gpu.state.blend_set('NONE')


def _theme_colour(context):
    """The shelf row background = the user's Image Editor header colour (read only; the kit ships no
    theme, #40), so the shelf sits in the same colour as the Status Line row in any theme."""
    c = context.preferences.themes[0].image_editor.space.header
    return (c[0], c[1], c[2], 1.0)


def _luma(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _text_colours(context):
    """(current tab text, other tab text, glyph) from the user's header text colours: Maya's light current tab and
    dimmer other tabs, readable on a dark or a light header."""
    sp = context.preferences.themes[0].image_editor.space
    base = _theme_colour(context)
    hi = tuple(getattr(sp, "header_text_hi", (1.0, 1.0, 1.0)))[:3]
    text = tuple(getattr(sp, "header_text", hi))[:3]
    other = tuple(t * 0.7 + b * 0.3 for t, b in zip(text, base))
    return (*hi, 1.0), (*other, 1.0), (*text, 1.0)


def _separator_colours(base):
    """Maya's raised vertical rule (dark line + light line) relative to the row colour."""
    dark = tuple(c * 0.55 for c in base[:3])
    light = tuple(c + (1.0 - c) * 0.18 for c in base[:3])
    return (*dark, 1.0), (*light, 1.0)


def _hover_colour(base, mapped):
    """A hover box that shows on dark and light rows: white over dark, black over light."""
    ink = 1.0 if _luma(base) < 0.5 else 0.0
    return (ink, ink, ink, (0.18 if mapped else 0.08) if ink else (0.12 if mapped else 0.05))


# The shelf tab row (and inactive tabs, #373737) is darker than the icon row, the active tab and the Status Line
# (#444444), but both rows share the Image Editor header colour. The tab row's header is dimmed by this black
# overlay (ratio #444444 -> #373737, applied to whatever header colour the user's theme has).
TAB_DIM = 1.0 - 0x37 / 0x44


def draw_tab_row():
    """POST_PIXEL of image editor headers: dim the shelf tab row (``TAB_DIM``)."""
    context = bpy.context
    if not is_shelf_row(context.space_data):
        return
    region = context.region
    _draw_rect(0, 0, region.width, region.height, (0.0, 0.0, 0.0, TAB_DIM))


_hover = {}   # region pointer -> slot under the mouse (set by the gizmos' test_select)
_tab_rects = {}   # region pointer -> [(x0, y0, x1, y1, action)] of the tab strip, drawn last ("menu", "gear", shelf id)


def tab_rects(context, region, tabs=None):
    """Rects of the shelf menu glyph, the editor gear and the tabs in region pixels, left to right (``tabs``: the
    ``shelves()`` list already read)."""
    import blf
    s = context.preferences.system.ui_scale or 1.0
    h = region.height
    th = round(TAB_PX * s)
    out = [(round(14 * s), h - th, round(32 * s), h, "menu"),
           (round(14 * s), round(4 * s), round(32 * s), h - th - round(4 * s), "gear")]
    blf.size(0, TAB_FONT_PX * s)
    x = TAB_LEFT_PX * s
    for shelf_id, label in (shelves() if tabs is None else tabs):
        w = blf.dimensions(0, label)[0] + 2 * TAB_PAD_PX * s
        out.append((round(x), h - th, round(x + w), h, shelf_id))
        x += w + round(2 * s)
    return out


def _text(x, y, text, colour, size):
    import blf
    blf.size(0, size)
    blf.color(0, *colour)
    blf.position(0, x, y, 0)
    blf.draw(0, text)


def _draw_tabs(context, region, base, cur=None):
    """The shelf tab strip: #373737 strip, flat tabs, the current one
    in the row colour with light text, the others dim; the shelf menu glyph left of the tabs, the shelf editor gear
    left of the icons."""
    s = context.preferences.system.ui_scale or 1.0
    h = region.height
    th = round(TAB_PX * s)
    dim = (base[0] * (1 - TAB_DIM), base[1] * (1 - TAB_DIM), base[2] * (1 - TAB_DIM), 1.0)
    _draw_rect(0, h - th, region.width, th, dim)
    tabs = shelves()
    rects = _tab_rects[region.as_pointer()] = tab_rects(context, region, tabs)
    cur = current(context) if cur is None else cur
    labels = dict(tabs)
    hover = _hover.get(region.as_pointer())
    text_on, text_off, grey = _text_colours(context)
    for x0, y0, x1, y1, action in rects:
        if action == "menu":
            for k in range(3):
                _draw_rect(x0 + 2 * s, y0 + (5 + 4 * k) * s, (x1 - x0) - 4 * s, max(1.0, 1.5 * s), grey)
            continue
        if action == "gear":
            cy = (y0 + y1) / 2
            _draw_rect(x0 + 2 * s, cy - 6 * s, (x1 - x0) - 4 * s, 12 * s, None,
                       shelf_icons_gear())
            continue
        on = action == cur
        if on:
            _draw_rect(x0, y0, x1 - x0, y1 - y0 - s, base)
        elif hover == ("tab", action):
            _draw_rect(x0, y0, x1 - x0, y1 - y0 - s, _hover_colour(dim, False))
        _text(x0 + TAB_PAD_PX * s, y0 + 5 * s, labels.get(action, action),
              text_on if on else text_off, TAB_FONT_PX * s)


_gear_tex = []


def shelf_icons_gear():
    if not _gear_tex:
        import gpu
        import numpy as np
        from . import status_icons
        cv = status_icons.Canvas(32)
        status_icons.gear(cv, 0.5, 0.5, 0.40, status_icons.GREY)
        px = cv.pixels().reshape(32, 32, 4).copy()
        rgb = px[..., :3]
        px[..., :3] = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        buf = gpu.types.Buffer('FLOAT', 32 * 32 * 4, px.ravel().tolist())
        _gear_tex.append(gpu.types.GPUTexture((32, 32), format='RGBA32F', data=buf))
    return _gear_tex[0]


def _separators(region, s, count, plan=None):
    """x of each Maya separator before ``count`` drawn icons."""
    out = []
    plan = plan or _plan(region, s)
    for g in _gaps(plan[0]):
        if g < count:
            x, _y, size = _plan_rect(plan, region, g, s)
            out.append(x - (PITCH_PX - ICON_PX + SEP_PX) * s / 2)
    return out


def draw_row():
    """POST_PIXEL of image editors: the shelf icon row (background, hover box, icons; the tab strip when the row has
    no header). The gizmos only pick (draw handlers draw in plain region pixels; gizmo drawing in the image editor
    does not show)."""
    context = bpy.context
    if not is_shelf_row(context.space_data):
        return
    region = context.region
    s = context.preferences.system.ui_scale
    base = _theme_colour(context)
    _draw_rect(0, 0, region.width, region.height, base)
    tabs = tabs_in_window(context.space_data)
    cur = current(context)          # read once for the whole redraw
    if tabs:
        _draw_tabs(context, region, base, cur)
    plan = _plan(region, s, cur)
    _cur, buttons, separators = plan[0], plan[3], plan[4]
    hover = _hover.get(region.as_pointer())
    shown = 0
    for slot, (index, label, colour_key, mapped) in enumerate(buttons[:SLOTS]):
        x, y, size = _plan_rect(plan, region, slot, s)
        if x > region.width:
            continue                  # another row
        shown = slot + 1
        if slot in separators:
            # Keep the slot narrow, but draw a divider at nearly the full button height.
            separator_height = min(ICON_PX * s, region.height - (TAB_PX * s if tabs else 0) - 4)
            separator_y = (region.height - (TAB_PX * s if tabs else 0) - separator_height) / 2
            cx = x + size / 2
            dark, light = _separator_colours(base)
            _draw_rect(cx - s, separator_y, max(1.0, s), separator_height, dark)
            _draw_rect(cx, separator_y, max(1.0, s), separator_height, light)
            continue
        if slot == hover:
            _draw_rect(x - 2, y - 2, size + 4, size + 4, _hover_colour(base, mapped))
        if colour_key is None:
            tex = _user_texture(_cur, index, label, not mapped, shelf_icons.texture_size(size))
        else:
            tex = shelf_icons.texture(label, colour_key, greyed=not mapped, size=shelf_icons.texture_size(size),
                                      index=index)
        _draw_rect(x, y, size, size, None, tex)
    if tabs:
        dark, light = _separator_colours(base)
        for x in _separators(region, s, shown, plan):   # Maya: a raised vertical rule in a 12 px gap
            _draw_rect(x - s, round(4 * s), max(1.0, s), size + 2 * s, dark)
            _draw_rect(x, round(4 * s), max(1.0, s), size + 2 * s, light)
    _draw_scroll_bar(region, s, base, plan)


def _triangle(cx, cy, half, up, colour):
    import gpu
    pts = ((cx - half, cy - half / 2), (cx + half, cy - half / 2), (cx, cy + half / 2)) if up else \
        ((cx - half, cy + half / 2), (cx + half, cy + half / 2), (cx, cy - half / 2))
    sh = _shelf_shader('UNIFORM_COLOR')
    batch = _shelf_batch('UNIFORM_COLOR', 'TRIS', pts)
    gpu.state.blend_set('ALPHA')
    sh.uniform_float("color", colour)
    batch.draw(sh)
    gpu.state.blend_set('NONE')


def _draw_scroll_bar(region, s, base, plan=None):
    """The shelf scroll bar (12 px, ▲ / ▼) while the shelf has more than one row; an
    arrow is dimmed at its end (``plan``: the redraw's ``_plan``)."""
    plan = plan or _plan(region, s)
    rects = scroll_rects(region, s, plan)
    if not rects:
        return
    rows, first = rows_of(region, s, plan)
    up, down = rects
    _draw_rect(up[0], down[1], up[2] - up[0], up[3] - down[1], tuple(max(0.0, c - 0.06) for c in base[:3]) + (1.0,))
    hover = _hover.get(region.as_pointer())
    for i, (r, on) in enumerate(((up, first > 0), (down, first < rows - 1))):
        if hover == ("scroll", i) and on:
            _draw_rect(r[0], r[1], r[2] - r[0], r[3] - r[1], _hover_colour(base, True))
        grey = 0.75 if on else 0.4
        _triangle((r[0] + r[2]) / 2, (r[1] + r[3]) / 2, 3.5 * s, i == 0, (grey, grey, grey, 1.0))


def _user_texture(shelf_id, index, label, greyed, size):
    """Icon of a user-made button. A menu button shows the menu item's kit picture (``menu_icon_data``:
    the same command's shelf drawing, else its Status Line / Tool Box / menu drawing), else Maya's command button
    with the label's initials (Maya: the item's image, else a default command icon with a label)."""
    rec = button_record(shelf_id, index)
    if rec:
        chosen_icon = rec.get("icon", "SCRIPT")
        if chosen_icon not in {"", "NONE", "SCRIPT"}:
            custom_texture = shelf_icons.icon_gpu_texture(chosen_icon, greyed=greyed, size=size)
            if custom_texture is not None:
                return custom_texture
    path = rec.get("menu") if rec else None
    if path:
        from . import menu_icon_data, menu_icons
        pic = menu_icon_data.ICONS.get(path)
        if pic is not None and pic[0] == "shelf":
            return shelf_icons.texture(pic[2], pic[1], greyed=greyed, size=size, index=pic[3])
        if pic is not None:
            return shelf_icons.texture_of(("menu",) + tuple(pic), lambda n: menu_icons.picture(pic, n),
                                          greyed=greyed, size=size)
    return shelf_icons.texture(label, None, greyed=greyed, size=size)


class ALLSET_GT_shelf_tab(bpy.types.Gizmo):
    """Tab strip slot ``slot`` of ``tab_rects`` (the shelf menu, the gear, a tab): picking only, drawn by
    ``draw_row``; clicking runs allset.shelf_tab."""
    bl_idname = "ALLSET_GT_shelf_tab"
    __slots__ = ("slot",)

    def setup(self):
        self.slot = 0

    def draw(self, context):
        pass

    def test_select(self, context, location):
        if not tabs_in_window(context.space_data):
            return -1
        key = context.region.as_pointer()
        rects = _tab_rects.get(key) or tab_rects(context, context.region)
        hit = self.slot < len(rects) and rects[self.slot][0] <= location[0] <= rects[self.slot][2] \
            and rects[self.slot][1] <= location[1] <= rects[self.slot][3]
        tag = ("tab", rects[self.slot][4]) if self.slot < len(rects) else None
        if hit:
            if _hover.get(key) != tag:
                _hover[key] = tag
                context.region.tag_redraw()
            return 0
        if tag is not None and _hover.get(key) == tag:
            _hover.pop(key, None)
            context.region.tag_redraw()
        return -1


class ALLSET_OT_shelf_tab(bpy.types.Operator):
    """Shelf tab strip: show this shelf, or open the shelf menu"""
    bl_idname = "allset.shelf_tab"
    bl_label = "Shelf Tab"
    bl_options = {'INTERNAL'}

    slot: IntProperty()

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        rects = _tab_rects.get(context.region.as_pointer()) if context.region else None
        action = rects[props.slot][4] if rects and props.slot < len(rects) else ""
        if action == "menu":
            return "Shelf menu: choose a shelf"
        if action == "gear":
            return "Shelf editor: new / delete shelf, add / edit / remove buttons"
        return f"Show the {dict(shelves()).get(action, action)} shelf"

    def invoke(self, context, event):
        rects = _tab_rects.get(context.region.as_pointer()) if context.region else None
        if not rects or self.slot >= len(rects):
            return {'CANCELLED'}
        action = rects[self.slot][4]
        _hover.pop(context.region.as_pointer(), None)
        if action == "menu":
            bpy.ops.wm.call_menu(name=ALLSET_MT_shelf_tabs.bl_idname)
        elif action == "gear":
            bpy.ops.wm.call_menu(name=ALLSET_MT_shelf_settings.bl_idname)
        else:
            set_current(context, action)
            _redraw(context)
        return {'FINISHED'}


TAB_SLOTS = 24


class ALLSET_GT_shelf_icon(bpy.types.Gizmo):
    """Shelf slot ``slot`` (the current shelf's button there): picking only, drawn by ``draw_row``;
    clicking runs allset.shelf_slot (its target operator). A fixed pool, so switching shelves needs
    no rebuild."""
    bl_idname = "ALLSET_GT_shelf_icon"
    __slots__ = ("slot",)

    def setup(self):
        self.slot = 0

    def draw(self, context):
        pass

    def test_select(self, context, location):
        key = context.region.as_pointer()
        hit = slot_button(context, self.slot)[1] is not None
        if hit and tabs_in_window(context.space_data) \
                and location[1] > context.region.height - TAB_PX * context.preferences.system.ui_scale:
            hit = False
        if hit:
            x, y, size = icon_rect(context.region, self.slot, context.preferences.system.ui_scale)
            hit = x <= location[0] <= x + size and y <= location[1] <= y + size
        if hit:
            if _hover.get(key) != self.slot:
                _hover[key] = self.slot
                context.region.tag_redraw()
            return 0
        if _hover.get(key) == self.slot:
            _hover.pop(key, None)
            context.region.tag_redraw()
        return -1


class ALLSET_GT_shelf_scroll(bpy.types.Gizmo):
    """The shelf scroll bar's up (slot 0) / down (slot 1) arrow: picking only, drawn by ``draw_row``. Gizmos come
    before the image editor's tool keymap (its Sample tool took plain clicks)."""
    bl_idname = "ALLSET_GT_shelf_scroll"
    __slots__ = ("slot",)

    def setup(self):
        self.slot = 0

    def draw(self, context):
        pass

    def test_select(self, context, location):
        key = context.region.as_pointer()
        rects = scroll_rects(context.region, context.preferences.system.ui_scale or 1.0)
        r = rects[self.slot] if rects else None
        tag = ("scroll", self.slot)
        if r is not None and r[0] <= location[0] <= r[2] and r[1] <= location[1] <= r[3]:
            if _hover.get(key) != tag:
                _hover[key] = tag
                context.region.tag_redraw()
            return 0
        if _hover.get(key) == tag:
            _hover.pop(key, None)
            context.region.tag_redraw()
        return -1


class ALLSET_OT_shelf_scroll(bpy.types.Operator):
    """Scroll the shelf one row (Maya: the shelf's scroll bar / the mouse wheel over the icons)"""
    bl_idname = "allset.shelf_scroll"
    bl_label = "Scroll Shelf"
    bl_options = {'INTERNAL'}

    delta: IntProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if not is_shelf_row(getattr(context, "space_data", None)) or context.region is None \
                or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}        # the items sit first in "Image": any other image editor zooms / samples
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and (event.ctrl or event.shift or event.alt):
            return {'PASS_THROUGH'}
        return self.execute(context)

    def execute(self, context):
        if context.region is None:
            return {'CANCELLED'}
        scroll_shelf(context, self.delta)
        return {'FINISHED'}


SLOTS = 64   # more than the largest factory shelf (Poly Modeling, 37 buttons)


class ALLSET_GGT_shelf(bpy.types.GizmoGroup):
    bl_idname = "ALLSET_GGT_shelf"
    bl_label = "Maya Shelf"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        return is_shelf_row(context.space_data)

    def setup(self, context):
        for slot in range(SLOTS):
            gz = self.gizmos.new(ALLSET_GT_shelf_icon.bl_idname)
            gz.slot = slot
            gz.target_set_operator(ALLSET_OT_shelf_slot.bl_idname).slot = slot
        for slot in range(TAB_SLOTS):
            gz = self.gizmos.new(ALLSET_GT_shelf_tab.bl_idname)
            gz.slot = slot
            gz.target_set_operator(ALLSET_OT_shelf_tab.bl_idname).slot = slot
        for slot, delta in ((0, -1), (1, 1)):          # the scroll bar's arrows
            gz = self.gizmos.new(ALLSET_GT_shelf_scroll.bl_idname)
            gz.slot = slot
            gz.target_set_operator(ALLSET_OT_shelf_scroll.bl_idname).delta = delta


def _draw_image_header(self, context):
    if is_strip(context.space_data):
        from .status_line import draw_status_line
        return draw_status_line(self.layout, context)
    if is_shelf_row(context.space_data):
        return draw_shelf_tabs(self.layout, context)
    from .editor_chrome import draw_uv_header   # Maya UV Editor menu bar
    if draw_uv_header(self, context):
        return None
    from .render_view import draw_header   # Render View Keep / Remove Image: first, like Maya's
    draw_header(self.layout, context)       # toolbar, so a small render window doesn't clip them
    return own_draw.original("IMAGE_HT_header", _draw_image_header)(self, context)


def _draw_image_tool_header(self, context):
    if is_strip(context.space_data):
        return draw_shelf(self.layout, context)
    from .editor_chrome import draw_uv_tool_header   # Maya UV Editor icon row
    if draw_uv_tool_header(self, context):
        return None
    return own_draw.original("IMAGE_HT_tool_header", _draw_image_tool_header)(self, context)


def patch_image_headers():
    """Blender's own Image Editor header draws only: others' appended items keep drawing."""
    own_draw.swap("IMAGE_HT_header", _draw_image_header)
    own_draw.swap("IMAGE_HT_tool_header", _draw_image_tool_header)


def unpatch_image_headers():
    own_draw.restore("IMAGE_HT_header", _draw_image_header)
    own_draw.restore("IMAGE_HT_tool_header", _draw_image_tool_header)


classes = (ALLSET_OT_shelf_button, ALLSET_OT_shelf_select, ALLSET_OT_shelf_step,
           ALLSET_OT_shelf_new, ALLSET_OT_shelf_delete, ALLSET_OT_shelf_add_button,
           ALLSET_OT_shelf_edit_button, ALLSET_OT_shelf_remove_button,
           ALLSET_MT_shelf_add_action, ALLSET_OT_shelf_add_action, ALLSET_OT_shelf_add_last_command,
           ALLSET_OT_shelf_strip_toggle, ALLSET_MT_shelf_tabs, ALLSET_MT_shelf_settings,
           ALLSET_OT_shelf_slot, ALLSET_GT_shelf_icon, ALLSET_GT_shelf_tab, ALLSET_OT_shelf_tab,
           ALLSET_GT_shelf_scroll, ALLSET_OT_shelf_scroll, ALLSET_GGT_shelf)


_handle = []


def settle_rows():
    """Shelf rows of files made by older versions: switch the image navigation gizmo off (it sat, undrawn, under the
    scroll bar and took its clicks); a strip or shelf row an older shelf UV Editor button switched to the UV Editor
    goes back to showing the strip. Run from a timer / load_post, never from drawing."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            space = area.spaces.active
            if area.type != 'IMAGE_EDITOR' or not is_kit_row(space):
                continue
            if space.mode != 'VIEW':
                space.mode = 'VIEW'
                area.tag_redraw()
            if is_shelf_row(space) and space.show_gizmo_navigate:
                space.show_gizmo_navigate = False


def _settle_later():
    try:
        settle_rows()
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    return None


@bpy.app.handlers.persistent
def _on_load(_dummy):
    if not bpy.app.timers.is_registered(_settle_later):
        bpy.app.timers.register(_settle_later, first_interval=0.1)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    patch_image_headers()
    _handle.append((bpy.types.SpaceImageEditor.draw_handler_add(draw_row, (), 'WINDOW', 'POST_PIXEL'), 'WINDOW'))
    _handle.append((bpy.types.SpaceImageEditor.draw_handler_add(draw_tab_row, (), 'HEADER', 'POST_PIXEL'),
                    'HEADER'))
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.timers.register(_settle_later, first_interval=0.1)


def unregister():
    if bpy.app.timers.is_registered(_deferred_redraw):
        bpy.app.timers.unregister(_deferred_redraw)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if bpy.app.timers.is_registered(_settle_later):
        bpy.app.timers.unregister(_settle_later)
    while _handle:
        bpy.types.SpaceImageEditor.draw_handler_remove(*_handle.pop())
    shelf_icons.clear()
    _SHELF_BATCHES.clear()
    _SHELF_SHADERS.clear()
    _factory_cache.clear()
    _hover.clear()
    _tab_rects.clear()
    _gear_tex.clear()
    _last_click.clear()
    _by_action.clear()
    _row.clear()
    unpatch_image_headers()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    _user.clear()
