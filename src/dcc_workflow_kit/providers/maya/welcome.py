# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""The opt-in: nothing changes until the user asks for Maya (docs/steps/step_115.md).

Part of CORE (registered whenever the extension is enabled, also in Blender mode). Enabling the extension only adds
the Maya | Blender switch, an Edit menu item, Ctrl+Alt+Shift+M and, once in a GUI session, this welcome dialog. Its
confirm button "Make Blender feel like Maya" (also in the add-on preferences) turns on Maya mode and Make Blender
Maya (``first_start.make``: start in the Maya layout, the layout shown now). Cancelling changes nothing. Blender's
preferences are never written (step 130).

Not in background runs; GUI tests and tools set ``ALLSET_NO_WELCOME=1`` (the dialog would eat simulated events).
"""
from .i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from .i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import os
import bpy
from . import preferences
WELCOME_IMAGE = os.path.join(os.path.dirname(__file__), 'welcome.png')
_previews = None

def _splash_icon():
    global _previews
    if not os.path.isfile(WELCOME_IMAGE):
        return 0
    if _previews is None:
        import bpy.utils.previews
        _previews = bpy.utils.previews.new()
    if 'splash' not in _previews:
        _previews.load('splash', WELCOME_IMAGE, 'IMAGE')
    return _previews['splash'].icon_id

def _window():
    wm = bpy.context.window_manager
    return wm.windows[0] if wm and wm.windows else None

def opt_in(open_layout=True):
    """Everything "Make Blender feel like Maya" does. Runs from a timer (switching registers the Maya mode
    modules, which an operator of theirs must not do while it runs; docs/steps/step_42.md)."""
    from . import switch
    switch.set_mode(True, layout=False)
    from . import first_start
    first_start.make(bpy.context, open_layout=False)
    if open_layout:
        first_start.show_layout(_window())
PARAGRAPHS = (_dcc_source('The whole Maya workflow in Blender, in one install.'), _dcc_source('Nothing has changed yet. Make Blender feel like Maya turns on the Maya-style keys: Alt+mouse, QWER, Space hotbox, marking menus; the Maya layout, menus, Channel Box and shelf.'), _dcc_source('Your Blender preferences are never changed: the Maya | Blender switch at the top right or Ctrl+Alt+Shift+M goes back to plain Blender at any time.'), _dcc_source("Tip: Maya's undo is unlimited, Blender keeps 32 steps by default. Raise Edit > Preferences > System > Undo Steps to 256 if you like Maya's long undo."))
WELCOME_SHOWS = 2
DIALOG_WIDTH = 640
ICON_SCALE = 7.0
ICON_FACTOR = (ICON_SCALE * 20 + 16) / DIALOG_WIDTH
TEXT_PAD = 40

def text_room(with_icon=True):
    """Unscaled px a body line may take."""
    return DIALOG_WIDTH * (1.0 - ICON_FACTOR if with_icon else 1.0) - TEXT_PAD

def text_width(text, size):
    import blf
    blf.size(0, size)
    return blf.dimensions(0, _dcc_display(_zh(text, 'MWK:welcome.py:82')))[0]

def wrap(text, width, size, measure=text_width):
    """Wrap complete translated paragraphs; preserve the original English word wrapping."""
    text = _zh(text, 'MWK:welcome.py:85')
    if any(('㐀' <= char <= '\u9fff' for char in text)):
        import re
        tokens = re.findall('[A-Za-z0-9_]+(?:[+./:-][A-Za-z0-9_]+)*|[^\\x00-\\x7f]|\\s+|.', text)
        (lines, current) = ([], '')
        for token in tokens:
            if '\n' in token:
                lines.append(current.rstrip())
                current = ''
                continue
            candidate = current + token
            if current and measure(candidate, size) > width:
                lines.append(current.rstrip())
                current = token.lstrip()
            else:
                current = candidate
        if current:
            lines.append(current.rstrip())
        return lines
    (lines, cur) = ([], '')
    for word in text.split():
        cand = f'{cur} {word}' if cur else word
        if cur and measure(cand, size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines

class ALLSET_OT_welcome(bpy.types.Operator):
    """Turn on the Maya-style keys, layout and menus (asks first). Blender's preferences are not changed;
    Ctrl+Alt+Shift+M or the Maya / Blender switch turns it off again"""
    bl_translation_context = 'MWK:welcome.py:104'
    bl_idname = 'allset.welcome'
    bl_label = _zh_native('Make Blender feel like Maya', 'MWK:welcome.py:104')
    bl_description = _zh_native("Turn on the Maya-style keys, layout and menus (asks first). Blender's preferences are not changed;\nCtrl+Alt+Shift+M or the Maya / Blender switch turns it off again", 'MWK:welcome.py:104')
    bl_options = {'INTERNAL'}
    open_layout: bpy.props.BoolProperty(name=_zh_native('Open Maya Layout', 'MWK:welcome.py:107'), default=True, options={'SKIP_SAVE'}, translation_context='MWK:welcome.py:107')

    def invoke(self, context, event):
        prefs = preferences.get(context)
        prefs.welcome_shown += 1
        if prefs.welcome_shown >= WELCOME_SHOWS:
            prefs.welcome_done = True
        return context.window_manager.invoke_props_dialog(self, width=DIALOG_WIDTH, title=_zh('Welcome to Maya Workflow Kit', 'MWK:welcome.py:118'), confirm_text=_zh('Make Blender feel like Maya', 'MWK:welcome.py:118'))

    def draw(self, context):
        icon = _splash_icon()
        if icon:
            row = self.layout.split(factor=ICON_FACTOR)
            row.template_icon(icon_value=icon, scale=ICON_SCALE)
        else:
            row = self.layout.row()
        col = row.column()
        col.label(text=_zh('Maya Workflow Kit', 'MWK:welcome.py:128'))
        scale = context.preferences.system.ui_scale or 1.0
        size = context.preferences.ui_styles[0].widget.points * scale
        width = text_room(bool(icon)) * scale
        paras = PARAGRAPHS
        emulate = preferences.emulate_hint(context)
        if emulate:
            paras = paras + (emulate,)
        for (k, para) in enumerate(paras):
            if k:
                col.separator()
            for line in wrap(para, width, size):
                col.label(text=_zh(line, 'MWK:welcome.py:140'))

    def execute(self, context):
        preferences.get(context).welcome_done = True
        open_layout = self.open_layout
        bpy.app.timers.register(lambda : opt_in(open_layout), first_interval=0.0)
        return {'FINISHED'}
DIALOG_ROOM_PX = 420

def spot_ok(window, x, y, ui_scale):
    """The pointer (window px, bottom-left origin) is a place the dialog may open: in the window, below the top bar by
    the dialog's height, above the status bar."""
    return 0 <= x < window.width and 30 * ui_scale <= y <= window.height - DIALOG_ROOM_PX * ui_scale

