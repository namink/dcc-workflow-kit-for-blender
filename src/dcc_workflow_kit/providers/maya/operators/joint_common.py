# SPDX-License-Identifier: GPL-3.0-or-later
"""Helpers every joint command shares: joint and skeleton names (the lowest free ``jointN`` over the scene,
``next_joint_name``, ``taken_joint_names``), Maya child order (``CHILD_ORDER`` stamps, ``child_order_key``,
``stamp_last``), an armature edit-mode block (``_InEditMode``) and the Channel Box accessor ``_cb``.
Used by joint_frames, joint_tool, joint_pick_walk and joints (which re-exports these names).
"""

import bpy

from . import naming


JOINT_BASE = "joint"
SKELETON_BASE = "skeleton"


def _cb():
    from ..ui import channel_box
    return channel_box


def taken_joint_names():
    """Joint names of the skeletons that still exist. Maya names are unique among existing nodes: a deleted
    skeleton frees ``joint1`` again (#73) — its armature data stays in ``bpy.data`` with no users until a purge,
    so only armatures an object still uses count."""
    names = set()
    for ob in bpy.data.objects:
        if ob.type != 'ARMATURE' or ob.users == 0:
            continue
        names.update(b.name for b in ob.data.bones)
        if ob.mode == 'EDIT':
            names.update(eb.name for eb in ob.data.edit_bones)
    return names


def next_joint_name(base=JOINT_BASE, extra=()):
    """Lowest free ``jointN`` over every armature (Maya numbers joints scene-wide)."""
    return f"{base}{naming.next_number(base, taken_joint_names() | set(extra))}"


class _InEditMode:
    """Run a block in armature edit mode and come back to the mode it started in."""

    def __init__(self, ob):
        self.ob, self.mode = ob, ob.mode

    def __enter__(self):
        if self.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
        return self.ob.data.edit_bones

    def __exit__(self, *exc):
        if self.mode != 'EDIT':
            bpy.ops.object.mode_set(mode=self.mode)


# Issue #165: Maya's pickWalk goes down to the first child and sideways through the siblings in the
# parent's child order, wrapping at the ends (SELECT_PICK: spine's children L_arm, R_arm,
# neck — L_arm left -> neck, neck right -> L_arm). Maya's child order = creation order, a re-parented node goes last.
# Blender keeps bones in creation order (``arm.bones``, the edit-bone list); the kit stamps ``CHILD_ORDER`` on a bone
# it re-parents (P, Connect / Remove / Disconnect / Insert Joint) with the armature's next number, so it sorts last.
CHILD_ORDER = "allset_child_order"


def child_order_key(bone):
    """Sort key of a bone (Bone or EditBone) among its siblings: Maya child order."""
    stamp = bone.get(CHILD_ORDER)
    if stamp is not None:
        return float(stamp)
    bones = bone.id_data.edit_bones if isinstance(bone, bpy.types.EditBone) else bone.id_data.bones
    try:
        return float(bones.find(bone.name))
    except (AttributeError, ReferenceError):
        return 0.0


def stamp_last(eb):
    """Mark edit bone / bone ``eb`` as its parent's newest child (Maya parent puts a re-parented node last)."""
    arm = eb.id_data
    bones = arm.edit_bones if arm.is_editmode else arm.bones
    used = [float(b.get(CHILD_ORDER)) for b in bones if b.get(CHILD_ORDER) is not None]
    eb[CHILD_ORDER] = max([len(bones)] + used) + 1.0
