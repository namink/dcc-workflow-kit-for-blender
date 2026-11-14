# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Edit > Duplicate (Ctrl+D), Duplicate with Transform (Shift+D), Duplicate Special (Ctrl+Shift+D) and Smart
Duplicate (Shift+drag on the manipulator) on picked joints.

Maya: duplicating a picked joint copies it with every joint below it, in place, under the same parent (a root joint's
copy is a new top joint); the top copy takes the next joint number, the copies keep their joint attributes and
display layers but no animation, and the copies of the picked joints are picked after. A joint picked below another
picked joint is copied with its parent's subtree, not twice.

- Duplicate with Transform: the first time a plain copy; after the copy is moved, rotated or scaled, the next one is a
  copy of it with the same change added again (joint4 -> joint5 -> joint6), and so on.
- Duplicate Special: Number of copies; Translate moves each copy in world space, Rotate turns it about the joint's
  orient axes (its frame before its own rotation), Scale scales it along its own axes, and each further copy adds the
  same change to the one before; Group under World makes the copies top joints that stay where they are.

``allset.duplicate`` / ``allset.duplicate_with_transform`` / ``allset.duplicate_special`` run this in Pose Mode and
joint Edit Mode. Here a picked joint is a bone picked in Pose Mode, or in Edit Mode with the Move tool
(``joint_selection``: the bone and its subtree are selected there, the head of a connected bone without its parent's
tail, so Blender's own Duplicate dropped the picked bone and copied its children only). Blender's Duplicate does the
copying (bone settings, bone collections, pose channels with their constraints, custom shapes and display layer) once
the selection is the subtrees of the topmost picked joints; the copies take their joints' current pose (Blender copies
the rest only), then get Maya joint names (Blender bone names are unique in a skeleton, so the copies below the top
one take the next numbers too) and the top copies sort last among their siblings, like a new node.

