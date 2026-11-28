# SPDX-License-Identifier: GPL-3.0-or-later
"""Attribute Editor operators: switching tabs and history nodes, Focus / Show / Hide / Load / Select, Delete
History, Add Limit, the Copy Tab and Blender Modifiers windows, and showing the dock's editors (Ctrl+A).
Main entry points: ``set_tab``, ``show_dock``, ``open_pinned_properties``, the ``ALLSET_OT_ae_*`` classes.
Related: ``attribute_editor`` (registers them), ``ae_nodes``."""

import bpy
from bpy.props import EnumProperty, StringProperty

from .. import results, live_refs
from . import channel_box
from .ae_nodes import _kind, ae_node, current_tab, hidden_types, tab_target, tabs
from .ae_rows import LIMIT_PROPS
from .ae_menus import _remember


DOCK_ITEMS = (('CHANNEL_BOX', "Channel Box / Layer Editor", "Maya Channel Box and Layer Editor"),
              ('ATTRIBUTE_EDITOR', "Attribute Editor", "Maya Attribute Editor"),
              ('MODELING_TOOLKIT', "Modeling Toolkit", "Maya Modeling Toolkit (ui/modeling_toolkit.py)"))
# the tab stack's panels: also Tool Settings (a tab only with the Tool Settings Tab preference, ui/maya_dock_roles)
DOCK_TABS = DOCK_ITEMS + (('TOOL_SETTINGS', "Tool Settings", "Maya Tool Settings (ui/tool_settings.py)"),)


def dock_mode(context):
    return getattr(context.window_manager, "allset_dock", 'CHANNEL_BOX')


# --- operators -----------------------------------------------------------------------------

def set_tab(context, key):
    wm = context.window_manager
    wm.allset_ae_tab = key
    wm.allset_ae_kind = _kind(key)
    if _kind(key) == 'H':
        from ..operators import model_history
        ob = ae_node(context)
        target = tab_target(ob, key) if ob is not None else None
        if target is not None:
            model_history.activate(ob, getattr(target, 'history_id', None) or target.name)


class ALLSET_OT_ae_tab(bpy.types.Operator):
    """Show this node in the Attribute Editor"""
    bl_idname = "allset.ae_tab"
    bl_label = "Attribute Editor Tab"
    bl_options = {'INTERNAL'}

    key: StringProperty()

    def execute(self, context):
        set_tab(context, self.key)
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_ae_step(bpy.types.Operator):
    """Go to the next input (left) or output (right) node in the history (Maya in/out arrows)"""
    bl_idname = "allset.ae_step"
    bl_label = "Input / Output Node"
    bl_options = {'INTERNAL'}

    forward: bpy.props.BoolProperty()

    def execute(self, context):
        ob = ae_node(context)
        if ob is None:
            return {'CANCELLED'}
        keys = [t[0] for t in tabs(ob) if _kind(t[0]) in ("H", "M", "CH")]
        cur = current_tab(context, ob)
        if cur not in keys:
            return {'CANCELLED'}
        i = keys.index(cur) + (1 if self.forward else -1)
        if 0 <= i < len(keys):
            set_tab(context, keys[i])
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_ae_modifier(bpy.types.Operator):
    """Delete History: apply this modifier (keep its effect, drop the node); Delete: remove it"""
    bl_idname = "allset.ae_modifier"
    bl_label = "History Node"
    bl_options = {'REGISTER', 'UNDO'}

    modifier: StringProperty()
    action: EnumProperty(items=(('APPLY', "Apply", ""), ('REMOVE', "Remove", "")))

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.active_object is not None

    def execute(self, context):
        ob = context.active_object
        md = ob.modifiers.get(self.modifier)
        if md is None:
            return {'CANCELLED'}
        from ..operators import mesh_maya
        inputs = mesh_maya.bool_inputs(ob) if md.type == 'BOOLEAN' else []
        inputs = [o for o in inputs if o is md.object]
        if self.action == 'REMOVE':
            ob.modifiers.remove(md)
            for o in inputs:              # a kit Boolean's hidden input comes back as an ordinary object
                mesh_maya.release_bool_input(o)
            return {'FINISHED'}
        with context.temp_override(object=ob, active_object=ob):
            done = bpy.ops.object.modifier_apply(modifier=self.modifier)
        for o in inputs:                  # Delete History: the input goes with the node, like Maya
            if 'FINISHED' in done and not mesh_maya.bool_users(o):
                mesh_maya.delete_bool_input(o)
        return done


