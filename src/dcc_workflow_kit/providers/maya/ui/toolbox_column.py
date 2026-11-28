# SPDX-License-Identifier: GPL-3.0-or-later
"""The kit layout's Tool Box column: which 3D View is the column (``is_toolbox``), its flat tool-strip look
(``settle``) and one toolbar column's width at the UI scale (``column_width``), plus the area gap and Outliner
width shared by ``layout_fit`` and ``toolbox_layouts``. ``_enabled`` reads the kit's Tool Box preference.
Registered by ``toolbox``."""

import bpy

from .. import compat


def _enabled(context):
    from .. import preferences
    try:
        return preferences.get(context).maya_toolbox
    except KeyError:
        return False


def is_toolbox(space):
    """True for the Maya Workflow Kit template's Tool Box column (= tools/make_startup.py is_toolbox_space). Not keyed on
    its overlays: a column whose overlays got turned on is still the column (``settle`` turns them off again)."""
    return (space is not None and space.type == 'VIEW_3D' and space.show_region_toolbar
            and not space.show_region_header and not space.show_region_ui and not space.show_object_viewport_mesh)


def settle(space, prefs=None):
    """Keep the column a solid tool strip: overlays off (else the grid axis lines show through it) and a flat
    background in the toolbar's theme colour, so any width left beside the tools (the column is wider than one
    toolbar column until ALLSET_OT_fit_columns has fitted it) reads as part of the Tool Box, not as a viewport.
    Returns True when something changed."""
    prefs = prefs or bpy.context.preferences
    # the viewport background colour is scene linear, theme colours are display (sRGB) values (an sRGB
    # 0.188 written as is shows as 119/255)
    rgb = tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                for c in tuple(compat.toolbar_back(prefs.themes[0]))[:3])
    shading = space.shading
    changed = False
    if space.overlay.show_overlays:
        space.overlay.show_overlays = False
        changed = True
    if shading.background_type != 'VIEWPORT':
        shading.background_type = 'VIEWPORT'
        changed = True
    if any(abs(a - b) > 1e-4 for a, b in zip(shading.background_color, rgb)):
        shading.background_color = rgb
        changed = True
    return changed


# --- column width -----------------------------------------------------------------------------

# Blender's toolbar is one 56 px column at scale 1 (UI_TOOLBAR_MARGIN + UI_TOOLBAR_COLUMN = 0.5 * 32 +
# 1.25 * 32, interface UI_interface.hh). Area sizes don't
# follow the UI scale: the template's column fits the toolbar at the Maya density (effective scale 1.0,
# "Maya Density" preset). At a larger scale it is resized to one toolbar column with screen.area_move,
# whose poll fails while the mouse is over any region (screen.active_region): the column stayed
# empty at Windows 125 % without the density preset. So ALLSET_OT_fit_columns
# puts the cursor on the area edge for a moment (the poll passes there), moves the edge and
# puts the cursor back; until then the main view of that screen shows its own toolbar.
TOOLBAR_PX = 56
RETINA_EXTRA_PX = 4  # px more per pixel-size step above 1 (column_width)
OUTLINER_PX = 260    # Maya's narrow panel width = the template Outliner at scale 1


def column_width(context=None):
    """One toolbar column at the current scale. A Retina display (pixel size 2) needs 4 px more than 56 x the scale,
    or Blender hides the toolbar (#248: 112 px empty, 116 px shown at scale 2)."""
    system = (context or bpy.context).preferences.system
    return round(TOOLBAR_PX * system.ui_scale) + RETINA_EXTRA_PX * max(0, int(system.pixel_size) - 1)


# px between neighbouring areas: 3 at UI scale 1.0, 5 at 1.5 (the area edge grows with the scale)
GAP_PX = 8
