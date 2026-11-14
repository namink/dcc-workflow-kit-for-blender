# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya camera bookmarks and the panel toolbar's 2D Pan/Zoom button (#346).

Maya: the panel toolbar's Bookmarks button adds a bookmark of the panel's camera view (cameraView1, cameraView2 ...).
Its right-click menu lists the bookmarks (picking one puts the view back), makes a 2D bookmark (the 2D pan / zoom of
the view) and opens the Bookmark Editor (name, description, apply, delete, new); View > Bookmarks lists every
bookmark of the panel's camera. The 2D Pan/Zoom button turns the panel's 2D pan / zoom off (the whole camera frame)
and on again without moving the camera; its right-click menu lists the 2D bookmarks.

Blender: a bookmark is kept on the panel's camera object (``Object.allset_view_bookmarks``, saved with the file): the
camera's place and lens when the view looks through a camera, else the view itself (place, turn, distance, lens) on
the startup camera that view stands for (persp / top / front / side). The 2D Pan/Zoom button is the view's 2D Pan/Zoom
(operators/pan_zoom.py, the \\ key): off shows the view without its 2D pan / zoom (a camera view: the whole camera
frame, fitted by the camera's Overscan), on brings it back. It lights up when the \\ key, the 2D Pan/Zoom Tool or a 2D
bookmark moves the view; a new session starts with it off. A 2D bookmark keeps a camera view's 2D pan / zoom
(``RegionView3D.view_camera_zoom`` / ``view_camera_offset``).
"""

import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty
from mathutils import Matrix

from .. import i18n, results
from ..operators import pan_zoom

PROP, INDEX = "allset_view_bookmarks", "allset_view_bookmark_index"
BASE = "cameraView"                 # Maya's bookmark names: cameraView1, cameraView2 ...
PAN_ZOOM = i18n.mark("2D Pan/Zoom")
NO_CAMERA = ("This view has no camera to keep bookmarks on: look through a camera, or use the persp / top / front / "
             "side view")
NO_CAMERA_VIEW = "2D bookmarks keep a camera view's 2D pan / zoom: look through a camera first"


# --- the view -------------------------------------------------------------------------------------------------------

def _space(context):
    space = getattr(context, "space_data", None)
    return space if space is not None and space.type == 'VIEW_3D' else None


def _rv3d(context):
    """The view of the panel (its main region's, also from the header / tool header)."""
    space = _space(context)
    return getattr(space, "region_3d", None) if space is not None else None


def camera_view(context):
    """The camera object the view looks through, else None (Blender's persp / ortho view)."""
    from . import panel_menus
    return panel_menus.view_camera(context)


def panel_camera(context, make=False):
    """The object the view's bookmarks are kept on: the camera it looks through, else the startup camera of that view
    (persp / top / front / side; ``make``: a scene without them gets them first)."""
    from . import panel_menus
    return panel_menus.panel_camera(context, make=make)


def bookmarks(ob, pan_zoom=None):
    """The bookmarks of ``ob`` in their order (``pan_zoom`` True / False: only the 2D / only the other ones)."""
    items = getattr(ob, PROP, None) if ob is not None else None
    if items is None:
        return []
    return [b for b in items if pan_zoom is None or b.pan_zoom == pan_zoom]


def row_text(bm):
    """A bookmark's menu row: its name, a 2D one with " (2D Pan/Zoom)" like Maya."""
    return f"{bm.name} ({i18n.iface(PAN_ZOOM)})" if bm.pan_zoom else bm.name


def _taken():
    return {b.name for ob in bpy.data.objects for b in (getattr(ob, PROP, None) or ())}


def add(context, pan_zoom=False):
    """A new bookmark of this view (Maya: a camera bookmark of the panel's camera): its name, or None when the view
    has no camera for it (a 2D bookmark: when it doesn't look through a camera)."""
    space, rv3d = _space(context), _rv3d(context)
    if rv3d is None:
        return None
    looked = camera_view(context)
    if pan_zoom and looked is None:
        return None
    ob = looked or panel_camera(context, make=True)
    if ob is None:
        return None
    from ..operators.naming import next_number
    name = f"{BASE}{next_number(BASE, _taken())}"
    items = getattr(ob, PROP)
    bm = items.add()
    bm.name = name
    if pan_zoom:
        bm.pan_zoom = True
        bm.zoom = rv3d.view_camera_zoom
        bm.offset = tuple(rv3d.view_camera_offset)
    elif looked is not None:
        bm.matrix = [v for row in ob.matrix_world for v in row]
        if ob.type == 'CAMERA':
            bm.ortho = ob.data.type == 'ORTHO'
            bm.lens, bm.ortho_scale = ob.data.lens, ob.data.ortho_scale
    else:
        bm.view = True
        bm.ortho = rv3d.view_perspective == 'ORTHO'
        bm.location = tuple(rv3d.view_location)
        bm.rotation = tuple(rv3d.view_rotation)
        bm.distance = rv3d.view_distance
        bm.lens = space.lens
    setattr(ob, INDEX, len(items) - 1)
    return name


def find(context, name):
    """(object, bookmark) of the view's camera named ``name``, or (object, None)."""
    ob = panel_camera(context)
    return ob, next((b for b in bookmarks(ob) if b.name == name), None)


def apply(context, ob, bm):
    """Put the view back to bookmark ``bm`` of ``ob`` (Maya: the camera goes back to the bookmark); None when done,
    else the reason."""
    space, rv3d = _space(context), _rv3d(context)
    if rv3d is None:
        return NO_CAMERA
    if bm.pan_zoom:
        if camera_view(context) is None:
            return NO_CAMERA_VIEW
        rv3d.view_camera_zoom = bm.zoom
        rv3d.view_camera_offset = tuple(bm.offset)
        pan_zoom_moved(rv3d)
    elif bm.view:
        rv3d.view_perspective = 'ORTHO' if bm.ortho else 'PERSP'
        rv3d.view_location = tuple(bm.location)
        rv3d.view_rotation = tuple(bm.rotation)
        rv3d.view_distance = bm.distance
        if not bm.ortho and bm.lens > 0.0:
            space.lens = bm.lens
    else:
        from . import panel_menus
        if panel_menus.camera_locked(ob):
            return f"{ob.name} is locked (Lock Camera)"
        m = list(bm.matrix)
        ob.matrix_world = Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])
        if ob.type == 'CAMERA':
            if ob.data.type == 'ORTHO' and bm.ortho_scale > 0.0:
                ob.data.ortho_scale = bm.ortho_scale
            elif ob.data.type != 'ORTHO' and bm.lens > 0.0:
                ob.data.lens = bm.lens
    _redraw(context)
    return None


