# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Channel Box in the 3D View sidebar (category "Channel Box / Layer Editor").

Maya's Channel Box.
- Translate/Rotate/Scale/Visibility rows are getter/setter proxies on
  ``Scene.allset_cb``: they read the lead (active) object and write every
  selected object, like Maya.
- Channel names are buttons that select channels; selected channels drive
  the MMB virtual slider in the viewport and the
  Channels menu.
- Value fields are text: Maya numbers in display units and relative entry
  (``+=5``, ``*=2``; ui/cb_entry.py), applied to every selected object that has the
  channel and to every selected channel when the edited row is one of them.
- Custom properties, SHAPES (object data) and INPUTS (modifiers = construction history)
  are rows in ``Scene.allset_cb.rows`` (rebuilt from handlers), so their edits reach
  the same-named channel of the other selected objects too; stale rows fall back to the
  lead object's real properties.

Registration, the field properties (``Scene.allset_cb``), the scene handlers and the wheel watcher live here; the
rest is in cb_nodes.py, cb_keys.py, cb_pane.py, cb_inputs.py, cb_values.py, cb_selection.py, cb_slider.py,
cb_drag.py, cb_menus.py and cb_panel.py. Every name those modules define can still be imported from here.
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, IntProperty, StringProperty

from .. import depsgraph_filter, live_refs
from .. import update_summary
from ..operators import auto_key
from . import cb_entry

from .cb_nodes import (is_bone, is_root_joint, root_translate, set_root_translate, bone_selected, set_bone_selected,
                       active_object, pose_armature, placing_joints, _generation, _skeletons, layer_armatures,
                       pose_objects, _picked, selected_bones, _drawing_lead, _field_lead, _field_texts, _in_draw,
                       field_lead, _end_field_reads, region_drawn, lead, targets, target_count, full_path,
                       COMPONENT_TYPES, component_mode)
from .cb_pane import (CB_SHARE, CB_SHARE_MAX, CB_LINES, cb_share, _hover, _round_half_up, row_pitch, _redraw, ROW_SCALE,
                      _scroll, _reveal, _last, _filled, WHEEL_LINES, BUTTON_LINES, Lines, reveal, as_lines,
                      window_lines, _unit, _split_off, pane_room, _is_cb_dock, in_channel_part, over_pane, scroll_lines,
                      ALLSET_OT_cb_scroll, _scroll_row, fill_pane, PANE_TOP)
from .cb_keys import (MAIN, MAIN_BY_KEY, _LOCK_PROP, HIDDEN_PROP, NONKEYABLE_PROP, CUSTOM_PREFIX, HISTORY_PREFIX,
                      MODEL_PREFIX, INPUT_PREFIX, CON_PREFIX, SHAPE_PREFIX, BLEND_PREFIX, model_key, model_parts,
                      _flag_list, _set_flag_list, is_hidden, is_keyable, is_locked, set_locked, custom_keys,
                      is_shape_key, is_input_key, is_constraint_key, input_key, constraint_key, input_parts,
                      is_blend_key, blend_path, is_history_key, row_key, channel_path, nice_name)
from .cb_inputs import (blend_target, _driven, driven_modifiers, _inputs, _virtual, input_label, SHAPE_LABELS,
                        shape_label, _open, lead_key, open_nodes, is_open, set_open, pick_node, picked_node, mod_node,
                        history_node, con_node, reset_open, MAYA_CONSTRAINT, _AIM, constraints, constraint_enabled,
                        _nth_constraint, maya_constraint_type, constraint_node_name, weight_name, _axes,
                        constrained_keys, _nth_of_type, row_owner, _row_kind, _row_read, _row_write, _modifier_props,
                        SHAPE_PROPS, wanted_rows, _drawing_sigs, rows_signature, _rows_signature, _rows_state,
                        rebuild_rows, row_for, blend_shape_key, blend_shape_node, blend_shape_targets)
from .cb_values import (model_node, shape_owner, shape_paths, input_owner, input_paths, constraint_weight, _own_weight,
                        input_curve_id, input_curve_paths, history_node_of, _history_get, _history_set, curve_owner,
                        channel_label, has_channel, _non_euler_rot, get_value, WRITE_HOOKS, set_value, keyframe,
                        _fcurves, shape_fcurves, input_fcurves, blend_fcurves, fcurve, channel_fcurves,
                        remove_channel_curves, driver, channel_state, keyed_at, _held_states, _holding, _UNSET,
                        _holds_states, row_state, auto_keys, _KIND_ENTRY, entry_kind)
