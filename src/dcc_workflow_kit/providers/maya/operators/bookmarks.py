# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Time Slider bookmarks as Blender timeline markers.

Maya hotkeys: Alt+T makes a Time Slider bookmark from the selected range (a dialog first), Alt+Shift+T makes
one at once, ' / ; go to the next / previous bookmark, Shift+| fits the playback range to the current bookmark,
Shift+" / Shift+: frame the next / previous one. Visualize > Time Slider Bookmarks > Edit edits the bookmark at the
current time, Show Bookmarks hides them on the Time Slider, Bookmark Manager lists them all (ui/bookmark_manager.py).

A Maya bookmark is a time range with a name and a colour; a Blender marker is one frame. The kit bookmark = a marker
at the range start that keeps its end and colour on the marker itself (``TimelineMarker.allset_end`` /
``allset_has_end`` / ``allset_color``, so renaming it keeps them). Like Maya, a new bookmark covers the selected Time
Slider range (``WindowManager.allset_time_range``), else the current frame. A marker without a kept end (one made by
Blender, or a file from an older kit version: its ends were the scene ID property ``allset_bookmarks``) ends one frame
before the next marker (or at the scene end).
"""

import random

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty, IntProperty, StringProperty

from .. import results
from .naming import next_number

ENDS = "allset_bookmarks"       # older files: scene ID property {marker name: end frame}

# Maya's bookmark colours (0-255); a Quick Create bookmark takes one at random, the Create dialog starts on the first.
PALETTE = ((204, 92, 92), (171, 60, 60), (217, 132, 72), (191, 102, 38), (191, 163, 77), (153, 122, 31),
           (158, 131, 95), (125, 98, 62), (71, 179, 107), (35, 140, 70), (67, 181, 191), (21, 130, 140),
           (71, 149, 204), (25, 107, 166), (145, 102, 204), (116, 71, 179), (196, 88, 142), (153, 67, 110))


def rgb(c):
    return tuple(v / 255 for v in c)


FIRST_COLOR = rgb(PALETTE[0])


def pick_color():
    return rgb(random.choice(PALETTE))


def markers(scene):
    return sorted(scene.timeline_markers, key=lambda m: m.frame)


def visible(context=None):
    """Visualize > Time Slider Bookmarks > Show Bookmarks (an add-on preference, on by default like Maya)."""
    from .. import preferences
    try:
        return bool(getattr(preferences.get(context), "show_time_slider_bookmarks", True))
    except (KeyError, AttributeError):
        return True


def shown(context):
    """The bookmarks the Time Slider draws: every one while Show Bookmarks is on, else none."""
    return markers(context.scene) if visible(context) else []


def next_name(scene):
    """``bookmark<N>`` one past the highest, gaps not filled like Maya's timeSliderBookmark nodes."""
    return f"bookmark{next_number('bookmark', {m.name for m in scene.timeline_markers})}"


def selected_range(context):
    """(start, end) of the Time Slider's Shift-drag range, or None (ui/time_slider)."""
    wm = context.window_manager
    if not getattr(wm, "allset_time_range_on", False):
        return None
    rng = getattr(wm, "allset_time_range", None)
    if rng is None:
        return None
    start, end = int(round(rng[0])), int(round(rng[1]))
    return (min(start, end), max(start, end))


def current_range(context):
    """Maya's range for a new or updated bookmark: the selected Time Slider range, else the current frame."""
    rng = selected_range(context)
    if rng is not None:
        return rng
    f = context.scene.frame_current
    return (f, f)


def bookmark_range(scene, marker):
    """(start, end) frames of the bookmark ``marker``."""
    if marker.allset_has_end:
        end = marker.allset_end_value
    else:
        end = (scene.get(ENDS) or {}).get(marker.name)
    if end is None:
        later = [m.frame for m in scene.timeline_markers if m.frame > marker.frame]
        end = (min(later) - 1) if later else scene.frame_end
    return marker.frame, max(int(end), marker.frame)


def set_range(marker, start, end):
    """Move the bookmark to [start, end] (swapped when start > end, like Maya)."""
    start, end = int(start), int(end)
    if start > end:
        start, end = end, start
    marker.frame = start
    marker.allset_end_value, marker.allset_has_end = end, True


