# SPDX-License-Identifier: GPL-3.0-or-later
"""UV Editor > Tools > Unfold, Optimize, Cut, Sew, Pin, Smear and Smudge as brush tools, like Maya.

Choosing one in the Tools menu makes it the UV Editor's active tool (ui/uv_brush_tools.py); an LMB drag applies it
under the brush, the brush circle follows the mouse, B + LMB drag left / right sets the brush size, M + LMB drag up /
down its strength, and Q / W / E / R leave it like any tool. One stroke = one undo step.

- Unfold / Optimize: the UVs under the brush relax against the 3D surface (operators/uv_brush_math.relax); UVs
  outside the brush, pinned UVs and, when some UVs are selected, the unselected ones stay. Unfold flattens; Optimize
  keeps the Surface Angle balance. A click or a very short drag does nothing.
- Cut: the edge lines the stroke runs along are cut on release (operators/uv_brush_math.CutPick); Ctrl or Shift +
  drag does nothing.
- Sew: the shell border edges under the brush are sewn on release (the smaller shell moves onto the other);
  Ctrl+drag cuts like the Cut tool.
- Pin: the UVs under the brush are pinned; Ctrl+drag unpins them.
- Smear: the UVs under the brush are pushed along the stroke (the first mouse move only places the brush).
- Symmetrize: the first click picks an edge on the symmetry line; then the UVs under the brush, on its side of the
  Axis Position line, take their counterpart's UV mirrored across it (operators/uv_symmetrize.py).
- Smudge: only selected UVs move. Fixed: those under the brush where the stroke starts follow it (a steep falloff);
  Smudge: those the brush passes over are pulled along each mouse move by the Pressure.
Settings live in ``Scene.allset_uv_brush``.
"""

import math

import bmesh
import bpy
import gpu
import numpy as np
from mathutils import Vector
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty
from gpu_extras.batch import batch_for_shader

from .. import compat, live_refs, results
from . import taphold, uv_brush_math, uv_symmetrize, uv_tools
from .uv_islands import sync
from .uv_shells import _loop_selected

PREFIX = "allset.uv_brush_"
MODES = ("UNFOLD", "OPTIMIZE", "CUT", "SEW", "PIN", "SMEAR", "SMUDGE", "GRAB", "PINCH", "SYMMETRIZE")
TOOL_IDS = {m: PREFIX + m.lower() for m in MODES}
MODE_OF_TOOL = {v: k for k, v in TOOL_IDS.items()}
# mode -> (size property, strength property) in Scene.allset_uv_brush; Unfold and Optimize share one brush like Maya
BRUSH_PROPS = {"UNFOLD": ("relax_size", "relax_strength"), "OPTIMIZE": ("relax_size", "relax_strength"),
               "CUT": (None, None), "SEW": ("sew_size", None), "PIN": ("pin_size", "pin_strength"),
               "SMEAR": ("smear_size", "smear_strength"), "SMUDGE": ("smudge_size", "smudge_pressure"),
               "GRAB": ("grab_size", "grab_strength"), "PINCH": ("pinch_size", "pinch_strength"),
               "SYMMETRIZE": ("sym_size", None)}
SYM_PICK_PX = 10          # Symmetrize: how near (pixels) a click must be to an edge to pick it
SPACING = 0.25            # a dab every quarter brush radius along the stroke
CIRCLE_RGB = (0.9, 0.9, 0.9)
CIRCLE_SEGMENTS = 48
STROKE_RGB = (1.0, 0.85, 0.1)       # the edges a Cut / Sew stroke collected (Maya draws the path yellow)
BORDER_RGB = (0.35, 0.8, 1.0)       # Display All Shell Borders
BORDER_CHECK_S = 0.3                # the shell borders are looked up again at most this often while hovering


