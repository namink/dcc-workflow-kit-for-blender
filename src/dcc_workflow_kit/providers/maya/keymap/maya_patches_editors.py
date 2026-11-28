# SPDX-License-Identifier: GPL-3.0-or-later
"""Keys of the kit's Maya editors: Channel Box (MMB virtual slider, hover, scroll), dock tab strip, Hypershade swatch
drag, Hypergraph, Outliner (MMB drag, kit tree rows), shelf wheel, Script Editor run, Render View slots, field drag,
option windows. Run by ``maya_patches.apply`` in ``PATCHES`` order; shared state: ``maya_patches_base``.
``IC:<line>`` = a line of ``$S\\presets\\keyconfig\\keymap_data\\industry_compatible_data.py``.
"""

from . import patch
from .patch import make_event
from .maya_patches_base import ADDED, PICK_WALK_KEYS, SLIDER_TOOL_KEYMAPS, UV_KM, _add


# --- 14. Channel Box MMB virtual slider ---------------------------------------
# Maya: MMB drag in the viewport drags the picked Channel Box attribute. Tool keymaps run before "3D View" and IC
# gives Move/Rotate/Scale/Transform an MMB drag (IC:3823-3858), so the slider
# goes first in those; it passes through when no channel is selected.


def patch_cb_slider(kd):
    for km in SLIDER_TOOL_KEYMAPS:
        _add(kd, km, "allset.cb_virtual_slider", make_event("MIDDLEMOUSE"), first=True,
             shadows=(km,))
    _add(kd, "Object Mode", "allset.cb_virtual_slider", make_event("MIDDLEMOUSE"),
         shadows=("Object Mode", "3D View"))     # the emulated Alt+LMB tumble (#242) passes through otherwise
    # Channel Box rows: drag over names / fields selects a range (the dock is a Properties editor;
    # ui/cb_drag.ALLSET_OT_cb_hover)
    _add(kd, "Property Editor", "allset.cb_hover", make_event("MOUSEMOVE", "ANY", any=True), first=True)
    # right-click on the panel toolbar's camera icon = the scene's cameras (ui/panel_toolbar.ALLSET_OT_pt_hover; the
    # 3D View tool header runs the "3D View Generic" keymap)
    _add(kd, "3D View Generic", "allset.pt_hover", make_event("MOUSEMOVE", "ANY", any=True), first=True)
    # Paint Skin Weights numeric labels around the brush need the pointer (ui/weight_numbers.py)
    # (both hover items pass the move on: the tool header's camera icon watch is in 3D View Generic)
    _add(kd, "Weight Paint", "allset.weight_numbers_hover", make_event("MOUSEMOVE", "ANY", any=True), first=True,
         shadows=("3D View Generic", "3D View"))
    # The Channel Box part of the dock scrolls by itself, the Layer Editor below stays (Maya's fixed split,
    # #55); passes through outside an overflowing Channel Box
    for wheel in ("WHEELUPMOUSE", "WHEELDOWNMOUSE"):
        # the region's "View2D Buttons List" handler runs before "Property Editor" (buttons_main_region_init adds
        # it first) and scrolls the whole region on the wheel, so the item sits first in that keymap
        _add(kd, "View2D Buttons List", "allset.cb_scroll", make_event(wheel), first=True,
             shadows=("View2D Buttons List",))   # first + PASS_THROUGH over view2d.scroll_up / _down
    # Maya's vertical tab strip on the dock's right edge (#78; ui/maya_dock_strip.draw_strip): drawn, not buttons,
    # so a click there reaches the keymaps; first in the region's earliest keymap (its scroller sits on that edge)
    _add(kd, "View2D Buttons List", "allset.dock_strip_click", make_event("LEFTMOUSE"), first=True,
         shadows=("View2D Buttons List", "Property Editor", "Screen"))   # PASS_THROUGH off the strip
    # Hypershade Browser: MMB-drag a material swatch onto an object = assign it (ui/hs_drag.py); the region's
    # view2d.pan / scroller_activate take MMB PRESS in this keymap, so the item goes first and passes through off a
    # swatch
    _add(kd, "View2D Buttons List", "allset.hs_swatch_drag", make_event("MIDDLEMOUSE"), first=True,
         shadows=("View2D Buttons List",))
    # Hypergraph: Hierarchy window (ui/hypergraph.py): a kit-drawn graph in a marked Properties region. The items
    # sit first in the region's earliest keymap and poll False outside a Hypergraph region.
    hg = ("View2D Buttons List", "Property Editor", "Screen", "Window", "Frames")
    for button, idname in (("LEFTMOUSE", "allset.hg_click"), ("MIDDLEMOUSE", "allset.hg_mmb"),
                           ("RIGHTMOUSE", "allset.hg_rmb")):
        _add(kd, "View2D Buttons List", idname, make_event(button, "PRESS", any=True), first=True, shadows=hg)
    for wheel, direction in (("WHEELUPMOUSE", "IN"), ("WHEELDOWNMOUSE", "OUT")):
        _add(kd, "View2D Buttons List", "allset.hg_zoom", make_event(wheel), {"direction": direction},
             first=True, shadows=hg)
    for key, everything in (("F", False), ("A", True)):
        _add(kd, "View2D Buttons List", "allset.hg_frame", make_event(key), {"all": everything},
             first=True, shadows=hg)


