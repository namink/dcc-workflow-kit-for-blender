# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl+middle-drag with the Rotate / Scale tool in mesh edit mode (Maya): each group of connected selected components
turns about its own normal (the component's local X axis), or grows / shrinks across its normal (the local YZ
plane), around the group's centre. A horizontal drag drives it; the vertical part of the drag does nothing. A Scale
drag past zero grows again (the factor never turns the components over). Outside mesh edit mode the drag is the
tool's plain middle drag, as if Ctrl were not held.

A group's normal is the sum of its faces' normals (face select mode), of its edges' normals (each edge: the mean of
its faces' normals) or of its vertices' normals; its centre is the mean of its vertices. Faces and edges group by
shared vertices, vertices by the selected edges between them.
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector


DEG_PER_PX = 0.36           # Rotate: degrees per pixel of horizontal drag (a drag to the right turns clockwise
                            # seen from the normal's tip)
PX_PER_SCALE = 79.2         # Scale: pixels of horizontal drag that add 1 to the factor (to the right = larger)
PLAIN_MODES = {'ROTATE': 'ROTATE', 'SCALE': 'RESIZE'}


def _groups(items, links):
    """Split ``items`` (hashable) into connected groups; ``links(item)`` gives its neighbours among ``items``."""
    todo, out = set(items), []
    for start in items:
        if start not in todo:
            continue
        todo.discard(start)
        group, stack = [start], [start]
        while stack:
            for nb in links(stack.pop()):
                if nb in todo:
                    todo.discard(nb)
                    group.append(nb)
                    stack.append(nb)
        out.append(group)
    return out


def _vertex_groups(bm, select_mode):
    """[(vertex indices, local normal sum)] of the selected component groups of ``bm``."""
    out = []
    if select_mode[2] and any(f.select for f in bm.faces):
        faces = [f for f in bm.faces if f.select]
        sel = set(faces)

        def links(f):
            return (g for v in f.verts for g in v.link_faces if g in sel and g is not f)
        for group in _groups(faces, links):
            verts = {v.index for f in group for v in f.verts}
            out.append((sorted(verts), sum((f.normal for f in group), Vector())))
        return out
    if select_mode[1] and any(e.select for e in bm.edges):
        edges = [e for e in bm.edges if e.select]
        sel = set(edges)

        def links(e):
            return (g for v in e.verts for g in v.link_edges if g in sel and g is not e)
        for group in _groups(edges, links):
            n = Vector()
            for e in group:
                d = Vector()
                for f in e.link_faces:
                    d += f.normal
                if d.length < 1e-9:
                    d = e.verts[0].normal + e.verts[1].normal
                if d.length > 1e-9:
                    n += d.normalized()
            out.append((sorted({v.index for e in group for v in e.verts}), n))
        return out
    verts = [v for v in bm.verts if v.select]
    sel = set(verts)

    def links(v):
        return (e.other_vert(v) for e in v.link_edges if e.select and e.other_vert(v) in sel)
    for group in _groups(verts, links):
        out.append((sorted(v.index for v in group), sum((v.normal for v in group), Vector())))
    return out


def collect(context):
    """[(object, [(world centre, world unit normal, [(vertex index, world co, local co)])])] of the edit-mode
    meshes."""
    data = []
    for ob in context.objects_in_mode_unique_data:
        if ob.type != 'MESH':
            continue
        bm = bmesh.from_edit_mesh(ob.data)
        bm.normal_update()
        bm.verts.ensure_lookup_table()
        mw = ob.matrix_world
        nmat = mw.to_3x3().inverted_safe().transposed()
        groups = []
        for idx, nsum in _vertex_groups(bm, tuple(context.tool_settings.mesh_select_mode)):
            n = nmat @ nsum
            if n.length < 1e-9:
                # the normals cancel out (a closed edge loop): the first component's own normal
                first = bm.verts[idx[0]].normal
                n = nmat @ first
            if n.length < 1e-9:
                continue
            pts = [(i, mw @ bm.verts[i].co, bm.verts[i].co.copy()) for i in idx]
            centre = sum((p[1] for p in pts), Vector()) / len(pts)
            groups.append((centre, n.normalized(), pts))
        if groups:
            data.append((ob, groups))
    return data