Where a copy goes: its pose channels take the place (as the joint's channels do in Maya), and on a skeleton the kit
edits in Edit Mode (unskinned, unanimated: the Move tool repositions its joints) the joint itself moves too, so Edit
Mode shows the copies where they stand. A top copy that leaves its parent's tip is disconnected (a Maya joint has no
connection). Duplicate with Transform repeats a change made in Edit Mode on the joint and a change made in Pose Mode
on its channels.
"""

import bpy
from mathutils import Euler, Matrix, Vector

from .. import compat

SOURCE = "allset_duplicate_of"      # temporary edit bone property: the source of a copy
EPS = 1e-6
# The last joint duplicates, for Duplicate with Transform: {(skeleton name, top copy name): source name}
PAIRS = {}
PARENT, WORLD = 'PARENT', 'WORLD'


def _picked(context):
    """{skeleton object: [picked joint names]} of the armatures in Pose / Edit Mode."""
    from . import joint_selection
    from ..ui.channel_box import bone_selected
    out = {}
    for ob in context.objects_in_mode_unique_data if context.mode in {'POSE', 'EDIT_ARMATURE'} else ():
        if ob.type != 'ARMATURE':
            continue
        if ob.mode == 'EDIT':
            names = [eb.name for eb in joint_selection._edit_picked(ob)]
        else:
            names = [pb.name for pb in ob.pose.bones if bone_selected(pb) and not compat.bone_hidden(pb)]
        if names:
            out[ob] = names
    return out


def any_picked(context):
    return bool(_picked(context))


def _tops(bones, names):
    """The picked joints with no picked joint above them, in bone order."""
    picked = set(names)
    out = []
    for n in names:
        b = bones.get(n)
        if b is None:
            continue
        p = b.parent
        while p is not None and p.name not in picked:
            p = p.parent
        if p is None:
            out.append(n)
    return out


def _depth(bone):
    n, p = 0, bone.parent
    while p is not None:
        n, p = n + 1, p.parent
    return n


def _select_subtrees(ob, tops):
    """Edit Mode selection Blender's Duplicate copies exactly: the subtrees of ``tops``; a connected top also needs
    its parent's tail (that end point is the top's head), its parent itself stays unselected."""
    ebs = ob.data.edit_bones
    for eb in ebs:
        eb.select = eb.select_head = eb.select_tail = False
    for n in tops:
        top = ebs[n]
        for b in (top, *top.children_recursive):
            b.select = b.select_head = b.select_tail = True
        if top.use_connect and top.parent is not None:
            top.parent.select_tail = True


POSE_CHANNELS = ("rotation_mode", "location", "rotation_quaternion", "rotation_euler", "rotation_axis_angle", "scale")


def _copy_pose(sources):
    """The copies stand where their joints stand now: their channels take the sources' current values (the keys
    stay with the sources, like Maya). Works in Edit Mode too: Blender's Duplicate makes the copies' pose channels
    right away."""
    for ob, pairs in sources.items():
        pbs = ob.pose.bones
        for copy, src in pairs.items():
            a, b = pbs.get(src), pbs.get(copy)
            if a is None or b is None:
                continue
            for prop in POSE_CHANNELS:
                setattr(b, prop, getattr(a, prop))


def _copy(context, picked, count):
    """In Edit Mode: ``count`` copies of the subtrees of the topmost picked joints, named the Maya way (each copy in
    turn, parents first). Returns ({skeleton: [(k, top source, top copy)]}, {skeleton: {copy: source}},
    {skeleton: [copies of the picked joints]})."""
    from . import joints
    active = context.view_layer.objects.active
    for ob in picked:
        for eb in ob.data.edit_bones:
            eb[SOURCE] = eb.name
    taken = set()
    tops_made, sources, made = {}, {}, {}
    for k in range(1, count + 1):
        before = {}
        for ob, names in picked.items():
            ebs = ob.data.edit_bones
            _select_subtrees(ob, _tops(ebs, names))
            before[ob] = {eb.name for eb in ebs}
        with context.temp_override(active_object=active, edit_object=active):
            bpy.ops.armature.duplicate()
        for ob, names in picked.items():
            ebs = ob.data.edit_bones
            new = [eb for eb in ebs if eb.name not in before[ob]]
            tops = set(_tops(ebs, names))
            copy_of = {}
            # Maya names in creation order: each top copy, then the copies below it, parents first
            for eb in sorted(new, key=lambda eb: (_depth(eb), ebs.find(eb.name))):
                name = joints.next_joint_name(extra=taken)
                taken.add(name)
                src = eb.get(SOURCE)
                eb.name = name
                copy_of[src] = name
                sources.setdefault(ob, {})[name] = src
                if src in tops:
                    joints.stamp_last(eb)              # a new node: last among its siblings
                    tops_made.setdefault(ob, []).append((k, src, name))
            made.setdefault(ob, []).extend(copy_of[n] for n in names if n in copy_of)
    for ob in picked:
        for eb in ob.data.edit_bones:
            if SOURCE in eb:
                del eb[SOURCE]
    return tops_made, sources, made


# --- where the copies go -----------------------------------------------------------------------------------------

def _close(a, b, eps=EPS):
    return all(abs(a[i][j] - b[i][j]) <= eps for i in range(4) for j in range(4))


def _parents_first(eb):
    out, todo = [], [eb]
    while todo:
        b = todo.pop(0)
        out.append(b)
        todo.extend(b.children)
    return out


def _rigid(m):
    loc, rot, _scale = m.decompose()
    return Matrix.Translation(loc) @ rot.to_matrix().to_4x4()


def _move_rest(eb, rest):
    """Put edit bone ``eb`` at armature-space matrix ``rest`` (its length kept); the joints below it go along. The
    new places are worked out first: moving a bone's tip moves the head of a connected child with it."""
    x = _rigid(rest) @ eb.matrix.inverted_safe()
    for b, m, length in [(b, x @ b.matrix, b.length) for b in _parents_first(eb)]:
        b.matrix = m
        b.length = length


def _set_basis(pb, basis):
    """Pose channels from a basis matrix, in the bone's rotation mode (an Euler keeps turning the same way)."""
    loc, rot, sca = basis.decompose()
    pb.location = loc
    mode = pb.rotation_mode
    if mode == 'QUATERNION':
        if rot.dot(pb.rotation_quaternion) < 0.0:
            rot.negate()
        pb.rotation_quaternion = rot
    elif mode == 'AXIS_ANGLE':
        axis, angle = rot.to_axis_angle()
        pb.rotation_axis_angle = (angle, *axis)
    else:
        pb.rotation_euler = rot.to_euler(mode, pb.rotation_euler)
    pb.scale = sca


