# SPDX-License-Identifier: GPL-3.0-or-later
"""maya.cmds look-alike: ``joint`` (a bone of a kit skeleton named ``jointN`` scene-wide, under the selected joint or
in a new skeleton; -p / -r / -n / -rad, -q / -e) and the joint helpers the DAG commands use: getAttr on a joint
(``_joint_attr``), selecting and deleting joints. Joint lookup: cmds_rig_common.py; skeleton building:
operators/joint_tool.py; re-exported by cmds_rig.py."""

import bpy
from mathutils import Vector

from .cmds_shim import _Flags, _flatten, _selection, _view_layer, _to_bu, _from_bu, _from_rad, linear_factor
from .cmds_rig_common import (JOINT_RADIUS, JOINT_ORIENT, _KEY, _cb, _taken_names, _channel_values, find_joint,
                              joint_world, joint_local)


def _joint_attr(arm, bone, attr, time=None):
    """getAttr on a joint (translate / rotate / scale / radius / jointOrient / visibility)."""
    _view_layer()
    vals = _channel_values(arm, joint_local(arm, bone))
    comp = {"translate": "t", "t": "t", "rotate": "r", "r": "r", "scale": "s", "s": "s"}
    if attr in comp:
        return [tuple(vals[comp[attr] + a] for a in "xyz")]
    key = _KEY.get(attr, attr)
    if key in vals:
        return vals[key]
    if attr in ("radius", "rad"):
        return float(bone.get(JOINT_RADIUS, 1.0))
    if attr in ("jointOrient", "jo"):
        jo = bone.get(JOINT_ORIENT, (0.0, 0.0, 0.0))
        return [tuple(_from_rad(float(x)) for x in jo)]
    if attr in ("jointOrientX", "jox", "jointOrientY", "joy", "jointOrientZ", "joz"):
        jo = bone.get(JOINT_ORIENT, (0.0, 0.0, 0.0))
        return _from_rad(float(jo["XYZ".index(attr[-1].upper())]))
    if attr in ("visibility", "v"):
        return not bone.hide
    raise ValueError(f"No attribute '{attr}' on {bone.name}")


def _joint_name(name):
    from ..operators import joints, naming
    taken = _taken_names()
    if name:
        if name not in taken:
            return str(name)
        base = naming.base_name(str(name))
        return f"{base}{naming.next_number(base, taken)}"
    return joints.next_joint_name(extra=taken)


def _selected_joint(context):
    """(armature, bone name) of the selected (lead) joint, else None."""
    act = context.view_layer.objects.active
    if act is None or act.type != 'ARMATURE' or act.mode != 'POSE' or not act.select_get():
        return None
    cb = _cb()
    picked = [pb for pb in act.pose.bones if cb.bone_selected(pb)]
    if not picked:
        return None
    active = act.data.bones.active
    lead = next((pb for pb in picked if active is not None and pb.name == active.name), picked[-1])
    return act, lead.name


def _object_mode(context):
    act = context.view_layer.objects.active
    if act is not None and act.mode != 'OBJECT':
        with context.temp_override(active_object=act, object=act):
            bpy.ops.object.mode_set(mode='OBJECT')


