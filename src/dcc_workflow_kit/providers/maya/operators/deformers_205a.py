# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Step 205 lane A (issue #112): Maya Deform > Tension, Solidify, Sculpt (+ Paint Weights > Tension, Prune Membership >
Sculpt).

Maya 2022 facts: nodes / names / selection / Channel Box rows / option windows, Tension, Solidify, Sculpt.
Blender has none of these deformers, so
each is a Geometry Nodes modifier named like the Maya node (``tension1``) on a shared node group built here (the
pattern of operators/wire_deformer.py, step 169); it reads its input from the modifiers above it (Maya: the upstream
deformers) and its weights from the vertex group of its name (Maya factory weight 1 on the deformed points, step 144).
Maya's ``<shape>Orig`` (the rest shape Tension / Solidify compare with) is the mesh's base positions when the deformer
is made, kept in a hidden point attribute ``.allset_rest_<node>`` (component edits made later are Maya tweaks = input,
not rest); a topology change (Delete Non-Deformer History of a bevel, ...) re-takes it with the partner table.

- **Tension** (every "O" case within 2.5e-7 in plain Python; the node group repeats Maya's Jacobi passes in a
  Repeat zone): partner table per vertex = edge neighbours (strength 1), face diagonals (Shear Strength), bend partners
  (Bend Strength) as hidden INT point attributes ``.allset_tension_p<k>`` = partner · 8 + flags (1 edge, 2 diagonal,
  4 bend, -1 none), computed from the topology in Python (operators can't build variable lists in Geometry Nodes).
  Vertex normals = Maya's corner rule (cross(f[k+h] - p, f[k-h] - p), h = max(1, m // 2 - 1)), recomputed each pass.
- **Solidify** ([U]): the known parts — membership = the vertex group (points selected at creation) picks
  the solid region; Full on the whole mesh = a rigid transform of the rest region onto the input with translation =
  input centroid; Borders on the whole mesh = nothing moves; a region's border ring stays (falloff on) / moves too
  (falloff off); envelope blends linearly. Unknown, delegated: the rotation is the least-squares (Kabsch / polar)
  fit (Maya differs by ~2.5°), Stabilization Level n divides the angle by 1 + n/2 (Maya: level 2 halves it), the
  border falloff is Blender's Blur Attribute of the inside weights, Scale Mode Edge / Edge Global = uniform scale by
  the region's edge-length ratio (× Scale Envelope), Normal / Tangent Plane Scale scale the normal / tangent part.
- **Sculpt**: sculptor = an Empty ``sculptor1`` (display Sphere, radius 1 Maya unit: Maya's implicit sphere;
  delta scale = maya_unit so the Channel Box shows Maya's Scale 1) and ``sculpt1StretchOrigin`` (plain axes), both at
  the deformed points' bounding-box centre ("Center within selection"); the rule =
  a model ("O": Stretch / Even, Flip / Ring, Project at the sculptor); Stretch with the origin moved off the
  sculptor, Flip / Even, Stretch / Ring, scaled sculptors and dropoff type None are [U] (the same rule, gaps recorded
  in tests/test_step205_deform_a.py). Maximum Displacement is a length (× maya_unit) in Stretch / Flip and a
  fraction in Project (Maya: the same attribute).

Delete Non-Deformer History keeps all three (history.is_deformer: every kit deformer in deformers.BASES); Delete
History bakes them. The Maya names / node types / Channel Box rows join deformers.BASES / ATTRS at register.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import math
import bpy
from bpy.props import EnumProperty
from mathutils import Vector
from .. import results, undo_steps
from . import deformers, units, wire_deformer
VERSION_PROP = 'allset_205a_version'
VERSION = 1
GROUPS = {'tension': '.Allset Tension', 'solidify': '.Allset Solidify', 'sculpt': '.Allset Sculpt'}
SLOT = '.allset_tension_p'
SLOT_COUNT = '.allset_tension_n'
REST = '.allset_rest_'
TOPO_PROP = 'allset_205a_topo'
TENSION_INPUTS = ((_dcc_source('Rest'), 'NodeSocketVector', None), (_dcc_source('Weight'), 'NodeSocketFloat', 1.0), (_dcc_source('Envelope'), 'NodeSocketFloat', 1.0), (_dcc_source('Smoothing Iterations'), 'NodeSocketInt', 10), (_dcc_source('Smoothing Step'), 'NodeSocketFloat', 0.5), (_dcc_source('Inward Constraint'), 'NodeSocketFloat', 0.0), (_dcc_source('Outward Constraint'), 'NodeSocketFloat', 0.0), (_dcc_source('Squash Constraint'), 'NodeSocketFloat', 1.0), (_dcc_source('Stretch Constraint'), 'NodeSocketFloat', 1.0), (_dcc_source('Shear Strength'), 'NodeSocketFloat', 0.0), (_dcc_source('Bend Strength'), 'NodeSocketFloat', 0.0), (_dcc_source('Relative'), 'NodeSocketFloat', 0.0), (_dcc_source('Pin Border Vertices'), 'NodeSocketBool', True))
SOLIDIFY_INPUTS = ((_dcc_source('Rest'), 'NodeSocketVector', None), (_dcc_source('Weight'), 'NodeSocketFloat', 1.0), (_dcc_source('Envelope'), 'NodeSocketFloat', 1.0), (_dcc_source('Normal Scale'), 'NodeSocketFloat', 1.0), (_dcc_source('Tangent Plane Scale'), 'NodeSocketFloat', 1.0), (_dcc_source('Scale Envelope'), 'NodeSocketFloat', 1.0), (_dcc_source('Attachment Mode'), 'NodeSocketInt', 0), (_dcc_source('Stabilization Level'), 'NodeSocketInt', 0), (_dcc_source('Use Border Falloff'), 'NodeSocketBool', True), (_dcc_source('Border Falloff Blur'), 'NodeSocketInt', 2), (_dcc_source('Scale Mode'), 'NodeSocketInt', 0))
SCULPT_INPUTS = ((_dcc_source('Sculptor'), 'NodeSocketObject', None), (_dcc_source('Stretch Origin'), 'NodeSocketObject', None), (_dcc_source('Weight'), 'NodeSocketFloat', 1.0), (_dcc_source('Envelope'), 'NodeSocketFloat', 1.0), (_dcc_source('Mode'), 'NodeSocketInt', 2), (_dcc_source('Inside Mode'), 'NodeSocketInt', 1), (_dcc_source('Maximum Displacement'), 'NodeSocketFloat', 0.1), (_dcc_source('Dropoff Distance'), 'NodeSocketFloat', 1.0), (_dcc_source('Dropoff Type'), 'NodeSocketInt', 1), (_dcc_source('Unit'), 'NodeSocketFloat', 1.0))
INPUTS = {'tension': TENSION_INPUTS, 'solidify': SOLIDIFY_INPUTS, 'sculpt': SCULPT_INPUTS}

class _B(wire_deformer._B):
    """wire_deformer's builder + the nodes these groups need (each helper returns an output socket)."""

    def out(self, n, name=0):
        return n.outputs[name]

    def cmp(self, a, b, eps=0.5):
        """1.0 where |a - b| <= eps (Math Compare)."""
        n = self.node('ShaderNodeMath', operation='COMPARE')
        self._in(n.inputs[0], a)
        self._in(n.inputs[1], b)
        self._in(n.inputs[2], eps)
        return n.outputs[0]

    def mix(self, cond, a, b):
        """a + cond · (b - a) for floats (cond 0 / 1)."""
        return self.math('ADD', a, self.math('MULTIPLY', cond, self.math('SUBTRACT', b, a)))

    def switch(self, kind, cond, false, true):
        n = self.node('GeometryNodeSwitch', input_type=kind)
        self._in(n.inputs[_dcc_source('Switch')], cond)
        self._in(n.inputs[_dcc_source('False')], false)
        self._in(n.inputs[_dcc_source('True')], true)
        return n.outputs[0]

    def combine(self, x, y, z):
        n = self.node('ShaderNodeCombineXYZ')
        for (i, v) in enumerate((x, y, z)):
            self._in(n.inputs[i], v)
        return n.outputs[0]

    def separate(self, v):
        n = self.node('ShaderNodeSeparateXYZ')
        self._in(n.inputs[0], v)
        return n.outputs

    def at_index(self, value, index, domain='POINT', data_type='FLOAT_VECTOR'):
        n = self.node('GeometryNodeFieldAtIndex', domain=domain, data_type=data_type)
        self._in(n.inputs[_dcc_source('Value')], value)
        self._in(n.inputs[_dcc_source('Index')], index)
        return n.outputs[0]

    def on_domain(self, value, domain, data_type='FLOAT'):
        n = self.node('GeometryNodeFieldOnDomain', domain=domain, data_type=data_type)
        self._in(n.inputs[0], value)
        return n.outputs[0]

    def named(self, name, data_type='FLOAT'):
        n = self.node('GeometryNodeInputNamedAttribute', data_type=data_type)
        self._in(n.inputs[_dcc_source('Name')], name)
        return n.outputs[_dcc_source('Attribute')]

    def store(self, geo, name, value, data_type='FLOAT', domain='POINT'):
        n = self.node('GeometryNodeStoreNamedAttribute', data_type=data_type, domain=domain)
        self.link(geo, n.inputs[_dcc_source('Geometry')])
        self._in(n.inputs[_dcc_source('Name')], name)
        self._in(n.inputs[_dcc_source('Value')], value)
        return n.outputs[0]

    def stat(self, geo, value, selection=None, domain='POINT', data_type='FLOAT'):
        n = self.node('GeometryNodeAttributeStatistic', domain=domain, data_type=data_type)
        self.link(geo, n.inputs[_dcc_source('Geometry')])
        self._in(n.inputs[_dcc_source('Attribute')], value)
        if selection is not None:
            self._in(n.inputs[_dcc_source('Selection')], selection)
        return n.outputs

    def position(self):
        return self.node('GeometryNodeInputPosition').outputs[0]

    def index(self):
        return self.node('GeometryNodeInputIndex').outputs[0]

    def set_position(self, geo, offset=None, position=None):
        n = self.node('GeometryNodeSetPosition')
        self.link(geo, n.inputs[_dcc_source('Geometry')])
        if offset is not None:
            self._in(n.inputs[_dcc_source('Offset')], offset)
        if position is not None:
            self._in(n.inputs[_dcc_source('Position')], position)
        return n.outputs[0]

    def repeat(self, geo, iterations, items=()):
        """(repeat input node, repeat output node): state = geometry (+ ``items`` (type, name, value))."""
        ri = self.node('GeometryNodeRepeatInput')
        ro = self.node('GeometryNodeRepeatOutput')
        ri.pair_with_output(ro)
        for (kind, name, _v) in items:
            ro.repeat_items.new(kind, name)
        self._in(ri.inputs[_dcc_source('Iterations')], iterations)
        self.link(geo, ri.inputs[_dcc_source('Geometry')])
        for (kind, name, v) in items:
            self._in(ri.inputs[name], v)
        return (ri, ro)

    def vlen(self, v):
        return self.vmath('LENGTH', v, out=_dcc_source('Value'))

    def dot(self, a, b):
        return self.vmath('DOT_PRODUCT', a, b, out=_dcc_source('Value'))

def _new_group(name, inputs):
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    ng[VERSION_PROP] = VERSION
    ng.interface.new_socket(_dcc_source('Geometry'), in_out='INPUT', socket_type='NodeSocketGeometry')
    for (sname, stype, default) in inputs:
        s = ng.interface.new_socket(sname, in_out='INPUT', socket_type=stype)
        if default is not None:
            s.default_value = default
    ng.interface.new_socket(_dcc_source('Geometry'), in_out='OUTPUT', socket_type='NodeSocketGeometry')
    b = _B(ng)
    (gin, gout) = (b.node('NodeGroupInput'), b.node('NodeGroupOutput'))
    return (ng, b, gin.outputs, gout)

def _maya_normal(b):
    """Maya's vertex normal (tension_model.normals): normalised sum over the vertex's corners of
    cross(P[f[k+h]] - p, P[f[k-h]] - p), h = max(1, m // 2 - 1) for an m-gon; a point field of the current geometry."""
    corner = b.index()
    foc = b.node('GeometryNodeFaceOfCorner')
    b.link(corner, foc.inputs[_dcc_source('Corner Index')])
    cof = b.node('GeometryNodeCornersOfFace')
    b.link(foc.outputs[_dcc_source('Face Index')], cof.inputs[_dcc_source('Face Index')])
    m = cof.outputs[_dcc_source('Total')]
    h = b.math('MAXIMUM', 1.0, b.math('SUBTRACT', b.math('FLOOR', b.math('DIVIDE', m, 2.0)), 1.0))
    sides = []
    for sign in (1.0, -1.0):
        off = b.node('GeometryNodeOffsetCornerInFace')
        b.link(corner, off.inputs[_dcc_source('Corner Index')])
        b._in(off.inputs[_dcc_source('Offset')], b.math('MULTIPLY', h, sign))
        sides.append(b.at_index(b.position(), off.outputs[0], domain='CORNER'))
    p = b.position()
    c = b.vmath('CROSS_PRODUCT', b.vmath('SUBTRACT', sides[0], p), b.vmath('SUBTRACT', sides[1], p))
    return b.vmath('NORMALIZE', b.on_domain(c, 'CORNER', 'FLOAT_VECTOR'))

def _slot(b, I, k):
    """(include 0/1, strength, partner index) of partner slot ``k`` (single int value) of each point."""
    vs = b.node('FunctionNodeValueToString')
    b._in(vs.inputs[_dcc_source('Value')], k)
    b._in(vs.inputs[_dcc_source('Decimals')], 0)
    name = b.node('FunctionNodeReplaceString')
    name.inputs[_dcc_source('String')].default_value = SLOT + '#'
    name.inputs[_dcc_source('Find')].default_value = '#'
    b.link(vs.outputs[0], name.inputs[_dcc_source('Replace')])
    code = b.named(name.outputs[0], 'INT')
    valid = b.math('GREATER_THAN', code, -0.5)
    j = b.math('FLOOR', b.math('DIVIDE', code, 8.0))
    fl = b.math('SUBTRACT', code, b.math('MULTIPLY', j, 8.0))
    edge = b.cmp(fl, 1.0, 0.25)
    diag = b.math('GREATER_THAN', b.math('MODULO', fl, 4.0), 1.5)
    bend = b.math('GREATER_THAN', fl, 3.5)
    extra = b.math('MAXIMUM', b.math('MULTIPLY', diag, I[_dcc_source('Shear Strength')]), b.math('MULTIPLY', bend, I[_dcc_source('Bend Strength')]))
    strength = b.mix(edge, extra, 1.0)
    inc = b.math('MULTIPLY', valid, b.math('GREATER_THAN', strength, 0.0))
    return (inc, strength, j)

def build_tension():
    """Maya tension: ``Smoothing Iterations`` Jacobi passes on the input, then
    out = input + envelope · weight · (P - input)."""
    (ng, b, I, gout) = _new_group(GROUPS['tension'], TENSION_INPUTS)
    g0 = I[_dcc_source('Geometry')]
    fc = b.node('GeometryNodeInputMeshEdgeNeighbors').outputs[_dcc_source('Face Count')]
    border = b.math('GREATER_THAN', b.on_domain(b.cmp(fc, 1.0, 0.25), 'EDGE'), 0.0)
    free = b.math('SUBTRACT', 1.0, b.math('MULTIPLY', border, I[_dcc_source('Pin Border Vertices')]))
    slots = b.stat(g0, b.named(SLOT_COUNT, 'INT'))[_dcc_source('Max')]
    (ri, ro) = b.repeat(g0, I[_dcc_source('Smoothing Iterations')])
    g = ri.outputs[_dcc_source('Geometry')]
    g1 = b.store(b.store(g, '.allset_t_sl', 0.0), '.allset_t_sr', 0.0)
    (r1, o1) = b.repeat(g1, slots)
    (inc, _s, j) = _slot(b, I, r1.outputs[_dcc_source('Iteration')])
    p = b.position()
    L = b.vlen(b.vmath('SUBTRACT', p, b.at_index(b.position(), j)))
    L0 = b.vlen(b.vmath('SUBTRACT', I[_dcc_source('Rest')], b.at_index(I[_dcc_source('Rest')], j)))
    acc = b.store(r1.outputs[_dcc_source('Geometry')], '.allset_t_sl', b.math('ADD', b.named('.allset_t_sl'), b.math('MULTIPLY', inc, L)))
    acc = b.store(acc, '.allset_t_sr', b.math('ADD', b.named('.allset_t_sr'), b.math('MULTIPLY', inc, L0)))
    b.link(acc, o1.inputs[_dcc_source('Geometry')])
    g2 = o1.outputs[_dcc_source('Geometry')]
    s_i = b.math('DIVIDE', b.named('.allset_t_sl'), b.named('.allset_t_sr'))
    k_i = b.math('ADD', 1.0, b.math('MULTIPLY', I[_dcc_source('Relative')], b.math('SUBTRACT', s_i, 1.0)))
    g2 = b.store(g2, '.allset_t_k', k_i)
    g2 = b.store(b.store(g2, '.allset_t_sum', (0.0, 0.0, 0.0), 'FLOAT_VECTOR'), '.allset_t_cnt', 0.0)
    (r2, o2) = b.repeat(g2, slots)
    (inc, strength, j) = _slot(b, I, r2.outputs[_dcc_source('Iteration')])
    p = b.position()
    pj = b.at_index(b.position(), j)
    d = b.vmath('SUBTRACT', p, pj)
    L = b.vlen(d)
    L0 = b.math('MULTIPLY', b.vlen(b.vmath('SUBTRACT', I[_dcc_source('Rest')], b.at_index(I[_dcc_source('Rest')], j))), b.named('.allset_t_k'))
    c = b.mix(b.math('LESS_THAN', L, L0), I[_dcc_source('Stretch Constraint')], I[_dcc_source('Squash Constraint')])
    lt = b.math('ADD', L, b.math('MULTIPLY', b.math('MULTIPLY', c, strength), b.math('SUBTRACT', L0, L)))
    t = b.vmath('ADD', pj, b.vmath('SCALE', d, scale=b.math('DIVIDE', lt, L)))
    acc = b.store(r2.outputs[_dcc_source('Geometry')], '.allset_t_sum', b.vmath('ADD', b.named('.allset_t_sum', 'FLOAT_VECTOR'), b.vmath('SCALE', t, scale=inc)), 'FLOAT_VECTOR')
    acc = b.store(acc, '.allset_t_cnt', b.math('ADD', b.named('.allset_t_cnt'), inc))
    b.link(acc, o2.inputs[_dcc_source('Geometry')])
    g3 = o2.outputs[_dcc_source('Geometry')]
    cnt = b.named('.allset_t_cnt')
    p = b.position()
    mean = b.vmath('SCALE', b.named('.allset_t_sum', 'FLOAT_VECTOR'), scale=b.math('DIVIDE', 1.0, cnt))
    has = b.math('GREATER_THAN', cnt, 0.0)
    delta = b.vmath('SCALE', b.vmath('SUBTRACT', mean, p), scale=b.math('MULTIPLY', I[_dcc_source('Smoothing Step')], has))
    n = _maya_normal(b)
    dn = b.dot(delta, n)
    corr = b.math('ADD', b.math('MULTIPLY', b.math('MINIMUM', dn, 0.0), I[_dcc_source('Inward Constraint')]), b.math('MULTIPLY', b.math('MAXIMUM', dn, 0.0), I[_dcc_source('Outward Constraint')]))
    delta = b.vmath('SUBTRACT', delta, b.vmath('SCALE', n, scale=corr))
    g4 = b.set_position(g3, offset=b.vmath('SCALE', delta, scale=free))
    b.link(g4, ro.inputs[_dcc_source('Geometry')])
    final = ro.outputs[_dcc_source('Geometry')]
    pf = b.node('GeometryNodeSampleIndex', data_type='FLOAT_VECTOR', domain='POINT')
    b.link(final, pf.inputs[_dcc_source('Geometry')])
    b.link(b.position(), pf.inputs[_dcc_source('Value')])
    b.link(b.index(), pf.inputs[_dcc_source('Index')])
    w = b.math('MULTIPLY', I[_dcc_source('Envelope')], I[_dcc_source('Weight')])
    out = b.set_position(g0, offset=b.vmath('SCALE', b.vmath('SUBTRACT', pf.outputs[0], b.position()), scale=w))
    b.link(out, gout.inputs[0])
    return ng

def build_sculpt():
    """Maya sculpt (the step-205 model)."""
    (ng, b, I, gout) = _new_group(GROUPS['sculpt'], SCULPT_INPUTS)
    info = b.node('GeometryNodeObjectInfo', transform_space='RELATIVE')
    b.link(I[_dcc_source('Sculptor')], info.inputs[_dcc_source('Object')])
    M = info.outputs[_dcc_source('Transform')]
    inv = b.node('FunctionNodeInvertMatrix')
    b.link(M, inv.inputs[_dcc_source('Matrix')])
    Minv = inv.outputs[_dcc_source('Matrix')]
    oinfo = b.node('GeometryNodeObjectInfo', transform_space='RELATIVE')
    b.link(I[_dcc_source('Stretch Origin')], oinfo.inputs[_dcc_source('Object')])

    def tp(v, m):
        n = b.node('FunctionNodeTransformPoint')
        b._in(n.inputs[_dcc_source('Vector')], v)
        b.link(m, n.inputs[_dcc_source('Transform')])
        return n.outputs[0]

    def td(v, m):
        n = b.node('FunctionNodeTransformDirection')
        b._in(n.inputs[_dcc_source('Direction')], v)
        b.link(m, n.inputs[_dcc_source('Transform')])
        return n.outputs[0]
    md_len = b.math('MULTIPLY', I[_dcc_source('Maximum Displacement')], I[_dcc_source('Unit')])
    dd = b.math('MULTIPLY', I[_dcc_source('Dropoff Distance')], I[_dcc_source('Unit')])
    linear = b.cmp(I[_dcc_source('Dropoff Type')], 1.0, 0.25)
    p = b.position()
    q = tp(p, Minv)
    rq = b.vlen(q)
    inside = b.math('LESS_THAN', rq, 1.0)
    centre = tp((0.0, 0.0, 0.0), M)
    src = b.switch('VECTOR', b.cmp(I[_dcc_source('Mode')], 2.0, 0.25), centre, oinfo.outputs[_dcc_source('Location')])
    sq = tp(src, Minv)
    dvec = b.vmath('SUBTRACT', q, sq)
    tiny = b.math('LESS_THAN', b.vlen(dvec), 1e-12)
    fallback = b.switch('VECTOR', b.math('GREATER_THAN', b.vlen(sq), 1e-12), (1.0, 0.0, 0.0), b.vmath('SCALE', sq, scale=-1.0))
    dvec = b.switch('VECTOR', tiny, dvec, fallback)
    dl = b.vmath('NORMALIZE', dvec)
    bb = b.dot(sq, dl)
    cc = b.math('SUBTRACT', b.dot(sq, sq), 1.0)
    t = b.math('ADD', b.math('MULTIPLY', bb, -1.0), b.math('SQRT', b.math('MAXIMUM', b.math('SUBTRACT', b.math('MULTIPLY', bb, bb), cc), 0.0)))
    s = tp(b.vmath('ADD', sq, b.vmath('SCALE', dl, scale=t)), M)
    dw = b.vmath('NORMALIZE', td(dl, M))
    dist = b.math('MULTIPLY', b.math('SUBTRACT', rq, 1.0), b.vlen(td(b.vmath('SCALE', q, scale=b.math('DIVIDE', 1.0, rq)), M)))
    w_lin = b.math('MAXIMUM', 0.0, b.math('SUBTRACT', 1.0, b.math('DIVIDE', dist, dd)))
    w_none = b.math('SUBTRACT', 1.0, b.math('GREATER_THAN', dist, dd))
    w = b.mix(linear, w_none, w_lin)
    np_in = b.vmath('ADD', s, b.vmath('SCALE', dw, scale=md_len))
    np_out = b.vmath('ADD', p, b.vmath('SCALE', dw, scale=b.math('MULTIPLY', md_len, w)))
    np_s = b.switch('VECTOR', inside, np_out, np_in)
    nq = b.switch('VECTOR', b.math('GREATER_THAN', rq, 0.0), (1.0, 0.0, 0.0), b.vmath('SCALE', q, scale=b.math('DIVIDE', 1.0, rq)))
    sw = tp(nq, M)
    distp = b.vlen(b.vmath('SUBTRACT', p, sw))
    skip = b.math('MULTIPLY', b.math('MULTIPLY', b.math('SUBTRACT', 1.0, inside), b.math('GREATER_THAN', distp, dd)), linear)
    np_p = b.vmath('ADD', p, b.vmath('SCALE', b.vmath('SUBTRACT', sw, p), scale=b.math('MULTIPLY', I[_dcc_source('Maximum Displacement')], b.math('SUBTRACT', 1.0, skip))))
    target = b.switch('VECTOR', b.cmp(I[_dcc_source('Mode')], 1.0, 0.25), np_s, np_p)
    wt = b.math('MULTIPLY', I[_dcc_source('Envelope')], I[_dcc_source('Weight')])
    out = b.set_position(I[_dcc_source('Geometry')], offset=b.vmath('SCALE', b.vmath('SUBTRACT', target, p), scale=wt))
    b.link(out, gout.inputs[0])
    return ng

def build_solidify():
    """Maya solidify ([U] rule — see the module doc)."""
    (ng, b, I, gout) = _new_group(GROUPS['solidify'], SOLIDIFY_INPUTS)
    g0 = I[_dcc_source('Geometry')]
    mem = b.math('GREATER_THAN', I[_dcc_source('Weight')], 0.0)
    face_in = b.math('GREATER_THAN', b.on_domain(mem, 'POINT'), 0.999)
    out_faces = b.on_domain(b.math('SUBTRACT', 1.0, face_in), 'FACE')
    border = b.math('MULTIPLY', mem, b.math('GREATER_THAN', out_faces, 0.001))
    has_border = b.math('GREATER_THAN', b.stat(g0, border)[_dcc_source('Max')], 0.5)
    w0 = b.math('MULTIPLY', mem, b.math('SUBTRACT', 1.0, border))
    blur = b.node('GeometryNodeBlurAttribute', data_type='FLOAT')
    b._in(blur.inputs[_dcc_source('Value')], w0)
    b._in(blur.inputs[_dcc_source('Iterations')], I[_dcc_source('Border Falloff Blur')])
    w_fall = b.math('MULTIPLY', blur.outputs[0], w0)
    w = b.switch('FLOAT', I[_dcc_source('Use Border Falloff')], mem, w_fall)
    full = b.cmp(I[_dcc_source('Attachment Mode')], 1.0, 0.25)
    w = b.math('MULTIPLY', w, b.math('MAXIMUM', full, has_border))
    w = b.math('MULTIPLY', w, b.math('MULTIPLY', I[_dcc_source('Weight')], I[_dcc_source('Envelope')]))
    cr = b.stat(g0, I[_dcc_source('Rest')], mem, data_type='FLOAT_VECTOR')[_dcc_source('Mean')]
    cp = b.stat(g0, b.position(), mem, data_type='FLOAT_VECTOR')[_dcc_source('Mean')]
    dr = b.vmath('SUBTRACT', I[_dcc_source('Rest')], cr)
    dp = b.vmath('SUBTRACT', b.position(), cp)
    rest_geo = b.set_position(g0, position=I[_dcc_source('Rest')])
    n_r = b.vmath('NORMALIZE', b.stat(rest_geo, b.node('GeometryNodeInputNormal').outputs[0], mem, data_type='FLOAT_VECTOR')[_dcc_source('Sum')])
    n_p = b.vmath('NORMALIZE', b.stat(g0, b.node('GeometryNodeInputNormal').outputs[0], mem, data_type='FLOAT_VECTOR')[_dcc_source('Sum')])
    sc = b.stat(g0, b.math('MULTIPLY', b.vlen(dr), b.vlen(dp)), mem)[_dcc_source('Sum')]
    drs = b.separate(dr)
    nrs = b.separate(n_r)
    cols = []
    for k in range(3):
        col = b.stat(g0, b.vmath('SCALE', dp, scale=drs[k]), mem, data_type='FLOAT_VECTOR')[_dcc_source('Sum')]
        cols.append(b.vmath('ADD', col, b.vmath('SCALE', n_p, scale=b.math('MULTIPLY', sc, nrs[k]))))
    fro = b.math('SQRT', b.math('DIVIDE', b.math('ADD', b.math('ADD', b.dot(cols[0], cols[0]), b.dot(cols[1], cols[1])), b.dot(cols[2], cols[2])), 3.0))
    inv_f = b.math('DIVIDE', 1.0, fro)
    cm = b.node('FunctionNodeCombineMatrix')
    for k in range(3):
        comp = b.separate(b.vmath('SCALE', cols[k], scale=inv_f))
        for r in range(3):
            b._in(cm.inputs[k * 4 + r], comp[r])
        cm.inputs[k * 4 + 3].default_value = 0.0
    for r in range(3):
        cm.inputs[12 + r].default_value = 0.0
    cm.inputs[15].default_value = 1.0
    ri = b.node('GeometryNodeRepeatInput')
    ro = b.node('GeometryNodeRepeatOutput')
    ri.pair_with_output(ro)
    ro.repeat_items.new('MATRIX', 'X')
    ri.inputs[_dcc_source('Iterations')].default_value = 16
    b.link(g0, ri.inputs[_dcc_source('Geometry')])
    b.link(cm.outputs[0], ri.inputs['X'])
    b.link(ri.outputs[_dcc_source('Geometry')], ro.inputs[_dcc_source('Geometry')])
    x = ri.outputs['X']
    xi = b.node('FunctionNodeInvertMatrix')
    b.link(x, xi.inputs[_dcc_source('Matrix')])
    xt = b.node('FunctionNodeTransposeMatrix')
    b.link(xi.outputs[_dcc_source('Matrix')], xt.inputs[_dcc_source('Matrix')])
    sa = b.node('FunctionNodeSeparateMatrix')
    b.link(x, sa.inputs[_dcc_source('Matrix')])
    sb = b.node('FunctionNodeSeparateMatrix')
    b.link(xt.outputs[_dcc_source('Matrix')], sb.inputs[_dcc_source('Matrix')])
    nx = b.node('FunctionNodeCombineMatrix')
    for i in range(16):
        if i % 4 == 3 or i >= 12:
            nx.inputs[i].default_value = 1.0 if i == 15 else 0.0
            continue
        b.link(b.math('MULTIPLY', b.math('ADD', sa.outputs[i], sb.outputs[i]), 0.5), nx.inputs[i])
    b.link(nx.outputs[0], ro.inputs['X'])
    sep = b.node('FunctionNodeSeparateTransform')
    b.link(ro.outputs['X'], sep.inputs[_dcc_source('Transform')])
    aa = b.node('FunctionNodeRotationToAxisAngle')
    b.link(sep.outputs[_dcc_source('Rotation')], aa.inputs[_dcc_source('Rotation')])
    ang = b.math('DIVIDE', aa.outputs[_dcc_source('Angle')], b.math('ADD', 1.0, b.math('MULTIPLY', I[_dcc_source('Stabilization Level')], 0.5)))
    rot = b.node('FunctionNodeAxisAngleToRotation')
    b.link(aa.outputs[_dcc_source('Axis')], rot.inputs[_dcc_source('Axis')])
    b.link(ang, rot.inputs[_dcc_source('Angle')])

    def turn(v):
        n = b.node('FunctionNodeRotateVector')
        b._in(n.inputs[_dcc_source('Vector')], v)
        b.link(rot.outputs[_dcc_source('Rotation')], n.inputs[_dcc_source('Rotation')])
        return n.outputs[0]
    o = turn(dr)
    ev = b.node('GeometryNodeInputMeshEdgeVertices')
    (v1, v2) = (ev.outputs[_dcc_source('Vertex Index 1')], ev.outputs[_dcc_source('Vertex Index 2')])
    e_mem = b.math('MULTIPLY', b.at_index(mem, v1, data_type='FLOAT'), b.at_index(mem, v2, data_type='FLOAT'))
    e_in = b.vlen(b.vmath('SUBTRACT', ev.outputs[_dcc_source('Position 1')], ev.outputs[_dcc_source('Position 2')]))
    e_rest = b.vlen(b.vmath('SUBTRACT', b.at_index(I[_dcc_source('Rest')], v1), b.at_index(I[_dcc_source('Rest')], v2)))
    ratio = b.math('DIVIDE', b.stat(g0, e_in, e_mem, domain='EDGE')[_dcc_source('Sum')], b.stat(g0, e_rest, e_mem, domain='EDGE')[_dcc_source('Sum')])
    s = b.math('ADD', 1.0, b.math('MULTIPLY', I[_dcc_source('Scale Envelope')], b.math('SUBTRACT', ratio, 1.0)))
    nn = b.vmath('NORMALIZE', turn(n_r))
    on = b.vmath('SCALE', nn, scale=b.dot(o, nn))
    ot = b.vmath('SUBTRACT', o, on)
    scaled = b.vmath('SCALE', b.vmath('ADD', b.vmath('SCALE', ot, scale=I[_dcc_source('Tangent Plane Scale')]), b.vmath('SCALE', on, scale=I[_dcc_source('Normal Scale')])), scale=s)
    o = b.switch('VECTOR', b.math('GREATER_THAN', I[_dcc_source('Scale Mode')], 0.5), o, scaled)
    target = b.vmath('ADD', cp, o)
    out = b.set_position(g0, offset=b.vmath('SCALE', b.vmath('SUBTRACT', target, b.position()), scale=w))
    b.link(out, gout.inputs[0])
    return ng
BUILDERS = {'tension': build_tension, 'solidify': build_solidify, 'sculpt': build_sculpt}

def group(kind):
    ng = bpy.data.node_groups.get(GROUPS[kind])
    if ng is not None and ng.bl_idname == 'GeometryNodeTree' and (ng.get(VERSION_PROP) == VERSION):
        return ng
    if ng is not None:
        ng.name = GROUPS[kind] + '.old'
    return BUILDERS[kind]()

def kind_of(md):
    """"tension" / "solidify" / "sculpt" for a kit modifier of this module, else None."""
    if md.type != 'NODES' or md.node_group is None:
        return None
    for (kind, name) in GROUPS.items():
        if md.node_group.name.startswith(name):
            return kind
    return None

def partners(faces, n):
    """[[(partner, flags)]] per vertex: edge neighbours (flag 1), then face diagonals (2) / bend partners (4) — the
    sets of the step-205 tension model (diagonals, bend_partners)."""
    nb = [set() for _ in range(n)]
    edge_faces = {}
    for (fi, f) in enumerate(faces):
        for k in range(len(f)):
            (a, c) = (f[k], f[(k + 1) % len(f)])
            nb[a].add(c)
            nb[c].add(a)
            edge_faces.setdefault((min(a, c), max(a, c)), set()).add(fi)
    dg = [set() for _ in range(n)]
    for f in faces:
        for v in f:
            for u in f:
                if u != v and u not in nb[v]:
                    dg[v].add(u)
    bp = [set() for _ in range(n)]
    for f in faces:
        for k in range(2, len(f) - 1):
            bp[f[0]].add(f[k])
            bp[f[k]].add(f[0])
    for i in range(n):
        for j in nb[i]:
            fij = edge_faces[min(i, j), max(i, j)]
            for k in nb[j]:
                if k != i and (not edge_faces[min(j, k), max(j, k)] & fij):
                    bp[i].add(k)
    out = []
    for i in range(n):
        row = [(j, 1) for j in sorted(nb[i])]
        row += [(j, (2 if j in dg[i] else 0) | (4 if j in bp[i] else 0)) for j in sorted(dg[i] | bp[i])]
        out.append(row)
    return out

def _signature(me):
    return [len(me.vertices), len(me.edges), len(me.loops)]

def write_partners(me):
    """The tension partner table of ``me`` as hidden INT point attributes."""
    n = len(me.vertices)
    rows = partners([list(p.vertices) for p in me.polygons], n)
    width = max((len(r) for r in rows), default=0)
    for a in [a.name for a in me.attributes if a.name.startswith(SLOT)]:
        me.attributes.remove(me.attributes[a])
    if SLOT_COUNT in me.attributes:
        me.attributes.remove(me.attributes[SLOT_COUNT])
    cnt = me.attributes.new(SLOT_COUNT, 'INT', 'POINT')
    cnt.data.foreach_set('value', [len(r) for r in rows])
    for k in range(width):
        a = me.attributes.new(f'{SLOT}{k}', 'INT', 'POINT')
        a.data.foreach_set('value', [r[k][0] * 8 + r[k][1] if k < len(r) else -1 for r in rows])

def write_rest(me, node):
    """``.allset_rest_<node>`` = the mesh's base positions (Maya's <shape>Orig)."""
    name = REST + node
    if name in me.attributes:
        me.attributes.remove(me.attributes[name])
    a = me.attributes.new(name, 'FLOAT_VECTOR', 'POINT')
    co = [0.0] * (3 * len(me.vertices))
    me.vertices.foreach_get('co', co)
    a.data.foreach_set('vector', co)

def sync(ob):
    """After a topology change (or on a mesh without the tables): partner table and rest positions again; tables of
    removed deformers are dropped. Returns True when the mesh was written."""
    if ob.type != 'MESH' or ob.mode == 'EDIT' or ob.data is None:
        return False
    me = ob.data
    mds = [(md, kind_of(md)) for md in ob.modifiers]
    mds = [(md, k) for (md, k) in mds if k in ('tension', 'solidify')]
    sig = _signature(me)
    changed = list(me.get(TOPO_PROP, [])) != sig
    wrote = False
    if any((k == 'tension' for (_m, k) in mds)) and (changed or SLOT_COUNT not in me.attributes):
        write_partners(me)
        wrote = True
    if not any((k == 'tension' for (_m, k) in mds)) and SLOT_COUNT in me.attributes:
        for a in [a.name for a in me.attributes if a.name.startswith(SLOT) or a.name == SLOT_COUNT]:
            me.attributes.remove(me.attributes[a])
        wrote = True
    wanted = {REST + md.name for (md, _k) in mds}
    for (md, _k) in mds:
        if changed or REST + md.name not in me.attributes:
            write_rest(me, md.name)
            _attr_input(md, _dcc_source('Rest'), REST + md.name)
            wrote = True
    for a in [a.name for a in me.attributes if a.name.startswith(REST) and a.name not in wanted]:
        me.attributes.remove(me.attributes[a])
        wrote = True
    if mds and changed:
        me[TOPO_PROP] = sig
    elif not mds and TOPO_PROP in me:
        del me[TOPO_PROP]
    return wrote

def _attr_input(md, name, attribute):
    from .. import compat
    compat.gn_input_attribute(md, wire_deformer.ident(md, name), attribute)
DEFAULTS = {'TENSION': {'iterations': 10, _dcc_source('step'): 0.5, 'pin_border': True, 'relative': 0.0, 'inward': 0.0, 'outward': 0.0, 'squash': 1.0, 'stretch': 1.0, 'shear': 0.0, 'bend': 0.0}, 'SOLIDIFY': {'attachment': _dcc_source('Borders'), 'stabilization': 0, 'border_falloff': True, 'falloff_iterations': 2}, 'SCULPT': {'mode': _dcc_source('Stretch'), 'inside_mode': _dcc_source('Even'), 'max_displacement': 0.1, 'dropoff_type': _dcc_source('Linear'), 'dropoff_distance': 1.0, 'centered': True}}
SCULPT_MODES = (_dcc_source('Flip'), _dcc_source('Project'), _dcc_source('Stretch'))
INSIDE_MODES = (_dcc_source('Ring'), _dcc_source('Even'))
DROPOFF_TYPES = (_dcc_source('None'), _dcc_source('Linear'))

def _meshes(context):
    items = [(ob, idx) for (ob, idx) in deformers._deformed(context) if ob.type == 'MESH']
    if not items:
        raise RuntimeError(_dcc_source('Select a mesh to deform.'))
    return items

def _add_node(ob, name, kind, idx):
    """The GN modifier ``name`` + its weights vertex group (weight 1 on the deformed points)."""
    vg = deformers._weights(ob, name, idx)
    md = ob.modifiers.new(name, 'NODES')
    md.node_group = group(kind)
    _attr_input(md, _dcc_source('Weight'), vg)
    if kind in ('tension', 'solidify'):
        sync(ob)
    return md

def _set(md, values):
    for (key, v) in values.items():
        wire_deformer.set_(md, key, v)

def _tension(context, v):
    items = _meshes(context)
    name = deformers.new_name('tension')
    for (ob, idx) in items:
        md = _add_node(ob, name, 'tension', idx)
        _set(md, {_dcc_source('Smoothing Iterations'): int(v['iterations']), _dcc_source('Smoothing Step'): float(v[_dcc_source('step')]), _dcc_source('Pin Border Vertices'): bool(v['pin_border']), _dcc_source('Relative'): float(v['relative']), _dcc_source('Inward Constraint'): float(v['inward']), _dcc_source('Outward Constraint'): float(v['outward']), _dcc_source('Squash Constraint'): float(v['squash']), _dcc_source('Stretch Constraint'): float(v['stretch']), _dcc_source('Shear Strength'): float(v['shear']), _dcc_source('Bend Strength'): float(v['bend'])})
    obs = [ob for (ob, _i) in items]
    deformers._select_only(context, obs, obs[0])
    return obs[0]

def _solidify(context, v):
    items = _meshes(context)
    name = deformers.new_name('solidify')
    for (ob, idx) in items:
        md = _add_node(ob, name, 'solidify', idx)
        _set(md, {_dcc_source('Attachment Mode'): 1 if v['attachment'] == _dcc_source('Full') else 0, _dcc_source('Stabilization Level'): int(v['stabilization']), _dcc_source('Use Border Falloff'): bool(v['border_falloff']), _dcc_source('Border Falloff Blur'): int(v['falloff_iterations'])})
    obs = [ob for (ob, _i) in items]
    deformers._select_only(context, obs, obs[0])
    return obs[0]

def _sculpt(context, v):
    items = _meshes(context)
    (lo, hi) = deformers._bounds(items)
    name = deformers.new_name('sculpt')
    u = units.maya_unit(context.scene)
    n = 1
    taken = {o.name for o in bpy.data.objects}
    while f'sculptor{n}' in taken:
        n += 1
    centre = (lo + hi) / 2 if v['centered'] else Vector()
    sculptor = deformers._link(context, bpy.data.objects.new(f'sculptor{n}', None))
    sculptor.empty_display_type = 'SPHERE'
    sculptor.empty_display_size = 1.0
    origin = deformers._link(context, bpy.data.objects.new(f'{name}StretchOrigin', None))
    origin.empty_display_type = 'PLAIN_AXES'
    origin.empty_display_size = 1.0
    for e in (sculptor, origin):
        e.delta_scale = (u, u, u)
        e.location = centre
    context.view_layer.update()
    for (ob, idx) in items:
        md = _add_node(ob, name, 'sculpt', idx)
        _set(md, {_dcc_source('Sculptor'): sculptor, _dcc_source('Stretch Origin'): origin, _dcc_source('Mode'): SCULPT_MODES.index(v['mode']), _dcc_source('Inside Mode'): INSIDE_MODES.index(v['inside_mode']), _dcc_source('Maximum Displacement'): float(v['max_displacement']), _dcc_source('Dropoff Type'): DROPOFF_TYPES.index(v['dropoff_type']), _dcc_source('Dropoff Distance'): float(v['dropoff_distance']), _dcc_source('Unit'): float(u)})
    deformers._select_only(context, [sculptor], sculptor)
    return sculptor

def create(context, kind, values=None):
    """Make Maya deformer ``kind`` (TENSION / SOLIDIFY / SCULPT) on the selection with ``values`` (option window
    values; missing = Maya factory). Raises RuntimeError with a Maya-style message when the selection doesn't fit."""
    v = {**DEFAULTS[kind], **(values or {})}
    return {'TENSION': _tension, 'SOLIDIFY': _solidify, 'SCULPT': _sculpt}[kind](context, v)
KINDS = tuple(((k, k.title(), '') for k in DEFAULTS))

class ALLSET_OT_deformer_tss(bpy.types.Operator):
    """Make a Maya Tension / Solidify / Sculpt deformer on the selection (Maya Deform menu)"""
    bl_translation_context = 'MWK:operators/deformers_205a.py:732'
    bl_idname = 'allset.deformer_tss'
    bl_label = _zh_native('Create Deformer', 'MWK:operators/deformers_205a.py:732')
    bl_description = _zh_native('Make a Maya Tension / Solidify / Sculpt deformer on the selection (Maya Deform menu)', 'MWK:operators/deformers_205a.py:732')
    bl_options = {'REGISTER', 'UNDO'}
    kind: EnumProperty(items=_zh_enum(KINDS, 'MWK:operators/deformers_205a.py:735'), name=_zh_native('Deformer', 'MWK:operators/deformers_205a.py:735'), options={'HIDDEN', 'SKIP_SAVE'}, translation_context='MWK:operators/deformers_205a.py:735')

    @classmethod
    def description(cls, context, properties):
        return _zh({'TENSION': 'Keep the edge lengths of the deformed mesh (Maya Deform > Tension)', 'SOLIDIFY': 'Keep a region of the deformed mesh rigid (Maya Deform > Solidify)', 'SCULPT': 'Push the mesh with a sphere (Maya Deform > Sculpt)'}.get(properties.kind, ''), 'MWK:operators/deformers_205a.py:739')

    def execute(self, context):
        from . import option_windows
        window = next((w for w in option_windows.WINDOWS if w.match == (self.bl_idname, {'kind': self.kind})), None)
        values = option_windows.saved(window.key) if window is not None else None
        try:
            create(context, self.kind, values)
        except RuntimeError as ex:
            self.report({'WARNING'}, _zh(str(ex), 'MWK:operators/deformers_205a.py:750'))
            return {'CANCELLED'}
        return {'FINISHED'}

def sculpt_targets(context):
    """[(mesh object, sculpt modifier)] for the selection: selected meshes' sculpt nodes, and the nodes a selected
    sculptor / stretch origin drives."""
    sel = set(context.selected_objects) | ({context.active_object} if context.active_object else set())
    out = []
    for ob in bpy.data.objects:
        for md in getattr(ob, 'modifiers', ()):
            if kind_of(md) != 'sculpt':
                continue
            if ob in sel or wire_deformer.get(md, _dcc_source('Sculptor')) in sel or wire_deformer.get(md, _dcc_source('Stretch Origin')) in sel:
                out.append((ob, md))
    return out

def sculpt_influence(md, points, ob_matrix):
    """Indices of ``points`` (object space) the sculpt node can move (weights and envelope aside): inside the sphere,
    or within the dropoff distance of it (Project: of its radial surface point)."""
    get = wire_deformer.get
    sculptor = get(md, _dcc_source('Sculptor'))
    if sculptor is None:
        return set()
    M = ob_matrix.inverted() @ sculptor.matrix_world
    Minv = M.inverted()
    dd = float(get(md, _dcc_source('Dropoff Distance'))) * float(get(md, _dcc_source('Unit')))
    linear = int(get(md, _dcc_source('Dropoff Type'))) == 1
    project = int(get(md, _dcc_source('Mode'))) == 1
    out = set()
    for (i, p) in enumerate(points):
        q = Minv @ p
        rq = q.length
        if rq < 1.0 or (not linear and project):
            out.add(i)
            continue
        if project:
            dist = (p - M @ (q / rq)).length
            if dist <= dd:
                out.add(i)
            continue
        dist = (rq - 1.0) * (M.to_3x3() @ (q / rq)).length
        if dist < dd if linear else dist <= dd:
            out.add(i)
    return out

def _input_points(context, ob, md):
    """Object-space positions the modifier ``md`` receives (the modifiers above it evaluated)."""
    shown = {m.name: m.show_viewport for m in ob.modifiers}
    after = False
    for m in ob.modifiers:
        if m == md:
            after = True
        if after:
            m.show_viewport = False
    try:
        dg = context.evaluated_depsgraph_get()
        dg.update()
        me = ob.evaluated_get(dg).to_mesh()
        pts = [v.co.copy() for v in me.vertices]
        ob.evaluated_get(dg).to_mesh_clear()
    finally:
        for m in ob.modifiers:
            m.show_viewport = shown[m.name]
    if len(pts) != len(ob.data.vertices):
        pts = [v.co.copy() for v in ob.data.vertices]
    return pts

def prune_sculpt(context):
    """Maya ``cmds.sculpt(edit=True, prune=True)``: the points the sculptor can't reach leave the node's vertex group.
    Returns the count."""
    n = 0
    for (ob, md) in sculpt_targets(context):
        vg = ob.vertex_groups.get(md.name)
        if vg is None:
            continue
        keep = sculpt_influence(md, _input_points(context, ob, md), ob.matrix_world)
        drop = [v.index for v in ob.data.vertices if v.index not in keep and any((g.group == vg.index for g in v.groups))]
        if drop:
            vg.remove(drop)
            n += len(drop)
    return n

@undo_steps.no_redo_panel
class ALLSET_OT_prune_sculpt(bpy.types.Operator):
    """Remove the points the sculptor can't reach from the sculpt deformer (Maya Deform > Prune Membership > Sculpt)"""
    bl_translation_context = 'MWK:operators/deformers_205a.py:845'
    bl_idname = 'allset.prune_sculpt'
    bl_label = _zh_native('Prune Membership', 'MWK:operators/deformers_205a.py:845')
    bl_description = _zh_native("Remove the points the sculptor can't reach from the sculpt deformer (Maya Deform > Prune Membership > Sculpt)", 'MWK:operators/deformers_205a.py:845')
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from . import deform_edit
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if not sculpt_targets(context):
            self.report({'WARNING'}, _zh('Select a sculpt deformer, its sculptor or the deformed object.', 'MWK:operators/deformers_205a.py:853'))
            return {'CANCELLED'}
        n = prune_sculpt(context)
        if not n:
            results.result(self, _zh(deform_edit.PRUNE_NONE, 'MWK:operators/deformers_205a.py:857'))
            return {'CANCELLED'}
        results.result(self, _zh(f'{n} points pruned', 'MWK:operators/deformers_205a.py:859'))
        return {'FINISHED'}
classes = (ALLSET_OT_deformer_tss, ALLSET_OT_prune_sculpt)

def _gn(name, cast=float):

    def get(md):
        v = wire_deformer.get(md, name)
        return cast(v) if v is not None else cast(0)

    def set_(md, v):
        wire_deformer.set_(md, name, cast(v))
    return (get, set_)

def _attrs(rows):
    return [deformers.Attr(key, label, kind, *_gn(name, int if kind == 'INT' else bool if kind == 'BOOL' else float)) for (key, label, kind, name) in rows]
BASES = {'tension': ('NODES', 'tension'), 'solidify': ('NODES', 'solidify'), 'sculpt': ('NODES', 'sculpt')}
ATTR_ROWS = {'tension': [('envelope', _dcc_source('Envelope'), 'NONE', _dcc_source('Envelope')), ('smoothingIterations', _dcc_source('Smoothing Iterations'), 'INT', _dcc_source('Smoothing Iterations')), ('smoothingStep', _dcc_source('Smoothing Step'), 'NONE', _dcc_source('Smoothing Step')), ('inwardConstraint', _dcc_source('Inward Constraint'), 'NONE', _dcc_source('Inward Constraint')), ('outwardConstraint', _dcc_source('Outward Constraint'), 'NONE', _dcc_source('Outward Constraint')), ('squashConstraint', _dcc_source('Squash Constraint'), 'NONE', _dcc_source('Squash Constraint')), ('stretchConstraint', _dcc_source('Stretch Constraint'), 'NONE', _dcc_source('Stretch Constraint')), ('relative', _dcc_source('Relative'), 'NONE', _dcc_source('Relative'))], 'solidify': [('envelope', _dcc_source('Envelope'), 'NONE', _dcc_source('Envelope')), ('normalScale', _dcc_source('Normal Scale'), 'NONE', _dcc_source('Normal Scale')), ('tangentPlaneScale', _dcc_source('Tangent Plane Scale'), 'NONE', _dcc_source('Tangent Plane Scale')), ('scaleEnvelope', _dcc_source('Scale Envelope'), 'NONE', _dcc_source('Scale Envelope'))], 'sculpt': [('envelope', _dcc_source('Envelope'), 'NONE', _dcc_source('Envelope')), ('maximumDisplacement', _dcc_source('Maximum Displacement'), 'NONE', _dcc_source('Maximum Displacement')), ('dropoffDistance', _dcc_source('Dropoff Distance'), 'NONE', _dcc_source('Dropoff Distance'))]}
AE_EXTRA = {'tension': (_dcc_source('Shear Strength'), _dcc_source('Bend Strength'), _dcc_source('Pin Border Vertices')), 'solidify': (_dcc_source('Attachment Mode'), _dcc_source('Stabilization Level'), _dcc_source('Use Border Falloff'), _dcc_source('Border Falloff Blur'), _dcc_source('Scale Mode')), 'sculpt': (_dcc_source('Mode'), _dcc_source('Inside Mode'), _dcc_source('Dropoff Type'), _dcc_source('Sculptor'), _dcc_source('Stretch Origin'))}

def _draw_input(layout, md, socket, label):
    from .. import compat
    key = wire_deformer.ident(md, socket)
    if key is None:
        return
    if compat.GN_INPUT_STRUCT:
        item = compat._gn_input(md, key)
        if item is not None:
            layout.prop(item, 'value', text=_zh(label, 'MWK:operators/deformers_205a.py:917'))
        return
    layout.prop(md, f'["{key}"]', text=_zh(label, 'MWK:operators/deformers_205a.py:919'))

def draw_ae(layout, md):
    """Draw a Tension / Solidify / Sculpt node's Maya attributes in its AE tab; False for other modifiers."""
    kind = kind_of(md)
    if kind is None or deformers.base_of(md) != kind:
        return False
    for (_key, label, _k, socket) in ATTR_ROWS[kind]:
        _draw_input(layout, md, socket, label)
    for socket in AE_EXTRA[kind]:
        _draw_input(layout, md, socket, socket)
    return True
MENU = {'Deform/Tension': ('allset.deformer_tss', {'kind': 'TENSION'}), 'Deform/Solidify': ('allset.deformer_tss', {'kind': 'SOLIDIFY'}), 'Deform/Sculpt': ('allset.deformer_tss', {'kind': 'SCULPT'}), 'Deform/Paint Weights/Tension': ('allset.paint_deformer_weights', {'kind': 'tension'}), 'Deform/Prune Membership/Sculpt': 'allset.prune_sculpt'}

def _windows():
    from .option_windows import F, Window
    from .option_windows_deform import ADVANCED

    def run(kind):

        def go(context, v):
            create(context, kind, v)
            return {'FINISHED'}
        return go
    match = 'allset.deformer_tss'
    return [Window('deform_tension', _dcc_source('Tension Options'), _dcc_source('Create'), (match, {'kind': 'TENSION'}), [F('iterations', _dcc_source('Smoothing iterations:'), 'int', 10, lo=0, hi=100, translation_context='MWK:operators/deformers_205a.py:959'), F(_dcc_source('step'), _dcc_source('Smoothing step:'), 'float', 0.5, lo=0.0, hi=1.0, translation_context='MWK:operators/deformers_205a.py:960'), F('pin_border', '', 'bool', True, text=_zh('Pin border vertices', 'MWK:operators/deformers_205a.py:961'), translation_context='MWK:operators/deformers_205a.py:961'), F('relative', _dcc_source('Relative:'), 'float', 0.0, lo=0.0, hi=1.0, translation_context='MWK:operators/deformers_205a.py:962'), F('inward', _dcc_source('Inward constraint:'), 'float', 0.0, lo=0.0, hi=1.0, heading=_dcc_source('Constraints'), translation_context='MWK:operators/deformers_205a.py:963'), F('outward', _dcc_source('Outward constraint:'), 'float', 0.0, lo=0.0, hi=1.0, translation_context='MWK:operators/deformers_205a.py:964'), F('squash', _dcc_source('Squash constraint:'), 'float', 1.0, lo=0.0, hi=1.0, translation_context='MWK:operators/deformers_205a.py:965'), F('stretch', _dcc_source('Stretch constraint:'), 'float', 1.0, lo=0.0, hi=1.0, translation_context='MWK:operators/deformers_205a.py:966'), F('shear', _dcc_source('Shear strength:'), 'float', 0.0, lo=0.0, hi=1.0, translation_context='MWK:operators/deformers_205a.py:967'), F('bend', _dcc_source('Bend strength:'), 'float', 0.0, lo=0.0, hi=1.0, translation_context='MWK:operators/deformers_205a.py:968')], run('TENSION'), paths=('Deform/Tension',), missing=ADVANCED, translation_context='MWK:operators/deformers_205a.py:958'), Window('deform_solidify', _dcc_source('Solidify Options'), _dcc_source('Create'), (match, {'kind': 'SOLIDIFY'}), [F('attachment', _dcc_source('Attachment mode:'), 'enum', _dcc_source('Borders'), items=(_dcc_source('Borders'), _dcc_source('Full')), translation_context='MWK:operators/deformers_205a.py:972'), F('stabilization', _dcc_source('Stabilization Level:'), 'int', 0, lo=0, hi=100, translation_context='MWK:operators/deformers_205a.py:973'), F('border_falloff', '', 'bool', True, text=_zh('Use border falloff', 'MWK:operators/deformers_205a.py:974'), translation_context='MWK:operators/deformers_205a.py:974'), F('falloff_iterations', _dcc_source('Falloff iterations:'), 'int', 2, lo=0, hi=100, translation_context='MWK:operators/deformers_205a.py:975')], run('SOLIDIFY'), paths=('Deform/Solidify',), missing=ADVANCED, translation_context='MWK:operators/deformers_205a.py:971'), Window('deform_sculpt', _dcc_source('Sculpt Options'), _dcc_source('Create'), (match, {'kind': 'SCULPT'}), [F('mode', _dcc_source('Mode:'), 'enum', _dcc_source('Stretch'), items=SCULPT_MODES, translation_context='MWK:operators/deformers_205a.py:979'), F('inside_mode', _dcc_source('Inside mode:'), 'enum', _dcc_source('Even'), items=INSIDE_MODES, translation_context='MWK:operators/deformers_205a.py:980'), F('max_displacement', _dcc_source('Max displacement:'), 'float', 0.1, lo=0.0, hi=10.0, translation_context='MWK:operators/deformers_205a.py:981'), F('dropoff_type', _dcc_source('Dropoff type:'), 'enum', _dcc_source('Linear'), items=DROPOFF_TYPES, translation_context='MWK:operators/deformers_205a.py:982'), F('dropoff_distance', _dcc_source('Dropoff distance:'), 'float', 1.0, lo=0.0, hi=20.0, translation_context='MWK:operators/deformers_205a.py:983'), F('centered', '', 'bool', True, text=_zh('Center within selection', 'MWK:operators/deformers_205a.py:984'), heading=_dcc_source('Positioning'), translation_context='MWK:operators/deformers_205a.py:984')], run('SCULPT'), paths=('Deform/Sculpt',), missing=(_dcc_source('Group sculptor with locator (the sculptor and its origin stay separate Empties)'), _dcc_source('Use secondary NURBS or polygon object (the sculptor is a sphere)')), translation_context='MWK:operators/deformers_205a.py:978')]
WINDOWS = []

def windows():
    if not WINDOWS:
        WINDOWS.extend(_windows())
        from .option_windows import Window
        from .option_windows_deform import PAINT_FIELDS, PAINT_MISSING, _paint
        WINDOWS.append(Window('paint_weights_tension', _dcc_source('Paint Attributes Tool'), _dcc_source('Paint'), None, PAINT_FIELDS(), _paint('tension'), paths=('Deform/Paint Weights/Tension',), missing=PAINT_MISSING, translation_context='MWK:operators/deformers_205a.py:1000'))
    return WINDOWS

def _on_depsgraph(scene, depsgraph):
    seen = set()
    obs = []
    for upd in depsgraph.updates:
        idb = getattr(upd.id, 'original', upd.id)
        if isinstance(idb, bpy.types.Object):
            obs.append(idb)
        elif isinstance(idb, bpy.types.Mesh):
            obs.extend((o for o in scene.objects if o.data == idb))
    for ob in obs:
        if ob.type != 'MESH' or ob.name in seen:
            continue
        seen.add(ob.name)
        me = ob.data
        if any((kind_of(md) in ('tension', 'solidify') for md in ob.modifiers)) or TOPO_PROP in me or SLOT_COUNT in me.attributes or any((a.name.startswith(REST) for a in me.attributes)):
            try:
                sync(ob)
            except (AttributeError, ReferenceError, RuntimeError):
                pass

def register_handlers():
    deformers.BASES.update(BASES)
    deformers.ATTRS.update({k: _attrs(rows) for (k, rows) in ATTR_ROWS.items()})
    if _on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)

def unregister_handlers():
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    for k in BASES:
        deformers.BASES.pop(k, None)
        deformers.ATTRS.pop(k, None)
