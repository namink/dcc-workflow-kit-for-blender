# SPDX-License-Identifier: GPL-3.0-or-later
"""Shelf Editor: move a button to a new place in Shelf Contents with the mouse (Preferences > Shelf Editor Drag, off
by default: Maya's Shelf Editor reorders Shelf Contents with Move Up / Move Down only).

With the preference on, every editable row of Shelf Contents gets a grip at its left. A click on the grip picks the
button up; it then follows the mouse up or down one row at a time; a left click drops it there, Esc or a right click
puts it back. Like Move Up / Move Down it changes the draft only: Save Shelf writes it.

The grip is its own operator button, so the row it belongs to comes with the click (Blender runs a button's operator
when the mouse is released over it); after that a modal operator follows the mouse.
"""

import bpy
from bpy.props import IntProperty

from .shelf_editor_draft import _draft_buttons, _redraw, _set_message, _wm


def enabled(context=None):
    from .. import preferences
    try:
        return bool(preferences.get(context).shelf_editor_drag)
    except (KeyError, AttributeError):
        return False


def row_px(context):
    """Height of one Shelf Contents row in px: Blender's widget unit at the current interface scale."""
    system = context.preferences.system
    return round(18 * system.ui_scale) + 2 * getattr(system, "pixel_size", 1)


def moved(order, start, target):
    """``order`` with the item at ``start`` taken out and put back at ``target``."""
    out = order[:start] + order[start + 1:]
    out.insert(target, order[start])
    return out


class ALLSET_OT_shelf_editor_drag_button(bpy.types.Operator):
    """Click, move the mouse up or down and click again to drop the button there (Esc puts it back)"""
    bl_idname = "allset.shelf_editor_drag_button"
    bl_label = "Drag Button"
    bl_options = {'INTERNAL'}

    index: IntProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if not enabled(context):
            return {'CANCELLED'}
        self.buttons = _draft_buttons(_wm(context).allset_se_shelf)
        if not self.buttons or not 0 <= self.index < len(self.buttons):
            return {'CANCELLED'}
        self.original = list(self.buttons)
        self.start_y = event.mouse_y
        self.row = max(1, row_px(context))
        self.current = self.index
        self.dropping = False
        bpy.ops.allset.shelf_editor_select_button(index=self.index)
        _set_message(context, "Click to drop the button here (Esc puts it back)")
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _place(self, target):
        self.buttons[:] = moved(self.original, self.index, target)   # in place: the draft holds this same list
        self.current = target
        bpy.ops.allset.shelf_editor_select_button(index=target)

    def _end(self, context):
        _set_message(context, "")
        _redraw(context)

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE' and not self.dropping:
            steps = round((self.start_y - event.mouse_y) / self.row)       # mouse down = a later row
            target = max(0, min(len(self.original) - 1, self.index + steps))
            if target != self.current:
                self._place(target)
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.dropping = True                 # the release is ours too (it must not click the row under it)
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE' and self.dropping:
            self._end(context)
            return {'FINISHED'}
        elif event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._place(self.index)
            self._end(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


def draw_grip(layout, index):
    """The row's grip (only while Preferences > Shelf Editor Drag is on)."""
    layout.operator(ALLSET_OT_shelf_editor_drag_button.bl_idname, text="", icon='GRIP', emboss=False).index = index


classes = (ALLSET_OT_shelf_editor_drag_button,)
