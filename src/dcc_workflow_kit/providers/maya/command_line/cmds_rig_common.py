# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared lookups of the maya.cmds rig commands: the ID property names, the Maya constraint node registry kept on
each constrained object (find, list, name, aliases, the channels something else drives), channel values after
constraints (``constrained_values``, ``maya_euler``) and the joint lookup (``find_joint``, ``joint_world``,
``joint_local``). Used by cmds_constraints.py, cmds_joints.py, cmds_connections.py and cmds_rig.py."""

import math
import types

import bpy
from mathutils import Matrix, Vector

from .cmds_shim import _from_bu, _from_rad, _view_layer

NODES = "allset_cmds_nodes"          # object ID property: Maya constraint nodes {name: {type, targets, ...}}
JOINT_RADIUS = "allset_radius"       # bone ID property: Maya joint radius (default 1)
JOINT_ORIENT = "allset_joint_orient"  # bone ID property: Maya jointOrient in radians (cmds.joint makes 0 0 0)
UP_PREFIX = ".allset_up_"            # hidden helper (no scene, fake user): an aim node's world-up space

CHANNELS = {"parentConstraint": "tr", "pointConstraint": "t", "orientConstraint": "r", "scaleConstraint": "s",
            "aimConstraint": "r"}
CONSTRAINT_TYPES = tuple(CHANNELS)
MAIN_KEYS = tuple(c + a for c in "trs" for a in "xyz")

# Maya attribute names <-> Connection Editor leaves (ui/connection_editor.SIMPLE / COMPOUNDS)
_LONG = {"tx": "translateX", "ty": "translateY", "tz": "translateZ", "rx": "rotateX", "ry": "rotateY",
         "rz": "rotateZ", "sx": "scaleX", "sy": "scaleY", "sz": "scaleZ", "v": "visibility", "t": "translate",
         "r": "rotate", "s": "scale"}
_KEY = {"translateX": "tx", "translateY": "ty", "translateZ": "tz", "rotateX": "rx", "rotateY": "ry",
        "rotateZ": "rz", "scaleX": "sx", "scaleY": "sy", "scaleZ": "sz", "visibility": "v"}


def _cb():
    from ..ui import channel_box
    return channel_box


# --- constraint nodes ----------------------------------------------------------------------------------------------

def _registry(ob):
    d = ob.get(NODES)
    return d.to_dict() if d is not None and hasattr(d, "to_dict") else {}


def _store(ob, reg):
    if reg:
        ob[NODES] = reg
    elif NODES in ob.keys():
        del ob[NODES]


def _owners():
    return [o for o in bpy.data.objects if NODES in o.keys()]


def nodes_of(ob):
    """[(node name, entry)] of ``ob`` in creation order (Maya lists them after the shape)."""
    return list(_registry(ob).items())


def find_node(name):
    """(owner, node name, entry) of the Maya constraint node ``name``, else None."""
    short = str(name).rsplit("|", 1)[-1]
    for ob in _owners():
        entry = _registry(ob).get(short)
        if entry is not None:
            return ob, short, entry
    return None


def _node_of_type(ob, mtype):
    return next((n for n, e in nodes_of(ob) if e["type"] == mtype), None)


def _cons(ob, entry):
    """The node's Blender constraints, in target order."""
    return [c for c in (ob.constraints.get(n) for n in entry["targets"]) if c is not None]


def _target(con):
    return getattr(con, "target", None)


def _aliases(ob, entry):
    out = []
    for cname, info in entry["targets"].items():
        con = ob.constraints.get(cname)
        tgt = _target(con) if con is not None else None
        out.append(f"{tgt.name if tgt is not None else ''}W{info['i']}")
    return out


def _taken_names():
    names = {o.name for o in bpy.data.objects} | set(joint_names())
    for ob in _owners():
        names |= set(_registry(ob))
    return names


def _new_node_name(owner, mtype, name=None):
    from ..operators import naming
    taken = _taken_names()
    if name:
        if name not in taken:
            return name
        base = naming.base_name(name)
        return f"{base}{naming.next_number(base, taken)}"
    base = f"{owner.name}_{mtype}"
    return f"{base}{naming.next_number(base, taken)}"


def _keys_of(cons):
    """Channel keys the Blender constraints ``cons`` drive (the Channel Box's rule)."""
    return set(_cb().constrained_keys(types.SimpleNamespace(constraints=list(cons))))


