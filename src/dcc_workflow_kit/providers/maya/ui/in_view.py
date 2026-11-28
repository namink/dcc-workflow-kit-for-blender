# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's extrude manipulator, In-View Editor and the INPUTS rows of the last extrusion
.

- Visible while the active edit object's last kit extrusion is valid and its extruded faces are the selection
  (operators/extrude_record.py). Maya swaps the Move manipulator for the extrude one: the kit Move/Scale manipulator
  (ui/manipulator.py) hides meanwhile.
- The manipulator is a Python gizmo group (Blender's C transform gizmo can't be extended).
  Maya's polyExtrudeFace manipulator in the faces' local frame - three
  arrows (Local Translate X red / Y green / Z blue = the normal), a cube past each cone (Local Scale X / Y / Z), three
  plane handles (two Local Translate values) and a light-blue centre square (uniform Local Scale). Every handle runs
  ``allset.extrude_drag`` with its ``handle``; release = one undo step (``extrude.set_params``). Edge / vertex
  extrusions and bevels keep the single arrow of their ``Spec.arrow``. No Blender tooltips (Maya manipulators have
  none).
- Face extrusions and Transform Component of faces / edges (polyMoveFace / polyMoveEdge) add Maya's light-blue ring
  and world / local switch (``TURN``): dragging the ring turns the components about the view axis, a press on it also shows three
  rotate rings; the switch puts the manipulator on world axes, where its handles drive Translate / Scale / Rotate
  instead of the Local values. Both are display states of the manipulator (``tc_state``), not node values.
