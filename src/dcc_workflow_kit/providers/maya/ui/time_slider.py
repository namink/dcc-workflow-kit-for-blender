# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Maya Time Slider + Range Slider in the Timeline header, and a timeline view that
follows the playback range.

Maya's Time Slider (8 transport buttons, current time
field, auto key) and Range Slider (animation start, playback start, [range], playback end,
animation end). Blender form (docs/steps/step_20.md 「계획」 2, 4):
- ``bl_ui.space_time.TIME_HT_editor_buttons.draw_header`` (a plain class, not in bpy.types)
  is swapped for ``draw_header`` below and restored on unregister.
- Maya's animation range = scene frame_start/end; its playback range = the preview range
  (``use_preview_range`` off: playback = animation range, inner fields greyed).
- Maya's time slider always shows the playback range: after a file load and whenever the
  range changes, every Timeline runs ``anim.scene_range_frame`` (a msgbus subscription and
  a load_post handler defer it to a timer).
- Step 56 (docs/steps/step_56.md 「계획」 1, 2, 5): LMB on the timeline = time (Shift = red range), RMB = Maya's
  Time Slider menu, MMB = time + a notice (no Maya MMB time drag in Blender).
- Step 50 (docs/steps/step_50.md 「계획」 4): the
  header is the Range Slider row in Maya's order; Blender's Playback / Keying / View / Marker menus move
  into the animation preferences menu at its right end (``TIME_MT_editor_menus.draw_collapsible`` is
  overridden on the class, deleted on unregister). A timeline with its sidebar shown (the Maya Workflow Kit
  layout) draws the current frame field and the 8 transport buttons there, at the right end of the
  Time Slider row like Maya (``ALLSET_PT_time_slider``); other timelines keep them in the header.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
from .. import results
from .. import compat
from bpy.app.handlers import persistent
LEGACY_TIMELINE = compat.LEGACY_TIMELINE
header_classes = compat.timeline_header_classes

def _is_timeline(context):
    space = getattr(context, 'space_data', None)
    return space is not None and getattr(space, 'mode', None) == 'TIMELINE'
_ORIGINAL = {}
_OWNER = object()
_RANGE_PROPS = ('frame_start', 'frame_end', 'frame_preview_start', 'frame_preview_end', 'use_preview_range')

def draw_transport(layout, context):
    """Current frame field + Maya's 8 transport buttons."""
    (scene, screen) = (context.scene, context.screen)
    row = layout.row()
    row.ui_units_x = 4.5
    row.prop(scene, 'frame_current', text=_dcc_display(''))
    row = layout.row(align=True)
    row.operator('screen.frame_jump', text=_dcc_display(''), icon='REW').end = False
    row.operator('screen.frame_offset', text=_dcc_display(''), icon='TRIA_LEFT_BAR').delta = -1
    row.operator('screen.keyframe_jump', text=_dcc_display(''), icon='PREV_KEYFRAME').next = False
    if screen.is_animation_playing:
        row.scale_x = 2
        row.operator('screen.animation_play', text=_dcc_display(''), icon='PAUSE')
        row.scale_x = 1
    else:
        row.operator('screen.animation_play', text=_dcc_display(''), icon='PLAY_REVERSE').reverse = True
        row.operator('screen.animation_play', text=_dcc_display(''), icon='PLAY')
    row.operator('screen.keyframe_jump', text=_dcc_display(''), icon='NEXT_KEYFRAME').next = True
    row.operator('screen.frame_offset', text=_dcc_display(''), icon='TRIA_RIGHT_BAR').delta = 1
    row.operator('screen.frame_jump', text=_dcc_display(''), icon='FF').end = True

def has_slider_panel(space, area=None):
    """The timeline shows the Time Slider buttons in its sidebar (the Maya Workflow Kit layout). With ``area``, the
    sidebar must also have room: Blender 5.x loads the 4.5 template's timeline sidebar 1 px wide
    (docs/steps/step_53.md), and then the buttons stay in the header."""
    if space is None or space.type != 'DOPESHEET_EDITOR' or (not space.show_region_ui):
        return False
    if area is None:
        return True
    ui = next((r for r in area.regions if r.type == 'UI'), None)
    return ui is not None and ui.width > 20
RANGE_ITEMS = ('start', 'playback start', 'range', 'playback end', 'end', 'auto key', _dcc_source('No Character Set'), _dcc_source('No Anim Layer'), 'fps', 'loop', 'sound', 'animation preferences')

def draw_header(context, layout):
    (space, area) = (context.space_data, context.area)
    if has_slider_panel(space) and (not has_slider_panel(space, area)):
        draw_range_slider(layout, context)
        layout.separator_spacer()
        draw_transport(layout, context)
        return
    if not has_slider_panel(space, area):
        layout.separator_spacer()
        draw_transport(layout, context)
        layout.separator_spacer()
    draw_range_slider(layout, context)

