# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format, error_text as _dcc_ui_error
"Render Setup and Edit UVWs surfaces backed by Blender scene and mesh data.\n\nThe interface is independently implemented from documented control placement\nand behavior. No application artwork, renderer, or proprietary modifier is\nbundled. Blender's render engines and UV algorithms keep their actual names.\n"
from contextlib import contextmanager
from math import atan2, ceil, cos, floor, hypot, log10, pi, sin
import os
import bpy
import bmesh
from bpy.props import BoolProperty, IntProperty, StringProperty
from . import runtime, surfaces
_views = {}
_gestures = {}
_render = {'tab': _msg('Common'), 'time': 'SINGLE', 'write_still': False, 'scroll': 0.0, 'content': 0.0}
_notices = {}
BG = (0.265, 0.265, 0.265, 1)
TEXT = (0.8, 0.8, 0.8, 1)
DIM = (0.61, 0.61, 0.61, 1)
ORANGE = (1.0, 0.63, 0.13, 1)
GREEN = (0.3, 0.77, 0.34, 1)

def action(name, *args):
    return ('UTIL', name, *args)

def _notice(context, text):
    if context.area:
        _notices[context.area.as_pointer()] = str(text)
    runtime.redraw()

def _state(area):
    return _views.setdefault(area.as_pointer(), {'center': (0.5, 0.5), 'scale': None, 'mode': 'VERTEX', 'tool': 'MOVE', 'checker': True, 'selected_only': False, 'rect': (8.0, 56.0, 500.0, 400.0)})

def active_mesh(context):
    obj = context.view_layer.objects.active
    if obj and obj.type == 'MESH' and obj.is_editable and obj.data.is_editable and (obj.mode in {'OBJECT', 'EDIT'}):
        return obj
    return None

class UVAccess:
    """An ephemeral adapter over real loop UVs, including Blender 5 selection.

    Each key is (polygon index, polygon corner). No RNA/BMesh reference is
    retained across topology changes, mode changes, redraws, or undo steps.
    """

    def __init__(self, obj, create=False):
        if obj is None or obj.type != 'MESH':
            raise ValueError(_msg('Select an editable mesh object'))
        self.obj = obj
        self.mesh = obj.data
        self.edit = obj.mode == 'EDIT'
        self.bm = bmesh.from_edit_mesh(self.mesh) if self.edit else None
        self.items = {}
        self.faces = {}
        self.corners = {}
        self.uv = None
        if self.edit:
            self.bm.faces.ensure_lookup_table()
            self.bm.faces.index_update()
            self.uv = self.bm.loops.layers.uv.active
            if self.uv is None and create:
                self.uv = self.bm.loops.layers.uv.new(_msg('UVMap'))
            if self.uv is not None:
                for face in self.bm.faces:
                    self.faces[face.index] = face
                    self.corners[face.index] = []
                    for (corner, loop) in enumerate(face.loops):
                        self.items[face.index, corner] = loop
                        self.corners[face.index].append((face.index, corner))
        else:
            self.uv = self.mesh.uv_layers.active
            if self.uv is None and create:
                self.uv = self.mesh.uv_layers.new(name=_msg('UVMap'))
            if self.uv is not None:
                for face in self.mesh.polygons:
                    self.faces[face.index] = face
                    self.corners[face.index] = []
                    for (corner, index) in enumerate(face.loop_indices):
                        self.items[face.index, corner] = index
                        self.corners[face.index].append((face.index, corner))

    def co(self, key):
        value = self.items[key]
        return tuple(value[self.uv].uv) if self.edit else tuple(self.uv.data[value].uv)

    def set_co(self, key, co):
        value = self.items[key]
        if self.edit:
            value[self.uv].uv = co
        else:
            self.uv.data[value].uv = co

    def _attribute(self, name, domain, create=False):
        attr = self.mesh.attributes.get(name)
        if attr is None and create:
            attr = self.mesh.attributes.new(name=name, type='BOOLEAN', domain=domain)
        return attr

    def selected(self, key):
        loop = self.items[key]
        if self.edit:
            if hasattr(loop, 'uv_select_vert'):
                return loop.uv_select_vert
            return loop[self.uv].select
        attr = self._attribute('.uv_select_vert', 'CORNER')
        if attr is not None:
            return attr.data[loop].value
        return getattr(self.uv.data[loop], 'select', False)

    def set_selected(self, key, value):
        loop = self.items[key]
        if self.edit:
            if hasattr(loop, 'uv_select_vert_set'):
                loop.uv_select_vert = value
            else:
                loop[self.uv].select = value
        elif hasattr(self.uv.data[loop], 'select'):
            self.uv.data[loop].select = value
        else:
            self._attribute('.uv_select_vert', 'CORNER', True).data[loop].value = value

    def set_edge_selected(self, key, value):
        loop = self.items[key]
        if self.edit:
            if hasattr(loop, 'uv_select_edge_set'):
                loop.uv_select_edge = value
            else:
                loop[self.uv].select_edge = value
        elif hasattr(self.uv.data[loop], 'select_edge'):
            self.uv.data[loop].select_edge = value
        else:
            self._attribute('.uv_select_edge', 'CORNER', True).data[loop].value = value

    def set_face_selected(self, index, value, mesh=False):
        face = self.faces[index]
        if self.edit:
            if hasattr(face, 'uv_select_set'):
                face.uv_select = value
            if mesh:
                face.select_set(value)
        else:
            self._attribute('.uv_select_face', 'FACE', True).data[index].value = value
            if mesh:
                face.select = value

    def face_selected(self, index):
        face = self.faces[index]
        if self.edit:
            return face.uv_select if hasattr(face, 'uv_select') else face.select
        attr = self._attribute('.uv_select_face', 'FACE')
        return attr.data[index].value if attr else face.select

    def base_face_selected(self, index):
        return self.faces[index].select

    def pinned(self, key):
        value = self.items[key]
        return value[self.uv].pin_uv if self.edit else self.uv.data[value].pin_uv

    def set_pinned(self, key, value):
        item = self.items[key]
        if self.edit:
            item[self.uv].pin_uv = value
        else:
            self.uv.data[item].pin_uv = value

    def vertex_index(self, key):
        item = self.items[key]
        return item.vert.index if self.edit else self.mesh.loops[item].vertex_index

    def face_keys(self, index):
        return self.corners.get(index, [])

    def update(self):
        if self.edit:
            bmesh.update_edit_mesh(self.mesh, loop_triangles=False, destructive=False)
        else:
            self.mesh.update()

    def signature(self):
        return (self.mesh.as_pointer(), len(self.items), tuple((len(self.face_keys(index)) for index in self.faces)))

def selection(obj):
    data = UVAccess(obj)
    return {key for key in data.items if data.selected(key)}

def select_keys(obj, keys, replace=True, toggle=False, subtract=False, sync_faces=False):
    """Write loop/edge/face UV selection, optionally syncing mesh polygons."""
    data = UVAccess(obj)
    keys = set(keys)
    for key in data.items:
        old = data.selected(key)
        value = (not old if toggle else not subtract) if key in keys else False if replace else old
        data.set_selected(key, value)
    for index in data.faces:
        corners = data.face_keys(index)
        face_selected = bool(corners) and all((data.selected(key) for key in corners))
        data.set_face_selected(index, face_selected, mesh=sync_faces)
        for (i, key) in enumerate(corners):
            data.set_edge_selected(key, data.selected(key) and data.selected(corners[(i + 1) % len(corners)]))
    data.update()

def uv_snapshot(obj, keys=None):
    data = UVAccess(obj)
    return {key: data.co(key) for key in (data.items if keys is None else keys) if key in data.items}

def apply_uv_snapshot(obj, values):
    data = UVAccess(obj)
    if not set(values).issubset(data.items):
        raise ValueError(_msg('The mesh topology changed during the UV edit'))
    for (key, co) in values.items():
        data.set_co(key, co)
    data.update()

def transform_uv(obj, values, *, offset=(0.0, 0.0), rotation=0.0, scale=(1.0, 1.0), pivot=None):
    """Apply a transform from a baseline, so repeated mouse updates do not drift."""
    if not values:
        return
    if pivot is None:
        pivot = tuple((sum((co[i] for co in values.values())) / len(values) for i in (0, 1)))
    (c, s) = (cos(rotation), sin(rotation))
    result = {}
    for (key, co) in values.items():
        (u, v) = ((co[i] - pivot[i]) * scale[i] for i in (0, 1))
        result[key] = (pivot[0] + u * c - v * s + offset[0], pivot[1] + u * s + v * c + offset[1])
    apply_uv_snapshot(obj, result)

