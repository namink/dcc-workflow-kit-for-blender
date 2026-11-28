# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's image plane menus of a viewport panel (#409): View > Image Plane (Import Image..., Import Movie..., Image
Plane Attributes = the camera's image planes) and the right-click menu of the panel toolbar's Image Plane button
(Import Image..., Display Mode, Delete: <the camera's first image plane>). The rows are in ``ui/panel_menu_data.py``
(counted with the other panel menus); the operators in ``operators/image_plane.py``.
"""

import json

import bpy

from .. import i18n
from . import panel_menus
from .panel_menu_data import IMAGE_PLANE, PT_IMAGE_PLANE, PT_IMAGE_PLANE_DISPLAY


def _planes(context):
    from ..operators import image_plane
    try:
        return image_plane.camera_planes(context)
    except (AttributeError, ReferenceError):
        return []


# The rows' own tooltips (the button's operator describes its show / hide click)
TIPS = {
    "Import Image...": "Pick an image file for a new image plane of this view (attached to the camera it looks "
                       "through)",
    "Import Movie...": "Pick a movie file for a new image plane of this view that plays it along the frames",
    "Delete:": "Delete the first image plane of this view's camera",
    "None": "Hide the first image plane of this view's camera",
    "RGBA": "Show the first image plane of this view's camera with its colours and alpha",
}


def _run_row(layout, row, label=None):
    p = layout.operator(panel_menus.ALLSET_OT_panel_run.bl_idname, text=label or row[1], translate=label is None)
    p.op, p.props, p.tip = row[2], json.dumps(row[3]), TIPS.get(row[1], "")


def _draw(layout, context, rows, idname):
    for row in rows:
        if row[0] == "run":
            _run_row(layout, row)
        else:
            panel_menus.draw_rows(layout, context, [row], idname)


def _menu_row(layout, row, enabled):
    sub = layout.row()
    sub.enabled = enabled
    sub.menu(row[2], text=row[1])


class ALLSET_MT_panel_image_plane(bpy.types.Menu):
    """Maya View > Image Plane: import an image or a movie onto this view's camera"""
    bl_idname = "ALLSET_MT_panel_image_plane"
    bl_label = "Image Plane"

    def draw(self, context):
        layout = self.layout
        planes = _planes(context)
        for row in IMAGE_PLANE:
            if row[0] == "menu":
                _menu_row(layout, row, bool(planes))     # Maya greys Image Plane Attributes without a plane
            else:
                _draw(layout, context, [row], self.bl_idname)


class ALLSET_MT_panel_image_plane_attributes(bpy.types.Menu):
    """The image planes of this view's camera: pick one to select it and show it in the Attribute Editor"""
    bl_idname = "ALLSET_MT_panel_image_plane_attributes"
    bl_label = "Image Plane Attributes"

    def draw(self, context):
        for ob in _planes(context):
            self.layout.operator("allset.image_plane_attributes", text=ob.name, translate=False).name = ob.name


class ALLSET_MT_pt_image_plane(bpy.types.Menu):
    """The image plane of this view's camera (right-click on the panel toolbar's Image Plane button)"""
    bl_idname = "ALLSET_MT_pt_image_plane"
    bl_label = "Image Plane"

    def draw(self, context):
        layout = self.layout
        first = next(iter(_planes(context)), None)
        for row in PT_IMAGE_PLANE:
            if row[0] == "menu":
                _menu_row(layout, row, first is not None)
            elif row[0] == "run" and row[2] == "allset.image_plane_delete":
                sub = layout.row()
                sub.enabled = first is not None
                _run_row(sub, row, i18n.iface(row[1]) + (" " + first.name if first is not None else ""))
            else:
                _draw(layout, context, [row], self.bl_idname)


class ALLSET_MT_pt_image_plane_display(bpy.types.Menu):
    """Display Mode of the first image plane of this view's camera"""
    bl_idname = "ALLSET_MT_pt_image_plane_display"
    bl_label = "Display Mode"

    def draw(self, context):
        layout = self.layout
        layout.enabled = bool(_planes(context))
        _draw(layout, context, PT_IMAGE_PLANE_DISPLAY, self.bl_idname)


classes = (ALLSET_MT_panel_image_plane, ALLSET_MT_panel_image_plane_attributes, ALLSET_MT_pt_image_plane,
           ALLSET_MT_pt_image_plane_display)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
