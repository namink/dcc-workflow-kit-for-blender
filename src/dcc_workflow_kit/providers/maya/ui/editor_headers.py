# SPDX-License-Identifier: GPL-3.0-or-later
"""Graph Editor / Dope Sheet header and footer draws swapped for the Maya menu bar and icon row (``patch_headers`` /
``unpatch_headers``), the footer put on top as Maya's toolbar row (``setup_toolbar_row``), and the UV Editor header
rows drawn through the shelf's header wrapper (``draw_uv_header``, ``draw_uv_tool_header``).
"""

import bpy

from .editor_kinds import GE, DS, UV, enabled, is_graph, is_dope, is_uv
from .editor_menu_bar import draw_menus
from .editor_icon_row import draw_icons
from . import own_draw as _own_draw


# --- header draws ------------------------------------------------------------------------------------------------

def toolbar_row(area):
    """True when the editor's footer is shown at the top: it holds Maya's toolbar row under the menu bar."""
    if area is None or not getattr(area.spaces.active, "show_region_footer", False):
        return False
    return any(r.type == 'FOOTER' and r.alignment == 'TOP' for r in area.regions)


@_own_draw.kit_draw("GRAPH_HT_header")
def _graph_header(self, context):
    if not (enabled(context) and is_graph(context.space_data)):
        return _own_draw.original("GRAPH_HT_header", _graph_header)(self, context)
    layout = self.layout
    layout.template_header()
    draw_menus(layout, context, GE)
    if not toolbar_row(context.area):
        draw_icons(layout, context, GE)
    layout.separator_spacer()
    layout.popover(panel="GRAPH_PT_filters", text="", icon='FILTER')


@_own_draw.kit_draw("DOPESHEET_HT_header")
def _dope_header(self, context):
    if not (enabled(context) and is_dope(context.space_data)):
        return _own_draw.original("DOPESHEET_HT_header", _dope_header)(self, context)
    layout = self.layout
    layout.template_header()
    draw_menus(layout, context, DS)
    if not toolbar_row(context.area):
        draw_icons(layout, context, DS)
    layout.separator_spacer()
    layout.popover(panel="DOPESHEET_PT_filters", text="", icon='FILTER')


# #192: Maya's Graph Editor / Dope Sheet keep the toolbar on its own row under the menu bar (on one row with
# the menus the tangent buttons ran past the right edge of a ~750 px editor). Blender gives these editors one header,
# but their footer (playback controls in 5.x) can sit at the top under it: in a Maya editor the footer is shown, put on
# top and draws the toolbar. Timeline mode keeps Blender's footer.
@_own_draw.kit_draw("GRAPH_HT_playback_controls")
def _graph_footer(self, context):
    if not (enabled(context) and is_graph(context.space_data)):
        return _own_draw.original("GRAPH_HT_playback_controls", _graph_footer)(self, context)
    draw_icons(self.layout, context, GE)


@_own_draw.kit_draw("DOPESHEET_HT_playback_controls")
def _dope_footer(self, context):
    if not (enabled(context) and is_dope(context.space_data)):
        return _own_draw.original("DOPESHEET_HT_playback_controls", _dope_footer)(self, context)
    draw_icons(self.layout, context, DS)


_set_up = set()          # area pointers given the Maya toolbar row this session (a later user choice is kept)


def _flip_footer(window, area):
    region = next((r for r in area.regions if r.type == 'FOOTER'), None)
    if region is None:
        return False
    try:
        with bpy.context.temp_override(window=window, area=area, region=region):
            return 'FINISHED' in bpy.ops.screen.region_flip()
    except (RuntimeError, TypeError, ReferenceError):
        return False


def setup_toolbar_row(window, area):
    """Maya Graph Editor / Dope Sheet layout of one editor, once per session: toolbar row on top; the Graph Editor
    draws tangent handles on selected keys only (Maya View > Tangents, default On Active Keys)."""
    key = area.as_pointer()
    if key in _set_up:
        return False
    _set_up.add(key)
    space = area.spaces.active
    if space.type == 'GRAPH_EDITOR':
        space.use_only_selected_keyframe_handles = True
    if toolbar_row(area):
        return False
    space.show_region_footer = True
    if all(r.alignment != 'TOP' for r in area.regions if r.type == 'FOOTER'):
        _flip_footer(window, area)
    return True


def release_toolbar_rows():
    """Maya mode off: the footers the kit put on top go back to Blender's place (bottom, hidden)."""
    try:
        wins = list(bpy.context.window_manager.windows)
    except (AttributeError, ReferenceError):
        return
    for window in wins:
        for area in window.screen.areas:
            sp = area.spaces.active
            if not (is_graph(sp) or is_dope(sp)) or not toolbar_row(area):
                continue
            _flip_footer(window, area)
            sp.show_region_footer = False
    _set_up.clear()


def draw_uv_header(self, context):
    """UV Editor header row (Maya menu bar); False = not a Maya UV Editor (draw Blender's)."""
    if not (enabled(context) and is_uv(context.space_data)):
        return False
    layout = self.layout
    layout.template_header()
    draw_menus(layout, context, UV)
    return True


def draw_uv_tool_header(self, context):
    """UV Editor tool header = Maya's icon row, then Blender's pivot / snapping / soft select."""
    if not (enabled(context) and is_uv(context.space_data)):
        return False
    layout = self.layout
    draw_icons(layout, context, UV)
    layout.separator_spacer()
    bpy.types.IMAGE_HT_header.draw_xform_template(layout, context)
    return True


HEADERS = (("GRAPH_HT_header", _graph_header), ("DOPESHEET_HT_header", _dope_header),
           ("GRAPH_HT_playback_controls", _graph_footer), ("DOPESHEET_HT_playback_controls", _dope_footer))


def own_draw(cls):
    """The class's own draw: the first of its draw functions once something appended to it (bpy_types
    _GenericUI), else ``draw``."""
    return getattr(cls.draw, "_draw_funcs", [cls.draw])[0]


def patch_headers():
    """Swap only Blender's own draw (ui/own_draw.py), so UI appended to the header by others (e.g. the kit's Graph
    Editor toolbar) keeps drawing after it."""
    for name, fn in HEADERS:
        _own_draw.swap(name, fn)


def unpatch_headers():
    for name, fn in HEADERS:
        _own_draw.restore(name, fn)