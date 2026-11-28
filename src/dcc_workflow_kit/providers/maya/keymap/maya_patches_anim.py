# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya animation keys: Time Slider mouse and range drag, key / frame stepping, S and Shift+W/E/R Set Key everywhere,
insert / nudge / select keys, Graph Editor keys (tangents, frame, axis drag, key tools, handles, outliner rows),
motion trail keys. Run by ``maya_patches.apply`` in ``PATCHES`` order; shared state: ``maya_patches_base``.
``IC:<line>`` = a line of ``$S\\presets\\keyconfig\\keymap_data\\industry_compatible_data.py``.
"""

from . import patch
from .patch import make_event
from .maya_patches_base import ADDED, _add


# --- 20. Key / frame stepping: . , Alt+. Alt+, --------------------------------------
# Maya hotkeys (NextKey, PreviousKey, NextFrame, PreviousFrame).
# "Frames" is in nearly every editor; the 3D View / Image pies on . , go (pivot and orientation stay
# in the headers). The Outliner (show active) and Clip Editor (pivot pie) keep their own . first; over the
# Hypershade graph , . select up / down the stream, like Maya's graph keys.

def patch_key_stepping(kd):
    kd.remove("3D View", "wm.call_menu_pie", type="PERIOD")      # pivot pie
    kd.remove("3D View", "wm.call_menu_pie", type="COMMA")       # orientation pie
    kd.remove("Image", "wm.call_menu_pie", type="PERIOD")        # UV pivot pie
    keep = ("Outliner", "Clip Editor", "Node Editor")
    # . , step through the keys the Time Slider shows (Maya findKeyframe -timeSlider): not a deformer's keys on the
    # deformed object, round from the last key to the first
    _add(kd, "Frames", "allset.key_jump", make_event("PERIOD"), {"next": True}, shadows=keep)
    _add(kd, "Frames", "allset.key_jump", make_event("COMMA"), {"next": False}, shadows=keep)
    _add(kd, "Frames", "screen.frame_offset", make_event("PERIOD", alt=True, repeat=True), {"delta": 1})
    _add(kd, "Frames", "screen.frame_offset", make_event("COMMA", alt=True, repeat=True), {"delta": -1})
    # Maya Previous / Next Blue Pencil Frame = Alt+< / Alt+> (the < > characters as for Grow / Shrink: Shift+, /
    # Shift+. on a US keyboard, a < > key of its own types < plain and > with Shift)
    for event, forward in ((make_event("COMMA", shift=True, alt=True), False), (make_event("GRLESS", alt=True), False),
                           (make_event("PERIOD", shift=True, alt=True), True),
                           (make_event("GRLESS", shift=True, alt=True), True)):
        _add(kd, "Frames", "allset.blue_pencil_frame", event, {"next": forward})


# --- 31. Time Slider and keys --------------------------------------------------------
# Maya Time Slider. The timeline is a Dope Sheet mode: the Maya Time Slider
# mouse (LMB time, Shift+LMB range, MMB time + notice, RMB menu) goes first in "Dopesheet" and passes
# through in the Dope Sheet. K (Time Dragger, Maya hotkey) is global ("Screen"); editor keymaps
# run first, so their plain K goes: Mesh knife tool cycle (IC:3074; Multi-Cut = Ctrl+Shift+X) and
# Dope Sheet select_column (IC:1435). "User Interface" / Outliner K only act over a button / row.
# S (Maya Set Key) = every keyable channel, not IC's LocRotScale (IC:2463, :2536).

TIME_SLIDER_SHADOWS = ("Dopesheet", "View2D", "Screen")   # Screen: the Range Slider click
# every View2D zoom / scroll event (wheel, tilt wheel, trackpad, Ctrl / Shift + MMB drag, numpad +/-)
TIME_VIEW_LOCK_EVENTS = (
    *(make_event(wheel, **mods) for wheel in ("WHEELUPMOUSE", "WHEELDOWNMOUSE")
      for mods in ({}, {"ctrl": True}, {"shift": True})),
    make_event("WHEELLEFTMOUSE"), make_event("WHEELRIGHTMOUSE"),
    make_event("MIDDLEMOUSE", ctrl=True), make_event("MIDDLEMOUSE", shift=True),
    make_event("TRACKPADZOOM", value="ANY"), make_event("TRACKPADPAN", value="ANY"),
    make_event("TRACKPADPAN", value="ANY", ctrl=True),
    make_event("NUMPAD_PLUS"), make_event("NUMPAD_MINUS"))
TIME_VIEW_LOCK_SHADOWS = ("View2D", "View2D Buttons List", "Animation Channels")


def patch_time_slider(kd):
    for shift in (False, True):
        _add(kd, "Dopesheet", "allset.time_scrub", make_event("LEFTMOUSE", shift=shift), {"range": shift},
             first=True, shadows=TIME_SLIDER_SHADOWS)
    _add(kd, "Dopesheet", "allset.time_scrub", make_event("MIDDLEMOUSE"), {"hold": True}, first=True,
         shadows=TIME_SLIDER_SHADOWS)
    _add(kd, "Dopesheet", "allset.time_slider_menu", make_event("RIGHTMOUSE"), first=True,
         shadows=TIME_SLIDER_SHADOWS)
    # Delete / Backspace over the Time Slider delete the selection as in the viewport (Maya); Blender's would delete
    # every key the Timeline shows
    for key in ("DEL", "BACK_SPACE"):
        _add(kd, "Dopesheet", "allset.time_slider_delete", make_event(key), first=True, shadows=TIME_SLIDER_SHADOWS)
    # Maya's Time Slider never zooms or scrolls (the Range Slider sets what it shows): View2D's wheel, trackpad,
    # Ctrl+MMB and numpad +/- zoom / scroll are swallowed in the Timeline, passed through elsewhere. Over the
    # Timeline these events reach the region's "View2D" keymap before "Dopesheet" (#292), so the items sit first
    # in View2D.
    for ev in TIME_VIEW_LOCK_EVENTS:
        _add(kd, "View2D", "allset.time_view_lock", ev, first=True, shadows=TIME_VIEW_LOCK_SHADOWS)
    # a double-click highlights the whole visible range (Maya); Blender's double-click item here toggles the
    # channel editability and left its redo panel over the Time Slider (#335)
    _add(kd, "Dopesheet", "allset.time_range_all", make_event("LEFTMOUSE", value="DOUBLE_CLICK"), first=True,
         shadows=TIME_SLIDER_SHADOWS)
    # Range Slider bar: a click on the empty label in the timeline header reaches the window
    # keymaps; the operator passes through anywhere but over the bar ui/range_bar.py drew.
    # Every editor keymap that uses the click runs first (intended: only unhandled clicks get here).
    for value in ("PRESS", "DOUBLE_CLICK"):
        under = tuple(n for n in kd.keymap_names() if n != "Screen" and kd.find(n, type="LEFTMOUSE", value=value))
        if value == "DOUBLE_CLICK":
            under += ("Time Scrub",)   # its double-click item (the whole visible range) comes in patch_time_range
        _add(kd, "Screen", "allset.range_bar_drag", make_event("LEFTMOUSE", value=value), shadows=under)
    kd.remove("Mesh", "wm.tool_set_by_id", type="K")
    kd.remove("Dopesheet", "action.select_column", type="K")
    _add(kd, "Screen", "allset.tap_hold", make_event("K"), {"binding": "time_drag"},
         shadows=("User Interface", "Outliner"))
    for km in ("Object Mode", "Pose"):
        kd.remove(km, "anim.keyframe_insert_by_name", type="S")
        _add(kd, km, "allset.set_key", make_event("S"))
        # Shift+W / E / R (#100): IC's keyframe_insert_by_name reports "Successfully added ... keying set";
        # the kit keys the Channel Box channels silently like Maya's SetKeyTranslate / Rotate / Scale
        # (one "Screen" item each, patch_global_set_key: they work in every editor)
        for key in ("W", "E", "R"):
            kd.remove(km, "anim.keyframe_insert_by_name", type=key, shift=True)
    # Maya S in component mode keys the selected points' positions (vertices, CVs, lattice points)
    for km in ("Mesh", "Curve", "Lattice"):
        _add(kd, km, "allset.set_key", make_event("S"))


# --- 37. Graph Editor keys, Shift+S tangent marking menu ---------------------------------------
# Maya hotkeys: Graph Editor G = FramePlaybackRange, D = TangentAuto, Shift+S hold =
# KeyframeTangentMarkingMenu. G / D go in "Graph Editor" (it runs before Screen's G = repeat_last);
# Shift+S replaces IC's keyframe_insert menu in Object Mode / Pose (IC:2462, 2535) and is added to the Graph Editor
# and Dope Sheet. Mesh / UV Shift+S (UV Sew) stay.

def patch_graph_keys(kd):
    _add(kd, "Graph Editor", "anim.scene_range_frame", make_event("G"), shadows=("Screen",))   # over repeat_last
    _add(kd, "Graph Editor", "allset.set_tangent", make_event("D"), {"kind": "AUTO"})
    for km in ("Object Mode", "Pose"):
        kd.remove(km, "anim.keyframe_insert", type="S", shift=True)
    for km in ("Object Mode", "Pose", "Graph Editor", "Dopesheet"):
        _add(kd, km, "allset.tap_hold", make_event("S", shift=True), {"binding": "key_tangent"})


# --- 39. Insert / nudge / select keys ---------------------------------------------------------
# Maya global keys (Maya hotkeys). "Screen" so they work over the 3D View, Graph Editor,
# Dope Sheet and Time Slider; the operators read the editor under the mouse. Editor / mode keymaps with the same
# event run first and keep it (Weight Paint / Grease Pencil / Mask Alt+I, Animation Channels Ctrl+Shift+W, Text
# Ctrl+Shift+E, the UI colour-ramp eyedropper Alt+I).
INSERT_KEY_KEYS = (("I", {"alt": True}, {"channels": "ALL"}),
                   ("W", {"ctrl": True, "shift": True}, {"channels": "TRANSLATE"}),
                   ("E", {"ctrl": True, "shift": True}, {"channels": "ROTATE"}),
                   ("R", {"ctrl": True, "shift": True}, {"channels": "SCALE"}))
KEY_STEP_SHADOWS = ("User Interface", "Mask Editing", "Weight Paint", "Grease Pencil Paint Mode",
                    "Grease Pencil Edit Mode", "Grease Pencil Sculpt Mode", "Grease Pencil Weight Paint",
                    "Grease Pencil Vertex Paint", "Animation Channels", "Text",
                    # Blender 5.x IC only: Draw Mode Alt+I / Ctrl+Shift+E, Sequencer Ctrl+Shift+R
                    "Grease Pencil Draw Mode", "Sequencer")


def patch_key_insert(kd):
    for key, mods, props in INSERT_KEY_KEYS:
        _add(kd, "Screen", "allset.insert_key", make_event(key, **mods), props, shadows=KEY_STEP_SHADOWS)
    for key, delta in (("NINE", -1), ("ZERO", 1)):
        _add(kd, "Screen", "allset.nudge_keys", make_event(key, shift=True, repeat=True), {"delta": delta},
             shadows=KEY_STEP_SHADOWS)
    for key, direction in (("COMMA", "PREVIOUS"), ("PERIOD", "NEXT")):
        _add(kd, "Screen", "allset.select_key", make_event(key, ctrl=True, alt=True), {"direction": direction},
             shadows=KEY_STEP_SHADOWS)


# --- 40. Time Slider range drag ------------------------------------------------------------------
# A press on the highlighted range moves / scales its keys; anywhere else it passes through to time_scrub,
# so it goes in front of it (added after patch_time_slider: ``first`` puts the latest item first).
# The Maya Workflow Kit Time Slider row (29 px at 1.25) is all Blender's scrub strip, whose "Time Scrub" keymap (LMB =
# anim.change_frame, blender_default.py:1171-1183) runs before "Dopesheet"; IC has no "Time Scrub", so Blender used
# its default one (seen with --debug-handlers). The Maya keyconfig gets its own: change_frame kept, the range
# drag and the kit's time_scrub (a click drops the range) in front; both pass through outside the Time Slider.
TIME_SCRUB_KM = ("Time Scrub", {"space_type": 'EMPTY', "region_type": 'WINDOW'})


def patch_time_range(kd):
    _add(kd, "Dopesheet", "allset.time_range_drag", make_event("LEFTMOUSE"), first=True, shadows=TIME_SLIDER_SHADOWS)
    kd.ensure(*TIME_SCRUB_KM, [("anim.change_frame", make_event("LEFTMOUSE"), None)])
    shadows = (*TIME_SLIDER_SHADOWS, "Time Scrub")
    _add(kd, "Time Scrub", "allset.time_scrub", make_event("LEFTMOUSE"), first=True, shadows=shadows)
    _add(kd, "Time Scrub", "allset.time_range_drag", make_event("LEFTMOUSE"), first=True, shadows=shadows)
    _add(kd, "Time Scrub", "allset.time_range_all", make_event("LEFTMOUSE", value="DOUBLE_CLICK"), first=True,
         shadows=shadows)
    # the bookmark strip (Maya layout): a click on a bookmark doesn't move the time, Ctrl + double-click highlights
    # its range; the mouse over a bookmark shows its name and range (gone once the mouse leaves the Time Slider)
    for mods in ({}, {"shift": True}, {"ctrl": True}):
        _add(kd, "Time Scrub", "allset.time_slider_bookmark_click", make_event("LEFTMOUSE", **mods), first=True,
             shadows=shadows)
    _add(kd, "Time Scrub", "allset.time_slider_bookmark_click", make_event("LEFTMOUSE", value="DOUBLE_CLICK",
                                                                           ctrl=True),
         {"double": True}, first=True, shadows=shadows)
    # Ctrl + drag on a bookmark moves it or one of its ends (in front of the Ctrl click item; a second press = the
    # Ctrl + double-click passes on to it)
    _add(kd, "Time Scrub", "allset.time_slider_bookmark_drag", make_event("LEFTMOUSE", ctrl=True), first=True,
         shadows=shadows)
    _add(kd, "Time Scrub", "allset.time_slider_bookmark_hover", make_event("MOUSEMOVE", "ANY", any=True), first=True)


# --- 44. Graph Editor key batch ---------------------------------------------------------------
# Maya hotkeys t = GraphEditorFrameCenterView, Alt+/ = SnapTimeToSelection toggle, i hold =
# Insert Key tool; Maya binds it globally, it only means something in the Graph Editor.
# None of these events is bound in the Graph Editor keymaps.

def patch_graph_keys_2(kd):
    _add(kd, "Graph Editor", "allset.graph_center_time", make_event("T"))
    _add(kd, "Graph Editor", "allset.snap_time_toggle", make_event("SLASH", alt=True))
    _add(kd, "Graph Editor", "allset.insert_key_tool", make_event("I"))
    # #192: Maya F / A frame Maya's rectangle (selected keys with both segments / every curve shown,
    # 10 % time and 25 % value margins) instead of Blender's View Selected / View All
    kd.remove("Graph Editor", "graph.view_selected", type="F")
    kd.remove("Graph Editor", "graph.view_all", type="A")
    _add(kd, "Graph Editor", "allset.graph_frame", make_event("F"), {"mode": 'SELECTED'})
    _add(kd, "Graph Editor", "allset.graph_frame", make_event("A"), {"mode": 'ALL'})
    # Maya S over the Graph Editor / Dope Sheet = Set Key on the selected objects' keyable channels (a fresh object's
    # 10 channels appear), not Blender's key on the curves the editor already shows
    for km, op in (("Graph Editor", "graph.keyframe_insert"), ("Dopesheet", "action.keyframe_insert")):
        kd.remove(km, op, type="S")
        _add(kd, km, "allset.set_key", make_event("S"))
    # #192: Maya Shift+MMB anywhere / Shift+LMB drag on a selected key = move along time or value only
    # (the first 3 px pick the axis); Blender binds no Shift+MMB here and its Shift+LMB drag is the marquee, which
    # still runs off the selected keys (the operator passes through). The Time Slider's view lock on Shift+MMB in
    # View2D passes through outside a Timeline.
    _add(kd, "Graph Editor", "allset.graph_axis_drag", make_event("MIDDLEMOUSE", shift=True), {"button": 'MIDDLE'},
         shadows=("View2D",))
    _add(kd, "Graph Editor", "allset.graph_axis_drag", make_event("LEFTMOUSE", "CLICK_DRAG", shift=True),
         {"button": 'LEFT'}, first=True, shadows=("Graph Editor",))
    # Maya time snap: Blender's MMB / LMB key moves land on whole frames (the operator only watches, PASS_THROUGH)
    for button in ("MIDDLEMOUSE", "LEFTMOUSE"):
        _add(kd, "Graph Editor", "allset.graph_move_snap", make_event(button, "CLICK_DRAG"), first=True,
             shadows=("Graph Editor",))
    # Scale Keys box, Shift on a corner: scale in time or value only (a Shift press off the corners / sides passes
    # through); added before the Shift press watcher below, which therefore still runs first
    _add(kd, "Graph Editor", "allset.graph_scale_box", make_event("LEFTMOUSE", shift=True), first=True,
         shadows=("Graph Editor", "Screen", "View2D"))
    # Blender's Shift+click toggles a selected key off on the press: remember the selection so a Shift+drag from it
    # still moves the keys (PASS_THROUGH, the toggle runs)
    _add(kd, "Graph Editor", "allset.graph_shift_press", make_event("LEFTMOUSE", shift=True), first=True,
         shadows=("Graph Editor",))
    # Maya middle drag = the current key tool (move / turn tangents / scale) counted from the press; Blender's own
    # drag starts a few px later. Passes through when no key is selected.
    _add(kd, "Graph Editor", "allset.graph_key_drag", make_event("MIDDLEMOUSE"), first=True,
         shadows=("Graph Editor", "View2D"))
    # Maya w / e / r over the Graph Editor pick the key tool instead of starting a move / rotate / scale at once
    for key, tool in (("W", 'MOVE'), ("E", 'ROTATE'), ("R", 'SCALE')):
        kd.remove("Graph Editor", GRAPH_WER[key], type=key)
        _add(kd, "Graph Editor", "allset.graph_key_tool", make_event(key), {"tool": tool})
    # Maya l = value lines
    _add(kd, "Graph Editor", "allset.graph_value_lines", make_event("L"))
    # Scale Keys tool (r): a left press on a side / corner of the box around the selected keys scales them; anywhere
    # else it passes through to Blender's click select
    _add(kd, "Graph Editor", "allset.graph_scale_box", make_event("LEFTMOUSE"), first=True,
         shadows=("Graph Editor", "Screen", "View2D"))


GRAPH_WER = {"W": "transform.translate", "E": "transform.rotate", "R": "transform.resize"}


# --- 47. Graph Editor outliner rows ------------------------------------------------------------------
# The kit draws Maya's outliner pane (object + "Translate X" rows) over the Graph Editor's channel region
# (ui/graph_outliner.py); presses on it go first in "Animation Channels" (Blender's channels_click is a PRESS item, a
# handled press sends no CLICK) and pass through over Blender's search field.

def patch_graph_outliner(kd):
    _add(kd, "Animation Channels", "allset.graph_channel_click", make_event("LEFTMOUSE", any=True),
         first=True, shadows=("Animation Channels", "View2D Buttons List"))   # Hypergraph items poll False here
    # #96: the wheel scrolls the kit's rows (ui/graph_outliner.py keeps the offset). In the channel region
    # the wheel goes to "View2D" and never reaches "Animation Channels" (--debug-handlers), so the items
    # sit first in View2D; the operator passes through anywhere but a kit Graph Editor's outliner pane.
    for wheel, delta in (("WHEELUPMOUSE", -3), ("WHEELDOWNMOUSE", 3)):
        _add(kd, "View2D", "allset.graph_channel_scroll", make_event(wheel), {"delta": delta}, first=True,
             shadows=("View2D", "View2D Buttons List"))
    # a click on a curve the kit draws for another selected animation layer (ui/graph_layers.py) makes that
    # layer the editable one (Maya edits every selected layer's curves; Blender one action per object); it passes
    # through when no such curve is under the mouse
    _add(kd, "Graph Editor", "allset.graph_layer_pick", make_event("LEFTMOUSE"), first=True,
         shadows=("Graph Editor", "Screen", "View2D"))


# Maya editable motion trail: a left press on a key marker of a motion path picks the key and a drag moves it
# (operators/motion_trail_edit.py); plain = set, Shift = toggle, Ctrl = remove, Ctrl+Shift = add. In front of the
# 3D View's and the Tweak tool's press items; passes through anywhere else. With the Move tool and picked keys a
# press on the kit's trail key manipulator drags its handle.
# the paint / sculpt / edit mode keymaps keep their own presses (the trail keys are for Object and Pose Mode only);
# the Screen's Range Slider bar click only acts over the bar
TRAIL_KEY_SHADOWS = ("Screen", "Image Paint", "Vertex Paint", "Weight Paint", "Sculpt", "Particle", "Curve", "Mesh",
                     "Armature")


def patch_motion_trail_keys(kd):
    for km in ("3D View", "3D View Tool: Tweak"):
        for shift, ctrl, mode in ((False, False, 'SET'), (True, False, 'TOGGLE'), (False, True, 'SUB'),
                                  (True, True, 'ADD')):
            _add(kd, km, "allset.motion_trail_key", make_event("LEFTMOUSE", shift=shift, ctrl=ctrl), {"mode": mode},
                 first=True, shadows=(km,) + TRAIL_KEY_SHADOWS)


def patch_motion_trail_mmb(kd):
    """Move tool: a middle drag anywhere moves the picked trail keys along the last used handle (passes through when
    no trail key is picked, so the Move tool's own middle drag runs). Applied before the Channel Box virtual slider
    patch, so the slider (highlighted channels) stays in front, like Maya."""
    _add(kd, "3D View Tool: Move", "allset.motion_trail_key", make_event("MIDDLEMOUSE"), {"button": 'MIDDLE'},
         first=True, shadows=("3D View Tool: Move",))


# --- Shift+W / E / R everywhere (Maya global hotkeys) ---------------------------------------------------------
# Maya's SetKeyTranslate / Rotate / Scale work in any editor (Graph Editor, Dope Sheet, Outliner, Channel Box /
# Attribute Editor, Time Slider): one item each in "Screen" ({"global_key": True}: passes through outside object /
# pose mode, so edit modes keep their own keys). IC's Animation Channels Shift+W (protect toggle) is removed; every
# other same-event item runs first on purpose (Object Mode / Pose kit items, edit-mode, sculpt and file keys).
# Maya's S (Set Key) too: over the Channel Box right after a typed value, the Outliner, the shelf ... it keys what S
# over the viewport keys (also in component mode: the selected points). The editors' own S items run first (the kit's
# 3D View / Graph Editor / Dope Sheet S, Node / Image / UV Editor scale, text typing), so they keep their meaning.

def patch_global_set_key(kd):
    kd.remove("Animation Channels", "anim.channels_setting_toggle", type="W", shift=True)
    for key, channels in (("W", "TRANSLATE"), ("E", "ROTATE"), ("R", "SCALE")):
        under = tuple(n for n in kd.keymap_names() if n != "Screen" and kd.find(n, type=key, shift=True))
        _add(kd, "Screen", "allset.set_key", make_event(key, shift=True), {"channels": channels, "global_key": True},
             shadows=under)
    ev = make_event("S")
    under = tuple(n for n in kd.keymap_names() if n != "Screen" and kd.find(n, type="S"))
    for i, (km, idname, e, props, shadows) in enumerate(ADDED):
        if km != "Screen" and patch.event_key(e) == patch.event_key(ev) and "Screen" not in shadows:
            ADDED[i] = (km, idname, e, props, shadows + ("Screen",))
    _add(kd, "Screen", "allset.set_key", ev, {"global_key": True}, shadows=under)


# --- w / e / r over the whole Graph Editor ------------------------------------------------------------------------
# The Graph Editor's own keymap covers only its curve area. Over its outliner, menu bar, toolbar row and sidebar the
# same keys pick the key tool too: one "Screen" item each, whose poll lets the key through outside a Graph Editor.
# Every editor / mode item with the same key runs before "Screen", so those keep their meaning.

def patch_graph_key_tool_everywhere(kd):
    for key, tool in (("W", 'MOVE'), ("E", 'ROTATE'), ("R", 'SCALE')):
        ev = make_event(key)
        under = tuple(n for n in kd.keymap_names() if n != "Screen" and kd.find(n, type=key))
        for i, (km, idname, e, props, shadows) in enumerate(ADDED):
            if km != "Screen" and patch.event_key(e) == patch.event_key(ev) and "Screen" not in shadows:
                ADDED[i] = (km, idname, e, props, shadows + ("Screen",))
        _add(kd, "Screen", "allset.graph_key_tool", ev, {"tool": tool}, shadows=under)


# --- Graph Editor tangent handles (#296) -------------------------------------------------------------------------
# While the kit draws a Graph Editor's tangent handles (ui/graph_handles.py) Blender's handle picking is off, so a
# left press on a kit handle end selects / drags it (plain and Ctrl = select, Shift = toggle, Ctrl+Shift = add) and a
# middle drag moves the selected handles; the marquee also picks the handle ends inside it. Added after every
# other Graph Editor click item so they run first; each passes through anywhere else.

def patch_graph_handles(kd):
    for shift, ctrl, mode in ((False, False, 'SET'), (False, True, 'SET'), (True, False, 'TOGGLE'),
                              (True, True, 'ADD')):
        _add(kd, "Graph Editor", "allset.graph_handle_drag", make_event("LEFTMOUSE", shift=shift, ctrl=ctrl),
             {"button": 'LEFT', "mode": mode}, first=True, shadows=("Graph Editor", "Screen", "View2D"))
    _add(kd, "Graph Editor", "allset.graph_handle_drag", make_event("MIDDLEMOUSE"), {"button": 'MIDDLE'},
         first=True, shadows=("Graph Editor", "View2D"))
    for shift, ctrl, mode in ((False, False, 'SET'), (True, False, 'XOR'), (False, True, 'SUB'),
                              (True, True, 'ADD')):
        _add(kd, "Graph Editor", "allset.graph_handle_box", make_event("LEFTMOUSE", "CLICK_DRAG", shift=shift,
                                                                       ctrl=ctrl),
             {"mode": mode}, first=True, shadows=("Graph Editor",))


# --- Graph Editor Region Keys tool, Pre-Select Highlight, Prefer Selected Curves ----------------------------------
# The mouse moves are watched for the curve under the mouse; a marquee is read when it ends (the Region Keys tool
# keeps its region, Prefer Selected Curves drops the other curves' keys); with Prefer Selected Curves a press near a
# key of a curve with selected keys picks it (Graph Editor rules: Ctrl = plain click, Shift toggles, Ctrl+Shift adds).
# All pass through when they don't apply. The watchers go in front of every Graph Editor item; the click goes in
# front of the Graph Editor's click select but behind the kit's tangent handle, Scale Keys box and Shift press items
# (``patch_graph_prefer_click`` runs early in PATCHES).

def patch_graph_tools(kd):
    _add(kd, "Graph Editor", "allset.graph_hover", make_event("MOUSEMOVE", "ANY", any=True), first=True)
    # a drag in the curve view (left-button drag start, middle-button press, any modifiers) drops the highlight
    _add(kd, "Graph Editor", "allset.graph_hover_drop", make_event("LEFTMOUSE", "CLICK_DRAG", any=True), first=True,
         shadows=("Graph Editor",))
    _add(kd, "Graph Editor", "allset.graph_hover_drop", make_event("MIDDLEMOUSE", any=True), first=True,
         shadows=("Graph Editor",))
    # the Time Slider's bookmark name goes once the mouse is anywhere outside the Time Slider (Window: every area);
    # the pre-selection highlight stays, like Maya
    _add(kd, "Window", "allset.hover_leave", make_event("MOUSEMOVE", "ANY", any=True))
    _add(kd, "Graph Editor", "allset.graph_marquee_watch", make_event("LEFTMOUSE", "CLICK_DRAG", any=True),
         first=True, shadows=("Graph Editor",))


def patch_graph_prefer_click(kd):
    for shift, ctrl, mode in ((False, False, 'SET'), (False, True, 'SET'), (True, False, 'TOGGLE'),
                              (True, True, 'ADD')):
        _add(kd, "Graph Editor", "allset.graph_prefer_click", make_event("LEFTMOUSE", shift=shift, ctrl=ctrl),
             {"mode": mode}, first=True, shadows=("Graph Editor", "Screen", "View2D"))
