# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya framing in the 3D views: F / A / Ctrl+Shift+F in this view (``allset.frame``) or in every view
(``allset.frame_all_views``), fitting the part of the view not under the sidebar / toolbar (``visible_bounds``); in
a camera view the camera moves (``frame_camera``). Entry point ``frame_region``; the fit math is framing.py.
"""

import bpy
from mathutils import Vector

from . import framing, units

# --- framing ------------------------------------------------------------------


def view3d_window_regions(window):
    """(area, region) for every 3D view WINDOW region (quad views: all four)."""
    for area in window.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type == 'WINDOW':
                yield area, region


# Object types whose evaluated bounding box is framed; others count as a point.
_BOX_TYPES = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES', 'POINTCLOUD', 'VOLUME',
              'GREASEPENCIL', 'LATTICE', 'ARMATURE'}


def _object_points(ob, depsgraph):
    """The 8 corners of the object's world-axis bounding box (like Maya, each object keeps its own box: two objects
    apart frame by their own boxes, not by the box around both), or its origin for an object without a box."""
    mw = ob.matrix_world
    if ob.type in _BOX_TYPES:
        ev = ob.evaluated_get(depsgraph)
        return framing.box_corners([mw @ Vector(c) for c in ev.bound_box], 0.0)
    return [mw.translation.copy()]


def _visible(ob, view_layer, v3d):
    try:
        return ob.visible_get(view_layer=view_layer) and ob.visible_in_viewport_get(v3d)
    except RuntimeError:   # not in this view layer
        return False


def _paint_selection_points(ob, depsgraph):
    """World points of the vertices a weight-paint selection shows (vertex mask: selected vertices, face mask: the
    selected faces' vertices), on the deformed mesh when its vertices match the original ones."""
    me = ob.data
    if me.use_paint_mask_vertex:
        idx = [v.index for v in me.vertices if v.select and not v.hide]
    elif me.use_paint_mask:
        idx = sorted({i for p in me.polygons if p.select and not p.hide for i in p.vertices})
    else:
        return []
    if not idx:
        return []
    shown = ob.evaluated_get(depsgraph).data
    verts = shown.vertices if len(shown.vertices) == len(me.vertices) else me.vertices
    mw = ob.matrix_world
    return [mw @ verts[i].co for i in idx]


def frame_points(context, v3d, selected, children, exclude=None):
    """World points to frame (Maya F / Ctrl+Shift+F / A), or None if this mode is left to
    Blender's own operator (curve/armature edit, pose, other paint and sculpt modes). ``exclude``: an object left out
    (the camera a view looks through)."""
    vl, dg = context.view_layer, context.evaluated_depsgraph_get()
    mode = context.mode
    if not selected:   # A / Shift+A: every visible object, in any mode (Maya Frame All)
        return [p for ob in vl.objects if ob != exclude and _visible(ob, vl, v3d) for p in _object_points(ob, dg)]
    if mode == 'EDIT_MESH':
        pts = []
        objs = list(context.objects_in_mode_unique_data)
        for ob in objs:
            ob.update_from_editmode()
            mw = ob.matrix_world
            pts.extend(mw @ v.co for v in ob.data.vertices if v.select)
        if pts:
            return pts
        # No components selected: frame the objects (Maya frames the whole shape).
        return [p for ob in objs for p in _object_points(ob, dg)] or None
    if mode == 'PAINT_WEIGHT':
        ob = context.active_object
        if ob is None or ob.type != 'MESH':
            return None
        # Maya Paint Skin Weights: the selected vertices, else the painted mesh, where the posed mesh shows them
        return _paint_selection_points(ob, dg) or _object_points(ob, dg)
    if mode != 'OBJECT':
        return None
    objs = [ob for ob in vl.objects if ob != exclude and _visible(ob, vl, v3d)]
    sel = [ob for ob in objs if ob.select_get()]
    if children:
        seen = {ob.name for ob in sel}
        for ob in list(sel):
            for ch in ob.children_recursive:
                if ch.name not in seen and _visible(ch, vl, v3d):
                    seen.add(ch.name)
                    sel.append(ch)
    objs = sel or objs    # nothing selected: Maya F frames everything
    return [p for ob in objs for p in _object_points(ob, dg)]


def _per_box(context, selected):
    """True when frame_points gave objects' own box corners (Frame All, objects in Object Mode)."""
    return not selected or context.mode == 'OBJECT'


def _others(area, region):
    return [(r.x, r.y, r.width, r.height) for r in area.regions
            if r.type in {'UI', 'TOOLS', 'HEADER', 'TOOL_HEADER', 'ASSET_SHELF',
                          'ASSET_SHELF_HEADER'} and r != region]


def visible_bounds(area, region):
    """Region-local (x0, y0, x1, y1) not covered by the sidebar/toolbar (Region Overlap)."""
    return framing.visible_rect((region.x, region.y, region.width, region.height),
                                _others(area, region))


def frame_region(context, area, region, selected=True, children=False):
    """Frame in one 3D view region the Maya way (fit 0.95 of the part not under the
    sidebar/toolbar). Falls back to Blender's view_selected / view_all."""
    rv3d, v3d = region.data, area.spaces.active
    points = None
    if rv3d is not None and rv3d.view_perspective == 'CAMERA':
        # Maya: F / A in a camera view move that camera (#9); Blender's view_selected would leave the camera view
        cam = view_camera(context, v3d)
        if cam is None:
            return False
        points = frame_points(context, v3d, selected, children, exclude=cam)
        if not points:
            return False
        if not frame_camera(context, cam, points, area, region, per_box=_per_box(context, selected)):
            return False
        try:
            bpy.ops.ed.undo_push(message="Frame Camera")
        except RuntimeError:
            pass
        return True
    if rv3d is not None:
        points = frame_points(context, v3d, selected, children)
    if not points:
        with context.temp_override(area=area, region=region):
            if selected:
                return bpy.ops.view3d.view_selected() == {'FINISHED'}
            return bpy.ops.view3d.view_all(center=False) == {'FINISHED'}
    rect = visible_bounds(area, region)
    loc, dist = framing.fit(points, rv3d.view_rotation, rv3d.window_matrix.copy(),
                            rv3d.view_distance, rv3d.view_perspective == 'ORTHO',
                            (region.width, region.height), rect,
                            min_half=framing.MIN_HALF * units.maya_unit(context.scene),
                            per_box=_per_box(context, selected))
    rv3d.view_location = loc
    rv3d.view_distance = dist
    region.tag_redraw()
    return True


def view_camera(context, v3d):
    """The object a camera view looks through (the view's local camera or the scene camera)."""
    if v3d.use_local_camera and v3d.camera is not None:
        return v3d.camera
    return context.scene.camera


def camera_projection(context, cam):
    """(window matrix, (width, height)) of the camera's frame at the render resolution."""
    r = context.scene.render
    w, h = max(r.resolution_x, 1), max(r.resolution_y, 1)
    win = cam.calc_matrix_camera(context.evaluated_depsgraph_get(), x=w, y=h,
                                 scale_x=r.pixel_aspect_x, scale_y=r.pixel_aspect_y)
    return win, (w, h)


def frame_camera(context, cam, points, area=None, region=None, per_box=False):
    """Move ``cam`` so ``points`` fill 0.95 of what the view shows, keeping its orientation (Maya framing in a
    camera view dollies / tracks the camera; an orthographic camera changes its width). ``region``: the camera view
    that frames, whose whole visible part is filled like Maya's panel, also the room an Overscan above 1 leaves
    around the gate (Resolution / Film Gate shown); without one the camera's frame is filled. A locked camera (Maya
    Lock Camera, ui/panel_cameras.camera_locked) stays. Returns True when the camera moved."""
    if all(cam.lock_location) or cam.type != 'CAMERA':
        return False
    mw = cam.matrix_world
    loc0, rot, scale = mw.decompose()
    rot = rot.normalized()
    ortho = cam.data.type == 'ORTHO'
    rv3d = region.data if region is not None else None
    if area is not None and rv3d is not None and rv3d.view_perspective == 'CAMERA' \
            and region.width > 1 and region.height > 1:
        win, size = rv3d.window_matrix.copy(), (region.width, region.height)
        rect = visible_bounds(area, region)
    else:
        win, size = camera_projection(context, cam)
        rect = (0.0, 0.0, size[0], size[1])
    centre = sum((Vector(p) for p in points), Vector()) / len(points)
    forward = rot @ Vector((0.0, 0.0, -1.0))
    dist0 = max((centre - loc0).dot(forward), 1e-3)
    loc, dist = framing.fit(points, rot, win, dist0, ortho, size, rect,
                            min_half=framing.MIN_HALF * units.maya_unit(context.scene), per_box=per_box)
    if ortho:
        cam.data.ortho_scale *= dist / dist0
        dist = dist0
    from mathutils import Matrix
    new = loc + rot @ Vector((0.0, 0.0, dist))
    cam.matrix_world = Matrix.LocRotScale(new, rot, scale)
    return True


class ALLSET_OT_frame(bpy.types.Operator):
    """Frame the selection (or everything) in this view with Maya's fit (F, A, Ctrl+Shift+F)"""
    bl_idname = "allset.frame"
    bl_label = "Frame"

    # SKIP_SAVE: keymap items set only some of these; a remembered children=True from
    # Ctrl+Shift+F must not leak into the next Shift+F.
    selected: bpy.props.BoolProperty(name="Selected", default=True, options={'SKIP_SAVE'})
    children: bpy.props.BoolProperty(name="With Children", default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D' and             context.region is not None and context.region.type == 'WINDOW'

    def execute(self, context):
        ok = frame_region(context, context.area, context.region, self.selected, self.children)
        return {'FINISHED'} if ok else {'CANCELLED'}


class ALLSET_OT_frame_all_views(bpy.types.Operator):
    """Frame the selection (or everything) in every 3D view (Maya Shift+F / Shift+A /
    Ctrl+Shift+F)"""
    bl_idname = "allset.frame_all_views"
    bl_label = "Frame in All Views"

    # SKIP_SAVE: keymap items set only some of these; a remembered children=True from
    # Ctrl+Shift+F must not leak into the next Shift+F.
    selected: bpy.props.BoolProperty(name="Selected", default=True, options={'SKIP_SAVE'})
    children: bpy.props.BoolProperty(name="With Children", default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.window is not None

    def execute(self, context):
        count = 0
        for area, region in view3d_window_regions(context.window):
            count += frame_region(context, area, region, self.selected, self.children)
        return {'FINISHED'} if count else {'CANCELLED'}
