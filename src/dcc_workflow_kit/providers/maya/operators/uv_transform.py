# SPDX-License-Identifier: GPL-3.0-or-later
"""UV Toolkit Transform section (Maya): Pivot, Move, Rotate, Scale, and the Align and Snap section's Snap grid.

- Pivot: the nine buttons put the pivot on a corner, an edge middle or the centre of the selected UVs' bounding box
  (or of the UV Area range, 0-1 by default). The kit's pivot is the UV Editor's 2D cursor with the transform pivot
  set to the 2D cursor, so the UV Editor's own Move / Rotate / Scale turn about it too. Reset = the selection's
  centre again; Edit Pivot = the Cursor tool (drag the pivot).
- Move: the eight buttons move the selected UVs by the step (0.1) in that direction; the U / V fields show the
  centre of the selected UVs' bounding box, and a typed value moves the selection there (Retain Component Spacing
  on) or puts every selected UV on that value (off). Distribute spaces the selected UVs evenly along U or V.
- Step Snap per area: the UV Editor's Move / Rotate / Scale tools move, turn or scale in steps (Blender's UV increment
  snapping); the Move step is the UV grid step, the Rotate step Blender's 2D angle increment.
- Rotate: turn the selected UVs by the angle (90 degrees) counterclockwise or clockwise about the pivot, in the
  shown image's pixels (a non-square image keeps its shapes); the buttons' right-click menu turns by 45 or 15.
- Scale: scale the selected UVs by the factor (2) in U and V, U only or V only, about the pivot; Shrink divides.
- Snap: the shells of the selection move as one block onto a corner, an edge middle or the centre of the Snap
  range (0-1 by default).

With the UV Shell mask the whole shells of the selection take part.
"""

import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty

from .. import results, undo_steps
from . import uv_tools
from .uv_modify import all_points, selected_ids
from .uv_shells import _index_loops, _meshes, _poll

# position -> (fraction of the box along U, along V)
POSITIONS = (
    ('TOP_LEFT', "Top Left", (0.0, 1.0)), ('TOP', "Top", (0.5, 1.0)), ('TOP_RIGHT', "Top Right", (1.0, 1.0)),
    ('LEFT', "Left", (0.0, 0.5)), ('CENTER', "Center", (0.5, 0.5)), ('RIGHT', "Right", (1.0, 0.5)),
    ('BOTTOM_LEFT', "Bottom Left", (0.0, 0.0)), ('BOTTOM', "Bottom", (0.5, 0.0)),
    ('BOTTOM_RIGHT', "Bottom Right", (1.0, 0.0)),
)
FRACTION = {k: f for k, _l, f in POSITIONS}
# direction -> (U sign, V sign)
DIRECTIONS = (
    ('UP_LEFT', "Up Left", (-1, 1)), ('UP', "Up", (0, 1)), ('UP_RIGHT', "Up Right", (1, 1)),
    ('LEFT', "Left", (-1, 0)), ('RIGHT', "Right", (1, 0)),
    ('DOWN_LEFT', "Down Left", (-1, -1)), ('DOWN', "Down", (0, -1)), ('DOWN_RIGHT', "Down Right", (1, -1)),
)
SIGNS = {k: s for k, _l, s in DIRECTIONS}


def _items(table):
    return tuple((k, label, "") for k, label, _v in table)


def _settings(context):
    return context.scene.allset_uv_toolkit


# --- the selected UVs ----------------------------------------------------------------------------------------------

def picked(context):
    """[(object, bmesh, uv layer, loops)] of the selected UVs (UV Shell mask: the whole shells of the selection)."""
    from .uv_toolkit_ops import _shell_mode
    synced = uv_tools.sync(context)
    shells = _shell_mode(context)
    out = []
    for ob in _meshes(context):
        bm = bmesh.from_edit_mesh(ob.data)
        uv = bm.loops.layers.uv.active
        if uv is None:
            continue
        _index_loops(bm)
        if shells:
            loops = [lp for isl in uv_tools.target_islands(bm, uv, synced, fallback=False) for f in isl
                     for lp in f.loops]
        else:
            pts, _where = all_points(bm, uv)
            loops = [lp for i in selected_ids(bm, uv, synced, pts) for lp in pts[i]]
        if loops:
            out.append((ob, bm, uv, loops))
    return out


def shells_of(context):
    """Like ``picked`` with the whole shells of the selection (Snap moves shells)."""
    synced = uv_tools.sync(context)
    out = []
    for ob in _meshes(context):
        bm = bmesh.from_edit_mesh(ob.data)
        uv = bm.loops.layers.uv.active
        if uv is None:
            continue
        loops = [lp for isl in uv_tools.target_islands(bm, uv, synced, fallback=False) for f in isl
                 for lp in f.loops]
        if loops:
            out.append((ob, bm, uv, loops))
    return out


