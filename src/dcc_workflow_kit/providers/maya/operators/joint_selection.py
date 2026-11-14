# SPDX-License-Identifier: GPL-3.0-or-later
"""Bridge Maya joint objects to Blender pose bones without a manual mode switch."""

import bpy
import numpy as np

from .. import compat
from .preselect import project, segment_distance


def _set_flags(seq, prop):
    """Indices of ``seq`` items whose boolean ``prop`` is on (one read for the whole collection)."""
    flags = np.zeros(len(seq), bool)
    seq.foreach_get(prop, flags)
    return np.flatnonzero(flags)


def clear(context, keep=None):
    """Clear latent bone selections too, so reselecting a rig cannot revive them. Only the bones that are selected
    are written: a write tags the skeleton (and the meshes it deforms) for a new evaluation even when the value
    stays the same.

    ``keep``: {skeleton pointer: pose bone names} the caller selects right after, with a new lead bone. Those of them
    that are selected stay as they are instead of going off and on again (the same end state), and the lead bone of
    such a skeleton is left for the caller to set. Returns the pointers of the skeletons cleared."""
    from ..ui.channel_box import set_bone_selected
    keep = keep or {}
    cleared = set()
    for ob in context.view_layer.objects:
        if ob is None or ob.type != 'ARMATURE':
            continue
        cleared.add(ob.as_pointer())
        if ob.mode == 'EDIT':
            ebs = ob.data.edit_bones
            picked = set()
            for prop in ("select", "select_head", "select_tail"):
                picked.update(_set_flags(ebs, prop).tolist())
            for i in sorted(picked):
                bone = ebs[i]
                bone.select = bone.select_head = bone.select_tail = False
            if ebs.active is not None:
                ebs.active = None
        pbs = ob.pose.bones
        stay = keep.get(ob.as_pointer())
        for i in _set_flags(pbs, "select").tolist():
            pb = pbs[i]
            if stay is None or pb.name not in stay:
                set_bone_selected(pb, False)
        if stay is None and ob.data.bones.active is not None:
            ob.data.bones.active = None
    return cleared


def _switches(context, ob):
    """``bpy.ops.object.mode_set`` with ``ob`` as the active object switches its mode (else it raises before
    switching): Blender's poll (an editable object not disabled in viewports) and no transform running, which
    blocks every mode switch (object_edit.cc ``object_mode_set_ok_or_report``)."""
    try:
        with context.temp_override(active_object=ob):
            if not bpy.ops.object.mode_set.poll():
                return False
        wm = context.window_manager
        return not any(op is not None and op.bl_idname.startswith("TRANSFORM_OT_")
                       for w in wm.windows for op in w.modal_operators)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False


def _write_joints(ob, want):
    """Give skeleton ``ob``'s pose bones the selection ``want`` (bools in bone order), writing only those that
    differ."""
    from ..ui.channel_box import set_bone_selected
    pbs = ob.pose.bones
    now = np.zeros(len(pbs), bool)
    pbs.foreach_get("select", now)
    for i in np.flatnonzero(now != want).tolist():
        set_bone_selected(pbs[i], bool(want[i]))


def _collection_hidden(bone):
    return bool(bone.collections) and not any(c.is_visible_effectively for c in bone.collections)


def root_joints(ob):
    """Pose bones of the skeleton's top joints: shown bones with no shown ancestor, in bone order (a display layer
    hides a joint with everything below it)."""
    from ..ui import layer_joints
    layered = layer_joints.state(ob)
    out = []
    for pb in ob.pose.bones:
        if compat.bone_hidden(pb) or _collection_hidden(pb.bone) or layered.get(pb.name) == layer_joints.HIDDEN:
            continue
        up = pb.bone.parent
        while up is not None and (up.hide or _collection_hidden(up)):
            up = up.parent
        if up is None:
            out.append(pb)
    return out


