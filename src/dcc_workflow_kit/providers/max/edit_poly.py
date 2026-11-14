# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format
'Max\'s Edit Poly modifier: a layer in the modifier stack that keeps sub-object moves.\n\nA layer is a Geometry Nodes modifier running the shared "MaxFlow Edit Poly" group. The group\nadds a move per vertex, stored in a hidden attribute of the mesh (".maxflow_edit_poly_<n>"),\nand then removes that attribute. The modifiers below a layer can change at any time and its\nmoves ride along, as long as they keep the vertices (Bend, Twist, FFD, Noise, other layers).\nThe group needs nothing from MaxFlow, so a file still shows its layers without the extension.\n\nA layer is edited in place. The base mesh takes the positions arriving at the layer plus its\nmoves; its own positions wait in ".maxflow_rest", the arriving ones in ".maxflow_input_<n>",\nand the layer and the modifiers below it stop showing in Edit Mode. Leaving the level stores\nthe difference as the layer\'s moves and puts the base positions back. The mesh attributes\nsay which layer is open, so undo, redo, reopening a file and leaving Edit Mode by any route\nall end in the same commit (sync).\n'
import bpy
import numpy as np
from bpy.app.handlers import persistent
GROUP = _msg('MaxFlow Edit Poly')
MARK = 'maxflow_edit_poly'
PREFIX = '.maxflow_edit_poly_'
REST = '.maxflow_rest'
INPUT = '.maxflow_input_'
INDEX = '.maxflow_index'
HIDDEN = 'maxflow_edit_poly_hidden'
STASH = 'maxflow_edit_poly_stash'
NAMES = (_msg('Edit Poly'), _msg('Edit Mesh'))
KEEPS_VERTICES = {'SHRINK', 'GROW', 'RING', 'LOOP', 'SELECT_ID', 'SET_ID', 'HIDE', 'UNHIDE', 'HIDE_UNSELECTED', 'RELAX', 'PLANAR', 'FLATTEN_X', 'FLATTEN_Y', 'FLATTEN_Z', 'OUTLINE', 'AUTO_SMOOTH', 'CLEAR_SMOOTH', 'FLIP', 'NORMALS', 'UV', 'REPEAT', 'NURMS'}
LAYER_ONLY_TIP = _msg('Edit Poly layers keep moves only: use this on the base Editable Poly')
_owner = object()

def node_group():
    group = next((g for g in bpy.data.node_groups if g.get(MARK) == 1 and g.bl_idname == _msg('GeometryNodeTree')), None)
    if group is not None:
        return group
    group = bpy.data.node_groups.new(GROUP, _msg('GeometryNodeTree'))
    group[MARK] = 1
    group.is_modifier = True
    group.description = _msg('MaxFlow Edit Poly layer: moves each vertex by the offset stored in the mesh attribute named by Layer')
    group.interface.new_socket(_msg('Geometry'), in_out='INPUT', socket_type=_msg('NodeSocketGeometry'))
    layer = group.interface.new_socket(_msg('Layer'), in_out='INPUT', socket_type=_msg('NodeSocketString'))
    if hasattr(layer, 'hide_in_modifier'):
        layer.hide_in_modifier = True
    group.interface.new_socket(_msg('Geometry'), in_out='OUTPUT', socket_type=_msg('NodeSocketGeometry'))
    (nodes, links) = (group.nodes, group.links)
    (source, result) = (nodes.new(_msg('NodeGroupInput')), nodes.new(_msg('NodeGroupOutput')))
    moves = nodes.new(_msg('GeometryNodeInputNamedAttribute'))
    moves.data_type = 'FLOAT_VECTOR'
    (move, remove) = (nodes.new(_msg('GeometryNodeSetPosition')), nodes.new(_msg('GeometryNodeRemoveAttribute')))
    for (node, x) in ((source, -400), (moves, -200), (move, 0), (remove, 200), (result, 400)):
        node.location = (x, 0)
    moves.location = (-200, -160)
    links.new(source.outputs[_msg('Layer')], moves.inputs[_msg('Name')])
    links.new(source.outputs[_msg('Geometry')], move.inputs[_msg('Geometry')])
    links.new(moves.outputs[_msg('Attribute')], move.inputs[_msg('Offset')])
    links.new(move.outputs[_msg('Geometry')], remove.inputs[_msg('Geometry')])
    links.new(source.outputs[_msg('Layer')], remove.inputs[_msg('Name')])
    links.new(remove.outputs[_msg('Geometry')], result.inputs[_msg('Geometry')])
    return group

