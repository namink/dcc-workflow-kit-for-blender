# SPDX-License-Identifier: GPL-3.0-or-later
"""maya.cmds look-alike 3 (Issue #122): node types, attribute queries, units, sets, shading nodes, polygon
queries / extrude, camera.

Everything goes through the kit's own data so a script gives what the menus give:

- Maya nodes that aren't DAG objects (``_node``): materials (``operators/material.py``; Blender's materials,
  with the Maya type an older kit version recorded), a ``file`` texture = a Shader node group holding an Image Texture node (outputs
  ``outColor`` / ``outAlpha``; Blender has no free-standing shader node, a group can be shared by every
  material it is connected to like Maya's node), sets = kit sets (``operators/sets.py``), shading groups =
  ``<material>SG`` (``material.shading_group_name``), initialShadingGroup = the shapes without a material, creation nodes (``prim_history``),
  extrusions (``operators/extrude_record.py`` records + the per-mesh list ``HISTORY_PROP`` the commands keep), constraints
  (``cb_inputs.constraint_node_name``), bones = joints.
- ``currentUnit`` = the scene's unit settings / frame rate (Maya's working units are the scene's display units);
  ``ls`` / ``getAttr`` / ``setAttr`` / ``select`` / ``objExists`` learn these nodes in
  ``_extend_shim`` (the shim's versions handle DAG objects only).

Code: cmds_nodes (non-DAG nodes, nodeType / objectType), cmds_attributes (attributeQuery, node attribute values),
cmds_units (currentUnit), cmds_sets_shading (sets, shadingNode, texture connections), cmds_poly (polyExtrudeFacet,
polyEvaluate, listHistory); this module keeps exactWorldBoundingBox, camera and ``_extend_shim`` and re-exports the
commands for cmds_shim.
"""

import bpy

from . import cmds_shim as _shim
from .cmds_nodes import split_plug
from .cmds_nodes import (HISTORY_PROP, TEXTURE_PROP, FILE_NAME_PROP, DEFAULT_SETS, DEFAULT_NODES, CHAINS, Node,
                         _chain, _dag, _node, _materials, _material_type, _textures, _shading_groups,
                         _extrusion_nodes, nodeType, objectType, unique_node_name, _EXTRA, _selection_signature,
                         select_nodes, extra_selection)  # noqa: F401
from .cmds_attributes import (TRANSFORM_ATTRS, nice_name, attributeQuery, _MISSING, EXTRUDE_ATTRS,
                              _node_attr_value, _set_node_attr)  # noqa: F401
from .cmds_units import LINEAR, ANGLE, TIME, currentUnit  # noqa: F401
from .cmds_sets_shading import (_set_members, sets, new_file_texture, shadingNode, connect_texture,
                                shading_sources)  # noqa: F401
from .cmds_poly import compact_components, polyExtrudeFacet, polyEvaluate, listHistory  # noqa: F401

_Flags = _shim._Flags
_flatten = _shim._flatten


def exactWorldBoundingBox(*args, **kwargs):
    """World bounding box of the shapes' points (evaluated, with everything under the objects), Maya units, in the
    kit's axes like ``xform -q -bb`` (xmin ymin zmin xmax ymax zmax)."""
    f = _Flags("exactWorldBoundingBox", kwargs)
    f.get("calculateExactly", "ce", False)
    f.get("ignoreInvisible", "ii", False)
    f.done()
    obs = _shim._objects(args)
    context = bpy.context
    context.view_layer.update()
    dg = context.evaluated_depsgraph_get()
    pts = []
    for ob in obs:
        for o in [ob, *ob.children_recursive]:
            if o.mode == 'EDIT' and o.type == 'MESH':
                o.update_from_editmode()
            ev = o.evaluated_get(dg)
            if o.type == 'MESH' and len(ev.data.vertices):
                mw = ev.matrix_world
                pts += [mw @ v.co for v in ev.data.vertices]
            elif o.type != 'MESH':
                pts += _shim._corners(o)
    if not pts:
        return [0.0] * 6
    k = _shim.linear_factor()
    return [min(p[i] for p in pts) / k for i in range(3)] + [max(p[i] for p in pts) / k for i in range(3)]


def camera(*args, **kwargs):
    """``camera`` = Create > Camera (``create.KINDS['CAMERA']``: camera1 / cameraShape1, a 35 mm lens on 36 x 24 mm
    film, level like Maya's) with Fit Resolution Gate Horizontal, like Maya's ``camera`` command (the menu's camera
    starts with Fill); selected; returns [transform, shape]."""
    from ..operators import create, film_fit
    f = _Flags("camera", kwargs)
    focal = f.get("focalLength", "fl")
    near = f.get("nearClipPlane", "ncp")
    far = f.get("farClipPlane", "fcp")
    ortho = f.get("orthographic", "o")
    width = f.get("orthographicWidth", "ow")
    f.get("position", "p")
    f.done()
    if args:
        raise RuntimeError("camera: editing an existing camera is not supported")
    context = bpy.context
    ob = create.create(context, 'CAMERA')
    data = ob.data
    film_fit.set_fit(data, 'HORIZONTAL')
    k = _shim.linear_factor()
    if focal is not None:
        data.lens = float(focal)
    if near is not None:
        data.clip_start = float(near) * k
    if far is not None:
        data.clip_end = float(far) * k
    if ortho is not None:
        data.type = 'ORTHO' if ortho else 'PERSP'
    # the camera command's own Orthographic Width is 10 (the Create menu's camera: 30)
    data.ortho_scale = (10.0 if width is None else float(width)) * k
    _shim._view_layer()
    _shim._select_only([ob])
    return [ob.name, _shim.shape_of(ob)]


