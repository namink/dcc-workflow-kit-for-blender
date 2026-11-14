# SPDX-License-Identifier: GPL-3.0-or-later
"""A placed component pivot moves with the components, like Maya's (Pin Component Pivot off).

Maya: once the component pivot was placed (D / Insert), dragging the components with the Move manipulator moves the
pivot by the same vector, with soft selection too; Rotate and Scale turn and scale them about it and it stays; a typed
move leaves it; Undo / Redo take it back and forward together with the move. With Pin Component Pivot on it stays
where it is.

The kit's component pivot is the 3D cursor (``hold.ComponentPivotEdit``). Blender's transform tells no one when it
ends and its undo never restores the cursor, so:

- a snapshot keeps up to ``SAMPLES`` selected vertices (world positions) and the newest registered operator; the
  samples are picked (a pass over every vertex) only for a new selection or after an Undo / Redo, and read again
  only after a new operator or a geometry update, so heavy meshes pay little while a pivot is placed;
- ``update`` (the component timer, and a 0 s timer the manipulator asks for once a move ended) moves the cursor when a
  newer registered move operator is there and every sample moved by the same vector, then takes a new snapshot;
- ``pending`` gives that vector while the move runs, so the manipulator is drawn with the components;
- each followed move is kept with the sample positions before and after it: an Undo that lands on the positions before
  it takes the cursor back, a Redo that lands on the positions after it brings it forward again. Anything else leaves
  the cursor where it is.
"""

import bpy
from bpy.app.handlers import persistent

SAMPLES = 64          # selected vertices compared (spread over the selection)
EPS = 1e-6            # smallest offset that counts as a move
SAME = 1e-5           # samples moved by the same vector within this
MOVE_OPS = frozenset({"TRANSFORM_OT_translate", "ALLSET_OT_live_translate"})
JOURNAL = 256         # followed moves kept for Undo (Blender's largest undo depth)
_LATEST = object()    # update / pending: read the operators from the window manager

# newest registered operator, [(object, vertex, world co)], selection signature, geometry update count at the time
_snap = {"key": None, "points": None, "sig": None, "geom": 0}
_geom = [0]           # geometry updates the depsgraph reported while a pivot is placed (no update = nothing to read)
_pend = {"tag": None, "value": None}   # pending(): one read per drawn frame (the manipulator asks several times)
_undo = []            # followed moves, newest last: (sample ids, positions before, positions after, offset)
_redo = []


def active(context):
    """The placed component pivot follows the components now."""
    from . import hold
    from .pivot_menu import option
    try:
        return (context.mode == hold.EDIT_MODE and hold.COMPONENT.custom and not hold.COMPONENT.on
                and context.scene.tool_settings.transform_pivot_point == 'CURSOR' and not option("PIN", context))
    except (AttributeError, ReferenceError):
        return False


def _op_key(context):
    try:
        ops = context.window_manager.operators
        if not len(ops):
            return None
        op = ops[-1]
        return (op.as_pointer(), len(ops), op.bl_idname)
    except (AttributeError, ReferenceError):
        return None


def _running(context):
    """bl_idname of a transform running in any window, or None."""
    from .manip_scale import TRANSFORM_MODALS
    try:
        for window in context.window_manager.windows:
            for op in window.modal_operators:
                if op.bl_idname.startswith(TRANSFORM_MODALS):
                    return op.bl_idname
    except (AttributeError, ReferenceError):
        pass
    return None


def _edit_meshes(context):
    obs = getattr(context, "objects_in_mode_unique_data", None)
    if obs is None:
        layer = getattr(context, "view_layer", None)
        obs = [ob for ob in layer.objects if ob.mode == 'EDIT'] if layer is not None else []
    return [ob for ob in obs if ob.type == 'MESH' and ob.data.is_editmode]


