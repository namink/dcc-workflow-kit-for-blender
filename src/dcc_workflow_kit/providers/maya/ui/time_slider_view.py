# SPDX-License-Identifier: GPL-3.0-or-later
"""The Timeline view kept on the playback range like Maya's Time Slider (``fit_timelines``; ``_check_view`` from the
draw handler and ``_schedule`` from a msgbus subscription re-fit a view that drifted; ``allset.time_view_lock`` swallows
wheel / Ctrl+MMB zoom). ``playback_range`` = the preview range while it is on, else the scene range; it and
``_is_timeline`` are shared by the other time_slider_* modules. Registered by ``time_slider``.
"""

import bpy


def _is_timeline(context):
    space = getattr(context, "space_data", None)
    return space is not None and getattr(space, "mode", None) == 'TIMELINE'


_OWNER = object()
_RANGE_PROPS = ("frame_start", "frame_end", "frame_preview_start", "frame_preview_end",
                "use_preview_range")


def playback_range(scene):
    """Maya playback range = the preview range when on, else the scene range (module docstring)."""
    if scene.use_preview_range:
        return scene.frame_preview_start, scene.frame_preview_end
    return scene.frame_start, scene.frame_end


# --- timeline view = playback range -------------------------------------------------------

def timeline_areas(wm):
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == 'DOPESHEET_EDITOR' and area.spaces.active.mode == 'TIMELINE':
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                if region is not None:
                    yield win, area, region


VIEW_TOL_PX = 0.75          # a view this close to the last fit is left alone
_fitted = {}                # area pointer -> (target lo, hi, achieved lo, hi, region width, height)


def view_target(scene):
    """The frame span a Maya Time Slider shows: the playback range's frame cells (f - 0.5 .. f + 0.5)."""
    a, b = playback_range(scene)
    return a - 0.5, b + 0.5


def visible_range(region):
    v = region.view2d
    return v.region_to_view(0, 0)[0], v.region_to_view(region.width, 0)[0]


def fit_timeline(win, area, region, scene):
    """Frame ``region`` (a Timeline WINDOW) to the playback range exactly; Blender's Frame Scene Range when the
    region has no size yet. Records what was reached so ``_check_view`` only acts on a view that moved."""
    lo, hi = view_target(scene)
    done = False
    gui = not bpy.app.background
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
        if gui and region.width >= 4 and bpy.ops.view2d.zoom_border.poll():
            v = region.view2d
            x0 = v.view_to_region(lo, 0, clip=False)[0]
            x1 = v.view_to_region(hi, 0, clip=False)[0]
            if x1 - x0 < 2 and bpy.ops.anim.scene_range_frame.poll():
                # zoomed out so far that the range is under two pixels: bring it near first, then frame it exactly
                bpy.ops.anim.scene_range_frame()
                x0 = v.view_to_region(lo, 0, clip=False)[0]
                x1 = v.view_to_region(hi, 0, clip=False)[0]
            if x1 - x0 >= 2:
                bpy.ops.view2d.zoom_border(xmin=int(round(x0)), xmax=int(round(x1)), ymin=0, ymax=region.height,
                                           wait_for_input=False, zoom_out=False)
                done = True
        if not done and bpy.ops.anim.scene_range_frame.poll():
            bpy.ops.anim.scene_range_frame()
            done = True
    got = visible_range(region) if gui else (lo, hi)
    _fitted[area.as_pointer()] = (lo, hi, got[0], got[1], region.width, region.height)
    return done


def fit_timelines():
    wm = bpy.context.window_manager
    n = 0
    for win, area, region in list(timeline_areas(wm)):
        if fit_timeline(win, area, region, win.scene):
            n += 1
    return n


def view_drifted(rec, target, cur, size, tol_px=VIEW_TOL_PX):
    """True when a Timeline whose last fit is ``rec`` (see _fitted) must be fitted again: no fit yet, another
    playback range or region size, or a view that moved from what the fit reached by more than ``tol_px``."""
    if rec is None or (rec[0], rec[1]) != tuple(target) or (rec[4], rec[5]) != tuple(size):
        return True
    ppf = size[0] / max(target[1] - target[0], 1e-6)
    return abs(cur[0] - rec[2]) * ppf > tol_px or abs(cur[1] - rec[3]) * ppf > tol_px


def _check_view(context, region):
    """Timeline WINDOW draw: schedule a fit when the view no longer shows the playback range (Blender's
    zoom / scroll / Frame All, a resize, a new window)."""
    area = context.area
    if area is None or region is None or region.width < 4:
        return
    try:
        if view_drifted(_fitted.get(area.as_pointer()), view_target(context.scene), visible_range(region),
                        (region.width, region.height)):
            _schedule()
    except Exception:
        pass


def _deferred_fit():
    try:
        fit_timelines()
    except Exception:   # never break file loading / editing over a view nicety
        import traceback
        traceback.print_exc()
    return None


def _schedule():
    if not bpy.app.timers.is_registered(_deferred_fit):
        bpy.app.timers.register(_deferred_fit, first_interval=0.0)


def _subscribe():
    bpy.msgbus.clear_by_owner(_OWNER)
    for prop in _RANGE_PROPS:
        bpy.msgbus.subscribe_rna(key=(bpy.types.Scene, prop), owner=_OWNER, args=(), notify=_schedule)


class ALLSET_OT_time_view_lock(bpy.types.Operator):
    """Maya's Time Slider shows the playback range and does not zoom or scroll: change the range with the
    Range Slider"""
    bl_idname = "allset.time_view_lock"
    bl_label = "Time Slider View"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if not _is_timeline(context):
            return {'PASS_THROUGH'}
        return {'FINISHED'}
