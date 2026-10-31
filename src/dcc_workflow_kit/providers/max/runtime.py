# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format
'Environment lifecycle. No third-party add-ons are inspected or modified.'
import json
import os
from pathlib import Path
import bpy
from bpy.app.handlers import persistent
_active = False
_pending = None
_previous_workspace = {}
_patched = []
_patched_polls = []
_saved_lock_state = []
_saved_orientation = {}
_msgbus_owner = object()
WORKSPACE_NAME = _msg('Blender Max')
OLD_WORKSPACE_NAMES = (_msg('Blender Studio Max'),)
_splash_before = []
SPLASH_ENV = 'BLENDER_CUSTOM_SPLASH'

def preferences():
    from ...preferences import get
    try:
        return get().max_settings
    except (KeyError, AttributeError):
        return None

def is_active():
    return _active

def apply_splash(on):
    """While Max mode is on, Blender's splash shows the image chosen in the preferences."""
    prefs = preferences()
    path = os.path.abspath(bpy.path.abspath(prefs.splash_image)) if prefs and prefs.splash_image else ''
    if on and path and os.path.isfile(path):
        if not _splash_before:
            _splash_before.append(os.environ.get(SPLASH_ENV))
        os.environ[SPLASH_ENV] = path
    elif _splash_before:
        previous = _splash_before.pop()
        if previous is None:
            os.environ.pop(SPLASH_ENV, None)
        else:
            os.environ[SPLASH_ENV] = previous

def in_workspace(context):
    return _active and context.workspace and context.workspace.get('bsm_workspace', False)

def redraw():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()

def _hex(value, alpha=None):
    color = tuple((int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)))
    return color + (alpha,) if alpha is not None else color

def _theme_paths():
    """Colours from 3ds Max 2027 DefaultUI.clrx (dark theme)."""
    paths = {'properties.space.back': (0.267, 0.267, 0.267), 'properties.space.header': (0.267, 0.267, 0.267, 1), 'image_editor.space.back': (0.267, 0.267, 0.267), 'image_editor.space.header': (0.29, 0.29, 0.29, 1), 'dopesheet_editor.space.back': (0.23, 0.23, 0.23), 'dopesheet_editor.space.header': (0.267, 0.267, 0.267, 1), 'topbar.space.header': (0.25, 0.25, 0.25, 1), 'statusbar.space.back': (0.267, 0.267, 0.267), 'view_3d.space.gradients.background_type': 'SINGLE_COLOR', 'view_3d.space.gradients.high_gradient': _hex('383838'), 'view_3d.space.gradients.gradient': _hex('1a1a1a'), 'view_3d.grid': (0.29, 0.29, 0.29, 1), 'view_3d.object_selected': _hex('00b2ff'), 'view_3d.object_active': _hex('66d1ff'), 'view_3d.vertex_select': _hex('d00000'), 'view_3d.edge_select': _hex('d00000'), 'view_3d.edge_mode_select': _hex('d00000'), 'view_3d.face_select': _hex('d00000', 0.18), 'view_3d.face_mode_select': _hex('d00000', 0.18), 'view_3d.wire_edit': (0, 0, 0), 'view_3d.editmesh_active': (1, 1, 1, 0.5)}
    for widget in ('regular', 'tool', 'toolbar_item', 'radio', 'text', 'option', 'toggle', 'num', 'numslider', 'box', 'menu', 'pulldown', 'menu_back', 'menu_item', 'list_item', 'tab'):
        prefix = _dcc_format('user_interface.wcol_{0}', widget)
        paths[_dcc_format('{0}.inner', prefix)] = (0.35, 0.35, 0.35, 1.0)
        paths[_dcc_format('{0}.inner_sel', prefix)] = _hex('5f8ac1', 1.0)
        paths[_dcc_format('{0}.text', prefix)] = _hex('dcdcdc')
        paths[_dcc_format('{0}.text_sel', prefix)] = (1.0, 1.0, 1.0)
        paths[_dcc_format('{0}.outline', prefix)] = (0.1, 0.1, 0.1, 1.0)
        paths[_dcc_format('{0}.roundness', prefix)] = 0.12
    paths['user_interface.wcol_box.inner'] = (0.28, 0.28, 0.28, 1)
    paths['user_interface.wcol_menu_item.inner_sel'] = _hex('3c82dc', 1.0)
    return paths

