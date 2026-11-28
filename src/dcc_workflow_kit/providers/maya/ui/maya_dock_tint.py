# SPDX-License-Identifier: GPL-3.0-or-later
"""Lifts the Maya dock areas to Maya's dock grey with one additive pass after drawing (``dock_lift``, ``draw_tint``),
leaving the Layer Editor list body as it is: found in the drawn pixels (``_list_hole``) and kept while a transform runs or a
window is dragged or resized (``_kept_hole``). Also ``_fill``, the cached rect batches the tab strip draws with. Drawn from
maya_dock.py's Properties draw callback; maya_dock.py re-exports these names.
"""

import bpy

from .draw_replay import call
from .maya_dock_roles import KINDS, role, shown_kind


# Maya-style dock grey #444444 (Blender's factory Properties grey is #303030). The kit
# ships no theme, so the dock areas are lifted by the difference after drawing: an additive grey over the
# region raises the background to #444444 and the value fields with it (#1d1d1d -> #313131); text stays
# near white. Only a theme darker than that is lifted, never a light one.
MAYA_DOCK_GREY = 0x44 / 255.0
TINTED_ROLES = {'STACK', *KINDS}


def dock_lift(context):
    """The sRGB grey added over a Maya dock (0 when the preference is off or the theme is already as light)."""
    from .. import preferences
    try:
        on = preferences.get().maya_dock_colors
    except Exception:
        on = True
    if not on:
        return 0.0
    th = context.preferences.themes[0]
    try:
        back = tuple(th.properties.space.back)[:3]
    except AttributeError:
        return 0.0
    d = MAYA_DOCK_GREY - max(back)
    return d if 0.0 < d <= 0.2 else 0.0


def draw_tint():
    """Lift a Maya dock area to Maya's grey (``dock_lift``): one additive quad over the WINDOW region."""
    context = bpy.context
    area, region = context.area, context.region
    if region is None or region.type != 'WINDOW' or role(area) not in TINTED_ROLES:
        return
    d = dock_lift(context)
    if d <= 0.0:
        return
    import gpu
    w, h = region.width, region.height
    hole = _kept_hole(context, region) if shown_kind(context) == 'CHANNEL_BOX' else None
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    call(gpu.state.blend_set, 'ADDITIVE')
    try:
        for x0, y0, x1, y1 in _around(hole, w, h):
            _fill(shader, x0, y0, x1, y1, (d, d, d, 1.0))
    finally:
        call(gpu.state.blend_set, 'NONE')


def _around(hole, w, h):
    """Rects covering (0, 0, w, h) except ``hole`` (x0, y0, x1, y1)."""
    if hole is None:
        return [(0, 0, w, h)]
    x0, y0, x1, y1 = hole
    return [r for r in ((0, 0, w, y0), (0, y1, w, h), (0, y0, x0, y1), (x1, y0, w, y1)) if r[2] > r[0] and r[3] > r[1]]


def dark_span(values, limit):
    """(first, last) index of the values below ``limit`` (0-255), or None."""
    idx = [i for i, v in enumerate(values) if v < limit]
    return (idx[0], idx[-1]) if idx else None


def dark_top(values, start, limit, gap):
    """Highest index from ``start`` upward still in the dark block: dark values with no run of more than ``gap``
    lighter ones between them and ``start`` (a selected layer row inside the list doesn't end it)."""
    top, light = start, 0
    for i in range(start, len(values)):
        if values[i] < limit:
            top, light = i, 0
        else:
            light += 1
            if light > gap:
                break
    return top


_hole_row = {}    # region pointer -> framebuffer row that last crossed the list body
_hole_kept = {}   # region pointer -> (transform pointer or None, region size and UI scale, list body rect) last found


def _kept_hole(context, region):
    """``_list_hole``, or the rect found at an earlier redraw of the same region size when nothing in the region can
    have moved since: while a transform runs (until it ends the selection and so the Channel Box rows and the Layer
    Editor list stay where they are, only values change) and while a window is dragged or resized (every window
    redraws at each step with the same contents). Reading the drawn pixels back waits for the GPU on every such
    redraw."""
    from . import window_motion
    from .maya_joints import transform_op
    key = region.as_pointer()
    op = transform_op()
    op_ptr = op.as_pointer() if op is not None else None
    size = (region.width, region.height, context.preferences.system.ui_scale)
    moved = window_motion.moved(("dock", key))
    got = _hole_kept.get(key)
    if got is not None and got[1] == size and (moved or (op_ptr is not None and got[0] == op_ptr)):
        return got[2]
    hole = _list_hole(context, region)
    _hole_kept[key] = (op_ptr, size, hole)
    return hole


def _list_hole(context, region):
    """The Layer Editor list body (Blender's list grey is already as dark): left unlifted. Found in the drawn
    pixels of the Layer Editor part, read back once: a row near the region bottom for its sides, a column inside its
    left edge for its top."""
    import gpu
    import numpy as np
    scale = context.preferences.system.ui_scale or 1.0
    try:
        back = max(tuple(context.preferences.themes[0].properties.space.back)[:3])
    except AttributeError:
        return None
    limit = back * 255.0 - 4.0
    from . import channel_box
    le_top = int(region.height * (1.0 - channel_box.cb_share(region, channel_box._unit(context))))
    width = region.width
    if le_top < 1 or width < 1:
        return None
    try:
        buf = gpu.state.active_framebuffer_get().read_color(0, 0, width, le_top, 4, 0, 'UBYTE')
    except ValueError:
        return None
    from .. import compat
    reds = np.frombuffer(compat.flat_buffer(buf), dtype=np.uint8)[0:4 * width * le_top:4].reshape(le_top, width)
    # the list ends 14 px x scale above the region bottom in a tall dock, higher in a shorter one (the
    # Time Slider grew at UI 1.25 and the list bottom left the sampled row): sample upwards, the last hit first
    key = region.as_pointer()
    first = max(1, round(14 * scale))
    rows = [_hole_row.get(key)] + list(range(first, round(64 * scale), max(1, round(4 * scale))))
    span, ys = None, first
    for ys in rows:
        if ys is None or le_top <= ys + 10:
            continue
        span = dark_span(reds[ys].tolist(), limit)
        if span is not None and span[1] - span[0] >= 40 * scale:
            break
        span = None
    if span is None:
        _hole_row.pop(key, None)
        return None
    _hole_row[key] = ys
    x0, x1 = span
    values = reds[:, x0 + 1].tolist()
    if values[ys] >= limit:
        return None
    top = dark_top(values, ys, limit, round(30 * scale))
    bottom = ys
    while bottom > 0 and values[bottom - 1] < limit:
        bottom -= 1
    return (x0, bottom, x1 + 1, top + 1)


_rects = {}      # (x0, y0, x1, y1) -> GPU batch of that rect: the dock draws the same rects on every redraw


def _fill(shader, x0, y0, x1, y1, rgba):
    key = (x0, y0, x1, y1)
    batch = _rects.get(key)
    if batch is None:
        from gpu_extras.batch import batch_for_shader
        if len(_rects) > 64:
            _rects.clear()
        batch = _rects[key] = batch_for_shader(shader, 'TRIS', {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]},
                                               indices=[(0, 1, 2), (0, 2, 3)])
    call(shader.uniform_float, "color", rgba)
    call(batch.draw, shader)
