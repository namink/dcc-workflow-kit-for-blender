# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Maya-behaviour operators (group, pick-walk, hold/tap snap, pivot, freeze, parent,
duplicate, delete history, create, visibility, ...).

Operator ids use the ``allset.`` prefix. Each module lists its classes in
``classes``; they are registered in that order.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
import bpy
from . import auto_key, bookmarks, ik_fk, component, create, curve_tools, curves_maya, cut_sew, display, driven_key, duplicate, extrude, file_io, freeze, option_windows, fx, global_keys4, graph_keys, graph_key_menu, deformer_weights, joint_labels, group, history, hold, joints, pivot_menu, key_batch, key_batch3, key_insert, loop_pick, manip, marquee, anim_layers, lights, light_links, material, menu_extras, menu_items, mesh_maya, multi_cut, poly_maya, rig_maya, mesh_tools, outliner_drag, parenting, pickwalk, pivot, playblast, preselect, project, render_persp, rig_tools, select_convert, select_priority, sets, shading_maps, skin, snap_align, soft_select, symmetry, taphold, time_keys, tool_keys, units, uv_shells, uv_tools, uv_modify, uv_select_178, view, view_keys3, visibility
from . import poly_draw, quad_draw
from . import edge_loops
from . import ik_rp
from . import joint_edit
classes = (*display.classes, *group.classes, *hold.classes, *taphold.classes, *pickwalk.classes, *view.classes, *freeze.classes, *parenting.classes, *duplicate.classes, *history.classes, *create.classes, *visibility.classes, *component.classes, *manip.classes, *material.classes, *marquee.classes, *preselect.classes, *select_priority.classes, *menu_extras.classes, *tool_keys.classes, *symmetry.classes, *pivot.classes, *snap_align.classes, *time_keys.classes, *joints.classes, *skin.classes, *driven_key.classes, *rig_tools.classes, *mesh_maya.classes, *mesh_tools.classes, *extrude.classes, *uv_tools.classes, *uv_shells.classes, *uv_modify.classes, *light_links.classes, *anim_layers.classes, *uv_select_178.classes, *shading_maps.classes, *fx.classes, *project.classes, *graph_keys.classes, *graph_key_menu.classes, *deformer_weights.classes, *joint_labels.classes, *ik_fk.classes, *playblast.classes, *key_batch.classes, *cut_sew.classes, *multi_cut.classes, *outliner_drag.classes, *key_insert.classes, *view_keys3.classes, *global_keys4.classes, *pivot_menu.classes, *sets.classes, *menu_items.classes, *file_io.classes, *option_windows.classes, *key_batch3.classes, *bookmarks.classes, *curve_tools.classes, *curves_maya.classes, *poly_maya.classes, *rig_maya.classes, *loop_pick.classes, *render_persp.classes, *select_convert.classes, *poly_draw.classes, *quad_draw.classes, *edge_loops.classes)
from . import deformers
classes += deformers.classes
from . import default_light, render_batch
classes += render_batch.classes
from . import curve_draw
classes += curve_draw.classes
from . import dag
classes += dag.classes
from . import by_type
classes += by_type.classes
from . import modify_maya
classes += modify_maya.classes
from . import deform_edit
classes += deform_edit.classes
from . import select_2d
classes += select_2d.classes
from . import anim_snapshot
classes += anim_snapshot.classes
from . import repeat_maya
classes += repeat_maya.classes
from . import surfaces_maya
classes += surfaces_maya.classes
from . import character_sets
classes += character_sets.classes
from . import color_sets_maya, normals_maya
classes += normals_maya.classes + color_sets_maya.classes
from . import poly_cleanup
classes += poly_cleanup.classes
from . import graph_buffers, graph_menu_198, graph_retime, graph_weights
classes += graph_retime.classes + graph_buffers.classes + graph_weights.classes + graph_menu_198.classes
from . import constrain_199, skin_tools_199
classes += skin_tools_199.classes + constrain_199.classes
from . import graph_curves_203
classes += graph_curves_203.classes
from . import anim_layers_204
classes += anim_layers_204.classes
from . import pins_205
classes += pins_205.classes
from . import deformers_205b
classes += deformers_205b.classes
from . import deformers_205a
classes += deformers_205a.classes
from . import uv_206
classes += uv_206.classes
from . import curves_207
classes += curves_207.classes
from . import references
classes += references.classes
from . import maya_lights
from . import weight_paint
classes += weight_paint.classes
from . import bake_maya
classes += bake_maya.classes
from . import controllers
classes += controllers.classes
from . import deformer_order
classes += deformer_order.classes
from . import game_exporter, motion_trail
classes += game_exporter.classes
classes += motion_trail.classes
from . import constrain_multi, control_shapes, wire_color
classes += control_shapes.classes + wire_color.classes + constrain_multi.classes
from . import constrain_interp
classes += constrain_interp.classes
from . import blend_shapes_227, pose_space_227
classes += blend_shapes_227.classes + pose_space_227.classes
from . import flow_path_228, motion_path_228
classes += motion_path_228.classes + flow_path_228.classes
from . import skeleton_menu
classes += skeleton_menu.classes
from . import skin_basics
classes += skin_basics.classes
from . import joint_display
classes += joint_display.classes
from . import skin_method
from . import uv_shell_select
classes += uv_shell_select.classes
(_register_classes, _unregister_classes) = bpy.utils.register_classes_factory(classes)

