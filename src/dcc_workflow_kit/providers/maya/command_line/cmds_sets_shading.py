# SPDX-License-Identifier: GPL-3.0-or-later
"""maya.cmds look-alike: ``sets`` on the kit's sets (operators/sets.py; ``_set_members`` also lists a shading
group's members) and shading nodes: ``shadingNode`` makes a kit material or a ``file`` texture
(``new_file_texture``) and selects it; ``connect_texture`` / ``shading_sources`` give cmds_connections.py's connectAttr /
listConnections the texture -> material colour connections. Re-exported by cmds_misc.py."""

import bpy

from . import cmds_shim as _shim
from .cmds_shim import _Flags, _flatten
from .cmds_nodes import FILE_NAME_PROP, TEXTURE_PROP, _all_names, _node, select_nodes, split_plug, unique_node_name
from .cmds_attributes import _COLOR_ATTRS

# --- sets ------------------------------------------------------------------------------------------------------------

def _set_members(found):
    if found.kind == 'SET':
        from ..operators import sets
        scene = bpy.context.scene
        return [o.name for o in sets.members(found.data, scene)] + [
            n for o in sets.part_objects(found.data, scene) for n in sets.component_names(found.data, o)]
    if found.kind == 'SG':
        mat = found.data
        return [_shim.shape_of(o) or o.name for o in bpy.context.scene.objects
                if any(s.material is mat for s in getattr(o, "material_slots", ()))]
    if found.name == _NO_MATERIAL:
        return [_shim.shape_of(o) or o.name for o in _unshaded()]
    return []


# initialShadingGroup: the shapes without a material (Blender has no default material)
_NO_MATERIAL = "initialShadingGroup"


def _unshaded():
    from ..operators import material
    return [o for o in bpy.context.scene.objects if o.type in material.SHADED_TYPES
            and not any(s.material is not None for s in o.material_slots)]


def _drop_materials(obs):
    """``sets -e -forceElement initialShadingGroup``: the shapes lose their materials (whole shapes)."""
    for ob in obs:
        if ob.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'} and ob.data is not None:
            if ob.type == 'MESH':
                ob.data.polygons.foreach_set("material_index", [0] * len(ob.data.polygons))
            ob.data.materials.clear()
            for slot in ob.material_slots:
                slot.material = None


def _set_node(name):
    found = _node(name)
    if found is None or found.kind not in ('SET', 'SG', 'DEFAULT_SET'):
        raise RuntimeError(f"sets: No object set matches name: {name}")
    return found


def sets(*args, **kwargs):
    """``sets`` = Create > Sets > Set: a kit set (``operators/sets.py``) named set1, set2 … (one past the highest);
    -add / -remove / -isMember / -q on a set. Making or editing a set doesn't change the selection."""
    from ..operators import sets as kit_sets
    f = _Flags("sets", kwargs)
    query = f.get("query", "q", False)
    f.get("edit", "e", False)
    add = f.get("addElement", "add") or f.get("include", "in") or f.get("forceElement", "fe")
    remove = f.get("remove", "rm")
    member = f.get("isMember", "im")
    empty = f.get("empty", "em", False)
    name = f.get("name", "n")
    text = f.get("text", "t")
    clear = f.get("clear", "cl")
    f.done()
    names = list(_flatten(args))
    if query:
        if len(names) != 1:
            raise RuntimeError("sets -q needs one set")
        return _set_members(_set_node(names[0])) or None
    if member is not None:
        found = _set_node(member)
        have = set(_set_members(found))
        obs = [_shim._object(n) for n in names] if names else _shim._selection()
        return bool(obs) and all(o.name in have or _shim.shape_of(o) in have for o in obs)
    for target, op in ((add, kit_sets.add), (remove, kit_sets.remove)):
        if target is not None:
            found = _set_node(target)
            if found.name == _NO_MATERIAL and op is kit_sets.add:
                _drop_materials([_shim._object(n) for n in names] if names else _shim._selection())
                return found.name
            if found.kind != 'SET':
                raise RuntimeError(f"sets: the kit can't edit the members of {target}")
            obs = [_shim._object(n) for n in names] if names else _shim._selection()
            # Maya: -add (c, a) lists a before c (members go in last given first)
            op(found.data, list(reversed(obs)))
            return found.name
    if clear is not None:
        found = _set_node(clear)
        if found.kind == 'SET':
            kit_sets.remove(found.data, list(found.data.objects))
            for o in kit_sets.part_objects(found.data):
                kit_sets.remove_components(found.data, o)
        return found.name
    parts = {}
    if empty:
        obs = []
    elif names:
        obs = [_shim._object(n) for n in names]
    elif bpy.context.mode == 'EDIT_MESH':          # Maya: the selected components (and objects)
        obs, parts = kit_sets.gather(bpy.context)
    else:
        obs = list(reversed(_shim._selection()))   # Maya: from the selection (b, c) -> [c, b]
    new_name = unique_node_name(str(name)) if name else kit_sets.next_name()
    coll = kit_sets.create(new_name, obs, text=str(text or ""), parts=parts)
    return coll.name