class ALLSET_PG_uv_brush(bpy.types.PropertyGroup):
    relax_size: FloatProperty(name="Size", default=0.1, min=0.0, max=100.0, soft_max=2.0, precision=3,
                              description="Brush radius in UV space (b + drag left / right)")
    relax_strength: FloatProperty(name="Strength", default=0.5, min=0.0, max=1.0, precision=3,
                                  description="How far the UVs move each dab (m + drag up / down)")
    surfangle: FloatProperty(name="Surface Angle", default=1.0, min=0.0, max=1.0, precision=3,
                             description="Optimize: keeping the surface area (1) against keeping only the angles (0)")
    cut_sensitivity: FloatProperty(name="Edge Select Sensitivity", default=0.2, min=0.1, max=0.5, precision=3,
                                   description="How much of an edge the stroke may leave out and still cut it, as a "
                                               "part of the edge's length")
    sew_size: FloatProperty(name="Size", default=0.04, min=0.00001, max=1.0, precision=3,
                            description="Sew brush radius in UV space (b + drag left / right)")
    cut_steady: BoolProperty(name="Steady Stroke", default=False,
                             description="Cut / Sew: the stroke trails the mouse by the Distance, for a smoother line")
    cut_steady_distance: FloatProperty(name="Distance", default=0.1, min=0.0, max=10.0, soft_max=1.0, precision=3,
                                       description="How far the steady stroke trails the mouse, in UV space")
    cut_open_ratio: FloatProperty(name="Cut Open Ratio", default=0.1, min=0.0, max=1.0, precision=3,
                                  description="The gap left between the UVs a cut splits, as a part of the cut "
                                              "edges' length (0 = the split UVs stay on each other)")
    show_shell_borders: BoolProperty(name="Display All Shell Borders", default=False,
                                     description="Cut / Sew: draw every UV shell border while the tool is active")
    pin_size: FloatProperty(name="Size", default=0.1, min=0.0, max=10000.0, soft_max=1.0, precision=3,
                            description="Brush radius in UV space (b + drag left / right)")
    pin_method: EnumProperty(name="Paint Method", default='PAINT', items=(
        ('PAINT', "Paint", "Drag pins the UVs under the brush (Ctrl unpins, Shift smooths)"),
        ('SMOOTH', "Smooth", "Drag smooths the pins under the brush")),
        description="How a Pin stroke changes the pins")
    pin_strength: FloatProperty(name="Strength", default=100.0, min=0.0, max=100000.0, soft_max=100.0, precision=3,
                                description="Pin strength (m + drag up / down)")
    smear_size: FloatProperty(name="Size", default=0.1, min=0.0, max=10000.0, soft_max=1.0, precision=3,
                              description="Brush radius in UV space (b + drag left / right)")
    smear_strength: FloatProperty(name="Strength", default=0.05, min=0.0, max=100000.0, soft_max=100.0, precision=3,
                                  description="How strongly the UVs follow the stroke (m + drag up / down)")
    grab_size: FloatProperty(name="Size", default=0.1, min=0.0, max=10000.0, soft_max=1.0, precision=3,
                             description="Brush radius in UV space (b + drag left / right)")
    grab_strength: FloatProperty(name="Strength", default=80.0, min=0.0, max=100000.0, soft_max=100.0, precision=3,
                                 description="How far the UVs under the brush follow the mouse, in percent "
                                             "(m + drag up / down)")
    grab_direction: EnumProperty(name="Direction", default='UV', items=(
        ('UV', "UV", "The UVs follow the mouse freely"),
        ('U', "U", "The UVs follow the mouse along U only"),
        ('V', "V", "The UVs follow the mouse along V only")))
    grab_twist: BoolProperty(name="Twist", default=False,
                             description="Ctrl+drag turns the UVs under the brush clockwise or counterclockwise")
    pinch_size: FloatProperty(name="Size", default=0.1, min=0.0, max=10000.0, soft_max=1.0, precision=3,
                              description="Brush radius in UV space (b + drag left / right)")
    pinch_strength: FloatProperty(name="Strength", default=10.0, min=0.0, max=100000.0, soft_max=100.0, precision=3,
                                  description="How strongly the UVs are pulled to the stroke (m + drag up / down)")
    sym_size: FloatProperty(name="Brush size", default=0.1, min=0.0, max=10000.0, soft_max=1.0, precision=3,
                            description="Brush radius in UV space (b + drag left / right)")
    sym_axis: EnumProperty(name="Mirror Axis", default='U', items=(
        ('U', "U", "Mirror across a line of constant U (picking an up-down edge sets it)"),
        ('V', "V", "Mirror across a line of constant V (picking a side-to-side edge sets it)")))
    sym_axis_pos: FloatProperty(name="Mirror Axis Position", default=0.5, soft_min=-10.0, soft_max=10.0,
                                precision=4, step=10, description="Where the mirror line is, in UV space")
    sym_flood: BoolProperty(name="Flood Shells", default=False,
                            description="A shell the brush touches is symmetrized on that whole side")
    smudge_size: FloatProperty(name="Smudge size", default=0.075, min=0.0, max=10.0, soft_max=1.0, precision=3,
                               description="Brush radius in UV space (b + drag left / right)")
    smudge_pressure: FloatProperty(name="Pressure", default=0.01, min=0.0, max=1.0, precision=3,
                                   description="Smudge effect: how strongly the UVs follow the stroke")
    smudge_effect: EnumProperty(name="Effect type", default='FIXED', items=(
        ('FIXED', "Fixed", "The UVs under the brush where the stroke starts follow it"),
        ('SMUDGE', "Smudge", "The UVs the brush passes over are pushed along with the pressure")))
    smudge_falloff: EnumProperty(name="Falloff type", default='EXPONENTIAL', items=(
        ('EXPONENTIAL', "Exponential", "The UVs near the brush centre follow most, the others much less"),
        ('LINEAR', "Linear", "The pull fades evenly to the brush edge"),
        ('CONSTANT', "Constant", "Every UV inside the brush follows the same")))
    smudge_middle: BoolProperty(name="Middle mouse initiates", default=False,
                                description="Smudge with a middle-mouse drag instead of a left-mouse drag")
    show_ring: BoolProperty(name="Show brush ring during stroke", default=True)
    falloff_type: EnumProperty(name="Type", default='SURFACE_VOLUME', items=(
        ('SURFACE_VOLUME', "Surface/Volume", "The brush reaches the UVs in its circle that are joined to the part of "
                                             "the shell under its centre, by straight distance"),
        ('SURFACE', "Surface", "The brush reaches the UVs joined to the part of the shell under its centre, by the "
                               "distance along the UV edges"),
        ('VOLUME', "Volume", "The brush reaches every UV in its circle, other shells and across cuts too")),
        description="How the brush falloff reaches the UVs (Pin, Smear)")
    lattice_columns: IntProperty(name="Columns", default=3, min=2, max=20,
                                 description="Lattice points across the selected UVs")
    lattice_rows: IntProperty(name="Rows", default=3, min=2, max=20, description="Lattice points up the selected UVs")
    lattice_falloff: FloatProperty(name="Falloff", default=1.0, min=0.0, max=1.0, precision=3,
                                   description="How far the UVs follow the lattice (1 = all the way)")
    lattice_bounding_rect: BoolProperty(name="Use bounding rectangle", default=True,
                                        description="Fit the lattice around the UVs; off: drag on empty space to draw "
                                                    "the lattice")
    lattice_move_manipulator: BoolProperty(name="Show move manipulator", default=True,
                                           description="A move handle on the lattice point last picked (U, V or free)")
    lattice_snap: EnumProperty(name="Placement", default='CENTER', items=(
        ('CORNER', "Snap corner", "With Pixel Snap on, dragged lattice points land on pixel corners"),
        ('CENTER', "Snap center", "With Pixel Snap on, dragged lattice points land on pixel centres")))


def settings(context):
    return context.scene.allset_uv_brush


def size_of(context, mode):
    prop = BRUSH_PROPS[mode][0]
    return getattr(settings(context), prop) if prop else 0.0


def strength_of(context, mode):
    """The brush strength as a 0-1 factor of one dab."""
    s = settings(context)
    if mode in {"UNFOLD", "OPTIMIZE"}:
        return s.relax_strength
    if mode == "SMEAR":
        return s.smear_strength * 10.0       # the default 0.05 pushes the UVs at the centre half the stroke
    if mode == "SMUDGE":
        return s.smudge_pressure
    if mode == "GRAB":
        return s.grab_strength / 100.0
    if mode == "PINCH":
        return s.pinch_strength / 100.0
    return 1.0


# --- the UV Editor's active tool -----------------------------------------------------------------------

def active_tool(context):
    try:
        tool = context.workspace.tools.from_space_image_mode('UV', create=False)
    except (AttributeError, TypeError, RuntimeError):
        return ""
    return tool.idname if tool is not None else ""


def active_mode(context):
    return MODE_OF_TOOL.get(active_tool(context))


def _uv_region(context):
    space = getattr(context, "space_data", None)
    region = context.region
    return (context.mode == 'EDIT_MESH' and space is not None and space.type == 'IMAGE_EDITOR'
            and space.mode == 'UV' and region is not None and region.type == 'WINDOW')


# --- one mesh's UVs as numpy arrays for a stroke ------------------------------------------------------

