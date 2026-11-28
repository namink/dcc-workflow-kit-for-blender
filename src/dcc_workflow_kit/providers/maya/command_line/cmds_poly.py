# SPDX-License-Identifier: GPL-3.0-or-later
"""maya.cmds look-alike: polygon commands. ``polyExtrudeFacet`` extrudes faces through the kit's extrusion, keeps
Maya's face ids and records a polyExtrudeFaceN node on the mesh (``HISTORY_PROP``); ``listHistory`` lists a
shape's extrusions and creation node, newest first; ``polyEvaluate`` counts vertices, edges, faces, triangles, UVs
and shells; ``compact_components`` writes Maya component ranges. Re-exported by cmds_misc.py."""

import re

import bmesh
import bpy
from mathutils import Vector

from . import cmds_shim as _shim
from .cmds_shim import _Flags, _flatten
from .cmds_nodes import HISTORY_PROP, _extrusion_nodes, select_nodes, unique_node_name

# --- polygon commands ------------------------------------------------------------------------------------------------

_COMPONENT = re.compile(r"^(.+)\.(f|vtx|e|map)\[(\d+)(?::(\d+))?\]$")


def _faces_of(args):
    """{object: [face ids]} of ``pCube1.f[1]`` / ``pCube1.f[0:2]`` names (the edit-mode selection without any)."""
    out = {}
    names = list(_flatten(args))
    if not names:
        for ob in _shim._selection():
            if ob.type == 'MESH':
                if ob.mode == 'EDIT':
                    bm = bmesh.from_edit_mesh(ob.data)
                    ids = [f.index for f in bm.faces if f.select]
                else:
                    ids = [p.index for p in ob.data.polygons if p.select]
                if ids:
                    out[ob] = ids
        return out
    for n in names:
        m = _COMPONENT.match(str(n))
        if m is None:
            ob = _shim._object(n)          # a whole mesh: every face (Maya extrudes them all)
            if ob.type == 'MESH':
                out.setdefault(ob, []).extend(range(len(ob.data.polygons)))
            continue
        ob = _shim._object(m.group(1))
        if m.group(2) != "f":
            raise RuntimeError(f"polyExtrudeFacet: {n} is not a face")
        a = int(m.group(3))
        b = int(m.group(4)) if m.group(4) is not None else a
        out.setdefault(ob, []).extend(range(a, b + 1))
    return out


def compact_components(ob_name, kind, ids):
    """Maya's component names: consecutive ids merge into ``f[a:b]``."""
    ids = sorted(set(ids))
    out, i = [], 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
            j += 1
        out.append(f"{ob_name}.{kind}[{ids[i]}]" if i == j else f"{ob_name}.{kind}[{ids[i]}:{ids[j]}]")
        i = j + 1
    return out


