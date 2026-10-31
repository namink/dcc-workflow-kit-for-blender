# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format
'Functional toolbar actions, using Blender data and viewport operators.'
import bpy
from bpy.props import EnumProperty, StringProperty
from mathutils import Matrix
from . import runtime
from .operators import Active, viewport_override
ACTIONS = (('LINK', _msg('Link / Parent')), ('UNLINK', _msg('Unlink Selection')), ('BOX', _msg('Rectangular Selection')), ('CIRCLE', _msg('Circular Selection')), ('LASSO', _msg('Lasso Selection')), ('ALIGN', _msg('Quick Align')), ('PIVOT', _msg('Center to Object')), ('PIVOT_WORLD', _msg('Align to World')), ('PIVOT_RESET', _msg('Reset Pivot')), ('CURSOR_VIEW', _msg('Working Pivot Align To View')), ('MIRROR', _msg('Symmetry Modifier')), ('ARRAY', _msg('Array Modifier')), ('SMOOTH', _msg('Smooth Shading')), ('FLAT', _msg('Flat Shading')), ('HIDE', _msg('Hide Selection')), ('UNHIDE', _msg('Unhide All')), ('FRAME', _msg('Zoom Extents')), ('ISOLATE', _msg('Isolate Selection')), ('FREEZE', _msg('Freeze Selection')), ('FREEZE_UNSELECTED', _msg('Freeze Unselected')), ('UNFREEZE', _msg('Unfreeze All')), ('RENDER', _msg('Render')), ('IPR', _msg('Interactive Render')), ('DENOISE', _msg('Denoiser')), ('AOVS', _msg('Render Passes')), ('LIGHT_GROUPS', _msg('Light Groups')))

class BSM_OT_toolbar_action(Active, bpy.types.Operator):
    bl_idname = 'bsm.toolbar_action'
    bl_label = _msg('Max Toolbar Action')
    bl_options = {'REGISTER', 'UNDO'}
    action: EnumProperty(items=tuple(((a, n, '') for (a, n) in ACTIONS)), translation_context=_msg('DCCWorkflowKit.Max'))

    @classmethod
    def description(cls, context, properties):
        return dict(ACTIONS).get(properties.action, '')

    def execute(self, context):
        from .commands import freeze
        state = context.window_manager.bsm
        selected = [o for o in context.view_layer.objects if o.select_get()]
        a = self.action
        if a in {'FREEZE', 'FREEZE_UNSELECTED', 'UNFREEZE'}:
            for obj in context.view_layer.objects:
                if a == 'FREEZE' and obj.select_get() or (a == 'FREEZE_UNSELECTED' and (not obj.select_get())):
                    freeze(obj, True)
                    obj.select_set(False)
                elif a == 'UNFREEZE':
                    freeze(obj, False)
            return {'FINISHED'}
        if a in {'RENDER', 'IPR'}:
            space = viewport_override(context)['area'].spaces.active
            if a == 'IPR' or state.render_mode == 'ACTIVESHADE':
                from .commands import toggle_activeshade
                toggle_activeshade(space)
                runtime.redraw()
                return {'FINISHED'}
            return bpy.ops.bsm.render_view()
        if a == 'DENOISE':
            scene = context.scene
            if scene.render.engine == 'CYCLES':
                scene.cycles.use_denoising = not scene.cycles.use_denoising
                self.report({'INFO'}, _dcc_ui_text(_dcc_format('Denoiser {0}', 'on' if scene.cycles.use_denoising else 'off')))
            else:
                self.report({'WARNING'}, _dcc_ui_text(_msg('Denoising is a Cycles render setting')))
            return {'FINISHED'}
        if a in {'AOVS', 'LIGHT_GROUPS'}:
            return bpy.ops.bsm.settings_popup('INVOKE_DEFAULT', kind=a)
        if a == 'CURSOR_VIEW':
            r3d = viewport_override(context)['region'].data
            context.scene.cursor.rotation_mode = 'QUATERNION'
            context.scene.cursor.rotation_quaternion = r3d.view_rotation
            return {'FINISHED'}
        if a in {'PIVOT_WORLD', 'PIVOT_RESET'}:
            with context.temp_override(**viewport_override(context)):
                if a == 'PIVOT_RESET':
                    bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')
                bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
            return {'FINISHED'}
        with context.temp_override(**viewport_override(context)):
            if a in {'BOX', 'CIRCLE', 'LASSO'}:
                state.region_type = {'BOX': 'RECT', 'CIRCLE': 'CIRCLE', 'LASSO': 'LASSO'}[a]
                bpy.ops.wm.tool_set_by_id(name={'BOX': 'builtin.select_box', 'CIRCLE': 'builtin.select_circle', 'LASSO': 'builtin.select_lasso'}[a])
            elif a == 'LINK':
                bpy.ops.object.parent_set('INVOKE_DEFAULT', keep_transform=True)
            elif a == 'UNLINK':
                bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
            elif a == 'ALIGN':
                bpy.ops.view3d.snap_selected_to_active()
            elif a == 'PIVOT':
                bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')
            elif a == 'MIRROR':
                bpy.ops.bsm.modifier(kind='MIRROR')
            elif a == 'ARRAY':
                bpy.ops.bsm.modifier(kind='ARRAY')
            elif a == 'SMOOTH':
                bpy.ops.object.shade_smooth()
            elif a == 'FLAT':
                bpy.ops.object.shade_flat()
            elif a == 'HIDE':
                bpy.ops.object.hide_view_set(unselected=False)
            elif a == 'UNHIDE':
                bpy.ops.object.hide_view_clear()
            elif a == 'FRAME':
                bpy.ops.view3d.view_all(center=False)
            elif a == 'ISOLATE':
                bpy.ops.view3d.localview(frame_selected=True)
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_selection_set(Active, bpy.types.Operator):
    bl_idname = 'bsm.selection_set'
    bl_label = _msg('Create Selection Set')
    bl_options = {'REGISTER', 'UNDO'}
    name: StringProperty(name=_msg('Set Name'), default=_msg('Selection Set'), translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300)

    def execute(self, context):
        selected = [o for o in context.view_layer.objects if o.select_get()]
        if not selected:
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select objects before creating a selection set')))
            return {'CANCELLED'}
        create_set(context, self.name, selected)
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def create_set(context, name, objects):
    group = bpy.data.collections.new(name)
    group['bsm_selection_set'] = True
    context.scene.collection.children.link(group)
    for obj in objects:
        group.objects.link(obj)
    return group

