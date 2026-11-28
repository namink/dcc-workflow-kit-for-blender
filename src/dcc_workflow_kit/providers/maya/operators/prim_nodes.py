# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya primitive creation nodes as data: ``NODES`` lists per node type (polyCube ... makeNurbCube) its attributes
(Maya name, Channel Box label, default = what the Create menu builds, kind, limits); ``defaults`` / ``spec`` /
``clamp`` read them. Also the shape containers ``Mesh`` (polygon shape) and ``Patch`` (NURBS curve / surface).
Pure Python; prim_shapes.py adds the Pipe / Helix / Gear / Soccer Ball and Super Shape nodes, so read NODES there."""

ALL = "ALL"


class Mesh:
    __slots__ = ("verts", "faces", "uvs", "hard", "edges")

    def __init__(self, verts, faces, uvs=None, hard=(), edges=None):
        self.verts, self.faces, self.uvs, self.hard = verts, faces, uvs, hard
        # Maya's edge ids: (a, b) per edge in Maya's order and direction, or None (unknown for this node)
        self.edges = edges


class Patch:
    """A NURBS curve (``rows`` = 1) or surface: ``points[row][col]`` in Maya space. Blender u = along a row
    (Maya V: sections / around), Blender v = rows (Maya U: spans / profile)."""
    __slots__ = ("name", "points", "order_u", "order_v", "cyclic_u", "cyclic_v")

    def __init__(self, name, points, order_u, order_v=1, cyclic_u=False, cyclic_v=False):
        self.name, self.points = name, points
        self.order_u, self.order_v, self.cyclic_u, self.cyclic_v = order_u, order_v, cyclic_u, cyclic_v


# --- creation nodes: Maya attribute name, Channel Box label, default, kind, (min, max) ------------------
# kind: "length" (scaled by the Maya unit), "float", "int", "bool", "angle" (degrees), ("enum", labels)

def _a(name, label, default, kind, lo=None, hi=None):
    return (name, label, default, kind, lo, hi)


AXIS = [_a("axisX", "Axis X", 0.0, "float"), _a("axisY", "Axis Y", 1.0, "float"), _a("axisZ", "Axis Z", 0.0, "float")]
PIVOT = [_a("pivotX", "Pivot X", 0.0, "length"), _a("pivotY", "Pivot Y", 0.0, "length"),
         _a("pivotZ", "Pivot Z", 0.0, "length")]
NORMAL = [_a("normalX", "Normal X", 0.0, "float"), _a("normalY", "Normal Y", 1.0, "float"),
          _a("normalZ", "Normal Z", 0.0, "float")]
CENTER = [_a("centerX", "Center X", 0.0, "length"), _a("centerY", "Center Y", 0.0, "length"),
          _a("centerZ", "Center Z", 0.0, "length")]
DEGREE = ("enum", ("Linear", "Cubic"))   # Maya degree 1 / 3 (stored as 1 / 3)
# Create UVs: 0 = no UVs; the kit lays out every other choice like the Create menu does (each node's default).
# polyCylinder / polyCone choices; polyCube, polySphere and polyPlane have their own, polyTorus has an on / off.
CREATE_UVS = ("None", "Normalization Off", "Normalize", "Normalize and Preserve Aspect Ratio")
CREATE_UVS_CUBE = ("None", "Normalization Off", "Normalize Each Face Separately", "Normalize Collectively",
                   "Normalize Collectively and Preserve Aspect Ratio")
CREATE_UVS_SPHERE = ("None", "Pinched at pole", "Sawtooth at pole")
CREATE_UVS_PLANE = ("None", "Normalization Off", "Normalize and Preserve Aspect Ratio")
# Height Baseline: -1 puts the bottom on the origin, 1 the top (moves the shape along its axis)
BASELINE = _a("heightBaseline", "Height Baseline", 0.0, "float", -1.0, 1.0)
SWEEPS = [_a("startSweep", "Start Sweep", 0.0, "angle", 0.0, 360.0), _a("endSweep", "End Sweep", 360.0, "angle", 0.0, 360.0)]

# Defaults = what the Create menu builds with default option boxes; where
# that differs from the bare command (polyCylinder subdivisionsCaps 0 -> menu 1) the menu wins.
NODES = {
    "polyCube": [*AXIS, BASELINE, _a("width", "Width", 1.0, "length", 0.0), _a("height", "Height", 1.0, "length", 0.0),
                 _a("depth", "Depth", 1.0, "length", 0.0), _a("subdivisionsWidth", "Subdivisions Width", 1, "int", 1),
                 _a("subdivisionsHeight", "Subdivisions Height", 1, "int", 1),
                 _a("subdivisionsDepth", "Subdivisions Depth", 1, "int", 1),
                 _a("createUVs", "Create UVs", 4, ("enum", CREATE_UVS_CUBE))],
    "polySphere": [*AXIS, BASELINE, _a("radius", "Radius", 1.0, "length", 0.0),
                   _a("subdivisionsAxis", "Subdivisions Axis", 20, "int", 3),
                   _a("subdivisionsHeight", "Subdivisions Height", 20, "int", 2),
                   _a("createUVs", "Create UVs", 2, ("enum", CREATE_UVS_SPHERE))],
    "polyCylinder": [*AXIS, BASELINE,
                     _a("radius", "Radius", 1.0, "length", 0.0), _a("height", "Height", 2.0, "length", 0.0),
                     _a("subdivisionsAxis", "Subdivisions Axis", 20, "int", 3),
                     _a("subdivisionsHeight", "Subdivisions Height", 1, "int", 1),
                     _a("subdivisionsCaps", "Subdivisions Caps", 1, "int", 0),
                     _a("createUVs", "Create UVs", 3, ("enum", CREATE_UVS)),
                     _a("roundCap", "Round Cap", False, "bool"),
                     _a("roundCapHeightCompensation", "Round Cap Height Compensation", False, "bool")],
    "polyCone": [*AXIS, BASELINE, _a("radius", "Radius", 1.0, "length", 0.0), _a("height", "Height", 2.0, "length", 0.0),
                 _a("subdivisionsAxis", "Subdivisions Axis", 20, "int", 3),
                 _a("subdivisionsHeight", "Subdivisions Height", 1, "int", 1),
                 _a("subdivisionsCap", "Subdivisions Cap", 0, "int", 0),
                 _a("createUVs", "Create UVs", 3, ("enum", CREATE_UVS)), _a("roundCap", "Round Cap", False, "bool")],
    "polyTorus": [*AXIS, BASELINE, _a("radius", "Radius", 1.0, "length", 0.0),
                  _a("sectionRadius", "Section Radius", 0.5, "length", 0.0), _a("twist", "Twist", 0.0, "angle"),
                  _a("subdivisionsAxis", "Subdivisions Axis", 20, "int", 3),
                  _a("subdivisionsHeight", "Subdivisions Height", 20, "int", 3),
                  _a("createUVs", "Create UVs", True, "bool")],
    "polyPlane": [*AXIS, BASELINE, _a("width", "Width", 1.0, "length", 0.0), _a("height", "Height", 1.0, "length", 0.0),
                  _a("subdivisionsWidth", "Subdivisions Width", 10, "int", 1),
                  _a("subdivisionsHeight", "Subdivisions Height", 10, "int", 1),
                  _a("createUVs", "Create UVs", 2, ("enum", CREATE_UVS_PLANE))],
    "polyDisc": [_a("sides", "Sides", 3, "int", 3),
                 _a("subdivisionMode", "Subdivision Mode", 4, ("enum", ("Quads", "Triangles", "Pie", "Caps", "Circle"))),
                 _a("subdivisions", "Subdivisions", 3, "int", 0), _a("radius", "Radius", 1.0, "length", 0.0)],
    "polyPlatonic": [_a("primitive", "Primitive", 4,
                        ("enum", ("Tetrahedron", "Cube", "Octahedron", "Dodecahedron", "Icosahedron"))),
                     _a("subdivisionMode", "Subdivision Mode", 0, ("enum", ("Quads", "Triangles", "Pie", "Caps"))),
                     _a("subdivisions", "Subdivisions", 0, "int", 0), _a("radius", "Radius", 1.0, "length", 0.0),
                     _a("sphericalInflation", "Spherical Inflation", 1.0, "float", 0.0, 1.0)],
    "polyPyramid": [*AXIS, _a("sideLength", "Side Length", 1.0, "length", 0.0),
                    _a("numberOfSides", "Number Of Sides", 4, ("enum3", (3, 4, 5))),
                    _a("subdivisionsHeight", "Subdivisions Height", 1, "int", 1),
                    _a("subdivisionsCaps", "Subdivisions Caps", 0, "int", 0)],
    "polyPrism": [*AXIS, _a("length", "Length", 2.0, "length", 0.0), _a("sideLength", "Side Length", 1.0, "length", 0.0),
                  _a("numberOfSides", "Number Of Sides", 3, "int", 3),
                  _a("subdivisionsHeight", "Subdivisions Height", 1, "int", 1),
                  _a("subdivisionsCaps", "Subdivisions Caps", 0, "int", 0)],
    # NURBS
    "makeNurbCircle": [*NORMAL, *CENTER, _a("radius", "Radius", 1.0, "length", 0.0),
                       _a("sweep", "Sweep", 360.0, "angle", -360.0, 360.0), _a("degree", "Degree", 3, DEGREE),
                       _a("sections", "Sections", 8, "int", 1)],
    "makeNurbsSquare": [*NORMAL, *CENTER, _a("sideLength1", "Side Length 1", 1.0, "length", 0.0),
                        _a("sideLength2", "Side Length 2", 1.0, "length", 0.0), _a("degree", "Degree", 3, DEGREE),
                        _a("spansPerSide", "Spans Per Side", 1, "int", 1)],
    "makeNurbSphere": [*PIVOT, *AXIS, _a("radius", "Radius", 1.0, "length", 0.0), *SWEEPS,
                       _a("degree", "Degree", 3, DEGREE), _a("sections", "Sections", 8, "int", 2),
                       _a("spans", "Spans", 4, "int", 2)],
    "makeNurbCylinder": [*PIVOT, *AXIS, _a("radius", "Radius", 1.0, "length", 0.0), *SWEEPS,
                         _a("degree", "Degree", 3, DEGREE), _a("sections", "Sections", 8, "int", 2),
                         _a("spans", "Spans", 1, "int", 1), _a("heightRatio", "Height Ratio", 2.0, "float", 0.0)],
    "makeNurbCone": [*PIVOT, *AXIS, _a("radius", "Radius", 1.0, "length", 0.0), *SWEEPS,
                     _a("degree", "Degree", 3, DEGREE), _a("sections", "Sections", 8, "int", 2),
                     _a("spans", "Spans", 1, "int", 1), _a("heightRatio", "Height Ratio", 2.0, "float", 0.0)],
    "makeNurbTorus": [*PIVOT, *AXIS, _a("radius", "Radius", 1.0, "length", 0.0), *SWEEPS,
                      _a("degree", "Degree", 3, DEGREE), _a("sections", "Sections", 8, "int", 2),
                      _a("spans", "Spans", 4, "int", 2), _a("heightRatio", "Height Ratio", 0.5, "float", 0.0),
                      _a("minorSweep", "Minor Sweep", 360.0, "angle", 0.0, 360.0)],
    "makeNurbPlane": [*PIVOT, *AXIS, _a("width", "Width", 1.0, "length", 0.0),
                      _a("lengthRatio", "Length Ratio", 1.0, "float", 0.0),
                      _a("patchesU", "Patches U", 1, "int", 1), _a("patchesV", "Patches V", 1, "int", 1),
                      _a("degree", "Degree", 3, DEGREE)],
    "makeNurbCube": [*PIVOT, *AXIS, _a("width", "Width", 1.0, "length", 0.0),
                     _a("lengthRatio", "Length Ratio", 1.0, "float", 0.0),
                     _a("heightRatio", "Height Ratio", 1.0, "float", 0.0),
                     _a("patchesU", "Patches U", 1, "int", 1), _a("patchesV", "Patches V", 1, "int", 1),
                     _a("degree", "Degree", 3, DEGREE)],
}
NURBS = {t for t in NODES if t.startswith("make")}


def defaults(node_type):
    return {a[0]: a[2] for a in NODES[node_type]}


def spec(node_type, name):
    return next(a for a in NODES[node_type] if a[0] == name)


def clamp(node_type, name, value):
    """``value`` for attribute ``name`` within Maya's limits (ints / bools / enums coerced)."""
    _n, _l, default, kind, lo, hi = spec(node_type, name)
    if kind == "bool":
        return bool(value)
    if isinstance(kind, tuple):
        if kind[0] == "enum3":
            v = int(round(value))
            return min(kind[1], key=lambda c: abs(c - v))
        if kind is DEGREE:
            return 1 if int(round(value)) < 2 else 3
        return max(0, min(len(kind[1]) - 1, int(round(value))))
    value = int(round(value)) if kind == "int" else float(value)
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value
