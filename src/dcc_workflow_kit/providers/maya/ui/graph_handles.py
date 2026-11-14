# SPDX-License-Identifier: GPL-3.0-or-later
"""Graph Editor tangent handles like Maya (#296).

Maya draws a non-weighted tangent at a fixed length on screen (``FIXED_PX`` at UI scale 1) along the tangent's
direction, whatever the zoom and however steep it is; a weighted tangent ends at its real control point. Unselected
tangent lines are grey, selected ones white.

Blender draws every handle at its control point and can't hide them per curve, so while the kit's editor chrome is
on (and the add-on pref ``graph_fixed_tangents``) the kit takes over handle display in every Graph Editor showing
F-Curves: the editor's own Show Handles value moves into the kit (``_owned``, by space pointer) and
``space.show_handles`` is set off; the kit draws the handles (``ui/graph_keys_draw.py``) and picks / drags them
(``operators/graph_handle_drag.py``). The value goes back to the editor when the editor leaves F-Curves mode, the
pref or Maya mode goes off, and around every file save (so a saved file keeps the user's value). Turning Blender's
own Show Handles back on (its View menu) counts as the kit value turning on.

Display rule (``display_ends``): from the key in region pixels, along the arm's direction (frame, display value
mapped to pixels), ``FIXED_PX`` x UI scale long for a non-weighted curve; the real handle for a weighted one. An arm
with no length points along time (left: back, right: forward).
"""

import math

import bpy
import numpy as np
from bpy.app.handlers import persistent
from bpy.props import EnumProperty

FIXED_PX = 50.0                     # non-weighted tangent length on screen at UI scale 1
LINE_RGBA = (0.55, 0.55, 0.55, 1.0)       # unselected tangent line (grey)
LINE_SEL_RGBA = (1.0, 1.0, 1.0, 1.0)      # selected tangent line (white)
SYNC = 0.1                          # s between editor checks

_owned = {}                         # SpaceGraphEditor pointer -> the editor's own Show Handles value
_state = {"saving": False}


# --- which editors the kit draws handles for --------------------------------------------------------------------

def feature_on(context=None):
    from .. import preferences
    from . import editor_chrome
    context = context or bpy.context
    try:
        return bool(editor_chrome.enabled(context)) and bool(preferences.get(context).graph_fixed_tangents)
    except (KeyError, AttributeError):
        return False


def _ptr(space):
    fn = getattr(space, "as_pointer", None)
    return fn() if fn is not None else None


def owns(space):
    """True when the kit draws and picks this editor's handles."""
    return space is not None and _ptr(space) in _owned


def shows_handles(space):
    """The editor's Show Handles as the user sees it (the kit's value while the kit owns the editor)."""
    p = _ptr(space)
    if p is not None and p in _owned:
        return bool(_owned[p])
    return bool(getattr(space, "show_handles", True))


def set_shows_handles(space, on):
    p = _ptr(space)
    if p is not None and p in _owned:
        _owned[p] = bool(on)
    else:
        space.show_handles = bool(on)
    _redraw_graphs()


def _graph_spaces():
    wm = getattr(bpy.context, "window_manager", None)
    for window in wm.windows if wm is not None else ():
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            for space in area.spaces:
                if space.type == 'GRAPH_EDITOR':
                    yield space


def sync(context=None):
    """Take over / give back each Graph Editor's handles. Returns the number of editors changed."""
    on = feature_on(context) and not _state["saving"]
    changed, seen = 0, set()
    for space in _graph_spaces():
        p = space.as_pointer()
        seen.add(p)
        want = on and space.mode == 'FCURVES'
        if want:
            if p not in _owned:
                _owned[p] = bool(space.show_handles)
                changed += 1
            elif space.show_handles:            # Blender's own Show Handles turned on
                _owned[p] = True
                changed += 1
            if space.show_handles:
                space.show_handles = False
        elif p in _owned:
            space.show_handles = _owned.pop(p)
            changed += 1
    for p in [p for p in _owned if p not in seen]:     # closed editors (freed pointers are reused)
        del _owned[p]
    if changed:
        _redraw_graphs()
    return changed


def release_all():
    """Every owned editor gets its own Show Handles back."""
    for space in _graph_spaces():
        p = space.as_pointer()
        if p in _owned:
            space.show_handles = _owned.pop(p)
    _owned.clear()


