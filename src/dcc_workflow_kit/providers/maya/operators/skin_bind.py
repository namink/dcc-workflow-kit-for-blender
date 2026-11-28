# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Bind Skin and Unbind Skin: closest-distance weights (or closest in hierarchy / heat map), binding in the
current pose (``unpose_mesh``), skinCluster names, the second-skin question, detaching with Delete / Keep / Bake
history; also Reset Default Weights and Move Skinned Joints. Entry points ``bind_skin``, ``closest_distance_weights``,
``joint_segments``, ``unbind``, ``move_skinned_joints``. Related: skin_basics.py, skin_follow.py, skin_influences.py.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from .. import results
from .skin_cluster import (NORMALIZE, NORMALIZE_PROP, PAINT_SEEN, _cb, armature_modifier, colorize, influences,
                           show_pose_in_components, skinned_mesh)


# --- Bind / Unbind Skin -------------------------------------------------------------------------

# Maya Bind Skin "Bind method". Closest distance is the default method (like Maya): weight of joint i on a vertex is
# distance(world vertex, joint i's segments) ** -dropoff, the segments run from the joint to each child joint (an end
# joint is a point), dropoff = skinCluster dropoffRate (default 4), the largest ``max influences`` kept, normalised.
# World space: an object's non-uniform scale doesn't matter (#94 - Blender's bone heat on a mesh with Scale Y 8 and
# one height subdivision left joint2 with no weights). Heat Map = Blender's automatic weights (bone heat).
BIND_METHODS = (("CLOSEST_DISTANCE", "Closest distance", "Default bind (like Maya): weights fall off with the distance to "
                 "each joint"),
                ("CLOSEST_HIERARCHY", "Closest in hierarchy", "Only the joints next to the closest one in the "
                 "skeleton (and the end joints) take weight"),
                ("HEAT_MAP", "Heat Map", "Blender's automatic weights (bone heat)"))
DROPOFF = 4.0
# Maya treats a vertex within 1e-4 of joints as on them: those share it equally
# (the kit used 1e-9 before)
ON_JOINT = 1e-4
SKINNING = (("CLASSIC_LINEAR", "Classic linear", "Weights blend the joint matrices (the default, like Maya)"),
            ("DUAL_QUATERNION", "Dual quaternion", "Volume-preserving blend (Blender Preserve Volume)"),
            ("WEIGHT_BLENDED", "Weight blended", "Per vertex mix of linear and dual quaternion by the blendWeights "
             "vertex group (0 = linear until painted)"))


def joint_segments(arm, bones=None, bound_children=False):
    """{bone name: [(a, b) world segment]}: Maya joint = the bone head, its segments go to each child joint (child
    bone head); a bone without children is an end joint (a point). ``bones`` limits which joints get weights.
    ``bound_children``: only segments to children in ``bones`` count (Bind to Selected joints, like Maya: a joint
    whose children are not bound is an end joint)."""
    mw = arm.matrix_world
    out = {}
    for bone in arm.data.bones:
        if not bone.use_deform or (bones is not None and bone.name not in bones):
            continue
        a = mw @ bone.head_local
        kids = [c for c in bone.children if not bound_children or bones is None or c.name in bones]
        out[bone.name] = [(a, mw @ c.head_local) for c in kids] or [(a, a)]
    return out


def closest_distance_weights(points, segments, dropoff=DROPOFF, max_influences=5, hierarchy=None):
    """(names, weights (V, J)) for world ``points`` (V, 3) - the Maya closest-distance rule above. ``hierarchy`` =
    {name: (parent name or None, [child names])} turns on Maya's Closest in hierarchy (``hierarchy_candidates``)."""
    import numpy as np
    names = list(segments)
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    dist = np.full((len(pts), len(names)), np.inf)
    for j, name in enumerate(names):
        for a, b in segments[name]:
            a = np.asarray(a, dtype=np.float64)
            ab = np.asarray(b, dtype=np.float64) - a
            ll = float(ab @ ab)
            t = np.clip((pts - a) @ ab / ll, 0.0, 1.0)[:, None] if ll > 0.0 else 0.0
            dist[:, j] = np.minimum(dist[:, j], np.linalg.norm(pts - (a + t * ab), axis=1))
    if hierarchy is not None:
        dist = np.where(hierarchy_candidates(dist, names, hierarchy, max_influences), dist, np.inf)
    on = dist <= ON_JOINT
    with np.errstate(divide='ignore'):
        w = np.where(on.any(axis=1)[:, None], on.astype(np.float64), dist ** -float(dropoff))
    w = np.where(np.isfinite(w), w, 0.0)
    if 0 < max_influences < len(names):
        cut = np.argsort(-w, axis=1)[:, max_influences:]
        np.put_along_axis(w, cut, 0.0, axis=1)
    total = w.sum(axis=1, keepdims=True)
    return names, np.divide(w, total, out=np.zeros_like(w), where=total > 0)


