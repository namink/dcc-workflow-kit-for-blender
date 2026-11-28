# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit Mesh > Extrude with faces or edges and a curve selected: they extrude along the curve (Maya's
polyExtrudeFace / polyExtrudeEdge with the curve as its path, the Extrude option box's Curve: Selected).

Like Maya: step k of ``Divisions`` N puts the faces' centre on the curve point at parameter k / N of the curve's
range (even in parameter, not in length), wherever the curve is in the world (it is not moved to the faces). Each
step turns the faces on from the previous step by the smallest turn from the previous chord onto this step's chord
(from the previous step's centre to this one; the first chord starts at the faces' centre and turns from their
normal), so the turns add up along the path; the faces keep their size. Taper scales step k by
1 - (1 - Taper) k / N, Twist turns it about its normal by Twist k / N degrees (right-handed). Local Translate Z adds
the faces' first normal x k / N, Thickness the last step's direction x k / N, and Offset the plain extrusion's offset
of each vertex x k / N (its border edges move into the faces by Offset x k / N, in the faces' first plane; it is not
tapered, twisted or turned with the path). Default Divisions 1: the faces go to
the curve's end at once. The node is editable afterwards like any kit extrusion (In-View Editor, Channel Box INPUTS).

Taper and Twist only shape an extrusion that follows a curve (Maya: without one they change nothing). The faces
always move as one piece about the centre of all of them (the mean of their vertices) and their summed normal;
Keep Faces Together off only splits their vertices. Edges (``extrude_edges_along``) move the same way about the
mean of their midpoints and the summed normal of their faces; their Thickness, like Local Translate Z, goes along
that first normal. Two curves selected: the first selected one is the path, like
Maya. The Extrude option box's Curve: Generated makes the path itself (``generate_curve``): a straight cubic curve
from the centre of the faces' world bounding box along their summed normal (world X when they cancel out), its
length set by the size of that box (``GENERATED_LENGTH``).
"""

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import curves_math as cm
from .. import undo_steps
from . import curves_maya, extrude

# Channel Box rows in Maya's order of the node's attributes; the In-View Editor starts with the plain extrusion's rows
FIELDS = ("local_translate_z", "offset", "keep_faces_together", "divisions", "twist", "taper", "thickness")
VIEW_FIELDS = ("thickness", "local_translate_z", "offset", "divisions", "keep_faces_together", "twist", "taper")
LABELS = {"divisions": "Divisions", "taper": "Taper", "twist": "Twist", "local_translate_z": "Local Translate Z",
          "offset": "Offset", "thickness": "Thickness", "keep_faces_together": "Keep Faces Together"}
DEFAULTS = {"divisions": 1, "taper": 1.0, "twist": 0.0, "local_translate_z": 0.0, "offset": 0.0, "thickness": 0.0,
            "keep_faces_together": True, "curve": ""}
KINDS = {"divisions": "INT", "taper": "NONE", "twist": "NONE", "local_translate_z": "NONE", "offset": "NONE",
         "thickness": "NONE", "keep_faces_together": "BOOL"}


def path_curve(context):
    """The first picked selected curve object that is not being edited (Maya: the first curve selected with the
    faces), else None."""
    from . import pick_order
    if not getattr(context, "selected_objects", None):
        return None
    for ob in pick_order.ordered(context):
        if ob.type == 'CURVE' and ob.mode != 'EDIT' and ob.data.splines:
            return ob
    return None


GENERATED_LENGTH = 0.9     # the generated path's length per unit of the faces' bounding box diagonal


def generated_points(world_points, world_normals):
    """The 4 CVs (world) of the path Curve: Generated makes: a straight line from the centre of the points' bounding
    box along the summed normal (world X when it is zero), GENERATED_LENGTH x the box's diagonal long. Pure maths."""
    lo = Vector(tuple(min(p[i] for p in world_points) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in world_points) for i in range(3)))
    start = (lo + hi) / 2.0
    d = sum(world_normals, Vector())
    d = d.normalized() if d.length > 1e-9 else Vector((1.0, 0.0, 0.0))
    length = GENERATED_LENGTH * (hi - lo).length
    return [start + d * (length * i / 3.0) for i in range(4)]


