# SPDX-License-Identifier: GPL-3.0-or-later
"""Attribute Editor menu bar: List, Selected, Focus, Attributes, Display, Show, Help and the Presets button menu,
the nodes shown lately (Focus menu) and the notices for the items Blender has no counterpart for.
Main entry points: ``MENU_BAR``, ``MENUS``, ``AE_NOTICES``, ``_remember``.
Related: ``attribute_editor`` (registers the menus), ``ae_operators``."""

import bpy

from .ae_nodes import ae_node, hidden_types, tabs


# --- Maya AE chrome ---------------------------------------------------------------------------------
# Menus, buttons and tooltips like Maya's Attribute Editor (bars, widgets).

ATTRIBUTE_NAMES = (('NICE', "Nice", "Readable names (Translate X)"),
                   ('LONG', "Long", "Property names (location)"),
                   ('SHORT', "Short", "Abbreviated property names"))
AE = "Attribute Editor"
AE_NOTICES = {
    f"{AE}/Presets": ("Blender presets per tool", "Attribute presets of a node aren't kept by Blender"),
    f"{AE}/List/Selected Items": ("Selected menu", "The Selected menu lists the selection"),
    f"{AE}/List/Dynamics": ("Outliner", "Node lists by type: use the Outliner filter (Maya greys these too while "
                                         "Auto Load is on)"),
    f"{AE}/Show/Filters": ("Hide button", "Hide a node type with the Hide button, bring them back with Show"),
    f"{AE}/Show/Views": ("one view", "Blender has no alternative AE layouts (views / templates)"),
    f"{AE}/Help": ("Blender manual", "Help > Manual in Blender's menus; hover a field for its tooltip"),
}
_recent = []            # object names the AE showed, newest first (Focus menu)
RECENT = 8


def _remember(ob):
    name = getattr(ob, "name", None)
    if not name or (_recent and _recent[0] == name):
        return
    if name in _recent:
        _recent.remove(name)
    _recent.insert(0, name)
    del _recent[RECENT:]


def _greyed(layout, path, text):
    layout.operator("allset.menu_unavailable", text=text).item = f"{AE}/{path}"


class ALLSET_MT_ae_list(bpy.types.Menu):
    bl_label = "List"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        layout.prop(wm, "allset_ae_auto_load")
        row = layout.row()
        row.enabled = not wm.allset_ae_auto_load      # Maya greys it while Auto Load is on (ae bars)
        row.operator("allset.ae_load", text="Load Selected Attributes")
        _greyed(layout, "List/Selected Items", "Selected Items")
        layout.separator()
        for name in ("Dynamics", "Kinematics", "Deformers", "Lights", "Shading"):
            _greyed(layout, "List/Dynamics", name)


class ALLSET_MT_ae_selected(bpy.types.Menu):
    bl_label = "Selected"

    def draw(self, context):
        obs = list(getattr(context, "selected_objects", ()) or ())
        if not obs:
            self.layout.label(text="Nothing selected")
        for ob in obs:
            self.layout.operator("allset.ae_show_node", text=ob.name).name = ob.name


class ALLSET_MT_ae_focus(bpy.types.Menu):
    bl_label = "Focus"

    def draw(self, context):
        names = [n for n in _recent if n in bpy.data.objects]
        if not names:
            self.layout.label(text="No nodes yet")
        for name in names:
            self.layout.operator("allset.ae_show_node", text="|" + name).name = name


class ALLSET_MT_ae_attributes(bpy.types.Menu):
    bl_label = "Attributes"

    def draw(self, context):
        layout = self.layout
        layout.operator("allset.add_attribute", text="Add Attributes...")
        layout.operator("allset.delete_attribute", text="Delete Attributes...")
        layout.operator("allset.edit_attribute", text="Edit Attributes...")


class ALLSET_MT_ae_attribute_names(bpy.types.Menu):
    bl_label = "Attribute Names"

    def draw(self, context):
        self.layout.props_enum(context.window_manager, "allset_ae_names")


class ALLSET_MT_ae_display(bpy.types.Menu):
    bl_label = "Display"

    def draw(self, context):
        self.layout.menu(ALLSET_MT_ae_attribute_names.__name__)


class ALLSET_MT_ae_node_types(bpy.types.Menu):
    bl_label = "By Node Type"

    def draw(self, context):
        layout = self.layout
        layout.operator("allset.ae_show_types", text="Enable All")
        hidden = sorted(hidden_types(context))
        if hidden:
            layout.separator()
        for t in hidden:
            op = layout.operator("allset.ae_show_types", text=t, icon='CHECKBOX_DEHLT')
            op.node_type = t


class ALLSET_MT_ae_show(bpy.types.Menu):
    bl_label = "Show"

    def draw(self, context):
        layout = self.layout
        layout.menu(ALLSET_MT_ae_node_types.__name__)
        layout.separator()
        for text in ("Add New Filter Type...", "Add Filter Types for Selected", "Save Show Preset"):
            _greyed(layout, "Show/Filters", text)
        layout.separator()
        for text in ("Set Current View", "Set Global View"):
            _greyed(layout, "Show/Views", text)
        layout.prop(context.window_manager, "allset_ae_show_notes")


class ALLSET_MT_ae_help(bpy.types.Menu):
    bl_label = "Help"

    def draw(self, context):
        layout = self.layout
        _greyed(layout, "Help", "Help on Attribute Editor")
        ob = ae_node(context)
        if ob is not None:
            layout.separator()
            for t in sorted({t[2] for t in tabs(ob)}):
                _greyed(layout, "Help", f'Help on "{t}"')
        layout.separator()
        _greyed(layout, "Help", "Node and Attribute Reference")


class ALLSET_MT_ae_presets(bpy.types.Menu):
    bl_label = "Presets"

    def draw(self, context):
        for text in ("Save attribute preset...", "Edit Presets..."):
            _greyed(self.layout, "Presets", text)


MENU_BAR = (("List", "ALLSET_MT_ae_list"), ("Selected", "ALLSET_MT_ae_selected"), ("Focus", "ALLSET_MT_ae_focus"),
            ("Attributes", "ALLSET_MT_ae_attributes"), ("Display", "ALLSET_MT_ae_display"),
            ("Show", "ALLSET_MT_ae_show"), ("Help", "ALLSET_MT_ae_help"))
MENUS = (ALLSET_MT_ae_list, ALLSET_MT_ae_selected, ALLSET_MT_ae_focus, ALLSET_MT_ae_attributes,
         ALLSET_MT_ae_attribute_names, ALLSET_MT_ae_display, ALLSET_MT_ae_node_types, ALLSET_MT_ae_show,
         ALLSET_MT_ae_help, ALLSET_MT_ae_presets)