from .cb_selection import (selected_channels, set_selected_channels, _slider, _view3d_tool, arm_slider, disarm_slider,
                           slider_armed, select_channel, drawn_keys, shown_weight_keys, shown_deformer_keys,
                           history_keys, channel_range, select_range, cell_key, sel_toggle, entry_keys,
                           SELECTION_EDITORS, redraw_selection, _visible_channels, value_cell, selection_column,
                           set_selection_column)
from .cb_slider import (SLIDER_STEP, SPEEDS, SPEED_FACTOR, slider_delta, slider_targets, drag_limit, ROT_DEG_PER_PX,
                        AXIS_MIN_SHARE, node_axes, screen_axis, projected_delta, rotate_delta, slider_apply, _unit_dirs,
                        ALLSET_OT_cb_virtual_slider)
from .cb_menus import (_ChannelAction, _op, _act_key, _act_breakdown, _act_mute, _act_delete, _act_break, _act_lock,
                       _act_hide, _act_keyable, _act_duplicate, CHANNEL_OPS, ALLSET_OT_cb_show_all,
                       ALLSET_MT_cb_channels, ALLSET_MT_cb_freeze, ALLSET_MT_cb_settings, ALLSET_MT_cb_edit,
                       ALLSET_OT_cb_make_lead, ALLSET_OT_cb_rotate_order, ALLSET_MT_cb_object, ALLSET_MT_cb_show,
                       MENU_BAR)
from .cb_drag import (ALLSET_OT_cb_select_channel, ALLSET_OT_cb_deselect_channels, _watching, _anchor, _field_handoff,
                      start_field_drag, _field_is_driven, field_drag_starts, ALLSET_OT_cb_field_drag, _hovered_cell,
                      ALLSET_OT_cb_hover, MENU_ROOM, MENU_GAP, ALLSET_OT_cb_channel_drag, field_owner, _edit,
                      edit_field, ALLSET_PT_cb_field, ALLSET_OT_cb_entry_enter)
from .cb_panel import (CATEGORY, AE_CATEGORY, MTK_CATEGORY, ALLSET_PT_cb_name, ALLSET_OT_cb_rename, EMPTY_TEXT,
                       PLACING_TEXT, POSE_HINT, draw_joint_translate, draw_empty, _STATE_ICON, _ALERT_STATES,
                       state_alert, _row_label, draw_channel_row, _draw_text_row, node_row, ALLSET_OT_cb_node_toggle,
                       _draw_component_lines, _draw_lines, draw_inputs, draw_blend_shape, _draw_group, _draw_interp_row,
                       ALLSET_MT_cb_interp, ALLSET_PT_channel_box, ALLSET_PT_dock_attribute_editor,
                       ALLSET_PT_dock_modeling_toolkit)


@persistent
def _on_scene_change(_scene, depsgraph):
    if not depsgraph_filter.only_motion(depsgraph, _on_scene_change):
        _generation[0] += 1


@persistent
def _on_reload(*_args):
    _generation[0] += 1


_RELOAD_HANDLERS = ("load_post", "undo_post", "redo_post")


def _sel_get(key):
    def get(_self):
        return key in selected_channels()
    return get


def _sel_set(key):
    def set_(_self, value):
        sel = [k for k in selected_channels() if k != key]
        set_selected_channels(sel + [key] if value else sel)
    return set_


def _on_get(_self):
    return True


def _on_set(_self, _value):
    pass


# --- proxies -------------------------------------------------------------------------------------

def _proxy_get(key):
    def get(_self):
        ob = field_lead()
        if ob is None or not has_channel(ob, key):
            return False if MAIN_BY_KEY[key][4] == "VIS" else 0.0
        return get_value(ob, key)
    return get


def _proxy_set(key):
    def set_(_self, value):
        context = bpy.context
        autokey = auto_key.enabled(context.scene)
        for ob in targets(context):
            if not has_channel(ob, key) or is_locked(ob, key):
                continue
            set_value(ob, key, value)
            if autokey and auto_keys(ob, key, context):
                keyframe(ob, key)
    return set_


