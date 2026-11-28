# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya polyExtrudeFace and the "last kit modeling operation" history.

Maya's Edit Mesh > Extrude = a zero-length extrusion
(Thickness 0, Local Translate Z 0, Offset 0, Divisions 1, Keep Faces Together on); Local Translate Z moves each face along
its normal (a border vertex shared by several extruded faces moves by the average, an inner one along its unit normal),
Thickness offsets every face plane by the same distance (shell), Offset shrinks the extruded faces in their plane (no new
faces), Divisions = rings along the sides.

Blender keeps no history in edit mode. The kit remembers the last extrusion per object:
its node name (``polyExtrudeFaceN``), the mesh before it and the values; changing a value rebuilds the extrusion from that
mesh (``allset.extrude_edit``), so it is one undo step and the Adjust Last Operation panel shows the same Maya names.
The record is valid only while the mesh equals one of the states the kit made (Ctrl+Z / Ctrl+Shift+Z included).
With Preferences > Persistent Modeling History on, ``model_history`` also keeps the recipe of every node and one
input mesh with the mesh, so earlier nodes can be changed (the later ones replay) and the chain survives Save / Load.

#70, #16: the record is one ``Spec`` per Maya node - polyExtrudeEdge / polyExtrudeVertex here (edges /
vertices extrude at once, no drag) and polyBevel3 in operators/bevel_maya.py - each with its Maya fields, edit
operator and arrow field.

The extrude manipulator's other handles drive polyExtrudeFace Local Translate X / Y and Local
Scale X / Y / Z the way Maya does (tests/test_step151_extrude_manip.py): every extruded face has its own frame
- Z = its normal, X = Maya world X (``localDirection`` 1 0 0, in world space) projected into the face plane
(Maya world Z = Blender -Y when the face faces X), Y = Z x X; Local Translate moves the face along X / Y, Local Scale scales it about its vertex mean along its X / Y / Z
(Z does nothing on a flat face); a vertex shared by several extruded faces takes the mean of their moves (Keep Faces
Together), the rings between take the level fraction, and Offset adds after the scale.

