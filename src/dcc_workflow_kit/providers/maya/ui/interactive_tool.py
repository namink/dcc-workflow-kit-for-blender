# SPDX-License-Identifier: GPL-3.0-or-later
"""Create > Polygon Primitives > Interactive Creation as a tool (#225).

With Interactive Creation on, picking a polygon primitive makes this tool current, like Maya's primitive creation
tools: each LMB press in a view starts one primitive (``allset.interactive_create``, operators/interactive_create.py
— Shift / Ctrl ride on the press too). The tool stays current after Esc; Exit On Completion switches to the Select
tool after a primitive, Q / W / E / R or another tool leave it, Y comes back to it. Object Mode only (picking a
primitive leaves component mode, a new primitive is an object).
"""

import bpy

from ..operators import interactive_create

_PRESS = "allset.interactive_create"


def _keymap():
    out = []
    for shift, ctrl in ((False, False), (True, False), (False, True), (True, True)):
        out.append((_PRESS, {"type": 'LEFTMOUSE', "value": 'PRESS', "shift": shift, "ctrl": ctrl}, None))
    return tuple(out)


class ALLSET_TL_interactive_create(bpy.types.WorkSpaceTool):
    """Maya Interactive Creation."""
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = interactive_create.TOOL
    bl_label = "Interactive Creation"
    bl_description = ("Drag in a view to place and size the polygon primitive picked from the Create menu or shelf, "
                      "drag again for its height (Maya Interactive Creation)")
    bl_icon = "ops.mesh.primitive_cube_add_gizmo"
    bl_cursor = 'CROSSHAIR'
    bl_widget = None
    bl_keymap = _keymap()


TOOLS = (ALLSET_TL_interactive_create,)


def register():
    for tool in TOOLS:
        bpy.utils.register_tool(tool, after={"builtin.measure"}, separator=True)


def unregister():
    for tool in reversed(TOOLS):
        bpy.utils.unregister_tool(tool)