def select_roots_if_empty(ob):
    """Maya: picking a skeleton picks its root joint (the Channel Box shows
    the root's channels, Select > All = every root, lead = the last). When the automatic Pose mode shows
    a rig with no shown bone selected, select its root joints, the last one active. True when it selected."""
    from ..ui.channel_box import bone_selected, set_bone_selected
    if ob is None or ob.type != 'ARMATURE' or ob.pose is None:
        return False
    if ob.mode == 'EDIT':
        # an unskinned skeleton is shown in Edit mode; its root joints are picked with their subtrees
        ebs = ob.data.edit_bones
        if any(eb.select or eb.select_head or eb.select_tail for eb in ebs):
            return False
        roots = [ebs[pb.name] for pb in root_joints(ob) if pb.name in ebs]
        for eb in roots:
            for b in _subtree(eb):
                _set_edit(b, True)
        if roots:
            ebs.active = roots[-1]
        return bool(roots)
    if any(bone_selected(pb) and not compat.bone_hidden(pb) and not _collection_hidden(pb.bone)
           for pb in ob.pose.bones):
        return False
    roots = root_joints(ob)
    for pb in roots:
        set_bone_selected(pb, True)
    if roots:
        ob.data.bones.active = roots[-1].bone
    return bool(roots)


def pick(context, ob, mouse, radius):
    """Pick a visible, selectable joint, preferring its head over the connecting shaft (a joint a display layer hides
    or makes Template / Reference can't be picked)."""
    from .select_priority import BONE_WIDTH, bone_width
    from ..ui import layer_joints
    editing = ob.mode == 'EDIT'
    bones = ob.data.edit_bones if editing else ob.pose.bones
    layered = layer_joints.state(ob)
    candidates = []
    persp = np.asarray(context.region_data.perspective_matrix, dtype=np.float64)
    region = context.region
    for item in bones:
        bone = item if editing else item.bone
        hidden = bone.hide if editing else compat.bone_hidden(item)
        if (hidden or bone.hide_select or item.name in layered or (bone.collections and
                not any(c.is_visible_effectively for c in bone.collections))):
            continue
        points = np.asarray([ob.matrix_world @ item.head, ob.matrix_world @ item.tail])
        screen, front = project(points, persp, region.width, region.height)
        if not all(front):
            continue
        distance, t = segment_distance(mouse, screen[:1], screen[1:])
        width = BONE_WIDTH * np.linalg.norm(screen[1] - screen[0]) if ob.data.display_type == 'OCTAHEDRAL' else 0
        shaft = max(0.0, float(distance[0] - bone_width(t, width)[0]))
        head = float(np.linalg.norm(screen[0] - mouse))
        if min(head, shaft) <= radius:
            candidates.append((head > radius, head if head <= radius else shaft, item.name))
    return min(candidates)[2] if candidates else None


# --- Edit or Pose (Issue #156) ------------------------------------
# Maya moves a placed joint with W at any time (translate; the children follow). Blender can't translate a connected
# bone in Pose mode, so while the **Move tool** is on, a skeleton that drives no mesh is shown in Edit mode (the rest
# = where Maya's joints are); with any other tool joints are picked in Pose mode as before (Channel Box
# channels, S keys, pick walk). A skinned (or animated) skeleton is posed with every tool, and Skin > Move Skinned
# Joints puts it in Edit mode for the move (the Armature modifier deforms by pose x rest^-1: a new rest at the rest
# pose leaves the mesh where it is = Maya's moveJointsMode rewriting bindPreMatrix). Entering Edit mode on every pick would
# lose the Channel Box / S / pick walk of unskinned joints.

MOVE_SKINNED = "allset_move_skinned"
AUTO_EDIT = "allset_joint_move_edit"      # Edit mode entered because of the Move tool (sync_tool_mode leaves it)
POSE_PIN = "allset_joint_pose_pin"        # F8 chose Pose while the Move tool is on


def move_tool_active(context):
    try:
        tools = context.workspace.tools
        return any((t := tools.from_space_view3d_mode(m, create=False)) is not None and t.idname == "builtin.move"
                   for m in {context.mode, 'POSE'} if m in {'POSE', 'EDIT_ARMATURE', 'OBJECT'})
    except (AttributeError, RuntimeError, TypeError):
        return False


