# SPDX-License-Identifier: GPL-3.0-or-later
"""UV Editor > Tools > Lattice, like Maya's Lattice UV Tool: a lattice of Columns x Rows points around the selected
UVs (all shown UVs when none is selected, like an object selection in Maya); LMB drag a lattice point to bend the
UVs inside it. Like Maya, the lattice is a Bezier patch: every lattice point pulls every UV with its Bernstein weight
(3 x 3 = quadratic), so one point bends the whole lattice smoothly. The lattice follows a change of the selection or an
undo: it is rebuilt around the UVs whenever they are not where it left them.

A drag on a lattice line moves both its points. Falloff scales how far the UVs follow the lattice (1 = all the
way). With Use bounding rectangle off the lattice is not fitted around the UVs: an LMB drag on empty space draws its
rectangle, and it bends the targeted UVs inside it. Show move manipulator: the lattice point last picked gets a move
handle (U arrow, V arrow, centre square) that moves it along U, V or freely. With the UV Editor's Pixel Snap on and an
image shown, a dragged lattice point lands on pixel corners or pixel centres (Snap corner / Snap center).

Settings: ``Scene.allset_uv_brush.lattice_*``.
"""

import math
import time

import bmesh
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from .. import compat
from . import uv_brush

TOOL = "allset.uv_lattice"
PICK_PX = 10.0
CHECK_S = 0.3
LINE_RGB = (0.85, 0.35, 0.85)
POINT_RGB = (1.0, 1.0, 1.0)
HOT_RGB = (1.0, 0.85, 0.1)
RECT_RGB = (0.85, 0.85, 0.85)
AXIS_U_RGB = (0.9, 0.25, 0.25)
AXIS_V_RGB = (0.3, 0.85, 0.3)
MANIP_PX = 40.0          # move handle arrow length (pixels at UI scale 1)


# --- maths (numpy) -----------------------------------------------------------------------------------

def grid(rect, cols, rows):
    """(rows, cols, 2) lattice points evenly over ``rect`` = (u0, v0, u1, v1)."""
    u = np.linspace(rect[0], rect[2], cols)
    v = np.linspace(rect[1], rect[3], rows)
    return np.stack(np.meshgrid(u, v), axis=-1)


def params(U, rect):
    """Each UV's place in ``rect`` as (s, t) 0-1."""
    w = max(rect[2] - rect[0], 1e-12)
    h = max(rect[3] - rect[1], 1e-12)
    return np.stack(((U[:, 0] - rect[0]) / w, (U[:, 1] - rect[1]) / h), axis=1)


def bernstein(n, x):
    """(len(x), n + 1) Bernstein weights of degree ``n`` at ``x`` (0-1)."""
    x = np.clip(np.asarray(x, float), 0.0, 1.0)[:, None]
    k = np.arange(n + 1)[None, :]
    binom = np.array([math.comb(n, i) for i in range(n + 1)], float)[None, :]
    return binom * x ** k * (1.0 - x) ** (n - k)


def deform(pts, st):
    """The UVs at lattice places ``st`` for the (rows, cols, 2) lattice points ``pts``: a Bezier patch over the whole
    lattice (an untouched, evenly spaced lattice gives back the places themselves)."""
    rows, cols = pts.shape[:2]
    ws = bernstein(cols - 1, st[:, 0])          # (n, cols)
    wt = bernstein(rows - 1, st[:, 1])          # (n, rows)
    return np.einsum("nc,nr,rcd->nd", ws, wt, pts)


def snap_pixel(value, size, mode):
    """``value`` (UV) on the nearest pixel corner (``mode`` 'CORNER') or pixel centre ('CENTER') of an image ``size``
    pixels across."""
    if size <= 0:
        return value
    if mode == 'CORNER':
        return round(value * size) / size
    return (math.floor(value * size) + 0.5) / size


