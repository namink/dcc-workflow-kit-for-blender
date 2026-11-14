# SPDX-License-Identifier: GPL-3.0-or-later
"""Picking and dragging tangent handles the kit draws in the Graph Editor (#296, ``ui/graph_handles.py``).

While the kit draws a Graph Editor's handles, Blender's own handle picking is off, so the kit picks and drags them:

- a left press on a handle end (closer than any key) selects that handle: plain / Ctrl = only it (a handle that is
  already selected keeps the selection, so several drag together), Shift = toggle, Ctrl+Shift = add; a drag from
  there moves every selected handle. Anywhere else the press passes through to the Graph Editor's own click.
- a middle drag with the Move Keys tool and selected handles but no selected key moves those handles.
- a marquee also picks the handle ends inside it (Shift toggles them, Ctrl deselects); when it caught handle ends,
  only the keys inside it count (Blender's marquee would also take a whole curve it merely crosses).

A drag moves each handle end by the mouse motion on screen. A non-weighted tangent (Maya) only turns: its time
length stays a third of the way to the neighbour key, its direction points at the moved end. A weighted one ends
where the moved end is (with Lock Tangent Length its length stays). A handle never crosses its key in time. An
aligned (unified) tangent turns its other side along; an automatic one becomes aligned, a vector one free. Esc /
right click puts everything back; a drag is one undo step.

Pure rule: ``arm_for`` (screen motion -> stored arm).
"""

import math

import bpy
from bpy.props import EnumProperty

from . import graph_move

CLICK_PX = 10.0           # how close to a handle end a press picks it (x UI scale)
AUTO_TYPES = {'AUTO', 'AUTO_CLAMPED'}


# --- pure rules -------------------------------------------------------------------------------------------------

def arm_for(side, dx_px, dy_px, px_frame, px_value, factor, weighted, third=None, length=None):
    """Stored (frames, value) arm of a handle whose end sits (``dx_px``, ``dy_px``) region pixels from its key.

    ``px_frame`` / ``px_value`` = pixels per frame / per display unit, ``factor`` = display units per stored unit.
    The arm never crosses the key in time (left arms point back, right arms forward; at least half a pixel).
    Non-weighted: time length ``third``, only the direction follows. Weighted: the end itself; ``length`` (a locked
    tangent length in (frames, value)) keeps its length."""
    sign = -1.0 if side == 0 else 1.0
    vx = dx_px / px_frame
    vy = dy_px / px_value / factor
    min_dx = 0.5 / abs(px_frame)
    if vx * sign < min_dx:
        vx = sign * min_dx
    if not weighted:
        if third is None:
            return None
        slope = vy / vx
        return sign * third, sign * third * slope
    if length is not None:
        n = math.hypot(vx, vy)
        if n > 1e-12:
            return vx / n * length, vy / n * length
    return vx, vy


def opposite_arm(arm, length=None, third=None, weighted=True):
    """The other side of an aligned tangent: opposite direction; its own ``length`` (weighted) or time ``third``."""
    ax, ay = arm
    if not weighted:
        if third is None or abs(ax) < 1e-12:
            return None
        f = third / abs(ax)
        return -ax * f, -ay * f
    n = math.hypot(ax, ay)
    if n < 1e-12 or length is None:
        return None
    return -ax / n * length, -ay / n * length


# --- keyframe helpers ---------------------------------------------------------------------------------------------

def _arm(kp, side):
    h = kp.handle_left if side == 0 else kp.handle_right
    return h[0] - kp.co[0], h[1] - kp.co[1]


def _set_arm(kp, side, ax, ay):
    p = (kp.co[0] + ax, kp.co[1] + ay)
    if side == 0:
        kp.handle_left = p
    else:
        kp.handle_right = p


def _types(kp):
    return kp.handle_left_type, kp.handle_right_type


def _set_types(kp, types):
    kp.handle_left_type, kp.handle_right_type = types


