# SPDX-License-Identifier: GPL-3.0-or-later
"""UV projections: Maya UV > Automatic (``auto_project``: plane choice, shells and their packed layout, with
operators/autoproj_layout.py; ``allset.uv_automatic``) and its editable polyAutoProj node (the ``AUTOPROJ`` spec of
operators/extrude_spec.py, ``allset.uv_automatic_edit``), and UV > Contour Stretch (``allset.uv_contour``: Follow Active
Quads, then 0-1) and UV > Cylindrical / Spherical (``allset.uv_cylindrical`` / ``allset.uv_spherical``,
``round_project``). From object mode they act on every face of the selected meshes (``_ObjectFaces``); in the kit's
UV component mode on the picked UV faces only (``UVPickedFaces``).
"""

import math

import bmesh
import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty
from mathutils import Vector

from .. import compat, undo_steps
from . import units
from .uv_islands import _edit_meshes, _with_faces, restore_selection, selection_state


class UVPickedFaces:
    """Projections work on faces, like Maya. In the kit's UV component mode (UV Sync Selection off, the UV selection is
    what is picked) the faces are the picked UV faces: with only UVs / UV edges picked no face is projected. Meanwhile
    the mesh selection is those faces; afterwards it is put back. Elsewhere (UV Sync Selection, the 3D View outside UV
    mode, UV Shell picking) nothing changes."""

    def __init__(self, context):
        self.context = context
        self.saved = []

    def __enter__(self):
        context = self.context
        if context.mode != 'EDIT_MESH':
            return self
        from . import uv_shell_select
        from .uv_components import mesh_selection_wanted
        ts = context.scene.tool_settings
        if mesh_selection_wanted(context) or compat.uv_island_mode(ts) or uv_shell_select.active(context):
            return self
        face_mode = ts.uv_select_mode == 'FACE'
        for ob in _edit_meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            uv = bm.loops.layers.uv.active
            keep = [f for f in bm.faces if face_mode and uv is not None and f.select and not f.hide
                    and all(compat.uv_vert_selected(lp, uv) for lp in f.loops)]
            self.saved.append((ob, selection_state(bm)))
            for f in bm.faces:
                f.select_set(False)
            for f in keep:
                f.select_set(True)
            bmesh.update_edit_mesh(ob.data)
        return self

    def __exit__(self, *exc):
        for ob, state in self.saved:
            if ob.mode == 'EDIT':
                restore_selection(bmesh.from_edit_mesh(ob.data), state)
                bmesh.update_edit_mesh(ob.data)
        return False


# --- Automatic / Contour Stretch -------------------

def _maya_shells(faces, k_unit, optimize=True, planes=6):
    """Maya's own plane choice and shells (autoproj_layout.assign_planes, with Fewer pieces on) for one of
    the plane counts in ``autoproj_layout.PLANE_SETS``, fed with the faces in index order and the points in Maya
    axes and units (Blender (x, y, z) = Maya (x, -z, y)). Returns ``[(projector, faces)]``; a projector maps a Blender point to the plane's (u, v)."""
    from . import autoproj_layout
    faces = sorted(faces, key=lambda f: f.index)
    ids = {}
    for f in faces:
        for v in f.verts:
            ids.setdefault(v, len(ids))
    points = [(v.co.x * k_unit, v.co.z * k_unit, -v.co.y * k_unit) for v in ids]
    shells = autoproj_layout.assign_planes(points, [[ids[v] for v in f.verts] for f in faces], optimize=optimize,
                                           planes=planes)
    frames = autoproj_layout.PLANE_SETS[planes].frames
    out = []
    for plane, group in shells:
        _n, mu, mv = frames[plane]
        # Maya (x, y, z) of a Blender point = (x, z, -y): the frame vectors in Blender axes
        u = Vector((mu[0], -mu[2], mu[1])) * k_unit
        v = Vector((mv[0], -mv[2], mv[1])) * k_unit
        out.append(((lambda co, u=u, v=v: (co.dot(u), co.dot(v))), [faces[i] for i in group]))
    return out


