# SPDX-License-Identifier: GPL-3.0-or-later
"""The Timeline header as Maya's Range Slider row (animation / playback start and end, range bar, auto key, character
set, anim layer, fps, loop, sound, animation preferences menu) and the Time Slider's current-frame field and transport
buttons (in the header, or in the sidebar panel ``ALLSET_PT_time_slider``). Entry points ``draw_header``,
``draw_range_slider``, ``row_plan``, ``has_slider_panel``; the range bar itself: ``range_bar``.
"""

import bpy

from .. import compat, i18n
from .time_slider_view import playback_range


def draw_transport(layout, context, field=4.5, icons=1.0):
    """Current frame field + the 8 Maya transport buttons (``field`` / ``icons``: a narrow row's sizes, row_layout)."""
    scene, screen = context.scene, context.screen
    if field > 0:
        row = layout.row()
        row.ui_units_x = field    # current time field width 90 px
        row.prop(scene, "frame_current", text="")
    row = layout.row(align=True)
    row.scale_x = icons
    row.operator("screen.frame_jump", text="", icon='REW').end = False
    row.operator("screen.frame_offset", text="", icon='TRIA_LEFT_BAR').delta = -1
    row.operator("allset.key_jump", text="", icon='PREV_KEYFRAME').next = False
    # allset.play: playback started from the viewport (ui/playback_redraw.py: the shelf isn't redrawn every frame)
    if screen.is_animation_playing:
        row.scale_x = 2 * icons
        row.operator("allset.play", text="", icon='PAUSE')
        row.scale_x = icons
    else:
        row.operator("allset.play", text="", icon='PLAY_REVERSE').reverse = True
        row.operator("allset.play", text="", icon='PLAY')
    row.operator("allset.key_jump", text="", icon='NEXT_KEYFRAME').next = True
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
# With the Time Slider's buttons in the same row (Blender 5.x) a narrow row (a small window, a large UI scale) still
# shows every control: once the optional items are gone and the bar is at its minimum, the four range fields and the
# current time field narrow to what their numbers need, then the icon buttons (8 transport + key, loop, sound,
# preferences) narrow a little.
FIELD_UNITS = 4.5            # a range field / the current time field
FIELD_FLOOR_UNITS = 1.8      # the narrowest field
FIELD_MARGIN_UNITS = 1.5     # a number field's text margins (its number shows whole only with them)
ROW_FIELDS = 4
ROW_ICONS = 12
ICON_FLOOR = 0.85            # icon buttons keep their icon whole (16 px x scale in a 20 px x scale button)


def field_floor(values, scale=1.0):
    """Narrowest field (ui units) that still shows the longest of these frame numbers whole at UI ``scale``."""
    from .layout_fit import text_px
    longest = max((str(int(v)) for v in values), key=len, default="000")
    return max(FIELD_FLOOR_UNITS, text_px(longest, scale) / (20.0 * scale) + FIELD_MARGIN_UNITS)


def row_layout(width_units, transport=False, floor=FIELD_FLOOR_UNITS):
    """(bar label units, names of the optional items shown, range field units, icon button scale, current time field
    units, 0 = not shown) for a Range Slider row ``width_units`` wide (``transport``: the current time field and the
    transport buttons are in the row too). The current time field goes last, on the narrowest rows only: the Time
    Slider shows the current frame too."""
    from . import range_bar
    shown = {name for name, _units in ROW_OPTIONAL}
    bar = width_units - ROW_CORE_UNITS - (ROW_TRANSPORT_UNITS if transport else 0.0) - sum(u for _n, u in ROW_OPTIONAL)
    for name, units in reversed(ROW_OPTIONAL):
        if bar >= ROW_MIN_BAR:
            break
        shown.discard(name)
        bar += units
    field, icons = FIELD_UNITS, 1.0
    clock = FIELD_UNITS if transport else 0.0
    if transport and bar < range_bar.MIN_BAR_UNITS:
        fields = ROW_FIELDS + 1
        field = max(min(floor, FIELD_UNITS), FIELD_UNITS - (range_bar.MIN_BAR_UNITS - bar) / fields)
        clock = field
        bar += (FIELD_UNITS - field) * fields
        if bar < range_bar.MIN_BAR_UNITS:
            icons = max(ICON_FLOOR, 1.0 - (range_bar.MIN_BAR_UNITS - bar) / ROW_ICONS)
            bar += (1.0 - icons) * ROW_ICONS
        if bar < range_bar.MIN_BAR_UNITS:
            bar += clock
            clock = 0.0
    bar = max(float(range_bar.MIN_BAR_UNITS), min(float(range_bar.BAR_UNITS), bar))
    return bar, shown, field, icons, clock


