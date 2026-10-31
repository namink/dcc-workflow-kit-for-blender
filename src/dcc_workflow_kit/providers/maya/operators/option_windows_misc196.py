# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Step 196 (issue #103) lane B: Maya option windows that were Blender's Adjust Last Operation ("redo") or the generic
"no settings" window — Create Character Set / Subcharacter Set, Curves Cut / Detach / Reverse Direction / Smooth (both)
/ Straighten, the circular arc tools, UV Merge UVs / Contour Stretch, Set / Assume Preferred Angle, Add Influence.

Same spec as operators/option_windows.py (``F`` fields, ``Window`` = one ``allset.opt_<key>`` operator, bound to its
menu paths; option_windows._extend appends ``WINDOWS``). Titles, buttons, labels and factory values come from Maya
2022's option windows; fields the kit
can't honour are only listed (``missing``), never faked. Every window run with its defaults does what the plain menu
item does; Merge UVs / Smooth (Modify section) run the kit's Maya operators, like their plain menu items
(menu_map, step 196).
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import bpy
from .option_windows import F, Window, _op
from .option_windows_rig import FText
_ATTRS = {_dcc_source('All keyable'): 'ALL', _dcc_source('From Channel Box'): 'CHANNEL_BOX', _dcc_source('All keyable except:'): 'EXCEPT'}

def _character(sub):

    def run(context, v):
        return bpy.ops.allset.character_create('EXEC_DEFAULT', sub=sub, character_name=v['name'], attributes=_ATTRS[v['attributes']], exclude_translate=v['no_translate'], exclude_rotate=v['no_rotate'], exclude_scale=v['no_scale'], exclude_visibility=v['no_visibility'], exclude_dynamic=v['no_dynamic'], hierarchy=v.get('hierarchy', False))
    return run

def _run_cut(context, v):
    return bpy.ops.allset.curve_cut('EXEC_DEFAULT', last_only=v['cut'] == _dcc_source('Using last curve'), keep_longest=v['keep'] == _dcc_source('Longest segments'))

def _run_detach(context, v):
    return bpy.ops.allset.curve_detach('EXEC_DEFAULT')

def _keep_copies(context, suffix):
    """Maya Keep original (object mode): the selected curves are duplicated, the copies — named
    ``<curve><suffix>N`` (``curveAreversedCurve1``, ``curveAsmoothCurve1``) — become the selection and get the
    command; the originals stay unchanged."""
    from . import naming
    if context.mode != 'OBJECT':
        return
    originals = [o for o in context.selected_objects if o.type == 'CURVE']
    for o in context.selected_objects:
        if o.type != 'CURVE':
            o.select_set(False)
    copies = []
    for o in originals:
        c = o.copy()
        c.data = o.data.copy()
        for coll in o.users_collection:
            coll.objects.link(c)
        naming.apply_maya_name(c, f'{o.name}{suffix}')
        o.select_set(False)
        c.select_set(True)
        copies.append(c)
    if copies:
        context.view_layer.objects.active = copies[-1]

def _run_reverse(context, v):
    """Curves > Reverse Direction: Blender's Switch Direction in edit mode (the plain item); in object mode every
    selected curve is reversed whole (CVs reversed, knots mirrored)."""
    if v['keep_original']:
        _keep_copies(context, 'reversedCurve')
    if context.mode == 'EDIT_CURVE':
        return _op('curve.switch_direction')
    from . import curves_maya as cmaya
    from . import curves_math as cm
    obs = [o for o in context.selected_objects if o.type == 'CURVE']
    if not obs:
        raise RuntimeError(_dcc_source('Select curves to reverse'))
    for ob in obs:
        out = []
        for sp in ob.data.splines:
            c = cmaya.read_spline(sp)
            if sp.type != 'BEZIER':
                res = cm.reverse(c.cvs, c.knots, c.weights)
                c = cmaya.MCurve(res[0], res[1], c.degree, res[2] if len(res) > 2 else None, c.periodic)
            out.append(c)
        cmaya._replace_splines(ob, out)
    return {'FINISHED'}

def _run_smooth_curves(context, v):
    return bpy.ops.allset.curve_smooth_curves('EXEC_DEFAULT', factor=v['factor'])

