# SPDX-License-Identifier: GPL-3.0-or-later
"""SHAPES and INPUTS: modifiers and kit deformers, constraint nodes and their target weights, blendShape targets,
which INPUTS nodes are expanded, and the Scene.allset_cb.rows list built from them.
Entry points: wanted_rows, rebuild_rows, row_for, row_owner, constraints, constraint_node_name, set_open.
Related: cb_values.py, cb_panel.py."""

import bpy

from ..operators import display
from . import cb_entry

from .cb_nodes import _drawing_lead, _generation, is_bone, lead
from .cb_pane import _scroll
from .cb_keys import BLEND_PREFIX, MAIN_BY_KEY, custom_keys, is_blend_key

from .. import update_summary


def blend_target(ob, key):
    """The shape key behind blendShape weight channel ``key`` on ``ob`` (None: ob has no target of that name)."""
    if not is_blend_key(key) or is_bone(ob):
        return None
    bs = blend_shape_key(ob)
    if bs is None:
        return None
    name = key[len(BLEND_PREFIX):]
    return next((kb for kb in blend_shape_targets(bs) if kb.name == name), None)


# --- rows for custom attributes, SHAPES and INPUTS --------------------------------

_driven = {}     # handle object pointer -> (generation, ((object, modifier name), ...))


def driven_modifiers(ob):
    """``deformers.driven_modifiers`` (every object's modifiers looked at) kept until the scene changes
    (``_generation``); each kept modifier is looked up on its object again and checked on use."""
    from ..operators import deformers
    if ob is None or getattr(ob, "type", None) not in deformers.HANDLE_TYPES:
        return []
    key = ob.as_pointer()
    got = _driven.get(key)
    if got is not None and got[0] == _generation[0]:
        out = []
        try:
            for owner, name in got[1]:
                md = owner.modifiers.get(name)
                if md is None or not deformers.drives(md, ob):
                    break
                out.append(md)
            else:
                return out
        except ReferenceError:
            pass
    mods = deformers.driven_modifiers(ob)
    if len(_driven) > 64:
        _driven.clear()
    _driven[key] = (_generation[0], tuple((md.id_data, md.name) for md in mods))
    return mods


def _inputs(ob):
    # + the kit deformers a lattice / handle drives: Maya shows ffd1 / bend1 in the INPUTS of ffd1Lattice /
    # bend1Handle
    from ..operators import deformers, skin_method, skin_tools_199, type_manip
    return [m for m in getattr(ob, "modifiers", ()) if not display.is_preview(m) and not deformers.is_base(m)
            and not skin_tools_199.is_part(m) and not skin_method.is_part(m) and not type_manip.is_part(m)] \
        + driven_modifiers(ob)


def _virtual(owner, name):
    """The Maya attribute behind an INPUTS row ``maya:<key>`` of a kit deformer (operators/deformers.ATTRS), or a
    SHAPES row of a light (Color R / G / B, operators/lights.channel_attrs), a camera (Film Aperture, F Stop,
    operators/film_fit.channel_attrs) or a locator (Local Position / Scale, operators/shape_attrs.locator_attrs)."""
    if not name.startswith("maya:"):
        return None
    if isinstance(owner, bpy.types.Object):
        from ..operators import shape_attrs
        return shape_attrs.locator_attr(name, owner)
    if isinstance(owner, bpy.types.Light):
        from ..operators import lights
        return lights.channel_attr(name, owner)
    if isinstance(owner, bpy.types.Camera):
        from ..operators import film_fit
        return film_fit.channel_attr(name)
    if not isinstance(owner, bpy.types.Modifier):
        return None
    from ..operators import deformers
    return deformers.attr(owner, name)


def input_label(mod, name):
    """Channel Box label of INPUTS row ``name`` of modifier ``mod`` (a Maya attribute, else the RNA name); a
    constraint's weight is named after its target (pCube1W0)."""
    if isinstance(mod, bpy.types.Constraint) and name == "influence":
        return weight_name(mod)
    v = _virtual(mod, name)
    if v is not None:
        return v.label
    rna = mod.bl_rna.properties.get(name)
    return rna.name if rna is not None else name


# Maya shape attribute labels of SHAPES rows (ffd1LatticeShape: S / T / U Divisions)
SHAPE_LABELS = {('LATTICE', "points_u"): "S Divisions", ('LATTICE', "points_w"): "T Divisions",
                ('LATTICE', "points_v"): "U Divisions", ('CAMERA', "display_size"): "Locator Scale"}


