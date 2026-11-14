# SPDX-License-Identifier: GPL-3.0-or-later
"""L4: Maya multi-target constraints (weighted average).

Maya: a point / orient / parent / scale constraint with several targets is
one node ``<owner>_<type><n>`` with one weight attribute ``<target>W<i>`` per target (default 1.0), the result is the
weighted average with the weights normalised w_i / Σw; every weight 0 = the node's rest position (its pose when the
constraint was made: with Maintain Offset its own pose, without it the targets' blend then).

The kit (one Blender constraint reads one target):
- One Blender constraint per target, stacked in Maya's target order, named ``<group>:<i>:<target>`` (parent: one
  Copy Location + one Copy Rotation ``... R`` per target). The owner (Object / PoseBone) keeps the group in the ID
  property ``allset_cgroups`` ({group: Maya type}) and Maya's weight per target in ``allset_w_<first member name>``
  (float 1.0 — keyable and drivable, Set Driven Key drives exactly these).
- Point / Orient / Parent: influence of member i >= 1 = driver ``w_i / S_i if S_i > 0 else 0.0`` with
  S_i = w_0 + ... + w_i, member 0 = ``1.0 if Σw > 0 else 0.0`` (Blender mixes the stack in order, so these
  influences give exactly the weighted average of the positions; W0 0.5 · W1 0 = target A, like Maya). Every weight 0
  turns every member off: the node shows its own channels, which hold its rest position (``drive_group``). Simple
  expressions only: no Python auto-run needed (``driver.is_simple_expression``).
- Rest position: a node made without Maintain Offset gets its pose at creation (the targets' blend) written into its
  own channels, like Maya (with Maintain Offset that pose is already its own), in the same undo step; keyed or driven
  channels keep their curves. So turning the node off or deleting it leaves the node there, not where it was before.
  Set Rest Position writes them later.
  Groups saved without these drivers (every weight 0 = the equal average) get them when the file loads (``upgrade``).
- One target (a joint following an object): the normalised weight w / w is 1 for any weight above 0, so like Maya
  the node follows its target fully while the weight is above 0 and lets go only at 0 (the joint's own channels,
  Maya's rest position): every member's influence = driver ``SINGLE``. Keyed 0 -> 1, the joint jumps onto the target
  on the first frame after the 0 key. A one-target group saved without that driver, or with the older linear one,
  gets it when the file loads (``upgrade``).
- A one-target constraint outside a group (an object following one object, a joint following one joint) gets the
  same rule once the Channel Box (or an option window) sets or keys its weight: the weight becomes an ID property of
  the owner, ``allset_w_<constraint name>`` (min 0), and the influence follows it through ``SINGLE``
  (``ensure_single_weight``); keys the influence already had move to the weight. Until then the influence is the
  weight, as Blender has it.
- Parent with Maintain Offset (the default, like Maya) / Point / Orient / Scale with Maintain Offset: each target gets a hidden
  helper empty holding the owner's offset from that target (point: Copy Location with offset; else Child Of the
  target with the offset as its own channels). The helpers live in the hidden collection ``.AllsetConstraintHelpers``
  (no scene: not in the Outliner, not exported, still evaluated as constraint targets) and go when their
  constraint goes (``cleanup``, from a depsgraph handler through a timer).
- Scale: Maya's multi-target scale is the weighted geometric mean: member i = Copy Scale with
  ``power = w_i / Σw`` (0 when Σw = 0), the first replaces (influence ``1.0 if Σw > 0 else 0.0``), the others
  multiply (``use_offset``) — exact; every weight 0 = the own scale.
- Rotation: Maya's interpType (orient / parent) — #168, operators/constrain_interp.py: Shortest is the
  rotation members' influence w_i / W_total, the other types (default Average) a kit-computed blend.
"""

import re

import bpy
from mathutils import Matrix

GROUPS = "allset_cgroups"          # owner ID property: {group: Maya node type}
WEIGHT = "allset_w_"               # owner ID property prefix: Maya target weight (allset_w_<member name>)
HELPERS = ".AllsetConstraintHelpers"
H_OWNER = "allset_cmulti_owner"    # helper empty: the owner object (armature for a pose bone owner)
H_BONE = "allset_cmulti_bone"      # helper empty: the owner pose bone name ("" = object)
H_CON = "allset_cmulti_con"        # helper empty: the member constraint that reads it

MAYA_TYPE = {'CHILD_OF': "parentConstraint", 'COPY_LOCATION': "pointConstraint",
             'COPY_ROTATION': "orientConstraint", 'COPY_SCALE': "scaleConstraint"}
