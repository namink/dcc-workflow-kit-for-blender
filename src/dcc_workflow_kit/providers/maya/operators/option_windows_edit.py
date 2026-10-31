# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Step 140 Maya option windows: modeling, parenting and key commands (issues #33, #35).

Same spec as operators/option_windows.py (``F`` fields, ``Window`` = one ``allset.opt_<key>`` operator); labels and
factory defaults are Maya 2022's; what the values do matches Maya.
option_windows.py appends ``WINDOWS`` to its own list, so this
module only imports ``F`` / ``Window`` / helpers from it. Maya fields Blender can't honour are listed in ``missing``
(drawn greyed), never as fields. Plan / decisions: docs/steps/step_140.md, docs/steps/step_140_edit.md.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import math
import bpy
from mathutils import Vector
from .option_windows import F, Window, _components, _k
_OBJECTS = F('objects', _dcc_source('Objects:'), 'enum', _dcc_source('Selected'), items=(_dcc_source('Selected'), _dcc_source('All')), translation_context='MWK:operators/option_windows_edit.py:22')

def _scope_fields(objects=True):
    """The rows every Maya key command window starts with."""
    return ([_OBJECTS] if objects else []) + [F('hierarchy', _dcc_source('Hierarchy:'), 'enum', _dcc_source('Selected'), items=(_dcc_source('Selected'), _dcc_source('Below')), translation_context='MWK:operators/option_windows_edit.py:28'), F('channels', _dcc_source('Channels:'), 'enum', _dcc_source('All keyable'), items=(_dcc_source('All keyable'), _dcc_source('From Channel Box')), translation_context='MWK:operators/option_windows_edit.py:29'), F('driven', _dcc_source('Driven channels:'), 'bool', False, translation_context='MWK:operators/option_windows_edit.py:30'), F('shapes', _dcc_source('Shapes:'), 'bool', True, translation_context='MWK:operators/option_windows_edit.py:31'), F('time_range', _dcc_source('Time range:'), 'enum', _dcc_source('All'), items=(_dcc_source('All'), _dcc_source('Start/End'), _dcc_source('Time Slider')), translation_context='MWK:operators/option_windows_edit.py:32'), F('start', _dcc_source('Start time:'), 'float', 0.0, lo=-1000000.0, hi=1000000.0, translation_context='MWK:operators/option_windows_edit.py:33'), F('end', _dcc_source('End time:'), 'float', 10.0, lo=-1000000.0, hi=1000000.0, translation_context='MWK:operators/option_windows_edit.py:34')]
_CONTROL_POINTS = _dcc_source('Control points (Blender animates no vertices: shape keys are the Shapes)')

def _tk():
    from . import time_keys
    return time_keys

def _scope(context, v):
    tk = _tk()
    scope = tk.KeyScope.of(v)
    if not tk.scope_nodes(context, scope):
        raise RuntimeError(_dcc_source('Nothing selected.'))
    return scope

def _done(context):
    for area in context.screen.areas if context.screen else ():
        area.tag_redraw()
    return {'FINISHED'}

def _gkm():
    from . import graph_key_menu
    return graph_key_menu

def _on_selected(context, v):
    """Maya fromGraphEditor rule (Cut / Copy / Paste Keys & co.): a key window opened from a Graph Editor / Dope Sheet
    menu with keys selected and Method Keys acts on those keys, not on the nodes' time range (step 157)."""
    g = _gkm()
    return g.in_key_editor(context) and v.get('method', _dcc_source('Keys')) == _dcc_source('Keys') and g.has_selected_keys(context)

def _run_delete(context, v):
    if _on_selected(context, v):
        _gkm().delete_selected(context)
        return _done(context)
    _tk().delete_scope(context, _scope(context, v), v['method'], v['adjustment'], v['connect'])
    return _done(context)

def _run_cut(context, v):
    if _on_selected(context, v):
        _gkm().cut_selected(context)
        return _done(context)
    _tk().delete_scope(context, _scope(context, v), v['method'], v['adjustment'], v['connect'], clipboard=True)
    return _done(context)

