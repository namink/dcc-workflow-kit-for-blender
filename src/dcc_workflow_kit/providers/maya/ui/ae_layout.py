# SPDX-License-Identifier: GPL-3.0-or-later
"""Attribute Editor sections: Maya template sections -> Blender properties (data only).

Section names and open/closed state follow Maya's Attribute Editor templates
(``collapse`` flag of each Attribute Editor section; Maya sections
without a flag start collapsed); rows are the Blender properties that play
the part of the Maya attributes. Maya
attributes with no Blender counterpart (shear, rotateAxis, tessellation, depth
map shadows, Node Behavior, UUID, ...) are left out.

Row forms:
  ("prop", owner, attr, label)   owner: "ob" | "data" | "view" (3D View space); joints (pose bones):
                                 "ob" = the pose bone, "bone" = its Bone, "arm" = the Armature data,
                                 "armob" = the armature object
  ("draw", name)                 custom drawer in ui/ae_rows.py
  ("socket", input name, label)  Principled BSDF input (material tabs), with the Maya map button
  ("maya", material prop, label, input name)  a value stored through a Material property (get/set) that edits that
                                 input, with the input's map button
  ("missing", label, note)       Maya attribute Blender doesn't have: a greyed row with the note

``TEMPLATE`` names the Maya Attribute Editor template a section list follows
(tests/test_step11_outliner_ae.py); ``None`` = no Maya template.
"""


class Section:
    __slots__ = ("name", "open", "rows", "subs")

    def __init__(self, name, open_, rows=(), subs=()):
        self.name = name
        self.open = open_
        self.rows = list(rows)
        self.subs = list(subs)


def S(name, open_, *rows, subs=()):
    return Section(name, open_, rows, subs)


# Maya Drawing Overrides colour (overrideEnabled / overrideRGBColors / overrideColor / overrideColorRGB): RNA over the
# kit's ID properties, operators/wire_color.py. Objects and
# joints (pose bones) both have them. Object.color is written by the kit from these, so it has no row of its own.
_DRAWING_OVERRIDES = (
    ("prop", "ob", "allset_override_enabled", "Enable Overrides"),
    ("prop", "ob", "allset_override_mode", "Color"),
    ("prop", "ob", "allset_override_index", "Color Index"),
    ("prop", "ob", "allset_override_color", "Color"),
)

# --- transform (Maya Attribute Editor transform tab) ------------------------------------
TRANSFORM = [
    S("Transform Attributes", True,                                          # collapse=0
      ("draw", "transform_channels"),
      ("prop", "ob", "rotation_mode", "Rotate Order")),
    S("Pivots", False, subs=[
        S("Local Space", False, ("prop", "ob", "delta_location", "Pivot Offset")),
        S("World Space", True, ("draw", "world_pivot")),                    # collapse=0
    ]),
    S("Limit Information", False, subs=[
        S("Translate", False, ("draw", "limit:LIMIT_LOCATION")),
        S("Rotate", True, ("draw", "limit:LIMIT_ROTATION")),                # collapse=0
        S("Scale", False, ("draw", "limit:LIMIT_SCALE")),
    ]),
    S("Display", False,
      ("draw", "visibility"),
      ("prop", "ob", "show_axis", "Display Local Axis"),
      ("prop", "ob", "hide_select", "Template (unselectable)"),
      ("prop", "ob", "show_in_front", "Always Draw On Top"),
      ("prop", "ob", "show_name", "Display Name"),
      subs=[
          S("Bounding Box Information", False,
            ("prop", "ob", "show_bounds", "Display Bounding Box"),
            ("prop", "ob", "display_bounds_type", "Bounds Type")),
          S("Drawing Overrides", False,                                     # collapse=1
            ("prop", "ob", "display_type", "Display Type"),
            *_DRAWING_OVERRIDES),
      ]),
]

