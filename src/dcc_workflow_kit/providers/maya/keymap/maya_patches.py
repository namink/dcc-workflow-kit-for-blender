# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Patches that turn Industry Compatible data into the "Maya" keyconfig.

``IC:<line>`` = ``$S\\presets\\keyconfig\\keymap_data\\industry_compatible_data.py``.
Plan and rationale: docs/steps/step_2.md (1-4), docs/steps/step_3.md (5-8),
docs/steps/step_4.md (9-13), docs/steps/step_10.md (16), docs/steps/step_11.md (17),
docs/steps/step_16.md (18), docs/steps/step_18.md (19), docs/steps/step_20.md (20),
docs/steps/step_22.md (21), docs/steps/step_24.md (22), docs/steps/step_27.md (23), docs/steps/step_28.md (24).

``ADDED`` lists every binding this module adds; tests use it for the
shadowing check and docs/keymap_mapping.md is cross-checked against it.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from . import patch
from .patch import KeyconfigData, make_event
ADDED = []
PASS_THROUGH_FIRST = ('allset.cb_virtual_slider', 'allset.cb_hover', 'allset.weight_numbers_hover', 'allset.cb_scroll', 'allset.time_range_drag', 'allset.manip_ctrl', 'allset.manip_duplicate', 'allset.manip_press', 'allset.select_priority', 'allset.select_through', 'allset.toolbox_guard', 'allset.time_scrub', 'allset.time_slider_menu', 'allset.outliner_set_click', 'allset.outliner_set_menu', 'allset.graph_channel_click', 'allset.graph_channel_scroll', 'allset.script_run', 'allset.dock_strip_click', 'allset.hs_swatch_drag', 'allset.shelf_scroll', 'allset.select_2d_click', 'allset.select_2d_box', 'allset.graph_layer_pick', 'allset.uv_shell_pick', 'allset.uv_shell_box')

def _add(kd, km_name, idname, event, props=None, shadows=(), first=False):
    kd.add(km_name, idname, event, props, first=first)
    ADDED.append((km_name, idname, event, dict(props or {}), tuple(shadows)))

def _click(plain, toggle, deselect, add):
    return [((False, False), plain), ((True, False), toggle), ((False, True), deselect), ((True, True), add)]
_CLICK_EXACT = _click({'deselect_all': True}, {'toggle': True}, {'deselect': True}, {'extend': True})
_OUTLINER_CLICK = _click({'extend': False, 'extend_range': False, 'deselect_all': True}, {'extend': False, 'extend_range': True, 'deselect_all': True}, {'extend': True, 'extend_range': False, 'deselect_all': True}, {'extend': True, 'extend_range': True, 'deselect_all': True})
_GRAPH_CLICK = _click({'extend': False, 'deselect_all': True}, {'extend': True}, {'extend': False, 'deselect_all': True}, {'extend': True})
_NLA_CLICK = _click({'extend': False, 'deselect_all': True}, {'extend': True}, {'extend': True}, {'extend': True})
_DOPE_CLICK = _click({'extend': False, 'deselect_all': True}, {'extend': True}, {'extend': True}, {'extend': True})
_BOX = _click({'mode': 'SET'}, {'mode': 'XOR'}, {'mode': 'SUB'}, {'mode': 'ADD'})
_BOX_SET_XOR = _click({'mode': 'SET'}, {'mode': 'SET'}, {'mode': 'SUB'}, {'mode': 'ADD'})
_BOX_NO_XOR = _click({'mode': 'SET'}, {'mode': 'ADD'}, {'mode': 'SUB'}, {'mode': 'ADD'})
_NODE_CLICK = _click({'deselect_all': True, 'select_passthrough': True}, {'toggle': True}, {'deselect': True}, {'extend': True})
_NODE_BOX = [v for v in _BOX_NO_XOR if v[0] != (False, True)]
SELECT_RULES = (('view3d.select', 'CLICK', _CLICK_EXACT, ()), ('view3d.select', 'PRESS', _CLICK_EXACT, ()), ('uv.select', 'CLICK', _CLICK_EXACT, ()), ('uv.select', 'PRESS', _CLICK_EXACT, ()), ('outliner.item_activate', 'CLICK', _OUTLINER_CLICK, ()), ('graph.clickselect', 'PRESS', _GRAPH_CLICK, ('column', 'curves')), ('view3d.select_box', 'CLICK_DRAG', _BOX, ('tweak',)), ('uv.select_box', 'CLICK_DRAG', _BOX_SET_XOR, ('tweak',)), ('outliner.select_box', 'CLICK_DRAG', _BOX_NO_XOR, ('tweak',)), ('graph.select_box', 'CLICK_DRAG', _BOX_SET_XOR, ('tweak', 'axis_range')), ('action.clickselect', 'PRESS', _DOPE_CLICK, ('column', 'channel')), ('nla.click_select', 'PRESS', _NLA_CLICK, ()), ('node.select', 'PRESS', _NODE_CLICK, ()), ('action.select_box', 'CLICK_DRAG', _BOX_SET_XOR, ('tweak', 'axis_range', 'wait_for_input')), ('nla.select_box', 'CLICK_DRAG', _BOX_NO_XOR, ('tweak', 'axis_range', 'wait_for_input')), ('node.select_box', 'CLICK_DRAG', _NODE_BOX, ('tweak',)))
SELECT_CTRL_SHIFT_REMOVED = ((_dcc_source('Dopesheet'), 'action.select_leftright'), (_dcc_source('NLA Editor'), 'nla.select_leftright'), (_dcc_source('Node Editor'), 'node.select_link_viewer'))

def patch_selection(kd):
    kd.remove(_dcc_source('Graph Editor'), 'graph.select_leftright', type='LEFTMOUSE', shift=True, ctrl=True)
    for (km, idname) in SELECT_CTRL_SHIFT_REMOVED:
        kd.remove(km, idname, type='LEFTMOUSE', shift=True, ctrl=True)
    touched = {}
    for (idname, value, variants, keep) in SELECT_RULES:
        kms = kd.rewrite_modifier_set(idname, value, variants, keep_props=keep)
        if not kms:
            if not patch.STRICT:
                patch.DRIFT.append(f'selection patch: {idname} {value} not found')
                continue
            raise LookupError(f'selection patch: {idname} {value} not found in IC data')
        touched[idname, value] = kms
    patch_select_2d(kd, touched)
    return touched
SELECT_2D_CLICKS = ((('graph.clickselect', 'PRESS'), 'GRAPH', ((False, False, 'KEEP'), (False, True, 'CTRL'), (True, True, 'ADD'))), (('action.clickselect', 'PRESS'), 'DOPE', ((False, True, 'DESELECT'), (True, True, 'ADD'))), (('outliner.item_activate', 'CLICK'), 'OUTLINER', ((False, True, 'TOGGLE'),)))
SELECT_2D_BOXES = ((('graph.select_box', 'CLICK_DRAG'), 'GRAPH'), (('action.select_box', 'CLICK_DRAG'), 'DOPE'), (('uv.select_box', 'CLICK_DRAG'), 'UV'))
SELECT_2D_KEYMAPS = set()

def patch_select_2d(kd, touched):
    for (key, editor, variants) in SELECT_2D_CLICKS:
        for km in touched.get(key, ()):
            if km not in (_dcc_source('Graph Editor'), _dcc_source('Dopesheet'), _dcc_source('Outliner')):
                continue
            for (shift, ctrl, rule) in variants:
                _add(kd, km, 'allset.select_2d_click', make_event('LEFTMOUSE', key[1], shift=shift, ctrl=ctrl), {'editor': editor, 'rule': rule}, shadows=(km, _dcc_source('Screen'), _dcc_source('View2D')), first=True)
    for (key, editor) in SELECT_2D_BOXES:
        for km in touched.get(key, ()):
            _add(kd, km, 'allset.select_2d_box', make_event('LEFTMOUSE', 'CLICK_DRAG', shift=True), {'editor': editor}, shadows=(km,), first=True)
            SELECT_2D_KEYMAPS.add(km)
DISPLAY_KEYS = (('FOUR', 'WIREFRAME'), ('FIVE', 'SHADED'), ('SIX', 'TEXTURED'), ('SEVEN', 'LIGHTS'))

def patch_display(kd):
    kd.remove(_dcc_source('Object Non-modal'), 'object.mode_set', type='FOUR')
    kd.remove(_dcc_source('Object Non-modal'), 'wm.call_menu_pie', type='FIVE')
    for (key, mode) in DISPLAY_KEYS:
        _add(kd, '3D View', 'allset.display_mode', make_event(key), {'mode': mode})
    _add(kd, _dcc_source('Object Non-modal'), 'allset.toggle_sel_mode', make_event('F8'))

def patch_group(kd):
    for km in (_dcc_source('Object Mode'), _dcc_source('Outliner')):
        kd.remove(km, None, type='G', ctrl=True)
        _add(kd, km, 'allset.group', make_event('G', ctrl=True))

