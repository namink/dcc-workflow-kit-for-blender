# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Maya workspaces: Windows > Workspaces, the Status Line "Workspace:" dropdown, Reset Current Workspace (step 160, #81).

Maya 2022 lists its factory workspaces in this order (Windows > Workspaces;
dividers after General, XGen - Interactive Groom, Animation and Rendering - Expert), then the actions Reset /
Save / Import / Delete Current Workspace and Disable Docking/Undocking. "General" is shown as "Maya Classic".
Choosing one switches the menu set to its ``linkedMenu``. The kit's template (tools/make_startup.MAYA_WORKSPACES) carries eight of them; a file without one gets it
appended from the bundled template (``switch.append_workspace``), Reset replaces the current one with a fresh copy
(``switch.reset_workspace``). Each template workspace keeps its menu set and the raised tab of the right tab stack
in ID properties (``allset_menu_set`` / ``allset_dock_tab``), applied when the kit switches to it.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
from bpy.props import StringProperty
from .. import switch
FACTORY = ((_dcc_source('General'), _dcc_source('Maya Classic')), None, (_dcc_source('Modeling - Standard'), _dcc_source('Modeling - Standard')), (_dcc_source('Modeling - Expert'), _dcc_source('Modeling - Expert')), (_dcc_source('Sculpting'), _dcc_source('Sculpting')), (_dcc_source('Pose Sculpting'), _dcc_source('Pose Sculpting')), (_dcc_source('UV Editing'), _dcc_source('UV Editing')), ('XGen', 'XGen'), (_dcc_source('XGen - Interactive Groom'), _dcc_source('XGen - Interactive Groom')), None, (_dcc_source('Rigging'), _dcc_source('Rigging')), (_dcc_source('Animation'), _dcc_source('Animation')), None, (_dcc_source('Rendering - Standard'), _dcc_source('Rendering - Standard')), (_dcc_source('Rendering - Expert'), _dcc_source('Rendering - Expert')), None, ('MASH', 'MASH'), (_dcc_source('Motion Graphics'), _dcc_source('Motion Graphics')))
IN_TEMPLATE = (_dcc_source('General'), _dcc_source('Modeling - Standard'), _dcc_source('Modeling - Expert'), _dcc_source('Sculpting'), _dcc_source('UV Editing'), _dcc_source('Rigging'), _dcc_source('Animation'), _dcc_source('Rendering - Standard'))
LABELS = {name: label for (name, label) in (e for e in FACTORY if e)}
PATH = 'Windows/Workspaces/'
NOTICES = {PATH + _dcc_source('Pose Sculpting'): (_dcc_source('Sculpting'), _dcc_source('Blender has no pose space deformation editor: the Sculpting workspace and shape keys (Shape Editor) cover sculpted corrections.')), PATH + 'XGen': (_dcc_source('Hair curves'), _dcc_source('Blender grooms hair with hair curve objects and their sculpt mode, not XGen.')), PATH + _dcc_source('XGen - Interactive Groom'): (_dcc_source('Hair curves'), _dcc_source('Blender grooms hair with hair curve objects and their sculpt mode, not XGen.')), PATH + _dcc_source('Rendering - Expert'): (_dcc_source('Rendering - Standard'), _dcc_source("The kit carries Rendering - Standard; Blender's Render properties and Shader Editor are its editors.")), PATH + 'MASH': (_dcc_source('Geometry Nodes'), _dcc_source('Blender has no MASH: instancing networks are Geometry Nodes.')), PATH + _dcc_source('Motion Graphics'): (_dcc_source('Geometry Nodes'), _dcc_source('Blender has no MASH: instancing networks are Geometry Nodes.')), PATH + _dcc_source('Save Current Workspace As...'): (_dcc_source('Workspace tabs'), _dcc_source("Blender saves workspaces with the file: duplicate one from its tab's menu.")), PATH + _dcc_source('Import Workspace Files...'): (_dcc_source('File > Append'), _dcc_source('Blender brings workspaces from other files with File > Append > WorkSpace.')), PATH + _dcc_source('Delete Current Workspace'): (_dcc_source('Workspace tabs'), _dcc_source("Blender deletes a workspace from its tab's menu; Maya's factory workspaces come back with Reset.")), PATH + 'Disable Docking/Undocking': (_dcc_source('Area corners'), _dcc_source("Blender's areas are split and joined at their corners; there is no docking lock."))}
ACTIONS_GREYED = (_dcc_source('Save Current Workspace As...'), _dcc_source('Import Workspace Files...'), _dcc_source('Delete Current Workspace'), 'Disable Docking/Undocking')

