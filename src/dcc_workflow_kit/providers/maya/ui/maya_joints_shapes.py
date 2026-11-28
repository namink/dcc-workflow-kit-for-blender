# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya joint shapes one joint at a time: colours, circle segments, Radius default and display types; the ``Joint``
record and its drawn radius / frame; selection and colours in Maya's terms; wire lines of spheres, bone pyramids,
B-Bone / Envelope shapes and custom shapes. Main entry points: ``selection``, ``colours``, ``joint_segments``,
``drawn_radius``. Related: ``maya_joints`` (``skeleton``), ``maya_joints_arrays``.
"""

import math

import bpy
from mathutils import Matrix, Quaternion, Vector


UNSELECTED = (0x26 / 255, 0.0, 0x43 / 255)
SELECTED = (1.0, 1.0, 1.0)
LEAD = (0x43 / 255, 1.0, 0xa3 / 255)
AXIS_COLORS = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
SEGMENTS = 32
MAYA_RADIUS = 1.0                     # Maya joint Radius default
STICK_TYPES = {'STICK', 'WIRE'}       # the skeleton's Blender display type: one line per bone, no spheres
SHAPE_TYPES = {'BBONE', 'ENVELOPE'}   # display types drawn as wire versions of Blender's bone shapes

_HIDDEN = "HIDDEN"                    # ui/layer_joints.HIDDEN
_COS = [math.cos(2.0 * math.pi * i / SEGMENTS) for i in range(SEGMENTS)]
_SIN = [math.sin(2.0 * math.pi * i / SEGMENTS) for i in range(SEGMENTS)]


def drawn_radius(bone, scene, arm_scale=1.0, scale=None):
    """World radius of the drawn joint sphere: 0.5 x Radius x Joint Size, in centimetres (``units.radius_unit``).
    ``scale``: (Joint Size, radius unit) read once for a whole skeleton (``_radius_scale``)."""
    from ..operators import joints
    r = float(bone.get(joints.RADIUS, MAYA_RADIUS))
    size, unit = scale if scale is not None else _radius_scale(scene)
    return 0.5 * r * size * unit * arm_scale


def _radius_scale(scene):
    """(Joint Size, Blender units per Radius unit) of ``scene``."""
    from ..operators import joint_display, units
    return joint_display.joint_size(scene), units.radius_unit(scene)


def _maya_q(bone):
    from ..operators import joints
    q = bone.get(joints.MAYA_FRAME)
    return Quaternion(q).to_matrix() if q is not None else None


class Joint:
    __slots__ = ("name", "parent", "centre", "frame", "radius", "shape", "children", "state")

    def __init__(self, name, parent, centre, frame, radius, shape=None, state=None):
        self.name, self.parent, self.centre, self.frame, self.radius = name, parent, centre, frame, radius
        self.shape = shape          # (custom shape object, world matrix) or None
        self.children = []
        self.state = state          # ui/layer_joints: HIDDEN (not drawn) / TEMPLATE / REFERENCE, None = normal


def _coll_hidden(bone):
    return bool(bone.collections) and not any(c.is_visible_effectively for c in bone.collections)


def _shown(ob, names=None, index=None):
    """Bool per pose bone of ``ob`` (pose bone order): not hidden by its own flag (``compat.bone_hidden``) or by its
    bone collections (``_coll_hidden``), read for the whole skeleton at once. ``names`` / ``index``: the pose bones'
    names and {name: row} when the caller has them."""
    import numpy as np
    pbs = ob.pose.bones
    hide = np.zeros(len(pbs), bool)
    pbs.foreach_get("hide", hide)
    colls = ob.data.collections_all
    if len(colls):
        if index is None:
            index = {name: i for i, name in enumerate(names if names is not None else pbs.keys())}
        member, visible = np.zeros(len(pbs), bool), np.zeros(len(pbs), bool)
        for c in colls:
            rows = [index[n] for n in c.bones.keys() if n in index]
            if rows:
                member[rows] = True
                if c.is_visible_effectively:
                    visible[rows] = True
        hide |= member & ~visible
    return ~hide


def _shape_matrix(pb):
    """Armature-space matrix Blender draws ``pb``'s custom shape with."""
    src = pb.custom_shape_transform or pb
    scale = Vector(pb.custom_shape_scale_xyz)
    if pb.use_custom_shape_bone_size:
        scale = scale * pb.bone.length
    return (src.matrix @ Matrix.Translation(pb.custom_shape_translation)
            @ pb.custom_shape_rotation_euler.to_matrix().to_4x4() @ Matrix.Diagonal(scale.to_4d()))


