# SPDX-License-Identifier: GPL-3.0-or-later
"""Set Driven Key nodes and channels: the nodes a loaded object lists (its blendShape and constraint nodes,
``extra_nodes``), their keyable attributes (``channels``), ``Chan`` / ``chan`` (where one attribute's value and
driver live) and the read side of SDK curves (``is_sdk``, ``is_blend``, ``sdk_fcurve``, ``driver_curve``,
``input_x``). Making curves: driven_key_drivers; the window and its operators: driven_key.
"""

import bpy

from ..ui import channel_box as cb

VAR = "sdk"          # the kit's driver variable name: marks a Set Driven Key driver
INPUT_PROP = "allset_sdk_"     # hidden blendWeighted input properties (cb_keys.custom_keys hides allset_*)
SHAPE = "bs:"        # a blendShape target weight: key block ``value`` of a shape Key
WEIGHT = "cw"        # a constraint node's weight (<target>W0)
WEIGHT_PROP = "allset_w_"      # the Maya weight of a multi-target constraint group, on the owner
HELPER = "allset_blend_inputs" # marks the hidden Texture that holds the blendWeighted inputs
HELPER_NAME = ".allset_sdk"


# --- nodes ---------------------------------------------------------------------------------------

def node_of(ob, bone, kind="", sub=""):
    """The node an (object, bone, kind, sub) reference names: object / pose bone, its shape Key ('KEY') or one of
    its constraints ('CON', ``sub`` = constraint name)."""
    if ob is None:
        return None
    if kind == 'KEY':
        return getattr(getattr(ob, "data", None), "shape_keys", None)
    if bone:
        node = ob.pose.bones.get(bone) if ob.pose else None
    else:
        node = ob
    if kind == 'CON':
        return node.constraints.get(sub) if node is not None else None
    return node


def item_node(item):
    """The node of a window list item (ALLSET_PG_sdk_node)."""
    return node_of(item.object, item.bone, item.kind, item.sub)


def is_key(node):
    return isinstance(node, bpy.types.Key)


def is_constraint(node):
    return isinstance(node, bpy.types.Constraint)


def constraint_owner(con):
    """The object or pose bone holding ``con``."""
    ob = con.id_data
    if any(c == con for c in ob.constraints):
        return ob
    for pb in (ob.pose.bones if ob.pose else ()):
        if any(c == con for c in pb.constraints):
            return pb
    return None


def node_ref(node, ob=None):
    """(object, bone name, kind, sub) of a node; a shape Key needs ``ob`` (the object using it)."""
    if is_key(node):
        return ob, "", 'KEY', ""
    if is_constraint(node):
        owner = constraint_owner(node)
        o, b = (owner.id_data, owner.name) if cb.is_bone(owner) else (owner, "")
        return o, b, 'CON', node.name
    return ((node.id_data, node.name) if cb.is_bone(node) else (node, "")) + ("", "")


def store(item, node, ob=None):
    item.object, item.bone, item.kind, item.sub = node_ref(node, ob)


def node_label(node):
    """Maya's node name: blendShapeN (the Key), <owner>_<type>N (constraints), else the object / joint name."""
    if is_constraint(node):
        owner = constraint_owner(node)
        return cb.constraint_node_name(owner, node) if owner is not None else node.name
    return node.name


def extra_nodes(node):
    """Nodes listed under a loaded object / joint in the Driven list: its blendShape and its constraint nodes
    (IK constraints are Maya ikHandles: their ikBlend is the handle's custom attribute, ik_fk.IK_BLEND)."""
    if is_key(node) or is_constraint(node):
        return []
    out = []
    if not cb.is_bone(node):
        keys = getattr(getattr(node, "data", None), "shape_keys", None)
        if keys is not None and keys.use_relative and len(keys.key_blocks) > 1:
            out.append(keys)
    return out + [c for c in cb.constraints(node) if c.type != 'IK']


def channels(node):
    """The node's keyable attributes (Maya SDK lists the Channel Box ones)."""
    if is_key(node):     # Maya targets only: the hidden in-between helper keys are driven
        from . import blend_shapes_227
        return [SHAPE + b.name for b in blend_shapes_227.target_blocks(node)]
    if is_constraint(node):
        return [WEIGHT]
    keys = cb._visible_channels(node)
    return [k for k in keys if not (k == "v" and cb.is_bone(node))]


def attr_label(node, key):
    if key.startswith(SHAPE):
        return key[len(SHAPE):]                 # Maya: the target name (blendShape1.smile)
    if key == WEIGHT:
        return cb.weight_name(node) if is_constraint(node) else "W0"
    return cb.channel_label(key)


# --- channels ------------------------------------------------------------------------------------

class Chan:
    """One driven / driver attribute: the ID that holds its animation data, the full data path + index, the struct
    and attribute that hold the value, and the struct that takes hidden blendWeighted input properties."""
    __slots__ = ("id", "path", "index", "struct", "attr", "host")

    def __init__(self, id_, path, index, struct, attr, host):
        self.id, self.path, self.index, self.struct, self.attr, self.host = id_, path, index, struct, attr, host

    def get(self):
        if self.attr.startswith('["'):
            return float(self.struct[self.attr[2:-2]])
        value = getattr(self.struct, self.attr)
        return float(value[self.index] if self.index >= 0 else value)

    def set(self, value):
        if self.attr.startswith('["'):
            name = self.attr[2:-2]
            self.struct[name] = type(self.struct[name])(value)
            self.id.update_tag()
        elif self.index >= 0:
            getattr(self.struct, self.attr)[self.index] = value
        else:
            setattr(self.struct, self.attr, type(getattr(self.struct, self.attr))(value))

    @property
    def var_path(self):
        return self.path + (f"[{self.index}]" if self.index >= 0 else "")

    def find(self):
        ad = self.id.animation_data
        return None if ad is None else ad.drivers.find(self.path, index=max(self.index, 0))


