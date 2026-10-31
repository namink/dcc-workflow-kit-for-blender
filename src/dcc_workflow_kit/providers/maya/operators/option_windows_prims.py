# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Step 196 (#103): Maya option windows of Create > Polygon Primitives (Disc ... Ultra Shape) and Create > NURBS
Primitives (same spec as operators/option_windows.py; option_windows._extend appends ``WINDOWS``).

Titles, field labels, ranges and factory values: Maya 2022's
option windows with factory settings.
Each window fills the kit's Maya creation node (operators/prim_history.py, prim_shapes*.py, prim_supershape.py) through
``create.create(context, kind, overrides)``: values are Maya values, lengths in Maya units (create() scales them).
Fields Blender / the kit can't follow are listed as ``missing``."""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
from .option_windows import AXIS, UVS, F, Window
_NORM = (_dcc_source('Normalize'), _dcc_source('Preserve aspect ratio'))
_TOL = _dcc_source('Use tolerance: Local / Global, Positional tolerance (None only: sections and spans are used)')
_VIEW = _dcc_source('Axis: Active view')
_AXES = {'X': (1.0, 0.0, 0.0), 'Y': (0.0, 1.0, 0.0), 'Z': (0.0, 0.0, 1.0)}

def _create(context, kind, over):
    from . import create
    create.create(context, kind, overrides=over)
    return {'FINISHED'}

def _poly(kind, attrs, axis=True, uvs=True, extra=None):
    """Run: fields named after the node attribute pass straight through; Axis -> axisX/Y/Z, Create UVs -> createUVs."""

    def run(context, v):
        over = {a: v[a] for a in attrs}
        if axis:
            ax = _AXES[v['axis']]
            over.update(axisX=ax[0], axisY=ax[1], axisZ=ax[2])
        if uvs:
            over['createUVs'] = int(bool(v['create_uvs']))
        if extra is not None:
            extra(v, over)
        return _create(context, kind, over)
    return run
_DISC_MODES = (_dcc_source('Quads'), _dcc_source('Triangles'), _dcc_source('Pie'), _dcc_source('Caps'), _dcc_source('Circle'))
_PLATONIC = (_dcc_source('Tetrahedron'), _dcc_source('Cube'), _dcc_source('Octahedron'), _dcc_source('Dodecahedron'), _dcc_source('Icosahedron'))
_PLATONIC_MODES = (_dcc_source('Quads'), _dcc_source('Triangles'), _dcc_source('Pie'), _dcc_source('Caps'))

def _disc_extra(v, over):
    over['subdivisionMode'] = _DISC_MODES.index(v['subdivision_mode'])

def _platonic_extra(v, over):
    over['primitive'] = _PLATONIC.index(v['primitive'])
    over['subdivisionMode'] = _PLATONIC_MODES.index(v['subdivision_mode'])

def _pyramid_extra(v, over):
    over['numberOfSides'] = int(v['number_of_sides'])

def _helix_extra(v, over):
    over['direction'] = (_dcc_source('Clockwise'), _dcc_source('Counterclockwise')).index(v['direction'])

def _soccer_extra(v, over):
    from . import prim_shapes_more
    side = prim_shapes_more.SOCCER_SIDE
    if abs(v['sideLength'] - v['radius'] * side) > 0.0001 and abs(v['radius'] - 1.0) < 1e-09:
        over['radius'] = v['sideLength'] / side
    over['sideLength'] = over['radius'] * side
_SUPER_KINDS = {_dcc_source('Super Ellipse'): 'SUPER_ELLIPSE', _dcc_source('Spherical Harmonics'): 'SPHERICAL_HARMONICS', _dcc_source('Ultra Shape'): 'ULTRA_SHAPE'}
_SUPER_ATTRS = ['radius', 'horizontalDivisions', 'verticalDivisions', 'mergeVertices', 'horizontalRevolutions', 'verticalRevolutions', 'verticalOffset', 'internalRadius', 'xOffset', 'zOffset', 'ellipse0', 'ellipse1', 'ellipseMirror'] + [f'harmonics{i}' for i in range(8)] + [f'ultra{i}' for i in range(16)] + ['ultraMirror']