def register():
    from ....lifecycle import activate
    activate(__name__ + '.register', [(extrude.register_handlers, extrude.unregister_handlers), (taphold.register_bindings, taphold.unregister_bindings), (graph_keys.register_bindings, graph_keys.unregister_bindings), (graph_key_menu.register_bindings, graph_key_menu.unregister_bindings), (deformer_weights.register_bindings, deformer_weights.unregister_bindings), (joint_labels.register_bindings, joint_labels.unregister_bindings), (view.register_timer, view.unregister_timer), (units.register_handler, units.unregister_handler), (tool_keys.register_timer, tool_keys.unregister_timer), (symmetry.register_handler, symmetry.unregister_handler), (soft_select.register_handlers, soft_select.unregister_handlers), (pivot.register_handler, pivot.unregister_handler), (project.register_handlers, project.unregister_handlers), (preselect.register_handlers, preselect.clear), (cut_sew.register_handlers, cut_sew.unregister_handlers), (multi_cut.register_handlers, multi_cut.unregister_handlers), (poly_draw.register_handlers, poly_draw.unregister_handlers), (quad_draw.register_handlers, quad_draw.unregister_handlers), (outliner_drag.register_handlers, outliner_drag.unregister_handlers), (auto_key.register_handlers, auto_key.unregister_handlers), (repeat_maya.register_handlers, repeat_maya.unregister_handlers), (graph_retime.register_handlers, graph_retime.unregister_handlers), (graph_buffers.register_handlers, graph_buffers.unregister_handlers), (graph_weights.register_handlers, graph_weights.unregister_handlers)])

def unregister():
    from ....lifecycle import deactivate
    deactivate(__name__ + '.register')

def register_data():
    from ....lifecycle import activate
    activate(__name__ + '.register_data', [(_register_classes, _unregister_classes), (weight_paint.register_props, weight_paint.unregister_props), (ik_fk.register_props, ik_fk.unregister_props), (game_exporter.register_props, game_exporter.unregister_props), (motion_trail.register_props, motion_trail.unregister_props), (control_shapes.register_props, control_shapes.unregister_props), (wire_color.register_props, wire_color.unregister_props), (constrain_multi.register_props, constrain_multi.unregister_props), (constrain_interp.register_handlers, constrain_interp.unregister_handlers), (blend_shapes_227.register_props, blend_shapes_227.unregister_props), (pose_space_227.register_props, pose_space_227.unregister_props), (motion_path_228.register_props, motion_path_228.unregister_props), (flow_path_228.register_props, flow_path_228.unregister_props), (default_light.register, default_light.unregister), (joint_edit.register, joint_edit.unregister), (joint_display.register_props, joint_display.unregister_props), (skin_method.register_props, skin_method.unregister_props), (ik_rp.register_handlers, ik_rp.unregister_handlers), (snap_align.register_props, snap_align.unregister_props), (material.register_props, material.unregister_props), (lights.register_props, lights.unregister_props), (maya_lights.register, maya_lights.unregister), (light_links.register_props, light_links.unregister_props), (anim_layers.register_props, anim_layers.unregister_props), (driven_key.register_props, driven_key.unregister_props), (mesh_tools.register_props, mesh_tools.unregister_props), (poly_draw.register_props, poly_draw.unregister_props), (edge_loops.register_props, edge_loops.unregister_props), (uv_tools.register_props, uv_tools.unregister_props), (uv_shell_select.register_props, uv_shell_select.unregister_props), (fx.register_props, fx.unregister_props), (pivot_menu.register_props, pivot_menu.unregister_props), (sets.register_props, sets.unregister_props), (material.register_handlers, material.unregister_handlers), (dag.register_handlers, dag.unregister_handlers), (modify_maya.register_props, modify_maya.unregister_props), (anim_snapshot.register_handlers, anim_snapshot.unregister_handlers), (character_sets.register_props, character_sets.unregister_props), (graph_menu_198.register_props, graph_menu_198.unregister_props), (skin_tools_199.register_handlers, skin_tools_199.unregister_handlers), (constrain_199.register_handlers, constrain_199.unregister_handlers), (graph_curves_203.register_handlers, graph_curves_203.unregister_handlers), (pins_205.register_handlers, pins_205.unregister_handlers), (deformers_205b.register_handlers, deformers_205b.unregister_handlers), (deformers_205a.register_handlers, deformers_205a.unregister_handlers), (curves_207.register_handlers, curves_207.unregister_handlers)])

def unregister_data():
    from ....lifecycle import deactivate
    deactivate(__name__ + '.register_data')
    select_2d.unregister_timers()
    curve_draw.unregister_handlers()
    marquee.restore_all()
    preselect.clear()
    duplicate.PAIRS.clear()
    hold.unregister_cleanup()
    mesh_tools.clear()
    edge_loops.clear()
    render_batch.unregister()
