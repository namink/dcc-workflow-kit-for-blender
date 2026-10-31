# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Maya Create menu: primitives at the origin with Maya's default size and names.

Maya: interactive creation is off by default, so a
primitive appears at the origin at its default size (polyCube 1x1x1, polySphere
r=1, polyPlane 1x1 with 10x10); names ``pCube1`` / ``pCubeShape1``.
Other default values are Maya behaviour knowledge [K]
and two are unverified [U] (docs/steps/step_10.md 「계획」 6).

Size rule (decision 8, docs/steps/step_21.md 「계획」, delegated): a Maya length of 1
is one scene display unit (``units.maya_unit``), like ``cmds.polyCube()`` and a
Maya FBX import: pCube1 shows 1 cm in the Maya Workflow Kit template (0.01 BU) and with
the "Maya Units" preference (1 BU). Lengths below are in Maya units.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import math
import bpy
from bpy.props import EnumProperty
from .. import results
from . import lights, naming, prim_history, units
HALF_PI = math.pi / 2
LEVEL = (HALF_PI, 0.0, 0.0)
KINDS = {'CUBE': (_dcc_source('Cube'), 'pCube', None, {}, None), 'SPHERE': (_dcc_source('Sphere'), 'pSphere', None, {}, None), 'CYLINDER': (_dcc_source('Cylinder'), 'pCylinder', None, {}, None), 'CONE': (_dcc_source('Cone'), 'pCone', None, {}, None), 'TORUS': (_dcc_source('Torus'), 'pTorus', None, {}, None), 'PLANE': (_dcc_source('Plane'), 'pPlane', None, {}, None), 'DISC': (_dcc_source('Disc'), 'pDisc', None, {}, None), 'PLATONIC': (_dcc_source('Platonic Solid'), 'pPlatonic', None, {}, None), 'PYRAMID': (_dcc_source('Pyramid'), 'pPyramid', None, {}, None), 'PRISM': (_dcc_source('Prism'), 'pPrism', None, {}, None), 'PIPE': (_dcc_source('Pipe'), 'pPipe', None, {}, None), 'HELIX': (_dcc_source('Helix'), 'pHelix', None, {}, None), 'GEAR': (_dcc_source('Gear'), 'pGear', None, {}, None), 'SOCCER_BALL': (_dcc_source('Soccer Ball'), 'pSolid', None, {}, None), 'SUPER_ELLIPSE': (_dcc_source('Super Ellipse'), 'pSuperShape', None, {}, None), 'SPHERICAL_HARMONICS': (_dcc_source('Spherical Harmonics'), 'pSuperShape', None, {}, None), 'ULTRA_SHAPE': (_dcc_source('Ultra Shape'), 'pSuperShape', None, {}, None), 'NURBS_SPHERE': (_dcc_source('NURBS Sphere'), 'nurbsSphere', None, {}, None), 'NURBS_CYLINDER': (_dcc_source('NURBS Cylinder'), 'nurbsCylinder', None, {}, None), 'NURBS_PLANE': (_dcc_source('NURBS Plane'), 'nurbsPlane', None, {}, None), 'NURBS_TORUS': (_dcc_source('NURBS Torus'), 'nurbsTorus', None, {}, None), 'NURBS_CIRCLE': (_dcc_source('NURBS Circle'), 'nurbsCircle', None, {}, None), 'NURBS_SQUARE': (_dcc_source('NURBS Square'), 'nurbsSquare', None, {}, None), 'NURBS_CUBE': (_dcc_source('NURBS Cube'), 'nurbsCube', None, {}, None), 'NURBS_CONE': (_dcc_source('NURBS Cone'), 'nurbsCone', None, {}, None), 'CV_CURVE': (_dcc_source('CV Curve'), _dcc_source('curve'), 'curve.primitive_nurbs_curve_add', {'radius': 1.0}, None), 'BEZIER_CURVE': (_dcc_source('Bezier Curve'), 'bezier', 'curve.primitive_bezier_curve_add', {'radius': 1.0}, None), 'DIRECTIONAL_LIGHT': (_dcc_source('Directional Light'), 'directionalLight', 'object.light_add', {'type': 'SUN'}, LEVEL), 'POINT_LIGHT': (_dcc_source('Point Light'), 'pointLight', 'object.light_add', {'type': 'POINT'}, None), 'SPOT_LIGHT': (_dcc_source('Spot Light'), 'spotLight', 'object.light_add', {'type': 'SPOT'}, LEVEL), 'AREA_LIGHT': (_dcc_source('Area Light'), 'areaLight', 'object.light_add', {'type': 'AREA'}, LEVEL), 'AMBIENT_LIGHT': (_dcc_source('Ambient Light'), 'ambientLight', 'object.light_add', {'type': 'POINT'}, None), 'VOLUME_LIGHT': (_dcc_source('Volume Light'), 'volumeLight', 'object.light_add', {'type': 'POINT'}, None), 'CAMERA': (_dcc_source('Camera'), 'camera', 'object.camera_add', {}, LEVEL), 'LOCATOR': (_dcc_source('Locator'), 'locator', 'object.empty_add', {'type': 'PLAIN_AXES', 'radius': 1.0}, None), 'EMPTY_GROUP': (_dcc_source('Empty Group'), 'null', 'object.empty_add', {'type': 'PLAIN_AXES', 'radius': 1.0}, None), 'JOINT': (_dcc_source('Joint'), 'skeleton', 'object.armature_add', {'radius': 1.0}, None), 'TEXT': (_dcc_source('Type'), 'typeMesh', 'object.text_add', {'radius': 1.0}, None), 'IMAGE_PLANE': (_dcc_source('Free Image Plane'), 'imagePlane', 'object.empty_add', {'type': 'IMAGE', 'radius': 1.0}, LEVEL), 'FIELD_AIR': (_dcc_source('Air Field'), 'airField', 'object.effector_add', {'type': 'WIND', 'radius': 1.0}, None), 'FIELD_DRAG': (_dcc_source('Drag Field'), 'dragField', 'object.effector_add', {'type': 'DRAG', 'radius': 1.0}, None), 'FIELD_GRAVITY': (_dcc_source('Gravity Field'), 'gravityField', 'object.effector_add', {'type': 'WIND', 'radius': 1.0}, (math.pi, 0.0, 0.0)), 'FIELD_NEWTON': (_dcc_source('Newton Field'), 'newtonField', 'object.effector_add', {'type': 'FORCE', 'radius': 1.0}, None), 'FIELD_RADIAL': (_dcc_source('Radial Field'), 'radialField', 'object.effector_add', {'type': 'FORCE', 'radius': 1.0}, None), 'FIELD_TURBULENCE': (_dcc_source('Turbulence Field'), 'turbulenceField', 'object.effector_add', {'type': 'TURBULENCE', 'radius': 1.0}, None), 'FIELD_UNIFORM': (_dcc_source('Uniform Field'), 'uniformField', 'object.effector_add', {'type': 'WIND', 'radius': 1.0}, (0.0, HALF_PI, 0.0)), 'FIELD_VORTEX': (_dcc_source('Vortex Field'), 'vortexField', 'object.effector_add', {'type': 'VORTEX', 'radius': 1.0}, None)}
FIELD_MAGNITUDES = {'FIELD_GRAVITY': 9.8, 'FIELD_NEWTON': -5.0}
NO_SHAPE_NAME = {'JOINT', 'TEXT'}
LOCATOR_PROP = 'allset_locator'
FALLOFF_LIGHTS = {'POINT', 'SPOT', 'AREA'}
LIGHT_NOTICE = _dcc_source('Maya Decay Rate No Decay renders in Cycles; EEVEE and the viewport get darker with the square of the distance (matched to Maya at 10 units).')
MAYA_LIGHT_NOTICES = {'AMBIENT_LIGHT': _dcc_source('Blender has no ambient light: World colour (flat part) + a point light (Ambient Shade part).'), 'VOLUME_LIGHT': _dcc_source('Blender has no volume light: a point light cut at the sphere (exact in Cycles, EEVEE approximates the falloff).')}
(MAYA_CAMERA_LENS, MAYA_FILM_MM) = (35.0, 36.0)
LENGTHS = {'size', 'radius', 'depth', 'radius1', 'radius2', 'major_radius', 'minor_radius'}