def patch_space(kd):
    kd.remove(_dcc_source('Frames'), 'screen.animation_play', type='SPACE')
    _add(kd, _dcc_source('Frames'), 'screen.animation_play', make_event('V', alt=True))
    _add(kd, _dcc_source('Frames'), 'screen.frame_jump', make_event('V', alt=True, shift=True), {'end': False})
_PAINT_MODES = (_dcc_source('Sculpt'), _dcc_source('Vertex Paint'), _dcc_source('Image Paint'), _dcc_source('Weight Paint'))
HOLD_KEYS = (('X', _dcc_source('grid')), ('C', _dcc_source('curve')), ('V', _dcc_source('point')), ('J', _dcc_source('step')))

def patch_hold_snap(kd):
    kd.remove('3D View', 'wm.context_toggle', type='X')
    kd.remove('3D View', 'wm.call_menu_pie', type='X', shift=True)
    kd.remove('3D View', 'wm.call_menu_pie', type='V')
    for km in (_dcc_source('Object Mode'), _dcc_source('Mesh'), _dcc_source('Curve'), _dcc_source('Curves'), _dcc_source('Armature'), _dcc_source('Metaball')):
        kd.remove(km, 'wm.tool_set_by_id', type='C')
    for (key, name) in HOLD_KEYS:
        for shift in (False, True):
            _add(kd, '3D View', 'allset.hold', make_event(key, shift=shift), {'name': name}, shadows=_PAINT_MODES)

def patch_soft_select(kd):
    for km in (_dcc_source('Object Mode'), _dcc_source('Mesh'), _dcc_source('Curve'), _dcc_source('Curves'), _dcc_source('Metaball'), _dcc_source('Lattice'), _dcc_source('Particle')):
        kd.remove(km, 'wm.context_toggle', type='B')
    _add(kd, '3D View', 'allset.tap_hold', make_event('B'), {'binding': 'soft_select'}, shadows=_PAINT_MODES)

def patch_tap_hold_and_pivot(kd):
    kd.remove('3D View', 'view3d.view_all', type='A')
    _add(kd, '3D View', 'allset.tap_hold', make_event('A'), {'binding': 'select_all'}, shadows=(_dcc_source('Sculpt'),))
    kd.remove(_dcc_source('Object Mode'), 'wm.tool_set_by_id', type='D')
    _add(kd, _dcc_source('Object Mode'), 'allset.hold', make_event('D'), {'name': _dcc_source('pivot')})
    _add(kd, _dcc_source('Object Mode'), 'allset.pivot_toggle', make_event('INSERT'))
PICK_WALK_KEYS = (('UP_ARROW', 'UP'), ('DOWN_ARROW', 'DOWN'), ('LEFT_ARROW', 'LEFT'), ('RIGHT_ARROW', 'RIGHT'))

def patch_pick_walk(kd):
    kd.remove(_dcc_source('Object Mode'), 'object.select_more', type='UP_ARROW')
    kd.remove(_dcc_source('Object Mode'), 'object.select_less', type='DOWN_ARROW')
    kd.remove(_dcc_source('Object Mode'), 'screen.frame_offset', type='LEFT_ARROW')
    kd.remove(_dcc_source('Object Mode'), 'screen.frame_offset', type='RIGHT_ARROW')
    for (key, direction) in PICK_WALK_KEYS:
        _add(kd, _dcc_source('Object Mode'), 'allset.pick_walk', make_event(key, repeat=True), {'direction': direction})

def patch_camera(kd):
    kd.remove('3D View', 'view3d.rotate', type='LEFTMOUSE', alt=True)
    _add(kd, '3D View', 'allset.tumble', make_event('LEFTMOUSE', alt=True))
    kd.remove('3D View', 'view3d.zoom', type='RIGHTMOUSE', alt=True)
    _add(kd, '3D View', 'allset.dolly', make_event('RIGHTMOUSE', alt=True), shadows=(_dcc_source('Image Paint'), _dcc_source('Vertex Paint'), _dcc_source('Sculpt')))
    kd.remove(_dcc_source('Image'), 'image.view_zoom', type='RIGHTMOUSE', alt=True)
    _add(kd, _dcc_source('Image'), 'allset.dolly_2d', make_event('RIGHTMOUSE', alt=True), shadows=(_dcc_source('View2D'),))
    kd.remove('3D View', 'view3d.view_center_pick', type='F', shift=True)
    _add(kd, '3D View', 'allset.frame_all_views', make_event('F', shift=True), {'selected': True})
    kd.remove('3D View', 'view3d.view_selected', type='F')
    _add(kd, '3D View', 'allset.frame', make_event('F'), {'selected': True})
    _add(kd, '3D View', 'allset.frame_all_views', make_event('F', shift=True, ctrl=True), {'selected': True, 'children': True})
    kd.remove('3D View', 'view3d.view_all', type='A', shift=True)
    _add(kd, '3D View', 'allset.frame_all_views', make_event('A', shift=True), {'selected': False}, shadows=(_dcc_source('Sculpt'),))

def patch_view_history(kd):
    kd.remove(_dcc_source('Object Mode'), 'object.select_hierarchy', type='LEFT_BRACKET')
    kd.remove(_dcc_source('Object Mode'), 'object.select_hierarchy', type='RIGHT_BRACKET')
    for (ev, direction) in ((make_event('LEFT_BRACKET'), 'UNDO'), (make_event('RIGHT_BRACKET'), 'REDO'), (make_event('Z', alt=True), 'UNDO'), (make_event('Y', alt=True), 'REDO')):
        _add(kd, '3D View', 'allset.view_history', ev, {'direction': direction}, shadows=_PAINT_MODES + (_dcc_source('Armature'),))
HOTBOX_KEYMAPS = ('3D View', _dcc_source('Outliner'), _dcc_source('Graph Editor'), _dcc_source('Dopesheet'), _dcc_source('Node Editor'), _dcc_source('Image'))

def patch_space_tap(kd):
    for km in HOTBOX_KEYMAPS:
        _add(kd, km, 'allset.hotbox', make_event('SPACE'))
    _add(kd, _dcc_source('Screen'), 'screen.screen_full_area', make_event('SPACE', ctrl=True), {'use_hide_panels': True})
SMOOTH_KEYS = (('ONE', 1), ('TWO', 2), ('THREE', 3))

def patch_smooth_preview(kd):
    for (key, level) in SMOOTH_KEYS:
        kd.remove(_dcc_source('Object Mode'), 'object.mode_set_with_submode', type=key)
        kd.remove(_dcc_source('Mesh'), 'mesh.select_mode', type=key)
        for km in (_dcc_source('Object Mode'), _dcc_source('Mesh')):
            _add(kd, km, 'allset.smooth_preview', make_event(key), {'level': level})
COMPONENT_KEYS = (('F9', 'VERT'), ('F10', 'EDGE'), ('F11', 'FACE'), ('F7', 'MULTI'))

def patch_component_keys(kd):
    for (key, comp) in COMPONENT_KEYS:
        _add(kd, _dcc_source('Object Non-modal'), 'allset.component_mode', make_event(key), {'type': comp})
SLIDER_TOOL_KEYMAPS = ('3D View Tool: Move', '3D View Tool: Rotate', '3D View Tool: Scale', '3D View Tool: Transform')

def patch_cb_slider(kd):
    for km in SLIDER_TOOL_KEYMAPS:
        _add(kd, km, 'allset.cb_virtual_slider', make_event('MIDDLEMOUSE'), first=True, shadows=(km,))
    _add(kd, _dcc_source('Object Mode'), 'allset.cb_virtual_slider', make_event('MIDDLEMOUSE'))
    _add(kd, _dcc_source('Property Editor'), 'allset.cb_hover', make_event('MOUSEMOVE', 'ANY', any=True), first=True)
    _add(kd, _dcc_source('Weight Paint'), 'allset.weight_numbers_hover', make_event('MOUSEMOVE', 'ANY', any=True), first=True)
    for wheel in ('WHEELUPMOUSE', 'WHEELDOWNMOUSE'):
        _add(kd, 'View2D Buttons List', 'allset.cb_scroll', make_event(wheel), first=True, shadows=('View2D Buttons List',))
    _add(kd, 'View2D Buttons List', 'allset.dock_strip_click', make_event('LEFTMOUSE'), first=True, shadows=('View2D Buttons List', _dcc_source('Property Editor'), _dcc_source('Screen')))
    _add(kd, 'View2D Buttons List', 'allset.hs_swatch_drag', make_event('MIDDLEMOUSE'), first=True, shadows=('View2D Buttons List',))
MM_KEYMAPS = ((_dcc_source('Object Mode'), 'VIEW3D_MT_object_context_menu'), (_dcc_source('Mesh'), 'VIEW3D_MT_edit_mesh_context_menu'), (_dcc_source('Curve'), 'VIEW3D_MT_edit_curve_context_menu'))
MM_EVENTS = (('RMB', {}), ('SHIFT_RMB', {'shift': True}), ('CTRL_RMB', {'ctrl': True}), ('TOOL_OPTIONS', {'shift': True, 'ctrl': True}))
TOOL_KEY_KEYMAPS = (_dcc_source('Object Mode'), _dcc_source('Mesh'), _dcc_source('Curve'), _dcc_source('Armature'), _dcc_source('Pose'), _dcc_source('Metaball'), _dcc_source('Lattice'), _dcc_source('Curves'))
TOOL_KEYS = (('Q', 'tool_select'), ('W', 'tool_move'), ('E', 'tool_rotate'), ('R', 'tool_scale'))

