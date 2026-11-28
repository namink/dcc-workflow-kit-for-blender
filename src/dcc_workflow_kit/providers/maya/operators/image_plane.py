# SPDX-License-Identifier: GPL-3.0-or-later
"""The viewport panel toolbar's Image Plane button (#398), like Maya.

A view without an image plane: the button opens a file browser (in the project's sourceimages folder) and the picked
image becomes an image plane of that view, a Blender image empty named ``imagePlane1``:
- an orthographic view (top / front / side or an orthographic camera) gets a plane facing it, at the origin for the
  top / front / side views and 5 units in front of any other orthographic camera;
- a perspective camera the view looks through gets a plane attached to it (parented) 100 units in front, filling its
  view, so it follows the camera (a hidden camera, like the startup persp, is shown so the plane is drawn);
- Blender's own perspective view (no camera object) gets a plane facing the view at the view's centre.
The plane is as wide as the image's pixel width / 100 (Maya length units), its height follows the image.

A camera the view looks through that has an image plane attached: the button shows / hides that plane (Maya's image
plane display on / off), nothing is made. The other planes (top / front / side, orthographic cameras, Blender's own
views) aren't attached to a camera, so every click there imports one more image, like Maya.

Import Image... (View > Image Plane, the button's right-click menu) always imports one more image; Import Movie...
imports a movie the plane plays along the frames. The button's right-click Display Mode None / RGBA hides / shows the
camera's first image plane, Delete removes it; View > Image Plane > Image Plane Attributes selects one of the camera's
planes and shows it in the Attribute Editor (``allset.image_plane_display`` / ``_delete`` / ``_attributes``).

A hidden plane (Display Mode None, the button's show / hide) is not drawn in any view but stays a visible, selectable
object, like a Maya image plane whose display is off: Image Plane Attributes selects it, and Show > Image Planes off and
on again leaves it undrawn.
"""

import json
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from mathutils import Quaternion, Vector

from . import units

TAG = "allset_image_plane_view"     # an image plane attached to a camera: that camera's name
PIXELS_PER_UNIT = 100.0             # the plane is the image's pixel width / 100 units wide
CAMERA_DEPTH = 100.0                # a camera's plane, units in front of it
ORTHO_OFFSET = 5.0                  # an orthographic camera's plane (not top / front / side), units in front of it
NONE_MARK = "allset_image_plane_none"   # Display Mode None: the plane's image is not drawn


def _view_target(context):
    """Where this view's image plane goes, as plain data (kept between the button click and the file browser):
    ``kind`` ORTHO / CAMERA / VIEW, ``key`` (the camera whose attached plane the button shows / hides; "" = none), ``rot`` (w, x, y, z),
    ``loc`` and ``camera`` (the camera object's name for CAMERA)."""
    from ..ui import panel_cameras
    from . import startup_cameras
    space = context.space_data if context.space_data is not None and context.space_data.type == 'VIEW_3D' else None
    rv3d = context.region_data or getattr(space, "region_3d", None)
    if rv3d is None:
        return None
    k = units.maya_unit(context.scene)
    cam = panel_cameras.view_camera(context)
    if cam is not None and cam.type == 'CAMERA':
        mark = cam.get(startup_cameras.MARK) if startup_cameras.is_startup(cam) else None
        rot = cam.matrix_world.to_quaternion()
        if cam.data.type != 'ORTHO':
            return {"kind": 'CAMERA', "key": cam.name, "rot": list(rot), "loc": [0.0, 0.0, 0.0], "camera": cam.name}
        if mark:
            loc = Vector()
        else:
            loc = cam.matrix_world.translation + rot @ Vector((0.0, 0.0, -ORTHO_OFFSET * k))
        return {"kind": 'ORTHO', "key": "", "rot": list(rot), "loc": list(loc), "camera": ""}
    rot = rv3d.view_rotation
    if rv3d.view_perspective == 'ORTHO':
        return {"kind": 'ORTHO', "key": "", "rot": list(rot), "loc": [0.0, 0.0, 0.0], "camera": ""}
    return {"kind": 'VIEW', "key": "", "rot": list(rot), "loc": list(rv3d.view_location), "camera": ""}


def view_planes(context, key):
    """The image planes attached to the camera named ``key``, in name order (the first is the one the button shows /
    hides)."""
    cam = bpy.data.objects.get(key) if key else None
    if cam is None:
        return []
    return sorted((ob for ob in cam.children if ob.get(TAG) == key and ob.type == 'EMPTY'
                   and ob.empty_display_type == 'IMAGE' and ob.name in context.view_layer.objects),
                  key=lambda ob: ob.name)


def view_plane(context, key):
    """The first image plane attached to the camera named ``key`` (None: it has none)."""
    planes = view_planes(context, key)
    return planes[0] if planes else None


def camera_planes(context):
    """The image planes attached to the camera this view looks through ([] in Blender's own views)."""
    target = _view_target(context)
    return view_planes(context, target["key"]) if target else []