def _run_super(context, v):
    over = {a: v[a] for a in _SUPER_ATTRS}
    over['createUVs'] = int(v['create_uvs'] != _dcc_source('None'))
    return _create(context, _SUPER_KINDS[v['shape']], over)

def _super_fields(shape):
    """Polygon Super Shape Options: General / Helix / Super Ellipse / Spherical Harmonics / Ultra
    frames (Maya factory values; the menu item sets the Shape)."""
    sh = [F(f'harmonics{i}', f"{('V' if i < 4 else 'H')} {('Multiplier' if i % 2 == 0 else 'Exponent')} {i % 4 // 2 + 1}:", 'float', d, lo=-20.0 if i % 2 == 0 else 0.0, hi=20.0 if i % 2 == 0 else 5.0, translation_context='MWK:operators/option_windows_prims.py:96') for (i, d) in enumerate((0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0))]
    ultra_labels = (_dcc_source('Multiplier 1:'), _dcc_source('Exponent 1:'), _dcc_source('Exponent 2:'), _dcc_source('Mixer:'), _dcc_source('Multiplier 2:'), _dcc_source('Exponent 3:'), _dcc_source('Exponent 4:'), _dcc_source('Exponent 5:'))
    ultra = [F(f'ultra{i}', f"{('Horizontal' if i < 8 else 'Vertical')} {ultra_labels[i % 8]}", 'float', d, lo=-30.0 if i % 4 == 0 else 0.0, hi=30.0 if i % 4 == 0 else 1.0 if i % 8 == 3 else 4.0, translation_context='MWK:operators/option_windows_prims.py:101') for (i, d) in enumerate((0.0, 1.0, 1.0, 0.5, 0.0, 1.0, 1.0, 1.0) * 2)]
    return [F('shape', _dcc_source('Shape:'), 'enum', shape, items=tuple(_SUPER_KINDS), translation_context='MWK:operators/option_windows_prims.py:105'), F('radius', _dcc_source('Radius:'), 'length', 1.0, lo=0.001, hi=100, translation_context='MWK:operators/option_windows_prims.py:106'), F('horizontalDivisions', _dcc_source('Horizontal Divisions:'), 'int', 16, lo=1, hi=100, translation_context='MWK:operators/option_windows_prims.py:107'), F('verticalDivisions', _dcc_source('Vertical Divisions:'), 'int', 16, lo=1, hi=100, translation_context='MWK:operators/option_windows_prims.py:108'), F('create_uvs', _dcc_source('Create UVs:'), 'enum', _dcc_source('Sawtooth at pole'), items=(_dcc_source('None'), _dcc_source('Pinched at pole'), _dcc_source('Sawtooth at pole')), translation_context='MWK:operators/option_windows_prims.py:109'), F('mergeVertices', _dcc_source('Merge Vertices:'), 'bool', True, translation_context='MWK:operators/option_windows_prims.py:110'), F('horizontalRevolutions', _dcc_source('Horizontal Revolutions:'), 'float', 1.0, lo=0.0, translation_context='MWK:operators/option_windows_prims.py:111'), F('verticalRevolutions', _dcc_source('Vertical Revolutions:'), 'float', 1.0, lo=0.0, translation_context='MWK:operators/option_windows_prims.py:112'), F('verticalOffset', _dcc_source('Vertical Offset:'), 'float', 0.0, lo=0.0, translation_context='MWK:operators/option_windows_prims.py:113'), F('internalRadius', _dcc_source('Internal Radius:'), 'float', 0.0, lo=0.0, translation_context='MWK:operators/option_windows_prims.py:114'), F('xOffset', _dcc_source('X Offset:'), 'float', 0.0, lo=0.0, translation_context='MWK:operators/option_windows_prims.py:115'), F('zOffset', _dcc_source('Z Offset:'), 'float', 0.0, lo=0.0, translation_context='MWK:operators/option_windows_prims.py:115'), F('ellipse0', _dcc_source('V Exponent:'), 'float', 1.0, lo=0.0, hi=5.0, translation_context='MWK:operators/option_windows_prims.py:116'), F('ellipse1', _dcc_source('H Exponent:'), 'float', 1.0, lo=0.0, hi=5.0, translation_context='MWK:operators/option_windows_prims.py:117'), F('ellipseMirror', _dcc_source('Mirror:'), 'bool', True, translation_context='MWK:operators/option_windows_prims.py:118'), *sh, *ultra, F('ultraMirror', _dcc_source('Ultra Mirror:'), 'bool', False, translation_context='MWK:operators/option_windows_prims.py:120')]