def sync_tool_mode(context):
    """Move tool on an unskinned skeleton's picked joints -> Edit mode with the picked subtrees; another tool -> back
    to Pose with the same joints picked. Returns the mode switched to (None: nothing done). tool_keys watch, 0.25 s."""
    ob = context.active_object
    if ob is None or ob.type != 'ARMATURE' or not ob.select_get() or ob.get(MOVE_SKINNED):
        return None
    moving = move_tool_active(context)
    if ob.get(POSE_PIN):            # F8 went back to Pose with the Move tool on: stay until another tool is picked
        if not moving:
            ob.pop(POSE_PIN, None)
        return None
    if ob.mode == 'POSE' and moving and joint_mode(ob) == 'EDIT':
        from ..ui.channel_box import bone_selected
        picked = [pb.name for pb in ob.pose.bones if bone_selected(pb)]
        active = ob.data.bones.active.name if ob.data.bones.active else None
        if not picked or any(ob.pose.bones[n].custom_shape is not None for n in picked):
            return None     # controls (custom shapes) are animated in Pose, never repositioned (#171)
        bpy.ops.object.mode_set(mode='EDIT')
        ob[AUTO_EDIT] = True
        ebs = ob.data.edit_bones
        for eb in ebs:
            _set_edit(eb, False)
        for name in picked:
            for b in _subtree(ebs[name]):
                _set_edit(b, True)
        ebs.active = ebs.get(active) if active in picked else ebs[picked[-1]]
        sync_joint_pivot(context)
        return 'EDIT'
    if ob.mode == 'EDIT' and ob.get(AUTO_EDIT) and not moving:
        picked = [eb.name for eb in _edit_picked(ob)]
        active = ob.data.edit_bones.active.name if ob.data.edit_bones.active else None
        ob.pop(AUTO_EDIT, None)
        bpy.ops.object.mode_set(mode='POSE')
        from ..ui.channel_box import set_bone_selected
        for pb in ob.pose.bones:
            set_bone_selected(pb, pb.name in picked)
        if picked:
            ob.data.bones.active = ob.data.bones[active if active in picked else picked[-1]]
        return 'POSE'
    return None


def is_skinned(ob):
    """An Armature modifier of some mesh uses ``ob`` (Maya: a skinCluster influence)."""
    return any(o.type == 'MESH' and any(m.type == 'ARMATURE' and m.object == ob for m in o.modifiers)
               for o in bpy.data.objects)


def is_animated(ob):
    ad = ob.animation_data
    if ad is None:
        return False
    if ad.nla_tracks:
        return True
    return any(fc.data_path.startswith("pose.bones") for fc in compat.id_fcurves(ob))


def joint_mode(ob):
    """'EDIT' where moving a joint repositions its rest (unskinned, unanimated, or Move Skinned Joints on), else
    'POSE' (used with the Move tool, see sync_tool_mode)."""
    if ob.get(MOVE_SKINNED):
        return 'EDIT'
    return 'POSE' if is_skinned(ob) or is_animated(ob) else 'EDIT'


def sync_joint_pivot(context):
    """E / R on picked joints in Edit mode turn / scale about the lead joint (Maya rotates a joint about itself).
    Blender's Active Element pivot of an edit bone is its middle, so the Edit Armature pivot is the 3D cursor kept on
    the lead joint (pivot.MAYA_PIVOT_POINT; the Maya layout doesn't draw the cursor). Called on a pick and from
    tool_keys' 0.25 s watch (the joint moves with W)."""
    ob = context.active_object
    if ob is None or ob.type != 'ARMATURE' or ob.mode != 'EDIT':
        return False
    eb = ob.data.edit_bones.active
    if eb is None or not eb.select:
        return False
    from .pivot import MAYA_PIVOT_POINT
    ts = context.scene.tool_settings
    if ts.transform_pivot_point != 'CURSOR' and ts.transform_pivot_point in {*MAYA_PIVOT_POINT.values(), 'MEDIAN_POINT'}:
        # only from a Maya pivot value (or Blender's default Median), and put back when Edit Armature ends (restore_joint_pivot): a user's cursor
        # pivot in mesh editing is never touched (test_step59_pivot_snap)
        _PIVOT["prev"] = ts.transform_pivot_point
        ts.transform_pivot_point = 'CURSOR'
    head = ob.matrix_world @ eb.head
    cursor = context.scene.cursor
    if (cursor.location - head).length > 1e-9:
        cursor.location = head
    return True


_PIVOT = {"prev": None}


def restore_joint_pivot(context):
    """Outside Edit Armature mode, give back the pivot sync_joint_pivot replaced. tool_keys watch."""
    prev = _PIVOT["prev"]
    if prev is None or context.mode == 'EDIT_ARMATURE':
        return False
    _PIVOT["prev"] = None
    ts = context.scene.tool_settings
    if ts.transform_pivot_point == 'CURSOR':
        ts.transform_pivot_point = prev
        return True
    return False


def _subtree(bone):
    return [bone, *bone.children_recursive]


def _edit_selected(eb):
    return eb.select and eb.select_head and eb.select_tail


