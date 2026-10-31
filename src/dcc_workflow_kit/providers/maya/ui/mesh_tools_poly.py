# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Quad Draw, Create Polygon and Append to Polygon as kit tools (docs/steps/step_144_poly.md 「계획」, GitHub #30).

The tools run the modals of operators/quad_draw.py and operators/poly_draw.py; their Maya Tool Settings (fields and
factory values of Maya 2022) are drawn here, in Blender's tool header / Tool tab and in the kit's
Tool Settings dock (ui/tool_settings.py kinds QUAD_DRAW / CREATE_POLYGON / APPEND_POLYGON).
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
from . import notices
from ..operators import poly_draw, quad_draw
_LIVE = _dcc_source('Blender draws the edited mesh with its Retopology overlay (over the surface, theme colours)')
GREY = {'Quad Draw/Wireframe Overlay': (_dcc_source('Retopology overlay'), _LIVE), 'Quad Draw/Mesh Color': (_dcc_source('Retopology overlay'), _LIVE), 'Quad Draw/Mesh Alpha': (_dcc_source('Retopology overlay'), _LIVE), 'Quad Draw/Surface Offset': (_dcc_source('Overlays > Retopology > Offset'), _dcc_source("Set the offset in the viewport's Overlays popover")), 'Quad Draw/Tab+MMB in empty space': (_dcc_source('Quad Strip Width'), _dcc_source('Strips are as wide as Quad Strip Width; change it here')), 'Quad Draw/Ctrl+Shift+RMB': (_dcc_source('this Tool Settings dock'), _dcc_source("Quad Draw's options marking menu isn't in the kit")), 'Append to Polygon/Rotation angle': (_dcc_source('Rotate afterwards'), _dcc_source('Maya keeps this field greyed in the tool too'))}
QUAD_DRAW_SHORTCUTS = (('(outside the quad mesh)', ''), (_dcc_source('LMB'), 'click to drop dots'), ('LMB / MMB', 'drag to tweak dots'), ('Ctrl + Shift + LMB', 'delete dots'), ('Tab + LMB', 'drag to draw quad strips'), ('Shift + LMB', 'click between dots to create geometry'), ('(inside the quad mesh)', ''), ('LMB / MMB', 'drag to tweak components'), ('Ctrl + LMB', 'click edge to insert loop'), ('Ctrl + MMB', 'click edge to insert centred loop'), ('Shift + LMB', 'drag to relax points'), ('Shift + MMB', 'drag to relax highlighted points'), ('Tab + LMB', 'drag to extend border edge (Extend: Loop = the border)'), ('Tab + MMB', 'drag to extend border edge loop'), ('Ctrl + Shift + LMB', 'click or drag across faces to delete'), ('Ctrl + Shift + LMB', 'click edge to delete edge loop'), ('Ctrl + Shift + MMB', 'drag edge to tweak edge loop'), ('Esc', 'leave the tool'))
CREATE_SHORTCUTS = ((_dcc_source('Click'), 'place a point (drag to move it)'), (_dcc_source('Middle-drag'), 'move the last point'), (_dcc_source('Backspace / Delete'), 'remove the last point'), ('Enter', 'complete the polygon (the tool stays)'), ('Esc', 'drop the points; with none, leave the tool'))
APPEND_SHORTCUTS = ((_dcc_source('Click a border edge'), 'start the new face there'), (_dcc_source('Click'), 'place a point / add another border edge'), (_dcc_source('Backspace / Delete'), 'remove the last point'), ('Enter', 'add the face (the tool stays)'), ('Esc', 'drop the points; with none, leave the tool'))
DESCRIPTIONS = {'CREATE_POLYGON': (_dcc_source('Click to place each point of the polygon,'), _dcc_source('then press Enter.')), 'APPEND_POLYGON': (_dcc_source('Click a border edge, then click to place points'), _dcc_source('or click more border edges; Enter adds the face.'))}

def _row(layout, label):
    split = layout.split(factor=0.42, align=True)
    left = split.row()
    left.alignment = 'RIGHT'
    left.label(text=_zh(label, 'MWK:ui/mesh_tools_poly.py:75'))
    return split.row(align=True)

def _grey(layout, key, text, check=None):
    row = layout.row()
    row.enabled = False
    icon = 'NONE' if check is None else 'CHECKBOX_HLT' if check else 'CHECKBOX_DEHLT'
    row.operator('allset.menu_unavailable', text=_zh(text, 'MWK:ui/mesh_tools_poly.py:83'), icon=icon, emboss=False).item = key

