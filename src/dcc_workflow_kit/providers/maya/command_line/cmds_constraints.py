# SPDX-License-Identifier: GPL-3.0-or-later
"""maya.cmds look-alike: parentConstraint, pointConstraint, orientConstraint, scaleConstraint and aimConstraint as
Blender constraints, one per target, whose influences give Maya's weighted blend (-q / -e / -rm / -w / -mo / -n,
target lists, weight aliases); ``delete_node`` removes a node and keeps the channels at their last value. Node
registry and channel values: cmds_rig_common.py; re-exported by cmds_rig.py."""

import bpy
from mathutils import Matrix, Vector

from .cmds_shim import _Flags, _flatten, _object, _selection, _view_layer
from .cmds_rig_common import (UP_PREFIX, CHANNELS, _registry, _store, find_node, _node_of_type, _cons, _target,
                              _aliases, _new_node_name, _keys_of, _foreign_keys, _own_world, _no_scale,
                              evaluated_local)


def _requested_keys(mtype, skip=(), skip_t=(), skip_r=()):
    out = set()
    for c in CHANNELS[mtype]:
        sk = set(skip) | set(skip_t if c == "t" else skip_r if c == "r" else ())
        out |= {c + a for a in "xyz" if a not in sk}
    return out


def _axes(value):
    if value in (None, False):
        return ()
    vals = value if isinstance(value, (list, tuple)) else [value]
    out = set()
    for v in vals:
        v = str(v).lower()
        if v == "none":
            continue
        out.add(v)
    return tuple(out)


def _bake(ob, keys):
    """Write the constrained values of ``keys`` into ``ob``'s own channels (Maya: a deleted constraint leaves the
    channels at their last value)."""
    if not keys:
        return
    _view_layer()
    m = evaluated_local(ob)
    t, _q, s = m.decompose()
    order = ob.rotation_mode if ob.rotation_mode in ('XYZ', 'YZX', 'ZXY', 'XZY', 'YXZ', 'ZYX') else 'XYZ'
    e = m.to_3x3().normalized().to_euler(order, ob.rotation_euler)
    for i, a in enumerate("xyz"):
        if "t" + a in keys:
            ob.location[i] = t[i]
        if "r" + a in keys and ob.rotation_mode == order:
            ob.rotation_euler[i] = e[i]
        if "s" + a in keys:
            ob.scale[i] = s[i]


def _up_helper(node, world_up):
    """A hidden empty (no scene, fake user) whose Z axis is ``world_up``: the space an aim node's Track To runs in."""
    h = bpy.data.objects.get(UP_PREFIX + node) or bpy.data.objects.new(UP_PREFIX + node, None)
    h.use_fake_user = True
    h.rotation_mode = 'QUATERNION'
    w = Vector(world_up)
    h.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(w.normalized() if w.length else w)
    h.matrix_world = h.matrix_basis.copy()
    return h


def _axis(v, what):
    from ..operators import rig_tools
    a = rig_tools.axis_of(v)
    if a is None:
        raise RuntimeError(f"aimConstraint: Blender aims along an axis: the {what} vector must be +-X, +-Y or +-Z")
    return a


def _add_blender(owner, node, entry, target, mtype, mo, skip):
    """The Blender constraint for one more target of ``node``; returns it."""
    cons = owner.constraints
    _view_layer()
    tw = target.matrix_world.copy()
    if mtype == "aimConstraint":
        a = _axis(entry["aim"], "aim")
        track = ("TRACK_" if a[1] > 0 else "TRACK_NEGATIVE_") + a[0]
        if entry["wut"] == "none":
            con = cons.new('DAMPED_TRACK')
            con.track_axis = track
        else:
            u = _axis(entry["up"], "up")
            if u[1] < 0 or u[0] == a[0]:
                raise RuntimeError("aimConstraint: Blender's Track To needs an up vector along a positive axis other "
                                   "than the aim vector's")
            con = cons.new('TRACK_TO')
            con.track_axis, con.up_axis, con.use_target_z = track, "UP_" + u[0], False
            con.owner_space = con.target_space = 'CUSTOM'
            con.space_object = _up_helper(node, entry["wu"])
        con.target = target
        return con
    if not mo and mtype == "pointConstraint":
        con = cons.new('COPY_LOCATION')
    elif not mo and mtype == "orientConstraint":
        con = cons.new('COPY_ROTATION')
    elif not mo and mtype == "scaleConstraint":
        con = cons.new('COPY_SCALE')
    else:
        con = cons.new('CHILD_OF')
    con.target = target
    if con.type in ('COPY_LOCATION', 'COPY_ROTATION', 'COPY_SCALE'):
        for a in "xyz":
            setattr(con, "use_" + a, a not in skip.get(CHANNELS[mtype], ()))
        return con
    # Child Of: parent (t r), or the one channel group of a point / orient / scale node with Maintain Offset
    groups = CHANNELS[mtype]
    for c, prop in (("t", "use_location_"), ("r", "use_rotation_"), ("s", "use_scale_")):
        for a in "xyz":
            setattr(con, prop + a, c in groups and a not in skip.get(c, ()))
    if mtype == "parentConstraint":
        con.inverse_matrix = _no_scale(tw if mo else _own_world(owner)).inverted_safe()
    elif mtype == "pointConstraint":
        con.inverse_matrix = Matrix.Translation(-tw.translation)
    elif mtype == "orientConstraint":
        con.inverse_matrix = tw.to_quaternion().to_matrix().to_4x4().inverted_safe()
    else:
        con.inverse_matrix = Matrix.Diagonal(Vector([*tw.to_scale(), 1.0])).inverted_safe()
    con.set_inverse_pending = False
    return con


