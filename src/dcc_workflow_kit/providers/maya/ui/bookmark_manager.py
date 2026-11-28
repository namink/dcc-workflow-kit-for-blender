# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's Bookmark Manager (Visualize > Time Slider Bookmarks > Bookmark Manager): a floating kit window
(``marked_window`` kind ``BOOKMARK_MANAGER``) listing every Time Slider bookmark.

Like Maya: a top bar (Frame Previous / Frame / Frame Next, Show Bookmarks, Frame all bookmarks, Delete All), one row
per bookmark in start order (colour, name, start, end edited in place; Update with the selected range, Frame, Delete),
and a line that adds a bookmark (an empty Start / End = the selected Time Slider range, else the current frame).
The rows edit the timeline markers themselves (``operators/bookmarks.py``): the scene keeps the values and their undo.
"""

import bpy
from bpy.props import FloatVectorProperty, StringProperty

from .. import results
from ..operators import bookmarks
from . import marked_window

KIND = "BOOKMARK_MANAGER"
MARK = ("show_properties_view_layer", "show_properties_material")      # marked_window.KINDS
PLACE = f"marked:{KIND}"
WINDOW_PX = (560, 300)         # first-open size at UI scale 1
WINDOW_MARGIN_PX = 60

_WM_PROPS = ("allset_bm_new_name", "allset_bm_new_color", "allset_bm_new_start", "allset_bm_new_end")


def rows(scene):
    """The bookmarks in the Manager's order: by start, then end."""
    return sorted(scene.timeline_markers, key=lambda m: bookmarks.bookmark_range(scene, m))


def _frame_text(text):
    text = text.strip()
    if not text:
        return None
    try:
        return int(round(float(text)))
    except ValueError:
        return False


def first_place(context):
    """The window's first rect (screen px): small, at the top left of the largest area; later opens reuse the place
    it was left at (``ui/window_places``)."""
    window = context.window
    area = max(window.screen.areas, key=lambda a: a.width * a.height, default=None)
    if area is None:
        return None
    scale = context.preferences.system.ui_scale or 1.0
    w, h = int(WINDOW_PX[0] * scale), int(WINDOW_PX[1] * scale)
    return (window.x + area.x + WINDOW_MARGIN_PX, window.y + area.y + area.height - h - WINDOW_MARGIN_PX, w, h)


class ALLSET_OT_bookmark_manager(bpy.types.Operator):
    """Open the Bookmark Manager: every Time Slider bookmark to rename, recolour, retime, frame or delete"""
    bl_idname = "allset.bookmark_manager"
    bl_label = "Bookmark Manager"

    def execute(self, context):
        from . import window_places
        if context.window is None:
            return {'CANCELLED'}
        if window_places.place(PLACE) is None:
            rect = first_place(context)
            if rect is not None:
                window_places.remember(PLACE, rect)
        if marked_window.open_window(context, KIND) is None:
            if not window_places.deferred():     # opens on a later tick
                self.report({'ERROR'}, "Could not open the Bookmark Manager window")
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_bookmark_add_line(bpy.types.Operator):
    """Add a Time Slider bookmark from this line: its colour and name, Start / End (empty = the selected Time Slider
    range, else the current frame)"""
    bl_idname = "allset.bookmark_add_line"
    bl_label = "Add"
    bl_options = {'UNDO'}

    def execute(self, context):
        wm = context.window_manager
        start, end = _frame_text(wm.allset_bm_new_start), _frame_text(wm.allset_bm_new_end)
        if start is False or end is False:
            self.report({'WARNING'}, "Start and End must be frame numbers")
            return {'CANCELLED'}
        marker = bookmarks.create(context, wm.allset_bm_new_name.strip(), start, end, tuple(wm.allset_bm_new_color))
        wm.allset_bm_new_color = bookmarks.pick_color()           # the next line starts on another colour, like Maya
        bookmarks._redraw(context)
        results.result(self, f"Bookmark {marker.name} at frame {marker.frame}")
        return {'FINISHED'}


def _op(layout, idname, icon, **props):
    op = layout.operator(idname, text="", icon=icon)
    for k, v in props.items():
        setattr(op, k, v)
    return op


