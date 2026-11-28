# SPDX-License-Identifier: GPL-3.0-or-later
"""The camera of a Maya viewport panel: the camera a 3D View looks through (``view_camera``), its startup camera
(``panel_camera``), Lock Camera (``camera_locked``), Look Through (``look_through``; ``_on_undo`` gives a view back
what it showed when an undo removes its camera) and Panels > Perspective / Orthographic > New
(``allset.panel_new_persp`` / ``allset.panel_new_ortho``). Registered by ``panel_menus``."""

import bpy
from bpy.app.handlers import persistent
from bpy.props import EnumProperty, StringProperty


def _space(context):
    space = context.space_data
    return space if space is not None and space.type == 'VIEW_3D' else None


def _scene_camera_view(context):
    rv3d = context.region_data or getattr(_space(context), "region_3d", None)
    return rv3d is not None and rv3d.view_perspective == 'CAMERA'


def view_camera(context):
    """The object this view looks through (None: Blender's persp / ortho view, which has no camera object)."""
    space = _space(context)
    if space is None or not _scene_camera_view(context):
        return None
    if space.use_local_camera and space.camera is not None:
        return space.camera
    return context.scene.camera


# Maya's startup camera of an orthographic view by its looking direction (Blender Z-up world)
_ORTHO_CAMERAS = (("top", (0.0, 0.0, -1.0)), ("front", (0.0, 1.0, 0.0)), ("side", (-1.0, 0.0, 0.0)))


def _startup_name(context):
    """The startup camera of this view: persp for a perspective view, top / front / side for those orthographic
    views, else None."""
    space = _space(context)
    return startup_name_of(context.region_data or getattr(space, "region_3d", None))


def startup_name_of(rv3d):
    """``_startup_name`` of the view ``rv3d`` (None: no view, or not one of those views)."""
    if rv3d is None:
        return None
    if rv3d.view_perspective == 'PERSP':
        return "persp"
    from mathutils import Vector
    forward = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
    for name, axis in _ORTHO_CAMERAS:
        if forward.dot(Vector(axis)) > 0.999:
            return name
    return None


def panel_camera(context, make=False):
    """Maya's camera of this panel: the camera it looks through, else the scene's startup camera of that view
    (persp for a perspective view, top / front / side for those orthographic views), else None. ``make``: a scene
    without startup cameras (one not made with File > New Scene in Maya mode) gets them first, as every Maya scene has
    them (#297)."""
    cam = view_camera(context)
    if cam is not None:
        return cam
    name = _startup_name(context)
    if name is None:
        return None
    from ..operators import startup_cameras
    found = {ob.get(startup_cameras.MARK): ob for ob in startup_cameras.cameras(context.scene)}
    if not found and make:
        found = {ob.get(startup_cameras.MARK): ob
                 for ob in startup_cameras.ensure(context.scene, context.view_layer)}
    return found.get(name)


def has_panel_camera(context):
    """Select Camera has a camera to select in this view (the startup ones are made on the first use)."""
    return view_camera(context) is not None or _startup_name(context) is not None


def camera_locked(ob):
    """Maya Lock Camera (camera -lockTransform): the kit locks the camera's location and rotation channels;
    Blender's camera-view navigation keeps locked channels."""
    return all(ob.lock_location) and all(ob.lock_rotation)


def _cameras(context, ortho):
    """Cameras listed under Panels > Perspective / Orthographic (``ortho`` None = both kinds, the panel toolbar's
    camera list); the startup persp / top / front / side are the menus' own rows."""
    from ..operators import startup_cameras
    return [ob for ob in context.scene.objects
            if ob.type == 'CAMERA' and (ortho is None or (ob.data.type == 'ORTHO') == ortho)
            and not startup_cameras.is_startup(ob)]


class ALLSET_OT_panel_look_through(bpy.types.Operator):
    """Look through this camera in this view"""
    bl_idname = "allset.panel_look_through"
    bl_label = "Look Through Camera"
    bl_options = {'INTERNAL'}

    camera: StringProperty(options={'SKIP_SAVE'})   # empty: the active object (Maya Look Through Selected)

    def execute(self, context):
        ob = context.scene.objects.get(self.camera) if self.camera else context.active_object
        area = context.area
        if ob is None or area is None or area.type != 'VIEW_3D':
            if ob is None:
                self.report({'WARNING'}, "Select an object to look through")
            return {'CANCELLED'}
        look_through(context, area, ob)
        return {'FINISHED'}


# what each view showed before a kit Look Through (RegionView3D pointer -> perspective, camera name, local camera):
# when Ctrl+Z removes the camera a view looks through, the view goes back to it (session only)
_before_look = {}


def _look_through_panel_camera(context, space):
    """Maya's persp / top / front / side panel is that camera: in Blender's own view, put the view's startup camera
    where the view looks (Create Camera From View's placement) and look through it. None: no such camera."""
    area = context.area
    rv3d = space.region_3d
    if area is None or area.type != 'VIEW_3D' or rv3d is None:
        return None
    cam = panel_camera(context, make=True)
    if cam is None or cam.type != 'CAMERA':
        return None
    from ..operators import camera_copy, units
    camera_copy._place_from_view(cam, space, rv3d, units.maya_unit(context.scene))
    look_through(context, area, cam)
    return cam


def enable_in_viewports(ob):
    if ob.hide_viewport:
        # Blender doesn't evaluate an object disabled in viewports (the startup cameras: Maya Visibility off), so
        # navigating through it would not move the view; hide it with the eye instead (still not drawn)
        ob.hide_viewport = False
        try:
            ob.hide_set(True)
        except RuntimeError:     # not in this view layer
            pass