def draw_range_slider(layout, context):
    scene = context.scene
    row = layout.row(align=True)
    row.ui_units_x = 4.5
    row.prop(scene, 'frame_start', text=_dcc_display(''))
    row = layout.row(align=True)
    row.ui_units_x = 4.5
    row.active = scene.use_preview_range
    row.prop(scene, 'frame_preview_start', text=_dcc_display(''))
    from . import range_bar
    bar = layout.row(align=True)
    bar.ui_units_x = range_bar.BAR_UNITS
    if range_bar.active(context):
        bar.label(text=_dcc_display(''))
    else:
        (a, b) = (scene.frame_preview_start, scene.frame_preview_end) if scene.use_preview_range else (scene.frame_start, scene.frame_end)
        bar.prop(scene, 'use_preview_range', text=_dcc_display(''), toggle=True, icon='PREVIEW_RANGE')
        bar.operator('anim.scene_range_frame', text=_zh(f'{a}' + ' ' * 40 + f'{b}', 'MWK:ui/time_slider.py:125'))
    row = layout.row(align=True)
    row.ui_units_x = 4.5
    row.active = scene.use_preview_range
    row.prop(scene, 'frame_preview_end', text=_dcc_display(''))
    row = layout.row(align=True)
    row.ui_units_x = 4.5
    row.prop(scene, 'frame_end', text=_dcc_display(''))
    layout.separator_spacer()
    row = layout.row(align=True)
    on = getattr(scene, 'allset_auto_key', False)
    key = row.row(align=True)
    key.alert = on
    key.prop(scene, 'allset_auto_key', text=_dcc_display(''), toggle=True, icon='KEY_HLT' if on else 'KEY_DEHLT')
    from ..operators import anim_layers
    ls = getattr(context.scene, 'allset_anim_layers', ())
    sel = anim_layers.selected(context.scene) if len(ls) > 1 else None
    ks = scene.keying_sets.active
    sub = layout.row()
    sub.ui_units_x = 6
    sub.menu('ALLSET_MT_character_set_current', text=_zh(ks.bl_label if ks is not None else 'No Character Set', 'MWK:ui/time_slider.py:152'), icon='DOWNARROW_HLT')
    for (text, on) in ((sel.name if sel is not None else _dcc_source('No Anim Layer'), sel is not None),):
        sub = layout.row()
        sub.enabled = on
        sub.ui_units_x = 6
        sub.label(text=_zh(text, 'MWK:ui/time_slider.py:158'), icon='DOWNARROW_HLT')
    row = layout.row()
    row.ui_units_x = 5
    fps = scene.render.fps / scene.render.fps_base
    row.menu('RENDER_MT_framerate_presets', text=_zh(f'{fps:g} fps', 'MWK:ui/time_slider.py:162'))
    row = layout.row(align=True)
    sub = row.row(align=True)
    sub.enabled = False
    sub.label(text=_dcc_display(''), icon='FILE_REFRESH')
    row.prop(scene, 'use_audio', text=_dcc_display(''), icon='SPEAKER', invert_checkbox=True)
    row.menu('ALLSET_MT_anim_preferences', text=_dcc_display(''), icon='PREFERENCES')

class ALLSET_MT_anim_preferences(bpy.types.Menu):
    """Animation preferences (Maya's button at the right end of the Range Slider): Blender's
    timeline Playback, Keying, View and Marker menus"""
    bl_translation_context = 'MWK:ui/time_slider.py:174'
    bl_label = _zh_native('Animation Preferences', 'MWK:ui/time_slider.py:174')

    def draw(self, context):
        lay = self.layout
        lay.popover(panel='TIME_PT_playback', text=_zh('Playback', 'MWK:ui/time_slider.py:178'))
        lay.popover(panel='TIME_PT_keyframing_settings', text=_zh('Keying', 'MWK:ui/time_slider.py:179'))
        lay.separator()
        lay.menu('TIME_MT_view', text=_zh('View', 'MWK:ui/time_slider.py:181'))
        lay.menu(compat.timeline_marker_menu(), text=_zh('Marker', 'MWK:ui/time_slider.py:182'))

class ALLSET_PT_time_slider(bpy.types.Panel):
    """Current time field and transport buttons at the right of Maya's Time Slider."""
    bl_translation_context = 'MWK:ui/time_slider.py:189'
    bl_space_type = 'DOPESHEET_EDITOR'
    bl_region_type = 'UI'
    bl_label = _zh_native('Time Slider', 'MWK:ui/time_slider.py:189')
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and space.mode == 'TIMELINE'

    def draw(self, context):
        draw_transport(self.layout.row(align=False), context)

def _no_editor_menus(cls, context, layout):
    """TIME_MT_editor_menus.draw_collapsible while the kit is on: the menus live in
    ALLSET_MT_anim_preferences (Maya has no menus in the Range Slider)."""
