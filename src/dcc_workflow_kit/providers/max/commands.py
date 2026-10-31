# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format, error_text as _dcc_ui_error
'3ds Max command vocabulary mapped onto Blender data and operators.\n\nEvery menu, quad and toolbar entry that has no single Blender operator goes\nthrough ``bsm.max_command``. Commands without a Blender equivalent are listed\nin ``UNAVAILABLE`` so menus can draw them disabled instead of pretending.\n'
import math
import os
import tempfile
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty
from bpy_extras import view3d_utils
from bpy_extras.io_utils import ImportHelper
from mathutils import Euler, Matrix, Quaternion, Vector
from . import runtime
from .operators import Active, viewport_override
HOLD_PATH = os.path.join(tempfile.gettempdir(), 'bsm_maxhold.blend')
UNAVAILABLE = {'SHOW_GHOSTING', 'SHOW_KEY_TIMES', 'TRANSFORM_TOOLBOX'}
_view_history = {}
_view_redo = {}
_saved_views = {}

def _view(context):
    override = viewport_override(context)
    area = override['area']
    return (override, area, area.spaces.active, area.spaces.active.region_3d)

def _view_state(r3d):
    return (r3d.view_location.copy(), r3d.view_rotation.copy(), r3d.view_distance, r3d.view_perspective)

def record_view(context, area=None):
    """Remember the current view so Undo View Change (Shift+Z) can restore it."""
    try:
        area = area or _view(context)[1]
    except RuntimeError:
        return
    state = _view_state(area.spaces.active.region_3d)
    history = _view_history.setdefault(area.as_pointer(), [])
    if not history or history[-1] != state:
        history.append(state)
        del history[:-50]
        _view_redo.pop(area.as_pointer(), None)

def _apply_view(r3d, state):
    (r3d.view_location, r3d.view_rotation, r3d.view_distance, r3d.view_perspective) = state

def selected(context):
    return [o for o in context.view_layer.objects if o.select_get()]

def world_bounds(obj):
    points = [obj.matrix_world @ Vector(c) for c in obj.bound_box] if obj.type in {'MESH', 'CURVE', 'FONT', 'SURFACE', 'META', 'LATTICE', 'VOLUME', 'POINTCLOUD', 'CURVES'} else [obj.matrix_world.translation.copy()]
    low = Vector(tuple((min((p[i] for p in points)) for i in range(3))))
    high = Vector(tuple((max((p[i] for p in points)) for i in range(3))))
    return (low, high)

def selection_bounds(objects):
    bounds = [world_bounds(o) for o in objects]
    low = Vector(tuple((min((b[0][i] for b in bounds)) for i in range(3))))
    high = Vector(tuple((max((b[1][i] for b in bounds)) for i in range(3))))
    return (low, high)

def unique_name(base):
    index = 1
    while f'{base}{index:03d}' in bpy.data.objects:
        index += 1
    return f'{base}{index:03d}'

def _link(context, obj):
    (context.collection or context.scene.collection).objects.link(obj)

def _parent_keep(child, parent):
    world = child.matrix_world.copy()
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted() if parent else Matrix()
    child.matrix_world = world

def group_head(obj):
    while obj is not None:
        if obj.get('bsm_group'):
            return obj
        obj = obj.parent
    return None

def closed_group(obj):
    """Top-most closed group containing ``obj`` (members of open groups select alone)."""
    top = None
    node = obj.parent
    while node is not None:
        if node.get('bsm_group') and (not node.get('bsm_group_open')):
            top = node
        node = node.parent
    return top

def promote_groups(context):
    for obj in selected(context):
        head = closed_group(obj)
        if head is None:
            continue
        head.select_set(True)
        for child in head.children_recursive:
            child.select_set(True)
        if context.view_layer.objects.active in head.children_recursive:
            context.view_layer.objects.active = head

def _make_group(context, name):
    objects = [o for o in selected(context) if o.parent not in selected(context)]
    if not objects:
        return None
    (low, high) = selection_bounds(objects)
    head = bpy.data.objects.new(name, None)
    head.empty_display_type = 'CUBE'
    head.empty_display_size = max(0.001, max(high - low) / 2)
    head.location = (low + high) / 2
    head['bsm_group'] = True
    head['bsm_group_open'] = False
    _link(context, head)
    context.view_layer.update()
    for obj in objects:
        _parent_keep(obj, head)
    for obj in context.view_layer.objects:
        obj.select_set(False)
    head.select_set(True)
    context.view_layer.objects.active = head
    promote_groups(context)
    return head

def _ungroup(context, recursive=False):
    heads = {group_head(o) for o in selected(context)} - {None}
    while heads:
        head = heads.pop()
        for child in list(head.children):
            _parent_keep(child, head.parent)
            if recursive and child.get('bsm_group'):
                heads.add(child)
        bpy.data.objects.remove(head, do_unlink=True)
FREEZE_GRAY = (0.47, 0.47, 0.47, 1.0)

def freeze(obj, state=True):
    if state and (not obj.get('_bsm_frozen')):
        obj['_bsm_frozen'] = tuple(obj.color)
        obj.color = FREEZE_GRAY
        obj.hide_select = True
    elif not state and obj.get('_bsm_frozen') is not None:
        obj.color = tuple(obj['_bsm_frozen'])
        del obj['_bsm_frozen']
        obj.hide_select = False
    elif not state:
        obj.hide_select = False

def is_frozen(obj):
    return obj.hide_select

def _mesh_level(context):
    return {1: 'VERT', 2: 'EDGE', 3: 'EDGE', 4: 'FACE', 5: 'FACE'}.get(context.window_manager.bsm.component, 'VERT')

def _floating(context, space_type, name, setup=None):
    from . import editor_host
    return editor_host.open_native(context, space_type, name, setup)

def _preferences(context, section):
    context.preferences.active_section = section
    bpy.ops.screen.userpref_show('INVOKE_DEFAULT')

def _toggle(owner, attr):
    setattr(owner, attr, not getattr(owner, attr))

def _home_rotation():
    return Euler((math.radians(64), 0, math.radians(315)), 'XYZ').to_quaternion()

