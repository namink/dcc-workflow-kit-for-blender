# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese display integration by namink.
"""Maya Command Line and Help Line in Blender's status bar.

Maya's Command Line (language toggle, input/result field, Script Editor button) and Help Line.
Design: docs/steps/step_7.md
「계획」 4. Python only: MEL is not supported (decision 5). ``maya.cmds`` is a
small look-alike (``cmds_shim``), importable as ``import maya.cmds as cmds`` in code run from the Command Line,
shelf buttons and the Script Editor only: those imports are rewritten to the kit's module before Blender's Run Script
runs the entry (``runner.prepare``, step 130).
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
from bpy.props import StringProperty
from .. import results
from . import runner, undo_text
from ..ui import own_draw
_result = {'text': '', 'error': False}

def show_result(text, error=False):
    """Put ``text`` in the Command Line result field (Maya's "// Result: ..." of a command) and redraw it."""
    (_result['text'], _result['error']) = (text, error)
    wm = bpy.context.window_manager
    for window in wm.windows if wm else ():
        for area in window.screen.areas:
            if area.type == 'STATUSBAR':
                area.tag_redraw()
    try:
        from ..ui import status_line
        status_line.redraw_top_bars()
    except Exception:
        pass

def submit(text):
    """Run a command and keep its result for the result field."""
    res = runner.run(text)
    (_result['text'], _result['error']) = (res.text, res.error)
    return res

def _on_command(self, context):
    text = self.allset_cmd
    if not text.strip():
        return
    self.allset_cmd = ''
    submit(text)
    bpy.ops.ed.undo_push(message=f'Command: {text[:40]}')
    undo_text.pushed(text.strip())

class ALLSET_OT_command_line_exec(bpy.types.Operator):
    """Run a Python command (one undo step), like Maya's command line"""
    bl_translation_context = 'MWK:command_line/__init__.py:64'
    bl_idname = 'allset.command_line_exec'
    bl_label = _zh_native('Run Command', 'MWK:command_line/__init__.py:64')
    bl_description = _zh_native("Run a Python command (one undo step), like Maya's command line", 'MWK:command_line/__init__.py:64')
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}
    command: StringProperty(name=_zh_native('Command', 'MWK:command_line/__init__.py:67'), options={'SKIP_SAVE'}, translation_context='MWK:command_line/__init__.py:67')

    def execute(self, context):
        res = submit(self.command)
        if res.error:
            self.report({'ERROR'}, _zh(res.text, 'MWK:command_line/__init__.py:72'))
        elif res.text:
            results.result(self, _zh(res.text, 'MWK:command_line/__init__.py:74'))
        return {'FINISHED'}

class ALLSET_OT_command_line_language(bpy.types.Operator):
    """Command language: Python. MEL is not supported in Blender"""
    bl_translation_context = 'MWK:command_line/__init__.py:81'
    bl_idname = 'allset.command_line_language'
    bl_label = _zh_native('Python', 'MWK:command_line/__init__.py:81')
    bl_description = _zh_native('Command language: Python. MEL is not supported in Blender', 'MWK:command_line/__init__.py:81')
    bl_options = {'INTERNAL'}

    def execute(self, context):
        self.report({'WARNING'}, _zh('MEL is not supported: the command line runs Python (cmds = a small maya.cmds subset; bpy, C, D as in the Python Console)', 'MWK:command_line/__init__.py:85'))
        return {'FINISHED'}

class ALLSET_OT_script_editor(bpy.types.Operator):
    """Open the Maya Script Editor: history over input with MEL / Python tabs (ui/script_editor.py, step 105)"""
    bl_translation_context = 'MWK:command_line/__init__.py:93'
    bl_idname = 'allset.script_editor'
    bl_label = _zh_native('Script Editor', 'MWK:command_line/__init__.py:93')
    bl_description = _zh_native('Open the Maya Script Editor: history over input with MEL / Python tabs (ui/script_editor.py, step 105)', 'MWK:command_line/__init__.py:93')

    def execute(self, context):
        if context.window is None:
            return {'CANCELLED'}
        from ..ui import script_editor
        if script_editor.open_window(context) is None:
            self.report({'ERROR'}, _zh('Could not open a new window', 'MWK:command_line/__init__.py:100'))
            return {'CANCELLED'}
        return {'FINISHED'}