def _scale_data(ob, k):
    """Lengths the add operators don't take: camera (Maya clip 0.1 / 10000),
    Blender's light sizes, kept in proportion to the Maya unit."""
    data = ob.data
    if ob.type == 'CAMERA':
        (data.lens, data.sensor_width) = (MAYA_CAMERA_LENS, MAYA_FILM_MM)
        data.display_size *= k
        (data.clip_start, data.clip_end) = (units.CLIP['clip_start'] * k, units.CLIP['clip_end'] * k)
    elif ob.type == 'LIGHT':
        data.shadow_soft_size *= k
        if data.type == 'AREA':
            data.size_y *= k
        lights.maya_defaults(data, k)

def _maya_naming(context):
    from .. import preferences
    try:
        return preferences.get(context).maya_naming
    except KeyError:
        return True

def create(context, kind, maya_naming=True, overrides=None):
    """Create ``kind`` at the world origin; returns the new object. ``overrides``: for primitives Maya node
    attributes (``{"subdivisionsCaps": 2}``, lengths in Maya units, ``createUVs`` 0 = no UVs), else operator values
    in Maya units (lengths are scaled like the defaults), e.g. from the primitive's option window (step 103)."""
    (_label, base, op, props, rot) = KINDS[kind]
    props = {**props, **(overrides or {})}
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    if kind in prim_history.KIND_NODES:
        vals = dict(overrides or {})
        uvs = bool(vals.pop('createUVs', True))
        ob = prim_history.create_object(context, kind, vals, maya_naming, create_uvs=uvs)
        from . import material
        for part in [ob, *ob.children]:
            if part.type in {'MESH', 'SURFACE'}:
                material.give_default(part)
        return ob
    (mod, name) = op.split('.')
    k = units.maya_unit(context.scene)
    kw = {key: v * k if key in LENGTHS else v for (key, v) in props.items()}
    kw.update(location=(0.0, 0.0, 0.0), rotation=rot or (0.0, 0.0, 0.0), align='WORLD')
    getattr(getattr(bpy.ops, mod), name)(**kw)
    ob = context.view_layer.objects.active
    from . import maya_lights
    if kind in maya_lights.KINDS:
        ob.data[lights.KIND_PROP] = maya_lights.KINDS[kind]
    _scale_data(ob, k)
    if kind in FIELD_MAGNITUDES and ob.field is not None:
        from . import fx
        g = fx.sim_scale(context.scene) if hasattr(context.scene, 'allset_nucleus') else k
        ob.field.strength = FIELD_MAGNITUDES[kind] * g
        ob.field.flow = 0.0
    if maya_naming:
        naming.apply_maya_name(ob, base, rename_data=kind not in NO_SHAPE_NAME)
    if kind == 'LOCATOR':
        ob[LOCATOR_PROP] = True
    if kind in maya_lights.KINDS:
        maya_lights.sync(context.scene)
    if kind == 'JOINT':
        _first_joint(ob, maya_naming)
    if maya_naming:
        from . import material
        material.give_default(ob)
    return ob

