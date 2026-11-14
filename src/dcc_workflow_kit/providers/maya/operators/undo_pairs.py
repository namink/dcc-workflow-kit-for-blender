# SPDX-License-Identifier: GPL-3.0-or-later
"""Undo steps the kit adds right after one of Blender's, taken back and brought back together with it.

Some kit work can only run after Blender has pushed the undo step of the user's action: Auto Key keys a transform
once it ended, the Maya joint pick finishes a box selection after Blender's box select. The kit's step then comes
right after Blender's, and one Ctrl+Z would take back only the kit's part (the key, the joint pick) — the user
presses again and again. Maya makes such a command one undo chunk.

``push`` pushes the kit's step paired with the step before it: it writes a new id into
``Scene.allset_undo_pair_step`` first, so every step remembers the newest paired step at its time. When an Undo
leaves a paired step and lands on the step before it, the kit takes one more Undo (from a timer: the undo system is
busy in its own handlers); when a Redo lands on that step on its way back to the paired step, one more Redo. A
``check`` callable tells whether the landed state really is the user's action (Auto Key: the scene holds the keyed
values); without one the pair is always taken together.

Object-mode steps inside an edit-mode command (``push_through``): an edit-mode command that also changes object data
(Soften Edge giving way to a Smooth by Angle modifier) makes that change in object mode, because an edit-mode undo
step holds only the mesh. It pushes the object-mode state before it (``BEFORE``, named "Object Mode" in Undo
History), the same state back in edit mode ("Edit Mode"), and the object-mode result (``AFTER``, the command's own
step, named after the command), then goes back to edit mode. Ctrl+Z right after it lands on the edit-mode state
before it (Blender reads the ``BEFORE`` step's data on the way). Each object-mode step carries its kind in
``Scene.allset_undo_through`` (only in that step's saved data: the value in memory goes back to 0 right after the push
and after every undo / redo). An undo / redo that lands on an ``AFTER`` step goes back to edit mode (the result, as
the command left it); one that lands on a ``BEFORE`` step goes on in the same direction (Ctrl+Z to the step before
the command, Shift+Z to its result). Next to a ``BEFORE`` step the edit-mode copy of the state before the command and
the step before the command look alike: when the press started in edit mode it goes past that one too, so no press
seems to do nothing.

Undo History can jump over several steps at once, and the undo handlers run once for the whole jump. The steps of
one command also carry its number in ``Scene.allset_undo_through_at`` (+n in the ``BEFORE`` step, -n from the
``AFTER`` step on; kept in memory, so the edit-mode steps read the number of the object-mode step they follow). An
undo that lands on a ``BEFORE`` step continues only when it started on that command's "Edit Mode" step (+n), which is
what one Ctrl+Z from there does; a jump from the result or a later step stops on the "Object Mode" line it picked, in
object mode with the state before the command. A redo that lands on a ``BEFORE`` step can't be told from Shift+Z on
the step before the command, so it goes on to the result.

Blender reads the newest object-mode step back from memory, not from its data (only a later object-mode step tells
what changed after it), so its kind is lost there: until the next object-mode state (``arm``), an undo from edit mode
that lands in object mode on the command's result is taken as its ``AFTER`` step.
"""

from contextlib import nullcontext

import bpy
from bpy.app.handlers import persistent

BEFORE, AFTER = 1, 2   # Scene.allset_undo_through: an object-mode step inside an edit-mode command
# Undo History names of the steps before an edit-mode command's object-mode result, like the steps of Tab
OBJECT_MODE_STEP, EDIT_MODE_STEP = "Object Mode", "Edit Mode"
EDIT = 'EDIT'          # the extra action that goes back to edit mode
_MAX_EXTRA = 16        # extra steps one press may take

_steps = {}            # paired step id -> (id of the step before it, check or None)
_marks = []            # one per user undo, newest last: the paired step id it went past (0 = none)
_extra = {"want": None, "running": False, "count": 0, "through": None, "busy": False}
_before = [0]          # step id when the undo / redo started
_start_edit = [False]  # the undo / redo started in edit mode
_start_at = [0]        # Scene.allset_undo_through_at when the undo / redo started
_command = [0]         # the newest command number push_through gave out
_user_moves = [0]      # user undo / redo presses (an extra step is dropped when another press came first)
_tail = {}             # "names", "print": the newest AFTER step's objects and what their data looked like


def step_id(scene):
    return int(getattr(scene, "allset_undo_pair_step", 0) or 0)


def _mark(scene, kind):
    scene.allset_undo_through = kind
    scene.update_tag()


