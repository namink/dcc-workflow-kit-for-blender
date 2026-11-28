# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya UV Editor > Modify > Flip (``allset.uv_flip``) with the Flip UVs Options.

Like Maya:
- Flip works on faces: the selected faces, or every face that uses a selected UV (edges / UVs selected).
- Direction: Horizontal mirrors U, Vertical mirrors V.
- Coordinate: Pivot (the UV pivot: the UV Editor's 2D cursor while it is the pivot, else the centre of the selection's
  UV bounding box; default), Selection Center (the centre of the flipped faces' UV bounding box) or Global (the
  0 line: U becomes -U, or V becomes -V).
- Cut UV Perimeter (on by default): the flipped faces are cut free along their border first, so the faces next to
  them stay where they are; off, the UVs they share move with them and pull the neighbours along.
- The UV Toolkit's Flip U / Flip V buttons and the UV marking menu's Flip Along U / V items flip in their own
  direction with the Coordinate and Cut UV Perimeter of the Flip options.
"""

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty

from .. import undo_steps
from . import uv_shells, uv_tools, uv_transform
from .uv_islands import EPS

COORDINATES = {"Pivot": 'PIVOT', "Selection Center": 'CENTER', "Global": 'GLOBAL'}


def _faces(bm, uv, synced, mode):
    """The faces Flip works on (``mode`` = the selection mode: 'FACE' takes whole faces)."""
    if mode == 'FACE':
        return uv_tools.selected_faces(bm, uv, synced)
    picked = uv_shells.selected_loops(bm, uv, synced)
    return [f for f in bm.faces if not f.hide and (synced or f.select) and any(l in picked for l in f.loops)]


def _selected_loops(bm, uv, synced, mode, faces):
    """The loops of the selection itself (its UV box is the pivot when no UV pivot is set)."""
    if mode == 'FACE':
        return [l for f in faces for l in f.loops]
    picked = uv_shells.selected_loops(bm, uv, synced)
    return [l for f in faces for l in f.loops if l in picked]


def _box_centre(points):
    us = [p.x for p in points]
    vs = [p.y for p in points]
    return (min(us) + max(us)) / 2, (min(vs) + max(vs)) / 2


def flip_loops(faces, uv, cut):
    """The loops a flip of ``faces`` moves: their own loops, plus (``cut`` off) every loop that shares one of their
    UVs. With ``cut`` the border edges to the other faces become seams."""
    loops = {l for f in faces for l in f.loops}
    fs = set(faces)
    if cut:
        for f in faces:
            for e in f.edges:
                if any(g not in fs and not g.hide for g in e.link_faces):
                    e.seam = True
        return loops
    extra = set()
    for l in loops:
        p = l[uv].uv
        for other in l.vert.link_loops:
            if other.face not in fs and not other.face.hide and (other[uv].uv - p).length <= EPS:
                extra.add(other)
    return loops | extra


def _mode(context, synced):
    ts = context.scene.tool_settings
    if synced:
        return 'FACE' if tuple(ts.mesh_select_mode) == (False, False, True) else 'UV'
    return 'FACE' if ts.uv_select_mode == 'FACE' else 'UV'


@undo_steps.no_redo_panel
class ALLSET_OT_uv_flip(bpy.types.Operator):
    """Mirror the selected UVs horizontally or vertically with the Flip options (Maya Flip): around the UV pivot, the
    selection's centre or the 0 line, cutting the flipped faces free first"""
    bl_idname = "allset.uv_flip"
    bl_label = "Flip"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(name="Direction", items=[('HORIZONTAL', "Horizontal", ""), ('VERTICAL', "Vertical", "")],
                            default='HORIZONTAL', options={'SKIP_SAVE'})
    coordinate: EnumProperty(name="Coordinate", items=[('PIVOT', "Pivot", ""), ('CENTER', "Selection Center", ""),
                                                       ('GLOBAL', "Global", "")],
                             default='PIVOT', options={'SKIP_SAVE'})
    cut: BoolProperty(name="Cut UV Perimeter", default=True, options={'SKIP_SAVE'})
    # the UV Toolkit's Flip U / Flip V buttons and the Flip Along U / V marking menu items: their own direction with
    # the Coordinate and Cut UV Perimeter of the Flip options (saved values, else the option defaults)
    use_options: BoolProperty(name="Use Flip Options", default=False, options={'SKIP_SAVE', 'HIDDEN'})

    poll = classmethod(lambda cls, context: context.mode == 'EDIT_MESH')

    def execute(self, context):
        if self.use_options:
            from . import option_windows
            v = option_windows.current("uv_flip")
            self.coordinate = COORDINATES.get(v.get("coordinate"), 'PIVOT')
            self.cut = bool(v.get("cut", True))
        synced = uv_tools.sync(context) or uv_tools.mesh_selection_wanted(context)
        mode = _mode(context, synced)
        found = []
        for ob in uv_shells._meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            uv = bm.loops.layers.uv.active
            if uv is None:
                continue
            faces = _faces(bm, uv, synced, mode)
            if faces:
                found.append((ob, bm, uv, faces))
        if not found:
            self.report({'WARNING'}, "Select UVs or faces to flip")
            return {'CANCELLED'}
        axis = 0 if self.direction == 'HORIZONTAL' else 1
        # one mirror line for every mesh: the selection's centre is the centre of them all together
        if self.coordinate == 'GLOBAL':
            centre = (0.0, 0.0)
        elif self.coordinate == 'CENTER':
            centre = _box_centre([l[uv].uv for _o, _b, uv, fs in found for f in fs for l in f.loops])
        else:
            space = uv_transform._space(context)
            if space is not None and space.pivot_point == 'CURSOR':
                centre = uv_transform.cursor_uv(space)
            else:
                centre = _box_centre([l[uv].uv for _o, bm, uv, fs in found
                                      for l in _selected_loops(bm, uv, synced, mode, fs)])
        for ob, bm, uv, faces in found:
            for l in flip_loops(faces, uv, self.cut):
                p = l[uv].uv.copy()
                p[axis] = 2.0 * centre[axis] - p[axis]
                l[uv].uv = p
            bmesh.update_edit_mesh(ob.data)
        return {'FINISHED'}


classes = (ALLSET_OT_uv_flip,)
