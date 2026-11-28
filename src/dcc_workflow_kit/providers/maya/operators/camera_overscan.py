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


LABEL_SIZE = 11     # px at UI scale 1
_label_handles = []


def res_label(scene):
    """Maya's resolution gate label: the render size."""
    r = scene.render
    return f"{r.resolution_x} x {r.resolution_y}"


FIELD_CELLS = 24                       # Maya's 12-field chart: 12 cells each side of the centre
FIELD_COLOUR = (0.0, 0.42, 0.18, 1.0)


def field_chart_lines(x0, y0, x1, y1, n=FIELD_CELLS):
    """Line end points of Maya's field chart over the rect: an n x n grid and both diagonals."""
    pts = []
    for i in range(n + 1):
        x = x0 + (x1 - x0) * i / n
        y = y0 + (y1 - y0) * i / n
        pts += [(x, y0), (x, y1), (x0, y), (x1, y)]
    pts += [(x0, y0), (x1, y1), (x0, y1), (x1, y0)]
    return pts


def _draw_field_chart(x0, y0, x1, y1, scale):
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'LINES', {"pos": field_chart_lines(x0, y0, x1, y1)})
    gpu.state.blend_set('ALPHA')
    shader.uniform_float("color", FIELD_COLOUR)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    # field numbers 1-11 out from the centre along both centre lines
    font, half = 0, FIELD_CELLS // 2
    blf.size(font, round(LABEL_SIZE * scale))
    blf.color(font, *FIELD_COLOUR[:3], 1.0)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    cw, ch = (x1 - x0) / FIELD_CELLS, (y1 - y0) / FIELD_CELLS
    for k in range(1, half):
        text = str(k)
        w, h = blf.dimensions(font, text)
        for sx in (-1, 1):
            blf.position(font, round(cx + sx * k * cw - w / 2.0), round(cy - h / 2.0), 0)
            blf.draw(font, text)
        for sy in (-1, 1):
            blf.position(font, round(cx - w / 2.0), round(cy + sy * k * ch - h / 2.0), 0)
            blf.draw(font, text)


def draw_gate_overlays():
    """Maya camera displays Blender doesn't draw: the Field Chart over the resolution gate, and with Resolution Gate
    on the render size written centred above the gate."""
    context = bpy.context
    space, region, rv3d = context.space_data, context.region, context.region_data
    if rv3d is None or rv3d.view_perspective != 'CAMERA':
        return
    cam = view_camera(space, context.scene)
    from ..ui.panel_menus import RES_GATE, FIELD_CHART
    if cam is None or cam.type != 'CAMERA':
        return
    res, chart = cam.data.get(RES_GATE), cam.data.get(FIELD_CHART)
    if not (res or chart):
        return
    import blf
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    pts = [location_3d_to_region_2d(region, rv3d, cam.matrix_world @ v)
           for v in cam.data.view_frame(scene=context.scene)]
    if any(p is None for p in pts):
        return
    scale = context.preferences.system.ui_scale
    x0, x1 = min(p.x for p in pts), max(p.x for p in pts)
    y0, y1 = min(p.y for p in pts), max(p.y for p in pts)
    if chart:
        _draw_field_chart(x0, y0, x1, y1, scale)
    if res:
        # styled like the viewport's own info text (widget font, theme text_hi, dark shadow), centred
        # halfway between the gate top and the region top
        text = res_label(context.scene)
        font = 0
        prefs = context.preferences
        blf.size(font, round(prefs.ui_styles[0].widget.points * scale))
        w, h = blf.dimensions(font, text)
        blf.color(font, *prefs.themes[0].view_3d.space.text_hi, 1.0)
        blf.enable(font, blf.SHADOW)
        blf.shadow(font, 5, 0.0, 0.0, 0.0, 1.0)
        blf.shadow_offset(font, 1, -1)
        # visible top: the region runs under overlapping (transparent) headers, so stop at their bottom edge
        top = region.height
        for r in context.area.regions:
            if r.type in {'HEADER', 'TOOL_HEADER'} and r.height > 1 and r.y > region.y + region.height / 2:
                top = min(top, r.y - region.y)
        blf.position(font, round((x0 + x1) / 2.0 - w / 2.0), round((y1 + top) / 2.0 - h / 2.0), 0)
        blf.draw(font, text)
        blf.disable(font, blf.SHADOW)


def register_props():
    _label_handles.append(bpy.types.SpaceView3D.draw_handler_add(draw_gate_overlays, (), 'WINDOW', 'POST_PIXEL'))
    bpy.types.Camera.allset_overscan = FloatProperty(
        name="Overscan", default=1.0, min=0.0001, soft_min=1.0, soft_max=3.0, step=10, precision=3, update=_update,
        description="Room around the camera's frame in a view that looks through this camera, like Maya: 1 fits "
                    "the frame to the view, 1.3 makes the frame 1 / 1.3 of the view")


def unregister_props():
    while _label_handles:
        bpy.types.SpaceView3D.draw_handler_remove(_label_handles.pop(), 'WINDOW')
    if hasattr(bpy.types.Camera, PROP):
        del bpy.types.Camera.allset_overscan
