# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya viewport panel bar in the Maya Workflow Kit layout: the panel menu bar alone, and the panel toolbar under it.

Maya 2022: every model panel has a menu bar
(View Shading Lighting Show Renderer Panels) and under it a toolbar of small icons in groups —
camera, gates and grid, shading modes and lights, effects, isolate / X-ray — then exposure and gamma fields and the
colour management view. Blender's 3D View header mixed Maya's menus with its own editor-type button, mode selector,
transform orientation, pivot, snapping, proportional editing, overlays and shading.

In 3D Views of the Maya Workflow Kit layout (a screen with the Maya strip, and a panel torn off it into a window of
its own) the class's own draw of ``VIEW3D_HT_header`` is
replaced by the Maya menu bar and the tool header's by the Maya panel toolbar (like ``editor_chrome``: only the
class's own draw function, so UI appended by others still draws; restored on unregister). Other layouts keep
Blender's header with the Maya menus (``panel_menus``). Icons are kit-drawn (``status_icons``), no Maya assets.
"""

import json
import math

import bpy
import numpy as np

from . import panel_menus, status_icons, toolbar_fit
from .toolbar_fit import BAR_UNITS
from .status_icons import DARK, DIM, GREY, LIGHT, TEAL, TEAL_DARK, TEAL_LIGHT, letter

GREY_OP = "allset.menu_unavailable"


# --- glyphs (16 px panel toolbar; drawn by status_icons at the icon size) ----

def _camera(cv, y=0.0):
    """Maya camera: a body with the lens cone opening to the right."""
    cv.rect(0.04, 0.30 + y, 0.60, 0.70 + y, GREY)
    cv.poly([(0.66, 0.50 + y), (0.96, 0.26 + y), (0.96, 0.74 + y)], GREY)


def g_cam_select(cv):
    _camera(cv)


def g_cam_lock(cv):
    _camera(cv, -0.16)
    cv.ring(0.32, 0.50, 0.12, 0.08, TEAL, 0, 180)
    cv.rect(0.14, 0.52, 0.50, 0.94, TEAL)
    cv.rect(0.30, 0.64, 0.36, 0.80, DARK)


def g_cam_attr(cv):
    _camera(cv, -0.16)
    status_icons.gear(cv, 0.32, 0.70, 0.27, TEAL)


def g_bookmark(cv):
    cv.poly([(0.24, 0.04), (0.76, 0.04), (0.76, 0.96), (0.50, 0.72), (0.24, 0.96)], GREY)


def g_image_plane(cv):
    """Maya: a teal plane standing on a grey floor."""
    cv.polyline([(0.04, 0.94), (0.60, 0.94), (0.94, 0.70), (0.40, 0.70), (0.04, 0.94)], 0.07, GREY)
    cv.poly([(0.30, 0.82), (0.30, 0.30), (0.70, 0.04), (0.70, 0.56)], TEAL)


def g_pan_zoom(cv):
    """Maya: a four-way move arrow with a teal magnifier."""
    cv.line(0.34, 0.08, 0.34, 0.62, 0.08, GREY)
    cv.line(0.06, 0.34, 0.62, 0.34, 0.08, GREY)
    cv.poly([(0.34, 0.0), (0.48, 0.16), (0.20, 0.16)], GREY)
    cv.poly([(0.0, 0.34), (0.16, 0.20), (0.16, 0.48)], GREY)
    cv.poly([(0.68, 0.34), (0.52, 0.20), (0.52, 0.48)], GREY)
    cv.ring(0.66, 0.64, 0.16, 0.09, TEAL)
    cv.line(0.54, 0.76, 0.34, 0.96, 0.12, TEAL)


def g_grease(cv):
    cv.line(0.84, 0.12, 0.38, 0.58, 0.20, GREY)
    cv.poly([(0.26, 0.56), (0.40, 0.70), (0.14, 0.82)], TEAL)
    cv.ring(0.56, 0.80, 0.14, 0.07, TEAL, 180, 360)


def g_grid(cv):
    cv.rect(0.10, 0.10, 0.90, 0.90, GREY)
    for i in range(3):
        for j in range(3):
            x, y = 0.18 + i * 0.25, 0.18 + j * 0.25
            cv.rect(x, y, x + 0.14, y + 0.14, DARK)


def _gate(cv):
    cv.frame(0.02, 0.10, 0.98, 0.90, 0.10, GREY)


def g_film_gate(cv):
    cv.frame(0.02, 0.10, 0.98, 0.90, 0.20, GREY)
    for i in range(5):
        x = 0.12 + i * 0.17
        cv.rect(x, 0.15, x + 0.08, 0.22, DARK)
        cv.rect(x, 0.78, x + 0.08, 0.85, DARK)


def g_res_gate(cv):
    _gate(cv)
    cv.circle(0.5, 0.5, 0.20, TEAL)


def g_gate_mask(cv):
    cv.rect(0.02, 0.10, 0.98, 0.90, GREY)
    cv.circle(0.5, 0.5, 0.27, DARK)


def g_field_chart(cv):
    _gate(cv)
    for k in range(4):
        y = 0.22 + k * 0.16
        cv.rect(0.46, y, 0.54, y + 0.08, TEAL)
    for k in range(6):
        x = 0.16 + k * 0.13
        if abs(x - 0.47) > 0.06:
            cv.rect(x, 0.46, x + 0.08, 0.54, TEAL)


def g_safe_action(cv):
    _gate(cv)
    cv.poly([(0.18, 0.80), (0.38, 0.44), (0.58, 0.80)], TEAL)
    cv.circle(0.66, 0.36, 0.13, TEAL)


def g_safe_title(cv):
    _gate(cv)
    cv.rect(0.26, 0.24, 0.74, 0.36, TEAL)
    cv.rect(0.44, 0.24, 0.56, 0.78, TEAL)


# isometric cube corners (shading icons)
_TOP = [(0.50, 0.04), (0.92, 0.24), (0.50, 0.44), (0.08, 0.24)]
_LEFT = [(0.08, 0.24), (0.50, 0.44), (0.50, 0.96), (0.08, 0.76)]
_RIGHT = [(0.50, 0.44), (0.92, 0.24), (0.92, 0.76), (0.50, 0.96)]


def _solid_cube(cv):
    cv.poly(_TOP, TEAL_LIGHT)
    cv.poly(_LEFT, TEAL)
    cv.poly(_RIGHT, TEAL_DARK)


def _wire_cube(cv, colour, w=0.07):
    cv.polyline(_TOP + [_TOP[0]], w, colour)
    cv.polyline([(0.08, 0.24), (0.08, 0.76), (0.50, 0.96), (0.92, 0.76), (0.92, 0.24)], w, colour)
    cv.line(0.50, 0.44, 0.50, 0.96, w, colour)


def g_wire(cv):
    _wire_cube(cv, GREY)
    # hidden edges, dimmer
    cv.polyline([(0.08, 0.76), (0.50, 0.56), (0.92, 0.76)], 0.05, DIM)
    cv.line(0.50, 0.04, 0.50, 0.56, 0.05, DIM)


def g_smooth(cv):
    _solid_cube(cv)


def g_wire_on_shaded(cv):
    _solid_cube(cv)
    _wire_cube(cv, LIGHT, 0.06)


def _disc(cv):
    return cv.disc_mask(0.5, 0.5, 0.44)


def _checker(cv, mask, n=4):
    c = ((np.floor(cv.x * n) + np.floor(cv.y * n)) % 2) == 0
    cv.fill(mask, GREY)
    cv.fill(mask & c, DARK)


def g_default_mat(cv):
    d = _disc(cv)
    _checker(cv, d & (cv.x >= 0.5))
    cv.fill(d & (cv.x < 0.5), GREY)


def g_textured(cv):
    _checker(cv, _disc(cv), 5)


def g_all_lights(cv):
    cv.circle(0.5, 0.42, 0.22, GREY)
    cv.rect(0.40, 0.58, 0.60, 0.80, GREY)
    cv.rect(0.42, 0.84, 0.58, 0.92, GREY)
    for a in (180, 135, 90, 45, 0):
        r = math.radians(a)
        cv.line(0.5 + math.cos(r) * 0.32, 0.42 - math.sin(r) * 0.32,
                0.5 + math.cos(r) * 0.44, 0.42 - math.sin(r) * 0.44, 0.08, GREY)


def g_shadows(cv):
    cv.poly([(0.04, 0.84), (0.30, 0.60), (0.62, 0.60), (0.36, 0.84)], GREY)
    for k in range(3):
        cv.line(0.12 + k * 0.10, 0.80, 0.30 + k * 0.10, 0.64, 0.05, DARK)
    cv.circle(0.64, 0.40, 0.30, TEAL)


def g_ssao(cv):
    """Maya: a grey ball sitting in a teal occlusion pool."""
    cv.poly([(0.04, 0.74), (0.50, 0.58), (0.96, 0.74), (0.50, 0.94)], TEAL)
    cv.circle(0.5, 0.40, 0.32, GREY)
    cv.ring(0.5, 0.40, 0.32, 0.06, DIM, 200, 340)


def g_motion_blur(cv):
    cv.circle(0.30, 0.66, 0.24, DARK)
    cv.circle(0.46, 0.50, 0.26, DIM)
    cv.circle(0.64, 0.34, 0.28, GREY)


def g_aa(cv):
    """Maya: a ring, smooth teal on the left, stair-stepped grey on the right."""
    cv.ring(0.5, 0.5, 0.36, 0.14, TEAL, 90, 270)
    for x0, y0, x1, y1 in ((0.50, 0.08, 0.66, 0.22), (0.66, 0.16, 0.80, 0.34), (0.76, 0.32, 0.90, 0.68),
                           (0.66, 0.66, 0.80, 0.84), (0.50, 0.78, 0.66, 0.92)):
        cv.rect(x0, y0, x1, y1, GREY)


def g_dof(cv):
    m = cv.rect_mask(0.04, 0.04, 0.54, 0.54)
    c = ((np.floor(cv.x * 12) + np.floor(cv.y * 12)) % 2) == 0
    cv.fill(m, TEAL_DARK)
    cv.fill(m & c, TEAL)
    cv.rect(0.34, 0.34, 0.96, 0.96, TEAL)


def g_isolate(cv):
    for (ax, ay, bx, by) in ((0.06, 0.06, 0.30, 0.06), (0.46, 0.06, 0.66, 0.06), (0.06, 0.06, 0.06, 0.30),
                             (0.06, 0.46, 0.06, 0.66), (0.66, 0.06, 0.66, 0.26), (0.06, 0.66, 0.26, 0.66)):
        cv.line(ax, ay, bx, by, 0.10, TEAL)
    status_icons.arrow_cursor(cv, 0.44, 0.40, 0.56)


def _xray_tile(cv):
    cv.rect(0.0, 0.0, 1.0, 1.0, DARK)


def g_xray(cv):
    """Maya: two overlapping squares on a dark tile, the overlap lighter (see-through)."""
    _xray_tile(cv)
    cv.rect(0.38, 0.12, 0.88, 0.62, DIM)
    cv.rect(0.12, 0.38, 0.62, 0.88, DIM)
    cv.rect(0.38, 0.38, 0.62, 0.62, LIGHT)


def g_xray_comp(cv):
    """Maya: the front square solid, the back one only an outline; teal component points on the front one."""
    _xray_tile(cv)
    cv.frame(0.38, 0.12, 0.88, 0.62, 0.08, GREY)
    cv.rect(0.12, 0.38, 0.62, 0.88, GREY)
    for x, y in ((0.12, 0.38), (0.62, 0.38), (0.12, 0.88), (0.62, 0.88)):
        cv.circle(x, y, 0.09, TEAL)


def g_xray_joints(cv):
    _xray_tile(cv)
    cv.frame(0.10, 0.10, 0.90, 0.90, 0.07, GREY)
    cv.poly([(0.28, 0.66), (0.38, 0.74), (0.74, 0.32), (0.68, 0.26)], GREY)
    cv.circle(0.30, 0.70, 0.11, TEAL)
    cv.circle(0.72, 0.28, 0.08, GREY)


def g_exposure(cv):
    """Maya: a camera iris (grey disc, dark blades)."""
    cv.circle(0.5, 0.5, 0.44, GREY)
    for k in range(6):
        a = math.radians(k * 60 + 15)
        b = math.radians(k * 60 + 75)
        cv.line(0.5 + math.cos(a) * 0.14, 0.5 + math.sin(a) * 0.14,
                0.5 + math.cos(b) * 0.40, 0.5 + math.sin(b) * 0.40, 0.05, DARK)
    cv.circle(0.5, 0.5, 0.12, DARK)


def g_gamma(cv):
    """Maya: a half-filled disc on a bracket (gamma)."""
    cv.polyline([(0.50, 0.06), (0.90, 0.06), (0.90, 0.94), (0.50, 0.94)], 0.10, GREY)
    m = cv.disc_mask(0.5, 0.5, 0.34)
    cv.fill(m & (cv.x < 0.5), GREY)
    cv.ring(0.5, 0.5, 0.34, 0.07, GREY, 270, 90)


def g_color_mgmt(cv):
    """Maya's colour management OFF button: a grey disc with OFF (the kit shows ON while colour management is on)."""
    cv.circle(0.5, 0.5, 0.46, GREY)
    for i, ch in enumerate("OFF"):
        letter(cv, ch, 0.18 + i * 0.23, 0.36, 0.28, 0.07, DARK)