def bounds(found):
    """(min U, min V, max U, max V) over every mesh's picked UVs, or None."""
    us = [lp[uv].uv.x for _o, _b, uv, loops in found for lp in loops]
    vs = [lp[uv].uv.y for _o, _b, uv, loops in found for lp in loops]
    if not us:
        return None
    return min(us), min(vs), max(us), max(vs)


def centre(found):
    box = bounds(found)
    return None if box is None else ((box[0] + box[2]) * 0.5, (box[1] + box[3]) * 0.5)


def _apply(found, fn):
    for ob, _bm, uv, loops in found:
        for lp in set(loops):
            lp[uv].uv = fn(lp[uv].uv.x, lp[uv].uv.y)
        bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)


def move(found, du, dv):
    _apply(found, lambda u, v: (u + du, v + dv))


def _space(context):
    space = getattr(context, "space_data", None)
    if space is not None and space.type == 'IMAGE_EDITOR':
        return space
    from .uv_components import find_uv_editor
    area = find_uv_editor(context)[1]
    return area.spaces.active if area is not None else None


def _image_size(space):
    image = getattr(space, "image", None)
    if image is not None and image.size[0] and image.size[1]:
        return float(image.size[0]), float(image.size[1])
    return 256.0, 256.0         # Blender's UV Editor without an image


def cursor_uv(space):
    """The UV Editor's 2D cursor in UV units (Blender reports it in the shown image's pixels)."""
    w, h = _image_size(space)
    return space.cursor_location[0] / w, space.cursor_location[1] / h


def set_cursor_uv(space, u, v):
    w, h = _image_size(space)
    space.cursor_location = (u * w, v * h)


def pivot(context, found):
    """Where Rotate / Scale turn: the 2D cursor while it is the transform pivot (the kit's UV pivot), else the
    centre of the selected UVs' bounding box."""
    space = _space(context)
    if space is not None and space.pivot_point == 'CURSOR':
        return cursor_uv(space)
    return centre(found)


# --- Pivot ---------------------------------------------------------------------------------------------------------

def _range(s, prefix):
    lo_u, hi_u = getattr(s, prefix + "_min_u"), getattr(s, prefix + "_max_u")
    lo_v, hi_v = getattr(s, prefix + "_min_v"), getattr(s, prefix + "_max_v")
    return float(lo_u), float(lo_v), float(hi_u), float(hi_v)


@undo_steps.no_redo_panel
class ALLSET_OT_uv_pivot(bpy.types.Operator):
    """Put the UV pivot on this point of the selected UVs' bounding box, or of the UV Area range"""
    bl_idname = "allset.uv_pivot"
    bl_label = "UV Pivot"
    bl_options = {'REGISTER', 'UNDO'}

    position: EnumProperty(items=_items(POSITIONS), default='CENTER', options={'SKIP_SAVE'})

    poll = classmethod(lambda cls, context: _poll(context) and _space(context) is not None)

    def execute(self, context):
        s = _settings(context)
        if s.pivot_area == 'UV_AREA':
            box = _range(s, "pivot")
        else:
            box = bounds(picked(context))
            if box is None:
                self.report({'WARNING'}, "Select UVs to place the pivot")
                return {'CANCELLED'}
        fu, fv = FRACTION[self.position]
        space = _space(context)
        set_cursor_uv(space, box[0] + (box[2] - box[0]) * fu, box[1] + (box[3] - box[1]) * fv)
        space.pivot_point = 'CURSOR'
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_uv_pivot_reset(bpy.types.Operator):
    """Put the UV pivot back on the centre of the selected UVs"""
    bl_idname = "allset.uv_pivot_reset"
    bl_label = "Reset UV Pivot"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(lambda cls, context: _poll(context) and _space(context) is not None)

    def execute(self, context):
        space = _space(context)
        c = centre(picked(context))
        if c is not None:
            set_cursor_uv(space, *c)
        space.pivot_point = 'BOUNDING_BOX_CENTER'
        return {'FINISHED'}


class ALLSET_OT_uv_pivot_edit(bpy.types.Operator):
    """Edit the UV pivot: drag it with the Cursor tool; the UV Editor's tools turn about it"""
    bl_idname = "allset.uv_pivot_edit"
    bl_label = "Edit UV Pivot"
    bl_options = {'INTERNAL'}

    poll = classmethod(lambda cls, context: _poll(context) and _space(context) is not None)

    def execute(self, context):
        space = _space(context)
        if space.pivot_point != 'CURSOR':
            c = centre(picked(context))
            if c is not None:
                set_cursor_uv(space, *c)
            space.pivot_point = 'CURSOR'
        from .uv_components import set_uv_editor_tool
        return set_uv_editor_tool(context, "builtin.cursor")


