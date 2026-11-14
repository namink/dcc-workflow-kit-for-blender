# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's extrude manipulator, In-View Editor and the INPUTS rows of the last extrusion
.

- Visible while the active edit object's last kit extrusion is valid and its extruded faces are the selection
  (operators/extrude.py). Maya swaps the Move manipulator for the extrude one: the kit Move/Scale manipulator
  (ui/manipulator.py) hides meanwhile.
- The manipulator is a Python gizmo group (Blender's C transform gizmo can't be extended).
  Maya's polyExtrudeFace manipulator in the faces' local frame - three
  arrows (Local Translate X red / Y green / Z blue = the normal), a cube past each cone (Local Scale X / Y / Z), three
  plane handles (two Local Translate values) and a light-blue centre square (uniform Local Scale). Every handle runs
  ``allset.extrude_drag`` with its ``handle``; release = one undo step (``extrude.set_params``). Edge / vertex
  extrusions and bevels keep the single arrow of their ``Spec.arrow``. No Blender tooltips (Maya manipulators have
  none).
- Transform Component of faces / edges (polyMoveFace / polyMoveEdge) adds Maya's light-blue ring and world / local
  switch (``TURN``): dragging the ring turns the components about the view axis, a press on it also shows three
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
"""

import math

import blf
import bmesh
import bpy
import gpu
from bpy.props import FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector, geometry

from . import cb_entry, creation_inputs, in_view_settings, manipulator
from .. import undo_steps
from ..operators import bevel_maya, extrude, prim_history, prim_shapes, units   # bevel_maya: registers polyBevel
from ..operators import uv_tools  # noqa: F401  registers the polyAutoProj spec
from ..operators import move_component  # noqa: F401  registers the polyMoveFace / Edge / Vertex specs
from ..operators import extrude_curve  # noqa: F401  registers the extrusion along a curve

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
# every field of every recorded node (Channel Box text proxies: edge / vertex extrusion, bevel)
ALL_FIELDS = tuple(dict.fromkeys(f for spec in extrude.SPECS.values() for f in spec.fields))


def creation_rows(node_type):
    """The In-View Editor rows of a creation node: its Channel Box values without the axis / pivot / normal /
    centre ones and the choice lists (polyCube: Width, Height, Depth, Subdivisions Width / Height / Depth)."""
    return tuple(n for n in creation_inputs.node_rows(node_type)
                 if n not in creation_inputs.AXIS_ATTRS and prim_history.entry_kind(node_type, n) != "ENUM")


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
YELLOW = (1.0, 1.0, 0.0)
VALUE_W = 56.0       # value field width, px at UI scale 1
FAN_R = 8.0          # drag-speed pie radius, px at UI scale 1
FAN_START = math.radians(210)   # an empty pie starts at eight o'clock and fills clockwise
FAN_FILL = (0.45, 0.72, 1.0, 1.0)
FAN_TRACK = (0.45, 0.72, 1.0, 0.45)

# hot = the selected row (yellow, the one MMB drags; the row under the pointer selects itself), hover = the row under
# the pointer, node = which node the rows belong to (a new one selects its first number row)
_state = {"hot": 0, "hover": -1, "node": None, "handle": None}


def _scale():
    return bpy.context.preferences.system.ui_scale


# --- what is shown -----------------------------------------------------------------------------------

class _CreationSpec:
    """The ``extrude.Spec`` attributes the In-View Editor reads, for a creation node type: rows only, no
    manipulator."""
    arrow = None
    in_view = True
    component = None
    full_manip = False
    manip = ()

    def __init__(self, node_type):
        self.node = self.node_type = node_type
        self.view_fields = self.fields = creation_rows(node_type)
        self.labels = {n: prim_shapes.spec(node_type, n)[1] for n in self.fields}
        self.kinds = {n: prim_history.entry_kind(node_type, n) for n in self.fields}


class CreationNode:
    """A primitive's creation node (polyCube1 ...) as the In-View Editor shows it: ``name``, ``spec``, ``params``
    (Maya units / degrees, like the Channel Box)."""
    creation = True
    dismissed = False

    def __init__(self, ob, owner, node):
        self.ob, self.owner, self.node = ob, owner, node
        self.name = node["name"]
        self.spec = _CreationSpec(node["type"])
        self.params = prim_history.attrs(owner)

    def clamp(self, field, value):
        return prim_shapes.clamp(self.node["type"], field, value)

    def apply(self, context, changes):
        """Rebuild the shape with ``changes`` (no undo step); True when the node was still there."""
        values = prim_history.rebuild(context, self.ob, changes)
        if values is None:
            return False
        self.owner, self.node = prim_history.node_of(self.ob)
        self.params = dict(values)
        return True


def is_creation(rec):
    return getattr(rec, "creation", False)


def object_node(ob):
    """Object mode: the input node T shows for ``ob`` - the one picked in Channel Box INPUTS when the kit can show
    it, else the newest: the last kit operation (``extrude.object_record``), else the creation node. None when
    there is none."""
    nodes = []
    rec = extrude.object_record(ob)
    if rec is not None and rec.spec.in_view:
        nodes.append(rec)
    owner, node = prim_history.node_of(ob)
    if node is not None and creation_rows(node["type"]):
        nodes.append(CreationNode(ob, owner, node))
    if not nodes:
        return None
    from . import channel_box
    picked = channel_box.picked_node(ob)
    return next((n for n in nodes if picked == channel_box.history_node(n.name)), nodes[0])


def object_shown(context):
    """(object, node) T showed in object mode while that object is the selected active one, else (None, None)."""
    if getattr(context, "mode", None) != 'OBJECT' or not extrude.SHOWN:
        return None, None
    ob = getattr(context, "active_object", None)
    try:
        if ob is None or ob.name != extrude.SHOWN.get("ob") or not ob.select_get():
            return None, None
    except (ReferenceError, RuntimeError):
        return None, None
    node = object_node(ob)
    return (ob, node) if node is not None else (None, None)


def target(context):
    """(object, node) the In-View Editor and manipulator edit: the edit object's last kit node, or in object mode the
    node T showed; else (None, None)."""
    ob, rec = extrude.active(context)
    if rec is not None:
        return ob, rec
    return object_shown(context)


def record(context):
    """(object, record) when the manipulator / In-View Editor show in this 3D View, else (None, None). Object mode:
    the node T showed (a ``CreationNode`` for a creation node)."""
    space = getattr(context, "space_data", None)
    if space is None or space.type != 'VIEW_3D':
        return None, None
    from .toolbox import is_toolbox
    if is_toolbox(space):
        return None, None
    ob, rec = extrude.active(context)
    if rec is None:
        return object_shown(context)
    if rec.dismissed or not rec.spec.in_view or not extrude.caps_selected(ob, rec):
        return None, None
    return ob, rec


def manip_visible(context):
    return record(context)[1] is not None


def arrow_visible(context):
    rec = record(context)[1]
    return rec is not None and rec.spec.arrow is not None


def _pre_direction(rec):
    """Arrow direction of an edge / vertex extrusion or a bevel, from the mesh before it (cached)."""
    d = getattr(rec, "arrow_dir", None)
    if d is not None:
        return d
    pre = rec.pre
    d = Vector()
    if pre is not None:
        pre.normal_update()
        component = rec.spec.component or ('VERTEX' if rec.spec.kind == 'VERTEX' else 'EDGE')
        if component == 'FACE':
            for f in pre.faces:
                if f.select:
                    d += f.normal
        elif component == 'VERTEX':
            for v in pre.verts:
                if v.select:
                    d += sum((f.normal for f in v.link_faces), Vector()).normalized()
        else:
            for e in pre.edges:
                if e.select:
                    d += extrude.edge_frame(e)[2]
    rec.arrow_dir = d
    return d


def cap_frame(ob, rec):
    """(world centre, world unit normal, world length of one local unit along it) of the extruded faces (edge /
    vertex extrusion: the selection it left, the mean edge / vertex normal; bevel: the bevel's vertices). Object mode
    reads the mesh data (the selection the node left = its stored one); a creation node: the object's bounds centre."""
    if is_creation(rec):
        corners = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        return sum(corners, Vector()) / len(corners), Vector((0.0, 0.0, 1.0)), 1.0
    if ob.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(ob.data)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        all_verts, all_faces = bm.verts, bm.faces
        verts = [all_verts[i] for i in rec.cap_verts if i < len(all_verts)]
        if rec.spec is not extrude.FACE:
            verts = [v for v in all_verts if v.select] or verts
    else:
        all_verts, all_faces = ob.data.vertices, ob.data.polygons
        verts = [all_verts[i] for i in rec.cap_verts if i < len(all_verts)]
        if rec.spec is not extrude.FACE and rec.sel is not None:
            verts = [all_verts[i] for i in rec.sel[0] if i < len(all_verts)] or verts
    faces = [all_faces[i] for i in rec.cap_faces if i < len(all_faces)]
    if not verts:
        return None
    centre = sum((v.co for v in verts), Vector()) / len(verts)
    n = sum((f.normal for f in faces), Vector()) if rec.spec is extrude.FACE else _pre_direction(rec).copy()
    n = n.normalized() if n.length > 1e-9 else Vector((0, 0, 1))
    mw = ob.matrix_world
    nw = mw.to_3x3() @ n
    k = nw.length or 1.0
    return mw @ centre, nw / k, k


def layout(region, anchor, scale, fields=extrude.FIELDS, gap=GAP):
    """Box geometry in region pixels: {"box", "title", "rows": [(field, x0, y0, x1, y1)]}."""
    w, h = WIDTH * scale, ROW_H * scale
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
    return rec, layout(context.region, a, _scale(), rec.spec.view_fields, (gap[0] + dx, gap[1] + dy))


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
        _text(rx0 + pad, ry0 + 4 * s, rec.spec.labels[field], HOT if hot else LIT if i == _state["hover"] else TEXT,
              size)
        v = value_text(rec, field)
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


# --- the extrude manipulator (3D gizmo) --------------------------------------------------

# Maya 2022 polyExtrudeFace manipulator (top face of a cube,
# local mode): lengths in "arrow units" (centre -> scale cube = 1): cone 0.64 -> 0.86 (radius 0.05), cube half 0.07,
# plane handles centred 0.5 / 0.5 between two axes (half 0.08, translucent with a full-colour rim), hollow centre square
# half 0.12 (20 px at an 83 px Z arrow) in #64dcff, screen facing. Axis colours = the kit Move manipulator's Maya
# colours (manipulator.MAYA_AXIS). Not drawn on the extrusion manipulator: Maya's cyan rotate ring and its world /
# local switch (the Transform Component manipulator has both, ``TURN`` below).
CONE_BASE, CONE_TIP, CONE_R = 0.64, 0.86, 0.05
CUBE_AT, CUBE_HALF = 1.0, 0.07
PLANE_AT, PLANE_HALF = 0.5, 0.08
PLANE_FILL = 0.25
CENTER_HALF = 0.12
CENTER_COLOUR = (0x64 / 255, 0xdc / 255, 1.0)
SCALE_PX = 100.0          # px of mouse travel along a scale handle that doubles the scale
# the extrude manipulator is drawn smaller than the Move one: Z arrow to cube 83 px at a ~27 deg persp elevation
# = ~93 px against the Move Y arrow's 108 px (manipulator.ARROW_PX)
SIZE = 0.86

# handle -> (role, axis or plane, the values it drives)
HANDLES = {
    "TX": ('ARROW', 'X', ("local_translate_x",)),
    "TY": ('ARROW', 'Y', ("local_translate_y",)),
    "TZ": ('ARROW', 'Z', ("local_translate_z",)),
    "SX": ('CUBE', 'X', ("local_scale_x",)),
    "SY": ('CUBE', 'Y', ("local_scale_y",)),
    "SZ": ('CUBE', 'Z', ("local_scale_z",)),
    "PXY": ('PLANE', 'XY', ("local_translate_x", "local_translate_y")),
    "PYZ": ('PLANE', 'YZ', ("local_translate_y", "local_translate_z")),
    "PXZ": ('PLANE', 'XZ', ("local_translate_x", "local_translate_z")),
    "S": ('CENTER', None, ("local_scale_x", "local_scale_y", "local_scale_z")),
}
AXIS_INDEX = {'X': 0, 'Y': 1, 'Z': 2}

# Transform Component of faces / edges, like Maya's: a light-blue ring past the scale cubes (radius 1.17 arrow units;
# drag = turn about the view axis by the angle the mouse sweeps round the centre), three rotate rings at the cube
# distance shown after a press on it (plane handles and centre square give way to them), and a world / local switch
# up and right of the manipulator (a kit-drawn globe). Polygon vertices have neither (Maya's polyMoveVertex has no
# Local Rotate).
VIEW_RING_R = 1.17
AXIS_RING_R = 1.0
RING_COLOUR = CENTER_COLOUR
RING_ACTIVE = manipulator.ACTIVE     # the ring while the rotate rings show
SPACE_AT = (1.39, 1.42)    # switch centre from the manipulator centre on screen (right, up), in arrow units
SPACE_R = 0.1              # switch radius, arrow units
CLICK_PX = 3.0             # a press on the ring that moves less than this (x UI scale) is a click
LOCAL_ROT = ("local_rotate_x", "local_rotate_y", "local_rotate_z")
WORLD_ROT = ("rotate_x", "rotate_y", "rotate_z")
TURN = {
    "VR": ('VIEW_RING', None, LOCAL_ROT),
    "RX": ('RING', 'X', ("local_rotate_x",)),
    "RY": ('RING', 'Y', ("local_rotate_y",)),
    "RZ": ('RING', 'Z', ("local_rotate_z",)),
}
# world axes: what each handle drives instead (the centre square moves in the view plane)
WORLD_FIELDS = {
    "TX": ("translate_x",), "TY": ("translate_y",), "TZ": ("translate_z",),
    "SX": ("scale_x",), "SY": ("scale_y",), "SZ": ("scale_z",),
    "PXY": ("translate_x", "translate_y"), "PYZ": ("translate_y", "translate_z"), "PXZ": ("translate_x", "translate_z"),
    "S": ("translate_x", "translate_y", "translate_z"),
    "VR": WORLD_ROT, "RX": ("rotate_x",), "RY": ("rotate_y",), "RZ": ("rotate_z",),
}


def turnable(rec):
    """True for a Transform Component of faces / edges: its manipulator has the ring and the world / local switch."""
    return rec is not None and rec.spec.full_manip and "local_rotate_x" in rec.spec.all_fields


def tc_state(rec):
    """{"world", "rings"} of the Transform Component manipulator of ``rec``: a display state kept on the record, not
    node values (nothing to undo); a new node starts on local axes without the rotate rings, like Maya."""
    state = getattr(rec, "manip_state", None)
    if state is None:
        state = rec.manip_state = {"world": False, "rings": False}
    return state


def flags(rec):
    """(world axes, rotate rings shown) of the manipulator of ``rec`` (always local, no rings when not turnable)."""
    if not turnable(rec):
        return False, False
    state = tc_state(rec)
    return state["world"], state["rings"]


def handle_entry(handle):
    return HANDLES.get(handle) or TURN.get(handle)


def handle_role(handle, world=False):
    """Drag role of ``handle``: the centre square moves freely ('FREE') on world axes."""
    role = handle_entry(handle)[0]
    return 'FREE' if role == 'CENTER' and world else role


def handle_fields(rec, handle, world=False, rings=False):
    """The values ``handle`` drives on ``rec`` (edge / vertex extrusion, bevel: only "TZ" = their arrow field;
    Transform Component: every handle of its fields; ``world`` / ``rings`` = the manipulator's state)."""
    entry = handle_entry(handle)
    if rec is None or entry is None:
        return ()
    if rec.spec is not extrude.FACE and not rec.spec.full_manip:
        return (rec.spec.arrow,) if handle == "TZ" and rec.spec.arrow is not None else ()
    role = entry[0]
    if not turnable(rec):
        if handle in TURN:
            return ()
        world = rings = False
    elif (role == 'RING' and not rings) or (rings and role in ('PLANE', 'CENTER')):
        return ()
    fields = WORLD_FIELDS[handle] if world else entry[2]
    # Transform Component of vertices: no Local Scale (Maya's polyMoveVertex has none)
    return fields if all(f in rec.spec.all_fields for f in fields) else ()


def manip_frame(ob, rec, world=False):
    """(world centre, 3x3 world unit axes (columns X, Y, Z), world lengths of one mesh unit along X / Y / Z) of the
    extrude manipulator: Z = the faces' normal, X / Y = polyExtrudeFace's local axes of that normal (world X projected
    into the face plane, extrude.face_axes); ``world``: the world axes (Transform Component switch). None when there
    is nothing to show."""
    frame = cap_frame(ob, rec)
    if frame is None:
        return None
    centre, nw, kz = frame
    if world:
        return centre, Matrix.Identity(3), (1.0, 1.0, 1.0)
    mw3 = ob.matrix_world.to_3x3()
    inv = mw3.inverted_safe()
    n_obj = (inv @ nw)
    n_obj = n_obj.normalized() if n_obj.length > 1e-12 else Vector((0, 0, 1))
    axes = extrude.mesh_axes(ob)
    x_obj, y_obj = extrude.face_axes(n_obj, axes["direction"], axes["fallback"])
    xw, yw = mw3 @ x_obj, mw3 @ y_obj
    kx, ky = xw.length or 1.0, yw.length or 1.0
    xw, yw = xw / kx, yw / ky
    return centre, Matrix((xw, yw, nw)).transposed(), (kx, ky, kz)


def unit_px(context):
    """Screen px of one arrow unit (wm_gizmo: scale_basis x gizmo_size x UI scale at use_draw_scale)."""
    return (manipulator.scale_basis(context) * SIZE * context.preferences.view.gizmo_size
            * (context.preferences.system.ui_scale or 1.0))


def handles_hit(context, region, rv3d, mouse, reach):
    """True when ``mouse`` (region px) is within ``reach`` px of a shown handle of the extrude manipulator: the
    pre-selection gizmo (operators/preselect.py, a 2D test_select that would win over these 3D-picked handles)
    declines there, like it does on the Move manipulator."""
    ob, rec = record(context)
    world, rings = flags(rec)
    frame = manip_frame(ob, rec, world) if rec is not None else None
    if frame is None:
        return False
    centre, axes, _k = frame
    c2 = view3d_utils.location_3d_to_region_2d(region, rv3d, centre)
    if c2 is None:
        return False
    w = view3d_utils.region_2d_to_location_3d(region, rv3d, c2 + Vector((1.0, 0.0)), centre) - centre
    unit = unit_px(context) * w.length          # world length of one arrow unit at the centre
    m = Vector(mouse)

    def at(vec):
        p = view3d_utils.location_3d_to_region_2d(region, rv3d, centre + vec * unit)
        return p if p is not None else c2

    if turnable(rec):
        at_px, r_px = space_button(context, c2)
        if (Vector(at_px) - m).length <= reach + r_px:
            return True
    for handle in (*HANDLES, *TURN):
        if not handle_fields(rec, handle, world, rings):
            continue
        role, data, _f = handle_entry(handle)
        if role == 'VIEW_RING':
            if abs((m - c2).length - VIEW_RING_R * unit_px(context)) <= reach:
                return True
        elif role == 'RING':
            ring = Matrix.Translation(centre) @ (axes @ manipulator._axis_rot(data)).to_4x4()                 @ Matrix.Scale(AXIS_RING_R * unit, 4)
            view_z = rv3d.view_matrix.inverted_safe().col[2].xyz.normalized()
            for arc in manipulator.front_arcs(ring, view_z):
                pts = [view3d_utils.location_3d_to_region_2d(region, rv3d, p) for p in arc]
                if any(p is not None and (p - m).length <= reach for p in pts):
                    return True
        elif role == 'ARROW':
            a, b = c2, at(axes.col[AXIS_INDEX[data]] * CONE_TIP)
            ab = b - a
            t = 0.0 if ab.length_squared < 1e-9 else max(0.0, min(1.0, (m - a).dot(ab) / ab.length_squared))
            if (a + ab * t - m).length <= reach:
                return True
        elif role == 'CUBE':
            if (at(axes.col[AXIS_INDEX[data]] * CUBE_AT) - m).length <= reach + CUBE_HALF * unit_px(context):
                return True
        elif role == 'PLANE':
            i, j = AXIS_INDEX[data[0]], AXIS_INDEX[data[1]]
            if (at((axes.col[i] + axes.col[j]) * PLANE_AT) - m).length <= reach + PLANE_HALF * unit_px(context):
                return True
        elif (c2 - m).length <= reach + CENTER_HALF * unit_px(context):
            return True
    return False


def handle_shapes(role):
    """(draw shapes [(type, verts, fill)], pick shape (type, verts)) of a handle in arrow units: arrows / cubes point
    along local +Z, plane handles lie in the local XY plane, the centre square faces +Z. Pure (tests run it headless)."""
    m = manipulator
    if role == 'ARROW':
        return ([('LINES', [(0, 0, 0), (0, 0, CONE_BASE)], False), ('TRIS', m._cone(CONE_BASE, CONE_TIP, CONE_R), False)],
                ('TRIS', m._bar(CENTER_HALF, CONE_BASE, 0.04) + m._cone(CONE_BASE, CONE_TIP, CONE_R * 1.6)))
    if role == 'CUBE':
        return ([('LINES', [(0, 0, CONE_TIP), (0, 0, CUBE_AT - CUBE_HALF)], False),
                 ('TRIS', m._box((0, 0, CUBE_AT), CUBE_HALF), False)],
                ('TRIS', m._box((0, 0, CUBE_AT), CUBE_HALF * 1.6)))
    if role == 'PLANE':
        rim = [(x + PLANE_AT, y + PLANE_AT, z) for x, y, z in m._square_outline(PLANE_HALF)]
        return ([('TRIS', m._square(PLANE_AT, PLANE_AT, PLANE_HALF), True), ('LINES', rim, False)],
                ('TRIS', m._square(PLANE_AT, PLANE_AT, PLANE_HALF * 1.3)))
    if role == 'CENTER':
        return ([('LINES', m._square_outline(CENTER_HALF), False)], ('TRIS', m._square(0, 0, CENTER_HALF * 1.3)))
    raise ValueError(role)


class ALLSET_GT_extrude_handle(bpy.types.Gizmo):
    """One handle of the Maya extrude manipulator (custom shapes; plane handles: translucent fill + rim)."""
    bl_idname = "ALLSET_GT_extrude_handle"
    __slots__ = ("draw_shapes", "pick_shape", "handle")

    def build(self, handle):
        self.handle = handle
        draw, pick = handle_shapes(HANDLES[handle][0])
        self.draw_shapes = [(self.new_custom_shape(t, v), fill) for t, v, fill in draw]
        self.pick_shape = self.new_custom_shape(*pick)

    def draw(self, context):
        colour = self.color_highlight if self.is_highlight else self.color
        alpha = self.alpha_highlight if self.is_highlight else self.alpha
        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(self.line_width)
        for (batch, shader), fill in getattr(self, "draw_shapes", ()):
            shader.bind()
            shader.uniform_float("color", (*colour, alpha * PLANE_FILL if fill else alpha))
            with gpu.matrix.push_pop():
                gpu.matrix.multiply_matrix(self.matrix_world)
                batch.draw(shader)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')

    def draw_select(self, context, select_id):
        sh = getattr(self, "pick_shape", None)
        if sh is not None:
            self.draw_custom_shape(sh, select_id=select_id)


def space_button(context, c2=None):
    """((x, y) region px, radius px) of the world / local switch of the shown Transform Component manipulator, or
    ((0, 0), -1) when there is none. ``c2`` = the manipulator centre on screen when the caller has it."""
    if c2 is None:
        ob, rec = record(context)
        frame = cap_frame(ob, rec) if turnable(rec) else None
        if frame is None or context.region_data is None:
            return (0.0, 0.0), -1.0
        c2 = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, frame[0])
        if c2 is None:
            return (0.0, 0.0), -1.0
    u = unit_px(context)
    return (c2[0] + SPACE_AT[0] * u, c2[1] + SPACE_AT[1] * u), SPACE_R * u


