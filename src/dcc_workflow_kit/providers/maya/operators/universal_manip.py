# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's Universal Manipulator (Ctrl+T): a bounding box that moves, rotates and scales the selection.

Like Maya:

- The box is the world bounding box of the selected objects (Transform space World), or the box in the lead
  object's own axes (Local).
- Corner boxes scale. A plain drag scales the one box axis that runs closest to the drag direction and keeps the
  opposite face where it is; Ctrl scales that axis about the box centre; Shift scales evenly and keeps the
  opposite corner where it is.
- The arrow pair at the middle of an edge rotates about that edge's direction: the drag along the arrows turns
  the selection, about its pivot (Rotate around Pivot) or about the box centre (Center).
- The centre arrows move along one axis, the centre circle moves in the view plane.
- The numbers beside three edges are the box's length along each axis; click one to type a new length (the box
  centre stays where it is).
In a mesh component mode the same box surrounds the selected vertices (edges / faces: their vertices) and the handles
move, rotate and scale those components; Rotate around Pivot turns them about the selection's centre point. (Maya's
own tool shows nothing for a component selection; the kit extends it so Ctrl+T scales components precisely too.)

Each drag runs Blender's own resize / rotate with the box frame and the fixed point (``center_override``): on
every mouse move from the state saved at the press, and once more on release with an undo step, so one Ctrl+Z
takes the drag back and Auto Key keys it like any other transform.

The maths below is free of ``bpy`` (tests call it headless); the drawing and the handles are ui/universal_manip.py.
"""

import math

import bmesh
import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty, PointerProperty
from mathutils import Matrix, Vector

TOOL = "allset.universal_manip"
DRAG_LOCK_PX = 4.0           # a corner drag picks its axis once the mouse moved this far
ROTATE_DEG_PER_PX = 0.2      # edge rotate: degrees per pixel of drag along the arrows
TINY = 1e-9
ZERO_BAND = 1e-5             # a scale factor this close to 0 is not applied
LAST = {}                    # the last drag (read by tests)


# --- box geometry (no bpy) -----------------------------------------------------------------------------------

def corner_signs(index):
    """(+1 / -1 per box axis) of corner ``index`` 0..7 (bit i set = the high side of axis i)."""
    return tuple(1 if index >> i & 1 else -1 for i in range(3))


def edge_spec(index):
    """(axis the edge runs along, {other axis: side sign}) of edge ``index`` 0..11."""
    axis = index // 4
    a1, a2 = (i for i in range(3) if i != axis)
    k = index % 4
    return axis, {a1: 1 if k & 1 else -1, a2: 1 if k & 2 else -1}


def edges_at_corner(index):
    """The three edge indices that meet at corner ``index``."""
    s = corner_signs(index)
    out = []
    for axis in range(3):
        a1, a2 = (i for i in range(3) if i != axis)
        out.append(axis * 4 + (1 if s[a1] > 0 else 0) + (2 if s[a2] > 0 else 0))
    return out


def centre(lo, hi):
    return Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2))


def corner_point(lo, hi, index):
    """Corner ``index`` in box coordinates."""
    s = corner_signs(index)
    return Vector(tuple(hi[i] if s[i] > 0 else lo[i] for i in range(3)))


def edge_mid(lo, hi, index):
    """Middle of edge ``index`` in box coordinates."""
    axis, sides = edge_spec(index)
    c = centre(lo, hi)
    for a, sgn in sides.items():
        c[a] = hi[a] if sgn > 0 else lo[a]
    c[axis] = (lo[axis] + hi[axis]) / 2
    return c


def pick_axis(drag, screen_axes):
    """The box axis whose screen direction runs closest to ``drag`` (px), or None. ``screen_axes`` = the screen
    vector of one world unit along each box axis; an axis seen end-on doesn't count."""
    dl = math.hypot(drag[0], drag[1])
    if dl < TINY:
        return None
    best, best_cos = None, -1.0
    for i, a in enumerate(screen_axes):
        if a is None:
            continue
        al = math.hypot(a[0], a[1])
        if al < 1e-3:
            continue
        cos = abs(drag[0] * a[0] + drag[1] * a[1]) / (dl * al)
        if cos > best_cos:
            best, best_cos = i, cos
    return best


