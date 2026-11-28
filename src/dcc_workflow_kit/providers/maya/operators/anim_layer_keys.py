# SPDX-License-Identifier: GPL-3.0-or-later
"""How the layer stack gives a channel's value and how a key on one layer is solved: ``compose`` / ``solve``
(Additive, Override, scale multiplies), ``result``, ``key`` / ``key_quaternion`` (the layer value that makes the
result the displayed value), ``key_pose_bone`` for joints and ``settle_base`` after a bake. Used by the Channel
Box, Auto Key, playback and Bake Simulation; built on anim_layer_tracks and anim_layer_members.
"""

import bpy

from .. import compat
from .anim_layer_members import bone_path, target_layer
from .anim_layer_tracks import BASE, _evaluate, _fcurve, is_scale, layers, _leaf, _slot, _strip, strip_weight, tracks


def settle_base(scene, ob, prefixes):
    """After a bake wrote the VISUAL values into BaseAnimation: re-solve every baked key of channels the layers
    above also animate, so base + layers = the baked value (otherwise the layers add again). ``prefixes`` = data path prefixes of the baked owners ("" = the object)."""
    base = tracks(ob).get(BASE)
    if base is None:
        return 0
    act = _strip(base).action
    upper = set()
    for name, tr in tracks(ob).items():
        if name != BASE:
            upper |= {(fc.data_path, fc.array_index) for fc in compat.action_fcurves(_strip(tr).action,
                                                                                   _slot(_strip(tr).action))}
    if not upper:
        return 0

    def mine(path):
        return any(path.startswith(p) if p else not path.startswith("pose.") for p in prefixes)
    curves = [fc for fc in compat.action_fcurves(act, _slot(act)) if mine(fc.data_path)]
    n = 0
    quats = {}
    for fc in curves:
        if _leaf(fc.data_path) == "rotation_quaternion":
            quats.setdefault(fc.data_path, {})[fc.array_index] = fc
            continue
        if (fc.data_path, fc.array_index) not in upper:
            continue
        for f, v in [(kp.co[0], kp.co[1]) for kp in fc.keyframe_points]:
            key(ob, fc.data_path, fc.array_index, frame=f, value=v, scene=scene, layer=BASE)
            n += 1
    from mathutils import Quaternion
    for path, comps in quats.items():
        if not any((path, i) in upper for i in range(4)) or len(comps) < 4:
            continue
        frames = sorted({kp.co[0] for kp in comps[0].keyframe_points})
        values = {f: Quaternion([comps[i].evaluate(f) for i in range(4)]) for f in frames}
        for f in frames:
            key_quaternion(ob, path, f, values[f], scene, BASE)
            n += 1
    ob.update_tag(refresh={'TIME'})
    return n


# --- evaluation and keys -------------------------------------------------------------------------------

def compose(steps, start):
    """Fold the layer steps over ``start``: steps = [(mode, weight, value)] bottom first, mode REPLACE / ADD /
    MUL (scale COMBINE). Returns the result."""
    acc = start
    for mode, w, x in steps:
        if mode == 'REPLACE':
            acc = (1.0 - w) * acc + w * x
        elif mode == 'MUL':
            acc = acc * (x ** w if x > 0 else 0.0)
        else:
            acc = acc + w * x
    return acc


def _steps(ob, path, index, frame, scene, ev=None):
    """[(layer name, mode, weight, value or None)] of the object's evaluated layers for one channel, bottom first."""
    ev = ev or _evaluate
    info = {e.name: e for e in layers(scene)}
    out = []
    ad = ob.animation_data
    for tr in ad.nla_tracks:
        if tr.name not in info or tr.mute:
            continue
        st = _strip(tr)
        fc = _fcurve(st.action, path, index)
        w = strip_weight(st, frame, ev)
        if st.blend_type == 'REPLACE':
            mode = 'REPLACE'
        elif st.blend_type == 'COMBINE' and is_scale(path):
            mode = 'MUL'
        else:
            mode = 'ADD'
        out.append((tr.name, mode, w, ev(fc, frame) if fc is not None else None))
    return out