def dragged_types(types, side):
    """Handle types once ``side`` is dragged: an automatic tangent becomes aligned (both sides), a vector side
    free."""
    lt, rt = types
    if lt in AUTO_TYPES or rt in AUTO_TYPES:
        lt = 'ALIGNED' if lt in AUTO_TYPES else lt
        rt = 'ALIGNED' if rt in AUTO_TYPES else rt
    if side == 0 and lt == 'VECTOR':
        lt = 'FREE'
    if side == 1 and rt == 'VECTOR':
        rt = 'FREE'
    return lt, rt


def _flag(side):
    return "select_left_handle" if side == 0 else "select_right_handle"


def _editable(context):
    return [fc for fc in (getattr(context, "visible_fcurves", None) or ()) if not fc.lock and
            (fc.group is None or not fc.group.lock)]


def deselect_all(context):
    for fc in getattr(context, "visible_fcurves", None) or ():
        n = len(fc.keyframe_points)
        off = [False] * n
        for name in ("select_control_point", "select_left_handle", "select_right_handle"):
            fc.keyframe_points.foreach_set(name, off)


def _ui(context):
    return context.preferences.system.ui_scale or 1.0


def _key_distance(context, space, region, x, y):
    """Distance in pixels from region (x, y) to the nearest key the Graph Editor draws (inf without keys)."""
    import numpy as np
    from ..ui import graph_keys_draw as gk
    unsel, sel = gk.key_points(context, space)
    pts = np.concatenate([unsel, sel]) if len(unsel) or len(sel) else np.zeros((0, 2))
    if not len(pts):
        return math.inf
    px = gk.to_region(region, pts)
    return float(np.min(np.hypot(px[:, 0] - x, px[:, 1] - y)))


def _redraw(context):
    graph_move._redraw(context)


# --- the drag -----------------------------------------------------------------------------------------------------

class Drag:
    """The handles one drag moves, with what they were at the press."""

    def __init__(self, context, handles, rows):
        import numpy as np
        from . import graph_weights
        from ..ui import graph_keys_draw as gk
        # pixels per frame / per value from the exact mapping the handle ends are drawn with: View2D.view_to_region
        # gives whole pixels, and a scale from those would leave a dragged handle end off the mouse
        (x0, y0), (x1, y1) = gk.to_region(context.region, np.array(((0.0, 0.0), (1.0, 1.0))))
        self.px_frame = (x1 - x0) or 1.0
        self.px_value = (y1 - y0) or 1.0
        self.items = []
        self.saved = {}                 # (curve pointer, key index) -> (keyframe point, co, left, right, types)
        self.curves = {}
        picked = {}
        for r in rows:
            fc, i, side = handles.row(r)
            picked.setdefault((fc.as_pointer(), i), set()).add(side)
        for r in rows:
            fc, i, side = handles.row(r)
            kp = fc.keyframe_points[i]
            key = (fc.as_pointer(), i)
            if key not in self.saved:
                self.saved[key] = (fc, i, tuple(kp.co), tuple(kp.handle_left), tuple(kp.handle_right), _types(kp))
            self.curves[fc.as_pointer()] = fc
            weighted = bool(handles.weighted[r])
            _off, factor = handles.factors[int(handles.curves[r])]
            lock = None
            other = 1 - side
            if weighted:
                locked = {p.as_pointer() for p, _l, _r in graph_weights._locked_points(fc)}
                if kp.as_pointer() in locked:
                    lock = math.hypot(*_arm(kp, side))
            types = dragged_types(_types(kp), side)
            coupled = types[0] == 'ALIGNED' and types[1] == 'ALIGNED' and other not in picked[key]
            self.items.append({
                "fc": fc, "i": i, "side": side, "weighted": weighted, "factor": factor or 1.0, "lock": lock,
                "key_px": tuple(handles.key_px[r]), "end_px": tuple(handles.end_px[r]),
                "third": graph_weights.third(fc, i, side), "other_third": graph_weights.third(fc, i, other),
                "other_len": math.hypot(*_arm(kp, other)), "types": types, "coupled": coupled})

    def __bool__(self):
        return bool(self.items)

    def apply(self, dx, dy):
        """Every handle end moved by (``dx``, ``dy``) region pixels from the press."""
        for it in self.items:
            kp, side = it["fc"].keyframe_points[it["i"]], it["side"]
            ex, ey = it["end_px"][0] + dx, it["end_px"][1] + dy
            arm = arm_for(side, ex - it["key_px"][0], ey - it["key_px"][1], self.px_frame, self.px_value,
                          it["factor"], it["weighted"], it["third"], it["lock"])
            if arm is None:
                continue
            if _types(kp) != it["types"]:
                _set_types(kp, it["types"])
            _set_arm(kp, side, *arm)
            if it["coupled"]:
                opp = opposite_arm(arm, it["other_len"], it["other_third"], it["weighted"])
                if opp is not None:
                    _set_arm(kp, 1 - side, *opp)
        for fc in self.curves.values():
            fc.id_data.update_tag()

    def restore(self):
        for fc, i, co, left, right, types in self.saved.values():
            kp = fc.keyframe_points[i]       # looked up again: an update may move the key array
            _set_types(kp, types)
            kp.co, kp.handle_left, kp.handle_right = co, left, right
        self.finish()

    def finish(self):
        for fc in self.curves.values():
            fc.update()
            fc.id_data.update_tag()


