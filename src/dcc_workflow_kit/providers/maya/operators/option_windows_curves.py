# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Step 156: Maya option windows of the Curves menu and Create > Curve Tools (same spec as operators/option_windows.py;
option_windows._extend appends ``WINDOWS``). Titles, fields and factory values from Maya's option windows
(each option with its factory value). Fields Blender / the kit can't follow are listed as ``missing``."""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
from .option_windows import F, Window

def _run_rebuild(context, v):
    return bpy.ops.allset.curve_rebuild('EXEC_DEFAULT', spans=v['spans'], degree=v['degree'].split()[0])

def _run_attach(context, v):
    return bpy.ops.allset.curve_attach('EXEC_DEFAULT', method=v['method'].upper(), bias=v['bias'], keep_originals='ON' if v['keep_originals'] else 'OFF')

def _run_fillet(context, v):
    return bpy.ops.allset.curve_fillet('EXEC_DEFAULT', radius=v['radius'])

def _run_cv_tool(context, v):
    return bpy.ops.allset.cv_curve_tool('INVOKE_DEFAULT', degree=int(v['degree'].split()[0]))

def _run_ep_tool(context, v):
    return bpy.ops.allset.ep_curve_tool('INVOKE_DEFAULT', degree=int(v['degree'].split()[0]))
DEGREES = (_dcc_source('1 Linear'), '2', _dcc_source('3 Cubic'), '5', '7')
WINDOWS = [Window('rebuild_curve', _dcc_source('Rebuild Curve Options'), _dcc_source('Rebuild'), ('allset.curve_rebuild', {}), [F('spans', _dcc_source('Number of spans:'), 'int', 4, lo=1, hi=1000, translation_context='MWK:operators/option_windows_curves.py:39'), F('degree', _dcc_source('Degree:'), 'enum', _dcc_source('3 Cubic'), items=(_dcc_source('1 Linear'), '2', _dcc_source('3 Cubic'), '5', '7'), translation_context='MWK:operators/option_windows_curves.py:40')], _run_rebuild, paths=('Curves/Rebuild',), missing=(_dcc_source('Rebuild type: Reduce / Match knots / No multiple knots / Curvature / End conditions / Clean (Uniform only)'), _dcc_source('Parameter range: Keep / 0 to #spans (0 to 1 only)'), _dcc_source('Keep: CVs / Tangents / NumSpans (Ends always kept)'), _dcc_source('Keep original (off)')), translation_context='MWK:operators/option_windows_curves.py:38'), Window('attach_curves', _dcc_source('Attach Curves Options'), _dcc_source('Attach'), ('allset.curve_attach', {}), [F('method', _dcc_source('Attach method:'), 'enum', _dcc_source('Blend'), items=(_dcc_source('Connect'), _dcc_source('Blend')), translation_context='MWK:operators/option_windows_curves.py:47'), F('bias', _dcc_source('Blend bias:'), 'float', 0.5, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_curves.py:48'), F('keep_originals', '', 'bool', True, text=_zh_native('Keep originals', 'MWK:operators/option_windows_curves.py:49'), translation_context='MWK:operators/option_windows_curves.py:49')], _run_attach, paths=('Curves/Attach',), missing=(_dcc_source('Multiple knots: Keep / Remove (Keep)'), _dcc_source('Insert knot / Insert parameter (off, 0.1)')), translation_context='MWK:operators/option_windows_curves.py:46'), Window('fillet_curve', _dcc_source('Fillet Curve Options'), _dcc_source('Fillet'), ('allset.curve_fillet', {}), [F('radius', _dcc_source('Radius:'), 'float', 1.0, lo=0.0001, hi=1000.0, translation_context='MWK:operators/option_windows_curves.py:54')], _run_fillet, paths=('Curves/Fillet',), missing=(_dcc_source('Trim / Join (off)'), _dcc_source('Construction: Freeform (Circular only)'), _dcc_source('Keep originals (off)')), translation_context='MWK:operators/option_windows_curves.py:53'), Window('cv_curve_tool', _dcc_source('CV Curve Tool'), _dcc_source('Create Curve'), None, [F('degree', _dcc_source('Curve degree:'), 'enum', _dcc_source('3 Cubic'), items=DEGREES, translation_context='MWK:operators/option_windows_curves.py:59')], _run_cv_tool, paths=('Create/Curve Tools/CV Curve Tool',), missing=(_dcc_source('Knot spacing: Uniform (Chord length not in the tool)'), _dcc_source('Multiple end knots (always on)')), translation_context='MWK:operators/option_windows_curves.py:58'), Window('ep_curve_tool', _dcc_source('EP Curve Tool'), _dcc_source('Create Curve'), None, [F('degree', _dcc_source('Curve degree:'), 'enum', _dcc_source('3 Cubic'), items=(_dcc_source('1 Linear'), _dcc_source('3 Cubic')), translation_context='MWK:operators/option_windows_curves.py:63')], _run_ep_tool, paths=('Create/Curve Tools/EP Curve Tool',), missing=(_dcc_source('Knot spacing: Uniform (Chord length not in the tool)'), _dcc_source('Multiple end knots (always on)')), translation_context='MWK:operators/option_windows_curves.py:62')]
