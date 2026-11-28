# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Quad Draw (Mesh Tools > Quad Draw, Ctrl+Shift+Q): retopology on a live surface
(GitHub #30).

The kit tool ``allset.quad_draw_tool`` (edit mode, ui/mesh_tools_poly.py) edits one mesh — the selected one, or a new
empty ``polySurfaceN`` (``allset.quad_draw_start``) — on the Make Live mesh list, or Maya's construction plane
when no surface is live. Unrelated visible meshes never participate.

- click = a dot on the surface; press-drag on a dot / vertex / edge / face = move it along the surface (Auto-weld:
  eligible points snap during the drag and weld on release); middle-drag = move too;
- Shift+click = fill: the polygon of the dots / border vertices around the mouse (4, else 3); Shift+drag = relax brush;
- Ctrl+click on an edge = edge loop there (new vertices on the surface);
- Ctrl+Shift+click = delete the dot / vertex / edge / face under the mouse;
- Tab held + drag from a border edge = extend it by a quad (Extend: Edge / Loop / Border), from a border vertex with two
  border edges = the quad of the vertex, its two border neighbours and the mouse point (an inner corner, #180), from
  empty space = a strip of quads Quad Strip Width pixels wide;
- hover previews (Shift: the fill, Ctrl: the loop, Ctrl+Shift: what goes, Tab: the border edge).
Pure parts (``fill_order``, ``fill_face``, ``extend_edges``, ``corner_quad``, ``strip_pairs``, ``relax``,
``delete_at``) live in ``quad_draw_geometry`` and are tested headless (tests/test_step144_poly.py).

Code: ``quad_draw_geometry`` (mesh and screen geometry, dots), ``quad_draw_surface`` (where points go on the live
surface), ``quad_draw_state`` (live state, what is under the mouse, preview drawing, the Retopology overlay, undo /
load resets), ``quad_draw_hover`` (hover previews), ``quad_draw_tab`` (Tab extend / strip), ``quad_draw_commands``
(start, exit, Clear Dots, Restore Modeling Display, Pick Topology Seam). This module keeps the main modal
(``allset.quad_draw``), ``classes`` and the handler registration; the names used elsewhere are importable from here
too, except the caches and ``_overlay_saving`` that ``quad_draw_state`` rebinds (read those on ``quad_draw_state``).
"""

import math

import bmesh
import bpy
from bpy.props import BoolProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from .. import compat
from . import preselect, quad_draw_symmetry
# the split-out parts, also read through this module by other operators, the UI and the tests
from .quad_draw_geometry import (DOT_LAYER, _area, _indices, add_dot, border_chain, border_loop,  # noqa: F401
                                 clear_dots, component_loop, corner_neighbours, corner_quad, delete_at, delete_loop,
                                 dots, edge_loop, extend_edges, fill_candidates, fill_face, fill_order, relax,
                                 strip_faces, strip_pairs, weld_target, width_preview)
from .quad_draw_surface import (_screen_xy, _surface_point, _ui_scale, _weld_px, place_point,  # noqa: F401
                                project_point, reference_objects, surface_hit, surface_offset)
from .quad_draw_state import (BRUSH_PX, DRAG_PX, STATE, TOOL, _begin_symmetry, _close_symmetry,  # noqa: F401
                              _commit_weld, _draw_pixel, _draw_view, _drop_dots, _file_reset, _geometry_reset,
                              _mouse, _overlay_save_post, _overlay_save_pre, _overlay_save_runtime, _overlay_space,
                              _overlay_values, _redraw, _reference_visible, _restore_inactive_overlays,
                              _restore_overlays, _restore_topology_state, _set_overlay_values, _sync_symmetry,
                              _view_ok, _watch, apply_fill, clear_topology_preview, component_at, edit_object,
                              fill_plan, loop_plan, reset_preview, sync_overlays, tool_active, topology_preview)
from .quad_draw_hover import ALLSET_OT_quad_draw_hover, update_hover  # noqa: F401
from .quad_draw_tab import TAB_HINT, ALLSET_OT_quad_draw_tab  # noqa: F401
from .quad_draw_commands import (ALLSET_OT_quad_draw_clear_dots, ALLSET_OT_quad_draw_exit,  # noqa: F401
                                 ALLSET_OT_quad_draw_pick_seam, ALLSET_OT_quad_draw_start,
                                 ALLSET_OT_restore_modeling_display, _retopology_on, new_target, pick_target)


def _close_relax(operator):
    session=getattr(operator,'_relax',None)
    if session is not None:session.close()
    operator._relax=None;STATE['relax_area']=None


# --- the main modal -------------------------------------------------------------------------------------

class ALLSET_OT_quad_draw(bpy.types.Operator):
    """Maya Quad Draw: click = dot on the surface, drag = move a dot / vertex / edge / face along the surface,
    Shift+click = fill a polygon, Shift+drag = relax, Ctrl+click = edge loop, Ctrl+Shift+click = delete"""
    bl_idname = "allset.quad_draw"
    bl_label = "Quad Draw"
    bl_options = {'REGISTER', 'UNDO'}

    middle: BoolProperty(options={'SKIP_SAVE', 'HIDDEN'}, description="Middle-drag: only move what is under the mouse")

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        if not _view_ok(context) or event.alt:
            return {'PASS_THROUGH'}
        ob = edit_object(context)
        if ob is None:
            return {'PASS_THROUGH'}
        self._ob = ob.name
        region, rv3d = context.region, context.region_data
        mouse = _mouse(event)
        self._press = mouse
        self._refs = reference_objects(context)
        self._moved = False
        self._grab = None
        self._relax=None
        if not _begin_symmetry(self,context,ob,coordinate_only=True):return {'CANCELLED'}
        # Maya's Keyboard/Mouse Shortcuts
        if event.ctrl and event.shift and self.middle:
            self._mode = 'MOVE'                 # Ctrl+Shift+MMB: drag an edge = tweak its edge loop
            self._grab = self._grab_loop(context, mouse)
            if self._grab is None:
                _close_symmetry(self)
                return {'PASS_THROUGH'}
            self._new_dot = False
        elif event.ctrl and event.shift:
            self._mode = 'DELETE'               # click / drag across faces = delete; an edge = its edge loop
            if self._delete(context, mouse) is None:
                _close_symmetry(self)
                return {'CANCELLED'}
        elif event.ctrl:
            return self._loop(context, mouse, center=self.middle)   # Ctrl+MMB = centred loop
        elif event.shift:
            self._mode = 'SHIFT'                # click = fill (LMB), drag = relax (MMB: the highlighted points)
            self._fill_plan=fill_plan(context,region,rv3d,mouse,ob) if not self.middle else None
            from . import quad_draw_relax
            try:self._relax=quad_draw_relax.Session(context,self,mouse)
            except quad_draw_symmetry.SymmetryError as ex:
                self.report({'WARNING'},str(ex));_close_symmetry(self);return {'CANCELLED'}
        else:
            self._mode = 'MOVE'
            self._grab = self._grab_at(context, mouse)
            if self._grab is None:
                if self.middle:
                    return {'PASS_THROUGH'}
                w = place_point(context, region, rv3d, mouse, self._refs)
                if w is None:
                    self.report({'INFO'}, "Quad Draw: click on the live surface")
                    return {'CANCELLED'}
                bm = bmesh.from_edit_mesh(ob.data)
                if self._sym is not None:self._sym.prepare_topology(local=True)
                v = add_dot(bm, ob.matrix_world.inverted_safe() @ w)
                if not _sync_symmetry(self,context):return {'CANCELLED'}
                bmesh.update_edit_mesh(ob.data)
                preselect.invalidate()
                self._depth = w.copy()
                self._grab = ('MESH', [v.index], [w], w)
                self._new_dot = True
            else:
                self._new_dot = False
        # Hover owns a snapshot of the pre-press coordinates. The modal consumes mouse
        # moves, so the hover operator cannot refresh that marker while dragging.
        STATE["preview"] = None
        STATE["snap"] = []
        STATE['delete_edges']=None
        STATE['topology_hover']=None
        self._snap = None
        if self._grab is not None and _weld_px(context) is not None:
            from .quad_draw_weld import Magnet
            excluded=self._sym.moving_mirrors(self._grab[1]) if self._sym else ()
            self._snap = Magnet(context,ob,self._grab[1],exclude=excluded)
        context.window_manager.modal_handler_add(self)
        _redraw(context)
        return {'RUNNING_MODAL'}

    # -- grabbing
    def _grab_at(self, context, mouse):
        region, rv3d = context.region, context.region_data
        ob = bpy.data.objects[self._ob]
        comp = component_at(context, region, rv3d, mouse, ob)
        if comp is None:
            return None
        bm = bmesh.from_edit_mesh(ob.data)
        if comp[0] == 'VERT':
            bm.verts.ensure_lookup_table()
            verts = [bm.verts[comp[1]]]
        elif comp[0] == 'EDGE':
            bm.edges.ensure_lookup_table()
            verts = list(bm.edges[comp[1]].verts)
        else:
            bm.faces.ensure_lookup_table()
            verts = list(bm.faces[comp[1]].verts)
        mw = ob.matrix_world
        start = surface_hit(context, region, rv3d, mouse, self._refs) if self._refs else None
        if start is None:
            start = sum((mw @ v.co for v in verts), Vector()) / len(verts)
        self._depth = start.copy()
        return ('MESH', [v.index for v in verts], [mw @ v.co for v in verts], start)

    def _drag_to(self, context, mouse):
        STATE["preview"] = None
        STATE["snap"] = []
        region, rv3d = context.region, context.region_data
        _k, idx, starts, start = self._grab
        ob = bpy.data.objects[self._ob]
        bm = bmesh.from_edit_mesh(ob.data)
        bm.verts.ensure_lookup_table()
        inv = ob.matrix_world.inverted_safe()
        if self._refs:
            # Preserve the cursor-to-component offset. No screen-plane fallback when the
            # cursor leaves a live surface: keep the last valid point until it re-enters.
            delta = Vector(mouse) - Vector(self._press)
            anchors = getattr(self, '_surface_anchors', None)
            if anchors is None:
                anchors = starts
                if surface_offset(context):
                    from . import live
                    anchors = []
                    for original in starts:
                        hit = live.nearest(context, original, self._refs)
                        anchors.append(hit[0] if hit is not None else original)
                self._surface_anchors = anchors
            news = []
            for i, original in zip(idx, anchors):
                xy = _screen_xy(region, rv3d, original)
                hit = surface_hit(context, region, rv3d, Vector(xy)+delta, self._refs) if xy else None
                news.append(hit if hit is not None else ob.matrix_world @ bm.verts[i].co)
        else:
            hit = view3d_utils.region_2d_to_location_3d(region, rv3d, mouse, self._depth)
            delta = hit - start
            news = [s + delta for s in starts]
        snap=getattr(self,'_snap',None)
        sym=getattr(self,'_sym',None)
        if snap is not None:
            proposed,pairs=snap.query(context,region,rv3d,dict(zip(idx,news)))
            if sym is not None:
                proposed,seam=sym.snap_seam(context,region,rv3d,proposed,snap)
            else:seam=[]
            news=[proposed[i] for i in idx]
            STATE["snap"]=[snap.co[t] for t in pairs.values()]+seam
        for i, w in zip(idx, news):
            bm.verts[i].co = inv @ w
        changed=[bm.verts[i] for i in idx]
        if sym is not None:
            sym.move(changed)
            changed += [sym.pairs[v] for v in changed if v in sym.pairs and sym.pairs[v].is_valid]
        preselect.coordinates_changed(ob,changed)
        bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)

    # -- one-shot actions
    def _delete(self, context, mouse, faces_only=False):
        """Ctrl+Shift+LMB: the dot / vertex / face under the mouse; an edge = its edge loop. While dragging only faces
        go. Returns what went or None."""
        region, rv3d = context.region, context.region_data
        ob = bpy.data.objects[self._ob]
        comp = component_at(context, region, rv3d, mouse, ob)
        if comp is None or (faces_only and comp[0] != 'FACE'):
            return None
        bm = bmesh.from_edit_mesh(ob.data)
        sym=getattr(self,'_sym',None)
        if sym is not None:
            bm.verts.ensure_lookup_table();bm.edges.ensure_lookup_table();bm.faces.ensure_lookup_table()
            vertices=list(bm.verts[comp[1]].link_faces) if comp[0]=='VERT' else []
            if comp[0]=='VERT':vertices={v for f in vertices for v in f.verts}|{bm.verts[comp[1]]}
            elif comp[0]=='FACE':vertices=list(bm.faces[comp[1]].verts)
            else:vertices={v for e in component_loop(bm.edges[comp[1]]) for f in e.link_faces for v in f.verts}
            sym.prepare_topology(local=True,vertices=vertices)
            try:sym.require(vertices)
            except quad_draw_symmetry.SymmetryError as ex:
                self.report({'WARNING'},str(ex));return None
        if comp[0] == 'EDGE':
            if not delete_loop(bm, comp[1]):
                self.report({'INFO'},'Quad Draw: choose a visible manifold edge loop');return None
        else:
            delete_at(bm, comp[0], comp[1])
        if not _sync_symmetry(self,context):return None
        bmesh.update_edit_mesh(ob.data)
        preselect.invalidate()
        self._deleted = True
        STATE["preview"] = None
        _redraw(context)
        return comp[0]

    def _grab_loop(self, context, mouse):
        region, rv3d = context.region, context.region_data
        ob = bpy.data.objects[self._ob]
        comp = component_at(context, region, rv3d, mouse, ob, edges_only=True)
        if comp is None:
            return None
        bm = bmesh.from_edit_mesh(ob.data)
        bm.edges.ensure_lookup_table()
        plan=loop_plan(context,ob,comp[1]);bm.verts.ensure_lookup_table()
        if not plan or not plan['verts']:return None
        verts = [bm.verts[i] for i in plan['verts']]
        mw = ob.matrix_world
        start = surface_hit(context, region, rv3d, mouse, self._refs) if self._refs else None
        if start is None:
            start = sum((mw @ v.co for v in verts), Vector()) / len(verts)
        self._depth = start.copy()
        return ('MESH', [v.index for v in verts], [mw @ v.co for v in verts], start)

    def _loop(self, context, mouse, center=False):
        from . import quad_draw_cut
        region, rv3d = context.region, context.region_data
        ob = bpy.data.objects[self._ob]
        comp = component_at(context, region, rv3d, mouse, ob, edges_only=True)
        if comp is None:
            _close_symmetry(self)
            return {'CANCELLED'}
        bm = bmesh.from_edit_mesh(ob.data)
        bm.edges.ensure_lookup_table()
        t = 0.5 if center else min(max(comp[2], 0.001), 0.999)
        backup=None
        try:
            plan=quad_draw_cut.Plan(bm,bm.edges[comp[1]],t,self._sym)
            if self._sym is None:backup=bm.copy()
            else:self._sym.prepare_backup()
            mw=ob.matrix_world;inv=mw.inverted_safe()
            project=(lambda co:inv@project_point(context,mw@co,self._refs,region,rv3d)) if self._refs else None
            plan.apply(project)
            if self._sym is not None:self._sym.check_seam()
        except (quad_draw_symmetry.SymmetryError,ValueError,ReferenceError,RuntimeError) as ex:
            if self._sym is not None:self._sym.rollback();self._sym=None
            elif backup is not None:
                mesh=bpy.data.meshes.new('_quad_draw_cut_rollback')
                try:backup.to_mesh(mesh);compat.refill_bmesh(bm,mesh)
                finally:bpy.data.meshes.remove(mesh)
            bmesh.update_edit_mesh(ob.data);_geometry_reset(None)
            self.report({'WARNING'},str(ex));return {'CANCELLED'}
        finally:
            if backup is not None:backup.free()
        _indices(bm)
        # Plan has already applied and validated both halves by exact edge pairs.
        # Replaying a second global topology diff would only repeat that work.
        if self._sym is not None and self._sym.disabled_reason:
            self.report({'WARNING'},self._sym.disabled_reason)
        _close_symmetry(self)
        bmesh.update_edit_mesh(ob.data)
        preselect.invalidate()
        STATE["preview"] = None
        _redraw(context)
        return {'FINISHED'}

    def _relax_at(self, context, mouse):
        from . import quad_draw_relax
        session=getattr(self,'_relax',None)
        if session is None:self._relax=session=quad_draw_relax.Session(context,self,getattr(self,'_press',mouse))
        session.apply(context,mouse)

    # -- modal
    def modal(self, context, event):
        if not tool_active(context) or not _view_ok(context) or bpy.data.objects.get(self._ob) is None:
            STATE["preview"] = None
            STATE["snap"] = []
            self._snap = None
            _close_relax(self)
            _close_symmetry(self);preselect.invalidate()
            return {'CANCELLED'}
        mouse = _mouse(event)
        button = 'MIDDLEMOUSE' if self.middle else 'LEFTMOUSE'
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            if not self._moved and math.hypot(mouse[0] - self._press[0], mouse[1] - self._press[1]) >= DRAG_PX:
                self._moved = True
            try:
                if self._mode == 'DELETE':self._delete(context, mouse, faces_only=True)
                elif self._moved:
                    if self._mode == 'SHIFT':self._relax_at(context, mouse)
                    else:self._drag_to(context, mouse)
                    _redraw(context)
            except quad_draw_symmetry.SymmetryError as ex:
                self.report({'WARNING'},str(ex));return self._cancel(context)
            return {'RUNNING_MODAL'}
        if event.type == button and event.value == 'RELEASE':
            return self._release(context, mouse)
        if event.type == 'ESC' and event.value == 'PRESS':
            return self._cancel(context)
        return {'RUNNING_MODAL'}

    def _release(self, context, mouse):
        ob = bpy.data.objects[self._ob]
        STATE["preview"] = None
        if self._mode == 'DELETE':
            _close_symmetry(self)
            return {'FINISHED'}
        if self._mode == 'SHIFT':
            _close_relax(self)
            if self._moved or self.middle:
                if not self._moved:
                    _close_symmetry(self)
                    return {'CANCELLED'}
                preselect.invalidate()
                _close_symmetry(self)
                _redraw(context)
                return {'FINISHED'}
            plan = self._fill_plan
            if plan is not None and self._sym is not None:self._sym.prepare_topology(local=True)
            if plan is None or apply_fill(ob, plan[0]) is None:
                _close_symmetry(self)
                self.report({'INFO'}, "Quad Draw: no valid local face; check overlap, folded corners and border connections")
                _redraw(context)
                return {'CANCELLED'}
            if not _sync_symmetry(self,context,finish=True):return {'CANCELLED'}
            bmesh.update_edit_mesh(ob.data)
            preselect.invalidate()
            _redraw(context)
            return {'FINISHED'}
        if not self._moved and not self._new_dot:
            _close_symmetry(self)
            return {'CANCELLED'}
        if self._moved:
            try:self._drag_to(context,mouse)
            except quad_draw_symmetry.SymmetryError as ex:
                self.report({'WARNING'},str(ex));return self._cancel(context)
        bm = bmesh.from_edit_mesh(ob.data)
        bm.verts.ensure_lookup_table()
        welded=0
        if self._snap is not None:
            if self._sym is not None and (self._snap.pairs or self._sym.seam_targets()):
                self._sym.prepare_topology(local=True,vertices=[bm.verts[i] for i in self._grab[1]]+[bm.verts[t] for t in self._snap.pairs.values()])
            try:welded=_commit_weld(self,bm,self._snap,{i:bm.verts[i] for i in self._grab[1]})
            except quad_draw_symmetry.SymmetryError as ex:
                self.report({'WARNING'},str(ex));return self._cancel(context)
            self._snap = None
            _indices(bm)
        STATE["snap"] = []
        self._surface_anchors = None
        if welded or self._new_dot:
            if not _sync_symmetry(self,context,finish=True):return {'CANCELLED'}
        else:_close_symmetry(self)
        bmesh.update_edit_mesh(ob.data)
        preselect.invalidate()
        _redraw(context)
        return {'FINISHED'}

    def _cancel(self, context):
        STATE["snap"] = []
        self._snap = None
        self._surface_anchors = None
        ob = bpy.data.objects.get(self._ob)
        session=getattr(self,'_relax',None)
        if session is not None:session.restore()
        _close_relax(self)
        sym=getattr(self,'_sym',None)
        if sym is not None:
            sym.rollback();self._sym=None
            if ob is not None:bmesh.update_edit_mesh(ob.data)
            preselect.invalidate();STATE['preview']=None;_redraw(context)
            return {'CANCELLED'}
        if self._grab is not None and ob is not None:
            bm = bmesh.from_edit_mesh(ob.data)
            bm.verts.ensure_lookup_table()
            if getattr(self, "_new_dot", False):
                bm.verts.remove(bm.verts[self._grab[1][0]])
                _indices(bm)
            else:
                inv = ob.matrix_world.inverted_safe()
                for i, w in zip(self._grab[1], self._grab[2]):
                    bm.verts[i].co = inv @ w
            bmesh.update_edit_mesh(ob.data)
        STATE["preview"] = None
        preselect.invalidate()
        _redraw(context)
        return {'CANCELLED'}


classes = (ALLSET_OT_quad_draw_hover, ALLSET_OT_quad_draw, ALLSET_OT_quad_draw_tab, ALLSET_OT_quad_draw_clear_dots,
           ALLSET_OT_quad_draw_exit, ALLSET_OT_restore_modeling_display, ALLSET_OT_quad_draw_start,ALLSET_OT_quad_draw_pick_seam)


# --- draw / undo / load / save handlers -----------------------------------------------------------------

_handles = []


def register_handlers():
    if not _handles:
        _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw_view, (), 'WINDOW', 'POST_VIEW'))
        _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw_pixel, (), 'WINDOW', 'POST_PIXEL'))
    if _geometry_reset not in bpy.app.handlers.undo_pre:bpy.app.handlers.undo_pre.append(_geometry_reset)
    if _geometry_reset not in bpy.app.handlers.redo_pre:bpy.app.handlers.redo_pre.append(_geometry_reset)
    if _file_reset not in bpy.app.handlers.load_pre:bpy.app.handlers.load_pre.append(_file_reset)
    for name, fn in (('save_pre', _overlay_save_pre), ('save_post', _overlay_save_post), ('save_post_fail', _overlay_save_post)):
        handlers = getattr(bpy.app.handlers, name, None)
        if handlers is not None and fn not in handlers:
            handlers.append(fn)
    for handlers in (bpy.app.handlers.undo_post,bpy.app.handlers.redo_post):
        if _restore_topology_state not in handlers:handlers.append(_restore_topology_state)


def unregister_handlers():
    for name, fn in (('save_pre', _overlay_save_pre), ('save_post', _overlay_save_post), ('save_post_fail', _overlay_save_post)):
        handlers = getattr(bpy.app.handlers, name, ())
        if fn in handlers:
            handlers.remove(fn)
    for handlers,fn in ((bpy.app.handlers.undo_pre,_geometry_reset),(bpy.app.handlers.redo_pre,_geometry_reset),(bpy.app.handlers.load_pre,_file_reset)):
        if fn in handlers:handlers.remove(fn)
    for handlers in (bpy.app.handlers.undo_post,bpy.app.handlers.redo_post):
        if _restore_topology_state in handlers:handlers.remove(_restore_topology_state)
    while _handles:
        bpy.types.SpaceView3D.draw_handler_remove(_handles.pop(), 'WINDOW')
    if bpy.app.timers.is_registered(_watch):
        bpy.app.timers.unregister(_watch)
    STATE.update(ob=None, preview=None, created=None, timer=False)
    _restore_overlays()