def shape_data(ob):
    """The struct holding the SHAPES rows of ``ob``: its object data, a locator's own object (Maya's locator shape
    has no Blender data), else None."""
    data = getattr(ob, "data", None)
    if data is not None:
        return data
    from ..operators import shape_attrs
    return ob if shape_attrs.is_locator(ob) else None


def shape_label(ob, prop):
    label = SHAPE_LABELS.get((ob.type, prop))
    data = shape_data(ob)
    v = _virtual(data, prop)
    if label is None and v is not None:
        label = v.label
    if label is None:
        rna = data.bl_rna.properties.get(prop)
        label = rna.name if rna is not None else prop
    return label


# --- INPUTS node expansion (#55) -------------------------------------------------------------------------
# Maya: every INPUTS node starts collapsed (polyCube1, polyExtrudeFace1), a click on
# its name shows its attributes under it and a second click hides them; a new lead shows every node collapsed again,
# also when the earlier lead comes back. This is UI state, not scene data: kept in Python (never
# Blender's ``Modifier.show_expanded``, which is the Properties editor's panel state, saved and undone), not undone,
# not saved.

_open = {"lead": None, "nodes": set(), "picked": None}


def lead_key(ob):
    if ob is None:
        return None
    if is_bone(ob):
        return ("BONE", ob.id_data.name, ob.name)
    return ("OB", ob.name)


def open_nodes(ob):
    """The expanded INPUTS node keys of lead ``ob`` (emptied when the lead changed, Maya's behaviour)."""
    key = lead_key(ob)
    if key != _open["lead"]:
        _open["lead"] = key
        _open["nodes"] = set()
        _open["picked"] = None
        _scroll.clear()
    return _open["nodes"]


def is_open(ob, node):
    return node in open_nodes(ob)


def set_open(ob, node, state=True):
    nodes = open_nodes(ob)
    if state:
        from ..operators import model_history
        if node.startswith('node:') and model_history.activate(ob, node[5:]) is not None:
            names = {history_node(rec.name) for rec in model_history.records(ob)}
            nodes.difference_update(names)
        nodes.add(node)
    else:
        nodes.discard(node)


def pick_node(ob, node, state=True):
    """The user clicked INPUTS node ``node`` open (``state``) or closed: the node the Show Manipulator Tool (T)
    shows for lead ``ob`` is the last one clicked open while it stays open, like picking an input node in Maya's
    Channel Box."""
    set_open(ob, node, state)
    if state:
        _open["picked"] = node
    elif _open.get("picked") == node:
        _open["picked"] = None


def picked_node(ob):
    """The INPUTS node key picked for lead ``ob`` (``pick_node``), or None. Reads only: another lead finds None."""
    if ob is None or lead_key(ob) != _open["lead"]:
        return None
    node = _open.get("picked")
    return node if node in _open["nodes"] else None


def mod_node(mod):
    return "mod:" + mod.name


def history_node(name):
    """A Maya history node drawn by the kit (creation node polyCube1, extrusion polyExtrudeFace1)."""
    return "node:" + name


def con_node(node, con):
    return "con:" + constraint_node_name(node, con)


def reset_open():
    _open["lead"] = None
    _open["nodes"] = set()
    _open["picked"] = None
    _scroll.clear()


# --- constraints = Maya constraint nodes ------------------------------------------------
# Maya names them like pCube1_parentConstraint1, weight locator1W0.

MAYA_CONSTRAINT = {'CHILD_OF': "parentConstraint", 'COPY_TRANSFORMS': "parentConstraint",
                   'COPY_LOCATION': "pointConstraint", 'COPY_ROTATION': "orientConstraint",
                   'COPY_SCALE': "scaleConstraint", 'TRACK_TO': "aimConstraint",
                   'DAMPED_TRACK': "aimConstraint", 'LOCKED_TRACK': "aimConstraint"}
_AIM = ('TRACK_TO', 'DAMPED_TRACK', 'LOCKED_TRACK')


def constraints(node):
    """Constraints shown as INPUTS nodes (Limit constraints are Maya transform limits: AE only)."""
    from ..operators import constrain_interp, ik_rp, rig_tools, skin_follow
    # a group blend / Object up turn is part of its Maya node; the kit's 3+ bone RP solve belongs
    # to the IK handle; a skin's follow of its skeleton is part of the skin
    return [c for c in getattr(node, "constraints", ()) if not c.type.startswith("LIMIT_")
            and not constrain_interp.is_blend(c) and not rig_tools.is_up_companion(c)
            and not ik_rp.is_solver_constraint(c) and not skin_follow.is_follow(c)]