This module: the extrude / edit operators, ``set_params`` and the handlers. Specs: ``extrude_spec``; face geometry:
``extrude_face``; edge / vertex: ``extrude_edge_vertex``; the record: ``extrude_record``; running a node:
``extrude_rebuild``. The names used elsewhere are importable from here too.
"""

from uuid import uuid4

import bmesh
import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty

from .. import undo_steps
from . import units
# the split-out parts, also read through this module by other operators and the tests (import order = SPECS order)
from .extrude_spec import (COUNTER, DEFAULTS, FACE, FIELDS, LABELS, MANIP_DEFAULTS, MANIP_FIELDS,  # noqa: F401
                           MANIP_LABELS, MAYA_Z, NODE, NOTICE, SPECS, WORLD_X, BuildResult, Spec, add_spec)
from .extrude_face import (_key, extrude, extrude_topology, face_axes, mesh_axes, moved_vertices,  # noqa: F401
                           place, renumber)
from .extrude_edge_vertex import EDGE, VERTEX, deselect_all, edge_frame, extrude_edges, extrude_vertices  # noqa: F401
from .extrude_record import (RECORDS, SHOWN, Record, _on_redo, _on_undo, _pre_signature, _store,  # noqa: F401
                             _store_generic, active, caps_selected, clear, coords_hash, current, dismiss, keep,
                             kind_of, mesh_coords_hash, next_name, object_record, park)
from .extrude_rebuild import (capture_preview, edit_from_object_mode, preview, record_new,  # noqa: F401
                              record_object, restore_mesh, restore_pre, run)


# --- operators -------------------------------------------------------------------------------------

def _props():
    return {
        "thickness": FloatProperty(name="Thickness", default=0.0, options={'SKIP_SAVE'},
                                   description="Every extruded face plane moves out by this much (Maya units)"),
        "local_translate_z": FloatProperty(name="Local Translate Z", default=0.0, options={'SKIP_SAVE'},
                                           description="Move the extruded faces along their normals (Maya units)"),
        "offset": FloatProperty(name="Offset", default=0.0, options={'SKIP_SAVE'},
                                description="Shrink the extruded faces in their plane (Maya units)"),
        "divisions": IntProperty(name="Divisions", default=1, min=1, soft_max=20, options={'SKIP_SAVE'},
                                 description="Segments along the extruded sides"),
        "keep_faces_together": BoolProperty(name="Keep Faces Together", default=True,
                                            description="Extrude adjacent faces as one piece (off: each face alone)"),
        # polyExtrudeFace values of the manipulator handles
        "local_translate_x": FloatProperty(name="Local Translate X", default=0.0, options={'SKIP_SAVE'},
                                           description="Move the extruded faces along their local X (Maya units)"),
        "local_translate_y": FloatProperty(name="Local Translate Y", default=0.0, options={'SKIP_SAVE'},
                                           description="Move the extruded faces along their local Y (Maya units)"),
        "local_scale_x": FloatProperty(name="Local Scale X", default=1.0, options={'SKIP_SAVE'},
                                       description="Scale the extruded faces along their local X"),
        "local_scale_y": FloatProperty(name="Local Scale Y", default=1.0, options={'SKIP_SAVE'},
                                       description="Scale the extruded faces along their local Y"),
        "local_scale_z": FloatProperty(name="Local Scale Z", default=1.0, options={'SKIP_SAVE'},
                                       description="Scale the extruded faces along their normal"),
        # the rotate rings and the world-axes handles (the manipulator's world / local switch)
        **{f: FloatProperty(name=MANIP_LABELS[f], default=MANIP_DEFAULTS[f], options={'SKIP_SAVE'},
                            description=MANIP_LABELS[f] + (" (degrees)" if "rotate" in f else ""))
           for f in MANIP_FIELDS[5:]},
        # polyExtrudeVertex
        "width": FloatProperty(name="Width", default=0.5, soft_min=0.0, soft_max=1.0, options={'SKIP_SAVE'},
                               description="Base of the extruded vertex as a fraction of each of its edges"),
        "length": FloatProperty(name="Length", default=1.0, options={'SKIP_SAVE'},
                                description="Tip of the extruded vertex along its normal (Maya units)"),
    }


def _params(op, spec=None):
    return {k: getattr(op, k) for k in (spec or FACE).all_fields}


class _ExtrudeProps:
    __annotations__ = _props()


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_extrude(_ExtrudeProps, bpy.types.Operator):
    """Extrude the selection now (Maya polyExtrudeFace / polyExtrudeEdge / polyExtrudeVertex by the component
    type; faces with a curve selected: along the curve, with Taper and Twist): change its values with the
    manipulator, the In-View Editor or Channel Box INPUTS"""
    bl_idname = "allset.extrude"
    bl_label = "Extrude"
    bl_options = {'REGISTER', 'UNDO'}

    # the Extrude option box's Curve settings (faces): the path and how the faces taper / twist along it
    curve: bpy.props.EnumProperty(
        name="Curve", default='SELECTED', options={'SKIP_SAVE'},
        items=(('NONE', "None", "Extrude straight, even with a curve selected"),
               ('SELECTED', "Selected", "Extrude along the selected curve (straight when no curve is selected)"),
               ('GENERATED', "Generated", "Make a straight curve along the faces' normal and extrude along it")))
    taper: FloatProperty(name="Taper", default=1.0, soft_min=0.0, soft_max=15.0, options={'SKIP_SAVE'},
                         description="Size of the last step along the curve (the steps between grow evenly)")
    twist: FloatProperty(name="Twist", default=0.0, soft_min=-180.0, soft_max=180.0, options={'SKIP_SAVE'},
                         description="Turn of the last step along the curve, in degrees (the steps between turn "
                                     "evenly)")

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def invoke(self, context, event):
        # Maya extrudes edges / vertices at once too (no drag: #70)
        return self.execute(context)

    def execute(self, context):
        unit = units.maya_unit(context.scene)
        mode = tuple(context.scene.tool_settings.mesh_select_mode)
        done = 0
        for ob in context.objects_in_mode_unique_data:
            if ob.type != 'MESH':
                continue
            bm = bmesh.from_edit_mesh(ob.data)
            kind = kind_of(bm, mode)
            if kind is None:
                continue
            if kind == 'EDGE' and self.curve == 'SELECTED':
                from . import extrude_curve
                path = extrude_curve.path_curve(context)     # edges + a curve selected: along it, like faces
                if path is not None:
                    values = {k: getattr(self, k) for k in ("divisions", "taper", "twist", "local_translate_z",
                                                            "offset", "thickness", "keep_faces_together")}
                    if extrude_curve.run(context, ob, bm, path, unit, edges=True, **values) is not None:
                        done += 1
                    continue
            if kind != 'FACE':
                spec = SPECS[kind]
                if record_new(context, ob, bm, spec, _params(self, spec), unit) is not None:
                    done += 1
                continue
            from . import extrude_curve
            path = None
            if self.curve == 'SELECTED':      # faces + a curve selected: extrude along the curve, like Maya
                path = extrude_curve.path_curve(context)
            elif self.curve == 'GENERATED':
                path = extrude_curve.generate_curve(context, ob, bm)
            if path is not None:
                values = {k: getattr(self, k) for k in ("divisions", "taper", "twist", "local_translate_z",
                                                        "offset", "thickness", "keep_faces_together")}
                if extrude_curve.run(context, ob, bm, path, unit, **values) is not None:
                    done += 1
                continue
            params = _params(self)
            old = RECORDS.get(ob.name)
            name = None
            if (old is not None and old.spec is FACE and old.pre is not None and old.mesh_uid == ob.data.session_uid
                    and _pre_signature(old.pre) == _pre_signature(bm)):
                name = old.name          # Adjust Last Operation re-runs the same extrusion
            from . import model_history, prim_history
            recorded = prim_history.history_on(context) and model_history.enabled()
            node_id = (old.history_id if name and old.history_id else uuid4().hex) if recorded else None
            snapshot, input_hash = model_history.prepare_input(ob, bm) if recorded else (None, None)
            if old is not None:
                old.free()
            rec = Record(name or next_name(context.scene), bm.copy(), params)
            rec.history_id, rec.input_snapshot, rec.input_hash = node_id, snapshot, input_hash
            rec.mesh_uid = ob.data.session_uid
            try:
                faces = [f for f in bm.faces if f.select]
                caps, moved = extrude(bm, faces, unit=unit, history_id=node_id, matrix=ob.matrix_world.copy(), **params,
                                      **mesh_axes(ob))
                _store(rec, bm, caps, moved, params)
                keep(context, ob, rec)
            except Exception:
                rec.free()
                raise
            bmesh.update_edit_mesh(ob.data)
            done += 1
        return {'FINISHED'} if done else {'CANCELLED'}


class _ExtrudeEdit(_ExtrudeProps):
    """Shared body of the edit operators (a registered operator class can't be subclassed: its poll broke)."""
    bl_options = {'REGISTER', 'UNDO'}
    _op = "extrude_edit"                  # the specs this operator edits (Spec.edit_op)

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}     # Maya edits history nodes in object mode too (#204)

    def invoke(self, context, event):
        _ob, rec = active(context)
        if rec is None:
            rec = object_record(getattr(context, "active_object", None))
        if rec is None or rec.spec.edit_op != self._op:
            return {'CANCELLED'}
        for k, v in rec.params.items():
            if not self.properties.is_property_set(k):
                setattr(self, k, v)
        return self.execute(context)

    def execute(self, context):
        unit = units.maya_unit(context.scene)
        if context.mode == 'OBJECT':
            if edit_from_object_mode(context, self._op, lambda spec: _params(self, spec)):
                return {'FINISHED'}
            self.report({'WARNING'}, "No extrusion to change: " + NOTICE)
            return {'CANCELLED'}
        done = 0
        for ob in context.objects_in_mode_unique_data:
            rec = RECORDS.get(ob.name)
            if rec is None or rec.pre is None or rec.spec.edit_op != self._op or (
                    not rec.live and current(ob) is None):
                continue
            if run(ob, rec, _params(self, rec.spec), unit):
                done += 1
        if not done:
            self.report({'WARNING'}, "No extrusion to change: " + NOTICE)
            return {'CANCELLED'}
        return {'FINISHED'}


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_extrude_edit(_ExtrudeEdit, bpy.types.Operator):
    """Change the last extrusion (Maya: edit the polyExtrudeFace node). Blender keeps no edit-mode history,
    so only the last one can be changed"""
    bl_idname = "allset.extrude_edit"
    bl_label = "polyExtrudeFace"          # the Adjust Last Operation title = the Maya node
    _op = "extrude_edit"


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_extrude_edge_edit(_ExtrudeEdit, bpy.types.Operator):
    """Change the last edge extrusion (Maya: edit the polyExtrudeEdge node). Blender keeps no edit-mode history,
    so only the last one can be changed"""
    bl_idname = "allset.extrude_edge_edit"
    bl_label = "polyExtrudeEdge"
    _op = "extrude_edge_edit"


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_extrude_vertex_edit(_ExtrudeEdit, bpy.types.Operator):
    """Change the last vertex extrusion (Maya: edit the polyExtrudeVertex node). Blender keeps no edit-mode
    history, so only the last one can be changed"""
    bl_idname = "allset.extrude_vertex_edit"
    bl_label = "polyExtrudeVertex"
    _op = "extrude_vertex_edit"


