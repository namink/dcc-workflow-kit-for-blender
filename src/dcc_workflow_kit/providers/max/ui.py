# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format
'Session state, the 3ds Max menu bar and the Scene Explorer menus.'
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty, StringProperty
from . import runtime, params

def _changed(name):
    return lambda self, context: runtime.on_state(context, name)

class BSM_State(bpy.types.PropertyGroup):
    explorer_search: StringProperty(name=_msg('Search Scene'), update=lambda self, context: runtime.redraw(), translation_context=_msg('DCCWorkflowKit.Max'))
    explorer_scroll: IntProperty(default=0, min=0, translation_context=_msg('DCCWorkflowKit.Max'))
    explorer_filter: EnumProperty(name=_msg('Display'), options={'ENUM_FLAG'}, items=tuple(((k, k.title(), '') for k in ('MESH', 'CURVE', 'LIGHT', 'CAMERA', 'EMPTY', 'FIELD', 'GROUP', 'XREF', 'ARMATURE', 'CONTAINER', 'FROZEN', 'HIDDEN'))), default={'MESH', 'CURVE', 'LIGHT', 'CAMERA', 'EMPTY', 'FIELD', 'GROUP', 'XREF', 'ARMATURE', 'CONTAINER', 'FROZEN', 'HIDDEN'}, translation_context=_msg('DCCWorkflowKit.Max'))
    tool_search: StringProperty(name=_msg('Search All Objects'), translation_context=_msg('DCCWorkflowKit.Max'))
    finite_grid: BoolProperty(name=_msg('Show Home Grid'), default=True, translation_context=_msg('DCCWorkflowKit.Max'))
    grid_spacing: FloatProperty(name=_msg('Grid Spacing'), default=1.0, min=0.0001, subtype='DISTANCE', unit='LENGTH', translation_context=_msg('DCCWorkflowKit.Max'))
    next_name: StringProperty(name=_msg('Name'), translation_context=_msg('DCCWorkflowKit.Max'))
    next_color: FloatVectorProperty(name=_msg('Object Color'), subtype='COLOR', size=4, min=0, max=1, default=(0.53, 0.89, 0.11, 1), translation_context=_msg('DCCWorkflowKit.Max'))
    tab: EnumProperty(name=_msg('Command Panel'), items=(('CREATE', _msg('Create'), _msg('Create objects'), 'ADD', 0), ('MODIFY', _msg('Modify'), _msg('Modifier stack and mesh tools'), 'MODIFIER', 1), ('HIERARCHY', _msg('Hierarchy'), _msg('Pivots and linking'), 'OUTLINER', 2), ('MOTION', _msg('Motion'), _msg('Controllers, keys and motion paths'), 'ANIM', 3), ('DISPLAY', _msg('Display'), _msg('Visibility and viewport display'), 'HIDE_OFF', 4), ('UTILITIES', _msg('Utilities'), _msg('Scene and object utilities'), 'TOOL_SETTINGS', 5), ('MATERIAL', _msg('Material'), _msg('Material assignment and shader controls'), 'MATERIAL', 6)), default='CREATE', translation_context=_msg('DCCWorkflowKit.Max'))
    category: EnumProperty(name=_msg('Category'), items=tuple(((x, n, '') for (x, n) in (('GEOMETRY', _msg('Geometry')), ('SHAPES', _msg('Shapes')), ('LIGHTS', _msg('Lights')), ('CAMERAS', _msg('Cameras')), ('HELPERS', _msg('Helpers')), ('SPACEWARPS', _msg('Space Warps')), ('SYSTEMS', _msg('Systems'))))), default='GEOMETRY', translation_context=_msg('DCCWorkflowKit.Max'))
    subcategory: StringProperty(name=_msg('Object Category'), translation_context=_msg('DCCWorkflowKit.Max'))
    autogrid: BoolProperty(name=_msg('AutoGrid'), translation_context=_msg('DCCWorkflowKit.Max'))
    active_creation: StringProperty(name=_msg('Creation Tool'), translation_context=_msg('DCCWorkflowKit.Max'))
    created_this_session: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    next_prim: PointerProperty(type=params.BSM_PrimitiveParams, translation_context=_msg('DCCWorkflowKit.Max'))
    keyboard_location: FloatVectorProperty(name=_msg('Keyboard Entry'), subtype='TRANSLATION', unit='LENGTH', size=3, translation_context=_msg('DCCWorkflowKit.Max'))
    active_modifier: StringProperty(name=_msg('Selected Modifier'), translation_context=_msg('DCCWorkflowKit.Max'))
    stack_context: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    stack_pinned: StringProperty(name=_msg('Pin Stack'), translation_context=_msg('DCCWorkflowKit.Max'))
    stack_expanded: BoolProperty(name=_msg('Show Sub-object Levels'), default=True, translation_context=_msg('DCCWorkflowKit.Max'))
    show_end_result: BoolProperty(name=_msg('Show End Result'), default=True, translation_context=_msg('DCCWorkflowKit.Max'))
    show_mod_buttons: BoolProperty(name=_msg('Show Buttons'), translation_context=_msg('DCCWorkflowKit.Max'))
    last_material_editor: EnumProperty(name=_msg('Material Editor'), items=(('MATERIAL', _msg('Slate'), ''), ('COMPACT', _msg('Compact'), '')), default='MATERIAL', translation_context=_msg('DCCWorkflowKit.Max'))
    component: IntProperty(default=0, min=0, max=5, translation_context=_msg('DCCWorkflowKit.Max'))
    material_id: IntProperty(name=_msg('Material ID'), default=1, min=1, max=65535, translation_context=_msg('DCCWorkflowKit.Max'))
    selection_locked: BoolProperty(default=False, translation_context=_msg('DCCWorkflowKit.Max'))
    region_type: EnumProperty(name=_msg('Selection Region'), items=tuple(((k, k.title(), '') for k in ('RECT', 'CIRCLE', 'FENCE', 'LASSO', 'PAINT'))), translation_context=_msg('DCCWorkflowKit.Max'))
    window_selection: BoolProperty(name=_msg('Window/Crossing'), description=_msg('On: objects must be fully inside the region (Window); off: Crossing'), translation_context=_msg('DCCWorkflowKit.Max'))
    selection_filter: EnumProperty(name=_msg('Selection Filter'), update=_changed('selection_filter'), items=tuple(((k, k.title(), '') for k in ('ALL', 'GEOMETRY', 'SHAPES', 'LIGHTS', 'CAMERAS', 'HELPERS', 'WARPS', 'BONE'))), translation_context=_msg('DCCWorkflowKit.Max'))
    ref_coord: EnumProperty(name=_msg('Reference Coordinate System'), update=_changed('ref_coord'), items=tuple(((k, k.replace('_', ' ').title(), '') for k in ('VIEW', 'SCREEN', 'WORLD', 'PARENT', 'LOCAL', 'GIMBAL', 'GRID', 'WORKING', 'LOCAL_ALIGNED', 'PICK'))), translation_context=_msg('DCCWorkflowKit.Max'))
    ref_pick: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    manipulate: BoolProperty(name=_msg('Select and Manipulate'), update=_changed('manipulate'), translation_context=_msg('DCCWorkflowKit.Max'))
    keyboard_override: BoolProperty(name=_msg('Keyboard Shortcut Override'), default=True, update=_changed('keyboard_override'), description=_msg('On: 3ds Max shortcuts; off: Blender shortcuts'), translation_context=_msg('DCCWorkflowKit.Max'))
    snap_mode: EnumProperty(name=_msg('Snaps'), items=(('2D', '2D', ''), ('2.5D', '2.5D', ''), ('3D', '3D', '')), default='3D', translation_context=_msg('DCCWorkflowKit.Max'))
    spinner_snap: BoolProperty(name=_msg('Spinner Snap'), translation_context=_msg('DCCWorkflowKit.Max'))
    spinner_snap_value: FloatProperty(name=_msg('Spinner Snap'), default=1.0, min=0.0001, translation_context=_msg('DCCWorkflowKit.Max'))
    new_set_name: StringProperty(name=_msg('Named Selection Sets'), translation_context=_msg('DCCWorkflowKit.Max'))
    ribbon_visible: BoolProperty(name=_msg('Show Ribbon'), default=True, update=lambda self, context: runtime.redraw(), translation_context=_msg('DCCWorkflowKit.Max'))
    ribbon_tab: EnumProperty(items=tuple(((k, k.replace('_', ' ').title(), '') for k in ('MODELING', 'FREEFORM', 'SELECTION', 'OBJECT_PAINT', 'POPULATE'))), translation_context=_msg('DCCWorkflowKit.Max'))
    render_mode: EnumProperty(items=(('PRODUCTION', _msg('Render Production'), ''), ('ITERATIVE', _msg('Render Iterative'), ''), ('ACTIVESHADE', _msg('ActiveShade'), '')), translation_context=_msg('DCCWorkflowKit.Max'))
    pick_mode: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    hierarchy_tab: EnumProperty(items=(('PIVOT', _msg('Pivot'), ''), ('IK', 'IK', ''), ('LINK', _msg('Link Info'), '')), translation_context=_msg('DCCWorkflowKit.Max'))
    motion_tab: EnumProperty(items=(('PARAMETERS', _msg('Parameters'), ''), ('PATHS', _msg('Motion Paths'), '')), translation_context=_msg('DCCWorkflowKit.Max'))
    hide_frozen: BoolProperty(name=_msg('Hide Frozen Objects'), translation_context=_msg('DCCWorkflowKit.Max'))
    freeze_gray: BoolProperty(name=_msg('Show Frozen in Gray'), default=True, translation_context=_msg('DCCWorkflowKit.Max'))
    utility: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    offset_mode: BoolProperty(name=_msg('Offset Mode Transform Type-In'), translation_context=_msg('DCCWorkflowKit.Max'))
    offset_vector: FloatVectorProperty(name=_msg('Offset'), size=3, translation_context=_msg('DCCWorkflowKit.Max'))
    key_filter: EnumProperty(name=_msg('Key Filters'), options={'ENUM_FLAG'}, items=(('LOCATION', _msg('Position'), ''), ('ROTATION', _msg('Rotation'), ''), ('SCALE', _msg('Scale'), '')), default={'LOCATION', 'ROTATION', 'SCALE'}, translation_context=_msg('DCCWorkflowKit.Max'))
    prompt: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    key_mode: BoolProperty(name=_msg('Key Mode Toggle'), description=_msg('Previous and Next Frame jump between keys of the selection'), translation_context=_msg('DCCWorkflowKit.Max'))
    set_key_mode: BoolProperty(name=_msg('Set Key Mode'), description=_msg('Pose freely, then commit keys with the Set Keys button (K)'), update=_changed('set_key_mode'), translation_context=_msg('DCCWorkflowKit.Max'))
    key_set: StringProperty(name=_msg('Key Selection Set'), description=_msg('Named selection set keyed by Set Keys; empty keys the selection'), translation_context=_msg('DCCWorkflowKit.Max'))
    track_filter: EnumProperty(name=_msg('Track Bar Filter'), items=(('ALL', _msg('All Keys'), ''), ('TRANSFORM', _msg('All Transform Keys'), ''), ('LOCATION', _msg('Current Transform: Position'), ''), ('ROTATION', _msg('Current Transform: Rotation'), ''), ('SCALE', _msg('Current Transform: Scale'), '')), default='ALL', update=lambda self, context: runtime.redraw(), translation_context=_msg('DCCWorkflowKit.Max'))
    track_numbers: BoolProperty(name=_msg('Show Frame Numbers'), default=True, update=lambda self, context: runtime.redraw(), translation_context=_msg('DCCWorkflowKit.Max'))
    cursor_coords: FloatVectorProperty(name=_msg('Cursor Position'), size=3, translation_context=_msg('DCCWorkflowKit.Max'))
    cursor_valid: BoolProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    show_viewcube: BoolProperty(name=_msg('Show the ViewCube'), default=True, translation_context=_msg('DCCWorkflowKit.Max'))
    shade_selected: BoolProperty(translation_context=_msg('DCCWorkflowKit.Max'))