def draw_quad_draw(layout, context, header=False):
    s = poly_draw.settings(context)
    if header:
        layout.prop(s, 'qd_auto_weld', text=_zh('Auto-weld', 'MWK:ui/mesh_tools_poly.py:89'))
        layout.prop(s, 'qd_relax', text=_dcc_display(''))
        layout.prop(s, 'qd_extend', text=_dcc_display(''))
        return
    row = _row(layout, _dcc_source('Auto-weld:'))
    row.prop(s, 'qd_auto_weld', text=_dcc_display(''))
    sub = row.row(align=True)
    sub.active = s.qd_auto_weld
    sub.prop(s, 'qd_weld_px', text=_dcc_display(''))
    _row(layout, _dcc_source('Relax:')).prop(s, 'qd_relax', text=_dcc_display(''))
    _row(layout, _dcc_source('Extend:')).prop(s, 'qd_extend', text=_dcc_display(''))
    _row(layout, _dcc_source('Quad Strip Width:')).prop(s, 'qd_strip_width', text=_dcc_display(''))
    _row(layout, '').operator('allset.quad_draw_clear_dots', text=_zh('Clear Dots', 'MWK:ui/mesh_tools_poly.py:101'))

def draw_live(layout, context):
    """Live Constraint Options (Maya factory: Wireframe Overlay on black, Mesh Color on blue, Mesh Alpha 0.75,
    Surface Offset off 0, Snap to Backfaces off)."""
    s = poly_draw.settings(context)
    _grey(_row(layout, _dcc_source('Wireframe Overlay:')), 'Quad Draw/Wireframe Overlay', _dcc_source('on'), check=True)
    _grey(_row(layout, _dcc_source('Mesh Color:')), 'Quad Draw/Mesh Color', _dcc_source('on'), check=True)
    _grey(_row(layout, _dcc_source('Mesh Alpha:')), 'Quad Draw/Mesh Alpha', '0.7500', check=True)
    _grey(_row(layout, _dcc_source('Surface Offset:')), 'Quad Draw/Surface Offset', '0.0000', check=False)
    _row(layout, _dcc_source('Snap to Backfaces:')).prop(s, 'qd_snap_backfaces', text=_dcc_display(''))
    live = getattr(context.scene, 'allset_live', None)
    _row(layout, _dcc_source('Live surface:')).label(text=_zh(live.name if live is not None else 'None (other visible meshes)', 'MWK:ui/mesh_tools_poly.py:114'))

def _limit(layout, s, prefix):
    _row(layout, '').prop(s, f'{prefix}_limit_on')
    row = _row(layout, _dcc_source('Limit points to:'))
    row.active = getattr(s, f'{prefix}_limit_on')
    row.prop(s, f'{prefix}_limit_points', text=_dcc_display(''))

def draw_create(layout, context, header=False):
    s = poly_draw.settings(context)
    if header:
        layout.prop(s, 'cp_divisions')
        layout.prop(s, 'cp_keep_planar')
        return
    _row(layout, _dcc_source('Divisions:')).prop(s, 'cp_divisions', text=_dcc_display(''))
    _row(layout, '').prop(s, 'cp_keep_planar')
    _limit(layout, s, 'cp')
    _row(layout, _dcc_source('Texture space:')).column(align=True).prop(s, 'cp_texture', expand=True)

def draw_append(layout, context, header=False):
    s = poly_draw.settings(context)
    if header:
        layout.prop(s, 'ap_divisions')
        layout.prop(s, 'ap_keep_planar')
        return
    _row(layout, _dcc_source('Divisions:')).prop(s, 'ap_divisions', text=_dcc_display(''))
    _grey(_row(layout, _dcc_source('Rotation angle:')), 'Append to Polygon/Rotation angle', '0.0000')
    _row(layout, '').prop(s, 'ap_keep_planar')
    _limit(layout, s, 'ap')
    _row(layout, _dcc_source('Texture space:')).column(align=True).prop(s, 'ap_texture', expand=True)

def draw_description(layout, kind):
    col = layout.column(align=True)
    for line in DESCRIPTIONS.get(kind, ()):
        col.label(text=_zh(line, 'MWK:ui/mesh_tools_poly.py:152'))

def draw_shortcuts(layout, rows):
    col = layout.column(align=True)
    for (key, what) in rows:
        split = col.split(factor=0.42)
        split.label(text=_zh(key, 'MWK:ui/mesh_tools_poly.py:159'))
        split.label(text=_zh(what, 'MWK:ui/mesh_tools_poly.py:160'))
    if rows is QUAD_DRAW_SHORTCUTS:
        _grey(col, 'Quad Draw/Tab+MMB in empty space', _dcc_source('Tab + MMB outside the mesh: drag to resize quad strips'))
        _grey(col, 'Quad Draw/Ctrl+Shift+RMB', _dcc_source('Ctrl + Shift + RMB: Quad Draw options'))

def _hover_items():
    items = [('allset.quad_draw_hover', {'type': 'MOUSEMOVE', 'value': 'ANY', 'any': True}, None)]
    for key in ('LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_SHIFT', 'RIGHT_SHIFT'):
        for value in ('PRESS', 'RELEASE'):
            items.append(('allset.quad_draw_hover', {'type': key, 'value': value, 'any': True}, None))
    return tuple(items)