def run(context, command):
    """Execute one Max command; returns an operator result set."""
    wm = context.window_manager
    state = wm.bsm
    ts = context.scene.tool_settings
    if command in UNAVAILABLE:
        raise RuntimeError(_msg('Not available in Blender'))
    if command == 'HOLD':
        bpy.ops.wm.save_as_mainfile(filepath=HOLD_PATH, copy=True, check_existing=False)
        return {'FINISHED'}
    if command == 'FETCH':
        if not os.path.isfile(HOLD_PATH):
            raise RuntimeError(_msg('No Hold buffer to fetch'))
        bpy.ops.wm.open_mainfile(filepath=HOLD_PATH)
        return {'FINISHED'}
    if command == 'DELETE':
        if context.mode == 'EDIT_MESH':
            with context.temp_override(**viewport_override(context)):
                bpy.ops.mesh.delete(type=_mesh_level(context))
        else:
            with context.temp_override(**viewport_override(context)):
                bpy.ops.object.delete(use_global=False)
        return {'FINISHED'}
    if command == 'SELECT_SIMILAR':
        with context.temp_override(**viewport_override(context)):
            if context.mode == 'EDIT_MESH':
                bpy.ops.mesh.select_similar('INVOKE_DEFAULT')
            else:
                bpy.ops.object.select_grouped(extend=True, type='TYPE')
        return {'FINISHED'}
    if command == 'SELECT_INSTANCES':
        with context.temp_override(**viewport_override(context)):
            bpy.ops.object.select_linked(extend=True, type='OBDATA')
        return {'FINISHED'}
    if command == 'SELECT_BY_COLOR':
        active = context.view_layer.objects.active
        if active:
            for obj in context.view_layer.objects:
                if not obj.hide_select and all((abs(a - b) < 0.001 for (a, b) in zip(obj.color, active.color))):
                    obj.select_set(True)
        return {'FINISHED'}
    if command == 'SELECT_BY_LAYER':
        with context.temp_override(**viewport_override(context)):
            bpy.ops.object.select_grouped(extend=True, type='COLLECTION')
        return {'FINISHED'}
    if command == 'SELECT_BY_NAME':
        return bpy.ops.bsm.select_from_scene('INVOKE_DEFAULT')
    if command.startswith('SELECT_REGION_'):
        state.region_type = command[len('SELECT_REGION_'):]
        return {'FINISHED'}
    if command in {'SELECT_WINDOW', 'SELECT_CROSSING'}:
        state.window_selection = command == 'SELECT_WINDOW'
        return {'FINISHED'}
    if command == 'MANAGE_SELECTION_SETS':
        return bpy.ops.bsm.manage_sets('INVOKE_DEFAULT')
    if command == 'OBJECT_PROPERTIES':
        return bpy.ops.bsm.object_properties('INVOKE_DEFAULT')
    if command == 'TRANSFORM_TYPEIN':
        return bpy.ops.bsm.transform_typein('INVOKE_DEFAULT')
    if command == 'PLACEMENT':
        return bpy.ops.bsm.place_surface('INVOKE_DEFAULT')
    if command in {'ISOLATE', 'END_ISOLATE', 'ZOOM_EXTENTS_ISOLATE'}:
        (override, area, space, r3d) = _view(context)
        local = space.local_view is not None
        with context.temp_override(**override):
            if command == 'ISOLATE' and (not local):
                bpy.ops.view3d.localview(frame_selected=True)
            elif command == 'END_ISOLATE' and local:
                bpy.ops.view3d.localview(frame_selected=False)
            elif command == 'ZOOM_EXTENTS_ISOLATE' and local:
                bpy.ops.view3d.view_all(center=False)
        return {'FINISHED'}
    if command == 'MIRROR':
        return bpy.ops.bsm.mirror('INVOKE_DEFAULT')
    if command == 'ARRAY':
        return bpy.ops.bsm.array('INVOKE_DEFAULT')
    if command == 'ALIGN':
        return bpy.ops.bsm.pick_object('INVOKE_DEFAULT', purpose='ALIGN')
    if command == 'QUICK_ALIGN':
        with context.temp_override(**viewport_override(context)):
            bpy.ops.view3d.snap_selected_to_active()
        return {'FINISHED'}
    if command == 'ALIGN_TO_VIEW':
        (override, area, space, r3d) = _view(context)
        rotation = r3d.view_rotation.to_matrix().to_4x4()
        for obj in selected(context):
            translation = obj.matrix_world.translation.copy()
            scale = obj.matrix_world.to_scale()
            obj.matrix_world = Matrix.Translation(translation) @ rotation @ Matrix.Diagonal((*scale, 1))
        return {'FINISHED'}
    if command == 'SNAPSHOT':
        with context.temp_override(**viewport_override(context)):
            bpy.ops.object.convert(target='MESH', keep_original=True)
        return {'FINISHED'}
    if command == 'RENAME_OBJECTS':
        return bpy.ops.bsm.rename_objects('INVOKE_DEFAULT')
    if command == 'MEASURE_DISTANCE':
        with context.temp_override(**viewport_override(context)):
            return bpy.ops.bsm.measure_distance('INVOKE_DEFAULT')
    if command == 'LIGHT_LISTER':
        return bpy.ops.bsm.settings_popup('INVOKE_DEFAULT', kind='LIGHTS')
    if command == 'GRID_SNAP_SETTINGS':
        return bpy.ops.bsm.settings_popup('INVOKE_DEFAULT', kind='SNAPS')
    if command == 'SHOW_HOME_GRID':
        _toggle(state, 'finite_grid')
        return {'FINISHED'}
    if command == 'SNAPS_TOGGLE':
        _toggle(ts, 'use_snap')
        return {'FINISHED'}
    if command == 'ANGLE_SNAP':
        _toggle(ts, 'use_snap_rotate')
        return {'FINISHED'}
    if command == 'PERCENT_SNAP':
        _toggle(ts, 'use_snap_scale')
        return {'FINISHED'}
    if command in {'PREVIEW_ANIMATION', 'CAPTURE_STILL'}:
        with context.temp_override(**viewport_override(context)):
            bpy.ops.render.opengl('INVOKE_DEFAULT', animation=command == 'PREVIEW_ANIMATION')
        if command == 'CAPTURE_STILL':
            bpy.ops.render.view_show('INVOKE_DEFAULT')
        return {'FINISHED'}
    if command == 'PLAY_PREVIEW':
        return bpy.ops.render.play_rendered_anim()
    if command == 'GROUP':
        return bpy.ops.bsm.group('INVOKE_DEFAULT')
    if command in {'UNGROUP', 'GROUP_EXPLODE'}:
        _ungroup(context, recursive=command == 'GROUP_EXPLODE')
        return {'FINISHED'}
    if command in {'GROUP_OPEN', 'GROUP_OPEN_RECURSIVE', 'GROUP_CLOSE'}:
        heads = {group_head(o) for o in selected(context)} - {None}
        for head in list(heads):
            stack = [head]
            while stack:
                node = stack.pop()
                if node.get('bsm_group'):
                    node['bsm_group_open'] = command != 'GROUP_CLOSE'
                if command == 'GROUP_OPEN_RECURSIVE':
                    stack.extend(node.children)
            if command == 'GROUP_CLOSE':
                head.select_set(True)
                context.view_layer.objects.active = head
        if command == 'GROUP_CLOSE':
            promote_groups(context)
        return {'FINISHED'}
    if command == 'GROUP_ATTACH':
        return bpy.ops.bsm.pick_object('INVOKE_DEFAULT', purpose='GROUP_ATTACH')
    if command == 'GROUP_DETACH':
        for obj in selected(context):
            head = group_head(obj.parent) if obj.parent else None
            if head and (not obj.get('bsm_group')):
                _parent_keep(obj, head.parent)
        return {'FINISHED'}
    if command in {'UNDO_VIEW', 'REDO_VIEW'}:
        (override, area, space, r3d) = _view(context)
        key = area.as_pointer()
        (source, target) = (_view_history, _view_redo) if command == 'UNDO_VIEW' else (_view_redo, _view_history)
        stack = source.get(key) or []
        current = _view_state(r3d)
        while stack and stack[-1] == current:
            stack.pop()
        if stack:
            target.setdefault(key, []).append(current)
            _apply_view(r3d, stack.pop())
        return {'FINISHED'}
    if command == 'REDRAW_ALL':
        runtime.redraw()
        return {'FINISHED'}
    if command in {'GIZMO_X', 'GIZMO_Y', 'GIZMO_Z', 'GIZMO_PLANE_CYCLE'}:
        from . import max_gizmo
        max_gizmo.set_constraint('PLANE' if command == 'GIZMO_PLANE_CYCLE' else command[-1])
        runtime.redraw()
        return {'FINISHED'}
    if command in {'GIZMO_SIZE_DOWN', 'GIZMO_SIZE_UP'}:
        from . import max_gizmo
        max_gizmo.resize_gizmo(-1 if command == 'GIZMO_SIZE_DOWN' else 1)
        runtime.redraw()
        return {'FINISHED'}
    if command == 'SAVE_INCREMENTAL':
        if not bpy.data.filepath:
            return bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT')
        return bpy.ops.wm.save_mainfile(incremental=True)
    if command == 'LIGHT_VIEW':
        light = context.view_layer.objects.active
        if light is None or light.type != 'LIGHT' or light.data.type not in {'SPOT', 'SUN', 'AREA'}:
            raise RuntimeError(_msg('Select a spot or directional light'))
        (override, area, space, r3d) = _view(context)
        record_view(context, area)
        rotation = light.matrix_world.to_quaternion()
        r3d.view_perspective = 'PERSP'
        r3d.view_rotation = rotation
        r3d.view_location = light.matrix_world.translation + rotation @ Vector((0, 0, -r3d.view_distance))
        return {'FINISHED'}
    if command == 'SELECTION_METHOD_CYCLE':
        state.region_type = SELECTION_METHODS[(SELECTION_METHODS.index(state.region_type) + 1) % len(SELECTION_METHODS)]
        runtime.redraw()
        return {'FINISHED'}
    if command == 'SUBOBJECT_TOGGLE':
        obj = context.view_layer.objects.active
        if obj is None or obj.type not in {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'LATTICE', 'ARMATURE'}:
            raise RuntimeError(_msg('Select an object with sub-objects'))
        with context.temp_override(**viewport_override(context)):
            bpy.ops.object.mode_set(mode='OBJECT' if obj.mode == 'EDIT' else 'EDIT')
        return {'FINISHED'}
    if command == 'SAFE_FRAMES':
        camera = context.scene.camera
        if camera is None or camera.type != 'CAMERA':
            raise RuntimeError(_msg('Safe frames show in camera views: the scene has no camera'))
        _toggle(camera.data, 'show_safe_areas')
        return {'FINISHED'}
    if command == 'ZOOM_OUT_2X':
        (override, area, space, r3d) = _view(context)
        record_view(context, area)
        r3d.view_distance *= 2
        return {'FINISHED'}
    if command == 'CENTER_POINT_CYCLE':
        current = ts.transform_pivot_point
        index = CENTER_POINTS.index(current) if current in CENTER_POINTS else -1
        ts.transform_pivot_point = CENTER_POINTS[(index + 1) % len(CENTER_POINTS)]
        runtime.redraw()
        return {'FINISHED'}
    if command == 'SHOW_END_RESULT':
        obj = context.view_layer.objects.active
        if obj is None or not obj.modifiers:
            raise RuntimeError(_msg('The object has no modifiers'))
        show = not all((m.show_in_editmode for m in obj.modifiers))
        for modifier in obj.modifiers:
            modifier.show_in_editmode = show
        return {'FINISHED'}
    if command == 'IGNORE_BACKFACING':
        _toggle(_view(context)[2].shading, 'show_xray')
        return {'FINISHED'}
    if command in {'POLY_CHAMFER', 'POLY_CONNECT'}:
        if context.mode != 'EDIT_MESH':
            raise RuntimeError(_msg('Choose a sub-object level of an Editable Poly'))
        vertex = context.tool_settings.mesh_select_mode[0]
        with context.temp_override(**viewport_override(context)):
            if command == 'POLY_CHAMFER':
                return bpy.ops.mesh.bevel('INVOKE_DEFAULT', affect='VERTICES' if vertex else 'EDGES')
            if vertex:
                return bpy.ops.mesh.vert_connect_path()
            return bpy.ops.mesh.subdivide(number_cuts=1)
    if command == 'VIEWPORT_CONFIG':
        return bpy.ops.bsm.settings_popup('INVOKE_DEFAULT', kind='VIEWPORT')
    if command == 'CAMERA_FROM_VIEW':
        (override, area, space, r3d) = _view(context)
        record_view(context, area)
        data = bpy.data.cameras.new(unique_name(_msg('PhysCamera')))
        data.lens = space.lens
        obj = bpy.data.objects.new(data.name, data)
        _link(context, obj)
        obj.matrix_world = r3d.view_matrix.inverted()
        if r3d.view_perspective == 'ORTHO':
            data.type = 'ORTHO'
            data.ortho_scale = r3d.view_distance * 2
        context.scene.camera = obj
        r3d.view_perspective = 'CAMERA'
        return {'FINISHED'}
    if command in {'SHOW_STATS', 'XVIEW_STATS'}:
        space = _view(context)[2]
        _toggle(space.overlay, 'show_stats')
        return {'FINISHED'}
    if command == 'XVIEW_FACE_ORIENTATION':
        _toggle(_view(context)[2].overlay, 'show_face_orientation')
        return {'FINISHED'}
    if command == 'XVIEW_OPEN_EDGES':
        if context.mode != 'EDIT_MESH':
            raise RuntimeError(_msg('Open Edges: choose a sub-object level of an Editable Poly'))
        with context.temp_override(**viewport_override(context)):
            bpy.ops.mesh.select_mode(type='EDGE')
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.mesh.select_non_manifold(extend=False, use_wire=False, use_boundary=True, use_multi_face=False, use_non_contiguous=False, use_verts=False)
        return {'FINISHED'}
    if command == 'SHOW_GIZMO':
        _toggle(_view(context)[2], 'show_gizmo_tool')
        return {'FINISHED'}
    if command == 'SHADE_SELECTED':
        _toggle(state, 'shade_selected')
        theme = context.preferences.themes[0].view_3d
        theme.face_select = (*theme.face_select[:3], 0.45 if state.shade_selected else 0.18)
        return {'FINISHED'}
    if command == 'EXPERT_MODE':
        with context.temp_override(**viewport_override(context)):
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
        return {'FINISHED'}
    if command == 'VIEWCUBE_TOGGLE':
        _toggle(state, 'show_viewcube')
        runtime.redraw()
        return {'FINISHED'}
    if command == 'VIEWCUBE_HOME':
        (override, area, space, r3d) = _view(context)
        record_view(context, area)
        r3d.view_perspective = 'PERSP'
        r3d.view_rotation = _home_rotation()
        with context.temp_override(**override):
            bpy.ops.view3d.view_all(center=False)
        return {'FINISHED'}
    if command in {'BACKGROUND_GRADIENT', 'BACKGROUND_SOLID'}:
        gradients = context.preferences.themes[0].view_3d.space.gradients
        gradients.background_type = 'LINEAR' if command == 'BACKGROUND_GRADIENT' else 'SINGLE_COLOR'
        if command == 'BACKGROUND_GRADIENT':
            (gradients.gradient, gradients.high_gradient) = ((0.1, 0.1, 0.1), (0.3, 0.3, 0.3))
        else:
            gradients.high_gradient = (0.2196, 0.2196, 0.2196)
        runtime.redraw()
        return {'FINISHED'}
    if command in {'ACTIVE_VIEW_SAVE', 'ACTIVE_VIEW_RESTORE'}:
        (override, area, space, r3d) = _view(context)
        if command == 'ACTIVE_VIEW_SAVE':
            _saved_views[area.as_pointer()] = _view_state(r3d)
        elif area.as_pointer() in _saved_views:
            record_view(context, area)
            _apply_view(r3d, _saved_views[area.as_pointer()])
        return {'FINISHED'}
    if command == 'DELETE_SELECTED_ANIMATION':
        for obj in selected(context):
            obj.animation_data_clear()
        return {'FINISHED'}
    if command == 'RENDER':
        return bpy.ops.bsm.render_view()
    if command == 'RENDERED_FRAME_WINDOW':
        return bpy.ops.render.view_show('INVOKE_DEFAULT')
    if command in {'ENVIRONMENT', 'EXPOSURE', 'COLOR_MANAGEMENT', 'PRINT_SIZE', 'UNITS_SETUP', 'SUMMARY_INFO'}:
        return bpy.ops.bsm.settings_popup('INVOKE_DEFAULT', kind=command)
    if command in {'HOTKEY_EDITOR', 'CUSTOMIZE_UI', 'PREFERENCES', 'PLUGIN_MANAGER', 'CONFIGURE_PATHS'}:
        _preferences(context, {'HOTKEY_EDITOR': 'KEYMAP', 'CUSTOMIZE_UI': 'INTERFACE', 'PREFERENCES': 'INTERFACE', 'PLUGIN_MANAGER': 'ADDONS', 'CONFIGURE_PATHS': 'FILE_PATHS'}[command])
        return {'FINISHED'}
    if command in {'NEW_SCRIPT', 'SCRIPT_EDITOR'}:

        def setup(space):
            if command == 'NEW_SCRIPT' or space.text is None:
                space.text = bpy.data.texts.new(_msg('Script'))
        return _floating(context, 'TEXT_EDITOR', _msg('MAXScript Editor'), setup)
    if command == 'OPEN_SCRIPT':
        return _floating(context, 'TEXT_EDITOR', _msg('MAXScript Editor'), lambda space: 'OPEN')
    if command == 'RUN_SCRIPT':
        return bpy.ops.bsm.run_script('INVOKE_DEFAULT')
    if command == 'LISTENER':
        return _floating(context, 'CONSOLE', _msg('Scripting Listener'))
    if command == 'MACRO_RECORDER':
        return _floating(context, 'INFO', _msg('Macro Recorder'))
    if command == 'PYTHON_HELP':
        return bpy.ops.wm.url_open(url='https://docs.blender.org/api/current/')
    if command == 'SEARCH_COMMANDS':
        return bpy.ops.wm.search_menu('INVOKE_DEFAULT')
    if command in {'SCHEMATIC_VIEW', 'LAYER_EXPLORER'}:

        def setup(space):
            space.display_mode = 'VIEW_LAYER'
        return _floating(context, 'OUTLINER', _msg('Schematic View') if command == 'SCHEMATIC_VIEW' else _msg('Layer Explorer'), setup)
    if command == 'MATERIAL_EXPLORER':

        def setup(space):
            space.display_mode = 'BLENDER_FILE'
        return _floating(context, 'OUTLINER', _msg('Material Explorer'), setup)
    if command == 'MOTION_MIXER':
        return _floating(context, 'NLA_EDITOR', _msg('Motion Mixer'))
    if command == 'SCENE_EXPLORER':
        return bpy.ops.bsm.editor(kind='SCENE')
    raise RuntimeError(_dcc_format('Unknown command {0}', command))
