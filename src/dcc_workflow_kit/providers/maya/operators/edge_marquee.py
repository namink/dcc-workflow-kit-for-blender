# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya marquee on edges (#438): in mesh edit mode with edge selection, a marquee picks every edge it touches.

Blender's box selection of edges takes the edges that lie wholly inside the box, and only when there is none the
edges that cross it, so a box across a row of faces can't pick the edges along the row without the ones across it.
Maya picks every edge the box touches: one that lies inside it or crosses its border.

``allset.select_through`` (first in the select tools' drag items) hands the drag to ``allset.edge_box`` when the
mesh is in edge select mode and the tool is not the Lasso. ``allset.edge_box`` draws the marquee and, on release,
applies the touched edges with Maya's modifiers (plain replaces, Shift toggles, Ctrl removes, Ctrl+Shift adds): one
undo step. An edge behind the surface counts only when the marquee selects through (the "Marquee Selects Hidden
Components" preference, or X-ray): then like Blender's own drag it is tested where it shows; otherwise one of its
points inside the box must be in front.
"""

import bmesh
import bpy
import gpu
import numpy as np
from bpy.props import BoolProperty, IntProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from .. import compat
from .preselect import caches, project

SAMPLES = 9          # points tested for visibility along the part of an edge inside the box
END_GAP = 0.02       # fraction of the edge kept clear of its ends for those points


# --- pure helpers (tests/test_issue438_edge_marquee.py) --------------------------------------------------------------

def touching(a, b, rect):
    """Which screen segments a[i]-b[i] (N x 2) touch ``rect`` (x0, y0, x1, y1), and the part inside it as segment
    parameters (u0, u1) (Liang-Barsky clipping)."""
    a, b = np.asarray(a, dtype=np.float64).reshape(-1, 2), np.asarray(b, dtype=np.float64).reshape(-1, 2)
    x0, y0, x1, y1 = rect
    d = b - a
    u0, u1 = np.zeros(len(a)), np.ones(len(a))
    ok = np.ones(len(a), dtype=bool)
    for p, q in ((-d[:, 0], a[:, 0] - x0), (d[:, 0], x1 - a[:, 0]), (-d[:, 1], a[:, 1] - y0), (d[:, 1], y1 - a[:, 1])):
        flat = np.abs(p) < 1e-12
        ok &= ~(flat & (q < 0))                       # parallel to this border and outside it
        r = np.where(flat, 0.0, q / np.where(flat, 1.0, p))
        enter, leave = ~flat & (p < 0), ~flat & (p > 0)
        u0 = np.where(enter, np.maximum(u0, r), u0)
        u1 = np.where(leave, np.minimum(u1, r), u1)
    ok &= u0 <= u1
    return ok, u0, u1


def combine(selected, hits, mode):
    """The new selected flag of one edge for a select mode (SET, ADD, SUB, XOR)."""
    if mode == 'ADD':
        return selected or hits
    if mode == 'SUB':
        return selected and not hits
    if mode == 'XOR':
        return selected != hits
    return hits


def click_mode(shift, ctrl):
    """Maya modifiers as a select mode: plain replaces, Shift toggles, Ctrl removes, Ctrl+Shift adds."""
    return {(True, False): 'XOR', (False, True): 'SUB', (True, True): 'ADD'}.get((bool(shift), bool(ctrl)), 'SET')


# --- scene -----------------------------------------------------------------------------------------------------------

def _view(context):
    space, region, rv3d = context.space_data, context.region, context.region_data
    if (context.mode != 'EDIT_MESH' or space is None or space.type != 'VIEW_3D' or region is None
            or region.type != 'WINDOW' or rv3d is None):
        return None
    return region, rv3d


def box_takes(context):
    """The kit draws this drag's marquee itself: edge select mode (vertices and faces off), and not the Lasso tool."""
    if _view(context) is None or tuple(context.tool_settings.mesh_select_mode) != (False, True, False):
        return False
    try:
        tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    except (AttributeError, RuntimeError):
        tool = None
    return tool is None or tool.idname != "builtin.select_lasso"


def _through(context):
    from .. import preferences
    try:
        if preferences.get().select_through:
            return True
    except KeyError:
        pass
    shading = context.space_data.shading
    return shading.show_xray_wireframe if shading.type == 'WIREFRAME' else shading.show_xray


def apply_rect(context, rect, mode):
    """Apply the marquee ``rect`` (region px x0, y0, x1, y1) to the edges of the meshes in edit mode. Returns True when
    a selection changed."""
    view = _view(context)
    if view is None:
        return False
    region, rv3d = view
    persp = rv3d.perspective_matrix
    through = _through(context)
    cs = caches(context)
    found = []
    for ob, c in cs:
        if not len(c.edges):
            continue
        xy, front = project(c.co, persp, region.width, region.height)
        i0, i1 = c.edges[:, 0], c.edges[:, 1]
        ok, u0, u1 = touching(xy[i0], xy[i1], rect)
        ok &= c.eok & front[i0] & front[i1]
        hits = np.zeros(len(c.edges), dtype=bool)
        for i in np.flatnonzero(ok):
            hits[i] = through or _seen(region, rv3d, cs, persp, c.co[i0[i]], c.co[i1[i]], u0[i], u1[i])
        if c.bm.is_valid:
            found.append((ob, c.bm, hits))
    # bm.edges runs in the cache's edge order; hidden edges keep their state
    before = {ob.name: [e.select for e in bm.edges] for ob, bm, _hits in found}
    from . import symmetry_select       # #445: with Symmetry on the partners of the touched edges too
    if symmetry_select.applies(context):
        picked = {ob.name: {int(k) for k in np.flatnonzero(hits)} for ob, _bm, hits in found}
        for name, idx in symmetry_select.partners(context, 'EDGE', picked).items():
            for ob, bm, hits in found:
                if ob.name == name:
                    for k in idx:
                        if not bm.edges[k].hide:
                            hits[k] = True
    changed = False
    for ob, bm, hits in found:
        old = before[ob.name]
        new = [s if e.hide else combine(s, bool(hits[k]), mode) for k, (e, s) in enumerate(zip(bm.edges, old))]
        if all(e.select == n for e, n in zip(bm.edges, new)) and new == old:
            continue
        for e, n in zip(bm.edges, new):             # deselect first: a selected edge then keeps its vertices
            if e.select and not n:
                e.select_set(False)
        for e, n in zip(bm.edges, new):
            if n:
                e.select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
        changed = changed or new != old
    return changed


def _seen(region, rv3d, cs, persp, a, b, u0, u1):
    """Some point of the world edge a-b whose screen part inside the box runs from u0 to u1 is in front."""
    m = np.asarray(persp, dtype=np.float64)
    wa = float(m[3, :3] @ a + m[3, 3])
    wb = float(m[3, :3] @ b + m[3, 3])
    for u in np.linspace(u0, u1, SAMPLES):
        t = u * wa / ((1.0 - u) * wb + u * wa)       # screen-straight u -> along the edge in 3D (perspective)
        # off the ends: an edge behind the surface often ends at a corner that shows, which proves nothing
        t = min(max(t, END_GAP), 1.0 - END_GAP)
        p = Vector(a + (b - a) * t)
        p2 = view3d_utils.location_3d_to_region_2d(region, rv3d, p)
        if p2 is None:
            continue
        o = view3d_utils.region_2d_to_origin_3d(region, rv3d, p2)
        d = p - o
        dist = d.length
        if dist < 1e-12:
            return True
        d /= dist
        if not any((h := c.ray(o, d)) is not None and h[0] < dist * (1.0 - 1e-4) - 1e-6 for _ob, c in cs):
            return True
    return False


def start_box(context, event):
    """Start ``allset.edge_box`` from the drag that ``event`` (a LMB CLICK_DRAG) began."""
    x = getattr(event, "mouse_prev_press_x", event.mouse_x) - context.region.x
    y = getattr(event, "mouse_prev_press_y", event.mouse_y) - context.region.y
    bpy.ops.allset.edge_box('INVOKE_DEFAULT', x=x, y=y, shift=event.shift, ctrl=event.ctrl)


class ALLSET_OT_edge_box(bpy.types.Operator):
    """Marquee on edges: every edge it touches (Shift toggles, Ctrl removes, Ctrl+Shift adds)"""
    bl_idname = "allset.edge_box"
    bl_label = "Box Select"
    bl_options = {'INTERNAL'}

    x: IntProperty(options={'HIDDEN', 'SKIP_SAVE'})
    y: IntProperty(options={'HIDDEN', 'SKIP_SAVE'})
    shift: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})
    ctrl: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        if _view(context) is None:
            return {'CANCELLED'}
        self._start = (self.x, self.y)
        self._end = (event.mouse_region_x, event.mouse_region_y)
        self._region = context.region
        self._handle = context.space_data.draw_handler_add(self._draw, (), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        self._region.tag_redraw()
        return {'RUNNING_MODAL'}

    def _draw(self):
        if bpy.context.region != self._region:
            return
        (x0, y0), (x1, y1) = self._start, self._end
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        loop = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        gpu.state.blend_set('ALPHA')
        for width, color in ((3.0, (0.0, 0.0, 0.0, 0.6)), (1.0, (1.0, 1.0, 1.0, 0.9))):
            gpu.state.line_width_set(width)
            shader.uniform_float("color", color)
            compat.closed_line_batch(shader, loop).draw(shader)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')

    def _stop(self, context):
        context.space_data.draw_handler_remove(self._handle, 'WINDOW')
        self._region.tag_redraw()

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._end = (event.mouse_region_x, event.mouse_region_y)
            self._region.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._stop(context)
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self._end = (event.mouse_region_x, event.mouse_region_y)
            self._stop(context)
            (x0, y0), (x1, y1) = self._start, self._end
            rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            with context.temp_override(region=self._region):
                if apply_rect(context, rect, click_mode(self.shift, self.ctrl)):
                    bpy.ops.ed.undo_push(message="Box Select")
            for area in context.screen.areas if context.screen else ():
                area.tag_redraw()
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


classes = (ALLSET_OT_edge_box,)
