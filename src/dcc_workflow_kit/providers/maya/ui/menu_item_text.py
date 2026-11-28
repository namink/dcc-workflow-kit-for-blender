# SPDX-License-Identifier: GPL-3.0-or-later
"""Menu item texts with Maya's right-aligned hotkey and option-box column: ``item_texts`` (label + hotkey + box,
padded with spaces / hair spaces sized in the menu font), ``font_size`` / ``text_width``. Used by the Maya menus
(``menu_sets``), ``option_click`` and ``maya_dock``; hotkeys from ``menu_hotkeys``.
"""

import bpy

from . import menu_hotkeys
from .menu_tree import BOX_MARK


# --- Maya hotkey column ------------------------------------------------------------------------
# Maya prints an item's hotkey right-aligned (File > New Scene "Ctrl+N",
# Edit Mesh > Bevel "Ctrl+B"), the option box after it. Blender takes no such text for a Python button,
# so the label carries it: label + filler + "Ctrl+N  ❒", the filler sized with the menu font so the tails line
# up on the right.
HAIR = "\u200a"          # a hair space: fine filler steps (plain spaces only if the UI font lacks it)
MIN_GAP = 3              # spaces between the longest label and its tail


def hotkey(path):
    """The Maya hotkey shown beside a menu item ("" without one): ui/menu_hotkeys.py."""
    return menu_hotkeys.HOTKEYS.get(path, "")


def font_size(context=None):
    """The menu text size in px: the UI style's widget points x the effective UI scale (0 in background -> 1)."""
    prefs = (context or bpy.context).preferences
    scale = prefs.system.ui_scale or 1.0
    try:
        points = prefs.ui_styles[0].widget.points
    except (IndexError, AttributeError):
        points = 11
    return points * scale


def text_width(text, size):
    import blf
    blf.size(0, size)
    return blf.dimensions(0, text)[0]


def filler(width, size, space=None, hair=None):
    """Blank text about ``width`` px wide: spaces, then hair spaces for the rest (if the UI font has them)."""
    space = space or (text_width(" ", size) or 1.0)
    if hair is None:
        hair = text_width(HAIR, size)
        if not 0.0 < hair < space:
            hair = 0.0
    n = int(max(width, 0.0) // space)
    hairs = int(round((width - n * space) / hair)) if hair else 0
    return " " * n + HAIR * hairs


def aligned(entries, size=None):
    """[(label, tail)] -> texts with the tails right-aligned on one column (rows without a tail stay as they are)."""
    if not any(tail for _label, tail in entries):
        return [label for label, _tail in entries]
    size = size or font_size()
    space = text_width(" ", size) or 1.0
    hair = text_width(HAIR, size)
    if not 0.0 < hair < space:
        hair = 0.0
    widths = [(text_width(label, size), text_width(tail, size) if tail else 0.0) for label, tail in entries]
    total = max(lw + MIN_GAP * space + tw for (lw, tw), (_l, tail) in zip(widths, entries) if tail)
    out = []
    for (label, tail), (lw, tw) in zip(entries, widths):
        if not tail:
            out.append(label)
            continue
        out.append(label + filler(max(total - lw - tw, space), size, space, hair) + tail)
    return out


def item_texts(rows, size=None):
    """{path: drawn text} for a menu's (path, label, boxed) rows: label + Maya hotkey + option box, aligned. In a
    menu with option boxes a hotkey without a box keeps the box column empty, so every hotkey ends on one line
    (Maya: Increment and Save "Ctrl+Alt+S" under "Ctrl+S" of Save Scene)."""
    size = size or font_size()
    any_box = any(boxed for _p, _l, boxed in rows)
    box_gap = filler(text_width(BOX_MARK, size), size) if any_box else ""
    entries = []
    for path, label, boxed in rows:
        key = hotkey(path)
        if key:
            tail = key + (BOX_MARK if boxed else box_gap)
        else:
            tail = BOX_MARK.strip() if boxed else ""
        entries.append((label, tail))
    return {row[0]: text for row, text in zip(rows, aligned(entries, size))}
