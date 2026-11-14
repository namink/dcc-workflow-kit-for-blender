# SPDX-License-Identifier: GPL-3.0-or-later
"""Signed face sweeps for Maya-style Smart Extrude.

Work exclusively on disposable datablocks. A positive swept volume grows the
surface; a negative one carves it. Exact Boolean stitches intersections with all
shells of the input mesh. The caller only replaces the edit mesh after validation.
"""
import math

import bmesh
import bpy
from . import smart_topology as topology

CAP = "allset_smart_cap"
SOURCE = ".allset_smart_source_face"


class GeometryError(ValueError):
    pass


def selected_faces(bm, mode):
    """Maya converts vertex/edge input to incident faces, ignoring hidden faces."""
    if mode[2]:
        return [f for f in bm.faces if f.select and not f.hide]
    if mode[1]:
        return [f for f in bm.faces if not f.hide and any(e.select for e in f.edges)]
    return [f for f in bm.faces if not f.hide and any(v.select for v in f.verts)]


def validate(bm, *, input_mesh=False):
    if not bm.faces or any(not e.is_manifold for e in bm.edges):
        raise GeometryError("Smart Extrude needs a closed manifold mesh" if input_mesh
                            else "The sweep would produce an open or non-manifold mesh; reduce the transform")
    if any(not math.isfinite(c) for v in bm.verts for c in v.co):
        raise GeometryError("The mesh contains invalid coordinates")
    if any(not e.is_contiguous for e in bm.edges):
        raise GeometryError("Conform face normals before using Smart Extrude")
    seen = set()
    for f in bm.faces:
        key = frozenset(f.verts)
        if key in seen or f.calc_area() <= 0:
            raise GeometryError("The mesh contains duplicate or degenerate faces")
        seen.add(key)


def _key(p):
    # Shared corners are computed identically, including the shared side diagonal.
    return tuple(float(c) for c in p)


def _clipped_triangles(ids, before, after, uvs, positive):
    """Split a face at zero normal displacement before forming sweep cells.

    A rotating face straddles its original plane. A single twisted prism there
    is self-intersecting. Clipping paired start/end corners makes two wedges,
    one to union and one to subtract, with the same contact seam.
    """
    points = [(before[i], after[i], uv, frozenset((i,))) for i, uv in zip(ids, uvs)]
    normal = (points[1][0]-points[0][0]).cross(points[2][0]-points[0][0]).normalized()
    distances = [(b-a).dot(normal) for a, b, _uv, _support in points]
    if max(abs(d) for d in distances) < 1e-12:
        return
    polygon = []
    for i in range(3):
        j = (i+1)%3
        a, b = points[i], points[j]
        da, db = distances[i], distances[j]
        inside = da >= 0 if positive else da <= 0
        if inside:
            polygon.append(a)
        if da*db < 0:
            # Canonical endpoint order keeps shared intersections bit-identical.
            if _key(a[0]) > _key(b[0]):
                a, b, da, db = b, a, db, da
            t = da/(da-db)
            uv = {name: a[2][name].lerp(b[2][name], t) for name in a[2]}
            polygon.append((a[0].lerp(b[0], t), a[1].lerp(b[1], t), uv, a[3] | b[3]))
    for i in range(1, len(polygon)-1):
        yield [polygon[0], polygon[i], polygon[i+1]]