def _run_copy(context, v):
    if _on_selected(context, v):
        _gkm().copy_selected(context)
        return _done(context)
    _tk().copy_scope(context, _scope(context, v), v['method'])
    return _done(context)

def _run_paste(context, v):
    g = _gkm()
    if g.in_key_editor(context) and g.editor_clipboard():
        if not g.paste_editor(context, time_range=v['time_range'], time_offset=v['time_offset'], value_offset=v['value_offset'], copies=v['copies'], method=v['method']):
            raise RuntimeError(_dcc_source('Nothing to paste: copy or cut keys first.'))
        return _done(context)
    tk = _tk()
    if not tk._CLIPBOARD.get('nodes'):
        raise RuntimeError(_dcc_source('The animation clipboard is empty: copy or cut keys first.'))
    if not tk.nodes(context):
        raise RuntimeError(_dcc_source('Nothing selected.'))
    tk.paste_scope(context, time_range=v['time_range'], start=v['start'], end=v['end'], time_offset=v['time_offset'], value_offset=v['value_offset'], copies=v['copies'], method=v['method'], replace_region=v['replace_region'])
    return _done(context)

def _run_scale(context, v):
    if _gkm().in_key_editor(context) and _gkm().has_selected_keys(context):
        _gkm().scale_selected(context, v['method'], v['time_scale'], v['time_pivot'], v['value_scale'], v['value_pivot'], v['new_start'], v['new_end'])
        return _done(context)
    _tk().scale_scope(context, _scope(context, v), v['method'], v['only_specified'], v['time_scale'], v['time_pivot'], v['value_scale'], v['value_pivot'], v['new_start'], v['new_end'])
    return _done(context)

def _run_snap(context, v):
    if _gkm().in_key_editor(context) and _gkm().has_selected_keys(context):
        _gkm().snap_selected(context, v['snap'], v['time_multiple'], v['value_multiple'])
        return _done(context)
    _tk().snap_scope(context, _scope(context, v), v['snap'], v['time_multiple'], v['value_multiple'])
    return _done(context)

def _paths(command, edit):
    """Main-menu paths of a key window + the Graph Editor / Dope Sheet Edit menu box (step 157)."""
    return (f'Key/{command}', f'Edit/Keys/{command}', f'Graph Editor/Edit/{edit}', f'Dope Sheet/Edit/{edit}')
