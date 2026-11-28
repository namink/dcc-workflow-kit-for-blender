# SPDX-License-Identifier: GPL-3.0-or-later
"""Constrain > Normal / Tangent / Remove Target / Set Rest Position / Modify Constrained Axis.

- Normal / Tangent (Maya Normal / Tangent Constraint Options, default: weight 1, aim (1, 0, 0),
  up (0, 1, 0), world up type Vector (0, 1, 0)): Maya only turns the object — its aim vector = the target's normal at
  the closest surface point (MFnMesh.getClosestPointAndNormal) / the curve's tangent at the closest curve point, its up
  vector towards the world up. No Blender constraint computes Maya's normal: Blender's Shrinkwrap uses Blender's
  corner-angle normals on Blender's triangulation, Maya interpolates face-vertex normals weighted by corner angle x
  face area (mesh vertexNormalMethod "Angle and Area Weighted") on its own triangulation (a quad is split along the
  shorter diagonal only when d02^2 < 0.999 d13^2, else 1-3). So the kit setup is: a Track To on
  the object (Maya's aim / up, rig_tools.aim) towards a hidden helper empty that a depsgraph / frame handler keeps at
  P + L * direction  (P = the object's world position, direction computed the Maya way in double precision:
  ``SurfaceData.normal`` / ``CurveData.tangent``).
- Remove Target: targets selected, the constrained object last; the constraints of the
  checked types whose target is selected go. When the last target of a type goes Maya deletes the constraint node and
  the channels keep the constrained value (Maya) — the kit bakes the visual value into the object's own channels.
- Set Rest Position: Maya stores the current constrained channels as the constraint's
  rest values, used when every target weight is 0. In Blender a constraint at influence 0 shows the object's own
  channels, so the rest position is the own channels: the kit writes the current constrained values into them.
- Modify Constrained Axis (default X / Y / Z on, Maintain offset off): which axes the point
  / orient / scale / parent constraints drive (Blender use_x / use_y / use_z, Child Of use_location_* / use_rotation_*;
  the axes are the Channel Box's). A newly skipped channel keeps its last constrained value (Maya); Maintain offset
  = Blender's constraint offsets set so nothing moves now.

Code: normal_tangent_math (closest-point normal / tangent), normal_tangent_helpers (helper empties), constrain_modify
(Remove Target, Set Rest Position, Modify Constrained Axis, ``maya_type``, ``bake``); this module keeps the Normal /
Tangent constraint setup, its handlers, the classes tuple and re-exports.
"""

import math

import bpy
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty
from mathutils import Vector

from .. import results
from .. import update_summary
from . import rig_tools
from .normal_tangent_math import (QUAD_SPLIT, CurveData, SurfaceData, _dot, _sub, closest_on_triangle,
                                  closest_param, quad_split)  # noqa: F401
from .normal_tangent_helpers import (KIND, LABEL, MAYA_NODE, OWNER, SURFACE, _rescan, _state, helper_of, helpers,
                                     helpers_owned_by, remove_helpers, surface_of)  # noqa: F401
from .constrain_modify import (ALLSET_OT_modify_constraint_axes, ALLSET_OT_remove_constraint_target,
                               ALLSET_OT_set_constraint_rest, AXIS_TYPES, CHANNELS, MSG_AXES_INVALID, MSG_AXES_NONE,
                               MSG_AXES_SELECT, MSG_REMOVE_CONSTRAINED, MSG_REMOVE_SELECT, MSG_REST, REMOVE_TYPES,
                               REST_TYPES, bake, has_offset, maya_target, maya_type, modify_axes, remove_targets,
                               set_rest, visual)  # noqa: F401

SURFACE_HINT = "Select the target surface(s), then the object to constrain last"
CURVE_HINT = "Select the target curve(s), then the object to constrain last"


# --- the live setup: helper empties kept up to date by handlers -----------------------------------------

_cache = {}          # surface name -> (signature, data)


def _signature(ob, depsgraph):
    ev = ob.evaluated_get(depsgraph) if depsgraph is not None else ob
    m = tuple(round(x, 12) for row in ev.matrix_world for x in row)
    if ob.type == 'MESH':
        import numpy as np
        me = ev.data
        co = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        return (m, len(me.polygons), len(me.edges), hash(co.tobytes()))
    pts = []
    for sp in ob.data.splines:
        pts.append((sp.type, sp.order_u, sp.use_cyclic_u, sp.use_endpoint_u))
        pts.extend(tuple(p.co) for p in sp.points)
        pts.extend((tuple(p.co), tuple(p.handle_left), tuple(p.handle_right)) for p in sp.bezier_points)
    return (m, hash(tuple(pts)))


def surface_data(ob, depsgraph=None):
    sig = _signature(ob, depsgraph)
    hit = _cache.get(ob.name)
    if hit is not None and hit[0] == sig:
        return hit[1]
    if ob.type == 'MESH':
        ev = ob.evaluated_get(depsgraph) if depsgraph is not None else ob
        data = SurfaceData(ev.data, ev.matrix_world)
    else:
        data = CurveData(ob)
    _cache[ob.name] = (sig, data)
    return data


def direction(kind, surface, p, depsgraph=None):
    data = surface_data(surface, depsgraph)
    return data.normal(p) if kind == "normal" else data.tangent(p)


