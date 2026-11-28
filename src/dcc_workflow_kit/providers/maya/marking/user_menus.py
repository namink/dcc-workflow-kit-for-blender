# SPDX-License-Identifier: GPL-3.0-or-later
"""User-edited marking menus: the data behind the Marking Menu Editor (marking/menu_editor.py).

Maya's Marking Menu Editor (Windows > Settings/Preferences > Marking Menu Editor) edits the factory marking menus
(Restore Default puts one back) and makes new ones that a hotkey opens: hold the key, press LMB, drag and release.
Maya keeps them as files in the user's prefs; here one JSON file in the extension's user folder (``store_path``,
next to ``shelves.json``, so it survives kit updates) holds:

- ``menus``: kit menus the user changed, {menu name: tree}. A changed kit menu is stored whole, but its untouched
  entries are references to the factory entry (type ``"factory"``), so the kit's own later fixes still reach them.
  Deleting the key = Maya's "Restore Default".
- ``custom``: the user's own marking menus, {name: tree + ``label`` + ``hotkey``}.

tree = ``{"radial": {pos: entry}, "items": [entry | "-"], "options": [labels with an option box]}``
entry = ``{"label": str, "type": T, ...}`` with T:

- ``"op"``: a Blender operator, ``op`` id + ``props``;
- ``"item"``: a Maya main menu item, ``path`` ("Edit Mesh/Bevel"; runs it like the menu does);
- ``"python"``: ``code`` run like a shelf button / the Command Line (``maya.cmds`` look-alike available);
- ``"shelf"``: a shelf button, ``shelf`` id + ``button`` label (Maya: a shelf button dragged into the editor), run
  like a click on it; found by label, so it follows the shelf's edits; ``nth`` (2, 3, ...) picks a later button of
  the same label on that shelf (absent = the first);
- ``"sub"``: a submenu, ``radial`` / ``items`` / ``options`` like a tree;
- ``"kit"``: any kit action value (``ui/menu_map.py`` forms) as JSON, ``action``;
- ``"factory"``: an entry of a kit menu (``menu`` + ``path`` + ``factory_label``), kept as the kit defines it
  (submenus included). Found by path, else by its factory label in the same submenu (the kit moved it), else greyed.
  While its ``label`` is the factory label, the kit's current label is shown (a kit rename reaches it too).

Paths: "/"-joined steps, a radial position ("N" … "NW") or a list index ("#3"); "" = the menu itself.

``apply`` puts the result into ``menus.MENUS``: kit menus are replaced by rebuilt copies, the factory objects
(``menus.FACTORY``) are never changed (they are shared between menus and read by tests). Kept free of ``bpy`` except
``store_path``.
"""

import copy
import json
import os
import re

from . import menus as mm

