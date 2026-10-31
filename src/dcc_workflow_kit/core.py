# SPDX-License-Identifier: GPL-3.0-or-later
"""Single owner of both mutually exclusive interactive workflows."""
import traceback
import bpy
from bpy.app.handlers import persistent
from .preferences import get
from .providers import max as max_provider, maya

_current = 'BLENDER'
_busy = False
_pending = None
_base_workspaces = {}
_startup_tries = 0


def current():
    return _current


def busy():
    return _busy or _pending is not None


def _windows():
    wm = bpy.context.window_manager
    return list(wm.windows) if wm else []


def _foreign(ws):
    return ws is not None and (ws.get('bsm_workspace') or ws.get('bsm_editor_kind') or
                               ws.get('bsm_native_kind') or maya.switch.is_maya_workspace(ws))


def _remember_layouts():
    for window in _windows():
        if window.workspace and not _foreign(window.workspace):
            _base_workspaces[window.as_pointer()] = window.workspace.name


def _return_layouts():
    if bpy.app.background:
        return
    for window in _windows():
        target = bpy.data.workspaces.get(_base_workspaces.get(window.as_pointer(), ''))
        if target is None or _foreign(target):
            target = next((ws for ws in bpy.data.workspaces if not _foreign(ws)), None)
        if target is None:
            with bpy.context.temp_override(window=window):
                bpy.ops.workspace.append_activate(idname='Layout', filepath='<startup.blend>')
        else:
            window.workspace = target


def _exit(layout=True):
    global _current
    errors = []
    # Inspect backend state too: partially initialized backends must also be cleaned up.
    if maya.switch._registered[0] or get().maya_settings.maya_mode:
        try:
            maya.switch._set_mode(False, layout=False)
        except Exception as error:
            errors.append(error)
        finally:
            get().maya_settings.maya_mode = False
            maya.switch._registered[0] = False
    if max_provider.runtime.is_active():
        try:
            max_provider.runtime._set_active(False, layout=False)
        except Exception as error:
            errors.append(error)
    max_provider.max_gizmo.unregister_tool()
    _current = 'BLENDER'
    if layout:
        _return_layouts()
    if errors:
        raise RuntimeError('; '.join(map(str, errors)))


def _enter(target, layout=True):
    global _current
    if target == 'MAX':
        max_provider.max_gizmo.register_tool()
        max_provider.runtime._set_active(True, layout=layout and not bpy.app.background)
    elif target == 'MAYA':
        maya.switch._set_mode(True, layout=False)
        if layout and not bpy.app.background:
            for window in _windows():
                maya.switch.enter_layout(window)
    _current = target


def _validate(target):
    if target not in {'BLENDER', 'MAX', 'MAYA'}:
        raise ValueError(f'Unknown workflow: {target}')
    if target != 'BLENDER' and target != get().profile:
        raise ValueError('Choose this workflow pair in DCC Workflow Kit Preferences first.')


def _failed(error):
    global _current
    traceback.print_exc()
    cleanup = ''
    try:
        _exit()
    except Exception as ex:
        cleanup = f'\nCleanup: {ex}'
    _current = 'BLENDER'
    get().last_error = str(error) + cleanup
    _redraw()


def set_mode(target, layout=True):
    """Synchronous entry for isolated tests and explicit legacy Python calls."""
    global _busy
    _validate(target)
    if _busy:
        raise RuntimeError('A workflow switch is already in progress.')
    if target == _current:
        return False
    _busy = True
    try:
        _remember_layouts()
        _exit(layout=layout)
        _enter(target, layout=layout)
        get().last_error = ''
        return True
    except Exception as error:
        _failed(error)
        raise
    finally:
        _busy = False
        _redraw()
        _redraw_after_workspace_change()


def request(target, layout=True):
    """Coalesce clicks, leave the old workspace, yield one event loop, then enter."""
    global _pending
    _validate(target)
    _pending = (target, layout)
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.01)
    _redraw()


def _tick():
    global _busy, _pending
    if _pending is None:
        _busy = False
        return None
    if not _busy:
        _busy = True
        try:
            _remember_layouts()
            _exit(layout=_pending[1])
        except Exception as error:
            _pending = None
            _busy = False
            _failed(error)
            return None
        return 0.15
    target, layout = _pending
    _pending = None
    try:
        _validate(target)
        _enter(target, layout=layout)
        get().last_error = ''
    except Exception as error:
        _failed(error)
    finally:
        _busy = False
        _redraw()
        _redraw_after_workspace_change()
    return 0.01 if _pending is not None else None


def _redraw():
    from .ui import tag_global_areas
    tag_global_areas()
    for window in _windows():
        for area in window.screen.areas:
            area.tag_redraw()


def _redraw_once():
    _redraw()
    return None


def _redraw_after_workspace_change():
    # window.workspace is applied by Blender on the next event loop. Tag the
    # resulting screen too, otherwise its top bar may keep a cached busy state.
    if not bpy.app.timers.is_registered(_redraw_once):
        bpy.app.timers.register(_redraw_once, first_interval=0.2)


@persistent
def _load_post(_):
    _base_workspaces.clear()
    if _current != 'BLENDER':
        request(_current)


def _startup():
    global _startup_tries
    if bpy.app.background:
        return None
    _startup_tries += 1
    if not _windows():
        return 0.1 if _startup_tries < 100 else None
    prefs = get()
    if prefs.startup == 'SELECTED':
        request(prefs.profile)
    return None


def register():
    global _startup_tries
    _startup_tries = 0
    bpy.app.handlers.load_post.append(_load_post)
    bpy.app.timers.register(_startup, first_interval=0.2)


def unregister():
    global _pending, _busy
    _pending = None
    for fn in (_tick, _startup, _redraw_once):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    try:
        _exit()
    finally:
        _busy = False
        _base_workspaces.clear()