# --- shading nodes ---------------------------------------------------------------------------------------------------

def new_file_texture(name=None):
    """Maya's ``file`` texture node: a Shader node group with an Image Texture node and Maya's outputs."""
    from ..operators import naming
    taken = _all_names()
    group = bpy.data.node_groups.new(unique_node_name(str(name)) if name
                                     else f"file{naming.next_number('file', taken)}", 'ShaderNodeTree')
    group[TEXTURE_PROP] = "file"
    group[FILE_NAME_PROP] = ""
    group.use_fake_user = True
    group.interface.new_socket("outColor", in_out='OUTPUT', socket_type='NodeSocketColor')
    group.interface.new_socket("outAlpha", in_out='OUTPUT', socket_type='NodeSocketFloat')
    tex = group.nodes.new("ShaderNodeTexImage")
    tex.name = "file"
    out = group.nodes.new("NodeGroupOutput")
    out.location = (300, 0)
    group.links.new(tex.outputs["Color"], out.inputs["outColor"])
    group.links.new(tex.outputs["Alpha"], out.inputs["outAlpha"])
    return group


def shadingNode(*args, **kwargs):
    """``shadingNode lambert -asShader`` (any Maya surface shader type of ``material.SURFACE_TYPES``) = Blender's new
    material (``material.new_material``: Material, Material.001 …, Blender's values), returned by its name;
    ``file -asTexture`` = ``new_file_texture``. No shading group is made; the new node becomes the selection."""
    from ..operators import material
    f = _Flags("shadingNode", kwargs)
    f.get("asShader", "asShader", False)
    as_texture = f.get("asTexture", "at", False)
    f.get("asUtility", "au", False)
    f.get("asLight", "al", False)
    f.get("asRendering", "ar", False)
    f.get("asPostProcess", "app", False)
    f.get("shared", "s", False)
    name = f.get("name", "n")
    skip = f.get("skipSelect", "ss", False)
    f.done()
    types = list(_flatten(args))
    if len(types) != 1:
        raise RuntimeError("shadingNode: one node type is needed")
    maya_type = str(types[0])
    if maya_type == "file":
        node_name = new_file_texture(name).name
    else:
        if maya_type not in material.SURFACE_TYPES:
            from ..ui import notices
            path = notices.NODE_SETUPS.get(maya_type)
            if path is not None:
                raise RuntimeError(f"shadingNode: {notices.NOTICES[path][1]}")
            raise RuntimeError(f"shadingNode: Maya Workflow Kit can't make a '{maya_type}' node"
                               + (" (texture nodes: file)" if as_texture else ""))
        mat = material.new_material()
        if name:
            mat.name = unique_node_name(str(name), _all_names() - {mat.name})
        node_name = mat.name
    if not skip:
        select_nodes([node_name])
    return node_name


def connect_texture(src_plug, dst_plug):
    """``connectAttr file1.outColor lambert2.color``: the file node's group goes into the material in front of its
    Maya colour input. Returns Maya's message, or None when the plugs aren't a texture -> material connection
    (for cmds_connections.connectAttr)."""
    from ..operators import material
    src_node, src_attr = split_plug(src_plug)
    dst_node, dst_attr = split_plug(dst_plug)
    if not src_attr or not dst_attr:
        return None
    src, dst = _node(src_node), _node(dst_node)
    if src is None or dst is None or src.kind != 'TEXTURE' or dst.kind != 'MATERIAL':
        return None
    if src_attr not in ("outColor", "outAlpha") or dst_attr not in _COLOR_ATTRS:
        return None
    mat = dst.data
    sock = material.maya_input(mat, _COLOR_ATTRS[dst_attr])
    if sock is None:
        return None
    tree = mat.node_tree
    node = next((n for n in tree.nodes if n.type == 'GROUP' and n.node_tree is src.data), None)
    if node is None:
        node = tree.nodes.new("ShaderNodeGroup")
        node.node_tree = src.data
        node.name = node.label = src.name
        node.location = (sock.node.location.x - 300, sock.node.location.y)
    tree.links.new(node.outputs[src_attr], sock)
    return f"Connected {src_plug} to {dst_plug}."


def shading_sources(plug):
    """Maya plugs feeding a material plug (``listConnections lambert2.color -s 1 -p 1``), or None when ``plug`` isn't
    a kit material's (for cmds_connections.listConnections)."""
    from ..operators import material
    node, attr = split_plug(plug)
    if not attr:
        return None
    found = _node(node)
    if found is None or found.kind != 'MATERIAL' or attr not in _COLOR_ATTRS:
        return None
    sock = material.maya_input(found.data, _COLOR_ATTRS[attr])
    out = []
    for link in getattr(sock, "links", ()):
        n = link.from_node
        if n.type == 'GROUP' and n.node_tree is not None and n.node_tree.get(TEXTURE_PROP):
            out.append(f"{n.node_tree.name}.{link.from_socket.name}")
    return out