class BSM_OT_select_set(Active, bpy.types.Operator):
    bl_idname = 'bsm.select_set'
    bl_label = _msg('Recall Selection Set')
    name: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        group = bpy.data.collections.get(self.name)
        if not group:
            return {'CANCELLED'}
        members = set(group.all_objects)
        for obj in context.view_layer.objects:
            if not obj.hide_select:
                obj.select_set(obj in members)
                if obj in members:
                    context.view_layer.objects.active = obj
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_selection_sets(bpy.types.Menu):
    bl_label = _msg('Named Selection Sets')

    def draw(self, context):
        groups = [c for c in bpy.data.collections if c.get('bsm_selection_set')]
        if not groups:
            self.layout.label(text=_dcc_ui_text(_msg('No selection sets')))
        for group in groups:
            self.layout.operator('bsm.select_set', text=_dcc_ui_text(group.name)).name = group.name
        self.layout.separator()
        self.layout.operator('bsm.manage_sets', text=_dcc_ui_text(_msg('Manage Selection Sets...')))
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_transform_typein(Active, bpy.types.Operator):
    bl_idname = 'bsm.transform_typein'
    bl_label = _msg('Transform Type-In')

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=360)

    def execute(self, context):
        return {'FINISHED'}

    def draw(self, context):
        obj = context.view_layer.objects.active
        tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
        name = {'builtin.rotate': _msg('Rotate'), 'bsm.max_rotate': _msg('Rotate'), 'builtin.scale': _msg('Scale'), 'bsm.max_scale': _msg('Scale')}.get(tool.idname if tool else '', _msg('Move'))
        self.layout.label(text=_dcc_ui_text(_dcc_format('{0} Transform Type-In', name)))
        if not obj:
            self.layout.label(text=_dcc_ui_text(_msg('Select an object')))
            return
        state = context.window_manager.bsm
        attr = {_msg('Move'): 'location', _msg('Rotate'): 'rotation_euler', _msg('Scale'): 'scale'}[name]
        row = self.layout.row()
        column = row.box().column()
        column.label(text=_dcc_ui_text(_msg('Absolute:World')))
        column.prop(obj, attr, text=_dcc_ui_text(''))
        column = row.box().column()
        column.label(text=_dcc_ui_text(_msg('Offset:World')))
        column.prop(state, 'offset_vector', text=_dcc_ui_text(''))
        column.operator('bsm.apply_offset', text=_dcc_ui_text(_msg('Apply Offset'))).attr = attr
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_apply_offset(Active, bpy.types.Operator):
    bl_idname = 'bsm.apply_offset'
    bl_label = _msg('Apply Offset')
    bl_options = {'REGISTER', 'UNDO'}
    attr: StringProperty(default='location', translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        state = context.window_manager.bsm
        for obj in [o for o in context.view_layer.objects if o.select_get()]:
            value = getattr(obj, self.attr)
            for i in range(3):
                value[i] += state.offset_vector[i] if self.attr != 'scale' else 0
                if self.attr == 'scale':
                    value[i] *= 1 + state.offset_vector[i] / 100.0
        state.offset_vector = (0, 0, 0)
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')
CLASSES = (BSM_OT_toolbar_action, BSM_OT_selection_set, BSM_OT_select_set, BSM_MT_selection_sets, BSM_OT_transform_typein, BSM_OT_apply_offset)