def auto_project(bm, uv, faces, planes=6, spacing=0.2, unit=1.0, optimize=True):
    """Maya's UV > Automatic on ``faces`` (object space) with its start options: faces take their planes
    and form shells Maya's way for every Planes choice (``_maya_shells``: candidate planes within the plane count's
    angle, seeds by fewest candidates, flood fill that stops where a shell would overlap itself). Shells are laid out
    in 0-1 at one scale with ``spacing`` percent between them by Maya's packed "Into square"
    layout (operators/autoproj_layout.py). ``unit`` = Blender length of one Maya unit
    (``units.maya_unit``): Maya projects and packs in Maya units. Returns the shell count."""
    from . import autoproj_layout
    faces = [f for f in faces if not f.hide]
    k_unit = 1.0 / (unit or 1.0)
    planes = int(planes) if int(planes) in autoproj_layout.PLANE_SETS else 6
    shells = _maya_shells(faces, k_unit, optimize, planes)
    # Maya's shell order for the layout = ascending lowest face index
    shells.sort(key=lambda s: min(f.index for f in s[1]))
    flat = [{lp: proj(lp.vert.co) for g in group for lp in g.loops} for proj, group in shells]
    if not flat:
        return 0
    lay = autoproj_layout.layout([autoproj_layout.bbox_of(pts.values()) for pts in flat], max(0.0, spacing))
    for i, pts in enumerate(flat):
        for lp, (x, y) in pts.items():
            lp[uv].uv = lay.transform(i, x, y)
    return len(flat)


def fit_unit(loops, uv):
    """Stretch the UVs of ``loops`` to fill 0-1 (Maya Contour Stretch: a strip of faces fills the square)."""
    pts = [lp[uv].uv.copy() for lp in loops]
    if not pts:
        return
    x0, y0 = min(p.x for p in pts), min(p.y for p in pts)
    w = (max(p.x for p in pts) - x0) or 1.0
    h = (max(p.y for p in pts) - y0) or 1.0
    for lp, p in zip(loops, pts):
        lp[uv].uv = ((p.x - x0) / w, (p.y - y0) / h)


class _ObjectFaces:
    """From object mode: the selected meshes in edit mode with every face selected (Maya converts an object selection
    to its faces for UV projections), back to
    object mode afterwards. In edit mode: the meshes in edit mode (``UVPickedFaces`` meanwhile)."""

    def __init__(self, context):
        self.context = context
        self.entered = False
        self.picked = None

    def __enter__(self):
        context = self.context
        if context.mode == 'EDIT_MESH':
            self.picked = UVPickedFaces(context).__enter__()
            return [o for o in context.objects_in_mode_unique_data if o.type == 'MESH']
        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if not meshes:
            return []
        if context.view_layer.objects.active not in meshes:
            context.view_layer.objects.active = meshes[0]
        bpy.ops.object.mode_set(mode='EDIT')
        self.entered = True
        bpy.ops.mesh.select_mode(type='FACE')
        bpy.ops.mesh.select_all(action='SELECT')
        return [o for o in bpy.context.objects_in_mode_unique_data if o.type == 'MESH']

    def __exit__(self, *exc):
        if self.picked is not None:
            self.picked.__exit__(*exc)
        if self.entered:
            bpy.ops.object.mode_set(mode='OBJECT')
        return False


def _mesh_poll(context):
    if context.mode == 'EDIT_MESH':
        return True
    return context.mode == 'OBJECT' and any(o.type == 'MESH' for o in context.selected_objects)


PLANE_ITEMS = [(n, n, f"{n} projection planes") for n in ("3", "4", "5", "6", "8", "12")]


class ALLSET_OT_uv_automatic(bpy.types.Operator):
    """Project UVs from several planes at once (Maya UV > Automatic): the selected faces, or every face of the
    selected meshes in object mode"""
    bl_idname = "allset.uv_automatic"
    bl_label = "Automatic"
    bl_options = {'REGISTER', 'UNDO'}

    planes: EnumProperty(name="Planes", items=PLANE_ITEMS, default="6")
    spacing: FloatProperty(name="Percentage Space", default=0.2, min=0.0, max=5.0)

    poll = classmethod(lambda cls, context: _mesh_poll(context))

    def execute(self, context):
        n = 0
        from . import extrude
        unit = units.maya_unit(context.scene)
        params = dict(AUTOPROJ.defaults, planes=int(self.planes), percentage_space=self.spacing)
        made = []
        object_mode = context.mode == 'OBJECT'
        with _ObjectFaces(context) as obs:
            for ob in obs:
                bm = bmesh.from_edit_mesh(ob.data)
                if not any(f.select and not f.hide for f in bm.faces):
                    continue
                # the polyAutoProj history node (#150): Channel Box INPUTS / AE, editable values
                if extrude.record_new(context, ob, bm, AUTOPROJ, params, unit) is not None:
                    n += 1
                    made.append(ob)
        if object_mode:
            for ob in made:
                note_object_state(ob)
        if not n:
            self.report({'WARNING'}, "Select faces (or a mesh) to project.")
            return {'CANCELLED'}
        return {'FINISHED'}


# --- polyAutoProj history node (Issue #150) ------------------------------------------------
# Maya's UV > Automatic leaves a polyAutoProj node whose Channel Box INPUTS rows can be edited
# (Planes, Optimize, Layout, Percentage Space, Scale Mode, Layout Method
# after the projection's Translate / Rotate / Scale / Pivot). The kit's node shows the rows it rebuilds with
# (Planes, Optimize = 1 Fewer pieces / 0 Less distortion, Percentage Space); the others stay at their
# defaults (Into square, Uniform, Bounding box, no projection transform). Like the kit's extrude / bevel
# nodes it is the last kit operation on the mesh (operators/extrude_record.py records); a UV > Automatic run from object
# mode stays editable there while the mesh's UVs are the ones it made.

