# SPDX-License-Identifier: GPL-3.0-or-later
"""One channel of one node: whether it has it, its value, writing and keying it, its animation curves and driver,
and the key state drawn beside the value.
Entry points: has_channel, get_value, set_value, keyframe, fcurve, driver, channel_state, row_state, channel_label.
Related: cb_keys.py, cb_inputs.py."""

import math

import bpy

from .. import compat
from . import cb_entry

from .cb_nodes import full_path, is_bone, is_root_joint, lead, root_translate, set_root_translate
from .cb_keys import (BLEND_PREFIX, CUSTOM_PREFIX, HISTORY_PREFIX, MAIN_BY_KEY, MODEL_PREFIX, SHAPE_PREFIX, blend_path,
                      channel_path, input_parts, is_blend_key, is_constraint_key, is_history_key, is_input_key,
                      is_keyable, is_locked, is_shape_key, model_parts, nice_name)
from .cb_inputs import (SHAPE_PROPS, _row_kind, _row_read, _row_write, _virtual, blend_target, input_label, row_owner,
                        shape_label)


def model_node(ob, key):
    from . import node_attributes
    if not isinstance(ob, bpy.types.Object):
        return None
    from ..operators import model_history
    kind, name, field = model_parts(key)
    node = node_attributes.target(bpy.context, ob)
    if node is not None and name:
        rec = model_history.find(ob, name)
        if rec is None and ob != lead():
            rec = next((r for r in reversed(model_history.records(ob)) if r.spec.kind == kind), None)
        if rec is not None and field in rec.params:
            return node_attributes.for_record(bpy.context, ob, rec)
        return None
    return node if (isinstance(node, node_attributes.ModelingNode) and node.spec.kind == kind
                    and field in node.params) else None


def shape_owner(ob, key):
    """The object data holding SHAPES channel ``key`` (None: ``ob`` has no such row)."""
    if not is_shape_key(key) or is_bone(ob):
        return None
    name = key[len(SHAPE_PREFIX):]
    if name not in SHAPE_PROPS.get(getattr(ob, "type", ""), ()):
        return None
    return row_owner(ob, "SHAPE", name)


def shape_paths(owner, key):
    """[(Blender data path, index)] a key / mute / delete on a SHAPES channel acts on: a Maya attribute
    kept differently in Blender keys its Blender properties (Color R = color[0], spot Cone / Penumbra = spot_size +
    spot_blend)."""
    name = key[len(SHAPE_PREFIX):]
    v = _virtual(owner, name)
    if v is not None:
        return list(getattr(v, "paths", ()))
    rna = owner.bl_rna.properties.get(name)
    return [(name, -1)] if rna is not None and rna.is_animatable else []


def input_owner(ob, key):
    """The modifier (or constraint) holding INPUTS channel ``key`` on ``ob``: the same type at the same position,
    like a typed value. A constraint weight is on an object or a joint, a modifier's property on an object."""
    if not is_input_key(key):
        return None
    if is_constraint_key(key):
        if not hasattr(ob, "constraints"):
            return None
        con_type, nth, name = input_parts(key)
        return row_owner(ob, "CONSTRAINT", name, con_type, nth)
    if is_bone(ob) or not hasattr(ob, "modifiers"):
        return None
    mod_type, nth, name = input_parts(key)
    return row_owner(ob, "INPUT", name, mod_type, nth)


def path_struct(owner, path):
    """(struct, property name) of ``path`` on ``owner``: a path through nested structs (a Geometry Nodes input's
    ``properties.inputs.Socket_2.value``) resolves to its last struct, which keys and names it."""
    head, dot, prop = path.rpartition(".")
    if not dot or path.startswith("["):
        i = path.find("[")
        if i > 0:       # an ID property of an object the owner points at (a lattice bend's handle: origin["..."])
            sub = owner.path_resolve(path[:i])
            if sub is not None:
                return sub, path[i:]
        return owner, path
    return owner.path_resolve(head), prop


def input_paths(owner, key):
    """[(path on the modifier, index)] a key on an INPUTS channel sets."""
    name = input_parts(key)[2]
    v = _virtual(owner, name)
    if v is not None:
        return list(getattr(v, "paths", ()))
    rna = owner.bl_rna.properties.get(name)
    return [(name, -1)] if rna is not None and rna.is_animatable else []


