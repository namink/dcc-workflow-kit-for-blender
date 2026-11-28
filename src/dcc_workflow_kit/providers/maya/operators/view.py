# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya camera/view feel: ortho tumble lock, Alt+Shift axis-locked tumble/track, framing in all views,
view-change undo (``[`` / ``]``), Space-tap four-view toggle.

Code: view_nav (3D navigation), view_nav_2d (2D editors), view_frame (framing), view_history ([ / ] view undo); this
module keeps the four view toggle, the ortho camera width, Home, the persp view of Single Perspective, the classes
tuple and re-exports.
"""

import bpy
from mathutils import Vector

from . import units
from .view_nav import (ALLSET_OT_dolly, ALLSET_OT_emulated_tumble, ALLSET_OT_nav_chord,  # noqa: F401
                       ALLSET_OT_track_view, ALLSET_OT_tumble, ALLSET_OT_view_axis_lock, AXIS_THRESHOLD,
                       CHORD_BUTTONS, CHORD_MODES, CHORD_STARTS, DOLLY_PX_PER_DOUBLING, NAV_MODALS,
                       camera_navigation, choose_axis, chord_held, chord_mode, dolly_distance, drag_jump,
                       emulated_alt_drag, invert_zoom, locked_offset, start_chord_dolly, start_track, start_tumble,
                       tumble_locked, tumble_rotation)
from .view_nav_2d import (ALLSET_OT_dolly_2d, ALLSET_OT_nav_2d, NAV2D_RULES, NAV2D_ZOOM_PER_PX,  # noqa: F401
                          V2D_CLIPPED, dolly_2d_factor, dolly_2d_step, dolly_zoom_factor, nav2d_editor,
                          nav2d_mode, nav2d_rule, nav2d_zoom_delta, view2d_range)
from .view_frame import (ALLSET_OT_frame, ALLSET_OT_frame_all_views, camera_projection,  # noqa: F401
                         frame_camera, frame_points, frame_region, view3d_window_regions, view_camera,
                         visible_bounds)
from .view_history import (ALLSET_OT_view_history, POLL_INTERVAL, ViewHistory, capture,  # noqa: F401
                           history_for, poll_views, register_timer, restore, unregister_timer)

# --- Space tap: four views <-> single view -------------------------------------


# --- Maya-style ortho cameras ----------------------------------------------------------------------------
# The top / front / side cameras show 30 units across (Maya units). Blender's viewport ortho width along the longer side =
# view_distance x 72 / lens (distance 3 cm with lens 70 = 3.086 units across).
# The four view's panels are real 3D View areas that keep their own camera (ui/four_view.py).
MAYA_ORTHO_WIDTH = 30.0
FOUR_VIEW_NOTE = "each panel has its own camera, shading and Show settings, like Maya's"


def ortho_key(rv3d):
    """'TOP' / 'FRONT' / 'SIDE' (+ '-' for the opposite views) of an axis-aligned ortho pane, else None."""
    if rv3d is None or rv3d.view_perspective != 'ORTHO':
        return None
    d = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))     # view direction
    i = max(range(3), key=lambda k: abs(d[k]))
    if abs(d[i]) < 0.999:
        return None
    return ("SIDE", "FRONT", "TOP")[i] + ("-" if d[i] > 0 else "")


def maya_ortho_distance(space, scene=None):
    """view_distance that shows 30 units across an ortho pane of this 3D View."""
    from .units import maya_unit
    return MAYA_ORTHO_WIDTH * maya_unit(scene or bpy.context.scene) * space.lens / 72.0


class ALLSET_OT_toggle_quad_view(bpy.types.Operator):
    """Toggle the four view; leaving it keeps the panel under the cursor (Maya Space tap). Four real panels, each
    with its own camera, shading and Show settings"""
    bl_idname = "allset.toggle_quad_view"
    bl_label = "Toggle Four Views"

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        from ..ui import four_view
        four = four_view.is_four(context.window.screen)
        got = four_view.tap(context, context.area, context.window)
        if got in ("four", "single"):
            return {'FINISHED'}
        if got == "failed" and four and bpy.app.background:
            self.report({'WARNING'}, "Leaving the four view needs the Blender window")
        elif got == "failed" and not bpy.app.background:
            self.report({'WARNING'}, "This panel can't be split into the four view here")
        return {'CANCELLED'}


def _persp_store():
    # the hotbox's store (marking/modal.py ALLSET_OT_hb_view): one memory of the persp view per area
    from ..marking import modal
    return modal._persp_views


def remember_persp(area, space):
    """Keep the perspective view of a four view before leaving it (the panel under the cursor may be ortho)."""
    for rv3d in (space.region_3d, *space.region_quadviews):
        if rv3d is not None and rv3d.view_perspective == 'PERSP':
            _persp_store()[area.as_pointer()] = (rv3d.view_rotation.copy(), rv3d.view_location.copy(),
                                                 rv3d.view_distance)
            return


def ensure_persp(area, space):
    """Maya Single Perspective / Four View (#8): the single view (or the four view's top right panel) shows the
    persp camera, never an ortho view: an ortho view gets the last persp view of this area back, else the
    default persp, like Maya (Home)."""
    rv3d = space.region_3d
    if rv3d is None or rv3d.view_perspective != 'ORTHO':
        return
    rv3d.is_orthographic_side_view = False
    rv3d.view_perspective = 'PERSP'
    saved = _persp_store().get(area.as_pointer())
    if saved:
        rv3d.view_rotation, rv3d.view_location, rv3d.view_distance = saved
    else:
        home_view(rv3d, units.maya_unit(bpy.context.scene))
    area.tag_redraw()


def home_view(rv3d, k):
    """Maya Home (viewSet -home): the default camera place, no animation.
    Perspective = Maya's new-scene persp (units.PERSP_EYE, Maya units); orthographic keeps
    its direction and goes back to the origin at the same distance."""
    eye = Vector(units.PERSP_EYE) * k
    rv3d.view_location = (0.0, 0.0, 0.0)
    rv3d.view_distance = eye.length
    if rv3d.view_perspective == 'PERSP':
        rv3d.view_rotation = eye.normalized().to_track_quat('Z', 'Y')


class ALLSET_OT_view_home(bpy.types.Operator):
    """Go to the default view (Maya Home)"""
    bl_idname = "allset.view_home"
    bl_label = "Default View"

    @classmethod
    def poll(cls, context):
        rv3d = context.region_data
        return rv3d is not None and context.area is not None and context.area.type == 'VIEW_3D'             and rv3d.view_perspective != 'CAMERA'

    def execute(self, context):
        home_view(context.region_data, units.maya_unit(context.scene))
        context.region.tag_redraw()
        return {'FINISHED'}


classes = (ALLSET_OT_tumble, ALLSET_OT_track_view, ALLSET_OT_nav_chord, ALLSET_OT_emulated_tumble, ALLSET_OT_dolly, ALLSET_OT_dolly_2d, ALLSET_OT_nav_2d, ALLSET_OT_view_axis_lock, ALLSET_OT_frame, ALLSET_OT_frame_all_views, ALLSET_OT_view_history,
           ALLSET_OT_toggle_quad_view, ALLSET_OT_view_home)
