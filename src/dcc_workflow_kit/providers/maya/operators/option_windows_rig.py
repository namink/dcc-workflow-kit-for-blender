# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Step 140 Maya option windows: rigging, skinning, deformers and constraints (issue #32, Aim / Pole Vector of #35).

Same spec as operators/option_windows.py (``F`` fields, ``Window`` = one ``allset.opt_<key>`` operator); labels and
factory defaults are Maya 2022's.
option_windows.py appends ``WINDOWS`` to its own list, so this module only imports ``F`` / ``Window`` / helpers from it.

Maya tool boxes (Create Joints, Create IK Handle, Create IK Spline Handle, Paint Skin Weights) open Tool Settings,
not a window: here they are the same kind of window titled with the tool name, whose
button starts the tool with the values (docs/steps/step_140.md 「설계」). Fields Blender can't honour are only listed
(``missing``), never faked.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
from bpy.props import StringProperty
from mathutils import Vector
from .option_windows import F, Window, _constraint, _last_constraint
from .option_windows_modify import FString

class FText(F):
    """A Maya text field (``kind`` "text")."""

    def __init__(self, name, label, default=''):
        super().__init__(name, label, 'text', default)

    def prop(self):
        return StringProperty(name=_zh_native(self.label.rstrip(':'), 'MWK:operators/option_windows_rig.py:31'), default=self.default, translation_context='MWK:operators/option_windows_rig.py:31')
_SOLVER = {_dcc_source('Rotate-Plane Solver'): 'RP', _dcc_source('Single-Chain Solver'): 'SC'}
_NORMALIZE = {_dcc_source('None'): 'NONE', _dcc_source('Off'): 'NONE', _dcc_source('Interactive'): 'INTERACTIVE', _dcc_source('Post'): 'POST'}

def _ik_fields(prefix=''):
    return [F(prefix + 'solver', _dcc_source('Current solver:'), 'enum', _dcc_source('Rotate-Plane Solver'), items=(_dcc_source('Single-Chain Solver'), _dcc_source('Rotate-Plane Solver')), translation_context='MWK:operators/option_windows_rig.py:42'), F(prefix + 'solver_enable', '', 'bool', True, text=_zh('Solver enable', 'MWK:operators/option_windows_rig.py:44'), translation_context='MWK:operators/option_windows_rig.py:44'), F(prefix + 'weight', _dcc_source('Weight:'), 'float', 1.0, lo=0.01, hi=1.0, translation_context='MWK:operators/option_windows_rig.py:45')]
_IK_MISSING = (_dcc_source('Autopriority'), _dcc_source("Snap enable (Blender's handle is a free empty)"), _dcc_source('Sticky'), _dcc_source('Priority'), _dcc_source('POWeight'))

def joint_tool_props(v):
    """Window values -> ``allset.joint_tool`` properties."""
    return dict(secondary_axis='NONE' if v['secondary_axis'] == _dcc_source('None') else v['secondary_axis'], secondary_world=v['secondary_world'], secondary_sign=v['secondary_sign'], auto_secondary=v.get('auto_secondary', True), orient_world=v.get('orient_world', False), create_ik=v['create_ik'], ik_solver=_SOLVER[v['ik_solver']], ik_solver_enable=v['ik_solver_enable'], ik_weight=v['ik_weight'])

def _run_joint_tool(context, v):
    props = joint_tool_props(v)
    if props['secondary_axis'] == 'X':
        raise RuntimeError(_dcc_source('Secondary axis must differ from the primary axis (X)'))
    return bpy.ops.allset.joint_tool('INVOKE_DEFAULT', **props)

def _run_ik_handle(context, v):
    return bpy.ops.allset.ik_handle('INVOKE_DEFAULT', solver=_SOLVER[v['solver']], solver_enable=v['solver_enable'], weight=v['weight'])

def _run_ik_spline(context, v):
    return bpy.ops.allset.ik_spline_handle('INVOKE_DEFAULT', root_on_curve=v.get('root_on_curve', True), parent_curve=v.get('parent_curve', True), snap_curve=v.get('snap_curve', False), create_curve=v.get('create_curve', True), spans=int(v.get('spans', '1')), twist_type=(_dcc_source('Linear'), _dcc_source('Ease In'), _dcc_source('Ease Out'), _dcc_source('Ease In Out')).index(v.get('twist_type', _dcc_source('Linear'))))
