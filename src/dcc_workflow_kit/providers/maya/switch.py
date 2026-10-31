# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Maya ⇄ Blender switch (docs/steps/step_60.md 「계획」, step 130).

The extension stays enabled; "Maya mode" is the set of sub-packages ``__init__.MODE``
(keymap, UI, operators, ...). Switching off unregisters them, which puts
back everything they registered (``tests/test_enable_disable.py`` enforces it), switching on
registers them again. Only this module and the preferences stay registered in Blender
mode, so the switch is always there: a small toggle at the right of the top bar, the
add-on preferences, Edit (Blender) / Windows > Settings/Preferences (Maya) menu items that
the menu search finds, and Ctrl+Alt+Shift+M (free in Blender, Industry Compatible and
Maya's factory hotkeys).

Nothing persistent (step 130, docs/user_decisions.md #13): Maya mode writes none of Blender's preferences and
nothing outside the extension's folders, so switching off / disabling / removing needs no snapshot or restore —
unregistering the Maya mode modules takes back everything they registered.

Layout: switching on in a file that has no Maya layout appends the layout workspace of the startup.blend
bundled inside the extension (``app_template.STARTUP``) (named "Maya-style") and activates it; switching off goes back to the previous
workspace and deletes the appended one. Scenes and objects are never touched.
"""
from .i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from .i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import os
import bpy
from . import results
from . import live_refs
WORKSPACE = _dcc_source('Maya-style')
TEMPLATE_WORKSPACE = _dcc_source('General')
PREV_KEY = 'allset_switch_prev'
SHORTCUT = ('M', {'ctrl': True, 'alt': True, 'shift': True})

def _prefs_addon():
    from . import preferences
    return preferences.get()

def is_on():
    try:
        return bool(_prefs_addon().maya_mode)
    except KeyError:
        return False

def _template_blend():
    from .app_template import STARTUP
    return STARTUP

def _window_override(window):
    return {'window': window, 'screen': window.screen}

def is_maya_workspace(ws):
    """A workspace that already is the Maya layout (appended by the switch or a Maya Workflow Kit file)."""
    if ws is None:
        return False
    if PREV_KEY in ws or TEMPLATE_KEY in ws:
        return True
    for screen in ws.screens:
        for area in screen.areas:
            space = area.spaces.active
            if area.type == 'IMAGE_EDITOR' and getattr(space, 'mask', None) is not None and space.mask.name.startswith('.Allset'):
                return True
    return False

def _fit_views(ws, scene):
    """The template views are in cm (Maya unit 0.01 BU): keep them on the same Maya-unit scene."""
    from .operators import units
    ratio = units.maya_unit(scene) / 0.01
    for screen in ws.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type != 'VIEW_3D':
                    continue
                if space.show_region_tool_header and (not space.show_region_header):
                    space.show_region_tool_header = False
                for (key, value) in units.clip(scene).items():
                    setattr(space, key, value)
                space.overlay.grid_scale = units.grid_scale(scene)
                if abs(ratio - 1.0) > 1e-09:
                    for rv3d in (space.region_3d, *space.region_quadviews):
                        rv3d.view_location = rv3d.view_location * ratio
                        rv3d.view_distance *= ratio

def enter_layout(window):
    """Append and activate the Maya layout workspace in ``window`` (unless it already is one)."""
    if window is None or is_maya_workspace(window.workspace):
        return None
    own = [ws for ws in bpy.data.workspaces if is_maya_workspace(ws)]
    own.sort(key=lambda ws: template_of(ws) != TEMPLATE_WORKSPACE)
    own = own[0] if own else None
    if own is not None:
        if window.workspace is not None:
            own[BLENDER_PREV_KEY] = window.workspace.name
        window.workspace = own
        return own
    prev = window.workspace.name
    ws = append_workspace(window, TEMPLATE_WORKSPACE)
    if ws is None:
        return None
    ws[PREV_KEY] = prev
    ws.name = WORKSPACE
    return ws
TEMPLATE_KEY = 'allset_template'

def append_workspace(window, template_name):
    """Append the template workspace ``template_name`` (General, Animation, ... tools/make_startup.MAYA_WORKSPACES) into
    the open file and show it in ``window``: its Status Line / Shelf masks and cm views are set up (step 160, #81)."""
    before = set(bpy.data.workspaces)
    with bpy.context.temp_override(**_window_override(window)):
        bpy.ops.workspace.append_activate(idname=template_name, filepath=_template_blend())
    new = [ws for ws in bpy.data.workspaces if ws not in before]
    if not new:
        return None
    ws = new[0]
    ws[TEMPLATE_KEY] = template_name
    window.workspace = ws
    with bpy.context.temp_override(**_window_override(window)):
        _mark_strips(ws)
        _fit_views(ws, window.scene)
    return ws

def template_of(ws):
    """The template name of a Maya workspace (None: not one of the kit's Maya workspaces)."""
    if ws is None:
        return None
    name = ws.get(TEMPLATE_KEY)
    if isinstance(name, str) and name:
        return name
    return TEMPLATE_WORKSPACE if is_maya_workspace(ws) else None

def reset_workspace(window, ws=None):
    """Maya Windows > Workspaces > Reset Current Workspace (#81): the current Maya workspace is replaced by a fresh
    copy from the bundled template (same name, same way back to Blender's layout); the old one is deleted once the
    window shows the new one. Returns the new workspace (None: not a Maya workspace)."""
    if window is None:
        return None
    old = ws or window.workspace
    template = template_of(old)
    if template is None:
        return None
    (name, prev) = (old.name, old.get(PREV_KEY))
    old.name = name + ' (old)'
    ws = append_workspace(window, template)
    if ws is None:
        old.name = name
        return None
    ws.name = name
    if prev is not None:
        ws[PREV_KEY] = prev
    gone = old.name
    if window.workspace == old:
        _delete_later(window, gone, [])
    else:
        _delete_workspace(window, gone, [])
    return ws
STRIP_MASKS = ('.AllsetStrip', '.AllsetShelf')
MASK_KEY = 'allset_switch_masks'

def _mark_strips(ws):
    """Appending a workspace doesn't bring the Masks its Image Editors point to, and those mark the
    Status Line row and the Shelf row (ui/shelf.is_strip, measured): load them and point the two
    top Image Editors (Status Line above the Shelf) at them again."""
    missing = [m for m in STRIP_MASKS if m not in bpy.data.masks]
    if missing:
        with bpy.data.libraries.load(_template_blend(), link=False) as (src, dst):
            dst.masks = [m for m in missing if m in src.masks]
        ws[MASK_KEY] = missing
    for screen in ws.screens:
        rows = sorted((a for a in screen.areas if a.type == 'IMAGE_EDITOR'), key=lambda a: -a.y)
        for (area, name) in zip(rows, STRIP_MASKS):
            mask = bpy.data.masks.get(name)
            if mask is not None:
                area.spaces.active.mask = mask

def leave_layout(window):
    """Back to the workspace from before ``enter_layout``; the appended one is deleted."""
    if window is None:
        return False
    ws = window.workspace
    if ws is None:
        return False
    if PREV_KEY not in ws:
        return _leave_template_layout(window) if is_maya_workspace(ws) else False
    prev = bpy.data.workspaces.get(ws[PREV_KEY]) or next((w for w in bpy.data.workspaces if w != ws and (not is_maya_workspace(w))), None)
    if prev is None:
        return False
    window.workspace = prev
    added = list(ws.get(MASK_KEY, ()))
    name = ws.name
    if window.workspace == ws:
        _delete_later(window, name, added)
    else:
        pass
    return True
BLENDER_LAYOUT_KEY = 'allset_blender_layout'
BLENDER_PREV_KEY = 'allset_blender_prev'
EMBEDDED_STARTUP = '<startup.blend>'
START_WORKSPACE = {'name': None}

def user_startup_file():
    """The user's own Blender startup file (File > Defaults > Save Startup File), or None. Only read: its workspaces
    come back when a new Maya scene had replaced the user's file (#185)."""
    config = os.environ.get('BLENDER_USER_CONFIG')
    if not config:
        base = os.environ.get('BLENDER_USER_RESOURCES') or bpy.utils.resource_path('USER')
        config = os.path.join(base, 'config')
    path = os.path.join(config, 'startup.blend')
    return path if os.path.isfile(path) else None

def _users_workspace(window):
    """A workspace of the user's already in the file: the one the user had before the Maya layout, else the one
    last brought back, else any workspace that isn't a Maya one (#185)."""
    ws = window.workspace
    names = [ws.get(BLENDER_PREV_KEY)] if ws is not None else []
    names.append(START_WORKSPACE['name'])
    for name in names:
        found = bpy.data.workspaces.get(name) if name else None
        if found is not None and (not is_maya_workspace(found)):
            return found
    marked = [w for w in bpy.data.workspaces if BLENDER_LAYOUT_KEY in w]
    if marked:
        return marked[0]
    return next((w for w in bpy.data.workspaces if not is_maya_workspace(w)), None)

def _append_workspaces(path, names):
    """Append the workspaces ``names`` of ``path`` as data (marked BLENDER_LAYOUT_KEY); returns {name in path:
    workspace}. Not ``workspace.append_activate``: in the UI each of those switches the window to the workspace it
    appended once the event loop runs, after the switch has chosen the one to show (measured, #185)."""
    before = set(bpy.data.workspaces)
    try:
        with bpy.data.libraries.load(path, link=False) as (_src, dst):
            dst.workspaces = list(names)
    except (OSError, RuntimeError) as ex:
        print(_dcc_source('Maya Workflow Kit: workspaces not appended:'), ex)
        return {}
    out = {}
    for (name, ws) in zip(names, dst.workspaces):
        if ws is not None and ws not in before:
            ws[BLENDER_LAYOUT_KEY] = True
            out[name] = ws
    return out

def _users_startup_workspaces(window):
    """The workspaces of the user's own startup file appended to the open file; returns the one to show (the one
    the user's file showed, else Layout, else the first), or None when there is no user startup file."""
    path = user_startup_file()
    if path is None:
        return None
    try:
        with bpy.data.libraries.load(path) as (src, _dst):
            names = list(src.workspaces)
    except (OSError, RuntimeError) as ex:
        print(_dcc_source('Maya Workflow Kit: startup file not read:'), ex)
        return None
    got = _append_workspaces(path, names)
    for name in (START_WORKSPACE['name'], _dcc_source('Layout')):
        if name in got:
            return got[name]
    return next(iter(got.values()), None)

def blender_target(window):
    """The workspace a switch to Blender shows in ``window`` when its Maya layout came with the file (no workspace
    to go back to): the user's workspace if the file has one, else the user's own startup workspaces appended,
    else Blender's factory Layout (#19 step 129, #185)."""
    target = _users_workspace(window) or _users_startup_workspaces(window)
    if target is not None:
        return target
    before = set(bpy.data.workspaces)
    try:
        with bpy.context.temp_override(**_window_override(window)):
            bpy.ops.workspace.append_activate(idname=_dcc_source('Layout'), filepath=EMBEDDED_STARTUP)
    except RuntimeError as ex:
        print(_dcc_source('Maya Workflow Kit: Blender layout not appended:'), ex)
        return None
    new = [w for w in bpy.data.workspaces if w not in before]
    if not new:
        return None
    new[0][BLENDER_LAYOUT_KEY] = True
    return new[0]

def _leave_template_layout(window):
    """The window shows the Maya layout of a Maya Workflow Kit template file (no workspace to go back to): give it
    the user's workspace (``blender_target``), appended once and reused. The Maya one stays in the file for the way
    back (``enter_layout``)."""
    target = blender_target(window)
    if target is None:
        return False
    window.workspace = target
    return True

def _delete_workspace(window, name, added):
    ws = bpy.data.workspaces.get(name)
    if ws is not None and all((w.workspace != ws for w in _windows())):
        bpy.data.batch_remove(ids=[ws])
    for mask_name in added:
        mask = bpy.data.masks.get(mask_name)
        if mask is not None:
            bpy.data.masks.remove(mask)

def _delete_later(window, name, added, tries=40):
    ptr = window.as_pointer()
    left = [tries]

    def tick():
        win = live_refs.window(ptr)
        ws = bpy.data.workspaces.get(name)
        if win is None or ws is None:
            _forget_timer(tick)
            return None
        left[0] -= 1
        if win.workspace == ws and left[0] > 0:
            return 0.05
        _delete_workspace(win, name, added)
        _forget_timer(tick)
        return None
    _timers.append(tick)
    bpy.app.timers.register(tick, first_interval=0.05)
_timers = []

def _forget_timer(fn):
    if fn in _timers:
        _timers.remove(fn)

def _windows():
    wm = bpy.context.window_manager
    return list(wm.windows) if wm is not None else []

def _mode_modules():
    from . import MODE
    return MODE

def register_mode():
    from ...lifecycle import activate
    activate(__name__ + '.mode', [(mod.register, mod.unregister) for mod in _mode_modules()])

def unregister_mode():
    from ...lifecycle import deactivate
    deactivate(__name__ + '.mode')

def _set_mode(on, layout=True):
    """Switch Maya mode on / off now (no restart). The open file's scenes are not touched; Blender's preferences
    are never written (step 130): switching off unregisters the Maya mode modules, which takes back everything
    they registered."""
    prefs = _prefs_addon()
    if on == bool(prefs.maya_mode) and on == _registered[0]:
        return False
    if on:
        prefs.maya_mode = True
        if not _registered[0]:
            register_mode()
            _registered[0] = True
        from . import keymap
        keymap.activate()
        if layout and (not bpy.app.background):
            for window in _windows():
                enter_layout(window)
    else:
        try:
            from .ui import maya_dock
            maya_dock.close_floating()
        except Exception:
            pass
        try:
            from .ui import four_view
            four_view.collapse_all(bpy.context)
        except Exception:
            pass
        if layout:
            for window in _windows():
                leave_layout(window)
        prefs.maya_mode = False
        if _registered[0]:
            unregister_mode()
            _registered[0] = False
    bpy.context.preferences.is_dirty = True
    _redraw()
    return True
_registered = [False]

def _redraw():
    for window in _windows():
        for area in window.screen.areas:
            area.tag_redraw()
_pending = []

def _apply_pending():
    while _pending:
        (on, layout) = _pending.pop(0)
        try:
            set_mode(on, layout=layout)
        except Exception as ex:
            print(_dcc_source('Maya Workflow Kit: switch failed:'), ex)
            import traceback
            traceback.print_exc()
    return None

def request(on, layout=True):
    from ...core import request
    request('MAYA' if on else 'BLENDER', layout=layout)

class ALLSET_OT_switch_mode(bpy.types.Operator):
    """Switch between Maya mode (Maya keymap, layout and menus) and plain Blender.
    Nothing in the open file's scenes changes; Blender's preferences are never changed"""
    bl_translation_context = 'MWK:switch.py:476'
    bl_idname = 'allset.switch_mode'
    bl_label = _zh_native('Switch Maya / Blender', 'MWK:switch.py:476')
    bl_description = _zh_native("Switch between Maya mode (Maya keymap, layout and menus) and plain Blender.\nNothing in the open file's scenes changes; Blender's preferences are never changed", 'MWK:switch.py:476')
    bl_options = {'REGISTER'}
    mode: bpy.props.EnumProperty(name=_zh_native('Mode', 'MWK:switch.py:479'), items=_zh_enum((('TOGGLE', 'Toggle', ''), ('MAYA', 'Maya', ''), ('BLENDER', 'Blender', '')), 'MWK:switch.py:479'), default='TOGGLE', options={'SKIP_SAVE'}, translation_context='MWK:switch.py:479')

    @classmethod
    def description(cls, context, props):
        if props.mode == 'MAYA':
            return _zh('Switch to Maya mode: Maya keymap, layout and menus (Ctrl+Alt+Shift+M)', 'MWK:switch.py:486')
        if props.mode == 'BLENDER':
            return _zh("Switch back to plain Blender: Blender's own keymap, layout and menus (Ctrl+Alt+Shift+M)", 'MWK:switch.py:488')
        return _zh('Switch between Maya mode and plain Blender (Ctrl+Alt+Shift+M)', 'MWK:switch.py:489')

    def execute(self, context):
        on = not is_on() if self.mode == 'TOGGLE' else self.mode == 'MAYA'
        request(on)
        results.result(self, _zh('Maya mode' if on else 'Blender mode', 'MWK:switch.py:494'))
        return {'FINISHED'}

def draw_topbar_switch(self, context):
    """Top bar, right: [Maya | Blender] (both modes)."""
    region = context.region
    if region is None or region.alignment != 'RIGHT':
        return
    on = is_on()
    row = self.layout.row(align=True)
    row.scale_x = 0.85
    sub = row.row(align=True)
    sub.active = on
    sub.operator(ALLSET_OT_switch_mode.bl_idname, text=_zh('Maya', 'MWK:switch.py:509'), emboss=False).mode = 'MAYA'
    row.label(text=_zh('|', 'MWK:switch.py:510'))
    sub = row.row(align=True)
    sub.active = not on
    sub.operator(ALLSET_OT_switch_mode.bl_idname, text=_zh('Blender', 'MWK:switch.py:513'), emboss=False).mode = 'BLENDER'

def draw_edit_menu(self, context):
    """Blender's Edit menu: found by the menu search (F3) in Blender mode."""
    if is_on():
        return
    self.layout.separator()
    self.layout.operator(ALLSET_OT_switch_mode.bl_idname, text=_zh('Switch to Maya Mode', 'MWK:switch.py:521'), icon='EVENT_M').mode = 'MAYA'
classes = (ALLSET_OT_switch_mode,)
_keymaps = []

def _add_shortcut():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new(name=_dcc_source('Window'), space_type='EMPTY', region_type='WINDOW')
    (key, mods) = SHORTCUT
    kmi = km.keymap_items.new(ALLSET_OT_switch_mode.bl_idname, key, 'PRESS', **mods)
    kmi.properties.mode = 'TOGGLE'
    _keymaps.append((km, kmi))

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_edit.append(draw_edit_menu)

def unregister():
    for (km, kmi) in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()
    bpy.types.TOPBAR_MT_edit.remove(draw_edit_menu)
    for fn in (_apply_pending, *_timers):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    _timers.clear()
    _pending.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

def set_mode(on, layout=True):
    from ...core import set_mode
    return set_mode('MAYA' if on else 'BLENDER', layout=layout)