def _socket(group):
    return next((item.identifier for item in group.interface.items_tree if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and (item.socket_type == _msg('NodeSocketString'))))

def is_layer(mod):
    return mod is not None and mod.type == 'NODES' and (mod.node_group is not None) and (mod.node_group.get(MARK) == 1)

def layer_name(mod):
    identifier = _socket(mod.node_group)
    inputs = getattr(getattr(mod, 'properties', None), 'inputs', None)
    if inputs is not None:
        return getattr(inputs, identifier).value
    return mod.get(identifier, '')

def _set_layer_name(mod, value):
    identifier = _socket(mod.node_group)
    inputs = getattr(getattr(mod, 'properties', None), 'inputs', None)
    if inputs is not None:
        getattr(inputs, identifier).value = value
    else:
        mod[identifier] = value

def layers(obj):
    return [mod for mod in obj.modifiers if is_layer(mod)] if obj is not None else []

def _users(mesh):
    return [obj for obj in bpy.data.objects if obj.data == mesh]

def _free_name(mesh):
    used = {a.name for a in mesh.attributes} | {layer_name(m) for obj in _users(mesh) for m in layers(obj)}
    n = 1
    while f'{PREFIX}{n}' in used:
        n += 1
    return f'{PREFIX}{n}'

def add(obj, name=_msg('Edit Poly')):
    mod = obj.modifiers.new(name, 'NODES')
    mod.node_group = node_group()
    _set_layer_name(mod, _free_name(obj.data))
    mod.show_in_editmode = True
    return mod

def ensure_unique(obj, mod):
    """A pasted or copied layer starts empty under its own attribute."""
    name = layer_name(mod)
    if not name.startswith(PREFIX) or any((layer_name(m) == name for m in layers(obj) if m != mod)):
        _set_layer_name(mod, _free_name(obj.data))

def remove(obj, mod):
    name = layer_name(mod)
    obj.modifiers.remove(mod)
    mesh = obj.data
    if mesh is not None and name in mesh.attributes and (not any((layer_name(m) == name for o in _users(mesh) for m in layers(o)))):
        mesh.attributes.remove(mesh.attributes[name])

def strip(obj):
    """Drop layer moves from a mesh about to be attached to another object."""
    mesh = obj.data
    names = [a.name for a in mesh.attributes if a.name.startswith(PREFIX)]
    if names and mesh.users > 1:
        obj.data = mesh = mesh.copy()
    for name in names:
        mesh.attributes.remove(mesh.attributes[name])

def _read(mesh, name):
    data = mesh.attributes[name].data
    values = np.empty(len(data) * 3, np.float32)
    data.foreach_get('vector', values)
    return values.reshape(-1, 3)

def _write(mesh, name, values):
    attr = mesh.attributes.get(name)
    if attr is not None and (attr.data_type != 'FLOAT_VECTOR' or attr.domain != 'POINT'):
        mesh.attributes.remove(attr)
        attr = None
    if attr is None:
        attr = mesh.attributes.new(name, 'FLOAT_VECTOR', 'POINT')
    attr.data.foreach_set('vector', np.ascontiguousarray(values, np.float32).ravel())

def _moves(mesh, name):
    attr = mesh.attributes.get(name)
    if attr is None or attr.data_type != 'FLOAT_VECTOR' or attr.domain != 'POINT':
        return np.zeros((len(mesh.vertices), 3), np.float32)
    return _read(mesh, name)

def _drop(mesh, *names):
    for name in names:
        attr = mesh.attributes.get(name)
        if attr is not None:
            mesh.attributes.remove(attr)

def editing(mesh):
    """The attribute name of the layer open on this mesh, or None."""
    attributes = getattr(mesh, 'attributes', None)
    if attributes is None:
        return None
    for attr in attributes:
        if attr.name.startswith(INPUT):
            return PREFIX + attr.name[len(INPUT):]
    return None