_DELETE_TAIL = [F('method', _dcc_source('Method:'), 'enum', _dcc_source('Keys'), items=(_dcc_source('Keys'), _dcc_source('Segments')), translation_context='MWK:operators/option_windows_edit.py:139'), F('adjustment', _dcc_source('Adjustment:'), 'enum', _dcc_source('None'), items=(_dcc_source('None'), _dcc_source('Collapse')), translation_context='MWK:operators/option_windows_edit.py:140'), F('connect', _dcc_source('Connect:'), 'bool', False, translation_context='MWK:operators/option_windows_edit.py:141')]
KEY_WINDOWS = [Window('delete_keys', _dcc_source('Delete Keys Options'), _dcc_source('Delete Keys'), None, _scope_fields() + _DELETE_TAIL, _run_delete, paths=_paths(_dcc_source('Delete Keys'), _dcc_source('Delete')), missing=(_CONTROL_POINTS,), translation_context='MWK:operators/option_windows_edit.py:144'), Window('cut_keys', _dcc_source('Cut Keys Options'), _dcc_source('Cut Keys'), None, _scope_fields(objects=False) + _DELETE_TAIL, _run_cut, paths=_paths(_dcc_source('Cut Keys'), _dcc_source('Cut')), missing=(_CONTROL_POINTS, _dcc_source('Method: Range (cutKey has no area option)')), translation_context='MWK:operators/option_windows_edit.py:146'), Window('copy_keys', _dcc_source('Copy Keys Options'), _dcc_source('Copy Keys'), None, _scope_fields(objects=False) + [F('method', _dcc_source('Method:'), 'enum', _dcc_source('Keys'), items=(_dcc_source('Keys'), _dcc_source('Segments')), translation_context='MWK:operators/option_windows_edit.py:150')], _run_copy, paths=_paths(_dcc_source('Copy Keys'), _dcc_source('Copy')), missing=(_CONTROL_POINTS, _dcc_source('Method: Range (copyKey has no area option)')), translation_context='MWK:operators/option_windows_edit.py:149'), Window('paste_keys', _dcc_source('Paste Keys Options'), _dcc_source('Paste Keys'), None, [F('time_range', _dcc_source('Time range:'), 'enum', _dcc_source('Current'), items=(_dcc_source('Start'), _dcc_source('Start/End'), _dcc_source('Current'), _dcc_source('Clipboard')), translation_context='MWK:operators/option_windows_edit.py:154'), F('start', _dcc_source('Start time:'), 'float', 0.0, lo=-1000000.0, hi=1000000.0, translation_context='MWK:operators/option_windows_edit.py:155'), F('end', _dcc_source('End time:'), 'float', 10.0, lo=-1000000.0, hi=1000000.0, translation_context='MWK:operators/option_windows_edit.py:155'), F('time_offset', _dcc_source('Time offset:'), 'float', 0.0, lo=-1000000.0, hi=1000000.0, translation_context='MWK:operators/option_windows_edit.py:156'), F('value_offset', _dcc_source('Value offset:'), 'float', 0.0, lo=-1000000.0, hi=1000000.0, translation_context='MWK:operators/option_windows_edit.py:157'), F('copies', _dcc_source('Copies:'), 'int', 1, lo=1, hi=100, translation_context='MWK:operators/option_windows_edit.py:158'), F('method', _dcc_source('Paste method:'), 'enum', _dcc_source('Merge'), items=(_dcc_source('Insert'), _dcc_source('Replace'), _dcc_source('Merge')), translation_context='MWK:operators/option_windows_edit.py:159'), F('replace_region', _dcc_source('Replace region:'), 'enum', _dcc_source('Time range'), items=(_dcc_source('Time range'), _dcc_source('Entire curve')), translation_context='MWK:operators/option_windows_edit.py:160')], _run_paste, paths=_paths(_dcc_source('Paste Keys'), _dcc_source('Paste')), missing=(_dcc_source('Selected keys override specified time range'), _dcc_source('Clipboard adjustment: Scale / Fit (Preserve only)'), _dcc_source('Connect')), translation_context='MWK:operators/option_windows_edit.py:153'), Window('scale_keys', _dcc_source('Scale Keys Options'), _dcc_source('Scale Keys'), None, _scope_fields() + [F('method', _dcc_source('Method:'), 'enum', _dcc_source('Scale/Pivot'), items=(_dcc_source('Scale/Pivot'), _dcc_source('Start/End')), translation_context='MWK:operators/option_windows_edit.py:165'), F('only_specified', '', 'bool', True, text=_zh_native('Only scale specified keys', 'MWK:operators/option_windows_edit.py:166'), translation_context='MWK:operators/option_windows_edit.py:166'), F('time_scale', _dcc_source('Time scale:'), 'float', 1.0, lo=-1000000.0, hi=1000000.0, translation_context='MWK:operators/option_windows_edit.py:167'), F('time_pivot', _dcc_source('Time pivot:'), 'float', 0.0, lo=-1000000.0, hi=1000000.0, translation_context='MWK:operators/option_windows_edit.py:168'), F('value_scale', _dcc_source('Value scale:'), 'float', 1.0, lo=-1000000.0, hi=1000000.0, translation_context='MWK:operators/option_windows_edit.py:169'), F('value_pivot', _dcc_source('Value pivot:'), 'float', 0.0, lo=-1000000.0, hi=1000000.0, translation_context='MWK:operators/option_windows_edit.py:170'), F('new_start', _dcc_source('New start time:'), 'float', 1.0, lo=-1000000.0, hi=1000000.0, translation_context='MWK:operators/option_windows_edit.py:171'), F('new_end', _dcc_source('New end time:'), 'float', 10.0, lo=-1000000.0, hi=1000000.0, translation_context='MWK:operators/option_windows_edit.py:172')], _run_scale, paths=_paths(_dcc_source('Scale Keys'), _dcc_source('Scale')), missing=(_CONTROL_POINTS,), translation_context='MWK:operators/option_windows_edit.py:164'), Window('snap_keys', _dcc_source('Snap Keys Options'), _dcc_source('Snap Keys'), None, _scope_fields() + [F('snap', _dcc_source('Snap:'), 'enum', _dcc_source('Times'), items=(_dcc_source('Times'), _dcc_source('Values'), _dcc_source('Both')), translation_context='MWK:operators/option_windows_edit.py:175'), F('time_multiple', _dcc_source('Snap times to multiple of:'), 'float', 1.0, lo=0.0, hi=1000.0, translation_context='MWK:operators/option_windows_edit.py:176'), F('value_multiple', _dcc_source('Snap values to multiple of:'), 'float', 1.0, lo=0.0, hi=1000.0, translation_context='MWK:operators/option_windows_edit.py:177')], _run_snap, paths=_paths(_dcc_source('Snap Keys'), _dcc_source('Snap')), missing=(_CONTROL_POINTS,), translation_context='MWK:operators/option_windows_edit.py:174')]

