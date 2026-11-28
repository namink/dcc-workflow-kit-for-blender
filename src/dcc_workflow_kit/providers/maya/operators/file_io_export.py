# SPDX-License-Identifier: GPL-3.0-or-later
"""Writing a file with the Maya preset (``write``): Blender's writer runs with Maya's pre / post steps -- OBJ ``g``
lines, Alembic scaled around the writer (``_AbcMayaScale``), USD rewritten to Y up and Maya units
(``usd_maya_axes``), FBX rigs with joint orients and only the deforming joints (``rig_fbx_maya``), blend shapes kept
past other deformers. Used by the file dialog in file_io and by game_exporter.
"""

import math
import os

import bpy
from mathutils import Matrix

from .. import compat


MAYA_MPU = 0.01        # Maya's internal unit is cm: kit USD files carry Maya-unit numbers with metersPerUnit 0.01


def _write_obj_groups(path):
    """Maya's OBJ reader names objects after ``g`` lines and ignores ``o``: add ``g <name>`` after every
    ``o <name>`` Blender writes (otherwise a cube comes in as "Mesh")."""
    with open(path, encoding="utf-8", errors="surrogateescape") as fh:
        lines = fh.readlines()
    if any(line.startswith("g ") for line in lines):
        return
    out = []
    for line in lines:
        out.append(line)
        if line.startswith("o "):
            out.append("g " + line[2:])
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as fh:
        fh.writelines(out)


def _scale_group(s):
    """Geometry Nodes group that scales the geometry by ``s`` (temporary, Alembic export)."""
    ng = bpy.data.node_groups.new(".allset_export_scale", 'GeometryNodeTree')
    ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    gi, go = ng.nodes.new('NodeGroupInput'), ng.nodes.new('NodeGroupOutput')
    tr = ng.nodes.new('GeometryNodeTransform')
    tr.inputs["Scale"].default_value = (s, s, s)
    ng.links.new(gi.outputs[0], tr.inputs["Geometry"])
    ng.links.new(tr.outputs["Geometry"], go.inputs[0])
    return ng


def _abc_scalable(obs):
    for ob in obs:
        if ob.type not in ('MESH', 'EMPTY', 'CAMERA', 'LIGHT') or ob.constraints or ob.parent_type != 'OBJECT':
            return False
        if ob.library is not None:            # linked objects can't take the temporary changes
            return False
        ad = ob.animation_data
        if ad is not None and any(fc.data_path == "delta_scale" for fc in
                                  list(compat.id_fcurves(ob)) + list(ad.drivers)):
            return False                       # animated delta scale would undo the temporary one
        if any(m.type == 'ARMATURE' for m in ob.modifiers):
            return False
    return True


class _AbcMayaScale:
    """Blender's Alembic writer puts ``global_scale`` s on the root transforms (S M, Scale 100 in Maya). For
    the export only, every object gets delta scale 1/s and a last Geometry Nodes modifier scaling its mesh by
    s, and every parent inverse S PI: the world geometry is unchanged, the evaluated worlds are W S^-1, so the
    writer's roots become S W S^-1 and children (S PI) M S^-1 — Maya's numbers with Scale 1. Scenes it can't
    do exactly (armatures, constraints, curves ...) keep Blender's root scale."""

    def __init__(self, context, s):
        self.s = s
        self.obs = list(context.view_layer.objects)
        self.on = abs(s - 1.0) > 1e-9 and _abc_scalable(self.obs)
        self.saved, self.mods, self.group = [], [], None

    def __enter__(self):
        if not self.on:
            return self
        s = self.s
        self.group = _scale_group(s)
        smat = Matrix.Scale(s, 4)
        for ob in self.obs:
            self.saved.append((ob, ob.delta_scale.copy(), ob.matrix_parent_inverse.copy()))
            ob.delta_scale = ob.delta_scale / s
            if ob.parent is not None:
                ob.matrix_parent_inverse = smat @ ob.matrix_parent_inverse
            if ob.type == 'MESH':
                mod = ob.modifiers.new(".allset_export_scale", 'NODES')
                mod.node_group = self.group
                mod.show_in_editmode = False
                self.mods.append((ob, mod))
        return self

    def __exit__(self, *exc):
        for ob, mod in self.mods:
            ob.modifiers.remove(mod)
        for ob, ds, pi in self.saved:
            ob.delta_scale = ds
            ob.matrix_parent_inverse = pi
        if self.group is not None:
            bpy.data.node_groups.remove(self.group)
        return False