def segment_hit(p, a, b):
    """Distance from point ``p`` to segment ``a`` - ``b`` (2D)."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    t = 0.0 if ll <= 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / ll))
    return math.hypot(ax + dx * t - p[0], ay + dy * t - p[1])


def bounds(U):
    lo, hi = U.min(axis=0), U.max(axis=0)
    pad = np.maximum((hi - lo) * 1e-3, 1e-6)       # a lattice on one row / column of UVs still has an area
    lo, hi = lo - pad, hi + pad
    return (float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1]))


# --- the live lattice --------------------------------------------------------------------------------

_state = {"lattice": None, "hot": None}
_handle = []


class Lattice:
    """The lattice and the UVs it bends: per mesh the target UV point indices and their lattice places."""

    def __init__(self, meshes, cols, rows, rect=None):
        self.targets = []
        allu = []
        for m in meshes:
            idx = np.nonzero(m.selected)[0] if m.selected.any() else np.arange(len(m.U))
            if rect is not None:            # a drawn lattice: the targeted UVs inside it
                u, v = m.U[idx, 0], m.U[idx, 1]
                idx = idx[(u >= rect[0]) & (u <= rect[2]) & (v >= rect[1]) & (v <= rect[3])]
            self.targets.append(idx)
            allu.append(m.U[idx])
        U = np.concatenate(allu) if allu else np.zeros((0, 2))
        self.drawn = rect is not None
        self.ok = len(U) > 0 or self.drawn
        self.rect = rect if rect is not None else bounds(U) if len(U) else (0.0, 0.0, 1.0, 1.0)
        self.pts = grid(self.rect, cols, rows)
        self.shape = (rows, cols)
        self.st = [params(m.U[idx], self.rect) for m, idx in zip(meshes, self.targets)]
        self.base = [m.U[idx].copy() for m, idx in zip(meshes, self.targets)]
        self.names = [m.ob.name for m in meshes]
        self.last = [m.U[idx].copy() for m, idx in zip(meshes, self.targets)]
        self.picked = None          # the lattice point the move handle sits on

    def matches(self, meshes, cols, rows):
        """Whether the UVs are still where this lattice left them (no undo, no new selection, same size)."""
        if (rows, cols) != self.shape or [m.ob.name for m in meshes] != self.names:
            return False
        for m, idx, last in zip(meshes, self.targets, self.last):
            sel = np.nonzero(m.selected)[0] if m.selected.any() else np.arange(len(m.U))
            if self.drawn:
                if not np.isin(idx, sel).all() or not np.allclose(m.U[idx], last, atol=1e-7):
                    return False
            elif len(sel) != len(idx) or not np.array_equal(sel, idx) or not np.allclose(m.U[idx], last, atol=1e-7):
                return False
        return True

    def apply(self, meshes, falloff=1.0):
        """Bend the target UVs by the lattice; ``falloff`` (0-1) = how far they follow it."""
        changed = False
        for k, (m, idx) in enumerate(zip(meshes, self.targets)):
            U = m.U.copy()
            U[idx] = self.base[k] + (deform(self.pts, self.st[k]) - self.base[k]) * float(falloff)
            changed |= m.write(U)
            self.last[k] = U[idx].copy()
        return changed


def lattice_for(context, meshes):
    """The live lattice for ``meshes``: kept while the UVs are where it left them, else fitted anew around the
    targeted UVs (Use bounding rectangle) or dropped until a new one is drawn (``None``)."""
    s = uv_brush.settings(context)
    lat = _state["lattice"]
    if lat is not None and (lat.drawn != (not s.lattice_bounding_rect)):
        lat = None
    if lat is None or not lat.matches(meshes, s.lattice_columns, s.lattice_rows):
        if not s.lattice_bounding_rect:
            lat = None
        else:
            lat = Lattice(meshes, s.lattice_columns, s.lattice_rows)
        _state["lattice"] = lat
    return lat


def image_size(space):
    """(width, height) of the image the UV Editor shows, or None."""
    img = getattr(space, "image", None)
    if img is None:
        return None
    w, h = img.size[:]
    return (w, h) if w > 0 and h > 0 else None


def snapped(context, uv):
    """A dragged lattice point with the UV Editor's Pixel Snap: on a pixel corner / centre (Lattice Snap settings)."""
    space = context.space_data
    size = image_size(space)
    mode = getattr(getattr(space, "uv_editor", None), "pixel_round_mode", 'DISABLED')
    if size is None or mode == 'DISABLED':
        return uv
    kind = uv_brush.settings(context).lattice_snap
    return (snap_pixel(uv[0], size[0], kind), snap_pixel(uv[1], size[1], kind))


