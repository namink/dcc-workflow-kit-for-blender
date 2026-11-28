# SPDX-License-Identifier: GPL-3.0-or-later
"""A Maya persp / top / front / side panel is its startup camera (#564), both ways:

- a change to the camera goes to the 3D Views of that camera: Near / Far Clip Plane (all four), Focal Length,
  translate and rotate (persp), Orthographic Width and translate (top / front / side; their rotation stays the
  view's, as it names the view);
- moving the view (tumble, track, dolly, zoom, the view's own clip planes and focal length) moves the camera, as
  Maya's view tools move the panel's camera.

Undo follows Maya, where camera moves are not undoable (Undoable Movements off) while attribute edits are: an undo
or redo that takes back or brings back a transform edit (Attribute Editor, Channel Box, a command) sets the camera's
place on the views; any other place it brings back (one a view move put there, saved with a later undo step) gives
way to the view's own, so undoing anything else never moves the view.

The kit's persp / ortho views are Blender's own views (``ui/panel_cameras.py``: ``panel_camera``) and the camera
objects (``operators/startup_cameras.py``) are hidden, so the depsgraph reports nothing for them: edits are heard
through message-bus subscriptions, view moves through a timer comparing each view with what it last saw. Views
looking through a camera are left alone. The cameras and views are remembered when a file loads, when Maya mode
starts and when a scene gets the cameras, so opening a file changes nothing.
"""

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

POLL = 0.1
EPS = 1e-6
TRANSFORM = ("loc", "rot", "ortho")      # the values view moves change (not undoable in Maya)

# (scene name, startup camera name) -> camera values last seen
_seen = {}
# area pointer -> (startup camera name, view values) last seen
_views = {}
# (scene name, startup camera name) -> [{"before", "after", "applied"}]: the transform edits, oldest first, as the
# undo stack has them (an undone one is dropped by the next edit, like the undo steps after it)
_edits = {}
_EDITS_KEPT = 200


def _key(scene, ob):
    from ..operators import startup_cameras
    return scene.name_full, ob.get(startup_cameras.MARK)


def _cam_values(ob):
    d = ob.data
    m = ob.matrix_basis
    return {"clip": (d.clip_start, d.clip_end), "lens": (d.lens, d.sensor_width), "ortho": d.ortho_scale,
            "loc": tuple(m.translation), "rot": tuple(v for row in m.to_3x3() for v in row)}


def _same(a, b):
    if isinstance(a, tuple):
        return len(a) == len(b) and all(abs(x - y) <= EPS * max(1.0, abs(x)) for x, y in zip(a, b))
    return abs(a - b) <= EPS * max(1.0, abs(a))


def _changed(before, now):
    return [k for k in now if not _same(before[k], now[k])]


def _transform(values):
    return {k: values[k] for k in TRANSFORM}


def _view_values(space, rv3d):
    return (tuple(rv3d.view_location), tuple(rv3d.view_rotation), rv3d.view_distance, rv3d.view_perspective,
            space.clip_start, space.clip_end, space.lens)


def _views_of(scene, name=None):
    """(area, space, rv3d, startup camera name) of every 3D View showing ``scene`` whose panel camera is a startup
    camera (``name``: only that one), not looking through a camera."""
    from .panel_cameras import startup_name_of
    for window in bpy.context.window_manager.windows:
        if window.scene != scene:
            continue
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            space = area.spaces.active
            rv3d = getattr(space, "region_3d", None)
            if rv3d is None or rv3d.view_perspective == 'CAMERA':
                continue
            view_name = startup_name_of(rv3d)
            if view_name is not None and (name is None or view_name == name):
                yield area, space, rv3d, view_name


def _cameras(scene):
    from ..operators import startup_cameras
    return {ob.get(startup_cameras.MARK): ob for ob in startup_cameras.cameras(scene) if ob.data is not None}


# --- camera -> views -------------------------------------------------------------------------