def hierarchy_candidates(dist, names, hierarchy, max_influences):
    """Maya Closest in hierarchy: per vertex the
    closest joint *with children*; candidates = its breadth-first list (each listed joint's children, then its parent,
    at most ``max_influences`` joints) plus every end joint. (V, J) bool mask."""
    import numpy as np
    col = {n: j for j, n in enumerate(names)}
    kids = {n: [c for c in hierarchy[n][1] if c in col] for n in names}
    par = {n: hierarchy[n][0] if hierarchy[n][0] in col else None for n in names}
    ends = np.array([not kids[n] for n in names])
    inner = [j for j, n in enumerate(names) if kids[n]]
    mask = np.tile(ends, (len(dist), 1))
    if not inner:
        return np.ones_like(mask)
    cache = {}
    for i, j in enumerate(np.asarray(inner)[np.argmin(dist[:, inner], axis=1)]):
        lst = cache.get(j)
        if lst is None:
            lst, k = [names[j]], 0
            while k < len(lst) and len(lst) < max_influences:
                for c in kids[lst[k]]:
                    if c not in lst and len(lst) < max_influences:
                        lst.append(c)
                p = par[lst[k]]
                if len(lst) < max_influences and p is not None and p not in lst:
                    lst.append(p)
                k += 1
            lst = cache[j] = [col[n] for n in lst]
        mask[i, lst] = True
    return mask


def joint_hierarchy(arm, names):
    bones = arm.data.bones
    return {n: (bones[n].parent.name if bones[n].parent is not None else None, [c.name for c in bones[n].children])
            for n in names}


def _bind_closest(arm, mesh, bones, max_influences, dropoff=DROPOFF, hierarchy=False):
    import numpy as np
    me = mesh.data
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    mw = np.array(mesh.matrix_world)
    pts = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
    segs = joint_segments(arm, bones, bound_children=True)
    names, w = closest_distance_weights(pts, segs, dropoff, max_influences,
                                        joint_hierarchy(arm, list(segs)) if hierarchy else None)
    every = list(range(len(me.vertices)))
    for j, name in enumerate(names):
        vg = mesh.vertex_groups.get(name) or mesh.vertex_groups.new(name=name)
        vg.remove(every)
        for value in np.unique(w[:, j]):
            if value > 0.0:
                vg.add(np.flatnonzero(w[:, j] == value).tolist(), float(value), 'REPLACE')
    md = armature_modifier(mesh)
    if md is None:
        md = mesh.modifiers.new("Armature", 'ARMATURE')   # same stack place as Blender's parenting (deformers first)
    md.object = arm
    md.use_vertex_groups = True


def name_skin_cluster(mesh):
    """Maya names each bind's deformer skinCluster1, skinCluster2 ... scene-wide (two binds give skinCluster1 /
    skinCluster2, #97): a skin modifier with Blender's automatic name gets the next free number."""
    md = armature_modifier(mesh)
    if md is None or md.name.startswith("skinCluster"):
        return md
    import re
    used = {int(m.group(1)) for ob in bpy.data.objects for mod in getattr(ob, "modifiers", ())
            for m in [re.fullmatch(r"skinCluster(\d+)", mod.name)] if m}
    n = 1
    while n in used:
        n += 1
    md.name = f"skinCluster{n}"
    return md


