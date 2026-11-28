# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Outliner selection in the kit tree: ``select_row`` (click, Ctrl toggle, Shift range, Ctrl+Shift add) on
object, joint, camera and set rows, ``deselect_all``, the range anchor (``active_row``), and hidden or
selection-locked objects that stay picked while the visible selection stays the same (``unselectable``,
``is_picked``, ``picked_unselectable``). The mouse operators: outliner_tree.
"""

import bpy

from .outliner_tree_rows import _state, default_set_members

def visible_signature(context):
    """The visible selection as text (``visibility._signature``) from the context's selection."""
    return "\n".join(sorted(o.name for o in context.selected_objects if o.visible_get()))


def _kept(ob, signature):
    """A hidden object that still counts as selected (Maya: hidden by h while selected, or picked hidden in the
    Outliner; ``visibility.KEPT``)."""
    from ..operators import visibility
    return ob.hide_viewport and visibility.KEPT in ob and visibility._kept(ob, signature)


# --- selection -----------------------------------------------------------------------------------------------------

def _select(ob, state=True):
    try:
        ob.select_set(state)
        return True
    except RuntimeError:      # not in the view layer
        return False


def _object_mode(context, clear):
    from ..operators import joint_selection
    if context.mode != 'OBJECT' and context.view_layer.objects.active is not None:
        try:
            joint_selection.leave(context, clear_selection=clear)
        except RuntimeError:
            pass


def _keep_hidden(context, obs, replace):
    """Objects Blender can't select (hidden, or selection-locked like a live surface) stay picked when their row is
    picked: a hidden one gets the visibility module's kept mark for the visible selection left now, so h / Shift+H
    act on it like on Maya's hidden-but-selected nodes, and every one is remembered with that visible selection
    (``picked``: Delete, the live list). ``replace`` drops every other pick first."""
    from ..operators import visibility
    if replace:
        visibility._clear(list(context.view_layer.objects), visibility.KEPT)
    signature = visible_signature(context)
    names = set() if replace or _state.get("picks", ("", set()))[0] != signature else set(_state["picks"][1])
    for ob in obs:
        if ob.hide_viewport:
            ob[visibility.KEPT] = signature
        names.add(ob.name)
    _state["picks"] = (signature, names)


def _drop_kept(obs):
    from ..operators import visibility
    visibility._clear(obs, visibility.KEPT)
    sig, names = _state.get("picks", ("", set()))
    _state["picks"] = (sig, names - {ob.name for ob in obs})


def unselectable(ob):
    """Blender can't select this object (hidden or selection-locked): its row is picked through ``_keep_hidden``."""
    try:
        return not ob.visible_get() or ob.hide_select
    except RuntimeError:
        return True


def is_picked(ob, signature):
    """An unselectable object picked in the Outliner while the visible selection is still ``signature``."""
    if _kept(ob, signature):
        return True
    sig, names = _state.get("picks", ("", set()))
    return sig == signature and ob.name in names


def picked_unselectable(context):
    """The unselectable objects picked in a kit Outliner tree (Blender's Outliner keeps such rows highlighted; the
    kit's tree keeps them here while the visible selection stays the same)."""
    signature = visible_signature(context)
    sig, names = _state.get("picks", ("", set()))
    if sig != signature:
        return []
    return [ob for ob in (bpy.data.objects.get(n) for n in sorted(names)) if ob is not None]


def deselect_all(context):
    """Maya: a click on empty Outliner space selects nothing."""
    _object_mode(context, True)
    for ob in context.selected_objects:
        _select(ob, False)
    _keep_hidden(context, (), True)
    _state["camera"] = ""


def active_row(context, rows):
    """Index of the row of the active object / joint (the range anchor), or None."""
    ob = context.view_layer.objects.active
    if ob is None:
        return None
    bone = None
    if ob.type == 'ARMATURE' and ob.mode == 'POSE' and ob.data.bones.active is not None:
        bone = ob.data.bones.active.name
    elif ob.type == 'ARMATURE' and ob.mode == 'EDIT' and ob.data.edit_bones.active is not None:
        bone = ob.data.edit_bones.active.name
    for i, r in enumerate(rows):
        if r.ob != ob.name:
            continue
        if bone is not None and r.kind == 'JOINT' and r.sub == bone:
            return i
        if bone is None and (r.kind == 'OBJECT' or (r.kind == 'JOINT' and r.top)):   # a kit skeleton = its root row
            return i
    return None


def _pick_joint(context, ob, name, add):
    """Pick joint ``name`` the way a viewport click does (Pose Mode, or Edit Mode with the Move tool on an unskinned
    skeleton); ``add`` keeps the joints already picked."""
    from ..operators import joint_selection
    try:
        joint_selection.select(context, ob, name, shift=add, ctrl=add)
        return True
    except (RuntimeError, KeyError):
        return False