def _reweigh(owner, entry):
    """Influence of target i = w_i / (w_1 + ... + w_i): the stack gives Maya's weighted blend."""
    total = 0.0
    for cname, info in entry["targets"].items():
        con = owner.constraints.get(cname)
        if con is None:
            continue
        total += max(0.0, float(info["w"]))
        con.influence = (float(info["w"]) / total) if total > 0 else 0.0


def _remove_node(owner, node, bake=True):
    reg = _registry(owner)
    entry = reg.pop(node, None)
    if entry is None:
        return
    cons = _cons(owner, entry)
    if bake:
        _bake(owner, _keys_of(cons))
    for con in cons:
        owner.constraints.remove(con)
    h = bpy.data.objects.get(UP_PREFIX + node)
    if h is not None:
        bpy.data.objects.remove(h)
    _store(owner, reg)
    _view_layer()


def delete_node(name):
    """Delete a Maya constraint node (Maya: the channels keep their last value). True if it was one."""
    hit = find_node(name)
    if hit is None:
        return False
    _remove_node(hit[0], hit[1])
    return True


def _resolve(mtype, names):
    """(constrained object, its ``mtype`` node or None, target objects) of a constraint command's objects."""
    if len(names) == 1:
        hit = find_node(names[0])
        if hit is not None:
            return hit[0], hit[1], []
        ob = _object(names[0])
        return ob, _node_of_type(ob, mtype), []
    obs = [_object(n) for n in names]
    return obs[-1], _node_of_type(obs[-1], mtype), obs[:-1]


def _con_of_target(owner, entry, target):
    for cname in entry["targets"]:
        con = owner.constraints.get(cname)
        if con is not None and _target(con) is target:
            return cname
    return None


def _vec(v, default):
    return [float(x) for x in (v if v is not None else default)]


