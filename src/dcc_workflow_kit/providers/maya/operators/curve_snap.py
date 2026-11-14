# SPDX-License-Identifier: GPL-3.0-or-later
"""Snapping for the Maya curve drawing tools (Issue #208; operators/curve_draw.py).

Maya's creation tools snap while a snap key is held, like the Move Tool: X = grid (curve_draw.snap_grid), C = curves
(the point lands on the nearest curve or polygon edge under the cursor and slides along it while dragged), V = points
(the nearest CV, polygon vertex or object pivot on screen). The Status Line snap buttons (= Blender's scene snapping)
snap the same way, and Ctrl while clicking inverts them, like Blender's snapping.

Pure parts (headless-tested in tests/test_issue208_curve_snap.py) take world points and a 4 x 4 perspective matrix;
``gather`` / ``snap`` read the scene.
"""

import numpy as np
from mathutils import Vector

from . import curves_math as cm
from .preselect import project, segment_distance

GRID, CURVE, POINT, SURFACE = "grid", "curve", "point", "surface"
CURVE_RADIUS_PX = 16.0          # curve snap: a curve this close to the cursor (Maya picks the curve under it)
ORDER = (POINT, CURVE, SURFACE)  # several snaps at once: a point first, then a curve, then a surface

# Blender snap elements (Status Line snap buttons / Blender's own snapping) -> curve tool snaps
ELEMENT_MODES = {
    'INCREMENT': GRID, 'GRID': GRID,
    'VERTEX': POINT,
    'EDGE': CURVE, 'EDGE_MIDPOINT': CURVE, 'EDGE_PERPENDICULAR': CURVE,
    'FACE': SURFACE, 'FACE_PROJECT': SURFACE, 'FACE_NEAREST': SURFACE,
}


# --- pure parts ----------------------------------------------------------------------------------

def modes_of_elements(elements):
    """Curve tool snaps for a set of Blender snap elements."""
    return {ELEMENT_MODES[e] for e in elements if e in ELEMENT_MODES}


def scene_modes(use_snap, elements, ctrl):
    """Snaps that Blender's scene snapping gives a click: on when ``use_snap`` differs from Ctrl (Blender: Ctrl
    inverts snapping while it is held)."""
    return modes_of_elements(elements) if bool(use_snap) != bool(ctrl) else set()


def _clip(co, persp):
    co = np.asarray(co, dtype=np.float64).reshape(-1, 3)
    return np.hstack([co, np.ones((len(co), 1))]) @ np.asarray(persp, dtype=np.float64).T


def nearest_point(mouse, co, persp, width, height):
    """Index of the world point (N x 3) nearest to ``mouse`` on screen, in front of the view; None if none."""
    co = np.asarray(co, dtype=np.float64).reshape(-1, 3)
    if len(co) == 0:
        return None
    xy, front = project(co, persp, width, height)
    if not front.any():
        return None
    dist = np.hypot(xy[:, 0] - mouse[0], xy[:, 1] - mouse[1])
    dist = np.where(front, dist, np.inf)
    return int(np.argmin(dist))


def segment_world_param(t, wa, wb):
    """Screen parameter t on a projected segment -> parameter s on the world segment (perspective-correct:
    clip coordinates are linear in s, screen = clip / w)."""
    den = (1.0 - t) * wb + t * wa
    return np.where(np.abs(den) > 1e-12, t * wa / np.where(np.abs(den) > 1e-12, den, 1.0), t)


def nearest_on_segments(mouse, a, b, persp, width, height, radius):
    """World point (3-tuple) on the segments a[i]-b[i] (world, M x 3) nearest to ``mouse`` on screen within
    ``radius`` px, and its screen distance; (None, inf) when no segment is that close."""
    a = np.asarray(a, dtype=np.float64).reshape(-1, 3)
    b = np.asarray(b, dtype=np.float64).reshape(-1, 3)
    if len(a) == 0:
        return None, float("inf")
    ha, hb = _clip(a, persp), _clip(b, persp)
    front = (ha[:, 3] > 1e-9) & (hb[:, 3] > 1e-9)
    xa, _fa = project(a, persp, width, height)
    xb, _fb = project(b, persp, width, height)
    dist, t = segment_distance(mouse, xa, xb)
    dist = np.where(front, dist, np.inf)
    i = int(np.argmin(dist))
    if not dist[i] <= radius:
        return None, float("inf")
    s = float(segment_world_param(t[i], ha[i, 3], hb[i, 3]))
    return tuple(a[i] + (b[i] - a[i]) * s), float(dist[i])


def _screen_dist(p, mouse, persp, width, height):
    xy, front = project([p], persp, width, height)
    return float(np.hypot(xy[0, 0] - mouse[0], xy[0, 1] - mouse[1])) if front[0] else float("inf")