def select_row(context, rows, index, mode, anchor=None):
    """Maya Outliner selection of row ``index``: 'REPLACE' (click), 'TOGGLE' (Ctrl), 'RANGE' (Shift, from
    ``anchor``), 'RANGE_ADD' (Ctrl+Shift). The pick order (``operators/pick_order``: Maya's selection list, the
    last pick leads) is brought up to date before and after, like after one of Blender's own Outliner clicks."""
    from ..operators import pick_order
    pick_order.ordered(context)
    try:
        _select_row(context, rows, index, mode, anchor)
    finally:
        pick_order.ordered(context)


def _select_row(context, rows, index, mode, anchor=None):
    from ..operators import sets
    row = rows[index]
    vl = context.view_layer
    kind = row.kind
    if kind == 'CAMERA':
        _object_mode(context, mode == 'REPLACE')
        if mode == 'REPLACE':
            for o in context.selected_objects:
                _select(o, False)
        _state["camera"] = row.ob
        return
    _state["camera"] = ""
    if kind == 'DEFAULT_SET':
        _object_mode(context, mode == 'REPLACE')
        mem = [o for o in default_set_members(row.ob, context.scene) if sets._selectable(o)]
        if mode == 'REPLACE':
            for o in context.selected_objects:
                _select(o, False)
        for o in mem:
            _select(o, not o.select_get() if mode == 'TOGGLE' else True)
        if mem and mem[-1].select_get():
            vl.objects.active = mem[-1]
        return
    if kind == 'SET':
        coll = sets.get(row.ob)
        if coll is not None:
            sets.select_members(context, coll, {'TOGGLE': 'TOGGLE', 'RANGE': 'ADD', 'RANGE_ADD': 'ADD'}.get(
                mode, 'REPLACE'))
        return
    if kind == 'MEMBER' and row.label != row.ob:        # a component member row (pCube1.vtx[0:3])
        coll, ob = sets.get(row.sub), bpy.data.objects.get(row.ob)
        if coll is not None and ob is not None:
            sets.select_members(context, coll, {'TOGGLE': 'TOGGLE', 'RANGE': 'ADD', 'RANGE_ADD': 'ADD'}.get(
                mode, 'REPLACE'), only=ob)
        return
    ranged = mode in ('RANGE', 'RANGE_ADD') and anchor is not None and 0 <= anchor < len(rows)
    span = rows[min(anchor, index):max(anchor, index) + 1] if ranged else ()
    # a range over joints of one skeleton picks those joints; a range that also holds other rows picks objects (a
    # joint row then stands for its skeleton: Blender can't pick joints and objects together)
    joints_only = ranged and all(r.kind == 'JOINT' and r.ob == row.ob for r in span)
    if kind == 'JOINT' and (not ranged or joints_only):
        ob = bpy.data.objects.get(row.ob)
        if ob is None or ob.type != 'ARMATURE':
            return
        if mode == 'TOGGLE':
            from ..operators import joint_selection
            try:
                joint_selection.select(context, ob, row.sub, shift=True, ctrl=False)
            except (RuntimeError, KeyError):
                pass
            return
        if ranged:
            names = [r.sub for r in span if r.sub != row.sub]
            add = mode == 'RANGE_ADD'
            for name in names:
                add = _pick_joint(context, ob, name, add) or add
            _pick_joint(context, ob, row.sub, add)
            return
        _pick_joint(context, ob, row.sub, mode == 'RANGE_ADD')
        return
    # OBJECT / SHAPE / MEMBER rows pick their object
    ob = bpy.data.objects.get(row.ob)
    if ob is None:
        return
    _object_mode(context, mode in ('REPLACE', 'RANGE'))
    hidden = unselectable(ob)
    if mode == 'TOGGLE':
        if hidden:          # a hidden / locked row: picked / unpicked through the kept mark
            if is_picked(ob, visible_signature(context)):
                _drop_kept([ob])
            else:
                _keep_hidden(context, [ob], False)
                vl.objects.active = ob
            return
        kept = picked_unselectable(context)
        if _select(ob, not ob.select_get()) and ob.select_get():
            vl.objects.active = ob
        _keep_hidden(context, kept, False)          # the visible selection changed: hidden picks stay picked
        return
    if ranged:
        if mode == 'RANGE':
            for o in context.selected_objects:
                _select(o, False)
        else:
            kept = picked_unselectable(context)
        picked_hidden = []
        for r in span:
            if r.kind in ('OBJECT', 'SHAPE', 'MEMBER', 'JOINT'):
                o = bpy.data.objects.get(r.ob)
                if o is None:
                    continue
                if unselectable(o):
                    picked_hidden.append(o)
                else:
                    _select(o)
        _keep_hidden(context, picked_hidden + (kept if mode == 'RANGE_ADD' else []), mode == 'RANGE')
        if ob.select_get() or hidden:
            vl.objects.active = ob
        return
    if mode != 'RANGE_ADD':
        for o in context.selected_objects:
            if o != ob:
                _select(o, False)
    if hidden:
        _keep_hidden(context, [ob], mode != 'RANGE_ADD')
        vl.objects.active = ob
        return
    if mode != 'RANGE_ADD':
        _keep_hidden(context, (), True)
    if _select(ob):
        vl.objects.active = ob
