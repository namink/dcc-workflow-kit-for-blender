# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's Distance Tool (Create > Measure Tools > Distance Tool, GitHub #370).

Like Maya: a click in a 3D View puts a locator there (on the ground in a perspective view, on the view plane through
the origin in an orthographic one; the X / C / V snap holds and Blender's snapping snap the point), a second click
puts a second locator and a distance dimension (``distanceDimension1``) that measures between the two. A click on an
existing locator measures from / to that locator instead of making a new one. The tool stays on: the next two clicks
make the next measurement. Moving either locator changes the distance; ``ui/distance_dimensions.py`` draws it.

A distance dimension is an empty at the origin that draws nothing itself (like a Maya group); its custom properties
``allset_dd_start`` / ``allset_dd_end`` point at the two locators. One measurement is one undo step.
"""

import bpy
from bpy.props import FloatVectorProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from .. import results
from . import create, naming, units

DD_BASE = "distanceDimension"
START, END = "allset_dd_start", "allset_dd_end"
PRECISION = 6                     # decimals of the drawn distance, like Maya's distance dimension
PICK_PX = 8.0                     # a click this close to a locator on screen measures from / to it
STATUS = "Distance Tool: click two points to measure the distance between them. Esc stops"


# --- the scene --------------------------------------------------------------------------------------------------

def is_locator(ob):
    return ob is not None and ob.type == 'EMPTY' and bool(ob.get(create.LOCATOR_PROP))


def is_dimension(ob):
    return ob is not None and ob.type == 'EMPTY' and START in ob and END in ob


def ends(ob):
    """The two locators (objects) a distance dimension measures between; None for a missing one."""
    a, b = ob.get(START), ob.get(END)
    return (a if isinstance(a, bpy.types.Object) else None, b if isinstance(b, bpy.types.Object) else None)


def dimensions_of(objects):
    """The distance dimensions (not in ``objects``) that measure from or to one of ``objects``."""
    names = {ob.name for ob in objects}
    out = []
    for ob in bpy.data.objects:
        if ob.name in names or not is_dimension(ob):
            continue
        if any(end is not None and end.name in names for end in ends(ob)):
            out.append(ob)
    return out


def distance(ob, scene=None):
    """The distance a dimension shows, in Maya units (None while a locator is missing)."""
    a, b = ends(ob)
    if a is None or b is None:
        return None
    return (b.matrix_world.translation - a.matrix_world.translation).length / units.maya_unit(scene)


def label(value, precision=PRECISION):
    """The number Maya draws: ``precision`` decimals, without trailing zeros (10 -> "10", 13.4571449 -> "13.457145")."""
    text = f"{value:.{precision}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _collection(context):
    layer = context.view_layer.active_layer_collection
    return layer.collection if layer is not None else context.scene.collection


def new_locator(context, point):
    """A Maya locator (``locatorN``, like Create > Locator) at world ``point``."""
    ob = bpy.data.objects.new("locator", None)
    ob.empty_display_type = 'PLAIN_AXES'
    ob.empty_display_size = units.maya_unit(context.scene)
    _collection(context).objects.link(ob)
    naming.apply_maya_name(ob, "locator", rename_data=False)
    ob[create.LOCATOR_PROP] = True
    ob.location = point
    return ob


def locator_at(context, point, tolerance=None):
    """A visible kit locator at world ``point`` (within ``tolerance``, default a thousandth of a unit)."""
    tol = tolerance if tolerance is not None else 1e-3 * units.maya_unit(context.scene)
    for ob in context.view_layer.objects:
        if is_locator(ob) and ob.visible_get() and (ob.matrix_world.translation - Vector(point)).length <= tol:
            return ob
    return None


def locator_under(context, region, rv3d, mouse, radius=PICK_PX):
    """The visible kit locator nearest to ``mouse`` (region px) on screen, within ``radius`` px."""
    best, best_d = None, radius
    for ob in context.view_layer.objects:
        if not is_locator(ob) or not ob.visible_get():
            continue
        xy = view3d_utils.location_3d_to_region_2d(region, rv3d, ob.matrix_world.translation)
        if xy is None:
            continue
        d = (xy - Vector(mouse)).length
        if d <= best_d:
            best, best_d = ob, d
    return best


def new_dimension(context, start, end):
    """``distanceDimensionN`` measuring from locator ``start`` to locator ``end``."""
    ob = bpy.data.objects.new(DD_BASE, None)
    ob.empty_display_type = 'PLAIN_AXES'
    ob.empty_display_size = 0.0               # draws nothing itself, like a Maya group: the dimension is drawn
    _collection(context).objects.link(ob)
    naming.apply_maya_name(ob, DD_BASE, rename_data=False)
    ob[START], ob[END] = start, end
    from ..ui import distance_dimensions
    distance_dimensions.forget()
    return ob


def _select(context, objects, active):
    for ob in context.selected_objects:
        if ob not in objects:
            ob.select_set(False)
    for ob in objects:
        ob.select_set(True)
    context.view_layer.objects.active = active


def measure(context, start, end):
    """Like Maya's ``distanceDimension -sp -ep``: a locator at each world point (an existing locator at the point is
    used instead) and the distance dimension between them. Returns (locator, locator, dimension)."""
    a = locator_at(context, start) or new_locator(context, start)
    b = locator_at(context, end) or new_locator(context, end)
    dd = new_dimension(context, a, b)
    _select(context, [b, dd], dd)
    return a, b, dd


# --- the tool ---------------------------------------------------------------------------------------------------

def click_point(context, region, rv3d, mouse, ctrl=False):
    """World point of a Distance Tool click: snapped like the kit's curve tools (X grid / C curve / V point holds and
    Blender's snapping, Ctrl inverts it), else on the ground / view plane."""
    from . import curve_draw, curve_snap
    ts = context.scene.tool_settings
    modes = curve_snap.scene_modes(ts.use_snap, ts.snap_elements, ctrl)
    if modes - {curve_snap.GRID}:
        space = context.space_data if context.space_data is not None and context.space_data.type == 'VIEW_3D' \
            else None
        targets = curve_snap.gather(context, space)
        surface = curve_snap.surface_under(context, region, rv3d) if curve_snap.SURFACE in modes else None
        p = curve_snap.snap_to(targets, modes, mouse, rv3d.perspective_matrix, region.width, region.height,
                               curve_snap.CURVE_RADIUS_PX * _ui_scale(context), surface)
        if p is not None:
            return Vector(p)
    p = curve_draw.plane_point(region, rv3d, mouse)
    if curve_snap.GRID in modes:
        p = curve_draw.snap_grid(p, curve_draw.grid_step(context.scene))
    return p


