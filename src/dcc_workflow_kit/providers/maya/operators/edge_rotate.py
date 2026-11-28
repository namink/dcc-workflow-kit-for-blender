# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl+Shift+drag on a Rotate manipulator ring (or Ctrl+Shift+middle-drag with the Rotate tool) in mesh edit mode:
the selection rotates about the ring's axis as in a plain drag, with every vertex kept on one of its own edges
(Maya's edge transform constraint, operators/edge_constraint.py).

A ring drag turns by the angle the mouse sweeps around the manipulator's centre on screen, so the components follow
the mouse; a middle drag turns 0.36 degrees per pixel of horizontal movement (to the right = clockwise seen from the
axis tip), like Maya. Each preview puts the mesh back, rotates it with Blender's rotate (pivot point and
orientation as in a plain drag) and slides the vertices; the release does the same once more and leaves one undo
step. Esc / right click put everything back.
"""
import math

import bpy
from mathutils import Vector

from . import edge_constraint

DEG_PER_PX = 0.36


def sweep(c, a, b):
    """Signed screen angle (radians, counter-clockwise) from point ``a`` to ``b`` around ``c``."""
    va, vb = (a[0] - c[0], a[1] - c[1]), (b[0] - c[0], b[1] - c[1])
    return math.atan2(va[0] * vb[1] - va[1] * vb[0], va[0] * vb[0] + va[1] * vb[1])


def toward_viewer(rv3d, point):
    """Unit vector from ``point`` toward the eye."""
    if rv3d.is_perspective:
        eye = rv3d.view_matrix.inverted().translation
        v = eye - point
        if v.length > 1e-9:
            return v.normalized()
    return (rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))).normalized()


class ALLSET_OT_edge_rotate(bpy.types.Operator):
    """Rotate the selected components while keeping every vertex on one of its edges (Maya Ctrl+Shift+drag with the
    Rotate tool)"""
    bl_idname = "allset.edge_rotate"
    bl_label = "Rotate"
    # not REGISTER / UNDO: the release pushes the one undo step itself (the previews make none)
    bl_options = {'INTERNAL', 'BLOCKING'}

    axis: bpy.props.EnumProperty(items=[(a, a, "") for a in ('X', 'Y', 'Z', 'VIEW')], default='Z',
                                 options={'SKIP_SAVE'})
    orient_type: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    button: bpy.props.EnumProperty(items=(('LEFTMOUSE', "Left", ""), ('MIDDLEMOUSE', "Middle", "")),
                                   default='LEFTMOUSE', options={'SKIP_SAVE'})
    # tests: the angle (radians, about the axis, right hand) to apply without a drag
    angle: bpy.props.FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def _setup(self, context):
        from . import manip_scale
        from ..ui import manipulator
        center, frame, otype = manipulator.pivot_frame(context, 'ROTATE')
        if center is None:
            return False
        if not self.orient_type:
            self.orient_type = otype
        self._center, self._frame = center, frame
        self._state = manip_scale.save_state(context)
        self._prep = edge_constraint.prepare(context)
        return True

    def _rotate(self, context, angle):
        """Put the mesh back, turn it by ``angle`` (right hand about the axis) and slide the vertices."""
        from . import manip_scale
        manip_scale.restore(self._state)
        kwargs = {"value": -angle, "snap": False, "mirror": True}     # Blender's value turns the other way
        if self.axis == 'VIEW':
            kwargs.update(orient_axis='Z', orient_type='VIEW')
        else:
            kwargs.update(orient_axis=self.axis, orient_type=self.orient_type or 'GLOBAL',
                          constraint_axis=tuple(a == self.axis for a in 'XYZ'))
        # auto-merge / UV correction stay off: they would act on the points before they are put on their edges
        try:
            with manip_scale._Quiet(context.scene.tool_settings):
                bpy.ops.transform.rotate('EXEC_DEFAULT', **kwargs)
        except (RuntimeError, TypeError) as ex:
            print("allset: edge rotate failed", ex)
            return
        edge_constraint.apply(self._prep)

    def execute(self, context):
        if not self._setup(context):
            return {'CANCELLED'}
        self._rotate(context, self.angle)
        bpy.ops.ed.undo_push(message="Rotate")
        return {'FINISHED'}

    def invoke(self, context, event):
        region, rv3d = context.region, context.region_data
        if region is None or rv3d is None or not self._setup(context):
            return {'PASS_THROUGH'}
        from bpy_extras.view3d_utils import location_3d_to_region_2d
        c = location_3d_to_region_2d(region, rv3d, self._center)
        self._c = (c.x, c.y) if c is not None else (region.width / 2, region.height / 2)
        self._press = (event.mouse_region_x, event.mouse_region_y)
        self._last = self._press
        self._sweep = 0.0
        if self.axis == 'VIEW':
            self._sign = 1.0                    # the view axis points at the eye
        else:
            a = self._frame.col['XYZ'.index(self.axis)]
            self._sign = 1.0 if a.dot(toward_viewer(rv3d, self._center)) >= 0.0 else -1.0
        self.angle = 0.0
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _angle(self, event):
        pos = (event.mouse_region_x, event.mouse_region_y)
        if self.button == 'MIDDLEMOUSE':
            return -math.radians((pos[0] - self._press[0]) * DEG_PER_PX)
        self._sweep += sweep(self._c, self._last, pos)       # summed, so a drag can go round more than once
        self._last = pos
        return self._sweep * self._sign

    def _end(self, context):
        if context.area is not None:
            context.area.header_text_set(None)
            context.area.tag_redraw()

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self.angle = self._angle(event)
            self._rotate(context, self.angle)
            if context.area is not None:
                context.area.header_text_set(f"Rotate: {math.degrees(self.angle):.2f}")
            return {'RUNNING_MODAL'}
        if event.type == self.button and event.value == 'RELEASE':
            self._rotate(context, self.angle)
            bpy.ops.ed.undo_push(message="Rotate")
            self._end(context)
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            from . import manip_scale
            manip_scale.restore(self._state)
            self._end(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


classes = (ALLSET_OT_edge_rotate,)