def apply_entry(key, text, context=None):
    """Typed text on channel ``key``: absolute or relative (``+=``...) per object, on every
    selected object that has the channel; returns how many values changed."""
    context = context or bpy.context
    scene = context.scene
    autokey = auto_key.enabled(scene)
    entries = []
    models = {}
    histories = {}
    history_fields = set()
    for k in entry_keys(key, context):
        for ob in targets(context):
            if not has_channel(ob, k) or is_locked(ob, k):
                continue
            kind = entry_kind(ob, k)
            if kind is None:
                continue
            try:
                if k.startswith(MODEL_PREFIX):
                    from . import node_attributes
                    node = model_node(ob, k)
                    field = k.rsplit(':', 1)[1]
                    if not node_attributes.editable(node, field):
                        continue
                    value = node_attributes.parse_value(node, field, text, scene)
                    if ob not in models:
                        models[ob] = node, dict(node.params)
                    models[ob][1][field] = value
                elif is_history_key(k):
                    from . import node_attributes
                    owner, history = history_node_of(ob, k)
                    field = k[len(HISTORY_PREFIX):]
                    pair = owner.as_pointer(), field
                    if pair in history_fields:
                        continue
                    history_fields.add(pair)
                    node = node_attributes.PrimitiveNode(ob, owner, history)
                    value = node_attributes.parse_value(node, field, text, scene)
                    if value == node.params[field]:
                        continue
                    if pair[0] not in histories:
                        histories[pair[0]] = node, dict(node.params)
                    histories[pair[0]][1][field] = value
                else:
                    value = cb_entry.parse_entry(text, get_value(ob, k), kind, scene)
            except (ValueError, TypeError, SyntaxError):
                return 0
            entries.append((ob, k, value))
    for ob, k, value in entries:
        if k.startswith(MODEL_PREFIX) or is_history_key(k):
            for hook in WRITE_HOOKS:
                hook(ob, k)
        else:
            set_value(ob, k, value)
        if autokey and auto_keys(ob, k, context):
            keyframe(ob, k)
    for node, params in (*models.values(), *histories.values()):
        try:
            node.commit(context, params)
        except (ValueError, RuntimeError) as error:
            from . import notices
            notices.show(str(error))
            return 0
        finally:
            node.finish()
    return len(entries)


def _text_get(key):
    def get(_self):
        drawing = _in_draw()
        if drawing:
            text = _field_texts.get(key)
            if text is not None:
                return text
        ob = field_lead()
        if ob is None or not has_channel(ob, key):
            text = ""
        else:
            text = cb_entry.format_value(get_value(ob, key), entry_kind(ob, key), bpy.context.scene)
        if drawing:
            _field_texts[key] = text
        return text
    return get


def _text_set(key):
    def set_(_self, text):
        apply_entry(key, text)
    return set_


def _row_get(self):
    ob = field_lead()
    if ob is None:
        return ""
    owner = row_owner(ob, self.kind, self.name, self.mod_type, self.nth)
    if owner is None:
        return ""
    entry = _row_kind(owner, self.kind, self.name)
    return cb_entry.format_value(_row_value(ob, owner, self), entry, bpy.context.scene)


def _row_value(ob, owner, row):
    """A row's value on ``ob``: a constraint's target weight through its channel (the constraint's own weight once
    it has one, else its influence), any other row's property."""
    if row.kind == "CONSTRAINT":
        return get_value(ob, row_key(row))
    return _row_read(owner, row.kind, row.name)


def apply_row_entry(row, text, context=None):
    """Typed text on a custom / SHAPES / INPUTS row: every selected object with that channel."""
    context = context or bpy.context
    if row.kind == "CUSTOM":
        return apply_entry(CUSTOM_PREFIX + row.name, text, context)
    ld = lead(context)
    autokey = auto_key.enabled(context.scene)
    count = 0
    for ob in targets(context):
        owner = row_owner(ob, row.kind, row.name, row.mod_type, row.nth, ld)
        if owner is None:
            continue
        entry = _row_kind(owner, row.kind, row.name)
        try:
            value = cb_entry.parse_entry(text, _row_value(ob, owner, row), entry, context.scene)
        except (ValueError, TypeError, SyntaxError):
            return count
        try:
            if row.kind == "CONSTRAINT":
                # the target weight: Maya's one-target rule gives the constraint its own weight (set_value)
                key = row_key(row)
                set_value(ob, key, value)
                if autokey and auto_keys(ob, key, context):
                    keyframe(ob, key)       # Auto Key: a weight that has keys is keyed, like a typed Translate X
            else:
                _row_write(owner, row.kind, row.name, value)
        except (TypeError, ValueError, AttributeError):
            continue
        count += 1
    return count


