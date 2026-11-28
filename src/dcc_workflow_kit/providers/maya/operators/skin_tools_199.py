# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Skin menu tools: Move Weights to Influences, Normalize Weights > Disable / Enable / Enable Post,
Export Weight Maps... / Import Weights Maps..., Substitute Geometry, Bake Deformation to Skin Weights...

Every rule here follows Maya.
A kit skin = the Armature modifier + vertex groups named after
its bones (operators/skin.py); a joint's Maya "lock weights" (.liw) = the vertex group's ``lock_weight``.

- Move Weights to Influences (the first selected joint is the source, the others the targets): on each
  selected vertex every unlocked target gets
  the **source's weight** (set, not added), the source gets 0; with Interactive normalisation the unlocked weights are
  then scaled to fill 1 - (locked weights). None / Post leave the sums as they are.
- Normalize Weights modes (skinCluster.normalizeWeights 0 / 1 / 2): Maya deforms
  a point by sum(w_i M_i p) in world space in None and Interactive (unnormalised weights scale the point about the
  world origin; a point without weights stays put) and by sum(w_i M_i p) / sum(w_i) in Post. Blender's Armature
  modifier is Post (it divides by the weight sum), so None / Interactive skins get a Geometry Nodes modifier
  after the Armature modifier that multiplies the world position by the weight sum.
- Weight maps (Maya Export / Import Skin Weight Maps): a ``<name>.weightMap`` text file (two comment lines, then
  ``<skin>\\t<influence>\\t<image>`` per weighted influence) and a ``<name>/`` folder with one grey image per influence
  in UV space (default 512 x 512, luminance). Import: every weight of the skins in the file is cleared, each listed
  influence takes the image value at the vertex UVs, then the weights are normalised.
- Substitute Geometry (reweighting distance 1 by default): the skinned object
  keeps its name, transform and skin and takes the new mesh's object-space points; each new vertex takes the old
  weights interpolated at the closest point of the old surface (bilinear on quads, barycentric on triangles) when that
  point is within the reweighting distance, else the weights of the nearest old vertex.
- Bake Deformation to Skin Weights: per vertex the weights are the
  least-squares fit, over a range of motion, of linear blend skinning of the **source rest point** to the source's
  deformed points, constrained to w >= 0 and sum(w) = 1. The kit's range of motion samples each joint rotated
  +-45 degrees about its X / Y / Z axes.

