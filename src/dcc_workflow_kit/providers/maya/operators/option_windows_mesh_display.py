# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Maya option windows of the Mesh Display menu (step 189): Set Vertex Normal, Average, Set to Face, Apply Color.

Fields and factory values: Maya's (option vars of the perform scripts).
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
from .option_windows import F, Window
from .option_windows_display import FColor

def _run_set_normal(context, v):
    (x, y, z) = v['normal']
    return bpy.ops.allset.set_vertex_normal('EXEC_DEFAULT', x=x, y=y, z=z)

def _run_average(context, v):
    return bpy.ops.allset.average_normals('EXEC_DEFAULT', distance=v['distance'])

def _run_to_face(context, v):
    return bpy.ops.allset.set_to_face_normal('EXEC_DEFAULT', user_normal=v['user_normal'])
_OPS = {_dcc_source('Replace'): 'REPLACE', _dcc_source('Add'): 'ADD', _dcc_source('Subtract'): 'SUBTRACT', _dcc_source('Remove'): 'REMOVE'}

def _run_apply_color(context, v):
    return bpy.ops.allset.apply_color('EXEC_DEFAULT', operation=_OPS[v['operation']], color=v['color'], alpha=v['alpha'])
_BLENDS = (_dcc_source('Overwrite'), _dcc_source('Add'), _dcc_source('Subtract'), _dcc_source('Multiply'), _dcc_source('Divide'), _dcc_source('Average'))

def _run_prelight(context, v):
    return bpy.ops.allset.prelight('EXEC_DEFAULT', use_options=True, bake_color=v['bake_color'], bake_alpha=v['bake_alpha'], color_blending=_BLENDS.index(v['color_blending']), alpha_blending=_BLENDS.index(v['alpha_blending']), scale_rgba=v['scale_rgba'])

class FApplyColor(FColor):
    """Apply Color's colour: Maya stores the value as is (0.5 grey, any float)."""

    def __init__(self):
        super().__init__('color', _dcc_source('Color value:'), (0.5, 0.5, 0.5))
WINDOWS = [Window('set_vertex_normal', _dcc_source('Set Vertex Normal Options'), _dcc_source('Set Normal'), ('allset.set_vertex_normal', {}), [F('normal', _dcc_source('Vertex normal:'), 'vec3', (1.0, 0.0, 0.0), translation_context='MWK:operators/option_windows_mesh_display.py:55')], _run_set_normal, paths=('Mesh Display/Set Vertex Normal',), translation_context='MWK:operators/option_windows_mesh_display.py:54'), Window('average_normals', _dcc_source('Average Normals Options'), _dcc_source('Average'), ('allset.average_normals', {}), [F('distance', _dcc_source('Distance:'), 'float', 0.1, lo=0.0, hi=10.0, translation_context='MWK:operators/option_windows_mesh_display.py:59')], _run_average, paths=('Mesh Display/Average',), missing=(_dcc_source('Normalize: Before / After / Not (Before)'), _dcc_source('Allow zero normals / Replace zero normal with (1, 0, 0)')), translation_context='MWK:operators/option_windows_mesh_display.py:58'), Window('set_to_face', _dcc_source('Set to Face Normal Options'), _dcc_source('Set to Face'), ('allset.set_to_face_normal', {}), [F('user_normal', '', 'bool', False, text=_zh_native('Set user normal', 'MWK:operators/option_windows_mesh_display.py:64'), translation_context='MWK:operators/option_windows_mesh_display.py:64')], _run_to_face, paths=('Mesh Display/Set to Face',), translation_context='MWK:operators/option_windows_mesh_display.py:63'), Window('apply_color', _dcc_source('Apply Color Options'), _dcc_source('Apply Color'), ('allset.apply_color', {}), [F('operation', _dcc_source('Operation:'), 'enum', _dcc_source('Replace'), items=tuple(_OPS), translation_context='MWK:operators/option_windows_mesh_display.py:68'), FApplyColor(), F('alpha', _dcc_source('Alpha value:'), 'float', 1.0, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_mesh_display.py:70')], _run_apply_color, paths=('Mesh Display/Apply Color',), missing=(_dcc_source('Individual channels (Red / Green / Blue / Alpha each on its own)'),), translation_context='MWK:operators/option_windows_mesh_display.py:67'), Window('prelight', _dcc_source('Prelight (Maya) Options'), _dcc_source('Prelight'), ('allset.prelight', {}), [F('bake_color', '', 'bool', True, text=_zh_native('Bake shading group lighting', 'MWK:operators/option_windows_mesh_display.py:75'), translation_context='MWK:operators/option_windows_mesh_display.py:75'), F('bake_alpha', '', 'bool', False, text=_zh_native('Bake alpha', 'MWK:operators/option_windows_mesh_display.py:76'), translation_context='MWK:operators/option_windows_mesh_display.py:76'), F('color_blending', _dcc_source('Color blending:'), 'enum', _dcc_source('Overwrite'), items=_BLENDS, translation_context='MWK:operators/option_windows_mesh_display.py:77'), F('alpha_blending', _dcc_source('Alpha blending:'), 'enum', _dcc_source('Overwrite'), items=_BLENDS, translation_context='MWK:operators/option_windows_mesh_display.py:78'), F('scale_rgba', _dcc_source('Scale RGBA:'), 'float', 1.0, lo=0.0, hi=10.0, translation_context='MWK:operators/option_windows_mesh_display.py:79')], _run_prelight, paths=('Mesh Display/Prelight (Maya)',), missing=(_dcc_source('Sample by face / Shared vertices / Normal direction'), _dcc_source('Ambient occlusion rays / falloff'), _dcc_source('Clamp min / max'), _dcc_source('Filter size / sample')), translation_context='MWK:operators/option_windows_mesh_display.py:74')]
