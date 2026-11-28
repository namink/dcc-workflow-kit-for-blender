# SPDX-License-Identifier: GPL-3.0-or-later
"""Attribute membership of animation layers like Maya's: which channels and joints of a member are in a layer
(``is_member``, ``member_keys``, ``member_bones``), Add to / Remove From Selected Layers (``add_attrs``,
``remove_attrs``), the layer a key goes to (``target_layer``) and the BaseAnimation curves the Channel Box and
Time Slider read (``base_curve``, ``member_of_layer``, ``hidden_base_curves``). Built on anim_layer_tracks.
"""

import bpy

from .. import compat
from .anim_layer_tracks import (add_object, BASE, display_layer, _fcurve, layer_curves, remove_object, selected, _slot,
                                _strip, tracks)


def base_curve(ob, path, index):
    """``ob``'s BaseAnimation curve of one channel (None without layers or curve)."""
    tr = tracks(ob).get(BASE)
    return None if tr is None else _fcurve(_strip(tr).action, path, max(index, 0))


def member_of_layer(ob, path, index):
    """The channel is in a layer above BaseAnimation (Maya draws it teal in the Channel Box)."""
    return any(name != BASE and is_member(ob, name, path, index) for name in tracks(ob))


def hidden_base_curves(ob, scene):
    """BaseAnimation curves the display layer doesn't show: channels that are not in that layer still show their
    base keys in Maya's Time Slider."""
    layer = display_layer(scene, ob)
    if layer == BASE or BASE not in tracks(ob):
        return []
    return [fc for fc in layer_curves(ob, BASE) if not is_member(ob, layer, fc.data_path, fc.array_index)]


# --- attribute membership ---------------------------------------
# Maya layer members are attributes (animLayer -attribute): Channel Box > Channels > Add to / Remove From Selected
# Layers edits them, a key on a non-member attribute goes to BaseAnimation, removing a keyed attribute deletes its
# layer curve. The kit's members are objects (one NLA track each, Add Selected Objects = every attribute); an object's
# attribute list is kept in the object ID property ATTRS {layer: "tx,ry,..."} only once Add / Remove edited it.
ATTRS = "allset_layer_attrs"


def _attr_record(ob):
    raw = ob.get(ATTRS)
    return {str(k): [x for x in str(v).split(",") if x] for k, v in raw.items()} if raw else {}


def _set_attr_record(ob, layer, keys):
    d = _attr_record(ob)
    if keys is None:
        d.pop(layer, None)
    else:
        d[layer] = list(dict.fromkeys(keys))
    if d:
        ob[ATTRS] = {k: ",".join(v) for k, v in d.items()}
    elif ATTRS in ob:
        del ob[ATTRS]


def channel_key(path, index):
    if path.startswith('key_blocks["') and path.endswith('"].value'):
        from ..ui import channel_box as cb       # a blendShape weight on the Key datablock
        return cb.BLEND_PREFIX + bpy.utils.unescape_identifier(path[12:-8])
    from . import character_sets
    return character_sets.channel_key_of(path, index)


BONE = "bone:"           # a joint member of a layer (Maya adds the joint node), "bone:<bone name>"


def bone_of(path):
    """The bone name of a ``pose.bones["<name>"]...`` path, else None."""
    if not path.startswith('pose.bones["'):
        return None
    end = path.find('"]', 12)
    return bpy.utils.unescape_identifier(path[12:end]) if end > 0 else None


def bone_path(pb, prop):
    return f'pose.bones["{bpy.utils.escape_identifier(pb.name)}"].{prop}'


def is_member(ob, layer, path=None, index=-1):
    """``ob``'s channel (``path``, ``index``) is in ``layer`` (no path: the object is a member at all). A joint
    channel is a member when its bone is (Maya Add Selected Objects on joints)."""
    if layer == BASE:
        return True
    if layer not in tracks(ob):
        return False
    rec = _attr_record(ob).get(layer)
    if rec is None or path is None:
        return True
    bone = bone_of(path)
    if bone is not None:
        return BONE + bone in rec
    return channel_key(path, index) in rec


def member_bones(ob, layer):
    """Joints of the armature ``ob`` in ``layer`` (all of them when the whole object is a member)."""
    if layer not in tracks(ob) or ob.type != 'ARMATURE':
        return []
    rec = _attr_record(ob).get(layer)
    if rec is None:
        return [pb.name for pb in ob.pose.bones]
    return [k[len(BONE):] for k in rec if k.startswith(BONE)]


def member_keys(ob, layer):
    """Channel Box keys of ``ob`` in ``layer`` (all keyable shown channels when no list was edited)."""
    rec = _attr_record(ob).get(layer)
    if rec is not None:
        return list(rec)
    from ..ui import channel_box as cb
    if isinstance(ob, bpy.types.Key):          # a whole blendShape node: every target weight
        return [cb.BLEND_PREFIX + kb.name for kb in ob.key_blocks[1:]] if layer in tracks(ob) else []
    return [k for k in cb._visible_channels(ob) if cb.is_keyable(ob, k)] if layer in tracks(ob) else []


def add_attrs(scene, ob, layer, keys):
    """Maya Add to Selected Layers: the object joins ``layer`` with only these attributes, or gains them."""
    new = layer not in tracks(ob)
    if new:
        add_object(scene, ob, layer)
        _set_attr_record(ob, layer, keys)
    elif layer in _attr_record(ob):
        _set_attr_record(ob, layer, _attr_record(ob)[layer] + list(keys))


def remove_attrs(scene, ob, layer, keys):
    """Maya Remove From Selected Layers: the attributes leave ``layer`` and their layer curves are deleted; an object
    left without attributes leaves the layer."""
    if layer == BASE or layer not in tracks(ob):
        return
    left = [k for k in member_keys(ob, layer) if k not in keys]
    act = _strip(tracks(ob)[layer]).action
    from ..ui import channel_box as cb
    for k in keys:
        if k.startswith(BONE):         # a joint leaves: all its layer curves go
            fcs = [fc for fc in compat.action_fcurves(act, _slot(act)) if bone_of(fc.data_path) == k[len(BONE):]]
        else:
            path, idx, _kind = cb.channel_path(k)
            fcs = [_fcurve(act, path, max(idx, 0))]
        for fc in fcs:
            if fc is None:
                continue
            for owner in compat.fcurve_owners(act):
                if any(f == fc for f in owner.fcurves):
                    owner.fcurves.remove(fc)
                    break
    if left:
        _set_attr_record(ob, layer, left)
    else:
        _set_attr_record(ob, layer, None)
        remove_object(scene, ob, layer)
    ob.update_tag(refresh={'TIME'})


def target_layer(scene, ob, path=None, index=-1):
    """The layer a key on ``ob`` goes to: the selected layer when the object (and with ``path`` that channel) is in
    it, else BaseAnimation (Maya: a non-member attribute is keyed on BaseAnimation)."""
    e = selected(scene)
    name = e.name if e is not None else BASE
    return name if is_member(ob, name, path, index) else BASE