def g_color_mgmt_on(cv):
    cv.circle(0.5, 0.5, 0.46, TEAL)
    for i, ch in enumerate("ON"):
        letter(cv, ch, 0.28 + i * 0.27, 0.36, 0.28, 0.07, DARK)


def g_more(cv):
    """Maya's overflow arrow (») at the end of a toolbar that doesn't fit its panel."""
    for dx in (0.0, 0.36):
        cv.polyline([(0.16 + dx, 0.24), (0.42 + dx, 0.50), (0.16 + dx, 0.76)], 0.12, LIGHT)


GLYPHS = {name[2:]: fn for name, fn in globals().items() if name.startswith("g_")}


# --- the toolbar (Maya 2022 order) -----

# The toolbar rows: ui/panel_menu_data.TOOLBAR (bpy-free, counted by tools/menu_count.py).
from . import panel_menu_data  # noqa: E402
from .panel_menu_data import TOOLBAR  # noqa: E402


def _flat(layout, on, left=False):
    """A button row, frameless unless on (Maya); ``left``: icon + text left-aligned (a » popover line)."""
    sub = layout.row(align=True)
    if left:
        sub.alignment = 'LEFT'
    if not on:
        sub.emboss = 'NONE'
    return sub


def _icon(name):
    return status_icons.icon("pt_" + name)


