# SPDX-License-Identifier: GPL-3.0-or-later
"""Smart Bevel (Maya 2027's Edit Mesh > Smart Bevel, a polySmartBevel history node).

The width is a length in scene units, never a fraction of the edges, and it is kept below what the edges around the
bevel allow (Limit Width), so a wide value on dense geometry does not collapse edges. The edges come from a filter:
the selected edges (default), every hard edge of the mesh, or every edge whose faces meet at the Filter Angle or more.
Output options: the bevel's border edges hard, the smoothing angle of the new edges, arcs welded within a tolerance.
Depth follows the kit's Bevel (1 round, 0 flat, -1 concave).

The geometry is the kit's bevel core (operators/bevel_maya.py) with these options: Maya 2027's surface-following
cut, cutback relaxation and isolated-arc removal are not reproduced.
"""

import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty

from .. import undo_steps
from . import bevel_maya, extrude

NODE = "polySmartBevel"
FILTERS = (('SELECTED', "Selected Edges", "Bevel only the selected edges"),
           ('HARD', "Hard Edges", "Bevel every hard edge of the mesh"),
           ('ANGLE', "Edges by Angle", "Bevel every edge whose faces meet at the Filter Angle or more"))
FILTER_LABELS = {k: label for k, label, _d in FILTERS}
FILTER_KEYS = {label: k for k, label, _d in FILTERS}
FIELDS = ("width", "segments", "depth", "limit_width", "set_border_hard", "smoothing_angle")
HIDDEN = ("filter", "filter_angle", "weld_opposing_arcs", "weld_all_arcs", "world_space")
LABELS = {"width": "Width", "segments": "Segments", "depth": "Depth", "limit_width": "Limit Width",
          "set_border_hard": "Set Border Edges To Hard", "smoothing_angle": "Smoothing Angle"}
DEFAULTS = {"width": 0.2, "segments": 1, "depth": 0.5, "limit_width": True, "set_border_hard": False,
            "smoothing_angle": bevel_maya.SMOOTHING_ANGLE, "filter": 'SELECTED', "filter_angle": 30.0,
            "weld_opposing_arcs": 0.0, "weld_all_arcs": 0.0, "world_space": True}
KINDS = {"width": "NONE", "segments": "INT", "depth": "NONE", "limit_width": "BOOL", "set_border_hard": "BOOL",
         "smoothing_angle": "NONE"}


def _props():
    return {
        "width": FloatProperty(name="Width", default=0.2, min=0.0, options={'SKIP_SAVE'},
                               description="Bevel width in scene units (not a fraction of the edges)"),
        "segments": IntProperty(name="Segments", default=1, min=1, soft_max=12, options={'SKIP_SAVE'},
                                description="Faces across the bevel"),
        "depth": FloatProperty(name="Depth", default=0.5, min=-1.0, max=1.0, options={'SKIP_SAVE'},
                               description="Roundness of the bevel: 1 round, 0 flat, -1 concave (Segments > 1)"),
        "limit_width": BoolProperty(name="Limit Width", default=True, options={'SKIP_SAVE'},
                                    description="Keep the width below what the edges around the bevel allow, so no "
                                                "edge collapses"),
        "filter": EnumProperty(name="Filter", items=FILTERS, default='SELECTED', options={'SKIP_SAVE'},
                               description="Which edges are bevelled"),
        "filter_angle": FloatProperty(name="Filter Angle", default=30.0, min=0.0, max=180.0, options={'SKIP_SAVE'},
                                      description="Edges by Angle: the smallest angle (degrees) between an edge's "
                                                  "faces that bevels it"),
        "set_border_hard": BoolProperty(name="Set Border Edges To Hard", default=False, options={'SKIP_SAVE'},
                                        description="The edges where the bevel meets the old faces are hard"),
        "smoothing_angle": FloatProperty(name="Smoothing Angle", default=30.0, min=0.0, max=180.0,
                                         options={'SKIP_SAVE'},
                                         description="New edges whose faces meet at more than this angle (degrees) "
                                                     "are hard, the others soft"),
        "weld_opposing_arcs": FloatProperty(name="Weld Opposing Arcs", default=0.0, min=0.0, options={'SKIP_SAVE'},
                                            description="Merge the bevel's vertices that lie within this distance "
                                                        "(scene units, 0 = off)"),
        "weld_all_arcs": FloatProperty(name="Weld All Arcs", default=0.0, min=0.0, options={'SKIP_SAVE'},
                                       description="Merge every vertex of the bevel within this distance (scene "
                                                   "units, 0 = off)"),
        "world_space": BoolProperty(name="World Space", default=True, options={'SKIP_SAVE'},
                                    description="Width in world units, ignoring the object's scale (off: in the "
                                                "object's own units)"),
    }