def _node_name(context, ob, bm):
    """The polyExtrudeFace name the next ``run`` gives (the same node again when it re-runs on the same mesh)."""
    old = extrude.RECORDS.get(ob.name)
    if (old is not None and old.spec is SPEC and old.pre is not None and old.mesh_uid == ob.data.session_uid
            and extrude._pre_signature(old.pre) == extrude._pre_signature(bm)):
        return old.name
    return f"{SPEC.node}{int(context.scene.get(SPEC.counter, 0)) + 1}"


def generate_curve(context, ob, bm):
    """Curve: Generated: the path curve object for the selected faces of ``ob`` (edit mode), named after the node
    it will drive (an earlier one of that name is reshaped). None without selected faces."""
    faces = [f for f in bm.faces if f.select]
    if not faces:
        return None
    m = ob.matrix_world
    nm = m.to_3x3().inverted_safe().transposed()
    points = [m @ v.co for f in faces for v in f.verts]
    normals = [(nm @ f.normal).normalized() for f in faces]
    cvs, knots, degree = cm.cv_curve([tuple(p) for p in generated_points(points, normals)], 3)
    name = _node_name(context, ob, bm) + "Curve"
    found = bpy.data.objects.get(name)
    if found is not None and found.type == 'CURVE':
        curves_maya._replace_splines(found, [curves_maya.MCurve(cvs, knots, degree)])
        found.matrix_world = Matrix.Identity(4)
        return found
    path = curves_maya._new_curve_object(context, name, [curves_maya.MCurve(cvs, knots, degree)], select=False)
    path.name, path.data.name = name, name + "Shape"
    return path


def path_points(curve_ob, count):
    """World points of the curve at parameters k / ``count`` of its range, k = 1 .. count."""
    c = curves_maya.read_spline(curve_ob.data.splines[0], curve_ob.matrix_world)
    a, b = curves_maya._domain(c)
    return [Vector(cm.evaluate(c.cvs, c.knots, c.degree, a + (b - a) * k / count, c.weights))
            for k in range(1, count + 1)]


def _turn(src, dst):
    """The smallest rotation taking direction ``src`` onto ``dst`` (3x3)."""
    if dst.length < 1e-12:
        return Matrix.Identity(3)
    return src.rotation_difference(dst.normalized()).to_matrix()


def place(groups, points, divisions, taper=1.0, twist=0.0, ltz=0.0, thickness=0.0, unit=1.0, offset=0.0,
          thickness_along_normal=False):
    """Vertex positions along the path. ``groups`` = [(centre, unit normal, [(level k, vertex, base co[, offset
    direction])])] in mesh space; ``points`` = the path points for k = 1 .. divisions (mesh space). Step k turns
    on from step k - 1 by the smallest turn from the previous chord (the normal for the first) onto its own chord.
    Thickness goes along the last chord, or along the normal with ``thickness_along_normal`` (edges). Returns
    {vertex: co}. Pure maths."""
    n = max(1, divisions)
    out = {}
    for centre, normal, members in groups:
        prev = centre
        turns, dirs = [], []
        turn, heading = Matrix.Identity(3), normal
        for p in points:
            d = p - prev
            if d.length > 1e-12:
                turn = _turn(heading, d) @ turn
                heading = d.normalized()
            dirs.append(heading)
            turns.append(turn)
            prev = p
        last = normal if thickness_along_normal else (dirs[-1] if dirs else normal)
        for k, v, co, *rest in members:
            frac = k / n
            size = 1.0 - (1.0 - taper) * frac
            spin = Matrix.Rotation(twist * frac * 3.141592653589793 / 180.0, 3, normal)
            p = points[k - 1] + turns[k - 1] @ (spin @ ((co - centre) * size))
            out[v] = p + normal * (ltz * frac * unit) + last * (thickness * frac * unit)
            if rest and offset:
                out[v] = out[v] + rest[0] * (offset * frac * unit)
    return out


def _groups(faces, together):
    """[(centre, normal, [vertex keys])] of the faces before the extrusion: one group, like Maya, whose centre is
    the mean of all their vertices and whose normal is their summed normal (Keep Faces Together off: the keys are
    per face, the vertices apart)."""
    verts = {v for f in faces for v in f.verts}
    centre = sum((v.co for v in verts), Vector()) / len(verts)
    normal = sum((f.normal for f in faces), Vector())
    normal = normal.normalized() if normal.length > 1e-9 else Vector((0.0, 0.0, 1.0))
    keys = [v.index for v in verts] if together else [(f.index, v.index) for f in faces for v in f.verts]
    return [(centre.copy(), normal, keys)]


