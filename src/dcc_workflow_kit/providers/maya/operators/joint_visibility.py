# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Hide / Show on joints (Ctrl+H, h, Alt+H, Shift+H, Ctrl+Shift+H, Display > Hide / Show) (#568).

A Maya joint has one ``visibility`` attribute, and a hidden joint hides every joint below it. The kit keeps that
attribute as an ID property on the bone (``OWN``, on ``Bone`` / ``EditBone``, which survives Pose <-> Edit) and
writes the result to Blender's two hide flags: ``PoseBone.hide`` (Pose / Object mode) and ``Bone.hide`` /
``EditBone.hide`` (Edit mode), so a joint hidden in one mode stays hidden in the other.

``LAST`` marks the joints the latest hide hid (Show Last Hidden brings them back, also from Object mode), ``KEPT``
the joints h hid while they were selected (h / Shift+H bring them back). A bone some other tool hid counts as a
hidden joint; one some other tool showed again loses its flag.
"""

import bpy

OWN = "allset_joint_hidden"     # the joint's own visibility is off
LAST = "allset_last_hidden"     # hidden by the latest hide
KEPT = "allset_kept"            # hidden by h while selected

JOINT_MODES = {'POSE', 'EDIT_ARMATURE'}
JOINT_KINDS = {'JOINTS', 'KINEMATICS'}


def _editing(ob):
    return ob.mode == 'EDIT'


def _bones(ob):
    return ob.data.edit_bones if _editing(ob) else ob.data.bones


def _hidden_now(ob, b):
    if _editing(ob):
        return b.hide
    pb = ob.pose.bones.get(b.name)
    return pb.hide if pb is not None else b.hide


def _write(ob, b, hidden):
    if b.hide != hidden:
        b.hide = hidden
    pb = ob.pose.bones.get(b.name) if ob.pose is not None else None
    if pb is not None and pb.hide != hidden:
        pb.hide = hidden


def _selected(ob, b):
    if _editing(ob):
        return b.select
    pb = ob.pose.bones.get(b.name)
    return pb is not None and pb.select


def _select(ob, b, state):
    if _editing(ob):
        b.select = b.select_head = b.select_tail = state
        return
    pb = ob.pose.bones.get(b.name)
    if pb is not None:
        pb.select = state


def _own_or_above(b):
    while b is not None:
        if b.get(OWN):
            return True
        b = b.parent
    return False


def normalize(ob):
    """Take over hide flags other tools wrote: a hidden bone with no hidden joint at or above it is a hidden joint;
    a shown bone drops its own flag."""
    bones = list(_bones(ob))
    explained = [_own_or_above(b) for b in bones]       # before any flag changes
    for b, known in zip(bones, explained):
        hidden = _hidden_now(ob, b)
        if hidden and not known:
            b[OWN] = True
        elif not hidden and b.get(OWN):
            del b[OWN]


def apply(ob):
    """Write every bone's hide flags from the joints' visibility (a hidden joint hides the joints below it)."""
    for b in _bones(ob):
        _write(ob, b, _own_or_above(b))


def _armatures(context, in_mode=True):
    if in_mode:
        obs = [o for o in getattr(context, "objects_in_mode", ()) or () if o.type == 'ARMATURE']
        if not obs and context.object is not None and context.object.type == 'ARMATURE' and \
                context.object.mode in {'POSE', 'EDIT'}:
            obs = [context.object]
        return obs
    in_layer = {o.session_uid for o in context.view_layer.objects}
    return [o for o in context.scene.objects if o.type == 'ARMATURE' and o.session_uid in in_layer]


def armatures_in_mode(context):
    return _armatures(context)


def clear_last_of(obs):
    """A hide of objects is the new "last hidden": the joints hidden before no longer are."""
    _clear(obs, LAST)


def _clear(obs, key):
    for ob in obs:
        for b in _bones(ob):
            if key in b:
                del b[key]


def selection_count(context):
    return sum(1 for ob in _armatures(context) for b in _bones(ob) if not _hidden_now(ob, b) and _selected(ob, b))


def _hide(ob, bones):
    for b in bones:
        b[OWN] = True
        b[LAST] = True
        _select(ob, b, False)


def _show(ob, bones, select):
    for b in bones:
        for key in (OWN, LAST, KEPT):
            if key in b:
                del b[key]
        if select:
            _select(ob, b, True)


def show_all(context, in_mode=False):
    """Every joint visible (Display > Show > All, Show > Joints); returns how many joints come back."""
    n = 0
    for ob in _armatures(context, in_mode):
        normalize(ob)
        n += sum(1 for b in _bones(ob) if _hidden_now(ob, b))
        _show(ob, [b for b in _bones(ob) if b.get(OWN)], select=False)
        apply(ob)
    return n


def show_last(context, in_mode=False):
    """The joints the latest hide hid come back selected (Show Last Hidden); returns their count."""
    n = 0
    for ob in _armatures(context, in_mode):
        normalize(ob)
        last = [b for b in _bones(ob) if b.get(LAST)]
        _show(ob, last, select=ob.mode in {'POSE', 'EDIT'})
        apply(ob)
        n += len(last)
    return n


def hide(context, action):
    """Joint part of a hide / toggle / show in Pose or Edit mode (``action`` as ``visibility.ACTIONS``); returns
    the joint count. Hiding joints drops the old "last hidden" joints (the caller drops the objects')."""
    obs = _armatures(context)
    every = _armatures(context, in_mode=False)
    for ob in every:
        normalize(ob)
    n = 0
    if action in {'HIDE', 'HIDE_UNSELECTED', 'HIDE_ALL', 'HIDE_TYPE'} or (
            action == 'TOGGLE' and selection_count(context)):
        _clear(every, LAST)
    for ob in obs:
        bones = list(_bones(ob))
        sel = [b for b in bones if not _hidden_now(ob, b) and _selected(ob, b)]
        if action == 'HIDE':
            _hide(ob, sel)
            n += len(sel)
        elif action == 'HIDE_UNSELECTED':
            # the selection's chain stays: its parents (a hidden parent would hide it) and the joints below it
            keep = set()
            for b in sel:
                keep.update(x.name for x in (b, *b.children_recursive))
                p = b.parent
                while p is not None:
                    keep.add(p.name)
                    p = p.parent
            rest = [b for b in bones if b.name not in keep and not _own_or_above(b)]
            _hide(ob, rest)
            n += len(rest)
        elif action in {'HIDE_ALL', 'HIDE_TYPE'}:
            roots = [b for b in bones if b.parent is None and not b.get(OWN)]
            _hide(ob, roots)
            n += len(roots)
        elif action == 'SHOW_SELECTED':
            kept = [b for b in bones if b.get(KEPT)]
            _show(ob, kept, select=True)
            n += len(kept)
        elif action == 'TOGGLE':
            kept = [b for b in bones if b.get(KEPT) and b not in sel]
            if sel:
                _hide(ob, sel)
                for b in sel:
                    b[KEPT] = True
            _show(ob, [b for b in kept if b.get(OWN)], select=True)
            n += len(sel) + len(kept)
        apply(ob)
    return n