# Maya's colour management section after the groups: exposure icon + field, gamma icon + field, colour management
# icon + view transform (widths in widget units; the fields are ``ui_units_x`` sub-rows).
CM_UNITS = (1, 2.2, 1, 2.2, 1, 6)
CM_FIELDS = (("EXPOSURE", "exposure", "Exposure"), ("GAMMA", "gamma", "Gamma"))


def fit_groups():
    """Unit widths of the toolbar groups in Maya's order (``toolbar_fit``), the colour management section last."""
    return [[1] * len(g) for g in TOOLBAR] + [list(CM_UNITS)]


def _draw_item(row, context, item, text=""):
    """One toolbar button (``text`` = its Maya name, in the » popover)."""
    space = context.space_data
    glyph, kind, data, label = item
    if kind == "set":
        on = bool(panel_menus.state(context, data))
        sub = _flat(row, on, bool(text))
        if data in panel_menus.CAMERA_KEYS:
            sub.enabled = panel_menus.view_camera(context) is not None
        elif data in ("SELECT_CAMERA", "BOOKMARK"):
            sub.enabled = panel_menus.has_panel_camera(context)
        op = sub.operator(panel_menus.ALLSET_OT_panel_set.bl_idname, text=text, icon_value=_icon(glyph),
                          depress=on)
        op.key, op.toggle = data, True
    elif kind == "prop":
        owner = panel_menus._owner(space, context, data[0])
        on = bool(getattr(owner, data[1]))
        _flat(row, on, bool(text)).prop(owner, data[1], text=text, icon_value=_icon(glyph), toggle=True)
    elif kind == "run":
        op = _flat(row, False, bool(text)).operator(panel_menus.ALLSET_OT_panel_run.bl_idname, text=text,
                                        icon_value=_icon(glyph))
        op.op = data[0]
        op.props = json.dumps(data[1])
    else:
        op = _flat(row, False, bool(text)).operator(GREY_OP, text=text, icon_value=_icon(glyph))
        op.item = panel_menu_data.toolbar_path(label)


