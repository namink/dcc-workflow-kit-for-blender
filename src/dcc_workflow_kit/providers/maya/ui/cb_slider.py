# SPDX-License-Identifier: GPL-3.0-or-later
"""The virtual slider: a middle drag in a view changes the selected channels (translate along the axis as drawn,
rotate by mouse distance, other channels by step and speed).
Entry points: ALLSET_OT_cb_virtual_slider, slider_targets, slider_apply, drag_limit.
Related: cb_selection.py (arming), cb_values.py."""

import math

import bpy

from ..operators import auto_key

from .cb_nodes import targets
from .cb_keys import (MAIN_BY_KEY, MODEL_PREFIX, channel_path, input_parts, is_constraint_key, is_hidden, is_input_key,
                      is_locked)
from .cb_values import (_non_euler_rot, auto_keys, channel_label, entry_kind, get_value, has_channel, input_owner,
                        keyframe, model_node, set_value)
from .cb_selection import _slider, _view3d_tool, selected_channels, slider_armed


# MMB slider: value change per pixel at speed Medium (a custom attribute moves 0.1 per px, like Maya).
SLIDER_STEP = {"LOC": 0.01, "ROT": math.radians(0.5), "SCALE": 0.01, "CUSTOM": 0.1, "SHAPE": 0.01, "INPUT": 0.01,
               "HISTORY": 0.01, "BLEND": 0.01, "MODEL": 0.01}
SPEEDS = (("SLOWEST", "Slowest", "x0.01", 0.01), ("SLOW", "Slow", "x0.1", 0.1),
          ("MEDIUM", "Medium", "x1", 1.0), ("FAST", "Fast", "x10", 10.0))
SPEED_FACTOR = {s[0]: s[3] for s in SPEEDS}


# --- MMB virtual slider ---------------------------------------------------------------------------

def slider_delta(dx, kind, speed=1.0, ctrl=False, shift=False, hyperbolic=False):
    from . import attribute_edit
    return attribute_edit.delta(dx, SLIDER_STEP[kind], speed, ctrl, shift, hyperbolic)


def slider_targets(context):
    """[(object, key)] the slider would change: selected numeric channels on targets."""
    out = []
    for key in selected_channels(context):
        if key in MAIN_BY_KEY and MAIN_BY_KEY[key][4] == "VIS":
            continue
        for ob in targets(context):
            if has_channel(ob, key) and not is_locked(ob, key) and not is_hidden(ob, key):
                value = get_value(ob, key)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                if entry_kind(ob, key) in {None, 'ENUM'}:
                    continue     # an enum attribute (Maya's slider skips it)
                if key.startswith(MODEL_PREFIX):
                    from . import node_attributes
                    if not node_attributes.editable(model_node(ob, key), key.rsplit(':', 1)[1]):
                        continue
                out.append((ob, key))
    return out


def drag_limit(ob, key, value):
    """A dragged INPUTS value stays in the property's soft range, like Blender's own field drag (a Subdivision's
    Levels stops at 6; typing can go to the hard limit); a constraint's target weight stays at 0 or more."""
    if key.startswith(MODEL_PREFIX):
        node = model_node(ob, key)
        return node.descriptor(key.rsplit(':', 1)[1], soft=True).limit(value)
    if not is_input_key(key):
        return value
    owner = input_owner(ob, key)
    if is_constraint_key(key) and owner is not None:
        from ..operators import constrain_multi
        if constrain_multi.single_applies(owner, ob):
            return max(0.0, value)      # a Maya target weight: 0 or more (any weight above 0 = on the target)
    rna = owner.bl_rna.properties.get(input_parts(key)[2]) if owner is not None else None
    if rna is None or rna.type not in {'INT', 'FLOAT'}:
        return value
    return max(rna.soft_min, min(rna.soft_max, value))


ROT_DEG_PER_PX = 0.36     # a selected rotate channel turns 0.36 degrees per px, right / down = more (like Maya)
AXIS_MIN_SHARE = 0.15     # an axis seen nearly end-on (shorter than this share of the longest) drags sideways


def node_axes(ob, key):
    """(world origin, world direction moved by one unit of the translate channel ``key``) of an object or pose
    bone, None for other channels."""
    path, index, kind = channel_path(key) if key in MAIN_BY_KEY else (None, -1, None)
    if kind != "LOC" or index < 0:
        return None
    from mathutils import Vector
    if isinstance(ob, bpy.types.PoseBone):
        arm = ob.id_data
        world = arm.matrix_world @ ob.matrix
        basis = ob.matrix_basis
    else:
        world, basis = ob.matrix_world, ob.matrix_basis
    try:
        parent = world.to_3x3() @ basis.to_3x3().inverted()
    except ValueError:
        return None
    axis = Vector((0.0, 0.0, 0.0))
    axis[index] = 1.0
    return world.translation.copy(), parent @ axis