RANGE_COLOR = (0.78, 0.16, 0.16, 0.35)
RANGE_ARROW_COLOR = (1.0, 1.0, 1.0, 0.9)
MMB_NOTICE = _dcc_source('Blender always updates the scene when the time changes (no Maya MMB time drag): copy keys instead (RMB > Copy, move, RMB > Paste).')
TIME_NOTICES = {_dcc_source('Paste Connect'): _dcc_source('Blender pastes keys as they were copied: no connect (offset) paste.'), _dcc_source('Play Every Frame, Free'): _dcc_source('Blender never plays faster than the scene frame rate.'), _dcc_source('Once'): _dcc_source('Blender playback always loops.'), _dcc_source('Oscillate'): _dcc_source('Blender playback always loops.'), _dcc_source('Enabled Clips'): _dcc_source('Blender has no Time Editor clips (NLA strips instead).'), _dcc_source('Sound Length'): _dcc_source("Use the sound strip's length in the Video Sequencer.")}

def frame_at(region, x):
    """Whole frame under window x in a timeline WINDOW region."""
    return int(round(region.view2d.region_to_view(x - region.x, 0)[0]))

def set_range(wm, a, b, on=True):
    wm.allset_time_range = (int(a), int(b))
    wm.allset_time_range_on = on

class ALLSET_OT_time_scrub(bpy.types.Operator):
    """Maya Time Slider: click or drag to move the time (Shift: highlight a range)"""
    bl_translation_context = 'MWK:ui/time_slider.py:240'
    bl_idname = 'allset.time_scrub'
    bl_label = _zh_native('Time Slider Scrub', 'MWK:ui/time_slider.py:240')
    bl_description = _zh_native('Maya Time Slider: click or drag to move the time (Shift: highlight a range)', 'MWK:ui/time_slider.py:240')
    bl_options = {'INTERNAL'}
    range: bpy.props.BoolProperty(name=_zh_native('Range', 'MWK:ui/time_slider.py:243'), description=_zh_native('Shift-drag: highlight a time range', 'MWK:ui/time_slider.py:243'), options={'SKIP_SAVE'}, translation_context='MWK:ui/time_slider.py:243')
    notice: bpy.props.BoolProperty(name=_zh_native('Notice', 'MWK:ui/time_slider.py:245'), description=_zh_native('Show the MMB time drag notice', 'MWK:ui/time_slider.py:245'), options={'SKIP_SAVE'}, translation_context='MWK:ui/time_slider.py:245')

    def invoke(self, context, event):
        region = context.region
        if not _is_timeline(context) or region is None or region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        self._region = region
        self._button = event.type
        (wm, scene) = (context.window_manager, context.scene)
        self._old = (scene.frame_current, tuple(wm.allset_time_range), wm.allset_time_range_on)
        f = frame_at(region, event.mouse_x)
        if self.range:
            self._anchor = f
            set_range(wm, f, f)
        else:
            wm.allset_time_range_on = False
            scene.frame_current = f
        if self.notice:
            from . import notices
            notices.show(MMB_NOTICE)
        _tag(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        (wm, scene) = (context.window_manager, context.scene)
        if event.type == 'MOUSEMOVE':
            f = frame_at(self._region, event.mouse_x)
            if self.range:
                set_range(wm, self._anchor, f)
            elif f != scene.frame_current:
                scene.frame_current = f
            _tag(context)
            return {'RUNNING_MODAL'}
        if event.type == self._button and event.value == 'RELEASE':
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            scene.frame_current = self._old[0]
            set_range(wm, *self._old[1], on=self._old[2])
            _tag(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}
RANGE_EDGE_PX = 8

def range_zone(context, region, x):
    """'LEFT' / 'RIGHT' / 'MOVE' when window x is on the highlighted range of this timeline, else None."""
    from ..operators import time_range
    wm = context.window_manager
    if not getattr(wm, 'allset_time_range_on', False):
        return None
    (x0, x1) = range_rect(region, *wm.allset_time_range)
    edge = RANGE_EDGE_PX * (context.preferences.system.ui_scale or 1.0)
    return time_range.zone(x - region.x, x0, x1, edge)

class ALLSET_OT_time_range_drag(bpy.types.Operator):
    """Maya Time Slider range: drag the middle to move its keys, an end arrow to scale them"""
    bl_translation_context = 'MWK:ui/time_slider.py:307'
    bl_idname = 'allset.time_range_drag'
    bl_label = _zh_native('Move / Scale Range Keys', 'MWK:ui/time_slider.py:307')
    bl_description = _zh_native('Maya Time Slider range: drag the middle to move its keys, an end arrow to scale them', 'MWK:ui/time_slider.py:307')
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
        (a, b) = sorted(wm.allset_time_range)
        (curves, seen) = ([], set())
        for node in time_keys.nodes(context):
            for fc in time_keys.node_fcurves(node):
                if fc.as_pointer() in seen:
                    continue
                seen.add(fc.as_pointer())
                idx = [i for (i, kp) in enumerate(fc.keyframe_points) if time_keys._in(kp, a, b)]
                if idx:
                    curves.append((fc, idx))
        self._drag = time_range.Drag(curves, a, b)
        (self._region, self._mode, self._range) = (region, 'MOVE' if a == b else mode, (a, b))
        self._f0 = frame_at(region, event.mouse_x)
        (self._f, self._moved) = (self._f0, False)
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
        (wm, scene) = (context.window_manager, context.scene)
        if event.type == 'MOUSEMOVE':
            f = frame_at(self._region, event.mouse_x)
            if abs(event.mouse_x - self._x0) >= 3:
                self._moved = True
            if self._moved and f != self._f:
                self._update(context, f)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if not self._moved:
                wm.allset_time_range_on = False
                scene.frame_current = self._f0
                _tag(context)
                return {'CANCELLED'}
            n = self._drag.finish(self._mode, self._f0, self._f)
            scene.frame_set(scene.frame_current)
            results.result(self, _zh(f"{('Moved' if self._mode == 'MOVE' else 'Scaled')} {n} key(s)", 'MWK:ui/time_slider.py:366'))
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
    bl_translation_context = 'MWK:ui/time_slider.py:386'
    bl_idname = 'allset.time_slider_menu'
    bl_label = _zh_native('Time Slider Menu', 'MWK:ui/time_slider.py:386')
    bl_description = _zh_native('Maya Time Slider menu (RMB on the Time Slider)', 'MWK:ui/time_slider.py:386')
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if not _is_timeline(context):
            return {'PASS_THROUGH'}
        bpy.ops.wm.call_menu(name=ALLSET_MT_time_slider.__name__)
        return {'FINISHED'}

class ALLSET_OT_time_slider_unavailable(bpy.types.Operator):
    """Time Slider item with no Blender equivalent (greyed)"""
    bl_translation_context = 'MWK:ui/time_slider.py:399'
    bl_idname = 'allset.time_slider_unavailable'
    bl_label = _zh_native('Not Available', 'MWK:ui/time_slider.py:399')
    bl_description = _zh_native('Time Slider item with no Blender equivalent (greyed)', 'MWK:ui/time_slider.py:399')
    bl_options = {'INTERNAL'}
    item: bpy.props.StringProperty(options={'SKIP_SAVE'}, translation_context='MWK:ui/time_slider.py:402')

    @classmethod
    def poll(cls, context):
        return False

    @classmethod
    def description(cls, context, props):
        line = TIME_NOTICES.get(props.item, '')
        if line:
            from . import notices
            notices.show(f'{props.item}: {line}')
        return _zh(f'Maya: Time Slider > {props.item}\n{line}', 'MWK:ui/time_slider.py:414')

    def execute(self, context):
        return {'CANCELLED'}

def _keys(layout, action, text=None, **props):
    op = layout.operator('allset.time_keys', text=_zh(text, 'MWK:ui/time_slider.py:421'))
    op.action = action
    for (k, v) in props.items():
        setattr(op, k, v)
    return op

def _grey(layout, label):
    layout.operator(ALLSET_OT_time_slider_unavailable.bl_idname, text=_zh(label, 'MWK:ui/time_slider.py:429')).item = label

class ALLSET_MT_time_slider(bpy.types.Menu):
    """Maya Time Slider menu, in Maya's order"""
    bl_translation_context = 'MWK:ui/time_slider.py:434'
    bl_label = _zh_native('Time Slider', 'MWK:ui/time_slider.py:434')

    def draw(self, context):
        lay = self.layout
        _keys(lay, 'CUT', _dcc_source('Cut'))
        _keys(lay, 'COPY', _dcc_source('Copy'))
        lay.menu('ALLSET_MT_time_slider_paste', text=_zh('Paste', 'MWK:ui/time_slider.py:440'))
        _keys(lay, 'DELETE', _dcc_source('Delete'))
        _keys(lay, 'SNAP', _dcc_source('Snap'))
        lay.menu('ALLSET_MT_time_slider_keys', text=_zh('Keys', 'MWK:ui/time_slider.py:443'))
        lay.menu('ALLSET_MT_time_slider_tangents', text=_zh('Tangents', 'MWK:ui/time_slider.py:444'))
        lay.separator()
        lay.menu('ALLSET_MT_time_slider_speed', text=_zh('Playback Speed', 'MWK:ui/time_slider.py:446'))
        lay.menu('ALLSET_MT_time_slider_looping', text=_zh('Playback Looping', 'MWK:ui/time_slider.py:447'))
        lay.menu('ALLSET_MT_time_slider_range', text=_zh('Set Range to', 'MWK:ui/time_slider.py:448'))
        lay.separator()
        op = lay.operator('allset.menu_run', text=_zh('Playblast...', 'MWK:ui/time_slider.py:450'))
        (op.op, op.props) = ('render.opengl', '{"animation": true}')

class ALLSET_MT_time_slider_paste(bpy.types.Menu):
    bl_translation_context = 'MWK:ui/time_slider.py:455'
    bl_label = _zh_native('Paste', 'MWK:ui/time_slider.py:455')

    def draw(self, context):
        _keys(self.layout, 'PASTE', _dcc_source('Paste'))
        _grey(self.layout, _dcc_source('Paste Connect'))

class ALLSET_MT_time_slider_keys(bpy.types.Menu):
    bl_translation_context = 'MWK:ui/time_slider.py:463'
    bl_label = _zh_native('Keys', 'MWK:ui/time_slider.py:463')

    def draw(self, context):
        for (action, label) in (('TO_KEY', _dcc_source('Convert to Key')), ('TO_BREAKDOWN', _dcc_source('Convert to Breakdown')), ('ADD_INBETWEEN', _dcc_source('Add Inbetween')), ('REMOVE_INBETWEEN', _dcc_source('Remove Inbetween'))):
            _keys(self.layout, action, label)

class ALLSET_MT_time_slider_tangents(bpy.types.Menu):
    bl_translation_context = 'MWK:ui/time_slider.py:472'
    bl_label = _zh_native('Tangents', 'MWK:ui/time_slider.py:472')

    def draw(self, context):
        for kind in ('SPLINE', 'LINEAR', 'CLAMPED', 'STEPPED', 'FLAT', 'PLATEAU', 'AUTO'):
            _keys(self.layout, 'TANGENT', kind.title(), tangent=kind)

class ALLSET_MT_time_slider_speed(bpy.types.Menu):
    bl_translation_context = 'MWK:ui/time_slider.py:480'
    bl_label = _zh_native('Playback Speed', 'MWK:ui/time_slider.py:480')

    def draw(self, context):
        lay = self.layout
        lay.prop_enum(context.scene, 'sync_mode', 'FRAME_DROP', text=_zh('Real-time', 'MWK:ui/time_slider.py:484'))
        _grey(lay, _dcc_source('Play Every Frame, Free'))
        lay.prop_enum(context.scene, 'sync_mode', 'NONE', text=_zh('Play Every Frame, Max Real-time', 'MWK:ui/time_slider.py:486'))

class ALLSET_MT_time_slider_looping(bpy.types.Menu):
    bl_translation_context = 'MWK:ui/time_slider.py:490'
    bl_label = _zh_native('Playback Looping', 'MWK:ui/time_slider.py:490')

    def draw(self, context):
        lay = self.layout
        _grey(lay, _dcc_source('Once'))
        _grey(lay, _dcc_source('Oscillate'))
        lay.label(text=_zh('Continuous', 'MWK:ui/time_slider.py:496'), icon='CHECKMARK')

class ALLSET_MT_time_slider_range(bpy.types.Menu):
    bl_translation_context = 'MWK:ui/time_slider.py:500'
    bl_label = _zh_native('Set Range to', 'MWK:ui/time_slider.py:500')

    def draw(self, context):
        lay = self.layout
        for (mode, label) in (('START_END', _dcc_source('Start/End')), ('MIN_MAX', _dcc_source('Min/Max')), ('SELECTED', _dcc_source('Selected'))):
            lay.operator('allset.time_set_range', text=_zh(label, 'MWK:ui/time_slider.py:505')).mode = mode
        _grey(lay, _dcc_source('Enabled Clips'))
        _grey(lay, _dcc_source('Sound Length'))
TIME_SLIDER_MENUS = (ALLSET_MT_time_slider, ALLSET_MT_time_slider_paste, ALLSET_MT_time_slider_keys, ALLSET_MT_time_slider_tangents, ALLSET_MT_time_slider_speed, ALLSET_MT_time_slider_looping, ALLSET_MT_time_slider_range)
_draw_handle = []

def range_rect(region, a, b):
    """Window-region x0, x1 of frames a..b (whole frames: half a frame either side)."""
    (lo, hi) = (min(a, b) - 0.5, max(a, b) + 0.5)
    x0 = region.view2d.view_to_region(lo, 0, clip=False)[0]
    x1 = region.view2d.view_to_region(hi, 0, clip=False)[0]
    return (x0, x1)

def _draw_range():
    context = bpy.context
    wm = context.window_manager
    if not _is_timeline(context):
        return
    region = context.region
    maya = has_slider_panel(context.space_data)
    if maya:
        _draw_ruler(context, region)
    _draw_keys(context, region, maya)
    if not getattr(wm, 'allset_time_range_on', False):
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    (x0, x1) = range_rect(region, *wm.allset_time_range)
    h = region.height
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {'pos': ((x0, 0), (x1, 0), (x1, h), (x0, 0), (x1, h), (x0, h))})
    gpu.state.blend_set('ALPHA')
    shader.uniform_float('color', RANGE_COLOR)
    batch.draw(shader)
    edge = RANGE_EDGE_PX * (context.preferences.system.ui_scale or 1.0)
    k = min(edge * 0.6, h * 0.25)
    y = h * 0.5
    tris = []

    def arrow(cx, d):
        tris.extend(((cx - d * k * 0.5, y), (cx + d * k * 0.5, y + k * 0.6), (cx + d * k * 0.5, y - k * 0.6)))
    cx = (x0 + x1) * 0.5
    if x1 - x0 >= 3 * edge:
        arrow(x0 + edge * 0.5, 1)
        arrow(x1 - edge * 0.5, -1)
    arrow(cx - k * 0.55, 1)
    arrow(cx + k * 0.55, -1)
    batch = batch_for_shader(shader, 'TRIS', {'pos': tris})
    shader.uniform_float('color', RANGE_ARROW_COLOR)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