def solve(steps, target, layer, start=0.0):
    """The value ``layer``'s curve needs so the folded result is ``target`` (Maya: a key on the selected layer makes
    the displayed value the result). ``steps`` as from ``_steps``; missing values = no curve yet (identity)."""
    def ident(mode):
        return 1.0 if mode == 'MUL' else 0.0
    k = next(i for i, s in enumerate(steps) if s[0] == layer)
    below = compose([(m, w, x) for _n, m, w, x in steps[:k] if x is not None], start)
    upper = [(m, w, x) for _n, m, w, x in steps[k + 1:] if x is not None]
    # the upper layers are affine in their input: result = a * acc + b (or a * acc for MUL steps)
    a, b = 1.0, 0.0
    for m, w, x in upper:
        if m == 'REPLACE':
            a, b = a * (1.0 - w), b * (1.0 - w) + w * x
        elif m == 'MUL':
            f = x ** w if x > 0 else 0.0
            a, b = a * f, b * f
        else:
            b = b + w * x
    _n, mode, w, cur = steps[k]
    if abs(a) < 1e-12 or w < 1e-12:
        return cur if cur is not None else ident(mode)        # an upper Override hides this layer: keep it
    acc = (target - b) / a
    if mode == 'REPLACE':
        return (acc - (1.0 - w) * below) / w
    if mode == 'MUL':
        return (acc / below) ** (1.0 / w) if below and acc / below > 0 else 1.0
    return (acc - below) / w


def result(ob, path, index, frame=None, scene=None, ev=None):
    """The value the layers give a channel at ``frame`` (None when no layer has a curve for it); ``ev`` as in
    ``strip_weight``."""
    scene = scene or bpy.context.scene
    frame = scene.frame_current if frame is None else frame
    steps = _steps(ob, path, max(index, 0), frame, scene, ev)
    known = [(m, w, x) for _n, m, w, x in steps if x is not None]
    if not known:
        return None
    return compose(known, below_value(ob, path, max(index, 0), frame, ev))


def below_value(ob, path, index, frame, ev=None):
    """What the layer stack starts from: the Trax clips' value (their tracks sit below the layers,
    operators/trax_clips.py), else the property's default (scale 1, else 0) like Blender's NLA."""
    from . import trax_clips
    default = 1.0 if is_scale(path) else 0.0
    v = trax_clips.stack_value(ob, path, index, frame, default, ev)
    return default if v is None else v


def key(ob, path, index, frame=None, value=None, scene=None, layer=None):
    """Key channel (``path``, ``index``) of ``ob`` on the selected layer (or ``layer``) so the result is ``value``
    (default: the displayed value). A quaternion (``rotation_quaternion``) is keyed whole whatever ``index``.
    False when the layer is locked."""
    scene = scene or bpy.context.scene
    frame = scene.frame_current if frame is None else frame
    if _leaf(path) == "rotation_quaternion":
        return key_quaternion(ob, path, frame, value if value is not None and not isinstance(value, float) else None,
                              scene, layer)
    if value is None:
        v = ob.path_resolve(path)
        value = float(v[index] if index >= 0 else v)
    layer = layer or target_layer(scene, ob, path, index)
    index = max(index, 0)
    info = {e.name: e for e in layers(scene)}
    if layer in info and info[layer].lock:
        return False
    steps = _steps(ob, path, index, frame, scene)
    if not any(s[0] == layer for s in steps):          # the target layer is muted: Maya keys it anyway
        tr = tracks(ob)[layer]
        steps = [s for s in steps if s[0] != layer]
        st = _strip(tr)
        steps.append((layer, 'REPLACE' if st.blend_type == 'REPLACE' else
                      ('MUL' if is_scale(path) else 'ADD'), 1.0, None))
    # NLA starts a channel no lower strip animates from the property's default (scale 1, else 0)
    start = value if layer == BASE else below_value(ob, path, index, frame)
    x = solve(steps, value, layer, start)
    act = _strip(tracks(ob)[layer]).action
    fc = _fcurve(act, path, index)
    if fc is None:
        fc = _new_fcurve(ob, act, path, index)
    if fc is None:
        return False
    fc.keyframe_points.insert(frame, x)
    fc.update()
    ob.update_tag(refresh={'TIME'})
    return True


# Quaternion channels (Rigify-style joints, shown as Euler). Blender's NLA mixes a quaternion
# as a whole: REPLACE = component lerp of the lower result and the strip by the influence, COMBINE = lower @ strip^w
# (checked in tests/test_step234_layer_joints.py against the evaluated pose). The layer's key is solved so the result
# is the displayed rotation, with the layers above combined after it.
def _quat_power(q, w):
    from mathutils import Quaternion
    axis, angle = q.to_axis_angle()
    return Quaternion(axis, angle * w)