class ALLSET_TL_quad_draw(bpy.types.WorkSpaceTool):
    """Maya Quad Draw (docs/steps/step_144_poly.md): dots on the live surface, Shift = fill / relax, Ctrl = loop,
    Ctrl+Shift = delete, Tab+drag = extend / strip. No select fallback: Maya's Quad Draw LMB doesn't select."""
    bl_translation_context = 'MWK:ui/mesh_tools_poly.py:180'
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'EDIT_MESH'
    bl_idname = quad_draw.TOOL
    bl_label = _zh_native('Quad Draw', 'MWK:ui/mesh_tools_poly.py:180')
    bl_description = _zh_native('Click on the live surface to place dots, Shift+click between them to fill a quad. Drag = move, Shift+drag = relax, Ctrl+click = edge loop, Ctrl+Shift+click = delete, Tab+drag = extend a border / quad strip (Maya Quad Draw)', 'MWK:ui/mesh_tools_poly.py:180')
    bl_icon = 'ops.mesh.polybuild_hover'
    bl_widget = None
    bl_keymap = (('allset.quad_draw', {'type': 'LEFTMOUSE', 'value': 'PRESS', 'any': True}, None), ('allset.quad_draw', {'type': 'MIDDLEMOUSE', 'value': 'PRESS', 'any': True}, {'properties': [('middle', True)]}), ('allset.quad_draw_tab', {'type': 'TAB', 'value': 'PRESS'}, None), ('allset.quad_draw_exit', {'type': 'ESC', 'value': 'PRESS'}, None), *_hover_items())

    @staticmethod
    def draw_settings(context, layout, tool):
        draw_quad_draw(layout, context, header=context.region.type == 'TOOL_HEADER')

def _create_keymap():
    return (('allset.create_polygon', {'type': 'LEFTMOUSE', 'value': 'PRESS'}, None), ('allset.poly_tool_exit', {'type': 'ESC', 'value': 'PRESS'}, None))

class ALLSET_TL_create_polygon(bpy.types.WorkSpaceTool):
    """Maya Create Polygon (object mode)."""
    bl_translation_context = 'MWK:ui/mesh_tools_poly.py:213'
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = poly_draw.CREATE_TOOL
    bl_label = _zh_native('Create Polygon', 'MWK:ui/mesh_tools_poly.py:213')
    bl_description = _zh_native('Click to place points, Enter to make a new polygon object. Backspace removes the last point, middle-drag moves it (Maya Create Polygon)', 'MWK:ui/mesh_tools_poly.py:213')
    bl_icon = 'ops.mesh.polybuild_hover'
    bl_widget = None
    bl_keymap = _create_keymap()

    @staticmethod
    def draw_settings(context, layout, tool):
        draw_create(layout, context, header=context.region.type == 'TOOL_HEADER')

class ALLSET_TL_create_polygon_edit(bpy.types.WorkSpaceTool):
    """Maya Create Polygon (component mode: the polygon is still a new object)."""
    bl_translation_context = 'MWK:ui/mesh_tools_poly.py:230'
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'EDIT_MESH'
    bl_idname = poly_draw.CREATE_TOOL
    bl_label = _zh_native('Create Polygon', 'MWK:ui/mesh_tools_poly.py:230')
    bl_description = _zh_native(ALLSET_TL_create_polygon.bl_description, 'MWK:ui/mesh_tools_poly.py:230')
    bl_icon = 'ops.mesh.polybuild_hover'
    bl_widget = None
    bl_keymap = _create_keymap()

    @staticmethod
    def draw_settings(context, layout, tool):
        draw_create(layout, context, header=context.region.type == 'TOOL_HEADER')

class ALLSET_TL_append_polygon(bpy.types.WorkSpaceTool):
    """Maya Append to Polygon."""
    bl_translation_context = 'MWK:ui/mesh_tools_poly.py:246'
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'EDIT_MESH'
    bl_idname = poly_draw.APPEND_TOOL
    bl_label = _zh_native('Append to Polygon', 'MWK:ui/mesh_tools_poly.py:246')
    bl_description = _zh_native('Click a border edge of the mesh, then place points or click another border edge; Enter adds the face (Maya Append to Polygon)', 'MWK:ui/mesh_tools_poly.py:246')
    bl_icon = 'ops.mesh.polybuild_hover'
    bl_widget = None
    bl_keymap = (('allset.append_polygon', {'type': 'LEFTMOUSE', 'value': 'PRESS'}, None), ('allset.poly_tool_exit', {'type': 'ESC', 'value': 'PRESS'}, None))

    @staticmethod
    def draw_settings(context, layout, tool):
        draw_append(layout, context, header=context.region.type == 'TOOL_HEADER')
TOOLS = (ALLSET_TL_quad_draw, ALLSET_TL_create_polygon, ALLSET_TL_create_polygon_edit, ALLSET_TL_append_polygon)

def register():
    notices.PANEL_NOTICES.update(GREY)
    for tool in TOOLS:
        after = {'builtin.poly_build'} if tool.bl_context_mode == 'EDIT_MESH' else None
        bpy.utils.register_tool(tool, after=after)

def unregister():
    for tool in reversed(TOOLS):
        bpy.utils.unregister_tool(tool)
    for key in GREY:
        notices.PANEL_NOTICES.pop(key, None)
