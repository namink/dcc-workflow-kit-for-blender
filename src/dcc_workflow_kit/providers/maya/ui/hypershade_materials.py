# SPDX-License-Identifier: GPL-3.0-or-later
"""What the Hypershade shows: its current material (``current``; ``show`` puts a material in the Graph), the
materials objects use (``assigned_materials``; ``release_editors`` before materials are deleted), and the
Browser's tabs, swatch sizes, sort orders and the items each tab lists (``browser_items``).
"""

import bpy

from .. import compat
from ..operators import material as material_ops
from .hypershade_window import graph_area

COLUMNS = 3

# Browser swatch tabs (Maya's tab bar)
TABS = (("MATERIALS", "Materials", "Materials of the scene"),
        ("TEXTURES", "Textures", "Image and texture nodes in the materials"),
        ("UTILITIES", "Utilities", "Other nodes in the materials (Maya utility nodes)"),
        ("RENDERING", "Rendering", "Worlds (Blender's environment / render node)"),
        ("LIGHTS", "Lights", "Light objects"),
        ("CAMERAS", "Cameras", "Camera objects"),
        ("SHADING_GROUPS", "Shading Groups", "Maya shading groups: one per material"))
# Maya's last three Browser tabs: no Blender counterpart (greyed, notices in PANE_NOTICES)
MAYA_ONLY_TABS = ("Bake Sets", "Projects", "Asset Nodes")
# View > As Icons / As List / As Small ... Extra Large Swatches (Maya's View menu; descriptions = the Browser
# toolbar's Maya tooltips); icon scale per size
SWATCHES = (("ICONS", "As Icons", "View as icons", 2.0), ("LIST", "As List", "View as list", 0.0),
            ("SMALL", "As Small Swatches", "View as small swatches", 2.0),
            ("MEDIUM", "As Medium Swatches", "View as medium swatches", 3.0),
            ("LARGE", "As Large Swatches", "View as large swatches", 4.5),
            ("XLARGE", "As Extra Large Swatches", "View as extra large swatches", 6.0))
SORTS = (("NAME", "By Name", "Sort by name"), ("TYPE", "By Type", "Sort by type"), ("TIME", "By Time", "Sort by time"))
# Browser toolbar icons (Blender icons standing in for Maya's)
SWATCH_ICONS = {"ICONS": 'IMGDISPLAY', "LIST": 'LONGDISPLAY', "SMALL": 'DOT', "MEDIUM": 'RADIOBUT_OFF',
                "LARGE": 'MATSPHERE', "XLARGE": 'MATERIAL'}
SORT_ICONS = {"NAME": 'SORTALPHA', "TYPE": 'SORTBYEXT', "TIME": 'SORTTIME'}

TEXTURE_NODES = {'TEX_IMAGE', 'TEX_CHECKER', 'TEX_NOISE', 'TEX_WAVE', 'TEX_VORONOI', 'TEX_BRICK', 'TEX_GRADIENT',
                 'TEX_MAGIC', 'TEX_ENVIRONMENT', 'TEX_SKY', 'TEX_WHITE_NOISE', 'TEX_GABOR'}
SHADER_NODES = {'OUTPUT_MATERIAL', 'BSDF_PRINCIPLED', 'MIX_SHADER', 'ADD_SHADER', 'HOLDOUT', 'EMISSION',
                'BSDF_DIFFUSE', 'BSDF_GLOSSY', 'BSDF_TRANSPARENT', 'BSDF_TRANSLUCENT', 'BSDF_REFRACTION', 'BSDF_GLASS',
                'SUBSURFACE_SCATTERING', 'BSDF_TOON', 'BSDF_SHEEN', 'BSDF_HAIR', 'BSDF_HAIR_PRINCIPLED',
                'VOLUME_ABSORPTION', 'VOLUME_SCATTER', 'PRINCIPLED_VOLUME', 'BSDF_METALLIC', 'FRAME', 'REROUTE',
                'GROUP_INPUT', 'GROUP_OUTPUT'}


def materials():
    return sorted((m for m in bpy.data.materials if not m.is_grease_pencil), key=lambda m: m.name.lower())


def current(context):
    """The Hypershade's current material: the picked one, else the active object's active material."""
    mat = bpy.data.materials.get(context.window_manager.allset_hs_material)
    if mat is None and context.active_object is not None:
        mat = context.active_object.active_material
    return mat


def assigned_materials():
    """Materials some object in a scene uses (Maya: connected to a shading group with members). Data left behind by
    a deleted object still counts as a user in Blender, so users alone don't tell."""
    out = set()
    for scene in bpy.data.scenes:
        for ob in scene.objects:
            out.update(s.material for s in ob.material_slots if s.material is not None)
    return out


