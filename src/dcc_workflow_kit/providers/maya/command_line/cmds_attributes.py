# SPDX-License-Identifier: GPL-3.0-or-later
"""maya.cmds look-alike: attributes. ``attributeQuery`` (exists, keyable, names, type, limits, children / parent)
for object transform channels (``TRANSFORM_ATTRS``, ``nice_name``), custom attributes and non-DAG nodes;
``_node_attr_value`` / ``_set_node_attr`` read and write the attributes of materials, file textures, extrusion and
creation nodes for the getAttr / setAttr / objExists extension in cmds_misc.py."""

import re

import bpy

from . import cmds_shim as _shim
from .cmds_shim import _Flags, _flatten
from .cmds_nodes import FILE_NAME_PROP, _cb, _dag, _node

# --- attributeQuery --------------------------------------------------------------------------------------------------

# Maya transform attributes: long -> (short, type, parent, default, min, max, keyable)
_XYZ = ("X", "Y", "Z")
TRANSFORM_ATTRS = {
    "visibility": ("v", "bool", None, 1.0, 0.0, 1.0, True),
    "rotateOrder": ("ro", "enum", None, 0.0, 0.0, 5.0, False),
}
for _long, _short, _type, _dv in (("translate", "t", "doubleLinear", 0.0), ("rotate", "r", "doubleAngle", 0.0),
                                  ("scale", "s", "double", 1.0)):
    TRANSFORM_ATTRS[_long] = (_short, "double3", None, _dv, None, None, False)
    for _a in _XYZ:
        TRANSFORM_ATTRS[_long + _a] = (_short + _a.lower(), _type, _long, _dv, None, None, True)
_SHORT = {v[0]: k for k, v in TRANSFORM_ATTRS.items()}


def nice_name(long):
    """Maya's nice name: camelCase split into capitalised words (translateX -> "Translate X", speed -> "Speed")."""
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", long)
    return words[:1].upper() + words[1:]


class _Attr:
    def __init__(self, long, short, typ, keyable, default, lo, hi, children=None, parent=None):
        self.long, self.short, self.type, self.keyable = long, short, typ, keyable
        self.default, self.min, self.max, self.children, self.parent = default, lo, hi, children, parent


def _attr_of(ob, name):
    """The Maya attribute ``name`` (long or short) of object ``ob``, or None."""
    cb = _cb()
    long = _SHORT.get(name, name)
    if long in TRANSFORM_ATTRS:
        short, typ, parent, dv, lo, hi, keyable = TRANSFORM_ATTRS[long]
        children = [long + a for a in _XYZ] if typ == "double3" else None
        if keyable:
            key = _shim.channel_keys(ob, long)
            keyable = bool(key) and _shim._keyable(ob, key[0])
        return _Attr(long, short, typ, keyable, dv, lo, hi, children, parent)
    if name in ob.keys() and not name.startswith("_"):
        value = ob[name]
        if isinstance(value, str):
            return _Attr(name, name, "typed", False, None, None, None)
        from ..operators import rig_tools
        kind, use_min, lo, use_max, hi, dv = rig_tools.limits(ob, name)
        typ = {"BOOL": "bool", "INT": "long"}.get(kind, "double")
        if kind == 'BOOL':
            use_min = use_max = True
            lo, hi = 0.0, 1.0
        keyable = _shim._keyable(ob, cb.CUSTOM_PREFIX + name)
        return _Attr(name, name, typ, keyable, float(dv), float(lo) if use_min else None,
                     float(hi) if use_max else None)
    return None