def _set_edit(eb, state):
    eb.select = eb.select_head = eb.select_tail = state


def _edit_picked(ob):
    """Picked joints in Edit mode: bones whose head is selected and whose parent isn't wholly selected (a picked joint
    is its whole subtree, or only its head with Preserve Children)."""
    return [eb for eb in ob.data.edit_bones if eb.select_head
            and (_edit_selected(eb) or not eb.select_tail)
            and not (eb.parent is not None and _edit_selected(eb.parent))]


def _pick_shape(eb, state, preserve):
    """Select joint ``eb`` for W: its bone and subtree, or (Maya Preserve Children) only its head, so the
    children stay — a connected head is the parent's tail point."""
    if not preserve:
        for b in _subtree(eb):
            _set_edit(b, state)
        return
    eb.select_head = state
    eb.select = eb.select_tail = False
    if eb.use_connect and eb.parent is not None and not _edit_selected(eb.parent):
        eb.parent.select_tail = state


def reshape(context, ob, preserve):
    """Re-select the picked joints of ``ob`` (edit mode) in the subtree / head-only shape; the active stays."""
    if ob is None or ob.type != 'ARMATURE' or ob.mode != 'EDIT':
        return False
    ebs = ob.data.edit_bones
    picked = [eb.name for eb in _edit_picked(ob)]
    active = ebs.active
    for eb in ebs:
        _set_edit(eb, False)
    for name in picked:
        _pick_shape(ebs[name], True, preserve)
    ebs.active = active
    return bool(picked)


def select_edit(context, ob, name, shift=False, ctrl=False):
    """Maya replace / toggle / subtract / add on joints of a skeleton in Edit mode: a picked joint selects its bone
    and the subtree below it (W moves them together, like Maya's children following their parent)."""
    if context.mode != 'OBJECT' and (context.active_object != ob or ob.mode != 'EDIT'):
        bpy.ops.object.mode_set(mode='OBJECT')
    if not shift and not ctrl:
        clear(context)
        for other in context.selected_objects:
            if other != ob:
                other.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    if ob.mode != 'EDIT':
        bpy.ops.object.mode_set(mode='EDIT')
        if not shift and not ctrl:
            for eb in ob.data.edit_bones:
                _set_edit(eb, False)
    ebs = ob.data.edit_bones
    eb = ebs[name]
    from .joint_edit import preserve_children
    preserve = preserve_children(context)
    selected = eb.select_head and (_edit_selected(eb) or preserve)
    remove = (ctrl and not shift) or (shift and not ctrl and selected)
    if not shift and not ctrl:
        for other in ebs:
            _set_edit(other, False)
    _pick_shape(eb, not remove, preserve)
    if remove:
        if ebs.active == eb:
            picked = _edit_picked(ob)
            ebs.active = picked[-1] if picked else None
        if not _edit_picked(ob):
            bpy.ops.object.mode_set(mode='OBJECT')
            ob.select_set(False)
            if context.view_layer.objects.active == ob:
                context.view_layer.objects.active = next(iter(context.selected_objects), None)
        return False
    ebs.active = eb
    sync_joint_pivot(context)
    return True