def _run_parent(context, v):
    return bpy.ops.allset.parent('EXEC_DEFAULT', preserve_position=v['preserve'])

def _run_unparent(context, v):
    return bpy.ops.allset.unparent('EXEC_DEFAULT', preserve_position=v['preserve'])

def _run_ungroup(context, v):
    if not any((ob.children for ob in context.selected_objects)):
        raise RuntimeError(_dcc_source('Select a group to ungroup.'))
    return bpy.ops.allset.ungroup('EXEC_DEFAULT', under='WORLD' if v['under'] == _dcc_source('World') else 'PARENT', preserve_position=v['preserve'])

def _run_duplicate_special(context, v):
    if v['smart']:
        res = {'CANCELLED'}
        for _i in range(max(1, v['copies'])):
            res = bpy.ops.allset.duplicate_with_transform('EXEC_DEFAULT')
            if res != {'FINISHED'}:
                break
        return res
    k = _k(context)
    return bpy.ops.allset.duplicate_special('EXEC_DEFAULT', geometry_type=v['geometry_type'].upper(), group_under={_dcc_source('Parent'): 'PARENT', _dcc_source('World'): 'WORLD', _dcc_source('New group'): 'NEW_GROUP'}[v['group_under']], translate=Vector((v['translate'][0], -v['translate'][2], v['translate'][1])) * k, rotate=tuple((math.radians(a) for a in (v['rotate'][0], -v['rotate'][2], v['rotate'][1]))), scale=(v['scale'][0], v['scale'][2], v['scale'][1]), copies=v['copies'])