# --- 38. Outliner MMB drag ---------------------------------------------------------------
# Maya parents / reorders / unparents with an MMB drag in the Outliner; Blender's Outliner has
# no MMB item (IC "Outliner"), only View2D's MMB scroller_activate (IC:323), which passes through off the scroll
# bars and runs first. Alt+MMB pans (IC View2D, = Maya). "View2D Buttons List" (MMB pan) belongs to button-list
# regions (header / sidebar), not the Outliner tree. LMB drag stays Blender's (operators/outliner_drag.py redoes its
# drop the Maya way).

def patch_outliner_drag(kd):
    _add(kd, "Outliner", "allset.outliner_drag", make_event("MIDDLEMOUSE"), shadows=("View2D", "View2D Buttons List"))


# --- 45b. Maya Outliner tree (#348) -------------------------------------------------------------------------
# A Maya Outliner shows the kit's own rows (ui/outliner_tree.py: joints as rows under their parent joint) with
# Blender's rows hidden, so Blender's Outliner items (item_activate / item_rename / show_active / select_walk /
# delete / context menus / scroll) would act on nothing there. The kit's items go first and pass through in every
# other Outliner. Maya's Outliner keys: Enter = rename, f = Reveal Selected, the arrows = pick walk (Up = parent,
# Down = child, Left / Right = siblings). A fast second press arrives as DOUBLE_CLICK (rename).
# allset.outliner_delete (below, Blender-row Outliners) runs after the tree's Delete item.

OUTLINER_TREE_ITEMS = ("allset.outliner_tree_click", "allset.outliner_tree_menu", "allset.outliner_tree_rename",
                       "allset.outliner_tree_reveal", "allset.outliner_tree_walk", "allset.outliner_tree_delete",
                       "allset.outliner_tree_scroll", "allset.outliner_tree_pan", "allset.outliner_tree_hover")


def patch_outliner_tree(kd):
    sh = ("Outliner",)
    # the row under the mouse lights up (always passes through: Blender's own highlight_update follows)
    _add(kd, "Outliner", "allset.outliner_tree_hover", make_event("MOUSEMOVE", "ANY", any=True), first=True,
         shadows=sh)
    # (the Hypergraph's items in "View2D Buttons List" poll False outside its window; F2 stays Maya's menu set key)
    for value in ("PRESS", "DOUBLE_CLICK"):
        _add(kd, "Outliner", "allset.outliner_tree_click", make_event("LEFTMOUSE", value, any=True), first=True,
             shadows=sh + ("View2D Buttons List",))
    _add(kd, "Outliner", "allset.outliner_tree_menu", make_event("RIGHTMOUSE"), first=True, shadows=sh)
    _add(kd, "Outliner", "allset.outliner_tree_rename", make_event("RET"), first=True, shadows=sh + ("Screen",))
    for key in ("F", "PERIOD"):
        _add(kd, "Outliner", "allset.outliner_tree_reveal", make_event(key), first=True,
             shadows=sh + ("View2D Buttons List",))
    for key, direction in PICK_WALK_KEYS:
        _add(kd, "Outliner", "allset.outliner_tree_walk", make_event(key, repeat=True), {"direction": direction},
             first=True, shadows=sh)
    for key in ("DEL", "BACK_SPACE"):
        _add(kd, "Outliner", "allset.outliner_tree_delete", make_event(key), first=True, shadows=sh)
    for key, page in (("PAGE_DOWN", 1), ("PAGE_UP", -1)):
        _add(kd, "Outliner", "allset.outliner_tree_scroll", make_event(key, repeat=True), {"page": page},
             first=True, shadows=sh + ("View2D Buttons List",))
    # the wheel over the Outliner's rows goes to "View2D" (like the Graph Editor's channel region)
    for wheel, rows in (("WHEELUPMOUSE", -3), ("WHEELDOWNMOUSE", 3)):
        _add(kd, "View2D", "allset.outliner_tree_scroll", make_event(wheel), {"rows": rows}, first=True,
             shadows=("View2D", "View2D Buttons List"))
    # Maya: Alt+middle-drag pans the rows both ways, so a deep joint chain can be seen (#365)
    _add(kd, "View2D", "allset.outliner_tree_pan", make_event("MIDDLEMOUSE", alt=True), first=True,
         shadows=("View2D", "View2D Buttons List"))


