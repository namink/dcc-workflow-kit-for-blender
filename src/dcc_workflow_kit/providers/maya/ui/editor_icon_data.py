# SPDX-License-Identifier: GPL-3.0-or-later
"""Icon-row tables of the Maya editors (Graph Editor, Dope Sheet, UV Editor, Hypershade graph): (button name,
Blender icon, action, tooltip) rows and the notices of greyed buttons. Data file: grep for a button name or read a
line range instead of the whole file. Drawn by ``editor_icon_row``.
"""

from .editor_kinds import GE, DS, UV


# --- icon rows -----------------------------------------------------------------------------------------------------
# (kit button name, Blender icon, action or None, tooltip). An action is a menu_map value
# (incl. ("prop", ...)); "|" = separator, "STATS" = the selected key's time / value fields, "IMAGE" / "UVMAP" = the
# UV Editor's texture field / UV set. Unmapped buttons draw greyed with their notice (NOTICES below).

def _t(kind):
    return ("allset.set_tangent", {"kind": kind})


def _inf(side, mode):
    return ("allset.curve_infinity", {"side": side, "mode": mode})


GRAPH_ICONS = (
    ("key_nearest_tool", 'RESTRICT_SELECT_OFF', None, "Move Nearest Picked Key Tool"),
    ("key_insert_tool", 'KEY_HLT', "allset.insert_key_tool", "Insert Keys Tool"),
    ("key_lattice_tool", 'MOD_LATTICE', None, "Lattice Deform Keys"),
    ("key_region_tool", 'FULLSCREEN_ENTER', ("prop", "window_manager.allset_graph_key_tool", {"value": 'REGION'}),
     "Region Tool: Scale or move keys"),
    ("key_retime_tool", 'TIME', "allset.retime_tool", "Retime Tool: scale and ripple keys"),
    "|",
    # Maya's curve sculpting group (the w / e / r key tools are keys and Edit > Transformation Tools items)
    ("key_grab_tool", 'MOUSE_LMB_DRAG', None, "Grab Keys Tool"),
    ("key_smooth", 'SMOOTHCURVE', "graph.smooth", "Smooth Keys"),
    ("key_smear_tool", 'MOUSE_MMB_DRAG', None, "Smear Keys Tool"),
    ("key_reduce", 'MOD_DECIM', "graph.decimate", "Reduce Keys"),
    "|", "STATS", "|",
    ("frame_all", 'ZOOM_ALL', ("allset.graph_frame", {"mode": 'ALL'}), "Frame all"),
    ("frame_range", 'PREVIEW_RANGE', "anim.scene_range_frame", "Frame playback range"),
    ("center_time", 'CENTER_ONLY', "allset.graph_center_time", "Scroll the view so the current time sits in the middle"),
    "|",
    ("tan_auto", 'HANDLE_AUTOCLAMPED', _t("AUTO"), "Auto tangents"),
    ("tan_auto_ease", 'HANDLE_AUTOCLAMPED', _t("AUTO"), "Auto Ease tangents"),
    ("tan_auto_mix", 'HANDLE_AUTOCLAMPED', _t("AUTO"), "Auto Mix tangents"),
    ("tan_auto_custom", 'HANDLE_AUTOCLAMPED', _t("AUTO"), "Auto Custom tangents"),
    ("tan_spline", 'IPO_BEZIER', _t("SPLINE"), "Spline tangents"),
    ("tan_clamped", 'HANDLE_AUTO', _t("CLAMPED"), "Clamped tangents"),
    ("tan_linear", 'IPO_LINEAR', _t("LINEAR"), "Linear tangents"),
    ("tan_flat", 'IPO_SINE', _t("FLAT"), "Flat tangents"),
    ("tan_stepped", 'IPO_CONSTANT', _t("STEPPED"), "Stepped tangents"),
    ("tan_plateau", 'IPO_EASE_IN_OUT', _t("PLATEAU"), "Plateau tangents"),
    "|",
    ("tan_default_in", 'TRIA_LEFT', ("submenu", "Tangents/Default In Tangent"), "Default in tangent"),
    ("tan_default_out", 'TRIA_RIGHT', ("submenu", "Tangents/Default Out Tangent"), "Default out tangent"),
    "|",
    ("buffer_snapshot", 'GHOST_ENABLED', "allset.buffer_snapshot", "Buffer curve snapshot"),
    ("buffer_swap", 'GHOST_DISABLED', "allset.buffer_swap", "Swap buffer curves"),
    "|",
    ("tan_break", 'HANDLE_FREE', _t("BREAK"), "Break tangents"),
    ("tan_unify", 'HANDLE_ALIGNED', _t("UNIFY"), "Unify tangents"),
    ("tan_free_length", 'UNLOCKED', ("allset.tangent_weight_lock", {"lock": False}), "Free tangent length"),
    ("tan_lock_length", 'LOCKED', ("allset.tangent_weight_lock", {"lock": True}), "Lock tangent length"),
    "|",
    ("list_auto_load", 'LINKED', ("prop", "window_manager.allset_auto_load", {}),
     "Auto load Graph Editor on selection"),
    ("list_load", 'FILE_REFRESH', ("allset.graph_list", {"action": "LOAD"}), "Load the selected objects"),
    "|",
    # Maya's drag constraint button: on = a middle drag moves freely, off = along the first direction
    ("constrained_drag", 'VIEW_PAN', ("prop", "addon_prefs.graph_unconstrained_drag", {}),
     "Unconstrained drag"),
    ("time_snap", 'SNAP_ON', ("prop", "tool_settings.use_snap_anim", {}), "Time snap"),
    ("value_snap", 'SNAP_INCREMENT', None, "Value snap"),
    "|",
    ("view_absolute", 'FCURVE', ("prop", "space_data.use_normalization", {"value": False}),
     "Absolute view"),
    ("view_stacked", 'ALIGN_JUSTIFY', ("allset.graph_view_mode", {"mode": "STACKED"}),
     "Stacked view"),
    ("view_normalized", 'NORMALIZE_FCURVES',
     ("prop", "space_data.use_normalization", {"value": True}), "Normalized view"),
    ("renormalize", 'RECOVER_LAST', ("prop", "space_data.use_auto_normalization", {}),
     "Re-normalize curves"),
    "|",
    ("pre_cycle", 'LOOP_BACK', _inf("PRE", "CYCLE"), "Pre-infinity cycle"),
    ("pre_cycle_offset", 'FRAME_PREV', _inf("PRE", "CYCLE_OFFSET"), "Pre-infinity cycle with offset"),
    ("post_cycle", 'LOOP_FORWARDS', _inf("POST", "CYCLE"), "Post-infinity cycle"),
    ("post_cycle_offset", 'FRAME_NEXT', _inf("POST", "CYCLE_OFFSET"),
     "Post-infinity cycle with offset"),
    "|",
    # Maya 2026: the editor buttons at the right end are Graph Editor / Dope Sheet / Time Editor
    # in both editors (Maya 2022: Trax Editor for the Time Editor)
    ("open_graph_editor", 'GRAPH', ("allset.open_editor", {"ui_type": 'FCURVES'}), "Open the Graph Editor"),
    ("open_dope_sheet", 'ACTION', ("allset.open_editor", {"ui_type": 'DOPESHEET'}), "Open the Dope Sheet"),
    ("open_time_editor", 'NLA', ("allset.open_editor", {"ui_type": 'NLA_EDITOR'}), "Open the Time Editor"),
)

