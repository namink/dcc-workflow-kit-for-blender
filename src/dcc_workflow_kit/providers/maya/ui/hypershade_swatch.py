# SPDX-License-Identifier: GPL-3.0-or-later
"""RMB on a Hypershade Browser material swatch: Maya's swatch menu.

Maya opens a marking menu on the swatch: N Assign Material To Viewport Selection, NE Paint Assign Shader, E Select
Objects with Material, SW Refresh Swatch, S Graph Network, then a list (Frame Objects with Material, Select Input /
Output Nodes, Rename, Help). RMB on a Blender UI button opens Blender's button context menu from C (no keymap item
sees it), so these items go on top of that menu, in the same order, the way the Channel Box's RMB menu does
(``channel_box.draw_button_menu``).
"""

import bpy
from bpy.props import EnumProperty, StringProperty

from .. import results
from .hypershade_ops import PICK_PROP

# Maya's order: the marking menu's directions (N, NE, E, SW, S), then the list
ORDER = ("ASSIGN", "PAINT", "SELECT_OBJECTS", "REFRESH", "GRAPH", None, "FRAME_OBJECTS", "SELECT_INPUTS", "RENAME",
         None, "HELP")


def swatch_material(context):
    """The material whose Browser swatch is under the mouse (its pick toggle is the hovered button), or None."""
    ptr = getattr(context, "button_pointer", None)
    prop = getattr(context, "button_prop", None)
    if isinstance(ptr, bpy.types.Material) and prop is not None and prop.identifier == PICK_PROP:
        return ptr
    return None


def _users(context, mat):
    return [o for o in context.view_layer.objects if any(s.material == mat for s in o.material_slots)]


class ALLSET_OT_hs_swatch_cmd(bpy.types.Operator):
    """Maya Hypershade swatch menu command"""
    bl_idname = "allset.hs_swatch_cmd"
    bl_label = "Swatch Command"
    bl_options = {'UNDO'}

    material: StringProperty(name="Material", options={'SKIP_SAVE'})
    action: EnumProperty(items=(
        ("ASSIGN", "Assign Material To Viewport Selection", "Assign this material to the selected objects or faces"),
        ("PAINT", "Paint Assign Shader", "Blender has no paint-assign tool: select faces in Edit Mode and use "
                                         "Assign Material To Viewport Selection"),
        ("SELECT_OBJECTS", "Select Objects with Material", "Select the objects that use this material"),
        ("REFRESH", "Refresh Swatch", "Render this material's preview again"),
        ("GRAPH", "Graph Network", "Show this material's node network in the Graph"),
        ("FRAME_OBJECTS", "Frame Objects with Material", "Select and frame the objects that use this material"),
        ("SELECT_INPUTS", "Select Input Nodes", "Show the material's network and select the nodes feeding its "
                                                "shader"),
        ("RENAME", "Rename", "Rename the material"),
        ("HELP", "Help", "Open Blender's manual page for materials"),
    ), name="Action", options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, props):
        return _item(props.action).description

    def execute(self, context):
        from .hypershade_materials import show
        mat = bpy.data.materials.get(self.material)
        if mat is None:
            return {'CANCELLED'}
        act = self.action
        if act == "PAINT":
            self.report({'WARNING'}, _item(act).description)
            return {'CANCELLED'}
        if act == "ASSIGN":
            return bpy.ops.allset.assign_material(material=mat.name)
        if act == "REFRESH":
            mat.preview_ensure()
            mat.update_tag()
            return {'FINISHED'}
        if act == "HELP":
            try:
                return bpy.ops.wm.doc_view_manual(doc_id="bpy.types.Material")
            except RuntimeError:
                self.report({'WARNING'}, "No manual page")
                return {'CANCELLED'}
        if act == "RENAME":
            show(context, mat)
            return bpy.ops.wm.call_panel('INVOKE_DEFAULT', name="ALLSET_PT_hs_rename", keep_open=False)
        if act in {"SELECT_OBJECTS", "FRAME_OBJECTS"}:
            hits = _users(context, mat)
            for o in context.view_layer.objects:
                o.select_set(o in hits)
            if hits:
                context.view_layer.objects.active = hits[0]
            if act == "FRAME_OBJECTS" and hits:
                from .hypershade_hands import _frame_in_views
                _frame_in_views(context)
            results.result(self, f"{len(hits)} object(s) with {mat.name}")
            return {'FINISHED'}
        # GRAPH / SELECT_INPUTS: the material's network in the Graph
        show(context, mat)
        tree = mat.node_tree
        if tree is not None and act == "SELECT_INPUTS":
            from .hypershade_hands import _upstream
            out = next((n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
            keep = _upstream(tree, out) if out is not None else set()
            for n in tree.nodes:
                n.select = n in keep
        _tag_graphs(context)
        return {'FINISHED'}


class ALLSET_PT_hs_rename(bpy.types.Panel):
    """Rename the Hypershade's current material"""
    bl_label = "Rename"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_options = {'INSTANCED'}

    def draw(self, context):
        from .hypershade_materials import current
        mat = current(context)
        if mat is not None:
            self.layout.activate_init = True
            self.layout.prop(mat, "name", text="")


def _item(key):
    """The action enum item ``key`` (label and description, from the operator's own items)."""
    return bpy.ops.allset.hs_swatch_cmd.get_rna_type().properties["action"].enum_items[key]


def _tag_graphs(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'NODE_EDITOR':
                area.tag_redraw()


def draw_button_menu(self, context):
    mat = swatch_material(context)
    if mat is None:
        return
    lay = self.layout
    for key in ORDER:
        if key is None:
            lay.separator()
            continue
        row = lay.row()
        row.enabled = key != "PAINT"
        op = row.operator(ALLSET_OT_hs_swatch_cmd.bl_idname, text=_item(key).name)
        op.material, op.action = mat.name, key
    lay.separator()


classes = (ALLSET_OT_hs_swatch_cmd, ALLSET_PT_hs_rename)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.UI_MT_button_context_menu.prepend(draw_button_menu)


def unregister():
    bpy.types.UI_MT_button_context_menu.remove(draw_button_menu)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