def along(drag, screen_unit):
    """World units a drag of ``drag`` px moves along a direction whose one world unit spans ``screen_unit`` px."""
    sq = screen_unit[0] ** 2 + screen_unit[1] ** 2
    if sq < TINY:
        return 0.0
    return (drag[0] * screen_unit[0] + drag[1] * screen_unit[1]) / sq


def scale_plan(lo, hi, corner, mode, axis=None, offset=0.0, factor=None):
    """(factor per box axis, fixed point in box coordinates) of a corner drag.

    ``mode`` 'FACE' (plain drag: ``axis`` only, the opposite face stays), 'CENTER' (Ctrl: ``axis`` about the box
    centre), 'UNIFORM' (Shift: every axis by ``factor``, the opposite corner stays) or 'UNIFORM_CENTER' (Ctrl+Shift:
    every axis by ``factor`` about the box centre). ``offset`` = how far the dragged corner moved outward along
    ``axis`` (world units)."""
    s = corner_signs(corner)
    c = centre(lo, hi)
    if mode in ('UNIFORM', 'UNIFORM_CENTER'):
        f = 1.0 if factor is None else factor
        if mode == 'UNIFORM_CENTER':
            return (f, f, f), c
        opposite = Vector(tuple(lo[i] if s[i] > 0 else hi[i] for i in range(3)))
        return (f, f, f), opposite
    length = hi[axis] - lo[axis]
    fixed = c.copy()
    if mode == 'CENTER':
        half = length / 2
        f = (half + offset) / half if half > TINY else 1.0
    else:
        f = (length + offset) / length if length > TINY else 1.0
        fixed[axis] = lo[axis] if s[axis] > 0 else hi[axis]
    return tuple(f if i == axis else 1.0 for i in range(3)), fixed


def uniform_factor(mouse, corner_px, fixed_px):
    """Shift drag: how far along the screen line from the fixed point to the corner the mouse is (1 = at the
    corner)."""
    vx, vy = corner_px[0] - fixed_px[0], corner_px[1] - fixed_px[1]
    sq = vx * vx + vy * vy
    if sq < TINY:
        return 1.0
    return ((mouse[0] - fixed_px[0]) * vx + (mouse[1] - fixed_px[1]) * vy) / sq


def tangent(axis_vec, point, pivot, view_dir=None):
    """Direction the edge middle ``point`` moves in when the box turns about ``axis_vec`` through ``pivot``
    (right hand). A point on the axis takes the direction across the view."""
    t = axis_vec.cross(point - pivot)
    if t.length < 1e-6 and view_dir is not None:
        t = axis_vec.cross(view_dir)
    return t.normalized() if t.length > 1e-12 else Vector((0.0, 0.0, 0.0))


def rotate_angle(drag, tangent_px):
    """Edge rotate: radians for a drag of ``drag`` px, counted along the arrows' screen direction ``tangent_px``
    (positive = the way the edge middle moves for a positive turn). Arrows seen end-on count the horizontal
    drag."""
    tl = math.hypot(tangent_px[0], tangent_px[1]) if tangent_px is not None else 0.0
    d = drag[0] if tl < 1e-3 else (drag[0] * tangent_px[0] + drag[1] * tangent_px[1]) / tl
    return math.radians(d * ROTATE_DEG_PER_PX)


def size_factor(current, wanted):
    """Factor that makes a box length ``current`` into ``wanted`` (1 when the box has no length there)."""
    return wanted / current if current > TINY else 1.0


def skip_factor(f):
    return abs(f) < ZERO_BAND


# --- the box of the selection ---------------------------------------------------------------------------------

def settings(context):
    return context.scene.allset_universal_manip


def selected(context):
    return [ob for ob in context.selected_objects if ob.visible_get()]


def lead_object(context):
    if context.mode == 'EDIT_MESH':
        meshes = edit_meshes(context)
        active = context.view_layer.objects.active
        return active if active in meshes else (meshes[0] if meshes else None)
    sel = selected(context)
    active = context.view_layer.objects.active
    if active is not None and active in sel:
        return active
    return sel[-1] if sel else None


def edit_meshes(context):
    '''The meshes being edited (component mode).'''
    obs = getattr(context, "objects_in_mode_unique_data", None)
    if obs is None:
        ob = getattr(context, "edit_object", None)
        obs = [ob] if ob is not None else []
    return [ob for ob in obs if ob.type == 'MESH']