def _plane_size(image, width, height=None):
    """Display size of an image empty showing ``image`` ``width`` wide, or fitting in ``width`` x ``height``
    (Blender draws an image empty's larger side at its display size)."""
    w, h = (image.size[0], image.size[1]) if image is not None and image.size[0] and image.size[1] else (1, 1)
    if height is not None and w * height < h * width:     # taller than the frame: fit the height
        width = height * w / h
    return width if w >= h else width * h / w


def build(context, target, image):
    """The image plane for ``target`` (``_view_target``) showing ``image``; returns the new object."""
    from . import create
    k = units.maya_unit(context.scene)
    ob = create.create(context, 'IMAGE_PLANE', create._maya_naming(context))
    ob.data = image
    ob.rotation_mode = 'XYZ'
    cam = bpy.data.objects.get(target["camera"]) if target["kind"] == 'CAMERA' else None
    if cam is not None:
        depth = min(CAMERA_DEPTH * k, cam.data.clip_end * 0.9)
        frame = [Vector(c) for c in cam.data.view_frame(scene=context.scene)]
        scale = depth / max(-frame[0].z, 1e-9)
        fw = (max(c.x for c in frame) - min(c.x for c in frame)) * scale
        fh = (max(c.y for c in frame) - min(c.y for c in frame)) * scale
        ob.parent = cam
        ob.matrix_parent_inverse.identity()
        ob.location = (0.0, 0.0, -depth)
        ob.rotation_euler = (0.0, 0.0, 0.0)
        ob.empty_display_size = _plane_size(image, fw, fh)
        # Maya shows the camera (Visibility on) so the attached plane is drawn: a hidden camera hides its children
        if cam.hide_viewport:
            cam.hide_viewport = False
        from . import dag
        dag.sync(context.scene, context.view_layer)
    else:
        w = (image.size[0] if image is not None and image.size[0] else PIXELS_PER_UNIT) / PIXELS_PER_UNIT
        ob.location = target["loc"]
        ob.rotation_euler = Quaternion(target["rot"]).to_euler('XYZ')
        ob.empty_display_size = _plane_size(image, w * k)
    if target["key"]:
        ob[TAG] = target["key"]
    from . import global_keys4
    if not global_keys4.image_planes_drawn(context.scene, exclude=ob):     # Show > Image Planes is off
        for flag in global_keys4.IMAGE_FLAGS:
            setattr(ob, flag, False)
    if image is not None and image.source == 'MOVIE':
        # a movie plays along the frames from the scene's first frame, like a Maya movie image plane
        iu = ob.image_user
        iu.frame_duration = max(image.frame_duration, 1)
        iu.frame_start = context.scene.frame_start
        iu.use_auto_refresh = True
    return ob


def shown(plane):
    """The plane is drawn (not hidden with Display Mode None / the button, nor with Blender's Hide)."""
    return not plane.get(NONE_MARK) and not plane.hide_get()


def set_shown(plane, on, scene):
    """Display Mode RGBA (``on``) / None of ``plane``: None stops drawing its image in every view and keeps the object
    selectable; RGBA draws it again, as far as Show > Image Planes draws image planes."""
    from . import global_keys4
    if on:
        drawn = global_keys4.image_planes_drawn(scene, exclude=plane)
        if NONE_MARK in plane:
            del plane[NONE_MARK]
        if plane.hide_get():
            plane.hide_set(False)
    else:
        drawn = False
        plane[NONE_MARK] = True
    for flag in global_keys4.IMAGE_FLAGS:
        setattr(plane, flag, drawn)


def toggle(plane, scene):
    set_shown(plane, not shown(plane), scene)


# --- Attribute Editor rows of an image plane (#436) ---------------------------------------------------------------

def is_image_plane(ob):
    return ob is not None and ob.type == 'EMPTY' and ob.empty_display_type == 'IMAGE'


def _alpha_get(ob):
    """Alpha Gain: how opaque the plane's image is drawn (1 = as the image is). Blender's Opacity of the image empty:
    the object colour's alpha, used while the empty's alpha blending is on."""
    return ob.color[3] if ob.use_empty_image_alpha else 1.0


def _alpha_set(ob, value):
    ob.color[3] = value
    ob.use_empty_image_alpha = value < 1.0


def _display_get(ob):
    return 0 if ob.get(NONE_MARK) else 1


def _display_set(ob, value):
    set_shown(ob, value == 1, bpy.context.scene)


def register_props():
    bpy.types.Object.allset_alpha_gain = FloatProperty(
        name="Alpha Gain", min=0.0, max=1.0, get=_alpha_get, set=_alpha_set, subtype='FACTOR',
        description="How opaque the image plane is drawn: lower it to see through the image, e.g. to trace over it "
                    "(Blender: the image empty's Opacity)")
    bpy.types.Object.allset_image_plane_display = EnumProperty(
        name="Display Mode", items=(('NONE', "None", "The image is not drawn"),
                                    ('RGBA', "RGBA", "The image is drawn with its colours and alpha")),
        get=_display_get, set=_display_set,
        description="Display Mode of the image plane, like the Image Plane button's right-click menu")


