# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's Transform Constraint for the Move tool in mesh edit mode.

Edge: dragging a Move handle (or MMB anywhere) slides the selection along its edges — vertices with Blender's
Vertex Slide, edges / faces with Edge Slide (Vertex Slide when Blender finds no edge loop to slide); the UVs follow
the slide only with Preserve UVs on. Surface: the drag moves the selection with each point snapped to the nearest
surface of the mesh. Along Normals: the drag moves each point along its own normal (Blender's Shrink / Fatten; selected edges along their
own normals, keeping their length, like Maya). Off: the Move tool as before. Ctrl+Shift+MMB slides along edges whatever the setting (Maya's quick edge slide).
"""
import bmesh
import bpy
from mathutils import Vector

MODES = (('NONE', "Off", "Move components freely"),
         ('EDGE', "Edge Slide", "Slide components along their edges"),
         ('SURFACE', "Surface Slide", "Move components along the surface of the mesh"),
         ('NORMAL', "Along Normals", "Move each component along its own normal"))


def mode(context):
    from .. import preferences
    try:
        return preferences.get(context).transform_constraint
    except AttributeError:
        return 'NONE'


def active(context):
    """The Move tool slides instead of moving (mesh edit mode, Maya mode, a constraint set)."""
    from .. import preferences
    try:
        prefs = preferences.get(context)
    except AttributeError:
        return False
    if context.mode != 'EDIT_MESH' or not prefs.maya_mode or prefs.transform_constraint == 'NONE':
        return False
    from . import hold
    return not hold.COMPONENT.on


def vertex_only(select_mode):
    """Vertex select mode alone: vertices slide on their own (Vertex Slide)."""
    return bool(select_mode[0]) and not select_mode[1] and not select_mode[2]


def slide_options(context):
    """Edge / vertex slide options: the UVs follow the slide only with Preserve UVs on, like Maya (Blender's slides
    correct UVs by default)."""
    return {"correct_uv": bool(context.scene.tool_settings.use_transform_correct_face_attributes)}


def slide(context, kind, release_confirm=True, axes=None):
    """Start the slide drag (INVOKE). Returns the operator result set. `axes` = (constraint_axis, orient_type,
    orient_matrix) of the Move handle being dragged: Surface then moves along that axis / plane before each point
    is put back on the surface (a free drag without it)."""
    if kind == 'NORMAL':
        if tuple(context.tool_settings.mesh_select_mode) == (False, True, False):
            # edges move along their own normals, keeping their length (Shrink / Fatten uses vertex normals)
            return bpy.ops.allset.edge_normal_move('INVOKE_DEFAULT')
        return bpy.ops.transform.shrink_fatten('INVOKE_DEFAULT', release_confirm=release_confirm)
    if kind == 'SURFACE':
        extra = {}
        if axes is not None and any(axes[0]) and not all(axes[0]):
            extra = {"constraint_axis": axes[0], "orient_type": axes[1], "orient_matrix_type": 'GLOBAL',
                     "orient_matrix": axes[2]}
        return bpy.ops.transform.translate('INVOKE_DEFAULT', release_confirm=release_confirm, snap=True,
                                           snap_elements={'FACE_NEAREST'}, snap_target='CLOSEST',
                                           use_snap_self=True, use_snap_edit=True, use_snap_nonedit=True,
                                           **extra)
    options = slide_options(context)
    if not vertex_only(context.tool_settings.mesh_select_mode):
        try:
            res = bpy.ops.transform.edge_slide('INVOKE_DEFAULT', release_confirm=release_confirm, **options)
        except RuntimeError:
            res = {'CANCELLED'}
        if res & {'RUNNING_MODAL', 'FINISHED'}:
            return res
    return bpy.ops.transform.vert_slide('INVOKE_DEFAULT', release_confirm=release_confirm, **options)


class ALLSET_OT_xform_constraint(bpy.types.Operator):
    """Set the Move tool's Transform Constraint (Off / Edge Slide / Surface Slide / Along Normals)"""
    bl_idname = "allset.xform_constraint"
    bl_label = "Transform Constraint"
    bl_options = {'INTERNAL'}

    mode: bpy.props.EnumProperty(items=MODES, default='NONE', options={'SKIP_SAVE'})

    def execute(self, context):
        from .. import preferences
        preferences.get(context).transform_constraint = self.mode
        from . import hold
        hold._redraw()
        return {'FINISHED'}


class ALLSET_OT_component_slide(bpy.types.Operator):
    """Slide the selected components along their edges or the surface (Maya Transform Constraint)"""
    bl_idname = "allset.component_slide"
    bl_label = "Slide Components"
    bl_options = {'INTERNAL'}

    mode: bpy.props.EnumProperty(items=(('AUTO', "Setting", "Use the Transform Constraint setting"),) + MODES[1:],
                                 default='AUTO', options={'SKIP_SAVE'})
    release_confirm: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    # the Move handle being dragged (set by the Maya manipulator): Surface keeps to its axis / plane
    constraint_axis: bpy.props.BoolVectorProperty(size=3, options={'HIDDEN', 'SKIP_SAVE'})
    orient_type: bpy.props.StringProperty(default='GLOBAL', options={'HIDDEN', 'SKIP_SAVE'})
    orient_matrix: bpy.props.FloatVectorProperty(size=(3, 3), subtype='MATRIX', options={'HIDDEN', 'SKIP_SAVE'},
                                                 default=((1, 0, 0), (0, 1, 0), (0, 0, 1)))

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, _event):
        kind = mode(context) if self.mode == 'AUTO' else self.mode
        if kind == 'NONE':
            return {'PASS_THROUGH'}
        try:
            axes = (tuple(self.constraint_axis), self.orient_type, [tuple(r) for r in self.orient_matrix])
            res = slide(context, kind, self.release_confirm, axes)
        except RuntimeError:
            return {'CANCELLED'}
        return {'FINISHED'} if res & {'RUNNING_MODAL', 'FINISHED'} else {'CANCELLED'}

    def execute(self, context):
        return {'CANCELLED'}


