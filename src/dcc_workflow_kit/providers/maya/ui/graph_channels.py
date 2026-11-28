# SPDX-License-Identifier: GPL-3.0-or-later
"""The channels of one Maya list node (object, joint, blendShape node, character set): its F-curves and driver
curves, a curve's Maya attribute name / colour / Show > Attributes kind, node identity and Maya attribute order, plus
the one-pass memo (``one_pass``) the list helpers share. Used by graph_list, graph_list_sync and graph_outliner.
"""

import contextlib
import re
import types

import bpy


# --- Graph Editor channel list (Maya outliner pane: node rows, "Translate X" rows) --------------------------------
# Maya lists DAG nodes with their animated attributes under them: objects, joints (= pose bones;
# their curves live on the armature object as ``pose.bones["joint1"].location``) and the
# blendShape node of a mesh (= its shape-key datablock, ``rig_tools`` names it blendShapeN; its curves are the Key
# ID's ``key_blocks["smile"].value``, one row per target, Maya's attribute = the target name). #96.

MAYA_ATTR = {"location": "Translate", "rotation_euler": "Rotate", "scale": "Scale", "rotation_quaternion": "Rotate",
             "delta_location": "Delta Translate", "delta_rotation_euler": "Delta Rotate", "delta_scale": "Delta Scale"}
# One-value attributes: Maya visibility = hide_viewport; hide_render has no Maya transform attribute,
# the closest is the shape's render stat Primary Visibility.
MAYA_SCALAR = {"hide_render": "Primary Visibility"}
AXES = "XYZ"
# Attribute name colours in the Graph Editor outliner, like Maya (Translate X red,
# Translate Y green; Z blue by the same rule as the manipulator / theme axis colours), other attributes light grey.
AXIS_COLOR = ((0.9, 0.25, 0.25, 1.0), (0.25, 0.85, 0.25, 1.0), (0.35, 0.55, 1.0, 1.0))
TEXT = (0.85, 0.85, 0.85, 1.0)
_BONES = 'pose.bones["'
_SHAPES = 'key_blocks["'
_bone_names = {}                         # data path -> its joint name (None: not a joint's path)
_BONE_NAMES_MAX = 200000
# One pass (a ``sync`` of every editor, one list build): results that can't change while it runs are computed once —
# an owner's drivers by joint, an object's curves by joint, the selection, each editor's listed nodes. None = no pass
# open (every call computes).
_memo = {"on": None}


@contextlib.contextmanager
def one_pass():
    """Open a pass (nested passes share the outer one): the list helpers reuse what they computed inside it."""
    if _memo["on"] is not None:
        yield
        return
    _memo["on"] = {}
    try:
        yield
    finally:
        _memo["on"] = None


def _memo_get(key, make):
    memo = _memo["on"]
    if memo is None:
        return make()
    try:
        return memo[key]
    except KeyError:
        value = memo[key] = make()
        return value


def _maya_names():
    """Attribute -> Maya name: the Channel Box's names first (one table), then MAYA_ATTR / MAYA_SCALAR."""
    from . import channel_box
    names, scalar = dict(MAYA_ATTR), dict(MAYA_SCALAR)
    for _key, label, path, idx, _kind in channel_box.MAIN:
        if idx < 0:
            scalar[path] = label
        else:
            names.setdefault(path, label.rsplit(" ", 1)[0])
    return names, scalar


def attr_label(fc):
    """Maya name of an F-curve's attribute: "Translate X", "Visibility", custom properties and blend shape targets
    by name."""
    path, idx = fc.data_path, fc.array_index
    if path.startswith(_SHAPES) and path.endswith('"].value'):
        return bpy.utils.unescape_identifier(path[len(_SHAPES):-len('"].value')])
    if path.endswith("]") and '["' in path:
        return path.rsplit('["', 1)[1].rstrip('"]')
    tail = path.rsplit(".", 1)[-1]
    names, scalar = _maya_names()
    if tail in scalar:
        return scalar[tail]
    if tail in names:
        name = names[tail]
        if tail == "rotation_quaternion":
            return f"{name} {'WXYZ'[idx]}"
        return f"{name} {AXES[idx]}" if idx < 3 else name
    return tail.replace("_", " ").title() + (f" {AXES[idx]}" if idx < 3 and fc.array_index else "")


def _themed(color, field, space=None):
    """A kit list colour moved with the Blender theme (ui/theme_follow.py)."""
    from . import theme_follow
    return theme_follow.follow(color, theme_follow.editor_of(space or bpy.context.space_data), field)


def attr_color(fc):
    tail = fc.data_path.rsplit(".", 1)[-1]
    if tail in MAYA_ATTR and tail != "rotation_quaternion" and fc.array_index < 3:
        return AXIS_COLOR[fc.array_index]
    return _themed(TEXT, "text")


def object_curves(ob):
    """The object's own F-curves (its action's slot), Blender order."""
    from .. import compat
    return compat.id_fcurves(ob)


