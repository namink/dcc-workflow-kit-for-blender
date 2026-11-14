# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's modular editor windows for the Graph Editor, Dope Sheet and UV Editor (#319).

Maya: an editor in a pane has a Panels menu (Panel ▸ other editors, Tear Off..., Tear Off Copy...), and a torn-off
editor floats in its own window, which is attached again by dragging it onto a dock zone of the main window (or by
Panels > Panel > that editor in a pane); Windows > ... reopens it where it last was. Blender has no API to move an
area between windows or to place a window, so the kit does what ``ui/maya_dock.py`` does for the Channel Box: a
torn-off window is a copy of the pane (``screen.area_dupli``), docking closes the window and splits the main
window's viewport on the chosen side, and a click stands in for the drag.

- A **pane** (an area of a window with several areas) shows the viewport's Panels menu after the Maya menus:
  Panel ▸ turns the pane into another editor, Tear Off... opens the pane in a window and leaves a 3D View in the
  pane (Maya fills the emptied pane with a model panel), Tear Off Copy... keeps the pane as it is.
- A **floating window** (one area) shows the kit's dotted handle instead; its popup offers Dock Bottom / Left /
  Right / Top and Close. Dock splits the main window's largest 3D View (else its largest area) by the window's
  height or width (10–45 % of that area), gives the new area the window's editor type and settings and closes
  the window.
