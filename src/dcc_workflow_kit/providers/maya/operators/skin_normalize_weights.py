# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Skin > Normalize Weights > Disable / Enable / Enable Post (``allset.skin_normalize_mode``). Blender's
Armature modifier always divides by the weight sum (Post), so None / Interactive skins get a Geometry Nodes modifier
``<skinCluster>WeightSum`` after it that scales the world position by the weight sum (``ensure_sum_modifier``);
``is_part`` marks it as part of the skin. The depsgraph handler that keeps it current is in skin_tools_199.
"""

import bpy
from bpy.props import EnumProperty

from .. import results
from . import skin
from .. import i18n
from .skin_weight_access import influence_names, skinned_meshes

# --- Normalize Weights: None / Interactive / Post --------------------------------------------------------------------
SUM_SUFFIX = "WeightSum"               # modifier "<skinClusterN>WeightSum" (part of the skin node, not an INPUTS node)
SUM_TAG = "allset_weight_sum"          # node group ID prop: the influence names it sums
NORMALIZE_LABELS = {"NONE": "Disable Weight Normalization", "INTERACTIVE": "Enable Weight Normalization",
                    "POST": "Enable Weight Post Normalization"}
MAYA_VALUE = {"NONE": 0, "INTERACTIVE": 1, "POST": 2}      # skinCluster.normalizeWeights


def is_part(md):
    """True for the kit's weight-sum modifier: part of the skin (hide it from INPUTS / the AE like a Hook base)."""
    return md.type == 'NODES' and md.node_group is not None and SUM_TAG in md.node_group


def sum_modifier(mesh):
    return next((m for m in mesh.modifiers if is_part(m)), None)


def _link(tree, a, b):
    tree.links.new(a, b)


def _build_sum_group(tree, names):
    """position_world *= sum(influence weights) where that sum > 1e-4 (Blender's Armature modifier leaves points
    whose sum is below 1e-4 at rest), in the object's world space (Maya scales about the world origin)."""
    tree.nodes.clear()
    if not tree.interface.items_tree:
        tree.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        tree.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    n = tree.nodes
    gin = n.new('NodeGroupInput')
    gout = n.new('NodeGroupOutput')
    total = None
    for name in names:
        na = n.new('GeometryNodeInputNamedAttribute')
        na.data_type = 'FLOAT'
        na.inputs["Name"].default_value = name
        if total is None:
            total = na.outputs["Attribute"]
        else:
            add = n.new('ShaderNodeMath')
            add.operation = 'ADD'
            _link(tree, total, add.inputs[0])
            _link(tree, na.outputs["Attribute"], add.inputs[1])
            total = add.outputs[0]
    setp = n.new('GeometryNodeSetPosition')
    _link(tree, gin.outputs[0], setp.inputs["Geometry"])
    _link(tree, setp.outputs["Geometry"], gout.inputs[0])
    if total is None:
        return
    self_ob = n.new('GeometryNodeSelfObject')
    info = n.new('GeometryNodeObjectInfo')
    info.transform_space = 'ORIGINAL'
    _link(tree, self_ob.outputs[0], info.inputs["Object"])
    pos = n.new('GeometryNodeInputPosition')
    to_world = n.new('FunctionNodeTransformPoint')
    _link(tree, pos.outputs[0], to_world.inputs["Vector"])
    _link(tree, info.outputs["Transform"], to_world.inputs["Transform"])
    scale = n.new('ShaderNodeVectorMath')
    scale.operation = 'SCALE'
    _link(tree, to_world.outputs[0], scale.inputs[0])
    _link(tree, total, scale.inputs["Scale"])
    inv = n.new('FunctionNodeInvertMatrix')
    _link(tree, info.outputs["Transform"], inv.inputs[0])
    back = n.new('FunctionNodeTransformPoint')
    _link(tree, scale.outputs[0], back.inputs["Vector"])
    _link(tree, inv.outputs[0], back.inputs["Transform"])
    cmp = n.new('FunctionNodeCompare')
    cmp.data_type = 'FLOAT'
    cmp.operation = 'GREATER_THAN'
    _link(tree, total, cmp.inputs[0])
    cmp.inputs[1].default_value = 1e-4
    _link(tree, cmp.outputs[0], setp.inputs["Selection"])
    _link(tree, back.outputs[0], setp.inputs["Position"])