class ALLSET_OT_ae_add_limit(bpy.types.Operator):
    """Add a limit constraint (Maya Limit Information)"""
    bl_idname = "allset.ae_add_limit"
    bl_label = "Add Limit"
    bl_options = {'REGISTER', 'UNDO'}

    type: EnumProperty(items=[(k, k.replace('_', ' ').title(), "") for k in LIMIT_PROPS])

    @classmethod
    def poll(cls, context):
        return channel_box.lead(context) is not None

    def execute(self, context):
        con = channel_box.lead(context).constraints.new(self.type)   # a joint: the pose bone
        con.owner_space = 'LOCAL'   # Maya limits act on the channel values
        return {'FINISHED'}


class ALLSET_OT_ae_select(bpy.types.Operator):
    """Select only the node shown in the Attribute Editor"""
    bl_idname = "allset.ae_select"
    bl_label = "Select"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and ae_node(context) is not None

    def execute(self, context):
        ob = ae_node(context)
        if channel_box.is_bone(ob):
            return {'CANCELLED'}
        for o in context.selected_objects:
            o.select_set(False)
        try:
            ob.select_set(True)
        except RuntimeError:     # not in the view layer
            return {'CANCELLED'}
        context.view_layer.objects.active = ob
        return {'FINISHED'}


def show_dock(context, dock):
    """Raise ``dock`` in the Maya tab stack, or open it as a floating window (ui/maya_dock_windows.py)."""
    from . import maya_dock
    return maya_dock.show(context, dock)


class ALLSET_OT_ae_toggle(bpy.types.Operator):
    """Switch the dock between Channel Box / Layer Editor and Attribute Editor
    (Maya Ctrl+A)"""
    bl_idname = "allset.ae_toggle"
    bl_label = "Attribute Editor / Channel Box"

    def execute(self, context):
        wm = context.window_manager
        show_dock(context, 'CHANNEL_BOX' if wm.allset_dock == 'ATTRIBUTE_EDITOR' else 'ATTRIBUTE_EDITOR')
        return {'FINISHED'}


class ALLSET_OT_dock_show(bpy.types.Operator):
    """Show the Attribute Editor, the Channel Box / Layer Editor or the Modeling Toolkit: the tab stack's tab, or a
    floating window when the layout has no tab stack (Maya Windows > General Editors)"""
    bl_idname = "allset.dock_show"
    bl_label = "Show Dock Editor"

    dock: EnumProperty(items=DOCK_ITEMS, name="Editor")
    le_tab: bpy.props.StringProperty(name="Layer Editor Tab", options={'SKIP_SAVE', 'HIDDEN'},
                                     description="DISPLAY / ANIM: the Layer Editor tab to raise")

    def execute(self, context):
        show_dock(context, self.dock)
        if self.le_tab in ('DISPLAY', 'ANIM'):
            context.window_manager.allset_le_tab = self.le_tab
        return {'FINISHED'}