# --- 46. Render slots ----------------------------------------------------------------------------------
# Keep Image = a Blender render slot (ui/render_view.py), compared with J / Alt+J like Blender
# ($S\presets\keyconfig\keymap_data\blender_default.py:2009-2011); IC's Image keymap has no J, so the kit's tip
# had no key behind it.

def patch_render_slots(kd):
    _add(kd, "Image", "image.cycle_render_slot", make_event("J"))
    _add(kd, "Image", "image.cycle_render_slot", make_event("J", alt=True), {"reverse": True})


def patch_shelf_scroll(kd):
    _add(kd, "Image", "allset.shelf_button_menu", make_event("RIGHTMOUSE", value="RELEASE"),
         first=True, shadows=("Image", "View2D"))
    # Maya's wheel over the shelf icons scrolls one row; the shelf
    # row is an Image Editor, so the items sit first in "Image" and pass through in every other image editor
    for wheel, delta in (("WHEELUPMOUSE", -1), ("WHEELDOWNMOUSE", 1)):
        _add(kd, "Image", "allset.shelf_scroll", make_event(wheel), {"delta": delta}, first=True,
             shadows=("Image", "View2D"))     # both pass through outside their own region


# --- 48. Script Editor execute ------------------------------------------------------------------------
# Maya: Ctrl+Enter executes (input kept), numpad Enter executes the whole tab and clears it. Only in the kit's Script
# Editor window (ui/script_editor.py); elsewhere the Text Editor's own keys stay (PASS_THROUGH).

def patch_script_editor(kd):
    # IC renders on Ctrl+Enter from "Screen Editing", a window keymap checked before every editor's (with
    # --debug-handlers: the Script Editor's Ctrl+Enter rendered, "No camera found"). Maya has no Ctrl+Enter render
    # (Render > Render Current Frame has no default hotkey; Ctrl+Alt+Enter render animation stays IC's).
    kd.remove("Screen Editing", "render.render", type="RET", ctrl=True, alt=False)
    # Blender 5.x IC adds Alt+F12 / Ctrl+Alt+F12 sequencer-scene renders there too (5.2 IC:299-302): they
    # took the UV Editor's Maya Alt+F12 (UV Shell, Maya hotkey).
    for ctrl in (False, True):
        if kd.find("Screen Editing", "render.render", type="F12", alt=True, ctrl=ctrl):
            kd.remove("Screen Editing", "render.render", type="F12", alt=True, ctrl=ctrl)
    _add(kd, "Text", "allset.script_run", make_event("RET", ctrl=True), first=True, shadows=("Text",))
    # Screen's numpad Enter = file.execute (file browsers only): the Text item runs first in a Text Editor anyway
    _add(kd, "Text", "allset.script_run", make_event("NUMPAD_ENTER"), {"clear": True}, first=True,
         shadows=("Text", "Screen"))