def _at(scene):
    try:
        return int(getattr(scene, "allset_undo_through_at", 0) or 0)
    except (AttributeError, ReferenceError, TypeError):
        return 0


def push_through(scene, label, kind):
    """Push the object-mode step ``label`` of an edit-mode command (``kind`` BEFORE / AFTER). Raises RuntimeError
    when Blender can't push."""
    if kind == BEFORE:
        _command[0] = max(_command[0], abs(_at(scene))) + 1
        scene.allset_undo_through_at = _command[0]
    else:
        scene.allset_undo_through_at = -_command[0]
    _mark(scene, kind)
    try:
        bpy.ops.ed.undo_push(message=label)
    finally:
        _mark(scene, 0)


def _attr(me, name):
    a = me.attributes.get(name)
    if a is None:
        return None
    out = [0] * len(a.data)
    a.data.foreach_get("value", out)
    return hash(tuple(out))


def fingerprint(names):
    """What the objects ``names`` hold in object mode (None in edit mode): modifiers, mesh size, hard edges, smooth
    faces, selection."""
    out = []
    for name in names:
        ob = bpy.data.objects.get(name)
        if ob is None or ob.type != 'MESH':
            out.append(None)
            continue
        if ob.mode == 'EDIT':
            return None
        me = ob.data
        out.append((name, tuple((md.name, md.type) for md in ob.modifiers),
                    (len(me.vertices), len(me.edges), len(me.polygons)),
                    tuple(_attr(me, n) for n in ("sharp_edge", "sharp_face", ".select_vert", ".select_edge",
                                                  ".select_poly"))))
    return tuple(out)


def arm(names, result):
    """The command's AFTER step (its result: ``fingerprint(names)`` == ``result``) is the newest object-mode step."""
    _tail["names"] = list(names)
    _tail["print"] = result


def _tail_here():
    return bool(_tail) and _tail.get("print") is not None and fingerprint(_tail["names"]) == _tail["print"]


def _take_mark(scene):
    """The landed step's ``allset_undo_through`` kind; the value in memory goes back to 0 (a later step must not
    inherit it)."""
    try:
        kind = int(getattr(scene, "allset_undo_through", 0) or 0)
        if kind:
            _mark(scene, 0)
    except (AttributeError, ReferenceError, TypeError):
        return 0
    return kind


def _edit_mode():
    try:
        return bpy.context.mode.startswith("EDIT")
    except AttributeError:
        return False


def _through_next(direction, left, scene):
    """After a step of an undo / redo that left the object-mode step ``left`` (BEFORE / AFTER, 0 = an extra step
    past a look-alike, None = a paired step): the kind of step to go on from, EDIT to go back to edit mode and stop,
    or None to stop here."""
    here = _take_mark(scene)
    edit = _edit_mode()
    if not edit and here == BEFORE:
        return BEFORE             # the state before a command: on to the step before it / to its result
    if not edit and here == AFTER:
        if direction == 'UNDO' and left == BEFORE:
            return AFTER          # the command before this one: its result is what the press started from
        return EDIT
    if left == BEFORE and edit and (direction == 'UNDO' or _start_edit[0]):
        return 0                  # this edit-mode step looks just like the one the press started from
    return None


def push(scene, label, check=None):
    """Push the kit's step ``label``, paired with the step before it."""
    prev = step_id(scene)
    new = max([prev] + list(_steps)) + 1
    try:
        scene.allset_undo_pair_step = new
        bpy.ops.ed.undo_push(message=label)
    except (RuntimeError, AttributeError, TypeError):
        return
    _steps[new] = (prev, check)


def extra_running():
    """The kit is taking the extra undo / redo step (other undo handlers ignore it)."""
    return _extra["running"]


def wanted():
    """The extra step waiting for its timer: 'UNDO', 'REDO', 'EDIT' (back to edit mode) or None."""
    return _extra["want"]


def _ok(step, scene):
    check = step[1]
    if check is None:
        return True
    try:
        return bool(check(scene))
    except (ReferenceError, AttributeError, KeyError, TypeError, ValueError):
        return False


def _want(direction, through=None):
    _extra["want"] = direction
    _extra["through"] = through
    _extra["count"] = _user_moves[0]
    if not bpy.app.timers.is_registered(run_extra):
        bpy.app.timers.register(run_extra, first_interval=0.0)


def run_extra():
    """Take the extra step now (the timer; tests call it directly)."""
    direction, _extra["want"] = _extra["want"], None
    left, _extra["through"] = _extra["through"], None
    try:
        _run(direction, left)
    finally:
        _extra["busy"] = False
    return None