_BIND_METHOD = {_dcc_source('Closest distance'): 'CLOSEST_DISTANCE', _dcc_source('Closest in hierarchy'): 'CLOSEST_HIERARCHY', _dcc_source('Heat Map'): 'HEAT_MAP'}

def _run_bind(context, v):
    return bpy.ops.allset.bind_skin('EXEC_DEFAULT', bind_to='SELECTED' if v['bind_to'] == _dcc_source('Selected joints') else 'HIERARCHY', max_influences=v['max_influences'], bind_method=_BIND_METHOD.get(v.get('bind_method'), 'CLOSEST_DISTANCE'), skinning={_dcc_source('Dual quaternion'): 'DUAL_QUATERNION', _dcc_source('Weight blended'): 'WEIGHT_BLENDED'}.get(v['skinning'], 'CLASSIC_LINEAR'), dropoff=v.get('dropoff', 4.0), maintain_max=v.get('maintain_max', True), normalize=_NORMALIZE[v['normalize']], remove_unused=v['remove_unused'], colorize=v['colorize'])

def _run_unbind(context, v):
    history = {_dcc_source('Delete history'): 'DELETE', _dcc_source('Keep history'): 'KEEP', _dcc_source('Bake history'): 'BAKE'}[v['history']]
    return bpy.ops.allset.unbind_skin('EXEC_DEFAULT', history=history, remove_colors=v['remove_colors'])
_SURFACE = {_dcc_source('Closest point on surface'): 'CLOSEST_POINT', _dcc_source('Ray cast'): 'RAY_CAST', _dcc_source('Closest component'): 'CLOSEST_COMPONENT'}
_INFLUENCE = {_dcc_source('Closest joint'): 'CLOSEST_JOINT', _dcc_source('Closest bone'): 'CLOSEST_BONE', _dcc_source('One to one'): 'ONE_TO_ONE', _dcc_source('Name'): 'NAME', _dcc_source('None'): 'NONE'}

def _run_copy_weights(context, v):
    return bpy.ops.allset.copy_skin_weights('EXEC_DEFAULT', surface=_SURFACE[v['surface']], influence1=_INFLUENCE[v['influence1']], influence2=_INFLUENCE[v['influence2']], influence3=_INFLUENCE[v['influence3']], normalize=v['normalize'])
_PAINT_OPS = {_dcc_source('Replace'): 'REPLACE', _dcc_source('Add'): 'ADD', _dcc_source('Scale'): 'SCALE', _dcc_source('Smooth'): 'SMOOTH'}
_PROFILES = {_dcc_source('Gaussian'): 'GAUSSIAN', _dcc_source('Soft'): 'SOFT', _dcc_source('Solid'): 'SOLID'}

def _run_paint(context, v):
    return bpy.ops.allset.paint_skin_weights('EXEC_DEFAULT', settings=True, operation=_PAINT_OPS[v['operation']], profile=_PROFILES[v['profile']], normalize=_NORMALIZE[v['normalize']], opacity=v['opacity'], value=v['value'], radius=v['radius'], screen_projection=v['screen_projection'], show_wireframe=v['show_wireframe'], xray_joints=v['xray_joints'])

def _run_blend_shape(context, v):
    return bpy.ops.allset.blend_shape('EXEC_DEFAULT', node_name=v['node_name'].strip(), origin=v['origin'].upper(), check_topology=v['check_topology'], delete_targets=v['delete_targets'])

def _run_aim(context, v):
    from . import rig_tools
    world_up = v['world_up_type']
    bone = context.mode == 'POSE'
    up_object = None
    if world_up in (_dcc_source('Object up'), _dcc_source('Object rotation up')):
        name = v.get('world_up_object', '').strip()
        if name:
            up_object = bpy.data.objects.get(name)
            if up_object is None:
                raise RuntimeError(f'World up object: no object named {name}')
    a = rig_tools.axis_of(rig_tools.local_axis(v['aim_vector'], bone))
    if a is None:
        raise RuntimeError(_dcc_source('Blender aims along an axis: the aim vector must be +-X, +-Y or +-Z'))
    if world_up != _dcc_source('None'):
        u = rig_tools.axis_of(rig_tools.local_axis(v['up_vector'], bone))
        if u is None or u[0] == a[0] or (u[1] < 0 and world_up != _dcc_source('Object up')):
            raise RuntimeError(_dcc_source("Blender turns the up vector along a local axis other than the aim vector's (a positive one unless World up type is Object up)"))
    res = bpy.ops.allset.constrain('EXEC_DEFAULT', type='TRACK_TO')
    con = _last_constraint(context)
    if res != {'FINISHED'} or con is None:
        return res
    owner = context.active_pose_bone if bone else context.active_object
    cons = owner.constraints
    if (tuple(v['aim_vector']), tuple(v['up_vector']), world_up, tuple(v['world_up_vector'])) != (rig_tools.AIM_VECTOR, rig_tools.UP_VECTOR, rig_tools.WORLD_UP, (0.0, 1.0, 0.0)):
        (target, sub, name) = (con.target, getattr(con, 'subtarget', ''), con.name)
        cons.remove(con)
        con = cons.new('TRACK_TO')
        (con.name, con.target) = (name, target)
        if sub:
            con.subtarget = sub
        con = rig_tools.aim(cons, con, v['aim_vector'], v['up_vector'], world_up, bone=bone, up_object=up_object, world_up_vector=v['world_up_vector'])
    con.influence = v['weight']
    companion = cons.get(con.name + rig_tools.UP_SUFFIX)
    if companion is not None:
        companion.influence = v['weight']
    return res

