# SPDX-License-Identifier: GPL-3.0-or-later
"""Graph Editor Region Keys tool and Select > Prefer Selected Curves, like Maya.

Region Keys tool (``window_manager.allset_graph_key_tool`` = 'REGION', Edit > Transformation Tools > Region Keys
Tool or the toolbar button): a marquee selects keys as usual and leaves its region as a box. ``graph_scale_box``
draws that box and drags it: a side scales the keys inside in time or value about the opposite side, a corner both,
a drag inside the box moves them, and the box follows. The region stays while the selected keys are the ones it was
made for (the same keys at the same places); after any other selection or key move the box is the selected keys'
own box, like the Scale Keys box.

Prefer Selected Curves (add-on pref ``graph_prefer_selected``, Select menu): while some curves have selected keys
or tangents, a click picks a key of those curves when one is within reach, even with a key of another curve nearer;
a marquee that catches keys of those curves leaves the other curves' keys unselected. With no such curves, clicks
and marquees work as usual.

Both read the marquee after Blender's box select ends (``_finish_box``, the region in region pixels from the
operator's properties). Pure rules: ``prefer_pick``, ``caught_keys``, ``prefer_drop``, ``region_moved``,
``region_scaled``.
"""

import bpy
from bpy.props import EnumProperty

from . import graph_move

CLICK_PX = 10.0          # Blender's key pick distance (x pixel size)
POLL = 0.02

_REGIONS = {}            # area pointer -> {"view": (x0, y0, x1, y1) in frames / display values, "sig": ...}
_PENDING = {}


# --- pure rules -------------------------------------------------------------------------------------------------

def prefer_pick(candidates, tol):
    """The key a click takes with Prefer Selected Curves, None for the Graph Editor's own pick.

    ``candidates`` = [(distance px, on a preferred curve, key)]. With keys of a preferred curve and of another curve
    both within ``tol`` the nearest preferred key wins (the Graph Editor would take the first curve's); with keys of
    only one kind in reach the Graph Editor picks as usual."""
    near =[c for c in candidates if c[0] <= tol]
    preferred = [c for c in near if c[1]]
    if not preferred or len(preferred) == len(near):
        return None
    return min(preferred, key=lambda c: c[0])[2]


def caught_keys(mode, before, after):
    """Keys a marquee caught: everything selected after a Set box, else what it added."""
    if mode == 'SUB':
        return set()
    if mode == 'SET':
        return set(after)
    return set(after) - set(before)


def prefer_drop(caught, preferred):
    """Keys ((curve pointer, index)) a marquee must leave unselected with Prefer Selected Curves: the caught keys of
    the other curves, when it caught any key of a preferred curve."""
    if not any(k[0] in preferred for k in caught):
        return set()
    return {k for k in caught if k[0] not in preferred}


def region_moved(view, dt, dv):
    x0, y0, x1, y1 = view
    return x0 + dt, y0 + dv, x1 + dt, y1 + dv


def region_scaled(view, pivot, sx, sy):
    px, py = pivot
    x0, y0, x1, y1 = view
    xs = sorted((px + (x0 - px) * sx, px + (x1 - px) * sx))
    ys = sorted((py + (y0 - py) * sy, py + (y1 - py) * sy))
    return xs[0], ys[0], xs[1], ys[1]


# --- the region of a Graph Editor ---------------------------------------------------------------------------------

def _shown(context):
    return [fc for fc in (getattr(context, "editable_fcurves", None) or ()) if not fc.hide]


def signature(context):
    """The selected keys of the shown curves and where they are (what a region was made for)."""
    import numpy as np
    out = []
    for fc in _shown(context):
        pts = fc.keyframe_points
        n = len(pts)
        if not n:
            continue
        sel = np.empty(n, dtype=bool)
        pts.foreach_get("select_control_point", sel)
        if not sel.any():
            continue
        co = np.empty(2 * n, dtype=np.float32)
        pts.foreach_get("co", co)
        out.append((fc.as_pointer(), np.round(co.reshape(n, 2)[sel], 4).tobytes()))
    return tuple(out)


def region_of(context):
    """The Region Keys box of this Graph Editor in view units, None when there is none or the keys changed."""
    area =getattr(context, "area", None)
    entry = _REGIONS.get(area.as_pointer()) if area is not None else None
    if entry is None:
        return None
    if entry["sig"] != signature(context):
        _REGIONS.pop(area.as_pointer(), None)
        return None
    return entry["view"]