def bind_skin(context, arm, meshes, max_influences=5, only_bones=None, normalize="INTERACTIVE",
              remove_unused=True, colorize_skeleton=True, method="CLOSEST_DISTANCE", dropoff=DROPOFF,
              skinning="CLASSIC_LINEAR", maintain_max=True):
    """Smooth bind (Maya skinCluster): the meshes stay where they are in the hierarchy. Also stores Maya's bind pose
    (Go to Bind Pose), maxInfluences / maintainMaxInfluences / dropoffRate on the mesh."""
    for mesh in meshes:
        mesh.pop(PAINT_SEEN, None)          # a new skin: Paint Skin Weights starts on its first influence
    if context.active_object is not None and context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    if method == "HEAT_MAP":
        for ob in context.selected_objects:
            ob.select_set(False)
        for ob in (*meshes, arm):
            ob.select_set(True)
        context.view_layer.objects.active = arm
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
        arm.select_set(False)
        context.view_layer.objects.active = meshes[-1]
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')   # Maya doesn't parent the skin to the joints
    else:
        for mesh in meshes:
            _bind_closest(arm, mesh, only_bones, max_influences, dropoff, method == "CLOSEST_HIERARCHY")
    for mesh in meshes:
        name_skin_cluster(mesh)
    bones = {b.name for b in arm.data.bones}
    for mesh in meshes:
        if only_bones:
            for vg in list(mesh.vertex_groups):
                if vg.name in bones and vg.name not in only_bones:
                    mesh.vertex_groups.remove(vg)
        context.view_layer.objects.active = mesh
        if method == "HEAT_MAP" and mesh.vertex_groups:
            bpy.ops.object.vertex_group_limit_total(group_select_mode='ALL', limit=max_influences)
            bpy.ops.object.vertex_group_normalize_all(group_select_mode='ALL', lock_active=False)
        if remove_unused:
            from .rig_maya import unused_influences
            for name in unused_influences(mesh):
                mesh.vertex_groups.remove(mesh.vertex_groups[name])
        mesh[NORMALIZE_PROP] = normalize
        from . import rig_maya, skin_basics
        mesh[rig_maya.MAX_INFLUENCES_PROP] = int(max_influences)
        mesh[skin_basics.MAINTAIN_MAX] = bool(maintain_max)
        if float(dropoff) != DROPOFF:
            mesh[rig_maya.DROPOFF_PROP] = {vg.name: float(dropoff) for vg in influences(mesh)}
        from . import skin_method
        skin_method.set_method(mesh, skinning)       # Classic linear / Dual quaternion / Weight blended
        show_pose_in_components(mesh)
    context.view_layer.update()
    for mesh in meshes:
        unpose_mesh(arm, mesh)
    from . import skin_basics, skin_follow
    skin_basics.store_bind_pose(arm)
    for mesh in meshes:
        skin_follow.attach(mesh, arm)       # the skin moves with the skeleton object / a group above it (Maya)
    if colorize_skeleton:
        colorize(arm)
    arm.select_set(True)
    return meshes


def unpose_mesh(arm, mesh):
    """Maya binds in the current pose: a chain posed by hand or bent by an IK handle / pole vector must not move the
    mesh. Blender deforms from the rest pose, so each vertex gets the base position that the current pose deforms back
    to where it is (the inverse of its weighted bone matrix, Blender's linear blend). Returns how many vertices moved
    (0 when the skeleton is at rest)."""
    from mathutils import Matrix
    bones = {}
    for pb in arm.pose.bones:
        if not pb.bone.use_deform:
            continue
        m = pb.matrix @ pb.bone.matrix_local.inverted()
        bones[pb.name] = m
    if not bones or all(_near_identity(m) for m in bones.values()):
        return 0
    me = mesh.data
    if me.shape_keys is not None or not me.vertices:
        return 0
    to_arm = arm.matrix_world.inverted() @ mesh.matrix_world
    from_arm = to_arm.inverted()
    names = {vg.index: vg.name for vg in mesh.vertex_groups}
    moved = 0
    for v in me.vertices:
        total, blend = 0.0, Matrix(((0.0,) * 4,) * 4)
        for g in v.groups:
            m = bones.get(names.get(g.group))
            if m is None or g.weight <= 0.0:
                continue
            blend += m * g.weight
            total += g.weight
        if total <= 0.0:
            continue
        blend = from_arm @ (blend * (1.0 / total)) @ to_arm
        try:
            v.co = blend.inverted() @ v.co
        except ValueError:
            continue
        moved += 1
    me.update()
    return moved


