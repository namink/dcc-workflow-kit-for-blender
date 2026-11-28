# SPDX-License-Identifier: GPL-3.0-or-later
"""The hidden helper empties of the kit Normal / Tangent constraints: the custom property keys a helper carries
(``KIND``, ``OWNER``, ``SURFACE``), the cached list of helpers (``helpers``, rescanned when objects come and go),
``helper_of`` / ``surface_of`` from a constraint, ``helpers_owned_by`` and ``remove_helpers`` (used when objects or
history are deleted). The handlers that move the helpers are in constrain_199.py.
"""

import bpy

KIND = "allset_aim_kind"             # helper empty: "normal" | "tangent"
OWNER = "allset_aim_owner"           # helper empty: the constrained object
SURFACE = "allset_aim_surface"       # helper empty: the Maya target (mesh / curve)
LABEL = {"normal": "Normal Constraint", "tangent": "Tangent Constraint"}
MAYA_NODE = {"normal": "normalConstraint", "tangent": "tangentConstraint"}


# --- helper empties -------------------------------------------------------------------------------------

_state = {"busy": False, "count": -1, "names": set()}


def helpers():
    """Helper empties of kit normal / tangent constraints (cached by name, rescanned when objects come and go)."""
    if len(bpy.data.objects) != _state["count"]:
        _state["count"] = len(bpy.data.objects)
        _state["names"] = {o.name for o in bpy.data.objects if o.get(KIND) in LABEL}
    out = []
    for name in list(_state["names"]):
        ob = bpy.data.objects.get(name)
        if ob is None or ob.get(KIND) not in LABEL:
            _state["count"] = -1
            continue
        out.append(ob)
    return out


def _rescan(*_args):
    _state["count"] = -1


def helper_of(con):
    t = getattr(con, "target", None)
    return t if t is not None and t.get(KIND) in LABEL else None


def helpers_owned_by(objects):
    """Helper empties of the kit normal / tangent constraints on ``objects``."""
    owners = set(objects)
    return [h for h in helpers() if h.get(OWNER) in owners]


def remove_helpers(objs):
    """Delete helper empties (each once; objects already gone are skipped). Maya's normal / tangent constraint is a
    DAG child of the constrained object, so it goes with the object and with Delete by Type > Constraints
    (#109; Remove Target already did this, ``remove_targets``)."""
    seen = set()
    for h in objs:
        try:
            if h.as_pointer() in seen or h.get(KIND) not in LABEL:
                continue
        except ReferenceError:
            continue
        seen.add(h.as_pointer())
        bpy.data.objects.remove(h, do_unlink=True)
    if seen:
        _rescan()
    return len(seen)


def surface_of(con):
    h = helper_of(con)
    return h.get(SURFACE) if h is not None else None
