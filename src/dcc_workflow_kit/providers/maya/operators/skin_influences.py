# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Skin > Edit Influences (Add / Remove Influence, Remove Unused Influences) and Hammer Skin Weights on a skinned
mesh (Armature modifier + one vertex group per joint); Add Influence recomputes the weights by distance like Bind Skin
(``maya_add_weights``) or, with Lock weights, gives the new joint a fixed weight. Entry points ``add_influence``,
``remove_influence``, ``unused_influences``, ``normalize``, ``hammer``; skin_basics / skin_bind read them via rig_maya.
"""

import bmesh
import bpy
from bpy.props import BoolProperty, FloatProperty

from .. import results


# --- Skin: influences, Hammer ----------------------------------------------------------------------

def _skin_armature(mesh):
    md = next((m for m in mesh.modifiers if m.type == 'ARMATURE' and m.object is not None), None)
    return md.object if md else None


def _skinned(context):
    return [o for o in context.selected_objects if o.type == 'MESH' and _skin_armature(o) is not None]


def _influence_groups(mesh):
    arm = _skin_armature(mesh)
    bones = set(arm.data.bones.keys()) if arm else set()
    return [g for g in mesh.vertex_groups if g.name in bones]


def normalize(mesh, groups=None):
    """Weights of each vertex over the influence groups sum to 1 (Maya normalizeWeights Interactive)."""
    idx = {g.index for g in (groups if groups is not None else _influence_groups(mesh))}
    for v in mesh.data.vertices:
        ws = [g for g in v.groups if g.group in idx]
        total = sum(g.weight for g in ws)
        if total > 1e-12:
            for g in ws:
                g.weight /= total


# Maya Add Influence without Lock weights: the skin's
# weights are recomputed by the closest-distance rule of Bind Skin (skin_bind.closest_distance_weights) over the old and
# the new influences, each with its own dropoff (old = the bind's, new = the option's Dropoff, default 4).
MAX_INFLUENCES_PROP = "allset_max_influences"   # Maya skinCluster maxInfluences (Bind Skin default 5)
DROPOFF_PROP = "allset_dropoff"                 # {influence: dropoff} of influences added with another dropoff
MAX_INFLUENCES = 5


def _joint_segments(arm, names):
    """{name: [(a, b) world segment]}: a joint's segments run to each child joint, an end joint is a point (the Bind
    Skin rule, skin_bind.joint_segments, without its deform filter: a joint added as influence counts whatever its flag)."""
    mw = arm.matrix_world
    out = {}
    for name in names:
        bone = arm.data.bones.get(name)
        if bone is not None:
            a = mw @ bone.head_local
            out[name] = [(a, mw @ c.head_local) for c in bone.children] or [(a, a)]
    return out


def maya_add_weights(points, before, segments, is_new, locked, dropoffs, max_influences):
    """Weights (V, K) after Maya's Add Influence for world ``points`` (V, 3); columns = influences in skinCluster order
    (old ones, then the new ones), ``before`` (V, K) = current weights (0 for new), ``segments`` a list of K segment
    lists, ``is_new`` / ``locked`` (K,) bools, ``dropoffs`` (K,). Per vertex, w_i = distance(vertex, influence i) **
    -dropoff_i (a vertex on influences = those share equally), and:
    - no locked influence, K <= max influences: every influence gets w_i / sum w (painted weights are discarded);
    - no locked influence, K > max influences: the max influences largest w (ties: skinCluster order) are kept, but
      only new influences and those with weight > 0 before receive weight;
    - locked influences keep their weights; the rest (1 - locked sum) goes to the n largest w of the unlocked ones,
      n = min(unlocked old influences with weight > 0, max influences - locked influences with weight > 0)."""
    import numpy as np
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    before = np.asarray(before, dtype=np.float64).reshape(len(pts), -1)
    is_new, locked = np.asarray(is_new, dtype=bool), np.asarray(locked, dtype=bool)
    k = len(segments)
    dist = np.full((len(pts), k), np.inf)
    for j, segs in enumerate(segments):
        for a, b in segs:
            a = np.asarray(a, dtype=np.float64)
            ab = np.asarray(b, dtype=np.float64) - a
            ll = float(ab @ ab)
            t = np.clip((pts - a) @ ab / ll, 0.0, 1.0)[:, None] if ll > 0.0 else 0.0
            dist[:, j] = np.minimum(dist[:, j], np.linalg.norm(pts - (a + t * ab), axis=1))
    on = dist <= 1e-4                     # Maya's on-joint distance
    with np.errstate(divide='ignore'):
        w = np.where(on.any(axis=1)[:, None], on.astype(np.float64), dist ** -np.asarray(dropoffs, dtype=np.float64))
    w = np.where(np.isfinite(w), w, 0.0)
    had = before > 0.0
    if locked.any():
        ranked = np.where(locked[None, :], -1.0, w)
        order = np.argsort(-ranked, axis=1, kind='stable')
        rank = np.empty_like(order)
        np.put_along_axis(rank, order, np.arange(k)[None, :].repeat(len(pts), axis=0), axis=1)
        slots = np.minimum((had & ~locked & ~is_new).sum(axis=1),
                           max_influences - (had & locked).sum(axis=1))
        rec = ~locked[None, :] & (rank < slots[:, None])
    elif k <= max_influences:
        rec = np.ones_like(had)
    else:
        order = np.argsort(-w, axis=1, kind='stable')
        rank = np.empty_like(order)
        np.put_along_axis(rank, order, np.arange(k)[None, :].repeat(len(pts), axis=0), axis=1)
        rec = (rank < max_influences) & (had | is_new[None, :])
    rest = 1.0 - (before * locked[None, :]).sum(axis=1)
    total = (w * rec).sum(axis=1)
    ok = total > 0.0
    out = np.where(rec, w * (rest / np.where(ok, total, 1.0))[:, None], 0.0)
    out = np.where(locked[None, :], before, out)
    return np.where(ok[:, None], out, before)


def _add_by_distance(mesh, names, dropoff):
    import numpy as np
    from .skin import DROPOFF
    arm = _skin_armature(mesh)
    old = _influence_groups(mesh)
    new_names = [n for n in names if arm is not None and n in arm.data.bones]
    columns = [g.name for g in old] + new_names
    segs = _joint_segments(arm, columns) if arm is not None else {}
    if any(n not in segs for n in columns) or not new_names:
        return False
    me = mesh.data
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    mw = np.array(mesh.matrix_world)
    pts = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
    col = {g.index: j for j, g in enumerate(old)}
    before = np.zeros((len(me.vertices), len(columns)))
    for v in me.vertices:
        for g in v.groups:
            j = col.get(g.group)
            if j is not None:
                before[v.index, j] = g.weight
    stored = mesh.get(DROPOFF_PROP) or {}
    dropoffs = [float(stored.get(g.name, DROPOFF)) for g in old] + [float(dropoff)] * len(new_names)
    out = maya_add_weights(pts, before, [segs[n] for n in columns], [False] * len(old) + [True] * len(new_names),
                           [g.lock_weight for g in old] + [False] * len(new_names), dropoffs,
                           int(mesh.get(MAX_INFLUENCES_PROP, MAX_INFLUENCES)))
    groups = list(old) + [mesh.vertex_groups.new(name=n) for n in new_names]
    every = list(range(len(me.vertices)))
    for j, vg in enumerate(groups):
        if vg.lock_weight:
            continue
        vg.remove(every)
        for value in np.unique(out[:, j]):
            if value > 0.0:
                vg.add(np.flatnonzero(out[:, j] == value).tolist(), float(value), 'REPLACE')
    if float(dropoff) != DROPOFF:
        stored = dict(stored.items())
        stored.update({n: float(dropoff) for n in new_names})
        mesh[DROPOFF_PROP] = stored
    return True


def add_influence(mesh, bone_names, lock=False, weight=0.0, dropoff=4.0):
    """Maya Add Influence. Default (Lock weights off): the skin weights are recomputed by distance with the new
    joints (``maya_add_weights``). Option window Lock weights:
    the new influence weighs ``weight`` on every vertex, the other influences are scaled
    by 1 - weight, and it is locked (Blender's vertex group lock)."""
    names = [n for n in dict.fromkeys(bone_names) if n not in mesh.vertex_groups]
    if not names:
        return []
    if not lock and _add_by_distance(mesh, names, dropoff):
        return names
    added = []
    all_verts = [v.index for v in mesh.data.vertices]
    w = min(max(weight, 0.0), 1.0) if lock else 0.0
    for name in names:
        if w > 0.0:
            idx = {g.index for g in _influence_groups(mesh)}
            for v in mesh.data.vertices:
                for g in v.groups:
                    if g.group in idx:
                        g.weight *= 1.0 - w
        g = mesh.vertex_groups.new(name=name)
        g.add(all_verts, w, 'REPLACE')
        g.lock_weight = lock
        added.append(name)
    return added


def remove_influence(mesh, bone_names):
    removed = []
    for name in bone_names:
        g = mesh.vertex_groups.get(name)
        if g is not None:
            mesh.vertex_groups.remove(g)
            removed.append(name)
    if removed:
        normalize(mesh)
    return removed


def unused_influences(mesh):
    groups = _influence_groups(mesh)
    used = {g.index: False for g in groups}
    for v in mesh.data.vertices:
        for g in v.groups:
            if g.group in used and g.weight > 1e-9:
                used[g.group] = True
    return [g.name for g in groups if not used[g.index]]


def _selected_bone_names(context):
    arm = None
    for o in context.selected_objects:
        if o.type == 'ARMATURE':
            arm = o
    if context.active_object is not None and context.active_object.type == 'ARMATURE':
        arm = context.active_object
    if arm is None:
        return []
    from ..ui import channel_box      # Bone.select is gone in 5.x: the shim
    return [pb.name for pb in arm.pose.bones if channel_box.bone_selected(pb)]


class ALLSET_OT_add_influence(bpy.types.Operator):
    """Add the selected joints to the selected skinned mesh; the weights are recomputed by distance (Maya Skin >
    Edit Influences > Add Influence)"""
    bl_idname = "allset.add_influence"
    bl_label = "Add Influence"
    bl_options = {'REGISTER', 'UNDO'}

    lock_weights: BoolProperty(name="Lock weights", default=False, options={'SKIP_SAVE', 'HIDDEN'})
    default_weight: FloatProperty(name="Default weight", default=0.0, min=0.0, max=1.0,
                                  options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        meshes, names = _skinned(context), _selected_bone_names(context)
        if not meshes or not names:
            self.report({'WARNING'}, "Select the skinned mesh and the joints to add")
            return {'CANCELLED'}
        added = [n for m in meshes for n in add_influence(m, names, self.lock_weights, self.default_weight)]
        results.result(self, f"Added {', '.join(added) or 'nothing (already influences)'}")
        return {'FINISHED'}


class ALLSET_OT_remove_influence(bpy.types.Operator):
    """Remove the selected joints from the selected skinned mesh; the weights are renormalised (Maya Skin > Edit
    Influences > Remove Influence)"""
    bl_idname = "allset.remove_influence"
    bl_label = "Remove Influence"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        meshes, names = _skinned(context), _selected_bone_names(context)
        if not meshes or not names:
            self.report({'WARNING'}, "Select the skinned mesh and the joints to remove")
            return {'CANCELLED'}
        for m in meshes:
            remove_influence(m, names)
        return {'FINISHED'}


class ALLSET_OT_remove_unused_influences(bpy.types.Operator):
    """Remove influences that weigh nothing on any vertex (Maya Skin > Edit Influences > Remove Unused
    Influences)"""
    bl_idname = "allset.remove_unused_influences"
    bl_label = "Remove Unused Influences"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        meshes = _skinned(context) or [o for o in context.selected_objects if o.type == 'MESH']
        n = 0
        for m in meshes:
            names = unused_influences(m)
            for name in names:
                m.vertex_groups.remove(m.vertex_groups[name])
            n += len(names)
        results.result(self, f"Removed {n} unused influence(s)")
        return {'FINISHED'}


def hammer(bm, deform, groups):
    """Selected vertices take the plain average of their edge neighbours' weights over ``groups`` (Maya Hammer Skin
    Weights). Returns the number of changed vertices."""
    new = {}
    for v in (v for v in bm.verts if v.select):
        nbrs = [e.other_vert(v) for e in v.link_edges]
        if not nbrs:
            continue
        avg = {g: sum(n[deform].get(g, 0.0) for n in nbrs) / len(nbrs) for g in groups}
        total = sum(avg.values())
        if total > 1e-12:
            avg = {g: w / total for g, w in avg.items()}
        new[v] = avg
    for v, avg in new.items():
        dv = v[deform]
        for g, w in avg.items():
            if w > 0.0 or g in dv:
                dv[g] = w
    return len(new)


class ALLSET_OT_hammer_weights(bpy.types.Operator):
    """Give the selected vertices the average skin weights of their neighbours (Maya Skin > Hammer Skin Weights)"""
    bl_idname = "allset.hammer_weights"
    bl_label = "Hammer Skin Weights"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.edit_object
        return ob is not None and ob.type == 'MESH'

    def execute(self, context):
        ob = context.edit_object
        groups = [g.index for g in (_influence_groups(ob) or ob.vertex_groups)]
        bm = bmesh.from_edit_mesh(ob.data)
        deform = bm.verts.layers.deform.verify()
        n = hammer(bm, deform, groups)
        bmesh.update_edit_mesh(ob.data)
        if not n:
            self.report({'WARNING'}, "Select vertices to hammer")
            return {'CANCELLED'}
        return {'FINISHED'}