COMMAND_ITEMS = tuple(((c, c.replace('_', ' ').title(), '') for c in ('HOLD', 'FETCH', 'DELETE', 'SELECT_SIMILAR', 'SELECT_INSTANCES', 'SELECT_BY_COLOR', 'SELECT_BY_NAME', 'SELECT_BY_LAYER', 'SELECT_REGION_RECT', 'SELECT_REGION_CIRCLE', 'SELECT_REGION_FENCE', 'SELECT_REGION_LASSO', 'SELECT_REGION_PAINT', 'SELECT_WINDOW', 'SELECT_CROSSING', 'MANAGE_SELECTION_SETS', 'OBJECT_PROPERTIES', 'TRANSFORM_TYPEIN', 'TRANSFORM_TOOLBOX', 'PLACEMENT', 'ISOLATE', 'END_ISOLATE', 'ZOOM_EXTENTS_ISOLATE', 'MIRROR', 'ARRAY', 'ALIGN', 'QUICK_ALIGN', 'ALIGN_TO_VIEW', 'SNAPSHOT', 'RENAME_OBJECTS', 'MEASURE_DISTANCE', 'LIGHT_LISTER', 'GRID_SNAP_SETTINGS', 'SHOW_HOME_GRID', 'SNAPS_TOGGLE', 'ANGLE_SNAP', 'PERCENT_SNAP', 'PREVIEW_ANIMATION', 'CAPTURE_STILL', 'PLAY_PREVIEW', 'GROUP', 'UNGROUP', 'GROUP_OPEN', 'GROUP_OPEN_RECURSIVE', 'GROUP_CLOSE', 'GROUP_ATTACH', 'GROUP_DETACH', 'GROUP_EXPLODE', 'UNDO_VIEW', 'REDO_VIEW', 'REDRAW_ALL', 'VIEWPORT_CONFIG', 'CAMERA_FROM_VIEW', 'SHOW_STATS', 'SHOW_GIZMO', 'SHADE_SELECTED', 'SHOW_GHOSTING', 'SHOW_KEY_TIMES', 'EXPERT_MODE', 'VIEWCUBE_TOGGLE', 'VIEWCUBE_HOME', 'BACKGROUND_GRADIENT', 'BACKGROUND_SOLID', 'ACTIVE_VIEW_SAVE', 'ACTIVE_VIEW_RESTORE', 'XVIEW_FACE_ORIENTATION', 'XVIEW_OPEN_EDGES', 'XVIEW_STATS', 'DELETE_SELECTED_ANIMATION', 'RENDER', 'RENDERED_FRAME_WINDOW', 'ENVIRONMENT', 'EXPOSURE', 'COLOR_MANAGEMENT', 'PRINT_SIZE', 'UNITS_SETUP', 'HOTKEY_EDITOR', 'CUSTOMIZE_UI', 'PREFERENCES', 'PLUGIN_MANAGER', 'CONFIGURE_PATHS', 'NEW_SCRIPT', 'OPEN_SCRIPT', 'RUN_SCRIPT', 'SCRIPT_EDITOR', 'LISTENER', 'MACRO_RECORDER', 'PYTHON_HELP', 'SUMMARY_INFO', 'SEARCH_COMMANDS', 'SCHEMATIC_VIEW', 'MOTION_MIXER', 'SCENE_EXPLORER', 'LAYER_EXPLORER', 'MATERIAL_EXPLORER', 'GIZMO_X', 'GIZMO_Y', 'GIZMO_Z', 'GIZMO_PLANE_CYCLE', 'GIZMO_SIZE_DOWN', 'GIZMO_SIZE_UP', 'SAVE_INCREMENTAL', 'LIGHT_VIEW', 'SELECTION_METHOD_CYCLE', 'SUBOBJECT_TOGGLE', 'SAFE_FRAMES', 'ZOOM_OUT_2X', 'CENTER_POINT_CYCLE', 'SHOW_END_RESULT', 'IGNORE_BACKFACING', 'POLY_CHAMFER', 'POLY_CONNECT')))
NO_UNDO = {'RENDER', 'HOLD', 'FETCH', 'RENDERED_FRAME_WINDOW', 'UNDO_VIEW', 'REDO_VIEW', 'GIZMO_X', 'GIZMO_Y', 'GIZMO_Z', 'GIZMO_PLANE_CYCLE', 'GIZMO_SIZE_DOWN', 'GIZMO_SIZE_UP', 'SAVE_INCREMENTAL', 'LIGHT_VIEW', 'ZOOM_OUT_2X', 'SELECTION_METHOD_CYCLE', 'IGNORE_BACKFACING'}
SELECTION_METHODS = ('RECT', 'CIRCLE', 'FENCE', 'LASSO', 'PAINT')
CENTER_POINTS = ('INDIVIDUAL_ORIGINS', 'BOUNDING_BOX_CENTER', 'CURSOR')

class BSM_OT_max_command(Active, bpy.types.Operator):
    bl_idname = 'bsm.max_command'
    bl_label = _msg('3ds Max Command')
    bl_options = {'REGISTER'}
    command: EnumProperty(items=COMMAND_ITEMS, translation_context=_msg('DCCWorkflowKit.Max'))

    @classmethod
    def description(cls, context, properties):
        if properties.command in UNAVAILABLE:
            return _msg('Not available in Blender')
        return dict(((c, n) for (c, n, _) in COMMAND_ITEMS)).get(properties.command, '')

    def invoke(self, context, event):
        if self.command == 'FETCH':
            return context.window_manager.invoke_confirm(self, event, title=_msg('Fetch'), message=_msg('About to Fetch. OK?'))
        return self.execute(context)

    def execute(self, context):
        try:
            result = run(context, self.command)
        except RuntimeError as error:
            self.report({'WARNING'}, _dcc_ui_error(error))
            return {'CANCELLED'}
        result = result if isinstance(result, set) else {'FINISHED'}
        if 'FINISHED' in result and self.command not in NO_UNDO:
            bpy.ops.ed.undo_push(message=dict(((c, n) for (c, n, _) in COMMAND_ITEMS)).get(self.command, _msg('Max Command')))
        runtime.redraw()
        return result
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def _deform(method, attr=None):

    def setup(obj, mod):
        mod.deform_method = method
        if attr:
            setattr(mod, attr, 0)
    return ('SIMPLE_DEFORM', setup)

def _displace_noise(obj, mod):
    texture = bpy.data.textures.new(_msg('Noise'), 'CLOUDS')
    texture.noise_scale = 0.5
    mod.texture = texture
    mod.strength = 0.0

def _push(obj, mod):
    mod.direction = 'NORMAL'
    mod.mid_level = 0.0
    mod.strength = 0.0

def _ffd(points):

    def setup(obj, mod):
        (low, high) = world_bounds(obj)
        data = bpy.data.lattices.new('FFD')
        data.points_u = data.points_v = data.points_w = points
        lattice = bpy.data.objects.new(_dcc_format('FFD {0}x{1}x{2}', points, points, points), data)
        for collection in obj.users_collection:
            collection.objects.link(lattice)
        lattice.location = (low + high) / 2
        lattice.scale = tuple((max(0.001, v) for v in high - low))
        lattice.display_type = 'WIRE'
        bpy.context.view_layer.update()
        _parent_keep(lattice, obj)
        mod.object = lattice
    return ('LATTICE', setup)

def _uvw_map(obj, mod):
    gizmo = bpy.data.objects.new(_msg('UVW Mapping Gizmo'), None)
    gizmo.empty_display_type = 'PLAIN_AXES'
    for collection in obj.users_collection:
        collection.objects.link(gizmo)
    (low, high) = world_bounds(obj)
    gizmo.location = (low + high) / 2
    gizmo.scale = tuple((max(0.001, v / 2) for v in high - low))
    bpy.context.view_layer.update()
    _parent_keep(gizmo, obj)
    if not obj.data.uv_layers:
        obj.data.uv_layers.new(name=_msg('UVMap'))
    mod.projectors[0].object = gizmo

def _set(**values):

    def setup(obj, mod):
        for (key, value) in values.items():
            setattr(mod, key, value)
    return setup
