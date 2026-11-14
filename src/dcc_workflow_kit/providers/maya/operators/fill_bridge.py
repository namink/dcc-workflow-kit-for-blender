# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesh > Fill Hole and Edit Mesh > Bridge with Maya's selection rules (#337).

Fill Hole closes every hole whose border edges are selected with one n-gon, whatever the number of edges around it;
with no edge selected (or the object selected) every hole of the mesh is closed. Bridge (``allset.bridge``,
operators/poly_attribute_nodes.py) joins two sets of border edges (or faces) as a polyBridgeEdge node; a selection
that is exactly one closed loop of border edges is filled with a single face instead, without divisions, like
Maya's Bridge (``fill_single_loops``). Every caller (menus, marking menus, shelf, Modeling Toolkit, option window)
runs these two operators.
"""

import bmesh
import bpy

# Maya's error for a Bridge selection that is not two sets of border edges
BRIDGE_WARNING = ("Invalid selection : polyBridgeEdge requires equal number of border edges to be selected "
                  "for source and target selection.")
NO_HOLE = "No hole to fill: select the border edges of a hole, or the object to fill every hole."


def one_closed_loop(edges):
    """True if ``edges`` are exactly one closed loop: every vertex on two of them and all of them connected."""
    edges = list(edges)
    if len(edges) < 3:
        return False
    degree = {}
    for e in edges:
        for v in e.verts:
            degree[v] = degree.get(v, 0) + 1
    if len(degree) != len(edges) or any(d != 2 for d in degree.values()):
        return False
    members = set(edges)
    seen, stack = set(), [edges[0].verts[0]]
    while stack:
        v = stack.pop()
        if v in seen:
            continue
        seen.add(v)
        stack.extend(e.other_vert(v) for e in v.link_edges if e in members)
    return len(seen) == len(degree)


def fill_holes(bm, edges):
    """One n-gon over every closed loop of border edges among ``edges``; the new faces are selected. Returns them."""
    border = [e for e in edges if e.is_boundary]
    if not border:
        return []
    faces = bmesh.ops.holes_fill(bm, edges=border, sides=0)["faces"]
    for f in faces:
        f.select_set(True)
    return faces


def _selected_edges(bm):
    return [e for e in bm.edges if e.select]


class ALLSET_OT_fill_hole(bpy.types.Operator):
    """Close every hole whose border edges are selected with one face; with nothing selected, every hole of the
    mesh (Maya Mesh > Fill Hole)"""
    bl_idname = "allset.fill_hole"
    bl_label = "Fill Hole"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        meshes = [(ob, bmesh.from_edit_mesh(ob.data)) for ob in context.objects_in_mode]
        picked = {ob: _selected_edges(bm) for ob, bm in meshes}
        every = not any(picked.values())          # no border edge picked: every hole, like an object selection
        total = 0
        for ob, bm in meshes:
            faces = fill_holes(bm, bm.edges if every else picked[ob])
            if faces:
                bm.select_flush_mode()
                bmesh.update_edit_mesh(ob.data)
                total += len(faces)
        if not total:
            self.report({'WARNING'}, NO_HOLE)
            return {'CANCELLED'}
        return {'FINISHED'}


def _counts(objects):
    return [(len(bm.verts), len(bm.edges), len(bm.faces))
            for bm in (bmesh.from_edit_mesh(ob.data) for ob in objects)]


def native_bridge(objects, others, divisions, offset):
    """Blender's Bridge Edge Loops on ``objects`` only (a selection the polyBridgeEdge node does not take, such as
    two faces whose borders are already joined, or more than two loops); the selection of ``others`` is set aside
    meanwhile. True when it changed a mesh."""
    kept = {}
    for ob in others:
        bm = bmesh.from_edit_mesh(ob.data)
        kept[ob] = [[e.index for e in seq if e.select] for seq in (bm.verts, bm.edges, bm.faces)]
        for seq in (bm.faces, bm.edges, bm.verts):
            for e in seq:
                e.select = False
        bmesh.update_edit_mesh(ob.data)
    before = _counts(objects)
    try:
        bpy.ops.mesh.bridge_edge_loops(number_cuts=divisions, twist_offset=offset)
    finally:
        for ob, picked in kept.items():
            bm = bmesh.from_edit_mesh(ob.data)
            for seq, indices in zip((bm.verts, bm.edges, bm.faces), picked):
                seq.ensure_lookup_table()
                for i in indices:
                    seq[i].select = True
            bmesh.update_edit_mesh(ob.data)
    return _counts(objects) != before


def fill_single_loops(context):
    """Edit Mesh > Bridge on one closed loop of border edges: that loop is filled with a single face, without
    divisions, like Maya. Returns the names of the objects filled that way (the others are bridged)."""
    done = set()
    for ob in context.objects_in_mode:
        bm = bmesh.from_edit_mesh(ob.data)
        edges = _selected_edges(bm)
        if edges and all(e.is_boundary for e in edges) and one_closed_loop(edges):
            faces = fill_holes(bm, edges)
            if faces:
                bm.select_flush_mode()
                bmesh.update_edit_mesh(ob.data)
                done.add(ob.name)
    return done


classes = (ALLSET_OT_fill_hole,)