INT_FIELDS = ("divisions", "segments")


def set_params(context, **changes):
    """Change values of the active object's last kit node (one undo step). Returns the operator result."""
    _ob, rec = active(context)
    if rec is None:
        rec = object_record(getattr(context, "active_object", None))
    if rec is None:
        return {'CANCELLED'}
    params = dict(rec.params)
    params.update(changes)
    properties = getattr(bpy.ops.allset, rec.spec.edit_op).get_rna_type().properties
    for key in rec.spec.all_fields:
        prop = properties.get(key)
        if prop is not None and prop.type == 'INT':
            params[key] = max(prop.hard_min, min(prop.hard_max, int(params[key])))
    # undo=True: a Python operator call pushes no undo step by default (bpy.ops positional ``undo``)
    return getattr(bpy.ops.allset, rec.spec.edit_op)('EXEC_DEFAULT', True, **params)


classes = (ALLSET_OT_extrude, ALLSET_OT_extrude_edit, ALLSET_OT_extrude_edge_edit, ALLSET_OT_extrude_vertex_edit)


@bpy.app.handlers.persistent
def _on_load(_dummy):
    clear()


_HANDLERS = (("load_pre", _on_load), ("undo_post", _on_undo), ("redo_post", _on_redo))


def register_handlers():
    from . import bridge_curve, model_history
    bridge_curve.register()
    if model_history.changed not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(model_history.changed)
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name)
        if fn not in lst:
            lst.append(fn)


def unregister_handlers():
    from . import bridge_curve, model_history
    bridge_curve.unregister()
    if model_history.changed in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(model_history.changed)
    model_history.clear()
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name)
        if fn in lst:
            lst.remove(fn)
    clear()
