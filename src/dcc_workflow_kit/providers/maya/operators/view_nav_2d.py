# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya navigation in the 2D editors: Alt+RMB dolly in the UV / Image Editor (``allset.dolly_2d``) and Alt+MMB pan /
Alt+LMB+MMB zoom in the Graph Editor, Dope Sheet, NLA, Node Editor and UV Editor (``allset.nav_2d``, one rule per
editor in ``NAV2D_RULES``). Entry points ``nav2d_rule``, ``nav2d_mode``, ``nav2d_zoom_delta``, ``dolly_2d_step``;
the chord buttons and the Invert Zoom reading come from view_nav.
"""

import bpy

from .view_nav import CHORD_BUTTONS, DOLLY_PX_PER_DOUBLING, chord_held, drag_jump, invert_zoom

# --- Alt+RMB dolly in the UV / Image Editor (B4) ---------------------------------
# Maya dollies 2D panels with Alt+RMB too. IC's image.view_zoom reads the drag axis
# from Blender's Zoom Axis preference (factory Vertical), so like allset.dolly the drag is read here and applied with
# a plain image.view_zoom call with a factor (centred, like Blender's factory "Zoom to Mouse Position" off).
# Maya's UV Editor zooms in with a drag right or down and out with a drag left or up (#325).


def dolly_zoom_factor(dx, dy, ui_scale=1.0, invert=False):
    """Zoom factor for a drag step of (dx, dy) px: the inverse of ``dolly_distance`` (right / up = in,
    reversed with ``invert``)."""
    step = (dx + dy) / (DOLLY_PX_PER_DOUBLING * max(ui_scale, 0.1))
    return 2.0 ** (-step if invert else step)


def dolly_2d_factor(dx, dy, ui_scale=1.0, invert=False):
    """Zoom factor of a UV / Image Editor drag step of (dx, dy) px (y up): right / down = in, left / up = out, so a
    right-and-up drag cancels, like Maya's UV Editor; reversed with ``invert``."""
    return dolly_zoom_factor(dx, -dy, ui_scale, invert)


def dolly_2d_step(context, dx, dy):
    """Zoom the UV / Image Editor of ``context`` by one drag step; the factor applied (1.0 = none)."""
    factor = dolly_2d_factor(dx, dy, context.preferences.system.ui_scale or 1.0, invert_zoom(context))
    if abs(factor - 1.0) <= 1e-6:
        return 1.0
    bpy.ops.image.view_zoom('EXEC_DEFAULT', factor=factor)
    return factor


