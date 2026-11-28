# SPDX-License-Identifier: GPL-3.0-or-later
"""Key edits on the keys a Graph Editor / Dope Sheet shows: the selected keys (``selected_keys``, ``editor_curves``),
Cut / Copy / Paste / Delete / Scale / Snap Keys on them (``*_selected``, ``paste_editor``), Add / Remove Inbetween
(``inbetween``), Mute / Unmute Key (``mute_selected``), Remove Key by time (``remove_keys``) and Clamp / Offset
Curves (``clamp_keys``, ``offset_keys``). The operators that run them are in graph_key_menu, which re-exports them.
"""

import bpy

from . import time_keys

MUTE_NAME = "Maya mute"
EPS = 1e-4
_END_GAP = 1e-3      # the hold stops just before the next unmuted key (Maya: that key's own value at its time)
_FAR = 1e7           # a muted last key holds to the end


def _space(context):
    space = getattr(context, "space_data", None)
    if space is None:
        return None
    if space.type == 'GRAPH_EDITOR' or (space.type == 'DOPESHEET_EDITOR' and space.mode != 'TIMELINE'):
        return space
    return None


def in_key_editor(context):
    return _space(context) is not None


def editor_curves(context):
    """The editable curves a Graph Editor / Dope Sheet shows."""
    if not in_key_editor(context):
        return []
    curves = getattr(context, "editable_fcurves", None)
    if curves is None:
        curves = getattr(context, "visible_fcurves", None) or ()
    return list(curves)


def selected_keys(context):
    """[(fcurve, [selected keyframe points])] in the key editor."""
    out = []
    for fc in editor_curves(context):
        pts = [kp for kp in fc.keyframe_points if kp.select_control_point]
        if pts:
            out.append((fc, pts))
    return out


def has_selected_keys(context):
    return bool(selected_keys(context))


# --- selected-key versions of the key windows ---------------------------------------------------------------

def _remove(fc, pts):
    """Remove the keyframe points ``pts`` of ``fc``: by index, last first (removing a key moves the ones after it, so
    a point taken before the first removal can name another key afterwards)."""
    ids = {kp.as_pointer() for kp in pts}
    idx = [i for i, kp in enumerate(fc.keyframe_points) if kp.as_pointer() in ids]
    for i in reversed(idx):
        fc.keyframe_points.remove(fc.keyframe_points[i])
    fc.update()


def delete_selected(context):
    """Delete Keys from a key editor: the selected keys. Count removed."""
    n = 0
    for fc, pts in selected_keys(context):
        n += len(pts)
        _remove(fc, pts)
    return n


_clip = {"from": None}     # who filled the last clipboard: "editor" (Blender's key buffer) or "kit" (time_keys)


def copy_selected(context):
    """Copy Keys from a key editor = the editor's own key buffer (Edit > Paste in the editor reads it)."""
    space = _space(context)
    if space is None or not has_selected_keys(context):
        return 0
    (bpy.ops.graph.copy if space.type == 'GRAPH_EDITOR' else bpy.ops.action.copy)()
    _clip["from"] = "editor"
    return sum(len(p) for _f, p in selected_keys(context))


def cut_selected(context):
    n = copy_selected(context)
    if n:
        delete_selected(context)
    return n


def note_kit_copy():
    _clip["from"] = "kit"


def editor_clipboard():
    return _clip["from"] == "editor"