_MODES = (('SET', "Set", "Select only this handle"), ('TOGGLE', "Toggle", "Toggle this handle"),
          ('ADD', "Add", "Add this handle"))
_BUTTONS = (('LEFT', "Left", ""), ('MIDDLE', "Middle", ""))


def pick(context, handles, x, y):
    """Row of the handle end a press at region (x, y) picks: within ``CLICK_PX`` and closer than every key."""
    row = handles.nearest(x, y, CLICK_PX * _ui(context))
    if row is None:
        return None
    if _key_distance(context, context.space_data, context.region, x, y) <= handles.distance(row, x, y):
        return None
    return row


def on_scale_box(context, x, y):
    """True when a press at region (x, y) grabs a side / corner of the Scale Keys box (r)."""
    from . import graph_scale_box as sb
    try:
        box = sb.current_box(context)
    except (AttributeError, ReferenceError, RuntimeError):
        return False
    return box is not None and sb.hit(box, x, y, sb.HIT_PX * _ui(context)) is not None


def select_row(context, handles, row, mode):
    """Apply a click on a handle (Maya rules). Returns True when the selection changed."""
    fc, i, side = handles.row(row)
    kp = fc.keyframe_points[i]
    name = _flag(side)
    was = bool(getattr(kp, name)) and not kp.select_control_point
    if mode == 'TOGGLE':
        setattr(kp, name, not was)
        if not was:
            fc.select = True
        return True
    if mode == 'SET' and was:
        return False                    # an already selected handle keeps the selection
    if mode == 'SET':
        deselect_all(context)
    if kp.select_control_point:         # the key's own selection would carry both handles along
        kp.select_control_point = False
        kp.select_left_handle = kp.select_right_handle = False
    setattr(kp, name, True)
    fc.select = True
    return True