def constraint_enabled(con):
    en = getattr(con, "enabled", None)
    return (not con.mute) if en is None else bool(en)


def _nth_constraint(node, con):
    return [c for c in constraints(node) if c.type == con.type].index(con)


def maya_constraint_type(con, default=None):
    """Maya node type of a kit constraint: normal / tangent constraints are a Track To on a helper (
    operators/constrain_modify.maya_type), UV / Proximity Pins a Copy Transforms on a helper (
    operators/pin_update.pin_type), a kit multi-target group its own type (a parent group's Copy Location / Rotation,
    operators/constrain_multi.py), the rest by Blender type."""
    from ..operators import constrain_multi
    grouped = constrain_multi.group_type(con)
    if grouped is not None:
        return grouped
    if con.type == 'COPY_TRANSFORMS':
        from ..operators import pins_205
        kind = pins_205.pin_type(con)
        if kind is not None:
            return kind
    if con.type in _AIM:
        from ..operators import constrain_199
        kind = constrain_199.maya_type(con)
        if kind in ("normal", "tangent"):
            return f"{kind}Constraint"
    return MAYA_CONSTRAINT.get(con.type, default)


def constraint_node_name(node, con):
    """Maya's name for the constraint node: ``<node>_<type><n>`` (pCube1_parentConstraint1)."""
    from ..operators import constrain_multi
    con = constrain_multi.head_of(con, node)     # a hidden blend / Object up turn = its node
    mtype = maya_constraint_type(con)
    if mtype is None:
        return con.name
    from ..operators import pins_205
    pin = pins_205.node_name(con)          # a pin node keeps its own name (uvPin1)
    if pin is not None:
        return pin
    from ..operators import constrain_multi
    # a multi-target group is one Maya node: count group heads, name every member like its head
    head = constrain_multi.head_of(con, node)
    same = [c for c in constraints(node) if constrain_multi.is_head(c, node) and maya_constraint_type(c) == mtype]
    return f"{node.name}_{mtype}{same.index(head) + 1}"


def weight_name(con):
    """Maya target weight attribute: ``<target>W0`` (one target per Blender constraint; normal / tangent
    constraints name their surface / curve; a member of a kit multi-target group = ``<target>W<i>``)."""
    from ..operators import constrain_199, constrain_multi, pins_205
    mb = constrain_multi.member(con)
    if mb is not None:
        return f"{mb.label}W{mb.index}"
    geometry = pins_205.geometry_of(con)   # UV / Proximity Pin: the pinned-to geometry
    if geometry is not None:
        return f"{geometry.name}W0"
    surface, _sub = constrain_199.maya_target(con)
    if surface is not None and surface is not getattr(con, "target", None):
        return f"{surface.name}W0"
    target = getattr(con, "target", None)
    if target is None:
        return "W0"
    sub = getattr(con, "subtarget", "")
    return f"{sub if target.type == 'ARMATURE' and sub else target.name}W0"


def _axes(con, pattern):
    return [a for a in "xyz" if getattr(con, pattern.format(a), True)]


def constrained_keys(node):
    """Channel keys an enabled constraint drives (Maya draws them blue)."""
    out = set()
    for con in constraints(node):
        if not constraint_enabled(con):
            continue
        t = con.type
        if t == 'CHILD_OF':
            for k, pattern in (("t", "use_location_{}"), ("r", "use_rotation_{}"), ("s", "use_scale_{}")):
                out.update(k + a for a in _axes(con, pattern))
        elif t in ('COPY_TRANSFORMS', 'ARMATURE'):
            out.update(k for k in MAIN_BY_KEY if k != "v")
        elif t == 'COPY_LOCATION':
            out.update("t" + a for a in _axes(con, "use_{}"))
        elif t == 'COPY_ROTATION':
            out.update("r" + a for a in _axes(con, "use_{}"))
        elif t == 'COPY_SCALE':
            out.update("s" + a for a in _axes(con, "use_{}"))
        elif t in _AIM:
            out.update(("rx", "ry", "rz"))
    return out


def _nth_of_type(ob, mod):
    return [m for m in _inputs(ob) if m.type == mod.type].index(mod)


