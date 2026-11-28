# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya joints: Joint Tool, Orient Joint, Mirror Joints, joint pick-walk and P / Shift+P.

Maya rigging (a Maya joint = a bone of one armature per
skeleton, ``skeleton1`` / ``joint1``, rotate order XYZ, Blender's bone Y points at the child).
A Maya joint is a point and a Blender bone a segment, so N clicks make N
bones: bone K runs from click K to click K+1, the last (Maya's end joint) gets a short tail along the
previous segment.

Code: joint_common (names, child order, edit-mode block), joint_frames (Maya joint frames, radius),
joint_tool (Joint Tool), joint_pick_walk (arrow-key pick walk); this module keeps Orient Joint, Mirror Joints,
P / Shift+P and freeing location-constrained joints, and re-exports the other modules' names.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from mathutils import Matrix, Vector

from .. import results
from . import naming, scene_axes
from .joint_common import (_cb, CHILD_ORDER, child_order_key, _InEditMode, JOINT_BASE, next_joint_name, SKELETON_BASE,
                           stamp_last, taken_joint_names)  # noqa: F401
from .joint_frames import (armature_world, _first_child, fix_frames, JOINT_AXES, joint_frame, _maya_axes,
                           maya_bone_frame, MAYA_FRAME, maya_frame, maya_frames, MAYA_WORLD, orient_bones, orient_new,
                           RADIUS, _rotated, set_bone_frame, set_maya_frame, set_radius, store_end_orient)  # noqa: F401
from .joint_tool import (add_joint, ALLSET_OT_joint_tool, BRANCH_MIN_PX, click_point, finish, JOINT_SPHERE,
                         joint_sphere_radius, move_joint, new_skeleton, pick_branch_joint, SECONDARY_AXES, STATUS,
                         view_under, WORLD_AXES)  # noqa: F401
from .joint_pick_walk import (ALLSET_OT_pick_walk_joint, _by_name, collection_hidden, CONTROLLER, controller_children,
                              CONTROLLER_PARENT, controller_parent, _controller_walk, _dag_walk, has_controllers,
                              is_rigify_rig, _mapped_walk, _RIGIFY_MAPS, rigify_parents, _skip_hidden_pref,
                              _split_variant, _twin_names, _VARIANT_RE, _VARIANTS, visible_ancestor, visible_below,
                              _visible_walk, walk_bone, _with_variant, _wrap)  # noqa: F401

AXIS_NOTE = ("Blender joints point their Y axis at the child joint; a Maya frame with another primary axis is "
             "kept with the joint (exported to FBX).")


# Issue #142: Blender ignores every location constraint on a CONNECTED bone (its head is glued to the
# parent's tail; 4.5: Copy Location / Child Of / Copy Transforms / Limit Location leave it in place, rotation
# constraints work), while a Maya joint's translate is free: Constrain > Point / Parent on a child joint moves it.
# The joint that gets such a constraint is disconnected (only that bone — Joint Tool chains stay connected,
# so moving a joint in edit mode still drags the chain); it stays where it is (rest pose unchanged) and the bone is
# marked ``FREED``. Undo brings the connection back with the constraint.
LOCATION_CONSTRAINTS = frozenset({'COPY_LOCATION', 'CHILD_OF', 'COPY_TRANSFORMS', 'LIMIT_LOCATION', 'LIMIT_DISTANCE',
                                  'SHRINKWRAP', 'FOLLOW_PATH', 'CLAMP_TO', 'FLOOR', 'TRANSFORM', 'PIVOT'})
FREED = "allset_freed_connect"


def location_constrained(arm):
    """Names of the connected bones of ``arm`` that carry a location constraint."""
    out = []
    for b in arm.data.bones:
        if not b.use_connect:
            continue
        pb = arm.pose.bones.get(b.name)
        if pb is not None and any(c.type in LOCATION_CONSTRAINTS and c.enabled for c in pb.constraints):
            out.append(b.name)
    return out


def free_location_constrained(context, arm):
    """Disconnect the bones Blender would hold at the parent's tail despite a location constraint; returns them."""
    names = location_constrained(arm)
    if not names:
        return []
    vl = context.view_layer
    prev = vl.objects.active
    vl.objects.active = arm
    try:
        with _InEditMode(arm) as ebs:
            for name in names:
                eb = ebs.get(name)
                if eb is not None:
                    eb.use_connect = False
                    eb[FREED] = True
    finally:
        vl.objects.active = prev
    return names


# --- edit-mode helpers ------------------------------------------------------------------------

def _armature(context):
    ob = context.active_object
    return ob if ob is not None and ob.type == 'ARMATURE' and ob.mode in {'POSE', 'EDIT'} else None


def selected_joint_names(ob):
    """The joints the user picked. In Edit mode (the Move tool) a picked joint selects its whole subtree
    so W carries the children: the Skeleton menu / P act on the picked joints only, like Maya's selection (
    clicking joint1 then P / Mirror / Orient saw joint1's children as picked too)."""
    if ob.mode == 'EDIT':
        from .joint_selection import _edit_picked
        picked = [eb.name for eb in _edit_picked(ob)]
        return picked or [eb.name for eb in ob.data.edit_bones if eb.select]
    cb = _cb()
    return [pb.name for pb in ob.pose.bones if cb.bone_selected(pb)]


def active_joint_name(ob):
    if ob.mode == 'EDIT':
        act = ob.data.edit_bones.active
    else:
        act = ob.data.bones.active
    return act.name if act is not None else None


def with_descendants(ebs, names):
    out = []
    for name in names:
        eb = ebs.get(name)
        if eb is None:
            continue
        for b in [eb, *eb.children_recursive]:
            if b.name not in out:
                out.append(b.name)
    return out


# --- Orient Joint ---------------------------------------------------------------------------

# Secondary Axis World Orientation (scene axes, like the Channel Box; Z+ = up) -> Blender calculate_roll type
SAO_ROLL = {"X+": 'GLOBAL_POS_X', "X-": 'GLOBAL_NEG_X', "Y+": 'GLOBAL_POS_Y', "Y-": 'GLOBAL_NEG_Y',
            "Z+": 'GLOBAL_POS_Z', "Z-": 'GLOBAL_NEG_Z'}
_AXES = [(a, a, "") for a in ("X", "Y", "Z")]


def orient(ob, names, sao, children=True, oj="xyz", aos=True, skipped=None):
    """Maya Skeleton > Orient Joint (``cmds.joint(edit=True, oj=oj, sao=sao, aos=..., ch=True, zso=True)``; default xyz
    / yup / aos on / children on): ``sao`` "X+" .. "Z-" (scene axes, "Z+" = up), "NONE" = no
    secondary world axis (Maya's traditional orient), ``oj`` "none" = Orient Joint to World. Rotated / skinned joints
    are skipped (``skipped``). Returns the number oriented."""
    if oj != "none" and sao not in SAO_ROLL and sao != "NONE":
        return 0
    if sao == "NONE":
        maya_sao = None
    else:
        axis, sign = scene_axes.signed_to_yup(sao[0], sao[1])     # the orientation maths works Y up
        maya_sao = axis.lower() + ("up" if sign == "+" else "down")
    done = {}
    with _InEditMode(ob) as ebs:
        targets = with_descendants(ebs, names) if children else [n for n in names if n in ebs]
        n = orient_bones(ob, ebs, targets, oj, maya_sao, aos, skipped, done) if targets else 0
    fix_frames(ob, done)
    return n


def _load_options(op, key, names):
    """The values last used (like Maya's saved options): Blender doesn't remember properties of operators run from Python."""
    from .option_windows import saved
    for name, value in (saved("op_" + key) or {}).items():
        if name in names:
            try:
                setattr(op, name, value)
            except (TypeError, ValueError):
                pass


def _save_options(op, key, names):
    from .option_windows import store
    store("op_" + key, {name: getattr(op, name) for name in names})


class ALLSET_OT_orient_joint(bpy.types.Operator):
    """Maya Orient Joint: orient the joints from their positions (primary axis down the chain, secondary axis by the
    bend or a world direction)"""
    bl_idname = "allset.orient_joint"
    bl_label = "Orient Joint Options"
    bl_options = {'UNDO'}

    to_world: BoolProperty(name="Orient Joint to World", default=False)
    primary: EnumProperty(name="Primary Axis", items=_AXES, default="X")
    secondary: EnumProperty(name="Secondary Axis", items=_AXES, default="Y")
    world: EnumProperty(name="Secondary Axis World Orientation",
                        items=[(k, k, "") for k in SAO_ROLL] + [("NONE", "None", "No secondary axis world "
                                                                 "orientation: Maya's orient from the bend alone")],
                        default="Z+")
    auto_secondary: BoolProperty(name="Auto orient secondary axis", default=True,
                                 description="Maya 2025+: the secondary axis follows the bend of the chain, turned "
                                             "toward the world orientation")
    children: BoolProperty(name="Orient Children of Joint", default=True)
    option_box: BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})

    OPTIONS = ("to_world", "primary", "secondary", "world", "auto_secondary", "children")

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def invoke(self, context, event):
        # Maya: a plain menu click runs with the saved options, the option box opens the window (the
        # dialog on every click kept the keyboard until closed). Blender keeps the last values.
        if self.option_box:
            return context.window_manager.invoke_props_dialog(self, width=360, confirm_text="Orient")
        _load_options(self, "orient_joint", self.OPTIONS)
        return self.execute(context)

    def draw(self, context):
        lay = self.layout
        lay.prop(self, "to_world")
        col = lay.column()
        col.enabled = not self.to_world
        col.prop(self, "primary")
        col.prop(self, "secondary")
        col.prop(self, "world")
        col.prop(self, "auto_secondary")
        lay.prop(self, "children")

    def execute(self, context):
        ob = _armature(context)
        names = selected_joint_names(ob)
        if not names:
            self.report({'WARNING'}, "Select joints to orient")
            return {'CANCELLED'}
        if not self.to_world and self.primary == self.secondary:
            self.report({'ERROR'}, "Secondary axis must differ from the primary axis")
            return {'CANCELLED'}
        _save_options(self, "orient_joint", self.OPTIONS)
        oj = "none" if self.to_world else (self.primary + self.secondary
                                           + ({"X", "Y", "Z"} - {self.primary, self.secondary}).pop()).lower()
        skipped = []
        orient(ob, names, self.world, self.children, oj, self.auto_secondary, skipped)
        for name, why in skipped:
            self.report({'WARNING'}, f"Skipping {name}: {why}")     # Maya's warning
        if skipped:
            # Maya ends with this one, naming the first rotated joint up the hierarchy
            self.report({'WARNING'}, f"Cannot perform joint orientation. Transform {skipped[0][0]} has non-zero "
                                     "rotations.")
        # Maya 2026 prints only the command echo (joint -e -oj xyz -sao yup -aos -ch -zso;), no result line
        # (Maya): the result field is cleared
        results.result(self, "")
        return {'FINISHED'}


