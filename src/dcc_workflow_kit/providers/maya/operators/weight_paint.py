# SPDX-License-Identifier: GPL-3.0-or-later
"""Paint Skin Weights workspace: native brush tools and configurable weight operations.

Code: weight_paint_settings (action settings, workspace settings, brush helpers), weight_paint_flood (Maya Flood);
this module keeps the Paint Skin Weights operators and register."""
from contextlib import contextmanager

import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from .. import compat
from . import skin
from .. import i18n
from .weight_paint_settings import (ACTIONS, SCOPE, TRANSFER_FIELDS, native, _SETTING_CLASSES, _FIELDS,
                                    ALLSET_PG_weight_workspace, state, active, viewport, brush_kind, brush_tool,
                                    activate_brush)  # noqa: F401
from .weight_paint_flood import (OPERATIONS, maya_target, redistribute, flood_vertices, flood_settings,
                                 flood)  # noqa: F401


class ALLSET_OT_weight_tool(bpy.types.Operator):
    bl_idname = 'allset.weight_tool'
    bl_label = 'Weight Paint Tool'
    bl_options = {'REGISTER', 'UNDO'}
    kind: StringProperty(default='DRAW')
    blend: StringProperty(default='')

    @classmethod
    @i18n.translated
    def description(cls, context, properties):
        return {'ASSETS': 'Browse Blender weight-paint brush assets',
                'DRAW': 'Paint weights with the chosen blend operation',
                'BLUR': 'Smooth weights across neighboring vertices',
                'AVERAGE': 'Paint the average weight under the brush',
                'SMEAR': 'Drag weights along the direction of your stroke',
                'LINEAR': 'Drag in the viewport to paint a linear weight gradient',
                'RADIAL': 'Drag in the viewport to paint a radial weight gradient',
                'SAMPLE': 'Click the mesh to sample its weight into Value',
                'SAMPLE_GROUP': 'Click the mesh to choose an influence under the cursor'}.get(properties.kind, 'Weight Paint Tool')

    @classmethod
    def poll(cls, context):
        return active(context)

    def execute(self, context):
        try:
            if self.kind == 'ASSETS':
                with viewport(context):
                    bpy.ops.wm.call_asset_shelf_popover('INVOKE_DEFAULT', name='VIEW3D_AST_brush_weight_paint')
            elif self.kind in {'DRAW', 'BLUR', 'AVERAGE', 'SMEAR'}:
                activate_brush(context, self.kind, self.blend or None)
            else:
                tool = {'LINEAR': 'builtin.gradient', 'RADIAL': 'builtin.gradient',
                        'SAMPLE': 'builtin.sample_weight', 'SAMPLE_GROUP': 'builtin.sample_vertex_group'}[self.kind]
                with viewport(context) as ctx:
                    bpy.ops.wm.tool_set_by_id(name=tool)
                    if self.kind in {'LINEAR', 'RADIAL'}:
                        current = ctx.workspace.tools.from_space_view3d_mode('PAINT_WEIGHT', create=False)
                        current.operator_properties('paint.weight_gradient').type = self.kind
            state(context).status = ''
            return {'FINISHED'}
        except (RuntimeError, TypeError, ValueError, KeyError) as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}


class ALLSET_OT_weight_value(bpy.types.Operator):
    bl_idname = 'allset.weight_value'
    bl_label = 'Set Paint Value'
    bl_options = {'UNDO', 'INTERNAL'}
    value: FloatProperty(min=0, max=1)

    @classmethod
    def poll(cls, context):
        return active(context)

    def execute(self, context):
        ups = compat.unified_paint_settings(context.tool_settings)
        brush = context.tool_settings.weight_paint.brush
        compat.unified_value_owner(ups, brush, 'weight').weight = self.value
        return {'FINISHED'}


