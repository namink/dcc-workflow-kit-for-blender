# SPDX-License-Identifier: GPL-3.0-or-later
"""Hypershade commands: ``allset.hypershade`` opens the window; ``hs_pick`` / ``hs_item`` are the Browser swatch
clicks (``PICK_PROP`` = the swatch's Material toggle, ``_get_pick`` / ``_set_pick``), ``hs_create`` / ``hs_node``
the Create pane, ``hs_edit`` the Edit menu. Area lookups come from hypershade_window.py, the current material
from hypershade_materials.py.
"""

import bpy
from bpy.props import EnumProperty, StringProperty

from .. import compat, results
from ..operators import material as material_ops
from ..operators import menu_extras
from .hypershade_window import _largest_area, build_later, hypershade_windows, is_hypershade
from .hypershade_materials import TABS, assigned_materials, current, materials, release_editors, show


class ALLSET_OT_hypershade(bpy.types.Operator):
    """Hypershade: Maya's window with the Browser, Material Viewer, Create, the graph (Shader Editor) and the
    Property Editor"""
    bl_idname = "allset.hypershade"
    bl_label = "Hypershade"

    def execute(self, context):
        if context.window is None:
            return {'CANCELLED'}
        if is_hypershade(context.screen):     # Hypershade > Window > Browser / Create / Property Editor: shown here
            return {'FINISHED'}
        # Maya brings its one Hypershade to the front; Blender can't raise a window: the old one closes and a fresh
        # one opens on top
        from . import maya_dock
        for w in hypershade_windows(context.window_manager):
            maya_dock.close_window_later(w)
        area = _largest_area(context)
        if area is None:
            return {'CANCELLED'}
        window = menu_extras.open_window(context, area, "hypershade")
        if window is None:
            from . import window_places
            if not window_places.deferred():     # opens on a later tick (#203)
                self.report({'ERROR'}, "Could not open a new window")
            return {'CANCELLED'}
        target = window.screen.areas[0]
        target.ui_type = 'ShaderNodeTree'
        mat = current(context)
        if mat is not None:
            show(context, mat, target.spaces.active)
        build_later(window, target)
        return {'FINISHED'}


class ALLSET_OT_hs_pick(bpy.types.Operator):
    """Show this material in the graph and the Property Editor (Maya Hypershade swatch click)"""
    bl_idname = "allset.hs_pick"
    bl_label = "Pick Material"

    material: StringProperty(name="Material", options={'SKIP_SAVE'})

    def execute(self, context):
        mat = bpy.data.materials.get(self.material)
        if mat is None:
            return {'CANCELLED'}
        show(context, mat, context.space_data)
        focus_material(mat)
        _redraw(context)
        return {'FINISHED'}


