# SPDX-License-Identifier: GPL-3.0-or-later
"""Quad Draw with Tab held (``allset.quad_draw_tab``): drag from a border edge = extend it by quads (Extend: Edge /
Loop / Border), from a border corner vertex = fill the inner corner, in empty space = a strip of quads; middle-drag in
empty space sets the strip width. ``TAB_HINT`` is its status-bar hint.
"""

import bmesh
import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

from . import poly_draw, preselect, quad_draw_symmetry
from .quad_draw_geometry import (_indices, border_chain, border_loop, corner_neighbours, corner_quad, extend_edges,
                                 strip_faces, strip_pairs)
from .quad_draw_surface import _ui_scale, _weld_px, place_point, project_point, reference_objects, surface_hit
from .quad_draw_state import (DRAG_PX, STATE, _begin_symmetry, _close_symmetry, _commit_weld, _mouse, _redraw,
                              _sync_symmetry, _view_ok, edit_object, tool_active)
from .quad_draw_hover import _corner_points, corner_vertex_at, update_hover

TAB_HINT = ("Quad Draw: hold Tab and drag a border edge to extend it, a corner vertex to fill the corner, or drag in "
            "empty space for a strip of quads; middle-drag in empty space sets the strip width")


class ALLSET_OT_quad_draw_tab(bpy.types.Operator):
    """Quad Draw Tab: while Tab is held, drag from a border edge to extend it, or in empty space to draw a strip of
    quads"""
    bl_idname = "allset.quad_draw_tab"
    bl_label = "Quad Draw Extend"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return tool_active(context)

    def invoke(self, context, event):
        if not _view_ok(context) or edit_object(context) is None:
            return {'PASS_THROUGH'}
        self._ob = edit_object(context).name
        self._drag = None
        self._snap = None
        self._new_ids = {}
        self._sym = None
        self._done = False
        self._refs = reference_objects(context)
        update_hover(context, context.region, context.region_data, _mouse(event), False, False, tab=True)
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(TAB_HINT)
        _redraw(context)
        return {'RUNNING_MODAL'}

    def _end(self, context, result):
        _close_symmetry(self)
        STATE["preview"] = None
        STATE["snap"] = []
        self._snap = None
        context.workspace.status_text_set(None)
        _redraw(context)
        return result

    def modal(self, context, event):
        if not tool_active(context) or not _view_ok(context) or bpy.data.objects.get(self._ob) is None:
            return self._end(context, {'CANCELLED'})
        region, rv3d = context.region, context.region_data
        mouse = _mouse(event)
        if event.type == 'TAB':
            if event.value == 'RELEASE':
                if self._drag is not None:
                    self._commit(context, mouse)
                return self._end(context, {'FINISHED'} if self._done else {'CANCELLED'})
            return {'RUNNING_MODAL'}      # key repeat
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            if self._drag is None:
                update_hover(context, region, rv3d, mouse, False, False, tab=True)
            elif self._drag[0]=='WIDTH':
                width=self._drag[2]+(mouse[0]-self._drag[1][0])/_ui_scale(context)
                poly_draw.settings(context).qd_strip_width=max(1,round(width))
                STATE["preview"]=('WIDTH',self._drag[1])
                context.workspace.status_text_set(f'Quad Strip Width: {poly_draw.settings(context).qd_strip_width:.1f} px — Esc to cancel')
            else:
                self._update_drag(context, mouse)
            _redraw(context)
            return {'RUNNING_MODAL'}
        if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE'} and event.value == 'PRESS' and self._drag is None:
            ob = bpy.data.objects[self._ob]
            mode = poly_draw.settings(context).qd_extend
            vi = corner_vertex_at(context, region, rv3d, mouse, ob) if event.type == 'LEFTMOUSE' and mode == 'EDGE' else None
            ei=poly_draw.border_edge_at(context,region,rv3d,mouse,ob) if vi is None else None
            if vi is None and ei is None and event.type=='MIDDLEMOUSE':
                self._button=event.type;self._drag=('WIDTH',mouse,poly_draw.settings(context).qd_strip_width)
                STATE["preview"]=('WIDTH',mouse)     # a preview strip of the current width while dragging
                _redraw(context)
                return {'RUNNING_MODAL'}
            if not _begin_symmetry(self,context,ob,coordinate_only=True):return {'RUNNING_MODAL'}
            self._press_mouse=mouse
            if vi is not None:
                # a border vertex: the quad of it, its two border neighbours and the mouse point (#180)
                self._button = event.type
                self._drag = ('CORNER', vi)
                bm=bmesh.from_edit_mesh(ob.data)
                bm.verts.ensure_lookup_table()
                a,b=corner_neighbours(bm.verts[vi])
                self._new_ids={None:len(bm.verts)}
                self._start_snap(context,[ob.matrix_world@bm.verts[vi].co],[(a.index,vi,b.index,len(bm.verts))])
                return {'RUNNING_MODAL'}
            self._button = event.type
            if ei is not None:
                bm = bmesh.from_edit_mesh(ob.data)
                bm.edges.ensure_lookup_table()
                edge = bm.edges[ei]
                mode = 'LOOP' if event.type == 'MIDDLEMOUSE' else mode
                loop = border_loop(edge) if mode == 'BORDER' else border_chain(edge) if mode == 'LOOP' else [edge]
                start = surface_hit(context, region, rv3d, mouse, self._refs) if self._refs else None
                if start is None:
                    mw = ob.matrix_world
                    start = mw @ ((edge.verts[0].co + edge.verts[1].co) / 2)
                self._drag = ('EXTEND', [e.index for e in loop], start)
                ids=sorted({v.index for e in loop for v in e.verts})
                self._new_ids={i:len(bm.verts)+k for k,i in enumerate(ids)}
                faces=[]
                for e in loop:
                    b,a=poly_draw.edge_start(e)
                    faces.append((b.index,a.index,self._new_ids[a.index],self._new_ids[b.index]))
                bm.verts.ensure_lookup_table()
                self._start_snap(context,[ob.matrix_world@bm.verts[i].co for i in ids],faces)
            else:
                self._drag = ('STRIP', [mouse])
            return {'RUNNING_MODAL'}
        if event.type == getattr(self, "_button", 'LEFTMOUSE') and event.value == 'RELEASE' \
                and self._drag is not None:
            self._commit(context, mouse)
            if self._drag[0]=='WIDTH':
                STATE["preview"]=None
                context.workspace.status_text_set(TAB_HINT)
                _redraw(context)
            self._drag = None
            self._snap = None
            STATE["snap"] = []
            return {'RUNNING_MODAL'}
        if event.type == 'ESC' and event.value == 'PRESS':
            if self._drag is not None and self._drag[0]=='WIDTH':
                poly_draw.settings(context).qd_strip_width=self._drag[2]
            return self._end(context, {'FINISHED'} if self._done else {'CANCELLED'})
        return {'RUNNING_MODAL'} if self._drag is not None else {'PASS_THROUGH'}

    def _start_snap(self,context,extra,faces):
        self._snap=None
        if _weld_px(context) is not None:
            from .quad_draw_weld import Magnet
            ob=bpy.data.objects[self._ob]
            # Duplicated extension endpoints must not weld back into their
            # source anchors on a short drag (which would collapse a quad).
            anchors=self._new_ids.keys() if self._drag[0]=='EXTEND' else [self._drag[1]] if self._drag[0]=='CORNER' else ()
            self._snap=Magnet(context,ob,self._new_ids.values(),extra,faces,exclude=anchors)
            sym=getattr(self,'_sym',None)
            if sym is not None and self._drag[0] in {'EXTEND','CORNER'}:
                bm=bmesh.from_edit_mesh(ob.data);bm.verts.ensure_lookup_table()
                sym.virtual_origins={new:bm.verts[old if old is not None else self._drag[1]] for old,new in self._new_ids.items()}

    def _snap_points(self,context,points):
        STATE["snap"]=[]
        snap=getattr(self,'_snap',None)
        if snap is None:
            return points
        proposed={self._new_ids[i]:p for i,p in points.items()}
        raw=dict(proposed)
        proposed,pairs=snap.query(context,context.region,context.region_data,proposed)
        sym=getattr(self,'_sym',None)
        if sym is not None:proposed,seam=sym.snap_virtual(context,context.region,context.region_data,proposed,snap,raw=raw)
        else:seam=[]
        STATE["snap"]=[snap.co[t] for t in snap.pairs.values()]+seam
        return {i:proposed[self._new_ids[i]] for i in points}

    def _strip_positions(self,context,mouse):
        path=self._drag[1]+[mouse]
        region,rv3d=context.region,context.region_data
        pairs=strip_pairs(path,poly_draw.settings(context).qd_strip_width*_ui_scale(context))
        points={}
        for row,(left,right) in enumerate(pairs):
            a=place_point(context,region,rv3d,left,self._refs);b=place_point(context,region,rv3d,right,self._refs)
            if a is None or b is None:break
            points[row*2]=a;points[row*2+1]=b
        count=len(points)
        ob=bpy.data.objects[self._ob];base=len(bmesh.from_edit_mesh(ob.data).verts)
        self._new_ids={i:base+i for i in range(count)}
        faces=[(base+i-1,base+i+1,base+i,base+i-2) for i in range(2,count,2)]
        if _weld_px(context) is not None:
            if self._snap is None:self._start_snap(context,list(points.values()),faces)
            else:self._snap.set_virtual(list(points.values()),faces)
        else:self._snap=None
        return self._snap_points(context,points) if points else points

    def _extend_positions(self,context,mouse):
        ob=bpy.data.objects[self._ob]
        bm=bmesh.from_edit_mesh(ob.data)
        bm.verts.ensure_lookup_table()
        offset=self._offset_fn(context,mouse)
        return self._snap_points(context,{i:ob.matrix_world@offset(bm.verts[i].co) for i in self._new_ids})

    def _offset_fn(self, context, mouse):
        region, rv3d = context.region, context.region_data
        ob = bpy.data.objects[self._ob]
        mw, inv = ob.matrix_world, ob.matrix_world.inverted_safe()
        start = self._drag[2]
        hit = surface_hit(context, region, rv3d, mouse, self._refs) if self._refs else None
        if hit is None:
            hit = view3d_utils.region_2d_to_location_3d(region, rv3d, mouse, start)
        delta = hit - start
        refs = self._refs

        def offset(co):
            w = mw @ co + delta
            return inv @ (project_point(context, w, refs, region, rv3d) if refs else w)
        return offset

    def _corner_point(self, context, mouse):
        """World point under the mouse for a corner quad: on the reference surface, else in the view plane through
        the vertex."""
        region, rv3d = context.region, context.region_data
        ob = bpy.data.objects[self._ob]
        bm = bmesh.from_edit_mesh(ob.data)
        bm.verts.ensure_lookup_table()
        at = ob.matrix_world @ bm.verts[self._drag[1]].co
        hit = place_point(context, region, rv3d, mouse, self._refs) if self._refs else None
        point=hit if hit is not None else view3d_utils.region_2d_to_location_3d(region, rv3d, mouse, at)
        return self._snap_points(context,{None:point})[None]

    def _update_drag(self, context, mouse):
        if self._drag[0] == 'CORNER':
            ob = bpy.data.objects[self._ob]
            p = self._corner_point(context, mouse)
            STATE["preview"] = ('EXTEND', [q for a, b in _corner_points(ob, self._drag[1]) for q in (b, p)])
            return
        if self._drag[0] == 'STRIP':
            self._drag[1].append(mouse)
            positions=self._strip_positions(context,mouse)
            pts=[]
            for i in range(0,len(positions),2):
                pts += [positions[i],positions[i+1]]
                if i:pts += [positions[i-2],positions[i],positions[i-1],positions[i+1]]
            STATE["preview"] = ('EXTEND', pts)
            return
        positions = self._extend_positions(context, mouse)
        ob = bpy.data.objects[self._ob]
        bm = bmesh.from_edit_mesh(ob.data)
        bm.edges.ensure_lookup_table()
        mw = ob.matrix_world
        segs = []
        for i in self._drag[1]:
            if i < len(bm.edges):
                b, a = poly_draw.edge_start(bm.edges[i])
                pa, pb = positions[a.index], positions[b.index]
                segs += [mw @ a.co, pa, pa, pb, pb, mw @ b.co]
        STATE["preview"] = ('EXTEND', segs)

    def _depth(self, context):
        hit = surface_hit(context, context.region, context.region_data, self._drag[1][0], self._refs) \
            if self._refs else None
        return hit if hit is not None else context.scene.cursor.location

    def _commit(self, context, mouse):
        if self._drag[0]=='WIDTH':return
        ob = bpy.data.objects[self._ob]
        press=getattr(self,'_press_mouse',None)
        if press is not None and (Vector(mouse)-Vector(press)).length<DRAG_PX:
            _close_symmetry(self);return
        try:
            if self._sym is not None:self._sym.prepare_topology(local=True)
            self._commit_geometry(context,mouse)
        except (quad_draw_symmetry.SymmetryError,ValueError,ReferenceError) as ex:
            sym=getattr(self,'_sym',None)
            if sym is not None:sym.rollback();self._sym=None
            bmesh.update_edit_mesh(ob.data);preselect.invalidate()
            self.report({'WARNING'},str(ex))
        finally:_close_symmetry(self)

    def _commit_geometry(self,context,mouse):
        ob = bpy.data.objects[self._ob]
        bm = bmesh.from_edit_mesh(ob.data)
        inv = ob.matrix_world.inverted_safe()
        if self._drag[0] == 'CORNER':
            bm.verts.ensure_lookup_table()
            before = set(bm.verts)
            face = corner_quad(bm, bm.verts[self._drag[1]], inv @ self._corner_point(context, mouse))
            faces = [face] if face is not None else []
            if faces and self._snap is not None:
                new=next(v for v in face.verts if v not in before)
                _commit_weld(self,bm,self._snap,{self._new_ids[None]:new})
                _indices(bm)
        elif self._drag[0] == 'EXTEND':
            bm.edges.ensure_lookup_table()
            edges = [bm.edges[i] for i in self._drag[1] if i < len(bm.edges)]
            positions=self._extend_positions(context,mouse)
            created={}
            faces = extend_edges(bm,edges,None,{i:inv@p for i,p in positions.items()},created)
            if faces and self._snap is not None:
                _commit_weld(self,bm,self._snap,{self._new_ids[i]:v for i,v in created.items()})
                _indices(bm)
        else:
            points=self._strip_positions(context,mouse)
            local=[(inv@points[i],inv@points[i+1]) for i in range(0,len(points),2)]
            start=len(bm.verts)
            faces = strip_faces(bm, local) if len(local) >= 2 else []
            if faces and self._snap is not None:
                bm.verts.ensure_lookup_table()
                _commit_weld(self,bm,self._snap,{start+i:bm.verts[start+i] for i in range(len(points))})
                _indices(bm)
        if not _sync_symmetry(self,context,finish=True):return
        bmesh.update_edit_mesh(ob.data)
        preselect.invalidate()
        self._done = self._done or bool(faces)
