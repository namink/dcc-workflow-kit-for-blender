# SPDX-License-Identifier: GPL-3.0-or-later
"""A click on the option box ❒ of a Maya menu item opens its option window (#82).

Blender runs a menu item's operator with EXEC and tells Python nothing about the popup menu (no region, no rect:
``context.region`` in ``Menu.draw`` is the region the menu was called from, ``Screen`` has no popup
regions, a screenshot taken in ``execute`` already shows the menu closed). Two things are known, though:
- where the click was: a nested ``INVOKE_DEFAULT`` call inside ``execute`` gets the window's latest event, the
  LEFTMOUSE release on the row (``ALLSET_OT_click_point``);
- where a Maya pulldown sits: the kit lays out the top bar itself (every menu button has ``ui_units_x``,
  ``status_line.menu_bar_widths``), Blender opens a pulldown with its left edge on the button's left edge and a
  submenu against its parent's right edge, every row's text starts ``TEXT_UNITS`` from the menu edge and the kit's
  label + hotkey + ❒ texts are right-aligned (``menu_sets.item_texts``), so the ❒ ends at menu left + text start +
  the aligned text width (checked on screenshots at UI scale 1.0 / 1.25, ``tests/test_step183_option_click.py`` +
  ``tests/gui/gui_step183_option_click.py``).
A Maya menu the Space hotbox opens is a popup at the pointer (``wm.call_menu``): Blender puts the pointer at
``POPUP_AT`` of the menu's width (the remembered last row, or the first one, under it) and keeps the menu
``SCREEN_MARGIN`` px inside the window; such a menu is ``POPUP_PAD_UNITS`` wider than its widest text plus a 1 px
border each side, and its rows' texts start 1 px further in than a pulldown's. The hotbox notes the menu and the
pointer x when it opens it (``note_called``), so these menus have their ❒ zone too
(``tests/gui/gui_issue350_hotbox_box.py``).
So the ❒ zone of a row is known for menus opened from the Maya menu bar or the hotbox (and their submenus);
anywhere else (marking menus, the » overflow, editor menu bars, a torn-off menu) the item keeps the press-and-hold /
Shift / Ctrl+click.
"""

import bpy

# In widget units (toolbar_fit.unit)
from .. import compat, i18n
LEAD_UNITS = compat.MENU_BAR_LEAD_UNITS   # top bar region left -> first Maya menu button (4.5 1.48, 5.x 1.25)
TEXT_UNITS = 1.6         # menu edge -> item text (menu padding + icon column)
PAD_SUB_UNITS = 1.6      # widest text -> menu right edge when the menu has submenu rows (arrow column)
PAD_UNITS = 1.28         # ... without submenu rows
ZONE_LEFT_UNITS = 0.5    # the click zone starts this far left of the ❒ glyph (Maya's box is a square cell)
POPUP_AT = 0.8           # a menu called at the pointer: the pointer sits at this share of its width
POPUP_PAD_UNITS = 2.5    # ... its width = widest text + this (+ a 1 px border each side)
POPUP_MIN_UNITS = 9.0    # ... and at least this
SCREEN_MARGIN = 10       # px between a popup and the window's left / right edge (not scaled)

_OPEN = {}    # window pointer -> {top menu label: ("BAR", top bar region x) / ("AT", pointer x) / None (elsewhere)}
_CALLED = {}  # window pointer -> (top menu label, pointer x, region pointer): the menu the hotbox is opening
_CLICK = {}


def _unit(context):
    from .toolbar_fit import unit
    system = context.preferences.system
    return unit(system.ui_scale or 1.0, system.pixel_size)


def note_called(context, label, x):
    """The hotbox opens the Maya menu ``label`` as a popup at window x ``x`` (``wm.call_menu`` from ``context``)."""
    window, region = getattr(context, "window", None), getattr(context, "region", None)
    if window is not None and region is not None:
        _CALLED[window.as_pointer()] = (label, x, region.as_pointer())