# --- mesh shape (Maya Attribute Editor mesh shape tab) ---------------------------------
MESH = [
    S("Mesh Component Display", False,
      ("prop", "ob", "show_wire", "Wireframe on Shaded"),
      ("prop", "ob", "show_all_edges", "Display All Edges"),
      ("prop", "view", "overlay.show_face_normals", "Display Normals (Face)"),
      ("prop", "view", "overlay.show_vertex_normals", "Display Normals (Vertex)"),
      ("prop", "view", "overlay.normals_length", "Normal Size")),
    S("Mesh Controls", False, ("draw", "shading")),
    S("Smooth Mesh", False, ("draw", "smooth_mesh")),
    S("Render Stats", False,
      ("prop", "ob", "visible_camera", "Primary Visibility"),
      ("prop", "ob", "visible_shadow", "Casts Shadows"),
      ("prop", "ob", "visible_diffuse", "Visible in Diffuse"),
      ("prop", "ob", "visible_glossy", "Visible in Reflections"),
      ("prop", "ob", "visible_transmission", "Visible in Refractions"),
      ("prop", "ob", "visible_volume_scatter", "Visible in Volume"),
      ("prop", "ob", "hide_render", "Hide in Render")),
    S("Object Display", False,
      ("prop", "ob", "display_type", "Display Type")),
]

# --- camera (Maya Attribute Editor camera tab) -----------------------------------------
CAMERA = [
    S("Camera Attributes", True,
      ("prop", "data", "lens", "Focal Length"),
      ("prop", "data", "clip_start", "Near Clip Plane"),
      ("prop", "data", "clip_end", "Far Clip Plane")),
    S("Film Back", True,
      ("prop", "data", "allset_film_aperture_h", "Horizontal Film Aperture"),    # inches (operators/film_fit.py)
      ("prop", "data", "allset_film_aperture_v", "Vertical Film Aperture"),
      ("prop", "data", "allset_film_fit", "Fit Resolution Gate"),     # Maya Fill / Horizontal / Vertical / Overscan
      ("prop", "data", "shift_x", "Film Offset X"),
      ("prop", "data", "shift_y", "Film Offset Y")),
    S("Depth of Field", False,
      ("prop", "data", "dof.use_dof", "Depth of Field"),
      ("prop", "data", "dof.focus_distance", "Focus Distance"),
      ("prop", "data", "dof.aperture_fstop", "F Stop")),
    S("Output Settings", False,
      ("prop", "data", "allset_renderable", "Renderable")),     # operators/render_cameras.py
    S("Display Options", False,
      ("prop", "data", "show_limits", "Display Near/Far Clip"),
      ("prop", "data", "show_passepartout", "Display Film Gate Mask"),
      ("prop", "data", "passepartout_alpha", "Gate Mask Opacity"),
      ("prop", "data", "allset_overscan", "Overscan"),
      ("prop", "data", "display_size", "Locator Scale")),
    S("Orthographic Views", False,
      ("prop", "data", "type", "Projection"),
      ("prop", "data", "ortho_scale", "Orthographic Width")),
]

# --- lights (Maya Attribute Editor point / directional light tabs) ----------------------
def _light_main(power):
    """Type, Color, then Blender's Power (a sun: Strength) where Maya has Intensity, Emit Diffuse / Specular."""
    return (("prop", "data", "type", "Type"),
            ("prop", "data", "color", "Color"),
            ("prop", "data", "energy", power),
            ("prop", "data", "diffuse_factor", "Emit Diffuse"),
            ("prop", "data", "specular_factor", "Emit Specular"))


_LIGHT_MAIN = _light_main("Power")
# Maya's Decay Rate: Blender lights fall off with the square of the distance
_DECAY = ("missing", "Decay Rate", "Blender lights fall off with distance squared; in Cycles a Light Falloff node "
                                   "in the light's node tree (Shader Editor) changes it")


