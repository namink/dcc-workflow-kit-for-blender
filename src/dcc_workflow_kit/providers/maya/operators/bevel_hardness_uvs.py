# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit Mesh > Bevel: hard edges and UVs afterwards, like Maya. Hardness read before the bevel (``input_hardness``) and
decided again by the Smoothing angle (``set_hardness``); UVs of the new points from the old faces they lie in
(``face_uv_maps``, ``set_uvs``). ``is_hard`` = Maya hardness of a Blender edge. Used by the bevel driver in
``bevel_maya`` (``smart_bevel`` reads ``is_hard`` there).
"""

import math

from .bevel_width import ZERO


ANGLE_SLACK = 1e-3      # degrees: faces meeting at the smoothing angle itself are not over it (soft edge)


def is_hard(e):
    """Maya hardness of a Blender edge: marked sharp, or next to a flat-shaded face."""
    return not e.smooth or not all(f.smooth for f in e.link_faces)


def input_hardness(bm, edges):
    """Before the bevel: hardness of segments around the picked vertices and their neighbours,
    and whether any face is shaded smooth. Unaffected edges retain their own flags through BMesh bevel."""
    ring = {v for e in edges for v in e.verts}
    ring |= {e.other_vert(v) for v in list(ring) for e in v.link_edges}
    segs = {e for v in ring for e in v.link_edges}
    return {"segments": [(e.verts[0].co.copy(), e.verts[1].co.copy(), is_hard(e)) for e in segs],
            "smooth": any(f.smooth for f in bm.faces)}


def _on_segment(a, b, segments):
    """Hardness of the old edge that the edge a-b lies on (a piece of it), else None."""
    for p, q, hard in segments:
        d = q - p
        length = d.length
        if length <= ZERO:
            continue
        d = d / length
        if all(((x - p) - d * (x - p).dot(d)).length < 1e-6 * max(1.0, length) for x in (a, b)):
            ta, tb = sorted(((a - p).dot(d), (b - p).dot(d)))
            if min(tb, length) - max(ta, 0.0) > 1e-7:
                return hard
    return None


def set_hardness(bm, hard_in, inner, touched, smoothing_angle):
    """Maya's hard edges after a bevel: an edge is decided again (hard when its two faces meet at more than
    ``smoothing_angle`` degrees, soft at that angle itself) when it is new (on no old edge) or one of its faces
    holds a profile point between a profile's ends; every other edge, pieces of cut old edges too, keeps its old
    hardness. Written as Blender sharp edges on smooth-shaded faces (a mesh with no smooth face before and no
    soft edge after stays flat)."""
    bm.normal_update()
    # a right-angle edge in three segments puts its strip faces at the smoothing angle itself (30 degrees): not
    # over it, so those edges are soft. The slack keeps rounding from leaving some of them hard and others soft
    # (#331: one strip of a box shaded faceted next to a smooth one)
    limit = math.radians(smoothing_angle + ANGLE_SLACK)
    redo_edges = {e for v in inner for f in v.link_faces for e in f.edges}
    affected = redo_edges | {e for v in touched for e in v.link_edges}
    hard = {}
    for e in affected:
        a, b = e.verts
        if len(e.link_faces) != 2:
            hard[e] = is_hard(e)
            continue
        redo = e in redo_edges
        old = _on_segment(a.co, b.co, hard_in["segments"]) if not redo else None
        if old is not None:
            hard[e] = old
        else:
            f0, f1 = e.link_faces
            hard[e] = f0.normal.angle(f1.normal, 0.0) > limit
    if not hard_in["smooth"] and all(hard.values()):
        if all(is_hard(e) for e in bm.edges if e not in hard):
            return
    # Read old flat-face hardness before changing the face shading. Only the
    # affected edges need a geometric decision; every other edge keeps its flags.
    for e in bm.edges:
        e.smooth = not hard[e] if e in hard else not is_hard(e)
    for f in bm.faces:
        f.smooth = True


def face_uv_maps(bm, faces):
    """Before the bevel: {(face index, UV layer name): (origin, axis x, axis y, 3 x 3 matrix)} mapping a point in the
    face's plane to that face's UV (least squares over its corners), for the faces around the bevelled vertices."""
    import numpy as np
    out = {}
    for layer in bm.loops.layers.uv.values():
        for f in faces:
            n = f.normal.copy()
            if n.length <= ZERO:
                continue
            o = f.verts[0].co.copy()
            ax = n.orthogonal().normalized()
            ay = n.cross(ax).normalized()
            rows = [[(lp.vert.co - o).dot(ax), (lp.vert.co - o).dot(ay), 1.0] for lp in f.loops]
            uvs = [list(lp[layer].uv) for lp in f.loops]
            m = np.linalg.lstsq(np.array(rows), np.array(uvs), rcond=None)[0]
            out[(f.index, layer.name)] = (o, ax, ay, m)
    return out


def _uv_at(fit, co):
    o, ax, ay, m = fit
    x, y = (co - o).dot(ax), (co - o).dot(ay)
    return (x * m[0][0] + y * m[1][0] + m[2][0], x * m[0][1] + y * m[1][1] + m[2][1])


def set_uvs(bm, uv_maps, flay, mlay, ilay, tlay):
    """Maya's UVs after a bevel, where they are known: in an old face every point the bevel made (slide and corner
    points) gets that face's own UV map at its position; a strip's outer rows take the UVs of the old faces next to
    them. Profile points between a profile's ends keep Blender's interpolation."""
    beside = uv_maps.get("beside", set())
    for layer in bm.loops.layers.uv.values():
        name = layer.name
        for f in bm.faces:
            if f[mlay]:
                continue
            fit = uv_maps.get((f[flay] - 1, name))
            if fit is None:
                continue
            for lp in f.loops:
                if lp.vert[tlay] and not lp.vert[ilay]:
                    lp[layer].uv = _uv_at(fit, lp.vert.co)
        for f in bm.faces:
            if not f[mlay]:
                continue
            for lp in f.loops:
                v = lp.vert
                if v[ilay]:
                    continue
                # the old face across one of this corner's two edges, a face next to a bevelled edge first (the
                # strip's side, not the far face at its end)
                olds = [g for e in (lp.edge, lp.link_loop_prev.edge) for g in e.link_faces if g is not f and not g[mlay]]
                olds.sort(key=lambda g: (g[flay] - 1) not in beside)
                for other in olds:
                    src = next((x for x in other.loops if x.vert is v), None)
                    if src is not None:
                        lp[layer].uv = src[layer].uv
                        break
