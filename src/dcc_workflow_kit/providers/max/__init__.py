# SPDX-License-Identifier: GPL-3.0-or-later
"""MaxFlow (Blender Max): original, reversible studio workflow extension."""
# Read only when the folder is copied into scripts/addons by hand; as an extension Blender
# uses blender_manifest.toml. tools/build.py checks that both agree.
bl_info = {
    "name": "MaxFlow",
    "author": "neom315",
    "version": (0, 8, 5),
    "blender": (5, 0, 0),
    "location": "Top bar > MaxFlow",
    "description": "A 3ds Max-style workspace, Command Panel and quad menus",
    "doc_url": "https://neom315.github.io/blender-max/",
    "category": "Interface",
}

import bpy
__version__ = '0.8.5'
from bpy.props import PointerProperty
from . import max_gizmo, edit_poly, i18n
from . import (preferences, params, operators, editors, ui, runtime, chrome, toolbar, interactions, commands, flyouts, quad,
               max_menus, material_ui, animation_ui, utility_editors, scene_ui, trackbar)

CLASSES = (preferences.CLASSES+ui.CLASSES+operators.CLASSES+editors.CLASSES+chrome.CLASSES+toolbar.CLASSES
           +interactions.CLASSES+commands.CLASSES+flyouts.CLASSES+quad.CLASSES+tuple(max_menus.CLASSES)
           +material_ui.CLASSES+animation_ui.CLASSES+utility_editors.CLASSES+scene_ui.CLASSES+trackbar.CLASSES)
CLASSES += max_gizmo.CLASSES
_registered = []

def unregister():
    edit_poly.unregister()
    max_gizmo.unregister_tool()
    runtime.unregister()
    material_ui.unregister_data()
    if hasattr(bpy.types.WindowManager, 'bsm'):
        del bpy.types.WindowManager.bsm
    for cls in reversed(_registered):
        if getattr(cls, 'is_registered', True):
            bpy.utils.unregister_class(cls)
    _registered.clear()
    params.unregister()