def _render_engine(*rows):
    """The render engine's own light attributes, in a section of their own like Maya's renderer section of a light
    (Exposure, Normalize, Spread, Max Bounces): Blender's light settings that have no Maya attribute above."""
    return S("Cycles", False,
             ("prop", "data", "exposure", "Exposure"),
             ("prop", "data", "normalize", "Normalize"), *rows,
             ("prop", "data", "cycles.max_bounces", "Max Bounces"),
             ("prop", "data", "cycles.use_multiple_importance_sampling", "Multiple Importance"),
             ("prop", "data", "cycles.is_caustics_light", "Shadow Caustics"))


_SOFT_FALLOFF = ("prop", "data", "use_soft_falloff", "Soft Falloff")
POINT_LIGHT = [
    S("Point Light Attributes", True, *_LIGHT_MAIN, _DECAY),
    S("Shadows", False, ("prop", "data", "use_shadow", "Use Shadows"), subs=[
        S("Raytrace Shadow Attributes", True, ("prop", "data", "shadow_soft_size", "Light Radius")),
    ]),
    _render_engine(_SOFT_FALLOFF),
]
DIRECTIONAL_LIGHT = [
    S("Directional Light Attributes", True, *_light_main("Strength")),
    S("Shadows", False, ("prop", "data", "use_shadow", "Use Shadows"), subs=[
        S("Raytrace Shadow Attributes", True, ("prop", "data", "angle", "Light Angle")),
    ]),
    _render_engine(),
]
# Spot and area lights: Maya's layout is the point light's.
SPOT_LIGHT = [
    S("Spot Light Attributes", True, *_LIGHT_MAIN,
      ("prop", "data", "spot_size", "Cone Angle"),
      ("prop", "data", "spot_blend", "Penumbra"), _DECAY),
    S("Shadows", False, ("prop", "data", "use_shadow", "Use Shadows"),
      ("prop", "data", "shadow_soft_size", "Light Radius")),
    _render_engine(_SOFT_FALLOFF),
]
AREA_LIGHT = [
    S("Area Light Attributes", True, *_LIGHT_MAIN,
      ("prop", "data", "shape", "Shape"),
      ("prop", "data", "size", "Size"), _DECAY),
    S("Shadows", False, ("prop", "data", "use_shadow", "Use Shadows")),
    _render_engine(("prop", "data", "spread", "Spread"), ("prop", "data", "cycles.is_portal", "Portal")),
]

# --- material: Blender's Principled BSDF, its inputs by Blender's names in the order of Blender's material panel --
# (Maya Attribute Editor tab layout: open / closed sections, map buttons, Break Connection). Diffuse shows only on a
# material made by an older kit version (its "Maya Diffuse" node, operators/material.py).
PRINCIPLED = [
    S("Base", True, ("socket", "Base Color", "Base Color"), ("socket", "Metallic", "Metallic"),
      ("socket", "Roughness", "Roughness"), ("socket", "IOR", "IOR"), ("socket", "Alpha", "Alpha"),
      ("socket", "Thin Wall", "Thin Wall"), ("socket", "Normal", "Normal"),("maya", "allset_diffuse", "Diffuse", "Diffuse")),
    S("Diffuse", False, ("socket", "Diffuse Roughness", "Roughness")),
    S("Subsurface", False, ("socket", "Subsurface Weight", "Weight"),
      ("socket", "Subsurface Radius", "Radius"), ("socket", "Subsurface Scale", "Scale"),
      ("socket", "Subsurface Anisotropy", "Anisotropy")),
    S("Specular", False, ("socket", "Specular IOR Level", "IOR Level"),
      ("socket", "Specular Tint", "Tint"), ("socket", "Anisotropic", "Anisotropic"),
      ("socket", "Anisotropic Rotation", "Anisotropic Rotation"), ("socket", "Tangent", "Tangent")),
    S("Transmission", False, ("socket", "Transmission Weight", "Weight")),
    S("Coat", False, ("socket", "Coat Weight", "Weight"), ("socket", "Coat Roughness", "Roughness"),
      ("socket", "Coat IOR", "IOR"), ("socket", "Coat Tint", "Tint"), ("socket", "Coat Normal", "Normal")),
    S("Sheen", False, ("socket", "Sheen Weight", "Weight"), ("socket", "Sheen Roughness", "Roughness"),
      ("socket", "Sheen Tint", "Tint")),
    S("Emission", False, ("socket", "Emission Color", "Color"), ("socket", "Emission Strength", "Strength")),
    S("Thin Film", False, ("socket", "Thin Film Thickness", "Thickness"), ("socket", "Thin Film IOR", "IOR")),
]