def constraint_weight(ob, key):
    """The ID property of ``ob`` holding the target weight behind constraint channel ``key`` when the constraint has
    its own weight (a one-target Maya constraint: operators/constrain_multi.ensure_single_weight), else None (the
    constraint's influence is the weight)."""
    if not is_constraint_key(key):
        return None
    con = input_owner(ob, key)
    if con is None:
        return None
    from ..operators import constrain_multi
    return constrain_multi.single_weight(con, ob)


def _own_weight(ob, key):
    """``constraint_weight``, after giving the constraint its own weight when Maya's one-target rule applies: a value
    written or keyed on the weight (any weight above 0 = fully on the target, 0 = the node's own channels)."""
    if not is_constraint_key(key):
        return None
    con = input_owner(ob, key)
    if con is None:
        return None
    from ..operators import constrain_multi
    return constrain_multi.ensure_single_weight(con, ob)


def input_curve_id(ob, key):
    """The ID whose animation holds INPUTS channel ``key`` of ``ob``: the node's own, or for a deformer a handle or
    lattice shows (bend1 in the INPUTS of bend1Handle) the deformed object's, where the modifier is; a deformer value
    kept on its handle (a lattice bend's Curvature) the handle's."""
    owner = input_owner(ob, key)
    if owner is None:
        return None
    if isinstance(owner, bpy.types.Modifier):
        paths = input_paths(owner, key)
        if paths:
            try:
                return path_struct(owner, paths[0][0])[0].id_data
            except (ValueError, AttributeError):
                pass
    return owner.id_data


def input_curve_paths(ob, key):
    """[(data path on ``input_curve_id``, index)] of the animation behind INPUTS channel ``key`` of ``ob``."""
    owner = input_owner(ob, key)
    if owner is None:
        return []
    prop = constraint_weight(ob, key)
    if prop is not None:
        from ..operators import constrain_multi
        return [(constrain_multi.weight_path(ob, prop), -1)]
    return [(sub.path_from_id(name), i) for p, i in input_paths(owner, key) for sub, name in [path_struct(owner, p)]]


def history_node_of(ob, key):
    """(owner, node) of ``ob``'s creation node when it has attribute ``key`` and the lead's node type, else (None,
    None) (a typed value goes to every selected object whose node has the same type)."""
    if not is_history_key(key) or not isinstance(ob, bpy.types.Object):
        return None, None
    from ..operators import prim_history
    owner, node = prim_history.node_of(ob)
    name = key[len(HISTORY_PREFIX):]
    if node is None or name not in prim_history.attrs(owner):
        return None, None
    ld = lead()
    if ld is not None and ld is not ob and isinstance(ld, bpy.types.Object):
        _o, lead_node = prim_history.node_of(ld)
        if lead_node is not None and lead_node["type"] != node["type"]:
            return None, None
    return owner, node


def _history_get(ob, key):
    from ..operators import prim_history
    owner, node = history_node_of(ob, key)
    name = key[len(HISTORY_PREFIX):]
    return prim_history.to_entry(node, name, prim_history.shown_attrs(owner)[name])


def _history_set(ob, key, value):
    from ..operators import prim_history, prim_shapes
    owner, node = history_node_of(ob, key)
    name = key[len(HISTORY_PREFIX):]
    value = prim_history.from_entry(node, name, value)
    if prim_history.entry_kind(node["type"], name) == "INT":
        value = math.floor(value + 0.5)      # a drag / slider gives floats: integer attributes step
    value = prim_shapes.clamp(node["type"], name, value)
    if value != prim_history.shown_attrs(owner)[name]:
        prim_history.rebuild(bpy.context, ob, prim_history.from_scene({name: value}))


def curve_owner(ob, key):
    """The ID whose animation holds channel ``key``'s curves."""
    if is_blend_key(key):
        kb = blend_target(ob, key)
        return kb.id_data if kb is not None else None
    if is_input_key(key):
        return input_curve_id(ob, key)
    return shape_owner(ob, key) if is_shape_key(key) else ob.id_data