class ALLSET_OT_weight_mask(bpy.types.Operator):
    bl_idname = 'allset.weight_mask'
    bl_label = 'Weight Paint Selection'
    bl_options = {'REGISTER', 'UNDO'}
    action: StringProperty(default='ALL')

    @classmethod
    def poll(cls, context):
        return active(context)

    def execute(self, context):
        mesh = context.active_object.data
        if not (mesh.use_paint_mask or mesh.use_paint_mask_vertex):
            mesh.use_paint_mask_vertex = True
        prefix = 'vert' if mesh.use_paint_mask_vertex else 'face'
        try:
            with viewport(context):
                if self.action in {'ALL', 'NONE', 'INVERT'}:
                    native('paint.' + prefix + '_select_all')(
                        action={'ALL': 'SELECT', 'NONE': 'DESELECT', 'INVERT': 'INVERT'}[self.action])
                elif self.action in {'BOX', 'CIRCLE', 'LASSO'}:
                    native('view3d.select_' + self.action.lower())('INVOKE_DEFAULT')
                elif self.action == 'REVEAL':
                    bpy.ops.paint.face_vert_reveal()
                elif self.action in {'HIDE', 'HIDE_OTHER'}:
                    native('paint.' + prefix + '_select_hide')(unselected=self.action == 'HIDE_OTHER')
                else:
                    suffix = {'GROW': 'more', 'SHRINK': 'less', 'LINKED': 'linked', 'UNGROUPED': 'ungrouped'}[self.action]
                    native('paint.' + prefix + '_select_' + suffix)()
            return {'FINISHED'}
        except (RuntimeError, KeyError) as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}


class ALLSET_OT_weight_curve(bpy.types.Operator):
    bl_idname = 'allset.weight_curve'
    bl_label = 'Draw Paint Curve'

    def execute(self, context):
        with viewport(context):
            if not bpy.ops.paintcurve.draw.poll():
                self.report({'WARNING'}, 'Create a Paint Curve before drawing it')
                return {'CANCELLED'}
            bpy.ops.paintcurve.draw('INVOKE_DEFAULT')
        return {'FINISHED'}


class ALLSET_OT_weight_influence(bpy.types.Operator):
    bl_idname = 'allset.weight_influence'
    bl_label = 'Influence Locks'
    bl_options = {'UNDO'}
    action: EnumProperty(items=[('LOCK', 'Lock all', ''), ('UNLOCK', 'Unlock all', ''),
                               ('OTHERS', 'Lock unselected', ''), ('INVERT', 'Invert locks', ''),
                               ('LOCK_SELECTED', 'Lock selected joints', ''),
                               ('UNLOCK_SELECTED', 'Unlock selected joints', ''),
                               ('LOCK_OTHERS', 'Lock Inverse Selection', ''),
                               ('UNLOCK_OTHERS', 'Unlock other influences', ''),
                               ('JOINT', 'Select influence joint', '')])

    @classmethod
    def poll(cls, context):
        return active(context)

    def execute(self, context):
        mesh = context.active_object
        groups = list(mesh.vertex_groups) if state(context).show_all else skin.influences(mesh)
        vg = mesh.vertex_groups.active
        if self.action == 'JOINT':
            mod = skin.armature_modifier(mesh)
            pb = mod.object.pose.bones.get(vg.name) if mod and vg else None
            if pb is None:
                return {'CANCELLED'}
            from ..ui.channel_box import set_bone_selected
            for bone in mod.object.pose.bones:
                set_bone_selected(bone, bone == pb)
            mod.object.data.bones.active = pb.bone
        else:
            selected = picked_influences(context, mesh)
            for group in groups:
                if self.action in {'LOCK_SELECTED', 'UNLOCK_SELECTED'}:
                    if group.name in selected:
                        group.lock_weight = self.action == 'LOCK_SELECTED'
                elif self.action in {'LOCK_OTHERS', 'UNLOCK_OTHERS'}:      # Maya Lock / Unlock Unselected
                    if group.name not in selected:
                        group.lock_weight = self.action == 'LOCK_OTHERS'
                else:
                    group.lock_weight = (not group.lock_weight if self.action == 'INVERT' else
                                         group != vg if self.action == 'OTHERS' else self.action == 'LOCK')
        return {'FINISHED'}


