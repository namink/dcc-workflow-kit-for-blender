# SPDX-License-Identifier: GPL-3.0-or-later
"""A Maya joint's frame on a Blender bone: the axis mapping (``JOINT_AXES``, ``MAYA_WORLD``), the Maya frame a bone
can't take (``MAYA_FRAME``: ``maya_frame``, ``set_maya_frame``, ``maya_frames``, ``fix_frames``), writing oriented
frames onto edit bones (``orient_bones``, ``set_bone_frame``), the Joint Tool's finishing orientation (``orient_new``)
and the joint radius (``RADIUS``, ``set_radius``). Orientation math: joint_orient.py; ``joints`` re-exports these names.
"""

import bpy
from mathutils import Matrix, Vector

from . import units
from .joint_common import _InEditMode


# A Maya joint's axes in its bone's axes: X = bone Y (down the chain), Y = bone Z, Z = bone X (rig_tools.local_axis);
# the kit's FBX writer uses the same mapping (file_io export_args primary 'X' / secondary 'Z').
JOINT_AXES = Matrix(((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
# Maya's world axes in Blender world coordinates (Maya X -> X, Y -> Z, Z -> -Y)
MAYA_WORLD = Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))
# A Maya joint frame a bone can't take: a Blender bone always points its Y at the child, a Maya joint's X need not.
# Such joints store their Maya frame relative to the bone's joint frame (``MAYA_FRAME``, quaternion in joint axes) and
# the FBX writer turns the joint by it (fbx_rig.rewrite). Two cases:
# - Orient Joint / Joint Tool (oj xyz, any sao) leave an END joint (no child joint) lined up with the world: joint3
#   jointOrient (0, 7.31, 0) after joint1 (0, 7.01, 0) and joint2 (0, -14.32, 0);
# - Mirror Joints Behavior: the copy's frame is -(reflection x source frame) — its X points back up the chain
#   (joint4 (-180, -7.01, 0), joint5 (0, -14.32, 0) with translate X -8.06), Orientation: the source's frame.
MAYA_FRAME = "allset_maya_frame"


def joint_frame(ob, eb):
    """World rotation of a Maya joint's axes for edit bone ``eb`` (as the bone allows)."""
    return (ob.matrix_world.to_3x3().normalized() @ eb.matrix.to_3x3().normalized()) @ JOINT_AXES


def maya_frame(ob, eb):
    """The joint's Maya frame (world rotation): the bone's joint frame turned by ``MAYA_FRAME``."""
    from mathutils import Quaternion
    q = eb.get(MAYA_FRAME)
    f = joint_frame(ob, eb)
    return f @ Quaternion(q).to_matrix() if q is not None and len(q) == 4 else f


def set_maya_frame(ob, eb, frame):
    """Store ``frame`` (world rotation) as the joint's Maya frame; nothing stored when the bone has it."""
    q = (joint_frame(ob, eb).inverted() @ frame).to_quaternion()
    if q.angle < 1e-7:
        if MAYA_FRAME in eb:
            del eb[MAYA_FRAME]
    else:
        eb[MAYA_FRAME] = list(q)


def store_end_orient(ob, ebs, names):
    """After an orient: joints with a child joint take the bone's frame, end joints Maya's world-aligned one."""
    for name in names:
        eb = ebs.get(name)
        if eb is not None:
            set_maya_frame(ob, eb, joint_frame(ob, eb) if eb.children else MAYA_WORLD)


def maya_frames(ob):
    """{bone name: rotation Matrix in joint axes} of the joints whose Maya frame differs from the bone's."""
    from mathutils import Quaternion
    out = {}
    for b in ob.data.bones:
        q = b.get(MAYA_FRAME)
        if q is not None and len(q) == 4:
            out[b.name] = Quaternion(q).to_matrix()
    return out


def orient_new(ob, names, secondary="Y", world="Y", sign="+", aos=True, to_world=False):
    """Orient the new joints the way Maya's Joint Tool does on finish (Joint Tool default: orientation xyz, secondary
    axis yup, auto orient secondary on): primary X, ``secondary`` Y /
    Z toward the Maya world axis ``world`` / ``sign`` (bend normal with ``aos``), "NONE" = Maya's traditional orient (no
    secondary axis), ``to_world`` = Orient Joint to World. Also writes Maya's variable bone radius. Returns the number of
    joints oriented."""
    if secondary == "X":
        raise RuntimeError("Secondary axis must differ from the primary axis (X)")
    oj = "none" if to_world else ("xzy" if secondary == "Z" else "xyz")
    sao = None if secondary == "NONE" else world.lower() + ("up" if sign == "+" else "down")
    done = {}
    with _InEditMode(ob) as ebs:
        n = orient_bones(ob, ebs, [nm for nm in names if nm in ebs], oj, sao, aos, result=done)
        set_radius(ebs, [nm for nm in names if nm in ebs])
    fix_frames(ob, done)
    return n


def maya_bone_frame(bone):
    """A bone's (Bone or EditBone) Maya frame in armature space: columns Maya X, Y, Z (bone axes, turned by
    ``MAYA_FRAME``)."""
    from mathutils import Quaternion
    m = bone.matrix if isinstance(bone, bpy.types.EditBone) else bone.matrix_local
    f = m.to_3x3().normalized() @ JOINT_AXES
    q = bone.get(MAYA_FRAME)
    return f @ Quaternion(q).to_matrix() if q is not None and len(q) == 4 else f


def armature_world(ob):
    """Maya's world axes in the armature's own space."""
    return ob.matrix_world.to_3x3().normalized().inverted() @ MAYA_WORLD


def _first_child(eb):
    kids = list(eb.children)
    return kids[0] if kids else None


def _rotated(ob, name):
    """Maya skips joints whose rotate isn't zero (1e-10)."""
    pb = ob.pose.bones.get(name) if ob.pose is not None else None
    return pb is not None and pb.matrix_basis.to_quaternion().angle > 1e-9


def fix_frames(ob, frames):
    """After edit mode: Blender rebuilds each bone's matrix through its parent chain in float32 (a few 1e-6 off on
    short bones); store the remainder against the intended Maya ``frames`` {name: frame} in ``MAYA_FRAME``
    of the Bone."""
    if ob.mode == 'EDIT':
        return
    for name, frame in frames.items():
        bone = ob.data.bones.get(name)
        if bone is None:
            continue
        base = bone.matrix_local.to_3x3().normalized() @ JOINT_AXES
        from .joint_edit import FRAME_TOL
        if max((base.col[i] - frame.col[i]).length for i in range(3)) < FRAME_TOL:   # not q.angle (float32)
            if MAYA_FRAME in bone:
                del bone[MAYA_FRAME]
        else:
            from .joint_edit import quat_between
            bone[MAYA_FRAME] = quat_between(base, frame)


def orient_bones(ob, ebs, names, oj="xyz", sao="yup", aos=True, skipped=None, result=None):
    """Write Maya orientJoint frames (operators/joint_orient.py) onto edit bones ``names``: the roll puts the bone's Z
    on Maya Y, and a frame the bone can't take (primary axis not X, an end joint) goes into ``MAYA_FRAME``. Rotated
    joints are skipped (``skipped`` gets (name, reason)). Returns the number oriented."""
    from . import joint_orient
    # Skin-bound joints are oriented too, without a warning. Maya then moves the skinned mesh (bindPreMatrix
    # kept); Blender's skin follows the new rest, so the kit's mesh stays (a kit difference).
    depth = {eb.name: len(eb.parent_recursive) for eb in ebs}
    order = sorted(names, key=lambda nm: depth.get(nm, 0))
    todo = []
    for nm in order:
        if _rotated(ob, nm):
            if skipped is not None:
                skipped.append((nm, "It has non-zero rotations."))
        else:
            todo.append(nm)
    pos = {eb.name: eb.head.copy() for eb in ebs}
    parent_of = {eb.name: (eb.parent.name if eb.parent is not None else None) for eb in ebs}
    first = {eb.name: (c.name if (c := _first_child(eb)) is not None else None) for eb in ebs}
    frames = {eb.name: maya_bone_frame(eb) for eb in ebs}
    old = {k: v.copy() for k, v in frames.items()}
    origin = ob.matrix_world.inverted() @ Vector((0.0, 0.0, 0.0))
    world = armature_world(ob)
    out = joint_orient.orient_frames(todo, pos, parent_of, first, frames, world, oj, sao, aos, origin)
    for nm, f in out.items():
        set_bone_frame(ebs[nm], f)
    # a skipped rotated joint keeps its jointOrient (Maya: jo / rotate unchanged), so it turns with a re-oriented parent
    for nm in order:
        par = parent_of.get(nm)
        if nm in out or par not in out:
            continue
        f = out[par] @ (old[par].transposed() @ old[nm])
        frames[nm] = out[nm] = f
        set_bone_frame(ebs[nm], f)
    if result is not None:
        result.update(out)
    return sum(1 for nm in out if nm in todo)


def set_bone_frame(eb, frame):
    """Give edit bone ``eb`` the Maya frame ``frame`` (armature space): roll its Z onto Maya Y (or the axis least along
    the bone), the rest into ``MAYA_FRAME``."""
    y = (eb.tail - eb.head).normalized()
    target = frame.col[1]
    if abs(y.dot(target)) > 0.999:
        target = frame.col[2] if abs(y.dot(frame.col[2])) < abs(y.dot(frame.col[0])) else frame.col[0]
    eb.align_roll(target)
    from .joint_edit import _set_local_frame
    _set_local_frame(eb, frame)


def set_radius(ebs, names, unit=None):
    """Maya Joint Tool variable bone radius (``allset_radius``, Maya units): from the distance to the first child,
    an end joint copies its parent's."""
    from . import joint_orient
    k = unit or units.maya_unit(bpy.context.scene)
    for nm in names:
        eb = ebs.get(nm)
        if eb is None:
            continue
        child = _first_child(eb)
        if child is not None:
            eb[RADIUS] = joint_orient.radius((child.head - eb.head).length / k)
        elif eb.parent is not None and RADIUS in eb.parent:
            eb[RADIUS] = eb.parent[RADIUS]
        else:
            eb[RADIUS] = 0.5


RADIUS = "allset_radius"


def _maya_axes(bone):
    """Maya joint axes in the bone's own coordinates (JOINT_AXES turned by ``MAYA_FRAME``)."""
    from mathutils import Quaternion
    q = bone.get(MAYA_FRAME)
    return JOINT_AXES @ Quaternion(q).to_matrix() if q is not None and len(q) == 4 else JOINT_AXES.copy()
