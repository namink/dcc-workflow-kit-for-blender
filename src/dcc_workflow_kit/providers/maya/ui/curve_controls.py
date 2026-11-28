# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Show > NURBS Curves for rig controls drawn as bone custom shapes (Issue #173).

In the kit's model a Maya NURBS control is a bone with a curve custom shape. Blender draws a custom shape as part
of its armature, so the view's curve filter
(``SpaceView3D.show_object_viewport_curve``) hides curve *objects* only (NURBS Curves off, nothing selected: the
bone's circle is still drawn; the armature filter hides it with the joints). Blender has no
per-view switch for custom shapes, so the kit hides those bones (pose-bone hide, every view) and marks them; turning
NURBS Curves back on un-hides only marked bones, like Show > IK Handles (ui/panel_state.show_ik_handles).
"""

import bpy

from .. import compat

MARK = "allset_hidden_by_curves"
CURVE_TYPES = {'CURVE'}          # Maya NURBS Curves; SURFACE / mesh shapes belong to other Show rows


def is_curve_control(pb):
    shape = pb.custom_shape
    return shape is not None and shape.type in CURVE_TYPES


def controls(scene):
    """Pose bones of the scene's armatures whose custom shape is a curve."""
    out = []
    for ob in scene.objects:
        if ob is None or ob.type != 'ARMATURE' or ob.pose is None:
            continue
        out.extend(pb for pb in ob.pose.bones if is_curve_control(pb))
    return out


def show(scene, on):
    """Show (on) or hide the curve-shaped controls. Hiding marks the bones it hid; showing un-hides only those."""
    for pb in controls(scene):
        if on:
            if pb.get(MARK):
                compat.set_bone_hidden(pb, False)
                del pb[MARK]
        elif not compat.bone_hidden(pb):
            compat.set_bone_hidden(pb, True)
            pb[MARK] = True


def sync(space, scene):
    """Make the controls follow this view's NURBS Curves flag (call after a kit path changed it)."""
    flag = getattr(space, "show_object_viewport_curve", None)
    if flag is None or scene is None:
        return
    show(scene, flag)


def hidden_by_kit(scene):
    return any(pb.get(MARK) for pb in controls(scene))


# --- Show > Joints (Issue #451) ---------------------------------------------------------------------------------
# Maya: Joints off hides the joints only; a control's curve stays (it follows NURBS Curves). The view's armature
# filter hides whole armatures, controls included, so while the scene has shaped controls Joints off hides the plain
# joints (bones without a custom shape: pose-bone hide, every view, marked) and keeps the filter on.

JOINT_MARK = "allset_hidden_by_joints"
MARKS = (MARK, JOINT_MARK)       # hidden by a Show filter, not by the joint's own Visibility


def _bones(scene):
    for ob in scene.objects:
        if ob is not None and ob.type == 'ARMATURE' and ob.pose is not None:
            yield from ob.pose.bones


def has_shaped_controls(scene):
    return any(pb.custom_shape is not None for pb in _bones(scene))


def joints_hidden_by_kit(scene):
    return any(pb.get(JOINT_MARK) for pb in _bones(scene))


def joints_shown(space, scene):
    """Show > Joints is on in this view."""
    return bool(space.show_object_viewport_armature) and not (scene is not None and joints_hidden_by_kit(scene))


def show_joints(space, scene, on):
    """Show > Joints on / off in ``space``: the armature filter, or (a scene with shaped controls) the plain joints."""
    if on:
        space.show_object_viewport_armature = True
        if scene is not None:
            release_joints(scene)
    elif scene is not None and has_shaped_controls(scene):
        space.show_object_viewport_armature = True
        for pb in _bones(scene):
            if pb.custom_shape is None and not compat.bone_hidden(pb):
                compat.set_bone_hidden(pb, True)
                pb[JOINT_MARK] = True
    else:
        space.show_object_viewport_armature = False


def release_joints(scene):
    for pb in _bones(scene):
        if pb.get(JOINT_MARK):
            compat.set_bone_hidden(pb, False)
            del pb[JOINT_MARK]


def release_all():
    """Disable: show again every bone the kit hid (the user's own hidden bones stay)."""
    for scene in bpy.data.scenes:
        for pb in controls(scene):
            if pb.get(MARK):
                compat.set_bone_hidden(pb, False)
                del pb[MARK]
        release_joints(scene)
