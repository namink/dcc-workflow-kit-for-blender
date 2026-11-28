# SPDX-License-Identifier: GPL-3.0-or-later
"""The kit's two rows in Image Editor areas: the Status Line strip (hidden Mask ``.AllsetStrip``) and the Shelf
row (``.AllsetShelf``). ``is_strip`` / ``is_shelf_row`` / ``is_kit_row`` tell them apart, ``strip_area`` /
``shelf_row_area`` find them on a screen, ``make_strip`` and ``allset.shelf_strip_toggle`` make / close the strip.
Also the shelf row's sizes in px at UI scale 1 (icons, tabs, separators). Related: shelf.py, status_line.py."""

import bpy


MARKER = ".AllsetStrip"
SHELF_MARKER = ".AllsetShelf"   # the template's shelf row

STRIP_PX = 68          # header + tool header rows at UI scale 1


# --- the strip area ----------------------------------------------------------------------------------

def is_strip(space):
    mask = getattr(space, "mask", None)
    return space is not None and space.type == 'IMAGE_EDITOR' and mask is not None and mask.name == MARKER


def is_shelf_row(space):
    mask = getattr(space, "mask", None)
    return space is not None and space.type == 'IMAGE_EDITOR' and mask is not None and mask.name == SHELF_MARKER


def is_kit_row(space):
    """The Status Line strip or the Shelf row: kit chrome in an Image Editor, never an editor of its own."""
    return is_strip(space) or is_shelf_row(space)


def strip_area(screen):
    for area in (screen.areas if screen else ()):
        if area.type == 'IMAGE_EDITOR' and is_strip(area.spaces.active):
            return area
    return None


def shelf_row_area(screen):
    for area in (screen.areas if screen else ()):
        if area.type == 'IMAGE_EDITOR' and is_shelf_row(area.spaces.active):
            return area
    return None


def marker_mask():
    mask = bpy.data.masks.get(MARKER)
    if mask is None:
        mask = bpy.data.masks.new(MARKER)
        mask.use_fake_user = True
    return mask


def make_strip(space):
    """Turn an Image Editor space into the Maya strip."""
    space.mask = marker_mask()
    space.mode = 'VIEW'
    space.show_region_tool_header = True
    space.show_region_ui = False
    space.show_region_toolbar = False


class ALLSET_OT_shelf_strip_toggle(bpy.types.Operator):
    """Show or hide the Status Line + Shelf strip above the largest 3D View"""
    bl_idname = "allset.shelf_strip_toggle"
    bl_label = "Shelf"

    def execute(self, context):
        screen = context.screen
        win = context.window
        if strip_area(screen) is not None or shelf_row_area(screen) is not None:   # the shelf row alone: Status Line off
            for area in (strip_area(screen), shelf_row_area(screen)):
                if area is None:
                    continue
                region = next(r for r in area.regions if r.type == 'WINDOW')
                with context.temp_override(window=win, screen=screen, area=area, region=region):
                    bpy.ops.screen.area_close()
            return {'FINISHED'}
        from . import four_view
        if four_view.is_four(screen):          # over the whole four view, never over one of its panels
            done = four_view.in_one_panel(context, win, lambda ctx, w, _p: _strip_over(ctx, w))
            return {'FINISHED'} if done else {'CANCELLED'}
        if _strip_over(context, win) is None:
            self.report({'WARNING'}, "No 3D View to put the shelf over")
            return {'CANCELLED'}
        from . import status_line_row
        status_line_row.sync(win)           # Status Line off: the new strip shows the shelf only
        return {'FINISHED'}


def _strip_over(context, win):
    """Split the Status Line + Shelf strip off the top of ``win``'s largest 3D View; the new area or None."""
    from .status_line import main_view3d
    screen = win.screen
    view3d, region = main_view3d(screen)
    if view3d is None:
        return None
    before = {a.as_pointer() for a in screen.areas}
    px = STRIP_PX * context.preferences.system.ui_scale
    factor = max(0.5, 1.0 - px / max(view3d.height, 1))
    with context.temp_override(window=win, screen=screen, area=view3d, region=region):
        bpy.ops.screen.area_split(direction='HORIZONTAL', factor=factor)
    new = next((a for a in screen.areas if a.as_pointer() not in before), None)
    if new is None:
        return None
    new.type = 'IMAGE_EDITOR'
    make_strip(new.spaces.active)
    return new


# Shelf buttons are 35x34 with 32 px icons.
ICON_PX = 32
PITCH_PX = 35
LEFT_PX = 6
# Maya's shelf: the shelf row is one 64 px block — an
# 18 px tab strip at the top (tabs from x 37, Segoe UI 11 px), the shelf menu / editor glyphs in a 16 px column at
# x 16, icons from x 43 at y 24 under the row's top, 12 px separators between Maya's button groups
# (``shelf_data.GAPS``). The kit draws that whole block in the shelf row's WINDOW region when the row has no
# header (the Maya Workflow Kit template); with a header (older files) the header keeps the tab buttons.
TAB_PX = 19
TAB_LEFT_PX = 37
TAB_PAD_PX = 10
TAB_FONT_PX = 11
STRIP_LEFT_PX = 43
SEP_PX = 12