class ALLSET_OT_weight_workspace(bpy.types.Operator):
    bl_idname = 'allset.weight_workspace'
    bl_label = 'Paint Skin Weights Workspace'

    def execute(self, context):
        if not active(context):
            result = bpy.ops.allset.paint_skin_weights('EXEC_DEFAULT')
            if 'FINISHED' not in result:
                return result
        from ..ui import tool_dock
        if tool_dock.show(context, width=400) is None:
            self.report({'WARNING'}, 'Open a modeling viewport to show Paint Skin Weights')
            return {'CANCELLED'}
        return {'FINISHED'}


def locked_snapshot(mesh):
    locked = {g.index: g.name for g in mesh.vertex_groups if g.lock_weight}
    result = {name: {} for name in locked.values()}
    if locked:
        for vertex in mesh.data.vertices:
            for entry in vertex.groups:
                name = locked.get(entry.group)
                if name is not None:
                    result[name][vertex.index] = entry.weight
    return result


def restore_locked(mesh, snapshot):
    indices = {g.index: g.name for g in mesh.vertex_groups if g.name in snapshot}
    current = {name: {} for name in indices.values()}
    if indices:
        for vertex in mesh.data.vertices:
            for entry in vertex.groups:
                name = indices.get(entry.group)
                if name is not None:
                    current[name][vertex.index] = entry.weight
    for name, before in snapshot.items():
        group = mesh.vertex_groups.get(name)
        if group is None:
            continue
        after = current[name]
        remove = list(after.keys() - before.keys())
        if remove:
            group.remove(remove)
        for index, weight in before.items():
            if after.get(index) != weight:
                group.add([index], weight, 'REPLACE')


@contextmanager
def vertex_targets(mesh, indices):
    """Give native flood/smooth/normalize the same precise mask, then restore it."""
    data = mesh.data
    selected = [v.select for v in data.vertices]
    vertex_mask, face_mask = data.use_paint_mask_vertex, data.use_paint_mask
    targets = set(indices)
    try:
        data.use_paint_mask = False
        data.use_paint_mask_vertex = True
        for vertex in data.vertices:
            vertex.select = vertex.index in targets
        data.update()
        yield
    finally:
        data.use_paint_mask_vertex = vertex_mask
        data.use_paint_mask = face_mask
        for vertex, value in zip(data.vertices, selected):
            vertex.select = value
        data.update()


# --- Influences list RMB (Maya 2026) -------------------

NO_INFLUENCE = 'Please select an influence first'      # Maya's warning text


def picked_influences(context, mesh):
    """The influences "selected in the Influences list" (Maya's treeView selection): Blender's list has one active
    row, so that row. Selected joints don't count: a skeleton often stays fully selected after it is
    made or bound, which would turn Select Vertices into "every vertex"."""
    vg = mesh.vertex_groups.active
    return {vg.name} if vg is not None else set()


def affected_vertices(mesh, names):
    """Vertices whose weight in any of the named influences is > 0 (Maya Select Affected Vertices)."""
    idx = {mesh.vertex_groups[n].index for n in names if n in mesh.vertex_groups}
    return {v.index for v in mesh.data.vertices if any(e.group in idx and e.weight > 0.0 for e in v.groups)}


def show_vertex_selection(mesh):
    """Blender shows (and limits painting to) a weight-paint vertex selection only with the vertex mask on."""
    mesh.data.use_paint_mask = False
    mesh.data.use_paint_mask_vertex = True


def set_vertex_selection(mesh, indices):
    from .. import compat
    data = mesh.data
    compat.repair_selection_attributes(data)     # Blender 5.0.1: a mistyped .select_edge crashes MeshEdge.select
    keep = set(indices)
    for v in data.vertices:
        v.select = v.index in keep and not v.hide
    for e in data.edges:
        e.select = all(data.vertices[i].select for i in e.vertices)
    for f in data.polygons:
        f.select = all(data.vertices[i].select for i in f.vertices)
    data.update()