class ALLSET_MT_command_history(bpy.types.Menu):
    """Recent commands: click to run again"""
    bl_translation_context = 'MWK:command_line/__init__.py:108'
    bl_idname = 'ALLSET_MT_command_history'
    bl_label = _zh_native('Recent Commands', 'MWK:command_line/__init__.py:108')

    def draw(self, context):
        layout = self.layout
        if not runner.history:
            layout.label(text=_zh('No commands yet', 'MWK:command_line/__init__.py:113'))
        for cmd in reversed(runner.history):
            text = cmd if len(cmd) <= 60 else cmd[:57] + '...'
            layout.operator(ALLSET_OT_command_line_exec.bl_idname, text=_zh(text, 'MWK:command_line/__init__.py:116')).command = cmd
TOOL_HELP = {'builtin.select': _dcc_source('Select Tool: click or drag to select. Shift toggles, Ctrl deselects, Ctrl+Shift adds'), 'builtin.move': 'Move Tool: drag the manipulator. Hold X/C/V to snap to grid/curve/point, D to move the pivot', 'builtin.rotate': _dcc_source('Rotate Tool: drag a ring to rotate. Hold J to snap rotation, D to move the pivot'), 'builtin.scale': _dcc_source('Scale Tool: drag a handle to scale, the centre scales uniformly'), 'builtin.transform': _dcc_source('Universal Manipulator: move, rotate and scale with one manipulator'), 'allset.multi_cut_tool': _dcc_source('Multi-Cut: click edges / faces to place points, Enter or right-click to cut. Ctrl+click: edge loop, Shift: snap step, Backspace: remove the last point'), 'builtin.loop_cut': _dcc_source('Insert Edge Loop: click an edge to insert a loop, drag to slide it'), 'allset.insert_edge_loop_tool': _dcc_source('Insert Edge Loop: click an edge to insert a loop there, drag to slide it'), 'allset.offset_edge_loop_tool': _dcc_source('Offset Edge Loop: click an edge and drag to insert loops on both sides'), 'allset.slide_edge_tool': _dcc_source('Slide Edge: select edges, then middle-drag to slide them'), 'allset.quad_draw_tool': _dcc_source('Quad Draw: click to place dots on the live surface, Shift+click to fill a quad, drag to move, Shift+drag to relax, Ctrl+click: edge loop, Ctrl+Shift+click: delete, Tab+drag: extend'), 'allset.create_polygon_tool': _dcc_source('Create Polygon: click to place points, Enter to complete, Backspace: remove the last point'), 'allset.append_polygon_tool': _dcc_source('Append to Polygon: click a border edge, then points, Enter to add the face, Backspace: remove the last point'), 'allset.target_weld_tool': _dcc_source('Target Weld: drag a vertex or edge onto the target. Selected vertices are merged too'), 'allset.crease_tool': _dcc_source('Crease Tool: select edges or vertices, then middle-drag left to crease less, right for more')}

def help_for_tool(idname):
    if idname.startswith('builtin.select'):
        return TOOL_HELP['builtin.select']
    return TOOL_HELP.get(idname, '')

def help_text(context):
    try:
        tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    except (AttributeError, TypeError):
        tool = None
    return help_for_tool(tool.idname) if tool else ''
HELP_UNITS = 33.75
COMMAND_UNITS = 45.75
INPUT_SHARE = 335 / 915
LANG_UNITS = 3.5
MAYA_WINDOW_PX = 1600

