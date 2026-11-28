# SPDX-License-Identifier: GPL-3.0-or-later
"""maya.cmds look-alike 3 (Issue #122): freeze, constraints, joints, connections.

Numbers follow the rest of the look-alike (cmds_shim.py): lengths in Maya units, Blender's axes as they are.

- makeIdentity = Modify > Freeze / Reset Transformations (``operators/freeze.py``: channels 0 / 0 / 1, the pivot kept
  in ``delta_location``, children frozen too).
- Constraints = Blender constraints like Constrain > ... (``ui/channel_box`` shows them as INPUTS nodes): one Maya
  node = one Blender constraint per target (influence w_i / (w_1 + ... + w_i), so the stack gives Maya's weighted
  blend). Maya's node name ``<constrained>_<type>N`` is fixed at creation (a rename doesn't follow), so it
  is kept in the object's ID property ``NODES`` with the targets' weight / alias index. Without Maintain Offset:
  point = Copy Location, orient = Copy Rotation, scale = Copy Scale, parent = Child Of with the inverse matrix that
  puts the object on the target; with it a Child Of on the node's channels whose inverse is the target's current
  matrix (Maya's offset is composed as a matrix: orient mo). aim = Track To (aim / up vectors along
  axes) evaluated in a hidden helper's space whose Z is Maya's world up vector — Blender's Track To ups to world Z.
- joint = a joint of a kit skeleton (``operators/joints.py``): a bone, ``jointN`` named scene-wide; the
  selected joint is the parent, a selected transform parents a new skeleton keeping the joint's world position.
- connectAttr / disconnectAttr = the Connection Editor's connections (``ui/connection_editor.py``: drivers
  with variable ``cn``, Maya unit conversion).

Constraint nodes and joints are not Blender objects, so the DAG commands of cmds_shim / cmds_dag (getAttr, setAttr,
xform, listRelatives, ls, select, delete, objExists) reach them through ``intercept``.

Code: cmds_rig_common (ID properties, constraint node registry, channel values, joint lookup), cmds_constraints
(the five constraint commands), cmds_joints (joint), cmds_connections (connectAttr ... connectionInfo); this module
keeps makeIdentity and the DAG commands' view of joints and constraint nodes (``intercept``, ``PASS``,
``node_type``) and re-exports the other modules' names.
"""

import bpy

from .cmds_shim import (_Flags, _flatten, _object, _objects, _selection, _view_layer, _to_bu, _from_bu, _from_rad,
                        linear_factor)
from .cmds_rig_common import (NODES, JOINT_RADIUS, JOINT_ORIENT, UP_PREFIX, CHANNELS, CONSTRAINT_TYPES, MAIN_KEYS,
                              _LONG, _KEY, _cb, _registry, _store, _owners, nodes_of, find_node, _node_of_type,
                              _cons, _target, _aliases, _taken_names, _new_node_name, _keys_of, _foreign_keys,
                              _raw_frame, _own_world, _no_scale, evaluated_local, maya_euler, _channel_values,
                              constrained_values, _skeletons, joint_names, find_joint, joint_world,
                              _joint_parent_world, joint_local)  # noqa: F401
from .cmds_constraints import (_requested_keys, _axes, _bake, _up_helper, _axis, _add_blender, _reweigh,
                               _remove_node, delete_node, _resolve, _con_of_target, _vec, _constrain,
                               parentConstraint, pointConstraint, orientConstraint, scaleConstraint,
                               aimConstraint)  # noqa: F401
from .cmds_joints import (_joint_attr, _joint_name, _selected_joint, _object_mode, joint, _select_joints,
                          _delete_joints)  # noqa: F401
from .cmds_connections import (_ce, _plug, _plug_text, connections, _leaf_key, connectAttr, disconnectAttr,
                               isConnected, _matching, listConnections, connectionInfo)  # noqa: F401

PASS = object()                      # intercept: not a joint / constraint matter, run the command itself


# --- makeIdentity --------------------------------------------------------------------------------------------------

