# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws the Maya outliner pane over the Graph Editor's channel region (node rows, coloured attribute rows, pins,
scroll bar) and handles its clicks, wheel scrolling and Pin / Unpin Channel. Entry points ``draw_channels`` (draw
handler), ``pick_row``, ``row_at``; the rows come from ``graph_list``.
"""

import blf
import bpy
import gpu
from bpy.props import BoolProperty, IntProperty
from gpu_extras.batch import batch_for_shader

from . import draw_replay, graph_layers
from .draw_replay import call
from .editor_kinds import enabled, is_graph
from .graph_channels import TEXT, _themed, attr_color, attr_label, node_key, node_name
from .graph_list import (ATTR_KINDS, _expanded, _pinned, _up_label, is_pinned, listed_curves, listed_nodes, row_id,
                         rows, upstream_curves)
from .graph_list_sync import _redraw_editors, sync


BACK = (0.267, 0.267, 0.267, 1.0)        # outliner pane #444444
SELECT = (0.322, 0.522, 0.651, 1.0)      # selection blue #5285a6 (kept with any theme)
THUMB = (0.36, 0.36, 0.36, 1.0)          # Maya scroll bar thumb (right of the rows)
_scroll = {}                             # area pointer -> first row shown
# Rows the user picked in this outliner (Maya highlights only those, not every attribute of a selected node), valid
# while the scene selection is the one they were picked under.
_picked = {"ids": set(), "sig": None}


def node_selected(context, kind, node):
    """Is the row's node selected in the scene (Maya loads the selection into the Graph Editor highlighted)?"""
    from . import channel_box
    if kind == "JOINT":
        arm = node.id_data
        return channel_box.bone_selected(node) if arm.mode == 'POSE' else arm.select_get()
    if kind == "CHARACTER":
        from ..operators import character_sets
        return node in character_sets.picked(context)
    if kind == "SHAPES":
        return any(o.select_get() for o in context.scene.objects
                   if getattr(getattr(o, "data", None), "shape_keys", None) == node)
    if kind == "SET":
        return False            # a set node is highlighted only when picked in the list
    return node.select_get()


def selection_sig(context):
    """Scene selection (objects + pose-mode joints) the outliner picks belong to."""
    from . import channel_box
    sig = []
    for ob in context.scene.objects:
        if ob.select_get():
            sig.append(ob.name)
        if ob.type == 'ARMATURE' and ob.mode == 'POSE' and ob.pose is not None:
            sig += [(ob.name, pb.name) for pb in ob.pose.bones if channel_box.bone_selected(pb)]
    return tuple(sig)


def picked_ids(context, all_rows):
    """The user's picks that still name a listed row, or an empty set (none yet / the scene selection changed)."""
    if _picked["sig"] != selection_sig(context):
        return set()
    return _picked["ids"] & {row_id(r) for r in all_rows}


def highlighted(kind, rid, selected, picked):
    """Maya: once rows were picked in the outliner exactly those are highlighted; before that the selected nodes
    (never their attribute rows — Blender selects every F-curve of a selected object, so ``fc.select`` is not
    the highlight). Clicking an attribute un-highlights its node like Maya's outliner."""
    if picked:
        return rid in picked
    return kind not in ATTR_KINDS and selected


def metrics(region):
    """(top of the first row, row height) in region pixels: Blender keeps its search field at the top."""
    s = bpy.context.preferences.system.ui_scale or 1.0     # 0 in background
    return region.height - round(24 * s), round(20 * s)


