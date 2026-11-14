# SPDX-License-Identifier: GPL-3.0-or-later
"""Skin layers on a kit skin, like Maya's Skin Tools: a stack of weight layers over the skin's vertex groups.

A kit skin = an Armature modifier + vertex groups named after its joints (``skin.py``). The layer stack lives on the
mesh object (``Object.allset_skin_layers``, registered by ``ui/skin_tools.py``): a list of layers, top first, each
with a name, Enabled, Opacity and a hidden ``uid``. A layer's weights are ID properties of its list item —
``item["w"] = {joint: float array, one value per vertex}`` (only joints that weigh something) and ``item["mask"]``
(one value per vertex; absent = the layer covers the whole mesh). Object data is saved with the file and restored by
undo, and it stays out of the mesh's attribute list (exporters write attributes).

The skin's vertex groups always hold the stack's result (``skin_layers_math.composite``): every layer edit
re-composites them.

Painting a layer: the kit paints working vertex groups ``.st:<joint>`` / ``.st:Mask`` holding the active layer's own
weights (not joint names, so the Armature modifier and Auto Normalize leave them alone). A depsgraph handler marks the
mesh dirty; a timer, once no paint stroke is running, reads the working groups back into the layer (the other joints
of an edited vertex make room for the painted one, ``settle_rows``) and re-composites. A joint picked while painting
(its vertex group made active) switches the brush to that joint's working group.
"""

import bpy
import numpy as np

from . import skin, skin_layers_math as math_

PROP = "allset_skin_layers"
WORK = ".st:"
WORK_MASK = WORK + "Mask"
BASE_NAME = "Base Weights"
F32 = np.float32


# --- reading the stack ----------------------------------------------------------------------------------------------

def state(ob):
    return getattr(ob, PROP, None) if ob is not None else None


def is_initialized(ob):
    st = state(ob)
    return bool(st is not None and st.initialized and len(st.layers))


def skinned(ob):
    return ob is not None and ob.type == 'MESH' and skin.armature_modifier(ob) is not None


def vert_count(ob):
    return len(ob.data.vertices)


def topology_ok(ob):
    st = state(ob)
    return st is not None and st.vert_count == vert_count(ob)


def influence_names(ob):
    """The skin's influences (joint vertex groups), skeleton order (depth first from the root, Maya's order)."""
    mod = skin.armature_modifier(ob)
    if mod is None:
        return []
    have = {vg.name for vg in skin.influences(ob, mod)}
    out, todo = [], [b for b in mod.object.data.bones if b.parent is None]
    while todo:
        b = todo.pop(0)
        if b.name in have:
            out.append(b.name)
        todo[0:0] = list(b.children)
    return out


def joint_depth(ob, name):
    mod = skin.armature_modifier(ob)
    b = mod.object.data.bones.get(name) if mod is not None else None
    d = 0
    while b is not None and b.parent is not None:
        b, d = b.parent, d + 1
    return d


def active_layer(ob):
    st = state(ob)
    if st is None or not len(st.layers):
        return None
    return st.layers[min(max(st.active_index, 0), len(st.layers) - 1)]


def layer_by_uid(ob, uid):
    st = state(ob)
    return next((lay for lay in st.layers if lay.uid == uid), None) if st is not None else None


def layer_matrix(ob, layer, names):
    """(V, K) weights of ``layer`` for joints ``names``."""
    n = vert_count(ob)
    w = np.zeros((n, len(names)))
    stored = layer.get("w")
    if stored is not None:
        for j, name in enumerate(names):
            arr = stored.get(name)
            if arr is not None:
                vals = np.asarray(arr.to_list() if hasattr(arr, "to_list") else list(arr), dtype=float)
                w[:min(n, len(vals)), j] = vals[:n]
    return w


def set_layer_matrix(layer, names, w):
    """Store (V, K) ``w`` as the layer's weights (float32 values: the same numbers the vertex groups hold)."""
    w = np.asarray(w, dtype=F32)
    layer["w"] = {name: w[:, j].astype(float).tolist() for j, name in enumerate(names) if np.any(w[:, j] > 0)}


