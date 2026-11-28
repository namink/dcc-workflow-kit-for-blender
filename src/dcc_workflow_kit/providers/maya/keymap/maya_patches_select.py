# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya selection keys: Shift / Ctrl / Ctrl+Shift click and marquee rules per editor, and the pass-through items in
front of Blender's selection (select-through, UV shells, selection priority, Tool Box guard, Tweak fallback). Run by
``maya_patches.apply`` in ``PATCHES`` order; shared state: ``maya_patches_base``. ``IC:<line>`` = a line of
``$S\\presets\\keyconfig\\keymap_data\\industry_compatible_data.py``.
"""

from . import patch
from .patch import make_event
from .maya_patches_base import _add


# --- 1. Selection modifiers ----------------------------------------------
# Maya: Shift = toggle, Ctrl = deselect, Ctrl+Shift = add, for click and
# marquee. Order of variants:
# (shift, ctrl) = none, Shift, Ctrl, Ctrl+Shift.

def _click(plain, toggle, deselect, add):
    return [((False, False), plain), ((True, False), toggle),
            ((False, True), deselect), ((True, True), add)]


# Operators with a real ``deselect`` option.
_CLICK_EXACT = _click({"deselect_all": True}, {"toggle": True},
                      {"deselect": True}, {"extend": True})

# Maya's Outliner is a Qt list — plain = replace,
# Shift = range from the anchor, Ctrl = toggle, Ctrl+Shift = add the range. Blender's item_activate does that with
# extend / extend_range (the anchor is Blender's active element).
_OUTLINER_CLICK = _click({"extend": False, "extend_range": False, "deselect_all": True},
                         {"extend": False, "extend_range": True, "deselect_all": True},
                         {"extend": True, "extend_range": False, "deselect_all": True},
                         {"extend": True, "extend_range": True, "deselect_all": True})
# Graph Editor (Maya): Shift toggles; Ctrl+click acts like a plain click; Ctrl+Shift adds — the plain / Ctrl /
# Ctrl+Shift rules that Blender's clickselect lacks are applied by allset.select_2d_click placed first (patch below);
# these items are what runs if that operator passes through.
_GRAPH_CLICK = _click({"extend": False, "deselect_all": True},
                      {"extend": True}, {"extend": False, "deselect_all": True}, {"extend": True})
# NLA (no Maya rule): every modifier toggles
_NLA_CLICK = _click({"extend": False, "deselect_all": True}, {"extend": True}, {"extend": True}, {"extend": True})
# Dope Sheet (Maya): Shift toggles, Ctrl deselects, Ctrl+Shift adds (select_2d_click)
_DOPE_CLICK = _click({"extend": False, "deselect_all": True},
                     {"extend": True}, {"extend": True}, {"extend": True})

_BOX = _click({"mode": "SET"}, {"mode": "XOR"}, {"mode": "SUB"}, {"mode": "ADD"})
# uv / graph / action select_box have no XOR: their Shift box runs as SET and allset.select_2d_box (first, PASS_THROUGH)
# toggles what it caught against the selection before. Outliner / NLA keep Shift = add.
_BOX_SET_XOR = _click({"mode": "SET"}, {"mode": "SET"}, {"mode": "SUB"}, {"mode": "ADD"})
_BOX_NO_XOR = _click({"mode": "SET"}, {"mode": "ADD"}, {"mode": "SUB"}, {"mode": "ADD"})

# node.select has a real deselect / toggle (4.5): Maya exactly. Node Ctrl+drag stays Blender's node.link
# (detach links from a socket): no Ctrl marquee there.
_NODE_CLICK = _click({"deselect_all": True, "select_passthrough": True}, {"toggle": True},
                     {"deselect": True}, {"extend": True})
_NODE_BOX = [v for v in _BOX_NO_XOR if v[0] != (False, True)]

SELECT_RULES = (
    # idname, event value, variants, props kept from IC's plain item
    ("view3d.select", "CLICK", _CLICK_EXACT, ()),          # IC "3D View", viewport
    ("view3d.select", "PRESS", _CLICK_EXACT, ()),          # "3D View Tool: Tweak"
    ("uv.select", "CLICK", _CLICK_EXACT, ()),              # "UV Editor"
    ("uv.select", "PRESS", _CLICK_EXACT, ()),              # "Image Editor Tool: Uv, Tweak"
    ("outliner.item_activate", "CLICK", _OUTLINER_CLICK, ()),
    ("graph.clickselect", "PRESS", _GRAPH_CLICK, ("column", "curves")),
    ("view3d.select_box", "CLICK_DRAG", _BOX, ("tweak",)),
    ("uv.select_box", "CLICK_DRAG", _BOX_SET_XOR, ("tweak",)),
    ("outliner.select_box", "CLICK_DRAG", _BOX_NO_XOR, ("tweak",)),
    ("graph.select_box", "CLICK_DRAG", _BOX_SET_XOR, ("tweak", "axis_range")),
    # Dope Sheet, NLA, Node Editor
    ("action.clickselect", "PRESS", _DOPE_CLICK, ("column", "channel")),
    ("nla.click_select", "PRESS", _NLA_CLICK, ()),
    ("node.select", "PRESS", _NODE_CLICK, ()),
    ("action.select_box", "CLICK_DRAG", _BOX_SET_XOR, ("tweak", "axis_range", "wait_for_input")),
    ("nla.select_box", "CLICK_DRAG", _BOX_NO_XOR, ("tweak", "axis_range", "wait_for_input")),
    ("node.select_box", "CLICK_DRAG", _NODE_BOX, ("tweak",)),
)


SELECT_CTRL_SHIFT_REMOVED = (("Dopesheet", "action.select_leftright"), ("NLA Editor", "nla.select_leftright"),
                             ("Node Editor", "node.select_link_viewer"),
                             # mesh edit mode: Ctrl+Shift+click adds the component (and with Symmetry on its
                             # partner), never Blender's shortest path from the active one (#445)
                             ("Mesh", "mesh.shortest_path_pick"))


def patch_selection(kd):
    # IC:935 Ctrl+Shift+LMB = select keys left/right of the frame; Maya has no
    # such binding and Ctrl+Shift click must add to the selection.
    kd.remove("Graph Editor", "graph.select_leftright", type="LEFTMOUSE",
              shift=True, ctrl=True)
    # the same Ctrl+Shift+LMB in the Dope Sheet / NLA, and Node Editor Ctrl+Shift+click = link to viewer
    for km, idname in SELECT_CTRL_SHIFT_REMOVED:
        kd.remove(km, idname, type="LEFTMOUSE", shift=True, ctrl=True)
    touched = {}
    for idname, value, variants, keep in SELECT_RULES:
        kms = kd.rewrite_modifier_set(idname, value, variants, keep_props=keep)
        if not kms:
            if not patch.STRICT:   # another Blender's IC data
                patch.DRIFT.append(f"selection patch: {idname} {value} not found")
                continue
            raise LookupError(f"selection patch: {idname} {value} not found in IC data")
        touched[(idname, value)] = kms
    patch_select_2d(kd, touched)
    return touched


# first-place operators that apply the Maya rule around Blender's own selection
# (operators/select_2d.py). (keymap family key, editor, [(shift, ctrl, rule)]) for clicks; boxes: Shift = XOR.
SELECT_2D_CLICKS = ((("graph.clickselect", "PRESS"), 'GRAPH', ((False, False, 'KEEP'), (False, True, 'CTRL'),
                                                               (True, True, 'ADD'))),
                    (("action.clickselect", "PRESS"), 'DOPE', ((False, True, 'DESELECT'), (True, True, 'ADD'))),
                    (("outliner.item_activate", "CLICK"), 'OUTLINER', ((False, True, 'TOGGLE'),)))
SELECT_2D_BOXES = ((("graph.select_box", "CLICK_DRAG"), 'GRAPH'), (("action.select_box", "CLICK_DRAG"), 'DOPE'),
                   (("uv.select_box", "CLICK_DRAG"), 'UV'))


SELECT_2D_KEYMAPS = set()      # keymaps that got a select_2d box item (tests: their shadowing stacks)


def patch_select_2d(kd, touched):
    for key, editor, variants in SELECT_2D_CLICKS:
        for km in touched.get(key, ()):
            if km not in ("Graph Editor", "Dopesheet", "Outliner"):          # tool keymaps keep Blender's items
                continue
            for shift, ctrl, rule in variants:
                _add(kd, km, "allset.select_2d_click", make_event("LEFTMOUSE", key[1], shift=shift, ctrl=ctrl),
                     {"editor": editor, "rule": rule}, shadows=(km, "Screen", "View2D"), first=True)
    for key, editor in SELECT_2D_BOXES:
        for km in touched.get(key, ()):
            _add(kd, km, "allset.select_2d_box", make_event("LEFTMOUSE", "CLICK_DRAG", shift=True),
                 {"editor": editor}, shadows=(km,), first=True)
            SELECT_2D_KEYMAPS.add(km)


# --- 26. Marquee selects occluded components --------------------------------------
# Like Maya. In front of every LMB drag
# box / lasso item of the select tools (and their fallbacks under Move/Rotate/Scale): sets the
# view's X-ray flag for the drag, then PASS_THROUGH to view3d.select_box / select_lasso.
SELECT_DRAG_KEYMAPS = ("3D View Tool: Select Box", "3D View Tool: Select Box (fallback)",
                       "3D View Tool: Select Lasso", "3D View Tool: Select Lasso (fallback)",
                       "3D View Tool: Tweak (fallback)")       # issue #205: the marquee copied there (below)


def patch_select_through(kd):
    for km in SELECT_DRAG_KEYMAPS:
        for shift, ctrl in ((False, False), (True, False), (False, True), (True, True)):
            _add(kd, km, "allset.select_through",
                 make_event("LEFTMOUSE", "CLICK_DRAG", shift=shift, ctrl=ctrl), first=True,
                 shadows=(km,))   # in front of the select item on purpose (PASS_THROUGH)


# Issue #205: Maya has no per-tool drag fallback — a drag off the Move / Rotate / Scale manipulator (or with any tool
# that falls back to selection) is a marquee. Blender keeps the fallback per workspace and mode ("Drag" in the tool
# header) and gives a tool the select group's current item, so a startup file or a session that had Tweak there
# makes the drag move the selection. The Tweak fallback keymaps (empty in Blender's data) get the Select Box
# fallback's marquee: add-on keymap items, gone with Maya mode, the workspace's fallback setting is never written.
# A Lasso / Circle fallback keeps its own keymap; Maya's tweak mode is the ` hold (the Tweak tool's own keymap).
# Runs before patch_selection so the Maya modifier rules, select-through and the UV shell box apply to the copies.
TWEAK_FALLBACK_MARQUEE = (("3D View Tool: Tweak (fallback)", "3D View Tool: Select Box (fallback)"),
                          ("Image Editor Tool: Uv, Tweak (fallback)", "Image Editor Tool: Uv, Select Box (fallback)"))


def patch_tweak_fallback(kd):
    for tweak, box in TWEAK_FALLBACK_MARQUEE:
        for idname, event, props in list(kd.items(box)):
            _add(kd, tweak, idname, dict(event), patch.props_dict(props), shadows=(tweak,))


# #172: Maya UV Shell selection (operators/uv_shell_select.py) — a click picks the whole UV shell, a box /
# lasso grows to shells; in front of the click / drag select items of the 3D View and the UV Editor, PASS_THROUGH
# unless the UV Shell mask is on.
UV_SHELL_CLICK_KEYMAPS = ("3D View", "UV Editor")
UV_SHELL_DRAG_KEYMAPS = SELECT_DRAG_KEYMAPS + ("Image Editor Tool: Uv, Select Box",
                                              "Image Editor Tool: Uv, Select Box (fallback)",
                                              "Image Editor Tool: Uv, Select Lasso",
                                              "Image Editor Tool: Uv, Select Lasso (fallback)",
                                              "Image Editor Tool: Uv, Tweak (fallback)")


def patch_uv_shell_select(kd):
    mods = ((False, False), (True, False), (False, True), (True, True))
    for km in UV_SHELL_CLICK_KEYMAPS:
        for shift, ctrl in mods:
            _add(kd, km, "allset.uv_shell_pick", make_event("LEFTMOUSE", "CLICK", shift=shift, ctrl=ctrl),
                 first=True, shadows=(km,))   # in front of view3d.select / uv.select on purpose (PASS_THROUGH)
    for km in UV_SHELL_DRAG_KEYMAPS:
        for shift, ctrl in mods:
            _add(kd, km, "allset.uv_shell_box", make_event("LEFTMOUSE", "CLICK_DRAG", shift=shift, ctrl=ctrl),
                 first=True, shadows=(km,))   # always PASS_THROUGH: Blender's box runs, the kit grows it after


# a click under the Tool Box column's tools reaches that narrow 3D View's WINDOW region,
# where view3d.select would deselect everything (it deselects hidden object types too). The guard
# swallows the click there and passes it through everywhere else (ui/toolbox.py).
def patch_toolbox_guard(kd):
    for shift, ctrl in ((False, False), (True, False), (False, True), (True, True)):
        _add(kd, "3D View", "allset.toolbox_guard", make_event("LEFTMOUSE", "CLICK", shift=shift, ctrl=ctrl),
             first=True, shadows=("3D View",))   # in front of view3d.select on purpose (PASS_THROUGH)


# Maya selection priority — in front of the object-mode click
# select items ("3D View" CLICK, Tweak tool PRESS); passes through outside object mode and when no IK
# handle / joint / curve is under the mouse (operators/select_priority.py).
SELECT_PRIORITY_ITEMS = (("3D View", "CLICK"), ("3D View Tool: Tweak", "PRESS"))


def patch_select_priority(kd):
    for km, value in SELECT_PRIORITY_ITEMS:
        for shift, ctrl in ((False, False), (True, False), (False, True), (True, True)):
            _add(kd, km, "allset.select_priority", make_event("LEFTMOUSE", value, shift=shift, ctrl=ctrl),
                 first=True, shadows=(km,))   # in front of view3d.select on purpose (PASS_THROUGH)


# Type Manipulator: a click on a character of a type whose manipulator is on picks that character (right behind the
# selection priority item, in front of the selection items; passes through anywhere else, operators/type_manip.py).
def patch_type_char_pick(kd):
    for km, value in SELECT_PRIORITY_ITEMS:
        _add(kd, km, "allset.type_char_pick", make_event("LEFTMOUSE", value), first=True, shadows=(km,))


# --- UV shell pre-selection (#264) ------------------------------------------------------------------------------
# The UV Editor's mouse moves are watched (always PASS_THROUGH) so the shell under the mouse can be highlighted.

def patch_uv_shell_hover(kd):
    _add(kd, "UV Editor", "allset.uv_shell_hover", make_event("MOUSEMOVE", "ANY", any=True), first=True)
