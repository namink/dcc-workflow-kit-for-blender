# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Time Slider + Range Slider in the Timeline header, and a timeline view that
follows the playback range.

Maya's Time Slider (transport buttons, current time
field, auto key) and Range Slider (animation start, playback start, [range], playback end,
animation end). Blender form:
- the timeline header's ``draw_header`` (``DOPESHEET_HT_editor_buttons`` in Timeline mode, a plain class, not in
  bpy.types) is wrapped to draw ``draw_header`` below and restored on unregister (``kit_wraps``: a wrapper another
  add-on put over the kit's stays, the kit's then only calls what it wrapped).
- Maya's animation range = scene frame_start/end; its playback range = the preview range
  (``use_preview_range`` off: playback = animation range, inner fields greyed).
- Maya's time slider always shows exactly the playback range and never zooms or scrolls: every Timeline is
  framed to the range's frame cells (``fit_timelines``, ``view2d.zoom_border``; a msgbus subscription on the
  range and a load_post handler defer it to a timer), the WINDOW draw handler re-fits a view that drifted
  (a resize, Blender's own view operators) and the wheel / Ctrl+MMB zoom are swallowed in the Timeline
  (``allset.time_view_lock``). The Range Slider is the one control of what the Time Slider shows.
- LMB on the timeline = time (Shift = red range), RMB = Maya's
  Time Slider menu, MMB = move the time without updating the scene (Maya's MMB drag).
- The
  header is the Range Slider row in Maya's order; Blender's Playback / Keying / View / Marker menus move
  into the animation preferences menu at its right end (``DOPESHEET_MT_editor_menus.draw_collapsible`` is
  overridden on the class for Timeline mode, deleted on unregister). A timeline with its sidebar shown (the Maya Workflow Kit
  layout) draws the current frame field and the 8 transport buttons there, at the right end of the
  Time Slider row like Maya (``ALLSET_PT_time_slider``); other timelines keep them in the header.

Code: ``time_slider_header`` (header rows, sidebar panel), ``time_slider_mouse`` (mouse operators),
``time_slider_menu`` (RMB menu), ``time_slider_ruler`` (ruler drawing), ``time_slider_view`` (view kept on the
playback range). This module keeps the key ticks, the Timeline draw handler, undo frame keeping and register /
unregister; their names used elsewhere are importable from here too (tests replace key-tick functions here).
"""

import re

import bpy

from .. import compat
from . import draw_replay, kit_wraps
from .draw_replay import call
from bpy.app.handlers import persistent
# the split-out parts, also read through this module by other UI and the tests
from .time_slider_view import (_OWNER, _check_view, _deferred_fit, _fitted, _is_timeline, _schedule,  # noqa: F401
                               _subscribe, timeline_areas, ALLSET_OT_time_view_lock, fit_timelines, playback_range,
                               view_drifted, view_target, visible_range)
from .time_slider_header import (ALLSET_MT_anim_preferences, ALLSET_PT_time_slider, RANGE_ITEMS,  # noqa: F401
                                 ROW_CORE_UNITS, ROW_OPTIONAL, draw_header, draw_range_slider, has_slider_panel,
                                 row_plan)
from .time_slider_mouse import (ALLSET_OT_time_scrub, ALLSET_OT_time_range_all, ALLSET_OT_time_range_drag,  # noqa: F401
                                RANGE_EDGE_PX, range_rect, set_range)
from .time_slider_menu import (ALLSET_MT_time_slider, ALLSET_MT_time_slider_looping,  # noqa: F401
                               ALLSET_MT_time_slider_tangents, ALLSET_OT_time_slider_delete,
                               ALLSET_OT_time_slider_menu, ALLSET_OT_time_slider_unavailable, TIME_SLIDER_MENUS)
from . import time_slider_bookmarks
from .time_slider_ruler import (MAYA_RULER_H, ROWS, ROWS_BOOKMARKS, RULER_BG, RULER_CURRENT,  # noqa: F401
                                RULER_FONT_SIZE, RULER_LABEL, STEP_DEVIATIONS, STEP_MATCHES, TICK_HALF_PAD, _TRIS,
                                _draw_blue_pencil, _draw_ruler, _rows, _themed, _tris_batch, blue_pencil_marks,
                                label_digits, ruler_ticks, tick_step)


# Blender 5.x: the Timeline is a Dope Sheet mode; compat names the header classes.
header_classes = compat.timeline_header_classes


_ORIGINAL = {}


# Maya's Time Slider has no Adjust Last Operation panel. Blender opens its HUD over a timeline once an operator
# with a redo panel ran there (its own double-click toggled the channel editability, #335); the flag that keeps
# the panel closed lives on the HUD region, which exists only after the panel was shown, so the draw handler asks
# a timer to close it when it sees one.
def hide_redo_panels():
    wm = bpy.context.window_manager
    for win, area, region in list(timeline_areas(wm)):
        space = area.spaces.active
        if space.show_region_hud and any(r.type == 'HUD' for r in area.regions):
            # the flag's update fades the region out and re-initialises the area for the context's window: from a
            # timer (no window in the context) the fade started window-less and Blender crashed when it ended
            with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
                space.show_region_hud = False
    return None


def _redo_panel_shown(context):
    area = context.area
    return (area is not None and getattr(context.space_data, "show_region_hud", False)
            and any(r.type == 'HUD' for r in area.regions))


# --- the red range highlight -----------------------------------------------------------------------

RANGE_COLOR = (0.78, 0.16, 0.16, 0.35)   # red range highlight
RANGE_ARROW_COLOR = (1.0, 1.0, 1.0, 0.9)
_draw_handle = []


def _draw_range():
    context = bpy.context
    wm = context.window_manager
    if not _is_timeline(context):
        return
    if _redo_panel_shown(context) and not bpy.app.timers.is_registered(hide_redo_panels):
        bpy.app.timers.register(hide_redo_panels, first_interval=0.0)
    region = context.region
    _check_view(context, region)
    key = ("time slider", region.as_pointer())
    sig = (region.width, region.height, context.preferences.system.ui_scale)
    moving = draw_replay.again(key, sig)     # a window moves: the Time Slider as drawn last
    if not moving:
        with draw_replay.recording(key, sig):
            _draw_slider(context, region, wm)
    if has_slider_panel(context.space_data):
        if moving:
            # the mouse holds a window's frame, off the Time Slider: the bookmark name goes, like Maya
            time_slider_bookmarks.forget(context.area)
        else:
            time_slider_bookmarks.draw_tip(context, region)    # follows the mouse: drawn anew every time


def _draw_slider(context, region, wm):
    maya = has_slider_panel(context.space_data)
    if maya:
        _draw_ruler(context, region)
    _draw_keys(context, region, maya)
    if maya:
        _draw_blue_pencil(context, region)
    if not getattr(wm, "allset_time_range_on", False):
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    x0, x1 = range_rect(region, *wm.allset_time_range)
    h = region.height
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": ((x0, 0), (x1, 0), (x1, h), (x0, 0), (x1, h), (x0, h))})
    call(gpu.state.blend_set, 'ALPHA')
    call(shader.uniform_float, "color", RANGE_COLOR)
    call(batch.draw, shader)
    # Maya's arrows on a highlighted range: ◀ / ▶ in the end zones (scale), ◀▶ in the middle (move)
    edge = RANGE_EDGE_PX * (context.preferences.system.ui_scale or 1.0)
    k = min(edge * 0.6, h * 0.25)
    y = h * 0.5
    tris = []

    def arrow(cx, d):
        tris.extend(((cx - d * k * 0.5, y), (cx + d * k * 0.5, y + k * 0.6), (cx + d * k * 0.5, y - k * 0.6)))
    cx = (x0 + x1) * 0.5
    if x1 - x0 >= 3 * edge:
        arrow(x0 + edge * 0.5, 1)       # tip left
        arrow(x1 - edge * 0.5, -1)      # tip right
    arrow(cx - k * 0.55, 1)
    arrow(cx + k * 0.55, -1)
    batch = batch_for_shader(shader, 'TRIS', {"pos": tris})
    call(shader.uniform_float, "color", RANGE_ARROW_COLOR)
    call(batch.draw, shader)
    call(gpu.state.blend_set, 'NONE')


# --- key ticks -----------------------------------------------------------------------------
# Maya draws the keys of the selected nodes as 1 px lines over the whole Time Slider height: keys red,
# breakdowns green.
KEY_RGB = (1.0, 0.0, 0.0, 1.0)
BREAKDOWN_RGB = (0.0, 1.0, 0.0, 1.0)


_bone_curves = {}     # pose bone pointer -> (owner's F-curve count, the bone's F-curves) kept while playing / dragging
# a curve path's leading ``pose.bones["name"]`` (names are escaped: a backslash goes with the character after it)
_BONE_PREFIX = re.compile(r'pose\.bones\["(?:[^"\\]|\\.)*"\]', re.DOTALL)


def _bones_curves(bones):
    """{pose bone pointer: ``key_nodes.node_fcurves``} for ``bones``: each skeleton's curves are shared out by the same
    rule (a bone's curves start with its ``pose.bones["n"]`` path and then "." or "["), once per skeleton
    (``_skeleton_parts``, kept until the curves change), instead of looking through every curve of the skeleton once
    per bone (hundreds of selected controls took a third of a second per Time Slider redraw; one picked control of a
    rig with a thousand curves read them all again on every redraw)."""
    from ..operators import time_keys
    out, owners = {}, {}
    for pb in bones:
        ptr = pb.as_pointer()
        if ptr not in out:
            out[ptr] = []
            owners.setdefault(pb.id_data.as_pointer(), []).append((ptr, pb))
    escape = bpy.utils.escape_identifier
    for group in owners.values():
        first = group[0][1]
        fcs = time_keys._cb()._fcurves(first)
        if fcs is None:
            continue
        ob = first.id_data
        parts = _skeleton_parts(ob, fcs, _skeleton_key(ob, fcs))
        # Blender finds the n-th curve of a slot by stepping through the n curves before it: several bones take
        # their curves from one list of the skeleton's curves
        seq = list(fcs) if len(group) > 1 else fcs
        for ptr, pb in group:
            # = key_nodes.prefix(pb): a pose bone's path is its escaped name in pose.bones["..."]
            idx = parts.get(f'pose.bones["{escape(pb.name)}"]')
            if idx:
                out[ptr] = [seq[i] for i in idx]
    return out


_PARTS = {}     # (Action, slot, curve count, bone names) -> ``_skeleton_parts``; dropped with ``_KEYS``


def _skeleton_key(ob, fcs):
    """(Action, slot, number of curves, bone names) of skeleton ``ob`` whose curves are ``fcs``, None when it has
    none: what its bones' share of the curves depends on (a renamed bone renames its curves' paths)."""
    try:
        ad = ob.animation_data
        return ad.action.as_pointer(), ad.action_slot.handle, len(fcs), tuple(ob.pose.bones.keys())
    except (AttributeError, ReferenceError):
        return None


def _skeleton_parts(ob, fcs, key):
    """{``pose.bones["n"]`` path: the indices in ``fcs`` (skeleton ``ob``'s curves) of that bone's curves}. A path
    names one bone, so its leading bone path is read once per curve and looked up. Kept for the skeleton's
    ``_skeleton_key`` ``key`` until the curves' keys are dropped (an Action update, a frame change, undo, redo, a
    file load)."""
    got = _PARTS.get(key) if key is not None else None
    if got is not None:
        return got
    parts = {}
    match = _BONE_PREFIX.match
    for i, fc in enumerate(fcs):
        path = fc.data_path
        m = match(path)
        if m is None:
            continue
        n = m.end()
        if len(path) > n and path[n] in ".[":
            parts.setdefault(path[:n], []).append(i)
    if key is not None:
        if len(_PARTS) > 64:
            _PARTS.clear()
        _PARTS[key] = parts
    return parts


def _bone_fcurves(bones, keep):
    """{pose bone pointer: its F-curves}; while playback or a drag runs (``keep``) a bone's curves are kept while its
    skeleton keeps its number of curves."""
    from ..operators import time_keys
    if not keep:
        return _bones_curves(bones)
    out, missing = {}, []
    for pb in bones:
        fcs = time_keys._cb()._fcurves(pb)
        key = len(fcs) if fcs is not None else -1
        got = _bone_curves.get(pb.as_pointer())
        if got is not None and got[0] == key:
            out[pb.as_pointer()] = got[1]
        else:
            missing.append((pb, key))
    if missing:
        found = _bones_curves([pb for pb, _key in missing])
        if len(_bone_curves) + len(missing) > 256:
            _bone_curves.clear()
        for pb, key in missing:
            out[pb.as_pointer()] = found[pb.as_pointer()]
            _bone_curves[pb.as_pointer()] = (key, found[pb.as_pointer()])
    return out


_BONE_KEYS = {}     # ``_skeleton_key`` -> {bone path: ([co arrays], [type arrays]) of its curves}, dropped with _KEYS


def _bones_keys(bones, cos, kinds):
    """Adds the ``_curve_keys`` arrays of the curves of pose bones ``bones`` (the curves ``_bones_curves`` shares
    out) to ``cos`` / ``kinds``. A bone's arrays are kept by its skeleton's ``_skeleton_key`` and its path,
    and dropped with the curves' keys (an Action update, a frame change, undo, redo, a file load): a new selection
    of bones whose keys were read takes one look per bone instead of finding each bone's curves and looking up
    every curve's keys (hundreds of selected controls of a rig with a thousand curves took milliseconds on every
    selection change)."""
    from ..operators import time_keys
    owners = {}
    for pb in bones:
        owners.setdefault(pb.id_data.as_pointer(), []).append(pb)
    escape = bpy.utils.escape_identifier
    for group in owners.values():
        first = group[0]
        fcs = time_keys._cb()._fcurves(first)
        if fcs is None:
            continue
        ob = first.id_data
        key = _skeleton_key(ob, fcs)
        held = None
        if key is not None:
            held = _BONE_KEYS.get(key)
            if held is None:
                if len(_BONE_KEYS) > 64:
                    _BONE_KEYS.clear()
                held = _BONE_KEYS[key] = {}
        missing = []
        for pb in group:
            # = key_nodes.prefix(pb): a pose bone's path is its escaped name in pose.bones["..."]
            path = f'pose.bones["{escape(pb.name)}"]'
            got = held.get(path) if held is not None else None
            if got is None:
                missing.append(path)
            else:
                cos += got[0]
                kinds += got[1]
        if not missing:
            continue
        parts = _skeleton_parts(ob, fcs, key)
        # Blender finds the n-th curve of a slot by stepping through the n curves before it: several bones take
        # their curves from one list of the skeleton's curves
        seq = list(fcs) if len(missing) > 1 else fcs
        for path in missing:
            got = ([], [])
            for i in parts.get(path, ()):
                keys = _curve_keys(seq[i])
                if keys is not None:
                    got[0].append(keys[1])
                    got[1].append(keys[2])
            if held is not None:
                held[path] = got
            cos += got[0]
            kinds += got[1]


def key_frames(nodes, keep=False):
    """Sorted [(frame, is_breakdown)] of the nodes' keys; a frame with any regular key is a regular key. ``keep``:
    playback or a drag runs (the curves of a bone found once are used again). A curve's keys are read once until its
    Action changes or the frame does (``_curve_keys``); so are a bone's (``_bones_keys``)."""
    import numpy as np
    from . import cb_channels
    from ..operators import time_keys
    if not keep:
        _bone_curves.clear()
    # looked up once: bpy.types finds a type by its name on every access (bpy_rna.cc bpy_types_module_getattro)
    pose_bone, object_type = bpy.types.PoseBone, bpy.types.Object
    frames, cos, kinds = {}, [], []
    # Channel Box Sync Timeline Display: only the selected channels' keys (none selected / off: all keys)
    from . import channel_box
    if cb_channels.sync_timeline_on() and channel_box.selected_channels(bpy.context):
        plan = [(node, cb_channels.timeline_curves(bpy.context, node)) for node in nodes]
    else:
        plan = [(node, None) for node in nodes]
    pose_bones = [n for n, c in plan if c is None and isinstance(n, pose_bone)]
    if keep:
        bones = _bone_fcurves(pose_bones, keep)
    else:
        bones = None
        _bones_keys(pose_bones, cos, kinds)
    for node, curves in plan:
        if curves is None:
            if isinstance(node, pose_bone):
                if bones is None:
                    continue        # its keys are in cos already (_bones_keys)
                curves = bones[node.as_pointer()]
            elif isinstance(node, object_type) and node.animation_data is None:
                curves = []         # no curves and no animation layers of its own (thousands of selected props)
            else:
                curves = time_keys.node_fcurves(node)
                if isinstance(node, object_type):
                    # the shown layer's keys + BaseAnimation keys of channels not in that layer (Maya)
                    from ..operators import anim_layers
                    curves = list(curves) + anim_layers.hidden_base_curves(node, bpy.context.scene)
                    curves = time_keys.without_deformer_curves(node, curves)
            if isinstance(node, object_type):
                # component mode: the keys of the selected points (vertices / CVs / lattice points)
                from ..operators import point_keys
                curves += point_keys.selected_point_curves(node)
        for fc in curves:
            got = _curve_keys(fc)
            if got is not None:
                cos.append(got[1])
                kinds.append(got[2])
    if not cos:
        return []
    # the keys of all curves at once: per distinct frame, is any key there a regular one. Two sorts of the frames
    # (all of them, the regular keys' ones) cost less than one sort that also maps every key to its frame.
    every = np.concatenate(cos)[0::2]
    raw = np.unique(every)
    regular = np.zeros(len(raw), bool)
    keyed = every[np.concatenate(kinds) != _breakdown_value()]
    regular[np.searchsorted(raw, np.unique(keyed))] = True     # a frame with any regular key
    for x, reg in zip(raw.tolist(), regular.tolist()):
        f = round(x, 3)
        frames[f] = frames.get(f, True) and not reg
    return sorted(frames.items())


_KEYS = {}      # F-curve pointer -> ``_curve_keys`` until an Action changes (``_drop_held``)
_KEYS_MAX = 50000


def _curve_keys(fc):
    """(key count, every key's (frame, value) co, every key's type) of the curve, None without keys: the keys' co and
    types in one read each per curve. Kept until a key is set, moved, retyped or deleted: Blender tags the curve's
    Action for that (its evaluated copy has to follow), so the next Action update drops them (``_drop_held``), as do
    a frame change (``_drop_keys``), undo, redo and a file load. A selection change keeps them: the keys of a new
    selection's bones are read once."""
    import numpy as np
    kps = fc.keyframe_points
    n = len(kps)
    if not n:
        return None
    ptr = fc.as_pointer()
    got = _KEYS.get(ptr)
    if got is not None and got[0] == n:
        return got
    # Blender's foreach_get fills a buffer of the property's own C type in one pass (a key's frame is a float, its
    # type one byte) and any other buffer one value at a time through Python objects (bpy_rna.cc
    # foreach_compat_buffer): float32 / uint8 read the same values in about half the time.
    co = np.empty(2 * n, np.float32)
    kps.foreach_get("co", co)
    kinds = np.empty(n, np.uint8)
    kps.foreach_get("type", kinds)
    if len(_KEYS) >= _KEYS_MAX:
        _KEYS.clear()
    got = _KEYS[ptr] = (n, co, kinds)
    return got


_BREAKDOWN = []     # the RNA value of a key's type 'BREAKDOWN'


def _breakdown_value():
    if not _BREAKDOWN:
        _BREAKDOWN.append(bpy.types.Keyframe.bl_rna.properties["type"].enum_items["BREAKDOWN"].value)
    return _BREAKDOWN[0]


def key_x(region, frame, maya):
    """Region x of a key tick: Maya draws it on the frame's tick, the left edge of the frame's cell;
    other timelines keep Blender's frame centre."""
    return region.view2d.view_to_region(frame - 0.5 if maya else frame, 0, clip=False)[0]


def _shows_keys(node):
    if not isinstance(node, bpy.types.Object):
        return True     # pose bones: only selected ones are listed
    if node.mode != 'OBJECT':
        return True     # edit / paint modes: the object whose components are being worked on
    try:
        return node.select_get()
    except RuntimeError:    # not in the view layer
        return False


def tick_nodes(context):
    """Nodes whose keys the Time Slider shows: the selected ones, like Maya (nothing selected = no ticks). Blender
    keeps an active object after it is deselected; its keys are not shown."""
    from . import channel_box
    object_type = bpy.types.Object      # looked up once (``key_frames``)
    return [n for n in channel_box.targets(context) if not isinstance(n, object_type) or _shows_keys(n)]


_HELD = {}      # region pointer -> its keys while a move or a time drag runs without playback (``_shown_keys``)


def _shown_keys(context, region):
    """``key_frames`` of the ticked nodes. While a move (Object / Pose Mode) or a time drag runs and playback doesn't,
    neither the selection nor the keys change until it ends — unless an animation editor's move drags keys, which
    updates their Action (``_drop_held``) — so the keys found once are drawn again (hundreds of selected bones were
    read again on every redraw of the drag). During playback a move can key (auto keying): read every time."""
    from .maya_joints import scrubbing, transforming
    playing = context.screen.is_animation_playing
    dragging = (context.mode in {'OBJECT', 'POSE'} and transforming()) or scrubbing()
    if playing or not dragging:
        _HELD.clear()
        return key_frames(tick_nodes(context), playing or dragging)
    ptr = region.as_pointer()
    got = _HELD.get(ptr)
    if got is None:
        if len(_HELD) > 16:
            _HELD.clear()
        got = _HELD[ptr] = key_frames(tick_nodes(context), True)
    return got


@persistent
def _drop_held(_scene, depsgraph=None):
    """Keys moved (their Action updated), undo, redo, a file load: the held keys and the curves' keys are read
    again."""
    if (_HELD or _KEYS or _PARTS or _BONE_KEYS) and (depsgraph is None or depsgraph.id_type_updated('ACTION')):
        _HELD.clear()
        _KEYS.clear()
        _PARTS.clear()
        _BONE_KEYS.clear()


@persistent
def _drop_keys(*_args):
    """A frame change evaluates what was tagged before it without a depsgraph update (a key set during playback
    would not reach ``_drop_held``): the curves' keys are read again on the next redraw."""
    _KEYS.clear()
    _PARTS.clear()
    _BONE_KEYS.clear()


def _draw_keys(context, region, maya=False):
    keys = _shown_keys(context, region)
    if not keys:
        return
    import gpu
    w = max(1.0, round(context.preferences.system.ui_scale or 1.0))
    h = region.height
    if maya:
        from ..operators import bookmarks
        if bookmarks.shown(context):     # Maya: keys stay under the bookmark strip
            h = _rows("strip", h, ROWS_BOOKMARKS, context.preferences.system.ui_scale or 1.0)[0]
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    current = context.scene.frame_current
    for colour, breakdown in ((KEY_RGB, False), (BREAKDOWN_RGB, True)):
        tris = []
        for f, bd in keys:
            if bd != breakdown:
                continue
            x = key_x(region, f, maya)
            if x < -w or x > region.width + w:
                continue
            x0, x1 = int(x), int(x) + w
            if abs(f - current) < 0.5:
                # Blender draws its current-frame box over add-on drawing (the region's draw_overlay runs after
                # POST_PIXEL), and in the Maya layout that box fills the Time Slider: a key at the current frame
                # was invisible (issue #38). Maya shows it through its current-time block, one frame wide. Here the
                # key fills the current frame's cell: the box hides its middle and the rows above and below the
                # box stay red, while the ticks of the neighbouring frames stay visible.
                left, right = (region.view2d.view_to_region(f + d, 0, clip=False)[0] for d in (-0.5, 0.5))
                x0 = int(left)
                x1 = max(x0 + w, int(right))
            tris += [(x0, 0), (x1, 0), (x1, h), (x0, 0), (x1, h), (x0, h)]
        if tris:
            call(shader.uniform_float, "color", colour)
            call(_tris_batch(shader, tris).draw, shader)


@persistent
def _on_load(_dummy=None):
    _subscribe()   # file loading clears msgbus subscriptions
    _KEYS.clear()  # another file: other curves
    _PARTS.clear()
    _BONE_KEYS.clear()
    _HELD.clear()
    if not bpy.app.background:
        _schedule()


classes = (ALLSET_MT_anim_preferences, ALLSET_PT_time_slider, ALLSET_OT_time_scrub, ALLSET_OT_time_range_all,
           ALLSET_OT_time_range_drag, ALLSET_OT_time_slider_menu, ALLSET_OT_time_slider_delete,
           ALLSET_OT_time_view_lock,
           ALLSET_OT_time_slider_unavailable, *TIME_SLIDER_MENUS, *time_slider_bookmarks.classes)


# Maya's undo never moves the current time (a time change isn't an undo step there); Blender's memfile undo restores
# the scene's frame_current with everything else, so Ctrl+Z after scrubbing jumped back. The frame
# is put back from a 0 s timer, not inside undo_post (data written there before the next push is unsafe for redo).
_KEEP = {}


@persistent
def _keep_frame_pre(*_args):
    scene = bpy.context.scene
    if scene is not None:
        _KEEP["frame"] = (scene.name, scene.frame_current)


@persistent
def _keep_frame_post(*_args):
    if "frame" in _KEEP and not bpy.app.timers.is_registered(restore_frame):
        bpy.app.timers.register(restore_frame, first_interval=0.0)


def restore_frame():
    """Put the frame from before the undo / redo back (None: timer done)."""
    name, frame = _KEEP.pop("frame", (None, None))
    scene = bpy.context.scene
    if scene is not None and scene.name == name and scene.frame_current != frame:
        scene.frame_current = frame
    return None


_UNDO_HANDLERS = (("undo_pre", _keep_frame_pre), ("redo_pre", _keep_frame_pre),
                  ("undo_post", _keep_frame_post), ("redo_post", _keep_frame_post),
                  ("depsgraph_update_post", _drop_held), ("undo_post", _drop_held), ("redo_post", _drop_held),
                  ("frame_change_post", _drop_keys))


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    for name, fn in _UNDO_HANDLERS:
        getattr(bpy.app.handlers, name).append(fn)
    wm = bpy.types.WindowManager
    wm.allset_time_range_on = bpy.props.BoolProperty(
        name="Time Range", description="A Shift-dragged Time Slider range is highlighted", options={'SKIP_SAVE'})
    wm.allset_time_range = bpy.props.IntVectorProperty(name="Time Range", size=2, options={'SKIP_SAVE'})
    _draw_handle.append(bpy.types.SpaceDopeSheetEditor.draw_handler_add(_draw_range, (), 'WINDOW', 'POST_PIXEL'))
    buttons, menus = header_classes()

    def make_menus(_previous, on):
        orig_menus = menus.draw_collapsible     # bound class method (Blender's, or another add-on's wrapper)

        def _menus_5(cls, context, layout):
            # Timeline mode: the menus live in ALLSET_MT_anim_preferences (Maya has no menus in the Range Slider)
            if not (on() and _is_timeline(context)):
                return orig_menus(context, layout)
        return classmethod(_menus_5)

    def make_header(_previous, on):
        orig_header = buttons.draw_header

        def _header_5(cls, context, layout):
            if on() and _is_timeline(context):
                return draw_header(context, layout)
            return orig_header(context, layout)
        return classmethod(_header_5)
    # another add-on that wraps these while Maya mode is on keeps its wrapper when Maya mode goes off (#449)
    kit_wraps.wrap(menus, "draw_collapsible", make_menus)
    kit_wraps.wrap(buttons, "draw_header", make_header)
    _ORIGINAL["draw_header"] = kit_wraps.previous(buttons, "draw_header")
    _subscribe()
    bpy.app.handlers.load_post.append(_on_load)


def unregister():
    for name, fn in _UNDO_HANDLERS:
        if fn in getattr(bpy.app.handlers, name):
            getattr(bpy.app.handlers, name).remove(fn)
    if bpy.app.timers.is_registered(restore_frame):
        bpy.app.timers.unregister(restore_frame)
    _KEEP.clear()
    time_slider_bookmarks.clear()
    _HELD.clear()
    _KEYS.clear()
    _PARTS.clear()
    _BONE_KEYS.clear()
    _TRIS.clear()
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    bpy.msgbus.clear_by_owner(_OWNER)
    if bpy.app.timers.is_registered(_deferred_fit):
        bpy.app.timers.unregister(_deferred_fit)
    _fitted.clear()
    buttons, menus = header_classes()
    _ORIGINAL.pop("draw_header", None)
    kit_wraps.unwrap(buttons, "draw_header")
    kit_wraps.unwrap(menus, "draw_collapsible")
    while _draw_handle:
        bpy.types.SpaceDopeSheetEditor.draw_handler_remove(_draw_handle.pop(), 'WINDOW')
    wm = bpy.types.WindowManager
    del wm.allset_time_range
    del wm.allset_time_range_on
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
