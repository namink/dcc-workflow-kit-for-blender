# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format, error_text as _dcc_ui_error
"Material and animation workflows implemented with Blender's native data.\n\nThese controls edit Blender shaders and action slots. They do not emulate or\nimport proprietary material types, animation controllers, or renderer plugins.\n"
import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from . import runtime

def _editable_objects(context):
    return [obj for obj in context.selected_objects if obj.is_editable]

def _material_objects(context):
    return [obj for obj in _editable_objects(context) if getattr(obj, 'data', None) is not None and hasattr(obj.data, 'materials') and obj.data.is_editable]

def _assign_material(obj, material):
    index = next((i for (i, slot) in enumerate(obj.material_slots) if slot.material == material), -1)
    if index < 0:
        obj.data.materials.append(material)
        index = len(obj.material_slots) - 1
    obj.active_material_index = index
    if obj.type == 'MESH':
        if obj.mode == 'EDIT':
            import bmesh
            mesh = bmesh.from_edit_mesh(obj.data)
            for face in mesh.faces:
                if face.select:
                    face.material_index = index
            bmesh.update_edit_mesh(obj.data)
        else:
            for polygon in obj.data.polygons:
                polygon.material_index = index

class _ActiveOperator:

    @classmethod
    def poll(cls, context):
        return runtime.is_active()

