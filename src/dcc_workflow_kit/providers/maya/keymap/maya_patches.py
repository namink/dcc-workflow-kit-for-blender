# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn Industry Compatible keymap data into the Maya keymap: ``apply(data)`` runs every patch in ``PATCHES`` order
(that order decides which item comes first in a keymap). The patches live in ``maya_patches_*.py`` by area; ``ADDED``
(every added binding, for the shadowing check and the keymap mapping table) and ``PASS_THROUGH_FIRST`` are read from
here.
"""

from . import patch
from .patch import KeyconfigData, make_event
# the patches by area (each file's docstring says what it holds); the constants are re-exported: tests and
# tools read them from here
from .maya_patches_base import ADDED, PICK_WALK_KEYS, SLIDER_TOOL_KEYMAPS, UV_KM, _add  # noqa: F401
from .maya_patches_select import (  # noqa: F401
    SELECT_2D_KEYMAPS, SELECT_CTRL_SHIFT_REMOVED, SELECT_DRAG_KEYMAPS, SELECT_PRIORITY_ITEMS, UV_SHELL_DRAG_KEYMAPS,
    patch_select_priority, patch_select_through, patch_selection, patch_toolbox_guard, patch_tweak_fallback,
    patch_type_char_pick, patch_uv_shell_hover, patch_uv_shell_select)
from .maya_patches_view import (  # noqa: F401
    DISPLAY_KEYS, EMULATED_TUMBLE_KEYMAPS, HOTBOX_KEYMAPS, PIXEL_MOVE_KEYS, SMOOTH_KEYS, patch_camera, patch_display,
    patch_emulated_tumble, patch_smooth_preview, patch_space, patch_space_tap, patch_view_history, patch_view_keys,
    patch_view_keys_3)
from .maya_patches_manip import (  # noqa: F401
    GIZMO_KEYMAPS, HOLD_KEYS, MMB_TOOLS, patch_active_handle, patch_component_slide, patch_hold_snap,
    patch_in_view_mmb, patch_manip_ctrl, patch_manip_duplicate, patch_soft_select, patch_tap_hold_and_pivot)
from .maya_patches_commands import (  # noqa: F401
    BLENDER_KEYS, CTRL_A_MODES, MM_KEYMAPS, TOOL_KEYS, TOOL_KEY_KEYMAPS, patch_attribute_editor, patch_blender_render,
    patch_concepts, patch_global_keys_4, patch_group, patch_joints, patch_key_batch, patch_key_batch_2,
    patch_marking_menus, patch_materials, patch_menu_shortcuts, patch_pick_walk, patch_pose_joints, patch_repeat,
    patch_blender_keys, patch_scene_files, patch_undo_visibility)
from .maya_patches_mesh import (  # noqa: F401
    COMPONENT_KEYS, MODE_KEYMAPS, SCULPT_BRUSHES, patch_component_delete, patch_component_keys,
    patch_component_pick_walk, patch_key_batch_3, patch_mesh_components, patch_uv, patch_weight_paint_exit)
from .maya_patches_anim import (
    patch_global_set_key, patch_graph_handles, patch_graph_key_tool_everywhere, patch_graph_keys,
    patch_graph_prefer_click, patch_graph_tools,
    patch_graph_keys_2, patch_graph_outliner, patch_key_insert, patch_key_stepping, patch_motion_trail_keys,
    patch_motion_trail_mmb, patch_time_range, patch_time_slider)
from .maya_patches_editors import (
    OUTLINER_TREE_ITEMS, patch_attribute_edit, patch_cb_slider, patch_outliner_drag, patch_outliner_tree,
    patch_render_slots, patch_script_editor, patch_shelf_scroll, patch_hypershade_graph)


# Operators that return PASS_THROUGH when they don't apply, so they may sit in
# front of another item with the same event in the same keymap.
PASS_THROUGH_FIRST = ("allset.pivot_pick", "allset.inview_drag", "allset.uv_shell_hover", "allset.emulated_tumble", "allset.cb_virtual_slider", "allset.cb_hover", "allset.pt_hover", "allset.weight_numbers_hover", "allset.cb_scroll","allset.time_range_drag", "allset.manip_ctrl", "allset.manip_slide", "allset.manip_duplicate", "allset.manip_release", "allset.manip_press",
                      "allset.select_priority", "allset.type_char_pick", "allset.select_through", "allset.toolbox_guard", "allset.time_scrub",
                      "allset.time_view_lock",
                      "allset.time_slider_menu", "allset.time_slider_delete", "allset.time_range_all",
                      "allset.graph_channel_click", "allset.graph_channel_scroll", "allset.script_run",
                      "allset.dock_strip_click",
                      "allset.hs_swatch_drag", "allset.hs_tab_create", "allset.hs_mmb_drag", "allset.shelf_scroll", "allset.shelf_button_menu",
                      "allset.select_2d_click", "allset.select_2d_box", "allset.graph_layer_pick",
                      "allset.uv_shell_pick", "allset.uv_shell_box",
                      "allset.graph_axis_drag", "allset.graph_move_snap", "allset.graph_shift_press",
                      "allset.graph_key_drag", "allset.graph_scale_box",
                      "allset.hg_click", "allset.hg_mmb", "allset.hg_rmb", "allset.hg_zoom",
                      "allset.hg_frame", "allset.marking_menu",
                      "allset.graph_handle_drag", "allset.graph_handle_box", "allset.motion_trail_key",
                      "allset.nav_2d", "allset.graph_hover", "allset.graph_marquee_watch",
                      "allset.graph_prefer_click", "allset.time_slider_bookmark_click",
                      "allset.time_slider_bookmark_hover", "allset.time_slider_bookmark_drag",
                      "allset.graph_hover_drop")
PASS_THROUGH_FIRST += ('allset.attribute_field_hover', 'allset.option_editor_key')
PASS_THROUGH_FIRST += OUTLINER_TREE_ITEMS


# --- Numpad digits = the top row (#283) -----------------------------------------------------------------------
# On a Maya keyboard the numpad digits are the same keys as the top row: 1 / 2 / 3 smooth preview, 4-7 display,
# 0 rough display, and every other plain digit key. Each plain digit item the kit adds gets a numpad twin, unless
# that key map already has an item on the numpad key (then Blender's stays). Runs after every other patch.

DIGITS = ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE")
NUMPAD_DIGITS = {key: f"NUMPAD_{n}" for n, key in enumerate(DIGITS)}


def patch_numpad_digits(kd):
    plain = (0,) * len(patch.MODS)
    twins = []
    for km, idname, e, props, shadows in ADDED:
        numpad = NUMPAD_DIGITS.get(e["type"])
        if numpad is not None and e.get("value", "PRESS") == "PRESS" and not e.get("any") and                 patch.event_key(e)[2] == plain and e.get("key_modifier", "NONE") == "NONE":
            twins.append((km, idname, numpad, props, shadows))
    taken = {(km, numpad) for km, _i, numpad, _p, _s in twins if kd.find(km, type=numpad)}
    for km, idname, numpad, props, shadows in twins:
        if (km, numpad) not in taken:
            _add(kd, km, idname, make_event(numpad), props, shadows=shadows)


# Order matters: a later patch's ``first=True`` items go in front of earlier ones in the same keymap, and
# the last passes read or rewrite what the earlier ones put in ``ADDED``.
PATCHES = (patch_tweak_fallback, patch_selection, patch_graph_prefer_click, patch_display, patch_group, patch_space,
           patch_hold_snap, patch_soft_select, patch_tap_hold_and_pivot, patch_pick_walk,
           patch_camera, patch_view_history, patch_space_tap, patch_smooth_preview,
           patch_component_keys, patch_motion_trail_mmb, patch_in_view_mmb, patch_cb_slider, patch_marking_menus,
           patch_concepts,
           patch_attribute_editor, patch_undo_visibility,
           patch_mesh_components, patch_key_stepping, patch_manip_duplicate,
           patch_component_delete, patch_view_keys, patch_active_handle, patch_materials,
           patch_uv_shell_select, patch_select_through, patch_key_batch, patch_component_pick_walk,
           patch_toolbox_guard, patch_type_char_pick, patch_select_priority, patch_motion_trail_keys, patch_pose_joints, patch_time_slider, patch_joints, patch_uv,
           patch_scene_files, patch_graph_keys, patch_key_batch_2, patch_outliner_drag,
           patch_key_insert, patch_time_range, patch_manip_ctrl, patch_view_keys_3,
           patch_global_keys_4, patch_graph_keys_2, patch_outliner_tree, patch_render_slots,
           patch_graph_outliner, patch_shelf_scroll, patch_script_editor, patch_key_batch_3,
           patch_menu_shortcuts, patch_repeat, patch_blender_render)
PATCHES += (patch_weight_paint_exit, patch_global_set_key, patch_graph_key_tool_everywhere, patch_emulated_tumble)
PATCHES += (patch_component_slide,)
PATCHES += (patch_uv_shell_hover,)
PATCHES += (patch_graph_handles,)
PATCHES += (patch_graph_tools,)
PATCHES += (patch_hypershade_graph,)
PATCHES += (patch_numpad_digits,)
PATCHES += (patch_attribute_edit,)


def apply(data, blender_keys=()):
    """Apply all patches to IC data in place and return it. ``blender_keys``: the opt-in Blender keys to keep
    (``BLENDER_KEYS`` names, add-on preferences "Keep Blender Keys")."""
    ADDED.clear()
    kd = KeyconfigData(data)
    for apply_patch in PATCHES:
        apply_patch(kd)
    patch_blender_keys(kd, blender_keys)
    return data