def _extrude_object(context, ob, ids, params, world_t, name, history):
    """Maya polyExtrudeFace on faces ``ids`` of ``ob`` (``operators/extrude_face.py`` geometry); the extruded faces keep
    their Maya ids and the new side faces come after them. Returns the node name (None without history)."""
    from ..operators import extrude, units
    me = ob.data
    in_edit = ob.mode == 'EDIT'
    if in_edit:
        bm = bmesh.from_edit_mesh(me)
    else:
        bm = bmesh.new()
        bm.from_mesh(me)
    try:
        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
        faces = [bm.faces[i] for i in sorted(set(ids)) if 0 <= i < len(bm.faces)]
        if not faces:
            raise RuntimeError("polyExtrudeFacet: no faces to extrude")
        pre = bm.copy()
        unit = units.maya_unit(context.scene)
        keep_index = {fc: fc.index for fc in bm.faces}
        by_shape = {frozenset(extrude._key(v.co) for v in fc.verts): fc.index for fc in faces}
        caps, levels, vectors = extrude.extrude_topology(bm, faces, params["divisions"],
                                                         params["keep_faces_together"], **extrude.mesh_axes(ob))
        cap_index = {cap: by_shape.get(frozenset(extrude._key(v.co) for v in cap.verts)) for cap in caps}
        moved = extrude.moved_vertices(levels, vectors, unit)
        extrude.place(moved, params["thickness"], params["local_translate_z"], params["offset"],
                      **{k: params[k] for k in extrude.MANIP_FIELDS})
        if world_t.length:
            local = ob.matrix_world.to_3x3().inverted_safe() @ (world_t * unit)
            for v in {v for cap in caps for v in cap.verts}:
                v.co += local
        # Maya ids: the extruded faces keep theirs, new faces go after the old ones (bmesh made new caps); an
        # extrusion of the whole mesh keeps the old faces as its bottom, first among the new ones
        big = len(keep_index) + len(bm.faces) + 1
        bottoms = {fc for fc in faces if fc.is_valid}
        order = {}
        for i, fc in enumerate(bm.faces):
            if fc in cap_index and cap_index[fc] is not None:
                order[fc] = cap_index[fc]
            elif fc in bottoms:
                order[fc] = len(keep_index) + keep_index[fc]
            elif fc in keep_index:
                order[fc] = keep_index[fc]
            else:
                order[fc] = big + i
        extrude.deselect_all(bm)
        for cap in caps:
            cap.select_set(True)
        bm.select_flush_mode()
        rank = {fc: i for i, fc in enumerate(sorted(bm.faces, key=lambda fc: order[fc]))}
        cap_ranks = [rank[cap] for cap in caps]
        # sorting moves the elements in memory: Python face references afterwards point elsewhere
        bm.faces.sort(key=lambda fc: order[fc])
        bm.faces.index_update()
        bm.faces.ensure_lookup_table()
        bm.verts.index_update()
        caps = [bm.faces[i] for i in cap_ranks]
        bm.normal_update()
        node = None
        if history:
            node = extrude.next_name(context.scene)
            if name:
                node = unique_node_name(str(name))
            rec = extrude.Record(node, pre, {k: params[k] for k in extrude.FACE.all_fields})
            rec.mesh_uid = me.session_uid
            extrude._store(rec, bm, caps, moved, rec.params)
            old = extrude.RECORDS.get(ob.name)
            if old is not None and old is not rec:
                old.free()
            extrude.keep(context, ob, rec)
            if extrude.RECORDS.get(ob.name) is not rec:
                node = None                  # Construction History off
        else:
            pre.free()
        if in_edit:
            bmesh.update_edit_mesh(me)
        else:
            bm.to_mesh(me)
            me.update()
    finally:
        if not in_edit:
            bm.free()
    if node is not None:
        entries = [e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in me.get(HISTORY_PROP, ())]
        values = dict(params, translate_x=world_t.x, translate_y=world_t.y, translate_z=world_t.z)
        entries.append({"name": node, "type": extrude.NODE, "values": values})
        me[HISTORY_PROP] = entries
    return node


def polyExtrudeFacet(*args, **kwargs):
    """``polyExtrudeFacet pCube1.f[1] -ltz 2`` = Maya polyExtrudeFace through the kit's extrusion (the In-View
    Editor / Channel Box INPUTS show the node); returns [polyExtrudeFaceN]. ``-t`` / ``-tx`` … is a world move of
    the extruded faces in the kit's axes (Blender's, like ``move``); the faces stay selected."""
    from ..operators import extrude
    f = _Flags("polyExtrudeFacet", kwargs)
    params = dict(extrude.DEFAULTS, **extrude.MANIP_DEFAULTS)
    for long, short, key in (("localTranslateZ", "ltz", "local_translate_z"),
                             ("localTranslateX", "ltx", "local_translate_x"),
                             ("localTranslateY", "lty", "local_translate_y"),
                             ("thickness", "tk", "thickness"), ("offset", "off", "offset"),
                             ("divisions", "dv", "divisions"), ("keepFacesTogether", "kft", "keep_faces_together")):
        v = f.get(long, short)
        if v is None and short == "tk":
            v = f.get("thk")
        if v is not None:
            params[key] = v
    ls = f.get("localScale", "ls")
    if ls is not None:
        params.update(local_scale_x=ls[0], local_scale_y=ls[1], local_scale_z=ls[2])
    t = Vector(f.get("translate", "t") or (0.0, 0.0, 0.0))
    for i, (long, short) in enumerate((("translateX", "tx"), ("translateY", "ty"), ("translateZ", "tz"))):
        v = f.get(long, short)
        if v is not None:
            t[i] = float(v)
    name = f.get("name", "n")
    history = f.get("constructionHistory", "ch", True)
    for long, short in (("worldSpace", "ws"), ("smoothingAngle", "sma"), ("localCenter", "lc"),
                        ("localDirection", "ld"), ("random", "ran"), ("pivot", "pvt"), ("rotate", "ro"),
                        ("scale", "s"), ("caching", "cch"), ("nodeState", "nds"), ("reverseAllFaces", "raf")):
        f.get(long, short)
    f.done()
    params["divisions"] = max(1, int(params["divisions"]))
    params["keep_faces_together"] = bool(params["keep_faces_together"])
    for k in params:
        if k not in ("divisions", "keep_faces_together"):
            params[k] = float(params[k])
    targets = _faces_of(args)
    if not targets:
        raise RuntimeError("polyExtrudeFacet: no faces given or selected")
    context = bpy.context
    from ..operators import prim_history
    history = bool(history) and prim_history.history_on(context)
    out, picked = [], []
    for ob, ids in targets.items():
        node = _extrude_object(context, ob, ids, params, t, name, history)
        if node is not None:
            out.append(node)
        picked += compact_components(ob.name, "f", ids)
    sel = _shim._selection()
    select_nodes([o.name for o in sel] + picked, keep_objects=True)
    return out


