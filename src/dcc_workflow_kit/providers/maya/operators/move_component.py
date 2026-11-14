# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit Mesh > Transform (Maya's Transform Component): a polyMoveFace / polyMoveEdge / polyMoveVertex history node
on the selected components, editable afterwards like the kit's extrusions (operators/extrude.py records).

Like Maya: the node acts on the selected component type; its pivot is the centre of the selection's bounding box;
its local frame has Z = the selection's normal (faces: the face normals, edges: the mean normal of their faces,
vertices: the vertex normals) and X / Y = world X projected into that plane (the extrude manipulator's frame).
Translate / Rotate / Scale act in world space about the pivot; Local Translate X / Y move along the local axes,
Local Translate Z moves every vertex along its own normal (a vertex shared by several selected faces moves by the
mean of their normals); Local Rotate / Local Scale act in the local frame about the pivot (faces and edges only,
like Maya's polyMoveVertex). Random scales each vertex's move by a random amount. The menu item leaves the mesh as it
is and shows the manipulator (Local Translate / Local Scale handles; faces and edges also a rotate ring and a world /
local switch, ui/in_view.py), the In-View Editor and the node in Channel Box INPUTS. Order: local scale, local rotate,
local translate, then world scale, rotate and translate.
"""

import math
import random as _random

import bmesh
import bpy
from bpy.props import FloatProperty
from mathutils import Euler, Matrix, Vector

from .. import undo_steps
from . import extrude, units

AXES = ("x", "y", "z")
WORLD = tuple(f"{t}_{a}" for t in ("translate", "rotate", "scale") for a in AXES)
LOCAL_T = tuple(f"local_translate_{a}" for a in AXES)
LOCAL_RS = tuple(f"local_{t}_{a}" for t in ("rotate", "scale") for a in AXES)
FACE_FIELDS = WORLD + LOCAL_T + LOCAL_RS + ("random",)
VERTEX_FIELDS = WORLD + LOCAL_T + ("random",)
IN_VIEW = LOCAL_T + ("random",)
LABELS = {f: " ".join(w.capitalize() for w in f.split("_")) for f in FACE_FIELDS}
DEFAULTS = {f: (1.0 if "scale" in f else 0.0) for f in FACE_FIELDS}
NOTHING = "Select faces, edges or vertices to transform"


def _seed(index):
    return _random.Random(index * 7919 + 17).uniform(-1.0, 1.0)


def turned(degrees, axis, angle):
    """XYZ Euler ``degrees`` after a further turn of ``angle`` radians about ``axis`` (both in the same frame: the
    node's local frame for Local Rotate, world for Rotate) - what the manipulator's rotate rings do. Stays close to
    ``degrees`` (no jump of 360)."""
    start = Euler([math.radians(d) for d in degrees], 'XYZ')
    axis = Vector(axis)
    if axis.length < 1e-12 or not angle:
        return tuple(float(d) for d in degrees)
    m = Matrix.Rotation(angle, 3, axis.normalized()) @ start.to_matrix()
    return tuple(round(math.degrees(a), 4) for a in m.to_euler('XYZ', start))


def _pieces(bm, component):
    """(vertices, {vertex: its Local Translate Z direction}, the selection's normal) in mesh space."""
    bm.normal_update()
    per = {}
    if component == 'FACE':
        faces = [f for f in bm.faces if f.select]
        for f in faces:
            for v in f.verts:
                per.setdefault(v, []).append(f.normal.copy())
        total = sum((f.normal for f in faces), Vector())
    elif component == 'EDGE':
        edges = [e for e in bm.edges if e.select]
        total = Vector()
        for e in edges:
            z = extrude.edge_frame(e)[2]
            total += z
            for v in e.verts:
                per.setdefault(v, []).append(z)
    else:
        total = Vector()
        for v in bm.verts:
            if v.select:
                n = sum((f.normal for f in v.link_faces), Vector())
                n = n.normalized() if n.length > 1e-12 else Vector((0.0, 0.0, 1.0))
                per[v] = [n]
                total += n
    dirs = {v: sum(ns, Vector()) / len(ns) for v, ns in per.items()}
    normal = total.normalized() if total.length > 1e-9 else Vector((0.0, 0.0, 1.0))
    return list(dirs), dirs, normal


def move(bm, component, params, unit=1.0, matrix=None, direction=extrude.WORLD_X, fallback=extrude.MAYA_Z):
    """Maya polyMoveFace / polyMoveEdge / polyMoveVertex on the selection of ``bm`` (``component`` 'FACE' / 'EDGE' /
    'VERTEX'). ``matrix`` = the object's world matrix; ``direction`` / ``fallback`` = world X / Maya Z in mesh
    space. Lengths are Maya units (``unit`` = mesh length of one). Returns the moved vertices."""
    verts, dirs, normal = _pieces(bm, component)
    if not verts:
        return []
    g = lambda k: params.get(k, DEFAULTS[k])            # noqa: E731
    mw = matrix if matrix is not None else Matrix.Identity(4)
    inv = mw.inverted_safe()
    world = [mw @ v.co for v in verts]
    lo = Vector(tuple(min(p[i] for p in world) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in world) for i in range(3)))
    pivot_w = (lo + hi) / 2
    pivot = inv @ pivot_w
    x, y = extrude.face_axes(normal, direction, fallback)
    frame = Matrix((x, y, normal)).transposed()          # local -> mesh (columns X, Y, Z)
    local_rs = (frame @ Euler([g(f"local_rotate_{a}") * 3.141592653589793 / 180.0 for a in AXES], 'XYZ').to_matrix()
                @ Matrix.Diagonal([g(f"local_scale_{a}") for a in AXES]) @ frame.transposed())
    world_rs = (Euler([g(f"rotate_{a}") * 3.141592653589793 / 180.0 for a in AXES], 'XYZ').to_matrix()
                @ Matrix.Diagonal([g(f"scale_{a}") for a in AXES]))
    shift = Vector([g(f"translate_{a}") for a in AXES]) * unit
    lt_x, lt_y, lt_z = (g(f) * unit for f in LOCAL_T)
    rnd = g("random")
    for v in verts:
        p0 = v.co.copy()
        p = pivot + local_rs @ (p0 - pivot) + x * lt_x + y * lt_y + dirs[v] * lt_z
        pw = mw @ p
        pw = pivot_w + world_rs @ (pw - pivot_w) + shift
        p = inv @ pw
        if rnd:
            p = p0 + (p - p0) * (1.0 + rnd * _seed(v.index))
        v.co = p
    bm.normal_update()
    return verts


def _builder(component):
    def build(bm, params, unit, ob=None):
        axes = extrude.mesh_axes(ob) if ob is not None else {}
        return move(bm, component, params, unit, ob.matrix_world if ob is not None else None, **axes)
    return build


def _spec(kind, node, component, fields):
    return extrude.add_spec(extrude.Spec(
        kind, node, fields, {f: LABELS[f] for f in fields}, {f: DEFAULTS[f] for f in fields},
        {f: "NONE" for f in fields}, "local_translate_z", "transform_component_edit", _builder(component),
        with_object=True, view_fields=IN_VIEW, component=component, full_manip=True))


SPECS = {
    'FACE': _spec('MOVE_FACE', "polyMoveFace", 'FACE', FACE_FIELDS),
    'EDGE': _spec('MOVE_EDGE', "polyMoveEdge", 'EDGE', FACE_FIELDS),
    'VERTEX': _spec('MOVE_VERTEX', "polyMoveVertex", 'VERTEX', VERTEX_FIELDS),
}
EDIT_SPECS = set(SPECS.values())


class ALLSET_OT_transform_component(bpy.types.Operator):
    """Transform the selected faces, edges or vertices with history (Maya Edit Mesh > Transform): move, rotate and
    scale them along their normal with the manipulator, the In-View Editor or Channel Box INPUTS"""
    bl_idname = "allset.transform_component"
    bl_label = "Transform Component"
    bl_options = {'REGISTER', 'UNDO'}

    random: FloatProperty(name="Random", default=0.0, min=0.0, max=1.0,
                          description="Scale each vertex move by a random amount")

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}

    def execute(self, context):
        if context.mode != 'EDIT_MESH':
            self.report({'WARNING'}, NOTHING)
            return {'CANCELLED'}
        unit = units.maya_unit(context.scene)
        mode = tuple(context.scene.tool_settings.mesh_select_mode)
        done = 0
        for ob in context.objects_in_mode_unique_data:
            if ob.type != 'MESH':
                continue
            bm = bmesh.from_edit_mesh(ob.data)
            kind = extrude.kind_of(bm, mode)
            if kind is None:
                continue
            spec = SPECS[kind]
            params = {f: DEFAULTS[f] for f in spec.fields}
            params["random"] = self.random
            if extrude.record_new(context, ob, bm, spec, params, unit) is not None:
                done += 1
        if not done:
            self.report({'WARNING'}, NOTHING)
            return {'CANCELLED'}
        return {'FINISHED'}


def _edit_props():
    return {f: FloatProperty(name=LABELS[f], default=DEFAULTS[f], options={'SKIP_SAVE'},
                             description=LABELS[f] + (" (degrees)" if "rotate" in f else ""))
            for f in FACE_FIELDS}


class _EditProps:
    __annotations__ = _edit_props()


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_transform_component_edit(_EditProps, bpy.types.Operator):
    """Change the last Transform Component (Maya: edit the polyMoveFace / polyMoveEdge / polyMoveVertex node).
    Blender keeps no edit-mode history, so only the last one can be changed"""
    bl_idname = "allset.transform_component_edit"
    bl_label = "polyMoveFace"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}

    def _params(self, spec):
        return {f: getattr(self, f) for f in spec.fields}

    def execute(self, context):
        if context.mode == 'OBJECT':
            ok = extrude.edit_from_object_mode(context, "transform_component_edit", self._params)
            return {'FINISHED'} if ok else {'CANCELLED'}
        unit = units.maya_unit(context.scene)
        done = 0
        for ob in context.objects_in_mode_unique_data:
            rec = extrude.RECORDS.get(ob.name)
            if rec is not None and rec.spec in EDIT_SPECS and rec.pre is not None and (
                    rec.live or extrude.current(ob) is not None):
                done += bool(extrude.run(ob, rec, self._params(rec.spec), unit))
        if not done:
            self.report({'WARNING'}, "No Transform Component to change: " + extrude.NOTICE)
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (ALLSET_OT_transform_component, ALLSET_OT_transform_component_edit)