def patch_marking_menus(kd):
    for (km, menu) in MM_KEYMAPS:
        kd.remove(km, 'wm.call_menu', type='RIGHTMOUSE')
        for (trigger, mods) in MM_EVENTS:
            _add(kd, km, 'allset.marking_menu', make_event('RIGHTMOUSE', **mods), {'trigger': trigger})
    kd.remove('3D View', 'view3d.cursor3d', type='RIGHTMOUSE', shift=True)
    kd.remove('3D View', 'transform.translate', type='RIGHTMOUSE', value='CLICK_DRAG', shift=True)
    for km in TOOL_KEY_KEYMAPS:
        for (key, binding) in TOOL_KEYS:
            kd.remove(km, 'wm.tool_set_by_id', type=key)
            _add(kd, km, 'allset.tap_hold', make_event(key), {'binding': binding})

def patch_concepts(kd):
    kd.remove(_dcc_source('Object Mode'), 'object.parent_set', type='P')
    kd.remove(_dcc_source('Object Mode'), 'object.parent_clear', type='P', shift=True)
    for km in (_dcc_source('Object Mode'), _dcc_source('Outliner')):
        _add(kd, km, 'allset.parent', make_event('P'))
        _add(kd, km, 'allset.unparent', make_event('P', shift=True))
    kd.remove(_dcc_source('Object Mode'), 'object.duplicate_move', type='D', ctrl=True)
    _add(kd, _dcc_source('Object Mode'), 'allset.duplicate', make_event('D', ctrl=True))
    kd.remove(_dcc_source('Mesh'), 'mesh.duplicate_move', type='D', ctrl=True)
    _add(kd, _dcc_source('Mesh'), 'allset.component_command', make_event('D', ctrl=True), {'item': 'Edit/Duplicate'})
    _add(kd, _dcc_source('Object Mode'), 'allset.duplicate_with_transform', make_event('D', shift=True))
    _add(kd, _dcc_source('Object Mode'), 'allset.duplicate_special', make_event('D', shift=True, ctrl=True))
    _add(kd, _dcc_source('Object Mode'), 'allset.delete_history', make_event('D', shift=True, alt=True))

def patch_attribute_editor(kd):
    kd.remove(_dcc_source('Object Mode'), 'object.select_all', type='A', ctrl=True)
    kd.remove(_dcc_source('Object Mode'), 'object.select_all', type='A', ctrl=True, shift=True)
    _add(kd, _dcc_source('Object Mode'), 'allset.ae_toggle', make_event('A', ctrl=True))
    _add(kd, _dcc_source('Object Mode'), 'object.select_all', make_event('A', ctrl=True, shift=True), {'action': 'SELECT'})
    _add(kd, _dcc_source('Object Mode'), 'allset.select_none', make_event('D', alt=True))
    for (km, idname) in CTRL_A_MODES:
        kd.remove(km, idname, type='A', ctrl=True)
        _add(kd, km, 'allset.ae_toggle', make_event('A', ctrl=True))
        if km == _dcc_source('Mesh'):
            continue
        if km != _dcc_source('Paint Vertex Selection (Weight, Vertex)'):
            kd.remove(km, idname, type='A', ctrl=True, shift=True)
        _add(kd, km, idname, make_event('A', ctrl=True, shift=True), {'action': 'SELECT'})
    _add(kd, _dcc_source('Pose'), 'allset.select_none', make_event('D', alt=True))
    for km in (_dcc_source('Curve'), _dcc_source('Armature'), _dcc_source('Metaball'), _dcc_source('Lattice'), _dcc_source('Curves'), _dcc_source('Point Cloud')):
        _add(kd, km, 'allset.select_none', make_event('D', alt=True))
CTRL_A_MODES = ((_dcc_source('Mesh'), 'mesh.select_all'), (_dcc_source('Pose'), 'pose.select_all'), (_dcc_source('Curve'), 'curve.select_all'), (_dcc_source('Armature'), 'armature.select_all'), (_dcc_source('Metaball'), 'mball.select_all'), (_dcc_source('Lattice'), 'lattice.select_all'), (_dcc_source('Particle'), 'particle.select_all'), (_dcc_source('Curves'), 'curves.select_all'), (_dcc_source('Sculpt Curves'), 'curves.select_all'), (_dcc_source('Point Cloud'), 'pointcloud.select_all'), (_dcc_source('Paint Face Mask (Weight, Vertex, Texture)'), 'paint.face_select_all'), (_dcc_source('Paint Vertex Selection (Weight, Vertex)'), 'paint.vert_select_all'), (_dcc_source('UV Editor'), 'uv.select_all'), (_dcc_source('Graph Editor'), 'graph.select_all'), (_dcc_source('Dopesheet'), 'action.select_all'), (_dcc_source('NLA Editor'), 'nla.select_all'), (_dcc_source('Animation Channels'), 'anim.channels_select_all'))
_Z_BORDERS = (('3D View', 'view3d.zoom_border', False), (_dcc_source('View2D'), 'view2d.zoom_border', False), (_dcc_source('Image'), 'image.view_zoom_border', False), (_dcc_source('Node Editor'), 'node.viewer_border', True))
VISIBILITY_KEYS = (('H', {}, 'TOGGLE'), ('H', {'ctrl': True}, 'HIDE'), ('H', {'alt': True}, 'HIDE_UNSELECTED'), ('H', {'shift': True}, 'SHOW_SELECTED'), ('H', {'ctrl': True, 'shift': True}, 'SHOW_LAST'))

def patch_undo_visibility(kd):
    for (km, idname, optional) in _Z_BORDERS:
        kd.remove(km, idname, optional=optional, type='Z')
    _add(kd, _dcc_source('Screen'), 'ed.undo', make_event('Z'))
    _add(kd, _dcc_source('Screen'), 'ed.redo', make_event('Z', shift=True))
    _add(kd, _dcc_source('Screen'), 'ed.redo', make_event('Y', ctrl=True))
    kd.remove(_dcc_source('Object Mode'), 'object.hide_view_set', type='H', ctrl=True)
    kd.remove(_dcc_source('Object Mode'), 'object.hide_view_set', type='H', shift=True)
    kd.remove(_dcc_source('Object Mode'), 'object.hide_view_clear', type='H', alt=True)
    for (key, mods, action) in VISIBILITY_KEYS:
        _add(kd, _dcc_source('Object Mode'), 'allset.visibility', make_event(key, **mods), {'action': action})
    kd.remove(_dcc_source('Mesh'), 'mesh.hide', type='H', shift=True)
    kd.remove(_dcc_source('Mesh'), 'mesh.reveal', type='H', alt=True)
    _add(kd, _dcc_source('Mesh'), 'mesh.hide', make_event('H', alt=True), {'unselected': True})
    for mods in ({'shift': True}, {'ctrl': True, 'shift': True}, {'ctrl': True, 'alt': True}):
        _add(kd, _dcc_source('Mesh'), 'mesh.reveal', make_event('H', **mods))
    kd.remove(_dcc_source('Mesh'), 'mesh.select_mode', type='ONE', ctrl=True)
    _add(kd, '3D View', 'allset.isolate', make_event('ONE', ctrl=True), shadows=(_dcc_source('Sculpt'),))
    for key in ('DEL', 'BACK_SPACE'):
        kd.remove(_dcc_source('Object Mode'), 'object.delete', type=key)
        _add(kd, _dcc_source('Object Mode'), 'allset.delete', make_event(key))
        kd.remove(_dcc_source('Outliner'), 'outliner.delete', type=key)
        _add(kd, _dcc_source('Outliner'), 'outliner.delete', make_event(key), {'hierarchy': True})
    _add(kd, _dcc_source('Object Mode'), 'object.select_all', make_event('I', ctrl=True, shift=True), {'action': 'INVERT'})
    _add(kd, _dcc_source('Mesh'), 'mesh.select_all', make_event('I', ctrl=True, shift=True), {'action': 'INVERT'})
CONVERT_KEYS = (('F9', 'VERT'), ('F10', 'EDGE'), ('F11', 'FACE'))

