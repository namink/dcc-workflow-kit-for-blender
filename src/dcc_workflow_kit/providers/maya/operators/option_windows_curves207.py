# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Step 207: Maya option windows of Curves > Bend / Curl / Scale Curvature (same spec as operators/option_windows.py).
Titles, labels and factory values: Maya's Bend / Curl / Scale Curvature Options windows."""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
import bpy
from .option_windows import F, Window

def _run(kind, a, b):

    def run(context, v):
        return bpy.ops.allset.curve_modify('EXEC_DEFAULT', kind=kind, amount=v[a], second=v[b])
    return run
WINDOWS = [Window('bend_curves', _dcc_source('Bend Curves Options'), _dcc_source('Bend Curves'), None, [F('amount', _dcc_source('Bend amount:'), 'float', 0.2, lo=-10.0, hi=10.0, translation_context='MWK:operators/option_windows_curves207.py:18'), F('twist', _dcc_source('Twist:'), 'float', 0.0, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_curves207.py:19')], _run('BEND', 'amount', 'twist'), paths=('Curves/Bend',), translation_context='MWK:operators/option_windows_curves207.py:17'), Window('curl_curves', _dcc_source('Curl Curves Options'), _dcc_source('Curl Curves'), None, [F('amount', _dcc_source('Curl amount:'), 'float', 0.3, lo=-10.0, hi=10.0, translation_context='MWK:operators/option_windows_curves207.py:22'), F('frequency', _dcc_source('Curl frequency:'), 'float', 1.0, lo=0.0, hi=100.0, translation_context='MWK:operators/option_windows_curves207.py:23')], _run('CURL', 'amount', 'frequency'), paths=('Curves/Curl',), translation_context='MWK:operators/option_windows_curves207.py:21'), Window('scale_curvature', _dcc_source('Scale Curvature Options'), _dcc_source('Scale Curvature'), None, [F('factor', _dcc_source('Scale factor:'), 'float', 1.1, lo=0.0, hi=10.0, translation_context='MWK:operators/option_windows_curves207.py:26'), F('max_curvature', _dcc_source('Max curvature:'), 'float', 0.8, lo=0.0, hi=10.0, translation_context='MWK:operators/option_windows_curves207.py:27')], _run('CURVATURE', 'factor', 'max_curvature'), paths=('Curves/Scale Curvature',), translation_context='MWK:operators/option_windows_curves207.py:25')]
