# SPDX-License-Identifier: GPL-3.0-or-later
"""Distance dimensions drawn like Maya's, and the Distance Tool (GitHub #370; operators/distance_tool.py).

Maya draws a distance dimension as a dimension line beside the two points: a solid line with a hollow arrowhead at
each end, set off to one side by a fixed screen distance (the line's direction turned a quarter, the same side for
the same direction), dotted lines from each point to it, and the distance in the middle with the dimension's
precision (6 decimals, trailing zeros left out). Grey when not selected, white when selected, green as the lead.
The distance is in Maya units (``operators/units.maya_unit``) and follows the locators while they move.

Every 3D View with overlays on draws them (its Object Types: Empty on). A click on a dimension line selects the
dimension (``operators/select_priority.py``).

Like Maya, deleting a locator deletes the distance dimensions that measure from or to it, whichever way it is deleted:
the kit's Delete takes them along (``operators/dag.py``); after any other delete (Blender's, the Outliner's, a script)
a depsgraph update that changed which objects exist schedules ``clean_up`` (a timer, outside the update). Undo brings
the locator and its dimensions back together. Blender's delete keeps a locator a dimension still points at as an
object in no collection: that counts as deleted, and it goes too.
"""

import bpy
from bpy.app.handlers import persistent
from bpy_extras import view3d_utils
from mathutils import Vector

from ..keymap.ic_data import platform_tool

DORMANT = (0.6, 0.6, 0.6)
LEAD = (0x43 / 255, 1.0, 0xa3 / 255)
SELECTED = (1.0, 1.0, 1.0)
OFFSET_PX = 65.0            # the dimension line's distance from the two points
ARROW_PX = 10.0             # arrowhead length and half width
ARROW_HALF_PX = 4.0
DOT_PX = 2.0                # dotted lines: dot and gap
FONT_PX = 11
TOOL = "allset.distance_tool"

_handle = []
_DIMS = {}                  # view layer pointer -> (``objects_version``, its distance dimensions)


# --- geometry (pure) --------------------------------------------------------------------------------------------

def dimension_line(a, b, scale=1.0):
    """Region points (y up) of the two locators -> the dimension line's ends: set off by OFFSET_PX to the
    side the line's direction turned a quarter clockwise on screen points to."""
    a, b = Vector(a), Vector(b)
    d = b - a
    if d.length < 1e-6:
        n = Vector((0.0, 1.0))
    else:
        d.normalize()
        n = Vector((d.y, -d.x))
    off = n * OFFSET_PX * scale
    return a + off, b + off


def arrowhead(tip, toward, scale=1.0):
    """The three corners of a hollow arrowhead with its point at ``tip``, its base towards ``toward``."""
    tip, toward = Vector(tip), Vector(toward)
    d = toward - tip
    if d.length < 1e-6:
        return [tip, tip, tip]
    d.normalize()
    n = Vector((-d.y, d.x))
    base = tip + d * ARROW_PX * scale
    return [tip, base + n * ARROW_HALF_PX * scale, base - n * ARROW_HALF_PX * scale]


def dots(a, b, scale=1.0):
    """Segments [(p, q)] of a dotted line from ``a`` to ``b``."""
    a, b = Vector(a), Vector(b)
    d = b - a
    length = d.length
    step = DOT_PX * scale
    if length < 1e-6 or step <= 0:
        return []
    d /= length
    out, t = [], 0.0
    while t < length:
        out.append((a + d * t, a + d * min(t + step, length)))
        t += 2 * step
    return out


# --- the scene --------------------------------------------------------------------------------------------------

def forget():
    """A dimension was made: look the view layers up again at the next draw."""
    _DIMS.clear()


def dimensions(view_layer):
    """The distance dimensions of ``view_layer``, looked up again only when objects came or went."""
    from ..operators.distance_tool import is_dimension
    from .outliner import objects_version
    key = objects_version()
    ptr = view_layer.as_pointer()
    got = _DIMS.get(ptr)
    if got is None or got[0] != key:
        if len(_DIMS) > 8:
            _DIMS.clear()
        got = _DIMS[ptr] = (key, [ob for ob in view_layer.objects if is_dimension(ob)])
    return got[1]