def draw_switch(self, context):
    if context.region and context.region.alignment != 'RIGHT':
        return
    row = self.layout.row(align=True)
    row.operator('bsm.environment', text=_dcc_ui_text(_msg('Blender')), depress=not runtime.is_active()).mode = 'BLENDER'
    row.operator('bsm.environment', text=_dcc_ui_text(_msg('Blender Max')), depress=runtime.is_active()).mode = 'STUDIO'

def draw_view_header(self, context):
    layout = self.layout
    row = layout.row(align=True)
    for (tool, icon, label) in (('SELECT', 'RESTRICT_SELECT_OFF', 'Q'), ('MOVE', 'ORIENTATION_GLOBAL', 'W'), ('ROTATE', 'DRIVER_ROTATIONAL_DIFFERENCE', 'E'), ('SCALE', 'FULLSCREEN_ENTER', 'R')):
        row.operator('bsm.tool', text=_dcc_ui_text(label), icon=icon).tool = tool
    layout.separator_spacer()
    layout.prop(context.space_data.shading, 'type', text=_dcc_ui_text(''), expand=True, icon_only=True)

def draw_time_header(self, context):
    if context.area.ui_type != 'TIMELINE':
        _original_time_header(self, context)
        return
    scene = context.scene
    layout = self.layout
    layout.prop(scene, 'frame_current', text=_dcc_ui_text(_msg('Time')))
    row = layout.row(align=True)
    row.prop(scene, 'frame_start', text=_dcc_ui_text(_msg('Start')))
    row.prop(scene, 'frame_end', text=_dcc_ui_text(_msg('End')))
    layout.prop(scene.tool_settings, 'use_keyframe_insert_auto', text=_dcc_ui_text(_msg('Auto Key')), icon='REC', toggle=True)
    layout.operator('bsm.keyframe', text=_dcc_ui_text(_msg('Set Keys')), icon='KEY_HLT')
