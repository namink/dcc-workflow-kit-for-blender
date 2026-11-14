# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya file dialog's left column in every Blender file browser: Current Project + the project's folders + Set
Project (Maya's file dialog: under Folder Bookmarks, "Current Project:"
drop-down, the project folder list, "Set Project..." button). Blender's own bookmarks stay above it.

Texture dialogs start in the project's sourceimages folder, like Maya's: Blender's Image Open (node Open buttons,
the Attribute Editor File row, the Image Editor) takes no start folder, so the file browser's path bar notices a
browser that Image Open started at the Textures path for an empty slot and moves it there on the next tick."""

import os

import bpy

from .. import live_refs
from ..operators import project

IMAGE_OPEN = "IMAGE_OT_open"
_pending = []       # (space pointer, operator pointer, folder) to move on the next tick


class ALLSET_PT_file_project(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOLS'
    bl_category = "Bookmarks"
    bl_label = "Current Project"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and space.type == 'FILE_BROWSER' and space.browse_mode == 'FILES'

    def draw(self, context):
        layout = self.layout
        root = project.current_root(context)
        layout.menu("ALLSET_MT_recent_projects", text=os.path.basename(root) or root, icon='DOWNARROW_HLT')
        col = layout.column(align=True)
        rows = [("Workspace Root", root)] + [(name, os.path.join(root, name)) for name in project.FOLDERS
                                              if os.path.isdir(os.path.join(root, name))]
        for text, path in rows:
            row = col.row(align=True)
            row.alignment = 'LEFT'
            row.operator("allset.file_goto", text=text, icon='FILE_FOLDER', emboss=False).path = path
        layout.operator("allset.file_set_project", text="Set Project...")


def _texture_browser(_self, context):
    """Drawn after the path bar of every file browser: an Image Open browser for an empty slot is queued to start
    in sourceimages (draw code only queues; the folder changes in a one-shot timer)."""
    space = context.space_data
    op = getattr(space, "active_operator", None)
    if op is None or op.bl_idname != IMAGE_OPEN:
        return
    folder = project.texture_folder(context, op.filepath)
    if not folder:
        return
    entry = (space.as_pointer(), op.as_pointer(), folder)
    if entry not in _pending:
        _pending.append(entry)
    if not bpy.app.timers.is_registered(_move_browsers):
        bpy.app.timers.register(_move_browsers, first_interval=0.0)


def _move_browsers():
    while _pending:
        space_ptr, op_ptr, folder = _pending.pop(0)
        _w, _a, space = live_refs.find_space(space_ptr)
        op = getattr(space, "active_operator", None) if space is not None else None
        if op is None or op.as_pointer() != op_ptr or op.bl_idname != IMAGE_OPEN or not os.path.isdir(folder):
            continue
        space.params.directory = folder.encode()
        # the browser's own start path now names the folder: its later draws leave it where the user goes
        op.filepath = os.path.join(folder, "")
    return None


classes = (ALLSET_PT_file_project,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.FILEBROWSER_PT_directory_path.append(_texture_browser)


def unregister():
    bpy.types.FILEBROWSER_PT_directory_path.remove(_texture_browser)
    if bpy.app.timers.is_registered(_move_browsers):
        bpy.app.timers.unregister(_move_browsers)
    _pending.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
