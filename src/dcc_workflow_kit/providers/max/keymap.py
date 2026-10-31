# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format
'Reversible Blender Max viewport bindings, researched against Max 2027.\n\nOnly addon-owned entries are touched. No preference or existing keymap mutation.\nKEY_TABLE is also the source for the on-screen shortcut reference. Assignments\ncome from the installed UI_ln/CUI/Default.hsxb; the last column is its action id.\n'
import bpy

def C(command):
    return {'command': command}
KEY_TABLE = (('Q', _msg('Select Object'), 'bsm.tool', 'Q', {}, {'tool': 'SELECT'}, '647394-SmartSelect`Selection'), ('W', _msg('Select and Move'), 'bsm.tool', 'W', {}, {'tool': 'MOVE'}, '0-50001'), ('E', _msg('Select and Rotate'), 'bsm.tool', 'E', {}, {'tool': 'ROTATE'}, '0-50002'), ('R', _msg('Select and Scale'), 'bsm.tool', 'R', {}, {'tool': 'SCALE'}, '647394-SmartScale`Tools'), ('Y', _msg('Select and Place'), 'bsm.place_surface', 'Y', {}, {}, '647394-SmartPlace`Tools'), ('1', _msg('Vertex level'), 'bsm.component', 'ONE', {}, {'level': 1}, _msg('647394-SubObject_1`Modifier Stack')), ('2', _msg('Edge level'), 'bsm.component', 'TWO', {}, {'level': 2}, _msg('647394-SubObject_2`Modifier Stack')), ('3', _msg('Border level'), 'bsm.component', 'THREE', {}, {'level': 3}, _msg('647394-SubObject_3`Modifier Stack')), ('4', _msg('Polygon level'), 'bsm.component', 'FOUR', {}, {'level': 4}, _msg('647394-SubObject_4`Modifier Stack')), ('5', _msg('Element level'), 'bsm.component', 'FIVE', {}, {'level': 5}, _msg('647394-SubObject_5`Modifier Stack')), ('F2', _msg('Shade Selected Faces'), 'bsm.max_command', 'F2', {}, C('SHADE_SELECTED'), '0-371'), ('F3', _msg('Wireframe / Smooth + Highlights'), 'bsm.shading', 'F3', {}, {'mode': 'WIRE'}, '0-272'), ('F4', _msg('Edged Faces'), 'bsm.shading', 'F4', {}, {'mode': 'EDGES'}, '0-369'), ('G', _msg('Show Grids'), 'bsm.shading', 'G', {}, {'mode': 'GRID'}, '0-40077'), ('Z', _msg('Zoom Extents Selected'), 'bsm.frame_selected', 'Z', {}, {}, '0-310'), (_msg('Ctrl+Alt+Z'), _msg('Zoom Extents'), 'bsm.toolbar_action', 'Z', {'ctrl': True, 'alt': True}, {'action': 'FRAME'}, '0-330'), (_msg('Ctrl+Shift+Z'), _msg('Zoom Extents All'), 'bsm.navigation', 'Z', {'ctrl': True, 'shift': True}, {'kind': 'EXTENTS_ALL'}, '0-331'), (_msg('Alt+Z'), _msg('Zoom'), 'bsm.navigation', 'Z', {'alt': True}, {'kind': 'ZOOM'}, '0-50013'), (_msg('Ctrl+W'), _msg('Zoom Region'), 'bsm.navigation', 'W', {'ctrl': True}, {'kind': 'REGION'}, '0-50014'), (_msg('Ctrl+P'), _msg('Pan View'), 'bsm.navigation', 'P', {'ctrl': True}, {'kind': 'PAN'}, '0-40202'), (_msg('Ctrl+R'), _msg('Orbit'), 'bsm.navigation', 'R', {'ctrl': True}, {'kind': 'ORBIT'}, '0-40203'), ('[', _msg('Zoom In'), 'view3d.zoom', 'LEFT_BRACKET', {}, {'delta': 1}, '0-321'), (']', _msg('Zoom Out'), 'view3d.zoom', 'RIGHT_BRACKET', {}, {'delta': -1}, '0-320'), (_msg('Shift+Z'), _msg('Undo View Change'), 'bsm.max_command', 'Z', {'shift': True}, C('UNDO_VIEW'), '0-40104'), (_msg('Shift+Y'), _msg('Redo View Change'), 'bsm.max_command', 'Y', {'shift': True}, C('REDO_VIEW'), '0-40101'), ('F', _msg('Front view'), 'bsm.view', 'F', {}, {'view': 'FRONT'}, '0-40060'), ('L', _msg('Left view'), 'bsm.view', 'L', {}, {'view': 'LEFT'}, '0-40061'), ('T', _msg('Top view'), 'bsm.view', 'T', {}, {'view': 'TOP'}, '0-40059'), ('P', _msg('Perspective view'), 'bsm.view', 'P', {}, {'view': 'PERSP'}, '0-40182'), ('U', _msg('Orthographic view'), 'bsm.view', 'U', {}, {'view': 'ORTHO'}, '0-40183'), ('C', _msg('Camera view'), 'bsm.view', 'C', {}, {'view': 'CAMERA'}, '0-40068'), (_msg('Alt+W'), _msg('Maximize Viewport Toggle'), 'bsm.quad_view', 'W', {'alt': True}, {}, '0-50026'), (_msg('Ctrl+Alt+X'), _msg('Expert Mode'), 'bsm.max_command', 'X', {'ctrl': True, 'alt': True}, C('EXPERT_MODE'), '0-40264'), ('M', _msg('Material Editor'), 'bsm.editor', 'M', {}, {'kind': 'MATERIAL_LAST'}, '0-50048'), (_msg('Ctrl+V'), _msg('Clone'), 'bsm.clone', 'V', {'ctrl': True}, {}, '0-40213'), ('K', _msg('Set Keys'), 'bsm.keyframe', 'K', {}, {'channels': 'FILTERED'}, '0-40800'), ('N', _msg('Auto Key Mode Toggle'), 'wm.context_toggle', 'N', {}, {'data_path': 'scene.tool_settings.use_keyframe_insert_auto'}, '0-50024'), (',', _msg('Previous Frame'), 'screen.frame_offset', 'COMMA', {}, {'delta': -1}, '0-50020'), ('.', _msg('Next Frame'), 'screen.frame_offset', 'PERIOD', {}, {'delta': 1}, '0-50022'), (_msg('Ctrl+Shift+N'), _msg('Selection Lock Toggle'), 'bsm.select_lock', 'N', {'ctrl': True, 'shift': True}, {}, '0-59231'), (_msg('Shift+N'), _msg('Sidebar (Add-on Panels)'), 'wm.context_toggle', 'N', {'shift': True}, {'data_path': 'space_data.show_region_ui'}, _msg('unassigned in Max')), ('S', _msg('Snaps Toggle'), 'wm.context_toggle', 'S', {}, {'data_path': 'tool_settings.use_snap'}, '0-40072'), ('A', _msg('Angle Snap Toggle'), 'wm.context_toggle', 'A', {}, {'data_path': 'tool_settings.use_snap_rotate'}, '0-40074'), ('H', _msg('Select by Name'), 'bsm.select_from_scene', 'H', {}, {}, '0-50029'), (_msg('Shift+O'), _msg('Window/Crossing Toggle'), 'wm.context_toggle', 'O', {'shift': True}, {'data_path': 'window_manager.bsm.window_selection'}, '0-202'), (_msg('Ctrl+Shift+A'), _msg('Select Similar'), 'bsm.max_command', 'A', {'ctrl': True, 'shift': True}, C('SELECT_SIMILAR'), '0-40099'), (_msg('Page Up'), _msg('Select Ancestor'), 'object.select_hierarchy', 'PAGE_UP', {}, {'direction': 'PARENT'}, '0-40193'), (_msg('Page Down'), _msg('Select Child'), 'object.select_hierarchy', 'PAGE_DOWN', {}, {'direction': 'CHILD'}, '0-40194'), (_msg('Alt+A'), _msg('Align'), 'bsm.max_command', 'A', {'alt': True}, C('ALIGN'), '0-40113'), (_msg('Shift+A'), _msg('Quick Align'), 'bsm.max_command', 'A', {'shift': True}, C('QUICK_ALIGN'), '0-49'), (_msg('Insert'), _msg('Affect Pivot Only'), 'wm.context_toggle', 'INSERT', {}, {'data_path': 'scene.tool_settings.use_transform_data_origin'}, '647394-PivotMode_Toggle`Tools'), (_msg('Alt+Q'), _msg('Isolate Selection'), 'bsm.max_command', 'Q', {'alt': True}, C('ISOLATE'), '0-197'), (_msg('Alt+H'), _msg('Hide Selection'), 'bsm.toolbar_action', 'H', {'alt': True}, {'action': 'HIDE'}, '0-223'), (_msg('Alt+I'), _msg('Hide Unselected'), 'object.hide_view_set', 'I', {'alt': True}, {'unselected': True}, '0-281'), (_msg('Alt+U'), _msg('Unhide All'), 'bsm.toolbar_action', 'U', {'alt': True}, {'action': 'UNHIDE'}, '0-277'), ('7', _msg('Show Statistics'), 'bsm.max_command', 'SEVEN', {}, C('XVIEW_STATS'), '0-40829'), ('8', _msg('Environment'), 'bsm.max_command', 'EIGHT', {}, C('ENVIRONMENT'), '0-40029'), ('X', _msg('Search 3ds Max Commands'), 'bsm.max_command', 'X', {}, C('SEARCH_COMMANDS'), '0-63621'), (_msg('Delete'), _msg('Delete'), 'bsm.max_command', 'DEL', {}, C('DELETE'), '0-40020'), (_msg('Ctrl+H'), _msg('Hold'), 'bsm.max_command', 'H', {'ctrl': True}, C('HOLD'), '0-40087'), (_msg('Ctrl+Alt+F'), _msg('Fetch'), 'bsm.max_command', 'F', {'ctrl': True, 'alt': True}, C('FETCH'), '0-40088'), (_msg('Ctrl+Y'), _msg('Redo'), 'ed.redo', 'Y', {'ctrl': True}, {}, '0-40016'), ('F9', _msg('Render Last'), 'bsm.render_view', 'F9', {}, {}, '0-50030'), (_msg('Shift+Q'), _msg('Render'), 'bsm.render_view', 'Q', {'shift': True}, {}, '0-50031'), ('F10', _msg('Render Setup'), 'bsm.editor', 'F10', {}, {'kind': 'RENDER'}, '0-60010'), ('F11', _msg('Scripting Listener'), 'bsm.editor', 'F11', {}, {'kind': 'CONSOLE'}, '0-40472'), ('F12', _msg('Transform Type-In'), 'bsm.transform_typein', 'F12', {}, {}, '0-40093'), (_msg('Home'), _msg('Go to Start Frame'), 'screen.frame_jump', 'HOME', {}, {'end': False}, '0-50019'), (_msg('End'), _msg('Go to End Frame'), 'screen.frame_jump', 'END', {}, {'end': True}, '0-50023'), ('/', _msg('Play Animation'), 'screen.animation_play', 'SLASH', {}, {}, '0-50021'), (_msg('Ctrl+A'), _msg('Select All'), 'object.select_all', 'A', {'ctrl': True}, {'action': 'SELECT'}, '0-40021'), (_msg('Ctrl+D'), _msg('Select None'), 'object.select_all', 'D', {'ctrl': True}, {'action': 'DESELECT'}, '0-40043'), (_msg('Ctrl+I'), _msg('Select Invert'), 'object.select_all', 'I', {'ctrl': True}, {'action': 'INVERT'}, '0-40044'), (_msg('Shift+F9'), _msg('Render'), 'bsm.render_view', 'F9', {'shift': True}, {}, '0-50031'), ('F5', _msg('Transform Gizmo X Constraint'), 'bsm.max_command', 'F5', {}, C('GIZMO_X'), '0-50004'), ('F6', _msg('Transform Gizmo Y Constraint'), 'bsm.max_command', 'F6', {}, C('GIZMO_Y'), '0-50006'), ('F7', _msg('Transform Gizmo Z Constraint'), 'bsm.max_command', 'F7', {}, C('GIZMO_Z'), '0-50007'), ('F8', _msg('Transform Gizmo Plane Constraint Cycle'), 'bsm.max_command', 'F8', {}, C('GIZMO_PLANE_CYCLE'), '0-59229'), ('-', _msg('Transform Gizmo Size Down'), 'bsm.max_command', 'MINUS', {}, C('GIZMO_SIZE_DOWN'), '0-419'), ('=', _msg('Transform Gizmo Size Up'), 'bsm.max_command', 'EQUAL', {}, C('GIZMO_SIZE_UP'), '0-418'), (_msg('Ctrl+Alt+S'), _msg('Save Incremental (+)'), 'bsm.max_command', 'S', {'ctrl': True, 'alt': True}, C('SAVE_INCREMENTAL'), '0-286'), (_msg('Shift+4'), _msg('Spot/Directional Light View'), 'bsm.max_command', 'FOUR', {'shift': True}, C('LIGHT_VIEW'), '0-217'), (_msg('Shift+G'), _msg('Hide Geometry Toggle'), 'wm.context_toggle', 'G', {'shift': True}, {'data_path': 'space_data.show_object_viewport_mesh'}, '0-40190'), (_msg('Shift+S'), _msg('Hide Shapes Toggle'), 'wm.context_toggle', 'S', {'shift': True}, {'data_path': 'space_data.show_object_viewport_curve'}, '0-40191'), (_msg('Shift+L'), _msg('Hide Lights Toggle'), 'wm.context_toggle', 'L', {'shift': True}, {'data_path': 'space_data.show_object_viewport_light'}, '0-40186'), (_msg('Shift+C'), _msg('Hide Cameras Toggle'), 'wm.context_toggle', 'C', {'shift': True}, {'data_path': 'space_data.show_object_viewport_camera'}, '0-40185'), (_msg('Shift+H'), _msg('Hide Helpers Toggle'), 'wm.context_toggle', 'H', {'shift': True}, {'data_path': 'space_data.show_object_viewport_empty'}, '0-40187'), (_msg('Ctrl+F'), _msg('Cycle Selection Method'), 'bsm.max_command', 'F', {'ctrl': True}, C('SELECTION_METHOD_CYCLE'), '0-325'), (_msg('Ctrl+L'), _msg('Illuminate with Default / Scene Lights'), 'wm.context_toggle', 'L', {'ctrl': True}, {'data_path': 'space_data.shading.use_scene_lights'}, '0-299'), ('\\', _msg('Sound Toggle'), 'wm.context_toggle', 'BACK_SLASH', {}, {'data_path': 'scene.use_audio'}, '0-40204'), ('`', _msg('Redraw All Views'), 'bsm.max_command', 'ACCENT_GRAVE', {}, C('REDRAW_ALL'), '0-40130'), (_msg('Ctrl+B'), _msg('Sub-object Selection Toggle'), 'bsm.max_command', 'B', {'ctrl': True}, C('SUBOBJECT_TOGGLE'), '0-40205'), (_msg('Alt+Home'), _msg('Home View'), 'bsm.max_command', 'HOME', {'alt': True}, C('VIEWCUBE_HOME'), '0-40885'), (_msg('Alt+J'), _msg('Selection/Preview Highlights Toggle'), 'wm.context_toggle', 'J', {'alt': True}, {'data_path': 'space_data.overlay.show_outline_selected'}, '0-470'), (_msg('Shift+F'), _msg('Viewport Safeframes Toggle'), 'bsm.max_command', 'F', {'shift': True}, C('SAFE_FRAMES'), '0-219'), (_msg('Ctrl+U'), _msg('Group Attach'), 'bsm.max_command', 'U', {'ctrl': True}, C('GROUP_ATTACH'), '0-40146'), ('I', _msg('Pan Viewport'), 'view3d.view_center_pick', 'I', {}, {}, '0-322'), (_msg('Ctrl+Alt+Q'), _msg('Isolate Selection Toggle'), 'bsm.max_command', 'Q', {'ctrl': True, 'alt': True}, C('ISOLATE'), '0-268'), (_msg('Shift+Page Down'), _msg('Select Children'), 'object.select_grouped', 'PAGE_DOWN', {'shift': True}, {'extend': True, 'type': 'CHILDREN_RECURSIVE'}, '0-40180'), (_msg('Ctrl+Alt+Shift+X'), _msg('Keyboard Shortcut Override Toggle'), 'wm.context_toggle', 'X', {'ctrl': True, 'alt': True, 'shift': True}, {'data_path': 'window_manager.bsm.keyboard_override'}, '0-30761'), (_msg('Ctrl+Alt+Shift+Z'), _msg('Zoom Out 2X'), 'bsm.max_command', 'Z', {'ctrl': True, 'alt': True, 'shift': True}, C('ZOOM_OUT_2X'), '0-297'), (_msg('Alt+Shift+5'), _msg('Center Point Cycle'), 'bsm.max_command', 'FIVE', {'alt': True, 'shift': True}, C('CENTER_POINT_CYCLE'), '0-40235'), (_msg('Alt+`'), _msg('Show End Result'), 'bsm.max_command', 'ACCENT_GRAVE', {'alt': True}, C('SHOW_END_RESULT'), _msg('647394-Show_End_Result_Toggle`Modifier Stack')), (_msg('Ctrl+C'), _msg('Create Physical Camera From View'), 'bsm.max_command', 'C', {'ctrl': True}, C('CAMERA_FROM_VIEW'), _msg('647394-PhysicalCamera_CreateFromView`Lights and Cameras')), (_msg('Alt+Shift+C'), _msg('Create Physical Camera From View'), 'bsm.max_command', 'C', {'alt': True, 'shift': True}, C('CAMERA_FROM_VIEW'), _msg('647394-PhysicalCamera_CreateFromView`Lights and Cameras')), (_msg('Ctrl+Alt+Shift+C'), _msg('Create Standard Camera From View'), 'bsm.max_command', 'C', {'ctrl': True, 'alt': True, 'shift': True}, C('CAMERA_FROM_VIEW'), _msg('647394-StandardCamera_CreateFromView`Lights and Cameras')), (_msg('Up'), _msg('WalkThrough View Mode'), 'view3d.walk', 'UP_ARROW', {}, {}, '647394-WalkThroughToggle`Views'), (_msg('Space'), _msg('Selection Lock Toggle'), 'bsm.select_lock', 'SPACE', {}, {}, '1261319018-30882'), ('V', _msg('Viewports quad (views)'), 'wm.call_menu', 'V', {}, {'name': 'VIEWPORTS_MENU'}, '1261319018-17219'))
MESH_EQUIVALENT = {'object.select_all': 'mesh.select_all', 'object.hide_view_set': 'mesh.hide', 'object.select_hierarchy': None, 'object.select_grouped': None}
MESH_TABLE = ((_msg('Alt+L'), _msg('Select Sub-object Loop'), 'mesh.loop_multi_select', 'L', {'alt': True}, {'ring': False}, _msg('647394-EPoly_Select_Loop`Editable Polygon Object')), (_msg('Alt+R'), _msg('Select Sub-object Ring'), 'mesh.loop_multi_select', 'R', {'alt': True}, {'ring': True}, _msg('647394-EPoly_Select_Ring`Editable Polygon Object')), (_msg('Ctrl+Up'), _msg('Grow Selection'), 'mesh.select_more', 'UP_ARROW', {'ctrl': True}, {}, '369982487-40037'), (_msg('Ctrl+Page Up'), _msg('Grow Selection'), 'mesh.select_more', 'PAGE_UP', {'ctrl': True}, {}, '369982487-40037'), (_msg('Ctrl+Down'), _msg('Shrink Selection'), 'mesh.select_less', 'DOWN_ARROW', {'ctrl': True}, {}, '369982487-40040'), (_msg('Ctrl+Page Down'), _msg('Shrink Selection'), 'mesh.select_less', 'PAGE_DOWN', {'ctrl': True}, {}, '369982487-40040'), (_msg('Shift+E'), _msg('Extrude Mode'), 'view3d.edit_mesh_extrude_move_normal', 'E', {'shift': True}, {}, '369982487-40017'), (_msg('Alt+Shift+E'), _msg('Extrude Face'), 'view3d.edit_mesh_extrude_move_normal', 'E', {'alt': True, 'shift': True}, {}, _msg('647394-EPoly_FExtrude`Editable Polygon Object')), (_msg('Ctrl+Shift+B'), _msg('Bevel Mode'), 'mesh.inset', 'B', {'ctrl': True, 'shift': True}, {}, '369982487-40013'), (_msg('Ctrl+Shift+C'), _msg('Chamfer Mode'), 'bsm.max_command', 'C', {'ctrl': True, 'shift': True}, C('POLY_CHAMFER'), '369982487-40055'), (_msg('Ctrl+Shift+E'), _msg('Connect'), 'bsm.max_command', 'E', {'ctrl': True, 'shift': True}, C('POLY_CONNECT'), '369982487-40061'), (_msg('Shift+R'), _msg('Break'), 'mesh.edge_split', 'R', {'shift': True}, {'type': 'VERT'}, '369982487-40011'), (_msg('Alt+P'), _msg('Cap'), 'mesh.edge_face_add', 'P', {'alt': True}, {}, '369982487-40060'), (_msg('Ctrl+Alt+C'), _msg('Collapse'), 'mesh.merge', 'C', {'ctrl': True, 'alt': True}, {'type': 'COLLAPSE'}, '369982487-40024'), (_msg('Alt+C'), _msg('Cut'), 'mesh.knife_tool', 'C', {'alt': True}, {}, '369982487-40015'), (_msg('Ctrl+Alt+D'), _msg('Detach'), 'mesh.separate', 'D', {'ctrl': True, 'alt': True}, {'type': 'SELECTED'}, '369982487-40031'), (_msg('Ctrl+M'), _msg('MeshSmooth'), 'mesh.subdivide', 'M', {'ctrl': True}, {'smoothness': 1.0}, '369982487-40048'), (_msg('Alt+M'), _msg('Make Planar'), 'mesh.face_make_planar', 'M', {'alt': True}, {}, '1250838234-40046'), (_msg('Ctrl+Shift+Q'), _msg('Quickslice Mode'), 'mesh.bisect', 'Q', {'ctrl': True, 'shift': True}, {}, '369982487-40044'), (_msg('Ctrl+Shift+W'), _msg('Target Weld Mode'), 'mesh.merge', 'W', {'ctrl': True, 'shift': True}, {'type': 'LAST'}, '369982487-40038'), (_msg('Shift+B'), _msg('Use Soft Selection'), 'wm.context_toggle', 'B', {'shift': True}, {'data_path': 'tool_settings.use_proportional_edit'}, '369982487-40029'), (';', _msg('Repeat Last Operation'), 'screen.repeat_last', 'SEMI_COLON', {}, {}, '369982487-40052'), (_msg('Alt+H'), _msg('Hide'), 'mesh.hide', 'H', {'alt': True}, {'unselected': False}, '369982487-40021'), (_msg('Alt+U'), _msg('Unhide All'), 'mesh.reveal', 'U', {'alt': True}, {}, '369982487-40033'), (_msg('Alt+Shift+X'), _msg('Ignore Backfacing in Selections'), 'bsm.max_command', 'X', {'alt': True, 'shift': True}, C('IGNORE_BACKFACING'), '369982487-40012'), (_msg('Alt+1'), _msg('Swift Loop'), 'mesh.loopcut_slide', 'ONE', {'alt': True}, {}, '647394-SwiftLoop`PolyTools'), (_msg('Alt+5'), _msg('Spin Edge'), 'mesh.edge_rotate', 'FIVE', {'alt': True}, {}, '647394-SpinEdge`PolyTools'))
NOT_KEYS = {'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE', 'BUTTON4MOUSE', 'BUTTON5MOUSE', 'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE', 'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_ALT', 'RIGHT_ALT', 'LEFT_SHIFT', 'RIGHT_SHIFT', 'OSKEY', 'TIMER', 'TIMER0', 'TIMER1', 'TIMER2', 'TEXTINPUT', 'WINDOW_DEACTIVATE', 'NONE'}

