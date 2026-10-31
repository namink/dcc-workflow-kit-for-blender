# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese display integration by namink.
"""Maya Outliner chrome on Blender's Outliner (docs/steps/step_50.md 「계획」 3).

Maya's Outliner has a menu bar Display / Show / Help and a search field.
Outliners set up the Maya way (the Maya Workflow Kit layout and Windows > Outliner:
View Layer mode, no collection rows, no object contents; ``is_maya_outliner``) get that header:
``OUTLINER_HT_header.draw`` is swapped while the kit is enabled and restored on unregister; other
Outliners draw as usual. The rows themselves are Blender's (the C list): Maya's grey camera rows
(persp/top/front/side) and default sets have no Blender objects behind them.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
from . import chrome, own_draw
HELP_URL = 'https://docs.blender.org/manual/en/4.5/editors/outliner/index.html'
MENU_BAR = ((_dcc_source('Display'), 'ALLSET_MT_outliner_display'), (_dcc_source('Show'), 'ALLSET_MT_outliner_show'), (_dcc_source('Help'), 'ALLSET_MT_outliner_help'))

def is_maya_outliner(space):
    return space is not None and space.type == 'OUTLINER' and (space.display_mode == 'VIEW_LAYER') and (not space.use_filter_collection) and (not space.use_filter_object_content)

def setup(space):
    """Maya Outliner filters (DAG only, from the world; no eye / mode column: Maya hides with H)."""
    space.display_mode = 'VIEW_LAYER'
    space.use_filter_object_content = False
    space.use_filter_collection = False
    space.use_filter_children = True
    space.show_restrict_column_render = False
    space.show_restrict_column_hide = False
    space.show_mode_column = False
    space.use_sort_alpha = False

class ALLSET_MT_outliner_display(bpy.types.Menu):
    """Maya Outliner Display menu"""
    bl_translation_context = 'MWK:ui/maya_outliner.py:42'
    bl_label = _zh_native('Display', 'MWK:ui/maya_outliner.py:42')

    def draw(self, context):
        (sp, lay) = (context.space_data, self.layout)
        lay.prop(sp, 'use_filter_children', text=_zh('Children (DAG Hierarchy)', 'MWK:ui/maya_outliner.py:46'))
        lay.prop(sp, 'use_sort_alpha', text=_zh('Sort Alphabetically', 'MWK:ui/maya_outliner.py:47'))
        lay.prop(sp, 'show_restrict_column_hide', text=_zh('Visibility Column', 'MWK:ui/maya_outliner.py:48'))
        lay.separator()
        lay.prop(sp, 'use_filter_object_content', text=_zh('Shapes', 'MWK:ui/maya_outliner.py:51'))

class ALLSET_MT_outliner_show(bpy.types.Menu):
    """Maya Outliner Show menu: object type filters"""
    bl_translation_context = 'MWK:ui/maya_outliner.py:56'
    bl_label = _zh_native('Show', 'MWK:ui/maya_outliner.py:56')

    def draw(self, context):
        (sp, lay) = (context.space_data, self.layout)
        lay.prop(sp, 'use_filter_object', text=_zh('Objects', 'MWK:ui/maya_outliner.py:60'))
        col = lay.column()
        col.active = sp.use_filter_object
        for (prop, label) in (('use_filter_object_mesh', _dcc_source('Geometry')), ('use_filter_object_armature', _dcc_source('Joints')), ('use_filter_object_empty', _dcc_source('Groups / Locators')), ('use_filter_object_light', _dcc_source('Lights')), ('use_filter_object_camera', _dcc_source('Cameras')), ('use_filter_object_others', _dcc_source('Others'))):
            col.prop(sp, prop, text=_zh(label, 'MWK:ui/maya_outliner.py:66'))

class ALLSET_MT_outliner_help(bpy.types.Menu):
    bl_translation_context = 'MWK:ui/maya_outliner.py:70'
    bl_label = _zh_native('Help', 'MWK:ui/maya_outliner.py:70')

    def draw(self, context):
        self.layout.operator('wm.url_open', text=_zh('Help on Outliner', 'MWK:ui/maya_outliner.py:73')).url = HELP_URL

def _draw(self, context):
    space = context.space_data
    if not is_maya_outliner(space):
        return own_draw.original('OUTLINER_HT_header', _draw)(self, context)
    layout = self.layout
    from . import maya_dock
    layout.operator('allset.dock_handle', text=_zh(maya_dock.HANDLE[:8], 'MWK:ui/maya_outliner.py:82'), emboss=False)
    chrome.menu_bar(layout, MENU_BAR)
    layout.prop(space, 'filter_text', text=_dcc_display(''), icon='VIEWZOOM', placeholder=_dcc_display(_dcc_source('Search...')))
classes = (ALLSET_MT_outliner_display, ALLSET_MT_outliner_show, ALLSET_MT_outliner_help)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    own_draw.swap('OUTLINER_HT_header', _draw)

def unregister():
    own_draw.restore('OUTLINER_HT_header', _draw)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