def layer_mask(ob, layer):
    m = layer.get("mask")
    if m is None:
        return None
    vals = np.asarray(m.to_list() if hasattr(m, "to_list") else list(m), dtype=float)
    out = np.zeros(vert_count(ob))
    out[:min(len(out), len(vals))] = vals[:len(out)]
    return out


def set_layer_mask(layer, mask):
    if mask is None:
        if "mask" in layer:
            del layer["mask"]
        return
    layer["mask"] = np.clip(np.asarray(mask, dtype=F32), 0.0, 1.0).astype(float).tolist()


def stack(ob, names):
    """The layers as ``skin_layers_math.composite`` takes them."""
    return [{"weights": {n: layer_matrix(ob, lay, names)[:, j] for j, n in enumerate(names)},
             "mask": layer_mask(ob, lay), "opacity": lay.opacity, "enabled": lay.enabled}
            for lay in state(ob).layers]


# --- vertex groups --------------------------------------------------------------------------------------------------

def read_groups(ob, names):
    """(V, K) weights of the vertex groups ``names`` (missing groups read 0)."""
    col = {}
    for j, name in enumerate(names):
        vg = ob.vertex_groups.get(name)
        if vg is not None:
            col[vg.index] = j
    w = np.zeros((vert_count(ob), len(names)))
    if col:
        for v in ob.data.vertices:
            for g in v.groups:
                j = col.get(g.group)
                if j is not None:
                    w[v.index, j] = g.weight
    return w


def write_groups(ob, names, w, old=None):
    """Write (V, K) ``w`` into vertex groups ``names`` (made when missing); only rows that differ from ``old``."""
    w = np.asarray(w, dtype=float)
    for name in names:
        if ob.vertex_groups.get(name) is None:
            ob.vertex_groups.new(name=name)
    if old is None:
        old = read_groups(ob, names)
    rows = np.flatnonzero((np.abs(w - old) > 1e-6).any(axis=1)) if len(names) else []
    if not len(rows):
        return 0
    for j, name in enumerate(names):
        vg = ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
        for i in rows:
            value = float(w[i, j])
            if value > 0.0:
                vg.add([int(i)], value, 'REPLACE')
            elif old[i, j] > 0.0:
                vg.remove([int(i)])
    ob.data.update()
    return len(rows)


def recomposite(ob):
    """Write the stack's result into the skin's joint vertex groups. False when the mesh's vertex count changed."""
    if not is_initialized(ob) or not topology_ok(ob):
        return False
    names = influence_names(ob)
    final = math_.composite(stack(ob, names), vert_count(ob), names)
    if write_groups(ob, names, final):
        from . import skin_basics
        skin_basics.enforce_max(ob)
    return True


# --- stack edits ----------------------------------------------------------------------------------------------------

def _next_uid(st):
    return max((lay.uid for lay in st.layers), default=0) + 1


def unique_name(st, base):
    taken = {lay.name for lay in st.layers}
    if base not in taken:
        return base
    n = 1
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"


def initialize(ob):
    """Make the stack: one base layer holding the skin's current weights (Maya: Initialize Skin Layers)."""
    st = state(ob)
    stop_paint(ob)
    st.layers.clear()
    st.vert_count = vert_count(ob)
    names = influence_names(ob)
    lay = st.layers.add()
    lay.uid = 1
    lay.name = BASE_NAME
    set_layer_matrix(lay, names, read_groups(ob, names))
    st.active_index = 0
    st.initialized = True
    st.influence = names[0] if names else ""
    st.paint_mask = False
    return lay


def delete_layers(ob):
    """Maya Delete Skin Layers: the stack goes, the skin keeps its current weights."""
    st = state(ob)
    stop_paint(ob)
    st.layers.clear()
    st.initialized = False


def add_layer(ob, name="Layer", copy_of=None):
    """A new empty layer above the active one (or a copy of ``copy_of``); returns its index."""
    st = state(ob)
    at = min(max(st.active_index, 0), len(st.layers))
    new_name = unique_name(st, copy_of.name if copy_of is not None else name)
    uid = _next_uid(st)
    lay = st.layers.add()
    lay.uid = uid
    lay.name = new_name
    if copy_of is not None:
        lay.opacity, lay.enabled = copy_of.opacity, copy_of.enabled
        names = influence_names(ob)
        set_layer_matrix(lay, names, layer_matrix(ob, copy_of, names))
        set_layer_mask(lay, layer_mask(ob, copy_of))
    st.layers.move(len(st.layers) - 1, at)
    st.active_index = at
    return at