# standardSurface / aiStandardSurface attribute -> Principled BSDF input: the names the command line's getAttr /
# setAttr take for a material (names from the public Standard Surface spec; aiStandardSurface uses the same names).
# None = no Principled input.
STANDARD_SURFACE_ATTRS = (
    ("base", "Weight"), ("baseColor", "Base Color"), ("diffuseRoughness", "Diffuse Roughness"),
    ("metalness", "Metallic"), ("specular", "Specular IOR Level"), ("specularColor", "Specular Tint"),
    ("specularRoughness", "Roughness"), ("specularIOR", "IOR"), ("specularAnisotropy", "Anisotropic"),
    ("specularRotation", "Anisotropic Rotation"), ("transmission", "Transmission Weight"),
    ("transmissionColor", None), ("transmissionDepth", None),
    ("subsurface", "Subsurface Weight"), ("subsurfaceColor", None), ("subsurfaceRadius", "Subsurface Radius"),
    ("subsurfaceScale", "Subsurface Scale"), ("subsurfaceAnisotropy", "Subsurface Anisotropy"),
    ("coat", "Coat Weight"), ("coatColor", "Coat Tint"), ("coatRoughness", "Coat Roughness"),
    ("coatIOR", "Coat IOR"), ("coatNormal", "Coat Normal"),
    ("sheen", "Sheen Weight"), ("sheenColor", "Sheen Tint"), ("sheenRoughness", "Sheen Roughness"),
    ("emission", "Emission Strength"), ("emissionColor", "Emission Color"),
    ("thinFilmThickness", "Thin Film Thickness"), ("thinFilmIOR", "Thin Film IOR"),
    ("opacity", "Alpha"), ("normalCamera", "Normal"), ("thinWalled", None),
)
MAYA_ATTR = {socket: attr for attr, socket in STANDARD_SURFACE_ATTRS if socket}
# Material without nodes: Blender viewport values (no Maya template).
# --- joint = pose bone (Maya Attribute Editor) ----
# Joint Labelling (side / type) and Preferred Angle have no Blender counterpart.
JOINT = [
    S("Transform Attributes", True,                                          # collapse=0
      ("draw", "transform_channels"),
      ("prop", "ob", "rotation_mode", "Rotate Order")),
    S("Joint", True,                                                         # collapse=0
      ("prop", "arm", "display_type", "Draw Style"),
      ("draw", "joint_stiffness"),
      ("draw", "joint_orient"),
      ("prop", "bone", "allset_ssc", "Segment Scale Compensate")),       # Maya's check box
    S("Limit Information", False, subs=[
        S("Translate", False, ("draw", "limit:LIMIT_LOCATION")),
        S("Rotate", True, ("draw", "limit:LIMIT_ROTATION")),                # collapse=0
        S("Scale", False, ("draw", "limit:LIMIT_SCALE")),
    ]),
    S("Display", False,
      ("draw", "visibility"),
      ("prop", "arm", "show_axes", "Display Local Axis"),
      ("prop", "armob", "show_in_front", "Always Draw On Top"),
      ("prop", "ob", "custom_shape", "Display as Control Shape"),
      subs=[S("Drawing Overrides", False, *_DRAWING_OVERRIDES)]),         # collapse=1
]

PLAIN_MATERIAL = [
    S("Common Material Attributes", True,
      ("prop", "data", "diffuse_color", "Color"),
      ("prop", "data", "metallic", "Metalness"),
      ("prop", "data", "roughness", "Roughness")),
]