class _Props:
    __annotations__ = _props()


def params_of(op):
    return {k: getattr(op, k) for k in FIELDS + HIDDEN}


# --- geometry (bmesh only) -------------------------------------------------------------------------

def candidate_edges(bm, params):
    """The edges the filter picks: selected / hard / by face angle (border edges never, like the Bevel)."""
    kind = params.get("filter", 'SELECTED')
    two = [e for e in bm.edges if len(e.link_faces) == 2]
    if kind == 'HARD':
        return [e for e in two if bevel_maya.is_hard(e)]
    if kind == 'ANGLE':
        bm.normal_update()
        limit = math.radians(max(0.0, min(180.0, float(params.get("filter_angle", 30.0))))) - 1e-6
        return [e for e in two if e.calc_face_angle(0.0) >= limit]
    return [e for e in two if e.select]


def safe_width(edges, unit):
    """The widest bevel (scene units) the edges around ``edges`` allow: the kit's Fraction 1 base (the shortest
    perpendicular slide along a neighbouring edge, halved where both of its ends are used)."""
    return bevel_maya.slide_limit(edges) / unit if unit > 0.0 else 0.0


def effective_width(edges, params, unit):
    w = max(0.0, float(params.get("width", 0.2)))
    if params.get("limit_width", True):
        w = min(w, safe_width(edges, unit))
    return w


def weld(bm, made, distance):
    """Merge the bevel's vertices within ``distance`` (mesh units); returns the surviving vertices."""
    if distance <= 0.0 or not made:
        return made
    bmesh.ops.remove_doubles(bm, verts=[v for v in made if v.is_valid], dist=distance)
    return [v for v in made if v.is_valid]


def _key(co):
    return tuple(round(c, 6) for c in co)


def fresh_vertices(bm, made, old_keys):
    """The vertices at new positions: the bevel core also lists untouched corners of the faces it rebuilt."""
    return [v for v in made if v.is_valid and _key(v.co) not in old_keys]


def border_edges(bm, made):
    """The edges where the bevel's new faces meet the old ones (new face = every corner is a vertex of ``made``,
    the vertices at new positions)."""
    made_set = set(made)
    new_faces = {f for v in made for f in v.link_faces if all(x in made_set for x in f.verts)}
    out = []
    for f in new_faces:
        for e in f.edges:
            if len(e.link_faces) == 2 and sum(1 for lf in e.link_faces if lf in new_faces) == 1:
                out.append(e)
    return out


def harden_border(bm, made):
    for e in border_edges(bm, made):
        e.smooth = False
        for f in e.link_faces:
            f.smooth = True        # hardness shows as a sharp edge between smooth faces (like the Bevel)


