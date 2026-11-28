# SPDX-License-Identifier: GPL-3.0-or-later
"""Rows of the kit Hotkey Editor (Issue #121): Maya's standard hotkeys + what the kit does with each, then Maya's
menu item commands without a hotkey (#530, ``command_rows``).

Pure Python (no bpy): ``build_rows`` joins ``hotkey_data.HOTKEYS`` (Maya's standard
hotkeys) with ``mapping.ENTRIES`` (status IC / KIT / STEP / NO, the expected Blender binding ``check``
and the note) and adds ``hotkey_data.COMMANDS`` (the main menus' commands); ``search`` filters them like Maya's Hotkey Editor (Search by Name / by Hotkey, category); ``conflicts``
finds items that already use an event. The live side (``keyconfigs.user`` items) is ``ui/hotkey_editor.py``.
"""

from . import hotkey_data, hotkey_kit, mapping

STATUS_TEXT = {"KIT": "Kit", "IC": "Blender (IC)", "STEP": "Planned", "NO": "Not in Blender", "MAC": "macOS only",
               None: "Unreviewed"}
MODIFIERS = ("ctrl", "alt", "shift", "oskey")
_MOD_TEXT = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "oskey": "Cmd"}
_MOD_WORDS = {"ctrl": "ctrl", "control": "ctrl", "ctl": "ctrl", "alt": "alt", "option": "alt", "shift": "shift",
              "sht": "shift", "cmd": "oskey", "oskey": "oskey", "command": "oskey"}
# Blender event type -> key text (Maya / Qt names); letters and F keys print as they are
_KEY_TEXT = {"SPACE": "Space", "UP_ARROW": "Up", "DOWN_ARROW": "Down", "LEFT_ARROW": "Left", "RIGHT_ARROW": "Right",
             "PAGE_UP": "PgUp", "PAGE_DOWN": "PgDown", "HOME": "Home", "END": "End", "INSERT": "Ins", "RET": "Return",
             "ESC": "Esc", "BACK_SPACE": "Backspace", "DEL": "Del", "TAB": "Tab", "MINUS": "-", "EQUAL": "=",
             "COMMA": ",", "PERIOD": ".", "SLASH": "/", "SEMI_COLON": ";", "QUOTE": "'", "LEFT_BRACKET": "[",
             "RIGHT_BRACKET": "]", "BACK_SLASH": "\\", "ACCENT_GRAVE": "`", "NUMPAD_ENTER": "Num Enter",
             "LEFTMOUSE": "LMB", "MIDDLEMOUSE": "MMB", "RIGHTMOUSE": "RMB", "WHEELUPMOUSE": "Wheel Up",
             "WHEELDOWNMOUSE": "Wheel Down"}
_KEY_TEXT.update({d: str(i) for i, d in enumerate(mapping._DIGITS)})
_KEY_TEXT.update({f"NUMPAD_{i}": f"Num {i}" for i in range(10)})
# Keys of their own on some keyboards: "<" (German / Nordic layouts, the key left of Z), "+", the Menu key. Typed in
# Search by Hotkey, "<" and "+" stay Maya's keys (Shift + comma, Shift + =), so they are not in _TEXT_KEY.
_OWN_KEY_TEXT = {"GRLESS": "<", "PLUS": "+", "APP": "Menu"}
_KEY_TEXT.update(_OWN_KEY_TEXT)
# Event types a Hotkey Editor key capture accepts: every keyboard key Blender has (mouse buttons cancel, modifier
# keys are modifiers)
KEYBOARD = frozenset([chr(c) for c in range(ord("A"), ord("Z") + 1)] + list(mapping._DIGITS)
                     + [f"F{i}" for i in range(1, 25)] + [f"NUMPAD_{i}" for i in range(10)]
                     + [k for k in _KEY_TEXT if not k.endswith("MOUSE")]
                     + ["NUMPAD_PERIOD", "NUMPAD_SLASH", "NUMPAD_ASTERIX", "NUMPAD_MINUS", "NUMPAD_PLUS", "PAUSE",
                        "LINE_FEED", "MEDIA_PLAY", "MEDIA_STOP", "MEDIA_FIRST", "MEDIA_LAST"])