def _row_set(self, text):
    apply_row_entry(self, text)


def _row_sel_get(self):
    key = row_key(self)
    return key is not None and key in selected_channels()


def _row_sel_set(self, value):
    key = row_key(self)
    if key is not None:
        _sel_set(key)(self, value)


class ALLSET_PG_cb_row(bpy.types.PropertyGroup):
    kind: StringProperty()        # CUSTOM / SHAPE / INPUT / CONSTRAINT / BLEND
    name: StringProperty()        # property name (BLEND: the blendShape target's name)
    mod_type: StringProperty()    # INPUT: modifier type, CONSTRAINT: constraint type
    nth: IntProperty()            # position among the lead's modifiers / constraints of that type
    text: StringProperty(get=_row_get, set=_row_set)
    text_on: BoolProperty(name="Value", get=_on_get, set=_on_set)
    sel: BoolProperty(name="Selected", get=_row_sel_get, set=_row_sel_set,
                      description="Select this channel: click, Ctrl toggle, Shift range, drag over the rows")
    sel_on: BoolProperty(name="Selected", get=_row_sel_get, set=_row_sel_set,
                         description="Select this channel: click, Ctrl toggle, Shift range, drag over the rows")


# --- the name line: click to rename (#283) ---------------------------------------------------------------

def rename_lead(ob, text):
    """Maya Channel Box name field: rename the lead (spaces -> "_", Maya's name rule; a taken name gets the next
    number of its base, the shape follows like Maya's rename). Returns the new name, None when nothing changed."""
    from . import input_line
    name = input_line.clean_name(text)
    if name is None:
        input_line._say(input_line.BAD_NAME.format(text.strip()))
        return None
    if is_bone(ob):
        name = input_line.number_hash(name, {b.name for b in ob.id_data.data.bones if b.name != ob.name}
                                      | {o.name for o in bpy.data.objects})
    else:
        name = input_line.number_hash(name, {o.name for o in bpy.data.objects if o != ob})
    if name == ob.name:
        return None
    if is_bone(ob):
        ob.name = name
        return ob.name
    from ..operators import naming
    taken = {o.name for o in bpy.data.objects if o != ob}
    if name in taken:       # a taken name: its base with one more than the highest number (pCube1 -> pCube2)
        base = naming.base_name(name)
        name = f"{base}{naming.next_number(base, taken)}"
    new = name
    ob.name = new
    data = ob.data
    if data is not None and data.users == 1 and hasattr(data, "name") and data.library is None:
        data.name = input_line.shape_name(new)
    return new


def _lead_name_get(_self):
    ob = field_lead()
    return ob.name if ob is not None else ""


def _lead_name_set(_self, value):
    ob = lead()
    if ob is not None and rename_lead(ob, value) is not None:
        _redraw_all()


def _redraw_all():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def _entry_text_get(_self):
    return _edit["text"]


def _entry_text_set(_self, text):
    # Blender commits a text field on Enter and on a click away alike; the editor's watcher (ALLSET_OT_cb_entry_enter)
    # has noted an Enter press by then. Like Maya, Enter writes the text into every selected channel also when it is
    # unchanged, a click away only a changed text.
    key, enter = _edit["key"], _edit["enter"]
    _edit["enter"] = False
    _edit["watch"] += 1                   # committed: the watcher ends
    if key is None or not text.strip():
        return
    if text == _edit["text"] and not enter:
        return
    apply_entry(key, text)


