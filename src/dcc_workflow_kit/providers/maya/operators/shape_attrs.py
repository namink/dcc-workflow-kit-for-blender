# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya shape attributes the kit keeps itself, for the Channel Box SHAPES rows of cameras, lights and locators.

- Camera: Lens Squeeze Ratio, Shutter Angle (degrees) and Center Of Interest (scene length units) are values of the
  camera data; Blender's camera, render and view keep their own settings (they don't follow these rows).
- Point / directional / spot / area light: Shad Color R / G / B, Use Depth Map Shadows, Dmap Bias and the spot light's Dropoff
  are values of the light data; Blender's shadows and falloff stay Blender's own.
- Locator (a kit Empty, ``create.LOCATOR_PROP``): Local Position X / Y / Z is the Empty's delta location (where the
  command line's ``spaceLocator -p`` puts it, so the locator draws there); Local Scale X / Y / Z is kept on the
  object and the Empty's display size follows its largest axis (a Blender Empty draws with one size).
Every value starts like Maya's new node.
"""

import bpy
from bpy.props import BoolProperty, FloatProperty, FloatVectorProperty

# Camera data
LENS_SQUEEZE = "allset_lens_squeeze_ratio"
SHUTTER_ANGLE = "allset_shutter_angle"
CENTER_OF_INTEREST = "allset_center_of_interest"
# Light data (point, directional, spot, area); Dropoff only on spot lights
SHADOW_COLOR = "allset_shadow_color"
DEPTH_MAP = "allset_use_depth_map_shadows"
DMAP_BIAS = "allset_dmap_bias"
DROPOFF = "allset_dropoff"
# Locator object
LOCAL_SCALE = "allset_local_scale"
LOCATOR_SIZE = "allset_locator_size"     # display size at Local Scale 1 (kept while Local Scale is 0)

LIGHT_TYPES = ("PointLight", "SunLight", "SpotLight", "AreaLight")


def _light_classes():
    return [getattr(bpy.types, n) for n in LIGHT_TYPES]


def register_props():
    bpy.types.Camera.allset_lens_squeeze_ratio = FloatProperty(
        name="Lens Squeeze Ratio", default=1.0, min=1e-10, soft_max=4.0, precision=3,
        description="Lens Squeeze Ratio of the camera, like Maya (kept by the kit; Blender's camera doesn't use it)")
    bpy.types.Camera.allset_shutter_angle = FloatProperty(
        name="Shutter Angle", default=144.0, precision=3,
        description="Shutter Angle in degrees, like Maya (kept by the kit; Blender's motion blur is a render "
                    "setting)")
    bpy.types.Camera.allset_center_of_interest = FloatProperty(
        name="Center Of Interest", default=5.0, min=1e-10, precision=3,
        description="Center Of Interest in scene units, like Maya (kept by the kit)")
    for cls in _light_classes():
        cls.allset_shadow_color = FloatVectorProperty(
            name="Shad Color", subtype='COLOR', size=3, default=(0.0, 0.0, 0.0), min=0.0, soft_max=1.0,
            description="Shadow color, like Maya (kept by the kit; Blender's shadows are black)")
        cls.allset_use_depth_map_shadows = BoolProperty(
            name="Use Depth Map Shadows", default=False,
            description="Use Depth Map Shadows, like Maya (kept by the kit; Blender's shadows are its own)")
        cls.allset_dmap_bias = FloatProperty(
            name="Dmap Bias", default=0.001, soft_min=1e-5, soft_max=1.0, precision=3,
            description="Depth map shadow bias, like Maya (kept by the kit)")
    bpy.types.SpotLight.allset_dropoff = FloatProperty(
        name="Dropoff", default=0.0, min=0.0, precision=3,
        description="Spot light Dropoff, like Maya (kept by the kit; Blender's spot blend is the Penumbra Angle)")


def unregister_props():
    for prop in (LENS_SQUEEZE, SHUTTER_ANGLE, CENTER_OF_INTEREST):
        if hasattr(bpy.types.Camera, prop):
            delattr(bpy.types.Camera, prop)
    for cls in _light_classes():
        for prop in (SHADOW_COLOR, DEPTH_MAP, DMAP_BIAS):
            if hasattr(cls, prop):
                delattr(cls, prop)
    if hasattr(bpy.types.SpotLight, DROPOFF):
        delattr(bpy.types.SpotLight, DROPOFF)


# --- light Shad Color R / G / B rows ---------------------------------------------------------------------------------

def shadow_color_attrs():
    """Shad Color R / G / B as three channels of the kept colour (Channel Box SHAPES ``maya:shadColorR`` ...)."""
    from .deformers import Attr
    out = []
    for i, c in enumerate("RGB"):
        def get(light, i=i):
            return getattr(light, SHADOW_COLOR)[i]

        def set_(light, v, i=i):
            getattr(light, SHADOW_COLOR)[i] = max(0.0, float(v))
        a = Attr(f"shadColor{c}", f"Shad Color {c}", "NONE", get, set_, ((SHADOW_COLOR, i),))
        a.light_types = LIGHT_TYPES
        out.append(a)
    return out


# --- locator Local Position / Local Scale rows ------------------------------------------------------------------------

def is_locator(ob):
    from . import create
    return isinstance(ob, bpy.types.Object) and ob.type == 'EMPTY' and bool(ob.get(create.LOCATOR_PROP))


def local_scale(ob):
    v = ob.get(LOCAL_SCALE)
    try:
        return [float(v[0]), float(v[1]), float(v[2])]
    except (TypeError, IndexError, KeyError, ValueError):
        return [1.0, 1.0, 1.0]


def set_local_scale(ob, axis, value):
    """Local Scale ``axis`` = ``value``; the Empty's display size = its size at Local Scale 1 x the largest axis."""
    old = local_scale(ob)
    new = list(old)
    new[axis] = float(value)
    f_old = max(abs(x) for x in old)
    if f_old > 1e-9:
        base = ob.empty_display_size / f_old
    else:
        base = float(ob.get(LOCATOR_SIZE, ob.empty_display_size))
    ob[LOCATOR_SIZE] = base
    ob[LOCAL_SCALE] = new
    f_new = max(abs(x) for x in new)
    ob.empty_display_size = max(base * f_new, 1e-4)


def locator_attrs():
    """Local Position X / Y / Z (delta location, a length) and Local Scale X / Y / Z: Channel Box SHAPES rows
    ``maya:localPositionX`` ... of a locator. Like Maya they are not keyable (no ``paths``)."""
    from .deformers import Attr
    out = []
    for i, a in enumerate("XYZ"):
        def get_p(ob, i=i):
            return ob.delta_location[i]

        def set_p(ob, v, i=i):
            ob.delta_location[i] = float(v)
        out.append(Attr(f"localPosition{a}", f"Local Position {a}", "LENGTH", get_p, set_p))
    for i, a in enumerate("XYZ"):
        def get_s(ob, i=i):
            return local_scale(ob)[i]

        def set_s(ob, v, i=i):
            set_local_scale(ob, i, v)
        out.append(Attr(f"localScale{a}", f"Local Scale {a}", "NONE", get_s, set_s))
    return out


def locator_attr(name, ob):
    if not is_locator(ob):
        return None
    for a in locator_attrs():
        if name == "maya:" + a.key:
            return a
    return None