def color(marker):
    return tuple(marker.allset_color)


def bookmark_at(scene, frame=None):
    """The bookmark whose range holds ``frame`` (default the current frame): the latest-starting one, or None."""
    frame = scene.frame_current if frame is None else frame
    inside = [m for m in markers(scene) if bookmark_range(scene, m)[0] <= frame <= bookmark_range(scene, m)[1]]
    return inside[-1] if inside else None


def current(scene, frame=None):
    """The bookmark containing ``frame`` (the last marker at or before it), or None."""
    frame = scene.frame_current if frame is None else frame
    before = [m for m in markers(scene) if m.frame <= frame]
    return before[-1] if before else None


def find(scene, name):
    return scene.timeline_markers.get(name) if name else None


def create(context, name="", start=None, end=None, colour=None):
    scene = context.scene
    a, b = current_range(context)
    start = a if start is None else start
    end = b if end is None else end
    marker = scene.timeline_markers.new(name or next_name(scene), frame=int(start))
    set_range(marker, start, end)
    marker.allset_color = pick_color() if colour is None else colour
    scene.frame_current = bookmark_range(scene, marker)[1]      # Maya: the time moves to the new bookmark's end
    return marker


def frame(scene, marker):
    """Playback range = the bookmark's range (Maya FrameTimeSliderBookmark); a current time outside it moves to its
    start."""
    start, end = bookmark_range(scene, marker)
    scene.use_preview_range = True
    scene.frame_preview_start, scene.frame_preview_end = start, end
    if not start <= scene.frame_current <= end:
        scene.frame_current = start
    return start, end


def frame_all(scene):
    """Playback range = the earliest bookmark start to the latest end (Maya Frame all bookmarks); False with none."""
    ranges = [bookmark_range(scene, m) for m in scene.timeline_markers]
    if not ranges:
        return False
    start, end = min(r[0] for r in ranges), max(r[1] for r in ranges)
    if end <= start:
        return False
    scene.use_preview_range = True
    scene.frame_preview_start, scene.frame_preview_end = start, end
    return True


def neighbour(scene, previous, t=None):
    """Maya's next / previous bookmark from the time ``t`` (default the current time): the first one starting after
    it (the last one starting before it), wrapping round to the first (last) one."""
    ms = markers(scene)
    if not ms:
        return None
    t = scene.frame_current if t is None else t
    if previous:
        before = [m for m in ms if m.frame < t]
        return before[-1] if before else ms[-1]
    return next((m for m in ms if m.frame > t), ms[0])


def _redraw(context):
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type in {'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'NLA_EDITOR', 'SEQUENCE_EDITOR', 'PROPERTIES'}:
                area.tag_redraw()


class _AtTime:
    """A bookmark action at a given frame instead of the current time (the Time Slider bookmark strip's right-click
    menu acts at the frame under the mouse, like Maya)."""
    at_frame: IntProperty(options={'SKIP_SAVE', 'HIDDEN'}, description="The frame to act at")
    use_at_frame: BoolProperty(options={'SKIP_SAVE', 'HIDDEN'},
                               description="Act at the given frame instead of the current time")

    def time(self, scene):
        return self.at_frame if self.use_at_frame else scene.frame_current


class _BookmarkFields:
    """Maya's Create / Edit bookmark dialog: name, colour, start and end."""
    name: StringProperty(name="Name", options={'SKIP_SAVE'})
    color: FloatVectorProperty(name="Color", subtype='COLOR', size=3, min=0.0, max=1.0, default=FIRST_COLOR,
                               options={'SKIP_SAVE'})
    start: IntProperty(name="Start", options={'SKIP_SAVE'})
    end: IntProperty(name="End", options={'SKIP_SAVE'})

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "name")
        layout.prop(self, "color")
        row = layout.row(align=True)
        row.prop(self, "start")
        row.prop(self, "end")