def patch_mesh_components(kd):
    kd.remove(_dcc_source('Mesh'), 'wm.tool_set_by_id', type='D')
    _add(kd, _dcc_source('Mesh'), 'allset.hold', make_event('D'), {'name': 'component_pivot'})
    _add(kd, _dcc_source('Mesh'), 'allset.pivot_toggle', make_event('INSERT'))
    kd.remove(_dcc_source('Armature'), 'wm.tool_set_by_id', type='D')
    _add(kd, _dcc_source('Armature'), 'allset.hold', make_event('D'), {'name': 'preserve_children'})
    _add(kd, _dcc_source('Armature'), 'allset.pivot_toggle', make_event('INSERT'))
    kd.remove(_dcc_source('Mesh'), 'mesh.select_all', type='A', ctrl=True, shift=True)
    _add(kd, _dcc_source('Mesh'), 'mesh.select_all', make_event('A', ctrl=True, shift=True), {'action': 'SELECT'})
    _add(kd, _dcc_source('Mesh'), 'allset.select_none', make_event('D', alt=True))
    kd.remove(_dcc_source('Mesh'), 'wm.tool_set_by_id', type='E', ctrl=True)
    _add(kd, _dcc_source('Mesh'), 'allset.extrude', make_event('E', ctrl=True))
    kd.remove(_dcc_source('Mesh'), 'wm.tool_set_by_id', type='B', ctrl=True)
    _add(kd, _dcc_source('Mesh'), 'allset.bevel', make_event('B', ctrl=True))
    _add(kd, _dcc_source('Mesh'), 'mesh.select_more', make_event('PERIOD', shift=True, repeat=True))
    _add(kd, _dcc_source('Mesh'), 'mesh.select_less', make_event('COMMA', shift=True, repeat=True))
    _add(kd, _dcc_source('Mesh'), 'mesh.select_next_item', make_event('PERIOD', shift=True, ctrl=True, repeat=True))
    _add(kd, _dcc_source('Mesh'), 'mesh.select_prev_item', make_event('COMMA', shift=True, ctrl=True, repeat=True))
    for (key, comp) in CONVERT_KEYS:
        _add(kd, _dcc_source('Mesh'), 'allset.convert_selection', make_event(key, ctrl=True), {'type': comp})
    for shift in (False, True):
        kd.remove(_dcc_source('Mesh'), 'mesh.loop_select', type='LEFTMOUSE', value='DOUBLE_CLICK', shift=shift)
        _add(kd, _dcc_source('Mesh'), 'allset.loop_pick', make_event('LEFTMOUSE', value='DOUBLE_CLICK', shift=shift), {'between': shift}, shadows=(_dcc_source('Screen'),))

def patch_key_stepping(kd):
    kd.remove('3D View', 'wm.call_menu_pie', type='PERIOD')
    kd.remove('3D View', 'wm.call_menu_pie', type='COMMA')
    kd.remove(_dcc_source('Image'), 'wm.call_menu_pie', type='PERIOD')
    keep = (_dcc_source('Outliner'), _dcc_source('Clip Editor'))
    _add(kd, _dcc_source('Frames'), 'screen.keyframe_jump', make_event('PERIOD'), {'next': True}, shadows=keep)
    _add(kd, _dcc_source('Frames'), 'screen.keyframe_jump', make_event('COMMA'), {'next': False}, shadows=keep)
    _add(kd, _dcc_source('Frames'), 'screen.frame_offset', make_event('PERIOD', alt=True, repeat=True), {'delta': 1})
    _add(kd, _dcc_source('Frames'), 'screen.frame_offset', make_event('COMMA', alt=True, repeat=True), {'delta': -1})
GIZMO_KEYMAPS = (_dcc_source('Generic Gizmo Maybe Drag'), _dcc_source('Generic Gizmo Drag'))

def patch_manip_duplicate(kd):
    for km in GIZMO_KEYMAPS:
        _add(kd, km, 'allset.manip_duplicate', make_event('LEFTMOUSE', 'PRESS', shift=True), first=True)
        found = kd.find(km, 'gizmogroup.gizmo_tweak', type='LEFTMOUSE', value='CLICK_DRAG')
        if not found:
            if not patch.STRICT:
                patch.DRIFT.append(f'{km}: no item gizmogroup.gizmo_tweak CLICK_DRAG')
                continue
            raise LookupError(f'{km}: no item gizmogroup.gizmo_tweak CLICK_DRAG')
        for item in found:
            item[1]['shift'] = -1

def patch_component_delete(kd):
    for key in ('DEL', 'BACK_SPACE'):
        kd.remove(_dcc_source('Mesh'), 'wm.call_menu', type=key)
        _add(kd, _dcc_source('Mesh'), 'allset.delete_components', make_event(key))

def patch_view_keys(kd):
    for (ev, factor) in ((make_event('EQUAL'), 1.25), (make_event('EQUAL', shift=True), 1.25), (make_event('MINUS'), 0.8)):
        _add(kd, '3D View', 'allset.manip_size', ev, {'factor': factor})
    _add(kd, '3D View', 'allset.view_home', make_event('HOME'), shadows=(_dcc_source('Font'),))
    _add(kd, '3D View', 'wm.context_toggle', make_event('FIVE', alt=True), {'data_path': 'space_data.overlay.show_wireframes'})
    for km in (_dcc_source('Object Mode'), _dcc_source('Mesh')):
        _add(kd, km, 'allset.smooth_level', make_event('PAGE_UP', repeat=True), {'delta': 1})
        _add(kd, km, 'allset.smooth_level', make_event('PAGE_DOWN', repeat=True), {'delta': -1})
        _add(kd, km, 'allset.smooth_preview', make_event('ZERO'), {'level': 1})
MMB_TOOLS = (('3D View Tool: Move', 'transform.translate', 'TRANSLATE'), ('3D View Tool: Rotate', 'transform.rotate', 'ROTATE'), ('3D View Tool: Scale', 'transform.resize', 'RESIZE'))

def patch_active_handle(kd):
    for km in GIZMO_KEYMAPS:
        _add(kd, km, 'allset.manip_press', make_event('LEFTMOUSE', 'PRESS'), first=True)
    for (km, idname, mode) in MMB_TOOLS:
        items = kd.items(km)
        old = kd.find(km, idname, type='MIDDLEMOUSE')
        if not old:
            if not patch.STRICT:
                patch.DRIFT.append(f'{km}: no MMB {idname}')
                continue
            raise LookupError(f'{km}: no MMB {idname}')
        at = next((i for (i, it) in enumerate(items) if it is old[0]))
        kd.remove(km, idname, type='MIDDLEMOUSE')
        item = kd.add(km, 'allset.manip_mmb', make_event('MIDDLEMOUSE'), {'mode': mode})
        items.remove(item)
        items.insert(at, item)
        ADDED.append((km, 'allset.manip_mmb', make_event('MIDDLEMOUSE'), {'mode': mode}, (km,)))

def patch_materials(kd):
    for km in (_dcc_source('Object Mode'), _dcc_source('Mesh')):
        _add(kd, km, 'allset.assign_new_material', make_event('T', shift=True))
SELECT_DRAG_KEYMAPS = ('3D View Tool: Select Box', '3D View Tool: Select Box (fallback)', '3D View Tool: Select Lasso', '3D View Tool: Select Lasso (fallback)')

def patch_select_through(kd):
    for km in SELECT_DRAG_KEYMAPS:
        for (shift, ctrl) in ((False, False), (True, False), (False, True), (True, True)):
            _add(kd, km, 'allset.select_through', make_event('LEFTMOUSE', 'CLICK_DRAG', shift=shift, ctrl=ctrl), first=True, shadows=(km,))
UV_SHELL_CLICK_KEYMAPS = ('3D View', _dcc_source('UV Editor'))
UV_SHELL_DRAG_KEYMAPS = SELECT_DRAG_KEYMAPS + ('Image Editor Tool: Uv, Select Box', 'Image Editor Tool: Uv, Select Box (fallback)', 'Image Editor Tool: Uv, Select Lasso', 'Image Editor Tool: Uv, Select Lasso (fallback)')

def patch_uv_shell_select(kd):
    mods = ((False, False), (True, False), (False, True), (True, True))
    for km in UV_SHELL_CLICK_KEYMAPS:
        for (shift, ctrl) in mods:
            _add(kd, km, 'allset.uv_shell_pick', make_event('LEFTMOUSE', 'CLICK', shift=shift, ctrl=ctrl), first=True, shadows=(km,))
    for km in UV_SHELL_DRAG_KEYMAPS:
        for (shift, ctrl) in mods:
            _add(kd, km, 'allset.uv_shell_box', make_event('LEFTMOUSE', 'CLICK_DRAG', shift=shift, ctrl=ctrl), first=True, shadows=(km,))

def patch_toolbox_guard(kd):
    for (shift, ctrl) in ((False, False), (True, False), (False, True), (True, True)):
        _add(kd, '3D View', 'allset.toolbox_guard', make_event('LEFTMOUSE', 'CLICK', shift=shift, ctrl=ctrl), first=True, shadows=('3D View',))
SELECT_PRIORITY_ITEMS = (('3D View', 'CLICK'), ('3D View Tool: Tweak', 'PRESS'))

def patch_select_priority(kd):
    for (km, value) in SELECT_PRIORITY_ITEMS:
        for (shift, ctrl) in ((False, False), (True, False), (False, True), (True, True)):
            _add(kd, km, 'allset.select_priority', make_event('LEFTMOUSE', value, shift=shift, ctrl=ctrl), first=True, shadows=(km,))
