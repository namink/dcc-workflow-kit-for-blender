# SPDX-License-Identifier: GPL-3.0-or-later
"""The order the selected objects were picked in, like Maya's selection list, and the lead that follows it.

Maya keeps the selection as a list in pick order; its last node is the lead. Blender keeps a selected flag per object
and one active object, and only a click makes the clicked object active: a box, lasso or circle drag, an Outliner box
or range, Select All and the select menus add objects and leave the active one alone. So the kit follows the
selection as it changes and keeps the order itself, per view layer:

- objects that get selected go to the end; several at once (one box) go in name order, the active one last when it
  is among them;
- an object that becomes the active one while selected (a click on an object already selected) moves to the end;
- objects that get deselected drop out.

The order is kept in memory only, objects by ``session_uid`` (it stays the same across undo and renames). After a
file load, or for a selection made while nothing was looking, it starts from the selection: the active object last,
the others by name.

The lead (Maya mode, Object mode): Blender's tools and outline, the Channel Box, the Attribute Editor and the
lead-coloured selection wire all show the active object as the lead. So once the user's selection has changed the kit
makes the last pick the active object, in one undo with that selection (``follow``):

- after a selecting operator that pushed its own undo step (a box, lasso or circle drag, an Outliner click, range or
  box, Select All, the Select menu, a click that deselects the lead): the kit's step is paired with the operator's
  (``undo_pairs``), so one Undo takes both back and one Redo brings both back;
- in a kit command (menus, shelf, marking menus): inside the command's own undo step (``undo_steps.command``);
- after a drag the kit finishes itself (joints in a marquee, ``joint_marquee``) or an Outliner Ctrl+click the kit
  turns into a toggle (``select_2d``): after that step, so it waits for them.

A selection a script makes (no operator) keeps Blender's active object; Match Transformations reads the pick order
itself, so it agrees either way. In Pose mode Maya's lead is the joint picked last (the rig's active bone): the active
object stays.
"""

from contextlib import nullcontext

import bpy
from bpy.app.handlers import persistent

# (scene session_uid, view layer name) -> object session_uids, first pick first
_orders = {}
# same key -> session_uid of the active object when the order was last brought up to date (0: none)
_actives = {}
# the newest registered operator seen (pointer, 0: none) and the window it ran in, for ``run_follow``
_ops = {"last": 0, "window": 0, "waited": 0.0}
_RETRY = 0.05
_GIVE_UP = 3.0           # s waiting for the kit's own finishing step (a marquee that never ends)
# operators that pick objects: Blender's 3D View / object / Outliner selection and the kit's own select commands
SELECT_PREFIXES = ("VIEW3D_OT_select", "OBJECT_OT_select", "OUTLINER_OT_select", "ALLSET_OT_select")
SELECT_OPS = {"OUTLINER_OT_item_activate"}


def _sync(scene, view_layer):
    """Bring the order of ``view_layer`` up to date with its selection; the selected objects in pick order."""
    key = (scene.session_uid, view_layer.name)
    selected = {ob.session_uid: ob for ob in view_layer.objects.selected}
    order = [uid for uid in _orders.get(key, ()) if uid in selected]
    active = view_layer.objects.active
    active_uid = active.session_uid if active is not None else 0
    known = set(order)
    added = [ob for uid, ob in selected.items() if uid not in known]
    added.sort(key=lambda ob: (ob.session_uid == active_uid, ob.name_full))
    order += [ob.session_uid for ob in added]
    if active_uid in selected and active_uid != _actives.get(key) and order[-1] != active_uid:
        order.remove(active_uid)
        order.append(active_uid)
    _orders[key] = order
    _actives[key] = active_uid
    return [selected[uid] for uid in order]


def ordered(context):
    """The selected objects of the context's view layer in pick order: the last one is Maya's lead."""
    return _sync(context.scene, context.view_layer)


def last(context):
    """The last picked of the selected objects (Maya's lead), or None when nothing is selected."""
    obs = ordered(context)
    return obs[-1] if obs else None


# --- the lead follows the last pick ----------------------------------------------------------------------------------

