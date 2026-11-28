# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Visualize > Create Turntable.

Maya:
- With objects selected, a copy of the active view's camera (``turnTableCamera<N>``, every camera setting and where
  it is) goes under a new group (``group<N>``, translate 0, pivot at the centre of the selection's bounding box);
  the group's Rotate Y gets two keys, 0 at frame 1 and a full turn (+360, or -360 for the other direction) at the
  last frame of the turn (the option box sets the number of frames, 24 to start with), with auto tangents and
  constant infinity: one turn, then the camera stays where it started.
- The active view then looks through the new camera; the selection, the time range and the current time don't
  change.
- Nothing selected, or no 3D view to run it from: a message, and nothing is made.

Kit: the group is an Empty whose pivot (origin + ``delta_location``, like every kit pivot) is the bounding-box centre;
Maya's Rotate Y is the Blender world up axis, rotation Z. The camera is made like View > Create Camera From View
(operators/camera_copy.py) and keeps its world place under the group. The messages: "Turntable: select one or more
objects first." and "Turntable: run it from a 3D View."
"""

import math

import bpy
from bpy.props import EnumProperty, IntProperty
from mathutils import Vector

from .. import i18n, results

NOTHING_SELECTED = i18n.mark("Turntable: select one or more objects first.")
NO_VIEW = i18n.mark("Turntable: run it from a 3D View.")
START_FRAME = 1
DIRECTIONS = (('COUNTERCLOCKWISE', "Counterclockwise", "The camera goes around counterclockwise seen from above"),
              ('CLOCKWISE', "Clockwise", "The camera goes around clockwise seen from above"))


def turn_keys(frames, direction):
    """The group's two Rotate Y keys: [(frame, degrees)] for a turn of ``frames`` frames from frame 1."""
    frames = max(int(frames), 2)
    end = 360.0 if direction == 'COUNTERCLOCKWISE' else -360.0
    return [(float(START_FRAME), 0.0), (float(START_FRAME + frames - 1), end)]


def bounds_centre(objects, depsgraph=None):
    """The centre of the world bounding box around ``objects`` (their evaluated geometry; an object without any:
    its origin)."""
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for ob in objects:
        ev = ob.evaluated_get(depsgraph) if depsgraph is not None else ob
        corners = [ev.matrix_world @ Vector(c) for c in ev.bound_box] if ob.type not in {'EMPTY', 'CAMERA', 'LIGHT'} \
            else [ob.matrix_world.translation.copy()]
        for p in corners:
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
    if lo.x == math.inf:
        return Vector((0.0, 0.0, 0.0))
    return (lo + hi) / 2.0


def _view(context):
    """(window, area, region) of the 3D View the turntable copies: the one this runs in, else the largest of the
    window (the main menu bar is in the top bar); (None, None, None) without one."""
    area = context.area
    if area is not None and area.type == 'VIEW_3D':
        region = context.region if context.region is not None and context.region.type == 'WINDOW' else \
            next((r for r in area.regions if r.type == 'WINDOW'), None)
        return context.window, area, region
    from ..ui.menu_item_ops import _view3d
    return _view3d(context)


def create_turntable(context, objects, frames=24, direction='COUNTERCLOCKWISE'):
    """Build the turntable around ``objects``; returns (group, camera) or raises ValueError with Maya's message."""
    if not objects:
        raise ValueError(NOTHING_SELECTED)
    window, area, region = _view(context)
    if area is None:
        raise ValueError(NO_VIEW)
    from . import camera_copy, create, group, pivot
    from ..ui import panel_cameras
    space = area.spaces.active
    rv3d = space.region_3d
    with context.temp_override(window=window, area=area, region=region):
        source = panel_cameras.view_camera(bpy.context)
    selected, active = list(context.selected_objects), context.view_layer.objects.active
    centre = bounds_centre(objects, context.evaluated_depsgraph_get())

    grp = group.make_group(context, [])
    pivot.match_pivot(grp, centre)
    cam = camera_copy.make(context, space, rv3d, source, create._maya_naming(context))
    name = camera_copy.copy_name("turnTableCamera")
    cam.name, cam.data.name = name, f"{name}Shape"
    if cam.users_collection and grp.users_collection and cam.users_collection[0] != grp.users_collection[0]:
        grp.users_collection[0].objects.link(cam)
        cam.users_collection[0].objects.unlink(cam)
    context.view_layer.update()
    group.set_parent_keep_world(cam, grp)

    from . import graph_key_menu
    grp.rotation_mode = 'XYZ'
    for frame, degrees in turn_keys(frames, direction):
        grp.rotation_euler[2] = math.radians(degrees)
        grp.keyframe_insert("rotation_euler", index=2, frame=frame)
        graph_key_menu.after_insert(grp, "rotation_euler", 2, frame)
    grp.rotation_euler[2] = 0.0
    context.scene.frame_set(context.scene.frame_current)     # the group back to the current frame's turn

    for ob in context.selected_objects:
        ob.select_set(ob in selected)
    context.view_layer.objects.active = active
    with context.temp_override(window=window, area=area, region=region):
        panel_cameras.look_through(bpy.context, area, cam)
    return grp, cam


class ALLSET_OT_create_turntable(bpy.types.Operator):
    """Turn a new camera once around the selected objects and look through it (Maya Visualize > Turntable)"""
    bl_idname = "allset.create_turntable"
    bl_label = "Create Turntable"
    bl_options = {'REGISTER', 'UNDO'}

    frames: IntProperty(name="Number of frames", default=24, min=2, soft_max=1000,
                        description="Frames for one full turn, from frame 1")
    direction: EnumProperty(name="Direction", items=DIRECTIONS, default='COUNTERCLOCKWISE')

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            grp, cam = create_turntable(context, list(context.selected_objects), self.frames, self.direction)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        results.result(self, f"{grp.name} {cam.name}")
        return {'FINISHED'}


classes = (ALLSET_OT_create_turntable,)
