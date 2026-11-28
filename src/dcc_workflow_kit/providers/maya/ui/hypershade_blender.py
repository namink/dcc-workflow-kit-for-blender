# SPDX-License-Identifier: GPL-3.0-or-later
"""The Hypershade Create pane's "Blender" section: Blender's own shader nodes, beside the Maya section, the way a
renderer's nodes get their own section in Maya's Create tree.

``catalog()`` lists every shader node type this Blender has (``bpy.types.ShaderNode*``) under Blender's own Add menu
categories, by Blender's names. A node type the table below doesn't know yet (a newer Blender) is still listed, under
Other, so nothing Blender adds goes missing. Nodes that work only in world, light or line-style node trees, the
material output (a material has one), node groups and Blender's hidden legacy / internal nodes are left out.

``allset.hs_shader``: a click on a shader makes a new material whose Surface (a volume shader: Volume) is that shader,
like a click on a Maya surface material; any other Blender node goes into the current material's graph
(``allset.hs_node``).
"""

import bpy
from bpy.props import StringProperty

from .. import compat
from ..operators import material as material_ops

# Blender's Add menu categories, in its order (key, label)
CATEGORIES = (("BL_INPUT", "Input"), ("BL_SHADER", "Shader"), ("BL_DISPLACEMENT", "Displacement"),
              ("BL_COLOR", "Color"), ("BL_TEXTURE", "Texture"), ("BL_UTILITIES", "Utilities"),
              ("BL_VECTOR", "Vector"), ("BL_OUTPUT", "Output"), ("BL_OTHER", "Other"))

_N = "ShaderNode"
_TABLE = {
    "BL_INPUT": ("AmbientOcclusion", "Attribute", "Bevel", "CameraData", "VertexColor", "HairInfo", "Fresnel",
                 "NewGeometry", "LayerWeight", "LightPath", "ObjectInfo", "ParticleInfo", "PointInfo", "RGB",
                 "TexCoord", "Tangent", "UVMap", "Value", "VolumeInfo", "Wireframe", "Raycast", "LightEvaluation",
                 "LightInfo", "ShadowRaycast"),
    "BL_SHADER": ("AddShader", "MixShader", "BsdfDiffuse", "Emission", "BsdfGlass", "BsdfAnisotropic", "BsdfHair",
                  "Holdout", "BsdfMetallic", "BsdfPrincipled", "BsdfHairPrincipled", "VolumePrincipled",
                  "BsdfRayPortal", "BsdfRefraction", "BsdfSheen", "EeveeSpecular", "SubsurfaceScattering",
                  "BsdfToon", "BsdfTranslucent", "BsdfTransparent", "VolumeAbsorption", "VolumeScatter",
                  "VolumeCoefficients", "LightAccumulation"),
    "BL_DISPLACEMENT": ("Bump", "Displacement", "NormalMap", "VectorDisplacement"),
    "BL_COLOR": ("BrightContrast", "Gamma", "HueSaturation", "Invert", "LightFalloff", "RGBCurve"),
    "BL_UTILITIES": ("Math", "MapRange", "Clamp", "Mix", "FloatCurve", "CombineColor", "SeparateColor",
                     "CombineXYZ", "SeparateXYZ", "Blackbody", "ValToRGB", "RGBToBW", "ShaderToRGB", "Wavelength",
                     "VectorMath", "Script"),
    "BL_VECTOR": ("Mapping", "Normal", "VectorCurve", "VectorRotate", "VectorTransform", "RadialTiling"),
    "BL_OUTPUT": ("OutputAOV",),
}
CATEGORY_OF = {_N + name: key for key, names in _TABLE.items() for name in names}
# not offered: other node trees only, the material's own output, groups, hidden legacy / internal nodes
EXCLUDED = {_N + n for n in ("Background", "OutputWorld", "OutputLight", "OutputLineStyle", "UVAlongStroke",
                             "OutputMaterial", "Group", "CustomGroup", "Tree", "MixRGB", "Squeeze")} | {_N}
VOLUME_SHADERS = {_N + n for n in ("VolumePrincipled", "VolumeAbsorption", "VolumeScatter", "VolumeCoefficients")}

_cache = []


def _category(idname):
    if idname in CATEGORY_OF:
        return CATEGORY_OF[idname]
    return "BL_TEXTURE" if idname.startswith(_N + "Tex") else "BL_OTHER"


def _label(idname):
    rna = getattr(getattr(bpy.types, idname, None), "bl_rna", None)
    return rna.name if rna is not None and rna.name else idname[len(_N):]


def catalog():
    """{category key: [(node idname, Blender label)]} sorted by label; built once per session."""
    if not _cache:
        out = {key: [] for key, _label in CATEGORIES}
        for idname in dir(bpy.types):
            if not idname.startswith(_N) or idname in EXCLUDED or "Internal" in idname:
                continue
            out[_category(idname)].append((idname, _label(idname)))
        for items in out.values():
            items.sort(key=lambda it: it[1].lower())
        _cache.append(out)
    return _cache[0]


def items(category):
    """(idname, label) of a Blender category; "BLENDER" = all of them."""
    cat = catalog()
    if category == "BLENDER":
        return [it for key, _label in CATEGORIES for it in cat[key]]
    return list(cat.get(category, ()))


def is_shader(idname):
    return CATEGORY_OF.get(idname) == "BL_SHADER"


def draw_item(layout, idname, label):
    if is_shader(idname):
        layout.operator("allset.hs_shader", text=label).node_type = idname
    else:
        op = layout.operator("allset.hs_node", text=label)
        op.node_type = idname
        op.label = ""


def new_shader_material(idname):
    """Blender's new material (Blender's name) with ``idname`` as its Surface, or its Volume for a volume shader."""
    mat = material_ops.new_material()
    if idname == _N + "BsdfPrincipled":
        return mat
    compat.ensure_material_nodes(mat)
    tree = mat.node_tree
    out = next((n for n in tree.nodes if n.bl_idname == _N + "OutputMaterial"), None)
    old = next((n for n in tree.nodes if n.bl_idname == _N + "BsdfPrincipled"), None)
    node = tree.nodes.new(idname)
    if old is not None:
        node.location = old.location
        tree.nodes.remove(old)
    if out is not None and node.outputs:
        tree.links.new(node.outputs[0], out.inputs["Volume" if idname in VOLUME_SHADERS else "Surface"])
    tree.nodes.active = node
    return mat


class ALLSET_OT_hs_shader(bpy.types.Operator):
    """Create a new material with this Blender shader (Maya Hypershade Create: a surface material click)"""
    bl_idname = "allset.hs_shader"
    bl_label = "Create Material"
    bl_options = {'REGISTER', 'UNDO'}

    node_type: StringProperty(name="Shader", options={'SKIP_SAVE'})

    def execute(self, context):
        from .hypershade_materials import show
        if not is_shader(self.node_type) or not hasattr(bpy.types, self.node_type):
            self.report({'ERROR'}, f"Blender has no shader {self.node_type}")
            return {'CANCELLED'}
        mat = new_shader_material(self.node_type)
        mat.use_fake_user = True    # no user yet: Blender would drop it on save, Maya keeps it
        show(context, mat, context.space_data)
        context.window_manager.allset_hs_tab = 'MATERIALS'
        return {'FINISHED'}