def _posed(obs):
    """{skeleton: {bone: posed matrix (armature space)}}: where the joints stand now."""
    return {ob: {pb.name: pb.matrix.copy() for pb in ob.pose.bones} for ob in obs}


def _place(context, tops, place, under, posed=None):
    """In Pose Mode with the copies made: move each top copy to ``place(ob, k, source, copy, posed[ob])`` = (posed
    matrix or None, rest matrix or None), both armature space; ``under`` WORLD makes the top copies top joints where
    they stand. ``posed``: where the joints stood before Duplicate (a mode switch evaluates the animation again, and
    the copies stand where the joints were seen). Ends in Pose Mode."""
    context.view_layer.update()
    if posed is None:
        posed = _posed(tops)
    plan = []
    for ob, items in tops.items():
        for k, src, copy in items:
            target, rest = place(ob, k, src, copy, posed[ob]) if place is not None else (None, None)
            now = posed[ob][src]                        # a copy stands where its joint stood
            if target is None and under == WORLD:
                target = now
            if target is not None or rest is not None or under == WORLD:
                plan.append((ob, copy, target, rest, now))
    if not plan:
        return
    bpy.ops.object.mode_set(mode='EDIT')
    for ob, copy, target, rest, now in plan:
        eb = ob.data.edit_bones[copy]
        if under == WORLD:
            eb.use_connect = False
            eb.parent = None
        old = eb.matrix.copy()
        leaves = ((rest is not None and (rest.translation - old.translation).length > EPS)
                  or (target is not None and (target.translation - now.translation).length > EPS))
        if leaves:
            eb.use_connect = False                     # it leaves its parent's tip
        if rest is not None and not _close(rest, old):
            rest = _rigid(rest)
            if not leaves:
                rest.translation = old.translation      # a turn about the joint keeps a connected joint on its tip
            _move_rest(eb, rest)
    bpy.ops.object.mode_set(mode='POSE')
    context.view_layer.update()
    dg = context.evaluated_depsgraph_get()
    for ob, copy, target, _rest, _now in plan:
        if target is None:
            continue
        ev = ob.evaluated_get(dg)
        basis = ev.convert_space(pose_bone=ev.pose.bones[copy], matrix=target, from_space='POSE', to_space='LOCAL')
        _set_basis(ob.pose.bones[copy], basis)
    context.view_layer.update()


def with_transform_place(ob, _k, src, _copy, posed):
    """Duplicate with Transform: the copy of ``src`` (the last copy) takes the change between ``src`` and the joint
    it was copied from once more — on its joint (rest) and on its channels (pose); none: in place."""
    source = PAIRS.get((ob.name, src))
    bones = ob.data.bones
    if source is None or source == src or source not in posed or src not in posed:
        return None, None
    pc, ps = posed[src], posed[source]
    target = pc @ ps.inverted_safe() @ pc
    rc, rs = bones[src].matrix_local, bones[source].matrix_local
    rest = rc @ rs.inverted_safe() @ rc
    return (None if _close(target, pc) else target), (None if _close(rest, rc) else rest)