- The In-View Editor box is drawn by a POST_PIXEL handler; 2D gizmos only pick its rows, its title and the
  drag-speed pie at the title's right end (the shelf's way; the title and the pie only while their options are on).
  The selected row's name is yellow: the row under the pointer, or the last one dragged, clicked or pointed at; a new
  node starts with its first number row. Dragging a row sideways changes the value and selects the row, a click
  without a drag types it, Keep Faces Together toggles. Like Maya, a plain middle drag anywhere in the view changes
  the selected row (over a row: that row; ``allset.inview_drag`` with row -1,
  started by the Channel Box virtual slider's press when no channel is picked, and by a "Mesh" keymap item for the
  edit-mode tools without a middle drag); a middle click only selects, also an On / Off row. Values sit in dark
  fields. Two add-on preferences, off by default (``in_view_settings``): the pie (click / drag round it, empty to
  full clockwise from eight o'clock) slows every row drag down to 2 %; dragging the title moves the box, which then
  keeps that offset from its place beside the manipulator / object. Off, the title has no pie, rows drag at full
  speed, a press on the title goes on to the view and the box stays at its place; the saved speed and offset are
  kept for when an option is turned back on.
- Channel Box INPUTS: the node and five rows (WindowManager text proxies: a UI edit of a WM property pushes no
  undo step, the edit itself is one) + the "only the last one" notice.
- Object mode (T, Show Manipulator Tool, #327): like Maya, the selected object's input node shows without leaving
  object mode - the node picked in Channel Box INPUTS, else the newest one: the last kit operation (its manipulator
  too, when it has one), else the primitive's creation node (polyCube1: Width ... Subdivisions Depth, In-View
  Editor only). The box sits right of the object. Edits rebuild the node on the object-mode mesh; release = one
  undo step.

Code: in_view_target (which node is shown and where, the shared state), extrude_manipulator (the extrude manipulator
gizmos and their drag operators), cb_model_node (the node's Channel Box INPUTS rows); this module keeps the In-View
Editor box (layout, drawing, row / title / pie picking, drag / type / move operators), registration and re-exports.
"""

import math

import blf
import bpy
import gpu
from bpy.props import FloatProperty, IntProperty, PointerProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import cb_entry, creation_inputs, in_view_settings, manipulator
from .. import i18n, undo_steps
from ..operators import bevel_maya, extrude, prim_history, prim_shapes, units   # bevel_maya: registers polyBevel
from ..operators import uv_tools  # noqa: F401  registers the polyAutoProj spec
from ..operators import move_component  # noqa: F401  registers the polyMoveFace / Edge / Vertex specs
from ..operators import extrude_curve  # noqa: F401  registers the extrusion along a curve
from .in_view_target import (_redraw, _scale, _state, arrow_visible, cap_frame, creation_rows,  # noqa: F401
                             is_creation, manip_visible, object_node, record, target)
from .extrude_manipulator import (ALLSET_GGT_extrude, ALLSET_GT_extrude_handle, ALLSET_GT_tc_space,  # noqa: F401
                                  ALLSET_OT_extrude_drag, ALLSET_OT_tc_space, CENTER_COLOUR, CONE_TIP, CUBE_AT,
                                  CUBE_HALF, HANDLES, LOCAL_ROT, PLANE_AT, PLANE_HALF, SCALE_PX, SIZE, VIEW_RING_R,
                                  _no_tooltip, flags, handle_fields, handle_role, handle_shapes, handles_hit,
                                  manip_frame, space_button, tc_state, turnable, unit_px)
from .cb_model_node import (ALLSET_OT_model_channel_entry, ALLSET_PG_history, HISTORY_TIP,  # noqa: F401
                            cb_record, draw_cb_node)

ROW_H = 16          # px at UI scale 1 (Maya In-View rows)
WIDTH = 180
GAP = (150, -6)     # box top-left from the manipulator centre on screen: right of the X / Y handles (
                    # Maya: past the manipulator, 250 px from its centre at a 100 px rotate ring)
OBJECT_GAP = (80, 12)   # object mode: box left past the object's right edge on screen, box top above its middle
FLOAT_STEP = 0.01   # Maya units per px of a sideways drag
ANGLE_STEP = 1.0    # degrees per px (creation node angles)
DIV_PX = 20         # px per division
KINDS = {"thickness": "NONE", "local_translate_z": "NONE", "offset": "NONE", "divisions": "INT",
         "keep_faces_together": "BOOL"}


MAX_ROWS = max(max(len(spec.view_fields) for spec in extrude.SPECS.values()),
               max(len(creation_rows(t)) for t in prim_shapes.NODES))
BOOL_FIELDS = {f for spec in extrude.SPECS.values() for f, k in spec.kinds.items() if k == "BOOL"}
INT_FIELDS = {f for spec in extrude.SPECS.values() for f, k in spec.kinds.items() if k == "INT"}
RANGES = {"random": (0.0, 1.0), "fraction": (0.0, 1.0), "depth": (-1.0, 1.0), "planes": (3, 12), "optimize": (0.0, 1.0),
          "percentage_space": (0.0, 5.0), "width": (0.0, None)}
_ = bevel_maya
BG = (0.22, 0.22, 0.22, 0.92)
TITLE_BG = (0.30, 0.30, 0.30, 0.95)
TEXT = (0.86, 0.86, 0.86, 1.0)
HOT = (1.0, 1.0, 0.35, 1.0)        # Maya's highlighted attribute name
LIT = (1.0, 1.0, 1.0, 1.0)         # the row under the pointer
VALUE_BG = (0.10, 0.10, 0.10, 1.0)  # the dark field behind a value
VALUE_W = 56.0       # value field width, px at UI scale 1
FAN_R = 8.0          # drag-speed pie radius, px at UI scale 1
FAN_START = math.radians(210)   # an empty pie starts at eight o'clock and fills clockwise
FAN_FILL = (0.45, 0.72, 1.0, 1.0)
FAN_TRACK = (0.45, 0.72, 1.0, 0.45)


def layout(region, anchor, scale, fields=extrude.FIELDS, gap=GAP, *, width=WIDTH):
    """Box geometry in region pixels: {"box", "title", "rows": [(field, x0, y0, x1, y1)]}."""
    w, h = width * scale, ROW_H * scale
    n = len(fields) + 1
    x0 = anchor[0] + gap[0] * scale
    top = anchor[1] + gap[1] * scale
    x0 = max(4 * scale, min(x0, region.width - w - 4 * scale))
    top = max(n * h + 4 * scale, min(top, region.height - 4 * scale))
    rows = []
    for i, field in enumerate(fields):
        y1 = top - (i + 1) * h
        rows.append((field, x0, y1 - h, x0 + w, y1))
    return {"box": (x0, top - n * h, x0 + w, top), "title": (x0, top - h, x0 + w, top), "rows": rows}


def anchor(context, ob, rec):
    frame = cap_frame(ob, rec)
    if frame is None:
        return None
    p = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, frame[0])
    return (p.x, p.y) if p is not None else None


def object_anchor(context, ob):
    """Object mode: (right edge, vertical middle) of ``ob``'s bounding box on screen, or None when it is behind the
    view. Maya draws the In-View Editor right of the object there, manipulator or not."""
    pts = [view3d_utils.location_3d_to_region_2d(context.region, context.region_data, ob.matrix_world @ Vector(c))
           for c in ob.bound_box]
    pts = [p for p in pts if p is not None]
    if not pts:
        return None
    ys = [p.y for p in pts]
    return max(p.x for p in pts), (min(ys) + max(ys)) / 2


def first_number_row(rec):
    """Index of the first row that is not On / Off (a node of only switches: 0)."""
    for i, field in enumerate(rec.spec.view_fields):
        if field_kind(rec, field) != "BOOL":
            return i
    return 0


def _sync_node(ob, rec):
    """A node the rows didn't show before: its first number row is the selected one."""
    key = (getattr(ob, "name", None), rec.name)
    if key != _state["node"]:
        _state["node"] = key
        _state["hot"] = first_number_row(rec)
        _state["hover"] = -1


def current_layout(context):
    ob, rec = record(context)
    if rec is None or context.region is None or context.region.type != 'WINDOW' or context.region_data is None:
        return None, None
    from .. import preferences
    if not preferences.get(context).inview_editors:   # Display > Heads Up Display > In-View Editors
        return None, None
    if ob.mode == 'EDIT':
        a, gap = anchor(context, ob, rec), GAP
    else:
        a, gap = object_anchor(context, ob), OBJECT_GAP
    if a is None:
        return None, None
    _sync_node(ob, rec)
    dx, dy = in_view_settings.get_offset()
    scale = _scale()
    blf.size(0, 11 * scale)
    label_width = max((blf.dimensions(0, i18n.iface(rec.spec.labels[f]))[0]
                       for f in rec.spec.view_fields), default=0)
    width = max(WIDTH, label_width / scale + VALUE_W + 15)
    return rec, layout(context.region, a, scale, rec.spec.view_fields,
                       (gap[0] + dx, gap[1] + dy), width=width)


def fan_circle(lay, scale):
    """(x, y, r) of the drag-speed pie at the right end of the title of layout ``lay``."""
    x0, y0, x1, y1 = lay["title"]
    return x1 - (FAN_R + 5.0) * scale, (y0 + y1) / 2, FAN_R * scale


def fan_fraction(cx, cy, x, y):
    """The pie's fraction (0..1) at a point: clockwise from eight o'clock."""
    dx, dy = x - cx, y - cy
    if dx * dx + dy * dy < 0.25:
        return 0.0
    return ((FAN_START - math.atan2(dy, dx)) % math.tau) / math.tau


def on_fan(lay, scale, x, y):
    cx, cy, r = fan_circle(lay, scale)
    return math.hypot(x - cx, y - cy) <= r


def on_title(lay, scale, x, y):
    """On the title bar, off the pie while it is shown: the handle that moves the box."""
    x0, y0, x1, y1 = lay["title"]
    return x0 <= x <= x1 and y0 <= y <= y1 and not (in_view_settings.pie_shown() and on_fan(lay, scale, x, y))


def row_at(lay, x, y):
    """Index of the row under (x, y), or -1."""
    for i, (_f, x0, y0, x1, y1) in enumerate(lay["rows"]):
        if x0 <= x <= x1 and y0 <= y <= y1:
            return i
    return -1


def _channel_slider(context):
    """The Channel Box virtual slider takes a middle drag here: channels picked (object / pose mode), or a picked
    channel of a modeling node in Channel Box INPUTS (edit mode)."""
    if context.mode not in {'OBJECT', 'POSE', 'EDIT_MESH'}:
        return False
    from . import channel_box
    if not channel_box.slider_armed(context):
        return False
    pairs = channel_box.slider_targets(context)
    if context.mode == 'EDIT_MESH':
        pairs = [pair for pair in pairs if pair[1].startswith(channel_box.MODEL_PREFIX)]
    return bool(pairs)


def _plain_middle(context, event):
    """A plain middle press (not the emulated Alt drag, #242)."""
    if event.alt or event.ctrl or event.shift:
        return False
    from ..operators import view
    return not view.emulated_alt_drag(context)


def _middle_drag_here(context, event):
    """A plain middle press in a view that shows the In-View Editor."""
    return _plain_middle(context, event) and current_layout(context)[1] is not None


def mmb_drag(context, event):
    """The Channel Box virtual slider's middle press when it has no channel to drive: like Maya, it drags the In-View
    Editor's row instead while this view shows one. True when that drag started."""
    if not _middle_drag_here(context, event):
        return False
    return bool({'RUNNING_MODAL', 'FINISHED'} & bpy.ops.allset.inview_drag('INVOKE_DEFAULT', row=-1))


def field_kind(rec, field):
    """"BOOL", "INT", "ROTATION" or a number kind of row ``field`` of ``rec``."""
    if is_creation(rec):
        return rec.spec.kinds[field]
    return "BOOL" if field in BOOL_FIELDS else "INT" if field in INT_FIELDS else "NONE"


def value_text(rec, field):
    if is_creation(rec):
        if rec.spec.kinds[field] == "BOOL":
            return "On" if rec.params[field] else "Off"
        return creation_inputs.format_attr(rec.node, field, rec.params[field], bpy.context.scene)
    v = rec.params[field]
    if field in BOOL_FIELDS:
        return "On" if v else "Off"
    if field in INT_FIELDS:
        return str(int(v))
    return cb_entry.fmt_number(v)


# --- drawing -----------------------------------------------------------------------------------------

def _rect(x0, y0, x1, y1, colour):
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]},
                             indices=[(0, 1, 2), (0, 2, 3)])
    shader.uniform_float("color", colour)
    batch.draw(shader)