def _redraw_graphs():
    wm = getattr(bpy.context, "window_manager", None)
    for window in wm.windows if wm is not None else ():
        for area in window.screen.areas if window.screen else ():
            if area.type == 'GRAPH_EDITOR':
                area.tag_redraw()


def _tick():
    try:
        sync(bpy.context)
    except (AttributeError, ReferenceError, RuntimeError, KeyError):
        pass
    return SYNC


@persistent
def _save_pre(*_args):
    """A saved file keeps the editors' own Show Handles."""
    _state["saving"] = True
    for space in _graph_spaces():
        p = space.as_pointer()
        if p in _owned:
            space.show_handles = _owned[p]


@persistent
def _save_post(*_args):
    _state["saving"] = False
    for space in _graph_spaces():
        if space.as_pointer() in _owned:
            space.show_handles = False


@persistent
def _load_pre(*_args):
    _owned.clear()          # the next file's editors carry their own values


# --- Maya View > Tangents (Always / Never / On Active Keys) ------------------------------------------------------

TANGENT_ITEMS = (('ALWAYS', "Always", "Show the tangents of every key"),
                 ('NEVER', "Never", "Hide the tangents"),
                 ('ACTIVE', "On Active Keys", "Show the tangents of the selected keys only"))


def _tangents_get(_self):
    space = getattr(bpy.context, "space_data", None)
    if space is None or space.type != 'GRAPH_EDITOR':
        return 0
    if not shows_handles(space):
        return 1
    return 2 if space.use_only_selected_keyframe_handles else 0


def _tangents_set(_self, value):
    space = getattr(bpy.context, "space_data", None)
    if space is None or space.type != 'GRAPH_EDITOR':
        return
    if value == 1:
        set_shows_handles(space, False)
        return
    space.use_only_selected_keyframe_handles = value == 2
    set_shows_handles(space, True)


# --- geometry ---------------------------------------------------------------------------------------------------

def fixed_ends(keys_px, ends_px, sides, length):
    """Region-pixel ends of non-weighted arms: ``length`` px from each key along its arm (``ends_px`` = the real
    handle ends). ``sides`` = 0 left / 1 right per row: an arm with no length points back / forward in time."""
    keys_px = np.asarray(keys_px, dtype=np.float64).reshape(-1, 2)
    d = np.asarray(ends_px, dtype=np.float64).reshape(-1, 2) - keys_px
    n = np.hypot(d[:, 0], d[:, 1])
    flat = n < 1e-9
    sign = np.where(np.asarray(sides).reshape(-1) == 0, -1.0, 1.0)
    d[flat, 0] = sign[flat]
    d[flat, 1] = 0.0
    n[flat] = 1.0
    return keys_px + d / n[:, None] * length


def fixed_px(context):
    return FIXED_PX * (context.preferences.system.ui_scale or 1.0)