def usd_maya_axes(path, k):
    """Rewrite a Blender-written USD (Z up, BU) the Maya way: Y up, Maya units (metersPerUnit 0.01), every
    transform conjugated (C M C^-1, cameras / lights C M S^-1 so their view axis stays) and every point / normal
    converted. Returns False (file untouched) when pxr or the stage can't do it (skeletons, usdz)."""
    try:
        import numpy as np
        from pxr import Gf, Usd, UsdGeom, Vt
    except ImportError:
        return False
    if path.lower().endswith(".usdz"):
        return False
    stage = Usd.Stage.Open(path)
    if stage is None or any(p.GetTypeName().startswith("Skel") for p in stage.Traverse()):
        return False
    s = 1.0 / k
    axes = Matrix.Rotation(math.radians(-90.0), 4, 'X')
    conv = Matrix.Scale(s, 4) @ axes
    unscale = Matrix.Scale(s, 4)
    lin = np.array(conv.to_3x3(), dtype=np.float64)
    rot = np.array(axes.to_3x3(), dtype=np.float64)
    oriented = ("Camera", "DistantLight", "SphereLight", "RectLight", "DiskLight", "CylinderLight")

    def mat(gf):
        return Matrix([list(gf.GetRow(i)) for i in range(4)]).transposed()

    def samples(attr):
        times = attr.GetTimeSamples()
        return [(t, attr.Get(t)) for t in times] if times else [(Usd.TimeCode.Default(), attr.Get())]

    def convert_array(attr, m3):
        if not attr or not attr.HasAuthoredValue():
            return
        for t, val in samples(attr):
            if val is None or len(val) == 0:
                continue
            arr = np.array(val, dtype=np.float64) @ m3.T
            attr.Set(type(val).FromNumpy(arr.astype(np.float32)) if hasattr(type(val), "FromNumpy")
                     else Vt.Vec3fArray.FromNumpy(arr.astype(np.float32)), t)

    for prim in stage.Traverse():
        typ = prim.GetTypeName()
        if typ == "Xform" and prim.HasAttribute("faceVertexCounts"):
            # Blender 4.5 writes a merged transform + mesh as an Xform prim holding the mesh attributes (no
            # mesh in Maya or Blender): it is the mesh prim mayaUsd writes (Mesh "pCube1")
            prim.SetTypeName("Mesh")
            typ = "Mesh"
        if prim.IsA(UsdGeom.Xformable):
            xf = UsdGeom.Xformable(prim)
            ops = xf.GetOrderedXformOps()
            times = sorted({t for op in ops for t in op.GetAttr().GetTimeSamples()})
            codes = [Usd.TimeCode(t) for t in times] or [Usd.TimeCode.Default()]
            pre = unscale if prim.GetParent().GetTypeName() in oriented else conv
            post = unscale.inverted() if typ in oriented else conv.inverted()
            mats = [pre @ mat(xf.GetLocalTransformation(c)) @ post for c in codes]
            for op in ops:
                prim.RemoveProperty(op.GetName())
            xf.ClearXformOpOrder()
            t_op, r_op, s_op = xf.AddTranslateOp(), xf.AddRotateXYZOp(), xf.AddScaleOp()
            prev = None
            for c, m in zip(codes, mats):
                loc, quat, scl = m.decompose()
                eul = quat.to_euler('XYZ', prev) if prev is not None else quat.to_euler('XYZ')
                prev = eul
                t_op.Set(Gf.Vec3d(*loc), c)
                r_op.Set(Gf.Vec3f(*(math.degrees(a) for a in eul)), c)
                s_op.Set(Gf.Vec3f(*scl), c)
        if prim.IsA(UsdGeom.PointBased):
            pb = UsdGeom.PointBased(prim)
            convert_array(pb.GetPointsAttr(), lin)
            convert_array(pb.GetNormalsAttr(), rot)
            convert_array(pb.GetVelocitiesAttr(), lin)
            pv = UsdGeom.PrimvarsAPI(prim).GetPrimvar("normals")
            if pv:
                convert_array(pv.GetAttr(), rot)
            ext = pb.GetExtentAttr()
            if ext and ext.HasAuthoredValue():
                for t, pts in samples(pb.GetPointsAttr()):
                    if pts is not None and len(pts):
                        ext.Set(UsdGeom.PointBased.ComputeExtent(pts), t)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, MAYA_MPU)
    stage.GetRootLayer().Save()
    return True


def write(context, fmt, path, op, args, maya, k, deform_only=True, maya_names=True):
    """Run Blender's writer with the Maya preset's pre / post steps; an older kit material's Base Color is linked
    straight to its colour / texture while it writes (``material.diffuse_bypass``). FBX with the Maya
    preset: ``deform_only`` = only the deforming joints, hung on the deforming chain; ``maya_names`` = Maya-safe
    node names (operators/fbx_skeleton.py)."""
    from . import material
    with material.diffuse_bypass():
        _write(context, fmt, path, op, args, maya, k, (deform_only, maya_names))