MENU_SET_SHADOWS = (_dcc_source('Image'), _dcc_source('File Browser'))

def patch_key_batch(kd):
    _add(kd, '3D View', 'allset.box_zoom', make_event('LEFTMOUSE', ctrl=True, alt=True), shadows=(_dcc_source('Sculpt'),))
    for km in (_dcc_source('Object Mode'), _dcc_source('Mesh')):
        _add(kd, km, 'wm.tool_set_by_id', make_event('T', ctrl=True), {'name': 'builtin.transform'})
        _add(kd, km, 'allset.last_tool', make_event('Y'))
        _add(kd, km, 'allset.menu_tool', make_event('X', shift=True, ctrl=True), {'tool': 'allset.multi_cut_tool', 'edit': True})
        _add(kd, km, 'allset.quad_draw_start', make_event('Q', shift=True, ctrl=True))
    kd.remove('3D View', 'view3d.view_axis', type='F2')
    kd.remove('3D View', 'view3d.view_axis', type='F3')
    kd.remove('3D View', 'view3d.view_camera', type='F4')
    kd.remove('3D View', 'view3d.view_orbit', type='F5')
    kd.remove('3D View', 'wm.call_panel', type='RET')
    for (key, set_id) in (('F2', 'modelingMenuSet'), ('F3', 'riggingMenuSet'), ('F4', 'animationMenuSet'), ('F5', 'dynamicsMenuSet'), ('F6', 'renderingMenuSet')):
        _add(kd, _dcc_source('Screen'), 'allset.menu_set', make_event(key), {'set': set_id}, shadows=MENU_SET_SHADOWS)
AXIS_LOCK_SHADOWS = (_dcc_source('Weight Paint'), _dcc_source('Paint Face Mask (Weight, Vertex, Texture)'), _dcc_source('Paint Vertex Selection (Weight, Vertex)'))

def patch_component_pick_walk(kd):
    kd.remove(_dcc_source('Mesh'), 'mesh.select_more', type='UP_ARROW')
    kd.remove(_dcc_source('Mesh'), 'mesh.select_less', type='DOWN_ARROW')
    for (key, direction) in PICK_WALK_KEYS:
        _add(kd, _dcc_source('Mesh'), 'allset.pick_walk_component', make_event(key, repeat=True), {'direction': direction})
    kd.remove('3D View', 'view3d.select', type='LEFTMOUSE', value='CLICK', shift=True, alt=True)
    _add(kd, '3D View', 'allset.view_axis_lock', make_event('LEFTMOUSE', shift=True, alt=True), {'mode': 'TUMBLE'}, shadows=AXIS_LOCK_SHADOWS)
    _add(kd, '3D View', 'allset.view_axis_lock', make_event('MIDDLEMOUSE', shift=True, alt=True), {'mode': 'TRACK'})

def patch_pose_joints(kd):
    _add(kd, _dcc_source('Object Non-modal'), 'object.posemode_toggle', make_event('TAB', ctrl=True), shadows=(_dcc_source('Screen'),))
    _add(kd, _dcc_source('Pose'), 'allset.cb_virtual_slider', make_event('MIDDLEMOUSE'))
TIME_SLIDER_SHADOWS = (_dcc_source('Dopesheet'), _dcc_source('View2D'), _dcc_source('Screen'))

def patch_time_slider(kd):
    for shift in (False, True):
        _add(kd, _dcc_source('Dopesheet'), 'allset.time_scrub', make_event('LEFTMOUSE', shift=shift), {'range': shift}, first=True, shadows=TIME_SLIDER_SHADOWS)
    _add(kd, _dcc_source('Dopesheet'), 'allset.time_scrub', make_event('MIDDLEMOUSE'), {'notice': True}, first=True, shadows=TIME_SLIDER_SHADOWS)
    _add(kd, _dcc_source('Dopesheet'), 'allset.time_slider_menu', make_event('RIGHTMOUSE'), first=True, shadows=TIME_SLIDER_SHADOWS)
    for value in ('PRESS', 'DOUBLE_CLICK'):
        under = tuple((n for n in kd.keymap_names() if n != _dcc_source('Screen') and kd.find(n, type='LEFTMOUSE', value=value)))
        _add(kd, _dcc_source('Screen'), 'allset.range_bar_drag', make_event('LEFTMOUSE', value=value), shadows=under)
    kd.remove(_dcc_source('Mesh'), 'wm.tool_set_by_id', type='K')
    kd.remove(_dcc_source('Dopesheet'), 'action.select_column', type='K')
    _add(kd, _dcc_source('Screen'), 'allset.tap_hold', make_event('K'), {'binding': 'time_drag'}, shadows=(_dcc_source('User Interface'), _dcc_source('Outliner')))
    for km in (_dcc_source('Object Mode'), _dcc_source('Pose')):
        kd.remove(km, 'anim.keyframe_insert_by_name', type='S')
        _add(kd, km, 'allset.set_key', make_event('S'))
        for (key, channels) in (('W', 'TRANSLATE'), ('E', 'ROTATE'), ('R', 'SCALE')):
            kd.remove(km, 'anim.keyframe_insert_by_name', type=key, shift=True)
            _add(kd, km, 'allset.set_key', make_event(key, shift=True), {'channels': channels})

def patch_joints(kd):
    kd.remove(_dcc_source('Pose'), 'pose.select_hierarchy', type='UP_ARROW')
    kd.remove(_dcc_source('Pose'), 'pose.select_hierarchy', type='DOWN_ARROW')
    kd.remove(_dcc_source('Pose'), 'screen.frame_offset', type='LEFT_ARROW')
    kd.remove(_dcc_source('Pose'), 'screen.frame_offset', type='RIGHT_ARROW')
    for (key, direction) in PICK_WALK_KEYS:
        _add(kd, _dcc_source('Pose'), 'allset.pick_walk_joint', make_event(key, repeat=True), {'direction': direction})
    kd.remove(_dcc_source('Pose'), 'object.parent_set', type='P')
    kd.remove(_dcc_source('Armature'), 'armature.parent_set', type='P')
    kd.remove(_dcc_source('Armature'), 'armature.parent_clear', type='P', shift=True)
    for km in (_dcc_source('Pose'), _dcc_source('Armature')):
        _add(kd, km, 'allset.parent_joint', make_event('P'))
        _add(kd, km, 'allset.unparent_joint', make_event('P', shift=True))
UV_KM = _dcc_source('UV Editor')

def patch_uv(kd):
    kd.remove(UV_KM, 'wm.call_menu', type='RIGHTMOUSE')
    for (trigger, mods) in (('RMB', {}), ('SHIFT_RMB', {'shift': True})):
        _add(kd, UV_KM, 'allset.marking_menu', make_event('RIGHTMOUSE', **mods), {'trigger': trigger})
    kd.remove(UV_KM, 'wm.call_menu_pie', type='X', shift=True)
    kd.remove(UV_KM, 'uv.select_linked', type='L', ctrl=True)
    _add(kd, UV_KM, 'allset.uv_cut', make_event('X', shift=True))
    _add(kd, UV_KM, 'allset.uv_sew', make_event('S', shift=True))
    _add(kd, UV_KM, 'allset.uv_unfold', make_event('U', ctrl=True))
    _add(kd, UV_KM, 'allset.uv_layout', make_event('L', ctrl=True))
    for km in (_dcc_source('Object Mode'), _dcc_source('Mesh')):
        _add(kd, km, 'allset.uv_component', make_event('F12'), {'mode': 'UV'}, shadows=(_dcc_source('Screen'),))
        _add(kd, km, 'allset.uv_component', make_event('F12', alt=True), {'mode': 'SHELL'})
SCENE_KEYS = (('wm.open_mainfile', 'allset.open_scene', {'ctrl': True}, 'O'), ('wm.save_mainfile', 'allset.save_scene', {'ctrl': True}, 'S'), ('wm.save_as_mainfile', 'allset.save_scene_as', {'ctrl': True, 'shift': True}, 'S'), ('wm.save_mainfile', 'allset.increment_save', {'ctrl': True, 'alt': True}, 'S'))

def patch_scene_files(kd):
    for (ic, kit, mods, key) in SCENE_KEYS:
        kd.remove(_dcc_source('Window'), ic, type=key, **mods)
        _add(kd, _dcc_source('Window'), kit, make_event(key, **mods))
    kd.remove(_dcc_source('Window'), 'wm.read_homefile', type='N', ctrl=True)
    _add(kd, _dcc_source('Window'), 'allset.new_maya_scene', make_event('N', ctrl=True), shadows=(_dcc_source('Text'),))
    _add(kd, _dcc_source('Window'), 'allset.create_reference', make_event('R', ctrl=True), shadows=(_dcc_source('Image Generic'), _dcc_source('File Browser'), _dcc_source('File Browser Main'), _dcc_source('Sequencer')))