class MeshUVs:
    """The UV points (one per vertex and UV coordinate) of the faces the UV Editor shows, for one stroke."""

    def __init__(self, ob, synced):
        self.ob = ob
        self.bm = bm = bmesh.from_edit_mesh(ob.data)
        self.uv = uv = bm.loops.layers.uv.verify()
        bm.verts.index_update()
        bm.edges.index_update()
        self.faces = faces = [f for f in bm.faces if not f.hide and (synced or f.select)]
        keys, loops, U, P, pins, sel = {}, [], [], [], [], []
        mw = ob.matrix_world
        point_of = {}
        for f in faces:
            for l in f.loops:
                c = l[uv].uv
                k = (l.vert.index, round(c.x, 6), round(c.y, 6))
                i = keys.get(k)
                if i is None:
                    i = keys[k] = len(loops)
                    loops.append([])
                    U.append((c.x, c.y))
                    P.append(tuple(mw @ l.vert.co))
                    pins.append(False)
                    sel.append(False)
                loops[i].append(l)
                pins[i] = pins[i] or l[uv].pin_uv
                sel[i] = sel[i] or _loop_selected(l, uv, synced)
                point_of[l] = i
        self.loops = loops
        self.U = np.array(U, float).reshape(-1, 2)
        self.U0 = self.U.copy()
        self.P = np.array(P, float).reshape(-1, 3)
        self.pinned = np.array(pins, bool)
        self.selected = np.array(sel, bool)
        self.point_of = point_of
        shown = set(faces)
        tris = [[point_of[l] for l in tri] for tri in bm.calc_loop_triangles() if tri[0].face in shown]
        self.T = np.array(tris, int).reshape(-1, 3)
        self._edges = None

    def edges(self):
        """(a, b, edge index, kind) per UV edge: ``a`` / ``b`` the point indices; kind 0 = inside a shell, 1 = a shell
        border between two faces (listed once per side), 2 = an open edge (one face)."""
        if self._edges is None:
            seen = {}
            for f in self.faces:
                for l in f.loops:
                    a, b = self.point_of[l], self.point_of[l.link_loop_next]
                    seen.setdefault((min(a, b), max(a, b), l.edge.index), 0)
                    seen[(min(a, b), max(a, b), l.edge.index)] += 1
            per_edge = {}
            for (a, b, e), _n in seen.items():
                per_edge.setdefault(e, []).append((a, b))
            rows = []
            for e, pairs in per_edge.items():
                kind = 1 if len(pairs) > 1 else 2 if seen[(*pairs[0], e)] == 1 else 0
                for a, b in pairs:
                    rows.append((a, b, e, kind))
            self._edges = rows
        return self._edges

    def edge_arrays(self):
        """``edges()`` as numpy columns (a, b, edge, kind)."""
        if getattr(self, "_edge_arrays", None) is None:
            rows = self.edges()
            self._edge_arrays = {k: np.array([r[c] for r in rows], int).reshape(-1)
                                 for c, k in enumerate(("a", "b", "edge", "kind"))}
        return self._edge_arrays

    def segments(self, picked):
        """The UV segments of the ``picked`` edge indices (the stroke drawing)."""
        arr = self.edge_arrays()
        if not picked or not len(arr["edge"]):
            return []
        on = np.isin(arr["edge"], np.fromiter(picked, int))
        return [(tuple(self.U[a]), tuple(self.U[b])) for a, b in zip(arr["a"][on], arr["b"][on])]

    def write(self, U):
        """Set the UVs that changed; returns whether any did."""
        moved = np.nonzero(np.any(np.abs(U - self.U) > 1e-12, axis=1))[0]
        uv = self.uv
        for i in moved:
            u, v = float(U[i, 0]), float(U[i, 1])
            for l in self.loops[i]:
                l[uv].uv = (u, v)
        self.U = np.array(U, float)
        return len(moved) > 0

    def write_pins(self, pins):
        changed = np.nonzero(pins != self.pinned)[0]
        uv = self.uv
        for i in changed:
            for l in self.loops[i]:
                l[uv].pin_uv = bool(pins[i])
        self.pinned = np.array(pins, bool)
        return len(changed) > 0

    def restore(self):
        self.write(self.U0)


def stroke_meshes(context):
    synced = sync(context)
    return [MeshUVs(ob, synced) for ob in context.objects_in_mode_unique_data or () if ob.type == 'MESH']


FALLOFF_MODES = {"PIN", "SMEAR", "GRAB", "PINCH"}        # brushes with a Falloff Type (Surface/Volume, Surface, Volume), like Maya


def brush_distances(mesh, centre, r, kind):
    """uv_brush_math.brush_distances for ``mesh`` (a MeshUVs)."""
    if kind == "VOLUME":
        return uv_brush_math.brush_distances(mesh.U, centre, r)
    arr = mesh.edge_arrays()
    return uv_brush_math.brush_distances(mesh.U, centre, r, kind, mesh.T, arr["a"], arr["b"])


def apply_dab(mode, mesh, centre, r, strength, *, invert=False, delta=(0.0, 0.0), surfangle=1.0, weights=None,
              held=None, falloff="VOLUME"):
    """One dab of ``mode`` on ``mesh`` (a MeshUVs) at UV ``centre`` with radius ``r``; returns whether anything
    changed. ``held`` = the UVs that must stay (the pinned UVs when None); ``falloff`` = the Falloff Type of the Pin
    and Smear brushes. Cut / Sew only collect edges."""
    if held is None:
        held = mesh.pinned
    dist = brush_distances(mesh, centre, r, falloff) if mode in FALLOFF_MODES else None
    if mode == "PIN_SMOOTH":
        inside = np.isfinite(brush_distances(mesh, centre, r, falloff))
        arr = mesh.edge_arrays()
        return mesh.write_pins(uv_brush_math.smooth_pins(mesh.pinned, arr["a"], arr["b"], inside))
    if mode == "PIN":
        return mesh.write_pins(uv_brush_math.pin(mesh.pinned, mesh.U, centre, r, on=not invert, dist=dist))
    if mode in {"UNFOLD", "OPTIMIZE"}:
        return mesh.write(uv_brush_math.relax(mesh.P, mesh.U, mesh.T, centre, r, strength, mode, surfangle,
                                              held=held))
    if mode == "SMEAR":
        return mesh.write(uv_brush_math.smear(mesh.U, centre, r, delta, strength, held=held, dist=dist))
    if mode == "PINCH":
        return mesh.write(uv_brush_math.pinch(mesh.U, centre, r, strength, dist=dist, held=held, invert=invert))
    if mode == "SMUDGE" and weights is not None:
        return mesh.write(mesh.U + weights[:, None] * np.asarray(delta, float)[None, :])
    return False