"""

import bpy
from bpy.props import EnumProperty

from .. import live_refs

EDITOR_TYPES = {'GRAPH_EDITOR': "Graph Editor", 'DOPESHEET_EDITOR': "Dope Sheet", 'IMAGE_EDITOR': "UV Editor"}
MIN_SHARE, MAX_SHARE = 0.1, 0.45    # a docked editor takes this much of the area it splits, at least / at most
# space properties copied from the window to the docked area: plain values + these sub-structs / pointers
SUB_STRUCTS = ("dopesheet",)
POINTERS = ("image",)


# --- where the editor is -------------------------------------------------------------------------------------------

def is_pane(context):
    """True when the editor is a pane of a window with several areas (no window in the context counts as a pane:
    the bar lists its Panels menu)."""
    window = getattr(context, "window", None)
    if window is None:
        return True
    from . import maya_dock
    return not maya_dock.is_floating(window)


def floating_editor(context):
    """The Maya name of the editor when ``context`` is a floating kit window of one, else None."""
    window = getattr(context, "window", None)
    area = getattr(context, "area", None)
    if window is None or area is None:
        return None
    from . import maya_dock
    if not maya_dock.is_floating(window):
        return None
    return EDITOR_TYPES.get(getattr(area, "type", None))


# --- docking -------------------------------------------------------------------------------------------------------

def share(size, full):
    """The part of an area ``full`` px long that a docked editor ``size`` px long takes."""
    return min(MAX_SHARE, max(MIN_SHARE, size / max(full, 1)))


def split(side, size, full):
    """(direction, factor) for ``screen.area_split`` that puts a new area about ``size`` px long on ``side`` of an
    area ``full`` px long: the new area is the smaller part, left / bottom for a factor under 0.5, right / top
    above it (so the share stays under a half)."""
    s = share(size, full)
    if side == 'BOTTOM':
        return 'HORIZONTAL', s
    if side == 'TOP':
        return 'HORIZONTAL', 1.0 - s
    if side == 'LEFT':
        return 'VERTICAL', s
    return 'VERTICAL', 1.0 - s


def copy_settings(src, dst, _depth=0):
    """Copy the plain settings of space ``src`` to ``dst`` (bool / int / float / enum / string, the Dope Sheet
    filters, the UV Editor's image); whatever can't be set is skipped."""
    for prop in src.bl_rna.properties:
        name = prop.identifier
        if name in ("rna_type", "type"):
            continue
        try:
            if prop.type == 'POINTER':
                if name in SUB_STRUCTS and _depth == 0:
                    copy_settings(getattr(src, name), getattr(dst, name), 1)
                elif name in POINTERS and not prop.is_readonly:
                    setattr(dst, name, getattr(src, name))
                continue
            if prop.type == 'COLLECTION' or prop.is_readonly:
                continue
            value = getattr(src, name)
            if getattr(prop, "is_array", False):
                value = tuple(value)
            if value != getattr(dst, name):
                setattr(dst, name, value)
        except Exception:      # a property this space can't take now (mode-dependent): keep the default
            pass


def target_area(window):
    """The area a docked editor is split from: the window's largest 3D View, else its largest area."""
    from . import maya_dock
    area = maya_dock._main_view(window.screen)[0]
    if area is None:
        area = max(window.screen.areas, key=lambda a: a.width * a.height, default=None)
    return area


def dock(context, window, side):
    """Close floating ``window`` and put its editor into the main window on ``side``; False when nothing was
    done (not a floating single-area window, no main window, the split was refused)."""
    from . import maya_dock
    if window is None or bpy.app.background or len(window.screen.areas) != 1:
        return False
    wm = context.window_manager
    if not maya_dock.is_floating(window, wm):
        return False
    area = window.screen.areas[0]
    main = maya_dock.main_window(wm)
    if main is None or main == window:
        return False
    target = target_area(main)
    if target is None:
        return False
    along_y = side in ('BOTTOM', 'TOP')
    direction, factor = split(side, window.height if along_y else window.width,
                              target.height if along_y else target.width)
    region = next((r for r in target.regions if r.type == 'WINDOW'), None)
    before = {a.as_pointer() for a in main.screen.areas}
    with context.temp_override(window=main, screen=main.screen, area=target, region=region):
        if bpy.ops.screen.area_split(direction=direction, factor=factor) != {'FINISHED'}:
            return False
    new = next((a for a in main.screen.areas if a.as_pointer() not in before), None)
    if new is None:
        return False
    ui_type = area.ui_type
    try:
        new.ui_type = ui_type
    except TypeError:
        return False
    copy_settings(area.spaces.active, new.spaces.active)
    maya_dock.close_window_later(window)
    frame_later(main, new, ui_type)
    return True


def frame_later(window, area, ui_type, tries=40):
    """Frame the playback range in the docked Graph Editor / Dope Sheet once its region has a size (the view
    range isn't a space setting and can't be copied)."""
    if ui_type not in ('FCURVES', 'DOPESHEET'):
        return
    win_ptr, area_ptr = window.as_pointer(), area.as_pointer()
    state = {"n": tries}

    def tick():
        window = live_refs.window(win_ptr)
        if window is None:
            return None
        area = next((a for a in window.screen.areas if a.as_pointer() == area_ptr), None)
        if area is None or area.ui_type != ui_type:
            return None
        from . import editor_chrome
        try:
            with bpy.context.temp_override(window=window, screen=window.screen, area=area):
                done = editor_chrome.frame_playback_range(bpy.context, area)
        except (ReferenceError, RuntimeError):
            return None
        area.tag_redraw()
        state["n"] -= 1
        return None if done or state["n"] <= 0 else 0.05

    bpy.app.timers.register(tick, first_interval=0.05)


# --- operators / drawing -------------------------------------------------------------------------------------------

class ALLSET_OT_editor_dock(bpy.types.Operator):
    """Dock this floating editor into the main window on that side (Maya: drag the window onto a dock zone)"""
    bl_idname = "allset.editor_dock"
    bl_label = "Dock Editor"
    bl_options = {'INTERNAL'}

    side: EnumProperty(items=(('BOTTOM', "Dock Bottom", "Below the main viewport"),
                              ('LEFT', "Dock Left", "Left of the main viewport"),
                              ('RIGHT', "Dock Right", "Right of the main viewport"),
                              ('TOP', "Dock Top", "Above the main viewport")),
                       default='BOTTOM', options={'SKIP_SAVE'})

    def execute(self, context):
        if not dock(context, context.window, self.side):
            self.report({'WARNING'}, "This window can't be docked")
            return {'CANCELLED'}
        return {'FINISHED'}


def sides():
    """(identifier, label) of the dock sides, in menu order."""
    rna = bpy.ops.allset.editor_dock.get_rna_type()
    return [(it.identifier, it.name) for it in rna.properties["side"].enum_items]


def draw_dock_items(layout):
    """The Dock Bottom / Left / Right / Top rows of a floating editor's handle popup."""
    for side, label in sides():
        layout.operator(ALLSET_OT_editor_dock.bl_idname, text=label, icon='DOCUMENTS').side = side


classes = (ALLSET_OT_editor_dock,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