def screen_axis(region, rv3d, origin, direction):
    """Region px moved per unit along ``direction`` at ``origin`` (None when it can't be projected)."""
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    eps = 1e-3
    a = location_3d_to_region_2d(region, rv3d, origin)
    b = location_3d_to_region_2d(region, rv3d, origin + direction * eps)
    if a is None or b is None:
        return None
    return (b - a) / eps


def projected_delta(axis_px, dx, dy):
    """Units along an axis for a mouse move (dx, dy): the move projected on the axis as drawn, like dragging that
    axis of the Move manipulator (vertical moves count)."""
    ax, ay = axis_px
    n = ax * ax + ay * ay
    return (dx * ax + dy * ay) / n if n > 0.0 else 0.0


def rotate_delta(dx, dy):
    """Radians for a mouse move on a selected rotate channel: right and down turn it up, left and up down."""
    return math.radians(ROT_DEG_PER_PX) * (dx - dy)


def slider_apply(starts, dx, speed=1.0, ctrl=False, shift=False, hyperbolic=False):
    """starts: {(ob, key): start value}. Sets each to start + delta."""
    for (ob, key), start in starts.items():
        kind = channel_path(key)[2]
        set_value(ob, key, drag_limit(ob, key, start + slider_delta(dx, kind, speed, ctrl, shift, hyperbolic)))


def _unit_dirs(direction):
    """``direction`` and two directions of the same length square to it (to tell an end-on axis)."""
    from mathutils import Vector
    n = direction.normalized()
    side = n.orthogonal().normalized()
    return [direction, side * direction.length, n.cross(side) * direction.length]