def transform(mode, amount, centre, normal, co):
    """``co`` turned by ``amount`` radians about ``normal`` (ROTATE) or scaled by ``amount`` across it (SCALE),
    around ``centre`` (world space)."""
    r = co - centre
    if mode == 'ROTATE':
        return centre + Matrix.Rotation(amount, 3, normal) @ r
    along = normal * r.dot(normal)
    return centre + along + (r - along) * amount


def amount_from_drag(mode, dx):
    """Rotate: radians; Scale: factor — from the horizontal drag ``dx`` in pixels."""
    if mode == 'ROTATE':
        return -math.radians(dx * DEG_PER_PX)
    return abs(1.0 + dx / PX_PER_SCALE)


class ALLSET_OT_component_local(bpy.types.Operator):
    """Rotate the selected component groups about their own normals, or scale them across their normals (Maya
    Ctrl+middle-drag with the Rotate / Scale tool)"""
    bl_idname = "allset.component_local"
    bl_label = "Rotate / Scale Components Locally"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    mode: bpy.props.EnumProperty(items=(('ROTATE', "Rotate", "Turn about the normal"),
                                        ('SCALE', "Scale", "Scale across the normal")),
                                 default='ROTATE', options={'HIDDEN', 'SKIP_SAVE'})
    # hidden: like Maya, the drag leaves no Adjust Last Operation panel behind
    amount: bpy.props.FloatProperty(name="Amount", default=0.0, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def _apply(self, amount, restore=False):
        for ob, groups in self._data:
            bm = bmesh.from_edit_mesh(ob.data)
            bm.verts.ensure_lookup_table()
            inv = ob.matrix_world.inverted_safe()
            for centre, normal, pts in groups:
                for i, co, local in pts:
                    bm.verts[i].co = local if restore else inv @ transform(self.mode, amount, centre, normal, co)
            bmesh.update_edit_mesh(ob.data, loop_triangles=True, destructive=False)

    def execute(self, context):
        if context.mode != 'EDIT_MESH':
            return {'CANCELLED'}
        self._data = collect(context)
        if not self._data:
            return {'CANCELLED'}
        self._apply(self.amount)
        return {'FINISHED'}

    def invoke(self, context, event):
        if context.mode != 'EDIT_MESH':
            return self._plain(context)
        self._data = collect(context)
        if not self._data:
            return {'PASS_THROUGH'}
        self.amount = amount_from_drag(self.mode, 0)
        self._x0 = event.mouse_region_x
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _plain(self, context):
        """The tool's plain middle drag (the Ctrl held at its start doesn't turn snapping on)."""
        from .manip import without_ctrl_snap
        try:
            res = without_ctrl_snap(context, lambda: bpy.ops.allset.manip_mmb('INVOKE_DEFAULT',
                                                                            mode=PLAIN_MODES[self.mode]))
        except RuntimeError:
            return {'PASS_THROUGH'}
        # the drag it started makes its own undo step: this call ends without one (and keeps the event)
        return {'CANCELLED'} if res & {'RUNNING_MODAL', 'FINISHED'} else {'PASS_THROUGH'}

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self.amount = amount_from_drag(self.mode, event.mouse_region_x - self._x0)
            self._apply(self.amount)
            return {'RUNNING_MODAL'}
        if event.type in {'MIDDLEMOUSE', 'LEFTMOUSE'} and event.value in {'RELEASE', 'PRESS'}:
            self.amount = amount_from_drag(self.mode, event.mouse_region_x - self._x0)
            self._apply(self.amount)
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._apply(0.0, restore=True)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


classes = (ALLSET_OT_component_local,)