# Maya 2026 Dope Sheet tools: Select keys / Move Tool / Scale Tool / Insert Keys Tool (Maya 2022: select, move
# nearest picked key, insert)
DOPE_ICONS = (
    ("key_select_tool", 'RESTRICT_SELECT_OFF', None, "Select keys"),
    ("key_move_tool", 'ORIENTATION_CURSOR', ("transform.transform", {"mode": 'TIME_TRANSLATE'}), "Move Tool"),
    ("key_scale_tool", 'FULLSCREEN_ENTER', ("transform.transform", {"mode": 'TIME_SCALE'}), "Scale Tool"),
    ("key_insert_tool", 'KEY_HLT', "action.keyframe_insert", "Insert Keys Tool"),
    "|", "STATS", "|",
    ("frame_all", 'ZOOM_ALL', "action.view_all", "Frame all"),
    ("frame_range", 'PREVIEW_RANGE', "anim.scene_range_frame", "Frame playback range"),
    ("center_time", 'TIME', "action.view_frame", "Scroll the view so the current time sits in the middle"),
    "|",
    ("hierarchy_below", 'OUTLINER', ("prop", "window_manager.allset_hierarchy_below", {}), "Show the hierarchy below"),
    "|",
    ("list_auto_load", 'LINKED', ("prop", "window_manager.allset_auto_load", {}),
     "Auto load Dope Sheet on selection"),
    ("list_load", 'FILE_REFRESH', ("allset.graph_list", {"action": "LOAD"}), "Load the selected objects"),
    "|",
    ("dope_time_snap", 'SNAP_ON', ("prop", "tool_settings.use_snap_anim", {}), "Time snap"),
    "|",
    ("open_graph_editor", 'GRAPH', ("allset.open_editor", {"ui_type": 'FCURVES'}), "Open the Graph Editor"),
    ("open_dope_sheet", 'ACTION', ("allset.open_editor", {"ui_type": 'DOPESHEET'}), "Open the Dope Sheet"),
    ("open_time_editor", 'NLA', ("allset.open_editor", {"ui_type": 'NLA_EDITOR'}), "Open the Time Editor"),
)