def nearest_on_curve(mouse, curve, persp, width, height, radius, count=None):
    """Point on a Maya curve ((cvs, knots, degree, weights), world) nearest to ``mouse`` on screen within
    ``radius`` px: (world point, parameter, screen distance) or (None, None, inf). Sampled, then refined on the
    curve itself, so the point is exactly on the curve."""
    cvs, knots, degree, weights = curve
    if len(cvs) < 2 or len(knots) != len(cvs) + degree - 1:
        return None, None, float("inf")
    full = cm.full(knots)
    u0, u1 = float(full[degree]), float(full[len(cvs)])      # the curve's own range (periodic: without the wrap)
    if u1 <= u0:
        return None, None, float("inf")
    spans = max(1, len(set(knots)) - 1)
    n = count or max(48, 16 * spans)
    us = [u0 + (u1 - u0) * k / (n - 1) for k in range(n)]
    pts = [cm.evaluate(cvs, knots, degree, u, weights) for u in us]
    _p, d = nearest_on_segments(mouse, pts[:-1], pts[1:], persp, width, height, radius + 8.0)
    if _p is None:
        return None, None, float("inf")
    xy, front = project(pts, persp, width, height)
    dist = np.where(front, np.hypot(xy[:, 0] - mouse[0], xy[:, 1] - mouse[1]), np.inf)
    k = int(np.argmin(dist))
    lo, hi = us[max(k - 1, 0)], us[min(k + 1, n - 1)]

    def f(u):
        return _screen_dist(cm.evaluate(cvs, knots, degree, u, weights), mouse, persp, width, height)

    for _ in range(60):                         # golden-section search on the screen distance
        m1 = hi - (hi - lo) * 0.6180339887
        m2 = lo + (hi - lo) * 0.6180339887
        if f(m1) <= f(m2):
            hi = m2
        else:
            lo = m1
    u = 0.5 * (lo + hi)
    p = cm.evaluate(cvs, knots, degree, u, weights)
    d = f(u)
    if d > radius:
        return None, None, float("inf")
    return tuple(p), u, d


class Targets:
    """Snap targets in world space: points (N x 3), polygon edges (a, b: M x 3) and curves (Maya curves)."""

    def __init__(self, points=(), edge_a=(), edge_b=(), curves=()):
        self.points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        self.edge_a = np.asarray(edge_a, dtype=np.float64).reshape(-1, 3)
        self.edge_b = np.asarray(edge_b, dtype=np.float64).reshape(-1, 3)
        self.curves = list(curves)


def snap_to(targets, modes, mouse, persp, width, height, radius=CURVE_RADIUS_PX, surface=None):
    """World point for ``mouse`` under the snaps ``modes`` (grid is applied by the caller), or None.
    ``surface``: a function mouse -> world point or None (ray cast on the scene)."""
    for mode in ORDER:
        if mode not in modes:
            continue
        if mode == POINT:
            i = nearest_point(mouse, targets.points, persp, width, height)
            if i is not None:
                return Vector(targets.points[i])
        elif mode == CURVE:
            best, best_d = None, float("inf")
            for c in targets.curves:
                p, _u, d = nearest_on_curve(mouse, c, persp, width, height, radius)
                if p is not None and d < best_d:
                    best, best_d = p, d
            p, d = nearest_on_segments(mouse, targets.edge_a, targets.edge_b, persp, width, height, radius)
            if p is not None and d < best_d:
                best, best_d = p, d
            if best is not None:
                return Vector(best)
        elif mode == SURFACE and surface is not None:
            p = surface(mouse)
            if p is not None:
                return Vector(p)
    return None


# --- the scene -----------------------------------------------------------------------------------

def _visible(ob, view_layer, space):
    try:
        return ob.visible_get(view_layer=view_layer, viewport=space) if space is not None \
            else ob.visible_get(view_layer=view_layer)
    except (TypeError, RuntimeError, ReferenceError):
        return False


def _mesh_world(ob, depsgraph):
    """World vertex positions and edge index pairs of the evaluated mesh of ``ob``."""
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    try:
        n = len(me.vertices)
        co = np.empty(n * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        e = np.empty(len(me.edges) * 2, dtype=np.int64)
        me.edges.foreach_get("vertices", e)
        e = e.reshape(-1, 2)
    finally:
        ev.to_mesh_clear()
    m = np.asarray(ob.matrix_world, dtype=np.float64)
    co = co @ m[:3, :3].T + m[:3, 3]
    return co, e


def gather(context, space=None, modes=(POINT, CURVE)):
    """Snap targets of the visible objects: CVs, polygon vertices and object pivots (V); curves and polygon
    edges (C)."""
    from . import curves_maya
    view_layer = context.view_layer
    depsgraph = context.evaluated_depsgraph_get()
    points, ea, eb, curves = [], [], [], []
    for ob in context.scene.objects:
        if ob is None or not _visible(ob, view_layer, space):
            continue
        if POINT in modes:
            points.append(np.asarray(ob.matrix_world.translation, dtype=np.float64).reshape(1, 3))
        if ob.type == 'MESH':
            try:
                co, e = _mesh_world(ob, depsgraph)
            except (RuntimeError, AttributeError):
                continue
            if POINT in modes:
                points.append(co)
            if CURVE in modes and len(e):
                ea.append(co[e[:, 0]])
                eb.append(co[e[:, 1]])
        elif ob.type == 'CURVE':
            for sp in ob.data.splines:
                try:
                    mc = curves_maya.read_spline(sp, ob.matrix_world)
                except (ValueError, IndexError, ZeroDivisionError):
                    continue
                if POINT in modes:
                    pts = [tuple(ob.matrix_world @ Vector(p.co[:3])) for p in sp.points] if sp.type != 'BEZIER' \
                        else [tuple(ob.matrix_world @ p.co) for p in sp.bezier_points]
                    if pts:
                        points.append(np.asarray(pts, dtype=np.float64))
                if CURVE in modes:
                    curves.append(mc.math())
    cat = (lambda parts: np.concatenate(parts) if parts else np.zeros((0, 3)))
    return Targets(cat(points), cat(ea), cat(eb), curves)


def surface_under(context, region, rv3d):
    """Function mouse (region px) -> the first surface point under it (scene ray cast), for FACE snapping."""
    from bpy_extras import view3d_utils

    def hit(mouse):
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse)
        ray = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse)
        try:
            ok, loc, *_rest = context.scene.ray_cast(context.evaluated_depsgraph_get(), origin, ray)
        except (RuntimeError, TypeError):
            return None
        return loc if ok else None
    return hit
