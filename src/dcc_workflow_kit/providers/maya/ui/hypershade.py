# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Hypershade = its own window, laid out the Maya way (issue #25; before:
a Shader Editor + sidebar tab).

Maya's standard Hypershade is a
floating window: the menu bar (File / Edit / View / Create / Tabs / Graph / Window / Options / Help) over the Browser
(top-left: toolbar, 10 swatch tabs, swatch grid), Material Viewer (top-right), Create (bottom-left: category tree +
node list), the Graph work area (centre: graph toolbar, "Untitled_1" tab, node editor) and the Property Editor
(bottom-right). ``allset.hypershade`` builds the same arrangement out of Blender areas in a new window
(``hypershade_layout`` = Maya's proportions as ``area_split`` steps, made one per timer tick):

- menu strip = a Shader Editor one header high whose header draws only the Maya menus (``NODE_HT_header``'s own draw
  swapped, ``own_draw``); items in ``editor_menu_map`` "Hypershade/...";
- Graph = a Shader Editor whose header is Maya's graph toolbar (``editor_icon_data.ICONS["Hypershade"]``) + Blender's
  node menus folded into "Blender"; a drawn "Untitled_1" tab at its top-left;
- Browser / Create / Material Viewer / Property Editor = Properties editors on the Tool tab (the Maya dock
  mechanism), marked by hidden tab flags (``MARK`` + ``PANE_FLAGS``) and drawn by ``ALLSET_PT_hypershade_pane``.

The Hypershade's current material (Browser click, Create, Edit menu) shows in the Graph (the active object's slot
when it has it, else the Graph is pinned to it), the Material Viewer and the Property Editor.
Windows > Rendering Editors > Hypershade, the Status Line icon and the hotbox's Windows menu all run
``allset.hypershade``; other Shader Editors keep the Maya menu bar in their header (``draw_collapsible``).

Code: ``hypershade_window`` (areas, building the window), ``hypershade_materials`` (current material, Browser
items), ``hypershade_ops`` (commands), ``hypershade_panes`` (pane drawing), ``hypershade_graph`` (Graph commands,
headers); this module keeps the classes tuple, register / unregister and re-exports the names used elsewhere.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

# the split-out parts, also read through this module by other UI and the tests
from .hypershade_window import (HS, MARK, PANE_FLAGS, PANE_LABELS, pane, context_pane, set_pane,  # noqa: F401
                                is_hypershade, graph_area, menu_area, hypershade_windows, build_later)
from .hypershade_materials import (COLUMNS, TABS, MAYA_ONLY_TABS, SWATCHES, SORTS,  # noqa: F401
                                   SWATCH_ICONS, SORT_ICONS, TEXTURE_NODES, SHADER_NODES, materials, current,
                                   assigned_materials, release_editors, show, browser_items, icon_value)
from .hypershade_ops import (ALLSET_OT_hypershade, ALLSET_OT_hs_pick, PICK_PROP, _get_pick,  # noqa: F401
                             _set_pick, ALLSET_OT_hs_item, ALLSET_OT_hs_create, ALLSET_OT_hs_node,
                             ALLSET_OT_hs_edit)
from .hypershade_panes import (CREATE_CATEGORIES, MAYA_KEYS, DISPLACEMENT, FAVORITES, PANE_NOTICES,  # noqa: F401
                               create_items, draw_title, draw_browser, draw_create, draw_viewer,
                               draw_property_editor, ALLSET_OT_hs_noop, ALLSET_PT_hypershade_pane)
from .hypershade_graph import (_linked, ALLSET_OT_hs_graph, _node_header, draw_graph_tab,  # noqa: F401
                               draw_collapsible, patch_header, unpatch_header)
from .hypershade_blender import ALLSET_OT_hs_shader


classes = (ALLSET_OT_hypershade, ALLSET_OT_hs_pick, ALLSET_OT_hs_item, ALLSET_OT_hs_create, ALLSET_OT_hs_node,
           ALLSET_OT_hs_shader,
           ALLSET_OT_hs_edit, ALLSET_OT_hs_graph, ALLSET_OT_hs_noop, ALLSET_PT_hypershade_pane)
_handles = []
_WM_PROPS = ("allset_hs_material", "allset_hs_tab", "allset_hs_swatch", "allset_hs_sort", "allset_hs_reverse",
             "allset_hs_filter", "allset_hs_create_cat", "allset_hs_create_filter")


def register():
    from . import notices, own_draw
    wm = bpy.types.WindowManager
    wm.allset_hs_material = StringProperty(name="Hypershade Material", options={'SKIP_SAVE'})
    wm.allset_hs_tab = EnumProperty(name="Browser Tab", items=TABS, options={'SKIP_SAVE'})
    wm.allset_hs_swatch = EnumProperty(name="Swatch Size", items=[s[:3] for s in SWATCHES], default='MEDIUM',
                                         options={'SKIP_SAVE'})
    wm.allset_hs_sort = EnumProperty(name="Sort", items=SORTS, options={'SKIP_SAVE'})
    wm.allset_hs_reverse = BoolProperty(name="Reverse Order", description="Sort in reverse order",
                                          options={'SKIP_SAVE'})
    wm.allset_hs_filter = StringProperty(name="Search", description="Show only the swatches whose name has this text",
                                          options={'SKIP_SAVE', 'TEXTEDIT_UPDATE'})
    wm.allset_hs_create_cat = EnumProperty(
        name="Create Category", items=[(k, label, f"Create > {label}") for k, label, _s in CREATE_CATEGORIES],
        default='MAYA', options={'SKIP_SAVE'})
    wm.allset_hs_create_filter = StringProperty(name="Search Node Types",
                                                 description="List the node types whose name has this text",
                                                 options={'SKIP_SAVE', 'TEXTEDIT_UPDATE'})
    bpy.types.Material.allset_hs_pick = BoolProperty(
        name="Pick Material", description=ALLSET_OT_hs_pick.__doc__, get=_get_pick, set=_set_pick,
        options={'SKIP_SAVE'})
    for cls in classes:
        bpy.utils.register_class(cls)
    patch_header()
    own_draw.swap("NODE_HT_header", _node_header)
    _handles.append(bpy.types.SpaceNodeEditor.draw_handler_add(draw_graph_tab, (), 'WINDOW', 'POST_PIXEL'))
    notices.PANEL_NOTICES.update(PANE_NOTICES)


def unregister():
    from . import notices, own_draw
    for key in PANE_NOTICES:
        notices.PANEL_NOTICES.pop(key, None)
    while _handles:
        bpy.types.SpaceNodeEditor.draw_handler_remove(_handles.pop(), 'WINDOW')
    own_draw.restore("NODE_HT_header", _node_header)
    unpatch_header()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    for name in _WM_PROPS:
        delattr(bpy.types.WindowManager, name)
    del bpy.types.Material.allset_hs_pick
