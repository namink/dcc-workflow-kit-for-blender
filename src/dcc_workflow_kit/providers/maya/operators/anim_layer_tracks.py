# SPDX-License-Identifier: GPL-3.0-or-later
"""Animation layers as NLA tracks: the scene's layer list (``layers``, ``selected``, ``selected_layers``), one track
per layer on every member with its strip and action (``tracks``, ``add_object``, ``remove_object``,
``order_tracks``), the keyed layer weight, and ``sync`` / ``show`` (write the list onto the tracks, make the display
layer the active action). Base of anim_layer_members and anim_layer_keys; the operators are in anim_layers.
"""

import bpy

from .. import compat


BASE = "BaseAnimation"
MARK = "allset_anim_layer"
WIDE = (-1000.0, 1000.0)          # strip / action range: keys outside it are not evaluated
SCALE_PATHS = {"scale", "delta_scale"}


def _leaf(path):
    """The property name of a data path (``pose.bones["j"].scale`` -> ``scale``)."""
    return path.rsplit(".", 1)[-1] if "." in path else path


def is_scale(path):
    return _leaf(path) in SCALE_PATHS


# --- scene model -----------------------------------------------------------------------------------

def layers(scene):
    return scene.allset_anim_layers


def ensure_list(scene):
    """The layer list with BaseAnimation as first entry."""
    ls = layers(scene)
    if not len(ls) or ls[0].name != BASE:
        e = ls.add()
        e.name = BASE
        ls.move(len(ls) - 1, 0)
    return ls


def selected(scene):
    ls = layers(scene)
    i = scene.allset_anim_layer_index
    return ls[i] if 0 <= i < len(ls) else (ls[0] if len(ls) else None)


def selected_layers(scene):
    """Maya's selected layers (Layer Editor Ctrl / Shift click), list order: the ``picked`` entries while
    they include the last picked one (``allset_anim_layer_index``), else only that one (any direct index write is a
    plain single selection)."""
    cur = selected(scene)
    if cur is None:
        return []
    if not cur.picked:
        return [cur]
    return [e for e in layers(scene) if e.picked]


# --- per object tracks -------------------------------------------------------------------------------

def layer_ids(scene):
    """Every datablock that can carry layer tracks: the scene's objects, then their shape-key (blendShape) Keys."""
    out, keys = [], []
    for ob in scene.objects:
        out.append(ob)
        key = getattr(getattr(ob, "data", None), "shape_keys", None)
        if key is not None and key not in keys:
            keys.append(key)
    return out + keys


def blend_node(ob):
    """The Key datablock (Maya blendShape node) holding ``ob``'s shape key weights, or None."""
    key = getattr(getattr(ob, "data", None), "shape_keys", None)
    return key if isinstance(key, bpy.types.Key) else None


def tracks(ob):
    ad = ob.animation_data
    if ad is None:
        return {}
    return {tr.name: tr for tr in ad.nla_tracks if tr.strips and tr.strips[0].action is not None
            and tr.strips[0].action.get(MARK) == tr.name}


def has_layers(ob):
    return bool(tracks(ob))


def _new_action(ob, layer):
    """An empty action with a slot for ``ob`` (Blender 4.4+ makes the slot when the action is assigned)."""
    act = bpy.data.actions.new(f"{layer}_{ob.name}")
    act[MARK] = layer
    ob.animation_data_create()
    slots = getattr(act, "slots", None)
    if slots is not None:       # 4.4+: an empty action gets no slot by being assigned; make it (the strip needs it)
        slot = slots.new(id_type='KEY' if isinstance(ob, bpy.types.Key) else 'OBJECT', name=ob.name)
        act["allset_slot"] = slot.identifier
    return act


def _slot(act):
    ident = act.get("allset_slot")
    slots = getattr(act, "slots", None)
    if slots is None:
        return None
    if ident and ident in slots:
        return slots[ident]
    return slots[0] if len(slots) else None


def _strip(tr):
    return tr.strips[0]