# --- Mirror Joints ----------------------------------------------------------------------------

# mirror plane (scene axes, like the Channel Box) -> reflection: YZ flips x, XZ flips y (front / back), XY flips z
PLANES = {"XY": (1.0, 1.0, -1.0), "YZ": (-1.0, 1.0, 1.0), "XZ": (1.0, -1.0, 1.0)}


def mirrored_name(name, search, replace, taken):
    new = name.replace(search, replace) if search and search in name else name
    if new == name or new in taken:
        base = naming.base_name(new)
        new = f"{base}{naming.next_number(base, taken)}"
    return new


def mirror(ob, names, plane="XZ", behavior=True, search="", replace=""):
    """Mirror the joints and their hierarchies across a plane through the world origin; returns the new names."""
    r = Matrix.Diagonal(PLANES[plane])
    mw = ob.matrix_world
    refl = mw.inverted().to_3x3() @ r @ mw.to_3x3()        # the world reflection in armature space
    origin = mw.inverted() @ (r @ (mw @ Vector((0.0, 0.0, 0.0))))
    new_names = []
    with _InEditMode(ob) as ebs:
        chain = with_descendants(ebs, names)
        taken = taken_joint_names() | {eb.name for eb in ebs}
        made = {}
        for name in chain:                                     # parents come before children
            src = ebs[name]
            rot = refl @ src.matrix.to_3x3()
            rot.col[0 if behavior else 2] *= -1.0              # right-handed again (Behavior = symmetrize)
            dst = ebs.new(mirrored_name(name, search, replace, taken))
            stamp_last(dst)
            taken.add(dst.name)
            dst.head = refl @ src.head + origin
            dst.tail = refl @ src.tail + origin
            m = rot.to_4x4()
            m.translation = dst.head
            dst.matrix = m
            # Maya's frame of the copy (see MAYA_FRAME): Behavior -(R F), Orientation F (world reflection R)
            f = maya_frame(ob, src)
            set_maya_frame(ob, dst, (r.to_3x3() @ f) * -1.0 if behavior else f)
            parent = src.parent
            if parent is not None and parent.name in made:
                dst.parent = ebs[made[parent.name]]
                dst.use_connect = src.use_connect
            else:
                dst.parent = parent
            made[name] = dst.name
            new_names.append(dst.name)
    if ob.mode != 'EDIT':
        copy_rotate(ob, made)
    return new_names