def _theme_property(path):
    value = bpy.context.preferences.themes[0]
    parts = path.split('.')
    for part in parts[:-1]:
        value = getattr(value, part)
    return (value, parts[-1])

def _plain(value):
    return value if isinstance(value, (str, int, float, bool)) else list(value)

def apply_theme():
    prefs = preferences()
    if not prefs or not prefs.studio_colors:
        return
    if not prefs.theme_backup:
        backup = {}
        for path in _theme_paths():
            try:
                (owner, attr) = _theme_property(path)
                backup[path] = _plain(getattr(owner, attr))
            except (AttributeError, TypeError):
                continue
        prefs.theme_backup = json.dumps(backup)
    for (path, value) in _theme_paths().items():
        try:
            (owner, attr) = _theme_property(path)
            setattr(owner, attr, value)
        except (AttributeError, TypeError, ValueError):
            continue

def restore_theme():
    prefs = preferences()
    if not prefs or not prefs.theme_backup:
        return
    try:
        backup = json.loads(prefs.theme_backup)
        for (path, value) in backup.items():
            try:
                (owner, attr) = _theme_property(path)
                setattr(owner, attr, value)
            except (AttributeError, TypeError, ValueError):
                continue
    except (TypeError, ValueError):
        print(_msg('Blender Max: invalid theme recovery data; snapshot retained'))
        return
    prefs.theme_backup = ''

def _patch_draw(cls, replacement):
    original = cls.draw

    def draw(self, context):
        if in_workspace(context):
            replacement(self, context)
        else:
            original(self, context)
    _patched.append((cls, original, draw))
    cls.draw = draw

def _install_draws():
    from . import ui, chrome
    _patch_draw(bpy.types.VIEW3D_HT_header, ui.draw_view_header)
    _patch_draw(bpy.types.TOPBAR_MT_editor_menus, ui.draw_menus)
    _patch_draw(bpy.types.DOPESHEET_HT_header, ui.draw_time_header)
    _patch_draw(bpy.types.TOPBAR_HT_upper_bar, chrome.draw_topbar)
    _patch_draw(bpy.types.IMAGE_HT_header, chrome.draw_image_header)
    _patch_draw(bpy.types.PROPERTIES_HT_header, chrome.draw_properties_header)
    _patch_draw(bpy.types.STATUSBAR_HT_header, chrome.draw_status)
    for name in (_msg('VIEW3D_PT_tools_active'), _msg('PROPERTIES_PT_navigation_bar'), _msg('WORKSPACE_PT_main'), _msg('WORKSPACE_PT_addons')):
        cls = getattr(bpy.types, name, None)
        if cls and hasattr(cls, 'draw'):
            _patch_draw(cls, lambda self, context: None)
    from bl_ui import properties_scene
    panels = [cls for cls in properties_scene.classes if issubclass(cls, bpy.types.Panel) and getattr(bpy.types, cls.__name__, None) is cls]
    for cls in panels:
        own = cls.__dict__.get('poll')
        original = getattr(cls, 'poll', None)

        def make_poll(original_poll):

            def poll(panel_cls, context):
                if in_workspace(context) and context.workspace.get('bsm_primary_workspace'):
                    return False
                return original_poll(context) if original_poll else True
            return poll
        replacement = classmethod(make_poll(original))
        _patched_polls.append((cls, own, replacement))
    for cls in reversed(panels):
        bpy.utils.unregister_class(cls)
    for (cls, own, replacement) in _patched_polls:
        cls.poll = replacement
        bpy.utils.register_class(cls)

def _restore_draws():
    for (cls, original, ours) in reversed(_patched_polls):
        if getattr(bpy.types, cls.__name__, None) is cls:
            bpy.utils.unregister_class(cls)
    for (cls, original, ours) in _patched_polls:
        if cls.__dict__.get('poll') is ours:
            if original is None:
                delattr(cls, 'poll')
            else:
                cls.poll = original
        if getattr(bpy.types, cls.__name__, None) is not cls:
            bpy.utils.register_class(cls)
    _patched_polls.clear()
    for (cls, original, ours) in reversed(_patched):
        if cls.draw is ours:
            cls.draw = original
    _patched.clear()
