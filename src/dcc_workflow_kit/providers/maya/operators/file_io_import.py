# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya channels and names on what an import with the Maya preset made: the reader's axis / unit conversion moves
from the channels into the geometry (``bake_conversion``; Transform Cache constraints become keys), name clashes
count up like Maya's (``maya_names``, ``maya_free_name``, ``shape_name``), FBX skin weights are renormalised and an
animated FBX sets the Time Slider. Entry point ``after_import``, called by the file dialog in file_io.
"""

import math
import os
import re

import bpy
from mathutils import Matrix


# --- the conversion goes into the geometry, not onto the channels ----------------------------
#
# Maya reads its transforms' channels straight from the file, so a Y-up / cm conversion written as a root
# rotation or scale shows as Rotate X -90 / Scale 100 in Maya and Blender's readers
# leave the reverse on the kit's channels. The kit instead conjugates: a transform M becomes C M C^-1 and
# geometry p becomes C p (C = axes x units), so channels read the same numbers in both programs (the kit's
# Z-up axes: Maya translate (1, 2, 3) = kit (1, -3, 2), rotate Y = kit rotate Z).

_SUFFIX = re.compile(r"^(.*)\.\d{3}$")
_TRAIL = re.compile(r"^(.*?)(\d*)$")
SCOPE_NAMES = ("Looks", "_materials", "materials", "mtl")      # USD material scopes (mayaUsd / Blender)


def shape_name(name):
    """Maya's shape name for transform ``name``: pCube1 -> pCubeShape1, box -> boxShape (same rule as
    ui/input_line.shape_name)."""
    m = _TRAIL.match(name)
    return f"{m.group(1)}Shape{m.group(2)}" if m.group(1) and m.group(2) else f"{name}Shape"


def maya_free_name(name, used):
    """Maya's name for an imported node whose name is taken: the trailing number goes up (pCube1 -> pCube2);
    ``name`` may carry Blender's ``.001`` clash suffix."""
    m = _SUFFIX.match(name)
    base = m.group(1) if m else name
    if base not in used:
        return base
    stem, num = _TRAIL.match(base).groups()
    n = int(num) + 1 if num else 1
    while f"{stem}{n}" in used:
        n += 1
    return f"{stem}{n}"


def _axis_matrix(up_y):
    """File axes -> kit axes: Y up becomes Z up (rotate X 90), as Blender's readers do."""
    return Matrix.Rotation(math.radians(90.0), 4, 'X') if up_y else Matrix.Identity(4)


def _parents_first(obs):
    obs = list(obs)
    rank = {}

    def depth(ob):
        if ob not in rank:
            rank[ob] = 0 if ob.parent is None else depth(ob.parent) + 1
        return rank[ob]
    return sorted(obs, key=depth)


def _bakeable(ob):
    """Objects whose data can take the conversion (others keep the reader's world matrix)."""
    if ob.type == 'EMPTY':
        return True
    if ob.type not in ('MESH', 'CURVE') or ob.data is None:
        return False
    if any(m.type in ('MESH_SEQUENCE_CACHE', 'ARMATURE') for m in ob.modifiers):
        return False
    return "transform" in ob.data.bl_rna.functions