class _BlendShapesKept:
    """Issue #144: Blender's FBX writer exports the EVALUATED mesh and drops its shape keys
    when any non-Armature modifier is on ($S/addons_core/io_scene_fbx/export_fbx_bin.py:2645-2690, 2773), so a mesh
    with a blend shape and a cluster / lattice / kit deformer lost every blend shape. Maya's FBX keeps the blendShape
    (and skinCluster) and leaves the other deformers out: while writing, those deformer modifiers of meshes with
    shape keys are switched off (restored afterwards)."""

    def __init__(self, obs):
        self.obs, self.saved = obs, []

    def __enter__(self):
        from .history import is_deformer
        for ob in self.obs:
            key = getattr(ob.data, "shape_keys", None) if ob.type == 'MESH' else None
            if key is None or len(key.key_blocks) < 2:
                continue
            for md in ob.modifiers:
                if md.type != 'ARMATURE' and is_deformer(md) and (md.show_viewport or md.show_render):
                    self.saved.append((md, md.show_viewport, md.show_render))
                    md.show_viewport = md.show_render = False
        return self

    def __exit__(self, *exc):
        for md, vp, rd in self.saved:
            md.show_viewport, md.show_render = vp, rd


def _write(context, fmt, path, op, args, maya, k, rig=(True, True)):
    if fmt == 'FBX' and maya:
        obs = context.selected_objects if args.get("use_selection") else list(context.view_layer.objects)
        with _BlendShapesKept([o for o in obs if o is not None]):
            return _write_one(context, fmt, path, op, args, maya, k, rig)
    return _write_one(context, fmt, path, op, args, maya, k, rig)


def _write_one(context, fmt, path, op, args, maya, k, rig=(True, True)):
    mod, name = op.split(".")
    run = getattr(getattr(bpy.ops, mod), name)
    if maya and fmt == 'ABC':
        with _AbcMayaScale(context, args.get("global_scale", 1.0)):
            run('EXEC_DEFAULT', filepath=path, **args)
        return
    run('EXEC_DEFAULT', filepath=path, **args)
    if not maya:
        return
    if fmt == 'FBX':
        rig_fbx_maya(context, path, run, args, deform_only=rig[0])
        from . import fbx_blend, fbx_rig
        if fbx_rig.modules() is not None:        # Maya's blendShape: in-betweens in their target's channel
            obs = context.selected_objects if args.get("use_selection") else list(context.view_layer.objects)
            fbx_blend.rewrite(path, [o for o in obs if o is not None and o.type == 'MESH'])
        if fbx_rig.modules() is not None:
            sc = context.scene
            fps = sc.render.fps / (sc.render.fps_base or 1.0)
            fbx_rig.set_time_span(path, sc.frame_start, sc.frame_end, fps)     # Maya's Time Slider range
            if rig[1]:
                from . import fbx_skeleton
                fbx_skeleton.rewrite_names(path)       # no FBXASC names in Maya
    elif fmt == 'OBJ':
        _write_obj_groups(path)
    elif fmt == 'USD' and not usd_maya_axes(path, k):
        # no pxr / skeletons / usdz: Blender's own conversion (it lands on the top prims' channels)
        run('EXEC_DEFAULT', filepath=path, **dict(args, convert_orientation=True,
                                                  export_global_forward_selection='NEGATIVE_Z',
                                                  export_global_up_selection='Y', convert_scene_units='CUSTOM',
                                                  meters_per_unit=k))


def _exported_armatures(context, args):
    obs = context.selected_objects if args.get("use_selection") else context.view_layer.objects
    return [ob for ob in obs if ob is not None and ob.type == 'ARMATURE']


def rig_fbx_maya(context, path, run, args, deform_only=True):
    """Joint orient as PreRotation, no armature Null (operators/fbx_rig.py). Needs a second export of the
    same objects at the rest pose (the writer's own conventions). ``deform_only``: only the
    deforming joints, on the deforming chain (``fbx_skeleton.deform_parents``). Returns (joints, nulls) or None."""
    from . import fbx_rig
    rigs = _exported_armatures(context, args)
    if not rigs or fbx_rig.modules() is None:
        return None
    saved = [(arm, arm.pose_position) for arm in {ob.data for ob in rigs}]
    # written beside the user's file and deleted at once (the kit writes nowhere the user didn't choose)
    rest = os.path.splitext(path)[0] + ".rest_pose.tmp.fbx"
    try:
        for arm, _pos in saved:
            arm.pose_position = 'REST'
        context.view_layer.update()
        run('EXEC_DEFAULT', filepath=rest, **dict(args, bake_anim=False))
    finally:
        for arm, pos in saved:
            arm.pose_position = pos
        context.view_layer.update()
    from .joints import maya_frames
    ends = {}
    for ob in rigs:
        ends.update(maya_frames(ob))
    parents = None
    if deform_only:
        from . import fbx_skeleton
        parents = {}
        for arm in {ob.data for ob in rigs}:          # armatures already on a deforming chain stay untouched
            own = fbx_skeleton.deform_parents(arm)
            if fbx_skeleton.changes_anything(own, arm):
                parents.update(own)
    try:
        return fbx_rig.rewrite(path, rest, ends, parents)
    finally:
        try:
            os.remove(rest)
        except OSError:
            pass