class ALLSET_OT_weight_influence_verts(bpy.types.Operator):
    """Select the vertices the influences picked in the list affect (weight > 0)"""
    bl_idname = 'allset.weight_influence_verts'
    bl_label = 'Select Vertices'
    bl_options = {'UNDO'}
    mode: EnumProperty(items=[('SET', 'Select Vertices', 'Select the vertices the picked influences affect'),
                              ('ADD', 'Add Affected Vertices', 'Add them to the vertex selection'),
                              ('REMOVE', 'Remove Affected Vertices', 'Remove them from the vertex selection')],
                       options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, properties):
        return {'SET': 'Select the vertices the picked influences affect (weight above 0)',
                'ADD': 'Add the vertices the picked influences affect to the selection',
                'REMOVE': 'Remove the vertices the picked influences affect from the selection'}[properties.mode]

    @classmethod
    def poll(cls, context):
        return active(context)

    def execute(self, context):
        mesh = context.active_object
        names = picked_influences(context, mesh)
        if not names:
            self.report({'ERROR'}, NO_INFLUENCE)
            return {'CANCELLED'}
        hit = affected_vertices(mesh, names)
        current = {v.index for v in mesh.data.vertices if v.select}
        chosen = hit if self.mode == 'SET' else current | hit if self.mode == 'ADD' else current - hit
        show_vertex_selection(mesh)
        set_vertex_selection(mesh, chosen)
        return {'FINISHED'}


# --- Skin Paint Mode (Paint / Select / Paint Select, Ctrl+. / Ctrl+,) and Select Geometry ----------------------

class ALLSET_OT_weight_skin_cluster(bpy.types.Operator):
    """Show this skin cluster's influences in the Influences list"""
    bl_idname = 'allset.weight_skin_cluster'
    bl_label = 'Skin Cluster'
    bl_options = {'INTERNAL'}

    index: IntProperty(default=0, min=0)

    def execute(self, context):
        state(context).skin_cluster = self.index
        for area in context.screen.areas if context.screen else ():
            area.tag_redraw()
        return {'FINISHED'}


class ALLSET_OT_weight_profile(bpy.types.Operator):
    """Maya brush Profile: the brush falloff (Gaussian / Soft / Solid)"""
    bl_idname = 'allset.weight_profile'
    bl_label = 'Profile'
    bl_options = {'REGISTER', 'UNDO'}

    profile: EnumProperty(items=[(k, k.title(), '') for k in ('GAUSSIAN', 'SOFT', 'SOLID', 'SQUARE')],
                          options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, properties):
        if properties.profile == 'SQUARE':
            return "Blender brushes are round: Maya's Square profile has no Blender brush"
        return f"Brush falloff {skin.PROFILE_CURVE.get(properties.profile, '').title()}"

    def execute(self, context):
        brush = context.tool_settings.weight_paint.brush
        preset = skin.PROFILE_CURVE.get(self.profile)
        if brush is None or preset is None:
            self.report({'WARNING'}, "Blender brushes are round: no Square profile")
            return {'CANCELLED'}
        if not skin._brush_set(brush, compat.brush_falloff_props(brush)[0], preset):
            self.report({'WARNING'}, "This brush is a linked asset: Blender keeps its falloff")
            return {'CANCELLED'}
        return {'FINISHED'}


PAINT_MODES = ('PAINT', 'SELECT', 'PAINT_SELECT')
MODE_LABELS = {'PAINT': 'Paint', 'SELECT': 'Select', 'PAINT_SELECT': 'Paint Select'}
_MODE_TOOLS = {'SELECT': 'builtin.select_box', 'PAINT_SELECT': 'builtin.select_circle'}
SELECT_SHAPES = {'BOX': 'builtin.select_box', 'LASSO': 'builtin.select_lasso'}


