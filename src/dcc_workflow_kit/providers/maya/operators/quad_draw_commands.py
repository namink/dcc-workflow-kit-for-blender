# SPDX-License-Identifier: GPL-3.0-or-later
"""The small Quad Draw commands: start (``allset.quad_draw_start``: edit the selected mesh or a new ``polySurfaceN``,
``pick_target`` / ``new_target``, and own the views' Retopology overlay), exit, Clear Dots, Restore Modeling Display
and Pick Topology Seam.
"""

import bmesh
import bpy
from bpy.props import BoolProperty

from . import poly_draw, preselect, quad_draw_symmetry
from .. import results
from .quad_draw_geometry import clear_dots
from .quad_draw_state import (STATE, TOOL, _geometry_reset, _overlay_save_runtime, _overlay_values, _redraw,
                              _restore_inactive_overlays, _set_overlay_values, _watch, component_at, edit_object,
                              sync_overlays, tool_active, topology_preview)
from .quad_draw_hover import _component_points


class ALLSET_OT_quad_draw_clear_dots(bpy.types.Operator):
    """Remove every Quad Draw dot (Maya Tool Settings: Clear Dots)"""
    bl_idname = "allset.quad_draw_clear_dots"
    bl_label = "Clear Dots"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return edit_object(context) is not None

    def execute(self, context):
        ob = edit_object(context)
        bm = bmesh.from_edit_mesh(ob.data)
        if not clear_dots(bm):
            return {'CANCELLED'}
        bmesh.update_edit_mesh(ob.data)
        preselect.invalidate()
        STATE["preview"] = None
        for area in context.screen.areas if context.screen else ():
            area.tag_redraw()
        return {'FINISHED'}


class ALLSET_OT_quad_draw_pick_seam(bpy.types.Operator):
    """Choose an existing center edge to establish topology correspondence"""
    bl_idname='allset.quad_draw_pick_seam'
    bl_label='Pick Topology Seam'
    bl_options={'REGISTER','UNDO'}
    reference: BoolProperty(default=False,options={'HIDDEN','SKIP_SAVE'})

    @classmethod
    def poll(cls,context):return tool_active(context)

    def invoke(self,context,event):
        self._ob=context.edit_object.name
        context.workspace.status_text_set('Topology symmetry: click a manifold '+('live reference' if self.reference else 'retopology')+' seam edge; Esc cancels')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _end(self,context,result):
        STATE['preview']=None;context.workspace.status_text_set(None)
        _redraw(context);return result

    def modal(self,context,event):
        if event.type in {'ESC','RIGHTMOUSE'} and event.value=='PRESS':return self._end(context,{'CANCELLED'})
        ob=bpy.data.objects.get(self._ob)
        if ob is None or ob.mode!='EDIT':return self._end(context,{'CANCELLED'})
        if event.alt:return {'PASS_THROUGH'}
        area=next((a for a in context.window.screen.areas if a.type=='VIEW_3D' and a.x<=event.mouse_x<a.x+a.width and a.y<=event.mouse_y<a.y+a.height),None)
        region=next((r for r in area.regions if r.type=='WINDOW'),None) if area else None
        if region is None:return {'RUNNING_MODAL'}
        with context.temp_override(area=area,region=region):
            ctx=bpy.context;mouse=(event.mouse_x-region.x,event.mouse_y-region.y)
            if self.reference:
                from . import quad_draw_reference
                picked=quad_draw_reference.pick(ctx,region,ctx.region_data,mouse)
                STATE['preview']=('TAB',picked[2]) if picked else None
                _redraw(ctx)
                if event.type=='LEFTMOUSE' and event.value=='PRESS' and picked:
                    reference,edge,_points=picked
                    try:quad_draw_reference.bind(ctx,reference,edge,'XYZ'.index(ctx.scene.allset_symmetry.axis),ctx.scene.allset_symmetry.allow_partial)
                    except quad_draw_symmetry.SymmetryError as ex:
                        self.report({'WARNING'},str(ex));return {'RUNNING_MODAL'}
                    from . import symmetry
                    sym=symmetry.state(ctx.scene);sym.on=True;sym.about='TOPOLOGY';sym.last='TOPOLOGY';symmetry.apply(sym,[ob])
                    _geometry_reset(None);results.result(self, 'Reference seam bound: '+reference.name)
                    return self._end(ctx,{'FINISHED'})
                return {'RUNNING_MODAL'}
            comp=component_at(ctx,region,ctx.region_data,mouse,ob,edges_only=True)
            STATE['preview']=('TAB',_component_points(ob,comp)) if comp else None
            _redraw(ctx)
            if event.type=='LEFTMOUSE' and event.value=='PRESS':
                if comp is None:return {'RUNNING_MODAL'}
                bm=bmesh.from_edit_mesh(ob.data);bm.edges.ensure_lookup_table()
                from . import symmetry
                sym=symmetry.state(ctx.scene)
                try:quad_draw_symmetry.bind_seam(ob,bm,bm.edges[comp[1]],sym)
                except quad_draw_symmetry.SymmetryError as ex:
                    self.report({'WARNING'},str(ex));return {'RUNNING_MODAL'}
                sym.on=True;sym.about='TOPOLOGY';sym.last='TOPOLOGY';symmetry.apply(sym,[ob])
                bmesh.update_edit_mesh(ob.data,loop_triangles=False,destructive=False)
                _geometry_reset(None);topology_preview(ctx,ob)
                return self._end(ctx,{'FINISHED'})
        return {'RUNNING_MODAL'}