def row_plan(width_units, transport=False):
    """(bar label units, names of the optional items shown) for a Range Slider row ``width_units`` wide."""
    return row_layout(width_units, transport)[:2]


def _row_plan(context):
    region = context.region
    unit = 20.0 * (context.preferences.system.ui_scale or 1.0)
    width = region.width if region is not None and region.type == 'HEADER' else 0
    if width <= 0:
        from . import range_bar
        return float(range_bar.BAR_UNITS), {name for name, _u in ROW_OPTIONAL}, FIELD_UNITS, 1.0, FIELD_UNITS
    space, area, scene = context.space_data, context.area, context.scene
    scale = context.preferences.system.ui_scale or 1.0
    values = (scene.frame_start, scene.frame_end, scene.frame_current, *playback_range(scene))
    longest = max((str(int(v)) for v in values), key=len, default="000")
    transport = not has_slider_panel(space, area)
    # the header draws on every played frame and asks twice per draw: the row is worked out again only when its
    # width, the UI scale, where the buttons sit or the longest frame number changed
    key = (width, unit, scale, transport, longest, context.preferences.view.font_path_ui)
    got = _plans.get(key)
    if got is None:
        if len(_plans) > 32:
            _plans.clear()
        bar, shown, field, icons, clock = row_layout(width / unit, transport=transport,
                                                     floor=field_floor((longest,), scale))
        got = _plans[key] = (bar, frozenset(shown), field, icons, clock)
    return got


_plans = {}      # (header width, unit, UI scale, transport in the row, longest frame number, UI font) -> row_layout


def draw_header(context, layout):
    space, area = context.space_data, context.area
    if has_slider_panel(space) and not has_slider_panel(space, area):
        # Maya Workflow Kit layout whose sidebar can't open (Blender 5.x: the Timeline mode keeps its sidebar 1 px, even in a
        # factory file): one row, Range Slider first, the Time Slider buttons at the right end
        draw_range_slider(layout, context)
        layout.separator_spacer()
        _bar, _shown, _field, icons, clock = _row_plan(context)
        draw_transport(layout, context, clock, icons)
        return
    if not has_slider_panel(space, area):
        layout.separator_spacer()
        draw_transport(layout, context)
        layout.separator_spacer()
    draw_range_slider(layout, context)   # Maya: the range fields start at the left edge


def draw_range_slider(layout, context):
    scene = context.scene
    bar_units, shown, field, icons, _clock = _row_plan(context)
    # animation start | playback start [range bar] playback end | animation end
    # (the playback fields are the range that plays: ui/range_bar.py's allset_playback_start / _end)
    row = layout.row(align=True)
    row.ui_units_x = field
    row.prop(scene, "frame_start", text="")
    row = layout.row(align=True)
    row.ui_units_x = field
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
    row.ui_units_x = field
    row.prop(scene, "allset_playback_end", text="")
    row = layout.row(align=True)
    row.ui_units_x = field
    row.prop(scene, "frame_end", text="")

    layout.separator_spacer()
    row = layout.row(align=True)
    row.scale_x = icons
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
    row.scale_x = icons
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
        lay.popover(panel=compat.keying_popover(), text="Keying")
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