def unregister_props():
    del bpy.types.Object.allset_image_plane_display
    del bpy.types.Object.allset_alpha_gain


class ALLSET_OT_image_plane(bpy.types.Operator):
    """Import an image as an image plane facing this view (attached to the camera it looks through); when that camera
    has one, show or hide it, like Maya"""
    bl_idname = "allset.image_plane"
    bl_label = "Image Plane"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'})
    filter_image: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    filter_movie: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    filter_folder: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    view: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    import_image: BoolProperty(name="Import", description="Import one more image, also when the camera has one",
                               options={'HIDDEN', 'SKIP_SAVE'})
    movie: BoolProperty(name="Movie", description="Import a movie file", options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.view_layer is not None

    def _target(self, context):
        if self.view:
            return json.loads(self.view)
        return _view_target(context)

    def invoke(self, context, _event):
        target = self._target(context)
        if target is None:
            return {'CANCELLED'}
        self.view = json.dumps(target)
        plane = view_plane(context, target["key"])
        if plane is not None and not self.filepath and not self.import_image:
            toggle(plane, context.scene)
            return {'FINISHED'}
        if self.movie:
            self.filter_image, self.filter_movie = False, True
        if not self.filepath:
            from . import project
            folder = project.texture_folder(context)     # the project's sourceimages, like Maya's image dialogs
            if folder:
                self.filepath = os.path.join(folder, "")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        target = self._target(context)
        if target is None:
            return {'CANCELLED'}
        path = bpy.path.abspath(self.filepath) if self.filepath else ""
        if not path:
            plane = None if self.import_image else view_plane(context, target["key"])
            if plane is None:
                self.report({'WARNING'}, "Image Plane: pick an image file")
                return {'CANCELLED'}
            toggle(plane, context.scene)
            return {'FINISHED'}
        if not os.path.isfile(path):
            self.report({'WARNING'}, f"Image Plane: no image file '{self.filepath}'")
            return {'CANCELLED'}
        try:
            image = bpy.data.images.load(path, check_existing=True)
        except RuntimeError as ex:       # a file Blender can't read as an image
            self.report({'WARNING'}, f"Image Plane: {ex}")
            return {'CANCELLED'}
        ob = build(context, target, image)
        from .. import results
        results.result(self, f"Created {ob.name}")
        return {'FINISHED'}


def _first_plane(op, context):
    plane = next(iter(camera_planes(context)), None)
    if plane is None:
        op.report({'WARNING'}, "This view's camera has no image plane")
    return plane


class ALLSET_OT_image_plane_display(bpy.types.Operator):
    """Display Mode of the first image plane of this view's camera: None hides it, RGBA shows it (Blender draws an
    image empty with its colours and alpha)"""
    bl_idname = "allset.image_plane_display"
    bl_label = "Image Plane Display Mode"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(name="Display Mode", items=(('NONE', "None", "Hide the image plane"),
                                                   ('RGBA', "RGBA", "Show the image plane")))

    def execute(self, context):
        plane = _first_plane(self, context)
        if plane is None:
            return {'CANCELLED'}
        set_shown(plane, self.mode != 'NONE', context.scene)
        return {'FINISHED'}


class ALLSET_OT_image_plane_delete(bpy.types.Operator):
    """Delete the first image plane of this view's camera"""
    bl_idname = "allset.image_plane_delete"
    bl_label = "Delete Image Plane"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        plane = _first_plane(self, context)
        if plane is None:
            return {'CANCELLED'}
        name = plane.name
        bpy.data.objects.remove(plane)
        from .. import results
        results.result(self, f"Deleted {name}")
        return {'FINISHED'}


class ALLSET_OT_image_plane_attributes(bpy.types.Operator):
    """Select this image plane and show it in the Attribute Editor"""
    bl_idname = "allset.image_plane_attributes"
    bl_label = "Image Plane Attributes"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        plane = context.view_layer.objects.get(self.name)
        if plane is None:
            return {'CANCELLED'}
        for ob in context.view_layer.objects.selected:
            ob.select_set(False)
        try:
            plane.select_set(True)
        except RuntimeError:            # hidden by its collection: nothing to select
            return {'CANCELLED'}
        context.view_layer.objects.active = plane
        try:
            bpy.ops.allset.dock_show(dock='ATTRIBUTE_EDITOR')
        except (RuntimeError, AttributeError):     # no dock in this window: the selection stays
            pass
        return {'FINISHED'}


classes = (ALLSET_OT_image_plane, ALLSET_OT_image_plane_display, ALLSET_OT_image_plane_delete,
           ALLSET_OT_image_plane_attributes)