def polyEvaluate(*args, **kwargs):
    """``polyEvaluate -v / -e / -f / -t / -uv``: counts of the mesh (Maya's shape = the kit's mesh without its
    display-only smooth preview); several flags / none = a dict like Maya's."""
    f = _Flags("polyEvaluate", kwargs)
    wanted = []
    for long, short, key in (("vertex", "v", "vertex"), ("edge", "e", "edge"), ("face", "f", "face"),
                             ("triangle", "t", "triangle"), ("uvcoord", "uv", "uvcoord"),
                             ("shell", "s", "shell")):
        if f.get(long, short, False):
            wanted.append(key)
    f.done()
    obs = _shim._objects(args)
    counts = {"vertex": 0, "edge": 0, "face": 0, "triangle": 0, "uvcoord": 0, "shell": 0}
    for ob in obs:
        if ob.type != 'MESH':
            raise RuntimeError(f"polyEvaluate: {ob.name} is not a polygon mesh")
        if ob.mode == 'EDIT':
            ob.update_from_editmode()
        me = ob.data
        counts["vertex"] += len(me.vertices)
        counts["edge"] += len(me.edges)
        counts["face"] += len(me.polygons)
        counts["triangle"] += sum(len(p.vertices) - 2 for p in me.polygons)
        uv = me.uv_layers.active
        if uv is not None:
            counts["uvcoord"] += len({(p.vertex_index, round(d.uv[0], 6), round(d.uv[1], 6))
                                      for p, d in zip(me.loops, uv.data)})
        counts["shell"] += _shells(me)
    if len(wanted) == 1:
        return counts[wanted[0]]
    return {k: counts[k] for k in (wanted or counts)}


def _shells(me):
    parent = list(range(len(me.vertices)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for e in me.edges:
        a, b = find(e.vertices[0]), find(e.vertices[1])
        if a != b:
            parent[a] = b
    return len({find(i) for i in range(len(me.vertices))})


def listHistory(*args, **kwargs):
    """``listHistory`` = the shape, then its history newest first: the extrusions the kit made, then the creation
    node (Maya: -pdo polyExtrudeFace3 2 1 polyCube1). ``-pdo`` leaves the DAG nodes out."""
    from ..operators import prim_history
    f = _Flags("listHistory", kwargs)
    pdo = f.get("pruneDagObjects", "pdo", False)
    f.get("future", "f", False)
    f.get("levels", "lv")
    f.done()
    out = []
    for ob in _shim._objects(args):
        shape = _shim.shape_of(ob)
        if shape and not pdo:
            out.append(shape)
        if ob.type == 'MESH':
            out += [n for n, _t, _v in reversed(_extrusion_nodes(ob))]
        node = prim_history.node_dict(prim_history.owner_of(ob))
        if node is not None and node.get("name"):
            out.append(node["name"])
    return out or None
