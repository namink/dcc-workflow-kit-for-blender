# SPDX-License-Identifier: GPL-3.0-or-later
"""Channel keys: the strings that name a Channel Box channel (tx ... v, custom "cp:", SHAPES "sh:", INPUTS "in:",
constraint weight "cw:", blendShape weight "bw:", creation node "ph:", modeling node "mh:") and each node's lock /
hide / keyable flags. Entry points: MAIN, channel_path, row_key, is_locked, set_locked.
Related: cb_values.py."""

import bpy

from .. import i18n

from .cb_nodes import is_bone


# key, label, data path, index, kind
MAIN = (
    ("tx", i18n.mark("Translate X"), "location", 0, "LOC"),
    ("ty", i18n.mark("Translate Y"), "location", 1, "LOC"),
    ("tz", i18n.mark("Translate Z"), "location", 2, "LOC"),
    ("rx", i18n.mark("Rotate X"), "rotation_euler", 0, "ROT"),
    ("ry", i18n.mark("Rotate Y"), "rotation_euler", 1, "ROT"),
    ("rz", i18n.mark("Rotate Z"), "rotation_euler", 2, "ROT"),
    ("sx", i18n.mark("Scale X"), "scale", 0, "SCALE"),
    ("sy", i18n.mark("Scale Y"), "scale", 1, "SCALE"),
    ("sz", i18n.mark("Scale Z"), "scale", 2, "SCALE"),
    ("v", i18n.mark("Visibility"), "hide_viewport", -1, "VIS"),
)
MAIN_BY_KEY = {c[0]: c for c in MAIN}
_LOCK_PROP = {"LOC": "lock_location", "ROT": "lock_rotation", "SCALE": "lock_scale"}

# Per-object bookkeeping for Maya attribute flags Blender doesn't have.
HIDDEN_PROP = "allset_cb_hidden"
NONKEYABLE_PROP = "allset_cb_nonkeyable"
CUSTOM_PREFIX = "cp:"
HISTORY_PREFIX = "ph:"   # an attribute of the creation node (polyCube1 ...): "ph:<attribute>"
MODEL_PREFIX = "mh:"     # a parameter of the active modeling node, identified by node kind and field
INPUT_PREFIX = "in:"     # an INPUTS row as a channel: "in:<modifier type>:<nth of that type>:<property>"
CON_PREFIX = "cw:"       # a constraint's target weight as a channel: "cw:<constraint type>:<nth of that type>:influence"
                         # (the influence, or the constraint's own weight once it has one: constraint_weight)
SHAPE_PREFIX = "sh:"     # a SHAPES row as a channel: light Intensity / Color, camera Focal Length ...
BLEND_PREFIX = "bw:"     # a blendShape target weight in INPUTS: "bw:<target name>" (the shape key's value)


def model_key(record, field):
    name = '@'+record.name if getattr(record, 'history_id', None) else ''
    return f'{MODEL_PREFIX}{record.spec.kind}{name}:{field}'


def model_parts(key):
    _prefix, identity, field = key.split(':', 2)
    kind, _separator, name = identity.partition('@')
    return kind, name, field


def _flag_list(ob, prop):
    raw = ob.get(prop, "")
    return [s for s in raw.split(",") if s] if isinstance(raw, str) else []


def _set_flag_list(ob, prop, keys):
    if keys:
        ob[prop] = ",".join(sorted(set(keys)))
    elif prop in ob:
        del ob[prop]


def is_hidden(ob, key):
    return key in _flag_list(ob, HIDDEN_PROP)


def is_keyable(ob, key):
    if key.startswith(MODEL_PREFIX):
        return False
    if key == "v" and is_bone(ob):
        return False   # Bone.hide lives on the armature data, not in the object's action
    return key not in _flag_list(ob, NONKEYABLE_PROP)


def is_locked(ob, key):
    if key.startswith(HISTORY_PREFIX):
        from ..operators import prim_history
        ob = prim_history.owner_of(ob) or ob
    if key.startswith((MODEL_PREFIX, HISTORY_PREFIX)):
        keys = _flag_list(ob, 'allset_cb_model_locked')
        if key.startswith(MODEL_PREFIX):
            kind, _name, field = model_parts(key)
            return key in keys or f'{MODEL_PREFIX}{kind}:{field}' in keys
        return key in keys
    c = MAIN_BY_KEY.get(key)
    if c is None or c[4] not in _LOCK_PROP:
        return False
    return bool(getattr(ob, _LOCK_PROP[c[4]])[c[3]])