def patch_graph_keys(kd):
    _add(kd, _dcc_source('Graph Editor'), 'anim.scene_range_frame', make_event('G'), shadows=(_dcc_source('Screen'),))
    _add(kd, _dcc_source('Graph Editor'), 'allset.set_tangent', make_event('D'), {'kind': 'AUTO'})
    for km in (_dcc_source('Object Mode'), _dcc_source('Pose')):
        kd.remove(km, 'anim.keyframe_insert', type='S', shift=True)
    for km in (_dcc_source('Object Mode'), _dcc_source('Pose'), _dcc_source('Graph Editor'), _dcc_source('Dopesheet')):
        _add(kd, km, 'allset.tap_hold', make_event('S', shift=True), {'binding': 'key_tangent'})
SELECT_MM_KEYMAPS = (_dcc_source('Object Mode'), _dcc_source('Mesh'))
REPEAT_SHADOWS = (_dcc_source('Armature'), _dcc_source('Metaball'), _dcc_source('Grease Pencil Selection'))
SELECT_MM_KEYS = (({'shift': True}, 'select_component'), ({'alt': True}, 'select_polygon'))
GRAPH_VIEW_KEYS = (('ONE', 'ABSOLUTE'), ('TWO', 'STACKED'), ('THREE', 'NORMALIZED'))

def patch_key_batch_2(kd):
    for (key, mode) in GRAPH_VIEW_KEYS:
        _add(kd, _dcc_source('Graph Editor'), 'allset.graph_view_mode', make_event(key), {'mode': mode})
    for km in SELECT_MM_KEYMAPS:
        for (mods, binding) in SELECT_MM_KEYS:
            _add(kd, km, 'allset.tap_hold', make_event('Q', **mods), {'binding': binding})
    _add(kd, _dcc_source('Mesh'), 'mesh.edge_rotate', make_event('LEFT_ARROW', ctrl=True, alt=True), {'use_ccw': True})
    _add(kd, _dcc_source('Mesh'), 'mesh.edge_rotate', make_event('RIGHT_ARROW', ctrl=True, alt=True), {'use_ccw': False})
    _add(kd, '3D View', 'allset.repeat_at_mouse', make_event('G', shift=True), shadows=REPEAT_SHADOWS)
    _add(kd, _dcc_source('Object Mode'), 'allset.camera_from_view', make_event('C', shift=True, ctrl=True))

def patch_outliner_drag(kd):
    _add(kd, _dcc_source('Outliner'), 'allset.outliner_drag', make_event('MIDDLEMOUSE'), shadows=(_dcc_source('View2D'), 'View2D Buttons List'))
INSERT_KEY_KEYS = (('I', {'alt': True}, {'channels': 'ALL'}), ('W', {'ctrl': True, 'shift': True}, {'channels': 'TRANSLATE'}), ('E', {'ctrl': True, 'shift': True}, {'channels': 'ROTATE'}), ('R', {'ctrl': True, 'shift': True}, {'channels': 'SCALE'}))
KEY_STEP_SHADOWS = (_dcc_source('User Interface'), _dcc_source('Mask Editing'), _dcc_source('Weight Paint'), _dcc_source('Grease Pencil Paint Mode'), _dcc_source('Grease Pencil Edit Mode'), _dcc_source('Grease Pencil Sculpt Mode'), _dcc_source('Grease Pencil Weight Paint'), _dcc_source('Grease Pencil Vertex Paint'), _dcc_source('Animation Channels'), _dcc_source('Text'), _dcc_source('Grease Pencil Draw Mode'), _dcc_source('Sequencer'))

def patch_key_insert(kd):
    for (key, mods, props) in INSERT_KEY_KEYS:
        _add(kd, _dcc_source('Screen'), 'allset.insert_key', make_event(key, **mods), props, shadows=KEY_STEP_SHADOWS)
    for (key, delta) in (('NINE', -1), ('ZERO', 1)):
        _add(kd, _dcc_source('Screen'), 'allset.nudge_keys', make_event(key, shift=True, repeat=True), {'delta': delta}, shadows=KEY_STEP_SHADOWS)
    for (key, direction) in (('COMMA', 'PREVIOUS'), ('PERIOD', 'NEXT')):
        _add(kd, _dcc_source('Screen'), 'allset.select_key', make_event(key, ctrl=True, alt=True), {'direction': direction}, shadows=KEY_STEP_SHADOWS)
TIME_SCRUB_KM = (_dcc_source('Time Scrub'), {'space_type': 'EMPTY', 'region_type': 'WINDOW'})

def patch_time_range(kd):
    _add(kd, _dcc_source('Dopesheet'), 'allset.time_range_drag', make_event('LEFTMOUSE'), first=True, shadows=TIME_SLIDER_SHADOWS)
    kd.ensure(*TIME_SCRUB_KM, [('anim.change_frame', make_event('LEFTMOUSE'), None)])
    shadows = (*TIME_SLIDER_SHADOWS, _dcc_source('Time Scrub'))
    _add(kd, _dcc_source('Time Scrub'), 'allset.time_scrub', make_event('LEFTMOUSE'), first=True, shadows=shadows)
    _add(kd, _dcc_source('Time Scrub'), 'allset.time_range_drag', make_event('LEFTMOUSE'), first=True, shadows=shadows)

def patch_manip_ctrl(kd):
    for km in GIZMO_KEYMAPS:
        _add(kd, km, 'allset.manip_ctrl', make_event('LEFTMOUSE', 'PRESS', ctrl=True), first=True)
    for (km, _idname, mode) in MMB_TOOLS:
        if mode == 'ROTATE':
            continue
        _add(kd, km, 'allset.manip_mmb_auto', make_event('MIDDLEMOUSE', 'PRESS', shift=True), {'mode': mode}, shadows=(km,))
VIEW3_SHADOWS = (_dcc_source('Sculpt'), _dcc_source('Font'), _dcc_source('Text'), _dcc_source('File Browser'), _dcc_source('Sequencer'), _dcc_source('Clip'), _dcc_source('Node Editor'), _dcc_source('Grease Pencil Selection'))
PIXEL_MOVE_KEYS = (('UP_ARROW', 0, 1), ('DOWN_ARROW', 0, -1), ('LEFT_ARROW', -1, 0), ('RIGHT_ARROW', 1, 0))

def patch_view_keys_3(kd):
    _add(kd, '3D View', 'allset.cycle_display', make_event('A', alt=True), shadows=VIEW3_SHADOWS)
    _add(kd, '3D View', 'allset.camera_mode_toggle', make_event('P', alt=True), shadows=VIEW3_SHADOWS)
    for (key, dx, dy) in PIXEL_MOVE_KEYS:
        _add(kd, '3D View', 'allset.pixel_move', make_event(key, alt=True, repeat=True), {'dx': dx, 'dy': dy}, shadows=VIEW3_SHADOWS)
    kd.remove(_dcc_source('Object Non-modal'), 'object.transfer_mode', type='ACCENT_GRAVE')
    _add(kd, '3D View', 'allset.tweak_hold', make_event('ACCENT_GRAVE'), shadows=VIEW3_SHADOWS)
    _add(kd, '3D View', 'allset.pan_zoom_hold', make_event('BACK_SLASH'), shadows=VIEW3_SHADOWS)
CUT_SHADOWS = (_dcc_source('Text'), _dcc_source('Console'), _dcc_source('Font'), _dcc_source('Grease Pencil Edit Mode'))
SHOW_KEYS = (('ONE', 'CURVES'), ('TWO', 'POLYGONS'), ('FOUR', 'IMAGE_PLANES'))

def patch_global_keys_4(kd):
    for km in (_dcc_source('Object Mode'), _dcc_source('Outliner')):
        _add(kd, km, 'allset.cut', make_event('X', ctrl=True), shadows=CUT_SHADOWS)
    _add(kd, _dcc_source('Object Mode'), 'allset.paste', make_event('V', ctrl=True), shadows=('3D View',))
    kd.remove('3D View', 'view3d.toggle_xray', type='X', alt=True)
    _add(kd, '3D View', 'view3d.walk', make_event('X', alt=True), shadows=VIEW3_SHADOWS)
    _add(kd, _dcc_source('Screen'), 'allset.playback_range_anim', make_event('BACK_SLASH', alt=True))
    for (key, kind) in SHOW_KEYS:
        _add(kd, '3D View', 'allset.toggle_show', make_event(key, alt=True), {'kind': kind}, shadows=VIEW3_SHADOWS)
    for km in (_dcc_source('Object Mode'), _dcc_source('Mesh')):
        _add(kd, km, 'allset.smooth_proxy', make_event('ACCENT_GRAVE', ctrl=True), {'action': 'TOGGLE'})
        _add(kd, km, 'allset.smooth_proxy', make_event('ACCENT_GRAVE', shift=True), {'action': 'BOTH'})
    _add(kd, _dcc_source('Object Mode'), 'allset.smooth_proxy', make_event('ACCENT_GRAVE', ctrl=True, shift=True), {'action': 'CREATE'})

