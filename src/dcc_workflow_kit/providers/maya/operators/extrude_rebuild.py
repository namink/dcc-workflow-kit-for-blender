# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs a recorded node: a new node from the selection (``record_new``, ``record_object``), a rebuild with new values
from the mesh before it (``run``, ``run_object``, ``run_from_object_mode`` / ``edit_from_object_mode``) and drag
previews that only move vertices (``preview``, ``capture_preview``). Related: extrude_record.py, extrude.py.
"""

from uuid import uuid4

import bmesh
import bpy

from .. import compat
from . import units
from .extrude_face import extrude, mesh_axes, position, world_space
from .extrude_record import (RECORDS, Record, _pre_signature, _store, _store_generic, _uv_signature, keep,
                             mesh_coords_hash, mesh_signature, next_name, object_record)
from .extrude_spec import FACE


def restore_pre(bm, rec):
    """Put the mesh from before the extrusion back into ``bm`` (an edit-mode bmesh)."""
    restore_mesh(bm, rec.pre)


def restore_mesh(bm, source):
    """Restore a BMesh snapshot, including its custom data, after an edit or failed build."""
    me = bpy.data.meshes.new(".allset_pre")
    try:
        source.to_mesh(me)
        compat.refill_bmesh(bm, me)
    finally:
        bpy.data.meshes.remove(me)


def _rebuild(ob, rec, bm, params, unit):
    """Put the mesh before ``rec`` into ``bm`` and run ``rec``'s node on it with ``params``; True when it made
    something. An atomic node that fails leaves ``bm`` as it was and raises."""
    if rec.spec is not FACE:
        rollback = bpy.data.meshes.new('.allset_preview') if rec.spec.atomic else None
        full_hash = None
        try:
            if rollback is not None:
                bm.to_mesh(rollback)
            try:
                restore_pre(bm, rec)
                values = {k: params[k] for k in rec.spec.fields + rec.spec.hidden if k in params}
                values['_history_id'] = rec.history_id
                tracked = rec.spec.build(bm, values, unit, **({"ob": ob} if rec.spec.with_object else {}))
                from . import history_references
                history_references.tag_generic(bm, rec.spec, params, rec.history_id, tracked)
                if rec.spec.atomic and not tracked:
                    raise ValueError('The attributes do not produce a valid '+rec.spec.node_type)
            except Exception:
                if rollback is not None:
                    compat.refill_bmesh(bm, rollback)
                raise
            preview_data = getattr(tracked, 'preview_data', None)
            if rollback is not None:
                # The build succeeded. Reuse its compact rollback mesh for the native coordinate hash.
                bm.to_mesh(rollback)
                full_hash = mesh_coords_hash(rollback)
            _store_generic(rec, bm, tracked, params, full_hash, preview_data)
        finally:
            if rollback is not None:
                bpy.data.meshes.remove(rollback)
        return bool(tracked)
    restore_pre(bm, rec)
    faces = [f for f in bm.faces if f.select]
    caps, moved = extrude(bm, faces, unit=unit, history_id=rec.history_id, matrix=ob.matrix_world.copy(), **params,
                          **mesh_axes(ob))
    _store(rec, bm, caps, moved, params)
    return bool(caps)


def run(ob, rec, params, unit, persist=True):
    """Rebuild the extrusion of ``rec`` on ``ob`` (edit mode) with ``params``."""
    bm = bmesh.from_edit_mesh(ob.data)
    try:
        ok = _rebuild(ob, rec, bm, params, unit)
    finally:
        bmesh.update_edit_mesh(ob.data)
    if persist:
        from . import model_history
        model_history.update(ob, rec)
    return ok


def run_object(ob, rec, params, unit, persist=True):
    """``run`` on an object-mode mesh without entering edit mode (an In-View Editor / manipulator drag in object
    mode): the new state is stored, so ``object_record`` keeps finding the node."""
    bm = bmesh.new()
    try:
        ok = _rebuild(ob, rec, bm, params, unit)
        bm.to_mesh(ob.data)
    finally:
        bm.free()
    ob.data.update()
    if rec.spec.object_note is not None:
        rec.spec.object_note(ob)
    if persist:
        from . import model_history
        model_history.update(ob, rec)
    return ok


def preview(ob, rec, params, unit):
    """Show ``params`` during a drag: move the vertices when only lengths change (the node's own preview, edit
    mode), else rebuild (object mode: always, without entering edit mode, so ``object_record`` keeps the state)."""
    if ob.mode == 'EDIT' and rec.spec.preview is not None and rec.spec.preview(ob, rec, params, unit):
        rec.fast_preview = True
    elif ob.mode == 'EDIT':
        run(ob, rec, params, unit, persist=False)
    else:
        run_object(ob, rec, params, unit, persist=False)
    rec.live = True


def _preview_face(ob, rec, params, unit):
    topo = (params["divisions"], params["keep_faces_together"])
    bm = bmesh.from_edit_mesh(ob.data) if ob.mode == 'EDIT' else None
    vertices = bm.verts if bm is not None else ob.data.vertices
    if topo != rec.topology or any(i >= len(vertices) for i, *_r in rec.moved):
        return False
    if bm is not None:
        vertices.ensure_lookup_table()
    world = world_space(rec.moved, ob.matrix_world, params, unit)
    for i, p0, *vecs in rec.moved:
        vertices[i].co = position(p0, vecs, params, world)
    if bm is not None:
        bm.normal_update()
        bmesh.update_edit_mesh(ob.data, loop_triangles=True, destructive=False)
    else:
        ob.data.update()
    rec.params = dict(params)
    return True


FACE.preview = _preview_face


def capture_preview(ob, rec):
    """Commit a coordinate preview using its existing topology and native Mesh hashing."""
    temporary = bpy.data.meshes.new('.allset_commit') if ob.mode == 'EDIT' else None
    try:
        mesh = temporary if temporary is not None else ob.data
        if temporary is not None:
            bmesh.from_edit_mesh(ob.data).to_mesh(mesh)
        sig = mesh_signature(mesh, rec.cap_verts)
        if sig is None:
            raise ValueError('The preview topology changed during attribute editing')
        rec.states.append((dict(rec.params), sig, rec.sel, mesh_coords_hash(mesh)))
        del rec.states[:-64]
        rec.fast_preview = rec.live = False
        from . import model_history
        model_history.update(ob, rec)
    finally:
        if temporary is not None:
            bpy.data.meshes.remove(temporary)


def run_from_object_mode(context, ob, rec, params, unit, persist=True):
    """Rebuild ``rec`` with ``params`` while in object mode: ``ob`` alone into edit mode, rerun, back to object mode
    with the selection as it was (the caller's operator is the undo step)."""
    view_layer = context.view_layer
    sel = [o for o in context.selected_objects]
    active_ob = view_layer.objects.active
    for o in sel:
        o.select_set(o == ob)
    ob.select_set(True)
    view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        ok = run(ob, rec, params, unit, persist=persist)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
        ob.select_set(ob in sel)
        for o in sel:
            o.select_set(True)
        view_layer.objects.active = active_ob
    if rec.spec.object_note is not None:
        rec.spec.object_note(ob)
    return ok


def edit_from_object_mode(context, edit_op, params_of):
    """Body of a kit node's edit operator in object mode: True when the active object's node was rebuilt."""
    ob = getattr(context, "active_object", None)
    rec = object_record(ob)
    if rec is None or rec.spec.edit_op != edit_op:
        return False
    return run_from_object_mode(context, ob, rec, params_of(rec.spec), units.maya_unit(context.scene))


def record_new(context, ob, bm, spec, params, unit):
    """Run ``spec`` on the selection of ``ob`` (edit mode) as a new history node; the same node again when
    Adjust Last Operation re-runs it on the same mesh. Returns the record or None."""
    try:
        return _record_bm(context, ob, bm, spec, params, unit)
    finally:
        # A failed build can replace the BMesh while restoring its snapshot.
        bmesh.update_edit_mesh(ob.data)


def record_object(context, ob, spec, params, unit):
    """``record_new`` on an object-mode mesh: every component of it (Maya acts on the whole mesh for an object
    selection). Returns the record or None."""
    me = ob.data
    bm = bmesh.new()
    try:
        bm.from_mesh(me)
        for el in (*bm.verts, *bm.edges, *bm.faces):
            el.select = True
        rec = _record_bm(context, ob, bm, spec, params, unit)
        if rec is not None:
            bm.to_mesh(me)
            me.update()
    finally:
        bm.free()
    return rec


def _record_bm(context, ob, bm, spec, params, unit):
    old = RECORDS.get(ob.name)
    name = None
    if (old is not None and old.spec is spec and old.pre is not None and old.mesh_uid == ob.data.session_uid
            and _pre_signature(old.pre) == _pre_signature(bm)
            and (not spec.pre_uv or _uv_signature(old.pre) == _uv_signature(bm))):
        name = old.name
    from . import history_references, model_history, prim_history
    recorded = prim_history.history_on(context) and model_history.enabled()
    node_id = (old.history_id if name and old.history_id else uuid4().hex) if recorded else None
    snapshot, input_hash = model_history.prepare_input(ob, bm) if recorded else (None, None)
    pre = bm.copy()
    try:
        values = dict(params, _history_id=node_id)
        tracked = spec.build(bm, values, unit, **({"ob": ob} if spec.with_object else {}))
        history_references.tag_generic(bm, spec, params, node_id, tracked)
    except Exception:
        try:
            restore_mesh(bm, pre)
        finally:
            pre.free()
            if snapshot is not None:
                bpy.data.meshes.remove(snapshot)
        raise
    if not tracked:
        restore_mesh(bm, pre)
        pre.free()
        if snapshot is not None:
            bpy.data.meshes.remove(snapshot)
        return None
    if old is not None:
        old.free()
    rec = Record(name or next_name(context.scene, spec), pre, params, spec)
    rec.history_id, rec.input_snapshot, rec.input_hash = node_id, snapshot, input_hash
    rec.mesh_uid = ob.data.session_uid
    _store_generic(rec, bm, tracked, params)
    keep(context, ob, rec)
    return rec