def set_locked(ob, key, locked):
    if key.startswith(HISTORY_PREFIX):
        from ..operators import prim_history
        ob = prim_history.owner_of(ob) or ob
    if key.startswith((MODEL_PREFIX, HISTORY_PREFIX)):
        keys = set(_flag_list(ob, 'allset_cb_model_locked'))
        keys.add(key) if locked else keys.discard(key)
        if not locked and key.startswith(MODEL_PREFIX):
            kind, _name, field = model_parts(key)
            keys.discard(f'{MODEL_PREFIX}{kind}:{field}')
        _set_flag_list(ob, 'allset_cb_model_locked', keys)
        return True
    c = MAIN_BY_KEY.get(key)
    if c is None or c[4] not in _LOCK_PROP:
        return False
    arr = getattr(ob, _LOCK_PROP[c[4]])
    arr[c[3]] = locked
    return True


def custom_keys(ob):
    """Numeric custom properties = Maya extra (user-defined) attributes."""
    out = []
    for k in ob.keys():
        if k.startswith("_") or k.startswith("allset_"):
            continue
        if isinstance(ob[k], (int, float)):  # bool is an int too
            out.append(k)
    return sorted(out)


def is_shape_key(key):
    return key.startswith(SHAPE_PREFIX)


def is_input_key(key):
    """An INPUTS node's channel: a modifier's property or a constraint's target weight (#329)."""
    return key.startswith(INPUT_PREFIX) or key.startswith(CON_PREFIX)


def is_constraint_key(key):
    return key.startswith(CON_PREFIX)


def input_key(mod_type, nth, name):
    return f"{INPUT_PREFIX}{mod_type}:{nth}:{name}"


def constraint_key(con_type, nth, name):
    return f"{CON_PREFIX}{con_type}:{nth}:{name}"


def input_parts(key):
    """(modifier / constraint type, nth, property) of an INPUTS channel key."""
    prefix = CON_PREFIX if is_constraint_key(key) else INPUT_PREFIX
    mod_type, nth, name = key[len(prefix):].split(":", 2)
    return mod_type, int(nth), name


def is_blend_key(key):
    return key.startswith(BLEND_PREFIX)


def blend_path(name):
    """Data path of a target weight on the Key datablock (its animation lives there, like Maya's blendShape node)."""
    return f'key_blocks["{bpy.utils.escape_identifier(name)}"].value'


def is_history_key(key):
    return key.startswith(HISTORY_PREFIX)


def row_key(row):
    """The channel key of a Channel Box row (CUSTOM / SHAPE / INPUT / CONSTRAINT / BLEND), or None."""
    if row.kind == "CUSTOM":
        return CUSTOM_PREFIX + row.name
    if row.kind == "SHAPE":
        return SHAPE_PREFIX + row.name
    if row.kind == "INPUT":
        return input_key(row.mod_type, row.nth, row.name)
    if row.kind == "CONSTRAINT":
        return constraint_key(row.mod_type, row.nth, row.name)
    if row.kind == "BLEND":
        return BLEND_PREFIX + row.name
    return None


def channel_path(key):
    """(data path, index, kind) for a channel key."""
    if key.startswith(MODEL_PREFIX):
        return key.rsplit(':', 1)[1], -1, 'MODEL'
    if key.startswith(CUSTOM_PREFIX):
        return f'["{key[len(CUSTOM_PREFIX):]}"]', -1, "CUSTOM"
    if is_shape_key(key):
        return key[len(SHAPE_PREFIX):], -1, "SHAPE"
    if is_input_key(key):
        return input_parts(key)[2], -1, "INPUT"
    if is_history_key(key):
        return key[len(HISTORY_PREFIX):], -1, "HISTORY"
    if is_blend_key(key):
        return blend_path(key[len(BLEND_PREFIX):]), -1, "BLEND"
    c = MAIN_BY_KEY[key]
    return c[2], c[3], c[4]


def nice_name(name):
    """Maya's nice attribute name (Channel Names > Nice, the default):
    ``fingerCurl`` -> "Finger Curl", ``curl`` -> "Curl", ``ik_blend2`` -> "Ik Blend 2"."""
    import re
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])", " ", name.replace("_", " ")).split()
    return " ".join(w[:1].upper() + w[1:] for w in words) or name