def _brush(triangles, before, after, positive, materials, edge_panels):
    """Boundary of the signed tetrahedral cells of a triangulated face sweep.

    Globally ordered corners choose the same diagonal on both sides of a
    shared edge. Opposite internal triangles cancel, leaving closed brushes
    without a Boolean operation per face. Rotation can create both signs.
    """
    faces = {}
    for ids, material, uv, base_panel, cap_panel in triangles:
        for triangle in _clipped_triangles(ids, before, after, uv, positive):
            ordered = sorted(range(3), key=lambda i: (_key(triangle[i][0]), _key(triangle[i][1])))
            orientation = 1 if ordered in ([0, 1, 2], [1, 2, 0], [2, 0, 1]) else -1
            points = [triangle[i][0] for i in ordered] + [triangle[i][1] for i in ordered]
            uvs = [triangle[i][2] for i in ordered] * 2
            supports = [triangle[i][3] for i in ordered] * 2
            _cells(faces, points, uvs, material, orientation, positive, supports, base_panel, cap_panel, edge_panels)
    if not faces:
        return None
    bm = bmesh.new()
    try:
        layer = bm.faces.layers.int.new(CAP)
        panel_layer = bm.faces.layers.int.new(topology.PANEL)
        uv_layers = {name: bm.loops.layers.uv.new(name) for name in triangles[0][2][0]}
        verts = {}
        for coords, material, cap, panel, uvs in faces.values():
            vs = [verts.setdefault(co, None) for co in coords]
            for i, co in enumerate(coords):
                if vs[i] is None:
                    vs[i] = verts[co] = bm.verts.new(co)
            f = bm.faces.new(vs)
            f.material_index, f[layer] = material, cap
            f[panel_layer] = panel
            for lp, uv in zip(f.loops, uvs):
                for name, uv_layer in uv_layers.items():
                    lp[uv_layer].uv = uv[name]
        bm.normal_update()
        mesh = bpy.data.meshes.new(".allset_smart_brush")
        bm.to_mesh(mesh)
        for material in materials:
            mesh.materials.append(material)
        return mesh
    finally:
        bm.free()


def _cells(faces, points, uvs, material, orientation, positive, supports, base_panel, cap_panel, edge_panels):
    for cell in ((0, 1, 2, 3), (1, 2, 3, 4), (2, 3, 4, 5)):
        p, q, r, s = [points[i] for i in cell]
        vol = (q-p).cross(r-p).dot(s-p)
        scale = max((q-p).length, (r-p).length, (s-p).length)
        if abs(vol) <= max(scale**3 * 1e-12, 1e-30):
            continue
        if (vol * orientation > 0) != positive:
            continue
        # This ordering points outwards for a positive determinant.
        for tri in ((cell[0], cell[2], cell[1]), (cell[0], cell[1], cell[3]),
                    (cell[1], cell[2], cell[3]), (cell[2], cell[0], cell[3])):
            if vol < 0:
                tri = tuple(reversed(tri))
            coords = tuple(_key(points[i]) for i in tri)
            key = tuple(sorted(coords))
            if key in faces:
                del faces[key]
            else:
                if all(i >= 3 for i in tri):
                    cap, panel = 1, cap_panel
                elif all(i < 3 for i in tri):
                    cap, panel = 0, base_panel
                else:
                    vertices = frozenset().union(*(supports[i] for i in tri))
                    cap, panel = 2, edge_panels.get(tuple(sorted(vertices)), 0)
                faces[key] = coords, material, cap, panel, [uvs[i] for i in tri]


def _boolean(context, mesh, brush, operation):
    source = bpy.data.objects.new(".allset_smart_source", mesh)
    operand = bpy.data.objects.new(".allset_smart_operand", brush)
    try:
        context.scene.collection.objects.link(source)
        context.scene.collection.objects.link(operand)
        modifier = source.modifiers.new("Smart Extrude", 'BOOLEAN')
        modifier.operation = operation
        modifier.solver = 'EXACT'
        modifier.use_self = True
        modifier.object = operand
        depsgraph = context.evaluated_depsgraph_get()
        depsgraph.update()
        return bpy.data.meshes.new_from_object(source.evaluated_get(depsgraph),
                                               preserve_all_data_layers=True, depsgraph=depsgraph)
    finally:
        bpy.data.objects.remove(source, do_unlink=True)
        bpy.data.objects.remove(operand, do_unlink=True)