class BSM_OT_material_new(_ActiveOperator, bpy.types.Operator):
    bl_idname = 'bsm.material_new'
    bl_label = _msg('New Material')
    bl_description = _msg('Create a Blender Principled material and assign it to the active object')
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objects = _material_objects(context)
        obj = context.view_layer.objects.active
        if obj not in objects:
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select an editable object that supports materials')))
            return {'CANCELLED'}
        material = bpy.data.materials.new(_msg('Max Material'))
        material.use_nodes = True
        _assign_material(obj, material)
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_material_assign(_ActiveOperator, bpy.types.Operator):
    bl_idname = 'bsm.material_assign'
    bl_label = _msg('Assign Material to Selection')
    bl_description = _msg('Assign the active material to selected objects, or selected faces in Edit Mode')
    bl_options = {'REGISTER', 'UNDO'}
    material_name: StringProperty(name=_msg('Material'), translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        material = bpy.data.materials.get(self.material_name) if self.material_name else getattr(context.view_layer.objects.active, 'active_material', None)
        objects = _material_objects(context)
        if not material or not objects:
            self.report({'WARNING'}, _dcc_ui_text(_msg('Choose a material and select editable objects')))
            return {'CANCELLED'}
        for obj in objects:
            _assign_material(obj, material)
        self.report({'INFO'}, _dcc_ui_text(_dcc_format('Assigned {0} to {1} object(s)', material.name, len(objects))))
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_material_duplicate(_ActiveOperator, bpy.types.Operator):
    bl_idname = 'bsm.material_duplicate'
    bl_label = _msg('Duplicate Material')
    bl_description = _msg('Make an independent copy of the active material in its current slot')
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if obj not in _material_objects(context) or not obj.active_material:
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select an object with a material')))
            return {'CANCELLED'}
        obj.active_material = obj.active_material.copy()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_material_remove_slot(_ActiveOperator, bpy.types.Operator):
    bl_idname = 'bsm.material_remove_slot'
    bl_label = _msg('Remove Material Slot')
    bl_description = _msg('Remove the active material slot; keep the material datablock')
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if obj not in _material_objects(context) or not obj.material_slots or obj.mode != 'OBJECT':
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select an object with material slots in Object Mode')))
            return {'CANCELLED'}
        obj.data.materials.pop(index=obj.active_material_index)
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def _rotation_path(obj):
    if obj.rotation_mode == 'QUATERNION':
        return 'rotation_quaternion'
    if obj.rotation_mode == 'AXIS_ANGLE':
        return 'rotation_axis_angle'
    return 'rotation_euler'

def _transform_targets(context):
    if context.mode == 'POSE':
        return list(context.selected_pose_bones or [])
    state = getattr(context.window_manager, 'bsm', None)
    named = bpy.data.collections.get(state.key_set) if state and state.key_set else None
    if named is not None:
        return [obj for obj in named.all_objects if obj.is_editable]
    return _editable_objects(context)

def _paths(target, channels):
    if channels == 'FILTERED':
        chosen = bpy.context.window_manager.bsm.key_filter
        return [p for c in ('LOCATION', 'ROTATION', 'SCALE') if c in chosen for p in _paths(target, c)]
    paths = []
    if channels in {'ALL', 'LOCATION'}:
        paths.append('location')
    if channels in {'ALL', 'ROTATION'}:
        paths.append(_rotation_path(target))
    if channels in {'ALL', 'SCALE'}:
        paths.append('scale')
    return paths

class BSM_OT_keyframe(_ActiveOperator, bpy.types.Operator):
    bl_idname = 'bsm.keyframe'
    bl_label = _msg('Set Transform Keys')
    bl_description = _msg('Insert Blender transform keys for selected objects or pose bones at the current frame')
    bl_options = {'REGISTER', 'UNDO'}
    channels: EnumProperty(name=_msg('Channels'), items=(('ALL', _msg('Position / Rotation / Scale'), ''), ('LOCATION', _msg('Position'), ''), ('ROTATION', _msg('Rotation'), ''), ('SCALE', _msg('Scale'), ''), ('FILTERED', _msg('Key Filters'), _msg('Channels chosen in Key Filters'))), default='ALL', translation_context=_msg('DCCWorkflowKit.Max'))
    delete: BoolProperty(name=_msg('Delete Keys'), default=False, translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        targets = _transform_targets(context)
        if not targets:
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select editable objects or pose bones')))
            return {'CANCELLED'}
        count = 0
        for target in targets:
            for path in _paths(target, self.channels):
                try:
                    if self.delete:
                        ok = target.keyframe_delete(data_path=path, frame=context.scene.frame_current)
                    else:
                        ok = target.keyframe_insert(data_path=path, frame=context.scene.frame_current, group=getattr(target, 'name', _msg('Transforms')))
                    count += bool(ok)
                except (RuntimeError, TypeError) as error:
                    self.report({'WARNING'}, _dcc_ui_error(error))
        if not count:
            self.report({'WARNING'}, _dcc_ui_text(_msg('No matching keys removed') if self.delete else _msg('No keys inserted')))
            return {'CANCELLED'}
        self.report({'INFO'}, _dcc_ui_text(_dcc_format('{0} {1} transform channel group(s)', 'Removed' if self.delete else 'Keyed', count)))
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def _action_fcurves(obj):
    """Return curves of this object's active slot, including Blender 5 actions."""
    animation = obj.animation_data
    if not animation or not animation.action:
        return []
    action = animation.action
    slot = getattr(animation, 'action_slot', None)
    if getattr(action, 'is_action_layered', False):
        curves = []
        for layer in action.layers:
            for strip in layer.strips:
                for bag in getattr(strip, 'channelbags', []):
                    if slot is not None and bag.slot_handle == slot.handle:
                        curves.extend(bag.fcurves)
        return curves
    return list(getattr(action, 'fcurves', []))

class BSM_OT_key_interpolation(_ActiveOperator, bpy.types.Operator):
    bl_idname = 'bsm.key_interpolation'
    bl_label = _msg('Set Key Interpolation')
    bl_description = _msg('Set interpolation on keys at the current frame for selected objects or selected pose bones')
    bl_options = {'REGISTER', 'UNDO'}
    mode: EnumProperty(name=_msg('Interpolation'), items=(('BEZIER', _msg('Bezier'), ''), ('LINEAR', _msg('Linear'), ''), ('CONSTANT', _msg('Constant'), '')), default='BEZIER', translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        frame = context.scene.frame_current
        count = 0
        if context.mode == 'POSE':
            objects = [context.view_layer.objects.active] if context.view_layer.objects.active else []
            prefixes = tuple((bone.path_from_id() + '.' for bone in context.selected_pose_bones or []))
        else:
            objects = _editable_objects(context)
            prefixes = None
        for obj in objects:
            for curve in _action_fcurves(obj):
                if prefixes is not None and (not curve.data_path.startswith(prefixes)):
                    continue
                for point in curve.keyframe_points:
                    if abs(point.co.x - frame) < 0.0001:
                        point.interpolation = self.mode
                        count += 1
                curve.update()
            obj.update_tag()
        if not count:
            self.report({'WARNING'}, _dcc_ui_text(_msg('No keys on the current frame')))
            return {'CANCELLED'}
        self.report({'INFO'}, _dcc_ui_text(_dcc_format('Updated {0} key(s)', count)))
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def draw_materials(layout, context):
    """Compact material controls, shared by the command panel and editor popup."""
    row = layout.row(align=True)
    row.operator('bsm.editor', text=_dcc_ui_text(_msg('Node Editor')), icon='NODETREE').kind = 'MATERIAL'
    row.operator('bsm.editor', text=_dcc_ui_text(_msg('Compact')), icon='MATERIAL').kind = 'COMPACT'
    layout.label(text=_dcc_ui_text(_msg('Blender Principled materials')), icon='INFO')
    obj = context.view_layer.objects.active
    if not obj or not getattr(obj, 'data', None) or (not hasattr(obj.data, 'materials')):
        layout.label(text=_dcc_ui_text(_msg('Select an object with material support.')))
        return
    row = layout.row()
    row.template_list(_msg('MATERIAL_UL_matslots'), '', obj, 'material_slots', obj, 'active_material_index', rows=3)
    col = row.column(align=True)
    col.operator('bsm.material_new', text=_dcc_ui_text(''), icon='ADD')
    remove = col.row()
    remove.enabled = obj.mode == 'OBJECT'
    remove.operator('bsm.material_remove_slot', text=_dcc_ui_text(''), icon='REMOVE')
    layout.template_ID(obj, 'active_material', new='bsm.material_new')
    material = obj.active_material
    if not material:
        return
    row = layout.row(align=True)
    row.operator('bsm.material_assign', text=_dcc_ui_text(_msg('Assign to Selection')), icon='CHECKMARK')
    row.operator('bsm.material_duplicate', text=_dcc_ui_text(''), icon='DUPLICATE')
    layout.prop(material, 'name', text=_dcc_ui_text(_msg('Name')))
    if material.use_nodes and material.node_tree:
        shader = next((node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED'), None)
        if shader:
            for name in (_msg('Base Color'), _msg('Metallic'), _msg('Roughness'), 'IOR', _msg('Alpha')):
                socket = shader.inputs.get(name)
                if socket and (not socket.is_linked):
                    layout.prop(socket, 'default_value', text=_dcc_ui_text(name))
                elif socket:
                    layout.label(text=_dcc_ui_text(_dcc_format('{0}: linked in Node Editor', name)), icon='LINKED')
        else:
            layout.label(text=_dcc_ui_text(_msg('Edit this shader in Node Editor.')))
    else:
        layout.prop(material, 'diffuse_color', text=_dcc_ui_text(_msg('Viewport Color')))
        layout.prop(material, 'metallic')
        layout.prop(material, 'roughness')
    layout.separator()
    layout.prop(material, 'diffuse_color', text=_dcc_ui_text(_msg('Viewport Color')))

def draw_animation(layout, context):
    scene = context.scene
    row = layout.row(align=True)
    row.prop(scene.tool_settings, 'use_keyframe_insert_auto', text=_dcc_ui_text(_msg('Auto Key')), icon='REC', toggle=True)
    row.prop(scene.tool_settings, 'auto_keying_mode', text=_dcc_ui_text(''))
    layout.label(text=_dcc_ui_text(_msg('Auto Key uses Blender keying rules.')), icon='INFO')
    row = layout.row(align=True)
    row.operator('bsm.keyframe', text=_dcc_ui_text(_msg('Set Keys')), icon='KEY_HLT')
    row.operator('bsm.keyframe', text=_dcc_ui_text(_msg('Delete Keys')), icon='KEY_DEHLT').delete = True
    layout.operator_menu_enum('bsm.keyframe', 'channels', text=_msg('Key Channels'))
    layout.operator_menu_enum('bsm.key_interpolation', 'mode', text=_msg('Current Key Interpolation'))
    row = layout.row(align=True)
    row.prop(scene, 'frame_start', text=_dcc_ui_text(_msg('Start')))
    row.prop(scene, 'frame_end', text=_dcc_ui_text(_msg('End')))
    layout.prop(scene, 'frame_current', text=_dcc_ui_text(_msg('Time')))
    row = layout.row(align=True)
    row.operator('screen.frame_jump', text=_dcc_ui_text(''), icon='REW').end = False
    row.operator('screen.keyframe_jump', text=_dcc_ui_text(''), icon='PREV_KEYFRAME').next = False
    row.operator('screen.animation_play', text=_dcc_ui_text(''), icon='PLAY_REVERSE').reverse = True
    row.operator('screen.animation_play', text=_dcc_ui_text(''), icon='PAUSE' if context.screen and context.screen.is_animation_playing else 'PLAY')
    row.operator('screen.keyframe_jump', text=_dcc_ui_text(''), icon='NEXT_KEYFRAME').next = True
    row.operator('screen.frame_jump', text=_dcc_ui_text(''), icon='FF').end = True
    row = layout.row(align=True)
    row.operator('bsm.editor', text=_dcc_ui_text(_msg('Curve Editor')), icon='GRAPH').kind = 'GRAPH'
    row.operator('bsm.editor', text=_dcc_ui_text(_msg('Dope Sheet')), icon='ACTION').kind = 'DOPESHEET'
CLASSES = (BSM_OT_material_new, BSM_OT_material_assign, BSM_OT_material_duplicate, BSM_OT_material_remove_slot, BSM_OT_keyframe, BSM_OT_key_interpolation)
