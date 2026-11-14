# SPDX-License-Identifier: GPL-3.0-or-later
"""Compact combined Move / Rotate / Scale manipulator for modern Smart Extrude."""
import math

import bmesh
import bpy
from bpy_extras import view3d_utils
from mathutils import Euler, Matrix, Vector

from . import in_view, manipulator
from ..operators import smart_extrude as smart, smart_geometry

ROTATE_SIZE = .55  # keep edge-on rings away from the arrow tips and scale boxes


def widget_frame(context):
    drag = smart.DRAG
    if drag is not None:
        session = drag._session
        params = drag._display_params
        centre = session.centre + session.axes @ (Vector(params['translation'])*session.unit)
        axes = session.axes @ Euler(tuple(params['rotation']), 'XYZ').to_matrix()
        return centre, axes
    saved = smart.display(context)
    if saved is not None:
        session, params = saved
        return (session.centre + session.axes @ (Vector(params['translation'])*session.unit),
                session.axes @ Euler(params['rotation'], 'XYZ').to_matrix())
    ob = context.edit_object
    if ob is None:
        return None
    bm = bmesh.from_edit_mesh(ob.data)
    faces = smart_geometry.selected_faces(bm, context.tool_settings.mesh_select_mode)
    if not faces:
        return None
    try:
        settings = context.scene.allset_smart_extrude
        return smart.frame(context, faces if settings.together else faces[:1], settings.orientation)
    except smart_geometry.GeometryError:
        return None


def handles_hit(context, region, rv3d, mouse, reach):
    if not smart.active(context):
        return False
    frame = widget_frame(context)
    if frame is None:
        return False
    centre, axes = frame
    c2 = view3d_utils.location_3d_to_region_2d(region, rv3d, centre)
    if c2 is None:
        return False
    pixels = in_view.unit_px(context)
    world_pixel = (view3d_utils.region_2d_to_location_3d(region, rv3d, c2+Vector((1, 0)), centre)-centre).length
    unit = pixels*world_pixel
    mouse = Vector(mouse)

    def near(a, b):
        if a is None or b is None:
            return False
        delta = b-a
        t = max(0., min(1., (mouse-a).dot(delta)/delta.length_squared)) if delta.length_squared > 1e-8 else 0.
        return (mouse-(a+delta*t)).length <= reach+3

    def project(p):
        return view3d_utils.location_3d_to_region_2d(region, rv3d, centre+axes @ p*unit)

    for i in range(3):
        v = Vector((0, 0, 0))
        v[i] = 1.08
        if near(c2, project(v)):
            return True
        ring = []
        for j in range(49):
            p = Vector()
            p[(i+1)%3] = ROTATE_SIZE*math.cos(j*math.tau/48)
            p[(i+2)%3] = ROTATE_SIZE*math.sin(j*math.tau/48)
            ring.append(project(p))
        if any(near(a, b) for a, b in zip(ring, ring[1:])):
            return True
    return False


class ALLSET_GGT_smart_extrude(bpy.types.GizmoGroup):
    bl_idname = "ALLSET_GGT_smart_extrude"
    bl_label = "Smart Extrude"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D'}

    @classmethod
    def poll(cls, context):
        return smart.active(context) and context.space_data.show_gizmo

    def setup(self, context):
        self.handles = []
        for kind in ('TRANSLATE', 'SCALE', 'ROTATE'):
            for i, axis in enumerate('XYZ'):
                if kind == 'ROTATE':
                    gz = self.gizmos.new("GIZMO_GT_dial_3d")
                    gz.draw_options = {'CLIP'}
                else:
                    gz = self.gizmos.new(in_view.ALLSET_GT_extrude_handle.bl_idname)
                    gz.build(('T' if kind == 'TRANSLATE' else 'S')+axis)
                op = gz.target_set_operator('allset.smart_extrude_drag')
                op.kind, op.axis = kind, i
                gz.color = manipulator.axis_colours()[axis]
                gz.color_highlight = manipulator.YELLOW
                gz.alpha, gz.alpha_highlight = .8, 1.
                gz.line_width = 1.5
                gz.use_draw_scale = True
                gz.use_draw_modal = True
                in_view._no_tooltip(gz)
                self.handles.append((gz, kind, axis))
        gz = self.gizmos.new(in_view.ALLSET_GT_extrude_handle.bl_idname)
        gz.build('S')
        op = gz.target_set_operator('allset.smart_extrude_drag')
        op.kind, op.axis = 'SCALE', -1
        gz.color, gz.color_highlight = in_view.CENTER_COLOUR, manipulator.YELLOW
        gz.alpha = gz.alpha_highlight = 1.
        gz.use_draw_scale = True
        gz.use_draw_modal = True
        self.handles.append((gz, 'SCALE', None))

    def draw_prepare(self, context):
        frame = widget_frame(context)
        for gz, kind, axis in self.handles:
            gz.hide = frame is None
            if frame is None:
                continue
            centre, axes = frame
            rot = (axes @ manipulator._axis_rot(axis)) if axis else context.region_data.view_rotation.to_matrix()
            gz.matrix_basis = Matrix.Translation(centre) @ rot.to_4x4()
            gz.scale_basis = manipulator.scale_basis(context)*in_view.SIZE*(ROTATE_SIZE if kind == 'ROTATE' else 1.)


class ALLSET_TL_smart_extrude(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'EDIT_MESH'
    bl_idname = smart.TOOL
    bl_label = "Smart Extrude"
    bl_description = "Drag arrows to grow or carve; rings rotate, boxes scale. J snaps, Esc cancels the drag"
    bl_icon = "ops.mesh.extrude_region_move"
    bl_widget = ALLSET_GGT_smart_extrude.bl_idname
    bl_options = {'KEYMAP_FALLBACK'}
    bl_keymap = (("allset.smart_extrude_drag", {'type': 'MIDDLEMOUSE', 'value': 'PRESS'},
                 {'properties': [('kind', 'TRANSLATE'), ('axis', 2)]}),)

    @staticmethod
    def draw_settings(context, layout, tool):
        settings = context.scene.allset_smart_extrude
        layout.prop(settings, 'orientation', text="")
        layout.prop(settings, 'together')
        if context.region.type != 'TOOL_HEADER':
            layout.label(text="Arrows: Move · Rings: Rotate · Boxes: Scale")
            layout.label(text="J: Snap · Type a value · Esc: Cancel drag")


def register():
    bpy.utils.register_class(ALLSET_GGT_smart_extrude)
    # no separator: inside a tool group it becomes a None entry that breaks Blender's tool cycling (T in edit mode)
    bpy.utils.register_tool(ALLSET_TL_smart_extrude, after={'builtin.extrude_region'})


def unregister():
    bpy.utils.unregister_tool(ALLSET_TL_smart_extrude)
    bpy.utils.unregister_class(ALLSET_GGT_smart_extrude)