REFERENCE = {'SCREEN': 'VIEW', 'WORLD': 'GLOBAL', 'PARENT': 'PARENT', 'LOCAL': 'LOCAL', 'GIMBAL': 'GIMBAL', 'GRID': 'GLOBAL', 'WORKING': 'CURSOR', 'LOCAL_ALIGNED': 'NORMAL'}

def sync_reference(context, region=None):
    if not _active or not hasattr(context.window_manager, 'bsm'):
        return
    state = context.window_manager.bsm
    slot = context.scene.transform_orientation_slots[0]
    choice = state.ref_coord
    if choice == 'VIEW':
        r3d = region.data if region is not None and region.type == 'WINDOW' else None
        if r3d is None:
            try:
                from .operators import viewport_override
                r3d = viewport_override(context)['region'].data
            except (RuntimeError, AttributeError):
                return
        if r3d is None:
            return
        from .operators import view_name
        side = r3d.view_perspective == 'ORTHO' and view_name(r3d) in {_msg('Top'), _msg('Bottom'), _msg('Front'), _msg('Back'), _msg('Left'), _msg('Right')}
        target = 'VIEW' if side else 'GLOBAL'
    elif choice == 'PICK':
        obj = bpy.data.objects.get(state.ref_pick)
        if obj is None:
            return
        name = _dcc_format('Pick: {0}', obj.name)
        if slot.type != name:
            existing = context.scene.transform_orientation_slots[0]
            try:
                existing.type = name
            except TypeError:
                from .operators import viewport_override
                override = viewport_override(context)
                active = context.view_layer.objects.active
                with context.temp_override(**override, active_object=obj, object=obj):
                    bpy.ops.transform.create_orientation(name=name, use=True, overwrite=True)
                context.view_layer.objects.active = active
        return
    else:
        target = REFERENCE.get(choice, 'GLOBAL')
    if slot.type != target:
        slot.type = target

def apply_selection_filter(context):
    state = context.window_manager.bsm
    allowed = {'ALL': None, 'GEOMETRY': {'mesh', 'surf', 'meta', 'font', 'curves', 'pointcloud', 'volume'}, 'SHAPES': {'curve', 'font'}, 'LIGHTS': {'light'}, 'CAMERAS': {'camera'}, 'HELPERS': {'empty'}, 'WARPS': {'empty'}, 'BONE': {'armature'}}[state.selection_filter]
    for space in _studio_spaces(context):
        for prop in space.bl_rna.properties:
            name = prop.identifier
            if name.startswith('show_object_select_'):
                setattr(space, name, allowed is None or name[len('show_object_select_'):] in allowed)

def apply_manipulate(context):
    on = context.window_manager.bsm.manipulate
    for space in _studio_spaces(context):
        for attr in ('show_gizmo_light_size', 'show_gizmo_light_look_at', 'show_gizmo_camera_lens', 'show_gizmo_camera_dof_distance', 'show_gizmo_empty_image', 'show_gizmo_empty_force_field'):
            if hasattr(space, attr):
                setattr(space, attr, on)

def _studio_spaces(context):
    for workspace in bpy.data.workspaces:
        if not workspace.get('bsm_primary_workspace'):
            continue
        for screen in workspace.screens:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    yield area.spaces.active

def on_state(context, name):
    if name == 'keyboard_override':
        from . import keymap
        keymap.set_enabled(context.window_manager.bsm.keyboard_override)
    elif name == 'manipulate':
        apply_manipulate(context)
    elif name == 'selection_filter':
        apply_selection_filter(context)
    elif name == 'ref_coord':
        sync_reference(context)
    elif name == 'set_key_mode' and context.window_manager.bsm.set_key_mode:
        context.scene.tool_settings.use_keyframe_insert_auto = False
    redraw()

def _object_mode_changed():
    """Entering Edit Mode on a primitive converts it to Editable Poly, as Max requires."""
    context = bpy.context
    obj = context.view_layer.objects.active if context.view_layer else None
    if not _active or obj is None or obj.mode != 'EDIT' or (obj.type != 'MESH'):
        if obj is not None and obj.mode == 'OBJECT' and hasattr(context.window_manager, 'bsm'):
            context.window_manager.bsm.component = 0
        return
    prim = getattr(obj, 'bsm_prim', None)
    if prim is not None and prim.kind:
        from . import params
        params.collapse(obj)
        context.window_manager.bsm.prompt = _dcc_format('{0} converted to Editable Poly', obj.name)
    level = {(True, False, False): 1, (False, True, False): 2, (False, False, True): 4}.get(tuple(context.tool_settings.mesh_select_mode))
    state = context.window_manager.bsm
    if state.component == 0 and level:
        state.component = level
    redraw()

