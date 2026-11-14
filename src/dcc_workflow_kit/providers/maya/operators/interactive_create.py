# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Create > Polygon Primitives > Interactive Creation (#225).

While the check item is on, a polygon primitive from the Create menu, the shelf or its option window is drawn in a
view instead of appearing at the origin, like Maya:

- a perspective view draws on the ground grid (z = 0, base edges along the world axes), an orthographic view on its
  own plane through the origin; the object keeps rotation 0 and its creation node's Axis points at the viewer;
- the first click-drag places the primitive and sizes its base: cube / plane corner to corner, the others a radius
  from the press point (a sphere's radius = the larger of the two ground offsets);
- the next click-drag sets the height: in a perspective view the height follows the pointer itself (the point of
  the vertical line through the base closest to the pointer), in an orthographic view the vertical drag distance;
  below the plane the shape hangs under it. A torus' second drag sets its section radius from the sideways drag;
- a click without dragging on a later step leaves that size at its default (a skipped height leaves the shape flat);
  a single click on the first step makes the default-size primitive centred on the clicked point;
- Shift: a cube / plane gets equal sides centred on the press point, a cylinder / cone a radius and height from the
  drag in one go (both sit on the plane), a sphere sits on the plane; Ctrl: a cube / plane grows from its centre;
  Ctrl+Shift: like Shift, centred on the plane;
- Enter completes a primitive whose remaining sizes aren't heights (torus section: its default); on a height step it
  waits for the drag; Esc drops an unfinished primitive and the tool stays (Esc with nothing started keeps it too);
- picking a primitive makes the Interactive Creation tool current (a workspace tool, ui/interactive_tool.py; its LMB
  press starts one primitive there). Exit On Completion (on by default) switches to the Select tool after one
  primitive; off, the tool stays and the next drag draws another one. Q / W / E / R or another tool leave it (an
  unfinished primitive is dropped); Y comes back to it.

The primitive is a regular kit primitive (Maya name, creation node in Channel Box INPUTS, lambert1), rebuilt while
dragging; each finished primitive is one undo step.
"""

import math

import bpy
from bpy.props import EnumProperty, StringProperty
from mathutils import Matrix, Vector

from .. import results

# kind -> its steps. The first step places the primitive; the others size it along the plane normal or in the plane.
STEPS = {
    'CUBE': ("rect", "height"),
    'PLANE': ("rect",),
    'SPHERE': ("radius",),
    'SOCCER_BALL': ("radius",),
    'PLATONIC': ("radius",),
    'TORUS': ("radius", "section"),
    'CYLINDER': ("radius", "height"),
    'CONE': ("radius", "height"),
    'PRISM': ("side", "height"),
    'PYRAMID': ("side",),
    'PIPE': ("radius", "height", "thickness"),
    'HELIX': ("width", "height", "coils", "radius"),
}
# Disc, Gear and the super shapes have no interactive creation in Maya: they are made at the origin at once.
# One-size primitives centred on the plane (Shift: sitting on it); the rest sit on the plane.
SOLIDS = {'SPHERE', 'SOCCER_BALL', 'PLATONIC', 'TORUS', 'PYRAMID'}
# Radius = the larger ground offset instead of the distance (pyramid: the corner distance)
MAX_RADIUS = {'SPHERE', 'PYRAMID'}
# Shift sets radius and height together (radius = larger offset x sqrt 2, height = 2 x larger offset)
SHIFT_HEIGHT = {'CYLINDER', 'CONE', 'PRISM', 'PIPE', 'HELIX'}
# Shift: radius = larger offset x sqrt 2, centre lifted by the larger offset (Ctrl+Shift: centred)
SHIFT_LIFT = {'PLATONIC', 'SOCCER_BALL'}
HEIGHT_ATTR = {'PRISM': "length"}
HEIGHT_FACTOR = {'PIPE': 2.0}   # the pipe node's Height is twice the drawn height
SECTION_PX = 0.1        # torus section radius per px dragged sideways (from its default)
SECTION_MIN = 0.01
# later steps sized by a sideways drag: default + PX_STEP x px, at least the minimum
PX_STEP = 0.1
PX_MIN = {"thickness": 0.01, "coils": 0.5, "radius": 0.01, "section": SECTION_MIN}
FLAT = 1e-4             # smallest size while drawing (a zero size has no faces to build)
# size attributes a single click sets to the option-window / default value
SIZES = ("width", "height", "depth", "radius", "sideLength", "length", "sectionRadius", "thickness", "coils")
STATUS = ("Interactive Creation: drag to place and size, drag again for the height, click to skip. "
          "Shift equal sides, Ctrl from the centre")
TOOL = "allset.interactive_create_tool"
SELECT_TOOL = "builtin.select_box"
# What the tool draws next: kind, option-window values (Maya node attributes), and a counter each pick raises
CURRENT = {"kind": 'CUBE', "values": {}, "pick": 0}


def wanted(context, kind):
    """True when Interactive Creation is on and ``kind`` can be drawn in a window."""
    from .. import preferences
    if kind not in STEPS or bpy.app.background or getattr(context, "window", None) is None:
        return False
    try:
        return bool(preferences.get(context).interactive_creation)
    except (KeyError, AttributeError):
        return False


def pick(kind, overrides=None):
    """Remember the primitive the tool draws next."""
    CURRENT.update(kind=kind, values=dict(overrides or {}), pick=CURRENT["pick"] + 1)


def start(context, kind, overrides=None):
    """Make the Interactive Creation tool current for ``kind`` with option-window values ``overrides``.
    False when the tool can't be set (the caller then creates the primitive at the origin)."""
    pick(kind, overrides)
    if context.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            return False
    try:
        bpy.ops.wm.tool_set_by_id(name=TOOL, space_type='VIEW_3D')
    except (RuntimeError, TypeError, ValueError):
        return False
    return tool_active(context)


def tool_active(context):
    """True when the Interactive Creation tool is the current tool of the mode."""
    try:
        tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    except (AttributeError, TypeError, RuntimeError):
        return False
    return tool is not None and tool.idname == TOOL


# --- geometry (no bpy) ----------------------------------------------------------------------------------------

class Plane:
    """The drawing plane: ``origin``, unit ``normal`` and in-plane axes ``u`` / ``v`` (u x v = normal)."""

    def __init__(self, origin, normal, u):
        self.origin = Vector(origin)
        self.normal = Vector(normal).normalized()
        self.u = Vector(u).normalized()
        self.v = self.normal.cross(self.u).normalized()

    def hit(self, ray_origin, ray_dir, forward_only=True):
        """Where the ray meets the plane, or None (parallel / behind the eye)."""
        d = Vector(ray_dir)
        den = d.dot(self.normal)
        if abs(den) < 1e-8:
            return None
        t = (self.origin - Vector(ray_origin)).dot(self.normal) / den
        if forward_only and t < 0:
            return None
        return Vector(ray_origin) + d * t

    def coords(self, p):
        q = Vector(p) - self.origin
        return q.dot(self.u), q.dot(self.v)

    def point(self, a, b):
        return self.origin + self.u * a + self.v * b

    def rotation(self):
        """Object rotation: local X = u, Y = v, Z = normal (Maya's up axis)."""
        return Matrix((self.u, self.v, self.normal)).transposed().to_4x4()


def world_axis(vec):
    """The signed world axis closest to ``vec``."""
    i = max(range(3), key=lambda j: abs(vec[j]))
    out = Vector((0.0, 0.0, 0.0))
    out[i] = 1.0 if vec[i] >= 0 else -1.0
    return out


def maya_axis(normal):
    """A Blender world direction as a Maya Y-up direction (the creation node's Axis): (x, y, z) -> (x, z, -y)."""
    return (normal[0], normal[2], -normal[1])


def axis_param(center, normal, ray_origin, ray_dir):
    """Parameter t of the point on the line ``center + normal t`` closest to the ray, or None when they're parallel."""
    n, d = Vector(normal), Vector(ray_dir).normalized()
    w = Vector(center) - Vector(ray_origin)
    b = n.dot(d)
    den = 1.0 - b * b
    if den < 1e-4:
        return None
    return (b * d.dot(w) - n.dot(w)) / den


def rect(a0, b0, a1, b1, centred=False, square=False):
    """(centre a, centre b, side a, side b) of a base dragged from (a0, b0) to (a1, b1) in plane coordinates:
    corner to corner; ``centred`` (Ctrl) = centred on the press, sides 2|da| x 2|db|; ``square`` (Shift) = equal
    sides 2 x max(|da|, |db|) centred on the press."""
    da, db = a1 - a0, b1 - b0
    if square:
        s = 2 * max(abs(da), abs(db))
        return a0, b0, s, s
    if centred:
        return a0, b0, 2 * abs(da), 2 * abs(db)
    return a0 + da / 2, b0 + db / 2, abs(da), abs(db)


def radius(kind, da, db):
    """First-step radius from the ground offset (da, db)."""
    if kind in MAX_RADIUS:
        return max(abs(da), abs(db))
    return math.hypot(da, db)


def side_for_radius(r, sides):
    """Side length of a regular ``sides``-gon with circumradius ``r``."""
    return 2.0 * r * math.sin(math.pi / sides)


def first_values(kind, size, sides=4, width_along_a=True):
    """Node attributes the first step sets from its size (Maya units): (side a, side b) for "rect", else a radius."""
    step = STEPS[kind][0]
    if step == "rect":
        a, b = size
        w, dp = (a, b) if width_along_a else (b, a)
        return {"width": w, ("height" if kind == 'PLANE' else "depth"): dp}
    if step == "side":
        return {"sideLength": side_for_radius(size, sides)}
    if step == "width":
        return {"width": 2.0 * size}
    return {"radius": size}


def step_attr(kind, step):
    return {"height": HEIGHT_ATTR.get(kind, "height"), "section": "sectionRadius", "thickness": "thickness",
            "coils": "coils", "radius": "radius"}.get(step)


def height_value(kind, h):
    """The node attribute value for a drawn height ``h`` (Maya units, positive)."""
    return h * HEIGHT_FACTOR.get(kind, 1.0)


def px_value(step, default, px):
    """Pipe thickness, helix coils / tube radius, torus section after a sideways drag of ``px`` logical pixels."""
    return max(default + PX_STEP * px, PX_MIN.get(step, 0.0))


def section_radius(default, px):
    """Torus section radius after a sideways drag of ``px`` (logical) pixels."""
    return max(default + SECTION_PX * px, SECTION_MIN)


def placement(base_point, normal, zmin, zmax, mode, lift=0.0):
    """Object location so the shape (extent [zmin, zmax] along ``normal``) sits on the plane: "base" = bottom on the
    plane, "top" = top on it (a height dragged below), "centre" = centred on it, "lift" = centre ``lift`` above it."""
    n = Vector(normal)
    off = {"base": -zmin, "top": -zmax, "lift": lift - (zmin + zmax) / 2}.get(mode, -(zmin + zmax) / 2)
    return Vector(base_point) + n * off


# --- the tool --------------------------------------------------------------------------------------------------

def drawing_plane(rv3d):
    """Ground (z = 0, X / Y) in a perspective view, else the view plane through the origin, snapped to the world axes
    (normal towards the viewer)."""
    if rv3d.is_perspective:
        return Plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    rot = rv3d.view_rotation
    n = world_axis(rot @ Vector((0.0, 0.0, 1.0)))
    u = world_axis(rot @ Vector((1.0, 0.0, 0.0)))
    if abs(u.dot(n)) > 0.5:          # a view looking down a diagonal: any axis across the normal
        u = world_axis(rot @ Vector((0.0, 1.0, 0.0))).cross(n)
    return Plane((0.0, 0.0, 0.0), n, u)


def _ray(region, rv3d, coord):
    from bpy_extras import view3d_utils
    return (view3d_utils.region_2d_to_origin_3d(region, rv3d, coord),
            view3d_utils.region_2d_to_vector_3d(region, rv3d, coord))


def _px_size(region, rv3d, point):
    """World length of one pixel at ``point`` (screen-vertical)."""
    from bpy_extras import view3d_utils
    c = view3d_utils.location_3d_to_region_2d(region, rv3d, point)
    if c is None:
        return 0.0
    a = view3d_utils.region_2d_to_location_3d(region, rv3d, c, point)
    b = view3d_utils.region_2d_to_location_3d(region, rv3d, (c[0], c[1] + 1.0), point)
    return (b - a).length


def _has_axis(node_type):
    from . import prim_shapes
    return "axisX" in prim_shapes.defaults(node_type)


def _width_along_u(axis, plane):
    """Does the node's width (Maya X after its Axis turn) run along the plane's u?"""
    from . import prim_history, prim_shapes
    m = prim_shapes._rot_to(axis)
    w = prim_shapes._apply(m, (1.0, 0.0, 0.0)) if m is not None else (1.0, 0.0, 0.0)
    wb = Vector(prim_history.to_blender(w, 1.0))
    return abs(wb.dot(plane.u)) >= abs(wb.dot(plane.v))


class ALLSET_OT_interactive_create(bpy.types.Operator):
    """Maya Interactive Creation: drag in a view to place and size a polygon primitive (the tool's LMB press)"""
    bl_idname = "allset.interactive_create"
    bl_label = "Interactive Creation"
    bl_options = set()          # each finished primitive pushes its own undo step

    kind: EnumProperty(name="Kind", items=[(k, k.replace("_", " ").title(), "") for k in STEPS], options={'SKIP_SAVE'})
    values: StringProperty(options={'SKIP_SAVE', 'HIDDEN'}, description="JSON: option-window node attributes")

    @classmethod
    def poll(cls, context):
        from ..ui import toolbox
        area, region = context.area, context.region
        return (context.window is not None and area is not None and area.type == 'VIEW_3D' and region is not None
                and region.type == 'WINDOW' and not toolbox.is_toolbox(context.space_data))

    def invoke(self, context, event):
        """A press in a view: start one primitive there and follow it until it's finished, dropped or left."""
        import json
        if self.properties.is_property_set("kind"):
            try:
                self._over = dict(json.loads(self.values)) if self.values else {}
            except (ValueError, TypeError):
                self._over = {}
        else:                                   # the tool's press: the primitive picked last
            self.kind = CURRENT["kind"]
            self._over = dict(CURRENT["values"])
        self._pick = CURRENT["pick"]
        self._reset()
        result = self._press(context, event)
        if self._ob is None:                    # outside a view / the ray misses the drawing plane
            return {'PASS_THROUGH'} if 'PASS_THROUGH' in result else {'CANCELLED'}
        from .. import command_line
        command_line.MODAL_HELP[self.bl_idname] = STATUS        # the Help Line while a primitive is drawn
        context.workspace.status_text_set(STATUS)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    # state of one primitive
    def _reset(self):
        self._ob = None          # the primitive being drawn
        self._step = 0           # index into STEPS[kind]
        self._down = None        # (x, y) of the press of the current drag
        self._moved = False
        self._area = self._region = None
        self._plane = None
        self._start = None       # plane coords of the first press
        self._base = None        # base point on the plane
        self._mode = "centre" if self.kind in SOLIDS else "base"
        self._lift = 0.0
        self._vals = {}
        self._history = True
        self._done_early = False  # Shift: the first drag set every size
        self._upright = False     # a single click: rotation 0 whatever the view

    def _end(self, context):
        context.workspace.status_text_set(None)

    def _default(self, attr):
        """The option-window value, else the default value, of ``attr``."""
        from . import prim_history, prim_shapes
        if attr in self._over:
            return self._over[attr]
        node_type = prim_history.KIND_NODES[self.kind][0]
        return prim_shapes.defaults(node_type).get(attr)

    def _superseded(self, context):
        """Another tool or primitive was picked (Maya: picking a tool leaves the current one)."""
        if CURRENT["pick"] != self._pick or not tool_active(context):
            return True
        me = self.as_pointer()
        for op in context.window.modal_operators:
            if op.as_pointer() == me:
                return False                 # this one comes first: nothing newer
            if op.bl_idname == self.bl_idname or op.bl_idname.endswith("_TOOL"):
                return True
        return False

    # --- events
    def modal(self, context, event):
        if context.window is not None and self._superseded(context):
            self._drop()
            self._end(context)
            return {'CANCELLED'}
        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            if self._ob is None:
                self._end(context)
                return {'CANCELLED'}
            if STEPS[self.kind][self._step] == "height" and self._step > 0:
                return {'RUNNING_MODAL'}             # a height only comes from its drag
            return self._complete(context)
        if event.type == 'ESC' and event.value == 'PRESS':
            self._drop()                              # the unfinished primitive goes, the tool stays
            self._end(context)
            return {'CANCELLED'}
        if event.type in {'Q', 'W', 'E', 'R'} and event.value == 'PRESS' \
                and not (event.alt or event.ctrl or event.shift or event.oskey):
            self._drop()                              # leaving the tool drops an unfinished primitive
            self._end(context)                        # the key goes on to pick its tool
            return {'CANCELLED', 'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE' and not event.alt:
            if event.value == 'PRESS':
                return self._press(context, event)
            if event.value == 'RELEASE' and self._down is not None:
                return self._release(context, event)
        if event.type == 'MOUSEMOVE' and self._down is not None:
            self._drag(context, event)
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    def _press(self, context, event):
        from .joints import view_under
        if self._ob is None:
            hit = view_under(context.window, event.mouse_x, event.mouse_y)
            if hit is None:
                return {'PASS_THROUGH'}
            area, region = hit
            coord = (event.mouse_x - region.x, event.mouse_y - region.y)
            plane = drawing_plane(region.data)
            p = plane.hit(*_ray(region, region.data, coord), forward_only=region.data.is_perspective)
            if p is None:
                return {'RUNNING_MODAL'}
            self._area, self._region, self._plane = area, region, plane
            self._start = plane.coords(p)
            self._base = p
            self._new(context)
        elif self._region is None or view_under(context.window, event.mouse_x, event.mouse_y) is None:
            return {'PASS_THROUGH'}            # a later step is dragged in a view; clicks elsewhere go on
        self._down = (event.mouse_x, event.mouse_y)
        self._moved = False
        return {'RUNNING_MODAL'}

    def _drag(self, context, event):
        dx, dy = event.mouse_x - self._down[0], event.mouse_y - self._down[1]
        thr = context.preferences.inputs.drag_threshold_mouse * (context.preferences.system.ui_scale or 1.0)
        if not self._moved and math.hypot(dx, dy) < max(thr, 3):
            return
        self._moved = True
        self._apply(context, event)

    def _release(self, context, event):
        self._down = None
        steps = STEPS[self.kind]
        if self._step == 0 and not self._moved:
            return self._complete(context, default=True)        # single click: default size, centred there
        if self._step > 0 and not self._moved:
            self._skip(context, steps[self._step])
        self._step += 1
        while self._step < len(steps) and self._done_early and steps[self._step] == "height":
            self._step += 1                                     # Shift already set the height
        if self._step >= len(steps):
            return self._complete(context)
        if steps[self._step] == "height":
            self._set(context, {step_attr(self.kind, "height"): FLAT})   # the height starts flat
        return {'RUNNING_MODAL'}

    # --- the primitive
    def _new(self, context):
        from . import create, material, prim_history
        node_type = prim_history.KIND_NODES[self.kind][0]
        self._axis_node = _has_axis(node_type)
        with context.temp_override(window=context.window, area=self._area, region=self._region):
            if context.mode != 'OBJECT' and context.active_object is not None:
                bpy.ops.object.mode_set(mode='OBJECT')
            vals = dict(self._over)
            uvs = bool(vals.pop("createUVs", True))
            if self._axis_node:          # the node turns towards the viewer, the object keeps rotation 0
                ax = maya_axis(self._plane.normal)
                vals.update(axisX=ax[0], axisY=ax[1], axisZ=ax[2])
                self._width_u = _width_along_u(ax, self._plane)
            else:
                self._width_u = True
            vals.update(first_values(self.kind, (FLAT, FLAT) if STEPS[self.kind][0] == "rect" else FLAT,
                                     int(vals.get("numberOfSides", 4 if self.kind == 'PYRAMID' else 3))))
            if "height" in STEPS[self.kind]:
                vals[step_attr(self.kind, "height")] = FLAT
            history = prim_history.history_on(context)
            wm = context.window_manager
            live = hasattr(wm, "allset_construction_history")
            if live:
                wm.allset_construction_history = True     # rebuilt live from its node; dropped at the end if off
            try:
                ob = prim_history.create_object(context, self.kind, vals, create._maya_naming(context), create_uvs=uvs)
            finally:
                if live:
                    wm.allset_construction_history = history
            material.give_default(ob)
        self._ob, self._history = ob, history
        self._vals = prim_history.attrs(prim_history.owner_of(ob))
        self._place()

    def _set(self, context, changes):
        from . import prim_history
        if self._ob is None or not changes:
            return
        vals = prim_history.rebuild(context, self._ob, changes)
        if vals is not None:
            self._vals = vals
        self._place()

    def _rotation(self):
        return Matrix.Identity(4) if (self._axis_node or self._upright) else self._plane.rotation()

    def _place(self):
        ob, n = self._ob, self._plane.normal
        rot = self._rotation()
        scale = Matrix.Diagonal(ob.scale.to_4d())
        zs = [(rot @ scale @ v.co.to_4d()).to_3d().dot(n) for v in ob.data.vertices] or [0.0]
        ob.location = placement(self._base, n, min(zs), max(zs), self._mode, self._lift)
        ob.rotation_euler = rot.to_euler(ob.rotation_mode if len(ob.rotation_mode) == 3 else 'XYZ')
        if self._area is not None:
            self._area.tag_redraw()

    def _axis_t(self, event):
        region = self._region
        coord = (event.mouse_x - region.x, event.mouse_y - region.y)
        return axis_param(self._base, self._plane.normal, *_ray(region, region.data, coord))

    def _apply(self, context, event):
        from . import units
        k = units.maya_unit(context.scene) or 1.0
        region, plane, kind = self._region, self._plane, self.kind
        step = STEPS[kind][self._step]
        if self._step == 0:
            self._first(context, event, k)
            return
        attr = step_attr(kind, step)
        if step == "height":
            t = self._axis_t(event) if region.data.is_perspective else None
            if t is None:      # orthographic: the vertical drag distance
                t = (event.mouse_y - self._down[1]) * _px_size(region, region.data, self._base)
            h = t / k
            changes = {attr: height_value(kind, max(abs(h), FLAT))}
            if kind == 'HELIX':
                self._mode, self._lift = "lift", t / 2       # the coil path runs from the plane to the height
            elif kind == 'CONE' and self._axis_node:
                # dragged below the plane: the cone turns over, base on the plane, apex down
                ax = maya_axis(-plane.normal if h < 0 else plane.normal)
                changes.update(axisX=ax[0], axisY=ax[1], axisZ=ax[2])
                self._mode = "top" if h < 0 else "base"
            elif self._mode != "centre":
                self._mode = "top" if h < 0 else "base"     # dragged below the plane: the shape hangs under it
            self._set(context, changes)
        else:
            px = (event.mouse_x - self._down[0]) / (context.preferences.system.ui_scale or 1.0)
            self._set(context, {attr: px_value(step, self._default(attr), px)})

    def _first(self, context, event, k):
        """The first drag: location and base size, with Maya's Shift / Ctrl rules."""
        region, plane, kind = self._region, self._plane, self.kind
        coord = (event.mouse_x - region.x, event.mouse_y - region.y)
        p = plane.hit(*_ray(region, region.data, coord), forward_only=region.data.is_perspective)
        if p is None:
            return
        a, b = plane.coords(p)
        a0, b0 = self._start
        da, db = a - a0, b - b0
        shift, ctrl = event.shift, event.ctrl
        big = max(abs(da), abs(db))
        sides = int(self._vals.get("numberOfSides", 3))
        changes = {}
        self._lift = 0.0
        self._done_early = False
        if STEPS[kind][0] == "rect":
            ca, cb, sa, sb = rect(a0, b0, a, b, centred=ctrl, square=shift)
            self._base = plane.point(ca, cb)
            changes = first_values(kind, (sa / k, sb / k), width_along_a=self._width_u)
            if shift and kind == 'CUBE':
                changes["height"] = sa / k                    # equal sides: one drag
                self._done_early = True
            self._mode = "centre" if (shift and ctrl and kind == 'CUBE') else "base"
        else:
            self._base = plane.point(a0, b0)
            if shift and kind in SHIFT_HEIGHT | SHIFT_LIFT | {'TORUS'}:
                r = big * math.sqrt(2.0)
            else:
                r = radius(kind, da, db)
            changes = first_values(kind, r / k, sides)
            if shift and kind in SHIFT_HEIGHT:
                changes[step_attr(kind, "height")] = height_value(kind, 2 * big / k)
                self._done_early = True
            if kind == 'TORUS' and shift and not ctrl:
                self._mode, self._lift = "lift", self._default("sectionRadius") * k   # raised by the default section
            elif kind in SHIFT_LIFT and shift:
                self._mode, self._lift = ("centre", 0.0) if ctrl else ("lift", big)
            elif kind == 'HELIX' and shift and not ctrl:
                self._mode, self._lift = "lift", big          # the coil path from the plane up
            elif kind in SOLIDS:
                self._mode = "base" if (shift and not ctrl) else "centre"
            else:
                self._mode = "centre" if (shift and ctrl) else "base"
        self._set(context, changes)

    def _skip(self, context, step):
        """A click without a drag on a later step: the size stays at its default; a skipped height leaves the shape
        flat (scale 0 along the plane normal)."""
        attr = step_attr(self.kind, step)
        if attr is None:
            return
        self._set(context, {attr: self._default(attr)})
        if step == "height":
            self._flatten()

    def _flatten(self):
        ob = self._ob
        rot = self._rotation().to_3x3()
        local_n = rot.inverted() @ self._plane.normal
        i = max(range(3), key=lambda j: abs(local_n[j]))
        s = list(ob.scale)
        s[i] = 0.0
        ob.scale = s
        self._mode = "base"
        self._place()

    def _complete(self, context, default=False):
        """Finish the primitive: the steps not done yet keep their default sizes; ``default`` (a single click) = every
        size at its default, centred on the click."""
        from . import prim_history
        ob = self._ob
        steps = STEPS[self.kind]
        if default:
            changes = {a: self._default(a) for a in SIZES if a in self._vals}
            if self._axis_node:            # a click makes the primitive upright (Maya Y up), not facing the view
                changes.update(axisX=0.0, axisY=1.0, axisZ=0.0)
            self._upright = True
            self._set(context, changes)
            self._mode = "centre"
            self._place()
        else:
            first = self._step + (1 if self._down is not None else 0)    # a step being dragged keeps its value
            for later in steps[max(first, 1):]:
                if later == "height" and self._done_early:
                    continue
                attr = step_attr(self.kind, later)
                if attr is not None:
                    self._set(context, {attr: self._default(attr)})
        if not self._history:
            prim_history.drop(ob)                   # Construction History off: no creation node (Maya -ch 0)
        name = ob.name
        self._reset()
        with context.temp_override(window=context.window):
            bpy.ops.ed.undo_push(message=f"Create {name}")
        results.result(self, f"Created {name}")
        from .. import preferences
        try:
            exit_now = preferences.get(context).exit_on_completion
        except (KeyError, AttributeError):
            exit_now = True
        self._end(context)
        if exit_now:                                  # Maya: the Select tool after one primitive
            try:
                bpy.ops.wm.tool_set_by_id(name=SELECT_TOOL, space_type='VIEW_3D')
            except (RuntimeError, TypeError):
                pass
        return {'FINISHED'}

    def _drop(self):
        ob = self._ob
        if ob is None:
            return
        data = ob.data
        bpy.data.objects.remove(ob)
        if data is not None and data.users == 0:
            bpy.data.meshes.remove(data)
        self._reset()


classes = (ALLSET_OT_interactive_create,)
