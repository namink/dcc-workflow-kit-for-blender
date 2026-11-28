# SPDX-License-Identifier: GPL-3.0-or-later
"""Mouse input over the rows: the hover watcher, click and drag selection on names and values, horizontal value
drags, in-place field editing, and the Channels / Edit menus on right-click.
Entry points: ALLSET_OT_cb_hover, ALLSET_OT_cb_channel_drag, ALLSET_OT_cb_field_drag, field_drag_starts, edit_field.
Related: cb_selection.py, cb_menus.py."""

import math

import bpy
from bpy.props import EnumProperty, StringProperty

from ..operators import auto_key
from . import cb_entry

from .cb_nodes import full_path, is_root_joint, lead, targets
from .cb_pane import _filled, _hover, _is_cb_dock, _redraw, _unit, cb_share, in_channel_part, row_pitch
from .cb_keys import (HISTORY_PREFIX, MAIN_BY_KEY, is_hidden, is_history_key, is_input_key, is_locked, is_shape_key,
                      row_key)
from .cb_inputs import constrained_keys
from .cb_values import (_non_euler_rot, auto_keys, driver, entry_kind, get_value, has_channel, keyframe, set_value,
                        shape_owner, shape_paths)
from .cb_selection import (cell_key, drawn_keys, entry_keys, redraw_selection, select_channel, select_range,
                           selected_channels, selection_column, set_selected_channels, set_selection_column)
from .cb_slider import drag_limit
from .cb_menus import ALLSET_MT_cb_channels, ALLSET_MT_cb_edit


# --- operators: selection, Channels menu ----------------------------------------------------------

class ALLSET_OT_cb_select_channel(bpy.types.Operator):
    """Select this channel (Ctrl: toggle, Shift: add). Selected channels follow MMB-drag in the viewport"""
    bl_idname = "allset.cb_select_channel"
    bl_label = "Select Channel"
    bl_options = {'INTERNAL'}

    key: StringProperty()
    mode: EnumProperty(items=(("SET", "Set", ""), ("TOGGLE", "Toggle", ""), ("EXTEND", "Extend", "")))

    def invoke(self, context, event):
        self.mode = "TOGGLE" if event.ctrl else "EXTEND" if event.shift else "SET"
        return self.execute(context)

    def execute(self, context):
        select_channel(self.key, self.mode, context)
        redraw_selection()
        return {'FINISHED'}


class ALLSET_OT_cb_deselect_channels(bpy.types.Operator):
    """Clear the Channel Box channel selection"""
    bl_idname = "allset.cb_deselect_channels"
    bl_label = "Deselect Channels"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        set_selected_channels([], context)
        return {'FINISHED'}


# --- drag over the rows ---------------------------------------------------------------------------------
# An embossed text field starts its text edit on PRESS, so no keymap item sees a press-drag that starts on a value
# field. ``allset.cb_hover`` (Property Editor MOUSEMOVE, first) remembers the Channel Box
# cell under the mouse (``context.property``) and starts ``allset.cb_channel_drag``, a window modal (window handlers
# run before the UI) that lives while the mouse is in that region and handles the LMB presses on channel cells.

_watching = set()
_anchor = {"key": None}
_field_handoff = {}


def start_field_drag(context, event, key, start_x):
    """Keep the triggering modifiers across bpy.ops' synchronous invoke handoff."""
    ptr = context.window.as_pointer()
    _field_handoff[ptr] = dict(type=event.type, value=event.value, mouse_x=event.mouse_x,
                               ctrl=event.ctrl, shift=event.shift, alt=event.alt)
    try:
        return bpy.ops.allset.cb_field_drag('INVOKE_DEFAULT', True, key=key, start_x=start_x)
    finally:
        _field_handoff.pop(ptr, None)


