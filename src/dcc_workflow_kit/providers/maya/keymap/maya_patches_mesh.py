# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya component-mode keys: mesh components (convert, grow / shrink, extrude, bevel, loop pick, delete, pick-walk),
F7-F11 modes, UV Editor keys, and ``patch_key_batch_3`` (one batch over many modes / editors: symmetry, F1, paint /
sculpt). Run by ``maya_patches.apply`` in ``PATCHES`` order; shared state: ``maya_patches_base``. ``IC:<line>`` = a
line of ``$S\\presets\\keyconfig\\keymap_data\\industry_compatible_data.py``.
"""

from . import patch
from .patch import make_event
from .maya_patches_base import PICK_WALK_KEYS, UV_KM, VIEW3_SHADOWS, _add


# --- 13. F7/F9/F10/F11 component modes ---------------------------------------
# Maya F8 / F9-F11 component modes. F8 = editmode_toggle (patch 2).

COMPONENT_KEYS = (("F9", "VERT"), ("F10", "EDGE"), ("F11", "FACE"), ("F7", "MULTI"))


def patch_component_keys(kd):
    for key, comp in COMPONENT_KEYS:
        _add(kd, "Object Non-modal", "allset.component_mode", make_event(key), {"type": comp})


# --- 19. Mesh component keys --------------------------------------------------
# Maya: Ctrl+Shift+A / Alt+D, Ctrl+F9-F11 convert, > < (grow / shrink,
# Ctrl: along loop), D component pivot; Maya hotkeys Ctrl+E extrude, Ctrl+B bevel.

CONVERT_KEYS = (("F9", "VERT"), ("F10", "EDGE"), ("F11", "FACE"))
# Maya Grow / Shrink Selection = the ">" / "<" characters. On a US keyboard they are Shift+. / Shift+,; keyboards
# with a key of their own for < > (Blender's GRLESS) type "<" plain and ">" with Shift. Mesh components and UVs.
GROW_KEYS = (make_event("PERIOD", shift=True, repeat=True), make_event("GRLESS", shift=True, repeat=True))
SHRINK_KEYS = (make_event("COMMA", shift=True, repeat=True), make_event("GRLESS", repeat=True))
GROW_SHRINK = (("Mesh", "allset.grow_selection", "allset.shrink_selection"),
               ("UV Editor", "uv.select_more", "uv.select_less"))


def patch_mesh_components(kd):
    kd.remove("Mesh", "wm.tool_set_by_id", type="D")                       # annotate tool
    _add(kd, "Mesh", "allset.hold", make_event("D"), {"name": "component_pivot"})
    # Insert = the same pivot edit as a toggle
    _add(kd, "Mesh", "allset.pivot_toggle", make_event("INSERT"))
    # #160: D held / Insert on joints in Edit mode = Maya Preserve Children (move the joint only,
    # like Maya's `move -pcp`)
    kd.remove("Armature", "wm.tool_set_by_id", type="D")                   # annotate tool
    _add(kd, "Armature", "allset.hold", make_event("D"), {"name": "preserve_children"})
    _add(kd, "Armature", "allset.pivot_toggle", make_event("INSERT"))
    kd.remove("Mesh", "mesh.select_all", type="A", ctrl=True, shift=True)   # IC: deselect
    _add(kd, "Mesh", "mesh.select_all", make_event("A", ctrl=True, shift=True), {"action": 'SELECT'})
    _add(kd, "Mesh", "allset.select_none", make_event("D", alt=True))
    kd.remove("Mesh", "wm.tool_set_by_id", type="E", ctrl=True)            # extrude tool
    # Maya polyExtrudeFace: zero-length extrusion + manipulator / In-View Editor; edges and
    # vertices = polyExtrudeEdge / polyExtrudeVertex at once. Ctrl+B = polyBevel3 at once.
    _add(kd, "Mesh", "allset.extrude", make_event("E", ctrl=True))
    kd.remove("Mesh", "wm.tool_set_by_id", type="B", ctrl=True)            # bevel tool
    _add(kd, "Mesh", "allset.bevel", make_event("B", ctrl=True))
    _add(kd, "Object Mode", "allset.bevel", make_event("B", ctrl=True))      # Maya: every edge of the selected meshes
    for km, more, less in GROW_SHRINK:
        for event in GROW_KEYS:
            _add(kd, km, more, event)
        for event in SHRINK_KEYS:
            _add(kd, km, less, event)
    _add(kd, "Mesh", "mesh.select_next_item", make_event("PERIOD", shift=True, ctrl=True, repeat=True))
    _add(kd, "Mesh", "mesh.select_prev_item", make_event("COMMA", shift=True, ctrl=True, repeat=True))
    for key, comp in CONVERT_KEYS:
        _add(kd, "Mesh", "allset.convert_selection", make_event(key, ctrl=True), {"type": comp})
    # Maya double-click = loop, Shift+double-click = the run between two picks (issue #22, operators/loop_pick.py);
    # IC's own double-click loop picks (Shift = add the loop) give way, Ctrl (deselect the loop) stays
    for shift in (False, True):
        kd.remove("Mesh", "mesh.loop_select", type="LEFTMOUSE", value="DOUBLE_CLICK", shift=shift)
        _add(kd, "Mesh", "allset.loop_pick", make_event("LEFTMOUSE", value="DOUBLE_CLICK", shift=shift),
             {"between": shift}, shadows=("Screen",))


# --- 22. Delete / Backspace on components -------------------------------------------
# Maya deletes the selected faces / edges / vertices right away (edges: their vertices stay; vertices: only those
# with two edges); IC opens the Delete menu (IC:3061-3062). Ctrl+Delete / Ctrl+Backspace = Edit Mesh > Delete
# Edge/Vertex (allset.delete_edge_vertex: edges go and the vertices they leave with two edges are cleaned up),
# in place of IC's mesh.dissolve_mode.

def patch_component_delete(kd):
    for key in ("DEL", "BACK_SPACE"):
        kd.remove("Mesh", "wm.call_menu", type=key)
        _add(kd, "Mesh", "allset.delete_components", make_event(key))
        kd.remove("Mesh", "mesh.dissolve_mode", type=key, ctrl=True)
        _add(kd, "Mesh", "allset.delete_edge_vertex", make_event(key, ctrl=True))


# --- 28. Component pick-walk, Alt+Shift axis-locked navigation -------------------------
# Arrows in edit mode walk vertices / edges / faces (Maya arrow keys, Maya pick-walk); IC's Up/Down
# grow/shrink go (Maya: Shift+> / <). Alt+Shift+LMB / MMB = tumble / track on one axis
# (Maya); IC's Alt+Shift+LMB click-select toggle goes (a PRESS item would hide it anyway).

AXIS_LOCK_SHADOWS = ("Weight Paint", "Paint Face Mask (Weight, Vertex, Texture)",
                     "Paint Vertex Selection (Weight, Vertex)")


def patch_component_pick_walk(kd):
    kd.remove("Mesh", "mesh.select_more", type="UP_ARROW")
    kd.remove("Mesh", "mesh.select_less", type="DOWN_ARROW")
    for key, direction in PICK_WALK_KEYS:
        _add(kd, "Mesh", "allset.pick_walk_component", make_event(key, repeat=True),
             {"direction": direction})
    kd.remove("3D View", "view3d.select", type="LEFTMOUSE", value="CLICK", shift=True, alt=True)
    # Paint modes keep their own Alt+Shift+LMB select (they run before 3D View).
    _add(kd, "3D View", "allset.view_axis_lock", make_event("LEFTMOUSE", shift=True, alt=True),
         {"mode": "TUMBLE"}, shadows=AXIS_LOCK_SHADOWS)
    _add(kd, "3D View", "allset.view_axis_lock", make_event("MIDDLEMOUSE", shift=True, alt=True),
         {"mode": "TRACK"})


# --- 33. Multi-Cut: a kit tool (operators/multi_cut.py, ui/mesh_tools.py) whose own tool keymap has
# Maya's Ctrl / Shift / Backspace handling, so Blender's knife keeps its own keys (no knife patches).


# --- 34. UV workflow ------------------------------------------------------------------
# Maya UV Editor keys, F12 / Alt+F12. IC's UV Editor: Shift+X = snap pie (IC:613),
# Ctrl+L = select_linked (IC:599), RMB = context menu (IC:614); Maya has no shell-select key there.


def patch_uv(kd):
    kd.remove(UV_KM, "wm.call_menu", type="RIGHTMOUSE")
    for trigger, mods in (("RMB", {}), ("SHIFT_RMB", {"shift": True}), ("CTRL_RMB", {"ctrl": True}),
                          ("TOOL_OPTIONS", {"ctrl": True, "shift": True})):
        _add(kd, UV_KM, "allset.marking_menu", make_event("RIGHTMOUSE", **mods), {"trigger": trigger})
    kd.remove(UV_KM, "wm.call_menu_pie", type="X", shift=True)
    kd.remove(UV_KM, "uv.select_linked", type="L", ctrl=True)
    _add(kd, UV_KM, "allset.uv_cut", make_event("X", shift=True))
    _add(kd, UV_KM, "allset.uv_sew", make_event("S", shift=True))
    _add(kd, UV_KM, "allset.uv_unfold", make_event("U", ctrl=True))
    _add(kd, UV_KM, "allset.uv_layout", make_event("L", ctrl=True))
    # double-click = UV edge loop (Ctrl: edge ring), on a UV / UV face its shell; Shift adds (operators/uv_loop_pick.py).
    # IC's own double-click loop picks give way
    for shift in (False, True):
        kd.remove(UV_KM, "uv.select_loop", type="LEFTMOUSE", value="DOUBLE_CLICK", shift=shift)
        for ctrl in (False, True):
            _add(kd, UV_KM, "allset.uv_loop_pick", make_event("LEFTMOUSE", value="DOUBLE_CLICK", shift=shift, ctrl=ctrl),
                 {"extend": shift, "ring": ctrl}, shadows=("Screen",))
    # Ctrl+Up / Ctrl+Down = checker density up / down (whole steps, at least 1)
    _add(kd, UV_KM, "allset.checker_density", make_event("UP_ARROW", ctrl=True), {"step": 1})
    _add(kd, UV_KM, "allset.checker_density", make_event("DOWN_ARROW", ctrl=True), {"step": -1})
    for km in ("Object Mode", "Mesh"):
        _add(kd, km, "allset.uv_component", make_event("F12"), {"mode": 'UV'},
             shadows=("Screen",))      # Screen F12 = Blender render, Maya's F12 wins in the 3D View
        _add(kd, km, "allset.uv_component", make_event("F12", alt=True), {"mode": 'SHELL'})


# --- 49. Key batch 3: wrong daily keys, missing keys ----------------------------------------------------
# Maya hotkeys: Alt+r ToggleReflection, Ctrl+i, F1 Help, Alt+c ToggleColorFeedback,
# m ModifyDisplacement, Ctrl+PgUp / PgDn PickWalkIn / Out, Ctrl+, PrevSkinPaintMode,
# Ctrl+m / Shift+M / Ctrl+Shift+M menu bars, Alt+b, paint u / n / Alt+f / Ctrl+Alt+c / v,
# sculpt Ctrl+0-9, f, b, m, Shift+U, Ctrl+Shift+I, Graph Editor h / j, Time Slider
# bookmarks, Ctrl+f, Ctrl+Shift+% Use Default Material, UV Editor 7 / 5.

MODE_KEYMAPS = ("Object Mode", "Mesh", "Pose", "Curve", "Curves", "Armature", "Metaball", "Lattice", "Particle",
                "Paint Face Mask (Weight, Vertex, Texture)", "Paint Vertex Selection (Weight, Vertex)")
SCULPT_BRUSHES = (("ZERO", "Mask"), ("ONE", "Draw"), ("TWO", "Smooth"), ("THREE", "Relax Slide"), ("FOUR", "Grab"),
                  ("FIVE", "Pinch/Magnify"), ("SIX", "Flatten/Contrast"), ("SEVEN", "Blob"), ("EIGHT", "Draw Sharp"),
                  ("NINE", "Layer"))
SCULPT_LIBRARY = "brushes/essentials_brushes-mesh_sculpt.blend/Brush/"
SEARCH_SHADOWS = ("Property Editor", "Outliner", "Graph Editor Generic", "Node Editor", "Dopesheet", "NLA Generic",
                  "Text Generic", "Animation Channels", "Image Paint", "Vertex Paint", "Weight Paint", "Sculpt",
                  "Grease Pencil Weight Paint",
                  "Preferences", "Preferences_nav")   # Blender 5.x: Ctrl+F filter in Preferences
BOOKMARK_KEYS = (("T", {"alt": True}, "allset.bookmark_create", {}),
                 ("T", {"alt": True, "shift": True}, "allset.bookmark_create", {"quick": True}),
                 ("QUOTE", {}, "allset.bookmark_go", {}),
                 ("SEMI_COLON", {}, "allset.bookmark_go", {"previous": True}),
                 ("BACK_SLASH", {"shift": True}, "allset.bookmark_frame", {"which": "CURRENT"}),
                 ("QUOTE", {"shift": True}, "allset.bookmark_frame", {"which": "NEXT"}),
                 ("SEMI_COLON", {"shift": True}, "allset.bookmark_frame", {"which": "PREVIOUS"}))


def _props_of(kd, km, idname, **ev):
    """Properties of the first matching item (to copy IC's radial-control settings onto a Maya key)."""
    found = kd.find(km, idname, **ev)
    return patch.props_dict(found[0][2]) if found else {}


def _remove_where(kd, km, predicate, **ev):
    if km not in kd.keymap_names():
        return []
    items = kd.items(km)
    found = [it for it in kd.find(km, **ev) if predicate(it)]
    items[:] = [it for it in items if not any(it is f for f in found)]
    return found


def patch_key_batch_3(kd):
    # Alt+R: IC clear scale -> Maya reflection (symmetry) toggle
    kd.remove("Object Mode", "object.scale_clear", type="R", alt=True)
    kd.remove("Pose", "pose.scale_clear", type="R", alt=True)
    # (weight paint has its own Alt+R = Maya's paint Reflection toggle)
    _add(kd, "3D View", "allset.symmetry", make_event("R", alt=True), {"mode": "TOGGLE"},
         shadows=(*VIEW3_SHADOWS, "Weight Paint"))
    # Ctrl+I: IC invert in the 3D modes (Maya Ctrl+I = next intermediate object; Ctrl+Shift+I still inverts)
    for km in MODE_KEYMAPS:
        _remove_where(kd, km, lambda it: it[0].endswith("select_all"), type="I", ctrl=True)
    # F1: Maya Help = Blender's manual for the button under the mouse
    kd.remove("3D View", "view3d.view_axis", type="F1")
    kd.remove("Image", "image.view_zoom_ratio", type="F1")
    _add(kd, "Window", "wm.doc_view_manual_ui_context", make_event("F1"))
    # Alt+C: IC loop cut tool -> Maya colour feedback while painting skin weights
    kd.remove("Mesh", "wm.tool_set_by_id", type="C", alt=True)
    _add(kd, "Weight Paint", "allset.color_feedback", make_event("C", alt=True))
    # m: IC Measure tool in every 3D mode -> Maya displacement / strength drag (sculpt)
    for km in MODE_KEYMAPS:
        _remove_where(kd, km, lambda it: it[0] == "wm.tool_set_by_id"
                      and patch.props_dict(it[2]).get("name") == "builtin.measure", type="M")
    # Ctrl+PgUp / PgDn: IC workspace cycle -> Maya pick-walk in / out (down / up the hierarchy)
    kd.remove("Screen", "screen.workspace_cycle", type="PAGE_UP", ctrl=True)
    kd.remove("Screen", "screen.workspace_cycle", type="PAGE_DOWN", ctrl=True)
    for km, op in (("Object Mode", "object.select_hierarchy"), ("Pose", "pose.select_hierarchy")):
        _add(kd, km, op, make_event("PAGE_UP", ctrl=True), {"direction": "CHILD", "extend": False})
        _add(kd, km, op, make_event("PAGE_DOWN", ctrl=True), {"direction": "PARENT", "extend": False})
    # Ctrl+,: IC Preferences (Maya on Windows opens them from Windows > Settings/Preferences only)
    kd.remove("Screen", "screen.userpref_show", type="COMMA", ctrl=True)

    # menu bars and background
    # Blender 5.3 Grease Pencil Draw Mode Ctrl+M mirror; Maya's Ctrl+M wins in the kit
    kd.remove("Grease Pencil Draw Mode", "transform.mirror", optional=True, type="M", ctrl=True)
    _add(kd, "Screen", "allset.main_menubar_toggle", make_event("M", ctrl=True), shadows=("Grease Pencil Edit Mode",))
    _add(kd, "Screen", "wm.context_toggle", make_event("M", shift=True), {"data_path": "area.show_menus"},
         shadows=("Sequencer",))
    _add(kd, "3D View", "wm.context_toggle", make_event("M", ctrl=True, shift=True),
         {"data_path": "space_data.show_region_header"}, shadows=VIEW3_SHADOWS)
    _add(kd, "3D View", "allset.cycle_background", make_event("B", alt=True), shadows=VIEW3_SHADOWS)
    _add(kd, "3D View", "allset.panel_set", make_event("FIVE", ctrl=True, shift=True), {"key": "DEFAULT_MATERIAL"},
         shadows=VIEW3_SHADOWS)
    # editors with their own Ctrl+F (find / filter, paint radial controls) keep it
    _add(kd, "Screen", "wm.search_menu", make_event("F", ctrl=True), shadows=SEARCH_SHADOWS)

    # skin weight painting
    size = _props_of(kd, "Weight Paint", "wm.radial_control", type="S")
    weight = _props_of(kd, "Weight Paint", "wm.radial_control", type="F", ctrl=True)
    kd.remove("Weight Paint", "wm.radial_control", type="U")
    kd.remove("Weight Paint", "wm.call_asset_shelf_popover", type="B")
    _add(kd, "Weight Paint", "wm.call_menu", make_event("U"), {"name": "ALLSET_MT_paint_operation"})
    _add(kd, "Weight Paint", "wm.radial_control", make_event("N"), weight)
    _add(kd, "Weight Paint", "wm.radial_control", make_event("B"), size, shadows=("3D View",))
    # Alt+F = Maya Flood, Ctrl+Alt+C / V = copy /
    # paste vertex weights, Ctrl+. / Ctrl+, = next / previous Skin Paint Mode, Alt+R = reflection (X mirror)
    _add(kd, "Weight Paint", "allset.flood_weights", make_event("F", alt=True))
    _add(kd, "Weight Paint", "allset.paint_copy_vertex_weights", make_event("C", ctrl=True, alt=True))
    _add(kd, "Weight Paint", "allset.paint_paste_vertex_weights", make_event("V", ctrl=True, alt=True))
    _add(kd, "Weight Paint", "allset.skin_paint_mode", make_event("PERIOD", ctrl=True), {"step": 1})
    _add(kd, "Weight Paint", "allset.skin_paint_mode", make_event("COMMA", ctrl=True), {"step": -1})
    _add(kd, "Weight Paint", "allset.paint_reflection", make_event("R", alt=True), shadows=("3D View",))
    _add(kd, "Mesh", "allset.copy_vertex_weights", make_event("C", ctrl=True, alt=True))
    _add(kd, "Mesh", "allset.paste_vertex_weights", make_event("V", ctrl=True, alt=True))

    # sculpting
    size = _props_of(kd, "Sculpt", "wm.radial_control", type="S")
    strength = _props_of(kd, "Sculpt", "wm.radial_control", type="U")
    for n in range(6):
        kd.remove("Sculpt", "object.subdivision_set", type=("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE")[n],
                  ctrl=True)
    for key, brush in SCULPT_BRUSHES:
        _add(kd, "Sculpt", "brush.asset_activate", make_event(key, ctrl=True),
             {"asset_library_type": "ESSENTIALS", "relative_asset_identifier": SCULPT_LIBRARY + brush},
             shadows=("3D View",))
    kd.remove("Sculpt", "wm.call_asset_shelf_popover", type="B")
    _add(kd, "Sculpt", "wm.radial_control", make_event("B"), size, shadows=("3D View",))
    _add(kd, "Sculpt", "wm.radial_control", make_event("M"), strength)
    _add(kd, "Sculpt", "paint.mask_flood_fill", make_event("U", shift=True), {"mode": "VALUE", "value": 0.0})
    _add(kd, "Sculpt", "paint.mask_flood_fill", make_event("I", ctrl=True, shift=True), {"mode": "INVERT"})

    # Graph Editor lock / unlock channel
    _add(kd, "Graph Editor", "anim.channels_setting_enable", make_event("H"), {"type": "PROTECT"})
    _add(kd, "Graph Editor", "anim.channels_setting_disable", make_event("J"), {"type": "PROTECT"})

    # Maya 2026 Dope Sheet keys (g / t / h / j, like the Graph Editor's); a / f are IC's
    # action.view_all / view_selected. allset.dope_sheet_key fails its poll in the Timeline, so the Time Slider keeps
    # the window keys (g = Repeat Last)
    for key, action in (("G", 'RANGE'), ("T", 'CENTER'), ("H", 'LOCK'), ("J", 'UNLOCK')):
        _add(kd, "Dopesheet", "allset.dope_sheet_key", make_event(key), {"action": action},
             shadows=("Screen",) if key == "G" else ())

    # Time Slider bookmarks = timeline markers (operators/bookmarks.py)
    for key, mods, op, props in BOOKMARK_KEYS:
        _add(kd, "Screen", op, make_event(key, **mods), props, shadows=("Clip Editor", "Clip Graph Editor", "Curve"))

    # UV Editor display toggles
    _add(kd, "UV Editor", "wm.context_toggle", make_event("SEVEN"), {"data_path": "space_data.uv_editor.show_stretch"})
    # Maya UV Editor keys (ui/uv_display.py, operators/uv_shells.py). IC's UV Editor 4 (island select
    # mode) and Ctrl+1 (vertex select mode) go: Maya's UV component keys are F9-F12 (Maya hotkeys).
    if kd.find("UV Editor", "uv.select_mode", type="FOUR"):
        kd.remove("UV Editor", "uv.select_mode", type="FOUR")
    else:       # 5.x IC: island picking is a toggle of tool_settings.use_uv_select_island on the same key
        kd.remove("UV Editor", "wm.context_toggle", type="FOUR")
    kd.remove("UV Editor", "mesh.select_mode", type="ONE", ctrl=True)
    for key, mode in (("FOUR", 'WIREFRAME'), ("FIVE", 'SHADED'), ("SIX", 'IMAGE'), ("EIGHT", 'SHELL_BORDERS'),
                      ("NINE", 'TEXTURE_BORDERS')):
        _add(kd, "UV Editor", "allset.uv_display", make_event(key), {"mode": mode})
    _add(kd, "UV Editor", "allset.uv_isolate", make_event("ONE", ctrl=True))          # macOS: Cmd+1 too
    _add(kd, "UV Editor", "allset.uv_delete", make_event("DEL"))
    _add(kd, "UV Editor", "allset.uv_create_shell", make_event("X", ctrl=True, shift=True))


def patch_weight_paint_exit(kd):
    """Maya's Q/W/E/R change the global tool, leaving weight painting."""
    for key, tool in (('Q', 'builtin.select_box'), ('W', 'builtin.move'),
                      ('E', 'builtin.rotate'), ('R', 'builtin.scale')):
        _remove_where(kd, 'Weight Paint', lambda it: it[0] == 'wm.tool_set_by_id', type=key)
        _add(kd, 'Weight Paint', 'allset.weight_paint_exit', make_event(key),
             {'tool': tool}, first=True, shadows=('3D View',))
