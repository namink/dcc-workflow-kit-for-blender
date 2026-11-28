# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya keys: S = Set Key on every keyable channel, Set Breakdown Key, and the Time Slider key edits
(Cut / Copy / Paste / Delete / Snap / Keys / Tangents / Set Range to).

Maya keys (S keys every keyable attribute); Maya
Time Slider menu (the time slider edits act on the Time Slider's highlighted range: the
Shift-dragged range, else the current frame).

Nodes are the Channel Box's (``ui/cb_nodes.targets``): selected objects, or the selected pose bones
in pose mode (a bone's curves are the armature action's ``pose.bones["n"]...`` curves).

Code: key_nodes (nodes, their curves, the Time Slider range), key_scope (Key menu commands with options, the
animation clipboard); this module keeps the tangent table, Set Key, the Time Slider key edits, the operators and
re-exports the other modules' names.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty

from .. import results
from .. import undo_steps
from .. import i18n
from .key_nodes import (_cb, _in, keys_in, _move, node_fcurves, nodes, prefix, slider_fcurves,  # noqa: F401
                        time_range, without_deformer_curves)
from .key_scope import (_CLIPBOARD, copy_scope, CurveRef, delete_scope, EPS, KeyScope, _offset_value,  # noqa: F401
                        PASTE_METHODS, paste_scope, scale_scope, scope_curves, scope_nodes, scope_range, _snap,
                        snap_scope, value_unit)

# Maya tangent -> (interpolation, handle type or None); FLAT also levels the handles.
# (reused by the Graph Editor tangent buttons)
TANGENTS = {
    "SPLINE": ("BEZIER", 'AUTO'),
    # Linear: a Vector handle side points at the neighbouring key; a segment is straight when both of its keys are
    # linear on the sides facing it (operators/maya_tangents.py)
    "LINEAR": ("BEZIER", 'VECTOR'),
    "CLAMPED": ("BEZIER", 'AUTO_CLAMPED'),
    "STEPPED": ("CONSTANT", None),
    "FLAT": ("BEZIER", 'ALIGNED'),
    "PLATEAU": ("BEZIER", 'AUTO_CLAMPED'),
    "AUTO": ("BEZIER", 'AUTO_CLAMPED'),
    # Fixed keeps the handles where they are; Blender has no
    # Stepped Next: Stepped. BREAK / UNIFY only change the handle type (free / aligned).
    "FIXED": ("BEZIER", 'ALIGNED'),
    "STEPPED_NEXT": ("CONSTANT", None),
    "BREAK": (None, 'FREE'),
    "UNIFY": (None, 'ALIGNED'),
}
# Maya names for the menus / buttons
TANGENT_LABELS = {"AUTO": "Auto", "SPLINE": "Spline", "CLAMPED": "Clamped", "LINEAR": "Linear", "FLAT": "Flat",
                  "STEPPED": "Stepped", "STEPPED_NEXT": "Stepped Next", "PLATEAU": "Plateau", "FIXED": "Fixed",
                  "BREAK": "Break Tangents", "UNIFY": "Unify Tangents"}


def apply_tangent(kp, kind, fc=None):
    """One key's Maya tangent (in and out); with the key's curve ``fc`` the Maya type is remembered for
    operators/maya_tangents.py (Clamped / Plateau / Flat share Blender handle types with others)."""
    interp, handle = TANGENTS[kind]
    if interp is not None:
        kp.interpolation = interp
    if handle is not None:
        kp.handle_left_type = kp.handle_right_type = handle
    if kind == "FLAT":
        kp.handle_left.y = kp.handle_right.y = kp.co.y
    if fc is not None:
        from . import maya_tangents
        maya_tangents.mark(fc, kp, kind)


def _maya_auto(fc):
    """Maya tangent shapes after the curve changed (operators/maya_tangents.py)."""
    from . import maya_tangents
    maya_tangents.apply(fc)


TANGENT_ITEMS = [(k, TANGENT_LABELS.get(k, k.title()), "") for k in TANGENTS]


# --- Set Key ----------------------------------------------------------------------------------

def keyable_channels(node):
    """Maya keyable attributes of a node: the Channel Box's shown channels that are keyable."""
    cb = _cb()
    return [k for k in cb._visible_channels(node) if cb.is_keyable(node, k)]


# Maya SetKeyTranslate / SetKeyRotate / SetKeyScale (Shift+W / E / R):
# setKeyframe on the translate / rotate / scale attributes of the selection only. Channel Box keys.
CHANNEL_SETS = {"TRANSLATE": ("tx", "ty", "tz"), "ROTATE": ("rx", "ry", "rz"), "SCALE": ("sx", "sy", "sz")}