def joint(*args, **kwargs):
    """``joint -p x y z`` = Skeleton > Create Joints for one click: a joint at the world position ``p`` under the
    selected joint (a new skeleton when no joint is selected; a selected transform becomes the new skeleton's parent,
    the joint keeping its world position). Maya names (joint1, -n tip), radius 1, jointOrient 0 0 0 (no auto orient);
    the new joint is the selection (pose mode). Returns its name (a string)."""
    from ..operators import joints, parenting
    f = _Flags("joint", kwargs)
    query = f.get("query", "q", False)
    edit = f.get("edit", "e", False)
    pos = f.get("position", "p")
    name = f.get("name", "n")
    rad = f.get("radius", "rad")
    relative = f.get("relative", "r", False)
    f.get("absolute", "a", False)
    f.get("zeroScaleOrient", "zso", False)
    f.get("scaleCompensate", "sc", True)
    f.done()
    context = bpy.context
    if query or edit:
        names = [str(n) for n in _flatten(args)]
        hit = find_joint(names[0]) if names else (lambda s: find_joint(s[1]) if s else None)(_selected_joint(context))
        if hit is None:
            raise RuntimeError("joint: no joint given")
        arm, bone = hit
        if query:
            if rad:
                return float(bone.get(JOINT_RADIUS, 1.0))
            if pos:
                _view_layer()
                return [_from_bu(x) for x in joint_world(arm, bone).translation]
            if name:
                return bone.name
            raise TypeError("joint -query needs -position, -radius or -name")
        if rad is not None:
            bone[JOINT_RADIUS] = float(rad)
        return None
    if args:
        raise TypeError("joint takes no objects (it works on the selection)")
    _view_layer()
    point = Vector([_to_bu(float(x)) for x in pos]) if pos is not None else Vector()
    picked = _selected_joint(context)
    under = None
    if picked is None:
        sel = _selection()
        if sel and sel[-1].type != 'ARMATURE':
            under = sel[-1]
    jname = _joint_name(name)
    if picked is not None:
        arm, parent = picked
        if relative:
            point = joint_world(arm, arm.data.bones[parent]).translation + point
        for o in [o for o in context.view_layer.objects if o is not None and o.select_get()]:
            if o is not arm:
                o.select_set(False)
        context.view_layer.objects.active = arm
        with context.temp_override(active_object=arm, object=arm):
            bpy.ops.object.mode_set(mode='EDIT')
    else:
        _object_mode(context)
        arm, parent = joints.new_skeleton(context), None
    ebs = arm.data.edit_bones
    # jointOrient 0 and rotate 0: the new joint's axes are its parent joint's (the world's for a root joint), and
    # the parent keeps its axes when its bone turns toward the new child
    from ..operators import joint_frames
    frame = joint_frames.maya_frame(arm, ebs[parent]).copy() if parent is not None else joint_frames.MAYA_WORLD
    made = joints.add_joint(arm, point, parent, length=linear_factor())
    if made == parent:                     # Maya makes a joint on its parent's position too
        eb = ebs.new(jname)
        eb.head = arm.matrix_world.inverted() @ point
        eb.tail = eb.head + Vector((0.0, 0.0, linear_factor()))
        eb.parent = ebs[parent]
    else:
        ebs[made].name = jname
    if parent is not None:
        joint_frames.set_maya_frame(arm, ebs[parent], frame)
    joint_frames.set_maya_frame(arm, ebs[jname], frame)
    with context.temp_override(active_object=arm, object=arm):
        joints.finish(context, arm, [jname])
    bone = arm.data.bones[jname]
    if rad is not None:
        bone[JOINT_RADIUS] = float(rad)
    bone[JOINT_ORIENT] = (0.0, 0.0, 0.0)
    if under is not None:
        _view_layer()
        parenting.set_parent_maya(arm, under)
    _view_layer()
    return jname


def _select_joints(names, add=False):
    context = bpy.context
    hits = [find_joint(n) for n in names]
    arm = hits[-1][0]
    act = context.view_layer.objects.active
    if act is not None and act is not arm and act.mode != 'OBJECT':
        _object_mode(context)
    if not add:
        for o in context.view_layer.objects:
            if o is not None and o is not arm and o.select_get():
                o.select_set(False)
    arm.select_set(True)
    context.view_layer.objects.active = arm
    if arm.mode != 'POSE':
        with context.temp_override(active_object=arm, object=arm):
            bpy.ops.object.mode_set(mode='POSE')
    cb = _cb()
    if not add:
        for pb in arm.pose.bones:
            cb.set_bone_selected(pb, False)
    for a, b in hits:
        if a is arm:
            cb.set_bone_selected(arm.pose.bones[b.name], True)
    arm.data.bones.active = hits[-1][1]


def _delete_joints(hits):
    context = bpy.context
    by_arm = {}
    for arm, bone in hits:
        by_arm.setdefault(arm, []).append(bone.name)
    for arm, names in by_arm.items():
        _object_mode(context)
        context.view_layer.objects.active = arm
        with context.temp_override(active_object=arm, object=arm):
            bpy.ops.object.mode_set(mode='EDIT')
            ebs = arm.data.edit_bones
            for n in names:
                eb = ebs.get(n)
                if eb is not None:
                    for b in [*eb.children_recursive, eb]:
                        ebs.remove(b)
            bpy.ops.object.mode_set(mode='OBJECT')