def _bar(layout):
    bar = layout.row(align=True)
    bar.ui_units_x = BAR_UNITS
    bar.label(text="", icon_value=status_icons.icon("bar"))


def _menu_row(layout):
    """A line of the » popover: icon + Maya name, left-aligned like a Maya menu item."""
    row = layout.row(align=True)
    row.alignment = 'LEFT'
    return row


def _draw_cm(layout, context, menu=False):
    """Exposure / gamma fields and the view transform (Maya's colour management controls). Maya's exposure / gamma
    icons switch between the default and the last value; the colour management icon is a check box
    (Maya panel toolbar). ``menu``: one line per control (the » popover)."""
    vs = context.scene.view_settings
    set_op = panel_menus.ALLSET_OT_panel_set.bl_idname

    def line():
        """(icon button layout, field layout) of one control."""
        if not menu:
            return layout, layout
        split = layout.split(factor=0.6, align=True)
        return _menu_row(split), split

    for key, prop, label in CM_FIELDS:
        left, row = line()
        _flat(left, False, menu).operator(set_op, text=label if menu else "", icon_value=_icon(prop)).key = key
        sub = row.row(align=True)
        if not menu:
            sub.ui_units_x = CM_UNITS[1]
        sub.prop(vs, prop, text="")
    left, row = line()
    cm = bool(panel_menus.state(context, "CM_ENABLE"))
    op = _flat(left, cm, menu).operator(set_op, text="Colour Management" if menu else "",
                                 icon_value=_icon("color_mgmt_on" if cm else "color_mgmt"), depress=cm)
    op.key, op.toggle = "CM_ENABLE", True
    sub = row.row(align=True)
    if not menu:
        sub.ui_units_x = CM_UNITS[-1]
    sub.prop(vs, "view_transform", text="")


