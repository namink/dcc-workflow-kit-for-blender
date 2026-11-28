# SPDX-License-Identifier: GPL-3.0-or-later
"""The Maya layout workspaces in the open file: the custom properties that mark them (``PREV_KEY``, ``TEMPLATE_KEY``,
``USER_KEY``, ...), ``is_maya_workspace`` / ``template_of``, ``enter_layout`` / ``append_workspace`` (a template
workspace with its Status Line / Shelf masks and Maya-unit views), ``reset_workspace``, ``drop_workspace`` and the
deferred delete (``_timers``: stopped by switch.unregister). Leaving the layout, the mode switch: switch.py."""

import os
import uuid

import bpy

from . import live_refs


WORKSPACE = "Maya-style"


TEMPLATE_WORKSPACE = "General"
PREV_KEY = "allset_switch_prev"


def _template_blend():
    from .app_template import STARTUP
    return STARTUP


def _window_override(window):
    return {"window": window, "screen": window.screen}


# "<run>:<session uid>" on each Maya workspace the kit made or keeps. Blender's Duplicate, or another add-on making
# its own layout from the window's workspace, copies the kit's keys too; the copy's session uid differs from the one
# written (#423). ``_RUN`` tells this Blender session's marks from ones saved in a file (session uids start again).
OWN_KEY = "allset_own"
_RUN = uuid.uuid4().hex[:12]


def mark_own(ws):
    ws[OWN_KEY] = f"{_RUN}:{ws.session_uid}"


def is_copy(ws):
    """A copy of one of the kit's Maya workspaces made by something else in this session (the kit's own workspace
    still exists): it carries the kit's keys but is not the kit's."""
    mark = ws.get(OWN_KEY)
    if not isinstance(mark, str) or not mark.startswith(_RUN + ":"):
        return False
    try:
        uid = int(mark.split(":", 1)[1])
    except ValueError:
        return False
    return uid != ws.session_uid and any(w.session_uid == uid for w in bpy.data.workspaces)


def forget_copies():
    """Copies of the kit's Maya workspaces lose the kit's keys (a switch to Blender doesn't delete or leave them,
    #423); the kit's own Maya workspaces get this session's mark. Returns the names of the copies."""
    copies = [ws for ws in bpy.data.workspaces if ws.library is None and is_copy(ws)]
    for ws in copies:
        for key in [k for k in ws.keys() if k.startswith("allset_")]:
            del ws[key]
    for ws in bpy.data.workspaces:
        if ws.library is None and is_maya_workspace(ws) and ws.get(OWN_KEY) != f"{_RUN}:{ws.session_uid}":
            mark_own(ws)
    return [ws.name for ws in copies]


def is_maya_workspace(ws):
    """A workspace that already is the Maya layout (appended by the switch or a Maya Workflow Kit file)."""
    if ws is None or is_copy(ws):
        return False
    if PREV_KEY in ws or TEMPLATE_KEY in ws or USER_KEY in ws:     # TEMPLATE_KEY: any Maya workspace of the template
        return True
    for screen in ws.screens:
        for area in screen.areas:
            if area.type != 'IMAGE_EDITOR':
                continue
            mask = getattr(area.spaces.active, "mask", None)
            if mask is not None and mask.name.startswith(".Allset"):
                return True
    return False


def _fit_views(ws, scene, saved_unit=0.01):
    """The template views are in cm (Maya unit 0.01 BU; a saved workspace: the Maya unit it was saved with): keep
    them on the same Maya-unit scene."""
    from .operators import units
    ratio = units.maya_unit(scene) / (saved_unit or 0.01)
    for screen in ws.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type != 'VIEW_3D':
                    continue
                # The tool header is Maya's panel toolbar in views with a header; the Tool Box column has
                # neither. Set it explicitly: an appended screen came back with it shown. Only a
                # change is written (Modeling - Expert keeps a header without the toolbar row; writing a
                # region flag of a screen no window shows crashes Blender in ED_area_init in -b).
                if space.show_region_tool_header and not space.show_region_header:
                    space.show_region_tool_header = False
                for key, value in units.clip(scene).items():
                    setattr(space, key, value)
                space.overlay.grid_scale = units.grid_scale(scene)
                if abs(ratio - 1.0) > 1e-9:
                    for rv3d in (space.region_3d, *space.region_quadviews):
                        rv3d.view_location = rv3d.view_location * ratio
                        rv3d.view_distance *= ratio