def _near_identity(m, eps=1e-6):
    from mathutils import Matrix
    ident = Matrix.Identity(4)
    return all(abs(m[i][j] - ident[i][j]) < eps for i in range(4) for j in range(4))


QUESTION = {"mesh": None}                 # the last mesh the second-skin question was asked for (tests)
SECOND_SKIN_NOTE = ("Blender keeps one skin per mesh here: FBX and game engines read one. To add joints to this "
                    "skin use Skin > Edit Influences > Add Influence; a second Armature modifier can be added by "
                    "hand in Properties > Modifiers.")


def question_text(name):
    """Maya's Bind Skin question."""
    return f"There is already a skin cluster on {name}.\nDo you want to create another?"


class ALLSET_OT_skin_cluster_question(bpy.types.Operator):
    """Maya Bind Skin Options question for a mesh that already has a skin"""
    bl_idname = "allset.skin_cluster_question"
    bl_label = "Bind Skin Options"
    bl_options = {'INTERNAL'}

    mesh: StringProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Bind Skin Options")
        for line in question_text(self.mesh).split("\n"):
            layout.label(text=line, icon='QUESTION' if line.startswith("There") else 'NONE')
        row = layout.row(align=True)
        yes = row.row(align=True)
        yes.enabled = False
        yes.operator("allset.skin_cluster_answer", text="Yes")
        row.operator("allset.skin_cluster_answer", text="No")
        from ..ui import chrome
        box = layout.box()
        chrome.paragraph(box, context, SECOND_SKIN_NOTE, width=400)

    def execute(self, context):
        return {'FINISHED'}


class ALLSET_OT_skin_cluster_answer(bpy.types.Operator):
    """No: leave the mesh with its one skin"""
    bl_idname = "allset.skin_cluster_answer"
    bl_label = "No"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'FINISHED'}


class ALLSET_OT_bind_skin(bpy.types.Operator):
    """Maya Bind Skin: the selected skeleton and meshes, in any order (closest distance weights, no parenting)"""
    bl_idname = "allset.bind_skin"
    bl_label = "Bind Skin"
    bl_options = {'REGISTER', 'UNDO'}

    bind_to: EnumProperty(name="Bind To", items=(("HIERARCHY", "Joint Hierarchy", "Every joint of the skeleton"),
                                                 ("SELECTED", "Selected Joints", "Only the joints selected in "
                                                  "pose mode")), default="HIERARCHY")
    bind_method: EnumProperty(name="Bind method", items=BIND_METHODS, default="CLOSEST_DISTANCE")
    skinning: EnumProperty(name="Skinning method", items=SKINNING, default="CLASSIC_LINEAR")
    max_influences: IntProperty(name="Max Influences", default=5, min=1, max=30)
    # Bind Skin Options defaults (Maintain max influences on, dropoff 4.0, slider 0.1-10)
    maintain_max: BoolProperty(name="Maintain max influences", default=True)
    dropoff: FloatProperty(name="Dropoff rate", default=DROPOFF, min=0.1, max=100.0, soft_max=10.0, precision=1)
    normalize: EnumProperty(name="Normalize weights", items=NORMALIZE, default="INTERACTIVE")
    remove_unused: BoolProperty(name="Remove unused influences", default=True)
    colorize: BoolProperty(name="Colorize skeleton", default=True)

    def execute(self, context):
        cb = _cb()
        arm = cb.pose_armature(context)
        picked = [pb.name for pb in arm.pose.bones if cb.bone_selected(pb)] if arm is not None else []
        sel = list(context.selected_objects)
        if arm is None:
            arm = next((o for o in sel if o.type == 'ARMATURE'), None)
            if arm is not None and arm.mode == 'EDIT':
                # an unskinned skeleton's joints are picked in Edit mode
                picked = [eb.name for eb in arm.data.edit_bones if eb.select]
        meshes = [o for o in sel if o.type == 'MESH']
        if not sel and not picked:
            from .maya_errors import SELECT_TO_BIND        # Maya 2026
            self.report({'ERROR'}, SELECT_TO_BIND)
            return {'CANCELLED'}
        if arm is None:
            # Maya: no joint in the selection (only an IK handle / a curve ...) is an Error
            from .maya_errors import MUST_SELECT_JOINT
            self.report({'ERROR'}, MUST_SELECT_JOINT)
            return {'CANCELLED'}
        if not meshes:
            from .maya_errors import BINDABLE_IN_SELECTION   # Maya: an Error, joints only
            self.report({'ERROR'}, BINDABLE_IN_SELECTION)
            return {'CANCELLED'}
        skinned = [m for m in meshes if armature_modifier(m) is not None]
        if skinned:
            # Maya 2024+ asks before a second skinCluster; the kit
            # keeps one skin per mesh — the question with Yes greyed and the Blender way
            QUESTION["mesh"] = skinned[0].name
            if context.window is not None:
                bpy.ops.allset.skin_cluster_question('INVOKE_DEFAULT', mesh=skinned[0].name)
            self.report({'WARNING'}, question_text(skinned[0].name).replace("\n", " "))
            return {'CANCELLED'}
        only = set(picked) if self.bind_to == "SELECTED" and picked else None
        bind_skin(context, arm, meshes, self.max_influences, only, self.normalize, self.remove_unused, self.colorize,
                  self.bind_method, self.dropoff, self.skinning, self.maintain_max)
        results.result(self, f"Bound {len(meshes)} mesh(es) to {arm.name}")
        return {'FINISHED'}


