# SPDX-License-Identifier: GPL-3.0-or-later
"""Whether a window moved or changed size since a draw callback last drew (``moved``), and what that draw kept for
such a redraw (``keep`` / ``kept``).

While a window is dragged or resized, Blender redraws every region of every window at each step. A region whose own
size stayed the same shows what it showed before, so a draw that finds something in its drawn pixels (a
framebuffer read waits for the GPU to finish) or works out its shapes, colours and texts can use what it had at its
previous draw instead. Once the windows stand still, every area redraws once more in full (``_settle``), so a
change that came while a window moved (a timer, a script) shows as soon as the drag ends.
"""

import time

import bpy

_seen = {}      # caller key -> (the windows' rects, time) at that caller's previous draw
_kept = {}      # caller key -> (signature, value) given to ``keep`` at that caller's last full draw
SEEN_MAX = 256  # keys are region pointers: closed regions' entries go when there are this many
RECENT = 0.5    # s: a draw longer ago than this is no "previous step" of a drag (a window shown again, restored)
SETTLE = 0.1    # s between the checks for windows that stand still again


def rects():
    """(x, y, width, height) of every open window."""
    try:
        return tuple((w.x, w.y, w.width, w.height) for w in bpy.context.window_manager.windows)
    except (AttributeError, ReferenceError):
        return None


def _look(key):
    """The windows' rects now, the time and what ``key``'s previous call saw ((rects, time) or None)."""
    now = rects()
    t = time.monotonic()
    last = _seen.get(key)
    if len(_seen) >= SEEN_MAX and last is None:
        _seen.clear()
    _seen[key] = (now, t)
    return now, t, last


def moved(key):
    """True when a window moved, changed size, opened or closed since the previous call with ``key``."""
    now, _t, last = _look(key)
    return now is not None and last is not None and last[0] != now


def _playing():
    try:
        screen = bpy.context.screen
        if screen is not None:
            return screen.is_animation_playing
        return any(w.screen.is_animation_playing for w in bpy.context.window_manager.windows)
    except (AttributeError, ReferenceError):
        return False


def kept(key, sig):
    """The value ``keep(key, sig, value)`` stored at ``key``'s previous draw, when this draw only follows a window
    move or resize: a window's rect changed since that draw a moment ago (none opened or closed), ``sig`` (the
    region's size, UI scale and whatever else the caller draws from that could differ) is the same and no animation
    plays. Else None (draw in full and ``keep`` again). Call it at every draw of ``key``."""
    now, t, last = _look(key)
    if now is None or last is None or last[0] == now or len(last[0]) != len(now) or t - last[1] > RECENT:
        return None             # windows stand still, opened or closed, or that draw was no step of a drag
    got = _kept.get(key)
    if got is None or got[0] != sig or _playing():
        return None
    _settle_later()
    return got[1]


def keep(key, sig, value):
    """What ``key``'s draw worked out for ``sig``, for its redraws while a window moves (``kept``)."""
    if len(_kept) >= SEEN_MAX and key not in _kept:
        _kept.clear()
    _kept[key] = (sig, value)


def drop(key):
    _kept.pop(key, None)


_still = {}


def _settle():
    """Timer: once the windows stood still for a tick, redraw every area in full."""
    now = rects()
    if now != _still.get("rects"):
        _still["rects"] = now
        return SETTLE
    _still.clear()
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except (AttributeError, ReferenceError):
        pass
    return None


def _settle_later():
    if not bpy.app.timers.is_registered(_settle):
        _still["rects"] = rects()
        bpy.app.timers.register(_settle, first_interval=SETTLE)


def forget():
    _seen.clear()
    _kept.clear()
    _still.clear()
    if bpy.app.timers.is_registered(_settle):
        bpy.app.timers.unregister(_settle)
