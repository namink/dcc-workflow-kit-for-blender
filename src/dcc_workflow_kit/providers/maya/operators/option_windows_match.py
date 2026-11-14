# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya option windows of Modify > Match Transformations: Match All Transforms / Translation / Rotation / Scaling /
Pivots ❒.

Same spec as operators/option_windows.py (``F`` fields, ``Window`` = one ``allset.opt_<key>`` operator;
option_windows._extend appends ``WINDOWS``). Titles, labels, buttons and default values match Maya's windows:

- Match All Transforms: Transforms Translate / Rotate / Scale (all on) and Match bounding box size (off, only with
  Scale); nothing checked = nothing runs.
- Match Translation / Rotation / Scaling: All (on) or the X / Y / Z channels (a checked axis turns All off, All turns
  the axes off); Scaling also has Match bounding box size (off).
- Match Pivots: Pivots Rotate / Scale (on) and Orientation (off).
"""

import bpy
from bpy.props import BoolProperty

from .. import i18n
from .option_windows import F, Window

TRANSFORMS = i18n.mark("Transforms")
TRANSLATION = i18n.mark("Translation")
ROTATION = i18n.mark("Rotation")
SCALING = i18n.mark("Scaling")
PIVOTS = i18n.mark("Pivots")
BOX = i18n.mark("Match bounding box size")
TITLES = (i18n.mark("Match All Transforms Options"), i18n.mark("Match Translation Options"),
          i18n.mark("Match Rotation Options"), i18n.mark("Match Scaling Options"), i18n.mark("Match Pivots Options"))
_MENU = "Modify/Match Transformations/"


class FAxis(F):
    """Maya's All / X / Y / Z check boxes: checking All clears the axes, checking an axis clears All."""

    def prop(self):
        name = self.name

        def update(holder, _context):
            if getattr(holder, name):
                for other in (("x", "y", "z") if name == "all" else ("all",)):
                    if getattr(holder, other):
                        setattr(holder, other, False)
        return BoolProperty(name=(self.text or self.label).rstrip(":"), default=self.default, update=update)


def _axis_fields(heading):
    return [FAxis("all", heading + ":", "bool", True, text="All"), FAxis("x", "", "bool", False, text="X"),
            FAxis("y", "", "bool", False, text="Y"), FAxis("z", "", "bool", False, text="Z")]


def _axes(v):
    return (v["all"] or v["x"], v["all"] or v["y"], v["all"] or v["z"])


def _run_all(context, v):
    if not (v["translate"] or v["rotate"] or v["scale"]):
        return {'CANCELLED'}          # Maya runs nothing
    return bpy.ops.allset.match_transform('EXEC_DEFAULT', kind='ALL', translate=v["translate"], rotate=v["rotate"],
                                          scale=v["scale"], box=v["box"] and v["scale"])


def _run_axes(kind):
    def run(context, v):
        axes = _axes(v)
        if not any(axes):
            return {'CANCELLED'}      # Maya runs nothing
        return bpy.ops.allset.match_transform('EXEC_DEFAULT', kind=kind, axes=axes, box=bool(v.get("box")))
    return run


def _run_pivots(context, v):
    if not (v["rotate"] or v["scale"] or v["orient"]):
        return {'CANCELLED'}          # Maya runs nothing
    return bpy.ops.allset.match_pivots('EXEC_DEFAULT', rotate_pivot=v["rotate"], scale_pivot=v["scale"],
                                       orientation=v["orient"])


WINDOWS = [
    Window("match_all", TITLES[0], "Match All Transforms", ("allset.match_transform", {"kind": 'ALL'}), [
        F("translate", TRANSFORMS + ":", "bool", True, text="Translate"), F("rotate", "", "bool", True, text="Rotate"),
        F("scale", "", "bool", True, text="Scale"), F("box", "", "bool", False, text=BOX)], _run_all,
        paths=(_MENU + "Match All Transforms",), enabled=lambda v, name: name != "box" or v["scale"]),
    Window("match_translation", TITLES[1], "Match Translation", ("allset.match_transform", {"kind": 'TRANSLATE'}),
           _axis_fields(TRANSLATION), _run_axes('TRANSLATE'), paths=(_MENU + "Match Translation",)),
    Window("match_rotation", TITLES[2], "Match Rotation", ("allset.match_transform", {"kind": 'ROTATE'}),
           _axis_fields(ROTATION), _run_axes('ROTATE'), paths=(_MENU + "Match Rotation",)),
    Window("match_scaling", TITLES[3], "Match Scaling", ("allset.match_transform", {"kind": 'SCALE'}),
           _axis_fields(SCALING) + [F("box", "", "bool", False, text=BOX)], _run_axes('SCALE'),
           paths=(_MENU + "Match Scaling",)),
    Window("match_pivots", TITLES[4], "Match Pivots", ("allset.match_pivots", {}), [
        F("rotate", PIVOTS + ":", "bool", True, text="Rotate"), F("scale", "", "bool", True, text="Scale"),
        F("orient", "", "bool", False, text="Orientation")], _run_pivots, paths=(_MENU + "Match Pivots",)),
]
