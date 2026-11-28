# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya option windows of the UV Editor's Cut/Sew menu (Auto Seams, Move and Sew, Merge, Stitch Together) and Modify
menu (Align, Distribute Shells / UVs, Flip, Layout Along, Match UVs, Normalize, Rotate, Snap Together, Stack Similar
Shells, Straighten Border, Unitize, Unstack Shells).

Same spec as operators/option_windows_spec.py; option_windows._extend appends ``WINDOWS``. Each window runs the
item's command with its values, and a plain menu click runs them once they are saved, like Maya. Defaults: Auto
Seams cuts automatic seams; Move and Sew moves shells of any size (Limit shell size off, 10 faces once it is on);
Merge UVs merges within 0.01; Stitch Together stitches the smaller shells onto the larger ones. Modify: Align to
the minimum U, Distribute Shells to the right without padding, Distribute UVs along U over the selection's width,
Flip horizontally around the UV pivot, cutting the flipped faces free, Layout Along U, Match UVs within 0.01, Normalize U and V together onto the closest tile, Rotate
90 degrees, Snap Together A to B, Stack Similar within 0.1, Straighten Border filling gaps of up to 5 UVs, Unstack
with reversed shells flipped back.
"""

import math

import bpy

from . import uv_flip, uv_stitch
from .option_windows import F, Window


def _run_auto_seams(context, v):
    return bpy.ops.allset.uv_auto_seams('EXEC_DEFAULT', seams=v["seams"].upper(),
                                       method='AUTOMATIC' if v["method"] == "Automatic" else 'HARD_EDGES')


def _run_move_sew(context, v):
    return bpy.ops.allset.uv_move_sew('EXEC_DEFAULT', limit=v["limit"], faces=v["faces"])


def _run_merge(context, v):
    return bpy.ops.allset.uv_merge('EXEC_DEFAULT', distance=v["distance"])


def _run_stitch(context, v):
    return bpy.ops.allset.uv_stitch_together('EXEC_DEFAULT', order=uv_stitch.ORDER_LABELS[v["order"]])


WINDOWS = [
    Window("uv_auto_seams", "Auto Seams Options", "Auto Seams", None, [
        F("seams", "Seams:", "enum", "Cut", items=("Cut", "Select")),
        F("method", "Method:", "enum", "Automatic", items=("Automatic", "Cut along hard edges")),
    ], _run_auto_seams, paths=("UV Editor/Cut/Sew/Auto Seams",),
        missing=("Fix non-manifold geometry", "Shell Splitting Tolerance, Connect Holes")),
    Window("uv_move_sew", "Move and Sew UVs Options", "Move and Sew", None, [
        F("limit", "", "bool", False, text="Limit shell size"),
        F("faces", "Number of faces:", "int", 10, lo=0, hi=100),
    ], _run_move_sew, paths=("UV Editor/Cut/Sew/Move and Sew",),
        enabled=lambda v, name: name != "faces" or v["limit"]),
    Window("uv_merge", "Merge UVs Options", "Merge UVs", None, [
        F("distance", "Threshold:", "float", 0.01, lo=0.0, hi=1.0),
    ], _run_merge, paths=("UV Editor/Cut/Sew/Merge",)),
    Window("uv_stitch_together", "Stitch Together Options", "Apply and Close", None, [
        F("order", "Stitch Together:", "enum", "Smallest to Largest", items=tuple(uv_stitch.ORDER_LABELS)),
    ], _run_stitch, paths=("UV Editor/Cut/Sew/Stitch Together",)),
]


# --- Modify ----------------------------------------------------------------------------------------------------------

_ALIGN = {"Minimum U value": ('U', 'MIN'), "Minimum V value": ('V', 'MIN'), "Center U value": ('U', 'AVG'),
          "Center V value": ('V', 'AVG'), "Maximum U value": ('U', 'MAX'), "Maximum V value": ('V', 'MAX')}


def _run_align(context, v):
    axis, where = _ALIGN[v["align"]]
    return bpy.ops.allset.uv_align_to('EXEC_DEFAULT', axis=axis, where=where)


def _run_distribute_shells(context, v):
    return bpy.ops.allset.uv_distribute('EXEC_DEFAULT', direction=v["direction"].upper(), padding=v["padding"])


def _run_distribute_uvs(context, v):
    return bpy.ops.allset.uv_distribute_uvs('EXEC_DEFAULT', axis=v["along"],
                                            distance=v["distance"] if v["spacing"] == "Custom" else 0.0)


def _run_flip(context, v):
    return bpy.ops.allset.uv_flip('EXEC_DEFAULT', direction=v["direction"].upper(),
                                  coordinate=uv_flip.COORDINATES[v["coordinate"]], cut=v["cut"])


def _run_layout_along(context, v):
    return bpy.ops.allset.uv_layout_along('EXEC_DEFAULT', direction=v["along"])


def _run_match_uvs(context, v):
    return bpy.ops.uv.remove_doubles('EXEC_DEFAULT', threshold=v["tolerance"])


def _run_normalize(context, v):
    return bpy.ops.allset.uv_normalize('EXEC_DEFAULT', along=v["along"], each_face=v["each"] != "Collectively",
                                       keep_aspect=v["keep_aspect"], closest_tile=v["closest_tile"])


def _run_rotate(context, v):
    return bpy.ops.transform.rotate('EXEC_DEFAULT', value=-math.radians(v["angle"]))


def _run_snap_together(context, v):
    return bpy.ops.allset.uv_snap_together('EXEC_DEFAULT', method='0' if v["method"] == "A to B" else '1')


def _run_stack_similar(context, v):
    return bpy.ops.allset.uv_stack_similar('EXEC_DEFAULT', tolerance=v["tolerance"])


def _run_straighten_border(context, v):
    return bpy.ops.allset.uv_straighten_border('EXEC_DEFAULT', gap=v["gap"] if v["fill_gaps"] else 0)


def _run_unitize(context, v):
    return bpy.ops.allset.uv_unitize('EXEC_DEFAULT')


def _run_unstack(context, v):
    return bpy.ops.allset.uv_unstack('EXEC_DEFAULT', flip_reversed=v["flip_reversed"])


M = "UV Editor/Modify/"
WINDOWS += [
    Window("uv_align", "Align UVs Options", "Align", None, [
        F("align", "Align selection to:", "enum", "Minimum U value", items=(
            "Minimum U value", "Minimum V value", "Center U value", "Center V value", "Maximum U value",
            "Maximum V value")),
    ], _run_align, paths=(M + "Align",)),
    Window("uv_distribute_shells", "Distribute Shells Options", "Distribute", None, [
        F("direction", "Direction:", "enum", "Right", items=("Right", "Left", "Up", "Down")),
        F("padding", "Shell Padding:", "float", 0.0, lo=0.0, hi=1.0),
    ], _run_distribute_shells, paths=(M + "Distribute Shells",), missing=("Direction: Towards Target",)),
    Window("uv_distribute_uvs", "Distribute UVs Options", "Distribute", None, [
        F("spacing", "Distribution Distance:", "enum", "Automatic", items=("Automatic", "Custom")),
        F("distance", "Distance:", "float", 0.5, lo=0.0, hi=1.0),
        F("along", "Distribute Along:", "enum", "U", items=("U", "V")),
    ], _run_distribute_uvs, paths=(M + "Distribute UVs",),
        enabled=lambda v, name: name != "distance" or v["spacing"] == "Custom"),
    Window("uv_flip", "Flip UVs Options", "Flip", None, [
        F("direction", "Direction:", "enum", "Horizontal", items=("Horizontal", "Vertical")),
        F("coordinate", "Coordinate:", "enum", "Pivot", items=tuple(uv_flip.COORDINATES)),
        F("cut", "Cut UV Perimeter:", "bool", True),
    ], _run_flip, paths=(M + "Flip",)),
    Window("uv_layout_along", "Layout Along Options", "Layout Along", None, [
        F("along", "Layout Along:", "enum", "U", items=("U", "V")),
    ], _run_layout_along, paths=(M + "Layout Along",)),
    Window("uv_match_uvs", "Match UVs Options", "Match UVs", None, [
        F("tolerance", "Tolerance:", "float", 0.01, lo=0.0, hi=1.0),
    ], _run_match_uvs, paths=(M + "Match UVs",)),
    Window("uv_normalize", "Normalize UVs Options", "Normalize", None, [
        F("along", "Normalize Along:", "enum", "UV", items=("UV", "U", "V")),
        F("each", "Normalize:", "enum", "Collectively", items=("Collectively", "Each face separately")),
        F("keep_aspect", "", "bool", False, text="Preserve aspect ratio"),
        F("closest_tile", "", "bool", True, text="Center on closest tile"),
    ], _run_normalize, paths=(M + "Normalize",)),
    Window("uv_rotate", "Rotate UVs Options", "Rotate UVs", None, [
        F("angle", "Rotation angle:", "float", 90.0, lo=-360.0, hi=360.0),
    ], _run_rotate, paths=(M + "Rotate",)),
    Window("uv_snap_together", "Snap Together Options", "Snap Together", None, [
        F("method", "Method:", "enum", "A to B", items=("A to B", "B to A")),
    ], _run_snap_together, paths=(M + "Snap Together",)),
    Window("uv_stack_similar", "Stack Similar Options", "Stack Similar", None, [
        F("tolerance", "Tolerance:", "float", 0.1, lo=0.0, hi=1.0),
    ], _run_stack_similar, paths=(M + "Stack Similar Shells",), missing=("Select Stacked Shells",)),
    Window("uv_straighten_border", "Straighten UV Border Options", "Straighten UV Border", None, [
        F("fill_gaps", "", "bool", True, text="Fill gaps in selection"),
        F("gap", "UV gap tolerance:", "int", 5, lo=1, hi=20),
    ], _run_straighten_border, paths=(M + "Straighten Border",),
        enabled=lambda v, name: name != "gap" or v["fill_gaps"],
        missing=("Curvature, Preserve length ratio, Preserve original shape",)),
    Window("uv_unitize", "Unitize UVs Options", "Unitize", None, [], _run_unitize, paths=(M + "Unitize",),
           missing=("Create new UV Set, UV Set name",)),
    Window("uv_unstack", "Unstack Options", "Unstack", None, [
        F("flip_reversed", "", "bool", True, text="Flip reversed UV shells"),
    ], _run_unstack, paths=(M + "Unstack Shells",)),
]