def _quote(name):
    return name.replace("\\", "\\\\").replace('"', '\\"')


def _rel_path(host, rel):
    """Data path of ``rel`` (relative to ``host``) on the host's ID."""
    return host.path_from_id(rel) if cb.is_bone(host) else rel


def chan(node, key):
    """The Chan of channel ``key`` of ``node`` (None: no such channel)."""
    if node is None or not key:
        return None
    if is_key(node):
        block = node.key_blocks.get(key[len(SHAPE):]) if key.startswith(SHAPE) else None
        if block is None:
            return None
        return Chan(node, f'key_blocks["{_quote(block.name)}"].value', -1, block, "value", node)
    if is_constraint(node):
        owner = constraint_owner(node)
        if key != WEIGHT or owner is None:
            return None
        prop = WEIGHT_PROP + node.name
        if prop not in owner.keys():
            from . import constrain_multi
            prop = constrain_multi.single_weight(node, owner)     # a renamed one-target constraint's weight
        if prop is not None:
            attr = f'["{_quote(prop)}"]'
            return Chan(owner.id_data, _rel_path(owner, attr), -1, owner, attr, owner)
        return Chan(owner.id_data, _rel_path(owner, f'constraints["{_quote(node.name)}"].influence'), -1, node,
                    "influence", owner)
    if cb.is_shape_key(key) or key.startswith(SHAPE) or key == WEIGHT:
        return None
    if key.startswith(cb.CUSTOM_PREFIX):
        if key[len(cb.CUSTOM_PREFIX):] not in node.keys():
            return None
    elif key not in cb.MAIN_BY_KEY:
        return None
    path, idx, _kind = cb.channel_path(key)
    full = cb.full_path(node, path)
    if full is None:
        return None
    return Chan(node.id_data, full, idx, node, path, node)


def raw_value(node, key):
    return chan(node, key).get()


def set_raw_value(node, key, value):
    chan(node, key).set(value)


def _var_path(node, key):
    """Driver variable path of a channel on the node's ID (pose bones: on the armature object)."""
    return chan(node, key).var_path


def _id_type(id_):
    if isinstance(id_, bpy.types.Key):
        return 'KEY'
    return 'TEXTURE' if isinstance(id_, bpy.types.Texture) else 'OBJECT'


def is_sdk(fc):
    return fc is not None and fc.driver is not None and any(v.name == VAR for v in fc.driver.variables)


def is_blend(fc):
    """A summed (Maya blendWeighted) channel driver: SUM over the hidden input properties."""
    return is_sdk(fc) and fc.driver.type == 'SUM' and all(
        INPUT_PROP in v.targets[0].data_path for v in fc.driver.variables)


def sdk_fcurve(node, key):
    """The kit SDK driver F-curve of a driven channel (the one driver's curve, or the summed channel driver)."""
    c = chan(node, key)
    fc = c.find() if c is not None else None
    return fc if is_sdk(fc) else None


def _inputs(blend):
    """[(variable, input F-curve or None)] of a summed channel driver."""
    out = []
    for var in blend.driver.variables:
        t = var.targets[0]
        ad = t.id.animation_data if t.id is not None else None
        out.append((var, ad.drivers.find(t.data_path) if ad is not None else None))
    return out


def input_curves(node, key):
    """Every per-driver SDK curve of a driven channel: [the channel curve] or the blendWeighted inputs' curves."""
    fc = sdk_fcurve(node, key)
    if fc is None:
        return []
    if not is_blend(fc):
        return [fc]
    return [f for _v, f in _inputs(fc) if is_sdk(f)]


def _target(fc):
    return next(v for v in fc.driver.variables if v.name == VAR).targets[0]


def _reads(fc, d):
    t = _target(fc)
    return t.id == d.id and t.data_path == d.var_path


def driver_curve(driven, key, driver_node, driver_key):
    """The SDK curve of ``driven``.``key`` that reads ``driver_node``.``driver_key``, or None."""
    d = chan(driver_node, driver_key)
    if d is None:
        return None
    return next((fc for fc in input_curves(driven, key) if _reads(fc, d)), None)


LENGTH_KEYS = ("tx", "ty", "tz")


def curve_scale(driver_key):
    """Curve x per raw driver value. Blender merges F-curve keys less than 0.01 apart in x,
    and a length driver in the cm template moves 0.01 BU per cm: those curves keep x in display units."""
    from . import units
    k = units.maya_unit()
    return 1.0 / k if driver_key in LENGTH_KEYS and k < 1.0 else 1.0


def fcurve_scale(fc):
    """The x scale a kit SDK curve was made with (``sdk*<s>`` expression; plain average = 1)."""
    d = fc.driver
    if d.type == 'SCRIPTED' and d.expression.startswith(VAR + "*"):
        try:
            return float(d.expression[len(VAR) + 1:])
        except ValueError:
            return 1.0
    return 1.0


def input_x(fc):
    """The curve x a per-driver SDK curve sits at now (its driver's raw value x its scale)."""
    t = _target(fc)
    if t.id is None:
        return 0.0
    try:
        value = t.id.path_resolve(t.data_path)
    except ValueError:
        return 0.0
    return float(value) * fcurve_scale(fc)


def input_value(fc):
    """What a per-driver SDK curve gives now (0 for a curve without keys)."""
    return fc.evaluate(input_x(fc)) if len(fc.keyframe_points) else 0.0
