# SPDX-License-Identifier: GPL-3.0-or-later
"""Toggle an editor window from a hotkey (#541): the kit Hotkey Editor's Custom Scripts > Windows commands. A Maya user
binds such a toggle with a small script of their own (Maya's Windows menu items only open); the kit lists them ready
to bind. The editor shown in a floating window: that window closes. Otherwise the Windows menu item runs, as from
the menu (it opens the window, or raises the panel where it is docked)."""

import bpy
from bpy.props import EnumProperty

# key: (label, Windows menu item, test of a floating window's screen)
WINDOWS = {
    'UV_EDITOR': ("UV Editor", "Windows/Modeling Editors/UV Editor", ('UI_TYPE', 'UV')),
    'OUTLINER': ("Outliner", "Windows/Outliner", ('UI_TYPE', 'OUTLINER')),
    'HYPERSHADE': ("Hypershade", "Windows/Rendering Editors/Hypershade", ('HYPERSHADE', None)),
    'GRAPH_EDITOR': ("Graph Editor", "Windows/Animation Editors/Graph Editor", ('UI_TYPE', 'FCURVES')),
    'DOPE_SHEET': ("Dope Sheet", "Windows/Animation Editors/Dope Sheet", ('UI_TYPE', 'DOPESHEET')),
    'TRAX_EDITOR': ("Trax Editor", "Windows/Animation Editors/Trax Editor", ('UI_TYPE', 'NLA_EDITOR')),
    'NODE_EDITOR': ("Node Editor", "Windows/Node Editor", ('UI_TYPE', 'ShaderNodeTree')),
    'SPREAD_SHEET': ("Attribute Spread Sheet", "Windows/General Editors/Attribute Spread Sheet",
                     ('UI_TYPE', 'SPREADSHEET')),
}


def _shows(screen, test):
    kind, value = test
    if kind == 'HYPERSHADE':
        from ..ui import hypershade_window
        return hypershade_window.is_hypershade(screen)
    return any(a.ui_type == value for a in screen.areas)


def floating(context, key):
    """The floating windows (not the main window) that show editor ``key``."""
    test = WINDOWS[key][2]
    return [w for w in context.window_manager.windows if w.parent is not None and _shows(w.screen, test)]


class ALLSET_OT_window_toggle(bpy.types.Operator):
    """Open the editor's window, or close it when it is open in a window of its own"""
    bl_idname = "allset.window_toggle"
    bl_label = "Toggle Window"
    bl_options = {'REGISTER'}

    window: EnumProperty(items=[(k, v[0], "") for k, v in WINDOWS.items()])

    def execute(self, context):
        found = floating(context, self.window)
        if found:
            from ..ui import marked_window
            for w in found:
                marked_window.close_later(w)       # also the window this key was pressed in: closed from a timer
            return {'FINISHED'}
        return bpy.ops.allset.menu_item(item=WINDOWS[self.window][1])


classes = (ALLSET_OT_window_toggle,)