def bake_conversion(context, obs, conv):
    """Move the reader's conversion ``conv`` (object world = true world @ conv) from the channels of the
    imported objects ``obs`` into their geometry. Transform Cache constraints (animated Alembic / USD) become
    keys on every frame of the scene range (the reader sets it to the file's), so the Channel Box shows Maya's
    numbers; cameras and lights only lose the unit scale (their local axes keep the reader's orientation)."""
    scene = context.scene
    obs = _parents_first(obs)
    if not obs:
        return
    scale = conv.to_scale()[0]
    unscale = Matrix.Scale(1.0 / scale, 4)
    conv_inv = conv.inverted_safe()
    users = {}
    for ob in obs:
        if ob.data is not None:
            users.setdefault(ob.data, []).append(ob)
    bake = {ob for ob in obs if _bakeable(ob)}
    for data, owners in users.items():          # data shared with an object that can't bake: leave all
        if data.users != len(owners) or not all(o in bake for o in owners):
            bake.difference_update(owners)
    cached = [ob for ob in obs if any(c.type == 'TRANSFORM_CACHE' for c in ob.constraints)]
    animated = any(ob in bake or ob.type in ('CAMERA', 'LIGHT') for ob in cached)
    frames = list(range(scene.frame_start, scene.frame_end + 1)) if animated else [scene.frame_current]
    keep_frame = scene.frame_current
    worlds = {ob: [] for ob in obs}
    for f in frames:
        if len(frames) > 1:
            scene.frame_set(f)
        for ob in obs:
            worlds[ob].append(ob.matrix_world.copy())
    if len(frames) > 1:
        scene.frame_set(keep_frame)
    target = {}
    for ob in obs:
        if ob in bake:
            target[ob] = [w @ conv_inv for w in worlds[ob]]
        elif ob.type in ('CAMERA', 'LIGHT'):
            target[ob] = [w @ unscale for w in worlds[ob]]
    caches = set()
    for ob in target:
        for con in [c for c in ob.constraints if c.type == 'TRANSFORM_CACHE']:
            caches.add(con.cache_file)
            ob.constraints.remove(con)
    for cache in caches:
        if cache is not None and cache.users == 0:
            bpy.data.batch_remove([cache])       # (CacheFile has no remove())
    for data in {ob.data for ob in bake if ob.data is not None}:
        if isinstance(data, bpy.types.Mesh):
            data.transform(conv, shape_keys=True)
        else:
            data.transform(conv)
    for ob in bake:
        if ob.type == 'EMPTY':
            ob.empty_display_size *= scale
    for ob in obs:
        if ob not in target:
            continue
        par = ob.parent
        locals_ = []
        for i, w in enumerate(target[ob]):
            pw = target[par][i] if par in target else (worlds[par][i] if par in worlds else
                                                         (par.matrix_world if par else Matrix.Identity(4)))
            locals_.append(pw.inverted_safe() @ w)
        ob.matrix_parent_inverse = Matrix.Identity(4)
        static = all(_close(m, locals_[0]) for m in locals_[1:])
        if static:
            ob.matrix_basis = locals_[0]
            continue
        _key_matrices(ob, frames, locals_)


def _close(a, b, eps=1e-6):
    return all(abs(a[i][j] - b[i][j]) < eps for i in range(4) for j in range(4))


def _key_matrices(ob, frames, mats):
    """Keys on location / rotation / scale at ``frames`` holding the local matrices ``mats``."""
    rot_path = {'QUATERNION': "rotation_quaternion", 'AXIS_ANGLE': "rotation_axis_angle"}.get(
        ob.rotation_mode, "rotation_euler")
    prev = None
    for f, m in zip(frames, mats):
        loc, quat, scl = m.decompose()
        ob.location, ob.scale = loc, scl
        if rot_path == "rotation_euler":
            eul = quat.to_euler(ob.rotation_mode, prev) if prev is not None else quat.to_euler(ob.rotation_mode)
            ob.rotation_euler = prev = eul
        elif rot_path == "rotation_quaternion":
            ob.rotation_quaternion = quat
        else:
            axis, angle = quat.to_axis_angle()
            ob.rotation_axis_angle = (angle, *axis)
        for path in ("location", rot_path, "scale"):
            ob.keyframe_insert(path, frame=f)


