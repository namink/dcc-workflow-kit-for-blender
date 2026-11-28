# SPDX-License-Identifier: GPL-3.0-or-later
"""maya.cmds look-alike: connectAttr, disconnectAttr, isConnected, listConnections and connectionInfo on the
Connection Editor's connections (drivers with Maya's unit conversion, ui/connection_editor.py); a file texture to
material plug goes to cmds_sets_shading.py. ``connections`` lists every kit connection in the scene. Re-exported by
cmds_rig.py."""

import bpy

from .cmds_shim import _Flags, _flatten, _object, _selection, _view_layer
from .cmds_rig_common import _LONG, _KEY, _cb, _foreign_keys


def _ce():
    from ..ui import connection_editor
    return connection_editor


# --- connections (drivers with variable ``cn``, ui/connection_editor.py) -------------------------------------------

def _plug(text):
    """(object, Maya long attribute name) of ``node.attr``."""
    text = str(text)
    if "." not in text:
        raise RuntimeError(f"Expected node.attribute, got '{text}'")
    node, attr = text.split(".", 1)
    attr = attr.rsplit(".", 1)[-1]               # pCube1.translate.translateX
    ob = _object(node)
    long = _LONG.get(attr, attr)
    ce = _ce()
    if long not in ce.COMPOUNDS and ce.resolve(ob, long) is None:
        raise RuntimeError(f"No attribute '{attr}' on {ob.name}")
    return ob, long


def _plug_text(ob, long):
    """Maya's message form: a compound child with its parent (pCube1.translate.translateX)."""
    for comp, leaves in _ce().COMPOUNDS.items():
        if long in leaves:
            return f"{ob.name}.{comp}.{long}"
    return f"{ob.name}.{long}"


def connections():
    """Every kit connection in the scene: [(source object, source leaf, destination object, destination leaf)]."""
    ce = _ce()
    out = []
    for ob in bpy.context.scene.objects:
        if ob is None or ob.animation_data is None:
            continue
        for fc in ob.animation_data.drivers:
            leaf = next((n for n, (p, i, _k) in ce.SIMPLE.items() if p == fc.data_path and
                         (i < 0 or i == fc.array_index)), None)
            if leaf is None and fc.data_path.startswith('["') and fc.data_path.endswith('"]'):
                leaf = fc.data_path[2:-2]
            if leaf is None:
                continue
            src = ce.source_of(ob, leaf)
            if src is not None:
                out.append((src[0], src[1], ob, leaf))
    return out


def _leaf_key(ob, leaf):
    return _KEY.get(leaf) or (_cb().CUSTOM_PREFIX + leaf)


def connectAttr(*args, **kwargs):
    """``connectAttr src.attr dst.attr``: ``dst`` follows ``src`` (a compound child by child, Maya's unit
    conversion). A connected or constrained destination is an error unless ``-f`` (which replaces the connection).
    Returns Maya's message "Connected a.translate.translateX to b.translate.translateY."."""
    f = _Flags("connectAttr", kwargs)
    force = f.get("force", "f", False)
    f.get("lock", "l", False)
    f.get("nextAvailable", "na", False)
    f.done()
    plugs = [str(a) for a in _flatten(args)]
    if len(plugs) != 2:
        raise RuntimeError("connectAttr: Expected a source and a destination attribute")
    from . import cmds_misc
    texture = cmds_misc.connect_texture(plugs[0], plugs[1])     # file1.outColor -> lambert2.color (shading network)
    if texture is not None:
        return texture
    src, s_attr = _plug(plugs[0])
    dst, d_attr = _plug(plugs[1])
    ce = _ce()
    s_leaves, d_leaves = ce.leaves(s_attr), ce.leaves(d_attr)
    if len(s_leaves) != len(d_leaves):
        raise RuntimeError(f"connectAttr: The attribute '{_plug_text(src, s_attr)}' cannot be connected to "
                           f"'{_plug_text(dst, d_attr)}'.")
    busy = _foreign_keys(dst)
    for d in d_leaves:
        key = _leaf_key(dst, d)
        if (key in busy or _cb().driver(dst, key) is not None) and not force:
            raise RuntimeError(f"connectAttr: The destination attribute '{dst.name}.{d}' is already connected.")
    try:
        ce.connect(bpy.context.scene, src, s_attr, dst, d_attr)
    except ValueError as ex:
        raise RuntimeError(f"connectAttr: {ex}") from None
    _view_layer()
    return f"Connected {_plug_text(src, s_attr)} to {_plug_text(dst, d_attr)}."


