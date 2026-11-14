# SPDX-License-Identifier: GPL-3.0-or-later
"""Kit-drawn panels follow the Blender theme (#312).

The panels the kit draws itself (the Graph Editor / Dope Sheet list, the Time Slider ruler, the Range Slider) use
Maya's greys. With a changed theme they move with it: each grey gets the difference between the theme's colour
and Blender's factory colour for the same place (an editor's background or text). With the factory theme the
difference is zero, so the panels keep their Maya look; a light theme makes them light, with dark text.
Colours that mean something (selection blue, axis colours, the red time range) stay as they are. The theme is
only read.
"""

import bpy

# Blender 5.2's factory theme: editor background 48/255, text 166/255 (Graph Editor, Dope Sheet / Timeline)
FACTORY = {"back": (48 / 255,) * 3, "text": (166 / 255,) * 3}
FIELDS = tuple(FACTORY)


def theme_color(editor, field):
    """The theme's ``editor.space.<field>`` colour (RGB), or None."""
    try:
        return tuple(getattr(getattr(bpy.context.preferences.themes[0], editor).space, field))[:3]
    except (AttributeError, IndexError, TypeError):
        return None


def follow(color, editor, field):
    """``color`` (RGB or RGBA) moved by the theme's difference from the factory theme for ``editor`` / ``field``
    ("back" for fills, "text" for text and thin marks)."""
    cur = theme_color(editor, field)
    if cur is None:
        return tuple(color)
    base = FACTORY[field]
    rgb = tuple(min(1.0, max(0.0, c + cur[i] - base[i])) for i, c in enumerate(color[:3]))
    return rgb + tuple(color[3:])


def editor_of(space):
    """Theme editor name for a space: the Graph Editor's own, else the Dope Sheet's (Timeline, Dope Sheet)."""
    return "graph_editor" if getattr(space, "type", "") == 'GRAPH_EDITOR' else "dopesheet_editor"