def row_owner(ob, kind, name, mod_type="", nth=0, lead_ob=None):
    """The struct holding row ``name`` on ``ob`` (None: ob has no such channel).

    Same-named channel: custom = same property name,
    SHAPE = same object type and data property, INPUT = same modifier type at the same
    position among that type."""
    if kind == "CUSTOM":
        return ob if name in ob.keys() else None
    if kind == "BLEND":
        return blend_target(ob, BLEND_PREFIX + name)
    if kind == "SHAPE":
        data = shape_data(ob)
        if data is None or (lead_ob is not None and ob.type != lead_ob.type):
            return None
        return data if name in data.bl_rna.properties or _virtual(data, name) is not None else None
    if kind == "INPUT":
        mods = [m for m in _inputs(ob) if m.type == mod_type]
        if nth < len(mods) and (name in mods[nth].bl_rna.properties or _virtual(mods[nth], name) is not None):
            return mods[nth]
    if kind == "CONSTRAINT":
        cons = [c for c in constraints(ob) if c.type == mod_type]
        if nth < len(cons) and name in cons[nth].bl_rna.properties:
            return cons[nth]
    return None


def _row_kind(owner, kind, name):
    if kind == "CUSTOM":
        return cb_entry.kind_of_value(owner.get(name))
    if kind == "BLEND":
        return "NONE"
    v = _virtual(owner, name)
    if v is not None:
        return v.kind
    return cb_entry.kind_of_rna(owner.bl_rna.properties[name])


def _row_read(owner, kind, name):
    if kind == "CUSTOM":
        return owner[name]
    if kind == "BLEND":
        return owner.value
    v = _virtual(owner, name)
    return v.get(owner) if v is not None else getattr(owner, name)


def _row_write(owner, kind, name, value):
    if kind == "CUSTOM":
        owner[name] = type(owner[name])(value)
        return
    if kind == "BLEND":
        owner.value = value
        return
    v = _virtual(owner, name)
    if v is not None:
        v.set(owner, value)
    else:
        setattr(owner, name, value)


def _modifier_props(mod, limit=10):
    """Editable scalar properties of a modifier, Maya INPUTS-style; a kit Maya deformer shows
    its Maya attributes instead (``maya:<key>`` rows, operators/deformers.ATTRS)."""
    from ..operators import deformers
    maya = deformers.attrs(mod)
    if maya is not None:
        return [deformers.PREFIX + a.key for a in maya]
    skip ={"name", "show_expanded", "show_on_cage", "show_in_editmode", "show_render",
            "use_apply_on_spline", "use_pin_to_last", "is_override_data_editable",
            "persistent_uid", "execution_time", "show_viewport"}
    out = []
    for p in mod.bl_rna.properties:
        ident = p.identifier
        if (ident in skip or p.is_readonly or ident.startswith(("show_", "open_", "is_"))
                or ident.endswith("_panel")):
            continue
        if p.type in {'INT', 'FLOAT', 'BOOLEAN'} and getattr(p, "array_length", 0) == 0:
            out.append(p.identifier)
        if len(out) >= limit:
            break
    return out


SHAPE_PROPS = {
    # Maya camera shape channels in Maya's order; Lens Squeeze Ratio, Shutter Angle and Center Of Interest are kept by
    # the kit (operators/shape_attrs.py)
    'CAMERA': ("maya:horizontalFilmAperture", "maya:verticalFilmAperture", "lens", "allset_lens_squeeze_ratio",
               "maya:fStop", "maya:focusDistance", "allset_shutter_angle", "allset_center_of_interest",
               "display_size"),
    # Maya light shapes in Maya's order: Color R / G / B, then Blender's Power (a sun: Strength) where Maya has
    # Intensity (operators/lights.py), Use Ray Trace Shadows (Blender's shadow switch), Shad Color R / G / B, Use Depth
    # Map Shadows and Dmap Bias (kept by the kit), spot Cone Angle / Penumbra Angle and the kept Dropoff. A light type
    # without a row's property (Cone Angle and the rows after it on a non-spot light) skips that row.
    'LIGHT': ("maya:colorR", "maya:colorG", "maya:colorB", "energy", "maya:useRayTraceShadows",
              "maya:shadColorR", "maya:shadColorG", "maya:shadColorB", "allset_use_depth_map_shadows",
              "allset_dmap_bias", "maya:coneAngle", "maya:penumbraAngle", "allset_dropoff"),
    'LATTICE': ("points_u", "points_w", "points_v"),     # Maya S / T / U Divisions (Maya Y = Blender Z)
    # a locator (operators/shape_attrs.locator_attrs); other empties have no SHAPES rows (shape_data)
    'EMPTY': ("maya:localPositionX", "maya:localPositionY", "maya:localPositionZ",
              "maya:localScaleX", "maya:localScaleY", "maya:localScaleZ"),
}