class ALLSET_OT_object_attributes(bpy.types.Operator):
    """Show this object in the Attribute Editor (Maya RMB marking menu row
    "<object>...")"""
    bl_idname = "allset.object_attributes"
    bl_label = "Object Attributes"

    rmb: bpy.props.BoolProperty(options={'HIDDEN', 'SKIP_SAVE'},
                                description="The object the RMB menu was opened on")

    @staticmethod
    def _object(context, rmb):
        if rmb:
            ob = bpy.data.objects.get(getattr(context.window_manager, "allset_mm_target", ""))
            if ob is not None:
                return ob
        return context.active_object

    @classmethod
    def poll(cls, context):
        return cls._object(context, True) is not None

    def execute(self, context):
        ob = self._object(context, self.rmb)
        if ob is None:
            return {'CANCELLED'}
        if context.active_object is not ob:
            try:   # Maya shows the node without changing the selection; the AE here shows the active object
                ob.select_get(view_layer=context.view_layer)
                context.view_layer.objects.active = ob
            except RuntimeError:
                return {'CANCELLED'}
        return bpy.ops.allset.dock_show(dock='ATTRIBUTE_EDITOR')


def _redraw(context):
    """The dock areas (Properties editors, any window) and the 3D Views."""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'VIEW_3D', 'PROPERTIES'}:
                area.tag_redraw()


class ALLSET_OT_ae_focus(bpy.types.Operator):
    """Set Attribute Editor focus to this node (it stays on this node and tab; List > Auto Load Selected
    Attributes follows the selection again)"""
    bl_idname = "allset.ae_focus"
    bl_label = "Focus"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        ob = ae_node(context)
        if ob is None or channel_box.is_bone(ob):
            return {'CANCELLED'}
        wm = context.window_manager
        set_tab(context, current_tab(context, ob))
        wm.allset_ae_node = ob.name
        wm.allset_ae_auto_load = False
        _remember(ob)
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_ae_show_types(bpy.types.Operator):
    """Show all the related nodes in the attribute editor"""
    bl_idname = "allset.ae_show_types"
    bl_label = "Show"
    bl_options = {'INTERNAL'}

    node_type: StringProperty(options={'SKIP_SAVE'}, description="Only this node type (empty: all)")

    def execute(self, context):
        wm = context.window_manager
        wm.allset_ae_hidden = ",".join(sorted(hidden_types(context) - {self.node_type})) if self.node_type else ""
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_ae_hide_type(bpy.types.Operator):
    """Hide nodes of this type in the attribute editor"""
    bl_idname = "allset.ae_hide_type"
    bl_label = "Hide"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        ob = ae_node(context)
        if ob is None:
            return {'CANCELLED'}
        key = current_tab(context, ob)
        if _kind(key) in ("T", "S", "J"):      # the node itself always keeps its tab
            results.result(self, "The transform and shape tabs stay")
            return {'CANCELLED'}
        mtype = next((t[2] for t in tabs(ob) if t[0] == key), None)
        wm = context.window_manager
        wm.allset_ae_hidden = ",".join(sorted(hidden_types(context) | {mtype}))
        set_tab(context, "S" if ob.data is not None else "T")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_ae_load(bpy.types.Operator):
    """Load current selection into the Attribute Editor"""
    bl_idname = "allset.ae_load"
    bl_label = "Load Attributes"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        lead = channel_box.lead(context)
        wm = context.window_manager
        wm.allset_ae_node = getattr(lead, "name", "") if lead is not None and not channel_box.is_bone(lead) else ""
        if lead is not None:
            _remember(lead)
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_ae_show_node(bpy.types.Operator):
    """Show this node in the Attribute Editor"""
    bl_idname = "allset.ae_show_node"
    bl_label = "Show Node"
    bl_options = {'INTERNAL'}

    name: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        ob = bpy.data.objects.get(self.name)
        if ob is None:
            return {'CANCELLED'}
        wm = context.window_manager
        if wm.allset_ae_auto_load:
            try:   # the AE follows the active object: make this one active, the selection stays
                ob.select_get(view_layer=context.view_layer)
                context.view_layer.objects.active = ob
            except RuntimeError:
                return {'CANCELLED'}
        else:
            wm.allset_ae_node = ob.name
        _remember(ob)
        _redraw(context)
        return {'FINISHED'}