def tool_active(context):
    return uv_brush.active_tool(context) == TOOL


def _pick(region, lat, xy):
    v2d = region.view2d
    best, bd = None, PICK_PX * PICK_PX
    rows, cols = lat.shape
    for j in range(rows):
        for i in range(cols):
            x, y = v2d.view_to_region(*lat.pts[j, i], clip=False)
            d = (x - xy[0]) ** 2 + (y - xy[1]) ** 2
            if d <= bd:
                best, bd = (j, i), d
    return best


def _pick_line(region, lat, xy):
    """The lattice line under ``xy``: its two points ((j, i), (j, i)), or None."""
    v2d = region.view2d
    rows, cols = lat.shape
    px = [[v2d.view_to_region(*lat.pts[j, i], clip=False) for i in range(cols)] for j in range(rows)]
    best, bd = None, PICK_PX * 0.6
    for j in range(rows):
        for i in range(cols):
            for (j2, i2) in ((j, i + 1), (j + 1, i)):
                if j2 < rows and i2 < cols:
                    d = segment_hit(xy, px[j][i], px[j2][i2])
                    if d <= bd:
                        best, bd = ((j, i), (j2, i2)), d
    return best


def _manip_handles(region, lat, scale):
    """The move handle of the picked lattice point: {'U' / 'V' / 'FREE': region (x, y) of its grip}."""
    if lat.picked is None:
        return {}
    x, y = region.view2d.view_to_region(*lat.pts[lat.picked], clip=False)
    n = MANIP_PX * scale
    return {"U": (x + n, y), "V": (x, y + n), "FREE": (x + 0.35 * n, y + 0.35 * n)}


def _pick_manip(context, lat, xy):
    if lat is None or lat.picked is None or not uv_brush.settings(context).lattice_move_manipulator:
        return None
    scale = context.preferences.system.ui_scale or 1.0
    for axis, (x, y) in _manip_handles(context.region, lat, scale).items():
        if (x - xy[0]) ** 2 + (y - xy[1]) ** 2 <= (PICK_PX * scale) ** 2:
            return axis
    return None