def wanted_rows(ob):
    """(kind, name, mod_type, nth) for every text row of the lead object."""
    out = [("CUSTOM", name, "", 0) for name in custom_keys(ob)]
    data = shape_data(ob)
    if data is not None:
        for prop in SHAPE_PROPS.get(ob.type, ()):
            rna = data.bl_rna.properties.get(prop)
            if (rna is not None and cb_entry.kind_of_rna(rna)) or _virtual(data, prop) is not None:
                out.append(("SHAPE", prop, "", 0))
    for mod in _inputs(ob):
        if is_open(ob, mod_node(mod)):
            for prop in _modifier_props(mod):
                out.append(("INPUT", prop, mod.type, _nth_of_type(ob, mod)))
    bs = blend_shape_key(ob)
    if bs is not None and is_open(ob, blend_shape_node(bs)):
        out += [("BLEND", kb.name, "", 0) for kb in blend_shape_targets(bs)]
    from ..operators import constrain_multi
    for con in constraints(ob):
        if not is_open(ob, con_node(ob, con)):
            continue
        mb = constrain_multi.member(con, ob)
        if mb is None:
            out.append(("CONSTRAINT", "influence", con.type, _nth_constraint(ob, con)))
        elif constrain_multi.is_head(con, ob):
            # Maya weights <target>W0, W1 ... = the owner's weight ID properties, typed like custom rows
            out += [("CUSTOM", prop, "", 0) for prop, _label in constrain_multi.weights(ob, mb.group)
                    if prop in ob.keys()]
    return out


_drawing_sigs = {}     # object / bone pointer -> rows_signature while the Channel Box draws (``body``)


def rows_signature(ob):
    """What the lead's text rows are made from. While the Channel Box draws it is found once per object: every
    custom attribute row asks for it (a control with 30 attributes asked 30 times per redraw)."""
    if ob is None:
        return ""
    if _drawing_lead:
        key = ob.as_pointer()
        sig = _drawing_sigs.get(key)
        if sig is None:
            sig = _drawing_sigs[key] = _rows_signature(ob)
        return sig
    return _rows_signature(ob)


def _rows_signature(ob):
    cons = [(c.name, c.type, weight_name(c)) for c in constraints(ob)]
    opened = sorted(open_nodes(ob))
    if is_bone(ob):
        return repr(("BONE", ob.id_data.name, ob.name, custom_keys(ob), cons, opened))
    mods = [(m.name, m.type) for m in _inputs(ob)]
    bs = blend_shape_key(ob)
    targets_ = [kb.name for kb in blend_shape_targets(bs)] if bs is not None else []
    return repr((ob.name, ob.type, custom_keys(ob), mods, cons, opened, targets_))


_rows_state = {"busy": False}


def rebuild_rows(context=None):
    """Make ``Scene.allset_cb.rows`` match the lead object (only when it changed)."""
    context = context or bpy.context
    scene = getattr(context, "scene", None)
    cb = getattr(scene, "allset_cb", None) if scene is not None else None
    view_layer = getattr(context, "view_layer", None)
    if cb is None or view_layer is None or _rows_state["busy"]:
        return False
    ob = lead(context)
    sig = rows_signature(ob)
    if cb.rows_sig == sig:
        return False
    update_summary.wrote()
    _rows_state["busy"] = True
    try:
        cb.rows.clear()
        if ob is not None:
            for kind, name, mod_type, nth in wanted_rows(ob):
                r = cb.rows.add()
                r.kind, r.name, r.mod_type, r.nth = kind, name, mod_type, nth
        cb.rows_sig = sig
    finally:
        _rows_state["busy"] = False
    return True


def row_for(context, ob, kind, name, mod_type="", nth=0):
    """The text row to draw, or None when the rows are stale (then draw the real property)."""
    cb = context.scene.allset_cb
    if cb.rows_sig != rows_signature(ob):
        return None
    for r in cb.rows:
        if r.kind == kind and r.name == name and r.mod_type == mod_type and r.nth == nth:
            return r
    return None


def blend_shape_key(ob):
    """The mesh's shape keys = its Maya blendShape node (named blendShapeN, as in the Shape Editor), or None."""
    if not isinstance(ob, bpy.types.Object) or ob.type != 'MESH':
        return None
    key = ob.data.shape_keys
    return key if key is not None and len(key.key_blocks) else None


def blend_shape_node(key):
    return "bs:" + key.name


def blend_shape_targets(key):
    """The key blocks Maya lists as targets: every block after the Basis but the kit's hidden in-between keys."""
    from ..operators import blend_shapes_227
    hidden = blend_shapes_227.helper_names(key)
    return [kb for i, kb in enumerate(key.key_blocks) if i and kb.name not in hidden]