def _redraw(context):
    area = getattr(context, "area", None)
    if area is not None and hasattr(area, "tag_redraw"):
        area.tag_redraw()


def remove(ob, name):
    items = getattr(ob, PROP, None)
    if items is None:
        return False
    i = next((k for k, b in enumerate(items) if b.name == name), None)
    if i is None:
        return False
    items.remove(i)
    setattr(ob, INDEX, max(0, min(getattr(ob, INDEX), len(items) - 1)))
    return True


# --- 2D Pan/Zoom (per view: operators/pan_zoom.py) -----------------------------------------------------------------

def pan_zoom_on(rv3d):
    return pan_zoom.is_on(rv3d)


def pan_zoom_moved(rv3d):
    """A 2D bookmark moved this camera view: its 2D Pan/Zoom is on."""
    pan_zoom.mark_on(rv3d)


def pan_zoom_forget(rv3d):
    """The camera frame was fitted to the view again (another camera, Overscan): no 2D pan / zoom to bring back."""
    pan_zoom.forget(rv3d)


def toggle_pan_zoom(context):
    """The 2D Pan/Zoom button: off = the view without its 2D pan / zoom (a camera view: the whole camera frame), on =
    the 2D pan / zoom back. False without a view."""
    rv3d, space = _rv3d(context), _space(context)
    if rv3d is None:
        return False
    done = pan_zoom.toggle(space, rv3d, (getattr(context, "window", None), getattr(context, "area", None)))
    _redraw(context)
    return done


# --- data -----------------------------------------------------------------------------------------------------------