def set_key(context, breakdown=False, channels=""):
    """S: key every keyable channel of every node (or the active keying set); ``channels`` = one of CHANNEL_SETS
    (Shift+W / E / R) keys only those. Count of channels keyed."""
    scene = context.scene
    keytype = 'BREAKDOWN' if breakdown else 'KEYFRAME'
    if not channels and not breakdown and scene.keying_sets.active is not None:
        # Maya: with a current character set, S keys that character's attributes (and its subcharacters'),
        # whatever is selected (rule 3)
        from . import character_sets
        return character_sets.key_current(context, keytype)
    from . import point_keys
    if point_keys.applies(context):
        if channels:
            # Maya component mode: points have no translate / rotate / scale, so Shift+W / E / R key nothing
            return 0
        # Maya component mode: S keys the selected points' X / Y / Z (edges / faces: their vertices)
        return point_keys.key_points(context, keytype)
    only = CHANNEL_SETS.get(channels)
    from ..ui import cb_channels
    cb = _cb()
    # the target weights of the constraint nodes and the attributes of the deformer nodes open in the Channel Box
    # (#329, #339): keyed with the channels below, on every node that has the same constraint / deformer (like a typed
    # value)
    opened = cb.shown_weight_keys(context) + cb.shown_deformer_keys(context) if only is None else []
    count = 0
    for node in nodes(context):
        # Channel Box Sync Selection in Graph Editor on: S keys the selected channels (as in Maya)
        synced = None if only is not None else cb_channels.synced_keys(context, node)
        if synced is not None:
            keys = synced
        else:
            keys = keyable_channels(node) + [k for k in opened if cb.has_channel(node, k)
                                             and not cb.is_hidden(node, k) and cb.driver(node, k) is None]
        for key in keys:
            if (only is None or key in only) and cb.is_keyable(node, key):
                count += bool(cb.keyframe(node, key, keytype))
    return count


# --- Time Slider edits ------------------------------------------------------------------------

def delete_keys(context, a, b):
    n = 0
    for node in nodes(context):
        fcs = _cb()._fcurves(node)
        for fc, pts in keys_in(node, a, b):
            for kp in sorted(pts, key=lambda p: -p.co.x):
                fc.keyframe_points.remove(kp, fast=True)
                n += 1
            if len(fc.keyframe_points) == 0 and fcs is not None:
                fcs.remove(fc)
            else:
                fc.update()
                _maya_auto(fc)
    return n


def copy_keys(context, a, b):
    """Time Slider copy: the nodes' keys in a..b onto the animation clipboard (see ``copy_scope``)."""
    # Time Slider frames are whole: a key within half a frame of the range counts (like ``_in``)
    return copy_scope(context, KeyScope(time_range="Start/End", start=a, end=b, slider=True), pad=0.5 - EPS)


def paste_keys(context, frame):
    """Time Slider paste at ``frame`` (Merge by default, like Maya): one copied node goes to every node, several in order."""
    return paste_scope(context, frame=frame)


def _find_curve(node, path, index):
    fcs = _cb()._fcurves(node)
    return fcs.find(path, index=index) if fcs is not None else None


def snap_keys(context, a, b):
    n = 0
    for node in nodes(context):
        for fc, pts in keys_in(node, a, b):
            for kp in pts:
                dx = round(kp.co.x) - kp.co.x
                if dx:
                    _move(kp, dx)
                    n += 1
            fc.update()
    return n


def set_key_type(context, a, b, ktype):
    n = 0
    for node in nodes(context):
        for _fc, pts in keys_in(node, a, b):
            for kp in pts:
                kp.type = ktype
                n += 1
    return n


def inbetween(context, frame, delta):
    """Add (+1) / Remove (-1) an inbetween at ``frame``: the keys after it move by ``delta``
    (Remove only where the next key is more than one frame away, so keys never collide)."""
    n = 0
    for node in nodes(context):
        for fc in slider_fcurves(node):
            later = [kp for kp in fc.keyframe_points if kp.co.x > frame + 0.5]
            if not later:
                continue
            if delta < 0 and min(kp.co.x for kp in later) < frame + 1.5:
                continue
            for kp in later:
                _move(kp, delta)
                n += 1
            fc.update()
    return n


def set_tangent(context, a, b, kind):
    n = 0
    for node in nodes(context):
        for fc, pts in keys_in(node, a, b):
            for kp in pts:
                apply_tangent(kp, kind, fc)
                n += 1
            fc.update()
            _maya_auto(fc)
    return n


def key_span(context):
    """(first, last) key frame of the nodes' Time Slider curves, or None."""
    frames = [kp.co.x for node in nodes(context) for fc in slider_fcurves(node) for kp in fc.keyframe_points]
    return (int(round(min(frames))), int(round(max(frames)))) if frames else None


# --- operators ----------------------------------------------------------------------------------

