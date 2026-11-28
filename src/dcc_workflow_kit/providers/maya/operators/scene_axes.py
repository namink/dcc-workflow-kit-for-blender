# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene axes in option windows.

Option windows and tool options read X / Y / Z as the scene's axes, the ones the Channel Box shows (Z up). Some kit
code builds shapes in a Y-up frame (Y up, Z towards the front view): ``to_yup`` / ``from_yup`` turn a scene vector into
that frame and back. ``OLD`` helpers convert option values saved while the windows read X / Y / Z in the Y-up frame,
so a saved choice keeps its result (an upright Axis Y becomes Axis Z).
"""

AXES = ("X", "Y", "Z")
VERSION = 3          # saved option values: 1 (no marker) = Y-up X / Y / Z, 2 = scene axes, 3 = also the aim /
                     # motion path vectors on the node's own axes (an object's Y-up reading before)


def to_yup(v):
    """Scene (x, y, z) -> the Y-up frame (x, z, -y)."""
    x, y, z = v
    return (x, z, -y)


def from_yup(v):
    """Y-up frame (x, y, z) -> scene (x, -z, y)."""
    x, y, z = v
    return (x, -z, y)


def signed_to_yup(axis, sign):
    """A scene axis with its sign ("Y", "+") -> the same direction in the Y-up frame (("Z", "-"))."""
    flip = {"+": "-", "-": "+"}
    if axis == "Y":
        return "Z", flip[sign]
    if axis == "Z":
        return "Y", sign
    return axis, sign


def signed_from_yup(axis, sign):
    """A Y-up frame axis with its sign -> the scene axis."""
    flip = {"+": "-", "-": "+"}
    if axis == "Y":
        return "Z", sign
    if axis == "Z":
        return "Y", flip[sign]
    return axis, sign


# --- option values saved with the Y-up reading -----------------------------------------------------------------------

def old_vector(values, name, kind="point"):
    """A saved vec3 ``name``: Y-up point / direction -> scene; ``kind`` "scale" swaps Y and Z only."""
    v = values.get(name)
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        return
    values[name] = (v[0], v[2], v[1]) if kind == "scale" else from_yup(v)


def old_local_axis(values, name, inverse):
    """A saved Motion Path Front / Up axis read on the object's Y-up frame -> its own axis; the old Z (= local -Y)
    becomes Y with ``inverse`` switched."""
    v = values.get(name)
    if v == "Y":
        values[name] = "Z"
    elif v == "Z":
        values[name] = "Y"
        values[inverse] = not values.get(inverse, False)


def old_swap(values, a, b):
    """Two saved values that trade places (Y and Z check boxes, Y and Z axis choices)."""
    if a in values or b in values:
        va, vb = values.get(a), values.get(b)
        values.pop(a, None)
        values.pop(b, None)
        if vb is not None:
            values[a] = vb
        if va is not None:
            values[b] = va


def old_axis(values, name, labels=AXES):
    """A saved axis choice: Y-up Y (up) -> Z, Z (front) -> Y; ``labels`` = the window's X / Y / Z item names."""
    v = values.get(name)
    if v == labels[1]:
        values[name] = labels[2]
    elif v == labels[2]:
        values[name] = labels[1]


def old_plane(values, name):
    """A saved plane choice: Y-up XY (the front plane) -> XZ, XZ (the ground) -> XY; YZ stays."""
    v = values.get(name)
    if v in ("XY", "XZ"):
        values[name] = "XZ" if v == "XY" else "XY"