class ALLSET_PG_view_bookmark(bpy.types.PropertyGroup):
    """A camera bookmark: the camera's place and lens, Blender's view or a 2D pan / zoom"""
    description: StringProperty(name="Description", description="What this bookmark shows")
    pan_zoom: BoolProperty()                     # a 2D bookmark (the view's 2D pan / zoom)
    view: BoolProperty()                         # Blender's own view (no camera object), else the camera's place
    ortho: BoolProperty()
    matrix: FloatVectorProperty(size=16)
    lens: FloatProperty()
    ortho_scale: FloatProperty()
    location: FloatVectorProperty(size=3)
    rotation: FloatVectorProperty(size=4)
    distance: FloatProperty()
    zoom: FloatProperty()
    offset: FloatVectorProperty(size=2)


# --- operators ------------------------------------------------------------------------------------------------------

def _view3d(context):
    area = getattr(context, "area", None)
    return area is not None and area.type == 'VIEW_3D'


class ALLSET_OT_camera_bookmark_add(bpy.types.Operator):
    """Bookmark this view: the camera's place and lens; a 2D bookmark keeps the view's 2D pan / zoom"""
    bl_idname = "allset.camera_bookmark_add"
    bl_label = "New Bookmark"
    bl_options = {'INTERNAL', 'UNDO'}

    pan_zoom: BoolProperty(default=False, options={'SKIP_SAVE'})          # a 2D bookmark

    @classmethod
    def poll(cls, context):
        return _view3d(context)

    def execute(self, context):
        name = add(context, self.pan_zoom)
        if name is None:
            self.report({'WARNING'}, NO_CAMERA_VIEW if self.pan_zoom else NO_CAMERA)
            return {'CANCELLED'}
        results.result(self, name)
        return {'FINISHED'}


class ALLSET_OT_camera_bookmark_apply(bpy.types.Operator):
    """Put the view back to this bookmark"""
    bl_idname = "allset.camera_bookmark_apply"
    bl_label = "Apply Bookmark"
    bl_options = {'INTERNAL', 'UNDO'}

    name: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _view3d(context)

    def execute(self, context):
        ob, bm = find(context, self.name)
        if bm is None:
            self.report({'WARNING'}, f"No bookmark {self.name}")
            return {'CANCELLED'}
        why = apply(context, ob, bm)
        if why:
            self.report({'WARNING'}, why)
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_camera_bookmark_delete(bpy.types.Operator):
    """Delete this bookmark"""
    bl_idname = "allset.camera_bookmark_delete"
    bl_label = "Delete Bookmark"
    bl_options = {'INTERNAL', 'UNDO'}

    name: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _view3d(context)

    def execute(self, context):
        ob = panel_camera(context)
        if ob is None or not remove(ob, self.name):
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_camera_bookmark_editor(bpy.types.Operator):
    """Open the Bookmark Editor of this view's camera: its bookmarks to rename, describe, apply or delete"""
    bl_idname = "allset.camera_bookmark_editor"
    bl_label = "Bookmark Editor"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _view3d(context)

    def execute(self, context):
        if context.window is None:
            return {'CANCELLED'}
        bpy.ops.wm.call_panel(name=ALLSET_PT_camera_bookmarks.bl_idname, keep_open=True)
        return {'FINISHED'}


# --- menus / editor -------------------------------------------------------------------------------------------------

def _rows(layout, ob, pan_zoom=None):
    for bm in bookmarks(ob, pan_zoom):
        layout.operator(ALLSET_OT_camera_bookmark_apply.bl_idname, text=row_text(bm),
                        translate=False).name = bm.name


class ALLSET_MT_panel_bookmarks(bpy.types.Menu):
    """The bookmarks of this view's camera: pick one to put the view back to it"""
    bl_idname = "ALLSET_MT_panel_bookmarks"
    bl_label = "Bookmarks"

    def draw(self, context):
        layout = self.layout
        ob = panel_camera(context)
        _rows(layout, ob, False)
        _rows(layout, ob, True)
        if bookmarks(ob):
            layout.separator()
        layout.operator(ALLSET_OT_camera_bookmark_editor.bl_idname, text="Edit Bookmarks...")


