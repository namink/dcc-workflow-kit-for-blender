# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's HumanIK entries lead to Blender's Rigify (#319).

Skeleton > HumanIK and Windows > Animation Editors > HumanIK (and the Rigging shelf's Human IK button) open one
submenu with the Rigify steps in Maya's place: Add Meta-Rig (Rigify's own list), Generate Rig, the rig's settings
(Properties > Armature with Rigify's panels, pinned in a window), the active bone's rig type (Properties > Bone)
and the generated rig's controls (the 3D View sidebar's Item tab). With Rigify off the submenu offers to enable it:
Rigify is bundled with Blender, and enabling it changes the add-on list, so it asks first. The kit builds no rig of
its own; Quick Rig (operators/rig_tools.py) is the short way to a human meta-rig.
"""

import bpy
from bpy.props import EnumProperty

from .. import live_refs
from ..operators import rig_tools

METARIG_MENU = "ARMATURE_MT_rigify_metarigs"      # Rigify's Add > Armature list (Human, Basic, Animals ...)
CONTROLS_TAB = "Item"                             # where a generated rig draws Rig Main Properties / Rig Layers
TABS = (('DATA', "Rig Settings", "Rigify's panels of the armature: generate, bone collections, advanced options"),
        ('BONE', "Bone Rig Type", "The active bone's Rigify rig type and its options"))


def _armature(context):
    ob = context.active_object
    return ob if ob is not None and ob.type == 'ARMATURE' else None


class ALLSET_OT_rigify_enable(bpy.types.Operator):
    """Enable Rigify, the rigging add-on bundled with Blender (your add-on list changes)"""
    bl_idname = "allset.rigify_enable"
    bl_label = "Enable Rigify"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if rig_tools.rigify_enabled(context):
            return {'FINISHED'}
        return context.window_manager.invoke_confirm(
            self, event, title="Enable Rigify?", confirm_text="Enable Rigify",
            message="HumanIK leads to Rigify, an add-on bundled with Blender. Enable it (your add-on list changes)?")

    def execute(self, context):
        if not rig_tools.enable_rigify(context):
            self.report({'ERROR'}, "Rigify could not be enabled")
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_rigify_properties(bpy.types.Operator):
    """Open the rig's Rigify settings (Properties > Armature) or the active bone's rig type (Properties > Bone)
    in a window pinned to the armature"""
    bl_idname = "allset.rigify_properties"
    bl_label = "Rigify Properties"
    bl_options = {'INTERNAL'}

    tab: EnumProperty(name="Tab", items=TABS, default='DATA', options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None and context.window is not None

    def execute(self, context):
        from .attribute_editor import open_pinned_properties
        ob = _armature(context)
        if open_pinned_properties(context, self.tab, ob.data, "rigify_properties") is None:
            from . import window_places
            if not window_places.deferred():     # opens on a later tick
                self.report({'ERROR'}, "Could not open a new window")
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_rigify_controls(bpy.types.Operator):
    """Show the generated rig's controls: the 3D View sidebar's Item tab (Rig Main Properties, Rig Layers)"""
    bl_idname = "allset.rigify_controls"
    bl_label = "Rigify Rig Controls"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None and context.window is not None

    def execute(self, context):
        ob = _armature(context)
        if ob.data.get("rig_id") is None:
            self.report({'WARNING'}, "This armature is not a generated Rigify rig: Generate Rig first, then its "
                                  "controls appear in the sidebar's Item tab")
        area = context.area if context.area is not None and context.area.type == 'VIEW_3D' else None
        if area is None:
            views = [a for a in context.window.screen.areas if a.type == 'VIEW_3D']
            area = max(views, key=lambda a: a.width * a.height, default=None)
        if area is None:
            self.report({'WARNING'}, "No 3D View in this window")
            return {'CANCELLED'}
        area.spaces.active.show_region_ui = True
        sidebar_tab_later(context.window, area, CONTROLS_TAB)
        return {'FINISHED'}


def sidebar_tab_later(window, area, category, tries=40):
    """Make ``category`` the active tab of ``area``'s sidebar once it has drawn its tabs (the property is read-only
    before that); pointers looked up each tick."""
    state = {"n": tries}
    win_ptr, area_ptr = window.as_pointer(), area.as_pointer()

    def tick():
        area = live_refs.area(area_ptr, win_ptr)
        if area is None:
            return None
        region = next((r for r in area.regions if r.type == 'UI'), None)
        try:
            if region is not None:
                region.active_panel_category = category
        except (TypeError, ReferenceError, AttributeError):
            state["n"] -= 1
            return 0.05 if state["n"] > 0 else None
        area.tag_redraw()
        return None

    bpy.app.timers.register(tick, first_interval=0.0)


class ALLSET_MT_rigify(bpy.types.Menu):
    """Blender's Rigify in Maya's HumanIK place: meta-rig, Generate Rig, rig settings and controls"""
    bl_idname = "ALLSET_MT_rigify"
    bl_label = "Rigify"

    def draw(self, context):
        lay = self.layout
        if not rig_tools.rigify_enabled(context):
            lay.operator(ALLSET_OT_rigify_enable.bl_idname, text="Enable Rigify Add-on...", icon='PLUGIN')
            lay.label(text="Rigify is bundled with Blender: it builds a rig from a meta-rig")
            return
        lay.menu(METARIG_MENU, text="Add Meta-Rig", icon='OUTLINER_OB_ARMATURE')
        lay.operator("pose.rigify_generate", text="Generate Rig", icon='POSE_HLT')
        lay.separator()
        lay.operator(ALLSET_OT_rigify_properties.bl_idname, text="Rig Settings...").tab = 'DATA'
        lay.operator(ALLSET_OT_rigify_properties.bl_idname, text="Bone Rig Type...").tab = 'BONE'
        lay.operator(ALLSET_OT_rigify_controls.bl_idname, text="Rig Controls")


classes = (ALLSET_OT_rigify_enable, ALLSET_OT_rigify_properties, ALLSET_OT_rigify_controls, ALLSET_MT_rigify)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
