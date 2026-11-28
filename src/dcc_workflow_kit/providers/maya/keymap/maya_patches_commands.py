# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya command keys in Object Mode, joints and the global Screen / Window keymaps: parent, group, duplicate, delete,
hide / show, isolate, undo, Ctrl+A, marking menus and Q/W/E/R/T tools, F2-F6 menu sets, scene files, G repeat, F12
render. Run by ``maya_patches.apply`` in ``PATCHES`` order; shared state: ``maya_patches_base``. ``IC:<line>`` = a
line of ``$S\\presets\\keyconfig\\keymap_data\\industry_compatible_data.py``.
"""

from .patch import make_event
from .maya_patches_base import PICK_WALK_KEYS, UV_KM, VIEW3_SHADOWS, _add


# --- 3. Ctrl+G group --------------------------------------------------------
# Maya Ctrl+G = group under common parent, pivot at origin.
# IC Ctrl+G = move to collection (IC:2547; Blender 5.x: the same as a
# wm.call_menu of OBJECT_MT_move_to_collection), so the item is removed whatever its operator.

def patch_group(kd):
    for km in ("Object Mode", "Outliner"):
        kd.remove(km, None, type="G", ctrl=True)
        _add(kd, km, "allset.group", make_event("G", ctrl=True))
    # A picked joint (pose mode, or skeleton edit mode with the Move tool): its skeleton goes under the group.
    for km in ("Pose", "Armature"):
        _add(kd, km, "allset.group", make_event("G", ctrl=True))


# --- 8. Arrow-key pick-walk (object mode) -----------------------------------
# Maya hotkeys. IC puts Left/Right frame
# stepping into each mode keymap (IC:93-97 _template_items_animation); only
# Object Mode's copy is replaced. Maya steps frames with Alt+,/..


def patch_pick_walk(kd):
    kd.remove("Object Mode", "object.select_more", type="UP_ARROW")
    kd.remove("Object Mode", "object.select_less", type="DOWN_ARROW")
    kd.remove("Object Mode", "screen.frame_offset", type="LEFT_ARROW")
    kd.remove("Object Mode", "screen.frame_offset", type="RIGHT_ARROW")
    for key, direction in PICK_WALK_KEYS:
        _add(kd, "Object Mode", "allset.pick_walk", make_event(key, repeat=True),
             {"direction": direction})


# --- 15. Marking menus (pies) and Q/W/E/R hold + LMB ---------------------------
# Maya marking menus. IC's RMB context menus in these
# modes give way to the Maya marking menus; Shift+RMB 3D cursor goes (no 3D cursor in Maya).

MM_KEYMAPS = (("Object Mode", "VIEW3D_MT_object_context_menu"),
              ("Mesh", "VIEW3D_MT_edit_mesh_context_menu"),
              ("Curve", "VIEW3D_MT_edit_curve_context_menu"),
              ("Pose", "VIEW3D_MT_pose_context_menu"))      # joints (#578)
MM_EVENTS = (("RMB", {}), ("SHIFT_RMB", {"shift": True}), ("CTRL_RMB", {"ctrl": True}),
             ("TOOL_OPTIONS", {"shift": True, "ctrl": True}))
# Modes whose IC keymap sets the Q/W/E/R tools (IC _template_items_tool_select etc.).
TOOL_KEY_KEYMAPS = ("Object Mode", "Mesh", "Curve", "Armature", "Pose", "Metaball", "Lattice", "Curves")
TOOL_KEYS = (("Q", "tool_select"), ("W", "tool_move"), ("E", "tool_rotate"), ("R", "tool_scale"))


def patch_marking_menus(kd):
    for km, menu in MM_KEYMAPS:
        kd.remove(km, "wm.call_menu", type="RIGHTMOUSE")
        for trigger, mods in MM_EVENTS:
            _add(kd, km, "allset.marking_menu", make_event("RIGHTMOUSE", **mods), {"trigger": trigger})
    # Sculpt Mode: Maya sculpts with a tool and keeps its RMB marking menu over the mesh (Object Mode / Vertex / Edge /
    # Face leave Sculpt Mode); IC's sculpt context panel goes. First, so it runs before the stencil drag on the same
    # event, which it passes through to while the brush maps a stencil.
    kd.remove("Sculpt", "wm.call_panel", type="RIGHTMOUSE")
    _add(kd, "Sculpt", "allset.marking_menu", make_event("RIGHTMOUSE"), {"trigger": "RMB"}, shadows=("Sculpt",),
         first=True)
    kd.remove("3D View", "view3d.cursor3d", type="RIGHTMOUSE", shift=True)
    kd.remove("3D View", "transform.translate", type="RIGHTMOUSE", value="CLICK_DRAG", shift=True)
    for km in TOOL_KEY_KEYMAPS:
        for key, binding in TOOL_KEYS:
            kd.remove(km, "wm.tool_set_by_id", type=key)
            _add(kd, km, "allset.tap_hold", make_event(key), {"binding": binding})
    # T: Show Manipulator Tool = the last kit operation's manipulator + In-View Editor, else the Transform tool
    for km in ("Object Mode", "Mesh"):
        kd.remove(km, "wm.tool_set_by_id", type="T")
        _add(kd, km, "allset.show_manipulator", make_event("T"))


# --- 16. Scene concepts: P / Shift+P, Shift+D, Ctrl+Shift+D, Alt+Shift+D ------------------
# Maya hotkeys: p Parent, P Unparent, D DuplicateWithTransform,
# Ctrl+D (capital) DuplicateSpecial, Alt+D (capital) DeleteHistory.
# IC Object Mode P / Shift+P = object.parent_set / parent_clear.

def patch_concepts(kd):
    kd.remove("Object Mode", "object.parent_set", type="P")
    kd.remove("Object Mode", "object.parent_clear", type="P", shift=True)
    for km in ("Object Mode", "Outliner"):
        _add(kd, km, "allset.parent", make_event("P"))
        _add(kd, km, "allset.unparent", make_event("P", shift=True))
    # Ctrl+D: Maya Duplicate = in place, subtree, Maya names; IC
    # duplicate_move would name the copy pCube1.001 and start a move.
    kd.remove("Object Mode", "object.duplicate_move", type="D", ctrl=True)
    _add(kd, "Object Mode", "allset.duplicate", make_event("D", ctrl=True))
    # picked joints (Pose Mode, joint Edit Mode with the Move tool): Maya Duplicate copies each picked joint with its
    # subtree in place; IC armature.duplicate_move dropped a picked connected joint and started a move
    kd.remove("Armature", "armature.duplicate_move", type="D", ctrl=True)
    for km in ("Pose", "Armature"):
        _add(kd, km, "allset.duplicate", make_event("D", ctrl=True))
    # Component mode Ctrl+D (#17): Maya's Duplicate there copies nothing ("No object(s) to duplicate");
    # IC mesh.duplicate_move copied the faces inside the mesh.
    kd.remove("Mesh", "mesh.duplicate_move", type="D", ctrl=True)
    _add(kd, "Mesh", "allset.component_command", make_event("D", ctrl=True), {"item": "Edit/Duplicate"})
    _add(kd, "Object Mode", "allset.duplicate_with_transform", make_event("D", shift=True))
    _add(kd, "Object Mode", "allset.duplicate_special", make_event("D", shift=True, ctrl=True))
    # picked joints too: Duplicate with Transform repeats the change between the last copy and its joint, Duplicate
    # Special copies with its options (IC binds neither key in these keymaps)
    for km in ("Pose", "Armature"):
        _add(kd, km, "allset.duplicate_with_transform", make_event("D", shift=True))
        _add(kd, km, "allset.duplicate_special", make_event("D", shift=True, ctrl=True))
    _add(kd, "Object Mode", "allset.delete_history", make_event("D", shift=True, alt=True))


# --- 17. Ctrl+A Attribute Editor / Channel Box, Ctrl+Shift+A / Alt+D ------------------
# Maya hotkeys: Ctrl+a ShowAttributeEditorOrChannelBox, Ctrl+A (capital)
# SelectAll, Alt+d SelectNone. IC Object Mode Ctrl+A / Ctrl+Shift+A = select all / none.

def patch_attribute_editor(kd):
    kd.remove("Object Mode", "object.select_all", type="A", ctrl=True)
    kd.remove("Object Mode", "object.select_all", type="A", ctrl=True, shift=True)
    _add(kd, "Object Mode", "allset.ae_toggle", make_event("A", ctrl=True))
    _add(kd, "Object Mode", "object.select_all", make_event("A", ctrl=True, shift=True),
         {"action": 'SELECT'})
    _add(kd, "Object Mode", "allset.select_none", make_event("D", alt=True))
    # Ctrl+a is a global Maya hotkey (no editor context binds Ctrl+a): in every component /
    # pose mode IC's Ctrl+A select-all gives way to the AE / CB swap and Ctrl+Shift+A selects all (#65).
    for km, idname in CTRL_A_MODES:
        kd.remove(km, idname, type="A", ctrl=True)
        _add(kd, km, "allset.ae_toggle", make_event("A", ctrl=True))
        if km == "Mesh":                                         # Ctrl+Shift+A: patch_mesh_components
            continue
        if km != "Paint Vertex Selection (Weight, Vertex)":     # IC has no Ctrl+Shift+A there
            kd.remove(km, idname, type="A", ctrl=True, shift=True)
        _add(kd, km, idname, make_event("A", ctrl=True, shift=True), {"action": 'SELECT'})
    # Alt+D clears joints, latent bone selection, and the active object, releasing
    # pose/edit mode so the next click can select any object.
    _add(kd, "Pose", "allset.select_none", make_event("D", alt=True))
    for km in ("Curve", "Armature", "Metaball", "Lattice", "Curves", "Point Cloud"):
        _add(kd, km, "allset.select_none", make_event("D", alt=True))


# Keymaps whose Ctrl+A is IC select-all (keymap/ic_5_0.py – ic_5_2.py). Text / Console / Font /
# File Browser keep their text-style select-all; the 2D animation editors follow.
CTRL_A_MODES = (("Mesh", "mesh.select_all"), ("Pose", "pose.select_all"), ("Curve", "curve.select_all"),
                ("Armature", "armature.select_all"), ("Metaball", "mball.select_all"),
                ("Lattice", "lattice.select_all"), ("Particle", "particle.select_all"),
                ("Curves", "curves.select_all"), ("Sculpt Curves", "curves.select_all"),
                ("Point Cloud", "pointcloud.select_all"),
                ("Paint Face Mask (Weight, Vertex, Texture)", "paint.face_select_all"),
                ("Paint Vertex Selection (Weight, Vertex)", "paint.vert_select_all"),
                ("UV Editor", "uv.select_all"),
                # #96: the 2D animation editors too — Maya's Ctrl+a is global (Graph Editor / Dope Sheet
                # included); IC Ctrl+A there = select all keys / channels, Ctrl+Shift+A = deselect
                ("Graph Editor", "graph.select_all"), ("Dopesheet", "action.select_all"),
                ("NLA Editor", "nla.select_all"), ("Animation Channels", "anim.channels_select_all"))


# --- 18. Undo / redo, visibility, isolate, invert -------------------------------
# Maya: z / Shift+Z / Ctrl+Y; h, Ctrl+H, Alt+H,
# Shift+H, Ctrl+Shift+H, Ctrl+Alt+H, Ctrl+1; Ctrl+Shift+I.

# Editor keymaps run before "Screen": their z = zoom/viewer border would hide the undo. The Node Editor's Z item
# exists in 5.0's Industry Compatible keymap only (keymap/ic_5_0.py; not in ic_5_1 / ic_5_2): optional.
_Z_BORDERS = (("3D View", "view3d.zoom_border", False), ("View2D", "view2d.zoom_border", False),
              ("Image", "image.view_zoom_border", False), ("Node Editor", "node.viewer_border", True))

VISIBILITY_KEYS = (("H", {}, "TOGGLE"), ("H", {"ctrl": True}, "HIDE"),
                   ("H", {"alt": True}, "HIDE_UNSELECTED"), ("H", {"shift": True}, "SHOW_SELECTED"),
                   ("H", {"ctrl": True, "shift": True}, "SHOW_LAST"))


def patch_undo_visibility(kd):
    for km, idname, optional in _Z_BORDERS:
        kd.remove(km, idname, optional=optional, type="Z")
    _add(kd, "Screen", "ed.undo", make_event("Z"))
    _add(kd, "Screen", "ed.redo", make_event("Z", shift=True))
    _add(kd, "Screen", "ed.redo", make_event("Y", ctrl=True))

    # Object Mode: IC Ctrl+H hide, Shift+H hide unselected, Alt+H reveal (IC Object Mode).
    kd.remove("Object Mode", "object.hide_view_set", type="H", ctrl=True)
    kd.remove("Object Mode", "object.hide_view_set", type="H", shift=True)
    kd.remove("Object Mode", "object.hide_view_clear", type="H", alt=True)
    for key, mods, action in VISIBILITY_KEYS:
        _add(kd, "Object Mode", "allset.visibility", make_event(key, **mods), {"action": action})
    # Joints (Pose / skeleton Edit mode): the same keys on joints (#568). IC Ctrl+H / Shift+H hide the selected /
    # unselected bones (children stay), Alt+H reveals; Show Last Hidden / Show Selection had no key there.
    for km, hide, reveal in (("Pose", "pose.hide", "pose.reveal"), ("Armature", "armature.hide", "armature.reveal")):
        kd.remove(km, hide, type="H", ctrl=True)
        kd.remove(km, hide, type="H", shift=True)
        kd.remove(km, reveal, type="H", alt=True)
        for key, mods, action in VISIBILITY_KEYS:
            _add(kd, km, "allset.visibility", make_event(key, **mods), {"action": action})
    # Outliner: the same keys (Maya hides from the Outliner with them). IC Ctrl+H = outliner.hide (the view-layer
    # flag, which Shift+H / Ctrl+Shift+H can't bring back), Alt+H = outliner.unhide_all.
    kd.remove("Outliner", "outliner.hide", type="H", ctrl=True)
    kd.remove("Outliner", "outliner.unhide_all", type="H", alt=True)
    for key, mods, action in VISIBILITY_KEYS:
        _add(kd, "Outliner", "allset.visibility", make_event(key, **mods), {"action": action})
    # Mesh components: hidden components can't be selected in Blender, so the "show"
    # keys reveal everything (and select it). IC Shift+H / Alt+H = hide unselected / reveal.
    kd.remove("Mesh", "mesh.hide", type="H", shift=True)
    kd.remove("Mesh", "mesh.reveal", type="H", alt=True)
    _add(kd, "Mesh", "mesh.hide", make_event("H", alt=True), {"unselected": True})
    for mods in ({"shift": True}, {"ctrl": True, "shift": True}, {"ctrl": True, "alt": True}):
        _add(kd, "Mesh", "mesh.reveal", make_event("H", **mods))

    # Ctrl+1 isolate select: local view without moving the camera; again = back.
    kd.remove("Mesh", "mesh.select_mode", type="ONE", ctrl=True)
    # isolating a group shows its children (Maya isolate select)
    _add(kd, "3D View", "allset.isolate", make_event("ONE", ctrl=True), shadows=("Sculpt",))   # macOS: Cmd+1 too
    # Maya Delete takes the selected hierarchy with it; Blender's leaves the children
    for key in ("DEL", "BACK_SPACE"):
        kd.remove("Object Mode", "object.delete", type=key)
        _add(kd, "Object Mode", "allset.delete", make_event(key))
        kd.remove("Outliner", "outliner.delete", type=key)
        # with the hierarchy; the kit tree's own Delete item comes first (patch_outliner_tree)
        _add(kd, "Outliner", "allset.outliner_delete", make_event(key), shadows=("Outliner",))
    # Maya Outliner Ctrl+D = Edit > Duplicate (groups with their children); IC Ctrl+D there adds drivers
    kd.remove("Outliner", "outliner.drivers_add_selected", type="D", ctrl=True)
    _add(kd, "Outliner", "allset.duplicate", make_event("D", ctrl=True), shadows=("Outliner",))

    _add(kd, "Object Mode", "object.select_all", make_event("I", ctrl=True, shift=True),
         {"action": 'INVERT'})
    _add(kd, "Mesh", "mesh.select_all", make_event("I", ctrl=True, shift=True), {"action": 'INVERT'})


# --- 25. Shift+T Assign New Material ---------------------------------------------------
# Maya hotkey. IC binds Shift+T only in the
# Dope Sheet.

def patch_materials(kd):
    for km in ("Object Mode", "Mesh"):
        _add(kd, km, "allset.assign_new_material", make_event("T", shift=True))


# --- 27. Maya key batch --------------------------------------------------------------
# Ctrl+Alt+LMB box zoom, Ctrl+T Universal Manipulator, Y last non-sacred
# tool, Ctrl+Shift+X Multi-Cut / Ctrl+Shift+Q Quad Draw, F2-F6 menu sets
# (IC's 3D View F2 right / F3 top / F4 camera / F5 orbit go, F1 and Ctrl+F1-F3 stay),
# Return: IC's 3D View rename popover goes (Blender modal tools confirm with their own Return).

# Editors whose own F2-F6 keys stay (they run before Screen): Image / UV zoom ratios, File Browser rename.
MENU_SET_SHADOWS = ("Image", "File Browser")


def patch_key_batch(kd):
    # Blender 5.x IC binds Ctrl+Alt+LMB in Sculpt mode too: there the sculpt stroke wins (Maya has no such
    # mode).
    _add(kd, "3D View", "allset.box_zoom", make_event("LEFTMOUSE", ctrl=True, alt=True), shadows=("Sculpt",))
    for km in ("Object Mode", "Mesh"):
        # Universal Manipulator: the kit's box tool, for objects and for mesh components (#318)
        _add(kd, km, "wm.tool_set_by_id", make_event("T", ctrl=True), {"name": "allset.universal_manip"})
        _add(kd, km, "allset.last_tool", make_event("Y"))
        _add(kd, km, "allset.menu_tool", make_event("X", shift=True, ctrl=True),
             {"tool": "allset.multi_cut_tool", "edit": True})     # the kit Multi-Cut tool
        _add(kd, km, "allset.quad_draw_start", make_event("Q", shift=True, ctrl=True))   # kit Quad Draw
    kd.remove("3D View", "view3d.view_axis", type="F2")
    kd.remove("3D View", "view3d.view_axis", type="F3")
    kd.remove("3D View", "view3d.view_camera", type="F4")
    kd.remove("3D View", "view3d.view_orbit", type="F5")
    kd.remove("3D View", "wm.call_panel", type="RET")
    for key, set_id in (('F2', 'modelingMenuSet'), ('F3', 'riggingMenuSet'), ('F4', 'animationMenuSet'),
                        ('F5', 'dynamicsMenuSet'), ('F6', 'renderingMenuSet')):
        _add(kd, "Screen", "allset.menu_set", make_event(key), {"set": set_id},
             shadows=MENU_SET_SHADOWS)


# --- 30. Joints = pose bones ------------------------------------------------------
# Maya has no pose mode: picking a joint selects it. Ctrl+Tab =
# pose mode toggle (Blender's default key for it; posemode_toggle returns PASS_THROUGH unless an
# armature is active, so Screen's Ctrl+Tab still gets the event); the Channel Box MMB
# slider works on joints.

def patch_pose_joints(kd):
    _add(kd, "Object Non-modal", "object.posemode_toggle", make_event("TAB", ctrl=True), shadows=("Screen",))
    _add(kd, "Pose", "allset.cb_virtual_slider", make_event("MIDDLEMOUSE"),
         shadows=("Pose", "3D View"))            # the emulated Alt+LMB tumble (#242) passes through otherwise


# --- 32. Joints: pose-mode pick-walk, P / Shift+P -------------------------------------------
# Maya arrows walk joints like objects (pickWalk); IC Pose
# arrows = select_hierarchy (IC:2453-2459) and frame_offset Left/Right (frames are Alt+, / Alt+.).
# Maya P parents joints keeping their place: IC Pose P = object.parent_set (IC:2434), Armature
# P / Shift+P = armature.parent_set / parent_clear menus (IC:3099-3100).

def patch_joints(kd):
    kd.remove("Pose", "pose.select_hierarchy", type="UP_ARROW")
    kd.remove("Pose", "pose.select_hierarchy", type="DOWN_ARROW")
    kd.remove("Pose", "screen.frame_offset", type="LEFT_ARROW")     # frames: Alt+, / Alt+.
    kd.remove("Pose", "screen.frame_offset", type="RIGHT_ARROW")
    for key, direction in PICK_WALK_KEYS:
        _add(kd, "Pose", "allset.pick_walk_joint", make_event(key, repeat=True), {"direction": direction})
    kd.remove("Pose", "object.parent_set", type="P")
    kd.remove("Armature", "armature.parent_set", type="P")
    kd.remove("Armature", "armature.parent_clear", type="P", shift=True)
    for km in ("Pose", "Armature"):
        _add(kd, km, "allset.parent_joint", make_event("P"))
        _add(kd, km, "allset.unparent_joint", make_event("P", shift=True))


# --- 36. Scene files -------------------------------------------------------------------------
# Maya hotkeys Ctrl+O / Ctrl+S / Ctrl+Shift+S / Ctrl+Alt+S / Ctrl+R. IC binds the first four in "Window"
# (IC:194-199): replaced in place by the kit's (file dialogs start in the project's scenes folder; Ctrl+Alt+S =
# Maya's Increment and Save rule shot_v001 -> shot_v001.0001, not Blender's shot_v002). Ctrl+R = Create Reference;
# editor keymaps that bind Ctrl+R themselves keep it there (they run first).

SCENE_KEYS = (
    ("wm.open_mainfile", "allset.open_scene", {"ctrl": True}, "O"),
    ("wm.save_mainfile", "allset.save_scene", {"ctrl": True}, "S"),
    ("wm.save_as_mainfile", "allset.save_scene_as", {"ctrl": True, "shift": True}, "S"),
    ("wm.save_mainfile", "allset.increment_save", {"ctrl": True, "alt": True}, "S"),
)


def patch_scene_files(kd):
    for ic, kit, mods, key in SCENE_KEYS:
        kd.remove("Window", ic, type=key, **mods)
        _add(kd, "Window", kit, make_event(key, **mods))
    # Ctrl+N = Maya New Scene (Maya hotkey NewScene): IC's wm.read_homefile opens Blender's default file (there is no
    # app template copy); the kit's new_maya_scene reads the Maya layout file like File > New Scene (#44).
    kd.remove("Window", "wm.read_homefile", type="N", ctrl=True)
    _add(kd, "Window", "allset.new_maya_scene", make_event("N", ctrl=True), shadows=("Text",))  # Text: new text
    # Ctrl+R stays refresh / reload where an editor binds it (they run before Window items).
    _add(kd, "Window", "allset.create_reference", make_event("R", ctrl=True),
         shadows=("Image Generic", "File Browser", "File Browser Main", "Sequencer"))


# --- 38. Key batch 2 --------------------------------------------------------------------------
# Graph Editor 1/2/3, Shift+Q / Alt+Q select tool marking menus, Ctrl+Alt+Left/Right
# Spin Edge, Shift+G repeat at the mouse, Ctrl+Shift+C camera from view (Maya hotkeys).
# IC has none of these events in these keymaps; same-event IC items elsewhere stay (editor keymaps run first):
# Shift+Q in Grease Pencil modes, Shift+G select similar / grouped in Armature, Metaball, Grease Pencil.
SELECT_MM_KEYMAPS = ("Object Mode", "Mesh")
REPEAT_SHADOWS = ("Armature", "Metaball", "Grease Pencil Selection")
SELECT_MM_KEYS = (({"shift": True}, "select_component"), ({"alt": True}, "select_polygon"))   # marking.SELECT_BINDINGS
GRAPH_VIEW_KEYS = (("ONE", "ABSOLUTE"), ("TWO", "STACKED"), ("THREE", "NORMALIZED"))


def patch_key_batch_2(kd):
    for key, mode in GRAPH_VIEW_KEYS:
        _add(kd, "Graph Editor", "allset.graph_view_mode", make_event(key), {"mode": mode})
    for km in SELECT_MM_KEYMAPS:
        for mods, binding in SELECT_MM_KEYS:
            _add(kd, km, "allset.tap_hold", make_event("Q", **mods), {"binding": binding})
    _add(kd, "Mesh", "mesh.edge_rotate", make_event("LEFT_ARROW", ctrl=True, alt=True), {"use_ccw": True})
    _add(kd, "Mesh", "mesh.edge_rotate", make_event("RIGHT_ARROW", ctrl=True, alt=True), {"use_ccw": False})
    _add(kd, "3D View", "allset.repeat_at_mouse", make_event("G", shift=True), shadows=REPEAT_SHADOWS)
    _add(kd, "Object Mode", "allset.camera_from_view", make_event("C", shift=True, ctrl=True))


# --- 43. Global key batch 4 -------------------------------------------------------------------
# Maya hotkeys Ctrl+x, Alt+x, Alt+backslash, Alt+1/2/4, Ctrl+` / Shift+~ /
# Ctrl+Shift+~). Ctrl+X exists only in other editors / modes (Text, Console, Font, Grease Pencil edit); Alt+X was IC's
# X-ray toggle; the rest were free. Plain ` stays the tweak hold.
CUT_SHADOWS = ("Text", "Console", "Font", "Grease Pencil Edit Mode")
SHOW_KEYS = (("ONE", "CURVES"), ("TWO", "POLYGONS"), ("FOUR", "IMAGE_PLANES"))


def patch_global_keys_4(kd):
    for km in ("Object Mode", "Outliner"):
        _add(kd, km, "allset.cut", make_event("X", ctrl=True), shadows=CUT_SHADOWS)
    # Blender's paste leaves no active object after a cut: the kit paste makes the first pasted node the lead.
    _add(kd, "Object Mode", "allset.paste", make_event("V", ctrl=True), shadows=("3D View",))
    kd.remove("3D View", "view3d.toggle_xray", type="X", alt=True)
    _add(kd, "3D View", "view3d.walk", make_event("X", alt=True), shadows=VIEW3_SHADOWS)
    _add(kd, "Screen", "allset.playback_range_anim", make_event("BACK_SLASH", alt=True))
    for key, kind in SHOW_KEYS:
        _add(kd, "3D View", "allset.toggle_show", make_event(key, alt=True), {"kind": kind}, shadows=VIEW3_SHADOWS)
    for km in ("Object Mode", "Mesh"):
        _add(kd, km, "allset.smooth_proxy", make_event("ACCENT_GRAVE", ctrl=True), {"action": "TOGGLE"})
        _add(kd, km, "allset.smooth_proxy", make_event("ACCENT_GRAVE", shift=True), {"action": "BOTH"})
    _add(kd, "Object Mode", "allset.smooth_proxy", make_event("ACCENT_GRAVE", ctrl=True, shift=True),
         {"action": "CREATE"})


# --- 50. Menu shortcuts -----------------------------------------------------------------------------
# Blender prints the keymap shortcut of a menu's ``wm.call_menu`` beside the item that opens it: File > Recent Files
# showed IC's "Shift Ctrl O" (a C menu, so no kit subclass can hide it). Maya has no Ctrl+Shift+O;
# the recent files stay in File > Recent Files.

def patch_menu_shortcuts(kd):
    kd.remove("Window", "wm.call_menu", type="O", ctrl=True, shift=True)


def patch_repeat(kd):
    """G = Maya repeat last, menu / shelf / marking commands too (operators/repeat_maya.py); Blender's
    screen.repeat_last only knows registered operators. Graph Editor G stays anim.scene_range_frame."""
    kd.remove("Screen", "screen.repeat_last", type="G")
    # Blender 5.3 Grease Pencil Draw Mode G move; Maya's G (repeat) wins in the kit
    kd.remove("Grease Pencil Draw Mode", "transform.translate", optional=True, type="G")
    repeat_maps = ("Screen", "3D View", "Object Mode", "Mesh")
    _add(kd, "Screen", "allset.repeat_last", make_event("G"),
         shadows=repeat_maps + ("Graph Editor", "Dopesheet", "Grease Pencil Edit Mode"))  # their own G wins
    # there; the Dope Sheet's g steps aside in the Timeline, so the Time Slider still repeats
    # A mode-specific add-on G menu runs ahead of Screen's binding. Own the same
    # viewport maps so the normal priority watcher can keep Maya Repeat first.
    for km in repeat_maps[1:]:
        _add(kd, km, "allset.repeat_last", make_event("G"), shadows=repeat_maps)


# --- 51. Blender's render keys ---------------------------------------------------------------------------------------
# F12 / Ctrl+F12 = Blender's Render Image / Render Animation. Their default-keyconfig items in "Screen" are switched
# off in Maya mode (Screen is a patched keymap), so the same render.render items go there as kit items. The 3D View's
# Object Mode / Mesh F12 (Maya's SelectUVMask, patch_uv) runs first there, and the UV Editor gets the same Maya F12
# (its keymap runs before Screen): F12 renders everywhere else. IC's Ctrl+Alt+Enter Render Animation stays.

def patch_blender_render(kd):
    _add(kd, "Screen", "render.render", make_event("F12"), {"use_viewport": True},
         shadows=("Object Mode", "Mesh", UV_KM))   # Maya's F12 UV mask wins in the 3D View / UV Editor
    _add(kd, UV_KM, "allset.uv_component", make_event("F12"), {"mode": 'UV'}, shadows=("Screen",))
    _add(kd, "Screen", "render.render", make_event("F12", ctrl=True), {"animation": True, "use_viewport": True})


# --- Blender keys next to the Maya keys (#226) -----------------------------------------------------------------
# Opt-in (add-on preferences "Keep Blender Keys", off by default): a few Blender keys for hands trained on both
# programs, only where no Maya key uses the same event. Not in ``PATCHES``: ``maya_patches.apply`` runs it last with
# the keys the preferences ask for. 3D View only; the other editors keep their keys. Keys Maya mode already uses stay
# Maya keys (Ctrl+Tab pose mode, Q Select tool, . next key, F frame selection), and an active tool's own key runs
# first (Quad Draw keeps Tab + drag).
#   TAB         Tab = Edit Mode toggle, as in Blender. Takes the place of the Industry Compatible operator search on
#               Tab in the 3D View (the search stays on Ctrl+F).
#   LOCAL_VIEW  Alt+E = Local View toggle. Takes the place of the Industry Compatible Alt+E Clear Rotation of Object
#               Mode and Pose Mode (Modify > Reset Transformations stays).
BLENDER_KEYS = ("TAB", "LOCAL_VIEW")


def patch_blender_keys(kd, keys=()):
    if "TAB" in keys:
        kd.remove("3D View", "wm.search_menu", type="TAB")
        _add(kd, "Object Non-modal", "object.mode_set", make_event("TAB"), {"mode": 'EDIT', "toggle": True})
    if "LOCAL_VIEW" in keys:
        kd.remove("Object Mode", "object.rotation_clear", type="E", alt=True)
        kd.remove("Pose", "pose.rot_clear", type="E", alt=True)
        _add(kd, "3D View", "view3d.localview", make_event("E", alt=True))