def _super(key, shape):
    return Window(key, _dcc_source('Polygon Super Shape Options'), _dcc_source('Create'), ('allset.create', {'kind': _SUPER_KINDS[shape]}), _super_fields(shape), _run_super, width=480, missing=(_dcc_source('Create UVs: Pinched at pole (built as Sawtooth at pole)'),), translation_context='MWK:operators/option_windows_prims.py:125')
_AXIS_N = ('X', 'Y', 'Z', _dcc_source('Free'))
LINEAR_CUBIC = (_dcc_source('Linear'), _dcc_source('Cubic'))

def _pivot_fields(label=_dcc_source('Pivot:')):
    return [F(_dcc_source('pivot'), label, 'enum', _dcc_source('Object'), items=(_dcc_source('Object'), _dcc_source('User defined')), translation_context='MWK:operators/option_windows_prims.py:137'), F('pivot_point', _dcc_source('Pivot point:'), 'vec3', (0.0, 0.0, 0.0), translation_context='MWK:operators/option_windows_prims.py:138')]

def _axis_fields(label=_dcc_source('Axis:'), definition=_dcc_source('Axis definition:')):
    return [F('axis', label, 'enum', 'Y', items=_AXIS_N, translation_context='MWK:operators/option_windows_prims.py:142'), F('axis_definition', definition, 'vec3', (0.0, 1.0, 0.0), translation_context='MWK:operators/option_windows_prims.py:143')]

def _axis_of(v):
    return tuple(v['axis_definition']) if v['axis'] == _dcc_source('Free') else _AXES[v['axis']]

def _pivot_of(v):
    return tuple(v['pivot_point']) if v[_dcc_source('pivot')] == _dcc_source('User defined') else (0.0, 0.0, 0.0)

def _degree(label):
    return 1 if label.strip().startswith(('1', _dcc_source('Linear'))) else 3

def _nurbs(kind, build):
    """Run: Pivot -> pivotX/Y/Z (Object = origin), Axis -> axisX/Y/Z (Free = Axis definition), then ``build``."""

    def run(context, v):
        (p, a) = (_pivot_of(v), _axis_of(v))
        over = {'pivotX': p[0], 'pivotY': p[1], 'pivotZ': p[2], 'axisX': a[0], 'axisY': a[1], 'axisZ': a[2]}
        build(v, over)
        return _create(context, kind, over)
    return run

def _sweeps(v, over):
    over.update(startSweep=v['start_sweep'], endSweep=v['end_sweep'], radius=v['radius'], degree=_degree(v['degree']), sections=v['sections'])

def _sphere_build(v, over):
    _sweeps(v, over)
    over['spans'] = v['spans']

def _cyl_build(v, over):
    _sweeps(v, over)
    over.update(spans=v['spans'], heightRatio=v['height'] / v['radius'] if v['radius'] else 0.0)

def _torus_build(v, over):
    _sweeps(v, over)
    over.update(spans=v['spans'], minorSweep=v['minor_sweep'], heightRatio=v['minor_radius'] / v['radius'] if v['radius'] else 0.0)

def _plane_build(v, over):
    w = v['width']
    over.update(width=w, lengthRatio=v['length'] / w if w else 0.0, patchesU=v['patches_u'], patchesV=v['patches_v'], degree=_degree(v['degree']))
    if 'height' in v:
        over['heightRatio'] = v['height'] / w if w else 0.0

def _run_circle(context, v):
    (c, n) = (_pivot_of(v), _axis_of(v))
    over = {'centerX': c[0], 'centerY': c[1], 'centerZ': c[2], 'normalX': n[0], 'normalY': n[1], 'normalZ': n[2], 'sweep': v['sweep'], 'radius': v['radius'], 'degree': _degree(v['degree']), 'sections': v['sections']}
    return _create(context, 'NURBS_CIRCLE', over)

