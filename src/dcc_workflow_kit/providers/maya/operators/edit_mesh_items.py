# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Edit Mesh > Detach, Edit Edge Flow and Wedge as bmesh edits in Edit Mode.

``detach`` splits vertices per face or edges open, ``edit_edge_flow`` moves each vertex of the selected edges to the
middle of the curve through its ring neighbours, ``edge_flow`` places each vertex on such a curve at its own position
between them (edge_loops), ``ALLSET_OT_wedge`` spins the selected faces around an edge. menu_items
re-exports them.
"""

import math

import bmesh
import bpy
from bpy.props import FloatProperty, IntProperty
from mathutils import Vector


# --- Edit Mesh > Detach / Edit Edge Flow / Wedge ----------------------------------------------

def _edit_bm(context):
    ob = context.edit_object
    return ob, bmesh.from_edit_mesh(ob.data)


def detach(bm, mode):
    """Maya Detach of vertices (each face around a selected vertex gets its own vertex) or edges (split
    open). Returns how many elements were detached."""
    if mode == 'VERT':
        verts = [v for v in bm.verts if v.select and len(v.link_faces) > 1]
        for v in verts:
            bmesh.utils.vert_separate(v, list(v.link_edges))
        return len(verts)
    if mode == 'EDGE':
        edges = [e for e in bm.edges if e.select and not e.is_boundary]
        if edges:
            bmesh.ops.split_edges(bm, edges=edges)
        return len(edges)
    return 0


class ALLSET_OT_detach(bpy.types.Operator):
    """Detach the selected components: vertices split per face, edges split open, faces become their own
    shell (Maya Edit Mesh > Detach)"""
    bl_idname = "allset.detach"
    bl_label = "Detach"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        ob, bm = _edit_bm(context)
        mode = context.tool_settings.mesh_select_mode
        if mode[2]:
            if not any(f.select for f in bm.faces):
                self.report({'WARNING'}, "No vertices or edges selected to detach.")
                return {'CANCELLED'}
            bpy.ops.mesh.split()
            return {'FINISHED'}
        n = detach(bm, 'VERT' if mode[0] else 'EDGE')
        if not n:
            self.report({'WARNING'}, "No vertices or edges selected to detach.")   # Maya's warning
            return {'CANCELLED'}
        bmesh.update_edit_mesh(ob.data)
        return {'FINISHED'}


def _across(v, e, border=False):
    """The edge of ``v`` opposite ``e`` in a 4-edge vertex (the next edge of the ring), or None. With ``border``, a
    border edge ``e`` at a 3-edge border vertex continues along the other border edge."""
    if border and len(v.link_edges) == 3 and e.is_boundary:
        others = [x for x in v.link_edges if x is not e and x.is_boundary]
        return others[0] if len(others) == 1 else None
    if len(v.link_edges) != 4:
        return None
    faces = set(e.link_faces)
    others = [x for x in v.link_edges if x is not e and not (set(x.link_faces) & faces)]
    return others[0] if len(others) == 1 else None


def _ring_ends(v, selected):
    """((a, a2), (b, b2)) for vertex ``v`` of the selected edges: its two ring neighbours (along the edges not
    selected) and the vertex beyond each one along the ring (None at a pole or a border corner), or None when ``v``
    has not exactly two ring edges."""
    ring = [x for x in v.link_edges if x not in selected]
    if len(ring) != 2:
        return None
    ends = []
    for x in ring:
        a = x.other_vert(v)
        nxt = _across(a, x, border=True)
        ends.append((a.co.copy(), nxt.other_vert(a).co.copy() if nxt else None))
    return ends


def _flow_offset(a, a2, b, b2):
    """How far the middle of the flow curve between ``a`` and ``b`` lies from the middle of the straight edge: a
    cubic Hermite curve whose tangent at a runs along the ring edge coming into a from beyond (a2 -> a), at b along
    the edge going on from b (b -> b2), both 0.7 x |ab| long; a side with no edge beyond runs along ab itself."""
    chord = b - a
    if chord.length_squared < 1e-18:
        return None
    u = chord.normalized()
    ta = (a - a2).normalized() if a2 is not None and (a - a2).length_squared > 1e-18 else u
    tb = (b2 - b).normalized() if b2 is not None and (b2 - b).length_squared > 1e-18 else u
    return (ta - tb) * (0.7 * chord.length / 8.0)       # Hermite at t = 0.5: (a + b) / 2 + (ma - mb) / 8


def edge_flow(bm, edges, flow=1.0):
    """Insert / Offset Edge Loop with edge flow: each vertex of the new edges, at fraction t from ring neighbour a to
    b, moves off the straight edge by 4 t (1 - t) x ``flow`` x the flow curve's offset at the middle
    (``_flow_offset``): the full offset halfway, none at the ends. Returns the number of moved vertices."""
    selected = set(edges)
    moves = {}
    for v in {v for e in edges for v in e.verts}:
        ends = _ring_ends(v, selected)
        if ends is None:
            continue
        (a, a2), (b, b2) = ends
        da, db = (v.co - a).length, (v.co - b).length
        off = _flow_offset(a, a2, b, b2)
        if da + db < 1e-9 or off is None:
            continue
        t = da / (da + db)
        moves[v] = a.lerp(b, t) + off * (4.0 * t * (1.0 - t) * flow)
    for v, co in moves.items():
        v.co = co
    return len(moves)


def edit_edge_flow(bm, edges, flow=1.0):
    """Maya Edit Edge Flow: each vertex of the selected edges moves to the middle of the flow curve between its two
    ring neighbours (``_flow_offset``; a border edge continues along the border), the offset scaled by ``flow``
    (0 = the middle of the straight edge). Returns the number of moved vertices."""
    selected = set(edges)
    moves = {}
    for v in {v for e in edges for v in e.verts}:
        ends = _ring_ends(v, selected)
        if ends is None:
            continue
        (a, a2), (b, b2) = ends
        off = _flow_offset(a, a2, b, b2)
        if off is not None:
            moves[v] = (a + b) * 0.5 + off * flow
    for v, co in moves.items():
        v.co = co
    return len(moves)


class ALLSET_OT_edge_flow(bpy.types.Operator):
    """Move the selected edges so they follow the curvature of the surrounding surface
    (Maya Edit Mesh > Edit Edge Flow)"""
    bl_idname = "allset.edge_flow"
    bl_label = "Edit Edge Flow"
    bl_options = {'REGISTER', 'UNDO'}

    flow: FloatProperty(name="Edge Flow", default=1.0, soft_min=-1.0, soft_max=2.0,
                        description="Maya adjustEdgeFlow: 1 follows the curvature, 0 is straight")

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        for ob in context.objects_in_mode:
            bm = bmesh.from_edit_mesh(ob.data)
            edit_edge_flow(bm, [e for e in bm.edges if e.select], self.flow)
            bmesh.update_edit_mesh(ob.data)
        return {'FINISHED'}


def wedge(bm, faces, edge, angle, divisions):
    """Maya Wedge: sweep ``faces`` around ``edge`` by ``angle`` degrees in ``divisions`` steps, turning them toward
    their normal (90 degrees stands a face up on that edge). The hinge edge's vertices stay single; the sides of the
    sweep close as fans. The faces' old place opens into the mesh, except on a piece with no other faces, where it
    stays as the wedge's bottom. Object space, so the view doesn't matter. Returns the faces at the end of the sweep."""
    a, b = edge.verts[0].co.copy(), edge.verts[1].co.copy()
    axis = (b - a).normalized()
    normal = sum((f.normal for f in faces), Vector()).normalized()
    side = sum((f.calc_center_median() for f in faces), Vector()) / len(faces) - (a + b) / 2
    # a small turn about +axis moves the faces along axis x side: make that their normal side
    if axis.cross(side).dot(normal) < 0:
        axis = -axis
    sel = set(faces)
    alone = all(lf in sel for f in faces for e in f.edges for lf in e.link_faces)
    geom = list(set(faces)) + list({e for f in faces for e in f.edges}) + list({v for f in faces for v in f.verts})
    out = bmesh.ops.spin(bm, geom=geom, cent=(a + b) / 2, axis=axis, angle=math.radians(angle),
                         steps=max(1, int(divisions)), use_merge=False, use_duplicate=False)
    if alone:       # a piece with no other faces keeps its face under the wedge, turned to face out (closed)
        bmesh.ops.reverse_faces(bm, faces=[f for f in set(faces) if f.is_valid])
    else:
        bmesh.ops.delete(bm, geom=[f for f in set(faces) if f.is_valid], context="FACES_ONLY")
    on_hinge = [v for v in bm.verts if (v.co - a).length < 1e-5 or (v.co - b).length < 1e-5]
    bmesh.ops.remove_doubles(bm, verts=on_hinge, dist=1e-5)
    bm.normal_update()
    return [f for f in out["geom_last"] if isinstance(f, bmesh.types.BMFace) and f.is_valid]


def wedge_edge(bm, faces, ob=None):
    """The edge a Wedge turns about: the active edge, else an edge picked before the faces (kept across the switch
    to face mode, wedge_hinge), else a selected edge on the border of the selected faces."""
    from . import wedge_hinge
    return wedge_hinge.hinge_edge(ob, bm, faces)


class ALLSET_OT_wedge(bpy.types.Operator):
    """Sweep the selected faces around one of their edges (the active edge) (Maya Edit Mesh > Wedge)"""
    bl_idname = "allset.wedge"
    bl_label = "Wedge"
    bl_options = {'REGISTER', 'UNDO'}

    angle: FloatProperty(name="Wedge Angle", default=90.0, min=-360.0, max=360.0)
    divisions: IntProperty(name="Divisions", default=4, min=1, max=256)

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        ob, bm = _edit_bm(context)
        faces = [f for f in bm.faces if f.select]
        edge = wedge_edge(bm, faces, ob) if faces else None
        if not faces or edge is None:
            self.report({'WARNING'}, "No faces selected to wedge. Select faces and one or more edges from the "
                                     "selected faces to wedge about.")   # Maya's warning
            return {'CANCELLED'}
        last = wedge(bm, faces, edge, self.angle, self.divisions)
        from . import wedge_hinge
        wedge_hinge.clear(ob)
        for el in (*bm.verts, *bm.edges, *bm.faces):
            el.select = False
        for f in last:
            f.select = True
        bm.select_flush(True)
        bmesh.update_edit_mesh(ob.data)
        return {'FINISHED'}