def _draw():
    context = bpy.context
    try:
        lat = _state["lattice"]
        if not uv_brush._uv_region(context) or not tool_active(context):
            return
        region = context.region
        v2d = region.view2d
        scale = context.preferences.system.ui_scale or 1.0
        rect = _state.get("rect")
        if rect is not None:            # a lattice being drawn (Use bounding rectangle off)
            a = v2d.view_to_region(rect[0], rect[1], clip=False)
            b = v2d.view_to_region(rect[2], rect[3], clip=False)
            sh = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
            sh.uniform_float("viewportSize", (region.width, region.height))
            sh.uniform_float("lineWidth", 1.0 * scale)
            sh.uniform_float("color", (*RECT_RGB, 1.0))
            gpu.state.blend_set('ALPHA')
            compat.closed_line_batch(sh, [a, (b[0], a[1]), b, (a[0], b[1])]).draw(sh)
            gpu.state.blend_set('NONE')
        if lat is None or not lat.ok:
            return
        rows, cols = lat.shape
        px = [[v2d.view_to_region(*lat.pts[j, i], clip=False) for i in range(cols)] for j in range(rows)]
        lines = []
        for j in range(rows):
            for i in range(cols - 1):
                lines += [px[j][i], px[j][i + 1]]
        for i in range(cols):
            for j in range(rows - 1):
                lines += [px[j][i], px[j + 1][i]]
        gpu.state.blend_set('ALPHA')
        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        shader.uniform_float("viewportSize", (region.width, region.height))
        shader.uniform_float("lineWidth", 1.5 * scale)
        shader.uniform_float("color", (*LINE_RGB, 1.0))
        batch_for_shader(shader, 'LINES', {"pos": lines}).draw(shader)
        pts = gpu.shader.from_builtin('POINT_UNIFORM_COLOR')     # sized on Vulkan / Metal too
        gpu.state.point_size_set(7.0 * scale)
        flat = [px[j][i] for j in range(rows) for i in range(cols)]
        pts.uniform_float("color", (*POINT_RGB, 1.0))
        batch_for_shader(pts, 'POINTS', {"pos": flat}).draw(pts)
        hot = _state["hot"]
        if hot is not None:
            pts.uniform_float("color", (*HOT_RGB, 1.0))
            batch_for_shader(pts, 'POINTS', {"pos": [px[hot[0]][hot[1]]]}).draw(pts)
        handles = _manip_handles(region, lat, scale) if uv_brush.settings(context).lattice_move_manipulator else {}
        if handles:
            o = px[lat.picked[0]][lat.picked[1]]
            for axis, rgb in (("U", AXIS_U_RGB), ("V", AXIS_V_RGB)):
                shader.uniform_float("lineWidth", 2.0 * scale)
                shader.uniform_float("color", (*rgb, 1.0))
                batch_for_shader(shader, 'LINES', {"pos": [o, handles[axis]]}).draw(shader)
                pts.uniform_float("color", (*rgb, 1.0))
                gpu.state.point_size_set(9.0 * scale)
                batch_for_shader(pts, 'POINTS', {"pos": [handles[axis]]}).draw(pts)
            pts.uniform_float("color", (1.0, 0.9, 0.2, 1.0))
            gpu.state.point_size_set(8.0 * scale)
            batch_for_shader(pts, 'POINTS', {"pos": [handles["FREE"]]}).draw(pts)
        gpu.state.point_size_set(1.0)
        gpu.state.blend_set('NONE')
    except (ReferenceError, AttributeError, IndexError):
        pass


class ALLSET_OT_uv_lattice_hover(bpy.types.Operator):
    """Show the lattice around the UVs and the point under the mouse (Lattice UV Tool)"""
    bl_idname = "allset.uv_lattice_hover"
    bl_label = "UV Lattice Hover"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if not uv_brush._uv_region(context):
            return {'PASS_THROUGH'}
        now = time.monotonic()
        if _state["lattice"] is None or now - _state.get("checked", 0.0) > CHECK_S:
            _state["checked"] = now            # a selection change / undo shows on the next look, not every move
            lattice_for(context, uv_brush.stroke_meshes(context))
        lat = _state["lattice"]
        hot = _pick(context.region, lat, (event.mouse_region_x, event.mouse_region_y)) if lat and lat.ok else None
        if hot != _state["hot"]:
            _state["hot"] = hot
            context.area.tag_redraw()
        return {'PASS_THROUGH'}


