# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format
'Blender Max: original, reversible studio workflow extension.'
import bpy
__version__ = '0.6.8'
from bpy.props import PointerProperty
from . import max_gizmo
from . import preferences, params, operators, editors, ui, runtime, chrome, toolbar, interactions, commands, flyouts, quad, max_menus, material_ui, animation_ui, utility_editors, scene_ui, trackbar
CLASSES = preferences.CLASSES + ui.CLASSES + operators.CLASSES + editors.CLASSES + chrome.CLASSES + toolbar.CLASSES + interactions.CLASSES + commands.CLASSES + flyouts.CLASSES + quad.CLASSES + tuple(max_menus.CLASSES) + material_ui.CLASSES + animation_ui.CLASSES + utility_editors.CLASSES + scene_ui.CLASSES + trackbar.CLASSES
CLASSES += max_gizmo.CLASSES
_registered = []
LEGACY_IDS = ('blender_studio_max',)
MIGRATED_PREFERENCES = ('enabled_mode', 'studio_colors', 'splash_image', 'last_material_editor')

def _take_legacy():
    """Disable a still-enabled Blender Studio Max and return its preferences.

    Both register the same operators and properties, so the old one must go before this
    one registers. Its own shutdown turns Max mode off and restores Blender's colors from
    its theme snapshot, so the snapshot itself is not carried over."""
    import addon_utils
    values = None
    for key in list(bpy.context.preferences.addons.keys()):
        if key == __package__ or key.rsplit('.', 1)[-1] not in LEGACY_IDS:
            continue
        old = getattr(bpy.context.preferences.addons[key], 'preferences', None)
        if old is not None and values is None:
            values = {name: getattr(old, name) for name in MIGRATED_PREFERENCES if hasattr(old, name)}
        try:
            addon_utils.disable(key, default_set=True)
        except Exception as error:
            print(_msg('Blender Max: could not disable'), key, error)
    return values

def _give_legacy(values):
    prefs = runtime.preferences()
    if not values or prefs is None:
        return
    for (name, value) in values.items():
        try:
            setattr(prefs, name, value)
        except (AttributeError, TypeError, ValueError):
            pass
    print(_msg('Blender Max: preferences migrated from Blender Studio Max'))

def register():
    try:
        legacy = _take_legacy()
        params.register()
        for cls in CLASSES:
            bpy.utils.register_class(cls)
            _registered.append(cls)
        bpy.types.WindowManager.bsm = PointerProperty(type=ui.BSM_State, translation_context=_msg('DCCWorkflowKit.Max'))
        material_ui.register_data()
        bpy.types.TOPBAR_HT_upper_bar.append(ui.draw_switch)
        max_gizmo.register_tool()
        _give_legacy(legacy)
        runtime.register()
    except Exception:
        unregister()
        raise

def unregister():
    max_gizmo.unregister_tool()
    runtime.unregister()
    material_ui.unregister_data()
    try:
        bpy.types.TOPBAR_HT_upper_bar.remove(ui.draw_switch)
    except (ValueError, RuntimeError):
        pass
    if hasattr(bpy.types.WindowManager, 'bsm'):
        del bpy.types.WindowManager.bsm
    for cls in reversed(_registered):
        if getattr(cls, 'is_registered', True):
            try:
                bpy.utils.unregister_class(cls)
            except RuntimeError:
                pass
    _registered.clear()
    params.unregister()