def binding(event, mode):
    """The operator and properties a key press runs in the viewport keymaps, or None."""
    if event.value != 'PRESS' or event.type in NOT_KEYS:
        return None
    rows = (MESH_TABLE if mode == 'EDIT_MESH' else ()) + KEY_TABLE
    for (_, _, operator, key, modifiers, properties, _) in rows:
        if key != event.type or any((getattr(event, m) != modifiers.get(m, False) for m in ('ctrl', 'alt', 'shift'))):
            continue
        if mode == 'EDIT_MESH' and operator in MESH_EQUIVALENT:
            equivalent = MESH_EQUIVALENT[operator]
            if equivalent is None:
                continue
            properties = {'unselected': True} if equivalent == 'mesh.hide' else properties
            operator = equivalent
        if operator == 'wm.call_menu' and properties.get('name') == 'VIEWPORTS_MENU':
            from .max_menus import LABEL_MENUS
            properties = dict(properties, name=LABEL_MENUS['POV'])
        from .compat import operator_binding
        return operator_binding(operator, properties)
    return None

def run_anywhere(context, event):
    """Max's main-window keys work wherever the mouse is, not only over a viewport: over
    the toolbar, Command Panel, Scene Explorer, time controls or an editor window, run the
    key's viewport binding on the active viewport. Returns True when a key ran."""
    from .operators import viewport_override
    state = getattr(context.window_manager, 'bsm', None)
    if state is not None and (not state.keyboard_override):
        found = binding(event, context.mode)
        if not found or found[1].get('data_path') != OVERRIDE_TOGGLE:
            return False
    found = binding(event, context.mode)
    if found is None:
        return False
    (operator, properties) = found
    (module, name) = operator.split('.')
    op = getattr(getattr(bpy.ops, module), name)
    try:
        override = viewport_override(context)
    except RuntimeError:
        return False
    with context.temp_override(**override):
        if not op.poll():
            return False
        try:
            op('INVOKE_DEFAULT', **properties)
        except RuntimeError as error:
            print(_msg('Blender Max:'), operator, str(error).split('\n')[0])
    return True

