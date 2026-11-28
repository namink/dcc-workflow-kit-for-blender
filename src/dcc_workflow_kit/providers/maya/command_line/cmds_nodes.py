# SPDX-License-Identifier: GPL-3.0-or-later
"""maya.cmds look-alike: the Maya nodes the kit keeps outside the object list (materials, file textures, sets,
shading groups, creation and extrusion nodes, constraints, joints) and their types. ``_node`` finds such a node by
name, ``nodeType`` / ``objectType`` give a type and its class chain (``CHAINS``), ``unique_node_name`` names new
nodes like Maya, ``select_nodes`` / ``extra_selection`` keep them selected (loaded through cmds_misc.py)."""

import bpy

from . import cmds_shim as _shim
from .cmds_shim import _Flags, _flatten

HISTORY_PROP = "allset_cmds_history"   # mesh data: [{name, type, values}] of the extrusions made by commands
TEXTURE_PROP = "allset_shading_node"   # node group: Maya node type ("file")
FILE_NAME_PROP = "allset_file_texture_name"
# Maya's standard scene nodes that aren't DAG objects (Maya: ls -type objectSet, nodeType time1)
DEFAULT_SETS = {"defaultLightSet": "objectSet", "defaultObjectSet": "objectSet",
                "initialParticleSE": "shadingEngine", "initialShadingGroup": "shadingEngine"}
DEFAULT_NODES = {"time1": "time"}

# nodeType -inherited (Maya's lists for joint and mesh; the others
# follow Maya's documented node hierarchy)
_DAG = ["containerBase", "entity", "dagNode"]
_SHAPE = _DAG + ["shape"]
_GEO = _SHAPE + ["geometryShape", "deformableShape", "controlPoint"]
_LAMBERT = ["shadingDependNode", "lambert"]
CHAINS = {
    "transform": _DAG + ["transform"],
    "joint": _DAG + ["transform", "joint"],
    "mesh": _GEO + ["surfaceShape", "mesh"],
    "nurbsCurve": _GEO + ["curveShape", "nurbsCurve"],
    "nurbsSurface": _GEO + ["surfaceShape", "nurbsSurface"],
    "lattice": _GEO + ["lattice"],
    "locator": _SHAPE + ["geometryShape", "locator"],
    "camera": _SHAPE + ["camera"],
    "lambert": _LAMBERT,
    "blinn": _LAMBERT + ["reflect", "blinn"],
    "phong": _LAMBERT + ["reflect", "phong"],
    "phongE": _LAMBERT + ["reflect", "phongE"],
    "anisotropic": _LAMBERT + ["reflect", "anisotropic"],
    "rampShader": ["shadingDependNode", "rampShader"],
    "file": ["shadingDependNode", "texture2d", "file"],
    "objectSet": ["entity", "objectSet"],
    "shadingEngine": ["entity", "objectSet", "shadingEngine"],
    "polyExtrudeFace": ["polyBase", "polyModifier", "polyModifierWorld", "polyMoveFace", "polyExtrudeFace"],
}
_LIGHT = _SHAPE + ["light", "renderLight"]
_CONSTRAINT = _DAG + ["transform", "constraint"]


def _cb():
    from ..ui import channel_box
    return channel_box


def _chain(maya_type):
    if maya_type in CHAINS:
        return list(CHAINS[maya_type])
    if maya_type.endswith("Light"):
        return _LIGHT + [maya_type]
    if maya_type.endswith("Constraint"):
        return _CONSTRAINT + [maya_type]
    if maya_type.startswith("poly"):
        return ["polyBase", "polyCreator", "polyPrimitive", maya_type]
    return [maya_type]


# --- non-DAG nodes ---------------------------------------------------------------------------------------------------

class Node:
    """A Maya node the kit keeps outside the object list: ``kind`` + Blender data + Maya node type."""

    def __init__(self, kind, name, maya_type, data=None, owner=None):
        self.kind, self.name, self.type, self.data, self.owner = kind, name, maya_type, data, owner


def _materials():
    return [m for m in bpy.data.materials if not m.is_grease_pencil and m.library is None]


