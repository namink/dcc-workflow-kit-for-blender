# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Deform > Cluster and Soft Modification as a Hook modifier (``clusterN`` / ``softModN``) driven by a handle empty
(``clusterNHandle`` / ``softModNHandle``) at the selection's centre: Cluster acts on the selected vertices / CVs (on a
mesh through a vertex group that Paint Weights paints), Soft Mod on every vertex with a smooth falloff (radius in Maya
units). Entry points ``allset.cluster``, ``allset.soft_mod``, ``control_points``; rig_maya re-exports them.
"""

import math

import bmesh
import bpy
from mathutils import Vector

from . import units

SOFT_MOD_RADIUS = 5.0          # Maya softMod falloffRadius default (Maya units)


# --- Cluster / Soft Mod (Hook modifiers + handle empties) ------------------------------------------

def _hook(context, ob, base, centre_world, vertex_indices=None):
    """Hook modifier ``<base>N`` driven by the empty ``<base>NHandle`` at ``centre_world`` (rest = no change).

    #34: a mesh's points are the vertex group ``<base>N`` (weight 1, the default deformer weight),
    which Deform > Paint Weights paints; ``vertex_indices`` None = every point (a Hook with neither a group nor
    indices moves nothing)."""
    from . import deformers
    name = deformers.new_name(base)
    handle = bpy.data.objects.new(f"{name}Handle", None)
    context.view_layer.active_layer_collection.collection.objects.link(handle)
    handle.empty_display_type = 'PLAIN_AXES'
    handle.empty_display_size = 0.5 * units.maya_unit(context.scene)
    handle.location = centre_world
    context.view_layer.update()
    md = ob.modifiers.new(name, 'HOOK')
    md.object = handle
    # inverted_safe: an object scaled to 0 on an axis still gets its cluster1 in Maya
    md.center = ob.matrix_world.inverted_safe() @ centre_world
    md.matrix_inverse = handle.matrix_world.inverted() @ ob.matrix_world
    if ob.type == 'MESH':
        vg = ob.vertex_groups.new(name=name)
        vg.add(list(vertex_indices) if vertex_indices is not None else list(range(len(ob.data.vertices))), 1.0,
               'REPLACE')
        md.vertex_group = vg.name
    elif vertex_indices is not None:
        md.vertex_indices_set(vertex_indices)
    return md, handle


def _selection(ob):
    """World centroid of the selected vertices and their indices (object mode: all vertices, the object's centre)."""
    if ob.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(ob.data)
        idx = [v.index for v in bm.verts if v.select]
        cos = [v.co for v in bm.verts if v.select]
    else:
        idx = None
        vs = [v.co for v in ob.data.vertices]          # undeformed points (bound_box follows the modifiers)
        cos = []
        if vs:   # the bounding-box corners: their mean is the box centre
            cos = [Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs))),
                   Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))]
    if not cos:
        return None, None
    c = sum(cos, Vector()) / len(cos)
    return ob.matrix_world @ c, idx


def control_points(ob):
    """``(hook index, local co, selected)`` of a curve / surface / lattice in the Hook modifier's point order: NURBS
    and poly points one each, a Bezier point three (left handle, point, right handle; the point carries the
    selection and the position)."""
    out = []
    if ob.type == 'LATTICE':
        for i, p in enumerate(ob.data.points):
            out.append((i, Vector(p.co_deform), p.select))
        return out
    i = 0
    for sp in ob.data.splines:
        if sp.type == 'BEZIER':
            for bp in sp.bezier_points:
                out.append(((i, i + 1, i + 2), bp.co.copy(), bp.select_control_point))
                i += 3
        else:
            for p in sp.points:
                out.append((i, Vector(p.co[:3]), p.select))
                i += 1
    return out