MAYA_RULER_H = 32.0
RULER_BG = (43 / 255, 43 / 255, 43 / 255, 1.0)
RULER_BAND = (55 / 255, 55 / 255, 55 / 255, 1.0)
RULER_TICK = (124 / 255, 124 / 255, 124 / 255, 1.0)
RULER_LABEL = (117 / 255, 117 / 255, 117 / 255, 1.0)
RULER_CURRENT = (1.0, 1.0, 1.0, (82 - 43) / (255 - 43))
RULER_CURRENT_LABEL = (1.0, 1.0, 1.0, 1.0)
ROWS = {'label': (1, 8), 'tick': (13, 27), 'current_label': (16, 23), 'band': (29, 31)}
ROWS_BOOKMARKS = {'label': (11, 18), 'tick': (23, 27), 'current_label': (19, 26), 'band': (29, 31), 'strip': (0, 8), 'bookmark': (0, 4)}
BOOKMARK_STRIP = (69 / 255, 69 / 255, 69 / 255, 1.0)
BOOKMARK_RGB = (204 / 255, 92 / 255, 92 / 255)
TICK_PX = 2.0
RULER_FONT_SIZE = 8.0 / 0.72
NICE_STEPS = tuple((m * 10 ** e for e in range(8) for m in (1, 2, 5)))
STEP_MATCHES = 32
STEP_DEVIATIONS = ((1292, 1, 10000), (692, 1, 120), (1592, 1, 120), (1592, 1, 60), (1292, 1, 215), (1292, 1, 230), (1292, 1, 250), (1292, 1001, 1100), (1292, 1, 100000), (692, 1, 130), (692, 1, 110))