# area pointer -> index of the first group in the » popover (written by the tool header draw, read by the popover;
# a plain dict, no ID data is written while drawing)
_FIRST_HIDDEN = {}


def shown_groups(context):
    """How many groups (``fit_groups`` order) the tool header of this view shows (Maya's » overflow, #52)."""
    region = context.region
    system = context.preferences.system
    if region is None or region.type != 'TOOL_HEADER':
        return len(TOOLBAR) + 1
    return toolbar_fit.fit(fit_groups(), region.width, system.ui_scale, system.pixel_size)


def draw_toolbar(layout, context):
    n = shown_groups(context)
    if context.area is not None:
        _FIRST_HIDDEN[context.area.as_pointer()] = n
    for group in TOOLBAR[:n]:
        _bar(layout)
        row = layout.row(align=True)
        for item in group:
            _draw_item(row, context, item)
    if n > len(TOOLBAR):
        _bar(layout)
        _draw_cm(layout.row(align=True), context)
        return
    # Maya's overflow arrow at the right end of the bar: the groups that don't fit, in a popover
    layout.separator_spacer()
    sub = layout.row(align=True)
    sub.ui_units_x = toolbar_fit.MORE_UNITS
    sub.popover(ALLSET_PT_panel_toolbar_more.bl_idname, text="", icon_value=_icon("more"))


class ALLSET_PT_panel_toolbar_more(bpy.types.Panel):
    """More panel toolbar buttons: the ones that don't fit this view's width"""
    bl_idname = "ALLSET_PT_panel_toolbar_more"
    bl_label = "More Panel Toolbar Buttons"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 12

    def draw(self, context):
        space = context.space_data
        if context.area is None or space is None or space.type != 'VIEW_3D':
            return
        first = _FIRST_HIDDEN.get(context.area.as_pointer(), 0)
        col = self.layout.column()
        for i in range(first, len(TOOLBAR) + 1):
            if i > first:
                col.separator(type='LINE')
            if i < len(TOOLBAR):
                for item in TOOLBAR[i]:
                    _draw_item(_menu_row(col), context, item, text=item[3])
            else:
                _draw_cm(col, context, menu=True)