def _active_changed():
    if not _active:
        return
    from .commands import promote_groups
    try:
        promote_groups(bpy.context)
    except (AttributeError, ReferenceError):
        pass

def subscribe():
    bpy.msgbus.clear_by_owner(_msgbus_owner)
    bpy.msgbus.subscribe_rna(key=(bpy.types.Object, 'mode'), owner=_msgbus_owner, args=(), notify=_object_mode_changed)
    bpy.msgbus.subscribe_rna(key=(bpy.types.LayerObjects, 'active'), owner=_msgbus_owner, args=(), notify=_active_changed)

def unsubscribe():
    bpy.msgbus.clear_by_owner(_msgbus_owner)
FACTORY_OBJECTS = {_msg('Cube'): ('MESH', (0, 0, 0), (0, 0, 0)), _msg('Camera'): ('CAMERA', (7.358891, -6.925791, 4.958309), (1.109319, 0, 0.814928)), _msg('Light'): ('LIGHT', (4.076245, 1.005454, 5.903862), (0.650328, 0.055217, 1.866391))}

def _close(values, expected):
    return all((abs(a - b) < 0.0001 for (a, b) in zip(values, expected)))

def _factory_objects(scene):
    """Blender's untouched startup Cube, Camera and Light, or None if the scene differs.

    bpy.data.is_dirty is already set on startup (even in a factory process), so the
    objects themselves are compared with the factory values instead."""
    objects = {o.name: o for o in scene.objects}
    if set(objects) != set(FACTORY_OBJECTS):
        return None
    for (name, (kind, location, rotation)) in FACTORY_OBJECTS.items():
        obj = objects[name]
        if obj.type != kind or obj.parent or obj.modifiers or obj.constraints or obj.animation_data or (obj.rotation_mode != 'XYZ') or (not _close(obj.scale, (1, 1, 1))) or (not _close(obj.location, location)) or (not _close(obj.rotation_euler, rotation)):
            return None
    (cube, camera, light) = (objects[_msg('Cube')].data, objects[_msg('Camera')].data, objects[_msg('Light')].data)
    if len(cube.vertices) != 8 or any((not _close(map(abs, v.co), (1, 1, 1)) for v in cube.vertices)):
        return None
    if camera.type != 'PERSP' or abs(camera.lens - 50) > 0.0001:
        return None
    if light.type != 'POINT' or abs(light.energy - 1000) > 0.001 or (not _close(light.color, (1, 1, 1))):
        return None
    return list(objects.values())

def clear_factory_scene(scene):
    """Max opens on an empty scene: remove the startup Cube, Camera and Light and their data."""
    objects = _factory_objects(scene)
    if not objects:
        return False
    for obj in objects:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            for collection in (bpy.data.meshes, bpy.data.cameras, bpy.data.lights):
                if data.name in collection and collection[data.name] == data:
                    collection.remove(data)
                    break
    material = bpy.data.materials.get(_msg('Material'))
    if material is not None and material.users == 0:
        bpy.data.materials.remove(material)
    return True

def apply_scene_defaults(context):
    """Workflow changes preserve scene data; scene defaults belong to explicit New commands."""
    return None