_original_time_header = bpy.types.DOPESHEET_HT_header.draw

def draw_menus(self, context):
    from . import max_menus
    for (idname, label) in max_menus.MAIN_MENUS:
        self.layout.menu(idname, text=_dcc_ui_text(label))

class BSM_MT_edit(bpy.types.Menu):
    bl_label = _msg('Edit')

    def draw(self, context):
        l = self.layout
        l.operator('ed.undo', text=_dcc_ui_text(_msg('Undo')))
        l.operator('ed.redo', text=_dcc_ui_text(_msg('Redo')))
        l.separator()
        l.operator('bsm.scene_rename', text=_dcc_ui_text(_msg('Rename...')))
        l.operator('bsm.max_command', text=_dcc_ui_text(_msg('Delete'))).command = 'DELETE'
        l.separator()
        l.operator('bsm.max_command', text=_dcc_ui_text(_msg('Group...'))).command = 'GROUP'
        l.operator('bsm.max_command', text=_dcc_ui_text(_msg('Ungroup'))).command = 'UNGROUP'
        l.operator('bsm.toolbar_action', text=_dcc_ui_text(_msg('Unlink Selected'))).action = 'UNLINK'
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_selection(bpy.types.Menu):
    bl_label = _msg('Select')

    def draw(self, context):
        l = self.layout
        for (action, label) in (('SELECT', _msg('Select All')), ('DESELECT', _msg('Select None')), ('INVERT', _msg('Select Invert'))):
            l.operator('object.select_all', text=_dcc_ui_text(label)).action = action
        l.separator()
        l.operator('object.select_hierarchy', text=_dcc_ui_text(_msg('Select Children'))).direction = 'CHILD'
        l.operator('bsm.max_command', text=_dcc_ui_text(_msg('Select Instances'))).command = 'SELECT_INSTANCES'
        l.operator('bsm.max_command', text=_dcc_ui_text(_msg('Select Dependents'))).command = 'SELECT_SIMILAR'
        l.separator()
        l.operator('bsm.explorer_search', text=_dcc_ui_text(_msg('Find...')))
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_display(bpy.types.Menu):
    bl_label = _msg('Display')

    def draw(self, context):
        l = self.layout
        l.operator('bsm.explorer_branches', text=_dcc_ui_text(_msg('Expand All'))).expand = True
        l.operator('bsm.explorer_branches', text=_dcc_ui_text(_msg('Collapse All'))).expand = False
        l.separator()
        l.operator('object.hide_view_set', text=_dcc_ui_text(_msg('Hide Selected'))).unselected = False
        l.operator('object.hide_view_set', text=_dcc_ui_text(_msg('Hide Unselected'))).unselected = True
        l.operator('object.hide_view_clear', text=_dcc_ui_text(_msg('Unhide All')))
    bl_translation_context = _msg('DCCWorkflowKit.Max')
CLASSES = (BSM_State, BSM_MT_edit, BSM_MT_selection, BSM_MT_display)
