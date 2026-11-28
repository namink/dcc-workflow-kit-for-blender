# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Skeleton > Enable IK/FK Control and Enable IK Handle Snap on kit IK handles.

In Maya the IK solver writes its result into the chain joints' rotate values (joints without keys): the Channel Box
shows the solved rotation, and with Ik Blend going from 1 to 0 the joints stay in the IK pose. Blender's IK constraint
leaves the bone channels alone (they stay the FK values), so a handler here writes the solved pose into the channels
of every kit IK chain at Ik Blend 1 whose joints have no rotation keys — the same values Maya keeps.

Rotating a joint of an IK chain, Maya 2026:

- Enable IK/FK Control off (the default) and the handle keyed: the joint does not turn.
- Enable IK/FK Control off and Enable IK Handle Snap on (the default), handle not keyed: the joint turns and the handle
  follows the end joint; at Ik Blend 0 the handle stays on the end joint.
- otherwise the joint turns and the handle stays where it is.

A turned joint stays turned (with snap too) until the chain is solved again: the handle moves or turns, its Ik Blend,
Pole Vector, Twist or Solver Enable changes, the time changes while the handle has keys, or the file is opened again.
With snap at Ik Blend 1 an RP handle's pole vector turns about the start -> goal line with the start joint, so the
next solve keeps the plane the start joint was turned into.