def _constrain(mtype, args, kwargs):
    f = _Flags(mtype, kwargs)
    query = f.get("query", "q", False)
    edit = f.get("edit", "e", False)
    remove = f.get("remove", "rm", False)
    mo = f.get("maintainOffset", "mo", False)
    weight = f.get("weight", "w")
    name = f.get("name", "n")
    tl = f.get("targetList", "tl", False)
    wal = f.get("weightAliasList", "wal", False)
    offset = f.get("offset", "o")
    skip = _axes(f.get("skip", "sk"))
    skip_t = _axes(f.get("skipTranslate", "st")) if mtype == "parentConstraint" else ()
    skip_r = _axes(f.get("skipRotate", "sr")) if mtype == "parentConstraint" else ()
    aim = f.get("aimVector", "aim") if mtype == "aimConstraint" else None
    up = f.get("upVector", "u") if mtype == "aimConstraint" else None
    wu = f.get("worldUpVector", "wu") if mtype == "aimConstraint" else None
    wut = f.get("worldUpType", "wut") if mtype == "aimConstraint" else None
    f.get("layer", "l")
    f.done()
    names = [str(n) for n in _flatten(args)] or [o.name for o in _selection()]
    if not names:
        raise RuntimeError(f"{mtype}: Nothing selected")
    owner, node, targets = _resolve(mtype, names)

    if query:
        if node is None:
            return None
        entry = _registry(owner)[node]
        if tl:
            out = []
            for con in _cons(owner, entry):
                tgt = _target(con)
                out.append(tgt.name if tgt is not None else "")
            return out
        if wal:
            return _aliases(owner, entry)
        if weight:
            infos = list(entry["targets"].items())
            if targets:
                picked = [entry["targets"][c]["w"] for c in (_con_of_target(owner, entry, t) for t in targets)
                          if c is not None]
                return float(picked[0]) if len(picked) == 1 else [float(w) for w in picked]
            return [float(i["w"]) for _c, i in infos]
        if offset:
            return [float(x) for x in entry.get("offset", (0.0, 0.0, 0.0))]
        if aim:
            return [float(x) for x in entry["aim"]]
        if up:
            return [float(x) for x in entry["up"]]
        if wu:
            return [float(x) for x in entry["wu"]]
        if wut:
            return entry["wut"]
        if mo:
            return bool(entry.get("mo", False))
        return node

    if remove:
        if node is None:
            raise RuntimeError(f"{mtype}: {owner.name} has no {mtype}")
        reg = _registry(owner)
        entry = reg[node]
        for t in targets:
            cname = _con_of_target(owner, entry, t)
            if cname is None:
                continue
            if len(entry["targets"]) == 1:          # the last target: the node goes, the channels stay
                _remove_node(owner, node)
                return None
            owner.constraints.remove(owner.constraints[cname])
            del entry["targets"][cname]
        _reweigh(owner, entry)
        reg[node] = entry
        _store(owner, reg)
        _view_layer()
        return [node]

    if edit:
        if node is None:
            raise RuntimeError(f"{mtype}: {owner.name} has no {mtype}")
        reg = _registry(owner)
        entry = reg[node]
        if weight is not None:
            for t in (targets or [_target(c) for c in _cons(owner, entry)]):
                cname = _con_of_target(owner, entry, t)
                if cname is not None:
                    entry["targets"][cname]["w"] = float(weight)
        _reweigh(owner, entry)
        reg[node] = entry
        _store(owner, reg)
        _view_layer()
        return [node]

    if not targets:
        raise RuntimeError(f"{mtype}: Select the target(s) and then the object to constrain")
    if mo and mtype == "aimConstraint":
        raise RuntimeError("aimConstraint -maintainOffset is not supported in Maya Workflow Kit")
    want = _requested_keys(mtype, skip, skip_t, skip_r)
    busy = want & _foreign_keys(owner, node)
    if busy:
        key = sorted(busy)[0]
        long = {"t": "translate", "r": "rotate", "s": "scale"}[key[0]] + key[1].upper()
        raise RuntimeError(f"{mtype}: '{owner.name}.{long}' is already connected: Object is already connected.")
    reg = _registry(owner)
    if node is None:
        node = _new_node_name(owner, mtype, name)
        entry = {"type": mtype, "targets": {}, "next": 0, "mo": bool(mo)}
        if mtype == "aimConstraint":
            entry.update(aim=_vec(aim, (1, 0, 0)), up=_vec(up, (0, 1, 0)), wu=_vec(wu, (0, 1, 0)),
                         wut=str(wut or "vector").lower())
            if entry["wut"] == "scene":
                entry["wu"] = [0.0, 1.0, 0.0]
            elif entry["wut"] not in ("vector", "none"):
                raise RuntimeError(f"aimConstraint: world up type '{wut}' is not supported in Maya Workflow Kit")
    else:
        entry = reg[node]
    skip_by = {"t": tuple(set(skip) | set(skip_t)), "r": tuple(set(skip) | set(skip_r)), "s": tuple(skip)}
    _view_layer()
    for t in targets:
        if t is owner:
            raise RuntimeError(f"{mtype}: an object can't constrain itself")
        if _con_of_target(owner, entry, t) is not None:
            continue
        i = int(entry["next"])
        if mtype == "orientConstraint" and mo and not entry["targets"]:
            off = (t.matrix_world.to_quaternion().to_matrix().inverted() @
                   _own_world(owner).to_quaternion().to_matrix()).to_euler('XYZ')
            entry["offset"] = [off.x, off.y, off.z]        # Maya's q -offset reads radians
        con = _add_blender(owner, node, entry, t, mtype, mo, skip_by)
        con.name = node if not entry["targets"] else f"{node} {i}"
        entry["targets"][con.name] = {"i": i, "w": float(1.0 if weight is None else weight)}
        entry["next"] = i + 1
    _reweigh(owner, entry)
    reg[node] = entry
    _store(owner, reg)
    _view_layer()
    return [node]


def parentConstraint(*args, **kwargs):
    """``parentConstraint target... object``: the object follows the targets' translate / rotate (Child Of).
    Returns ['<object>_parentConstraintN']; ``-q`` / ``-e`` / ``-rm`` / ``-w`` / ``-mo`` / ``-n`` like Maya."""
    return _constrain("parentConstraint", args, kwargs)


def pointConstraint(*args, **kwargs):
    """``pointConstraint``: the object's pivot on the targets' weighted pivot (Copy Location)."""
    return _constrain("pointConstraint", args, kwargs)


def orientConstraint(*args, **kwargs):
    """``orientConstraint``: the targets' world rotation (Copy Rotation; with ``-mo`` the offset as a rotation)."""
    return _constrain("orientConstraint", args, kwargs)


def scaleConstraint(*args, **kwargs):
    """``scaleConstraint``: the targets' scale (Copy Scale)."""
    return _constrain("scaleConstraint", args, kwargs)


def aimConstraint(*args, **kwargs):
    """``aimConstraint``: the aim vector at the target, the up vector towards the world up vector (defaults
    like Maya: aim 1 0 0, up 0 1 0, world up type vector 0 1 0)."""
    return _constrain("aimConstraint", args, kwargs)
