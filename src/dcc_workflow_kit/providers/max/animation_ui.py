# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format
"Track View surfaces backed by Blender action slots, never demonstration data.\n\n``draw(context, kind)`` paints Curve/Dope Image Editor surfaces. The chrome\nrouter calls ``active_event`` first, then ``handle_event`` for a surface under\nthe pointer, and dispatches ``('ANIM', ...)`` actions through ``dispatch``.\nAll pointer coordinates are logical units from surfaces.scale().\n"
import math
import re
from dataclasses import dataclass, field
import bpy
from bpy.props import FloatProperty
from . import runtime, surfaces
from .editors import _action_fcurves
BG = (0.265, 0.265, 0.265, 1.0)
PLOT = (0.185, 0.185, 0.185, 1.0)
GRID = (0.265, 0.265, 0.265, 1.0)
TEXT = (0.81, 0.81, 0.81, 1.0)
DIM = (0.57, 0.57, 0.57, 1.0)
SELECT = (0.28, 0.44, 0.61, 1.0)
YELLOW = (0.94, 0.83, 0.22, 1.0)
AXES = ((0.83, 0.31, 0.29, 1.0), (0.33, 0.75, 0.37, 1.0), (0.34, 0.55, 0.94, 1.0))
_states = {}
_drag = None
_clipboard = []

@dataclass
class ViewState:
    kind: str = _msg('Curve')
    tmin: float = -5.0
    tmax: float = 105.0
    vmin: float = -5.0
    vmax: float = 105.0
    left: float = 265.0
    scroll: float = 0.0
    closed: set = field(default_factory=set)
    tool: str = 'MOVE'
    snap: bool = True
    selected_only: bool = False
    handles: bool = True
    auto_zoom: bool = True
    ranges: bool = False
    popup: str = ''
    popup_x: float = 0.0
    active_curve: object = None
    initialized: bool = False
    area_pointer: int = 0
    rectangle: object = None
    isolate: set = field(default_factory=set)

def state_for(area, kind=None):
    key = area.as_pointer()
    state = _states.setdefault(key, ViewState(area_pointer=key))
    if kind is not None:
        state.kind = kind
    return state

def _shown(obj, state):
    """The object's active-slot curves, limited to the isolated ones while Isolate Curve is on."""
    return [c for c in _action_fcurves(obj) if not state.isolate or c.as_pointer() in state.isolate]

def _objects(context, state):
    objects = [o for o in context.view_layer.objects if _action_fcurves(o) or o.select_get()]
    if state.selected_only:
        objects = [o for o in objects if o.select_get()]
    if state.isolate:
        objects = [o for o in objects if _shown(o, state)]
    return sorted(objects, key=lambda o: o.name.casefold())

def curves(context, state):
    """The editable active-slot curves shown by this editor's object filter."""
    return [(o, c) for o in _objects(context, state) for c in _shown(o, state)]

def _can_edit(obj, curve):
    return bool(obj.is_editable and curve.id_data.is_editable and (not curve.lock))

def _display_scale(curve):
    path = curve.data_path.rsplit('.', 1)[-1]
    if path == 'rotation_euler' or (path == 'rotation_axis_angle' and curve.array_index == 0):
        return 180.0 / math.pi
    return 100.0 if path == 'scale' else 1.0

def _channel_name(curve):
    path = curve.data_path.rsplit('.', 1)[-1]
    axis = 'XYZW'[min(3, curve.array_index)]
    names = {'location': _msg('Position'), 'rotation_euler': _msg('Rotation'), 'rotation_quaternion': _msg('Quaternion'), 'rotation_axis_angle': _msg('Axis Angle'), 'scale': _msg('Scale')}
    label = f'{axis} {names[path]}' if path in names else f'{path} [{curve.array_index}]'
    bone = re.match('pose\\.bones\\["(.*)"\\]\\.', curve.data_path)
    return bone.group(1) + ': ' + label if bone else label

def _group_name(curve):
    path = curve.data_path.rsplit('.', 1)[-1]
    return {'location': _msg('Position'), 'rotation_euler': _msg('Rotation'), 'rotation_quaternion': _msg('Rotation'), 'rotation_axis_angle': _msg('Rotation'), 'scale': _msg('Scale')}.get(path, _msg('Parameters'))

def _row_tree(context, state):
    """(label, depth, collapse id, object, curves) rows; each row is real data."""
    rows = [(_msg('World'), 0, 'WORLD', None, ())]
    if 'WORLD' in state.closed:
        return rows
    rows.append((_msg('Objects'), 1, 'OBJECTS', None, ()))
    if 'OBJECTS' in state.closed:
        return rows
    for obj in _objects(context, state):
        all_curves = tuple(_shown(obj, state))
        oid = ('OBJECT', obj.as_pointer())
        rows.append((obj.name, 2, oid, obj, all_curves))
        if oid in state.closed:
            continue
        rows.append((_msg('Transform'), 3, ('TRANSFORM', obj.as_pointer()), obj, all_curves))
        if ('TRANSFORM', obj.as_pointer()) in state.closed:
            continue
        groups = {}
        for curve in all_curves:
            groups.setdefault(_group_name(curve), []).append(curve)
        for (name, members) in groups.items():
            gid = ('GROUP', obj.as_pointer(), name)
            rows.append((name, 4, gid, obj, tuple(members)))
            if gid not in state.closed:
                for curve in members:
                    rows.append((_channel_name(curve), 5, None, obj, (curve,)))
    return rows

def selected_keys(context, state):
    return [(obj, curve, key) for (obj, curve) in curves(context, state) if _can_edit(obj, curve) for key in curve.keyframe_points if key.select_control_point]

def select_keys(context, state, mode='ALL'):
    for (obj, curve) in curves(context, state):
        if not _can_edit(obj, curve):
            continue
        for key in curve.keyframe_points:
            selected = not key.select_control_point if mode == 'INVERT' else mode == 'ALL'
            key.select_control_point = selected
            key.select_left_handle = key.select_right_handle = selected

def frame_all(context, state, selected=False):
    keys = [(c, k) for (_, c) in curves(context, state) for k in c.keyframe_points if not selected or k.select_control_point]
    if keys:
        ts = [k.co.x for (_, k) in keys]
        vs = [k.co.y * _display_scale(c) for (c, k) in keys]
        (t0, t1, v0, v1) = (min(ts), max(ts), min(vs), max(vs))
    else:
        (t0, t1) = (context.scene.frame_start, context.scene.frame_end)
        (v0, v1) = (-10.0, 10.0)
    tpad = max(2.0, (t1 - t0) * 0.08)
    vpad = max(0.5, (v1 - v0) * 0.12)
    (state.tmin, state.tmax) = (t0 - tpad, t1 + tpad)
    (state.vmin, state.vmax) = (v0 - vpad, v1 + vpad)
    state.initialized = True

def _plot(state, width, height):
    left = min(state.left, max(135.0, width * 0.4))
    return (left + 43 if state.kind == _msg('Curve') else left + 2, 49.0, max(30.0, width - left - (53 if state.kind == _msg('Curve') else 12)), max(35.0, height - 166.0))

def _screen(state, plot, frame, value):
    (x, y, w, h) = plot
    return (x + (frame - state.tmin) / max(1e-09, state.tmax - state.tmin) * w, y + (value - state.vmin) / max(1e-09, state.vmax - state.vmin) * h)

def _values(state, plot, x, y):
    (px, py, w, h) = plot
    return (state.tmin + (x - px) / w * (state.tmax - state.tmin), state.vmin + (y - py) / h * (state.vmax - state.vmin))

def _step(span, pixels, spacing=72):
    raw = max(1e-09, span / max(1.0, pixels / spacing))
    base = 10.0 ** math.floor(math.log10(raw))
    return next((m * base for m in (1, 2, 5, 10) if m * base >= raw))