def _field_is_driven(ob, key):
    if is_input_key(key) or is_history_key(key):
        return driver(ob, key) is not None
    if not is_shape_key(key):
        kind = MAIN_BY_KEY.get(key, (None, None, None, None, None))[4]
        # A displayed Euler channel on a quaternion/axis-angle node writes the
        # entire four-component rotation; a root joint's armature-space translate
        # writes all three local components. Do not overwrite any driven component.
        if _non_euler_rot(ob, kind) or (kind == "LOC" and is_root_joint(ob)):
            ad = ob.id_data.animation_data
            if ad is None:
                return False
            if _non_euler_rot(ob, kind):
                from .. import rotation_display
                path, size = rotation_display.curve_path(ob), 4
            else:
                path, size = "location", 3
            path = full_path(ob, path)
            return bool(path and any(ad.drivers.find(path, index=i) is not None for i in range(size)))
        return driver(ob, key) is not None
    owner = shape_owner(ob, key)
    ad = owner.animation_data if owner is not None else None
    return bool(ad and any(ad.drivers.find(path, index=max(index, 0)) is not None
                           for path, index in shape_paths(owner, key)))


def field_drag_starts(context, key):
    """Snapshot editable scalar channels, using the same selection rule as text entry."""
    starts = {}
    for k in entry_keys(key, context):
        for ob in targets(context):
            if (not has_channel(ob, k) or is_locked(ob, k) or is_hidden(ob, k)
                    or k in constrained_keys(ob) or _field_is_driven(ob, k)):
                continue
            value = get_value(ob, k)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                kind = entry_kind(ob, k)
                if kind in {'LENGTH', 'ROTATION', 'NONE', 'INT', 'FLOAT'}:
                    starts[(ob, k)] = (value, kind)
    return starts