def editing_layer(obj):
    name = editing(obj.data) if obj is not None and obj.type == 'MESH' else None
    return next((m for m in layers(obj) if layer_name(m) == name), None) if name else None

def _arriving(context, obj, mod):
    """Positions arriving at the layer: the stack evaluated with the layer and the
    modifiers above it off. None when the modifiers below change the vertices."""
    stack = list(obj.modifiers)
    off = [m for m in stack[stack.index(mod):] if m.show_viewport]
    for m in off:
        m.show_viewport = False
    try:
        depsgraph = context.evaluated_depsgraph_get()
        depsgraph.update()
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            if mesh is None or len(mesh.vertices) != len(obj.data.vertices):
                return None
            return _read(mesh, 'position').copy()
        finally:
            evaluated.to_mesh_clear()
    finally:
        for m in off:
            m.show_viewport = True

def _hide(obj, mod):
    stack = list(obj.modifiers)
    hidden = {}
    for m in stack[:stack.index(mod) + 1]:
        hidden[m.name] = int(m.show_in_editmode)
        m.show_in_editmode = False
    obj[HIDDEN] = hidden

def _unhide(obj):
    hidden = obj.get(HIDDEN)
    if hidden is None:
        return
    for (name, value) in hidden.to_dict().items():
        mod = obj.modifiers.get(name)
        if mod is not None:
            mod.show_in_editmode = bool(value)
    del obj[HIDDEN]

def enter(context, obj, mod):
    """Open a layer for editing; the object must be in Object Mode. Returns an error or None."""
    mesh = obj.data
    if mesh.shape_keys is not None:
        return _dcc_format("{0}: an Edit Poly layer can't be edited on an object with shape keys (Morpher) yet", mod.name)
    if editing(mesh):
        return _dcc_format('{0}: another Edit Poly layer of this object is still open', mod.name)
    ensure_unique(obj, mod)
    arriving = _arriving(context, obj, mod)
    if arriving is None:
        return _dcc_format("{0}: a modifier below it changes the number of vertices, so it can't be edited yet. Move {1} below that modifier, or collapse the stack to it", mod.name, mod.name)
    name = layer_name(mod)
    moves = _moves(mesh, name)
    _write(mesh, REST, _read(mesh, 'position'))
    _write(mesh, INPUT + name[len(PREFIX):], arriving)
    index = mesh.attributes.new(INDEX, 'INT', 'POINT')
    index.data.foreach_set('value', np.arange(len(mesh.vertices), dtype=np.int32))
    mesh.attributes['position'].data.foreach_set('vector', (arriving + moves).ravel())
    mesh.update()
    _hide(obj, mod)
    return None

def commit(mesh):
    """Store the open layer's moves and put the base positions back; the mesh must not be in
    Edit Mode. Returns a message when vertices were added or deleted at the layer."""
    name = editing(mesh)
    if name is None:
        return None
    arriving_name = INPUT + name[len(PREFIX):]
    users = _users(mesh)
    message = None
    if REST in mesh.attributes and arriving_name in mesh.attributes:
        (edited, arriving, rest) = (_read(mesh, 'position'), _read(mesh, arriving_name), _read(mesh, REST))
        _write(mesh, name, edited - arriving)
        mesh.attributes['position'].data.foreach_set('vector', rest.ravel())
        index = mesh.attributes.get(INDEX)
        if index is not None:
            numbers = np.empty(len(mesh.vertices), np.int32)
            index.data.foreach_get('value', numbers)
            if not np.array_equal(numbers, np.arange(len(numbers))):
                from . import params
                for obj in users:
                    params.collapse(obj)
                message = _msg('Edit Poly keeps moves: the added or deleted vertices went to the base object')
    _drop(mesh, REST, arriving_name, INDEX)
    mesh.update()
    for obj in users:
        _unhide(obj)
    return message