def label_digits(frame):
    return len(str(abs(int(frame)))) + (1 if frame < 0 else 0)

def label_need_px(digits):
    """Spacing (px at UI scale 1) Maya needs between two labels of ``digits`` characters (fitted to the 1292 px
    widget cases: <= 3 digits fit at 25.6 px but not 24.7, 4 digits need more than 25.6 and fit at 32, 5 digits
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
TICK_HALF_PAD = 2.33

def _rows(name, h, rows=None, scale=1.0):
    """(y0, y1) region rows (bottom-up) of a ruler row band at region height ``h``, UI-scaled: the label rows keep
    their place under the top edge, the band and the current frame number theirs above the bottom edge, and the
    ticks grow Maya's way (``TICK_HALF_PAD``)."""
    rows = rows or ROWS
    (top, bottom) = rows[name]
    k = min(h / MAYA_RULER_H, scale)
    if name == 'tick':
        y0 = (MAYA_RULER_H - bottom - 1) * k
        normal = (bottom + 1 - top) * k
        label_low = h - (rows['label'][1] + 1) * k
        half = (label_low - y0) / 2 - TICK_HALF_PAD * k
        return (y0, y0 + max(normal, half))
    if name in ('band', 'current_label'):
        return ((MAYA_RULER_H - bottom - 1) * k, (MAYA_RULER_H - top) * k)
    return (h - (bottom + 1) * k, h - top * k)