# --- type (Maya Type tool node) -> Blender text object data ------------------------------------------------------
TYPE = [
    S("Text", True,
      ("prop", "data", "body", "Text"),
      ("prop", "data", "font", "Font"),
      ("prop", "data", "font_bold", "Bold Font"),
      ("prop", "data", "font_italic", "Italic Font"),
      ("prop", "data", "size", "Font Size"),
      ("prop", "data", "align_x", "Alignment"),
      ("prop", "data", "space_character", "Tracking"),
      ("prop", "data", "space_line", "Leading"),
      ("prop", "data", "space_word", "Word Spacing"),
      ("prop", "data", "shear", "Slant"),
      ("draw", "type_manipulator"),
      ("missing", "Kerning", "Blender sets kerning per character in text edit mode (Alt+Left / Alt+Right).")),
    S("Geometry", True,
      ("prop", "data", "extrude", "Extrude Distance"),
      ("prop", "data", "offset", "Extrude Offset"),
      ("prop", "data", "bevel_depth", "Bevel Distance"),
      ("prop", "data", "bevel_resolution", "Bevel Divisions"),
      ("prop", "data", "resolution_u", "Curve Resolution")),
    S("Generator", False,
      ("missing", "Generator", "Blender text has no generator mode (Python expressions, time code, frame "
                               "numbers): type the text, or drive it with a Python script.")),
    S("Texturing", False,
      ("missing", "Texturing", "Assign materials to the text object; Blender has no per-type caps / bevel "
                               "material slots like Maya's type texturing.")),
    S("Animation", False,
      ("missing", "Animation", "Blender has no per-character type animation: animate the object, or convert the "
                               "text to a mesh (Modify > Convert) and animate that.")),
]

# --- image plane (a Blender image empty; the kit's View > Image Plane, Create > Free Image Plane) ------------------
IMAGE_PLANE = [
    S("Image Plane Attributes", True,
      ("prop", "ob", "allset_image_plane_display", "Display Mode"),
      ("prop", "data", "filepath", "Image Name"),
      ("prop", "ob", "allset_alpha_gain", "Alpha Gain")),          # #436: see-through reference images
]

# Tab type of a material with a Principled BSDF (new materials and those of older kit versions alike)
PRINCIPLED_TYPE = "Principled BSDF"

# (sections, Maya template name or None)
BY_KIND = {
    "IMAGE_PLANE": (IMAGE_PLANE, None),
    "FONT": (TYPE, None),
    "transform": (TRANSFORM, "transform"),
    "joint": (JOINT, "joint"),
    "MESH": (MESH, "mesh"),
    "CAMERA": (CAMERA, "camera"),
    "POINT": (POINT_LIGHT, "pointLight"),
    "SUN": (DIRECTIONAL_LIGHT, "directionalLight"),
    "SPOT": (SPOT_LIGHT, None),
    "AREA": (AREA_LIGHT, None),
    PRINCIPLED_TYPE: (PRINCIPLED, None),
    "material": (PLAIN_MATERIAL, None),
}

# Maya node type shown in the tab header ("transform: [pCube1]").
NODE_TYPE = {"MESH": "mesh", "CURVE": "nurbsCurve", "SURFACE": "nurbsSurface", "CAMERA": "camera",
             "LIGHT": "light", "LATTICE": "lattice", "ARMATURE": "joint", "FONT": "type",
             "META": "metaball", "EMPTY": "locator", "IMAGE_PLANE": "imagePlane"}
LIGHT_TYPE = {"POINT": "pointLight", "SUN": "directionalLight", "SPOT": "spotLight",
              "AREA": "areaLight"}


def light_type(light):
    """Maya node type of a light shape."""
    return LIGHT_TYPE.get(light.type, "light")


def walk(sections, depth=0):
    """Yield (depth, section) depth first."""
    for sec in sections:
        yield depth, sec
        yield from walk(sec.subs, depth + 1)
