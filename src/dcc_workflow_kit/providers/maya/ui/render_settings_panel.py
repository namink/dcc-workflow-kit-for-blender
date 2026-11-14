# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Settings in Maya mode: Maya's Common tab values that Render Sequence uses, in Blender's Properties >
Render tab (the tab the kit's Render Settings opens), right under Render Engine like Maya's Common tab under
Render Using (a sub-panel of Blender's engine panel, so it stays there whatever panel order the editor keeps):

- Frame Range > Skip existing frames: Blender's Overwrite off + Placeholders on (``Scene.allset_skip_existing``);
- Renderable Cameras: each camera's Renderable check (``Camera.allset_renderable``, the same check as the Attribute
  Editor camera tab and the Render Sequence option window).

With Maya mode off the panel isn't shown: plain Blender stays as it is.
"""

import bpy


class ALLSET_PT_render_common(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"
    bl_label = "Common"
    bl_parent_id = "RENDER_PT_context"

    @classmethod
    def poll(cls, context):
        from .. import switch
        return context.scene is not None and switch.is_on()

    def draw(self, context):
        from ..operators import render_cameras
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        render_cameras.draw_settings(layout, context.scene)


classes = (ALLSET_PT_render_common,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
