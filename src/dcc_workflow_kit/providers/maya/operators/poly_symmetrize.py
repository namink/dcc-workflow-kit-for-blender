# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Edit Mesh > Symmetrize (``allset.symmetrize``, a modal edge pick): the clicked edge is the symmetry seam; each
selected vertex's topological counterpart (both sides walked face by face: ``topo_mirror``) takes its mirrored position
about the plane through the seam (``mirror_plane``, ``symmetrize``). Screen edge picking: ``pick_edge`` (on
preselect.py). Imported through poly_maya.py.
"""

import bmesh
import bpy


# --- Symmetrize --------------------------------------------------------------------------------
# Maya: with symmetry off (as in a new scene) Edit Mesh > Symmetrize enters "Select Symmetry
# Edge" ("Select a mesh edge for symmetry"), the mesh unchanged; the clicked edge = a topological symmetry seam, then
# each selected component's counterpart takes the mirrored position (the selected side drives; with both sides
# selected the side of the lowest-index selected vertex drives, Maya's -X side on a cube).
# Object mode / nothing selected: "No components selected for Symmetrize."

SYMMETRIZE_NO_COMPONENTS = "No components selected for Symmetrize."
SYMMETRIZE_PROMPT = "Select a mesh edge for symmetry"


def topo_mirror(bm, seam, face_map=None):
    """(vertex -> mirror vertex, vertex -> side 0 / 1) by walking both sides of ``seam`` face by face; None if the
    mesh isn't topologically symmetric about it. ``face_map`` (a dict), when given, gets face -> mirror face."""
    if len(seam.link_faces) != 2:
        return None
    fa, fb = seam.link_faces
    m = {seam.verts[0]: seam.verts[0], seam.verts[1]: seam.verts[1]}
    side_f = {fa: 0, fb: 1}
    queue = [(fa, fb, seam, seam)]
    while queue:
        f, g, ea, eb = queue.pop()
        if len(f.loops) != len(g.loops):
            return None
        if face_map is not None:
            face_map[f], face_map[g] = g, f
        la = next(lp for lp in f.loops if lp.edge is ea)
        lb = next(lp for lp in g.loops if lp.edge is eb)
        if m.get(la.vert) is lb.link_loop_next.vert:
            a, b, back = la, lb.link_loop_next, True
        elif m.get(la.vert) is lb.vert:
            a, b, back = la, lb, False
        else:
            return None
        for _ in range(len(f.loops)):
            va, vb = a.vert, b.vert
            if m.get(va, vb) is not vb or m.get(vb, va) is not va:
                return None
            m[va], m[vb] = vb, va
            na = a.link_loop_next
            nb = b.link_loop_prev if back else b.link_loop_next
            e1 = a.edge
            e2 = nb.edge if back else b.edge
            if e1 is not e2:
                o1 = [x for x in e1.link_faces if x is not f]
                o2 = [x for x in e2.link_faces if x is not g]
                if len(o1) != len(o2):
                    return None
                if o1 and o1[0] not in side_f:
                    if o2[0] in side_f or o1[0] is o2[0]:
                        return None
                    side_f[o1[0]], side_f[o2[0]] = side_f[f], side_f[g]
                    queue.append((o1[0], o2[0], e1, e2))
            a, b = na, nb
    side = {}
    for f, s in side_f.items():
        for v in f.verts:
            if m.get(v) is not v:
                side[v] = s
    return m, side


def mirror_plane(bm, m, seam):
    """(point, unit normal) of the symmetry plane: fitted through the seam vertices (they map to themselves), else
    through the seam edge across its two faces."""
    import numpy as np
    from mathutils import Vector
    pts = [v.co for v, w in m.items() if v is w]
    c = sum(pts, Vector()) / len(pts)
    if len(pts) >= 3:
        a = np.array([p - c for p in pts], dtype=np.float64)
        w, vecs = np.linalg.eigh(a.T @ a)
        if w[1] > 1e-12:
            return c, Vector(vecs[:, 0]).normalized()
    d = (seam.verts[1].co - seam.verts[0].co).normalized()
    nrm = (seam.link_faces[0].normal + seam.link_faces[1].normal)
    return c, d.cross(nrm).normalized()


def symmetrize(bm, seam, selected):
    """Move the counterparts of ``selected`` vertices to their mirror positions about ``seam``. Returns the number
    of moved vertices, or None when the mesh isn't symmetric about that edge."""
    res = topo_mirror(bm, seam)
    if res is None:
        return None
    m, side = res
    src = [v for v in selected if v in side]
    if not src:
        return 0
    sides = {side[v] for v in src}
    drive = side[min(src, key=lambda v: v.index)] if len(sides) > 1 else sides.pop()
    c, n = mirror_plane(bm, m, seam)
    moved = 0
    for v in src:
        if side[v] != drive:
            continue
        w = m[v]
        w.co = v.co - 2.0 * (v.co - c).dot(n) * n
        moved += 1
    return moved


