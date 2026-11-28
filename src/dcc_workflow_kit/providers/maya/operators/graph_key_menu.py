# SPDX-License-Identifier: GPL-3.0-or-later
"""Graph Editor / Dope Sheet key commands in Maya terms.

- Edit menu key windows from a key editor act on the **selected keys** (Maya's Edit > Cut / Copy / Delete Keys & co.:
  from the Graph Editor with keys selected and the "keys" option; else the time range of the nodes,
  ``operators/time_keys``).
- Keys > Add / Remove Inbetween: the keys after the current time on the curves the editor shows move by one frame
  (Maya's Graph Editor Keys menu).
- Keys > Mute / Unmute Key: Maya keys a mute node so the curve holds the muted key's value until the
  next unmuted key. Blender has no per-key mute: a Stepped F-modifier limited to
  [muted key, next unmuted key) gives the same values; the modifiers named ``MUTE_NAME`` are the kit's.
- Select > All / Only Curve / Curve / Key / In Tangent / Out Tangent (Maya's Graph Editor Select menu): pick masks
  as add-on prefs; Blender has none, so ``_mask_tick`` filters what a selection just added.
- Tangents > Default In / Out Tangent: add-on prefs applied to the keys the kit sets (``after_insert``).

Code: graph_key_edits (the selected keys and the key edits on them), graph_select_masks (the Select menu masks);
this module keeps the default in / out tangents and their handlers, the operators, register_bindings and
re-exports the other modules' names.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty

from .. import undo_steps
from .. import update_summary
from . import time_keys
from .. import i18n
from .graph_key_edits import (_clip, _curve_keys, _END_GAP, _ensure_key, _FAR, _key_at, _remove,  # noqa: F401
                              _remove_at, _space, clamp_keys, copy_selected, cut_selected, delete_selected,
                              editor_clipboard, editor_curves, EPS, has_selected_keys, in_key_editor, inbetween,
                              mute_modifiers, MUTE_NAME, mute_selected, muted_times, note_kit_copy, offset_keys,
                              paste_editor, remove_keys, RIPPLE_GAP, scale_selected, selected_keys, selected_range,
                              set_muted, snap_selected)
from .graph_select_masks import (_curves, _flags, _graph_open, _mask, _mask_reset, _mask_tick, _prefs,  # noqa: F401
                                 _signature, MASK_POLL, mask_step, MASKS, masks, remember_masks)


def _redraw(context):
    for area in context.screen.areas if getattr(context, "screen", None) else ():
        if area.type in {'GRAPH_EDITOR', 'DOPESHEET_EDITOR', 'VIEW_3D', 'PROPERTIES'}:
            area.tag_redraw()


# --- Default In / Out Tangent -------------------------------------------------------------------------------

def default_tangents():
    p = _prefs()
    if p is None:
        return "AUTO", "AUTO"
    return p.default_in_tangent, p.default_out_tangent


def apply_default(fc, kp):
    """The default in / out tangent (like Maya) on a key the kit just set (Auto = Blender's own new key: untouched)."""
    tin, tout = default_tangents()
    if tin == "AUTO" and tout == "AUTO":
        return False
    if tin == tout:
        time_keys.apply_tangent(kp, tin, fc)
    else:
        _default_side(kp, tin, "IN", fc)
        _default_side(kp, tout, "OUT", fc)
    fc.update()
    return True


def _default_side(kp, kind, side, fc=None):
    """One side of a new key. Blender's interpolation belongs to the segment after a key, so only a Stepped out
    tangent changes it; a Linear side = a Vector handle (points at the neighbour key), the neighbour segment keeps
    its shape (Maya: the other key's own tangent)."""
    if kind == "AUTO":
        return
    if kind == "STEPPED":            # out only (Maya has no stepped in tangent)
        kp.interpolation = 'CONSTANT'
        return
    # a Flat side next to a different one is a free handle (an aligned one would follow the other side)
    handle = {"LINEAR": 'VECTOR', "FLAT": 'FREE'}.get(kind) or time_keys.TANGENTS[kind][1]
    setattr(kp, "handle_left_type" if side == "IN" else "handle_right_type", handle)
    if kind == "FLAT":
        (kp.handle_left if side == "IN" else kp.handle_right).y = kp.co.y
    if fc is not None:
        from . import maya_tangents
        maya_tangents.mark(fc, kp, kind, side)


def _new_curve_weights(idd, full, index):
    from . import graph_weights
    from .. import compat
    try:
        for fc in compat.id_fcurves(idd):
            if fc.data_path == full and (index is None or index < 0 or fc.array_index == index)                     and len(fc.keyframe_points) == 1:
                graph_weights.apply_default(fc)
    except (AttributeError, TypeError, ReferenceError):
        pass


def after_insert(owner, path, index, frame):
    """Apply the default tangents to the keys ``owner.keyframe_insert(path, index=index, frame=frame)`` made.
    ``owner`` is an ID or a struct inside one (pose bone). A curve this insert created gets the Default Tangent
    Weight (operators/graph_weights.apply_default)."""
    from .. import compat
    idd = owner.id_data
    full = path if owner == idd else owner.path_from_id(path)
    _new_curve_weights(idd, full, index)
    from . import maya_tangents
    n = 0
    for fc in compat.id_fcurves(idd):
        if fc.data_path != full or (index is not None and index >= 0 and fc.array_index != index):
            continue
        kp = next((k for k in fc.keyframe_points if abs(k.co.x - frame) <= EPS), None)
        if kp is not None and apply_default(fc, kp):
            n += 1
        # Maya tangent shapes on the curve (the new key and its neighbours; #151, #210)
        maya_tangents.apply(fc)
    return n


# --- Blender's own keys: the default in / out tangent too ----------------------------------------------------------
# Blender's insert operators (I key, Insert Keyframe menu and button, the Graph Editor / Dope Sheet insert) make keys
# with Blender's own handles. Right after one of them finished, the keys it added get the Default In / Out Tangent like
# the kit's keys. A key that replaced one already on that frame keeps its tangents.

BLENDER_KEY_OPS = frozenset(("ANIM_OT_keyframe_insert", "ANIM_OT_keyframe_insert_menu",
                             "ANIM_OT_keyframe_insert_by_name", "ANIM_OT_keyframe_insert_button",
                             "GRAPH_OT_keyframe_insert", "GRAPH_OT_click_insert", "ACTION_OT_keyframe_insert"))
_frames = {}                # Action name -> {curve key: frozenset of key frames} as last seen
_insert = {"op": 0}


def _curve_frames(action):
    from .. import compat
    return {f"{fc.data_path}|{fc.array_index}": frozenset(round(kp.co.x, 3) for kp in fc.keyframe_points)
            for fc in compat.action_fcurves(action)}


@bpy.app.handlers.persistent
def remember_all_keys(*_args):
    """Note every Action's key frames (new keys are told apart from these)."""
    _frames.clear()
    try:
        actions = list(bpy.data.actions)
        _insert["op"] = _last_op_pointer()
    except AttributeError:          # restricted data while Blender starts
        return
    for action in actions:
        _frames[action.name] = _curve_frames(action)


def _last_op_pointer():
    ops = bpy.context.window_manager.operators
    return ops[-1].as_pointer() if len(ops) else 0


def blender_new_keys(action):
    """(curve, key) pairs of ``action`` that are not in its remembered frames."""
    from .. import compat
    seen = _frames.get(action.name, {})
    out = []
    for fc in compat.action_fcurves(action):
        old = seen.get(f"{fc.data_path}|{fc.array_index}", frozenset())
        out.extend((fc, kp) for kp in fc.keyframe_points if round(kp.co.x, 3) not in old)
    return out


def tangent_blender_keys(action):
    """Default In / Out Tangent on the keys a Blender insert just added to ``action``; returns how many."""
    from . import maya_tangents
    n = 0
    curves = []
    for fc, kp in blender_new_keys(action):
        if apply_default(fc, kp):
            n += 1
            if fc not in curves:
                curves.append(fc)
    for fc in curves:
        maya_tangents.apply(fc)
    return n


@bpy.app.handlers.persistent
def _keys_depsgraph(scene, depsgraph):
    try:
        if not depsgraph.id_type_updated('ACTION'):
            return
        ops = bpy.context.window_manager.operators
        op = ops[-1] if len(ops) else None
        fresh = op is not None and op.as_pointer() != _insert["op"] and op.bl_idname in BLENDER_KEY_OPS
        if op is not None and fresh:
            _insert["op"] = op.as_pointer()
        for update in update_summary.updates(depsgraph, _keys_depsgraph):
            idd = update.id
            if not isinstance(idd, bpy.types.Action):
                continue
            action = idd.original
            if fresh and action.library is None and action.override_library is None:
                update_summary.wrote()
                tangent_blender_keys(action)
            _frames[action.name] = _curve_frames(action)
    except Exception as exc:        # a handler must never raise
        print("allset graph_key_menu:", exc)


_KEY_HANDLERS = (("depsgraph_update_post", _keys_depsgraph), ("load_post", remember_all_keys),
                 ("undo_post", remember_all_keys), ("redo_post", remember_all_keys))


# --- operators ----------------------------------------------------------------------------------------------

@undo_steps.no_redo_panel
class ALLSET_OT_mute_key(bpy.types.Operator):
    """Mute the selected keys: the curve holds the key's value until the next unmuted key (Maya Keys > Mute Key;
    Blender has no per-key mute: a Stepped modifier named "Maya mute" holds the value)"""
    bl_idname = "allset.mute_key"
    bl_label = "Mute Key"
    bl_options = {'REGISTER', 'UNDO'}

    mute: BoolProperty(name="Mute", default=True, options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        if props.mute:
            return cls.__doc__
        return "Unmute the selected keys: the curve plays through them again (Maya Keys > Unmute Key)"

    def execute(self, context):
        if not in_key_editor(context):
            self.report({'WARNING'}, "Mute Key works on the keys selected in the Graph Editor or Dope Sheet")
            return {'CANCELLED'}
        n = mute_selected(context, self.mute)
        if not n:
            # Maya's Mute / Unmute Key error texts
            self.report({'WARNING'}, "No keys selected to mute" if self.mute else "No muted keys selected to unmute")
            return {'CANCELLED'}
        _redraw(context)
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_graph_inbetween(bpy.types.Operator):
    """Add or remove an inbetween: the keys after the current time on the curves shown move one frame later or
    earlier (Maya Keys > Add / Remove Inbetween)"""
    bl_idname = "allset.graph_inbetween"
    bl_label = "Add Inbetween"
    bl_options = {'REGISTER', 'UNDO'}

    delta: EnumProperty(items=(("ADD", "Add Inbetween", ""), ("REMOVE", "Remove Inbetween", "")),
                        name="Inbetween", options={'SKIP_SAVE'})

    def execute(self, context):
        if not in_key_editor(context):
            return bpy.ops.allset.key_edit(action="ADD_INBETWEEN" if self.delta == "ADD" else "REMOVE_INBETWEEN")
        if not inbetween(context, 1.0 if self.delta == "ADD" else -1.0):
            self.report({'WARNING'}, "No keys after the current time")
        _redraw(context)
        return {'FINISHED'}


# --- Keys > Remove Key ----------------------------------------------------------------------------------------

REMOVE_MODES = (
    ("UNSNAPPED", "Unsnapped", "Delete the keys that are not on whole frames (Maya Keys > Remove Key > Unsnapped)"),
    ("BEFORE", "Before Current Frame", "Delete the keys before the current frame (Maya Keys > Remove Key > Before "
     "Current Frame)"),
    ("AFTER", "After Current Frame", "Delete the keys after the current frame (Maya Keys > Remove Key > After "
     "Current Frame)"),
    ("OUTSIDE", "Outside Selected Range", "Delete the keys outside the selected keys' time range; a curve without a "
     "key at an end of the range gets one there, so its shape inside stays (Maya Keys > Remove Key > Outside Selected "
     "Range)"),
    ("RIPPLE", "Ripple Delete", "Delete the keys inside the selected keys' time range and move the later keys back "
     "to close the gap (Maya Keys > Remove Key > Ripple Delete)"),
)


class ALLSET_OT_remove_keys(bpy.types.Operator):
    """Delete keys by time: unsnapped, before / after the current frame, outside the selected keys' range, or a ripple
    delete of that range (Maya Keys > Remove Key)"""
    bl_idname = "allset.remove_keys"
    bl_label = "Remove Key"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(items=REMOVE_MODES, name="Remove", options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return next(d for k, _l, d in REMOVE_MODES if k == props.mode)

    @classmethod
    def poll(cls, context):
        return in_key_editor(context)

    def execute(self, context):
        n = remove_keys(context, self.mode)
        if n is None:
            self.report({'WARNING'}, "Could not apply the command. No range has been selected")
            return {'CANCELLED'}
        _redraw(context)
        return {'FINISHED'}


TIME_RANGES = (
    ('SELECTED', "All", "The selected keys (every key of the shown curves when none is selected)"),
    ('TIME_SLIDER', "Playback", "Only those of them inside the Time Slider's playback range"),
    ('START_END', "Custom", "Only those of them between the Start and End times"),
)


class ALLSET_OT_clamp_curves(bpy.types.Operator):
    """Clamp the selected keys' values (all keys of the shown curves when none is selected) to a limit, like Maya's
    Curves > Clamp Curves"""
    bl_idname = "allset.clamp_curves"
    bl_label = "Clamp Curves"
    bl_options = {'REGISTER', 'UNDO'}

    limit: FloatProperty(name="Limit Value", default=0.0, description="The value the keys are clamped to")
    side: EnumProperty(name="Clamp", default='ABOVE', items=(
        ('ABOVE', "Upper Limit", "Keys greater than the limit get the limit"),
        ('BELOW', "Lower Limit", "Keys smaller than the limit get the limit")))
    time_range: EnumProperty(name="Time Range", items=TIME_RANGES, default='SELECTED')
    start: FloatProperty(name="Start Time", default=0.0)
    end: FloatProperty(name="End Time", default=10.0)

    @classmethod
    def poll(cls, context):
        return in_key_editor(context)

    def execute(self, context):
        clamp_keys(context, self.limit, self.side, self.time_range, self.start, self.end)
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_offset_curves(bpy.types.Operator):
    """Move the selected keys (all keys of the shown curves when none is selected) in time, like Maya's
    Curves > Offset Curves"""
    bl_idname = "allset.offset_curves"
    bl_label = "Offset Curves"
    bl_options = {'REGISTER', 'UNDO'}

    frames: FloatProperty(name="Offset Frames", default=1.0, description="Frames to move the keys by, or the frame "
                          "the first key moves to")
    mode: EnumProperty(name="Offset", default='RELATIVE', items=(
        ('RELATIVE', "Offset by", "Move the keys by the offset"),
        ('START', "Offset to", "Move the keys so the first one is on the offset frame")))
    time_range: EnumProperty(name="Time Range", items=TIME_RANGES, default='SELECTED')
    start: FloatProperty(name="Start Time", default=0.0)
    end: FloatProperty(name="End Time", default=10.0)

    @classmethod
    def poll(cls, context):
        return in_key_editor(context)

    def execute(self, context):
        offset_keys(context, self.frames, self.mode, self.time_range, self.start, self.end)
        _redraw(context)
        return {'FINISHED'}


SELECT_PRESETS = (("ALL", "All", "Curves, keys and tangents can be picked (Maya Select > All)"),
                  ("ONLY_CURVE", "Only Curve", "Only curves can be picked (Maya Select > Only Curve)"))


class ALLSET_OT_graph_select_type(bpy.types.Operator):
    """Choose what a click or drag picks in the Graph Editor (Maya Select > All / Only Curve)"""
    bl_idname = "allset.graph_select_type"
    bl_label = "Select Type"
    bl_options = {'REGISTER'}

    preset: EnumProperty(items=SELECT_PRESETS, name="Preset", options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return next(d for k, _l, d in SELECT_PRESETS if k == props.preset)

    def execute(self, context):
        p = _prefs()
        if p is None:
            return {'CANCELLED'}
        only = self.preset == "ONLY_CURVE"
        p.graph_select_curve = True
        p.graph_select_key = p.graph_select_in = p.graph_select_out = not only
        remember_masks(context.scene)
        return {'FINISHED'}


# --- Dope Sheet Curves items that are Graph Editor commands -----------------------------------------
# Maya's Dope Sheet Curves menu runs the Graph Editor's curve commands (Euler Filter, Smooth Filter, Resample, Isolate;
# same annotations) on the curves of the selected keys. Blender's
# graph.* operators only run in a Graph Editor, so the Dope Sheet area turns into one for the call and back.

DOPE_GRAPH_OPS = {"EULER": ("graph.euler_filter", {}), "BUTTERWORTH": ("graph.butterworth_smooth", {}),
                  "GAUSSIAN": ("graph.gaussian_smooth", {}), "RESAMPLE": ("graph.bake_keys", {}),
                  "ISOLATE": ("graph.hide", {"unselected": True})}


def curves_with_selected_keys(fcurves):
    return [fc for fc in fcurves if any(k.select_control_point for k in fc.keyframe_points)]


class ALLSET_OT_dope_graph_op(bpy.types.Operator):
    """Run this Graph Editor curve command on the curves of the selected keys (Maya Dope Sheet > Curves)"""
    bl_idname = "allset.dope_graph_op"
    bl_label = "Curve Command"
    bl_options = {'REGISTER', 'UNDO'}

    command: EnumProperty(items=[(k, k.title(), "") for k in DOPE_GRAPH_OPS], options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        area = context.area
        return area is not None and area.type in {'DOPESHEET_EDITOR', 'GRAPH_EDITOR'}

    def execute(self, context):
        idname, props = DOPE_GRAPH_OPS[self.command]
        mod, name = idname.split(".")
        op = getattr(getattr(bpy.ops, mod), name)
        area = context.area
        if area.type == 'GRAPH_EDITOR':
            return op('EXEC_DEFAULT', **props)
        fcurves = list(getattr(context, "editable_fcurves", None) or getattr(context, "visible_fcurves", None) or ())
        picked = curves_with_selected_keys(fcurves)
        if not picked:
            self.report({'WARNING'}, "Select keys of the curves to filter.")
            return {'CANCELLED'}
        saved = {fc: fc.select for fc in fcurves}
        for fc in fcurves:
            fc.select = fc in picked              # the Graph Editor commands act on the selected curves
        old = area.ui_type
        try:
            area.ui_type = 'FCURVES'
            region = next(r for r in area.regions if r.type == 'WINDOW')
            with context.temp_override(area=area, region=region, space_data=area.spaces.active):
                res = op('EXEC_DEFAULT', **props)
        except (RuntimeError, StopIteration) as ex:
            self.report({'WARNING'}, str(ex).strip() or "The curve command did not run")
            res = {'CANCELLED'}
        finally:
            area.ui_type = old
            for fc, sel in saved.items():
                try:
                    fc.select = sel
                except ReferenceError:      # Resample can replace curves
                    pass
        return res


classes = (ALLSET_OT_mute_key, ALLSET_OT_graph_inbetween, ALLSET_OT_remove_keys, ALLSET_OT_clamp_curves,
           ALLSET_OT_offset_curves, ALLSET_OT_graph_select_type, ALLSET_OT_dope_graph_op)


def register_bindings():
    bpy.app.handlers.load_post.append(_mask_reset)
    remember_all_keys()
    for name, fn in _KEY_HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn not in handlers:
            handlers.append(fn)
    if not bpy.app.timers.is_registered(_mask_tick):
        bpy.app.timers.register(_mask_tick, first_interval=MASK_POLL, persistent=True)


def unregister_bindings():
    if bpy.app.timers.is_registered(_mask_tick):
        bpy.app.timers.unregister(_mask_tick)
    if _mask_reset in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_mask_reset)
    for name, fn in _KEY_HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn in handlers:
            handlers.remove(fn)
    _frames.clear()
    _mask["last"] = None
