# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya UV Editor > Cut/Sew > Stitch Together (``allset.uv_stitch_together``): stitch shells along the selected
border edges at once.

Like Maya:
- Works on the selected UV edges or UVs (faces alone are not enough). Of those, the edges where the UVs on both sides
  differ at both ends (a cut between two shells) line the shells up.
- Each such edge (in edge order) joins the two shells on its sides, once per pair of shells: by default (Smallest to
  Largest) the shell with the smaller UV area moves onto the other one (Largest to Smallest: the larger one moves).
  The moving shell is moved so the middles of the two edge copies meet, turned so the edges lie on one line with
  the two faces on opposite sides, and scaled so the edge lengths match. A joined pair then counts as one shell
  whose area is that of the shell that stayed (Smallest to Largest) or that moved (Largest to Smallest).
- Afterwards the selected border edges are sewn (Move and Sew): the UVs that now meet become one.
"""

import math

import bmesh
import bpy
from bpy.props import EnumProperty
from mathutils import Vector

from .. import undo_steps
from . import uv_shells, uv_tools
from .uv_islands import _same, _uv_at, _uv_area, islands

ORDERS = ('SMALL_TO_LARGE', 'LARGE_TO_SMALL')
ORDER_LABELS = {"Smallest to Largest": 'SMALL_TO_LARGE', "Largest to Smallest": 'LARGE_TO_SMALL'}


def _split_ends(e, a, b, uv):
    """How many ends of ``e`` have different UVs on faces ``a`` and ``b``."""
    return sum(not _same(_uv_at(a, v, uv), _uv_at(b, v, uv)) for v in e.verts)


def border_edges(edges, uv):
    """The edges of ``edges`` that lie on a UV border between two faces: (edge, face a, face b, split ends)."""
    out = []
    for e in sorted(set(edges), key=lambda e: e.index):
        fs = sorted((f for f in e.link_faces if not f.hide), key=lambda f: f.index)
        if len(fs) != 2:
            continue
        n = _split_ends(e, fs[0], fs[1], uv)
        if n:
            out.append((e, fs[0], fs[1], n))
    return out


def _face_centre(face, uv):
    """Centre of the face's UV bounding box."""
    xs = [l[uv].uv.x for l in face.loops]
    ys = [l[uv].uv.y for l in face.loops]
    return Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))


def _cross(a, b):
    return a.x * b.y - a.y * b.x


def _sign(x):
    return (x > 0) - (x < 0)


def _place(e, mover_face, fixed_face, uv):
    """(pivot, turn in radians, scale, move) that put the mover's copy of ``e`` onto the fixed face's copy, the two
    faces on opposite sides of it."""
    v0, v1 = e.verts
    m0, m1 = _uv_at(mover_face, v0, uv).copy(), _uv_at(mover_face, v1, uv).copy()
    f0, f1 = _uv_at(fixed_face, v0, uv).copy(), _uv_at(fixed_face, v1, uv).copy()
    dm, df = m1 - m0, f1 - f0
    if dm.length < 1e-12 or df.length < 1e-12:
        return None
    mid_m, mid_f = (m0 + m1) / 2, (f0 + f1) / 2
    side_m = _sign(_cross(dm, _face_centre(mover_face, uv) - m0))
    side_f = _sign(_cross(df, _face_centre(fixed_face, uv) - f0))
    if side_m == side_f:
        df = -df          # the same side: line the edges up the other way round, so the faces end up apart
    turn = math.atan2(_cross(dm, df), dm.dot(df))
    return mid_f, turn, df.length / dm.length, mid_f - mid_m


def _transform(loops, uv, pivot, turn, scale, move):
    c, s = math.cos(turn) * scale, math.sin(turn) * scale
    for l in loops:
        p = l[uv].uv + move - pivot
        l[uv].uv = pivot + Vector((c * p.x - s * p.y, s * p.x + c * p.y))


def stitch_together(bm, uv, edges, order='SMALL_TO_LARGE'):
    """Stitch the shells along ``edges`` (Maya Stitch Together with the order option). Returns the number of
    shell pairs lined up plus the edges sewn."""
    border = border_edges(edges, uv)
    if not border:
        return 0
    groups = islands(bm, uv, [f for f in bm.faces if not f.hide])
    where = {f: i for i, g in enumerate(groups) for f in g}
    area = [sum(abs(_uv_area(f, uv)) for f in g) for g in groups]
    members = [list(g) for g in groups]
    parent = list(range(len(groups)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    joined = 0
    for e, a, b, n in border:
        if n < 2:
            continue      # one end already shared: nothing to line up, the sew below joins it
        ra, rb = root(where[a]), root(where[b])
        if ra == rb:
            continue
        a_larger = area[ra] > area[rb]
        if order == 'SMALL_TO_LARGE':
            mover_a = not a_larger
        else:
            mover_a = a_larger
        (rm, fm), (rf, ff) = ((ra, a), (rb, b)) if mover_a else ((rb, b), (ra, a))
        placed = _place(e, fm, ff, uv)
        if placed is None:
            continue
        _transform([l for f in members[rm] for l in f.loops], uv, *placed)
        kept = max(area[ra], area[rb]) if order == 'SMALL_TO_LARGE' else min(area[ra], area[rb])
        parent[rm] = rf
        members[rf] += members[rm]
        area[rf] = kept
        joined += 1
    sewn = uv_shells.move_sew(bm, uv, [e for e, _a, _b, _n in border])
    return joined + sewn


def _faces_only(context, synced):
    ts = context.scene.tool_settings
    if synced:
        return tuple(ts.mesh_select_mode) == (False, False, True)
    return ts.uv_select_mode == 'FACE'


@undo_steps.no_redo_panel
class ALLSET_OT_uv_stitch_together(uv_shells._ShellOp, bpy.types.Operator):
    """Stitch the shells along the selected border edges at once: the smaller shell moves, turns and scales onto the
    larger one and the edges are sewn (Maya Stitch Together)"""
    bl_idname = "allset.uv_stitch_together"
    bl_label = "Stitch Together"
    empty = "Select UV edges or UVs on the border between two shells"
    reads_3d = True

    order: EnumProperty(name="Stitch Together", items=[
        ('SMALL_TO_LARGE', "Smallest to Largest", "The smaller shell moves onto the larger one"),
        ('LARGE_TO_SMALL', "Largest to Smallest", "The larger shell moves onto the smaller one")],
        default='SMALL_TO_LARGE', options={'SKIP_SAVE'})

    def execute(self, context):
        synced = uv_tools.sync(context) or uv_tools.mesh_selection_wanted(context)
        if _faces_only(context, synced):
            self.report({'WARNING'}, "Some edges or UVs must be selected")
            return {'CANCELLED'}
        return super().execute(context)

    def run(self, context, bm, uv, synced):
        edges = uv_tools.selected_edges(bm, uv, synced)
        return stitch_together(bm, uv, edges, self.order) if edges else 0


classes = (ALLSET_OT_uv_stitch_together,)