# --- Move ----------------------------------------------------------------------------------------------------------

@undo_steps.no_redo_panel
class ALLSET_OT_uv_nudge(bpy.types.Operator):
    """Move the selected UVs by the Move step in this direction"""
    bl_idname = "allset.uv_nudge"
    bl_label = "Move UVs"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=_items(DIRECTIONS), default='RIGHT', options={'SKIP_SAVE'})

    poll = classmethod(lambda cls, context: _poll(context))

    def execute(self, context):
        found = picked(context)
        if not found:
            self.report({'WARNING'}, "Select UVs to move")
            return {'CANCELLED'}
        step = _settings(context).nudge
        su, sv = SIGNS[self.direction]
        move(found, su * step, sv * step)
        return {'FINISHED'}


def position_get(axis):
    def get(_self):
        try:
            from ..ui import uv_hud
            c = uv_hud.selection_centre(bpy.context)
        except (AttributeError, ReferenceError, RuntimeError):
            c = None
        return 0.0 if c is None else c[axis]
    return get


def position_set(axis):
    def set_(_self, value):
        context = bpy.context
        if context.mode != 'EDIT_MESH':
            return
        found = picked(context)
        c = centre(found)
        if c is None:
            return
        if not _settings(context).retain_spacing:       # every selected UV onto the value
            _apply(found, lambda u, v: (value, v) if axis == 0 else (u, value))
            return
        d = value - c[axis]
        move(found, d if axis == 0 else 0.0, d if axis == 1 else 0.0)
    return set_


# --- Step Snap (per area) -------------------------------------------------------------------------------------------

def uv_space(context):
    return _space(context)


def apply_move_step(context):
    """Move Step Snap value -> the UV Editor's grid step (Blender's UV increment snapping moves by the grid)."""
    space = _space(context)
    value = _settings(context).move_snap_value
    if space is None or value <= 0:
        return
    n = max(1, int(round(1.0 / value)))
    ed = space.uv_editor
    try:
        ed.grid_shape_source = 'FIXED'
        ed.custom_grid_subdivisions = (n, n)
    except (AttributeError, TypeError, ValueError):
        pass


def move_step_update(self, context):
    apply_move_step(context)


def rotate_step_update(self, context):
    context.scene.tool_settings.snap_angle_increment_2d = math.radians(self.rotate_snap_value)


# --- Rotate / Scale ------------------------------------------------------------------------------------------------

