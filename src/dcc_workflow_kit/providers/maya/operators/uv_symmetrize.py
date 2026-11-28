# SPDX-License-Identifier: GPL-3.0-or-later
"""UV Editor > Tools > Symmetrize (the SYMMETRIZE mode of operators/uv_brush.py), like Maya's Symmetrize UV tool.

The first click picks a UV edge on the mesh's symmetry line (``pick_edge``): the mesh is walked face by face from both
sides of it (poly_symmetrize.topo_mirror) and the Mirror Axis follows the edge (an up-down edge = U). After the pick
every dab (``dab``) gives the UVs under the brush, on the brush's side of the Axis Position line, the UV of their
counterpart on the other side mirrored across that line; UVs of the symmetry line itself move onto it. With Flood Shells
a shell the brush touches is done on that whole side. The picked edge stays until the tool is left.
"""

import numpy as np

from . import poly_symmetrize

ON_LINE = -1        # a point of the symmetry line
OUTSIDE = -2        # a point the walk didn't reach (another part, a hidden face)

_seam = {}          # object name -> {"edge": edge index, "sig": (verts, edges, faces), "segments": UV segments}


def clear():
    _seam.clear()


def signature(bm):
    return (len(bm.verts), len(bm.edges), len(bm.faces))


def seam_of(mesh):
    """The picked edge index of ``mesh`` (a uv_brush.MeshUVs) or None."""
    s = _seam.get(mesh.ob.name)
    if s is None or s["sig"] != signature(mesh.bm):
        return None
    return s["edge"]


def segments():
    return [seg for s in _seam.values() for seg in s["segments"]]


def nearest_edge(mesh, uv):
    """(distance, edge index, UV direction) of the UV edge of ``mesh`` nearest to UV point ``uv``, or None."""
    arr = mesh.edge_arrays()
    if not len(arr["a"]):
        return None
    p = np.asarray(uv, float)
    A, B = mesh.U[arr["a"]], mesh.U[arr["b"]]
    d = B - A
    t = np.clip(((p - A) * d).sum(1) / np.maximum((d * d).sum(1), 1e-18), 0.0, 1.0)
    dist = np.hypot(*(A + d * t[:, None] - p).T)
    k = int(np.argmin(dist))
    return float(dist[k]), int(arr["edge"][k]), (float(d[k, 0]), float(d[k, 1]))


def axis_of(direction):
    """The Mirror Axis an edge with this UV direction sets: an up-down edge mirrors U, a side-to-side one V."""
    du, dv = abs(direction[0]), abs(direction[1])
    return 'U' if du <= dv else 'V'


class Mirror:
    """Per UV point of a MeshUVs: its side of the symmetry line (0 / 1, ON_LINE, OUTSIDE), its counterpart point and
    its shell."""

    def __init__(self, mesh, edge_index):
        bm = mesh.bm
        bm.edges.ensure_lookup_table()
        self.ok = False
        if not 0 <= edge_index < len(bm.edges):
            return
        faces = {}
        res = poly_symmetrize.topo_mirror(bm, bm.edges[edge_index], faces)
        if res is None:
            return
        m, side_of = res
        n = len(mesh.U)
        self.side = np.full(n, OUTSIDE, int)
        self.other = np.full(n, -1, int)
        for i, loops in enumerate(mesh.loops):
            for lp in loops:
                v = lp.vert
                w = m.get(v)
                if w is None:
                    continue
                if w is v:
                    self.side[i] = ON_LINE
                    break
                g = faces.get(lp.face)
                if g is None:
                    continue
                j = next((mesh.point_of.get(x) for x in g.loops if x.vert is w), None)
                if j is None:
                    continue
                self.side[i], self.other[i] = side_of[v], j
                break
        line = {e.index for e in bm.edges if m.get(e.verts[0]) is e.verts[0] and m.get(e.verts[1]) is e.verts[1]}
        self.line_edges = line
        self.shell = shells(mesh)
        self.ok = True


def low_side(side, coord):
    """The side (0 / 1) whose UVs lie lower along ``coord`` (the U or V column): the side a brush centre on or below
    the line paints."""
    m0 = coord[side == 0]
    m1 = coord[side == 1]
    if not len(m0) or not len(m1):
        return 0 if len(m0) else 1
    return 0 if m0.mean() <= m1.mean() else 1


def shells(mesh):
    """Shell id per UV point (points joined by the UV edges of a face share a shell)."""
    arr = mesh.edge_arrays()
    n = len(mesh.U)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in zip(arr["a"], arr["b"]):
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[ra] = rb
    return np.array([find(i) for i in range(n)], int)


def dab(U, side, other, shell, centre, r, axis, pos, flood=False):
    """New UVs after one Symmetrize dab: ``U`` (N x 2) the UVs, ``side`` / ``other`` / ``shell`` from Mirror,
    ``centre`` / ``r`` the brush, ``axis`` 'U' / 'V', ``pos`` the Axis Position."""
    U = np.asarray(U, float)
    c = 0 if axis == 'U' else 1
    inside = np.hypot(U[:, 0] - centre[0], U[:, 1] - centre[1]) <= r
    if flood and inside.any():
        inside = np.isin(shell, np.unique(shell[inside]))
    paint = low_side(side, U[:, c])
    if centre[c] > pos:
        paint = 1 - paint
    new = U.copy()
    on = inside & (side == ON_LINE)
    new[on, c] = pos
    pts = np.nonzero(inside & (side == paint) & (other >= 0))[0]
    if len(pts):
        src = U[other[pts]]
        new[pts] = src
        new[pts, c] = 2.0 * pos - src[:, c]
    return new


def remember(mesh, edge_index, mirror):
    _seam[mesh.ob.name] = {"edge": edge_index, "sig": signature(mesh.bm),
                           "segments": mesh.segments(mirror.line_edges)}


def refresh_segments(mesh, mirror):
    s = _seam.get(mesh.ob.name)
    if s is not None:
        s["segments"] = mesh.segments(mirror.line_edges)
