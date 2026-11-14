# SPDX-License-Identifier: GPL-3.0-or-later
"""Read a hotkey set exported from Maya's Hotkey Editor (a ``.mhk`` file) and plan the kit key changes (#219).

The file is MEL: ``nameCommand`` lines name a command (``-command`` = the runtime command it runs) and ``hotkey`` lines
bind a key (``-keyShortcut`` + ``-ctl`` / ``-alt`` / ``-sht`` / ``-cmd``) to a name command (``-name``; ``-ctxClient``
for an editor's own hotkey context). Only the key bindings are read, nothing in the file is run. A binding changes
the kit key of a Hotkey Editor row with the same command and context; commands the kit doesn't bind are reported.
No bpy here (tests/test_hotkey_import.py).
"""

import re

from . import mapping

_FLAGS = {"-keyShortcut": "key", "-k": "key", "-name": "name", "-n": "name", "-releaseName": "release",
          "-rn": "release", "-ctxClient": "ctx", "-ctc": "ctx", "-command": "command", "-c": "command"}
_MODS = {"-ctl": "ctl", "-ctrlModifier": "ctl", "-alt": "alt", "-altModifier": "alt", "-sht": "sht",
         "-shiftModifier": "sht", "-cmd": "cmd", "-commandModifier": "cmd"}
_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([^\s();"]+)')


def _statements(text):
    """MEL statements (``;``-separated, outside strings), comments dropped."""
    out, cur, quote, i = [], [], False, 0
    while i < len(text):
        ch = text[i]
        if quote:
            cur.append(ch)
            if ch == "\\" and i + 1 < len(text):
                cur.append(text[i + 1])
                i += 1
            elif ch == '"':
                quote = False
        elif ch == '"':
            quote = True
            cur.append(ch)
        elif ch == "/" and text[i:i + 2] == "//":
            j = text.find("\n", i)
            i = len(text) if j < 0 else j
            continue
        elif ch == ";":
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def _tokens(statement):
    return [m.group(1) if m.group(1) is not None else m.group(2) for m in _TOKEN.finditer(statement)]


def parse(text):
    """(bindings, name commands): bindings = [{"key", "modifiers", "name", "release", "ctx"}], name commands =
    {name: runtime command}."""
    bindings, names = [], {}
    for st in _statements(text):
        toks = _tokens(st)
        if not toks:
            continue
        cmd, rest = toks[0], toks[1:]
        if cmd not in ("hotkey", "nameCommand"):
            continue
        vals, mods, i, positional = {}, [], 0, []
        while i < len(rest):
            t = rest[i]
            if t in _MODS:
                mods.append(_MODS[t])
            elif t in _FLAGS and i + 1 < len(rest):
                vals[_FLAGS[t]] = rest[i + 1]
                i += 1
            elif t.startswith("-") and not t[1:2].isdigit():
                if i + 1 < len(rest) and not rest[i + 1].startswith("-"):
                    i += 1      # another flag with a value (-annotation, -sourceType ...)
            else:
                positional.append(t)
            i += 1
        if cmd == "nameCommand":
            if positional and "command" in vals:
                names[positional[-1]] = vals["command"]
        elif "key" in vals:
            bindings.append({"key": vals["key"], "modifiers": mods, "name": vals.get("name"),
                             "release": vals.get("release"), "ctx": vals.get("ctx") or "global"})
    return bindings, names


def _commands(name, names):
    """Command names a binding's name command may appear under in the Hotkey Editor rows."""
    out = {name}
    if name in names:
        out.add(names[name])
    if name.endswith("NameCommand"):
        out.add(name[:-len("NameCommand")])
    return out


def event_of(binding):
    """Blender event dict of a binding's key (KeyError: a key the kit can't read)."""
    return mapping.maya_event({"key": binding["key"], "modifiers": binding["modifiers"]})


def plan(rows, bindings, names, key_of=None):
    """[(row, event)] key changes, plus [(binding, reason)] not applied.

    ``rows`` = hotkey_rows.build_rows(); ``key_of(event)`` = a comparable key (default hotkey_rows-style tuple).
    Bindings of one command and context fill that command's rows: a binding equal to a row's Maya key keeps it, the
    others go to the remaining editable rows in order."""
    if key_of is None:
        def key_of(ev):
            return (ev["type"], bool(ev.get("ctrl")), bool(ev.get("alt")), bool(ev.get("shift")),
                    bool(ev.get("oskey")))
    groups = {}
    skipped = []
    for b in bindings:
        if not b["name"]:
            skipped.append((b, "no command (an emptied key)"))
            continue
        try:
            ev = event_of(b)
        except KeyError:
            skipped.append((b, f"key {b['key']!r} is not read by the kit"))
            continue
        cmds = _commands(b["name"], names)
        groups.setdefault((frozenset(cmds), b["ctx"]), []).append((b, ev))
    changes = []
    for (cmds, ctx), items in groups.items():
        cands = [r for r in rows if r["command"] in cmds and r["context"] == ctx]
        if not cands:
            for b, _ev in items:
                skipped.append((b, "the kit has no hotkey for this command"))
            continue
        wanted = {key_of(ev) for _b, ev in items}
        free = [r for r in cands if r["editable"] and key_of(r["event"]) not in wanted]
        have = {key_of(r["event"]) for r in cands}
        for b, ev in items:
            if key_of(ev) in have:
                continue                       # the Maya key: the kit row already has it
            if not free:
                skipped.append((b, "no kit hotkey left to change for this command"
                                if any(r["editable"] for r in cands) else "the kit binds this command another way"))
                continue
            changes.append((free.pop(0), ev))
    return changes, skipped