def patch_attribute_edit(kd):
    """Ctrl + left / middle / right drag on a number field of a kit editor (Attribute Editor, Channel Box, option
    windows) changes it in fine / normal / coarse steps, like Maya's field sliders: a mouse-move item tracks the field
    under the pointer and passes every event on, like the kit's other hover items (which pass it on too). Enter / Esc
    in a floating option window run or close it (they pass through everywhere else)."""
    for key, action in (('RET', 'RUN'), ('NUMPAD_ENTER', 'RUN'), ('ESC', 'CLOSE')):
        _add(kd, 'Property Editor', 'allset.option_editor_key', make_event(key), {'action': action},
             first=True, shadows=('Property Editor', 'Screen'))
    hover = make_event('MOUSEMOVE', 'ANY', any=True)
    hover_maps = ('Property Editor', 'View2D Buttons List', 'User Interface')
    for i, (km, idname, event, props, shadows) in enumerate(ADDED):
        if patch.event_key(event) == patch.event_key(hover):
            ADDED[i] = km, idname, event, props, tuple(dict.fromkeys((*shadows, *hover_maps, 'Window')))
    for km in hover_maps:
        _add(kd, km, 'allset.attribute_field_hover', hover, first=True,
             shadows=(*hover_maps, '3D View Generic', '3D View', 'Outliner', UV_KM, 'File Browser Main', 'Weight Paint',
                      'Graph Editor', 'Time Scrub', 'Window'))
    # the "Window" hover-leave item (operators/graph_hover.py) runs after every one of them and after the File
    # Browser's highlight (all pass the move on): no shadow either way
    hover_key = patch.event_key(hover)
    hover_kms = tuple(dict.fromkeys(km for km, _i, ev, _p, _s in ADDED if patch.event_key(ev) == hover_key))
    for i, (km, idname, event, props, shadows) in enumerate(ADDED):
        if km == 'Window' and patch.event_key(event) == patch.event_key(hover):
            ADDED[i] = km, idname, event, props, tuple(dict.fromkeys((*shadows, *hover_kms, 'File Browser Main')))


# --- Hypershade graph / Shader Editor (ui/hypershade_hands.py): Maya's graph hands in a material's node tree. Every
# item passes through in other node trees (Geometry Nodes, compositor keep Blender's keys). RMB = the graph marking
# menus (first: IC's context menu, IC:Node Editor RIGHTMOUSE, stays for other trees); Tab = Maya's create-node field
# (first over IC's Add-menu search in "Node Generic"); 1 / 2 / 3 / 4 view modes; = / - zoom; / , . select stream;
# Shift+? / < / > graph the stream (select + frame). Backspace / Delete / Ctrl+C / Ctrl+V / Ctrl+X are IC's already.
GRAPH_KEYMAP = "Node Editor"


def patch_hypershade_graph(kd):
    _add(kd, GRAPH_KEYMAP, "allset.marking_menu", make_event("RIGHTMOUSE"), {"trigger": "RMB"}, first=True,
         shadows=(GRAPH_KEYMAP,))
    # Node Generic: its Tab (Add menu search) runs before the Node Editor keymap's items
    _add(kd, "Node Generic", "allset.hs_tab_create", make_event("TAB"), first=True, shadows=("Node Generic",))
    # MMB on a node: Maya's drag-to-connect (Ctrl = the default connection); off a node the press passes on
    _add(kd, GRAPH_KEYMAP, "allset.hs_mmb_drag", make_event("MIDDLEMOUSE"), first=True,
         shadows=("View2D",))
    _add(kd, GRAPH_KEYMAP, "allset.hs_mmb_drag", make_event("MIDDLEMOUSE", ctrl=True), first=True,
         shadows=("View2D",))
    for key, mode in (("ONE", 'SIMPLE'), ("TWO", 'CONNECTED'), ("THREE", 'ALL'), ("FOUR", 'ALL')):
        _add(kd, GRAPH_KEYMAP, "allset.hs_view_mode", make_event(key), {"mode": mode})
    _add(kd, GRAPH_KEYMAP, "view2d.zoom_in", make_event("EQUAL"))
    _add(kd, GRAPH_KEYMAP, "view2d.zoom_out", make_event("MINUS"))
    for key, stream in (("SLASH", "BOTH"), ("COMMA", "UP"), ("PERIOD", "DOWN")):
        # over the graph these win over the Time Slider's , . (previous / next key)
        _add(kd, GRAPH_KEYMAP, "allset.hs_node_cmd", make_event(key), {"action": f"STREAM_{stream}", "selected": True},
             shadows=("Frames",))
        _add(kd, GRAPH_KEYMAP, "allset.hs_node_cmd", make_event(key, shift=True),
             {"action": f"GRAPH_{stream}", "selected": True})