def rotate(found, about, degrees, aspect=1.0):
    """Turn counterclockwise by ``degrees`` about ``about``; ``aspect`` = the image's width / height: the turn happens
    in pixels, so a shape keeps its look on a non-square image."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    pu, pv = about
    k = aspect if aspect > 0 else 1.0

    def fn(u, v):
        du, dv = (u - pu) * k, v - pv
        return pu + (du * c - dv * s) / k, pv + du * s + dv * c
    _apply(found, fn)


def image_aspect(context):
    """Width / height of the image the UV Editor shows (1 without an image)."""
    space = _space(context)
    image = getattr(space, "image", None) if space is not None else None
    if image is not None and image.size[0] and image.size[1]:
        return float(image.size[0]) / float(image.size[1])
    return 1.0


def scale(found, about, su, sv):
    pu, pv = about
    _apply(found, lambda u, v: (pu + (u - pu) * su, pv + (v - pv) * sv))


@undo_steps.no_redo_panel
class ALLSET_OT_uv_rotate_step(bpy.types.Operator):
    """Turn the selected UVs by the Rotate angle about the UV pivot"""
    bl_idname = "allset.uv_rotate_step"
    bl_label = "Rotate UVs"
    bl_options = {'REGISTER', 'UNDO'}

    clockwise: BoolProperty(options={'SKIP_SAVE'})
    angle: FloatProperty(options={'SKIP_SAVE'}, default=0.0,
                         description="Degrees to turn (0 = the Rotate angle of the toolkit)")

    poll = classmethod(lambda cls, context: _poll(context))

    def execute(self, context):
        found = picked(context)
        if not found:
            self.report({'WARNING'}, "Select UVs to rotate")
            return {'CANCELLED'}
        angle = self.angle or _settings(context).rotate_angle
        rotate(found, pivot(context, found), -angle if self.clockwise else angle, image_aspect(context))
        return {'FINISHED'}


def rotate_button_menu(self, context):
    """Right-click on a Rotate button of the UV Toolkit: turn by 45 or 15 degrees that way (Maya: middle / right
    click on the button)."""
    op = getattr(context, "button_operator", None)
    if op is None or getattr(op, "bl_rna", None) is None or op.bl_rna.identifier != "ALLSET_OT_uv_rotate_step":
        return
    layout = self.layout
    layout.separator()
    for angle in (45.0, 15.0):
        o = layout.operator("allset.uv_rotate_step", text=f"Rotate {angle:g}\u00b0")
        o.clockwise, o.angle = op.clockwise, angle


@undo_steps.no_redo_panel
class ALLSET_OT_uv_scale_step(bpy.types.Operator):
    """Scale the selected UVs by the Scale factor about the UV pivot (in U and V, U only or V only)"""
    bl_idname = "allset.uv_scale_step"
    bl_label = "Scale UVs"
    bl_options = {'REGISTER', 'UNDO'}

    shrink: BoolProperty(options={'SKIP_SAVE'}, description="Divide by the factor")

    poll = classmethod(lambda cls, context: _poll(context))

    def execute(self, context):
        s = _settings(context)
        if abs(s.scale_factor) < 1e-9:
            self.report({'WARNING'}, "The Scale factor is 0")
            return {'CANCELLED'}
        found = picked(context)
        if not found:
            self.report({'WARNING'}, "Select UVs to scale")
            return {'CANCELLED'}
        f = 1.0 / s.scale_factor if self.shrink else s.scale_factor
        scale(found, pivot(context, found), 1.0 if s.scale_axis == 'V' else f, 1.0 if s.scale_axis == 'U' else f)
        return {'FINISHED'}


# --- Snap ----------------------------------------------------------------------------------------------------------

@undo_steps.no_redo_panel
class ALLSET_OT_uv_snap_shells(bpy.types.Operator):
    """Move the shells of the selection as one block onto this point of the Snap range"""
    bl_idname = "allset.uv_snap_shells"
    bl_label = "Snap UV Shells"
    bl_options = {'REGISTER', 'UNDO'}

    position: EnumProperty(items=_items(POSITIONS), default='CENTER', options={'SKIP_SAVE'})

    poll = classmethod(lambda cls, context: _poll(context))

    def execute(self, context):
        found = shells_of(context)
        box = bounds(found)
        if box is None:
            self.report({'WARNING'}, "Select UVs of the shells to snap")
            return {'CANCELLED'}
        lo_u, lo_v, hi_u, hi_v = _range(_settings(context), "snap")
        fu, fv = FRACTION[self.position]
        # the block's point at this fraction lands on the range's point at the same fraction
        du = (lo_u + (hi_u - lo_u) * fu) - (box[0] + (box[2] - box[0]) * fu)
        dv = (lo_v + (hi_v - lo_v) * fv) - (box[1] + (box[3] - box[1]) * fv)
        move(found, du, dv)
        results.result(self, "Snapped the UV shells")
        return {'FINISHED'}


# Maya's preset lists of the UV Toolkit Transform fields
PRESETS = {"nudge": (1.0, 0.1, 0.01), "rotate_angle": (15.0, 45.0, 90.0, 180.0), "scale_factor": (2.0, 4.0),
           "texel_density": (8.0, 16.0, 32.0)}
PRESET_OWNER = {"texel_density": "scene.allset_uv"}     # the others: scene.allset_uv_toolkit


def _preset_menu_class(prop):
    def draw(self, context):
        for value in PRESETS[prop]:
            o = self.layout.operator("wm.context_set_float", text=f"{value:g}", translate=False)
            o.data_path, o.value = f"{PRESET_OWNER.get(prop, 'scene.allset_uv_toolkit')}.{prop}", value
    return type(f"ALLSET_MT_uvtk_preset_{prop}", (bpy.types.Menu,), {
        "bl_idname": f"ALLSET_MT_uvtk_preset_{prop}", "bl_label": "Presets", "draw": draw,
        "__doc__": "Preset values"})


PRESET_MENUS = tuple(_preset_menu_class(p) for p in PRESETS)


@undo_steps.no_redo_panel
class ALLSET_OT_uv_distribute_toolkit(bpy.types.Operator):
    """Distribute the selected UVs evenly along U or V (UV Toolkit Move); the options button sets a custom distance"""
    bl_idname = "allset.uv_distribute_toolkit"
    bl_label = "Distribute UVs"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(lambda cls, context: _poll(context))

    def execute(self, context):
        axis = _settings(context).distribute_axis
        return bpy.ops.allset.uv_distribute_uvs('EXEC_DEFAULT', axis=axis, distance=0.0)


classes = (ALLSET_OT_uv_pivot, ALLSET_OT_uv_pivot_reset, ALLSET_OT_uv_pivot_edit, ALLSET_OT_uv_nudge,
           ALLSET_OT_uv_rotate_step, ALLSET_OT_uv_scale_step, ALLSET_OT_uv_snap_shells, ALLSET_OT_uv_distribute_toolkit,
           *PRESET_MENUS)


def register_extra():
    bpy.types.UI_MT_button_context_menu.prepend(rotate_button_menu)


def unregister_extra():
    bpy.types.UI_MT_button_context_menu.remove(rotate_button_menu)
