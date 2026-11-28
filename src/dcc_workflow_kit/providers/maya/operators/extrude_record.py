# SPDX-License-Identifier: GPL-3.0-or-later
"""The last kit modeling node per object (``Record``; ``RECORDS``, Delete History's ``PARKED``, object-mode ``SHOWN``),
its saved mesh states and the checks that the mesh is still its result (``current`` in edit mode, ``object_record`` in
object mode, ``caps_selected``); ``keep`` / ``park`` / ``clear`` and the undo / redo handlers.
Related: extrude_rebuild.py (runs a node), model_history.py (persistent chain), extrude.py.
"""

import hashlib

import bmesh
import bpy

from . import units
from .extrude_face import _key
from .extrude_spec import FACE


def selection_signature(bm):
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    return (tuple(v.index for v in bm.verts if v.select), tuple(e.index for e in bm.edges if e.select),
            tuple(f.index for f in bm.faces if f.select))


# --- the record ------------------------------------------------------------------------------------

class Record:
    """The last kit extrusion on one object."""

    def __init__(self, name, pre, params, spec=None):
        self.name = name            # polyExtrudeFaceN (polyExtrudeEdgeN, polyExtrudeVertexN, polyBevelN)
        self.spec = spec or FACE    # which Maya node
        self.pre = pre              # BMesh copy before the extrusion
        self.params = dict(params)
        self.cap_verts = []         # vertex indices whose positions identify the kit's state
        self.sel = None             # selection signature the operation left (not FACE)
        self.topology = None        # (divisions, together) of ``moved``
        self.moved = []             # [(vertex index, P0, T, L, O, X, Y, SX, SY, SZ)]
        self.cap_faces = []         # face indices
        self.states = []            # [(params, signature, selection signature, whole-mesh coordinate hash)]
        self.live = False           # a drag is previewing values
        self.mesh_uid = None        # session_uid of the mesh it was made on
        self.dismissed = False      # Q/W/E/R picked a tool since: Maya shows that tool's manipulator (#80)
        self.preview_data = None
        self.fast_preview = False
        self.history_id = None
        self.history_token = None
        self.input_snapshot = None
        self.input_hash = None

    def free(self):
        self.preview_data = None
        self.moved.clear()
        self.states.clear()
        self.cap_verts.clear()
        self.cap_faces.clear()
        self.sel = None
        self.live = self.fast_preview = False
        if self.pre is not None:
            self.pre.free()
            self.pre = None
        if self.input_snapshot is not None:
            bpy.data.meshes.remove(self.input_snapshot)
            self.input_snapshot = None


RECORDS = {}   # object name -> Record
# Delete History drops an object's record; Maya's undo brings the node back (redo drops it again). Delete
# History doesn't change the mesh, so the parked record is valid again after the undo (its signature still matches).
PARKED = {}    # object name -> Record dropped by Delete History
# Object mode: T (Show Manipulator Tool) shows the In-View Editor / manipulator of this object's input node without
# leaving object mode, like Maya (so does Bevel run on an object selection); Q / W / E / R (``dismiss``) end it.
# {"ob": object name} or empty.
SHOWN = {}


def park(name):
    """Delete History: the object's record leaves the Channel Box but stays for an undo. Returns it (or None)."""
    rec = RECORDS.pop(name, None)
    from . import model_history
    model_history.drop(bpy.data.objects.get(name))
    if rec is not None:
        old = PARKED.pop(name, None)
        if old is not None and old is not rec:
            old.free()
        if rec.history_id is not None:
            rec.free()  # Native Undo restores the persistent recipe and its input mesh.
            return rec
        PARKED[name] = rec
    return rec


@bpy.app.handlers.persistent
def _on_undo(*_args):
    from . import model_history
    model_history.invalidate()
    for name, rec in PARKED.items():
        RECORDS.setdefault(name, rec)


@bpy.app.handlers.persistent
def _on_redo(*_args):
    from . import model_history
    model_history.invalidate()
    for name, rec in PARKED.items():
        if RECORDS.get(name) is rec:
            del RECORDS[name]


def keep(context, ob, rec):
    """Remember ``rec`` as the object's history node, unless Maya's Construction History is off (Status Line
    toggle): Maya's menu commands then run without construction history and leave no polyExtrude / polyBevel
    node (Maya's Construction History)."""
    from . import prim_history
    if prim_history.history_on(context):
        parked = PARKED.pop(ob.name, None)          # a new node: the dropped one can't come back any more
        if parked is not None and parked is not RECORDS.get(ob.name) and parked is not rec:
            parked.free()
        RECORDS[ob.name] = rec
        from . import model_history
        model_history.append(ob, rec, units.maya_unit(context.scene))
        return
    rec.free()
    RECORDS.pop(ob.name, None)
    from . import model_history
    model_history.drop(ob)