def sweep(context, pre, face_ids, transforms, materials=(), *, separate=False):
    """Return a new, validated BMesh. ``transforms`` are absolute mesh-space matrices.

    No input mutations, selection changes, mode switches, or user modifiers.
    UVs/materials on original polygons travel through the Exact solver.
    """
    validate(pre, input_mesh=True)
    pre.faces.ensure_lookup_table()
    pre.faces.index_update()
    pre.verts.index_update()
    input_panels = topology.input_panels(pre)
    patch = pre.copy()
    mesh = None
    try:
        patch.faces.ensure_lookup_table()
        chosen = set(face_ids)
        group_layer = patch.faces.layers.int.new(".smart_group")
        for f in patch.faces:
            f[group_layer] = f.index
        discard = [f for f in patch.faces if f.index not in chosen]
        bmesh.ops.delete(patch, geom=discard, context='FACES_ONLY')
        bmesh.ops.triangulate(patch, faces=list(patch.faces))
        uv_layers = {layer.name: layer for layer in patch.loops.layers.uv.values()}
        triangles = [(tuple((f[group_layer], v.index) if separate else v.index for v in f.verts), f.material_index,
                      [{name: lp[layer].uv.copy() for name, layer in uv_layers.items()} for lp in f.loops],
                      input_panels[f[group_layer]],
                      len(pre.faces)+(f[group_layer]+1 if separate else input_panels[f[group_layer]]))
                     for f in patch.faces]
        edge_counts = {}
        for ids, *_data in triangles:
            for a, b in zip(ids, ids[1:]+ids[:1]):
                key = tuple(sorted((a, b)))
                edge_counts[key] = edge_counts.get(key, 0)+1
        edge_panels = {key: 2*len(pre.faces)+i+1 for i, key in enumerate(sorted(edge_counts))
                       if edge_counts[key] == 1}
        positions = {((f[group_layer], v.index) if separate else v.index): v.co.copy()
                     for f in patch.faces for v in f.verts}
        mesh = bpy.data.meshes.new(".allset_smart_input")
        original = pre.copy()
        try:
            marker = original.faces.layers.int.get(CAP) or original.faces.layers.int.new(CAP)
            source = original.faces.layers.int.get(SOURCE) or original.faces.layers.int.new(SOURCE)
            panel = original.faces.layers.int.get(topology.PANEL) or original.faces.layers.int.new(topology.PANEL)
            for i, f in enumerate(original.faces):
                f[marker] = 0
                f[source] = i+1
                f[panel] = input_panels[i]
            original.to_mesh(mesh)
        finally:
            original.free()
        for material in materials:
            mesh.materials.append(material)
        before = positions
        changed = False
        for transform in transforms:
            after = {i: (transform(p, i[0]) if separate else transform @ p) for i, p in positions.items()}
            for positive, operation in ((True, 'UNION'), (False, 'DIFFERENCE')):
                brush = _brush(triangles, before, after, positive, materials, edge_panels)
                if brush is None:
                    continue
                changed = True
                try:
                    result = _boolean(context, mesh, brush, operation)
                finally:
                    bpy.data.meshes.remove(brush)
                bpy.data.meshes.remove(mesh)
                mesh = result
            before = after
        protected = {topology._key(v.co) for v in pre.verts}
        moved = set()
        for transform in transforms:
            moved |= {topology._key(transform(p, i[0]) if separate else transform @ p) for i, p in positions.items()}
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.normal_update()
            marker = bm.faces.layers.int.get(CAP)
            if changed:
                topology.reconstruct(bm)
                # a moved corner stays only while a surviving cap still uses it (a buried cap leaves none)
                cap_points = {topology._key(v.co) for f in bm.faces if marker and f[marker] == 1 for v in f.verts}
                topology.dissolve_seam_points(bm, protected | (moved & cap_points))
            validate(bm)
            caps = [f for f in bm.faces if marker and f[marker] == 1]
            selection = caps or [f for f in bm.faces if marker and f[marker] == 2]
            if not changed:
                selection = [f for f in bm.faces if f.index in chosen]
            for v in bm.verts:
                v.select = False
            for e in bm.edges:
                e.select = False
            for f in bm.faces:
                f.select = False
            for f in selection:
                f.select_set(True)
            bm.select_mode = {'FACE'}
            bm.select_flush_mode()
            for name in (CAP, SOURCE, topology.PANEL, '.allset_smart_surface', '.allset_smart_touched'):
                layer = bm.faces.layers.int.get(name)
                if layer is not None:
                    bm.faces.layers.int.remove(layer)
            return bm
        except Exception:
            bm.free()
            raise
    finally:
        patch.free()
        if mesh is not None:
            bpy.data.meshes.remove(mesh)