Code: skin_weight_access (shared lookups), skin_normalize_weights, skin_weight_maps, skin_substitute_geometry,
skin_bake_deformation; this module keeps Move Weights to Influences, the weight-sum depsgraph handler
(``_sync_sum_modifiers``), the classes tuple, the handler registration and re-exports.
"""

import bpy
from bpy.props import StringProperty

from .. import results
from .. import update_summary
from . import skin
from .skin_cluster import off_the_cage, show_pose_in_components
from .skin_weight_access import _skin_armature, influence_names, NO_SKIN, skinned_meshes, _Weights  # noqa: F401
from .skin_normalize_weights import (ALLSET_OT_skin_normalize_mode, _build_sum_group, ensure_sum_modifier, is_part,
                                     _link, MAYA_VALUE, NORMALIZE_LABELS, normalize_state, remove_sum_modifier,
                                     set_normalize_mode, SUM_SUFFIX, _sum_signature, sum_modifier,
                                     SUM_TAG)  # noqa: F401
from .skin_weight_maps import (ALLSET_OT_export_weight_maps, ALLSET_OT_import_weight_maps, export_weight_maps,
                               import_weight_maps, MAP_EXT, map_file_name, MAP_FORMATS, MAP_HEADER, map_paths,
                               _sample, _uv_raster, _vertex_uvs, _vertex_weights)  # noqa: F401
from .skin_substitute_geometry import (ALLSET_OT_substitute_geometry, _all_group_weights, face_weights, NO_DEFORMERS,
                                       _quad_weights, substitute_geometry, substitute_weights,
                                       _tri_weights)  # noqa: F401
from .skin_bake_deformation import (ALLSET_OT_bake_deformation, apply_weights, BAKE_ANGLE, bake_weights,
                                    _deformed_world, _pose_bones_matching, simplex_lsq,
                                    _skin_matrices)  # noqa: F401

# --- Move Weights to Influences ------------------------------------------------------------------------------------
# Maya's errors (Move Weights to Influences, skinPercent).
NO_VERTS = "No skin vertices were selected."
BAD_SOURCE = "Selected source influence for move weights are either locked or not connected to this skin cluster."
BAD_TARGETS = "Selected target influences for move weights are either locked or not connected to this skin cluster."


def move_row(row, source, targets, locked, interactive):
    """One vertex: ``row`` {influence: weight} (every influence), returns the new row (Maya skinPercent -tmw)."""
    row = dict(row)
    s = row.get(source, 0.0)
    for t in targets:
        if t not in locked:
            row[t] = s
    row[source] = 0.0
    if interactive:
        room = max(0.0, 1.0 - sum(w for n, w in row.items() if n in locked))
        free = [n for n in row if n not in locked]
        total = sum(row[n] for n in free)
        if total > 0.0:
            for n in free:
                row[n] = row[n] * room / total
    return row


def move_weights(mesh, source, targets, verts=None):
    """Move ``source``'s weights to ``targets`` on the selected (or given) vertices; raises ValueError with Maya's
    message. Returns the number of vertices changed."""
    names = influence_names(mesh)
    groups = {vg.name: vg for vg in mesh.vertex_groups}
    locked = {n for n in names if groups[n].lock_weight}
    if source not in names or source in locked:
        raise ValueError(BAD_SOURCE)
    tgts = [t for t in targets if t in names and t != source]
    if not [t for t in tgts if t not in locked]:
        raise ValueError(BAD_TARGETS)
    io = _Weights(mesh)
    vs = io.selected() if verts is None else list(verts)
    if not vs:
        if not io.edit:
            io.bm.free()
        raise ValueError(NO_VERTS)
    interactive = skin.normalize_mode(mesh) == "INTERACTIVE"
    idx = {n: groups[n].index for n in names}
    for vi in vs:
        row = {n: io.get(vi, idx[n]) for n in names}
        new = move_row(row, source, tgts, locked, interactive)
        for n, w in new.items():
            if abs(w - row[n]) > 0.0:
                io.set(vi, idx[n], w)
    io.flush()
    return len(vs)


def picked_joints(arm):
    """Selected joints of ``arm`` as (source, targets): Maya takes the first selected joint as the source; Blender
    keeps no selection order, so with two joints the active (last picked) one is the target, with more the joints
    other than the active one come in skeleton order and the first is the source."""
    from ..ui import channel_box      # Bone.select is gone in 5.x: the shim
    sel = [pb.name for pb in arm.pose.bones if channel_box.bone_selected(pb)]
    act = arm.data.bones.active
    act = act.name if act is not None and act.name in sel else None
    others = [n for n in sel if n != act]
    if act is None:
        return (sel[0], sel[1:]) if sel else (None, [])
    if not others:
        return None, [act]
    return others[0], others[1:] + [act]


class ALLSET_OT_move_skin_weights(bpy.types.Operator):
    """Maya Skin > Move Weights to Influences: on the selected vertices the target joints get the source joint's
    weight and the source gets none (select the vertices, the source joint, then the targets)"""
    bl_idname = "allset.move_skin_weights"
    bl_label = "Move Weights to Influences"
    bl_options = {'REGISTER', 'UNDO'}

    source: StringProperty(name="Source", default="", options={'SKIP_SAVE', 'HIDDEN'})
    targets: StringProperty(name="Targets", description="Comma-separated joint names", default="",
                            options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        meshes = skinned_meshes(context)
        if not meshes:
            self.report({'WARNING'}, "No skin cluster found: select the skinned vertices and the joints")
            return {'CANCELLED'}
        done = 0
        for mesh in meshes:
            if self.source:
                src, tgts = self.source, [t.strip() for t in self.targets.split(",") if t.strip()]
            else:
                src, tgts = picked_joints(_skin_armature(mesh))
            try:
                done += move_weights(mesh, src, tgts)
            except ValueError as ex:
                self.report({'ERROR'}, str(ex))
                return {'CANCELLED'}
        results.result(self, f"skinPercent: moved weights on {done} vertices")
        return {'FINISHED'}


@bpy.app.handlers.persistent
def _sync_sum_modifiers(scene, depsgraph):
    """Keep weight-sum modifiers summing the skin's current influences; drop them when the skin is gone. A skinned mesh
    in component mode shows its components on the posed mesh (Maya), whoever bound it."""
    for upd in update_summary.updates(depsgraph, _sync_sum_modifiers):
        ob = upd.id.original if isinstance(upd.id, bpy.types.Object) else None
        if ob is None or ob.type != 'MESH' or not ob.modifiers:
            continue
        if ob.mode == 'EDIT' and any(off_the_cage(m) for m in ob.modifiers):
            update_summary.wrote()
            show_pose_in_components(ob)
        md = sum_modifier(ob)
        if md is None:
            continue
        if skin.armature_modifier(ob) is None:
            update_summary.wrote()
            remove_sum_modifier(ob)
        elif md.node_group.get(SUM_TAG) != _sum_signature(ob):
            update_summary.wrote()
            ensure_sum_modifier(ob)


classes = (ALLSET_OT_move_skin_weights, ALLSET_OT_skin_normalize_mode, ALLSET_OT_export_weight_maps,
           ALLSET_OT_import_weight_maps, ALLSET_OT_substitute_geometry, ALLSET_OT_bake_deformation)


def register_handlers():
    if _sync_sum_modifiers not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_sync_sum_modifiers)


def unregister_handlers():
    while _sync_sum_modifiers in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_sync_sum_modifiers)
