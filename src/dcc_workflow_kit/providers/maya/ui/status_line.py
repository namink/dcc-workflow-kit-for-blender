# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese display integration by namink.
"""Maya top bar (menu bar) and Status Line.

Maya's menu bar and Status Line groups;
$S\\startup\\bl_ui\\space_topbar.py:14-62.
Design: docs/steps/step_7.md 「계획」 1 and 3.

``TOPBAR_HT_upper_bar.draw_left`` / ``draw_right`` are swapped for Maya
versions while the add-on is enabled and put back on unregister; the
originals still run when the "Maya Menu Bar" preference is off. Maya has the
Status Line on its own row under the menus; one TOPBAR row can't hold both
(measured at 1600 px, docs/steps/step_7.md 「한 것」), so the Status Line is
drawn first in the tool header of the largest 3D View.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
from bpy.props import EnumProperty, StringProperty
from . import input_line, menu_sets, own_draw, status_icons

def main_view3d(screen=None):
    """(area, WINDOW region) of the largest 3D View in ``screen`` (or the active screen)."""
    screen = screen or bpy.context.screen
    best = None
    for area in screen.areas if screen else ():
        if area.type == 'VIEW_3D' and (best is None or area.width * area.height > best.width * best.height):
            best = area
    if best is None:
        return (None, None)
    return (best, next((r for r in best.regions if r.type == 'WINDOW'), None))

def all_view3d_spaces():
    """Every 3D View space in every screen (Maya selection masks are global)."""
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    yield space
OBJECT_MASKS = (('HANDLES', _dcc_source('Select by handle object type'), 'RESTRICT_SELECT_OFF', None), ('JOINTS', _dcc_source('Select by joint object type (armatures)'), 'OUTLINER_OB_ARMATURE', ('armature',)), ('CURVES', _dcc_source('Select by curve object type'), 'OUTLINER_OB_CURVE', (_dcc_source('curve'), 'font', 'curves')), ('SURFACES', _dcc_source('Select by surface object type (meshes, NURBS)'), 'OUTLINER_OB_MESH', ('mesh', 'surf', 'meta', 'pointcloud', 'volume')), ('DEFORMERS', _dcc_source('Select by deformation object type (lattices)'), 'OUTLINER_OB_LATTICE', ('lattice',)), ('DYNAMICS', _dcc_source('Select by dynamic object type'), 'OUTLINER_OB_FORCE_FIELD', None), ('RENDERING', _dcc_source('Select by rendering object type (cameras, lights)'), 'OUTLINER_OB_LIGHT', ('camera', 'light')), ('MISC', _dcc_source('Select by miscellaneous object type (locators, empties)'), 'OUTLINER_OB_EMPTY', (_dcc_source('empty'), 'speaker', 'light_probe', 'grease_pencil')))
_MASK_TYPES = {m[0]: m[3] for m in OBJECT_MASKS}

def mask_on(space, group):
    return all((getattr(space, f'show_object_select_{t}') for t in _MASK_TYPES[group]))

def set_mask(group, value):
    for space in all_view3d_spaces():
        for t in _MASK_TYPES[group]:
            setattr(space, f'show_object_select_{t}', value)

class ALLSET_OT_select_mask(bpy.types.Operator):
    """Toggle whether this kind of object can be selected (all 3D Views)"""
    bl_translation_context = 'MWK:ui/status_line.py:78'
    bl_idname = 'allset.select_mask'
    bl_label = _zh_native('Selection Mask', 'MWK:ui/status_line.py:78')
    bl_description = _zh_native('Toggle whether this kind of object can be selected (all 3D Views)', 'MWK:ui/status_line.py:78')
    bl_options = {'INTERNAL'}
    group: EnumProperty(items=_zh_enum([(m[0], m[0].title(), m[1]) for m in OBJECT_MASKS if m[3]], 'MWK:ui/status_line.py:81'), translation_context='MWK:ui/status_line.py:81')

    @classmethod
    def description(cls, context, props):
        return _zh(next((m[1] for m in OBJECT_MASKS if m[0] == props.group)), 'MWK:ui/status_line.py:85')

    def execute(self, context):
        (area, _r) = main_view3d(context.screen)
        spaces = [area.spaces.active] if area else list(all_view3d_spaces())[:1]
        if not spaces:
            return {'CANCELLED'}
        set_mask(self.group, not mask_on(spaces[0], self.group))
        return {'FINISHED'}
MASK_FLAGS = tuple(sorted({t for m in OBJECT_MASKS if m[3] for t in m[3]}))
_carried = {}

def session_masks(context=None):
    """The current masks: {type: selectable} of the main 3D View and the mesh select mode (or None)."""
    context = context or bpy.context
    (area, _r) = main_view3d(context.screen) if context.screen else (None, None)
    space = area.spaces.active if area else next(iter(all_view3d_spaces()), None)
    scene = context.scene
    if space is None and scene is None:
        return None
    return {'objects': {t: getattr(space, f'show_object_select_{t}') for t in MASK_FLAGS} if space else None, 'mesh': tuple(scene.tool_settings.mesh_select_mode) if scene else None}

def apply_masks(masks):
    if not masks:
        return
    if masks['objects']:
        for space in all_view3d_spaces():
            for (t, value) in masks['objects'].items():
                setattr(space, f'show_object_select_{t}', value)
    if masks['mesh']:
        for scene in bpy.data.scenes:
            scene.tool_settings.mesh_select_mode = masks['mesh']

@bpy.app.handlers.persistent
def _masks_before_load(*_args):
    try:
        _carried['masks'] = session_masks()
    except (AttributeError, ReferenceError):
        _carried.pop('masks', None)

@bpy.app.handlers.persistent
def _masks_after_load(*_args):
    apply_masks(_carried.pop('masks', None))

class ALLSET_OT_select_mode(bpy.types.Operator):
    """Maya selection mode: Object (object mode) or Component (edit mode)"""
    bl_translation_context = 'MWK:ui/status_line.py:145'
    bl_idname = 'allset.select_mode'
    bl_label = _zh_native('Selection Mode', 'MWK:ui/status_line.py:145')
    bl_description = _zh_native('Maya selection mode: Object (object mode) or Component (edit mode)', 'MWK:ui/status_line.py:145')
    bl_options = {'UNDO'}
    mode: EnumProperty(items=_zh_enum((('OBJECT', 'Object', 'Select by object type (object mode)'), ('COMPONENT', 'Component', 'Select by component type (edit mode)')), 'MWK:ui/status_line.py:148'), translation_context='MWK:ui/status_line.py:148')

    @classmethod
    def description(cls, context, props):
        return _zh({'OBJECT': 'Select by object type (Object Mode)', 'COMPONENT': 'Select by component type (Edit Mode)'}[props.mode], 'MWK:ui/status_line.py:153')

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        target = 'OBJECT' if self.mode == 'OBJECT' else 'EDIT'
        if context.active_object.mode != target:
            bpy.ops.object.mode_set(mode=target)
        return {'FINISHED'}
SNAPS = (('GRID', _dcc_source('Snap to grids (hold X)'), 'SNAP_GRID', {'GRID'}), ('CURVE', _dcc_source('Snap to curves (hold C)'), 'SNAP_EDGE', {'EDGE'}), ('POINT', _dcc_source('Snap to points (hold V)'), 'SNAP_VERTEX', {'VERTEX'}), ('PROJECTED', _dcc_source('Snap to projected center'), 'PIVOT_MEDIAN', None), ('PLANE', _dcc_source('Snap to view planes'), 'VIEW_PERSPECTIVE', None), ('LIVE', _dcc_source('Snap to the surface under the cursor (Make Live)'), 'SNAP_FACE', {'FACE_PROJECT'}))
_SNAP_ELEMENTS = {s[0]: s[3] for s in SNAPS}

def snap_on(ts, name):
    elements = _SNAP_ELEMENTS[name]
    return elements is not None and ts.use_snap and (elements <= set(ts.snap_elements))

def toggle_snap(ts, name):
    """Status Line snap button: add/remove its element; snapping off when none is left."""
    current = set(ts.snap_elements) if ts.use_snap else set()
    elements = _SNAP_ELEMENTS[name]
    new = current - elements if snap_on(ts, name) else current | elements
    if new:
        ts.snap_elements = new
        ts.use_snap = True
        from ..operators import snap_align
        snap_align.settle_affect(ts)
    else:
        ts.use_snap = False

class ALLSET_OT_snap_toggle(bpy.types.Operator):
    """Toggle a Maya snap mode"""
    bl_translation_context = 'MWK:ui/status_line.py:204'
    bl_idname = 'allset.snap_toggle'
    bl_label = _zh_native('Snap Toggle', 'MWK:ui/status_line.py:204')
    bl_description = _zh_native('Toggle a Maya snap mode', 'MWK:ui/status_line.py:204')
    bl_options = {'INTERNAL'}
    snap: EnumProperty(items=_zh_enum([(s[0], s[0].title(), s[1]) for s in SNAPS if s[3]], 'MWK:ui/status_line.py:209'), translation_context='MWK:ui/status_line.py:209')

    @classmethod
    def description(cls, context, props):
        return _zh(next((s[1] for s in SNAPS if s[0] == props.snap)), 'MWK:ui/status_line.py:213')

    def execute(self, context):
        toggle_snap(context.scene.tool_settings, self.snap)
        return {'FINISHED'}
_KEEP_SNAP = {}

@bpy.app.handlers.persistent
def _keep_snap_pre(*_args):
    scene = bpy.context.scene
    if scene is not None:
        ts = scene.tool_settings
        _KEEP_SNAP['state'] = (scene.name, ts.use_snap, set(ts.snap_elements))

@bpy.app.handlers.persistent
def _keep_snap_post(*_args):
    if 'state' in _KEEP_SNAP and (not bpy.app.timers.is_registered(restore_snap)):
        bpy.app.timers.register(restore_snap, first_interval=0.0)

def restore_snap():
    """Put the Status Line snap state from before the undo / redo back (None: timer done)."""
    (name, on, elements) = _KEEP_SNAP.pop('state', (None, None, None))
    scene = bpy.context.scene
    if scene is None or scene.name != name:
        return None
    ts = scene.tool_settings
    if elements and set(ts.snap_elements) != elements:
        ts.snap_elements = elements
    if ts.use_snap != on:
        ts.use_snap = on
    return None
_SNAP_UNDO_HANDLERS = (('undo_pre', _keep_snap_pre), ('redo_pre', _keep_snap_pre), ('undo_post', _keep_snap_post), ('redo_post', _keep_snap_post))

class ALLSET_MT_symmetry(bpy.types.Menu):
    """Maya symmetry modes (Status Line ▾ list)"""
    bl_translation_context = 'MWK:ui/status_line.py:263'
    bl_idname = 'ALLSET_MT_symmetry'
    bl_label = _zh_native('Symmetry', 'MWK:ui/status_line.py:263')

    def draw(self, context):
        from ..operators import symmetry
        current = symmetry.mode_of(symmetry.state(context.scene))
        layout = self.layout
        for (mode, text) in symmetry.MODES:
            layout.operator('allset.symmetry', text=_zh(text, 'MWK:ui/status_line.py:270'), icon='RADIOBUT_ON' if mode == current else 'RADIOBUT_OFF').mode = mode

def draw_symmetry(layout, context):
    """▾ list with the mode text + a toggle that is blue (pressed) while symmetry is on.

    Maya: LMB ▾ = list, MMB = toggle, the text box turns blue when on (Maya 2022
    Status Line). A Blender menu button has no MMB action, so the toggle is its own button.
    """
    from ..operators import symmetry
    sym = symmetry.state(context.scene)
    row = layout.row(align=True)
    row.operator('allset.symmetry', text=_dcc_display(''), icon='MOD_MIRROR', depress=sym.on).mode = 'TOGGLE'
    sub = row.row(align=True)
    sub.ui_units_x = 6
    sub.menu(ALLSET_MT_symmetry.bl_idname, text=_zh(symmetry.label(sym), 'MWK:ui/status_line.py:286'), icon='DOWNARROW_HLT')
TRANSFORM_TOOLS = ('builtin.move', 'builtin.rotate', 'builtin.scale', 'builtin.transform', 'builtin.select', 'builtin.select_box', 'builtin.select_circle', 'builtin.select_lasso')

def draw_tool_symmetry(self, context):
    """Maya Move/Rotate/Scale Tool Settings 「Symmetry Settings」 (edit mesh only)."""
    if context.mode != 'EDIT_MESH':
        return
    tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    if tool is None or tool.idname not in TRANSFORM_TOOLS:
        return
    layout = self.layout
    layout.separator()
    layout.label(text=_zh('Symmetry Settings', 'MWK:ui/status_line.py:302'))
    draw_symmetry(layout, context)

def _properties_area(screen):
    """A Properties editor of ``screen`` that is not the Tool Settings dock (step 106)."""
    from . import maya_dock, tool_dock
    return next((a for a in (screen.areas if screen else ()) if a.type == 'PROPERTIES' and (not tool_dock.is_dock(a)) and (maya_dock.role(a) is None)), None)

def show_properties(screen, context_name):
    """Switch a Properties editor to a tab; False if the screen has none."""
    area = _properties_area(screen)
    if area is None:
        return False
    try:
        area.spaces.active.context = context_name
    except TypeError:
        return False
    return True

class ALLSET_OT_render_settings(bpy.types.Operator):
    """Open the render settings (Maya Render Settings window)"""
    bl_translation_context = 'MWK:ui/status_line.py:330'
    bl_idname = 'allset.render_settings'
    bl_label = _zh_native('Render Settings', 'MWK:ui/status_line.py:330')
    bl_description = _zh_native('Open the render settings (Maya Render Settings window)', 'MWK:ui/status_line.py:330')

    def execute(self, context):
        if context.window is not None:
            from . import render_settings
            if render_settings.open_window(context) is not None:
                return {'FINISHED'}
        return {'FINISHED'} if show_properties(context.screen, 'RENDER') else {'CANCELLED'}

class ALLSET_OT_ipr_toggle(bpy.types.Operator):
    """IPR: interactive render in the main viewport (toggle Rendered shading)"""
    bl_translation_context = 'MWK:ui/status_line.py:349'
    bl_idname = 'allset.ipr_toggle'
    bl_label = _zh_native('IPR Render', 'MWK:ui/status_line.py:349')
    bl_description = _zh_native('IPR: interactive render in the main viewport (toggle Rendered shading)', 'MWK:ui/status_line.py:349')

    def execute(self, context):
        (area, _r) = main_view3d(context.screen)
        if area is None:
            return {'CANCELLED'}
        ipr_toggle(area.spaces.active)
        return {'FINISHED'}

def ipr_toggle(space):
    """IPR on = Rendered shading; off = the shading the view had before (Wireframe stays Wireframe, #24)."""
    from . import panel_menus
    if space.shading.type == 'RENDERED':
        panel_menus.leave_rendered(space)
    else:
        panel_menus.enter_rendered(space)
EDITORS = (('MODELING_TOOLKIT', _dcc_source('Show or hide the Modeling Toolkit'), 'EDITMODE_HLT'), ('ATTRIBUTE', _dcc_source('Show or hide the Attribute Editor'), 'PROPERTIES'), ('TOOL_SETTINGS', _dcc_source('Show or hide the Tool Settings of the active tool (dock left of the viewport)'), 'TOOL_SETTINGS'), ('CHANNEL_BOX', _dcc_source('Show or hide the Channel Box / Layer Editor'), 'MENU_PANEL'))
DOCK_KINDS = {'MODELING_TOOLKIT': 'MODELING_TOOLKIT', 'ATTRIBUTE': 'ATTRIBUTE_EDITOR', 'CHANNEL_BOX': 'CHANNEL_BOX'}

def editor_shown(screen, editor):
    if editor == 'TOOL_SETTINGS':
        from . import tool_dock
        return tool_dock.shown(screen)
    from . import maya_dock
    return maya_dock.kind_visible(bpy.context.window_manager, DOCK_KINDS[editor])

class ALLSET_OT_editor_toggle(bpy.types.Operator):
    """Show or hide a Maya editor"""
    bl_translation_context = 'MWK:ui/status_line.py:392'
    bl_idname = 'allset.editor_toggle'
    bl_label = _zh_native('Toggle Editor', 'MWK:ui/status_line.py:392')
    bl_description = _zh_native('Show or hide a Maya editor', 'MWK:ui/status_line.py:392')
    bl_options = {'INTERNAL'}
    editor: EnumProperty(items=_zh_enum([(e[0], e[0].title(), e[1]) for e in EDITORS], 'MWK:ui/status_line.py:395'), translation_context='MWK:ui/status_line.py:395')
    show: bpy.props.BoolProperty(options={'SKIP_SAVE'}, description=_zh_native('Only show the editor (Maya toolPropertyWindow), never hide it', 'MWK:ui/status_line.py:396'), translation_context='MWK:ui/status_line.py:396')

    @classmethod
    def description(cls, context, props):
        return _zh(next((e[1] for e in EDITORS if e[0] == props.editor)), 'MWK:ui/status_line.py:401')

    def execute(self, context):
        if self.editor == 'TOOL_SETTINGS':
            from . import tool_dock
            tool_dock.toggle(context, show_only=self.show)
            return {'FINISHED'}
        from . import maya_dock
        maya_dock.toggle(context, DOCK_KINDS[self.editor], show_only=self.show)
        return {'FINISHED'}
GROUPS = (('FILE', _dcc_source('File: New, Open, Save, Undo, Redo')), ('SELECT_MODE', _dcc_source('Selection mode: hierarchy, object, component')), ('MASKS', _dcc_source('Selection masks')), ('SNAP', _dcc_source('Snap toggles')), ('SYMMETRY', _dcc_source('Symmetry')), ('HISTORY', _dcc_source('Construction History')), ('RENDER', _dcc_source('Render')), ('INPUT', _dcc_source('Input line: absolute / relative transform, rename, select by name')), ('EDITORS', _dcc_source('Editor toggles')))
DEFAULT_COLLAPSED = ('MASKS', 'HISTORY', 'INPUT')
_collapsed = set(DEFAULT_COLLAPSED)

class ALLSET_OT_status_group(bpy.types.Operator):
    """Show or hide this Status Line group (Maya collapse handle)"""
    bl_translation_context = 'MWK:ui/status_line.py:441'
    bl_idname = 'allset.status_group'
    bl_label = _zh_native('Status Line Group', 'MWK:ui/status_line.py:441')
    bl_description = _zh_native('Show or hide this Status Line group (Maya collapse handle)', 'MWK:ui/status_line.py:441')
    bl_options = {'INTERNAL'}
    group: EnumProperty(items=_zh_enum([(g, g.replace('_', ' ').title(), d) for (g, d) in GROUPS], 'MWK:ui/status_line.py:444'), translation_context='MWK:ui/status_line.py:444')

    @classmethod
    def description(cls, context, props):
        desc = next((d for (g, d) in GROUPS if g == props.group))
        return f"{_dcc_display(_dcc_source('Show') if props.group in _collapsed else _dcc_source('Hide'))}: {_dcc_display(desc)}"

    def execute(self, context):
        _collapsed.symmetric_difference_update({self.group})
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
        return {'FINISHED'}
ICON_SCALE = 1.0

def _flat(layout, op, name, depress=False, text=''):
    """A Maya Status Line button: a kit-drawn glyph without a frame; a pressed button gets the frame (Maya's blue
    square behind an active toggle)."""
    sub = layout.row(align=True)
    sub.scale_x = sub.scale_y = ICON_SCALE
    if not depress:
        sub.emboss = 'NONE'
    return sub.operator(op, text=_zh(text, 'MWK:ui/status_line.py:471'), icon_value=status_icons.icon(name), depress=depress)

def _grey(layout, name, item):
    _flat(layout, menu_sets.ALLSET_OT_menu_unavailable.bl_idname, name).item = item

def _group(layout, group):
    """Maya group start: the bar, then the filled arrow when the group is collapsed. True when its buttons should be
    drawn (``_group_end`` then adds the open collapse arrow)."""
    bar = layout.row(align=True)
    bar.ui_units_x = 0.5
    bar.label(text=_dcc_display(''), icon_value=status_icons.icon('bar'))
    if group in _collapsed:
        sub = layout.row(align=True)
        sub.ui_units_x = 0.6
        sub.emboss = 'NONE'
        sub.operator(ALLSET_OT_status_group.bl_idname, text=_dcc_display(''), icon_value=status_icons.icon('closed')).group = group
        return False
    return True

def _group_end(layout, group):
    sub = layout.row(align=True)
    sub.ui_units_x = 0.6
    sub.emboss = 'NONE'
    sub.operator(ALLSET_OT_status_group.bl_idname, text=_dcc_display(''), icon_value=status_icons.icon('open')).group = group

def _field(layout, owner, prop, units):
    sub = layout.row(align=True)
    sub.ui_units_x = units
    sub.prop(owner, prop, text=_dcc_display(''))

def draw_status_line(layout, context, compact=False):
    """The Maya Status Line, left to right (Maya 2022:
    menu set combo, then groups of bar + buttons + collapse arrow, sidebar toggles at the right end). ``compact``
    (the 3D View tool header of other layouts, which overflows): the input line goes after the editor toggles
    (step 75, delegated)."""
    from .. import preferences
    screen = context.screen
    ts = context.scene.tool_settings
    (area, _r) = main_view3d(screen)
    space = area.spaces.active if area else None
    sub = layout.row(align=True)
    sub.ui_units_x = 5
    sub.prop(preferences.get(context), 'menu_set', text=_dcc_display(''))
    if _group(layout, 'FILE'):
        row = layout.row(align=True)
        _flat(row, 'allset.new_maya_scene', 'new')
        _flat(row, 'allset.open_scene', 'open_scene')
        _flat(row, 'allset.save_scene', 'save')
        _flat(row, 'ed.undo', 'undo')
        _flat(row, 'ed.redo', 'redo')
        _group_end(layout, 'FILE')
    if _group(layout, 'SELECT_MODE'):
        editing = context.mode != 'OBJECT' and context.mode.startswith('EDIT')
        row = layout.row(align=True)
        _grey(row, 'sel_hierarchy', _dcc_source('Status Line/Select by hierarchy'))
        _flat(row, ALLSET_OT_select_mode.bl_idname, 'sel_object', depress=not editing).mode = 'OBJECT'
        _flat(row, ALLSET_OT_select_mode.bl_idname, 'sel_component', depress=editing).mode = 'COMPONENT'
        _group_end(layout, 'SELECT_MODE')
    if _group(layout, 'MASKS'):
        row = layout.row(align=True)
        if context.mode == 'EDIT_MESH':
            for (i, name) in enumerate(('vertex', 'edge', 'face')):
                sub = row.row(align=True)
                if not ts.mesh_select_mode[i]:
                    sub.emboss = 'NONE'
                sub.prop(ts, 'mesh_select_mode', index=i, text=_dcc_display(''), icon_value=status_icons.icon(name))
        else:
            for (group, desc, _icon, types) in OBJECT_MASKS:
                if types is None:
                    _grey(row, 'mask_' + group, f'Status Line/{desc}')
                else:
                    _flat(row, ALLSET_OT_select_mask.bl_idname, 'mask_' + group, depress=bool(space) and mask_on(space, group)).group = group
        _group_end(layout, 'MASKS')
    if _group(layout, 'SNAP'):
        row = layout.row(align=True)
        for (name, desc, _icon, elements) in SNAPS:
            if elements is None:
                _grey(row, 'snap_' + name, f'Status Line/{desc}')
            else:
                _flat(row, ALLSET_OT_snap_toggle.bl_idname, 'snap_' + name, depress=snap_on(ts, name)).snap = name
        row = layout.row(align=True)
        sub = row.row(align=True)
        sub.emboss = 'NONE'
        sub.operator('allset.make_live', text=_dcc_display(''), icon='DOWNARROW_HLT')
        _field(row, context.scene, 'allset_live_text', 5)
        _group_end(layout, 'SNAP')
    if _group(layout, 'SYMMETRY'):
        row = layout.row(align=True)
        sub = row.row(align=True)
        sub.emboss = 'NONE'
        sub.menu(ALLSET_MT_symmetry.bl_idname, text=_dcc_display(''), icon='DOWNARROW_HLT')
        box = row.row(align=True)
        box.ui_units_x = 5
        box.menu(ALLSET_MT_symmetry.bl_idname, text=_zh(_symmetry_text(None), 'MWK:ui/status_line.py:579'))
        _group_end(layout, 'SYMMETRY')
    if _group(layout, 'HISTORY'):
        _flat(layout, input_line.ALLSET_OT_construction_history.bl_idname, 'history', depress=context.window_manager.allset_construction_history)
        _group_end(layout, 'HISTORY')
    if _group(layout, 'RENDER'):
        row = layout.row(align=True)
        _flat(row, 'render.view_show', 'render_view')
        _flat(row, 'allset.render_current_frame', 'render')
        _flat(row, ALLSET_OT_ipr_toggle.bl_idname, 'ipr', depress=bool(space) and space.shading.type == 'RENDERED')
        _flat(row, ALLSET_OT_render_settings.bl_idname, 'render_settings')
        _flat(row, 'allset.hypershade', 'hypershade')
        _grey(row, 'render_setup', _dcc_source('Status Line/Render Setup'))
        _flat(row, 'allset.light_editor', 'light_editor')
        _grey(row, 'pause', _dcc_source('Status Line/Pause Viewport 2.0'))
        _group_end(layout, 'RENDER')
    if not compact and _group(layout, 'INPUT'):
        input_line.draw(layout, context)
        _group_end(layout, 'INPUT')
    if not compact:
        layout.separator_spacer()
    row = layout.row(align=True)
    for (editor, _desc, _icon) in EDITORS:
        if editor == 'TOOL_SETTINGS':
            _grey(row, 'ed_CHARACTER', _dcc_source('Status Line/Show or hide the Character Controls'))
        _flat(row, ALLSET_OT_editor_toggle.bl_idname, 'ed_' + editor, depress=editor_shown(screen, editor)).editor = editor
    if compact and _group(layout, 'INPUT'):
        input_line.draw(layout, context)
        _group_end(layout, 'INPUT')

def _live_text(self):
    live = getattr(bpy.context.scene, 'allset_live', None)
    return live.name if live else _zh('No Live Surface', 'MWK:ui/status_line.py:635')

def _symmetry_text(self):
    from ..operators import symmetry
    return _zh(symmetry.label(symmetry.state(bpy.context.scene)), 'MWK:ui/status_line.py:640')

def _read_only(self, value):
    pass

def _maya_bar(context):
    from .. import preferences
    try:
        return preferences.get(context).maya_top_bar
    except KeyError:
        return False
_top_bars = {}

def redraw_top_bars():
    open_windows = {w.as_pointer() for w in bpy.context.window_manager.windows}
    for key in list(_top_bars):
        if key not in open_windows:
            del _top_bars[key]
            continue
        try:
            _top_bars[key].tag_redraw()
        except ReferenceError:
            del _top_bars[key]
MENU_LEAD_UNITS = 0.4
LOGO_UNITS = 1.6
MENU_SET_UNITS = 5.5
MENU_MORE_UNITS = 1.5
MENU_SLACK_UNITS = 0.5
_menus_shown = {}

def menu_fit(widths, width, fixed, more):
    """How many leading menus (px ``widths``) the bar shows in ``width`` px after ``fixed`` px; when they don't all
    fit, the » button (``more`` px) takes its place at the end."""
    if fixed + sum(widths) <= width:
        return len(widths)
    x = fixed + more
    n = 0
    for w in widths:
        if x + w > width:
            break
        x += w
        n += 1
    return n

def menu_bar_widths(context, names, menu_set):
    """(px width of each menu of ``names``, fixed px: padding, logo, menu set dropdown, slack, » button)."""
    from .toolbar_fit import unit
    system = context.preferences.system
    u = unit(system.ui_scale or 1.0, system.pixel_size)
    widths = []
    for name in names:
        cls = getattr(bpy.types, menu_sets.menu_idname(name), None)
        label = cls.bl_label if cls is not None else name
        widths.append(int(menu_sets.menu_width_units(label, context) * u))
    fixed = int((MENU_LEAD_UNITS + LOGO_UNITS + MENU_SLACK_UNITS) * u) + (int(MENU_SET_UNITS * u) if menu_set else 0)
    return (widths, fixed, int(MENU_MORE_UNITS * u))

def shown_menus(window):
    """(menu names, how many the menu bar of ``window`` showed when it was last drawn)."""
    return _menus_shown.get(window.as_pointer(), ((), 0)) if window is not None else ((), 0)

def _menu_set_field(layout, prefs):
    sub = layout.row()
    sub.ui_units_x = MENU_SET_UNITS
    sub.prop(prefs, 'menu_set', text=_dcc_display(''))

def draw_menu_bar_fit(layout, context, menu_set=True):
    """``menu_sets.draw_menu_bar`` when every menu fits the region, else the menus that fit and Maya's » overflow."""
    from .. import preferences
    prefs = preferences.get(context)
    names = menu_sets.menus_for_set(prefs.menu_set)
    region = getattr(context, 'region', None)
    (widths, fixed, more) = menu_bar_widths(context, names, menu_set)
    n = menu_fit(widths, region.width, fixed, more) if region is not None and region.width > 1 else len(names)
    if context.window is not None:
        _menus_shown[context.window.as_pointer()] = (tuple(names), n)
    if n >= len(names):
        menu_sets.draw_menu_bar(layout, context, menu_set=menu_set)
        return
    layout.menu('TOPBAR_MT_blender', text=_dcc_display(''), icon='BLENDER')
    common = len(menu_sets._SET_MENUS[menu_sets.COMMON_SET])
    for (i, name) in enumerate(names[:n]):
        cls = getattr(bpy.types, menu_sets.menu_idname(name), None)
        sub = layout.row(align=True)
        sub.ui_units_x = menu_sets.menu_width_units(cls.bl_label if cls else name, context)
        sub.menu(menu_sets.menu_idname(name))
        if menu_set and i == common - 1:
            _menu_set_field(layout, prefs)
    if menu_set and n < common:
        _menu_set_field(layout, prefs)
    sub = layout.row(align=True)
    sub.ui_units_x = MENU_MORE_UNITS
    icon = status_icons.icon('pt_more') if 'pt_more' in status_icons.EXTRA else 0
    if icon:
        sub.menu(ALLSET_MT_menu_more.bl_idname, text=_dcc_display(''), icon_value=icon)
    else:
        sub.menu(ALLSET_MT_menu_more.bl_idname, text=_zh('»', 'MWK:ui/status_line.py:742'))

class ALLSET_MT_menu_more(bpy.types.Menu):
    """More Maya menus: the ones that don't fit the menu bar"""
    bl_translation_context = 'MWK:ui/status_line.py:748'
    bl_idname = 'ALLSET_MT_menu_more'
    bl_label = _zh_native('More Menus', 'MWK:ui/status_line.py:748')

    def draw(self, context):
        (names, n) = shown_menus(context.window)
        for name in names[n:]:
            self.layout.menu(menu_sets.menu_idname(name))

def draw_left(self, context):
    if context.window is not None and context.area is not None:
        _top_bars[context.window.as_pointer()] = context.area
    if not _maya_bar(context):
        return bpy.types.TOPBAR_HT_upper_bar.draw_left(self, context)
    layout = self.layout
    if context.area.show_menus:
        draw_menu_bar_fit(layout.row(align=True), context, menu_set=not status_line_shown(context))
    else:
        layout.menu(menu_sets.ALLSET_MT_menu_bar.bl_idname, text=_dcc_display(''), icon='COLLAPSEMENU')
    if context.screen.show_fullscreen:
        layout.separator()
        layout.operator('screen.back_to_previous', icon='SCREEN_BACK', text=_zh('Back to Previous', 'MWK:ui/status_line.py:768'))

def draw_right(self, context):
    if not _maya_bar(context):
        return bpy.types.TOPBAR_HT_upper_bar.draw_right(self, context)
    layout = self.layout
    window = context.window
    if not context.screen.show_statusbar:
        layout.template_reports_banner()
        layout.template_running_jobs()
    row = layout.row(align=True)
    row.label(text=_zh('Workspace:', 'MWK:ui/status_line.py:783'))
    sub = row.row(align=True)
    sub.ui_units_x = 7
    sub.prop(context.window_manager, 'allset_workspace', text=_dcc_display(''))
    if len(bpy.data.scenes) > 1:
        row = layout.row()
        row.ui_units_x = 6
        row.template_ID(window, 'scene', new='scene.new')

def status_line_shown(context):
    """A Status Line is drawn in this screen: the Maya strip row, or the main 3D View's tool header."""
    from .shelf import strip_area
    screen = context.screen
    if screen is None:
        return False
    if strip_area(screen) is not None:
        return True
    from .. import preferences
    try:
        if not preferences.get(context).show_status_line:
            return False
    except KeyError:
        return False
    (area, _r) = main_view3d(screen)
    return area is not None and area.spaces.active.show_region_tool_header

def _workspaces(self, context):
    from . import workspaces
    return workspaces.dropdown_items(self, context)

def _get_workspace(self):
    from . import workspaces
    return workspaces.dropdown_get(self)

def _set_workspace(self, value):
    from . import workspaces
    workspaces.dropdown_set(self, value)

def draw_tool_header(self, context):
    """Status Line at the start of the main 3D View's tool header row."""
    from .. import preferences
    try:
        if not preferences.get(context).show_status_line:
            return
    except KeyError:
        return
    (area, _r) = main_view3d(context.screen)
    if area is None or context.area != area:
        return
    from .shelf import strip_area
    if strip_area(context.screen) is not None:
        return
    draw_status_line(self.layout, context, compact=True)
    self.layout.separator(type='LINE')

def draw_upper_bar(self, context):
    """The top bar's own draw while the kit is on (as space_topbar.py TOPBAR_HT_upper_bar.draw, with the kit's
    left / right): Blender's ``draw_left`` / ``draw_right`` methods stay untouched (step 115)."""
    if context.region.alignment == 'RIGHT':
        draw_right(self, context)
    else:
        draw_left(self, context)

def patch_topbar():
    own_draw.swap('TOPBAR_HT_upper_bar', draw_upper_bar)

def unpatch_topbar():
    own_draw.restore('TOPBAR_HT_upper_bar', draw_upper_bar)
classes = (ALLSET_OT_select_mask, ALLSET_OT_select_mode, ALLSET_OT_snap_toggle, ALLSET_MT_symmetry, ALLSET_MT_menu_more, ALLSET_OT_render_settings, ALLSET_OT_ipr_toggle, ALLSET_OT_editor_toggle, ALLSET_OT_status_group)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.allset_live_text = StringProperty(name=_zh_native('Live Surface', 'MWK:ui/status_line.py:873'), description=_zh_native('The live surface (Make Live); No Live Surface when none', 'MWK:ui/status_line.py:873'), get=_live_text, set=_read_only, options={'SKIP_SAVE'}, translation_context='MWK:ui/status_line.py:873')
    bpy.types.Scene.allset_symmetry_text = StringProperty(name=_zh_native('Symmetry', 'MWK:ui/status_line.py:876'), description=_zh_native('Symmetric modeling: the current mode (the arrow opens the list)', 'MWK:ui/status_line.py:876'), get=_symmetry_text, set=_read_only, options={'SKIP_SAVE'}, translation_context='MWK:ui/status_line.py:876')
    bpy.types.WindowManager.allset_workspace = EnumProperty(name=_zh_native('Workspace', 'MWK:ui/status_line.py:879'), description=_zh_native('Maya workspace: switch to another workspace of this file', 'MWK:ui/status_line.py:879'), items=_zh_enum(_workspaces, 'MWK:ui/status_line.py:879'), get=_get_workspace, set=_set_workspace, options={'SKIP_SAVE'}, translation_context='MWK:ui/status_line.py:879')
    patch_topbar()
    bpy.types.VIEW3D_HT_tool_header.prepend(draw_tool_header)
    bpy.types.VIEW3D_PT_active_tool.append(draw_tool_symmetry)
    bpy.app.handlers.load_pre.append(_masks_before_load)
    bpy.app.handlers.load_post.append(_masks_after_load)
    for (name, fn) in _SNAP_UNDO_HANDLERS:
        getattr(bpy.app.handlers, name).append(fn)

def unregister():
    for (name, fn) in _SNAP_UNDO_HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn in handlers:
            handlers.remove(fn)
    if bpy.app.timers.is_registered(restore_snap):
        bpy.app.timers.unregister(restore_snap)
    _KEEP_SNAP.clear()
    for (handlers, fn) in ((bpy.app.handlers.load_pre, _masks_before_load), (bpy.app.handlers.load_post, _masks_after_load)):
        if fn in handlers:
            handlers.remove(fn)
    _carried.clear()
    bpy.types.VIEW3D_PT_active_tool.remove(draw_tool_symmetry)
    bpy.types.VIEW3D_HT_tool_header.remove(draw_tool_header)
    unpatch_topbar()
    del bpy.types.WindowManager.allset_workspace
    del bpy.types.Scene.allset_live_text
    del bpy.types.Scene.allset_symmetry_text
    _collapsed.clear()
    _collapsed.update(DEFAULT_COLLAPSED)
    _top_bars.clear()
    _menus_shown.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