class ALLSET_OT_dolly_2d(bpy.types.Operator):
    """Zoom the UV / Image Editor in / out with a left / right drag (Maya Alt+RMB dolly)"""
    bl_idname = "allset.dolly_2d"
    bl_label = "Dolly 2D"
    bl_options = {'GRAB_CURSOR', 'BLOCKING'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'IMAGE_EDITOR'

    def invoke(self, context, event):
        self._last = (event.mouse_x, event.mouse_y)
        # the button that started it ends it (modal() reads this)
        self._button = event.type if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE'} else 'RIGHTMOUSE'
        self._zoom0 = tuple(context.space_data.zoom)
        self.applied = 1.0
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def step(self, context, dx, dy):
        """Zoom by one drag step."""
        factor = dolly_2d_step(context, dx, dy)
        self.applied *= factor
        return factor

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            dx, dy = event.mouse_x - self._last[0], event.mouse_y - self._last[1]
            self._last = (event.mouse_x, event.mouse_y)
            if not drag_jump(context.region, dx, dy):
                self.step(context, dx, dy)
            context.area.tag_redraw()
        elif event.type == self._button and event.value == 'RELEASE':
            return {'FINISHED'}
        elif event.type == 'ESC' and event.value == 'PRESS':
            zoom = context.space_data.zoom[0] or 1.0     # zoom limits may have kept some steps out
            bpy.ops.image.view_zoom('EXEC_DEFAULT', factor=self._zoom0[0] / zoom if self._zoom0[0] else 1.0)
            context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


# --- Alt+LMB+MMB zoom in the 2D editors (#325) ------------------------------------------------------------
# Maya's 2D editors zoom like their Alt+RMB while Alt+LMB and Alt+MMB are held together, whichever button comes first,
# and pressing a let-go button again zooms again. Letting go of LMB carries on with the MMB pan in the Graph Editor,
# Dope Sheet and NLA editor (like Maya's Trax Editor); the Node Editor and the UV / Image Editor stop there. Letting go
# of MMB leaves LMB alone, which holds the view still (Maya's Alt+LMB does nothing in these editors) until MMB is
# pressed again or LMB is let go. Blender's view2d.pan / view2d.zoom / image.view_pan only end on the release of the
# button that started them, so one kit modal runs the whole drag: Alt+LMB / Alt+MMB start it where those pans did,
# and each mouse step goes through those operators' exec. The zoom of each editor is the one of its Alt+RMB:
# - AXES (Graph Editor, Dope Sheet, NLA): Blender's drag rule, 1 % of the shown range per px on each axis (the rows
#   of the Dope Sheet / NLA never zoom), Invert Zoom Direction and Zoom to Mouse Position read from the preferences.
# - WIDTH (Node Editor): the same rule read from the left / right drag only, on both axes; an up / down drag does
#   nothing, like Maya's Node Editor. The kit's Alt+RMB there runs this modal too (Blender's zoom would read the
#   Zoom Axis preference instead).
# - DOLLY (UV / Image Editor): the kit's 2D dolly (right / down = in, left / up = out).
NAV2D_ZOOM_PER_PX = 0.01
V2D_CLIPPED = 12000            # what View2D.view_to_region(clip=True) gives outside the shown range
# editor: (zoom, MMB alone pans on once both buttons were held)
NAV2D_RULES = {'GRAPH_EDITOR': ('AXES', True), 'DOPESHEET_EDITOR': ('AXES', True), 'NLA_EDITOR': ('AXES', True),
               'NODE_EDITOR': ('WIDTH', False), 'IMAGE_EDITOR': ('DOLLY', False)}


def nav2d_rule(area, region, space):
    """The (zoom, pan on) rule of the editor when the chord applies there: the main region of the Graph Editor (also
    Drivers), Dope Sheet, NLA, Node Editor and UV / Image Editor. None for the Time Slider (a Timeline: Maya's never
    zooms or pans) and the kit's own rows drawn in an Image Editor (Shelf, Status Line)."""
    if area is None or region is None or region.type != 'WINDOW':
        return None
    rule = NAV2D_RULES.get(area.type)
    if rule is None:
        return None
    if area.type == 'DOPESHEET_EDITOR' and getattr(space, "ui_mode", "") == 'TIMELINE':
        return None
    if area.type == 'IMAGE_EDITOR':
        from ..ui import shelf
        if shelf.is_kit_row(space):
            return None
    return rule


def nav2d_editor(area, region, space):
    """True where the chord applies (``nav2d_rule``)."""
    return nav2d_rule(area, region, space) is not None


def nav2d_mode(held, lmb_pans=True, mmb_pans=True):
    """The Alt drag of the held buttons: both = zoom; MMB alone = pan while ``mmb_pans`` (a drag started with Alt+MMB,
    or once both were held where the editor pans on); LMB alone = pan while ``lmb_pans`` (a drag started with Alt+LMB
    alone, which pans as before); otherwise the view holds still; None once both are let go."""
    held = frozenset(held)
    if held == frozenset(CHORD_BUTTONS):
        return 'ZOOM'
    if held == {'MIDDLEMOUSE'}:
        return 'PAN' if mmb_pans else 'HOLD'
    if held == {'LEFTMOUSE'}:
        return 'PAN' if lmb_pans else 'HOLD'
    return None


def nav2d_zoom_delta(dpx, dpy, size_x, size_y, invert=False, uniform=False):
    """view2d.zoom deltax / deltay (view units taken off each side) for a drag step of (dpx, dpy) px over a shown
    range of size_x by size_y: Blender's drag zoom, right / up = in (reversed with ``invert``); ``uniform``: both axes
    from the left / right drag (Node Editor)."""
    if uniform:
        dpy = dpx
    dx = NAV2D_ZOOM_PER_PX * dpx * size_x
    dy = NAV2D_ZOOM_PER_PX * dpy * size_y
    return (-dx, -dy) if invert else (dx, dy)


def view2d_range(region):
    """(xmin, ymin, xmax, ymax) of the view range a View2D region shows, in view units. Blender fits that range
    into the region less its scroll bars, so the edges are found with the region's clip test."""
    v2d = region.view2d
    cx, cy = v2d.region_to_view(region.width * 0.5, region.height * 0.5)
    lo = v2d.region_to_view(-region.width, -region.height)
    hi = v2d.region_to_view(2.0 * region.width, 2.0 * region.height)

    def edge(inside, outside, axis):
        for _ in range(40):
            mid = (inside + outside) * 0.5
            p = (mid, cy) if axis == 0 else (cx, mid)
            if v2d.view_to_region(p[0], p[1], clip=True)[axis] == V2D_CLIPPED:
                outside = mid
            else:
                inside = mid
        return inside
    return edge(cx, lo[0], 0), edge(cy, lo[1], 1), edge(cx, hi[0], 0), edge(cy, hi[1], 1)


class ALLSET_OT_nav_2d(bpy.types.Operator):
    """Pan a 2D editor with Alt+MMB, zoom it with Alt+LMB+MMB (Maya)"""
    bl_idname = "allset.nav_2d"
    bl_label = "Pan / Zoom 2D View"
    bl_options = {'GRAB_CURSOR', 'BLOCKING', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return nav2d_editor(context.area, context.region, context.space_data)

    def invoke(self, context, event):
        rule = nav2d_rule(context.area, context.region, context.space_data)
        if rule is None or event.type not in {*CHORD_BUTTONS, 'RIGHTMOUSE'}:
            return {'PASS_THROUGH'}
        if event.type == 'RIGHTMOUSE' and rule[0] != 'WIDTH':
            return {'PASS_THROUGH'}             # Blender's own Alt+RMB zoom there
        self._rule, self._pan_on = rule
        self._held = frozenset({event.type})
        self._lmb_pans = self._mmb_pans = True
        rmb = event.type == 'RIGHTMOUSE'
        self._mode = 'ZOOM' if rmb else nav2d_mode(self._held)
        self._last = (event.mouse_x, event.mouse_y)
        self._anchor = (event.mouse_region_x, event.mouse_region_y) if rmb else None
        self._carry = [0.0, 0.0]
        context.window.cursor_modal_set('SCROLL_XY')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _end(self, context):
        context.window.cursor_modal_restore()
        return {'FINISHED'}

    def _pan(self, context, dpx, dpy):
        """Move the view by one mouse step (the content follows the mouse)."""
        if self._rule != 'DOLLY':
            bpy.ops.view2d.pan('EXEC_DEFAULT', deltax=-dpx, deltay=-dpy)
            return
        zoom = context.space_data.zoom[0]       # image.view_pan's offset is in image pixels at that zoom
        if zoom > 0.0:
            bpy.ops.image.view_pan('EXEC_DEFAULT', offset=(-dpx / zoom, -dpy / zoom))

    def _zoom(self, context, dpx, dpy):
        if self._rule == 'DOLLY':
            dolly_2d_step(context, dpx, dpy)
            return
        region = context.region
        v2d = region.view2d
        x0, y0, x1, y1 = view2d_range(region)
        zx, zy = nav2d_zoom_delta(dpx, dpy, x1 - x0, y1 - y0, invert_zoom(context), uniform=self._rule == 'WIDTH')
        if not (zx or zy):
            return
        anchor = self._anchor if context.preferences.inputs.use_zoom_to_mouse else None
        before = v2d.region_to_view(*anchor) if anchor else None
        bpy.ops.view2d.zoom('EXEC_DEFAULT', deltax=zx, deltay=zy)
        if before is None:
            return
        # Zoom to Mouse Position: pan the point under the mouse at the zoom's start back under it (view2d.pan
        # moves by whole px of the region's width / height; the rest carries over to the next step)
        after = v2d.region_to_view(*anchor)
        x0, y0, x1, y1 = view2d_range(region)
        for i, (a, b, size, px) in enumerate(((before[0], after[0], x1 - x0, region.width),
                                              (before[1], after[1], y1 - y0, region.height))):
            if size > 0.0 and px > 0:
                self._carry[i] += (a - b) * px / size
        step = [int(c) for c in self._carry]
        self._carry = [c - s for c, s in zip(self._carry, step)]
        if step[0] or step[1]:
            bpy.ops.view2d.pan('EXEC_DEFAULT', deltax=step[0], deltay=step[1])

    def modal(self, context, event):
        if self._held == {'RIGHTMOUSE'}:            # Alt+RMB zoom: until RMB is let go
            if event.type == 'RIGHTMOUSE' and event.value == 'RELEASE':
                return self._end(context)
        else:
            held = chord_held(self._held, event.type, event.value)
            if held is not None:
                self._held = held
                mode = nav2d_mode(held, self._lmb_pans, self._mmb_pans)
                if mode is None:
                    return self._end(context)
                if mode == 'ZOOM':
                    # from now on LMB alone holds the view still, like Maya; MMB alone pans on where Maya's does
                    self._lmb_pans, self._mmb_pans = False, self._pan_on
                    if self._mode != 'ZOOM':
                        self._anchor = (event.mouse_region_x, event.mouse_region_y)
                        self._carry = [0.0, 0.0]
                self._mode = mode
                self._last = (event.mouse_x, event.mouse_y)
                return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            dpx, dpy = event.mouse_x - self._last[0], event.mouse_y - self._last[1]
            self._last = (event.mouse_x, event.mouse_y)
            if dpx or dpy:
                if self._mode == 'PAN':
                    self._pan(context, dpx, dpy)
                elif self._mode == 'ZOOM':
                    self._zoom(context, dpx, dpy)
            return {'RUNNING_MODAL'}
        if event.type == 'ESC' and event.value == 'PRESS':
            return self._end(context)
        return {'RUNNING_MODAL'}
