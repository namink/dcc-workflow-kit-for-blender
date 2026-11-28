# SPDX-License-Identifier: GPL-3.0-or-later
"""Which editors get the Maya editor chrome and whether it is on: ``enabled`` (the Panel Menus preference),
``is_graph`` / ``is_dope`` / ``is_uv`` (test a space) and ``GE`` / ``DS`` / ``UV`` (the editor names). The shared base
of the editor_* and graph_* modules; ``editor_chrome`` registers them all.
"""


GE, DS, UV = "Graph Editor", "Dope Sheet", "UV Editor"


def enabled(context):
    """Maya editor chrome follows the Panel Menus preference (Maya menus in editor headers)."""
    from .. import preferences
    try:
        return preferences.get(context).maya_panel_menus
    except (KeyError, AttributeError):    # add-on prefs gone (disable in progress) / a context without preferences
        return False


def is_graph(space):
    return space is not None and space.type == 'GRAPH_EDITOR' and space.mode == 'FCURVES'


def is_dope(space):
    return space is not None and space.type == 'DOPESHEET_EDITOR' and space.mode in {'DOPESHEET', 'ACTION'}


def is_uv(space):
    return space is not None and space.type == 'IMAGE_EDITOR' and space.mode == 'UV'
