# SPDX-License-Identifier: GPL-3.0-or-later
"""Attribute Editor nodes: which node tabs an object or joint shows and in what order (transform, shape, history,
materials, constraints), their Maya node names and types, and what each tab points at.
Main entry points: ``tabs``, ``current_tab``, ``tab_target``, ``sections_for``, ``ae_node``, ``modifier_node``.
Related: ``attribute_editor`` (the panel), ``ae_rows`` (a tab's body), ``ae_layout`` (section tables)."""

import re

import bpy

from .. import compat
from ..operators import display
from . import ae_layout
from . import channel_box


# --- tabs ---------------------------------------------------------------------------------

def principled(material):
    if not compat.material_uses_nodes(material):
        return None
    return next((n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)


def material_type(material):
    """Tab type of a material: Principled BSDF for a material with one (new materials and those of older kit
    versions alike), else "material"."""
    if material is not None and principled(material):
        return ae_layout.PRINCIPLED_TYPE
    return "material"


def shape_kind(ob):
    """The ``BY_KIND`` / ``NODE_TYPE`` key of an object's shape: the light type, IMAGE_PLANE for an image empty, else
    the object type."""
    if ob.type == 'LIGHT':
        return ob.data.type
    if ob.type == 'EMPTY' and ob.empty_display_type == 'IMAGE':
        return 'IMAGE_PLANE'
    return ob.type


def node_type(ob):
    if ob.type == 'LIGHT':
        return ae_layout.light_type(ob.data)
    return ae_layout.NODE_TYPE.get(shape_kind(ob), ob.type.lower())


# Blender modifier -> the Maya history node that does the same (Maya node type names; where Maya has
# none of its own: the closest poly / deformer node).
MODIFIER_NODES = {
    'SUBSURF': "polySmoothFace", 'MULTIRES': "polySmoothFace", 'BEVEL': "polyBevel3", 'MIRROR': "polyMirror",
    'TRIANGULATE': "polyTriangulate", 'WELD': "polyMergeVert", 'DECIMATE': "polyReduce", 'REMESH': "polyRemesh",
    'SOLIDIFY': "polyExtrudeFace", 'BOOLEAN': "polyCBoolOp", 'SMOOTH': "polyAverageVertex",
    'LAPLACIANSMOOTH': "polyAverageVertex", 'CORRECTIVE_SMOOTH': "deltaMush", 'ARMATURE': "skinCluster",
    'LATTICE': "ffd", 'SHRINKWRAP': "shrinkWrap", 'WIREFRAME': "polyWireframe", 'ARRAY': "polyDuplicate",
    'CLOTH': "nCloth", 'COLLISION': "nRigid", 'PARTICLE_SYSTEM': "nParticle", 'SOFT_BODY': "nCloth",
    'SIMPLE_DEFORM': "nonLinear", 'CAST': "nonLinear", 'WAVE': "nonLinear", 'DISPLACE': "textureDeformer",
    'SCREW': "polyRevolve", 'EDGE_SPLIT': "polySoftEdge",
    'WEIGHTED_NORMAL': "polyNormalPerVertex", 'NODES': "geometryNodes",
    'HOOK': "cluster", 'SURFACE_DEFORM': "wrap", 'CURVE': "curveWarp",    # operators/deformers.BASES
}


def modifier_node(ob, md):
    """(Maya node name, Maya node type) of a modifier: a modifier with Blender's automatic name gets Maya's
    (``<type><n>``, numbered per type like Maya: ``polyBevel1``); a named one (kit-made ``polySmoothFace``, the
    user's own) keeps its name."""
    from ..operators import deformers
    kit = deformers.node_type(md)     # a kit Maya deformer (cluster1 = HOOK, wrap1 = SURFACE_DEFORM ...)
    if kit is not None:
        return md.name, kit
    mtype = MODIFIER_NODES.get(md.type, md.type.lower())
    base = re.sub(r"\d+$", "", mtype)         # Maya names polyBevel3 nodes polyBevel1, polyBevel2, ...
    if not default_name(md):
        return md.name, mtype                  # a name the user / the kit gave it
    same = [m for m in ob.modifiers if MODIFIER_NODES.get(m.type, m.type.lower()) == mtype
            and not display.is_preview(m) and default_name(m)]
    return f"{base}{same.index(md) + 1}", mtype


def default_name(md):
    """True for Blender's automatic modifier names ("Bevel", "Subdivision.001", "GeometryNodes")."""
    base = re.sub(r"\.\d+$", "", md.name).replace(" ", "").lower()
    ui = md.bl_rna.properties["type"].enum_items[md.type].name.replace(" ", "").lower()
    return bool(base) and ui.startswith(base)


def history_record(ob):
    """The kit's last extrusion of ``ob`` (Maya polyExtrudeFace node), or None (edit mode only)."""
    from . import in_view
    try:
        return in_view.cb_record(bpy.context, ob)
    except (AttributeError, ReferenceError):
        return None


def nice_type(mtype):
    """"polyExtrudeFace" -> "Poly Extrude Face" (Maya's history section title is "<Nice Type> History")."""
    return re.sub(r"(?<!^)(?=[A-Z])", " ", mtype[:1].upper() + mtype[1:])


def hidden_types(context=None):
    wm = (context or bpy.context).window_manager
    return {t for t in getattr(wm, "allset_ae_hidden", "").split(",") if t}


def _constraint_tabs(node):
    return [(f"C:{con.name}", channel_box.constraint_node_name(node, con),
             channel_box.maya_constraint_type(con, con.type.lower()))
            for con in channel_box.constraints(node)]


def tabs(ob):
    """[(key, label, Maya node type)] in Maya's order: transform, shape, history, materials,
    constraints; a joint (pose bone): joint, constraints."""
    if channel_box.is_bone(ob):
        return [("J", ob.name, "joint")] + _constraint_tabs(ob)
    out = [("T", ob.name, "transform")]
    if ob.data is not None:
        out.append(("S", ob.data.name, node_type(ob)))
    rec = history_record(ob)
    if rec is not None:
        from ..operators import model_history
        nodes = model_history.records(ob)
        if nodes:
            for index, node in enumerate(reversed(nodes)):
                out.append(('H' if index == 0 else 'H:'+node.history_id, node.name, node.spec.node_type))
        else:
            out.append(('H', rec.name, rec.spec.node_type))
    from ..operators import skin_tools_199
    for md in ob.modifiers:
        if display.is_preview(md):   # shape display attribute, drawn in "Smooth Mesh"
            continue
        if skin_tools_199.is_part(md):   # the skin's weight-sum helper belongs to the skinCluster
            continue
        from ..operators import skin_method
        if skin_method.is_part(md):      # Weight Blended's DQ half belongs to the skinCluster too
            continue
        from ..operators import type_manip
        if type_manip.is_part(md):       # the type node's own per-character transforms
            continue
        name, mtype = modifier_node(ob, md)
        out.append((f"M:{md.name}", name, mtype))
    from ..operators import prim_history
    _owner, node = prim_history.node_of(ob)
    if node is not None:             # the primitive's creation node, the oldest history
        out.append(("CH", node["name"], node["type"]))
    from ..operators import material as material_ops
    for i, slot in enumerate(ob.material_slots):
        if slot.material is not None:
            # Maya: the shape's shading group, then its surface shader (pCubeShape1 | polyCube1 |
            # Material1SG | Material1)
            out.append((f"SG:{i}", material_ops.shading_group_name(slot.material), "shadingEngine"))
            out.append((f"MAT:{i}", slot.material.name, material_type(slot.material)))
    out += _constraint_tabs(ob)
    hide = hidden_types()             # AE Hide button: nodes of these types get no tab (the node itself stays)
    return [t for t in out if t[0] in ("T", "S") or t[2] not in hide]


def _kind(key):
    return key.split(":", 1)[0]


def current_tab(context, ob):
    """The selected tab key: the stored one, else the first of the stored kind, else
    the shape (Maya's preferred node), else the transform."""
    wm = context.window_manager
    keys = [t[0] for t in tabs(ob)]
    if wm.allset_ae_tab in keys:
        return wm.allset_ae_tab
    for k in keys:
        if _kind(k) == wm.allset_ae_kind:
            return k
    if "J" in keys:
        return "J"
    return "S" if "S" in keys else "T"


def tab_target(ob, key):
    """The datablock or modifier a tab shows."""
    kind = _kind(key)
    if kind in ("T", "J"):
        return ob
    if kind == "C":
        return ob.constraints.get(key[2:])
    if kind == "S":
        return ob.data
    if kind == "M":
        return ob.modifiers.get(key[2:])
    if kind in ("MAT", "SG"):
        i = int(key.split(":", 1)[1])
        return ob.material_slots[i].material if i < len(ob.material_slots) else None
    if kind == "H":
        from ..operators import model_history
        if ':' in key:
            return model_history.find(ob, key.split(':', 1)[1])
        nodes = model_history.records(ob)
        return nodes[-1] if nodes else history_record(ob)
    if kind == "CH":
        from ..operators import prim_history
        return prim_history.node_of(ob)[0]
    return None


def sections_for(ob, key):
    """(sections, layout id) for a tab; empty for history tabs (drawn generically)."""
    kind = _kind(key)
    if kind == "T":
        return ae_layout.BY_KIND["transform"][0], "transform"
    if kind == "J":
        return ae_layout.BY_KIND["joint"][0], "joint"
    if kind == "S":
        sub = shape_kind(ob)
        return ae_layout.BY_KIND.get(sub, ([], None))[0], sub.lower()
    if kind == "MAT":
        mat = tab_target(ob, key)
        name = material_type(mat)
        return ae_layout.BY_KIND[name][0], name
    return [], None


def ae_node(context):
    """The object (or pose bone) the AE shows: the lead, or the focused node while Auto Load is off."""
    wm = context.window_manager
    if not getattr(wm, "allset_ae_auto_load", True):
        ob = bpy.data.objects.get(getattr(wm, "allset_ae_node", ""))
        if ob is not None:
            return ob
    return channel_box.lead(context)
