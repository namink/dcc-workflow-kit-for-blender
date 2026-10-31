# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese display integration by namink.
"""Maya Delete History, Delete Non-Deformer History, Edit > Delete (All) by Type.

Maya history = upstream DG nodes; the closest
Blender equivalent is the modifier stack plus shape keys (blendShape). Delete
History (``cmds.delete(constructionHistory=True)``, Alt+Shift+D) bakes them; Non-Deformer History
(``BakeNonDefHistory``) bakes the modelling operations and keeps the deformers.
Plan: docs/steps/step_10.md 「계획」 8.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
from bpy.props import BoolProperty, EnumProperty
from .. import results
from .. import undo_steps
from .display import is_preview
DEFORMERS = {'ARMATURE', 'LATTICE', 'HOOK', 'MESH_DEFORM', 'SURFACE_DEFORM', 'CORRECTIVE_SMOOTH', 'SIMPLE_DEFORM', 'WAVE', 'CAST', 'CURVE', 'SHRINKWRAP', 'DISPLACE', 'SMOOTH', 'LAPLACIANSMOOTH', 'LAPLACIANDEFORM', 'WARP', 'MESH_CACHE', 'MESH_SEQUENCE_CACHE'}
CLUSTERS = {'HOOK'}
NONLINEARS = {'SIMPLE_DEFORM', 'WAVE', 'CAST'}

def is_deformer(md):
    """``md`` plays a Maya deformer: a DEFORMERS modifier, or a kit Geometry Nodes deformer — the wire
    (operators/wire_deformer.py, Maya wire) and the skin's weight sum (operators/skin_tools_199.py, part of the
    skinCluster). Non-Deformer History keeps both like Maya (step 202 / #109)."""
    if md.type in DEFORMERS:
        return True
    if md.type != 'NODES':
        return False
    from . import skin_tools_199, wire_deformer
    if wire_deformer.is_wire(md) or skin_tools_199.is_part(md):
        return True
    from . import deformers
    return deformers.base_of(md) is not None

def _bake(context, ob, keep):
    """Replace ``ob``'s mesh with its evaluated result, with the modifiers in ``keep``
    (names) switched off for the evaluation and kept afterwards."""
    saved = {}
    for md in ob.modifiers:
        if md.name in keep:
            saved[md.name] = md.show_viewport
            md.show_viewport = False
    dg = context.evaluated_depsgraph_get()
    try:
        mesh = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    finally:
        for (name, show) in saved.items():
            ob.modifiers[name].show_viewport = show
    old = ob.data
    for md in [m for m in ob.modifiers if m.name not in keep]:
        ob.modifiers.remove(md)
    ob.data = mesh
    name = old.name
    if old.users == 0:
        bpy.data.meshes.remove(old)
    mesh.name = name

def delete_history(context, objects, non_deformer=False, before_only=False):
    """Bake history on mesh ``objects``. Returns (baked, notes).

    ``non_deformer``: Maya Delete Non-Deformer History keeps the deformers. Its option window (step 162):
    "All non-deformer history" (factory, ``bakePartialHistory
    -prePostDeformers``) also removes the non-deformer nodes *after* a deformer — polyCube / extrude / bend / bevel
    keeps only bend — so every non-deformer modifier is baked into the mesh under the deformers;
    ``before_only`` = "History before deformers only" (``-preDeformers``) bakes only the modifiers above the first
    deformer (the kit's rule before step 162)."""
    from . import extrude, prim_history
    (baked, notes) = (0, [])
    for ob in objects:
        rec = extrude.RECORDS.pop(ob.name, None)
        if rec is not None:
            rec.free()
            if not ob.modifiers and (not (ob.type == 'MESH' and ob.data.shape_keys)) and (prim_history.owner_of(ob) is None):
                baked += 1
                continue
        if prim_history.drop(ob) and (not ob.modifiers) and (not (ob.type == 'MESH' and ob.data.shape_keys)):
            baked += 1
            continue
        preview = {md.name for md in ob.modifiers if is_preview(md)}
        history = [md for md in ob.modifiers if md.name not in preview]
        if not history and (not (ob.type == 'MESH' and ob.data.shape_keys)):
            continue
        if ob.type != 'MESH':
            notes.append(f'{ob.name}: not a mesh, modifiers kept')
            continue
        if not non_deformer:
            _bake(context, ob, keep=preview)
            baked += 1
            continue
        if not before_only:
            deformers = {md.name for md in history if is_deformer(md)}
            if len(deformers) == len(history):
                continue
            if ob.data.shape_keys:
                notes.append(f'{ob.name}: has shape keys, modelling modifiers kept')
                continue
            _bake(context, ob, keep=deformers | preview)
            baked += 1
            continue
        prefix = []
        for md in history:
            if is_deformer(md):
                break
            prefix.append(md.name)
        if not prefix:
            continue
        if ob.data.shape_keys:
            notes.append(f'{ob.name}: has shape keys, modelling modifiers kept')
            continue
        rest = [md.name for md in history if md.name not in prefix]
        if any((not is_deformer(ob.modifiers[n]) for n in rest)):
            notes.append(f'{ob.name}: modifiers after a deformer kept')
        _bake(context, ob, keep=set(rest) | preview)
        baked += 1
    return (baked, notes)

def _static(fcurve):
    pts = fcurve.keyframe_points
    return len(pts) > 0 and all((abs(k.co[1] - pts[0].co[1]) < 1e-06 for k in pts))

def _fcurve_owners(action):
    """Collections holding the action's F-curves (layered actions in 4.4+, legacy fallback)."""
    from .. import compat
    return compat.fcurve_owners(action)

def delete_static_channels(ob):
    ad = ob.animation_data
    if ad is None or ad.action is None:
        return 0
    n = 0
    for owner in _fcurve_owners(ad.action):
        for fc in [f for f in owner.fcurves if _static(f)]:
            owner.fcurves.remove(fc)
            n += 1
    return n
TYPES = (('HISTORY', _dcc_source('History'), _dcc_source('Bake modifiers and shape keys (Delete History)')), ('NON_DEFORMER_HISTORY', _dcc_source('Non-Deformer History'), _dcc_source('Bake modelling modifiers, keep deformers')), ('CHANNELS', _dcc_source('Channels'), _dcc_source('Remove animation')), ('STATIC_CHANNELS', _dcc_source('Static Channels'), _dcc_source('Remove animation curves whose value never changes')), ('CONSTRAINTS', _dcc_source('Constraints'), _dcc_source('Remove constraints')), ('MOTION_PATHS', _dcc_source('Motion Paths'), _dcc_source('Remove motion paths')), ('RIGID_BODIES', _dcc_source('Rigid Bodies'), _dcc_source('Remove rigid bodies')), ('JOINTS', _dcc_source('Joints'), _dcc_source('Delete armatures')), ('LATTICES', _dcc_source('Lattices'), _dcc_source('Delete lattices')), ('CAMERAS', _dcc_source('Cameras'), _dcc_source('Delete cameras')), ('LIGHTS', _dcc_source('Lights'), _dcc_source('Delete lights')), ('IMAGE_PLANES', _dcc_source('Image Planes'), _dcc_source('Delete image empties')), ('CLUSTERS', _dcc_source('Clusters'), _dcc_source('Remove the clusters (Hook modifiers) and their handles')), ('IK_HANDLES', _dcc_source('IK Handles'), _dcc_source('Remove the IK constraints and their handle empties')), ('NONLINEARS', _dcc_source('Nonlinears'), _dcc_source('Remove Simple Deform / Wave / Cast modifiers')), ('PARTICLES', _dcc_source('Particles'), _dcc_source('Remove particle systems')), ('WIRES', _dcc_source('Wires'), _dcc_source('Remove the kit wire deformers and their base wires (the curves stay)')), ('NCLOTHS', _dcc_source('nCloths'), _dcc_source('Remove the cloth from the meshes (the meshes stay)')), ('NPARTICLES', 'nParticles', _dcc_source('Remove the nParticle systems (the emitters stay)')), ('NRIGIDS', _dcc_source('nRigids'), _dcc_source('Remove the passive colliders (the meshes stay)')))
_DELETE_OBJECTS = {'JOINTS': lambda o: o.type == 'ARMATURE', 'LATTICES': lambda o: o.type == 'LATTICE', 'CAMERAS': lambda o: o.type == 'CAMERA', 'LIGHTS': lambda o: o.type == 'LIGHT', 'IMAGE_PLANES': lambda o: o.type == 'EMPTY' and o.empty_display_type == 'IMAGE'}
_REMOVE_MODIFIERS = {'NONLINEARS': NONLINEARS, 'PARTICLES': {'PARTICLE_SYSTEM'}}

def delete_by_type(context, kind, objects):
    """Delete ``kind`` from ``objects``. Returns (count, notes)."""
    objects = list(objects)
    if kind in ('HISTORY', 'NON_DEFORMER_HISTORY'):
        return delete_history(context, objects, kind == 'NON_DEFORMER_HISTORY')
    n = 0
    if kind in ('CLUSTERS', 'IK_HANDLES'):
        from . import by_type
        if kind == 'CLUSTERS':
            return (by_type.delete_clusters(context.scene, objects), [])
        return (by_type.delete_ik_handles(context.scene), [])
    if kind in ('WIRES', 'NCLOTHS', 'NPARTICLES', 'NRIGIDS'):
        from . import by_type
        return (by_type.DELETERS[kind](objects), [])
    if kind in _DELETE_OBJECTS:
        for ob in [o for o in objects if _DELETE_OBJECTS[kind](o)]:
            bpy.data.objects.remove(ob)
            n += 1
    elif kind in _REMOVE_MODIFIERS:
        for ob in objects:
            for md in [m for m in ob.modifiers if m.type in _REMOVE_MODIFIERS[kind]]:
                ob.modifiers.remove(md)
                n += 1
    elif kind == 'CHANNELS':
        for ob in objects:
            if ob.animation_data is not None:
                ob.animation_data_clear()
                n += 1
    elif kind == 'STATIC_CHANNELS':
        n = sum((delete_static_channels(ob) for ob in objects))
    elif kind == 'CONSTRAINTS':
        from . import constrain_199
        helpers = []
        for ob in objects:
            helpers += [h for h in (constrain_199.helper_of(c) for c in ob.constraints) if h is not None]
            n += len(ob.constraints)
            ob.constraints.clear()
        constrain_199.remove_helpers(helpers)
    elif kind == 'MOTION_PATHS':
        targets = [ob for ob in objects if ob.motion_path is not None]
        if targets:
            with context.temp_override(selected_objects=targets, selected_editable_objects=targets):
                bpy.ops.object.paths_clear(only_selected=True)
        n = len(targets)
    elif kind == 'RIGID_BODIES':
        targets = [ob for ob in objects if ob.rigid_body is not None]
        if targets:
            with context.temp_override(selected_objects=targets, object=targets[0], active_object=targets[0]):
                bpy.ops.rigidbody.objects_remove()
        n = len(targets)
    return (n, [])

@undo_steps.no_redo_panel
class ALLSET_OT_delete_history(bpy.types.Operator):
    """Bake the modifier stack and shape keys into the mesh (Maya Edit > Delete by
    Type > History, Alt+Shift+D)"""
    bl_translation_context = 'MWK:operators/history.py:248'
    bl_idname = 'allset.delete_history'
    bl_label = _zh_native('Delete History', 'MWK:operators/history.py:248')
    bl_description = _zh_native('Bake the modifier stack and shape keys into the mesh (Maya Edit > Delete by\nType > History, Alt+Shift+D)', 'MWK:operators/history.py:248')
    bl_options = {'REGISTER', 'UNDO'}
    non_deformer: BoolProperty(name=_zh_native('Non-Deformer Only', 'MWK:operators/history.py:251'), description=_zh_native('Keep deformers (Armature, Lattice, ...) and shape keys', 'MWK:operators/history.py:251'), translation_context='MWK:operators/history.py:251')
    before_only: BoolProperty(name=_zh_native('Before Deformers Only', 'MWK:operators/history.py:254'), options={'SKIP_SAVE'}, description=_zh_native('Bake only the modelling modifiers above the first deformer', 'MWK:operators/history.py:254'), translation_context='MWK:operators/history.py:254')

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        (baked, notes) = delete_history(context, context.selected_objects, self.non_deformer, self.before_only)
        for note in notes:
            self.report({'WARNING'}, _zh(note, 'MWK:operators/history.py:264'))
        results.result(self, _zh(f'Deleted history on {baked} object(s)', 'MWK:operators/history.py:265'))
        return {'FINISHED'}

class ALLSET_OT_delete_by_type(bpy.types.Operator):
    """Delete one kind of node from the selection or the whole scene
    (Maya Edit > Delete by Type / Delete All by Type)"""
    bl_translation_context = 'MWK:operators/history.py:273'
    bl_idname = 'allset.delete_by_type'
    bl_label = _zh_native('Delete by Type', 'MWK:operators/history.py:273')
    bl_description = _zh_native('Delete one kind of node from the selection or the whole scene\n(Maya Edit > Delete by Type / Delete All by Type)', 'MWK:operators/history.py:273')
    bl_options = {'REGISTER', 'UNDO'}
    type: EnumProperty(name=_zh_native('Type', 'MWK:operators/history.py:276'), items=_zh_enum(TYPES, 'MWK:operators/history.py:276'), translation_context='MWK:operators/history.py:276')
    all: BoolProperty(name=_zh_native('All', 'MWK:operators/history.py:277'), description=_zh_native('Whole scene instead of the selection', 'MWK:operators/history.py:277'), translation_context='MWK:operators/history.py:277')

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        objects = context.scene.objects if self.all else context.selected_objects
        (n, notes) = delete_by_type(context, self.type, objects)
        for note in notes:
            self.report({'WARNING'}, _zh(note, 'MWK:operators/history.py:287'))
        results.result(self, f"{_dcc_display(_dcc_source(self.type.replace('_', ' ').title()))}: {_dcc_display(n)}")
        return {'FINISHED'}
classes = (ALLSET_OT_delete_history, ALLSET_OT_delete_by_type)