def component_points(context):
    '''World positions of the selected vertices of the meshes being edited.'''
    pts = []
    for ob in edit_meshes(context):
        mw = ob.matrix_world
        bm = bmesh.from_edit_mesh(ob.data)
        pts.extend(mw @ v.co for v in bm.verts if v.select)
    return pts


def ready(context):
    '''Something the box can surround: selected objects, or selected components of the meshes being edited.'''
    if context.mode == 'OBJECT':
        return bool(selected(context))
    if context.mode == 'EDIT_MESH':
        return any(ob.data.total_vert_sel for ob in edit_meshes(context))
    return False


def _object_points(ob):
    """World corners of the object's own bounding box (its evaluated geometry, like Maya's bounding box)."""
    mw = ob.matrix_world
    if ob.type == 'EMPTY':
        s = ob.empty_display_size
        return [mw @ Vector((x, y, z)) for x in (-s, s) for y in (-s, s) for z in (-s, s)]
    return [mw @ Vector(c) for c in ob.bound_box]


def frame_of(context, space):
    """3x3 box axes in world: identity (World) or the lead object's rotation (Local)."""
    if space == 'LOCAL':
        ob = lead_object(context)
        if ob is not None:
            m = ob.matrix_world.to_3x3()
            cols = [m.col[i].normalized() if m.col[i].length > TINY else Vector(v)
                    for i, v in enumerate(((1, 0, 0), (0, 1, 0), (0, 0, 1)))]
            r = Matrix((cols[0], cols[1], cols[2])).transposed()
            q = r.to_quaternion()               # orthonormal even for a sheared matrix
            return q.to_matrix()
    return Matrix.Identity(3)


def box_of(context, space=None):
    """(frame 3x3, lo, hi) of the selection's box in box coordinates (world = frame @ p), or None."""
    obs = selected(context)
    if not obs and context.mode != 'EDIT_MESH':
        return None
    if space is None:
        space = settings(context).space
    frame = frame_of(context, space)
    inv = frame.transposed()
    if context.mode == 'EDIT_MESH':
        pts = [inv @ p for p in component_points(context)]
        if not pts:
            return None
    else:
        pts = [inv @ p for ob in obs for p in _object_points(ob)]
    lo = Vector(tuple(min(p[i] for p in pts) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in pts) for i in range(3)))
    return frame, lo, hi


def rotate_pivot(context, frame, lo, hi):
    """World centre of an edge rotate: the lead object's pivot (Rotate around Pivot) or the box centre."""
    if settings(context).rotate_around == 'CENTER':
        return frame @ centre(lo, hi)
    if context.mode == 'EDIT_MESH':
        pts = component_points(context)           # the components' own pivot: their centre point
        return sum(pts, Vector()) / len(pts) if pts else frame @ centre(lo, hi)
    ob = lead_object(context)
    return ob.matrix_world.translation.copy() if ob is not None else frame @ centre(lo, hi)


# --- applying (Blender's transforms) -------------------------------------------------------------------------

def _orient(kwargs, frame):
    kwargs.update(orient_type='GLOBAL', orient_matrix_type='GLOBAL', orient_matrix=frame)


def apply_scale(factors, frame, fixed_world, final=False):
    mask = tuple(abs(f - 1.0) > 1e-12 for f in factors)
    if not any(mask):
        return {'CANCELLED'}
    kwargs = {"value": tuple(factors), "constraint_axis": (False,) * 3 if all(mask) else mask,
              "center_override": tuple(fixed_world), "snap": False, "use_proportional_edit": False}
    _orient(kwargs, frame)
    return _run(bpy.ops.transform.resize, kwargs, final)


def apply_rotate(axis, angle, frame, pivot_world, final=False):
    if abs(angle) < 1e-12:
        return {'CANCELLED'}
    kwargs = {"value": angle, "orient_axis": 'XYZ'[axis],
              "constraint_axis": tuple(i == axis for i in range(3)),
              "center_override": tuple(pivot_world), "snap": False, "use_proportional_edit": False}
    _orient(kwargs, frame)
    return _run(bpy.ops.transform.rotate, kwargs, final)


def _run(op, kwargs, final):
    from .manip_scale import _Quiet
    if final:
        return op('EXEC_DEFAULT', True, **kwargs)
    with _Quiet(bpy.context.scene.tool_settings):
        return op('EXEC_DEFAULT', **kwargs)