def patch_graph_keys_2(kd):
    _add(kd, _dcc_source('Graph Editor'), 'allset.graph_center_time', make_event('T'))
    _add(kd, _dcc_source('Graph Editor'), 'allset.snap_time_toggle', make_event('SLASH', alt=True))
    _add(kd, _dcc_source('Graph Editor'), 'allset.insert_key_tool', make_event('I'))

def patch_outliner_sets(kd):
    _add(kd, _dcc_source('Outliner'), 'allset.outliner_set_click', make_event('LEFTMOUSE', 'CLICK', any=True), first=True, shadows=(_dcc_source('Outliner'),))
    _add(kd, _dcc_source('Outliner'), 'allset.outliner_set_menu', make_event('RIGHTMOUSE'), first=True, shadows=(_dcc_source('Outliner'),))

def patch_render_slots(kd):
    _add(kd, _dcc_source('Image'), 'image.cycle_render_slot', make_event('J'))
    _add(kd, _dcc_source('Image'), 'image.cycle_render_slot', make_event('J', alt=True), {'reverse': True})

def patch_graph_outliner(kd):
    _add(kd, _dcc_source('Animation Channels'), 'allset.graph_channel_click', make_event('LEFTMOUSE', any=True), first=True, shadows=(_dcc_source('Animation Channels'),))
    for (wheel, delta) in (('WHEELUPMOUSE', -3), ('WHEELDOWNMOUSE', 3)):
        _add(kd, _dcc_source('View2D'), 'allset.graph_channel_scroll', make_event(wheel), {'delta': delta}, first=True, shadows=(_dcc_source('View2D'), 'View2D Buttons List'))
    _add(kd, _dcc_source('Graph Editor'), 'allset.graph_layer_pick', make_event('LEFTMOUSE'), first=True, shadows=(_dcc_source('Graph Editor'), _dcc_source('Screen'), _dcc_source('View2D')))

def patch_shelf_scroll(kd):
    for (wheel, delta) in (('WHEELUPMOUSE', -1), ('WHEELDOWNMOUSE', 1)):
        _add(kd, _dcc_source('Image'), 'allset.shelf_scroll', make_event(wheel), {'delta': delta}, first=True, shadows=(_dcc_source('Image'), _dcc_source('View2D')))

def patch_script_editor(kd):
    kd.remove(_dcc_source('Screen Editing'), 'render.render', type='RET', ctrl=True, alt=False)
    for ctrl in (False, True):
        if kd.find(_dcc_source('Screen Editing'), 'render.render', type='F12', alt=True, ctrl=ctrl):
            kd.remove(_dcc_source('Screen Editing'), 'render.render', type='F12', alt=True, ctrl=ctrl)
    _add(kd, _dcc_source('Text'), 'allset.script_run', make_event('RET', ctrl=True), first=True, shadows=(_dcc_source('Text'),))
    _add(kd, _dcc_source('Text'), 'allset.script_run', make_event('NUMPAD_ENTER'), {'clear': True}, first=True, shadows=(_dcc_source('Text'), _dcc_source('Screen')))
MODE_KEYMAPS = (_dcc_source('Object Mode'), _dcc_source('Mesh'), _dcc_source('Pose'), _dcc_source('Curve'), _dcc_source('Curves'), _dcc_source('Armature'), _dcc_source('Metaball'), _dcc_source('Lattice'), _dcc_source('Particle'), _dcc_source('Paint Face Mask (Weight, Vertex, Texture)'), _dcc_source('Paint Vertex Selection (Weight, Vertex)'))
SCULPT_BRUSHES = (('ZERO', _dcc_source('Mask')), ('ONE', _dcc_source('Draw')), ('TWO', _dcc_source('Smooth')), ('THREE', _dcc_source('Relax Slide')), ('FOUR', _dcc_source('Grab')), ('FIVE', _dcc_source('Pinch/Magnify')), ('SIX', _dcc_source('Flatten/Contrast')), ('SEVEN', _dcc_source('Blob')), ('EIGHT', _dcc_source('Draw Sharp')), ('NINE', _dcc_source('Layer')))
SCULPT_LIBRARY = 'brushes/essentials_brushes-mesh_sculpt.blend/Brush/'
SEARCH_SHADOWS = (_dcc_source('Property Editor'), _dcc_source('Outliner'), _dcc_source('Graph Editor Generic'), _dcc_source('Node Editor'), _dcc_source('Dopesheet'), _dcc_source('NLA Generic'), _dcc_source('Text Generic'), _dcc_source('Animation Channels'), _dcc_source('Image Paint'), _dcc_source('Vertex Paint'), _dcc_source('Weight Paint'), _dcc_source('Sculpt'), _dcc_source('Grease Pencil Weight Paint'), _dcc_source('Preferences'), _dcc_source('Preferences_nav'))
BOOKMARK_KEYS = (('T', {'alt': True}, 'allset.bookmark_create', {}), ('T', {'alt': True, 'shift': True}, 'allset.bookmark_create', {'quick': True}), ('QUOTE', {}, 'screen.marker_jump', {'next': True}), ('SEMI_COLON', {}, 'screen.marker_jump', {'next': False}), ('BACK_SLASH', {'shift': True}, 'allset.bookmark_frame', {'which': 'CURRENT'}), ('QUOTE', {'shift': True}, 'allset.bookmark_frame', {'which': 'NEXT'}), ('SEMI_COLON', {'shift': True}, 'allset.bookmark_frame', {'which': 'PREVIOUS'}))

def _props_of(kd, km, idname, **ev):
    """Properties of the first matching item (to copy IC's radial-control settings onto a Maya key)."""
    found = kd.find(km, idname, **ev)
    return patch.props_dict(found[0][2]) if found else {}

def _remove_where(kd, km, predicate, **ev):
    if km not in kd.keymap_names():
        return []
    items = kd.items(km)
    found = [it for it in kd.find(km, **ev) if predicate(it)]
    items[:] = [it for it in items if not any((it is f for f in found))]
    return found