def _make_proxy_annotations():
    ann = {}
    for key, label, _path, _idx, kind in MAIN:
        if kind == "VIS":
            ann[key] = BoolProperty(name=label, get=_proxy_get(key), set=_proxy_set(key))
        elif kind == "LOC":
            ann[key] = FloatProperty(name=label, get=_proxy_get(key), set=_proxy_set(key),
                                     subtype='DISTANCE', unit='LENGTH', precision=3, step=10)
        elif kind == "ROT":
            ann[key] = FloatProperty(name=label, get=_proxy_get(key), set=_proxy_set(key),
                                     subtype='ANGLE', unit='ROTATION', precision=3)
        else:
            ann[key] = FloatProperty(name=label, get=_proxy_get(key), set=_proxy_set(key),
                                     precision=3, step=10)
        ann[key + "_text"] = StringProperty(name=label, get=_text_get(key), set=_text_set(key))
        ann[key + "_text_on"] = BoolProperty(name=label, get=_on_get, set=_on_set)
        for suffix in ("_sel", "_sel_on"):
            ann[key + suffix] = BoolProperty(name=label, get=_sel_get(key), set=_sel_set(key),
                                             description="Select this channel: click, Ctrl toggle, Shift range, "
                                                         "drag over the rows")
    ann["lead_name"] = StringProperty(name="Name", get=_lead_name_get, set=_lead_name_set,
                                      description="The lead's name: Enter renames it")
    ann["entry_text"] = StringProperty(name="Value", get=_entry_text_get, set=_entry_text_set,
                                       description="A value for every selected channel: Enter sets it")
    ann["rows"] = CollectionProperty(type=ALLSET_PG_cb_row)
    ann["rows_sig"] = StringProperty(options={'HIDDEN'})
    return ann


ALLSET_PG_channel_box = type("ALLSET_PG_channel_box", (bpy.types.PropertyGroup,),
                              {"__annotations__": _make_proxy_annotations()})


def is_cb_button(context):
    """The button under the mouse is a Channel Box channel name or value (for its RMB menu)."""
    op = getattr(context, "button_operator", None)
    if op is not None and op.bl_rna.identifier == ALLSET_OT_cb_select_channel.__name__:
        return True
    ptr = getattr(context, "button_pointer", None)
    return isinstance(ptr, (ALLSET_PG_channel_box, ALLSET_PG_cb_row))


# Maya's Channel Box RMB menu = the Channels menu. RMB on a UI button
# opens Blender's button context menu from C (not a keymap item), so the Channels items go on top of it.
RMB_ITEMS = (("allset.cb_key_selected", "Key Selected", {}),
             ("allset.cb_breakdown_selected", "Breakdown Selected", {}),
             ("allset.cb_mute", "Mute Selected", {"mute": True}),
             ("allset.cb_mute", "Unmute Selected", {"mute": False}),
             ("allset.cb_delete_keys", "Delete Selected", {}),
             ("allset.cb_break_connections", "Break Connections", {}),
             ("allset.cb_lock", "Lock Selected", {"lock": True}),
             ("allset.cb_lock", "Unlock Selected", {"lock": False}),
             ("allset.cb_hide", "Hide Selected", {"lock": False}),
             ("allset.cb_keyable", "Make Selected Nonkeyable", {"keyable": False}))


def draw_button_menu(self, context):
    if not is_cb_button(context):
        return
    lay = self.layout
    for idname, text, props in RMB_ITEMS:
        op = lay.operator(idname, text=text)
        for k, v in props.items():
            setattr(op, k, v)
    lay.separator()


def _nothing_selected(context):
    sel = getattr(context, "selected_objects", None)
    if sel is None:
        return False     # a window context without a view layer (File Browser, Preferences)
    if getattr(context.window_manager, "allset_character_nodes", ""):
        return False     # picked character nodes stand in for the selection
    if pose_armature(context) is not None:
        return not selected_bones(context)
    return not sel


@persistent
def _on_depsgraph(_scene, depsgraph):
    if _held_states and (depsgraph is None or depsgraph.id_type_updated('ACTION')):
        _held_states.clear()           # keys moved (or keyed) during a move: the rows' states are read again
    from .maya_joints import transforming
    if not transforming():             # a drag changes values only: the selection and the rows stay
        if selected_channels() and _nothing_selected(bpy.context):
            update_summary.wrote()
            set_selected_channels([])      # Maya: deselecting everything also deselects the channels
        rebuild_rows()
    # The dock is a custom PROPERTIES-area UI, not Blender's native transform
    # sidebar. Tag it explicitly: transform gizmos can update RNA values without
    # invalidating the Channel Box panel's drawn value fields.
    from . import maya_dock
    maya_dock.redraw()


@persistent
def _on_load(_dummy):
    global _wheel_generation
    _wheel_generation += 1
    _wheel_windows.clear()
    _last.clear()
    reset_open()
    rebuild_rows()


_transform_snapshot = None


