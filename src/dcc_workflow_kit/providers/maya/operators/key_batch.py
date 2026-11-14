# SPDX-License-Identifier: GPL-3.0-or-later
"""Keys: Shift+G repeat last at the mouse position, Ctrl+Shift+C camera from
the view.

- Shift+G = Maya's Repeat Last at the mouse position:
  the point on the
  ground plane under the mouse, then the last action again, then the (new) selection moved there.
- Ctrl+Shift+C = Maya's View > Create Camera From View hotkey: a copy of the view's camera
  (``operators/camera_copy.py``).
"""

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

from .. import results
from . import create

# Blender's viewport lens is defined on a 72 mm sensor (BKE_camera_params_from_view3d: lens on the 36 mm default
# sensor with CAMERA_PARAM_ZOOM_INIT_PERSP 2): a camera on 36 mm needs half the lens.
VIEW_SENSOR = 72.0


def ground_point(origin, direction, eps=1e-6):
    """Where the view ray ``origin + t * direction`` (t > 0) meets Maya's ground plane (Y = 0 -> Blender Z = 0);
    None when the ray runs along the plane or away from it."""
    if abs(direction.z) < eps:
        return None
    t = -origin.z / direction.z
    if t <= 0:
        return None
    return origin + direction * t


def mouse_point(region, rv3d, mouse):
    """Maya autoPlace -um: the ground plane under the mouse, else the view plane through the world origin."""
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse)
    p = ground_point(Vector(origin), Vector(direction))
    if p is None:
        p = view3d_utils.region_2d_to_location_3d(region, rv3d, mouse, Vector((0.0, 0.0, 0.0)))
    return Vector(p)


def move_to(objects, point):
    """Maya ``move x y z`` (absolute): each object's pivot (the origin) goes to ``point``. Children of
    another moved object follow their parent."""
    moved = set(objects)
    for ob in objects:
        if ob.parent in moved:
            continue
        mw = ob.matrix_world.copy()
        mw.translation = point
        ob.matrix_world = mw


class ALLSET_OT_repeat_at_mouse(bpy.types.Operator):
    """Repeat the last action and move the result to the mouse position (Maya Shift+G)"""
    bl_idname = "allset.repeat_at_mouse"
    bl_label = "Repeat Last at Mouse Position"
    # Not REGISTER: it must not become the "last operator" itself, or the next Shift+G repeats the
    # move instead of the create (Maya repeats the command every time).
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        region, rv3d = context.region, context.region_data
        if region is None or region.type != 'WINDOW' or rv3d is None:
            return {'PASS_THROUGH'}
        point = mouse_point(region, rv3d, (event.mouse_region_x, event.mouse_region_y))
        from . import repeat_maya
        try:
            res = repeat_maya.repeat(context, inside_undo_op=True)   # Maya repeatLast, menu commands too
        except RuntimeError as ex:
            self.report({'WARNING'}, f"Nothing to repeat ({ex})")
            return {'CANCELLED'}
        if res is None:
            self.report({'WARNING'}, "Nothing to repeat")
            return {'CANCELLED'}
        if context.mode == 'OBJECT' and context.selected_objects:
            move_to(list(context.selected_objects), point)
        return {'FINISHED'}


def camera_matrix(view_matrix):
    """The camera world matrix that sees what the view sees (both look down their local -Z)."""
    return view_matrix.inverted()


class ALLSET_OT_camera_from_view(bpy.types.Operator):
    """Copy this view's camera and look through the copy (Maya View > Create Camera From View, Ctrl+Shift+C)"""
    bl_idname = "allset.camera_from_view"
    bl_label = "Create Camera From View"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def execute(self, context):
        from ..ui import panel_menus
        from . import camera_copy
        area = context.area
        space = area.spaces.active
        rv3d = context.region_data or space.region_3d
        if rv3d is None:
            return {'CANCELLED'}
        ob = camera_copy.make(context, space, rv3d, panel_menus.view_camera(context), create._maya_naming(context))
        panel_menus.look_through(context, area, ob)
        results.result(self, f"Created {ob.name} from the view")
        return {'FINISHED'}


classes = (ALLSET_OT_repeat_at_mouse, ALLSET_OT_camera_from_view)
