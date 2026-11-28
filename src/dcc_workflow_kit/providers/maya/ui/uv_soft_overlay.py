# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya soft select colours in the UV Editor (#579), like the 3D View's (ui/soft_overlay.py).

With soft select on, every UV a UV Move / Rotate / Scale will move gets Maya's soft select colour (yellow at weight
1, red at 0.5, black at 0) on its UV edges and, in vertex (UV) select mode, its point, so the falloff radius shows
before the drag.

Weights = Blender's UV transform rule, so the colours show what the drag will move:
- distances are taken in UV space stretched by the image's aspect (the transform's ``aspect``: image size x pixel
  aspect, the smaller side 1; no image = square);
- without Connected: straight distance to the nearest selected UV of any mesh in edit mode;
- with Connected: the shortest path through the shown UV faces: a step goes from a face corner to any other corner
  of the same face, and corners of one vertex at the same UV with the same selection state are one point;
- falloff curve and radius = the scene's (``soft_select.falloff``); only the faces the UV Editor shows take part.

A UV selection change with UV Sync off sends no depsgraph update: the selection is read again when the UV Editor
signals a selection change (``uv_arrays.selection_epoch``), and the weights are worked out again only when it (or the
radius, falloff, Connected, aspect, mesh) changed. While a UV
drag runs the mesh is not walked (operators/uv_arrays.EDIT_MODALS): the coloured UVs follow the drag from the
loops kept before it, with the weights of the drag's start, like the transform itself.
"""

import bmesh
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from ..operators import soft_select, uv_arrays

LINE_PX = 2.0
POINT_PX = 5.0
IMG_SIZE_FALLBACK = 256

_handle = []
_cache = {}            # object pointer -> _State
STATS = {"weights": 0}


class _State:
    __slots__ = ("arrays", "key", "w", "loops", "seg", "pts", "bm_loops", "uv_layer", "bm")

    def __init__(self):
        self.arrays = None
        self.key = None
        self.w = None
        self.loops = None          # shown loops (corner indices), the order of ``w``
        self.seg = None            # (2N,) local indices: drawn edge ends
        self.pts = None            # local indices: drawn points
        self.bm_loops = None       # BMLoops of the shown loops (drag follow), or None
        self.uv_layer = None       # their BMesh UV layer
        self.bm = None             # the BMesh kept too: its loops stay valid while it lives


# --- weights (pure: tests/test_issue579_uv_soft.py) ----------------------------------------------------------

def uv_aspect(space):
    """Blender's UV transform aspect for an Image Editor ``space``: (x, y), the smaller one 1."""
    img = getattr(space, "image", None)
    ax = ay = 1.0
    w = h = IMG_SIZE_FALLBACK
    if img is not None:
        da = tuple(img.display_aspect)
        if da[0] > 0 and da[1] > 0:
            ax, ay = 1.0, da[1] / da[0]
        size = tuple(img.size)
        if size[0] > 0 and size[1] > 0:
            w, h = size
    ax *= w
    ay *= h
    if ax < ay:
        return 1.0, ay / ax
    return ax / ay, 1.0


def connect_pairs(a, loops, picked):
    """(m, 2) local index pairs of the Connected graph over the shown ``loops`` (both directions): every two corners
    of a face, and corners of one vertex at the same UV with the same selection state (length 0)."""
    n = len(loops)
    pos = np.full(len(a.corner_vert), -1, np.int64)
    pos[loops] = np.arange(n)
    faces = np.unique(a.corner_face[loops])
    out = []
    sizes = a.loop_total[faces]
    for size in np.unique(sizes).tolist():
        fs = faces[sizes == size]
        corners = pos[a.loop_start[fs][:, None] + np.arange(size)[None, :]]      # (F, size) local
        i, j = np.nonzero(~np.eye(size, dtype=bool))
        out.append(np.stack((corners[:, i].reshape(-1), corners[:, j].reshape(-1)), axis=1))
    # same vertex, same UV, same selection state: consecutive rows after sorting
    uv = a.uv[loops]
    order = np.lexsort((picked.astype(np.int64), uv[:, 1], uv[:, 0], a.corner_vert[loops]))
    v, u, s = a.corner_vert[loops][order], uv[order], picked[order]
    same = (v[1:] == v[:-1]) & np.all(u[1:] == u[:-1], axis=1) & (s[1:] == s[:-1])
    p, q = order[:-1][same], order[1:][same]
    out.append(np.stack((p, q), axis=1))
    out.append(np.stack((q, p), axis=1))
    pairs = np.concatenate(out) if out else np.zeros((0, 2), np.int64)
    return pairs[(pairs[:, 0] >= 0) & (pairs[:, 1] >= 0)]


