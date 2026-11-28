# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya editor chrome for the Graph Editor, Dope Sheet and UV Editor.

Maya's editors:

- menu bars: Graph Editor Edit / View / Select / Curves / Keys / Tangents / List / Show / Help, Dope Sheet the same
  without Select, UV Editor Edit / Create / Select / Cut/Sew / Modify / Tools / View / Image / Textures / UV Sets /
  Help (structure ``editor_menu_data``, actions ``editor_menu_map``, classes built by ``menu_sets``);
- icon rows under them (the kit's own button names; Maya's order kept, Maya icons not copied);
- the Graph Editor's outliner lists the object and its attributes "Translate X" (red) / "Translate Y" (green), no
  Action / group rows.

Blender: ``GRAPH_HT_header.draw`` and ``DOPESHEET_HT_header.draw`` are swapped while the kit is on (restored on
unregister, ``tests/kit.py`` snapshots them); the UV Editor's header / tool header go through the ``ui/shelf.py``
``IMAGE_HT_header`` wrapper. Graph Editor and Dope Sheet areas have a single header row (no tool header region), so
the icon row follows the menus on it; the UV Editor's tool header is Maya's second row. Blender's own editor menus
stay in a "Blender" menu at the end of the bar.

Code: ``editor_kinds``, ``editor_menu_bar``, ``editor_icon_data`` / ``editor_icon_row``, ``editor_headers``,
``editor_open``, ``graph_channels``, ``graph_list``, ``graph_list_sync``, ``graph_outliner``; this module registers
them and re-exports their names.
"""

import bpy
from bpy.props import BoolProperty, StringProperty

from . import graph_icons, graph_layers
from .editor_kinds import GE, DS, UV, enabled, is_graph, is_dope, is_uv  # noqa: F401
from .editor_menu_bar import _BLENDER, _BAR, draw_menu_bar, draw_menus  # noqa: F401
from .editor_icon_data import GRAPH_ICONS, DOPE_ICONS, ICONS, NOTICES  # noqa: F401
from .editor_icon_row import (ALLSET_MT_editor_more, ALLSET_OT_editor_icon, ALLSET_OT_editor_icon_unavailable,
                              _FIRST_HIDDEN, _icon_spec, _kind, draw_icons, drop_stats, icon_groups, shown_groups, _stats_get,
                              _stats_set)  # noqa: F401
from .editor_headers import (_graph_header, _dope_header, _graph_footer, _dope_footer, _set_up, own_draw, toolbar_row,
                             setup_toolbar_row, release_toolbar_rows, draw_uv_header, draw_uv_tool_header,
                             patch_headers, unpatch_headers)  # noqa: F401
from .editor_open import frame_playback_range, prepare_later  # noqa: F401
from .graph_channels import (AXIS_COLOR, TEXT, _bone_name, _themed, attr_color, attr_label, character_curves,
                             maya_order, node_drivers, node_key, node_name, object_curves, one_pass,
                             shape_key)  # noqa: F401
from .graph_list import (AUTO, BONES, LIST_MARK, LOADED, FLAGS, FLAGS_ON, _ds, _expanded, _listed_nodes, _pinned,
                         _selected_objects, _up_label, auto_load, kit_list, listed_curves, listed_nodes, listed_objects,
                         loaded_names, row_id, row_objects, rows)  # noqa: F401
from .graph_list_sync import (ALLSET_OT_graph_list, ALLSET_OT_graph_attr_clear, _auto_get, _auto_set, _filters_changed,
                              _kit_hidden, _new_list, _redraw_editors, drawn_objects, load_selected, needs_kit_list,
                              release_all, set_auto_load, sync, sync_hidden, sync_space)  # noqa: F401
from .graph_outliner import (ALLSET_OT_graph_channel_click, ALLSET_OT_graph_channel_scroll, ALLSET_OT_graph_pin, BACK,
                             SELECT, _picked, _rect, _scroll, _target_rows, clamp_scroll, draw_channels, highlighted,
                             metrics, node_selected, pick_row, picked_ids, row_at, scroll_offset, selection_sig,
                             show_rows, visible_rows)  # noqa: F401


# --- registration --------------------------------------------------------------------------------------------------

classes = (ALLSET_OT_editor_icon, ALLSET_OT_editor_icon_unavailable, ALLSET_MT_editor_more, ALLSET_OT_graph_channel_click,
           ALLSET_OT_graph_channel_scroll, ALLSET_OT_graph_list, ALLSET_OT_graph_pin, ALLSET_OT_graph_attr_clear,
           *_BLENDER.values(), *_BAR.values())
_handle = []
_STATS_DROPS = ("animation_playback_pre", "animation_playback_post", "load_post")


@bpy.app.handlers.persistent
def _drop_stats(*_args):
    drop_stats()


@bpy.app.handlers.persistent
def _drop_stats_on_keys(_scene, depsgraph=None):
    if depsgraph is None or depsgraph.id_type_updated('ACTION'):
        drop_stats()


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.allset_key_time = StringProperty(
        name="Key Time", description="Maya Stats: the selected keys' time (type a frame, +=5 to move them)",
        get=_stats_get("time"), set=_stats_set("time"))
    bpy.types.Scene.allset_key_value = StringProperty(
        name="Key Value", description="Maya Stats: the selected keys' value (display units, +=5 / *=2 work)",
        get=_stats_get("value"), set=_stats_set("value"))
    bpy.types.WindowManager.allset_show_characters = BoolProperty(
        name="Characters", description="List only the character sets with their member attributes (Maya Show > "
        "Objects > Characters)", default=False, options={'SKIP_SAVE'}, update=_filters_changed)
    for name, label, tip in FLAGS:
        setattr(bpy.types.WindowManager, name, BoolProperty(
            name=label, description=f"Maya: {tip}", default=name in FLAGS_ON, options={'SKIP_SAVE'},
            update=_filters_changed))
    bpy.types.WindowManager.allset_auto_load = BoolProperty(
        name="Auto Load Selected Objects", description="Maya: the list follows the selection (off: Load / Add "
        "Selected Objects keep a fixed list)", get=_auto_get, set=_auto_set, options={'SKIP_SAVE'})
    graph_icons.register()
    for name in _STATS_DROPS:
        getattr(bpy.app.handlers, name).append(_drop_stats)
    bpy.app.handlers.depsgraph_update_post.append(_drop_stats_on_keys)
    patch_headers()
    _handle.append(bpy.types.SpaceGraphEditor.draw_handler_add(draw_channels, (), 'CHANNELS', 'POST_PIXEL'))
    graph_layers.register()


def unregister():
    graph_layers.unregister()
    while _handle:
        bpy.types.SpaceGraphEditor.draw_handler_remove(_handle.pop(), 'CHANNELS')
    unpatch_headers()
    for name in _STATS_DROPS:
        hs = getattr(bpy.app.handlers, name)
        if _drop_stats in hs:
            hs.remove(_drop_stats)
    if _drop_stats_on_keys in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_drop_stats_on_keys)
    drop_stats()
    graph_icons.unregister()
    del bpy.types.Scene.allset_key_time
    del bpy.types.Scene.allset_key_value
    del bpy.types.WindowManager.allset_show_characters
    release_all()
    for name, _label, _tip in FLAGS:
        delattr(bpy.types.WindowManager, name)
    del bpy.types.WindowManager.allset_auto_load
    _expanded.clear()
    _up_label.clear()
    _scroll.clear()
    _FIRST_HIDDEN.clear()
    _picked["ids"], _picked["sig"] = set(), None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