def find(template_name):
    """The open file's workspace made from ``template_name`` (None: not in the file)."""
    for ws in bpy.data.workspaces:
        if switch.template_of(ws) == template_name:
            return ws
    return None

def apply_settings(context, ws):
    """Maya's linkedMenu and the tab-stack tab of workspace ``ws``."""
    menu_set = ws.get('allset_menu_set')
    if isinstance(menu_set, str) and menu_set:
        from .. import preferences
        try:
            preferences.get(context).menu_set = menu_set
        except (KeyError, TypeError):
            pass
    tab = ws.get('allset_dock_tab')
    if isinstance(tab, str) and tab:
        try:
            context.window_manager.allset_dock = tab
        except TypeError:
            pass

def activate(context, window, template_name):
    """Show Maya workspace ``template_name`` in ``window`` (appended from the template when the file lacks it)."""
    ws = find(template_name)
    if ws is None:
        prev = window.workspace.name if window.workspace is not None else ''
        ws = switch.append_workspace(window, template_name)
        if ws is None:
            return None
        if prev and switch.PREV_KEY not in ws:
            ws[switch.PREV_KEY] = prev
    window.workspace = ws
    apply_settings(context, ws)
    return ws

def label_of(ws):
    t = switch.template_of(ws)
    return LABELS.get(t, ws.name) if t else ws.name

def reset_label(ws):
    """Maya's item text for a factory workspace (Windows > Workspaces menu)."""
    return f'Reset "{label_of(ws)}" to Factory Default' if switch.template_of(ws) else _dcc_source('Reset Current Workspace')
_items = {}

def entries():
    """[(template name or None, workspace or None, label)] in dropdown order."""
    out = [(name, find(name), LABELS[name]) for name in IN_TEMPLATE]
    out += [(None, ws, ws.name) for ws in bpy.data.workspaces if switch.template_of(ws) is None]
    return out

def dropdown_items(_self, _context):
    labels = tuple((label for (_t, _w, label) in entries()))
    items = _items.get(labels)
    if items is None:
        items = [(str(i), label, _dcc_source('Switch to this Maya workspace') if i < len(IN_TEMPLATE) else _dcc_source('Switch to this workspace')) for (i, label) in enumerate(labels)] or [('0', '-', '')]
        _items[labels] = items
    return items

def dropdown_get(_self):
    window = bpy.context.window
    if window is None:
        return 0
    for (i, (_t, ws, _label)) in enumerate(entries()):
        if ws is not None and ws == window.workspace:
            return i
    return 0

def dropdown_set(_self, value):
    context = bpy.context
    window = context.window
    rows = entries()
    if window is None or not 0 <= value < len(rows):
        return
    (template, ws, _label) = rows[value]
    if template is not None:
        ptr = window.as_pointer()
        bpy.app.timers.register(lambda : _later(ptr, template), first_interval=0.0)
    elif ws is not None:
        window.workspace = ws

def _later(window_ptr, template):
    from .. import live_refs
    window = live_refs.window(window_ptr)
    if window is not None:
        with bpy.context.temp_override(window=window):
            activate(bpy.context, window, template)
    return None