def paste_editor(context, time_range="Current", time_offset=0.0, value_offset=0.0, copies=1, method="Merge"):
    """Paste Keys into a key editor from its buffer: Current = at the current time, Clipboard = at the copied
    times; Merge mixes, Replace replaces the pasted range, Insert pushes later keys right by the pasted length.
    Time / value offsets move the pasted keys; Copies repeats them end to end."""
    space = _space(context)
    if space is None:
        return 0
    graph = space.type == 'GRAPH_EDITOR'
    paste = bpy.ops.graph.paste if graph else bpy.ops.action.paste
    offset = 'NONE' if time_range == "Clipboard" else 'START'
    merge = 'OVER_RANGE' if method == "Replace" else 'MIX'
    n = 0
    shift = 0.0
    for _i in range(max(1, int(copies))):
        before = {fc.as_pointer(): {kp.as_pointer() for kp in fc.keyframe_points} for fc in editor_curves(context)}
        try:
            paste(offset=offset, merge=merge)
        except RuntimeError:
            return n
        pasted = []
        for fc in editor_curves(context):
            old = before.get(fc.as_pointer(), set())
            pasted += [(fc, kp) for kp in fc.keyframe_points if kp.as_pointer() not in old or kp.select_control_point]
        if not pasted:
            return n
        span = max(kp.co.x for _f, kp in pasted) - min(kp.co.x for _f, kp in pasted)
        dx = time_offset + shift
        for fc, kp in pasted:
            u = time_keys.value_unit(fc)
            if abs(dx) > 1e-9:
                time_keys._move(kp, dx)
            if abs(value_offset) > 1e-12:
                time_keys._offset_value(kp, value_offset * u)
        if method == "Insert":
            start = min(kp.co.x for _f, kp in pasted)
            ids = {kp.as_pointer() for _f, kp in pasted}
            for fc in {f.as_pointer(): f for f, _k in pasted}.values():
                for kp in fc.keyframe_points:
                    if kp.as_pointer() not in ids and kp.co.x >= start - EPS:
                        time_keys._move(kp, span + 1.0)
        for fc in {f.as_pointer(): f for f, _k in pasted}.values():
            fc.update()
        n += len(pasted)
        shift += span + 1.0
    return n


def scale_selected(context, method="Scale/Pivot", time_scale=1.0, time_pivot=0.0, value_scale=1.0, value_pivot=0.0,
                   new_start=1.0, new_end=10.0):
    """Scale Keys from a key editor: the selected keys (time about the pivot, values about the value pivot in Maya
    units; Start/End maps the selected keys' span onto New start / end)."""
    sel = selected_keys(context)
    if not sel:
        return 0
    if method == "Start/End":
        xs = [kp.co.x for _f, pts in sel for kp in pts]
        a, b = min(xs), max(xs)
        k = (new_end - new_start) / (b - a) if b - a > EPS else 1.0

        def tmap(x):
            return new_start + (x - a) * k
    else:
        def tmap(x):
            return time_pivot + (x - time_pivot) * time_scale
    n = 0
    for fc, pts in sel:
        vp = value_pivot * time_keys.value_unit(fc)
        vs = value_scale if method != "Start/End" else 1.0
        for kp in pts:
            x, y = kp.co.x, kp.co.y
            nx, ny = tmap(x), vp + (y - vp) * vs
            ks = tmap(x + 1.0) - nx
            for h in (kp.handle_left, kp.handle_right):
                h.x, h.y = nx + (h.x - x) * ks, ny + (h.y - y) * vs
            kp.co.x, kp.co.y = nx, ny
            n += 1
        fc.update()
    return n


def snap_selected(context, snap="Times", time_multiple=1.0, value_multiple=1.0):
    n = 0
    for fc, pts in selected_keys(context):
        u = time_keys.value_unit(fc)
        for kp in pts:
            hit = False
            if snap in ("Times", "Both"):
                dx = time_keys._snap(kp.co.x, time_multiple) - kp.co.x
                if abs(dx) > 1e-9:
                    time_keys._move(kp, dx)
                    hit = True
            if snap in ("Values", "Both"):
                dv = time_keys._snap(kp.co.y / u, value_multiple) * u - kp.co.y
                if abs(dv) > 1e-12:
                    time_keys._offset_value(kp, dv)
                    hit = True
            n += hit
        fc.update()
    return n


# --- Add / Remove Inbetween ---------------------------------------------------------------------------------

