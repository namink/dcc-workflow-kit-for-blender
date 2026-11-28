# SPDX-License-Identifier: GPL-3.0-or-later
"""View-change undo / redo (Maya [ and ]), apart from scene undo: a persistent timer (``poll_views``, started by
``register_timer``) keeps a ``ViewHistory`` of settled views per 3D view; ``allset.view_history`` steps back /
forward. ``unregister_timer`` stops it and forgets the histories.
"""

import bpy

from .. import results

# --- view history ---------------------------------------------------------------

_DIGITS = 5


def capture(rv3d):
    """Comparable snapshot of a RegionView3D's view."""
    r = lambda v: round(v, _DIGITS)  # noqa: E731
    return (tuple(map(r, rv3d.view_location)), tuple(map(r, rv3d.view_rotation)),
            r(rv3d.view_distance), rv3d.view_perspective,
            r(rv3d.view_camera_zoom), tuple(map(r, rv3d.view_camera_offset)))


def restore(rv3d, state):
    loc, rot, dist, persp, cam_zoom, cam_offset = state
    rv3d.view_perspective = persp
    rv3d.view_location = loc
    rv3d.view_rotation = rot
    rv3d.view_distance = dist
    rv3d.view_camera_zoom = cam_zoom
    rv3d.view_camera_offset = cam_offset


class ViewHistory:
    """Undo/redo stack of settled view states for one RegionView3D.

    ``observe`` is called periodically with the current state. A change is
    recorded once the view has stayed the same for one more observation
    (navigation or smooth-view animation finished).
    """

    def __init__(self, limit=50):
        self.limit = limit
        self.undo = []
        self.redo = []
        self.stable = None
        self.pending = None

    def _push(self, state):
        self.undo.append(state)
        del self.undo[:-self.limit]
        self.redo.clear()

    def observe(self, state):
        if self.stable is None or state == self.stable:
            self.stable = state
            self.pending = None
            return
        if state != self.pending:
            self.pending = state  # still moving
            return
        self._push(self.stable)
        self.stable = state
        self.pending = None

    def step_back(self, current):
        """State to show for "undo view change", or None."""
        if self.stable is None:  # never observed: nothing to go back to
            self.stable = current
            return None
        if current != self.stable:  # a change not settled/observed yet
            self._push(self.stable)
            self.stable = current
        if not self.undo:
            return None
        self.redo.append(current)
        self.stable = self.undo.pop()
        self.pending = None
        return self.stable

    def step_forward(self, current):
        """State to show for "redo view change", or None."""
        if self.stable is None:
            self.stable = current
            return None
        if current != self.stable:
            self.redo.clear()  # the view moved since the undo: redo is void
            self.observe(current)
            return None
        if not self.redo:
            return None
        self.undo.append(current)
        self.stable = self.redo.pop()
        self.pending = None
        return self.stable


_histories = {}
POLL_INTERVAL = 0.25


def history_for(rv3d):
    key = rv3d.as_pointer()
    h = _histories.get(key)
    if h is None:
        h = _histories[key] = ViewHistory()
    return h


def _all_rv3d():
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            space = area.spaces.active
            yield space.region_3d
            yield from space.region_quadviews


def poll_views():
    """Timer: observe every 3D view; forget views that no longer exist."""
    seen = set()
    for rv3d in _all_rv3d():
        if rv3d is None:
            continue
        seen.add(rv3d.as_pointer())
        history_for(rv3d).observe(capture(rv3d))
    for key in list(_histories):
        if key not in seen:
            del _histories[key]
    return POLL_INTERVAL


class ALLSET_OT_view_history(bpy.types.Operator):
    """Undo or redo a view change (Maya [ and ]); separate from scene undo"""
    bl_idname = "allset.view_history"
    bl_label = "Undo/Redo View Change"

    direction: bpy.props.EnumProperty(items=(("UNDO", "Undo", ""), ("REDO", "Redo", "")))

    @classmethod
    def poll(cls, context):
        return context.region_data is not None

    def execute(self, context):
        rv3d = context.region_data
        h = history_for(rv3d)
        cur = capture(rv3d)
        state = h.step_back(cur) if self.direction == "UNDO" else h.step_forward(cur)
        if state is None:
            results.result(self, "No more view changes")
            return {'CANCELLED'}
        restore(rv3d, state)
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


def register_timer():
    if not bpy.app.timers.is_registered(poll_views):
        bpy.app.timers.register(poll_views, first_interval=POLL_INTERVAL, persistent=True)


def unregister_timer():
    if bpy.app.timers.is_registered(poll_views):
        bpy.app.timers.unregister(poll_views)
    _histories.clear()