def _ui_scale(context):
    try:
        return context.preferences.system.ui_scale or 1.0
    except AttributeError:
        return 1.0


def click_locator(context, region, rv3d, mouse, ctrl=False):
    """The locator a click gives: the one under the cursor, else a new one at the click point."""
    ob = locator_under(context, region, rv3d, mouse, PICK_PX * _ui_scale(context))
    if ob is not None:
        return ob
    p = click_point(context, region, rv3d, mouse, ctrl)
    return locator_at(context, p) or new_locator(context, p)


# keys that end a measurement waiting for its second point and then do their own job (Q / W / E / R tools, ...)
_PASS_KEYS = {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE', 'MOUSEMOVE',
              'INBETWEEN_MOUSEMOVE', 'TRACKPADPAN', 'TRACKPADZOOM', 'MOUSEROTATE', 'TIMER', 'TIMER_REPORT',
              'TIMERREGION', 'WINDOW_DEACTIVATE', 'NDOF_MOTION', 'LEFT_ALT', 'RIGHT_ALT', 'LEFT_CTRL',
              'RIGHT_CTRL', 'LEFT_SHIFT', 'RIGHT_SHIFT', 'OSKEY', 'X', 'C', 'V'}


class ALLSET_OT_distance_click(bpy.types.Operator):
    """Distance Tool click: the first click places a locator, the second one another locator and a distance
    dimension between them (Maya Distance Tool)"""
    bl_idname = "allset.distance_click"
    bl_label = "Distance Tool"
    bl_options = {'UNDO', 'INTERNAL'}

    # scripts: measure between two world points in Maya units without clicks (like distanceDimension -sp -ep)
    start: FloatVectorProperty(name="Start Point", size=3, options={'SKIP_SAVE'})
    end: FloatVectorProperty(name="End Point", size=3, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'EDIT_MESH'}

    def execute(self, context):
        k = units.maya_unit(context.scene)
        start, end = Vector(self.start) * k, Vector(self.end) * k
        if (end - start).length < 1e-9:
            self.report({'WARNING'}, "The two points are the same: nothing to measure")
            return {'CANCELLED'}
        _a, _b, dd = measure(context, start, end)
        results.result(self, f"{dd.name}: {label(distance(dd, context.scene))}")
        return {'FINISHED'}

    def _here(self, context, event):
        """(region, rv3d, mouse) of the 3D View under the event (None outside every 3D View)."""
        from .joint_tool import view_under
        hit = view_under(context.window, event.mouse_x, event.mouse_y)
        if hit is None:
            return None
        _area, region = hit
        return region, region.data, (event.mouse_x - region.x, event.mouse_y - region.y)

    def _place(self, context, event):
        here = self._here(context, event)
        if here is None:
            return None
        region, rv3d, mouse = here
        return click_locator(context, region, rv3d, mouse, event.ctrl)

    def invoke(self, context, event):
        if context.region_data is None:
            return {'PASS_THROUGH'}
        ob = self._place(context, event)
        if ob is None:
            return {'PASS_THROUGH'}
        self._first = ob.name
        if context.mode == 'OBJECT':
            _select(context, [ob], ob)
        try:
            context.workspace.status_text_set(STATUS)
        except AttributeError:
            pass
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _end(self, context):
        try:
            context.workspace.status_text_set(None)
        except (AttributeError, ReferenceError):
            pass

    def modal(self, context, event):
        if event.type == 'ESC' and event.value == 'PRESS':
            self._end(context)
            return {'FINISHED'}            # the first locator stays, like Maya
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and not event.alt:
            first = bpy.data.objects.get(self._first)
            ob = self._place(context, event)
            if ob is None:
                return {'PASS_THROUGH'}    # a click outside the 3D Views (a menu, the Outliner)
            if first is None or first == ob:
                self._first = ob.name      # the first locator is gone (or clicked again): start from this one
                return {'RUNNING_MODAL'}
            dd = new_dimension(context, first, ob)
            if context.mode == 'OBJECT':
                _select(context, [ob, dd], dd)
            self._end(context)
            results.result(self, f"{dd.name}: {label(distance(dd, context.scene))}")
            return {'FINISHED'}
        if event.type in _PASS_KEYS or event.type == 'LEFTMOUSE' or event.value not in {'PRESS', 'CLICK'}:
            return {'PASS_THROUGH'}
        # another key or button (a tool key, a marking menu): the measurement stops, the event does its own job
        self._end(context)
        return {'FINISHED', 'PASS_THROUGH'}


classes = (ALLSET_OT_distance_click,)
