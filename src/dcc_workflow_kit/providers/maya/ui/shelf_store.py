# SPDX-License-Identifier: GPL-3.0-or-later
"""What each shelf holds: factory shelves from ``shelf_data`` / ``shelf_map`` in Maya slot order (``all_buttons``,
``factory_buttons``, ``factory_count``), the user's shelves and the buttons added to factory tabs, kept in
``shelves.json`` in the extension's user folder (``user_data``, ``save_user``, ``reload_user``, ``button_record``),
the shown shelf (``current``, ``set_current``) and ``add_menu_item`` (Ctrl+Shift+click). Related: shelf.py."""

import json
import os
import traceback
from pathlib import Path

import bpy

from .. import i18n
from . import shelf_data, shelf_map


USER_PREFIX = "USER:"
DEFAULT_USER = {"shelves": [{"name": "Custom", "buttons": []}]}

_user = {}             # cached shelves.json content


# --- storage -------------------------------------------------------------------------------------

def _package():
    from ....identity import package_id
    return package_id()


def store_path():
    """Return the same shelf file used by the DCC import and export actions."""
    from ....identity import user_path
    return str(Path(user_path()) / "maya_shelves.json")


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


def button_index(shelf_id, label, nth=1):
    """Slot index of the button ``label`` on shelf ``shelf_id`` (the ``nth`` button of that label, the first one by
    default: a shelf can hold several buttons of one label), or None."""
    found = [i for i, lab in button_labels(shelf_id) if lab == label]
    return found[nth - 1] if 1 <= nth <= len(found) else None


def factory_buttons(name):
    """[(index, label, action, icon)] of the mapped buttons of a factory shelf."""
    return [b for b in all_buttons(name) if b[2] is not None]


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