def extrude_along(bm, faces, curve_ob, matrix, divisions=1, taper=1.0, twist=0.0, local_translate_z=0.0,
                  thickness=0.0, keep_faces_together=True, unit=1.0, offset=0.0, direction=extrude.WORLD_X,
                  fallback=extrude.MAYA_Z):
    """Extrude ``faces`` (bmesh) along ``curve_ob``; ``matrix`` = the mesh object's world matrix. Returns the moved
    vertices; the end faces end up selected."""
    bm.normal_update()
    bm.verts.index_update()
    bm.faces.index_update()
    faces = [f for f in faces if f.is_valid]
    if not faces:
        return []
    groups = _groups(faces, keep_faces_together)
    inv = matrix.inverted_safe()
    n = max(1, int(divisions))
    first = {f: f.normal.copy() for f in faces}
    # like Maya, faces with no neighbours (a one-face plane) keep their original face as the bottom
    caps, levels, vectors = extrude.extrude_topology(bm, faces, n, keep_faces_together, direction, fallback,
                                                     keep_bottom=True)
    n = len(levels)
    points = [inv @ p for p in path_points(curve_ob, n)]
    member = []
    for centre, normal, keys in groups:
        wanted = set(keys)
        # vectors[key] = (base co, Thickness, Local Translate Z, Offset, ...) of the plain extrusion
        rows = [(k, v, vectors[key][0], vectors[key][3]) for k, found in enumerate(levels, 1)
                for key, v in found.items() if key in wanted and v.is_valid]
        member.append((centre, normal, rows))
    moved = place(member, points, n, taper, twist, local_translate_z, thickness, unit, offset)
    for v, co in moved.items():
        v.co = co
    bm.normal_update()
    bottoms = [f for f, nrm in first.items() if f.is_valid and f.normal.dot(nrm) > 0]
    if bottoms:              # the bottom faces away from the extrusion
        bmesh.ops.reverse_faces(bm, faces=bottoms)
    extrude.deselect_all(bm)
    for f in caps:
        if f.is_valid:
            f.select_set(True)
    bm.select_flush_mode()
    bm.normal_update()
    return list(moved)


def _edge_group(edges):
    """(centre, normal) of the edges before the extrusion: the mean of their midpoints and the summed normal of
    their faces (the mesh's Z when they have none or it cancels out)."""
    centre = sum(((e.verts[0].co + e.verts[1].co) * 0.5 for e in edges), Vector()) / len(edges)
    normal = sum((f.normal for e in edges for f in e.link_faces), Vector())
    normal = normal.normalized() if normal.length > 1e-9 else Vector((0.0, 0.0, 1.0))
    return centre.copy(), normal


def extrude_edges_along(bm, edges, curve_ob, matrix, divisions=1, taper=1.0, twist=0.0, local_translate_z=0.0,
                        thickness=0.0, keep_faces_together=True, unit=1.0, offset=0.0, **_unused):
    """Extrude ``edges`` (bmesh) along ``curve_ob`` (Maya polyExtrudeEdge with a curve); ``matrix`` = the mesh
    object's world matrix. Offset moves each new vertex out of the faces like the plain edge extrusion, x k / N and
    not turned with the path. Returns the new vertices; the outer edges end up selected."""
    from .extrude_edge_vertex import extrude_edges
    bm.normal_update()
    edges = [e for e in edges if e.is_valid]
    if not edges:
        return []
    centre, normal = _edge_group(edges)
    inv = matrix.inverted_safe()
    n = max(1, int(divisions))
    levels = {}
    # the plain extrusion with only Offset 1: each new vertex sits at its offset direction x k / N
    new = extrude_edges(bm, edges, offset=1.0, divisions=n, keep_faces_together=keep_faces_together, levels=levels)
    rows = []
    for v in new:
        k, src = levels[v]
        rows.append((k, v, src.co.copy(), (v.co - src.co) * (n / k)))
    points = [inv @ p for p in path_points(curve_ob, n)]
    moved = place([(centre, normal, rows)], points, n, taper, twist, local_translate_z, thickness, unit, offset,
                  thickness_along_normal=True)
    for v, co in moved.items():
        v.co = co
    bm.normal_update()
    return list(moved)


