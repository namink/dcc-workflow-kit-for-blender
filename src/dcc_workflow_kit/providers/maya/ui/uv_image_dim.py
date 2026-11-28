# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya UV Editor > Image > Dim: the image drawn darker under the UVs.

The menu item (and the UV Editor toolbar's Dim button) toggles ``WindowManager.allset_uv_image_dim`` (off by
default, like Maya); its option box opens Image Dim Options with the Dimming slider (0 - 1, default 0.5), which
changes the image at once while it is dragged. Dimmed, the image shows at (1 - Dimming) of its brightness.

Blender has no image brightness for the UV Editor, so an Image Editor WINDOW POST_PIXEL handler darkens it: Blender
draws the UVs into an overlay that it lays over the image, and the image shows through where that overlay is
transparent. The handler raises only the overlay's alpha over the image's rectangle (colour writes masked off), so
the image behind is weighted down while every UV line, point and face fill keeps its colour.
"""

import bpy
import gpu
from bpy.props import BoolProperty, FloatProperty
from gpu_extras.batch import batch_for_shader

DEFAULT_DIMMING = 0.5
_handle = []


def _redraw(self=None, context=None):
    wm = bpy.context.window_manager
    for win in wm.windows if wm else ():
        for area in win.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.tag_redraw()


def _tiles(image):
    """The UV squares the image covers: (u, v) of each UDIM tile's corner, else the 0-1 square."""
    if image.source == 'TILED':
        return [((t.number - 1001) % 10, (t.number - 1001) // 10) for t in image.tiles]
    return [(0, 0)]


def _quads(context, space):
    region = context.region
    if getattr(space, "show_repeat", False):     # View > Repeat Image: the image fills the whole view
        w, h = region.width, region.height
        return [(0, 0), (w, 0), (w, h), (0, 0), (w, h), (0, h)]
    v2d = region.view2d
    pts = []
    for u, v in _tiles(space.image):
        x0, y0 = v2d.view_to_region(u, v, clip=False)
        x1, y1 = v2d.view_to_region(u + 1, v + 1, clip=False)
        pts += [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]
    return pts


def overlay_alpha(dimming):
    """Overlay alpha that leaves the image at (1 - ``dimming``) of its brightness."""
    return min(1.0, max(0.0, dimming))


def _draw():
    context = bpy.context
    wm = context.window_manager
    if not wm.allset_uv_image_dim:
        return
    space = context.space_data
    area = context.area
    if space is None or area is None or area.ui_type != 'UV' or space.image is None:
        return
    alpha = overlay_alpha(wm.allset_uv_image_dimming)
    if alpha <= 0.0:
        return
    pts = _quads(context, space)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": pts})
    gpu.state.blend_set('ALPHA')
    gpu.state.color_mask_set(False, False, False, True)     # only the overlay's alpha: UV colours stay as drawn
    shader.uniform_float("color", (0.0, 0.0, 0.0, alpha))
    batch.draw(shader)
    gpu.state.color_mask_set(True, True, True, True)
    gpu.state.blend_set('NONE')


class ALLSET_OT_uv_image_dim(bpy.types.Operator):
    """Dim the image in the UV Editor (press and hold the menu item for the Image Dim Options)"""
    bl_idname = "allset.uv_image_dim"
    bl_label = "Dim Image"
    bl_options = {'INTERNAL'}

    option_box: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        if self.option_box:
            return context.window_manager.invoke_popup(self, width=320)
        return self.execute(context)

    def draw(self, context):
        lay = self.layout
        lay.label(text="Image Dim Options")
        box = lay.box()
        box.label(text="Settings")
        box.prop(context.window_manager, "allset_uv_image_dimming", slider=True)

    def execute(self, context):
        if self.option_box:
            return {'FINISHED'}
        wm = context.window_manager
        wm.allset_uv_image_dim = not wm.allset_uv_image_dim
        return {'FINISHED'}


classes = (ALLSET_OT_uv_image_dim,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.allset_uv_image_dim = BoolProperty(name="Dim", default=False, update=_redraw,
                                          description="Maya UV Editor > Image > Dim: draw the image darker under the "
                                                      "UVs")
    wm.allset_uv_image_dimming = FloatProperty(name="Dimming", default=DEFAULT_DIMMING, min=0.0, max=1.0,
                                               precision=2, update=_redraw,
                                               description="How much darker the dimmed image is: 0 = unchanged, "
                                                           "1 = black")
    _handle.append(bpy.types.SpaceImageEditor.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL'))


def unregister():
    while _handle:
        bpy.types.SpaceImageEditor.draw_handler_remove(_handle.pop(), 'WINDOW')
    wm = bpy.types.WindowManager
    for name in ("allset_uv_image_dimming", "allset_uv_image_dim"):
        if hasattr(wm, name):
            delattr(wm, name)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
