# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Maya-style UI: Channel Box, Layer Editor, Attribute Editor, Outliner (3D View
sidebar), menu bar + menu sets, Status Line (top bar), Shelf (strip under it), Time
Slider + Range Slider (Timeline header), viewport panel menus (3D View header), Maya grid, view furniture and selection wire (3D View),
Tool Box (3D View toolbar) and the Maya dock areas / floating panels (maya_dock, step 116).

Blender's Python UI can't replace every C-drawn part; the modules note where they work around it.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from . import attribute_editor, cb_channels, cb_points, workspaces, editor_chrome, file_project, render_settings, script_editor, input_line, graph_editor, graph_units, graph_view, hypershade, light_editor, render_view, channel_box, dock_tabs, layer_editor, maya_grid, maya_outliner, menu_sets, outliner_sets, notices, outliner, creation_inputs, in_view, manipulator, mesh_tools, modeling_toolkit, uv_toolkit, paint_weights, weight_numbers, panel_menus, camera_tools, light_link_editor, set_driven_key, shelf, selection_wire, component_colors, status_line, time_slider, tool_settings, toolbox, view_furniture, view_message, range_bar, status_icons, kit_icons, panel_toolbar, maya_dock, soft_overlay, save_prompt, scene_carry, armature_mode_pulse
from . import mesh_tools_poly
from . import mesh_tools_loop
from . import uv_display
from . import uv_hud
from . import hs_drag
from . import ghosting
from . import reference_editor
from . import outliner_joints
from . import outliner_order
from . import marked_window, component_editor, shape_editor, connection_editor
from . import hotkey_editor
from . import maya_prefs
_modules = (status_icons, kit_icons, notices, input_line, cb_points, channel_box, cb_channels, creation_inputs, layer_editor, attribute_editor, outliner, menu_sets, workspaces, file_project, status_line, shelf, time_slider, panel_menus, panel_toolbar, camera_tools, light_link_editor, maya_grid, view_furniture, selection_wire, component_colors, ghosting, toolbox, dock_tabs, maya_outliner, outliner_joints, outliner_sets, outliner_order, paint_weights, weight_numbers, manipulator, set_driven_key, modeling_toolkit, mesh_tools, mesh_tools_poly, mesh_tools_loop, in_view, uv_toolkit, uv_display, uv_hud, hypershade, hs_drag, light_editor, render_view, graph_editor, graph_units, graph_view, editor_chrome, render_settings, script_editor, reference_editor, marked_window, component_editor, shape_editor, connection_editor, hotkey_editor, maya_prefs, view_message, range_bar, tool_settings, maya_dock, soft_overlay, save_prompt, scene_carry, armature_mode_pulse)

def register():
    from ....lifecycle import activate
    activate(__name__, [(mod.register, mod.unregister) for mod in _modules])

def unregister():
    from ....lifecycle import deactivate
    deactivate(__name__)