def _build_edges(bm, params, unit, ob=None):
    curve = bpy.data.objects.get(params.get("curve") or "")
    if curve is None or curve.type != 'CURVE' or not curve.data.splines or ob is None:
        return []
    edges = [e for e in bm.edges if e.select]
    values = {k: params[k] for k in FIELDS if k in params}
    return extrude_edges_along(bm, edges, curve, ob.matrix_world, unit=unit, **values)


def _build(bm, params, unit, ob=None):
    curve = bpy.data.objects.get(params.get("curve") or "")
    if curve is None or curve.type != 'CURVE' or not curve.data.splines or ob is None:
        return []
    faces = [f for f in bm.faces if f.select]
    values = {k: params[k] for k in FIELDS if k in params}
    return extrude_along(bm, faces, curve, ob.matrix_world, unit=unit, **values, **extrude.mesh_axes(ob))


SPEC = extrude.add_spec(extrude.Spec(
    'FACE_CURVE', "polyExtrudeFace", FIELDS, LABELS, DEFAULTS, KINDS, None, "extrude_curve_edit", _build,
    hidden=("curve",), with_object=True, component='FACE', view_fields=VIEW_FIELDS))
EDGE_SPEC = extrude.add_spec(extrude.Spec(
    'EDGE_CURVE', "polyExtrudeEdge", FIELDS, LABELS, DEFAULTS, KINDS, None, "extrude_curve_edit", _build_edges,
    hidden=("curve",), with_object=True, component='EDGE', view_fields=VIEW_FIELDS))


def run(context, ob, bm, curve_ob, unit=1.0, edges=False, **values):
    """Edit Mesh > Extrude of the selected faces (``edges``: edges) of ``ob`` along ``curve_ob``: a new history node
    with ``values`` (FIELDS; the rest default). Record or None."""
    params = dict(DEFAULTS, **{k: v for k, v in values.items() if k in FIELDS}, curve=curve_ob.name)
    params["divisions"] = max(1, int(params["divisions"]))
    return extrude.record_new(context, ob, bm, EDGE_SPEC if edges else SPEC, params, unit)


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_extrude_curve_edit(bpy.types.Operator):
    """Change the last extrusion along a curve (Maya: edit the polyExtrudeFace node). Blender keeps no edit-mode
    history, so only the last one can be changed"""
    bl_idname = "allset.extrude_curve_edit"
    bl_label = "polyExtrudeFace"
    bl_options = {'REGISTER', 'UNDO'}

    divisions: bpy.props.IntProperty(name="Divisions", default=1, min=1, soft_max=50, options={'SKIP_SAVE'})
    taper: bpy.props.FloatProperty(name="Taper", default=1.0, soft_min=0.0, soft_max=15.0, options={'SKIP_SAVE'})
    twist: bpy.props.FloatProperty(name="Twist", default=0.0, soft_min=-180.0, soft_max=180.0,
                                   options={'SKIP_SAVE'})
    local_translate_z: bpy.props.FloatProperty(name="Local Translate Z", default=0.0, options={'SKIP_SAVE'})
    offset: bpy.props.FloatProperty(name="Offset", default=0.0, options={'SKIP_SAVE'})
    thickness: bpy.props.FloatProperty(name="Thickness", default=0.0, options={'SKIP_SAVE'})
    keep_faces_together: bpy.props.BoolProperty(name="Keep Faces Together", default=True, options={'SKIP_SAVE'})
    curve: bpy.props.StringProperty(name="Curve", default="", options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}

    def _params(self, _spec=None):
        return {k: getattr(self, k) for k in (*FIELDS, "curve")}

    def execute(self, context):
        if context.mode == 'OBJECT':
            ok = extrude.edit_from_object_mode(context, "extrude_curve_edit", self._params)
            return {'FINISHED'} if ok else {'CANCELLED'}
        unit = extrude.units.maya_unit(context.scene)
        done = 0
        for ob in context.objects_in_mode_unique_data:
            rec = extrude.RECORDS.get(ob.name)
            if rec is not None and rec.spec in (SPEC, EDGE_SPEC) and rec.pre is not None and (
                    rec.live or extrude.current(ob) is not None):
                params = self._params()
                params["curve"] = params["curve"] or rec.params.get("curve", "")
                done += bool(extrude.run(ob, rec, params, unit))
        if not done:
            self.report({'WARNING'}, "No extrusion to change: " + extrude.NOTICE)
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (ALLSET_OT_extrude_curve_edit,)
