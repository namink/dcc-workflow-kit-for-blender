# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Skin > Substitute Geometry (``allset.substitute_geometry``): the skinned object keeps its name, transform,
skin and vertex group names and takes the new mesh's points and faces; each new vertex gets the old weights
interpolated at the closest old surface point within the reweighting distance (``substitute_weights``,
``face_weights``), else the nearest old vertex's weights.
"""

import bpy
from bpy.props import BoolProperty, FloatProperty
from mathutils import Vector, kdtree
from mathutils.bvhtree import BVHTree

from .. import results
from . import skin, units
from .skin_normalize_weights import is_part

# --- Substitute Geometry -------------------------------------------------------------------------------------------
NO_DEFORMERS = "No deformers found attached to the geometry."      # substituteGeometry's warning


def _quad_weights(p, q):
    """Bilinear weights of the point of quad ``q`` (4 corners, in order) closest to ``p`` (Newton, clamped)."""
    s = t = 0.5
    for _ in range(30):
        pt = (1 - s) * (1 - t) * q[0] + s * (1 - t) * q[1] + s * t * q[2] + (1 - s) * t * q[3]
        ps = (1 - t) * (q[1] - q[0]) + t * (q[2] - q[3])
        pq = (1 - s) * (q[3] - q[0]) + s * (q[2] - q[1])
        r = p - pt
        a, b, c = ps.dot(ps), ps.dot(pq), pq.dot(pq)
        det = a * c - b * b
        if abs(det) < 1e-18:
            break
        e, f = ps.dot(r), pq.dot(r)
        ds, dt = (c * e - b * f) / det, (a * f - b * e) / det
        s2, t2 = min(1.0, max(0.0, s + ds)), min(1.0, max(0.0, t + dt))
        if abs(s2 - s) < 1e-13 and abs(t2 - t) < 1e-13:
            s, t = s2, t2
            break
        s, t = s2, t2
    return ((1 - s) * (1 - t), s * (1 - t), s * t, (1 - s) * t)


def _tri_weights(p, a, b, c):
    v0, v1, v2 = b - a, c - a, p - a
    d00, d01, d11 = v0.dot(v0), v0.dot(v1), v1.dot(v1)
    d20, d21 = v2.dot(v0), v2.dot(v1)
    den = d00 * d11 - d01 * d01
    if abs(den) < 1e-18:
        return (1.0, 0.0, 0.0)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    return (1.0 - v - w, v, w)


def face_weights(p, corners):
    """Interpolation weights of the face corners at its point ``p`` (on or near the face)."""
    if len(corners) == 3:
        return _tri_weights(p, *corners)
    if len(corners) == 4:
        return _quad_weights(p, corners)
    from mathutils.interpolate import poly_3d_calc
    return tuple(poly_3d_calc(corners, p))       # n-gons: Blender's polygon weights


def substitute_weights(old_co, old_faces, old_w, new_co, tolerance):
    """New vertices' weights (list of rows) from the old surface: closest point within ``tolerance`` = interpolated
    weights there, else the nearest old vertex's weights (tolerance <= 0: always the nearest vertex)."""
    old_co = [Vector(c) for c in old_co]
    kd = kdtree.KDTree(len(old_co))
    for i, c in enumerate(old_co):
        kd.insert(c, i)
    kd.balance()
    bvh = BVHTree.FromPolygons(old_co, old_faces) if old_faces else None
    out = []
    for p in new_co:
        p = Vector(p)
        hit = bvh.find_nearest(p) if bvh is not None and tolerance > 0 else (None, None, None, None)
        if hit[0] is None or hit[3] > tolerance:
            out.append(list(old_w[kd.find(p)[1]]))
            continue
        face = old_faces[hit[2]]
        cw = face_weights(hit[0], [old_co[i] for i in face])
        out.append([sum(c * old_w[i][g] for c, i in zip(cw, face)) for g in range(len(old_w[0]))])
    return out