def remove_layer(ob, index):
    st = state(ob)
    if not (0 <= index < len(st.layers)) or len(st.layers) <= 1:
        return False
    st.layers.remove(index)
    st.active_index = min(st.active_index, len(st.layers) - 1)
    return True


def move_layer(ob, index, step):
    st = state(ob)
    to = index + step
    if not (0 <= index < len(st.layers) and 0 <= to < len(st.layers)):
        return False
    st.layers.move(index, to)
    st.active_index = to
    return True


def target_rows(ob):
    from . import skin_basics
    return skin_basics.target_rows(ob)


def _neighbours(ob):
    nb = [[] for _ in range(vert_count(ob))]
    for e in ob.data.edges:
        a, b = e.vertices
        nb[a].append(b)
        nb[b].append(a)
    return nb


def set_weights(ob, mode, intensity, iterations=1, rows=None):
    """Set Weights tab on the active layer: REPLACE / ADD / SCALE the picked influence (or the mask) by
    ``intensity`` on ``rows`` (selected vertices, else all), or SMOOTH every influence of the layer (or the mask)."""
    st = state(ob)
    lay = active_layer(ob)
    names = influence_names(ob)
    rows = target_rows(ob) if rows is None else np.asarray(rows, dtype=int)
    if st.paint_mask:
        cur = layer_mask(ob, lay)
        m = np.zeros(vert_count(ob)) if cur is None else cur
        if mode == "SMOOTH":
            m = math_.smooth(m, _neighbours(ob), rows, intensity, iterations)
        elif mode == "REPLACE":
            m[rows] = intensity
        elif mode == "ADD":
            m[rows] = m[rows] + intensity
        else:
            m[rows] = m[rows] * intensity
        set_layer_mask(lay, np.clip(m, 0.0, 1.0))
    else:
        w = layer_matrix(ob, lay, names)
        if mode == "SMOOTH":
            new = math_.smooth(w, _neighbours(ob), rows, intensity, iterations)
            new = math_.clamp_rows(new)
        else:
            if st.influence not in names:
                return False
            new = math_.set_value(w, rows, names.index(st.influence), mode, intensity)
        set_layer_matrix(lay, names, new)
    refresh_after_edit(ob)
    return True


def mirror_layer(ob, axis=0, positive_to_negative=True):
    """Mirror tab: the active layer's weights and mask from one side onto the other; vertices are paired with the
    vertex nearest their mirrored place, joints by label then by place (Mirror Skin Weights' pairing)."""
    from mathutils import kdtree
    lay = active_layer(ob)
    names = influence_names(ob)
    mod = skin.armature_modifier(ob)
    pair = skin.mirror_group_names(mod.object, axis, modes=("LABEL", "CLOSEST_JOINT"))
    col = {n: j for j, n in enumerate(names)}
    column_pair = {j: col.get(pair.get(n, n), j) for j, n in enumerate(names)}
    mw = ob.matrix_world
    world = [mw @ v.co for v in ob.data.vertices]
    tree = kdtree.KDTree(len(world))
    for i, p in enumerate(world):
        tree.insert(p, i)
    tree.balance()
    eps = 1e-6
    dst = [i for i, p in enumerate(world) if (p[axis] < -eps if positive_to_negative else p[axis] > eps)]
    src = []
    for i in dst:
        q = world[i].copy()
        q[axis] = -q[axis]
        src.append(tree.find(q)[1])
    w = layer_matrix(ob, lay, names)
    set_layer_matrix(lay, names, math_.mirror_columns(w, src, column_pair, dst))
    mask = layer_mask(ob, lay)
    if mask is not None:
        mask = mask.copy()
        mask[dst] = mask[src]
        set_layer_mask(lay, mask)
    refresh_after_edit(ob)
    return len(dst)