def _run_square(context, v):
    (c, n) = (tuple(v['center']), _axis_of(v))
    over = {'centerX': c[0], 'centerY': c[1], 'centerZ': c[2], 'normalX': n[0], 'normalY': n[1], 'normalZ': n[2], 'sideLength1': v['side1'], 'sideLength2': v['side2'], 'spansPerSide': v['spans_per_side'], 'degree': _degree(v['degree'])}
    return _create(context, 'NURBS_SQUARE', over)

def _sweep_fields():
    return [F('start_sweep', _dcc_source('Start sweep angle:'), 'float', 0.0, lo=-3600.0, hi=3600.0, translation_context='MWK:operators/option_windows_prims.py:214'), F('end_sweep', _dcc_source('End sweep angle:'), 'float', 360.0, lo=-3600.0, hi=3600.0, translation_context='MWK:operators/option_windows_prims.py:215')]

def _degree_field(label=_dcc_source('Surface degree:'), items=LINEAR_CUBIC):
    return F('degree', label, 'enum', items[-1], items=items, translation_context='MWK:operators/option_windows_prims.py:219')

def _sections(spans_default=None, spans_lo=1):
    out = [F('sections', _dcc_source('Number of sections:'), 'int', 8, lo=4, hi=200, translation_context='MWK:operators/option_windows_prims.py:223')]
    if spans_default is not None:
        out.append(F('spans', _dcc_source('Number of spans:'), 'int', spans_default, lo=spans_lo, hi=200, translation_context='MWK:operators/option_windows_prims.py:225'))
    return out