PLANE_COUNTS = (3, 4, 5, 6, 8, 12)


def _build_autoproj(bm, params, unit):
    faces = [f for f in bm.faces if f.select and not f.hide]
    if not faces:
        return []
    planes = min(PLANE_COUNTS, key=lambda n: abs(n - int(round(params["planes"]))))
    uv = bm.loops.layers.uv.verify()
    auto_project(bm, uv, faces, planes, max(0.0, params["percentage_space"]), unit,
                 optimize=int(round(params["optimize"])) >= 1)
    return list({v for f in faces for v in f.verts})


def _uv_state(me):
    import numpy as np
    layer = me.uv_layers.active
    if layer is None:
        return None
    a = np.empty(len(layer.data) * 2, dtype=np.float32)
    layer.data.foreach_get("uv", a)
    return (len(me.vertices), len(me.polygons), layer.name, hash(a.tobytes()))


def note_object_state(ob):
    """Remember the UVs a UV > Automatic left on ``ob`` (object mode): its node stays while they are unchanged."""
    from . import extrude
    rec = extrude.RECORDS.get(ob.name)
    if rec is not None and rec.spec is AUTOPROJ:
        rec.object_state = _uv_state(ob.data)


def object_state_ok(ob, rec):
    st = getattr(rec, "object_state", None)
    return st is not None and st == _uv_state(ob.data)


def _autoproj_spec():
    from . import extrude
    return extrude.add_spec(extrude.Spec(
        'AUTOPROJ', "polyAutoProj", ("planes", "optimize", "percentage_space"),
        {"planes": "Planes", "optimize": "Optimize", "percentage_space": "Percentage Space"},
        {"planes": 6, "optimize": 1.0, "percentage_space": 0.2},
        {"planes": "INT", "optimize": "NONE", "percentage_space": "NONE"},
        None, "uv_automatic_edit", _build_autoproj, in_view=False, object_check=object_state_ok,
        object_note=note_object_state, pre_uv=True))


AUTOPROJ = _autoproj_spec()


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_uv_automatic_edit(bpy.types.Operator):
    """Change the last UV > Automatic (Maya: edit the polyAutoProj node). Blender keeps no history, so only the
    last one can be changed"""
    bl_idname = "allset.uv_automatic_edit"
    bl_label = "polyAutoProj"
    bl_options = {'REGISTER', 'UNDO'}

    planes: IntProperty(name="Planes", default=6, min=3, max=12, options={'SKIP_SAVE'})
    optimize: FloatProperty(name="Optimize", default=1.0, min=0.0, max=1.0, options={'SKIP_SAVE'},
                            description="1 = Fewer pieces, 0 = Less distortion")
    percentage_space: FloatProperty(name="Percentage Space", default=0.2, min=0.0, max=5.0, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}

    def execute(self, context):
        from . import extrude
        unit = units.maya_unit(context.scene)
        params = {"planes": self.planes, "optimize": self.optimize, "percentage_space": self.percentage_space}
        if context.mode == 'EDIT_MESH':
            done = 0
            for ob in context.objects_in_mode_unique_data:
                rec = extrude.RECORDS.get(ob.name)
                if rec is not None and rec.spec is AUTOPROJ and rec.pre is not None and (
                        rec.live or extrude.current(ob) is not None):
                    done += bool(extrude.run(ob, rec, params, unit))
            return {'FINISHED'} if done else {'CANCELLED'}
        ob = context.active_object
        rec = extrude.object_record(ob)
        if rec is None or rec.spec is not AUTOPROJ:
            return {'CANCELLED'}
        sel = list(context.selected_objects)
        for o in sel:
            o.select_set(o == ob)
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            ok = extrude.run(ob, rec, params, unit)
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')
            for o in sel:
                o.select_set(True)
        note_object_state(ob)
        return {'FINISHED'} if ok else {'CANCELLED'}


# --- Cylindrical / Spherical (Issue #442) ------------------------------------------------------------
# Like Maya's UV > Cylindrical / Spherical: the projection sits on the centre of the selection's world bounding box,
# its axis is the scene's up axis and the 3D View's angle plays no part. Around the axis a half turn spans one UV
# tile (the projection's horizontal sweep), the front (Maya +Z = Blender -Y) in the middle of the tile. Cylindrical
# spans the tile's height over the selection's height; Spherical spans one tile over a quarter turn up or down (its
# vertical sweep), the equator in the middle.