def _transforming():
    """A transform modal (manipulator drag, G / R / S) runs in some window."""
    wm = bpy.context.window_manager
    from ..operators.manip_scale import TRANSFORM_MODALS
    return wm is not None and any(op.bl_idname.startswith(TRANSFORM_MODALS)
                                  for w in wm.windows for op in live_refs.running_modals(w))


def _poll_transform_values():
    """Refresh displayed transform channels even during modal gizmo movements."""
    global _transform_snapshot
    _end_field_reads()      # timers run between redraws: a draw-time lead never outlives one
    try:
        ob = lead()
        if ob is None:
            signature = None
        elif is_bone(ob):
            signature = (ob.id_data.as_pointer(), ob.name, tuple(v for row in ob.matrix for v in row))
        else:
            signature = (ob.as_pointer(), tuple(ob.location), tuple(ob.rotation_euler),
                         tuple(ob.rotation_quaternion), tuple(ob.rotation_axis_angle),
                         tuple(ob.scale), ob.rotation_mode, ob.hide_viewport)
        # Redraw when the lead's channels changed, and on every tick while a transform modal runs (its RNA values
        # can stay the same between ticks while the drawn fields are stale); idle ticks draw nothing.
        if signature != _transform_snapshot or _transforming():
            _transform_snapshot = signature
            from . import maya_dock
            maya_dock.redraw()
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    return 0.1


def _first_rebuild():
    rebuild_rows()
    return None


_wheel_windows = {}   # live window pointer -> registration generation
_wheel_generation = 0


class ALLSET_OT_cb_wheel(bpy.types.Operator):
    """Catch Channel Box scrolling before Blender's field and panel handlers"""
    bl_idname = 'allset.cb_wheel'
    bl_label = 'Channel Box Wheel Navigation'
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if context.window is None:
            return {'CANCELLED'}
        self._window_ptr = context.window.as_pointer()
        self._generation = _wheel_generation
        self._fraction = {}
        _wheel_windows[self._window_ptr] = self._generation
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        from .. import live_refs
        window = live_refs.window(self._window_ptr)
        if self._generation != _wheel_generation or window is None:
            if _wheel_windows.get(self._window_ptr) == self._generation:
                _wheel_windows.pop(self._window_ptr, None)
            return {'CANCELLED', 'PASS_THROUGH'}
        if (event.type not in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN'} or event.oskey):
            return {'PASS_THROUGH'}
        # Resolve the current regions each event: panes can resize, change tabs,
        # move to another window, or close while this window watcher is running.
        x, y = event.mouse_x, event.mouse_y
        for area in window.screen.areas:
            if area.type != 'PROPERTIES':
                continue
            for region in area.regions:
                if (region.type != 'WINDOW' or not region.x <= x < region.x + region.width
                        or not region.y <= y < region.y + region.height):
                    continue
                with context.temp_override(window=window, area=area, region=region):
                    ctx = bpy.context
                    from . import maya_dock
                    if x >= region.x + region.width - maya_dock.area_reserved_px(ctx):
                        return {'PASS_THROUGH'}
                    from types import SimpleNamespace
                    if event.ctrl or event.shift or event.alt:
                        # Ctrl+wheel over a value steps it, also over a selected value's blue cell (a toggle,
                        # which Blender's own Ctrl+wheel would only flip) and when the rows fit
                        hit = _hover.get(self._window_ptr)
                        if (event.ctrl and event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}
                                and hit is not None and hit[1] == 'VALUE'
                                and maya_dock.shown_kind(ctx) == 'CHANNEL_BOX'
                                and field_drag_starts(ctx, hit[0])):
                            start_field_drag(ctx, event, hit[0], event.mouse_x)
                            # The gesture belongs to the field even at a limit or
                            # on a rounded no-op; don't send it on to the UI too.
                            return {'RUNNING_MODAL'}
                        return {'PASS_THROUGH'}
                    if not over_pane(ctx, SimpleNamespace(mouse_region_y=y - region.y)):
                        return {'PASS_THROUGH'}
                    if event.type == 'TRACKPADPAN':
                        ptr = area.as_pointer()
                        delta = (event.mouse_prev_y - event.mouse_y) / row_pitch(ctx)
                        fraction = self._fraction.get(ptr, 0.0) + delta
                        amount = int(fraction)
                        self._fraction[ptr] = fraction - amount
                    else:
                        amount = WHEEL_LINES if event.type == 'WHEELDOWNMOUSE' else -WHEEL_LINES
                    scroll_lines(ctx, amount)
                    return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}