TYPES = tuple(MAYA_TYPE)
DEFAULT_OFFSET = {'CHILD_OF': True}      # default Maintain Offset: parent on, point / orient / scale off
# the channels each node type drives (its rest position is kept in them)
REST_CHANNELS = {'COPY_LOCATION': "t", 'COPY_ROTATION': "r", 'CHILD_OF': "tr", 'COPY_SCALE': "s"}
ROT = " R"                               # suffix of a parent group's Copy Rotation member
SINGLE = "1.0 if w0 > 0.0 else 0.0"   # influence of a one-target node: on while its weight is above 0
# Maya constraint nodes whose one-target weight follows SINGLE (Maya normalises the weights of every type)
STEP_NODES = ("parentConstraint", "pointConstraint", "orientConstraint", "scaleConstraint", "aimConstraint",
              "normalConstraint", "tangentConstraint")
_NAME = re.compile(r"^(?P<group>[^:]+):(?P<index>\d+):(?P<label>.*?)(?P<rot> R)?$")


# --- owners ---------------------------------------------------------------------------------------------------------

def _id_and_prefix(owner):
    """(ID object, data path prefix) of an Object or PoseBone owner."""
    if isinstance(owner, bpy.types.PoseBone):
        return owner.id_data, f'pose.bones["{bpy.utils.escape_identifier(owner.name)}"]'
    return owner, ""


def owner_of(con):
    """The Object / PoseBone holding constraint ``con``."""
    ob = con.id_data
    try:
        path = con.path_from_id()
    except (ValueError, AttributeError):
        return ob
    if path.startswith("pose.bones["):
        return ob.path_resolve(path.rsplit(".constraints[", 1)[0])
    return ob


def world(owner):
    if isinstance(owner, bpy.types.PoseBone):
        return owner.id_data.matrix_world @ owner.matrix
    return owner.matrix_world.copy()


def _target_world(ob, sub):
    if sub and ob.type == 'ARMATURE' and sub in ob.pose.bones:
        return ob.matrix_world @ ob.pose.bones[sub].matrix
    return ob.matrix_world.copy()


def _groups(owner):
    g = owner.get(GROUPS)
    return dict(g) if g is not None else {}


# --- group membership -----------------------------------------------------------------------------------------------

class Member:
    __slots__ = ("group", "index", "label", "rot", "con", "owner")

    def __init__(self, m, con, owner):
        self.group, self.index, self.label = m["group"], int(m["index"]), m["label"]
        self.rot, self.con, self.owner = bool(m["rot"]), con, owner

    @property
    def weight_prop(self):
        return weight_prop(self.group, self.index, self.label)


def weight_prop(group, index, label):
    return f"{WEIGHT}{group}:{index}:{label}"


def member(con, owner=None):
    """``Member`` when ``con`` belongs to a kit multi-target group, else None."""
    m = _NAME.match(con.name)
    if m is None:
        return None
    owner = owner if owner is not None else owner_of(con)
    if m["group"] not in _groups(owner):
        return None
    return Member(m, con, owner)


def members(owner, group):
    """Constraints of ``group`` on ``owner`` in stack order."""
    out = []
    for c in owner.constraints:
        m = _NAME.match(c.name)
        if m is not None and m["group"] == group:
            out.append(c)
    return out


def is_head(con, owner=None):
    """True for a constraint that stands for a Maya node: an ungrouped one, or the first member of its group."""
    mb = member(con, owner)
    if mb is None:
        return True
    ms = members(mb.owner, mb.group)
    return bool(ms) and ms[0] == con


def head_of(con, owner=None):
    """The constraint that stands for ``con``'s Maya node: a group's first member; an Interp Type blend's
    group head; an aim's Object up turn (``rig_tools.UP_SUFFIX``) = that aim."""
    mb = member(con, owner)
    if mb is None:
        from . import constrain_interp, rig_tools
        owner = owner if owner is not None else owner_of(con)
        if constrain_interp.is_blend(con):
            ms = members(owner, con.name[:-len(constrain_interp.BLEND)])
            return ms[0] if ms else con
        if rig_tools.is_up_companion(con):
            return owner.constraints.get(con.name[:-len(rig_tools.UP_SUFFIX)]) or con
        return con
    ms = members(mb.owner, mb.group)
    return ms[0] if ms else con