def paint_mode(context):
    """Maya's Skin Paint Mode read from the active weight-paint tool."""
    ws = context.workspace
    tool = ws.tools.from_space_view3d_mode('PAINT_WEIGHT', create=False) if ws is not None else None
    name = tool.idname if tool is not None else ''
    if name == 'builtin.select_circle':
        return 'PAINT_SELECT'
    if name.startswith('builtin.select'):
        return 'SELECT'
    return 'PAINT'


def next_mode(mode, step):
    return PAINT_MODES[(PAINT_MODES.index(mode) + step) % len(PAINT_MODES)]


class ALLSET_OT_skin_paint_mode(bpy.types.Operator):
    """Maya Skin Paint Mode: Paint weights, Select vertices, or Paint Select vertices with a brush"""
    bl_idname = 'allset.skin_paint_mode'
    bl_label = 'Skin Paint Mode'
    bl_options = {'UNDO'}
    mode: EnumProperty(items=[('PAINT', 'Paint', 'Paint weights'), ('SELECT', 'Select', 'Select vertices'),
                              ('PAINT_SELECT', 'Paint Select', 'Select vertices with a brush')],
                       options={'SKIP_SAVE'})
    step: IntProperty(default=0, options={'SKIP_SAVE', 'HIDDEN'},
                      description='1 = next mode (Ctrl+.), -1 = previous mode (Ctrl+,), 0 = the mode above')
    shape: EnumProperty(items=[('KEEP', 'Keep', 'The shape Select mode used last'),
                               ('BOX', 'Box', 'Select vertices inside a dragged box'),
                               ('LASSO', 'Lasso', 'Select vertices inside a drawn lasso')],
                        default='KEEP', options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    @i18n.translated
    def description(cls, context, properties):
        if properties.step:
            return 'Next Skin Paint Mode' if properties.step > 0 else 'Previous Skin Paint Mode'
        if properties.mode == 'SELECT' and properties.shape == 'LASSO':
            return 'Select vertices by drawing a lasso around them; Flood then fills only the selection'
        return {'PAINT': 'Paint weights with the brush',
                'SELECT': 'Select vertices (drag a box); Flood then fills only the selection',
                'PAINT_SELECT': 'Select vertices by brushing over them'}[properties.mode]

    @classmethod
    def poll(cls, context):
        return active(context)

    def execute(self, context):
        current = paint_mode(context)
        mode = next_mode(current, self.step) if self.step else self.mode
        mesh = context.active_object
        s = state(context)
        if mode == 'SELECT' and self.shape != 'KEEP':
            s.select_shape = self.shape
        try:
            if mode == 'PAINT':
                skin.set_view_tool(context, s.paint_tool or 'builtin.brush')
            else:
                if current == 'PAINT':
                    ws = context.workspace
                    tool = ws.tools.from_space_view3d_mode('PAINT_WEIGHT', create=False) if ws else None
                    s.paint_tool = tool.idname if tool is not None and tool.idname else 'builtin.brush'
                show_vertex_selection(mesh)
                from ..ui import toolbox
                toolbox.KEEP_PAINT[0] = True
                try:
                    skin.set_view_tool(context, SELECT_SHAPES.get(s.select_shape, _MODE_TOOLS[mode])
                                       if mode == 'SELECT' else _MODE_TOOLS[mode])
                finally:
                    toolbox.KEEP_PAINT[0] = False
        except RuntimeError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        from .. import results
        results.result(self, 'Paint mode: ' + MODE_LABELS[mode])
        return {'FINISHED'}


class ALLSET_OT_select_geometry(bpy.types.Operator):
    """Select the whole mesh (drop the vertex selection) and keep painting"""
    bl_idname = 'allset.select_geometry'
    bl_label = 'Select Geometry'
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        return active(context)

    def execute(self, context):
        mesh = context.active_object
        set_vertex_selection(mesh, ())
        mesh.data.use_paint_mask_vertex = False
        mesh.data.use_paint_mask = False
        mesh.select_set(True)
        return {'FINISHED'}


class ALLSET_OT_paint_copy_vertex_weights(bpy.types.Operator):
    """Maya Copy Vertex Weights while painting: remember the active (else first selected) vertex's weights"""
    bl_idname = 'allset.paint_copy_vertex_weights'
    bl_label = 'Copy Vertex Weights'

    @classmethod
    def poll(cls, context):
        return active(context)

    def execute(self, context):
        import bmesh
        mesh = context.active_object
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh.data)
            act = bm.select_history.active
            index = act.index if isinstance(act, bmesh.types.BMVert) and act.select else None
        finally:
            bm.free()
        if index is None:
            index = next((v.index for v in mesh.data.vertices if v.select and not v.hide), None)
        if index is None:
            self.report({'WARNING'}, 'Select a vertex')
            return {'CANCELLED'}
        names = {vg.index: vg.name for vg in mesh.vertex_groups}
        skin._VERTEX_CLIPBOARD.clear()
        skin._VERTEX_CLIPBOARD.update({names[e.group]: e.weight for e in mesh.data.vertices[index].groups
                                       if e.group in names})
        from .. import results
        results.result(self, f"Copied {len(skin._VERTEX_CLIPBOARD)} weight(s)")
        return {'FINISHED'}