# --- right-click menus ----------------------------------------------------------------------------------------
# Maya: right-click on the camera icon at the left of the panel toolbar lists the scene's cameras (picking one looks
# through it in that view), on Bookmarks the camera's bookmarks, on 2D Pan/Zoom its 2D bookmarks
# (ui/camera_bookmarks.py). Blender opens its own button context menu on a right-click over a button before any
# keymap runs, so ``allset.pt_hover`` (3D View Generic MOUSEMOVE, first; poll = tool header) remembers which of these
# buttons the mouse is over and starts ``allset.pt_camera_rmb``, a window modal (window handlers run before the
# UI) that lives while the mouse is in that tool header and opens the button's menu on a right-click there.

RMB_MENUS = {"cam_select": "ALLSET_MT_panel_cameras", "bookmark": "ALLSET_MT_pt_bookmarks",
             "pan_zoom": "ALLSET_MT_pt_pan_zoom"}
_over_camera = {}     # window pointer -> the right-click menu of the button under the mouse ("" = none; last move)
_watching = set()


def _rmb_menu(context, event):
    """The right-click menu of the first group's button under the mouse, else "" (Blender's layout can't report
    where it put a button: its x comes from the same layout rules as the » overflow, ``toolbar_fit.starts``)."""
    region = context.region
    if region is None or region.type != 'TOOL_HEADER' or shown_groups(context) < 1:
        return ""
    system = context.preferences.system
    x0 = toolbar_fit.starts(fit_groups(), system.ui_scale, system.pixel_size)[0]
    u = toolbar_fit.unit(system.ui_scale, system.pixel_size)
    i = (event.mouse_region_x - x0) // u if event.mouse_region_x >= x0 else -1
    if not 0 <= i < len(TOOLBAR[0]):
        return ""
    return RMB_MENUS.get(TOOLBAR[0][i][0], "")


STARTUP_VIEWS = (("persp", 'PERSP'), ("top", 'TOP'), ("front", 'FRONT'), ("side", 'RIGHT'))


def camera_rows(context):
    """The camera list's rows like Maya: every camera of the scene once, in name order (perspective and
    orthographic together, hidden ones too), the startup persp / top / front / side as the kit's view rows."""
    rows = {name: panel_menu_data._view(name, view) for name, view in STARTUP_VIEWS}
    for ob in panel_menus._cameras(context, None):
        rows[ob.name] = ob.name
    return [rows[name] for name in sorted(rows)]


class ALLSET_MT_panel_cameras(bpy.types.Menu):
    """The scene's cameras: pick one to look through it in this view"""
    bl_idname = "ALLSET_MT_panel_cameras"
    bl_label = "Cameras"

    def draw(self, context):
        layout = self.layout
        for row in camera_rows(context):
            if isinstance(row, tuple):
                panel_menus.draw_rows(layout, context, [row])
            else:
                layout.operator(panel_menus.ALLSET_OT_panel_look_through.bl_idname, text=row,
                                icon='OUTLINER_OB_CAMERA').camera = row
        layout.separator()
        layout.operator(panel_menus.ALLSET_OT_panel_new_persp.bl_idname, text="New Perspective")
        layout.menu(panel_menus.ALLSET_MT_panel_new_ortho.bl_idname, text="New Orthographic")
        # Blender has no stereo camera rig to look through: the Panels > Stereo notice
        layout.operator(panel_menus.GREY_OP, text="Stereo Cameras").item = \
            panel_menu_data.item_path("ALLSET_MT_panel_panels", "Stereo")


class ALLSET_OT_pt_hover(bpy.types.Operator):
    """Panel toolbar: watch for a right-click on the camera icon"""
    bl_idname = "allset.pt_hover"
    bl_label = "Panel Toolbar Hover"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        region = context.region
        return region is not None and region.type == 'TOOL_HEADER'

    def invoke(self, context, event):
        window = context.window
        if window is None or not maya_layout(context):
            return {'PASS_THROUGH'}
        ptr = window.as_pointer()
        over = _rmb_menu(context, event)
        _over_camera[ptr] = over
        if over and ptr not in _watching:
            bpy.ops.allset.pt_camera_rmb('INVOKE_DEFAULT', True)
        return {'PASS_THROUGH'}


