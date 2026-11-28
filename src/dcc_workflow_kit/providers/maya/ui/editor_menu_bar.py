# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya menu bar in editor headers: the editor's Maya menus, a Panels menu when it sits in a pane and Blender's own
menus in a "Blender" menu at the end (one folded menu when the header hides menus). Entry points ``draw_menu_bar``,
``draw_menus``; also used by the Hypershade, Script Editor, Trax Editor and other kit windows.
"""

import bpy

from . import editor_menu_data, menu_sets
from .editor_kinds import GE, DS, UV


# --- menu bars ---------------------------------------------------------------------------------------------------

BLENDER_MENUS = {GE: "GRAPH_MT_editor_menus", DS: "DOPESHEET_MT_editor_menus", UV: "IMAGE_MT_editor_menus",
                 # Hypershade / Script Editor windows
                 "Hypershade": "NODE_MT_editor_menus", "Script Editor": "INFO_MT_editor_menus",
                 "Trax Editor": "NLA_MT_editor_menus"}


def _blender_menu_class(editor):
    def draw(self, context):
        layout = self.layout
        if editor == DS:
            layout.prop(context.space_data, "ui_mode", text="")
            layout.separator()
        getattr(bpy.types, BLENDER_MENUS[editor]).draw(self, context)
    idname = "ALLSET_MT_ed_blender_" + editor.replace(" ", "").lower()
    return type(idname, (bpy.types.Menu,), {"bl_idname": idname, "bl_label": "Blender", "draw": draw,
                                             "__doc__": f"Blender's own {editor} menus"})


def _bar_class(editor):
    def draw(self, context):
        draw_menu_bar(self.layout, context, editor)
    idname = "ALLSET_MT_ed_bar_" + editor.replace(" ", "").lower()
    return type(idname, (bpy.types.Menu,), {"bl_idname": idname, "bl_label": "Menus", "draw": draw,
                                             "__doc__": f"The Maya {editor} menus folded into one menu"})


_BLENDER = {ed: _blender_menu_class(ed) for ed in BLENDER_MENUS}
_BAR = {ed: _bar_class(ed) for ed in BLENDER_MENUS}


def draw_menu_bar(layout, context, editor):
    from . import editor_panels
    for i, (title, _items) in enumerate(editor_menu_data.EDITORS[editor]):
        layout.menu(menu_sets.editor_menu_idname(editor, i), text=title)
    if editor_panels.is_pane(context):
        # Maya: an editor in a pane has the viewport's Panels menu (Panel ▸ other editors, Tear Off...); a torn-off
        # window has none (#319)
        layout.menu("ALLSET_MT_panel_panels", text="Panels")
    if editor in _BLENDER:
        layout.menu(_BLENDER[editor].bl_idname, text="Blender")


def draw_menus(layout, context, editor):
    from . import editor_panels
    if editor_panels.floating_editor(context):
        from . import maya_dock      # the dotted handle: Dock Bottom / Left / Right / Top, Close (#319)
        maya_dock.draw_handle(layout)
    if context.area is None or context.area.show_menus:
        draw_menu_bar(layout.row(align=True), context, editor)
    else:
        layout.menu(_BAR[editor].bl_idname, text="", icon='COLLAPSEMENU')