def _run_smooth_curve(context, v):
    """Curves > Smooth (Edit section): Blender's curve Smooth on the selected points (the plain item); Keep original
    smooths copies (all their points)."""
    if not v['keep_original'] or context.mode != 'OBJECT':
        return _op('curve.smooth')
    _keep_copies(context, 'smoothCurve')
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        bpy.ops.curve.select_all(action='SELECT')
        return _op('curve.smooth')
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

def _run_straighten(context, v):
    return bpy.ops.allset.curve_straighten('EXEC_DEFAULT', straightness=v['straightness'], preserve_length=v['preserve_length'])

def _arc(op_name):

    def run(context, v):
        op = getattr(bpy.ops.allset, op_name)
        return op('INVOKE_DEFAULT', degree=1 if v['degree'].startswith('1') else 3, sections=v['sections'])
    return run

def _run_merge_uvs(context, v):
    return bpy.ops.allset.uv_merge('EXEC_DEFAULT', distance=v['threshold'])

def _run_contour(context, v):
    return bpy.ops.allset.uv_contour('EXEC_DEFAULT')

def _preferred(op_name):

    def run(context, v):
        return getattr(bpy.ops.allset, op_name)('EXEC_DEFAULT', hierarchy=v['options'] == _dcc_source('Hierarchy'))
    return run

def _run_add_influence(context, v):
    return bpy.ops.allset.add_influence('EXEC_DEFAULT', lock_weights=v['lock_weights'], default_weight=v['default_weight'])
