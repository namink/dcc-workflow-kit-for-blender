# SPDX-License-Identifier: GPL-3.0-or-later
"""Rebuild semantic Smart Extrude panels from their intersection boundaries.

Boolean tessellation is disposable; input face borders are not. Only faces with
the same explicit panel id can be rebuilt together. Hole connectors carry their
endpoint coordinates so an inset/subdivision cannot accidentally inherit their
temporary role. No UV-shape heuristics or flood across arbitrary planar faces.
"""
import bmesh
from mathutils import Vector

PANEL = '.allset_smart_panel'
SUPPORT = '.allset_smart_support'
SUPPORT_A = '.allset_smart_support_a'
SUPPORT_B = '.allset_smart_support_b'


def _uv_continuous(edge, layers):
    a, b = edge.link_loops
    b0, b1 = (b, b.link_loop_next) if a.vert is b.vert else (b.link_loop_next, b)
    return all((a[layer].uv-b0[layer].uv).length < 1e-6
               and (a.link_loop_next[layer].uv-b1[layer].uv).length < 1e-6 for layer in layers)


def input_panels(bm):
    bm.faces.index_update()
    parents = list(range(len(bm.faces)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    flag = bm.edges.layers.int.get(SUPPORT)
    a = bm.edges.layers.float_vector.get(SUPPORT_A)
    b = bm.edges.layers.float_vector.get(SUPPORT_B)
    uv = list(bm.loops.layers.uv.values())
    if flag and a and b:
        for edge in bm.edges:
            if not edge[flag] or len(edge.link_faces) != 2 or edge.seam or not edge.smooth:
                continue
            p, q = (v.co for v in edge.verts)
            saved_p, saved_q = edge[a], edge[b]
            same = min((p-saved_p).length_squared+(q-saved_q).length_squared,
                       (p-saved_q).length_squared+(q-saved_p).length_squared) < 1e-14
            f, g = edge.link_faces
            if (same and f.material_index == g.material_index and f.hide == g.hide and f.smooth == g.smooth
                    and f.normal.dot(g.normal) > 1-1e-7
                    and _uv_continuous(edge, uv)):
                i, j = root(f.index), root(g.index)
                parents[max(i, j)] = min(i, j)
    return {f.index: root(f.index)+1 for f in bm.faces}


def _boundaries(faces):
    selected = set(faces)
    outgoing = {}
    for face in faces:
        for lp in face.loops:
            if sum(f in selected for f in lp.edge.link_faces) != 1:
                continue
            if lp.vert in outgoing:
                return None  # touching loops: keep the validated solver decomposition
            outgoing[lp.vert] = lp
    cycles = []
    while outgoing:
        start = min(outgoing, key=lambda v: tuple(v.co))
        cycle, vertex = [], start
        while vertex in outgoing:
            lp = outgoing.pop(vertex)
            cycle.append(lp)
            vertex = lp.link_loop_next.vert
        if vertex is not start or len(cycle) < 3:
            return None
        cycles.append(cycle)
    return cycles


def _area(points):
    return .5*sum(a.x*b.y-a.y*b.x for a, b in zip(points, points[1:]+points[:1]))


def _cross(a, b, c):
    d, e = b-a, c-a
    return d.x*e.y-d.y*e.x


def _simple(points, eps):
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i+1)%n]
        for j in range(i+2, n):
            if i == 0 and j == n-1:
                continue
            c, d = points[j], points[(j+1)%n]
            if _cross(a, b, c)*_cross(a, b, d) < -eps and _cross(c, d, a)*_cross(c, d, b) < -eps:
                return False
    return True


def _corner_indices(points):
    corners = []
    for i, point in enumerate(points):
        a, b = point-points[i-1], points[(i+1)%len(points)]-point
        if abs(a.x*b.y-a.y*b.x) > max(a.length*b.length*1e-6, 1e-20) or a.dot(b) <= 0:
            corners.append(i)
    return corners


def _arc(cycle, a, b):
    result = [cycle[a]]
    while a != b:
        a = (a+1)%len(cycle)
        result.append(cycle[a])
    return result