def match(table, event):
    """The row of an editor key table (shortcut, label, key, modifiers, command, action id)
    that a key press matches, or None. Modifiers must match exactly, as in Max."""
    if event.value != 'PRESS':
        return None
    for row in table:
        (key, modifiers) = (row[2], row[3])
        if event.type == key and all((getattr(event, m) == modifiers.get(m, False) for m in ('ctrl', 'alt', 'shift'))):
            return row
    return None
_owned_items = []
_owned_maps = []
OVERRIDE_TOGGLE = 'window_manager.bsm.keyboard_override'


def _new_map(config, **kwargs):
    existing = config.keymaps.find(kwargs['name'], space_type=kwargs.get('space_type', 'EMPTY'),
                                   region_type=kwargs.get('region_type', 'WINDOW'))
    km = config.keymaps.new(**kwargs)
    if existing is None:
        _owned_maps.append((config, km))
    return km

def _add(keymap, operator, event, properties=None, value='PRESS', **modifiers):
    from .compat import operator_binding
    (operator, properties) = operator_binding(operator, properties)
    item = keymap.keymap_items.new(operator, event, value, head=True, **modifiers)
    _owned_items.append((keymap, item))
    for (name, prop_value) in (properties or {}).items():
        if operator == 'wm.call_menu' and prop_value == 'VIEWPORTS_MENU':
            from .max_menus import LABEL_MENUS
            prop_value = LABEL_MENUS['POV']
        setattr(item.properties, name, prop_value)
    return item