class Handles:
    """The handles Blender would show in one Graph Editor region, in region pixels (kit display rule).

    Rows (numpy, one per shown handle): ``curves`` (index into ``fcurves``), ``keys`` (key index), ``sides`` (0 left,
    1 right), ``key_px``, ``end_px`` (where the handle is drawn), ``selected`` (handle flag set while its key isn't
    selected: Blender sets a key's handle flags with the key), ``weighted``."""

    def __init__(self, context, space, region, keys=None):
        from . import graph_keys_draw as gk
        from ..operators import graph_weights
        self.fcurves, self.factors = [], []
        if not shows_handles(space):
            self._empty()
            return
        if keys is None or not keys.handles:
            keys = gk.Keys(context, space, handles=True)
        near_selected = bool(getattr(space, "use_only_selected_keyframe_handles", False))
        left_on, right_on = keys.handle_sides(near_selected)
        rows, sides = keys.handle_rows(left_on, right_on)
        if not len(rows):
            self._empty()
            return
        # the curves with a shown handle, in Blender's order: ``curves`` indexes into them
        curve_of = keys.curve_of_key()
        shown = np.unique(curve_of[rows])
        index = np.full(len(keys.fcurves), -1, dtype=int)
        index[shown] = np.arange(len(shown))
        self.fcurves = [keys.fcurves[i] for i in shown]
        self.factors = [keys.factors[i] for i in shown]
        weighted = np.array([graph_weights.is_weighted(fc) for fc in self.fcurves], dtype=bool)
        self.curves = index[curve_of[rows]]
        self.keys = (rows - keys.start[curve_of[rows]]).astype(int)
        self.sides = sides
        self.weighted = weighted[self.curves]
        self.key_px = gk.to_region(region, keys.co[rows])
        self.end_px = gk.to_region(region, keys.handle_ends(rows, sides))
        loose = ~self.weighted
        if loose.any():
            self.end_px[loose] = fixed_ends(self.key_px[loose], self.end_px[loose], sides[loose], fixed_px(context))
        picked = np.where(sides == 0, keys.select_left[rows], keys.select_right[rows])
        self.selected = (picked & ~keys.select[rows]).astype(bool)

    def _empty(self):
        for name in ("curves", "keys", "sides", "selected", "weighted"):
            setattr(self, name, np.zeros(0, dtype=int))
        self.key_px, self.end_px = np.zeros((0, 2)), np.zeros((0, 2))
        self.selected = self.selected.astype(bool)
        self.weighted = self.weighted.astype(bool)

    def __len__(self):
        return len(self.keys)

    def nearest(self, x, y, tol):
        """Row of the handle end nearest region (x, y) within ``tol`` px, else None."""
        if not len(self):
            return None
        d = np.hypot(self.end_px[:, 0] - x, self.end_px[:, 1] - y)
        i = int(np.argmin(d))
        return i if d[i] <= tol else None

    def distance(self, row, x, y):
        return math.hypot(self.end_px[row, 0] - x, self.end_px[row, 1] - y)

    def row(self, i):
        """(F-curve, key index, side) of a row."""
        return self.fcurves[int(self.curves[i])], int(self.keys[i]), int(self.sides[i])


def key_positions(context, space, region):
    """{(F-curve pointer, key index): (x, y)} region pixels of the keys the Graph Editor draws."""
    from . import graph_keys_draw as gk
    from .graph_layers import normalization, value_factor
    scene = context.scene
    only_selected = bool(getattr(context.preferences.edit, "show_only_selected_curve_keyframes", False))
    normalize = bool(getattr(space, "use_normalization", False))
    tweak = gk._owners(scene)
    out = {}
    for fc in getattr(context, "visible_fcurves", None) or ():
        if not gk.draws_keys(fc, only_selected):
            continue
        n = len(fc.keyframe_points)
        co = np.empty(n * 2, dtype=np.float64)
        fc.keyframe_points.foreach_get("co", co)
        co = co.reshape(n, 2)
        off, k = normalization(fc) if normalize else (0.0, value_factor(scene, fc))
        co[:, 1] = (co[:, 1] + off) * k
        ad = tweak.get(fc.id_data.as_pointer()) if fc.id_data is not None else None
        if ad is not None:
            co[:, 0] = [ad.nla_tweak_strip_time_to_scene(x) for x in co[:, 0]]
        px = gk.to_region(region, co)
        p = fc.as_pointer()
        for i in range(n):
            out[(p, i)] = (float(px[i, 0]), float(px[i, 1]))
    return out


def current(context):
    """Handles of the Graph Editor region in ``context`` while the kit owns it, else None."""
    space, region = getattr(context, "space_data", None), getattr(context, "region", None)
    if space is None or region is None or space.type != 'GRAPH_EDITOR' or region.type != 'WINDOW' \
            or space.mode != 'FCURVES' or not owns(space):
        return None
    return Handles(context, space, region)


# --- register ---------------------------------------------------------------------------------------------------

_HANDLERS = (("save_pre", _save_pre), ("save_post", _save_post), ("load_pre", _load_pre))


def register():
    bpy.types.WindowManager.allset_graph_tangents = EnumProperty(
        name="Tangents", items=TANGENT_ITEMS, get=_tangents_get, set=_tangents_set,
        description="Which tangents the Graph Editor shows (Maya View > Tangents)")
    for name, fn in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn not in handlers:
            handlers.append(fn)
    _state["saving"] = False
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=SYNC, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    for name, fn in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn in handlers:
            handlers.remove(fn)
    try:
        release_all()
    except (AttributeError, ReferenceError):
        _owned.clear()
    _state["saving"] = False
    if hasattr(bpy.types.WindowManager, "allset_graph_tangents"):
        del bpy.types.WindowManager.allset_graph_tangents
