# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya option windows of UV Editor > Modify > Unfold, Optimize, Layout, Straighten UVs and Randomize Shells, and View >
Grid.

Same spec as operators/option_windows_spec.py (``F`` fields, ``Window`` = one ``allset.opt_<key>`` operator bound to its
menu paths; option_windows._extend appends ``WINDOWS``). Defaults: Straighten UVs straightens along U and V within
30 degrees; Randomize Shells moves shells up to 0.1 along U and V and neither turns nor scales them (22.5 degrees and
10 percent once those are switched on). View > Grid's window sets how many UDIM tiles (0-1 squares, 1001 at the
origin) Blender's UV grid shows across and up; View > Grid itself still shows / hides the grid.

Unfold, Optimize and Layout: the menu item, Ctrl+U / Ctrl+L, the UV Toolkit buttons and the marking menu items all run
with the saved values (operators/uv_tools.option_values). Unfold: 1 iteration, triangle flips prevented, no Layout after
it. Optimize (operators/uv_optimize.py): 1 iteration, Surfangle 1, Power 100 (below 100 nothing moves, like Maya),
triangle flips prevented; Method Legacy (relax) relaxes the shells instead (UV border pinned, uniform edge weights, 5
iterations).
Layout: shells pre-scaled to their 3D size ratio, not turned, packed together into the 0-1 square without padding,
uniformly scaled, in one tile (Shell Distribution Distribute, Tiles U / V 1) (operators/uv_layout.py).
"""

import json

import bpy

from .option_windows import F, Window
from . import uv_optimize
from . import uv_toolkit_ops as tk
from .uv_layout import DISTRIBUTIONS, MAP_SIZES, MULTI, PRE_ROTATE, PRE_SCALE, SCALE_MODES


UNFOLD_MAP_SIZES = MAP_SIZES[:-1]        # Unfold's Map size has no Custom entry


def _run_unfold(context, v):
    return bpy.ops.allset.uv_unfold('EXEC_DEFAULT', options=json.dumps(v))


def _run_optimize(context, v):
    return bpy.ops.allset.uv_optimize('EXEC_DEFAULT', options=json.dumps(v))


_LEGACY_FIELDS = ("pin_border", "pin_uvs", "pin_which", "edge_weights", "max_iterations")


def _optimize_enabled(v, name):
    """Legacy (relax) switches the window to its relax settings (Maya); the pin choice needs Pin UVs."""
    if name == "method":
        return True
    legacy = v["method"] == uv_optimize.LEGACY
    if name in _LEGACY_FIELDS:
        return legacy and (name != "pin_which" or v["pin_uvs"])
    return not legacy


def _run_layout(context, v):
    return bpy.ops.allset.uv_layout('EXEC_DEFAULT', options=json.dumps(v))


_REGION_FIELDS = ("region_min_u", "region_max_u", "region_min_v", "region_max_v")
_REGIONS = ("Full square", "Top half", "Top left", "Top right", "Bottom half", "Bottom left", "Bottom right",
            "Left half", "Right half", "Custom")


def _layout_enabled(v, name):
    """Rotation Steps only with Rotate Shells, the custom map size and region only when Custom is picked (Maya)."""
    if name == "rotate_step":
        return v["rotate"]
    if name == "custom_size":
        return v["map_size"] == "Custom"
    if name in _REGION_FIELDS:
        return v["region"] == "Custom"
    return True


def _run_straighten(context, v):
    return bpy.ops.allset.uv_straighten_uvs('EXEC_DEFAULT', axis=v["direction"], tolerance=v["angle"])


def _run_randomize(context, v):
    return bpy.ops.allset.uv_randomize(
        'EXEC_DEFAULT', translate_u=v["translate_u"], translate_v=v["translate_v"], translate=v["translate"],
        rotate_cw=v["rotate_cw"], rotate_ccw=v["rotate_ccw"], rotate=v["rotate"],
        scale_up=v["scale_up"], scale_down=v["scale_down"], scale=v["scale"])


def _run_uv_grid(context, v):
    """Every UV Editor shows the UDIM tile grid of the window's size (Blender's UDIM Grid overlay; an image with
    UDIM tiles shows its own tiles)."""
    wm = context.window_manager
    for win in wm.windows if wm else ():
        for area in win.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.spaces.active.uv_editor.tile_grid_shape = (v["tiles_u"], v["tiles_v"])
                area.tag_redraw()
    return {'FINISHED'}


WINDOWS = [
    Window("uv_unfold", "Unfold UVs Options", "Unfold", None, [
        F("iterations", "Iterations:", "int", 1, lo=0, hi=10),
        F("layout_uvs", "", "bool", False, text="Layout UVs"),
        # the unfold keeps a shell's border from crossing itself either way; the map size and room space change no
        # result, like Maya's
        F("prevent_border", "", "bool", True, text="Prevent self border intersections"),
        F("prevent_flips", "", "bool", True, text="Prevent triangle flips"),
        F("map_size", "Map size (Pixels):", "enum", "1024", items=UNFOLD_MAP_SIZES),
        F("room_space", "Room space (Pixels):", "int", 0, lo=0, hi=10),
    ], _run_unfold, paths=("UV Editor/Modify/Unfold",),
        missing=("Method: Legacy", "Fix non-manifold geometry")),
    Window("uv_optimize", "Optimize UVs Options", "Optimize", None, [
        F("method", "Method:", "enum", "Unfold3D", items=("Unfold3D", uv_optimize.LEGACY)),
        F("iterations", "Iterations:", "int", 1, lo=0, hi=10),
        F("surfangle", "Surfangle:", "float", 1.0, lo=0.0, hi=1.0),
        F("power", "Power:", "int", 100, lo=0, hi=100),
        F("prevent_flips", "", "bool", True, text="Prevent triangle flips"),
        F("pin_border", "", "bool", True, text="Pin UV border"),
        F("pin_uvs", "Pin UVs:", "bool", False),
        F("pin_which", "", "enum", uv_optimize.PIN_WHICH[0], items=uv_optimize.PIN_WHICH),
        F("edge_weights", "Edge weights:", "enum", uv_optimize.EDGE_WEIGHTS[0], items=uv_optimize.EDGE_WEIGHTS),
        F("max_iterations", "Maximum iterations:", "int", 5, lo=1, hi=10),
    ], _run_optimize, paths=("UV Editor/Modify/Optimize",), enabled=_optimize_enabled,
        missing=("Fix non-manifold geometry", "Prevent self border intersections",
                 "Map size (Pixels), Room space (Pixels)")),
    Window("uv_layout", "Layout UVs Options", "Layout", None, [
        F("multi", "Multiple Objects:", "enum", MULTI[0], items=MULTI),
        F("stack_similar", "Stack Similar:", "bool", False),
        F("pre_rotate", "Shell Pre-Rotation:", "enum", "Off", items=PRE_ROTATE),
        F("pre_scale", "Shell Pre-Scaling:", "enum", "Preserve 3D Ratios", items=PRE_SCALE),
        F("rotate", "Rotate Shells:", "bool", False),
        F("rotate_step", "Rotation Steps:", "float", 90.0, lo=0.0, hi=360.0),
        F("map_size", "Texture Map Size:", "enum", "1024", items=MAP_SIZES),
        F("custom_size", "Custom Map Size:", "int", 1024, lo=1, hi=8192),
        F("padding_units", "Padding Units:", "enum", "Pixels", items=("Pixels", "UV")),
        F("shell_padding", "Shell Padding:", "float", 0.0, lo=0.0, hi=64.0),
        F("tile_padding", "Tile Padding:", "float", 0.0, lo=0.0, hi=64.0),
        F("distribution", "Shell Distribution:", "enum", DISTRIBUTIONS[0], items=DISTRIBUTIONS),
        F("tiles_u", "Tiles U:", "int", 1, lo=1, hi=10),
        F("tiles_v", "Tiles V:", "int", 1, lo=1, hi=10),
        F("region", "Packing Region:", "enum", "Full square", items=_REGIONS),
        F("region_min_u", "U from:", "float", 0.0, lo=0.0, hi=1.0),
        F("region_max_u", "U to:", "float", 1.0, lo=0.0, hi=1.0),
        F("region_min_v", "V from:", "float", 0.0, lo=0.0, hi=1.0),
        F("region_max_v", "V to:", "float", 1.0, lo=0.0, hi=1.0),
        F("scale_mode", "Scale Mode:", "enum", "Uniform", items=SCALE_MODES),
    ], _run_layout, paths=("UV Editor/Modify/Layout",), width=640, enabled=_layout_enabled,
        missing=("Method: Legacy", "Fix non-manifold geometry", "Packing Resolution, Packing Iterations",
                 "Translate Shells (shells are always moved)", "Minimum / Maximum Shell Rotation")),
    Window("straighten_uvs", "Straighten UVs Options", "Straighten UVs", None, [
        F("direction", "Straighten:", "enum", "UV", items=["UV", "U", "V"]),
        F("angle", "Angle tolerance:", "float", tk.STRAIGHTEN_TOLERANCE, lo=0.0, hi=90.0),
    ], _run_straighten, paths=("UV Editor/Modify/Straighten UVs",)),
    Window("randomize_shells", "Randomize Shells Options", "Randomize", None, [
        F("translate_u", "Translate:", "bool", True, text="U"),
        F("translate_v", "", "bool", True, text="V"),
        F("translate", "Units:", "float", tk.RANDOM_TRANSLATE, lo=0.001, hi=1.0),
        F("rotate_cw", "Rotate:", "bool", False, text="Clockwise"),
        F("rotate_ccw", "", "bool", False, text="Counter-clockwise"),
        F("rotate", "Degrees:", "float", tk.RANDOM_ROTATE, lo=1.0, hi=180.0),
        F("scale_up", "Scale:", "bool", False, text="Up"),
        F("scale_down", "", "bool", False, text="Down"),
        F("scale", "Percent:", "float", tk.RANDOM_SCALE, lo=0.1, hi=100.0),
    ], _run_randomize, paths=("UV Editor/Modify/Randomize Shells",)),
    Window("uv_grid", "UV Grid Options", "Apply and Close", None, [
        F("tiles_u", "UDIM tiles across (U):", "int", 1, lo=1, hi=10),
        F("tiles_v", "UDIM tiles up (V):", "int", 1, lo=1, hi=10),
    ], _run_uv_grid, paths=("UV Editor/View/Grid",), click_saved=False),
]