# --- non-DAG selection, ls / select / getAttr / setAttr / objExists for these nodes ----------------------------------

def _node_list():
    """Every non-DAG Maya node: (name, type)."""
    from ..operators import sets as kit_sets
    out = [(m.name, _material_type(m)) for m in _materials()]
    out += [(g.name, g[TEXTURE_PROP]) for g in _textures()]
    out += [(c.name, "objectSet") for c in kit_sets.all_sets()]
    out += list(DEFAULT_SETS.items()) + [(n, "shadingEngine") for n in _shading_groups()]
    out += list(DEFAULT_NODES.items())
    return out


# Maya material types of older kit materials (their recorded type) besides the surface shaders new materials stand for
_OLD_TYPES = {"surfaceShader", "rampShader", "layeredShader", "useBackground"}


def _material_types():
    from ..operators import material
    return set(material.SURFACE_TYPES) | _OLD_TYPES | {"material"}


def _extend_shim():
    """Teach the shim's ls / select / getAttr / setAttr / objExists the non-DAG nodes above (they stay the shim's
    for DAG objects)."""
    ls0, select0, get0, set0, exists0 = _shim.ls, _shim.select, _shim.getAttr, _shim.setAttr, _shim.objExists

    def ls(*args, **kwargs):
        kw = dict(kwargs)
        mats = kw.pop("materials", kw.pop("mat", False))
        texs = kw.pop("textures", kw.pop("tex", False))
        typ = kw.get("type", kw.get("typ"))
        names = list(_flatten(args))
        dag_names = [n for n in names if any(c in str(n) for c in "*?") or _dag(n) is not None]
        node_names = [n for n in names if n not in dag_names]
        if mats or texs:
            out = [n for n, t in _node_list() if (mats and t in _material_types()) or (texs and t == "file")]
            return [n for n in out if not names or n in node_names]
        types = [] if typ is None else list(typ) if isinstance(typ, (list, tuple)) else [typ]
        if names and not dag_names:
            out = []
        elif names:
            out = ls0(*dag_names, **kw)
        else:
            out = ls0(**kw)
        extra = []
        if kw.get("selection") or kw.get("sl"):
            extra = extra_selection() if not names else []
        elif types:
            extra = sorted(n for n, t in _node_list() if any(x in _chain(t) for x in types))
        for n in node_names:
            found = _node(n)
            if found is not None and (not types or any(x in _chain(found.type) for x in types)):
                extra.append(found.name)
        return out + [n for n in extra if n not in out]

    def select(*args, **kwargs):
        names = list(_flatten(args))
        dag, nodes = [], []
        for n in names:
            found = None if (any(c in str(n) for c in "*?") or _dag(n) is not None) else _node(n)
            if found is not None and found.kind == 'SET':
                dag += _set_members(found)          # Maya: select <set> = its members
            elif found is not None:
                nodes.append(found.name)
            else:
                dag.append(n)
        if names and not dag and nodes and not kwargs:
            result = select0(clear=True)
        else:
            result = select0(*dag, **kwargs) if (dag or not names) else None
        _EXTRA["items"], _EXTRA["sig"] = [], None
        if nodes:
            _EXTRA["items"], _EXTRA["sig"] = nodes, _selection_signature()
        return result

    def getAttr(attr, **kwargs):
        text = str(attr)
        node, name = split_plug(text)
        if name and _dag(node) is None:
            found = _node(node)
            if found is not None:
                value = _node_attr_value(found, name)
                if value is not _MISSING:
                    if kwargs.get("type") or kwargs.get("typ"):
                        return "float3" if isinstance(value, list) else "string" if isinstance(value, str) else \
                            "bool" if isinstance(value, bool) else "long" if isinstance(value, int) else "float"
                    return value
        return get0(attr, **kwargs)

    def setAttr(attr, *values, **kwargs):
        text = str(attr)
        node, name = split_plug(text)
        if name and _dag(node) is None:
            found = _node(node)
            if found is not None:
                kw = {k: v for k, v in kwargs.items() if k not in ("type", "typ")}
                if not kw and _set_node_attr(found, name, values):
                    return None
        return set0(attr, *values, **kwargs)

    def objExists(name, **kwargs):
        if exists0(name, **kwargs):
            return True
        node, attr = split_plug(name)
        found = _node(node)
        if found is None:
            return False
        return not attr or _node_attr_value(found, attr) is not _MISSING

    for fn, old in ((ls, ls0), (select, select0), (getAttr, get0), (setAttr, set0), (objExists, exists0)):
        fn.__doc__ = old.__doc__
        fn.__name__ = old.__name__
        fn.__wrapped__ = old
        setattr(_shim, old.__name__, fn)


_extend_shim()