def enter_layout(window):
    """Append and activate the Maya layout workspace in ``window`` (unless it already is one)."""
    if window is None:
        return None
    forget_copies()
    if is_maya_workspace(window.workspace):
        return None
    own = [ws for ws in bpy.data.workspaces if is_maya_workspace(ws)]
    own.sort(key=lambda ws: template_of(ws) != TEMPLATE_WORKSPACE)     # Maya Classic first
    own = own[0] if own else None
    if own is not None:
        # the file's own Maya layout (a Maya Workflow Kit template file left by a switch to Blender): back to it,
        # nothing appended twice (#19); the user's workspace is remembered for the way back (#185)
        if window.workspace is not None:
            own[BLENDER_PREV_KEY] = window.workspace.name
        _prepare_layout(window, own)
        keep_panels(window, own, window.workspace, fresh=False)
        window.workspace = own
        return own
    shown = window.workspace
    prev = shown.name
    ws = append_workspace(window, TEMPLATE_WORKSPACE)
    if ws is None:
        return None
    ws[PREV_KEY] = prev
    ws.name = WORKSPACE
    _prepare_layout(window, ws, fresh=True)
    keep_panels(window, ws, shown, fresh=True)
    return ws


def keep_panels(window, ws, shown, fresh):
    """The Maya panels the switch to Blender kept (#458) back in ``ws``: ``fresh`` = a workspace just appended from
    the template. ``shown``: the Blender workspace the window showed."""
    from . import switch, switch_keep
    if bpy.app.background or not switch._registered[0]:
        return
    try:
        switch_keep.restore(window, ws, switch_keep.find(template_of(ws), shown), fresh)
    except Exception as ex:          # never stop the switch for this
        print("Maya Workflow Kit: Maya panels not laid out again:", ex)



def _prepare_layout(window, ws, fresh=False):
    """Restore and fit the destination before the event loop presents its first frame."""
    from . import switch
    if bpy.app.background or not switch._registered[0] or not ws.screens:
        return
    from .ui import kit_icons, outliner_tree, shelf, time_slider, toolbox, viewport_settings
    screen = ws.screens[0]
    if fresh:
        toolbox._state.pop(screen.name, None)  # a deleted workspace may have used this name
    kit_icons.make_all()    # else the first frame draws Blender's fallback icons
    previous = None
    # Re-entering the screen updates area rectangles after area_move without drawing a frame. A window that already
    # shows the screen (a new Maya scene) is left to its timers: passing it through another screen to recompute the
    # rectangles lost the next presses in the viewport (a middle drag after a manipulator click, a Multi-Cut click).
    for _ in range(4):
        with bpy.context.temp_override(window=window, screen=screen):
            if previous is None:
                shelf.settle_rows()
                outliner_tree.hide_all()
                viewport_settings.sample()
            sizes = tuple((a.x, a.y, a.width, a.height) for a in screen.areas)
            if sizes == previous:
                break
            previous = sizes
            toolbox.fit_columns(start_fit=False)
    with bpy.context.temp_override(window=window, screen=screen):
        time_slider.fit_timelines()     # at the final sizes; else the first draw schedules it and the ruler jumps


TEMPLATE_KEY = "allset_template"      # the template workspace a Maya workspace was made from
USER_KEY = "allset_user_workspace"    # a workspace the user saved (Save Current Workspace As): its name
USER_UNIT_KEY = "allset_user_unit"    # the Maya unit of the scene it was saved in