def _run_scale(context, v):
    res = _constraint('COPY_SCALE')(context, {**v, 'maintain_offset': False})
    con = _last_constraint(context)
    if res != {'FINISHED'} or con is None or con.type != 'COPY_SCALE':
        return res
    owner = context.active_pose_bone if context.mode == 'POSE' else context.active_object
    offset = Vector((v['offset'][0], v['offset'][2], v['offset'][1]))
    if v['maintain_offset']:
        target = con.target
        ts = target.pose.bones[con.subtarget].matrix.to_scale() if con.subtarget else target.matrix_world.to_scale()
        own = owner.scale.copy()
        offset = Vector([own[i] / ts[i] if abs(ts[i]) > 1e-09 else 1.0 for i in range(3)])
    if (offset - Vector((1.0, 1.0, 1.0))).length > 1e-09:
        con.use_offset = True
        owner.scale = offset
    return res

def _run_pole_vector(context, v):
    if abs(v['weight'] - 1.0) > 1e-09:
        raise RuntimeError(_dcc_source("Blender's IK pole target has no weight: the pole vector always counts fully (Weight 1)"))
    return bpy.ops.allset.pole_vector('EXEC_DEFAULT')
_ANIM_LAYER = (_dcc_source('Animation Layer'), _dcc_source('Set layer to override'))
WINDOWS = [Window('joint_tool', _dcc_source('Joint Tool'), _dcc_source('Create Joints'), None, [F('orient_world', '', 'bool', False, text=_zh_native('Orient Joint to World', 'MWK:operators/option_windows_rig.py:212'), translation_context='MWK:operators/option_windows_rig.py:212'), F('secondary_axis', _dcc_source('Secondary Axis:'), 'enum', 'Y', items=('X', 'Y', 'Z', _dcc_source('None')), translation_context='MWK:operators/option_windows_rig.py:213'), F('secondary_world', _dcc_source('Secondary Axis World Orientation:'), 'enum', 'Y', items=('X', 'Y', 'Z'), translation_context='MWK:operators/option_windows_rig.py:214'), F('secondary_sign', '', 'enum', '+', items=('+', '-'), translation_context='MWK:operators/option_windows_rig.py:215'), F('auto_secondary', '', 'bool', True, text=_zh_native('Auto orient secondary axis', 'MWK:operators/option_windows_rig.py:216'), translation_context='MWK:operators/option_windows_rig.py:216'), F('create_ik', '', 'bool', False, text=_zh_native('Create IK handle', 'MWK:operators/option_windows_rig.py:217'), translation_context='MWK:operators/option_windows_rig.py:217'), *_ik_fields('ik_')], _run_joint_tool, paths=('Skeleton/Create Joints',), missing=(_dcc_source('Degrees of freedom'), _dcc_source('Symmetry'), _dcc_source('Scale compensate'), _dcc_source('Auto joint limits'), _dcc_source('Variable Bone Radius Settings / Bone Radius Settings'), _dcc_source('Projected Centering'), _dcc_source("Primary Axis (always the bone's Y = Maya X)")) + _IK_MISSING, translation_context='MWK:operators/option_windows_rig.py:211'), Window('ik_handle_tool', _dcc_source('IK Handle Tool'), _dcc_source('Create IK Handle'), None, _ik_fields(), _run_ik_handle, paths=('Skeleton/Create IK Handle',), missing=_IK_MISSING, translation_context='MWK:operators/option_windows_rig.py:223'), Window('ik_spline_tool', _dcc_source('IK Spline Handle Tool'), _dcc_source('Create IK Spline Handle'), None, [F('root_on_curve', '', 'bool', True, text=_zh_native('Root on curve', 'MWK:operators/option_windows_rig.py:228'), translation_context='MWK:operators/option_windows_rig.py:228'), F('parent_curve', '', 'bool', True, text=_zh_native('Auto parent curve', 'MWK:operators/option_windows_rig.py:229'), translation_context='MWK:operators/option_windows_rig.py:229'), F('snap_curve', '', 'bool', False, text=_zh_native('Snap curve to root', 'MWK:operators/option_windows_rig.py:230'), translation_context='MWK:operators/option_windows_rig.py:230'), F('create_curve', '', 'bool', True, text=_zh_native('Auto create curve', 'MWK:operators/option_windows_rig.py:231'), translation_context='MWK:operators/option_windows_rig.py:231'), F('spans', _dcc_source('Number of spans:'), 'enum', '1', items=('1', '2', '3', '4'), translation_context='MWK:operators/option_windows_rig.py:232'), F('twist_type', _dcc_source('Twist type:'), 'enum', _dcc_source('Linear'), items=(_dcc_source('Linear'), _dcc_source('Ease In'), _dcc_source('Ease Out'), _dcc_source('Ease In Out')), translation_context='MWK:operators/option_windows_rig.py:234')], _run_ik_spline, paths=('Skeleton/Create IK Spline Handle',), missing=(_dcc_source('Auto create root axis'), _dcc_source('Auto simplify curve (the kit always fits the curve: on)'), _dcc_source('Root twist mode')), translation_context='MWK:operators/option_windows_rig.py:227'), Window('bind_skin_maya', _dcc_source('Bind Skin Options'), _dcc_source('Apply and Close'), ('allset.bind_skin', {}), [F('bind_to', _dcc_source('Bind to:'), 'enum', _dcc_source('Joint hierarchy'), items=(_dcc_source('Joint hierarchy'), _dcc_source('Selected joints')), translation_context='MWK:operators/option_windows_rig.py:240'), F('bind_method', _dcc_source('Bind method:'), 'enum', _dcc_source('Closest distance'), items=(_dcc_source('Closest distance'), _dcc_source('Closest in hierarchy'), _dcc_source('Heat Map')), translation_context='MWK:operators/option_windows_rig.py:241'), F('skinning', _dcc_source('Skinning method:'), 'enum', _dcc_source('Classic linear'), items=(_dcc_source('Classic linear'), _dcc_source('Dual quaternion'), _dcc_source('Weight blended')), translation_context='MWK:operators/option_windows_rig.py:243'), F('normalize', _dcc_source('Normalize weights:'), 'enum', _dcc_source('Interactive'), items=(_dcc_source('None'), _dcc_source('Interactive'), _dcc_source('Post')), translation_context='MWK:operators/option_windows_rig.py:245'), F('max_influences', _dcc_source('Max influences:'), 'int', 5, lo=1, hi=30, translation_context='MWK:operators/option_windows_rig.py:246'), F('maintain_max', '', 'bool', True, text=_zh_native('Maintain max influences', 'MWK:operators/option_windows_rig.py:248'), translation_context='MWK:operators/option_windows_rig.py:248'), F('dropoff', _dcc_source('Dropoff rate:'), 'float', 4.0, lo=0.1, hi=100.0, translation_context='MWK:operators/option_windows_rig.py:249'), F('remove_unused', '', 'bool', True, text=_zh_native('Remove unused influences', 'MWK:operators/option_windows_rig.py:250'), translation_context='MWK:operators/option_windows_rig.py:250'), F('colorize', '', 'bool', True, text=_zh_native('Colorize skeleton', 'MWK:operators/option_windows_rig.py:251'), translation_context='MWK:operators/option_windows_rig.py:251')], _run_bind, paths=('Skin/Bind Skin',), missing=(_dcc_source('Bind to: Object hierarchy'), _dcc_source('Bind method: Geodesic Voxel'), _dcc_source('Weight distribution'), _dcc_source('Allow multiple bind poses'), _dcc_source('Include hidden selections on creation'), _dcc_source('Deformer node')), translation_context='MWK:operators/option_windows_rig.py:239'), Window('unbind_skin', _dcc_source('Detach Skin Options'), _dcc_source('Detach'), ('allset.unbind_skin', {}), [F('history', _dcc_source('History:'), 'enum', _dcc_source('Delete history'), items=(_dcc_source('Delete history'), _dcc_source('Keep history'), _dcc_source('Bake history')), translation_context='MWK:operators/option_windows_rig.py:256'), F('remove_colors', _dcc_source('Coloring:'), 'bool', True, text=_zh_native('Remove joint colors', 'MWK:operators/option_windows_rig.py:257'), translation_context='MWK:operators/option_windows_rig.py:257')], _run_unbind, paths=('Skin/Unbind Skin',), translation_context='MWK:operators/option_windows_rig.py:255'), Window('copy_skin_weights', _dcc_source('Copy Skin Weights Options'), _dcc_source('Copy'), ('allset.copy_skin_weights', {}), [F('surface', _dcc_source('Surface Association:'), 'enum', _dcc_source('Closest point on surface'), items=(_dcc_source('Closest point on surface'), _dcc_source('Ray cast'), _dcc_source('Closest component')), translation_context='MWK:operators/option_windows_rig.py:261'), F('influence1', _dcc_source('Influence Association 1:'), 'enum', _dcc_source('Closest joint'), items=(_dcc_source('Closest joint'), _dcc_source('Closest bone'), _dcc_source('One to one'), _dcc_source('Name')), translation_context='MWK:operators/option_windows_rig.py:263'), F('influence2', _dcc_source('Influence Association 2:'), 'enum', _dcc_source('None'), items=(_dcc_source('None'), _dcc_source('Closest joint'), _dcc_source('Closest bone'), _dcc_source('One to one'), _dcc_source('Name')), translation_context='MWK:operators/option_windows_rig.py:265'), F('influence3', _dcc_source('Influence Association 3:'), 'enum', _dcc_source('None'), items=(_dcc_source('None'), _dcc_source('Closest joint'), _dcc_source('Closest bone'), _dcc_source('One to one'), _dcc_source('Name')), translation_context='MWK:operators/option_windows_rig.py:267'), F('normalize', '', 'bool', False, text=_zh_native('Normalize', 'MWK:operators/option_windows_rig.py:269'), translation_context='MWK:operators/option_windows_rig.py:269')], _run_copy_weights, paths=('Skin/Copy Skin Weights',), missing=(_dcc_source('Surface Association: UV space'), _dcc_source('Influence Association: Label')), translation_context='MWK:operators/option_windows_rig.py:260'), Window('paint_skin_weights', _dcc_source('Paint Skin Weights Tool'), _dcc_source('Paint Skin Weights'), None, [F('operation', _dcc_source('Paint operation:'), 'enum', _dcc_source('Replace'), items=(_dcc_source('Replace'), _dcc_source('Add'), _dcc_source('Scale'), _dcc_source('Smooth')), translation_context='MWK:operators/option_windows_rig.py:273'), F('profile', _dcc_source('Profile:'), 'enum', _dcc_source('Soft'), items=(_dcc_source('Gaussian'), _dcc_source('Soft'), _dcc_source('Solid')), translation_context='MWK:operators/option_windows_rig.py:274'), F('normalize', _dcc_source('Normalize Weights:'), 'enum', _dcc_source('Interactive'), items=(_dcc_source('Off'), _dcc_source('Interactive'), _dcc_source('Post')), translation_context='MWK:operators/option_windows_rig.py:275'), F('opacity', _dcc_source('Opacity:'), 'float', 1.0, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_rig.py:276'), F('value', _dcc_source('Value:'), 'float', 1.0, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_rig.py:276'), F('radius', _dcc_source('Radius(U):'), 'float', 1.0, lo=0.0001, hi=1000.0, translation_context='MWK:operators/option_windows_rig.py:277'), F('screen_projection', '', 'bool', False, text=_zh_native('Screen projection', 'MWK:operators/option_windows_rig.py:278'), translation_context='MWK:operators/option_windows_rig.py:278'), F('show_wireframe', '', 'bool', True, text=_zh_native('Show wireframe', 'MWK:operators/option_windows_rig.py:279'), translation_context='MWK:operators/option_windows_rig.py:279'), F('xray_joints', '', 'bool', True, text=_zh_native('XRay Joints', 'MWK:operators/option_windows_rig.py:280'), translation_context='MWK:operators/option_windows_rig.py:280')], _run_paint, paths=('Skin/Paint Skin Weights',), missing=(_dcc_source('Influences sort / filter (the vertex group list)'), _dcc_source('Mode: Select / Paint Select'), _dcc_source('Weight Type'), 'Min/Max value', _dcc_source('Gradient / color ramp'), _dcc_source('Radius(L)'), _dcc_source('Reflection'), _dcc_source('Stamp spacing / depth'), _dcc_source('Stylus pressure'), _dcc_source('Other display options')), translation_context='MWK:operators/option_windows_rig.py:272'), Window('blend_shape', _dcc_source('Blend Shape Options'), _dcc_source('Create'), ('allset.blend_shape', {}), [FText('node_name', _dcc_source('BlendShape node:')), F('origin', _dcc_source('Origin:'), 'enum', _dcc_source('Local'), items=(_dcc_source('Local'), _dcc_source('World')), translation_context='MWK:operators/option_windows_rig.py:287'), F('check_topology', '', 'bool', True, text=_zh_native('Check topology', 'MWK:operators/option_windows_rig.py:288'), translation_context='MWK:operators/option_windows_rig.py:288'), F('delete_targets', '', 'bool', False, text=_zh_native('Delete targets', 'MWK:operators/option_windows_rig.py:289'), translation_context='MWK:operators/option_windows_rig.py:289')], _run_blend_shape, paths=('Deform/Blend Shape',), missing=(_dcc_source('Envelope (Blender shape keys have no envelope)'), _dcc_source('Target shape options: In-between')), translation_context='MWK:operators/option_windows_rig.py:285'), Window('aim_constraint', _dcc_source('Aim Constraint Options'), _dcc_source('Add'), ('allset.constrain', {'type': 'TRACK_TO'}), [F('aim_vector', _dcc_source('Aim vector:'), 'vec3', (1.0, 0.0, 0.0), translation_context='MWK:operators/option_windows_rig.py:294'), F('up_vector', _dcc_source('Up vector:'), 'vec3', (0.0, 1.0, 0.0), translation_context='MWK:operators/option_windows_rig.py:294'), F('world_up_type', _dcc_source('World up type:'), 'enum', _dcc_source('Vector'), items=(_dcc_source('Scene up'), _dcc_source('Object up'), _dcc_source('Object rotation up'), _dcc_source('Vector'), _dcc_source('None')), translation_context='MWK:operators/option_windows_rig.py:295'), F('world_up_vector', _dcc_source('World up vector:'), 'vec3', (0.0, 1.0, 0.0), translation_context='MWK:operators/option_windows_rig.py:297'), FString('world_up_object', _dcc_source('World up object:')), F('weight', _dcc_source('Weight:'), 'float', 1.0, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_rig.py:299')], _run_aim, paths=('Constrain/Aim',), missing=(_dcc_source("Maintain offset / Offset (Blender's Track To has none)"),) + _ANIM_LAYER + (_dcc_source('Constraint axes (always All)'),), translation_context='MWK:operators/option_windows_rig.py:293'), Window('pole_vector', _dcc_source('Pole Vector Constraint Options'), _dcc_source('Add'), ('allset.pole_vector', {}), [F('weight', _dcc_source('Weight:'), 'float', 1.0, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_rig.py:304')], _run_pole_vector, paths=('Constrain/Pole Vector',), translation_context='MWK:operators/option_windows_rig.py:303'), Window('scale_constraint', _dcc_source('Scale Constraint Options'), _dcc_source('Add'), ('allset.constrain', {'type': 'COPY_SCALE'}), [F('maintain_offset', _dcc_source('Maintain offset:'), 'bool', False, translation_context='MWK:operators/option_windows_rig.py:307'), F('offset', _dcc_source('Offset:'), 'vec3', (1.0, 1.0, 1.0), translation_context='MWK:operators/option_windows_rig.py:307'), F('all', _dcc_source('Constraint axes:'), 'bool', True, text=_zh_native('All', 'MWK:operators/option_windows_rig.py:308'), translation_context='MWK:operators/option_windows_rig.py:308'), F('x', '', 'bool', False, text=_zh_native('X', 'MWK:operators/option_windows_rig.py:308'), translation_context='MWK:operators/option_windows_rig.py:308'), F('y', '', 'bool', False, text=_zh_native('Y', 'MWK:operators/option_windows_rig.py:309'), translation_context='MWK:operators/option_windows_rig.py:309'), F('z', '', 'bool', False, text=_zh_native('Z', 'MWK:operators/option_windows_rig.py:309'), translation_context='MWK:operators/option_windows_rig.py:309'), F('weight', _dcc_source('Weight:'), 'float', 1.0, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_rig.py:310')], _run_scale, paths=('Constrain/Scale',), missing=_ANIM_LAYER, translation_context='MWK:operators/option_windows_rig.py:306')]