def group_type(con, owner=None):
    """Maya node type of a grouped constraint (a parent group's Copy Location = parentConstraint), else None."""
    mb = member(con, owner)
    return _groups(mb.owner).get(mb.group) if mb is not None else None


def weights(owner, group):
    """[(weight property, Maya weight attribute label <target>W<i>)] of a group, in target order."""
    seen, out = set(), []
    for c in members(owner, group):
        m = _NAME.match(c.name)
        i = int(m["index"])
        if i in seen:
            continue
        seen.add(i)
        out.append((weight_prop(group, i, m["label"]), f"{m['label']}W{i}"))
    return out


def set_enabled(owner, group, on):
    from . import constrain_interp
    blend = constrain_interp.blend_constraint(owner, group)
    for c in members(owner, group) + ([blend] if blend is not None else []):
        if hasattr(c, "enabled"):
            c.enabled = on
        else:
            c.mute = not on


# --- helpers --------------------------------------------------------------------------------------------------------

def _helper_collection():
    coll = bpy.data.collections.get(HELPERS)
    if coll is None:
        coll = bpy.data.collections.new(HELPERS)
        coll.use_fake_user = True         # in no scene: kept by its fake user, not in the Outliner / exports
    return coll


def _helper(owner, name, target, sub, offset_world, point):
    """Hidden empty at the owner's offset from (target, sub): point = Copy Location (+ offset, Maya's point offset is a
    translation), else Child Of the target with the offset as its own channels (orient / parent / scale offset)."""
    h = bpy.data.objects.new(name, None)
    h.empty_display_size = 0.0
    h.hide_viewport = h.hide_render = h.hide_select = True
    _helper_collection().objects.link(h)
    id_ob, _prefix = _id_and_prefix(owner)
    h[H_OWNER] = id_ob
    h[H_BONE] = owner.name if isinstance(owner, bpy.types.PoseBone) else ""
    tw = _target_world(target, sub)
    if point:
        h.location = offset_world.translation - tw.translation
        c = h.constraints.new('COPY_LOCATION')
        c.use_offset = True
    else:
        h.matrix_basis = tw.inverted_safe() @ offset_world
        c = h.constraints.new('CHILD_OF')
        c.inverse_matrix = Matrix.Identity(4)
        c.set_inverse_pending = False
    c.target = target
    if sub:
        c.subtarget = sub
    return h


def helpers():
    # register() runs with Blender's restricted data while add-ons load at start-up / install (no ``collections``):
    # nothing to find then; load_post handlers look again once the file is loaded
    colls = getattr(bpy.data, "collections", None)
    coll = colls.get(HELPERS) if colls is not None else None
    return list(coll.objects) if coll is not None else []


def helper_of(con):
    t = getattr(con, "target", None)
    return t if t is not None and H_CON in t.keys() else None


# --- drivers --------------------------------------------------------------------------------------------------------

def _sum(n):
    return "+".join(f"w{j}" for j in range(n))


def any_weight(n):
    """Influence of the member that starts a node of ``n`` targets (and of its Interp Type blend): on while any weight
    is above 0, off when every weight is 0 (the node's rest position = its own channels)."""
    return f"1.0 if ({_sum(n)}) > 0 else 0.0"


def share(k, n):
    """w_k / (w_0 + ... + w_(n-1)), 0 when those weights are all 0."""
    s = _sum(n)
    return f"w{k} / ({s}) if ({s}) > 0 else 0.0"


def _var_path(prefix, prop):
    return prefix + f'["{bpy.utils.escape_identifier(prop)}"]'


def _write(con, prop, owner, names, expression):
    """Driver on ``con.<prop>``: ``expression`` of the weight properties ``names`` (variables w0, w1 ...)."""
    id_ob, prefix = _id_and_prefix(owner)
    fc = con.driver_add(prop)
    d = fc.driver
    d.type = 'SCRIPTED'
    while d.variables:
        d.variables.remove(d.variables[0])
    for j, wp in enumerate(names):
        v = d.variables.new()
        v.name = f"w{j}"
        v.type = 'SINGLE_PROP'
        v.targets[0].id = id_ob
        v.targets[0].data_path = _var_path(prefix, wp)
    d.expression = expression
    for m in list(fc.modifiers):          # driver_add makes a Generator: the expression alone is the value
        fc.modifiers.remove(m)
    return fc