def select(context, ob, name, shift=False, ctrl=False):
    """Maya replace / toggle / subtract / add on individual joints."""
    # a bone with a custom shape is a control (control = bone Custom Shape), not a Maya joint: picking it
    # keeps Pose mode with the Move tool too (#171: an unkeyed Rigify rig went to Edit mode on a W click)
    control = name in ob.pose.bones and ob.pose.bones[name].custom_shape is not None
    # the tool first: ``joint_mode`` looks at every object's modifiers (is the skeleton skinned?)
    if ob.get(MOVE_SKINNED) or (not control and not ob.get(POSE_PIN) and move_tool_active(context)
                                and joint_mode(ob) == 'EDIT'):
        r = select_edit(context, ob, name, shift, ctrl)
        if not ob.get(MOVE_SKINNED) and ob.mode == 'EDIT':
            ob[AUTO_EDIT] = True
        return r
    from ..ui.channel_box import bone_selected, set_bone_selected
    pb = ob.pose.bones[name]
    selected = bone_selected(pb)
    remove = (ctrl and not shift) or (shift and not ctrl and selected)
    if (remove and context.active_object == ob and ob.mode == 'POSE' and _switches(context, ob)
            and not any(bone_selected(b) for b in ob.pose.bones if b != pb)):
        # the last joint taken off: the skeleton leaves Pose Mode, its joint written with that switch (see below)
        def write():
            set_bone_selected(pb, False)
            if ob.data.bones.active == pb.bone:
                ob.data.bones.active = None
            ob.select_set(False)
            if context.view_layer.objects.active == ob:
                context.view_layer.objects.active = next(iter(context.selected_objects), None)
        if not _switch_with(context, 'OBJECT', write, lambda: ob.mode == 'OBJECT'):
            write()
        return False
    if remove:
        set_bone_selected(pb, False)
        if ob.data.bones.active == pb.bone:
            ob.data.bones.active = next((b.bone for b in ob.pose.bones if bone_selected(b)), None)
        if not any(bone_selected(b) for b in ob.pose.bones):
            if context.active_object == ob and ob.mode == 'POSE':
                bpy.ops.object.mode_set(mode='OBJECT')
            ob.select_set(False)
            if context.view_layer.objects.active == ob:
                context.view_layer.objects.active = next(iter(context.selected_objects), None)
        return False
    leave = context.mode != 'OBJECT' and context.active_object != ob
    # Every mode switch evaluates the scene after it (and what is pending before it), so the selection is written
    # where an evaluation comes anyway: inside the one after the switch out of the mode another object is in, or
    # after the switch from Object Mode into Pose Mode (the switch in only needs ``ob`` active and, for a replace,
    # no other skeleton selected: object_edit.cc ``posemode_exec`` enters the selected skeletons too), else before
    # the switch in. Entering Pose Mode changes no bone selection (pose_edit.cc ``ED_object_posemode_enter_ex``), so
    # the joint may be written before it. Not when a switch may fail (the joint would stay picked) or ``ob`` is in
    # Edit Mode (leaving it writes the edit bones' selection and lead into the bones).
    sure = ob.mode in {'POSE', 'OBJECT'} and _switches(context, ob) and _in_layer(context, ob)
    if leave and sure and _switches(context, context.active_object):
        done = _one_switch(context, lambda: _write_pick(context, ob, name, shift, ctrl, True), True)
        if done is None and not _switch_with(context, 'OBJECT',
                                             lambda: _write_pick(context, ob, name, shift, ctrl, True),
                                             lambda: bpy.context.mode == 'OBJECT'):
            done = False
        if done is False:
            _write_pick(context, ob, name, shift, ctrl, True)
        if ob.mode != 'POSE':
            bpy.ops.object.mode_set(mode='POSE')
        return True
    if leave:
        bpy.ops.object.mode_set(mode='OBJECT')
    early = (ob.mode == 'POSE' or (ob.mode == 'OBJECT' and _switches(context, ob))) and _in_layer(context, ob)
    if early and ob.mode == 'OBJECT':
        # the selection, then the switch into Pose Mode (which enters ``ob`` and the selected skeletons), in one call
        done = _one_switch(context, lambda: _write_pick(context, ob, name, shift, ctrl, True), False, ob)
        if done is not None:
            if not done:
                _write_pick(context, ob, name, shift, ctrl, True)
            if ob.mode != 'POSE':
                bpy.ops.object.mode_set(mode='POSE')
            return True
    if early and ob.mode == 'OBJECT' and (shift or ctrl or not any(
            o != ob and o.type == 'ARMATURE' for o in context.view_layer.objects.selected)):
        if context.view_layer.objects.active != ob:
            context.view_layer.objects.active = ob     # (set again with the selection)
        if not _switch_with(context, 'POSE', lambda: _write_pick(context, ob, name, shift, ctrl, True),
                            lambda: ob.mode == 'POSE'):
            _write_pick(context, ob, name, shift, ctrl, True)
        return True
    _write_pick(context, ob, name, shift, ctrl, early)
    if ob.mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
    if not early:
        set_bone_selected(ob.pose.bones[name], True)
        ob.data.bones.active = ob.data.bones[name]
    return True


def _write_pick(context, ob, name, shift, ctrl, joint):
    """A joint pick's selection: a replace clears the joints and the other objects, ``ob`` selected and active, and
    (``joint``) the joint picked and made the lead (one already picked is not written off and on again)."""
    from ..ui.channel_box import bone_selected, set_bone_selected
    if not shift and not ctrl:
        clear(context, {ob.as_pointer(): {name}} if joint else None)
        for other in context.selected_objects:
            if other != ob:
                other.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    if joint:
        pb = ob.pose.bones[name]
        if not bone_selected(pb):
            set_bone_selected(pb, True)
        ob.data.bones.active = ob.data.bones[name]


