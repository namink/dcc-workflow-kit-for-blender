# SPDX-License-Identifier: GPL-3.0-or-later
"""The shelf drawn as header buttons (the strip's tool header in older files): ``draw_shelf`` (Shelf menu,
< tab menu >, the buttons) and ``draw_shelf_tabs`` (one flat tab per shelf), plus the Shelf menu
(``ALLSET_MT_shelf_settings``) and the tab menu (``ALLSET_MT_shelf_tabs``). Related: shelf.py (header swap)."""

import bpy

from . import shelf_icons

from .shelf_store import (USER_PREFIX, user_data, user_shelf, factory_extras, editable_buttons, shelves, all_buttons,
                          factory_buttons, current)
from .shelf_run import ALLSET_OT_shelf_button
from .shelf_edit_ops import (ALLSET_OT_shelf_select, ALLSET_OT_shelf_step, ALLSET_OT_shelf_new, ALLSET_OT_shelf_delete,
                             ALLSET_OT_shelf_add_button, ALLSET_OT_shelf_edit_button, ALLSET_OT_shelf_remove_button,
                             ALLSET_MT_shelf_add_action, ALLSET_OT_shelf_add_last_command)


# --- drawing --------------------------------------------------------------------------------------------

class ALLSET_MT_shelf_tabs(bpy.types.Menu):
    """Choose the shelf (Maya shelf tabs)"""
    bl_idname = "ALLSET_MT_shelf_tabs"
    bl_label = "Shelves"

    def draw(self, context):
        cur = current(context)
        for shelf_id, label in shelves():
            if shelf_id.startswith(USER_PREFIX) and shelf_id == USER_PREFIX + user_data()["shelves"][0]["name"]:
                self.layout.separator()
            op = self.layout.operator(ALLSET_OT_shelf_select.bl_idname, text=label,
                                      icon='RADIOBUT_ON' if shelf_id == cur else 'RADIOBUT_OFF')
            op.shelf = shelf_id


class ALLSET_MT_shelf_settings(bpy.types.Menu):
    """Maya shelf menu: editor, shelf navigation and shelf management"""
    bl_idname = "ALLSET_MT_shelf_settings"
    bl_label = "Shelf"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.emboss = 'PULLDOWN_MENU'
        layout.operator("allset.shelf_editor_open", icon='WINDOW', text="Shelf Editor...")
        layout.separator()
        layout.menu(ALLSET_MT_shelf_tabs.bl_idname, text="Navigate Shelves")
        layout.separator()
        layout.operator(ALLSET_OT_shelf_new.bl_idname, icon='ADD')
        layout.operator(ALLSET_OT_shelf_delete.bl_idname, icon='TRASH')
        layout.separator()
        layout.menu(ALLSET_MT_shelf_add_action.bl_idname, icon='ADD', text="Add Shelf Button...")
        layout.operator(ALLSET_OT_shelf_add_last_command.bl_idname, icon='CONSOLE')


def draw_shelf(layout, context):
    """Shelf row: settings menu, tab dropdown with < >, then the current shelf's buttons."""
    cur = current(context)
    label = dict(shelves()).get(cur, cur)
    row = layout.row(align=True)
    row.menu(ALLSET_MT_shelf_settings.bl_idname, text="", icon='PREFERENCES')
    row = layout.row(align=True)
    row.operator(ALLSET_OT_shelf_step.bl_idname, text="", icon='TRIA_LEFT').forward = False
    row.menu(ALLSET_MT_shelf_tabs.bl_idname, text=label)
    row.operator(ALLSET_OT_shelf_step.bl_idname, text="", icon='TRIA_RIGHT').forward = True
    layout.separator(type='LINE')
    row = layout.row(align=True)
    if cur.startswith(USER_PREFIX):
        s = user_shelf(cur[len(USER_PREFIX):]) or {"buttons": []}
        if not s["buttons"]:
            row.operator(ALLSET_OT_shelf_add_button.bl_idname, text="Add Button", icon='ADD')
        for i, b in enumerate(s["buttons"]):
            if b.get("type") == "separator" or (b.get("action") or {}).get("type") == "separator":
                row.separator(factor=0.45)
                continue
            icon_kwargs = shelf_icons.icon_ui_kwargs(b.get("icon", "SCRIPT"))
            op = row.operator(
                ALLSET_OT_shelf_button.bl_idname,
                text=b.get("label", "Button") if b.get("icon", "SCRIPT") == 'SCRIPT' else "",
                **icon_kwargs,
            )
            op.shelf, op.index = cur, i
        return
    # Factory shelves have immutable Maya slots plus user-added records stored
    # in shelves.json under ``extra``. Draw both groups in slot order so buttons
    # added by Shelf Editor are visible in the real Image Editor tool header.
    for i, _label, _action, icon in factory_buttons(cur):
        op = row.operator(ALLSET_OT_shelf_button.bl_idname, text="", icon=icon)
        op.shelf, op.index = cur, i

    factory_slot_count = len(all_buttons(cur))
    for offset, button in enumerate(factory_extras(cur) or ()):
        if button.get("type") == "separator" or (button.get("action") or {}).get("type") == "separator":
            row.separator(factor=0.45)
            continue
        icon_kwargs = shelf_icons.icon_ui_kwargs(button.get("icon", "SCRIPT"))
        op = row.operator(
            ALLSET_OT_shelf_button.bl_idname,
            text=button.get("label", "Button") if button.get("icon", "SCRIPT") == 'SCRIPT' else "",
            **icon_kwargs,
        )
        op.shelf, op.index = cur, factory_slot_count + offset


def draw_shelf_tabs(layout, context):
    """Maya shelf tab row: settings, then one flat tab per shelf,
    the current one raised."""
    cur = current(context)
    layout.menu(ALLSET_MT_shelf_settings.bl_idname, text="", icon='PREFERENCES')
    row = layout.row(align=True)
    for shelf_id, label in shelves():
        row.operator(ALLSET_OT_shelf_select.bl_idname, text=label, emboss=shelf_id == cur).shelf = shelf_id