def _material_type(mat):
    from ..operators import material
    return material.maya_type(mat)


def _textures():
    return [g for g in bpy.data.node_groups if g.get(TEXTURE_PROP)]


def _used_materials():
    used = []
    for ob in bpy.context.scene.objects:
        for slot in getattr(ob, "material_slots", ()):
            if slot.material is not None and slot.material not in used:
                used.append(slot.material)
    return used


def _shading_groups():
    """Maya shading groups: ``<material>SG`` of every assigned material (initialShadingGroup, the shapes without a
    material, is one of ``DEFAULT_SETS``)."""
    from ..operators import material
    return {material.shading_group_name(m): m for m in _used_materials()}


def _extrusion_nodes(ob):
    """[(name, type, values)] of ``ob``'s extrusions, oldest first: the command list + the kit's live record."""
    from ..operators import extrude
    out = []
    data = ob.data if ob.type == 'MESH' else None
    if data is not None:
        for entry in data.get(HISTORY_PROP, ()):
            e = entry.to_dict() if hasattr(entry, "to_dict") else dict(entry)
            out.append((e["name"], e["type"], dict(e.get("values", {}))))
    rec = extrude.RECORDS.get(ob.name)
    if rec is not None and rec.pre is not None and not any(n == rec.name for n, _t, _v in out):
        out.append((rec.name, rec.spec.node_type, dict(rec.params)))
    return out


def _node(name):
    """The non-DAG Maya node called ``name``, or None."""
    from ..operators import prim_history, sets
    name = str(name)
    mat = bpy.data.materials.get(name)
    if mat is not None and not mat.is_grease_pencil:
        return Node('MATERIAL', name, _material_type(mat), mat)
    group = bpy.data.node_groups.get(name)
    if group is not None and group.get(TEXTURE_PROP):
        return Node('TEXTURE', name, group[TEXTURE_PROP], group)
    coll = sets.get(name)
    if coll is not None:
        return Node('SET', name, "objectSet", coll)
    if name in DEFAULT_SETS:
        return Node('DEFAULT_SET', name, DEFAULT_SETS[name])
    if name in DEFAULT_NODES:
        return Node('DEFAULT', name, DEFAULT_NODES[name])
    sg = _shading_groups().get(name)
    if sg is not None:
        return Node('SG', name, "shadingEngine", sg)
    for ob in bpy.context.scene.objects:
        owner = prim_history.owner_of(ob)
        node = prim_history.node_dict(owner)
        if node is not None and node.get("name") == name:
            return Node('HISTORY', name, node["type"], owner, ob)
        if ob.type == 'MESH':
            for n, t, values in _extrusion_nodes(ob):
                if n == name:
                    return Node('EXTRUDE', name, t, values, ob)
        for target in [ob, *(ob.pose.bones if ob.pose is not None else ())]:
            for con in _cb().constraints(target):
                if con.name == name or _cb().constraint_node_name(target, con) == name:
                    return Node('CONSTRAINT', name, _cb().maya_constraint_type(con, "constraint"), con, target)
    for arm in bpy.data.armatures:
        if arm.users and name in arm.bones:
            return Node('BONE', name, "joint", arm.bones[name], arm)
    return None


def _dag(name):
    """(kind 'T' / 'S', object) of a DAG name (shim rules), or None."""
    short = str(name).rsplit("|", 1)[-1]
    try:
        ob = _shim._object(short)
    except (ValueError, RuntimeError):
        return None
    return ('S' if _shim._is_shape_name(short) else 'T', ob)


def _default_camera_type(name):
    """Maya's startup cameras when the scene has no such object: persp (transform) / perspShape (camera)."""
    if name in _shim.DEFAULT_CAMERAS:
        return "transform"
    if name.endswith("Shape") and name[:-5] in _shim.DEFAULT_CAMERAS:
        return "camera"
    return None