def enter_workspace(window):
    if window and (window.workspace.get('bsm_editor_kind') or window.workspace.get('bsm_native_kind')):
        if window.workspace.get('bsm_editor_kind'):
            from . import editor_host
            editor_host.prepare(window)
        return
    if not window or (window.workspace.get('bsm_workspace') and window.workspace.get('bsm_layout_version', 0) >= 2):
        if window:
            from . import chrome
            chrome.prepare_workspace(window)
        return
    _previous_workspace[window.as_pointer()] = window.workspace.name
    target = next((w for w in bpy.data.workspaces if w.get('bsm_primary_workspace') and w.get('bsm_layout_version', 0) >= 2), None)
    if target is None:
        before = set(bpy.data.workspaces)
        with bpy.context.temp_override(window=window):
            bpy.ops.workspace.append_activate(idname=_msg('BSM_Layout'), filepath=str(Path(__file__).with_name('workspace.blend')))
        target = next((w for w in bpy.data.workspaces if w not in before and w.name.startswith(_msg('BSM_Layout'))), None)
        if target is None:
            raise RuntimeError(_msg('The Blender Max workspace could not be appended'))
        target.name = WORKSPACE_NAME
        target['bsm_workspace'] = True
        target['bsm_primary_workspace'] = True
    window.workspace = target
    attempts = [0]

    def prepare():
        attempts[0] += 1
        if not _active or attempts[0] > 40:
            return None
        if window.workspace != target or window.screen not in list(target.screens):
            return 0.05
        from . import chrome
        chrome.prepare_workspace(window)
        return None
    bpy.app.timers.register(prepare, first_interval=0.1)

def leave_workspace(window):
    if not window or not window.workspace.get('bsm_workspace'):
        return
    previous = _previous_workspace.get(window.as_pointer(), '')
    target = bpy.data.workspaces.get(previous)
    if not target or target.get('bsm_workspace'):
        target = bpy.data.workspaces.get(_msg('Layout')) or next((w for w in bpy.data.workspaces if not w.get('bsm_workspace')), None)
    if target:
        window.workspace = target
    else:
        with bpy.context.temp_override(window=window):
            bpy.ops.workspace.append_activate(idname=_msg('Layout'), filepath='<startup.blend>')

def _remember_orientation():
    _saved_orientation.clear()
    for scene in bpy.data.scenes:
        _saved_orientation[scene.name] = (scene.transform_orientation_slots[0].type, scene.tool_settings.transform_pivot_point)

def _restore_orientation():
    for (name, (orientation, pivot)) in _saved_orientation.items():
        scene = bpy.data.scenes.get(name)
        if scene is None:
            continue
        try:
            scene.transform_orientation_slots[0].type = orientation
        except TypeError:
            scene.transform_orientation_slots[0].type = 'GLOBAL'
    _saved_orientation.clear()

def _set_active(on, layout=True):
    global _active
    on = bool(on)
    if on == _active:
        if on and layout and (not bpy.app.background):
            from . import chrome
            for window in bpy.context.window_manager.windows:
                enter_workspace(window)
            chrome.register_mode()
        return
    from . import keymap, chrome
    prefs = preferences()
    if on:
        _active = True
        try:
            _install_draws()
            keymap.register_mode()
            apply_theme()
            _remember_orientation()
            subscribe()
            apply_scene_defaults(bpy.context)
            if layout:
                for window in bpy.context.window_manager.windows:
                    enter_workspace(window)
            chrome.register_mode()
            if hasattr(bpy.context.window_manager, 'bsm'):
                keymap.set_enabled(bpy.context.window_manager.bsm.keyboard_override)
                sync_reference(bpy.context)
            apply_splash(True)
        except Exception:
            chrome.unregister_mode()
            keymap.unregister_mode()
            unsubscribe()
            _restore_draws()
            restore_theme()
            apply_splash(False)
            _active = False
            raise
    else:
        chrome.unregister_mode()
        keymap.unregister_mode()
        unsubscribe()
        _restore_draws()
        restore_theme()
        _restore_orientation()
        apply_splash(False)
        _active = False
        if not bpy.app.background:
            from . import max_gizmo, commands
            max_gizmo.restore_blender_tools(bpy.context)
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D' and area.spaces.active.as_pointer() in commands._activeshade:
                        commands.set_activeshade(area.spaces.active, False)
        if layout:
            for window in bpy.context.window_manager.windows:
                leave_workspace(window)
        recover_selection_lock()
    if prefs:
        prefs.enabled_mode = on
    redraw()

def _apply_pending():
    global _pending
    on = _pending
    _pending = None
    if on is not None:
        try:
            set_active(on)
        except Exception as error:
            print(_msg('Blender Max switch failed:'), error)
            import traceback
            traceback.print_exc()
    return None

def request(on):
    from ...core import request
    request('MAX' if on else 'BLENDER')