MODIFIERS = {_msg('Bend'): _deform('BEND', 'angle'), _msg('Twist'): _deform('TWIST', 'angle'), _msg('Taper'): _deform('TAPER', 'factor'), _msg('Stretch'): _deform('STRETCH', 'factor'), _msg('Noise'): ('DISPLACE', _displace_noise), _msg('Noise Plus'): ('DISPLACE', _displace_noise), _msg('Displace'): ('DISPLACE', _set(strength=0.0)), _msg('Lattice'): ('WIREFRAME', _set(thickness=0.02, use_replace=False)), _msg('Mirror'): ('MIRROR', None), _msg('Symmetry'): ('MIRROR', _set(use_bisect_axis=(True, False, False), use_mirror_merge=True)), _msg('Shell'): ('SOLIDIFY', _set(thickness=0.1, offset=1.0)), _msg('Chamfer'): ('BEVEL', _set(width=0.1, segments=1, limit_method='NONE')), _msg('TurboSmooth'): ('SUBSURF', _set(levels=1, render_levels=1)), _msg('MeshSmooth'): ('SUBSURF', _set(levels=1, render_levels=1)), _msg('OpenSubdiv'): ('SUBSURF', _set(levels=1, render_levels=1)), _msg('Subdivide'): ('SUBSURF', _set(subdivision_type='SIMPLE', levels=1)), _msg('Tessellate'): ('SUBSURF', _set(subdivision_type='SIMPLE', levels=1)), _msg('Relax'): ('SMOOTH', _set(factor=0.5, iterations=1)), _msg('Push'): ('DISPLACE', _push), _msg('Spherify'): ('CAST', _set(cast_type='SPHERE', factor=1.0)), _msg('Wave'): ('WAVE', _set(use_normal=False)), _msg('Ripple'): ('WAVE', None), _msg('Optimize'): ('DECIMATE', _set(ratio=1.0)), _msg('ProOptimizer'): ('DECIMATE', _set(ratio=1.0)), _msg('Vertex Weld'): ('WELD', None), _msg('Weld'): ('WELD', None), _msg('Edit Normals'): ('NORMAL_EDIT', None), _msg('Weighted Normals'): ('WEIGHTED_NORMAL', None), _msg('Skin'): ('ARMATURE', None), _msg('Skin Wrap'): ('SURFACE_DEFORM', None), _msg('Surf Deform'): ('SURFACE_DEFORM', None), _msg('Path Deform'): ('CURVE', None), _msg('Path Deform (WSM)'): ('CURVE', None), _msg('FFD 2x2x2'): _ffd(2), _msg('FFD 3x3x3'): _ffd(3), _msg('FFD 4x4x4'): _ffd(4), _msg('FFD Box'): _ffd(4), _msg('FFD Cylinder'): _ffd(4), _msg('UVW Map'): ('UV_PROJECT', _uvw_map), _msg('Boolean'): ('BOOLEAN', None), _msg('ProBoolean'): ('BOOLEAN', None), _msg('Array'): ('ARRAY', None), _msg('Lathe'): ('SCREW', _set(steps=16, render_steps=16)), _msg('Turn To Mesh'): ('TRIANGULATE', None), _msg('Retopology'): ('REMESH', _set(mode='VOXEL')), _msg('Conform'): ('SHRINKWRAP', None), _msg('Conform Modifier'): ('SHRINKWRAP', None), _msg('Attribute Transfer'): ('DATA_TRANSFER', None), _msg('Point Cache'): ('MESH_CACHE', None), _msg('Point Cache (WSM)'): ('MESH_CACHE', None), _msg('MultiRes'): ('MULTIRES', None), _msg('Melt'): None, _msg('Edit Poly'): None, _msg('Edit Mesh'): None, _msg('Cap Holes'): None, _msg('Slice'): None, _msg('Normal Modifier'): None, _msg('Quadify Mesh'): None, _msg('Turn To Poly'): None, _msg('Morpher'): None}
SPECIAL_MODIFIERS = {_msg('Smooth'), _msg('Cloth'), _msg('Flex'), _msg('Unwrap UVW'), _msg('Hair and Fur (WSM)'), _msg('Extrude'), _msg('Renderable Spline Modifier'), _msg('Bevel')}

def modifier_available(name):
    return name in SPECIAL_MODIFIERS or MODIFIERS.get(name) is not None

class BSM_OT_max_modifier(Active, bpy.types.Operator):
    bl_idname = 'bsm.max_modifier'
    bl_label = _msg('Add Modifier')
    bl_options = {'REGISTER', 'UNDO'}
    name: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))

    @classmethod
    def description(cls, context, properties):
        return properties.name if modifier_available(properties.name) else _dcc_format('{0}: no Blender equivalent', properties.name)

    def execute(self, context):
        obj = context.view_layer.objects.active
        if obj is None or not obj.is_editable:
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select an object')))
            return {'CANCELLED'}
        name = self.name
        if not modifier_available(name):
            self.report({'WARNING'}, _dcc_ui_text(_dcc_format('{0}: no Blender equivalent', name)))
            return {'CANCELLED'}
        with context.temp_override(**viewport_override(context), active_object=obj, object=obj):
            if name == _msg('Smooth'):
                bpy.ops.object.shade_auto_smooth()
                return {'FINISHED'}
            if name in {_msg('Cloth'), _msg('Flex')}:
                bpy.ops.object.modifier_add(type='CLOTH' if name == _msg('Cloth') else 'SOFT_BODY')
                return {'FINISHED'}
            if name == _msg('Hair and Fur (WSM)'):
                bpy.ops.object.particle_system_add()
                obj.particle_systems[-1].settings.type = 'HAIR'
                return {'FINISHED'}
            if name == _msg('Unwrap UVW'):
                return bpy.ops.bsm.editor(kind='UV')
            if name in {_msg('Extrude'), _msg('Renderable Spline Modifier'), _msg('Bevel')}:
                if obj.type != 'CURVE':
                    self.report({'WARNING'}, _dcc_ui_text(_dcc_format('{0} applies to shapes', name)))
                    return {'CANCELLED'}
                if name == _msg('Extrude'):
                    obj.data.extrude = 0.1
                else:
                    obj.data.bevel_depth = 0.02
                return {'FINISHED'}
        (kind, setup) = MODIFIERS[name]
        try:
            mod = obj.modifiers.new(name, kind)
        except (RuntimeError, TypeError) as error:
            self.report({'WARNING'}, _dcc_ui_error(error))
            return {'CANCELLED'}
        if mod is None:
            self.report({'WARNING'}, _dcc_ui_text(_dcc_format('{0} cannot be applied to {1}', name, obj.type.title())))
            return {'CANCELLED'}
        if setup:
            setup(obj, mod)
        context.window_manager.bsm.active_modifier = mod.name
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')
CONSTRAINTS = {'ATTACHMENT': 'SHRINKWRAP', 'SURFACE': 'SHRINKWRAP', 'PATH': 'FOLLOW_PATH', 'POSITION': 'COPY_LOCATION', 'LINK': 'CHILD_OF', 'LOOKAT': 'DAMPED_TRACK', 'ORIENTATION': 'COPY_ROTATION'}