_CAPS = _dcc_source('Caps: None only, Extra transform on caps (no cap surfaces)')
_DEG_MORE = _dcc_source('Surface degree: 2 / 5 / 7 (1 Linear and 3 Cubic only)')
WINDOWS = [Window('poly_disc', _dcc_source('Polygon Disc Options'), _dcc_source('Create'), ('allset.create', {'kind': 'DISC'}), [F('sides', _dcc_source('Sides:'), 'int', 3, lo=3, hi=20, translation_context='MWK:operators/option_windows_prims.py:235'), F('subdivision_mode', _dcc_source('Subdivision Mode:'), 'enum', _dcc_source('Circle'), items=_DISC_MODES, translation_context='MWK:operators/option_windows_prims.py:236'), F('subdivisions', _dcc_source('Subdivisions:'), 'int', 3, lo=0, hi=40, translation_context='MWK:operators/option_windows_prims.py:237'), F('radius', _dcc_source('Radius:'), 'length', 1.0, lo=0.001, hi=100, translation_context='MWK:operators/option_windows_prims.py:238')], _poly('DISC', ('sides', 'subdivisions', 'radius'), axis=False, uvs=False, extra=_disc_extra), translation_context='MWK:operators/option_windows_prims.py:234'), Window('poly_platonic', _dcc_source('Polygon Platonic Options'), _dcc_source('Create'), ('allset.create', {'kind': 'PLATONIC'}), [F('primitive', _dcc_source('Primitive:'), 'enum', _dcc_source('Icosahedron'), items=_PLATONIC, translation_context='MWK:operators/option_windows_prims.py:242'), F('subdivision_mode', _dcc_source('Subdivision Mode:'), 'enum', _dcc_source('Quads'), items=_PLATONIC_MODES, translation_context='MWK:operators/option_windows_prims.py:243'), F('subdivisions', _dcc_source('Subdivisions:'), 'int', 0, lo=0, hi=40, translation_context='MWK:operators/option_windows_prims.py:244'), F('radius', _dcc_source('Radius:'), 'length', 1.0, lo=0.001, hi=100, translation_context='MWK:operators/option_windows_prims.py:245'), F('sphericalInflation', _dcc_source('Spherical Inflation:'), 'float', 1.0, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_prims.py:246')], _poly('PLATONIC', ('subdivisions', 'radius', 'sphericalInflation'), axis=False, uvs=False, extra=_platonic_extra), translation_context='MWK:operators/option_windows_prims.py:241'), Window('poly_pyramid', _dcc_source('Polygon Pyramid Options'), _dcc_source('Create'), ('allset.create', {'kind': 'PYRAMID'}), [F('sideLength', _dcc_source('Side length:'), 'length', 1.0, lo=0.0, hi=100, translation_context='MWK:operators/option_windows_prims.py:251'), F('number_of_sides', _dcc_source('Number of sides in base:'), 'enum', '4', items=('3', '4', '5'), translation_context='MWK:operators/option_windows_prims.py:252'), F('subdivisionsHeight', _dcc_source('Height divisions:'), 'int', 1, lo=1, hi=1000, translation_context='MWK:operators/option_windows_prims.py:253'), F('subdivisionsCaps', _dcc_source('Cap divisions:'), 'int', 0, lo=0, hi=1000, translation_context='MWK:operators/option_windows_prims.py:254'), AXIS, UVS], _poly('PYRAMID', ('sideLength', 'subdivisionsHeight', 'subdivisionsCaps'), extra=_pyramid_extra), missing=_NORM, translation_context='MWK:operators/option_windows_prims.py:250'), Window('poly_prism', _dcc_source('Polygon Prism Options'), _dcc_source('Create'), ('allset.create', {'kind': 'PRISM'}), [F('length', _dcc_source('Length:'), 'length', 2.0, lo=0.0, hi=100, translation_context='MWK:operators/option_windows_prims.py:259'), F('sideLength', _dcc_source('Side length:'), 'length', 1.0, lo=0.0, hi=100, translation_context='MWK:operators/option_windows_prims.py:259'), F('numberOfSides', _dcc_source('Number of sides in base:'), 'int', 3, lo=3, hi=1000, translation_context='MWK:operators/option_windows_prims.py:260'), F('subdivisionsHeight', _dcc_source('Height divisions:'), 'int', 1, lo=1, hi=1000, translation_context='MWK:operators/option_windows_prims.py:261'), F('subdivisionsCaps', _dcc_source('Cap divisions:'), 'int', 0, lo=0, hi=1000, translation_context='MWK:operators/option_windows_prims.py:262'), AXIS, UVS], _poly('PRISM', ('length', 'sideLength', 'numberOfSides', 'subdivisionsHeight', 'subdivisionsCaps')), missing=_NORM, translation_context='MWK:operators/option_windows_prims.py:258'), Window('poly_pipe', _dcc_source('Polygon Pipe Options'), _dcc_source('Create'), ('allset.create', {'kind': 'PIPE'}), [F('radius', _dcc_source('Radius:'), 'length', 1.0, lo=0.01, hi=100, translation_context='MWK:operators/option_windows_prims.py:267'), F('height', _dcc_source('Height:'), 'length', 2.0, lo=0.01, hi=100, translation_context='MWK:operators/option_windows_prims.py:267'), F('thickness', _dcc_source('Thickness:'), 'length', 0.5, lo=0.01, hi=100, translation_context='MWK:operators/option_windows_prims.py:268'), F('subdivisionsAxis', _dcc_source('Axis divisions:'), 'int', 20, lo=3, hi=1000, translation_context='MWK:operators/option_windows_prims.py:269'), F('subdivisionsHeight', _dcc_source('Height divisions:'), 'int', 1, lo=1, hi=1000, translation_context='MWK:operators/option_windows_prims.py:270'), F('subdivisionsCaps', _dcc_source('Cap divisions:'), 'int', 0, lo=0, hi=1000, translation_context='MWK:operators/option_windows_prims.py:271'), F('roundCap', '', 'bool', False, text=_zh_native('Round cap', 'MWK:operators/option_windows_prims.py:272'), translation_context='MWK:operators/option_windows_prims.py:272'), AXIS, UVS], _poly('PIPE', ('radius', 'height', 'thickness', 'subdivisionsAxis', 'subdivisionsHeight', 'subdivisionsCaps', 'roundCap')), translation_context='MWK:operators/option_windows_prims.py:266'), Window('poly_helix', _dcc_source('Polygon Helix Options'), _dcc_source('Create'), ('allset.create', {'kind': 'HELIX'}), [F('coils', _dcc_source('Coils:'), 'float', 3.0, lo=0.5, hi=1000, translation_context='MWK:operators/option_windows_prims.py:278'), F('height', _dcc_source('Height:'), 'length', 2.0, lo=0.01, hi=100, translation_context='MWK:operators/option_windows_prims.py:278'), F('width', _dcc_source('Width:'), 'length', 2.0, lo=0.01, hi=100, translation_context='MWK:operators/option_windows_prims.py:279'), F('radius', _dcc_source('Radius:'), 'length', 0.4, lo=0.01, hi=100, translation_context='MWK:operators/option_windows_prims.py:279'), F('subdivisionsAxis', _dcc_source('Axis divisions:'), 'int', 8, lo=3, hi=1000, translation_context='MWK:operators/option_windows_prims.py:280'), F('subdivisionsCoil', _dcc_source('Coil divisions:'), 'int', 50, lo=2, hi=1000, translation_context='MWK:operators/option_windows_prims.py:281'), F('subdivisionsCaps', _dcc_source('Coils:'), 'int', 0, lo=0, hi=1000, translation_context='MWK:operators/option_windows_prims.py:282'), F('roundCap', '', 'bool', False, text=_zh_native('Round cap', 'MWK:operators/option_windows_prims.py:283'), translation_context='MWK:operators/option_windows_prims.py:283'), F('direction', _dcc_source('Direction'), 'enum', _dcc_source('Counterclockwise'), items=(_dcc_source('Clockwise'), _dcc_source('Counterclockwise')), translation_context='MWK:operators/option_windows_prims.py:284'), AXIS, UVS], _poly('HELIX', ('coils', 'height', 'width', 'radius', 'subdivisionsAxis', 'subdivisionsCoil', 'subdivisionsCaps', 'roundCap'), extra=_helix_extra), missing=_NORM, translation_context='MWK:operators/option_windows_prims.py:277'), Window('poly_gear', _dcc_source('Polygon Gear Options'), _dcc_source('Create'), ('allset.create', {'kind': 'GEAR'}), [F('sides', _dcc_source('Sides:'), 'int', 16, lo=3, hi=20, translation_context='MWK:operators/option_windows_prims.py:290'), F('radius', _dcc_source('Radius:'), 'length', 1.0, lo=0.001, hi=100, translation_context='MWK:operators/option_windows_prims.py:290'), F('internalRadius', _dcc_source('Internal Radius:'), 'length', 0.3, lo=0.0, hi=50, translation_context='MWK:operators/option_windows_prims.py:291'), F('height', _dcc_source('Height:'), 'length', 1.0, lo=0.001, hi=100, translation_context='MWK:operators/option_windows_prims.py:292'), F('heightDivisions', _dcc_source('Height Divisions:'), 'int', 10, lo=1, hi=40, translation_context='MWK:operators/option_windows_prims.py:293'), F('gearSpacing', _dcc_source('Gear Spacing:'), 'float', 0.6, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_prims.py:294'), F('gearOffset', _dcc_source('Gear Offset:'), 'length', 0.2, lo=0.0, hi=20, translation_context='MWK:operators/option_windows_prims.py:295'), F('gearTip', _dcc_source('Gear Tip:'), 'float', 0.5, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_prims.py:296'), F('gearMiddle', _dcc_source('Gear Middle:'), 'float', 1.2, lo=0.0, hi=2.0, translation_context='MWK:operators/option_windows_prims.py:296'), F('twist', _dcc_source('Twist:'), 'float', 0.0, lo=0.0, hi=1.0, translation_context='MWK:operators/option_windows_prims.py:297'), F('taper', _dcc_source('Taper:'), 'float', 1.0, lo=0.001, hi=1.0, translation_context='MWK:operators/option_windows_prims.py:297')], _poly('GEAR', ('sides', 'radius', 'internalRadius', 'height', 'heightDivisions', 'gearSpacing', 'gearOffset', 'gearTip', 'gearMiddle', 'twist', 'taper'), axis=False, uvs=False), translation_context='MWK:operators/option_windows_prims.py:289'), Window('poly_soccer_ball', _dcc_source('Polygon Soccer Ball Options'), _dcc_source('Create'), ('allset.create', {'kind': 'SOCCER_BALL'}), [F('radius', _dcc_source('Radius:'), 'length', 1.0, lo=0.01, hi=100, translation_context='MWK:operators/option_windows_prims.py:302'), F('sideLength', _dcc_source('Side length:'), 'length', 0.4036, lo=0.01, hi=100, translation_context='MWK:operators/option_windows_prims.py:303'), AXIS, UVS], _poly('SOCCER_BALL', ('radius', 'sideLength'), extra=_soccer_extra), missing=(_dcc_source('Normalize'), _dcc_source('Collectively / Each face separately'), _dcc_source('Preserve aspect ratio')), translation_context='MWK:operators/option_windows_prims.py:301'), _super('poly_super_ellipse', _dcc_source('Super Ellipse')), _super('poly_spherical_harmonics', _dcc_source('Spherical Harmonics')), _super('poly_ultra_shape', _dcc_source('Ultra Shape')), Window('nurbs_sphere', _dcc_source('NURBS Sphere Options'), _dcc_source('Create'), ('allset.create', {'kind': 'NURBS_SPHERE'}), [*_pivot_fields(), *_axis_fields(), *_sweep_fields(), F('radius', _dcc_source('Radius:'), 'length', 1.0, lo=0.0001, hi=1000, translation_context='MWK:operators/option_windows_prims.py:313'), _degree_field(), *_sections(4, 2)], _nurbs('NURBS_SPHERE', _sphere_build), missing=(_VIEW, _TOL), translation_context='MWK:operators/option_windows_prims.py:311'), Window('nurbs_cube', _dcc_source('NURBS Cube Options'), _dcc_source('Create'), ('allset.create', {'kind': 'NURBS_CUBE'}), [*_pivot_fields(), *_axis_fields(), F('width', _dcc_source('Width:'), 'length', 1.0, lo=0.0001, hi=1000, translation_context='MWK:operators/option_windows_prims.py:317'), F('length', _dcc_source('Length:'), 'length', 1.0, lo=0.0, hi=1000, translation_context='MWK:operators/option_windows_prims.py:317'), F('height', _dcc_source('Height:'), 'length', 1.0, lo=0.0, hi=1000, translation_context='MWK:operators/option_windows_prims.py:318'), _degree_field(items=(_dcc_source('1 Linear'), _dcc_source('3 Cubic'))), F('patches_u', _dcc_source('U patches:'), 'int', 1, lo=1, hi=500, translation_context='MWK:operators/option_windows_prims.py:319'), F('patches_v', _dcc_source('V patches:'), 'int', 1, lo=1, hi=500, translation_context='MWK:operators/option_windows_prims.py:319')], _nurbs('NURBS_CUBE', _plane_build), missing=(_VIEW, _DEG_MORE), translation_context='MWK:operators/option_windows_prims.py:315'), Window('nurbs_cylinder', _dcc_source('NURBS Cylinder Options'), _dcc_source('Create'), ('allset.create', {'kind': 'NURBS_CYLINDER'}), [*_pivot_fields(), *_axis_fields(), *_sweep_fields(), F('radius', _dcc_source('Radius:'), 'length', 1.0, lo=0.0001, hi=1000, translation_context='MWK:operators/option_windows_prims.py:323'), F('height', _dcc_source('Height:'), 'length', 2.0, lo=0.0, hi=1000, translation_context='MWK:operators/option_windows_prims.py:323'), _degree_field(), *_sections(1, 1)], _nurbs('NURBS_CYLINDER', _cyl_build), missing=(_VIEW, _CAPS, _TOL), translation_context='MWK:operators/option_windows_prims.py:321'), Window('nurbs_cone', _dcc_source('NURBS Cone Options'), _dcc_source('Create'), ('allset.create', {'kind': 'NURBS_CONE'}), [*_pivot_fields(), *_axis_fields(), *_sweep_fields(), F('radius', _dcc_source('Radius:'), 'length', 1.0, lo=0.0001, hi=1000, translation_context='MWK:operators/option_windows_prims.py:328'), F('height', _dcc_source('Height:'), 'length', 2.0, lo=0.0, hi=1000, translation_context='MWK:operators/option_windows_prims.py:328'), _degree_field(), *_sections(1, 1)], _nurbs('NURBS_CONE', _cyl_build), missing=(_VIEW, _dcc_source('Caps: None only, Extra transform on caps (no cap surface)'), _TOL), translation_context='MWK:operators/option_windows_prims.py:326'), Window('nurbs_plane', _dcc_source('NURBS Plane Options'), _dcc_source('Create'), ('allset.create', {'kind': 'NURBS_PLANE'}), [*_pivot_fields(), *_axis_fields(), F('width', _dcc_source('Width:'), 'length', 1.0, lo=0.0001, hi=1000, translation_context='MWK:operators/option_windows_prims.py:334'), F('length', _dcc_source('Length:'), 'length', 1.0, lo=0.0, hi=1000, translation_context='MWK:operators/option_windows_prims.py:334'), _degree_field(items=(_dcc_source('1 Linear'), _dcc_source('3 Cubic'))), F('patches_u', _dcc_source('U patches:'), 'int', 1, lo=1, hi=500, translation_context='MWK:operators/option_windows_prims.py:336'), F('patches_v', _dcc_source('V patches:'), 'int', 1, lo=1, hi=500, translation_context='MWK:operators/option_windows_prims.py:336')], _nurbs('NURBS_PLANE', _plane_build), missing=(_VIEW, _DEG_MORE), translation_context='MWK:operators/option_windows_prims.py:332'), Window('nurbs_torus', _dcc_source('NURBS Torus Options'), _dcc_source('Create'), ('allset.create', {'kind': 'NURBS_TORUS'}), [*_pivot_fields(), *_axis_fields(), *_sweep_fields(), F('minor_sweep', _dcc_source('Minor sweep angle:'), 'float', 360.0, lo=-3600.0, hi=3600.0, translation_context='MWK:operators/option_windows_prims.py:340'), F('radius', _dcc_source('Radius:'), 'length', 1.0, lo=0.0001, hi=1000, translation_context='MWK:operators/option_windows_prims.py:341'), F('minor_radius', _dcc_source('Minor radius:'), 'length', 0.5, lo=0.0, hi=1000, translation_context='MWK:operators/option_windows_prims.py:342'), _degree_field(), *_sections(4, 4)], _nurbs('NURBS_TORUS', _torus_build), missing=(_VIEW, _TOL), translation_context='MWK:operators/option_windows_prims.py:338'), Window('nurbs_circle', _dcc_source('NURBS Circle Options'), _dcc_source('Create'), ('allset.create', {'kind': 'NURBS_CIRCLE'}), [*_pivot_fields(), *_axis_fields(_dcc_source('Normal axis:'), _dcc_source('Normal definition:')), F('sweep', _dcc_source('Sweep angle:'), 'float', 360.0, lo=-3600.0, hi=3600.0, translation_context='MWK:operators/option_windows_prims.py:347'), F('radius', _dcc_source('Radius:'), 'length', 1.0, lo=0.0001, hi=1000, translation_context='MWK:operators/option_windows_prims.py:348'), _degree_field(_dcc_source('Degree:')), *_sections()], _run_circle, missing=(_dcc_source('Normal axis: Active view'), _TOL), translation_context='MWK:operators/option_windows_prims.py:345'), Window('nurbs_square', _dcc_source('NURBS Square Options'), _dcc_source('Create'), ('allset.create', {'kind': 'NURBS_SQUARE'}), [F('center', _dcc_source('Center:'), 'vec3', (0.0, 0.0, 0.0), translation_context='MWK:operators/option_windows_prims.py:352'), *_axis_fields(_dcc_source('Normal axis:'), _dcc_source('Normal definition:')), F('side1', _dcc_source('Length of Side 1:'), 'length', 1.0, lo=0.1, hi=1000, translation_context='MWK:operators/option_windows_prims.py:353'), F('side2', _dcc_source('Length of Side 2:'), 'length', 1.0, lo=0.1, hi=1000, translation_context='MWK:operators/option_windows_prims.py:354'), F('spans_per_side', _dcc_source('Spans per side:'), 'int', 1, lo=1, hi=200, translation_context='MWK:operators/option_windows_prims.py:355'), _degree_field(_dcc_source('Curve degree:'), items=('1', '3'))], _run_square, missing=(_dcc_source('Normal axis: Active view'), _dcc_source('Curve degree: 2 / 5 / 7 (1 and 3 only)')), translation_context='MWK:operators/option_windows_prims.py:351')]
