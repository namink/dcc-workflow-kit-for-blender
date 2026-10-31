# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Maya keys without a Blender operator of their own (docs/steps/step_35.md 「계획」).

- ``allset.box_zoom`` (Ctrl+Alt+LMB drag): draw a box; left→right zooms in on it,
  right→left zooms out.
- ``allset.last_tool`` (Y): back to the last tool that is not Q/W/E/R/T, Maya's
  "non-sacred" tool. A timer remembers it per mode.
- ``allset.menu_set`` (F2–F6): switch the Maya menu set (Maya default hotkeys).
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
import gpu
from bpy.props import EnumProperty
from gpu_extras.batch import batch_for_shader
from .. import results
MIN_DRAG = 6

def zoom_direction(start_x, end_x):
    """Maya box zoom: dragging right zooms in, dragging left zooms out."""
    return 'OUT' if end_x < start_x else 'IN'

class ALLSET_OT_box_zoom(bpy.types.Operator):
    """Drag a box to zoom: left to right zooms in on it, right to left zooms out (Maya Ctrl+Alt+LMB)"""
    bl_translation_context = 'MWK:operators/tool_keys.py:33'
    bl_idname = 'allset.box_zoom'
    bl_label = _zh_native('Box Zoom', 'MWK:operators/tool_keys.py:33')
    bl_description = _zh_native('Drag a box to zoom: left to right zooms in on it, right to left zooms out (Maya Ctrl+Alt+LMB)', 'MWK:operators/tool_keys.py:33')

    @classmethod
    def poll(cls, context):
        return context.region_data is not None and context.region is not None and (context.region.type == 'WINDOW')

    def invoke(self, context, event):
        self._start = (event.mouse_region_x, event.mouse_region_y)
        self._end = self._start
        self._button = event.type
        self._region = context.region
        self._handle = context.space_data.draw_handler_add(self._draw, (), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _draw(self):
        if bpy.context.region != self._region:
            return
        ((x0, y0), (x1, y1)) = (self._start, self._end)
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINE_LOOP', {'pos': [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]})
        gpu.state.blend_set('ALPHA')
        shader.uniform_float('color', (1.0, 1.0, 1.0, 0.8))
        batch.draw(shader)
        gpu.state.blend_set('NONE')

    def _finish(self, context):
        context.space_data.draw_handler_remove(self._handle, 'WINDOW')
        self._region.tag_redraw()

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._end = (event.mouse_region_x, event.mouse_region_y)
            self._region.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._finish(context)
            return {'CANCELLED'}
        if event.type == self._button and event.value == 'RELEASE':
            self._end = (event.mouse_region_x, event.mouse_region_y)
            self._finish(context)
            ((x0, y0), (x1, y1)) = (self._start, self._end)
            if abs(x1 - x0) < MIN_DRAG or abs(y1 - y0) < MIN_DRAG:
                return {'CANCELLED'}
            with context.temp_override(region=self._region):
                bpy.ops.view3d.zoom_border(xmin=min(x0, x1), xmax=max(x0, x1), ymin=min(y0, y1), ymax=max(y0, y1), wait_for_input=False, zoom_out=zoom_direction(x0, x1) == 'OUT')
            return {'FINISHED'}
        return {'RUNNING_MODAL'}
SACRED_PREFIXES = ('builtin.select', 'builtin.move', 'builtin.rotate', 'builtin.scale', 'builtin.transform')
_TICK = 0.25
LAST = {}
_active = [None]

def is_sacred(idname):
    return idname.startswith(SACRED_PREFIXES)

def remember(mode, idname):
    if idname and (not is_sacred(idname)):
        LAST[mode] = idname

def _watch():
    try:
        context = bpy.context
        workspace = context.workspace
        if workspace is not None:
            tool = workspace.tools.from_space_view3d_mode(context.mode, create=False)
            remember(context.mode, tool.idname if tool else None)
            idname = tool.idname if tool else None
            if idname != _active[0]:
                _active[0] = idname
                from . import snap_align
                snap_align.apply_active(context)
            if context.mode == _mode[0]:
                for m in CARRY_MODES:
                    _seen[m] = _tool_of(workspace, m)
            if _mode[0] is None:
                _mode[0] = context.mode
            elif context.mode != _mode[0] and (not bpy.app.timers.is_registered(_carry)):
                _carry()
        if context.mode in {'POSE', 'EDIT_ARMATURE'}:
            from . import joint_selection
            if context.mode == 'EDIT_ARMATURE':
                from . import joint_edit
                joint_edit.process(context)
                joint_edit.watch()
            joint_selection.sync_tool_mode(context)
            if context.mode == 'EDIT_ARMATURE':
                joint_selection.sync_joint_pivot(context)
        if context.mode != 'EDIT_ARMATURE':
            from . import joint_selection
            joint_selection.restore_joint_pivot(context)
    except (AttributeError, RuntimeError, ReferenceError):
        pass
    return _TICK
CARRY_MODES = {'OBJECT', 'EDIT_MESH', 'EDIT_CURVE', 'EDIT_SURFACE', 'EDIT_LATTICE', 'EDIT_ARMATURE', 'EDIT_METABALL', 'POSE'}
_mode = [None]
_seen = {}

def carried_tool(prev_mode, new_mode, prev_tool, new_tool):
    """The tool idname the new mode should get, or None (bpy-free rule)."""
    if prev_mode == new_mode or prev_mode not in CARRY_MODES or new_mode not in CARRY_MODES:
        return None
    if not prev_tool or not is_sacred(prev_tool):
        return None
    if prev_tool == 'builtin.transform':
        prev_tool = 'builtin.select_box'
    return None if prev_tool == new_tool else prev_tool

def _tool_of(workspace, mode):
    tool = workspace.tools.from_space_view3d_mode(mode, create=False)
    return tool.idname if tool else None

def _carry():
    """0 s timer after a mode change: give the new mode the previous mode's Q / W / E / R / T tool."""
    context = bpy.context
    try:
        (mode, prev, workspace) = (context.mode, _mode[0], context.workspace)
    except AttributeError:
        return None
    _mode[0] = mode
    if workspace is None:
        return None
    from . import hold
    if hold.COMPONENT.on or hold.COMPONENT.pending_tool:
        return None
    current = _tool_of(workspace, mode)
    seen = _seen.get(mode)
    if seen is not None and seen != current or (seen is None and current and (not is_sacred(current))):
        _seen[mode] = current
        return None
    tool = carried_tool(prev, mode, _tool_of(workspace, prev) if prev else None, current)
    if tool is None:
        return None
    _seen[mode] = tool
    from ..ui.status_line import main_view3d
    window = context.window or (context.window_manager.windows[0] if context.window_manager.windows else None)
    (area, region) = main_view3d(window.screen) if window is not None else (None, None)
    try:
        if area is not None:
            with context.temp_override(window=window, area=area, region=region):
                bpy.ops.wm.tool_set_by_id(name=tool, space_type='VIEW_3D')
    except (RuntimeError, ReferenceError, TypeError):
        pass
    return None

@bpy.app.handlers.persistent
def _on_depsgraph(_scene, _depsgraph):
    try:
        mode = bpy.context.mode
    except AttributeError:
        return
    if mode != _mode[0] and (not bpy.app.timers.is_registered(_carry)):
        bpy.app.timers.register(_carry, first_interval=0.0)

@bpy.app.handlers.persistent
def _on_load(*_args):
    _mode[0] = None

class ALLSET_OT_last_tool(bpy.types.Operator):
    """Go back to the last tool other than Select/Move/Rotate/Scale (Maya Y)"""
    bl_translation_context = 'MWK:operators/tool_keys.py:225'
    bl_idname = 'allset.last_tool'
    bl_label = _zh_native('Last Tool', 'MWK:operators/tool_keys.py:225')
    bl_description = _zh_native('Go back to the last tool other than Select/Move/Rotate/Scale (Maya Y)', 'MWK:operators/tool_keys.py:225')

    def execute(self, context):
        tool = LAST.get(context.mode)
        if tool is None:
            results.result(self, _zh('No previous tool in this mode', 'MWK:operators/tool_keys.py:230'))
            return {'CANCELLED'}
        try:
            bpy.ops.wm.tool_set_by_id(name=tool, space_type='VIEW_3D')
        except RuntimeError as ex:
            self.report({'WARNING'}, _zh(str(ex).strip(), 'MWK:operators/tool_keys.py:235'))
            return {'CANCELLED'}
        return {'FINISHED'}
MENU_SET_KEYS = (('F2', 'modelingMenuSet'), ('F3', 'riggingMenuSet'), ('F4', 'animationMenuSet'), ('F5', 'dynamicsMenuSet'), ('F6', 'renderingMenuSet'))

def _set_items(self, context):
    from ..ui import menu_sets
    return menu_sets.SET_ITEMS

class ALLSET_OT_menu_set(bpy.types.Operator):
    """Switch the Maya menu set (Maya F2 Modeling, F3 Rigging, F4 Animation, F5 FX, F6 Rendering)"""
    bl_translation_context = 'MWK:operators/tool_keys.py:254'
    bl_idname = 'allset.menu_set'
    bl_label = _zh_native('Menu Set', 'MWK:operators/tool_keys.py:254')
    bl_description = _zh_native('Switch the Maya menu set (Maya F2 Modeling, F3 Rigging, F4 Animation, F5 FX, F6 Rendering)', 'MWK:operators/tool_keys.py:254')
    set: EnumProperty(items=_zh_enum(_set_items, 'MWK:operators/tool_keys.py:256'), name=_zh_native('Menu Set', 'MWK:operators/tool_keys.py:256'), translation_context='MWK:operators/tool_keys.py:256')

    def execute(self, context):
        from .. import preferences
        preferences.get(context).menu_set = self.set
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
        from ..ui import status_line
        status_line.redraw_top_bars()
        return {'FINISHED'}

class ALLSET_OT_toggle_sel_mode(bpy.types.Operator):
    """Toggle object / component selection (Maya F8, SelectToggleMode) with Maya's in-view message"""
    bl_translation_context = 'MWK:operators/tool_keys.py:272'
    bl_idname = 'allset.toggle_sel_mode'
    bl_label = _zh_native('Object/Component', 'MWK:operators/tool_keys.py:272')
    bl_description = _zh_native("Toggle object / component selection (Maya F8, SelectToggleMode) with Maya's in-view message", 'MWK:operators/tool_keys.py:272')
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        return bpy.ops.object.editmode_toggle.poll()

    def execute(self, context):
        ob = context.active_object
        if ob is not None and ob.type == 'ARMATURE':
            if ob.mode == 'EDIT':
                ob.pop('allset_move_skinned', None)
                if ob.pop('allset_joint_move_edit', None):
                    ob['allset_joint_pose_pin'] = True
            result = bpy.ops.object.mode_set(mode='POSE' if ob.mode == 'EDIT' else 'EDIT')
        else:
            result = bpy.ops.object.editmode_toggle()
        if 'FINISHED' not in result:
            return {'CANCELLED'}
        from ..ui import view_message
        if context.mode in {'OBJECT', 'POSE'}:
            text = 'Object selection <hl>on</hl>.\nF8 goes back to components.'
        else:
            text = 'Component selection <hl>on</hl>.\nF8 goes back to objects.'
        view_message.show(context, text, 'TOP_CENTER')
        from ..command_line import undo_text
        undo_text.operator_step(self)
        return {'FINISHED'}
classes = (ALLSET_OT_box_zoom, ALLSET_OT_last_tool, ALLSET_OT_menu_set, ALLSET_OT_toggle_sel_mode)

def register_timer():
    if not bpy.app.timers.is_registered(_watch):
        bpy.app.timers.register(_watch, first_interval=_TICK, persistent=True)
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    bpy.app.handlers.load_post.append(_on_load)

def unregister_timer():
    if bpy.app.timers.is_registered(_watch):
        bpy.app.timers.unregister(_watch)
    if bpy.app.timers.is_registered(_carry):
        bpy.app.timers.unregister(_carry)
    for (lst, fn) in ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph), (bpy.app.handlers.load_post, _on_load)):
        if fn in lst:
            lst.remove(fn)
    LAST.clear()
    _seen.clear()
    _mode[0] = None