def _wanted():
    try:
        prefs = preferences.get()
    except KeyError:
        return False
    return not (prefs.welcome_done or prefs.maya_mode)

class ALLSET_OT_welcome_wait(bpy.types.Operator):
    """Open the welcome dialog once the pointer is in the main window, clear of its menu bar (#170)"""
    bl_translation_context = 'MWK:welcome.py:174'
    bl_idname = 'allset.welcome_wait'
    bl_label = _zh_native('Welcome (wait for the pointer)', 'MWK:welcome.py:174')
    bl_description = _zh_native('Open the welcome dialog once the pointer is in the main window, clear of its menu bar (#170)', 'MWK:welcome.py:174')
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        self._win = context.window.as_pointer()
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if not _wanted():
            return {'CANCELLED', 'PASS_THROUGH'}
        if event.type != 'MOUSEMOVE' or context.window is None or context.window.as_pointer() != self._win:
            return {'PASS_THROUGH'}
        win = context.window
        (x, y) = (event.mouse_x, event.mouse_y)
        if not spot_ok(win, x, y, context.preferences.system.ui_scale or 1.0):
            return {'PASS_THROUGH'}
        ptr = self._win

        def show():
            from . import live_refs
            w = live_refs.window(ptr)
            if w is not None and _wanted():
                with bpy.context.temp_override(window=w, screen=w.screen):
                    bpy.ops.allset.welcome('INVOKE_DEFAULT')
            return None
        bpy.app.timers.register(show, first_interval=0.0)
        return {'FINISHED', 'PASS_THROUGH'}

def _show_welcome():
    if not _wanted():
        return None
    win = _window()
    if win is None:
        return 0.5
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.allset.welcome_wait('INVOKE_DEFAULT')
    return None
classes = (ALLSET_OT_welcome, ALLSET_OT_welcome_wait)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if not bpy.app.background and os.environ.get('ALLSET_NO_WELCOME') != '1':
        bpy.app.timers.register(_show_welcome, first_interval=0.5)

def unregister():
    global _previews
    if bpy.app.timers.is_registered(_show_welcome):
        bpy.app.timers.unregister(_show_welcome)
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