class BSM_OT_add_constraint(Active, bpy.types.Operator):
    bl_idname = 'bsm.add_constraint'
    bl_label = _msg('Add Constraint')
    bl_options = {'REGISTER', 'UNDO'}
    kind: EnumProperty(items=tuple(((k, k.title(), '') for k in CONSTRAINTS)), translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        obj = context.view_layer.objects.active
        if obj is None:
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select an object')))
            return {'CANCELLED'}
        constraint = obj.constraints.new(CONSTRAINTS[self.kind])
        if self.kind == 'LOOKAT':
            constraint.track_axis = 'TRACK_NEGATIVE_Z' if obj.type in {'CAMERA', 'LIGHT'} else 'TRACK_X'
        return bpy.ops.bsm.pick_object('INVOKE_DEFAULT', purpose='CONSTRAINT', data=constraint.name)
    bl_translation_context = _msg('DCCWorkflowKit.Max')
_activeshade = {}
SHADING_TYPE_STYLES = {'DEFAULT_SHADING', 'FACETS', 'FLAT_COLOR', 'CLAY', 'HIDDEN_LINE', 'WIREFRAME_OVERRIDE', 'STANDARD', 'PERFORMANCE', 'HIGH_QUALITY', 'DX_MODE', 'MATERIALS_REALISTIC', 'MATERIALS_SHADED'}

def set_activeshade(space, on):
    """Max's ActiveShade in a viewport: the render alone, without light and camera
    wireframes, the grid, selection outlines or the transform gizmo. Leaving it restores
    the shading and guides it replaced."""
    key = space.as_pointer()
    if on:
        if space.shading.type != 'RENDERED' or key not in _activeshade:
            previous = space.shading.type if space.shading.type != 'RENDERED' else 'SOLID'
            _activeshade[key] = (previous, space.overlay.show_overlays, space.show_gizmo)
        space.shading.type = 'RENDERED'
        space.overlay.show_overlays = False
        space.show_gizmo = False
    else:
        (shading, overlays, gizmos) = _activeshade.pop(key, ('SOLID', True, True))
        if space.shading.type == 'RENDERED':
            space.shading.type = shading
        (space.overlay.show_overlays, space.show_gizmo) = (overlays, gizmos)

def toggle_activeshade(space):
    set_activeshade(space, space.shading.type != 'RENDERED')

def _set_shading(context, style):
    space = _view(context)[2]
    (shading, overlay) = (space.shading, space.overlay)
    if style in SHADING_TYPE_STYLES and space.as_pointer() in _activeshade:
        (_, overlay.show_overlays, space.show_gizmo) = _activeshade.pop(space.as_pointer())
    if style == 'DEFAULT_SHADING':
        (shading.type, shading.light, shading.color_type) = ('SOLID', 'STUDIO', 'OBJECT')
    elif style == 'FACETS':
        (shading.type, shading.light) = ('SOLID', 'STUDIO')
        shading.show_cavity = False
    elif style == 'FLAT_COLOR':
        (shading.type, shading.light) = ('SOLID', 'FLAT')
    elif style == 'CLAY':
        (shading.type, shading.light, shading.color_type) = ('SOLID', 'STUDIO', 'SINGLE')
        shading.single_color = (0.8, 0.6, 0.45)
    elif style == 'HIDDEN_LINE':
        shading.type = 'WIREFRAME'
        shading.show_xray_wireframe = False
    elif style == 'WIREFRAME_OVERRIDE':
        shading.type = 'WIREFRAME'
        shading.show_xray_wireframe = True
        shading.wireframe_color_type = 'OBJECT'
    elif style == 'BOUNDING_BOX':
        for obj in context.view_layer.objects:
            if obj.type == 'MESH':
                obj.display_type = 'BOUNDS' if obj.display_type != 'BOUNDS' else 'TEXTURED'
    elif style == 'EDGED_FACES':
        overlay.show_wireframes = not overlay.show_wireframes
        overlay.wireframe_threshold = 1.0
    elif style == 'SHADE_SELECTED':
        run(context, 'SHADE_SELECTED')
    elif style in {'STANDARD', 'PERFORMANCE'}:
        (shading.type, shading.light) = ('SOLID', 'STUDIO')
        shading.show_shadows = shading.show_cavity = False
    elif style in {'HIGH_QUALITY', 'DX_MODE', 'MATERIALS_REALISTIC'}:
        shading.type = 'MATERIAL'
    elif style == 'MATERIALS_SHADED':
        (shading.type, shading.color_type) = ('SOLID', 'MATERIAL')
    elif style == 'DEFAULT_LIGHTS':
        shading.use_scene_lights = shading.use_scene_lights_render = False
    elif style == 'SCENE_LIGHTS':
        shading.use_scene_lights = shading.use_scene_lights_render = True
    elif style == 'SHADOWS':
        shading.show_shadows = not shading.show_shadows
    elif style == 'AO':
        shading.show_cavity = not shading.show_cavity
    elif style == 'UV_CHECKER':
        (shading.type, shading.color_type) = ('SOLID', 'TEXTURE')
SHADING_STYLES = ('DEFAULT_SHADING', 'FACETS', 'FLAT_COLOR', 'CLAY', 'HIDDEN_LINE', 'WIREFRAME_OVERRIDE', 'BOUNDING_BOX', 'EDGED_FACES', 'SHADE_SELECTED', 'STANDARD', 'HIGH_QUALITY', 'PERFORMANCE', 'DX_MODE', 'DEFAULT_LIGHTS', 'SCENE_LIGHTS', 'SHADOWS', 'AO', 'MATERIALS_SHADED', 'MATERIALS_REALISTIC', 'UV_CHECKER')

class BSM_OT_viewport_shading(Active, bpy.types.Operator):
    bl_idname = 'bsm.viewport_shading'
    bl_label = _msg('Viewport Shading')
    style: EnumProperty(items=tuple(((s, s.replace('_', ' ').title(), '') for s in SHADING_STYLES)), translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        try:
            _set_shading(context, self.style)
        except RuntimeError as error:
            self.report({'WARNING'}, _dcc_ui_error(error))
            return {'CANCELLED'}
        runtime.redraw()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def object_under_mouse(context, region, r3d, xy, exclude=()):
    """Nearest visible object under a region point: an icon Blender Max draws (lights,
    cameras, empties) first, as a click on a light's icon means the light; then mesh ray
    hits, else nearby origins."""
    from . import object_icons
    icon = object_icons.pick(bpy.context, region, xy)
    if icon is not None and icon not in exclude:
        return (icon, icon.matrix_world.translation.copy(), None)
    origin = view3d_utils.region_2d_to_origin_3d(region, r3d, xy)
    direction = view3d_utils.region_2d_to_vector_3d(region, r3d, xy)
    depsgraph = context.evaluated_depsgraph_get()
    (hit, location, normal, index, obj, matrix) = context.scene.ray_cast(depsgraph, origin, direction)
    if hit and obj is not None:
        obj = obj.original
        if obj not in exclude:
            return (obj, location, normal)
    best = None
    for obj in context.visible_objects:
        if obj in exclude or obj.type == 'MESH':
            continue
        point = view3d_utils.location_3d_to_region_2d(region, r3d, obj.matrix_world.translation)
        if point is None:
            continue
        distance = (point - Vector(xy)).length
        if distance < 14 and (best is None or distance < best[0]):
            best = (distance, obj)
    return (best[1], best[1].matrix_world.translation.copy(), None) if best else (None, None, None)
PICK_PURPOSES = ('LINK', 'BIND', 'ALIGN', 'CONSTRAINT', 'HIDE_BY_HIT', 'FREEZE_BY_HIT', 'UNFREEZE_BY_HIT', 'GROUP_ATTACH', 'REF_PICK', 'MOD_OBJECT', 'ATTACH')
PICK_PROMPTS = {'LINK': _msg('Drag from a child to its parent object'), 'BIND': _msg('Drag from an object to a space warp'), 'ALIGN': _msg('Pick Align Target Object'), 'CONSTRAINT': _msg('Pick the constraint target'), 'HIDE_BY_HIT': _msg('Pick objects to hide; right-click to finish'), 'FREEZE_BY_HIT': _msg('Pick objects to freeze; right-click to finish'), 'UNFREEZE_BY_HIT': _msg('Pick objects to unfreeze; right-click to finish'), 'GROUP_ATTACH': _msg('Pick a group to attach to'), 'REF_PICK': _msg('Pick an object for the reference coordinate system'), 'MOD_OBJECT': _msg('Pick an object for the modifier'), 'ATTACH': _msg('Pick an object to attach')}

class BSM_OT_pick_object(Active, bpy.types.Operator):
    bl_idname = 'bsm.pick_object'
    bl_label = _msg('Pick Object')
    bl_options = {'REGISTER', 'UNDO'}
    purpose: EnumProperty(items=tuple(((p, p.title(), '') for p in PICK_PURPOSES)), translation_context=_msg('DCCWorkflowKit.Max'))
    data: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            override = viewport_override(context)
            with context.temp_override(**override):
                return bpy.ops.bsm.pick_object('INVOKE_DEFAULT', purpose=self.purpose, data=self.data)
        self.source = None
        state = context.window_manager.bsm
        if state.pick_mode == self.purpose and self.purpose in {'LINK', 'BIND'}:
            state.pick_mode = ''
            return {'CANCELLED'}
        state.pick_mode = self.purpose
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(PICK_PROMPTS[self.purpose])
        state.prompt = PICK_PROMPTS[self.purpose]
        context.window.cursor_modal_set('EYEDROPPER')
        return {'RUNNING_MODAL'}

    def _finish(self, context, result):
        state = context.window_manager.bsm
        state.pick_mode = ''
        state.prompt = ''
        context.workspace.status_text_set(None)
        context.window.cursor_modal_restore()
        runtime.redraw()
        return result

    def _region(self, context, event):
        for area in context.window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type == 'WINDOW' and region.x <= event.mouse_x < region.x + region.width and (region.y <= event.mouse_y < region.y + region.height):
                    return (region, region.data)
        return (None, None)

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            return self._finish(context, {'CANCELLED'} if self.purpose not in {'HIDE_BY_HIT', 'FREEZE_BY_HIT', 'UNFREEZE_BY_HIT'} else {'FINISHED'})
        if event.type != 'LEFTMOUSE' or event.value not in {'PRESS', 'RELEASE'}:
            return {'RUNNING_MODAL'} if event.type not in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'MOUSEMOVE'} else {'PASS_THROUGH'}
        (region, r3d) = self._region(context, event)
        if region is None:
            return {'RUNNING_MODAL'}
        xy = (event.mouse_x - region.x, event.mouse_y - region.y)
        obj = object_under_mouse(context, region, r3d, xy)[0]
        if self.purpose in {'LINK', 'BIND'}:
            if event.value == 'PRESS':
                self.source = obj
                return {'RUNNING_MODAL'}
            if obj is None or self.source is None or obj == self.source:
                self.source = None
                return {'RUNNING_MODAL'}
            children = selected(context) if self.source.select_get() else [self.source]
            if self.purpose == 'LINK':
                for child in children:
                    if child != obj and obj not in child.children_recursive:
                        _parent_keep(child, obj)
                self.report({'INFO'}, _dcc_ui_text(_dcc_format('Linked {0} object(s) to {1}', len(children), obj.name)))
            else:
                if obj.field is None or obj.field.type == 'NONE':
                    self.report({'WARNING'}, _dcc_ui_text(_msg('Pick a space warp (force field)')))
                    return {'RUNNING_MODAL'}
                group = bpy.data.collections.get(_dcc_format('Bound to {0}', obj.name)) or bpy.data.collections.new(_dcc_format('Bound to {0}', obj.name))
                if obj.name not in group.objects:
                    group.objects.link(obj)
                bound = 0
                for child in children:
                    for settings in [m.settings for m in child.modifiers if m.type in {'CLOTH', 'SOFT_BODY'}] + [p.settings for p in getattr(child, 'particle_systems', ())]:
                        settings.effector_weights.collection = group
                        bound += 1
                self.report({'INFO'} if bound else {'WARNING'}, _dcc_ui_text(_dcc_format('Bound {0} simulation(s) to {1}', bound, obj.name) if bound else _msg('Blender space warps affect simulations (cloth, soft body, particles) only')))
            self.source = None
            return {'RUNNING_MODAL'}
        if event.value != 'PRESS' or obj is None:
            return {'RUNNING_MODAL'}
        if self.purpose == 'ALIGN':
            if obj.select_get():
                return {'RUNNING_MODAL'}
            self._finish(context, {'FINISHED'})
            return bpy.ops.bsm.align('INVOKE_DEFAULT', target=obj.name)
        if self.purpose == 'CONSTRAINT':
            active = context.view_layer.objects.active
            constraint = active.constraints.get(self.data) if active else None
            if constraint and obj != active:
                constraint.target = obj
                if constraint.type == 'FOLLOW_PATH' and obj.type == 'CURVE':
                    obj.data.use_path = True
            return self._finish(context, {'FINISHED'})
        if self.purpose == 'HIDE_BY_HIT':
            obj.hide_set(True)
            return {'RUNNING_MODAL'}
        if self.purpose in {'FREEZE_BY_HIT', 'UNFREEZE_BY_HIT'}:
            freeze(obj, self.purpose == 'FREEZE_BY_HIT')
            return {'RUNNING_MODAL'}
        if self.purpose == 'GROUP_ATTACH':
            head = group_head(obj)
            if head is None:
                self.report({'WARNING'}, _dcc_ui_text(_msg('Pick a member of a group')))
                return {'RUNNING_MODAL'}
            for child in selected(context):
                if child != head and head not in child.children_recursive:
                    _parent_keep(child, head)
            return self._finish(context, {'FINISHED'})
        if self.purpose == 'MOD_OBJECT':
            active = context.view_layer.objects.active
            mod = active.modifiers.get(self.data) if active else None
            if mod and obj != active:
                from .surfaces import OBJECT_SLOTS
                slot = OBJECT_SLOTS.get(mod.type, 'object')
                try:
                    setattr(mod, slot, obj)
                except (TypeError, AttributeError) as error:
                    self.report({'WARNING'}, _dcc_ui_error(error))
                    return {'RUNNING_MODAL'}
                if mod.type == 'BOOLEAN':
                    obj.display_type = 'WIRE'
            return self._finish(context, {'FINISHED'})
        if self.purpose == 'ATTACH':
            active = context.view_layer.objects.active
            if active is None or obj == active or obj.type != active.type:
                return {'RUNNING_MODAL'}
            mode = active.mode
            if mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            for other in context.view_layer.objects:
                other.select_set(other in {obj, active})
            with context.temp_override(active_object=active, object=active, selected_objects=[active, obj], selected_editable_objects=[active, obj]):
                bpy.ops.object.join()
            if mode == 'EDIT':
                bpy.ops.object.mode_set(mode='EDIT')
            return self._finish(context, {'FINISHED'})
        if self.purpose == 'REF_PICK':
            context.window_manager.bsm.ref_coord = 'PICK'
            context.window_manager.bsm.ref_pick = obj.name
            from . import runtime as rt
            rt.sync_reference(context)
            return self._finish(context, {'FINISHED'})
        return {'RUNNING_MODAL'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_align(Active, bpy.types.Operator):
    bl_idname = 'bsm.align'
    bl_label = _msg('Align Selection')
    bl_options = {'REGISTER', 'UNDO'}
    target: StringProperty(name=_msg('Target'), translation_context=_msg('DCCWorkflowKit.Max'))
    pos_x: BoolProperty(name=_msg('X Position'), default=True, translation_context=_msg('DCCWorkflowKit.Max'))
    pos_y: BoolProperty(name=_msg('Y Position'), default=True, translation_context=_msg('DCCWorkflowKit.Max'))
    pos_z: BoolProperty(name=_msg('Z Position'), default=True, translation_context=_msg('DCCWorkflowKit.Max'))
    points = (('MIN', _msg('Minimum'), ''), ('CENTER', _msg('Center'), ''), ('PIVOT', _msg('Pivot Point'), ''), ('MAX', _msg('Maximum'), ''))
    current: EnumProperty(name=_msg('Current Object'), items=points, default='CENTER', translation_context=_msg('DCCWorkflowKit.Max'))
    target_point: EnumProperty(name=_msg('Target Object'), items=points, default='CENTER', translation_context=_msg('DCCWorkflowKit.Max'))
    orient_x: BoolProperty(name=_msg('X Axis'), translation_context=_msg('DCCWorkflowKit.Max'))
    orient_y: BoolProperty(name=_msg('Y Axis'), translation_context=_msg('DCCWorkflowKit.Max'))
    orient_z: BoolProperty(name=_msg('Z Axis'), translation_context=_msg('DCCWorkflowKit.Max'))
    scale_x: BoolProperty(name=_msg('X Axis'), translation_context=_msg('DCCWorkflowKit.Max'))
    scale_y: BoolProperty(name=_msg('Y Axis'), translation_context=_msg('DCCWorkflowKit.Max'))
    scale_z: BoolProperty(name=_msg('Z Axis'), translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360, title=_dcc_format('Align Selection ({0})', self.target))

    def draw(self, context):
        l = self.layout
        box = l.box()
        box.label(text=_dcc_ui_text(_msg('Align Position (World):')))
        row = box.row()
        row.prop(self, 'pos_x')
        row.prop(self, 'pos_y')
        row.prop(self, 'pos_z')
        row = box.row()
        row.column().prop(self, 'current', expand=True)
        row.column().prop(self, 'target_point', expand=True)
        box = l.box()
        box.label(text=_dcc_ui_text(_msg('Align Orientation (Local):')))
        row = box.row()
        row.prop(self, 'orient_x')
        row.prop(self, 'orient_y')
        row.prop(self, 'orient_z')
        box = l.box()
        box.label(text=_dcc_ui_text(_msg('Match Scale:')))
        row = box.row()
        row.prop(self, 'scale_x')
        row.prop(self, 'scale_y')
        row.prop(self, 'scale_z')

    @staticmethod
    def _point(obj, kind):
        if kind == 'PIVOT':
            return obj.matrix_world.translation.copy()
        (low, high) = world_bounds(obj)
        return {'MIN': low, 'MAX': high, 'CENTER': (low + high) / 2}[kind]

    def execute(self, context):
        target = bpy.data.objects.get(self.target)
        if target is None:
            return {'CANCELLED'}
        for obj in selected(context):
            if obj == target:
                continue
            source = self._point(obj, self.current)
            goal = self._point(target, self.target_point)
            world = obj.matrix_world.copy()
            for (axis, use) in enumerate((self.pos_x, self.pos_y, self.pos_z)):
                if use:
                    world.translation[axis] += goal[axis] - source[axis]
            (location, rotation, scale) = world.decompose()
            target_rotation = target.matrix_world.to_quaternion()
            if self.orient_x and self.orient_y and self.orient_z:
                rotation = target_rotation
            elif self.orient_x or self.orient_y or self.orient_z:
                (euler, goal_euler) = (rotation.to_euler(), target_rotation.to_euler())
                for (axis, use) in enumerate((self.orient_x, self.orient_y, self.orient_z)):
                    if use:
                        euler[axis] = goal_euler[axis]
                rotation = euler.to_quaternion()
            target_scale = target.matrix_world.to_scale()
            for (axis, use) in enumerate((self.scale_x, self.scale_y, self.scale_z)):
                if use:
                    scale[axis] = target_scale[axis]
            obj.matrix_world = Matrix.LocRotScale(location, rotation, scale)
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')
AXES = (('X', 'X', ''), ('Y', 'Y', ''), ('Z', 'Z', ''), ('XY', 'XY', ''), ('YZ', 'YZ', ''), ('ZX', 'ZX', ''))
CLONES = (('NONE', _msg('No Clone'), ''), ('COPY', _msg('Copy'), ''), ('INSTANCE', _msg('Instance'), ''), ('REFERENCE', _msg('Reference'), ''))

def clone_object(context, obj, mode):
    copy = obj.copy()
    if mode == 'COPY' and obj.data is not None:
        copy.data = obj.data.copy()
    for collection in obj.users_collection:
        collection.objects.link(copy)
    copy.name = unique_name(obj.name.rstrip('0123456789') or obj.name)
    return copy

class BSM_OT_mirror(Active, bpy.types.Operator):
    bl_idname = 'bsm.mirror'
    bl_label = _msg('Mirror: World Coordinates')
    bl_options = {'REGISTER', 'UNDO'}
    axis: EnumProperty(name=_msg('Mirror Axis'), items=AXES, default='X', translation_context=_msg('DCCWorkflowKit.Max'))
    offset: FloatProperty(name=_msg('Offset'), subtype='DISTANCE', unit='LENGTH', translation_context=_msg('DCCWorkflowKit.Max'))
    clone: EnumProperty(name=_msg('Clone Selection'), items=CLONES, default='NONE', translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        if not selected(context):
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select objects to mirror')))
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        row = self.layout.row()
        row.column().prop(self, 'axis', expand=True)
        column = row.column()
        column.prop(self, 'offset')
        column.label(text=_dcc_ui_text(_msg('Clone Selection:')))
        column.prop(self, 'clone', expand=True)

    def execute(self, context):
        flip = [-1 if a in self.axis else 1 for a in 'XYZ']
        pivot = context.scene.tool_settings.transform_pivot_point
        objects = selected(context)
        center = sum((o.matrix_world.translation for o in objects), Vector()) / len(objects)
        if pivot in {'BOUNDING_BOX_CENTER', 'MEDIAN_POINT'}:
            (low, high) = selection_bounds(objects)
            center = (low + high) / 2
        targets = objects
        if self.clone != 'NONE':
            targets = [clone_object(context, o, self.clone) for o in objects]
            for o in objects:
                o.select_set(False)
            for o in targets:
                o.select_set(True)
            context.view_layer.objects.active = targets[0]
        offset = Vector(tuple((self.offset if a in self.axis else 0 for a in 'XYZ')))
        for obj in targets:
            origin = center if pivot in {'BOUNDING_BOX_CENTER', 'MEDIAN_POINT'} else obj.matrix_world.translation.copy()
            mirror = Matrix.Translation(origin + offset) @ Matrix.Diagonal((*flip, 1)) @ Matrix.Translation(-origin)
            obj.matrix_world = mirror @ obj.matrix_world
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_array(Active, bpy.types.Operator):
    bl_idname = 'bsm.array'
    bl_label = _msg('Array')
    bl_options = {'REGISTER', 'UNDO'}
    move: FloatVectorProperty(name=_msg('Move'), subtype='TRANSLATION', unit='LENGTH', default=(2, 0, 0), translation_context=_msg('DCCWorkflowKit.Max'))
    rotate: FloatVectorProperty(name=_msg('Rotate'), size=3, default=(0, 0, 0), translation_context=_msg('DCCWorkflowKit.Max'))
    scale: FloatVectorProperty(name=_msg('Scale %'), size=3, default=(100, 100, 100), translation_context=_msg('DCCWorkflowKit.Max'))
    kind: EnumProperty(name=_msg('Type of Object'), items=CLONES[1:], default='COPY', translation_context=_msg('DCCWorkflowKit.Max'))
    count_1d: IntProperty(name=_msg('1D Count'), default=10, min=1, translation_context=_msg('DCCWorkflowKit.Max'))
    count_2d: IntProperty(name=_msg('2D Count'), default=1, min=1, translation_context=_msg('DCCWorkflowKit.Max'))
    offset_2d: FloatVectorProperty(name=_msg('2D Offset'), subtype='TRANSLATION', unit='LENGTH', default=(0, 2, 0), translation_context=_msg('DCCWorkflowKit.Max'))
    count_3d: IntProperty(name=_msg('3D Count'), default=1, min=1, translation_context=_msg('DCCWorkflowKit.Max'))
    offset_3d: FloatVectorProperty(name=_msg('3D Offset'), subtype='TRANSLATION', unit='LENGTH', default=(0, 0, 2), translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        if not selected(context):
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select objects to array')))
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        l = self.layout
        box = l.box()
        box.label(text=_dcc_ui_text(_msg('Array Transformation: World Coordinates (Use Pivot Point Center)')))
        box.prop(self, 'move', text=_dcc_ui_text(_msg('Incremental Move')))
        box.prop(self, 'rotate', text=_dcc_ui_text(_msg('Incremental Rotate')))
        box.prop(self, 'scale', text=_dcc_ui_text(_msg('Incremental Scale %')))
        row = l.row()
        row.prop(self, 'kind', expand=True)
        box = l.box()
        box.label(text=_dcc_ui_text(_msg('Array Dimensions')))
        box.prop(self, 'count_1d')
        row = box.row()
        row.prop(self, 'count_2d')
        row.prop(self, 'offset_2d', text=_dcc_ui_text(''))
        row = box.row()
        row.prop(self, 'count_3d')
        row.prop(self, 'offset_3d', text=_dcc_ui_text(''))
        total = self.count_1d * self.count_2d * self.count_3d * len(selected(context))
        l.label(text=_dcc_ui_text(_dcc_format('Total in Array: {0}', total)))

    def execute(self, context):
        sources = selected(context)
        created = 0
        for obj in sources:
            base = obj.matrix_world.copy()
            pivot = base.translation.copy()
            for k in range(self.count_3d):
                for j in range(self.count_2d):
                    for i in range(self.count_1d):
                        if i == j == k == 0:
                            continue
                        copy = clone_object(context, obj, self.kind)
                        rotation = Matrix.Identity(4)
                        for (axis, angle) in zip('XYZ', self.rotate):
                            rotation = Matrix.Rotation(math.radians(angle * i), 4, axis) @ rotation
                        scale = Matrix.Diagonal(tuple(((s / 100.0) ** i for s in self.scale)) + (1,))
                        offset = Vector(self.move) * i + Vector(self.offset_2d) * j + Vector(self.offset_3d) * k
                        copy.matrix_world = Matrix.Translation(pivot + offset) @ rotation @ scale @ Matrix.Translation(-pivot) @ base
                        created += 1
        self.report({'INFO'}, _dcc_ui_text(_dcc_format('Created {0} object(s)', created)))
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_group(Active, bpy.types.Operator):
    bl_idname = 'bsm.group'
    bl_label = _msg('Group')
    bl_options = {'REGISTER', 'UNDO'}
    name: StringProperty(name=_msg('Group name'), default=_msg('Group001'), translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        if not selected(context):
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select objects to group')))
            return {'CANCELLED'}
        self.name = unique_name(_msg('Group'))
        return context.window_manager.invoke_props_dialog(self, width=260)

    def execute(self, context):
        return {'FINISHED'} if _make_group(context, self.name) else {'CANCELLED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_rename_objects(Active, bpy.types.Operator):
    bl_idname = 'bsm.rename_objects'
    bl_label = _msg('Rename Objects')
    bl_options = {'REGISTER', 'UNDO'}
    use_base: BoolProperty(name=_msg('Base Name'), translation_context=_msg('DCCWorkflowKit.Max'))
    base: StringProperty(name=_msg('Base Name'), default=_msg('Object'), translation_context=_msg('DCCWorkflowKit.Max'))
    use_prefix: BoolProperty(name=_msg('Prefix'), translation_context=_msg('DCCWorkflowKit.Max'))
    prefix: StringProperty(name=_msg('Prefix'), translation_context=_msg('DCCWorkflowKit.Max'))
    remove_first: IntProperty(name=_msg('Remove First'), min=0, translation_context=_msg('DCCWorkflowKit.Max'))
    remove_last: IntProperty(name=_msg('Remove Last'), min=0, translation_context=_msg('DCCWorkflowKit.Max'))
    use_suffix: BoolProperty(name=_msg('Suffix'), translation_context=_msg('DCCWorkflowKit.Max'))
    suffix: StringProperty(name=_msg('Suffix'), translation_context=_msg('DCCWorkflowKit.Max'))
    numbered: BoolProperty(name=_msg('Numbered'), translation_context=_msg('DCCWorkflowKit.Max'))
    base_number: IntProperty(name=_msg('Base Number'), default=0, translation_context=_msg('DCCWorkflowKit.Max'))
    step: IntProperty(name=_msg('Step'), default=1, translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320, confirm_text=_msg('Rename'))

    def draw(self, context):
        l = self.layout
        for (use, value) in (('use_base', 'base'), ('use_prefix', 'prefix'), ('use_suffix', 'suffix')):
            row = l.row()
            row.prop(self, use, text=_dcc_ui_text(''))
            sub = row.row()
            sub.enabled = getattr(self, use)
            sub.prop(self, value)
        l.prop(self, 'remove_first')
        l.prop(self, 'remove_last')
        row = l.row()
        row.prop(self, 'numbered')
        row.prop(self, 'base_number')
        row.prop(self, 'step')

    def execute(self, context):
        objects = sorted(selected(context), key=lambda o: o.name)
        for (index, obj) in enumerate(objects):
            name = self.base if self.use_base else obj.name
            name = name[self.remove_first:]
            if self.remove_last:
                name = name[:-self.remove_last]
            if self.use_prefix:
                name = self.prefix + name
            if self.use_suffix:
                name += self.suffix
            if self.numbered:
                name += f'{self.base_number + index * self.step:03d}'
            obj.name = name
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_SceneItem(bpy.types.PropertyGroup):
    selected: BoolProperty(name='', translation_context=_msg('DCCWorkflowKit.Max'))

class BSM_UL_scene_items(bpy.types.UIList):

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0, flt_flag=0):
        obj = bpy.data.objects.get(item.name)
        row = layout.row(align=True)
        row.prop(item, 'selected', text=_dcc_ui_text(''))
        row.label(text=_dcc_ui_text(item.name), icon={'MESH': 'MESH_DATA', 'LIGHT': 'LIGHT', 'CAMERA': 'CAMERA_DATA', 'EMPTY': 'EMPTY_DATA', 'CURVE': 'CURVE_DATA'}.get(obj.type if obj else '', 'OBJECT_DATA'))

class BSM_OT_select_from_scene(Active, bpy.types.Operator):
    bl_idname = 'bsm.select_from_scene'
    bl_label = _msg('Select From Scene')
    bl_options = {'REGISTER', 'UNDO'}
    purpose: EnumProperty(items=(('SELECT', _msg('Select'), ''), ('HIDE', _msg('Hide'), ''), ('UNHIDE', _msg('Unhide'), ''), ('FREEZE', _msg('Freeze'), ''), ('UNFREEZE', _msg('Unfreeze'), '')), default='SELECT', translation_context=_msg('DCCWorkflowKit.Max'))
    items: CollectionProperty(type=BSM_SceneItem, translation_context=_msg('DCCWorkflowKit.Max'))
    index: IntProperty(translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        self.items.clear()
        for obj in sorted(context.view_layer.objects, key=lambda o: o.name.casefold()):
            hidden = obj.hide_get()
            if self.purpose == 'UNHIDE' and (not hidden) or (self.purpose in {'SELECT', 'HIDE', 'FREEZE'} and hidden):
                continue
            if self.purpose == 'UNFREEZE' and (not obj.hide_select):
                continue
            item = self.items.add()
            item.name = obj.name
            item.selected = obj.select_get() if self.purpose == 'SELECT' else False
        title = {'SELECT': _msg('Select From Scene'), 'HIDE': _msg('Hide Objects'), 'UNHIDE': _msg('Unhide Objects'), 'FREEZE': _msg('Freeze Objects'), 'UNFREEZE': _msg('Unfreeze Objects')}[self.purpose]
        return context.window_manager.invoke_props_dialog(self, width=360, title=title, confirm_text=self.purpose.title())

    def draw(self, context):
        self.layout.template_list(_msg('BSM_UL_scene_items'), '', self, 'items', self, 'index', rows=14)

    def execute(self, context):
        chosen = {item.name for item in self.items if item.selected}
        for obj in list(context.view_layer.objects):
            if self.purpose == 'SELECT':
                if not obj.hide_select and (not obj.hide_get()):
                    obj.select_set(obj.name in chosen)
            elif obj.name in chosen:
                if self.purpose in {'HIDE', 'UNHIDE'}:
                    obj.hide_set(self.purpose == 'HIDE')
                else:
                    freeze(obj, self.purpose == 'FREEZE')
        if self.purpose == 'SELECT':
            first = next((bpy.data.objects.get(n) for n in sorted(chosen)), None)
            if first:
                context.view_layer.objects.active = first
            promote_groups(context)
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_set_action(Active, bpy.types.Operator):
    bl_idname = 'bsm.set_action'
    bl_label = _msg('Selection Set Action')
    bl_options = {'REGISTER', 'UNDO'}
    name: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    action: EnumProperty(items=tuple(((a, a.title(), '') for a in ('SELECT', 'ADD', 'REMOVE', 'DELETE', 'CREATE'))), translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        group = bpy.data.collections.get(self.name)
        objects = selected(context)
        if self.action == 'CREATE':
            if not objects:
                self.report({'WARNING'}, _dcc_ui_text(_msg('Select objects first')))
                return {'CANCELLED'}
            group = bpy.data.collections.new(self.name or _msg('Selection Set'))
            group['bsm_selection_set'] = True
            context.scene.collection.children.link(group)
            for obj in objects:
                group.objects.link(obj)
        elif group is None:
            return {'CANCELLED'}
        elif self.action == 'SELECT':
            return bpy.ops.bsm.select_set(name=self.name)
        elif self.action == 'ADD':
            for obj in objects:
                if obj.name not in group.objects:
                    group.objects.link(obj)
        elif self.action == 'REMOVE':
            for obj in objects:
                if obj.name in group.objects:
                    group.objects.unlink(obj)
        elif self.action == 'DELETE':
            bpy.data.collections.remove(group)
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_manage_sets(Active, bpy.types.Operator):
    bl_idname = 'bsm.manage_sets'
    bl_label = _msg('Named Selection Sets')
    name: StringProperty(name=_msg('New Set'), default=_msg('Selection Set'), translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=340)

    def draw(self, context):
        l = self.layout
        l.label(text=_dcc_ui_text(_msg('Named Selection Sets')))
        row = l.row(align=True)
        row.prop(self, 'name', text=_dcc_ui_text(''))
        op = row.operator('bsm.set_action', text=_dcc_ui_text(_msg('Create New Set')), icon='ADD')
        (op.name, op.action) = (self.name, 'CREATE')
        sets = [c for c in bpy.data.collections if c.get('bsm_selection_set')]
        if not sets:
            l.label(text=_dcc_ui_text(_msg('No selection sets')))
        for group in sets:
            box = l.box()
            row = box.row(align=True)
            row.label(text=_dcc_ui_text(f'{group.name} ({len(group.objects)})'), icon='GROUP')
            for (action, icon) in (('SELECT', 'RESTRICT_SELECT_OFF'), ('ADD', 'ADD'), ('REMOVE', 'REMOVE'), ('DELETE', 'X')):
                op = row.operator('bsm.set_action', text=_dcc_ui_text(''), icon=icon)
                (op.name, op.action) = (group.name, action)

    def execute(self, context):
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_object_properties(Active, bpy.types.Operator):
    bl_idname = 'bsm.object_properties'
    bl_label = _msg('Object Properties')

    def invoke(self, context, event):
        if context.view_layer.objects.active is None:
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select an object')))
            return {'CANCELLED'}
        return context.window_manager.invoke_popup(self, width=420)

    def draw(self, context):
        obj = context.view_layer.objects.active
        l = self.layout
        box = l.box()
        box.label(text=_dcc_ui_text(_msg('Object Information')))
        box.prop(obj, 'name', text=_dcc_ui_text(_msg('Name')))
        box.label(text=_dcc_ui_text(_dcc_format('Dimensions: {0:.3f} x {1:.3f} x {2:.3f}', obj.dimensions.x, obj.dimensions.y, obj.dimensions.z)))
        if obj.type == 'MESH':
            box.label(text=_dcc_ui_text(_dcc_format('Vertices: {0}    Faces: {1}', len(obj.data.vertices), len(obj.data.polygons))))
        box.label(text=_dcc_ui_text(_dcc_format('Parent: {0}    Material: {1}', obj.parent.name if obj.parent else 'Scene Root', obj.active_material.name if obj.active_material else 'None')))
        row = l.row()
        col = row.box().column()
        col.label(text=_dcc_ui_text(_msg('Interactivity')))
        col.prop(obj, 'hide_viewport', text=_dcc_ui_text(_msg('Hide')))
        col.prop(obj, 'hide_select', text=_dcc_ui_text(_msg('Freeze')))
        col = row.box().column()
        col.label(text=_dcc_ui_text(_msg('Display Properties')))
        col.prop(obj, 'display_type', text=_dcc_ui_text(''))
        col.prop(obj, 'show_wire', text=_dcc_ui_text(_msg('Edges Only')))
        col.prop(obj, 'show_in_front', text=_dcc_ui_text(_msg('Display in Front')))
        col = l.box().column()
        col.label(text=_dcc_ui_text(_msg('Rendering Control')))
        col.prop(obj, 'hide_render', text=_dcc_ui_text(_msg('Not Renderable')))
        col.prop(obj, 'visible_camera', text=_dcc_ui_text(_msg('Visible to Camera')))
        col.prop(obj, 'visible_shadow', text=_dcc_ui_text(_msg('Cast Shadows')))
        col.prop(obj, 'visible_diffuse', text=_dcc_ui_text(_msg('Visible to Reflection/Refraction')))

    def execute(self, context):
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_settings_popup(Active, bpy.types.Operator):
    bl_idname = 'bsm.settings_popup'
    bl_label = _msg('Settings')
    kind: EnumProperty(items=tuple(((k, k.title(), '') for k in ('LIGHTS', 'SNAPS', 'VIEWPORT', 'ENVIRONMENT', 'EXPOSURE', 'COLOR_MANAGEMENT', 'PRINT_SIZE', 'UNITS_SETUP', 'SUMMARY_INFO', 'AOVS', 'LIGHT_GROUPS'))), translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=440)

    def draw(self, context):
        l = self.layout
        scene = context.scene
        title = {'LIGHTS': _msg('Light Lister'), 'SNAPS': _msg('Grid and Snap Settings'), 'VIEWPORT': _msg('Viewport Configuration'), 'ENVIRONMENT': _msg('Environment and Effects'), 'EXPOSURE': _msg('Exposure Control'), 'COLOR_MANAGEMENT': _msg('Color Management'), 'PRINT_SIZE': _msg('Print Size Assistant'), 'UNITS_SETUP': _msg('Units Setup'), 'SUMMARY_INFO': _msg('Summary Info'), 'AOVS': _msg('Render Passes (AOVs)'), 'LIGHT_GROUPS': _msg('Light Groups')}[self.kind]
        l.label(text=_dcc_ui_text(title))
        if self.kind == 'AOVS':
            layer = context.view_layer
            grid = l.grid_flow(columns=2)
            for attr in ('use_pass_combined', 'use_pass_z', 'use_pass_mist', 'use_pass_normal', 'use_pass_diffuse_color', 'use_pass_glossy_color', 'use_pass_emit', 'use_pass_environment', 'use_pass_ambient_occlusion', 'use_pass_shadow', 'use_pass_object_index', 'use_pass_material_index'):
                if hasattr(layer, attr):
                    grid.prop(layer, attr)
        elif self.kind == 'LIGHT_GROUPS':
            layer = context.view_layer
            for group in getattr(layer, 'lightgroups', ()):
                l.prop(group, 'name', text=_dcc_ui_text(''))
            l.operator('scene.view_layer_add_lightgroup', text=_dcc_ui_text(_msg('Add Light Group')))
            for obj in [o for o in scene.objects if o.type == 'LIGHT']:
                l.prop(obj, 'lightgroup', text=_dcc_ui_text(obj.name))
        elif self.kind == 'LIGHTS':
            lights = [o for o in scene.objects if o.type == 'LIGHT']
            if not lights:
                l.label(text=_dcc_ui_text(_msg('No lights in the scene')))
            for obj in lights:
                row = l.row(align=True)
                row.prop(obj, 'hide_render', text=_dcc_ui_text(''), icon='LIGHT', invert_checkbox=True)
                row.label(text=_dcc_ui_text(obj.name))
                row.prop(obj.data, 'color', text=_dcc_ui_text(''))
                row.prop(obj.data, 'energy', text=_dcc_ui_text(_msg('Multiplier')))
        elif self.kind == 'SNAPS':
            ts = scene.tool_settings
            l.prop(ts, 'snap_elements', expand=True)
            l.prop(ts, 'snap_target')
            l.prop(ts, 'use_snap_self')
            l.prop(ts, 'snap_angle_increment_3d', text=_dcc_ui_text(_msg('Angle')))
            l.prop(context.window_manager.bsm, 'snap_mode', expand=True)
            l.prop(context.window_manager.bsm, 'grid_spacing')
            l.prop(context.window_manager.bsm, 'spinner_snap_value')
        elif self.kind == 'VIEWPORT':
            space = _view(context)[2]
            l.prop(space.shading, 'type', expand=True)
            l.prop(space.overlay, 'show_stats')
            l.prop(space, 'lens')
            l.prop(space, 'clip_start')
            l.prop(space, 'clip_end')
            l.operator('bsm.quad_view', text=_dcc_ui_text(_msg('Toggle 4 Viewports / Maximize')))
        elif self.kind == 'ENVIRONMENT':
            world = scene.world
            if world is None:
                l.operator('world.new')
            else:
                node = world.node_tree.nodes.get(_msg('Background')) if world.node_tree else None
                if node:
                    l.prop(node.inputs[_msg('Color')], 'default_value', text=_dcc_ui_text(_msg('Background Color')))
                    l.prop(node.inputs[_msg('Strength')], 'default_value', text=_dcc_ui_text(_msg('Level')))
                else:
                    l.prop(world, 'color', text=_dcc_ui_text(_msg('Background Color')))
        elif self.kind in {'EXPOSURE', 'COLOR_MANAGEMENT'}:
            view = scene.view_settings
            if self.kind == 'COLOR_MANAGEMENT':
                l.prop(scene.display_settings, 'display_device')
                l.prop(view, 'view_transform')
            l.prop(view, 'look')
            l.prop(view, 'exposure')
            l.prop(view, 'gamma')
        elif self.kind == 'PRINT_SIZE':
            render = scene.render
            l.prop(render, 'resolution_x', text=_dcc_ui_text(_msg('Image Width')))
            l.prop(render, 'resolution_y', text=_dcc_ui_text(_msg('Image Height')))
            l.prop(render, 'resolution_percentage')
        elif self.kind == 'UNITS_SETUP':
            units = scene.unit_settings
            l.prop(units, 'system')
            l.prop(units, 'scale_length', text=_dcc_ui_text(_msg('System Unit Scale')))
            l.prop(units, 'length_unit')
            l.prop(units, 'system_rotation')
        else:
            stats = [o for o in scene.objects]
            meshes = [o for o in stats if o.type == 'MESH']
            l.label(text=_dcc_ui_text(_dcc_format('Scene: {0}', bpy.data.filepath or 'Untitled')))
            l.label(text=_dcc_ui_text(_dcc_format('Objects: {0}   Meshes: {1}   Lights: {2}   Cameras: {3}', len(stats), len(meshes), sum((o.type == 'LIGHT' for o in stats)), sum((o.type == 'CAMERA' for o in stats)))))
            l.label(text=_dcc_ui_text(_dcc_format('Vertices: {0}   Faces: {1}', sum((len(o.data.vertices) for o in meshes)), sum((len(o.data.polygons) for o in meshes)))))
            l.label(text=_dcc_ui_text(_dcc_format('Animation: {0} to {1} at {2} fps', scene.frame_start, scene.frame_end, scene.render.fps)))
            l.label(text=_dcc_ui_text(_dcc_format('Render size: {0} x {1}', scene.render.resolution_x, scene.render.resolution_y)))

    def execute(self, context):
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_run_script(Active, bpy.types.Operator, ImportHelper):
    bl_idname = 'bsm.run_script'
    bl_label = _msg('Run Script')
    filename_ext = '.py'
    filter_glob: StringProperty(default='*.py', options={'HIDDEN'}, translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        with open(self.filepath, encoding='utf-8') as handle:
            code = compile(handle.read(), self.filepath, 'exec')
        exec(code, {'__name__': '__main__', '__file__': self.filepath})
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')
_render_cleanup = []

def _remove_render_temps():
    for (scene_name, previous, temps) in _render_cleanup:
        scene = bpy.data.scenes.get(scene_name)
        if scene is not None:
            try:
                scene.camera = previous
            except ReferenceError:
                scene.camera = None
        for obj in temps:
            try:
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
            except ReferenceError:
                continue
            if data is not None and data.users == 0:
                (bpy.data.cameras if isinstance(data, bpy.types.Camera) else bpy.data.lights).remove(data)
    _render_cleanup.clear()
    runtime.redraw()
    return None

def _render_finished(*_):
    for handlers in (bpy.app.handlers.render_complete, bpy.app.handlers.render_cancel):
        if _render_finished in handlers:
            handlers.remove(_render_finished)
    bpy.app.timers.register(_remove_render_temps, first_interval=0.1)

def render_active_view(context, animation=False, write_still=False):
    """Render the active viewport (Max's Render Production) and return the operator result."""
    scene = context.scene
    previous = scene.camera
    temps = []
    try:
        override = viewport_override(context)
        r3d = override['region'].data
    except RuntimeError:
        (override, r3d) = (None, None)
    view_rotation = None
    from .editor_host import render_view
    from .operators import view_name
    render_view[0] = view_name(r3d) if r3d is not None else scene.camera.name if scene.camera else ''
    if r3d is not None and r3d.view_perspective != 'CAMERA':
        (region, space) = (override['region'], override['area'].spaces.active)
        data = bpy.data.cameras.new(_msg('Viewport Render'))
        camera = bpy.data.objects.new(_msg('Viewport Render'), data)
        camera['bsm_render_temp'] = True
        scene.collection.objects.link(camera)
        camera.matrix_world = r3d.view_matrix.inverted()
        projection = r3d.window_matrix
        landscape = scene.render.resolution_x * scene.render.pixel_aspect_x >= scene.render.resolution_y * scene.render.pixel_aspect_y
        if r3d.view_perspective == 'ORTHO':
            data.type = 'ORTHO'
            data.ortho_scale = 2 / (projection[0][0] if landscape else projection[1][1])
            matrix = camera.matrix_world.copy()
            matrix.translation += matrix.to_3x3() @ Vector((0, 0, space.clip_end / 2))
            camera.matrix_world = matrix
            (data.clip_start, data.clip_end) = (0.001, space.clip_end * 1.5)
        else:
            data.lens = data.sensor_width / 2 * (projection[0][0] if landscape else projection[1][1])
            (data.clip_start, data.clip_end) = (space.clip_start, space.clip_end)
        camera.hide_viewport = camera.hide_select = True
        scene.camera = camera
        temps.append(camera)
        view_rotation = r3d.view_rotation
    elif scene.camera is None:
        raise RuntimeError(_msg('Choose a camera or a viewport before rendering'))
    if not any((o.type == 'LIGHT' and (not o.hide_render) for o in scene.objects)):
        data = bpy.data.lights.new(_msg('Default Light'), 'SUN')
        data.energy = 3.0
        light = bpy.data.objects.new(_msg('Default Light'), data)
        light['bsm_render_temp'] = True
        scene.collection.objects.link(light)
        base = view_rotation if view_rotation is not None else scene.camera.matrix_world.to_quaternion()
        light.rotation_mode = 'QUATERNION'
        light.rotation_quaternion = base @ Euler((math.radians(25), math.radians(-30), 0)).to_quaternion()
        light.hide_viewport = light.hide_select = True
        temps.append(light)
    if temps:
        _render_cleanup.append((scene.name, previous, temps))
        for handlers in (bpy.app.handlers.render_complete, bpy.app.handlers.render_cancel):
            if _render_finished not in handlers:
                handlers.append(_render_finished)
    try:
        result = bpy.ops.render.render('INVOKE_DEFAULT' if not bpy.app.background else 'EXEC_DEFAULT', animation=animation, write_still=write_still)
    except RuntimeError:
        _render_finished()
        if bpy.app.background:
            _remove_render_temps()
        raise
    if bpy.app.background:
        _render_finished()
        _remove_render_temps()
    elif 'CANCELLED' in result:
        _render_finished()
    return result

class BSM_OT_render_view(Active, bpy.types.Operator):
    """Render the active viewport; a scene without lights uses a default light"""
    bl_idname = 'bsm.render_view'
    bl_label = _msg('Render Production')
    bl_options = {'REGISTER'}

    def execute(self, context):
        state = context.window_manager.bsm
        if state.render_mode == 'ACTIVESHADE':
            toggle_activeshade(viewport_override(context)['area'].spaces.active)
            runtime.redraw()
            return {'FINISHED'}
        try:
            return render_active_view(context)
        except RuntimeError as error:
            self.report({'WARNING'}, _dcc_ui_error(error))
            return {'CANCELLED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def _surface_point(context, region, r3d, xy):
    (obj, location, normal) = object_under_mouse(context, region, r3d, xy)
    if location is not None:
        return location
    origin = view3d_utils.region_2d_to_origin_3d(region, r3d, xy)
    direction = view3d_utils.region_2d_to_vector_3d(region, r3d, xy)
    if abs(direction.z) > 1e-06:
        return origin + direction * (-origin.z / direction.z)
    return origin + direction * 10

class BSM_OT_measure_distance(Active, bpy.types.Operator):
    bl_idname = 'bsm.measure_distance'
    bl_label = _msg('Measure Distance')

    def invoke(self, context, event):
        self.start = None
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(_msg('Pick the first point; right-click cancels'))
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            context.workspace.status_text_set(None)
            return {'CANCELLED'}
        if event.type != 'LEFTMOUSE' or event.value != 'PRESS':
            return {'PASS_THROUGH'} if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'MOUSEMOVE'} else {'RUNNING_MODAL'}
        region = context.region
        point = _surface_point(context, region, context.region_data, (event.mouse_x - region.x, event.mouse_y - region.y))
        if self.start is None:
            self.start = point
            context.workspace.status_text_set(_msg('Pick the second point'))
            return {'RUNNING_MODAL'}
        delta = point - self.start
        units = context.scene.unit_settings
        text = lambda v: bpy.utils.units.to_string(units.system, 'LENGTH', v * units.scale_length, precision=3)
        message = _dcc_format('Distance: {0}  Delta X: {1}  Y: {2}  Z: {3}', text(delta.length), text(delta.x), text(delta.y), text(delta.z))
        context.window_manager.bsm.prompt = message
        self.report({'INFO'}, _dcc_ui_text(message))
        context.workspace.status_text_set(None)
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')
CLASSES = (BSM_OT_max_command, BSM_OT_render_view, BSM_OT_max_modifier, BSM_OT_add_constraint, BSM_OT_viewport_shading, BSM_OT_pick_object, BSM_OT_align, BSM_OT_mirror, BSM_OT_array, BSM_OT_group, BSM_OT_rename_objects, BSM_SceneItem, BSM_UL_scene_items, BSM_OT_select_from_scene, BSM_OT_set_action, BSM_OT_manage_sets, BSM_OT_object_properties, BSM_OT_settings_popup, BSM_OT_run_script, BSM_OT_measure_distance)
