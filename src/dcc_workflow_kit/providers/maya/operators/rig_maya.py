# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Skeleton / Skin / Deform commands with Maya's results.

Reroot, Preferred Angle, IK Spline Handle; Hammer, Add / Remove
Influence, Remove Unused Influences; Cluster, Soft Mod (Nonlinear lives in ``menu_items``). A Maya joint is a
bone head (or a chain end's tail), skin = Armature modifier + vertex groups
named after the joints.

Code: ik_spline_handle (Create IK Spline Handle), skin_influences (Edit Influences, Hammer Skin Weights),
cluster_soft_mod (Cluster, Soft Modification); this module keeps Reroot Skeleton, Set / Assume Preferred Angle, the
classes tuple and re-exports.
"""

import math

import bpy
from bpy.props import BoolProperty
from mathutils import Matrix, Vector

from .. import results
from .joints import _InEditMode
from .ik_spline_handle import (SPLINE_RESOLUTION, SPLINE_SAMPLES, SPLINE_STATUS,  # noqa: F401
                               ALLSET_OT_ik_spline_handle, create_spline_ik, fit_cubic, fit_spans)
from .skin_influences import (DROPOFF_PROP, MAX_INFLUENCES, MAX_INFLUENCES_PROP,  # noqa: F401
                              ALLSET_OT_add_influence, ALLSET_OT_hammer_weights, ALLSET_OT_remove_influence,
                              ALLSET_OT_remove_unused_influences, _influence_groups, _joint_segments, add_influence,
                              hammer, maya_add_weights, normalize, remove_influence, unused_influences)
from .cluster_soft_mod import (SOFT_MOD_RADIUS, ALLSET_OT_cluster, ALLSET_OT_soft_mod,  # noqa: F401
                               _point_selection, control_points, cosine_falloff)

PREFERRED_PROP = "allset_preferred_angle"
PREFERRED_NOTE = ("Preferred angle stored: RP handles on 3+ bones start their solve from it like Maya; "
                  "2-bone chains bend from the rest pose (Blender's IK).")


def _cb():
    from ..ui import channel_box
    return channel_box


def _selected_bones(arm):
    cb = _cb()
    return [pb for pb in arm.pose.bones if cb.bone_selected(pb)]


def _armature(context):
    ob = context.active_object
    return ob if ob is not None and ob.type == 'ARMATURE' else None


# --- Reroot Skeleton ---------------------------------------------------------------------------

def reroot(arm, name):
    """Make the joint at the head of bone ``name`` the root: the bones on the way to the old root are reversed and
    re-parented (joint positions unchanged, Maya ``reroot``). Bone names stay. Returns False if already a root."""
    with _InEditMode(arm) as ebs:
        b = ebs[name]
        path, p = [], b.parent
        while p is not None:
            path.append(p)
            p = p.parent
        if not path:
            return False
        on_path = {eb.name for eb in path} | {b.name}
        others = {eb.name: [c.name for c in eb.children if c.name not in on_path] for eb in path}
        old_tail = {eb.name: eb.tail.copy() for eb in path}
        b.use_connect = False
        b.parent = None
        for eb in path:
            eb.use_connect = False
            eb.parent = None
        for eb in path:
            head, tail = eb.head.copy(), eb.tail.copy()
            eb.head, eb.tail = tail, head
        for i, eb in enumerate(path):
            if i > 0:
                eb.parent = path[i - 1]
                eb.use_connect = True
        # the other children of a path bone hang at its old tail = the previous reversed bone's tail
        for i, eb in enumerate(path):
            for cname in others[eb.name]:
                c = ebs[cname]
                at_tail = (c.head - old_tail[eb.name]).length < 1e-5
                if at_tail:
                    c.use_connect = False
                    c.parent = path[i - 1] if i > 0 else None
    return True


class ALLSET_OT_reroot_skeleton(bpy.types.Operator):
    """Make the selected joint the root of its skeleton (Maya Skeleton > Reroot Skeleton)"""
    bl_idname = "allset.reroot_skeleton"
    bl_label = "Reroot Skeleton"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        arm = _armature(context)
        act = arm.data.bones.active
        if act is None:
            self.report({'WARNING'}, "Select a joint")
            return {'CANCELLED'}
        if not reroot(arm, act.name):
            results.result(self, f"{act.name} is already a root")
        return {'FINISHED'}


# --- Set / Assume Preferred Angle -----------------------------------------------------------------

def _euler(pb):
    if pb.rotation_mode == 'QUATERNION':
        return pb.rotation_quaternion.to_euler()
    if pb.rotation_mode == 'AXIS_ANGLE':
        w, x, y, z = pb.rotation_axis_angle
        return Matrix.Rotation(w, 3, Vector((x, y, z))).to_euler()
    return pb.rotation_euler.copy()


def _set_euler(pb, e):
    if pb.rotation_mode == 'QUATERNION':
        pb.rotation_quaternion = e.to_quaternion()
    elif pb.rotation_mode == 'AXIS_ANGLE':
        axis, angle = e.to_quaternion().to_axis_angle()
        pb.rotation_axis_angle = (angle, *axis)
    else:
        pb.rotation_euler = e


def _with_children(bones):
    out = []
    for pb in bones:
        for b in (pb, *pb.children_recursive):
            if b not in out:
                out.append(b)
    return out


def set_preferred(bones, hierarchy=True):
    """Maya ``cmds.joint(edit=True, setPreferredAngles=True, children=True)``: preferredAngle = the current rotation, on
    the joints and their children (option window Options: Selected joint = ``hierarchy`` False, no ``children``)."""
    for pb in (_with_children(bones) if hierarchy else bones):
        pb[PREFERRED_PROP] = [math.degrees(a) for a in _euler(pb)]


def assume_preferred(bones, hierarchy=True):
    """Maya ``cmds.joint(edit=True, assumePreferredAngles=True, children=True)``: rotation = preferredAngle (joints
    without one keep their rotation)."""
    from mathutils import Euler
    for pb in (_with_children(bones) if hierarchy else bones):
        if PREFERRED_PROP in pb:
            d = pb[PREFERRED_PROP]
            _set_euler(pb, Euler([math.radians(a) for a in d], _euler(pb).order))


class _PoseBones:
    @classmethod
    def poll(cls, context):
        return _cb().pose_armature(context) is not None

    def bones(self, context):
        arm = _cb().pose_armature(context)
        bones = _selected_bones(arm) if arm else []
        if not bones and arm is not None:
            bones = [pb for pb in arm.pose.bones if pb.parent is None]   # Maya: the skeleton when no joint picked
        return bones


class ALLSET_OT_set_preferred_angle(_PoseBones, bpy.types.Operator):
    """Remember the selected joints' current rotation as their preferred angle (Maya Skeleton > Set Preferred
    Angle)"""
    bl_idname = "allset.set_preferred_angle"
    bl_label = "Set Preferred Angle"
    bl_options = {'REGISTER', 'UNDO'}

    hierarchy: BoolProperty(name="Hierarchy", default=True, options={'SKIP_SAVE', 'HIDDEN'})    # default like Maya

    def execute(self, context):
        set_preferred(self.bones(context), self.hierarchy)
        results.result(self, PREFERRED_NOTE)
        return {'FINISHED'}


class ALLSET_OT_assume_preferred_angle(_PoseBones, bpy.types.Operator):
    """Turn the selected joints back to their preferred angle (Maya Skeleton > Assume Preferred Angle)"""
    bl_idname = "allset.assume_preferred_angle"
    bl_label = "Assume Preferred Angle"
    bl_options = {'REGISTER', 'UNDO'}

    hierarchy: BoolProperty(name="Hierarchy", default=True, options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        assume_preferred(self.bones(context), self.hierarchy)
        return {'FINISHED'}


classes = (ALLSET_OT_reroot_skeleton, ALLSET_OT_set_preferred_angle, ALLSET_OT_assume_preferred_angle,
           ALLSET_OT_ik_spline_handle, ALLSET_OT_add_influence, ALLSET_OT_remove_influence,
           ALLSET_OT_remove_unused_influences, ALLSET_OT_hammer_weights, ALLSET_OT_cluster, ALLSET_OT_soft_mod)
