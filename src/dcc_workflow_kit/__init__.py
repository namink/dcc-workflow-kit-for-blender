# SPDX-License-Identifier: GPL-3.0-or-later
"""DCC Workflow Kit: one selected Max or Maya workflow alongside Blender."""
import bpy
from bpy.props import PointerProperty
from . import lifecycle, localization, preferences, ui, core, migration
from .providers import max as max_provider, maya

bl_info = {'name': 'DCC Workflow Kit', 'author': 'DCC Workflow Kit contributors; original authors credited in THIRD_PARTY.md',
           'version': (0, 1, 1), 'blender': (5, 1, 0), 'category': 'Interface',
           'description': 'Choose 3ds Max + Blender or Maya + Blender workflows'}


def _check_conflicts():
    # Same operator namespaces cannot coexist with standalone installs.
    for name in ('BSM_OT_environment', 'ALLSET_OT_switch_mode'):
        if hasattr(bpy.types, name):
            raise RuntimeError('Disable the standalone Blender Max / Maya Workflow Kit add-on before enabling DCC Workflow Kit.')


def _register_preferences():
    for cls in preferences.CLASSES:
        bpy.utils.register_class(cls)
    preferences._migrating = True
    try:
        preferences.migrate_existing()
        # Backend flags describe the live process; only the unified startup choice persists.
        prefs = preferences.get()
        prefs.max_settings.enabled_mode = False
        prefs.maya_settings.maya_mode = False
        prefs.maya_settings.start_in_maya_layout = False
    finally:
        preferences._migrating = False


def _unregister_preferences():
    for cls in reversed(preferences.CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)


def _register_max_data():
    max_provider.params.register()
    for cls in max_provider.CLASSES:
        if cls in max_provider.preferences.CLASSES:
            continue
        bpy.utils.register_class(cls)
        max_provider._registered.append(cls)
    bpy.types.WindowManager.bsm = PointerProperty(type=max_provider.ui.BSM_State)
    max_provider.material_ui.register_data()
    max_provider.runtime.register()


def _unregister_max_data():
    max_provider.unregister()


def register():
    _check_conflicts()
    lifecycle.activate(__name__, [
        (localization.register, localization.unregister),
        (maya.i18n.register, maya.i18n.unregister),
        (_register_preferences, _unregister_preferences),
        (_register_max_data, _unregister_max_data),
        (maya.operators.register_data, maya.operators.unregister_data),
        (maya.switch.register, maya.switch.unregister),
        (migration.register, migration.unregister),
        (ui.register, ui.unregister),
        (core.register, core.unregister),
    ])
    maya.i18n.refresh()


def unregister():
    lifecycle.deactivate(__name__)