def _polygons(cycles, normal):
    """Single ngons, or stable radial bands for matching polygonal hole loops."""
    if len(cycles) == 1:
        return [cycles[0]]
    x = normal.orthogonal().normalized()
    y = normal.cross(x).normalized()
    origin = cycles[0][0].vert.co

    def project(cycle):
        return [Vector(((lp.vert.co-origin).dot(x), (lp.vert.co-origin).dot(y))) for lp in cycle]

    projected = [project(c) for c in cycles]
    outer = [i for i, p in enumerate(projected) if _area(p) > 0]
    if len(cycles) != 2 or len(outer) != 1:
        return None
    oi = outer[0]
    outside, inside = cycles[oi], list(reversed(cycles[1-oi]))
    p, q = project(outside), project(inside)
    oc, ic = _corner_indices(p), _corner_indices(q)
    if len(oc) != len(ic) or len(oc) < 3:
        return None
    # Straight radial bands are guaranteed only for nested convex loops. Other
    # outlines retain the valid constrained solver partition of this panel.
    if any(_cross(poly[i-1], poly[i], poly[(i+1)%len(poly)]) < -1e-10
           for poly in ([p[i] for i in oc], [q[i] for i in ic]) for i in range(len(poly))):
        return None
    target = _area(p)-_area(q)
    eps = max(abs(target)*1e-6, 1e-12)
    choices = []
    for shift in range(len(ic)):
        rotated = ic[shift:]+ic[:shift]
        polygons = []
        for i in range(len(oc)):
            j = (i+1)%len(oc)
            polygons.append(_arc(outside, oc[i], oc[j])+list(reversed(_arc(inside, rotated[i], rotated[j]))))
        coords = [project(poly) for poly in polygons]
        if (all(_area(poly) > eps and _simple(poly, eps*eps) for poly in coords)
                and abs(sum(_area(poly) for poly in coords)-target) < eps):
            cost = sum((p[a]-q[b]).length_squared for a, b in zip(oc, rotated))
            choices.append((cost, shift, polygons))
    return min(choices, key=lambda item: item[:2])[2] if choices else None


def _rebuild(bm, faces):
    cycles = _boundaries(faces)
    if not cycles:
        return False
    polygons = _polygons(cycles, faces[0].normal)
    if polygons is None:
        return False
    old_edges = {e for f in faces for e in f.edges}
    old_verts = {v for f in faces for v in f.verts}
    existing = {frozenset(f.verts): f for f in faces}
    kept, created = set(), []
    try:
        for polygon in polygons:
            verts = [lp.vert for lp in polygon]
            old = existing.get(frozenset(verts))
            if old is not None and len(old.verts) == len(verts):
                kept.add(old)
                continue
            new = bm.faces.new(verts)
            created.append(new)
            new.material_index, new.smooth, new.hide = faces[0].material_index, faces[0].smooth, faces[0].hide
            for kind in ('int', 'float', 'float_vector', 'string', 'color', 'float_color'):
                collection = getattr(bm.faces.layers, kind, None)
                for layer in collection.values() if collection is not None else ():
                    new[layer] = faces[0][layer]
            for dst, src in zip(new.loops, polygon):
                for layer in bm.loops.layers.uv.values():
                    dst[layer].uv = src[layer].uv
                    dst[layer].pin_uv = src[layer].pin_uv
                for kind in ('color', 'float_color', 'float_vector', 'float', 'int', 'string'):
                    collection = getattr(bm.loops.layers, kind, None)
                    for layer in collection.values() if collection is not None else ():
                        dst[layer] = src[layer]
    except (ValueError, RuntimeError):
        extra_edges = {e for f in created for e in f.edges if e not in old_edges}
        for face in created:
            bm.faces.remove(face)
        for edge in extra_edges:
            if edge.is_valid and not edge.link_faces:
                bm.edges.remove(edge)
        return False
    for face in faces:
        if face not in kept:
            bm.faces.remove(face)
    for edge in old_edges:
        if edge.is_valid and not edge.link_faces:
            bm.edges.remove(edge)
    for vertex in old_verts:
        if vertex.is_valid and not vertex.link_edges:
            bm.verts.remove(vertex)
    return True