def draw(layout, context):
    from .. import preferences
    scene = context.scene
    top = layout.row(align=False)
    left = top.row(align=False)
    nav = left.row(align=True)
    _op(nav, "allset.bookmark_frame", 'TRIA_LEFT', which='PREVIOUS')
    _op(nav, "allset.bookmark_frame", 'PREVIEW_RANGE', which='CURRENT')
    _op(nav, "allset.bookmark_frame", 'TRIA_RIGHT', which='NEXT')
    prefs = preferences.get(context)
    on = prefs.show_time_slider_bookmarks
    left.prop(prefs, "show_time_slider_bookmarks", text="", icon='HIDE_OFF' if on else 'HIDE_ON', toggle=True)
    end = top.row(align=True)
    end.alignment = 'RIGHT'
    _op(end, "allset.bookmark_frame", 'FULLSCREEN_ENTER', which='ALL')
    _op(end, "allset.bookmark_delete", 'TRASH', all=True)
    layout.separator()
    col = layout.column(align=True)
    for m in rows(scene):
        row = col.row(align=True)
        sw = row.row(align=True)
        sw.ui_units_x = 1.5
        sw.prop(m, "allset_color", text="")
        row.prop(m, "name", text="")
        se = row.row(align=True)
        se.ui_units_x = 6
        se.prop(m, "frame", text="")
        se.prop(m, "allset_end", text="")
        _op(row, "allset.bookmark_update", 'FILE_REFRESH', bookmark=m.name)
        _op(row, "allset.bookmark_frame", 'PREVIEW_RANGE', bookmark=m.name)
        _op(row, "allset.bookmark_delete", 'X', bookmark=m.name)
    if not scene.timeline_markers:
        col.label(text="No bookmarks")
    layout.separator()
    wm = context.window_manager
    row = layout.row(align=True)
    sw = row.row(align=True)
    sw.ui_units_x = 1.5
    sw.prop(wm, "allset_bm_new_color", text="")
    row.prop(wm, "allset_bm_new_name", text="", placeholder="Name")
    se = row.row(align=True)
    se.ui_units_x = 6
    se.prop(wm, "allset_bm_new_start", text="", placeholder="Start")
    se.prop(wm, "allset_bm_new_end", text="", placeholder="End")
    add = row.row(align=True)
    add.ui_units_x = 3.5            # under the rows' Update / Frame / Delete buttons
    add.operator(ALLSET_OT_bookmark_add_line.bl_idname, text="Add")


class ALLSET_PT_bookmark_manager(bpy.types.Panel):
    bl_idname = "ALLSET_PT_bookmark_manager"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"            # = drawn by the Properties Tool tab
    bl_label = "Bookmark Manager"
    bl_options = {'HIDE_HEADER'}
    bl_order = -300

    @classmethod
    def poll(cls, context):
        return marked_window.context_kind(context) == KIND

    def draw(self, context):
        draw(self.layout, context)


classes = (ALLSET_OT_bookmark_manager, ALLSET_OT_bookmark_add_line, ALLSET_PT_bookmark_manager)


def register():
    from . import window_places
    for cls in classes:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.allset_bm_new_name = StringProperty(name="Name", options={'SKIP_SAVE'})
    wm.allset_bm_new_color = FloatVectorProperty(name="Color", subtype='COLOR', size=3, min=0.0, max=1.0,
                                                 default=bookmarks.FIRST_COLOR, options={'SKIP_SAVE'})
    wm.allset_bm_new_start = StringProperty(name="Start", options={'SKIP_SAVE'},
                                            description="First frame (empty: the selected range or the current frame)")
    wm.allset_bm_new_end = StringProperty(name="End", options={'SKIP_SAVE'},
                                          description="Last frame (empty: the selected range or the current frame)")
    marked_window.KINDS[KIND] = MARK
    window_places.STRICT.add(PLACE)


def unregister():
    from . import window_places
    marked_window.KINDS.pop(KIND, None)
    window_places.STRICT.discard(PLACE)
    for name in _WM_PROPS:
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