VERSION = 1
FILE_NAME = "marking_menus.json"
CUSTOM_PREFIX = "USER_"
PYTHON_OP = "allset.mm_python"
SHELF_OP = "allset.mm_shelf_button"
TYPES = ("op", "item", "python", "shelf", "sub", "kit", "factory")
MODIFIERS = ("ctrl", "alt", "shift", "oskey")
_NAME = re.compile(r"[A-Za-z0-9_]+")
_OP = re.compile(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*")
_KIT_KINDS = ("v3d", "tool", "menu", "pie", "prop", "item")

FACTORY = mm.FACTORY      # the kit's own menus (menus.MENUS before any user edit)

_data = {}          # the loaded / edited document (see module doc); filled by load()


# --- file -------------------------------------------------------------------------------------------------------

def _package():
    from ....identity import package_id
    return package_id()


def store_path():
    """``marking_menus.json`` in the extension's user folder (like ``ui/shelf_store.store_path``; the legacy add-on build:
    a folder inside the add-on's own folder — nothing is written to the user's Blender config)."""
    import bpy
    try:
        base = bpy.utils.extension_path_user(_package(), create=True)
    except (ValueError, AttributeError):
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_data")
        os.makedirs(base, exist_ok=True)
    return os.path.join(base, FILE_NAME)


def empty():
    return {"version": VERSION, "menus": {}, "custom": {}}


def normalized(data):
    """A well-formed document from whatever was read (unknown keys dropped, bad entries skipped)."""
    out = empty()
    if not isinstance(data, dict):
        return out
    menus = data.get("menus")
    if isinstance(menus, dict):
        out["menus"] = {k: _tree(v) for k, v in menus.items() if k in FACTORY and isinstance(v, dict)}
    custom = data.get("custom")
    if isinstance(custom, dict):
        for name, src in custom.items():
            # the name is part of keymap binding names: a plain identifier, never a kit menu's
            if not isinstance(src, dict) or name in FACTORY or not _NAME.fullmatch(str(name)):
                continue
            tree = _tree(src)
            tree["label"] = str(src.get("label") or name)
            tree["hotkey"] = _hotkey(src.get("hotkey"))
            out["custom"][str(name)] = tree
    return out


def _tree(src):
    radial = src.get("radial") if isinstance(src.get("radial"), dict) else {}
    items = src.get("items") if isinstance(src.get("items"), list) else []
    options = src.get("options") if isinstance(src.get("options"), list) else []
    out = {"radial": {}, "items": [], "options": [o for o in options if isinstance(o, str)]}
    for pos in mm.RADIALS:
        e = _entry(radial.get(pos))
        if e is not None:
            out["radial"][pos] = e
    for e in items:
        e = e if e == mm.DIVIDER else _entry(e)
        if e is not None:
            out["items"].append(e)
    return out


def _entry(e):
    if not isinstance(e, dict) or e.get("type") not in TYPES:
        return None
    out = {k: v for k, v in e.items() if k not in ("radial", "items", "options")}
    out["label"] = str(e.get("label", ""))
    if e["type"] == "sub":
        out.update(_tree(e))
    return out


def _hotkey(h):
    if not isinstance(h, dict) or not h.get("key"):
        return None
    return {"key": str(h["key"]), **{m: bool(h.get(m)) for m in MODIFIERS}}


def load(path=None):
    """Read the file into the module document (missing / broken file: nothing edited)."""
    path = path or store_path()
    data = None
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as ex:     # the kit's menus then; the file stays until the next edit
            print(f"Maya Workflow Kit: marking menus file not read ({path}): {ex}")
    _data.clear()
    _data.update(normalized(data))
    return _data


def save(path=None):
    """Write the document (through a temporary file, so a crash never leaves half a file)."""
    path = path or store_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(document(), fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def document():
    if not _data:
        _data.update(empty())
    return _data


# --- paths ------------------------------------------------------------------------------------------------------

def _steps(path):
    return [s for s in path.split("/") if s] if path else []


def _index(step):
    """The list index of a "#3" step, else None."""
    if step.startswith("#") and step[1:].isdigit():
        return int(step[1:])
    return None


def _join(parent, step):
    return f"{parent}/{step}" if parent else step


def child(sub, step):
    """(label, action | entry) at one step of ``sub`` (a Sub or a tree dict), or None."""
    is_sub = isinstance(sub, mm.Sub)
    radial = sub.radial if is_sub else sub.get("radial", {})
    items = sub.items if is_sub else sub.get("items", [])
    i = _index(step)
    if i is not None:
        if i >= len(items) or items[i] == mm.DIVIDER:
            return None
        e = items[i]
    elif step in mm.RADIALS:
        e = radial.get(step)
        if e is None:
            return None
    else:
        return None
    return e if is_sub else (e.get("label", ""), e)


def factory_entry(menu, path):
    """(label, action) of the factory entry at ``path`` in kit menu ``menu``, or None."""
    sub = FACTORY.get(menu)
    found = None
    for step in _steps(path):
        if not isinstance(sub, mm.Sub):
            return None
        found = child(sub, step)
        if found is None:
            return None
        sub = found[1]
    return found


def _find_ref(e):
    """The factory (label, action) a "factory" entry points at: by path when the label still matches, else by label
    in the same submenu (the kit moved it), else by path (the kit renamed it), else None (greyed)."""
    menu, path = e.get("menu", ""), e.get("path", "")
    want = e.get("factory_label", e.get("label", ""))
    found = factory_entry(menu, path)
    if found is not None and found[0] == want:
        return found
    steps = _steps(path)
    parent = FACTORY.get(menu)
    for step in steps[:-1]:
        nxt = child(parent, step) if isinstance(parent, mm.Sub) else None
        parent = nxt[1] if nxt else None
    if isinstance(parent, mm.Sub):
        for lab, act in list(parent.radial.values()) + [x for x in parent.items if x != mm.DIVIDER]:
            if lab == want:
                return (lab, act)
    return found


# --- building menus from the document ---------------------------------------------------------------------------

def _tuple(value):
    if isinstance(value, list):
        return tuple(_tuple(v) for v in value)
    if isinstance(value, dict):
        return {k: _tuple(v) for k, v in value.items()}
    return value


def action_from_json(a):
    """A kit action value from its JSON form ("op.id" | [kind, ...]); None when it isn't one."""
    if isinstance(a, str):
        return a if _OP.fullmatch(a) else None
    if not isinstance(a, list) or not a or not isinstance(a[0], str):
        return None
    if a[0] not in _KIT_KINDS and not (_OP.fullmatch(a[0]) and len(a) == 2 and isinstance(a[1], dict)):
        return None
    # dict props stay dicts (menu_map.normalize copies them); lists inside become tuples like the kit's own values
    return tuple(v if isinstance(v, dict) else _tuple(v) for v in a)


def action_to_json(action):
    """The JSON form of a kit action value (not a Sub)."""
    if isinstance(action, tuple):
        return [action_to_json(v) for v in action]
    if isinstance(action, dict):
        return {k: action_to_json(v) for k, v in action.items()}
    if isinstance(action, (set, frozenset)):
        return sorted(action)
    return action


def ref(menu, path, label=None):
    """A "factory" entry pointing at kit menu ``menu``'s entry at ``path``."""
    found = factory_entry(menu, path)
    flabel = found[0] if found else (label or "")
    return {"label": label if label is not None else flabel, "type": "factory", "menu": menu, "path": path,
            "factory_label": flabel}


def factory_tree(menu, path=""):
    """The tree of kit menu ``menu`` (or of its submenu at ``path``) with every entry a factory reference."""
    if path:
        found = factory_entry(menu, path)
        sub = found[1] if found else None
    else:
        sub = FACTORY.get(menu)
    if not isinstance(sub, mm.Sub):
        return {"radial": {}, "items": [], "options": []}
    return {"radial": {pos: ref(menu, _join(path, pos)) for pos in mm.RADIALS if pos in sub.radial},
            "items": [mm.DIVIDER if e == mm.DIVIDER else ref(menu, _join(path, f"#{i}"))
                      for i, e in enumerate(sub.items)],
            "options": sorted(sub.options)}


def is_editable_sub(action):
    """A factory submenu the editor can open (its entries are fixed data, not filled when the menu opens)."""
    return isinstance(action, mm.Sub) and not isinstance(action, mm.NodeList)


def entry_label(e):
    """The label shown for an entry: an untouched factory reference shows the kit's current label."""
    label = e.get("label", "")
    if e.get("type") == "factory" and label == e.get("factory_label", label):
        found = _find_ref(e)
        if found is not None:
            return found[0]
    return label


def entry_action(e):
    """The kit action (menu_map forms or a Sub) of an entry; None = greyed."""
    t = e.get("type")
    if t == "op":
        op = (e.get("op") or "").strip()
        if not _OP.fullmatch(op):
            return None
        props = e.get("props")
        return (op, dict(props)) if isinstance(props, dict) and props else op
    if t == "item":
        return ("item", e["path"]) if isinstance(e.get("path"), str) and e["path"] else None
    if t == "python":
        code = e.get("code")
        return (PYTHON_OP, {"code": code}) if isinstance(code, str) and code.strip() else None
    if t == "shelf":
        shelf, button = e.get("shelf"), e.get("button")
        if isinstance(shelf, str) and isinstance(button, str) and shelf and button:
            nth = e.get("nth")
            if isinstance(nth, int) and not isinstance(nth, bool) and nth > 1:
                return (SHELF_OP, {"shelf": shelf, "button": button, "nth": nth})
            return (SHELF_OP, {"shelf": shelf, "button": button})
        return None
    if t == "kit":
        return action_from_json(e.get("action"))
    if t == "factory":
        found = _find_ref(e)
        return found[1] if found else None
    if t == "sub":
        return build_sub(e)
    return None


def build_sub(tree, cls=mm.Sub, **kw):
    radial = {}
    options = set(tree.get("options", ()))
    for pos in mm.RADIALS:
        e = tree.get("radial", {}).get(pos)
        if e is not None:
            radial[pos] = _built(e, options)
    items = [mm.DIVIDER if e == mm.DIVIDER else _built(e, options) for e in tree.get("items", [])]
    if cls is mm.Sub:
        return mm.Sub(radial, items, options)
    return cls(radial=radial, items=items, options=options, **kw)


def _built(e, options):
    """(label, action) of an entry; the option box follows the shown label."""
    label = entry_label(e)
    if label != e.get("label", "") and e.get("label", "") in options:
        options.add(label)
    return (label, entry_action(e))


def build_menu(name, tree, label=None, source="user"):
    return build_sub(tree, mm.MarkingMenu, name=name, label=label or tree.get("label") or name, source=source)


# --- applying ---------------------------------------------------------------------------------------------------

def apply(data=None):
    """Put the document into ``menus.MENUS``: factory menus first, then the user's changes and custom menus."""
    data = document() if data is None else data
    for name in [n for n in mm.MENUS if n not in FACTORY]:
        del mm.MENUS[name]
    mm.MENUS.update(FACTORY)
    for name, tree in data.get("menus", {}).items():
        if name in FACTORY:
            f = FACTORY[name]
            mm.MENUS[name] = build_menu(name, tree, f.label, f.source)
    for name, tree in data.get("custom", {}).items():
        if name not in FACTORY:
            mm.MENUS[name] = build_menu(name, tree, tree.get("label"))


def reset():
    """The kit's own menus only (unregister): nothing of the document stays in ``menus.MENUS``."""
    apply(empty())


def is_custom(name):
    return name in document()["custom"]


def is_changed(name):
    return name in document()["menus"]


def changed_names():
    """Menus ``apply`` built from the document: changed kit menus, then custom ones."""
    doc = document()
    return [n for n in doc["menus"] if n in FACTORY] + [n for n in doc["custom"] if n not in FACTORY]


def menu_names():
    """Kit menu names in the kit's order, then custom ones by label."""
    custom = document()["custom"]
    return list(FACTORY) + sorted(custom, key=lambda n: custom[n].get("label", n).lower())


def menu_label(name):
    if name in FACTORY:
        return FACTORY[name].label
    return document()["custom"].get(name, {}).get("label", name)


# --- editing (the editor's operators; each returns True / a path when something changed) -----------------------

def tree_of(name, create=False):
    """The editable tree of menu ``name``: a custom menu's, or a kit menu's change (made from the factory menu when
    ``create``; None while the kit menu is unchanged and not ``create``)."""
    doc = document()
    if name in doc["custom"]:
        return doc["custom"][name]
    if name not in FACTORY:
        return None
    if name not in doc["menus"]:
        if not create:
            return None
        doc["menus"][name] = factory_tree(name)
    return doc["menus"][name]


def view_tree(name):
    """The tree shown for ``name`` (a kit menu's factory tree while unchanged)."""
    t = tree_of(name)
    if t is None and name in FACTORY:
        return factory_tree(name)
    return t


def _as_sub(e):
    """A factory reference to an editable kit submenu as a "sub" entry (its own entries references), else None."""
    if not is_editable_sub(entry_action(e)):
        return None
    sub = {"label": e.get("label", ""), "type": "sub", **factory_tree(e["menu"], e["path"])}
    if e.get("factory_label") is not None:
        sub["factory_label"] = e["factory_label"]
    return sub


def container(tree, path, create=False):
    """The tree / "sub" entry at ``path`` (a submenu), or None. With ``create``, a factory submenu on the way is
    turned into an editable "sub" entry in ``tree`` (its own entries still factory references)."""
    node = tree
    for step in _steps(path):
        found = child(node, step) if node is not None else None
        if found is None:
            return None
        e = found[1]
        if e.get("type") == "factory":
            sub = _as_sub(e)
            if sub is None:
                return None
            if create:
                _put(node, step, sub)
            e = sub
        if e.get("type") != "sub":
            return None
        node = e
    return node


def _put(node, step, entry):
    i = _index(step)
    if i is not None:
        node["items"][i] = entry
    else:
        node["radial"][step] = entry


def entry_at(name, path):
    """The entry dict at ``path`` (read-only view), or None."""
    steps = _steps(path)
    if not steps:
        return None
    node = container(view_tree(name), "/".join(steps[:-1]))
    found = child(node, steps[-1]) if node is not None else None
    return found[1] if found else None


def _edit(name, path):
    """(container, last step) to change the entry at ``path`` of menu ``name``; (None, None) when there is none."""
    steps = _steps(path)
    if not steps or (steps[-1] not in mm.RADIALS and _index(steps[-1]) is None):
        return None, None
    tree = tree_of(name, create=True)
    if tree is None:
        return None, None
    node = container(tree, "/".join(steps[:-1]), create=True)
    return (node, steps[-1]) if node is not None else (None, None)


def set_entry(name, path, entry):
    """Put ``entry`` (None = empty the radial slot / remove the list row) at ``path``."""
    node, step = _edit(name, path)
    if node is None:
        return False
    i = _index(step)
    if i is not None:
        if i >= len(node["items"]):
            return False
        old = node["items"][i]
        if entry is None:
            del node["items"][i]
        else:
            node["items"][i] = entry
    else:
        old = node["radial"].get(step)
        if entry is None:
            node["radial"].pop(step, None)
        else:
            node["radial"][step] = entry
    if isinstance(old, dict) and old.get("label") in node.get("options", ()) and not _label_used(node, old["label"]):
        node["options"] = [o for o in node["options"] if o != old["label"]]
    return True


def _label_used(node, label):
    entries = list(node["radial"].values()) + [e for e in node["items"] if e != mm.DIVIDER]
    return any(e.get("label") == label for e in entries)


def update_entry(name, path, /, **fields):
    """Change some fields of the entry at ``path`` (a factory reference keeps its target; ``fields`` may hold a
    ``path`` of its own: a menu item's). A new label keeps the entry's option box (Maya: the option box belongs to the
    item, not to its name)."""
    node, step = _edit(name, path)
    if node is None:
        return False
    found = child(node, step)
    if found is None:
        return False
    e = found[1]
    old = e.get("label", "")
    e.update(fields)
    new = e.get("label", "")
    if new != old and old in node.get("options", ()):
        opts = set(node["options"])
        if not _label_used(node, old):
            opts.discard(old)
        opts.add(new)
        node["options"] = sorted(opts)
    return True


def add_item(name, path, entry, index=None):
    """Add a list row (``entry`` or mm.DIVIDER) to the submenu at ``path``; returns its path or None."""
    tree = tree_of(name, create=True)
    if tree is None:
        return None
    node = container(tree, path, create=True)
    if node is None:
        return None
    items = node["items"]
    index = len(items) if index is None else max(0, min(index, len(items)))
    items.insert(index, entry)
    return _join(path, f"#{index}")


def move_item(name, path, delta):
    """Move the list row at ``path`` up (-1) / down (+1); returns its new path or None."""
    node, step = _edit(name, path)
    i = _index(step) if node is not None else None
    if i is None:
        return None
    j = i + delta
    items = node["items"]
    if not (i < len(items) and 0 <= j < len(items)):
        return None
    items[i], items[j] = items[j], items[i]
    return _join(path.rsplit("/", 1)[0] if "/" in path else "", f"#{j}")


def swap_radial(name, path, other_pos):
    """Swap the radial entry at ``path`` with the one at ``other_pos`` in the same submenu (Maya: drag a slot)."""
    node, step = _edit(name, path)
    if node is None or step not in mm.RADIALS or other_pos not in mm.RADIALS:
        return False
    a, b = node["radial"].get(step), node["radial"].get(other_pos)
    for pos, e in ((step, b), (other_pos, a)):
        if e is None:
            node["radial"].pop(pos, None)
        else:
            node["radial"][pos] = e
    return True


def has_option(name, path):
    steps = _steps(path)
    if not steps:
        return False
    node = container(view_tree(name), "/".join(steps[:-1]))
    found = child(node, steps[-1]) if node is not None else None
    return found is not None and found[0] in node.get("options", ())


def set_option(name, path, on):
    """Give the entry at ``path`` an option box (Maya ``[]``) or remove it."""
    node, step = _edit(name, path)
    if node is None:
        return False
    found = child(node, step)
    if found is None:
        return False
    opts = set(node.get("options", ()))
    (opts.add if on else opts.discard)(found[0])
    node["options"] = sorted(opts)
    return True


def restore(name):
    """Maya's Restore Default for a kit menu."""
    return document()["menus"].pop(name, None) is not None


def new_custom(label, from_menu=None):
    """A new custom menu (empty, or a copy of ``from_menu``, kit or custom); returns its name."""
    doc = document()
    base = CUSTOM_PREFIX + (re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").upper() or "MENU")
    name, n = base, 1
    while name in doc["custom"] or name in FACTORY:
        n += 1
        name = f"{base}_{n}"
    if from_menu in FACTORY:
        tree = copy.deepcopy(doc["menus"].get(from_menu) or factory_tree(from_menu))
    elif from_menu in doc["custom"]:
        tree = copy.deepcopy(doc["custom"][from_menu])
    else:
        tree = {"radial": {}, "items": [], "options": []}
    tree["label"] = label
    tree["hotkey"] = None
    doc["custom"][name] = tree
    return name


def delete_custom(name):
    return document()["custom"].pop(name, None) is not None


def rename_custom(name, label):
    t = document()["custom"].get(name)
    if t is None or not label.strip():
        return False
    t["label"] = label.strip()
    return True


def set_hotkey(name, hotkey):
    """Bind custom menu ``name`` to ``hotkey`` ({"key", "ctrl", "alt", "shift", "oskey"}; None = no hotkey). The key
    is taken from any other custom menu that had it (Maya: one command per hotkey)."""
    custom = document()["custom"]
    t = custom.get(name)
    if t is None:
        return False
    t["hotkey"] = _hotkey(hotkey)
    if t["hotkey"] is not None:
        for other, ot in custom.items():
            if other != name and ot.get("hotkey") == t["hotkey"]:
                ot["hotkey"] = None
    return True


def hotkeys():
    """[(menu name, hotkey dict)] of the custom menus with a hotkey."""
    return [(n, t["hotkey"]) for n, t in document()["custom"].items() if t.get("hotkey")]


def describe(entry):
    """One line for the editor: what the entry runs."""
    if entry is None:
        return ""
    t = entry.get("type")
    if t == "op":
        props = entry.get("props") or {}
        return f"{entry.get('op', '')}" + (f"({', '.join(f'{k}={v!r}' for k, v in props.items())})" if props else "")
    if t == "item":
        return f"Menu item: {entry.get('path', '')}"
    if t == "python":
        lines = (entry.get("code") or "").strip().splitlines()
        return "Python: " + (lines[0] + (" …" if len(lines) > 1 else "") if lines else "")
    if t == "shelf":
        return f"Shelf button: {shelf_text(entry.get('shelf', ''))} / {entry.get('button', '')}{nth_text(entry)}"
    if t == "sub":
        return "Submenu"
    if t == "kit":
        act = action_from_json(entry.get("action"))
        return f"Kit: {_action_text(act)}" if act is not None else "Kit: (not a kit action)"
    if t == "factory":
        act = entry_action(entry)
        if act is None:
            return "Kit default (not found in this version)"
        if isinstance(act, mm.NodeList):
            return "Kit submenu (filled when the menu opens)"
        if isinstance(act, mm.Sub):
            return "Kit submenu"
        return f"Kit default: {_action_text(act)}"
    return ""


def nth_text(entry):
    """" (2)" for the second button of one label on a shelf (the Shelf Button field and list text), "" for the first."""
    nth = entry.get("nth")
    return f" ({nth})" if isinstance(nth, int) and not isinstance(nth, bool) and nth > 1 else ""


def shelf_text(shelf_id):
    """A shelf's tab name from its id (a user shelf's id has a "USER:" prefix)."""
    return shelf_id.split(":", 1)[1] if shelf_id.startswith("USER:") else shelf_id


def _action_text(act):
    if isinstance(act, str):
        return act
    if isinstance(act, tuple) and act:
        if act[0] == "item":
            return f"menu item {act[1]}"
        if act[0] == "tool":
            return f"tool {act[1]}"
        if act[0] in ("menu", "pie"):
            return f"{act[0]} {act[1]}"
        if act[0] == "v3d":
            return act[1]
        if act[0] == "prop":
            return f"toggle {act[1]}"
        if act[0] == PYTHON_OP:
            return "Python"
        if act[0] == SHELF_OP:
            return f"shelf button {act[1]['button']}"
        return act[0]
    return repr(act)
