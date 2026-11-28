# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Flood for Paint Skin Weights: the paint operation x Opacity into the painted influence (``maya_target``:
Replace, Add, Scale, Smooth ...), the other unlocked influences sharing the rest in their old ratio
(``redistribute``), the vertices a Flood changes (``flood_vertices``) and ``flood`` itself (called by
paint_skin_weights). Settings: weight_paint_settings."""
from .. import compat
from . import skin
from .weight_paint_settings import brush_kind, state


# --- Flood (Maya 2026 Paint Skin Weights Flood) ---------
# Maya applies the operation to the influence being painted, multiplied by Opacity o:
#   Replace w' = w + o(v - w)   Add w' = min(1, w + o v)   Scale w' = w (1 - o (1 - v))
#   Smooth  w' = w + o(avg - w), avg = the mean of the vertex and its edge neighbours (Value ignored)
# and gives the change to the other unlocked influences in their old ratio; locked influences keep their weight; only
# selected vertices change when any vertex is selected (Maya).

OPERATIONS = (('BRUSH', 'Brush', 'The current brush and its blend'), ('REPLACE', 'Replace', ''),
              ('ADD', 'Add', ''), ('SCALE', 'Scale', ''), ('SMOOTH', 'Smooth', ''))
_BLEND_OPERATION = {'MIX': 'REPLACE', 'ADD': 'ADD', 'MUL': 'SCALE'}


def maya_target(op, w, value, opacity, avg=None):
    """New weight of the painted influence for one vertex (before clamping / redistribution)."""
    if op == 'REPLACE':
        return w + opacity * (value - w)
    if op == 'ADD':
        return w + opacity * value
    if op == 'SCALE':
        return w * (1.0 - opacity * (1.0 - value))
    if op == 'SMOOTH':
        return w + opacity * (avg - w)
    if op == 'SUB':
        return w - opacity * value
    if op == 'LIGHTEN':
        return w + opacity * (max(w, value) - w)
    if op == 'DARKEN':
        return w + opacity * (min(w, value) - w)
    raise ValueError(op)


def redistribute(weights, target, new, locked, influences):
    """Maya Interactive normalization of one vertex: ``weights`` {group: w}; returns the new {group: w}.

    The painted influence gets ``new`` clamped to what the locked ones leave; the unlocked other influences share the
    rest in their old ratio (Replace 0.3 keeps j1:j3, Value 0 gives j2's weight to j1 / j3, joint1 locked + Add 1 only
    takes joint3's share)."""
    out = dict(weights)
    locked_sum = sum(w for g, w in weights.items() if g != target and g in locked and g in influences)
    others = {g: w for g, w in weights.items() if g != target and g not in locked and g in influences and w > 0}
    room = max(0.0, 1.0 - locked_sum)
    new = min(max(new, 0.0), room)
    total = sum(others.values())
    if total <= 0.0:
        # nothing unlocked takes the rest: a normalized vertex can't lose weight, an unweighted one simply gets the
        # value (a kit choice)
        new = max(new, min(room, weights.get(target, 0.0)))
    else:
        rest = room - new
        for g, w in others.items():
            out[g] = rest * w / total
    out[target] = new
    return out


def flood_vertices(mesh):
    """Vertices a Flood changes: the face mask's faces, else the selected vertices when any vertex is selected (Maya
    floods only selected components, vertex mask on or off), else every visible vertex."""
    data = mesh.data
    visible = [v.index for v in data.vertices if not v.hide]
    if data.use_paint_mask:
        faces = {i for f in data.polygons if f.select and not f.hide for i in f.vertices}
        return [i for i in visible if i in faces]
    selected = [i for i in visible if data.vertices[i].select]
    return selected if selected else visible


def _neighbours(data):
    nb = [[] for _ in data.vertices]
    for e in data.edges:
        a, b = e.vertices
        nb[a].append(b)
        nb[b].append(a)
    return nb


def flood_settings(context, operation='BRUSH'):
    """(operation, value, opacity) from the operator or the current brush."""
    ts = context.tool_settings
    brush = ts.weight_paint.brush
    ups = compat.unified_paint_settings(ts)
    strength = compat.unified_value_owner(ups, brush, 'strength').strength
    value = compat.unified_value_owner(ups, brush, 'weight').weight
    if operation != 'BRUSH':
        return operation, value, strength
    kind = brush_kind(brush) or 'DRAW'
    if kind == 'SMEAR':
        raise ValueError('Smear needs a directional stroke; choose another operation to flood')
    if kind == 'BLUR':
        return 'SMOOTH', value, strength
    if kind == 'AVERAGE':
        return 'AVERAGE', value, strength
    blend = brush.blend if brush is not None else 'MIX'
    op = _BLEND_OPERATION.get(blend, blend)
    if op not in {'REPLACE', 'ADD', 'SCALE', 'SUB', 'LIGHTEN', 'DARKEN'}:
        raise ValueError('Flood supports Replace, Add, Scale, Smooth, Subtract, Lighten, Darken and Average')
    return op, value, strength


def flood(context, operation='BRUSH'):
    """Maya Flood: the paint operation x Opacity into the painted influence, Maya's redistribution and locks."""
    mesh = context.active_object
    group = mesh.vertex_groups.active
    if group is None or group.lock_weight:
        raise ValueError('Choose an unlocked influence before flooding')
    op, value, opacity = flood_settings(context, operation)
    data = mesh.data
    targets = flood_vertices(mesh)
    if context.tool_settings.weight_paint.use_group_restrict:
        targets = [i for i in targets if any(e.group == group.index for e in data.vertices[i].groups)]
    if not targets or opacity <= 0:
        return {'FINISHED'}
    t = group.index
    rows = {i: {e.group: e.weight for e in data.vertices[i].groups} for i in targets}
    nb, own = None, None
    if op == 'SMOOTH':
        nb = _neighbours(data)
        own = {}
        for i in {j for i in targets for j in (i, *nb[i])}:
            own[i] = next((e.weight for e in data.vertices[i].groups if e.group == t), 0.0)
    elif op == 'AVERAGE':
        op, value = 'REPLACE', sum(r.get(t, 0.0) for r in rows.values()) / len(rows)
    influences = {g.index for g in skin.influences(mesh)}
    normalize = context.tool_settings.use_auto_normalize and t in influences
    locked = {g.index for g in mesh.vertex_groups if g.lock_weight}
    groups = mesh.vertex_groups
    st = state(context)
    lo_hi = (min(st.min_value, st.max_value), max(st.min_value, st.max_value))
    for i, row in rows.items():
        w = row.get(t, 0.0)
        avg = (own[i] + sum(own[j] for j in nb[i])) / (1 + len(nb[i])) if op == 'SMOOTH' else None
        new = maya_target(op, w, value, opacity, avg)
        new = min(lo_hi[1], max(lo_hi[0], new))         # Maya Min / Max value
        if normalize:
            result = redistribute(row, t, new, locked, influences)
        else:
            result = {**row, t: min(1.0, max(0.0, new))}
        for g, nw in result.items():
            if nw == row.get(g):
                continue
            if nw <= 0.0:
                if g in row:
                    groups[g].remove([i])
            else:
                groups[g].add([i], nw, 'REPLACE')
    data.update()
    state(context).status = 'Flood complete'
    return {'FINISHED'}
