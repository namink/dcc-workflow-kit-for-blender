# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Skeleton > Create IK Spline Handle: a Spline IK constraint ``ikHandleN`` on the chain from the start joint to
the end joint, on a new curve fitted through the chain (``fit_spans`` / ``fit_cubic``) or on an existing curve, run as
a command or as a click tool (start joint, end joint, then the curve). Entry points ``create_spline_ik`` and
``allset.ik_spline_handle``; twist drivers: spline_twist.py, chain lookup: ik_handle.ik_chain; rig_maya re-exports them.
"""

import bpy
from bpy.props import BoolProperty
from mathutils import Matrix, Vector

from .. import results
from . import naming
from .joint_common import _cb

SPLINE_SAMPLES = 200           # polyline samples for the IK Spline curve fit


# --- IK Spline Handle ----------------------------------------------------------------------------

def _resample(points, n):
    seg = [(points[i + 1] - points[i]).length for i in range(len(points) - 1)]
    total = sum(seg) or 1.0
    out, i, acc = [], 0, 0.0
    for k in range(n + 1):
        d = total * k / n
        while i < len(seg) - 1 and acc + seg[i] < d:
            acc += seg[i]
            i += 1
        t = 0.0 if seg[i] == 0 else min(1.0, (d - acc) / seg[i])
        out.append((points[i].lerp(points[i + 1], t), k / n))
    return out


def fit_cubic(points):
    """One-span cubic (4 control points) with its ends on the first / last point and the middle two a least-squares
    fit of the polyline (Maya's IK Spline curve: spans 1, degree 3)."""
    p0, p3 = points[0], points[-1]
    a11 = a12 = a22 = 0.0
    r1, r2 = Vector(), Vector()
    for p, t in _resample(points, SPLINE_SAMPLES):
        b0, b1, b2, b3 = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
        rest = p - p0 * b0 - p3 * b3
        a11 += b1 * b1
        a12 += b1 * b2
        a22 += b2 * b2
        r1 += rest * b1
        r2 += rest * b2
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-12:
        return [p0, p0.lerp(p3, 1 / 3), p0.lerp(p3, 2 / 3), p3]
    return [p0, (r1 * a22 - r2 * a12) / det, (r2 * a11 - r1 * a12) / det, p3]


def fit_spans(points, spans=1):
    """Clamped uniform cubic with ``spans`` spans (spans + 3 CVs), ends on the first / last point, inner CVs a
    least-squares fit of the polyline (Maya IK Spline Handle Tool "Number of spans", default 1; 1 = ``fit_cubic``)."""
    if spans <= 1:
        return fit_cubic(points)
    from . import curves_math as cm
    n = spans + 3
    U = cm.full(cm.clamped_uniform(n, 3))
    p0, pn = points[0], points[-1]
    m = n - 2
    A = [[0.0] * m for _ in range(m)]
    B = [Vector() for _ in range(m)]
    for p, t in _resample(points, SPLINE_SAMPLES):
        row = cm._row(U, 3, n, t * spans, 0)
        rest = p - p0 * row[0] - pn * row[-1]
        for a in range(m):
            if row[a + 1]:
                B[a] += rest * row[a + 1]
                for b in range(m):
                    A[a][b] += row[a + 1] * row[b + 1]
    try:
        inner = [Vector(c) for c in cm.solve(A, [tuple(b) for b in B])]
    except ValueError:
        inner = [p0.lerp(pn, k / (n - 1)) for k in range(1, n - 1)]
    return [p0, *inner, pn]


# Blender's Spline IK walks the curve's evaluated polyline (resolution_u segments per span): at 128 the joints land
# where tests/test_step218_curve_rig.py expects them (64 is a little off), so kit Spline IK curves get
# at least this.
SPLINE_RESOLUTION = 128


def _first_cv_world(curve):
    sp = curve.data.splines[0]
    co = sp.bezier_points[0].co if sp.type == 'BEZIER' else Vector(sp.points[0].co[:3])
    return curve.matrix_world @ co


def _parent_curve(curve, arm, first):
    """Maya Auto parent curve: the curve goes under the start joint's parent (a bone of the skeleton, else the
    skeleton's parent object); a root without parent leaves it in the world."""
    world = curve.matrix_world.copy()
    if first.parent is not None:
        pb = first.parent
        # Blender's bone parent space = the bone's pose matrix moved to its tail
        parent = arm.matrix_world @ pb.matrix @ Matrix.Translation((0.0, pb.bone.length, 0.0))
        curve.parent = arm
        curve.parent_type = 'BONE'
        curve.parent_bone = pb.name
    elif arm.parent is not None:
        parent = arm.parent.matrix_world
        curve.parent = arm.parent
    else:
        return
    curve.matrix_parent_inverse = Matrix.Identity(4)
    curve.matrix_basis = parent.inverted_safe() @ world


def _new_spline_curve(context, cvs):
    data = bpy.data.curves.new("curveShape", 'CURVE')
    data.dimensions = '3D'
    sp = data.splines.new('NURBS')
    sp.points.add(len(cvs) - 1)
    for p, c in zip(sp.points, cvs):
        p.co = (c.x, c.y, c.z, 1.0)
    sp.order_u = 4
    sp.use_endpoint_u = True
    curve = bpy.data.objects.new("curve", data)
    context.view_layer.active_layer_collection.collection.objects.link(curve)
    naming.apply_maya_name(curve, "curve")
    return curve


def create_spline_ik(context, arm, start, end, curve=None, root_on_curve=True, snap_curve=False,
                     parent_curve=True, spans=1):
    """Spline IK constraint ``ikHandleN`` on the bone ending at the end joint (Maya ikSplineSolver).

    ``curve`` None = Auto create curve: ``curveN`` fitted through the chain (degree 3, ``spans`` spans).
    An existing curve: Root on curve moves the root onto
    the curve start and the joints keep their lengths along the curve (Blender Spline IK, Y scale None, no chain
    offset); off keeps the root where it is and the chain takes the curve's shape from there (Chain Offset; Maya
    instead puts the joints after the root on the curve itself, roc0_snc0: up to 1.35
    units apart, Blender's Spline IK has no start point on the curve); Snap curve to root moves the curve so its
    first CV is on the root joint. Returns (constraint, curve) or None."""
    from .skin import ik_chain
    chain = ik_chain(arm, start, end)
    if chain is None:
        return None
    ik_bone, count = chain
    bones, b = [], ik_bone
    for _ in range(count):
        bones.append(b)
        b = b.parent
    bones.reverse()
    mw = arm.matrix_world
    root = mw @ bones[0].head
    if curve is None:
        pts = [mw @ pb.head for pb in bones] + [mw @ ik_bone.tail]
        curve = _new_spline_curve(context, fit_spans(pts, spans))
    elif snap_curve:
        curve.matrix_world = Matrix.Translation(root - _first_cv_world(curve)) @ curve.matrix_world
    if curve.data.resolution_u < SPLINE_RESOLUTION:
        curve.data.resolution_u = SPLINE_RESOLUTION
    if parent_curve:
        context.view_layer.update()
        _parent_curve(curve, arm, bones[0])
    taken = {c.name for o in bpy.data.objects if o.pose for p in o.pose.bones for c in p.constraints}
    taken |= {o.name for o in bpy.data.objects}
    con = ik_bone.constraints.new('SPLINE_IK')
    con.name = f"ikHandle{naming.next_number('ikHandle', taken)}"
    con.target = curve
    con.chain_count = count
    con.y_scale_mode = 'NONE'           # Maya: bone lengths kept (no stretch by default)
    con.xz_scale_mode = 'NONE'
    con.use_curve_radius = False
    con.use_chain_offset = not root_on_curve
    # #166: Maya's handle with Twist / Roll / Twist Type (drivers on the chain's roll)
    from . import spline_twist
    spline_twist.setup(context, arm, ik_bone, con, mw @ ik_bone.tail)
    return con, curve


SPLINE_STATUS = "IK Spline Handle Tool: click the start joint, then the end joint{} (Esc: cancel)"


class ALLSET_OT_ik_spline_handle(bpy.types.Operator):
    """Create a spline IK from the start joint to the end joint: a new curve through the chain, or (Auto create
    curve off) the selected / clicked curve (Maya Skeleton > Create IK Spline Handle)"""
    bl_idname = "allset.ik_spline_handle"
    bl_label = "Create IK Spline Handle"
    bl_options = {'UNDO'}       # a click tool: Maya has no redo panel

    # IK Spline Handle Tool settings, defaults like Maya 2026
    root_on_curve: BoolProperty(name="Root on curve", default=True, options={'SKIP_SAVE'})
    parent_curve: BoolProperty(name="Auto parent curve", default=True, options={'SKIP_SAVE'})
    snap_curve: BoolProperty(name="Snap curve to root", default=False, options={'SKIP_SAVE'})
    create_curve: BoolProperty(name="Auto create curve", default=True, options={'SKIP_SAVE'})
    spans: bpy.props.IntProperty(name="Number of spans", default=1, min=1, max=4, options={'SKIP_SAVE'})
    # Maya Twist type of the tool (default Linear) = the new handle's Twist Type
    twist_type: bpy.props.IntProperty(name="Twist type", default=0, min=0, max=3, options={'SKIP_SAVE'})
    curve: bpy.props.StringProperty(name="Curve", default="", options={'SKIP_SAVE', 'HIDDEN'},
                                    description="Existing curve object (Auto create curve off); empty = the "
                                                "selected curve")

    def _existing_curve(self, context):
        if self.curve:
            ob = bpy.data.objects.get(self.curve)
            return ob if ob is not None and ob.type == 'CURVE' else None
        return next((o for o in context.selected_objects if o.type == 'CURVE'), None)

    def execute(self, context):
        from .skin import selected_pair
        pair = selected_pair(context)
        if pair is None:
            self.report({'WARNING'}, "Select the start joint, then the end joint (pose mode)")
            return {'CANCELLED'}
        return self._make(context, *pair, self._existing_curve(context))

    def _make(self, context, arm, start, end, curve):
        if not self.create_curve and curve is None:
            self.report({'WARNING'}, "Auto create curve is off: select or click a curve")
            return {'CANCELLED'}
        res = create_spline_ik(context, arm, start, end, None if self.create_curve else curve,
                               root_on_curve=self.root_on_curve, snap_curve=self.snap_curve,
                               parent_curve=self.parent_curve, spans=self.spans)
        if res is None:
            self.report({'WARNING'}, "The end joint must be below the start joint in the same skeleton")
            return {'CANCELLED'}
        con, curve = res
        handle = bpy.data.objects.get(con.name)
        if handle is not None and self.twist_type:
            handle["twistType"] = int(self.twist_type)
            handle.update_tag()
        # Maya selects the new ikHandle: the kit handle is the
        # constraint, so its bone becomes the only selected joint
        cb = _cb()
        owner = next(pb for pb in arm.pose.bones if pb.constraints.get(con.name) == con)
        for pb in arm.pose.bones:
            cb.set_bone_selected(pb, pb == owner)
        arm.data.bones.active = owner.bone
        results.result(self, f"Created {con.name} with {curve.name} (Spline IK constraint; Blender has no "
                              "effector node)")
        return {'FINISHED'}

    # --- click tool: start joint, end joint, then (Auto create curve off) the curve ------------------------

    def invoke(self, context, event):
        from .skin import selected_pair
        pair = selected_pair(context)
        curve = self._existing_curve(context)
        if context.window is None or (pair is not None and (self.create_curve or curve is not None)):
            return self.execute(context)
        self._picks = [] if pair is None else list(pair)
        self._swallow = False
        context.workspace.status_text_set(SPLINE_STATUS.format("" if self.create_curve else ", then the curve"))
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _pick_curve(self, context, event):
        from . import select_priority
        from .joints import view_under
        hit = view_under(context.window, event.mouse_x, event.mouse_y)
        if hit is None:
            return None
        area, region = hit
        mouse = (event.mouse_x - region.x, event.mouse_y - region.y)
        with context.temp_override(window=context.window, area=area, region=region):
            found = select_priority.hits(bpy.context, region, region.data, mouse)
        radius = 25 * context.preferences.system.ui_scale
        best = min((h for h in found if h[2] <= radius and bpy.data.objects[h[0]].type == 'CURVE'),
                   key=lambda h: h[2], default=None)
        return bpy.data.objects[best[0]] if best else None

    def modal(self, context, event):
        from .skin import ALLSET_OT_ik_handle
        if event.type == 'ESC' and event.value == 'PRESS':
            context.workspace.status_text_set(None)
            return {'CANCELLED'}
        if event.type != 'LEFTMOUSE':
            return {'PASS_THROUGH'}
        if event.value == 'RELEASE' and self._swallow:
            self._swallow = False
            return {'RUNNING_MODAL'}
        if event.value != 'PRESS' or event.alt or event.ctrl or event.shift:
            return {'PASS_THROUGH'}
        curve = None
        if len(self._picks) < 3:
            hit = ALLSET_OT_ik_handle._pick(self, context, event)
            if hit is None:
                return {'RUNNING_MODAL'} if self._swallow else {'PASS_THROUGH'}
            arm, joint = hit
            if not self._picks or self._picks[0] != arm:
                self._picks = [arm, joint]
            else:
                self._picks.append(joint)
            self._swallow = True
            if len(self._picks) < 3 or not self.create_curve:
                return {'RUNNING_MODAL'}
        else:
            curve = self._pick_curve(context, event)
            if curve is None:
                return {'RUNNING_MODAL'} if self._swallow else {'PASS_THROUGH'}
            self._swallow = True
        context.workspace.status_text_set(None)
        with context.temp_override(window=context.window):
            return self._make(context, *self._picks, curve)
