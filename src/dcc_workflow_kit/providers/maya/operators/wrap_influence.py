# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Deform > Wrap > Add / Remove Influence: every extra influence of a wrap node is one more Surface Deform
``wrap1Influence<k>`` (with its Base hook) and each wrapped point moves to the vertex group of its nearest
influence; removing the last influence removes the wrap node. Entry points ``wrap_influence``,
``add_wrap_influence``, ``remove_wrap_influence`` and ``allset.wrap_influence``; the wrap node is made in deformers.py.
"""

import math

import bpy
from bpy.props import EnumProperty

from .. import i18n, results, undo_steps
from . import deformers

MSG_WRAP_SELECT = "Select at least one surface (or wrap node) and one influence object."
MSG_WRAP_INFLUENCE = "Influence objects must be polygon meshes, NURBS curves or NURBS surfaces."
MSG_NO_WRAP = "No wrap deformer is associated with surface {0}."


# --- wrap influences --------------------------------------------------------------------------------------------

def _influence_parts(ob, md):
    """[(Surface Deform modifier, its Base hook or None)] of wrap node ``md`` on ``ob``: md first, then the kit's
    extra influences ``<md>Influence<k>`` in stack order."""
    out = [(md, ob.modifiers.get(f"{md.name}Base"))]
    for m in ob.modifiers:
        if m.type == 'SURFACE_DEFORM' and m.name.startswith(f"{md.name}Influence") \
                and m.name[len(md.name) + 9:].isdigit():
            out.append((m, ob.modifiers.get(f"{m.name}Base")))
    return out


def _wraps(ob):
    return [m for m in ob.modifiers if deformers.base_of(m) == "wrap"]


def _weights(ob, group):
    vg = ob.vertex_groups.get(group) if group else None
    if vg is None:
        return {}
    out = {}
    for v in ob.data.vertices:
        for g in v.groups:
            if g.group == vg.index and g.weight > 0.0:
                out[v.index] = g.weight
    return out


def _distances(ob, idx, infl, depsgraph):
    """Distance from each rest point ``idx`` of ``ob`` (world) to the evaluated surface of ``infl`` (world)."""
    from mathutils.bvhtree import BVHTree
    ev = infl.evaluated_get(depsgraph)
    bvh = BVHTree.FromObject(ev, depsgraph)
    inv = ev.matrix_world.inverted_safe()
    mw = ob.matrix_world
    out = []
    for i in idx:
        p = mw @ ob.data.vertices[i].co
        hit = bvh.find_nearest(inv @ p)
        out.append(math.inf if hit is None or hit[0] is None else (ev.matrix_world @ hit[0] - p).length)
    return out


def _partition(context, ob, parts, weights):
    """Give each wrapped point (weights = Maya wrap weight) to the vertex group of its nearest influence."""
    depsgraph = context.evaluated_depsgraph_get()
    idx = sorted(weights)
    dist = [_distances(ob, idx, sd.target, depsgraph) for sd, _hk in parts]
    groups = [ob.vertex_groups.get(sd.vertex_group) for sd, _hk in parts]
    for k, vg in enumerate(groups):
        mine = [i for j, i in enumerate(idx) if min(range(len(parts)), key=lambda q: dist[q][j]) == k]
        others = [i for i in idx if i not in set(mine)]
        if others:
            vg.remove(others)
        for i in mine:
            vg.add([i], weights[i], 'REPLACE')


def _move_after(context, ob, names, after):
    """Put modifiers ``names`` (in order) right after index ``after``."""
    with context.temp_override(object=ob, active_object=ob):
        for k, name in enumerate(names):
            bpy.ops.object.modifier_move_to_index(modifier=name, index=after + 1 + k)


def add_wrap_influence(context, ob, md, infl):
    parts = _influence_parts(ob, md)
    if any(sd.target == infl for sd, _hk in parts):
        return None
    weights = {}
    for sd, _hk in parts:
        for i, w in _weights(ob, sd.vertex_group).items():
            weights[i] = weights.get(i, 0.0) + w
    k = 2
    while ob.modifiers.get(f"{md.name}Influence{k}") or ob.vertex_groups.get(f"{md.name}Influence{k}"):
        k += 1
    name = f"{md.name}Influence{k}"
    ob.vertex_groups.new(name=name)
    new = ob.modifiers.new(name, 'SURFACE_DEFORM')
    new.target = infl
    new.vertex_group = name
    _partition(context, ob, parts + [(new, None)], weights)
    last = max(ob.modifiers.find(m.name) for sd, hk in parts for m in (sd, hk) if m is not None)
    deformers._bind(ob, new)
    hk = deformers._base_hook(ob, name, infl, name)
    _move_after(context, ob, [new.name, hk.name], last)
    return new


def remove_wrap_influence(context, ob, md, infl):
    parts = _influence_parts(ob, md)
    hit = next(((sd, hk) for sd, hk in parts if sd.target == infl), None)
    if hit is None:
        return False
    weights = {}
    for sd, _hk in parts:
        for i, w in _weights(ob, sd.vertex_group).items():
            weights[i] = weights.get(i, 0.0) + w
    if len(parts) == 1:                        # the last influence: the wrap node goes (Maya keeps an empty wrap1)
        group = md.vertex_group
        for m in (md, hit[1]):
            if m is not None:
                ob.modifiers.remove(m)
        vg = ob.vertex_groups.get(group)
        if vg is not None:
            ob.vertex_groups.remove(vg)
        return True
    sd, hk = hit
    if sd == md:
        # the node's own influence goes: its first extra influence takes the node's modifier (target, bind, hook)
        extra, extra_hk = parts[1]
        md.target = extra.target
        main_hk = parts[0][1]
        if main_hk is not None and extra_hk is not None:
            main_hk.object = extra_hk.object
            main_hk.center = extra_hk.center
            main_hk.matrix_inverse = extra_hk.matrix_inverse
        sd, hk = extra, extra_hk
        parts = [(md, main_hk)] + parts[2:]
    else:
        parts = [p for p in parts if p[0] != sd]
    group = sd.vertex_group
    for m in (sd, hk):
        if m is not None:
            ob.modifiers.remove(m)
    vg = ob.vertex_groups.get(group)
    if vg is not None:
        ob.vertex_groups.remove(vg)
    _partition(context, ob, parts, weights)
    if hit[0] is md:
        _rebind(ob, md)
    return True


def _rebind(ob, md):
    """Bind ``md`` again to its (new) target: Blender's bind operator toggles, so unbind first."""
    if md.is_bound:
        with bpy.context.temp_override(object=ob, active_object=ob):
            bpy.ops.object.surfacedeform_bind(modifier=md.name)
    deformers._bind(ob, md)


