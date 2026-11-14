# SPDX-License-Identifier: GPL-3.0-or-later
"""The menu of a set row in the Maya Outliner (right-click a set or a set member; ``ui/outliner_tree_edit.py``).

Maya lists object sets after the DAG nodes; expanding one shows its members. The kit's Outliner tree
(``ui/outliner_tree.py``) draws the set rows, the startup camera rows and defaultLightSet / defaultObjectSet itself;
a right-click on a set row opens this menu.
"""

import bpy

from ..operators import sets


class ALLSET_MT_outliner_set(bpy.types.Menu):
    """Maya Outliner set / set member RMB menu"""
    bl_label = "Set"
    bl_idname = "ALLSET_MT_outliner_set"

    def draw(self, context):
        wm = context.window_manager
        name, member = wm.allset_set_target, wm.allset_set_member
        coll = sets.get(name)
        layout = self.layout
        if coll is None:
            return
        layout.operator("allset.select_set_members", text="Select Set Members").name = name
        if member:
            op = layout.operator("allset.set_edit", text="Remove From Current Set")
            op.name, op.member, op.action = name, member, 'REMOVE_MEMBER'
            return
        op = layout.operator("allset.set_edit", text="Show Set Members", icon='CHECKBOX_HLT' if coll.allset_expanded
                             else 'CHECKBOX_DEHLT')
        op.name, op.action = name, 'EXPAND'
        layout.separator()
        for action, label in (('ADD', "Add Selected Objects"), ('REMOVE', "Remove Selected Objects"),
                              ('RENAME', "Rename..."), ('DELETE', "Delete Set")):
            op = layout.operator("allset.set_edit", text=label)
            op.name, op.action = name, action


classes = (ALLSET_MT_outliner_set,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