class ALLSET_OT_cb_virtual_slider(bpy.types.Operator):
    """MMB-drag in the viewport changes the channels selected in the Channel Box"""
    bl_idname = "allset.cb_virtual_slider"
    bl_label = "Channel Box Virtual Slider"
    bl_options = {'REGISTER', 'GRAB_CURSOR', 'BLOCKING'}

    def invoke(self, context, event):
        from . import attribute_edit
        from .. import preferences
        if (_slider['armed'] and _view3d_tool(context) == _slider['tool']
                and preferences.get(context).cb_manipulators == 'NONE'):
            return {'CANCELLED'}
        if context.mode not in {'OBJECT', 'POSE', 'EDIT_MESH'} or not slider_armed(context):
            return self._pass(context, event)  # another tool was picked after the channels: its own middle drag
        pairs = slider_targets(context)
        if context.mode == 'EDIT_MESH':
            pairs = [(ob, key) for ob, key in pairs if key.startswith(MODEL_PREFIX)]
        if not pairs:
            return self._pass(context, event)  # let the tool's MMB drag run
        if attribute_edit.busy(context):
            return {'PASS_THROUGH'}
        self._starts = {(ob, key): get_value(ob, key) for ob, key in pairs}
        self._nodes = {ob: model_node(ob, key) for ob, key in pairs if key.startswith(MODEL_PREFIX)}
        self._node_starts = {ob: dict(node.params) for ob, node in self._nodes.items()}
        self._drags = {}
        self._axes = {}
        self._dx = self._dy = 0
        self._last = event.mouse_x, event.mouse_y
        self._scene, self._frame = context.scene, context.scene.frame_current
        self._object = context.active_object
        self._window = context.window.as_pointer()
        self._mode = context.mode
        self._tool = _view3d_tool(context)
        region, rv3d = context.region, context.region_data
        for ob, key in pairs:
            kind = channel_path(key)[2]
            if key.startswith(MODEL_PREFIX):
                descriptor = self._nodes[ob].descriptor(channel_path(key)[0], soft=True)
            else:
                descriptor = attribute_edit.Field(entry_kind(ob, key), SLIDER_STEP[kind])
            self._drags[(ob, key)] = attribute_edit.Drag(self._starts[(ob, key)], descriptor)
            if rv3d is None or context.area.type != 'VIEW_3D':
                continue
            if kind == "ROT" and not _non_euler_rot(ob, kind):
                self._axes[(ob, key)] = "ROT"
                continue
            axes = node_axes(ob, key)
            if axes is None:
                continue
            px = screen_axis(region, rv3d, *axes)
            longest = max((v.length for v in (screen_axis(region, rv3d, axes[0], d) for d in
                                               _unit_dirs(axes[1])) if v is not None), default=0.0)
            if px is not None and px.length > AXIS_MIN_SHARE * longest > 0.0:
                self._axes[(ob, key)] = (px.x, px.y)
        if not attribute_edit.claim(context, self):
            return {'CANCELLED'}
        self._finished = False
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    @staticmethod
    def _pass(context, event):
        """No channel to drive: the In-View Editor's row drag where the view shows one (it runs as its own modal;
        CANCELLED ends this one without an undo step), else the event goes on to the tool's middle drag."""
        from . import in_view
        return {'CANCELLED'} if in_view.mmb_drag(context, event) else {'PASS_THROUGH'}

    def _header(self, context, text):
        if context.area:
            context.area.header_text_set(text)

    def _finish(self, context, cancel=False):
        from . import attribute_edit
        if getattr(self, '_finished', True):
            return {'CANCELLED'}
        self._finished = True
        changed = False
        try:
            for ob, node in self._nodes.items():
                if node.valid():
                    if cancel:
                        node.preview(context, self._node_starts[ob])
                    node_changed = node.params != self._node_starts[ob]
                    changed |= node_changed
                    if not cancel and node_changed:
                        node.commit(context, node.params)
                    node.finish()
            for (ob, key), start in self._starts.items():
                if key.startswith(MODEL_PREFIX):
                    continue
                try:
                    changed |= get_value(ob, key) != start
                    if cancel:
                        set_value(ob, key, start)
                    elif (get_value(ob, key) != start and auto_key.enabled(context.scene)
                          and auto_keys(ob, key, context)):
                        keyframe(ob, key)
                except (ReferenceError, RuntimeError, AttributeError):
                    pass
        finally:
            self._header(context, None)
            attribute_edit.release(self._window, self)
        if not cancel and changed:
            from .. import undo_steps
            undo_steps.push('Edit Channel Attributes')
        return {'CANCELLED'} if cancel or not changed else {'FINISHED'}

    def modal(self, context, event):
        try:
            if (context.scene != self._scene or context.scene.frame_current != self._frame
                    or context.active_object != self._object or context.mode != self._mode
                    or _view3d_tool(context) != self._tool):
                return self._finish(context, cancel=True)
            if event.type == 'MOUSEMOVE':
                sx, sy = event.mouse_x-self._last[0], event.mouse_y-self._last[1]
                self._last = event.mouse_x, event.mouse_y
                if context.region and abs(sx) > context.region.width//2:
                    sx = 0
                if context.region and abs(sy) > context.region.height//2:
                    sy = 0
                self._dx += sx
                self._dy += sy
                from .. import preferences
                prefs = preferences.get(context)
                pending = {ob: dict(node.params) for ob, node in self._nodes.items()}
                for pair, start in self._starts.items():
                    ob, key = pair
                    how = self._axes.get(pair)
                    if how == 'ROT':
                        value = start+rotate_delta(self._dx, self._dy)
                    elif how is not None:
                        value = start+projected_delta(how, self._dx, self._dy)
                    else:
                        value = self._drags[pair].move(sx/(context.preferences.system.ui_scale or 1.0),
                                                      SPEED_FACTOR[prefs.cb_speed], event.ctrl,
                                                      event.shift, prefs.cb_hyperbolic)
                        value = drag_limit(ob, key, value)
                    if key.startswith(MODEL_PREFIX):
                        pending[ob][channel_path(key)[0]] = value
                    elif get_value(ob, key) != value:
                        set_value(ob, key, value)
                for ob, params in pending.items():
                    if self._nodes[ob].params != params:
                        self._nodes[ob].preview(context, params)
                ob, key = next(iter(self._starts))
                self._header(context, f"{channel_label(key)}: {get_value(ob, key):.3f}")
                context.area.tag_redraw()
            elif event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
                return self._finish(context)
            elif event.type in {'ESC', 'RIGHTMOUSE', 'WINDOW_DEACTIVATE'}:
                return self._finish(context, cancel=True)
            elif event.value == 'PRESS' and event.type in {'Q', 'W', 'E', 'R', 'T', 'Z'}:
                self._finish(context, cancel=True)
                return {'CANCELLED', 'PASS_THROUGH'}
        except (ReferenceError, RuntimeError, AttributeError, TypeError, ValueError) as error:
            self.report({'WARNING'}, str(error))
            return self._finish(context, cancel=True)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._finish(context, cancel=True)
