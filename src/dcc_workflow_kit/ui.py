# SPDX-License-Identifier: GPL-3.0-or-later
import bpy
from bpy.props import EnumProperty
from .localization import CONTEXT, tr

_topbars = {}


def tag_global_areas():
    # Blender's global top bar is outside window.screen.areas.
    for pointer, area in list(_topbars.items()):
        try:
            area.tag_redraw()
        except ReferenceError:
            _topbars.pop(pointer, None)


class DCC_OT_switch(bpy.types.Operator):
    bl_idname = 'dcc_workflow.switch'
    bl_label = 'Switch Workflow'
    bl_translation_context = CONTEXT
    bl_description = 'Switch between Blender and the workflow selected in Preferences'
    mode: EnumProperty(items=(('TOGGLE', 'Toggle', ''), ('BLENDER', 'Blender', ''),
                              ('MAX', '3ds Max', ''), ('MAYA', 'Maya', '')), default='TOGGLE')

    def execute(self, context):
        from . import core
        from .preferences import get
        target = self.mode
        if target == 'TOGGLE':
            target = get().profile if core.current() == 'BLENDER' else 'BLENDER'
        try:
            core.request(target)
        except (RuntimeError, ValueError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


def draw_controls(layout, context):
    from . import core
    from .preferences import get
    if context.area is not None and context.area.type == 'TOPBAR':
        _topbars[context.area.as_pointer()] = context.area
    try:
        prefs = get(context)
    except KeyError:
        return
    row = layout.row(align=True)
    row.enabled = not core.busy()
    row.operator(DCC_OT_switch.bl_idname, text='Blender', depress=core.current() == 'BLENDER').mode = 'BLENDER'
    row.operator(DCC_OT_switch.bl_idname, text='3ds Max' if prefs.profile == 'MAX' else 'Maya',
                 depress=core.current() == prefs.profile).mode = prefs.profile
    if core.busy():
        row.label(text=tr('Switching…'), icon='TIME')
    if prefs.last_error:
        row.label(text=tr('Switch failed'), icon='ERROR')


def draw_switch(self, context):
    if context.region and context.region.alignment == 'RIGHT':
        draw_controls(self.layout, context)


def draw_edit(self, context):
    self.layout.separator()
    self.layout.operator(DCC_OT_switch.bl_idname, text=tr('Switch Workflow'))


_keymaps = []
_owned_maps = []


def register():
    bpy.utils.register_class(DCC_OT_switch)
    bpy.types.TOPBAR_HT_upper_bar.append(draw_switch)
    bpy.types.TOPBAR_MT_edit.append(draw_edit)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:
        existing = kc.keymaps.find('Window', space_type='EMPTY', region_type='WINDOW')
        km = kc.keymaps.new(name='Window', space_type='EMPTY')
        if existing is None:
            _owned_maps.append((kc, km))
        kmi = km.keymap_items.new(DCC_OT_switch.bl_idname, 'M', 'PRESS', ctrl=True, alt=True, shift=True)
        _keymaps.append((km, kmi))


def unregister():
    _topbars.clear()
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
    for kc, km in _owned_maps:
        if not km.keymap_items:
            kc.keymaps.remove(km)
    _owned_maps.clear()
    bpy.types.TOPBAR_MT_edit.remove(draw_edit)
    bpy.types.TOPBAR_HT_upper_bar.remove(draw_switch)
    bpy.utils.unregister_class(DCC_OT_switch)