def _graph_distances(co, sel, radius, pairs):
    """Shortest path length from the selection along ``pairs`` (to, from), worked out inside the radius ball."""
    near = soft_select.distances(co, sel, radius) <= radius
    d = np.full(len(co), np.inf)
    d[sel] = 0.0
    e = pairs[near[pairs[:, 0]] & near[pairs[:, 1]]]
    if not len(e):
        return d
    elen = np.linalg.norm(co[e[:, 0]] - co[e[:, 1]], axis=1)
    changed = sel.copy()
    for _ in range(100000):
        live = changed[e[:, 1]]
        if not live.any():
            break
        new = d.copy()
        np.minimum.at(new, e[live, 0], d[e[live, 1]] + elen[live])
        new[sel] = 0.0
        changed = new < d - 1e-12
        d = new
    return d


def loop_weights(parts, radius, kind, connected, aspect):
    """Weights per shown loop for each of ``parts`` = [(arrays, shown loops, picked per shown loop)]: a list of
    arrays in the same order. Selected UVs 1, beyond the radius 0."""
    asp = np.asarray(aspect, dtype=np.float64)
    cos = [a.uv[loops] * asp for a, loops, _p in parts]
    sels = [np.asarray(p, dtype=bool) for _a, _l, p in parts]
    radius = max(float(radius), 1e-12)
    if connected:
        ds = [_graph_distances(co, sel, radius, connect_pairs(a, loops, sel)) if sel.any()
              else np.full(len(co), np.inf) for (a, loops, _p), co, sel in zip(parts, cos, sels)]
    else:
        co = np.concatenate(cos) if cos else np.zeros((0, 2))
        sel = np.concatenate(sels) if sels else np.zeros(0, bool)
        d = soft_select.distances(co, sel, radius)
        ds = np.split(d, np.cumsum([len(c) for c in cos])[:-1]) if cos else []
    out = []
    for d, sel in zip(ds, sels):
        w = np.zeros(len(d))
        inside = d <= radius
        w[inside] = soft_select.falloff((radius - d[inside]) / radius, kind)
        w[sel] = 1.0
        out.append(w)
    return out


# --- reading the edit meshes ---------------------------------------------------------------------------------

def _picked(a, bm, uv, shown, ts):
    from . import uv_manipulator
    return uv_manipulator._picked_loops(a, bm, uv, shown, ts.use_uv_select_sync, ts)


def _bm_loops(a, bm, shown):
    kept = getattr(a, "_uv_loops", None)
    if kept is not None and kept[0] is bm and np.array_equal(kept[1], shown) and (not kept[3]
                                                                                     or kept[3][0].is_valid):
        return kept[3]
    bm.faces.ensure_lookup_table()
    fs = bm.faces
    return [l for i in np.nonzero(shown)[0].tolist() for l in fs[i].loops]


def _vertex_mode(ts):
    if ts.use_uv_select_sync:
        return bool(ts.mesh_select_mode[0])
    return ts.uv_select_mode == 'VERTEX'


def _redraw_uv_editors():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.tag_redraw()
    return None


def selection_changed():
    """The UV selection may have changed (ui/uv_manipulator.ALLSET_GGT_uv_select_watch). The colours are drawn before
    the UV Editor's gizmos refresh, so with soft select on they are drawn once more with the new selection."""
    if soft_select.is_on() and not bpy.app.timers.is_registered(_redraw_uv_editors):
        bpy.app.timers.register(_redraw_uv_editors, first_interval=0.0)