def channel_label(key):
    if key.startswith(MODEL_PREFIX):
        from ..operators import extrude
        kind, _name, field = model_parts(key)
        return extrude.SPECS[kind].labels[field]
    if key.startswith(CUSTOM_PREFIX):
        return nice_name(key[len(CUSTOM_PREFIX):])
    if is_shape_key(key):
        ob = lead()
        name = key[len(SHAPE_PREFIX):]
        return shape_label(ob, name) if ob is not None and shape_owner(ob, key) is not None else nice_name(name)
    if is_input_key(key):
        ob = lead()
        owner = input_owner(ob, key) if ob is not None else None
        name = input_parts(key)[2]
        return input_label(owner, name) if owner is not None else nice_name(name)
    if is_history_key(key):
        from ..operators import prim_shapes
        _owner, node = history_node_of(lead(), key) if lead() is not None else (None, None)
        name = key[len(HISTORY_PREFIX):]
        return prim_shapes.spec(node["type"], name)[1] if node is not None else nice_name(name)
    if is_blend_key(key):
        return key[len(BLEND_PREFIX):]      # Maya names a weight after its target
    return MAIN_BY_KEY[key][1]


def has_channel(ob, key):
    if key.startswith(MODEL_PREFIX):
        return model_node(ob, key) is not None
    if key.startswith(CUSTOM_PREFIX):
        return key[len(CUSTOM_PREFIX):] in ob.keys()
    if is_shape_key(key):
        return shape_owner(ob, key) is not None
    if is_input_key(key):
        return input_owner(ob, key) is not None
    if is_history_key(key):
        return history_node_of(ob, key)[1] is not None
    if is_blend_key(key):
        return blend_target(ob, key) is not None
    # Maya rotation channels are always Rotate X / Y / Z: quaternion / axis-angle nodes show Euler
    return MAIN_BY_KEY[key][4] != "ROT" or hasattr(ob, "rotation_mode")


def _non_euler_rot(ob, kind):
    return kind == "ROT" and getattr(ob, "rotation_mode", 'XYZ') in ('QUATERNION', 'AXIS_ANGLE')


def get_value(ob, key):
    path, idx, kind = channel_path(key)
    if kind == 'MODEL':
        return model_node(ob, key).params[path]
    if kind == "SHAPE":
        return _row_read(shape_owner(ob, key), "SHAPE", path)
    if kind == "INPUT":
        prop = constraint_weight(ob, key)
        if prop is not None:
            return ob[prop]
        return _row_read(input_owner(ob, key), "INPUT", path)
    if kind == "HISTORY":
        return _history_get(ob, key)
    if kind == "BLEND":
        return blend_target(ob, key).value
    if kind == "CUSTOM":
        return ob[key[len(CUSTOM_PREFIX):]]
    if kind == "VIS":
        return not (compat.bone_hidden(ob) if is_bone(ob) else ob.hide_viewport)
    if _non_euler_rot(ob, kind):
        from .. import rotation_display
        return rotation_display.shown_euler(ob)[idx]
    if kind == "LOC" and is_root_joint(ob):
        return root_translate(ob)[idx]
    return getattr(ob, path)[idx]


# Called before the Channel Box writes a channel: (node, key). The Set Driven Key window keeps a
# typed value on a driven channel this way (operators/driven_key.hold_driven).
WRITE_HOOKS = []


def set_value(ob, key, value):
    for hook in WRITE_HOOKS:
        hook(ob, key)
    path, idx, kind = channel_path(key)
    if kind == 'MODEL':
        node = model_node(ob, key)
        node.preview(bpy.context, dict(node.params, **{path: node.descriptor(path).limit(value)}))
        return
    if kind == "SHAPE":
        _row_write(shape_owner(ob, key), "SHAPE", path, value)
        return
    if kind == "INPUT":
        prop = _own_weight(ob, key)
        if prop is not None:
            ob[prop] = max(0.0, float(value))      # a Maya weight is 0 or more
            ob.id_data.update_tag()     # an ID property write tags nothing: the influence driver would not update
            return
        owner = input_owner(ob, key)
        rna = owner.bl_rna.properties.get(path)
        if rna is not None and rna.type == 'INT' and not isinstance(value, bool):
            value = int(math.floor(value + 0.5))     # a drag / slider gives floats: integer attributes step
        _row_write(owner, "INPUT", path, value)
        return
    if kind == "HISTORY":
        _history_set(ob, key, value)
        return
    if kind == "BLEND":
        blend_target(ob, key).value = value
        return
    if kind == "CUSTOM":
        name = key[len(CUSTOM_PREFIX):]
        cur = ob[name]
        if isinstance(cur, (int, float)) and not isinstance(cur, bool):
            # Maya clamps a typed value to the attribute's Min / Max (Add Attribute)
            try:
                ui = ob.id_properties_ui(name).as_dict()
                value = max(ui.get("min", value), min(ui.get("max", value), value))
            except TypeError:
                pass
        ob[name] = type(cur)(value)
        ob.id_data.update_tag()   # an ID property write tags nothing: drivers reading it would not update
    elif kind == "VIS":
        if is_bone(ob):
            compat.set_bone_hidden(ob, not value)
            from . import layer_joints
            from ..operators import dag
            layer_joints.bump()          # Maya: the joints and objects below a hidden joint are hidden too
            dag.sync()
        else:
            ob.hide_viewport = not value
    elif _non_euler_rot(ob, kind):
        from .. import rotation_display
        rotation_display.set_component(ob, idx, value)
    elif kind == "LOC" and is_root_joint(ob):
        t = root_translate(ob)
        t[idx] = value
        set_root_translate(ob, t)
    else:
        getattr(ob, path)[idx] = value