def copy_rotate(ob, pairs):
    """Maya Mirror Joints copies the rotate values (both functions:
    dst r = src r). ``pairs`` {source: copy}; same Maya rotate in
    each joint's own axes, also when their bones differ from their Maya frames."""
    for src, dst in pairs.items():
        ps, pd = ob.pose.bones.get(src), ob.pose.bones.get(dst)
        if ps is None or pd is None:
            continue
        a_s, a_d = _maya_axes(ps.bone), _maya_axes(pd.bone)
        r_m = a_s.transposed() @ ps.matrix_basis.to_3x3() @ a_s
        q = (a_d @ r_m @ a_d.transposed()).to_quaternion()
        # a Maya joint rotates by Euler values: the copy keeps the source's order, XYZ otherwise
        euler = ps.rotation_mode not in ('QUATERNION', 'AXIS_ANGLE')
        pd.rotation_mode = ps.rotation_mode if euler else 'XYZ'
        pd.rotation_euler = q.to_euler(pd.rotation_mode, ps.rotation_euler) if euler else q.to_euler('XYZ')


class ALLSET_OT_mirror_joints(bpy.types.Operator):
    """Maya Mirror Joints: copy the selected joints and their children across a plane through the origin"""
    bl_idname = "allset.mirror_joints"
    bl_label = "Mirror Joints Options"
    bl_options = {'UNDO'}

    # XZ: front and back trade places, the plane Maya mirrors across until another one is picked
    plane: EnumProperty(name="Mirror Across", items=[(k, k, "") for k in ("XY", "YZ", "XZ")], default="XZ")
    function: EnumProperty(name="Mirror Function", items=(("BEHAVIOR", "Behavior", "Mirrored joints rotate "
                                                           "the opposite way (Blender symmetrize)"),
                                                          ("ORIENTATION", "Orientation", "Mirrored joints keep the "
                                                           "same axes")), default="BEHAVIOR")
    search: StringProperty(name="Search For")
    replace: StringProperty(name="Replace With")
    option_box: BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def invoke(self, context, event):
        # Maya: a plain menu click runs with the saved options, the option box opens the window (the
        # dialog on every click kept the keyboard until closed). Blender keeps the last values.
        if self.option_box:
            return context.window_manager.invoke_props_dialog(self, width=360, confirm_text="Mirror")
        _load_options(self, "mirror_joints", ("plane", "function", "search", "replace"))
        return self.execute(context)

    def draw(self, context):
        lay = self.layout
        lay.prop(self, "plane", expand=True)
        lay.prop(self, "function", expand=True)
        lay.label(text="Replacement names for duplicated joints")
        lay.prop(self, "search")
        lay.prop(self, "replace")

    def execute(self, context):
        ob = _armature(context)
        names = selected_joint_names(ob)
        if not names:
            self.report({'WARNING'}, "Select the joints to mirror")
            return {'CANCELLED'}
        _save_options(self, "mirror_joints", ("plane", "function", "search", "replace"))
        new = mirror(ob, names, self.plane, self.function == "BEHAVIOR", self.search, self.replace)
        results.result(self, f"Mirrored {len(new)} joint(s)")
        return {'FINISHED'}