class ALLSET_OT_graph_handle_drag(bpy.types.Operator):
    """Select and drag a tangent handle in the Graph Editor (a non-weighted tangent only turns)"""
    bl_idname = "allset.graph_handle_drag"
    bl_label = "Drag Tangent"
    bl_options = {'UNDO', 'INTERNAL'}

    button: EnumProperty(items=_BUTTONS, options={'SKIP_SAVE'})
    mode: EnumProperty(items=_MODES, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        from ..ui import graph_handles
        if self.button == 'LEFT':
            _PRESS.clear()
        if not graph_move._graph_window(context):
            return {'PASS_THROUGH'}
        try:
            handles = graph_handles.current(context)
        except (AttributeError, ReferenceError, RuntimeError, ValueError):
            handles = None
        if handles is None or not len(handles):
            return {'PASS_THROUGH'}
        region = context.region
        x, y = event.mouse_x - region.x, event.mouse_y - region.y
        changed = False
        if self.button == 'LEFT':
            if on_scale_box(context, x, y):
                return {'PASS_THROUGH'}         # the Scale Keys box's side / corner wins
            row = pick(context, handles, x, y)
            if row is None:
                remember_press(context, handles)        # a marquee may follow
                return {'PASS_THROUGH'}
            changed = select_row(context, handles, row, self.mode)
            if self.mode == 'TOGGLE':
                _redraw(context)
                return {'FINISHED'}
            handles = graph_handles.current(context)
        else:
            if graph_move.key_tool(context) != 'MOVE':
                return {'PASS_THROUGH'}
            if any(kp.select_control_point for fc in _editable(context) for kp in fc.keyframe_points):
                return {'PASS_THROUGH'}         # keys selected: the key drag moves them
        rows = [r for r in range(len(handles)) if handles.selected[r]]
        self._drag = Drag(context, handles, rows)
        if not self._drag:
            if changed:
                _redraw(context)
                return {'FINISHED'}
            return {'PASS_THROUGH'}
        self._region = region
        self._press = (x, y)
        self._changed = changed
        self._moved = False
        self._release = 'LEFTMOUSE' if self.button == 'LEFT' else 'MIDDLEMOUSE'
        self._drag_px = max(1, context.preferences.inputs.drag_threshold_mouse) * _ui(context) \
            if self.button == 'LEFT' else 0
        context.window_manager.modal_handler_add(self)
        _redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            if self._moved:
                self._drag.restore()
            _redraw(context)
            return {'FINISHED'} if self._changed and not self._moved else {'CANCELLED'}
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            x, y = event.mouse_x - self._region.x, event.mouse_y - self._region.y
            dx, dy = x - self._press[0], y - self._press[1]
            if not self._moved and max(abs(dx), abs(dy)) < self._drag_px:
                return {'RUNNING_MODAL'}        # not a drag yet: a click stays a click
            self._moved = True
            self._drag.apply(dx, dy)
            _redraw(context)
            return {'RUNNING_MODAL'}
        if event.type == self._release and event.value == 'RELEASE':
            if self._moved:
                self._drag.finish()
            _redraw(context)
            return {'FINISHED'} if (self._moved or self._changed) else {'CANCELLED'}
        return {'RUNNING_MODAL'}


# --- marquee: handle ends inside the box ------------------------------------------------------------------------

_PENDING = {}
_PRESS = {}


def remember_press(context, handles):
    """What a marquee starting at this press needs from before Blender's click (it deselects, and On Active Keys
    then hides the handles)."""
    from . import select_2d
    _PRESS.clear()
    _PRESS.update(area=context.area.as_pointer(), handles=handles, before=selected_handles(handles),
                  keys_before=select_2d.key_state())


def box_rows(handles, xmin, ymin, xmax, ymax):
    """Rows whose handle end lies inside the region-pixel box."""
    e = handles.end_px
    if not len(e):
        return []
    inside = (e[:, 0] >= xmin) & (e[:, 0] <= xmax) & (e[:, 1] >= ymin) & (e[:, 1] <= ymax)
    return [int(r) for r in inside.nonzero()[0]]


def apply_box(handles, rows, mode, before=None):
    """Handles inside a marquee: SET / ADD select, SUB deselect, XOR toggle against ``before`` ({(curve pointer,
    key index, side)} selected before the box), KEEP = as in ``before``. Returns the number changed."""
    n = 0
    for r in rows:
        fc, i, side = handles.row(r)
        kp = fc.keyframe_points[i]
        if kp.select_control_point:
            continue                    # its key is selected: the handle moves with it
        name = _flag(side)
        if mode == 'SUB':
            on = False
        elif mode == 'KEEP':
            on = (fc.as_pointer(), i, side) in (before or ())
        elif mode == 'XOR':
            on = (fc.as_pointer(), i, side) not in (before or ())
        else:
            on = True
        if bool(getattr(kp, name)) != on:
            setattr(kp, name, on)
            n += 1
    return n


def keys_in_box(key_px, xmin, ymin, xmax, ymax):
    return {k for k, (x, y) in key_px.items() if xmin <= x <= xmax and ymin <= y <= ymax}


def box_key_rule(mode, before, inside):
    """Keys a marquee that caught handle ends leaves selected: only the keys inside it count (Blender would take a
    whole curve the box merely crosses)."""
    if mode == 'SUB':
        return before - inside
    if mode == 'ADD':
        return before | inside
    return set(inside)


def box_keys(p, props):
    """Put the key selection to the Maya rule after a marquee that caught handle ends. Returns 1 when changed."""
    from . import select_2d
    items = select_2d.key_items()
    inside = keys_in_box(p["key_px"], props.xmin, props.ymin, props.xmax, props.ymax)
    want = box_key_rule(p["mode"], set(p["keys_before"]), inside)
    if set(select_2d.key_state(items)) == want:
        return 0
    select_2d.set_key_state(frozenset(want), items)
    return 1


def selected_handles(handles):
    return {(handles.fcurves[int(handles.curves[r])].as_pointer(), int(handles.keys[r]), int(handles.sides[r]))
            for r in range(len(handles)) if handles.selected[r]}


def _finish_box():
    from .. import live_refs
    p = _PENDING.get("box")
    if p is None:
        return None
    wm = bpy.context.window_manager
    running = any(op.bl_idname == "GRAPH_OT_select_box" for w in wm.windows for op in w.modal_operators)
    if not p["started"]:
        last = wm.operators[-1].as_pointer() if len(wm.operators) else 0
        p["started"] = running or last != p["last"]
        p["ticks"] += 1
        if not p["started"] and p["ticks"] < 40:
            return 0.02
    if running:
        return 0.02
    if p["mode"] == 'XOR':
        from . import select_2d
        if select_2d._PENDING.get("box") is not None and p["ticks"] < 80:
            p["ticks"] += 1
            return 0.02                 # the key toggle first: it clears the handles of keys it deselects
    _PENDING.pop("box", None)
    last = wm.operators[-1] if len(wm.operators) else None
    if last is None or last.as_pointer() == p["last"] or last.bl_idname != "GRAPH_OT_select_box":
        return None
    _win, area = live_refs.find_area(p["area"], p["window"])
    if area is None:
        return None
    props = last.properties
    handles = p["handles"]          # the handles shown at the press (On Active Keys hides them once deselected)
    try:
        rows = box_rows(handles, props.xmin, props.ymin, props.xmax, props.ymax)
        n = 0
        if rows and p["mode"] != 'XOR':
            n += box_keys(p, props)
        n += apply_box(handles, rows, p["mode"], p["before"])
        if p["mode"] == 'XOR':      # Blender ran the box as Set: handles outside it keep what they were
            inside = set(rows)
            outside = [r for r in range(len(handles)) if r not in inside]
            n += apply_box(handles, outside, 'KEEP', p["before"])
        if n:
            area.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, IndexError):
        pass
    return None