def _sum_signature(mesh):
    return "\n".join(influence_names(mesh))


def ensure_sum_modifier(mesh):
    """The weight-sum modifier right after the skin's Armature modifier, summing the current influences."""
    arm_md = skin.armature_modifier(mesh)
    if arm_md is None:
        return None
    md = sum_modifier(mesh)
    if md is None:
        tree = bpy.data.node_groups.new(f".Allset Weight Sum {mesh.name}", 'GeometryNodeTree')
        md = mesh.modifiers.new(f"{arm_md.name}{SUM_SUFFIX}", 'NODES')
        md.node_group = tree
        md.show_in_editmode = arm_md.show_in_editmode
        md.show_on_cage = arm_md.show_on_cage            # the posed cage includes the sum (component mode)
        md.show_expanded = False
        target = list(mesh.modifiers).index(arm_md) + 1
        if list(mesh.modifiers).index(md) != target:
            with bpy.context.temp_override(object=mesh):
                bpy.ops.object.modifier_move_to_index(modifier=md.name, index=target)
    sig = _sum_signature(mesh)
    if md.node_group.get(SUM_TAG) != sig or not md.node_group.nodes:
        _build_sum_group(md.node_group, influence_names(mesh))
        md.node_group[SUM_TAG] = sig
    return md


def remove_sum_modifier(mesh):
    md = sum_modifier(mesh)
    if md is None:
        return
    tree = md.node_group
    mesh.modifiers.remove(md)
    if tree is not None and tree.users == 0:
        bpy.data.node_groups.remove(tree)


def set_normalize_mode(context, mesh, mode):
    """Maya skinCluster.normalizeWeights for one skin: the mode only (weights are not touched, switching
    to Interactive or Post leaves unnormalised weights as they are)."""
    mesh[skin.NORMALIZE_PROP] = mode
    if mode == "POST":
        remove_sum_modifier(mesh)
    else:
        ensure_sum_modifier(mesh)


def normalize_state(context):
    """The normalize mode of the active skin (None without one): the menu's radio state."""
    meshes = skinned_meshes(context)
    return skin.normalize_mode(meshes[0]) if meshes else None


class ALLSET_OT_skin_normalize_mode(bpy.types.Operator):
    """Maya Skin > Normalize Weights > Disable / Enable / Enable Post: how the selected skins keep their weights"""
    bl_idname = "allset.skin_normalize_mode"
    bl_label = "Weight Normalization"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(name="Normalize Weights", items=skin.NORMALIZE, default="INTERACTIVE")

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return {"NONE": "Maya Disable Weight Normalization: weights stay as painted and deform unnormalised",
                "INTERACTIVE": "Maya Enable Weight Normalization: painting a joint takes weight from the others",
                "POST": "Maya Enable Weight Post Normalization: weights are stored as painted, the skin deforms "
                        "with them normalised"}[props.mode]

    def execute(self, context):
        meshes = skinned_meshes(context)
        if not meshes:
            self.report({'ERROR'}, "Select a skinned object or its components")     # Maya's error text
            return {'CANCELLED'}
        for mesh in meshes:
            set_normalize_mode(context, mesh, self.mode)
        context.tool_settings.use_auto_normalize = self.mode == "INTERACTIVE"
        names = [m.name for m in meshes]
        results.result(self, f"setAttr {', '.join(names)} normalizeWeights {MAYA_VALUE[self.mode]}")
        return {'FINISHED'}
