# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya camera Overscan (#313): how much room a view that looks through the camera shows around its frame.

Maya: Overscan 1.0 (a new camera's value) fits the camera's frame to the view; 1.3 makes the frame 1 / 1.3 of the
view, 2.0 half of it. Blender keeps a per-view camera zoom instead (``RegionView3D.view_camera_zoom``), so the kit
keeps the value on the camera (``Camera.allset_overscan``) and sets the zoom of the views that look through it:
when a kit Look Through starts looking through it and when the value changes. Blender's Frame Camera Bounds fits
the frame first; the zoom is then scaled down by the overscan. Zooming the view afterwards (2D Pan / Zoom, the
mouse wheel) is left alone, like Maya's 2D pan / zoom on top of the overscan.
"""

import math

import bpy
from bpy.props import FloatProperty

PROP = "allset_overscan"
ZOOM_MIN, ZOOM_MAX = -30.0, 600.0          # Blender's camera zoom range


def zoom_to_fac(zoom):
    """Frame scale of a camera zoom value (Blender's view zoom curve: 0 -> 0.5)."""
    return (math.sqrt(2.0) + zoom / 50.0) ** 2 / 4.0


def fac_to_zoom(fac):
    return (2.0 * math.sqrt(max(fac, 1e-9)) - math.sqrt(2.0)) * 50.0


def overscan(cam_ob):
    data = getattr(cam_ob, "data", None)
    return max(float(getattr(data, PROP, 1.0)), 1e-4) if isinstance(data, bpy.types.Camera) else 1.0


def view_camera(space, scene):
    return space.camera if space.use_local_camera and space.camera is not None else scene.camera


def apply_view(window, area):
    """Fit the camera frame of this view, then scale it down by the camera's overscan. False when the view doesn't
    look through a camera (or is a quad view)."""
    space = area.spaces.active
    rv3d = space.region_3d
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None or rv3d is None or rv3d.view_perspective != 'CAMERA' or space.region_quadviews:
        return False
    cam = view_camera(space, window.scene)
    if cam is None or cam.type != 'CAMERA':
        return False
    with bpy.context.temp_override(window=window, area=area, region=region, space_data=space):
        bpy.ops.view3d.view_center_camera()
    fac = zoom_to_fac(rv3d.view_camera_zoom) / overscan(cam)
    rv3d.view_camera_zoom = min(ZOOM_MAX, max(ZOOM_MIN, fac_to_zoom(fac)))
    from ..ui import camera_bookmarks
    camera_bookmarks.pan_zoom_forget(rv3d)       # the whole frame: no 2D pan / zoom left in this view
    area.tag_redraw()
    return True


def _views(camera_data=None):
    wm = bpy.context.window_manager
    for window in (wm.windows if wm else ()):
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            space = area.spaces.active
            if camera_data is not None:
                cam = view_camera(space, window.scene)
                if cam is None or cam.data != camera_data:
                    continue
            yield window, area


def apply_later(area=None, camera_data=None):
    """Apply after the current event (the view's camera / region are settled by then): one area, or every view
    looking through ``camera_data``."""
    ptr = area.as_pointer() if area is not None else None
    name = camera_data.name if camera_data is not None else None

    def run():
        try:
            data = bpy.data.cameras.get(name) if name is not None else None
            for window, a in _views(data):
                if ptr is None or a.as_pointer() == ptr:
                    apply_view(window, a)
        except (ReferenceError, RuntimeError, AttributeError):
            pass
        return None
    bpy.app.timers.register(run, first_interval=0.0)


def _update(self, _context):
    apply_later(camera_data=self)


def register_props():
    bpy.types.Camera.allset_overscan = FloatProperty(
        name="Overscan", default=1.0, min=0.0001, soft_min=1.0, soft_max=3.0, step=10, precision=3, update=_update,
        description="Room around the camera's frame in a view that looks through this camera, like Maya: 1 fits "
                    "the frame to the view, 1.3 makes the frame 1 / 1.3 of the view")


def unregister_props():
    if hasattr(bpy.types.Camera, PROP):
        del bpy.types.Camera.allset_overscan
