# SPDX-License-Identifier: GPL-3.0-or-later
"""Pin helper empties and how they follow their pin: the custom property keys a helper carries (``KIND``, ``NODE``,
``OWNER``, ``GEOM`` ...), lookups from a pin constraint (``pin_type``, ``node_name``, ``geometry_of``, read by the
Channel Box INPUTS), the pin matrix of a UV / Proximity Pin (``pin_matrix``) and ``update``, which moves every
helper to its pin. The handlers that call ``update`` are registered in pins_205.py.
"""

import bpy
import numpy as np
from mathutils import Matrix, Vector

from .pin_geometry import Geo

from .. import update_summary

KIND = "allset_pin"                  # helper empty: "uvPin" | "proximityPin"
NODE = "allset_pin_node"             # helper empty: Maya node name (uvPin1)
OWNER = "allset_pin_owner"           # helper empty: the pinned transform
GEOM = "allset_pin_geometry"         # helper empty: the geometry (mesh object)
UV = "allset_pin_uv"                 # uvPin helper: (u, v)
INPUT = "allset_pin_input"           # proximityPin helper: pinInput object (None = stored matrix INPUT_MATRIX)
INPUT_MATRIX = "allset_pin_input_matrix"
OFFSET = "allset_pin_offset"         # proximityPin helper: maintain offset (the default of the two below)
OFFSET_T = "allset_pin_offset_translation"   # proximityPin helper: Maya offsetTranslation (0..1)
OFFSET_O = "allset_pin_offset_orientation"   # proximityPin helper: Maya offsetOrientation (0..1)
ENVELOPE = "allset_pin_envelope"     # proximityPin helper: Maya envelope (0..1)
MODE = "allset_pin_mode"             # "edge" | "uv" (coordinate system of the tangent)
AXES = "allset_pin_axes"             # (normal axis, tangent axis), 0..5 = X Y Z -X -Y -Z
PIN_TYPES = ("uvPin", "proximityPin")
AXIS_ITEMS = ("X", "Y", "Z", "-X", "-Y", "-Z")


# --- helpers (one per pinned output) and the handler that keeps them at the pin -------------------------------

_state = {"busy": False, "count": -1, "names": set()}


def helpers():
    if len(bpy.data.objects) != _state["count"]:
        _state["count"] = len(bpy.data.objects)
        _state["names"] = {o.name for o in bpy.data.objects if o.get(KIND) in PIN_TYPES}
    out = []
    for name in list(_state["names"]):
        ob = bpy.data.objects.get(name)
        if ob is None or ob.get(KIND) not in PIN_TYPES:
            _state["count"] = -1
            continue
        out.append(ob)
    return out


def _rescan(*_args):
    _state["count"] = -1


def helper_of(con):
    t = getattr(con, "target", None) if con.type == 'COPY_TRANSFORMS' else None
    return t if t is not None and t.get(KIND) in PIN_TYPES else None


def pin_type(con):
    """``uvPin`` / ``proximityPin`` for a kit pin constraint, else None (ui/cb_inputs INPUTS / AE tab type)."""
    h = helper_of(con)
    return h.get(KIND) if h is not None else None


def node_name(con):
    """The Maya node name of a kit pin constraint (``uvPin1``), else None."""
    h = helper_of(con)
    return h.get(NODE) if h is not None else None


def geometry_of(con):
    h = helper_of(con)
    g = h.get(GEOM) if h is not None else None
    return g if isinstance(g, bpy.types.Object) else None


def _parent_matrix(owner, depsgraph):
    if owner.parent is None:
        return Matrix.Identity(4)
    par = owner.parent.evaluated_get(depsgraph) if depsgraph is not None else owner.parent
    return par.matrix_world @ owner.matrix_parent_inverse


def _input_matrix(h):
    inp = h.get(INPUT)
    if isinstance(inp, bpy.types.Object):
        return np.array(inp.matrix_world, dtype=np.float64)
    flat = h.get(INPUT_MATRIX)
    if flat is not None and len(flat) == 16:
        return np.array(list(flat), dtype=np.float64).reshape(4, 4)
    return None


def offsets(h):
    """(Offset Translation, Offset Orientation, Envelope) of a proximityPin helper (Maya keyable attributes; Maintain
    offset on = 1 / 1, off = 0 / 0)."""
    on = 1.0 if h.get(OFFSET, True) else 0.0
    return (float(h.get(OFFSET_T, on)), float(h.get(OFFSET_O, on)), float(h.get(ENVELOPE, 1.0)))