def attributeQuery(*args, **kwargs):
    """``attributeQuery <attr> -node <node>``: exists / keyable / names / type / limits / default of an attribute
    (Maya: lists for min / max / listDefault; a missing attribute answers exists False, other flags raise)."""
    f = _Flags("attributeQuery", kwargs)
    node = f.get("node", "n")
    flags = {}
    for long, short in (("exists", "ex"), ("keyable", "k"), ("shortName", "sn"), ("longName", "ln"),
                        ("niceName", "nn"), ("attributeType", "at"), ("minExists", "mne"), ("maxExists", "mxe"),
                        ("minimum", "min"), ("maximum", "max"), ("listDefault", "ld"), ("listChildren", "lc"),
                        ("listParent", "lp"), ("hidden", "h"), ("writable", "w"), ("readable", "r"),
                        ("numberOfChildren", "nc"), ("multi", "m")):
        v = f.get(long, short, False)
        if v:
            flags[long] = v
    f.get("type", "typ")
    f.done()
    names = list(_flatten(args))
    if len(names) != 1 or node is None:
        raise RuntimeError("attributeQuery: an attribute name and -node are needed")
    name = str(names[0])
    dag = _dag(node)
    if dag is None:
        found = _node(node)
        if found is None:
            raise RuntimeError(f"attributeQuery: No object matches name: {node}")
        attr = None
        if _node_attr_value(found, name) is not _MISSING:
            attr = _Attr(name, name, "double", True, None, None, None)
    else:
        attr = _attr_of(dag[1], name)
    if "exists" in flags:
        return attr is not None
    if attr is None:
        raise RuntimeError(f"attributeQuery: Node '{node}' does not have attribute '{name}'")
    for flag in flags:
        if flag == "keyable":
            return bool(attr.keyable)
        if flag == "shortName":
            return attr.short
        if flag == "longName":
            return attr.long
        if flag == "niceName":
            return nice_name(attr.long)
        if flag == "attributeType":
            return attr.type
        if flag == "minExists":
            return attr.min is not None
        if flag == "maxExists":
            return attr.max is not None
        if flag in ("minimum", "maximum"):
            v = attr.min if flag == "minimum" else attr.max
            if v is None:
                raise RuntimeError(f"attributeQuery: '{node}.{name}' has no {flag}")
            return [float(v)]
        if flag == "listDefault":
            if attr.default is None:
                return None
            n = 3 if attr.type == "double3" else 1
            return [float(attr.default)] * n
        if flag == "listChildren":
            return list(attr.children) if attr.children else None
        if flag == "listParent":
            return [attr.parent] if attr.parent else None
        if flag == "numberOfChildren":
            return len(attr.children or ())
        if flag == "multi":
            return False
        if flag == "hidden":
            return False
        return True              # readable / writable
    raise TypeError("attributeQuery needs a query flag (exists, keyable, shortName, ...)")


# --- getAttr / setAttr on shading and history nodes ------------------------------------------------------------------

_MISSING = object()
# Maya material attribute -> material.maya_input name (colours) or Material property (numbers); Standard Surface
# attribute names (ui/ae_layout.STANDARD_SURFACE_ATTRS) reach the Principled input of that name too
_COLOR_ATTRS = {"color": "Base Color", "incandescence": "Emission Color", "specularColor": "Specular Tint"}
_NUMBER_ATTRS = {"diffuse": "allset_diffuse"}
_SOCKET_NUMBERS = {"specularRollOff": "Specular IOR Level"}


def _standard_surface_socket(mat, attr):
    """The Principled input a Standard Surface attribute name stands for (a colour or a number), or None."""
    from ..operators import material
    from ..ui import ae_layout
    name = dict(ae_layout.STANDARD_SURFACE_ATTRS).get(attr)
    if name is None:
        return None
    sock = material.maya_input(mat, name)
    return sock if sock is not None and hasattr(sock, "default_value") else None
# polyExtrudeFace attribute -> kit record field
EXTRUDE_ATTRS = {"thickness": "thickness", "localTranslateZ": "local_translate_z", "offset": "offset",
                 "divisions": "divisions", "keepFacesTogether": "keep_faces_together",
                 "localTranslateX": "local_translate_x", "localTranslateY": "local_translate_y",
                 "localScaleX": "local_scale_x", "localScaleY": "local_scale_y", "localScaleZ": "local_scale_z",
                 "translateX": "translate_x", "translateY": "translate_y", "translateZ": "translate_z"}
