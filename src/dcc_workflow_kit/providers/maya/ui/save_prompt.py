# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Maya's "Save changes?" prompt before an action that replaces the open scene (step 138, #57).

Maya 2022: when the scene is modified, a dialog with the buttons
Save / Don't Save / Cancel (default Save, Esc = Cancel):

- a saved scene: title "Save Changes", message "Save changes to <scene path>?"; Save = File > Save Scene, then the
  action;
- an untitled scene: title "Warning: Scene Not Saved", message "Save changes to untitled scene?"; Save = the Save As
  browser (File > Save Scene As), the action only once the scene was really saved;
- Don't Save = the action; Cancel = nothing.

``ask(context, proceed)`` runs ``proceed`` (a callable that may load a file) from a timer after that check — never
inside an operator (CLAUDE.md step 42). An unmodified scene runs it without asking.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import os
import bpy
TITLE_SAVED = _dcc_source('Save Changes')
TITLE_UNTITLED = _dcc_source('Warning: Scene Not Saved')
CHOICES = (('SAVE', _dcc_source('Save'), _dcc_source('Save the scene, then go on')), ('DONT_SAVE', _dcc_source("Don't Save"), _dcc_source('Go on without saving (the changes are lost)')), ('CANCEL', _dcc_source('Cancel'), _dcc_source('Keep the open scene')))
_pending = [None]
_run = [None]
_save_watch = {'proceed': None, 'saved': False, 'seen': False, 'ticks': 0}
WATCH_SECONDS = 3.0

def message(filepath=None):
    """Maya's question for the open file (``filepath`` default: ``bpy.data.filepath``)."""
    path = bpy.data.filepath if filepath is None else filepath
    return f'Save changes to {path}?' if path else _dcc_source('Save changes to untitled scene?')

def title(filepath=None):
    path = bpy.data.filepath if filepath is None else filepath
    return TITLE_SAVED if path else TITLE_UNTITLED

def ask(context, proceed):
    """Maya's save check, then ``proceed()`` (from a timer). Returns the calling operator's result: FINISHED when
    the action runs now, CANCELLED while it waits for the answer (the dialog does the rest)."""
    if not bpy.data.is_dirty:
        run_later(proceed)
        return {'FINISHED'}
    _pending[0] = proceed
    if context.window is not None and (not bpy.app.background):
        bpy.ops.allset.save_prompt('INVOKE_DEFAULT')
    return {'CANCELLED'}

def choose(context, choice):
    """The answer: 'SAVE' / 'DONT_SAVE' / 'CANCEL'. Returns the operator result."""
    (proceed, _pending[0]) = (_pending[0], None)
    if proceed is None or choice == 'CANCEL':
        return {'CANCELLED'}
    if choice == 'DONT_SAVE':
        run_later(proceed)
        return {'FINISHED'}
    if bpy.data.filepath:
        try:
            bpy.ops.wm.save_mainfile()
        except RuntimeError as ex:
            print(_dcc_source('Maya Workflow Kit: save failed:'), ex)
            return {'CANCELLED'}
        run_later(proceed)
        return {'FINISHED'}
    _watch_save(proceed)
    try:
        return bpy.ops.allset.save_scene_as('INVOKE_DEFAULT')
    except RuntimeError:
        _stop_watch()
        return {'CANCELLED'}

def run_later(proceed):
    _run[0] = proceed
    if not bpy.app.timers.is_registered(_run_tick):
        bpy.app.timers.register(_run_tick, first_interval=0.0)

def _run_tick():
    (proceed, _run[0]) = (_run[0], None)
    if proceed is not None:
        proceed()
    return None

def _watch_save(proceed):
    _stop_watch()
    _save_watch.update(proceed=proceed, saved=False, seen=False, ticks=0)
    bpy.app.handlers.save_post.append(_on_save_post)
    bpy.app.timers.register(_watch_tick, first_interval=0.1)

def _stop_watch():
    _save_watch.update(proceed=None, saved=False, seen=False, ticks=0)
    if _on_save_post in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(_on_save_post)
    if bpy.app.timers.is_registered(_watch_tick):
        bpy.app.timers.unregister(_watch_tick)

def _on_save_post(filepath, *_args):
    if filepath and os.path.isfile(filepath):
        _save_watch['saved'] = True

def _save_browser_open():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'FILE_BROWSER':
                op = getattr(area.spaces.active, 'active_operator', None)
                if op is not None and op.bl_idname == 'WM_OT_save_as_mainfile':
                    return True
    return False

def _watch_tick():
    if _save_watch['saved']:
        proceed = _save_watch['proceed']
        _stop_watch()
        if proceed is not None:
            proceed()
        return None
    _save_watch['ticks'] += 1
    if _save_browser_open():
        _save_watch['seen'] = True
        return 0.1
    if _save_watch['seen'] or _save_watch['ticks'] * 0.1 > WATCH_SECONDS:
        _stop_watch()
        return None
    return 0.1

def _draw(menu, _context):
    layout = menu.layout
    layout.label(text=_zh(message(), 'MWK:ui/save_prompt.py:149'))
    layout.separator()
    row = layout.column_flow(columns=len(CHOICES))
    row.emboss = 'NORMAL'
    for (key, label, _tip) in CHOICES:
        row.operator(ALLSET_OT_save_prompt_choice.bl_idname, text=_zh(label, 'MWK:ui/save_prompt.py:156')).choice = key

class ALLSET_OT_save_prompt(bpy.types.Operator):
    """Maya's Save Changes dialog: Save / Don't Save / Cancel"""
    bl_translation_context = 'MWK:ui/save_prompt.py:162'
    bl_idname = 'allset.save_prompt'
    bl_label = _zh_native('Save Changes', 'MWK:ui/save_prompt.py:162')
    bl_description = _zh_native("Maya's Save Changes dialog: Save / Don't Save / Cancel", 'MWK:ui/save_prompt.py:162')
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        context.window_manager.popup_menu(_draw, title=_dcc_display(title()), icon='QUESTION')
        return {'FINISHED'}

    def execute(self, context):
        return {'FINISHED'}

class ALLSET_OT_save_prompt_choice(bpy.types.Operator):
    """Answer Maya's Save Changes dialog"""
    bl_translation_context = 'MWK:ui/save_prompt.py:178'
    bl_idname = 'allset.save_prompt_choice'
    bl_label = _zh_native('Save Changes', 'MWK:ui/save_prompt.py:178')
    bl_description = _zh_native("Answer Maya's Save Changes dialog", 'MWK:ui/save_prompt.py:178')
    bl_options = {'INTERNAL'}
    choice: bpy.props.EnumProperty(items=_zh_enum(CHOICES, 'MWK:ui/save_prompt.py:181'), options={'SKIP_SAVE'}, translation_context='MWK:ui/save_prompt.py:181')

    @classmethod
    def description(cls, context, props):
        return _zh(next((tip for (key, _label, tip) in CHOICES if key == props.choice)), 'MWK:ui/save_prompt.py:185')

    def execute(self, context):
        return choose(context, self.choice)
classes = (ALLSET_OT_save_prompt, ALLSET_OT_save_prompt_choice)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    _stop_watch()
    if bpy.app.timers.is_registered(_run_tick):
        bpy.app.timers.unregister(_run_tick)
    _pending[0] = _run[0] = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