def focus_material(mat):
    """A swatch click selects the material node itself (Maya): its shader becomes the graph's only selected, active
    node, so the Property Editor shows the material, not a node picked before."""
    tree = mat.node_tree
    if tree is None:
        return
    shader = next((n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if shader is None:
        return
    for n in tree.nodes:
        n.select = n == shader
    tree.nodes.active = shader


# Browser material swatch = a toggle on this Material property: on = the Hypershade's current material; a click
# picks it like ``allset.hs_pick`` (clicking the picked one keeps it picked). Nothing is stored (get / set).
PICK_PROP = "allset_hs_pick"


def _get_pick(mat):
    try:
        return current(bpy.context) == mat
    except (AttributeError, ReferenceError):
        return False


def _set_pick(mat, _value):
    context = bpy.context
    show(context, mat, getattr(context, "space_data", None))
    focus_material(mat)
    _redraw(context)


class ALLSET_OT_hs_item(bpy.types.Operator):
    """Maya Hypershade Browser swatch: a light / camera = select it; a texture / utility = show it in its graph;
    a world = the scene's environment"""
    bl_idname = "allset.hs_item"
    bl_label = "Browser Item"
    bl_options = {'REGISTER', 'UNDO'}

    tab: EnumProperty(items=[t for t in TABS], name="Tab", options={'SKIP_SAVE'})
    key: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        if self.tab in {'LIGHTS', 'CAMERAS'}:
            ob = context.scene.objects.get(self.key)
            if ob is None:
                return {'CANCELLED'}
            for o in context.selected_objects:
                o.select_set(False)
            ob.select_set(True)
            context.view_layer.objects.active = ob
        elif self.tab == 'RENDERING':
            world = bpy.data.worlds.get(self.key)
            if world is None:
                return {'CANCELLED'}
            context.scene.world = world
        elif self.tab in {'TEXTURES', 'UTILITIES'}:
            mname, _sep, nname = self.key.partition("::")
            mat = bpy.data.materials.get(mname)
            node = mat.node_tree.nodes.get(nname) if mat is not None and mat.node_tree else None
            if node is None:
                return {'CANCELLED'}
            show(context, mat, context.space_data)
            for n in mat.node_tree.nodes:
                n.select = n == node
            mat.node_tree.nodes.active = node
        else:
            return bpy.ops.allset.hs_pick(material=self.key)
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_hs_create(bpy.types.Operator):
    """Create a new material (Blender's Principled BSDF) without assigning it (Maya Hypershade Create)"""
    bl_idname = "allset.hs_create"
    bl_label = "New Material"
    bl_options = {'REGISTER', 'UNDO'}

    kind: StringProperty(name="Type", options={'HIDDEN', 'SKIP_SAVE'})   # of an older call: ignored

    def execute(self, context):
        mat = material_ops.new_material()
        mat.use_fake_user = True    # no user yet: Blender would drop it on save, Maya keeps it
        show(context, mat, context.space_data)
        context.window_manager.allset_hs_tab = 'MATERIALS'
        return {'FINISHED'}


class ALLSET_OT_hs_node(bpy.types.Operator):
    """Add this Maya node type to the current material's graph (Maya Hypershade Create: a texture / utility node
    is made on its own; the Blender node is left unconnected)"""
    bl_idname = "allset.hs_node"
    bl_label = "Create Node"
    bl_options = {'REGISTER', 'UNDO'}

    node_type: StringProperty(name="Node", options={'SKIP_SAVE'})
    label: StringProperty(name="Maya Name", options={'SKIP_SAVE'})
    operation: StringProperty(name="Operation", options={'SKIP_SAVE'})    # Math / Vector Math nodes

    def execute(self, context):
        mat = current(context)
        if mat is None:
            mat = material_ops.new_material()
            mat.use_fake_user = True
        compat.ensure_material_nodes(mat)
        tree = mat.node_tree
        try:
            node = tree.nodes.new(self.node_type)
        except RuntimeError:
            self.report({'ERROR'}, f"Blender has no node {self.node_type}")
            return {'CANCELLED'}
        if self.label:
            node.label = self.label
        if self.operation and hasattr(node, "operation"):
            node.operation = self.operation
        left = min((n.location.x for n in tree.nodes if n != node), default=0.0)
        node.location = (left - 300.0, 300.0)      # left of the network, like a new upstream node
        for n in tree.nodes:
            n.select = n == node
        tree.nodes.active = node
        show(context, mat, context.space_data)
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_hs_edit(bpy.types.Operator):
    """Maya Hypershade Edit menu commands"""
    bl_idname = "allset.hs_edit"
    bl_label = "Hypershade Edit"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(
        ("DELETE", "Delete", "Delete the current material"),
        ("DELETE_UNUSED", "Delete Unused Nodes", "Delete the materials no object uses"),
        ("DELETE_MATERIALS", "Delete All Materials", "Delete every material"),
        ("SELECT_OBJECTS", "Select Objects with Materials", "Select the objects that use the current material"),
        ("FROM_OBJECT", "Select Materials from Objects", "The active object's material becomes current"),
        ("DUPLICATE", "Duplicate", "Copy the current material (and its network)"),
    ), name="Action", options={'SKIP_SAVE'})

    def execute(self, context):
        act = self.action
        cur = current(context)
        if act in {"DELETE", "SELECT_OBJECTS", "DUPLICATE"} and cur is None:
            self.report({'WARNING'}, "No material selected in the Hypershade")
            return {'CANCELLED'}
        if act == "DELETE":
            release_editors([cur])
            bpy.data.materials.remove(cur)
            context.window_manager.allset_hs_material = ""
        elif act in {"DELETE_UNUSED", "DELETE_MATERIALS"}:
            assigned = assigned_materials() if act == "DELETE_UNUSED" else set()
            doomed = [m for m in materials() if m not in assigned]
            release_editors(doomed)
            if context.window_manager.allset_hs_material in {m.name for m in doomed}:
                context.window_manager.allset_hs_material = ""
            for m in doomed:
                bpy.data.materials.remove(m)
            n = len(doomed)
            results.result(self, f"Deleted {n} material{'s' if n != 1 else ''}")
        elif act == "SELECT_OBJECTS":
            for o in context.selected_objects:
                o.select_set(False)
            hits = [o for o in context.scene.objects if any(s.material == cur for s in o.material_slots)]
            for o in hits:
                try:
                    o.select_set(True)
                except RuntimeError:
                    pass
            if hits:
                context.view_layer.objects.active = hits[0]
        elif act == "FROM_OBJECT":
            ob = context.active_object
            if ob is None or ob.active_material is None:
                self.report({'WARNING'}, "Select an object with a material")
                return {'CANCELLED'}
            show(context, ob.active_material, context.space_data)
        elif act == "DUPLICATE":
            new = cur.copy()
            new.use_fake_user = True
            show(context, new, context.space_data)
        _redraw(context)
        return {'FINISHED'}


def _redraw(context):
    for area in context.screen.areas if context.screen else ():
        area.tag_redraw()