Enable IK Handle Snap is greyed out while Enable IK/FK Control is on (it has no effect then). Both are global checks
(kit session state, like Enable IK Solver).
"""

import bpy
from bpy.app.handlers import persistent

from .. import update_summary
from . import ik_fk

_STATE = {"control": False, "snap": True}
_seen = {}                 # constraint pointer -> {bone name: channel values} last seen or written
_held = {}                 # handle name -> its state when the chain was held (a change solves the chain again)
_found = [None, []]        # (objects_version, object count) of the last look, [(armature, bone, IK constraint)]
_busy = []
ROT_EPS = 1e-4             # channel change that counts (radians / quaternion units)
POS_EPS = 1e-6

_XFORM_PATHS = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle")


def control_on():
    return _STATE["control"]


def snap_on():
    """Enable IK Handle Snap in effect (Maya ignores it while IK/FK control is on)."""
    return _STATE["snap"] and not _STATE["control"]


# --- chains ---------------------------------------------------------------------------------------------------------

def kit_chains():
    """[(armature, constrained pose bone, IK constraint)] whose target is a kit IK handle (it has Ik Blend)."""
    out = []
    for ob in bpy.data.objects:
        if ob.type != 'ARMATURE' or ob.pose is None:
            continue
        for pb in ob.pose.bones:
            for con in pb.constraints:
                t = con.target if con.type == 'IK' else None
                if t is not None and t.type != 'ARMATURE' and ik_fk.IK_BLEND in t.keys():
                    out.append((ob, pb, con))
    return out


def _chains():
    from ..ui.outliner import objects_version
    key = (objects_version(), len(bpy.data.objects))
    if _found[0] != key:
        _found[0], _found[1] = key, kit_chains()
    return _found[1]


def channels(pb):
    return tuple(getattr(pb, ik_fk.rotation_path(pb)))


def basis_channels(pb, basis):
    """The rotation channel values that give ``basis`` (what ``ik_fk.write_rotation`` would write)."""
    q = basis.to_quaternion()
    if pb.rotation_mode == 'QUATERNION':
        if q.dot(pb.rotation_quaternion) < 0.0:
            q.negate()
        return tuple(q)
    if pb.rotation_mode == 'AXIS_ANGLE':
        axis, angle = q.to_axis_angle()
        return (angle, *axis)
    return tuple(q.to_euler(pb.rotation_mode, pb.rotation_euler))


def _differ(a, b):
    return any(abs(x - y) > ROT_EPS for x, y in zip(a, b))


def _animated_paths(ob):
    from .. import compat
    paths = {fc.data_path for fc in compat.id_fcurves(ob)}
    ad = ob.animation_data
    if ad is not None:
        paths.update(fc.data_path for fc in ad.drivers)
    return paths


def handle_keyed(handle):
    """The handle has transform keys (Maya: the joints of its chain don't turn while IK/FK control is off)."""
    from .. import compat
    return any(fc.data_path in _XFORM_PATHS for fc in compat.id_fcurves(handle))


def _move_handle(handle, where):
    if (handle.matrix_world.translation - where).length <= POS_EPS:
        return False
    update_summary.wrote()
    mw = handle.matrix_world.copy()
    mw.translation = where
    handle.matrix_world = mw
    return True


def _set_channels(pb, values):
    update_summary.wrote()
    setattr(pb, ik_fk.rotation_path(pb), values)


# --- a turned joint stays turned until the handle changes ------------------------------------------------------------
# Maya solves an IK chain again only when its handle changes (translate, rotate, Ik Blend, pole vector, twist, Solver
# Enable) or, for a handle with keys, when the time changes; until then a turned joint of the chain stays turned
# (selecting, moving the skeleton, turning or keying other joints solve nothing). The kit shows the turned pose by
# switching the chain's IK influence off with the handle's hold switch (``ik_fk.HOLD``) and on again at those changes.

def held(handle):
    return bool(handle.get(ik_fk.HOLD))


def _signature(handle, con):
    from . import ik_rp
    vals = [v for row in handle.matrix_world for v in row]
    vals.append(ik_fk.blend_of(con))
    vals += [float(handle.get(n, 0.0)) for n in ik_rp.PV]
    vals.append(float(handle.get(ik_rp.TWIST, 0.0)))
    vals.append(1.0 if con.mute else 0.0)
    return tuple(vals)


def _same(a, b):
    return len(a) == len(b) and all(abs(x - y) <= POS_EPS for x, y in zip(a, b))


def _hold(arm, pb, con, handle):
    if not held(handle):
        update_summary.wrote()
        ik_fk.ensure_hold(arm, pb, con)
        handle[ik_fk.HOLD] = 1.0
        handle.update_tag()
    _held[handle.name] = _signature(handle, con)


def release(handle):
    """Solve the chain again (the handle changed)."""
    if held(handle):
        update_summary.wrote()
        handle[ik_fk.HOLD] = 0.0
        handle.update_tag()
    _held.pop(handle.name, None)


def _handle_animated(handle):
    from .. import compat
    if any(True for _fc in compat.id_fcurves(handle)):
        return True
    ad = handle.animation_data
    return ad is not None and len(ad.drivers) > 0


def _check_release(handle, con, frame):
    """Release a held chain whose handle changed. True when released."""
    if not held(handle):
        return False
    sig = _signature(handle, con)
    old = _held.get(handle.name)
    if old is None:
        _held[handle.name] = sig            # after undo / redo: changes count from here
        return False
    if _same(old, sig) and not (frame and _handle_animated(handle)):
        return False
    release(handle)
    return True


# --- the start joint's solve plane (RP handles, Maya's pole vector follows a turned joint with snap) -----------------

def _normal_local(arm, bones, handle):
    """The RP solve plane's normal in the start joint's frame, read from the solved (shown) pose."""
    from . import ik_rp
    if ik_rp.HELPER not in handle.keys():
        return None
    root = bones[0]
    root_w = arm.matrix_world @ root.head
    n = ik_rp.solve_plane_normal(handle, root_w, handle.matrix_world.translation)
    if n.length < 1e-9:
        return None
    rot = (arm.matrix_world.to_3x3() @ root.matrix.to_3x3()).normalized()
    return rot.inverted() @ n.normalized()


def _fk_start_rot(arm, root):
    """World rotation (3x3) of the start joint posed by its own channels."""
    if root.parent is not None:
        m = root.parent.matrix @ (root.parent.bone.matrix_local.inverted() @ root.bone.matrix_local)
    else:
        m = root.bone.matrix_local.copy()
    return (arm.matrix_world.to_3x3() @ (m @ root.matrix_basis).to_3x3()).normalized()


def update_chain(arm, pb, con, animated, frame=False):
    """Apply Maya's IK / FK rules to one kit chain. Returns True when something was written."""
    handle = con.target
    key = con.as_pointer()
    bones = ik_fk.chain(pb, con)
    released = _check_release(handle, con, frame)
    hold = held(handle)
    if con.mute or any(b.path_from_id(ik_fk.rotation_path(b)) in animated for b in bones):
        _seen.pop(key, None)            # keyed joints: their curves give the FK values (Maya keeps them too)
        return released
    cur = {b.name: channels(b) for b in bones}
    seen = _seen.get(key)
    if seen is not None and seen["ch"].keys() != cur.keys():
        seen = None
    prev = seen["ch"] if seen is not None else None
    blend = ik_fk.blend_of(con)
    full = blend >= 1.0 - 1e-6
    wrote = released
    changed = prev is not None and any(_differ(cur[n], prev[n]) for n in cur)
    if (seen is not None and not full and seen["blend"] >= 1.0 - 1e-6 and not changed and seen["ik"] is not None
            and any(_differ(cur[n], seen["ik"][n]) for n in cur)):
        # Ik Blend left 1: the joints keep the last IK solution (Maya's rotate values)
        for b in bones:
            _set_channels(b, seen["ik"][b.name])
        cur = dict(seen["ik"])
        wrote = True
    snap = snap_on() and not handle_keyed(handle)
    normal = seen.get("n") if seen is not None else None
    if blend <= 1e-6:                   # FK: the joints turn freely; with snap the handle sits on the end joint
        _seen[key] = {"ch": cur, "ik": None, "blend": blend, "n": normal}
        return (snap and _move_handle(handle, ik_fk.fk_end(arm, pb, con))) or wrote
    bases = ik_fk.visual_bases(arm, bones)
    shown = {b.name: basis_channels(b, bases[b.name]) for b in bones}
    if changed and (hold or any(_differ(cur[n], shown[n]) for n in cur)):
        # a joint of the chain was turned
        if not control_on() and handle_keyed(handle):
            for b in bones:             # Maya: the joint doesn't turn
                if _differ(cur[b.name], prev[b.name]):
                    _set_channels(b, prev[b.name])
            return True
        from . import ik_rp
        if isinstance(handle.get(ik_rp.POLE_OBJECT), bpy.types.Object):
            # a Pole Vector constraint drives the handle: Maya solves the chain again right away
            _seen[key] = {"ch": cur, "ik": seen["ik"] if seen is not None else None, "blend": blend, "n": normal}
            return wrote
        moved = False
        if snap:
            end = ik_fk.fk_end(arm, pb, con)
            if full and normal is not None:
                if ik_rp.follow_turn(handle, arm.matrix_world @ bones[0].head, normal,
                                     _fk_start_rot(arm, bones[0]), end):
                    update_summary.wrote()
                    wrote = True
            moved = _move_handle(handle, end)
        _hold(arm, pb, con, handle)     # Maya shows the turned pose until the handle changes
        ik = seen["ik"] if (seen is not None and not moved) else None
        _seen[key] = {"ch": cur, "ik": ik, "blend": blend, "n": normal}
        return True
    if hold or released:                # the turned pose is shown (released: IK is back from the next update)
        _seen[key] = {"ch": cur, "ik": seen["ik"] if seen is not None else None, "blend": blend, "n": normal}
        return wrote
    ik = shown if full else None
    normal = _normal_local(arm, bones, handle) if full else normal
    if prev is not None and full and any(_differ(cur[n], shown[n]) for n in cur):
        for b in bones:                 # Maya: the solved rotation is the joints' rotate value
            if _differ(cur[b.name], shown[b.name]):
                _set_channels(b, shown[b.name])
        _seen[key] = {"ch": shown, "ik": ik, "blend": blend, "n": normal}
        return True
    _seen[key] = {"ch": cur, "ik": ik, "blend": blend, "n": normal}
    return wrote


def _playing():
    wm = bpy.context.window_manager
    return wm is not None and any(w.screen is not None and w.screen.is_animation_playing for w in wm.windows)


def update(frame=False):
    if _busy:
        return
    try:
        if not _chains():               # no kit IK chain (the usual case): nothing to do, also on every frame
            return
    except (ReferenceError, AttributeError, RuntimeError):
        _found[0] = None
        return
    from . import anim_snapshot
    if anim_snapshot._busy:
        return
    if _playing():
        if frame:
            _release_on_frame()
        return
    _busy.append(1)
    try:
        wrote = False
        animated = {}
        for arm, pb, con in _chains():
            if arm.mode == 'EDIT':
                continue
            paths = animated.get(arm.name)
            if paths is None:
                paths = animated[arm.name] = _animated_paths(arm)
            wrote |= update_chain(arm, pb, con, paths, frame)
        if wrote:
            for arm in {a for a, _p, _c in _found[1]}:
                arm.update_tag()
    except (ReferenceError, AttributeError, RuntimeError):
        _found[0] = None
        _seen.clear()
        _held.clear()
    finally:
        _busy.clear()


def _release_on_frame():
    """Playback: a held chain whose handle has keys is solved again (Maya evaluates the keyed handle each frame)."""
    _busy.append(1)
    try:
        for arm, _pb, con in _chains():
            handle = con.target
            if held(handle) and _handle_animated(handle):
                release(handle)
                arm.update_tag()
    except (ReferenceError, AttributeError, RuntimeError):
        _found[0] = None
    finally:
        _busy.clear()


def release_all():
    """Solve every held chain again (a file is opened: Maya evaluates every handle)."""
    for ob in bpy.data.objects:
        if ob.get(ik_fk.HOLD):
            ob[ik_fk.HOLD] = 0.0
            ob.update_tag()
    _held.clear()


_pending = [False]


def _rerun():
    _pending[0] = False
    update()
    return None


def pole_moved():
    """An RP handle's pole or bone helpers moved inside an update: Blender evaluates them once more without update
    handlers, so the solved pose is read again right after (a one-shot timer)."""
    if _pending[0]:
        return
    _pending[0] = True
    if not bpy.app.timers.is_registered(_rerun):
        bpy.app.timers.register(_rerun, first_interval=0.0)


def forget():
    """Undo, redo and load: start again from the channels as they are."""
    _seen.clear()
    _held.clear()
    _found[0] = None


@persistent
def _on_update(_scene=None, _depsgraph=None):
    update()


@persistent
def _on_frame(_scene=None, _depsgraph=None):
    update(frame=True)


@persistent
def _on_reset(*_args):
    forget()


@persistent
def _on_load(*_args):
    forget()
    release_all()


# --- menu check items -----------------------------------------------------------------------------------------------

def _get_control(_self):
    return _STATE["control"]


def _set_control(_self, value):
    _STATE["control"] = bool(value)
    forget()


def _get_snap(_self):
    return _STATE["snap"]


def _set_snap(_self, value):
    if _STATE["control"]:
        return                      # greyed out in Maya while IK/FK control is on
    _STATE["snap"] = bool(value)
    forget()


_HANDLERS = (("depsgraph_update_post", _on_update), ("frame_change_post", _on_frame),
             ("undo_post", _on_reset), ("redo_post", _on_reset), ("load_post", _on_load))


def register():
    bpy.types.WindowManager.allset_ik_fk_control = bpy.props.BoolProperty(
        name="Enable IK/FK Control", get=_get_control, set=_set_control,
        description="Let the joints of an IK chain turn even when the IK handle has keys; the handle stays where it "
                    "is (Maya Skeleton > Enable IK/FK Control)")
    bpy.types.WindowManager.allset_ik_handle_snap = bpy.props.BoolProperty(
        name="Enable IK Handle Snap", get=_get_snap, set=_set_snap,
        description="The IK handle follows the end joint when a joint of its chain is turned, and stays on it at "
                    "Ik Blend 0 (Maya Skeleton > Enable IK Handle Snap)")
    for name, fn in _HANDLERS:
        hs = getattr(bpy.app.handlers, name)
        if fn not in hs:
            hs.append(fn)


def unregister():
    for name, fn in _HANDLERS:
        hs = getattr(bpy.app.handlers, name)
        if fn in hs:
            hs.remove(fn)
    del bpy.types.WindowManager.allset_ik_handle_snap
    del bpy.types.WindowManager.allset_ik_fk_control
    if bpy.app.timers.is_registered(_rerun):
        bpy.app.timers.unregister(_rerun)
    _pending[0] = False
    try:
        release_all()                   # Blender mode: the chains follow their IK again
    except (AttributeError, ReferenceError, RuntimeError):
        pass                            # no file data while Blender starts or quits
    forget()