def save_state(context):
    '''What a drag changes, as it was at the press: object matrices, or the selected vertices' positions.'''
    if context.mode == 'EDIT_MESH':
        out = []
        for ob in edit_meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            bm.verts.ensure_lookup_table()
            out.append(("V", ob.name, [(v.index, v.co.copy()) for v in bm.verts if v.select]))
        return out
    return [(ob.name, ob.matrix_basis.copy()) for ob in context.selected_objects]


def restore(state):
    for item in state:
        if item[0] == "V":
            ob = bpy.data.objects.get(item[1])
            if ob is None or ob.mode != 'EDIT':
                continue
            bm = bmesh.from_edit_mesh(ob.data)
            bm.verts.ensure_lookup_table()
            changed = False
            for i, co in item[2]:
                if i < len(bm.verts) and bm.verts[i].co != co:
                    bm.verts[i].co = co
                    changed = True
            if changed:
                bm.normal_update()      # Preserve UVs (Blender's UV correction) projects through these normals
                bmesh.update_edit_mesh(ob.data)
            continue
        name, m = item
        ob = bpy.data.objects.get(name)
        if ob is not None and ob.matrix_basis != m:
            ob.matrix_basis = m


# --- screen helpers --------------------------------------------------------------------------------------------

def to_px(region, rv3d, world):
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    p = location_3d_to_region_2d(region, rv3d, world)
    return None if p is None else (p[0], p[1])


def screen_unit(region, rv3d, world, direction):
    """Screen px vector of one world unit along ``direction`` at ``world`` (a short step, scaled up)."""
    eps = max(rv3d.view_distance, 1e-6) * 1e-3
    a = to_px(region, rv3d, world)
    b = to_px(region, rv3d, world + direction * eps)
    if a is None or b is None:
        return None
    return ((b[0] - a[0]) / eps, (b[1] - a[1]) / eps)


def press_xy(event, region):
    """Region px of the press that started the drag (a gizmo drag starts once the mouse passed the threshold)."""
    x, y = event.mouse_x, event.mouse_y
    if event.value == 'CLICK_DRAG':
        x, y = getattr(event, "mouse_prev_press_x", x), getattr(event, "mouse_prev_press_y", y)
    return x - region.x, y - region.y


def _object_mode(context):
    return ready(context)