def store(context, view):
    """Keep ``view`` as the region of this Graph Editor for the keys selected now (none selected: no region)."""
    area = context.area
    sig = signature(context)
    if view is None or not sig:
        _REGIONS.pop(area.as_pointer(), None)
        return
    x0, y0, x1, y1 = view
    _REGIONS[area.as_pointer()] = {"view": (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), "sig": sig}


def clear():
    _REGIONS.clear()


# --- Prefer Selected Curves ---------------------------------------------------------------------------------------

def prefer_on(context=None):
    from .. import preferences
    try:
        return bool(preferences.get(context).graph_prefer_selected)
    except (KeyError, AttributeError):
        return False


def _has_selection(fc):
    return any(kp.select_control_point or kp.select_left_handle or kp.select_right_handle
               for kp in fc.keyframe_points)


def preferred_curves(context):
    """Pointers of the shown curves with selected keys or tangents."""
    return {fc.as_pointer() for fc in _shown(context) if _has_selection(fc)}


def _candidates(context, x, y, preferred):
    """[(distance px, on a preferred curve, (curve, key index))] of the shown curves' keys."""
    v2d = context.region.view2d
    fcs = _shown(context)
    out = []
    for fc, scale in zip(fcs, graph_move._value_scales(context, fcs) if fcs else ()):
        off = graph_move._offset(context, fc)
        mine = fc.as_pointer() in preferred
        for i, kp in enumerate(fc.keyframe_points):
            rx, ry = v2d.view_to_region(kp.co.x, (kp.co.y + off) / scale, clip=False)
            d = max(abs(rx - x), abs(ry - y))
            if d <= CLICK_PX * 4:
                out.append((d, mine, (fc, i)))
    return out


def _pick_tol(context):
    return CLICK_PX * getattr(context.preferences.system, "pixel_size", 1.0)


def _deselect_keys(fcs):
    for fc in fcs:
        pts = fc.keyframe_points
        n = len(pts)
        for attr in ("select_control_point", "select_left_handle", "select_right_handle"):
            pts.foreach_set(attr, [False] * n)


def apply_click(context, fc, i, mode):
    """A click on key ``i`` of ``fc`` with the Graph Editor's Maya rules: Set = only it, Toggle (Shift), Sub (Ctrl)
    deselects it, Add (Ctrl+Shift)."""
    kp = fc.keyframe_points[i]
    if mode == 'SET':
        shown = _shown(context)
        _deselect_keys(shown)
        for other in shown:
            other.select = other == fc
        on = True
    elif mode == 'TOGGLE':
        on = not kp.select_control_point
    else:
        on = mode == 'ADD'
    kp.select_control_point = kp.select_left_handle = kp.select_right_handle = on
    if on:
        fc.select = True


_MODES = (('SET', "Set", ""), ('TOGGLE', "Toggle", ""), ('SUB', "Deselect", ""), ('ADD', "Add", ""))


