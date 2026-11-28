# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya component-mode keys that need more than one Blender operator: Alt+D select none
(back to object mode), Ctrl+B bevel (Maya polyBevel3 at once, Chamfer Vertex in vertex mode),
Ctrl+F9-F11 convert selection and Delete / Backspace on components.

Alt+D = SelectNone (object selection mode, selection cleared); Ctrl+B = BevelPolygon, a Maya hotkey.
"""

import bmesh
import bpy

from .. import results
from .. import undo_steps

_MODES = {'VERT': (True, False, False), 'EDGE': (False, True, False), 'FACE': (False, False, True)}


class ALLSET_OT_select_none(bpy.types.Operator):
    """Clear the selection and go back to object mode (Maya Alt+D)"""
    bl_idname = "allset.select_none"
    bl_label = "Select None"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.view_layer is not None

    def execute(self, context):
        from . import joint_selection
        joint_selection.clear(context)
        if context.mode == 'EDIT_MESH':
            bpy.ops.mesh.select_all(action='DESELECT')
        if context.mode != 'OBJECT' and context.active_object is not None:
            bpy.ops.object.mode_set(mode='OBJECT')
        for ob in context.view_layer.objects:
            ob.select_set(False)
        context.view_layer.objects.active = None
        return {'FINISHED'}


def bevel_affect(select_mode):
    """Maya bevels vertices in vertex mode, edges otherwise (faces: their edges)."""
    return 'VERTICES' if tuple(select_mode) == (True, False, False) else 'EDGES'


def _bevel_props():
    from bpy.props import BoolProperty, FloatProperty, IntProperty
    return {
        "fraction": FloatProperty(name="Fraction", default=0.5, min=0.0, max=1.0, options={'SKIP_SAVE'},
                                  description="Bevel width as a fraction of the shortest edge it slides along"),
        "offset_as_fraction": BoolProperty(name="Offset As Fraction", default=True, options={'SKIP_SAVE'},
                                           description="Use Fraction (off: Offset in Maya units)"),
        "offset": FloatProperty(name="Offset", default=0.2, min=0.0, options={'SKIP_SAVE'},
                                description="Bevel width in Maya units when Offset As Fraction is off"),
        "segments": IntProperty(name="Segments", default=1, min=1, soft_max=12, options={'SKIP_SAVE'},
                                description="Faces across the bevel"),
        "depth": FloatProperty(name="Depth", default=1.0, min=-1.0, max=1.0, options={'SKIP_SAVE'},
                               description="Roundness of the bevel: 1 round, 0 flat, -1 inverted"),
        "chamfer": BoolProperty(name="Chamfer", default=True, options={'SKIP_SAVE'},
                                description="Cut the edge off (off: keep the old corner, the new points run along "
                                            "the two faces)"),
        "world_space": BoolProperty(name="World Space", default=True, options={'SKIP_SAVE'},
                                    description="Offset in world units, ignoring the object's scale (off: in the "
                                                "object's own units)"),
        "smoothing_angle": FloatProperty(name="Smoothing Angle", default=30.0, min=0.0, max=180.0,
                                         options={'SKIP_SAVE'},
                                         description="New edges whose faces meet at more than this angle (degrees) "
                                                     "are hard, the others soft"),
    }


class _BevelProps:
    __annotations__ = _bevel_props()


def _bevel_params(op):
    from .bevel_maya import BEVEL
    return {k: getattr(op, k) for k in BEVEL.fields + BEVEL.hidden}


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_bevel(_BevelProps, bpy.types.Operator):
    """Bevel the selection now (Maya Ctrl+B, polyBevel3): change Fraction, Segments, Depth in the In-View Editor or
    Channel Box INPUTS; in vertex mode Chamfer Vertex"""
    bl_idname = "allset.bevel"
    bl_label = "Bevel"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'EDIT_MESH':
            return True
        return context.mode == 'OBJECT' and any(o.type == 'MESH' for o in context.selected_objects)

    def invoke(self, context, event):
        # Maya bevels at once (no drag; Esc / no mouse keeps it): #16,
        return self.execute(context)

    def execute(self, context):
        from . import bevel_maya, extrude, units
        unit = units.maya_unit(context.scene)
        if context.mode == 'OBJECT':
            return self._objects(context, unit)
        chamfer = bevel_affect(context.scene.tool_settings.mesh_select_mode) == 'VERTICES'
        done = 0
        for ob in context.objects_in_mode_unique_data:
            if ob.type != 'MESH':
                continue
            bm = bmesh.from_edit_mesh(ob.data)
            if chamfer:
                if bevel_maya.chamfer_vertices(bm, [v for v in bm.verts if v.select]):
                    bmesh.update_edit_mesh(ob.data)
                    done += 1
                continue
            if not any(e.select for e in bm.edges):
                continue
            if extrude.record_new(context, ob, bm, bevel_maya.BEVEL, _bevel_params(self), unit) is not None:
                done += 1
        if not done:
            self.report({'WARNING'}, "Select edges or faces to bevel.")
            return {'CANCELLED'}
        return {'FINISHED'}

    def _objects(self, context, unit):
        """Maya on an object selection: every edge of each selected mesh, still in object mode, with the new
        polyBevel node in the In-View Editor."""
        from . import bevel_maya, extrude
        done, seen = [], set()
        for ob in context.selected_objects:
            if ob.type != 'MESH' or ob.data in seen:
                continue
            seen.add(ob.data)
            if extrude.record_object(context, ob, bevel_maya.BEVEL, _bevel_params(self), unit) is not None:
                done.append(ob)
        if not done:
            self.report({'WARNING'}, "Select edges or faces to bevel.")
            return {'CANCELLED'}
        view_layer = context.view_layer
        if view_layer.objects.active not in done:
            view_layer.objects.active = done[-1]
        extrude.SHOWN.clear()
        extrude.SHOWN["ob"] = view_layer.objects.active.name
        return {'FINISHED'}


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_bevel_edit(_BevelProps, bpy.types.Operator):
    """Change the last bevel (Maya: edit the polyBevel node). Blender keeps no edit-mode history, so only the last
    one can be changed"""
    bl_idname = "allset.bevel_edit"
    bl_label = "polyBevel"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}     # Maya edits history nodes in object mode too (#204)

    def invoke(self, context, event):
        from . import extrude
        _ob, rec = extrude.active(context)
        if rec is None:
            rec = extrude.object_record(getattr(context, "active_object", None))
        if rec is None or rec.spec.edit_op != "bevel_edit":
            return {'CANCELLED'}
        for k, v in rec.params.items():
            if not self.properties.is_property_set(k):
                setattr(self, k, v)
        return self.execute(context)

    def execute(self, context):
        from . import extrude, units
        unit = units.maya_unit(context.scene)
        if context.mode == 'OBJECT':
            if extrude.edit_from_object_mode(context, "bevel_edit", lambda _spec: _bevel_params(self)):
                return {'FINISHED'}
            self.report({'WARNING'}, "No bevel to change: " + extrude.NOTICE)
            return {'CANCELLED'}
        done = 0
        for ob in context.objects_in_mode_unique_data:
            rec = extrude.RECORDS.get(ob.name)
            if rec is None or rec.pre is None or rec.spec.edit_op != "bevel_edit" or (
                    not rec.live and extrude.current(ob) is None):
                continue
            if extrude.run(ob, rec, _bevel_params(self), unit):
                done += 1
        if not done:
            self.report({'WARNING'}, "No bevel to change: " + extrude.NOTICE)
            return {'CANCELLED'}
        return {'FINISHED'}


def touching(bm, select_mode, target):
    """Maya "Convert Selection to Vertices / Edges / Faces": the target elements touching
    the selection, read from the current component type (faces -> their edges / vertices;
    vertices -> the edges / faces using them). Blender's select_mode switch keeps only
    *contained* elements, which is Maya's separate "To Contained ..." (Ctrl+RMB menu), and
    ``use_expand=True`` clears the selection instead (4.5)."""
    sv, se, sf = select_mode
    if sf and not (sv or se):
        src = [f for f in bm.faces if f.select]
    elif se and not sv:
        src = [e for e in bm.edges if e.select]
    else:
        src = [v for v in bm.verts if v.select]
    out = set()
    for el in src:
        if target == 'VERT':
            out.update([el] if isinstance(el, bmesh.types.BMVert) else el.verts)
        elif target == 'EDGE':
            if isinstance(el, bmesh.types.BMEdge):
                out.add(el)
            else:
                out.update(el.edges if isinstance(el, bmesh.types.BMFace) else el.link_edges)
        else:
            out.update([el] if isinstance(el, bmesh.types.BMFace) else el.link_faces)
    return out


def select_only(bm, target, elements):
    for seq in (bm.verts, bm.edges, bm.faces):
        for el in seq:
            el.select_set(False)
    bm.select_mode = {target}
    for el in elements:
        el.select_set(True)
    bm.select_flush_mode()


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_convert_selection(bpy.types.Operator):
    """Convert the selection to the vertices, edges or faces it touches (Maya Ctrl+F9-F11)"""
    bl_idname = "allset.convert_selection"
    bl_label = "Convert Selection"
    bl_options = {'REGISTER', 'UNDO'}

    type: bpy.props.EnumProperty(name="To", items=(('VERT', "Vertices", "Maya Ctrl+F9"),
                                                   ('EDGE', "Edges", "Maya Ctrl+F10"),
                                                   ('FACE', "Faces", "Maya Ctrl+F11")))

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        ts = context.scene.tool_settings
        mode = tuple(ts.mesh_select_mode)
        # Read first: switching the select mode re-flushes the selection.
        found = []
        for ob in context.objects_in_mode_unique_data:
            bm = bmesh.from_edit_mesh(ob.data)
            found.append((ob, bm, touching(bm, mode, self.type)))
        ts.mesh_select_mode = _MODES[self.type]
        for ob, bm, elements in found:
            select_only(bm, self.type, elements)
            bmesh.update_edit_mesh(ob.data)
        return {'FINISHED'}


def delete_components(bm, mode):
    """Maya's Delete key on one mesh's selection; ``mode`` = 'FACE' / 'EDGE' / 'VERT'.

    Returns (deleted, skipped). Like Maya: faces go with their unused edges and vertices; edges between two faces
    go and the faces merge, every vertex stays (border edges are left alone); a vertex goes only when it has two
    edges (they become one), others stay. Edit Mesh > Delete Edge/Vertex (Ctrl+Delete, delete_edge_vertex_edges) is
    the one that also cleans up the vertices left with two edges and deletes vertices with their edges.
    """
    if mode == 'FACE':
        faces = [f for f in bm.faces if f.select]
        bmesh.ops.delete(bm, geom=faces, context='FACES')
        return len(faces), 0
    if mode == 'EDGE':
        sel = [e for e in bm.edges if e.select]
        inner = [e for e in sel if len(e.link_faces) == 2]
        if inner:
            bmesh.ops.dissolve_edges(bm, edges=inner, use_verts=False, use_face_split=False)
        return len(inner), len(sel) - len(inner)
    sel = [v for v in bm.verts if v.select]
    winged = [v for v in sel if len(v.link_edges) == 2]
    if winged:
        bmesh.ops.dissolve_verts(bm, verts=winged, use_face_split=False, use_boundary_tear=False)
    return len(winged), len(sel) - len(winged)


def delete_edge_vertex_edges(bm):
    """Edit Mesh > Delete Edge/Vertex on one mesh's selected edges, like Maya. Returns (deleted, kept edges).

    The selected edges go one at a time in index order. An edge with two faces goes (the faces merge); then each of
    its two end vertices that is left with two edges, and whose faces all keep four or more corners, is cleaned up
    so its two edges become one. That joined edge carries on as the higher-numbered of the two: if it was selected
    it is deleted in its turn, the lower-numbered one is gone. Border edges and their vertices stay. An edge whose
    two faces already share another edge can't go (the merged face would need a hole) and stays.
    """
    lay = bm.edges.layers.int.new("_allset_delete_id")
    bm.edges.index_update()
    by_id = {}
    for e in bm.edges:
        e[lay] = e.index
        by_id[e.index] = e
    order = sorted(e.index for e in bm.edges if e.select)
    pending = set(order)
    kept, deleted = [], 0
    for i in order:
        if i not in pending:
            continue
        pending.discard(i)
        e = by_id.get(i)
        if e is None or not e.is_valid:
            continue
        if len(e.link_faces) != 2:
            kept.append(e)
            continue
        ends = list(e.verts)
        bmesh.ops.dissolve_edges(bm, edges=[e], use_verts=False, use_face_split=False)
        if e.is_valid:
            kept.append(e)
            continue
        deleted += 1
        for v in ends:
            if not v.is_valid or len(v.link_edges) != 2 or any(len(f.verts) < 4 for f in v.link_faces):
                continue
            a, b = v.link_edges
            hi, lo = max(a[lay], b[lay]), min(a[lay], b[lay])
            o1, o2 = a.other_vert(v), b.other_vert(v)
            bmesh.ops.dissolve_verts(bm, verts=[v], use_face_split=False, use_boundary_tear=False)
            if v.is_valid:
                continue
            joined = next((x for x in o1.link_edges if x.other_vert(o1) is o2), None)
            pending.discard(lo)
            if joined is not None:
                joined[lay] = hi
                by_id[hi] = joined
    ends = [tuple(e.verts) for e in kept if e.is_valid]
    bm.edges.layers.int.remove(lay)         # this makes the edge references stale: find the kept edges again
    kept = [bm.edges.get(pair) for pair in ends]
    return deleted, [e for e in kept if e is not None]


class ALLSET_OT_delete_edge_vertex(bpy.types.Operator):
    """Delete the selected edges and clean up the vertices they leave with two edges, or delete the selected
    vertices (Maya Edit Mesh > Delete Edge/Vertex)"""
    bl_idname = "allset.delete_edge_vertex"
    bl_label = "Delete Edge/Vertex"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        if select_mode_kind(context.tool_settings) != 'EDGE':
            return bpy.ops.mesh.dissolve_mode()
        any_sel = False
        for ob in context.objects_in_mode_unique_data:
            if ob.type != 'MESH':
                continue
            bm = bmesh.from_edit_mesh(ob.data)
            if not any(e.select for e in bm.edges):
                continue
            any_sel = True
            _deleted, kept = delete_edge_vertex_edges(bm)
            for seq in (bm.verts, bm.edges, bm.faces):
                for el in seq:
                    el.select = False
            for e in kept:          # like Maya, edges that could not go stay selected
                e.select = True
            bm.select_flush(True)
            bmesh.update_edit_mesh(ob.data)
        if not any_sel:
            results.result(self, "No Vertices / Edges have been selected for Delete!")
            return {'CANCELLED'}
        return {'FINISHED'}


def select_mode_kind(ts):
    vert, edge, face = ts.mesh_select_mode
    return 'FACE' if face else 'EDGE' if edge else 'VERT'


class ALLSET_OT_delete_components(bpy.types.Operator):
    """Delete the selected faces, edges (non-border; their vertices stay) or two-edge vertices right away, by the
    select mode (Maya Delete on components)"""
    bl_idname = "allset.delete_components"
    bl_label = "Delete Components"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        mode = select_mode_kind(context.tool_settings)
        deleted = skipped = 0
        for ob in context.objects_in_mode_unique_data:
            if ob.type != 'MESH':
                continue
            bm = bmesh.from_edit_mesh(ob.data)
            d, s = delete_components(bm, mode)
            for seq in (bm.verts, bm.edges, bm.faces):
                for el in seq:
                    el.select = False
            bm.select_flush(False)
            bmesh.update_edit_mesh(ob.data)
            deleted, skipped = deleted + d, skipped + s
        if not deleted and not skipped:
            results.result(self, "Nothing selected")
            return {'CANCELLED'}
        return {'FINISHED'}       # like Maya, the selection is cleared even when nothing could go


class ALLSET_OT_select_loops(bpy.types.Operator):
    """Select the edge loops (or rings) of the selected edges (Maya Select > Contiguous Edges, Convert
    Selection > To Edge Loop / Ring)"""
    bl_idname = "allset.select_loops"
    bl_label = "Select Edge Loops"
    bl_options = {'REGISTER', 'UNDO'}

    ring: bpy.props.BoolProperty(name="Ring", description="Edge rings instead of edge loops")
    border: bpy.props.BoolProperty(
        name="Whole Border", options={'SKIP_SAVE'},
        description="A selected open-border edge takes in its whole border, round the corners too "
                    "(Maya Convert Selection > To Edge Loop)")

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        starts = {}
        if self.border and not self.ring:
            for ob in context.objects_in_mode_unique_data:
                bm = bmesh.from_edit_mesh(ob.data)
                starts[ob.name] = [e.index for e in bm.edges if e.select and e.is_boundary]
        # Blender 5.0: mesh.loop_multi_select(ring); 5.1+: mesh.select_edge_loop_multi /
        # select_edge_ring_multi (VIEW3D_MT_edit_mesh_select_loops).
        from .. import compat
        if compat.has_op(bpy.ops.mesh, "loop_multi_select"):
            res = bpy.ops.mesh.loop_multi_select(ring=self.ring)
        else:
            op = bpy.ops.mesh.select_edge_ring_multi if self.ring else bpy.ops.mesh.select_edge_loop_multi
            res = op()
        for ob in context.objects_in_mode_unique_data:
            if starts.get(ob.name):
                bm = bmesh.from_edit_mesh(ob.data)
                bm.edges.ensure_lookup_table()
                for e in border_run(bm.edges[i] for i in starts[ob.name]):
                    e.select_set(True)
                bmesh.update_edit_mesh(ob.data)
        return res


def border_run(edges):
    """The open-border edges joined to ``edges`` through vertices where exactly two border edges meet: a border
    edge's whole border loop, round its corners (Maya's edge loop of a border edge)."""
    seen, todo = set(), list(edges)
    while todo:
        e = todo.pop()
        if e in seen:
            continue
        seen.add(e)
        for v in e.verts:
            nxt = [o for o in v.link_edges if o is not e and o.is_boundary]
            if len(nxt) == 1:
                todo.append(nxt[0])
    return seen



def shrink_off_border(bm, mode):
    """After Blender's Shrink: Maya also lets go of the selected vertices on an open border of the mesh and of the
    selected faces that touch one (the mesh border counts as outside the selection). ``mode`` = 'VERT' / 'FACE'."""
    if mode == 'VERT':
        for v in bm.verts:
            if v.select and v.is_boundary:
                v.select_set(False)
    else:
        for f in bm.faces:
            if f.select and any(v.is_boundary for v in f.verts):
                f.select_set(False)
    bm.select_flush_mode()


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_grow_selection(bpy.types.Operator):
    """Grow the component selection by one step (Maya Select > Grow, >): vertices and faces take in every vertex
    or face that shares a face with the selection, edges every edge that shares a vertex with a selected edge"""
    bl_idname = "allset.grow_selection"
    bl_label = "Grow Selection"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        mode = tuple(context.scene.tool_settings.mesh_select_mode)
        return bpy.ops.mesh.select_more(use_face_step=mode != _MODES['EDGE'])


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_shrink_selection(bpy.types.Operator):
    """Shrink the component selection by one step (Maya Select > Shrink, <): the border of the selected region goes,
    and so do selected vertices and faces on an open border of the mesh"""
    bl_idname = "allset.shrink_selection"
    bl_label = "Shrink Selection"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        res = bpy.ops.mesh.select_less()
        kind = next((k for k in ('VERT', 'FACE') if tuple(context.scene.tool_settings.mesh_select_mode) == _MODES[k]),
                    None)
        if kind is not None and 'FINISHED' in res:
            for ob in context.objects_in_mode_unique_data:
                bm = bmesh.from_edit_mesh(ob.data)
                shrink_off_border(bm, kind)
                bmesh.update_edit_mesh(ob.data)
        return res


classes = (ALLSET_OT_select_none, ALLSET_OT_bevel, ALLSET_OT_bevel_edit, ALLSET_OT_convert_selection,
           ALLSET_OT_delete_components, ALLSET_OT_delete_edge_vertex, ALLSET_OT_select_loops,
           ALLSET_OT_grow_selection, ALLSET_OT_shrink_selection)