def _switch_with(context, mode, write, switched):
    """``bpy.ops.object.mode_set(mode=mode)`` with ``write()`` run inside the scene evaluation that follows the
    switch, so it is evaluated together with the switch instead of in an evaluation of its own: a one-time
    depsgraph_update_pre handler runs it before that evaluation, once the switch is done (``switched()``). Returns
    True when ``write`` ran there (raising what it raised), False when the switch evaluated nothing (the caller
    writes)."""
    done, err = [], []

    def before_update(*_args):
        if done or not switched():
            return
        done.append(True)
        try:
            write()
        except Exception as e:      # noqa: BLE001 - raised from the caller, as a write made there would be
            err.append(e)
    handlers = bpy.app.handlers.depsgraph_update_pre
    handlers.insert(0, before_update)
    try:
        bpy.ops.object.mode_set(mode=mode)
    finally:
        # removed only now: Blender walks the handler list by index while it calls them
        while before_update in handlers:
            handlers.remove(before_update)
    if err:
        raise err[0]
    return bool(done)


_JOB = [None]       # the pick ``_one_switch`` hands to ALLSET_OT_joint_pick_write


def _quiet_between(context, out):
    """No depsgraph handler of the kit acts on the Object Mode state between the switches: the Maya pivot point of
    Object Mode is set already (or isn't a Maya one), and no pivot axes follow the lead (``pivot._on_depsgraph``)."""
    from . import pivot
    scene = context.scene
    slots = scene.transform_orientation_slots
    if any(slots[i].type == pivot.ORIENT_NAME for i in pivot.PIVOT_SLOTS):
        return False
    if out:
        now = scene.tool_settings.transform_pivot_point
        if now != pivot.MAYA_PIVOT_POINT.get('OBJECT') and now in pivot.MAYA_PIVOT_POINT.values():
            return False
    return True


def _one_switch_ready(context, out, lead=None):
    """``_one_switch`` can run now (see there)."""
    macro = bpy.ops.allset.joint_pick_switch if out else bpy.ops.allset.joint_pick_enter
    try:
        with context.temp_override(**({} if out else {"active_object": lead})):
            return _quiet_between(context, out) and macro.poll()
    except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError):
        return False


def _one_switch(context, write, out, lead=None):
    """The switch out of the current mode (``out``), ``write()`` and the switch into Pose Mode as one operator call (a
    macro). Blender evaluates the scene after an operator call, not between the operators of a macro, so the
    selection and both switches are evaluated once instead of after each switch; the same objects, modes and
    selection come out. Without ``out``, ``write`` makes ``lead`` the active object: Blender checks the switch into
    Pose Mode before the call, so it is checked with ``lead`` active. None when it can't be used and the caller goes
    the usual way: the switches can't run in this context, or a depsgraph handler of the kit would act on the Object
    Mode state between them (``_quiet_between``). True when ``write`` ran (raising what it raised), False when the
    switch out didn't happen (the caller writes)."""
    if not _one_switch_ready(context, out, lead):
        return None
    macro = bpy.ops.allset.joint_pick_switch if out else bpy.ops.allset.joint_pick_enter
    job = {"write": write, "out": out, "ran": False, "err": None}
    _JOB[0] = job
    try:
        with context.temp_override(**({} if out else {"active_object": lead})):
            macro()
    finally:
        _JOB[0] = None
    if job["err"] is not None:
        raise job["err"]
    return job["ran"]


class ALLSET_OT_joint_pick_write(bpy.types.Operator):
    """Write the joint pick waiting between the mode switches of a joint pick (internal)"""
    bl_idname = "allset.joint_pick_write"
    bl_label = "Joint Pick"
    bl_options = {'INTERNAL'}

    def execute(self, _context):
        job = _JOB[0]
        if job is None or job["ran"] or (job["out"] and bpy.context.mode != 'OBJECT'):
            return {'CANCELLED'}        # nothing waiting, or the switch out didn't happen: the caller writes
        job["ran"] = True
        try:
            job["write"]()
        except Exception as e:      # noqa: BLE001 - raised from the caller, as a write made there would be
            job["err"] = e
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_joint_pick_switch(bpy.types.Macro):
    """Leave the mode, write the joint pick and enter Pose Mode (internal)"""
    bl_idname = "allset.joint_pick_switch"
    bl_label = "Joint Pick"
    bl_options = {'INTERNAL'}

    @classmethod
    def register(cls):
        cls.define("OBJECT_OT_mode_set").properties.mode = 'OBJECT'
        cls.define("ALLSET_OT_joint_pick_write")
        cls.define("OBJECT_OT_mode_set").properties.mode = 'POSE'