def split_plug(text):
    """(node, attribute) of ``node.attr`` (attribute "" without one). Blender names materials Material.001, so the
    longest head that names a material is the node; any other name ends at the first dot."""
    base = str(text).rsplit("|", 1)[-1]
    parts = base.split(".")
    for i in range(len(parts) - 1, 0, -1):
        head = ".".join(parts[:i])
        if bpy.data.materials.get(head) is not None:
            return head, ".".join(parts[i:])
    if len(parts) > 1 and bpy.data.materials.get(base) is not None:
        return base, ""
    node, _dot, attr = base.partition(".")
    return node, attr


def _type_of(name):
    """Maya node type of a node / plug / component name; RuntimeError when nothing has that name."""
    text = str(name)
    node = split_plug(text)[0]
    component = "[" in text
    hook = getattr(_rig(), "node_type", None)     # cmds_rig may name nodes it makes
    if hook is not None and not component:
        found = hook(node)
        if found:
            return found
    dag = _dag(node)
    if dag is not None:
        kind, ob = dag
        if kind == 'S' or component:
            return _shim.shape_type(ob) or "shape"
        return "joint" if ob.type == 'ARMATURE' else "transform"
    found = _node(node)
    if found is not None:
        return found.type
    cam = _default_camera_type(node)
    if cam is not None:
        return cam
    raise RuntimeError(f"No object matches name: {name}")


def _rig():
    from . import cmds_rig
    return cmds_rig


def nodeType(*args, **kwargs):
    """``nodeType`` = the Maya type of a node, plug (its node) or component (its shape); ``-inherited`` = the class
    chain (Maya: joint containerBase entity dagNode transform joint). A missing node raises RuntimeError."""
    f = _Flags("nodeType", kwargs)
    inherited = f.get("inherited", "i", False)
    f.get("apiType", "api", False)
    f.done()
    names = list(_flatten(args))
    if len(names) != 1:
        raise RuntimeError("nodeType: one node name is needed")
    t = _type_of(names[0])
    return _chain(t) if inherited else t


def objectType(*args, **kwargs):
    """``objectType`` = nodeType; ``-isType`` is exact (a joint is not a "transform"), ``-isAType`` follows the
    class chain."""
    f = _Flags("objectType", kwargs)
    is_type = f.get("isType", "i")
    is_a = f.get("isAType", "isa")
    f.done()
    names = list(_flatten(args))
    if len(names) != 1:
        raise RuntimeError("objectType: one object name is needed")
    t = _type_of(names[0])
    if is_type is not None:
        return t == is_type
    if is_a is not None:
        return is_a in _chain(t)
    return t


# --- unique node names -----------------------------------------------------------------------------------------------

def _all_names():
    from ..operators import sets
    names = {o.name for o in bpy.data.objects} | {m.name for m in bpy.data.materials}
    names |= {g.name for g in bpy.data.node_groups} | {c.name for c in sets.all_sets()}
    names |= set(_shim.DEFAULT_CAMERAS) | set(DEFAULT_SETS) | set(DEFAULT_NODES)
    return names


def unique_node_name(name, taken=None):
    """``name`` when no Maya node has it, else one past the highest number of its base (Maya: -n set1 with set1 ..
    set3 taken -> set4)."""
    from ..operators import naming
    taken = _all_names() if taken is None else taken
    if name not in taken:
        return name
    base = naming.base_name(name)
    return f"{base}{naming.next_number(base, taken)}"


# --- non-DAG selection -----------------------------------------------------------------------------------------------

_EXTRA = {"items": [], "sig": None}


def _selection_signature():
    return tuple(o.name for o in _shim._selection())


def select_nodes(items, keep_objects=False):
    """Make ``items`` (non-DAG nodes, components; object names when ``keep_objects``) the selection, as Maya's
    shadingNode / polyExtrudeFacet do. The kit keeps them beside Blender's object selection until it changes."""
    objects = [n for n in items if bpy.data.objects.get(n) is not None]
    extra = [n for n in items if n not in objects]
    if not keep_objects:
        _shim._select_only([bpy.data.objects[n] for n in objects])
    _EXTRA["items"] = extra
    _EXTRA["sig"] = _selection_signature()


def extra_selection():
    if _EXTRA["sig"] is not None and _EXTRA["sig"] != _selection_signature():
        _EXTRA["items"], _EXTRA["sig"] = [], None
    return list(_EXTRA["items"])