def _point_selection(ob, selected_only):
    """Maya cluster on CVs: the handle pivot is the centre
    of the selected CVs, the Hook acts on exactly those indices; object mode = every CV (pivot = their box centre,
    like a mesh). Returns (world centre, indices) or (None, None)."""
    pts = [p for p in control_points(ob) if p[2] or not selected_only]
    if not pts:
        return None, None
    idx = []
    for k, _co, _sel in pts:
        idx.extend(k if isinstance(k, tuple) else (k,))
    cos = [co for _k, co, _sel in pts]
    if selected_only:
        c = sum(cos, Vector()) / len(cos)
    else:
        lo = Vector([min(v[a] for v in cos) for a in range(3)])
        hi = Vector([max(v[a] for v in cos) for a in range(3)])
        c = (lo + hi) / 2
    return ob.matrix_world @ c, idx


def _select_handle(context, handle):
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in context.selected_objects:
        o.select_set(False)
    handle.select_set(True)
    context.view_layer.objects.active = handle


class ALLSET_OT_cluster(bpy.types.Operator):
    """Make a cluster of the selected components (or the whole object): a Hook modifier ``clusterN`` driven by the
    handle ``clusterNHandle`` at their centre (Maya Deform > Cluster)"""
    bl_idname = "allset.cluster"
    bl_label = "Cluster"
    bl_options = {'REGISTER', 'UNDO'}

    envelope: bpy.props.FloatProperty(name="Envelope", default=1.0, min=0.0, max=1.0,
                                      description="Maya cluster envelope = the Hook's strength")

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type in {'MESH', 'LATTICE', 'CURVE', 'SURFACE'}

    def execute(self, context):
        ob = context.active_object
        if ob.type == 'MESH':
            centre, idx = _selection(ob)
            if ob.mode == 'EDIT':
                bpy.ops.object.mode_set(mode='OBJECT')
        else:
            if ob.mode == 'EDIT':     # leaving edit mode writes the CV selection back to the data
                bpy.ops.object.mode_set(mode='OBJECT')
                centre, idx = _point_selection(ob, True)
            else:
                centre, idx = _point_selection(ob, False)
        if centre is None:
            self.report({'WARNING'}, "Select components or an object")
            return {'CANCELLED'}
        md, handle = _hook(context, ob, "cluster", centre, idx)
        md.strength = self.envelope
        handle.empty_display_type = 'SPHERE'
        _select_handle(context, handle)       # Maya: the new handle is selected
        return {'FINISHED'}


def cosine_falloff(curve_mapping, steps=10):
    """Hook falloff curve = Maya softMod's smooth curve: weight = (1 + cos(pi d / r)) / 2, input x = 1 - d / r."""
    curve = curve_mapping.curves[0]
    while len(curve.points) > 2:
        curve.points.remove(curve.points[1])
    curve.points[0].location = (0.0, 0.0)
    curve.points[-1].location = (1.0, 1.0)
    for k in range(1, steps):
        x = k / steps
        curve.points.new(x, (1 - math.cos(math.pi * x)) / 2)
    curve_mapping.update()


class ALLSET_OT_soft_mod(bpy.types.Operator):
    """Soft modification at the selection: a Hook modifier ``softModN`` on the whole mesh with Maya's falloff
    (radius 5, smooth) driven by ``softModNHandle`` (Maya Deform > Soft Modification)"""
    bl_idname = "allset.soft_mod"
    bl_label = "Soft Modification"
    bl_options = {'REGISTER', 'UNDO'}

    radius: bpy.props.FloatProperty(name="Falloff Radius", default=SOFT_MOD_RADIUS, min=0.0,
                                    description="Maya units (softMod falloffRadius)")

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'MESH'

    def execute(self, context):
        ob = context.active_object
        if ob.mode == 'EDIT':
            centre, _idx = _selection(ob)
            bpy.ops.object.mode_set(mode='OBJECT')
        else:
            centre = ob.matrix_world.translation.copy()
        if centre is None:
            self.report({'WARNING'}, "Select components or an object")
            return {'CANCELLED'}
        # a Hook with neither a vertex group nor indices moves nothing: every vertex, weighted by falloff
        md, handle = _hook(context, ob, "softMod", centre, None)
        md.falloff_type = 'CURVE'
        md.falloff_radius = self.radius * units.maya_unit(context.scene)
        cosine_falloff(md.falloff_curve)
        handle.empty_display_type = 'CUBE'
        _select_handle(context, handle)
        return {'FINISHED'}
