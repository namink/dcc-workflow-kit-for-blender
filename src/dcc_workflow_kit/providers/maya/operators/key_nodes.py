# SPDX-License-Identifier: GPL-3.0-or-later
"""The nodes the kit's key commands act on and their keys: the Channel Box's targets (``nodes``: selected objects, or
pose bones in pose mode), a node's F-curves (``node_fcurves``; a bone: its own ``pose.bones["n"]`` curves), the Time
Slider range (``time_range``), the curves the Time Slider shows and edits (``slider_fcurves``), the keys in it
(``keys_in``) and ``_move`` (a key and its handles in time).
Used by key_scope and time_keys (which re-exports these names for key_insert, graph_key_menu and ui/time_slider).
"""

import bpy


def _cb():
    from ..ui import channel_box
    return channel_box


# --- nodes and their curves ---------------------------------------------------------------

def nodes(context=None):
    return _cb().targets(context)


def prefix(node):
    """Animation path prefix of a node: ``pose.bones["n"]`` for a bone, "" for an object."""
    return node.path_from_id() if _cb().is_bone(node) else ""


def node_fcurves(node):
    """The node's F-curves (a bone: only its own ``pose.bones["n"]`` curves)."""
    fcs = _cb()._fcurves(node)
    if fcs is None:
        return []
    pre = prefix(node)
    if not pre:
        return list(fcs)
    return [fc for fc in fcs if fc.data_path.startswith(pre + ".") or fc.data_path.startswith(pre + "[")]


def without_deformer_curves(node, curves):
    """``curves`` without those of an object's deformer nodes (``modifiers["squash1"].factor``): in Maya they are the
    deformer node's keys, which the Time Slider shows, steps through and edits while that node is selected, not with
    the deformed object or the handle."""
    mods = getattr(node, "modifiers", None)
    if not mods or not curves:
        return curves
    from . import deformers
    heads = tuple(f'modifiers["{bpy.utils.escape_identifier(md.name)}"]' for md in mods
                  if deformers.base_of(md) is not None)
    if not heads:
        return curves
    return [fc for fc in curves if not fc.data_path.startswith(heads)]


def slider_fcurves(node):
    """The node's curves the Time Slider shows and edits: ``node_fcurves`` without its deformer nodes' curves."""
    return without_deformer_curves(node, node_fcurves(node))


def time_range(context=None):
    """(start, end) the time slider edits act on: the Shift range, else the current frame."""
    context = context or bpy.context
    wm = context.window_manager
    if getattr(wm, "allset_time_range_on", False):
        a, b = wm.allset_time_range
        return min(a, b), max(a, b)
    f = context.scene.frame_current
    return f, f


def _in(kp, a, b):
    return a - 0.5 <= kp.co.x < b + 0.5


def keys_in(node, a, b):
    """[(fcurve, [keyframe points in a..b])] of a node's Time Slider curves (``slider_fcurves``)."""
    out = []
    for fc in slider_fcurves(node):
        pts = [kp for kp in fc.keyframe_points if _in(kp, a, b)]
        if pts:
            out.append((fc, pts))
    return out


def _move(kp, dx):
    kp.co.x += dx
    kp.handle_left.x += dx
    kp.handle_right.x += dx