def _quat_layers(ob, path, frame, scene, ev=None):
    """[(layer, blend, weight, Quaternion or None)] bottom first for a quaternion channel."""
    from mathutils import Quaternion
    ev = ev or _evaluate
    info = {e.name: e for e in layers(scene)}
    out = []
    for tr in ob.animation_data.nla_tracks:
        if tr.name not in info or tr.mute:
            continue
        st = _strip(tr)
        fcs = [_fcurve(st.action, path, i) for i in range(4)]
        q = None
        if any(fcs):
            ident = (1.0, 0.0, 0.0, 0.0)
            q = Quaternion([ev(fc, frame) if fc is not None else ident[i] for i, fc in enumerate(fcs)])
        out.append((tr.name, st.blend_type, strip_weight(st, frame, ev), q))
    return out


def compose_quaternion(steps, start):
    from mathutils import Quaternion
    acc = Quaternion(start)
    for _n, blend, w, q in steps:
        if q is None:
            continue
        if blend == 'REPLACE':
            acc = Quaternion([(1.0 - w) * a + w * b for a, b in zip(acc, q)])
        else:
            acc = acc @ _quat_power(q, w)
    return acc


def key_quaternion(ob, path, frame, value=None, scene=None, layer=None):
    """Key a quaternion channel (all four curves) on ``layer`` (default: the selected one) so the result is ``value``
    (default: the displayed rotation)."""
    from mathutils import Quaternion
    scene = scene or bpy.context.scene
    target = Quaternion(value if value is not None else ob.path_resolve(path))
    layer = layer or target_layer(scene, ob, path, 0)
    info = {e.name: e for e in layers(scene)}
    if layer in info and info[layer].lock:
        return False
    steps = _quat_layers(ob, path, frame, scene)
    if not any(s[0] == layer for s in steps):
        st = _strip(tracks(ob)[layer])
        steps.append((layer, st.blend_type, 1.0, None))
    k = next(i for i, s in enumerate(steps) if s[0] == layer)
    _n, blend, w, cur = steps[k]
    upper = Quaternion()
    for _u, b, uw, q in steps[k + 1:]:
        if q is not None and b != 'REPLACE':
            upper = upper @ _quat_power(q, uw)
    acc = target @ upper.inverted()                     # the result just above this layer
    if layer == BASE:
        x = acc
    else:
        below = compose_quaternion(steps[:k], Quaternion())
        if w < 1e-12:
            return False
        if blend == 'REPLACE':
            if below.dot(acc) < 0.0:
                acc = -acc
            x = Quaternion([(a - (1.0 - w) * b) / w for a, b in zip(acc, below)])
        else:
            x = _quat_power(below.inverted() @ acc, 1.0 / w)
    if cur is not None and cur.dot(x) < 0.0:
        x = -x                                          # keep the curve on one side (no flips between keys)
    act = _strip(tracks(ob)[layer]).action
    for i in range(4):
        fc = _fcurve(act, path, i) or _new_fcurve(ob, act, path, i)
        if fc is None:
            return False
        fc.keyframe_points.insert(frame, x[i])
        fc.update()
    ob.update_tag(refresh={'TIME'})
    return True


def key_pose_bone(pb, path, index, frame=None, scene=None):
    """Channel Box / S key of a joint channel on a layered armature (Blender's own keying refuses an
    NLA-stacked armature: "Due to the NLA stack setup ..."). ``index`` -1 = every component."""
    scene = scene or bpy.context.scene
    frame = scene.frame_current if frame is None else frame
    arm = pb.id_data
    full = bone_path(pb, path)
    if _leaf(full) == "rotation_quaternion":
        return key_quaternion(arm, full, frame, scene=scene)
    if index >= 0:
        return key(arm, full, index, frame, scene=scene)
    v = arm.path_resolve(full)
    try:
        n = len(v)
    except TypeError:
        return key(arm, full, 0, frame, value=float(v), scene=scene)
    done = False
    for i in range(n):
        done = key(arm, full, i, frame, scene=scene) or done
    return done


def _new_fcurve(ob, act, path, index):
    ad = ob.animation_data
    keep, keep_slot = ad.action, getattr(ad, "action_slot", None)
    try:
        ad.action = act
        sl = _slot(act)
        if sl is not None and hasattr(ad, "action_slot"):
            ad.action_slot = sl
        if hasattr(act, "fcurve_ensure_for_datablock"):
            fc = act.fcurve_ensure_for_datablock(ob, path, index=index)
        else:
            fc = act.fcurves.new(path, index=index)
        # Blender's keying gives transform channels X / Y / Z = red / green / blue (Maya's axis colours); a curve
        # made through the API starts AUTO_RAINBOW (a layer's Translate Y would draw red)
        if _leaf(path) in {"location", "rotation_euler", "scale", "delta_location", "rotation_quaternion"}:
            fc.color_mode = 'AUTO_RGB'
        return fc
    finally:
        ad.action = keep
        if keep is not None and keep_slot is not None:
            ad.action_slot = keep_slot