def _set_view(ob, keys, area, space, rv3d, name):
    """Put the camera values ``keys`` of ``ob`` on one view of it."""
    from ..operators.key_batch import VIEW_SENSOR
    d = ob.data
    if "clip" in keys:
        space.clip_start, space.clip_end = d.clip_start, d.clip_end
    if name == "persp":
        if "lens" in keys and d.sensor_width > 0.0:
            space.lens = d.lens * VIEW_SENSOR / d.sensor_width
        if "loc" in keys or "rot" in keys:
            rot = ob.matrix_basis.to_quaternion()
            rv3d.view_rotation = rot
            rv3d.view_location = ob.matrix_basis.translation - rot @ Vector((0.0, 0.0, rv3d.view_distance))
    else:
        if "ortho" in keys:
            rv3d.view_distance = d.ortho_scale * space.lens / VIEW_SENSOR
        if "loc" in keys:
            forward = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
            eye = ob.matrix_basis.translation
            # on the view axis through the camera, at the depth the view had
            rv3d.view_location = eye - forward * eye.dot(forward) + forward * Vector(rv3d.view_location).dot(forward)
    _views[area.as_pointer()] = (name, _view_values(space, rv3d))
    area.tag_redraw()


def push(scene, ob, keys):
    from ..operators import startup_cameras
    for area, space, rv3d, name in _views_of(scene, ob.get(startup_cameras.MARK)):
        _set_view(ob, keys, area, space, rv3d, name)


# --- views -> camera -------------------------------------------------------------------------

def _set_camera(scene, ob, space, rv3d, name):
    """Move the camera ``ob`` to where its view ``rv3d`` looks from, as Maya's view tools do."""
    from ..operators import framing, units
    from ..operators.camera_copy import ORTHO_DISTANCE, ortho_eye
    from ..operators.key_batch import VIEW_SENSOR, camera_matrix
    d = ob.data
    if not _same((d.clip_start, d.clip_end), (space.clip_start, space.clip_end)):
        d.clip_start, d.clip_end = space.clip_start, space.clip_end
    if name == "persp":
        lens = space.lens * d.sensor_width / VIEW_SENSOR
        if not _same(d.lens, lens):
            d.lens = lens
        m = camera_matrix(framing.view_matrix(rv3d.view_location, rv3d.view_rotation, rv3d.view_distance))
        loc, rot, _scale = m.decompose()
        basis = Matrix.LocRotScale(loc, rot, ob.matrix_basis.to_scale())
    else:
        width = rv3d.view_distance * VIEW_SENSOR / space.lens
        if not _same(d.ortho_scale, width):
            d.ortho_scale = width
        forward = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
        eye = ortho_eye(rv3d.view_location, forward, ORTHO_DISTANCE * units.maya_unit(scene))
        basis = ob.matrix_basis.copy()
        basis.translation = eye
    if any(abs(a - b) > EPS for ra, rb in zip(basis, ob.matrix_basis) for a, b in zip(ra, rb)):
        ob.matrix_basis = basis
    _seen[_key(scene, ob)] = _cam_values(ob)      # the view's own move: not an edit to send back


def _poll():
    try:
        for window in bpy.context.window_manager.windows:
            scene = window.scene
            cams = None
            for area, space, rv3d, name in _views_of(scene):
                now = (name, _view_values(space, rv3d))
                before = _views.get(area.as_pointer())
                _views[area.as_pointer()] = now
                if before is None or before[0] != name or before[1] == now[1]:
                    continue       # first sight, or the view turned to another camera: remember only
                if cams is None:
                    cams = _cameras(scene)
                ob = cams.get(name)
                if ob is not None:
                    _set_camera(scene, ob, space, rv3d, name)
    except (ReferenceError, RuntimeError, AttributeError):
        pass
    return POLL


# --- edits, undo -----------------------------------------------------------------------------

def remember(scene):
    """Remember the scene's startup cameras and their views as they are now (nothing is set)."""
    for ob in _cameras(scene).values():
        _seen[_key(scene, ob)] = _cam_values(ob)
    try:
        for area, space, rv3d, name in _views_of(scene):
            _views[area.as_pointer()] = (name, _view_values(space, rv3d))
    except (AttributeError, ReferenceError):
        pass


def _remember_all():
    _seen.clear()
    _views.clear()
    _edits.clear()
    try:
        for scene in bpy.data.scenes:
            remember(scene)
    except (AttributeError, ReferenceError):     # restricted context
        pass