def _rot_blend(a, b, f):
    """3x3 rotation slerp a -> b by f (the scale of ``a`` kept)."""
    qa = Matrix(a.tolist()).to_quaternion()
    qb = Matrix(b.tolist()).to_quaternion()
    m = qa.slerp(qb, f).to_matrix()
    sc = np.linalg.norm(a, axis=0)
    return np.array(m, dtype=np.float64) * sc[None, :]


def _orientation_base(inp, geo, loc, mode, axes):
    """Offset Orientation 0: Edge = the input turned by the minimal rotation taking its normal axis
    onto the rest normal n0; UV = the rest frame on the normal / tangent options."""
    if mode == "uv":
        return geo.frame(loc, axes, deformed=False, world=False)[:3, :3]
    na = axes[0]
    r = inp[:3, :3]
    ax = Vector(r[:, na % 3] * (1.0 if na < 3 else -1.0))
    n0 = Vector(geo.frame(loc, (0, 1), deformed=False, world=False)[:3, 0])
    if ax.length < 1e-12:
        return r
    turn = np.array(ax.normalized().rotation_difference(n0).to_matrix(), dtype=np.float64)
    return turn @ r


def pin_matrix(h, geo):
    """World matrix (numpy 4x4) the pin puts its output at, or None."""
    axes = tuple(h.get(AXES, (0, 1)))
    if h.get(KIND) == "uvPin":
        # UV Pin: the frame at the stored UV on the deformed mesh (the target's own rotation is dropped)
        uv = h.get(UV)
        loc = geo.at_uv(tuple(uv)) if uv is not None else None
        return geo.frame(loc, axes) if loc is not None else None
    # Proximity Pin: each evaluation the closest point to the input on the ORIGINAL mesh (moving pinInput moves the
    # pin); output = F1 · F0⁻¹ · wanted (Maya row vectors: M · F0⁻¹ · F1), F0 / F1 = rest / deformed frames (X, Y).
    mode = h.get(MODE, "edge")
    inp = _input_matrix(h)
    if inp is None:
        return None
    loc = geo.closest(inp[:3, 3], original=True)
    if loc is None:
        return None
    off_t, off_o, env = offsets(h)
    f0 = geo.frame(loc, (0, 1), deformed=False, world=False)
    f1 = geo.frame(loc, (0, 1))
    want = inp.copy()
    if off_t != 1.0:
        want[:3, 3] = off_t * inp[:3, 3] + (1.0 - off_t) * f0[:3, 3]      # 0 = on the surface
    if off_o != 1.0:
        base = _orientation_base(inp, geo, loc, mode, axes)
        want[:3, :3] = base if off_o == 0.0 else _rot_blend(base, inp[:3, :3], off_o)   # between 0 and 1
    out = f1 @ np.linalg.inv(f0) @ want
    if env != 1.0:
        # Envelope: rotation slerp(input, pinned, e), translation lerp (the input as the geometry carries it at rest)
        src = geo.mw @ inp
        res = np.identity(4)
        res[:3, :3] = _rot_blend(src[:3, :3], out[:3, :3], env)
        res[:3, 3] = (1.0 - env) * src[:3, 3] + env * out[:3, 3]
        out = res
    return out


def update(depsgraph=None):
    """Move every pin helper to its pin (no write when it is already there: the handler doesn't loop)."""
    if _state["busy"]:
        return
    hs = helpers()
    if not hs:
        return
    _state["busy"] = True
    try:
        if depsgraph is None:
            depsgraph = bpy.context.evaluated_depsgraph_get()
        geos = {}
        for h in hs:
            owner, geom = h.get(OWNER), h.get(GEOM)
            if not isinstance(owner, bpy.types.Object) or not isinstance(geom, bpy.types.Object):
                continue
            if geom.type != 'MESH':
                continue
            geo = geos.get(geom.name)
            if geo is None:
                geo = geos[geom.name] = Geo(geom, depsgraph)
            if not geo.ok:
                continue
            m = pin_matrix(h, geo)
            if m is None:
                continue
            new = Matrix(m.tolist()) @ _parent_matrix(owner, depsgraph).inverted_safe()
            old = h.matrix_world
            if max(abs(old[i][j] - new[i][j]) for i in range(4) for j in range(4)) > 1e-7 or h.parent is not None:
                update_summary.wrote()
                h.parent = None
                h.matrix_world = new
    finally:
        _state["busy"] = False
