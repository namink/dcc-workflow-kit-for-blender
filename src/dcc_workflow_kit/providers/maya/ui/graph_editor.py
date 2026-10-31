# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Maya Graph Editor toolbar: tangent buttons and buffer curves in the Graph Editor header (docs/steps/step_70.md).

Maya's Graph Editor has a toolbar of tangent buttons (Auto, Spline, Clamped, Linear, Flat, Stepped, Plateau, then
Break / Unify) and buffer curve buttons.
Blender has the same settings two menus deep (Key > Interpolation Mode / Handle Type), so a row of buttons is
appended to ``GRAPH_HT_header`` (removed on unregister). Buffer curves = Blender ghost curves (a snapshot shown
behind the curves; Maya's Swap Buffer Curve has no counterpart).
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
import bpy
TANGENT_BUTTONS = (('AUTO', 'HANDLE_AUTOCLAMPED'), ('SPLINE', 'IPO_BEZIER'), ('CLAMPED', 'HANDLE_AUTO'), ('LINEAR', 'IPO_LINEAR'), ('FLAT', 'IPO_SINE'), ('STEPPED', 'IPO_CONSTANT'), ('PLATEAU', 'IPO_EASE_IN_OUT'))
HANDLE_BUTTONS = (('BREAK', 'HANDLE_FREE'), ('UNIFY', 'HANDLE_ALIGNED'))
BUFFER_NOTE = _dcc_source("Buffer curve = Blender ghost curve (display only; Swap Buffer Curve isn't available)")

def draw_toolbar(self, context):
    space = context.space_data
    if space is None or space.type != 'GRAPH_EDITOR' or space.mode != 'FCURVES':
        return
    from . import editor_chrome
    if editor_chrome.enabled(context):
        return
    layout = self.layout
    layout.separator()
    row = layout.row(align=True)
    for (kind, icon) in TANGENT_BUTTONS:
        row.operator('allset.set_tangent', text=_dcc_display(''), icon=icon).kind = kind
    row = layout.row(align=True)
    for (kind, icon) in HANDLE_BUTTONS:
        row.operator('allset.set_tangent', text=_dcc_display(''), icon=icon).kind = kind
    row = layout.row(align=True)
    row.operator('graph.ghost_curves_create', text=_dcc_display(''), icon='GHOST_ENABLED')
    row.operator('graph.ghost_curves_clear', text=_dcc_display(''), icon='GHOST_DISABLED')

def register():
    bpy.types.GRAPH_HT_header.append(draw_toolbar)

def unregister():
    bpy.types.GRAPH_HT_header.remove(draw_toolbar)
