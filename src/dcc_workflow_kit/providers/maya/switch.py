# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya ⇄ Blender switch.

The extension stays enabled; "Maya mode" is the set of sub-packages ``__init__.MODE``
(keymap, UI, operators, ...). Switching off unregisters them, which puts
back everything they registered (``tests/test_enable_disable.py`` enforces it), switching on
registers them again. Only this module and the preferences stay registered in Blender
mode, so the switch is always there: a small toggle at the right of the top bar, the
add-on preferences, Edit (Blender) / Windows > Settings/Preferences (Maya) menu items that
the menu search finds, and Ctrl+Alt+Shift+M (free in Blender, Industry Compatible and
Maya's standard hotkeys).

Nothing persistent: Maya mode writes none of Blender's preferences and
nothing outside the extension's folders, so switching off / disabling / removing needs no snapshot or restore —
unregistering the Maya mode modules takes back everything they registered.

Layout: switching on in a file that has no Maya layout appends the layout workspace of the startup.blend
bundled inside the extension (``app_template.STARTUP``) (named "Maya-style") and activates it; switching off goes back to the previous
workspace and deletes the appended one. Scenes and objects are never touched.

Code: ``switch_layout`` (the Maya layout workspaces: their keys, append, reset, delete); this module keeps the
mode switch, the way back to Blender's workspaces and register / unregister. The names used elsewhere are
importable from here too.
"""

import os

import bpy

from . import results
from . import live_refs
from . import i18n
from . import switch_keep
# the Maya layout workspaces, also read through this module by other UI, tools and the tests
from .switch_layout import (BLENDER_LAYOUT_KEY, BLENDER_PREV_KEY, MASK_KEY, PREV_KEY, STRIP_MASKS,  # noqa: F401
                            TEMPLATE_KEY, TEMPLATE_WORKSPACE, USER_KEY, USER_UNIT_KEY, WORKSPACE, _delete_later,
                            _delete_workspace, _fit_views, _forget_timer, _linked_from, _mark_strips,
                            _prepare_layout, _template_blend, _timers, _window_override, _windows,
                            append_workspace, drop_workspace, enter_layout, forget_copies, is_copy, keep_panels,
                            is_maya_workspace, mark_own, reset_workspace, template_of)


SHORTCUT = ('M', {"ctrl": True, "alt": True, "shift": True})


# --- mode on / off ------------------------------------------------------------------------------

def _prefs_addon():
    from . import preferences
    return preferences.get()


def is_on():
    try:
        return bool(_prefs_addon().maya_mode)
    except KeyError:
        return False


def leave_layout(window):
    """Return to Blender and keep the Maya workspace for reuse."""
    if window is None:
        return False
    forget_copies()
    ws = window.workspace
    if ws is None:
        return False
    if PREV_KEY not in ws:
        if is_maya_workspace(ws):
            return _leave_template_layout(window)
        return False
    chain, cur = [], ws
    while cur is not None and PREV_KEY in cur and cur not in chain:
        chain.append(cur)
        cur = bpy.data.workspaces.get(cur[PREV_KEY])
    appended = [w for w in bpy.data.workspaces if PREV_KEY in w]
    prev = cur if cur is not None and not is_maya_workspace(cur) else next(
        (w for w in bpy.data.workspaces if w not in appended and not is_maya_workspace(w)), None)
    if prev is None:
        if not any(is_maya_workspace(w) and w not in appended for w in bpy.data.workspaces):
            return False
        prev = blender_target(window)          # only Maya workspaces besides: the user's / Blender's own
        if prev is None:
            return False
    window.workspace = prev
    return True


def _drop_unshown(window):
    """The window shows a workspace that isn't a Maya one (another add-on's layout made from the Maya layout, #423):
    the Maya workspaces the switch appended that no window shows are deleted all the same."""
    shown = {w.workspace for w in _windows()}
    appended = [w for w in bpy.data.workspaces if PREV_KEY in w and w not in shown]
    added = []
    for w in appended:
        added += [m for m in w.get(MASK_KEY, ()) if m not in added]
    for w in appended:
        _delete_workspace(window, w.name, added if w == appended[-1] else [])


# Blender's embedded factory startup file: what Add Workspace > General appends from (workspace_edit.cc
# workspace_append_button, BLO_EMBEDDED_STARTUP_BLEND)
EMBEDDED_STARTUP = "<startup.blend>"
# The workspace the user's own file showed when a new Maya scene replaced it (first_start.new_maya_scene).
START_WORKSPACE = {"name": None}


def user_startup_file():
    """The user's own Blender startup file (File > Defaults > Save Startup File), or None. Only read: its workspaces
    come back when a new Maya scene had replaced the user's file (#185)."""
    config = os.environ.get("BLENDER_USER_CONFIG")
    if not config:
        base = os.environ.get("BLENDER_USER_RESOURCES") or bpy.utils.resource_path('USER')
        config = os.path.join(base, "config")
    path = os.path.join(config, "startup.blend")
    return path if os.path.isfile(path) else None


def _users_workspace(window):
    """A workspace of the user's already in the file: the one the user had before the Maya layout, else the one
    last brought back, else any workspace that isn't a Maya one (#185)."""
    ws = window.workspace
    names = [ws.get(BLENDER_PREV_KEY)] if ws is not None else []
    names.append(START_WORKSPACE["name"])
    for name in names:
        found = bpy.data.workspaces.get(name) if name else None
        if found is not None and not is_maya_workspace(found):
            return found
    marked = [w for w in bpy.data.workspaces if BLENDER_LAYOUT_KEY in w]
    if marked:
        return marked[0]
    return next((w for w in bpy.data.workspaces if not is_maya_workspace(w)), None)


def _append_workspaces(path, names):
    """Append the workspaces ``names`` of ``path`` as data (marked BLENDER_LAYOUT_KEY); returns {name in path:
    workspace}. Not ``workspace.append_activate``: in the UI each of those switches the window to the workspace it
    appended once the event loop runs, after the switch has chosen the one to show (#185)."""
    before = set(bpy.data.workspaces)
    try:
        with bpy.data.libraries.load(path, link=False) as (_src, dst):
            dst.workspaces = list(names)
    except (OSError, RuntimeError) as ex:
        print("Maya Workflow Kit: workspaces not appended:", ex)
        return {}
    out = {}
    for name, ws in zip(names, dst.workspaces):
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
        print("Maya Workflow Kit: startup file not read:", ex)
        return None
    got = _append_workspaces(path, names)
    for name in (START_WORKSPACE["name"], "Layout"):
        if name in got:
            return got[name]
    return next(iter(got.values()), None)


# Blender's factory workspaces (the embedded startup file, Blender 5.x)
BLENDER_WORKSPACES = ("Layout", "Modeling", "Sculpting", "UV Editing", "Texture Paint", "Shading", "Animation",
                      "Rendering", "Compositing", "Geometry Nodes", "Scripting")
MAYA_SUFFIX = " (Maya)"
MAYA_NAME_KEY = "allset_maya_name"      # a Maya workspace renamed in Blender mode: its name in the template


def _startup_names(path):
    try:
        with bpy.data.libraries.load(path) as (src, _dst):
            return list(src.workspaces)
    except (OSError, RuntimeError):
        return []


def _blender_names():
    """Workspace names a switch to Blender may show as Blender's own: the user's startup file's, else Blender's
    factory ones."""
    path = user_startup_file()
    names = _startup_names(path) if path is not None else []
    return names or list(BLENDER_WORKSPACES)


def _rename_maya_clashes():
    """A Maya Workflow Kit file carries Maya workspaces with Blender's names (Sculpting, UV Editing, Animation): in
    Blender mode those tabs would open a Maya layout with Blender's tools (#282). Rename them "<name> (Maya)" (the
    Maya menus find them by their template, not their name). Returns the freed names."""
    names = set(_blender_names())
    renamed = []
    for ws in list(bpy.data.workspaces):
        if ws.name in names and is_maya_workspace(ws) and ws.library is None:
            ws[MAYA_NAME_KEY] = ws.name
            renamed.append(ws.name)
            ws.name = ws.name + MAYA_SUFFIX
    return renamed


def _append_counterparts(window, names):
    """Blender's own workspace for each freed name the file lacks: the user's startup file's, else Blender's
    factory one."""
    names = [n for n in names if bpy.data.workspaces.get(n) is None]
    path = user_startup_file()
    if path is not None and names:
        have = set(_startup_names(path))
        for ws in _append_workspaces(path, [n for n in names if n in have]).values():
            del ws[BLENDER_LAYOUT_KEY]          # not a workspace to go back to (_users_workspace)
    for name in [n for n in names if bpy.data.workspaces.get(n) is None]:
        try:
            with bpy.context.temp_override(**_window_override(window)):
                bpy.ops.workspace.append_activate(idname=name, filepath=EMBEDDED_STARTUP)
        except RuntimeError as ex:
            print("Maya Workflow Kit: Blender workspace not appended:", ex)


def _drop_new_scene_layouts(window):
    """A new Maya scene that was never saved: its Maya workspaces leave the file (#307), like the ones a switch
    appends to a Blender file, so Blender mode shows Blender's tabs only. Switching back to Maya brings the Maya layout
    again. A saved file keeps its Maya workspaces. The one ``window`` shows goes once the window shows another; one
    another window shows stays for that window's own switch. Returns the names dropped."""
    if bpy.data.filepath:
        return []
    forget_copies()
    shown = {w.workspace for w in _windows() if w != window}
    gone = []
    for ws in list(bpy.data.workspaces):
        if ws.library is not None or not is_maya_workspace(ws) or ws in shown:
            continue
        gone.append(ws.name)
        if ws == window.workspace:
            _delete_later(window, ws.name, [])
        else:
            bpy.data.batch_remove(ids=[ws])
    return gone


def _append_blender_workspaces(window):
    """Blender's factory workspaces the file lacks, in Blender's order; returns the one to show (the one the user's
    file showed, else Layout)."""
    for name in BLENDER_WORKSPACES:
        if bpy.data.workspaces.get(name) is not None:
            continue
        before = set(bpy.data.workspaces)
        try:
            with bpy.context.temp_override(**_window_override(window)):
                bpy.ops.workspace.append_activate(idname=name, filepath=EMBEDDED_STARTUP)
        except RuntimeError as ex:
            print("Maya Workflow Kit: Blender workspace not appended:", ex)
            continue
        if name == "Layout":
            for ws in bpy.data.workspaces:
                if ws not in before:
                    ws[BLENDER_LAYOUT_KEY] = True
    for name in (START_WORKSPACE["name"], "Layout"):
        ws = bpy.data.workspaces.get(name) if name else None
        if ws is not None and not is_maya_workspace(ws):
            return ws
    return next((w for w in bpy.data.workspaces if BLENDER_LAYOUT_KEY in w), None)


def blender_target(window):
    """The workspace a switch to Blender shows in ``window`` when its Maya layout came with the file (no workspace
    to go back to): the user's workspace if the file has one, else the user's own startup workspaces appended,
    else Blender's factory workspaces, showing Layout (#19, #185). Maya workspaces with Blender's names step aside for
    Blender's own (#282); a never saved new Maya scene loses its Maya workspaces (#307). The caller shows the result
    after these appends (each append also asks the window to show what it appended; the last request wins)."""
    renamed = _rename_maya_clashes()
    _drop_new_scene_layouts(window)
    target = _users_workspace(window) or _users_startup_workspaces(window) or _append_blender_workspaces(window)
    _append_counterparts(window, renamed)
    return target


def _leave_template_layout(window):
    """The window shows the Maya layout of a Maya Workflow Kit template file (no workspace to go back to): give it
    the user's workspace (``blender_target``), appended once and reused. In a saved file the Maya one stays for the
    way back (``enter_layout``)."""
    target = blender_target(window)
    if target is None:
        return False
    window.workspace = target
    _show_later(window, target.name)
    return True


def _show_later(window, name, tries=3):
    """Show workspace ``name`` in ``window`` again over the next event loops: Blender's appends switch the window to
    the workspace each appended once the event loop runs, after the switch chose the one to show."""
    ptr = window.as_pointer()
    left = [tries]

    def tick():
        win = live_refs.window(ptr)
        ws = bpy.data.workspaces.get(name)
        left[0] -= 1
        if win is None or ws is None or left[0] < 0:
            _forget_timer(tick)
            return None
        if win.workspace != ws:
            win.workspace = ws
        return 0.05
    _timers.append(tick)
    bpy.app.timers.register(tick, first_interval=0.05)


def _mode_modules():
    from . import MODE
    return MODE


# The Maya mode modules registered right now, in order (#198 #199). ``unregister_mode`` takes back exactly
# these, so a half-done register or a module that raises on unregister can't leave Maya menus behind.
_mode_done = []


def register_mode():
    """Register the Maya mode modules all or nothing: on an exception the ones already registered are taken back
    and the exception is raised again (``_registered[0]`` stays False)."""
    from . import safe_reg
    if _mode_done:                  # a previous half state: start clean
        unregister_mode()
    safe_reg.release_panels(_mode_panels())
    safe_reg.register_all(_mode_modules(), _mode_done)
    _panels_on[:] = [cls for cls in _mode_panels() if cls.is_registered]
    _registered[0] = True


# The kit's panels registered by ``register_mode``. Another add-on may unregister panels of the sidebar's Tool tab
# (where the kit's panels are) while it is on and register them again later (#423): ``unregister_mode`` first puts
# back what was taken, ``register_mode`` first takes out what was put back while Maya mode was off.
_panels_on = []


def _mode_panels():
    from . import safe_reg
    from . import operators
    return safe_reg.own_panels(tuple(m.__name__ + "." for m in _mode_modules() if m is not operators))


def unregister_mode():
    """Take back every Maya mode module that is registered (whatever ``_registered[0]`` says). Returns the names of
    modules whose unregister raised (the others still went)."""
    from . import safe_reg
    safe_reg.restore_panels(_panels_on)
    _panels_on.clear()
    failed = safe_reg.unregister_all(_mode_done)
    _registered[0] = False
    return failed


def preferences_off():
    """Maya mode off in the add-on preference (after a failed start, so the switch shows Blender)."""
    try:
        prefs = _prefs_addon()
        if prefs.maya_mode:
            prefs.maya_mode = False
    except Exception:
        pass


# Why the last switch to Maya mode failed (None = it didn't): shown in the console, a report and the preferences.
last_error = [None]


def _report_failure(ex):
    text = f"Maya mode could not start ({type(ex).__name__}: {ex}). Blender stays as it was; see the system console"
    last_error[0] = text
    print("Maya Workflow Kit:", text)
    if bpy.app.background:
        return
    try:
        def draw(menu, _context):
            menu.layout.label(text="Maya mode could not start: Blender stays as it was.", icon='ERROR')
            menu.layout.label(text=f"{type(ex).__name__}: {ex}"[:160])
            menu.layout.label(text="Details: Window > Toggle System Console.")
        bpy.context.window_manager.popup_menu(draw, title="Maya Workflow Kit", icon='ERROR')
    except Exception:
        pass


def stop_playback():
    """Stop animation playback in every window before a switch: the keymap and the timeline header change under
    a running playback otherwise. Returns the number of windows stopped."""
    stopped = 0
    if bpy.app.background:
        return 0
    for window in _windows():
        screen = window.screen
        if screen is None or screen.is_temporary or not screen.is_animation_playing:
            continue
        try:
            with bpy.context.temp_override(window=window, screen=screen):
                bpy.ops.screen.animation_cancel(restore_frame=False)
            stopped += 1
        except RuntimeError:
            pass
    return stopped


def _set_mode(on, layout=True):
    """Switch Maya mode on / off now (no restart). The open file's scenes are not touched; Blender's preferences
    are never written: switching off unregisters the Maya mode modules, which takes back everything
    they registered."""
    prefs = _prefs_addon()
    stop_playback()
    if on and prefs.maya_mode and _registered[0]:
        # already on (a start with Maya mode saved on keeps the user's workspace): the Maya button puts the Maya
        # keys back in place and opens the Maya layout
        from . import keymap
        keymap.sync()
        if layout and not bpy.app.background:
            for window in _windows()[:1]:
                enter_layout(window)
        _redraw()
        return False
    if on == bool(prefs.maya_mode) and (on == _registered[0]):
        return False
    if on:
        if not _registered[0]:
            try:
                register_mode()
            except Exception as ex:      # rolled back already: plain Blender, Maya mode stays off
                preferences_off()
                _report_failure(ex)
                _redraw()
                raise
        last_error[0] = None
        prefs.maya_mode = True
        from . import keymap
        keymap.sync()
        _pending_hotkeys()
        if layout and not bpy.app.background:
            for window in _windows()[:1]:
                enter_layout(window)
    else:
        try:
            from .ui import maya_dock
            maya_dock.close_floating()     # floating Maya panels would show Blender's Tool tab
        except Exception:
            pass
        kept = _keep_panels() if layout else []
        try:
            from .ui import four_view
            four_view.collapse_all(bpy.context)   # the four panels back to one, the screen as it was
        except Exception:
            pass
        if layout:
            for window, record in kept:
                switch_keep.add_four_view(record, window)
            for window in _windows():
                leave_layout(window)
            switch_keep.store([record for _window, record in kept])
        prefs.maya_mode = False
        unregister_mode()      # whatever is recorded as registered, also after a half-done switch (#198)
    # The mode is this add-on's own setting: marked for Blender's Auto-Save Preferences like a change made in the
    # Preferences editor (no Blender setting is written).
    _redraw()
    return True


_registered = [False]


def _keep_panels():
    """[(window, record)] of the Maya layout panels each window shows (``switch_keep``), first window first; one
    record per Maya template workspace."""
    out, seen = [], set()
    for window in _windows():
        try:
            record = switch_keep.capture(window)
        except Exception as ex:      # never stop the switch for this
            print("Maya Workflow Kit: Maya panels not kept:", ex)
            continue
        if record is not None and record["template"] not in seen:
            seen.add(record["template"])
            out.append((window, record))
    return out


def _pending_hotkeys():
    """Hotkeys a settings import made with Maya mode off wait for Maya mode: give them now."""
    try:
        from . import settings_io
        done = settings_io.apply_pending(bpy.context)
    except Exception as ex:         # never stop Maya mode for this
        print("Maya Workflow Kit: kept hotkeys:", ex)
        return
    if done:
        print(f"Maya Workflow Kit: {done} imported hotkey(s) given")


def _redraw():
    for window in _windows():
        for area in window.screen.areas:
            area.tag_redraw()


# --- UI -----------------------------------------------------------------------------------------

_pending = []


def _apply_pending():
    while _pending:
        on, layout = _pending.pop(0)
        try:
            set_mode(on, layout=layout)
        except Exception as ex:   # never leave a timer raising forever
            print("Maya Workflow Kit: switch failed:", ex)
            import traceback
            traceback.print_exc()
    return None


def request(on, layout=True):
    from ...core import request as switch
    return switch('MAYA' if on else 'BLENDER', layout=layout)


class ALLSET_OT_switch_mode(bpy.types.Operator):
    """Switch between Maya mode (Maya keymap, layout and menus) and plain Blender.
    Nothing in the open file's scenes changes; Blender's preferences are never changed"""
    bl_idname = "allset.switch_mode"
    bl_label = "Switch Maya / Blender"
    bl_options = {'REGISTER'}

    mode: bpy.props.EnumProperty(
        name="Mode", items=(('TOGGLE', "Toggle", ""), ('MAYA', "Maya", ""), ('BLENDER', "Blender", "")),
        default='TOGGLE', options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        if props.mode == 'MAYA':
            return "Switch to Maya mode: Maya keymap, layout and menus (Ctrl+Alt+Shift+M)"
        if props.mode == 'BLENDER':
            return "Switch back to plain Blender: Blender's own keymap, layout and menus (Ctrl+Alt+Shift+M)"
        return "Switch between Maya mode and plain Blender (Ctrl+Alt+Shift+M)"

    def execute(self, context):
        on = (not is_on()) if self.mode == 'TOGGLE' else self.mode == 'MAYA'
        try:
            request(on)
        except ValueError as error:
            from ...localization import tr
            self.report({'WARNING'}, tr(str(error)))
            return {'CANCELLED'}
        results.result(self, "Maya mode" if on else "Blender mode")
        return {'FINISHED'}


def draw_topbar_switch(self, context):
    """Top bar, right: [Maya | Blender] (both modes)."""
    region = context.region
    if region is None or region.alignment != 'RIGHT':
        return
    on = is_on()
    # Maya's menu bar has nothing here: flat text, the current mode bright and the other dim
    row = self.layout.row(align=True)
    row.scale_x = 0.85
    sub = row.row(align=True)
    sub.active = on
    sub.operator(ALLSET_OT_switch_mode.bl_idname, text="Maya", emboss=False).mode = 'MAYA'
    row.label(text="|")
    sub = row.row(align=True)
    sub.active = not on
    sub.operator(ALLSET_OT_switch_mode.bl_idname, text="Blender", emboss=False).mode = 'BLENDER'


def draw_edit_menu(self, context):
    """Blender's Edit menu: found by the menu search (F3) in Blender mode."""
    if is_on():
        return
    self.layout.separator()
    self.layout.operator(ALLSET_OT_switch_mode.bl_idname, text="Switch to Maya Mode",
                         icon='EVENT_M').mode = 'MAYA'


classes = (ALLSET_OT_switch_mode,)
_keymaps = []


def _add_shortcut():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new(name="Window", space_type='EMPTY', region_type='WINDOW')
    key, mods = SHORTCUT
    kmi = km.keymap_items.new(ALLSET_OT_switch_mode.bl_idname, key, 'PRESS', **mods)
    kmi.properties.mode = 'TOGGLE'
    _keymaps.append((km, kmi))


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()
    for fn in (_apply_pending, *_timers):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    _timers.clear()
    _pending.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

def set_mode(on, layout=True):
    from ...core import set_mode as switch
    return switch('MAYA' if on else 'BLENDER', layout=layout)
