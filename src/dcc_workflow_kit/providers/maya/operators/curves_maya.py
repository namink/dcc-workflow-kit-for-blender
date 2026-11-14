# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya 2022 curve commands on Blender curves (
maths in ``curves_math``, bpy-free).

Representation: a Maya clamped-uniform NURBS curve = a Blender NURBS spline with
``use_endpoint_u`` and order = degree + 1 (Blender's endpoint knots are the clamped uniform vector); periodic
uniform = a cyclic NURBS spline; degree 1 = a POLY spline; any other cubic (non-uniform knots after Detach / Cut at a
curve point) = an exact Bezier decomposition. Blender Bezier input = a cubic B-spline with triple interior knots.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from mathutils import Vector

from .. import undo_steps
from . import curves_math as cm
from . import naming, units


# --- Blender spline <-> Maya curve -------------------------------------------------------------------

class MCurve:
    """A Maya-style curve: cvs (3-tuples), knots (Maya list), degree, weights (or None), periodic."""

    def __init__(self, cvs, knots, degree, weights=None, periodic=False):
        self.cvs, self.knots, self.degree, self.weights, self.periodic = list(cvs), list(knots), degree, weights, periodic

    def math(self):
        return (self.cvs, self.knots, self.degree, self.weights)


def _periodic_knots(n_unique, degree):
    n = n_unique + degree
    return [float(i - degree + 1) for i in range(n + degree - 1)]


def read_spline(sp, matrix=None):
    """Blender spline -> MCurve (in ``matrix`` space: world when given)."""
    def tx(v):
        v = Vector(v[:3])
        return tuple(matrix @ v) if matrix is not None else tuple(v)

    if sp.type == 'BEZIER':
        pts = list(sp.bezier_points)
        cvs = []
        seq = pts + ([pts[0]] if sp.use_cyclic_u else [])
        for i, (a, b) in enumerate(zip(seq, seq[1:])):
            if i == 0:
                cvs.append(tx(a.co))
            cvs += [tx(a.handle_right), tx(b.handle_left), tx(b.co)]
        segs = (len(cvs) - 1) // 3
        knots = [0.0] * 3 + [float(k) for k in range(1, segs) for _ in range(3)] + [float(segs)] * 3
        return MCurve(cvs, knots, 3)
    pts = [tx(p.co) for p in sp.points]
    weights = [p.co[3] for p in sp.points]
    weights = None if all(abs(w - 1.0) < 1e-9 for w in weights) else weights
    if sp.type == 'POLY':
        return MCurve(pts + ([pts[0]] if sp.use_cyclic_u else []),
                      cm.clamped_uniform(len(pts) + (1 if sp.use_cyclic_u else 0), 1), 1)
    degree = max(1, min(sp.order_u - 1, len(pts) - 1))
    if sp.use_cyclic_u:
        cvs = pts + pts[:degree]
        w = weights + weights[:degree] if weights else None
        return MCurve(cvs, _periodic_knots(len(pts), degree), degree, w, periodic=True)
    if sp.use_endpoint_u:
        return MCurve(pts, cm.clamped_uniform(len(pts), degree), degree, weights)
    # Blender's plain uniform knots (not clamped): Maya's open curve with uniform unclamped knots
    return MCurve(pts, [float(i) for i in range(len(pts) + degree - 1)], degree, weights)


def _norm_knots(knots):
    a, b = knots[0], knots[-1]
    return [(k - a) / (b - a) for k in knots] if b > a else knots


def write_spline(data, c, matrix_inv=None, bezier=False):
    """MCurve -> a new spline in curve ``data`` (points through ``matrix_inv``: world -> object when given;
    ``bezier``: a cubic stays a Bezier spline even when its knots are uniform)."""
    def tx(v):
        v = Vector(v)
        return tuple(matrix_inv @ v) if matrix_inv is not None else tuple(v)

    if c.degree == 1 and not c.weights:
        sp = data.splines.new('POLY')
        cvs = c.cvs[:-1] if c.periodic else c.cvs
        sp.points.add(len(cvs) - 1)
        for p, v in zip(sp.points, cvs):
            p.co = (*tx(v), 1.0)
        sp.use_cyclic_u = c.periodic
        return sp
    if c.periodic or (cm.is_clamped_uniform(c.knots, c.degree) and not (bezier and c.degree == 3 and not c.weights)):
        unique = len(c.cvs) - c.degree if c.periodic else len(c.cvs)
        sp = data.splines.new('NURBS')
        sp.points.add(unique - 1)
        for i, p in enumerate(sp.points):
            w = c.weights[i] if c.weights else 1.0
            p.co = (*tx(c.cvs[i]), w)
        sp.order_u = c.degree + 1
        sp.use_cyclic_u = c.periodic
        sp.use_endpoint_u = not c.periodic
        sp.resolution_u = 12
        return sp
    if c.degree == 3 and not c.weights:
        segs = cm.to_bezier(c.cvs, c.knots, 3)
        sp = data.splines.new('BEZIER')
        sp.bezier_points.add(len(segs))
        bp = sp.bezier_points
        for i, seg in enumerate(segs):
            bp[i].co = tx(seg[0])
            bp[i].handle_right = tx(seg[1])
            bp[i + 1].handle_left = tx(seg[2])
            bp[i + 1].co = tx(seg[3])
        for p in bp:
            p.handle_left_type = p.handle_right_type = 'FREE'
        bp[0].handle_left = tuple(Vector(bp[0].co) * 2 - Vector(bp[0].handle_right))
        bp[-1].handle_right = tuple(Vector(bp[-1].co) * 2 - Vector(bp[-1].handle_left))
        return sp
    # other degrees with non-uniform knots: a dense polyline of the exact curve (rare)
    pts = cm.samples(c.cvs, c.knots, c.degree, 64, c.weights)
    return write_spline(data, MCurve(pts, cm.clamped_uniform(len(pts), 1), 1), matrix_inv)


def _new_curve_object(context, base, curves, matrix=None, select=True):
    data = bpy.data.curves.new(base + "Shape", 'CURVE')
    data.dimensions = '3D'
    inv = matrix.inverted() if matrix is not None else None
    for c in curves:
        write_spline(data, c, inv)
    ob = bpy.data.objects.new(base, data)
    if matrix is not None:
        ob.matrix_world = matrix
    (context.collection or context.scene.collection).objects.link(ob)
    if select:
        for o in context.selected_objects:
            o.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
    return ob


def _replace_splines(ob, curves):
    data = ob.data
    data.splines.clear()
    for c in curves:
        write_spline(data, c)


def _curves_selected(context):
    return [o for o in context.selected_objects if o.type == 'CURVE']


# --- drawing tools' builders (operators/curve_draw.py calls these; points in world, scene units) ------

def _named(ob, base="curve"):
    naming.apply_maya_name(ob, base)
    return ob


def make_cv_curve(context, points, degree=3):
    """Maya CV Curve Tool: the clicked points are the CVs (clamped uniform knots)."""
    cvs, knots, deg = cm.cv_curve([tuple(p) for p in points], degree)
    return _new_curve_object(context, "curve", [MCurve(cvs, knots, deg)])


def make_ep_curve(context, points, degree=3, uniform=True):
    """Maya EP Curve Tool (default Uniform knot spacing): the cubic through the clicks at u = 0 .. n-1, natural ends."""
    cvs, knots, deg = cm.ep_curve([tuple(p) for p in points], degree, uniform)
    return _new_curve_object(context, "curve", [MCurve(cvs, knots, deg)])


def make_arc3(context, p1, p2, p3, sections=8, degree=3):
    cvs, knots, deg = cm.arc3(tuple(p1), tuple(p2), tuple(p3), sections, degree)
    return _new_curve_object(context, "curve", [MCurve(cvs, knots, deg)])


def make_arc2(context, p1, p2, normal=(0.0, 0.0, 1.0), radius=None, toggle=False, sections=8, degree=3):
    """Maya Two Point Circular Arc tool: half circle (radius = chord / 2) about the view normal (ground: +Z)."""
    cvs, knots, deg = cm.arc2(tuple(p1), tuple(p2), tuple(normal), radius, toggle, sections, degree)
    return _new_curve_object(context, "curve", [MCurve(cvs, knots, deg)])


# --- operators -------------------------------------------------------------------------------------------

class _CurveOp:
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'EDIT_CURVE'} and any(o.type == 'CURVE' for o in context.selected_objects)

    def _object_mode(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')


@undo_steps.no_redo_panel
class ALLSET_OT_curve_rebuild(_CurveOp, bpy.types.Operator):
    """Rebuild the selected curves with uniform spans (Maya Curves > Rebuild; default 4 spans, degree 3)"""
    bl_idname = "allset.curve_rebuild"
    bl_label = "Rebuild Curve"

    spans: IntProperty(name="Number of spans", default=4, min=1, max=1000, options={'SKIP_SAVE'})
    degree: EnumProperty(name="Degree", items=[('1', "1 Linear", ""), ('2', "2", ""), ('3', "3 Cubic", ""),
                                               ('5', "5", ""), ('7', "7", "")], default='3', options={'SKIP_SAVE'})

    def execute(self, context):
        self._object_mode(context)
        for ob in _curves_selected(context):
            out = []
            for sp in ob.data.splines:
                c = read_spline(sp)
                if c.periodic:
                    out.append(c)       # periodic rebuild unknown: left as it is
                    continue
                cvs, knots, deg = cm.rebuild(c.cvs, c.knots, c.degree, self.spans, int(self.degree), c.weights)
                out.append(MCurve(cvs, knots, deg))
            _replace_splines(ob, out)
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_curve_attach(_CurveOp, bpy.types.Operator):
    """Join two curves into a new one at their nearest ends (Maya Curves > Attach; default Blend, bias 0.5)"""
    bl_idname = "allset.curve_attach"
    bl_label = "Attach Curves"

    method: EnumProperty(name="Attach method", items=[('CONNECT', "Connect", ""), ('BLEND', "Blend", "")],
                         default='BLEND', options={'SKIP_SAVE'})
    bias: FloatProperty(name="Blend bias", default=0.5, min=0.0, max=1.0, options={'SKIP_SAVE'})
    keep_originals: EnumProperty(name="Keep originals", items=[('ON', "On", ""), ('OFF', "Off", "")], default='ON',
                                 options={'SKIP_SAVE'})

    def execute(self, context):
        self._object_mode(context)
        obs = _curves_selected(context)
        if len(obs) != 2:
            self.report({'WARNING'}, "Select two curves to attach")
            return {'CANCELLED'}
        active = context.view_layer.objects.active
        first = next(o for o in obs if o is not active) if active in obs else obs[0]
        second = obs[1] if first is obs[0] else obs[0]
        a = read_spline(first.data.splines[0], first.matrix_world)
        b = read_spline(second.data.splines[0], second.matrix_world)
        if a.degree != b.degree or a.periodic or b.periodic:
            self.report({'WARNING'}, "Attach needs two open curves of the same degree")
            return {'CANCELLED'}
        cvs, knots = cm.attach((a.cvs, a.knots), (b.cvs, b.knots), a.degree, self.method, self.bias)
        ob = _new_curve_object(context, f"{first.name}attachedCurve", [MCurve(cvs, knots, a.degree)])
        naming.apply_maya_name(ob, f"{first.name}attachedCurve")
        if self.keep_originals == 'OFF':
            for o in (first, second):
                bpy.data.objects.remove(o)
        return {'FINISHED'}


def _greville(c, i):
    p = c.degree
    U = cm.full(c.knots)
    return sum(U[i + 1:i + p + 1]) / p


@undo_steps.no_redo_panel
class ALLSET_OT_curve_detach(_CurveOp, bpy.types.Operator):
    """Split the curve at the edit point nearest each selected CV (Maya Curves > Detach)"""
    bl_idname = "allset.curve_detach"
    bl_label = "Detach Curve"

    def execute(self, context):
        ob = context.edit_object if context.mode == 'EDIT_CURVE' else context.active_object
        if ob is None or ob.type != 'CURVE':
            return {'CANCELLED'}
        picks = []
        for si, sp in enumerate(ob.data.splines):
            pts = sp.points if sp.type != 'BEZIER' else sp.bezier_points
            sel = [i for i, p in enumerate(pts) if (p.select if sp.type != 'BEZIER' else p.select_control_point)]
            if sel:
                picks.append((si, sel))
        self._object_mode(context)
        if not picks:
            self.report({'WARNING'}, "Select curve points to detach at")
            return {'CANCELLED'}
        out, extra = [], []
        for si, sp in enumerate(ob.data.splines):
            c = read_spline(sp)
            sel = dict(picks).get(si)
            if not sel or c.periodic:
                out.append(c)
                continue
            if sp.type == 'BEZIER':
                us = [float(i) for i in sel]
            else:
                inner = sorted(set(c.knots))
                us = [min(inner, key=lambda k: abs(k - _greville(c, i))) for i in sel]
            us = sorted(u for u in set(us) if c.knots[0] < u < c.knots[-1])
            cur = (c.cvs, c.knots)
            pieces = []
            for u in us:
                a, cur = cm.split(cur[0], cur[1], c.degree, u)
                pieces.append(a)
            pieces.append(cur)
            out.append(MCurve(*pieces[0], c.degree))
            extra += [MCurve(*p, c.degree) for p in pieces[1:]]
        _replace_splines(ob, out)
        for i, c in enumerate(extra):
            new = _new_curve_object(context, f"{ob.name}detachedCurve", [c], ob.matrix_world, select=False)
            naming.apply_maya_name(new, f"{ob.name}detachedCurve")
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_curve_cut(_CurveOp, bpy.types.Operator):
    """Cut the selected curves where they cross, keeping all pieces (Maya Curves > Cut)"""
    bl_idname = "allset.curve_cut"
    bl_label = "Cut Curve"

    # Cut Curve Options: Cut "Using last curve" / Keep "Longest
    # segments"; the last curve = the active one (Maya's last selected)
    last_only: BoolProperty(name="Using last curve", default=False, options={'SKIP_SAVE'})
    keep_longest: BoolProperty(name="Longest segments", default=False, options={'SKIP_SAVE'})

    def execute(self, context):
        self._object_mode(context)
        obs = _curves_selected(context)
        if len(obs) < 2:
            self.report({'WARNING'}, "Select two or more crossing curves")
            return {'CANCELLED'}
        active = context.view_layer.objects.active
        if self.last_only and active in obs:
            obs.remove(active)
            obs.append(active)
        world = [read_spline(o.data.splines[0], o.matrix_world) for o in obs]
        res = cm.cut_all([c.math() for c in world], last_only=self.last_only, keep_longest=self.keep_longest)
        cuts = 0
        for ob, c, pieces in zip(obs, world, res):
            if len(pieces) < 2:
                if self.keep_longest and pieces and (abs(pieces[0][1][0] - c.knots[0]) > 1e-9
                                                     or abs(pieces[0][1][-1] - c.knots[-1]) > 1e-9):  # longest kept
                    cuts += 1
                    ob.data.splines.clear()
                    write_spline(ob.data, MCurve(*pieces[0], c.degree), ob.matrix_world.inverted())
                continue
            cuts += len(pieces) - 1
            inv = ob.matrix_world.inverted()
            ob.data.splines.clear()
            write_spline(ob.data, MCurve(*pieces[0], c.degree), inv)
            for p in pieces[1:]:
                new = _new_curve_object(context, f"{ob.name}detachedCurve", [MCurve(*p, c.degree)], ob.matrix_world,
                                        select=False)
                naming.apply_maya_name(new, f"{ob.name}detachedCurve")
        if not cuts:
            self.report({'WARNING'}, "The curves don't cross")
            return {'CANCELLED'}
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_curve_fillet(_CurveOp, bpy.types.Operator):
    """A circular fillet curve between two curves (Maya Curves > Fillet; default radius 1)"""
    bl_idname = "allset.curve_fillet"
    bl_label = "Fillet Curves"

    radius: FloatProperty(name="Radius", default=1.0, min=0.0001, options={'SKIP_SAVE'})

    def execute(self, context):
        self._object_mode(context)
        obs = _curves_selected(context)
        if len(obs) != 2:
            self.report({'WARNING'}, "Select two curves to fillet")
            return {'CANCELLED'}
        a, b = (read_spline(o.data.splines[0], o.matrix_world) for o in obs)
        res = cm.fillet_curves(a.math(), b.math(), self.radius * units.maya_unit(context.scene))
        if res is None:
            self.report({'WARNING'}, "Fillet needs two curves that are not parallel")
            return {'CANCELLED'}
        cvs, knots, weights = res
        ob = _new_curve_object(context, "filletedCurve", [MCurve(cvs, knots, 3, weights)])
        naming.apply_maya_name(ob, "filletedCurve")
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_curve_straighten(_CurveOp, bpy.types.Operator):
    """Lay every CV leg of the selected curves on one line, keeping their lengths (Maya Curves > Straighten)"""
    bl_idname = "allset.curve_straighten"
    bl_label = "Straighten Curve"

    # Straighten Curves Options: default Straightness 1, Preserve length on
    straightness: FloatProperty(name="Straightness", default=1.0, soft_min=0.0, soft_max=2.0, options={'SKIP_SAVE'})
    preserve_length: BoolProperty(name="Preserve length", default=True, options={'SKIP_SAVE'})

    def execute(self, context):
        self._object_mode(context)
        for ob in _curves_selected(context):
            out = []
            for sp in ob.data.splines:
                c = read_spline(sp)
                if not c.periodic and len(c.cvs) >= 2:
                    c = MCurve(cm.straighten(c.cvs, self.straightness, self.preserve_length), c.knots, c.degree,
                               c.weights)
                out.append(c)
            _replace_splines(ob, out)
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_curve_smooth_curves(_CurveOp, bpy.types.Operator):
    """Smooth the CVs of the selected curves, ends kept (Maya Curves > Smooth in the Modify section, nHair > Modify
    Curves > Smooth; default Smooth factor 4)"""
    bl_idname = "allset.curve_smooth_curves"
    bl_label = "Smooth Curves"

    factor: IntProperty(name="Smooth factor", default=4, min=0, soft_min=1, soft_max=100, options={'SKIP_SAVE'})

    def execute(self, context):
        self._object_mode(context)
        for ob in _curves_selected(context):
            out = []
            for sp in ob.data.splines:
                c = read_spline(sp)
                if not c.periodic and len(c.cvs) >= 3:
                    c = MCurve(cm.smooth_cvs(c.cvs, self.factor), c.knots, c.degree, c.weights)
                out.append(c)
            _replace_splines(ob, out)
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_curve_move_seam(_CurveOp, bpy.types.Operator):
    """Move the start of a closed curve to the selected point (Maya Curves > Move Seam)"""
    bl_idname = "allset.curve_move_seam"
    bl_label = "Move Seam"

    def execute(self, context):
        ob = context.edit_object if context.mode == 'EDIT_CURVE' else context.active_object
        if ob is None or ob.type != 'CURVE':
            return {'CANCELLED'}
        done = 0
        if context.mode == 'EDIT_CURVE':
            bpy.ops.object.mode_set(mode='OBJECT')
        for sp in ob.data.splines:
            if not sp.use_cyclic_u or sp.type == 'BEZIER':
                continue
            sel = [i for i, p in enumerate(sp.points) if p.select]
            if not sel:
                continue
            k = sel[0]
            co = [tuple(p.co) for p in sp.points]
            co = co[k:] + co[:k]
            for p, v in zip(sp.points, co):
                p.co = v
            done += 1
        if not done:
            self.report({'WARNING'}, "Select a point on a closed curve")
            return {'CANCELLED'}
        return {'FINISHED'}


def _spline_points(sp):
    """(points, select attribute) of a spline: Bezier control points or NURBS / poly points."""
    if sp.type == 'BEZIER':
        return sp.bezier_points, "select_control_point"
    return sp.points, "select"


def _domain(c):
    """Parameter range of an open curve (Maya knot list): knots[degree - 1] .. knots[-degree]."""
    return c.knots[c.degree - 1], c.knots[len(c.knots) - c.degree]


def point_params(sp, c):
    """The curve parameter each Blender point of ``sp`` stands for: a Bezier / poly point is the curve point
    under it, a NURBS CV the parameter where it pulls most (its Greville abscissa), inside the curve range."""
    a, b = _domain(c)
    if sp.type == 'BEZIER':
        return [float(i) for i in range(len(sp.bezier_points))]
    return [min(b, max(a, _greville(c, i))) for i in range(len(sp.points))]


def knot_targets(c, params, selected, between=False, number=1, set_to=False):
    """Knots to insert, as sorted [(u, times)], for the points ``selected`` (indices into ``params``).

    At selection: a knot at each selected point; a curve end gives none (like Maya, the curve stays as it is); a
    knot that is already full (Bezier / poly points) gives the middle between it and the next point instead (the
    one before at the last point). Increase by: ``number`` more; Set to: up to ``number`` in all. A knot never exceeds the degree.
    Between selections: a knot at each selected point plus ``number`` evenly spaced between neighbouring ones.
    """
    a, b = _domain(c)
    eps = 1e-9
    deg = c.degree

    def mult(u):
        return cm.multiplicity(c.knots, u)

    def open_at(u):
        return a + eps < u < b - eps and mult(u) < deg

    def at_end(u):
        return _is_end(c, u, eps)

    want = {}

    def add(u, times):
        u = round(u, 12)
        times = min(times, deg - mult(u) - want.get(u, 0))
        if times > 0 and a + eps < u < b - eps:
            want[u] = want.get(u, 0) + times

    sel = sorted(set(i for i in selected if 0 <= i < len(params)))
    us = sorted({round(params[i], 12) for i in sel})
    if between and len(us) >= 2:
        for u in us:
            if open_at(u) and not mult(u):
                add(u, 1)
        for u0, u1 in zip(us, us[1:]):
            for k in range(1, number + 1):
                add(u0 + (u1 - u0) * k / (number + 1), 1)
        return sorted(want.items())
    spots = set()
    for i in sel:
        u = params[i]
        if at_end(u):
            continue
        if not open_at(u):
            j = i + 1 if i + 1 < len(params) else i - 1
            if j < 0:
                continue
            u = (u + params[j]) / 2
        spots.add(round(u, 12))
    for u in sorted(spots):
        add(u, max(0, number - mult(u)) if set_to else number)
    return sorted(want.items())


def _is_end(c, u, eps=1e-9):
    a, b = _domain(c)
    return u <= a + eps or u >= b - eps


def apply_knots(c, targets):
    """``c`` with the knots ``targets`` inserted (Boehm insertion: same shape, same parameters)."""
    cvs, knots = c.cvs, c.knots
    for u, times in targets:
        cvs, knots = cm.insert_knot(cvs, knots, c.degree, u, times)
    return MCurve(cvs, knots, c.degree)


def _writable(c):
    return not c.periodic and not c.weights and c.degree in (1, 3)


def _inserted_indices(c, targets, spline_type):
    """Indices of the Blender points at the inserted knots once ``c`` is written: Bezier anchors / poly points at
    the knots, or (a NURBS spline, when the knots came out uniform) the CVs that pull most there."""
    if spline_type == 'NURBS':
        keys = [_greville(c, i) for i in range(len(c.cvs))]
    elif c.degree == 1:
        keys = list(c.knots)
    else:
        keys = sorted(set(c.knots))
    return {min(range(len(keys)), key=lambda k: abs(keys[k] - u)) for u, _t in targets}


def _copy_spline_look(src, dst):
    for attr in ("resolution_u", "material_index", "use_smooth"):
        try:
            setattr(dst, attr, getattr(src, attr))
        except (AttributeError, TypeError):
            pass


class ALLSET_OT_curve_insert_knot(bpy.types.Operator):
    """Insert knots at the selected curve points without changing the curve shape (Maya Curves > Insert Knot)"""
    bl_idname = "allset.curve_insert_knot"
    bl_label = "Insert Knot"
    bl_options = {'REGISTER', 'UNDO'}

    # Insert Knot Options: Insert location At selection / Between selections, Multiplicity Increase by / Set to
    # (default Increase by 1), Keep original off (the curve changes in place)
    location: EnumProperty(name="Insert location", items=(
        ('AT', "At selection", "A knot at each selected curve point"),
        ('BETWEEN', "Between selections", "A knot at each selected curve point and evenly spaced knots between them"),
    ), default='AT')
    mode: EnumProperty(name="Multiplicity", items=(
        ('INCREASE', "Increase by", "Add this many knots at each point"),
        ('SET', "Set to", "Make the knot count at each point this number"),
    ), default='INCREASE')
    number: IntProperty(name="Multiplicity", default=1, min=1, max=100,
                        description="Knots added at each point (Between selections: knots between two points)")
    keep_original: BoolProperty(name="Keep original", default=False,
                                description="Leave the curve as it is and make a new curve with the knots")

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'EDIT_CURVE'} and any(o.type == 'CURVE' for o in context.selected_objects)

    def draw(self, context):
        lay = self.layout
        lay.use_property_split = True
        lay.prop(self, "location", expand=True)
        lay.prop(self, "mode", expand=True)
        lay.prop(self, "number")
        lay.prop(self, "keep_original")

    def execute(self, context):
        if context.mode != 'EDIT_CURVE':
            self.report({'WARNING'}, "Select curve points first (right-click a curve > Control Vertex)")
            return {'CANCELLED'}
        picks = []          # (object, spline index, curve, targets)
        found = skipped = ends = 0
        for ob in context.objects_in_mode:
            if ob.type != 'CURVE':
                continue
            for si, sp in enumerate(ob.data.splines):
                pts, attr = _spline_points(sp)
                sel = [i for i, p in enumerate(pts) if getattr(p, attr)]
                if not sel or len(pts) < 2:
                    continue
                found += 1
                c = read_spline(sp)
                if sp.use_cyclic_u or not _writable(c):
                    skipped += 1
                    continue
                params = point_params(sp, c)
                targets = knot_targets(c, params, sel, self.location == 'BETWEEN', self.number, self.mode == 'SET')
                if targets:
                    picks.append((ob, si, c, targets))
                elif all(_is_end(c, params[i]) for i in sel):
                    ends += 1
        if not found:
            self.report({'WARNING'}, "Select curve points first: one point, or two points to insert between")
            return {'CANCELLED'}
        if not picks:
            if skipped:
                self.report({'WARNING'}, "Insert Knot works on open curves of degree 1 or 3")
            elif ends == found:
                return {'CANCELLED'}       # only curve ends selected: nothing changes, like Maya
            else:
                self.report({'WARNING'}, "No knot to insert there (a curve end, or the knots are already full)")
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')
        by_ob = {}
        for ob, si, c, targets in picks:
            by_ob.setdefault(ob, []).append((si, c, targets))
        new_obs = []
        for ob, items in by_ob.items():
            data = ob.data
            if self.keep_original:
                data = bpy.data.curves.new(ob.data.name + "insertedKnotCurve", 'CURVE')
                data.dimensions = ob.data.dimensions
            for si, c, targets in sorted(items, key=lambda t: -t[0]):
                old = ob.data.splines[si]
                nc = apply_knots(c, targets)
                sp = write_spline(data, nc, bezier=old.type == 'BEZIER')
                _copy_spline_look(old, sp)
                pts, attr = _spline_points(sp)
                for p in pts:
                    setattr(p, attr, False)
                    if sp.type == 'BEZIER':
                        p.select_left_handle = p.select_right_handle = False
                for i in _inserted_indices(nc, targets, sp.type):
                    if i < len(pts):
                        setattr(pts[i], attr, True)
                if not self.keep_original:
                    data.splines.remove(old)
            if self.keep_original:
                new = bpy.data.objects.new(ob.name + "insertedKnotCurve", data)
                new.matrix_world = ob.matrix_world
                for coll in ob.users_collection:
                    coll.objects.link(new)
                naming.apply_maya_name(new, ob.name + "insertedKnotCurve")
                new_obs.append(new)
        if new_obs:
            for o in context.selected_objects:
                o.select_set(False)
            for o in new_obs:
                o.select_set(True)
            context.view_layer.objects.active = new_obs[0]
        bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}


classes = (ALLSET_OT_curve_insert_knot, ALLSET_OT_curve_rebuild, ALLSET_OT_curve_attach, ALLSET_OT_curve_detach, ALLSET_OT_curve_cut,
           ALLSET_OT_curve_fillet, ALLSET_OT_curve_straighten, ALLSET_OT_curve_move_seam,
           ALLSET_OT_curve_smooth_curves)