def forget_called(context):
    """A menu is called at the pointer from somewhere the kit doesn't know the pointer of (a marking menu item)."""
    window = getattr(context, "window", None)
    if window is not None:
        _CALLED.pop(window.as_pointer(), None)


def note_draw(context, top_label):
    """Called by every top Maya menu's draw: opened from the Maya menu bar of this window, or by the hotbox?"""
    window = getattr(context, "window", None)
    if window is None:
        return
    from . import status_line
    area, region = getattr(context, "area", None), getattr(context, "region", None)
    top = status_line._top_bars.get(window.as_pointer())
    ok = (area is not None and top is not None and region is not None and region.type == 'HEADER'
          and area.as_pointer() == top.as_pointer())
    entry = ("BAR", region.x) if ok else None
    called = _CALLED.get(window.as_pointer())
    if (entry is None and called is not None and called[0] == top_label and region is not None
            and called[2] == region.as_pointer()):
        entry = ("AT", called[1])
    _OPEN.setdefault(window.as_pointer(), {})[top_label] = entry


def _items_of(path):
    """(items, prefix, top label) of the Maya menu at ``path`` ("Create" or "Create/Polygon Primitives")."""
    from . import menu_data, menu_sets
    top = path.split("/")[0]
    entry = next((m for m in menu_data.MENUS.values() if m[0] == top), None)
    if entry is None:
        return None
    items = entry[3]
    if path == top:
        return items, top, top
    try:
        node = menu_sets._find(items, top, path)
    except KeyError:
        return None
    return menu_sets.sub_items(path, node), path, None


def rows(path):
    """[(drawn text, is a submenu row)] of the Maya menu at ``path`` — the texts ``menu_sets._menu_class`` draws."""
    from . import maya_dock, menu_map, menu_sets
    got = _items_of(path)
    if got is None or not got[0]:
        return None
    items, prefix, top_label = got
    kids = menu_sets.menu_rows(items, prefix)       # labels in the interface language
    plain = [(p, it[0], p in menu_sets.OPTION_BOXES) for p, it in kids
             if p is not None and not (menu_sets.sub_items(p, it) and p not in menu_map.MAP)]
    texts = menu_sets.item_texts(plain)
    out = [(maya_dock.TEAR_LINE, False)]
    for p, it in kids:
        if p is None:
            if len(it) > 1 and it[1]:
                out.append((i18n.iface(it[1]), False))   # drawn by Blender, translated
        elif menu_sets.sub_items(p, it) and p not in menu_map.MAP:
            out.append((it[0] + (menu_sets.BOX_MARK if p in menu_sets.OPTION_BOXES else ""), True))
        else:
            out.append((texts[p], False))
    blender = menu_map.BLENDER_MENU.get(top_label) if top_label else None
    if blender:
        out.append((i18n.iface(blender[1]), True))
    return out, texts


def width(path, u, size=None):
    """Menu width in px (``u`` = widget unit): text start + widest text + right padding."""
    from . import menu_sets
    got = rows(path)
    if got is None:
        return None
    size = size or menu_sets.font_size()
    out, _texts = got
    widest = max(menu_sets.text_width(t, size) for t, _sub in out)
    pad = PAD_SUB_UNITS if any(sub for _t, sub in out) else PAD_UNITS
    return int(TEXT_UNITS * u + widest + pad * u)


def popup_width(path, u, size=None):
    """Width in px of the Maya menu at ``path`` opened as a popup at the pointer (its title row included)."""
    from . import menu_sets
    got = rows(path)
    if got is None:
        return None
    size = size or menu_sets.font_size()
    texts = [t for t, _sub in got[0]] + [i18n.iface(path.split("/")[-1])]
    widest = max(menu_sets.text_width(t, size) for t in texts)
    return max(int(widest + POPUP_PAD_UNITS * u), int(POPUP_MIN_UNITS * u)) + 2