class ALLSET_OT_bookmark_create(_BookmarkFields, bpy.types.Operator):
    """Create a Time Slider bookmark (a timeline marker) at the selected range or the current time"""
    bl_idname = "allset.bookmark_create"
    bl_label = "Create Bookmark"
    bl_options = {'UNDO'}

    quick: BoolProperty(options={'SKIP_SAVE', 'HIDDEN'}, description="No dialog (Maya Quick Create)")

    def invoke(self, context, event):
        if self.quick:
            return self.execute(context)
        self.name = next_name(context.scene)
        self.start, self.end = current_range(context)
        return context.window_manager.invoke_props_dialog(self, title="Create Bookmark", confirm_text="Create")

    def execute(self, context):
        if self.quick:
            marker = create(context, self.name.strip())
        else:
            marker = create(context, self.name.strip(), self.start, self.end, tuple(self.color))
        _redraw(context)
        results.result(self, f"Bookmark {marker.name} at frame {marker.frame}")
        return {'FINISHED'}


class ALLSET_OT_bookmark_edit(_AtTime, _BookmarkFields, bpy.types.Operator):
    """Edit the Time Slider bookmark at the current time: its name, colour, start and end"""
    bl_idname = "allset.bookmark_edit"
    bl_label = "Edit Bookmark"
    bl_options = {'UNDO'}

    bookmark: StringProperty(options={'SKIP_SAVE', 'HIDDEN'}, description="The bookmark (default: the current one)")

    def _target(self, context):
        scene = context.scene
        return find(scene, self.bookmark) if self.bookmark else bookmark_at(scene, self.time(scene))

    def invoke(self, context, event):
        marker = self._target(context)
        if marker is None:
            self.report({'WARNING'}, "There is no bookmark to edit at the current time")
            return {'CANCELLED'}
        self.bookmark = marker.name
        self.name = marker.name
        self.color = color(marker)
        self.start, self.end = bookmark_range(context.scene, marker)
        return context.window_manager.invoke_props_dialog(self, title="Edit Bookmark", confirm_text="Edit")

    def execute(self, context):
        marker = self._target(context)
        if marker is None:
            self.report({'WARNING'}, "There is no bookmark to edit at the current time")
            return {'CANCELLED'}
        set_range(marker, self.start, self.end)
        marker.allset_color = tuple(self.color)
        if self.name.strip() and self.name.strip() != marker.name:
            marker.name = self.name.strip()
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_bookmark_update(_AtTime, bpy.types.Operator):
    """Set a Time Slider bookmark's start and end to the selected Time Slider range (else the current frame)"""
    bl_idname = "allset.bookmark_update"
    bl_label = "Update Bookmark with Selection"
    bl_options = {'UNDO'}

    bookmark: StringProperty(options={'SKIP_SAVE', 'HIDDEN'}, description="The bookmark (default: the current one)")

    def execute(self, context):
        scene = context.scene
        marker = find(scene, self.bookmark) if self.bookmark else bookmark_at(scene, self.time(scene))
        if marker is None:
            return {'CANCELLED'}
        set_range(marker, *current_range(context))
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_bookmark_frame(_AtTime, bpy.types.Operator):
    """Set the playback range to a Time Slider bookmark's range (this one, the next or the previous)"""
    bl_idname = "allset.bookmark_frame"
    bl_label = "Frame Bookmark"
    bl_options = {'UNDO'}

    which: EnumProperty(items=(("CURRENT", "Current", ""), ("NEXT", "Next", ""), ("PREVIOUS", "Previous", ""),
                               ("ALL", "All", "")),
                        options={'SKIP_SAVE'})
    bookmark: StringProperty(options={'SKIP_SAVE', 'HIDDEN'}, description="This bookmark (Bookmark Manager row)")

    def execute(self, context):
        scene = context.scene
        if not scene.timeline_markers:
            self.report({'WARNING'}, "There is no bookmark to frame")
            return {'CANCELLED'}
        if self.which == "ALL":
            ok = frame_all(scene)
            _redraw(context)
            return {'FINISHED'} if ok else {'CANCELLED'}
        if self.bookmark:
            target = find(scene, self.bookmark)
        elif self.which == "CURRENT":
            target = bookmark_at(scene, self.time(scene))
        else:
            target = neighbour(scene, self.which == "PREVIOUS", self.time(scene))
        if target is None:
            self.report({'WARNING'}, "There is no bookmark to frame at the current time")
            return {'CANCELLED'}
        frame(scene, target)
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_bookmark_go(_AtTime, bpy.types.Operator):
    """Move the current time to the start of the next or previous Time Slider bookmark (wrapping round, like Maya)"""
    bl_idname = "allset.bookmark_go"
    bl_label = "Next / Previous Bookmark"
    bl_options = {'UNDO_GROUPED'}
    bl_undo_group = "Frames"          # like Blender's own frame jumps

    previous: BoolProperty(name="Previous", options={'SKIP_SAVE'},
                           description="The previous bookmark instead of the next one")

    def execute(self, context):
        scene = context.scene
        target = neighbour(scene, self.previous, self.time(scene))
        if target is None:
            self.report({'WARNING'}, "There is no bookmark")
            return {'CANCELLED'}
        scene.frame_current = target.frame
        _redraw(context)
        return {'FINISHED'}