def follow(context):
    """Maya mode, Object mode: make the last picked of the selected objects the active one (Maya's lead). Pushes no
    undo step: the caller's step holds it. True when the active object changed."""
    from .. import switch
    if not switch.is_on():
        return False
    scene, view_layer = getattr(context, "scene", None), getattr(context, "view_layer", None)
    if scene is None or view_layer is None:
        return False
    active = view_layer.objects.active
    if active is not None and active.mode != 'OBJECT':
        return False                    # Pose mode: the joint picked last; Edit mode: components
    obs = _sync(scene, view_layer)
    lead = obs[-1] if obs else None
    if lead is None or lead == active or lead.mode != 'OBJECT':
        return False
    try:
        view_layer.objects.active = lead
        # select_set (already selected: no change) has the Outliner highlight the new active row; setting the active
        # object alone leaves its highlight on the old one
        lead.select_set(True, view_layer=view_layer)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    _actives[(scene.session_uid, view_layer.name)] = lead.session_uid
    return True


def selecting(op):
    """``op`` (a registered operator) picks objects and pushed its own undo step."""
    idname = op.bl_idname
    return (idname.startswith(SELECT_PREFIXES) or idname in SELECT_OPS) and 'UNDO' in op.bl_options


def _kit_finishing():
    """A kit step that finishes this selection is still to come (it makes the lead itself)."""
    from . import joint_marquee, select_2d
    return joint_marquee.pending() or select_2d.click_pending()


def run_follow():
    """After a selecting operator (a timer): the last pick becomes the active object in a step paired with the
    operator's. Returns the retry interval while a kit step that finishes the selection is still to come."""
    if _kit_finishing():
        _ops["waited"] += _RETRY
        return _RETRY if _ops["waited"] < _GIVE_UP else None
    from .. import live_refs
    from . import undo_pairs
    wm = bpy.context.window_manager
    window = live_refs.window(_ops["window"]) if _ops["window"] else None
    if window is None and wm is not None and len(wm.windows):
        window = wm.windows[0]
    try:
        with bpy.context.temp_override(window=window) if window is not None else nullcontext():
            context = bpy.context
            if follow(context):
                undo_pairs.push(context.scene, "Select")
                for area in (window.screen.areas if window is not None else ()):
                    area.tag_redraw()
    except (ReferenceError, RuntimeError, AttributeError, TypeError) as e:
        print("allset: lead follow:", e)
    return None


def _watch_ops():
    """A selection changed: when a new selecting operator was registered since the last look, follow from a timer
    (its undo step is pushed by now; the kit's step comes right after it)."""
    wm = bpy.context.window_manager
    ops = wm.operators if wm is not None else ()
    ptr = ops[-1].as_pointer() if len(ops) else 0
    if ptr == _ops["last"]:
        return
    _ops["last"] = ptr
    if not ptr or not selecting(ops[-1]):
        return
    from .. import live_refs, switch
    if not switch.is_on():
        return
    window = getattr(bpy.context, "window", None)
    _ops["window"] = live_refs.pointer(window) if window is not None else 0
    _ops["waited"] = 0.0
    if not bpy.app.timers.is_registered(run_follow):
        bpy.app.timers.register(run_follow, first_interval=0.0)


@persistent
def _on_depsgraph(scene, depsgraph):
    # selection and active-object changes update the Scene alone; edits that touch no Scene can't change them
    if depsgraph is None or not depsgraph.id_type_updated('SCENE'):
        return
    try:
        _sync(depsgraph.scene, depsgraph.view_layer)
        _watch_ops()
    except (ReferenceError, AttributeError, RuntimeError):
        pass


@persistent
def _on_undo(*_args):
    # Undo / Redo empty the registered operators: the next one is new whatever its address
    _ops["last"] = 0


@persistent
def _on_load(*_args):
    _orders.clear()
    _actives.clear()
    _ops["last"] = 0


_HANDLERS = (("depsgraph_update_post", _on_depsgraph), ("load_post", _on_load),
             ("undo_post", _on_undo), ("redo_post", _on_undo))


def register_handlers():
    for name, fn in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn not in handlers:
            handlers.append(fn)


def unregister_handlers():
    for name, fn in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        while fn in handlers:
            handlers.remove(fn)
    if bpy.app.timers.is_registered(run_follow):
        bpy.app.timers.unregister(run_follow)
    _orders.clear()
    _actives.clear()
    _ops["last"] = 0
