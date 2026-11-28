# SPDX-License-Identifier: GPL-3.0-or-later
"""Channel selection (WindowManager.allset_cb_selected): click and range selection in draw order, the channels a
typed value goes to, and arming the middle-drag slider when channels are picked.
Entry points: selected_channels, set_selected_channels, select_channel, select_range, drawn_keys, cell_key.
Related: cb_drag.py, cb_slider.py."""

import bpy

from .cb_nodes import is_bone, lead
from .cb_keys import (CUSTOM_PREFIX, HISTORY_PREFIX, MAIN, MAIN_BY_KEY, SHAPE_PREFIX, constraint_key, custom_keys,
                      input_key, is_hidden, row_key)
from .cb_inputs import SHAPE_PROPS, history_node, is_open, wanted_rows
from .cb_values import has_channel


# --- channel selection (WindowManager string; not undoable) -----------------------------------

def selected_channels(context=None):
    wm = (context or bpy.context).window_manager
    return [s for s in wm.allset_cb_selected.split(",") if s]


# Like Maya, a channel selection shows in the column it was picked in: blue names after a pick on the names, blue
# value cells after a pick or a drag on the values. The channels are the same either way. A selection made any other
# way shows on the names.
_column = {"part": "NAME"}


def selection_column():
    return _column["part"]


def set_selection_column(part):
    _column["part"] = "VALUE" if part == "VALUE" else "NAME"


def set_selected_channels(keys, context=None):
    _column["part"] = "NAME"
    wm = (context or bpy.context).window_manager
    wm.allset_cb_selected = ",".join(dict.fromkeys(keys))
    if keys:
        arm_slider(context)
    else:
        disarm_slider()
    from . import cb_channels       # Sync Selection in Graph Editor
    cb_channels.after_selection(context or bpy.context)


# Like Maya, picking channels makes a middle drag in a view change them until another tool is picked (Q / W / E /
# R, the toolbar): the channels stay highlighted, and the middle drag is that tool's own again.
_slider = {"armed": False, "tool": None}


def _view3d_tool(context=None):
    context = context or bpy.context
    try:
        tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    except (AttributeError, RuntimeError, TypeError):
        return None
    return tool.idname if tool is not None else None


def arm_slider(context=None):
    _slider["armed"] = True
    _slider["tool"] = _view3d_tool(context)


def disarm_slider():
    _slider["armed"] = False


def slider_armed(context=None):
    """A middle drag in a view drives the selected channels: channels were picked since the last tool change."""
    from .. import preferences
    return (_slider["armed"] and _view3d_tool(context) == _slider["tool"]
            and preferences.get(context or bpy.context).cb_manipulators != 'NONE')


def select_channel(key, mode="SET", context=None):
    """mode: SET (click), TOGGLE (Ctrl), EXTEND (Shift)."""
    sel = selected_channels(context)
    if mode == "SET":
        sel = [key]
    elif mode == "TOGGLE":
        sel = [k for k in sel if k != key] if key in sel else sel + [key]
    else:
        sel = sel + [key]
    set_selected_channels(sel, context)
    return sel


# --- channel ranges (drag over the rows, #6) -------------------------------------------------------------------

def drawn_keys(ob):
    """Channel keys in the order the Channel Box draws them (main channels, custom attributes, SHAPES rows)."""
    keys = [c[0] for c in MAIN if not is_hidden(ob, c[0]) and has_channel(ob, c[0])]
    keys += [CUSTOM_PREFIX + n for n in custom_keys(ob) if not is_hidden(ob, CUSTOM_PREFIX + n)]
    keys += [SHAPE_PREFIX + n for n in SHAPE_PROPS.get(getattr(ob, "type", ""), ())
             if has_channel(ob, SHAPE_PREFIX + n) and not is_hidden(ob, SHAPE_PREFIX + n)]
    scene = bpy.context.scene
    rows = scene.allset_cb.rows if scene is not None and hasattr(scene, "allset_cb") else ()
    keys += history_keys(ob)
    keys += [k for r in rows if r.kind in ("INPUT", "CONSTRAINT", "BLEND") for k in [row_key(r)]
             if has_channel(ob, k)]
    return keys


def shown_weight_keys(context=None):
    """Channel keys of the constraint target weights the Channel Box shows under the lead's open constraint nodes
    (pCube1W0 ...). Maya keys a constraint's weights with S when its node is selected; here the node sits in the
    INPUTS of the object or joint it drives, so S keys the weights shown there along with the node's channels."""
    ob = lead(context)
    if ob is None:
        return []
    from ..operators import constrain_multi
    out = []
    for kind, name, mod_type, nth in wanted_rows(ob):
        if kind == "CONSTRAINT":
            out.append(constraint_key(mod_type, nth, name))
        elif kind == "CUSTOM" and name.startswith(constrain_multi.WEIGHT):
            out.append(CUSTOM_PREFIX + name)
    return out


def shown_deformer_keys(context=None):
    """Channel keys of the attributes the Channel Box shows under the lead's open deformer nodes (bend1 Curvature, Low
    Bound ...: operators/deformers.ATTRS). Maya's deformer attributes are keyable and S keys them on a selected
    deformer node; here the node sits in the INPUTS of the deformed object and of its handle, so S keys the
    attributes shown there along with the selection's own channels. A closed node stays unkeyed."""
    ob = lead(context)
    if ob is None or is_bone(ob):
        return []
    from ..operators import deformers
    return [input_key(mod_type, nth, name) for kind, name, mod_type, nth in wanted_rows(ob)
            if kind == "INPUT" and name.startswith(deformers.PREFIX)]


