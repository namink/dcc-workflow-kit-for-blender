# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's IK Handle Tool and Pole Vector on Blender bones: a Maya joint is a bone head (or a chain end's tail), so an
IK handle on end joint J is an IK constraint on the bone that ends at J, aimed at an ``ikHandleN`` empty. Entry points
``create_ik``, ``ik_chain``, ``selected_pair``, ``set_pole``, ``ik_constraints_on``; operators ``allset.ik_handle``
(click two joints) and ``allset.pole_vector``. Related: ik_fk.py (IK / FK blend), ik_rp.py (Rotate-Plane pole).
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from .. import results
from . import naming, units
from .skin_cluster import _cb


PICK_RADIUS = 25          # px at UI scale 1.0
IK_STATUS = "IK Handle Tool: click the start joint, then the end joint (Esc: cancel)"
# The kit's IK is an IK constraint on the bone that ends at the end joint (no effector node); Maya answers the
# ikHandle command with its node names in the Command Line result field (#100: no Blender note in the status bar).


# --- joints (Maya points) on bones -----------------------------------------------------------

def joints_of(arm):
    """[(bone name, 'HEAD' | 'TAIL', world position)]: every bone head, plus the tails of chain ends."""
    mw = arm.matrix_world
    out = []
    for pb in arm.pose.bones:
        out.append((pb.name, 'HEAD', mw @ pb.head))
        if not pb.children:
            out.append((pb.name, 'TAIL', mw @ pb.tail))
    return out


def pick_joint(region, rv3d, armatures, coord, radius):
    """(armature, (bone, 'HEAD'|'TAIL')) of the joint nearest ``coord`` on screen within ``radius`` px."""
    best, best_d = None, radius
    for arm in armatures:
        for name, end, pos in joints_of(arm):
            p = view3d_utils.location_3d_to_region_2d(region, rv3d, pos)
            if p is None:
                continue
            d = (Vector(coord) - p).length
            if d < best_d:
                best, best_d = (arm, (name, end)), d
    return best


def _incoming(arm, joint):
    """The bone whose tail is the joint (None for a root joint)."""
    name, end = joint
    pb = arm.pose.bones[name]
    if end == 'TAIL':
        return pb
    parent = pb.parent
    if parent is not None and (parent.tail - pb.head).length < 1e-5:
        return parent
    return None


def ik_chain(arm, start, end):
    """(IK bone, chain_count) for a Maya IK from joint ``start`` to joint ``end``, or None."""
    if start[1] == 'TAIL':
        return None
    first = arm.pose.bones[start[0]]
    ik_bone = _incoming(arm, end)
    if ik_bone is None:
        return None
    count, b = 1, ik_bone
    while b is not None and b != first:
        b = b.parent
        count += 1
    return (ik_bone, count) if b == first else None


def joint_position(arm, joint):
    pb = arm.pose.bones[joint[0]]
    return arm.matrix_world @ (pb.tail if joint[1] == 'TAIL' else pb.head)


# Maya IK Handle Tool default settings: Rotate-Plane solver, solver enabled,
# weight 1. Blender's IK constraint: RP = plain IK (pole vector: Constrain > Pole Vector), SC = the chain end follows
# the handle's rotation (``use_rotation``; the handle starts turned like the end joint so nothing jumps).
IK_SOLVERS = (("RP", "Rotate-Plane Solver", "Maya ikRPsolver: Blender IK, the pole vector (Constrain > Pole Vector) "
               "turns the chain plane"),
              ("SC", "Single-Chain Solver", "Maya ikSCsolver: Blender IK whose chain end follows the handle's "
               "rotation"))


