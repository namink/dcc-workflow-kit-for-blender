# SPDX-License-Identifier: GPL-3.0-or-later
"""Which node the In-View Editor and the extrude manipulator show and edit: the edit object's last kit node, or in
object mode the node T showed (``target``, ``record``, ``object_node``; a primitive's creation node as ``CreationNode``),
where it sits (``cap_frame``) and the state both share (``_state``, ``_scale``, ``_redraw``).
Related: in_view.py (the box), extrude_manipulator.py, operators/extrude.py.
"""

import bmesh
import bpy
from mathutils import Vector

from . import creation_inputs
from ..operators import extrude, prim_history, prim_shapes


# hot = the selected row (yellow, the one MMB drags; the row under the pointer selects itself), hover = the row under
# the pointer, node = which node the rows belong to (a new one selects its first number row)
_state = {"hot": 0, "hover": -1, "node": None, "handle": None}


def _scale():
    return bpy.context.preferences.system.ui_scale


def _redraw(context):
    for area in context.screen.areas if context.screen else ():
        if area.type == 'VIEW_3D':
            area.tag_redraw()


# --- what is shown -----------------------------------------------------------------------------------

def creation_rows(node_type):
    """The In-View Editor rows of a creation node: its Channel Box values without the axis / pivot / normal /
    centre ones and the choice lists (polyCube: Width, Height, Depth, Subdivisions Width / Height / Depth).
    Height Baseline shows here for the Cylinder only."""
    return tuple(n for n in creation_inputs.node_rows(node_type)
                 if n not in creation_inputs.AXIS_ATTRS and prim_history.entry_kind(node_type, n) != "ENUM"
                 and (n != "heightBaseline" or node_type == "polyCylinder"))


class _CreationSpec:
    """The ``extrude_spec.Spec`` attributes the In-View Editor reads, for a creation node type: rows only, no
    manipulator."""
    arrow = None
    in_view = True
    component = None
    full_manip = False
    manip = ()

    def __init__(self, node_type):
        self.node = self.node_type = node_type
        self.view_fields = self.fields = creation_rows(node_type)
        self.labels = {n: prim_shapes.spec(node_type, n)[1] for n in self.fields}
        self.kinds = {n: prim_history.entry_kind(node_type, n) for n in self.fields}


class CreationNode:
    """A primitive's creation node (polyCube1 ...) as the In-View Editor shows it: ``name``, ``spec``, ``params``
    (Maya units / degrees, like the Channel Box)."""
    creation = True
    dismissed = False

    def __init__(self, ob, owner, node):
        self.ob, self.owner, self.node = ob, owner, node
        self.name = node["name"]
        self.spec = _CreationSpec(node["type"])
        self.params = prim_history.attrs(owner)

    def clamp(self, field, value):
        return prim_shapes.clamp(self.node["type"], field, value)

    def apply(self, context, changes):
        """Rebuild the shape with ``changes`` (no undo step); True when the node was still there."""
        values = prim_history.rebuild(context, self.ob, changes)
        if values is None:
            return False
        self.owner, self.node = prim_history.node_of(self.ob)
        self.params = dict(values)
        return True


def is_creation(rec):
    return getattr(rec, "creation", False)


def object_node(ob):
    """Object mode: the input node T shows for ``ob`` - the one picked in Channel Box INPUTS when the kit can show
    it, else the newest: the last kit operation (``extrude_record.object_record``), else the creation node. None when
    there is none."""
    nodes = []
    rec = extrude.object_record(ob)
    if rec is not None and rec.spec.in_view:
        nodes.append(rec)
    owner, node = prim_history.node_of(ob)
    if node is not None and creation_rows(node["type"]):
        nodes.append(CreationNode(ob, owner, node))
    if not nodes:
        return None
    from . import channel_box
    picked = channel_box.picked_node(ob)
    return next((n for n in nodes if picked == channel_box.history_node(n.name)), nodes[0])


