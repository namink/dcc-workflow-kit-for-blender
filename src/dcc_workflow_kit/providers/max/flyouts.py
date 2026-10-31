# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format
'Toolbar flyouts, stack/explorer context menus, ribbon panels and small dialogs.'
import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from . import runtime
from .operators import Active, viewport_override

def _item(layout, label, op=None, **props):
    if op is None:
        row = layout.row()
        row.enabled = False
        row.operator('bsm.unavailable', text=_dcc_ui_text(label))
        return
    button = layout.operator(op, text=_dcc_ui_text(label))
    for (key, value) in props.items():
        setattr(button, key, value)

def _choice(layout, label, owner, attr, value, current=None):
    current = getattr(owner, attr) if current is None else current
    button = layout.operator('bsm.set_state', text=_dcc_ui_text(label), icon='RADIOBUT_ON' if current == value else 'RADIOBUT_OFF')
    (button.attr, button.value) = (attr, value)

class BSM_OT_unavailable(bpy.types.Operator):
    bl_idname = 'bsm.unavailable'
    bl_label = _msg('Not available in Blender')
    bl_description = _msg('This 3ds Max command has no Blender equivalent')

    @classmethod
    def poll(cls, context):
        return False

    def execute(self, context):
        return {'CANCELLED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_set_state(Active, bpy.types.Operator):
    bl_idname = 'bsm.set_state'
    bl_label = _msg('Set Option')
    attr: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    value: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))

    @classmethod
    def description(cls, context, properties):
        return properties.value or cls.bl_label

    def execute(self, context):
        state = context.window_manager.bsm
        setattr(state, self.attr, self.value)
        if self.attr == 'selection_filter':
            runtime.apply_selection_filter(context)
        elif self.attr == 'ref_coord':
            runtime.sync_reference(context)
        elif self.attr == 'region_type':
            from .operators import REGION_TOOLS
            tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
            if tool and tool.idname.startswith('builtin.select'):
                with context.temp_override(**viewport_override(context)):
                    bpy.ops.wm.tool_set_by_id(name=REGION_TOOLS[self.value])
        runtime.redraw()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_selection_filter(bpy.types.Menu):
    bl_label = _msg('Selection Filter')

    def draw(self, context):
        state = context.window_manager.bsm
        for (value, label) in (('ALL', _msg('All')), ('GEOMETRY', _msg('Geometry')), ('SHAPES', _msg('Shapes')), ('LIGHTS', _msg('Lights')), ('CAMERAS', _msg('Cameras')), ('HELPERS', _msg('Helpers')), ('WARPS', _msg('Warps'))):
            _choice(self.layout, label, state, 'selection_filter', value)
        _item(self.layout, _msg('Combos...'))
        _choice(self.layout, _msg('Bone'), state, 'selection_filter', 'BONE')
        _item(self.layout, _msg('IK Chain Object'))
        _item(self.layout, _msg('Point'))
        _item(self.layout, _msg('CAT Bone'))
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_region_flyout(bpy.types.Menu):
    bl_label = _msg('Selection Region')

    def draw(self, context):
        state = context.window_manager.bsm
        for (value, label) in (('RECT', _msg('Rectangular Selection Region')), ('CIRCLE', _msg('Circular Selection Region')), ('FENCE', _msg('Fence Selection Region')), ('LASSO', _msg('Lasso Selection Region')), ('PAINT', _msg('Paint Selection Region'))):
            _choice(self.layout, label, state, 'region_type', value)
        self.layout.separator()
        self.layout.prop(state, 'window_selection', text=_dcc_ui_text(_msg('Window (off: Crossing)')))
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_scale_flyout(bpy.types.Menu):
    bl_label = _msg('Scale')

    def draw(self, context):
        for label in (_msg('Select and Uniform Scale'), _msg('Select and Non-uniform Scale'), _msg('Select and Squash')):
            _item(self.layout, label, 'bsm.tool', tool='SCALE')
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_ref_coord(bpy.types.Menu):
    bl_label = _msg('Reference Coordinate System')

    def draw(self, context):
        state = context.window_manager.bsm
        for (value, label) in (('VIEW', _msg('View')), ('SCREEN', _msg('Screen')), ('WORLD', _msg('World')), ('PARENT', _msg('Parent')), ('LOCAL', _msg('Local')), ('GIMBAL', _msg('Gimbal')), ('GRID', _msg('Grid')), ('WORKING', _msg('Working')), ('LOCAL_ALIGNED', _msg('Local Aligned'))):
            _choice(self.layout, label, state, 'ref_coord', value)
        _item(self.layout, _msg('Pick'), 'bsm.pick_object', purpose='REF_PICK')
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_pivot_center(bpy.types.Menu):
    bl_label = _msg('Transform Center')

    def draw(self, context):
        ts = context.scene.tool_settings
        for (value, label) in (('INDIVIDUAL_ORIGINS', _msg('Use Pivot Point Center')), ('BOUNDING_BOX_CENTER', _msg('Use Selection Center')), ('CURSOR', _msg('Use Transform Coordinate Center'))):
            button = self.layout.operator('wm.context_set_enum', text=_dcc_ui_text(label), icon='RADIOBUT_ON' if ts.transform_pivot_point == value else 'RADIOBUT_OFF')
            (button.data_path, button.value) = ('scene.tool_settings.transform_pivot_point', value)
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_align_flyout(bpy.types.Menu):
    bl_label = _msg('Align')

    def draw(self, context):
        l = self.layout
        _item(l, _msg('Align...'), 'bsm.max_command', command='ALIGN')
        _item(l, _msg('Quick Align'), 'bsm.max_command', command='QUICK_ALIGN')
        _item(l, _msg('Normal Align...'))
        _item(l, _msg('Place Highlight...'))
        _item(l, _msg('Align Camera'))
        _item(l, _msg('Align to View...'), 'bsm.max_command', command='ALIGN_TO_VIEW')
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_material_flyout(bpy.types.Menu):
    bl_label = _msg('Material Editor')

    def draw(self, context):
        _item(self.layout, _msg('Compact Material Editor...'), 'bsm.editor', kind='COMPACT')
        _item(self.layout, _msg('Slate Material Editor...'), 'bsm.editor', kind='MATERIAL')
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_render_flyout(bpy.types.Menu):
    bl_label = _msg('Render')

    def draw(self, context):
        state = context.window_manager.bsm
        for (value, label) in (('PRODUCTION', _msg('Render Production')), ('ITERATIVE', _msg('Render Iterative')), ('ACTIVESHADE', _msg('ActiveShade'))):
            _choice(self.layout, label, state, 'render_mode', value)
        _item(self.layout, _msg('Render in Autodesk A360'))
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_subcategories(bpy.types.Menu):
    bl_label = _msg('Object Category')

    def draw(self, context):
        from .surfaces import CREATE, subcategory
        state = context.window_manager.bsm
        for (name, _) in CREATE[state.category]:
            _choice(self.layout, name, state, 'subcategory', name, subcategory(state))
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def _modifier_labels():
    from . import max_menus
    labels = []

    def walk(items):
        for item in items:
            if isinstance(item, max_menus.Sub):
                walk(item.items)
            elif isinstance(item, max_menus.Item) and item.op == 'bsm.max_modifier':
                labels.append((item.props or {}).get('name', item.label))
    for (label, items) in max_menus.MAIN:
        if label == _msg('Modifiers'):
            walk(items)
    return sorted(set(labels), key=str.casefold)