def _draw_toolbar_menu(layout, context, pan_zoom):
    """The right-click menu of the panel toolbar's Bookmarks (``pan_zoom`` False) / 2D Pan/Zoom button."""
    ob = panel_camera(context)
    _rows(layout, ob, pan_zoom)
    if bookmarks(ob, pan_zoom):
        layout.separator()
    sub = layout.row()
    sub.enabled = camera_view(context) is not None
    sub.operator(ALLSET_OT_camera_bookmark_add.bl_idname, text="Create 2D Bookmark").pan_zoom = True
    layout.operator(ALLSET_OT_camera_bookmark_editor.bl_idname, text="Edit 2D Bookmarks...")


class ALLSET_MT_pt_bookmarks(bpy.types.Menu):
    """The camera's bookmarks (right-click on the panel toolbar's Bookmarks button)"""
    bl_idname = "ALLSET_MT_pt_bookmarks"
    bl_label = "Bookmarks"

    def draw(self, context):
        _draw_toolbar_menu(self.layout, context, False)


class ALLSET_MT_pt_pan_zoom(bpy.types.Menu):
    """The camera's 2D bookmarks (right-click on the panel toolbar's 2D Pan/Zoom button)"""
    bl_idname = "ALLSET_MT_pt_pan_zoom"
    bl_label = "2D Bookmarks"

    def draw(self, context):
        _draw_toolbar_menu(self.layout, context, True)


class ALLSET_UL_view_bookmarks(bpy.types.UIList):
    """A camera's bookmarks"""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon='BOOKMARKS')
        if item.pan_zoom:
            row.label(text=PAN_ZOOM)


class ALLSET_PT_camera_bookmarks(bpy.types.Panel):
    """Maya's Bookmark Editor: the bookmarks of this view's camera"""
    bl_idname = "ALLSET_PT_camera_bookmarks"
    bl_label = "Bookmark Editor"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 16

    def draw(self, context):
        layout = self.layout
        ob = panel_camera(context)
        if ob is None:
            layout.label(text=NO_CAMERA, icon='INFO')
            return
        layout.label(text=i18n.compose("Bookmark Editor ({camera})", camera=ob.name), translate=False)
        layout.template_list(ALLSET_UL_view_bookmarks.__name__, "", ob, PROP, ob, INDEX, rows=5)
        items = getattr(ob, PROP)
        i = getattr(ob, INDEX)
        col = layout.column()
        if 0 <= i < len(items):
            col.prop(items[i], "name", text="Name")
            col.prop(items[i], "description", text="Description")
        row = layout.row(align=True)
        row.operator(ALLSET_OT_camera_bookmark_add.bl_idname, text="New Bookmark").pan_zoom = False
        sub = row.row(align=True)
        sub.enabled = camera_view(context) is not None
        sub.operator(ALLSET_OT_camera_bookmark_add.bl_idname, text="New 2D Bookmark").pan_zoom = True
        row = layout.row(align=True)
        row.enabled = 0 <= i < len(items)
        name = items[i].name if 0 <= i < len(items) else ""
        row.operator(ALLSET_OT_camera_bookmark_apply.bl_idname, text="Apply").name = name
        row.operator(ALLSET_OT_camera_bookmark_delete.bl_idname, text="Delete").name = name


CLASSES = (ALLSET_PG_view_bookmark, ALLSET_OT_camera_bookmark_add, ALLSET_OT_camera_bookmark_apply,
           ALLSET_OT_camera_bookmark_delete, ALLSET_OT_camera_bookmark_editor, ALLSET_MT_panel_bookmarks,
           ALLSET_MT_pt_bookmarks, ALLSET_MT_pt_pan_zoom, ALLSET_UL_view_bookmarks, ALLSET_PT_camera_bookmarks)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.allset_view_bookmarks = CollectionProperty(type=ALLSET_PG_view_bookmark)
    bpy.types.Object.allset_view_bookmark_index = IntProperty(options={'HIDDEN'})


def unregister():
    for name in (INDEX, PROP):
        if hasattr(bpy.types.Object, name):
            delattr(bpy.types.Object, name)
    pan_zoom.clear()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
