# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the kit draws Maya joints: 3D Views of the Maya layout's workspaces whose Bones overlay is off (``settle``
turns it off once per screen, ``release_all`` gives it back), see-through views, and the skeletons a view shows
(``armatures``, ``_view_skeletons``). Related: ``maya_joints`` (drawing, the ``settle`` timer), ``maya_joints_cache``.
"""

import bpy


SETTLED = "allset_bones_settled"      # screen ID prop: the kit turned Blender's Bones overlay off in its 3D Views


def maya_workspace(workspace):
    from .. import switch
    try:
        return switch.is_maya_workspace(workspace)
    except (ReferenceError, AttributeError):
        return False


def is_maya_view(space, workspace):
    """A 3D View where the kit draws the joints (and Blender's bones are off)."""
    from . import toolbox
    return (space is not None and workspace is not None and space.type == 'VIEW_3D'
            and space.show_object_viewport_armature and not toolbox.is_toolbox(space)
            and space.overlay.show_overlays and not space.overlay.show_bones and maya_workspace(workspace))


def settle(window):
    """Turn Blender's Bones overlay off in the 3D Views of ``window``'s screen once (Maya layout workspaces only)."""
    from . import toolbox
    screen = window.screen
    # temporary screens (Preferences, file browser windows) can't be a context override and hold no 3D View
    if screen is None or screen.is_temporary or screen.get(SETTLED) or not maya_workspace(window.workspace):
        return False
    changed = False
    with bpy.context.temp_override(window=window, screen=screen):
        for area in screen.areas:
            space = area.spaces.active
            if area.type == 'VIEW_3D' and not toolbox.is_toolbox(space) and space.overlay.show_bones:
                space.overlay.show_bones = False
                area.tag_redraw()
                changed = True
    screen[SETTLED] = True
    return changed


def release_all():
    """Give Blender's bones back in every screen the kit settled (disable / Maya mode off)."""
    from . import toolbox
    for screen in bpy.data.screens:
        if not screen.get(SETTLED):
            continue
        for area in screen.areas:
            space = area.spaces.active
            if area.type == 'VIEW_3D' and not toolbox.is_toolbox(space):
                space.overlay.show_bones = True
                area.tag_redraw()
        del screen[SETTLED]


_ARMS = {}          # view layer pointer -> (layer generation, its armature objects in its object order)
_LAYER_GEN = [0]    # bumped by every update that can add, remove or re-include objects (Scene / Collection), edits


def armatures(view_layer):
    """The armature objects of ``view_layer`` in its object order. Read again only after an update that can add,
    remove, hide or re-include objects (a Scene or Collection update), an edit, undo or a file load: a redraw doesn't
    walk every object of the scene."""
    ptr = view_layer.as_pointer()
    got = _ARMS.get(ptr)
    if got is None or got[0] != _LAYER_GEN[0]:
        if len(_ARMS) > 16:
            _ARMS.clear()
        got = _ARMS[ptr] = (_LAYER_GEN[0], [ob for ob in view_layer.objects if ob.type == 'ARMATURE'])
    return got[1]


def _view_skeletons(context, space):
    """The skeletons this view shows, in the view layer's order (``context.visible_objects``): from the view layer's
    armatures (``armatures``) in a redraw; a context that isn't Blender's lists its own visible objects."""
    if isinstance(context, bpy.types.Context):
        for _try in range(2):
            try:
                return [ob for ob in armatures(context.view_layer)
                        if ob.visible_get() and ob.visible_in_viewport_get(space)]
            except ReferenceError:              # removed since the list was read
                _ARMS.clear()
    return [ob for ob in context.visible_objects if ob.type == 'ARMATURE' and ob.visible_in_viewport_get(space)]


def see_through(space):
    """Joints draw over every surface: X-Ray Joints, a wireframe view (no surface hides a joint, like Maya) or
    X-Ray shading."""
    shading = space.shading
    return bool(space.overlay.show_xray_bone or shading.type == 'WIREFRAME' or shading.show_xray)
