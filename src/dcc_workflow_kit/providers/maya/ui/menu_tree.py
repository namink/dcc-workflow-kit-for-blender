# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya menu sets and the menu item tree: which menus a set shows (``menus_for_set``), every item's label path
(``iter_items`` / ``children`` / ``sub_items``), menu class names (``menu_idname``, ``editor_menu_idname``),
``OPTION_BOXES`` and the box mark. Structure from ``menu_data`` / ``editor_menu_data``, run-time items from
``menu_map``; the menus themselves are built in ``menu_sets``.
"""

from . import editor_menu_data, menu_data, menu_map

COMMON_SET = "commonMenuSet"
ALWAYS = "(always visible)"
DEFAULT_SET = "modelingMenuSet"

# Menu set dropdown items.
SET_ITEMS = tuple((sid, label, f"Maya {label} menu set")
                  for sid, label, _menus in menu_data.MENU_SETS if sid != COMMON_SET)
# Plugin menus (MASH, Bifrost, Boss) are listed in the sets but have no data: skipped.
_SET_MENUS = {sid: tuple(m for m in menus if m in menu_data.MENUS)
              for sid, _label, menus in menu_data.MENU_SETS}
_ALWAYS_MENUS = tuple(n for n, m in menu_data.MENUS.items() if m[1] == ALWAYS)
# Main menu bar option boxes + the editor menu bars'
OPTION_BOXES = menu_data.OPTION_BOXES | editor_menu_data.OPTION_BOXES | menu_map.EXTRA_OPTION_BOXES


def menu_idname(maya_name):
    return f"ALLSET_MT_{maya_name}"


def menus_for_set(set_id):
    """Maya menu names shown in the menu bar for ``set_id``, left to right."""
    return _SET_MENUS[COMMON_SET] + _SET_MENUS.get(set_id, ()) + _ALWAYS_MENUS


def iter_items(items=None, prefix=""):
    """Yield (label path, item) for every entry below ``items`` (all menus if None)."""
    if items is None:
        for label, _set, _src, its in menu_data.MENUS.values():
            yield from iter_items(its, label)
        for editor, menus in editor_menu_data.EDITORS.items():
            for title, its in menus:
                yield from iter_items(its, f"{editor}/{title}")
        return
    for path, it in children(items, prefix):
        if path is None:
            continue
        yield path, it
        kids = sub_items(path, it)
        if kids:
            yield from iter_items(kids, path)


def sub_items(path, it):
    """Children of a menu entry: Maya's run-time ones (``menu_map.CHILDREN``), else the data's."""
    return menu_map.CHILDREN.get(path) or (it[1] if len(it) > 1 else None)


def children(items, prefix):
    """(path, item) per direct entry; path None for dividers. A label repeated
    among siblings gets "#2", "#3" (Select > Components for polygons, curves,
    surfaces). ``menu_map.EXTRA`` items follow the entry they are attached to; ``menu_map.HIDE`` entries are left
    out (their EXTRA items stay)."""
    seen = {}
    for it in items:
        if it[0] == "-":
            yield None, it
            continue
        n = seen[it[0]] = seen.get(it[0], 0) + 1
        path = f"{prefix}/{it[0]}" + (f"#{n}" if n > 1 else "")
        if path not in menu_map.HIDE:
            yield path, it
        for extra in menu_map.EXTRA.get(path, ()):
            yield (None if extra[0] == "-" else f"{prefix}/{extra[0]}"), extra


def current_set(context=None):
    from .. import preferences
    try:
        return preferences.get(context).menu_set
    except KeyError:  # add-on preferences not registered (disable in progress)
        return DEFAULT_SET


# Maya's option box is a small square at the right end of the item's line.
BOX_MARK = "  ❒"


def editor_menu_idname(editor, index):
    """Menu class of the ``index``-th menu of a Maya editor menu bar (``editor_menu_data.EDITORS``)."""
    return "ALLSET_MT_ed_" + "".join(ch for ch in editor.title() if ch.isalnum()) + f"_{index}"