_UVE = "space_data.uv_editor"
UV_ICONS = (
    ("uv_wireframe", 'SHADING_WIRE', ("prop", f"{_UVE}.show_faces", {"value": False}),
     "Display the UVs as wireframe"),
    ("uv_shaded", 'SHADING_SOLID', ("prop", f"{_UVE}.show_faces", {"value": True}),
     "Shade the UV shells"),
    ("uv_distortion", 'MOD_UVPROJECT', ("prop", f"{_UVE}.show_stretch", {}), "Display UV distortion"),
    "|",
    ("texture_borders", 'MOD_EDGESPLIT', ("prop", "window_manager.allset_uv_texture_borders", {}), "Display texture borders"),
    ("shell_borders", 'MESH_DATA', ("prop", "window_manager.allset_uv_shell_borders", {}), "Display shell borders"),
    "|",
    ("grid_show", 'GRID', ("prop", "space_data.overlay.show_grid_background", {}), "Display the grid"),
    ("isolate_selected", 'HIDE_OFF', "allset.uv_isolate", "Isolate select"),
    "|",
    ("uv_snapshot", 'IMAGE_DATA', "uv.export_layout", "UV snapshot"),
    "|",
    ("checker_tiles", 'TEXTURE', "allset.checker_toggle", "Checker tiling"),
    "IMAGE",
    ("image_channels", 'IMAGE_RGB_ALPHA', ("channels", "space_data.display_channels", {}), "Image channels"),
    ("image_dim", 'LIGHT', ("prop", "window_manager.allset_uv_image_dim", {}), "Dim the image"),
    "|", "UVMAP",
)

def _hsg(action):
    return ("allset.hs_graph", {"action": action})


# Maya Hypershade graph toolbar (kit button names + tooltips); actions run in the Hypershade's graph (ui/hypershade_graph.py)
HS_GRAPH_ICONS = (
    ("show_inputs", 'BACK', _hsg("UPSTREAM"), "Input connections"),
    ("show_inputs_outputs", 'ARROW_LEFTRIGHT', _hsg("BOTH"), "Input and output connections"),
    ("show_outputs", 'FORWARD', _hsg("DOWNSTREAM"), "Output connections"),
    "|",
    ("graph_clear", 'X', None, "Clear graph"),
    ("graph_add_selected", 'ADD', None, "Add selected nodes to graph"),
    ("graph_remove_selected", 'REMOVE', None, "Remove selected nodes from graph"),
    ("graph_rearrange", 'NODETREE', None, "Rearrange graph"),
    ("graph_materials", 'MATERIAL', ("allset.hs_edit", {"action": "FROM_OBJECT"}),
     "Graph materials on selected objects"),
    "|",
    ("attrs_hidden", 'COLLAPSEMENU', _hsg("COLLAPSE"), "Hide attributes on selected nodes"),
    ("attrs_connected", 'LINKED', _hsg("CONNECTED"), "Show connected attributes on selected nodes"),
    ("attrs_primary", 'ALIGN_JUSTIFY', _hsg("SHOW_ALL"), "Show primary attributes on selected nodes"),
    ("attrs_custom", 'PRESET', None, "Show attributes from custom attribute view"),
    ("attr_filter", 'FILTER', None, "Toggle the display of the attribute filter field on selected nodes"),
    ("swatch_size", 'IMAGE_PLANE', _hsg("PREVIEW"), "Toggle the icon swatch size of selected nodes to "
     "small/large"),
    "|",
    ("tab_reopen", 'LOOP_BACK', None, "Restore last closed tab"),
)
ICONS = {GE: GRAPH_ICONS, DS: DOPE_ICONS, UV: UV_ICONS, "Hypershade": HS_GRAPH_ICONS}

# Notices of the greyed icon buttons (same form as ui/notices.NOTICES)
NOTICES = {
    "key_nearest_tool": ("Drag a key", "Blender's Graph Editor / Dope Sheet always move the key under the mouse when you "
                      "drag it: no tool to pick."),
    "key_select_tool": ("Click / box select", "Blender selects keys with a click or a box drag: no tool to pick."),
    "key_lattice_tool": ("Scale (S)", "Blender has no lattice for keys: scale the selected keys with S."),
    "key_grab_tool": ("Move keys (G)", "Blender has no brush that drags keys: select keys and move them with G "
                          "(proportional editing for a soft pull)."),
    "key_smear_tool": ("Move keys (G)", "Blender has no smear brush for keys: move the selected keys with G and "
                           "proportional editing."),
    "value_snap": ("Snap", "Blender snaps keys to frames only (Edit > Snap, time snap button)."),
    "texture_borders": ("Seams", "Blender draws seams in the 3D View, not texture borders here."),
    "shell_borders": ("Select Linked", "Blender doesn't draw shell borders in the UV Editor: select a "
                                "shell with Select > Select Linked."),
    "isolate_selected": ("Hide", "Blender isolates UVs by hiding the rest (H / Shift+H)."),
    "graph_clear": ("Pin", "Blender's graph always shows the whole material: pin another material to change "
                         "what it shows."),
    "graph_add_selected": ("Pin", "Blender's graph shows one material's whole network: nodes can't be added to it "
                          "from elsewhere."),
    "graph_remove_selected": ("Hide attributes", "Blender's graph shows the whole network: collapse nodes instead."),
    "graph_rearrange": ("Move nodes", "Blender has no automatic node layout: move nodes with G."),
    "attrs_custom": ("Not in Blender", "Blender has no custom attribute views on nodes."),
    "attr_filter": ("Not in Blender", "Blender's nodes have no attribute filter field."),
    "tab_reopen": ("Not in Blender", "Blender's graph has one tab (one material at a time)."),
}