def _refresh(context, space):
    """Weights of every mesh in edit mode, worked out again only when something they depend on changed."""
    ts = context.scene.tool_settings
    sync = ts.use_uv_select_sync
    depsgraph = context.view_layer.depsgraph
    if not space.show_gizmo:
        uv_arrays.selection_changed()     # gizmos hidden: no refresh signal from this editor, read every time
    parts, states = [], []
    for ob in getattr(context, "objects_in_mode_unique_data", None) or ():
        if ob.type != 'MESH':
            continue
        bm = bmesh.from_edit_mesh(ob.data)
        uv = bm.loops.layers.uv.active
        if uv is None:
            continue
        a = uv_arrays.read(ob, bm, uv, depsgraph, cached=True)
        shown = uv_arrays.shown_faces(a, sync)
        loops = np.nonzero(np.repeat(shown, a.loop_total))[0]
        picked = _picked(a, bm, uv, shown, ts)[loops]
        st = _cache.get(ob.as_pointer())
        if st is None:
            st = _cache[ob.as_pointer()] = _State()
        parts.append((a, loops, picked))
        states.append((st, a, bm, uv, shown, loops, picked))
    for ptr in set(_cache) - {st_ptr for st_ptr, st in _cache.items() if any(st is x[0] for x in states)}:
        del _cache[ptr]        # meshes no longer in edit mode
    key = (tuple((id(a), hash(p.tobytes())) for a, _l, p in parts), float(ts.proportional_size),
           ts.proportional_edit_falloff, bool(ts.use_proportional_connected), uv_aspect(space))
    if all(st.arrays is s_a and st.key == key for st, s_a, *_r in states) and states:
        return [st for st, *_r in states]
    ws = loop_weights(parts, ts.proportional_size, ts.proportional_edit_falloff, ts.use_proportional_connected,
                      uv_aspect(space))
    STATS["weights"] += 1
    for (st, a, bm, uv, shown, loops, picked), w in zip(states, ws):
        st.arrays, st.key, st.w, st.loops, st.uv_layer, st.bm = a, key, w, loops, uv, bm
        on = w > 0.0
        nxt_local = np.searchsorted(loops, a.corner_next[loops])
        m = on | on[nxt_local]
        st.seg = np.stack((np.nonzero(m)[0], nxt_local[m]), axis=1).reshape(-1)
        st.pts = np.nonzero(on)[0]
        st.bm_loops = _bm_loops(a, bm, shown) if on.any() else None
    return [st for st, *_r in states]


def _follow(states):
    """UV positions during a drag, read only from the kept loops of the drawn UVs; None when they are gone."""
    out = []
    for st in states:
        if st.bm_loops is None:
            out.append(None)
            continue
        if not st.bm_loops or not st.bm_loops[0].is_valid:
            return None
        pts = np.zeros((len(st.w), 2), np.float64)
        bm_loops, layer = st.bm_loops, st.uv_layer
        for i in np.unique(np.concatenate((st.seg, st.pts))).tolist():
            pts[i] = bm_loops[i][layer].uv
        out.append(pts)
    return out


# --- drawing ---------------------------------------------------------------------------------------------------

def _shader(names):
    for n in names:
        try:
            return gpu.shader.from_builtin(n)
        except (ValueError, TypeError):
            continue
    return None


def _draw():
    context = bpy.context
    if context.mode != 'EDIT_MESH' or not soft_select.is_on():
        return
    ts = context.scene.tool_settings
    if not ts.use_proportional_edit:
        return
    space, region = context.space_data, context.region
    if space is None or space.mode != 'UV' or not space.uv_editor.show_uv or region is None:
        return
    from .uv_display import to_region
    wm = context.window_manager
    try:
        v2d = region.view2d
        p0 = v2d.view_to_region(0.0, 0.0, clip=False)
        p1 = v2d.view_to_region(1.0, 1.0, clip=False)
        if uv_arrays.editing_now(wm):
            from .uv_display import _only_follow_modals
            if not _only_follow_modals(wm):
                return
            states = [st for st in _cache.values() if st.w is not None]
            positions = _follow(states)
            if positions is None:
                return
        else:
            states = _refresh(context, space)
            positions = [st.arrays.uv[st.loops] for st in states]
        lines = _shader(('POLYLINE_SMOOTH_COLOR',))
        points = _shader(('POINT_FLAT_COLOR', 'FLAT_COLOR'))
        scale = context.preferences.system.ui_scale or 1.0
        vertex_mode = _vertex_mode(ts)
        gpu.state.blend_set('ALPHA')
        for st, uvs in zip(states, positions):
            if uvs is None or st.w is None or not len(st.pts):
                continue
            rgba = np.concatenate([soft_select.ramp(st.w), np.ones((len(st.w), 1))], axis=1).astype(np.float32)
            px = to_region(uvs, p0, p1)
            if len(st.seg) and lines is not None:
                lines.bind()
                lines.uniform_float("viewportSize", (region.width, region.height))
                lines.uniform_float("lineWidth", LINE_PX * scale)
                batch_for_shader(lines, 'LINES', {"pos": px[st.seg], "color": rgba[st.seg]}).draw(lines)
            if vertex_mode and points is not None:
                points.bind()
                gpu.state.point_size_set(POINT_PX * scale)
                batch_for_shader(points, 'POINTS', {"pos": px[st.pts], "color": rgba[st.pts]}).draw(points)
                gpu.state.point_size_set(1.0)
        gpu.state.blend_set('NONE')
    except (ReferenceError, AttributeError, ValueError):
        _cache.clear()


def register():
    _handle.append(bpy.types.SpaceImageEditor.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL'))


def unregister():
    if bpy.app.timers.is_registered(_redraw_uv_editors):
        bpy.app.timers.unregister(_redraw_uv_editors)
    while _handle:
        bpy.types.SpaceImageEditor.draw_handler_remove(_handle.pop(), 'WINDOW')
    _cache.clear()