class _Drag:
    """Shared modal plumbing: Esc / RMB cancel, the release confirms with one undo step."""

    def _begin(self, context, event):
        region = context.region
        self._region_xy = (region.x, region.y)
        self._press = press_xy(event, region)
        self._state = save_state(context)
        self._result = None
        LAST.clear()
        context.window_manager.modal_handler_add(self)
        self._update(context, event)
        return {'RUNNING_MODAL'}

    def _mouse(self, event):
        return (event.mouse_x - self._region_xy[0], event.mouse_y - self._region_xy[1])

    def _end(self, context):
        if context.area is not None:
            context.area.header_text_set(None)
            context.area.tag_redraw()

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._update(context, event)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self._update(context, event)
            restore(self._state)
            if self._result is not None:
                try:
                    self._apply(self._result, final=True)
                except RuntimeError as ex:
                    print("allset: universal manipulator failed", ex)
            self._end(context)
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            restore(self._state)
            self._end(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _preview(self, context, result, text):
        if result == self._result:
            return
        self._result = result
        restore(self._state)
        if result is not None:
            try:
                self._apply(result, final=False)
            except RuntimeError as ex:
                print("allset: universal manipulator preview failed", ex)
        if context.area is not None:
            context.area.header_text_set(text)
            context.area.tag_redraw()


class ALLSET_OT_um_scale(_Drag, bpy.types.Operator):
    """Scale one box axis, the opposite face staying (Ctrl: about the centre; Shift: evenly)"""
    bl_idname = "allset.um_scale"
    bl_label = "Universal Manipulator Scale"
    # not REGISTER / UNDO: the final transform.resize call is the registered operator and the one undo step
    bl_options = {'INTERNAL', 'BLOCKING'}

    corner: IntProperty(min=0, max=7, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D' and _object_mode(context)

    def invoke(self, context, event):
        region, rv3d = context.region, context.region_data
        box = box_of(context)
        if region is None or rv3d is None or box is None or event.value == 'CLICK':
            return {'CANCELLED'}
        frame, lo, hi = box
        self._frame, self._lo, self._hi = frame, lo, hi
        s = corner_signs(self.corner)
        world = frame @ corner_point(lo, hi, self.corner)
        self._axes_px = [screen_unit(region, rv3d, world, frame.col[i] * s[i]) for i in range(3)]
        if event.shift:
            self._mode = 'UNIFORM_CENTER' if event.ctrl else 'UNIFORM'
            _f, fixed = scale_plan(lo, hi, self.corner, self._mode)
            self._corner_px = to_px(region, rv3d, world)
            self._fixed_px = to_px(region, rv3d, frame @ fixed)
            if self._corner_px is None or self._fixed_px is None:
                return {'CANCELLED'}
        else:
            self._mode = 'CENTER' if event.ctrl else 'FACE'
        self._axis = None
        return self._begin(context, event)

    def _update(self, context, event):
        m = self._mouse(event)
        drag = (m[0] - self._press[0], m[1] - self._press[1])
        if self._mode in ('UNIFORM', 'UNIFORM_CENTER'):
            mouse = (self._corner_px[0] + drag[0], self._corner_px[1] + drag[1])
            f = uniform_factor(mouse, self._corner_px, self._fixed_px)
            factors, fixed = scale_plan(self._lo, self._hi, self.corner, self._mode, factor=f)
        else:
            if self._axis is None:
                if math.hypot(*drag) < DRAG_LOCK_PX:
                    return
                self._axis = pick_axis(drag, self._axes_px)
                if self._axis is None:
                    return
            offset = along(drag, self._axes_px[self._axis])
            factors, fixed = scale_plan(self._lo, self._hi, self.corner, self._mode, self._axis, offset)
        if any(skip_factor(f) for f in factors):
            return
        LAST.update(kind='SCALE', mode=self._mode, axis=self._axis, factors=factors, fixed=tuple(fixed))
        text = "Scale: " + "  ".join(f"{f:.4f}" for f in factors)
        self._preview(context, (factors, tuple(self._frame @ fixed)), text)

    def _apply(self, result, final):
        factors, fixed_world = result
        return apply_scale(factors, self._frame, Vector(fixed_world), final)


class ALLSET_OT_um_rotate(_Drag, bpy.types.Operator):
    """Rotate about this edge's direction"""
    bl_idname = "allset.um_rotate"
    bl_label = "Universal Manipulator Rotate"
    bl_options = {'INTERNAL', 'BLOCKING'}

    edge: IntProperty(min=0, max=11, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D' and _object_mode(context)

    def invoke(self, context, event):
        region, rv3d = context.region, context.region_data
        box = box_of(context)
        if region is None or rv3d is None or box is None or event.value == 'CLICK':
            return {'CANCELLED'}
        frame, lo, hi = box
        self._frame = frame
        self._axis, _sides = edge_spec(self.edge)
        self._pivot = rotate_pivot(context, frame, lo, hi)
        mid = frame @ edge_mid(lo, hi, self.edge)
        view_dir = rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))
        t = tangent(frame.col[self._axis], mid, self._pivot, view_dir)
        self._tangent_px = screen_unit(region, rv3d, mid, t)
        return self._begin(context, event)

    def _update(self, context, event):
        m = self._mouse(event)
        drag = (m[0] - self._press[0], m[1] - self._press[1])
        angle = rotate_angle(drag, self._tangent_px)
        LAST.update(kind='ROTATE', axis=self._axis, angle=angle, pivot=tuple(self._pivot))
        self._preview(context, angle, f"Rotate: {math.degrees(angle):.2f}")

    def _apply(self, angle, final):
        return apply_rotate(self._axis, angle, self._frame, self._pivot, final)


NAVIGATION = {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN',
              'TRACKPADZOOM', 'LEFT_ALT', 'RIGHT_ALT', 'TIMER', 'TIMER_REPORT'}
EDIT = {}                    # the length being typed: axis index, text, whether the first key replaces it


def typed_value(text):
    """The number typed into a length field, or None."""
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return None


def edit_text(text, fresh, event_type, char):
    """(text, fresh) after one key of a length field: the first character typed replaces the shown length,
    Backspace takes the last character back (all of it while the shown length is untouched)."""
    if event_type == 'BACK_SPACE':
        return ("" if fresh else text[:-1]), False
    if char and (char.isdigit() or char in ".-,+"):
        return ((char if fresh else text + char), False)
    return text, fresh


class ALLSET_OT_um_size(bpy.types.Operator):
    """Type the box's length along this axis: the selection scales to it about the box centre"""
    bl_idname = "allset.um_size"
    bl_label = "Box Size"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    # hidden: the length is typed in the field on the box, not in Blender's redo panel
    axis: EnumProperty(items=[(a, a, "") for a in 'XYZ'], default='X', options={'SKIP_SAVE', 'HIDDEN'})
    length: FloatProperty(name="Length", precision=3, step=10, options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return _object_mode(context)

    def invoke(self, context, event):
        # a click on the length turns it into a field, like Maya: type a number, Enter applies, Esc cancels
        from .units import maya_unit
        box = box_of(context)
        if box is None or context.area is None:
            return {'CANCELLED'}
        _frame, lo, hi = box
        i = 'XYZ'.index(self.axis)
        self.length = (hi[i] - lo[i]) / maya_unit(context.scene)
        EDIT.clear()
        EDIT.update(axis=i, text=f"{self.length:.3f}", fresh=True)
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set("Box size: type a length, Enter to apply, Esc to cancel")
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _close(self, context):
        EDIT.clear()
        if context.area is not None:
            context.area.header_text_set(None)
            context.area.tag_redraw()

    def modal(self, context, event):
        if event.type in NAVIGATION:
            return {'PASS_THROUGH'}         # the view still tumbles / zooms; the field follows the box
        if event.value != 'PRESS':
            return {'RUNNING_MODAL'}
        if event.type in {'RET', 'NUMPAD_ENTER'}:
            value = typed_value(EDIT.get("text", ""))
            self._close(context)
            if value is None:
                return {'CANCELLED'}
            self.length = value
            return self.execute(context)
        if event.type in {'ESC', 'RIGHTMOUSE', 'LEFTMOUSE'}:
            self._close(context)
            return {'CANCELLED'} if event.type != 'LEFTMOUSE' else {'CANCELLED', 'PASS_THROUGH'}
        text, fresh = edit_text(EDIT.get("text", ""), EDIT.get("fresh", False), event.type, event.unicode)
        EDIT.update(text=text, fresh=fresh)
        if context.area is not None:
            context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def execute(self, context):
        from .units import maya_unit
        box = box_of(context)
        if box is None:
            return {'CANCELLED'}
        frame, lo, hi = box
        i = 'XYZ'.index(self.axis)
        f = size_factor(hi[i] - lo[i], self.length * maya_unit(context.scene))
        if skip_factor(f):
            self.report({'WARNING'}, "Length must not be 0")
            return {'CANCELLED'}
        factors = tuple(f if k == i else 1.0 for k in range(3))
        apply_scale(factors, frame, frame @ centre(lo, hi))
        return {'FINISHED'}


class ALLSET_OT_um_reset(bpy.types.Operator):
    """Put the Universal Manipulator's settings back (Transform space World, Rotate around Pivot)"""
    bl_idname = "allset.um_reset"
    bl_label = "Reset Tool"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        s = settings(context)
        for name in ("space", "rotate_around"):
            s.property_unset(name)
        return {'FINISHED'}


class ALLSET_PG_universal_manip(bpy.types.PropertyGroup):
    space: EnumProperty(
        name="Transform space",
        items=(('WORLD', "World", "The box is the selection's world bounding box"),
               ('LOCAL', "Local", "The box follows the lead object's own axes")),
        default='WORLD')
    rotate_around: EnumProperty(
        name="Rotate around",
        items=(('PIVOT', "Pivot", "An edge drag turns the selection about the lead object's pivot"),
               ('CENTER', "Center", "An edge drag turns the selection about the box centre")),
        default='PIVOT')


classes = (ALLSET_OT_um_scale, ALLSET_OT_um_rotate, ALLSET_OT_um_size, ALLSET_OT_um_reset)


def register_props():
    bpy.utils.register_class(ALLSET_PG_universal_manip)
    bpy.types.Scene.allset_universal_manip = PointerProperty(type=ALLSET_PG_universal_manip)


def unregister_props():
    del bpy.types.Scene.allset_universal_manip
    bpy.utils.unregister_class(ALLSET_PG_universal_manip)