def selection(ob, joints_):
    """(selected joint names, lead name or None) of ``ob`` in Maya's terms."""
    from ..operators import joint_preview
    from ..operators.joint_selection import _edit_selected
    from .channel_box import bone_selected
    if joint_preview.running() and joint_preview.STATE.get("ob") == ob.name:
        cur = joint_preview.STATE.get("current")
        return ({cur} if cur else set()), cur          # the Joint Tool: the newest joint is the selection
    if ob.mode == 'EDIT':
        sel = {eb.name for eb in ob.data.edit_bones if eb.name in joints_ and _edit_selected(eb)}
        act = ob.data.edit_bones.active
    elif ob.mode == 'POSE':
        sel = {pb.name for pb in ob.pose.bones if pb.name in joints_ and bone_selected(pb)}
        act = ob.data.bones.active
    else:
        if not ob.select_get():
            return set(), None
        roots = [n for n, j in joints_.items() if j.parent is None]
        lead = roots[0] if roots and bpy.context.view_layer.objects.active == ob else None
        return set(roots), lead
    lead = act.name if act is not None and act.name in sel else None
    return sel, lead


def colours(joints_, sel, lead):
    """{name: colour}: own selection first, else its Template / Reference layer colour, else the nearest selected
    joint above it, else unselected."""
    from .layer_joints import COLOURS
    out = {}

    def colour(name):
        if name in out:
            return out[name]
        if name == lead:
            c = LEAD
        elif name in sel:
            c = SELECTED
        elif joints_[name].state in COLOURS:
            c = COLOURS[joints_[name].state]
        else:
            p = joints_[name].parent
            c = colour(p) if p in joints_ else UNSELECTED
        out[name] = c
        return c

    for n in joints_:
        colour(n)
    return out


def sphere_lines(c, frame, r):
    """Line segment end points of the three great circles."""
    x, y, z = frame.col[0], frame.col[1], frame.col[2]
    pts = []
    for a, b in ((x, y), (y, z), (x, z)):
        ring = [c + (a * _COS[i] + b * _SIN[i]) * r for i in range(SEGMENTS)]
        for i in range(SEGMENTS):
            pts += (ring[i], ring[(i + 1) % SEGMENTS])
    return pts


def bone_lines(parent, child):
    """The eight edges of the bone pyramid from ``parent`` to ``child`` (Joint), or [] when they overlap."""
    d = child.centre - parent.centre
    length = d.length
    if length <= parent.radius + child.radius or length < 1e-9:
        return []
    u = d / length
    base = parent.centre + u * parent.radius
    apex = child.centre - u * child.radius
    a = parent.frame.col[1] - u * parent.frame.col[1].dot(u)
    if a.length < 1e-6:
        a = parent.frame.col[2] - u * parent.frame.col[2].dot(u)
    a.normalize()
    b = u.cross(a)
    r = parent.radius
    corners = [base + a * r, base + b * r, base - a * r, base - b * r]
    pts = []
    for i in range(4):
        pts += (corners[i], corners[(i + 1) % 4], corners[i], apex)
    return pts


def _box_lines(rings):
    """Edges of a tube through ``rings`` (each four corners): the rings and the lines joining their corners."""
    pts = []
    for k, ring in enumerate(rings):
        for i in range(4):
            pts += (ring[i], ring[(i + 1) % 4])
            if k:
                pts += (rings[k - 1][i], ring[i])
    return pts