_TEXT_KEY = {v.lower(): k for k, v in _KEY_TEXT.items() if k not in _OWN_KEY_TEXT}
_TEXT_KEY.update({"pageup": "PAGE_UP", "pagedown": "PAGE_DOWN", "page_up": "PAGE_UP", "page_down": "PAGE_DOWN",
                  "enter": "RET", "return": "RET", "delete": "DEL", "insert": "INSERT", "escape": "ESC",
                  "backspace": "BACK_SPACE", "space": "SPACE"})


def key_text(etype):
    """Maya-style text of a Blender event type: 'ONE' -> '1', 'LEFT_BRACKET' -> '[', 'F8' -> 'F8'."""
    if etype in _KEY_TEXT:
        return _KEY_TEXT[etype]
    return etype if len(etype) <= 3 else etype.replace("_", " ").title()


def event_text(ev):
    """'Ctrl+Shift+F6' for an event dict ({"type", "ctrl", "alt", "shift", "oskey"}), Qt modifier order."""
    parts = [_MOD_TEXT[m] for m in MODIFIERS if ev.get(m)]
    return "+".join(parts + [key_text(ev["type"])])


def event_key(ev):
    """Comparable (type, ctrl, alt, shift, oskey) of an event dict."""
    return (ev["type"],) + tuple(bool(ev.get(m)) for m in MODIFIERS)


def parse_hotkey(text):
    """An event dict for a typed hotkey ('ctrl+z', 'Shift+Q', 'f8', 'alt+['), else None."""
    parts = [p.strip() for p in text.replace(" ", "").split("+")]
    if text.strip().endswith("+") and len(text.strip()) > 1:     # "ctrl++" = Ctrl and the + key
        parts = [p for p in parts if p] + ["+"]
    if not parts or not parts[-1]:
        return None
    *mods, key = parts
    ev = {}
    for m in mods:
        name = _MOD_WORDS.get(m.lower())
        if name is None:
            return None
        ev[name] = True
    low = key.lower()
    if low in _TEXT_KEY:
        etype = _TEXT_KEY[low]
    elif len(key) > 1 and low[0] == "f" and low[1:].isdigit():
        etype = key.upper()
    else:
        maya_key = key.lower() if len(key) == 1 and key.isalpha() else key
        try:
            maya = mapping.maya_event({"key": maya_key, "modifiers": []})
        except KeyError:
            return None
        etype = maya["type"]
        if maya.get("shift"):
            ev["shift"] = True
    ev["type"] = etype
    return ev


def _hotkey(raw):
    """Maya-hotkey-shaped dict of one ``hotkey_data`` tuple (what ``mapping`` reads)."""
    d = dict(zip(hotkey_data.FIELDS, raw))
    press = {}
    if d["command"]:
        press["runTimeCommand"] = d["command"]
    elif d["name_command"]:
        press["nameCommand"] = d["name_command"]
    return {"key": d["key"], "modifiers": list(d["modifiers"]), "context": d["context"], "line": d["line"],
            "platform": d["platform"], "category": d["category"], "text": d["text"], "press": press,
            "release": {"runTimeCommand": d["release"]} if d["release"] else {}}


