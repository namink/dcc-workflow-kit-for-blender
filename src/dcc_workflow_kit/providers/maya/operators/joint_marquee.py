# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya marquee / lasso on joints in the Maya layout's views, where the kit draws the joints (``ui/maya_joints.py``)
and Blender's bones are off, so Blender's box and lasso selection can't see them.

Maya's rules: a marquee or lasso hits a joint when it touches one of its drawn lines (sphere rings or a bone to a
child — a bone belongs to its parent joint); each skeleton keeps only its hit joint closest to the root; when any
joint is hit the meshes in the same region are dropped (joints have the higher selection priority); Shift toggles,
Ctrl removes, Ctrl+Shift adds, as for objects.

``allset.select_through`` (first in the select tools' drag keymaps) calls ``begin``: the selection is remembered and,
once Blender's box / lasso modal has ended, the region it registered is checked against the drawn joints. When a joint
was hit the remembered selection comes back and the joints are applied with the drag's mode.

Like Maya, the first frame after the release shows the final selection. The check runs from a timer on every
main-loop pass while a drag waits, and a pass runs the event handlers (where Blender's box / lasso ends), then the
timers, then the scene evaluation and the drawing (wm.cc ``WM_main``; wm_event_system.cc ``wm_event_do_notifiers``
runs the timers first). So the joint rules run in the pass that ends Blender's box, before its result is evaluated or
drawn.

A box that changes nothing in Blender's eyes (nothing selected before, no Blender element inside) ends CANCELLED and is
not registered, so the box is also read from the running operator while it is drawn and used when nothing new was
registered. Blender pushed no undo step then, so the kit's step stands alone. A running lasso keeps its path to
itself until it ends, so the path of such a lasso is the pointer track a draw cursor callback collects while it runs.

While a drag waits, the scene evaluations are counted (a depsgraph_update_post handler; Blender runs the update
handlers only for an evaluation that updated something, scene.cc:2759-2786). When Blender's box / lasso has ended with a
result and no evaluation has run since, its selection is still waiting to be evaluated, and the joint rules are told so
(``waiting``): the kit's first operator call evaluates what is pending before it runs, so a selection written then is
evaluated in the same pass as Blender's result.
"""

import time

import bpy

from .. import live_refs

MODES = {'OBJECT', 'POSE', 'EDIT_ARMATURE'}
SELECT_OPS = {"VIEW3D_OT_select_box", "VIEW3D_OT_select_lasso"}
_GIVE_UP = 1.5          # s: a drag whose box / lasso was never seen running nor registered is dropped
_pending = []
_track = {"handle": None, "region": 0, "pts": []}      # pointer track of the running drag (region px)
_evaluations = [0]      # scene evaluations counted while a drag waits (``_count``)


def _count(*_args):
    _evaluations[0] += 1


def _counting(on):
    """The evaluation count runs only while a drag waits."""
    handlers = bpy.app.handlers.depsgraph_update_post
    if on:
        if _count not in handlers:
            handlers.append(_count)
    else:
        while _count in handlers:
            handlers.remove(_count)


def _track_cursor(*args):
    """Draw cursor callback: called for the region under the pointer while it redraws (a lasso redraws on every
    move). Keeps the pointer track of the drag's region."""
    region = bpy.context.region
    if region is None or region.as_pointer() != _track["region"] or not args:
        return
    xy = args[0] if isinstance(args[0], (tuple, list)) else args[:2]     # Blender passes the pointer first
    try:
        x, y = float(xy[0]) - region.x, float(xy[1]) - region.y       # window px -> region px
    except (TypeError, ValueError, IndexError):
        return
    pts = _track["pts"]
    if not pts or pts[-1] != (x, y):
        pts.append((x, y))


def _track_start(region):
    _track["region"], _track["pts"] = region.as_pointer(), []
    if _track["handle"] is None:
        _track["handle"] = bpy.context.window_manager.draw_cursor_add(_track_cursor, (), 'VIEW_3D', 'WINDOW')


def _track_stop():
    if _track["handle"] is not None:
        try:
            bpy.context.window_manager.draw_cursor_remove(_track["handle"])
        except (ValueError, ReferenceError, AttributeError):
            pass
        _track["handle"] = None
    _track["region"] = 0


def begin(context):
    from ..ui import maya_joints
    space = context.space_data
    if (context.mode not in MODES or context.region is None or context.region.type != 'WINDOW'
            or not maya_joints.is_maya_view(space, getattr(getattr(context, "window", None), "workspace", None))):
        return False
    _flush()            # the drags before this one have ended: their joint rules first, in order
    if not bpy.data.armatures:
        return False    # no skeleton in the file: no joint to pick, Blender's result stands
    wm = context.window_manager
    last = wm.operators[-1].as_pointer() if len(wm.operators) else 0
    _pending.append({
        "window": live_refs.pointer(context.window), "area": context.area.as_pointer(),
        "region": context.region.as_pointer(), "last": last, "snap": snapshot(context),
        "seen": False, "start": time.monotonic(), "mode": context.mode, "box": None, "evaluations": _evaluations[0],
    })
    _counting(True)
    if not bpy.app.timers.is_registered(_watch):
        bpy.app.timers.register(_watch, first_interval=0.0)
    _track_start(context.region)
    return True


EDIT_FLAGS = ("select", "select_head", "select_tail")


def _flags(seq, props):
    """(N, len(props)) bools of ``props`` of every item of ``seq``, one read per property."""
    import numpy as np
    out = np.zeros((len(props), len(seq)), bool)
    for row, prop in zip(out, props):
        seq.foreach_get(prop, row)
    return out.T


def snapshot(context):
    """The selection a drag starts from: the selected objects, the active one and every skeleton's joint picks. Read
    a collection at a time (a scene can hold thousands of objects, a rig hundreds of joints)."""
    scene, layer = context.scene, context.view_layer
    act = layer.objects.active
    bones = {}
    for ob in scene.objects:
        if ob.type != 'ARMATURE':
            continue
        if ob.mode == 'EDIT':
            ebs = ob.data.edit_bones
            bones[ob.name] = ('EDIT', ebs.keys(), _flags(ebs, EDIT_FLAGS), ebs.active.name if ebs.active else None)
        else:
            pbs = ob.pose.bones
            bones[ob.name] = ('POSE', pbs.keys(), _flags(pbs, ("select",)),
                              ob.data.bones.active.name if ob.data.bones.active else None)
    # the view layer's selected objects = the objects whose select_get() is on (hidden ones too)
    return {"names": set(scene.objects.keys()), "selected": set(layer.objects.selected.keys()),
            "active": act.name if act else None, "bones": bones}


def _changed(seq, names, want, props, now=None):
    """Indices of ``seq`` items whose ``props`` differ from ``want`` (rows of ``snapshot``'s names), with the wanted
    row: by index while the items are the same, else by name. ``now``: their flags, when read already."""
    import numpy as np
    if now is None:
        now = _flags(seq, props)
    if seq.keys() == names:
        return [(int(i), want[i]) for i in np.flatnonzero((now != want).any(axis=1))]
    rows = dict(zip(names, want))
    out = []
    for i, name in enumerate(seq.keys()):
        row = rows.get(name)
        if row is not None and (now[i] != row).any():
            out.append((i, row))
    return out


def restore(context, snap, defer=False):
    """Back to ``snapshot``. Only what differs is written: a write makes Blender evaluate the skeleton (and what it
    deforms) again even with the same value. ``defer``: the joint selection of skeletons not in Edit Mode is not
    written but returned, {skeleton pointer: (skeleton, its pose bones' selection as bools)} for those that differ
    (``joint_selection.select_groups`` writes it with the picks)."""
    from ..ui import channel_box
    later = {}
    scene, objects = context.scene, context.scene.objects
    now = set(context.view_layer.objects.selected.keys())
    pick, drop = snap["selected"] - now, (now - snap["selected"]) & snap["names"]
    if drop:
        # the objects selected since are among the selected ones (a box can select thousands in a big scene)
        for ob in [ob for ob in context.view_layer.objects.selected if ob.name in drop]:
            ob.select_set(False)
    if pick:
        # one pass over the scene: looking an object up by name walks the scene's objects each time
        for ob in objects:
            if ob.name in pick:
                ob.select_set(True)
    act = snap["active"]
    if act and act in objects and context.view_layer.objects.active != objects[act]:
        context.view_layer.objects.active = objects[act]
    for name, (kind, names, states, active) in snap["bones"].items():
        ob = scene.objects.get(name)
        if ob is None:
            continue
        if kind == 'EDIT' and ob.mode == 'EDIT':
            ebs = ob.data.edit_bones
            for i, want in _changed(ebs, names, states, EDIT_FLAGS):
                ebs[i].select, ebs[i].select_head, ebs[i].select_tail = (bool(v) for v in want)
            lead = ebs.get(active) if active else None
            if ebs.active != lead:
                ebs.active = lead
        elif kind == 'POSE':
            pbs = ob.pose.bones
            now = _flags(pbs, ("select",))
            changes = _changed(pbs, names, states, ("select",), now)
            if defer and changes:
                want = now[:, 0].copy()
                for i, row in changes:
                    want[i] = bool(row[0])
                later[ob.as_pointer()] = (ob, want)
            elif not defer:
                for i, want in changes:
                    channel_box.set_bone_selected(pbs[i], bool(want[0]))
            lead = ob.data.bones.get(active) if active else None
            if ob.data.bones.active != lead:
                ob.data.bones.active = lead
    return later


def region_of(op):
    """The screen polygon (region px) of a finished select_box / select_lasso, or None."""
    props = op.properties
    if op.bl_idname == "VIEW3D_OT_select_box":
        x0, x1, y0, y1 = props.xmin, props.xmax, props.ymin, props.ymax
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    path = [tuple(p.loc) for p in props.path]
    return path if len(path) >= 3 else None


def modifiers(mode):
    """(shift, ctrl) of joint_selection.select for a box mode: SET replace, XOR toggle, SUB remove, ADD add."""
    return {'XOR': (True, False), 'SUB': (False, True), 'ADD': (True, True)}.get(mode, (False, False))


def objects_instead(context, poly, mode, lasso):
    """A drag in Pose / joint Edit mode that hit no joint: Maya selects the objects in it (Blender's box there only
    looks at bones). Leave the mode and run the same box / lasso (``poly`` from ``region_of``) on objects."""
    from . import joint_selection
    joint_selection.leave(context, clear_selection=(mode == 'SET'))
    if not lasso:
        (x0, y0), _b, (x1, y1), _d = poly
        bpy.ops.view3d.select_box(xmin=x0, xmax=x1, ymin=y0, ymax=y1, mode=mode, wait_for_input=False)
    else:
        bpy.ops.view3d.select_lasso(path=[{"name": "", "loc": q, "time": 0.0} for q in poly], mode=mode)


def apply(context, poly, mode, snap, waiting=False):
    """Maya's joint rules for a finished drag. Returns the joints selected (empty: Blender's result stands).
    ``waiting``: Blender's own result has not been evaluated yet (see ``joint_selection.select_groups``)."""
    from ..ui import maya_joints
    from . import joint_selection
    space = context.space_data
    picks = []
    for ob in context.scene.objects:
        if ob.type != 'ARMATURE' or ob.hide_select or not ob.visible_get() \
                or not ob.visible_in_viewport_get(space):
            continue
        picks.extend((ob, name) for name in maya_joints.region_pick(context, ob, poly))
    if not picks:
        return []
    shift, ctrl = modifiers(mode)
    if mode in {'SET', 'ADD'}:
        # the joints of the selection the drag started from go back with the picks (a replace clears most of them)
        restored = restore(context, snap, defer=True)
        groups = []                           # the picks skeleton by skeleton, in order
        for ob, name in picks:
            if groups and groups[-1][0] == ob:
                groups[-1][1].append(name)
            else:
                groups.append((ob, [name]))
        # the first skeleton with the drag's modifiers, the rest of a replace adds
        joint_selection.select_groups(context, groups, shift, ctrl, restored, waiting)
        return [n for _o, n in picks]
    restore(context, snap)
    for ob, name in picks:                    # toggle / remove: joint by joint
        joint_selection.select(context, ob, name, shift, ctrl)
    return [n for _o, n in picks]


def _registered(entry):
    """The box / lasso Blender registered for this drag, or None (it ended CANCELLED)."""
    wm = bpy.context.window_manager
    if not len(wm.operators):
        return None
    op = wm.operators[-1]
    if op.as_pointer() == entry["last"] or op.bl_idname not in SELECT_OPS:
        return None
    return op


def _finish(entry):
    window = live_refs.window(entry["window"])
    if window is None:
        return
    op = _registered(entry)
    if op is not None:
        poly, mode = region_of(op), op.properties.mode
    elif entry["box"] is not None:
        poly, mode = entry["box"]
    elif entry.get("lasso") and len(entry.get("track", ())) >= 3:
        poly, mode = entry["track"], entry["lasso"]
    else:
        return
    if poly is None:
        return
    area = next((a for a in window.screen.areas if a.as_pointer() == entry["area"]), None)
    region = next((r for r in area.regions if r.as_pointer() == entry["region"]), None) if area else None
    if region is None:
        return
    # Blender's box / lasso ended with a result and the scene has not been evaluated since
    waiting = op is not None and entry.get("evaluations") == _evaluations[0]
    with bpy.context.temp_override(window=window, area=area, region=region):
        picked = apply(bpy.context, poly, mode, entry["snap"], waiting)
        if not picked and entry["mode"] in {'POSE', 'EDIT_ARMATURE'}:
            lasso = (op.bl_idname == "VIEW3D_OT_select_lasso") if op is not None else bool(entry.get("lasso"))
            objects_instead(bpy.context, poly, mode, lasso)
            picked = True
        if picked:
            from . import pick_order
            pick_order.follow(bpy.context)     # objects boxed after the joints: the last pick leads, in this step
            if op is not None:
                from . import undo_pairs       # one undo with Blender's box select step before it
                undo_pairs.push(bpy.context.scene, "Select")
            else:
                bpy.ops.ed.undo_push(message="Select")
            for a in window.screen.areas:
                a.tag_redraw()


def _running(entry):
    """Blender's box / lasso modal of this drag is still running; keeps the box drawn so far in ``entry``."""
    window = live_refs.window(entry["window"])
    try:
        ops = [op for op in window.modal_operators if op.bl_idname in SELECT_OPS] if window is not None else []
        for op in ops:
            if op.bl_idname == "VIEW3D_OT_select_box":
                p = op.properties
                if p.xmin != p.xmax or p.ymin != p.ymax:
                    entry["box"] = (region_of(op), p.mode)
            else:
                entry["lasso"] = op.properties.mode
                entry["track"] = list(_track["pts"])
        return bool(ops)
    except ReferenceError:
        return False


def _watch():
    for entry in list(_pending):
        running = _running(entry)
        ended = _registered(entry) is not None
        if running or not ended:
            entry["evaluations"] = _evaluations[0]      # Blender's box / lasso has no result yet
        entry["seen"] = entry["seen"] or running
        if not running and (entry["seen"] or ended):
            _pending.remove(entry)
            try:
                _finish(entry)
            except (ReferenceError, RuntimeError, AttributeError, KeyError) as e:
                print("allset: joint marquee:", e)
        elif not entry["seen"] and time.monotonic() - entry.get("start", 0.0) >= _GIVE_UP:
            _pending.remove(entry)
    if not _pending:
        _track_stop()
        _counting(False)
        return None
    return 0.0          # again on the next main-loop pass (see the module notes)


def _flush():
    """Apply the joint rules of every drag whose box / lasso has ended. A new drag starts only once the one before it
    ended, so however fast drags follow each other each one is finished, and its selection remembered, before the
    next one begins."""
    for entry in list(_pending):
        if _running(entry):
            continue
        _pending.remove(entry)
        if not (entry["seen"] or _registered(entry) is not None):
            continue                  # never seen running and nothing registered: Blender's box didn't start
        try:
            _finish(entry)
        except (ReferenceError, RuntimeError, AttributeError, KeyError) as e:
            print("allset: joint marquee:", e)


def pending():
    """A drag is waiting for its joint rules (they run once Blender's box / lasso has ended)."""
    return bool(_pending)


def cancel_all():
    _pending.clear()
    _track_stop()
    _counting(False)
    if bpy.app.timers.is_registered(_watch):
        bpy.app.timers.unregister(_watch)