def _undo(message):
    if not bpy.app.background and bpy.ops.ed.undo_push.poll():
        bpy.ops.ed.undo_push(message=message)

@contextmanager
def _uv_operator_context(context, obj):
    """Use a real viewport; temporarily supply one in an editor-only window.

    The caller's active object, object selection, object/edit mode, UV sync,
    area type and image marker are restored even when an operator raises.
    """
    old_active = context.view_layer.objects.active
    old_selected = [o for o in context.view_layer.objects if o.select_get()]
    old_mode = obj.mode
    old_sync = context.scene.tool_settings.use_uv_select_sync
    if old_active and old_active.mode != 'OBJECT' and (old_active != obj):
        raise RuntimeError(_msg('Finish editing the other object before editing these UVs'))
    area = next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None)
    temporary = area is None
    if area is None:
        area = context.area
    if area is None:
        raise RuntimeError(_msg('No editor area is available for UV operations'))
    (previous_type, previous_ui) = (area.type, area.ui_type)
    previous_image = getattr(area.spaces.active, 'image', None)
    previous_header = getattr(area.spaces.active, 'show_region_header', True)
    try:
        if temporary:
            area.type = 'VIEW_3D'
        region = next((r for r in area.regions if r.type == 'WINDOW'))
        with context.temp_override(window=context.window, area=area, region=region):
            if obj.mode != 'EDIT':
                for other in context.view_layer.objects:
                    other.select_set(False)
                obj.select_set(True)
                context.view_layer.objects.active = obj
                bpy.ops.object.mode_set(mode='EDIT')
            context.scene.tool_settings.use_uv_select_sync = False
            yield
    finally:
        try:
            context.scene.tool_settings.use_uv_select_sync = old_sync
            if obj.mode != old_mode:
                region = next((r for r in area.regions if r.type == 'WINDOW'))
                with context.temp_override(window=context.window, area=area, region=region):
                    bpy.ops.object.mode_set(mode=old_mode)
            if old_mode == 'OBJECT':
                for other in context.view_layer.objects:
                    other.select_set(other in old_selected)
                context.view_layer.objects.active = old_active
        finally:
            if temporary:
                area.type = previous_type
                area.ui_type = previous_ui
                if hasattr(area.spaces.active, 'image'):
                    area.spaces.active.image = previous_image
                if hasattr(area.spaces.active, 'show_region_header'):
                    area.spaces.active.show_region_header = previous_header

def uv_operator(context, name):
    obj = active_mesh(context)
    if obj is None:
        raise ValueError(_msg('Select an editable mesh object'))
    UVAccess(obj, create=True).update()
    original_data = UVAccess(obj)
    base = {i: f.select for (i, f) in original_data.faces.items()}
    vertices = original_data.bm.verts if original_data.edit else obj.data.vertices
    edges = original_data.bm.edges if original_data.edit else obj.data.edges
    base_vertices = [v.select for v in vertices]
    base_edges = [edge.select for edge in edges]
    selected_uvs = {key for key in original_data.items if original_data.selected(key)}
    if name == 'WELD' and (not selected_uvs):
        raise ValueError(_msg('Select the texture vertices to weld'))
    targets = {key[0] for key in selected_uvs} or {i for (i, selected) in base.items() if selected} or set(base)
    if not targets:
        raise ValueError(_msg('The mesh has no polygon faces to map'))
    with _uv_operator_context(context, obj):
        data = UVAccess(obj)
        for (index, face) in data.faces.items():
            face.select_set(index in targets if name in {'UNWRAP', 'SMART'} else True)
        if not selected_uvs:
            for key in data.items:
                data.set_selected(key, key[0] in targets)
        data.update()
        try:
            if name == 'UNWRAP':
                result = bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0.001)
            elif name == 'SMART':
                result = bpy.ops.uv.smart_project(island_margin=0.02)
            elif name == 'PACK':
                result = bpy.ops.uv.pack_islands(rotate=True, margin=0.02)
            elif name == 'AVERAGE':
                result = bpy.ops.uv.average_islands_scale()
            elif name == 'WELD':
                result = bpy.ops.uv.weld()
            else:
                raise ValueError(_msg('Unknown UV operation: ') + name)
            if result != {'FINISHED'}:
                raise RuntimeError(_msg('The UV operation was cancelled by Blender'))
        finally:
            data = UVAccess(obj)
            for (index, face) in data.faces.items():
                face.select = base.get(index, False)
            for (vert, selected) in zip(data.bm.verts, base_vertices):
                vert.select = selected
            for (edge, selected) in zip(data.bm.edges, base_edges):
                edge.select = selected
            data.update()
    _undo(_msg('Edit UVWs ') + name.title())
    runtime.redraw()
    return {'FINISHED'}

def _screen(co, view):
    (x, y, w, h) = view['rect']
    return (x + w * 0.5 + (co[0] - view['center'][0]) * view['scale'], y + h * 0.5 + (co[1] - view['center'][1]) * view['scale'])

def _uv(point, view):
    (x, y, w, h) = view['rect']
    return (view['center'][0] + (point[0] - x - w * 0.5) / view['scale'], view['center'][1] + (point[1] - y - h * 0.5) / view['scale'])

def fit_uv(context, selected=False):
    state = _state(context.area)
    obj = active_mesh(context)
    values = uv_snapshot(obj, selection(obj) if selected else None) if obj else {}
    if not values:
        values = {0: (0.0, 0.0), 1: (1.0, 1.0)}
    low = [min((co[i] for co in values.values())) for i in (0, 1)]
    high = [max((co[i] for co in values.values())) for i in (0, 1)]
    state['center'] = tuple(((a + b) * 0.5 for (a, b) in zip(low, high)))
    state['scale'] = max(4.0, min(state['rect'][2] / max(0.1, high[0] - low[0]), state['rect'][3] / max(0.1, high[1] - low[1])) * 0.82)

def _inside(point, rect):
    (x, y, w, h) = rect
    return x <= point[0] <= x + w and y <= point[1] <= y + h

