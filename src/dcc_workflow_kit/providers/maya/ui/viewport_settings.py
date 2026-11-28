# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep Maya panel display settings in the extension's user folder across sessions (the Remember Panel Settings
preference, off by default: ``follow_preference`` starts / stops the 0.5 s sampling timer)."""

import json
import os

import bpy
from bpy.app.handlers import persistent

from .. import settings_io, switch
from . import four_view, range_bar, selection_wire

FILE = "viewport_settings.json"
TICK = 0.5
_data = {}
_seen = {}
_dirty = False


def path():
    if bpy.app.factory_startup or bpy.app.background:
        return None
    try:
        folder = bpy.utils.extension_path_user(__package__.rpartition(".")[0], create=True)
    except (ValueError, AttributeError):
        return None
    return os.path.join(folder, FILE)


def capture(screen, area):
    space = area.spaces.active
    data = four_view.capture(space)
    # Camera positions, lens and clipping belong to the scene, not display preferences.
    data.pop("view")
    data["space"] = {k: getattr(space, k) for k in ("show_gizmo", "show_gizmo_navigate")}
    data["highlight_off"] = selection_wire._off_map(screen).get(str(list(screen.areas).index(area)))
    return data


def apply(screen, area, data):
    if not isinstance(data, dict):
        return
    space = area.spaces.active
    for part in ("shading", "overlay", "space", "shown"):
        values = data.get(part, {})
        if isinstance(values, dict):
            owner = getattr(space, part) if part in {"shading", "overlay"} else space
            four_view._apply_props(owner, values)
    key = str(list(screen.areas).index(area))
    off = selection_wire._off_map(screen)
    if data.get("highlight_off") is None:
        off.pop(key, None)
    else:
        off[key] = bool(data["highlight_off"])
    if off:
        screen[selection_wire.HILITE_OFF] = json.dumps(off)
    elif selection_wire.HILITE_OFF in screen:
        del screen[selection_wire.HILITE_OFF]
    area.tag_redraw()


def panels(window):
    """Stable workspace / panel roles; resizing or folding Four View keeps each panel's choices."""
    ws, screen = window.workspace, window.screen
    if not switch.is_maya_workspace(ws):
        return
    workspace = ws.get(switch.USER_KEY) or switch.template_of(ws) or ws.name
    areas = four_view.panes(screen)
    roles = {a.as_pointer(): role for role, a in four_view.roles(screen).items()}
    for i, area in enumerate(areas):
        role = roles.get(area.as_pointer())
        if role is None:
            role = four_view.state(screen).get("single", "persp") if len(areas) == 1 else f"panel-{i}"
        yield f"{workspace}/{role}", area


def save():
    global _dirty
    target = path()
    if not _dirty or target is None:
        return
    try:
        settings_io._write(target, _data)
        _dirty = False
    except OSError as ex:
        print("Maya Workflow Kit: could not save viewport settings:", ex)


def enabled():
    from .. import preferences
    try:
        return bool(preferences.get().remember_panel_settings)
    except (KeyError, AttributeError):
        return False


def sample():
    global _dirty
    if not _running[0]:
        return
    saved = _data.setdefault("panels", {})
    alive = set()
    for window in bpy.context.window_manager.windows:
        for key, area in panels(window):
            pointer = (window.as_pointer(), area.spaces.active.as_pointer())
            alive.add(pointer)
            previous = _seen.get(pointer)
            if previous is None or previous[0] != key:
                apply(window.screen, area, saved.get(key))
                background = _data.get("background")
                if isinstance(background, dict):
                    four_view._apply_props(area.spaces.active.shading, background)
            current = capture(window.screen, area)
            if previous is None or previous != (key, current):
                saved[key] = current
                _dirty = True
                # Alt+B and Color Settings use one background for every panel / workspace.
                if previous is None or any(current["shading"][k] != previous[1]["shading"][k]
                                           for k in ("background_type", "background_color")):
                    _data["background"] = {k: current["shading"][k]
                                           for k in ("background_type", "background_color")}
                _seen[pointer] = (key, current)
    for pointer in set(_seen) - alive:
        del _seen[pointer]
    # the Range Slider bar widths found by drawing: the next session's first frame starts from them
    bars = {f"{w},{u}": e for (w, u), e in range_bar._settled.items()}
    if _data.get("range_bar") != bars:
        _data["range_bar"] = bars
        _dirty = True
    save()


def _tick():
    try:
        sample()
    except (AttributeError, ReferenceError, RuntimeError) as ex:
        print("Maya Workflow Kit: could not remember viewport settings:", ex)
    return TICK


@persistent
def _before_load(*_args):
    _tick()


@persistent
def _after_load(*_args):
    _seen.clear()


_running = [False]


def register():
    follow_preference()


def follow_preference():
    """Start remembering (read the file, sample every TICK) or stop, as the preference says."""
    if enabled():
        start()
    else:
        stop()


def start():
    global _dirty
    if _running[0]:
        return
    _data.clear()
    _seen.clear()
    _dirty = False
    target = path()
    if target is None:
        return
    _running[0] = True
    data = settings_io._read(target)
    if isinstance(data, dict) and isinstance(data.get("panels"), dict):
        _data.update(data)
    try:
        for key, extra in _data.get("range_bar", {}).items():
            w, u = key.split(",")
            range_bar._settled.setdefault((int(w), float(u)), int(extra))
    except (AttributeError, ValueError, TypeError):     # a hand-edited file: the bar finds its width by drawing
        pass
    bpy.app.handlers.load_pre.append(_before_load)
    bpy.app.handlers.load_post.append(_after_load)
    bpy.app.timers.register(_tick, first_interval=TICK, persistent=True)


def stop():
    if bpy.app.timers.is_registered(_tick):
        _tick()
        bpy.app.timers.unregister(_tick)
    for handlers, fn in ((bpy.app.handlers.load_pre, _before_load), (bpy.app.handlers.load_post, _after_load)):
        if fn in handlers:
            handlers.remove(fn)
    _running[0] = False
    _seen.clear()
    _data.clear()


def unregister():
    stop()