def create_ik(context, arm, start, end, solver="RP", solver_enable=True, weight=1.0):
    """IK constraint + ``ikHandleN`` empty at the end joint; returns the handle (None = not a chain)."""
    chain = ik_chain(arm, start, end)
    if chain is None:
        return None
    ik_bone, count = chain
    handle = bpy.data.objects.new("ikHandle", None)
    context.view_layer.active_layer_collection.collection.objects.link(handle)
    naming.apply_maya_name(handle, "ikHandle", rename_data=False)
    handle.empty_display_type = 'PLAIN_AXES'
    handle.empty_display_size = units.maya_unit(context.scene)
    if solver == "SC":
        handle.rotation_euler = (arm.matrix_world @ ik_bone.matrix).to_euler()   # the end joint's orientation
    handle.location = joint_position(arm, end)
    con = ik_bone.constraints.new('IK')
    con.name = handle.name
    con.target = handle
    con.chain_count = count
    con.use_tail = True
    con.use_rotation = solver == "SC"
    con.weight = max(0.01, weight)               # Blender's IK weight range starts at 0.01
    con.mute = not solver_enable
    from . import ik_fk
    ik_fk.ensure_blend(arm, ik_bone, con)           # Maya Ik Blend on the handle
    if solver == "RP":
        # Maya ikRPsolver: default pole vector + Twist channels, the pole helper, Blender's pole angle
        from . import ik_rp
        ik_rp.setup(context, arm, ik_bone, con, handle)
    if context.active_object is not None and context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for ob in context.selected_objects:
        ob.select_set(False)
    handle.select_set(True)
    context.view_layer.objects.active = handle       # Maya: the new handle is selected, W moves it
    return handle


def selected_pair(context):
    """(start, end) joints from two selected pose bones (the ancestor starts, the active ends), or None."""
    cb = _cb()
    arm = cb.pose_armature(context)
    if arm is None:
        return None
    sel = [pb for pb in arm.pose.bones if cb.bone_selected(pb)]
    act = arm.data.bones.active
    if len(sel) != 2 or act is None:
        return None
    end = arm.pose.bones[act.name]
    start = sel[0] if sel[1] == end else sel[1]
    return arm, (start.name, 'HEAD'), (end.name, 'HEAD')


class ALLSET_OT_ik_handle(bpy.types.Operator):
    """Maya IK Handle Tool: click the start joint, then the end joint (or select both joints first)"""
    bl_idname = "allset.ik_handle"
    bl_label = "IK Handle Tool"
    bl_options = {'UNDO'}

    solver: EnumProperty(name="Current solver", items=IK_SOLVERS, default="RP")
    solver_enable: BoolProperty(name="Solver enable", default=True)
    weight: FloatProperty(name="Weight", default=1.0, min=0.01, max=1.0)

    def execute(self, context):
        """Without clicks: the two selected joints (scripts, and invoke when two are selected)."""
        pair = selected_pair(context)
        if pair is None:
            self.report({'WARNING'}, "Select the start joint, then the end joint (pose mode)")
            return {'CANCELLED'}
        return self._make(context, *pair)

    def invoke(self, context, event):
        if selected_pair(context) is not None or context.window is None:
            return self.execute(context)
        self._start = None
        self._swallow = False
        context.workspace.status_text_set(IK_STATUS)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _make(self, context, arm, start, end):
        handle = create_ik(context, arm, start, end, self.solver, self.solver_enable, self.weight)
        if handle is None:
            self.report({'WARNING'}, "The end joint must be below the start joint in the same skeleton")
            return {'CANCELLED'}
        from ..command_line import show_result
        show_result(f"Result: {handle.name}")
        return {'FINISHED'}

    def _pick(self, context, event):
        from .joints import view_under
        hit = view_under(context.window, event.mouse_x, event.mouse_y)
        if hit is None:
            return None
        area, region = hit
        arms = [o for o in context.view_layer.objects if o.type == 'ARMATURE' and o.visible_get()]
        radius = PICK_RADIUS * context.preferences.system.ui_scale
        return pick_joint(region, region.data, arms, (event.mouse_x - region.x, event.mouse_y - region.y),
                          radius)

    def modal(self, context, event):
        if event.type == 'ESC' and event.value == 'PRESS':
            context.workspace.status_text_set(None)
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS' and not (event.alt or event.ctrl or event.shift):
                hit = self._pick(context, event)
                if hit is None:
                    return {'PASS_THROUGH'} if not self._swallow else {'RUNNING_MODAL'}
                self._swallow = True
                arm, joint = hit
                if self._start is None or self._start[0] != arm:
                    self._start = (arm, joint)
                    return {'RUNNING_MODAL'}
                context.workspace.status_text_set(None)
                with context.temp_override(window=context.window):
                    return self._make(context, arm, self._start[1], joint)
            if event.value == 'RELEASE' and self._swallow:
                self._swallow = False
                return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}


