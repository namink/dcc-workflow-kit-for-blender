# SPDX-License-Identifier: GPL-3.0-or-later
"""Which nodes and channels the Maya Graph Editor / Dope Sheet list shows: loaded list, Auto Load, Hierarchy Below,
Show > Objects / Attributes filters (``FLAGS``), pinned channels and Show Upstream Curves rows. Entry points
``listed_objects``, ``listed_nodes``, ``rows``, ``listed_curves``; built on ``graph_channels``.
"""

import bpy

from . import graph_layers
from .graph_channels import (_memo_get, one_pass, attr_label, node_key, node_curves, data_curves, shape_key,
                             object_curves, split_object_curves, node_drivers, character_curves, maya_order,
                             is_driver, upstream_rows, sdk_target, curve_kinds, _character_routed)


_expanded = {}                           # node key -> bool (Maya shows attributes expanded)


def row_id(row):
    kind, node, fc = row
    if kind in graph_layers.KINDS:
        return graph_layers.row_id(row)
    if kind in ("UP_SDK", "UP_CURVE"):       # Show Upstream Curves rows: one per label under the node
        return (node_key(node), kind, fc.data_path, fc.array_index, _up_label.get((kind, fc.as_pointer()), ""))
    return node_key(node) if kind != "ATTR" else (node_key(node), fc.data_path, fc.array_index)


def listed_objects(context, space):
    """Objects the Maya list shows as rows: the loaded list, else the selection with Auto Load (keyed or not),
    else all animated ones (also by shape keys / data-block curves); plus Hierarchy Below (Dope Sheet), narrowed by Show > Objects, by name. Driven
    channels count like keyed ones (Maya lists a driven-key / expression
    channel)."""
    ds = space.dopesheet
    base = row_objects(context, space)
    if base is not None:
        # #192: Maya lists every loaded / auto-loaded node, keyed or not (a bare node row until it is keyed)
        base = set(base)
        obs = [ob for ob in context.scene.objects if ob in base]
    else:
        obs = [ob for ob in context.scene.objects
               if (ob.animation_data and (ob.animation_data.action or ob.animation_data.drivers))
               or shape_key(ob) is not None or data_curves(ob)]
    if not ds.show_hidden:
        obs = [ob for ob in obs if ob.visible_get()]
    return sorted(obs, key=lambda o: o.name)


# --- List > Load / Add Selected Objects, Auto Load, Pin Channel, Show filters (#110) --------------------
# Maya: Auto Load Selected Objects is on by
# default and the list follows the selection; unchecking it freezes the list shown then; Load / Add Selected Objects
# are greyed while Auto Load is on (the kit's poll fails) and replace / append the frozen list (nothing selected =
# empty list), Auto Load stays off. Maya's first Add right after a Load drops the loaded objects — the kit appends
# (looks like a Maya bug). Pin Channel pins the highlighted rows (a node row = all its channels; nothing
# highlighted = nothing pinned); pinned channels stay listed under their node, below the listed nodes. Show >
# Attributes / Objects check items list only the checked kinds (several = union). Show Upstream Curves (on by default)
# lists a driven-key channel's SDK curve and the driver's own curve under it. Pins / filters are one state for every
# editor (Maya keeps pins per editor).
LIST_MARK = "allset_list"      # kit list collection marker
LOADED = "allset_loaded"       # loaded object names (absent = no loaded list)
BONES = "allset_bones"         # loaded joints "armature\tbone" (an armature without entries = all its joints)
AUTO = "allset_auto"           # Auto Load state while Only Show Selected is off for the kit list
ATTR_FILTERS = ("hidden", "anim_curve", "expression", "driven_key", "user_defined")
_pinned = set()                # ATTR row ids of pinned channels (Maya Pin Channel; session state)


def _ds(space):
    return getattr(space, "dopesheet", None)


def _is_dope_space(space):
    return getattr(space, "type", "") == 'DOPESHEET_EDITOR'


def kit_list(space):
    """The editor's kit list collection, or None (Blender's own filters)."""
    coll = getattr(_ds(space), "filter_collection", None)
    return coll if coll is not None and coll.get(LIST_MARK) else None


def loaded_names(space):
    coll = kit_list(space)
    names = coll.get(LOADED) if coll is not None else None
    return None if names is None else list(names)


def auto_load(space):
    """Maya Auto Load Selected Objects: Blender's Only Show Selected, or the kit list's remembered state."""
    ds = _ds(space)
    if ds is None:
        return False
    if ds.show_only_selected:
        return True
    coll = kit_list(space)
    return bool(coll is not None and coll.get(LOADED) is None and coll.get(AUTO, False))


def _wm_flag(name):
    return bool(getattr(bpy.context.window_manager, name, False))