class ALLSET_OT_paint_paste_vertex_weights(bpy.types.Operator):
    """Maya Paste Vertex Weights while painting: give the selected vertices the copied weights"""
    bl_idname = 'allset.paint_paste_vertex_weights'
    bl_label = 'Paste Vertex Weights'
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        return active(context) and bool(skin._VERTEX_CLIPBOARD)

    def execute(self, context):
        mesh = context.active_object
        targets = [v.index for v in mesh.data.vertices if v.select and not v.hide]
        if not targets:
            self.report({'WARNING'}, 'Select vertices to paste the weights on')
            return {'CANCELLED'}
        groups = {name: (mesh.vertex_groups.get(name) or mesh.vertex_groups.new(name=name))
                  for name in skin._VERTEX_CLIPBOARD}
        for vg in mesh.vertex_groups:
            if vg.name not in groups:
                vg.remove(targets)
        for name, w in skin._VERTEX_CLIPBOARD.items():
            groups[name].add(targets, w, 'REPLACE')
        mesh.data.update()
        from .. import results
        results.result(self, f"Pasted weights on {len(targets)} vertices")
        return {'FINISHED'}


class ALLSET_OT_paint_reflection(bpy.types.Operator):
    """Maya Toggle Reflection while painting: mirror the paint across X"""
    bl_idname = 'allset.paint_reflection'
    bl_label = 'Toggle Reflection'
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        return active(context)

    def execute(self, context):
        data = context.active_object.data
        data.use_mirror_x = not data.use_mirror_x
        from .. import results
        results.result(self, 'Reflection ' + ('on (X)' if data.use_mirror_x else 'off'))
        return {'FINISHED'}