def object_shown(context):
    """(object, node) T showed in object mode while that object is the selected active one, else (None, None)."""
    if getattr(context, "mode", None) != 'OBJECT' or not extrude.SHOWN:
        return None, None
    ob = getattr(context, "active_object", None)
    try:
        if ob is None or ob.name != extrude.SHOWN.get("ob") or not ob.select_get():
            return None, None
    except (ReferenceError, RuntimeError):
        return None, None
    node = object_node(ob)
    return (ob, node) if node is not None else (None, None)


def target(context):
    """(object, node) the In-View Editor and manipulator edit: the edit object's last kit node, or in object mode the
    node T showed; else (None, None)."""
    ob, rec = extrude.active(context)
    if rec is not None:
        return ob, rec
    return object_shown(context)


def record(context):
    """(object, record) when the manipulator / In-View Editor show in this 3D View, else (None, None). Object mode:
    the node T showed (a ``CreationNode`` for a creation node)."""
    space = getattr(context, "space_data", None)
    if space is None or space.type != 'VIEW_3D':
        return None, None
    from .toolbox import is_toolbox
    if is_toolbox(space):
        return None, None
    ob, rec = extrude.active(context)
    if rec is None:
        return object_shown(context)
    if rec.dismissed or not rec.spec.in_view or not extrude.caps_selected(ob, rec):
        return None, None
    return ob, rec


def manip_visible(context):
    return record(context)[1] is not None


def arrow_visible(context):
    rec = record(context)[1]
    return rec is not None and rec.spec.arrow is not None


def _pre_direction(rec):
    """Arrow direction of an edge / vertex extrusion or a bevel, from the mesh before it (cached)."""
    d = getattr(rec, "arrow_dir", None)
    if d is not None:
        return d
    pre = rec.pre
    d = Vector()
    if pre is not None:
        pre.normal_update()
        component = rec.spec.component or ('VERTEX' if rec.spec.kind == 'VERTEX' else 'EDGE')
        if component == 'FACE':
            for f in pre.faces:
                if f.select:
                    d += f.normal
        elif component == 'VERTEX':
            for v in pre.verts:
                if v.select:
                    d += sum((f.normal for f in v.link_faces), Vector()).normalized()
        else:
            for e in pre.edges:
                if e.select:
                    d += extrude.edge_frame(e)[2]
    rec.arrow_dir = d
    return d


def cap_frame(ob, rec):
    """(world centre, world unit normal, world length of one local unit along it) of the extruded faces (edge /
    vertex extrusion: the selection it left, the mean edge / vertex normal; bevel: the bevel's vertices). Object mode
    reads the mesh data (the selection the node left = its stored one); a creation node: the object's bounds centre."""
    if is_creation(rec):
        corners = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        return sum(corners, Vector()) / len(corners), Vector((0.0, 0.0, 1.0)), 1.0
    if ob.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(ob.data)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        all_verts, all_faces = bm.verts, bm.faces
        verts = [all_verts[i] for i in rec.cap_verts if i < len(all_verts)]
        if rec.spec is not extrude.FACE:
            verts = [v for v in all_verts if v.select] or verts
    else:
        all_verts, all_faces = ob.data.vertices, ob.data.polygons
        verts = [all_verts[i] for i in rec.cap_verts if i < len(all_verts)]
        if rec.spec is not extrude.FACE and rec.sel is not None:
            verts = [all_verts[i] for i in rec.sel[0] if i < len(all_verts)] or verts
    faces = [all_faces[i] for i in rec.cap_faces if i < len(all_faces)]
    if not verts:
        return None
    centre = sum((v.co for v in verts), Vector()) / len(verts)
    n = sum((f.normal for f in faces), Vector()) if rec.spec is extrude.FACE else _pre_direction(rec).copy()
    n = n.normalized() if n.length > 1e-9 else Vector((0, 0, 1))
    mw = ob.matrix_world
    nw = mw.to_3x3() @ n
    k = nw.length or 1.0
    return mw @ centre, nw / k, k