_INCLUDE = (_dcc_source('All keyable'), _dcc_source('From Channel Box'), _dcc_source('All keyable except:'))
_KEEP_ORIGINAL = _dcc_source('Keep original (Maya keeps the input curve and makes new ones)')
WINDOWS = [Window('character_set', _dcc_source('Create Character Set Options'), _dcc_source('Create Character Set'), None, [FText('name', _dcc_source('Name:'), 'character1'), F('hierarchy', _dcc_source('Include:'), 'bool', False, text=_zh_native('Hierarchy below selected node', 'MWK:operators/option_windows_misc196.py:152'), translation_context='MWK:operators/option_windows_misc196.py:152'), F('attributes', _dcc_source('Include:'), 'enum', _dcc_source('All keyable except:'), items=_INCLUDE, translation_context='MWK:operators/option_windows_misc196.py:153'), F('no_translate', '', 'bool', False, text=_zh_native('Translate', 'MWK:operators/option_windows_misc196.py:154'), translation_context='MWK:operators/option_windows_misc196.py:154'), F('no_rotate', '', 'bool', False, text=_zh_native('Rotate', 'MWK:operators/option_windows_misc196.py:155'), translation_context='MWK:operators/option_windows_misc196.py:155'), F('no_scale', '', 'bool', True, text=_zh_native('Scale', 'MWK:operators/option_windows_misc196.py:156'), translation_context='MWK:operators/option_windows_misc196.py:156'), F('no_visibility', '', 'bool', True, text=_zh_native('Visibility', 'MWK:operators/option_windows_misc196.py:157'), translation_context='MWK:operators/option_windows_misc196.py:157'), F('no_dynamic', '', 'bool', False, text=_zh_native('Dynamic', 'MWK:operators/option_windows_misc196.py:158'), translation_context='MWK:operators/option_windows_misc196.py:158')], _character(False), paths=('Control/Create Character Set', 'Key/Create Character Set'), missing=(_dcc_source('Redirection: Redirect character (Rotation and translation / Rotation only / Translation only)'),), translation_context='MWK:operators/option_windows_misc196.py:150'), Window('subcharacter_set', _dcc_source('Create Subcharacter Set Options'), _dcc_source('Create Subcharacter Set'), None, [FText('name', _dcc_source('Name:'), 'subCharacter1'), F('attributes', _dcc_source('Subcharacter set attributes:'), 'enum', _dcc_source('All keyable except:'), items=_INCLUDE, translation_context='MWK:operators/option_windows_misc196.py:164'), F('no_translate', '', 'bool', False, text=_zh_native('No translate', 'MWK:operators/option_windows_misc196.py:165'), translation_context='MWK:operators/option_windows_misc196.py:165'), F('no_rotate', '', 'bool', False, text=_zh_native('No rotate', 'MWK:operators/option_windows_misc196.py:166'), translation_context='MWK:operators/option_windows_misc196.py:166'), F('no_scale', '', 'bool', True, text=_zh_native('No scale', 'MWK:operators/option_windows_misc196.py:167'), translation_context='MWK:operators/option_windows_misc196.py:167'), F('no_visibility', '', 'bool', True, text=_zh_native('No visibility', 'MWK:operators/option_windows_misc196.py:168'), translation_context='MWK:operators/option_windows_misc196.py:168'), F('no_dynamic', '', 'bool', False, text=_zh_native('No dynamic', 'MWK:operators/option_windows_misc196.py:169'), translation_context='MWK:operators/option_windows_misc196.py:169')], _character(True), paths=('Control/Create Subcharacter Set', 'Key/Create Subcharacter Set'), translation_context='MWK:operators/option_windows_misc196.py:162'), Window('cut_curve', _dcc_source('Cut Curve Options'), _dcc_source('Cut'), None, [F('cut', _dcc_source('Cut:'), 'enum', _dcc_source('At all intersections'), items=(_dcc_source('At all intersections'), _dcc_source('Using last curve')), translation_context='MWK:operators/option_windows_misc196.py:173'), F('keep', _dcc_source('Keep:'), 'enum', _dcc_source('All curve segments'), items=(_dcc_source('Longest segments'), _dcc_source('All curve segments')), translation_context='MWK:operators/option_windows_misc196.py:174')], _run_cut, paths=('Curves/Cut',), missing=(_dcc_source('Find intersections: In 2D and 3D / In 3D only / Use direction (the kit finds 3D crossings)'), _dcc_source('Keep: Segments with curve points'), _dcc_source('Use tolerance: Global / Local, Tolerance 0.0001'), _KEEP_ORIGINAL), translation_context='MWK:operators/option_windows_misc196.py:172'), Window('detach_curves', _dcc_source('Detach Curves Options'), _dcc_source('Detach'), None, [], _run_detach, paths=('Curves/Detach',), missing=(_KEEP_ORIGINAL,), translation_context='MWK:operators/option_windows_misc196.py:180'), Window('reverse_curve', _dcc_source('Reverse Curve Options'), _dcc_source('Reverse'), None, [F('keep_original', '', 'bool', False, text=_zh_native('Keep original', 'MWK:operators/option_windows_misc196.py:184'), translation_context='MWK:operators/option_windows_misc196.py:184')], _run_reverse, paths=('Curves/Reverse Direction',), translation_context='MWK:operators/option_windows_misc196.py:183'), Window('smooth_curves', _dcc_source('Smooth Curves Options'), _dcc_source('Smooth Curves'), None, [F('factor', _dcc_source('Smooth factor:'), 'int', 4, lo=1, hi=100, translation_context='MWK:operators/option_windows_misc196.py:188')], _run_smooth_curves, paths=('Curves/Smooth', 'nHair/Modify Curves/Smooth'), translation_context='MWK:operators/option_windows_misc196.py:187'), Window('smooth_curve', _dcc_source('Smooth Curve Options'), _dcc_source('Smooth'), None, [F('keep_original', '', 'bool', False, text=_zh_native('Keep original', 'MWK:operators/option_windows_misc196.py:192'), translation_context='MWK:operators/option_windows_misc196.py:192')], _run_smooth_curve, paths=('Curves/Smooth#2',), missing=(_dcc_source("Smoothness: 10.0 (Maya's smoothCurve; the kit runs Blender's curve Smooth)"),), translation_context='MWK:operators/option_windows_misc196.py:191'), Window('straighten_curves', _dcc_source('Straighten Curves Options'), _dcc_source('Straighten Curves'), None, [F('straightness', _dcc_source('Straightness:'), 'float', 1.0, lo=0.0, hi=2.0, translation_context='MWK:operators/option_windows_misc196.py:197'), F('preserve_length', '', 'bool', True, text=_zh_native('Preserve length', 'MWK:operators/option_windows_misc196.py:198'), translation_context='MWK:operators/option_windows_misc196.py:198')], _run_straighten, paths=('Curves/Straighten', 'nHair/Modify Curves/Straighten'), translation_context='MWK:operators/option_windows_misc196.py:196'), Window('arc3_tool', _dcc_source('Three Point Arc Settings'), _dcc_source('Create Arc'), None, [F('degree', _dcc_source('Circular arc degree:'), 'enum', '3', items=(_dcc_source('1 Linear'), '3'), translation_context='MWK:operators/option_windows_misc196.py:203'), F('sections', _dcc_source('Sections:'), 'int', 8, lo=4, hi=200, translation_context='MWK:operators/option_windows_misc196.py:204')], _arc('arc3_tool'), paths=('Create/Curve Tools/Three Point Circular Arc',), translation_context='MWK:operators/option_windows_misc196.py:202'), Window('arc2_tool', _dcc_source('Two Point Arc Settings'), _dcc_source('Create Arc'), None, [F('degree', _dcc_source('Circular arc degree:'), 'enum', '3', items=(_dcc_source('1 Linear'), '3'), translation_context='MWK:operators/option_windows_misc196.py:207'), F('sections', _dcc_source('Sections:'), 'int', 8, lo=4, hi=200, translation_context='MWK:operators/option_windows_misc196.py:208')], _arc('arc2_tool'), paths=('Create/Curve Tools/Two Point Circular Arc',), translation_context='MWK:operators/option_windows_misc196.py:206'), Window('merge_uvs', _dcc_source('Merge UVs Options'), _dcc_source('Merge UVs'), None, [F('threshold', _dcc_source('Threshold:'), 'float', 0.01, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_misc196.py:212')], _run_merge_uvs, paths=('UV/Merge UVs',), translation_context='MWK:operators/option_windows_misc196.py:211'), Window('contour_stretch', _dcc_source('Contour Stretch Mapping Options'), _dcc_source('Project'), None, [], _run_contour, paths=('UV/Contour Stretch',), missing=(_dcc_source('Method: Walk Contours / NURBS Projection (the kit follows the quad grid)'), _dcc_source('Smoothness 0-3, Offset 0-3'), _dcc_source('User defined corner vertices'), _dcc_source('Insert projection before deformers'), _dcc_source('Create new UV Set')), translation_context='MWK:operators/option_windows_misc196.py:215'), Window('set_preferred_angle', _dcc_source('Set Preferred Angle Options'), _dcc_source('Set'), None, [F('options', _dcc_source('Options:'), 'enum', _dcc_source('Hierarchy'), items=(_dcc_source('Selected joint'), _dcc_source('Hierarchy')), translation_context='MWK:operators/option_windows_misc196.py:222')], _preferred('set_preferred_angle'), paths=('Skeleton/Set Preferred Angle',), translation_context='MWK:operators/option_windows_misc196.py:221'), Window('assume_preferred_angle', _dcc_source('Assume Preferred Angle Options'), _dcc_source('Assume'), None, [F('options', _dcc_source('Options:'), 'enum', _dcc_source('Hierarchy'), items=(_dcc_source('Selected joint'), _dcc_source('Hierarchy')), translation_context='MWK:operators/option_windows_misc196.py:225')], _preferred('assume_preferred_angle'), paths=('Skeleton/Assume Preferred Angle',), translation_context='MWK:operators/option_windows_misc196.py:224'), Window('add_influence', _dcc_source('Add Influence Options'), _dcc_source('Add'), None, [F('lock_weights', _dcc_source('Weight locking:'), 'bool', False, text=_zh_native('Lock weights', 'MWK:operators/option_windows_misc196.py:229'), translation_context='MWK:operators/option_windows_misc196.py:229'), F('default_weight', _dcc_source('Default weight:'), 'float', 0.0, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_misc196.py:230')], _run_add_influence, paths=('Skin/Edit Influences/Add Influence',), missing=(_dcc_source('Geometry: Use geometry'), _dcc_source('Dropoff: 4.0 (Maya weighs an unlocked influence by distance; the kit adds it at 0)'), _dcc_source('Polygon smoothness: 0.0'), _dcc_source('NURBS samples: 10')), translation_context='MWK:operators/option_windows_misc196.py:228')]
