# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya UV Editor shell commands.

Shell = the kit island rule (`uv_islands.islands`, shared UV coordinates); any selected UV / edge / face of a shell picks
the whole shell for the shell commands. A "UV" = the loops of one vertex that share
one coordinate inside one face set (Maya's UV id); UVs are ordered by their first loop index, which is Maya's UV-index order
for meshes built face by face (the test meshes).
"""

import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from mathutils import Vector

from .. import compat, undo_steps
from . import uv_tools
from .uv_tools import EPS, islands, sync, uv_bounds

DELETED = Vector((0.0, 0.0))      # Delete UVs: Blender has no unmapped face — its UVs collapse here


# --- selection -----------------------------------------------------------------------------------------

def _loop_selected(loop, uv, synced):
    if synced:
        return loop.vert.select
    return compat.uv_vert_selected(loop, uv)


def uv_points(bm, uv, loops):
    """Group ``loops`` into Maya UVs (same vertex, same coordinate), ordered by their first loop index."""
    groups = {}
    for loop in sorted(loops, key=lambda l: l.index):
        p = loop[uv].uv
        key = None
        for k in groups.get(loop.vert.index, ()):
            if (k[1] - p).length <= EPS:
                key = k
                break
        if key is None:
            key = (loop.vert.index, p.copy(), [])
            groups.setdefault(loop.vert.index, []).append(key)
        key[2].append(loop)
    pts = [k[2] for ks in groups.values() for k in ks]
    pts.sort(key=lambda ls: min(l.index for l in ls))
    return pts


def _all_loops(bm):
    return [l for f in bm.faces if not f.hide for l in f.loops]


def synced_test(bm):
    """With UV Sync Selection the mesh selection picks the UVs like Maya converts it: a selected vertex = every UV
    on it, a selected edge = the UVs at its ends on the faces beside it, a selected face = the UVs of its corners
    (UVs of other faces on the same vertex stay out)."""
    mode = bm.select_mode
    if 'VERT' in mode:
        return lambda l: l.vert.select
    if 'EDGE' in mode:
        return lambda l: l.edge.select or l.link_loop_prev.edge.select
    return lambda l: l.face.select


def selected_loops(bm, uv, synced):
    """The loops of the selected UVs (a UV shared by several faces of a shell: all its loops), on shown faces."""
    if not synced:
        return {l for f in bm.faces if not f.hide and f.select for l in f.loops if compat.uv_vert_selected(l, uv)}
    if 'VERT' in bm.select_mode:
        return {l for f in bm.faces if not f.hide for l in f.loops if l.vert.select}
    test = synced_test(bm)
    _index_loops(bm)
    return {l for ls in uv_points(bm, uv, _all_loops(bm)) if any(test(l) for l in ls) for l in ls}


def selected_points(bm, uv, synced):
    """Selected UVs (lists of loops), Maya UV-index order."""
    _index_loops(bm)
    return uv_points(bm, uv, selected_loops(bm, uv, synced))


def _index_loops(bm):
    i = 0
    for f in bm.faces:
        for l in f.loops:
            l.index = i
            i += 1


def shells(bm, uv):
    return islands(bm, uv, [f for f in bm.faces if not f.hide])


def owner_map(groups):
    return {f: i for i, isl in enumerate(groups) for f in isl}


def _loops_of(island):
    return [l for f in island for l in f.loops]


def point_mean(island, uv):
    """Mean of the shell's UV positions (each Maya UV once) — Maya's Orient / Unfold pivot."""
    pts = uv_points(None, uv, _loops_of(island))
    if not pts:
        return Vector((0.0, 0.0))
    return sum((ls[0][uv].uv for ls in pts), Vector((0.0, 0.0))) / len(pts)


def bbox_centre(island, uv):
    lo, hi = uv_bounds(island, uv)
    return (lo + hi) / 2


def _move(island, uv, d):
    for l in _loops_of(island):
        l[uv].uv = l[uv].uv + d


def _rotate(island, uv, pivot, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    for l in _loops_of(island):
        p = l[uv].uv - pivot
        l[uv].uv = pivot + Vector((c * p.x - s * p.y, s * p.x + c * p.y))


def target_shells(bm, uv, synced, fallback=True):
    """Shells touched by the selection; every shell only when ``fallback`` (nothing picked in any mesh)."""
    return uv_tools.target_islands(bm, uv, synced, fallback=fallback)


# --- Stack / Orient / Orient to Edges -------------------------------------------------------------------

def stack(groups, uv):
    """Every shell's bbox centre to the centre of the bbox of all of them (Stack)."""
    if not groups:
        return 0
    lo = Vector((min(uv_bounds(g, uv)[0].x for g in groups), min(uv_bounds(g, uv)[0].y for g in groups)))
    hi = Vector((max(uv_bounds(g, uv)[1].x for g in groups), max(uv_bounds(g, uv)[1].y for g in groups)))
    centre = (lo + hi) / 2
    for g in groups:
        _move(g, uv, centre - bbox_centre(g, uv))
    return len(groups)


def _hull(points):
    pts = sorted(set((round(p.x, 9), round(p.y, 9)) for p in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _min_side(points, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    xs = [c * x - s * y for x, y in points]
    ys = [s * x + c * y for x, y in points]
    return min(max(xs) - min(xs), max(ys) - min(ys))


def orient_angle(island, uv):
    """Counter-clockwise turn in [0, 90) that makes the smaller side of the shell's UV bbox as short as possible
    (minimum caliper width — attained with a hull edge on an axis; Orient)."""
    hull = _hull([l[uv].uv for l in _loops_of(island)])
    if len(hull) < 2:
        return 0.0
    cands = {0.0}
    for i in range(len(hull)):
        (x0, y0), (x1, y1) = hull[i], hull[(i + 1) % len(hull)]
        if abs(x1 - x0) + abs(y1 - y0) < 1e-12:
            continue
        cands.add(round((-math.degrees(math.atan2(y1 - y0, x1 - x0))) % 90.0, 9) % 90.0)
    return min(sorted(cands), key=lambda d: round(_min_side(hull, d), 9))


def orient(groups, uv):
    for g in groups:
        deg = orient_angle(g, uv)
        if deg:
            _rotate(g, uv, point_mean(g, uv), deg)
    return len(groups)


def edge_turn(du, dv):
    """Maya Orient to Edges turn for a UV pair."""
    if du < 0 or (du == 0 and dv < 0):
        du, dv = -du, -dv
    a = round(math.degrees(math.atan2(dv, du)), 4)
    if a in (0.0, 90.0, -90.0):
        return 0.0
    if abs(a) == 45.0:
        return 45.0
    if abs(a) < 45:
        return -a
    return 90.0 - a if a > 0 else -(90.0 + a)


def orient_edges(bm, uv, synced, edges=None):
    """Turn each shell so its selected edge (else its first two selected UVs) is horizontal / vertical, about the
    shell's bbox centre; once per pair, in order."""
    groups = shells(bm, uv)
    where = owner_map(groups)
    pairs = []          # (shell index, loop a, loop b)
    edges = uv_tools.selected_edges(bm, uv, synced) if edges is None else edges
    # selected faces (UV Sync Selection, face mode) bring only their own UV edges, not the neighbour's side
    own = synced and set(bm.select_mode) == {'FACE'}
    for e in sorted(edges, key=lambda e: e.index):
        seen = set()
        for f in e.link_faces:
            if f.hide or f not in where or (own and not f.select):
                continue
            # without UV Sync Selection a UV edge belongs to one face: the other face's side of it is its own
            if not synced and not compat.uv_edge_selected(next(l for l in f.loops if l.edge is e), uv):
                continue
            la = next(l for l in f.loops if l.vert is e.verts[0])
            lb = next(l for l in f.loops if l.vert is e.verts[1])
            key = (where[f], tuple(round(c, 6) for c in (*la[uv].uv, *lb[uv].uv)))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((where[f], la, lb))
    if not pairs:
        by_shell = {}
        for pt in selected_points(bm, uv, synced):
            s = where.get(pt[0].face)
            if s is not None:
                by_shell.setdefault(s, []).append(pt[0])
        pairs = [(s, ls[0], ls[1]) for s, ls in by_shell.items() if len(ls) >= 2]
    for s, la, lb in pairs:
        d = lb[uv].uv - la[uv].uv
        turn = edge_turn(d.x, d.y)
        if turn:
            _rotate(groups[s], uv, bbox_centre(groups[s], uv), turn)
    return len({p[0] for p in pairs})


# --- Snap and Stack / Snap Together / Distribute / Normalize -------------------------------------------

def snap_stack(bm, uv, synced):
    """Each selected UV's shell moves so that UV lands on the bbox centre of the selected UVs."""
    pts = selected_points(bm, uv, synced)
    if not pts:
        return 0
    xs = [p[0][uv].uv.x for p in pts]
    ys = [p[0][uv].uv.y for p in pts]
    centre = Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
    groups = shells(bm, uv)
    where = owner_map(groups)
    for p in pts:
        _move(groups[where[p[0].face]], uv, centre - p[0][uv].uv)
    return len(pts)


def snap_together(bm, uv, synced, method=0):
    """Exactly two UVs: method 0 moves the first UV's shell so it lands on the second, 1 the other way."""
    pts = selected_points(bm, uv, synced)
    if len(pts) != 2:
        return None
    a, b = (pts[0], pts[1]) if method == 0 else (pts[1], pts[0])
    groups = shells(bm, uv)
    where = owner_map(groups)
    _move(groups[where[a[0].face]], uv, b[0][uv].uv.copy() - a[0][uv].uv)
    return 1


DIRECTIONS = {'RIGHT': (0, 1), 'LEFT': (0, -1), 'UP': (1, 1), 'DOWN': (1, -1)}


def distribute(groups, uv, padding=0.0, direction='RIGHT'):
    """Right: widest shell first at the selection centre, the others to its right, ``padding`` apart, centred on its
    v. Left the same to the left; Up / Down: tallest first, the others above / below, centred on its u."""
    if not groups:
        return 0
    k, sign = DIRECTIONS[direction]
    o = 1 - k
    lo = Vector((min(uv_bounds(g, uv)[0].x for g in groups), min(uv_bounds(g, uv)[0].y for g in groups)))
    hi = Vector((max(uv_bounds(g, uv)[1].x for g in groups), max(uv_bounds(g, uv)[1].y for g in groups)))
    centre = (lo + hi) / 2

    def size(g):
        a, b = uv_bounds(g, uv)
        return b[k] - a[k]
    order = sorted(groups, key=size, reverse=True)
    _move(order[0], uv, centre - bbox_centre(order[0], uv))
    mid = centre[o]
    a, b = uv_bounds(order[0], uv)
    edge = b[k] if sign > 0 else a[k]
    for g in order[1:]:
        a, b = uv_bounds(g, uv)
        d = Vector((0.0, 0.0))
        d[k] = edge + padding - a[k] if sign > 0 else edge - padding - b[k]
        d[o] = mid - (a[o] + b[o]) / 2
        _move(g, uv, d)
        a, b = uv_bounds(g, uv)
        edge = b[k] if sign > 0 else a[k]
    return len(groups)


def normalize(loops, uv, along='UV', keep_aspect=False, closest_tile=True):
    """The bbox of ``loops`` stretched to the tile under its centre (``closest_tile``; else the 0-1 tile), u and v
    separately (``along`` 'UV'; 'U' / 'V' = only that direction), or by one factor when ``keep_aspect``."""
    if not loops:
        return 0
    xs = [l[uv].uv.x for l in loops]
    ys = [l[uv].uv.y for l in loops]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    tu, tv = (math.floor((x0 + x1) / 2), math.floor((y0 + y1) / 2)) if closest_tile else (0, 0)
    sx = 1.0 / (x1 - x0) if x1 - x0 > 1e-12 else 1.0
    sy = 1.0 / (y1 - y0) if y1 - y0 > 1e-12 else 1.0
    if keep_aspect:
        sx = sy = min(sx if along != 'V' else sy, sy if along != 'U' else sx)
    for l in loops:
        p = l[uv].uv
        u = tu + (p.x - x0) * sx if along != 'V' or keep_aspect else p.x
        v = tv + (p.y - y0) * sy if along != 'U' or keep_aspect else p.y
        l[uv].uv = Vector((u, v))
    return len(loops)


# --- Move and Sew / Create UV Shell / Delete UVs -------------------------------------------------------

def _rigid_fit(src, dst):
    """Rotation angle + translation (no scale) taking points ``src`` onto ``dst`` best (2D Kabsch)."""
    n = len(src)
    cs = sum(src, Vector((0.0, 0.0))) / n
    cd = sum(dst, Vector((0.0, 0.0))) / n
    sxx = sum((p - cs).x * (q - cd).x + (p - cs).y * (q - cd).y for p, q in zip(src, dst))
    sxy = sum((p - cs).x * (q - cd).y - (p - cs).y * (q - cd).x for p, q in zip(src, dst))
    return math.atan2(sxy, sxx), cs, cd


def _along(e, fs):
    """Of the two faces ``fs`` of ``e``, the one whose corners run along the edge from its first vertex to its
    second."""
    v0 = e.verts[0]
    for f in fs:
        for l in f.loops:
            if l.edge is e:
                if l.vert is v0:
                    return f
                break
    return fs[0]


def move_sew(bm, uv, edges, max_faces=None):
    """Maya Move and Sew: per pair of shells the one with fewer faces moves rigidly onto the other along the selected
    seam edges (seams centred), then each seam UV pair merges at its average. With equal face counts the shell on the
    side of the first seam edge whose face runs along the edge's own direction moves, like Maya. A border inside one shell is sewn
    like Sew UV Edges (its UV pairs meet half-way). ``max_faces`` = the Limit shell size option: a pair whose moving
    shell has more faces than that stays apart. Returns the edges sewn."""
    groups = shells(bm, uv)
    where = owner_map(groups)
    by_pair = {}
    inside = []
    for e in sorted(edges, key=lambda e: e.index):
        fs = [f for f in e.link_faces if not f.hide]
        if len(fs) != 2:
            continue
        if where[fs[0]] == where[fs[1]]:
            inside.append((e, fs))
            continue
        by_pair.setdefault(tuple(sorted((where[fs[0]], where[fs[1]]))), []).append((e, fs))
    sewn = 0
    for (i, j), items in by_pair.items():
        mover, fixed = (i, j) if len(groups[i]) < len(groups[j]) else (j, i)
        if len(groups[i]) == len(groups[j]):
            mover = where[_along(*items[0])]
            fixed = j if mover == i else i
        if max_faces is not None and len(groups[mover]) > max_faces:
            continue
        verts = []
        for e, fs in items:
            fm = fs[0] if where[fs[0]] == mover else fs[1]
            ff = fs[1] if fm is fs[0] else fs[0]
            for v in e.verts:
                verts.append((v, fm, ff))
        seen, src, dst = set(), [], []
        for v, fm, ff in verts:
            if v in seen:
                continue
            seen.add(v)
            src.append(next(l for l in fm.loops if l.vert is v)[uv].uv.copy())
            dst.append(next(l for l in ff.loops if l.vert is v)[uv].uv.copy())
        ang, cs, cd = _rigid_fit(src, dst)
        c, s = math.cos(ang), math.sin(ang)
        for l in _loops_of(groups[mover]):
            p = l[uv].uv - cs
            l[uv].uv = cd + Vector((c * p.x - s * p.y, s * p.x + c * p.y))
        for v, fm, ff in verts:
            lm = next(l for l in fm.loops if l.vert is v)
            lf = next(l for l in ff.loops if l.vert is v)
            pm, pf = lm[uv].uv.copy(), lf[uv].uv.copy()
            mid = (pm + pf) / 2
            for l in v.link_loops:
                if l.face in where and where[l.face] in (mover, fixed) and \
                        ((l[uv].uv - pm).length <= 1e-6 or (l[uv].uv - pf).length <= 1e-6):
                    l[uv].uv = mid.copy()
        for e, _fs in items:
            e.seam = False
        sewn += len(items)
    for e, (a, b) in inside:
        if uv_tools.weld_edge(e, a, b, uv):
            e.seam = False
            sewn += 1
    return sewn


def create_shell(bm, uv, faces):
    """Maya Create UV Shell: cut along the border of ``faces`` (edges to unselected faces); uv_tools.cut nudges the
    smaller side by uv_islands.NUDGE so the island rule sees two shells."""
    fs = set(faces)
    border = [e for f in faces for e in f.edges
              if len([g for g in e.link_faces if not g.hide]) == 2 and any(g not in fs for g in e.link_faces)]
    border = list({e: None for e in border})
    return uv_tools.cut(bm, uv, border) if border else 0


def delete_faces(bm, uv, synced, uv_mode='VERTEX'):
    """Faces that lose their UVs in Maya (polyMapDel): every face using a selected face / edge / UV."""
    if synced:
        if 'FACE' in bm.select_mode:
            return [f for f in bm.faces if not f.hide and f.select]
        if 'EDGE' in bm.select_mode:
            return [f for f in bm.faces if not f.hide and any(e.select for e in f.edges)]
        return [f for f in bm.faces if not f.hide and any(v.select for v in f.verts)]
    if uv_mode == 'FACE':
        return uv_tools.selected_faces(bm, uv, False)
    if uv_mode == 'EDGE':
        return [f for f in bm.faces if not f.hide and f.select and any(compat.uv_edge_selected(l, uv) for l in f.loops)]
    return [f for f in bm.faces if not f.hide and f.select and any(_loop_selected(l, uv, False) for l in f.loops)]


def delete_uvs(faces, uv):
    for f in faces:
        for l in f.loops:
            l[uv].uv = DELETED.copy()
    return len(faces)


# --- operators -------------------------------------------------------------------------------------------

def _meshes(context):
    return [o for o in getattr(context, "objects_in_mode_unique_data", ()) if o.type == 'MESH']


def _poll(context):
    return context.mode == 'EDIT_MESH'


class _ShellOp:
    bl_options = {'REGISTER', 'UNDO'}
    empty = "Select UV shells"
    # "the selected shells, all when none are selected" counts the selection of every mesh in edit mode: a mesh
    # with nothing picked is left alone while another mesh has a pick
    _fallback = True
    # a main UV menu command: with UV Sync Selection off it can take the 3D View selection
    # (uv_components.mesh_selection_wanted)
    reads_3d = False

    poll = classmethod(lambda cls, context: _poll(context))

    def run(self, context, bm, uv, synced):
        raise NotImplementedError

    def execute(self, context):
        done = 0
        synced = sync(context) or (self.reads_3d and uv_tools.mesh_selection_wanted(context))
        self._fallback = not uv_tools.picked_anywhere(context)
        for ob in _meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            uv = bm.loops.layers.uv.verify()
            _index_loops(bm)
            got = self.run(context, bm, uv, synced)
            if got:
                done += got
                bmesh.update_edit_mesh(ob.data)
        if not done:
            self.report({'WARNING'}, self.empty)
            return {'CANCELLED'}
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_uv_stack(_ShellOp, bpy.types.Operator):
    """Stack the selected UV shells on the centre of their bounding box (Maya Stack Shells)"""
    bl_idname = "allset.uv_stack"
    bl_label = "Stack Shells"

    orient: EnumProperty(items=[('NONE', "Stack", ""), ('ORIENT', "Stack and Orient", "")], default='NONE',
                         options={'SKIP_SAVE'})

    def run(self, context, bm, uv, synced):
        groups = target_shells(bm, uv, synced, self._fallback)
        n = stack(groups, uv)
        if self.orient == 'ORIENT':
            orient(groups, uv)
        return n


@undo_steps.no_redo_panel
class ALLSET_OT_uv_orient_shells(_ShellOp, bpy.types.Operator):
    """Turn each selected UV shell to its narrowest bounding box, counter-clockwise (Maya Orient Shells)"""
    bl_idname = "allset.uv_orient_shells"
    bl_label = "Orient Shells"

    def run(self, context, bm, uv, synced):
        return orient(target_shells(bm, uv, synced, self._fallback), uv)


@undo_steps.no_redo_panel
class ALLSET_OT_uv_orient_edges(_ShellOp, bpy.types.Operator):
    """Turn each shell so its selected edge is horizontal or vertical (Maya Orient Shells to Edges)"""
    bl_idname = "allset.uv_orient_edges"
    bl_label = "Orient Shells to Edges"
    empty = "Select a UV edge (or two UVs) on each shell"

    def run(self, context, bm, uv, synced):
        return orient_edges(bm, uv, synced)


@undo_steps.no_redo_panel
class ALLSET_OT_uv_snap_stack(_ShellOp, bpy.types.Operator):
    """Move the shells so their selected UVs meet at the centre of those UVs (Maya Snap and Stack)"""
    bl_idname = "allset.uv_snap_stack"
    bl_label = "Snap and Stack"
    empty = "Select one UV on each shell"

    def run(self, context, bm, uv, synced):
        return snap_stack(bm, uv, synced)


@undo_steps.no_redo_panel
class ALLSET_OT_uv_snap_together(_ShellOp, bpy.types.Operator):
    """Move the first selected UV's shell so that UV lands on the second (Maya Snap Together)"""
    bl_idname = "allset.uv_snap_together"
    bl_label = "Snap Together"
    empty = "Select exactly two UVs"

    method: EnumProperty(items=[('0', "First onto Second", ""), ('1', "Second onto First", "")], default='0',
                         options={'SKIP_SAVE'})

    def run(self, context, bm, uv, synced):
        return snap_together(bm, uv, synced, int(self.method))

    def execute(self, context):
        total = 0
        for ob in _meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            _index_loops(bm)
            total += len(selected_points(bm, bm.loops.layers.uv.verify(), sync(context)))
        if total != 2:
            self.report({'WARNING'}, "Snap Together needs exactly two UVs selected")
            return {'CANCELLED'}
        return super().execute(context)


@undo_steps.no_redo_panel
class ALLSET_OT_uv_distribute(_ShellOp, bpy.types.Operator):
    """Line the selected shells up to the right, widest first, touching (Maya Distribute Shells)"""
    bl_idname = "allset.uv_distribute"
    bl_label = "Distribute Shells"

    # the Distribute Shells options
    direction: EnumProperty(items=[(d, d.title(), "") for d in DIRECTIONS], default='RIGHT', options={'SKIP_SAVE'})
    padding: FloatProperty(name="Shell Padding", default=0.0, options={'SKIP_SAVE'})

    def run(self, context, bm, uv, synced):
        return distribute(target_shells(bm, uv, synced, self._fallback), uv, self.padding, self.direction)


@undo_steps.no_redo_panel
class ALLSET_OT_uv_normalize(_ShellOp, bpy.types.Operator):
    """Scale the UVs of the faces the selection touches to fill the 0-1 tile under them, u and v separately (Maya
    Normalize); UVs shared with untouched faces split off"""
    bl_idname = "allset.uv_normalize"
    bl_label = "Normalize"

    # the Normalize options
    along: EnumProperty(items=[('UV', "UV", ""), ('U', "U", ""), ('V', "V", "")], default='UV', options={'SKIP_SAVE'})
    each_face: BoolProperty(name="Each face separately", default=False, options={'SKIP_SAVE'})
    keep_aspect: BoolProperty(name="Preserve aspect ratio", default=False, options={'SKIP_SAVE'})
    closest_tile: BoolProperty(name="Center on closest tile", default=True, options={'SKIP_SAVE'})

    def run(self, context, bm, uv, synced):
        faces = uv_tools.selected_faces(bm, uv, synced)
        if not faces:
            # selected UVs / edges: every face using one of them, like Maya
            touched = {l.face for p in selected_points(bm, uv, synced) for l in p}
            faces = sorted(touched, key=lambda f: f.index)
        groups = [[f] for f in faces] if self.each_face else [faces]
        for fs in groups:
            normalize([l for f in fs for l in f.loops], uv, self.along, self.keep_aspect, self.closest_tile)
        return len(faces)


@undo_steps.no_redo_panel
class ALLSET_OT_uv_unstack(_ShellOp, bpy.types.Operator):
    """Spread the selected shells apart so none overlap, keeping their size and the group's centre
    (Maya Unstack Shells; Blender Pack Islands without scaling)"""
    bl_idname = "allset.uv_unstack"
    bl_label = "Unstack Shells"

    # the Unstack option: mirrored (reversed) shells are flipped back first, like Maya
    flip_reversed: BoolProperty(name="Flip reversed UV shells", default=True, options={'SKIP_SAVE'})

    def execute(self, context):
        done = 0
        fallback = not uv_tools.picked_anywhere(context)
        for ob in _meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            uv = bm.loops.layers.uv.verify()
            groups = target_shells(bm, uv, sync(context), fallback)
            if len(groups) < 2:
                continue
            if self.flip_reversed:
                from .uv_modify import _signed_area
                for g in groups:
                    if _signed_area(g, uv) < 0:
                        c = bbox_centre(g, uv)
                        for loop in _loops_of(g):
                            loop[uv].uv.x = 2 * c.x - loop[uv].uv.x
            faces = [f for g in groups for f in g]
            bm.faces.index_update()
            idx = [f.index for f in faces]
            lo, hi = _group_bounds(groups, uv)
            before = (lo + hi) / 2
            uv_tools._with_faces(context, ob, faces, lambda: bpy.ops.uv.pack_islands(
                rotate=True, scale=False, margin_method='FRACTION', margin=0.002))
            bm = bmesh.from_edit_mesh(ob.data)
            uv = bm.loops.layers.uv.verify()
            bm.faces.ensure_lookup_table()
            moved = [[bm.faces[i] for i in idx]]
            lo, hi = _group_bounds(moved, uv)
            _move(moved[0], uv, before - (lo + hi) / 2)
            bmesh.update_edit_mesh(ob.data)
            done += len(groups)
        if not done:
            self.report({'WARNING'}, "Select two or more UV shells")
            return {'CANCELLED'}
        return {'FINISHED'}


def _group_bounds(groups, uv):
    bs = [uv_bounds(g, uv) for g in groups]
    return (Vector((min(b[0].x for b in bs), min(b[0].y for b in bs))),
            Vector((max(b[1].x for b in bs), max(b[1].y for b in bs))))


@undo_steps.no_redo_panel
class ALLSET_OT_uv_move_sew(_ShellOp, bpy.types.Operator):
    """Move the smaller shell onto the other along the selected edges and sew them (Maya Move and Sew)"""
    bl_idname = "allset.uv_move_sew"
    bl_label = "Move and Sew"
    empty = "Select UV edges between two shells"

    # the Move and Sew options: Limit shell size, Number of faces
    limit: BoolProperty(name="Limit shell size", default=False, options={'SKIP_SAVE'})
    faces: IntProperty(name="Number of faces", default=10, min=0, options={'SKIP_SAVE'})

    def run(self, context, bm, uv, synced):
        edges = uv_tools.selected_edges(bm, uv, synced)
        if not edges:
            fs = set(uv_tools.selected_faces(bm, uv, synced))
            edges = [e for f in fs for e in f.edges]
        return move_sew(bm, uv, edges, self.faces if self.limit else None)


@undo_steps.no_redo_panel
class ALLSET_OT_uv_create_shell(_ShellOp, bpy.types.Operator):
    """Cut the UVs around the selected faces so they become their own shell (Maya Create UV Shell)"""
    bl_idname = "allset.uv_create_shell"
    bl_label = "Create UV Shell"
    empty = "Select faces inside a UV shell"

    def run(self, context, bm, uv, synced):
        return create_shell(bm, uv, uv_tools.selected_faces(bm, uv, synced))


@undo_steps.no_redo_panel
class ALLSET_OT_uv_delete(_ShellOp, bpy.types.Operator):
    """Delete the UVs of every face that uses the selection (Maya Delete UVs: Blender keeps a UV per corner, so
    they collapse to 0,0)"""
    bl_idname = "allset.uv_delete"
    bl_label = "Delete UVs"
    empty = "Select UVs, edges or faces"
    reads_3d = True

    def run(self, context, bm, uv, synced):
        return delete_uvs(delete_faces(bm, uv, synced, context.scene.tool_settings.uv_select_mode), uv)


def merge_points(pts, uv, distance):
    """Maya Merge UVs (polyMergeUV -d): among the given UVs (lists of
    loops), UVs **of the same vertex** closer than ``distance`` (chains included) move to their average; UVs of
    different vertices never merge. Returns how many UVs went away."""
    by_vert = {}
    for pt in pts:
        by_vert.setdefault(pt[0].vert.index, []).append(pt)
    gone = 0
    for group in by_vert.values():
        if len(group) < 2:
            continue
        cos = [pt[0][uv].uv.copy() for pt in group]
        parent = list(range(len(group)))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if (cos[i] - cos[j]).length <= distance + 1e-12:
                    parent[root(i)] = root(j)
        clusters = {}
        for i in range(len(group)):
            clusters.setdefault(root(i), []).append(i)
        for members in clusters.values():
            if len(members) < 2:
                continue
            mean = sum((cos[i] for i in members), Vector((0.0, 0.0))) / len(members)
            for i in members:
                _set_pt(group[i], uv, mean)
            gone += len(members) - 1
    return gone


def _set_pt(pt, uv, p):
    for loop in pt:
        loop[uv].uv = p


@undo_steps.no_redo_panel
class ALLSET_OT_uv_merge(_ShellOp, bpy.types.Operator):
    """Merge the selected UVs of each vertex that lie within the threshold (default 0.01; Maya UV > Merge UVs)"""
    bl_idname = "allset.uv_merge"
    bl_label = "Merge UVs"
    empty = "Select UVs to merge"

    distance: FloatProperty(name="Threshold", default=0.01, min=0.0, soft_max=1.0, options={'SKIP_SAVE'})
    reads_3d = True

    def run(self, context, bm, uv, synced):
        pts = selected_points(bm, uv, synced)
        if not pts:
            return 0
        merge_points(pts, uv, self.distance)
        return len(pts)


classes = (ALLSET_OT_uv_merge, ALLSET_OT_uv_stack, ALLSET_OT_uv_orient_shells, ALLSET_OT_uv_orient_edges, ALLSET_OT_uv_snap_stack,
           ALLSET_OT_uv_snap_together, ALLSET_OT_uv_distribute, ALLSET_OT_uv_normalize, ALLSET_OT_uv_unstack,
           ALLSET_OT_uv_move_sew, ALLSET_OT_uv_create_shell, ALLSET_OT_uv_delete)