def _draw_ruler(context, region):
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader
    scene = context.scene
    s = context.preferences.system.ui_scale or 1.0
    (w, h) = (region.width, region.height)
    v2d = region.view2d

    def x_of(f):
        return v2d.view_to_region(f, 0, clip=False)[0]
    pxf = x_of(1.0) - x_of(0.0)
    if pxf <= 0:
        return
    (start, end) = playback_range(scene)
    step = tick_step(start, end, pxf, s)
    (lo, hi) = (v2d.region_to_view(0, 0)[0], v2d.region_to_view(w, 0)[0])
    frames = ruler_ticks(step, lo, hi)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')

    def rects(rs, colour):
        tris = []
        for (x0, y0, x1, y1) in rs:
            tris += [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]
        if tris:
            shader.uniform_float('color', colour)
            batch_for_shader(shader, 'TRIS', {'pos': tris}).draw(shader)
    from ..operators import bookmarks
    marks = bookmarks.markers(scene)
    rows = ROWS_BOOKMARKS if marks else ROWS
    gpu.state.blend_set('ALPHA')
    rects([(0, 0, w, h)], RULER_BG)
    (b0, b1) = _rows('band', h, rows, s)
    rects([(0, b0, w, b1)], RULER_BAND)
    if marks:
        (s0, s1) = _rows('strip', h, rows, s)
        rects([(0, s0, w, s1)], BOOKMARK_STRIP)
        (m0, m1) = _rows('bookmark', h, rows, s)
        (bars, edges) = ([], [])
        for m in marks:
            (a, b) = bookmarks.bookmark_range(scene, m)
            (x0, x1) = (round(x_of(a - 0.5)), round(x_of(b + 0.5)))
            bars.append((x0, m0, x1, m1))
            edges.append((x0, s0, x0 + max(1.0, round(s)), s1))
        rects(bars, (*BOOKMARK_RGB, 0.8))
        rects(edges, (*BOOKMARK_RGB, 1.0))
    tw = max(1.0, round(TICK_PX * s))
    (t0, t1) = _rows('tick', h, rows, s)
    lefts = {f: round(x_of(f - 0.5)) for f in frames}
    rects([(x, t0, x + tw, t1) for x in lefts.values()], RULER_TICK)
    cur = scene.frame_current
    (cx0, cx1) = (x_of(cur - 0.5), x_of(cur + 0.5))
    rects([(round(cx0), 0, max(round(cx0) + 1, round(cx1)), h)], RULER_CURRENT)
    (l0, _l1) = _rows('label', h, rows, s)
    blf.size(0, RULER_FONT_SIZE * s)
    off = 2 * s + 0.2 * pxf
    blf.color(0, *RULER_LABEL)
    for (f, x) in lefts.items():
        blf.position(0, x + off, l0, 0)
        blf.draw(0, _dcc_display(_zh(str(f), 'MWK:ui/time_slider.py:729')))
    (c0, _c1) = _rows('current_label', h, rows, s)
    blf.color(0, *RULER_CURRENT_LABEL)
    blf.position(0, round(cx0) + off, c0, 0)
    blf.draw(0, _dcc_display(_zh(str(cur), 'MWK:ui/time_slider.py:733')))
    gpu.state.blend_set('NONE')