class ALLSET_OT_joint_pick_enter(bpy.types.Macro):
    """Write the joint pick and enter Pose Mode (internal)"""
    bl_idname = "allset.joint_pick_enter"
    bl_label = "Joint Pick"
    bl_options = {'INTERNAL'}

    @classmethod
    def register(cls):
        cls.define("ALLSET_OT_joint_pick_write")
        cls.define("OBJECT_OT_mode_set").properties.mode = 'POSE'


classes = (ALLSET_OT_joint_pick_write, ALLSET_OT_joint_pick_switch, ALLSET_OT_joint_pick_enter)


def _in_layer(context, ob):
    """``ob`` is in the view layer (selecting it or making it active would raise otherwise): a selected or visible
    object has its base there."""
    try:
        return ob.select_get() or ob.visible_get() or any(o == ob for o in context.view_layer.objects)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False


def _pose_picks(context, ob, names):
    """``select`` picks each of ``names`` of ``ob`` as a pose bone (none as an edit joint with the Move tool)."""
    if ob.get(MOVE_SKINNED):
        return False
    pbs = ob.pose.bones
    if any(pbs.get(n) is None for n in names):
        return False
    if ob.get(POSE_PIN) or not move_tool_active(context) or joint_mode(ob) != 'EDIT':
        return True
    return all(pbs[n].custom_shape is not None for n in names)     # controls stay pose bones


def select_many(context, ob, names, shift=False, ctrl=False):
    """``select`` on each of ``names`` of skeleton ``ob`` in turn: the first with ``shift`` / ``ctrl``, the rest added
    (a marquee's joints of one skeleton). Once the first has made ``ob`` the lead in Pose mode, adding another bone
    there only selects it and makes it the lead bone, so the rest are written at once; anything else (a removal, an
    edit joint, another mode) goes joint by joint. Returns ``select``'s result for the last one."""
    names = list(names)
    if not names:
        return False
    result = select(context, ob, names[0], shift, ctrl)
    rest = names[1:]
    if not rest:
        return result
    from ..ui.channel_box import bone_selected, set_bone_selected
    if not (result and context.active_object == ob and ob.mode == 'POSE'
            and _pose_picks(context, ob, rest)):
        for n in rest:
            result = select(context, ob, n, True, True)
        return result
    pbs = ob.pose.bones
    for n in rest:
        pb = pbs[n]
        if not bone_selected(pb):
            set_bone_selected(pb, True)
    if ob.data.bones.active != ob.data.bones[rest[-1]]:
        ob.data.bones.active = ob.data.bones[rest[-1]]
    return True