# --- Pole Vector ------------------------------------------------------------------------------

def _signed_angle(v1, v2, normal):
    a = v1.angle(v2)
    return -a if normal.dot(v1.cross(v2)) < 0 else a


def pole_angle(arm, con_bone, count, pole_location):
    """IK pole angle that keeps the chain where it is (first chain bone's X axis to the pole plane)."""
    mw = arm.matrix_world
    base = con_bone
    for _ in range(count - 1):
        base = base.parent
    m = mw @ base.matrix
    head, tail = m.translation, mw @ base.tail
    x_axis = m.to_3x3().col[0]
    ik_tail = mw @ con_bone.tail
    pole_normal = (ik_tail - head).cross(pole_location - head)
    projected = pole_normal.cross(tail - head)
    return _signed_angle(x_axis, projected, tail - head)


def _chain_heads(arm, con_bone, count):
    out, b = [], con_bone
    for _ in range(count):
        if b is None:
            break
        out.append(arm.matrix_world @ b.head)
        out.append(arm.matrix_world @ b.tail)
        b = b.parent
    return out


def set_pole(context, arm, pb, con, pole):
    """Maya poleVectorConstraint: the handle's pole vector = target − start joint, so the
    chain plane turns to face the target like Maya's. A kit RP handle keeps its pole helper (twist still applies);
    another IK constraint gets the target as its pole with Blender's pole angle for Maya's plane (the old
    "move the chain least" search kept the chain where it was, which Maya doesn't). Returns the chain's movement."""
    from . import ik_rp
    from .ik_fk import chain
    count = max(con.chain_count, 1)
    context.view_layer.update()
    before = _chain_heads(arm, pb, count)
    handle = con.target
    if handle is not None and ik_rp.HELPER in handle:
        ik_rp.set_pole_object(handle, pole)
    else:
        bones = chain(pb, con)
        inv = (arm.matrix_world @ bones[0].matrix @ bones[0].bone.matrix_local.inverted()).to_3x3().inverted()
        start = arm.matrix_world @ bones[0].head
        bend, _straight = ik_rp._rest_bend(bones, inv @ (pole.matrix_world.translation - start))
        con.pole_target = pole
        con.pole_angle = ik_rp.pole_angle(arm, bones, bend)
    context.view_layer.update()
    return sum((p - q).length for p, q in zip(before, _chain_heads(arm, pb, count)))


def ik_constraints_on(target):
    """[(armature, pose bone, IK constraint)] whose IK target is ``target``."""
    out = []
    for ob in bpy.data.objects:
        if ob.type != 'ARMATURE' or ob.pose is None:
            continue
        for pb in ob.pose.bones:
            for con in pb.constraints:
                if con.type == 'IK' and con.target == target:
                    out.append((ob, pb, con))
    return out


class ALLSET_OT_pole_vector(bpy.types.Operator):
    """Maya Pole Vector constraint: select the pole object, then the IK handle"""
    bl_idname = "allset.pole_vector"
    bl_label = "Pole Vector"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.active_object is not None

    def execute(self, context):
        handle = context.active_object
        poles = [o for o in context.selected_objects if o is not handle]
        found = ik_constraints_on(handle)
        if not poles or not found:
            self.report({'WARNING'}, "Select the pole object, then the IK handle")
            return {'CANCELLED'}
        pole = poles[0]
        for arm, pb, con in found:
            set_pole(context, arm, pb, con, pole)
        results.result(self, f"{pole.name} is the pole vector of {handle.name}")
        return {'FINISHED'}