class ALLSET_OT_quad_draw_exit(bpy.types.Operator):
    """Leave Quad Draw for the Select tool (Maya Esc / Q)"""
    bl_idname = "allset.quad_draw_exit"
    bl_label = "Exit Quad Draw"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return tool_active(context)

    def execute(self, context):
        STATE["preview"] = None
        bpy.ops.wm.tool_set_by_id(name="builtin.select_box", space_type='VIEW_3D')
        _restore_inactive_overlays()
        return {'FINISHED'}


class ALLSET_OT_restore_modeling_display(bpy.types.Operator):
    """Turn off a persisted Retopology overlay in this viewport to restore ordinary component shading"""
    bl_idname = 'allset.restore_modeling_display'
    bl_label = 'Restore Modeling Display'
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        from ..ui import toolbox
        return context.space_data is not None and context.space_data.type == 'VIEW_3D' and not toolbox.is_toolbox(context.space_data)

    def execute(self, context):
        if tool_active(context):
            bpy.ops.wm.tool_set_by_id(name='builtin.select_box', space_type='VIEW_3D')
        space = context.space_data
        ptr = space.as_pointer()
        original = STATE['overlays'].pop(ptr, _overlay_values(space))
        _overlay_save_runtime.pop(ptr, None)
        _set_overlay_values(space, (False, original[1], original[2]))
        context.area.tag_redraw()
        return {'FINISHED'}


# --- start: the mesh to edit, the views' overlay --------------------------------------------------------

def _retopology_on(context):
    """Own only the real 3D views in this window, preserving their native settings."""
    from ..ui import toolbox
    screen = context.window.screen if context.window else None
    for area in screen.areas if screen else ():
        if area.type != 'VIEW_3D' or toolbox.is_toolbox(area.spaces.active):
            continue
        space = area.spaces.active
        ptr = space.as_pointer()
        if ptr not in STATE['overlays']:
            STATE['overlays'][ptr] = _overlay_values(space)
    sync_overlays()


def new_target(context):
    """A new empty mesh ``polySurfaceN`` at the origin, selected and in edit mode (Quad Draw with nothing to edit)."""
    from . import mesh_maya
    if context.view_layer.objects.active is not None and context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    me = bpy.data.meshes.new(poly_draw.BASE_NAME)
    ob = bpy.data.objects.new(poly_draw.BASE_NAME, me)
    context.view_layer.active_layer_collection.collection.objects.link(ob)
    mesh_maya._maya_rename(ob, poly_draw.BASE_NAME)
    for other in context.selected_objects:
        other.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    return ob


def pick_target(context):
    """The mesh Quad Draw edits: the edited / selected mesh unless it is the live surface; else None (make one)."""
    from . import live
    ob = context.active_object
    if ob is not None and ob.type == 'MESH' and not live.contains(context.scene, ob) and (ob.mode == 'EDIT' or ob.select_get()):
        return ob
    return None


class ALLSET_OT_quad_draw_start(bpy.types.Operator):
    """Maya Mesh Tools > Quad Draw: draw a new mesh on the live surface (or edit the selected mesh)"""
    bl_idname = "allset.quad_draw_start"
    bl_label = "Quad Draw Tool"
    bl_options = {'REGISTER', 'UNDO'}

    option_box: BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        ob = pick_target(context)
        from . import maya_errors
        if maya_errors.refuse_hidden(self, ob):        # Blender can't edit a hidden mesh (#187)
            return {'CANCELLED'}
        if ob is None:
            ob = new_target(context)
            STATE["created"] = ob.name
        if context.mode != 'EDIT_MESH' or context.edit_object is not ob:
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            from . import live
            for other in context.selected_objects:
                if other is not ob:
                    other.select_set(False)
            for reference in live.objects(context.scene):
                reference.select_set(False)
            ob.select_set(True)
            context.view_layer.objects.active = ob
            bpy.ops.object.mode_set(mode='EDIT')
        STATE["ob"] = ob.name
        sym=context.scene.allset_symmetry
        if sym.on and sym.about=='TOPOLOGY' and quad_draw_symmetry.SEED not in ob.data:
            bm=bmesh.from_edit_mesh(ob.data);edge=bm.select_history.active
            if isinstance(edge,bmesh.types.BMEdge) and len(edge.link_faces)==2:
                try:quad_draw_symmetry.bind_seam(ob,bm,edge,sym)
                except quad_draw_symmetry.SymmetryError as ex:self.report({'WARNING'},str(ex))
        try:
            bpy.ops.wm.tool_set_by_id(name=TOOL, space_type='VIEW_3D')
        except RuntimeError as ex:
            self.report({'ERROR'}, str(ex).strip())
            return {'CANCELLED'}
        if context.window is not None:
            _retopology_on(context)
            if not bpy.app.background:
                from ..ui import maya_dock
                maya_dock.show(context, 'MODELING_TOOLKIT')
        if not STATE["timer"]:
            STATE["timer"] = True
            bpy.app.timers.register(_watch, first_interval=0.5)
        if self.option_box:
            poly_draw._open_tool_settings()
        return {'FINISHED'}