def keyframe(ob, key, keytype='KEYFRAME'):
    if is_locked(ob, key):
        # like Maya: a locked channel is never keyed (Key Selected, Key All Keyable, S, setKeyframe)
        return False
    prop = _own_weight(ob, key)
    if prop is not None:
        # a one-target constraint's own weight: an ID property of the node, keyed like a custom attribute
        path, idx, kind = f'["{bpy.utils.escape_identifier(prop)}"]', -1, "CUSTOM"
    else:
        path, idx, kind = channel_path(key)
    if kind in {"HISTORY", "MODEL"}:
        return False
    if kind == "VIS" and is_bone(ob):
        return False
    if kind == "BLEND":
        # a blendShape weight is keyed on the mesh's Key datablock (Graph Editor / Dope Sheet show it there)
        kb = blend_target(ob, key)
        if kb is None:
            return False
        from ..operators import anim_layers
        if anim_layers.has_layers(kb.id_data):
            # the weight's blendShape node is in animation layers: keyed on the selected layer, solved like Translate
            return anim_layers.key(kb.id_data, path, -1)
        try:
            ok = kb.id_data.keyframe_insert(path, keytype=keytype)
        except (TypeError, RuntimeError):
            return False
        if ok:
            from ..operators import graph_key_menu
            graph_key_menu.after_insert(kb.id_data, path, -1, bpy.context.scene.frame_current)
        return ok
    if _non_euler_rot(ob, kind):
        # a quaternion is one rotation: Rotate X / Y / Z key all its components
        from .. import rotation_display
        path, idx = rotation_display.curve_path(ob), -1
    elif kind == "LOC" and is_root_joint(ob):
        # a root joint's Translate X / Y / Z mixes the bone's location components (rest axes): key all three
        idx = -1
    if kind in ("SHAPE", "INPUT"):
        owner = shape_owner(ob, key) if kind == "SHAPE" else input_owner(ob, key)
        if owner is None:
            return False
        from ..operators import graph_key_menu
        done = False
        for p, i in (shape_paths(owner, key) if kind == "SHAPE" else input_paths(owner, key)):
            try:
                sub, name = path_struct(owner, p)
                if sub.keyframe_insert(name, index=i, keytype=keytype):
                    graph_key_menu.after_insert(sub, name, i, bpy.context.scene.frame_current)
                    done = True
            except (TypeError, RuntimeError, ValueError):
                pass
        return done
    from ..operators import anim_layers
    if isinstance(ob, bpy.types.Object) and anim_layers.has_layers(ob):
        # Maya animation layers: the key goes to the selected layer, solved so the result is the value
        return anim_layers.key(ob, path, idx)
    if is_bone(ob) and anim_layers.has_layers(ob.id_data):
        # a joint of a layered armature (Blender's keying refuses NLA-stacked data)
        return anim_layers.key_pose_bone(ob, path, idx)
    ok = ob.keyframe_insert(path, index=idx, keytype=keytype)
    if ok:      # Maya Tangents > Default In / Out Tangent
        from ..operators import graph_key_menu
        graph_key_menu.after_insert(ob, path, idx, bpy.context.scene.frame_current)
    return ok


# --- animation state ---------------------------------------------------------------------

def _fcurves(ob):
    from .. import compat
    return compat.id_fcurve_collection(ob.id_data)