class ALLSET_OT_graph_prefer_click(bpy.types.Operator):
    """Prefer Selected Curves: a Graph Editor click picks a key of the curves with selected keys first"""
    bl_idname = "allset.graph_prefer_click"
    bl_label = "Select Key"
    bl_options = {'UNDO', 'INTERNAL'}

    mode: EnumProperty(items=_MODES, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if not graph_move._graph_window(context) or not prefer_on(context):
            return {'PASS_THROUGH'}
        region = context.region
        x, y = event.mouse_x - region.x, event.mouse_y - region.y
        from . import graph_handle_drag
        if graph_handle_drag.on_scale_box(context, x, y):
            return {'PASS_THROUGH'}         # the Scale / Region Keys box's side or corner
        preferred = preferred_curves(context)
        if not preferred:
            return {'PASS_THROUGH'}
        try:
            from ..ui import graph_handles
            handles = graph_handles.current(context)
            if handles is not None and len(handles) and graph_handle_drag.pick(context, handles, x, y) is not None:
                return {'PASS_THROUGH'}     # a tangent handle end: the kit's handle drag
        except (AttributeError, ReferenceError, RuntimeError, ValueError):
            pass
        hit = prefer_pick(_candidates(context, x, y, preferred), _pick_tol(context))
        if hit is None:
            return {'PASS_THROUGH'}
        fc, i = hit
        # a press on a key that is already selected keeps the selection, so a drag moves every selected key; a
        # click without a drag then selects only it
        self._later = self.mode == 'SET' and fc.keyframe_points[i].select_control_point
        if not self._later:
            apply_click(context, fc, i, self.mode)
            graph_move._redraw(context)
        self._hit = hit
        self._press = (x, y)
        self._region = region
        self._drag_px = max(1, context.preferences.inputs.drag_threshold_mouse)
        self._can_move = fc.keyframe_points[i].select_control_point
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            x, y = event.mouse_x - self._region.x, event.mouse_y - self._region.y
            if self._can_move and max(abs(x - self._press[0]), abs(y - self._press[1])) >= self._drag_px:
                # a drag from the picked key moves the selected keys, like a drag from a key
                try:
                    bpy.ops.transform.translate('INVOKE_DEFAULT')
                except RuntimeError:
                    pass
                return {'FINISHED'}
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if self._later:
                try:
                    apply_click(context, *self._hit, 'SET')
                except (ReferenceError, IndexError):
                    pass
                graph_move._redraw(context)
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


# --- the marquee ----------------------------------------------------------------------------------------------------

def _finish_box():
    from .. import live_refs
    from . import graph_handle_drag, select_2d
    p = _PENDING.get("box")
    if p is None:
        return None
    wm = bpy.context.window_manager
    running = any(op.bl_idname == "GRAPH_OT_select_box" for w in wm.windows for op in live_refs.running_modals(w))
    if not p["started"]:
        last = wm.operators[-1].as_pointer() if len(wm.operators) else 0
        p["started"] = running or last != p["last"]
        p["ticks"] += 1
        if not p["started"] and p["ticks"] < 40:
            return POLL
    if running:
        return POLL
    # the kit's own marquee rules first (Shift toggle, tangent ends): they rewrite the key selection
    if (select_2d._PENDING.get("box") is not None or graph_handle_drag._PENDING.get("box") is not None) \
            and p["ticks"] < 120:
        p["ticks"] += 1
        return POLL
    _PENDING.pop("box", None)
    last = wm.operators[-1] if len(wm.operators) else None
    if last is None or last.as_pointer() == p["last"] or last.bl_idname != "GRAPH_OT_select_box":
        return None                     # a key drag (tweak) or a cancelled marquee
    win, area = live_refs.find_area(p["area"], p["window"])
    if area is None:
        return None
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None:
        return None
    try:
        props = last.properties
        mode = props.mode
        rect = (props.xmin, props.ymin, props.xmax, props.ymax)
        with bpy.context.temp_override(window=win, area=area, region=region):
            finish_marquee(bpy.context, p, mode, rect)
        area.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    return None


def finish_marquee(context, p, mode, rect):
    """After a marquee: Prefer Selected Curves drops the other curves' caught keys; the Region Keys tool keeps the
    marquee's region (``rect`` in region pixels)."""
    from . import select_2d
    if p.get("preferred"):
        items = select_2d.key_items()
        drop = prefer_drop(caught_keys(mode, p["before"], select_2d.key_state(items)), p["preferred"])
        for k in drop:
            kp = items.get(k)
            if kp is not None:
                kp.select_control_point = kp.select_left_handle = kp.select_right_handle = False
    if p.get("region"):
        if mode == 'SUB':
            store(context, None)
            return
        v2d = context.region.view2d
        x0, y0 = v2d.region_to_view(rect[0], rect[1])
        x1, y1 = v2d.region_to_view(rect[2], rect[3])
        store(context, (x0, y0, x1, y1))


class ALLSET_OT_graph_marquee_watch(bpy.types.Operator):
    """Region Keys tool / Prefer Selected Curves: read the Graph Editor's marquee when it ends (passes through)"""
    bl_idname = "allset.graph_marquee_watch"
    bl_label = "Graph Editor Marquee"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if not graph_move._graph_window(context):
            return {'PASS_THROUGH'}
        region_tool = graph_move.key_tool(context) == 'REGION'
        preferred = preferred_curves(context) if prefer_on(context) else set()
        if not (region_tool or preferred):
            return {'PASS_THROUGH'}
        from . import select_2d
        wm = context.window_manager
        _PENDING["box"] = {"region": region_tool, "preferred": preferred, "before": select_2d.key_state(),
                           "last": wm.operators[-1].as_pointer() if len(wm.operators) else 0,
                           "started": False, "ticks": 0, "window": context.window.as_pointer(),
                           "area": context.area.as_pointer()}
        if not bpy.app.timers.is_registered(_finish_box):
            bpy.app.timers.register(_finish_box, first_interval=POLL)
        return {'PASS_THROUGH'}


classes = (ALLSET_OT_graph_prefer_click, ALLSET_OT_graph_marquee_watch)


def unregister_timers():
    _PENDING.clear()
    _REGIONS.clear()
    if bpy.app.timers.is_registered(_finish_box):
        bpy.app.timers.unregister(_finish_box)