# Maya Detach Skin Options: History Delete history (default) / Keep history /
# Bake history, Coloring: Remove joint colors on.
UNBIND_HISTORY = (("DELETE", "Delete history", "Remove the skin and the joints' weights"),
                  ("KEEP", "Keep history", "Remove the skin, keep the joints' weights (vertex groups)"),
                  ("BAKE", "Bake history", "Keep the current deformed shape as the mesh, then remove the skin"))


def unbind(context, mesh, history="DELETE"):
    """Detach one mesh's skin (Armature modifiers); returns the skeletons it was bound to."""
    arms = []
    for mod in [m for m in mesh.modifiers if m.type == 'ARMATURE']:
        arm = mod.object
        if arm is not None and arm not in arms:
            arms.append(arm)
        if history == "BAKE" and arm is not None:
            with context.temp_override(object=mesh, active_object=mesh):
                bpy.ops.object.modifier_apply(modifier=mod.name)
        else:
            mesh.modifiers.remove(mod)
        if history != "KEEP" and arm is not None:
            bones = {b.name for b in arm.data.bones}
            from .skin_method import BLEND_GROUP      # the skinCluster's blendWeights go with it
            for vg in [g for g in mesh.vertex_groups if g.name in bones or g.name == BLEND_GROUP]:
                mesh.vertex_groups.remove(vg)
    if NORMALIZE_PROP in mesh:
        del mesh[NORMALIZE_PROP]
    from . import skin_basics, skin_follow
    skin_follow.detach(mesh, keep_shape=history == "BAKE")
    for arm in arms:
        skin_basics.forget_bind_pose(arm)
    return arms


class ALLSET_OT_unbind_skin(bpy.types.Operator):
    """Maya Unbind Skin: remove the Armature modifier (and, by default, the joint weight groups)"""
    bl_idname = "allset.unbind_skin"
    bl_label = "Unbind Skin"
    bl_options = {'REGISTER', 'UNDO'}

    history: EnumProperty(name="History", items=UNBIND_HISTORY, default="DELETE")
    remove_colors: BoolProperty(name="Remove joint colors", default=True)

    def execute(self, context):
        meshes = [o for o in context.selected_objects if o.type == 'MESH' and armature_modifier(o)]
        if meshes and context.active_object is not None and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        arms = []
        for mesh in meshes:
            arms += [a for a in unbind(context, mesh, self.history) if a not in arms]
        if self.remove_colors:
            for arm in arms:
                still = any(m.object == arm for o in bpy.data.objects if o.type == 'MESH'
                            for m in o.modifiers if m.type == 'ARMATURE')
                if not still:          # Maya removes the colours of joints no skin uses any more
                    colorize(arm, False)
        results.result(self, f"Unbound {len(meshes)} skin(s)")
        return {'FINISHED'} if meshes else {'CANCELLED'}


