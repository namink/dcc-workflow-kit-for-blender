# SPDX-License-Identifier: GPL-3.0-or-later
"""Geometry Nodes groups behind the kit's Tension, Solidify and Sculpt deformers: the node builder ``_B``
(wire_deformer's builder plus the nodes these groups use), ``build_tension`` / ``build_solidify`` /
``build_sculpt``, ``group(kind)`` (reuses the group or rebuilds it when its version differs) and ``kind_of`` (which
of the three a modifier is). deformers_205a describes the models, makes the modifiers and writes the partner table
and rest positions.
"""

import bpy

from . import wire_deformer

VERSION_PROP = "allset_205a_version"
VERSION = 1
GROUPS = {"tension": ".Allset Tension", "solidify": ".Allset Solidify", "sculpt": ".Allset Sculpt"}
SLOT = ".allset_tension_p"          # + k: partner * 8 + flags, -1 = none
SLOT_COUNT = ".allset_tension_n"     # partners per vertex

TENSION_INPUTS = (
    ("Rest", 'NodeSocketVector', None), ("Weight", 'NodeSocketFloat', 1.0), ("Envelope", 'NodeSocketFloat', 1.0),
    ("Smoothing Iterations", 'NodeSocketInt', 10), ("Smoothing Step", 'NodeSocketFloat', 0.5),
    ("Inward Constraint", 'NodeSocketFloat', 0.0), ("Outward Constraint", 'NodeSocketFloat', 0.0),
    ("Squash Constraint", 'NodeSocketFloat', 1.0), ("Stretch Constraint", 'NodeSocketFloat', 1.0),
    ("Shear Strength", 'NodeSocketFloat', 0.0), ("Bend Strength", 'NodeSocketFloat', 0.0),
    ("Relative", 'NodeSocketFloat', 0.0), ("Pin Border Vertices", 'NodeSocketBool', True))
SOLIDIFY_INPUTS = (
    ("Rest", 'NodeSocketVector', None), ("Weight", 'NodeSocketFloat', 1.0), ("Envelope", 'NodeSocketFloat', 1.0),
    ("Normal Scale", 'NodeSocketFloat', 1.0), ("Tangent Plane Scale", 'NodeSocketFloat', 1.0),
    ("Scale Envelope", 'NodeSocketFloat', 1.0), ("Attachment Mode", 'NodeSocketInt', 0),
    ("Stabilization Level", 'NodeSocketInt', 0), ("Use Border Falloff", 'NodeSocketBool', True),
    ("Border Falloff Blur", 'NodeSocketInt', 2), ("Scale Mode", 'NodeSocketInt', 0))
SCULPT_INPUTS = (
    ("Sculptor", 'NodeSocketObject', None), ("Stretch Origin", 'NodeSocketObject', None),
    ("Weight", 'NodeSocketFloat', 1.0), ("Envelope", 'NodeSocketFloat', 1.0), ("Mode", 'NodeSocketInt', 2),
    ("Inside Mode", 'NodeSocketInt', 1), ("Maximum Displacement", 'NodeSocketFloat', 0.1),
    ("Dropoff Distance", 'NodeSocketFloat', 1.0), ("Dropoff Type", 'NodeSocketInt', 1), ("Unit", 'NodeSocketFloat', 1.0))
INPUTS = {"tension": TENSION_INPUTS, "solidify": SOLIDIFY_INPUTS, "sculpt": SCULPT_INPUTS}


# --- node builder -----------------------------------------------------------------------------------------------

