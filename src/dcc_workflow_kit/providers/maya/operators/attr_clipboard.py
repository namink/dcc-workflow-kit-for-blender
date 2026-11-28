# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Mesh > Clipboard Actions and Edit > Transfer Attribute Values, like Maya 2026:

- Copy Attributes takes the first selected face only: its shader and UVs (the menu item's options: UV on, Shader on,
  Color off). An object selection is refused.
- Paste Attributes gives every target face (the selected faces; an object = all its faces) that shader and those
  UVs. Nothing selected or an empty clipboard is refused.
- Clear Clipboard empties it.
- Transfer Attribute Values copies, from the first selected object to the second, translate / rotate / scale /
  visibility / rotate order and the custom attributes both have (values only, no animation). Exactly two objects.
"""

import bmesh
import bpy
from bpy.props import EnumProperty

from .. import results
from .mesh_maya import _first_selected

# Session clipboard like Maya's: {"material": name or None, "uvs": [(u, v), ...] or None}
CLIPBOARD = {}
NO_FACES = "Select a face to copy its attributes."
NO_PASTE = "Nothing to paste: copy a face first, then select faces or objects."


def copy(context):
    """Clipboard = the first selected face of the edit mesh; False when there is no face selection."""
    ob = context.edit_object
    if ob is None or ob.type != 'MESH':
        return False
    bm = bmesh.from_edit_mesh(ob.data)
    faces = [f for f in bm.faces if f.select]
    if not faces:
        return False
    act = bm.faces.active
    face = act if act is not None and act.select else min(faces, key=lambda f: f.index)
    uv = bm.loops.layers.uv.active
    mat = ob.material_slots[face.material_index].material if face.material_index < len(ob.material_slots) else None
    CLIPBOARD.clear()
    CLIPBOARD.update(material=mat.name if mat else None,
                     uvs=[tuple(loop[uv].uv) for loop in face.loops] if uv is not None else None)
    return True


def _slot(ob, mat):
    for i, s in enumerate(ob.material_slots):
        if s.material == mat:
            return i
    ob.data.materials.append(mat)
    return len(ob.material_slots) - 1


def paste_faces(ob, bm, faces):
    mat = bpy.data.materials.get(CLIPBOARD["material"]) if CLIPBOARD.get("material") else None
    index = _slot(ob, mat) if mat is not None else None
    src = CLIPBOARD.get("uvs")
    uv = (bm.loops.layers.uv.active or bm.loops.layers.uv.new("map1")) if src else None
    for f in faces:
        if index is not None:
            f.material_index = index
        if src:
            n, m = len(f.loops), len(src)
            for i, loop in enumerate(f.loops):
                # a face with another corner count samples the copied corners evenly (Maya places them along the
                # copied face's border instead)
                loop[uv].uv = src[i * m // n]
    return len(faces)


def paste(context):
    """Paste onto the selected faces (edit mode) or every face of the selected meshes; faces changed."""
    if not CLIPBOARD:
        return 0
    n = 0
    if context.mode == 'EDIT_MESH':
        for ob in context.objects_in_mode_unique_data:
            bm = bmesh.from_edit_mesh(ob.data)
            n += paste_faces(ob, bm, [f for f in bm.faces if f.select])
            bmesh.update_edit_mesh(ob.data)
        return n
    for ob in {o.data: o for o in context.selected_objects if o.type == 'MESH'}.values():
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        n += paste_faces(ob, bm, list(bm.faces))
        bm.to_mesh(ob.data)
        bm.free()
        ob.data.update()
    return n


class ALLSET_OT_mesh_clipboard(bpy.types.Operator):
    """Copy the first selected face's material and UVs, paste them on the selected faces or meshes, or clear the
    clipboard (Maya Mesh > Clipboard Actions)"""
    bl_idname = "allset.mesh_clipboard"
    bl_label = "Clipboard Actions"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(('COPY', "Copy Attributes", ""), ('PASTE', "Paste Attributes", ""),
                                ('CLEAR', "Clear Clipboard", "")), options={'SKIP_SAVE'})

    def execute(self, context):
        if self.action == 'CLEAR':
            CLIPBOARD.clear()
            return {'FINISHED'}
        if self.action == 'COPY':
            if not copy(context):
                self.report({'WARNING'}, NO_FACES)
                return {'CANCELLED'}
            return {'FINISHED'}
        n = paste(context)
        if not n:
            self.report({'WARNING'}, NO_PASTE)
            return {'CANCELLED'}
        results.result(self, f"Pasted on {n} face(s)")
        return {'FINISHED'}


CHANNELS = ("location", "scale", "rotation_mode", "rotation_euler", "rotation_quaternion", "rotation_axis_angle",
            "hide_viewport")


def transfer_values(src, dst):
    """Maya Transfer Attribute Values: transform channels, visibility, rotate order and the custom attributes ``dst``
    has."""
    for attr in CHANNELS:
        setattr(dst, attr, getattr(src, attr))
    for key in src.keys():
        if key in dst.keys() and not key.startswith(("_", "allset")):
            dst[key] = src[key]


class ALLSET_OT_transfer_values(bpy.types.Operator):
    """Copy the first selected object's transform, visibility and shared custom attribute values to the second
    (Maya Edit > Transfer Attribute Values)"""
    bl_idname = "allset.transfer_values"
    bl_label = "Transfer Attribute Values"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sel = list(context.selected_objects)
        if len(sel) != 2:
            self.report({'ERROR'}, "Select only two objects: the source, then the target." if len(sel) > 2
                        else "Select two objects: the source, then the target.")
            return {'CANCELLED'}
        src = _first_selected(sel, context.view_layer.objects.active)
        dst = sel[1] if sel[0] is src else sel[0]
        transfer_values(src, dst)
        results.result(self, f"{src.name} -> {dst.name}")
        return {'FINISHED'}


classes = (ALLSET_OT_mesh_clipboard, ALLSET_OT_transfer_values)