class ALLSET_OT_reset_skin_weights(bpy.types.Operator):
    """Maya Reset Default Weights: give the skinned mesh its bind weights again (closest distance, the joints it is
    bound to, at most as many influences as each vertex has now, at least 5)"""
    bl_idname = "allset.reset_skin_weights"
    bl_label = "Reset Default Weights"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mesh = skinned_mesh(context)
        if mesh is None:
            self.report({'WARNING'}, "Select a skinned mesh")
            return {'CANCELLED'}
        mode = mesh.mode
        if mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')
        md = armature_modifier(mesh)
        bones = {vg.name for vg in mesh.vertex_groups if md.object.data.bones.get(vg.name) is not None}
        most = max((sum(1 for g in v.groups if g.weight > 0) for v in mesh.data.vertices), default=0)
        _bind_closest(md.object, mesh, bones or None, max(5, most))
        mesh.data.update()
        if mode == 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}

class ALLSET_OT_move_skinned_joints(bpy.types.Operator):
    """Maya Skin > Move Skinned Joints: reposition the joints of a skinned skeleton without deforming the mesh (the
    new place becomes the bind). Run it again, press F8 or pick another tool mode to go back to posing"""
    bl_idname = "allset.move_skinned_joints"
    bl_label = "Move Skinned Joints"
    bl_options = {'UNDO'}

    def execute(self, context):
        from . import joint_selection
        ob = context.active_object
        if ob is not None and ob.type == 'MESH':
            md = armature_modifier(ob)
            ob = md.object if md is not None else None
        if ob is None or ob.type != 'ARMATURE' or not joint_selection.is_skinned(ob):
            self.report({'WARNING'}, "Select a skinned skeleton or a skinned mesh")   # Maya: "No skinned joints"
            return {'CANCELLED'}
        if not ob.visible_get():
            self.report({'WARNING'}, f"{ob.name} is hidden: show the skeleton first")
            return {'CANCELLED'}
        # Like choosing Maya's tool again: on unless its joints are being edited now (then off = Pose); a click
        # elsewhere left Edit Mode with the tool still on, and running it again goes back to editing the joints.
        on = move_skinned_joints(context, ob, not (ob.get(joint_selection.MOVE_SKINNED) and ob.mode == 'EDIT'))
        results.result(self, "Move Skinned Joints " + ("on: move the joints, run it again to pose" if on else "off"))
        return {'FINISHED'}


def move_skinned_joints(context, arm, on):
    """Maya moveJointsMode: on = the skeleton in Edit mode, its picked joints
    kept; off = back to Pose mode. The Armature modifier deforms by pose x rest^-1, so moving the rest at the rest
    pose leaves the mesh where it is and the new rest is the bind (Maya rewrites bindPreMatrix)."""
    from . import joint_selection
    picked = [pb.name for pb in arm.pose.bones if _cb().bone_selected(pb)] if arm.mode == 'POSE' else []
    if context.active_object is not None and context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for ob in context.selected_objects:
        if ob != arm:
            ob.select_set(False)
    arm.select_set(True)
    context.view_layer.objects.active = arm
    if on:
        arm[joint_selection.MOVE_SKINNED] = True
        bpy.ops.object.mode_set(mode='EDIT')
        for eb in arm.data.edit_bones:
            eb.select = eb.select_head = eb.select_tail = False
        for i, name in enumerate(picked):
            joint_selection.select_edit(context, arm, name, shift=i > 0)
        if not picked:
            joint_selection.select_roots_if_empty(arm)
    else:
        arm.pop(joint_selection.MOVE_SKINNED, None)
        bpy.ops.object.mode_set(mode='POSE')
        joint_selection.select_roots_if_empty(arm)
    return on
