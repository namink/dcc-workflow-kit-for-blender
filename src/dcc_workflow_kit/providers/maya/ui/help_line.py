# SPDX-License-Identifier: GPL-3.0-or-later
"""The Help Line message: a short text shown in the status bar's Help Line for a few seconds (menu notices, tool
messages), and a flat info button whose tooltip is a note.

Entry points: ``show``, ``current``, ``remember_status_area``, ``tip`` / ``ALLSET_OT_tip``. Related: ``notices``
(the notice tables; registers ``ALLSET_OT_tip``), ``command_line`` (draws the Help Line).
"""

import time

import bpy

from .. import i18n, live_refs

SHOW_SECONDS = 5.0
_current = {"text": "", "until": 0.0}
# [(window pointer, status bar area)] seen while drawing it. Global areas aren't in screen.areas, so the area can't be
# found again by pointer; it lives as long as its window, so it is only touched while that window is open (#36).
_status_area = []


def show(text):
    """Put ``text`` in the Help Line for a few seconds."""
    _current["text"] = text
    _current["until"] = time.monotonic() + SHOW_SECONDS
    _redraw_status_later()
    if not bpy.app.timers.is_registered(_expire):
        bpy.app.timers.register(_expire, first_interval=SHOW_SECONDS + 0.1)


def current():
    return _current["text"] if time.monotonic() < _current["until"] else ""


def remember_status_area(area, window=None):
    window = window or bpy.context.window
    if area is not None and window is not None and (not _status_area or _status_area[0][1] != area):
        _status_area[:] = [(window.as_pointer(), area)]


def _redraw_status():
    for win_ptr, area in list(_status_area):
        if live_refs.window(win_ptr) is None:
            _status_area.clear()
            continue
        try:
            area.tag_redraw()
        except ReferenceError:
            _status_area.clear()
    return None


def _redraw_status_later():
    # Not from inside a tooltip / draw callback: one tick later.
    if not bpy.app.timers.is_registered(_redraw_status):
        bpy.app.timers.register(_redraw_status, first_interval=0.0)


def _expire():
    if not current():
        _current["text"] = ""
        _redraw_status()
        return None
    return 0.5


class ALLSET_OT_tip(bpy.types.Operator):
    """A note about the Blender side of a Maya window, shown as a tooltip instead of a sentence in the window;
    clicking puts it in the Help Line"""
    bl_idname = "allset.tip"
    bl_label = "Note"
    bl_options = {'INTERNAL'}

    text: bpy.props.StringProperty(options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return i18n.tip(props.text)

    def execute(self, context):
        if self.text:
            show(i18n.tip(self.text))
        return {'FINISHED'}


def tip(layout, text, label="", icon='INFO'):
    """A flat button whose tooltip is ``text`` (Maya windows carry no Blender explanation sentences)."""
    op = layout.operator(ALLSET_OT_tip.bl_idname, text=label, icon=icon, emboss=False)
    op.text = text
    return op
