# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Outliner chrome on Blender's Outliner.

Maya's Outliner has a menu bar Display / Show / Help and a search field.
Outliners set up the Maya way (the Maya Workflow Kit layout and Windows > Outliner:
View Layer mode, no collection rows; ``is_maya_outliner``) get that header: ``OUTLINER_HT_header.draw`` is swapped
while the kit is enabled and restored on unregister; other Outliners draw as usual. The rows of an Outliner the kit
set up are the kit's own (``ui/outliner_tree.py``: joints as rows under their parent joint, Maya's startup cameras
and default sets); Display > Shapes adds the shape rows, Show filters the object types.
"""

import bpy

from . import chrome, own_draw

HELP_URL = "https://docs.blender.org/manual/en/5.2/editors/outliner/index.html"
MENU_BAR = (("Display", "ALLSET_MT_outliner_display"), ("Show", "ALLSET_MT_outliner_show"),
            ("Help", "ALLSET_MT_outliner_help"))


def is_maya_outliner(space):
    """The Maya header goes on this Outliner: View Layer mode, no collection rows, and either no object contents (how
    the kit sets it up) or Display > Shapes on in an Outliner the kit set up — no mode column and no render toggle,
    which the Maya menus can't change and a plain Blender Outliner shows."""
    if (space is None or space.type != 'OUTLINER' or space.display_mode != 'VIEW_LAYER'
            or space.use_filter_collection):
        return False
    return not space.use_filter_object_content or not (space.show_mode_column or space.show_restrict_column_render)


def setup(space):
    """Maya Outliner filters (DAG only, from the world; no eye / mode column: Maya hides with H)."""
    space.display_mode = 'VIEW_LAYER'
    space.use_filter_object_content = False
    space.use_filter_collection = False
    space.use_filter_children = True
    space.show_restrict_column_render = False
    space.show_restrict_column_hide = False
    space.show_mode_column = False      # Maya has no mode column (Blender shows it in edit mode)
    space.sort_method = "NONE"  # Maya lists the DAG in creation order
    from . import outliner_tree         # the kit draws the rows (joints under their skeleton, #348)
    outliner_tree.hide_rows(space)


class ALLSET_MT_outliner_display(bpy.types.Menu):
    """Maya Outliner Display menu"""
    bl_label = "Display"

    def draw(self, context):
        sp, lay = context.space_data, self.layout
        lay.prop(sp, "use_filter_children", text="Children (DAG Hierarchy)")
        op = lay.operator("wm.context_set_enum", text="Sort Alphabetically", depress=sp.sort_method == "ALPHA")
        op.data_path = "space_data.sort_method"
        op.value = "ALPHA"
        op = lay.operator("wm.context_set_enum", text="Creation Order", depress=sp.sort_method != "ALPHA")
        op.data_path = "space_data.sort_method"
        op.value = "NONE"
        lay.prop(sp, "show_restrict_column_hide", text="Visibility Column")
        lay.separator()
        # Maya Display > Shapes: a shape row (pCubeShape1) under each transform
        lay.prop(sp, "use_filter_object_content", text="Shapes")
        lay.separator()
        # Blender's collections have no Maya counterpart: this Outliner shows them with Blender's own rows
        lay.operator("allset.outliner_collections", text="Blender Collections").show = True


class ALLSET_MT_outliner_show(bpy.types.Menu):
    """Maya Outliner Show menu: object type filters"""
    bl_label = "Show"

    def draw(self, context):
        sp, lay = context.space_data, self.layout
        from . import outliner_tree
        if outliner_tree.is_tree(sp):
            # the kit tree hides Blender's rows with Objects off: Maya's Show All turns every type back on
            lay.operator("allset.outliner_tree_show_all", text="Show All")
            col = lay.column()
        else:
            lay.prop(sp, "use_filter_object", text="Objects")
            col = lay.column()
            col.active = sp.use_filter_object
        for prop, label in (("use_filter_object_mesh", "Geometry"), ("use_filter_object_armature", "Joints"),
                            ("use_filter_object_empty", "Groups / Locators"), ("use_filter_object_light", "Lights"),
                            ("use_filter_object_camera", "Cameras"), ("use_filter_object_others", "Others")):
            col.prop(sp, prop, text=label)


class ALLSET_MT_outliner_help(bpy.types.Menu):
    bl_label = "Help"

    def draw(self, context):
        self.layout.operator("wm.url_open", text="Help on Outliner").url = HELP_URL


def is_collection_view(space):
    """A Maya Outliner switched to Blender Collections: View Layer mode with collection rows and no mode column (the
    kit's setup; Blender's Outliner shows the mode column)."""
    return (space is not None and space.type == 'OUTLINER' and space.display_mode == 'VIEW_LAYER'
            and space.use_filter_collection and not space.show_mode_column)


class ALLSET_OT_outliner_collections(bpy.types.Operator):
    """Show Blender's collections in this Outliner with Blender's own rows and header; Maya Outliner goes back to the
    Maya Outliner"""
    bl_idname = "allset.outliner_collections"
    bl_label = "Blender Collections"
    bl_options = {'INTERNAL'}

    show: bpy.props.BoolProperty(default=True, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and space.type == 'OUTLINER'

    def execute(self, context):
        space = context.space_data
        if self.show:
            space.display_mode = 'VIEW_LAYER'
            space.use_filter_collection = True
            space.use_filter_object = True      # Blender's rows: collections with their objects
            space.show_mode_column = False
        else:
            space.use_filter_collection = False
            from . import outliner_tree         # the kit draws the Maya rows again
            outliner_tree.hide_rows(space)
        if context.area is not None:
            context.area.tag_redraw()
        return {'FINISHED'}


def _draw(self, context):
    space = context.space_data
    if not is_maya_outliner(space):
        if is_collection_view(space):           # back to the Maya Outliner (first: a narrow header clips the end)
            self.layout.operator("allset.outliner_collections", text="Maya Outliner").show = False
        return own_draw.original("OUTLINER_HT_header", _draw)(self, context)
    layout = self.layout
    from . import maya_dock      # Maya's dotted handle: tear the Outliner off / dock it back
    layout.operator("allset.dock_handle", text=maya_dock.HANDLE[:8], emboss=False)
    chrome.menu_bar(layout, MENU_BAR)
    layout.prop(space, "filter_text", text="", icon='VIEWZOOM', placeholder="Search...")


classes = (ALLSET_MT_outliner_display, ALLSET_MT_outliner_show, ALLSET_MT_outliner_help,
           ALLSET_OT_outliner_collections)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    own_draw.swap("OUTLINER_HT_header", _draw)   # Blender's own draw only


def unregister():
    own_draw.restore("OUTLINER_HT_header", _draw)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