def attr_filters():
    """The checked Show > Attributes filters (Maya: none checked = every animated attribute)."""
    return {f for f in ATTR_FILTERS if _wm_flag("allset_attr_" + f)}


def _selected_objects(context):
    return list(_memo_get(("selected", context.scene.as_pointer()), lambda: _scene_selection(context)))


def _scene_selection(context):
    """``[ob for ob in context.scene.objects if ob.select_get()]``. ``select_get`` reads the object's base in the
    context view layer, so the selected ones are that view layer's selected bases (one pass in C, no Python call per
    object); the scene's walk only puts them in its order and stops at the last one."""
    view_layer = getattr(context, "view_layer", None)
    if view_layer is None:
        return [ob for ob in context.scene.objects if ob.select_get()]
    picked = set(view_layer.objects.selected)
    out = []
    if picked:
        for ob in context.scene.objects:
            if ob in picked:
                out.append(ob)
                if len(out) == len(picked):
                    break
    return out


def _descendants(obs):
    out, seen = [], set()
    for ob in obs:
        for child in ob.children_recursive:
            if child not in seen:
                seen.add(child)
                out.append(child)
    return out


def _object_kinds():
    """The checked kit Show > Objects items (Maya: checked = only nodes of those types)."""
    return {k for k, flag in (("ik", "allset_show_ik_handles"), ("sets", "allset_show_sets"),
                              ("characters", "allset_show_characters")) if _wm_flag(flag)}


def row_objects(context, space):
    """Objects the Maya list is made of (None = every object): loaded, else selected with Auto Load, plus Hierarchy
    Below (Dope Sheet). A checked Show > Objects item lists only nodes of that type:
    IkHandles keeps the IK handles (kit IK handles = IK constraint targets, operators/by_type.py), Sets / Characters
    alone list no objects (their nodes come from ``listed_nodes``)."""
    names = loaded_names(space)
    in_scene = False     # every object of ``obs`` is known to be in the scene (the selection is)
    if names is not None:
        obs = [ob for ob in (bpy.data.objects.get(n) for n in names) if ob is not None]
    elif auto_load(space):
        obs = _selected_objects(context)
        in_scene = True
    else:
        obs = None
    if obs is not None and _is_dope_space(space) and _wm_flag("allset_hierarchy_below"):
        # Maya shows the descendants' keys in the object's own rows without listing them; Blender's C Dope Sheet
        # list can't merge another object's keys into a row, so the kit lists the descendants
        below = [o for o in _descendants(obs) if o not in obs]
        obs = obs + below
        in_scene = in_scene and not below
    kinds = _object_kinds()
    if "ik" in kinds:
        from ..operators import by_type
        handles = by_type.ik_handles(context.scene)
        if obs is None:
            obs, in_scene = handles, False
        else:
            obs = [o for o in obs if o in handles]
    elif kinds:
        obs = []
    flt = attr_filters()
    if flt and _is_dope_space(space):
        # Blender's Dope Sheet channel list can't drop single channels (fc.hide is Graph Editor only, drivers are
        # no Dope Sheet channels): the attribute filters keep the objects with a matching attribute
        if obs is None:
            obs, in_scene = [o for o in context.scene.objects if _has_attr(o, flt)], True
        else:
            obs = [o for o in obs if _has_attr(o, flt)]
    if obs is not None and not in_scene:
        scene_obs = set(context.scene.objects)
        obs = [o for o in obs if o in scene_obs]
    return obs


def _has_attr(ob, flt):
    own, joints = split_object_curves(ob)
    if filter_curves(ob, own + node_drivers(ob), flt):
        return True
    if any(filter_curves(pb, curves + node_drivers(pb), flt) for pb, curves in joints):
        return True
    key = shape_key(ob)
    return bool(key is not None and filter_curves(key, object_curves(key) + node_drivers(key), flt))


def _character_members(context):
    from ..operators import character_sets
    out = []
    for ks in character_sets.characters(context.scene):
        for p in character_sets.all_paths(context.scene, ks):
            if isinstance(p.id, bpy.types.Object) and p.id not in out:
                out.append(p.id)
    return out


def _bone_loaded(space, pb):
    """Is this joint in the loaded list (an armature loaded without joints: all of them)?"""
    coll = kit_list(space)
    if coll is None or coll.get(LOADED) is None:
        return True
    bones = list(coll.get(BONES, ()))
    arm = pb.id_data.name
    mine = [b for b in bones if b.split("\t", 1)[0] == arm]
    return not mine or f"{arm}\t{pb.name}" in mine


