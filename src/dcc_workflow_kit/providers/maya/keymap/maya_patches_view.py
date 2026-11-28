# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya 3D View and 2D-editor navigation / display keys: Alt+mouse tumble / track / dolly, framing (F, Shift+F,
Shift+A), display modes 4-7, smooth preview 1-3, [ ] view undo, Space hotbox, Home, +/- manipulator size, Alt+arrows,
emulated 3-button tumble. Run by ``maya_patches.apply`` in ``PATCHES`` order; shared state: ``maya_patches_base``.
``IC:<line>`` = a line of ``$S\\presets\\keyconfig\\keymap_data\\industry_compatible_data.py``.
"""

from .patch import make_event
from .maya_patches_base import _PAINT_MODES, SLIDER_TOOL_KEYMAPS, VIEW3_SHADOWS, _add


# --- 2. 4/5/6/7 display modes ---------------------------------------------
# Maya: 4 wireframe, 5 shaded, 6 shaded+textured, 7 all lights
# (Maya hotkeys 4..7).

DISPLAY_KEYS = (("FOUR", "WIREFRAME"), ("FIVE", "SHADED"),
                ("SIX", "TEXTURED"), ("SEVEN", "LIGHTS"))


def patch_display(kd):
    # IC:3458-3459 "Object Non-modal": 4 = object mode, 5 = mode pie.
    kd.remove("Object Non-modal", "object.mode_set", type="FOUR")
    kd.remove("Object Non-modal", "wm.call_menu_pie", type="FIVE")
    for key, mode in DISPLAY_KEYS:
        _add(kd, "3D View", "allset.display_mode", make_event(key), {"mode": mode})
    # Losing 4 = object mode leaves no quick way out of edit mode; Maya's F8
    # toggles object <-> last component mode.
    # allset.toggle_sel_mode = editmode_toggle + Maya's in-view message.
    _add(kd, "Object Non-modal", "allset.toggle_sel_mode", make_event("F8"))


# --- 4. Space reserved for the hotbox ---------------------------------------
# Maya Space = hotbox (Space shows the hotbox),
# Space does nothing in other editors.
# Playback moves to Maya's Alt+V (PlaybackToggle) and Alt+Shift+V (GoToMinFrame).

def patch_space(kd):
    kd.remove("Frames", "screen.animation_play", type="SPACE")  # IC:2258
    _add(kd, "Frames", "allset.play", make_event("V", alt=True))       # Blender's play, from the viewport
    _add(kd, "Frames", "screen.frame_jump", make_event("V", alt=True, shift=True), {"end": False})


# --- 9. Camera: ortho tumble lock, framing in all views ----------------------
# Maya: Alt+LMB tumble, Shift+F / Shift+A framing.

def patch_camera(kd):
    kd.remove("3D View", "view3d.rotate", type="LEFTMOUSE", alt=True)       # IC:674
    _add(kd, "3D View", "allset.tumble", make_event("LEFTMOUSE", alt=True))
    # Maya's tumble never snaps. Blender's rotate snaps to the nearest axis view when Alt is pressed during the drag
    # and then turns a perspective view orthographic; Alt is the tumble key itself, so pressing it again mid-drag
    # locked the persp view like a top / front / side view (#288).
    for snap in ("AXIS_SNAP_ENABLE", "AXIS_SNAP_DISABLE"):
        kd.remove("View3D Rotate Modal", snap)
    # Alt+LMB+MMB = dolly, whichever button comes first (#325), and letting go of one of them carries on with the
    # button still held (#343): the kit's tumble / track / chord dolly start a watcher that starts the next navigation
    # on each press / release of these two buttons, and the running one ends on that event. A tumble / track the
    # watcher starts on a release ends on the release of the button still held.
    kd.remove("3D View", "view3d.move", type="MIDDLEMOUSE", alt=True)
    _add(kd, "3D View", "allset.track_view", make_event("MIDDLEMOUSE", alt=True))
    for km, other, held in (("View3D Rotate Modal", "MIDDLEMOUSE", "LEFTMOUSE"),
                            ("View3D Move Modal", "LEFTMOUSE", "MIDDLEMOUSE")):
        kd.add(km, "CONFIRM", make_event(other, any=True))
        kd.add(km, "CONFIRM", make_event(other, "DOUBLE_CLICK", any=True))     # a quick second press
        kd.add(km, "CONFIRM", make_event(held, "RELEASE", any=True))
    # through a camera the chord dolly is Blender's zoom: it ends when either button is let go
    for button in ("LEFTMOUSE", "MIDDLEMOUSE"):
        kd.add("View3D Zoom Modal", "CONFIRM", make_event(button, "RELEASE", any=True))
    # Alt+RMB dolly reads the drag itself: Blender's zoom axis is a preference the kit no longer sets (#51)
    kd.remove("3D View", "view3d.zoom", type="RIGHTMOUSE", alt=True)       # IC:433
    _add(kd, "3D View", "allset.dolly", make_event("RIGHTMOUSE", alt=True),
         shadows=("Image Paint", "Vertex Paint", "Sculpt"))     # their Alt+RMB stencil control stays, as before
    # UV / Image Editor: a dolly instead of IC image.view_zoom (Zoom Axis preference): right / down = in, left / up
    # = out. Graph Editor / Dope Sheet / NLA keep View2D view2d.zoom: it zooms each axis by its own drag (right = in;
    # their rows never zoom), no preference involved.
    kd.remove("Image", "image.view_zoom", type="RIGHTMOUSE", alt=True)
    _add(kd, "Image", "allset.dolly_2d", make_event("RIGHTMOUSE", alt=True), shadows=("View2D",))  # Image runs first
    # 2D editors: Alt+LMB+MMB zooms like Alt+RMB, whichever button comes first (#325). The kit's modal runs the whole
    # Alt+LMB / Alt+MMB drag (it pans like the pan it sits in front of): in View2D for the Graph Editor, Dope Sheet,
    # NLA and Node Editor, in "Image" for the UV / Image Editor. Its poll keeps the editor's own pan in every other
    # editor, the Time Slider and the kit's rows.
    for button in ("LEFTMOUSE", "MIDDLEMOUSE"):
        _add(kd, "View2D", "allset.nav_2d", make_event(button, alt=True), first=True,
             shadows=("View2D", "View2D Buttons List"))
        _add(kd, "Image", "allset.nav_2d", make_event(button, alt=True), first=True, shadows=("Image", "View2D"))
    # Node Editor Alt+RMB: zoom by the left / right drag only (Blender's view2d.zoom reads the Zoom Axis preference
    # there); the item passes Alt+RMB on to view2d.zoom in the other View2D editors
    _add(kd, "View2D", "allset.nav_2d", make_event("RIGHTMOUSE", alt=True), first=True,
         shadows=("View2D", "View2D Buttons List"))
    kd.remove("3D View", "view3d.view_center_pick", type="F", shift=True)
    _add(kd, "3D View", "allset.frame_all_views", make_event("F", shift=True), {"selected": True})
    # Maya fit (factor 0.95, sidebar excluded) for F and Ctrl+Shift+F (with children);
    # A tap goes through taphold.SelectAllBinding.
    kd.remove("3D View", "view3d.view_selected", type="F")                  # IC:681
    # Mode keymaps run before the general 3D View keymap. Another addon's
    # Object/Mesh F menu would consume the key before Frame Selection runs.
    # Mode-local aliases also participate in the existing Maya priority watcher;
    # the foreign bindings remain available when Maya mode is turned off.
    frame_maps = ("3D View", "Object Mode", "Mesh")
    for km in frame_maps:
        _add(kd, km, "allset.frame", make_event("F"), {"selected": True}, shadows=frame_maps)
    _add(kd, "3D View", "allset.frame_all_views", make_event("F", shift=True, ctrl=True),
         {"selected": True, "children": True})
    kd.remove("3D View", "view3d.view_all", type="A", shift=True)
    _add(kd, "3D View", "allset.frame_all_views", make_event("A", shift=True), {"selected": False},
         shadows=("Sculpt",))


# --- 10. View-change undo: [ ] and Alt+Z / Alt+Y ----------------------------
# Maya hotkeys. IC [ ] = select_hierarchy
# (IC:2506-2512), replaced by the arrow pick-walk. Paint modes keep
# [ ] for brush size.

def patch_view_history(kd):
    kd.remove("Object Mode", "object.select_hierarchy", type="LEFT_BRACKET")
    kd.remove("Object Mode", "object.select_hierarchy", type="RIGHT_BRACKET")
    for ev, direction in ((make_event("LEFT_BRACKET"), "UNDO"), (make_event("RIGHT_BRACKET"), "REDO"),
                          (make_event("Z", alt=True), "UNDO"), (make_event("Y", alt=True), "REDO")):
        _add(kd, "3D View", "allset.view_history", ev, {"direction": direction},
             shadows=_PAINT_MODES + ("Armature",))


# --- 11. Space tap = four views, Ctrl+Space = full screen -------------------
# Maya: Space tap = four views. Space hold = hotbox.

# Space = hotbox (tap = pane toggle, Maya hotbox). Also in the editors
# the hotbox South zone switches a pane to, so the hotbox can switch it back; Space is
# free there since patch_space (IC used it only in "Frames"). Not in text editors.
HOTBOX_KEYMAPS = ("3D View", "Outliner", "Graph Editor", "Dopesheet", "Node Editor", "Image")


def patch_space_tap(kd):
    for km in HOTBOX_KEYMAPS:
        _add(kd, km, "allset.hotbox", make_event("SPACE"))
    _add(kd, "Screen", "screen.screen_full_area", make_event("SPACE", ctrl=True),
         {"use_hide_panels": True})


# --- 12. 1/2/3 smooth mesh preview -------------------------------------------
# Maya 1/2/3 = smooth mesh preview levels. IC 1/2/3 = component modes
# (IC:2558-2563 Object Mode, IC:164-177 Mesh), now on F9-F11.

SMOOTH_KEYS = (("ONE", 1), ("TWO", 2), ("THREE", 3))


def patch_smooth_preview(kd):
    for key, level in SMOOTH_KEYS:
        kd.remove("Object Mode", "object.mode_set_with_submode", type=key)
        kd.remove("Mesh", "mesh.select_mode", type=key)
        for km in ("Object Mode", "Mesh"):
            _add(kd, km, "allset.smooth_preview", make_event(key), {"level": level})


# --- 23. Manipulator size, smoothing level, default view, wireframe on shaded -------------------
# Maya hotkeys = Shift++ - (numpad + - too), PgUp/PgDn, 0, Home, Alt+5.

def patch_view_keys(kd):
    # A Maya keyboard's numpad + / - are the same keys (IC: numpad zoom in / out; Shift = dolly stays).
    for key in ("NUMPAD_PLUS", "NUMPAD_MINUS"):
        kd.remove("3D View", "view3d.zoom", type=key, repeat=True)
    for ev, factor in ((make_event("EQUAL"), 1.25), (make_event("EQUAL", shift=True), 1.25),
                       (make_event("MINUS"), 0.8), (make_event("NUMPAD_PLUS"), 1.25),
                       (make_event("NUMPAD_MINUS"), 0.8)):
        _add(kd, "3D View", "allset.manip_size", ev, {"factor": factor})
    # Text edit mode keeps Home = line start (Font keymap runs first).
    _add(kd, "3D View", "allset.view_home", make_event("HOME"), shadows=("Font",))
    _add(kd, "3D View", "wm.context_toggle", make_event("FIVE", alt=True),
         {"data_path": "space_data.overlay.show_wireframes"})
    for km in ("Object Mode", "Mesh"):
        _add(kd, km, "allset.smooth_level", make_event("PAGE_UP", repeat=True), {"delta": 1})
        _add(kd, km, "allset.smooth_level", make_event("PAGE_DOWN", repeat=True), {"delta": -1})
        _add(kd, km, "allset.smooth_preview", make_event("ZERO"), {"level": 1})


# --- 42. View keys 3 -----------------------------------------------------------------------------
# Maya hotkeys Alt+p, Alt+a, Alt+arrows, `, backslash. All in "3D View" (Maya's model
# panel); the same events elsewhere belong to other editors / modes, whose keymaps run first.


PIXEL_MOVE_KEYS = (("UP_ARROW", 0, 1), ("DOWN_ARROW", 0, -1), ("LEFT_ARROW", -1, 0), ("RIGHT_ARROW", 1, 0))


def patch_view_keys_3(kd):
    for km in ("Vertex Paint", "Weight Paint"):   # Blender 5.3 Alt+A pie; Maya's Alt+A wins in the kit
        kd.remove(km, "wm.call_menu_pie", optional=True, type="A", alt=True)
    _add(kd, "3D View", "allset.cycle_display", make_event("A", alt=True), shadows=VIEW3_SHADOWS)
    _add(kd, "3D View", "allset.camera_mode_toggle", make_event("P", alt=True), shadows=VIEW3_SHADOWS)
    for key, dx, dy in PIXEL_MOVE_KEYS:
        _add(kd, "3D View", "allset.pixel_move", make_event(key, alt=True, repeat=True), {"dx": dx, "dy": dy},
             shadows=VIEW3_SHADOWS)
    kd.remove("Object Non-modal", "object.transfer_mode", type="ACCENT_GRAVE")
    _add(kd, "3D View", "allset.tweak_hold", make_event("ACCENT_GRAVE"), shadows=VIEW3_SHADOWS)
    _add(kd, "3D View", "allset.pan_zoom_hold", make_event("BACK_SLASH"), shadows=VIEW3_SHADOWS)


# --- Alt+LMB tumble under Emulate 3 Button Mouse (#242) ------------------------------------------------------
# Blender turns Alt+LMB into a plain middle drag before any key map sees it. While the Alt key is still held that
# drag tumbles (a real middle drag passes through). It goes first wherever the kit's middle drag items run before
# "3D View" (tool keymaps: Maya's middle drag on the manipulator; Object Mode / Pose: the Channel Box slider), so
# this patch runs last.

EMULATED_TUMBLE_KEYMAPS = SLIDER_TOOL_KEYMAPS + ("Object Mode", "Pose", "3D View")


def patch_emulated_tumble(kd):
    for km in EMULATED_TUMBLE_KEYMAPS:
        _add(kd, km, "allset.emulated_tumble", make_event("MIDDLEMOUSE"), first=True,
             shadows=("Image Paint", "Object Mode", "Pose", "Mesh") if km == "3D View" else (km, "3D View"))