def playback_range(scene):
    """Maya playback range = the preview range when on, else the scene range (module docstring)."""
    if scene.use_preview_range:
        return (scene.frame_preview_start, scene.frame_preview_end)
    return (scene.frame_start, scene.frame_end)
KEY_RGB = (1.0, 0.0, 0.0, 1.0)
BREAKDOWN_RGB = (0.0, 1.0, 0.0, 1.0)

def key_frames(nodes):
    """Sorted [(frame, is_breakdown)] of the nodes' keys; a frame with any regular key is a regular key."""
    from ..operators import time_keys
    from . import cb_channels
    frames = {}
    for node in nodes:
        curves = cb_channels.timeline_curves(bpy.context, node)
        if curves is None:
            curves = time_keys.node_fcurves(node)
            if isinstance(node, bpy.types.Object):
                from ..operators import anim_layers
                curves = list(curves) + anim_layers.hidden_base_curves(node, bpy.context.scene)
        for fc in curves:
            for kp in fc.keyframe_points:
                f = round(kp.co.x, 3)
                frames[f] = frames.get(f, True) and kp.type == 'BREAKDOWN'
    return sorted(frames.items())

def playhead_half_width(context, frame):
    """Half the width of Blender's current-frame box on the scrub row (time_scrub_ui.cc ``draw_current_frame``:
    max(text width + 8, 24) x UI scale, the frame number in the widget font)."""
    import blf
    s = context.preferences.system.ui_scale or 1.0
    try:
        points = context.preferences.ui_styles[0].widget.points
    except (AttributeError, IndexError):
        points = 11
    blf.size(0, points * s)
    text_w = blf.dimensions(0, _dcc_display(_zh(str(int(frame)), 'MWK:ui/time_slider.py:782')))[0]
    return max(text_w + 8 * s, 24 * s) / 2

def key_x(region, frame, maya):
    """Region x of a key tick: Maya draws it on the frame's tick, the left edge of the frame's cell (step 186);
    other timelines keep Blender's frame centre."""
    return region.view2d.view_to_region(frame - 0.5 if maya else frame, 0, clip=False)[0]

def _draw_keys(context, region, maya=False):
    from . import channel_box
    keys = key_frames(channel_box.targets(context))
    if not keys:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    w = max(1.0, round(context.preferences.system.ui_scale or 1.0))
    h = region.height
    if maya:
        from ..operators import bookmarks
        if bookmarks.markers(context.scene):
            h = _rows('strip', h, ROWS_BOOKMARKS, context.preferences.system.ui_scale or 1.0)[0]
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    current = context.scene.frame_current
    for (colour, breakdown) in ((KEY_RGB, False), (BREAKDOWN_RGB, True)):
        tris = []
        for (f, bd) in keys:
            if bd != breakdown:
                continue
            x = key_x(region, f, maya)
            if x < -w or x > region.width + w:
                continue
            (x0, x1) = (int(x), int(x) + w)
            if abs(f - current) < 0.5:
                centre = region.view2d.view_to_region(f, 0, clip=False)[0]
                half = playhead_half_width(context, current) + 2 * w
                (x0, x1) = (int(centre - half), int(centre + half))
            tris += [(x0, 0), (x1, 0), (x1, h), (x0, 0), (x1, h), (x0, h)]
        if tris:
            shader.uniform_float('color', colour)
            batch_for_shader(shader, 'TRIS', {'pos': tris}).draw(shader)