def build_rows(platform="windows"):
    """Hotkey Editor rows: every standard Maya hotkey (``platform`` 'windows' leaves out the 68 macOS-only Cmd
    bindings, None keeps all 468), then the menu item commands (``command_rows``). Each row is a dict:

    index, command (runTimeCommand / nameCommand, "" for an explicitly empty binding), release, maya_key (Maya key
    text), event (Blender event dict of the Maya key), context, category (Maya Hotkey Editor category path, "" if
    none), status (KIT / IC / STEP / NO / MAC / None), status_text, check ((keymap, idname, props) or None), step,
    note, line (row number in Maya's standard hotkey list), editable (the kit binds it: IC / KIT with a check),
    number / label (see ``_number``)."""
    rows = []
    for i, raw in enumerate(hotkey_data.HOTKEYS):
        hk = _hotkey(raw)
        if platform == "windows" and hk["platform"] == "mac-only":
            continue
        entry = mapping.entry_for(hk)
        if hk["platform"] == "mac-only":
            status, check, step, note = "MAC", None, None, "Cmd key binding (macOS)"
        elif entry is None:
            status, check, step, note = None, None, None, ""
        else:
            status, check, step, note = entry["status"], entry["check"], entry["step"], entry["note"]
        command = hk["press"].get("runTimeCommand") or hk["press"].get("nameCommand") or ""
        rows.append({
            "index": i, "command": command, "release": hk["release"].get("runTimeCommand", ""),
            "maya_key": hk["text"], "event": mapping.maya_event(hk), "context": hk["context"],
            "category": hk["category"].replace(".", " > "), "status": status,
            "status_text": STATUS_TEXT.get(status, str(status)), "check": check, "step": step, "note": note,
            "line": hk["line"], "editable": status in ("KIT", "IC") and check is not None,
        })
    _number(rows)
    rows.extend(command_rows(len(hotkey_data.HOTKEYS), {r["command"] for r in rows if r["context"] == "global"}))
    return rows


# Keymap of the keys given to menu item commands: runs in every editor, after the editors' own keys, like a Maya
# global hotkey
COMMAND_KEYMAP = "Window"
COMMAND_OPS = ("allset.menu_item", "allset.menu_option_box", "allset.hotkey_command")
KIT_PREFIX = "kit:"      # path of a kit command row (``hotkey_kit``): not a menu item


def _menu_tables():
    """(mapped label paths, label paths with an option box) of the kit menus."""
    from ..ui import menu_map, menu_tree
    return menu_map.MAP, menu_tree.OPTION_BOXES


def command_rows(start, skip=(), tables=None):
    """Rows of Maya's menu item commands (Maya's Hotkey Editor lists every menu item, with or without a hotkey:
    "Merge", "Merge (Option)", "Merge to Center"), indexes from ``start``; commands in ``skip`` (they have a hotkey row)
    are left out. A command of several menus (Merge Character Sets in Key and Control) is one row, on the first menu
    item the kit runs. No Maya key (``event`` None, ``maya_key`` ""); the kit binds it on demand: a key the user gives
    is a keymap item of ``COMMAND_KEYMAP`` running the menu item (``allset.menu_item``) or its option box
    (``allset.menu_option_box``), so it does exactly what the menu does."""
    mapped, boxes = tables if tables is not None else _menu_tables()
    by_command = {}
    for raw in getattr(hotkey_data, "COMMANDS", ()):
        c = dict(zip(hotkey_data.COMMAND_FIELDS, raw))
        if c["command"] in skip:
            continue
        runs = c["path"] in mapped and (not c["option"] or c["path"] in boxes)
        old = by_command.get(c["command"])
        if old is None or (runs and not old[1]):
            by_command[c["command"]] = (c, runs)
    out = []
    for c, runs in by_command.values():
        if c["option"]:
            check = (COMMAND_KEYMAP, COMMAND_OPS[1], {"item": c["path"]})
        else:
            check = (COMMAND_KEYMAP, COMMAND_OPS[0], {"item": c["path"], "hotkey": True})
        status = "KIT" if runs else "NO"
        out.append({
            "index": start + len(out), "command": c["command"], "release": "", "maya_key": "", "event": None,
            "context": "global", "category": c["category"].replace(".", " > "), "status": status,
            "status_text": STATUS_TEXT[status], "check": check if runs else None, "step": None, "note": "",
            "line": None, "editable": runs, "number": 1, "label": c["label"], "path": c["path"],
            "option": c["option"], "names": (c["label"], c["path"].replace("#", " ")),
        })
    for command, label, category, _idname, _props in hotkey_kit.COMMANDS:
        if command in skip:
            continue
        out.append({
            "index": start + len(out), "command": command, "release": "", "maya_key": "", "event": None,
            "context": "global", "category": category.replace(".", " > "), "status": "KIT",
            "status_text": STATUS_TEXT["KIT"], "check": (COMMAND_KEYMAP, COMMAND_OPS[2], {"item": command}),
            "step": None, "note": "", "line": None, "editable": True, "number": 1, "label": label,
            "path": KIT_PREFIX + command, "option": False, "names": (label,),
        })
    return out