def makeIdentity(*args, **kwargs):
    """``makeIdentity -apply 1 -t -r -s`` = Freeze Transformations (channels 0 / 0 / 1, world pivots and shapes stay,
    the hierarchy below frozen too); without ``-apply`` = the channels back to identity (the objects jump). No t / r /
    s flag = all three. Returns None."""
    from ..operators import freeze
    f = _Flags("makeIdentity", kwargs)
    apply = f.get("apply", "a", False)
    t = f.get("translate", "t", False)
    r = f.get("rotate", "r", False)
    s = f.get("scale", "s", False)
    f.get("normal", "n", 0)
    f.get("preserveNormals", "pn", True)
    f.get("jointOrient", "jo", False)
    f.done()
    obs = _objects(args)
    if not (t or r or s):
        t = r = s = True
    _view_layer()
    if apply:
        # like Maya, an instance and what is below it is not frozen
        freeze.freeze(obs, translate=bool(t), rotate=bool(r), scale=bool(s),
                      refuse={o for o in freeze.hierarchy(obs) if freeze.instanced(o)})
    else:
        freeze.reset(freeze.hierarchy(obs), translate=bool(t), rotate=bool(r), scale=bool(s))
    _view_layer()
    return None


# --- the DAG commands' view of joints and constraint nodes -------------------------------------------------------

def node_type(name):
    """Maya node type of a joint / kit constraint node ('joint', 'pointConstraint' ...), else None (nodeType)."""
    if find_joint(name) is not None and bpy.data.objects.get(str(name).rsplit("|", 1)[-1]) is None:
        return "joint"
    hit = find_node(name)
    return hit[2]["type"] if hit is not None else None


def _is_joint(name):
    return isinstance(name, str) and bpy.data.objects.get(name.rsplit("|", 1)[-1]) is None and \
        find_joint(name) is not None


def _flag(kwargs, long, short=None, default=None):
    for k in (long, short):
        if k and k in kwargs:
            return kwargs[k]
    return default


def _get_attr(fn, args, kwargs):
    attr = str(args[0]) if args else ""
    if "." not in attr:
        return PASS
    node, name = attr.split(".", 1)
    hit = find_node(node)
    if hit is not None:
        owner, n, entry = hit
        aliases = _aliases(owner, entry)
        if name in aliases:
            info = list(entry["targets"].values())[aliases.index(name)]
            return float(info["w"])
        if name in ("offset", "o") and "offset" in entry:
            return [tuple(_from_rad(float(x)) for x in entry["offset"])]
        raise ValueError(f"No attribute '{name}' on {n}")
    if _is_joint(node):
        arm, bone = find_joint(node)
        return _joint_attr(arm, bone, name)
    try:
        ob = _object(node)
    except (ValueError, RuntimeError):
        return PASS
    _view_layer()                 # connections and constraints show their result
    if any(k in kwargs for k in ("lock", "l", "keyable", "k", "channelBox", "cb", "type", "typ", "time", "t")):
        return PASS
    vals = constrained_values(ob)
    if not vals:
        return PASS
    from .cmds_shim import channel_keys
    keys = channel_keys(ob, name)
    if not keys or not any(k in vals for k in keys):
        return PASS
    res = fn(*args, **kwargs)
    if len(keys) == 3:
        return [tuple(vals.get(k, v) for k, v in zip(keys, res[0]))]
    return vals.get(keys[0], res)