def _run(direction, left):
    if direction is None or _extra["count"] != _user_moves[0]:
        return
    wm = bpy.context.window_manager
    # Blender empties the registered operators on undo / redo: one there now ran after it (Adjust Last Operation
    # re-runs its operator through an undo), so the user is somewhere else
    if wm is None or len(wm.operators):
        return
    window = bpy.context.window or next(iter(wm.windows), None)
    _extra["running"] = True
    try:
        with bpy.context.temp_override(window=window) if window is not None else nullcontext():
            for _ in range(_MAX_EXTRA):
                if left == EDIT:
                    if _tail.get("names"):        # this result is the newest object-mode step again
                        _tail["print"] = fingerprint(_tail["names"])
                    bpy.ops.object.mode_set(mode='EDIT')
                    break
                res = bpy.ops.ed.undo() if direction == 'UNDO' else bpy.ops.ed.redo()
                if 'FINISHED' not in res:
                    break
                left = _through_next(direction, left, bpy.context.scene)
                if left is None:
                    break
    except (RuntimeError, ReferenceError):
        pass
    finally:
        _extra["running"] = False


@persistent
def _on_pre(scene, *_args):
    if _extra["running"]:
        return
    _user_moves[0] += 1
    _extra["busy"] = True
    _before[0] = step_id(scene)
    _start_edit[0] = _edit_mode()
    _start_at[0] = _at(scene)


def _through_landed(direction, scene):
    """A user undo / redo landed: on an object-mode step inside an edit-mode command it goes on (True)."""
    kind = _take_mark(scene)
    if _edit_mode():
        return False
    if not kind and direction == 'UNDO' and _start_edit[0] and _tail_here():
        kind = AFTER              # the newest object-mode step: Blender kept the scene in memory, without its kind
    if kind == AFTER:
        _want(EDIT, EDIT)
        return True
    if kind == BEFORE:
        if direction == 'UNDO' and _start_at[0] != _at(scene):
            return False          # an Undo History jump from the result or later: stays on the line it picked
        _want(direction, BEFORE)
        return True
    return False


@persistent
def _on_undo_post(scene, *_args):
    if _extra["running"]:
        return
    left, here = _before[0], step_id(scene)
    step = _steps.get(left)
    if left != here and step is not None and step[0] == here and _ok(step, scene):
        _marks.append(left)               # the kit's step was taken back: take back the user's action too
        _want('UNDO')
        _take_mark(scene)
    else:
        _marks.append(0)
        if not _through_landed('UNDO', scene):
            _extra["busy"] = False


@persistent
def _on_redo_post(scene, *_args):
    if _extra["running"]:
        return
    mark = _marks.pop() if _marks else 0
    step = _steps.get(mark)
    if step is not None and step_id(scene) == step[0] and _ok(step, scene):
        _want('REDO')                     # the user's action is back: the kit's part comes with it
        _take_mark(scene)
    elif not _through_landed('REDO', scene):
        _extra["busy"] = False


@persistent
def _on_depsgraph(*_args):
    """Object mode outside an undo / redo: a later object-mode step may follow, the newest result is no longer known."""
    if _tail.get("print") is not None and not _extra["busy"] and not _extra["running"] and not _edit_mode():
        _tail["print"] = None


@persistent
def reset(*_args):
    _steps.clear()
    _marks.clear()
    _tail.clear()
    _extra["want"] = None
    _extra["through"] = None
    _extra["busy"] = False


_HANDLERS = (("undo_pre", _on_pre), ("redo_pre", _on_pre), ("undo_post", _on_undo_post),
             ("redo_post", _on_redo_post), ("depsgraph_update_post", _on_depsgraph), ("load_post", reset))


def register():
    bpy.types.Scene.allset_undo_pair_step = bpy.props.IntProperty(options={'HIDDEN'})
    bpy.types.Scene.allset_undo_through = bpy.props.IntProperty(options={'HIDDEN'})
    bpy.types.Scene.allset_undo_through_at = bpy.props.IntProperty(options={'HIDDEN'})
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name)
        if fn not in lst:
            lst.append(fn)


def unregister():
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name)
        while fn in lst:
            lst.remove(fn)
    if bpy.app.timers.is_registered(run_extra):
        bpy.app.timers.unregister(run_extra)
    reset()
    del bpy.types.Scene.allset_undo_through_at
    del bpy.types.Scene.allset_undo_through
    del bpy.types.Scene.allset_undo_pair_step
