# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Copy Skin Weights (Data Transfer, then each source joint moved onto its associated destination joint), Mirror
Skin Weights (weights at the closest point of the mirrored surface, joints paired by position or label) and Copy /
Paste Vertex Weights (one vertex's joint weights on a clipboard). Entry points ``associate``, ``mirror_group_names``,
``mirror_weights``, ``surface_weights``. Related: skin_basics.py (weight arrays), joint_labels.py (labels).
"""

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty
from mathutils import Vector

from .. import results
from .skin_cluster import armature_modifier, influences, skinned_mesh


# --- Copy / Mirror Skin Weights, Copy / Paste Vertex Weights -----------------------------------------

# Maya Copy Skin Weights Options: Surface Association -> Blender Data Transfer
# vertex mapping; Influence Association 1-3 = how a source joint finds its destination joint when the two meshes use
# different skeletons (tried in order; one skeleton = every joint is itself).
SURFACE_ASSOCIATION = (("CLOSEST_POINT", "Closest point on surface", "Interpolated from the nearest face"),
                       ("RAY_CAST", "Ray cast", "Along the vertex normal onto the source"),
                       ("CLOSEST_COMPONENT", "Closest component", "The nearest source vertex"))
VERT_MAPPING = {"CLOSEST_POINT": 'POLYINTERP_NEAREST', "RAY_CAST": 'POLYINTERP_VNORPROJ', "CLOSEST_COMPONENT": 'NEAREST'}
INFLUENCE_ASSOCIATION = (("CLOSEST_JOINT", "Closest joint", "The destination joint nearest the source joint"),
                         ("CLOSEST_BONE", "Closest bone", "The destination bone nearest the source joint's bone"),
                         ("ONE_TO_ONE", "One to one", "The joint at the same place in the hierarchy"),
                         ("NAME", "Name", "The joint with the same name"),
                         ("NONE", "None", "No further association"))


def _hierarchy_order(arm):
    out = []

    def walk(bone):
        out.append(bone.name)
        for child in bone.children:
            walk(child)
    for root in [b for b in arm.data.bones if b.parent is None]:
        walk(root)
    return out


def _segment_distance(p, a, b):
    ab = b - a
    t = 0.0 if ab.length_squared < 1e-12 else max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (p - (a + ab * t)).length


def associate(src_arm, dst_arm, name, modes=("CLOSEST_JOINT",)):
    """The destination joint for source joint ``name`` (Maya influence association), or None."""
    if src_arm == dst_arm:
        return name if name in dst_arm.data.bones else None
    bone = src_arm.data.bones.get(name)
    if bone is None:
        return None
    head = src_arm.matrix_world @ bone.head_local
    dst = dst_arm.data.bones
    for mode in modes:
        if mode == "NAME" and name in dst:
            return name
        if mode == "ONE_TO_ONE":
            order, other = _hierarchy_order(src_arm), _hierarchy_order(dst_arm)
            i = order.index(name)
            if i < len(other):
                return other[i]
        if mode == "CLOSEST_JOINT" and len(dst):
            return min(dst, key=lambda b: (dst_arm.matrix_world @ b.head_local - head).length).name
        if mode == "CLOSEST_BONE" and len(dst):
            return _closest_bone(src_arm, bone, dst_arm)
    return None


def _bones_of(arm):
    """(joint name, start, end) of every bone of a skeleton, Maya's way: the segment from a joint to each child joint
    (an end joint has none), in hierarchy order, world space."""
    mw = arm.matrix_world
    out = []
    for name in _hierarchy_order(arm):
        b = arm.data.bones[name]
        out += [(name, mw @ b.head_local, mw @ c.head_local) for c in b.children]
    return out


def _closest_bone(src_arm, bone, dst_arm):
    """Closest bone (#462): the source joint's place = the middle of its bone (an end joint: the joint itself); its
    weights go to the destination joint whose bone lies nearest that place (a tie: the first in the hierarchy)."""
    mw = src_arm.matrix_world
    head = mw @ bone.head_local
    points = [(head + mw @ c.head_local) / 2 for c in bone.children] or [head]
    segments = _bones_of(dst_arm)
    if not segments:                     # a destination of single joints: the joints themselves
        segments = [(b.name, dst_arm.matrix_world @ b.head_local, dst_arm.matrix_world @ b.head_local)
                    for b in dst_arm.data.bones]
    best, best_d = None, None
    for name, a, b in segments:
        d = min(_segment_distance(p, a, b) for p in points)
        if best_d is None or d < best_d - 1e-9:
            best, best_d = name, d
    return best


def remap_influences(mesh, src_arm, dst_arm, names, modes):
    """Move the copied weights of source joints ``names`` onto their associated destination joints."""
    if src_arm == dst_arm:
        return
    weights = {}
    for name in names:
        vg = mesh.vertex_groups.get(name)
        if vg is None:
            continue
        for v in mesh.data.vertices:
            for g in v.groups:
                if g.group == vg.index and g.weight > 0.0:
                    weights.setdefault(name, []).append((v.index, g.weight))
        mesh.vertex_groups.remove(vg)
    targets = {name: associate(src_arm, dst_arm, name, modes) for name in weights}
    if any(t is not None for t in targets.values()):
        # the copied weights replace the destination's own weights (like Maya; with no joint matched the
        # destination keeps its weights)
        every = [v.index for v in mesh.data.vertices]
        for vg in mesh.vertex_groups:
            if vg.name in dst_arm.data.bones:
                vg.remove(every)
    for name, pairs in weights.items():
        target = targets[name]
        if target is None:
            continue
        vg = mesh.vertex_groups.get(target) or mesh.vertex_groups.new(name=target)
        for i, w in pairs:
            vg.add([i], w, 'ADD')


class ALLSET_OT_copy_skin_weights(bpy.types.Operator):
    """Maya Copy Skin Weights: select the source mesh, then the destination"""
    bl_idname = "allset.copy_skin_weights"
    bl_label = "Copy Skin Weights"
    bl_options = {'REGISTER', 'UNDO'}

    surface: EnumProperty(name="Surface Association", items=SURFACE_ASSOCIATION, default="CLOSEST_POINT")
    influence1: EnumProperty(name="Influence Association 1", items=INFLUENCE_ASSOCIATION, default="CLOSEST_JOINT")
    influence2: EnumProperty(name="Influence Association 2", items=INFLUENCE_ASSOCIATION, default="NONE")
    influence3: EnumProperty(name="Influence Association 3", items=INFLUENCE_ASSOCIATION, default="NONE")
    normalize: BoolProperty(name="Normalize", default=False)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        dst = context.active_object
        srcs = [o for o in context.selected_objects if o is not dst and o.type == 'MESH' and armature_modifier(o)]
        if dst is None or dst.type != 'MESH' or not srcs:
            self.report({'WARNING'}, "Select the skinned source mesh, then the destination mesh")
            return {'CANCELLED'}
        src_arm = armature_modifier(srcs[0]).object
        if armature_modifier(dst) is None:
            mod = dst.modifiers.new("Armature", 'ARMATURE')
            mod.object = src_arm
        dst_arm = armature_modifier(dst).object
        src_names = [vg.name for vg in influences(srcs[0])]
        bpy.ops.object.data_transfer(use_reverse_transfer=True, data_type='VGROUP_WEIGHTS', use_create=True,
                                     vert_mapping=VERT_MAPPING[self.surface],
                                     # reverse transfer swaps the two layer enums
                                     layers_select_src='NAME', layers_select_dst='ALL')
        if dst_arm != src_arm:
            modes = [m for m in (self.influence1, self.influence2, self.influence3) if m != "NONE"]
            # the transfer wrote the weights under the source joints' names: move them to the associated joints
            remap_influences(dst, src_arm, dst_arm, src_names, modes)
        if self.normalize:
            from .rig_maya import normalize
            normalize(dst)
        results.result(self, f"Copied skin weights to {dst.name}")
        return {'FINISHED'}


# mirror plane (scene axes, like the Channel Box) -> the axis it flips
PLANE_AXIS = {"YZ": 0, "XZ": 1, "XY": 2}


def _reflect(v, axis):
    v = Vector(v)
    v[axis] = -v[axis]
    return v


# Maya Mirror Skin Weights Options: Influence Association 1 = Closest joint / One to one /
# Label (default Closest joint), 2 = None / the same (default None). One to one pairs a joint with itself inside one
# skeleton, so the kit offers Closest joint and Label.
MIRROR_INFLUENCE = (("CLOSEST_JOINT", "Closest joint", "The joint nearest the mirrored place of the joint"),
                    ("LABEL", "Label", "The joint with the same type label on the other side (Skeleton > Joint "
                     "Labelling): Left <-> Right"))
MIRROR_INFLUENCE_2 = (("NONE", "None", "No further association"),) + MIRROR_INFLUENCE


def _mirror_label_partner(arm, bone, reflected, labels):
    """Label association: the bone on the other side with the same type (Other: same other type); several = the one
    nearest the mirrored place (fingers of one type pair by place). Center / None side = the joint itself.
    None = no label to match."""
    side, typ, other, _d = labels.get_label(bone)
    if typ == labels.T_NONE:
        return None
    if side in (labels.CENTER, labels.NO_SIDE):
        return bone.name
    want = labels.RIGHT if side == labels.LEFT else labels.LEFT
    mw = arm.matrix_world
    cands = [b for b in arm.data.bones
             if labels.get_label(b)[:2] == (want, typ) and (typ != labels.T_OTHER or labels.get_label(b)[2] == other)]
    if not cands:
        return None
    return min(cands, key=lambda b: (mw @ b.head_local - reflected).length).name


def mirror_group_names(arm, axis, tol=1e-3, modes=("CLOSEST_JOINT",), unmatched=None):
    """Joint name -> its partner on the other side, by Maya influence association ``modes`` tried in order.

    Closest joint = the joint whose head is nearest the mirrored head (no tolerance, an unmirrored skeleton
    still pairs; a joint on the plane pairs with itself). Label = ``_mirror_label_partner``. A joint no mode pairs
    falls back to Closest joint and is added to ``unmatched`` (Maya warns "Not all influences could be matched")."""
    from . import joint_labels as labels
    mw = arm.matrix_world
    bones = list(arm.data.bones)
    heads = {b.name: mw @ b.head_local for b in bones}
    tails = {b.name: mw @ b.tail_local for b in bones}
    out = {}
    for b in bones:
        rh, rt = _reflect(heads[b.name], axis), _reflect(tails[b.name], axis)
        closest = min(bones, key=lambda o: ((heads[o.name] - rh).length, (tails[o.name] - rt).length)).name
        partner = None
        for mode in modes:
            if mode == "CLOSEST_JOINT":
                partner = closest
            elif mode == "LABEL":
                partner = _mirror_label_partner(arm, b, rh, labels)
            if partner is not None:
                break
        if partner is None:
            partner = closest
            if unmatched is not None:
                unmatched.append(b.name)
        out[b.name] = partner
    return out


def surface_weights(mesh, points, groups, w):
    """Weights at world ``points`` from the closest point on the mesh surface: the barycentric mix of that triangle's
    vertices (Maya Surface Association "Closest point on surface").
    ``w`` = (V, K) vertex weights of ``groups``. Returns (P, K)."""
    import numpy as np
    from mathutils import geometry
    from mathutils.bvhtree import BVHTree
    me = mesh.data
    me.calc_loop_triangles()
    mw = mesh.matrix_world
    co = [mw @ v.co for v in me.vertices]
    tris = [tuple(t.vertices) for t in me.loop_triangles]
    tree = BVHTree.FromPolygons(co, tris, all_triangles=True)
    out = np.zeros((len(points), len(groups)))
    for i, p in enumerate(points):
        hit, _n, t, _d = tree.find_nearest(p)
        if hit is None:
            continue
        a, b, c = tris[t]
        bary = geometry.barycentric_transform(hit, co[a], co[b], co[c], (1, 0, 0), (0, 1, 0), (0, 0, 1))
        out[i] = bary[0] * w[a] + bary[1] * w[b] + bary[2] * w[c]
    return out


def mirror_weights(mesh, axis=0, positive_to_negative=True, modes=("CLOSEST_JOINT",), unmatched=None, only=None,
                   normalize=False):
    """Copy the weights of one side onto the other (Maya Mirror Skin Weights, default Closest point on surface): each
    destination vertex takes the weights at the closest surface point to its mirror image (barycentric), every joint
    renamed to its mirror partner; vertices on the plane are left alone. ``only`` = Maya filterSelected: just these
    destination vertices are written (a selected source vertex writes nothing);
    ``normalize`` = the option's Normalize (default off). Count of vertices written."""
    import numpy as np
    from . import skin_basics
    mod = armature_modifier(mesh)
    pair = mirror_group_names(mod.object, axis, modes=modes, unmatched=unmatched) if mod and mod.object else {}
    groups = list(mesh.vertex_groups)
    if not groups:
        return 0
    mw = mesh.matrix_world
    verts = mesh.data.vertices
    world = [mw @ v.co for v in verts]
    eps = 1e-6
    dst = [i for i, p in enumerate(world) if (p[axis] < -eps if positive_to_negative else p[axis] > eps)]
    if only is not None:
        keep = {int(i) for i in only}
        dst = [i for i in dst if i in keep]
    if not dst:
        return 0
    w = skin_basics.weights(mesh, groups)                  # read before any write (faces across the plane)
    got = surface_weights(mesh, [_reflect(world[i], axis) for i in dst], groups, w)
    col = {g.name: j for j, g in enumerate(groups)}
    out = w.copy()
    out[dst] = 0.0
    for j, g in enumerate(groups):
        k = col.get(pair.get(g.name, g.name))
        if k is not None:
            out[dst, k] += got[:, j]
    out[np.abs(out) < 1e-12] = 0.0
    if normalize:
        infl = [j for j, g in enumerate(groups) if g.name in mod.object.data.bones] if mod and mod.object else []
        total = out[np.ix_(dst, infl)].sum(axis=1, keepdims=True)
        out[np.ix_(dst, infl)] = np.divide(out[np.ix_(dst, infl)], total, out=out[np.ix_(dst, infl)],
                                           where=total > 0)
    skin_basics.write(mesh, groups, out, dst)
    skin_basics.enforce_max(mesh)
    return len(dst)


class ALLSET_OT_mirror_skin_weights(bpy.types.Operator):
    """Maya Mirror Skin Weights: copy one side's weights onto the other, joints paired by position"""
    bl_idname = "allset.mirror_skin_weights"
    bl_label = "Mirror Skin Weights"
    bl_options = {'REGISTER', 'UNDO'}

    plane: EnumProperty(name="Mirror Across", items=[(k, k, "") for k in ("XY", "YZ", "XZ")], default="YZ")
    positive_to_negative: BoolProperty(name="Direction: Positive to Negative", default=True)
    influence1: EnumProperty(name="Influence Association 1", items=MIRROR_INFLUENCE, default="CLOSEST_JOINT")
    influence2: EnumProperty(name="Influence Association 2", items=MIRROR_INFLUENCE_2, default="NONE")
    # off by default (Mirror Skin Weights Options)
    normalize: BoolProperty(name="Normalize", default=False)

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'PAINT_WEIGHT', 'EDIT_MESH'}

    def execute(self, context):
        mesh = skinned_mesh(context)
        if mesh is None:
            self.report({'WARNING'}, "Select a skinned mesh")
            return {'CANCELLED'}
        modes = [m for m in (self.influence1, self.influence2) if m != "NONE"]
        unmatched = []
        from . import skin_basics
        rows = skin_basics.target_rows(mesh)             # Maya filterSelected: selected vertices, else all
        only = rows if len(rows) < len(mesh.data.vertices) else None
        with skin_basics._ObjectData(mesh):
            n = mirror_weights(mesh, PLANE_AXIS[self.plane], self.positive_to_negative, modes, unmatched, only,
                               self.normalize)
        if unmatched:
            self.report({'WARNING'}, "Not all influences could be matched up using the selected association "
                        "options. Weight transfer may be problematic near the unmatched influences.")
        else:
            results.result(self, f"Mirrored the weights of {n} vertices")
        return {'FINISHED'}


_VERTEX_CLIPBOARD = {}


def _edit_bmesh(context):
    ob = context.edit_object
    if ob is None or ob.type != 'MESH':
        return None, None, None
    bm = bmesh.from_edit_mesh(ob.data)
    return ob, bm, bm.verts.layers.deform.verify()


class ALLSET_OT_copy_vertex_weights(bpy.types.Operator):
    """Maya Copy Vertex Weights: remember the active vertex's joint weights"""
    bl_idname = "allset.copy_vertex_weights"
    bl_label = "Copy Vertex Weights"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        ob, bm, layer = _edit_bmesh(context)
        act = bm.select_history.active
        if not isinstance(act, bmesh.types.BMVert):
            act = next((v for v in bm.verts if v.select), None)
        if act is None:
            self.report({'WARNING'}, "Select a vertex")
            return {'CANCELLED'}
        names = {vg.index: vg.name for vg in ob.vertex_groups}
        _VERTEX_CLIPBOARD.clear()
        _VERTEX_CLIPBOARD.update({names[i]: w for i, w in act[layer].items() if i in names})
        results.result(self, f"Copied {len(_VERTEX_CLIPBOARD)} weight(s)")
        return {'FINISHED'}


class ALLSET_OT_paste_vertex_weights(bpy.types.Operator):
    """Maya Paste Vertex Weights: give the selected vertices the copied joint weights"""
    bl_idname = "allset.paste_vertex_weights"
    bl_label = "Paste Vertex Weights"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and bool(_VERTEX_CLIPBOARD)

    def execute(self, context):
        ob, bm, layer = _edit_bmesh(context)
        idx = {}
        for name in _VERTEX_CLIPBOARD:
            vg = ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
            idx[name] = vg.index
        n = 0
        for v in bm.verts:
            if v.select:
                dv = v[layer]
                dv.clear()
                for name, w in _VERTEX_CLIPBOARD.items():
                    dv[idx[name]] = w
                n += 1
        bmesh.update_edit_mesh(ob.data)
        results.result(self, f"Pasted weights on {n} vertices")
        return {'FINISHED'}