def colour(ob, active):
    if ob.select_get():
        return LEAD if ob == active else SELECTED
    return DORMANT


def shown(space):
    return (space is not None and space.type == 'VIEW_3D' and space.overlay.show_overlays
            and space.show_object_viewport_empty)


def screen_items(context, region, rv3d, space=None):
    """[(dimension, a, b, a2, b2, text)] for the dimensions visible in this view: region points of the two locators,
    the dimension line's ends and the drawn number."""
    from ..operators import distance_tool as dt
    view_layer = context.view_layer
    scale = context.preferences.system.ui_scale or 1.0
    out = []
    for ob in dimensions(view_layer):
        seen = ob.visible_get(view_layer=view_layer, viewport=space) if space is not None else ob.visible_get()
        if not seen:
            continue
        p, q = dt.ends(ob)
        if p is None or q is None:
            continue
        wa, wb = p.matrix_world.translation, q.matrix_world.translation
        a = view3d_utils.location_3d_to_region_2d(region, rv3d, wa)
        b = view3d_utils.location_3d_to_region_2d(region, rv3d, wb)
        if a is None or b is None:
            continue
        a2, b2 = dimension_line(a, b, scale)
        value = (wb - wa).length / _unit(context.scene)
        out.append((ob, a, b, a2, b2, dt.label(value)))
    return out


def _unit(scene):
    from ..operators import units
    return units.maya_unit(scene)


def segment_distance_px(mouse, a, b):
    """Screen distance from ``mouse`` to the segment a-b."""
    m, a, b = Vector(mouse), Vector(a), Vector(b)
    d = b - a
    t = 0.0 if d.length_squared < 1e-12 else max(0.0, min(1.0, (m - a).dot(d) / d.length_squared))
    return (a + d * t - m).length


def hits(context, region, rv3d, mouse):
    """[(name, screen distance)] from ``mouse`` to each visible dimension line (click selection)."""
    try:
        items = screen_items(context, region, rv3d, context.space_data)
    except (ReferenceError, AttributeError):
        _DIMS.clear()
        return []
    return [(ob.name, segment_distance_px(mouse, a2, b2)) for ob, _a, _b, a2, b2, _t in items
            if not ob.hide_select]


# --- drawing ------------------------------------------------------------------------------------------------------

def _draw():
    context = bpy.context
    try:
        space = context.space_data
        if not dimensions(context.view_layer) or not shown(space):
            return
        region, rv3d = context.region, context.region_data
        try:
            items = screen_items(context, region, rv3d, space)
        except ReferenceError:      # a dimension or locator removed before the next depsgraph update
            _DIMS.clear()
            items = screen_items(context, region, rv3d, space)
    except (ReferenceError, AttributeError, KeyError, ValueError, RuntimeError, TypeError):
        return
    if not items:
        return
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader
    scale = context.preferences.system.ui_scale or 1.0
    active = context.view_layer.objects.active
    lines, cols = [], []
    for ob, a, b, a2, b2, _text in items:
        c = (*colour(ob, active), 1.0)
        segs = [(a2, b2), *dots(a, a2, scale), *dots(b, b2, scale)]
        for tip, toward in ((a2, b2), (b2, a2)):
            t0, t1, t2 = arrowhead(tip, toward, scale)
            segs += [(t0, t1), (t1, t2), (t2, t0)]
        for p, q in segs:
            lines += [(p.x, p.y), (q.x, q.y)]
            cols += [c, c]
    sh = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
    gpu.state.blend_set('ALPHA')
    try:
        sh.uniform_float("viewportSize", (region.width, region.height))
        sh.uniform_float("lineWidth", 1.0 * context.preferences.system.pixel_size)
        batch_for_shader(sh, 'LINES', {"pos": [(x, y, 0.0) for x, y in lines], "color": cols}).draw(sh)
        font = 0
        blf.size(font, round(FONT_PX * scale))
        for ob, _a, _b, a2, b2, text in items:
            w, h = blf.dimensions(font, text)
            mid = (a2 + b2) / 2
            blf.color(font, *colour(ob, active), 1.0)
            blf.position(font, round(mid.x - w / 2), round(mid.y - h / 2), 0)
            blf.draw(font, text)
    finally:
        gpu.state.blend_set('NONE')