def _drive(con, prop, owner, names, k, scale=False):
    """Driver on ``con.<prop>`` from the weight properties ``names`` (target order) — cumulative influence of member k
    >= 1 (point / orient / parent), the geometric-mean power w_k / Σw (scale), or on / off by the weight when the node
    has one target (``SINGLE``)."""
    if len(names) == 1 and not scale:
        return _write(con, prop, owner, names, SINGLE)
    if scale:
        return _write(con, prop, owner, names, share(k, len(names)))
    return _write(con, prop, owner, names[:k + 1], share(k, k + 1))


def _unique_group(owner, mtype):
    taken = set(_groups(owner))
    for c in owner.constraints:
        m = _NAME.match(c.name)
        if m is not None:
            taken.add(m["group"])
    n = 1
    while f"{mtype}{n}" in taken:
        n += 1
    return f"{mtype}{n}"


def target_label(target, sub):
    return sub if sub and target.type == 'ARMATURE' else target.name


def _joint_from_object():
    from .joints import JOINT_AXES, MAYA_WORLD
    return (MAYA_WORLD @ JOINT_AXES.transposed()).to_4x4()


# an object's Maya axes are its Blender X / Z / -Y (joints.MAYA_WORLD), a joint's are its bone's Y / Z / X
# (joints.JOINT_AXES), so a bone copying an object's rotation has to copy the object's frame turned by
# MAYA_WORLD JOINT_AXES^-1 (Maya orientConstraint / parentConstraint without offset: the joint's axes = the target's;
# 90 deg off before). A bone target needs nothing.


def needs_joint_axes(owner, target, sub, ctype):
    """A joint (pose bone) copying the rotation of an object (not of a bone)."""
    return (isinstance(owner, bpy.types.PoseBone) and ctype in ('COPY_ROTATION', 'CHILD_OF')
            and not (sub and target.type == 'ARMATURE'))


def build(context, owner, targets, ctype, maintain_offset=None, weight=1.0):
    """Maya multi-target constraint on ``owner`` (Object / PoseBone) from ``targets`` [(object, subtarget)] in Maya
    target order. Returns the group's first constraint."""
    if ctype not in MAYA_TYPE:
        raise ValueError(ctype)
    if maintain_offset is None:
        maintain_offset = DEFAULT_OFFSET.get(ctype, False)
    mtype = MAYA_TYPE[ctype]
    group = _unique_group(owner, mtype)
    groups = _groups(owner)
    groups[group] = mtype
    owner[GROUPS] = groups
    ow = world(owner)
    owner_name = owner.name
    labels = []
    for i, (t, sub) in enumerate(targets):
        label = target_label(t, sub)
        labels.append(label)
        owner[weight_prop(group, i, label)] = float(weight)
    names = [weight_prop(group, i, lab) for i, lab in enumerate(labels)]
    cons = owner.constraints
    first = None
    for i, (t, sub) in enumerate(targets):
        base = f"{group}:{i}:{labels[i]}"
        src, src_sub = t, sub
        if maintain_offset:
            src = _helper(owner, f"{owner_name}_{group}_{labels[i]}Offset", t, sub, ow, ctype == 'COPY_LOCATION')
            src_sub = ""
        elif needs_joint_axes(owner, t, sub, ctype):
            # a joint takes the target's Maya axes, not its Blender ones (joints.JOINT_AXES)
            src = _helper(owner, f"{owner_name}_{group}_{labels[i]}Axes", t, sub,
                          _target_world(t, sub) @ _joint_from_object(), False)
            src_sub = ""
        kinds = (('COPY_LOCATION', base), ('COPY_ROTATION', base + ROT)) if ctype == 'CHILD_OF' else ((ctype, base),)
        for btype, name in kinds:
            c = cons.new(btype)
            c.name = name
            c.target = src
            if src_sub:
                c.subtarget = src_sub
            if src is not t:
                src[H_CON] = base if H_CON not in src.keys() else src[H_CON]
            if btype == 'COPY_SCALE':
                c.use_offset = i > 0              # the first replaces, the others multiply
                c.use_add = False
                if len(names) == 1:
                    _drive(c, "power", owner, names, i, scale=True)
            if len(names) == 1:
                _drive(c, "influence", owner, names, 0)       # one target: on while its weight is above 0
            if first is None:
                first = c
    if len(names) > 1:
        drive_group(owner, group)
    _state["armed"] = True
    if ctype in ('COPY_ROTATION', 'CHILD_OF') and len(targets) > 1:
        # #168: Maya interpType, default Average (operators/constrain_interp.py); one target = its own
        # rotation whatever the type (Maya: fewer than 2 targets blend as Average = that target)
        from . import constrain_interp
        constrain_interp.set_mode(context, owner, group, constrain_interp.AVERAGE)
    owner.id_data.update_tag()
    context.view_layer.update()
    if len(names) > 1 and not maintain_offset:
        # Maya: the rest position (every weight 0) is the node's pose when the constraint is made, here the targets'
        # blend; the own channels hold it (what Blender shows at influence 0), like Set Rest Position
        _keep_rest(context, owner, REST_CHANNELS[ctype])
    return first