def _add_track(ob, layer, act):
    ad = ob.animation_data_create()
    tr = ad.nla_tracks.new()
    tr.name = layer
    st = tr.strips.new(layer, int(WIDE[0]), act)
    sl = _slot(act)
    if sl is not None and hasattr(st, "action_slot"):
        st.action_slot = sl
    st.action_frame_start, st.action_frame_end = WIDE
    st.frame_start, st.frame_end = WIDE
    st.use_auto_blend = False
    st.blend_in = st.blend_out = 0.0
    st.extrapolation = 'HOLD' if layer == BASE else 'HOLD_FORWARD'
    return tr


def ensure_base(ob):
    """Move the object's own animation (its active action) onto the BaseAnimation track."""
    if BASE in tracks(ob):
        return tracks(ob)[BASE]
    ad = ob.animation_data_create()
    act = ad.action
    if act is not None:
        slot = getattr(ad, "action_slot", None)
        act[MARK] = BASE
        if slot is not None:
            act["allset_slot"] = slot.identifier
        ad.action = None
    else:
        act = _new_action(ob, BASE)
    tr = _add_track(ob, BASE, act)
    order_tracks(ob, [e.name for e in layers(bpy.context.scene)] or [BASE])
    return tr


def add_object(scene, ob, layer):
    """Make ``ob`` a member of ``layer`` (Maya Add Selected Objects / Create Layer from Selected)."""
    ensure_list(scene)
    ensure_base(ob)
    if layer != BASE and layer not in tracks(ob):
        _add_track(ob, layer, _new_action(ob, layer))
    order_tracks(ob, [e.name for e in layers(scene)])
    sync(scene)


def remove_object(scene, ob, layer):
    tr = tracks(ob).get(layer)
    if tr is None or layer == BASE:
        return
    act = _strip(tr).action
    ad = ob.animation_data
    if ad.action is not None and ad.action == act:      # shown as the active action
        ad.action = None
    ad.nla_tracks.remove(tr)
    if act is not None and act.users == 0:
        bpy.data.actions.remove(act)


def order_tracks(ob, names, force=False):
    """NLA tracks in the layer list order, bottom first (Blender can only move tracks by recreating them, so only the
    kit tracks' strip settings are swapped into place: track i gets layer names[i]). The layer tracks are re-added on
    top, so other tracks (Trax clip tracks, operators/trax_clips.py) stay below them; ``force`` re-adds them even
    when the order is right (a clip track was just added on top)."""
    have = tracks(ob)
    want = [n for n in names if n in have]
    ad = ob.animation_data
    kit = [tr for tr in ad.nla_tracks if tr.name in have]
    if [tr.name for tr in kit] == want and not force:
        return
    data = {n: (_strip(have[n]).action, have[n].mute, strip_state(_strip(have[n]))) for n in want}
    for tr in kit:
        ad.nla_tracks.remove(tr)
    for n in want:
        tr = _add_track(ob, n, data[n][0])
        tr.mute = data[n][1]
        restore_strip_state(_strip(tr), data[n][2])      # a keyed weight survives the rebuild


def strip_state(st):
    """(animated?, influence, influence keys) of a layer strip: Maya's layer weight and its keys."""
    keys = []
    fc = st.fcurves.find("influence") if st.use_animated_influence else None
    if fc is not None:
        keys = [(tuple(kp.co), tuple(kp.handle_left), tuple(kp.handle_right), kp.interpolation,
                 kp.handle_left_type, kp.handle_right_type) for kp in fc.keyframe_points]
    return st.use_animated_influence, st.influence, keys


def restore_strip_state(st, state):
    animated, influence, keys = state
    if not animated:
        return
    fc = weight_curve(st)
    if fc is None:
        return
    fc.keyframe_points.clear()
    for co, hl, hr, interp, tl, tr in keys:
        kp = fc.keyframe_points.insert(co[0], co[1], options={'FAST'})
        kp.interpolation = interp
        kp.handle_left_type, kp.handle_right_type = tl, tr
        kp.handle_left, kp.handle_right = hl, hr
    fc.update()
    st.influence = influence


def weight_curve(st):
    """The strip's influence F-curve (Maya's keyed layer weight), made without Blender's automatic first key."""
    if not st.use_animated_influence:
        keep = st.influence
        st.use_animated_influence = True      # Blender keys influence when it turns this on: drop that key
        fc = st.fcurves.find("influence")
        if fc is not None:
            fc.keyframe_points.clear()
        st.influence = keep
    return st.fcurves.find("influence")