def _redraw(context):
    for area in context.screen.areas if context.screen else ():
        area.tag_redraw()


def global_key_applies(context, channels="ALL"):
    """Shift+W / E / R from any editor key the object / pose selection; edit, paint and sculpt modes keep their
    own keys for them. S from any editor also keys the selected points in component mode, like S over the
    viewport."""
    if context.mode in {'OBJECT', 'POSE'}:
        return True
    from . import point_keys
    return channels == 'ALL' and point_keys.applies(context)


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_set_key(bpy.types.Operator):
    """Set a key on every keyable channel of the selection (Maya S); the active keying set if there is one"""
    bl_idname = "allset.set_key"
    bl_label = "Set Key"
    bl_options = {'REGISTER', 'UNDO'}

    breakdown: BoolProperty(name="Breakdown", description="Set a breakdown key (Maya Set Breakdown Key)",
                            options={'SKIP_SAVE'})
    channels: EnumProperty(name="Channels", items=(("ALL", "All Keyable", "Every keyable channel"),
                                                   ("TRANSLATE", "Translate", "Translate X / Y / Z (Maya Shift+W)"),
                                                   ("ROTATE", "Rotate", "Rotate X / Y / Z (Maya Shift+E)"),
                                                   ("SCALE", "Scale", "Scale X / Y / Z (Maya Shift+R)")),
                           default="ALL", options={'SKIP_SAVE'})   # not "": Blender reads it as a separator (QA B)
    global_key: BoolProperty(name="Global Key",
                             description="Run from a global hotkey: only in object / pose mode (S also in component "
                                         "mode)",
                             options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.scene.keying_sets.active is not None or _cb().lead(context) is not None

    def invoke(self, context, _event):
        if self.global_key and not global_key_applies(context, self.channels):
            return {'PASS_THROUGH'}
        return self.execute(context)

    def execute(self, context):
        n = set_key(context, self.breakdown, "" if self.channels == 'ALL' else self.channels)
        if n == 0:
            from . import point_keys
            if not (self.channels != 'ALL' and point_keys.applies(context)):     # Maya: silent on points
                self.report({'WARNING'}, "Nothing keyable selected")
            return {'CANCELLED'}
        # Maya prints nothing for a key (#100: Blender's "Successfully added ... keying set" text is gone too)
        _redraw(context)
        return {'FINISHED'}


ACTIONS = (("CUT", "Cut", "Remove keys and place on the animation clipboard"),
           ("COPY", "Copy", "Copy keys and place on the animation clipboard"),
           ("PASTE", "Paste", "Paste keys from the animation clipboard at the current time"),
           ("DELETE", "Delete", "Delete keys but do not place on the animation clipboard"),
           ("SNAP", "Snap", "Snap keys to whole frames"),
           ("TO_KEY", "Convert to Key", "Change existing breakdowns into keys"),
           ("TO_BREAKDOWN", "Convert to Breakdown", "Change existing keys into breakdowns"),
           ("ADD_INBETWEEN", "Add Inbetween", "Move every key after the current time one frame later"),
           ("REMOVE_INBETWEEN", "Remove Inbetween", "Move every key after the current time one frame earlier"),
           ("TANGENT", "Tangent", "Set in and out tangents"))


class ALLSET_OT_time_keys(bpy.types.Operator):
    """Edit the selection's keys in the Time Slider range (Shift-drag), else at the current frame (Maya Time Slider menu)"""
    bl_idname = "allset.time_keys"
    bl_label = "Time Slider Keys"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(name="Action", items=ACTIONS, options={'SKIP_SAVE'})
    tangent: EnumProperty(name="Tangent", items=TANGENT_ITEMS, options={'SKIP_SAVE'})
    # the Key / Edit > Keys menu items run with the default option values, like Maya (Time range All);
    # the Time Slider menu acts on its range / the current frame
    time_range: EnumProperty(name="Time Range", options={'SKIP_SAVE'}, items=(
        ('SLIDER', "Time Slider", "The Shift-dragged Time Slider range, else the current frame"),
        ('ALL', "All", "Every key of the selection (Maya Key menu, default Time range All)")))

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return next(d for k, _l, d in ACTIONS if k == props.action)

    @classmethod
    def poll(cls, context):
        return _cb().lead(context) is not None

    def execute(self, context):
        a, b = time_range(context)
        frame = context.scene.frame_current
        act = self.action
        if self.time_range == 'ALL' and act in ("COPY", "CUT", "DELETE", "SNAP"):
            scope = KeyScope()
            if act == "COPY":
                n = copy_scope(context, scope)
            elif act == "SNAP":
                n = snap_scope(context, scope)
            else:
                n = delete_scope(context, scope, clipboard=act == "CUT")
            results.result(self, f"{dict((k, l) for k, l, _d in ACTIONS)[act]}: {n} key(s)")
            _redraw(context)
            return {'FINISHED'}
        if act == "COPY":
            n = copy_keys(context, a, b)
        elif act == "CUT":
            n = copy_keys(context, a, b)
            delete_keys(context, a, b)
        elif act == "PASTE":
            n = paste_keys(context, frame)
        elif act == "DELETE":
            n = delete_keys(context, a, b)
        elif act == "SNAP":
            n = snap_keys(context, a, b)
        elif act in ("TO_KEY", "TO_BREAKDOWN"):
            n = set_key_type(context, a, b, 'KEYFRAME' if act == "TO_KEY" else 'BREAKDOWN')
        elif act in ("ADD_INBETWEEN", "REMOVE_INBETWEEN"):
            n = inbetween(context, frame, 1 if act == "ADD_INBETWEEN" else -1)
        else:
            n = set_tangent(context, a, b, self.tangent)
        results.result(self, f"{dict((k, l) for k, l, _d in ACTIONS)[act]}: {n} key(s)")
        _redraw(context)
        return {'FINISHED'}


def sound_span(scene):
    """(start, end) of the Time Slider sound: from the sound's offset to the whole frame its end falls in, like Maya.
    Blender has no "displayed" sound: the active sound strip, else the first one."""
    from .. import compat
    if scene.sequence_editor is None:
        return None
    sounds = sorted((s for s in compat.strips(scene.sequence_editor) if s.type == 'SOUND'),
                    key=lambda s: s.frame_final_start)
    if not sounds:
        return None
    act = scene.sequence_editor.active_strip
    s = act if act in sounds else sounds[0]
    return int(s.frame_final_start), int(s.frame_final_end)


class ALLSET_OT_time_set_range(bpy.types.Operator):
    """Set the playback range (Maya Time Slider > Set Range to)"""
    bl_idname = "allset.time_set_range"
    bl_label = "Set Range to"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(items=(("START_END", "Start/End", "Playback range = animation range"),
                              ("MIN_MAX", "Min/Max", "Playback range = first and last keys of the selection"),
                              ("SELECTED", "Selected", "Playback range = the Shift-dragged Time Slider range"),
                              ("SOUND", "Sound Length", "Playback range = the sound's start to its end")),
                       options={'SKIP_SAVE'})

    def execute(self, context):
        scene, wm = context.scene, context.window_manager
        if self.mode == "START_END":
            a, b = scene.frame_start, scene.frame_end
        elif self.mode == "MIN_MAX":
            span = key_span(context)
            if span is None:
                self.report({'WARNING'}, "No keys found. Cannot determine min/max of animation range.")
                return {'CANCELLED'}
            a, b = span
        elif self.mode == "SOUND":
            span = sound_span(scene)
            if span is None:
                self.report({'ERROR'}, "No sound to take the range from: import a sound first (Audio > Import "
                                       "Audio...)")
                return {'CANCELLED'}
            a, b = span
        else:
            if not getattr(wm, "allset_time_range_on", False):
                self.report({'WARNING'}, "No range selected. Use Shift-LMB to select a range.")
                return {'CANCELLED'}
            a, b = time_range(context)
        scene.use_preview_range = True
        a, b = int(a), int(max(a, b))
        if a > scene.frame_preview_end:   # the setters keep start <= end: move the far side first
            scene.frame_preview_end, scene.frame_preview_start = b, a
        else:
            scene.frame_preview_start, scene.frame_preview_end = a, b
        return {'FINISHED'}


def jump_frame(frames, current, forward):
    """Maya Next / Previous Key: the first key frame after (before) ``current``; past the last (first) key it goes
    round to the first (last). None without keys."""
    whole = sorted({int(round(f)) for f in frames})
    if not whole:
        return None
    if forward:
        later = [f for f in whole if f > current]
        return later[0] if later else whole[0]
    earlier = [f for f in whole if f < current]
    return earlier[-1] if earlier else whole[-1]


class ALLSET_OT_key_jump(bpy.types.Operator):
    """Go to the next / previous key the Time Slider shows (Maya . / ,)"""
    bl_idname = "allset.key_jump"
    bl_label = "Jump to Key"
    bl_options = {'UNDO_GROUPED'}
    bl_undo_group = "Frame Change"

    next: BoolProperty(name="Next", default=True, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        from ..ui import time_slider
        frames = [f for f, _bd in time_slider.key_frames(time_slider.tick_nodes(context))]
        frame = jump_frame(frames, context.scene.frame_current, self.next)
        if frame is None:
            return {'CANCELLED'}
        context.scene.frame_current = frame
        return {'FINISHED'}


classes = (ALLSET_OT_set_key, ALLSET_OT_time_keys, ALLSET_OT_time_set_range, ALLSET_OT_key_jump)
