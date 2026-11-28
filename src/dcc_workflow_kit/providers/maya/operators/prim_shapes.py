# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya primitives as data: creation nodes (attributes + defaults) and the shapes they build.

Pure Python (no bpy), in Maya's Y-up space and Maya units; ``prim_history`` turns a shape into a Blender mesh /
curve. Every rule here follows Maya (default option boxes).
No Maya code or data was copied; vertex counts, positions,
face layouts and UVs follow Maya's for the default and varied attributes
(``tests/test_step129_primitives.py`` keeps the count table).

A polygon shape = ``Mesh(verts, faces, uvs, hard, edges)``: ``uvs`` one (u, v) per face corner (or None), ``hard`` the
edges Maya marks hard (frozenset vertex pairs) or ``ALL``, ``edges`` Maya's edge ids as vertex pairs in Maya's order
(polyCube / polyCylinder) or None. A NURBS shape = list of ``Patch`` (one per Maya shape:
nurbsSquare / nurbsCube are a group of four / six).

Code: prim_nodes (creation node table, ``Mesh`` / ``Patch``), prim_poly (Cube ... Prism, shared vector helpers),
prim_disc_platonic (Disc, Platonic Solids), prim_nurbs (NURBS); this module keeps the builder tables, ``build`` and
the re-exports.
"""

from .prim_nodes import (  # noqa: F401
    ALL, AXIS, CENTER, CREATE_UVS, DEGREE, NODES, NORMAL, NURBS, PIVOT, SWEEPS, Mesh, Patch, _a, clamp, defaults,
    spec)
from .prim_poly import (  # noqa: F401
    CAP_DV, CAP_R, CAP_V, SIDE_U, SIDE_V, _apply, _lerp, _orient, _rot_to, cylinder_heights, poly_cone, poly_cube,
    poly_cylinder, poly_plane, poly_prism, poly_pyramid, poly_sphere, poly_torus)
from .prim_disc_platonic import _platonic_base, poly_disc, poly_platonic  # noqa: F401
from .prim_nurbs import (  # noqa: F401
    arc_cvs, nurbs_circle, nurbs_cone, nurbs_cube, nurbs_cylinder, nurbs_plane, nurbs_sphere, nurbs_square,
    nurbs_torus)


POLY = {"polyCube": poly_cube, "polySphere": poly_sphere, "polyCylinder": poly_cylinder, "polyCone": poly_cone,
        "polyTorus": poly_torus, "polyPlane": poly_plane, "polyDisc": poly_disc, "polyPlatonic": poly_platonic,
        "polyPyramid": poly_pyramid, "polyPrism": poly_prism}


NURBS_BUILD = {"makeNurbCircle": nurbs_circle, "makeNurbsSquare": nurbs_square, "makeNurbSphere": nurbs_sphere,
               "makeNurbCylinder": nurbs_cylinder, "makeNurbCone": nurbs_cone, "makeNurbTorus": nurbs_torus,
               "makeNurbPlane": nurbs_plane, "makeNurbCube": nurbs_cube}


def build(node_type, attrs):
    a = {**defaults(node_type), **attrs}
    a = {k: clamp(node_type, k, v) for k, v in a.items() if any(s[0] == k for s in NODES[node_type])}
    if node_type in POLY:
        return POLY[node_type](a)
    return NURBS_BUILD[node_type](a)


# Pipe / Helix / Gear / Soccer Ball (prim_shapes_more) and Super Ellipse / Spherical Harmonics / Ultra Shape
# (prim_supershape, one polySuperShape node) join the tables; both modules import this one, so they come last.
from . import prim_shapes_more, prim_supershape  # noqa: E402

for _mod in (prim_shapes_more, prim_supershape):
    NODES.update(_mod.NODES)
    POLY.update(_mod.POLY)