def maya_names(obs, materials, path):
    """Maya's names for what an import made: clashes count up (pCube1.001 -> pCube2), shapes are <transform>Shape
    (Maya FBX / OBJ / USD files name meshes "Mesh", after the file or after the transform). Materials keep
    Blender's names (Material.001)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    used = {o.name for o in bpy.data.objects}
    for ob in obs:
        if _SUFFIX.match(ob.name):
            used.discard(ob.name)
            ob.name = maya_free_name(ob.name, used)
            used.add(ob.name)
    used_data = {d.name for coll in (bpy.data.meshes, bpy.data.curves) for d in coll}
    for ob in obs:
        data = ob.data
        if ob.type not in ('MESH', 'CURVE', 'SURFACE') or data is None or data.users != 1:
            continue
        base = _SUFFIX.match(data.name).group(1) if _SUFFIX.match(data.name) else data.name
        if base in (ob.name, "Mesh", stem, "") or _SUFFIX.match(data.name):
            want = shape_name(ob.name) if base in (ob.name, "Mesh", stem, "") else base
            used_data.discard(data.name)
            data.name = want if want not in used_data else maya_free_name(want, used_data)
            used_data.add(data.name)


def _usd_stage_info(path):
    """(up axis is Y, metersPerUnit, Scope prim names) of a USD file; None without pxr."""
    try:
        from pxr import Usd, UsdGeom
    except ImportError:
        return None
    stage = Usd.Stage.Open(path)
    if stage is None:
        return None
    scopes = {p.GetName() for p in stage.Traverse() if p.GetTypeName() == "Scope"}
    return UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y, UsdGeom.GetStageMetersPerUnit(stage), scopes


def after_import(context, fmt, path, obs, materials, args):
    """Maya channels and names on what a Maya-preset import made (``obs`` = the new objects)."""
    if fmt == 'OBJ':
        # OBJ has no transforms: the reader's whole matrix is the conversion
        for ob in obs:
            if ob.parent is None and _bakeable(ob):
                bake_conversion(context, [ob], ob.matrix_world.copy())
    elif fmt == 'ABC':
        # Blender's Alembic reader turns Y up into Z up itself; only the scale stays on the channels
        bake_conversion(context, obs, Matrix.Scale(args.get("scale", 1.0), 4))
    elif fmt == 'USD':
        info = _usd_stage_info(path)
        if info is not None:
            up_y, mpu, scopes = info
            c = args.get("scale", 1.0) * (mpu if args.get("apply_unit_conversion_scale", True) else 1.0)
            for ob in [o for o in obs if o.type == 'EMPTY' and o.name.split(".")[0] in scopes | set(SCOPE_NAMES)
                       and not o.children]:
                obs.remove(ob)
                bpy.data.objects.remove(ob)
            bake_conversion(context, obs, _axis_matrix(up_y) @ Matrix.Scale(c, 4))
    elif fmt == 'FBX':
        # rigs: Maya's curves / Euler rotations / skeleton without the conversion node (L12)
        # (a rig file is read without bake_space_transform, see execute: the reader would shrink skinned meshes)
        from . import fbx_rig_import, joints, naming
        done, conv = set(), None
        for arm in [o for o in obs if o.type == 'ARMATURE']:
            res = fbx_rig_import.fix_armature(context, arm, path)
            if res is None or "conversion" not in res:
                continue
            done.add(arm)
            done.update(res["meshes"])
            conv = res["conversion"]
            if arm.name.startswith("Armature"):
                naming.apply_maya_name(arm, joints.SKELETON_BASE, rename_data=False)
        if conv is not None and not args.get("bake_space_transform", False):
            rest = [o for o in obs if o not in done and o.parent not in done]
            if rest:
                bake_conversion(context, rest, conv)
        if not done:
            _file_time_slider(context, path, obs)
        for ob in obs:
            normalise_skin_weights(ob)
    maya_names(obs, materials, path)


def normalise_skin_weights(ob, eps=1e-6):
    """#189: Maya's FBX export leaves out skin weights of 0.001 or less without scaling the rest, and
    Maya's FBX import renormalises each vertex's weights to sum 1 (its skin cluster normalises). Blender's reader
    keeps the file values, so the Component Editor / Paint Skin Weights / a later export showed up to 0.0016 less.
    Divide every vertex's joint weights (groups named after a bone of the mesh's Armature modifiers) by their sum;
    other vertex groups stay. Positions don't change: the Armature modifier divides by the sum while it deforms.
    Returns the number of vertices changed."""
    if ob is None or ob.type != 'MESH':
        return 0
    bones = set()
    for md in ob.modifiers:
        if md.type == 'ARMATURE' and md.object is not None and md.object.type == 'ARMATURE':
            bones.update(b.name for b in md.object.data.bones)
    joints = {vg.index for vg in ob.vertex_groups if vg.name in bones}
    if not joints:
        return 0
    changed = 0
    for v in ob.data.vertices:
        els = [g for g in v.groups if g.group in joints]
        s = sum(g.weight for g in els)
        if s > 0.0 and abs(s - 1.0) > eps:
            for g in els:
                g.weight = g.weight / s
            changed += 1
    if changed:
        ob.data.update()
    return changed


def _file_time_slider(context, path, obs):
    """#146: an animated FBX without a skeleton sets the Time Slider to the file's range too —
    Maya's FBXImport does even with Fill Timeline off; Blender's reader
    leaves the scene's range (0-250). Rigs get it in fbx_rig_import.fix_armature."""
    if not any(o.animation_data is not None and o.animation_data.action is not None for o in obs):
        return None
    from . import fbx_rig, fbx_rig_import
    if fbx_rig.modules() is None:
        return None
    scene = context.scene
    tree, _v = fbx_rig.load(path)
    span = fbx_rig_import.time_span(tree, fbx_rig_import.file_fps(tree, scene))
    if span is None:
        return None
    scene.frame_start, scene.frame_end = span
    if scene.use_preview_range:
        scene.frame_preview_start, scene.frame_preview_end = span
    scene.frame_set(max(span[0], min(scene.frame_current, span[1])))
    return span