def _first_joint(ob, maya_naming):
    """The armature's one bone = Maya's joint1, rotate order XYZ (W1)."""
    bone = ob.data.bones[0]
    if maya_naming:
        bone.name = 'joint1'
    pose_bone = ob.pose.bones.get(bone.name)
    if pose_bone is not None:
        pose_bone.rotation_mode = 'XYZ'

class ALLSET_OT_create(bpy.types.Operator):
    """Create a primitive, light, camera or locator at the origin with Maya's default
    size and name (Maya Create menu)"""
    bl_translation_context = 'MWK:operators/create.py:211'
    bl_idname = 'allset.create'
    bl_label = _zh_native('Create', 'MWK:operators/create.py:211')
    bl_description = _zh_native("Create a primitive, light, camera or locator at the origin with Maya's default\nsize and name (Maya Create menu)", 'MWK:operators/create.py:211')
    bl_options = {'REGISTER', 'UNDO'}
    kind: EnumProperty(name=_zh_native('Kind', 'MWK:operators/create.py:214'), items=_zh_enum([(k, v[0], '') for (k, v) in KINDS.items()], 'MWK:operators/create.py:214'), translation_context='MWK:operators/create.py:214')

    @classmethod
    def description(cls, context, props):
        return _zh(f'Create a {KINDS[props.kind][0]} at the origin, Maya default size and name', 'MWK:operators/create.py:218')

    def execute(self, context):
        ob = create(context, self.kind, _maya_naming(context))
        note = LIGHT_NOTICE if ob.type == 'LIGHT' and ob.data.type in FALLOFF_LIGHTS else ''
        note = MAYA_LIGHT_NOTICES.get(self.kind, note)
        results.result(self, _zh(f'Created {ob.name}' + (f'. {note}' if note else ''), 'MWK:operators/create.py:224'))
        return {'FINISHED'}