def _sample(context):
    """Up to SAMPLES selected, visible vertices of the meshes in edit mode: (object name, index, world position)."""
    import bmesh
    found = []
    for ob in _edit_meshes(context):
        mw = ob.matrix_world
        found += [(ob.name, i, mw @ v.co) for i, v in enumerate(bmesh.from_edit_mesh(ob.data).verts)
                  if v.select and not v.hide]
    step = max(1, len(found) // SAMPLES)
    return found[::step][:SAMPLES]


def _read(ids, selected=False):
    """World positions of the vertices ``ids`` ((object name, index) ...) now, or None when one is gone (or, with
    ``selected``, no longer selected)."""
    import bmesh
    out, meshes = [], {}
    for name, index in ids:
        got = meshes.get(name)
        if got is None:
            ob = bpy.data.objects.get(name)
            if ob is None or ob.type != 'MESH' or not ob.data.is_editmode:
                return None
            verts = bmesh.from_edit_mesh(ob.data).verts
            verts.ensure_lookup_table()
            got = meshes[name] = (verts, ob.matrix_world.copy())
        verts, mw = got
        if index >= len(verts):
            return None
        vert = verts[index]
        if selected and not vert.select:
            return None
        out.append(mw @ vert.co)
    return out


def together(before, after):
    """The vector every point moved by, or None when they moved apart (turned, scaled, slid, ...)."""
    if not before or after is None or len(before) != len(after):
        return None
    d = after[0] - before[0]
    for a, b in zip(before, after):
        if ((b - a) - d).length > SAME:
            return None
    return d


def _ids(points):
    return [(name, index) for name, index, _co in points]


def _same(a, b):
    return a is not None and b is not None and len(a) == len(b) and all((p - q).length <= SAME for p, q in zip(a, b))


def snapshot(context):
    """Remember the selection's sample positions and the newest registered operator (follows nothing). Picks the
    samples anew: a pass over every vertex, so only when the selection is new (or after an Undo / Redo)."""
    from . import hold
    _pend.update(tag=None, value=None)
    try:
        if active(context):
            _snap.update(key=_op_key(context), points=_sample(context), sig=hold.selection_signature(context),
                         geom=_geom[0])
        else:
            _snap.update(key=None, points=None, sig=None)
    except (AttributeError, ReferenceError):
        _snap.update(key=None, points=None, sig=None)


def _refresh(points, now, key):
    """The same samples at their positions ``now`` (the selection didn't change: no pass over every vertex)."""
    _pend.update(tag=None, value=None)
    _snap.update(key=key, points=[(name, index, co) for (name, index, _old), co in zip(points, now)], geom=_geom[0])


def clear():
    _snap.update(key=None, points=None, sig=None)
    _pend.update(tag=None, value=None)
    _undo.clear()
    _redo.clear()


def journal_size():
    return len(_undo)


def _moved(op):
    """The vector the samples moved by since the snapshot when ``op`` (a bl_idname) is a move, else None."""
    points = _snap["points"]
    if not points or op not in MOVE_OPS:
        return None
    d = together([co for _n, _i, co in points], _read(_ids(points)))
    return d if d is not None and d.length > EPS else None


def pending(context, running=_LATEST):
    """The components' offset the pivot has not followed yet: the move ``running`` (bl_idname; default = the transform
    running in a window), or a finished move the timer has not taken yet (it is asked to, at once). None = none."""
    if not active(context) or not _snap["points"]:
        return None
    if running is _LATEST:
        running = _running(context)
        if running is None:
            key = _op_key(context)
            if key is None or key == _snap["key"]:
                return None
            d = _cached(("op", key, _geom[0]), key[2])
            if d is not None:
                request()
            return d
        return _cached(("run", running, _geom[0]), running)
    return _moved(running)


def _cached(tag, op):
    """``_moved(op)``, read once per geometry update (the manipulator draws several times a frame)."""
    if _pend["tag"] != tag:
        _pend.update(tag=tag, value=_moved(op))
    return _pend["value"]


def update(context, newest=_LATEST):
    """Follow a finished move. ``newest`` = bl_idname of the operator registered since the snapshot (default: read
    from the window manager; None = none). Returns the vector the pivot moved by, or None."""
    if not active(context):
        if _snap["points"] is not None or _undo or _redo:
            clear()
        return None
    if newest is _LATEST:
        if _running(context) is not None:
            return None
        key = _op_key(context)
        newest = key[2] if key is not None and key != _snap["key"] else None
    else:
        key = _op_key(context)
    from . import hold
    points = _snap["points"]
    if points is None or _snap["sig"] != hold.selection_signature(context):
        snapshot(context)
        return None
    if newest is None and key == _snap["key"] and _geom[0] == _snap["geom"]:
        return None              # no operator, no geometry update: nothing can have moved
    before = [co for _n, _i, co in points]
    now = _read(_ids(points))
    if now is None:              # a sampled vertex is gone: sample the selection again
        snapshot(context)
        return None
    d = together(before, now) if newest in MOVE_OPS else None
    if d is not None and d.length <= EPS:
        d = None
    if d is not None:
        cursor = context.scene.cursor
        cursor.location = cursor.location + d
        _undo.append((_ids(points), before, now, d.copy()))
        del _undo[:-JOURNAL]
        _redo.clear()
        hold._redraw()
    _refresh(points, now, key)   # a typed change, a turn or a scale counts from here on
    return d


def _step(context, undo):
    """After an Undo / Redo: the cursor goes back / forward with the followed move the components went back /
    forward to."""
    if not active(context):
        return
    src, dst = (_undo, _redo) if undo else (_redo, _undo)
    if src:
        ids, before, after, d = src[-1]
        if _same(_read(ids), before if undo else after):
            cursor = context.scene.cursor
            cursor.location = cursor.location - d if undo else cursor.location + d
            dst.append(src.pop())
            from . import hold
            hold._redraw()
    from . import hold
    points = _snap["points"]
    now = _read(_ids(points), selected=True) if points else None
    if now is not None and _snap["sig"] == hold.selection_signature(context):
        _refresh(points, now, _op_key(context))     # the same samples, still selected: no pass over every vertex
    else:
        snapshot(context)


@persistent
def _on_undo_post(*_args):
    try:
        _step(bpy.context, True)
    except (AttributeError, ReferenceError, RuntimeError):
        pass


@persistent
def _on_redo_post(*_args):
    try:
        _step(bpy.context, False)
    except (AttributeError, ReferenceError, RuntimeError):
        pass


@persistent
def _on_depsgraph(_scene, depsgraph):
    if _snap["points"] is None:
        return
    try:
        for change in depsgraph.updates:
            if change.is_updated_geometry:
                _geom[0] += 1
                return
    except (AttributeError, ReferenceError):
        pass


@persistent
def _on_load_pre(*_args):
    """File > Open / New / Revert: the pivot edit and the placed pivot stay with the file they were made in."""
    from . import hold
    hold.forget_component()
    if bpy.app.timers.is_registered(_apply_now):
        bpy.app.timers.unregister(_apply_now)
    clear()


@persistent
def _on_load(*_args):
    clear()


def _apply_now():
    try:
        update(bpy.context)
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    return None


def request():
    """Follow a finished move at once (a 0 s timer: the manipulator asks while drawing)."""
    if not bpy.app.timers.is_registered(_apply_now):
        bpy.app.timers.register(_apply_now, first_interval=0.0)


HANDLERS = (("undo_post", _on_undo_post), ("redo_post", _on_redo_post), ("load_pre", _on_load_pre),
            ("load_post", _on_load), ("depsgraph_update_post", _on_depsgraph))


def register_handlers():
    for name, fn in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn not in handlers:
            handlers.append(fn)


def unregister_handlers():
    for name, fn in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn in handlers:
            handlers.remove(fn)
    if bpy.app.timers.is_registered(_apply_now):
        bpy.app.timers.unregister(_apply_now)
    clear()
