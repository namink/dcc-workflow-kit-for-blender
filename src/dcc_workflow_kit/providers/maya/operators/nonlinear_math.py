# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's Twist, Squash, Flare, Sine and Wave shapes on a lattice or a NURBS surface (#493).

The same shapes as the Geometry Nodes groups in operators/nonlinear_nodes.py (see its docstring for each one), worked
out here in Python for the objects that can't take Geometry Nodes. Such a node keeps its modifier (no effect of its own:
Simple Deform angle / factor 0, Wave height 0) for the node's name, rows and history, and its Maya values on the handle
(``allset_nl_<attribute>``, keyable like the node's attributes). The shape itself is a shape key of the node's name
on the object, relative to its Basis: the handler below works it out again whenever the handle, the object, the
points or a value changes. Several such nodes on one object deform one after the other, in their keys' order.
"""

import math

import bpy

from . import nonlinear_nodes as nl

KIND_PROP = "allset_nl_kind"      # on the handle: the node type its Maya values are for
PREFIX = "allset_nl_"
KEY_PROP = "allset_nl_keys"       # on a Key datablock: the names of its kit nonlinear shape keys
BASIS_PROP = "allset_nl_basis"    # on a Key datablock: the kit made its Basis
_MODIFIER = {"twist": ('SIMPLE_DEFORM', 'TWIST'), "squash": ('SIMPLE_DEFORM', 'STRETCH'),
             "flare": ('SIMPLE_DEFORM', 'TAPER'), "sine": ('WAVE', None), "wave": ('WAVE', None)}


def prop(name):
    """The handle property that holds Maya attribute ``name`` (``Start Angle`` -> ``allset_nl_startAngle``)."""
    words = name.split()
    return PREFIX + words[0].lower() + "".join(words[1:])


def names(kind):
    return ("Envelope",) + tuple(n for n, _d, _s in nl.KINDS[kind][1])


def defaults(kind):
    return {"Envelope": 1.0, **{n: d for n, d, _s in nl.KINDS[kind][1]}}


# --- the shapes (Maya handle space: y along the handle) ------------------------------------------------------

def _clamp(v, lo, hi):
    return min(max(v, lo), hi)


def _along(v, y):
    lo, hi = v["Low Bound"], v["High Bound"]
    t = _clamp(y, lo, hi)
    return t, ((t - lo) / (hi - lo) if hi - lo != 0.0 else 0.0)


def _twist(v, x, y, z):
    _t, u = _along(v, y)
    a = v["Start Angle"] + (v["End Angle"] - v["Start Angle"]) * u
    s, c = math.sin(a), math.cos(a)
    return x * c - z * s, y, x * s + z * c


def _flare(v, x, y, z):
    _t, u = _along(v, y)
    curve = 1.0 + v["Curve"] * math.sin(math.pi * u)
    sx = (v["Start Flare X"] + (v["End Flare X"] - v["Start Flare X"]) * u) * curve
    sz = (v["Start Flare Z"] + (v["End Flare Z"] - v["Start Flare Z"]) * u) * curve
    return x * sx, y, z * sz


def squash_profile(v, up):
    """The bulge over ``up``: 1 at 0.5, 0 at 0 and 1, rounded off towards each end by its smoothness."""
    m = _clamp(v["End Smoothness"] if up > 0.5 else v["Start Smoothness"], 0.0, 1.0)
    w = abs(up - 0.5) * 2.0
    r = m + 1.0
    e = math.sqrt(m * (m + 2.0))
    ellipse = (math.sqrt(max(r * r - w * w, 0.0)) - e) / (r - e)
    ease = (math.cos(w * math.pi) + 1.0) * 0.5
    return ellipse + (ease - ellipse) * m


def _squash(v, x, y, z):
    t, u = _along(v, y)
    f = v["Factor"]
    s = (1.0 + max(f, 0.0)) / (1.0 - min(f, 0.0))
    y2 = y + t * (s - 1.0)
    m = _clamp(v["Max Expand Pos"], 0.01, 0.99)
    up = u ** math.log(0.5, m) if u > 0.0 else 0.0
    k = v["Expand"] * 2.0 * (math.sqrt(s) - 1.0) * squash_profile(v, up)
    side = 1.0 / (1.0 + k) if 1.0 + k != 0.0 else 0.0
    return x * side, y2, z * side


def _sine(v, x, y, z):
    t, _u = _along(v, y)
    d = v["Dropoff"]
    reach = max(v["High Bound"], -v["Low Bound"])
    n = abs(t) / reach if reach != 0.0 else 0.0
    k = 1.0 - d * n + min(d, 0.0)
    wl = max(v["Wavelength"], nl.WAVELENGTH_MIN["sine"])
    return x + v["Amplitude"] * k * math.sin(2.0 * math.pi * (t + v["Offset"]) / wl), y, z


def _wave(v, x, y, z):
    lo, hi = v["Min Radius"], v["Max Radius"]
    rc = _clamp(math.hypot(x, z), lo, hi)
    n = (rc - lo) / (hi - lo) if hi - lo != 0.0 else 0.0
    pos = _clamp(v["Dropoff Position"], 0.0, 1.0)
    above = max(n - pos, 0.0) / (1.0 - pos) if pos != 1.0 else 0.0
    below = max(pos - n, 0.0) / pos if pos != 0.0 else 0.0
    d = v["Dropoff"]
    k = (1.0 if d > -1e-12 else 0.0) - d * (above + below)
    wl = max(v["Wavelength"], nl.WAVELENGTH_MIN["wave"])
    return x, y + v["Amplitude"] * k * math.cos(2.0 * math.pi * (rc - lo + v["Offset"]) / wl), z


SHAPES = {"twist": _twist, "flare": _flare, "squash": _squash, "sine": _sine, "wave": _wave}


def deform(kind, values, x, y, z):
    """Point (x, y, z) in Maya handle space moved by ``kind`` with Maya ``values`` (Envelope not applied)."""
    return SHAPES[kind](values, x, y, z)


# --- the node on a lattice / surface ----------------------------------------------------------------------------

def handle(md):
    return getattr(md, "origin", None) or getattr(md, "start_position_object", None)


def kind_of(md):
    """The node type of a kit nonlinear node made this way on a lattice / surface, else None."""
    if md.type not in ('SIMPLE_DEFORM', 'WAVE'):
        return None
    from . import deformers
    base = deformers.base_of(md)
    h = handle(md)
    if base not in _MODIFIER or h is None:
        return None
    return base if h.get(KIND_PROP) == base else None


def values(md):
    """{Maya attribute: value} of such a node, read from its handle (angles in radians)."""
    kind = kind_of(md)
    h = handle(md)
    out = defaults(kind)
    for n in out:
        try:
            out[n] = float(h.get(prop(n), out[n]))
        except (TypeError, ValueError):
            pass
    return out


def set_value(md, name, value):
    kind = kind_of(md)
    v = nl.limited(kind, name, value)
    if name in ("Low Bound", "High Bound"):
        v = min(v, 0.0) if name == "Low Bound" else max(v, 0.0)
    h = handle(md)
    h[prop(name)] = v
    h.update_tag()
    sync(md.id_data)


def add(ob, name, kind, h, group_name, vals):
    """The node on lattice / surface ``ob``: its no-effect modifier, its Maya values on handle ``h``, its shape key."""
    mtype, method = _MODIFIER[kind]
    md = ob.modifiers.new(name, mtype)
    if mtype == 'SIMPLE_DEFORM':
        md.deform_method = method
        md.deform_axis = 'Z'
        md.origin = h
        md.angle = 0.0
        md.factor = 0.0
    else:
        md.start_position_object = h
        md.use_normal = False
        md.speed = 0.0
        md.height = 0.0
    if group_name:
        md.vertex_group = group_name
    h[KIND_PROP] = kind
    for n, d in defaults(kind).items():
        h[prop(n)] = nl.limited(kind, n, vals[n]) if n in vals else d
    sync(ob)
    return md


# --- the shape keys ---------------------------------------------------------------------------------------------

def _co_list(block):
    n = len(block.data)
    flat = [0.0] * (3 * n)
    block.data.foreach_get("co", flat)
    return [(flat[3 * i], flat[3 * i + 1], flat[3 * i + 2]) for i in range(n)]


def _weights(ob, group_name, n):
    if ob.type != 'LATTICE' or not group_name:
        return [1.0] * n
    vg = ob.vertex_groups.get(group_name)
    if vg is None:
        return [1.0] * n
    out = [0.0] * n
    for i, pt in enumerate(ob.data.points[:n]):
        for g in pt.groups:
            if g.group == vg.index:
                out[i] = g.weight
    return out


def _nodes(ob):
    """[(modifier, kind)] of the kit nonlinear nodes made this way on ``ob``."""
    return [(md, k) for md in ob.modifiers for k in [kind_of(md)] if k is not None]


def _shape(ob, md, kind, pts):
    """``pts`` (object space) moved by node ``md``, Envelope and weights applied."""
    h = handle(md)
    v = values(md)
    env = _clamp(v["Envelope"], -1.0, 1.0) if kind == "squash" else v["Envelope"]
    if not md.show_viewport or env == 0.0:
        return pts
    to_h = h.matrix_world.inverted_safe() @ ob.matrix_world
    back = to_h.inverted_safe()
    w = _weights(ob, md.vertex_group, len(pts))
    out = []
    from mathutils import Vector
    for p, wt in zip(pts, w):
        a = env * wt
        if a == 0.0:
            out.append(p)
            continue
        q = to_h @ Vector(p)
        x, y, z = deform(kind, v, q.x, q.z, -q.y)        # the kit handle's +X / +Z / -Y are Maya's X / Y / Z
        r = back @ Vector((x, -z, y))
        out.append(tuple(c + (d - c) * a for c, d in zip(p, r)))
    return out


def _ours(key):
    """Names of the kit nonlinear keys on Key datablock ``key`` (a key block can't hold properties of its own)."""
    try:
        return list(key.get(KEY_PROP, ())) if key is not None else []
    except TypeError:
        return []


def sync(ob):
    """Work the kit nonlinear shape keys of ``ob`` out again: each node's key = Basis + what it moves the points by
    after the nodes before it. Keys of nodes that are gone are removed (and the Basis with the last one, when the kit
    made it). Writes only what changed; True when something was written."""
    nodes = _nodes(ob)
    key = getattr(ob.data, "shape_keys", None)
    ours = _ours(key)
    if not nodes and key is None:
        return False
    from .. import update_summary
    done = False
    if key is None:
        update_summary.wrote()
        ob.shape_key_add(name="Basis", from_mix=False)
        key = ob.data.shape_keys
        key[BASIS_PROP] = True
        done = True
    blocks = key.key_blocks
    names_ = [md.name for md, _k in nodes]
    for kb in [kb for kb in list(blocks)[1:] if kb.name in ours and kb.name not in names_]:
        update_summary.wrote()
        ob.shape_key_remove(kb)
        done = True
    if not nodes:
        if len(blocks) == 1 and key.get(BASIS_PROP):        # only the kit's Basis left: remove it too
            update_summary.wrote()
            ob.shape_key_clear()
            return True
        if KEY_PROP in key:                                  # the user's own keys stay; the kit stops looking
            update_summary.wrote()
            del key[KEY_PROP]
        return done
    if ours != names_:
        update_summary.wrote()
        key[KEY_PROP] = names_
    basis = blocks[0]
    rest = _co_list(basis)
    pts = rest
    order = []
    for md, kind in nodes:
        kb = blocks.get(md.name)
        if kb is None:
            update_summary.wrote()
            kb = ob.shape_key_add(name=md.name, from_mix=False)
            ob.active_shape_key_index = 0                  # point edits go to the Basis, under the shapes
            done = True
        order.append((list(blocks).index(kb), kb, md, kind))
    for _i, kb, md, kind in sorted(order, key=lambda o: o[0]):
        moved = _shape(ob, md, kind, pts)
        want = [b + (m - p) for bp, mp, pp in zip(rest, moved, pts) for b, m, p in zip(bp, mp, pp)]
        have = [c for co in _co_list(kb) for c in co]
        if kb.relative_key != basis:
            update_summary.wrote()
            kb.relative_key = basis
        if kb.value != 1.0 or kb.slider_max < 1.0:
            update_summary.wrote()
            kb.slider_max = max(kb.slider_max, 1.0)
            kb.value = 1.0
        if any(abs(a - b) > 1e-7 for a, b in zip(want, have)):
            update_summary.wrote()
            kb.data.foreach_set("co", want)
            ob.data.update_tag()
            done = True
        pts = moved
    return done


_busy = [False]


def sync_all():
    """Every object's kit nonlinear shape keys (a handler calls this on each update; with no Key datablock marked
    by the kit it reads nothing more)."""
    if _busy[0]:
        return
    users = {k.user for k in bpy.data.shape_keys if KEY_PROP in k}          # the node makes its key at once
    if not users:
        return
    _busy[0] = True
    try:
        for ob in [o for o in bpy.data.objects if o.type in ('LATTICE', 'SURFACE') and o.data in users]:
            sync(ob)
    except ReferenceError:
        pass
    finally:
        _busy[0] = False


def rows(md):
    """The Channel Box rows of such a node (Envelope first like Maya), held on its handle."""
    from .deformers import Attr
    kind = kind_of(md)
    field = "origin" if md.type == 'SIMPLE_DEFORM' else "start_position_object"
    out = []
    for name, subtype in (("Envelope", None),) + tuple((n, s) for n, _d, s in nl.KINDS[kind][1]):
        p = prop(name)
        out.append(Attr(p[len(PREFIX):], name, "ROTATION" if subtype == 'ANGLE' else "NONE",
                        lambda m, n=name: values(m)[n], lambda m, v, n=name: set_value(m, n, v),
                        ((f'{field}["{p}"]', -1),)))
    return out