def _animated(owner, letter):
    """Indices of channel ``letter`` ("t" / "r" / "s", rotation: the node's rotation mode) that a key or a driver sets:
    their curve wins over any value written there."""
    id_ob, prefix = _id_and_prefix(owner)
    if letter == "r":
        name = {'QUATERNION': "rotation_quaternion", 'AXIS_ANGLE': "rotation_axis_angle"}.get(owner.rotation_mode,
                                                                                            "rotation_euler")
    else:
        name = "location" if letter == "t" else "scale"
    path = prefix + ("." if prefix else "") + name
    from .. import compat
    ad = id_ob.animation_data
    fcs = list(compat.id_fcurves(id_ob)) + (list(ad.drivers) if ad is not None else [])
    return {fc.array_index for fc in fcs if fc.data_path == path}


def _keep_rest(context, owner, letters):
    """Write the node's current pose into its own channels ``letters``, except the keyed or driven ones (they keep their
    curve; a quaternion / axis-angle rotation with any curve stays whole)."""
    from .constrain_199 import bake
    for letter in letters:
        busy = _animated(owner, letter)
        if not busy:
            bake(context, owner, letter)
        elif letter != "r" or owner.rotation_mode not in ('QUATERNION', 'AXIS_ANGLE'):
            free = {0, 1, 2} - busy
            if free:
                bake(context, owner, letter, axes=free)


def drive_single(owner, group):
    """A node with one target: its weight drives the influence of the constraints that apply the node (``SINGLE``;
    with an Interp Type blend, the blend instead of the rotation members it stands for). Adds only the drivers that
    are missing or differ; returns how many it wrote."""
    ws = weights(owner, group)
    if len(ws) != 1:
        return 0
    from . import constrain_interp
    blend = constrain_interp.blend_constraint(owner, group)
    skip = {c.name for c in constrain_interp.rotation_members(owner, group)} if blend is not None else set()
    id_ob, _prefix = _id_and_prefix(owner)
    source = f'["{bpy.utils.escape_identifier(ws[0][0])}"]'
    n = 0
    for c in members(owner, group) + ([blend] if blend is not None else []):
        if c.name in skip:
            continue
        ad = id_ob.animation_data
        fc = ad.drivers.find(c.path_from_id("influence")) if ad is not None else None
        d = fc.driver if fc is not None else None
        if (d is not None and d.expression == SINGLE and len(d.variables) == 1
                and d.variables[0].targets[0].data_path.endswith(source)):
            continue
        _drive(c, "influence", owner, [ws[0][0]], 0)
        n += 1
    return n


def _group_drivers(owner, group):
    """The weight drivers a node with two or more targets needs: [(constraint, property, weight properties,
    expression)]. Location members (and the rotation members of groups older than Interp Type) blend cumulatively,
    Shortest rotation members by w_k / Σw, the other Interp Types through the group's blend constraint; the first member
    (and the blend) is on while any weight is above 0, so every weight 0 leaves the node on its own channels."""
    from . import constrain_interp
    names, index = [], {}
    for c in members(owner, group):
        m = _NAME.match(c.name)
        i = int(m["index"])
        if i not in index:
            index[i] = len(names)
            names.append(weight_prop(group, i, m["label"]))
    n = len(names)
    mode = constrain_interp.mode_of(owner, group)
    rot = {c.name for c in constrain_interp.rotation_members(owner, group)}
    blend = constrain_interp.blend_constraint(owner, group)
    out = []
    for c in members(owner, group):
        k = index[int(_NAME.match(c.name)["index"])]
        if c.type == 'COPY_SCALE':
            out.append((c, "power", names, share(k, n)))
            if k == 0:
                out.append((c, "influence", names, any_weight(n)))
        elif c.name in rot and mode is not None and mode != constrain_interp.SHORTEST:
            continue                      # off: the blend applies them
        elif k == 0:
            out.append((c, "influence", names, any_weight(n)))
        elif c.name in rot and mode == constrain_interp.SHORTEST:
            out.append((c, "influence", names, share(k, n)))
        else:
            out.append((c, "influence", names[:k + 1], share(k, k + 1)))
    if blend is not None:
        out.append((blend, "influence", names, any_weight(n)))
    return out