def disconnectAttr(*args, **kwargs):
    """``disconnectAttr src.attr dst.attr``: the destination keeps its current value. Returns "Disconnect a.attr
    from b.attr."; no such connection is an error."""
    f = _Flags("disconnectAttr", kwargs)
    f.get("nextAvailable", "na", False)
    f.done()
    plugs = [str(a) for a in _flatten(args)]
    if len(plugs) != 2:
        raise RuntimeError("disconnectAttr: Expected a source and a destination attribute")
    src, s_attr = _plug(plugs[0])
    dst, d_attr = _plug(plugs[1])
    ce = _ce()
    if not ce.connected(src, s_attr, dst, d_attr):
        raise RuntimeError(f"disconnectAttr: There is no connection from '{_plug_text(src, s_attr)}' to "
                           f"'{_plug_text(dst, d_attr)}' to disconnect.")
    _view_layer()
    ce.disconnect(dst, d_attr)
    _view_layer()
    return f"Disconnect {_plug_text(src, s_attr)} from {_plug_text(dst, d_attr)}."


def isConnected(*args, **kwargs):
    f = _Flags("isConnected", kwargs)
    f.get("ignoreUnitConversion", "iuc", False)
    f.done()
    plugs = [str(a) for a in _flatten(args)]
    if len(plugs) != 2:
        raise RuntimeError("isConnected: Expected a source and a destination attribute")
    src, s_attr = _plug(plugs[0])
    dst, d_attr = _plug(plugs[1])
    return bool(_ce().connected(src, s_attr, dst, d_attr))


def _matching(node_text):
    """(object, leaves or None for the whole node) of a listConnections / connectionInfo argument."""
    text = str(node_text)
    if "." in text:
        ob, long = _plug(text)
        return ob, set(_ce().leaves(long))
    return _object(text), None


def listConnections(*args, **kwargs):
    """Sources / destinations of a node or plug's connections (``-s`` / ``-d`` default on, ``-p`` = plugs).
    None when there are none."""
    f = _Flags("listConnections", kwargs)
    s = f.get("source", "s", True)
    d = f.get("destination", "d", True)
    plugs = f.get("plugs", "p", False)
    f.get("connections", "c", False)
    f.get("skipConversionNodes", "scn", False)
    typ = f.get("type", "t")
    f.done()
    names = [str(a) for a in _flatten(args)] or [o.name for o in _selection()]
    from . import cmds_misc
    if len(names) == 1:
        shading = cmds_misc.shading_sources(names[0])       # a kit material plug: its texture node
        if shading is not None:
            return (shading if plugs else [p.split(".")[0] for p in shading]) or None
        if typ == "shadingEngine":
            try:
                kind = cmds_misc.nodeType(names[0].split(".")[0])
            except RuntimeError:
                kind = None
            if "shadingDependNode" in cmds_misc.CHAINS.get(kind, ()):
                return None                                 # kit materials have no shading group nodes
    out = []
    for n in names:
        ob, leaves = _matching(n)
        for so, sl, do, dl in connections():
            if s and do is ob and (leaves is None or dl in leaves):
                out.append(f"{so.name}.{sl}" if plugs else so.name)
            if d and so is ob and (leaves is None or sl in leaves):
                out.append(f"{do.name}.{dl}" if plugs else do.name)
    if typ is not None:
        out = [o for o in out if typ == "transform"]
    return out or None


def connectionInfo(*args, **kwargs):
    """``-sfd`` = the source plug ('' when none), ``-dfs`` = destination plugs, ``-id`` / ``-is`` = bools."""
    f = _Flags("connectionInfo", kwargs)
    sfd = f.get("sourceFromDestination", "sfd", False)
    dfs = f.get("destinationFromSource", "dfs", False)
    is_dst = f.get("isDestination", "id", False)
    is_src = f.get("isSource", "is", False)
    f.get("isExactDestination", "ied", False)
    f.get("isExactSource", "ies", False)
    f.done()
    names = [str(a) for a in _flatten(args)]
    if len(names) != 1 or "." not in names[0]:
        raise RuntimeError("connectionInfo: Expected one attribute")
    ob, leaves = _matching(names[0])
    conns = connections()
    srcs = [f"{so.name}.{sl}" for so, sl, do, dl in conns if do is ob and dl in leaves]
    dsts = [f"{do.name}.{dl}" for so, sl, do, dl in conns if so is ob and sl in leaves]
    if sfd:
        return srcs[0] if srcs else ""
    if dfs:
        return dsts
    if is_dst:
        return bool(srcs)
    if is_src:
        return bool(dsts)
    raise TypeError("connectionInfo needs -sourceFromDestination, -destinationFromSource, -isDestination or "
                    "-isSource")