def offsets_place(translate, rotate, scale, under=PARENT):
    """Duplicate Special offsets: the k-th copy = the source moved by ``translate`` (world space), turned by
    ``rotate`` about the joint (Euler X, Y, Z about the joint's orient axes: its frame before its own rotation) and
    scaled by ``scale`` along its own axes, k times over. ``translate`` / ``rotate`` / ``scale`` are the operator's:
    Maya X / Y / Z as X / -Z / Y (``translate``, world space), X / -Z / Y (``rotate``) and X / Z / Y (``scale``).
    A joint's Maya X / Y / Z are its bone's Y / Z / X (``joints.JOINT_AXES``, turned by a stored Maya frame)."""
    from mathutils import Quaternion
    from .joint_selection import joint_mode
    from .joints import JOINT_AXES, MAYA_FRAME
    turn = Euler((rotate[0], rotate[2], -rotate[1]), 'XYZ').to_matrix()     # Maya X, then Y, then Z
    bone_scale = Vector((scale[1], scale[0], scale[2]))
    plain = (Vector(translate).length < EPS and turn.to_quaternion().angle < EPS
             and (bone_scale - Vector((1.0, 1.0, 1.0))).length < EPS)

    def place(ob, k, src, _copy, posed):
        if plain:
            return None, None
        bone = ob.data.bones[src]
        ps = posed[src]
        parent = bone.parent
        # the parent's pose as a change of its rest: the joint's orient axes go with it
        q = (posed[parent.name] @ parent.matrix_local.inverted_safe()) if parent else Matrix.Identity(4)
        axes = (q @ bone.matrix_local).to_3x3().normalized() @ JOINT_AXES
        frame = bone.get(MAYA_FRAME)
        if frame is not None and len(frame) == 4:
            axes = axes @ Quaternion(frame).to_matrix()
        head = ps.translation
        move = ob.matrix_world.to_3x3().inverted_safe() @ Vector(translate)
        d = (Matrix.Translation(move + head) @ (axes @ turn @ axes.inverted_safe()).to_4x4()
             @ Matrix.Translation(-head))
        dk = Matrix.Identity(4)
        for _i in range(k):
            dk = d @ dk
        sk = Matrix.Diagonal((*(s ** k for s in bone_scale), 1.0))
        target = dk @ ps @ sk
        rest = None
        if joint_mode(ob) == 'EDIT':
            # the joint moves too; under a posed parent, the parent's pose is taken out of the change first
            rest = dk @ q @ bone.matrix_local
            if under != WORLD:
                rest = q.inverted_safe() @ rest
        return target, rest
    return place


def duplicate(context, count=1, place=None, under=PARENT):
    """Maya Duplicate of the picked joints, ``count`` copies each; ``place`` / ``under`` see ``_place`` (None /
    PARENT: in place under the same parent). Returns the names of the copies of the picked joints (empty: nothing
    picked); they are picked after. One copy each: Duplicate with Transform repeats from these pairs."""
    from . import joint_selection
    picked = _picked(context)
    if not picked:
        return []
    start = context.mode
    posed = None
    if start != 'EDIT_ARMATURE':
        if place is not None or under != PARENT:
            context.view_layer.update()
            posed = _posed(picked)
        bpy.ops.object.mode_set(mode='EDIT')         # every armature in Pose Mode goes with the active one
    tops, sources, made = _copy(context, picked, max(1, count))
    _copy_pose(sources)
    if place is not None or under != PARENT:
        bpy.ops.object.mode_set(mode='POSE')
        _place(context, tops, place, under, posed)
        if start == 'EDIT_ARMATURE':
            bpy.ops.object.mode_set(mode='EDIT')
    elif start != 'EDIT_ARMATURE':
        bpy.ops.object.mode_set(mode='POSE')
    PAIRS.clear()
    if count == 1:
        PAIRS.update({(ob.name, copy): src for ob, items in tops.items() for _k, src, copy in items})
    if start == 'EDIT_ARMATURE':
        for ob, copies in made.items():
            ebs = ob.data.edit_bones
            for eb in ebs:
                eb.select = eb.select_head = eb.select_tail = False
            for n in copies:
                joint_selection._pick_shape(ebs[n], True, False)
            if copies:
                ebs.active = ebs[copies[-1]]
        joint_selection.sync_joint_pivot(context)
    else:
        from ..ui.channel_box import set_bone_selected
        for ob, copies in made.items():
            for pb in ob.pose.bones:
                set_bone_selected(pb, pb.name in copies)
            if copies:
                ob.data.bones.active = ob.data.bones[copies[-1]]
    from ..ui import layer_joints
    layer_joints.bump()
    return [n for copies in made.values() for n in copies]


def duplicate_with_transform(context):
    """Maya Duplicate with Transform (Shift+D) on the picked joints."""
    return duplicate(context, place=with_transform_place)
