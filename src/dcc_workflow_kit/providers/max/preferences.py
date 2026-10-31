# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format
import bpy
from bpy.props import BoolProperty, StringProperty, EnumProperty

def _splash_changed(self, context):
    from . import runtime
    runtime.apply_splash(runtime.is_active())

class BSM_Preferences(bpy.types.PropertyGroup):
    enabled_mode: BoolProperty(name=_msg('Start in Blender Max'), default=False, translation_context=_msg('DCCWorkflowKit.Max'))
    studio_colors: BoolProperty(name=_msg('Max gray colors'), default=True, description=_msg('Temporarily apply original gray UI colors; restore the previous colors on exit'), translation_context=_msg('DCCWorkflowKit.Max'))
    theme_backup: StringProperty(default='', options={'HIDDEN'}, translation_context=_msg('DCCWorkflowKit.Max'))
    splash_image: StringProperty(name=_msg('Custom Splash Image'), subtype='FILE_PATH', update=_splash_changed, description=_msg("PNG or JPEG shown as Blender's splash screen while Max mode is on. Blender's own splash is 1000 x 500 px; the version number is drawn at the top right"), translation_context=_msg('DCCWorkflowKit.Max'))
    last_material_editor: EnumProperty(name=_msg('Material Editor'), items=(('MATERIAL', _msg('Slate'), ''), ('COMPACT', _msg('Compact'), '')), default='MATERIAL', translation_context=_msg('DCCWorkflowKit.Max'))

    def draw(self, context):
        from . import runtime
        layout = self.layout
        layout.label(text=_dcc_ui_text(_msg('Blender Max · 0.6.8 development preview')))
        layout.prop(self, 'last_material_editor')
        row = layout.row(align=True)
        row.operator('bsm.environment', text=_dcc_ui_text(_msg('Blender')), depress=not runtime.is_active()).mode = 'BLENDER'
        row.operator('bsm.environment', text=_dcc_ui_text(_msg('Blender Max')), depress=runtime.is_active()).mode = 'STUDIO'
        row = layout.row()
        row.enabled = not runtime.is_active()
        row.prop(self, 'studio_colors')
        layout.label(text=_dcc_ui_text(_msg('Switch back to Blender before changing the color option.')))
        row = layout.row(align=True)
        row.prop(self, 'splash_image')
        row.operator('wm.splash', text=_dcc_ui_text(''), icon='HIDE_OFF')
        layout.label(text=_dcc_ui_text(_msg('Splash: 1000 x 500 px like the original; used at startup while Max mode is on.')))
        layout.label(text=_dcc_ui_text(_msg('Materials, modifiers and animation use Blender data.')), icon='INFO')
        layout.operator('bsm.shortcuts', text=_dcc_ui_text(_msg('Shortcut Reference')), icon='HELP')
CLASSES = (BSM_Preferences,)