def look_through(context, area, ob):
    space = area.spaces.active
    rv3d = space.region_3d
    if rv3d is not None:
        old = space.camera if space.use_local_camera else context.scene.camera
        _before_look[rv3d.as_pointer()] = (rv3d.view_perspective, old.name if old is not None else "",
                                           space.use_local_camera)
    # the view's own camera (a Maya panel's): local first, since a camera set on a view locked to the scene becomes
    # the scene camera
    enable_in_viewports(ob)
    space.use_local_camera = ob != context.scene.camera
    space.camera = ob
    space.region_3d.view_perspective = 'CAMERA'
    # Maya: navigating a view that looks through a camera moves the camera (#9)
    space.lock_camera = True
    from ..operators import camera_overscan
    camera_overscan.apply_later(area)      # the frame fills the view by the camera's Overscan (Maya)


def restore_camera_less(window_manager):
    """Views left looking through no camera (Ctrl+Z took away the camera they looked through) show again what they
    showed before that Look Through: that camera, else the persp / orthographic view."""
    for window in window_manager.windows:
        scene = window.scene
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            space = area.spaces.active
            rv3d = space.region_3d
            if rv3d is None or rv3d.view_perspective != 'CAMERA':
                continue
            if (space.camera if space.use_local_camera else scene.camera) is not None:
                continue
            perspective, name, local = _before_look.pop(rv3d.as_pointer(), ('PERSP', "", False))
            cam = scene.objects.get(name) if name else None
            if perspective == 'CAMERA' and cam is not None:
                space.use_local_camera = local
                space.camera = cam
            else:
                rv3d.view_perspective = 'ORTHO' if perspective == 'ORTHO' else 'PERSP'
            area.tag_redraw()


@persistent
def _on_undo(*_args):
    try:
        restore_camera_less(bpy.context.window_manager)
    except (AttributeError, ReferenceError, RuntimeError):
        pass


class ALLSET_OT_panel_new_persp(bpy.types.Operator):
    """Make a new perspective camera and look through it in this view"""
    bl_idname = "allset.panel_new_persp"
    bl_label = "New"
    # an undo step, no Adjust Last Operation (Maya has no redo panel)
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def execute(self, context):
        # Maya 2026 behaviour (#193): New makes persp1, persp2 ... with the camera settings and the place
        # of a new scene's persp (35 mm, translate 28 21 28 aimed at the origin), selects it and looks through it
        from ..operators import create, film_fit, naming, startup_cameras, units
        ob = create.create(context, 'CAMERA', maya_naming=False)
        film_fit.set_fit(ob.data, 'HORIZONTAL')       # the Fit Resolution Gate of a new scene's persp
        naming.apply_maya_name(ob, "persp")
        ob.matrix_world = startup_cameras.maya_matrix("persp", units.maya_unit(context.scene))
        for other in context.selected_objects:
            other.select_set(other == ob)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        look_through(context, context.area, ob)
        return {'FINISHED'}


ORTHO_SIDES = (('front', "Front"), ('back', "Back"), ('right', "Right"), ('left', "Left"), ('top', "Top"),
               ('bottom', "Bottom"))


class ALLSET_OT_panel_new_ortho(bpy.types.Operator):
    """Make a new orthographic camera that looks from one side and look through it in this view"""
    bl_idname = "allset.panel_new_ortho"
    bl_label = "New Orthographic Camera"
    bl_options = {'UNDO'}

    kind: EnumProperty(name="View", items=[(k, label, "") for k, label in (*ORTHO_SIDES, ('side', "Side"))],
                       default='front', options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def execute(self, context):
        # Maya: New makes front1, back1, right1 ... (side1 from the panel toolbar's list) 30 units wide, 1000.1 units
        # out on that side looking at the origin, not renderable; it selects it and looks through it
        from ..operators import create, film_fit, naming, startup_cameras, units
        unit = units.maya_unit(context.scene)
        ob = create.create(context, 'CAMERA', maya_naming=False)
        film_fit.set_fit(ob.data, 'HORIZONTAL')
        naming.apply_maya_name(ob, self.kind)
        ob.data.type = 'ORTHO'
        ob.data.ortho_scale = startup_cameras.MAYA_ORTHO_WIDTH * unit
        ob.data.allset_renderable = False
        ob.matrix_world = startup_cameras.maya_matrix(self.kind, unit)
        for other in context.selected_objects:
            other.select_set(other == ob)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        look_through(context, context.area, ob)
        return {'FINISHED'}


class ALLSET_MT_panel_new_ortho(bpy.types.Menu):
    """New orthographic camera: front, side or top (Maya New Orthographic)"""
    bl_idname = "ALLSET_MT_panel_new_ortho"
    bl_label = "New Orthographic"

    def draw(self, context):
        for kind, label in (('front', "Front"), ('side', "Side"), ('top', "Top")):
            self.layout.operator(ALLSET_OT_panel_new_ortho.bl_idname, text=label).kind = kind


class ALLSET_MT_panel_ortho_new(bpy.types.Menu):
    """New orthographic camera looking from one side (Maya Panels > Orthographic > New)"""
    bl_idname = "ALLSET_MT_panel_ortho_new"
    bl_label = "New"

    def draw(self, context):
        for kind, label in ORTHO_SIDES:
            self.layout.operator(ALLSET_OT_panel_new_ortho.bl_idname, text=label).kind = kind


def _draw_camera_list(layout, context, ortho):
    for ob in _cameras(context, ortho):
        layout.operator(ALLSET_OT_panel_look_through.bl_idname, text=ob.name,
                        icon='OUTLINER_OB_CAMERA').camera = ob.name