def visible_rows(region):
    top, h = metrics(region)
    return max(1, int(top // h)) if h > 0 else 1


def clamp_scroll(offset, n_rows, n_visible):
    """First row shown: 0 .. the last full page (a list that fits doesn't scroll)."""
    return max(0, min(int(offset), n_rows - n_visible))


def _area_ptr(context):
    area = getattr(context, "area", None)
    return area.as_pointer() if area is not None else 0


def scroll_offset(context, region, n_rows):
    return clamp_scroll(_scroll.get(_area_ptr(context), 0), n_rows, visible_rows(region))


def row_at(context, region, y):
    top, h = metrics(region)
    if y > top:
        return None
    rs = rows(context, context.space_data)
    k = int((top - y) // h) + scroll_offset(context, region, len(rs))
    return rs[k] if 0 <= k < len(rs) else None


def _rect(x0, y0, x1, y1, color):
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": ((x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1))})
    call(shader.uniform_float, "color", color)
    call(batch.draw, shader)


PIN = (0.85, 0.85, 0.85, 1.0)
PIN_OFF = (0.55, 0.55, 0.55, 1.0)


def _draw_pin(x, y, s, pinned):
    """Maya's pin icon left of a channel row's name: an upright push-pin on a
    pinned row (head, plate, needle), a grey sideways one on the others."""
    PIN, PIN_OFF = _themed(globals()["PIN"], "text"), _themed(globals()["PIN_OFF"], "text")
    if pinned:
        _rect(x - 2 * s, y + 1 * s, x + 2 * s, y + 6 * s, PIN)
        _rect(x - 4 * s, y, x + 4 * s, y + 1.5 * s, PIN)
        _rect(x - 0.5 * s, y - 5 * s, x + 0.5 * s, y, PIN)
    else:
        _rect(x - 6 * s, y - 2 * s, x - 1 * s, y + 2 * s, PIN_OFF)
        _rect(x - 1 * s, y - 3.5 * s, x + 0.5 * s, y + 3.5 * s, PIN_OFF)
        _rect(x + 0.5 * s, y - 0.5 * s, x + 6 * s, y + 0.5 * s, PIN_OFF)


def draw_channels():
    context = bpy.context
    space, region = context.space_data, context.region
    if not (is_graph(space) and enabled(context)) or region is None:
        return
    top, h = metrics(region)
    s = context.preferences.system.ui_scale
    pins = getattr(context.window_manager, "allset_show_pins", True)      # Maya 2026 View > Show Pins
    key = ("graph outliner", region.as_pointer())
    if draw_replay.again(key, (region.width, region.height, s, pins)):     # a window moves: the list as drawn last
        return
    with draw_replay.recording(key, (region.width, region.height, s, pins)):
        _draw_list(context, space, region, top, h, s, pins)


def _draw_list(context, space, region, top, h, s, pins):
    call(gpu.state.blend_set, 'ALPHA')
    text = _themed(TEXT, "text", space)
    _rect(0, 0, region.width, top, _themed(BACK, "back", space))
    font = 0
    call(blf.size, font, 12 * s)
    all_rows = rows(context, space)
    picked = picked_ids(context, all_rows)
    first = scroll_offset(context, region, len(all_rows))
    y = top
    for row in all_rows[first:]:
        if y < 0:
            break
        kind, node, fc = row
        if kind in graph_layers.KINDS:          # another selected animation layer (ui/graph_layers.py)
            graph_layers.draw_row(row, y, h, s, font, region.width)
            y -= h
            continue
        sel = highlighted(kind, row_id(row), kind not in ATTR_KINDS and node_selected(context, kind, node), picked)
        if sel:
            _rect(0, y - h, region.width, y, SELECT)
        if kind in ("UP_SDK", "UP_CURVE"):       # Show Upstream Curves rows, indented under their channel
            call(blf.color, font, *(attr_color(fc) if kind == "UP_SDK" else text))
            call(blf.position, font, 66 * s, y - h + 6 * s, 0)
            call(blf.draw, font, _up_label.get((kind, fc.as_pointer()), ""))
            if pins:
                _draw_pin(56 * s, y - h / 2, s, False)
        elif kind != "ATTR":
            sign = "−" if _expanded.get(node_key(node), True) else "+"
            call(blf.color, font, *text)
            call(blf.position, font, 6 * s, y - h + 6 * s, 0)
            call(blf.draw, font, sign)
            call(blf.position, font, 22 * s, y - h + 6 * s, 0)
            call(blf.draw, font, node_name(node))
        else:
            call(blf.color, font, *attr_color(fc))
            call(blf.position, font, 44 * s, y - h + 6 * s, 0)
            call(blf.draw, font, attr_label(fc))
            if pins:
                _draw_pin(34 * s, y - h / 2, s, is_pinned(node, fc))
        y -= h
    n_vis = visible_rows(region)
    if len(all_rows) > n_vis:       # Maya's scroll bar at the right edge: thumb = the shown part of the list
        span = top / len(all_rows)
        x1 = region.width - 2 * s
        _rect(x1 - 6 * s, top - (first + n_vis) * span, x1, top - first * span, _themed(THUMB, "back", space))
    call(gpu.state.blend_set, 'NONE')


def show_rows(context, chosen):
    """Maya: the curves of the selected outliner rows are shown and selected, the others hidden (pinned curves stay
    shown)."""
    for _kind, node, curves in listed_nodes(context, context.space_data):
        for fc in curves:
            on = fc in chosen
            fc.select = on
            fc.hide = not (on or is_pinned(node, fc))
    for _owner, fc in upstream_curves(context, context.space_data):
        on = fc in chosen
        fc.select = on
        fc.hide = not on


def pick_row(context, row, ctrl=False, shift=False):
    """A click on an outliner row: remember the picked rows (the highlight) and show / select their curves. Ctrl
    toggles, Shift adds, a plain click replaces."""
    space = context.space_data
    all_rows = rows(context, space)
    kind, node, fc = row
    rid = row_id(row)
    listed = {node_key(n): c for _k, n, c in listed_nodes(context, space)}
    picked = set(listed.get(node_key(node), ()) if kind not in ATTR_KINDS else [fc])
    current = {c for c in listed_curves(context, space) if c.select and not c.hide}
    ids = picked_ids(context, all_rows)
    if ctrl:
        chosen, ids = current ^ picked, ids ^ {rid}
    elif shift:
        chosen, ids = current | picked, ids | {rid}
    else:
        chosen, ids = picked, {rid}
    _picked["ids"], _picked["sig"] = ids, selection_sig(context)
    show_rows(context, chosen)
    return chosen


class ALLSET_OT_graph_channel_click(bpy.types.Operator):
    """Maya Graph Editor outliner: click a node (all its curves) or an attribute (that curve); Ctrl toggles,
    Shift adds; the +/- sign folds the attributes"""
    bl_idname = "allset.graph_channel_click"
    bl_label = "Graph Editor Outliner Click"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.region is not None and context.region.type == 'CHANNELS' and is_graph(context.space_data)

    def invoke(self, context, event):
        if not enabled(context):
            return {'PASS_THROUGH'}
        region = context.region
        if event.mouse_region_y > metrics(region)[0]:
            return {'PASS_THROUGH'}       # Blender's search field
        row = row_at(context, region, event.mouse_region_y)
        if row is None:
            return {'FINISHED'}
        kind, node, _fc = row
        if kind in graph_layers.KINDS:          # that layer becomes the last picked one
            graph_layers.activate_row(context, row)
            return {'FINISHED'}
        s = context.preferences.system.ui_scale
        if kind not in ATTR_KINDS and event.mouse_region_x < 18 * s:
            key = node_key(node)
            _expanded[key] = not _expanded.get(key, True)
            region.tag_redraw()
            return {'FINISHED'}
        pick_row(context, row, ctrl=event.ctrl, shift=event.shift)
        for area in context.screen.areas:
            if area.type == 'GRAPH_EDITOR':
                area.tag_redraw()
        return {'FINISHED'}


def _channels_region(context):
    region = getattr(context, "region", None)
    if region is not None and region.type == 'CHANNELS':
        return region
    area = getattr(context, "area", None)
    return next((r for r in area.regions if r.type == 'CHANNELS'), None) if area is not None else None


class ALLSET_OT_graph_channel_scroll(bpy.types.Operator):
    """Scroll the Maya Graph Editor outliner by rows (positive = down the list)"""
    bl_idname = "allset.graph_channel_scroll"
    bl_label = "Graph Editor Outliner Scroll"

    delta: IntProperty(name="Rows", description="Rows to scroll, positive = down the list", default=3,
                       options={'SKIP_SAVE'})

    def execute(self, context):
        space = getattr(context, "space_data", None)
        region = _channels_region(context)
        if not (is_graph(space) and enabled(context)) or region is None:
            return {'PASS_THROUGH'}     # no Maya Graph Editor here: Blender's own channel scrolling
        n = len(rows(context, space))
        ptr = _area_ptr(context)
        old = scroll_offset(context, region, n)
        _scroll[ptr] = clamp_scroll(old + self.delta, n, visible_rows(region))
        region.tag_redraw()
        return {'FINISHED'}

    def invoke(self, context, event):
        # a wheel item: only over the outliner pane itself (the curve area keeps Blender's zoom)
        region = getattr(context, "region", None)
        if region is None or region.type != 'CHANNELS':
            return {'PASS_THROUGH'}
        return self.execute(context)


def _target_rows(context, space):
    """[(node, fcurve)] a channel command (Pin / Unpin Channel) acts on: the highlighted outliner rows, a node row =
    all its channels; nothing highlighted = nothing (Maya). The highlight is the one drawn:
    the rows picked in the list, else the selected nodes' rows."""
    all_rows = rows(context, space)
    picked = picked_ids(context, all_rows)
    out = []
    for kind, node, curves in listed_nodes(context, space):
        nk = node_key(node)
        whole = highlighted(kind, nk, node_selected(context, kind, node), picked)
        for fc in curves:
            if whole or (nk, fc.data_path, fc.array_index) in picked:
                out.append((node, fc))
    return out


class ALLSET_OT_graph_pin(bpy.types.Operator):
    """Maya Curves > Pin Channel / Unpin Channel: pinned curves stay listed and drawn whatever is selected"""
    bl_idname = "allset.graph_pin"
    bl_label = "Pin Channel"
    bl_options = {'UNDO'}

    pin: BoolProperty(default=True, options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return is_graph(getattr(context, "space_data", None))

    def execute(self, context):
        targets = _target_rows(context, context.space_data)
        if not targets:
            self.report({'WARNING'}, "No channels selected.")
            return {'CANCELLED'}
        ids = {(node_key(n), fc.data_path, fc.array_index) for n, fc in targets}
        if self.pin:
            _pinned.update(ids)
        else:
            _pinned.difference_update(ids)
        sync(context)
        _redraw_editors(context)
        return {'FINISHED'}