def wrap_influence(context, add):
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    infl = context.view_layer.objects.active
    surfaces = [o for o in context.selected_objects if o is not infl]
    if infl is None or not infl.select_get() or not surfaces:
        raise RuntimeError(MSG_WRAP_SELECT)
    if infl.type not in {'MESH'}:
        raise RuntimeError(MSG_WRAP_INFLUENCE)
    done = []
    for ob in surfaces:
        wraps = _wraps(ob) if ob.type == 'MESH' else []
        if not wraps:
            raise RuntimeError(MSG_NO_WRAP.format(ob.name))
        for md in wraps:
            name = md.name
            if add:
                if add_wrap_influence(context, ob, md, infl) is not None:
                    done.append(name)
            elif remove_wrap_influence(context, ob, md, infl):
                done.append(name)
    infl.select_set(False)                     # Maya: the influence leaves the selection (select -tgl)
    context.view_layer.objects.active = surfaces[-1]
    context.view_layer.update()
    return done


@undo_steps.no_redo_panel
class ALLSET_OT_wrap_influence(bpy.types.Operator):
    """Add / remove the last selected object as an influence of the selected surfaces' wrap deformers (Maya Deform >
    Wrap > Add Influence / Remove Influence)"""
    bl_idname = "allset.wrap_influence"
    bl_label = "Wrap Influence"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=[('ADD', "Add Influence", ""), ('REMOVE', "Remove Influence", "")], default='ADD',
                         options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return ("Let this object drive the wrap deformation too" if props.action == 'ADD'
                else "Remove wrap influence")

    def execute(self, context):
        try:
            done = wrap_influence(context, self.action == 'ADD')
        except RuntimeError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        results.result(self, " ".join(done))
        return {'FINISHED'}