# --- joint pick-walk and parenting --------------------------------------------------------------

def parent_joints(ob, names, parent_name):
    """Parent the joints to ``parent_name`` keeping where they are (Maya P); None = unparent."""
    n = 0
    with _InEditMode(ob) as ebs:
        parent = ebs.get(parent_name) if parent_name else None
        for name in names:
            eb = ebs.get(name)
            if eb is None or eb is parent:
                continue
            if parent is not None and (parent == eb or eb in parent.parent_recursive):
                continue                                       # would make a loop
            eb.use_connect = False
            eb.parent = parent
            stamp_last(eb)
            n += 1
    return n


class ALLSET_OT_parent_joint(bpy.types.Operator):
    """Parent the selected joints to the last selected one, keeping their place (Maya P)"""
    bl_idname = "allset.parent_joint"
    bl_label = "Parent Joints"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        ob = _armature(context)
        active = active_joint_name(ob)
        names = [n for n in selected_joint_names(ob) if n != active]
        if active is None or not names:
            self.report({'WARNING'}, "Select the child joints, then the parent joint last")
            return {'CANCELLED'}
        results.result(self, f"Parented {parent_joints(ob, names, active)} joint(s) to {active}")
        return {'FINISHED'}


class ALLSET_OT_unparent_joint(bpy.types.Operator):
    """Unparent the selected joints, keeping their place (Maya Shift+P)"""
    bl_idname = "allset.unparent_joint"
    bl_label = "Unparent Joints"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        ob = _armature(context)
        n = parent_joints(ob, selected_joint_names(ob), None)
        results.result(self, f"Unparented {n} joint(s)")
        return {'FINISHED'}


classes = (ALLSET_OT_joint_tool, ALLSET_OT_orient_joint, ALLSET_OT_mirror_joints, ALLSET_OT_pick_walk_joint,
           ALLSET_OT_parent_joint, ALLSET_OT_unparent_joint)