class ALLSET_OT_weight_action(bpy.types.Operator):
    bl_idname = 'allset.weight_action'
    bl_label = 'Edit Skin Weights'
    bl_options = {'REGISTER', 'UNDO'}
    action: EnumProperty(items=[(key, label, label) for key, (label, op) in ACTIONS.items()])

    @classmethod
    @i18n.translated
    def description(cls, context, properties):
        return ACTIONS.get(properties.action, ('Edit Skin Weights', ''))[0] + ': configure and apply; locked influences stay protected'

    @classmethod
    def poll(cls, context):
        return active(context) and len(context.active_object.vertex_groups) > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=380, title=ACTIONS[self.action][0], confirm_text='Apply')

    def draw(self, context):
        layout = self.layout
        settings = getattr(state(context), self.action.lower())
        layout.use_property_split = True
        layout.use_property_decorate = False
        for name in _FIELDS[self.action]:
            if self.action in {'AUTO', 'ENVELOPE'} and name == 'type':
                continue
            layout.prop(settings, name)
        if not _FIELDS[self.action]:
            layout.label(text=('Assign the current Value to the masked or visible vertices.' if self.action == 'SET'
                               else 'Normalize the active influence to its maximum weight.'))
        note = layout.row()
        note.active = False
        note.label(text='Locked influences are preserved.', icon='LOCKED')
        if context.active_object.data.use_paint_mask_vertex or context.active_object.data.use_paint_mask:
            layout.label(text='Selection mask limits affected vertices.', icon='RESTRICT_SELECT_OFF')

    def execute(self, context):
        mesh = context.active_object
        settings = getattr(state(context), self.action.lower())
        values = {k: getattr(settings, k) for k in _FIELDS[self.action] if k != 'source'}
        if self.action in {'AUTO', 'ENVELOPE'}:
            values['type'] = 'AUTOMATIC' if self.action == 'AUTO' else 'ENVELOPES'
        if self.action == 'TRANSFER':
            source = settings.source
            if source is None or source == mesh or source.name not in context.view_layer.objects:
                self.report({'WARNING'}, 'Choose a different source mesh in this view layer')
                return {'CANCELLED'}
            values.update(data_type='VGROUP_WEIGHTS', use_reverse_transfer=True)
            # Blender's reverse-transfer flag also reverses the two layer enums.
            # Keep the workspace labels in source -> painted mesh order.
            values['layers_select_src'], values['layers_select_dst'] = (
                values['layers_select_dst'], values['layers_select_src'])
        snapshot = locked_snapshot(mesh)
        selected = list(context.selected_objects)
        try:
            with viewport(context):
                if self.action == 'TRANSFER':
                    for ob in context.selected_objects:
                        if ob != mesh:
                            ob.select_set(False)
                    settings.source.select_set(True)
                op = native(ACTIONS[self.action][1])
                if not op.poll():
                    raise RuntimeError('This operation needs a skinned mesh and a valid influence selection')
                result = op('EXEC_DEFAULT', **values)
                if 'FINISHED' not in result:
                    return result
            state(context).status = ACTIONS[self.action][0] + ' complete'
            return {'FINISHED'}
        except (RuntimeError, TypeError, ValueError) as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        finally:
            restore_locked(mesh, snapshot)
            if self.action == 'TRANSFER':
                for ob in context.selected_objects:
                    if ob not in selected:
                        ob.select_set(False)
                for ob in selected:
                    ob.select_set(True)
                context.view_layer.objects.active = mesh


classes = (*_SETTING_CLASSES, ALLSET_PG_weight_workspace, ALLSET_OT_weight_tool,
           ALLSET_OT_weight_value, ALLSET_OT_weight_mask, ALLSET_OT_weight_influence, ALLSET_OT_weight_action,
           ALLSET_OT_weight_workspace, ALLSET_OT_weight_curve, ALLSET_OT_weight_influence_verts,
           ALLSET_OT_skin_paint_mode, ALLSET_OT_select_geometry, ALLSET_OT_weight_skin_cluster, ALLSET_OT_weight_profile, ALLSET_OT_paint_copy_vertex_weights,
           ALLSET_OT_paint_paste_vertex_weights, ALLSET_OT_paint_reflection)


def register_props():
    bpy.types.WindowManager.allset_weight_workspace = PointerProperty(type=ALLSET_PG_weight_workspace)
    # Good skinning defaults without changing mesh/brush data.
    s = bpy.context.window_manager.allset_weight_workspace
    s.transfer.vert_mapping = 'POLYINTERP_NEAREST'
    s.transfer.layers_select_src = 'ALL'
    s.transfer.layers_select_dst = 'NAME'


def unregister_props():
    if hasattr(bpy.types.WindowManager, 'allset_weight_workspace'):
        del bpy.types.WindowManager.allset_weight_workspace