def _node_of_key(key):
    """Node of a row id's node key (objects / joints / blendShape nodes), None when gone."""
    if isinstance(key, str):
        return bpy.data.objects.get(key)
    if key[0] == "JOINT":
        arm = bpy.data.objects.get(key[1])
        return arm.pose.bones.get(key[2]) if arm is not None and arm.pose is not None else None
    if key[0] == "SHAPES":
        return bpy.data.shape_keys.get(key[1])
    return None


def _in_scene(node):
    ob = node.id_data if isinstance(node, bpy.types.PoseBone) else node
    return not isinstance(ob, bpy.types.Object) or ob.name in bpy.context.scene.objects


def _pinned_nodes():
    out = []
    for key in dict.fromkeys(rid[0] for rid in _pinned):
        node = _node_of_key(key)
        if node is not None and _in_scene(node):
            out.append(node)
    return out


def is_pinned(node, fc):
    return (node_key(node), fc.data_path, fc.array_index) in _pinned


def filter_curves(node, curves, flt=None):
    """The node's curves (keyed and driver curves) the checked attribute filters list: none checked = all, several
    = their union (Maya); pinned curves always."""
    flt = attr_filters() if flt is None else flt
    if not flt:
        return list(curves)
    routed = _character_routed(node) if "anim_curve" in flt and not isinstance(node, bpy.types.KeyingSet) else ()
    return [fc for fc in curves if is_pinned(node, fc) or curve_kinds(node, fc, routed=routed) & flt]


def listed_nodes(context, space):
    """[(kind, node, curves)]: per listed object its own row (also without curves, a bare node row like Maya;
    its curves include its data-block's = Maya shape channels), its joints (with Only
    Show Selected only the selected ones, in any mode: Blender's Graph Editor draws no curves of unselected bones
    then, gui_step150_outliner), its blendShape node. A node's curves are its keyed and its driven
    (driver) channels: Maya lists a driven-key / expression channel too. A checked Show >
    Objects > Sets / Characters lists only those nodes: kit sets as rows without channels (a Maya set row has
    none), character sets (a character is a set) with their member channels; kit sets and characters can't be
    selected like Maya's, so every one is listed. A bookmark loaded from List > Bookmarks shows its set row first."""
    with one_pass():
        nodes = _memo_get(("listed", _list_key(space)), lambda: _listed_nodes(context, space))
        return [(kind, node, list(curves)) for kind, node, curves in nodes]


def _list_key(space):
    """What a pass keys an editor's list by: the editor, and its list state ``sync_space`` may change in the pass."""
    ds = _ds(space)
    coll = kit_list(space)
    ptr = getattr(space, "as_pointer", None)
    return (ptr() if ptr is not None else id(space), bool(getattr(ds, "show_only_selected", False)),
            coll.as_pointer() if coll is not None else 0,
            None if coll is None else (coll.get(LOADED) is None, bool(coll.get(AUTO, False))))


def _listed_nodes(context, space):
    from . import channel_box
    out = []
    flt = attr_filters()
    kinds = _object_kinds()
    if kinds & {"sets", "characters"}:
        from ..operators import character_sets
        for ks in character_sets.characters(context.scene):
            curves = filter_curves(ks, character_curves(context.scene, ks), flt)
            if curves:
                out.append(("CHARACTER", ks, curves))
    if "sets" in kinds:
        from ..operators import sets
        out += [("SET", coll, []) for coll in sets.all_sets()]
    else:
        from ..operators import graph_bookmarks
        bm = graph_bookmarks.loaded(context, space)
        if bm is not None:
            out.append(("SET", bm, []))      # the loaded bookmark's set row, its objects below (Maya)
    auto = auto_load(space)

    def add(kind, node, curves):
        curves = filter_curves(node, curves, flt)
        if curves:
            out.append((kind, node, curves))
    for ob in listed_objects(context, space):
        own, joints = split_object_curves(ob)
        start = len(out)
        add("OBJECT", ob, maya_order(own + node_drivers(ob)) + data_curves(ob))
        for pb, curves in joints:
            if auto and not channel_box.bone_selected(pb) or not _bone_loaded(space, pb):
                continue
            add("JOINT", pb, maya_order(curves + node_drivers(pb)))
        key = shape_key(ob)
        if key is not None:
            add("SHAPES", key, object_curves(key) + node_drivers(key))
        if len(out) == start and not flt and not joints:      # keyed joints: the joints are the Maya nodes
            out.append(("OBJECT", ob, []))     # Maya lists the node before it has keys (a bare node row)
    # pinned channels stay listed under their node whatever the list / selection is now, the node below the listed
    # ones (Maya Pin Channel)
    shown = {node_key(n) for _k, n, _c in out}
    for node in _pinned_nodes():
        if node_key(node) in shown:
            continue
        curves = [fc for fc in node_curves(node) if is_pinned(node, fc)]
        if curves:
            kind = "JOINT" if isinstance(node, bpy.types.PoseBone) else \
                "SHAPES" if isinstance(node, bpy.types.Key) else "OBJECT"
            out.append((kind, node, curves))
    return out