class BSM_MT_modifier_list(bpy.types.Menu):
    bl_label = _msg('Modifier List')

    def draw(self, context):
        from .commands import modifier_available
        labels = _modifier_labels()
        selection = [n for n in labels if n.endswith(_msg('Select')) or n.startswith(_msg('Select By'))]
        world = [n for n in labels if '(WSM)' in n]
        rest = [n for n in labels if n not in selection and n not in world]
        row = self.layout.row()
        for (title, names) in (('SELECTION MODIFIERS', selection), ('WORLD-SPACE MODIFIERS', world), ('OBJECT-SPACE MODIFIERS', rest)):
            for start in range(0, len(names), 34):
                column = row.column()
                column.label(text=_dcc_ui_text(title if start == 0 else ''))
                for name in names[start:start + 34]:
                    if modifier_available(name):
                        column.operator('bsm.max_modifier', text=_dcc_ui_text(name)).name = name
                    else:
                        sub = column.row()
                        sub.enabled = False
                        sub.operator('bsm.unavailable', text=_dcc_ui_text(name))
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_modifier_sets(bpy.types.Menu):
    bl_label = _msg('Configure Modifier Sets')

    def draw(self, context):
        state = context.window_manager.bsm
        self.layout.prop(state, 'show_mod_buttons', text=_dcc_ui_text(_msg('Show Buttons')))
        _item(self.layout, _msg('Configure Modifier Sets...'))
        _item(self.layout, _msg('Show All Sets in List'))
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_stack_context(bpy.types.Menu):
    bl_label = _msg('Modifier Stack')

    def draw(self, context):
        state = context.window_manager.bsm
        name = state.stack_context
        l = self.layout

        def act(label, action, enabled=True):
            row = l.row()
            row.enabled = enabled
            button = row.operator('bsm.stack_action', text=_dcc_ui_text(label))
            (button.action, button.modifier) = (action, name)
        modifier = bool(name)
        act(_msg('Rename'), 'RENAME', modifier)
        act(_msg('Delete'), 'DELETE', modifier)
        l.separator()
        act(_msg('Cut'), 'CUT', modifier)
        act(_msg('Copy'), 'COPY', modifier)
        act(_msg('Paste'), 'PASTE', bool(_clipboard))
        l.separator()
        act(_msg('Make Unique'), 'MAKE_UNIQUE')
        act(_msg('Collapse To'), 'COLLAPSE_TO', modifier)
        act(_msg('Collapse All'), 'COLLAPSE_ALL')
        l.separator()
        act(_msg('On'), 'ON', modifier)
        act(_msg('Off in Viewport'), 'OFF_VIEWPORT', modifier)
        act(_msg('Off in Renderer'), 'OFF_RENDER', modifier)
        l.separator()
        act(_msg('Move Up'), 'MOVE_UP', modifier)
        act(_msg('Move Down'), 'MOVE_DOWN', modifier)
        if not modifier:
            l.separator()
            act(_msg('Convert to: Editable Poly'), 'CONVERT_POLY')
            act(_msg('Convert to: Editable Mesh'), 'CONVERT_POLY')
            act(_msg('Convert to: Editable Spline'), 'CONVERT_SPLINE')
    bl_translation_context = _msg('DCCWorkflowKit.Max')
