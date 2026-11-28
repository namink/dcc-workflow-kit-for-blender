# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Constrain > Modify: Remove Target, Set Rest Position and Modify Constrained Axis on the kit's constraints, and
the Maya type of a kit constraint (``maya_type``, ``maya_target``, ``CHANNELS``, read by the Channel Box). A channel a
constraint stops driving keeps its constrained value: ``bake`` writes it into the object's own channels (also used by
constrain_multi.py). Operators ``allset.remove_constraint_target`` / ``set_constraint_rest`` /
``modify_constraint_axes``.
"""

import bpy
from bpy.props import BoolProperty
from mathutils import Matrix, Vector

from .. import results
from .normal_tangent_helpers import KIND, _rescan, helper_of, surface_of

# Maya's own messages
MSG_REMOVE_SELECT = "You must select one or more target(s) followed by the constrained object."
MSG_REMOVE_CONSTRAINED = "A constrained object must be the last object selected."
MSG_REST = "A constrained object must be selected."
MSG_AXES_SELECT = "You must select the constrained object."
MSG_AXES_NONE = "No axes were selected."
MSG_AXES_INVALID = "An aim-, orient-, parent-, point-, or scale-constrained object must be the last object selected."


# --- Maya constraint types of the kit's Blender constraints -------------------------------------------

CHANNELS = {"point": "t", "geometry": "t", "aim": "r", "orient": "r", "normal": "r", "tangent": "r",
            "scale": "s", "parent": "tr"}


def maya_type(con):
    t = con.type
    if t in {'TRACK_TO', 'DAMPED_TRACK', 'LOCKED_TRACK'}:
        h = helper_of(con)
        return h.get(KIND) if h is not None else "aim"
    return {'CHILD_OF': "parent", 'COPY_TRANSFORMS': "parent", 'COPY_LOCATION': "point",
            'COPY_ROTATION': "orient", 'COPY_SCALE': "scale", 'SHRINKWRAP': "geometry"}.get(t)


def maya_target(con, arm=None):
    """(object, bone name or "") the Maya target of a kit constraint."""
    s = surface_of(con)
    if s is not None:
        return s, ""
    t = getattr(con, "target", None)
    return t, (getattr(con, "subtarget", "") if t is not None and t.type == 'ARMATURE' else "")


# --- baking the visual value into the own channels ------------------------------------------------------

def _save(node):
    return {"t": node.location.copy(), "e": node.rotation_euler.copy(), "q": node.rotation_quaternion.copy(),
            "a": tuple(node.rotation_axis_angle), "s": node.scale.copy()}


def _restore(node, saved, keys, axes=None):
    """Put back the saved channels not in ``keys`` (and, with ``axes``, the axes of ``keys`` not in ``axes``)."""
    for k in "trs":
        if k in keys and axes is None:
            continue
        if k == "t":
            cur = node.location.copy()
            node.location = [cur[i] if (k in keys and i in axes) else saved["t"][i] for i in range(3)]
        elif k == "s":
            cur = node.scale.copy()
            node.scale = [cur[i] if (k in keys and i in axes) else saved["s"][i] for i in range(3)]
        else:
            if k in keys:                   # per axis: only Euler channels split; other modes keep the new value
                if node.rotation_mode not in {'QUATERNION', 'AXIS_ANGLE'}:
                    cur = node.rotation_euler.copy()
                    node.rotation_euler = [cur[i] if i in axes else saved["e"][i] for i in range(3)]
                continue
            node.rotation_euler = saved["e"]
            node.rotation_quaternion = saved["q"]
            node.rotation_axis_angle = saved["a"]


def visual(context, node):
    context.view_layer.update()
    return node.matrix.copy() if isinstance(node, bpy.types.PoseBone) else node.matrix_world.copy()


def bake(context, node, keys, axes=None, matrix=None):
    """Write the visual (constrained) value of channels ``keys`` ("t" / "r" / "s") into ``node``'s own channels."""
    if not keys:
        return
    m = visual(context, node) if matrix is None else matrix
    saved = _save(node)
    if isinstance(node, bpy.types.PoseBone):
        node.matrix = m
    else:
        node.matrix_world = m
    _restore(node, saved, keys, axes)
    context.view_layer.update()


