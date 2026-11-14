# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Rendering and Hypershade items on Blender's render systems (#123).

- Toon > Assign Fill Shader: EEVEE toon materials (Diffuse / Glossy > Shader to RGB > constant Color Ramp >
  Emission), assigned like Maya's (``material.assign``);
- Toon > Set Camera Background Color: the World background colour (Blender has one background for every camera);
- Lighting/Shading > Transfer Maps: Cycles Bake set to Selected to Active;
- Hypershade > Create: volume materials (Volume output / World volume), hair materials (Principled Hair BSDF),
  USD Preview Surface (a Principled BSDF, which Blender's USD export writes as UsdPreviewSurface) and Shading Map
  (Shader to RGB remapped by a Color Ramp).
"""

import bpy
from bpy.props import EnumProperty, FloatVectorProperty, StringProperty

from .. import compat, results
from . import material, naming

# --- node helpers ---------------------------------------------------------------------------------------------------


def _socket(sockets, name, kind=None):
    return next(s for s in sockets if s.name == name and (kind is None or s.type == kind))


def _mix(nodes, links, blend, a, b, fac=1.0, x=0.0, y=0.0):
    mix = nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = blend
    mix.location = (x, y)
    _socket(mix.inputs, "Factor", 'VALUE').default_value = fac
    links.new(a, _socket(mix.inputs, "A", 'RGBA'))
    links.new(b, _socket(mix.inputs, "B", 'RGBA'))
    return _socket(mix.outputs, "Result", 'RGBA')


def _ramp(nodes, stops, x, y):
    """A constant Color Ramp with ``stops`` = [(position, rgb)]."""
    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.location = (x, y)
    cr = ramp.color_ramp
    cr.interpolation = 'CONSTANT'
    while len(cr.elements) < len(stops):
        cr.elements.new(1.0)
    for el, (pos, rgb) in zip(cr.elements, stops):
        el.position = pos
        el.color = (*rgb, 1.0)
    return ramp


def _shade(nodes, links, bsdf_type, x, y):
    """Shader to RGB of a white BSDF: the lighting as a colour."""
    bsdf = nodes.new(bsdf_type)
    bsdf.location = (x - 400, y)
    s2r = nodes.new('ShaderNodeShaderToRGB')
    s2r.location = (x - 200, y)
    links.new(bsdf.outputs[0], s2r.inputs[0])
    return s2r.outputs["Color"]


def _fresh_tree(mat):
    compat.ensure_material_nodes(mat)
    tree = mat.node_tree
    tree.nodes.clear()
    out = tree.nodes.new('ShaderNodeOutputMaterial')
    out.location = (600, 0)
    return tree.nodes, tree.links, out


def _new_material(base):
    mat = bpy.data.materials.new(f"{base}{naming.next_number(base, {m.name for m in bpy.data.materials})}")
    return mat


# --- Toon > Assign Fill Shader ------------------------------------------------------------------------------------

TOON_BASE = (0.5, 0.5, 0.5)
TOON_DARK = (0.15, 0.15, 0.15)
TOON_KINDS = (
    ('SOLID_COLOR', "Solid Color", "One flat colour, no shading", "solidColor"),
    ('LIGHT_ANGLE_TWO_TONE', "Light Angle Two Tone", "Lit and shadow side by the light angle", "lightAngleTwoTone"),
    ('SHADED_BRIGHTNESS_TWO_TONE', "Shaded Brightness Two Tone", "Two tones by the shaded brightness",
     "shadedBrightnessTwoTone"),
    ('SHADED_BRIGHTNESS_THREE_TONE', "Shaded Brightness Three Tone", "Three tones by the shaded brightness",
     "shadedBrightnessThreeTone"),
    ('DARK_PROFILE', "Dark Profile", "Two tones, darker where the surface turns away", "darkProfile"),
    ('RIM_LIGHT', "Rim Light", "Two tones with a bright rim", "rimLight"),
    ('CIRCLE_HIGHLIGHT', "Circle Highlight", "Two tones with a round specular highlight", "circleHighlight"),
)
_TOON_BASE_NAMES = {k: base for k, _l, _d, base in TOON_KINDS}


def toon_material(kind, base=TOON_BASE):
    """A new EEVEE toon material of this Assign Fill Shader kind."""
    mat = _new_material(_TOON_BASE_NAMES[kind])
    nodes, links, out = _fresh_tree(mat)
    emit = nodes.new('ShaderNodeEmission')
    emit.location = (400, 0)
    links.new(emit.outputs[0], out.inputs["Surface"])
    mat.diffuse_color = (*base, 1.0)
    if kind == 'SOLID_COLOR':
        emit.inputs["Color"].default_value = (*base, 1.0)
        return mat
    light = _shade(nodes, links, 'ShaderNodeBsdfDiffuse', -200, 0)
    dark = tuple(c * 0.4 for c in base)
    if kind == 'SHADED_BRIGHTNESS_THREE_TONE':
        stops = [(0.0, dark), (0.2, tuple(c * 0.7 for c in base)), (0.5, base)]
    else:
        stops = [(0.0, dark), (0.35 if kind == 'LIGHT_ANGLE_TWO_TONE' else 0.5, base)]
    colour = _ramp(nodes, stops, -100, 0).outputs["Color"]
    links.new(light, colour.node.inputs["Fac"])
    if kind in {'DARK_PROFILE', 'RIM_LIGHT'}:
        lw = nodes.new('ShaderNodeLayerWeight')
        lw.location = (-300, -300)
        lw.inputs["Blend"].default_value = 0.3
        if kind == 'DARK_PROFILE':
            edge = _ramp(nodes, [(0.0, (1.0, 1.0, 1.0)), (0.6, TOON_DARK)], -100, -300)
            links.new(lw.outputs["Facing"], edge.inputs["Fac"])
            colour = _mix(nodes, links, 'MULTIPLY', colour, edge.outputs["Color"], x=200, y=0)
        else:
            rim = _ramp(nodes, [(0.0, (0.0, 0.0, 0.0)), (0.7, (1.0, 1.0, 1.0))], -100, -300)
            links.new(lw.outputs["Facing"], rim.inputs["Fac"])
            colour = _mix(nodes, links, 'ADD', colour, rim.outputs["Color"], x=200, y=0)
    elif kind == 'CIRCLE_HIGHLIGHT':
        gloss = _shade(nodes, links, 'ShaderNodeBsdfGlossy', -200, -300)
        spot = _ramp(nodes, [(0.0, (0.0, 0.0, 0.0)), (0.5, (1.0, 1.0, 1.0))], -100, -300)
        links.new(gloss, spot.inputs["Fac"])
        colour = _mix(nodes, links, 'ADD', colour, spot.outputs["Color"], x=200, y=0)
    links.new(colour, emit.inputs["Color"])
    return mat


class ALLSET_OT_toon_fill(bpy.types.Operator):
    """Assign a toon fill material to the selection (Maya Toon > Assign Fill Shader: Blender's Shader to RGB +
    Color Ramp material; the toon look renders in EEVEE)"""
    bl_idname = "allset.toon_fill"
    bl_label = "Assign Fill Shader"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(items=[k[:3] for k in TOON_KINDS], name="Fill", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return bool(material.targets(context, rmb=True))

    def execute(self, context):
        obs = material.targets(context, rmb=True)
        if not obs:
            self.report({'WARNING'}, "Select objects to assign the fill shader to")
            return {'CANCELLED'}
        mat = material.new_material('SURFACE') if self.kind == 'SOLID_COLOR' else toon_material(self.kind)
        material.assign(context, mat, obs)
        results.result(self, f"Assigned {mat.name}")
        return {'FINISHED'}


# --- Toon > Set Camera Background Color -------------------------------------------------------------------------------

def world_background(scene, create=True):
    """The Background node of the scene's World (made when missing)."""
    world = scene.world
    if world is None:
        if not create:
            return None
        world = bpy.data.worlds.new("World")
        scene.world = world
    compat.ensure_world_nodes(world)
    tree = world.node_tree
    out = next((n for n in tree.nodes if n.type == 'OUTPUT_WORLD'), None) or tree.nodes.new('ShaderNodeOutputWorld')
    surf = out.inputs["Surface"]
    if surf.is_linked and surf.links[0].from_node.type == 'BACKGROUND':
        return surf.links[0].from_node
    bg = next((n for n in tree.nodes if n.type == 'BACKGROUND'), None)
    if bg is None:
        bg = tree.nodes.new('ShaderNodeBackground')
        bg.location = (out.location.x - 250, out.location.y)
    if not surf.is_linked:
        tree.links.new(bg.outputs[0], surf)
    return bg


class ALLSET_OT_camera_background(bpy.types.Operator):
    """Set the render background colour (Maya Toon > Set Camera Background Color: Blender has one background for
    every camera, the World colour)"""
    bl_idname = "allset.camera_background"
    bl_label = "Set Camera Background Color"
    bl_options = {'REGISTER', 'UNDO'}

    camera: StringProperty(name="Camera", options={'SKIP_SAVE'})
    color: FloatVectorProperty(name="Background Color", subtype='COLOR', size=3, min=0.0, max=1.0,
                               default=(0.0, 0.0, 0.0))

    def invoke(self, context, event):
        bg = world_background(context.scene, create=False)
        if bg is not None:
            self.color = bg.inputs["Color"].default_value[:3]
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        bg = world_background(context.scene)
        bg.inputs["Color"].default_value = (*self.color, 1.0)
        context.scene.world.color = self.color
        return {'FINISHED'}


# --- Lighting/Shading > Transfer Maps --------------------------------------------------------------------------------

class ALLSET_OT_transfer_maps(bpy.types.Operator):
    """Set up a map transfer from the selected meshes to the active one (Maya Transfer Maps: Blender's Cycles Bake
    with Selected to Active; the Bake panel opens in Render properties)"""
    bl_idname = "allset.transfer_maps"
    bl_label = "Transfer Maps"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        scene.render.engine = 'CYCLES'
        scene.render.bake.use_selected_to_active = True
        try:
            bpy.ops.allset.open_editor(ui_type='PROPERTIES', tab='RENDER')
        except RuntimeError:            # no window to open from (background)
            pass
        results.result(self, "Cycles Bake: Selected to Active (Render properties > Bake)")
        return {'FINISHED'}


# --- Hypershade > Create: materials Blender builds from other nodes ---------------------------------------------------

EXTRA_KINDS = (
    ('VOLUME_SHADER', "Volume Shader", "Principled Volume on the material's Volume output", "volumeShader"),
    ('VOLUME_FOG', "Volume Fog", "Volume Scatter on the material's Volume output", "volumeFog"),
    ('LIGHT_FOG', "Light Fog", "Volume Scatter on the material's Volume output", "lightFog"),
    ('ENV_FOG', "Env Fog", "Principled Volume on the World's Volume output", "envFog"),
    ('HAIR_PHYSICAL', "Hair Physical Shader", "Principled Hair BSDF", "hairPhysicalShader"),
    ('HAIR_TUBE', "Hair Tube Shader", "Principled Hair BSDF", "hairTubeShader"),
    ('USD_PREVIEW', "Usd Preview Surface", "Principled BSDF (USD export writes it as UsdPreviewSurface)",
     "usdPreviewSurface"),
    ('SHADING_MAP', "Shading Map", "Shader to RGB of a Diffuse BSDF remapped by a Color Ramp", "shadingMap"),
)
_EXTRA_BASE = {k: base for k, _l, _d, base in EXTRA_KINDS}
ENV_FOG_DENSITY = 0.01


def extra_material(kind):
    """A new material (or, for Env Fog, the World's volume node) of this Hypershade Create kind."""
    if kind == 'ENV_FOG':
        bg = world_background(bpy.context.scene)
        tree = bg.id_data
        out = next(n for n in tree.nodes if n.type == 'OUTPUT_WORLD')
        vol = tree.nodes.new('ShaderNodeVolumePrincipled')
        vol.name = vol.label = _EXTRA_BASE[kind]
        vol.location = (out.location.x - 250, out.location.y - 250)
        vol.inputs["Density"].default_value = ENV_FOG_DENSITY
        tree.links.new(vol.outputs[0], out.inputs["Volume"])
        return None
    mat = _new_material(_EXTRA_BASE[kind])
    nodes, links, out = _fresh_tree(mat)
    if kind in {'VOLUME_SHADER', 'VOLUME_FOG', 'LIGHT_FOG'}:
        vol = nodes.new('ShaderNodeVolumePrincipled' if kind == 'VOLUME_SHADER' else 'ShaderNodeVolumeScatter')
        vol.location = (300, -200)
        links.new(vol.outputs[0], out.inputs["Volume"])
    elif kind in {'HAIR_PHYSICAL', 'HAIR_TUBE'}:
        hair = nodes.new('ShaderNodeBsdfHairPrincipled')
        hair.location = (300, 0)
        links.new(hair.outputs[0], out.inputs["Surface"])
    elif kind == 'USD_PREVIEW':
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.location = (300, 0)
        links.new(bsdf.outputs[0], out.inputs["Surface"])
    elif kind == 'SHADING_MAP':
        emit = nodes.new('ShaderNodeEmission')
        emit.location = (400, 0)
        links.new(emit.outputs[0], out.inputs["Surface"])
        light = _shade(nodes, links, 'ShaderNodeBsdfDiffuse', -200, 0)
        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.location = (100, 0)
        links.new(light, ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], emit.inputs["Color"])
    return mat


class ALLSET_OT_hs_create_extra(bpy.types.Operator):
    """Create this Maya material from Blender nodes without assigning it (Maya Hypershade Create; Env Fog goes on
    the World)"""
    bl_idname = "allset.hs_create_extra"
    bl_label = "Create Material"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(items=[k[:3] for k in EXTRA_KINDS], name="Material", options={'SKIP_SAVE'})

    def execute(self, context):
        mat = extra_material(self.kind)
        if mat is None:
            results.result(self, f"{_EXTRA_BASE[self.kind]}: World > Volume")
            return {'FINISHED'}
        mat.use_fake_user = True     # no user yet: Blender would drop it on save
        from ..ui import hypershade
        hypershade.show(context, mat, context.space_data)
        context.window_manager.allset_hs_tab = 'MATERIALS'
        results.result(self, f"Created {mat.name}")
        return {'FINISHED'}


classes = (ALLSET_OT_toon_fill, ALLSET_OT_camera_background, ALLSET_OT_transfer_maps, ALLSET_OT_hs_create_extra)