def assign_closest(ob, picked=None, rows=None):
    """Assign from Closest Joint: on the active layer each target vertex weighs 1 on its nearest joint (distance to
    the joint's segments) among ``picked`` (default: every influence)."""
    names = influence_names(ob)
    use = [n for n in (picked or names) if n in names] or names
    mod = skin.armature_modifier(ob)
    segs = skin.joint_segments(mod.object, set(use))
    mw = ob.matrix_world
    rows = target_rows(ob) if rows is None else np.asarray(rows, dtype=int)
    pts = [mw @ ob.data.vertices[int(i)].co for i in rows]
    dist = np.full((len(rows), len(use)), np.inf)
    for k, name in enumerate(use):
        for a, b in segs.get(name, ()):
            for r, p in enumerate(pts):
                dist[r, k] = min(dist[r, k], skin._segment_distance(p, a, b))
    one = math_.closest_joint(dist)
    lay = active_layer(ob)
    w = layer_matrix(ob, lay, names)
    w[rows] = 0.0
    for k, name in enumerate(use):
        w[rows, names.index(name)] = one[:, k]
    set_layer_matrix(lay, names, w)
    refresh_after_edit(ob)
    return len(rows)


def refresh_after_edit(ob):
    """After a stack edit: the working groups (while painting) show the active layer again, the skin is
    re-composited."""
    if painting(ob):
        load_working(ob)
    recomposite(ob)


# --- painting a layer -----------------------------------------------------------------------------------------------

_session = {"ob": None, "uid": 0, "dirty": False, "auto_normalize": None}


def painting(ob=None):
    name = _session["ob"]
    return name is not None and (ob is None or ob.name == name)


def session_object():
    return bpy.data.objects.get(_session["ob"]) if _session["ob"] else None


def work_names(names):
    return [WORK + n for n in names]


def load_working(ob):
    """Fill the working groups from the active layer and make the picked one active."""
    st = state(ob)
    lay = active_layer(ob)
    names = influence_names(ob)
    _session["uid"] = lay.uid
    write_groups(ob, work_names(names), layer_matrix(ob, lay, names))
    mask = layer_mask(ob, lay)
    write_groups(ob, [WORK_MASK], (np.zeros(vert_count(ob)) if mask is None else mask)[:, None])
    pick_working(ob, WORK_MASK if st.paint_mask else WORK + st.influence)


def pick_working(ob, group_name):
    vg = ob.vertex_groups.get(group_name)
    if vg is not None and ob.vertex_groups.active_index != vg.index:
        ob.vertex_groups.active_index = vg.index


def remove_working(ob):
    for vg in [vg for vg in ob.vertex_groups if vg.name.startswith(WORK)]:
        ob.vertex_groups.remove(vg)


def start_paint(context, ob):
    """Weight paint the active layer (kit Paint Skin Weights' paint mode + working groups)."""
    if not is_initialized(ob) or not topology_ok(ob):
        return False
    if _session["ob"] and _session["ob"] != ob.name:
        other = session_object()
        if other is not None:
            stop_paint(other)
    if ob.mode != 'WEIGHT_PAINT':
        from ..ui.status_line import main_view3d
        override = {}
        wins = context.window_manager.windows
        if len(wins):                     # the main window's 3D View (the window may be Skin Tools' own)
            win = wins[0]
            area, region = main_view3d(win.screen)
            override = {"window": win, "screen": win.screen}
            if area is not None and region is not None:
                override.update(area=area, region=region)
        view_layer = context.view_layer
        for o in context.selected_objects:
            o.select_set(False)
        ob.select_set(True)
        view_layer.objects.active = ob
        try:
            with context.temp_override(**override):
                bpy.ops.allset.paint_skin_weights(classic=True)
        except RuntimeError:              # no tool system (background): paint mode alone
            if ob.mode != 'WEIGHT_PAINT':
                bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
    if ob.mode != 'WEIGHT_PAINT':
        return False
    remove_working(ob)
    _session["ob"] = ob.name
    ts = context.scene.tool_settings
    _session["auto_normalize"] = ts.use_auto_normalize
    ts.use_auto_normalize = False          # working groups aren't joints: the kit makes room on stroke end itself
    load_working(ob)
    _session["dirty"] = False
    ensure_timer()
    return True