def clear():
    for rec in {id(r): r for r in (*RECORDS.values(), *PARKED.values())}.values():
        rec.free()
    RECORDS.clear()
    PARKED.clear()
    SHOWN.clear()
    from . import model_history
    model_history.clear()


def signature(bm, cap_verts):
    bm.verts.ensure_lookup_table()
    if any(i >= len(bm.verts) for i in cap_verts):
        return None
    return (len(bm.verts), len(bm.faces), tuple(cap_verts), tuple(_key(bm.verts[i].co) for i in cap_verts))


def _store(rec, bm, caps, moved, params, full_hash=None):
    rec.fast_preview = False
    bm.verts.index_update()
    bm.faces.index_update()
    rec.params = dict(params)
    rec.topology = (params["divisions"], params["keep_faces_together"])
    rec.moved = [(v.index, p0, *vecs) for v, p0, *vecs in moved]
    rec.cap_faces = [f.index for f in caps]
    cap_verts = sorted({v.index for f in caps for v in f.verts})
    rec.cap_verts = cap_verts
    rec.states.append((dict(params), signature(bm, cap_verts), None,
                       coords_hash(bm) if full_hash is None else full_hash))
    del rec.states[:-64]
    rec.live = False


def _store_generic(rec, bm, tracked, params, full_hash=None, preview_data=None):
    bm.verts.index_update()
    rec.params = dict(params)
    rec.preview_data = preview_data if preview_data is not None else getattr(tracked, 'preview_data', None)
    rec.fast_preview = False
    rec.cap_verts = sorted({v.index for v in tracked if v.is_valid})
    rec.cap_faces = []
    rec.sel = selection_signature(bm)
    rec.states.append((dict(params), signature(bm, rec.cap_verts), rec.sel,
                       coords_hash(bm) if full_hash is None else full_hash))
    del rec.states[:-64]
    rec.live = False


def current(ob):
    """The valid record of ``ob`` (its mesh equals a state the kit made), with that state's values; else None."""
    if ob is None or ob.type != 'MESH' or ob.mode != 'EDIT':
        return None
    from . import model_history
    rec = model_history.ensure(ob)
    if rec is None or rec.pre is None or rec.mesh_uid != ob.data.session_uid:
        return None
    if rec.live:
        return rec
    bm = bmesh.from_edit_mesh(ob.data)
    for params, sig, sel, *_full in reversed(rec.states):
        if rec.history_id and params != rec.params:
            continue
        cap_verts = list(sig[2]) if sig else []
        if sig is not None and signature(bm, cap_verts) == sig:
            if rec.spec is not FACE:
                rec.params, rec.cap_verts, rec.sel = dict(params), cap_verts, sel
                return rec
            if params != rec.params or cap_verts != getattr(rec, "cap_verts", None):
                rec.params = dict(params)
                rec.topology = None          # ``moved`` belongs to another state: the next drag rebuilds
                rec.cap_verts = cap_verts
                rec.cap_faces = _cap_faces(bm, cap_verts)
            return rec
    return None


def coords_hash(bm):
    """Persistent native geometry signature, including connectivity and authored corner data."""
    mesh = bpy.data.meshes.new('.allset_signature')
    try:
        bm.to_mesh(mesh)
        return mesh_coords_hash(mesh)
    finally:
        bpy.data.meshes.remove(mesh)


def mesh_coords_hash(me):
    import numpy as np
    digest = hashlib.blake2b(digest_size=16)
    for collection, name, width, dtype in (
            (me.vertices, 'co', 3, np.float32), (me.edges, 'vertices', 2, np.int32),
            (me.loops, 'vertex_index', 1, np.int32), (me.polygons, 'loop_start', 1, np.int32),
            (me.polygons, 'loop_total', 1, np.int32), (me.polygons, 'material_index', 1, np.int32),
            (me.polygons, 'use_smooth', 1, np.bool_), (me.edges, 'use_edge_sharp', 1, np.bool_)):
        values = np.empty(width*len(collection), dtype=dtype)
        collection.foreach_get(name, values)
        if name == 'vertices':
            values.reshape((-1, 2)).sort(axis=1)  # An edge's endpoint order is not topology.
        digest.update((name+str(len(collection))).encode())
        digest.update(values)
    for layer in sorted(me.uv_layers, key=lambda item: item.name):
        digest.update(layer.name.encode())
        values = np.empty(2*len(layer.data), dtype=np.float32)
        layer.data.foreach_get('uv', values)
        digest.update(values)
    for layer in sorted(me.color_attributes, key=lambda item: item.name):
        digest.update((layer.name+layer.domain).encode())
        values = np.empty(4*len(layer.data), dtype=np.float32)
        layer.data.foreach_get('color', values)
        digest.update(values)
    return digest.hexdigest()


def mesh_signature(me, cap_verts):
    """``signature`` read from an object-mode Mesh (same vertex order as the edit-mode BMesh it was written from)."""
    verts = me.vertices
    if any(i >= len(verts) for i in cap_verts):
        return None
    return (len(verts), len(me.polygons), tuple(cap_verts), tuple(_key(verts[i].co) for i in cap_verts))