_clipboard = []

class BSM_OT_stack_action(Active, bpy.types.Operator):
    bl_idname = 'bsm.stack_action'
    bl_label = _msg('Modifier Stack Action')
    bl_options = {'REGISTER', 'UNDO'}
    action: EnumProperty(items=tuple(((a, a.replace('_', ' ').title(), '') for a in ('RENAME', 'DELETE', 'CUT', 'COPY', 'PASTE', 'MAKE_UNIQUE', 'COLLAPSE_TO', 'COLLAPSE_ALL', 'ON', 'OFF_VIEWPORT', 'OFF_RENDER', 'MOVE_UP', 'MOVE_DOWN', 'MOVE_TO', 'CONVERT_POLY', 'CONVERT_SPLINE'))), translation_context=_msg('DCCWorkflowKit.Max'))
    modifier: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    index: IntProperty(default=-1, translation_context=_msg('DCCWorkflowKit.Max'))
    new_name: StringProperty(name=_msg('Name'), translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        if self.action == 'RENAME':
            self.new_name = self.modifier
            return context.window_manager.invoke_props_dialog(self, width=260, title=_msg('Rename Modifier'))
        return self.execute(context)

    def execute(self, context):
        from . import params
        state = context.window_manager.bsm
        obj = bpy.data.objects.get(state.stack_pinned) if state.stack_pinned else context.view_layer.objects.active
        if obj is None:
            return {'CANCELLED'}
        mod = obj.modifiers.get(self.modifier)
        a = self.action
        override = dict(viewport_override(context), active_object=obj, object=obj)
        if a == 'RENAME' and mod:
            mod.name = self.new_name
            state.active_modifier = mod.name
        elif a in {'DELETE', 'CUT'} and mod:
            if a == 'CUT':
                _copy(mod)
            obj.modifiers.remove(mod)
            state.active_modifier = ''
        elif a == 'COPY' and mod:
            _copy(mod)
        elif a == 'PASTE' and _clipboard:
            (kind, values) = _clipboard[0]
            new = obj.modifiers.new(values.get('name', kind.title()), kind)
            if new:
                for (key, value) in values.items():
                    try:
                        setattr(new, key, value)
                    except (AttributeError, TypeError, ValueError):
                        pass
                state.active_modifier = new.name
        elif a == 'MAKE_UNIQUE':
            if obj.data is not None and obj.data.users > 1:
                obj.data = obj.data.copy()
        elif a == 'COLLAPSE_TO' and mod:
            names = [m.name for m in obj.modifiers]
            if obj.mode != 'OBJECT':
                self.report({'WARNING'}, _dcc_ui_text(_msg('Return to the top level first')))
                return {'CANCELLED'}
            if obj.data.users > 1:
                obj.data = obj.data.copy()
            with context.temp_override(**override):
                for name in names[:names.index(mod.name) + 1]:
                    bpy.ops.object.modifier_apply(modifier=name)
            params.collapse(obj)
            state.active_modifier = ''
        elif a in {'COLLAPSE_ALL', 'CONVERT_POLY', 'CONVERT_SPLINE'}:
            targets = [o for o in context.view_layer.objects if o.select_get()] or [obj]
            if context.mode != 'OBJECT':
                with context.temp_override(**override):
                    bpy.ops.object.mode_set(mode='OBJECT')
            for target in targets:
                if target.data is not None and target.data.users > 1:
                    target.data = target.data.copy()
                params.collapse(target)
            with context.temp_override(**dict(override, selected_objects=targets, selected_editable_objects=targets)):
                bpy.ops.object.convert(target='CURVE' if a == 'CONVERT_SPLINE' else 'MESH')
            state.active_modifier = ''
        elif a == 'ON' and mod:
            mod.show_viewport = mod.show_render = True
        elif a == 'OFF_VIEWPORT' and mod:
            mod.show_viewport = False
        elif a == 'OFF_RENDER' and mod:
            mod.show_render = False
        elif a in {'MOVE_UP', 'MOVE_DOWN', 'MOVE_TO'} and mod:
            index = list(obj.modifiers).index(mod)
            target = self.index if a == 'MOVE_TO' else index + (1 if a == 'MOVE_UP' else -1)
            target = max(0, min(len(obj.modifiers) - 1, target))
            with context.temp_override(**override):
                bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=target)
        else:
            return {'CANCELLED'}
        runtime.redraw()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def _copy(mod):
    values = {'name': mod.name}
    for p in mod.bl_rna.properties:
        if p.is_readonly or p.identifier in {'name', 'rna_type'} or p.type == 'COLLECTION':
            continue
        value = getattr(mod, p.identifier, None)
        if p.type == 'POINTER' and (not isinstance(value, bpy.types.ID)):
            continue
        values[p.identifier] = tuple(value) if getattr(p, 'array_length', 0) else value
    _clipboard[:] = [(mod.type, values)]