_EXTRUDE_SHORT = {"thk": "thickness", "ltz": "localTranslateZ", "off": "offset", "dv": "divisions",
                  "kft": "keepFacesTogether", "ltx": "localTranslateX", "lty": "localTranslateY",
                  "tx": "translateX", "ty": "translateY", "tz": "translateZ"}
_EXTRUDE_LENGTHS = {"thickness", "local_translate_z", "offset", "local_translate_x", "local_translate_y"}


def _node_attr_value(found, attr):
    """Maya value of ``found.attr``, or _MISSING."""
    from ..operators import material, prim_history
    if found.kind == 'MATERIAL':
        mat = found.data
        if attr in _COLOR_ATTRS:
            sock = material.maya_input(mat, _COLOR_ATTRS[attr])
            if sock is None:
                return _MISSING
            return [tuple(float(c) for c in sock.default_value[:3])]
        if attr in _NUMBER_ATTRS:
            return float(getattr(mat, _NUMBER_ATTRS[attr]))
        if attr in _SOCKET_NUMBERS:
            sock = material.maya_input(mat, _SOCKET_NUMBERS[attr])
            return _MISSING if sock is None else float(sock.default_value)
        sock = _standard_surface_socket(mat, attr)
        if sock is not None:
            v = sock.default_value
            return [tuple(float(c) for c in v[:3])] if hasattr(v, "__len__") else float(v)
        return _MISSING
    if found.kind == 'TEXTURE':
        if attr in ("fileTextureName", "ftn"):
            tex = found.data.nodes.get("file")
            if tex is not None and tex.image is not None:
                return tex.image.filepath
            return str(found.data.get(FILE_NAME_PROP, ""))
        return _MISSING
    if found.kind == 'EXTRUDE':
        long = _EXTRUDE_SHORT.get(attr, attr)
        key = EXTRUDE_ATTRS.get(long)
        if key is None:
            return _MISSING
        from ..operators import extrude
        default = dict(extrude.DEFAULTS, **extrude.MANIP_DEFAULTS).get(key, 0.0)
        value = found.data.get(key, default)
        return bool(value) if key == "keep_faces_together" else int(value) if key == "divisions" else float(value)
    if found.kind == 'HISTORY':
        values = prim_history.attrs(found.data)
        return values[attr] if attr in values else _MISSING
    return _MISSING


def _set_node_attr(found, attr, values):
    from ..operators import material
    v = list(_flatten(values))
    if found.kind == 'MATERIAL':
        mat = found.data
        if attr in _COLOR_ATTRS and len(v) == 3:
            sock = material.maya_input(mat, _COLOR_ATTRS[attr])
            if sock is not None:
                sock.default_value = (*[float(x) for x in v], 1.0)
                if attr == "color":
                    material.sync_display(mat)
                return True
        if attr in _NUMBER_ATTRS and len(v) == 1:
            setattr(mat, _NUMBER_ATTRS[attr], float(v[0]))
            return True
        if attr in _SOCKET_NUMBERS and len(v) == 1:
            sock = material.maya_input(mat, _SOCKET_NUMBERS[attr])
            if sock is not None:
                sock.default_value = float(v[0])
                return True
        sock = _standard_surface_socket(mat, attr)
        if sock is not None:
            n = len(sock.default_value) if hasattr(sock.default_value, "__len__") else 1
            if n == 1 and len(v) == 1:
                sock.default_value = float(v[0])
            elif n == 4 and len(v) == 3:
                sock.default_value = (*[float(x) for x in v], 1.0)
            elif n == len(v):
                sock.default_value = [float(x) for x in v]
            else:
                return False
            material.sync_display(mat)
            return True
    if found.kind == 'TEXTURE' and attr in ("fileTextureName", "ftn") and len(v) == 1:
        import os
        path = str(v[0])
        found.data[FILE_NAME_PROP] = path
        tex = found.data.nodes.get("file")
        if tex is not None:
            tex.image = bpy.data.images.load(path, check_existing=True) if path and os.path.isfile(path) else None
        return True
    return False
