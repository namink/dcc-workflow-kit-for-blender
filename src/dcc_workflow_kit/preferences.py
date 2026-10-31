# SPDX-License-Identifier: GPL-3.0-or-later
import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty
from .identity import package_id
from .localization import CONTEXT, tr
from .providers.max.preferences import BSM_Preferences
from .providers.maya.preferences import ALLSET_AddonPreferences

_migrating = False


def get(context=None):
    return (context or bpy.context).preferences.addons[package_id()].preferences


def _profile_changed(self, context):
    from . import core
    core.request('BLENDER')


class DCC_Preferences(bpy.types.AddonPreferences):
    bl_idname = package_id()
    profile: EnumProperty(name='Workflow Pair', translation_context=CONTEXT,
        items=(('MAX', '3ds Max + Blender', ''), ('MAYA', 'Maya + Blender', '')),
        default='MAX', update=_profile_changed)
    startup: EnumProperty(name='Startup Interface', translation_context=CONTEXT,
        items=(('BLENDER', 'Blender', ''), ('SELECTED', 'Selected Workflow', '')),
        default='BLENDER')
    max_settings: PointerProperty(type=BSM_Preferences)
    maya_settings: PointerProperty(type=ALLSET_AddonPreferences)
    last_error: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    migration_done: BoolProperty(default=False, options={'HIDDEN'})

    def draw(self, context):
        from . import core
        layout = self.layout
        layout.prop(self, 'profile')
        layout.prop(self, 'startup')
        from .ui import draw_controls
        draw_controls(layout, context)
        layout.label(text=tr('Changing the workflow pair returns to Blender. Both sets of settings are retained.'), icon='INFO')
        layout.label(text=tr('Interface language follows Blender. Scene data is preserved when switching.'))
        if self.last_error:
            box = layout.box()
            box.alert = True
            box.label(text=tr('Switch failed. Return to Blender and retry.'), icon='ERROR')
            # Wrap long exception text without hiding the useful cause.
            for line in self.last_error.splitlines():
                for offset in range(0, len(line), 100):
                    box.label(text=line[offset:offset + 100])
        box = layout.box()
        box.enabled = not core.busy()
        if self.profile == 'MAX':
            box.label(text=tr('3ds Max Settings'))
            box.prop(self.max_settings, 'studio_colors', text=tr('Max gray colors'))
            box.prop(self.max_settings, 'last_material_editor', text=tr('Material Editor'))
            box.prop(self.max_settings, 'splash_image', text=tr('Custom Splash Image'))
            box.label(text=tr('Color changes apply the next time Max mode starts.'))
        else:
            box.label(text=tr('Maya Settings'))
            box.operator('dcc_workflow.import_maya_shelves', text=tr('Import Maya Shelves'), icon='IMPORT')
            for name in ('lock_ortho_tumble', 'select_through', 'preselect_highlight',
                         'select_priority', 'maya_naming', 'maya_units', 'smart_duplicate',
                         'smart_extrude', 'parent_mode', 'marking_menu_style', 'hotbox_style',
                         'hotbox_all_sets', 'menu_set', 'maya_top_bar', 'maya_panel_menus',
                         'show_status_line', 'show_command_line', 'show_help_line',
                         'maya_toolbox', 'maya_viewcube', 'maya_selection_wire',
                         'maya_component_colors', 'maya_dock_colors', 'project_root'):
                box.prop(self.maya_settings, name)
            if core.current() == 'MAYA':
                box.operator('allset.new_maya_scene', icon='FILE_NEW')
        layout.label(text='DCC Workflow Kit 0.1.1 · Blender Max 0.6.8 · Maya Workflow Kit 0.6.2+zh.2')


CLASSES = (BSM_Preferences, ALLSET_AddonPreferences, DCC_Preferences)


def migrate_existing():
    """Copy readable original preferences; never disable or modify another extension."""
    prefs = get()
    if prefs.migration_done:
        return
    for addon in bpy.context.preferences.addons:
        short = addon.module.rsplit('.', 1)[-1]
        group = prefs.maya_settings if short == 'allset' else prefs.max_settings if short == 'blender_max' else None
        if group is None or addon.module == package_id():
            continue
        original = addon.preferences
        if original is None:
            continue
        for prop in group.bl_rna.properties:
            name = prop.identifier
            if name in {'rna_type', 'maya_mode', 'enabled_mode', 'theme_backup', 'start_in_maya_layout'}:
                continue
            if not hasattr(original, name) or prop.is_readonly or prop.type in {'COLLECTION', 'POINTER'}:
                continue
            try:
                setattr(group, name, getattr(original, name))
            except (TypeError, ValueError, AttributeError):
                pass
    prefs.max_settings.enabled_mode = False
    prefs.maya_settings.maya_mode = False
    prefs.maya_settings.start_in_maya_layout = False
    prefs.maya_settings.welcome_done = True
    prefs.migration_done = True