def data_curves(ob):
    """Curves of the object's data-block (Maya shape node attributes: a light's intensity, a camera's focal length):
    Maya's node row draws its shape's animated channels too. Shape keys have their own row."""
    from .. import compat
    data = getattr(ob, "data", None)
    return compat.id_fcurves(data) if isinstance(data, bpy.types.ID) else []


def shape_key(ob):
    """The object's shape-key datablock (Maya blendShape node) when it is animated, else None."""
    from .. import compat
    key = getattr(getattr(ob, "data", None), "shape_keys", None)
    return key if key is not None and compat.id_fcurves(key) else None


def _parse_bone_name(path):
    if not path.startswith(_BONES):
        return None
    end = path.find('"]', len(_BONES))
    while end > 0 and path[end - 1] == "\\":      # an escaped quote inside the name
        end = path.find('"]', end + 1)
    return bpy.utils.unescape_identifier(path[len(_BONES):end]) if end > 0 else None


def _bone_name(path):
    """``pose.bones["joint1"].location`` -> "joint1" (None for other paths). The name depends on the path text
    alone, so it is kept per path."""
    try:
        return _bone_names[path]
    except KeyError:
        pass
    if len(_bone_names) >= _BONE_NAMES_MAX:
        _bone_names.clear()
    name = _bone_names[path] = _parse_bone_name(path)
    return name


def split_object_curves(ob):
    """(the object's own curves, [(pose bone, its curves)] in the armature's bone order): joints are Maya nodes."""
    if _memo["on"] is None:
        return _split_object_curves(ob)
    own, joints = _memo_get(("split", ob.as_pointer()), lambda: _split_object_curves(ob))
    return list(own), [(pb, list(c)) for pb, c in joints]


def _split_object_curves(ob):
    own, by_bone = [], {}
    bones = ob.pose.bones if ob.type == 'ARMATURE' and ob.pose is not None else None
    for fc in object_curves(ob):
        name = _bone_name(fc.data_path) if bones is not None else None
        pb = bones.get(name) if name is not None else None
        if pb is None:
            own.append(fc)
        else:
            by_bone.setdefault(pb.name, []).append(fc)
    return own, [(pb, by_bone[pb.name]) for pb in (bones or ()) if pb.name in by_bone]


def character_curves(scene, ks):
    """F-curves a character set's members (its own and its subcharacters' attributes) have (#104)."""
    from .. import compat
    from ..operators import character_sets
    out = []
    for p in character_sets.all_paths(scene, ks):
        if p.id is None:
            continue
        for fc in compat.id_fcurves(p.id):
            if fc.data_path == p.data_path and (p.use_entire_array or fc.array_index == p.array_index)                     and fc not in out:
                out.append(fc)
    return out


def node_name(node):
    return node.bl_label if isinstance(node, bpy.types.KeyingSet) else node.name


def node_curves(node):
    """F-curves of one outliner node: an object (without its joints'), a pose bone, a shape-key datablock or a
    character set."""
    from .. import compat
    if isinstance(node, bpy.types.KeyingSet):
        return character_curves(bpy.context.scene, node)
    if isinstance(node, bpy.types.Collection):       # a kit set (Show > Objects > Sets)
        from ..operators import sets
        return [fc for ob in sets.members(node, bpy.context.scene) for fc in maya_order(split_object_curves(ob)[0])]
    if isinstance(node, bpy.types.PoseBone):
        return dict((pb.name, c) for pb, c in split_object_curves(node.id_data)[1]).get(node.name, [])
    if isinstance(node, bpy.types.Key):
        return compat.id_fcurves(node)
    return split_object_curves(node)[0]


def node_key(node):
    """Identity of a node row (``_expanded`` / picks): object name, ("JOINT", armature, bone), ("SHAPES", key)."""
    if isinstance(node, bpy.types.PoseBone):
        return ("JOINT", node.id_data.name, node.name)
    if isinstance(node, bpy.types.Key):
        return ("SHAPES", node.name)
    if isinstance(node, bpy.types.KeyingSet):
        return ("CHARACTER", node.bl_label)
    if isinstance(node, bpy.types.Collection):
        return ("SET", node.name)
    return node.name


def _path_index(path):
    """``location[0]`` -> ("location", 0); other paths keep index 0 (custom properties end in ``"]``)."""
    m = re.match(r"^(.*)\[(\d+)\]$", path)
    return (m.group(1), int(m.group(2))) if m else (path, 0)


def sdk_target(fc):
    """(driver ID, its data path, index) a kit SDK driver curve reads (variable ``sdk``), else None."""
    from ..operators import driven_key
    if isinstance(fc.id_data, bpy.types.Action):
        return None
    var = next((v for v in fc.driver.variables if v.name == driven_key.VAR), None)
    if var is None or not var.targets or var.targets[0].id is None:
        return None
    t = var.targets[0]
    path, idx = _path_index(t.data_path)
    return t.id, path, idx


