# SPDX-License-Identifier: GPL-3.0-or-later
"""Skin lookups shared by the Skin menu tools: a mesh's skeleton (``_skin_armature``), the selected skinned meshes
(``skinned_meshes``), a skin's influence (joint) names in vertex group order (``influence_names``) and ``_Weights``,
which reads / writes vertex group weights through a BMesh deform layer in object, paint or edit mode.
skin_tools_199 re-exports them (ui/component_editor.py reads ``_Weights`` / ``influence_names`` there).
"""

import bmesh

from . import skin

# --- shared helpers -----------------------------------------------------------------------------------------------

NO_SKIN = "Select a skinned mesh"


def _skin_armature(mesh):
    md = skin.armature_modifier(mesh)
    return md.object if md is not None else None


def skinned_meshes(context):
    """Selected skinned meshes, the active one first (edit / paint modes: the active object)."""
    out = []
    ob = context.active_object
    if ob is not None and ob.type == 'MESH' and _skin_armature(ob) is not None:
        out.append(ob)
    for o in context.selected_objects:
        if o.type == 'MESH' and o not in out and _skin_armature(o) is not None:
            out.append(o)
    return out


def influence_names(mesh):
    """Maya skinCluster influences = the mesh's vertex groups that are bones of its skeleton, in group order."""
    arm = _skin_armature(mesh)
    if arm is None:
        return []
    bones = set(arm.data.bones.keys())
    return [vg.name for vg in mesh.vertex_groups if vg.name in bones]


class _Weights:
    """Read / write vertex group weights through a BMesh deform layer: works in object, paint and edit mode."""

    def __init__(self, mesh):
        self.mesh = mesh
        self.edit = mesh.mode == 'EDIT'
        if self.edit:
            self.bm = bmesh.from_edit_mesh(mesh.data)
        else:
            self.bm = bmesh.new()
            self.bm.from_mesh(mesh.data)
        self.bm.verts.ensure_lookup_table()
        self.layer = self.bm.verts.layers.deform.verify()

    def selected(self):
        return [v.index for v in self.bm.verts if v.select]

    def get(self, vi, gi):
        return self.bm.verts[vi][self.layer].get(gi, 0.0)

    def set(self, vi, gi, w):
        dv = self.bm.verts[vi][self.layer]
        if w > 0.0 or gi in dv:
            dv[gi] = w

    def flush(self):
        if self.edit:
            bmesh.update_edit_mesh(self.mesh.data, loop_triangles=False, destructive=False)
        else:
            self.bm.to_mesh(self.mesh.data)
            self.bm.free()
        self.mesh.data.update()