class ALLSET_OT_cb_field_drag(bpy.types.Operator):
    """Drag a numeric Channel Box value horizontally"""
    bl_idname = "allset.cb_field_drag"
    bl_label = "Adjust Channel Values"
    bl_options = {'INTERNAL', 'UNDO', 'BLOCKING'}

    key: StringProperty(options={'SKIP_SAVE'})
    start_x: bpy.props.IntProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        from types import SimpleNamespace
        handoff = _field_handoff.get(context.window.as_pointer()) if context.window is not None else None
        if handoff is not None:
            event = SimpleNamespace(**handoff)
        self._starts = field_drag_starts(context, self.key)
        if not self._starts:
            return {'CANCELLED'}
        self._last_x = self.start_x
        self._drag_values = {pair: value for pair, (value, _kind) in self._starts.items()}
        self._mode = None
        self._window = context.window
        self._scene = context.scene
        self._frame = context.scene.frame_current
        try:
            if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
                self._apply(event, 1 if event.type == 'WHEELUPMOUSE' else -1, wheel=True)
                return self._confirm(context)
            self._move(event)
        except (ReferenceError, RuntimeError, AttributeError, TypeError, ValueError):
            self._restore()
            return {'CANCELLED'}
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _move(self, event):
        step = event.mouse_x - self._last_x
        self._last_x = event.mouse_x
        self._apply(event, step)

    def _apply(self, event, step, wheel=False):
        if not step:
            return
        mode = (event.ctrl, event.shift, event.alt)
        if mode != self._mode or wheel:
            # Begin each sensitivity mode and each wheel notch at the actual value.
            # Neither a modifier change nor a notch should reveal a hidden fraction.
            self._drag_values = {pair: get_value(*pair) for pair in self._starts}
            self._mode = mode
        precision = (0.1 if event.shift else 1.0) * (0.01 if event.alt else 1.0)
        for (ob, key), (start, kind) in self._starts.items():
            display_step = 0.5 if kind == 'ROTATION' and cb_entry._degrees(self._scene) else 0.01
            if kind == 'INT':
                display_step = 0.1
            amount = (step * precision if wheel else
                      step * display_step * precision * (10.0 if event.ctrl else 1.0))
            continuous = self._drag_values[(ob, key)] + cb_entry.from_display(amount, kind, self._scene)
            self._drag_values[(ob, key)] = continuous
            value = continuous
            if event.ctrl and not wheel:
                quantum = precision
                shown = cb_entry.to_display(value, kind, self._scene) / quantum
                snapped = math.floor(shown + 0.5) if shown >= 0 else math.ceil(shown - 0.5)
                value = cb_entry.from_display(snapped * quantum, kind, self._scene)
            if kind == 'INT':
                # Symmetric nearest integer, independent of the sign of the starting value.
                value = math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)
            value = drag_limit(ob, key, value)
            if get_value(ob, key) != value:
                set_value(ob, key, value)
        try:
            _redraw(self._window)
        except ReferenceError:
            pass

    def _restore(self):
        for (ob, key), (start, _kind) in self._starts.items():
            try:
                if get_value(ob, key) != start:
                    set_value(ob, key, start)
            except (ReferenceError, RuntimeError, AttributeError, TypeError, ValueError):
                pass  # A removed or no longer writable object cannot be restored.
        try:
            _redraw(self._window)
        except ReferenceError:
            pass

    def _confirm(self, context):
        if context.scene != self._scene or self._scene.frame_current != self._frame:
            self._restore()
            return {'CANCELLED'}
        changed = [(ob, key) for (ob, key), (start, _kind) in self._starts.items()
                   if get_value(ob, key) != start]
        if not changed:
            return {'CANCELLED'}
        if auto_key.enabled(self._scene):
            for ob, key in changed:
                if auto_keys(ob, key, context):
                    keyframe(ob, key)
        return {'FINISHED'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            try:
                self._move(event)
            except (ReferenceError, RuntimeError, AttributeError, TypeError, ValueError):
                self._restore()
                return {'CANCELLED'}
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            try:
                return self._confirm(context)
            except (ReferenceError, RuntimeError, AttributeError, TypeError, ValueError):
                self._restore()
                return {'CANCELLED'}
        elif event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            try:
                self._apply(event, 1 if event.type == 'WHEELUPMOUSE' else -1, wheel=True)
            except (ReferenceError, RuntimeError, AttributeError, TypeError, ValueError):
                self._restore()
                return {'CANCELLED'}
        elif event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._restore()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


def _hovered_cell(context):
    prop = getattr(context, "property", None)
    if not prop or not isinstance(prop[0], bpy.types.Scene):
        return None
    return cell_key(prop[1], prop[0])


class ALLSET_OT_cb_hover(bpy.types.Operator):
    """Channel Box: remember the channel under the mouse and watch for a drag over the rows"""
    bl_idname = "allset.cb_hover"
    bl_label = "Channel Box Hover"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        window = context.window
        if window is None:
            return {'PASS_THROUGH'}
        hit = _hovered_cell(context)
        _hover[window.as_pointer()] = hit
        # also over the Channel Box part's empty space / headers: RMB there is Maya's Channels menu
        if ((hit is not None or in_channel_part(context, event)) and window.as_pointer() not in _watching
                and context.region is not None):
            bpy.ops.allset.cb_channel_drag('INVOKE_DEFAULT', True)
        return {'PASS_THROUGH'}


# #315: room a dock needs on its left for the Channels menu (UI units), and how far left of the dock's edge the
# cursor goes (a Blender menu opens with about four fifths of its width left of the cursor)
MENU_ROOM = 14
MENU_GAP = 3


class ALLSET_OT_cb_channel_drag(bpy.types.Operator):
    """Maya Channel Box selection: click a channel name or field, drag over the rows to select a range
    (Ctrl toggles / adds, Shift selects from the last clicked channel)"""
    bl_idname = "allset.cb_channel_drag"
    bl_label = "Select Channels"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        region = context.region
        if region is None or context.window is None:
            return {'CANCELLED'}
        self._win = context.window.as_pointer()
        self._window = context.window
        self._rect = (region.x, region.y, region.x + region.width, region.y + region.height)
        self._pitch = row_pitch(context)
        self._press = None
        # the Channel Box part of a Maya dock: from the region top down to the Layer Editor split (None: no dock)
        self._cb_bottom = None
        self._rows_bottom = None
        if _is_cb_dock(context):
            u = _unit(context)
            self._cb_bottom = region.y + region.height - cb_share(region, u) * region.height
            used = _filled.get(context.area.as_pointer())
            if used is not None:
                self._rows_bottom = region.y + region.height - used * u
        _watching.add(self._win)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _inside(self, event):
        x0, y0, x1, y1 = self._rect
        return x0 <= event.mouse_x < x1 and y0 <= event.mouse_y < y1

    def _finish(self, cancel=False):
        _watching.discard(self._win)
        return {'CANCELLED' if cancel else 'FINISHED', 'PASS_THROUGH'}

    def modal(self, context, event):
        try:
            self._window.screen
        except ReferenceError:
            _watching.discard(self._win)
            return {'CANCELLED', 'PASS_THROUGH'}
        if self._press is None:
            if event.type == 'MOUSEMOVE' and not self._inside(event):
                return self._finish()
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and self._inside(event):
                hit = _hover.get(self._win)
                if hit is not None:
                    return self._on_press(context, event, hit)
                if self._in_empty_space(event) and selected_channels(context):
                    # Maya: a click on the empty space under the channels deselects them
                    set_selected_channels([], context)
                    redraw_selection()
            if event.type == 'RIGHTMOUSE' and event.value == 'PRESS' and self._inside(event):
                hit = _hover.get(self._win)
                in_part = hit is not None or (self._cb_bottom is not None and event.mouse_y >= self._cb_bottom)
                if in_part and not (event.shift or event.alt):
                    return self._on_rmb(context, hit, edit=event.ctrl, y=event.mouse_y)
            if (event.type == 'S' and event.value == 'PRESS' and self._inside(event)
                    and not (event.shift or event.ctrl or event.alt or event.oskey)):
                return self._set_key()
            return {'PASS_THROUGH'}
        if event.type == 'MOUSEMOVE':
            if self._on_move(context, event):
                # The field already applied this move. Passing it through can
                # start a newer channel watcher that preempts the active drag.
                self._finish()
                return {'FINISHED'}
            return {'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return self._on_release(context, event)
        if event.type == 'ESC' and event.value == 'PRESS':
            set_selected_channels(self._base)
            set_selection_column(self._column)
            self._press = None
            redraw_selection()
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    def _set_key(self):
        """Maya S over a Channel Box cell: Set Key, like S anywhere else. Blender's button handler takes a key press
        over a field before any key map (the "Screen" S item never sees it), so it is taken here first; typing in a
        field never gets here (the field editor's handler runs before this one)."""
        try:
            res = bpy.ops.allset.set_key('INVOKE_DEFAULT', True, global_key=True)
        except RuntimeError:       # nothing to key (no selection): the press goes on as before
            return {'PASS_THROUGH'}
        return {'PASS_THROUGH'} if 'PASS_THROUGH' in res else {'RUNNING_MODAL'}

    def _in_empty_space(self, event):
        if self._cb_bottom is None or self._rows_bottom is None:
            return False
        return self._cb_bottom <= event.mouse_y < self._rows_bottom

    def _on_rmb(self, context, hit, edit=False, y=0):
        """Maya: RMB in the Channel Box = the Channels menu. Blender's button
        context menu draws its C items first and a Python menu only after them (#87: the Channels items
        sat under 15 Blender rows), so the press is taken here, before the region's button handler. A channel
        that isn't selected becomes the selection first, so Key Selected keys the clicked channel."""
        if edit:     # Ctrl+RMB = the Edit menu (Maya Channel Box), selection kept
            self._menu_beside(context, y)
            bpy.ops.wm.call_menu(name=ALLSET_MT_cb_edit.__name__)
            return {'RUNNING_MODAL'}
        if hit is not None:
            key, part = hit
            if key not in selected_channels(context):
                set_selected_channels([key], context)
                set_selection_column(part)
                _anchor["key"] = key
                redraw_selection()
        self._menu_beside(context, y)
        bpy.ops.wm.call_menu(name=ALLSET_MT_cb_channels.__name__)
        return {'RUNNING_MODAL'}

    def _menu_beside(self, context, y):
        """#315: the Channels / Edit menu opens left of the dock, so it doesn't cover the channel names and values.
        A Blender menu opens at the cursor (most of it left of the cursor) and Python can't place it: the cursor
        moves just left of the dock's edge first. A dock with too little room on its left keeps the menu at the
        cursor."""
        if self._cb_bottom is None:
            return
        u = _unit(context)
        x0, _y0, _x1, _y1 = self._rect
        if x0 < MENU_ROOM * u:
            return
        window = context.window
        x = x0 - round(MENU_GAP * u)
        window.cursor_warp(x, y)
        if bpy.app.use_event_simulate:   # event simulation drops the OS mouse move a warp makes
            window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)

    def _on_press(self, context, event, hit):
        ob = lead(context)
        if ob is None:
            return {'PASS_THROUGH'}
        key, part = hit
        self._ob = ob
        self._y0 = event.mouse_y
        self._x0 = event.mouse_x
        self._field_candidate = part == 'VALUE'
        self._dragging = False
        self._extended = None
        self._ctrl = event.ctrl
        self._base = selected_channels(context)
        self._column = selection_column()
        self._anchor = key
        self._part = part
        self._key = key
        self._mods = (event.shift, event.ctrl)
        if part == 'VALUE' and (event.shift or event.ctrl):
            # over a value, a modifier press may start a drag (Shift finer, Ctrl whole units): the Shift / Ctrl
            # selection waits for the release of a plain click (_on_release)
            pass
        elif part == 'VALUE':
            if key not in self._base:
                set_selected_channels([key], context)
                set_selection_column('VALUE')
                _anchor["key"] = key
        elif event.shift and _anchor["key"] is not None:
            select_range(ob, _anchor["key"], key, "SET", context=context)
            self._anchor = _anchor["key"]
        elif event.ctrl:
            select_channel(key, "TOGGLE", context)
            _anchor["key"] = key
        elif not (part == "VALUE" and key in self._base and len(self._base) > 1):
            # a field of one of several selected channels keeps them (the typed value goes to all of them)
            set_selected_channels([key], context)
            _anchor["key"] = key
        self._press = part
        redraw_selection()
        # eaten: an embossed field would start its text edit here and swallow the drag
        return {'RUNNING_MODAL'}

    def _key_at_offset(self, event):
        keys = drawn_keys(self._ob)
        if self._anchor not in keys:
            return None
        rows = round((self._y0 - event.mouse_y) / self._pitch)
        i = max(0, min(len(keys) - 1, keys.index(self._anchor) + rows))
        return keys[i]

    def _current(self, event):
        hit = _hover.get(self._win)   # updated by allset.cb_hover after the previous move
        return hit[0] if hit is not None else self._key_at_offset(event)

    def _extend(self, context, cur):
        if cur is None or (cur == self._anchor and not self._dragging):
            return
        self._dragging = True
        if cur == getattr(self, "_extended", None):
            return      # the same row as the last move: nothing to select or draw again
        self._extended = cur
        base = self._base if self._ctrl else None
        select_range(self._ob, self._anchor, cur, "ADD" if self._ctrl else "SET", base=base, context=context)
        set_selection_column(self._part)
        redraw_selection()

    def _on_move(self, context, event):
        dx = event.mouse_x - self._x0
        dy = event.mouse_y - self._y0
        if (self._field_candidate and not self._dragging and abs(dx) >= 6
                and abs(dx) > abs(dy) and field_drag_starts(context, self._key)):
            result = start_field_drag(context, event, self._key, self._x0)
            if 'RUNNING_MODAL' in result:
                self._press = None
                return True
        if not self._dragging and abs(event.mouse_y - self._y0) < 0.5 * self._pitch:
            return
        self._extend(context, self._current(event))

    def _on_release(self, context, event):
        part, self._press = self._press, None
        shift, ctrl = getattr(self, "_mods", (False, False))
        if self._dragging:
            self._extend(context, self._current(event))   # the hover of the last move
            if part == "VALUE" and not (shift or ctrl):
                # #375, Maya: after a drag over the values, typing goes straight into every selected channel
                try:
                    edit_field(context, self._extended or self._key)
                except RuntimeError:
                    pass
        elif part == "VALUE" and (shift or ctrl):
            # a Shift / Ctrl click on a value selects like one on the name
            if shift and _anchor["key"] is not None:
                select_range(self._ob, _anchor["key"], self._key, "SET", context=context)
            else:
                select_channel(self._key, "TOGGLE", context)
                _anchor["key"] = self._key
            set_selection_column('VALUE')
        elif part == "VALUE" and not (event.ctrl or event.shift):
            # a click on a field: Maya edits it in place. The press was eaten, so the field is edited in a popup
            # over it (text active at once); Enter writes the text into every selected channel (apply_entry).
            try:
                edit_field(context, self._key)
            except RuntimeError:
                pass
        redraw_selection()
        return {'RUNNING_MODAL'}


def field_owner(context, key):
    """(owner, property) of the Channel Box text field of channel ``key``."""
    cb = context.scene.allset_cb
    if key in MAIN_BY_KEY:
        return cb, key + "_text"
    for r in cb.rows:
        if row_key(r) == key:
            return r, "text"
    if is_history_key(key):
        return context.scene.allset_creation, key[len(HISTORY_PREFIX):] + "_text"
    return None, None


# the open value editor: its channel, the text it opened with, whether Enter was pressed, and its watcher's number
_edit = {"key": None, "text": "", "enter": False, "watch": 0}


def edit_field(context, key):
    """Edit channel ``key``'s value in a popover at the mouse, its text selected so typing replaces it (Maya: a click
    into a field, or the end of a drag over the values, edits that cell). Like Maya, Enter writes the text into every
    selected channel (apply_entry), also when it is unchanged; a click away writes it only when it was changed, and
    Esc writes nothing (``Scene.allset_cb.entry_text``)."""
    owner, prop = field_owner(context, key)
    if owner is None:
        return False
    _edit["key"] = key
    _edit["text"] = getattr(owner, prop)
    _edit["enter"] = False
    bpy.ops.wm.call_panel(name=ALLSET_PT_cb_field.__name__, keep_open=False)
    # Blender commits the field the same way on Enter and on a click away; a window handler added after the popover
    # gets each event before it, so this one notes the Enter press first
    _edit["watch"] += 1
    bpy.ops.allset.cb_entry_enter('INVOKE_DEFAULT')
    return True


class ALLSET_OT_cb_entry_enter(bpy.types.Operator):
    """Channel Box value editor: note an Enter press before the editor's field takes it (Enter writes an unchanged value, a click away doesn't)"""
    bl_idname = "allset.cb_entry_enter"
    bl_label = "Value Editor Enter"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        self._watch = _edit["watch"]
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if self._watch != _edit["watch"]:        # the editor committed, or a newer one opened
            return {'FINISHED', 'PASS_THROUGH'}
        if event.value == 'PRESS':
            if event.type in {'RET', 'NUMPAD_ENTER'}:
                _edit["enter"] = True
            elif event.type == 'ESC':            # the editor closes without writing
                return {'FINISHED', 'PASS_THROUGH'}
        return {'PASS_THROUGH'}


class ALLSET_PT_cb_field(bpy.types.Panel):
    """The Channel Box field editor popover (called by edit_field only)"""
    bl_space_type = 'TOPBAR'   # dummy, like Blender's TOPBAR_PT_name (F2): only shown through wm.call_panel
    bl_region_type = 'HEADER'
    bl_label = "Channel Value"
    bl_ui_units_x = 6

    def draw(self, context):
        if field_owner(context, _edit["key"] or "")[0] is None:
            return
        row = self.layout.row()
        row.activate_init = True
        row.prop(context.scene.allset_cb, "entry_text", text="")