def shape_fcurves(ob, key):
    owner = shape_owner(ob, key)
    if owner is None:
        return []
    fcs = compat.id_fcurve_collection(owner)
    if fcs is None:
        return []
    out = []
    for p, i in shape_paths(owner, key):
        fc = fcs.find(p, index=max(i, 0))
        if fc is not None:
            out.append(fc)
    return out


def input_fcurves(ob, key):
    paths = input_curve_paths(ob, key)
    fcs = compat.id_fcurve_collection(input_curve_id(ob, key)) if paths else None
    if fcs is None:
        return []
    out = []
    for p, i in paths:
        fc = fcs.find(p, index=max(i, 0))
        if fc is not None:
            out.append(fc)
    return out


def blend_fcurves(ob, key):
    kb = blend_target(ob, key)
    fcs = compat.id_fcurve_collection(kb.id_data) if kb is not None else None
    fc = fcs.find(blend_path(kb.name)) if fcs is not None else None
    return [fc] if fc is not None else []


def fcurve(ob, key):
    if is_history_key(key) or key.startswith(MODEL_PREFIX):
        return None
    if is_blend_key(key):
        fcs = blend_fcurves(ob, key)
        return fcs[0] if fcs else None
    if is_shape_key(key):
        fcs = shape_fcurves(ob, key)
        return fcs[0] if fcs else None
    if is_input_key(key):
        fcs = input_fcurves(ob, key)
        return fcs[0] if fcs else None
    fcs = _fcurves(ob)
    if fcs is None:
        return None
    path, idx, kind = channel_path(key)
    if _non_euler_rot(ob, kind):
        from .. import rotation_display
        path = full_path(ob, rotation_display.curve_path(ob))
        return None if path is None else next((fc for i in range(4) for fc in [fcs.find(path, index=i)] if fc), None)
    path = full_path(ob, path)
    return None if path is None else fcs.find(path, index=max(idx, 0))


def channel_fcurves(ob, key):
    """Every F-curve behind a channel (a SHAPES channel can have several: spot Cone Angle = size + blend)."""
    if is_shape_key(key):
        return shape_fcurves(ob, key)
    if is_input_key(key):
        return input_fcurves(ob, key)
    if is_blend_key(key):
        return blend_fcurves(ob, key)
    if is_history_key(key) or key.startswith(MODEL_PREFIX):
        return []
    if _non_euler_rot(ob, MAIN_BY_KEY.get(key, ("", "", "", 0, ""))[4]):
        from .. import rotation_display
        fcs, path = _fcurves(ob), full_path(ob, rotation_display.curve_path(ob))
        return [fc for i in range(4) for fc in [fcs.find(path, index=i) if fcs is not None and path else None] if fc]
    fc = fcurve(ob, key)
    return [fc] if fc is not None else []


def remove_channel_curves(ob, key):
    """Delete the channel's animation curves (Maya cutKey -clear on the whole curve). True if any."""
    owner = curve_owner(ob, key)
    fcs = compat.id_fcurve_collection(owner) if owner is not None else None
    curves = channel_fcurves(ob, key)
    for fc in curves:
        fcs.remove(fc)
    return bool(curves)


def driver(ob, key):
    if is_shape_key(key) or is_history_key(key) or key.startswith(MODEL_PREFIX):
        return None
    if is_blend_key(key):
        kb = blend_target(ob, key)
        ad = kb.id_data.animation_data if kb is not None else None
        return ad.drivers.find(blend_path(kb.name)) if ad is not None else None
    if is_input_key(key):
        paths = input_curve_paths(ob, key)
        ad = input_curve_id(ob, key).animation_data if paths else None
        if ad is None:
            return None
        return next((d for p, i in paths for d in [ad.drivers.find(p, index=max(i, 0))] if d is not None), None)
    ad = ob.id_data.animation_data
    if ad is None:
        return None
    path, idx, _kind = channel_path(key)
    path = full_path(ob, path)
    return None if path is None else ad.drivers.find(path, index=max(idx, 0))