# --- a deleted locator takes its dimensions along ------------------------------------------------------------------

def _gone(ob):
    """A dimension's locator is deleted: missing, or kept only by the dimension (in no collection)."""
    try:
        return ob is None or not ob.users_collection
    except ReferenceError:
        return True


def orphaned(objects=None):
    """The distance dimensions (of ``objects``, default every object) one of whose locators is deleted."""
    from ..operators.distance_tool import ends, is_dimension
    out = []
    for ob in (bpy.data.objects if objects is None else objects):
        try:
            if is_dimension(ob) and any(_gone(e) for e in ends(ob)):
                out.append(ob)
        except ReferenceError:
            continue
    return out


def clean_up():
    """Delete the distance dimensions whose locator was deleted, and the locators only they still kept. Returns the
    names deleted."""
    from ..operators.distance_tool import ends
    names, kept = [], []
    for dd in orphaned():
        for end in ends(dd):
            if end is not None and _gone(end):
                kept.append(end)
        names.append(dd.name)
        bpy.data.objects.remove(dd, do_unlink=True)
    for ob in kept:
        try:
            if ob.users == 0:
                names.append(ob.name)
                bpy.data.objects.remove(ob)
        except ReferenceError:          # kept by two dimensions: gone already
            pass
    if names:
        _DIMS.clear()
    return names


def _clean_up_later():
    try:
        clean_up()
    except (ReferenceError, RuntimeError, AttributeError):
        _DIMS.clear()
    return None


_seen = [None]              # the ``objects_version`` the delete check last looked at


@persistent
def _on_depsgraph(_scene, _depsgraph=None):
    """After an update that changed which objects exist: a dimension of the view layer with a deleted locator
    schedules ``clean_up``. Other updates (a move, playback) cost one number compare."""
    from .outliner import objects_version
    version = objects_version()
    if version == _seen[0]:
        return
    _seen[0] = version
    try:
        view_layer = bpy.context.view_layer
        bad = view_layer is not None and bool(orphaned(dimensions(view_layer)))
    except (ReferenceError, AttributeError):
        _DIMS.clear()
        return
    if bad and not bpy.app.timers.is_registered(_clean_up_later):
        bpy.app.timers.register(_clean_up_later, first_interval=0.0)


# --- the tool -----------------------------------------------------------------------------------------------------

def _tool_class(mode):
    return type(f"ALLSET_TL_distance_{mode.lower()}", (bpy.types.WorkSpaceTool,), {
        "bl_space_type": 'VIEW_3D', "bl_context_mode": mode, "bl_idname": TOOL, "bl_label": "Distance Tool",
        "bl_description": "Click two points to measure the distance between them: a locator at each point and a "
                          "distance dimension that shows the distance (Maya Distance Tool)",
        "bl_icon": "ops.view3d.ruler", "bl_widget": None, "bl_cursor": 'CROSSHAIR',
        "bl_keymap": (("allset.distance_click", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),
                      ("allset.distance_click", {"type": 'LEFTMOUSE', "value": 'PRESS', "ctrl": True}, None)),
    })


TOOLS = [_tool_class(mode) for mode in ('OBJECT', 'EDIT_MESH')]


def register():
    if not _handle:
        _handle.append(bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL'))
    for tool in TOOLS:
        bpy.utils.register_tool(platform_tool(tool), after={"builtin.measure"})
    _seen[0] = None             # a locator deleted in Blender mode: looked at with the next update
    if _on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)


def unregister():
    while _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    if bpy.app.timers.is_registered(_clean_up_later):
        bpy.app.timers.unregister(_clean_up_later)
    for tool in reversed(TOOLS):
        bpy.utils.unregister_tool(tool)
    while _handle:
        bpy.types.SpaceView3D.draw_handler_remove(_handle.pop(), 'WINDOW')
    _DIMS.clear()