def stop_paint(ob):
    """Leave layer painting: last sync, working groups removed (weight paint mode itself is left to the caller)."""
    if not painting(ob):
        return
    sync(ob)
    remove_working(ob)
    _end_session()


def _end_session():
    if _session["auto_normalize"] is not None:
        try:
            bpy.context.scene.tool_settings.use_auto_normalize = _session["auto_normalize"]
        except AttributeError:
            pass
    _session.update(ob=None, uid=0, dirty=False, auto_normalize=None)


def stroke_running():
    wm = bpy.context.window_manager
    for win in wm.windows:
        for op in win.modal_operators:
            if op.bl_idname in ("PAINT_OT_weight_paint", "paint.weight_paint", "PAINT_OT_weight_gradient",
                                "paint.weight_gradient"):
                return True
    return False


def follow_pick(ob):
    """A joint group made active while painting (Ctrl+click on a joint, the Tool Settings list) = paint that joint
    on the layer."""
    st = state(ob)
    vg = ob.vertex_groups.active
    if vg is None:
        return
    names = influence_names(ob)
    if vg.name in names:
        st.influence, st.paint_mask = vg.name, False
        pick_working(ob, WORK + vg.name)
    elif vg.name == WORK_MASK:
        if not st.paint_mask:
            st.paint_mask = True
    elif vg.name.startswith(WORK) and vg.name[len(WORK):] in names:
        if st.influence != vg.name[len(WORK):] or st.paint_mask:
            st.influence, st.paint_mask = vg.name[len(WORK):], False


def sync(ob):
    """Read the working groups back into the session's layer and re-composite. True when something changed."""
    lay = layer_by_uid(ob, _session["uid"])
    if lay is None or not topology_ok(ob):
        return False
    names = influence_names(ob)
    wnames = work_names(names)
    work = read_groups(ob, wnames)
    stored = layer_matrix(ob, lay, names)
    changed = False
    if np.any(np.abs(work - stored) > 1e-6):
        settled = math_.settle_rows(stored, work)
        set_layer_matrix(lay, names, settled)
        write_groups(ob, wnames, settled, old=work)
        changed = True
    m = read_groups(ob, [WORK_MASK])[:, 0]
    old_mask = layer_mask(ob, lay)
    if old_mask is None:
        if np.any(m > 1e-6):
            set_layer_mask(lay, m)
            changed = True
    elif np.any(np.abs(m - old_mask) > 1e-6):
        set_layer_mask(lay, m)
        changed = True
    if changed:
        recomposite(ob)
    return changed


TICK = 0.2


def _tick():
    ob = session_object()
    if ob is None:
        _end_session()
        return None
    if ob.mode != 'WEIGHT_PAINT':
        try:
            sync(ob)
            remove_working(ob)
        finally:
            _end_session()
        return None
    if stroke_running():
        return TICK
    try:
        follow_pick(ob)
        if _session["dirty"]:
            _session["dirty"] = False
            st = state(ob)
            if active_layer(ob) is not None and active_layer(ob).uid != _session["uid"]:
                load_working(ob)          # undo / another layer picked: show the active layer
            elif sync(ob):
                st.id_data.update_tag()
    except (ReferenceError, AttributeError, RuntimeError):
        _end_session()
        return None
    return TICK


def ensure_timer():
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=TICK, persistent=True)


@bpy.app.handlers.persistent
def on_depsgraph(scene, depsgraph):
    if not _session["ob"]:
        return
    for up in depsgraph.updates:
        idb = up.id
        if isinstance(idb, (bpy.types.Object, bpy.types.Mesh)) and getattr(idb, "name", None) in (
                _session["ob"], getattr(getattr(session_object(), "data", None), "name", None)):
            _session["dirty"] = True
            return


@bpy.app.handlers.persistent
def on_load(*_args):
    _session.update(ob=None, uid=0, dirty=False, auto_normalize=None)


def switch_layer(ob, old_uid):
    """The active layer changed while painting: keep the old layer's strokes, show the new one."""
    if not painting(ob):
        return
    if old_uid:
        _session["uid"] = old_uid
        sync(ob)
    load_working(ob)