class _B(wire_deformer._B):
    """wire_deformer's builder + the nodes these groups need (each helper returns an output socket)."""

    def out(self, n, name=0):
        return n.outputs[name]

    def cmp(self, a, b, eps=0.5):
        """1.0 where |a - b| <= eps (Math Compare)."""
        n = self.node("ShaderNodeMath", operation='COMPARE')
        self._in(n.inputs[0], a)
        self._in(n.inputs[1], b)
        self._in(n.inputs[2], eps)
        return n.outputs[0]

    def mix(self, cond, a, b):
        """a + cond · (b - a) for floats (cond 0 / 1)."""
        return self.math('ADD', a, self.math('MULTIPLY', cond, self.math('SUBTRACT', b, a)))

    def switch(self, kind, cond, false, true):
        n = self.node("GeometryNodeSwitch", input_type=kind)
        self._in(n.inputs["Switch"], cond)
        self._in(n.inputs["False"], false)
        self._in(n.inputs["True"], true)
        return n.outputs[0]

    def combine(self, x, y, z):
        n = self.node("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self._in(n.inputs[i], v)
        return n.outputs[0]

    def separate(self, v):
        n = self.node("ShaderNodeSeparateXYZ")
        self._in(n.inputs[0], v)
        return n.outputs

    def at_index(self, value, index, domain='POINT', data_type='FLOAT_VECTOR'):
        n = self.node("GeometryNodeFieldAtIndex", domain=domain, data_type=data_type)
        self._in(n.inputs["Value"], value)
        self._in(n.inputs["Index"], index)
        return n.outputs[0]

    def on_domain(self, value, domain, data_type='FLOAT'):
        n = self.node("GeometryNodeFieldOnDomain", domain=domain, data_type=data_type)
        self._in(n.inputs[0], value)
        return n.outputs[0]

    def named(self, name, data_type='FLOAT'):
        n = self.node("GeometryNodeInputNamedAttribute", data_type=data_type)
        self._in(n.inputs["Name"], name)
        return n.outputs["Attribute"]

    def store(self, geo, name, value, data_type='FLOAT', domain='POINT'):
        n = self.node("GeometryNodeStoreNamedAttribute", data_type=data_type, domain=domain)
        self.link(geo, n.inputs["Geometry"])
        self._in(n.inputs["Name"], name)
        self._in(n.inputs["Value"], value)
        return n.outputs[0]

    def stat(self, geo, value, selection=None, domain='POINT', data_type='FLOAT'):
        n = self.node("GeometryNodeAttributeStatistic", domain=domain, data_type=data_type)
        self.link(geo, n.inputs["Geometry"])
        self._in(n.inputs["Attribute"], value)
        if selection is not None:
            self._in(n.inputs["Selection"], selection)
        return n.outputs

    def position(self):
        return self.node("GeometryNodeInputPosition").outputs[0]

    def index(self):
        return self.node("GeometryNodeInputIndex").outputs[0]

    def set_position(self, geo, offset=None, position=None):
        n = self.node("GeometryNodeSetPosition")
        self.link(geo, n.inputs["Geometry"])
        if offset is not None:
            self._in(n.inputs["Offset"], offset)
        if position is not None:
            self._in(n.inputs["Position"], position)
        return n.outputs[0]

    def repeat(self, geo, iterations, items=()):
        """(repeat input node, repeat output node): state = geometry (+ ``items`` (type, name, value))."""
        ri = self.node("GeometryNodeRepeatInput")
        ro = self.node("GeometryNodeRepeatOutput")
        ri.pair_with_output(ro)
        for kind, name, _v in items:
            ro.repeat_items.new(kind, name)
        self._in(ri.inputs["Iterations"], iterations)
        self.link(geo, ri.inputs["Geometry"])
        for kind, name, v in items:
            self._in(ri.inputs[name], v)
        return ri, ro

    def vlen(self, v):
        return self.vmath('LENGTH', v, out="Value")

    def dot(self, a, b):
        return self.vmath('DOT_PRODUCT', a, b, out="Value")


def _new_group(name, inputs):
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    ng[VERSION_PROP] = VERSION
    ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    for sname, stype, default in inputs:
        s = ng.interface.new_socket(sname, in_out='INPUT', socket_type=stype)
        if default is not None:
            s.default_value = default
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    b = _B(ng)
    gin, gout = b.node("NodeGroupInput"), b.node("NodeGroupOutput")
    return ng, b, gin.outputs, gout


def _maya_normal(b):
    """Maya's vertex normal (tension_model.normals): normalised sum over the vertex's corners of
    cross(P[f[k+h]] - p, P[f[k-h]] - p), h = max(1, m // 2 - 1) for an m-gon; a point field of the current geometry."""
    corner = b.index()
    foc = b.node("GeometryNodeFaceOfCorner")
    b.link(corner, foc.inputs["Corner Index"])
    cof = b.node("GeometryNodeCornersOfFace")
    b.link(foc.outputs["Face Index"], cof.inputs["Face Index"])
    m = cof.outputs["Total"]
    h = b.math('MAXIMUM', 1.0, b.math('SUBTRACT', b.math('FLOOR', b.math('DIVIDE', m, 2.0)), 1.0))
    sides = []
    for sign in (1.0, -1.0):
        off = b.node("GeometryNodeOffsetCornerInFace")
        b.link(corner, off.inputs["Corner Index"])
        b._in(off.inputs["Offset"], b.math('MULTIPLY', h, sign))
        sides.append(b.at_index(b.position(), off.outputs[0], domain='CORNER'))
    p = b.position()
    c = b.vmath('CROSS_PRODUCT', b.vmath('SUBTRACT', sides[0], p), b.vmath('SUBTRACT', sides[1], p))
    return b.vmath('NORMALIZE', b.on_domain(c, 'CORNER', 'FLOAT_VECTOR'))


def _slot(b, I, k):
    """(include 0/1, strength, partner index) of partner slot ``k`` (single int value) of each point."""
    vs = b.node("FunctionNodeValueToString")
    b._in(vs.inputs["Value"], k)
    b._in(vs.inputs["Decimals"], 0)
    name = b.node("FunctionNodeReplaceString")       # "<SLOT>#" with # = k (no link-order question)
    name.inputs["String"].default_value = SLOT + "#"
    name.inputs["Find"].default_value = "#"
    b.link(vs.outputs[0], name.inputs["Replace"])
    code = b.named(name.outputs[0], 'INT')
    valid = b.math('GREATER_THAN', code, -0.5)
    j = b.math('FLOOR', b.math('DIVIDE', code, 8.0))
    fl = b.math('SUBTRACT', code, b.math('MULTIPLY', j, 8.0))
    edge = b.cmp(fl, 1.0, 0.25)
    diag = b.math('GREATER_THAN', b.math('MODULO', fl, 4.0), 1.5)
    bend = b.math('GREATER_THAN', fl, 3.5)
    extra = b.math('MAXIMUM', b.math('MULTIPLY', diag, I["Shear Strength"]),
                   b.math('MULTIPLY', bend, I["Bend Strength"]))
    strength = b.mix(edge, extra, 1.0)
    inc = b.math('MULTIPLY', valid, b.math('GREATER_THAN', strength, 0.0))
    return inc, strength, j


def build_tension():
    """Maya tension: ``Smoothing Iterations`` Jacobi passes on the input, then
    out = input + envelope · weight · (P - input)."""
    ng, b, I, gout = _new_group(GROUPS["tension"], TENSION_INPUTS)
    g0 = I["Geometry"]
    # pinned = Pin Border Vertices and the point is on an edge with one face
    fc = b.node("GeometryNodeInputMeshEdgeNeighbors").outputs["Face Count"]
    border = b.math('GREATER_THAN', b.on_domain(b.cmp(fc, 1.0, 0.25), 'EDGE'), 0.0)
    free = b.math('SUBTRACT', 1.0, b.math('MULTIPLY', border, I["Pin Border Vertices"]))
    slots = b.stat(g0, b.named(SLOT_COUNT, 'INT'))["Max"]

    ri, ro = b.repeat(g0, I["Smoothing Iterations"])
    g = ri.outputs["Geometry"]
    # pass 1: Σ|P_i - P_j|, Σ|R_i - R_j| over the partners (Relative's s_i)
    g1 = b.store(b.store(g, ".allset_t_sl", 0.0), ".allset_t_sr", 0.0)
    r1, o1 = b.repeat(g1, slots)
    inc, _s, j = _slot(b, I, r1.outputs["Iteration"])
    p = b.position()
    L = b.vlen(b.vmath('SUBTRACT', p, b.at_index(b.position(), j)))
    L0 = b.vlen(b.vmath('SUBTRACT', I["Rest"], b.at_index(I["Rest"], j)))
    acc = b.store(r1.outputs["Geometry"], ".allset_t_sl",
                  b.math('ADD', b.named(".allset_t_sl"), b.math('MULTIPLY', inc, L)))
    acc = b.store(acc, ".allset_t_sr", b.math('ADD', b.named(".allset_t_sr"), b.math('MULTIPLY', inc, L0)))
    b.link(acc, o1.inputs["Geometry"])
    g2 = o1.outputs["Geometry"]
    s_i = b.math('DIVIDE', b.named(".allset_t_sl"), b.named(".allset_t_sr"))
    k_i = b.math('ADD', 1.0, b.math('MULTIPLY', I["Relative"], b.math('SUBTRACT', s_i, 1.0)))
    g2 = b.store(g2, ".allset_t_k", k_i)
    # pass 2: targets t_ij and their mean
    g2 = b.store(b.store(g2, ".allset_t_sum", (0.0, 0.0, 0.0), 'FLOAT_VECTOR'), ".allset_t_cnt", 0.0)
    r2, o2 = b.repeat(g2, slots)
    inc, strength, j = _slot(b, I, r2.outputs["Iteration"])
    p = b.position()
    pj = b.at_index(b.position(), j)
    d = b.vmath('SUBTRACT', p, pj)
    L = b.vlen(d)
    L0 = b.math('MULTIPLY', b.vlen(b.vmath('SUBTRACT', I["Rest"], b.at_index(I["Rest"], j))), b.named(".allset_t_k"))
    c = b.mix(b.math('LESS_THAN', L, L0), I["Stretch Constraint"], I["Squash Constraint"])
    lt = b.math('ADD', L, b.math('MULTIPLY', b.math('MULTIPLY', c, strength), b.math('SUBTRACT', L0, L)))
    t = b.vmath('ADD', pj, b.vmath('SCALE', d, scale=b.math('DIVIDE', lt, L)))      # Math DIVIDE by 0 = 0
    acc = b.store(r2.outputs["Geometry"], ".allset_t_sum",
                  b.vmath('ADD', b.named(".allset_t_sum", 'FLOAT_VECTOR'), b.vmath('SCALE', t, scale=inc)),
                  'FLOAT_VECTOR')
    acc = b.store(acc, ".allset_t_cnt", b.math('ADD', b.named(".allset_t_cnt"), inc))
    b.link(acc, o2.inputs["Geometry"])
    g3 = o2.outputs["Geometry"]
    cnt = b.named(".allset_t_cnt")
    p = b.position()
    mean = b.vmath('SCALE', b.named(".allset_t_sum", 'FLOAT_VECTOR'), scale=b.math('DIVIDE', 1.0, cnt))
    has = b.math('GREATER_THAN', cnt, 0.0)
    delta = b.vmath('SCALE', b.vmath('SUBTRACT', mean, p), scale=b.math('MULTIPLY', I["Smoothing Step"], has))
    n = _maya_normal(b)
    dn = b.dot(delta, n)
    corr = b.math('ADD', b.math('MULTIPLY', b.math('MINIMUM', dn, 0.0), I["Inward Constraint"]),
                  b.math('MULTIPLY', b.math('MAXIMUM', dn, 0.0), I["Outward Constraint"]))
    delta = b.vmath('SUBTRACT', delta, b.vmath('SCALE', n, scale=corr))
    g4 = b.set_position(g3, offset=b.vmath('SCALE', delta, scale=free))
    b.link(g4, ro.inputs["Geometry"])
    final = ro.outputs["Geometry"]

    pf = b.node("GeometryNodeSampleIndex", data_type='FLOAT_VECTOR', domain='POINT')
    b.link(final, pf.inputs["Geometry"])
    b.link(b.position(), pf.inputs["Value"])
    b.link(b.index(), pf.inputs["Index"])
    w = b.math('MULTIPLY', I["Envelope"], I["Weight"])
    out = b.set_position(g0, offset=b.vmath('SCALE', b.vmath('SUBTRACT', pf.outputs[0], b.position()), scale=w))
    b.link(out, gout.inputs[0])
    return ng


def build_sculpt():
    """Maya sculpt (the kit's sculpt model)."""
    ng, b, I, gout = _new_group(GROUPS["sculpt"], SCULPT_INPUTS)
    info = b.node("GeometryNodeObjectInfo", transform_space='RELATIVE')
    b.link(I["Sculptor"], info.inputs["Object"])
    M = info.outputs["Transform"]
    inv = b.node("FunctionNodeInvertMatrix")
    b.link(M, inv.inputs["Matrix"])
    Minv = inv.outputs["Matrix"]
    oinfo = b.node("GeometryNodeObjectInfo", transform_space='RELATIVE')
    b.link(I["Stretch Origin"], oinfo.inputs["Object"])

    def tp(v, m):
        n = b.node("FunctionNodeTransformPoint")
        b._in(n.inputs["Vector"], v)
        b.link(m, n.inputs["Transform"])
        return n.outputs[0]

    def td(v, m):
        n = b.node("FunctionNodeTransformDirection")
        b._in(n.inputs["Direction"], v)
        b.link(m, n.inputs["Transform"])
        return n.outputs[0]

    md_len = b.math('MULTIPLY', I["Maximum Displacement"], I["Unit"])
    dd = b.math('MULTIPLY', I["Dropoff Distance"], I["Unit"])
    linear = b.cmp(I["Dropoff Type"], 1.0, 0.25)
    p = b.position()
    q = tp(p, Minv)
    rq = b.vlen(q)
    inside = b.math('LESS_THAN', rq, 1.0)
    # stretch (origin = the stretch origin) / flip (origin = the sculptor centre): rays from the origin
    centre = tp((0.0, 0.0, 0.0), M)
    src = b.switch('VECTOR', b.cmp(I["Mode"], 2.0, 0.25), centre, oinfo.outputs["Location"])
    sq = tp(src, Minv)
    dvec = b.vmath('SUBTRACT', q, sq)
    tiny = b.math('LESS_THAN', b.vlen(dvec), 1e-12)
    fallback = b.switch('VECTOR', b.math('GREATER_THAN', b.vlen(sq), 1e-12), (1.0, 0.0, 0.0),
                        b.vmath('SCALE', sq, scale=-1.0))
    dvec = b.switch('VECTOR', tiny, dvec, fallback)
    dl = b.vmath('NORMALIZE', dvec)
    bb = b.dot(sq, dl)
    cc = b.math('SUBTRACT', b.dot(sq, sq), 1.0)
    t = b.math('ADD', b.math('MULTIPLY', bb, -1.0),
               b.math('SQRT', b.math('MAXIMUM', b.math('SUBTRACT', b.math('MULTIPLY', bb, bb), cc), 0.0)))
    s = tp(b.vmath('ADD', sq, b.vmath('SCALE', dl, scale=t)), M)
    dw = b.vmath('NORMALIZE', td(dl, M))
    dist = b.math('MULTIPLY', b.math('SUBTRACT', rq, 1.0),
                  b.vlen(td(b.vmath('SCALE', q, scale=b.math('DIVIDE', 1.0, rq)), M)))
    w_lin = b.math('MAXIMUM', 0.0, b.math('SUBTRACT', 1.0, b.math('DIVIDE', dist, dd)))
    w_none = b.math('SUBTRACT', 1.0, b.math('GREATER_THAN', dist, dd))
    w = b.mix(linear, w_none, w_lin)
    np_in = b.vmath('ADD', s, b.vmath('SCALE', dw, scale=md_len))
    np_out = b.vmath('ADD', p, b.vmath('SCALE', dw, scale=b.math('MULTIPLY', md_len, w)))
    np_s = b.switch('VECTOR', inside, np_out, np_in)
    # project: towards the radial surface point by Maximum Displacement (a fraction)
    nq = b.switch('VECTOR', b.math('GREATER_THAN', rq, 0.0), (1.0, 0.0, 0.0),
                  b.vmath('SCALE', q, scale=b.math('DIVIDE', 1.0, rq)))
    sw = tp(nq, M)
    distp = b.vlen(b.vmath('SUBTRACT', p, sw))
    skip = b.math('MULTIPLY', b.math('MULTIPLY', b.math('SUBTRACT', 1.0, inside), b.math('GREATER_THAN', distp, dd)),
                  linear)
    np_p = b.vmath('ADD', p, b.vmath('SCALE', b.vmath('SUBTRACT', sw, p),
                                     scale=b.math('MULTIPLY', I["Maximum Displacement"], b.math('SUBTRACT', 1.0, skip))))
    target = b.switch('VECTOR', b.cmp(I["Mode"], 1.0, 0.25), np_s, np_p)
    wt = b.math('MULTIPLY', I["Envelope"], I["Weight"])
    out = b.set_position(I["Geometry"], offset=b.vmath('SCALE', b.vmath('SUBTRACT', target, p), scale=wt))
    b.link(out, gout.inputs[0])
    return ng


def build_solidify():
    """Maya solidify (rule — see the module doc)."""
    ng, b, I, gout = _new_group(GROUPS["solidify"], SOLIDIFY_INPUTS)
    g0 = I["Geometry"]
    mem = b.math('GREATER_THAN', I["Weight"], 0.0)
    # region border: member points next to a face that is not wholly member
    face_in = b.math('GREATER_THAN', b.on_domain(mem, 'POINT'), 0.999)
    out_faces = b.on_domain(b.math('SUBTRACT', 1.0, face_in), 'FACE')
    border = b.math('MULTIPLY', mem, b.math('GREATER_THAN', out_faces, 0.001))
    has_border = b.math('GREATER_THAN', b.stat(g0, border)["Max"], 0.5)
    w0 = b.math('MULTIPLY', mem, b.math('SUBTRACT', 1.0, border))
    blur = b.node("GeometryNodeBlurAttribute", data_type='FLOAT')
    b._in(blur.inputs["Value"], w0)
    b._in(blur.inputs["Iterations"], I["Border Falloff Blur"])
    w_fall = b.math('MULTIPLY', blur.outputs[0], w0)
    w = b.switch('FLOAT', I["Use Border Falloff"], mem, w_fall)
    full = b.cmp(I["Attachment Mode"], 1.0, 0.25)
    w = b.math('MULTIPLY', w, b.math('MAXIMUM', full, has_border))      # Borders without a border: nothing moves
    w = b.math('MULTIPLY', w, b.math('MULTIPLY', I["Weight"], I["Envelope"]))

    # least-squares rotation of the rest region onto the input (polar factor of Σ dp drᵀ)
    cr = b.stat(g0, I["Rest"], mem, data_type='FLOAT_VECTOR')["Mean"]
    cp = b.stat(g0, b.position(), mem, data_type='FLOAT_VECTOR')["Mean"]
    dr = b.vmath('SUBTRACT', I["Rest"], cr)
    dp = b.vmath('SUBTRACT', b.position(), cp)
    rest_geo = b.set_position(g0, position=I["Rest"])
    n_r = b.vmath('NORMALIZE', b.stat(rest_geo, b.node("GeometryNodeInputNormal").outputs[0], mem,
                                      data_type='FLOAT_VECTOR')["Sum"])
    n_p = b.vmath('NORMALIZE', b.stat(g0, b.node("GeometryNodeInputNormal").outputs[0], mem,
                                      data_type='FLOAT_VECTOR')["Sum"])
    sc = b.stat(g0, b.math('MULTIPLY', b.vlen(dr), b.vlen(dp)), mem)["Sum"]
    drs = b.separate(dr)
    nrs = b.separate(n_r)
    cols = []
    for k in range(3):
        col = b.stat(g0, b.vmath('SCALE', dp, scale=drs[k]), mem, data_type='FLOAT_VECTOR')["Sum"]
        cols.append(b.vmath('ADD', col, b.vmath('SCALE', n_p, scale=b.math('MULTIPLY', sc, nrs[k]))))
    fro = b.math('SQRT', b.math('DIVIDE', b.math('ADD', b.math('ADD', b.dot(cols[0], cols[0]), b.dot(cols[1], cols[1])),
                                                 b.dot(cols[2], cols[2])), 3.0))
    inv_f = b.math('DIVIDE', 1.0, fro)
    cm = b.node("FunctionNodeCombineMatrix")
    for k in range(3):
        comp = b.separate(b.vmath('SCALE', cols[k], scale=inv_f))
        for r in range(3):
            b._in(cm.inputs[k * 4 + r], comp[r])
        cm.inputs[k * 4 + 3].default_value = 0.0
    for r in range(3):
        cm.inputs[12 + r].default_value = 0.0
    cm.inputs[15].default_value = 1.0
    ri = b.node("GeometryNodeRepeatInput")
    ro = b.node("GeometryNodeRepeatOutput")
    ri.pair_with_output(ro)
    ro.repeat_items.new('MATRIX', "X")
    ri.inputs["Iterations"].default_value = 16
    b.link(g0, ri.inputs["Geometry"])
    b.link(cm.outputs[0], ri.inputs["X"])
    b.link(ri.outputs["Geometry"], ro.inputs["Geometry"])
    x = ri.outputs["X"]
    xi = b.node("FunctionNodeInvertMatrix")
    b.link(x, xi.inputs["Matrix"])
    xt = b.node("FunctionNodeTransposeMatrix")
    b.link(xi.outputs["Matrix"], xt.inputs["Matrix"])
    sa = b.node("FunctionNodeSeparateMatrix")
    b.link(x, sa.inputs["Matrix"])
    sb = b.node("FunctionNodeSeparateMatrix")
    b.link(xt.outputs["Matrix"], sb.inputs["Matrix"])
    nx = b.node("FunctionNodeCombineMatrix")
    for i in range(16):
        if i % 4 == 3 or i >= 12:
            nx.inputs[i].default_value = 1.0 if i == 15 else 0.0
            continue
        b.link(b.math('MULTIPLY', b.math('ADD', sa.outputs[i], sb.outputs[i]), 0.5), nx.inputs[i])
    b.link(nx.outputs[0], ro.inputs["X"])
    sep = b.node("FunctionNodeSeparateTransform")
    b.link(ro.outputs["X"], sep.inputs["Transform"])
    aa = b.node("FunctionNodeRotationToAxisAngle")
    b.link(sep.outputs["Rotation"], aa.inputs["Rotation"])
    ang = b.math('DIVIDE', aa.outputs["Angle"], b.math('ADD', 1.0, b.math('MULTIPLY', I["Stabilization Level"], 0.5)))
    rot = b.node("FunctionNodeAxisAngleToRotation")
    b.link(aa.outputs["Axis"], rot.inputs["Axis"])
    b.link(ang, rot.inputs["Angle"])

    def turn(v):
        n = b.node("FunctionNodeRotateVector")
        b._in(n.inputs["Vector"], v)
        b.link(rot.outputs["Rotation"], n.inputs["Rotation"])
        return n.outputs[0]
    o = turn(dr)
    # Scale Mode Edge / Edge Global: uniform scale by the region's edge-length ratio
    ev = b.node("GeometryNodeInputMeshEdgeVertices")
    v1, v2 = ev.outputs["Vertex Index 1"], ev.outputs["Vertex Index 2"]
    e_mem = b.math('MULTIPLY', b.at_index(mem, v1, data_type='FLOAT'), b.at_index(mem, v2, data_type='FLOAT'))
    e_in = b.vlen(b.vmath('SUBTRACT', ev.outputs["Position 1"], ev.outputs["Position 2"]))
    e_rest = b.vlen(b.vmath('SUBTRACT', b.at_index(I["Rest"], v1), b.at_index(I["Rest"], v2)))
    ratio = b.math('DIVIDE', b.stat(g0, e_in, e_mem, domain='EDGE')["Sum"],
                   b.stat(g0, e_rest, e_mem, domain='EDGE')["Sum"])
    s = b.math('ADD', 1.0, b.math('MULTIPLY', I["Scale Envelope"], b.math('SUBTRACT', ratio, 1.0)))
    nn = b.vmath('NORMALIZE', turn(n_r))
    on = b.vmath('SCALE', nn, scale=b.dot(o, nn))
    ot = b.vmath('SUBTRACT', o, on)
    scaled = b.vmath('SCALE', b.vmath('ADD', b.vmath('SCALE', ot, scale=I["Tangent Plane Scale"]),
                                      b.vmath('SCALE', on, scale=I["Normal Scale"])), scale=s)
    o = b.switch('VECTOR', b.math('GREATER_THAN', I["Scale Mode"], 0.5), o, scaled)
    target = b.vmath('ADD', cp, o)
    out = b.set_position(g0, offset=b.vmath('SCALE', b.vmath('SUBTRACT', target, b.position()), scale=w))
    b.link(out, gout.inputs[0])
    return ng


BUILDERS = {"tension": build_tension, "solidify": build_solidify, "sculpt": build_sculpt}


def group(kind):
    ng = bpy.data.node_groups.get(GROUPS[kind])
    if ng is not None and ng.bl_idname == 'GeometryNodeTree' and ng.get(VERSION_PROP) == VERSION:
        return ng
    if ng is not None:
        ng.name = GROUPS[kind] + ".old"
    return BUILDERS[kind]()


def kind_of(md):
    """"tension" / "solidify" / "sculpt" for a kit modifier of this module, else None."""
    if md.type != 'NODES' or md.node_group is None:
        return None
    for kind, name in GROUPS.items():
        if md.node_group.name.startswith(name):
            return kind
    return None