def _set_attr(fn, args, kwargs):
    attr = str(args[0]) if args else ""
    if "." not in attr:
        return PASS
    node, name = attr.split(".", 1)
    values = list(_flatten(args[1:]))
    hit = find_node(node)
    if hit is not None:
        owner, n, entry = hit
        aliases = _aliases(owner, entry)
        if name not in aliases or not values:
            raise RuntimeError(f"setAttr: '{n}.{name}' can't be set in Maya Workflow Kit")
        reg = _registry(owner)
        cname = list(entry["targets"])[aliases.index(name)]
        reg[n]["targets"][cname]["w"] = float(values[0])
        _reweigh(owner, reg[n])
        _store(owner, reg)
        _view_layer()
        return None
    if _is_joint(node):
        arm, bone = find_joint(node)
        if name in ("radius", "rad") and values:
            bone[JOINT_RADIUS] = float(values[0])
            return None
        raise RuntimeError(f"setAttr: '{node}.{name}' of a joint can't be set by script in Maya Workflow Kit")
    if not values:
        return PASS
    try:
        ob = _object(node)
    except (ValueError, RuntimeError):
        return PASS
    from .cmds_shim import channel_keys
    keys = channel_keys(ob, name) or ()
    busy = _foreign_keys(ob)
    if any(k in busy for k in keys):
        raise RuntimeError(f"setAttr: The attribute '{ob.name}.{name}' is locked or connected and cannot be "
                           f"modified.")
    return PASS


def _xform(fn, args, kwargs):
    names = [n for n in _flatten(args) if isinstance(n, str)]
    if not names or not _is_joint(names[0]):
        return PASS
    arm, bone = find_joint(names[0])
    if not _flag(kwargs, "query", "q", False):
        raise RuntimeError("xform: moving a joint by script is not supported in Maya Workflow Kit")
    _view_layer()
    ws = _flag(kwargs, "worldSpace", "ws", False)
    m = joint_world(arm, bone) if ws else joint_local(arm, bone)
    if _flag(kwargs, "rotatePivot", "rp") or _flag(kwargs, "scalePivot", "sp") or \
            _flag(kwargs, "translation", "t"):
        return [_from_bu(x) for x in m.translation]
    if _flag(kwargs, "rotation", "ro"):
        return [_from_rad(x) for x in maya_euler(m.to_3x3().normalized())]
    if _flag(kwargs, "matrix", "m"):
        k = linear_factor()
        return [m[i][j] / k if (i < 3 and j == 3) else m[i][j] for j in range(4) for i in range(4)]
    raise TypeError("xform -query on a joint needs -translation, -rotation, -matrix or a pivot flag")


def _joint_children(arm, bone):
    return [b.name for b in bone.children]


def _joint_branch(arm, bone):
    out = []
    for c in bone.children:
        out += _joint_branch(arm, c)
    return out + [bone.name]


def _root_joints(ob):
    return [b.name for b in ob.data.bones if b.parent is None] if ob.type == 'ARMATURE' else []


def _list_relatives(fn, args, kwargs):
    names = [str(n) for n in _flatten(args)]
    parent_ = _flag(kwargs, "parent", "p", False) or _flag(kwargs, "allParents", "ap", False)
    all_desc = _flag(kwargs, "allDescendents", "ad", False)
    shapes = _flag(kwargs, "shapes", "s", False)
    typ = _flag(kwargs, "type", "typ")
    types_ = [typ] if isinstance(typ, str) else list(typ or [])
    if names and any(_is_joint(n) for n in names):
        out = []
        for n in names:
            arm, bone = find_joint(n)
            if parent_:
                rel = [bone.parent.name] if bone.parent is not None else \
                    ([arm.parent.name] if arm.parent is not None else [])
            elif shapes:
                rel = []
            elif all_desc:
                rel = [x for c in bone.children for x in _joint_branch(arm, c)]
            else:
                rel = _joint_children(arm, bone)
            if types_:
                rel = [r for r in rel if any(t in ("joint", "transform", "dagNode") for t in types_)]
            out += [r for r in rel if r not in out]
        return out or None
    res = fn(*args, **kwargs)
    if parent_ or shapes:
        return res
    out = list(res or [])
    # kit skeletons are their joints in Maya's DAG
    for ob in [o for o in _skeletons() if o.name in out]:
        i = out.index(ob.name)
        roots = _root_joints(ob)
        if all_desc:
            roots = [x for r in roots for x in _joint_branch(ob, ob.data.bones[r])]
        if types_ and not any(t in ("joint", "transform", "dagNode") for t in types_):
            roots = []
        out[i:i + 1] = roots
    if not all_desc:
        try:
            obs = [_object(n) for n in names] if names else _selection()
        except (ValueError, RuntimeError):
            obs = []
        for ob in obs:
            for node, entry in nodes_of(ob):
                if types_ and not any(t in ("constraint", entry["type"]) for t in types_):
                    continue
                if node not in out:
                    out.append(node)
    return out or None


