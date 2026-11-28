# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared state of the Maya keymap patches: ``ADDED`` (every binding the patches add, with the keymaps allowed to
shadow it) and ``_add`` (adds one item and records it), plus keymap-name lists used by several ``maya_patches_*``
files. ``ADDED`` is filled in place and never rebound; ``maya_patches.apply`` clears it.
"""

# (km_name, idname, event, props, shadows) for every binding added below.
# ``shadows``: keymaps allowed to bind the same event in the same editor
# (intentional: e.g. paint modes keep their own X/B).
ADDED = []


def _add(kd, km_name, idname, event, props=None, shadows=(), first=False):
    kd.add(km_name, idname, event, props, first=first)
    ADDED.append((km_name, idname, event, dict(props or {}), tuple(shadows)))


# Paint / sculpt mode keymaps, checked before "3D View": they keep their own keys (shadows of 3D View items).
_PAINT_MODES = ("Sculpt", "Vertex Paint", "Image Paint", "Weight Paint")


# Arrow keys and their pick-walk direction (objects, components, joints, the kit's Outliner tree).
PICK_WALK_KEYS = (("UP_ARROW", "UP"), ("DOWN_ARROW", "DOWN"),
                  ("LEFT_ARROW", "LEFT"), ("RIGHT_ARROW", "RIGHT"))


# Transform tool keymaps (they run before "3D View"): the Channel Box slider and the emulated tumble go
# first there.
SLIDER_TOOL_KEYMAPS = ("3D View Tool: Move", "3D View Tool: Rotate", "3D View Tool: Scale",
                       "3D View Tool: Transform")


# The UV Editor's keymap.
UV_KM = "UV Editor"


# Editors / modes whose keymaps run before "3D View" with the same events: they keep them (shadows of
# 3D View items).
VIEW3_SHADOWS = ("Sculpt", "Font", "Text", "File Browser", "Sequencer", "Clip", "Node Editor", "Grease Pencil Selection")