def _foreign_keys(ob, node=None):
    """Channels of ``ob`` that something other than ``node`` drives: other constraints, connections / drivers."""
    own = set(_registry(ob).get(node, {}).get("targets", {})) if node else set()
    keys = _keys_of(c for c in ob.constraints if c.name not in own)
    cb = _cb()
    keys |= {k for k in MAIN_KEYS + ("v",) if cb.driver(ob, k) is not None}
    return keys


def _raw_frame(ob):
    """World matrix of ``ob``'s parent space (the constraint stack works after it)."""
    if ob.parent is not None and ob.parent_type == 'OBJECT':
        return ob.parent.matrix_world @ ob.matrix_parent_inverse
    return Matrix.Identity(4)


def _own_world(ob):
    """``ob``'s world matrix without its constraints."""
    return _raw_frame(ob) @ ob.matrix_basis


def _no_scale(m):
    t, q, _s = m.decompose()
    return Matrix.LocRotScale(t, q, None)


def evaluated_local(ob):
    """Maya's local matrix of ``ob`` after its constraints (without the pivot offset): what Maya's channels read."""
    return Matrix.Translation(-Vector(ob.delta_location)) @ _raw_frame(ob).inverted_safe() @ ob.matrix_world


def maya_euler(m3, order='XYZ'):
    """Maya's Euler angles of a rotation: the middle axis within +-90 degrees (Maya: aim (0 1 0) / up (1 0 0) ->
    -180 0 135, where Blender's ``to_euler`` gives -0 180 -45, the smaller angle sum)."""
    e = list(m3.to_euler(order))
    mid = "XYZ".index(order[1])
    if abs(e[mid]) > math.pi / 2 + 1e-6:
        for i in range(3):
            if i == mid:
                e[i] = math.pi - e[i]
                e[i] = e[i] - 2 * math.pi if e[i] > math.pi else e[i] + 2 * math.pi if e[i] <= -math.pi else e[i]
            else:
                e[i] = e[i] - math.pi if e[i] >= 0 else e[i] + math.pi
    return e


def _channel_values(ob, m):
    """{key: Maya value} of the local matrix ``m`` (BU)."""
    t, _q, s = m.decompose()
    order = ob.rotation_mode if ob.rotation_mode in ('XYZ', 'YZX', 'ZXY', 'XZY', 'YXZ', 'ZYX') else 'XYZ'
    e = maya_euler(m.to_3x3().normalized(), order)
    out = {}
    for i, a in enumerate("xyz"):
        out["t" + a] = _from_bu(t[i])
        out["r" + a] = _from_rad(e[i])
        out["s" + a] = s[i]
    return out


def constrained_values(ob):
    """{key: Maya channel value} for the channels of ``ob`` its constraints drive (Maya's channels hold the
    constraint's output; Blender's keep the object's own values under the constraint)."""
    keys = _keys_of(ob.constraints) & set(MAIN_KEYS)
    if not keys:
        return {}
    _view_layer()
    vals = _channel_values(ob, evaluated_local(ob))
    return {k: vals[k] for k in keys}


# --- joints --------------------------------------------------------------------------------------------------------

def _skeletons():
    return [o for o in bpy.context.scene.objects if o is not None and o.type == 'ARMATURE']


def joint_names():
    return [b.name for arm in _skeletons() for b in arm.data.bones]


def find_joint(name):
    """(armature object, bone) of the Maya joint ``name``, else None."""
    short = str(name).rsplit("|", 1)[-1]
    for arm in _skeletons():
        b = arm.data.bones.get(short)
        if b is not None:
            return arm, b
    return None


def joint_world(arm, bone):
    """Maya world matrix of a joint: its position, the pose turn (jointOrient 0: the bone's rest axis is not Maya's)."""
    pb = arm.pose.bones[bone.name]
    turn = (pb.matrix @ bone.matrix_local.inverted()).to_3x3()
    m = turn.to_4x4()
    m.translation = pb.head
    return arm.matrix_world @ m


def _joint_parent_world(arm, bone):
    if bone.parent is not None:
        return joint_world(arm, bone.parent)
    from .cmds_shim import _frame
    return _frame(arm) @ Matrix.Translation(-Vector(arm.delta_location))


def joint_local(arm, bone):
    return _joint_parent_world(arm, bone).inverted_safe() @ joint_world(arm, bone)