def top_left(context, label):
    """Window x of the Maya menu bar button ``label`` (None: not drawn there by the kit's layout this time)."""
    from . import menu_sets, status_line
    window = context.window
    entry = _OPEN.get(window.as_pointer(), {}).get(label)
    if entry is None or entry[0] != "BAR" or status_line.status_line_shown(context) is False:
        return None          # opened elsewhere, or the bar also holds the menu set field (not modelled)
    names, n = status_line.shown_menus(window)
    labels = [getattr(getattr(bpy.types, menu_sets.menu_idname(nm), None), "bl_label", nm) for nm in names]
    if label not in labels[:n] or n < len(names):
        return None          # in the » overflow menu, or the bar is cut (the » button changes the layout)
    widths, _fixed, _more = status_line.menu_bar_widths(context, list(names), False)
    i = labels.index(label)
    return entry[1] + int(LEAD_UNITS * _unit(context)) + sum(widths[:i])


def _top_menu(context, label, u, size):
    """(left, width, text inset) in window px of the top Maya menu ``label`` as it is open now, or None."""
    win_w = context.window.width
    entry = _OPEN.get(context.window.as_pointer(), {}).get(label)
    if entry is not None and entry[0] == "AT":
        w = popup_width(label, u, size)
        if w is None:
            return None
        left = entry[1] - round(POPUP_AT * w)
        return max(SCREEN_MARGIN, min(left, win_w - SCREEN_MARGIN - w)), w, 1
    left = top_left(context, label)
    w = width(label, u, size) if left is not None else None
    if w is None:
        return None
    return min(left, win_w - w), w, 0


def box_zone(context, path):
    """(zone x0, zone x1, menu left, menu right) in window px for the ❒ of menu item ``path``, or None."""
    from . import menu_sets
    parts = path.split("/")
    if len(parts) < 2 or context.window is None:
        return None
    u = _unit(context)
    size = menu_sets.font_size(context)
    got = _top_menu(context, parts[0], u, size)
    if got is None:
        return None
    left, w, inset = got
    win_w = context.window.width
    for k in range(2, len(parts)):          # submenus: against the parent's right edge, else its left
        sub = "/".join(parts[:k])
        sw = width(sub, u, size)
        if sw is None:
            return None
        left = left + w if left + w + sw <= win_w else left - sw
        w, inset = sw, 0
    got = rows("/".join(parts[:-1]))
    if got is None or path not in got[1]:
        return None
    text = got[1][path]
    if not text.endswith(menu_sets.BOX_MARK.strip()):
        return None
    end = left + inset + TEXT_UNITS * u + menu_sets.text_width(text, size)
    glyph = menu_sets.text_width(menu_sets.BOX_MARK.strip(), size)
    return end - glyph - ZONE_LEFT_UNITS * u, left + w, left, left + w


class ALLSET_OT_click_point(bpy.types.Operator):
    """Where the last click went (called with INVOKE from inside an EXEC operator: the window's latest event)"""
    bl_idname = "allset.click_point"
    bl_label = "Click Point"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        _CLICK["at"] = (event.mouse_x, event.mouse_y, event.type)
        return {'FINISHED'}

    def execute(self, context):
        return {'CANCELLED'}


def on_box(context, path):
    """True when the menu item ``path`` was clicked on its ❒ (a menu of the Maya menu bar or the hotbox, left mouse
    button)."""
    if bpy.app.background or getattr(context, "window", None) is None:
        return False
    zone = box_zone(context, path)
    if zone is None:
        return False
    _CLICK.clear()
    try:
        bpy.ops.allset.click_point('INVOKE_DEFAULT')
    except RuntimeError:
        return False
    at = _CLICK.get("at")
    if at is None or at[2] != 'LEFTMOUSE':
        return False
    x0, x1, left, right = zone
    if not left <= at[0] <= right:
        return False         # the click isn't where the model puts the menu: trust nothing, run the command
    return x0 <= at[0] <= x1


classes = (ALLSET_OT_click_point,)