def register_mode():
    """Activate viewport bindings once; safe in background Blender as well."""
    if _owned_items:
        return
    config = bpy.context.window_manager.keyconfigs.addon
    if config is None:
        return
    try:
        viewport = _new_map(config, name=_msg('3D View'), space_type='VIEW_3D', region_type='WINDOW')
        objects = _new_map(config, name=_msg('Object Mode'), space_type='EMPTY', region_type='WINDOW')
        mesh = _new_map(config, name=_msg('Mesh'), space_type='EMPTY', region_type='WINDOW')
        for (_, _, operator, event, modifiers, properties, _) in KEY_TABLE:
            if operator in MESH_EQUIVALENT:
                _add(objects, operator, event, properties, **modifiers)
                equivalent = MESH_EQUIVALENT[operator]
                if equivalent:
                    values = {'unselected': True} if equivalent == 'mesh.hide' else properties
                    _add(mesh, equivalent, event, values, **modifiers)
                continue
            for target in (objects, mesh):
                _add(target, operator, event, properties, **modifiers)
        for (_, _, operator, event, modifiers, properties, _) in KEY_TABLE:
            if operator not in MESH_EQUIVALENT:
                _add(viewport, operator, event, properties, **modifiers)
        for (_, _, operator, event, modifiers, properties, _) in MESH_TABLE:
            _add(mesh, operator, event, properties, **modifiers)
        _add(viewport, 'view3d.move', 'MIDDLEMOUSE')
        _add(viewport, 'view3d.rotate', 'MIDDLEMOUSE', alt=True)
        _add(viewport, 'view3d.zoom', 'MIDDLEMOUSE', ctrl=True, alt=True)
        _add(viewport, 'view3d.zoom', 'WHEELUPMOUSE', {'delta': 1})
        _add(viewport, 'view3d.zoom', 'WHEELDOWNMOUSE', {'delta': -1})
        for target in (objects, mesh, viewport):
            _add(target, 'bsm.quad_menu', 'RIGHTMOUSE')
        for name in (_msg('Curve'), _msg('Armature'), _msg('Pose'), _msg('Lattice'), _msg('Font')):
            _add(_new_map(config, name=name, space_type='EMPTY', region_type='WINDOW'), 'bsm.quad_menu', 'RIGHTMOUSE')
    except Exception:
        unregister_mode()
        raise

def set_enabled(on):
    """Keyboard Shortcut Override Toggle: off falls back to Blender's own keys."""
    for (_, item) in _owned_items:
        try:
            toggle = item.idname == 'wm.context_toggle' and item.properties.data_path == OVERRIDE_TOGGLE
            if item.type not in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'RIGHTMOUSE'} and (not toggle):
                item.active = on
        except ReferenceError:
            pass

def unregister_mode():
    """Remove exactly the entries created by register_mode, preserving others."""
    while _owned_items:
        (keymap, item) = _owned_items.pop()
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, RuntimeError):
            pass
    while _owned_maps:
        config, km = _owned_maps.pop()
        try:
            if not km.keymap_items:
                config.keymaps.remove(km)
        except (ReferenceError, RuntimeError):
            pass