def check(scene):
    """An edit changed camera values: remember it (for undo) and set the changed values on the views."""
    for ob in _cameras(scene).values():
        key = _key(scene, ob)
        now = _cam_values(ob)
        before = _seen.get(key)
        _seen[key] = now
        if before is None:
            continue
        keys = _changed(before, now)
        if not keys:
            continue
        if any(k in TRANSFORM for k in keys):
            edits = [e for e in _edits.get(key, ()) if e["applied"]]
            edits.append({"before": _transform(before), "after": _transform(now), "applied": True})
            _edits[key] = edits[-_EDITS_KEPT:]
        push(scene, ob, keys)


def _same_transform(a, b):
    return all(_same(a[k], b[k]) for k in TRANSFORM)


def _undid_edit(key, values, redo):
    """Did this undo (redo) take back (bring back) a transform edit: the camera is back at what the latest applied
    edit started from (at what the next undone edit set)? Marks that edit."""
    edits = _edits.get(key, ())
    t = _transform(values)
    if redo:
        e = next((e for e in edits if not e["applied"]), None)
        if e is not None and _same_transform(e["after"], t):
            e["applied"] = True
            return True
        return False
    e = next((e for e in reversed(edits) if e["applied"]), None)
    if e is not None and _same_transform(e["before"], t):
        e["applied"] = False
        return True
    return False


def after_undo(scene, redo=False):
    """Undo / redo: a transform edit it takes back or brings back goes to the views; any other transform it brings
    back (one a view move put there) gives way to the view's own, camera moves not being undoable. Clip planes and
    focal length always go to the views."""
    for ob in _cameras(scene).values():
        key = _key(scene, ob)
        now = _cam_values(ob)
        before = _seen.get(key)
        _seen[key] = now
        if before is None:
            continue
        keys = _changed(before, now)
        if not keys:
            continue
        moved = [k for k in keys if k in TRANSFORM]
        if moved and not _undid_edit(key, now, redo):
            for _area, space, rv3d, name in _views_of(scene, key[1]):
                _set_camera(scene, ob, space, rv3d, name)
                break
            keys = [k for k in keys if k not in TRANSFORM]
        if keys:
            push(scene, ob, keys)


_OWNER = object()
SUBSCRIBED = ((bpy.types.Camera, "clip_start"), (bpy.types.Camera, "clip_end"), (bpy.types.Camera, "lens"),
              (bpy.types.Camera, "sensor_width"), (bpy.types.Camera, "ortho_scale"),
              (bpy.types.Object, "location"), (bpy.types.Object, "rotation_euler"),
              (bpy.types.Object, "rotation_quaternion"), (bpy.types.Object, "matrix_world"))


def _for_scenes(fn):
    try:
        for scene in bpy.data.scenes:
            fn(scene)
    except (ReferenceError, RuntimeError, AttributeError):
        pass


def _on_edit(*_args):
    _for_scenes(check)


@persistent       # undo / redo handlers: kept when a file loads
def _on_undo(*_args):
    _for_scenes(after_undo)


@persistent
def _on_redo(*_args):
    _for_scenes(lambda scene: after_undo(scene, redo=True))


def _subscribe():
    bpy.msgbus.clear_by_owner(_OWNER)
    for key in SUBSCRIBED:
        bpy.msgbus.subscribe_rna(key=key, owner=_OWNER, args=(), notify=_on_edit)


def _start():
    _remember_all()
    _subscribe()
    return None


@persistent
def _on_load(*_args):
    _start()      # a loaded file drops the subscriptions


def register():
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.handlers.undo_post.append(_on_undo)
    bpy.app.handlers.redo_post.append(_on_redo)
    bpy.app.timers.register(_start, first_interval=0.0)
    bpy.app.timers.register(_poll, first_interval=POLL, persistent=True)


def unregister():
    for handlers, fn in ((bpy.app.handlers.load_post, _on_load), (bpy.app.handlers.undo_post, _on_undo),
                         (bpy.app.handlers.redo_post, _on_redo)):
        if fn in handlers:
            handlers.remove(fn)
    for fn in (_start, _poll):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    bpy.msgbus.clear_by_owner(_OWNER)
    _seen.clear()
    _views.clear()
    _edits.clear()