def history_keys(ob):
    """Channel keys of the creation node's attributes while its INPUTS node is open (Channel Box order)."""
    if not isinstance(ob, bpy.types.Object):
        return []
    from ..operators import prim_history
    _owner, node = prim_history.node_of(ob)
    if node is None or not is_open(ob, history_node(node["name"])):
        return []
    from . import creation_inputs
    return [HISTORY_PREFIX + n for n in creation_inputs.node_rows(node["type"])]


def channel_range(ob, first, last):
    """The drawn channels from ``first`` to ``last`` (either order), top to bottom."""
    keys = drawn_keys(ob)
    if first not in keys or last not in keys:
        return [k for k in (first, last) if k in keys]
    i, j = sorted((keys.index(first), keys.index(last)))
    return keys[i:j + 1]


def select_range(ob, first, last, mode="SET", base=None, context=None):
    """Select the rows ``first``..``last``: SET replaces the selection, ADD adds to ``base`` (default: the current
    selection). Maya: drag over channel names / fields selects a range, Ctrl+drag adds."""
    rng = channel_range(ob, first, last)
    if mode == "SET":
        sel = rng
    else:
        sel = list(selected_channels(context) if base is None else base) + rng
    set_selected_channels(sel, context)
    return selected_channels(context)


def cell_key(path, scene=None):
    """(channel key, "NAME" / "VALUE") of a Channel Box cell from its data path (``context.property``), or None."""
    import re
    m = re.match(r"^allset_cb\.([a-z]+)_(text|text_on|sel|sel_on)$", path or "")
    if m and m.group(1) in MAIN_BY_KEY:
        return m.group(1), ("VALUE" if m.group(2).startswith("text") else "NAME")
    m = re.match(r"^allset_creation\.([A-Za-z0-9]+?)_(text|text_on|sel|sel_on)$", path or "")
    if m:
        return HISTORY_PREFIX + m.group(1), ("VALUE" if m.group(2).startswith("text") else "NAME")
    m = re.match(r"^allset_cb\.rows\[(\d+)\]\.(text|text_on|sel|sel_on)$", path or "")
    if m and scene is not None:
        rows = scene.allset_cb.rows
        i = int(m.group(1))
        if i < len(rows) and rows[i].kind in ("CUSTOM", "SHAPE", "INPUT", "CONSTRAINT", "BLEND"):
            return row_key(rows[i]), ("VALUE" if m.group(2).startswith("text") else "NAME")
    return None


def sel_toggle(layout, owner, prop, selected, text, translate=True):
    """A Channel Box name cell: a toggle of the channel's selection, pressed (embossed) when selected. A selected
    cell draws the twin property ``<prop>_on``: Blender keeps the button under the mouse from the last redraw
    (with its old emboss), so the same property would show the new selection only after the mouse leaves the
    row (#316); another property is another button. Pressed only while the selection shows on the names
    (selection_column)."""
    selected = selected and _column["part"] == "NAME"
    layout.prop(owner, prop + "_on" if selected else prop, text=text, toggle=True, emboss=selected,
                translate=translate)


def _left_pad(text):
    """Spaces after ``text`` that move it, centred in a Channel Box value cell, to the cell's left edge.
    The cell width is estimated from the region width (half the row, less the state icon column) and kept a little
    short, so the text never clips."""
    import blf
    region = bpy.context.region
    if region is None:
        return ""
    prefs = bpy.context.preferences
    s = prefs.system.ui_scale
    blf.size(0, prefs.ui_styles[0].widget.points * s)
    space = blf.dimensions(0, "a a")[0] - blf.dimensions(0, "aa")[0]
    if space <= 0:
        return ""
    cell = (region.width - 24 * s) * 0.5 - 20 * s
    room = cell - 30 * s - blf.dimensions(0, text)[0]
    return " " * max(0, int(room / space))


def value_cell(layout, owner, prop, selected):
    """A Channel Box value field; selected (#375), Maya's blue value cell: a pressed toggle of the twin ``<prop>_on``
    showing the value (UILayout can't colour a text field), while the selection shows on the values
    (selection_column). The drag watcher eats the press either way and edits ``prop`` (edit_field)."""
    twin = prop + "_on"
    if selected and _column["part"] == "VALUE" and twin in owner.bl_rna.properties:
        # one pressed toggle (two joined buttons draw a divider, and a narrow one drops its text); a toggle centres
        # its text, so trailing spaces push the value to the cell's left edge like the text field's
        val = getattr(owner, prop)
        layout.prop(owner, twin, text=val + _left_pad(val), toggle=True, translate=False)
    else:
        layout.prop(owner, prop, text="")


def entry_keys(key, context=None):
    """The edited channel, or every selected channel when it is one of them."""
    sel = selected_channels(context)
    return sel if key in sel else [key]


# editors that show the channel selection: the Channel Box (dock / floating windows), the Graph Editor (Sync Graph
# Editor selects the channels' curves) and the Time Slider (Sync Timeline Display)
SELECTION_EDITORS = {'PROPERTIES', 'GRAPH_EDITOR', 'DOPESHEET_EDITOR'}


def redraw_selection():
    """Redraw what a channel selection change shows. The 3D Views, Outliner, shelf ... stay as drawn: a click or a
    drag over the rows redraws no viewport, so picking channels stays quick in a heavy scene (#316)."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in SELECTION_EDITORS:
                    area.tag_redraw()
    except (AttributeError, ReferenceError):
        pass


def _visible_channels(ob):
    keys = [c[0] for c in MAIN if has_channel(ob, c[0])] + \
           [CUSTOM_PREFIX + k for k in custom_keys(ob)]
    return [k for k in keys if not is_hidden(ob, k)]
