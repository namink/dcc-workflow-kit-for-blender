# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit Mesh > Extrude with faces and a curve selected: the faces extrude along the curve (Maya's polyExtrudeFace
with the curve as its path, the Extrude option box's Curve: Selected).

Like Maya: step k of ``Divisions`` N puts the faces' centre on the curve point at parameter k / N of the curve's
range (even in parameter, not in length), wherever the curve is in the world (it is not moved to the faces). Each
step turns the faces from their first direction straight onto the chord from the previous step's centre to this
one (the first chord starts at the faces' centre) and keeps their size. Taper scales step k by
1 - (1 - Taper) k / N, Twist turns it about its normal by Twist k / N degrees (right-handed). Local Translate Z adds
the faces' first normal x k / N, Thickness the last step's direction x k / N. Default Divisions 1: the faces go to
the curve's end at once. The node is editable afterwards like any kit extrusion (In-View Editor, Channel Box INPUTS).
"""

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import curves_math as cm
from .. import undo_steps
from . import curves_maya, extrude

FIELDS = ("divisions", "taper", "twist", "local_translate_z", "thickness", "keep_faces_together")
LABELS = {"divisions": "Divisions", "taper": "Taper", "twist": "Twist", "local_translate_z": "Local Translate Z",
          "thickness": "Thickness", "keep_faces_together": "Keep Faces Together"}
DEFAULTS = {"divisions": 1, "taper": 1.0, "twist": 0.0, "local_translate_z": 0.0, "thickness": 0.0,
            "keep_faces_together": True, "curve": ""}
KINDS = {"divisions": "INT", "taper": "NONE", "twist": "NONE", "local_translate_z": "NONE", "thickness": "NONE",
         "keep_faces_together": "BOOL"}


def path_curve(context):
    """The selected curve object that is not being edited (Maya: the curve selected with the faces), else None."""
    for ob in getattr(context, "selected_objects", ()) or ():
        if ob.type == 'CURVE' and ob.mode != 'EDIT' and ob.data.splines:
            return ob
    return None


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


def place(groups, points, divisions, taper=1.0, twist=0.0, ltz=0.0, thickness=0.0, unit=1.0):
    """Vertex positions along the path. ``groups`` = [(centre, unit normal, [(level k, vertex, base co)])] in mesh
    space; ``points`` = the path points for k = 1 .. divisions (mesh space). Returns {vertex: co}. Pure maths."""
    n = max(1, divisions)
    out = {}
    for centre, normal, members in groups:
        prev = centre
        turns, dirs = [], []
        for p in points:
            d = p - prev
            dirs.append(d.normalized() if d.length > 1e-12 else (dirs[-1] if dirs else normal))
            turns.append(_turn(normal, d) if d.length > 1e-12 else (turns[-1] if turns else Matrix.Identity(3)))
            prev = p
        last = dirs[-1] if dirs else normal
        for k, v, co in members:
            frac = k / n
            size = 1.0 - (1.0 - taper) * frac
            spin = Matrix.Rotation(twist * frac * 3.141592653589793 / 180.0, 3, normal)
            p = points[k - 1] + turns[k - 1] @ (spin @ ((co - centre) * size))
            out[v] = p + normal * (ltz * frac * unit) + last * (thickness * frac * unit)
    return out


def _groups(faces, together):
    """[(centre, normal, [vertex keys])] of the faces before the extrusion (one group, or one per face)."""
    sets = [faces] if together else [[f] for f in faces]
    out = []
    for fs in sets:
        verts = {v for f in fs for v in f.verts}
        centre = sum((v.co for v in verts), Vector()) / len(verts)
        normal = sum((f.normal for f in fs), Vector())
        normal = normal.normalized() if normal.length > 1e-9 else Vector((0.0, 0.0, 1.0))
        keys = [v.index for v in verts] if together else [(fs[0].index, v.index) for v in fs[0].verts]
        out.append((centre.copy(), normal, keys))
    return out


def extrude_along(bm, faces, curve_ob, matrix, divisions=1, taper=1.0, twist=0.0, local_translate_z=0.0,
                  thickness=0.0, keep_faces_together=True, unit=1.0, direction=extrude.WORLD_X,
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
        rows = [(k, v, vectors[key][0]) for k, found in enumerate(levels, 1)
                for key, v in found.items() if key in wanted and v.is_valid]
        member.append((centre, normal, rows))
    moved = place(member, points, n, taper, twist, local_translate_z, thickness, unit)
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


def _build(bm, params, unit, ob=None):
    curve = bpy.data.objects.get(params.get("curve") or "")
    if curve is None or curve.type != 'CURVE' or not curve.data.splines or ob is None:
        return []
    faces = [f for f in bm.faces if f.select]
    values = {k: params[k] for k in FIELDS if k in params}
    return extrude_along(bm, faces, curve, ob.matrix_world, unit=unit, **values, **extrude.mesh_axes(ob))


SPEC = extrude.add_spec(extrude.Spec(
    'FACE_CURVE', "polyExtrudeFace", FIELDS, LABELS, DEFAULTS, KINDS, None, "extrude_curve_edit", _build,
    hidden=("curve",), with_object=True, component='FACE'))


def run(context, ob, bm, curve_ob, divisions=1, unit=1.0):
    """Edit Mesh > Extrude of the selected faces of ``ob`` along ``curve_ob``: a new history node. Record or None."""
    params = dict(DEFAULTS, divisions=max(1, int(divisions)), curve=curve_ob.name)
    return extrude.record_new(context, ob, bm, SPEC, params, unit)


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_extrude_curve_edit(bpy.types.Operator):
    """Change the last extrusion along a curve (Maya: edit the polyExtrudeFace node). Blender keeps no edit-mode
    history, so only the last one can be changed"""
    bl_idname = "allset.extrude_curve_edit"
    bl_label = "polyExtrudeFace"
    bl_options = {'REGISTER', 'UNDO'}

    divisions: bpy.props.IntProperty(name="Divisions", default=1, min=1, soft_max=50, options={'SKIP_SAVE'})
    taper: bpy.props.FloatProperty(name="Taper", default=1.0, options={'SKIP_SAVE'})
    twist: bpy.props.FloatProperty(name="Twist", default=0.0, options={'SKIP_SAVE'})
    local_translate_z: bpy.props.FloatProperty(name="Local Translate Z", default=0.0, options={'SKIP_SAVE'})
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
            if rec is not None and rec.spec is SPEC and rec.pre is not None and (
                    rec.live or extrude.current(ob) is not None):
                params = self._params()
                params["curve"] = params["curve"] or rec.params.get("curve", "")
                done += bool(extrude.run(ob, rec, params, unit))
        if not done:
            self.report({'WARNING'}, "No extrusion to change: " + extrude.NOTICE)
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (ALLSET_OT_extrude_curve_edit,)