def relax_held(meshes):
    """Per mesh, the UVs an Unfold / Optimize stroke keeps still: the pinned ones and, when any UV is selected, every
    unselected one (with nothing selected the brush works on all UVs), like Maya."""
    any_selected = any(m.selected.any() for m in meshes)
    return [m.pinned | ~m.selected if any_selected else m.pinned.copy() for m in meshes]


def collect_sew_edges(mesh, p, r, picked):
    """Sew stroke point ``p``: adds the shell border edges the brush of radius ``r`` touches to the set ``picked``."""
    if not mesh.edges():
        return
    arr = mesh.edge_arrays()
    a, b = mesh.U[arr["a"]], mesh.U[arr["b"]]
    hit = uv_brush_math.sew_pick(p, a, b, r) & (arr["kind"] == 1)       # only borders between two shells sew
    picked.update(int(e) for e in arr["edge"][hit])


def cut_pick(mesh):
    """A CutPick over the edges inside the shells of ``mesh`` (a shell border is already cut)."""
    arr = mesh.edge_arrays()
    inner = arr["kind"] == 0
    pick = uv_brush_math.CutPick(mesh.U[arr["a"][inner]], mesh.U[arr["b"][inner]])
    pick.edge = arr["edge"][inner]
    return pick


def cut_edges(pick, sensitivity, length):
    """The edge indices a Cut stroke of ``length`` takes."""
    return {int(e) for e in pick.edge[pick.picked(sensitivity, length)]}