def _ensure_wheel_watch():
    if bpy.app.background:
        return None
    for window in bpy.context.window_manager.windows:
        if _wheel_windows.get(window.as_pointer()) == _wheel_generation:
            continue
        for area in window.screen.areas:
            if area.type != 'PROPERTIES':
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue
            with bpy.context.temp_override(window=window, area=area, region=region):
                if _is_cb_dock(bpy.context):
                    bpy.ops.allset.cb_wheel('INVOKE_DEFAULT', True)
                    break
    return 0.25


classes = (ALLSET_PG_cb_row, ALLSET_PG_channel_box, ALLSET_OT_cb_virtual_slider, ALLSET_OT_cb_select_channel,
           ALLSET_OT_cb_deselect_channels, ALLSET_OT_cb_hover, ALLSET_OT_cb_channel_drag, ALLSET_OT_cb_field_drag,
           ALLSET_PT_cb_field, ALLSET_OT_cb_entry_enter, ALLSET_PT_cb_name, ALLSET_OT_cb_rename, ALLSET_OT_cb_node_toggle, ALLSET_OT_cb_scroll, ALLSET_OT_cb_wheel, *CHANNEL_OPS,
           ALLSET_OT_cb_show_all,
           ALLSET_MT_cb_channels, ALLSET_MT_cb_freeze, ALLSET_MT_cb_settings, ALLSET_OT_cb_make_lead,
           ALLSET_OT_cb_rotate_order, ALLSET_MT_cb_edit, ALLSET_MT_cb_interp,
           ALLSET_MT_cb_object, ALLSET_MT_cb_show)
# ALLSET_PT_channel_box / _dock_attribute_editor / _dock_modeling_toolkit are no longer registered as 3D View sidebar
# tabs: the Maya panels live in their own dock areas / floating windows (ui/maya_dock.py), which call
# ``ALLSET_PT_channel_box.body`` etc.


def register():
    global _wheel_generation
    _wheel_generation += 1
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.allset_cb = bpy.props.PointerProperty(type=ALLSET_PG_channel_box)
    bpy.types.WindowManager.allset_cb_selected = StringProperty(
        name="Selected Channels", options={'SKIP_SAVE'})
    # in front: the handlers that ask the Channel Box during this update see the kept scene facts dropped
    bpy.app.handlers.depsgraph_update_post.insert(0, _on_scene_change)
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    for name in _RELOAD_HANDLERS:
        getattr(bpy.app.handlers, name).append(_on_reload)
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.timers.register(_first_rebuild, first_interval=0.0)
    if not bpy.app.timers.is_registered(_poll_transform_values):
        # persistent: Blender drops the other timers on File > Open / New (and the Maya layout opening is one)
        bpy.app.timers.register(_poll_transform_values, first_interval=0.1, persistent=True)
    bpy.types.UI_MT_button_context_menu.prepend(draw_button_menu)
    if not bpy.app.background:
        bpy.app.timers.register(_ensure_wheel_watch, first_interval=0.0, persistent=True)


def unregister():
    global _transform_snapshot, _wheel_generation
    _wheel_generation += 1
    _wheel_windows.clear()
    if bpy.app.timers.is_registered(_ensure_wheel_watch):
        bpy.app.timers.unregister(_ensure_wheel_watch)
    _transform_snapshot = None
    if bpy.app.timers.is_registered(_poll_transform_values):
        bpy.app.timers.unregister(_poll_transform_values)
    _reveal["node"] = None
    _watching.clear()
    _hover.clear()
    reset_open()
    _last.clear()
    bpy.types.UI_MT_button_context_menu.remove(draw_button_menu)
    if bpy.app.timers.is_registered(_first_rebuild):
        bpy.app.timers.unregister(_first_rebuild)
    bpy.app.handlers.load_post.remove(_on_load)
    bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    for name in _RELOAD_HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        while _on_reload in handlers:
            handlers.remove(_on_reload)
    while _on_scene_change in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_scene_change)
    _skeletons.clear()
    _driven.clear()
    _end_field_reads()
    del bpy.types.WindowManager.allset_cb_selected
    del bpy.types.Scene.allset_cb
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