def release_editors(mats):
    """Let every Shader Editor showing one of ``mats`` go of its tree before the materials are removed: a pinned
    editor keeps drawing the freed tree and Blender crashes."""
    trees = {m.node_tree.as_pointer() for m in mats if m.node_tree is not None}
    if not trees:
        return
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            for space in area.spaces:
                if space.type != 'NODE_EDITOR':
                    continue
                shown = {t.as_pointer() for t in (space.node_tree, space.edit_tree) if t is not None}
                if shown & trees:
                    space.node_tree = None
                    space.pin = False


def show(context, mat, space=None):
    """Make ``mat`` current and show it in the Shader Editor ``space`` (default: the Hypershade Graph of this
    window, since panes are Properties editors): the active object's slot when it has the material (the editor
    follows the object, unpinned), else pin the editor to it."""
    context.window_manager.allset_hs_material = mat.name
    ob = context.active_object
    index = next((i for i, s in enumerate(ob.material_slots) if s.material == mat), None) if ob else None
    if space is None or space.type != 'NODE_EDITOR':
        graph = graph_area(getattr(context, "screen", None))
        space = graph.spaces.active if graph is not None else None
    if space is None or space.type != 'NODE_EDITOR':
        if index is not None:
            ob.active_material_index = index
        return
    if index is not None:
        ob.active_material_index = index
        space.pin = False
    elif mat.node_tree is not None:
        space.pin = True
        space.node_tree = mat.node_tree


# --- Browser items --------------------------------------------------------------------------------------------

def _node_items(want_textures):
    out = []
    for mat in materials():
        if not compat.material_uses_nodes(mat):
            continue
        for node in mat.node_tree.nodes:
            if node.type in SHADER_NODES or node.name == "Maya Diffuse":
                continue        # the diffuse multiply is part of the Maya material (operators/material.py)
            if (node.type in TEXTURE_NODES) == want_textures:
                out.append((f"{mat.name}::{node.name}", node.label or node.name, mat, node))
    return out


def browser_items(context, tab):
    """[(key, label, icon or ID with a preview, type name)] of a Browser tab, sorted by the View menu's order."""
    scene = context.scene
    if tab == 'MATERIALS':
        items = [(m.name, m.name, m, m.get(material_ops.TYPE_PROP, "material")) for m in materials()]
    elif tab in {'TEXTURES', 'UTILITIES'}:
        items = []
        for key, label, mat, node in _node_items(tab == 'TEXTURES'):
            img = getattr(node, "image", None)
            items.append((key, label, img if img is not None else
                          ('TEXTURE' if tab == 'TEXTURES' else 'NODE'), node.bl_idname))
    elif tab == 'RENDERING':
        items = [(w.name, w.name, w, "world") for w in bpy.data.worlds]
    elif tab in {'LIGHTS', 'CAMERAS'}:
        kind = 'LIGHT' if tab == 'LIGHTS' else 'CAMERA'
        items = [(o.name, o.name, ('LIGHT_' + o.data.type if kind == 'LIGHT' else 'CAMERA_DATA'),
                  o.data.type if kind == 'LIGHT' else "camera")
                 for o in scene.objects if o.type == kind]
        items = [(k, lab, ic if ic in _ICONS else 'LIGHT', t) for k, lab, ic, t in items]
    else:   # SHADING_GROUPS
        items = [(m.name, material_ops.shading_group_name(m), 'NODETREE', "shadingEngine") for m in materials()]
    wm = context.window_manager
    order = wm.allset_hs_sort
    if order == 'TYPE':
        items.sort(key=lambda it: (str(it[3]).lower(), it[1].lower()))
    elif order == 'TIME':
        items.sort(key=lambda it: _uid(context, tab, it[0]))
    else:
        items.sort(key=lambda it: it[1].lower())
    if wm.allset_hs_reverse:
        items.reverse()
    return items


_ICONS = {'LIGHT_POINT', 'LIGHT_SUN', 'LIGHT_SPOT', 'LIGHT_AREA', 'CAMERA_DATA'}


def icon_value(name):
    """The icon id of a named Blender icon (template_icon takes ids only)."""
    return bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items[name].value


def _uid(context, tab, key):
    """Creation order (session uid grows with every new data-block)."""
    if tab == 'MATERIALS' or tab == 'SHADING_GROUPS':
        data = bpy.data.materials.get(key)
    elif tab == 'RENDERING':
        data = bpy.data.worlds.get(key)
    elif tab in {'LIGHTS', 'CAMERAS'}:
        data = bpy.data.objects.get(key)
    else:
        data = bpy.data.materials.get(key.split("::", 1)[0])
    return getattr(data, "session_uid", 0)