def upstream_rows(node, fc):
    """Maya Show Upstream Curves rows under a driven-key channel: the SDK curve
    labelled by its input ("> pCube1.User A") = the driver curve itself, then the driver attribute's own anim curve
    ("pCube1.User A") when it is keyed. [(kind, fcurve, label)]."""
    tgt = sdk_target(fc)
    if tgt is None:
        return []
    owner, path, idx = tgt
    label = attr_label(types.SimpleNamespace(data_path=path, array_index=idx))
    bone = _bone_name(path)
    name = f"{bone if bone is not None else owner.name}.{label}"
    out = [("UP_SDK", fc, "> " + name)]
    own = next((c for c in object_curves(owner) if c.data_path == path and c.array_index == idx), None)
    if own is not None:
        out.append(("UP_CURVE", own, name))
    return out


# Show > Attributes kinds of a curve (Maya attribute filters): keyed curves are "Driven by Anim Curve", kit SDK
# drivers (variable ``sdk``) "Driven by Driven Key", scripted drivers "Driven by Expression", custom properties
# "User Defined", Channel Box hidden channels (Channel Control / Hide Selected, ``cb_keys.HIDDEN_PROP``) "Hidden".

def _channel_tail(node, fc):
    path = fc.data_path
    if isinstance(node, bpy.types.PoseBone):
        head = node.path_from_id()
        path = path[len(head):].lstrip(".") if path.startswith(head) else path
    return path


def is_driver(fc):
    """A driver curve (Maya: an attribute driven by a driven key / expression), not an action's keyed curve."""
    return not isinstance(fc.id_data, bpy.types.Action)


def _character_routed(node):
    """{(data path, index)} of the node's channels that are character members (index -1 = whole array): Maya routes
    a character member's curve through the character node, so it is not "Driven by Anim Curve"."""
    from ..operators import character_sets
    owner = node.id_data if isinstance(node, bpy.types.PoseBone) else node
    scene = bpy.context.scene
    out = set()
    for ks in character_sets.characters(scene):
        for p in ks.paths:
            if p.id == owner:
                out.add((p.data_path, -1 if p.use_entire_array else p.array_index))
    return out


def curve_kinds(node, fc, driver=None, routed=()):
    """Maya Show > Attributes kinds of a curve: a keyed curve is "anim_curve" unless it is
    a character member (``routed``); a kit SDK driver is "driven_key" and "anim_curve" (its input is the SDK anim
    curve), another scripted driver "expression"."""
    from . import channel_box
    kinds = set()
    if is_driver(fc) if driver is None else driver:
        from ..operators import driven_key
        if any(v.name == driven_key.VAR for v in fc.driver.variables):
            kinds |= {"driven_key", "anim_curve"}
        elif fc.driver.type == 'SCRIPTED':
            kinds.add("expression")
    elif (fc.data_path, fc.array_index) not in routed and (fc.data_path, -1) not in routed:
        kinds.add("anim_curve")
    tail = _channel_tail(node, fc)
    key = None
    if tail.startswith('["') and tail.endswith('"]'):
        kinds.add("user_defined")
        key = channel_box.CUSTOM_PREFIX + bpy.utils.unescape_identifier(tail[2:-2])
    else:
        key = next((c[0] for c in channel_box.MAIN if c[2] == tail and (c[3] < 0 or c[3] == fc.array_index)), None)
    owner = node if isinstance(node, (bpy.types.Object, bpy.types.PoseBone)) else None
    if key is not None and owner is not None and channel_box.is_hidden(owner, key):
        kinds.add("hidden")
    return kinds


def node_drivers(node):
    """Driver curves of a node (Maya attributes driven by an expression / driven key)."""
    if isinstance(node, bpy.types.KeyingSet):
        return []
    owner = node.id_data if isinstance(node, bpy.types.PoseBone) else node
    ad = getattr(owner, "animation_data", None)
    if ad is None:
        return []
    every, by_joint = _memo_get(("drivers", owner.as_pointer()), lambda: _drivers_by_joint(owner, ad))
    if isinstance(node, bpy.types.PoseBone):
        return list(by_joint.get(node.name, ()))
    if isinstance(owner, bpy.types.Object) and owner.type == 'ARMATURE':
        return list(by_joint.get(None, ()))        # the armature's own (not a joint's) driver curves
    return list(every)


def _drivers_by_joint(owner, ad):
    """(every driver curve, {joint name or None: its driver curves}) of one owner, in Blender's order."""
    every, by_joint = list(ad.drivers), {}
    if isinstance(owner, bpy.types.Object):
        for fc in every:
            by_joint.setdefault(_bone_name(fc.data_path), []).append(fc)
    else:
        by_joint[None] = every
    return every, by_joint


# Maya lists a node's attributes in its attribute order (translate, rotate, scale, visibility, then the rest, e.g.
# custom attributes / blend shape targets), not in the order they were keyed.
ATTR_ORDER = ("location", "rotation_euler", "rotation_quaternion", "scale", "hide_viewport", "hide_render")


def maya_order(curves):
    def key(fc):
        tail = fc.data_path.rsplit(".", 1)[-1]
        return (ATTR_ORDER.index(tail) if tail in ATTR_ORDER else len(ATTR_ORDER), fc.array_index)
    return sorted(curves, key=key)      # stable: other attributes keep Blender's order