def delete(scene, targets):
    """Remove bookmark markers (and an older file's kept range ends); the number removed."""
    ends = dict(scene.get(ENDS) or {})
    for m in targets:
        ends.pop(m.name, None)
        scene.timeline_markers.remove(m)
    if ENDS in scene:
        scene[ENDS] = ends
    return len(targets)


class ALLSET_OT_bookmark_delete(_AtTime, bpy.types.Operator):
    """Delete the Time Slider bookmark at the current time, or every bookmark (Maya Delete / Delete All Bookmarks)"""
    bl_idname = "allset.bookmark_delete"
    bl_label = "Delete Bookmark"
    bl_options = {'UNDO'}

    all: BoolProperty(options={'SKIP_SAVE'}, description="Every bookmark (Maya Delete All Bookmarks)")
    bookmark: StringProperty(options={'SKIP_SAVE', 'HIDDEN'}, description="This bookmark (Bookmark Manager row)")

    def execute(self, context):
        scene = context.scene
        if self.all:
            targets = list(scene.timeline_markers)
        elif self.bookmark:
            targets = [m for m in [find(scene, self.bookmark)] if m is not None]
        else:
            cur = bookmark_at(scene, self.time(scene))
            targets = [cur] if cur is not None else []
        n = delete(scene, targets)
        if not n:
            self.report({'WARNING'}, "No bookmark at the current time")
            return {'CANCELLED'}
        _redraw(context)
        results.result(self, f"{n} bookmark(s) deleted")
        return {'FINISHED'}


classes = (ALLSET_OT_bookmark_create, ALLSET_OT_bookmark_edit, ALLSET_OT_bookmark_update, ALLSET_OT_bookmark_frame,
           ALLSET_OT_bookmark_go, ALLSET_OT_bookmark_delete)

_MARKER_PROPS = ("allset_end", "allset_end_value", "allset_has_end", "allset_color")


def _tag(self, context):
    _redraw(context)


def _get_end(marker):
    return bookmark_range(marker.id_data, marker)[1]


def _set_end(marker, value):
    """The Bookmark Manager's End field: keep the end (an end before the start swaps them, like Maya)."""
    set_range(marker, marker.frame, value)
    _redraw(bpy.context)


def register_props():
    bpy.types.TimelineMarker.allset_end_value = IntProperty(options={'HIDDEN'})
    bpy.types.TimelineMarker.allset_has_end = BoolProperty(options={'HIDDEN'})
    bpy.types.TimelineMarker.allset_end = IntProperty(name="End", description="Last frame of this Time Slider bookmark",
                                                      get=_get_end, set=_set_end)
    bpy.types.TimelineMarker.allset_color = FloatVectorProperty(
        name="Color", description="Colour of this Time Slider bookmark", subtype='COLOR', size=3, min=0.0, max=1.0,
        default=FIRST_COLOR, update=_tag)


def unregister_props():
    for name in _MARKER_PROPS:
        if hasattr(bpy.types.TimelineMarker, name):
            delattr(bpy.types.TimelineMarker, name)