def _evaluate(fc, frame):
    return fc.evaluate(frame)


def strip_weight(st, frame, ev=None):
    """The strip's weight at ``frame`` (its influence curve when keyed). ``ev(fc, frame)`` evaluates a curve
    (default: its own value; Enable Stepped Preview passes the stepped one)."""
    if not st.use_animated_influence:
        return 1.0
    fc = st.fcurves.find("influence")
    if fc is not None and len(fc.keyframe_points):
        return (ev or _evaluate)(fc, frame)
    return st.influence


def members(scene, layer):
    return [ob for ob in layer_ids(scene) if layer in tracks(ob)]


def sync(scene):
    """Write the layer list onto every member object's tracks (Maya weight / mute / solo / mode)."""
    ls = layers(scene)
    if not len(ls):
        return
    solo = {e.name for e in ls if e.solo and e.name != BASE}
    info = {e.name: e for e in ls}
    for ob in layer_ids(scene):
        have = tracks(ob)
        if not have:
            continue
        for name, tr in have.items():
            e = info.get(name)
            if e is None:
                continue
            st = _strip(tr)
            tr.mute = e.mute or (bool(solo) and name != BASE and name not in solo)
            st.blend_type = 'REPLACE' if name == BASE or e.override else 'COMBINE'
            st.extrapolation = 'HOLD' if name == BASE else 'HOLD_FORWARD'
            _set_influence(st, 1.0 if name == BASE else e.weight)
            tr.lock = e.lock
        ob.update_tag(refresh={'TIME'})
    show(scene)


def display_layer(scene, ob):
    """The layer whose keys ``ob`` shows: the selected layer when the object is in it, else BaseAnimation."""
    e = selected(scene)
    name = e.name if e is not None else BASE
    have = tracks(ob)
    if name in have:
        return name
    for x in reversed(selected_layers(scene)):     # another selected layer the object is in (top first)
        if x.name in have:
            return x.name
    return BASE


def show(scene):
    """Make every layered object's active action its display layer's strip action at influence 0 (anim_layers.py module docstring):
    Graph Editor / Dope Sheet / key readers then show that layer, the evaluated result stays the NLA's."""
    for ob in layer_ids(scene):
        have = tracks(ob)
        if not have:
            continue
        ad = ob.animation_data
        tr = have.get(display_layer(scene, ob)) or have.get(BASE) or next(iter(have.values()))
        act = _strip(tr).action
        if ad.action != act:
            ad.action = act
            sl = _slot(act)
            if sl is not None and hasattr(ad, "action_slot"):
                ad.action_slot = sl
        if ad.action_influence != 0.0:
            ad.action_influence = 0.0      # the strip already plays it: shown, not applied twice


def show_base(ob):
    """Make BaseAnimation ``ob``'s active action (influence 0) — what a bake writes into."""
    tr = tracks(ob).get(BASE)
    if tr is None:
        return
    ad = ob.animation_data
    act = _strip(tr).action
    if ad.action != act:
        ad.action = act
        sl = _slot(act)
        if sl is not None and hasattr(ad, "action_slot"):
            ad.action_slot = sl
    ad.action_influence = 0.0


def _set_influence(st, w):
    if abs(w - 1.0) < 1e-9 and not st.use_animated_influence:
        return
    if not st.use_animated_influence:
        st.use_animated_influence = True      # Blender keys influence when it turns this on: drop that key
        fc = st.fcurves.find("influence")
        if fc is not None:
            while fc.keyframe_points:
                fc.keyframe_points.remove(fc.keyframe_points[0])
    st.influence = w


def _fcurve(act, path, index):
    for fc in compat.action_fcurves(act, _slot(act)):
        if fc.data_path == path and fc.array_index == index:
            return fc
    return None


def layer_curves(ob, layer):
    """F-curves of ``ob`` on ``layer``."""
    tr = tracks(ob).get(layer)
    if tr is None:
        return []
    act = _strip(tr).action
    return list(compat.action_fcurves(act, _slot(act))) if act is not None else []
