# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's Twist, Squash, Flare, Sine and Wave deformers (Deform > Nonlinear) on a mesh or a curve (#457, #461).

Like the kit bend (operators/bend_deformer.py), each one works in its handle's space: the handle's Y axis is the
length the deformer runs along. With y held between Low Bound and High Bound as t and u = (t - Low) / (High - Low)
(0 at Low Bound, 1 at High Bound):

- Twist turns the points around the handle's Y axis by Start Angle + (End Angle - Start Angle) * u.
- Flare scales X by Start Flare X + (End Flare X - Start Flare X) * u, Z the same with the Z values, both times
  1 + Curve * sin(pi * u).
- Squash stretches the length by s = 1 + Factor (Factor >= 0) or 1 / (1 - Factor) (Factor < 0): y moves by
  t * (s - 1), so the parts beyond the bounds move with the ends. The sides scale by
  1 / (1 + 2 * Expand * (sqrt(s) - 1) * g), where g is 1 at Max Expand Pos and 0 at the bounds. With w = the
  distance from Max Expand Pos towards a bound (0 to 1) and m = that side's Start / End Smoothness, g is
  (1 - m) * (sqrt(R^2 - w^2) - e) / (R - e) + m * (1 + cos(pi * w)) / 2, R = 1 + m, e = sqrt(R^2 - 1): a half
  ellipse at 0 that eases into the bound at 1. Its Envelope works between -1 and 1.
- Sine moves X by Amplitude * k * sin(2 pi (t + Offset) / Wavelength); k = 1 - Dropoff * |t| / m for a positive
  Dropoff and 1 + Dropoff * (1 - |t| / m) for a negative one, m = the larger of High Bound and -Low Bound.
- Wave moves Y by Amplitude * k * cos(2 pi (r - Min Radius + Offset) / Wavelength), r = the distance from the
  handle's Y axis held between Min Radius and Max Radius. With n = r's place between the radii (0 to 1) and x =
  its distance from Dropoff Position (scaled to 1 at the nearer end), k = 1 - Dropoff * x for a positive Dropoff and
  -Dropoff * x for a negative one.