def rows(context, space):
    """[(kind, node, fcurve)] of the Maya list: a node row (OBJECT / JOINT / SHAPES / CHARACTER / SET), then its
    ATTR rows while expanded; under a driven-key ATTR row its Show Upstream Curves rows (UP_SDK, UP_CURVE)."""
    out = []
    flt = (space.dopesheet.filter_text or "").lower()
    up = shows_upstream(space)
    for kind, node, curves in listed_nodes(context, space):
        out.append((kind, node, None))
        if _expanded.get(node_key(node), True):
            for fc in curves:
                if flt and flt not in fc.data_path.lower() and flt not in attr_label(fc).lower():
                    continue
                out.append(("ATTR", node, fc))
                if up and is_driver(fc):
                    for kind2, ufc, label in upstream_rows(node, fc):
                        _up_label[(kind2, ufc.as_pointer())] = label
                        out.append((kind2, node, ufc))
            if kind == "OBJECT":         # the other selected animation layers' rows
                out += graph_layers.outliner_rows(context.scene, node)
    return out


ATTR_KINDS = ("ATTR", "UP_SDK", "UP_CURVE")      # channel rows (the rest are node rows)
_up_label = {}                                   # (row kind, fcurve pointer) -> upstream row label


def shows_upstream(space, flt=None):
    """Graph Editor List > Show Upstream Curves (on by default, like Maya): upstream rows show unless an attribute filter
    other than Driven by Driven Key is checked (Driven by Anim Curve hides them)."""
    flt = attr_filters() if flt is None else flt
    return (not _is_dope_space(space) and _wm_flag("allset_show_upstream")
            and (not flt or "driven_key" in flt))


def upstream_curves(context, space):
    """[(driver ID, its keyed curve)] the listed driven-key channels' upstream rows show (Blender must draw them)."""
    if not shows_upstream(space):
        return []
    with one_pass():
        return list(_memo_get(("upstream", _list_key(space)), lambda: _upstream_curves(context, space)))


def _sdk_drivers(owner):
    """Does the ID have a driver with the kit's SDK variable (an upstream row needs one)?"""
    from ..operators import driven_key
    ad = getattr(owner, "animation_data", None)
    return ad is not None and any(v.name == driven_key.VAR for fc in ad.drivers for v in fc.driver.variables)


def _upstream_curves(context, space):
    # the list's driver curves are its objects' (joints' included) and their shape keys' drivers: without an SDK
    # driver among them there is no upstream row, and the list need not be built
    owners = []
    for ob in listed_objects(context, space):
        owners += [ob, getattr(getattr(ob, "data", None), "shape_keys", None)]
    if not any(_memo_get(("sdk", o.as_pointer()), lambda o=o: _sdk_drivers(o)) for o in owners if o is not None):
        return []
    out = []
    for _kind, node, curves in listed_nodes(context, space):
        for fc in curves:
            if is_driver(fc):
                tgt = sdk_target(fc)
                for kind2, ufc, _label in upstream_rows(node, fc):
                    if kind2 == "UP_CURVE" and tgt is not None:
                        out.append((tgt[0], ufc))
    return out


def listed_curves(context, space):
    return [fc for _kind, _node, curves in listed_nodes(context, space) for fc in curves] + \
        [fc for _owner, fc in upstream_curves(context, space)]


# (WindowManager property, label, Maya annotation) of the Show / List check items
FLAGS = (
    ("allset_attr_hidden", "Hidden", "List only hidden attributes (Channel Box hidden channels)"),
    ("allset_attr_anim_curve", "Driven by Anim Curve", "List only keyed attributes"),
    ("allset_attr_expression", "Driven by Expression", "List only attributes driven by an expression (scripted "
     "driver)"),
    ("allset_attr_driven_key", "Driven by Driven Key", "List only attributes driven by a Set Driven Key"),
    ("allset_attr_user_defined", "User Defined", "List only user-defined attributes (custom properties)"),
    ("allset_show_ik_handles", "IkHandles", "List only IK handles"),
    ("allset_show_sets", "Sets", "List only the sets and character sets"),
    ("allset_show_upstream", "Show Upstream Curves", "Under a driven-key channel also list its driven key curve "
     "and the driver's own curve"),
    ("allset_hierarchy_below", "Hierarchy Below", "Also show the keys of the listed objects' children (the kit lists "
     "them as rows)"),
    ("allset_show_pins", "Show Pins", "Show or hide the pin buttons next to the outliner rows"),
)
# On by default, like Maya: Show Upstream Curves checked; View > Show Pins checked
FLAGS_ON = {"allset_show_upstream", "allset_show_pins"}