def _all_group_weights(mesh):
    names = [vg.name for vg in mesh.vertex_groups]
    rows = [[0.0] * len(names) for _ in mesh.data.vertices]
    for v in mesh.data.vertices:
        for g in v.groups:
            rows[v.index][g.group] = g.weight
    return names, rows


def substitute_geometry(context, old, new, tolerance, retain_old=False, disable_non_skin=False):
    """Maya substituteGeometry: ``old`` keeps name, transform, skin and vertex group names, takes ``new``'s points
    (object space) and faces with reweighted weights; ``new`` is removed. Returns the retained copy (or None)."""
    arm_md = skin.armature_modifier(old)
    if arm_md is None:
        raise ValueError(NO_DEFORMERS)
    old_me = old.data
    names, old_w = _all_group_weights(old)
    old_co = [v.co.copy() for v in old_me.vertices]
    old_faces = [list(p.vertices) for p in old_me.polygons]
    new_me = new.data.copy()
    new_w = substitute_weights(old_co, old_faces, old_w, [v.co for v in new_me.vertices], tolerance)
    kept = None
    if retain_old:                              # Maya: a copy of the old skinned geometry on a copy of the skeleton
        arm = arm_md.object
        arm2 = arm.copy()
        arm2.data = arm.data.copy()
        kept = old.copy()
        kept.data = old_me
        for coll in old.users_collection:
            coll.objects.link(kept)
        for coll in arm.users_collection:
            coll.objects.link(arm2)
        for md in kept.modifiers:
            if md.type == 'ARMATURE' and md.object == arm:
                md.object = arm2
    shape_name = old_me.name
    old.data = new_me
    if old_me.users == 0:
        bpy.data.meshes.remove(old_me)
    new_me.name = shape_name
    old.vertex_groups.clear()                   # group names live on the mesh: the skin's groups, in their order
    groups = old.vertex_groups
    for name in names:
        groups.new(name=name)
    for vi, row in enumerate(new_w):
        for gi, w in enumerate(row):
            if w > 0.0:
                groups[names[gi]].add([vi], w, 'REPLACE')
    if disable_non_skin:
        for md in old.modifiers:
            if md.type != 'ARMATURE' and not is_part(md):
                md.show_viewport = md.show_render = False
    new_data = new.data
    bpy.data.objects.remove(new)
    if new_data is not None and new_data.users == 0:
        bpy.data.meshes.remove(new_data)
    return kept


class ALLSET_OT_substitute_geometry(bpy.types.Operator):
    """Maya Skin > Substitute Geometry: the selected skinned mesh takes the other selected mesh's geometry and keeps
    its skin (weights carried over by closest point)"""
    bl_idname = "allset.substitute_geometry"
    bl_label = "Substitute Geometry"
    bl_options = {'REGISTER', 'UNDO'}

    reweight_distance: FloatProperty(name="Reweighting distance", description="Maya units: new points farther "
                                     "from the old surface take the nearest old vertex's weights", default=1.0,
                                     min=0.0, soft_max=10.0, max=10000.0)
    retain_old: BoolProperty(name="Retain old geometry", default=False)
    disable_non_skin: BoolProperty(name="Disable non-skin deformers", default=False)

    def execute(self, context):
        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        skinned = [o for o in meshes if skin.armature_modifier(o) is not None]
        if len(meshes) != 2 or not skinned:
            self.report({'WARNING'}, "Select the skinned mesh and the new mesh")
            return {'CANCELLED'}
        act = context.active_object
        if len(skinned) == 2:                   # both skinned: the active one is the new geometry
            old = next(o for o in meshes if o is not act) if act in meshes else skinned[0]
        else:
            old = skinned[0]
        new = next(o for o in meshes if o is not old)
        if context.active_object is not None and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            substitute_geometry(context, old, new, self.reweight_distance * units.maya_unit(context.scene),
                                self.retain_old, self.disable_non_skin)
        except ValueError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        old.select_set(True)
        context.view_layer.objects.active = old
        results.result(self, old.name)
        return {'FINISHED'}