def _text(x, y, s, colour, size):
    blf.size(0, size)
    blf.color(0, *colour)
    blf.position(0, x, y, 0)
    blf.draw(0, s)


def _draw_fan(cx, cy, r, fraction):
    """The drag-speed pie: a thin full circle and the part ``fraction`` filled clockwise from eight o'clock."""
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    track = [(cx + r * math.cos(FAN_START - math.tau * i / 48), cy + r * math.sin(FAN_START - math.tau * i / 48))
             for i in range(49)]
    batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": track})
    shader.uniform_float("color", FAN_TRACK)
    batch.draw(shader)
    fraction = max(0.0, min(1.0, fraction))
    steps = max(2, round(48 * fraction))
    points = [(cx, cy)] + [(cx + r * math.cos(FAN_START - math.tau * fraction * i / steps),
                            cy + r * math.sin(FAN_START - math.tau * fraction * i / steps)) for i in range(steps + 1)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": points}, indices=[(0, i, i + 1) for i in range(1, steps + 1)])
    shader.uniform_float("color", FAN_FILL)
    batch.draw(shader)


def draw_box():
    """POST_PIXEL of 3D View WINDOW regions: the In-View Editor next to the extrude manipulator."""
    context = bpy.context
    rec, lay = current_layout(context)
    if rec is None:
        return
    from ..marking import draw as marking_draw
    if marking_draw.menu_up():   # Maya's hotbox / marking menus cover the In-View Editor
        return
    s = _scale()
    size = 11 * s
    pad = 5 * s
    gpu.state.blend_set('ALPHA')
    _rect(*lay["box"], BG)
    _rect(*lay["title"], TITLE_BG)
    x0, y0, x1, y1 = lay["title"]
    blf.size(0, size)
    tw = blf.dimensions(0, rec.name)[0]
    _text((x0 + x1 - tw) / 2, y0 + 4 * s, rec.name, TEXT, size)
    if in_view_settings.pie_shown():
        _draw_fan(*fan_circle(lay, s), in_view_settings.get_sensitivity())
    for i, (field, rx0, ry0, rx1, ry1) in enumerate(lay["rows"]):
        hot = i == _state["hot"]
        _text(rx0 + pad, ry0 + 4 * s, i18n.iface(rec.spec.labels[field]), HOT if hot else LIT if i == _state["hover"] else TEXT,
              size)
        v = value_text(rec, field)
        if field_kind(rec, field) == "BOOL":
            v = i18n.iface(v)
        blf.size(0, size)
        vx1 = rx1 - pad
        _rect(vx1 - VALUE_W * s, ry0 + 2 * s, vx1 + 3 * s, ry1 - 1 * s, VALUE_BG)
        _text(vx1 - blf.dimensions(0, v)[0], ry0 + 4 * s, v, HOT if hot else TEXT, size)
    gpu.state.blend_set('NONE')


# --- In-View picking (2D gizmos) -------------------------------------------------------------------

class ALLSET_GT_in_view_row(bpy.types.Gizmo):
    """Row ``row`` of the In-View Editor: picking only (drawn by ``draw_box``)."""
    bl_idname = "ALLSET_GT_in_view_row"
    __slots__ = ("row",)

    def setup(self):
        self.row = 0

    def draw(self, context):
        pass

    def test_select(self, context, location):
        _rec, lay = current_layout(context)
        if lay is None or self.row >= len(lay["rows"]):
            return -1
        _f, x0, y0, x1, y1 = lay["rows"][self.row]
        if x0 <= location[0] <= x1 and y0 <= location[1] <= y1:
            if _state["hot"] != self.row or _state["hover"] != self.row:
                # like Maya: the row under the pointer is the yellow one, and stays it after the pointer leaves
                # (a middle drag in the view then changes it)
                _state["hot"] = self.row
                _state["hover"] = self.row
                context.region.tag_redraw()
            return 0
        if _state["hover"] == self.row:
            _state["hover"] = -1
            context.region.tag_redraw()
        return -1


class ALLSET_GT_in_view_title(bpy.types.Gizmo):
    """The In-View Editor's title bar (off its pie): picking only, drawn by ``draw_box``"""
    bl_idname = "ALLSET_GT_in_view_title"

    def draw(self, context):
        pass

    def test_select(self, context, location):
        if not in_view_settings.title_moves():
            return -1
        _rec, lay = current_layout(context)
        return 0 if lay is not None and on_title(lay, _scale(), *location) else -1


class ALLSET_GT_in_view_fan(bpy.types.Gizmo):
    """The In-View Editor's drag-speed pie: picking only, drawn by ``draw_box``"""
    bl_idname = "ALLSET_GT_in_view_fan"

    def draw(self, context):
        pass

    def test_select(self, context, location):
        if not in_view_settings.pie_shown():
            return -1
        _rec, lay = current_layout(context)
        return 0 if lay is not None and on_fan(lay, _scale(), *location) else -1


class ALLSET_GGT_in_view(bpy.types.GizmoGroup):
    bl_idname = "ALLSET_GGT_in_view"
    bl_label = "Maya In-View Editor"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        return manip_visible(context)

    def setup(self, context):
        for i in range(MAX_ROWS):
            gz = self.gizmos.new(ALLSET_GT_in_view_row.bl_idname)
            gz.row = i
            gz.target_set_operator(ALLSET_OT_inview_drag.bl_idname).row = i
        self.gizmos.new(ALLSET_GT_in_view_title.bl_idname).target_set_operator(ALLSET_OT_inview_move.bl_idname)
        self.gizmos.new(ALLSET_GT_in_view_fan.bl_idname).target_set_operator(ALLSET_OT_inview_fan.bl_idname)


# --- operators ---------------------------------------------------------------------------------------

def preview(context, ob, rec, params, unit):
    """Show ``params`` of node ``rec`` during a drag (no undo step)."""
    if is_creation(rec):
        rec.apply(context, params)
    else:
        extrude.preview(ob, rec, params, unit)


def commit(context, rec, changes):
    """Set ``changes`` on node ``rec`` as one undo step. Returns the operator result."""
    if not is_creation(rec):
        return extrude.set_params(context, **changes)
    if not rec.apply(context, changes):
        return {'CANCELLED'}
    undo_steps.push(rec.name)
    return {'FINISHED'}


def _cursor(context, shape):
    """Set (``shape``) or give back (None) a modal cursor of ``context.window``."""
    window = getattr(context, "window", None)
    if window is None:
        return
    try:
        if shape is None:
            window.cursor_modal_restore()
        else:
            window.cursor_modal_set(shape)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass


class ALLSET_OT_inview_drag(bpy.types.Operator):
    """In-View Editor: drag sideways to change the value (Ctrl: finer, Shift: coarser), click to type it"""
    bl_idname = "allset.inview_drag"
    bl_label = "In-View Editor"
    bl_options = {'INTERNAL'}

    # row -1 = a plain middle drag anywhere in the view (keymap, like Maya): the row under the pointer, else the
    # selected one; passes the event on where this view shows no In-View Editor or the Channel Box slider takes it
    row: IntProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return target(context)[1] is not None

    def invoke(self, context, event):
        middle = self.row < 0
        if middle:
            if _channel_slider(context):
                if context.mode != 'EDIT_MESH' or not _plain_middle(context, event):
                    return {'PASS_THROUGH'}
                # edit mode, a picked channel of a modeling node in Channel Box INPUTS: the Channel Box slider
                # (its own modal; CANCELLED ends this one without an undo step)
                started = bpy.ops.allset.cb_virtual_slider('INVOKE_DEFAULT')
                return {'CANCELLED'} if {'RUNNING_MODAL', 'FINISHED'} & started else {'PASS_THROUGH'}
            if not _middle_drag_here(context, event):
                return {'PASS_THROUGH'}
            _rec, lay = current_layout(context)
            under = row_at(lay, event.mouse_region_x, event.mouse_region_y)
            self.row = under if under >= 0 else _state["hot"]
        ob, rec = target(context)
        if rec is None or self.row >= len(rec.spec.view_fields):
            return {'CANCELLED'}
        field = rec.spec.view_fields[self.row]
        _state["hot"] = self.row
        if field_kind(rec, field) == "BOOL" and middle:
            _redraw(context)
            return {'FINISHED'}
        if field_kind(rec, field) == "BOOL":
            commit(context, rec, {field: not rec.params[field]})
            _redraw(context)
            return {'FINISHED'}
        self._ob, self._rec, self._field = ob, rec, field
        self._start = dict(rec.params)
        self._x0, self._moved = event.mouse_x, False
        self._button = 'MIDDLEMOUSE' if middle else event.type if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE'} \
            else 'LEFTMOUSE'
        self._unit = units.maya_unit(context.scene)
        self._cursor = self._button == 'MIDDLEMOUSE'
        if self._cursor:
            _cursor(context, 'MOVE_X')
        _redraw(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _value(self, event):
        s = _scale()
        dx = (event.mouse_x - self._x0) / s * in_view_settings.speed()
        start = self._start[self._field]
        kind = field_kind(self._rec, self._field)
        if kind == "INT":
            value = int(start + round(dx / DIV_PX))
            return self._rec.clamp(self._field, value) if is_creation(self._rec) else max(1, value)
        step = (ANGLE_STEP if kind == "ROTATION" else FLOAT_STEP) * (0.1 if event.ctrl else 10.0 if event.shift
                                                                     else 1.0)
        value = round(start + dx * step, 4)
        return self._rec.clamp(self._field, value) if is_creation(self._rec) else clamp(self._field, value)

    def _end(self, context):
        if self._cursor:
            _cursor(context, None)
            self._cursor = False
        _redraw(context)

    def cancel(self, context):
        self._end(context)

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            if abs(event.mouse_x - self._x0) > 3 * _scale():
                self._moved = True
            if self._moved:
                params = dict(self._start, **{self._field: self._value(event)})
                preview(context, self._ob, self._rec, params, self._unit)
                _redraw(context)
            return {'RUNNING_MODAL'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            if self._moved:
                preview(context, self._ob, self._rec, self._start, self._unit)
                self._rec.live = False
            self._end(context)
            return {'CANCELLED'}
        if event.type == self._button and event.value == 'RELEASE':
            self._end(context)
            if self._moved:
                commit(context, self._rec, {self._field: self._value(event)})
            elif self._button == 'LEFTMOUSE':      # an MMB click only selects the row
                bpy.ops.allset.inview_type('INVOKE_DEFAULT', row=self.row)
            _redraw(context)
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


class ALLSET_OT_inview_fan(bpy.types.Operator):
    """In-View Editor drag speed: click or drag round the pie (empty = slowest, full = full speed)"""
    bl_idname = "allset.inview_fan"
    bl_label = "In-View Editor Drag Speed"
    bl_options = {'INTERNAL'}       # a setting of the editor, no undo step

    @classmethod
    def poll(cls, context):
        return in_view_settings.pie_shown() and target(context)[1] is not None

    def invoke(self, context, event):
        _rec, lay = current_layout(context)
        if lay is None:
            return {'CANCELLED'}
        self._cx, self._cy, _r = fan_circle(lay, _scale())
        self._start = in_view_settings.get_sensitivity()
        self._set(context, event)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _set(self, context, event):
        in_view_settings.set_sensitivity(fan_fraction(self._cx, self._cy, event.mouse_region_x,
                                                      event.mouse_region_y))
        _redraw(context)

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._set(context, event)
            return {'RUNNING_MODAL'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            in_view_settings.set_sensitivity(self._start)
            _redraw(context)
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


class ALLSET_OT_inview_move(bpy.types.Operator):
    """Drag the In-View Editor by its title to move it"""
    bl_idname = "allset.inview_move"
    bl_label = "Move In-View Editor"
    bl_options = {'INTERNAL'}       # where the box sits is no scene change: no undo step

    @classmethod
    def poll(cls, context):
        return in_view_settings.title_moves() and target(context)[1] is not None

    def invoke(self, context, event):
        self._start = in_view_settings.get_offset()
        self._mouse = (event.mouse_x, event.mouse_y)
        _cursor(context, 'SCROLL_XY')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        _cursor(context, None)

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            s = _scale() or 1.0
            in_view_settings.set_offset(self._start[0] + (event.mouse_x - self._mouse[0]) / s,
                                        self._start[1] + (event.mouse_y - self._mouse[1]) / s)
            _redraw(context)
            return {'RUNNING_MODAL'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            in_view_settings.set_offset(*self._start)
            _cursor(context, None)
            _redraw(context)
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            _cursor(context, None)
            _redraw(context)
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


class ALLSET_OT_inview_type(bpy.types.Operator):
    """Type a value of the last extrusion (In-View Editor)"""
    bl_idname = "allset.inview_type"
    bl_label = "In-View Editor"
    bl_options = {'INTERNAL'}

    row: IntProperty(options={'SKIP_SAVE'})
    number: FloatProperty(name="Value")
    count: IntProperty(name="Divisions", min=1)
    whole: IntProperty(name="Value")          # a creation node's whole number (its own limits)

    @classmethod
    def poll(cls, context):
        return target(context)[1] is not None

    def _field(self, context):
        _ob, rec = target(context)
        if rec is None or self.row >= len(rec.spec.view_fields):
            return rec, None
        return rec, rec.spec.view_fields[self.row]

    @staticmethod
    def _prop(rec, field):
        if field_kind(rec, field) == "INT":
            return "whole" if is_creation(rec) else "count"
        return "number"

    def invoke(self, context, event):
        rec, field = self._field(context)
        if field is None:
            return {'CANCELLED'}
        prop = self._prop(rec, field)
        setattr(self, prop, (int if prop != "number" else float)(rec.params[field]))
        return context.window_manager.invoke_props_dialog(self, title=f"{rec.name}: {i18n.iface(rec.spec.labels[field])}")

    def draw(self, context):
        rec, field = self._field(context)
        if field is not None:
            self.layout.prop(self, self._prop(rec, field), text=rec.spec.labels[field])

    def execute(self, context):
        rec, field = self._field(context)
        if field is None:
            return {'CANCELLED'}
        value = getattr(self, self._prop(rec, field))
        value = rec.clamp(field, value) if is_creation(rec) else value if field in INT_FIELDS else clamp(field, value)
        res = commit(context, rec, {field: value})
        _redraw(context)
        return res


def clamp(field, value):
    lo, hi = RANGES.get(field, (None, None))
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


classes = (ALLSET_OT_model_channel_entry, ALLSET_PG_history, ALLSET_GT_in_view_row, ALLSET_GT_in_view_title, ALLSET_GT_in_view_fan,
           ALLSET_GGT_in_view, ALLSET_GT_extrude_handle, ALLSET_GT_tc_space, ALLSET_GGT_extrude,
           ALLSET_OT_inview_drag, ALLSET_OT_inview_fan, ALLSET_OT_inview_move, ALLSET_OT_inview_type,
           ALLSET_OT_extrude_drag, ALLSET_OT_tc_space)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.allset_history = PointerProperty(type=ALLSET_PG_history)
    _state["handle"] = bpy.types.SpaceView3D.draw_handler_add(draw_box, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    if _state["handle"] is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_state["handle"], 'WINDOW')
        _state["handle"] = None
    del bpy.types.WindowManager.allset_history
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
