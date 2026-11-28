# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Edit Mesh > Average Vertices: rounds the selected vertices without adding any (``average``), kept as an
editable ``polyAverageVertex`` history node whose Iterations (10 by default) the In-View Editor and Channel Box
INPUTS change afterwards. ``AVERAGE`` is its extrude_spec.Spec (made once, at import), ``allset.average_vertices``
records it, ``allset.average_vertices_edit`` changes it. Imported through poly_maya.py.
"""

import bmesh
import bpy
import numpy as np

from .. import undo_steps

ITERATIONS = 10
# Each pass moves a selected vertex to the average of its edge neighbours, then takes back part of that move: SHAPE
# blends the vertex's start position with its position before the pass, KEEP is how much of the vertex's own pull back
# applies (the rest comes from its neighbours' pulls). A sharp corner rounds off while flat areas barely move.
SHAPE = 0.5
KEEP = 0.7


def average(co, edges, selected, iterations=ITERATIONS):
    """Positions ``co`` (N x 3) after ``iterations`` passes over the ``selected`` vertices (N booleans); ``edges``
    (E x 2 vertex indices) give the neighbours. Unselected and unconnected vertices stay."""
    co = np.asarray(co, dtype=np.float64).reshape(-1, 3)
    n = len(co)
    edges = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
    a, b = edges[:, 0], edges[:, 1]
    count = np.bincount(a, minlength=n) + np.bincount(b, minlength=n)
    moving = np.asarray(selected, dtype=bool) & (count > 0)
    if not moving.any() or iterations <= 0:
        return co.copy()
    inv = 1.0 / np.maximum(count, 1)[:, None]

    def neighbours_mean(x):
        out = np.empty_like(x)
        for k in range(3):
            out[:, k] = np.bincount(a, x[b, k], n) + np.bincount(b, x[a, k], n)
        return out * inv

    start = co
    q = co.copy()
    for _ in range(int(iterations)):
        p = q.copy()
        p[moving] = neighbours_mean(q)[moving]
        pull = np.zeros_like(q)
        pull[moving] = p[moving] - (SHAPE * start[moving] + (1.0 - SHAPE) * q[moving])
        p[moving] += (1.0 - KEEP) * neighbours_mean(pull)[moving] - KEEP * pull[moving]
        q = p
    return q


def average_bmesh(bm, iterations=ITERATIONS):
    """Average the selected vertices of ``bm`` in place. Returns them (empty: nothing selected)."""
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    verts = [v for v in bm.verts if v.select and not v.hide]
    if not verts:
        return []
    co = np.array([v.co[:] for v in bm.verts], dtype=np.float64).reshape(-1, 3)
    edges = np.array([(e.verts[0].index, e.verts[1].index) for e in bm.edges], dtype=np.int64).reshape(-1, 2)
    selected = np.zeros(len(co), dtype=bool)
    selected[[v.index for v in verts]] = True
    new = average(co, edges, selected, iterations)
    for v in verts:
        v.co = new[v.index]
    bm.normal_update()
    return verts


def _build(bm, params, unit):
    return average_bmesh(bm, int(params["iterations"]))


def _average_spec():
    from . import extrude
    return extrude.add_spec(extrude.Spec(
        'AVERAGE', "polyAverageVertex", ("iterations",), {"iterations": "Iterations"}, {"iterations": ITERATIONS},
        {"iterations": "INT"}, None, "average_vertices_edit", _build))


AVERAGE = _average_spec()


class ALLSET_OT_average_vertices(bpy.types.Operator):
    """Move the selected vertices to round the shape without adding vertices (Maya Edit Mesh > Average Vertices):
    change its Iterations in the In-View Editor or Channel Box INPUTS (polyAverageVertex)"""
    bl_idname = "allset.average_vertices"
    bl_label = "Average Vertices"
    bl_options = {'REGISTER', 'UNDO'}

    iterations: bpy.props.IntProperty(name="Iterations", default=ITERATIONS, min=0, soft_max=100)

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        from . import extrude, units
        unit = units.maya_unit(context.scene)
        params = {"iterations": self.iterations}
        done = False
        for ob in context.objects_in_mode_unique_data:
            if ob.type != 'MESH':
                continue
            bm = bmesh.from_edit_mesh(ob.data)
            if extrude.record_new(context, ob, bm, AVERAGE, params, unit) is not None:
                done = True
            else:
                bmesh.update_edit_mesh(ob.data)
        if not done:
            self.report({'WARNING'}, "Nothing selected.")
            return {'CANCELLED'}
        return {'FINISHED'}


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_average_vertices_edit(bpy.types.Operator):
    """Change the last Average Vertices (Maya: edit the polyAverageVertex node). Blender keeps no history, so only
    the last one can be changed"""
    bl_idname = "allset.average_vertices_edit"
    bl_label = "polyAverageVertex"
    bl_options = {'REGISTER', 'UNDO'}

    iterations: bpy.props.IntProperty(name="Iterations", default=ITERATIONS, min=0, max=10000,
                                      options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}

    def execute(self, context):
        from . import extrude, units
        params = {"iterations": self.iterations}
        if context.mode == 'OBJECT':
            ok = extrude.edit_from_object_mode(context, "average_vertices_edit", lambda _spec: params)
            return {'FINISHED'} if ok else {'CANCELLED'}
        unit = units.maya_unit(context.scene)
        done = 0
        for ob in context.objects_in_mode_unique_data:
            rec = extrude.RECORDS.get(ob.name)
            if rec is not None and rec.spec is AVERAGE and rec.pre is not None and (
                    rec.live or extrude.current(ob) is not None):
                done += bool(extrude.run(ob, rec, params, unit))
        return {'FINISHED'} if done else {'CANCELLED'}