_PRESERVE = F('preserve', '', 'bool', True, text=_zh_native('Preserve position', 'MWK:operators/option_windows_edit.py:219'), translation_context='MWK:operators/option_windows_edit.py:219')
EDIT_WINDOWS = [Window('parent', _dcc_source('Parent Options'), _dcc_source('Parent'), ('allset.parent', {}), [_PRESERVE], _run_parent, paths=('Edit/Parent',), missing=(_dcc_source('Parent method: Add instance (Blender objects have one parent)'),), translation_context='MWK:operators/option_windows_edit.py:222'), Window('unparent', _dcc_source('Unparent Options'), _dcc_source('Unparent'), ('allset.unparent', {}), [_PRESERVE], _run_unparent, paths=('Edit/Unparent',), missing=(_dcc_source('Unparent method: Remove instance'),), translation_context='MWK:operators/option_windows_edit.py:224'), Window('ungroup', _dcc_source('Ungroup Options'), _dcc_source('Ungroup'), ('allset.ungroup', {}), [F('under', _dcc_source('Ungroup under:'), 'enum', _dcc_source('Parent'), items=(_dcc_source('Parent'), _dcc_source('World')), translation_context='MWK:operators/option_windows_edit.py:227'), _PRESERVE], _run_ungroup, paths=('Edit/Ungroup',), translation_context='MWK:operators/option_windows_edit.py:226'), Window('duplicate_special_maya', _dcc_source('Duplicate Special Options'), _dcc_source('Duplicate Special'), None, [F('geometry_type', _dcc_source('Geometry type:'), 'enum', _dcc_source('Copy'), items=(_dcc_source('Copy'), _dcc_source('Instance')), translation_context='MWK:operators/option_windows_edit.py:232'), F('group_under', _dcc_source('Group under:'), 'enum', _dcc_source('Parent'), items=(_dcc_source('Parent'), _dcc_source('World'), _dcc_source('New group')), translation_context='MWK:operators/option_windows_edit.py:233'), F('smart', '', 'bool', False, text=_zh_native('Smart transform', 'MWK:operators/option_windows_edit.py:234'), translation_context='MWK:operators/option_windows_edit.py:234'), F('translate', _dcc_source('Translate:'), 'vec3', (0.0, 0.0, 0.0), translation_context='MWK:operators/option_windows_edit.py:235'), F('rotate', _dcc_source('Rotate:'), 'vec3', (0.0, 0.0, 0.0), translation_context='MWK:operators/option_windows_edit.py:235'), F('scale', _dcc_source('Scale:'), 'vec3', (1.0, 1.0, 1.0), translation_context='MWK:operators/option_windows_edit.py:236'), F('copies', _dcc_source('Number of copies:'), 'int', 1, lo=1, hi=1000, translation_context='MWK:operators/option_windows_edit.py:236')], _run_duplicate_special, paths=('Edit/Duplicate Special',), missing=(_dcc_source('Duplicate input graph'), _dcc_source('Duplicate input connections'), _dcc_source('Instance leaf nodes'), _dcc_source('Assign unique name to children nodes')), translation_context='MWK:operators/option_windows_edit.py:231')]

def _edit_only(context):
    from .poly_maya import CONNECT_WARNING
    if context.mode != 'EDIT_MESH':
        raise RuntimeError(CONNECT_WARNING)

def _run_connect(context, v):
    _edit_only(context)
    return bpy.ops.allset.connect('EXEC_DEFAULT', insert_with_edge_flow=v['edge_flow'], adjust_edge_flow=v['adjust_edge_flow'])

def _run_connect_tool(context, v):
    _edit_only(context)
    return bpy.ops.allset.connect('EXEC_DEFAULT', segments=v['segments'], slide=v['slide'])

def _run_circularize(context, v):
    k = _k(context)
    return _components(context, 'allset.circularize', 'VERT', normal_offset=v['normal_offset'] * k, radial_offset=v['radial_offset'] * k, twist=math.radians(v['twist']), evenly_distribute=v['evenly'], divisions=v['divisions'])

def _run_make_hole(context, v):
    if context.mode != 'EDIT_MESH':
        raise RuntimeError(_dcc_source('Select the face to cut, then the face whose shape makes the hole.'))
    return bpy.ops.allset.make_hole('EXEC_DEFAULT', merge_mode=v['merge_mode'])
_MAINTAIN = {_dcc_source('Relative distance from edge'): 'RELATIVE', _dcc_source('Equal distance from edge'): 'EQUAL', _dcc_source('Multiple edge loops'): 'MULTIPLE'}

def insert_edge_loop_options(context, v):
    """Put the Insert Edge Loop window's values on the kit tool's settings (Scene.allset_loop_tools, step 144 LOOP;
    step 140 put them on Blender's Loop Cut tool). Returns the settings."""
    from . import edge_loops
    s = edge_loops.settings(context)
    s.iel_position = _MAINTAIN[v['maintain']]
    s.iel_loops = v['loops']
    s.iel_edge_flow = v['edge_flow']
    s.iel_adjust_flow = v['adjust_edge_flow']
    s.iel_smoothing = v['smoothing']
    return s

