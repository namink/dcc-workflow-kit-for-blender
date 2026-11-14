# SPDX-License-Identifier: GPL-3.0-or-later
"""Saved settings of the kit's In-View Editor (ui/in_view.py): the drag speed set with the pie in its title and
where the box was dragged to. Both live in the add-on preferences (hidden), so they are kept across sessions.

The pie and moving the box by its title are add-on preferences, off by default. Off, the title shows no pie and
rows drag at full speed, and the box sits at its place beside its manipulator / object; the saved speed and offset
stay, so turning an option back on brings them back.
"""

DEFAULT_SENSITIVITY = 1.0     # full speed: a row drag changes the value by the In-View Editor's own steps


def _preferences():
    try:
        from .. import preferences
        return preferences.get()
    except (ImportError, AttributeError, KeyError, RuntimeError):
        return None


def _option(name):
    try:
        return bool(getattr(_preferences(), name))
    except (AttributeError, TypeError, ReferenceError):
        return False


def pie_shown():
    """The title shows the drag-speed pie (add-on preference, off by default)."""
    return _option("in_view_speed_pie")


def title_moves():
    """Dragging the title moves the box (add-on preference, off by default)."""
    return _option("in_view_title_move")


def get_sensitivity():
    """The pie's fraction, 0..1."""
    prefs = _preferences()
    try:
        return max(0.0, min(1.0, float(prefs.hud_drag_sensitivity)))
    except (AttributeError, TypeError, ValueError):
        return DEFAULT_SENSITIVITY


def set_sensitivity(value):
    value = max(0.0, min(1.0, float(value)))
    prefs = _preferences()
    if prefs is not None:
        try:
            prefs.hud_drag_sensitivity = value
        except (AttributeError, TypeError, RuntimeError):
            pass
    return value


def speed():
    """Multiplier of a row drag's step: 2 % of the step at an empty pie, the full step at a full one; the full step
    while the pie is off."""
    if not pie_shown():
        return 1.0
    return 0.02 + 0.98 * get_sensitivity()


def get_offset():
    """(dx, dy) in px at UI scale 1 the box was dragged by its title from its place beside the manipulator /
    object; (0, 0) when it was never moved or moving it by its title is off."""
    if not title_moves():
        return 0.0, 0.0
    prefs = _preferences()
    try:
        return float(prefs.in_view_offset_x), float(prefs.in_view_offset_y)
    except (AttributeError, TypeError, ValueError):
        return 0.0, 0.0


def set_offset(dx, dy):
    prefs = _preferences()
    if prefs is None:
        return
    try:
        prefs.in_view_offset_x, prefs.in_view_offset_y = float(dx), float(dy)
    except (AttributeError, TypeError, RuntimeError):
        pass