The result is blended in by Envelope times the point's weight. The kit node is a Geometry Nodes modifier named like
the Maya node (``twist1``) on one shared node group per deformer type; a lattice or a surface (no Geometry Nodes
there) gets the same shapes as a shape key (operators/nonlinear_math.py). Angles are held in radians and shown in degrees. The weights are the
vertex group of the node's name, which Deform > Paint Weights > Nonlinear paints.
"""

import math

import bpy

VERSION_PROP = "allset_nonlinear_version"
VERSION = 2
_BOUNDS = (("Low Bound", -1.0, None), ("High Bound", 1.0, None))
# Maya node base -> (node group, [(input, default, subtype)])
KINDS = {
    "twist": (".Allset Twist", (("Start Angle", 0.0, 'ANGLE'), ("End Angle", 0.0, 'ANGLE')) + _BOUNDS),
    "squash": (".Allset Squash", (("Factor", 0.0, None), ("Expand", 1.0, None), ("Max Expand Pos", 0.5, None),
                                    ("Start Smoothness", 0.0, None), ("End Smoothness", 0.0, None)) + _BOUNDS),
    "flare": (".Allset Flare", (("Start Flare X", 1.0, None), ("Start Flare Z", 1.0, None),
                                ("End Flare X", 1.0, None), ("End Flare Z", 1.0, None), ("Curve", 0.0, None))
              + _BOUNDS),
    "sine": (".Allset Sine", (("Amplitude", 0.0, None), ("Wavelength", 2.0, None), ("Offset", 0.0, None),
                              ("Dropoff", 0.0, None)) + _BOUNDS),
    "wave": (".Allset Wave", (("Amplitude", 0.0, None), ("Wavelength", 1.0, None), ("Offset", 0.0, None),
                              ("Dropoff", 0.0, None), ("Dropoff Position", 0.0, None), ("Min Radius", 0.0, None),
                              ("Max Radius", 1.0, None))),
}
# Maya's limits of the attributes: (low, high), None = open
LIMITS = {"Envelope": (-2.0, 2.0), "Low Bound": (None, 0.0), "High Bound": (0.0, None), "Expand": (0.0, None),
          "Max Expand Pos": (0.01, 0.99), "Start Smoothness": (0.0, 1.0),
          "End Smoothness": (0.0, 1.0), "Dropoff": (-1.0, 1.0), "Dropoff Position": (0.0, 1.0),
          "Min Radius": (0.0, None), "Max Radius": (0.0, None)}
WAVELENGTH_MIN = {"sine": 0.001, "wave": 0.1}


# --- node groups ------------------------------------------------------------------------------------------------

def _clamp(b, v, lo, hi):
    return b.math('MINIMUM', b.math('MAXIMUM', v, lo), hi)


def _lerp(b, a, c, u):
    return b.math('ADD', a, b.math('MULTIPLY', b.math('SUBTRACT', c, a), u))


def _along(b, I, y):
    """(t, u): y held between the bounds, and its place between them (0 at Low Bound, 1 at High Bound)."""
    t = _clamp(b, y, I["Low Bound"], I["High Bound"])
    u = b.math('DIVIDE', b.math('SUBTRACT', t, I["Low Bound"]),
               b.math('SUBTRACT', I["High Bound"], I["Low Bound"]))       # equal bounds: 0
    return t, u


def _twist(b, I, x, y, z):
    _t, u = _along(b, I, y)
    a = _lerp(b, I["Start Angle"], I["End Angle"], u)
    s, c = b.math('SINE', a), b.math('COSINE', a)
    return (b.math('SUBTRACT', b.math('MULTIPLY', x, c), b.math('MULTIPLY', z, s)), y,
            b.math('ADD', b.math('MULTIPLY', x, s), b.math('MULTIPLY', z, c)))


def _flare(b, I, x, y, z):
    _t, u = _along(b, I, y)
    curve = b.math('ADD', 1.0, b.math('MULTIPLY', I["Curve"], b.math('SINE', b.math('MULTIPLY', u, math.pi))))
    sx = b.math('MULTIPLY', _lerp(b, I["Start Flare X"], I["End Flare X"], u), curve)
    sz = b.math('MULTIPLY', _lerp(b, I["Start Flare Z"], I["End Flare Z"], u), curve)
    return b.math('MULTIPLY', x, sx), y, b.math('MULTIPLY', z, sz)


def _squash_profile(b, I, up):
    """The bulge over ``up``: 1 at 0.5, 0 at 0 and 1, rounded off towards each end by its smoothness."""
    end = b.math('GREATER_THAN', up, 0.5)
    m = _clamp(b, _lerp(b, I["Start Smoothness"], I["End Smoothness"], end), 0.0, 1.0)
    w = b.math('MULTIPLY', b.math('ABSOLUTE', b.math('SUBTRACT', up, 0.5)), 2.0)
    r = b.math('ADD', m, 1.0)
    e = b.math('SQRT', b.math('MULTIPLY', m, b.math('ADD', m, 2.0)))
    arc = b.math('SQRT', b.math('MAXIMUM', b.math('SUBTRACT', b.math('MULTIPLY', r, r), b.math('MULTIPLY', w, w)),
                                0.0))
    ellipse = b.math('DIVIDE', b.math('SUBTRACT', arc, e), b.math('SUBTRACT', r, e))
    ease = b.math('MULTIPLY', b.math('ADD', b.math('COSINE', b.math('MULTIPLY', w, math.pi)), 1.0), 0.5)
    return _lerp(b, ellipse, ease, m)


def _squash(b, I, x, y, z):
    t, u = _along(b, I, y)
    f = I["Factor"]
    s = b.math('MULTIPLY', b.math('ADD', 1.0, b.math('MAXIMUM', f, 0.0)),
               b.math('DIVIDE', 1.0, b.math('SUBTRACT', 1.0, b.math('MINIMUM', f, 0.0))))
    y2 = b.math('ADD', y, b.math('MULTIPLY', t, b.math('SUBTRACT', s, 1.0)))
    m = _clamp(b, I["Max Expand Pos"], 0.01, 0.99)
    up = b.math('POWER', u, b.math('LOGARITHM', 0.5, m))               # the widest point moves to Max Expand Pos
    g = _squash_profile(b, I, up)
    k = b.math('MULTIPLY', b.math('MULTIPLY', b.math('MULTIPLY', I["Expand"], 2.0),
                                  b.math('SUBTRACT', b.math('SQRT', s), 1.0)), g)
    side = b.math('DIVIDE', 1.0, b.math('ADD', 1.0, k))
    return b.math('MULTIPLY', x, side), y2, b.math('MULTIPLY', z, side)


def _sine(b, I, x, y, z):
    t, _u = _along(b, I, y)
    d = I["Dropoff"]
    reach = b.math('MAXIMUM', I["High Bound"], b.math('MULTIPLY', I["Low Bound"], -1.0))
    n = b.math('DIVIDE', b.math('ABSOLUTE', t), reach)
    k = b.math('ADD', b.math('SUBTRACT', 1.0, b.math('MULTIPLY', d, n)), b.math('MINIMUM', d, 0.0))
    wl = b.math('MAXIMUM', I["Wavelength"], WAVELENGTH_MIN["sine"])
    phase = b.math('MULTIPLY', b.math('DIVIDE', b.math('ADD', t, I["Offset"]), wl), 2.0 * math.pi)
    amp = b.math('MULTIPLY', I["Amplitude"], k)
    return b.math('ADD', x, b.math('MULTIPLY', amp, b.math('SINE', phase))), y, z


def _wave(b, I, x, y, z):
    lo, hi = I["Min Radius"], I["Max Radius"]
    r = b.math('SQRT', b.math('ADD', b.math('MULTIPLY', x, x), b.math('MULTIPLY', z, z)))
    rc = _clamp(b, r, lo, hi)
    n = b.math('DIVIDE', b.math('SUBTRACT', rc, lo), b.math('SUBTRACT', hi, lo))
    pos = _clamp(b, I["Dropoff Position"], 0.0, 1.0)
    above = b.math('DIVIDE', b.math('MAXIMUM', b.math('SUBTRACT', n, pos), 0.0), b.math('SUBTRACT', 1.0, pos))
    below = b.math('DIVIDE', b.math('MAXIMUM', b.math('SUBTRACT', pos, n), 0.0), pos)
    dist = b.math('ADD', above, below)
    d = I["Dropoff"]
    k = b.math('SUBTRACT', b.math('GREATER_THAN', d, -1e-12), b.math('MULTIPLY', d, dist))
    wl = b.math('MAXIMUM', I["Wavelength"], WAVELENGTH_MIN["wave"])
    phase = b.math('MULTIPLY', b.math('DIVIDE', b.math('ADD', b.math('SUBTRACT', rc, lo), I["Offset"]), wl),
                   2.0 * math.pi)
    amp = b.math('MULTIPLY', I["Amplitude"], k)
    return x, b.math('ADD', y, b.math('MULTIPLY', amp, b.math('COSINE', phase))), z


_SHAPES = {"twist": _twist, "flare": _flare, "squash": _squash, "sine": _sine, "wave": _wave}


def build_group(kind):
    from .wire_deformer import _B
    name, inputs = KINDS[kind]
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    ng[VERSION_PROP] = VERSION
    ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Handle", in_out='INPUT', socket_type='NodeSocketObject')
    for sname, default, subtype in inputs + (("Envelope", 1.0, None), ("Weight", 1.0, None)):
        s = ng.interface.new_socket(sname, in_out='INPUT', socket_type='NodeSocketFloat')
        s.default_value = default
        if subtype:
            s.subtype = subtype
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    b = _B(ng)
    gin = b.node("NodeGroupInput")
    gout = b.node("NodeGroupOutput")
    I = gin.outputs                                             # noqa: E741
    info = b.node("GeometryNodeObjectInfo", transform_space='RELATIVE')
    b.link(I["Handle"], info.inputs["Object"])
    to_handle = b.node("FunctionNodeInvertMatrix")
    b.link(info.outputs["Transform"], to_handle.inputs["Matrix"])
    p = b.node("GeometryNodeInputPosition").outputs[0]
    local = b.node("FunctionNodeTransformPoint")
    b.link(p, local.inputs["Vector"])
    b.link(to_handle.outputs["Matrix"], local.inputs["Transform"])
    sep = b.node("ShaderNodeSeparateXYZ")
    b.link(local.outputs["Vector"], sep.inputs[0])
    # the kit handle's local +X / +Z / -Y are Maya's X / Y / Z
    mz = b.math('MULTIPLY', sep.outputs["Y"], -1.0)
    x2, y2, z2 = _SHAPES[kind](b, I, sep.outputs["X"], sep.outputs["Z"], mz)
    comb = b.node("ShaderNodeCombineXYZ")
    b._in(comb.inputs[0], x2)
    b._in(comb.inputs[1], b.math('MULTIPLY', z2, -1.0))
    b._in(comb.inputs[2], y2)
    back = b.node("FunctionNodeTransformPoint")
    b.link(comb.outputs[0], back.inputs["Vector"])
    b.link(info.outputs["Transform"], back.inputs["Transform"])
    env = I["Envelope"] if kind != "squash" else _clamp(b, I["Envelope"], -1.0, 1.0)
    amount = b.math('MULTIPLY', env, I["Weight"])
    offset = b.vmath('SCALE', b.vmath('SUBTRACT', back.outputs["Vector"], p), scale=amount)
    sp = b.node("GeometryNodeSetPosition")
    b.link(I["Geometry"], sp.inputs["Geometry"])
    b.link(offset, sp.inputs["Offset"])
    b.link(sp.outputs["Geometry"], gout.inputs[0])
    return ng


def group(kind):
    name = KINDS[kind][0]
    ng = bpy.data.node_groups.get(name)
    if ng is not None and ng.bl_idname == 'GeometryNodeTree' and ng.get(VERSION_PROP) == VERSION:
        return ng
    if ng is not None:
        ng.name = name + ".old"
    return build_group(kind)


# --- modifier inputs ------------------------------------------------------------------------------------------

def kind_of(md):
    """``twist`` / ``squash`` / ``flare`` / ``sine`` / ``wave`` for a kit nonlinear node modifier, else None."""
    if md.type != 'NODES' or md.node_group is None:
        return None
    n = md.node_group.name
    return next((k for k, (g, _i) in KINDS.items() if n == g or n.startswith(g + ".")), None)


def is_nonlinear(md):
    return kind_of(md) is not None


def handle_of(md):
    from . import wire_deformer
    return wire_deformer.get(md, "Handle") if is_nonlinear(md) else None


def limited(kind, name, value):
    """``value`` held to Maya's limits of attribute ``name``."""
    v = float(value)
    lo, hi = LIMITS.get(name, (None, None))
    if name == "Wavelength":
        lo = WAVELENGTH_MIN.get(kind)
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def add(ob, name, kind, handle, group_name, values=None):
    """Kit nonlinear ``kind`` named ``name`` on ``ob`` driven by empty ``handle``; ``values`` = {input: Maya value}
    (angles in radians), weights = vertex group ``group_name`` (none: every point at weight 1)."""
    from . import wire_deformer
    from .. import compat
    md = ob.modifiers.new(name, 'NODES')
    md.node_group = group(kind)
    wire_deformer.set_(md, "Handle", handle)
    for key, v in (values or {}).items():
        wire_deformer.set_(md, key, limited(kind, key, v))
    if group_name:
        compat.gn_input_attribute(md, wire_deformer.ident(md, "Weight"), group_name)
    return md


def draw_ae(layout, md):
    """Draw a kit nonlinear node's Maya attributes in its Attribute Editor tab; False for other modifiers."""
    kind = kind_of(md)
    if kind is None:
        return False
    from . import wire_deformer
    from .. import compat
    for name in ("Envelope",) + tuple(n for n, _d, _s in KINDS[kind][1]):
        key = wire_deformer.ident(md, name)
        if key is None:
            continue
        if compat.GN_INPUT_STRUCT:
            item = compat._gn_input(md, key)
            if item is not None:
                layout.prop(item, "value", text=name)
        else:
            layout.prop(md, f'["{key}"]', text=name)
    return True