def bbone_lines(ob, bone):
    """World edges of Blender's B-Bone box of ``bone`` (pose bone, or edit bone in Edit Mode): ``bbone_x`` /
    ``bbone_z`` half sizes, one box per segment along the bent bone in Object / Pose Mode."""
    mw = ob.matrix_world
    data = bone.bone if isinstance(bone, bpy.types.PoseBone) else bone
    x, z = data.bbone_x, data.bbone_z
    corners = (Vector((x, 0.0, z)), Vector((-x, 0.0, z)), Vector((-x, 0.0, -z)), Vector((x, 0.0, -z)))
    base = mw @ bone.matrix
    frames = []
    if isinstance(bone, bpy.types.PoseBone) and data.bbone_segments > 1:
        try:
            frames = [base @ bone.bbone_segment_matrix(i, rest=False) for i in range(data.bbone_segments + 1)]
        except (RuntimeError, ValueError):
            frames = []
    if not frames:
        frames = [base, base @ Matrix.Translation((0.0, bone.length, 0.0))]
    return _box_lines([[f @ c for c in corners] for f in frames])


def envelope_lines(ob, bone):
    """World edges of Blender's Envelope shape of ``bone``: wire spheres of the head and tail radius joined by four
    lines along the bone."""
    mw = ob.matrix_world
    data = bone.bone if isinstance(bone, bpy.types.PoseBone) else bone
    s = max(mw.to_scale())
    m = mw @ bone.matrix
    frame = m.to_3x3().normalized()
    head, tail = mw @ bone.head, mw @ bone.tail
    rh, rt = data.head_radius * s, data.tail_radius * s
    pts = sphere_lines(head, frame, rh) + sphere_lines(tail, frame, rt)
    for axis in (frame.col[0], -frame.col[0], frame.col[2], -frame.col[2]):
        pts += (head + axis * rh, tail + axis * rt)
    return pts


def own_shape_lines(ob, kind):
    """{bone name: world edges} of every visible bone of ``ob`` drawn as Blender's ``kind`` shape (B-Bone /
    Envelope), custom-shaped bones left out (they draw their shape)."""
    from .. import compat
    from . import layer_joints
    layered = layer_joints.state(ob)       # hidden by a display layer or a hidden joint above: nothing drawn
    fn = bbone_lines if kind == 'BBONE' else envelope_lines
    out = {}
    if ob.mode == 'EDIT':
        for eb in ob.data.edit_bones:
            if not (eb.hide or _coll_hidden(eb) or layered.get(eb.name) == _HIDDEN):
                out[eb.name] = fn(ob, eb)
    else:
        for pb in ob.pose.bones:
            if not (compat.bone_hidden(pb) or _coll_hidden(pb.bone) or pb.custom_shape is not None
                    or layered.get(pb.name) == _HIDDEN):
                out[pb.name] = fn(ob, pb)
    return out


def shape_lines(ob, matrix, depsgraph):
    """World line segments of a custom shape's edges."""
    try:
        ev = ob.evaluated_get(depsgraph)
        me = ev.to_mesh()
    except (RuntimeError, AttributeError):
        return []
    try:
        vs = [matrix @ v.co for v in me.vertices]
        return [vs[i] for e in me.edges for i in e.vertices]
    finally:
        ev.to_mesh_clear()


def joint_segments(js, name, depsgraph=None):
    """World line segments drawn for joint ``name``: its sphere and its bones to the children (a bone belongs to
    its parent joint), or its custom shape; nothing for a joint a display layer hides. Flat list of end points."""
    j = js[name]
    if j.state == _HIDDEN:
        return []
    if j.shape is not None:
        return shape_lines(j.shape[0], j.shape[1], depsgraph) if depsgraph is not None else []
    pts = sphere_lines(j.centre, j.frame, j.radius)
    for cn in j.children:
        if js[cn].shape is None:
            pts += bone_lines(j, js[cn])
    return pts