# --- Remove Target ------------------------------------------------------------------------------------

REMOVE_TYPES = ("point", "orient", "aim", "scale", "parent", "geometry", "normal", "tangent", "pole_vector")


def _owner_and_targets(context):
    """(constrained node, [(object, bone name)] targets) in Maya's selection order (constrained last)."""
    if context.mode == 'POSE' and context.active_pose_bone is not None:
        pb = context.active_pose_bone
        arm = pb.id_data
        targets = [(o, "") for o in context.selected_objects if o is not arm]
        targets += [(arm, b.name) for b in context.selected_pose_bones or () if b != pb]
        return pb, targets
    ob = context.active_object
    return ob, [(o, "") for o in context.selected_objects if o is not ob]


def remove_targets(context, owner, targets, types=REMOVE_TYPES):
    """Remove the kit constraints of ``types`` on ``owner`` whose Maya target is in ``targets``; bake the channels of
    a Maya type whose last target goes. Returns [(maya type, target name)] removed, or None when ``owner`` is not
    constrained at all."""
    removed = []
    cons = list(getattr(owner, "constraints", ()))
    poles = []
    if "pole_vector" in types and isinstance(owner, bpy.types.Object):
        from . import skin
        poles = [(arm, pb, con) for arm, pb, con in skin.ik_constraints_on(owner) if con.pole_target is not None]
    typed = [(c, maya_type(c)) for c in cons]
    typed = [(c, t) for c, t in typed if t is not None]
    if not typed and not poles:
        return None
    tset = {(o.name, b) for o, b in targets}
    doomed = []
    for c, t in typed:
        if t not in types:
            continue
        obj, bone = maya_target(c)
        if obj is not None and (obj.name, bone) in tset:
            doomed.append((c, t, obj.name + ("." + bone if bone else "")))
    for t in {t for _c, t, _n in doomed}:
        left = [c for c, tt in typed if tt == t and all(c is not d for d, _t, _n in doomed)]
        if not left:
            bake(context, owner, CHANNELS[t])
    for c, t, name in doomed:
        h = helper_of(c)
        owner.constraints.remove(c)
        if h is not None:
            bpy.data.objects.remove(h)
            _rescan()
        removed.append((t, name))
    for arm, pb, con in poles:
        if (con.pole_target.name, getattr(con, "pole_subtarget", "") or "") in tset:
            name = con.pole_target.name
            con.pole_target = None
            removed.append(("pole_vector", name))
    context.view_layer.update()
    return removed


class ALLSET_OT_remove_constraint_target(bpy.types.Operator):
    """Maya Remove Target: select the target(s), then the constrained object; the constraints from those targets go
    (the last one of a type leaves the channels where the constraint had them)"""
    bl_idname = "allset.remove_constraint_target"
    bl_label = "Remove Target"
    bl_options = {'REGISTER', 'UNDO'}

    remove_all: BoolProperty(name="All", default=True, description="Remove the targets from every constraint type")
    point: BoolProperty(name="Point constraint", default=True)
    orient: BoolProperty(name="Orient constraint", default=True)
    aim: BoolProperty(name="Aim constraint", default=True)
    scale: BoolProperty(name="Scale constraint", default=True)
    parent: BoolProperty(name="Parent constraint", default=True)
    geometry: BoolProperty(name="Geometry constraint", default=True)
    normal: BoolProperty(name="Normal constraint", default=True)
    tangent: BoolProperty(name="Tangent constraint", default=True)
    pole_vector: BoolProperty(name="Pole vector constraint", default=True)

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE'} and context.active_object is not None

    def execute(self, context):
        owner, targets = _owner_and_targets(context)
        if owner is None or not targets:
            self.report({'ERROR'}, MSG_REMOVE_SELECT)
            return {'CANCELLED'}
        types = REMOVE_TYPES if self.remove_all else tuple(t for t in REMOVE_TYPES if getattr(self, t))
        removed = remove_targets(context, owner, targets, types)
        if removed is None:
            self.report({'ERROR'}, MSG_REMOVE_CONSTRAINED)
            return {'CANCELLED'}
        if removed:
            results.result(self, f"Removed {', '.join(f'{n} ({t})' for t, n in removed)} from {owner.name}")
        else:
            results.result(self, f"No selected target constrains {owner.name}")
        return {'FINISHED'}