SMOKE_MARGIN = (1.0, 1.0, 2.0)
SMOKE_LIFT = 1.0

def _selection_bounds(objects):
    from mathutils import Vector
    pts = [ob.matrix_world @ Vector(c) for ob in objects for c in ob.bound_box]
    lo = Vector((min((p.x for p in pts)), min((p.y for p in pts)), min((p.z for p in pts))))
    hi = Vector((max((p.x for p in pts)), max((p.y for p in pts)), max((p.z for p in pts))))
    return (lo, hi)

class ALLSET_OT_quick_smoke(bpy.types.Operator):
    """Smoke or fire from the selected meshes in a Mantaflow domain sized in Maya units
    (Maya Fluids > 3D Container, Effects > Fire / Smoke)"""
    bl_translation_context = 'MWK:operators/create.py:247'
    bl_idname = 'allset.quick_smoke'
    bl_label = _zh_native('Quick Smoke', 'MWK:operators/create.py:247')
    bl_description = _zh_native('Smoke or fire from the selected meshes in a Mantaflow domain sized in Maya units\n(Maya Fluids > 3D Container, Effects > Fire / Smoke)', 'MWK:operators/create.py:247')
    bl_options = {'REGISTER', 'UNDO'}
    style: EnumProperty(name=_zh_native('Style', 'MWK:operators/create.py:250'), items=_zh_enum((('SMOKE', 'Smoke', ''), ('FIRE', 'Fire', ''), ('BOTH', 'Both', '')), 'MWK:operators/create.py:250'), translation_context='MWK:operators/create.py:250')

    @classmethod
    def poll(cls, context):
        return any((ob.type == 'MESH' for ob in context.selected_objects))

    def execute(self, context):
        from mathutils import Vector
        meshes = [ob for ob in context.selected_objects if ob.type == 'MESH']
        (lo, hi) = _selection_bounds(meshes)
        before = set(bpy.data.objects)
        if not bpy.ops.object.quick_smoke.poll():
            self.report({'WARNING'}, _zh('Smoke: switch to Object Mode with the emitting meshes selected first.', 'MWK:operators/create.py:262'))
            return {'CANCELLED'}
        res = bpy.ops.object.quick_smoke(style=self.style)
        if res != {'FINISHED'}:
            return res
        domain = next((ob for ob in bpy.data.objects if ob not in before), None)
        if domain is None:
            return res
        k = units.maya_unit(context.scene)
        domain.location = (lo + hi) / 2 + Vector((0.0, 0.0, SMOKE_LIFT * k))
        domain.scale = (hi - lo) / 2 + Vector(SMOKE_MARGIN) * k
        return res
classes = (ALLSET_OT_create, ALLSET_OT_quick_smoke)