def channel_state(ob, key, frame=None):
    """'DRIVEN', 'MUTED', 'LAYERED', 'KEYED' (key on this frame), 'ANIMATED' or None (Maya
    muted = brown: Blender's UI has no brown, the mute icon marks it). A channel in an animation
    layer above BaseAnimation is teal #4db6ac in every layer state, keyed or not
    (Maya); the other channels of a layered object show their BaseAnimation keys."""
    if driver(ob, key) is not None:
        return 'DRIVEN'
    fc = fcurve(ob, key)
    if is_blend_key(key):
        from ..operators import anim_layers
        kb = blend_target(ob, key)
        if kb is not None and anim_layers.has_layers(kb.id_data):
            path = blend_path(kb.name)
            if anim_layers.member_of_layer(kb.id_data, path, -1):
                return 'LAYERED'
            fc = anim_layers.base_curve(kb.id_data, path, -1)
    if (not is_shape_key(key) and not is_input_key(key) and not is_history_key(key) and not is_blend_key(key)
            and (isinstance(ob, bpy.types.Object) or is_bone(ob))):
        from ..operators import anim_layers
        id_ob = ob.id_data
        if anim_layers.has_layers(id_ob):
            path, idx, _kind = channel_path(key)
            path = full_path(ob, path) if path is not None else None
            if path is not None:
                if anim_layers.member_of_layer(id_ob, path, idx):
                    return 'LAYERED'
                fc = anim_layers.base_curve(id_ob, path, idx)
    if fc is None:
        return None
    if fc.mute:
        return 'MUTED'
    frame = bpy.context.scene.frame_current if frame is None else frame
    return 'KEYED' if keyed_at(fc, frame) else 'ANIMATED'


def keyed_at(fc, frame):
    """F-curve ``fc`` has a key within half a frame of ``frame``. A long curve (motion capture: a key on every frame)
    is read in one call; the test is the same double-precision comparison either way."""
    kps = fc.keyframe_points
    n = len(kps)
    if n <= 32:
        return any(abs(kp.co[0] - frame) < 0.5 for kp in kps)
    import numpy as np
    co = np.empty(2 * n, dtype=np.float32)     # the stored type: read in one copy
    kps.foreach_get("co", co)
    return bool((np.abs(co[0::2].astype(np.float64) - frame) < 0.5).any())


_held_states = {}       # (lead pointer, channel key) -> its channel_state while a move runs (``row_state``)
_holding = [False]      # set by ALLSET_PT_channel_box.body for the draw
_UNSET = object()


def _holds_states(context):
    """A move runs in Object / Pose Mode and playback doesn't: until it ends the keys, drivers, layers and the frame
    stay as they are (an animation editor's move that drags keys updates their Action: ``_on_depsgraph`` drops the
    held states)."""
    from .maya_joints import transforming
    screen = getattr(context, "screen", None)
    return (getattr(context, "mode", None) in {'OBJECT', 'POSE'} and transforming()
            and not (screen is not None and screen.is_animation_playing))


def row_state(ob, key):
    """``channel_state`` of a drawn row; while a move runs the state found once is drawn again (every row looked its
    curves up on every redraw of the drag)."""
    if not _holding[0]:
        return channel_state(ob, key)
    k = (ob.as_pointer(), key)
    got = _held_states.get(k, _UNSET)
    if got is _UNSET:
        if len(_held_states) > 512:
            _held_states.clear()
        got = _held_states[k] = channel_state(ob, key)
    return got


def auto_keys(ob, key, context=None):
    """Auto Key keys this channel: keyable and (Maya) already keyed (the kit's own Auto Key,
    operators/auto_key.py)."""
    if not is_keyable(ob, key):
        return False
    return fcurve(ob, key) is not None


# --- text entry ------------------------------------------------------------------

_KIND_ENTRY = {"LOC": "LENGTH", "ROT": "ROTATION", "SCALE": "NONE", "VIS": "BOOL"}


def entry_kind(ob, key):
    if key.startswith(MODEL_PREFIX):
        node = model_node(ob, key)
        return node.spec.kinds[key.rsplit(':', 1)[1]] if node is not None else None
    if key.startswith(CUSTOM_PREFIX):
        return cb_entry.kind_of_value(ob.get(key[len(CUSTOM_PREFIX):]))
    if is_shape_key(key):
        return _row_kind(shape_owner(ob, key), "SHAPE", key[len(SHAPE_PREFIX):])
    if is_input_key(key):
        return _row_kind(input_owner(ob, key), "INPUT", input_parts(key)[2])
    if is_history_key(key):
        from ..operators import prim_history
        _owner, node = history_node_of(ob, key)
        kind = prim_history.entry_kind(node["type"], key[len(HISTORY_PREFIX):])
        return kind
    if is_blend_key(key):
        return "NONE"
    return _KIND_ENTRY[MAIN_BY_KEY[key][4]]