# --- Set Rest Position ----------------------------------------------------------------------------------

REST_TYPES = ("point", "aim", "orient", "scale", "tangent", "normal", "parent")


def has_offset(con):
    """True when the constraint adds the own channels in (Copy Location / Scale Offset, Copy Rotation mixing): the own
    channels are its offset, so they can't also hold the rest position."""
    if con.type in {'COPY_LOCATION', 'COPY_SCALE'}:
        return con.use_offset
    if con.type == 'COPY_ROTATION':
        return con.mix_mode != 'REPLACE'
    return False


def set_rest(context, node):
    """The constrained channels become the own channels (= what Blender shows at influence 0); nothing moves now.
    Returns (keys written, names of constraints whose own channels are an offset and were left alone)."""
    keys, kept = set(), []
    cons = [(c, maya_type(c)) for c in getattr(node, "constraints", ())]
    cons = [(c, t) for c, t in cons if t in REST_TYPES]
    for c, t in cons:
        if has_offset(c):
            kept.append(c.name)
        else:
            keys.update(CHANNELS[t] + ("s" if c.type == 'CHILD_OF' else ""))   # its inverse is reset below
    for c, t in cons:
        if has_offset(c):
            keys.difference_update(CHANNELS[t])
    if keys:
        bake(context, node, "".join(sorted(keys)))
        # Child Of multiplies the own channels in: a new inverse keeps the object where it is (and moving the
        # target then moves it exactly as before)
        for c, _t in cons:
            if c.type == 'CHILD_OF':
                c.set_inverse_pending = True
        context.view_layer.update()
    return keys, kept


class ALLSET_OT_set_constraint_rest(bpy.types.Operator):
    """Maya Set Rest Position: the constrained objects' current values become where they go when the constraint
    weights are 0"""
    bl_idname = "allset.set_constraint_rest"
    bl_label = "Set Rest Position"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE'}

    def execute(self, context):
        nodes = list(context.selected_pose_bones or ()) if context.mode == 'POSE' else list(context.selected_objects)
        done, kept, constrained = [], [], False
        for n in nodes:
            constrained |= any(maya_type(c) in REST_TYPES for c in getattr(n, "constraints", ()))
            keys, k = set_rest(context, n)
            if keys:
                done.append(n.name)
            kept += k
        if not constrained:
            self.report({'ERROR'}, MSG_REST)
            return {'CANCELLED'}
        if kept:
            self.report({'WARNING'}, f"These keep their offset in the own channels: {', '.join(kept)}")
        if not done:
            return {'FINISHED'}
        results.result(self, f"Rest position set: {', '.join(done)}")
        return {'FINISHED'}


# --- Modify Constrained Axis ----------------------------------------------------------------------------

AXIS_TYPES = ("point", "aim", "orient", "scale", "parent")


def _target_matrix(con):
    t = con.target
    if t is None:
        return Matrix.Identity(4)
    if t.type == 'ARMATURE' and getattr(con, "subtarget", ""):
        pb = t.pose.bones.get(con.subtarget)
        if pb is not None:
            return t.matrix_world @ pb.matrix
    return t.matrix_world.copy()


def _flags(con):
    if con.type == 'CHILD_OF':
        return [con.use_location_x, con.use_location_y, con.use_location_z]
    return [con.use_x, con.use_y, con.use_z]


def _set_flags(con, flags):
    if con.type == 'CHILD_OF':
        for i, a in enumerate("xyz"):
            setattr(con, f"use_location_{a}", flags[i])
            setattr(con, f"use_rotation_{a}", flags[i])
        return
    con.use_x, con.use_y, con.use_z = flags