class ALLSET_OT_maya_workspace(bpy.types.Operator):
    """Switch to this Maya workspace (Maya Windows > Workspaces); a file without it gets the kit's copy"""
    bl_translation_context = 'MWK:ui/workspaces.py:168'
    bl_idname = 'allset.maya_workspace'
    bl_label = _zh_native('Maya Workspace', 'MWK:ui/workspaces.py:168')
    bl_description = _zh_native("Switch to this Maya workspace (Maya Windows > Workspaces); a file without it gets the kit's copy", 'MWK:ui/workspaces.py:168')
    bl_options = {'REGISTER'}
    name: StringProperty(options={'SKIP_SAVE'}, translation_context='MWK:ui/workspaces.py:171')

    @classmethod
    def description(cls, context, props):
        return _zh(f'Switch to the Maya workspace {LABELS.get(props.name, props.name)}', 'MWK:ui/workspaces.py:175')

    def execute(self, context):
        if self.name not in IN_TEMPLATE or context.window is None:
            return {'CANCELLED'}
        if activate(context, context.window, self.name) is None:
            self.report({'WARNING'}, _zh(f'The workspace {LABELS[self.name]} could not be loaded', 'MWK:ui/workspaces.py:181'))
            return {'CANCELLED'}
        return {'FINISHED'}

class ALLSET_OT_reset_workspace(bpy.types.Operator):
    """Put the current Maya workspace back to its factory layout (Maya Windows > Workspaces > Reset Current
    Workspace): closed, moved or resized panels come back"""
    bl_translation_context = 'MWK:ui/workspaces.py:190'
    bl_idname = 'allset.reset_workspace'
    bl_label = _zh_native('Reset Current Workspace', 'MWK:ui/workspaces.py:190')
    bl_description = _zh_native('Put the current Maya workspace back to its factory layout (Maya Windows > Workspaces > Reset Current\nWorkspace): closed, moved or resized panels come back', 'MWK:ui/workspaces.py:190')
    bl_options = {'REGISTER'}

    def execute(self, context):
        window = context.window
        ws = switch.reset_workspace(window)
        if ws is None:
            self.report({'WARNING'}, _zh("This isn't one of Maya's workspaces: nothing to reset", 'MWK:ui/workspaces.py:197'))
            return {'CANCELLED'}
        apply_settings(context, ws)
        return {'FINISHED'}

class ALLSET_MT_maya_workspaces(bpy.types.Menu):
    """Maya Windows > Workspaces (Maya 2022 order)"""
    bl_translation_context = 'MWK:ui/workspaces.py:205'
    bl_label = _zh_native('Workspaces', 'MWK:ui/workspaces.py:205')

    def draw(self, context):
        from .menu_sets import ALLSET_OT_menu_unavailable
        lay = self.layout
        current = switch.template_of(context.window.workspace) if context.window else None
        for entry in FACTORY:
            if entry is None:
                lay.separator()
                continue
            (name, label) = entry
            if name in IN_TEMPLATE:
                op = lay.operator(ALLSET_OT_maya_workspace.bl_idname, text=_zh(label, 'MWK:ui/workspaces.py:217'), icon='RADIOBUT_ON' if name == current else 'RADIOBUT_OFF')
                op.name = name
            else:
                lay.operator(ALLSET_OT_menu_unavailable.bl_idname, text=_zh(label, 'MWK:ui/workspaces.py:221'), icon='RADIOBUT_OFF').item = PATH + name
        lay.separator()
        ws = context.window.workspace if context.window else None
        lay.operator(ALLSET_OT_reset_workspace.bl_idname, text=_zh(reset_label(ws) if ws else 'Reset Current Workspace', 'MWK:ui/workspaces.py:224'))
        for label in ACTIONS_GREYED:
            lay.operator(ALLSET_OT_menu_unavailable.bl_idname, text=_zh(label, 'MWK:ui/workspaces.py:226')).item = PATH + label
classes = (ALLSET_OT_maya_workspace, ALLSET_OT_reset_workspace, ALLSET_MT_maya_workspaces)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    from . import notices
    notices.PANEL_NOTICES.update(NOTICES)

def unregister():
    from . import notices
    for k in NOTICES:
        notices.PANEL_NOTICES.pop(k, None)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    _items.clear()