def reconstruct(bm):
    panel = bm.faces.layers.int.get(PANEL)
    if panel is None:
        return
    layers = list(bm.loops.layers.uv.values())
    remaining = {f for f in bm.faces if f[panel] > 0}
    ordered = sorted(remaining, key=lambda f: (f[panel], tuple(f.calc_center_median())))
    for seed in ordered:
        if seed not in remaining:
            continue
        remaining.remove(seed)
        faces, todo = [seed], [seed]
        while todo:
            f = todo.pop()
            for edge in f.edges:
                if len(edge.link_faces) != 2:
                    continue
                other = edge.link_faces[0] if edge.link_faces[1] is f else edge.link_faces[1]
                if (other in remaining and other[panel] == seed[panel]
                        and other.material_index == seed.material_index
                        and other.hide == seed.hide and other.smooth == seed.smooth
                        and other.normal.dot(seed.normal) > 1-1e-7):
                    remaining.remove(other)
                    todo.append(other)
                    faces.append(other)
        if len(faces) > 1:
            if not _rebuild(bm, faces):
                # Complex/non-simple outlines keep a valid decomposition. Limit
                # cleanup to this proven panel; never flood through source borders.
                selected = set(faces)
                edges = [e for f in faces for e in f.edges if len(e.link_faces) == 2
                         and all(n in selected for n in e.link_faces)]
                bmesh.ops.dissolve_limit(bm, angle_limit=.001, verts=[], edges=list(set(edges)),
                                        delimit={'MATERIAL', 'UV'} if layers else {'MATERIAL'})
    bm.normal_update()
    bm.edges.index_update()
    connectors = set()
    for edge in bm.edges:
        if len(edge.link_faces) == 2:
            f, g = edge.link_faces
            if f[panel] > 0 and f[panel] == g[panel] and f.normal.dot(g.normal) > 1-1e-7:
                connectors.add(edge.index)
    if not connectors:
        for collection, name in ((bm.edges.layers.int, SUPPORT),
                                 (bm.edges.layers.float_vector, SUPPORT_A),
                                 (bm.edges.layers.float_vector, SUPPORT_B)):
            layer = collection.get(name)
            if layer is not None:
                collection.remove(layer)
        return
    flag = bm.edges.layers.int.get(SUPPORT) or bm.edges.layers.int.new(SUPPORT)
    a = bm.edges.layers.float_vector.get(SUPPORT_A) or bm.edges.layers.float_vector.new(SUPPORT_A)
    b = bm.edges.layers.float_vector.get(SUPPORT_B) or bm.edges.layers.float_vector.new(SUPPORT_B)
    # Adding edge layers can invalidate Python BMEdge wrappers in Blender 5.2.
    # Keep indices across that allocation and obtain fresh wrappers afterwards.
    bm.edges.index_update()
    for edge in bm.edges:
        edge[flag] = int(edge.index in connectors)
        if edge[flag]:
            edge[a], edge[b] = edge.verts[0].co, edge.verts[1].co


def _key(co, eps=1e-5):
    return tuple(round(c/eps) for c in co)


def _uv_straight(v, layers):
    """Each face's UVs run straight through the corner at ``v`` (or there are no UV layers)."""
    for lp in v.link_loops:
        for layer in layers:
            a, m, b = lp.link_loop_prev[layer].uv, lp[layer].uv, lp.link_loop_next[layer].uv
            ab = b-a
            if ab.length < 1e-9 or abs(ab.x*(m-a).y-ab.y*(m-a).x)/ab.length > 1e-6:
                return False
    return True


def dissolve_seam_points(bm, protected):
    """Remove the in-between points the solver leaves where a seam crosses a straight edge.

    Maya's result has no corner that sits on a straight line between two edges unless the input mesh had it:
    a point with exactly two edges in line, two faces of more than three corners, straight UVs on both sides
    and a position that is neither an input point nor a moved one (``protected`` = rounded coordinates) goes.
    """
    layers = list(bm.loops.layers.uv.values())
    strays = []
    for v in bm.verts:
        if len(v.link_edges) != 2 or len(v.link_faces) != 2 or _key(v.co) in protected:
            continue
        if any(len(f.verts) <= 3 for f in v.link_faces):
            continue
        a, b = (e.other_vert(v).co-v.co for e in v.link_edges)
        if a.length < 1e-9 or b.length < 1e-9 or a.normalized().dot(b.normalized()) > -1+1e-9:
            continue
        if not _uv_straight(v, layers):
            continue
        strays.append(v)
    if strays:
        bmesh.ops.dissolve_verts(bm, verts=strays)
    return len(strays)
