# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender API differences between the supported versions (5.0 to 5.2).

Each name is the operator and properties to use on the running Blender, chosen by what
Blender actually provides rather than by version number.
"""
import bpy


def _has(group, name):
    return name in dir(getattr(bpy.ops, group))


# Blender 5.2 split Select Loop/Ring (mesh.loop_multi_select with ring=...) into two operators.
if _has('mesh', 'select_edge_loop_multi'):
    SELECT_LOOP = ('mesh.select_edge_loop_multi', {})
    SELECT_RING = ('mesh.select_edge_ring_multi', {})
else:
    SELECT_LOOP = ('mesh.loop_multi_select', {'ring': False})
    SELECT_RING = ('mesh.loop_multi_select', {'ring': True})
