# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-view state the view furniture changes: which 3D Views are Maya views (``maya_view``), Blender's navigation
gizmo shown there instead of the ViewCube when the preference asks (``apply_navigation`` with its timer and save /
load handlers), the asset shelf header hidden in pose / paint modes (``strip_action``, ``_show_strips``) and the
HUD draw handler list (``_handle``). Registered by view_furniture.py, which also re-exports these names.
"""

import bpy

# --- per-view state -------------------------------------------------------------------------

def _prefs():
    from .. import preferences
    try:
        return preferences.get()
    except KeyError:
        return None


def maya_view(space):
    return space is not None and space.type == 'VIEW_3D' and space.overlay.show_overlays \
        and (not space.show_gizmo_navigate or space.as_pointer() in _SHOWN)


# --- Blender navigation gizmo instead of the ViewCube (#209) --------------------------------------------------------
# Add-on preference ``view_navigation``: 'VIEWCUBE' (Maya, default) or 'BLENDER'. With 'BLENDER' the kit turns
# Blender's navigation gizmo on in the Maya views (the views whose gizmo is off) and draws no ViewCube there; the
# camera name / view axis stay. Display > Heads Up Display > ViewCube (``maya_viewcube``) shows or hides whichever
# navigation widget is chosen. The kit gives every such view its flag back when the preference goes
# back, Maya mode goes off or the add-on is disabled, and around every save, so a file always holds the Maya view.

_SHOWN = set()        # pointers of the 3D View spaces whose navigation gizmo the kit turned on (this session)
_APPLY_LATER = []
_SAVING = []


def cube_wanted(prefs):
    """True when the kit draws its ViewCube (the HUD item is on and the Maya ViewCube is the chosen widget)."""
    return bool(prefs.maya_viewcube) and getattr(prefs, "view_navigation", 'VIEWCUBE') == 'VIEWCUBE'


def blender_gizmo_wanted(prefs):
    return prefs is not None and bool(prefs.maya_viewcube) and prefs.view_navigation == 'BLENDER'


def _spaces():
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    yield area, space


def _hideable(space):
    """A Maya view whose navigation gizmo the kit may turn on (not the Tool Box column)."""
    from . import toolbox
    return not space.show_gizmo_navigate and space.overlay.show_overlays and not toolbox.is_toolbox(space)


def apply_navigation(want=None):
    """Bring every 3D View in line with the preference (``want`` overrides it: False = give every flag back)."""
    if want is None:
        want = blender_gizmo_wanted(_prefs()) and not _SAVING
    live = set()
    for area, space in _spaces():
        ptr = space.as_pointer()
        live.add(ptr)
        if want and ptr not in _SHOWN and _hideable(space):
            space.show_gizmo_navigate = True
            _SHOWN.add(ptr)
            area.tag_redraw()
        elif not want and ptr in _SHOWN:
            if space.show_gizmo_navigate:
                space.show_gizmo_navigate = False
            _SHOWN.discard(ptr)
            area.tag_redraw()
    _SHOWN.intersection_update(live)      # closed areas: their pointers may be reused


def _apply_tick():
    _APPLY_LATER.clear()
    if _handle:
        apply_navigation()
    return None


def _apply_later():
    """A new Maya view (appended workspace, duplicated area) seen while drawing: apply from a timer."""
    if not _APPLY_LATER:
        _APPLY_LATER.append(_apply_tick)
        bpy.app.timers.register(_apply_tick, first_interval=0.0)


@bpy.app.handlers.persistent
def _save_pre(*_args):
    _SAVING.append(True)
    apply_navigation(False)


@bpy.app.handlers.persistent
def _save_post(*_args):
    _SAVING.clear()
    apply_navigation()


@bpy.app.handlers.persistent
def _load_pre(*_args):
    _SHOWN.clear()                        # the old file's spaces go: never compare their pointers again


@bpy.app.handlers.persistent
def _load_post(*_args):
    _SAVING.clear()
    apply_navigation()


_HANDLERS = (("save_pre", _save_pre), ("save_post", _save_post), ("load_pre", _load_pre),
             ("load_post", _load_post))


# --- asset shelf strip ----------------------------------------------------------
# Pose / paint modes give the view an ASSET_SHELF_HEADER region (29 px at the bottom) that never draws
# while the shelf is collapsed: it expects Region Overlap, which Maya mode turns off. Without overlap the
# WINDOW region shrinks above it and the strip keeps the pixels drawn there before the mode change — the camera
# label and triad showed twice ("persp" under "persp"). A draw handler on that region is never called,
# so the strip is hidden instead (screen.region_toggle; Maya has no asset shelf) and shown again when the shelf is
# opened or the kit unregisters. The HUD draw sees the state; the toggle runs from a timer.

def strip_action(area, overlap):
    """'HIDE' / 'SHOW' for the asset shelf header of ``area``, or None."""
    shelf = next((r for r in area.regions if r.type == 'ASSET_SHELF'), None)
    header = next((r for r in area.regions if r.type == 'ASSET_SHELF_HEADER'), None)
    if shelf is None or header is None:
        return None
    if header.height > 1 and shelf.height <= 1 and not overlap:
        return 'HIDE'
    if header.height <= 1 and area.as_pointer() in _HIDDEN and (shelf.height > 1 or overlap):
        return 'SHOW'
    return None


_HIDDEN = set()       # area pointers whose shelf header the kit hid (this session)
_PENDING = {}        # area pointer -> its timer function


def _toggle_strip(window, area):
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None:
        return False
    with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
        return bpy.ops.screen.region_toggle(region_type='ASSET_SHELF_HEADER') == {'FINISHED'}


def _strip_later(area_ptr):
    def tick():
        _PENDING.pop(area_ptr, None)
        overlap = bpy.context.preferences.system.use_region_overlap
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.as_pointer() != area_ptr:
                    continue
                act = strip_action(area, overlap)
                if act and _toggle_strip(window, area):
                    (_HIDDEN.add if act == 'HIDE' else _HIDDEN.discard)(area_ptr)
                    area.tag_redraw()
        return None
    if area_ptr not in _PENDING:
        _PENDING[area_ptr] = tick
        bpy.app.timers.register(tick, first_interval=0.0)


def _check_strip(context):
    area = context.area
    if area is not None and strip_action(area, context.preferences.system.use_region_overlap):
        _strip_later(area.as_pointer())


def _show_strips():
    """Unregister: give back every shelf header the kit hid."""
    wm = getattr(bpy.context, "window_manager", None)
    for window in (wm.windows if wm else ()):
        for area in window.screen.areas:
            if area.as_pointer() in _HIDDEN:
                header = next((r for r in area.regions if r.type == 'ASSET_SHELF_HEADER'), None)
                if header is not None and header.height <= 1:
                    try:
                        _toggle_strip(window, area)
                    except RuntimeError:
                        pass
    _HIDDEN.clear()
    for tick in _PENDING.values():
        if bpy.app.timers.is_registered(tick):
            bpy.app.timers.unregister(tick)
    _PENDING.clear()


_handle = []


def _remove_handler():
    while _handle:
        bpy.types.SpaceView3D.draw_handler_remove(_handle.pop(), 'WINDOW')