def append_workspace(window, template_name, filepath=None, idname=None):
    """Append the template workspace ``template_name`` (General, Animation, ... tools/make_startup.MAYA_WORKSPACES) into
    the open file and show it in ``window``: its Status Line / Shelf masks and cm views are set up (#81). With
    ``filepath`` / ``idname``: workspace ``idname`` of that file (a saved workspace, ``template_name`` None)."""
    before = set(bpy.data.workspaces)
    libs = set(bpy.data.libraries)
    with bpy.context.temp_override(**_window_override(window)):
        bpy.ops.workspace.append_activate(idname=idname or template_name, filepath=filepath or _template_blend())
    if filepath is not None:
        # the appended workspace is local: the saved file's library entry isn't needed
        def same(path):
            return os.path.normcase(os.path.normpath(bpy.path.abspath(path))) ==                 os.path.normcase(os.path.normpath(filepath))
        for lib in [lib for lib in bpy.data.libraries if lib not in libs and same(lib.filepath)]:
            if not _linked_from(lib):
                bpy.data.libraries.remove(lib)
    new = [ws for ws in bpy.data.workspaces if ws not in before]
    if not new:
        return None
    ws = new[0]
    if template_name is not None:
        ws[TEMPLATE_KEY] = template_name
    mark_own(ws)
    window.workspace = ws
    # region flag writes call ED_area_init, which reads the context window's workspace (None after a file load in
    # -b crashed Blender)
    with bpy.context.temp_override(**_window_override(window)):
        _mark_strips(ws)
        _fit_views(ws, window.scene, ws.get(USER_UNIT_KEY, 0.01))
    return ws


def _linked_from(lib):
    """True when some data of the open file is still linked from library ``lib``."""
    for attr in dir(bpy.data):
        coll = getattr(bpy.data, attr, None)
        if attr == "libraries" or not isinstance(coll, bpy.types.bpy_prop_collection):
            continue
        if any(getattr(i, "library", None) == lib for i in coll):
            return True
    return False


def template_of(ws):
    """The template name of a Maya workspace (None: not one of the kit's Maya workspaces)."""
    if ws is None or USER_KEY in ws:      # a saved workspace isn't a template's copy
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
    name, prev = old.name, old.get(PREV_KEY)
    old.name = name + " (old)"
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


STRIP_MASKS = (".AllsetStrip", ".AllsetShelf")   # ui/shelf_strip.MARKER, SHELF_MARKER (top to bottom)
MASK_KEY = "allset_switch_masks"


def _mark_strips(ws):
    """Appending a workspace doesn't bring the Masks its Image Editors point to, and those mark the
    Status Line row and the Shelf row (ui/shelf_strip.is_strip): load them and point the two
    top Image Editors (Status Line above the Shelf) at them again."""
    missing = [m for m in STRIP_MASKS if m not in bpy.data.masks]
    if missing:
        with bpy.data.libraries.load(_template_blend(), link=False) as (src, dst):
            dst.masks = [m for m in missing if m in src.masks]
        ws[MASK_KEY] = missing
    for screen in ws.screens:
        rows = sorted((a for a in screen.areas if a.type == 'IMAGE_EDITOR'), key=lambda a: -a.y)
        for area, name in zip(rows, STRIP_MASKS):
            mask = bpy.data.masks.get(name)
            if mask is not None:
                area.spaces.active.mask = mask


BLENDER_LAYOUT_KEY = "allset_blender_layout"
BLENDER_PREV_KEY = "allset_blender_prev"     # on a template Maya workspace: the user's workspace before it (#185)


def _delete_workspace(window, name, added):
    ws = bpy.data.workspaces.get(name)
    # workspace.delete removes the window's active workspace whatever the override says: remove the
    # left one as data once no window shows it (4.5 and 5.1 GUI)
    if ws is not None and all(w.workspace != ws for w in _windows()):
        bpy.data.batch_remove(ids=[ws])
    for mask_name in added:                  # masks the switch loaded go too: the file is as before
        mask = bpy.data.masks.get(mask_name)
        if mask is not None:
            bpy.data.masks.remove(mask)


def drop_workspace(window, ws):
    """Remove workspace ``ws`` from the open file (once ``window`` no longer shows it)."""
    name = ws.name + " (old)" if not ws.name.endswith(" (old)") else ws.name
    ws.name = name
    if window.workspace == ws:
        _delete_later(window, ws.name, [])
    else:
        _delete_workspace(window, ws.name, [])


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


# Timers this module started (closures): unregister() stops any still pending, so nothing of the kit runs after it.
_timers = []


def _forget_timer(fn):
    if fn in _timers:
        _timers.remove(fn)


def _windows():
    wm = bpy.context.window_manager
    return list(wm.windows) if wm is not None else []