def offset_edge_loop_options(context, v):
    """The Offset Edge Loop Options values on the kit tool's settings (step 144 LOOP)."""
    from . import edge_loops
    s = edge_loops.settings(context)
    s.oel_delete_edge = v['delete_edge']
    s.oel_edge_flow = v['edge_flow']
    s.oel_adjust_flow = v['adjust_edge_flow']
    s.oel_smoothing = v['smoothing']
    s.oel_position = _MAINTAIN[v['maintain']]
    return s

def _run_insert_edge_loop(context, v):
    from . import edge_loops
    insert_edge_loop_options(context, v)
    return bpy.ops.allset.menu_tool('EXEC_DEFAULT', tool=edge_loops.INSERT_TOOL, edit=True)

def _run_offset_edge_loop(context, v):
    """Maya "Enter Tool": the values go to the tool, then the tool starts."""
    from . import edge_loops
    offset_edge_loop_options(context, v)
    return bpy.ops.allset.menu_tool('EXEC_DEFAULT', tool=edge_loops.OFFSET_TOOL, edit=True)
MESH_WINDOWS = [Window('connect', _dcc_source('Connect Components Options'), _dcc_source('Connect'), None, [F('edge_flow', '', 'bool', False, text=_zh_native('Insert with edge flow', 'MWK:operators/option_windows_edit.py:319'), translation_context='MWK:operators/option_windows_edit.py:319'), F('adjust_edge_flow', _dcc_source('Adjust Edge Flow:'), 'float', 1.0, lo=-1.0, hi=2.0, translation_context='MWK:operators/option_windows_edit.py:320')], _run_connect, paths=('Edit Mesh/Connect',), translation_context='MWK:operators/option_windows_edit.py:318'), Window('connect_tool', _dcc_source('Connect Tool'), _dcc_source('Connect'), None, [F('slide', _dcc_source('Slide:'), 'float', 0.5, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_edit.py:323'), F('segments', _dcc_source('Segments:'), 'int', 1, lo=1, hi=10, translation_context='MWK:operators/option_windows_edit.py:323')], _run_connect_tool, paths=('Mesh Tools/Connect',), missing=(_dcc_source('Pinch'), _dcc_source('Active option (MMB drag) / Keyboard and mouse shortcuts')), translation_context='MWK:operators/option_windows_edit.py:322'), Window('circularize', _dcc_source('Polygon Circularize Options'), _dcc_source('Circularize'), ('allset.circularize', {}), [F('normal_offset', _dcc_source('Normal Offset:'), 'length', 0.0, lo=-100.0, hi=100.0, translation_context='MWK:operators/option_windows_edit.py:327'), F('radial_offset', _dcc_source('Radial Offset:'), 'length', 0.0, lo=-100.0, hi=100.0, translation_context='MWK:operators/option_windows_edit.py:328'), F('twist', _dcc_source('Twist:'), 'float', 0.0, lo=-360.0, hi=360.0, translation_context='MWK:operators/option_windows_edit.py:329'), F('evenly', _dcc_source('Evenly Distribute:'), 'bool', True, translation_context='MWK:operators/option_windows_edit.py:330'), F('divisions', _dcc_source('Add Divisions:'), 'int', 0, lo=0, hi=50, translation_context='MWK:operators/option_windows_edit.py:331')], _run_circularize, paths=('Edit Mesh/Circularize',), missing=(_dcc_source('Relax Interior'), _dcc_source('Alignment: Automatic / Surface'), _dcc_source('Smoothing Angle'), _dcc_source('Supporting Edges')), translation_context='MWK:operators/option_windows_edit.py:326'), Window('make_hole', _dcc_source('Make Hole Tool'), _dcc_source('Make Hole'), None, [F('merge_mode', _dcc_source('Merge mode:'), 'enum', _dcc_source('None'), items=(_dcc_source('First'), _dcc_source('Middle'), _dcc_source('Second'), _dcc_source('Project First'), _dcc_source('Project Middle'), _dcc_source('Project Second'), _dcc_source('None')), translation_context='MWK:operators/option_windows_edit.py:335')], _run_make_hole, paths=('Mesh Tools/Make Hole',), translation_context='MWK:operators/option_windows_edit.py:334'), Window('insert_edge_loop', _dcc_source('Insert Edge Loop Tool'), _dcc_source('Insert Edge Loop'), None, [F('maintain', _dcc_source('Maintain position:'), 'enum', _dcc_source('Relative distance from edge'), items=(_dcc_source('Relative distance from edge'), _dcc_source('Equal distance from edge'), _dcc_source('Multiple edge loops')), translation_context='MWK:operators/option_windows_edit.py:339'), F('loops', _dcc_source('Number of edge loops:'), 'int', 2, lo=1, hi=100, translation_context='MWK:operators/option_windows_edit.py:341'), F('edge_flow', '', 'bool', False, text=_zh_native('Insert with edge flow', 'MWK:operators/option_windows_edit.py:342'), translation_context='MWK:operators/option_windows_edit.py:342'), F('adjust_edge_flow', _dcc_source('Adjust Edge Flow:'), 'float', 1.0, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_edit.py:343'), F('smoothing', _dcc_source('Smoothing angle:'), 'float', 30.0, lo=0.0, hi=180.0, translation_context='MWK:operators/option_windows_edit.py:344')], _run_insert_edge_loop, paths=('Mesh Tools/Insert Edge Loop',), missing=(_dcc_source('Use Equal Multiplier (always on)'), _dcc_source('Auto complete (always on)'), _dcc_source('Fix Quads (always on)')), translation_context='MWK:operators/option_windows_edit.py:338'), Window('offset_edge_loop', _dcc_source('Offset Edge Loop Options'), _dcc_source('Enter Tool And Close'), None, [F('delete_edge', '', 'bool', True, text=_zh_native('Delete edge (maintain 4-sided polygons)', 'MWK:operators/option_windows_edit.py:349'), translation_context='MWK:operators/option_windows_edit.py:349'), F('edge_flow', '', 'bool', False, text=_zh_native('Insert with edge flow', 'MWK:operators/option_windows_edit.py:350'), translation_context='MWK:operators/option_windows_edit.py:350'), F('adjust_edge_flow', _dcc_source('Adjust Edge Flow:'), 'float', 1.0, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_edit.py:351'), F('smoothing', _dcc_source('Smoothing angle:'), 'float', 180.0, lo=0.0, hi=180.0, translation_context='MWK:operators/option_windows_edit.py:352'), F('maintain', _dcc_source('Maintain position:'), 'enum', _dcc_source('Relative distance from edge'), items=(_dcc_source('Relative distance from edge'), _dcc_source('Equal distance from edge')), translation_context='MWK:operators/option_windows_edit.py:353')], _run_offset_edge_loop, paths=('Mesh Tools/Offset Edge Loop',), apply_text=_dcc_source('Enter Tool'), missing=('Start/End vertex offset (0)', _dcc_source('Tool completion: Press enter (the loops are made on release)')), translation_context='MWK:operators/option_windows_edit.py:348')]
NONDEF_ALL = _dcc_source('All non-deformer history')
NONDEF_PRE = _dcc_source('History before deformers only')

def _run_non_deformer(context, v):
    return bpy.ops.allset.delete_history('EXEC_DEFAULT', non_deformer=True, before_only=v['delete'] == NONDEF_PRE)
HISTORY_WINDOWS = [Window('non_deformer_history', _dcc_source('Delete Non Deformer History Options'), _dcc_source('Delete'), None, [F('delete', _dcc_source('Delete:'), 'enum', NONDEF_ALL, items=(NONDEF_ALL, NONDEF_PRE), translation_context='MWK:operators/option_windows_edit.py:373')], _run_non_deformer, paths=('Edit/Delete by Type/Non-Deformer History',), translation_context='MWK:operators/option_windows_edit.py:372')]
WINDOWS = KEY_WINDOWS + EDIT_WINDOWS + MESH_WINDOWS + HISTORY_WINDOWS