def modify_axes(context, node, flags, maintain=False):
    """Set the constrained axes of ``node``'s point / orient / scale / parent constraints. Returns (changed, skipped):
    skipped = aim constraints (Blender's Track To always aims on every axis)."""
    changed, skipped = [], []
    is_bone = isinstance(node, bpy.types.PoseBone)
    for c in list(getattr(node, "constraints", ())):
        t = maya_type(c)
        if t not in AXIS_TYPES:
            continue
        if t == "aim":
            if not all(flags):
                skipped.append(c.name)
            continue
        before = _flags(c)
        vis = visual(context, node)
        newly_off = [i for i in range(3) if before[i] and not flags[i]]
        _set_flags(c, flags)
        key = CHANNELS[t]
        if maintain and not is_bone and t in {"point", "scale", "orient"}:
            _maintain(context, node, c, t, vis, flags)
        else:
            if t in {"point", "scale"}:
                c.use_offset = False
            elif t == "orient":
                c.mix_mode = 'REPLACE'
            elif t == "parent":
                # Child Of multiplies the own channels in: a new inverse keeps the object where it is (Maya zeroes
                # the offset without Maintain offset)
                bake(context, node, "trs", matrix=vis)
                c.set_inverse_pending = True
            if newly_off and t != "parent":
                bake(context, node, key, axes=set(newly_off), matrix=vis)
        changed.append(c.name)
    context.view_layer.update()
    return changed, skipped


def _maintain(context, node, con, t, vis, flags):
    """Blender offsets so the object stays where it is now (Maya's Maintain offset)."""
    tm = _target_matrix(con)
    loc, rot, sca = vis.decompose()
    tl, tr, ts = tm.decompose()
    saved = _save(node)
    if t == "point":
        con.use_offset = True                       # result = target + own (world space, axes that follow)
        want = Vector([loc[i] - tl[i] if flags[i] else loc[i] for i in range(3)])
        node.matrix_world = Matrix.LocRotScale(want, rot, sca)
        _restore(node, saved, "t")
    elif t == "scale":
        con.use_offset, con.use_add = True, False   # result = target x own
        want = Vector([sca[i] / ts[i] if flags[i] and abs(ts[i]) > 1e-12 else sca[i] for i in range(3)])
        node.scale = want
    else:                                           # orient: result = target rotation, then the own rotation
        if all(flags):
            con.mix_mode = 'BEFORE'
            own = (tr.inverted() @ rot)
            node.matrix_world = Matrix.LocRotScale(loc, own, sca)
            _restore(node, saved, "r")
        else:
            con.mix_mode = 'REPLACE'
            newly = [i for i in range(3) if not flags[i]]
            bake(context, node, "r", axes=set(newly), matrix=vis)
    context.view_layer.update()


class ALLSET_OT_modify_constraint_axes(bpy.types.Operator):
    """Maya Modify Constrained Axis: which axes the selected objects' point / orient / scale / parent constraints
    drive"""
    bl_idname = "allset.modify_constraint_axes"
    bl_label = "Modify Constrained Axis"
    bl_options = {'REGISTER', 'UNDO'}

    x: BoolProperty(name="X", default=True, description="Enable to make the constraint act upon the X axis")
    y: BoolProperty(name="Y", default=True, description="Enable to make the constraint act upon the Y axis")
    z: BoolProperty(name="Z", default=True, description="Enable to make the constraint act upon the Z axis")
    maintain_offset: BoolProperty(name="Maintain offset", default=False,
                                  description="Preserve the current offset of the constrained objects")

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE'}

    def execute(self, context):
        nodes = list(context.selected_pose_bones or ()) if context.mode == 'POSE' else list(context.selected_objects)
        if not nodes:
            self.report({'ERROR'}, MSG_AXES_SELECT)
            return {'CANCELLED'}
        flags = [self.x, self.y, self.z]
        if not any(flags):
            self.report({'ERROR'}, MSG_AXES_NONE)
            return {'CANCELLED'}
        changed, skipped = [], []
        for n in nodes:
            c, s = modify_axes(context, n, flags, self.maintain_offset)
            changed += c
            skipped += s
        if not changed and not skipped:
            self.report({'ERROR'}, MSG_AXES_INVALID)
            return {'CANCELLED'}
        if skipped:
            self.report({'WARNING'}, f"Blender's Track To aims on every axis: {', '.join(skipped)} unchanged")
        if changed:
            axes = "".join(a for a, f in zip("XYZ", flags) if f)
            results.result(self, f"Constrained axes {axes}: {', '.join(changed)}")
        return {'FINISHED'}