def build(bm, params, unit, ob=None):
    """polySmartBevel on ``bm`` (edit-mode bmesh); returns the vertices it made (empty: nothing done)."""
    params = dict(params)
    if params.get("world_space", True):
        unit = unit / bevel_maya.world_scale(ob)
    edges = candidate_edges(bm, params)
    if not edges:
        return []
    w = effective_width(edges, params, unit)
    if w <= 0.0:
        return []
    old_keys = {_key(v.co) for v in bm.verts}
    made = bevel_maya.bevel_edges(
        bm, edges, offset_as_fraction=False, offset=w, segments=max(1, int(params.get("segments", 1))),
        depth=max(-1.0, min(1.0, float(params.get("depth", 0.5)))), unit=unit, chamfer=True,
        smoothing_angle=max(0.0, min(180.0, float(params.get("smoothing_angle", 30.0)))))
    if not made:
        return []
    tol = max(float(params.get("weld_opposing_arcs", 0.0)), float(params.get("weld_all_arcs", 0.0)))
    made = weld(bm, made, tol * unit)
    if params.get("set_border_hard", False):
        harden_border(bm, fresh_vertices(bm, made, old_keys))
    if made and getattr(ob, "type", None) == 'MESH' and bevel_maya._soft(bm):
        from . import display
        display.ensure_maya_normals(ob)      # Maya's smooth normals on the soft edges the bevel made
    return made


SPEC = extrude.add_spec(extrude.Spec(
    'SMART_BEVEL', NODE, FIELDS, LABELS, DEFAULTS, KINDS, "width", "smart_bevel_edit", build,
    hidden=HIDDEN, with_object=True, component='EDGE', view_fields=("width", "segments", "depth")))


# --- operators -------------------------------------------------------------------------------------

@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_smart_bevel(_Props, bpy.types.Operator):
    """Smart Bevel (Maya 2027): bevel the selected edges, the mesh's hard edges or its edges by angle by a width
    in scene units, kept below what the edges around allow; change Width, Segments, Depth afterwards in the In-View
    Editor or Channel Box INPUTS"""
    bl_idname = "allset.smart_bevel"
    bl_label = "Smart Bevel"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def invoke(self, context, event):
        return self.execute(context)       # at once, like the Bevel (Esc / no mouse keeps it)

    def execute(self, context):
        from . import units
        unit = units.maya_unit(context.scene)
        params = params_of(self)
        done = 0
        for ob in context.objects_in_mode_unique_data:
            if ob.type != 'MESH':
                continue
            bm = bmesh.from_edit_mesh(ob.data)
            if params["filter"] == 'SELECTED' and not any(e.select for e in bm.edges):
                continue
            if extrude.record_new(context, ob, bm, SPEC, params, unit) is not None:
                done += 1
        if not done:
            self.report({'WARNING'}, {"SELECTED": "Select edges or faces to bevel.",
                                      "HARD": "No hard edges to bevel.",
                                      "ANGLE": "No edges at the Filter Angle or more to bevel."}[params["filter"]])
            return {'CANCELLED'}
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_smart_bevel_edit(_Props, bpy.types.Operator):
    """Change the last Smart Bevel (Maya: edit the polySmartBevel node). Blender keeps no edit-mode history, so
    only the last one can be changed"""
    bl_idname = "allset.smart_bevel_edit"
    bl_label = "polySmartBevel"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}

    def invoke(self, context, event):
        _ob, rec = extrude.active(context)
        if rec is None:
            rec = extrude.object_record(getattr(context, "active_object", None))
        if rec is None or rec.spec.edit_op != "smart_bevel_edit":
            return {'CANCELLED'}
        for k, v in rec.params.items():
            if not self.properties.is_property_set(k):
                setattr(self, k, v)
        return self.execute(context)

    def execute(self, context):
        from . import units
        unit = units.maya_unit(context.scene)
        if context.mode == 'OBJECT':
            if extrude.edit_from_object_mode(context, "smart_bevel_edit", lambda _spec: params_of(self)):
                return {'FINISHED'}
            self.report({'WARNING'}, "No Smart Bevel to change: " + extrude.NOTICE)
            return {'CANCELLED'}
        done = 0
        for ob in context.objects_in_mode_unique_data:
            rec = extrude.RECORDS.get(ob.name)
            if rec is None or rec.pre is None or rec.spec.edit_op != "smart_bevel_edit" or (
                    not rec.live and extrude.current(ob) is None):
                continue
            if extrude.run(ob, rec, params_of(self), unit):
                done += 1
        if not done:
            self.report({'WARNING'}, "No Smart Bevel to change: " + extrude.NOTICE)
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (ALLSET_OT_smart_bevel, ALLSET_OT_smart_bevel_edit)
