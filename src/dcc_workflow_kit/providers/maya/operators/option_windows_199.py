# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Step 199 (#106): Maya option windows of the new Skin / Constrain commands.

Titles, buttons, labels and factory values from Maya 2022's option windows.
Fields the kit can't honour
are listed (``missing``), never faked.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
from mathutils import Vector
from .option_windows import F, Window
WORLD_UP = (_dcc_source('Scene up'), _dcc_source('Vector'), _dcc_source('None'))

def _aim_like(op_name):

    def run(context, v):
        up = Vector(v['world_up_vector'])
        if v['world_up_type'] == _dcc_source('Vector') and (up.length < 1e-09 or (up.normalized() - Vector((0, 1, 0))).length > 1e-06):
            raise RuntimeError(_dcc_source('The kit turns the up vector towards the scene up only: World up vector must be 0 1 0 (Maya Y)'))
        return getattr(bpy.ops.allset, op_name)('EXEC_DEFAULT', weight=v['weight'], aim_vector=v['aim_vector'], up_vector=v['up_vector'], world_up_type=v['world_up_type'])
    return run

def _aim_fields():
    return [F('aim_vector', _dcc_source('Aim vector:'), 'vec3', (1.0, 0.0, 0.0), translation_context='MWK:operators/option_windows_199.py:32'), F('up_vector', _dcc_source('Up vector:'), 'vec3', (0.0, 1.0, 0.0), translation_context='MWK:operators/option_windows_199.py:33'), F('world_up_type', _dcc_source('World up type:'), 'enum', _dcc_source('Vector'), items=WORLD_UP, translation_context='MWK:operators/option_windows_199.py:34'), F('world_up_vector', _dcc_source('World up vector:'), 'vec3', (0.0, 1.0, 0.0), translation_context='MWK:operators/option_windows_199.py:35'), F('weight', _dcc_source('Weight:'), 'float', 1.0, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_199.py:36')]
_AIM_MISSING = (_dcc_source('World up type: Object up / Object rotation up'), _dcc_source('World up object'))
REMOVE_TYPES = ((_dcc_source('point'), _dcc_source('Point constraint')), ('orient', _dcc_source('Orient constraint')), ('aim', _dcc_source('Aim constraint')), ('scale', _dcc_source('Scale constraint')), ('parent', _dcc_source('Parent constraint')), ('geometry', _dcc_source('Geometry constraint')), ('normal', _dcc_source('Normal constraint')), ('tangent', _dcc_source('Tangent constraint')), ('pole_vector', _dcc_source('Pole vector constraint')))

def _run_remove(context, v):
    kw = {k: v[k] for (k, _l) in REMOVE_TYPES}
    return bpy.ops.allset.remove_constraint_target('EXEC_DEFAULT', remove_all=v['remove_all'], **kw)

def _run_axes(context, v):
    return bpy.ops.allset.modify_constraint_axes('EXEC_DEFAULT', x=v['x'], y=v['y'], z=v['z'], maintain_offset=v['maintain_offset'])

def _run_substitute(context, v):
    return bpy.ops.allset.substitute_geometry('EXEC_DEFAULT', reweight_distance=v['reweight_distance'], retain_old=v['retain_old'], disable_non_skin=v['disable_non_skin'])
WINDOWS = [Window('normal_constraint', _dcc_source('Normal Constraint Options'), _dcc_source('Add'), ('allset.normal_constraint', {}), _aim_fields(), _aim_like('normal_constraint'), paths=('Constrain/Normal',), missing=_AIM_MISSING, translation_context='MWK:operators/option_windows_199.py:64'), Window('tangent_constraint', _dcc_source('Tangent Constraint Options'), _dcc_source('Add'), ('allset.tangent_constraint', {}), _aim_fields(), _aim_like('tangent_constraint'), paths=('Constrain/Tangent',), missing=_AIM_MISSING, translation_context='MWK:operators/option_windows_199.py:66'), Window('remove_constraint_target', _dcc_source('Remove Target Options'), _dcc_source('Remove'), ('allset.remove_constraint_target', {}), [F('remove_all', _dcc_source('Constraint type:'), 'bool', True, text=_zh_native('All', 'MWK:operators/option_windows_199.py:70'), translation_context='MWK:operators/option_windows_199.py:70')] + [F(k, '', 'bool', True, text=_zh_native(label, 'MWK:operators/option_windows_199.py:71'), translation_context='MWK:operators/option_windows_199.py:71') for (k, label) in REMOVE_TYPES], _run_remove, paths=('Constrain/Remove Target',), missing=(_dcc_source("Point on poly constraint (the kit's is a Shrinkwrap = Geometry)"), _dcc_source('Maintain offset')), translation_context='MWK:operators/option_windows_199.py:69'), Window('modify_constraint_axes', _dcc_source('Modify Constrained Axis Options'), _dcc_source('Modify'), ('allset.modify_constraint_axes', {}), [F('x', _dcc_source('Constrain:'), 'bool', True, text=_zh_native('X', 'MWK:operators/option_windows_199.py:77'), translation_context='MWK:operators/option_windows_199.py:77'), F('y', '', 'bool', True, text=_zh_native('Y', 'MWK:operators/option_windows_199.py:77'), translation_context='MWK:operators/option_windows_199.py:77'), F('z', '', 'bool', True, text=_zh_native('Z', 'MWK:operators/option_windows_199.py:78'), translation_context='MWK:operators/option_windows_199.py:78'), F('maintain_offset', '', 'bool', False, text=_zh_native('Maintain offset', 'MWK:operators/option_windows_199.py:78'), translation_context='MWK:operators/option_windows_199.py:78')], _run_axes, paths=('Constrain/Modify Constrained Axis...',), translation_context='MWK:operators/option_windows_199.py:75'), Window('substitute_geometry', _dcc_source('Substitute Geometry Options'), _dcc_source('Substitute Geometry'), ('allset.substitute_geometry', {}), [F('reweight_distance', _dcc_source('Re-weighting distance tolerance:'), 'float', 1.0, lo=0.0, hi=10.0, translation_context='MWK:operators/option_windows_199.py:83'), F('disable_non_skin', '', 'bool', False, text=_zh_native('Disable non-skin deformers', 'MWK:operators/option_windows_199.py:84'), translation_context='MWK:operators/option_windows_199.py:84'), F('retain_old', '', 'bool', False, text=_zh_native('Retain old geometry', 'MWK:operators/option_windows_199.py:85'), translation_context='MWK:operators/option_windows_199.py:85')], _run_substitute, paths=('Skin/Substitute Geometry',), missing=(_dcc_source('Move new geometry to a layer'), _dcc_source('Move old geometry to a layer')), translation_context='MWK:operators/option_windows_199.py:81')]