class ALLSET_OT_pt_camera_rmb(bpy.types.Operator):
    """Right-click on the panel toolbar's camera, Bookmarks or 2D Pan/Zoom icon: its menu"""
    bl_idname = "allset.pt_camera_rmb"
    bl_label = "Camera List"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        region = context.region
        if region is None or context.window is None:
            return {'CANCELLED'}
        self._win = context.window.as_pointer()
        self._window = context.window
        self._rect = (region.x, region.y, region.x + region.width, region.y + region.height)
        _watching.add(self._win)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _inside(self, event):
        x0, y0, x1, y1 = self._rect
        return x0 <= event.mouse_x < x1 and y0 <= event.mouse_y < y1

    def _finish(self):
        _watching.discard(self._win)
        _over_camera.pop(self._win, None)
        return {'FINISHED', 'PASS_THROUGH'}

    def modal(self, context, event):
        try:
            self._window.screen
        except ReferenceError:
            _watching.discard(self._win)
            return {'CANCELLED', 'PASS_THROUGH'}
        if event.type == 'MOUSEMOVE' and not self._inside(event):
            return self._finish()
        menu = _over_camera.get(self._win)
        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS' and self._inside(event) and menu:
            bpy.ops.wm.call_menu(name=menu)
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}


# --- header patch ---------------------------------------------------------------------------------------

def torn_off(context):
    """The window is a panel torn off the Maya Workflow Kit layout (Panels > Tear Off / Tear Off Copy): a window of
    one area that shows a Maya workspace. Like a torn-off Maya panel it keeps the panel menu bar and toolbar."""
    window = getattr(context, "window", None)
    if window is None:
        return False
    from . import ipr_window, maya_dock
    from .. import switch
    try:
        if ipr_window.window() == window:        # the IPR window is a render picture, not a panel
            return False
        return maya_dock.is_floating(window) and switch.is_maya_workspace(window.workspace)
    except (AttributeError, ReferenceError):
        return False


def maya_screen(context):
    """The window shows the Maya Workflow Kit layout: its screen has the Maya strip, or it is a panel torn off it."""
    from .shelf import strip_area
    return context.screen is not None and (strip_area(context.screen) is not None or torn_off(context))


def maya_layout(context):
    """A 3D View of the Maya Workflow Kit layout (its screen has the Maya strip, or a panel torn off it)."""
    area = context.area
    return (area is not None and area.type == 'VIEW_3D' and maya_screen(context)
            and panel_menus._enabled(context))


def _header(self, context):
    if not maya_layout(context):
        return _orig["header"](self, context)
    layout = self.layout
    row = layout.row(align=True)
    for label, idname in panel_menus.BAR:
        row.menu(idname, text=label)
    return None


def _tool_header(self, context):
    if not maya_layout(context):
        return _orig["tool_header"](self, context)
    draw_toolbar(self.layout, context)
    return None


HEADERS = (("header", "VIEW3D_HT_header", _header), ("tool_header", "VIEW3D_HT_tool_header", _tool_header))
_orig = {}


def _own_index(cls_name, funcs):
    """Index of the class's own draw among its draw functions (something may have been prepended)."""
    for i, f in enumerate(funcs):
        if getattr(f, "__qualname__", "") == f"{cls_name}.draw":
            return i
    return 0


def patch_headers():
    for key, name, fn in HEADERS:
        funcs = getattr(bpy.types, name)._dyn_ui_initialize()
        i = _own_index(name, funcs)
        if key not in _orig:
            _orig[key] = funcs[i]
        funcs[i] = fn


def unpatch_headers():
    for key, name, fn in HEADERS:
        if key in _orig:
            funcs = getattr(bpy.types, name)._dyn_ui_initialize()
            funcs[funcs.index(fn)] = _orig.pop(key)


CLASSES = (ALLSET_PT_panel_toolbar_more, ALLSET_MT_panel_cameras, ALLSET_OT_pt_hover, ALLSET_OT_pt_camera_rmb)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for name, fn in GLYPHS.items():
        status_icons.EXTRA["pt_" + name] = fn
    patch_headers()


def unregister():
    unpatch_headers()
    for name in GLYPHS:
        status_icons.EXTRA.pop("pt_" + name, None)
    _FIRST_HIDDEN.clear()
    _over_camera.clear()
    _watching.clear()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