@persistent
def load_post(_):
    from .surfaces import reset_fonts
    from .commands import _activeshade
    from .operators import _quad_memory
    reset_fonts()
    _activeshade.clear()
    _quad_memory.clear()
    recover_selection_lock()
    if _active:
        subscribe()

        def activate():
            if _active and (not bpy.app.background):
                from . import chrome
                chrome.restart_events()
                apply_scene_defaults(bpy.context)
                for window in bpy.context.window_manager.windows:
                    enter_workspace(window)
                chrome.register_mode()
            elif _active:
                apply_scene_defaults(bpy.context)
            return None
        bpy.app.timers.register(activate, first_interval=0.25)

def recover_selection_lock():
    if not hasattr(bpy.data, 'objects'):
        return
    for obj in bpy.data.objects:
        if '_bsm_selectable_before_lock' in obj:
            obj.hide_select = bool(obj['_bsm_selectable_before_lock'])
            del obj['_bsm_selectable_before_lock']
    if hasattr(bpy.context, 'window_manager') and hasattr(bpy.context.window_manager, 'bsm'):
        bpy.context.window_manager.bsm.selection_locked = False

@persistent
def save_pre(_):
    _saved_lock_state.clear()
    for obj in bpy.data.objects:
        if '_bsm_selectable_before_lock' in obj:
            previous = bool(obj['_bsm_selectable_before_lock'])
            _saved_lock_state.append((obj, previous))
            obj.hide_select = previous
            del obj['_bsm_selectable_before_lock']

@persistent
def save_post(_):
    if _active:
        for (obj, previous) in _saved_lock_state:
            try:
                obj['_bsm_selectable_before_lock'] = previous
                obj.hide_select = True
            except ReferenceError:
                continue
    _saved_lock_state.clear()

def recover_startup():
    recover_selection_lock()
    return None

def register():
    restore_theme()
    bpy.app.timers.register(recover_startup, first_interval=0.0)
    if load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_post)
    bpy.app.handlers.save_pre.append(save_pre)
    bpy.app.handlers.save_post.append(save_post)
    if hasattr(bpy.app.handlers, 'save_post_fail'):
        bpy.app.handlers.save_post_fail.append(save_post)
    prefs = preferences()
    if prefs and prefs.enabled_mode:
        apply_splash(True)
        request(True)
        if not bpy.app.background:
            bpy.app.timers.register(reconcile_startup, first_interval=6.0)
            if bpy.context.preferences.view.show_splash:
                _splash_attempts[0] = 0
                bpy.app.timers.register(startup_splash, first_interval=0.5)
_splash_attempts = [0]

def startup_splash():
    """Blender opens its splash on the startup screen and entering the Studio workspace
    closes it, so open it again once the Studio screen is in place."""
    window = bpy.context.window_manager.windows[0] if bpy.context.window_manager.windows else None
    _splash_attempts[0] += 1
    if not _active or bpy.data.filepath or window is None or (_splash_attempts[0] > 40):
        return None
    if not window.workspace.get('bsm_primary_workspace') or window.screen not in list(window.workspace.screens):
        return 0.1
    with bpy.context.temp_override(window=window, screen=window.screen):
        bpy.ops.wm.splash('INVOKE_DEFAULT')
    return None

def reconcile_startup():
    return None

def unregister():
    global _pending
    _pending = None
    if bpy.app.timers.is_registered(_apply_pending):
        bpy.app.timers.unregister(_apply_pending)
    if bpy.app.timers.is_registered(recover_startup):
        bpy.app.timers.unregister(recover_startup)
    if bpy.app.timers.is_registered(reconcile_startup):
        bpy.app.timers.unregister(reconcile_startup)
    if bpy.app.timers.is_registered(startup_splash):
        bpy.app.timers.unregister(startup_splash)
    if load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post)
    for (collection, fn) in ((bpy.app.handlers.save_pre, save_pre), (bpy.app.handlers.save_post, save_post)):
        if fn in collection:
            collection.remove(fn)
    if hasattr(bpy.app.handlers, 'save_post_fail') and save_post in bpy.app.handlers.save_post_fail:
        bpy.app.handlers.save_post_fail.remove(save_post)
    if _active:
        _set_active(False)
    else:
        restore_theme()
        recover_selection_lock()
    apply_splash(False)

def set_active(on, layout=True):
    from ...core import set_mode
    return set_mode('MAX' if on else 'BLENDER', layout=layout)