def edge_directions(bm):
    """{vertex index: direction} of the selected edges of ``bm``: each edge's normal (the mean of its faces' normals;
    of its vertex normals for an edge without faces); a vertex of several selected edges takes their mean."""
    sums = {}
    for e in bm.edges:
        if not e.select:
            continue
        n = Vector()
        for f in e.link_faces:
            n += f.normal
        if n.length < 1e-9:
            n = e.verts[0].normal + e.verts[1].normal
        if n.length < 1e-9:
            continue
        n.normalize()
        for v in e.verts:
            sums[v.index] = sums.get(v.index, Vector()) + n
    return {i: d.normalized() for i, d in sums.items() if d.length > 1e-9}


class ALLSET_OT_edge_normal_move(bpy.types.Operator):
    """Move the selected edges along their own normals, keeping their length (Maya Ctrl+middle-drag with the Move
    tool)"""
    bl_idname = "allset.edge_normal_move"
    bl_label = "Move Edges Along Normals"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    # hidden: like Maya, the drag leaves no Adjust Last Operation panel behind
    distance: bpy.props.FloatProperty(name="Distance", subtype='DISTANCE', options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def _collect(self, context):
        """[(object, [(vertex index, start co, local offset per world unit)])], world centre, world mean direction."""
        data, centre, mean, count = [], Vector(), Vector(), 0
        for ob in context.objects_in_mode_unique_data:
            if ob.type != 'MESH':
                continue
            bm = bmesh.from_edit_mesh(ob.data)
            bm.normal_update()
            bm.verts.ensure_lookup_table()
            m3 = ob.matrix_world.to_3x3()
            items = []
            for i, d in edge_directions(bm).items():
                w = m3 @ d
                if w.length < 1e-12:
                    continue
                items.append((i, bm.verts[i].co.copy(), d / w.length))
                centre += ob.matrix_world @ bm.verts[i].co
                mean += w.normalized()
                count += 1
            if items:
                data.append((ob, items))
        return data, (centre / count if count else None), mean

    def _apply(self, t):
        for ob, items in self._data:
            bm = bmesh.from_edit_mesh(ob.data)
            bm.verts.ensure_lookup_table()
            for i, co, step in items:
                bm.verts[i].co = co + step * t
            bmesh.update_edit_mesh(ob.data, loop_triangles=True, destructive=False)

    def execute(self, context):
        self._data = self._collect(context)[0]
        if not self._data:
            return {'CANCELLED'}
        self._apply(self.distance)
        return {'FINISHED'}

    def invoke(self, context, event):
        from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d
        self._data, centre, mean = self._collect(context)
        region, rv3d = context.region, context.region_data
        if not self._data or region is None or rv3d is None or mean.length < 1e-9:
            return {'CANCELLED'}
        mean.normalize()
        p0 = location_3d_to_region_2d(region, rv3d, centre)
        if p0 is None:
            return {'CANCELLED'}
        size = max(rv3d.view_distance * 0.01, 1e-6)
        p1 = location_3d_to_region_2d(region, rv3d, centre + mean * size)
        sdir = (p1 - p0) / size if p1 is not None else Vector((0.0, 0.0))      # px per world unit along the normal
        px = (region_2d_to_location_3d(region, rv3d, p0 + Vector((1.0, 0.0)), centre) - centre).length
        # the drag follows the normal's direction on screen; a normal pointing at the viewer takes the sideways drag
        self._sdir = sdir if sdir.length * px > 0.2 else None
        self._px = px
        self._mouse0 = Vector((event.mouse_region_x, event.mouse_region_y))
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _distance(self, event):
        drag = Vector((event.mouse_region_x, event.mouse_region_y)) - self._mouse0
        if self._sdir is None:
            return drag.x * self._px
        return drag.dot(self._sdir) / self._sdir.length_squared

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self.distance = self._distance(event)
            self._apply(self.distance)
            return {'RUNNING_MODAL'}
        if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE'} and event.value in {'RELEASE', 'PRESS'}:
            self.distance = self._distance(event)
            self._apply(self.distance)
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._apply(0.0)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


classes = (ALLSET_OT_xform_constraint, ALLSET_OT_component_slide, ALLSET_OT_edge_normal_move)