def _driver(con, prop, owner):
    id_ob, _prefix = _id_and_prefix(owner)
    ad = id_ob.animation_data
    if ad is None:
        return None
    try:
        return ad.drivers.find(con.path_from_id(prop))
    except (ValueError, AttributeError):
        return None


def _is_weight_driver(fc, owner, names=None, expression=None):
    """True when F-curve ``fc`` is a kit weight driver (every variable reads an ``allset_w_`` property of the owner);
    with ``names`` / ``expression``: exactly that driver."""
    d = fc.driver
    if d.type != 'SCRIPTED' or (expression is not None and d.expression != expression):
        return False
    id_ob, prefix = _id_and_prefix(owner)
    vs = list(d.variables)
    if names is not None and len(vs) != len(names):
        return False
    for j, v in enumerate(vs):
        t = v.targets[0]
        if v.type != 'SINGLE_PROP' or t.id != id_ob:
            return False
        if names is not None:
            if v.name != f"w{j}" or t.data_path != _var_path(prefix, names[j]):
                return False
        elif not t.data_path.startswith(prefix + '["' + WEIGHT):
            return False
    return True


def drive_group(owner, group):
    """Give a node its weight drivers (``_group_drivers``; one target: ``drive_single``). Writes only the ones that are
    missing or differ; a driver that reads anything but the node's weights (the user's own) stays. Returns how many
    it wrote."""
    if len(weights(owner, group)) < 2:
        return drive_single(owner, group)
    n = 0
    for c, prop, names, expression in _group_drivers(owner, group):
        fc = _driver(c, prop, owner)
        if fc is not None and (_is_weight_driver(fc, owner, names, expression)
                               or not _is_weight_driver(fc, owner)):
            continue
        _write(c, prop, owner, names, expression)
        n += 1
    return n


# --- one-target constraints outside a group: the weight as its own value ---------------------------------------------

def weight_path(owner, prop):
    """Data path of owner ID property ``prop`` on the owner's ID (pose bones: on the armature object)."""
    _id_ob, prefix = _id_and_prefix(owner)
    return prefix + f'["{bpy.utils.escape_identifier(prop)}"]'


def _influence_driver(con, owner):
    id_ob, _prefix = _id_and_prefix(owner)
    ad = id_ob.animation_data
    if ad is None:
        return None
    try:
        return ad.drivers.find(con.path_from_id("influence"))
    except (ValueError, AttributeError):
        return None


def single_weight(con, owner=None):
    """The owner ID property holding the weight of ``con``, a one-target constraint outside a group whose influence
    follows it (``SINGLE``), or None while the influence is the weight. Found through the influence driver, so a
    renamed constraint keeps its weight."""
    owner = owner if owner is not None else owner_of(con)
    if member(con, owner) is not None:
        return None
    fc = _influence_driver(con, owner)
    d = fc.driver if fc is not None else None
    if d is None or d.expression != SINGLE or len(d.variables) != 1:
        return None
    t = d.variables[0].targets[0]
    id_ob, prefix = _id_and_prefix(owner)
    head = prefix + '["'
    path = t.data_path
    if t.id != id_ob or not (path.startswith(head) and path.endswith('"]')):
        return None
    prop = bpy.utils.unescape_identifier(path[len(head):-2])
    return prop if prop.startswith(WEIGHT) and prop in owner.keys() else None


def single_applies(con, owner=None):
    """True when ``con``'s Channel Box weight follows Maya's one-target rule (``ensure_single_weight``): a Maya
    constraint node type (``STEP_NODES``) outside a group whose influence no other driver (Set Driven Key, a
    user's driver) feeds."""
    owner = owner if owner is not None else owner_of(con)
    if member(con, owner) is not None:
        return False
    if single_weight(con, owner) is not None:
        return True
    from ..ui import channel_box
    if channel_box.maya_constraint_type(con) not in STEP_NODES:
        return False
    return _influence_driver(con, owner) is None


def _companions(con, owner):
    """Constraints that are part of ``con``'s Maya node and follow its weight: an aim's Object up turn."""
    from . import rig_tools
    c = owner.constraints.get(con.name + rig_tools.UP_SUFFIX)
    return [c] if c is not None and rig_tools.is_up_companion(c) else []