class BSM_MT_enum_choice(bpy.types.Menu):
    bl_label = _msg('Choose')

    def draw(self, context):
        from . import surfaces
        if surfaces._enum_owner:
            (owner, attr) = surfaces._enum_owner
            try:
                self.layout.prop(owner, attr, expand=True)
            except ReferenceError:
                pass
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_key_interpolation(bpy.types.Menu):
    bl_label = _msg('Key Tangents')

    def draw(self, context):
        for (mode, label) in (('BEZIER', _msg('Smooth')), ('LINEAR', _msg('Linear')), ('CONSTANT', _msg('Step'))):
            self.layout.operator('bsm.key_interpolation', text=_dcc_ui_text(label)).mode = mode
        for label in (_msg('Fast'), _msg('Slow'), _msg('Custom'), _msg('Auto')):
            _item(self.layout, label)
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_key_filters(bpy.types.Menu):
    bl_label = _msg('Set Key Filters')

    def draw(self, context):
        state = context.window_manager.bsm
        self.layout.prop(state, 'key_filter', expand=True)
        for label in (_msg('Modifiers'), _msg('Object Parameters'), _msg('Custom Attributes'), _msg('Materials'), _msg('Other')):
            _item(self.layout, label)
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_more_utilities(bpy.types.Menu):
    bl_label = _msg('Utilities')

    def draw(self, context):
        l = self.layout
        _item(l, _msg('Edit UVWs'), 'bsm.editor', kind='UV')
        _item(l, _msg('Render Setup'), 'bsm.editor', kind='RENDER')
        _item(l, _msg('Scene Explorer'), 'bsm.editor', kind='SCENE')
        _item(l, _msg('Units Setup'), 'bsm.max_command', command='UNITS_SETUP')
        _item(l, _msg('Summary Info'), 'bsm.max_command', command='SUMMARY_INFO')
        _item(l, _msg('Shortcut Reference'), 'bsm.shortcuts')
        l.separator()
        _item(l, _msg('Return to Blender'), 'bsm.environment', mode='BLENDER')
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_explorer_context(bpy.types.Menu):
    bl_label = _msg('Scene Explorer')

    def draw(self, context):
        l = self.layout
        _item(l, _msg('Hide'), 'object.hide_view_set', unselected=False)
        _item(l, _msg('Unhide All'), 'object.hide_view_clear')
        _item(l, _msg('Freeze'), 'bsm.toolbar_action', action='FREEZE')
        _item(l, _msg('Unfreeze All'), 'bsm.toolbar_action', action='UNFREEZE')
        l.separator()
        _item(l, _msg('Rename'), 'bsm.scene_rename')
        _item(l, _msg('Delete'), 'bsm.max_command', command='DELETE')
        l.separator()
        _item(l, _msg('Select Children'), 'object.select_hierarchy', direction='CHILD', extend=True)
        _item(l, _msg('Object Properties...'), 'bsm.object_properties')
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_explorer_mode(bpy.types.Menu):
    bl_label = _msg('Scene Explorer')

    def draw(self, context):
        _item(self.layout, _msg('Open Scene Explorer'), 'bsm.editor', kind='SCENE')
        _item(self.layout, _msg('Expand All'), 'bsm.explorer_branches', expand=True)
        _item(self.layout, _msg('Collapse All'), 'bsm.explorer_branches', expand=False)
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_explorer_branches(Active, bpy.types.Operator):
    bl_idname = 'bsm.explorer_branches'
    bl_label = _msg('Expand or Collapse All')
    expand: bpy.props.BoolProperty(translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        from . import surfaces
        surfaces._collapsed.clear()
        if not self.expand:
            surfaces._collapsed.update((o.name for o in context.view_layer.objects if o.children))
        runtime.redraw()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_ribbon_options(bpy.types.Menu):
    bl_label = _msg('Ribbon')

    def draw(self, context):
        _item(self.layout, _msg('Show Full Ribbon'))
        _item(self.layout, _msg('Minimize to Panel Titles'))
        self.layout.prop(context.window_manager.bsm, 'ribbon_visible', text=_dcc_ui_text(_msg('Show Ribbon')))
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def _m(action):
    return ('bsm.mesh_action', {'action': action})

def _c(level):
    return ('bsm.component', {'level': level})
RIBBON_ITEMS = {_msg('Polygon Modeling'): ((_msg('Vertex'), _c(1)), (_msg('Edge'), _c(2)), (_msg('Border'), _c(3)), (_msg('Polygon'), _c(4)), (_msg('Element'), _c(5)), (_msg('Top Level'), _c(0)), None, (_msg('Collapse Stack'), ('bsm.stack_action', {'action': 'COLLAPSE_ALL'})), (_msg('Convert to Poly'), ('bsm.stack_action', {'action': 'CONVERT_POLY'})), (_msg('Apply Edit Poly Mod'), None), (_msg('Show End Result'), ('wm.context_toggle', {'data_path': 'window_manager.bsm.show_end_result'}))), _msg('Modify Selection'): ((_msg('Grow'), _m('GROW')), (_msg('Shrink'), _m('SHRINK')), (_msg('Loop'), _m('LOOP')), (_msg('Ring'), _m('RING')), (_msg('Similar'), ('bsm.max_command', {'command': 'SELECT_SIMILAR'})), (_msg('Fill'), None), (_msg('Step Loop'), None)), _msg('Edit'): ((_msg('Preserve UVs'), None), (_msg('Repeat'), _m('REPEAT')), (_msg('QuickSlice'), _m('SLICE')), (_msg('SwiftLoop'), _m('LOOPCUT')), ('NURMS', _m('NURMS')), (_msg('Cut'), _m('CUT')), (_msg('P Connect'), None), (_msg('Constraints'), None)), _msg('Geometry (All)'): ((_msg('Relax'), _m('RELAX')), (_msg('Create'), _m('CREATE_FACE')), (_msg('Attach'), _m('ATTACH')), (_msg('Detach'), _m('DETACH')), (_msg('Collapse'), _m('COLLAPSE')), (_msg('Cap Poly'), _m('CAP')), (_msg('Quadrify All'), _m('QUADRIFY')), (_msg('Slice Plane'), _m('SLICE'))), _msg('Loops'): ((_msg('Connect'), _m('CONNECT_EDGES')), (_msg('Insert Loop'), _m('LOOPCUT')), (_msg('Remove Loop'), _m('DISSOLVE_EDGES')), (_msg('Distance Connect'), None), (_msg('Flow Connect'), None), (_msg('Build End'), None), (_msg('Build Corner'), None)), _msg('Tris'): ((_msg('Retriangulate'), _m('RETRIANGULATE')), (_msg('Turn'), _m('TURN')), (_msg('Quadrify'), _m('QUADRIFY'))), _msg('Subdivision'): ((_msg('MeshSmooth'), _m('MSMOOTH')), (_msg('Tessellate'), _m('TESSELLATE')), (_msg('Use Displacement'), None)), _msg('Visibility'): ((_msg('Hide Selected'), _m('HIDE')), (_msg('Hide Unselected'), _m('HIDE_UNSELECTED')), (_msg('Unhide All'), _m('UNHIDE'))), _msg('Align'): ((_msg('Make Planar'), _m('PLANAR')), ('X', _m('FLATTEN_X')), ('Y', _m('FLATTEN_Y')), ('Z', _m('FLATTEN_Z')), (_msg('To View'), None), (_msg('To Grid'), None)), _msg('Properties'): ((_msg('Hard'), _m('CLEAR_SMOOTH')), (_msg('Smooth'), _m('AUTO_SMOOTH')), (_msg('Smooth 30'), _m('AUTO_SMOOTH')), (_msg('Set ID'), _m('SET_ID')), (_msg('Select ID'), _m('SELECT_ID'))), _msg('Vertices'): ((_msg('Remove'), _m('DISSOLVE_VERTS')), (_msg('Break'), _m('BREAK')), (_msg('Extrude'), _m('EXTRUDE_VERTS')), (_msg('Weld'), _m('WELD')), (_msg('Chamfer'), _m('CHAMFER_VERTS')), (_msg('Target Weld'), _m('TARGET_WELD')), (_msg('Connect'), _m('CONNECT_VERTS'))), _msg('Edges'): ((_msg('Insert Vertex'), _m('INSERT_VERTEX')), (_msg('Remove'), _m('DISSOLVE_EDGES')), (_msg('Split'), _m('SPLIT_EDGES')), (_msg('Extrude'), _m('EXTRUDE_EDGES')), (_msg('Weld'), _m('WELD')), (_msg('Chamfer'), _m('CHAMFER')), (_msg('Target Weld'), _m('TARGET_WELD')), (_msg('Bridge'), _m('BRIDGE')), (_msg('Connect'), _m('CONNECT_EDGES')), (_msg('Create Shape'), _m('CREATE_SHAPE'))), _msg('Borders'): ((_msg('Extrude'), _m('EXTRUDE_EDGES')), (_msg('Chamfer'), _m('CHAMFER')), (_msg('Cap'), _m('CAP')), (_msg('Bridge'), _m('BRIDGE')), (_msg('Connect'), _m('CONNECT_EDGES'))), _msg('Polygons'): ((_msg('Extrude'), _m('EXTRUDE')), (_msg('Outline'), _m('OUTLINE')), (_msg('Bevel'), _m('BEVEL_POLY')), (_msg('Inset'), _m('INSET')), (_msg('Bridge'), _m('BRIDGE')), (_msg('Flip'), _m('FLIP')), (_msg('Hinge'), None), (_msg('Extrude on Spline'), None)), _msg('Elements'): ((_msg('Flip'), _m('FLIP')), (_msg('Retriangulate'), _m('RETRIANGULATE'))), _msg('PolyDraw'): ((_msg('Drag'), None), (_msg('Conform'), None), (_msg('Step Build'), None), (_msg('Extend'), None), (_msg('Optimize'), None), (_msg('Strips'), None)), _msg('Paint Deform'): ((_msg('Shift'), ('bsm.sculpt', {'brush': 'GRAB'})), (_msg('Push/Pull'), ('bsm.sculpt', {'brush': 'DRAW'})), (_msg('Relax/Soften'), ('bsm.sculpt', {'brush': 'SMOOTH'})), (_msg('Smudge'), ('bsm.sculpt', {'brush': 'SMUDGE'})), (_msg('Flatten'), ('bsm.sculpt', {'brush': 'FLATTEN'})), (_msg('Pinch/Spread'), ('bsm.sculpt', {'brush': 'PINCH'}))), _msg('Defaults'): ((_msg('Freeform Defaults'), None),), _msg('Select'): ((_msg('Select All'), ('object.select_all', {'action': 'SELECT'})), (_msg('Select None'), ('object.select_all', {'action': 'DESELECT'})), (_msg('Invert'), ('object.select_all', {'action': 'INVERT'}))), _msg('Stored Selections'): ((_msg('Copy Store 1'), None), (_msg('Paste Store 1'), None), (_msg('Add'), None), (_msg('Subtract'), None), (_msg('Intersect'), None)), _msg('Sets'): ((_msg('Manage Selection Sets...'), ('bsm.manage_sets', {})),), _msg('By Random'): ((_msg('Select Random'), ('object.select_random', {})),)}

def _ribbon_class(title):
    from .surfaces import ribbon_menu
    items = RIBBON_ITEMS.get(title, ((_dcc_format('{0} tools', title), None),))

    def draw(self, context):
        for entry in items:
            if entry is None:
                self.layout.separator()
                continue
            (label, target) = entry
            if target is None:
                _item(self.layout, label)
            else:
                _item(self.layout, label, target[0], **target[1])
    return type(ribbon_menu(title), (bpy.types.Menu,), {'bl_idname': ribbon_menu(title), 'bl_label': title, 'draw': draw, 'bl_translation_context': 'DCCWorkflowKit.Max'})

def _ribbon_classes():
    from .surfaces import RIBBON_PANELS, LEVEL_PANELS
    titles = {t for panels in RIBBON_PANELS.values() for t in panels if t} | set(LEVEL_PANELS.values())
    return tuple((_ribbon_class(t) for t in sorted(titles)))

class BSM_OT_sculpt(Active, bpy.types.Operator):
    bl_idname = 'bsm.sculpt'
    bl_label = _msg('Paint Deform')
    brush: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        obj = context.view_layer.objects.active
        if obj is None or obj.type != 'MESH':
            self.report({'WARNING'}, _dcc_ui_text(_msg('Paint Deform needs an Editable Poly')))
            return {'CANCELLED'}
        with context.temp_override(**viewport_override(context)):
            if obj.mode != 'SCULPT':
                bpy.ops.object.mode_set(mode='SCULPT')
            names = {'GRAB': 'builtin_brush.grab', 'DRAW': 'builtin_brush.draw', 'SMOOTH': 'builtin_brush.smooth', 'SMUDGE': 'builtin_brush.snake_hook', 'FLATTEN': 'builtin_brush.flatten', 'PINCH': 'builtin_brush.pinch'}
            try:
                bpy.ops.wm.tool_set_by_id(name=names[self.brush])
            except (RuntimeError, KeyError):
                pass
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_keyboard_create(Active, bpy.types.Operator):
    bl_idname = 'bsm.keyboard_create'
    bl_label = _msg('Create')
    bl_options = {'REGISTER', 'UNDO'}
    kind: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        from . import params
        from mathutils import Matrix, Vector
        state = context.window_manager.bsm
        if self.kind not in params.DEFAULTS:
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        values = {}
        for attr in params.DEFAULTS[self.kind]:
            if hasattr(state.next_prim, attr):
                values[attr] = getattr(state.next_prim, attr)
        obj = params.new_object(context, self.kind, Matrix.Translation(Vector(state.keyboard_location)), **values)
        obj.color = state.next_color
        from .interactions import next_random_color
        next_random_color(state)
        state.created_this_session = obj.name
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_time_configuration(Active, bpy.types.Operator):
    bl_idname = 'bsm.time_configuration'
    bl_label = _msg('Time Configuration')

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=380)

    def draw(self, context):
        scene = context.scene
        l = self.layout
        l.label(text=_dcc_ui_text(_msg('Time Configuration')))
        box = l.box()
        box.label(text=_dcc_ui_text(_msg('Frame Rate')))
        row = box.row(align=True)
        for (fps, label) in ((30, 'NTSC'), (25, 'PAL'), (24, _msg('Film'))):
            button = row.operator('wm.context_set_int', text=_dcc_ui_text(label), depress=scene.render.fps == fps and scene.render.fps_base == 1)
            (button.data_path, button.value) = ('scene.render.fps', fps)
        box.prop(scene.render, 'fps', text=_dcc_ui_text('FPS'))
        box = l.box()
        box.label(text=_dcc_ui_text(_msg('Playback')))
        box.prop(scene, 'sync_mode', text=_dcc_ui_text(_msg('Real Time')))
        box = l.box()
        box.label(text=_dcc_ui_text(_msg('Animation')))
        row = box.row(align=True)
        row.prop(scene, 'frame_start', text=_dcc_ui_text(_msg('Start Time')))
        row.prop(scene, 'frame_end', text=_dcc_ui_text(_msg('End Time')))
        box.label(text=_dcc_ui_text(_dcc_format('Length: {0}    Frame Count: {1}', scene.frame_end - scene.frame_start, scene.frame_end - scene.frame_start + 1)))
        box.prop(scene, 'frame_current', text=_dcc_ui_text(_msg('Current Time')))

    def execute(self, context):
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')
CLASSES = (BSM_OT_unavailable, BSM_OT_set_state, BSM_MT_selection_filter, BSM_MT_region_flyout, BSM_MT_scale_flyout, BSM_MT_ref_coord, BSM_MT_pivot_center, BSM_MT_align_flyout, BSM_MT_material_flyout, BSM_MT_render_flyout, BSM_MT_subcategories, BSM_MT_modifier_list, BSM_MT_modifier_sets, BSM_MT_stack_context, BSM_OT_stack_action, BSM_MT_enum_choice, BSM_MT_key_interpolation, BSM_MT_key_filters, BSM_MT_more_utilities, BSM_MT_explorer_context, BSM_MT_explorer_mode, BSM_OT_explorer_branches, BSM_MT_ribbon_options, BSM_OT_sculpt, BSM_OT_keyboard_create, BSM_OT_time_configuration) + _ribbon_classes()