def _selected_verts(bm):
    return [v for v in bm.verts if v.select]


def _region_under(context, x, y):
    for area in context.window.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type == 'WINDOW' and region.x <= x < region.x + region.width \
                    and region.y <= y < region.y + region.height:
                from ..ui import toolbox
                if toolbox.is_toolbox(area.spaces.active):
                    return None
                return area, region
    return None


def pick_edge(context, region, rv3d, mouse):
    """(object, edge index) of the edit-mesh edge nearest ``mouse`` (region pixels) on screen, or None."""
    import numpy as np
    from . import preselect
    best = None
    scale = context.preferences.system.ui_scale or 1.0
    for ob in context.objects_in_mode_unique_data or ():
        if ob.type != 'MESH':
            continue
        bm = bmesh.from_edit_mesh(ob.data)
        bm.edges.ensure_lookup_table()
        mw = np.array(ob.matrix_world, dtype=np.float64)
        co = np.array([v.co[:] for v in bm.verts], dtype=np.float64).reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
        xy, front = preselect.project(co, rv3d.perspective_matrix, region.width, region.height)
        edges = np.array([(e.verts[0].index, e.verts[1].index) for e in bm.edges], dtype=np.int64).reshape(-1, 2)
        ok = np.array([not e.hide for e in bm.edges], dtype=bool)
        if len(edges):
            ok &= front[edges[:, 0]] & front[edges[:, 1]]
        i = preselect.pick_edge(xy, edges, ok, mouse, preselect.RADIUS_PX * scale, lambda i, t: True)
        if i is None:
            continue
        d, _t = preselect.segment_distance(mouse, xy[edges[[i], 0]], xy[edges[[i], 1]])
        if best is None or float(d[0]) < best[0]:
            best = (float(d[0]), ob, i)
    return None if best is None else (best[1], best[2])


class ALLSET_OT_symmetrize(bpy.types.Operator):
    """Click a mesh edge on the symmetry seam: the selected components' counterparts on the other side take their
    mirrored positions (Maya Edit Mesh > Symmetrize). Esc / right click cancels"""
    bl_idname = "allset.symmetrize"
    bl_label = "Symmetrize"
    bl_options = {'REGISTER', 'UNDO'}

    object_name: bpy.props.StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    edge: bpy.props.IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.mode in ('EDIT_MESH', 'OBJECT')

    def _has_components(self, context):
        if context.mode != 'EDIT_MESH':
            return False
        return any(v.select for ob in context.objects_in_mode for v in bmesh.from_edit_mesh(ob.data).verts)

    def execute(self, context):
        if not self._has_components(context):
            self.report({'WARNING'}, SYMMETRIZE_NO_COMPONENTS)
            return {'CANCELLED'}
        ob = bpy.data.objects.get(self.object_name) if self.object_name else context.edit_object
        if ob is None or ob.mode != 'EDIT' or self.edge < 0:
            self.report({'WARNING'}, SYMMETRIZE_PROMPT)
            return {'CANCELLED'}
        bm = bmesh.from_edit_mesh(ob.data)
        bm.edges.ensure_lookup_table()
        if self.edge >= len(bm.edges):
            return {'CANCELLED'}
        moved = symmetrize(bm, bm.edges[self.edge], _selected_verts(bm))
        if moved is None:
            self.report({'WARNING'}, "The mesh is not topologically symmetric about that edge")
            return {'CANCELLED'}
        bmesh.update_edit_mesh(ob.data)
        return {'FINISHED'}

    def invoke(self, context, event):
        if self.edge >= 0:
            return self.execute(context)
        if not self._has_components(context):
            self.report({'WARNING'}, SYMMETRIZE_NO_COMPONENTS)
            return {'CANCELLED'}
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(SYMMETRIZE_PROMPT)
        self._header = None
        if context.area is not None and context.area.type == 'VIEW_3D':
            context.area.header_text_set(SYMMETRIZE_PROMPT)
            self._header = context.area
        return {'RUNNING_MODAL'}

    def _end(self, context):
        context.workspace.status_text_set(None)
        if self._header is not None:
            try:
                self._header.header_text_set(None)
            except ReferenceError:
                pass

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._end(context)
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            hit = _region_under(context, event.mouse_x, event.mouse_y)
            if hit is None:
                return {'RUNNING_MODAL'}
            area, region = hit
            mouse = (event.mouse_x - region.x, event.mouse_y - region.y)
            with context.temp_override(area=area, region=region):
                found = pick_edge(context, region, region.data, mouse)
            if found is None:
                return {'RUNNING_MODAL'}       # Maya keeps waiting for an edge
            self._end(context)
            self.object_name, self.edge = found[0].name, found[1]
            return self.execute(context)
        return {'PASS_THROUGH'}