def inbetween(context, delta):
    """Keys at or after the current frame on the editor's curves move by ``delta`` frames (Maya ``-option over``:
    a key moved onto another stays a separate key). Count moved."""
    frame = context.scene.frame_current + context.scene.frame_subframe
    n = 0
    for fc in editor_curves(context):
        pts = [kp for kp in fc.keyframe_points if kp.co.x >= frame - EPS]
        if delta < 0:
            pts.sort(key=lambda kp: kp.co.x)
        else:
            pts.sort(key=lambda kp: -kp.co.x)
        for kp in pts:
            time_keys._move(kp, delta)
        if pts:
            fc.update()
            n += len(pts)
    return n


# --- Mute / Unmute Key --------------------------------------------------------------------------------------

def mute_modifiers(fc):
    return [m for m in fc.modifiers if m.type == 'STEPPED' and m.name == MUTE_NAME]


def muted_times(fc):
    """Times of the keys the kit's mute modifiers hold (key times inside a [start, end) range)."""
    spans = [(m.frame_start, m.frame_end) for m in mute_modifiers(fc)]
    return sorted(kp.co.x for kp in fc.keyframe_points
                  if any(a - EPS <= kp.co.x <= b + EPS for a, b in spans))


def set_muted(fc, times):
    """Rebuild the mute modifiers: each run of consecutive muted keys holds its first key's value until the next
    unmuted key (to the end after the last key)."""
    for m in mute_modifiers(fc):
        fc.modifiers.remove(m)
    keys = sorted(kp.co.x for kp in fc.keyframe_points)
    muted = [any(abs(x - t) <= EPS for t in times) for x in keys]
    i = 0
    while i < len(keys):
        if not muted[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(keys) and muted[j + 1]:
            j += 1
        start = keys[i]
        end = keys[j + 1] - _END_GAP if j + 1 < len(keys) else _FAR
        m = fc.modifiers.new('STEPPED')
        m.name = MUTE_NAME
        m.frame_step = max(1.0, end - start + 1.0)
        m.frame_offset = start
        m.use_restricted_range = True
        m.frame_end = end            # end before start: Blender clamps start to end otherwise
        m.frame_start = start
        m.blend_in = m.blend_out = 0.0
        m.show_expanded = False
        i = j + 1
    fc.update()


def mute_selected(context, mute=True):
    """Maya Keys > Mute / Unmute Key on the selected keys. Count of keys changed."""
    n = 0
    for fc, pts in selected_keys(context):
        times = muted_times(fc)
        sel = [kp.co.x for kp in pts]
        if mute:
            new = sorted(set(times) | set(sel))
        else:
            new = [t for t in times if not any(abs(t - s) <= EPS for s in sel)]
        if new != times:
            n += len(sel)
            set_muted(fc, new)
    return n


# --- Keys > Remove Key ----------------------------------------------------------------------------------------
# Maya's Remove Key items act on the curves that hold selected keys. Unsnapped / Before / After Current Frame use
# the editor's shown curves when no key is selected; Outside Selected Range and Ripple Delete need selected keys, whose
# earliest and latest times are the range (on every curve with a selected key).

RIPPLE_GAP = 0.02     # the key from the range's end lands just after the start (Blender merges keys closer than
                      # 0.01 frame), so the curve jumps there like Maya's


def _key_at(fc, t):
    return next((kp for kp in fc.keyframe_points if abs(kp.co.x - t) < EPS), None)


def _ensure_key(fc, t):
    """A key at time ``t`` on ``fc`` holding the curve's value there (the existing one if any)."""
    if _key_at(fc, t) is None:
        fc.keyframe_points.insert(t, fc.evaluate(t))


def _remove_at(fc, times):
    """Remove the keys of ``fc`` at ``times`` (looked up again after each removal: removing a key moves the others)."""
    for t in times:
        kp = _key_at(fc, t)
        if kp is not None:
            fc.keyframe_points.remove(kp)
    if times:
        fc.update()


def selected_range(context):
    """(first, last) time of the selected keys in the editor, or None."""
    times = [kp.co.x for _fc, pts in selected_keys(context) for kp in pts]
    return (min(times), max(times)) if times else None


def remove_keys(context, mode):
    """Maya Keys > Remove Key items. Count of removed keys, or None when the mode needs selected keys and has none."""
    picked = [fc for fc, _pts in selected_keys(context)]
    a = b = None
    if mode in {"OUTSIDE", "RIPPLE"}:
        rng = selected_range(context)
        if rng is None:
            return None
        a, b = rng
    curves = picked or (editor_curves(context) if mode in {"UNSNAPPED", "BEFORE", "AFTER"} else [])
    frame = context.scene.frame_current + context.scene.frame_subframe
    n = 0
    for fc in curves:
        if mode == "UNSNAPPED":
            gone = [kp for kp in fc.keyframe_points if abs(kp.co.x - round(kp.co.x)) > EPS]
        elif mode == "BEFORE":
            gone = [kp for kp in fc.keyframe_points if kp.co.x < frame - EPS]
        elif mode == "AFTER":
            gone = [kp for kp in fc.keyframe_points if kp.co.x > frame + EPS]
        elif mode == "OUTSIDE":
            _ensure_key(fc, a)
            _ensure_key(fc, b)
            gone = [kp for kp in fc.keyframe_points if kp.co.x < a - EPS or kp.co.x > b + EPS]
        else:                                   # RIPPLE
            if b - a < EPS:
                continue
            _ensure_key(fc, a)
            _ensure_key(fc, b)
            gone = [kp for kp in fc.keyframe_points if a + EPS < kp.co.x < b - EPS]
        n += len(gone)
        _remove_at(fc, [kp.co.x for kp in gone])
        if mode == "RIPPLE":
            later = sorted((kp for kp in fc.keyframe_points if kp.co.x >= b - EPS), key=lambda kp: kp.co.x)
            for kp in later:
                time_keys._move(kp, a - b + (RIPPLE_GAP if abs(kp.co.x - b) < EPS else 0.0))
            fc.update()
    return n


# --- Curves > Clamp / Offset Curves --------------------------------------------------------------------------

def _curve_keys(context, time_range='SELECTED', start=0.0, end=0.0):
    """(F-curve, keys) to act on, like Maya: the selected keys, else every key of the shown curves; a Playback or
    Custom range keeps only those of them inside it."""
    work = selected_keys(context) or [(fc, list(fc.keyframe_points)) for fc in editor_curves(context)]
    if time_range == 'SELECTED':
        return work
    if time_range == 'TIME_SLIDER':
        sc = context.scene
        start, end = ((sc.frame_preview_start, sc.frame_preview_end) if sc.use_preview_range
                      else (sc.frame_start, sc.frame_end))
    out = []
    for fc, pts in work:
        pts = [kp for kp in pts if start - EPS <= kp.co.x <= end + EPS]
        if pts:
            out.append((fc, pts))
    return out


def clamp_keys(context, limit, side, time_range='SELECTED', start=0.0, end=0.0):
    """Maya Curves > Clamp Curves: key values past ``limit`` ('ABOVE' = greater, 'BELOW' = smaller) become the limit;
    the tangents keep their shape. Count of changed keys."""
    n = 0
    for fc, pts in _curve_keys(context, time_range, start, end):
        hit = False
        for kp in pts:
            v = kp.co.y
            if (side == 'ABOVE' and v > limit) or (side == 'BELOW' and v < limit):
                dy = limit - v
                kp.co.y = limit
                kp.handle_left.y += dy
                kp.handle_right.y += dy
                hit = True
                n += 1
        if hit:
            fc.update()
    return n


def offset_keys(context, frames, mode, time_range='SELECTED', start=0.0, end=0.0):
    """Maya Curves > Offset Curves: move the keys in time by ``frames`` ('RELATIVE'), or so the first of them lands
    on frame ``frames`` ('START'). Count of moved keys."""
    work = _curve_keys(context, time_range, start, end)
    times = [kp.co.x for _fc, pts in work for kp in pts]
    if not times:
        return 0
    dx = frames if mode == 'RELATIVE' else frames - min(times)
    if abs(dx) < EPS:
        return 0
    n = 0
    for fc, pts in work:
        for kp in sorted(pts, key=lambda kp: kp.co.x, reverse=dx > 0):
            time_keys._move(kp, dx)
            n += 1
        fc.update()
    return n