def update(depsgraph=None):
    """Move every helper to  P + L * direction  (no write when it is already there: the handler doesn't loop)."""
    if _state["busy"]:
        return
    hs = helpers()
    if not hs:
        return
    _state["busy"] = True
    try:
        if depsgraph is None:
            depsgraph = bpy.context.evaluated_depsgraph_get()
        for h in hs:
            owner, surface = h.get(OWNER), h.get(SURFACE)
            if not isinstance(owner, bpy.types.Object) or not isinstance(surface, bpy.types.Object):
                continue
            if surface.type not in {'MESH', 'CURVE'}:
                continue
            p = tuple(owner.evaluated_get(depsgraph).matrix_world.translation)
            d = direction(h[KIND], surface, p, depsgraph)
            if d is None:
                continue
            length = 1000.0 * max(1.0, math.sqrt(_dot(p, p)))     # far away: the float32 helper keeps the angle
            new = Vector(p) + Vector(d) * length
            if (h.location - new).length > 1e-7 * length or h.parent is not None:
                update_summary.wrote()
                h.parent = None
                h.location = new
    finally:
        _state["busy"] = False


@bpy.app.handlers.persistent
def _on_depsgraph(scene, depsgraph):
    update(depsgraph)


@bpy.app.handlers.persistent
def _on_frame(scene, depsgraph=None):
    update(depsgraph)


@bpy.app.handlers.persistent
def _on_load(*_args):
    _cache.clear()
    _rescan()


_HANDLERS = (("depsgraph_update_post", _on_depsgraph), ("frame_change_post", _on_frame),
             ("load_post", _on_load), ("undo_post", _on_load), ("redo_post", _on_load))


def register_handlers():
    for attr, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, attr)
        if fn not in lst:
            lst.append(fn)


def unregister_handlers():
    for attr, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, attr)
        if fn in lst:
            lst.remove(fn)
    _cache.clear()
    _rescan()


def _link_like(ob, owner, context):
    cols = list(owner.users_collection) or [context.scene.collection]
    cols[0].objects.link(ob)


def add_surface_constraint(context, kind, owner, surface, aim_vector=rig_tools.AIM_VECTOR,
                           up_vector=rig_tools.UP_VECTOR, world_up=rig_tools.WORLD_UP, weight=1.0):
    """Kit normal / tangent constraint on ``owner`` from ``surface``: helper empty + Track To. Returns the constraint."""
    n = 1 + sum(1 for c in owner.constraints if helper_of(c) is not None and helper_of(c).get(KIND) == kind)
    helper = bpy.data.objects.new(f"{owner.name}_{MAYA_NODE[kind]}{n}Aim", None)
    helper.empty_display_size = 0.0
    helper.hide_viewport = helper.hide_render = helper.hide_select = True
    helper[KIND], helper[OWNER], helper[SURFACE] = kind, owner, surface
    _link_like(helper, owner, context)
    _rescan()
    cons = owner.constraints
    con = cons.new('TRACK_TO')
    con.target = helper
    con = rig_tools.aim(cons, con, aim_vector, up_vector, world_up)
    con.name = f"{LABEL[kind]} {surface.name}"
    from . import constrain_multi
    constrain_multi.set_weight(con, weight, owner)      # Maya: any weight above 0 = fully on the surface's normal
    context.view_layer.update()
    update(context.evaluated_depsgraph_get())
    context.view_layer.update()
    return con


WORLD_UP_ITEMS = (("Vector", "Vector", "World up vector 0 0 1: the scene's Z, up (default)"),
                  ("Scene up", "Scene up", "The scene's up axis (Z)"),
                  ("None", "None", "No up vector: the shortest turn (Blender Damped Track)"))


class _SurfaceConstraint:
    bl_options = {'REGISTER', 'UNDO'}
    kind = "normal"

    weight: FloatProperty(name="Weight", default=1.0, min=0.0, max=1.0)
    aim_vector: FloatVectorProperty(name="Aim vector", default=(1.0, 0.0, 0.0), size=3)
    up_vector: FloatVectorProperty(name="Up vector", default=(0.0, 0.0, 1.0), size=3)
    world_up_type: EnumProperty(name="World up type", items=WORLD_UP_ITEMS, default="Vector")

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.active_object is not None

    def _targets(self, context, owner):
        want = {'MESH'} if self.kind == "normal" else {'CURVE'}
        return [o for o in context.selected_objects if o is not owner and o.type in want]

    def execute(self, context):
        owner = context.active_object
        targets = self._targets(context, owner)
        if not targets:
            self.report({'WARNING'}, SURFACE_HINT if self.kind == "normal" else CURVE_HINT)
            return {'CANCELLED'}
        try:
            for t in targets:
                add_surface_constraint(context, self.kind, owner, t, tuple(self.aim_vector), tuple(self.up_vector),
                                       self.world_up_type, self.weight)
        except RuntimeError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        results.result(self, f"{LABEL[self.kind]} on {owner.name} (target {', '.join(t.name for t in targets)})")
        return {'FINISHED'}


class ALLSET_OT_normal_constraint(_SurfaceConstraint, bpy.types.Operator):
    """Maya Normal constraint: select the target surface(s), then the object; its aim vector follows the surface
    normal at the closest point"""
    bl_idname = "allset.normal_constraint"
    bl_label = "Normal Constraint"
    kind = "normal"


class ALLSET_OT_tangent_constraint(_SurfaceConstraint, bpy.types.Operator):
    """Maya Tangent constraint: select the target curve(s), then the object; its aim vector follows the curve
    tangent at the closest point"""
    bl_idname = "allset.tangent_constraint"
    bl_label = "Tangent Constraint"
    kind = "tangent"


classes = (ALLSET_OT_normal_constraint, ALLSET_OT_tangent_constraint, ALLSET_OT_remove_constraint_target,
           ALLSET_OT_set_constraint_rest, ALLSET_OT_modify_constraint_axes)