def select_groups(context, groups, shift=False, ctrl=False, restored=None, waiting=False):
    """``select_many`` on each (skeleton, names) of ``groups`` in turn: the first with ``shift`` / ``ctrl``, the rest
    added (a replace / add marquee over several skeletons).

    Skeleton by skeleton, each added skeleton leaves Pose Mode for Object Mode and comes back (it has to be the active
    object to enter), and every mode switch evaluates the scene twice (rigs and the meshes they deform). When every
    group is picked as pose bones from Object or Pose Mode the end state is written with at most one switch out and
    one into Pose Mode: leave the mode the drag started in, the replace's clearing, the skeletons selected, the last
    one active, Pose Mode (every selected skeleton enters it, as the last skeleton's switch did), then each
    skeleton's joints with its last joint as its lead. The same objects, modes, joints and leads as skeleton by
    skeleton. Anything else goes skeleton by skeleton.

    ``restored``: {skeleton pointer: (skeleton, its pose bones' selection as bools in bone order)}, the joint
    selection the caller puts back before the picks (the one a marquee started from) and has not written yet. It is
    written first; or, when the switches can't fail, with the joints before the switch into Pose Mode (see
    ``select``), only where the end state differs: a replace clears every skeleton of the view layer anyway.

    ``waiting``: a change made before (Blender's own box / lasso result) has not been evaluated yet. The switches'
    operator call evaluates it first anyway, so a replace from Pose Mode writes the end state before the switches,
    evaluated in that same pass, and the switches' own evaluation is left with the mode change. Only while the active
    object is the last skeleton, in Pose Mode: the switch out of Pose Mode acts on the active object (object_modes.cc
    ``mode_set_ex``), so it takes the same skeletons out as with the selection written between the switches; entering
    Pose Mode changes no bone selection and enters the active and selected skeletons (object_edit.cc
    ``posemode_exec``), the ones written."""
    groups = [(ob, list(names)) for ob, names in groups if names]
    restored = restored or {}
    one_by_one = (len(groups) < 2 or shift != ctrl or context.mode not in {'OBJECT', 'POSE'}
                  or len({ob.as_pointer() for ob, _names in groups}) < len(groups)
                  or any(ob.library is not None or not _pose_picks(context, ob, names) for ob, names in groups)
                  # Object Mode with a skeleton left in Pose Mode: only a switch from Pose Mode would take it out
                  or (context.mode == 'OBJECT' and any(o.mode == 'POSE' for o in context.view_layer.objects)))
    early = (not one_by_one and (context.mode == 'OBJECT' or _switches(context, context.active_object))
             and _switches(context, groups[-1][0])
             and all(ob.mode != 'EDIT' and _in_layer(context, ob) for ob, _names in groups))
    if not early:
        for ob, want in restored.values():
            _write_joints(ob, want)
    if one_by_one:
        result = False
        for i, (ob, names) in enumerate(groups):
            if i > 0:
                shift, ctrl = True, True
            result = select_many(context, ob, names, shift, ctrl)
        return result
    first, last = groups[0][0], groups[-1][0]

    def write():
        cleared = set()
        if not shift:
            cleared = clear(context, {ob.as_pointer(): set(names) for ob, names in groups} if early else None)
            for other in context.selected_objects:
                if other != first:
                    other.select_set(False)
        if early:
            for ptr, (ob, want) in restored.items():
                if ptr not in cleared:
                    _write_joints(ob, want)
        for ob, _names in groups:
            ob.select_set(True)
        context.view_layer.objects.active = last
        if early:
            _pick_groups(groups, not shift)     # a replace cleared the leads: each is set again

    if (waiting and early and not shift and context.mode == 'POSE' and last.mode == 'POSE'
            and context.view_layer.objects.active == last and _one_switch_ready(context, True)):
        write()                                 # evaluated with the pending change, before the switches
        if _one_switch(context, lambda: None, True) is None:
            bpy.ops.object.mode_set(mode='OBJECT')
        if last.mode != 'POSE':
            bpy.ops.object.mode_set(mode='POSE')
        return True
    # (see ``select``: the switch out, the selection and the switch in as one operator call when it can be)
    done = _one_switch(context, write, context.mode != 'OBJECT', last) if early else None
    if done is not None:
        if not done:
            write()
    elif context.mode == 'OBJECT':
        write()
    elif not early:
        bpy.ops.object.mode_set(mode='OBJECT')
        write()
    elif not _switch_with(context, 'OBJECT', write, lambda: bpy.context.mode == 'OBJECT'):
        write()                                 # (see ``select``: written with the switch out of Pose Mode)
    if last.mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
    if not early:
        _pick_groups(groups, False)
    return True


def _pick_groups(groups, lead):
    """Select each group's joints, its last joint the skeleton's lead (``lead``: set even when it is already)."""
    from ..ui.channel_box import bone_selected, set_bone_selected
    for ob, names in groups:
        pbs = ob.pose.bones
        for n in names:
            pb = pbs[n]
            if not bone_selected(pb):
                set_bone_selected(pb, True)
        if lead or ob.data.bones.active != ob.data.bones[names[-1]]:
            ob.data.bones.active = ob.data.bones[names[-1]]


def leave(context, clear_selection=False):
    if clear_selection:
        clear(context)
    if context.mode != 'OBJECT' and context.active_object is not None:
        bpy.ops.object.mode_set(mode='OBJECT')


def select_object_at(context, mouse, shift=False, ctrl=False):
    """Native object picking after releasing Blender's pose/edit selection lock."""
    leave(context, clear_selection=not (shift or ctrl))
    result = bpy.ops.view3d.select(location=tuple(map(int, mouse)),
                                  deselect_all=not (shift or ctrl),
                                  toggle=shift and not ctrl,
                                  deselect=ctrl and not shift,
                                  extend=shift and ctrl)
    if not context.selected_objects:
        context.view_layer.objects.active = None
    return result