class ALLSET_OT_graph_handle_box(bpy.types.Operator):
    """The Graph Editor marquee also picks the tangent handle ends the kit draws (passes through to the marquee)"""
    bl_idname = "allset.graph_handle_box"
    bl_label = "Marquee Tangents"
    bl_options = {'INTERNAL'}

    mode: EnumProperty(items=(('SET', "Set", ""), ('XOR', "Toggle", ""), ('SUB', "Deselect", ""),
                              ('ADD', "Add", "")), options={'SKIP_SAVE'})

    def invoke(self, context, event):
        from ..ui import graph_handles
        if not graph_move._graph_window(context) or not graph_handles.owns(context.space_data):
            return {'PASS_THROUGH'}
        press = dict(_PRESS)
        _PRESS.clear()
        if press.get("area") != context.area.as_pointer() or not len(press["handles"]):
            return {'PASS_THROUGH'}
        handles = press["handles"]      # the handles shown at the press
        wm = context.window_manager
        _PENDING["box"] = {"mode": self.mode, "before": press["before"], "handles": handles,
                           "keys_before": press["keys_before"],
                           "key_px": graph_handles.key_positions(context, context.space_data, context.region),
                           "last": wm.operators[-1].as_pointer() if len(wm.operators) else 0,
                           "started": False, "ticks": 0, "window": context.window.as_pointer(),
                           "area": context.area.as_pointer()}
        if not bpy.app.timers.is_registered(_finish_box):
            bpy.app.timers.register(_finish_box, first_interval=0.02)
        return {'PASS_THROUGH'}


classes = (ALLSET_OT_graph_handle_drag, ALLSET_OT_graph_handle_box)


def unregister_timers():
    _PENDING.clear()
    _PRESS.clear()
    if bpy.app.timers.is_registered(_finish_box):
        bpy.app.timers.unregister(_finish_box)
