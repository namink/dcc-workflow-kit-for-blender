# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Select menu rows for NURBS curves and surfaces.

Maya:
- Select > Components > Control Vertex (NURBS Curves and NURBS Surfaces sections): the selected curves and surfaces
  show their CVs to pick (CV component mode).
- Select > Surface Border: every CV on the first and last row and column of each selected surface's CV grid; an
  object or any of its CVs selected gives the same border.
- Select > CV Selection Boundary: of the selected CVs of a surface, the ones that have an unselected CV, or the edge
  of the grid, among their eight neighbours in the grid (a block keeps its outline, a lone CV or a single row
  stays as it is).
- A curve has no border: both leave nothing selected on it.

Kit: a Blender surface spline's points are a U x V grid, point ``j * nu + i`` = Maya ``cv[i][j]``; a closed (cyclic)
direction has no edge there, its neighbours wrap around. The CVs are picked in edit mode of the surfaces.
"""

import bpy

from . import maya_errors

CURVE_TYPES = {'CURVE', 'SURFACE'}


# --- pure rules --------------------------------------------------------------------------------------------------

def border(nu, nv, cyclic_u=False, cyclic_v=False):
    """Indices (j * nu + i) of the CVs on an open edge of a nu x nv grid."""
    out = set()
    for j in range(nv):
        for i in range(nu):
            if (not cyclic_u and i in (0, nu - 1)) or (not cyclic_v and j in (0, nv - 1)):
                out.add(j * nu + i)
    return out


def boundary(selected, nu, nv, cyclic_u=False, cyclic_v=False):
    """Of ``selected`` (indices j * nu + i), the ones with an unselected or missing CV among their eight
    neighbours."""
    selected = set(selected)
    out = set()
    for k in selected:
        i, j = k % nu, k // nu
        edge = False
        for dj in (-1, 0, 1):
            for di in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                a, b = i + di, j + dj
                if cyclic_u:
                    a %= nu
                if cyclic_v:
                    b %= nv
                if not (0 <= a < nu and 0 <= b < nv) or b * nu + a not in selected:
                    edge = True
                    break
            if edge:
                break
        if edge:
            out.add(k)
    return out


# --- Blender ---------------------------------------------------------------------------------------------------

def _targets(context):
    """The curves and surfaces the command works on: the ones in edit mode, else the selected ones."""
    obs = list(getattr(context, "objects_in_mode", None) or ()) if context.mode in {'EDIT_CURVE', 'EDIT_SURFACE'} \
        else list(context.selected_objects)
    return [o for o in obs if o.type in CURVE_TYPES]


def _object_mode(context):
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def _edit(context, objects):
    """Edit mode on ``objects`` (Blender edits one object type at a time: the surfaces)."""
    vl = context.view_layer
    for o in context.selected_objects:
        if o not in objects:
            o.select_set(False)
    for o in objects:
        o.select_set(True)
    if objects:
        if vl.objects.active not in objects:
            vl.objects.active = objects[0]
        bpy.ops.object.mode_set(mode='EDIT')


def _points(sp):
    return sp.points if sp.type != 'BEZIER' else ()


def _set_selection(ob, pick):
    """Select exactly the points ``pick(spline) -> set of indices`` of every spline of ``ob``."""
    for sp in ob.data.splines:
        chosen = pick(sp)
        if sp.type == 'BEZIER':
            for bp in sp.bezier_points:
                bp.select_control_point = bp.select_left_handle = bp.select_right_handle = False
            continue
        for k, p in enumerate(sp.points):
            p.select = k in chosen


def _grid(sp):
    nv = max(sp.point_count_v, 1)
    return sp.point_count_u, nv, sp.use_cyclic_u, sp.use_cyclic_v


def select_border(context, targets):
    _object_mode(context)
    surfaces = [o for o in targets if o.type == 'SURFACE']
    for ob in targets:
        if ob.type == 'SURFACE':
            _set_selection(ob, lambda sp: border(*_grid(sp)))
        else:
            _set_selection(ob, lambda sp: set())
    _edit(context, surfaces)
    return surfaces


def select_boundary(context, targets):
    _object_mode(context)
    surfaces = [o for o in targets if o.type == 'SURFACE']
    for ob in targets:
        if ob.type == 'SURFACE':
            _set_selection(ob, lambda sp: boundary([k for k, p in enumerate(sp.points) if p.select], *_grid(sp)))
        else:
            _set_selection(ob, lambda sp: set())
    _edit(context, surfaces)
    return surfaces


class ALLSET_OT_nurbs_component(bpy.types.Operator):
    """Show the CVs of the selected curves and surfaces to pick them (Maya Select > Components > Control Vertex)"""
    bl_idname = "allset.nurbs_component"
    bl_label = "Control Vertex"
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type in CURVE_TYPES

    def execute(self, context):
        ob = context.active_object
        if maya_errors.refuse_hidden(self, ob):
            return {'CANCELLED'}
        if context.mode == 'OBJECT':
            for o in context.selected_objects:     # Blender edits one object type at a time: the active one's
                if o.type != ob.type:
                    o.select_set(False)
            bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}


class ALLSET_OT_select_surface_border(bpy.types.Operator):
    """Select the CVs along the borders of the selected surfaces (Maya Select > Surface Border)"""
    bl_idname = "allset.select_surface_border"
    bl_label = "Surface Border"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(_targets(context))

    def execute(self, context):
        select_border(context, _targets(context))
        return {'FINISHED'}


class ALLSET_OT_select_cv_boundary(bpy.types.Operator):
    """Keep only the outline of the selected CV region on each surface (Maya Select > CV Selection Boundary)"""
    bl_idname = "allset.select_cv_boundary"
    bl_label = "CV Selection Boundary"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(_targets(context))

    def execute(self, context):
        select_boundary(context, _targets(context))
        return {'FINISHED'}


classes = (ALLSET_OT_nurbs_component, ALLSET_OT_select_surface_border, ALLSET_OT_select_cv_boundary)