def is_command(row):
    """A menu item command row (no Maya hotkey; the kit key is added when the user gives one)."""
    return bool(row) and row.get("path") is not None


_ORDINAL = {2: "2nd", 3: "3rd"}


def _number(rows):
    """A command with more than one Maya hotkey in one context (Undo: z and Ctrl+Z) has a row per hotkey, each
    changing its own key: ``number`` = which of the command's hotkeys the row is (1, 2, ...), ``label`` = the list
    text, "Undo" then "Undo (2nd hotkey)"."""
    seen = {}
    for r in rows:
        key = (r["command"], r["context"])
        n = seen[key] = seen.get(key, 0) + 1 if r["command"] else 1
        r["number"] = n
        name = r["command"] or "(none)"
        r["label"] = f"{name} ({_ORDINAL.get(n, f'{n}th')} hotkey)" if n > 1 else name


def categories(rows):
    """Category filter values: the top level of each row's Maya category (Menu items / Editors / Other items), then
    each second level ("Menu items > Common"), sorted; rows without one go under "Other"."""
    top, second = set(), set()
    for r in rows:
        parts = r["category"].split(" > ") if r["category"] else ["Other"]
        top.add(parts[0])
        if len(parts) > 1:
            second.add(" > ".join(parts[:2]))
    return sorted(top) + sorted(second)


def in_category(row, category):
    if not category or category == "ALL":
        return True
    cat = row["category"] or "Other"
    return cat == category or cat.startswith(category + " > ")


def _squash(text):
    return "".join(ch for ch in text.lower() if ch.isalnum())


def matches(row, text, by="NAME", live_events=(), names=()):
    """Maya's Hotkey Editor search: by NAME = the command name or one of ``names`` (the kit command's own name,
    "Last Tool" for NonSacredTool) contains the text (case, spaces and punctuation ignored: "select toggle" finds
    SelectToggleMode); by HOTKEY = the Maya key or one of ``live_events`` (the kit's current events of the row) is
    that hotkey ("ctrl+z", "Shift+Q", "F8")."""
    if not text.strip():
        return True
    if by == "HOTKEY":
        ev = parse_hotkey(text)
        if ev is None:
            return bool(row["maya_key"]) and _squash(text) == _squash(row["maya_key"])
        want = event_key(ev)
        return ((row["event"] is not None and event_key(row["event"]) == want)
                or any(event_key(e) == want for e in live_events))
    q = _squash(text)
    return (q in _squash(row["command"]) or bool(row["release"] and q in _squash(row["release"]))
            or any(q in _squash(n) for n in (*names, *row.get("names", ())) if n))


def search(rows, text="", by="NAME", category="ALL", live=None, names=None):
    """Rows matching ``text`` / ``category``; ``live`` = {row index: [event dicts]} for hotkey search, ``names`` =
    {row index: [other names]} for name search."""
    live, names = live or {}, names or {}
    return [r for r in rows if in_category(r, category)
            and matches(r, text, by, live.get(r["index"], ()), names.get(r["index"], ()))]


def same_event(a, b):
    """Two items' events collide: same key + modifiers (``any`` matches any modifiers) and values that overlap
    (equal, or one of them ANY)."""
    if a["type"] != b["type"]:
        return False
    if not (a.get("any") or b.get("any")) and event_key(a) != event_key(b):
        return False
    va, vb = a.get("value", "PRESS"), b.get("value", "PRESS")
    return va == vb or "ANY" in (va, vb)


def conflicts(items, event):
    """[(keymap, idname)] of ``items`` [(keymap, idname, event dict)] whose event collides with ``event``."""
    return [(km, idname) for km, idname, ev in items if same_event(ev, event)]