def _ticks(low, high, step):
    value = math.ceil(low / step) * step
    for _ in range(150):
        if value > high + step * 1e-07:
            break
        yield (0.0 if abs(value) < step * 1e-07 else value)
        value += step

def _clip_line(a, b, rect):
    """Liang-Barsky clips graph samples and handles, without GPU state leaks."""
    (x, y, w, h) = rect
    (dx, dy) = (b[0] - a[0], b[1] - a[1])
    (lo, hi) = (0.0, 1.0)
    for (p, q) in ((-dx, a[0] - x), (dx, x + w - a[0]), (-dy, a[1] - y), (dy, y + h - a[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return None
        else:
            t = q / p
            if p < 0:
                lo = max(lo, t)
            else:
                hi = min(hi, t)
            if lo > hi:
                return None
    return ((a[0] + lo * dx, a[1] + lo * dy), (a[0] + hi * dx, a[1] + hi * dy))

def _inside(x, y, rect):
    (px, py, w, h) = rect
    return px <= x <= px + w and py <= y <= py + h

def _curve_color(curve):
    if curve.color_mode == 'CUSTOM':
        return (*curve.color, 1.0)
    return AXES[curve.array_index % 3]

def _diamond(c, x, y, size, color):
    c.c.polygon([(x * c.u, (y + size) * c.u), ((x + size) * c.u, y * c.u), (x * c.u, (y - size) * c.u), ((x - size) * c.u, y * c.u)], color)

def _glyph(c, name, x, y):
    """Small independent tangent diagrams, on the same 24-unit button grid."""
    if name in {'AUTO', 'AUTO_CLAMPED', 'FREE', 'ALIGNED', 'VECTOR', 'FLAT', 'STEP'}:
        color = (0.44, 0.75, 0.75, 1.0)
        if name == 'STEP':
            points = [(x + 2, y + 6), (x + 11, y + 6), (x + 11, y + 16), (x + 21, y + 16)]
        elif name == 'VECTOR':
            points = [(x + 2, y + 3), (x + 11, y + 17), (x + 21, y + 8)]
        elif name == 'FREE':
            points = [(x + 2, y + 4), (x + 11, y + 12), (x + 21, y + 18)]
        elif name == 'FLAT':
            points = [(x + 2, y + 12), (x + 21, y + 12)]
        elif name == 'ALIGNED':
            points = [(x + 2, y + 5), (x + 21, y + 18)]
        else:
            points = [(x + 2, y + 5), (x + 5, y + 5), (x + 9, y + 11), (x + 14, y + 14), (x + 21, y + 14)]
        for (a, b) in zip(points, points[1:]):
            c.line([a, b], color, 1.1)
        _diamond(c, x + 11, y + 12, 2.4, YELLOW)
    else:
        c.icon(name, x + 1, y + 1, 22)

def _command(command, *args):
    return ('ANIM', command, *args)

def _button(c, x, y, label, command, icon=None, selected=False, width=24):
    c.button(x, y, width, 24, action=_command(command) if isinstance(command, str) else command, selected=selected, flat=True, label='' if icon else label)
    if icon:
        _glyph(c, icon, x + (width - 24) / 2, y)

def _draw_toolbar(c, state):
    y = c.h - 89
    buttons = [(_msg('Filters'), _command('FILTER'), 'filter', state.selected_only), (_msg('Move Keys'), _command('TOOL', 'MOVE'), 'move', state.tool == 'MOVE'), (_msg('Move Keys Horizontally'), _command('TOOL', 'TIME'), 'right', state.tool == 'TIME'), (_msg('Move Keys Vertically'), _command('TOOL', 'VALUE'), 'angle', state.tool == 'VALUE'), (_msg('Scale Keys'), _command('TOOL', 'SCALE_TIME'), 'scale', state.tool == 'SCALE_TIME'), (_msg('Scale Values'), _command('TOOL', 'SCALE_VALUE'), 'percent', state.tool == 'SCALE_VALUE'), (_msg('Add Keys'), _command('TOOL', 'ADD'), 'key', state.tool == 'ADD'), (_msg('Delete Keys'), 'DELETE', 'minus', False), (_msg('Zoom Extents'), 'FRAME_ALL', 'frame', False), (_msg('Zoom Selected'), 'FRAME_SELECTED', 'selection_region', False), (_msg('Pan'), _command('TOOL', 'PAN'), 'pan', state.tool == 'PAN'), (_msg('Zoom'), _command('TOOL', 'ZOOM'), 'zoom', state.tool == 'ZOOM')]
    x = 5
    for (label, cmd, icon, pressed) in buttons:
        _button(c, x, y, label, cmd, icon, pressed)
        x += 25
    c.line([(x + 3, y + 2), (x + 3, y + 22)], (0.39, 0.39, 0.39, 1))
    x += 10
    if state.kind == _msg('Curve'):
        for name in ('AUTO', 'AUTO_CLAMPED', 'FREE', 'ALIGNED', 'VECTOR', 'FLAT', 'STEP'):
            _button(c, x, y, name, _command('TANGENT', name), name)
            x += 25
        _button(c, x + 4, y, _msg('Show Tangents'), 'HANDLES', 'curve', state.handles)
        x += 33
    else:
        _button(c, x, y, _msg('Edit Keys'), _command('RANGES', False), 'dope', not state.ranges)
        x += 25
        _button(c, x, y, _msg('Edit Ranges'), _command('RANGES', True), 'layer', state.ranges)
        x += 25
    _button(c, x, y, _msg('Snap to Frames'), 'SNAP', 'snap3', state.snap)
    c.text(_msg('Controller'), 7, c.h - 109, 9, DIM)
    c.text(_msg('Key Window'), min(state.left, max(135.0, c.w * 0.4)) + 8, c.h - 109, 9, DIM)

def _menu_items(name, state):
    menus = {_msg('Editor'): [(_msg('Curve Editor'), _command('EDITOR', 'GRAPH')), (_msg('Dope Sheet'), _command('EDITOR', 'DOPESHEET')), (_msg('Return to Viewports'), _command('RETURN'))], _msg('Edit'): [(_msg('Undo'), surfaces.op('ed.undo')), (_msg('Redo'), surfaces.op('ed.redo')), (_msg('Cut Keys'), _command('CUT')), (_msg('Copy Keys'), _command('COPY')), (_msg('Paste Keys'), _command('PASTE')), (_msg('Delete Keys'), _command('DELETE'))], _msg('View'): [(_msg('Zoom Extents'), _command('FRAME_ALL')), (_msg('Zoom Selected'), _command('FRAME_SELECTED')), (_msg('Enable Auto-Zoom'), _command('AUTO_ZOOM')), (_msg('Pan'), _command('TOOL', 'PAN')), (_msg('Zoom'), _command('TOOL', 'ZOOM'))], _msg('Curves'): [(_msg('Constant Interpolation'), _command('INTERPOLATION', 'CONSTANT')), (_msg('Linear Interpolation'), _command('INTERPOLATION', 'LINEAR')), (_msg('Bezier Interpolation'), _command('INTERPOLATION', 'BEZIER')), (_msg('Mute Selected Tracks'), _command('MUTE')), (_msg('Constant Extrapolation'), _command('EXTRAPOLATION', 'CONSTANT')), (_msg('Linear Extrapolation'), _command('EXTRAPOLATION', 'LINEAR'))], _msg('Keys'): [(_msg('Select All'), _command('SELECT', 'ALL')), (_msg('Select None'), _command('SELECT', 'NONE')), (_msg('Invert Selection'), _command('SELECT', 'INVERT')), (_msg('Add Keys'), _command('TOOL', 'ADD')), (_msg('Key Properties...'), surfaces.op('bsm.animation_key_properties')), (_msg('Delete Keys'), _command('DELETE'))], _msg('Tangents'): [(label, _command('TANGENT', value)) for (label, value) in ((_msg('Auto'), 'AUTO'), (_msg('Clamped'), 'AUTO_CLAMPED'), (_msg('Custom'), 'FREE'), (_msg('Unified'), 'ALIGNED'), (_msg('Linear'), 'VECTOR'), (_msg('Flat'), 'FLAT'), (_msg('Step'), 'STEP'))], _msg('Time'): [(_msg('Reverse Selected Time'), _command('REVERSE')), (_msg('Scale Selected Time 50%'), _command('SCALE', 0.5)), (_msg('Scale Selected Time 200%'), _command('SCALE', 2.0)), (_msg('Insert 10 Frames'), _command('INSERT_TIME', 10.0)), (_msg('Delete 10 Frames'), _command('INSERT_TIME', -10.0))], _msg('Show'): [(_msg('Selected Objects Only'), _command('FILTER')), (_msg('Expand All'), _command('EXPAND')), (_msg('Collapse Objects'), _command('COLLAPSE')), (_msg('Show Tangent Handles'), _command('HANDLES')), (_msg('Edit Ranges') if not state.ranges else _msg('Edit Keys'), _command('RANGES', not state.ranges))]}
    return menus.get(name, [])

def _draw_popup(c, state):
    if not state.popup:
        return
    items = _menu_items(state.popup, state)
    x = min(state.popup_x, c.w - 225)
    top = c.h - 61
    c.rect(x - 1, top - len(items) * 23 - 3, 225, len(items) * 23 + 4, (0.13, 0.13, 0.13, 1))
    for (i, (label, action)) in enumerate(items):
        y = top - (i + 1) * 23
        c.button(x, y, 222, 23, label, action, flat=True)

def draw(context, kind=_msg('Curve')):
    c = surfaces.Canvas(context)
    state = state_for(context.area, kind)
    if not state.initialized:
        frame_all(context, state)
    plot = _plot(state, c.w, c.h)
    (px, py, pw, ph) = plot
    left = min(state.left, max(135.0, c.w * 0.4))
    c.rect(0, 0, c.w, c.h, BG)
    c.rect(0, c.h - 26, c.w, 26, (0.2, 0.2, 0.2, 1))
    c.icon('curve' if kind == _msg('Curve') else 'dope', 6, c.h - 23, 18)
    c.text(_msg('Track View - ') + (_msg('Curve Editor') if kind == _msg('Curve') else _msg('Dope Sheet')), 29, c.h - 18, 11)
    c.button(c.w - 105, c.h - 23, 100, 20, _msg('Viewports'), _command('RETURN'), flat=True)
    menu_names = [_msg('Editor'), _msg('Edit'), _msg('View'), _msg('Curves'), _msg('Keys')] + ([_msg('Tangents')] if kind == _msg('Curve') else [_msg('Time')]) + [_msg('Show')]
    x = 7
    for name in menu_names:
        width = len(name) * 6.5 + 14
        c.button(x, c.h - 59, width, 24, name, _command('MENU', name, x), selected=state.popup == name, flat=True)
        x += width
    c.line([(0, c.h - 62), (c.w, c.h - 62)], (0.16, 0.16, 0.16, 1))
    _draw_toolbar(c, state)
    c.rect(left, 26, c.w - left, c.h - 143, PLOT)
    c.rect(0, 26, left - 1, c.h - 143, (0.235, 0.235, 0.235, 1))
    c.line([(left, 26), (left, c.h - 94)], (0.1, 0.1, 0.1, 1))
    rows = _row_tree(context, state)
    row_top = c.h - 129 + state.scroll
    visible = []
    for (i, row) in enumerate(rows):
        (label, depth, collapse, obj, members) = row
        y = row_top - i * 20
        if y < 32 or y > c.h - 116:
            continue
        visible.append((row, y))
        leaf = collapse is None
        chosen = bool(members) and (members[0].select if leaf else obj and obj.select_get() and (depth == 2))
        if chosen:
            c.rect(1, y - 4, left - 2, 20, SELECT)
        color = _curve_color(members[0]) if leaf else DIM
        if leaf:
            c.rect(11 + depth * 12, y + 1, 7, 7, color)
        else:
            c.text('+' if collapse in state.closed else '−', 7 + depth * 12, y, 10, DIM)
        c.text(label[:max(8, int((left - 35 - depth * 12) / 5.8))], 23 + depth * 12, y, 9, TEXT)
        c.hit(2, y - 4, left - 4, 20, _command('TRACK', row), _msg('Select ') + label)
        if collapse is not None:
            c.hit(4 + depth * 12, y - 3, 16, 18, _command('COLLAPSE_ROW', collapse), _msg('Expand ') + label)
    tstep = _step(state.tmax - state.tmin, pw)
    for frame in _ticks(state.tmin, state.tmax, tstep):
        (sx, _) = _screen(state, plot, frame, 0)
        c.line([(sx, py), (sx, py + ph)], GRID)
        c.line([(sx, 28), (sx, 47)], DIM)
        c.text(f'{frame:g}', sx + 3, 34, 8, DIM)
    c.rect(left, 27, c.w - left, 21, (0.235, 0.235, 0.235, 1))
    for frame in _ticks(state.tmin, state.tmax, tstep):
        (sx, _) = _screen(state, plot, frame, 0)
        c.line([(sx, 42), (sx, 47)], DIM)
        c.text(f'{frame:g}', sx + 3, 32, 8, DIM)
    if kind == _msg('Curve'):
        vstep = _step(state.vmax - state.vmin, ph, 48)
        for value in _ticks(state.vmin, state.vmax, vstep):
            (_, sy) = _screen(state, plot, 0, value)
            c.line([(px, sy), (px + pw, sy)], (0.34, 0.34, 0.34, 1) if abs(value) < vstep * 1e-05 else GRID)
            c.text(f'{value:.4g}', left + 3, sy - 3, 8, DIM)
        for (obj, curve) in curves(context, state):
            if curve.hide or curve.mute:
                continue
            color = _curve_color(curve)
            if not curve.select:
                color = tuple((v * 0.55 for v in color[:3])) + (1.0,)
            factor = _display_scale(curve)
            previous = None
            samples = min(600, max(80, int(pw / 3)))
            segments = []
            for i in range(samples + 1):
                frame = state.tmin + (state.tmax - state.tmin) * i / samples
                position = _screen(state, plot, frame, curve.evaluate(frame) * factor)
                if previous:
                    clipped = _clip_line(previous, position, plot)
                    if clipped:
                        segments.extend(clipped)
                previous = position
            if segments:
                c.line(segments, color, 1.25 if curve.select else 1.0)
            for (index, key) in enumerate(curve.keyframe_points):
                (sx, sy) = _screen(state, plot, key.co.x, key.co.y * factor)
                if not _inside(sx, sy, plot):
                    continue
                selected = key.select_control_point
                if selected and state.handles and (key.interpolation == 'BEZIER'):
                    for side in ('left', 'right'):
                        handle = getattr(key, 'handle_' + side)
                        (hx, hy) = _screen(state, plot, handle.x, handle.y * factor)
                        clipped = _clip_line((sx, sy), (hx, hy), plot)
                        if clipped:
                            c.line(list(clipped), (0.68, 0.68, 0.68, 1))
                        if _inside(hx, hy, plot):
                            c.rect(hx - 2.3, hy - 2.3, 4.6, 4.6, (0.87, 0.87, 0.87, 1))
                            if _can_edit(obj, curve):
                                c.hit(hx - 5, hy - 5, 10, 10, _command('HANDLE', obj, curve, index, side), _msg('Tangent Handle'))
                c.rect(sx - 3, sy - 3, 6, 6, YELLOW if selected else color)
                if _can_edit(obj, curve):
                    c.hit(sx - 6, sy - 6, 12, 12, _command('KEY', obj, curve, index), _msg('Animation Key'))
    else:
        for (row, y) in visible:
            (label, depth, collapse, obj, members) = row
            if not members:
                continue
            c.line([(px, y - 4), (px + pw, y - 4)], GRID)
            frames = {}
            for curve in members:
                for key in curve.keyframe_points:
                    frames.setdefault(round(key.co.x, 5), []).append((curve, key))
            if state.ranges and frames:
                (low, high) = (min(frames), max(frames))
                (sx, _) = _screen(state, plot, low, 0)
                (ex, _) = _screen(state, plot, high, 0)
                sx = max(px, min(px + pw, sx))
                ex = max(px, min(px + pw, ex))
                c.rect(sx, y + 1, max(2, ex - sx), 7, (0.45, 0.62, 0.73, 1))
                c.rect(sx - 2, y - 1, 4, 11, YELLOW)
                c.rect(ex - 2, y - 1, 4, 11, YELLOW)
                c.hit(sx + 3, y - 3, max(1, ex - sx - 6), 17, _command('RANGE', obj, members, 'MOVE'), _msg('Move Range'))
                c.hit(sx - 5, y - 4, 10, 19, _command('RANGE', obj, members, 'LEFT'), _msg('Range Start'))
                c.hit(ex - 5, y - 4, 10, 19, _command('RANGE', obj, members, 'RIGHT'), _msg('Range End'))
            else:
                for (frame, matches) in frames.items():
                    (sx, _) = _screen(state, plot, frame, 0)
                    if px <= sx <= px + pw:
                        chosen = any((key.select_control_point for (_, key) in matches))
                        color = YELLOW if chosen else _curve_color(matches[0][0]) if collapse is None else (0.58, 0.68, 0.79, 1)
                        c.rect(sx - 3.5, y, 7, 9, color)
                        editable = tuple(((curve, key) for (curve, key) in matches if _can_edit(obj, curve)))
                        if editable:
                            c.hit(sx - 6, y - 3, 12, 15, _command('DOPE_KEYS', obj, editable), _msg('Animation Keys'))
    current = context.scene.frame_current + context.scene.frame_subframe
    (cx, _) = _screen(state, plot, current, 0)
    if px <= cx <= px + pw:
        c.line([(cx, py), (cx, py + ph)], (0.92, 0.28, 0.27, 1))
        c.rect(cx - 3, 27, 6, 20, (0.74, 0.29, 0.28, 1))
    if state.rectangle:
        (ax, ay, bx, by) = state.rectangle
        c.rect(min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay), (0.25, 0.48, 0.68, 0.15))
        c.line([(ax, ay), (bx, ay), (bx, ay), (bx, by), (bx, by), (ax, by), (ax, by), (ax, ay)], (0.55, 0.72, 0.86, 1))
    c.rect(0, 0, c.w, 25, (0.24, 0.24, 0.24, 1))
    selected = selected_keys(context, state)
    c.text(_dcc_format('{0} Keys Selected', len(selected)), 7, 8, 9, DIM)
    if selected:
        (_, curve, key) = selected[0]
        c.button(146, 4, 96, 17, _dcc_format('Time: {0:g}', key.co.x), surfaces.op('bsm.animation_key_properties'), flat=True)
        c.button(246, 4, 122, 17, _dcc_format('Value: {0:.4g}', key.co.y * _display_scale(curve)), surfaces.op('bsm.animation_key_properties'), flat=True)
    c.text(_msg('Drag keys to move  |  Ctrl: add selection  |  MMB: pan  |  Wheel: zoom'), max(390, c.w - 570), 8, 8, DIM)
    _draw_popup(c, state)

def _changed(context, objects=(), update=True):
    for obj in set(objects):
        if obj:
            obj.update_tag()
    if update:
        scene = context.scene
        scene.frame_set(scene.frame_current, subframe=scene.frame_subframe)
    runtime.redraw()

def _undo(message):
    if not bpy.app.background:
        try:
            bpy.ops.ed.undo_push(message=message)
        except RuntimeError:
            pass

def delete_selected(context, state):
    count = 0
    objects = []
    for (obj, curve) in curves(context, state):
        if not _can_edit(obj, curve):
            continue
        for key in reversed(list(curve.keyframe_points)):
            if key.select_control_point:
                curve.keyframe_points.remove(key, fast=True)
                count += 1
        curve.update()
        objects.append(obj)
    _changed(context, objects)
    if count:
        _undo(_msg('Delete Animation Keys'))
    return count

def set_interpolation(context, state, mode):
    selected = selected_keys(context, state)
    for (_, curve, key) in selected:
        key.interpolation = mode
    for curve in {curve for (_, curve, _) in selected}:
        curve.update()
    _changed(context, [o for (o, _, _) in selected])
    _undo(_msg('Set Key Interpolation'))
    return len(selected)

def set_tangent(context, state, mode):
    selected = selected_keys(context, state)
    for (_, curve, key) in selected:
        if mode == 'STEP':
            key.interpolation = 'CONSTANT'
        else:
            key.interpolation = 'BEZIER'
            key.handle_left_type = key.handle_right_type = 'FREE' if mode == 'FLAT' else mode
            if mode == 'FLAT':
                key.handle_left.y = key.handle_right.y = key.co.y
    for curve in {curve for (_, curve, _) in selected}:
        curve.update()
    _changed(context, [o for (o, _, _) in selected])
    _undo(_msg('Set Key Tangents'))
    return len(selected)

def _snapshot(entries):
    return [dict(obj=o, curve=c, key=k, co=tuple(k.co), left=tuple(k.handle_left), right=tuple(k.handle_right), left_type=k.handle_left_type, right_type=k.handle_right_type, interpolation=k.interpolation) for (o, c, k) in entries]

def _restore(snapshot):
    for item in snapshot:
        key = item['key']
        key.co = item['co']
        key.handle_left_type = item['left_type']
        key.handle_right_type = item['right_type']
        key.interpolation = item['interpolation']
        key.handle_left = item['left']
        key.handle_right = item['right']

def transform_keys(snapshot, delta_time=0.0, delta_value=0.0, time_scale=1.0, value_scale=1.0, origin_time=0.0, origin_value=0.0):
    """Transform saved coordinates; repeated moves never accumulate rounding error."""
    for item in snapshot:
        curve = item['curve']
        factor = _display_scale(curve)
        key = item['key']
        reverse = time_scale < 0
        if reverse:
            key.handle_left_type = item['right_type']
            key.handle_right_type = item['left_type']
        else:
            key.handle_left_type = item['left_type']
            key.handle_right_type = item['right_type']
        for (attr, old) in (('co', item['co']), ('handle_left', item['right'] if reverse else item['left']), ('handle_right', item['left'] if reverse else item['right'])):
            target = getattr(key, attr)
            target.x = origin_time + (old[0] - origin_time) * time_scale + delta_time
            target.y = (origin_value + (old[1] * factor - origin_value) * value_scale + delta_value) / factor

def _finish_snapshot(context, snapshot, cancel=False):
    if cancel:
        _restore(snapshot)
    for curve in {item['curve'] for item in snapshot}:
        curve.update()
    _changed(context, [item['obj'] for item in snapshot])
    if not cancel and snapshot:
        _undo(_msg('Edit Animation Keys'))

def copy_keys(context, state):
    global _clipboard
    selected = selected_keys(context, state)
    if not selected:
        _clipboard = []
        return 0
    first = min((key.co.x for (_, _, key) in selected))
    _clipboard = [dict(object=obj.name, curve=curve.data_path, index=curve.array_index, frame=key.co.x - first, value=key.co.y, interpolation=key.interpolation, left_type=key.handle_left_type, right_type=key.handle_right_type, left=(key.handle_left.x - key.co.x, key.handle_left.y - key.co.y), right=(key.handle_right.x - key.co.x, key.handle_right.y - key.co.y)) for (obj, curve, key) in selected]
    return len(_clipboard)

def paste_keys(context, state):
    if not _clipboard:
        return 0
    select_keys(context, state, 'NONE')
    count = 0
    objects = []
    changed = set()
    for item in _clipboard:
        obj = context.view_layer.objects.get(item['object'])
        if not obj or not obj.is_editable:
            continue
        curve = next((c for c in _action_fcurves(obj) if c.data_path == item['curve'] and c.array_index == item['index']), None)
        if not curve or not _can_edit(obj, curve):
            continue
        frame = context.scene.frame_current + item['frame']
        key = curve.keyframe_points.insert(frame, item['value'], options={'FAST'})
        key.interpolation = item['interpolation']
        key.handle_left_type = item['left_type']
        key.handle_right_type = item['right_type']
        key.handle_left = (frame + item['left'][0], item['value'] + item['left'][1])
        key.handle_right = (frame + item['right'][0], item['value'] + item['right'][1])
        key.select_control_point = True
        count += 1
        changed.add(curve)
        objects.append(obj)
    for curve in changed:
        curve.update()
    _changed(context, objects)
    if count:
        _undo(_msg('Paste Animation Keys'))
    return count

def _track_select(context, state, row, additive=False):
    (_, _, _, obj, members) = row
    if not additive:
        for (_, curve) in curves(context, state):
            curve.select = False
    for curve in members:
        curve.select = not curve.select if additive else True
    if members:
        state.active_curve = members[0]
        if state.auto_zoom:
            keys = [(c, k) for c in members for k in c.keyframe_points]
            if keys:
                values = [k.co.y * _display_scale(c) for (c, k) in keys]
                (low, high) = (min(values), max(values))
                pad = max(0.5, (high - low) * 0.12)
                (state.vmin, state.vmax) = (low - pad, high + pad)
    runtime.redraw()

def dispatch(context, action):
    state = state_for(context.area)
    command = action[1]
    args = action[2:]
    if command != 'MENU':
        state.popup = ''
    if command == 'MENU':
        (name, x) = args
        state.popup = '' if state.popup == name else name
        state.popup_x = x
    elif command == 'EDITOR':
        return bpy.ops.bsm.editor(kind=args[0])
    elif command == 'RETURN':
        primary = next((w for w in bpy.data.workspaces if w.get('bsm_primary_workspace')), None)
        if primary:
            context.window.workspace = primary
    elif command == 'TOOL':
        state.tool = args[0]
    elif command == 'SNAP':
        state.snap = not state.snap
    elif command == 'FILTER':
        state.selected_only = not state.selected_only
        state.scroll = 0
    elif command == 'HANDLES':
        state.handles = not state.handles
    elif command == 'AUTO_ZOOM':
        state.auto_zoom = not state.auto_zoom
    elif command == 'RANGES':
        state.ranges = args[0]
    elif command == 'FRAME_ALL':
        frame_all(context, state)
    elif command == 'FRAME_SELECTED':
        frame_all(context, state, True)
    elif command == 'FRAME_TIME':
        (vmin, vmax) = (state.vmin, state.vmax)
        frame_all(context, state, args[0])
        (state.vmin, state.vmax) = (vmin, vmax)
    elif command == 'NUDGE':
        snapshot = _snapshot(selected_keys(context, state))
        if snapshot:
            transform_keys(snapshot, delta_time=float(args[0]))
            _finish_snapshot(context, snapshot)
    elif command == 'SCROLL':
        total = len(_row_tree(context, state)) * 20
        state.scroll = min(max(0.0, state.scroll + args[0] * 45.0), max(0.0, total - 100.0))
    elif command in {'HIGHLIGHT', 'EXPAND_TOGGLE'}:
        rows = [r for r in _row_tree(context, state) if r[4]]
        current = max((i for (i, r) in enumerate(rows) if all((c.select for c in r[4]))), default=None)
        if command == 'HIGHLIGHT':
            if rows:
                index = 0 if current is None else min(len(rows) - 1, max(0, current + args[0]))
                _track_select(context, state, rows[index])
        elif current is not None:
            row = rows[current]
            if args[0] == 'OBJECT':
                row = next((r for r in rows if r[1] == 2 and r[3] == row[3]), row)
            else:
                row = next((r for r in reversed(rows[:current + 1]) if r[2] is not None and r[1] >= 3 and (r[3] == row[3])), row)
            if row[2] is not None:
                state.closed ^= {row[2]}
    elif command == 'SELECT':
        select_keys(context, state, args[0])
    elif command == 'DELETE':
        delete_selected(context, state)
    elif command == 'INTERPOLATION':
        set_interpolation(context, state, args[0])
    elif command == 'TANGENT':
        set_tangent(context, state, args[0])
    elif command == 'COPY':
        copy_keys(context, state)
    elif command == 'CUT':
        copy_keys(context, state)
        delete_selected(context, state)
    elif command == 'PASTE':
        paste_keys(context, state)
    elif command == 'EXPAND':
        state.closed.clear()
    elif command == 'COLLAPSE':
        state.closed |= {('OBJECT', o.as_pointer()) for o in _objects(context, state)}
    elif command == 'TREE':
        objects = {('OBJECT', o.as_pointer()) for o in _objects(context, state)}
        tracks = {('TRANSFORM', o.as_pointer()) for o in _objects(context, state)} | {('GROUP', o.as_pointer(), _group_name(c)) for (o, c) in curves(context, state)}
        if args[0] == 'COLLAPSE_ALL':
            state.closed |= objects | tracks
        elif args[0] == 'COLLAPSE_TRACKS':
            state.closed |= tracks
        elif args[0] == 'EXPAND_TRACKS':
            state.closed -= tracks
        elif args[0] == 'EXPAND_OBJECTS':
            state.closed -= objects
    elif command == 'TRACKS':
        listed = curves(context, state)
        if args[0] == 'CHILDREN':
            owners = {o for (o, c) in listed if c.select}
            for (o, c) in listed:
                c.select = c.select or o in owners
        else:
            for (_, c) in listed:
                c.select = {'ALL': True, 'NONE': False}.get(args[0], not c.select)
    elif command == 'ISOLATE':
        if state.isolate:
            state.isolate = set()
        else:
            chosen = {c.as_pointer() for (_, c, _) in selected_keys(context, state)}
            state.isolate = chosen or {c.as_pointer() for (_, c) in curves(context, state) if c.select}
        state.scroll = 0
    elif command == 'COLLAPSE_ROW':
        key = args[0]
        state.closed.remove(key) if key in state.closed else state.closed.add(key)
    elif command == 'TRACK':
        _track_select(context, state, args[0])
    elif command in {'MUTE', 'EXTRAPOLATION'}:
        objects = []
        for (obj, curve) in curves(context, state):
            if curve.select and _can_edit(obj, curve):
                if command == 'MUTE':
                    curve.mute = not curve.mute
                else:
                    curve.extrapolation = args[0]
                objects.append(obj)
        _changed(context, objects)
        _undo(_msg('Edit Animation Tracks'))
    elif command in {'REVERSE', 'SCALE', 'INSERT_TIME'}:
        selected = selected_keys(context, state)
        if command == 'INSERT_TIME':
            point = context.scene.frame_current
            amount = args[0]
            selected = [(o, c, k) for (o, c) in curves(context, state) if _can_edit(o, c) for k in c.keyframe_points if k.co.x >= point]
            if amount < 0:
                for (obj, curve) in curves(context, state):
                    if not _can_edit(obj, curve):
                        continue
                    for key in reversed(list(curve.keyframe_points)):
                        if point <= key.co.x < point - amount:
                            curve.keyframe_points.remove(key, fast=True)
                    curve.update()
                selected = [(o, c, k) for (o, c) in curves(context, state) if _can_edit(o, c) for k in c.keyframe_points if k.co.x >= point - amount]
            snapshot = _snapshot(selected)
            transform_keys(snapshot, delta_time=amount)
        else:
            snapshot = _snapshot(selected)
            if snapshot:
                low = min((i['co'][0] for i in snapshot))
                high = max((i['co'][0] for i in snapshot))
                if command == 'REVERSE':
                    transform_keys(snapshot, time_scale=-1.0, origin_time=(low + high) / 2)
                else:
                    transform_keys(snapshot, time_scale=args[0], origin_time=context.scene.frame_current)
        _finish_snapshot(context, snapshot)
    runtime.redraw()
    return {'FINISHED'}

def track_view_quads(context, state, keys):
    """Max's Track View quads (Default.qmnxb): Track View Key Quad in the key window and
    Track View Quad in the controller window. Items without a Blender equivalent are disabled."""
    from .quad import I, S, SEP
    run = lambda *action: lambda ctx: dispatch(ctx, _command(*action))
    empty = ('', [])
    if keys:
        return {'TL': empty, 'TR': empty, 'BL': empty, 'BR': (_msg('track view'), [I(_msg('Move Keys'), call=run('TOOL', 'MOVE')), I(_msg('Add/Remove Keys'), call=run('TOOL', 'ADD')), I(_msg('Isolate Curve'), call=run('ISOLATE')), SEP, I(_msg('Auto'), call=run('TANGENT', 'AUTO')), I(_msg('Spline'), call=run('TANGENT', 'ALIGNED')), I(_msg('Linear'), call=run('TANGENT', 'VECTOR')), I(_msg('Stepped'), call=run('TANGENT', 'STEP')), SEP, I(_msg('Break Tangents'), call=run('TANGENT', 'FREE')), I(_msg('Unify Tangents'), call=run('TANGENT', 'ALIGNED'))])}
    selected = any((c.select for (_, c) in curves(context, state)))
    return {'TL': ('', [I(_msg('Select Children'), call=run('TRACKS', 'CHILDREN'), enabled=selected), SEP, I(_msg('Select None'), call=run('TRACKS', 'NONE')), I(_msg('Select Invert'), call=run('TRACKS', 'INVERT')), I(_msg('Select All'), call=run('TRACKS', 'ALL')), SEP, I(_msg('Override All Locks')), SEP, I(_msg('Conceal')), I(_msg('Expose')), I(_msg('Unlock Leaves')), I(_msg('Unlock')), I(_msg('Lock'))]), 'TR': ('', [I(_msg('Manual Navigation')), S(_msg('Auto Expand'), [I(_msg('Children')), SEP, I(_msg('Materials')), I(_msg('Modifiers')), I(_msg('Base Objects')), SEP, I(_msg('Animated')), I(_msg('Keyable')), SEP, I(_msg('Limits')), I(_msg('XYZ Components')), I(_msg('Transforms')), SEP, I(_msg('Selected Objects Only'))]), SEP, I(_msg('Collapse All'), call=run('TREE', 'COLLAPSE_ALL')), I(_msg('Collapse Tracks'), call=run('TREE', 'COLLAPSE_TRACKS')), I(_msg('Collapse Objects'), call=run('COLLAPSE')), I(_msg('Expand All'), call=run('EXPAND')), I(_msg('Expand Tracks'), call=run('TREE', 'EXPAND_TRACKS')), I(_msg('Expand Objects'), call=run('TREE', 'EXPAND_OBJECTS'))]), 'BR': ('controllers', [I(_msg('Properties...'), 'bsm.animation_key_properties'), SEP, I(_msg('Assign Controller...')), SEP, I(_msg('Add/Edit Parameters...')), I(_msg('View Attribute Dialog...')), I(_msg('Collect Parameters')), I(_msg('Publish Parameters...')), SEP, I(_msg('Copy')), I(_msg('Paste...')), I(_msg('Make Unique')), SEP, S(_msg('Limit Controller:'), [I(_msg('Toggle Limit')), SEP, I(_msg('Set Upper Limit')), I(_msg('Set Lower Limit')), I(_msg('Remove Limit')), I(_msg('Copy Limit Only')), I(_msg('Paste Limit Only'))]), SEP, S(_msg('XRef Tracks State'), [I(_msg('Use XRefed')), I(_msg('Use Local'))])]), 'BL': ('animation', [I(_msg('Load Animation...')), I(_msg('Save Animation...'))])}

def _start_drag(context, event, area, region, state, x, y, kind, snapshot=(), **values):
    global _drag
    _drag = dict(window=context.window.as_pointer(), area=area, region=region, state=state, x=x, y=y, kind=kind, snapshot=list(snapshot), plot=_plot(state, region.width / surfaces.scale(), region.height / surfaces.scale()), view=(state.tmin, state.tmax, state.vmin, state.vmax), **values)

def active_event(context, event):
    """Consume an active cross-boundary gesture, or return None when idle."""
    global _drag
    d = _drag
    if d is None or d['window'] != context.window.as_pointer():
        return None
    state = d['state']
    u = surfaces.scale()
    region = d['region']
    x = (event.mouse_x - region.x) / u
    y = (event.mouse_y - region.y) / u
    if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
        if d['kind'] not in {'PAN', 'ZOOM', 'BOX', 'ZOOM_BOX', 'SCRUB'}:
            _finish_snapshot(context, d['snapshot'], True)
        (state.tmin, state.tmax, state.vmin, state.vmax) = d['view']
        state.rectangle = None
        _drag = None
        runtime.redraw()
        return {'RUNNING_MODAL'}
    if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE'} and event.value == 'RELEASE':
        if d['kind'] == 'BOX':
            (ax, ay) = (d['x'], d['y'])
            bounds = (min(ax, x), min(ay, y), abs(x - ax), abs(y - ay))
            if not d['additive']:
                select_keys(context, state, 'NONE')
            if state.kind == _msg('Curve'):
                for (obj, curve) in curves(context, state):
                    if not _can_edit(obj, curve):
                        continue
                    for key in curve.keyframe_points:
                        if _inside(*_screen(state, d['plot'], key.co.x, key.co.y * _display_scale(curve)), bounds):
                            key.select_control_point = True
            else:
                top = region.height / u - 129 + state.scroll
                for (i, row) in enumerate(_row_tree(context, state)):
                    ry = top - i * 20 + 4
                    if bounds[1] <= ry <= bounds[1] + bounds[3]:
                        for curve in row[4]:
                            if not _can_edit(row[3], curve):
                                continue
                            for key in curve.keyframe_points:
                                (sx, _) = _screen(state, d['plot'], key.co.x, 0)
                                if bounds[0] <= sx <= bounds[0] + bounds[2]:
                                    key.select_control_point = True
        elif d['kind'] == 'ZOOM_BOX':
            if abs(x - d['x']) > 3 and abs(y - d['y']) > 3:
                ((ta, va), (tb, vb)) = (_values(state, d['plot'], d['x'], d['y']), _values(state, d['plot'], x, y))
                (state.tmin, state.tmax) = (min(ta, tb), max(ta, tb))
                if state.kind == _msg('Curve'):
                    (state.vmin, state.vmax) = (min(va, vb), max(va, vb))
        elif d['kind'] not in {'PAN', 'ZOOM', 'SCRUB'}:
            _finish_snapshot(context, d['snapshot'])
        state.rectangle = None
        _drag = None
        runtime.redraw()
        return {'RUNNING_MODAL'}
    if event.type != 'MOUSEMOVE':
        return {'RUNNING_MODAL'}
    (px, py, pw, ph) = d['plot']
    (t0, t1, v0, v1) = d['view']
    dt = (x - d['x']) / pw * (t1 - t0)
    dv = (y - d['y']) / ph * (v1 - v0)
    if state.snap and (not event.alt):
        dt = round(dt)
    kind = d['kind']
    if kind == 'PAN':
        state.tmin = t0 - (x - d['x']) / pw * (t1 - t0)
        state.tmax = t1 - (x - d['x']) / pw * (t1 - t0)
        if state.kind == _msg('Curve'):
            state.vmin = v0 - dv
            state.vmax = v1 - dv
    elif kind == 'ZOOM':
        amount = max(0.05, min(20.0, math.exp((d['x'] - x + d['y'] - y) * 0.006)))
        tc = (t0 + t1) / 2
        vc = (v0 + v1) / 2
        state.tmin = tc - (t1 - t0) * amount / 2
        state.tmax = tc + (t1 - t0) * amount / 2
        state.vmin = vc - (v1 - v0) * amount / 2
        state.vmax = vc + (v1 - v0) * amount / 2
    elif kind in {'BOX', 'ZOOM_BOX'}:
        state.rectangle = (d['x'], d['y'], x, y)
    elif kind == 'SCRUB':
        (frame, _) = _values(state, d['plot'], x, y)
        context.scene.frame_set(round(frame))
    elif kind == 'HANDLE':
        item = d['snapshot'][0]
        key = item['key']
        side = d['side']
        key.handle_left_type = key.handle_right_type = 'FREE'
        old = item['left' if side == 'left' else 'right']
        factor = _display_scale(item['curve'])
        getattr(key, 'handle_' + side).xy = (old[0] + dt, old[1] + dv / factor)
        _changed(context, [item['obj']])
    elif kind == 'SCALE_TIME':
        origin = d.get('origin', context.scene.frame_current)
        anchor = d.get('anchor', origin + 1.0)
        amount = (anchor + dt - origin) / max(1e-09, anchor - origin) if anchor >= origin else (anchor + dt - origin) / min(-1e-09, anchor - origin)
        transform_keys(d['snapshot'], time_scale=amount, origin_time=origin)
        _changed(context, [i['obj'] for i in d['snapshot']])
    elif kind == 'SCALE_VALUE':
        amount = max(0.001, 1.0 + (y - d['y']) / 100.0)
        transform_keys(d['snapshot'], value_scale=amount)
        _changed(context, [i['obj'] for i in d['snapshot']])
    else:
        horizontal = state.tool != 'VALUE'
        vertical = state.kind == _msg('Curve') and state.tool not in {'TIME', 'RANGES'}
        transform_keys(d['snapshot'], delta_time=dt if horizontal else 0.0, delta_value=dv if vertical else 0.0)
        _changed(context, [i['obj'] for i in d['snapshot']])
    runtime.redraw()
    return {'RUNNING_MODAL'}
(_C, _A, _S) = ({'ctrl': True}, {'alt': True}, {'shift': True})
TRACK_VIEW_KEYS = (('K', _msg('Add/Remove Keys'), 'K', {}, ('TOOL', 'ADD'), '1-280'), ('M', _msg('Move Keys'), 'M', {}, ('TOOL', 'MOVE'), '1-2020'), (_msg('Ctrl+A'), _msg('Select All'), 'A', _C, ('SELECT', 'ALL'), '1-720'), (_msg('Ctrl+D'), _msg('Select None'), 'D', _C, ('SELECT', 'NONE'), '1-722'), (_msg('Ctrl+I'), _msg('Select Invert'), 'I', _C, ('SELECT', 'INVERT'), '1-721'), (_msg('Shift+Page Down'), _msg('Select Children'), 'PAGE_DOWN', _S, ('TRACKS', 'CHILDREN'), '1-723'), ('Z', _msg('Frame Horizontal and Value Extents'), 'Z', {}, ('FRAME_ALL',), '1-1130'), (_msg('Ctrl+Alt+Z'), _msg('Frame Horizontal Extents'), 'Z', {'ctrl': True, 'alt': True}, ('FRAME_TIME', False), '1-2180'), (_msg('Ctrl+Alt+Shift+Z'), _msg('Frame Horizontal Extents Keys'), 'Z', {'ctrl': True, 'alt': True, 'shift': True}, ('FRAME_TIME', True), '1-2190'), (_msg('Alt+Z'), _msg('Zoom'), 'Z', _A, ('TOOL', 'ZOOM'), '1-2200'), (_msg('Ctrl+W'), _msg('Zoom Region'), 'W', _C, ('TOOL', 'ZOOM_REGION'), '1-1020'), (_msg('Ctrl+P'), _msg('Pan'), 'P', _C, ('TOOL', 'PAN'), '1-1030'), (_msg('Left'), _msg('Nudge Keys Left'), 'LEFT_ARROW', {}, ('NUDGE', -1), '1-40329'), (_msg('Right'), _msg('Nudge Keys Right'), 'RIGHT_ARROW', {}, ('NUDGE', 1), '1-40330'), (_msg('Up'), _msg('Move Highlight Up'), 'UP_ARROW', {}, ('HIGHLIGHT', -1), '1-40331'), (_msg('Down'), _msg('Move Highlight Down'), 'DOWN_ARROW', {}, ('HIGHLIGHT', 1), '1-40332'), (_msg('Ctrl+Up'), _msg('Scroll Up'), 'UP_ARROW', _C, ('SCROLL', -1), '1-40335'), (_msg('Ctrl+Down'), _msg('Scroll Down'), 'DOWN_ARROW', _C, ('SCROLL', 1), '1-40336'), ('T', _msg('Expand Track Toggle'), 'T', {}, ('EXPAND_TOGGLE', 'TRACK'), '1-40333'), (_msg('Enter'), _msg('Expand Track Toggle'), 'RET', {}, ('EXPAND_TOGGLE', 'TRACK'), '1-40333'), ('O', _msg('Expand Object Toggle'), 'O', {}, ('EXPAND_TOGGLE', 'OBJECT'), '1-40334'), ('S', _msg('Snap Frames'), 'S', {}, ('SNAP',), '1-2000'), (_msg('Alt+F'), _msg('Filters'), 'F', _A, ('FILTER',), '1-330'), (_msg('Ctrl+C'), _msg('Copy (keys)'), 'C', _C, ('COPY',), '1-610'), (_msg('Ctrl+V'), _msg('Paste (keys)'), 'V', _C, ('PASTE',), '1-620'), (_msg('Delete'), _msg('Delete Keys'), 'DEL', {}, ('DELETE',), _msg('Track View Delete')))

def handle_event(context, event, area, region, x, y):
    state = state_for(area)
    plot = _plot(state, region.width / surfaces.scale(), region.height / surfaces.scale())
    if event.type == 'MOUSEMOVE':
        return None
    if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
        direction = 1 if event.type == 'WHEELUPMOUSE' else -1
        if x < plot[0] - 2:
            state.scroll = max(0.0, state.scroll - direction * 45.0)
            total = len(_row_tree(context, state)) * 20
            state.scroll = min(state.scroll, max(0, total - (region.height / surfaces.scale() - 165)))
        else:
            (anchor_t, anchor_v) = _values(state, plot, x, y)
            factor = 0.84 if direction > 0 else 1.0 / 0.84
            state.tmin = anchor_t + (state.tmin - anchor_t) * factor
            state.tmax = anchor_t + (state.tmax - anchor_t) * factor
            if state.kind == _msg('Curve') and (not event.ctrl):
                state.vmin = anchor_v + (state.vmin - anchor_v) * factor
                state.vmax = anchor_v + (state.vmax - anchor_v) * factor
        runtime.redraw()
        return {'RUNNING_MODAL'}
    if event.value != 'PRESS':
        return None
    if event.type == 'MIDDLEMOUSE' and _inside(x, y, plot):
        _start_drag(context, event, area, region, state, x, y, 'PAN')
        return {'RUNNING_MODAL'}
    from .keymap import match
    row = match(TRACK_VIEW_KEYS, event)
    if row:
        with context.temp_override(area=area, region=region):
            dispatch(context, ('ANIM',) + row[4])
        runtime.redraw()
        return {'RUNNING_MODAL'}
    if event.type == 'X' and (not (event.ctrl or event.alt or event.shift)):
        delete_selected(context, state)
        return {'RUNNING_MODAL'}
    if event.type == 'F':
        frame_all(context, state, event.ctrl)
        runtime.redraw()
        return {'RUNNING_MODAL'}
    if event.type == 'RIGHTMOUSE':
        state.popup = ''
        left = min(state.left, max(135.0, region.width / surfaces.scale() * 0.4))
        if not plot[1] <= y <= plot[1] + plot[3]:
            runtime.redraw()
            return {'RUNNING_MODAL'}
        keys = x >= left
        if not keys:
            hit = surfaces.lookup(area, x, y)
            if hit and hit[4][:2] == ('ANIM', 'TRACK') and (not any((c.select for c in hit[4][2][4]))):
                _track_select(context, state, hit[4][2])
        from . import quad
        quad.open_menu(context, event, track_view_quads(context, state, keys), _msg('track view key') if keys else _msg('track view'))
        return {'RUNNING_MODAL'}
    if event.type != 'LEFTMOUSE':
        return None
    hit = surfaces.lookup(area, x, y)
    if hit and hit[4][0] == 'ANIM':
        action = hit[4]
        command = action[1]
        args = action[2:]
        state.popup = '' if command != 'MENU' else state.popup
        if command == 'TRACK':
            _track_select(context, state, args[0], event.ctrl)
            return {'RUNNING_MODAL'}
        if command in {'KEY', 'HANDLE', 'DOPE_KEYS', 'RANGE'}:
            entries = []
            if command in {'KEY', 'HANDLE'}:
                (obj, curve, index, *extra) = args
                if index >= len(curve.keyframe_points) or not _can_edit(obj, curve):
                    return {'RUNNING_MODAL'}
                key = curve.keyframe_points[index]
                entries = [(obj, curve, key)]
                state.active_curve = curve
            elif command == 'DOPE_KEYS':
                (obj, matches) = args
                entries = [(obj, c, k) for (c, k) in matches]
            else:
                (obj, members, edge) = args
                entries = [(obj, c, k) for c in members if _can_edit(obj, c) for k in c.keyframe_points]
            if command != 'HANDLE':
                all_selected = all((k.select_control_point for (_, _, k) in entries))
                if not event.ctrl and (not all_selected):
                    select_keys(context, state, 'NONE')
                for (_, _, key) in entries:
                    key.select_control_point = not key.select_control_point if event.ctrl else True
                if event.ctrl and all_selected:
                    runtime.redraw()
                    return {'RUNNING_MODAL'}
            selected = entries if command == 'HANDLE' else selected_keys(context, state)
            snapshot = _snapshot(selected)
            mode = 'HANDLE' if command == 'HANDLE' else state.tool if state.tool in {'SCALE_TIME', 'SCALE_VALUE'} else 'KEYS'
            values = {}
            if command == 'HANDLE':
                values['side'] = extra[0]
            if command == 'RANGE' and edge != 'MOVE' and entries:
                low = min((k.co.x for (_, _, k) in entries))
                high = max((k.co.x for (_, _, k) in entries))
                values.update(origin=high if edge == 'LEFT' else low, anchor=low if edge == 'LEFT' else high)
                mode = 'SCALE_TIME'
            if mode == 'SCALE_TIME' and 'anchor' not in values:
                values['anchor'] = _values(state, plot, x, y)[0]
            _start_drag(context, event, area, region, state, x, y, mode, snapshot, **values)
            runtime.redraw()
            return {'RUNNING_MODAL'}
        with context.temp_override(area=area, region=region):
            dispatch(context, action)
        return {'RUNNING_MODAL'}
    if state.popup:
        state.popup = ''
        runtime.redraw()
        return {'RUNNING_MODAL'}
    if 27 <= y < 49 and x >= plot[0]:
        (frame, _) = _values(state, plot, x, y)
        context.scene.frame_set(round(frame))
        _start_drag(context, event, area, region, state, x, y, 'SCRUB')
        return {'RUNNING_MODAL'}
    if not _inside(x, y, plot):
        return None
    if state.tool in {'PAN', 'ZOOM'}:
        _start_drag(context, event, area, region, state, x, y, state.tool)
        return {'RUNNING_MODAL'}
    if state.tool == 'ZOOM_REGION':
        _start_drag(context, event, area, region, state, x, y, 'ZOOM_BOX')
        return {'RUNNING_MODAL'}
    if state.tool == 'ADD':
        (frame, value) = _values(state, plot, x, y)
        if state.snap and (not event.alt):
            frame = round(frame)
        targets = []
        if state.kind == _msg('Dope'):
            i = int((region.height / surfaces.scale() - 129 + state.scroll - y + 9) / 20)
            rows = _row_tree(context, state)
            if 0 <= i < len(rows):
                targets = list(rows[i][4])
        elif state.active_curve:
            targets = [state.active_curve]
        else:
            targets = [c for (_, c) in curves(context, state) if c.select][:1]
        select_keys(context, state, 'NONE')
        writable = {c for (o, c) in curves(context, state) if _can_edit(o, c)}
        for curve in targets:
            if curve not in writable:
                continue
            val = value / _display_scale(curve) if state.kind == _msg('Curve') else curve.evaluate(frame)
            key = curve.keyframe_points.insert(frame, val, options={'FAST'})
            key.select_control_point = True
            curve.update()
        _changed(context, [o for (o, c) in curves(context, state) if c in targets])
        _undo(_msg('Add Animation Keys'))
        return {'RUNNING_MODAL'}
    _start_drag(context, event, area, region, state, x, y, 'BOX', additive=event.ctrl)
    return {'RUNNING_MODAL'}

class BSM_OT_animation_key_properties(bpy.types.Operator):
    bl_idname = 'bsm.animation_key_properties'
    bl_label = _msg('Key Properties')
    bl_options = {'REGISTER', 'UNDO'}
    time: FloatProperty(name=_msg('Time'), precision=3, translation_context=_msg('DCCWorkflowKit.Max'))
    value: FloatProperty(name=_msg('Value'), precision=4, translation_context=_msg('DCCWorkflowKit.Max'))
    _entries = None
    _initial_time = 0.0
    _initial_value = 0.0

    @classmethod
    def poll(cls, context):
        return runtime.is_active() and context.area is not None

    def invoke(self, context, event):
        state = state_for(context.area)
        entries = selected_keys(context, state)
        if not entries:
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select one or more animation keys')))
            return {'CANCELLED'}
        self._entries = _snapshot(entries)
        (_, curve, key) = entries[0]
        self.time = self._initial_time = key.co.x
        self.value = self._initial_value = key.co.y * _display_scale(curve)
        return context.window_manager.invoke_props_dialog(self, width=310)

    def draw(self, context):
        self.layout.prop(self, 'time')
        self.layout.prop(self, 'value')
        self.layout.label(text=_dcc_ui_text(_msg('Changes offset all selected keys.')))

    def execute(self, context):
        if not self._entries:
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select keys and open Key Properties')))
            return {'CANCELLED'}
        transform_keys(self._entries, delta_time=self.time - self._initial_time, delta_value=self.value - self._initial_value)
        _finish_snapshot(context, self._entries)
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def clear():
    global _drag, _clipboard
    if _drag and _drag.get('snapshot'):
        try:
            _restore(_drag['snapshot'])
            for item in _drag['snapshot']:
                item['curve'].update()
        except (ReferenceError, RuntimeError):
            pass
    _drag = None
    _clipboard = []
    _states.clear()
CLASSES = (BSM_OT_animation_key_properties,)
