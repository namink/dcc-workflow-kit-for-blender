# SPDX-License-Identifier: GPL-3.0-or-later
"""The Graph Editor Select menu's pick masks (All / Only Curve; Curve / Key / In / Out Tangent) kept as add-on
preferences: a timer (``_mask_tick``) drops what a click or drag just selected against the masks (``mask_step``);
``remember_masks`` takes the current selection as the new baseline. ``_prefs`` = the kit's add-on preferences or
None. graph_key_menu.register_bindings registers the timer and the load handler and re-exports these names.
"""

import bpy


def _prefs():
    from .. import preferences
    try:
        return preferences.get()
    except (KeyError, AttributeError):
        return None


# --- Select masks -------------------------------------------------------------------------------------------

MASKS = ("graph_select_curve", "graph_select_key", "graph_select_in", "graph_select_out")
_mask = {"last": None}
MASK_POLL = 0.05


def masks():
    p = _prefs()
    if p is None:
        return (True, True, True, True)
    return tuple(bool(getattr(p, m)) for m in MASKS)


def _flags(fc):
    import numpy as np
    n = len(fc.keyframe_points)
    out = []
    for attr in ("select_control_point", "select_left_handle", "select_right_handle"):
        a = np.empty(n, dtype=bool)
        fc.keyframe_points.foreach_get(attr, a)
        out.append(a)
    return out


def _curves(scene):
    from .. import compat
    for ob in scene.objects:
        if ob is None:
            continue
        for fc in compat.id_fcurves(ob):
            yield ob, fc


def _signature(scene):
    return {(ob.name, fc.data_path, fc.array_index): _flags(fc) for ob, fc in _curves(scene)}


def mask_step(scene, curve, key, tin, tout):
    """One poll: drop what the last selection added against the masks. Returns how many curves changed."""
    if curve and key and tin and tout:
        _mask["last"] = None
        return 0
    last = _mask["last"]
    changed = 0
    now = {}
    for ob, fc in _curves(scene):
        k = (ob.name, fc.data_path, fc.array_index)
        flags = _flags(fc)
        prev = last.get(k) if last else None
        if prev is not None and len(prev[0]) == len(flags[0]):
            ctrl_new = flags[0] & ~prev[0]
            left_new = flags[1] & ~prev[1]
            right_new = flags[2] & ~prev[2]
            hit = False
            pts = fc.keyframe_points
            if not key and ctrl_new.any():
                if curve:       # Maya curve pick: the whole curve
                    pts.foreach_set("select_control_point", [True] * len(pts))
                else:
                    for i in ctrl_new.nonzero()[0]:
                        pts[int(i)].select_control_point = False
                hit = True
            if not tin and left_new.any():
                for i in left_new.nonzero()[0]:
                    pts[int(i)].select_left_handle = False
                hit = True
            if not tout and right_new.any():
                for i in right_new.nonzero()[0]:
                    pts[int(i)].select_right_handle = False
                hit = True
            if hit:
                changed += 1
                flags = _flags(fc)
        now[k] = flags
    _mask["last"] = now
    return changed


def remember_masks(scene=None):
    scene = scene or bpy.context.scene
    _mask["last"] = _signature(scene) if scene else None


def _graph_open():
    wm = bpy.context.window_manager
    return any(a.type == 'GRAPH_EDITOR' for w in wm.windows for a in w.screen.areas)


def _mask_tick():
    try:
        scene = bpy.context.scene
        m = masks()
        if scene is not None and not all(m) and _graph_open():
            if mask_step(scene, *m):
                for w in bpy.context.window_manager.windows:
                    for a in w.screen.areas:
                        if a.type in {'GRAPH_EDITOR', 'DOPESHEET_EDITOR'}:
                            a.tag_redraw()
        else:
            _mask["last"] = None
    except (KeyError, AttributeError, ReferenceError):
        pass
    return MASK_POLL


@bpy.app.handlers.persistent
def _mask_reset(*_args):
    _mask["last"] = None