def _drop_weight(owner, prop):
    """Remove owner ID property ``prop`` and the curves keyed on it."""
    from .. import compat
    id_ob, _prefix = _id_and_prefix(owner)
    path = weight_path(owner, prop)
    fcs = compat.id_fcurve_collection(id_ob)
    if fcs is not None:
        for fc in [f for f in fcs if f.data_path == path]:
            fcs.remove(fc)
    ad = id_ob.animation_data
    if ad is not None:
        for fc in [f for f in ad.drivers if f.data_path == path]:
            ad.drivers.remove(fc)
    if prop in owner.keys():
        del owner[prop]


def ensure_single_weight(con, owner=None):
    """Give one-target constraint ``con`` its own weight (an owner ID property, min 0, like Maya) holding its
    current influence, move the keys of the influence onto it and drive the influence by it (``SINGLE``: on while
    the weight is above 0, like Maya). Returns the property, or None when the rule does not apply
    (``single_applies``)."""
    owner = owner if owner is not None else owner_of(con)
    prop = single_weight(con, owner)
    if prop is not None:
        return prop
    if not single_applies(con, owner):
        return None
    from .. import compat
    id_ob, _prefix = _id_and_prefix(owner)
    taken = {p for c in owner.constraints if c != con for p in [single_weight(c, owner)] if p is not None}
    prop, n = WEIGHT + con.name, 1
    while prop in taken:               # a renamed constraint still reads the weight named after its old name
        prop, n = f"{WEIGHT}{con.name}.{n:03d}", n + 1
    value = max(0.0, float(con.influence))
    _drop_weight(owner, prop)          # left by a deleted constraint of the same name
    owner[prop] = value
    try:
        owner.id_properties_ui(prop).update(min=0.0, soft_min=0.0)
    except TypeError:
        pass
    fcs = compat.id_fcurve_collection(id_ob)
    fc = fcs.find(con.path_from_id("influence")) if fcs is not None else None
    if fc is not None:
        fc.data_path = weight_path(owner, prop)     # the keys, tangents and mute state stay with the weight
    for c in [con] + _companions(con, owner):
        _drive(c, "influence", owner, [prop], 0)
    _state["armed"] = True
    id_ob.update_tag()
    return prop


def set_weight(con, value, owner=None):
    """An option window's Weight on one-target constraint ``con``: its own weight (``ensure_single_weight``; any
    weight above 0 = fully on the target, like Maya), or its influence where that rule does not apply. Weight 1 on a
    constraint without its own weight is its influence 1 already. Returns the weight property or None."""
    owner = owner if owner is not None else owner_of(con)
    value = max(0.0, float(value))
    prop = single_weight(con, owner)
    if prop is None and value != 1.0:
        prop = ensure_single_weight(con, owner)
    if prop is None:
        con.influence = value
        return None
    owner[prop] = value
    owner.id_data.update_tag()
    return prop


def _drop_orphan_weights(owner):
    """Remove one-target weights no constraint reads any more (its constraint was deleted, which drops the driver).
    Returns the number removed."""
    if getattr(owner.id_data, "library", None) is not None:      # linked data is read-only here
        return 0
    groups = _groups(owner)
    read = {p for c in owner.constraints for p in [single_weight(c, owner)] if p is not None}
    n = 0
    for prop in [k for k in owner.keys() if k.startswith(WEIGHT)]:
        if prop in read or any(prop.startswith(f"{WEIGHT}{g}:") for g in groups):
            continue
        _drop_weight(owner, prop)
        n += 1
    return n


def upgrade():
    """Give the groups of older files today's weight drivers (one target: on / off by its weight; several: every
    weight 0 = the own channels). Returns drivers written."""
    n = 0
    for owner in list(_owners()):
        for group in list(_groups(owner)):
            if members(owner, group):
                n += drive_group(owner, group)
    return n


def remove_group(owner, group):
    """Delete a group: its constraints, their drivers, weight properties and helper empties."""
    id_ob, prefix = _id_and_prefix(owner)
    from . import constrain_interp
    constrain_interp._remove_blend(owner, group)
    for key in (constrain_interp.INTERP, constrain_interp.LAST, constrain_interp.REST, constrain_interp.OFFSET):
        if key + group in owner.keys():
            del owner[key + group]
    hs = []
    for c in members(owner, group):
        h = helper_of(c)
        if h is not None:
            hs.append(h)
        for prop in ("influence", "power"):
            try:
                c.driver_remove(prop)
            except TypeError:
                pass
        owner.constraints.remove(c)
    for k in [k for k in owner.keys() if k.startswith(f"{WEIGHT}{group}:")]:
        del owner[k]
    groups = _groups(owner)
    groups.pop(group, None)
    if groups:
        owner[GROUPS] = groups
    elif GROUPS in owner.keys():
        del owner[GROUPS]
    for h in dict.fromkeys(hs):
        try:
            bpy.data.objects.remove(h, do_unlink=True)
        except ReferenceError:
            pass