def mesh_state_ok(ob, rec):
    """The object-mode mesh of ``ob`` equals a state the kit made for ``rec`` (the edit-mode rule of ``current``);
    takes that state's values."""
    me = ob.data
    full = None
    for params, sig, sel, *rest in reversed(rec.states):
        if rec.history_id and params != rec.params:
            continue
        if sig is None:
            continue
        cap_verts = list(sig[2])
        if mesh_signature(me, cap_verts) != sig:
            continue
        if full is None:
            full = mesh_coords_hash(me)
        if rest and rest[0] != full:        # object mode checks every vertex (cheap there)
            continue
        if rec.spec is not FACE:
            rec.params, rec.cap_verts, rec.sel = dict(params), cap_verts, sel
        elif params != rec.params or cap_verts != getattr(rec, "cap_verts", None):
            rec.params = dict(params)
            rec.topology = None
            rec.cap_verts = cap_verts
            s = set(cap_verts)
            rec.cap_faces = [p.index for p in me.polygons if all(v in s for v in p.vertices)]
        return True
    return False


def object_record(ob):
    """The record of ``ob`` in object mode, else None. Maya lists a mesh's history nodes in object mode too: a kit
    node shows (and can be edited) there while the mesh is still the result the kit made (UV > Automatic checks its
    UVs instead)."""
    if not isinstance(ob, bpy.types.Object) or ob.type != 'MESH' or ob.mode == 'EDIT':   # a pose bone lead too
        return None
    from . import model_history
    rec = model_history.ensure(ob)
    if rec is None or rec.pre is None or rec.mesh_uid != ob.data.session_uid:
        return None
    if rec.live:
        return rec
    check = rec.spec.object_check or mesh_state_ok
    return rec if check(ob, rec) else None


def _cap_faces(bm, cap_verts):
    s = set(cap_verts)
    bm.faces.ensure_lookup_table()
    return [f.index for f in bm.faces if f.verts and all(v.index in s for v in f.verts)]


def caps_selected(ob, rec):
    """Maya's extrude manipulator / In-View Editor stay while the extruded faces are the selection (edge / vertex
    extrusion, bevel: while the selection is the one the operation left)."""
    bm = bmesh.from_edit_mesh(ob.data)
    selected = (None, None, rec.cap_faces) if rec.spec is FACE else rec.sel
    if selected is None or (rec.spec is FACE and not rec.cap_faces):
        return False
    return _selection_matches(ob, bm, selected)


def _selection_matches(ob, bm, selected):
    if selected is None:
        return False
    for sequence, indices, count in zip((bm.verts, bm.edges, bm.faces), selected,
                                        ('total_vert_sel', 'total_edge_sel', 'total_face_sel')):
        if indices is None:
            continue
        if getattr(ob.data, count) != len(indices):
            return False
        sequence.ensure_lookup_table()
        if any(index >= len(sequence) or not sequence[index].select for index in indices):
            return False
    return True


def active(context):
    """(object, record) of the active edit object when its last extrusion can be edited."""
    ob = context.edit_object if context is not None else None
    rec = current(ob)
    return (ob, rec) if rec is not None else (None, None)


def dismiss(context):
    """Maya: picking a tool (Q / W / E / R) after an extrusion swaps the extrude manipulator and In-View Editor for
    that tool's manipulator; the node stays in Channel Box INPUTS (issue #80). It also ends what T showed in object
    mode. True when one was showing."""
    shown = bool(SHOWN)
    SHOWN.clear()
    _ob, rec = active(context)
    if rec is None or rec.dismissed:
        return shown
    rec.dismissed = True
    return True


def next_name(scene, spec=None):
    spec = spec or FACE
    n = int(scene.get(spec.counter, 0)) + 1
    scene[spec.counter] = n
    return f"{spec.node}{n}"


def _pre_signature(bm):
    return (len(bm.verts), len(bm.edges), len(bm.faces)) + selection_signature(bm)


def _uv_signature(bm):
    uv = bm.loops.layers.uv.active
    if uv is None:
        return None
    return hash(tuple(round(c, 7) for f in bm.faces for lp in f.loops for c in lp[uv].uv))


def kind_of(bm, select_mode):
    """Which Maya extrusion the selection asks for: the select mode first (Maya extrudes the selected
    component type), then whatever is selected."""
    sv, se, sf = select_mode
    has = {'FACE': any(f.select for f in bm.faces), 'EDGE': any(e.select for e in bm.edges),
           'VERTEX': any(v.select for v in bm.verts)}
    for kind, on in (('FACE', sf), ('EDGE', se), ('VERTEX', sv)):
        if on and has[kind]:
            return kind
    return next((k for k in ('FACE', 'EDGE', 'VERTEX') if has[k]), None)