HORIZONTAL_SWEEP = math.pi
VERTICAL_SWEEP = math.pi / 2


def round_project(faces, uv, matrix, spherical=False):
    """Cylindrical (or Spherical) UVs on ``faces`` from the world bounding box of their vertices. A face keeps its
    corners within half a turn of its own centre, so faces across the back seam stay whole."""
    faces = [f for f in faces if not f.hide]
    pts = {v: matrix @ v.co for f in faces for v in f.verts}
    if not pts:
        return 0
    lo = Vector([min(p[i] for p in pts.values()) for i in range(3)])
    hi = Vector([max(p[i] for p in pts.values()) for i in range(3)])
    c = (lo + hi) / 2
    height = hi.z - lo.z
    tiny = max((hi - lo).length, 1e-9) * 1e-6

    def angle(p):
        return math.atan2(p.x - c.x, c.y - p.y)       # 0 at the front, a quarter turn at +X

    for f in faces:
        corners = [pts[v] for v in f.verts]
        ref = angle(sum(corners, Vector()) / len(corners))
        for lp in f.loops:
            p = pts[lp.vert]
            r = math.hypot(p.x - c.x, p.y - c.y)
            phi = angle(p) if r > tiny else ref           # a point on the axis takes its face's angle
            phi += 2 * math.pi * math.floor((ref + math.pi - phi) / (2 * math.pi))
            if spherical:
                v = 0.5 + math.atan2(p.z - c.z, r) / VERTICAL_SWEEP
            else:
                v = 0.5 + (p.z - c.z) / height if height > tiny else 0.5
            lp[uv].uv = (0.5 + phi / HORIZONTAL_SWEEP, v)
    return len(faces)


class _RoundProjection:
    bl_options = {'REGISTER', 'UNDO'}
    spherical = False

    poll = classmethod(lambda cls, context: _mesh_poll(context))

    def execute(self, context):
        done = 0
        with _ObjectFaces(context) as obs:
            for ob in obs:
                bm = bmesh.from_edit_mesh(ob.data)
                faces = [f for f in bm.faces if f.select and not f.hide]
                if not faces:
                    continue
                uv = bm.loops.layers.uv.verify()
                done += bool(round_project(faces, uv, ob.matrix_world, self.spherical))
                bmesh.update_edit_mesh(ob.data)
        if not done:
            self.report({'WARNING'}, "Select faces (or a mesh) to project.")
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_uv_cylindrical(_RoundProjection, bpy.types.Operator):
    """Project UVs from a cylinder around the scene's up axis, centred on the selection (Maya UV > Cylindrical):
    the selected faces, or every face of the selected meshes in object mode"""
    bl_idname = "allset.uv_cylindrical"
    bl_label = "Cylindrical"


class ALLSET_OT_uv_spherical(_RoundProjection, bpy.types.Operator):
    """Project UVs from a sphere around the scene's up axis, centred on the selection (Maya UV > Spherical):
    the selected faces, or every face of the selected meshes in object mode"""
    bl_idname = "allset.uv_spherical"
    bl_label = "Spherical"
    spherical = True


class ALLSET_OT_uv_contour(bpy.types.Operator):
    """Lay the selected faces out along their quad grid and stretch them to fill 0-1 (Maya UV > Contour Stretch;
    Blender Follow Active Quads): every face of the selected meshes in object mode"""
    bl_idname = "allset.uv_contour"
    bl_label = "Contour Stretch"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(lambda cls, context: _mesh_poll(context))

    def execute(self, context):
        done = 0
        with _ObjectFaces(context) as obs:
            for ob in obs:
                bm = bmesh.from_edit_mesh(ob.data)
                uv = bm.loops.layers.uv.verify()
                faces = [f for f in bm.faces if f.select and not f.hide]
                quads = [f for f in faces if len(f.verts) == 4]
                if not quads:
                    continue
                if bm.faces.active not in quads:
                    bm.faces.active = quads[0]
                bmesh.update_edit_mesh(ob.data)
                with context.temp_override(active_object=ob, object=ob, edit_object=ob,
                                           objects_in_mode=[ob], objects_in_mode_unique_data=[ob]):
                    try:
                        _with_faces(context, ob, faces, lambda: bpy.ops.uv.follow_active_quads(mode='LENGTH_AVERAGE'))
                    except RuntimeError:
                        continue
                bm = bmesh.from_edit_mesh(ob.data)
                uv = bm.loops.layers.uv.verify()
                fit_unit([lp for f in bm.faces if f.select and not f.hide for lp in f.loops], uv)
                bmesh.update_edit_mesh(ob.data)
                done += 1
        if not done:
            self.report({'WARNING'}, "Select quad faces (or a mesh) for Contour Stretch.")
            return {'CANCELLED'}
        return {'FINISHED'}