def globe_lines(x, y, r, n=32):
    """Line pairs of the switch's globe (outline, equator, one meridian) around region px (x, y). Pure."""
    out = []
    for rx in (r, r * 0.45):            # outline and meridian
        pts = [(x + rx * math.cos(2 * math.pi * i / n), y + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
        for i in range(n):
            out += [pts[i], pts[(i + 1) % n]]
    out += [(x - r, y), (x + r, y)]
    return out


class ALLSET_GT_tc_space(bpy.types.Gizmo):
    """The world / local switch of the Transform Component manipulator, drawn and picked in region pixels"""
    bl_idname = "ALLSET_GT_tc_space"

    def draw(self, context):
        (x, y), r = space_button(context)
        region = context.region
        if r <= 0 or region is None:
            return
        colour = self.color_highlight if self.is_highlight else self.color
        ortho = Matrix(((2 / region.width, 0, 0, -1), (0, 2 / region.height, 0, -1), (0, 0, -1, 0), (0, 0, 0, 1)))
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(ortho)
            gpu.state.blend_set('ALPHA')
            if flags(record(context)[1])[0]:        # world axes: the globe is filled
                fan = [(x, y)] + [(x + r * math.cos(2 * math.pi * i / 32), y + r * math.sin(2 * math.pi * i / 32))
                                  for i in range(33)]
                sh = gpu.shader.from_builtin('UNIFORM_COLOR')
                sh.uniform_float("color", (*colour[:3], 0.35))
                batch_for_shader(sh, 'TRI_FAN', {"pos": fan}).draw(sh)
            sh = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
            sh.bind()
            sh.uniform_float("viewportSize", (region.width, region.height))
            sh.uniform_float("lineWidth", 1.5 * (_scale() or 1.0))
            sh.uniform_float("color", (*colour[:3], 1.0))
            batch_for_shader(sh, 'LINES', {"pos": globe_lines(x, y, r)}).draw(sh)
            gpu.state.blend_set('NONE')

    def test_select(self, context, location):
        (x, y), r = space_button(context)
        if r <= 0:
            return -1
        return 0 if (Vector(location) - Vector((x, y))).length <= r + 3 * (_scale() or 1.0) else -1


def _no_tooltip(gz):
    """Maya manipulators have no tooltips; Blender would show the target operator's description (#98)."""
    if hasattr(gz, "use_tooltip"):
        gz.use_tooltip = False


class ALLSET_GGT_extrude(bpy.types.GizmoGroup):
    bl_idname = "ALLSET_GGT_extrude"
    bl_label = "Maya Extrude Manipulator"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and space.type == 'VIEW_3D' and space.show_gizmo and arrow_visible(context)

    def setup(self, context):
        self.handles = {}
        for handle in HANDLES:
            gz = self.gizmos.new(ALLSET_GT_extrude_handle.bl_idname)
            gz.build(handle)
            gz.target_set_operator(ALLSET_OT_extrude_drag.bl_idname).handle = handle
            gz.color_highlight = YELLOW
            gz.alpha = gz.alpha_highlight = 1.0
            gz.line_width = 1.5
            gz.use_draw_scale = True
            gz.use_draw_modal = True
            _no_tooltip(gz)
            self.handles[handle] = gz
        self.arrow = self.handles["TZ"]
        # Transform Component: made after the handles, so the rings win where they cross an arrow or a cube (the
        # first hit runs from the last made gizmo), the switch last
        for handle, (role, _data, _f) in TURN.items():
            gz = self.gizmos.new(manipulator.RING_GIZMO if role == 'RING' else "GIZMO_GT_dial_3d")
            if role == 'RING':
                gz.handle_role, gz.handle_axis = role, _data
            else:
                gz.draw_options = set()
            gz.target_set_operator(ALLSET_OT_extrude_drag.bl_idname).handle = handle
            gz.color_highlight = YELLOW
            gz.alpha = gz.alpha_highlight = 1.0
            gz.line_width = 1.5
            gz.use_draw_scale = True
            gz.use_draw_modal = True
            _no_tooltip(gz)
            self.handles[handle] = gz
        gz = self.gizmos.new(ALLSET_GT_tc_space.bl_idname)
        gz.target_set_operator(ALLSET_OT_tc_space.bl_idname)
        gz.color, gz.color_highlight = RING_COLOUR, YELLOW
        gz.alpha = gz.alpha_highlight = 1.0
        _no_tooltip(gz)
        self.space = gz

    def draw_prepare(self, context):
        ob, rec = record(context)
        if rec is None:
            return
        world, rings = flags(rec)
        frame = manip_frame(ob, rec, world)
        rv3d = context.region_data
        view = rv3d.view_rotation.to_matrix() if rv3d is not None else Matrix.Identity(3)
        colours = manipulator.axis_colours()
        s = manipulator.scale_basis(context) * SIZE
        self.space.hide = frame is None or not turnable(rec)
        for handle, gz in self.handles.items():
            gz.hide = frame is None or not handle_fields(rec, handle, world, rings)
            if gz.hide:
                continue
            centre, axes, _k = frame
            role, data, _fields = handle_entry(handle)
            gz.scale_basis = s
            if role in ('ARROW', 'CUBE', 'RING'):
                rot = axes @ manipulator._axis_rot(data)
                gz.color = colours[data]
                if role == 'RING':
                    gz.scale_basis = s * AXIS_RING_R
            elif role == 'PLANE':
                _c, normal, local = manipulator.PLANES[data]
                rot = axes @ local
                gz.color = colours[normal]
            elif role == 'VIEW_RING':
                rot = view
                gz.color = RING_ACTIVE if rings else RING_COLOUR
                gz.scale_basis = s * VIEW_RING_R
            else:
                rot = view
                gz.color = CENTER_COLOUR
            gz.matrix_basis = Matrix.Translation(centre) @ rot.to_4x4()


# --- operators ---------------------------------------------------------------------------------------

def _redraw(context):
    for area in context.screen.areas if context.screen else ():
        if area.type == 'VIEW_3D':
            area.tag_redraw()


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
        return context.window_manager.invoke_props_dialog(self, title=f"{rec.name}: {rec.spec.labels[field]}")

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


class ALLSET_OT_extrude_drag(bpy.types.Operator):
    """Drag a handle of the extrude manipulator (Maya polyExtrudeFace Local Translate / Local Scale; Local
    Translate Z of an edge extrusion, Length of a vertex extrusion)"""
    bl_idname = "allset.extrude_drag"
    bl_label = "Extrude Manipulator"
    bl_options = {'INTERNAL'}

    handle: StringProperty(default="TZ", options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        rec = target(context)[1]
        return rec is not None and rec.spec.arrow is not None and context.region_data is not None

    def _ray(self, context, event):
        region, rv3d = context.region, context.region_data
        co = (event.mouse_region_x, event.mouse_region_y)
        return (view3d_utils.region_2d_to_origin_3d(region, rv3d, co),
                view3d_utils.region_2d_to_vector_3d(region, rv3d, co))

    def _along(self, context, event, axis):
        o, d = self._ray(context, event)
        hit = geometry.intersect_line_line(self._c, self._c + axis, o, o + d)
        return None if hit is None else (hit[0] - self._c).dot(axis)

    def _on_plane(self, context, event, normal):
        o, d = self._ray(context, event)
        return geometry.intersect_line_plane(o, o + d, self._c, normal)

    def _screen_dir(self, context, axis):
        region, rv3d = context.region, context.region_data
        p0 = view3d_utils.location_3d_to_region_2d(region, rv3d, self._c)
        p1 = view3d_utils.location_3d_to_region_2d(region, rv3d, self._c + axis * 1e-3)
        if p0 is None or p1 is None or (p1 - p0).length < 1e-9:
            return Vector((1.0, 0.0))
        return (p1 - p0).normalized()

    def _ring_tangent(self, context, data):
        """Screen tangent (px per radian of turn) of the rotate ring of axis ``data`` at its point nearest the press."""
        region, rv3d = context.region, context.region_data
        c2 = view3d_utils.location_3d_to_region_2d(region, rv3d, self._c)
        if c2 is None:
            return Vector((0.0, 0.0))
        w = view3d_utils.region_2d_to_location_3d(region, rv3d, c2 + Vector((1.0, 0.0)), self._c) - self._c
        r = AXIS_RING_R * unit_px(context) * w.length
        rot = self._frame3 @ manipulator._axis_rot(data)       # columns: two ring directions, the axis

        def at(a):
            return view3d_utils.location_3d_to_region_2d(
                region, rv3d, self._c + (rot.col[0] * math.cos(a) + rot.col[1] * math.sin(a)) * r)
        best = None
        for i in range(72):
            a = 2 * math.pi * i / 72
            p = at(a)
            if p is not None and (best is None or (p - self._mouse0).length < best[0]):
                best = ((p - self._mouse0).length, a, p)
        if best is None:
            return Vector((0.0, 0.0))
        p1 = at(best[1] + 1e-3)
        return Vector((0.0, 0.0)) if p1 is None else (p1 - best[2]) / 1e-3

    def _sweep(self, event):
        """Angle (radians, counter-clockwise on screen) the mouse has swept round the manipulator centre so far."""
        v = Vector((event.mouse_region_x, event.mouse_region_y)) - self._c2
        if v.length > 1e-6 and self._prev.length > 1e-6:
            self._swept += math.atan2(self._prev.cross(v), self._prev.dot(v))
            self._prev = v
        return self._swept

    def invoke(self, context, event):
        ob, rec = target(context)
        world, rings = flags(rec)
        fields = handle_fields(rec, self.handle, world, rings)
        frame = manip_frame(ob, rec, world) if fields else None
        if frame is None:
            return {'CANCELLED'}
        self._ob, self._rec, self._fields = ob, rec, fields
        self._c, axes, self._k = frame
        self._frame3 = axes.copy()
        self._axes = [axes.col[i].copy() for i in range(3)]
        self._world = world
        self._role = handle_role(self.handle, world)
        data = handle_entry(self.handle)[1]
        self._idx = [AXIS_INDEX[a] for a in data] if data else []
        self._start = dict(extrude.DEFAULTS, **rec.params)
        self._unit = units.maya_unit(context.scene)
        self._mouse0 = Vector((event.mouse_region_x, event.mouse_region_y))
        self._moved = False
        rv3d = context.region_data
        if self._role in ('VIEW_RING', 'RING'):
            self._rot = WORLD_ROT if world else LOCAL_ROT
        if self._role == 'VIEW_RING':
            # about the view axis (toward the viewer), by the angle swept round the centre; a press shows the rings
            self._axis = (rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))).normalized()
            self._c2 = view3d_utils.location_3d_to_region_2d(context.region, rv3d, self._c) or self._mouse0.copy()
            self._prev, self._swept = self._mouse0 - self._c2, 0.0
            state = tc_state(rec)
            self._rings_before, state["rings"] = state["rings"], True
        elif self._role == 'RING':
            self._axis = self._axes[self._idx[0]]
            self._tan = self._ring_tangent(context, data)
        elif self._role == 'FREE':          # world centre square: free move in the view plane
            self._normal = (rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))).normalized()
            self._h0 = self._on_plane(context, event, self._normal)
        if self._role == 'ARROW':
            self._t0 = self._along(context, event, self._axes[self._idx[0]])
        elif self._role == 'PLANE':
            normal = self._axes[self._idx[0]].cross(self._axes[self._idx[1]])
            self._normal = normal
            self._h0 = self._on_plane(context, event, normal)
        elif self._role == 'CUBE':
            self._sdir = self._screen_dir(context, self._axes[self._idx[0]])
        self._last = {}
        self._button = event.type if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE'} else 'LEFTMOUSE'
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def values(self, context, event):
        """{field: value} for the mouse at ``event`` (the press values while the drag has no reading yet)."""
        start, out = self._start, {}
        if self._role == 'ARROW':
            i = self._idx[0]
            t = self._along(context, event, self._axes[i])
            if t is None or self._t0 is None:
                return dict(self._last)
            out[self._fields[0]] = round(start[self._fields[0]] + (t - self._t0) / self._k[i] / self._unit, 4)
        elif self._role in ('PLANE', 'FREE'):
            h = self._on_plane(context, event, self._normal)
            if h is None or self._h0 is None:
                return dict(self._last)
            d = h - self._h0
            for field, i in zip(self._fields, self._idx or range(3)):
                out[field] = round(start[field] + d.dot(self._axes[i]) / self._k[i] / self._unit, 4)
        elif self._role in ('VIEW_RING', 'RING'):
            if self._role == 'VIEW_RING':
                angle = self._sweep(event)
            else:       # along the ring's tangent at the pressed point
                mouse = Vector((event.mouse_region_x, event.mouse_region_y))
                n2 = self._tan.length_squared
                angle = 0.0 if n2 < 1e-9 else (mouse - self._mouse0).dot(self._tan) / n2
            axis = self._axis if self._world else self._frame3.transposed() @ self._axis
            out.update(zip(self._rot, move_component.turned([start[f] for f in self._rot], axis, angle)))
        else:
            mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            if self._role == 'CUBE':
                dist = (mouse - self._mouse0).dot(self._sdir)
            else:   # centre: Maya's uniform scale follows the horizontal drag
                dist = mouse.x - self._mouse0.x
            factor = 1.0 + dist / (SCALE_PX * (_scale() or 1.0))      # ui_scale reads 0 in background
            for field in self._fields:
                out[field] = round(start[field] * factor, 4)
        self._last = out
        return dict(out)

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            self._moved = self._moved or (mouse - self._mouse0).length > CLICK_PX * (_scale() or 1.0)
            params = dict(self._rec.params, **self.values(context, event))
            extrude.preview(self._ob, self._rec, params, self._unit)
            if self._fields[0] in self._rec.spec.view_fields:
                _state["hot"] = self._rec.spec.view_fields.index(self._fields[0])
            _redraw(context)
            return {'RUNNING_MODAL'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            extrude.preview(self._ob, self._rec, {k: self._start[k] for k in self._rec.params}, self._unit)
            self._rec.live = False
            _redraw(context)
            return {'CANCELLED'}
        if event.type == self._button and event.value == 'RELEASE':
            changes = self.values(context, event)
            if self._role in ('VIEW_RING', 'RING') and not self._moved:
                changes = {}        # a click on a ring changes no value
                if self._role == 'VIEW_RING':       # it shows / hides the rotate rings
                    tc_state(self._rec)["rings"] = not self._rings_before
            if changes:
                extrude.set_params(context, **changes)
            else:
                extrude.preview(self._ob, self._rec, {k: self._start[k] for k in self._rec.params}, self._unit)
                self._rec.live = False
            _redraw(context)
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


class ALLSET_OT_tc_space(bpy.types.Operator):
    """Put the Transform Component manipulator on world or local axes"""
    bl_idname = "allset.tc_space"
    bl_label = "World / Local Axes"
    bl_options = {'INTERNAL'}       # a display state of the manipulator: no undo step, like Maya

    @classmethod
    def poll(cls, context):
        return turnable(target(context)[1])

    def execute(self, context):
        _ob, rec = target(context)
        state = tc_state(rec)
        state["world"] = not state["world"]
        _redraw(context)
        return {'FINISHED'}


# --- Channel Box INPUTS ------------------------------------------------------------------------------

def cb_record(context, ob):
    """The lead object's last extrusion for Channel Box INPUTS (any selection), or None."""
    if ob is None:
        return None
    rec = (extrude.object_record(ob) if ob is not getattr(context, 'edit_object', None)
           else extrude.current(ob))
    if rec is not None:
        from ..operators import model_history
        selected = model_history.selected(ob)
        return (selected if selected is not None and not hasattr(selected, 'creation')
                and selected.history_id != rec.history_id else rec)
    return None


def _lead(context):
    return getattr(context, "edit_object", None) or getattr(context, "active_object", None)


def clamp(field, value):
    lo, hi = RANGES.get(field, (None, None))
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def _text_get(field):
    def get(_self):
        rec = cb_record(bpy.context, _lead(bpy.context))
        if rec is None or field not in rec.params:
            return ""
        from . import node_attributes
        node = node_attributes.for_record(bpy.context, _lead(bpy.context), rec)
        return node_attributes.format_value(node, field, bpy.context.scene)
    return get


def _text_set(field):
    def set_(_self, text):
        context = bpy.context
        rec = cb_record(context, _lead(context))
        if rec is None or field not in rec.params:
            return
        from . import channel_box
        bpy.ops.allset.model_channel_entry('EXEC_DEFAULT', True,
                                           key=channel_box.model_key(rec, field), text=text)
    return set_


class ALLSET_OT_model_channel_entry(bpy.types.Operator):
    """Apply typed modeling channels and compatible selected channels as one undo step"""
    bl_idname = 'allset.model_channel_entry'
    bl_label = 'Edit Node Attributes'
    bl_options = {'INTERNAL', 'UNDO'}
    key: StringProperty(options={'SKIP_SAVE'})
    text: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        from . import channel_box
        count = channel_box.apply_entry(self.key, self.text, context)
        return {'FINISHED'} if count else {'CANCELLED'}


class ALLSET_PG_history(bpy.types.PropertyGroup):
    __annotations__ = {f"{f}_text": StringProperty(name=next(s.labels[f] for s in extrude.SPECS.values()
                                                             if f in s.fields),
                                                   get=_text_get(f), set=_text_set(f), options={'SKIP_SAVE'})
                       for f in ALL_FIELDS}


HISTORY_TIP = "Blender keeps no edit-mode history: only the last operation can be changed here."
CHAIN_TIP = "Edit this recorded modeling node and replay its downstream operations."   # Persistent Modeling History


def draw_cb_node(layout, context, rec):
    """The polyExtrudeFace node in Channel Box INPUTS; the Blender notice is the node name's
    tooltip (no Blender sentences in Maya windows). Collapsed until its name is clicked, like Maya
   ."""
    from . import channel_box
    lines = channel_box.as_lines(layout)
    ob = channel_box.lead(context)
    from ..operators import model_history
    tip = CHAIN_TIP if model_history.enabled() else HISTORY_TIP
    _row, opened = channel_box.node_row(lines, ob, channel_box.history_node(rec.name), rec.name, tip=tip)
    if not opened:
        return
    hist = context.window_manager.allset_history
    from . import node_attributes
    node = node_attributes.for_record(context, ob, rec)
    for field in rec.spec.fields:
        row = lines.row()
        if row is None:
            continue
        split = row.split(factor=0.5, align=True)
        key = channel_box.model_key(rec, field)
        split.operator('allset.cb_select_channel', text=rec.spec.labels[field], emboss=False,
                       depress=key in channel_box.selected_channels(context)).key = key
        values = split.row()
        values.enabled = node_attributes.editable(node, field)
        values.prop(hist, f"{field}_text", text="")
    if rec.spec.kind == 'BRIDGE':
        row = lines.row()
        if row is not None:
            from . import bridge_editor
            bridge_editor.draw_controls(row.column(), node)


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