# AE tab kind -> Properties tab of the Copy Tab window and the ID it pins
COPY_TABS = {"T": 'OBJECT', "S": 'DATA', "M": 'MODIFIER', "H": 'DATA', "CH": 'DATA', "C": 'CONSTRAINT', "MAT": 'MATERIAL',
             "SG": 'MATERIAL', "J": 'BONE'}


def copy_tab_target(ob, key):
    """(Properties tab, ID to pin) for Copy Tab."""
    kind = _kind(key)
    tab = COPY_TABS.get(kind, 'OBJECT')
    if channel_box.is_bone(ob):
        return tab, ob.id_data
    if kind == "S" and ob.data is not None:
        return tab, ob.data
    if kind in ("MAT", "SG"):
        return tab, ob       # the material tab of a pinned object shows its slots
    return tab, ob


class ALLSET_OT_ae_copy_tab(bpy.types.Operator):
    """Copy the contents of the current tab into a new floating window (a Properties editor pinned to it)"""
    bl_idname = "allset.ae_copy_tab"
    bl_label = "Copy Tab"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return ae_node(context) is not None and context.window is not None

    def execute(self, context):
        ob = ae_node(context)
        tab, pin = copy_tab_target(ob, current_tab(context, ob))
        if open_pinned_properties(context, tab, pin, "attribute_editor_copy") is None:
            from . import window_places
            if not window_places.deferred():     # opens on a later tick (#203)
                self.report({'ERROR'}, "Could not open a new window")
            return {'CANCELLED'}
        return {'FINISHED'}


# object types with a modifier stack (Blender's Properties shows the Modifiers tab for them)
MODIFIER_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'LATTICE', 'GREASEPENCIL', 'CURVES', 'POINTCLOUD', 'VOLUME'}


def modifier_owner(ob):
    """The object whose modifier stack the button opens: the AE node's object (a joint's skeleton has none)."""
    if isinstance(ob, bpy.types.Object) and ob.type in MODIFIER_TYPES:
        return ob
    return None


class ALLSET_OT_ae_blender_modifiers(bpy.types.Operator):
    """Open Blender's modifier stack of this object in a floating window: every modifier with its settings, the
    order and Add Modifier. Each modifier is also a history node in Channel Box INPUTS and an Attribute Editor tab"""
    bl_idname = "allset.ae_blender_modifiers"
    bl_label = "Blender Modifiers"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.window is not None and modifier_owner(ae_node(context)) is not None

    def execute(self, context):
        ob = modifier_owner(ae_node(context))
        if open_pinned_properties(context, 'MODIFIER', ob, "attribute_editor_modifiers") is None:
            from . import window_places
            if not window_places.deferred():     # opens on a later tick (#203)
                self.report({'ERROR'}, "Could not open a new window")
            return {'CANCELLED'}
        return {'FINISHED'}


def open_pinned_properties(context, tab, pin, kind):
    """A new floating window with a Properties editor pinned to ``pin`` on ``tab`` (its place remembered under
    ``kind``, ui/window_places.py). None when no window could open now."""
    from ..operators.menu_extras import open_window
    area = max(context.window.screen.areas, key=lambda a: a.width * a.height, default=None)
    new = open_window(context, area, kind) if area is not None else None
    if new is None:
        return None
    target = new.screen.areas[0]
    target.ui_type = 'PROPERTIES'
    state = {"n": 40}
    win_ptr, area_ptr = new.as_pointer(), target.as_pointer()

    def tick():
        target = live_refs.area(area_ptr, win_ptr)   # pointers, looked up each tick (#36)
        if target is None:
            return None
        try:
            space = target.spaces.active
            space.pin_id = pin
            space.use_pin_id = True
            space.context = tab
        except (TypeError, ReferenceError, AttributeError):
            state["n"] -= 1
            return 0.05 if state["n"] > 0 else None
        target.tag_redraw()
        return None
    bpy.app.timers.register(tick, first_interval=0.0)
    return new