def units_for(width_px, ui_scale):
    """(help, command, input) widths in UI units for a status bar ``width_px`` wide: Maya's 675 / 915 / 335 px of a
    1600 px window, scaled to the bar (at most Maya's sizes in UI units: a wide window keeps them)."""
    unit = 20.0 * max(ui_scale, 0.001)
    f = min(1.0, width_px / unit / (MAYA_WINDOW_PX / 20.0))
    command = COMMAND_UNITS * f
    return (HELP_UNITS * f, command, command * INPUT_SHARE)

def row_units(context):
    """``units_for`` this status bar region (the window's width when there is no region)."""
    region = getattr(context, 'region', None)
    scale = context.preferences.system.ui_scale
    width = region.width if region is not None and region.width > 1 else MAYA_WINDOW_PX * scale
    return units_for(width, scale)

def draw_help_line(layout, context):
    """Tool help, else Blender's mouse/key hints; reports and job progress after it (Maya's Help Line
    shows progress too)."""
    from ..ui import notices
    notices.remember_status_area(context.area, context.window)
    note = notices.current()
    from ..ui import weight_numbers
    text = note or weight_numbers.help_note() or help_text(context)
    if text:
        layout.label(text=_zh(text, 'MWK:command_line/__init__.py:202'), icon='ERROR' if note else 'INFO')
    else:
        layout.template_input_status()
    layout.template_reports_banner()
    if not context.screen or not context.screen.is_animation_playing:
        layout.template_running_jobs()

def draw_command_line(layout, context):
    wm = context.window_manager
    (_help, command, input_units) = row_units(context)
    row = layout.row(align=True)
    sub = row.row(align=True)
    sub.ui_units_x = LANG_UNITS
    sub.operator(ALLSET_OT_command_line_language.bl_idname, text=_zh('Python', 'MWK:command_line/__init__.py:218'))
    sub = row.row(align=True)
    sub.ui_units_x = input_units
    sub.prop(wm, 'allset_cmd', text=_dcc_display(''), placeholder=_dcc_display(_dcc_source('Python  (cmds.polyCube(), C.object ...)')))
    sub = row.box().row()
    sub.ui_units_x = max(2.0, command - input_units - LANG_UNITS - 2.5)
    sub.alert = _result['error']
    sub.label(text=_zh(_result['text'] or ' ', 'MWK:command_line/__init__.py:226'))
    row.menu(ALLSET_MT_command_history.bl_idname, text=_dcc_display(''), icon='RECOVER_LAST')
    row.operator(ALLSET_OT_script_editor.bl_idname, text=_dcc_display(''), icon='CONSOLE')

def draw_status_bar(self, context):
    """STATUSBAR_HT_header.draw while the kit is on: Help Line | Command Line, then Blender's
    scene statistics if there is room; Blender's own draw when both are off."""
    from .. import preferences
    try:
        prefs = preferences.get(context)
    except KeyError:
        prefs = None
    if prefs is None or not (prefs.show_help_line or prefs.show_command_line):
        return own_draw.original('STATUSBAR_HT_header', draw_status_bar)(self, context)
    layout = self.layout
    if prefs.show_help_line:
        row = layout.row()
        row.ui_units_x = row_units(context)[0]
        draw_help_line(row, context)
    if prefs.show_command_line:
        row = layout.row()
        row.ui_units_x = row_units(context)[1]
        draw_command_line(row, context)
classes = (ALLSET_OT_command_line_exec, ALLSET_OT_command_line_language, ALLSET_OT_script_editor, ALLSET_MT_command_history)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.allset_cmd = StringProperty(name=_zh_native('Command Line', 'MWK:command_line/__init__.py:262'), description=_zh_native('Python command (Enter to run). MEL is not supported', 'MWK:command_line/__init__.py:262'), options={'SKIP_SAVE'}, update=_on_command, translation_context='MWK:command_line/__init__.py:262')
    own_draw.swap('STATUSBAR_HT_header', draw_status_bar)
    undo_text.register()

def unregister():
    undo_text.unregister()
    own_draw.restore('STATUSBAR_HT_header', draw_status_bar)
    del bpy.types.WindowManager.allset_cmd
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    runner.reset()
    _result.update(text='', error=False)
