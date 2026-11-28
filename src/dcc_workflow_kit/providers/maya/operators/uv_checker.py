# SPDX-License-Identifier: GPL-3.0-or-later
"""UV checker: Maya UV > Assign Checker Shader and the UV Editor checker button with its density.

``allset.checker_shader`` assigns a lambert with the checker grid image; ``allset.checker_toggle`` shows / hides a
checker material on the objects' slots at object level (``checker_show`` / ``checker_hide``); ``checker_on`` tells the
UV Editor icon row (ui/editor_icon_row) whether it shows; ``allset.checker_density`` / ``set_checker_density`` set the
density. menu_items re-exports them.
"""

import bpy
from bpy.props import IntProperty

from .. import results
from .. import undo_steps


# --- UV > Assign Checker Shader ---------------------------------------------------------------

CHECKER_IMAGE = "uvChecker"


class ALLSET_OT_checker_shader(bpy.types.Operator):
    """Give the selected objects (or faces) a UV checker material (Maya UV > Assign Checker Shader)"""
    bl_idname = "allset.checker_shader"
    bl_label = "Assign Checker Shader"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from . import material
        obs = [ob for ob in (context.objects_in_mode or context.selected_objects) if ob.type == 'MESH']
        if not obs:
            self.report({'WARNING'}, "Select objects or faces to assign the checker to")
            return {'CANCELLED'}
        img = bpy.data.images.get(CHECKER_IMAGE) or bpy.data.images.new(CHECKER_IMAGE, 1024, 1024)
        img.generated_type = 'UV_GRID'
        mat = material.new_material()
        tree = mat.node_tree
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = img
        node.location = (-570, 300)
        tree.links.new(node.outputs["Color"], material.color_socket(mat))
        material.assign(context, mat, obs)
        return {'FINISHED'}


# --- UV Editor checker button / Textures > Checker Map (a display toggle, #13) -------------------------------
# Maya: the UV Editor checker button shows / hides a checker map on the objects
# (a check button). Blender has no display-only override, so the kit
# puts a checker material on the objects' slots at object level (``link = 'OBJECT'``: the mesh's own materials are
# untouched) and remembers what was there in the object property CHECKER_PREV; off puts it back.

CHECKER_PREV = "allset_checker_prev"
CHECKER_MAT = "allset_checker_display"


def checker_objects(scene):
    return [ob for ob in scene.objects if CHECKER_PREV in ob]


def checker_on(context):
    return bool(checker_objects(context.scene))


def _checker_material():
    from . import material
    mat = next((m for m in bpy.data.materials if m.get(CHECKER_MAT)), None)
    if mat is not None:
        return mat
    img = bpy.data.images.get(CHECKER_IMAGE) or bpy.data.images.new(CHECKER_IMAGE, 1024, 1024)
    img.generated_type = 'UV_GRID'
    mat = material.new_material()
    mat.name = "checkerDisplay"
    mat[CHECKER_MAT] = True
    tree = mat.node_tree
    node = tree.nodes.new("ShaderNodeTexImage")
    node.image = img
    node.location = (-570, 300)
    tree.nodes.active = node
    tree.links.new(node.outputs["Color"], material.color_socket(mat))
    _density_node(mat)
    return mat


# Checker density (Maya UV Editor Ctrl+Up / Ctrl+Down): a whole number from 1, one step per key; the checker
# repeats that many times per UV unit (a Mapping node scale in front of the checker image).
CHECKER_DENSITY = "allset_checker_density"
DENSITY_NODE = "Checker Density"


def _density_node(mat):
    tree = mat.node_tree
    node = tree.nodes.get(DENSITY_NODE)
    if node is not None:
        return node
    tex = next((n for n in tree.nodes if n.type == 'TEX_IMAGE'), None)
    if tex is None:
        return None
    coord = tree.nodes.new("ShaderNodeTexCoord")
    coord.location = tex.location.x - 420, tex.location.y
    node = tree.nodes.new("ShaderNodeMapping")
    node.name = node.label = DENSITY_NODE
    node.location = tex.location.x - 220, tex.location.y
    tree.links.new(coord.outputs["UV"], node.inputs["Vector"])
    tree.links.new(node.outputs["Vector"], tex.inputs["Vector"])
    d = checker_density(mat)
    node.inputs["Scale"].default_value = (d, d, 1.0)
    return node


def checker_density(mat=None):
    if mat is None:
        mat = next((m for m in bpy.data.materials if m.get(CHECKER_MAT)), None)
    return max(1, int(mat.get(CHECKER_DENSITY, 1))) if mat is not None else 1


def set_checker_density(density):
    """Set the checker density (at least 1) on the checker display material; returns the new value."""
    mat = _checker_material()
    d = max(1, int(density))
    mat[CHECKER_DENSITY] = d
    node = _density_node(mat)
    if node is not None:
        node.inputs["Scale"].default_value = (d, d, 1.0)
    return d


def checker_show(obs):
    import json
    mat = _checker_material()
    for ob in obs:
        if CHECKER_PREV in ob:
            continue
        added = not ob.material_slots
        if added:
            ob.data.materials.append(None)
        prev = [(s.link, s.material.name if s.link == 'OBJECT' and s.material else "") for s in ob.material_slots]
        ob[CHECKER_PREV] = json.dumps({"slots": prev, "added": added})
        for slot in ob.material_slots:
            slot.link = 'OBJECT'
            slot.material = mat


def checker_hide(obs):
    import json
    for ob in obs:
        raw = ob.get(CHECKER_PREV)
        if raw is None:
            continue
        data = json.loads(raw)
        for slot, (link, name) in zip(ob.material_slots, data["slots"]):
            slot.link = 'OBJECT'
            slot.material = bpy.data.materials.get(name) if name else None
            slot.link = link
        if data.get("added") and ob.type == 'MESH' and len(ob.data.materials) == 1 and ob.data.materials[0] is None:
            ob.data.materials.clear()
        del ob[CHECKER_PREV]


class ALLSET_OT_checker_toggle(bpy.types.Operator):
    """Show or hide a checker map on the selected objects (Maya UV Editor checker button); a second click puts the
    objects' own materials back"""
    bl_idname = "allset.checker_toggle"
    bl_label = "Checker Map"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        shown = checker_objects(context.scene)
        if shown:
            checker_hide(shown)
            return {'FINISHED'}
        obs = [ob for ob in (context.objects_in_mode or context.selected_objects) if ob.type == 'MESH']
        if not obs:
            self.report({'WARNING'}, "Select objects or faces to show the checker on")
            return {'CANCELLED'}
        checker_show(obs)
        return {'FINISHED'}


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_checker_density(bpy.types.Operator):
    """Make the UV checker finer or coarser (Maya UV Editor Increase / Decrease Checker Density)"""
    bl_idname = "allset.checker_density"
    bl_label = "Checker Density"
    bl_options = {'REGISTER', 'UNDO'}

    step: IntProperty(name="Step", default=1, options={'SKIP_SAVE'})

    def execute(self, context):
        d = set_checker_density(checker_density() + self.step)
        results.result(self, f"Checker density {d}")
        return {'FINISHED'}