def open_cut(bm, uv, edges, ratio):
    """The Cut brush on release: ``edges`` become UV cuts, and at each vertex of the cut the UVs on either side move
    apart, away from the cut, by half of ``ratio`` times the cut edges' mean UV length there (Cut Open Ratio; 0 = they
    stay on each other). The ends of a cut inside a shell stay joined. Returns the number of edges cut."""
    for e in edges:
        e.seam = True
    cut = set(edges)
    verts = {v for e in edges for v in e.verts}
    moves = []                          # (loops, new UV): worked out on the UVs before any of them moves
    for v in verts:
        loops = [l for l in v.link_loops if not l.face.hide]
        if len(loops) < 2:
            continue
        parent = list(range(len(loops)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        at = {l.face: i for i, l in enumerate(loops)}
        for e in v.link_edges:
            if e in cut or e.seam:
                continue
            fs = [f for f in e.link_faces if f in at]
            if len(fs) == 2:
                a, b = loops[at[fs[0]]], loops[at[fs[1]]]
                if (a[uv].uv - b[uv].uv).length < 1e-6:
                    parent[find(at[fs[0]])] = find(at[fs[1]])
        fans = {}
        for i, l in enumerate(loops):
            fans.setdefault(find(i), []).append(l)
        if len(fans) < 2 or ratio <= 0.0:
            continue
        lengths = [_edge_uv_length(e, uv) for e in v.link_edges if e in cut]
        along = sum((_edge_uv_dir(e, v, uv) for e in v.link_edges if e in cut), loops[0][uv].uv * 0.0)
        step = 0.5 * ratio * (sum(lengths) / len(lengths)) if lengths else 0.0
        for fan in fans.values():
            here = fan[0][uv].uv.copy()
            if any((l[uv].uv - here).length > 1e-6 for l in fan):
                continue
            centre = sum((_face_uv_centre(l.face, uv) for l in fan), here * 0.0) / len(fan)
            d = centre - here
            if along.length > 1e-12:            # straight off the cut line, not along it
                t = along.normalized()
                d = d - t * d.dot(t)
            if d.length < 1e-12:
                continue
            moves.append((fan, here + d.normalized() * step))
    for fan, new in moves:
        for l in fan:
            l[uv].uv = new
    return len(edges)


def _edge_uv_length(e, uv):
    l = next((l for l in e.link_loops if not l.face.hide), None)
    if l is None:
        return 0.0
    return (l[uv].uv - l.link_loop_next[uv].uv).length


def _edge_uv_dir(e, v, uv):
    """The UV direction of cut edge ``e`` through vertex ``v``, pointing the same way for both edges of a straight
    cut (U up, or V up for an edge along V)."""
    l = next((l for l in e.link_loops if not l.face.hide), None)
    if l is None:
        return Vector((0.0, 0.0))
    d = l.link_loop_next[uv].uv - l[uv].uv
    if d.length < 1e-12:
        return Vector((0.0, 0.0))
    d = d.normalized()
    return -d if d.x < -1e-6 or (abs(d.x) <= 1e-6 and d.y < 0.0) else d


def _face_uv_centre(f, uv):
    c = f.loops[0][uv].uv * 0.0
    for l in f.loops:
        c = c + l[uv].uv
    return c / len(f.loops)


def finish_edges(mode, mesh, picked, ratio=0.1):
    """Cut / sew the collected edges of ``mesh`` (``ratio`` = Cut Open Ratio); returns how many changed."""
    if not picked:
        return 0
    bm = mesh.bm
    bm.edges.ensure_lookup_table()
    edges = [bm.edges[i] for i in sorted(picked) if i < len(bm.edges)]
    if mode == "CUT":
        return open_cut(bm, mesh.uv, edges, ratio)
    return uv_tools.sew(bm, mesh.uv, edges, move=True)


# --- drawing: the brush circle and the Cut / Sew stroke ------------------------------------------------

_hover = {"area": 0, "pos": None, "lock": False}
_modes = {"current": None, "last": None}     # the brush tool in use and the one before it (Last Tool)
_stroke = {"area": 0, "segments": [], "lazy": None}   # a Cut / Sew stroke: collected edges' UV segments; Steady
# Stroke: (area, the mouse UV) while the stroke point trails it
_borders = {"area": 0, "segments": [], "t": 0.0}      # Display All Shell Borders: UV segments of the shell borders
_handle = []
_border_handle = []


def _circle(cx, cy, rad):
    return [(cx + rad * math.cos(2 * math.pi * k / CIRCLE_SEGMENTS),
             cy + rad * math.sin(2 * math.pi * k / CIRCLE_SEGMENTS)) for k in range(CIRCLE_SEGMENTS)]


def _draw():
    context = bpy.context
    area, region = context.area, context.region
    try:
        if area is None or not _uv_region(context):
            return
        mode = active_mode(context)
        if mode != "SYMMETRIZE":
            uv_symmetrize.clear()           # the picked symmetry line lasts while the tool stays active
        if mode is None:
            return
        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        shader.uniform_float("viewportSize", (region.width, region.height))
        scale = context.preferences.system.ui_scale or 1.0
        gpu.state.blend_set('ALPHA')
        v2d = region.view2d
        lazy = _stroke.get("lazy")
        if lazy is not None and lazy[0] == area.as_pointer() and _hover["pos"] is not None:
            shader.uniform_float("lineWidth", 1.0 * scale)
            shader.uniform_float("color", (*CIRCLE_RGB, 0.7))
            batch_for_shader(shader, 'LINES', {"pos": [_hover["pos"], v2d.view_to_region(*lazy[1], clip=False)]}
                             ).draw(shader)
        sym = uv_symmetrize.segments() if mode == "SYMMETRIZE" else []
        if sym:
            pts = [v2d.view_to_region(u, v, clip=False) for seg in sym for (u, v) in seg]
            shader.uniform_float("lineWidth", 3.0 * scale)
            shader.uniform_float("color", (*STROKE_RGB, 1.0))
            batch_for_shader(shader, 'LINES', {"pos": pts}).draw(shader)
        if _stroke["area"] == area.as_pointer() and _stroke["segments"]:
            pts = [v2d.view_to_region(u, v, clip=False) for seg in _stroke["segments"] for (u, v) in seg]
            shader.uniform_float("lineWidth", 3.0 * scale)
            shader.uniform_float("color", (*STROKE_RGB, 1.0))
            batch_for_shader(shader, 'LINES', {"pos": pts}).draw(shader)
        pos = _hover["pos"]
        r = size_of(context, mode)
        if pos is not None and _hover["area"] == area.as_pointer() and r > 0:
            u, v = v2d.region_to_view(*pos)
            x1 = v2d.view_to_region(u + r, v, clip=False)[0]
            rad = abs(x1 - pos[0])
            shader.uniform_float("lineWidth", 1.5 * scale)
            shader.uniform_float("color", (*CIRCLE_RGB, 0.9))
            compat.closed_line_batch(shader, _circle(pos[0], pos[1], rad)).draw(shader)
        gpu.state.blend_set('NONE')
    except (ReferenceError, AttributeError):
        pass


def _draw_borders():
    """Display All Shell Borders (Cut / Sew tools). Its own draw handler, added on first use so it draws over the
    kit's UV Editor colours (ui/uv_display.py)."""
    context = bpy.context
    area, region = context.area, context.region
    try:
        if area is None or not _uv_region(context) or active_mode(context) not in {"CUT", "SEW"}:
            return
        if not settings(context).show_shell_borders or _borders["area"] != area.as_pointer() \
                or not _borders["segments"]:
            return
        v2d = region.view2d
        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        shader.uniform_float("viewportSize", (region.width, region.height))
        shader.uniform_float("lineWidth", 2.5 * (context.preferences.system.ui_scale or 1.0))
        shader.uniform_float("color", (*BORDER_RGB, 1.0))
        gpu.state.blend_set('ALPHA')
        pts = [v2d.view_to_region(u, v, clip=False) for seg in _borders["segments"] for (u, v) in seg]
        batch_for_shader(shader, 'LINES', {"pos": pts}).draw(shader)
        gpu.state.blend_set('NONE')
    except (ReferenceError, AttributeError):
        pass


def shell_border_segments(meshes):
    """UV segments of every shell border and open edge of ``meshes`` (MeshUVs)."""
    out = []
    for m in meshes:
        arr = m.edge_arrays()
        if not len(arr["kind"]):
            continue
        on = arr["kind"] > 0
        out += [(tuple(m.U[a]), tuple(m.U[b])) for a, b in zip(arr["a"][on], arr["b"][on])]
    return out


def refresh_borders(context, force=False):
    import time
    now = time.monotonic()
    area = context.area.as_pointer()
    if not force and _borders["area"] == area and now - _borders["t"] < BORDER_CHECK_S:
        return
    _borders.update(area=area, t=now, segments=shell_border_segments(stroke_meshes(context)))
    if not _border_handle:
        _border_handle.append(bpy.types.SpaceImageEditor.draw_handler_add(_draw_borders, (), 'WINDOW', 'POST_PIXEL'))


def _redraw(context):
    if context.area is not None:
        context.area.tag_redraw()


# --- operators ---------------------------------------------------------------------------------------

class ALLSET_OT_uv_brush_hover(bpy.types.Operator):
    """The brush circle follows the mouse (UV Editor brush tools)"""
    bl_idname = "allset.uv_brush_hover"
    bl_label = "UV Brush Hover"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        mode = active_mode(context)
        note_mode(mode)
        if mode in {"CUT", "SEW"} and settings(context).show_shell_borders and context.area is not None:
            refresh_borders(context)
        if not _hover["lock"] and context.area is not None:
            _hover["area"] = context.area.as_pointer()
            _hover["pos"] = (event.mouse_region_x, event.mouse_region_y)
            context.area.tag_redraw()
        return {'PASS_THROUGH'}


class ALLSET_OT_uv_brush_stroke(bpy.types.Operator):
    """Drag to apply the UV brush under the circle (Maya UV Editor brush tools)"""
    bl_idname = "allset.uv_brush_stroke"
    bl_label = "UV Brush Stroke"
    bl_options = {'UNDO', 'INTERNAL'}

    mode: EnumProperty(name="Mode", items=[(m, m.title(), "") for m in MODES], options={'SKIP_SAVE'})
    invert: BoolProperty(name="Invert", default=False, options={'SKIP_SAVE'},
                         description="Ctrl: Pin unpins, Sew cuts; the Cut tool does nothing with Ctrl or Shift")
    smooth: BoolProperty(name="Smooth", default=False, options={'SKIP_SAVE'},
                         description="Shift: the Pin tool smooths the pins")
    middle: BoolProperty(name="Middle Mouse", default=False, options={'SKIP_SAVE'},
                         description="Started with the middle mouse (Smudge with Middle mouse initiates)")

    @classmethod
    def poll(cls, context):
        return _uv_region(context)

    def _mode(self):
        if self.invert and self.mode == "SEW":
            return "CUT"
        return self.mode

    def invoke(self, context, event):
        smudge_middle = self.mode == "SMUDGE" and settings(context).smudge_middle
        if self.middle and not smudge_middle:
            return {'PASS_THROUGH'}         # the middle mouse smudges only with Middle mouse initiates
        self._meshes = stroke_meshes(context)
        if not self._meshes:
            return {'CANCELLED'}
        note_mode(self.mode)
        self._button = 'MIDDLEMOUSE' if self.middle else 'LEFTMOUSE'
        self._area = context.area.as_pointer()
        self._xy = (event.mouse_region_x, event.mouse_region_y)
        self._uv = context.region.view2d.region_to_view(*self._xy)
        self._picked = [set() for _ in self._meshes]
        self._changed = False
        self._moves = 0
        self._carry = 0.0
        # Ctrl / Shift + drag with the Cut tool; a left drag with Smudge's Middle mouse initiates on: nothing
        self._idle = ((self.mode in {"CUT", "SYMMETRIZE"} and self.invert)      # Ctrl+click does nothing
                      or (smudge_middle and not self.middle))
        mode = self._mode()
        s = settings(context)
        self._held = relax_held(self._meshes) if mode in {"UNFOLD", "OPTIMIZE"} else [m.pinned for m in self._meshes]
        self._weights = None
        self._cut = self._picks = None
        if self._idle:
            pass
        elif mode == "SMUDGE" and s.smudge_effect == 'FIXED':
            self._weights = [uv_brush_math.grab_weights(m.U, self._uv, s.smudge_size, held=m.pinned, only=m.selected,
                                                        kind=s.smudge_falloff) for m in self._meshes]
        elif mode == "GRAB":
            r = size_of(context, mode)
            k = strength_of(context, mode)
            self._grab = [(m.U.copy(), uv_brush_math.sculpt_weights(
                m.U, self._uv, r, brush_distances(m, self._uv, r, s.falloff_type), m.pinned) * k)
                for m in self._meshes]
            self._grab_from = self._uv
        elif mode == "CUT":
            self._cut = uv_brush_math.CutStroke(self._uv)
            self._picks = [cut_pick(m) for m in self._meshes]
        elif mode == "SYMMETRIZE":
            self._sym = [uv_symmetrize.Mirror(m, e) if e is not None else None
                         for m, e in ((m, uv_symmetrize.seam_of(m)) for m in self._meshes)]
            if not any(x is not None and x.ok for x in self._sym):
                return self._sym_pick(context)              # no symmetry line yet: this click picks it
            self._dab(context, self._uv, (0.0, 0.0))        # a click paints too
        elif mode in {"PIN", "SEW"}:
            self._dab(context, self._uv, (0.0, 0.0))        # a click pins / picks under the brush
        self._show()
        _hover["area"], _hover["pos"] = self._area, self._xy
        context.window_manager.modal_handler_add(self)
        _redraw(context)
        return {'RUNNING_MODAL'}

    def _sym_pick(self, context):
        """Pick the UV edge nearest the click (within SYM_PICK_PX) as the symmetry line; the Mirror Axis follows it."""
        v2d = context.region.view2d
        x, y = self._xy
        tol = abs(v2d.region_to_view(x + SYM_PICK_PX * (context.preferences.system.ui_scale or 1.0), y)[0]
                  - self._uv[0])
        best = None
        for m in self._meshes:
            hit = uv_symmetrize.nearest_edge(m, self._uv)
            if hit is not None and hit[0] <= tol and (best is None or hit[0] < best[0][0]):
                best = (hit, m)
        if best is None:
            results.result(self, "Click a UV edge on the symmetry line")
            return {'CANCELLED'}
        (_d, edge, direction), m = best
        mirror = uv_symmetrize.Mirror(m, edge)
        if not mirror.ok:
            results.result(self, "The mesh is not symmetrical about this edge")
            return {'CANCELLED'}
        uv_symmetrize.remember(m, edge, mirror)
        settings(context).sym_axis = uv_symmetrize.axis_of(direction)
        _redraw(context)
        return {'CANCELLED'}           # the pick changes no UV: no undo step

    def _dab(self, context, p, delta):
        mode = self._mode()
        s = settings(context)
        r = size_of(context, mode)
        k = strength_of(context, mode)
        for i, m in enumerate(self._meshes):
            if mode == "SYMMETRIZE":
                mir = self._sym[i]
                if mir is not None and mir.ok:
                    self._changed |= m.write(uv_symmetrize.dab(m.U, mir.side, mir.other, mir.shell, p, r, s.sym_axis,
                                                               s.sym_axis_pos, s.sym_flood))
                continue
            if mode == "SEW":
                collect_sew_edges(m, p, r, self._picked[i])
            else:
                w = None if self._weights is None else self._weights[i]
                if mode == "PIN" and (self.smooth or s.pin_method == 'SMOOTH'):
                    self._changed |= apply_dab("PIN_SMOOTH", m, p, r, k, falloff=s.falloff_type)
                    continue
                self._changed |= apply_dab(mode, m, p, r, k, invert=self.invert, delta=delta,
                                           surfangle=s.surfangle, weights=w, held=self._held[i],
                                           falloff=s.falloff_type)

    def _cut_picked(self, context):
        sens = settings(context).cut_sensitivity
        return [cut_edges(pk, sens, self._cut.length) for pk in self._picks]

    def _show(self, context=None):
        """After one mouse move: the collected Cut / Sew edges, or the moved UVs, on screen."""
        mode = self._mode()
        if self._cut is not None and context is not None:
            self._picked = self._cut_picked(context)
        if mode in {"CUT", "SEW"}:
            _stroke["area"] = self._area
            _stroke["segments"] = [seg for m, p in zip(self._meshes, self._picked) for seg in m.segments(p)]
        elif self._changed:
            for m in self._meshes:
                bmesh.update_edit_mesh(m.ob.data, loop_triangles=False, destructive=False)

    def _move(self, context, prev, uv):
        mode = self._mode()
        s = settings(context)
        r = size_of(context, mode)
        delta = (uv[0] - prev[0], uv[1] - prev[1])
        if mode == "CUT":
            self._cut.add(uv)
            for pk in self._picks:
                pk.update(*self._cut.take())
        elif mode in {"UNFOLD", "OPTIMIZE"}:
            pts, self._carry = uv_brush_math.spaced_points(prev, uv, max(r * SPACING, 1e-4), self._carry)
            for p in pts:              # dabs a quarter radius apart: a click or a tiny drag relaxes nothing
                self._dab(context, p, (0.0, 0.0))
        elif mode == "SMUDGE" and s.smudge_effect == 'FIXED':
            self._dab(context, uv, delta)
        elif mode == "SMUDGE":
            for m in self._meshes:          # each mouse move pulls the selected UVs under the brush by the Pressure
                self._changed |= m.write(uv_brush_math.smudge(m.U, prev, r, delta, s.smudge_pressure, held=m.pinned,
                                                              only=m.selected, kind=s.smudge_falloff))
        elif mode == "GRAB":
            du, dv = uv[0] - self._grab_from[0], uv[1] - self._grab_from[1]
            if s.grab_direction == 'U':
                dv = 0.0
            elif s.grab_direction == 'V':
                du = 0.0
            twist = 0.0
            if self.invert and s.grab_twist:       # Ctrl with Twist: turn, a brush radius sideways = a quarter turn
                twist = -(uv[0] - self._grab_from[0]) / max(r, 1e-9) * (math.pi / 2)
            for m, (U0, w) in zip(self._meshes, self._grab):
                self._changed |= m.write(uv_brush_math.grab(U0, w, self._grab_from, (du, dv), twist))
        elif mode == "SMEAR" and self._moves == 1:
            pass                         # the first mouse move after the press only places the brush, like Maya
        else:
            last = prev
            for p in uv_brush_math.stroke_points(prev, uv, max(r * SPACING, 1e-4)):
                self._dab(context, p, (p[0] - last[0], p[1] - last[1]))
                last = p

    def modal(self, context, event):
        if event.type == 'ESC' and event.value == 'PRESS':
            for m in self._meshes:
                m.restore()
                bmesh.update_edit_mesh(m.ob.data, loop_triangles=False, destructive=False)
            _stroke["segments"] = []
            _stroke["lazy"] = None
            _redraw(context)
            return {'CANCELLED'}
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            region = context.region
            xy = (event.mouse_x - region.x, event.mouse_y - region.y) if region is not None else self._xy
            uv = region.view2d.region_to_view(*xy) if region is not None else self._uv
            uv = self._steady(context, uv)
            self._moves += 1
            if not self._idle:
                self._move(context, self._uv, uv)
                self._show(context)
            self._uv, self._xy = uv, xy
            if _stroke.get("lazy") is not None:      # the circle stays on the stroke point, a line to the mouse
                xy = (int(round(region.view2d.view_to_region(*uv, clip=False)[0])),
                      int(round(region.view2d.view_to_region(*uv, clip=False)[1])))
            _hover["area"], _hover["pos"] = self._area, xy
            _redraw(context)
            return {'RUNNING_MODAL'}
        if event.type == self._button and event.value == 'RELEASE':
            return self._finish(context)
        return {'RUNNING_MODAL'}

    def _steady(self, context, uv):
        """Cut / Sew with Steady Stroke: the stroke point follows the mouse only when it is farther than the Distance,
        staying that far behind it."""
        s = settings(context)
        if self._mode() not in {"CUT", "SEW"} or not s.cut_steady:
            _stroke["lazy"] = None
            return uv
        dx, dy = uv[0] - self._uv[0], uv[1] - self._uv[1]
        ln = math.hypot(dx, dy)
        dist = s.cut_steady_distance
        _stroke["lazy"] = (self._area, uv)
        if ln <= dist:
            return self._uv
        k = (ln - dist) / ln
        return (self._uv[0] + dx * k, self._uv[1] + dy * k)

    def _finish(self, context):
        mode = self._mode()
        _stroke["segments"] = []
        _stroke["lazy"] = None
        done = 0
        if self._idle:
            pass
        elif mode in {"CUT", "SEW"}:
            if self._cut is not None:
                for pk in self._picks:
                    pk.update(*self._cut.take(final=True))
                self._picked = self._cut_picked(context)
            for m, picked in zip(self._meshes, self._picked):
                n = finish_edges(mode, m, picked, settings(context).cut_open_ratio)
                done += n
                if n:
                    bmesh.update_edit_mesh(m.ob.data)
            if not done and mode == "SEW" and any(self._picked):
                results.result(self, "No UV shells to sew along these edges")
        else:
            done = self._changed
            for m in self._meshes:
                bmesh.update_edit_mesh(m.ob.data)
            if mode == "SYMMETRIZE" and not self._idle:
                for m, mir in zip(self._meshes, self._sym):
                    if mir is not None and mir.ok:
                        uv_symmetrize.refresh_segments(m, mir)
        _redraw(context)
        return {'FINISHED'} if done else {'CANCELLED'}


class ALLSET_OT_uv_invert_pin(bpy.types.Operator):
    """Pin the unpinned UVs and unpin the pinned ones (Maya Invert Pin)"""
    bl_idname = "allset.uv_invert_pin"
    bl_label = "Invert Pin"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        for m in stroke_meshes(context):
            m.write_pins(~m.pinned)
            bmesh.update_edit_mesh(m.ob.data)
        return {'FINISHED'}


LABELS = {"UNFOLD": "Unfold", "OPTIMIZE": "Optimize", "CUT": "Cut", "SEW": "Sew", "PIN": "Pin", "SMEAR": "Smear",
          "SMUDGE": "Smudge", "GRAB": "Grab", "PINCH": "Pinch"}


def note_mode(mode):
    """A brush tool is in use: the one used before it becomes the Last Tool (like Maya, only a change of brush counts;
    other tools in between leave it)."""
    if mode is not None and mode != _modes["current"]:
        _modes["last"], _modes["current"] = _modes["current"], mode


def last_mode(context):
    """The brush tool used before the active one."""
    note_mode(active_mode(context))
    return _modes["last"]


def last_tool_label(context):
    """The brush marking menu's east item: "Last Tool: <tool>" like Maya ("Last Tool:" before a second brush)."""
    from ..i18n import iface
    mode = last_mode(context)
    head = iface("Last Tool")
    return f"{head}: {iface(LABELS[mode])}" if mode in LABELS else f"{head}:"


class ALLSET_OT_uv_brush_last(bpy.types.Operator):
    """Go back to the UV brush tool used before this one (Maya's Last Tool in the brush marking menu)"""
    bl_idname = "allset.uv_brush_last"
    bl_label = "Last Tool"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        mode = last_mode(context)
        if mode is None:
            self.report({'WARNING'}, "No other UV brush tool used yet")
            return {'CANCELLED'}
        bpy.ops.wm.tool_set_by_id(name=TOOL_IDS[mode], space_type='IMAGE_EDITOR')
        return {'FINISHED'}


# --- B / M + drag: brush size and strength -----------------------------------------------------------

def _header(context, text):
    area = live_refs.area(_hover["area"]) if _hover["area"] else None
    if area is not None:
        area.header_text_set(text)
        area.tag_redraw()


class _BrushDrag(taphold.TapHoldBinding):
    prop_index = 0

    def _prop(self, context):
        mode = active_mode(context)
        return None if mode is None else BRUSH_PROPS[mode][self.prop_index]

    def click(self, context, event):
        self._name = self._prop(context)
        if self._name is None:
            return None
        s = settings(context)
        self._start = getattr(s, self._name)
        _hover["lock"] = True
        self._show(context)
        return 'DRAG'

    def drag_end(self, context):
        _hover["lock"] = False
        _header(context, None)

    def drag_cancel(self, context):
        setattr(settings(context), self._name, self._start)
        self.drag_end(context)

    def _show(self, context):
        s = settings(context)
        label = s.bl_rna.properties[self._name].name
        _header(context, f"{label}: {getattr(s, self._name):.3f}  (Esc cancel)")


class UVBrushSizeBinding(_BrushDrag):
    """B + LMB drag left / right: the UV brush size (Maya)."""
    name = "uv_brush_size"
    label = "UV Brush Size"
    prop_index = 0

    def drag(self, context, event, start):
        s = settings(context)
        hard = s.bl_rna.properties[self._name].hard_max
        setattr(s, self._name, min(hard, taphold.radius_from_drag(max(self._start, 1e-3), event.mouse_x - start[0])))
        self._show(context)


class UVBrushStrengthBinding(_BrushDrag):
    """M + LMB drag up / down: the UV brush strength (Maya)."""
    name = "uv_brush_strength"
    label = "UV Brush Strength"
    prop_index = 1

    def drag(self, context, event, start):
        s = settings(context)
        p = s.bl_rna.properties[self._name]
        span = p.soft_max - p.soft_min
        value = self._start + (event.mouse_y - start[1]) / 200.0 * span
        setattr(s, self._name, min(p.hard_max, max(p.hard_min, value)))
        self._show(context)


# --- MMB drag: brush size (left / right) and strength (up / down) ------------------------------------------

MMB_SIZE_MIN = {"UNFOLD": 0.0, "OPTIMIZE": 0.0}      # other brushes keep at least MMB_MIN
MMB_MIN = 0.01
MMB_STRENGTH = {"PIN", "SMEAR", "GRAB", "PINCH"}        # brushes whose strength (0-100) follows an up / down MMB drag
MMB_AXIS_PX = 3                        # the drag picks its direction after this many pixels


def mmb_value(mode, axis, start, du):
    """The brush size (``axis`` 'X') or strength ('Y') after an MMB drag of ``du`` UV units (right / up = more):
    the size grows by the drag in UV units, the strength by a hundred times it (its 0-100 scale)."""
    if axis == 'X':
        return max(MMB_SIZE_MIN.get(mode, MMB_MIN), start + du)
    return max(MMB_MIN, start + du * 100.0)


class ALLSET_OT_uv_brush_mmb(bpy.types.Operator):
    """Middle-mouse drag left / right: brush size; up / down: strength (UV Editor brush tools, like Maya)"""
    bl_idname = "allset.uv_brush_mmb"
    bl_label = "UV Brush Size / Strength"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _uv_region(context)

    def invoke(self, context, event):
        mode = active_mode(context)
        if mode is None or BRUSH_PROPS[mode][0] is None or mode in {"CUT", "SEW", "SMUDGE"}:
            return {'PASS_THROUGH'}         # Maya's Cut / Sew / Smudge tools: the middle mouse changes nothing
        self._mode = mode
        self._xy = (event.mouse_region_x, event.mouse_region_y)
        self._axis = None
        self._prop = None
        self._start = None
        _hover["area"], _hover["pos"], _hover["lock"] = context.area.as_pointer(), self._xy, True
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _pick_axis(self, dx, dy):
        if max(abs(dx), abs(dy)) < MMB_AXIS_PX:
            return None
        if abs(dx) >= abs(dy):
            return 'X'
        return 'Y' if self._mode in MMB_STRENGTH else ''

    def _end(self, context):
        _hover["lock"] = False
        _header(context, None)

    def modal(self, context, event):
        s = settings(context)
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            if self._prop:
                setattr(s, self._prop, self._start)
            self._end(context)
            return {'CANCELLED'}
        if event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
            self._end(context)
            return {'FINISHED'}
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'} and context.region is not None:
            region = context.region
            xy = (event.mouse_x - region.x, event.mouse_y - region.y)
            dx, dy = xy[0] - self._xy[0], xy[1] - self._xy[1]
            if self._axis is None:
                self._axis = self._pick_axis(dx, dy)
                if self._axis:
                    self._prop = BRUSH_PROPS[self._mode][0 if self._axis == 'X' else 1]
                    self._start = getattr(s, self._prop)
            if self._prop:
                v2d = region.view2d
                a = v2d.region_to_view(*self._xy)
                b = v2d.region_to_view(*xy)
                du = b[0] - a[0] if self._axis == 'X' else b[1] - a[1]
                hard = s.bl_rna.properties[self._prop].hard_max
                setattr(s, self._prop, min(hard, mmb_value(self._mode, self._axis, self._start, du)))
                label = s.bl_rna.properties[self._prop].name
                _header(context, f"{label}: {getattr(s, self._prop):.3f}  (Esc cancel)")
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}


BINDINGS = (UVBrushSizeBinding, UVBrushStrengthBinding)
classes = (ALLSET_PG_uv_brush, ALLSET_OT_uv_brush_hover, ALLSET_OT_uv_brush_stroke, ALLSET_OT_uv_invert_pin,
           ALLSET_OT_uv_brush_last, ALLSET_OT_uv_brush_mmb)


def register_extra():
    bpy.types.Scene.allset_uv_brush = PointerProperty(type=ALLSET_PG_uv_brush)
    for cls in BINDINGS:
        taphold.register_binding(cls())
    if not _handle:
        _handle.append(bpy.types.SpaceImageEditor.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL'))


def unregister_extra():
    while _handle:
        bpy.types.SpaceImageEditor.draw_handler_remove(_handle.pop(), 'WINDOW')
    while _border_handle:
        bpy.types.SpaceImageEditor.draw_handler_remove(_border_handle.pop(), 'WINDOW')
    for cls in BINDINGS:
        taphold.unregister_binding(cls.name)
    if hasattr(bpy.types.Scene, "allset_uv_brush"):
        del bpy.types.Scene.allset_uv_brush
    _hover.update(area=0, pos=None, lock=False)
    _stroke["segments"] = []
    _stroke["lazy"] = None
    _borders.update(area=0, segments=[], t=0.0)
    _modes.update(current=None, last=None)