def _clip_segment(a, b, rect):
    """Liang-Barsky clipping avoids drawing UVs into surrounding controls."""
    (x, y, w, h) = rect
    (dx, dy) = (b[0] - a[0], b[1] - a[1])
    (low, high) = (0.0, 1.0)
    for (p, q) in ((-dx, a[0] - x), (dx, x + w - a[0]), (-dy, a[1] - y), (dy, y + h - a[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return None
        else:
            t = q / p
            if p < 0:
                low = max(low, t)
            else:
                high = min(high, t)
            if low > high:
                return None
    return ((a[0] + low * dx, a[1] + low * dy), (a[0] + high * dx, a[1] + high * dy))

def _line(c, a, b, rect, color, width=1):
    points = _clip_segment(a, b, rect)
    if points:
        c.line(points, color, width)

def _rect_outline(c, rect, color, width=1):
    (x, y, w, h) = rect
    for (a, b) in (((x, y), (x + w, y)), ((x + w, y), (x + w, y + h)), ((x + w, y + h), (x, y + h)), ((x, y + h), (x, y))):
        c.line((a, b), color, width)

def _uv_draw(context):
    c = surfaces.Canvas(context)
    view = _state(context.area)
    c.rect(0, 0, c.w, c.h, BG)
    c.text(_msg('Edit UVWs'), 10, c.h - 18, 12, bold=True)
    menu_x = 7
    for (label, menu_name, width) in ((_msg('Edit'), 'edit', 35), (_msg('Select'), 'select', 47), (_msg('Tools'), 'tools', 43), (_msg('Mapping'), 'mapping', 64), (_msg('Options'), 'options', 58)):
        c.button(menu_x, c.h - 42, width, 18, label, surfaces.menu(_msg('BSM_MT_uv_') + menu_name), flat=True)
        menu_x += width + 2
    (x, y) = (8, c.h - 65)
    for (icon, tool, label) in (('cursor', 'SELECT', _msg('Select')), ('move', 'MOVE', _msg('Move')), ('rotate', 'ROTATE', _msg('Rotate')), ('scale', 'SCALE', _msg('Scale')), ('selection_region', 'BOX', _msg('Region')), ('pan', 'PAN', _msg('Pan'))):
        c.button(x, y, 25, 24, icon=icon, action=action('TOOL', tool), selected=view['tool'] == tool, flat=True)
        x += 27
    for (icon, op) in (('mirror', 'MIRROR_U'), ('frame', 'FIT'), ('zoom', 'FIT_SELECTED')):
        c.button(x, y, 25, 24, icon=icon, action=action(op), flat=True)
        x += 27
    c.button(x + 8, y + 3, 84, 19, _msg('CheckerPattern'), action('CHECKER'), selected=view['checker'])
    c.text(_msg('UV Channel: ') + (active_mesh(context).data.uv_layers.active.name if active_mesh(context) and active_mesh(context).data.uv_layers.active else _msg('None')), x + 105, y + 8, 9, DIM)
    side = min(198.0, max(145.0, c.w * 0.22))
    rect = (8.0, 58.0, max(60.0, c.w - side - 20), max(50.0, c.h - 129.0))
    view['rect'] = rect
    if view['scale'] is None:
        view['scale'] = min(rect[2], rect[3]) * 0.72
    c.rect(*rect, (0.17, 0.17, 0.17, 1))
    low = _uv((rect[0], rect[1]), view)
    high = _uv((rect[0] + rect[2], rect[1] + rect[3]), view)
    step = 1.0 if view['scale'] >= 35 else max(1.0, 10 ** floor(2.0 - log10(max(1.0, view['scale']))))
    if view['checker'] and view['scale'] > 50:
        (a, b) = (_screen((0.0, 0.0), view), _screen((1.0, 1.0), view))
        cell = view['scale'] / 16
        for i in range(16):
            for j in range(16):
                (xx, yy) = (max(rect[0], a[0] + i * cell), max(rect[1], a[1] + j * cell))
                ww = min(rect[0] + rect[2], a[0] + (i + 1) * cell) - xx
                hh = min(rect[1] + rect[3], a[1] + (j + 1) * cell) - yy
                if ww > 0 and hh > 0:
                    shade = 0.25 if (i + j) % 2 else 0.31
                    c.rect(xx, yy, ww, hh, (shade, shade, shade, 1))
    for i in range(floor(low[0] / step), min(ceil(high[0] / step) + 1, floor(low[0] / step) + 150)):
        _line(c, _screen((i * step, low[1]), view), _screen((i * step, high[1]), view), rect, (0.25, 0.25, 0.25, 1))
    for i in range(floor(low[1] / step), min(ceil(high[1] / step) + 1, floor(low[1] / step) + 150)):
        _line(c, _screen((low[0], i * step), view), _screen((high[0], i * step), view), rect, (0.25, 0.25, 0.25, 1))
    tile = [_screen(p, view) for p in ((0, 0), (1, 0), (1, 1), (0, 1))]
    for (a, b) in zip(tile, tile[1:] + tile[:1]):
        _line(c, a, b, rect, (0.65, 0.65, 0.65, 1), 1.5)
    obj = active_mesh(context)
    data = UVAccess(obj) if obj else None
    count = 0
    if data and data.uv is not None:
        for face_index in data.faces:
            if view['selected_only'] and (not data.base_face_selected(face_index)):
                continue
            keys = data.face_keys(face_index)
            for (i, key) in enumerate(keys):
                (a, b) = (_screen(data.co(key), view), _screen(data.co(keys[(i + 1) % len(keys)]), view))
                selected = data.selected(key)
                _line(c, a, b, rect, ORANGE if selected and data.selected(keys[(i + 1) % len(keys)]) else GREEN, 1.3)
                if _inside(a, rect):
                    color = ORANGE if selected else (0.95, 0.35, 0.28, 1) if data.pinned(key) else GREEN
                    c.rect(a[0] - 2, a[1] - 2, 4, 4, color)
                count += selected
        if data.uv is not None and (not data.items):
            c.text(_msg('The mesh has no faces'), rect[0] + 15, rect[1] + rect[3] * 0.5, 11, DIM)
    else:
        label = _msg('Select a mesh object') if not obj else _msg('Create UV coordinates with Unwrap or Flatten Mapping')
        c.text(label, rect[0] + 15, rect[1] + rect[3] * 0.5, 11, DIM)
    gesture = _gestures.get(context.window.as_pointer()) if context.window else None
    if gesture and gesture['kind'] == 'BOX' and (gesture['area'] == context.area.as_pointer()):
        (a, b) = (gesture['start'], gesture['last'])
        box = (min(a[0], b[0]), min(a[1], b[1]), abs(a[0] - b[0]), abs(a[1] - b[1]))
        _rect_outline(c, box, (0.8, 0.8, 0.8, 1))
    (sx, sy) = (rect[0] + rect[2] + 10, c.h - 79)
    sw = c.w - sx - 8

    def heading(label, height):
        nonlocal sy
        c.rect(sx, sy - 17, sw, 17, (0.31, 0.31, 0.31, 1))
        c.text('▾ ' + label, sx + 6, sy - 12, 9, bold=True)
        sy -= 17
        c.rect(sx, sy - height, sw, height, (0.285, 0.285, 0.285, 1))
    heading(_msg('Selection Modes'), 87)
    for (i, (mode, icon)) in enumerate((('VERTEX', 'vertex'), ('EDGE', 'edge'), ('FACE', 'polygon'))):
        c.button(sx + 8 + i * 29, sy - 29, 26, 23, icon=icon, action=action('MODE', mode), selected=view['mode'] == mode)
    c.button(sx + 8, sy - 53, sw - 16, 18, _msg('Select All'), action('SELECT_ALL'))
    c.button(sx + 8, sy - 77, sw - 16, 18, _msg('Select None'), action('SELECT_NONE'))
    sy -= 93
    heading(_msg('Quick Transform'), 98)
    for (i, (label, name)) in enumerate(((_msg('Rotate +90°'), 'ROTATE_90'), (_msg('Mirror Horizontal'), 'MIRROR_U'), (_msg('Mirror Vertical'), 'MIRROR_V'))):
        c.button(sx + 8, sy - 25 - i * 25, sw - 16, 19, label, action(name))
    sy -= 104
    heading(_msg('Mapping'), 125)
    for (i, (label, name)) in enumerate(((_msg('Unwrap'), 'UNWRAP'), (_msg('Flatten Mapping'), 'SMART'), (_msg('Pack Islands'), 'PACK'), (_msg('Rescale Islands'), 'AVERAGE'))):
        c.button(sx + 8, sy - 25 - i * 25, sw - 16, 19, label, action('UV_OP', name))
    sy -= 131
    heading(_msg('Selection and Pins'), 126)
    for (i, (label, name)) in enumerate(((_msg('Selection From Base'), 'FROM_BASE'), (_msg('Selection To Base'), 'TO_BASE'), (_msg('Pin Selected'), 'PIN'), (_msg('Unpin Selected'), 'UNPIN'))):
        c.button(sx + 8, sy - 25 - i * 25, sw - 16, 19, label, action(name))
    c.rect(0, 0, c.w, 50, BG)
    for (i, (icon, name)) in enumerate((('vertex', 'VERTEX'), ('edge', 'EDGE'), ('polygon', 'FACE'))):
        c.button(8 + i * 27, 24, 24, 22, icon=icon, action=action('MODE', name), selected=view['mode'] == name, flat=True)
    c.button(100, 25, 150, 19, _msg('Selected Polygons Only'), action('SELECTED_ONLY'), selected=view['selected_only'])
    c.text(_dcc_format('{0} texture vertices selected', count), 9, 9, 9, DIM)
    c.text(_notices.get(context.area.as_pointer(), _msg('MMB: Pan   Wheel: Zoom   W/E/R: Transform   Esc: Cancel')), 260, 9, 9, DIM)
    _rect_outline(c, rect, (0.1, 0.1, 0.1, 1))
FONT = 8.5
HDTV_SIZES = ((1280, 720), (1920, 1080), (2560, 1440), (3840, 2160))
GROUP_LINE = (0.36, 0.36, 0.36, 1)
DISABLED_FIELD = (0.3, 0.3, 0.3, 1)

def engine_label(render):
    engine = render.engine
    return _msg('Cycles') if engine == 'CYCLES' else 'EEVEE' if 'EEVEE' in engine else engine.replace('BLENDER_', '').title()

def _view_to_render(context):
    """Max lists the viewport to render as "Quad 4 - Perspective", or the camera."""
    scene = context.scene
    if scene.camera:
        return scene.camera.name
    from .operators import view_name, viewport_override
    try:
        override = viewport_override(context)
    except RuntimeError:
        return _msg('Choose a Camera')
    views = sorted((a for a in override['window'].screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
    slot = views.index(override['area']) + 1 if len(views) == 4 else 4
    return _dcc_format('Quad {0} - {1}', slot, view_name(override['region'].data))

def _render_draw(context):
    """Max 2027's Render Setup dialog, laid out from the owner's screenshot of it: the
    renderer header, the tabs, then Common Parameters and its collapsed rollouts."""
    c = surfaces.Canvas(context)
    c.rect(0, 0, c.w, c.h, BG)
    (scene, render) = (context.scene, context.scene.render)
    engine = engine_label(render)
    ox = max(0.0, (c.w - 355) * 0.5)

    def X(mx):
        return ox + mx - 846

    def Y(my):
        return c.h - (my - 161)

    def label(text, mx, my, enabled=True):
        c.text(text, X(mx), Y(my) - 3.5, FONT, TEXT if enabled else DIM)

    def box(mx, my, w, text):
        c.rect(X(mx), Y(my) - 14, w, 14, DISABLED_FIELD)
        c.text(text, X(mx) + 4, Y(my) - 10.5, 9, DIM)

    def check(mx, my, text, **kwargs):
        c.checkbox(X(mx), Y(my) - 6.5, text, size=FONT, **kwargs)

    def radio(mx, my, text, selected, act, enabled=True):
        c.radio(X(mx), Y(my) - 6.5, text, selected, act, enabled, size=FONT)

    def group(title, top, bottom):
        c.text(title, X(906), Y(top) - 3.5, FONT)
        tw = c.text_width(title, FONT) + 8
        (y0, y1) = (Y(bottom), Y(top))
        for (x, y, w, h) in ((X(900), y1, 3, 1), (X(903) + tw, y1, X(1138) - X(903) - tw, 1), (X(900), y0, X(1138) - X(900), 1), (X(900), y0, 1, y1 - y0), (X(1138) - 1, y0, 1, y1 - y0)):
            c.rect(x, y, w, h, GROUP_LINE)
    header = Y(268)
    c.oy = _render.get('scroll', 0.0)
    c.clip = (0.0, header)
    tab = _render['tab']
    if tab == _msg('Common'):
        (y, opened) = c.rollout(_msg('Common Parameters'), Y(268), 623, key=('RENDER', _msg('Common Parameters')))
        if opened:
            group(_msg('Time Output'), 290, 391)
            (single, active, ranged) = (_render['time'] == t for t in ('SINGLE', 'ACTIVE', 'RANGE'))
            radio(906, 308, _msg('Single'), single, action('RENDER_TIME', 'SINGLE'))
            label(_msg('Every Nth Frame:'), 1020, 308, not single)
            c.field(X(1090), Y(302) - 14, 43, scene, 'frame_step', enabled=not single)
            radio(906, 325, _dcc_format('Active Time Segment:   {0} To {1}', scene.frame_start, scene.frame_end), active, action('RENDER_TIME', 'ACTIVE'))
            radio(906, 341, _msg('Range:'), ranged, action('RENDER_TIME', 'RANGE'))
            c.field(X(958), Y(335) - 14, 52, scene, 'frame_start', enabled=ranged)
            label(_msg('To'), 1015, 341, ranged)
            c.field(X(1035), Y(335) - 14, 51, scene, 'frame_end', enabled=ranged)
            label(_msg('File Number Base:'), 958, 360, False)
            box(1035, 353, 51, '0')
            radio(906, 378, _msg('Frames'), False, ('NONE',), enabled=False)
            box(958, 371, 175, '1,3,5-12')
            group(_msg('Area to Render'), 399, 425)
            area_name = (_msg('Crop') if render.use_crop_to_border else _msg('Region')) if render.use_border else _msg('View')
            c.dropdown(X(905), Y(406) - 16, 95, area_name, surfaces.menu(_msg('BSM_MT_render_area')))
            check(1031, 414, _msg('Auto Region Selected'), value=False, enabled=False)
            group(_msg('Output Size'), 441, 527)
            size = (render.resolution_x, render.resolution_y)
            c.dropdown(X(905), Y(447) - 16, 95, _msg('HDTV (video)') if size in HDTV_SIZES else _msg('Custom'), surfaces.menu(_msg('BSM_MT_utility_size')))
            camera = scene.camera.data if scene.camera and scene.camera.type == 'CAMERA' else None
            if camera:
                label(_msg('Aperture Width(mm):'), 1010, 456)
                lw = c.text_width(_msg('Aperture Width(mm):')) + 3
                c.field(X(1010) + lw, Y(449) - 14, X(1138) - X(1010) - lw, camera, 'sensor_width', spinner=False)
            else:
                label(_msg('Aperture Width(mm): 36.000'), 1010, 456, False)
            label(_msg('Width:'), 905, 477)
            c.field(X(958), Y(470) - 14, 44, render, 'resolution_x')
            label(_msg('Height:'), 905, 494)
            c.field(X(958), Y(487) - 14, 44, render, 'resolution_y')
            for (i, (w, h)) in enumerate(HDTV_SIZES):
                c.button(X(1018 + 61 * (i % 2)), Y(471 + 17 * (i // 2)) - 13, 55, 13, _dcc_format('{0}x{1}', w, h), action('SIZE', w, h), selected=size == (w, h))
            aspect = render.resolution_x * render.pixel_aspect_x / max(1e-09, render.resolution_y * render.pixel_aspect_y)
            label(_dcc_format('Image Aspect: {0:.5f}', aspect), 905, 516)
            label(_msg('Pixel Aspect:'), 1025, 514)
            c.field(X(1078), Y(508) - 14, 55, render, 'pixel_aspect_x', spinner=False)
            group(_msg('Options'), 538, 633)
            for (i, (text, attr)) in enumerate(((_msg('Atmospherics'), None), (_msg('Effects'), 'use_compositing'), (_msg('Displacement'), None), (_msg('Video Color Check'), None), (_msg('Render to Fields'), None))):
                if attr:
                    check(907, 553 + 17.25 * i, text, owner=render, attr=attr)
                else:
                    check(907, 553 + 17.25 * i, text, value=text in {_msg('Atmospherics'), _msg('Displacement')}, enabled=False)
            for (i, text) in enumerate((_msg('Render Hidden Geometry'), _msg('Area Lights/Shadows as Points'), _msg('Force 2-Sided'), _msg('Super Black'))):
                check(996, 553 + 17.25 * i, text, value=False, enabled=False)
            group(_msg('Advanced Lighting'), 644, 686)
            check(907, 659, _msg('Use Advanced Lighting'), value=True, enabled=False)
            check(907, 676, _msg('Compute Advanced Lighting when Required'), value=False, enabled=False)
            group(_msg('Bitmap Performance and Memory Options'), 697, 726)
            label(_msg('Bitmap Proxies / Paging Disabled'), 905, 714)
            c.button(X(1079), Y(721), 54, 13, _msg('Setup...'), enabled=False)
            group(_msg('Render Output'), 738, 896)
            check(907, 756, _msg('Save File'), value=_render['write_still'], action=action('SAVE_FILE'))
            c.button(X(1079), Y(762), 54, 13, _msg('Files...'), action('BROWSE'))
            c.field(X(905), Y(767) - 15, 228, render, 'filepath')
            check(907, 793, _msg('Put Image File List(s) in Output Path(s)'), value=False, enabled=False)
            c.button(X(1079), Y(800), 54, 13, _msg('Create Now'), enabled=False)
            radio(921, 810, _msg('Autodesk ME Image Sequence File (.imsq)'), True, ('NONE',), enabled=False)
            radio(921, 827, _msg('Legacy 3ds Max Image File List (.ifl)'), False, ('NONE',), enabled=False)
            check(907, 846, _msg('Use Device'), value=False, enabled=False)
            box(971, 840, 102, '')
            c.button(X(1079), Y(853), 54, 13, _msg('Devices...'), enabled=False)
            check(907, 869, _msg('Rendered Frame Window'), value=context.preferences.view.render_display_type != 'NONE', action=action('FRAME_WINDOW'))
            check(907, 885, _msg('Skip Existing Images'), value=not render.use_overwrite, action=action('SKIP_EXISTING'))
            y -= 623
        y -= 1
        for (title, height) in ((_msg('Email Notifications'), 30), (_msg('Scripts'), 48), (_msg('Assign Renderer'), 66)):
            (y, opened) = c.rollout(title, y, height, key=('RENDER', title))
            if opened:
                if title == _msg('Email Notifications'):
                    c.checkbox(X(907), y - 20, _msg('Enable Notifications'), value=False, enabled=False)
                elif title == _msg('Scripts'):
                    c.checkbox(X(907), y - 20, _msg('Pre-Render: Enable'), value=False, enabled=False)
                    c.checkbox(X(907), y - 38, _msg('Post-Render: Enable'), value=False, enabled=False)
                else:
                    for (i, text) in enumerate((_msg('Production:'), _msg('Material Editor:'), _msg('ActiveShade:'))):
                        row = y - 21 - 18 * i
                        c.text_right(text, X(980), row + 4, 9, TEXT if i == 0 else DIM)
                        if i == 0:
                            c.dropdown(X(985), row, 148, engine, surfaces.menu(_msg('BSM_MT_utility_engine')))
                        else:
                            c.rect(X(985), row, 148, 16, DISABLED_FIELD)
                            c.text(engine, X(989), row + 4, 9, DIM)
                y -= height
            y -= 1
    elif tab == _msg('Renderer'):
        (y, opened) = c.rollout(engine + _msg(' Renderer'), Y(268), 430, key=('RENDER', _msg('Renderer')))
        if opened:
            if render.engine == 'CYCLES' and hasattr(scene, 'cycles'):
                owner = scene.cycles
                rows = [(_msg('Render Samples'), 'samples'), (_msg('Viewport Samples'), 'preview_samples'), (_msg('Max Bounces'), 'max_bounces'), (_msg('Diffuse Bounces'), 'diffuse_bounces'), (_msg('Glossy Bounces'), 'glossy_bounces'), (_msg('Transmission Bounces'), 'transmission_bounces'), (_msg('Transparent Bounces'), 'transparent_max_bounces'), (_msg('Noise Threshold'), 'adaptive_threshold')]
                toggles = [(_msg('Denoising'), 'use_denoising'), (_msg('Adaptive Sampling'), 'use_adaptive_sampling')]
            elif 'EEVEE' in render.engine and hasattr(scene, 'eevee'):
                owner = scene.eevee
                rows = [(_msg('Render Samples'), 'taa_render_samples'), (_msg('Viewport Samples'), 'taa_samples'), (_msg('Shadow Rays'), 'shadow_ray_count'), (_msg('Shadow Steps'), 'shadow_step_count'), (_msg('Volume Samples'), 'volumetric_samples'), (_msg('Light Threshold'), 'light_threshold')]
                toggles = [(_msg('Ray Tracing'), 'use_raytracing'), (_msg('Shadows'), 'use_shadows')]
            else:
                (owner, toggles) = (scene.display, [])
                rows = [(_msg('Render Anti-Aliasing'), 'render_aa')]
            row_y = y - 24
            for (text, attr) in rows:
                if not hasattr(owner, attr):
                    continue
                c.text_right(text + ':', X(1030), row_y + 4, 9)
                if owner.bl_rna.properties[attr].type == 'ENUM':
                    c.dropdown(X(1035), row_y, 98, str(getattr(owner, attr)), surfaces.op('wm.context_menu_enum', data_path='scene.display.' + attr))
                else:
                    c.field(X(1035), row_y, 98, owner, attr)
                row_y -= 20
            for (text, attr) in toggles:
                if hasattr(owner, attr):
                    c.checkbox(X(907), row_y, text, owner=owner, attr=attr)
                    row_y -= 18
            row_y -= 8
            c.text(_msg('Output'), X(906), row_y, 9, bold=True)
            row_y -= 22
            c.text_right(_msg('File Format:'), X(1030), row_y + 4, 9)
            c.dropdown(X(1035), row_y, 98, render.image_settings.file_format, surfaces.menu(_msg('BSM_MT_utility_format')))
            row_y -= 22
            c.text_right(_msg('Output %:'), X(1030), row_y + 4, 9)
            c.field(X(1035), row_y, 98, render, 'resolution_percentage')
            row_y -= 20
            c.checkbox(X(907), row_y, _msg('Transparent Background'), owner=render, attr='film_transparent')
            row_y -= 18
            c.checkbox(X(907), row_y, _msg('Motion Blur'), owner=render, attr='use_motion_blur')
            row_y -= 22
            c.text(_msg('Color Management: ') + scene.view_settings.view_transform, X(907), row_y, 9, DIM)
            y -= 430
    else:
        layer = context.view_layer
        passes = [(text, attr) for (text, attr) in ((_msg('Z Depth'), 'use_pass_z'), (_msg('Mist'), 'use_pass_mist'), (_msg('Normal'), 'use_pass_normal'), (_msg('Diffuse Color'), 'use_pass_diffuse_color'), (_msg('Specular (Glossy) Color'), 'use_pass_glossy_color'), (_msg('Emission'), 'use_pass_emit'), (_msg('Ambient Occlusion'), 'use_pass_ambient_occlusion'), (_msg('Shadow'), 'use_pass_shadow'), (_msg('Cryptomatte Object'), 'use_pass_cryptomatte_object'), (_msg('Cryptomatte Material'), 'use_pass_cryptomatte_material')) if hasattr(layer, attr)]
        height = 30 + 18 * len(passes)
        (y, opened) = c.rollout(_msg('Render Elements'), Y(268), height, key=('RENDER', _msg('Render Elements')))
        if opened:
            c.text(_msg('Elements active in view layer ') + layer.name, X(907), y - 16, 9, DIM)
            for (i, (text, attr)) in enumerate(passes):
                c.checkbox(X(907), y - 36 - 18 * i, text, owner=layer, attr=attr)
            y -= height
    _render['content'] = Y(268) - y
    c.oy = 0.0
    c.clip = None
    c.rect(0, header, c.w, c.h - header, BG)
    label(_msg('Target:'), 849, 174)
    c.dropdown(X(915), Y(167) - 16, 165, _msg('Production Rendering Mode'), surfaces.menu(_msg('BSM_MT_render_target')))
    label(_msg('Preset:'), 849, 194)
    c.dropdown(X(915), Y(187) - 16, 165, _msg('No preset selected'), surfaces.op('wm.call_menu', name=_msg('RENDER_MT_format_presets')))
    label(_msg('Renderer:'), 849, 214)
    c.dropdown(X(915), Y(207) - 16, 165, engine, surfaces.menu(_msg('BSM_MT_utility_engine')))
    animation = _render['time'] in {'ACTIVE', 'RANGE'}
    c.button(X(1087), Y(202), 109, 35, _msg('Render'), action('RENDER'), tip=_msg('Render Animation') if animation else _msg('Render'))
    check(1089, 214, _msg('Save File'), value=_render['write_still'], action=action('SAVE_FILE'))
    c.button(X(1180), Y(221), 16, 13, '...', action('BROWSE'), flat=True, tip=_msg('Files...'))
    label(_msg('View to Render:'), 849, 237)
    c.dropdown(X(915), Y(230) - 16, 260, _view_to_render(context), surfaces.menu(_msg('BSM_MT_utility_camera')))
    c.button(X(1180), Y(244), 16, 15, '', icon='lock', enabled=False, tip=_msg('Lock View (not available in Blender)'))
    x = X(850)
    for (key, text) in ((_msg('Common'), _msg('Common')), (_msg('Renderer'), engine + _msg(' Renderer')), (_msg('Elements'), _msg('Render Elements'))):
        width = c.text_width(text, 9) + 14
        c.button(x, Y(266), width, 14, text, action('RENDER_TAB', key), flat=True, fill=(0.33, 0.33, 0.33, 1) if _render['tab'] == key else None)
        x += width + 4
    c.line([(0, Y(267)), (c.w, Y(267))], GROUP_LINE)
    notice = _notices.get(context.area.as_pointer(), '')
    if notice:
        c.rect(0, 0, c.w, 16, BG)
        c.text(notice, 8, 4, 9, DIM)

def draw(context, kind):
    if kind == 'UV':
        _uv_draw(context)
    elif kind == _msg('Render'):
        _render_draw(context)

def _distance_segment(point, a, b):
    (dx, dy) = (b[0] - a[0], b[1] - a[1])
    t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / max(1e-12, dx * dx + dy * dy)))
    return hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy)

def _in_polygon(point, coords):
    result = False
    for (a, b) in zip(coords, coords[1:] + coords[:1]):
        if (a[1] > point[1]) != (b[1] > point[1]):
            xx = a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if point[0] < xx:
                result = not result
    return result

def hit_uv(obj, point, view):
    data = UVAccess(obj)
    visible = {key for key in data.items if not view['selected_only'] or data.base_face_selected(key[0])}
    if view['mode'] == 'VERTEX':
        if not visible:
            return set()
        key = min(visible, key=lambda k: hypot(*[a - b for (a, b) in zip(_screen(data.co(k), view), point)]))
        if hypot(*[a - b for (a, b) in zip(_screen(data.co(key), view), point)]) > 8:
            return set()
        (vertex, co) = (data.vertex_index(key), data.co(key))
        return {k for k in visible if data.vertex_index(k) == vertex and hypot(data.co(k)[0] - co[0], data.co(k)[1] - co[1]) < 1e-06}
    if view['mode'] == 'EDGE':
        candidates = []
        for index in data.faces:
            keys = [k for k in data.face_keys(index) if k in visible]
            for (i, key) in enumerate(keys):
                other = keys[(i + 1) % len(keys)]
                candidates.append((_distance_segment(point, _screen(data.co(key), view), _screen(data.co(other), view)), {key, other}))
        return min(candidates, key=lambda pair: pair[0])[1] if candidates and min((p[0] for p in candidates)) <= 7 else set()
    for index in reversed(list(data.faces)):
        keys = [k for k in data.face_keys(index) if k in visible]
        if len(keys) >= 3 and _in_polygon(point, [_screen(data.co(k), view) for k in keys]):
            return set(keys)
    return set()

def _box_keys(data, view, start, end):
    rect = (min(start[0], end[0]), min(start[1], end[1]), abs(start[0] - end[0]), abs(start[1] - end[1]))
    inside = {k for k in data.items if _inside(_screen(data.co(k), view), rect) and (not view['selected_only'] or data.base_face_selected(k[0]))}
    if view['mode'] == 'VERTEX':
        return inside
    crossing = end[0] < start[0]
    result = set()
    for index in data.faces:
        if view['selected_only'] and (not data.base_face_selected(index)):
            continue
        keys = data.face_keys(index)
        points = [_screen(data.co(key), view) for key in keys]
        if view['mode'] == 'FACE':
            if crossing:
                box_corners = ((rect[0], rect[1]), (rect[0] + rect[2], rect[1]), (rect[0] + rect[2], rect[1] + rect[3]), (rect[0], rect[1] + rect[3]))
                intersects = any((k in inside for k in keys)) or any((_clip_segment(a, b, rect) is not None for (a, b) in zip(points, points[1:] + points[:1]))) or any((_in_polygon(p, points) for p in box_corners))
            else:
                intersects = all((k in inside for k in keys))
            if intersects:
                result.update(keys)
        else:
            for (i, key) in enumerate(keys):
                edge = {key, keys[(i + 1) % len(keys)]}
                intersects = _clip_segment(points[i], points[(i + 1) % len(points)], rect) is not None
                if intersects if crossing else edge <= inside:
                    result.update(edge)
    return result
(_CTRL, _SHIFT) = ({'ctrl': True}, {'shift': True})
UNWRAP_KEYS = (('Q', _msg('Freeform Mode (Select)'), 'Q', {}, ('TOOL', 'SELECT'), '2077580866-40087'), ('W', _msg('Texture Vertex Move Mode'), 'W', {}, ('TOOL', 'MOVE'), '2077580866-40007'), ('E', _msg('Texture Vertex Rotate Mode'), 'E', {}, ('TOOL', 'ROTATE'), '2077580866-40008'), ('R', _msg('Texture Vertex Scale Mode'), 'R', {}, ('TOOL', 'SCALE'), '2077580866-40009'), ('1', _msg('Vertex sub-object level'), 'ONE', {}, ('MODE', 'VERTEX'), _msg('647394-SubObject_1`Modifier Stack')), ('2', _msg('Edge sub-object level'), 'TWO', {}, ('MODE', 'EDGE'), _msg('647394-SubObject_2`Modifier Stack')), ('3', _msg('Polygon sub-object level'), 'THREE', {}, ('MODE', 'FACE'), _msg('647394-SubObject_3`Modifier Stack')), (_msg('Ctrl+A'), _msg('Select All'), 'A', _CTRL, ('SELECT_ALL',), '0-40021'), (_msg('Ctrl+D'), _msg('Select None'), 'D', _CTRL, ('SELECT_NONE',), '0-40043'), (_msg('Ctrl+I'), _msg('Select Invert'), 'I', _CTRL, ('INVERT',), '0-40044'), ('Z', _msg('Zoom Extents Selected'), 'Z', {}, ('FIT_SELECTED',), '2077580866-40030'), (_msg('Ctrl+Alt+Z'), _msg('Zoom Extents'), 'Z', {'ctrl': True, 'alt': True}, ('FIT',), '2077580866-40029'), (_msg('Ctrl+P'), _msg('Pan'), 'P', _CTRL, ('TOOL', 'PAN'), '2077580866-40026'), (_msg('Ctrl+Right'), _msg('Rotate +90'), 'RIGHT_ARROW', _CTRL, ('ROTATE_90',), '2077580866-40255'), (_msg('Ctrl+Left'), _msg('Rotate -90'), 'LEFT_ARROW', _CTRL, ('ROTATE_MINUS_90',), '2077580866-40256'), (_msg('Shift+A'), _msg('Pack'), 'A', _SHIFT, ('UV_OP', 'PACK'), '2077580866-40074'), (_msg('Ctrl+Q'), _msg('Quick Peel Unfold'), 'Q', _CTRL, ('UV_OP', 'UNWRAP'), '2077580866-46000'), (_msg('Alt+Shift+W'), _msg('Texture Vertex Weld Selected'), 'W', {'alt': True, 'shift': True}, ('UV_OP', 'WELD'), '2077580866-40015'))

def handle_event(context, event, area, region, x, y):
    from . import chrome
    if chrome.role(area) == _msg('Render'):
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            visible = region.height / surfaces.scale() - 107
            top = max(0.0, _render.get('content', 0.0) - visible)
            step = 30.0 if event.type == 'WHEELDOWNMOUSE' else -30.0
            _render['scroll'] = min(top, max(0.0, _render.get('scroll', 0.0) + step))
            runtime.redraw()
            return {'RUNNING_MODAL'}
        return None
    if chrome.role(area) != 'UV':
        return None
    view = _state(area)
    point = (x, y)
    if event.value == 'PRESS' and _inside(point, view['rect']):
        from .keymap import match
        row = match(UNWRAP_KEYS, event)
        if row:
            try:
                dispatch(context, action(*row[4]))
            except (ValueError, RuntimeError) as error:
                _notice(context, str(error))
            runtime.redraw()
            return {'RUNNING_MODAL'}
    if not _inside(point, view['rect']):
        return None
    if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
        anchor = _uv(point, view)
        view['scale'] = min(30000.0, max(4.0, view['scale'] * (1.18 if event.type == 'WHEELUPMOUSE' else 1 / 1.18)))
        after = _uv(point, view)
        view['center'] = tuple((view['center'][i] + anchor[i] - after[i] for i in (0, 1)))
        runtime.redraw()
        return {'RUNNING_MODAL'}
    if event.value != 'PRESS' or event.type not in {'LEFTMOUSE', 'MIDDLEMOUSE'}:
        return None
    window_key = context.window.as_pointer()
    base = {'area': area.as_pointer(), 'start': point, 'last': point, 'center': view['center'], 'scale': view['scale'], 'shift': event.shift, 'ctrl': event.ctrl}
    if event.type == 'MIDDLEMOUSE' or view['tool'] == 'PAN':
        _gestures[window_key] = dict(base, kind='PAN')
        return {'RUNNING_MODAL'}
    obj = active_mesh(context)
    if not obj or not UVAccess(obj).items:
        return {'RUNNING_MODAL'}
    keys = hit_uv(obj, point, view)
    if view['tool'] == 'BOX' or not keys:
        _gestures[window_key] = dict(base, kind='BOX', obj=obj, signature=UVAccess(obj).signature())
        return {'RUNNING_MODAL'}
    old = selection(obj)
    if event.ctrl:
        select_keys(obj, keys, replace=False, toggle=True, sync_faces=view['mode'] == 'FACE')
        _undo(_msg('UV Selection'))
        runtime.redraw()
        return {'RUNNING_MODAL'}
    if not keys <= old or event.shift:
        select_keys(obj, keys, replace=not event.shift, sync_faces=view['mode'] == 'FACE')
    if view['tool'] == 'SELECT':
        _undo(_msg('UV Selection'))
        runtime.redraw()
        return {'RUNNING_MODAL'}
    values = uv_snapshot(obj, selection(obj))
    pivot = _uv(point, view) if event.ctrl and event.alt else tuple((sum((co[i] for co in values.values())) / len(values) for i in (0, 1)))
    _gestures[window_key] = dict(base, kind='TRANSFORM', obj=obj, signature=UVAccess(obj).signature(), values=values, tool=view['tool'], pivot=pivot)
    runtime.redraw()
    return {'RUNNING_MODAL'}

def active_event(context, event):
    if not context.window:
        return None
    window_key = context.window.as_pointer()
    gesture = _gestures.get(window_key)
    if gesture is None:
        return None
    area = next((a for a in context.window.screen.areas if a.as_pointer() == gesture['area']), None)
    if area is None:
        _cancel(window_key)
        return {'RUNNING_MODAL'}
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None:
        _cancel(window_key)
        return {'RUNNING_MODAL'}
    view = _state(area)
    point = ((event.mouse_x - region.x) / surfaces.scale(), (event.mouse_y - region.y) / surfaces.scale())
    gesture['last'] = point
    if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
        _cancel(window_key)
        runtime.redraw()
        return {'RUNNING_MODAL'}
    obj = gesture.get('obj')
    if obj:
        try:
            valid = active_mesh(context) == obj and UVAccess(obj).signature() == gesture['signature']
        except (ReferenceError, ValueError):
            valid = False
        if not valid:
            _cancel(window_key)
            return {'RUNNING_MODAL'}
    if event.type == 'MOUSEMOVE':
        if gesture['kind'] == 'PAN':
            view['center'] = tuple((gesture['center'][i] - (point[i] - gesture['start'][i]) / gesture['scale'] for i in (0, 1)))
        elif gesture['kind'] == 'TRANSFORM':
            delta = [(point[i] - gesture['start'][i]) / view['scale'] for i in (0, 1)]
            (values, pivot) = (gesture['values'], gesture['pivot'])
            if gesture['tool'] == 'MOVE':
                if event.shift:
                    delta[0 if abs(delta[0]) < abs(delta[1]) else 1] = 0.0
                transform_uv(obj, values, offset=delta)
            else:
                (start_uv, now_uv) = (_uv(gesture['start'], view), _uv(point, view))
                (a, b) = ((start_uv[0] - pivot[0], start_uv[1] - pivot[1]), (now_uv[0] - pivot[0], now_uv[1] - pivot[1]))
                if gesture['tool'] == 'ROTATE':
                    angle = atan2(b[1], b[0]) - atan2(a[1], a[0])
                    if event.ctrl:
                        angle = round(angle / (pi / 36)) * (pi / 36)
                    transform_uv(obj, values, rotation=angle, pivot=pivot)
                else:
                    factor = max(0.001, hypot(*b) / max(1e-06, hypot(*a)))
                    scales = (factor, factor)
                    if event.shift:
                        scales = (1.0, factor) if abs(delta[1]) > abs(delta[0]) else (factor, 1.0)
                    transform_uv(obj, values, scale=scales, pivot=pivot)
        runtime.redraw()
    if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE'} and event.value == 'RELEASE':
        if gesture['kind'] == 'BOX':
            select_keys(obj, _box_keys(UVAccess(obj), view, gesture['start'], point), replace=not (event.shift or event.ctrl), subtract=event.ctrl, sync_faces=view['mode'] == 'FACE')
        if gesture['kind'] != 'PAN':
            _undo(_msg('Edit UVWs ') + (_msg('Selection') if gesture['kind'] == 'BOX' else gesture['tool'].title()))
        _gestures.pop(window_key, None)
        runtime.redraw()
    return {'RUNNING_MODAL'}

def _cancel(window_key):
    gesture = _gestures.pop(window_key, None)
    if not gesture:
        return
    if gesture['kind'] == 'TRANSFORM':
        try:
            if UVAccess(gesture['obj']).signature() == gesture['signature']:
                apply_uv_snapshot(gesture['obj'], gesture['values'])
        except (ReferenceError, ValueError, RuntimeError):
            pass
    elif gesture['kind'] == 'PAN' and gesture['area'] in _views:
        _views[gesture['area']]['center'] = gesture['center']

def dispatch(context, value):
    if not value or value[0] != 'UTIL':
        return None
    (name, *args) = value[1:]
    view = _state(context.area) if context.area else None
    obj = active_mesh(context)
    if name == 'RENDER_TAB':
        _render['tab'] = args[0]
    elif name == 'RENDER_TIME':
        _render['time'] = args[0]
    elif name == 'SIZE':
        render = context.scene.render
        (render.resolution_x, render.resolution_y) = (int(args[0]), int(args[1]))
        render.pixel_aspect_x = render.pixel_aspect_y = 1.0
        _undo(_msg('Render Output Size'))
    elif name == 'AREA':
        render = context.scene.render
        render.use_border = args[0] != 'VIEW'
        render.use_crop_to_border = args[0] == 'CROP'
    elif name == 'FRAME_WINDOW':
        view_prefs = context.preferences.view
        view_prefs.render_display_type = 'NONE' if view_prefs.render_display_type != 'NONE' else 'WINDOW'
    elif name == 'SKIP_EXISTING':
        render = context.scene.render
        render.use_overwrite = not render.use_overwrite
    elif name == 'SAVE_FILE':
        _render['write_still'] = not _render['write_still']
    elif name == 'BROWSE':
        return bpy.ops.bsm.render_output_file('INVOKE_DEFAULT')
    elif name == 'RENDER':
        from .commands import render_active_view
        try:
            return render_active_view(context, animation=_render['time'] in {'ACTIVE', 'RANGE'}, write_still=_render['write_still'])
        except RuntimeError as error:
            raise ValueError(str(error))
    elif name in {'TOOL', 'MODE'}:
        view[name.lower()] = args[0]
    elif name in {'FIT', 'FIT_SELECTED'}:
        fit_uv(context, selected=name == 'FIT_SELECTED')
    elif name in {'CHECKER', 'SELECTED_ONLY'}:
        key = 'checker' if name == 'CHECKER' else 'selected_only'
        view[key] = not view[key]
    elif name == 'UV_OP':
        result = uv_operator(context, args[0])
        fit_uv(context)
        _notice(context, _msg('Completed ') + {'SMART': _msg('Flatten Mapping (Smart UV Project)')}.get(args[0], args[0].replace('_', ' ').title()))
        return result
    else:
        if not obj:
            raise ValueError(_msg('Select an editable mesh object'))
        data = UVAccess(obj)
        if name in {'SELECT_ALL', 'SELECT_NONE', 'INVERT'}:
            keys = set(data.items) if name == 'SELECT_ALL' else {k for k in data.items if not data.selected(k)} if name == 'INVERT' else set()
            select_keys(obj, keys, sync_faces=view['mode'] == 'FACE')
        elif name == 'FROM_BASE':
            select_keys(obj, {k for k in data.items if data.base_face_selected(k[0])})
        elif name == 'TO_BASE':
            for index in data.faces:
                keys = data.face_keys(index)
                data.set_face_selected(index, bool(keys) and all((data.selected(k) for k in keys)), mesh=True)
            data.update()
        elif name in {'PIN', 'UNPIN'}:
            for key in data.items:
                if data.selected(key):
                    data.set_pinned(key, name == 'PIN')
            data.update()
        elif name in {'ROTATE_90', 'ROTATE_MINUS_90', 'MIRROR_U', 'MIRROR_V'}:
            values = uv_snapshot(obj, selection(obj))
            transform_uv(obj, values, rotation={'ROTATE_90': pi * 0.5, 'ROTATE_MINUS_90': -pi * 0.5}.get(name, 0.0), scale=(-1.0, 1.0) if name == 'MIRROR_U' else (1.0, -1.0) if name == 'MIRROR_V' else (1.0, 1.0))
        else:
            raise ValueError(_msg('Unknown utility action: ') + name)
        _undo(_msg('Edit UVWs ') + name.replace('_', ' ').title())
    runtime.redraw()
    return {'FINISHED'}

class BSM_OT_render_output_file(bpy.types.Operator):
    bl_idname = 'bsm.render_output_file'
    bl_label = _msg('Render Output File')
    filepath: StringProperty(subtype='FILE_PATH', translation_context=_msg('DCCWorkflowKit.Max'))
    check_existing: BoolProperty(default=False, options={'HIDDEN'}, translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        self.filepath = bpy.path.abspath(context.scene.render.filepath)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        render = context.scene.render
        render.filepath = self.filepath
        formats = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.exr': 'OPEN_EXR', '.tif': 'TIFF', '.tiff': 'TIFF', '.bmp': 'BMP', '.tga': 'TARGA', '.hdr': 'HDR', '.webp': 'WEBP'}
        extension = os.path.splitext(self.filepath)[1].lower()
        if extension in formats:
            try:
                render.image_settings.file_format = formats[extension]
            except TypeError:
                pass
        _render['write_still'] = True
        runtime.redraw()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_utility_setting(bpy.types.Operator):
    bl_idname = 'bsm.utility_setting'
    bl_label = _msg('Max Editor Setting')
    bl_options = {'REGISTER', 'UNDO'}
    setting: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    value: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    width: IntProperty(default=1920, min=4, translation_context=_msg('DCCWorkflowKit.Max'))
    height: IntProperty(default=1080, min=4, translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        if self.setting == 'CAMERA':
            camera = context.scene.objects.get(self.value)
            if not camera or camera.type != 'CAMERA':
                self.report({'WARNING'}, _dcc_ui_text(_msg('The camera is no longer in this scene')))
                return {'CANCELLED'}
            context.scene.camera = camera
        elif self.setting == 'SIZE':
            context.scene.render.resolution_x = self.width
            context.scene.render.resolution_y = self.height
            context.scene.render.pixel_aspect_x = 1.0
            context.scene.render.pixel_aspect_y = 1.0
        else:
            self.report({'WARNING'}, _dcc_ui_text(_msg('Unknown editor setting')))
            return {'CANCELLED'}
        runtime.redraw()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_utility_action(bpy.types.Operator):
    bl_idname = 'bsm.utility_action'
    bl_label = _msg('Edit UVWs Action')
    command: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    value: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        try:
            return dispatch(context, action(self.command, self.value) if self.value else action(self.command))
        except (ValueError, RuntimeError, ReferenceError) as error:
            self.report({'WARNING'}, _dcc_ui_error(error))
            return {'CANCELLED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def _menu_action(layout, label, command, value=''):
    op = layout.operator('bsm.utility_action', text=_dcc_ui_text(label))
    (op.command, op.value) = (command, value)

class BSM_MT_uv_edit(bpy.types.Menu):
    bl_label = _msg('Edit')

    def draw(self, context):
        self.layout.operator('ed.undo', text=_dcc_ui_text(_msg('Undo')))
        self.layout.operator('ed.redo', text=_dcc_ui_text(_msg('Redo')))
        self.layout.separator()
        _menu_action(self.layout, _msg('Pin Selected'), 'PIN')
        _menu_action(self.layout, _msg('Unpin Selected'), 'UNPIN')
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_uv_select(bpy.types.Menu):
    bl_label = _msg('Select')

    def draw(self, context):
        for (label, name) in ((_msg('Select All'), 'SELECT_ALL'), (_msg('Select None'), 'SELECT_NONE'), (_msg('Invert Selection'), 'INVERT'), (_msg('Selection From Base'), 'FROM_BASE'), (_msg('Selection To Base'), 'TO_BASE')):
            _menu_action(self.layout, label, name)
        self.layout.separator()
        for (label, mode) in ((_msg('Vertex'), 'VERTEX'), (_msg('Edge'), 'EDGE'), (_msg('Polygon'), 'FACE')):
            _menu_action(self.layout, label, 'MODE', mode)
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_uv_tools(bpy.types.Menu):
    bl_label = _msg('Tools')

    def draw(self, context):
        for (label, tool) in ((_msg('Move'), 'MOVE'), (_msg('Rotate'), 'ROTATE'), (_msg('Scale'), 'SCALE'), (_msg('Region Select'), 'BOX'), (_msg('Pan View'), 'PAN')):
            _menu_action(self.layout, label, 'TOOL', tool)
        self.layout.separator()
        for (label, name) in ((_msg('Rotate +90°'), 'ROTATE_90'), (_msg('Mirror Horizontal'), 'MIRROR_U'), (_msg('Mirror Vertical'), 'MIRROR_V'), (_msg('Zoom Extents'), 'FIT'), (_msg('Zoom Extents Selected'), 'FIT_SELECTED')):
            _menu_action(self.layout, label, name)
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_uv_mapping(bpy.types.Menu):
    bl_label = _msg('Mapping')

    def draw(self, context):
        for (label, name) in ((_msg('Unwrap (Angle Based)'), 'UNWRAP'), (_msg('Flatten Mapping (Smart UV Project)'), 'SMART'), (_msg('Pack Islands'), 'PACK'), (_msg('Rescale Islands'), 'AVERAGE')):
            _menu_action(self.layout, label, 'UV_OP', name)
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_uv_options(bpy.types.Menu):
    bl_label = _msg('Options')

    def draw(self, context):
        _menu_action(self.layout, _msg('Show Checker Pattern'), 'CHECKER')
        _menu_action(self.layout, _msg('Display Only Selected Polygons'), 'SELECTED_ONLY')
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_utility_engine(bpy.types.Menu):
    bl_label = _msg('Renderer')

    def draw(self, context):
        self.layout.prop(context.scene.render, 'engine', expand=True)
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_utility_camera(bpy.types.Menu):
    bl_label = _msg('View to Render')

    def draw(self, context):
        cameras = [obj for obj in context.scene.objects if obj.type == 'CAMERA']
        for camera in cameras:
            op = self.layout.operator('bsm.utility_setting', text=_dcc_ui_text(camera.name), icon='RADIOBUT_ON' if camera == context.scene.camera else 'RADIOBUT_OFF')
            (op.setting, op.value) = ('CAMERA', camera.name)
        if not cameras:
            self.layout.label(text=_dcc_ui_text(_msg('Add a camera to this scene')), icon='INFO')
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_utility_size(bpy.types.Menu):
    bl_label = _msg('Output Size')

    def draw(self, context):
        for (label, width, height) in (('HDTV 1280 × 720', 1280, 720), ('HDTV 1920 × 1080', 1920, 1080), ('UHD 3840 × 2160', 3840, 2160), (_msg('Square 1024 × 1024'), 1024, 1024), (_msg('Square 2048 × 2048'), 2048, 2048), ('640 × 480', 640, 480)):
            op = self.layout.operator('bsm.utility_setting', text=_dcc_ui_text(label))
            (op.setting, op.width, op.height) = ('SIZE', width, height)
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_render_area(bpy.types.Menu):
    bl_label = _msg('Area to Render')

    def draw(self, context):
        render = context.scene.render
        current = ('CROP' if render.use_crop_to_border else 'REGION') if render.use_border else 'VIEW'
        for (label, value) in ((_msg('View'), 'VIEW'), (_msg('Region'), 'REGION'), (_msg('Crop'), 'CROP')):
            op = self.layout.operator('bsm.utility_action', text=_dcc_ui_text(label), icon='RADIOBUT_ON' if value == current else 'RADIOBUT_OFF')
            (op.command, op.value) = ('AREA', value)
        for label in (_msg('Selected'), _msg('Blowup')):
            row = self.layout.row()
            row.enabled = False
            row.label(text=_dcc_ui_text(label), icon='RADIOBUT_OFF')
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_render_target(bpy.types.Menu):
    bl_label = _msg('Target')

    def draw(self, context):
        self.layout.label(text=_dcc_ui_text(_msg('Production Rendering Mode')), icon='RADIOBUT_ON')
        for label in (_msg('Iterative Rendering Mode'), _msg('ActiveShade Mode'), _msg('Submit to Network Rendering')):
            row = self.layout.row()
            row.enabled = False
            row.label(text=_dcc_ui_text(label), icon='RADIOBUT_OFF')
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_utility_format(bpy.types.Menu):
    bl_label = _msg('Output File Format')

    def draw(self, context):
        self.layout.prop(context.scene.render.image_settings, 'file_format', expand=True)
    bl_translation_context = _msg('DCCWorkflowKit.Max')
CLASSES = (BSM_OT_render_output_file, BSM_OT_utility_setting, BSM_OT_utility_action, BSM_MT_uv_edit, BSM_MT_uv_select, BSM_MT_uv_tools, BSM_MT_uv_mapping, BSM_MT_uv_options, BSM_MT_utility_engine, BSM_MT_utility_camera, BSM_MT_utility_size, BSM_MT_render_area, BSM_MT_render_target, BSM_MT_utility_format)

def clear():
    for window in list(_gestures):
        _cancel(window)
    _views.clear()
    _notices.clear()