def patch_key_batch_3(kd):
    kd.remove(_dcc_source('Object Mode'), 'object.scale_clear', type='R', alt=True)
    kd.remove(_dcc_source('Pose'), 'pose.scale_clear', type='R', alt=True)
    _add(kd, '3D View', 'allset.symmetry', make_event('R', alt=True), {'mode': 'TOGGLE'}, shadows=(*VIEW3_SHADOWS, _dcc_source('Weight Paint')))
    for km in MODE_KEYMAPS:
        _remove_where(kd, km, lambda it: it[0].endswith('select_all'), type='I', ctrl=True)
    kd.remove('3D View', 'view3d.view_axis', type='F1')
    kd.remove(_dcc_source('Image'), 'image.view_zoom_ratio', type='F1')
    _add(kd, _dcc_source('Window'), 'wm.doc_view_manual_ui_context', make_event('F1'))
    kd.remove(_dcc_source('Mesh'), 'wm.tool_set_by_id', type='C', alt=True)
    _add(kd, _dcc_source('Weight Paint'), 'allset.color_feedback', make_event('C', alt=True))
    for km in MODE_KEYMAPS:
        _remove_where(kd, km, lambda it: it[0] == 'wm.tool_set_by_id' and patch.props_dict(it[2]).get('name') == 'builtin.measure', type='M')
    kd.remove(_dcc_source('Screen'), 'screen.workspace_cycle', type='PAGE_UP', ctrl=True)
    kd.remove(_dcc_source('Screen'), 'screen.workspace_cycle', type='PAGE_DOWN', ctrl=True)
    for (km, op) in ((_dcc_source('Object Mode'), 'object.select_hierarchy'), (_dcc_source('Pose'), 'pose.select_hierarchy')):
        _add(kd, km, op, make_event('PAGE_UP', ctrl=True), {'direction': 'CHILD', 'extend': False})
        _add(kd, km, op, make_event('PAGE_DOWN', ctrl=True), {'direction': 'PARENT', 'extend': False})
    kd.remove(_dcc_source('Screen'), 'screen.userpref_show', type='COMMA', ctrl=True)
    _add(kd, _dcc_source('Screen'), 'allset.main_menubar_toggle', make_event('M', ctrl=True), shadows=(_dcc_source('Grease Pencil Edit Mode'),))
    _add(kd, _dcc_source('Screen'), 'wm.context_toggle', make_event('M', shift=True), {'data_path': 'area.show_menus'}, shadows=(_dcc_source('Sequencer'),))
    _add(kd, '3D View', 'wm.context_toggle', make_event('M', ctrl=True, shift=True), {'data_path': 'space_data.show_region_header'}, shadows=VIEW3_SHADOWS)
    _add(kd, '3D View', 'allset.cycle_background', make_event('B', alt=True), shadows=VIEW3_SHADOWS)
    _add(kd, '3D View', 'allset.panel_set', make_event('FIVE', ctrl=True, shift=True), {'key': 'DEFAULT_MATERIAL'}, shadows=VIEW3_SHADOWS)
    _add(kd, _dcc_source('Screen'), 'wm.search_menu', make_event('F', ctrl=True), shadows=SEARCH_SHADOWS)
    size = _props_of(kd, _dcc_source('Weight Paint'), 'wm.radial_control', type='S')
    weight = _props_of(kd, _dcc_source('Weight Paint'), 'wm.radial_control', type='F', ctrl=True)
    kd.remove(_dcc_source('Weight Paint'), 'wm.radial_control', type='U')
    kd.remove(_dcc_source('Weight Paint'), 'wm.call_asset_shelf_popover', type='B')
    _add(kd, _dcc_source('Weight Paint'), 'wm.call_menu', make_event('U'), {'name': 'ALLSET_MT_paint_operation'})
    _add(kd, _dcc_source('Weight Paint'), 'wm.radial_control', make_event('N'), weight)
    _add(kd, _dcc_source('Weight Paint'), 'wm.radial_control', make_event('B'), size, shadows=('3D View',))
    _add(kd, _dcc_source('Weight Paint'), 'allset.flood_weights', make_event('F', alt=True))
    _add(kd, _dcc_source('Weight Paint'), 'allset.paint_copy_vertex_weights', make_event('C', ctrl=True, alt=True))
    _add(kd, _dcc_source('Weight Paint'), 'allset.paint_paste_vertex_weights', make_event('V', ctrl=True, alt=True))
    _add(kd, _dcc_source('Weight Paint'), 'allset.skin_paint_mode', make_event('PERIOD', ctrl=True), {_dcc_source('step'): 1})
    _add(kd, _dcc_source('Weight Paint'), 'allset.skin_paint_mode', make_event('COMMA', ctrl=True), {_dcc_source('step'): -1})
    _add(kd, _dcc_source('Weight Paint'), 'allset.paint_reflection', make_event('R', alt=True), shadows=('3D View',))
    _add(kd, _dcc_source('Mesh'), 'allset.copy_vertex_weights', make_event('C', ctrl=True, alt=True))
    _add(kd, _dcc_source('Mesh'), 'allset.paste_vertex_weights', make_event('V', ctrl=True, alt=True))
    size = _props_of(kd, _dcc_source('Sculpt'), 'wm.radial_control', type='S')
    strength = _props_of(kd, _dcc_source('Sculpt'), 'wm.radial_control', type='U')
    for n in range(6):
        kd.remove(_dcc_source('Sculpt'), 'object.subdivision_set', type=('ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE')[n], ctrl=True)
    for (key, brush) in SCULPT_BRUSHES:
        _add(kd, _dcc_source('Sculpt'), 'brush.asset_activate', make_event(key, ctrl=True), {'asset_library_type': 'ESSENTIALS', 'relative_asset_identifier': SCULPT_LIBRARY + brush}, shadows=('3D View',))
    kd.remove(_dcc_source('Sculpt'), 'wm.call_asset_shelf_popover', type='B')
    _add(kd, _dcc_source('Sculpt'), 'wm.radial_control', make_event('B'), size, shadows=('3D View',))
    _add(kd, _dcc_source('Sculpt'), 'wm.radial_control', make_event('M'), strength)
    _add(kd, _dcc_source('Sculpt'), 'paint.mask_flood_fill', make_event('U', shift=True), {'mode': 'VALUE', 'value': 0.0})
    _add(kd, _dcc_source('Sculpt'), 'paint.mask_flood_fill', make_event('I', ctrl=True, shift=True), {'mode': 'INVERT'})
    _add(kd, _dcc_source('Graph Editor'), 'anim.channels_setting_enable', make_event('H'), {'type': 'PROTECT'})
    _add(kd, _dcc_source('Graph Editor'), 'anim.channels_setting_disable', make_event('J'), {'type': 'PROTECT'})
    for (key, action) in (('G', 'RANGE'), ('T', 'CENTER'), ('H', 'LOCK'), ('J', 'UNLOCK')):
        _add(kd, _dcc_source('Dopesheet'), 'allset.dope_sheet_key', make_event(key), {'action': action}, shadows=(_dcc_source('Screen'),) if key == 'G' else ())
    for (key, mods, op, props) in BOOKMARK_KEYS:
        _add(kd, _dcc_source('Screen'), op, make_event(key, **mods), props, shadows=(_dcc_source('Clip Editor'), _dcc_source('Clip Graph Editor'), _dcc_source('Curve')))
    _add(kd, _dcc_source('UV Editor'), 'wm.context_toggle', make_event('SEVEN'), {'data_path': 'space_data.uv_editor.show_stretch'})
    if kd.find(_dcc_source('UV Editor'), 'uv.select_mode', type='FOUR'):
        kd.remove(_dcc_source('UV Editor'), 'uv.select_mode', type='FOUR')
    else:
        kd.remove(_dcc_source('UV Editor'), 'wm.context_toggle', type='FOUR')
    kd.remove(_dcc_source('UV Editor'), 'mesh.select_mode', type='ONE', ctrl=True)
    for (key, mode) in (('FOUR', 'WIREFRAME'), ('FIVE', 'SHADED'), ('SIX', 'IMAGE'), ('EIGHT', 'SHELL_BORDERS'), ('NINE', 'TEXTURE_BORDERS')):
        _add(kd, _dcc_source('UV Editor'), 'allset.uv_display', make_event(key), {'mode': mode})
    _add(kd, _dcc_source('UV Editor'), 'allset.uv_isolate', make_event('ONE', ctrl=True))
    _add(kd, _dcc_source('UV Editor'), 'allset.uv_delete', make_event('DEL'))
    _add(kd, _dcc_source('UV Editor'), 'allset.uv_create_shell', make_event('X', ctrl=True, shift=True))

def patch_menu_shortcuts(kd):
    kd.remove(_dcc_source('Window'), 'wm.call_menu', type='O', ctrl=True, shift=True)

def patch_repeat(kd):
    """Step 175: G = Maya repeat last, menu / shelf / marking commands too (operators/repeat_maya.py); Blender's
    screen.repeat_last only knows registered operators. Graph Editor G stays anim.scene_range_frame (step 70)."""
    kd.remove(_dcc_source('Screen'), 'screen.repeat_last', type='G')
    _add(kd, _dcc_source('Screen'), 'allset.repeat_last', make_event('G'), shadows=(_dcc_source('Graph Editor'), _dcc_source('Dopesheet'), _dcc_source('Grease Pencil Edit Mode')))

def patch_blender_render(kd):
    _add(kd, _dcc_source('Screen'), 'allset.render_blender', make_event('F12'), {'use_viewport': True}, first=True, shadows=(_dcc_source('Object Mode'), _dcc_source('Mesh'), UV_KM))
    _add(kd, UV_KM, 'allset.uv_component', make_event('F12'), {'mode': 'UV'}, shadows=(_dcc_source('Screen'),))
    _add(kd, _dcc_source('Screen'), 'allset.render_blender', make_event('F12', ctrl=True), {'animation': True, 'use_viewport': True}, first=True)
    if kd.remove(_dcc_source('Screen Editing'), 'render.render', type='RET', ctrl=True, alt=True):
        _add(kd, _dcc_source('Screen Editing'), 'allset.render_blender', make_event('RET', ctrl=True, alt=True), {'animation': True, 'use_viewport': True}, first=True)
PATCHES = (patch_selection, patch_display, patch_group, patch_space, patch_hold_snap, patch_soft_select, patch_tap_hold_and_pivot, patch_pick_walk, patch_camera, patch_view_history, patch_space_tap, patch_smooth_preview, patch_component_keys, patch_cb_slider, patch_marking_menus, patch_concepts, patch_attribute_editor, patch_undo_visibility, patch_mesh_components, patch_key_stepping, patch_manip_duplicate, patch_component_delete, patch_view_keys, patch_active_handle, patch_materials, patch_uv_shell_select, patch_select_through, patch_key_batch, patch_component_pick_walk, patch_toolbox_guard, patch_select_priority, patch_pose_joints, patch_time_slider, patch_joints, patch_uv, patch_scene_files, patch_graph_keys, patch_key_batch_2, patch_outliner_drag, patch_key_insert, patch_time_range, patch_manip_ctrl, patch_view_keys_3, patch_global_keys_4, patch_graph_keys_2, patch_outliner_sets, patch_render_slots, patch_graph_outliner, patch_shelf_scroll, patch_script_editor, patch_key_batch_3, patch_menu_shortcuts, patch_repeat, patch_blender_render)

def patch_weight_paint_exit(kd):
    """Maya's Q/W/E/R change the global tool, leaving weight painting."""
    for (key, tool) in (('Q', 'builtin.select_box'), ('W', 'builtin.move'), ('E', 'builtin.rotate'), ('R', 'builtin.scale')):
        _remove_where(kd, _dcc_source('Weight Paint'), lambda it: it[0] == 'wm.tool_set_by_id', type=key)
        _add(kd, _dcc_source('Weight Paint'), 'allset.weight_paint_exit', make_event(key), {'tool': tool}, first=True, shadows=('3D View',))
PATCHES += (patch_weight_paint_exit,)

def apply(data):
    """Apply all patches to IC data in place and return it."""
    ADDED.clear()
    kd = KeyconfigData(data)
    for apply_patch in PATCHES:
        apply_patch(kd)
    return data