def _ls(fn, args, kwargs):
    typ = _flag(kwargs, "type", "typ")
    types_ = [typ] if isinstance(typ, str) else list(typ or [])
    sl = _flag(kwargs, "selection", "sl", False)
    names = [str(n) for n in _flatten(args)]
    special = [t for t in types_ if t in ("joint", "constraint") + CONSTRAINT_TYPES]
    if special and len(special) == len(types_):
        out = []
        if "joint" in special:
            out += sorted(joint_names())
        for ob in bpy.context.scene.objects:
            if ob is None:
                continue
            for node, entry in nodes_of(ob):
                if "constraint" in special or entry["type"] in special:
                    out.append(node)
        if names:
            out = [n for n in out if n in names]
        if sl:
            chosen = set(_ls(fn, (), {"sl": True}) or [])
            out = [n for n in out if n in chosen]
        return out
    if sl and not names:
        res = fn(*args, **kwargs)
        out = []
        cb = _cb()
        for n in res:
            ob = bpy.data.objects.get(n.rsplit("|", 1)[-1])
            if ob is not None and ob.type == 'ARMATURE' and ob.mode == 'POSE':
                picked = [pb.name for pb in ob.pose.bones if cb.bone_selected(pb)]
                active = ob.data.bones.active
                if active is not None and active.name in picked:
                    picked.remove(active.name)
                    picked.append(active.name)
                out += picked
            else:
                out.append(n)
        return out
    if names and any(_is_joint(n) or find_node(n) for n in names):
        return [n for n in names if _is_joint(n) or find_node(n) or bpy.data.objects.get(n)]
    return PASS


def _select(fn, args, kwargs):
    names = [str(n) for n in _flatten(args)]
    joint_hits = [n for n in names if _is_joint(n)]
    if joint_hits:
        _select_joints(joint_hits, add=bool(_flag(kwargs, "add", None, False)))
        rest = [n for n in names if n not in joint_hits]
        if rest:
            fn(*rest, add=True)
        return None
    act = bpy.context.view_layer.objects.active
    if act is not None and act.type == 'ARMATURE' and act.mode == 'POSE':
        _object_mode(bpy.context)       # Maya: picking objects leaves joint selection
    return PASS


def _delete(fn, args, kwargs):
    names = [n for n in _flatten(args)]
    strs = [str(n) for n in names if isinstance(n, str)]
    nodes = [n for n in strs if find_node(n) is not None]
    jnts = [n for n in strs if _is_joint(n)]
    if not nodes and not jnts:
        return PASS
    for n in nodes:
        delete_node(n)
    if jnts:
        _delete_joints([find_joint(n) for n in jnts])
    rest = [n for n in names if n not in nodes and n not in jnts]
    if rest:
        return fn(*rest, **kwargs)
    _view_layer()
    return None


def _obj_exists(fn, args, kwargs):
    name = str(args[0]) if args else ""
    node = name.split(".", 1)[0]
    hit = find_node(node)
    if hit is not None:
        return "." not in name or name.split(".", 1)[1] in _aliases(hit[0], hit[2])
    if _is_joint(node):
        return True
    return PASS


_INTERCEPT = {"getAttr": _get_attr, "setAttr": _set_attr, "xform": _xform, "listRelatives": _list_relatives,
              "ls": _ls, "select": _select, "delete": _delete, "objExists": _obj_exists}


def intercept(command, fn, args, kwargs):
    """Run ``command`` (cmds_shim / cmds_dag function ``fn``) for joints and constraint nodes, which are not Blender
    objects; returns PASS when it isn't about them (the caller then runs ``fn`` itself)."""
    handler = _INTERCEPT.get(command)
    if handler is None:
        return PASS
    return handler(fn, args, kwargs)