class ALLSET_OT_uv_lattice_drag(bpy.types.Operator):
    """Drag a lattice point to bend the UVs inside the lattice (Maya Lattice UV Tool)"""
    bl_idname = "allset.uv_lattice_drag"
    bl_label = "Lattice UV Drag"
    bl_options = {'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return uv_brush._uv_region(context)

    def invoke(self, context, event):
        self._meshes = uv_brush.stroke_meshes(context)
        s = uv_brush.settings(context)
        lat = lattice_for(context, self._meshes)
        xy = (event.mouse_region_x, event.mouse_region_y)
        self._start = context.region.view2d.region_to_view(*xy)
        self._axis = _pick_manip(context, lat, xy)
        self._points = None
        if lat is not None and lat.ok:
            if self._axis is not None:
                self._points = [lat.picked]
            else:
                hit = _pick(context.region, lat, xy)
                if hit is not None:
                    self._points = [hit]
                    lat.picked = hit
                else:
                    line = _pick_line(context.region, lat, xy)
                    if line is not None:
                        self._points = list(line)
        if self._points is None:
            if s.lattice_bounding_rect:
                context.area.tag_redraw()
                return {'CANCELLED'}
            _state["rect"] = (*self._start, *self._start)     # draw a new lattice
            self._drawing = True
        else:
            self._drawing = False
            self._pts0 = lat.pts.copy()
            _state["hot"] = self._points[0]
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _finish_rect(self, context):
        r = _state.pop("rect", None)
        if r is None:
            return {'CANCELLED'}
        rect = (min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3]))
        v2d = context.region.view2d
        a = v2d.view_to_region(rect[0], rect[1], clip=False)
        b = v2d.view_to_region(rect[2], rect[3], clip=False)
        if abs(b[0] - a[0]) < 4 or abs(b[1] - a[1]) < 4:      # a click: no lattice
            context.area.tag_redraw()
            return {'CANCELLED'}
        s = uv_brush.settings(context)
        _state["lattice"] = Lattice(self._meshes, s.lattice_columns, s.lattice_rows, rect=rect)
        context.area.tag_redraw()
        return {'CANCELLED'}           # nothing in the UVs changed: no undo step

    def modal(self, context, event):
        lat = _state["lattice"]
        region = context.region
        if region is None or (lat is None and not self._drawing):
            _state.pop("rect", None)
            return {'CANCELLED'}
        if self._drawing:
            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
                uv = region.view2d.region_to_view(event.mouse_x - region.x, event.mouse_y - region.y)
                _state["rect"] = (*self._start, *uv)
                context.area.tag_redraw()
            elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                return self._finish_rect(context)
            elif event.type == 'ESC' and event.value == 'PRESS':
                _state.pop("rect", None)
                context.area.tag_redraw()
                return {'CANCELLED'}
            return {'RUNNING_MODAL'}
        s = uv_brush.settings(context)
        if event.type == 'ESC' and event.value == 'PRESS':
            lat.pts[:] = self._pts0
            lat.apply(self._meshes, s.lattice_falloff)
            for m in self._meshes:
                bmesh.update_edit_mesh(m.ob.data, loop_triangles=False, destructive=False)
            context.area.tag_redraw()
            return {'CANCELLED'}
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            uv = region.view2d.region_to_view(event.mouse_x - region.x, event.mouse_y - region.y)
            d = np.array((uv[0] - self._start[0], uv[1] - self._start[1]))
            if self._axis == 'U':
                d[1] = 0.0
            elif self._axis == 'V':
                d[0] = 0.0
            first = self._points[0]
            to = snapped(context, tuple(self._pts0[first] + d))     # the grabbed point on the pixel grid
            d = np.array(to) - self._pts0[first]
            if self._axis == 'U':
                d[1] = 0.0
            elif self._axis == 'V':
                d[0] = 0.0
            for p in self._points:
                lat.pts[p] = self._pts0[p] + d
            if lat.apply(self._meshes, s.lattice_falloff):
                for m in self._meshes:
                    bmesh.update_edit_mesh(m.ob.data, loop_triangles=False, destructive=False)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            for m in self._meshes:
                bmesh.update_edit_mesh(m.ob.data)
            context.area.tag_redraw()
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


classes = (ALLSET_OT_uv_lattice_hover, ALLSET_OT_uv_lattice_drag)


def register_extra():
    if not _handle:
        _handle.append(bpy.types.SpaceImageEditor.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL'))


def unregister_extra():
    while _handle:
        bpy.types.SpaceImageEditor.draw_handler_remove(_handle.pop(), 'WINDOW')
    _state.clear()
    _state.update(lattice=None, hot=None)
