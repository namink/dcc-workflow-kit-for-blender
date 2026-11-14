# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Time Slider + Range Slider in the Timeline header, and a timeline view that
follows the playback range.

Maya's Time Slider (transport buttons, current time
field, auto key) and Range Slider (animation start, playback start, [range], playback end,
animation end). Blender form:
- the timeline header's ``draw_header`` (``DOPESHEET_HT_editor_buttons`` in Timeline mode, a plain class, not in
  bpy.types) is wrapped to draw ``draw_header`` below and restored on unregister.
- Maya's animation range = scene frame_start/end; its playback range = the preview range
  (``use_preview_range`` off: playback = animation range, inner fields greyed).
- Maya's time slider always shows exactly the playback range and never zooms or scrolls: every Timeline is
  framed to the range's frame cells (``fit_timelines``, ``view2d.zoom_border``; a msgbus subscription on the
  range and a load_post handler defer it to a timer), the WINDOW draw handler re-fits a view that drifted
  (a resize, Blender's own view operators) and the wheel / Ctrl+MMB zoom are swallowed in the Timeline
  (``allset.time_view_lock``). The Range Slider is the one control of what the Time Slider shows.
- LMB on the timeline = time (Shift = red range), RMB = Maya's
  Time Slider menu, MMB = move the time without updating the scene (Maya's MMB drag).
- The
  header is the Range Slider row in Maya's order; Blender's Playback / Keying / View / Marker menus move
  into the animation preferences menu at its right end (``DOPESHEET_MT_editor_menus.draw_collapsible`` is
  overridden on the class for Timeline mode, deleted on unregister). A timeline with its sidebar shown (the Maya Workflow Kit
  layout) draws the current frame field and the 8 transport buttons there, at the right end of the
  Time Slider row like Maya (``ALLSET_PT_time_slider``); other timelines keep them in the header.
"""

import re
import time

import bpy

from .. import results
from .. import compat, i18n
from ..operators import taphold
from bpy.app.handlers import persistent

# Blender 5.x: the Timeline is a Dope Sheet mode; compat names the header classes.
header_classes = compat.timeline_header_classes


def _is_timeline(context):
    space = getattr(context, "space_data", None)
    return space is not None and getattr(space, "mode", None) == 'TIMELINE'

_ORIGINAL = {}
_OWNER = object()
_RANGE_PROPS = ("frame_start", "frame_end", "frame_preview_start", "frame_preview_end",
                "use_preview_range")


def draw_transport(layout, context):
    """Current frame field + the 8 Maya transport buttons."""
    scene, screen = context.scene, context.screen
    row = layout.row()
    row.ui_units_x = 4.5    # current time field width 90 px
    row.prop(scene, "frame_current", text="")
    row = layout.row(align=True)
    row.operator("screen.frame_jump", text="", icon='REW').end = False
    row.operator("screen.frame_offset", text="", icon='TRIA_LEFT_BAR').delta = -1
    row.operator("screen.keyframe_jump", text="", icon='PREV_KEYFRAME').next = False
    if screen.is_animation_playing:
        row.scale_x = 2
        row.operator("screen.animation_play", text="", icon='PAUSE')
        row.scale_x = 1
    else:
        row.operator("screen.animation_play", text="", icon='PLAY_REVERSE').reverse = True
        row.operator("screen.animation_play", text="", icon='PLAY')
    row.operator("screen.keyframe_jump", text="", icon='NEXT_KEYFRAME').next = True
    row.operator("screen.frame_offset", text="", icon='TRIA_RIGHT_BAR').delta = 1
    row.operator("screen.frame_jump", text="", icon='FF').end = True


def has_slider_panel(space, area=None):
    """The timeline shows the Time Slider buttons in its sidebar (the Maya Workflow Kit layout). With ``area``, the
    sidebar must also have room: Blender 5.x loads the 4.5 template's timeline sidebar 1 px wide,
    and then the buttons stay in the header."""
    if space is None or space.type != 'DOPESHEET_EDITOR' or not space.show_region_ui:
        return False
    if area is None:
        return True
    ui = next((r for r in area.regions if r.type == 'UI'), None)
    return ui is not None and ui.width > 20


# Range Slider row, Maya order.
RANGE_ITEMS = ("start", "playback start", "range", "playback end", "end", "auto key", "No Character Set",
               "No Anim Layer", "fps", "loop", "sound", "animation preferences")

# The row's budget in ui units (one unit = 20 px at scale 1). Blender scrolls a header whose layout is wider
# than the area, which put a scrollbar between the Time Slider and the Range Slider and pushed the end fields out
# of sight on a short timeline; the bar label is sized so the row always fits, and the optional items at the right
# go first when it can't (last in the tuple = dropped first).
ROW_CORE_UNITS = 29.0        # editor-type menu, the four range fields (4 x 4.5), auto key, loop, sound, preferences, gaps
ROW_TRANSPORT_UNITS = 14.0   # current frame field + 8 transport buttons when they sit in the header
ROW_OPTIONAL = (("fps", 5.0), ("character_set", 6.0), ("anim_layer", 6.0))
ROW_MIN_BAR = 8.0            # keep this much bar before dropping an optional item


def row_plan(width_units, transport=False):
    """(bar label units, names of the optional items shown) for a Range Slider row ``width_units`` wide."""
    from . import range_bar
    shown = {name for name, _units in ROW_OPTIONAL}
    bar = width_units - ROW_CORE_UNITS - (ROW_TRANSPORT_UNITS if transport else 0.0) - sum(u for _n, u in ROW_OPTIONAL)
    for name, units in reversed(ROW_OPTIONAL):
        if bar >= ROW_MIN_BAR:
            break
        shown.discard(name)
        bar += units
    bar = max(float(range_bar.MIN_BAR_UNITS), min(float(range_bar.BAR_UNITS), bar))
    return bar, shown


def _row_plan(context):
    region = context.region
    unit = 20.0 * (context.preferences.system.ui_scale or 1.0)
    width = region.width if region is not None and region.type == 'HEADER' else 0
    if width <= 0:
        from . import range_bar
        return float(range_bar.BAR_UNITS), {name for name, _u in ROW_OPTIONAL}
    space, area = context.space_data, context.area
    return row_plan(width / unit, transport=not has_slider_panel(space, area))


def draw_header(context, layout):
    space, area = context.space_data, context.area
    if has_slider_panel(space) and not has_slider_panel(space, area):
        # Maya Workflow Kit layout whose sidebar can't open (Blender 5.x: the Timeline mode keeps its sidebar 1 px, even in a
        # factory file): one row, Range Slider first, the Time Slider buttons at the right end
        draw_range_slider(layout, context)
        layout.separator_spacer()
        draw_transport(layout, context)
        return
    if not has_slider_panel(space, area):
        layout.separator_spacer()
        draw_transport(layout, context)
        layout.separator_spacer()
    draw_range_slider(layout, context)   # Maya: the range fields start at the left edge


def draw_range_slider(layout, context):
    scene = context.scene
    bar_units, shown = _row_plan(context)
    # animation start | playback start [range bar] playback end | animation end
    # (the playback fields are the range that plays: ui/range_bar.py's allset_playback_start / _end)
    row = layout.row(align=True)
    row.ui_units_x = 4.5
    row.prop(scene, "frame_start", text="")
    row = layout.row(align=True)
    row.ui_units_x = 4.5
    row.prop(scene, "allset_playback_start", text="")
    # Maya's range bar. In the Maya Workflow Kit layout an empty label holds its place and
    # ui/range_bar.py draws the draggable bar there. Elsewhere Blender has no such
    # widget: the toggle = use the playback range (off = the whole animation range), the button frames it.
    from . import range_bar
    bar = layout.row(align=True)
    bar.ui_units_x = bar_units
    if range_bar.active(context):
        range_bar.plan_units(context.area, bar_units)
        bar.ui_units_x = max(float(range_bar.MIN_BAR_UNITS), bar_units + range_bar.extra_units(context.area))
        bar.label(text="")
    else:
        a, b = playback_range(scene)
        bar.prop(scene, "use_preview_range", text="", toggle=True, icon='PREVIEW_RANGE')
        bar.operator("anim.scene_range_frame", text=f"{a}" + " " * 40 + f"{b}")
    row = layout.row(align=True)
    row.ui_units_x = 4.5
    row.prop(scene, "allset_playback_end", text="")
    row = layout.row(align=True)
    row.ui_units_x = 4.5
    row.prop(scene, "frame_end", text="")

    layout.separator_spacer()
    row = layout.row(align=True)
    # Maya auto key: Maya's key button, red while on (issue #37: Blender's record circle wasn't recognised)
    # The kit's own Maya Auto Key (operators/auto_key.py): keys only already keyed channels without
    # Blender's "Only Insert Available" preference.
    on = getattr(scene, "allset_auto_key", False)
    key = row.row(align=True)
    key.alert = on
    key.prop(scene, "allset_auto_key", text="", toggle=True, icon='KEY_HLT' if on else 'KEY_DEHLT')
    # Maya: the current character set and the current animation layer (the selected
    # layer of operators/anim_layers; "No Anim Layer" while the scene has only BaseAnimation)
    from ..operators import anim_layers
    ls = getattr(context.scene, "allset_anim_layers", ())
    sel = anim_layers.selected(context.scene) if len(ls) > 1 else None
    # Maya's current character field (kit character sets = Keying Sets, operators/character_sets.py)
    ks = scene.keying_sets.active
    if "character_set" in shown:
        sub = layout.row()
        sub.ui_units_x = 6
        sub.menu("ALLSET_MT_character_set_current",
                 text=ks.bl_label if ks is not None else i18n.mark("No Character Set"), icon='DOWNARROW_HLT')
    for text, on in ((sel.name if sel is not None else i18n.mark("No Anim Layer"), sel is not None),):
        if "anim_layer" not in shown:
            continue
        sub = layout.row()
        sub.enabled = on
        sub.ui_units_x = 6
        sub.label(text=text, icon='DOWNARROW_HLT')
    if "fps" in shown:
        row = layout.row()
        row.ui_units_x = 5
        fps = scene.render.fps / scene.render.fps_base
        row.menu("RENDER_MT_framerate_presets", text=f"{fps:g} fps")
    row = layout.row(align=True)
    from ..operators import playback_maya
    loop = getattr(scene, "allset_playback_loop", 'CONTINUOUS')
    row.operator("allset.playback_loop_cycle", text="", icon=playback_maya.LOOP_ICONS[loop])
    row.prop(scene, "use_audio", text="", icon='SPEAKER', invert_checkbox=True)
    row.menu("ALLSET_MT_anim_preferences", text="", icon='PREFERENCES')


class ALLSET_MT_anim_preferences(bpy.types.Menu):
    """Animation preferences (Maya's button at the right end of the Range Slider): Blender's
    timeline Playback, Keying, View and Marker menus"""
    bl_label = "Animation Preferences"

    def draw(self, context):
        lay = self.layout
        lay.popover(panel="TIME_PT_playback", text="Playback")
        lay.popover(panel="TIME_PT_keyframing_settings", text="Keying")
        lay.separator()
        lay.menu("TIME_MT_view", text="View")
        lay.menu(compat.timeline_marker_menu(), text="Marker")


class ALLSET_PT_time_slider(bpy.types.Panel):
    """Current time field and transport buttons at the right of Maya's Time Slider."""
    bl_space_type = 'DOPESHEET_EDITOR'
    bl_region_type = 'UI'
    bl_label = "Time Slider"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and space.mode == 'TIMELINE'

    def draw(self, context):
        draw_transport(self.layout.row(align=False), context)


# --- Time Slider hand feel ---------------------------------------------------------------
# Maya: LMB anywhere on the Time Slider moves the time, Shift+LMB drag highlights a range, RMB = the
# Time Slider menu (Maya 2022 labels).
# Blender's timeline is a Dope Sheet mode, so these sit first in the "Dopesheet" keymap and pass
# through in the Dope Sheet itself (keys are clicked there in Maya too).

RANGE_COLOR = (0.78, 0.16, 0.16, 0.35)   # red range highlight
RANGE_ARROW_COLOR = (1.0, 1.0, 1.0, 0.9)
# Time Slider items with no Blender equivalent: (label, Help Line text)
TIME_NOTICES = {
    "Paste Connect": "Blender pastes keys as they were copied: no connect (offset) paste.",
    "Play Every Frame, Free": "Blender never plays faster than the scene frame rate.",
    "Enabled Clips": "Blender has no Time Editor clips (NLA strips instead).",
    "Sound Length": "Use the sound strip's length in the Video Sequencer.",
}


def frame_at(region, x):
    """Whole frame under window x in a timeline WINDOW region."""
    return int(round(region.view2d.region_to_view(x - region.x, 0)[0]))


def set_range(wm, a, b, on=True):
    wm.allset_time_range = (int(a), int(b))
    wm.allset_time_range_on = on


_LAST_PRESS = None   # (time, window x, region pointer) of the last plain Time Slider press


def _second_press(context, event, region):
    """True for a second plain press within the double-click time near the first: a double-click. Blender's own
    DOUBLE_CLICK event goes to allset.time_range_all before this; simulated events never become one."""
    global _LAST_PRESS
    now = time.monotonic()
    last, _LAST_PRESS = _LAST_PRESS, (now, event.mouse_x, region.as_pointer())
    if last is None or last[2] != region.as_pointer():
        return False
    limit = getattr(context.preferences.inputs, "mouse_double_click_time", 350) / 1000.0
    if now - last[0] <= limit and abs(event.mouse_x - last[1]) <= 4 * (context.preferences.system.ui_scale or 1.0):
        _LAST_PRESS = None
        return True
    return False


class ALLSET_OT_time_scrub(bpy.types.Operator):
    """Maya Time Slider: click or drag to move the time (Shift: highlight a range, middle mouse: keep the pose)"""
    bl_idname = "allset.time_scrub"
    bl_label = "Time Slider Scrub"
    bl_options = {'INTERNAL'}

    range: bpy.props.BoolProperty(name="Range", description="Shift-drag: highlight a time range",
                                  options={'SKIP_SAVE'})
    hold: bpy.props.BoolProperty(name="Hold", description="Move the time without updating the scene, so the "
                                 "current pose can be keyed at another frame", options={'SKIP_SAVE'})

    def invoke(self, context, event):
        region = context.region
        if not _is_timeline(context) or region is None or region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        self._region = region
        self._button = event.type
        self._held = None
        if self.hold:
            # Maya MMB: every animated channel keeps the value it has now while the time moves
            from ..operators import time_hold
            self._held = time_hold.snapshot()
        wm, scene = context.window_manager, context.scene
        self._old = (scene.frame_current, tuple(wm.allset_time_range), wm.allset_time_range_on)
        f = frame_at(region, event.mouse_x)
        if self.range:
            self._anchor = f
            set_range(wm, f, f)
        elif not self.hold and _second_press(context, event, region):
            # a double-click: the whole visible range; the time stays where the first click put it
            set_range(wm, *playback_range(scene))
            _tag(context)
            return {'FINISHED'}
        else:
            wm.allset_time_range_on = False   # a plain click drops the highlighted range (Maya)
            self._set_frame(scene, f)
        _tag(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _set_frame(self, scene, f):
        if self._held is None:
            scene.frame_current = f
        else:
            from ..operators import time_hold
            time_hold.move_time(scene, f, self._held)

    def modal(self, context, event):
        wm, scene = context.window_manager, context.scene
        if event.type == 'MOUSEMOVE':
            f = frame_at(self._region, event.mouse_x)
            if self.range:
                set_range(wm, self._anchor, f)
            elif (f if self._held is not None else taphold.kept_frame(f)) != scene.frame_current:
                # MMB evaluates the frame as asked; the plain write keeps 0 below frame 0 (see kept_frame)
                self._set_frame(scene, f)
            _tag(context)
            return {'RUNNING_MODAL'}
        if event.type == self._button and event.value == 'RELEASE':
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._set_frame(scene, self._old[0])
            set_range(wm, *self._old[1], on=self._old[2])
            _tag(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class ALLSET_OT_time_range_all(bpy.types.Operator):
    """Maya Time Slider: a double-click highlights the whole visible range"""
    bl_idname = "allset.time_range_all"
    bl_label = "Time Slider Range All"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        global _LAST_PRESS
        region = context.region
        if not _is_timeline(context) or region is None or region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        _LAST_PRESS = None
        set_range(context.window_manager, *playback_range(context.scene))
        _tag(context)
        return {'FINISHED'}


# Maya's Time Slider has no Adjust Last Operation panel. Blender opens its HUD over a timeline once an operator
# with a redo panel ran there (its own double-click toggled the channel editability, #335); the flag that keeps
# the panel closed lives on the HUD region, which exists only after the panel was shown, so the draw handler asks
# a timer to close it when it sees one.
def hide_redo_panels():
    wm = bpy.context.window_manager
    for win, area, region in list(timeline_areas(wm)):
        space = area.spaces.active
        if space.show_region_hud and any(r.type == 'HUD' for r in area.regions):
            # the flag's update fades the region out and re-initialises the area for the context's window: from a
            # timer (no window in the context) the fade started window-less and Blender crashed when it ended
            with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
                space.show_region_hud = False
    return None


def _redo_panel_shown(context):
    area = context.area
    return (area is not None and getattr(context.space_data, "show_region_hud", False)
            and any(r.type == 'HUD' for r in area.regions))


RANGE_EDGE_PX = 8          # end-arrow zone of a highlighted range (x UI scale)


def range_zone(context, region, x):
    """'LEFT' / 'RIGHT' / 'MOVE' when window x is on the highlighted range of this timeline, else None."""
    from ..operators import time_range
    wm = context.window_manager
    if not getattr(wm, "allset_time_range_on", False):
        return None
    x0, x1 = range_rect(region, *wm.allset_time_range)
    edge = RANGE_EDGE_PX * (context.preferences.system.ui_scale or 1.0)
    return time_range.zone(x - region.x, x0, x1, edge)


class ALLSET_OT_time_range_drag(bpy.types.Operator):
    """Maya Time Slider range: drag the middle to move its keys, an end arrow to scale them"""
    bl_idname = "allset.time_range_drag"
    bl_label = "Move / Scale Range Keys"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def invoke(self, context, event):
        from ..operators import time_keys, time_range
        region = context.region
        if not _is_timeline(context) or region is None or region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        mode = range_zone(context, region, event.mouse_x)
        if mode is None:
            return {'PASS_THROUGH'}
        wm = context.window_manager
        a, b = sorted(wm.allset_time_range)
        curves, seen = [], set()
        for node in time_keys.nodes(context):
            for fc in time_keys.node_fcurves(node):
                if fc.as_pointer() in seen:
                    continue
                seen.add(fc.as_pointer())
                idx = [i for i, kp in enumerate(fc.keyframe_points) if time_keys._in(kp, a, b)]
                if idx:
                    curves.append((fc, idx))
        self._drag = time_range.Drag(curves, a, b)
        self._region, self._mode, self._range = region, ('MOVE' if a == b else mode), (a, b)
        self._f0 = frame_at(region, event.mouse_x)
        self._f, self._moved = self._f0, False
        self._x0 = event.mouse_x
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _update(self, context, f):
        from ..operators import time_range
        wm = context.window_manager
        self._f = f
        self._drag.apply(self._mode, self._f0, f)
        set_range(wm, *time_range.new_range(*self._range, self._mode, self._f0, f))
        _tag(context)
        for area in context.screen.areas:
            if area.type in {'GRAPH_EDITOR', 'VIEW_3D'}:
                area.tag_redraw()

    def modal(self, context, event):
        wm, scene = context.window_manager, context.scene
        if event.type == 'MOUSEMOVE':
            f = frame_at(self._region, event.mouse_x)
            if abs(event.mouse_x - self._x0) >= 3:
                self._moved = True
            if self._moved and f != self._f:
                self._update(context, f)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if not self._moved:
                # a click on the range = a plain Time Slider click: drop the range, go to that frame (no undo step)
                wm.allset_time_range_on = False
                scene.frame_current = self._f0
                _tag(context)
                return {'CANCELLED'}
            n = self._drag.finish(self._mode, self._f0, self._f)
            scene.frame_set(scene.frame_current)          # re-evaluate at the current time
            results.result(self, f"{'Moved' if self._mode == 'MOVE' else 'Scaled'} {n} key(s)")
            _tag(context)
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._drag.cancel()
            set_range(wm, *self._range)
            _tag(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


def _tag(context):
    for area in context.screen.areas if context.screen else ():
        if area.type == 'DOPESHEET_EDITOR':
            area.tag_redraw()


class ALLSET_OT_time_slider_menu(bpy.types.Operator):
    """Maya Time Slider menu (RMB on the Time Slider)"""
    bl_idname = "allset.time_slider_menu"
    bl_label = "Time Slider Menu"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if not _is_timeline(context):
            return {'PASS_THROUGH'}
        bpy.ops.wm.call_menu(name=ALLSET_MT_time_slider.__name__)
        return {'FINISHED'}


class ALLSET_OT_time_slider_unavailable(bpy.types.Operator):
    """Time Slider item with no Blender equivalent (greyed)"""
    bl_idname = "allset.time_slider_unavailable"
    bl_label = "Not Available"
    bl_options = {'INTERNAL'}

    item: bpy.props.StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return False

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        line = TIME_NOTICES.get(props.item, "")
        if line:
            from . import notices
            notices.show(f"{props.item}: {line}")
        return f"Maya: Time Slider > {props.item}\n{line}"

    def execute(self, context):
        return {'CANCELLED'}


def _keys(layout, action, text=None, **props):
    op = layout.operator("allset.time_keys", text=text)
    op.action = action
    for k, v in props.items():
        setattr(op, k, v)
    return op


def _grey(layout, label):
    layout.operator(ALLSET_OT_time_slider_unavailable.bl_idname, text=label).item = label


class ALLSET_MT_time_slider(bpy.types.Menu):
    """Maya Time Slider menu, in Maya's order"""
    bl_label = "Time Slider"

    def draw(self, context):
        lay = self.layout
        _keys(lay, "CUT", "Cut")
        _keys(lay, "COPY", "Copy")
        lay.menu("ALLSET_MT_time_slider_paste", text="Paste")
        _keys(lay, "DELETE", "Delete")
        _keys(lay, "SNAP", "Snap")
        lay.menu("ALLSET_MT_time_slider_keys", text="Keys")
        lay.menu("ALLSET_MT_time_slider_tangents", text="Tangents")
        lay.separator()
        lay.menu("ALLSET_MT_time_slider_speed", text="Playback Speed")
        lay.menu("ALLSET_MT_time_slider_looping", text="Playback Looping")
        lay.menu("ALLSET_MT_time_slider_range", text="Set Range to")
        lay.separator()
        op = lay.operator("allset.menu_run", text="Playblast...")
        op.op, op.props = "render.opengl", '{"animation": true}'


class ALLSET_MT_time_slider_paste(bpy.types.Menu):
    bl_label = "Paste"

    def draw(self, context):
        _keys(self.layout, "PASTE", "Paste")
        _grey(self.layout, "Paste Connect")


class ALLSET_MT_time_slider_keys(bpy.types.Menu):
    bl_label = "Keys"

    def draw(self, context):
        for action, label in (("TO_KEY", "Convert to Key"), ("TO_BREAKDOWN", "Convert to Breakdown"),
                              ("ADD_INBETWEEN", "Add Inbetween"), ("REMOVE_INBETWEEN", "Remove Inbetween")):
            _keys(self.layout, action, label)


class ALLSET_MT_time_slider_tangents(bpy.types.Menu):
    bl_label = "Tangents"

    def draw(self, context):
        for kind in ("SPLINE", "LINEAR", "CLAMPED", "STEPPED", "FLAT", "PLATEAU", "AUTO"):
            _keys(self.layout, "TANGENT", kind.title(), tangent=kind)


class ALLSET_MT_time_slider_speed(bpy.types.Menu):
    bl_label = "Playback Speed"

    def draw(self, context):
        lay = self.layout
        lay.prop_enum(context.scene, "sync_mode", 'FRAME_DROP', text="Real-time")
        _grey(lay, "Play Every Frame, Free")
        lay.prop_enum(context.scene, "sync_mode", 'NONE', text="Play Every Frame, Max Real-time")


class ALLSET_MT_time_slider_looping(bpy.types.Menu):
    bl_label = "Playback Looping"

    def draw(self, context):
        lay = self.layout
        for value, label in (('ONCE', "Once"), ('OSCILLATE', "Oscillate"), ('CONTINUOUS', "Continuous")):
            lay.prop_enum(context.scene, "allset_playback_loop", value, text=label)


class ALLSET_MT_time_slider_range(bpy.types.Menu):
    bl_label = "Set Range to"

    def draw(self, context):
        lay = self.layout
        for mode, label in (("START_END", "Start/End"), ("MIN_MAX", "Min/Max"), ("SELECTED", "Selected")):
            lay.operator("allset.time_set_range", text=label).mode = mode
        _grey(lay, "Enabled Clips")
        _grey(lay, "Sound Length")


TIME_SLIDER_MENUS = (ALLSET_MT_time_slider, ALLSET_MT_time_slider_paste, ALLSET_MT_time_slider_keys,
                     ALLSET_MT_time_slider_tangents, ALLSET_MT_time_slider_speed,
                     ALLSET_MT_time_slider_looping, ALLSET_MT_time_slider_range)


# --- the red range highlight -----------------------------------------------------------------------

_draw_handle = []


def range_rect(region, a, b):
    """Window-region x0, x1 of frames a..b (whole frames: half a frame either side)."""
    lo, hi = min(a, b) - 0.5, max(a, b) + 0.5
    x0 = region.view2d.view_to_region(lo, 0, clip=False)[0]
    x1 = region.view2d.view_to_region(hi, 0, clip=False)[0]
    return x0, x1


def _draw_range():
    context = bpy.context
    wm = context.window_manager
    if not _is_timeline(context):
        return
    if _redo_panel_shown(context) and not bpy.app.timers.is_registered(hide_redo_panels):
        bpy.app.timers.register(hide_redo_panels, first_interval=0.0)
    region = context.region
    _check_view(context, region)
    maya = has_slider_panel(context.space_data)
    if maya:
        _draw_ruler(context, region)
    _draw_keys(context, region, maya)
    if maya:
        _draw_blue_pencil(context, region)
    if not getattr(wm, "allset_time_range_on", False):
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    x0, x1 = range_rect(region, *wm.allset_time_range)
    h = region.height
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": ((x0, 0), (x1, 0), (x1, h), (x0, 0), (x1, h), (x0, h))})
    gpu.state.blend_set('ALPHA')
    shader.uniform_float("color", RANGE_COLOR)
    batch.draw(shader)
    # Maya's arrows on a highlighted range: ◀ / ▶ in the end zones (scale), ◀▶ in the middle (move)
    edge = RANGE_EDGE_PX * (context.preferences.system.ui_scale or 1.0)
    k = min(edge * 0.6, h * 0.25)
    y = h * 0.5
    tris = []

    def arrow(cx, d):
        tris.extend(((cx - d * k * 0.5, y), (cx + d * k * 0.5, y + k * 0.6), (cx + d * k * 0.5, y - k * 0.6)))
    cx = (x0 + x1) * 0.5
    if x1 - x0 >= 3 * edge:
        arrow(x0 + edge * 0.5, 1)       # tip left
        arrow(x1 - edge * 0.5, -1)      # tip right
    arrow(cx - k * 0.55, 1)
    arrow(cx + k * 0.55, -1)
    batch = batch_for_shader(shader, 'TRIS', {"pos": tris})
    shader.uniform_float("color", RANGE_ARROW_COLOR)
    batch.draw(shader)
    gpu.state.blend_set('NONE')


# --- Maya ruler -------------------------------------------
# The Maya Workflow Kit layout's Time Slider is painted over Blender's timeline drawing: a dark background, one 2 px
# tick + label per step (the smallest step whose spacing fits the labels, like Maya), the bottom band and the
# translucent current-time block with its white frame number. At UI scale 1.0 (a 32 px tall ruler): rows 1-8 labels
# #757575, ticks rows 13-27 #7c7c7c, rows 29-31 #373737, background #2b2b2b, current time = white at 18.4 % over the
# frame's cell, its number white in rows 16-23.
# Blender draws its own current-frame box in the region overlay after every Python handler (a full-region
# POST_PIXEL fill hides everything else of Blender's) and no RNA / theme-free switch hides it, so that box stays on
# top.
MAYA_RULER_H = 32.0
RULER_BG = (0x2b / 255, 0x2b / 255, 0x2b / 255, 1.0)
RULER_BAND = (0x37 / 255, 0x37 / 255, 0x37 / 255, 1.0)
RULER_TICK = (0x7c / 255, 0x7c / 255, 0x7c / 255, 1.0)
RULER_LABEL = (0x75 / 255, 0x75 / 255, 0x75 / 255, 1.0)
# the current-time block is #525252 over the #2b2b2b ruler = white at (0x52 - 0x2b) / (0xff - 0x2b) = 18.4 %
RULER_CURRENT = (1.0, 1.0, 1.0, (0x52 - 0x2b) / (0xff - 0x2b))
RULER_CURRENT_LABEL = (1.0, 1.0, 1.0, 1.0)
# (top row, bottom row) of the 32 px ruler. With Time Slider bookmarks
# (kit: timeline markers, operators/bookmarks.py) the ruler gets a strip on top and moves labels / ticks down:
# strip #454545 rows 0-8, each bookmark's colour at 80 % over
# it in rows 0-4 with a solid 1 px left edge over the strip height.
ROWS = {"label": (1, 8), "tick": (13, 27), "current_label": (16, 23), "band": (29, 31)}
ROWS_BOOKMARKS = {"label": (11, 18), "tick": (23, 27), "current_label": (19, 26), "band": (29, 31),
                  "strip": (0, 8), "bookmark": (0, 4)}
BOOKMARK_STRIP = (0x45 / 255, 0x45 / 255, 0x45 / 255, 1.0)


def _themed(color, field):
    """A ruler colour moved with the Blender theme's Dope Sheet / Timeline colours (ui/theme_follow.py)."""
    from . import theme_follow
    return theme_follow.follow(color, "dopesheet_editor", field)


BOOKMARK_RGB = (204 / 255, 92 / 255, 92 / 255)   # bookmark colour (Maya picks one per bookmark)
TICK_PX = 2.0
# Eight-pixel label row in the 32 px ruler, converted to BLF size.
RULER_FONT_SIZE = 8.0 / 0.72
NICE_STEPS = tuple(m * 10 ** e for e in range(8) for m in (1, 2, 5))


# Cases (widget px, first, last frame) where this model picks another step than Maya (tests/test_step186_time_slider.py;
# the default 1-120 and the short ranges match): Maya's threshold also moves with the widget width and the step, and
# it uses steps of 4 / 400 / 4000 with wide labels. "max(a, b x digits)" thresholds with 1-2-4 steps drew 1-120 every
# 4 frames: not taken.
STEP_MATCHES = 32
STEP_DEVIATIONS = ((1292, 1, 10000), (692, 1, 120), (1592, 1, 120), (1592, 1, 60), (1292, 1, 215), (1292, 1, 230),
                   (1292, 1, 250), (1292, 1001, 1100), (1292, 1, 100000), (692, 1, 130), (692, 1, 110))


def label_digits(frame):
    return len(str(abs(int(frame)))) + (1 if frame < 0 else 0)


def label_need_px(digits):
    """Spacing (px at UI scale 1) between two labels of ``digits`` characters (at a 1292 px wide
    ruler: <= 3 digits fit at 25.6 px but not 24.7, 4 digits need more than 25.6 and fit at 32, 5 digits
    need more than 32)."""
    return max(25.0, 7.0 * digits + 3.0)


def _multiples(step, lo, hi):
    import math
    first = math.ceil(lo / step) * step
    return range(int(first), int(hi) + 1, int(step))


def tick_step(start, end, px_per_frame, scale=1.0):
    """Maya Time Slider step (frames between ticks / labels) for the playback range start..end shown at
    ``px_per_frame``: the smallest of 1, 2, 5, 10, 20, 50 ... whose spacing fits the widest label below the end."""
    for step in NICE_STEPS:
        labels = _multiples(step, start, max(start, end - 1))
        widest = max((label_digits(f) for f in (labels[0], labels[-1])), default=1) if len(labels) else 1
        if step * px_per_frame >= label_need_px(widest) * scale:
            return step
    return NICE_STEPS[-1]


def ruler_ticks(step, lo, hi):
    """Frames with a tick and a label in the visible frame range lo..hi."""
    return list(_multiples(step, lo - 1, hi + 1))


# A taller Time Slider (Maya 2026 behaviour, #190): the frame numbers stay at the top in
# their size, the current frame number stays at the bottom, and the ticks keep their bottom end and normal length
# until half the room between the numbers and that end (less this many px) is longer; then they take that half.
TICK_HALF_PAD = 2.33


def _rows(name, h, rows=None, scale=1.0):
    """(y0, y1) region rows (bottom-up) of a ruler row band at region height ``h``, UI-scaled: the label rows keep
    their place under the top edge, the band and the current frame number theirs above the bottom edge, and the
    ticks grow Maya's way (``TICK_HALF_PAD``)."""
    rows = rows or ROWS
    top, bottom = rows[name]
    k = min(h / MAYA_RULER_H, scale)
    if name == "tick":
        y0 = (MAYA_RULER_H - bottom - 1) * k                     # the bottom end, above the band
        normal = (bottom + 1 - top) * k
        label_low = h - (rows["label"][1] + 1) * k              # the frame numbers' lowest row
        half = (label_low - y0) / 2 - TICK_HALF_PAD * k
        return y0, y0 + max(normal, half)
    if name in ("band", "current_label"):
        return (MAYA_RULER_H - bottom - 1) * k, (MAYA_RULER_H - top) * k
    return h - (bottom + 1) * k, h - top * k


_TRIS = {}      # triangle points -> their GPU batch: the ruler and the key ticks redraw the same shapes every frame


def _tris_batch(shader, tris):
    """The GPU batch of the triangle list ``tris`` (``UNIFORM_COLOR``), made once and drawn again while the same
    shapes are drawn (the Time Slider redraws on every frame change)."""
    key = tuple(tris)
    batch = _TRIS.get(key)
    if batch is None:
        from gpu_extras.batch import batch_for_shader
        batch = batch_for_shader(shader, 'TRIS', {"pos": tris})
        if len(_TRIS) > 256:
            _TRIS.clear()
        _TRIS[key] = batch
    return batch


def _draw_ruler(context, region):
    import blf
    import gpu
    scene = context.scene
    s = context.preferences.system.ui_scale or 1.0
    w, h = region.width, region.height
    v2d = region.view2d

    def x_of(f):
        return v2d.view_to_region(f, 0, clip=False)[0]
    pxf = x_of(1.0) - x_of(0.0)
    if pxf <= 0:
        return
    start, end = playback_range(scene)
    step = tick_step(start, end, pxf, s)
    lo, hi = v2d.region_to_view(0, 0)[0], v2d.region_to_view(w, 0)[0]
    frames = ruler_ticks(step, lo, hi)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')

    def rects(rs, colour):
        tris = []
        for x0, y0, x1, y1 in rs:
            tris += [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]
        if tris:
            shader.uniform_float("color", colour)
            _tris_batch(shader, tris).draw(shader)
    from ..operators import bookmarks
    marks = bookmarks.markers(scene)
    rows = ROWS_BOOKMARKS if marks else ROWS
    gpu.state.blend_set('ALPHA')
    rects([(0, 0, w, h)], _themed(RULER_BG, "back"))
    b0, b1 = _rows("band", h, rows, s)
    rects([(0, b0, w, b1)], _themed(RULER_BAND, "back"))
    if marks:
        s0, s1 = _rows("strip", h, rows, s)
        rects([(0, s0, w, s1)], _themed(BOOKMARK_STRIP, "back"))
        m0, m1 = _rows("bookmark", h, rows, s)
        bars, edges = [], []
        for m in marks:
            a, b = bookmarks.bookmark_range(scene, m)
            x0, x1 = round(x_of(a - 0.5)), round(x_of(b + 0.5))
            bars.append((x0, m0, x1, m1))
            edges.append((x0, s0, x0 + max(1.0, round(s)), s1))
        rects(bars, (*BOOKMARK_RGB, 0.8))
        rects(edges, (*BOOKMARK_RGB, 1.0))
    tw = max(1.0, round(TICK_PX * s))
    t0, t1 = _rows("tick", h, rows, s)
    lefts = {f: round(x_of(f - 0.5)) for f in frames}
    rects([(x, t0, x + tw, t1) for x in lefts.values()], _themed(RULER_TICK, "text"))
    cur = scene.frame_current
    cx0, cx1 = x_of(cur - 0.5), x_of(cur + 0.5)
    rects([(round(cx0), 0, max(round(cx0) + 1, round(cx1)), h)], _themed(RULER_CURRENT, "text"))
    # labels: 2 px + a fifth of a frame right of the tick
    l0, _l1 = _rows("label", h, rows, s)
    # The same UI-scaled font is used for the current-frame number.
    blf.size(0, RULER_FONT_SIZE * s)
    off = 2 * s + 0.2 * pxf
    blf.color(0, *_themed(RULER_LABEL, "text"))
    for f, x in lefts.items():
        blf.position(0, x + off, l0, 0)
        blf.draw(0, str(f))
    c0, _c1 = _rows("current_label", h, rows, s)
    blf.color(0, *_themed(RULER_CURRENT_LABEL, "text"))
    blf.position(0, round(cx0) + off, c0, 0)
    blf.draw(0, str(cur))
    gpu.state.blend_set('NONE')


def playback_range(scene):
    """Maya playback range = the preview range when on, else the scene range (module docstring)."""
    if scene.use_preview_range:
        return scene.frame_preview_start, scene.frame_preview_end
    return scene.frame_start, scene.frame_end


# --- key ticks -----------------------------------------------------------------------------
# Maya draws the keys of the selected nodes as 1 px lines over the whole Time Slider height: keys red,
# breakdowns green.
KEY_RGB = (1.0, 0.0, 0.0, 1.0)
BREAKDOWN_RGB = (0.0, 1.0, 0.0, 1.0)


_bone_curves = {}     # pose bone pointer -> (owner's F-curve count, the bone's F-curves) kept while playing / dragging
# a curve path's leading ``pose.bones["name"]`` (names are escaped: a backslash goes with the character after it)
_BONE_PREFIX = re.compile(r'pose\.bones\["(?:[^"\\]|\\.)*"\]', re.DOTALL)


def _bones_curves(bones):
    """{pose bone pointer: ``time_keys.node_fcurves``} for ``bones``: each skeleton's curves are shared out by the same
    rule (a bone's curves start with its ``pose.bones["n"]`` path and then "." or "["), once per skeleton
    (``_skeleton_parts``, kept until the curves change), instead of looking through every curve of the skeleton once
    per bone (hundreds of selected controls took a third of a second per Time Slider redraw; one picked control of a
    rig with a thousand curves read them all again on every redraw)."""
    from ..operators import time_keys
    out, owners = {}, {}
    for pb in bones:
        ptr = pb.as_pointer()
        if ptr not in out:
            out[ptr] = []
            owners.setdefault(pb.id_data.as_pointer(), []).append((ptr, pb))
    escape = bpy.utils.escape_identifier
    for group in owners.values():
        first = group[0][1]
        fcs = time_keys._cb()._fcurves(first)
        if fcs is None:
            continue
        ob = first.id_data
        parts = _skeleton_parts(ob, fcs, _skeleton_key(ob, fcs))
        # Blender finds the n-th curve of a slot by stepping through the n curves before it: several bones take
        # their curves from one list of the skeleton's curves
        seq = list(fcs) if len(group) > 1 else fcs
        for ptr, pb in group:
            # = time_keys.prefix(pb): a pose bone's path is its escaped name in pose.bones["..."]
            idx = parts.get(f'pose.bones["{escape(pb.name)}"]')
            if idx:
                out[ptr] = [seq[i] for i in idx]
    return out


_PARTS = {}     # (Action, slot, curve count, bone names) -> ``_skeleton_parts``; dropped with ``_KEYS``


def _skeleton_key(ob, fcs):
    """(Action, slot, number of curves, bone names) of skeleton ``ob`` whose curves are ``fcs``, None when it has
    none: what its bones' share of the curves depends on (a renamed bone renames its curves' paths)."""
    try:
        ad = ob.animation_data
        return ad.action.as_pointer(), ad.action_slot.handle, len(fcs), tuple(ob.pose.bones.keys())
    except (AttributeError, ReferenceError):
        return None


def _skeleton_parts(ob, fcs, key):
    """{``pose.bones["n"]`` path: the indices in ``fcs`` (skeleton ``ob``'s curves) of that bone's curves}. A path
    names one bone, so its leading bone path is read once per curve and looked up. Kept for the skeleton's
    ``_skeleton_key`` ``key`` until the curves' keys are dropped (an Action update, a frame change, undo, redo, a
    file load)."""
    got = _PARTS.get(key) if key is not None else None
    if got is not None:
        return got
    parts = {}
    match = _BONE_PREFIX.match
    for i, fc in enumerate(fcs):
        path = fc.data_path
        m = match(path)
        if m is None:
            continue
        n = m.end()
        if len(path) > n and path[n] in ".[":
            parts.setdefault(path[:n], []).append(i)
    if key is not None:
        if len(_PARTS) > 64:
            _PARTS.clear()
        _PARTS[key] = parts
    return parts


def _bone_fcurves(bones, keep):
    """{pose bone pointer: its F-curves}; while playback or a drag runs (``keep``) a bone's curves are kept while its
    skeleton keeps its number of curves."""
    from ..operators import time_keys
    if not keep:
        return _bones_curves(bones)
    out, missing = {}, []
    for pb in bones:
        fcs = time_keys._cb()._fcurves(pb)
        key = len(fcs) if fcs is not None else -1
        got = _bone_curves.get(pb.as_pointer())
        if got is not None and got[0] == key:
            out[pb.as_pointer()] = got[1]
        else:
            missing.append((pb, key))
    if missing:
        found = _bones_curves([pb for pb, _key in missing])
        if len(_bone_curves) + len(missing) > 256:
            _bone_curves.clear()
        for pb, key in missing:
            out[pb.as_pointer()] = found[pb.as_pointer()]
            _bone_curves[pb.as_pointer()] = (key, found[pb.as_pointer()])
    return out


_BONE_KEYS = {}     # ``_skeleton_key`` -> {bone path: ([co arrays], [type arrays]) of its curves}, dropped with _KEYS


def _bones_keys(bones, cos, kinds):
    """Adds the ``_curve_keys`` arrays of the curves of pose bones ``bones`` (the curves ``_bones_curves`` shares
    out) to ``cos`` / ``kinds``. A bone's arrays are kept by its skeleton's ``_skeleton_key`` and its path,
    and dropped with the curves' keys (an Action update, a frame change, undo, redo, a file load): a new selection
    of bones whose keys were read takes one look per bone instead of finding each bone's curves and looking up
    every curve's keys (hundreds of selected controls of a rig with a thousand curves took milliseconds on every
    selection change)."""
    from ..operators import time_keys
    owners = {}
    for pb in bones:
        owners.setdefault(pb.id_data.as_pointer(), []).append(pb)
    escape = bpy.utils.escape_identifier
    for group in owners.values():
        first = group[0]
        fcs = time_keys._cb()._fcurves(first)
        if fcs is None:
            continue
        ob = first.id_data
        key = _skeleton_key(ob, fcs)
        held = None
        if key is not None:
            held = _BONE_KEYS.get(key)
            if held is None:
                if len(_BONE_KEYS) > 64:
                    _BONE_KEYS.clear()
                held = _BONE_KEYS[key] = {}
        missing = []
        for pb in group:
            # = time_keys.prefix(pb): a pose bone's path is its escaped name in pose.bones["..."]
            path = f'pose.bones["{escape(pb.name)}"]'
            got = held.get(path) if held is not None else None
            if got is None:
                missing.append(path)
            else:
                cos += got[0]
                kinds += got[1]
        if not missing:
            continue
        parts = _skeleton_parts(ob, fcs, key)
        # Blender finds the n-th curve of a slot by stepping through the n curves before it: several bones take
        # their curves from one list of the skeleton's curves
        seq = list(fcs) if len(missing) > 1 else fcs
        for path in missing:
            got = ([], [])
            for i in parts.get(path, ()):
                keys = _curve_keys(seq[i])
                if keys is not None:
                    got[0].append(keys[1])
                    got[1].append(keys[2])
            if held is not None:
                held[path] = got
            cos += got[0]
            kinds += got[1]


def key_frames(nodes, keep=False):
    """Sorted [(frame, is_breakdown)] of the nodes' keys; a frame with any regular key is a regular key. ``keep``:
    playback or a drag runs (the curves of a bone found once are used again). A curve's keys are read once until its
    Action changes or the frame does (``_curve_keys``); so are a bone's (``_bones_keys``)."""
    import numpy as np
    from . import cb_channels
    from ..operators import time_keys
    if not keep:
        _bone_curves.clear()
    # looked up once: bpy.types finds a type by its name on every access (bpy_rna.cc bpy_types_module_getattro)
    pose_bone, object_type = bpy.types.PoseBone, bpy.types.Object
    frames, cos, kinds = {}, [], []
    # Channel Box Sync Timeline Display: only the selected channels' keys (none selected / off: all keys)
    from . import channel_box
    if cb_channels.sync_timeline_on() and channel_box.selected_channels(bpy.context):
        plan = [(node, cb_channels.timeline_curves(bpy.context, node)) for node in nodes]
    else:
        plan = [(node, None) for node in nodes]
    pose_bones = [n for n, c in plan if c is None and isinstance(n, pose_bone)]
    if keep:
        bones = _bone_fcurves(pose_bones, keep)
    else:
        bones = None
        _bones_keys(pose_bones, cos, kinds)
    for node, curves in plan:
        if curves is None:
            if isinstance(node, pose_bone):
                if bones is None:
                    continue        # its keys are in cos already (_bones_keys)
                curves = bones[node.as_pointer()]
            elif isinstance(node, object_type) and node.animation_data is None:
                curves = []         # no curves and no animation layers of its own (thousands of selected props)
            else:
                curves = time_keys.node_fcurves(node)
                if isinstance(node, object_type):
                    # the shown layer's keys + BaseAnimation keys of channels not in that layer (Maya)
                    from ..operators import anim_layers
                    curves = list(curves) + anim_layers.hidden_base_curves(node, bpy.context.scene)
            if isinstance(node, object_type):
                curves = list(curves) + blend_weight_curves(node)
                # component mode: the keys of the selected points (vertices / CVs / lattice points)
                from ..operators import point_keys
                curves += point_keys.selected_point_curves(node)
        for fc in curves:
            got = _curve_keys(fc)
            if got is not None:
                cos.append(got[1])
                kinds.append(got[2])
    if not cos:
        return []
    # the keys of all curves at once: per distinct frame, is any key there a regular one. Two sorts of the frames
    # (all of them, the regular keys' ones) cost less than one sort that also maps every key to its frame.
    every = np.concatenate(cos)[0::2]
    raw = np.unique(every)
    regular = np.zeros(len(raw), bool)
    keyed = every[np.concatenate(kinds) != _breakdown_value()]
    regular[np.searchsorted(raw, np.unique(keyed))] = True     # a frame with any regular key
    for x, reg in zip(raw.tolist(), regular.tolist()):
        f = round(x, 3)
        frames[f] = frames.get(f, True) and not reg
    return sorted(frames.items())


_KEYS = {}      # F-curve pointer -> ``_curve_keys`` until an Action changes (``_drop_held``)
_KEYS_MAX = 50000


def _curve_keys(fc):
    """(key count, every key's (frame, value) co, every key's type) of the curve, None without keys: the keys' co and
    types in one read each per curve. Kept until a key is set, moved, retyped or deleted: Blender tags the curve's
    Action for that (its evaluated copy has to follow), so the next Action update drops them (``_drop_held``), as do
    a frame change (``_drop_keys``), undo, redo and a file load. A selection change keeps them: the keys of a new
    selection's bones are read once."""
    import numpy as np
    kps = fc.keyframe_points
    n = len(kps)
    if not n:
        return None
    ptr = fc.as_pointer()
    got = _KEYS.get(ptr)
    if got is not None and got[0] == n:
        return got
    # Blender's foreach_get fills a buffer of the property's own C type in one pass (a key's frame is a float, its
    # type one byte) and any other buffer one value at a time through Python objects (bpy_rna.cc
    # foreach_compat_buffer): float32 / uint8 read the same values in about half the time.
    co = np.empty(2 * n, np.float32)
    kps.foreach_get("co", co)
    kinds = np.empty(n, np.uint8)
    kps.foreach_get("type", kinds)
    if len(_KEYS) >= _KEYS_MAX:
        _KEYS.clear()
    got = _KEYS[ptr] = (n, co, kinds)
    return got


_BREAKDOWN = []     # the RNA value of a key's type 'BREAKDOWN'


def _breakdown_value():
    if not _BREAKDOWN:
        _BREAKDOWN.append(bpy.types.Keyframe.bl_rna.properties["type"].enum_items["BREAKDOWN"].value)
    return _BREAKDOWN[0]


def blend_weight_curves(ob):
    """Curves of the mesh's blendShape target weights (they live on its Key datablock, which the Channel Box lists
    under INPUTS): their keys are part of the object's ticks."""
    from . import channel_box
    from .. import compat
    bs = channel_box.blend_shape_key(ob)
    if bs is None:
        return []
    fcs = compat.id_fcurves(bs)
    if not fcs:
        return []           # no weight is keyed: the targets aren't listed
    paths = {channel_box.blend_path(kb.name) for kb in channel_box.blend_shape_targets(bs)}
    return [fc for fc in fcs if fc.data_path in paths]


def key_x(region, frame, maya):
    """Region x of a key tick: Maya draws it on the frame's tick, the left edge of the frame's cell;
    other timelines keep Blender's frame centre."""
    return region.view2d.view_to_region(frame - 0.5 if maya else frame, 0, clip=False)[0]


def _shows_keys(node):
    if not isinstance(node, bpy.types.Object):
        return True     # pose bones: only selected ones are listed
    if node.mode != 'OBJECT':
        return True     # edit / paint modes: the object whose components are being worked on
    try:
        return node.select_get()
    except RuntimeError:    # not in the view layer
        return False


def tick_nodes(context):
    """Nodes whose keys the Time Slider shows: the selected ones, like Maya (nothing selected = no ticks). Blender
    keeps an active object after it is deselected; its keys are not shown."""
    from . import channel_box
    object_type = bpy.types.Object      # looked up once (``key_frames``)
    return [n for n in channel_box.targets(context) if not isinstance(n, object_type) or _shows_keys(n)]


_HELD = {}      # region pointer -> its keys while a move or a time drag runs without playback (``_shown_keys``)


def _shown_keys(context, region):
    """``key_frames`` of the ticked nodes. While a move (Object / Pose Mode) or a time drag runs and playback doesn't,
    neither the selection nor the keys change until it ends — unless an animation editor's move drags keys, which
    updates their Action (``_drop_held``) — so the keys found once are drawn again (hundreds of selected bones were
    read again on every redraw of the drag). During playback a move can key (auto keying): read every time."""
    from .maya_joints import scrubbing, transforming
    playing = context.screen.is_animation_playing
    dragging = (context.mode in {'OBJECT', 'POSE'} and transforming()) or scrubbing()
    if playing or not dragging:
        _HELD.clear()
        return key_frames(tick_nodes(context), playing or dragging)
    ptr = region.as_pointer()
    got = _HELD.get(ptr)
    if got is None:
        if len(_HELD) > 16:
            _HELD.clear()
        got = _HELD[ptr] = key_frames(tick_nodes(context), True)
    return got


@persistent
def _drop_held(_scene, depsgraph=None):
    """Keys moved (their Action updated), undo, redo, a file load: the held keys and the curves' keys are read
    again."""
    if (_HELD or _KEYS or _PARTS or _BONE_KEYS) and (depsgraph is None or depsgraph.id_type_updated('ACTION')):
        _HELD.clear()
        _KEYS.clear()
        _PARTS.clear()
        _BONE_KEYS.clear()


@persistent
def _drop_keys(*_args):
    """A frame change evaluates what was tagged before it without a depsgraph update (a key set during playback
    would not reach ``_drop_held``): the curves' keys are read again on the next redraw."""
    _KEYS.clear()
    _PARTS.clear()
    _BONE_KEYS.clear()


def _draw_keys(context, region, maya=False):
    keys = _shown_keys(context, region)
    if not keys:
        return
    import gpu
    w = max(1.0, round(context.preferences.system.ui_scale or 1.0))
    h = region.height
    if maya:
        from ..operators import bookmarks
        if bookmarks.markers(context.scene):     # Maya: keys stay under the bookmark strip
            h = _rows("strip", h, ROWS_BOOKMARKS, context.preferences.system.ui_scale or 1.0)[0]
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    current = context.scene.frame_current
    for colour, breakdown in ((KEY_RGB, False), (BREAKDOWN_RGB, True)):
        tris = []
        for f, bd in keys:
            if bd != breakdown:
                continue
            x = key_x(region, f, maya)
            if x < -w or x > region.width + w:
                continue
            x0, x1 = int(x), int(x) + w
            if abs(f - current) < 0.5:
                # Blender draws its current-frame box over add-on drawing (the region's draw_overlay runs after
                # POST_PIXEL), and in the Maya layout that box fills the Time Slider: a key at the current frame
                # was invisible (issue #38). Maya shows it through its current-time block, one frame wide. Here the
                # key fills the current frame's cell: the box hides its middle and the rows above and below the
                # box stay red, while the ticks of the neighbouring frames stay visible.
                left, right = (region.view2d.view_to_region(f + d, 0, clip=False)[0] for d in (-0.5, 0.5))
                x0 = int(left)
                x1 = max(x0 + w, int(right))
            tris += [(x0, 0), (x1, 0), (x1, h), (x0, 0), (x1, h), (x0, h)]
        if tris:
            shader.uniform_float("color", colour)
            _tris_batch(shader, tris).draw(shader)


def blue_pencil_marks(region, frames, y0, scale):
    """Triangles (x, y) of Maya's Blue Pencil frame marks: one per frame, its upright edge ``MARK_GAP`` right of the
    frame's tick, standing on ``y0`` (the ticks' bottom end)."""
    from . import blue_pencil as bp
    w, h, gap = bp.MARK_W * scale, bp.MARK_H * scale, bp.MARK_GAP * scale
    tris = []
    for f in frames:
        x = round(region.view2d.view_to_region(f - 0.5, 0, clip=False)[0]) + gap
        if x + w < 0 or x > region.width:
            continue
        tris += [(x, y0), (x + w, y0), (x, y0 + h)]
    return tris


def _draw_blue_pencil(context, region):
    """Maya Time Slider: a light blue triangle on every Blue Pencil (annotation) frame (ui/blue_pencil.py)."""
    from . import blue_pencil as bp
    frames = bp.frame_numbers(context.scene)
    if not frames:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    from ..operators import bookmarks
    s = context.preferences.system.ui_scale or 1.0
    rows = ROWS_BOOKMARKS if bookmarks.markers(context.scene) else ROWS
    y0 = _rows("tick", region.height, rows, s)[0]
    k = min(region.height / MAYA_RULER_H, s)
    tris = blue_pencil_marks(region, frames, y0, k)
    if not tris:
        return
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    shader.uniform_float("color", bp.FRAME_RGB)
    batch_for_shader(shader, 'TRIS', {"pos": tris}).draw(shader)


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


@persistent
def _on_load(_dummy=None):
    _subscribe()   # file loading clears msgbus subscriptions
    _KEYS.clear()  # another file: other curves
    _PARTS.clear()
    _BONE_KEYS.clear()
    _HELD.clear()
    if not bpy.app.background:
        _schedule()


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


classes = (ALLSET_MT_anim_preferences, ALLSET_PT_time_slider, ALLSET_OT_time_scrub, ALLSET_OT_time_range_all,
           ALLSET_OT_time_range_drag, ALLSET_OT_time_slider_menu, ALLSET_OT_time_view_lock,
           ALLSET_OT_time_slider_unavailable, *TIME_SLIDER_MENUS)


# Maya's undo never moves the current time (a time change isn't an undo step there); Blender's memfile undo restores
# the scene's frame_current with everything else, so Ctrl+Z after scrubbing jumped back. The frame
# is put back from a 0 s timer, not inside undo_post (data written there before the next push is unsafe for redo).
_KEEP = {}


@persistent
def _keep_frame_pre(*_args):
    scene = bpy.context.scene
    if scene is not None:
        _KEEP["frame"] = (scene.name, scene.frame_current)


@persistent
def _keep_frame_post(*_args):
    if "frame" in _KEEP and not bpy.app.timers.is_registered(restore_frame):
        bpy.app.timers.register(restore_frame, first_interval=0.0)


def restore_frame():
    """Put the frame from before the undo / redo back (None: timer done)."""
    name, frame = _KEEP.pop("frame", (None, None))
    scene = bpy.context.scene
    if scene is not None and scene.name == name and scene.frame_current != frame:
        scene.frame_current = frame
    return None


_UNDO_HANDLERS = (("undo_pre", _keep_frame_pre), ("redo_pre", _keep_frame_pre),
                  ("undo_post", _keep_frame_post), ("redo_post", _keep_frame_post),
                  ("depsgraph_update_post", _drop_held), ("undo_post", _drop_held), ("redo_post", _drop_held),
                  ("frame_change_post", _drop_keys))


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    for name, fn in _UNDO_HANDLERS:
        getattr(bpy.app.handlers, name).append(fn)
    wm = bpy.types.WindowManager
    wm.allset_time_range_on = bpy.props.BoolProperty(
        name="Time Range", description="A Shift-dragged Time Slider range is highlighted", options={'SKIP_SAVE'})
    wm.allset_time_range = bpy.props.IntVectorProperty(name="Time Range", size=2, options={'SKIP_SAVE'})
    _draw_handle.append(bpy.types.SpaceDopeSheetEditor.draw_handler_add(_draw_range, (), 'WINDOW', 'POST_PIXEL'))
    buttons, menus = header_classes()
    orig_menus, orig_header = menus.draw_collapsible, buttons.draw_header   # bound class methods
    _ORIGINAL["draw_header"] = buttons.__dict__["draw_header"]

    def _menus_5(cls, context, layout):
        # Timeline mode: the menus live in ALLSET_MT_anim_preferences (Maya has no menus in the Range Slider)
        if not _is_timeline(context):
            return orig_menus(context, layout)

    def _header_5(cls, context, layout):
        if _is_timeline(context):
            return draw_header(context, layout)
        return orig_header(context, layout)
    menus.draw_collapsible = classmethod(_menus_5)
    buttons.draw_header = classmethod(_header_5)
    _subscribe()
    bpy.app.handlers.load_post.append(_on_load)


def unregister():
    for name, fn in _UNDO_HANDLERS:
        if fn in getattr(bpy.app.handlers, name):
            getattr(bpy.app.handlers, name).remove(fn)
    if bpy.app.timers.is_registered(restore_frame):
        bpy.app.timers.unregister(restore_frame)
    _KEEP.clear()
    _HELD.clear()
    _KEYS.clear()
    _PARTS.clear()
    _BONE_KEYS.clear()
    _TRIS.clear()
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    bpy.msgbus.clear_by_owner(_OWNER)
    if bpy.app.timers.is_registered(_deferred_fit):
        bpy.app.timers.unregister(_deferred_fit)
    _fitted.clear()
    buttons, menus = header_classes()
    if "draw_header" in _ORIGINAL:
        orig = _ORIGINAL.pop("draw_header")
        buttons.draw_header = orig
    if "draw_collapsible" in menus.__dict__:
        del menus.draw_collapsible
    while _draw_handle:
        bpy.types.SpaceDopeSheetEditor.draw_handler_remove(_draw_handle.pop(), 'WINDOW')
    wm = bpy.types.WindowManager
    del wm.allset_time_range
    del wm.allset_time_range_on
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