def timeline_areas(wm):
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == 'DOPESHEET_EDITOR' and area.spaces.active.mode == 'TIMELINE':
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                if region is not None:
                    yield (win, area, region)

def fit_timelines():
    wm = bpy.context.window_manager
    n = 0
    for (win, area, region) in list(timeline_areas(wm)):
        with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
            if bpy.ops.anim.scene_range_frame.poll():
                bpy.ops.anim.scene_range_frame()
                n += 1
    return n

def _deferred_fit():
    try:
        fit_timelines()
    except Exception:
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
    _subscribe()
    if not bpy.app.background:
        _schedule()
classes = (ALLSET_MT_anim_preferences, ALLSET_PT_time_slider, ALLSET_OT_time_scrub, ALLSET_OT_time_range_drag, ALLSET_OT_time_slider_menu, ALLSET_OT_time_slider_unavailable, *TIME_SLIDER_MENUS)
_KEEP = {}

@persistent
def _keep_frame_pre(*_args):
    scene = bpy.context.scene
    if scene is not None:
        _KEEP['frame'] = (scene.name, scene.frame_current)

@persistent
def _keep_frame_post(*_args):
    if 'frame' in _KEEP and (not bpy.app.timers.is_registered(restore_frame)):
        bpy.app.timers.register(restore_frame, first_interval=0.0)

def restore_frame():
    """Put the frame from before the undo / redo back (None: timer done)."""
    (name, frame) = _KEEP.pop('frame', (None, None))
    scene = bpy.context.scene
    if scene is not None and scene.name == name and (scene.frame_current != frame):
        scene.frame_current = frame
    return None
_UNDO_HANDLERS = (('undo_pre', _keep_frame_pre), ('redo_pre', _keep_frame_pre), ('undo_post', _keep_frame_post), ('redo_post', _keep_frame_post))

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    for (name, fn) in _UNDO_HANDLERS:
        getattr(bpy.app.handlers, name).append(fn)
    wm = bpy.types.WindowManager
    wm.allset_time_range_on = bpy.props.BoolProperty(name=_zh_native('Time Range', 'MWK:ui/time_slider.py:921'), description=_zh_native('A Shift-dragged Time Slider range is highlighted', 'MWK:ui/time_slider.py:921'), options={'SKIP_SAVE'}, translation_context='MWK:ui/time_slider.py:921')
    wm.allset_time_range = bpy.props.IntVectorProperty(name=_zh_native('Time Range', 'MWK:ui/time_slider.py:923'), size=2, options={'SKIP_SAVE'}, translation_context='MWK:ui/time_slider.py:923')
    _draw_handle.append(bpy.types.SpaceDopeSheetEditor.draw_handler_add(_draw_range, (), 'WINDOW', 'POST_PIXEL'))
    (buttons, menus) = header_classes()
    if LEGACY_TIMELINE:
        menus.draw_collapsible = classmethod(_no_editor_menus)
        _ORIGINAL['draw_header'] = buttons.draw_header
        buttons.draw_header = staticmethod(draw_header)
    else:
        (orig_menus, orig_header) = (menus.draw_collapsible, buttons.draw_header)
        _ORIGINAL['draw_header'] = buttons.__dict__['draw_header']

        def _menus_5(cls, context, layout):
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
    for (name, fn) in _UNDO_HANDLERS:
        if fn in getattr(bpy.app.handlers, name):
            getattr(bpy.app.handlers, name).remove(fn)
    if bpy.app.timers.is_registered(restore_frame):
        bpy.app.timers.unregister(restore_frame)
    _KEEP.clear()
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    bpy.msgbus.clear_by_owner(_OWNER)
    if bpy.app.timers.is_registered(_deferred_fit):
        bpy.app.timers.unregister(_deferred_fit)
    (buttons, menus) = header_classes()
    if 'draw_header' in _ORIGINAL:
        orig = _ORIGINAL.pop('draw_header')
        buttons.draw_header = orig if not LEGACY_TIMELINE else staticmethod(orig)
    if 'draw_collapsible' in menus.__dict__:
        del menus.draw_collapsible
    while _draw_handle:
        bpy.types.SpaceDopeSheetEditor.draw_handler_remove(_draw_handle.pop(), 'WINDOW')
    wm = bpy.types.WindowManager
    del wm.allset_time_range
    del wm.allset_time_range_on
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