def close_in_edit_mode(mesh):
    """Commit a layer still open in Edit Mode through bmesh, leaving the base in Edit Mode:
    for when MaxFlow is disabled with a layer open and nothing would commit it later."""
    import bmesh
    name = editing(mesh)
    if name is None or not mesh.is_editmode:
        return
    bm = bmesh.from_edit_mesh(mesh)
    vectors = bm.verts.layers.float_vector
    arriving_name = INPUT + name[len(PREFIX):]
    if vectors.get(REST) is not None and vectors.get(arriving_name) is not None:
        if vectors.get(name) is None:
            vectors.new(name)
        (moves, rest, arriving) = (vectors.get(name), vectors.get(REST), vectors.get(arriving_name))
        for v in bm.verts:
            v[moves] = v.co - v[arriving]
            v.co = v[rest]
        index = bm.verts.layers.int.get(INDEX)
        if index is not None and any((v[index] != i for (i, v) in enumerate(bm.verts))):
            from . import params
            for obj in _users(mesh):
                params.collapse(obj)
    for layer_name_ in (REST, arriving_name):
        layer = vectors.get(layer_name_)
        if layer is not None:
            vectors.remove(layer)
    index = bm.verts.layers.int.get(INDEX)
    if index is not None:
        bm.verts.layers.int.remove(index)
    bmesh.update_edit_mesh(mesh)
    for obj in _users(mesh):
        _unhide(obj)

def sync():
    """Commit every layer whose mesh left Edit Mode; re-hide the modifiers of a layer that
    came back into Edit Mode through redo. Returns the commit messages."""
    messages = []
    for mesh in bpy.data.meshes:
        name = editing(mesh)
        if name is None:
            continue
        if mesh.is_editmode:
            for obj in _users(mesh):
                if obj.mode == 'EDIT' and HIDDEN not in obj:
                    mod = next((m for m in layers(obj) if layer_name(m) == name), None)
                    if mod is not None:
                        _hide(obj, mod)
            continue
        message = commit(mesh)
        if message:
            messages.append(message)
    return messages

def leave(context, obj):
    """Leave Edit Mode and commit an open layer at once (not on the next notification)."""
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    return commit(obj.data) if obj.type == 'MESH' else None

def keep(mesh):
    """Layer moves of a primitive's mesh before its parameters rebuild it."""
    return {a.name: _read(mesh, a.name).copy() for a in mesh.attributes if a.name.startswith(PREFIX) and a.data_type == 'FLOAT_VECTOR' and (a.domain == 'POINT')}

def put_back(mesh, kept):
    """Restore layer moves after a rebuild with the same vertex count. Moves that no longer
    fit wait in the mesh, by vertex count, until that count returns (Max's segments)."""
    count = len(mesh.vertices)
    stash = mesh.get(STASH)
    stash = stash.to_dict() if stash is not None else {}
    for (name, moves) in kept.items():
        if len(moves) == count:
            _write(mesh, name, moves)
        else:
            stash[f'{name}|{len(moves)}'] = moves.ravel().tolist()
    for key in list(stash):
        (name, n) = key.rsplit('|', 1)
        if int(n) == count:
            if name not in kept or len(kept[name]) != count:
                _write(mesh, name, np.array(stash[key], np.float32).reshape(-1, 3))
            del stash[key]
    if stash:
        mesh[STASH] = stash
    elif STASH in mesh:
        del mesh[STASH]

def _report(messages):
    wm = getattr(bpy.context, 'window_manager', None)
    for message in messages:
        print(_msg('MaxFlow:'), message)
        if wm is not None and hasattr(wm, 'bsm'):
            wm.bsm.prompt = message

def _mode_changed():
    _report(sync())

@persistent
def _after_undo(*_):
    _report(sync())

@persistent
def _after_load(*_):
    subscribe()
    _report(sync())

def subscribe():
    bpy.msgbus.clear_by_owner(_owner)
    bpy.msgbus.subscribe_rna(key=(bpy.types.Object, 'mode'), owner=_owner, args=(), notify=_mode_changed)
HANDLERS = ((bpy.app.handlers.undo_post, _after_undo), (bpy.app.handlers.redo_post, _after_undo), (bpy.app.handlers.load_post, _after_load))

def register():
    for (collection, fn) in HANDLERS:
        if fn not in collection:
            collection.append(fn)
    subscribe()

def unregister():
    for (collection, fn) in HANDLERS:
        if fn in collection:
            collection.remove(fn)
    bpy.msgbus.clear_by_owner(_owner)
    try:
        for mesh in bpy.data.meshes:
            close_in_edit_mode(mesh)
        _report(sync())
    except (AttributeError, ReferenceError):
        pass