# --- cleanup (a deleted owner / cleared constraints leave helpers, drivers and weights behind) -----------------------

def _is_owner(node):
    """A node holding a group or a one-target weight (``ensure_single_weight``)."""
    return any(k == GROUPS or k.startswith(WEIGHT) for k in node.keys())


def _owners():
    for ob in bpy.data.objects:
        if _is_owner(ob):
            yield ob
        if ob.type == 'ARMATURE' and ob.pose is not None:
            for pb in ob.pose.bones:
                if _is_owner(pb):
                    yield pb


def cleanup():
    """Drop helpers whose constraint is gone, groups with no constraint left and one-target weights whose constraint
    is gone. Returns the number of removals."""
    n = 0
    for h in helpers():
        owner = h.get(H_OWNER)
        con_name = h.get(H_CON, "")
        alive = False
        if owner is not None:
            bone = h.get(H_BONE, "")
            node = owner.pose.bones.get(bone) if bone and owner.pose is not None else (None if bone else owner)
            if node is not None:
                alive = any(helper_of(c) == h for c in node.constraints if c.name.startswith(con_name))
                partner = h.get("allset_aim_up")       # an aim's up helper goes with its aim
                if alive and partner and node.constraints.get(partner) is None:
                    alive = False
                    for c in [c for c in node.constraints if helper_of(c) == h]:
                        node.constraints.remove(c)
        if not alive:
            bpy.data.objects.remove(h, do_unlink=True)
            n += 1
    for owner in list(_owners()):
        for group in list(_groups(owner)):
            if not members(owner, group):
                id_ob, prefix = _id_and_prefix(owner)
                ad = id_ob.animation_data
                if ad is not None:
                    from .constrain_interp import BLEND
                    base = f'{prefix}{"." if prefix else ""}constraints["{group}'
                    want = (base + ":", base + BLEND + '"]')         # the members and the Interp Type blend
                    for fc in [f for f in ad.drivers if f.data_path.startswith(want)]:
                        ad.drivers.remove(fc)
                remove_group(owner, group)
                n += 1
        n += _drop_orphan_weights(owner)
    return n


_state = {"pending": False, "armed": False}


def _tick():
    _state["pending"] = False
    try:
        cleanup()
        upgrade()
    except Exception:          # never break the timer loop
        pass
    return None


@bpy.app.handlers.persistent
def _on_depsgraph(_scene, _depsgraph):
    # armed once a group exists in this session (build / file load): at most one cleanup scan per 0.3 s
    if _state["pending"] or not (_state["armed"] or bpy.data.collections.get(HELPERS) is not None):
        return
    _state["pending"] = True
    bpy.app.timers.register(_tick, first_interval=0.3)


@bpy.app.handlers.persistent
def _on_load(*_args):
    _state["armed"] = bpy.data.collections.get(HELPERS) is not None or any(True for _ in _owners())
    if _state["armed"]:
        try:
            upgrade()
        except (ReferenceError, AttributeError, RuntimeError, TypeError):
            pass


# --- Channel Box node state (one Maya node = every member) ----------------------------------------------------------

class ALLSET_OT_constraint_group_enable(bpy.types.Operator):
    """Turn the Maya constraint node on / off (every Blender constraint of the multi-target group)"""
    bl_idname = "allset.constraint_group_enable"
    bl_label = "Constraint Node State"
    bl_options = {'UNDO', 'INTERNAL'}

    object: bpy.props.StringProperty()
    bone: bpy.props.StringProperty()
    group: bpy.props.StringProperty()

    def execute(self, context):
        ob = bpy.data.objects.get(self.object)
        owner = ob.pose.bones.get(self.bone) if ob is not None and self.bone and ob.pose is not None else ob
        if owner is None:
            return {'CANCELLED'}
        ms = members(owner, self.group)
        if not ms:
            return {'CANCELLED'}
        on = not (ms[0].enabled if hasattr(ms[0], "enabled") else not ms[0].mute)
        set_enabled(owner, self.group, on)
        ob.update_tag()
        return {'FINISHED'}


classes = (ALLSET_OT_constraint_group_enable,)


def register_props():
    if _on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister_props():
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _state["pending"] = False
