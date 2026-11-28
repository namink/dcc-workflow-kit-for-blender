# SPDX-License-Identifier: GPL-3.0-or-later
"""Quad Draw hover previews (``allset.quad_draw_hover``, passes the event on): ``update_hover`` sets what Shift (fill),
Ctrl (loop), Ctrl+Shift (delete), Tab (border edge / corner) or nothing would act on; ``corner_vertex_at`` finds the
border corner vertex a Tab drag starts from. ``quad_draw_state`` draws the previews.
"""

import bmesh
import bpy

from . import poly_draw
from .quad_draw_geometry import corner_neighbours
from .quad_draw_state import (STATE, _mouse, _redraw, _ring_lines, _view_ok, component_at, edit_object, fill_plan,
                              loop_plan, topology_preview)


def _component_points(ob, comp):
    bm = bmesh.from_edit_mesh(ob.data)
    mw = ob.matrix_world
    kind, i = comp[0], comp[1]
    if kind == 'VERT':
        bm.verts.ensure_lookup_table()
        return [mw @ bm.verts[i].co]
    if kind == 'EDGE':
        bm.edges.ensure_lookup_table()
        return [mw @ v.co for v in bm.edges[i].verts]
    bm.faces.ensure_lookup_table()
    return [mw @ v.co for v in bm.faces[i].verts]


def corner_vertex_at(context, region, rv3d, mouse, ob):
    """Index of a border vertex of ``ob`` with two border edges under ``mouse`` (Tab+drag makes a quad there), or
    None."""
    comp = component_at(context, region, rv3d, mouse, ob)
    if comp is None or comp[0] != 'VERT':
        return None
    bm = bmesh.from_edit_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    if comp[1] >= len(bm.verts) or corner_neighbours(bm.verts[comp[1]]) is None:
        return None
    return comp[1]


def _corner_points(ob, vi):
    bm = bmesh.from_edit_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    v = bm.verts[vi]
    mw = ob.matrix_world
    return [(mw @ v.co, mw @ e.other_vert(v).co) for e in v.link_edges if e.is_boundary]


def update_hover(context, region, rv3d, mouse, ctrl, shift, tab=False):
    ob = edit_object(context)
    STATE["preview"] = None
    STATE['hover_component'] = None
    STATE['topology_hover']=None;STATE['topology_preview']=None
    STATE['delete_edges']=None;STATE['relax_area']=None
    if ob is None:
        return
    info=topology_preview(context,ob)
    if info is not None:info['hover_supported']=None
    if context.scene.allset_soft_select and not ctrl and not tab:
        from . import quad_draw_relax
        quad_draw_relax.preview(context,ob,mouse)
    if tab:
        vi = corner_vertex_at(context, region, rv3d, mouse, ob)
        if vi is not None:
            STATE["preview"] = ('EXTEND', [p for seg in _corner_points(ob, vi) for p in seg])
            return
        bm_edge = poly_draw.border_edge_at(context, region, rv3d, mouse, ob)
        if bm_edge is not None:
            STATE["preview"] = ('TAB', _component_points(ob, ('EDGE', bm_edge)))
        return
    if shift and not ctrl:
        plan = fill_plan(context, region, rv3d, mouse, ob)
        if plan is not None:
            STATE["preview"] = ('FILL', plan[1])
        return
    if ctrl and not shift:
        comp = component_at(context, region, rv3d, mouse, ob, edges_only=True)
        if comp is not None:
            from . import quad_draw_cut
            segs = quad_draw_cut.segments(bmesh.from_edit_mesh(ob.data), comp[1], comp[2])
            mw = ob.matrix_world
            STATE["preview"] = ('LOOP', [(mw @ a, mw @ b) for a, b in segs])
        return
    comp = component_at(context, region, rv3d, mouse, ob)
    if comp is not None:
        STATE["preview"] = ('DELETE' if ctrl else 'HOVER', _component_points(ob, comp))
        if ctrl and comp[0]=='EDGE':
            plan=loop_plan(context,ob,comp[1])
            STATE['preview']=('DELETE_LOOP',plan['points']);STATE['delete_edges']=(ob.name,plan['edges'])
        STATE['hover_component'] = (ob.name, *comp[:2])
        if info is not None:
            bm=bmesh.from_edit_mesh(ob.data);bm.verts.ensure_lookup_table();bm.edges.ensure_lookup_table();bm.faces.ensure_lookup_table()
            kind,i=comp[:2]
            indices=[i] if kind=='VERT' else [v.index for v in (bm.edges[i].verts if kind=='EDGE' else bm.faces[i].verts)]
            if all(i in info['pairs'] for i in indices):
                points=[ob.matrix_world@bm.verts[info['pairs'][i]].co for i in indices]
                STATE['topology_hover']=points if len(points)<3 else _ring_lines(points)
                info['hover_supported']=True
            else:info['hover_supported']=False


def _mods(event):
    ctrl = event.ctrl or (event.type in {'LEFT_CTRL', 'RIGHT_CTRL'} and event.value == 'PRESS')
    if event.type in {'LEFT_CTRL', 'RIGHT_CTRL'} and event.value == 'RELEASE':
        ctrl = False
    shift = event.shift or (event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value == 'PRESS')
    if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value == 'RELEASE':
        shift = False
    return bool(ctrl), bool(shift)


class ALLSET_OT_quad_draw_hover(bpy.types.Operator):
    """Quad Draw hover preview (passes the event on)"""
    bl_idname = "allset.quad_draw_hover"
    bl_label = "Quad Draw Preview"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def invoke(self, context, event):
        if _view_ok(context):
            ctrl, shift = _mods(event)
            try:
                update_hover(context, context.region, context.region_data, _mouse(event), ctrl, shift)
            except (ReferenceError, ValueError, IndexError, KeyError):
                STATE["preview"] = None
            _redraw(context)
        return {'PASS_THROUGH'}
