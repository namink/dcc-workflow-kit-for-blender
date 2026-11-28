# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya light shape channels on Blender lights: Color R / G / B, Use Ray Trace Shadows, the spot light's Cone Angle
/ Penumbra Angle and the kept Shad Color R / G / B (operators/shape_attrs.py) as Channel Box SHAPES rows
(``channel_attrs``).

A light's power, its falloff and its other values are Blender's own: a new light has Blender's values, and the
Intensity place of the Channel Box and the Attribute Editor shows Blender's Power (a sun: Strength).
"""

import math


def _color(i):
    def get(light):
        return light.color[i]

    def set_(light, v):
        light.color[i] = max(0.0, float(v))
    return get, set_


PENUMBRA_PROP = "allset_penumbra"     # Maya penumbra angle (degrees) last written: tells a negative penumbra apart


def cone_penumbra(light):
    """(Maya coneAngle, penumbraAngle) in degrees from Blender's spot: a positive penumbra widens the
    cone outward (size = cone + 2p, blend = 2p / size), a negative one softens inward (size = cone, blend = 2|p| / cone)."""
    size = math.degrees(light.spot_size)
    soft = light.spot_blend * size / 2.0
    p = light.get(PENUMBRA_PROP)
    if isinstance(p, (int, float)) and p < 0 and abs(abs(p) - soft) < 1e-3:
        return size, float(p)
    return size - 2.0 * soft, soft


def set_cone_penumbra(light, cone=None, penumbra=None):
    c0, p0 = cone_penumbra(light)
    cone = c0 if cone is None else max(0.006, float(cone))
    p = p0 if penumbra is None else float(penumbra)
    size = cone + 2.0 * max(p, 0.0)
    size = min(180.0, max(1.0, size))
    light.spot_size = math.radians(size)
    light.spot_blend = min(1.0, 2.0 * abs(p) / size) if size > 0 else 0.0
    light[PENUMBRA_PROP] = p


def _cone():
    def get(light):
        return cone_penumbra(light)[0]

    def set_(light, v):
        set_cone_penumbra(light, cone=v)
    return get, set_


def _penumbra():
    def get(light):
        return cone_penumbra(light)[1]

    def set_(light, v):
        set_cone_penumbra(light, penumbra=v)
    return get, set_


def _shadow_get(light):
    return light.use_shadow


def _shadow_set(light, v):
    light.use_shadow = bool(v)


def channel_attrs(light=None):
    """Maya light shape channels Blender keeps differently (keyable attributes): Color R / G / B
    (one colour vector), Use Ray Trace Shadows (the light's shadow switch), spot Cone Angle / Penumbra Angle
    (``spot_size`` + ``spot_blend``) — Channel Box SHAPES rows
    ``maya:colorR`` ... (ui/cb_inputs._virtual). ``paths`` = the Blender properties a key on the row keys."""
    from .deformers import Attr
    out = []
    for i, c in enumerate("RGB"):
        a = Attr(f"color{c}", f"Color {c}", "NONE", *_color(i))
        a.paths = (("color", i),)
        out.append(a)
    a = Attr("useRayTraceShadows", "Use Ray Trace Shadows", "BOOL", _shadow_get, _shadow_set)
    a.paths = (("use_shadow", -1),)
    out.append(a)
    for key, label, fns in (("coneAngle", "Cone Angle", _cone()), ("penumbraAngle", "Penumbra Angle", _penumbra())):
        a = Attr(key, label, "NONE", *fns)
        a.paths = (("spot_size", -1), ("spot_blend", -1))
        a.spot_only = True
        out.append(a)
    from . import shape_attrs
    out += shape_attrs.shadow_color_attrs()     # Shad Color R / G / B, kept by the kit
    return out


def channel_attr(name, light=None):
    for a in channel_attrs():
        if name == "maya:" + a.key:
            if getattr(a, "spot_only", False) and light is not None and light.type != 'SPOT':
                return None
            types = getattr(a, "light_types", None)
            if types is not None and light is not None and type(light).__name__ not in types:
                return None
            return a
    return None
