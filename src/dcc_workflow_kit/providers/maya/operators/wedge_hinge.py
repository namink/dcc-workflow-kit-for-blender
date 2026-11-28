# SPDX-License-Identifier: GPL-3.0-or-later
"""The edge Edit Mesh > Wedge turns the selected faces about (the hinge), kept and drawn like Maya's edge selection.

Maya keeps an edge selection when the selection mode changes to faces, so an edge picked first and a face added
after it (Shift+click in face mode) still give Wedge its hinge. Blender drops edges that are not part of a selected
face when it switches to face mode, so ``remember`` keeps them (vertex index pairs and their positions) per object
just before the switch (kit F11 / marking menu), ``follow_active`` keeps the active lone edge while edge mode is
drawn (any other route to face mode), and ``hinge_edge`` finds them again.

In edge mode a selected face's edges all draw as selected, so the edge picked on it (the active edge) can't be told
apart; ``draw_hinge`` draws the hinge Wedge would use (the active edge on a selected face, or a kept edge on the
border of the selected faces) as a thick line in the theme's active colour.
"""

import bmesh
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

# object name -> [((vert index, vert index), (co, co)), ...]
_kept = {}
_handles = []
LINE_PX = 4.0
_EPS = 1e-5


def clear(ob=None):
    if ob is None:
        _kept.clear()
    else:
        _kept.pop(ob.name, None)


def remember(context):
    """Keep the picked edges of every mesh in Edit Mode (the active edge first, then the other selected edges that
    are not part of a selected face). Called just before the selection mode changes to faces."""
    for ob in context.objects_in_mode_unique_data:
        if ob.type != 'MESH':
            continue
        bm = bmesh.from_edit_mesh(ob.data)
        picked = [e for e in bm.select_history if isinstance(e, bmesh.types.BMEdge) and e.select]
        picked.reverse()                                           # the newest pick first
        picked += [e for e in bm.edges if e.select and e not in picked and not any(f.select for f in e.link_faces)]
        if picked:
            _kept[ob.name] = [((e.verts[0].index, e.verts[1].index), (e.verts[0].co.copy(), e.verts[1].co.copy()))
                              for e in picked]
        else:
            _kept.pop(ob.name, None)


def _border(edge, faces):
    return sum(f in faces for f in edge.link_faces) == 1


def _kept_edges(ob, bm):
    out = []
    entries = _kept.get(ob.name) if ob is not None else None
    if not entries:
        return out
    bm.verts.ensure_lookup_table()
    n = len(bm.verts)
    for (i, j), (ci, cj) in entries:
        if i >= n or j >= n:
            continue
        a, b = bm.verts[i], bm.verts[j]
        if (a.co - ci).length > _EPS or (b.co - cj).length > _EPS:
            continue
        e = next((e for e in a.link_edges if e.other_vert(a) is b), None)
        if e is not None:
            out.append(e)
    return out


def _picked_edge(bm, faces):
    """The newest edge picked on its own and still selected on the border of ``faces`` (Multi-Component mode keeps
    the edge picked before a face in the pick list), or None."""
    for e in reversed(list(bm.select_history)):
        if isinstance(e, bmesh.types.BMEdge) and e.select and _border(e, faces):
            return e
    return None


def hinge_edge(ob, bm, faces, fallback=True):
    """The edge Wedge turns ``faces`` about: the active edge, else an edge picked before them still in the pick list
    (Multi-Component mode), else a kept edge on their border, else (``fallback``) a selected edge on their border."""
    edge = bm.select_history.active
    if isinstance(edge, bmesh.types.BMEdge):
        return edge
    sel = set(faces)
    e = _picked_edge(bm, sel)
    if e is not None:
        return e
    for e in _kept_edges(ob, bm):
        if _border(e, sel):
            return e
    if not fallback:
        return None
    return next((e for f in faces for e in f.edges if e.select and _border(e, sel)), None)


def follow_active(ob, bm, select_mode):
    """In edge mode alone, keep the active edge picked on its own (not part of a selected face) as it changes, so
    a switch to face mode by any route (the header's mode buttons too) still finds it; another active element (or
    none) drops it. Run on each viewport draw: one look at the active element."""
    if tuple(select_mode) != (False, True, False):
        return
    act = bm.select_history.active
    if isinstance(act, bmesh.types.BMEdge) and act.select and not any(f.select for f in act.link_faces):
        key = (act.verts[0].index, act.verts[1].index)
        entries = _kept.get(ob.name)
        if not entries or entries[0][0] != key or (entries[0][1][0] - act.verts[0].co).length > _EPS:
            _kept[ob.name] = [(key, (act.verts[0].co.copy(), act.verts[1].co.copy()))]
    elif ob.name in _kept:
        del _kept[ob.name]


def shown_hinge(ob, bm):
    """The hinge drawn for ``ob`` (``bm`` = its edit BMesh, kept alive by the caller), or None."""
    act = bm.select_history.active
    if isinstance(act, bmesh.types.BMEdge):
        # the active edge counts when it is one of a selected face's edges (else it already draws as picked)
        return act if act.select and any(f.select for f in act.link_faces) else None
    picked = [e for e in bm.select_history if isinstance(e, bmesh.types.BMEdge) and e.select]
    if ob.name not in _kept and not picked:
        return None
    faces = {f for e in _kept_edges(ob, bm) + picked for f in e.link_faces if f.select}
    return hinge_edge(ob, bm, list(faces), fallback=False) if faces else None


def draw_hinge():
    context = bpy.context
    try:
        if context.mode != 'EDIT_MESH':
            return
        pts = []
        select_mode = context.tool_settings.mesh_select_mode
        for ob in context.objects_in_mode_unique_data:
            if ob.type != 'MESH':
                continue
            bm = bmesh.from_edit_mesh(ob.data)
            follow_active(ob, bm, select_mode)
            e = shown_hinge(ob, bm)
            if e is not None:
                mw = ob.matrix_world
                pts += [tuple(mw @ e.verts[0].co), tuple(mw @ e.verts[1].co)]
        if not pts:
            return
        region = context.region
        rgba = tuple(context.preferences.themes[0].view_3d.editmesh_active)
        px = LINE_PX * (context.preferences.system.ui_scale or 1.0)
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        shader.uniform_float("viewportSize", (region.width, region.height))
        shader.uniform_float("lineWidth", px)
        shader.uniform_float("color", (*rgba[:3], 1.0))
        batch_for_shader(shader, 'LINES', {"pos": pts}).draw(shader)
        gpu.state.blend_set('NONE')
    except ReferenceError:
        return


def register_bindings():
    if not _handles:
        _handles.append(bpy.types.SpaceView3D.draw_handler_add(draw_hinge, (), 'WINDOW', 'POST_VIEW'))


def unregister_bindings():
    while _handles:
        bpy.types.SpaceView3D.draw_handler_remove(_handles.pop(), 'WINDOW')
    _kept.clear()
