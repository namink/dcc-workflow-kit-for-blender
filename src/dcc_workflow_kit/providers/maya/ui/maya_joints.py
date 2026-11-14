# SPDX-License-Identifier: GPL-3.0-or-later
"""Joints drawn like Maya's in the Maya layout's 3D Views, in place of Blender's bone shapes.

Maya draws a joint as a wire sphere of three great circles in the joint's local XY, YZ and XZ planes, never filled,
1 px lines, at pure world size: the drawn radius is half the joint's Radius times the scene's Joint Size, with no
screen-size limit. Between a joint and each child it draws a wire four-sided pyramid: the square base stands across
the bone on the parent's sphere, turned with the parent's axes, its corners on that sphere; the apex touches the
child's sphere. A joint without children draws no bone.

Colours follow the selection: unselected joints dark violet, selected ones white, the lead (last selected) green; a
joint below a selected one takes that joint's colour, and a bone takes its parent joint's colour. A joint in a Template
display layer draws grey and in a Reference layer black (unless it is selected itself); a joint a display layer hides,
or one below a joint whose Visibility is off, is not drawn, but the bone from its shown parent joint stays (it belongs
to the parent). Joints a layer hides or makes Template / Reference, and joints Blender can't select, are never picked.
Selected joints in a perspective view also show short local axes (X red, Y green, Z blue). A shaded surface hides the
joints behind or inside it; X-Ray Joints, X-Ray and wireframe views draw them through every surface.

Here a skeleton's joints are its bones' heads (pose positions in Object / Pose Mode, edit bones in Edit Mode); in
Object Mode a selected skeleton object counts as its root joints selected. Bones with a custom shape draw that shape
instead. The skeleton's Blender display type picks the look: Octahedral (Blender's default for a new skeleton) draws
Maya joints; Stick or Wire one line per bone and no spheres; B-Bone a wire box per bone (per segment, following the
curve) and Envelope the wire head and tail spheres joined along the bone, both in the joint colours. The kit draws
only in 3D Views of the Maya layout's workspaces where Blender's Bones overlay is off — the kit turns it off once per
screen; a view whose Bones overlay is turned back on shows Blender's bones and no kit joints.
"""

import math

import bpy
from mathutils import Matrix, Quaternion, Vector

UNSELECTED = (0x26 / 255, 0.0, 0x43 / 255)
SELECTED = (1.0, 1.0, 1.0)
LEAD = (0x43 / 255, 1.0, 0xa3 / 255)
AXIS_COLORS = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
SEGMENTS = 32
LINE_PX = 1.0
SETTLED = "allset_bones_settled"      # screen ID prop: the kit turned Blender's Bones overlay off in its 3D Views
MAYA_RADIUS = 1.0                     # Maya joint Radius default
STICK_TYPES = {'STICK', 'WIRE'}       # the skeleton's Blender display type: one line per bone, no spheres
SHAPE_TYPES = {'BBONE', 'ENVELOPE'}   # display types drawn as wire versions of Blender's bone shapes

_HIDDEN = "HIDDEN"                    # ui/layer_joints.HIDDEN
_handle = []
_GEN = [0]          # one generation per update or new frame that can change a drawn joint (``_note``, ``changed``)
_CACHE = {}         # space pointer -> (key, points, colours)
_COS = [math.cos(2.0 * math.pi * i / SEGMENTS) for i in range(SEGMENTS)]
_SIN = [math.sin(2.0 * math.pi * i / SEGMENTS) for i in range(SEGMENTS)]


# --- which views ------------------------------------------------------------------------------------------------

def maya_workspace(workspace):
    from .. import switch
    try:
        return switch.is_maya_workspace(workspace)
    except (ReferenceError, AttributeError):
        return False


def is_maya_view(space, workspace):
    """A 3D View where the kit draws the joints (and Blender's bones are off)."""
    from . import toolbox
    return (space is not None and workspace is not None and space.type == 'VIEW_3D' and not toolbox.is_toolbox(space)
            and space.overlay.show_overlays and not space.overlay.show_bones
            and space.show_object_viewport_armature and maya_workspace(workspace))


def settle(window):
    """Turn Blender's Bones overlay off in the 3D Views of ``window``'s screen once (Maya layout workspaces only)."""
    from . import toolbox
    screen = window.screen
    # temporary screens (Preferences, file browser windows) can't be a context override and hold no 3D View
    if screen is None or screen.is_temporary or screen.get(SETTLED) or not maya_workspace(window.workspace):
        return False
    changed = False
    with bpy.context.temp_override(window=window, screen=screen):
        for area in screen.areas:
            space = area.spaces.active
            if area.type == 'VIEW_3D' and not toolbox.is_toolbox(space) and space.overlay.show_bones:
                space.overlay.show_bones = False
                area.tag_redraw()
                changed = True
    screen[SETTLED] = True
    return changed


def release_all():
    """Give Blender's bones back in every screen the kit settled (disable / Maya mode off)."""
    from . import toolbox
    for screen in bpy.data.screens:
        if not screen.get(SETTLED):
            continue
        for area in screen.areas:
            space = area.spaces.active
            if area.type == 'VIEW_3D' and not toolbox.is_toolbox(space):
                space.overlay.show_bones = True
                area.tag_redraw()
        del screen[SETTLED]


def _tick():
    try:
        for window in bpy.context.window_manager.windows:
            settle(window)
    except (ReferenceError, AttributeError, RuntimeError):
        pass
    return 0.5


# --- joints ------------------------------------------------------------------------------------------------------

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


def skeleton(ob, scene):
    """{name: Joint} of armature object ``ob`` in world space: the joints not hidden by their own flags, with their
    display layer state (a joint a layer hides is kept for its parent's bone, ``joint_segments`` draws nothing for
    it)."""
    from ..operators import joints
    from ..operators.joint_edit import local_frame
    from . import layer_joints
    layered = layer_joints.state(ob)
    mw = ob.matrix_world
    m3 = mw.to_3x3()
    s = max(mw.to_scale())
    scale = _radius_scale(scene)
    out = {}
    if ob.mode == 'EDIT':
        for eb in ob.data.edit_bones:
            if eb.hide or _coll_hidden(eb):
                continue
            frame = (m3 @ local_frame(eb)).normalized()
            out[eb.name] = Joint(eb.name, eb.parent.name if eb.parent else None, mw @ eb.head, frame,
                                 drawn_radius(eb, scene, s, scale), state=layered.get(eb.name))
    else:
        shown = _shown(ob)
        for i, pb in enumerate(ob.pose.bones):
            if not shown[i]:
                continue
            bone = pb.bone
            f = m3 @ pb.matrix.to_3x3() @ joints.JOINT_AXES
            q = _maya_q(bone)
            frame = (f @ q if q is not None else f).normalized()
            shape = None
            if pb.custom_shape is not None:
                shape = (pb.custom_shape, mw @ _shape_matrix(pb))
            out[pb.name] = Joint(pb.name, bone.parent.name if bone.parent else None, mw @ pb.head, frame,
                                 drawn_radius(bone, scene, s, scale), shape, layered.get(pb.name))
    for j in out.values():
        if j.parent in out:
            out[j.parent].children.append(j.name)
    return out


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


def depth(js, name):
    n, p = 0, js[name].parent
    while p in js:
        n, p = n + 1, js[p].parent
    return n


def _screen(context, pts):
    """(a, b, ok) screen end points of segments ``pts`` (pairs) in the context region; ok = both in front."""
    from ..operators.preselect import project
    region, rv3d = context.region, context.region_data
    xy, front = project([tuple(p) for p in pts], rv3d.perspective_matrix, region.width, region.height)
    return xy[0::2], xy[1::2], front[0::2] & front[1::2]


def _unpickable(ob, js):
    """Joints of ``js`` that can't be picked: hidden / Template / Reference by a display layer, or Blender's
    unselectable bones."""
    bones = ob.data.edit_bones if ob.mode == 'EDIT' else ob.data.bones
    return {n for n, j in js.items() if j.state is not None or (n in bones and bones[n].hide_select)}


def _shape_points(shape, matrix, depsgraph):
    """``shape_lines`` as one (2E, 3) array, from the edges read once per shape (``_widget_segments``)."""
    import numpy as np
    segs, _moves = _widget_segments(shape, depsgraph)
    if not len(segs):
        return np.zeros((0, 3))
    m = np.array(matrix, np.float64)
    return segs @ m[:3, :3].T + m[:3, 3]


def _pick_lines(context, ob, js):
    """(joint names, (S, 2) screen start points, end points, in-front mask, owner index per segment) of every joint of
    ``js`` that can be picked: the lines ``joint_segments`` draws for each (sphere and bones to its children, or its
    custom shape), built for all joints at once."""
    import numpy as np
    from ..operators.preselect import project
    dg = context.evaluated_depsgraph_get()
    skip = _unpickable(ob, js)
    names = [n for n in js if n not in skip and js[n].state != _HIDDEN]
    plain = [n for n in names if js[n].shape is None]
    rings = {}
    if plain:
        c = np.array([tuple(js[n].centre) for n in plain], np.float64)
        f = np.array([[tuple(r) for r in js[n].frame] for n in plain], np.float64)
        r = np.array([js[n].radius for n in plain], np.float64)
        rings = dict(zip(plain, _spheres(c, f, r).reshape(len(plain), -1, 3)))
    kept, chunks = [], []
    for n in names:
        j = js[n]
        if j.shape is not None:
            pts = _shape_points(j.shape[0], j.shape[1], dg)
        else:
            pts = rings[n]
            more = [tuple(p) for cn in j.children if js[cn].shape is None for p in bone_lines(j, js[cn])]
            if more:
                pts = np.vstack((pts, np.array(more, np.float32)))
        if len(pts):
            kept.append(n)
            chunks.append(np.asarray(pts, np.float64).reshape(-1, 3))
    if not kept:
        return kept, np.zeros((0, 2)), np.zeros((0, 2)), np.zeros(0, bool), np.zeros(0, np.int64)
    owner = np.repeat(np.arange(len(kept)), [len(p) // 2 for p in chunks])
    region, rv3d = context.region, context.region_data
    xy, front = project(np.concatenate(chunks), rv3d.perspective_matrix, region.width, region.height)
    return kept, xy[0::2], xy[1::2], front[0::2] & front[1::2], owner


_PICK_PLAN = {}   # skeleton object pointer -> (its ``_PICK`` entry, what clicks reuse of it: ``_pick_plan``)


def _pick_current(context, ob):
    """The lines kept for skeleton ``ob`` (``_PICK``) are still its drawn lines: nothing that can move them reached
    it since they were built (a selection or a change to another skeleton doesn't)."""
    layer = getattr(context, "view_layer", None) or bpy.context.view_layer
    ptr = ob.as_pointer()
    key = _world_key(context.scene, layer)
    if _WORLD[0] != key:
        dirt = _since(_WORLD[0], key)
        if dirt is None or dirt[1] is not None or dirt[3] or ptr in dirt[0]:
            return False
        if _radius_scale(context.scene) != _SCALE[0]:
            return False
    b = _BUILDS.get(ptr)
    return b is None or b.level is None


def _pick_plan(ptr, got):
    """What every click reuses of pick lines ``got`` (``_PICK``): the segments joined once, their joints; per set of
    pickable joints the kept segments, per view their screen ends."""
    import numpy as np
    held = _PICK_PLAN.get(ptr)
    if held is not None and held[0] is got:
        return held[1]
    jl, chunks = got
    pts, owner = [], []
    for p, who, index in chunks:
        if index is not None:
            p, who = p[index], who[index]
        if len(p):
            pts.append(p)
            owner.append(who)
    plan = None
    if pts:
        pts, owner = np.concatenate(pts), np.concatenate(owner)
        plan = {"pts": pts.reshape(-1, 2, 3), "seg": owner[0::2], "pickable": None, "view": None,
                "state": np.array([jl.js[n].state is None for n in jl.names], bool)}
    if len(_PICK_PLAN) > 32:
        _PICK_PLAN.clear()
    _PICK_PLAN[ptr] = (got, plan)
    return plan


def _drawn_pick_lines(context, ob):
    """``_pick_lines`` of skeleton ``ob`` (Object / Pose Mode, drawn as Maya joints) from the lines last drawn for it,
    when nothing has changed them since they were built (``_joined``), + its joint list; else None. A click then
    projects the drawn lines instead of reading the skeleton again; the lines joined, the pickable ones and their
    screen ends in a view are kept for the next click."""
    import numpy as np
    from ..operators.preselect import project
    ptr = ob.as_pointer()
    got = _PICK.get(ptr)
    if got is None or ob.mode == 'EDIT' or not _pick_current(context, ob):
        return None
    plan = _pick_plan(ptr, got)
    if plan is None:
        return None
    jl = got[0]
    bones = ob.data.bones
    hide_select = np.zeros(len(bones), bool)
    bones.foreach_get("hide_select", hide_select)
    # ``_unpickable``: a display layer's state (hidden / Template / Reference) or Blender's unselectable bones
    pickable = plan["state"] & ~hide_select[_bone_rows(ob, jl)]
    if plan["pickable"] is None or not np.array_equal(plan["pickable"], pickable):
        seg = plan["seg"]
        keep = pickable[seg]
        kept, owner = np.unique(seg[keep], return_inverse=True)
        plan.update(pickable=pickable, view=None, kept=[jl.names[i] for i in kept], owner=owner.astype(np.int64),
                    ends=plan["pts"][keep].reshape(-1, 3).astype(np.float64))
    if not len(plan["owner"]):
        return [], np.zeros((0, 2)), np.zeros((0, 2)), np.zeros(0, bool), np.zeros(0, np.int64), jl
    region, rv3d = context.region, context.region_data
    persp = rv3d.perspective_matrix
    view = (tuple(tuple(r) for r in persp), region.width, region.height)
    if plan["view"] != view:
        xy, front = project(plan["ends"], persp, region.width, region.height)
        plan.update(view=view, a=np.ascontiguousarray(xy[0::2]), b=np.ascontiguousarray(xy[1::2]),
                    ok=front[0::2] & front[1::2], columns=None)
    return list(plan["kept"]), plan["a"], plan["b"], plan["ok"], plan["owner"], jl


_PICK_MEMO = [None]     # while one click is picked (``pick_memo``): {(skeleton, mode, region, mouse): distances}


class pick_memo:
    """Within one click nothing moves between the coarse object test and the joint pick: ``screen_distance`` reads
    each skeleton once (a skeleton read costs milliseconds per hundred joints). Nests; the outermost one ends it."""

    def __enter__(self):
        self._outer = _PICK_MEMO[0] is not None
        if not self._outer:
            _PICK_MEMO[0] = {}
        return self

    def __exit__(self, *_exc):
        if not self._outer:
            _PICK_MEMO[0] = None


def screen_distance(context, ob, mouse):
    """{joint: screen distance from ``mouse`` to its drawn lines} of armature ``ob``, for the joints that can be
    picked."""
    memo = _PICK_MEMO[0]
    key = None
    if memo is not None:
        key = (ob.as_pointer(), ob.mode, context.region.as_pointer(), float(mouse[0]), float(mouse[1]))
        got = memo.get(key)
        if got is not None:
            return dict(got)
    out = _screen_distance(context, ob, mouse)
    if key is not None:
        memo[key] = dict(out)
    return out


def _screen_distance(context, ob, mouse):
    import numpy as np
    got = _drawn_pick_lines(context, ob)
    names, a, b, ok, owner = got[:5] if got is not None else _pick_lines(context, ob, skeleton(ob, context.scene))
    if not names:
        return {}
    held = _PICK_PLAN.get(ob.as_pointer()) if got is not None else None
    plan = held[1] if held is not None else None
    if plan is not None and plan.get("a") is a:      # the drawn lines in this view: their columns are kept
        if plan.get("columns") is None:
            plan["columns"] = _segment_columns(a, b)
        columns = plan["columns"]
    else:
        columns = _segment_columns(a, b)
    near = _nearest(owner, len(names), _segment_distances(mouse, columns), ok)
    found = np.flatnonzero(np.isfinite(near))
    return dict(zip([names[i] for i in found.tolist()], near[found].tolist()))


def _segment_columns(a, b):
    """What ``preselect.segment_distance`` works out of the screen segments a[i]-b[i] ((S, 2) each) before it looks
    at the mouse, one array per coordinate: start x, start y, direction x, y, long enough, squared length (1 where
    not)."""
    import numpy as np
    ax, ay = np.ascontiguousarray(a[:, 0], np.float64), np.ascontiguousarray(a[:, 1], np.float64)
    dx, dy = b[:, 0] - ax, b[:, 1] - ay
    ll = dx * dx + dy * dy
    long_ = ll > 1e-12
    return ax, ay, dx, dy, long_, np.where(long_, ll, 1.0)


def _segment_distances(p, columns):
    """``preselect.segment_distance`` (its distances) from point ``p`` to the segments of ``_segment_columns``: the
    same steps in the same order, one coordinate array at a time."""
    import numpy as np
    ax, ay, dx, dy, long_, ll = columns
    t = np.where(long_, ((p[0] - ax) * dx + (p[1] - ay) * dy) / ll, 0.0)
    t = np.clip(t, 0.0, 1.0)
    return np.hypot(ax + dx * t - p[0], ay + dy * t - p[1])


_NEAREST = [None]   # (segment owners, joint count, segment order by joint, first segment of each joint) of a click


def _nearest(owner, n, d, ok):
    """The smallest ``d`` of the ``ok`` segments of each of ``n`` joints (``owner``: joint per segment), inf where it
    has none. The segments sorted by joint are kept for the owners of the drawn lines (every click uses them)."""
    import numpy as np
    got = _NEAREST[0]
    if got is None or got[0] is not owner or got[1] != n:
        cnt = np.bincount(owner, minlength=n) if len(owner) else np.zeros(n, np.intp)
        order = starts = None
        if len(cnt) == n and n and cnt.all():           # every joint has a segment: one minimum per run
            order = np.argsort(owner, kind='stable')
            starts = np.concatenate(([0], np.cumsum(cnt)[:-1]))
        got = _NEAREST[0] = (owner, n, order, starts)
    if got[2] is None:
        near = np.full(n, np.inf)
        np.minimum.at(near, owner[ok], d[ok])
        return near
    return np.minimum.reduceat(np.where(ok, d, np.inf)[got[2]], got[3])


def pick(context, ob, mouse, radius):
    """The joint of ``ob`` whose drawn line is nearest to ``mouse`` within ``radius`` px (Maya: a click hits the wire,
    not the inside of the sphere; a bone hit picks its parent joint), or None."""
    d = screen_distance(context, ob, mouse)
    near = [(v, n) for n, v in d.items() if v <= radius]
    return min(near)[1] if near else None


def _seg_cross(p1, p2, q1, q2):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def _in_poly(pt, poly):
    x, y = pt
    inside = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def segments_touch(a, b, poly):
    """Does any segment a[i]-b[i] touch the closed polygon ``poly`` (screen points)?"""
    edges = [(poly[i - 1], poly[i]) for i in range(len(poly))]
    for p, q in zip(a, b):
        if _in_poly(p, poly) or _in_poly(q, poly):
            return True
        if any(_seg_cross(p, q, e0, e1) for e0, e1 in edges):
            return True
    return False


def region_pick(context, ob, poly):
    """Maya marquee / lasso on a skeleton: the bones whose drawn lines touch ``poly``. Maya joints keep the one
    closest to the root (a box around a whole chain selects its top joint); controls (bones with a custom shape)
    and bones of a skeleton not drawn as Maya joints are each picked, like Maya's curve controls. Joints that can't be
    picked (``_unpickable``) are left out. Returns names."""
    import numpy as np
    maya_drawn = getattr(ob.data, "display_type", 'OCTAHEDRAL') not in STICK_TYPES | SHAPE_TYPES
    got = _drawn_pick_lines(context, ob)
    if got is not None:                        # the drawn lines (``_joined``); a joint list's joints have no shape
        names, a, b, ok, owner, jl = got
        js = jl.js
        control = {jl.names[j] for j in jl.ctrl}
    else:
        js = skeleton(ob, context.scene)
        names, a, b, ok, owner = _pick_lines(context, ob, js)
        control = {n for n, j in js.items() if j.shape is not None}
    joints, each = [], []
    if not names:
        return each
    hit = np.zeros(len(names), bool)
    use = np.flatnonzero(ok)
    hit[owner[use[_touching(a[use], b[use], poly)]]] = True
    for i in np.flatnonzero(hit).tolist():
        n = names[i]
        if maya_drawn and n not in control:
            joints.append(n)
        else:
            each.append(n)
    if not joints:
        return each
    depths, index = _region_depths(js)
    return each + [min((depths[n], index[n], n) for n in joints)[2]]


_DEPTHS = {}    # id(joints) -> (joints, {name: ``depth``}, {name: position}): ``region_pick`` of the same joints


def _region_depths(js):
    """{name: ``depth(js, name)``} and {name: position in ``js``} of every joint, kept while ``js`` is the same (a
    drawn skeleton's joint list lasts until the skeleton changes)."""
    held = _DEPTHS.get(id(js))
    if held is not None and held[0] is js:
        return held[1], held[2]
    depths = {}
    for name in js:
        chain, p = [], name
        while p not in depths:
            chain.append(p)
            p = js[p].parent
            if p not in js:              # the top: no parent among the joints
                d = 0
                break
        else:
            d = depths[p] + 1
        for n in reversed(chain):
            depths[n] = d
            d += 1
    if len(_DEPTHS) > 8:
        _DEPTHS.clear()
    index = {n: i for i, n in enumerate(js)}
    _DEPTHS[id(js)] = (js, depths, index)
    return depths, index


def _box_bounds(pg):
    """(x min, x max, y min, y max) of a polygon that is an upright rectangle given corner by corner (a box select's
    region), else None."""
    if len(pg) != 4:
        return None
    (ax, ay), (bx, by), (cx, cy), (dx, dy) = pg.tolist()
    if not ((ay == by and bx == cx and cy == dy and dx == ax) or (ax == bx and by == cy and cx == dx and dy == ay)):
        return None
    return min(ax, cx), max(ax, cx), min(ay, cy), max(ay, cy)


def _touching(a, b, poly):
    """``segments_touch`` for each segment a[i]-b[i] ((S, 2) arrays) at once: a bool per segment."""
    import numpy as np
    pg = np.asarray(poly, np.float64).reshape(-1, 2)
    box = _box_bounds(pg)

    def inside(p):
        x, y = p[:, 0], p[:, 1]
        if box is not None:
            # the crossing rule below on an upright rectangle: only its two upright sides count, each at its own x
            # for any y, so a point is inside from the low side up to (not including) the high side
            x0, x1, y0, y1 = box
            return (x >= x0) & (x < x1) & (y >= y0) & (y < y1)
        res = np.zeros(len(p), bool)
        for i in range(len(pg)):
            (x1, y1), (x2, y2) = pg[i], pg[i - 1]
            if y1 != y2:              # a level edge never crosses the ray
                res ^= ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1)
        return res

    out = inside(a) | inside(b)
    rest = np.flatnonzero(~out)          # a segment with an end inside touches already: the crossings of the others
    if not len(rest):
        return out
    a, b = a[rest], b[rest]
    ax, ay, bx, by = a[:, 0], a[:, 1], b[:, 0], b[:, 1]
    cross = np.zeros(len(rest), bool)
    for i in range(len(pg)):
        (ex0, ey0), (ex1, ey1) = pg[i - 1], pg[i]
        d1 = (ex1 - ex0) * (ay - ey0) - (ey1 - ey0) * (ax - ex0)
        d2 = (ex1 - ex0) * (by - ey0) - (ey1 - ey0) * (bx - ex0)
        d3 = (bx - ax) * (ey0 - ay) - (by - ay) * (ex0 - ax)
        d4 = (bx - ax) * (ey1 - ay) - (by - ay) * (ex1 - ax)
        cross |= (d1 * d2 < 0) & (d3 * d4 < 0)
    out[rest] = cross
    return out


def _sphere_array(js):
    """(points, joint order) of every sphere's three great circles as one float32 array of segment end points."""
    import numpy as np
    order = [n for n, j in js.items() if j.shape is None and j.state != _HIDDEN]
    if not order:
        return np.zeros((0, 3), np.float32), order
    c = np.array([tuple(js[n].centre) for n in order], np.float64)                  # (N, 3)
    f = np.array([[tuple(r) for r in js[n].frame] for n in order], np.float64)      # (N, 3, 3) rows
    r = np.array([js[n].radius for n in order], np.float64)
    return _spheres(c, f, r), order


def _spheres(c, f, r):
    """Segment end points (float32) of the three great circles of spheres at centres ``c`` (N, 3) with frames ``f``
    (N, 3, 3; columns = the joint's X, Y, Z) and radii ``r`` (N,): per joint, circle and segment its two ends."""
    import numpy as np
    if not len(c):
        return np.zeros((0, 3), np.float32)
    return _sphere_ring(c, f, r)[_sphere_index(len(c))]


def _sphere_index(n):
    """Int32 line index into ``_sphere_ring`` of ``n`` spheres giving the segments of ``_spheres`` in its order (per
    joint, circle and segment: ring points i and i + 1). Kept per ``n``."""
    import numpy as np
    got = _RING_INDEX.get(n)
    if got is None:
        j = np.arange(n, dtype=np.intc)[:, None, None]
        k = np.arange(3, dtype=np.intc)[None, :, None]
        s = np.arange(SEGMENTS, dtype=np.intc)[None, None, :]
        a = (k * (SEGMENTS + 1) + s) * n + j                                    # (joint, circle, segment)
        got = np.ascontiguousarray(np.stack((a, a + n), axis=3).reshape(-1))
        if len(_RING_INDEX) > 64:
            _RING_INDEX.clear()
        _RING_INDEX[n] = got
    return got


def _sphere_ring(c, f, r):
    """The ring points (float32) of the three great circles of spheres at centres ``c`` (N, 3) with frames ``f``
    (N, 3, 3; columns = the joint's X, Y, Z) and radii ``r`` (N,), each point once: (3 * (SEGMENTS + 1) * N, 3) in
    the order circle, ring point, joint. ``_sphere_index`` draws them as the segments of ``_spheres``."""
    import numpy as np
    n = len(c)
    if not n:
        return np.zeros((0, 3), np.float32)
    if _RING[0] is None:
        t = np.arange(SEGMENTS + 1) * (2.0 * math.pi / SEGMENTS)
        _RING[0] = np.cos(t)[:, None], np.sin(t)[:, None]
    cos, sin = _RING[0]
    # ring point i of the circle in the joint's axes a, b: centre + (cos_i * axis a + sin_i * axis b) * radius, each
    # step rounded in this order; worked out for every joint side by side (x, y, z of joint 0, of joint 1, ...)
    axes = f.transpose(2, 0, 1).reshape(3, n * 3)       # frame column a of every joint
    u = np.empty((3, SEGMENTS + 1, n * 3))
    term = np.empty((SEGMENTS + 1, n * 3))
    for k, (a, b) in enumerate(((0, 1), (1, 2), (0, 2))):
        np.multiply(cos, axes[a], out=u[k])
        np.multiply(sin, axes[b], out=term)
        u[k] += term
    u *= np.repeat(r, 3)
    u += c.reshape(-1)
    return u.astype(np.float32).reshape(-1, 3)          # (circle, ring point, joint): x, y, z of each point


_RING = [None]      # (cos, sin) of the ring points' angles (S + 1, 1)
_RING_INDEX = {}    # sphere count -> ``_sphere_index``


def _bone_array(pc, pf, pr, cc, cr):
    """``bone_lines`` for many bones at once: parents' centres / frames / radii (M, 3) (M, 3, 3) (M,) and children's
    centres / radii. Returns (points (K * 5, 3): each pyramid's four base corners and its apex, the K bones that are
    drawn) — a bone whose spheres overlap draws nothing. ``_bone_index`` draws them as ``bone_lines``' segments."""
    import numpy as np
    d = cc - pc
    length = np.linalg.norm(d, axis=1)
    drawn = np.nonzero((length > pr + cr) & (length >= 1e-9))[0]
    if not len(drawn):
        return np.zeros((0, 3), np.float64), drawn
    d, length, pc, pf, pr, cc, cr = d[drawn], length[drawn], pc[drawn], pf[drawn], pr[drawn], cc[drawn], cr[drawn]
    u = d / length[:, None]
    base = pc + u * pr[:, None]
    apex = cc - u * cr[:, None]

    def across(axis):
        v = pf[:, :, axis]
        return v - u * np.sum(v * u, axis=1)[:, None]

    a = across(1)
    flat = np.linalg.norm(a, axis=1) < 1e-6
    if flat.any():
        a[flat] = across(2)[flat]
    n = np.linalg.norm(a, axis=1)[:, None]
    a = np.divide(a, n, out=np.zeros_like(a), where=n > 0)
    b = np.cross(u, a)
    ar, br = a * pr[:, None], b * pr[:, None]
    pts = np.stack((base + ar, base + br, base - ar, base - br, apex), axis=1)          # (K, 5, 3)
    return pts.reshape(-1, 3), drawn


_BONE_SEGMENTS = (0, 1, 0, 4, 1, 2, 1, 4, 2, 3, 2, 4, 3, 0, 3, 4)   # corner i to i + 1 and to the apex, per corner
_BONE_INDEX = {}    # pyramid count -> ``_bone_index``


def _bone_index(k):
    """Int32 line index into ``_bone_array``'s points of ``k`` pyramids: per corner the base edge to the next corner,
    then the edge up to the apex. Kept per ``k``."""
    import numpy as np
    got = _BONE_INDEX.get(k)
    if got is None:
        got = np.ascontiguousarray((np.arange(k, dtype=np.intc)[:, None] * 5
                                    + np.array(_BONE_SEGMENTS, np.intc)[None, :]).reshape(-1))
        if len(_BONE_INDEX) > 64:
            _BONE_INDEX.clear()
        _BONE_INDEX[k] = got
    return got


class JointList:
    """What a pose doesn't change of a skeleton's drawn joints (Object / Pose Mode)."""
    __slots__ = ("js", "names", "rows", "parents", "raw", "turned", "shaped", "plain", "ctrl", "ctrl_src",
                 "ctrl_len", "ctrl_shapes", "bone_par", "bone_child", "widgets", "bone_rows", "shown", "tint",
                 "parent_names", "owners")


def _joint_list(ob):
    """What a pose doesn't change of skeleton ``ob``'s drawn joints: joints {name: Joint, geometry left out}, names,
    their pose bone rows, parent index per joint (-1: no drawn parent), Radius values, {index: Maya frame turn
    (3, 3)}, {index: custom shape object}; for the controls (bones with a custom shape) the pose bone row their shape
    follows and their rest length; the drawn bones (parent, child) between joints without a custom shape. The bones
    are read in one pass in their own order (a lookup by position or name walks the list)."""
    import numpy as np
    from ..operators import joints
    from . import layer_joints
    layered = layer_joints.state(ob)
    pbs, bones = ob.pose.bones, ob.data.bones
    pose_names = pbs.keys()
    pose_row = {n: i for i, n in enumerate(pose_names)}
    shown = _shown(ob, pose_names, pose_row)
    shapes, transforms = [], []
    for pb in pbs:
        s = pb.custom_shape
        shapes.append(s)
        transforms.append(pb.custom_shape_transform if s is not None else None)
    bone_row = {n: k for k, n in enumerate(bones.keys())}
    parent, frame, radius = [], [], []
    frame_key, radius_key = joints.MAYA_FRAME, joints.RADIUS
    for b in bones:
        p = b.parent
        parent.append(p.name if p is not None else None)
        frame.append(b.get(frame_key))
        radius.append(b.get(radius_key, MAYA_RADIUS))
    lengths = np.empty(len(bones), np.float32)
    bones.foreach_get("length", lengths)
    js, names, keep, raw, turned, shaped, src, blen, parent_names = {}, [], [], [], {}, {}, [], [], []
    for i, name in enumerate(pose_names):
        if not shown[i]:
            continue
        k = bone_row[name]
        shape = shapes[i]
        if shape is not None:
            shaped[len(keep)] = shape
            t = transforms[i]
            row = pose_row.get(t.name, -1) if t is not None else i
            src.append(row if row >= 0 else i)
            blen.append(float(lengths[k]))
        q = frame[k]
        if q is not None:
            turned[len(keep)] = np.array(Quaternion(q).to_matrix(), np.float64)
        js[name] = Joint(name, parent[k], None, None, None, state=layered.get(name))
        names.append(name)
        parent_names.append(parent[k])
        keep.append(i)
        raw.append(float(radius[k]))
    index = {nm: j for j, nm in enumerate(names)}
    jl = JointList()
    jl.js, jl.names, jl.rows, jl.raw = js, names, np.asarray(keep, np.intp), np.asarray(raw, np.float64)
    jl.parent_names = parent_names
    jl.parents = np.array([index.get(js[nm].parent, -1) for nm in names], np.intp)
    jl.turned, jl.shaped = turned, shaped
    jl.plain = np.ones(len(names), bool)
    jl.ctrl = np.fromiter(shaped, np.intp, len(shaped))
    jl.plain[jl.ctrl] = False
    jl.ctrl_src = np.asarray(src, np.intp)
    jl.ctrl_len = np.asarray(blen, np.float64)
    jl.ctrl_shapes = list(shaped.values())
    # a joint a display layer hides draws nothing, but the bone from its shown parent stays (the parent's)
    jl.shown = np.array([js[nm].state != layer_joints.HIDDEN for nm in names], bool)
    jl.tint = {j: (*layer_joints.COLOURS[js[nm].state], 1.0) for j, nm in enumerate(names)
               if js[nm].state in layer_joints.COLOURS}
    child = np.nonzero(jl.parents >= 0)[0]
    child = child[jl.plain[child] & jl.plain[jl.parents[child]] & jl.shown[jl.parents[child]]]
    par = jl.parents[child]
    order = np.lexsort((child, par))           # a bone belongs to its parent joint: parent by parent
    jl.bone_child, jl.bone_par = child[order], par[order]
    jl.widgets = None                          # the controls' shape lines in their own space (``_control_lines``)
    jl.owners = {}                             # joint index per drawn point, kept per part (``_owner``)
    jl.bone_rows = np.array([bone_row[nm] for nm in names], np.intp)      # rows in ``ob.data.bones``
    return jl


def _same_list(a, b):
    """Joint lists ``a`` and ``b`` hold the same joints, hierarchy, Radius values, Maya frames, controls, display
    layer states and drawn bones (what a pose doesn't change is unchanged)."""
    import numpy as np
    if a.names != b.names or a.parent_names != b.parent_names:
        return False
    for x, y in ((a.rows, b.rows), (a.parents, b.parents), (a.raw, b.raw), (a.ctrl, b.ctrl), (a.ctrl_src, b.ctrl_src),
                 (a.ctrl_len, b.ctrl_len), (a.shown, b.shown), (a.bone_rows, b.bone_rows)):
        if not np.array_equal(x, y):
            return False
    if a.tint != b.tint or a.turned.keys() != b.turned.keys():
        return False
    if any(not np.array_equal(a.turned[j], b.turned[j]) for j in a.turned):
        return False
    try:
        return [s.as_pointer() for s in a.ctrl_shapes] == [s.as_pointer() for s in b.ctrl_shapes]
    except ReferenceError:                     # a shape object removed since ``a`` was read
        return False


_LISTS = {}     # skeleton object pointer -> (key, _joint_list) kept while playback runs
_EDITS = [0]    # bumped by every change that can change a skeleton's joint list (not by a new frame)
_WIDGETS = {}   # custom shape object session uid -> (its data pointer, its edges' end points in its own space)
_WIDGET_GEN = [0]   # bumped whenever a custom shape is read again (``_widget_plan`` joins them again)


def joint_list(ob, playing=False):
    """``_joint_list`` of ``ob``. While playback runs only the pose changes from frame to frame, so the list read
    on the first frame is used again until something is edited (a depsgraph update, undo, a Radius typed)."""
    key = (_EDITS[0], ob.data.as_pointer(), len(ob.pose.bones))
    got = _LISTS.get(ob.as_pointer())
    if playing and got is not None and got[0] == key:
        return got[1]
    out = _joint_list(ob)
    if playing:
        if len(_LISTS) > 32:
            _LISTS.clear()
        _LISTS[ob.as_pointer()] = (key, out)
    else:
        _LISTS.pop(ob.as_pointer(), None)
    return out


def _bone_rows(ob, jl):
    """Row of every joint of ``jl`` in ``ob.data.bones`` (its order can differ from the pose bones')."""
    import numpy as np
    if jl.bone_rows is None:
        index = {b.name: i for i, b in enumerate(ob.data.bones)}
        jl.bone_rows = np.array([index[nm] for nm in jl.names], np.intp)
    return jl.bone_rows


def _pose_raw(ob, scene, jl):
    """What skeleton ``ob``'s drawn lines follow besides its joint list, read in one go: every pose bone's
    armature-space matrix and head (as stored), the world matrix, the drawn radius factor and, with controls, their
    custom shape offset / turn / scale. The same readings draw the same lines."""
    import numpy as np
    from ..operators import joint_display, units
    pbs = ob.pose.bones
    n = len(pbs)
    mw = ob.matrix_world
    k = 0.5 * joint_display.joint_size(scene) * units.radius_unit(scene) * max(mw.to_scale())
    mat = np.empty(n * 16, np.float32)
    pbs.foreach_get("matrix", mat)
    head = np.empty(n * 3, np.float32)
    pbs.foreach_get("head", head)
    shape = None
    if len(jl.ctrl):
        shape = []
        for prop in ("custom_shape_translation", "custom_shape_rotation_euler", "custom_shape_scale_xyz"):
            a = np.empty(n * 3, np.float32)
            pbs.foreach_get(prop, a)
            shape.append(a)
        use = np.zeros(n, bool)
        pbs.foreach_get("use_custom_shape_bone_size", use)
        shape.append(use)
    return mat, head, np.array(mw, np.float64), k, shape


def _same_raw(a, b):
    """Two ``_pose_raw`` readings are the same."""
    import numpy as np
    if a is None or b is None or a[3] != b[3] or (a[4] is None) != (b[4] is None):
        return False
    if not all(np.array_equal(x, y) for x, y in zip(a[:3], b[:3])):
        return False
    return a[4] is None or all(np.array_equal(x, y) for x, y in zip(a[4], b[4]))


def _pose_read(ob, scene, jl, raw=None, only=None):
    """(world matrix (4, 4), every pose bone's armature-space matrix (n, 4, 4), and the drawn joints' centres (N, 3),
    frames (N, 3, 3; columns normalised) and radii (N,)) of skeleton ``ob`` — one read of the pose for all joints.
    ``raw``: its ``_pose_raw`` when already read. ``only``: joint indices: the centres, frames and radii of these
    joints alone (each joint's numbers are worked out from its own bone: the same as among all joints)."""
    import numpy as np
    from ..operators import joints
    mat, head, w, k, _shape = raw if raw is not None else _pose_raw(ob, scene, jl)
    n = len(head) // 3
    allm = mat.reshape(n, 4, 4).transpose(0, 2, 1).astype(np.float64)       # stored by columns
    m3 = w[:3, :3]
    rows = jl.rows if only is None else jl.rows[only]
    centres = head.reshape(n, 3)[rows].astype(np.float64) @ m3.T + w[:3, 3]
    frames = m3 @ allm[rows][:, :3, :3] @ np.array(joints.JOINT_AXES, np.float64)
    if only is None:
        for j, q in jl.turned.items():
            frames[j] = frames[j] @ q
    elif jl.turned:
        for i, j in enumerate(only.tolist()):
            q = jl.turned.get(j)
            if q is not None:
                frames[i] = frames[i] @ q
    norms = np.linalg.norm(frames, axis=1, keepdims=True)
    frames = np.divide(frames, norms, out=np.zeros_like(frames), where=norms > 0)
    return w, allm, centres, frames, (jl.raw if only is None else jl.raw[only]) * k


def _pose_arrays(ob, scene, playing=False):
    """The visible joints of ``ob`` in Object / Pose Mode: (joints {name: Joint, geometry left out}, names, parent
    index per joint (-1: no drawn parent), centres (N, 3), frames (N, 3, 3), radii (N,), {index: (custom shape,
    world matrix)}) — the same joints, centres, frames (columns normalised) and radii as ``skeleton``."""
    import numpy as np
    jl = joint_list(ob, playing)
    if not jl.names:
        return jl.js, jl.names, jl.parents, np.zeros((0, 3)), np.zeros((0, 3, 3)), jl.raw, {}
    _w, _allm, centres, frames, radii = _pose_read(ob, scene, jl)
    pbs, mw = ob.pose.bones, ob.matrix_world
    shapes = {j: (shape, mw @ _shape_matrix(pbs[int(jl.rows[j])])) for j, shape in jl.shaped.items()}
    return jl.js, jl.names, jl.parents, centres, frames, radii, shapes


def _joint_selection(ob, jl):
    """``selection`` of ``ob``; in Pose Mode the selected bones are read in one call."""
    import numpy as np
    from ..operators import joint_preview
    if ob.mode != 'POSE' or (joint_preview.running() and joint_preview.STATE.get("ob") == ob.name):
        return selection(ob, jl.js)
    pbs = ob.pose.bones
    flags = np.zeros(len(pbs), bool)
    pbs.foreach_get("select", flags)
    sel = {jl.names[j] for j in np.nonzero(flags[jl.rows])[0]}
    act = ob.data.bones.active
    return sel, (act.name if act is not None and act.name in sel else None)


def _joint_rgba(jl, sel, lead):
    """(N, 4) colour of every joint (``colours``, resolved for all joints at once); nothing selected: all
    unselected."""
    import numpy as np
    n = len(jl.names)
    if not sel:
        rgba = np.tile(np.array((*UNSELECTED, 1.0), np.float32), (n, 1))
        for j, c in jl.tint.items():           # Template / Reference layer colour
            rgba[j] = c
        return rgba
    # each joint's own colour (lead, selected, its layer's), else the nearest joint above it with one
    palette = [(*UNSELECTED, 1.0), (*SELECTED, 1.0), (*LEAD, 1.0)]
    val = np.full(n, -1, np.intp)
    for j, c in jl.tint.items():
        if c not in palette:
            palette.append(c)
        val[j] = palette.index(c)
    val[np.fromiter((nm in sel for nm in jl.names), bool, n)] = 1
    if lead is not None and lead in jl.js:
        val[jl.names.index(lead)] = 2
    up = jl.parents.copy()
    todo = np.flatnonzero((val < 0) & (up >= 0))
    while len(todo):
        got = val[up[todo]]
        have = got >= 0
        val[todo[have]] = got[have]
        rest = todo[~have]
        up[rest] = up[up[rest]]                # the parent has no colour of its own: look past it
        todo = rest[up[rest] >= 0]
    val[val < 0] = 0
    return np.array(palette, np.float32)[val]


def _read_widget(shape, depsgraph):
    """(2E, 3) end points of the edges of custom shape object ``shape``'s evaluated geometry, in its own space."""
    import numpy as np
    try:
        ev = shape.evaluated_get(depsgraph)
        me = ev.to_mesh()
    except (RuntimeError, AttributeError, ReferenceError):
        return np.zeros((0, 3))
    try:
        if me is None:
            return np.zeros((0, 3))
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        ed = np.empty(len(me.edges) * 2, np.intc)      # C int: an int32 buffer of another kind is copied item by item
        me.edges.foreach_get("vertices", ed)
        return co.reshape(-1, 3).astype(np.float64)[ed]
    finally:
        ev.to_mesh_clear()


# modifiers that only reshape the object's own geometry: unkeyed, their result can't change with the frame
_STILL_MODIFIERS = frozenset({'SUBSURF', 'MULTIRES', 'TRIANGULATE', 'EDGE_SPLIT', 'WELD', 'SOLIDIFY', 'BEVEL',
                              'WIREFRAME'})


def shape_moves(shape):
    """Can custom shape ``shape``'s geometry change with the frame? Shape keys, particles, animated or driven data,
    a modifier that can read the time or other objects, or a keyed / driven modifier setting. A Subdivision Surface
    (Bevel, Solidify ...) modifier alone can't."""
    if getattr(shape, "particle_systems", None):
        return True
    if shape.modifiers and (shape.animation_data is not None
                            or any(m.type not in _STILL_MODIFIERS for m in shape.modifiers)):
        return True
    data = shape.data
    return data is not None and (getattr(data, "shape_keys", None) is not None or data.animation_data is not None)


def _widget_segments(shape, depsgraph):
    """(``_read_widget`` of ``shape``, changes with the frame). A shape whose geometry can't change with the frame is
    read once and kept until its geometry is edited (``_depsgraph_post``), something is edited (``changed``) or
    undone; one that can (``shape_moves``) is read every time."""
    uid, data = shape.session_uid, shape.data
    dptr = data.as_pointer() if data is not None else 0
    got = _WIDGETS.get(uid)
    if got is not None and got[0] == dptr:
        return got[1], False
    segs = _read_widget(shape, depsgraph)
    if shape_moves(shape):
        return segs, True
    _WIDGETS[uid] = (dptr, segs)
    return segs, False


def _drop_widget(uid):
    """Read custom shape ``uid``'s geometry again at its next use."""
    if _WIDGETS.pop(uid, None) is not None:
        _WIDGET_GEN[0] += 1


def _euler_xyz(e):
    """(K, 3) XYZ Euler angles -> (K, 3, 3) rotation matrices (``Euler.to_matrix``)."""
    import numpy as np
    cx, cy, cz = np.cos(e[:, 0]), np.cos(e[:, 1]), np.cos(e[:, 2])
    sx, sy, sz = np.sin(e[:, 0]), np.sin(e[:, 1]), np.sin(e[:, 2])
    m = np.empty((len(e), 3, 3))
    m[:, 0, 0], m[:, 0, 1], m[:, 0, 2] = cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz
    m[:, 1, 0], m[:, 1, 1], m[:, 1, 2] = cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz
    m[:, 2, 0], m[:, 2, 1], m[:, 2, 2] = -sy, sx * cy, cx * cy
    return m


def _distinct_points(segs):
    """(each distinct point of segment end points ``segs`` (2E, 3) once, int32 index of every end point into them):
    points with the same bits are one point."""
    import numpy as np
    if not len(segs):
        return segs, np.zeros(0, np.intc)
    rows = np.ascontiguousarray(segs).view(np.dtype((np.void, segs.dtype.itemsize * 3))).reshape(-1)
    _u, first, inverse = np.unique(rows, return_index=True, return_inverse=True)
    return segs[first], inverse.reshape(-1).astype(np.intc)


def _widget_plan(jl, depsgraph):
    """The controls' shape lines joined in their own space: (points, shape per point, points per shape, the shapes
    that change with the frame [(shape, start, count)], widget generation, int32 line index into the points of every
    shape's segments in order). A shape that can't change with the frame keeps each of its points once; one that can
    keeps its segments' end points. Joined once per joint list and kept while no shape's own geometry changed; the
    shapes that change with the frame are read again in place."""
    import numpy as np
    plan = jl.widgets
    if plan is not None and plan[4] != _WIDGET_GEN[0]:
        plan = None                                  # a shape's own geometry changed: join them again
    if plan is not None and plan[3]:
        p = plan[0]
        for shape, start, count in plan[3]:          # shapes that change with the frame: read again in place
            segs = _read_widget(shape, depsgraph)
            if len(segs) != count:
                plan = None                          # a new edge count: join every shape again
                break
            p[start:start + count] = segs
    if plan is None:
        pts, index, moving, start = [], [], [], 0
        for shape in jl.ctrl_shapes:
            s, m = _widget_segments(shape, depsgraph)
            if m:
                moving.append((shape, start, len(s)))
                at = np.arange(len(s), dtype=np.intc)
            else:
                s, at = _distinct_points(s)
            pts.append(s)
            index.append(at + start)
            start += len(s)
        counts = np.fromiter((len(s) for s in pts), np.intp, len(pts))
        p = np.concatenate(pts) if counts.sum() else np.zeros((0, 3))
        index = np.concatenate(index).astype(np.intc) if index else np.zeros(0, np.intc)
        plan = jl.widgets = (p, np.repeat(np.arange(len(pts)), counts), counts, moving, _WIDGET_GEN[0], index)
    return plan


def _control_lines(ob, jl, w, allm, depsgraph, props=None):
    """(points, joint index per point, int32 line index into the points) of every control's custom shape
    (``shape_lines`` with ``_shape_matrix``, all controls at once), or None. The shapes' own lines are joined once per
    joint list (``_widget_plan``); the pose and the custom shape offset / turn / scale (they can be keyed; ``props``:
    as ``_pose_raw`` read them) are read every time. The controls a display layer hides keep their points but have
    no lines."""
    import numpy as np
    p, owner, _counts, _moving, _gen, index = _widget_plan(jl, depsgraph)
    if not len(p):
        return None
    pbs = ob.pose.bones
    n = len(pbs)
    if props is None:
        props = []
        for prop in ("custom_shape_translation", "custom_shape_rotation_euler", "custom_shape_scale_xyz"):
            a = np.empty(n * 3, np.float32)
            pbs.foreach_get(prop, a)
            props.append(a)
        use = np.zeros(n, bool)
        pbs.foreach_get("use_custom_shape_bone_size", use)
        props.append(use)
    lin, off = _control_placement(jl, w, allm, props, n)
    pts = np.einsum('kij,kj->ki', lin[owner], p) + off[owner]
    got = jl.owners.get("ctrl")
    if got is None or got[0] is not owner:
        if not jl.shown.all():                       # controls a display layer hides draw nothing
            pairs = index.reshape(-1, 2)
            index = np.ascontiguousarray(pairs[jl.shown[jl.ctrl][owner][pairs[:, 0]]].reshape(-1))
        got = jl.owners["ctrl"] = (owner, jl.ctrl[owner], index)
    return pts.astype(np.float32), got[1], got[2]


def _control_placement(jl, w, allm, props, n, which=None):
    """(linear part (C, 3, 3), offset (C, 3)) of the world matrix every control's shape is drawn with (``_shape_matrix``
    in world space; ``props``: the custom shape offset / turn / scale of the ``n`` pose bones as ``_pose_raw`` read
    them). ``which``: control indices: those controls alone (each from its own bone: the same numbers)."""
    import numpy as np
    ctrl_rows, ctrl_src, ctrl_len = jl.rows[jl.ctrl], jl.ctrl_src, jl.ctrl_len
    if which is not None:
        ctrl_rows, ctrl_src, ctrl_len = ctrl_rows[which], ctrl_src[which], ctrl_len[which]
    offset, turn, size = (a.reshape(n, 3)[ctrl_rows].astype(np.float64) for a in props[:3])
    scale = size * np.where(props[3][ctrl_rows], ctrl_len, 1.0)[:, None]
    src = allm[ctrl_src]
    a = w[:3, :3] @ src[:, :3, :3]
    lin = a @ (_euler_xyz(turn) * scale[:, None, :])
    off = (a @ offset[:, :, None])[:, :, 0] + src[:, :3, 3] @ w[:3, :3].T + w[:3, 3]
    return lin, off


def _control_points(jl, w, allm, props, plan, which):
    """(bool per control shape point, float32 points) of the controls ``which`` (indices, sorted) alone: their points
    in ``_control_lines`` and those points worked out again (the same numbers; every control shown)."""
    import numpy as np
    p, owner = plan[0], plan[1]
    chosen = np.zeros(len(jl.ctrl), bool)
    chosen[which] = True
    at = chosen[owner]
    lin, off = _control_placement(jl, w, allm, props, len(props[3]), which)
    local = (np.cumsum(chosen) - 1)[owner[at]]          # position in ``which`` of each point's control
    return at, (np.einsum('kij,kj->ki', lin[local], p[at]) + off[local]).astype(np.float32)


def _box_array(frames, corners):
    """``_box_lines`` of many tubes with the same number of rings: frames (K, F, 4, 4) of each ring, corners
    (K, 4, 3) of each tube in its rings' space. Returns (K, 8 + 16 * (F - 1), 3) end points per tube."""
    import numpy as np
    rings = np.einsum('kfij,kcj->kfci', frames[:, :, :3, :3], corners) + frames[:, :, None, :3, 3]
    edges = np.stack((rings, np.roll(rings, -1, axis=2)), axis=3)                 # (K, F, 4, 2, 3)
    k = len(rings)
    first = edges[:, 0].reshape(k, -1, 3)
    if rings.shape[1] < 2:
        return first
    joins = np.stack((rings[:, :-1], rings[:, 1:]), axis=3)                       # (K, F - 1, 4, 2, 3)
    rest = np.stack((edges[:, 1:], joins), axis=3).reshape(k, -1, 3)             # ring edge i, then join i
    return np.concatenate((first, rest), axis=1)


def _own_lines(ob, jl, w, allm, kind):
    """(points, joint index per point) of Blender's B-Bone / Envelope ``kind`` shape of every drawn joint without a
    custom shape (``bbone_lines`` / ``envelope_lines`` in joint order), or None."""
    import numpy as np
    plain = np.nonzero(jl.plain & jl.shown)[0]
    if not len(plain):
        return None
    pbs, bones = ob.pose.bones, ob.data.bones
    n, nb = len(pbs), len(bones)
    rows, brows = jl.rows[plain], _bone_rows(ob, jl)[plain]
    w3, wt = w[:3, :3], w[:3, 3]
    m = allm[rows]

    def bone_values(prop, dtype=np.float32):
        a = np.empty(nb, dtype)
        bones.foreach_get(prop, a)
        return a[brows].astype(np.float64)

    if kind == 'ENVELOPE':
        hd, tl = np.empty(n * 3, np.float32), np.empty(n * 3, np.float32)
        pbs.foreach_get("head", hd)
        pbs.foreach_get("tail", tl)
        s = max(ob.matrix_world.to_scale())
        f = w3 @ m[:, :3, :3]
        norms = np.linalg.norm(f, axis=1, keepdims=True)
        f = np.divide(f, norms, out=np.zeros_like(f), where=norms > 0)
        h = hd.reshape(n, 3)[rows].astype(np.float64) @ w3.T + wt
        t = tl.reshape(n, 3)[rows].astype(np.float64) @ w3.T + wt
        rh, rt = bone_values("head_radius") * s, bone_values("tail_radius") * s
        k = len(rows)
        ax = np.stack((f[:, :, 0], -f[:, :, 0], f[:, :, 2], -f[:, :, 2]), axis=1)          # (K, 4, 3)
        joins = np.stack((h[:, None] + ax * rh[:, None, None], t[:, None] + ax * rt[:, None, None]), axis=2)
        pts = np.concatenate((_spheres(h, f, rh).reshape(k, -1, 3), _spheres(t, f, rt).reshape(k, -1, 3),
                              joins.reshape(k, -1, 3)), axis=1)
        return pts.reshape(-1, 3).astype(np.float32), np.repeat(plain, pts.shape[1])
    # B-Bone: one box per segment along the bent bone, a straight box for one segment
    x, z, segments = bone_values("bbone_x"), bone_values("bbone_z"), bone_values("bbone_segments", np.intc)
    length = np.empty(n, np.float32)
    pbs.foreach_get("length", length)
    zero = np.zeros_like(x)
    corners = np.stack((np.stack((x, zero, z), 1), np.stack((-x, zero, z), 1), np.stack((-x, zero, -z), 1),
                        np.stack((x, zero, -z), 1)), axis=1)                           # (K, 4, 3)
    base = w @ m
    tip = base.copy()
    tip[:, :3, 3] += base[:, :3, 1] * length[rows][:, None]
    straight = np.stack((base, tip), axis=1)                                            # (K, 2, 4, 4)
    bent = {}
    for k in np.nonzero(segments > 1)[0]:
        pb = pbs[int(rows[k])]
        try:
            bent[int(k)] = np.array([np.array(pb.bbone_segment_matrix(i, rest=False), np.float64)
                                     for i in range(int(segments[k]) + 1)])
        except (RuntimeError, ValueError):
            continue
    if not bent:
        pts = _box_array(straight, corners)
        return pts.reshape(-1, 3).astype(np.float32), np.repeat(plain, pts.shape[1])
    blocks = [None] * len(rows)
    rest = np.array([k for k in range(len(rows)) if k not in bent], np.intp)
    if len(rest):
        for k, b in zip(rest, _box_array(straight[rest], corners[rest])):
            blocks[k] = b
    by_rings = {}
    for k, fr in bent.items():
        by_rings.setdefault(len(fr), []).append(k)
    for ks in by_rings.values():
        frames = base[ks][:, None] @ np.array([bent[k] for k in ks])
        for k, b in zip(ks, _box_array(frames, corners[ks])):
            blocks[k] = b
    sizes = [len(b) for b in blocks]
    return np.concatenate(blocks).astype(np.float32), np.repeat(plain, sizes)


class _Lines:
    """A skeleton's drawn lines without their colours (Object / Pose Mode): centres / frames / radii of the joints,
    the joints with a sphere, the lines before the axes and after them as (points, joint index per point, int32 line
    index into the points or None: the points are segment end points) triples, the lines a click picks (``_parts``
    ``pick``, the same triples) and the control shape lines they were built from."""
    __slots__ = ("centres", "frames", "radii", "plain", "before", "after", "chunks", "plan", "ctrl_at")


def _sphere_owner(jl, plain):
    """(joints with a sphere, joint index per ``_sphere_ring`` point, ``_sphere_index``) of joint list ``jl``, whose
    joints ``plain`` have a sphere; kept on it."""
    import numpy as np
    got = jl.owners.get("spheres")
    if got is None:
        idx = np.flatnonzero(plain)
        got = jl.owners["spheres"] = (idx, np.tile(idx, 3 * (SEGMENTS + 1)), _sphere_index(len(idx)))
    return got


def _owner(jl, part, rows, per, of=None):
    """Joint index per point of ``part``: ``per`` points for each of ``rows`` (indices into ``of``, else joint
    indices). Kept on joint list ``jl`` while ``rows`` stay the same: a part whose points belong to the same joints
    keeps its colours too (``_paint``)."""
    import numpy as np
    got = jl.owners.get(part)
    if got is None or not np.array_equal(got[0], rows):
        got = jl.owners[part] = (rows, np.repeat(rows if of is None else of[rows], per))
    return got[1]


def _lines(ob, scene, depsgraph, jl, kind, raw):
    """``_Lines`` of skeleton ``ob`` drawn as ``kind`` from joint list ``jl`` and pose reading ``raw``."""
    import numpy as np
    stick, own = kind in STICK_TYPES, kind in SHAPE_TYPES
    w, allm, centres, frames, radii = _pose_read(ob, scene, jl, raw)
    g = _Lines()
    g.centres, g.frames, g.radii = centres, frames, radii
    g.plain = plain = jl.plain & jl.shown      # spheres / axes: joints with no custom shape that are shown
    g.before, g.after, g.plan, g.ctrl_at = [], [], None, None
    chunks = None if stick or own else []
    if not (stick or own) and plain.any():
        pts = _sphere_ring(centres[plain], frames[plain], radii[plain])
        got = _sphere_owner(jl, plain)
        g.before.append((pts, got[1], got[2]))
        if chunks is not None:
            chunks.append(g.before[-1])
    if len(jl.ctrl):
        got = _control_lines(ob, jl, w, allm, depsgraph, raw[4])
        g.plan = jl.widgets
        if got is not None:
            g.ctrl_at = len(g.before)
            g.before.append(got)
            if chunks is not None:
                chunks.append(got)
    if own:
        got = _own_lines(ob, jl, w, allm, kind)
        if got is not None:
            g.after.append((got[0], got[1], None))
    elif len(jl.bone_child):
        child, par = jl.bone_child, jl.bone_par
        if stick:
            segs = np.stack((centres[par], centres[child]), axis=1).reshape(-1, 3)
            owner, index = _owner(jl, "sticks", par, 2), None
        else:
            segs, drawn = _bone_array(centres[par], frames[par], radii[par], centres[child], radii[child])
            owner, index = _owner(jl, "bones", drawn, 5, par), _bone_index(len(drawn))
        if len(segs):
            g.after.append((segs.astype(np.float32), owner, index))
            if chunks is not None:
                chunks.append(g.after[-1])
    g.chunks = chunks
    return g


def _moved_bones(raw, old_raw):
    """Bool per pose bone: its matrix or head reads differently (any bit) in pose reading ``raw`` than in
    ``old_raw``; None when something else the lines follow changed (the object's matrix, the joint size, a custom
    shape offset / turn / scale)."""
    import numpy as np
    if (old_raw is None or len(raw[1]) != len(old_raw[1]) or (raw[4] is None) != (old_raw[4] is None)
            or np.float64(raw[3]).tobytes() != np.float64(old_raw[3]).tobytes()
            or raw[2].tobytes() != old_raw[2].tobytes()):
        return None
    if raw[4] is not None and any(x.tobytes() != y.tobytes() for x, y in zip(raw[4], old_raw[4])):
        return None
    n = len(raw[1]) // 3
    return (np.any(raw[0].view(np.uint32).reshape(n, 16) != old_raw[0].view(np.uint32).reshape(n, 16), axis=1)
            | np.any(raw[1].view(np.uint32).reshape(n, 3) != old_raw[1].view(np.uint32).reshape(n, 3), axis=1))


def _lines_moved(ob, scene, jl, kind, raw, g0, old_raw):
    """``_lines`` of pose reading ``raw`` from the lines ``g0`` of ``old_raw`` when a part of the skeleton moved (a
    limb dragged): only the joints whose bones moved are worked out again — each joint's sphere and control shape
    from its own bone, so the numbers are the ones of building every joint — the bones between joints all again.
    None when that isn't the case or not worth it (the object moved, most joints moved, a control shape that changes
    with the frame or hidden, Blender's Stick / B-Bone / Envelope looks)."""
    import numpy as np
    if g0 is None or kind in STICK_TYPES or kind in SHAPE_TYPES:
        return None
    moved = _moved_bones(raw, old_raw)
    if moved is None:
        return None
    ctrl = len(jl.ctrl)
    plan = jl.widgets
    if ctrl and (plan is None or plan is not g0.plan or plan[4] != _WIDGET_GEN[0] or plan[3] or not jl.shown.all()):
        return None
    plain = g0.plain
    joints_moved = np.flatnonzero(moved[jl.rows])
    spheres = joints_moved[plain[joints_moved]]
    controls = np.flatnonzero(moved[jl.ctrl_src]) if ctrl and g0.ctrl_at is not None else np.zeros(0, np.intp)
    if 2 * (len(spheres) + len(controls)) > int(plain.sum()) + ctrl:
        return None                              # most of it moved: build it all
    w, allm, c_moved, f_moved, _r = _pose_read(ob, scene, jl, raw, joints_moved)
    g = _Lines()
    g.centres, g.frames, g.radii, g.plain, g.plan, g.ctrl_at = g0.centres, g0.frames, g0.radii, plain, g0.plan, None
    if len(joints_moved):
        g.centres, g.frames = g0.centres.copy(), g0.frames.copy()
        g.centres[joints_moved], g.frames[joints_moved] = c_moved, f_moved
    g.before, g.after, chunks = [], [], []
    if plain.any():
        pts, owner, index = g0.before[0]
        if len(spheres):
            pts = pts.copy()
            ring = pts.reshape(3, SEGMENTS + 1, -1, 3)        # ``_sphere_ring``: circle, ring point, joint
            ring[:, :, np.cumsum(plain)[spheres] - 1] = _sphere_ring(
                g.centres[spheres], g.frames[spheres], g.radii[spheres]).reshape(3, SEGMENTS + 1, len(spheres), 3)
        g.before.append((pts, owner, index))
        chunks.append(g.before[-1])
    if g0.ctrl_at is not None:
        pts, joint, index = g0.before[g0.ctrl_at]
        if len(controls):
            pts = pts.copy()
            at, new = _control_points(jl, w, allm, raw[4], plan, controls)
            pts[at] = new
        g.ctrl_at = len(g.before)
        g.before.append((pts, joint, index))
        chunks.append(g.before[-1])
    if len(jl.bone_child):
        child, par = jl.bone_child, jl.bone_par
        segs, drawn = _bone_array(g.centres[par], g.frames[par], g.radii[par], g.centres[child], g.radii[child])
        owner = _owner(jl, "bones", drawn, 5, par)
        if len(segs):
            g.after.append((segs.astype(np.float32), owner, _bone_index(len(drawn))))
            chunks.append(g.after[-1])
    g.chunks = chunks
    return g


def _lines_hold(g, jl, kind, raw, old_raw):
    """Lines ``g`` (built from ``jl`` and ``old_raw``) are still the lines of pose reading ``raw``: the same
    readings, the control shapes joined from the same, unchanged geometry and none of them changing with the frame,
    and a look built from the pose and the joint list alone (not Blender's B-Bone / Envelope shapes)."""
    if g is None or kind in SHAPE_TYPES or not _same_raw(raw, old_raw):
        return False
    if len(jl.ctrl):
        plan = jl.widgets
        if plan is None or plan is not g.plan or plan[4] != _WIDGET_GEN[0] or plan[3]:
            return False
    return True


def _paint(jl, g, sel, rgba, prev=None):
    """``_parts`` (before, axes, after) of lines ``g`` in joint colours ``rgba``; the local axes of the selected
    joints ``sel``. ``prev``: (lines, colours, parts) painted before: a part whose lines belong to the same joints in
    the same colours keeps its colour array (a new frame moves the lines, not their colours)."""
    import numpy as np

    def colour(part, k, idx):
        if prev is not None and prev[0] is not None and prev[1] is rgba:
            old = getattr(prev[0], part)
            if k < len(old) and (old[k][1] is idx or (len(old[k][1]) == len(idx) and np.array_equal(old[k][1], idx))):
                return prev[2][0 if part == "before" else 2][1][k]
        return rgba[idx]

    before = ([p for p, _i, _x in g.before], [colour("before", k, i) for k, (_p, i, _x) in enumerate(g.before)],
              [x for _p, _i, x in g.before])
    after = ([p for p, _i, _x in g.after], [colour("after", k, i) for k, (_p, i, _x) in enumerate(g.after)],
             [x for _p, _i, x in g.after])
    axes = ([], [], [])
    if sel:
        key = frozenset(sel)
        got = jl.owners.get("axes")
        if got is None or got[0] != key:             # the selected joints with a sphere and their axes' colours
            plain = g.plain
            picked = np.array([j for j, nm in enumerate(jl.names) if plain[j] and nm in sel], np.intp)
            axis_rgba = np.array([(*rgb, 1.0) for rgb in AXIS_COLORS], np.float32)
            got = jl.owners["axes"] = (key, picked, np.tile(np.repeat(axis_rgba, 2, axis=0), (len(picked), 1)))
        picked = got[1]
        if len(picked):
            c = g.centres[picked]
            ends = c[:, None, :] + g.frames[picked].transpose(0, 2, 1) * g.radii[picked][:, None, None]   # (K, 3, 3)
            axes[0].append(np.stack((np.broadcast_to(c[:, None, :], ends.shape), ends), axis=2)
                           .reshape(-1, 3).astype(np.float32))
            axes[1].append(got[2])
            axes[2].append(None)
    return before, axes, after


class _Build:
    """What a view drew for one skeleton, kept between redraws: ``level`` says what may have changed since (None:
    nothing; 'pose': its pose; 'light': its pose, selection, names or shown bones; 'edit': anything; 'new': build it
    again from scratch)."""
    __slots__ = ("level", "key", "jl", "stamp", "raw", "lines", "sel", "rgba", "parts", "pick", "sig", "registered")

    def __init__(self):
        _forget_build(self)


def _forget_build(b):
    b.level, b.key, b.jl, b.stamp, b.raw, b.lines = 'new', None, None, None, None, None
    b.sel, b.rgba, b.parts, b.pick, b.sig, b.registered = None, None, None, None, None, None


def _build_key(ob, kind):
    """What a build of skeleton ``ob`` in Object / Pose Mode is for: its armature data, look and number of bones."""
    return ob.data.as_pointer(), kind, len(ob.pose.bones)


def _stamp(ob):
    """What of skeleton ``ob``'s joint list an update without a pose or data change can change (a rename, a bone
    collection shown or hidden, a joint's Visibility): its joints' names, hidden flags and shown bone collections."""
    import numpy as np
    pbs = ob.pose.bones
    hide = np.zeros(len(pbs), bool)
    pbs.foreach_get("hide", hide)
    return tuple(pbs.keys()), hide.tobytes(), tuple(c.is_visible_effectively for c in ob.data.collections_all)


def _parts(ob, scene, depsgraph, kind=None, playing=False, pick=None, keep=None):
    """Every line of skeleton ``ob`` as three parts (points list, colours list): the joints' spheres and the
    controls' shapes; the local axes of the selected joints (drawn in perspective views only); the bones (pyramids,
    sticks, or Blender's B-Bone / Envelope shapes). ``kind`` = the display type (default: the skeleton's). Object
    and Pose Mode build them in arrays from one read of the pose; Edit Mode joint by joint.
    ``pick``: a list that gets (joint list, [(points, joint index per point or per joint, points per joint)]) — the
    lines a click picks (``_drawn_pick_lines``) — when they are the drawn Maya joints.
    ``keep``: this skeleton's ``_Build`` from an earlier redraw. What can't have changed since (``keep.level``) is
    used again: the joint list when only the pose may have changed (or when it reads the same), the lines when the
    pose reads the same, the colours when the selection is the same; ``keep`` then holds this build."""
    if kind is None:
        kind = getattr(ob.data, "display_type", 'OCTAHEDRAL')
    if ob.mode == 'EDIT':
        return _joint_parts(ob, scene, depsgraph, kind)
    key = _build_key(ob, kind)
    old = keep if keep is not None and keep.key == key and keep.parts is not None and keep.level != 'new' else None
    stamp = old.stamp if old is not None else None
    if keep is None:
        jl = joint_list(ob, playing)
    elif old is not None and old.level in (None, 'pose'):
        jl = old.jl                                   # only the pose may have changed
    elif old is not None and old.level == 'light' and old.stamp == (stamp := _stamp(ob)):
        jl = old.jl                                   # a selection, a mode, the same names and shown bones
    else:
        stamp = _stamp(ob) if keep is not None else None
        jl = _joint_list(ob)
        if old is not None and _same_list(old.jl, jl):
            jl = old.jl
    if not jl.names:
        parts = ([], [], []), ([], [], []), ([], [], [])
        if keep is not None:
            keep.level, keep.key, keep.jl, keep.stamp, keep.raw, keep.lines = None, key, jl, stamp, None, None
            keep.sel, keep.rgba, keep.parts, keep.pick = None, None, parts, None
        return parts
    raw = _pose_raw(ob, scene, jl)
    same_jl = old is not None and jl is old.jl
    g = old.lines if same_jl and _lines_hold(old.lines, jl, kind, raw, old.raw) else None
    if g is None and same_jl:
        g = _lines_moved(ob, scene, jl, kind, raw, old.lines, old.raw)
    if g is None:
        g = _lines(ob, scene, depsgraph, jl, kind, raw)
    sel, lead = _joint_selection(ob, jl)
    sel_key = (frozenset(sel), lead)
    if same_jl and old.sel == sel_key:
        rgba = old.rgba
    else:
        rgba = _joint_rgba(jl, sel, lead)
    if old is not None and g is old.lines and rgba is old.rgba:
        parts = old.parts
    else:
        parts = _paint(jl, g, sel, rgba, (old.lines, old.rgba, old.parts) if old is not None else None)
    if pick is not None and g.chunks is not None:
        pick.append((jl, g.chunks) if old is None or old.pick is None or old.pick[1] is not g.chunks
                    or old.pick[0] is not jl else old.pick)
    if keep is not None:
        keep.level, keep.key, keep.jl, keep.stamp, keep.raw, keep.lines = None, key, jl, stamp, raw, g
        keep.sel, keep.rgba, keep.parts = sel_key, rgba, parts
        keep.pick = pick[-1] if pick else None
    return parts


def _joint_parts(ob, scene, depsgraph, kind):
    """``_parts`` joint by joint (``skeleton``): Edit Mode."""
    import numpy as np
    before, axes, after = ([], [], []), ([], [], []), ([], [], [])
    js = skeleton(ob, scene)
    if not js:
        return before, axes, after
    stick, own = kind in STICK_TYPES, kind in SHAPE_TYPES
    sel, lead = selection(ob, js)
    col = colours(js, sel, lead)

    def add(part, segs, colour):
        if segs:
            part[0].append(np.array([tuple(v) for v in segs], np.float32))
            part[1].append(np.tile(np.array((*colour, 1.0), np.float32), (len(segs), 1)))
            part[2].append(None)

    spheres, order = _sphere_array(js) if not (stick or own) else (None, ())
    if order:
        before[0].append(spheres)
        before[1].append(np.repeat(np.array([(*col[n], 1.0) for n in order], np.float32), 3 * SEGMENTS * 2,
                                   axis=0))
        before[2].append(None)
    bones, bone_cols = [], []
    if own:
        for name, segs in own_shape_lines(ob, kind).items():
            if name in col and js[name].state != _HIDDEN:
                bones += segs
                bone_cols += [col[name]] * len(segs)
    for j in js.values():
        if j.state == _HIDDEN:
            continue                           # hidden by a display layer: only its parent's bone to it stays
        if j.shape is not None:
            add(before, shape_lines(j.shape[0], j.shape[1], depsgraph), col[j.name])
            continue
        for cn in () if own else j.children:
            child = js[cn]
            if child.shape is None:
                segs = [j.centre, child.centre] if stick else bone_lines(j, child)
                bones += segs
                bone_cols += [col[j.name]] * len(segs)
        if j.name in sel:
            for i in range(3):
                add(axes, [j.centre, j.centre + j.frame.col[i] * j.radius], AXIS_COLORS[i])
    if bones:
        after[0].append(np.array([tuple(v) for v in bones], np.float32))
        after[1].append(np.array([(*c, 1.0) for c in bone_cols], np.float32))
        after[2].append(None)
    return before, axes, after


def _part_arrays(parts, perspective):
    """([points], [colours], [int32 line index or None]) of the ``_parts`` of several skeletons in drawing order, the
    axes only in perspective."""
    pts, cols, index = [], [], []
    for before, axes, after in parts:
        for part in (before, axes, after) if perspective else (before, after):
            pts += part[0]
            cols += part[1]
            index += part[2]
    return pts, cols, index


def _segments(pts, cols, index):
    """Lists ``pts`` / ``cols`` of points and colours with their line indices ``index`` as segment end points and
    their colours (a piece without an index is one already)."""
    return ([p if x is None else p[x] for p, x in zip(pts, index)],
            [c if x is None else c[x] for c, x in zip(cols, index)])


def _join(parts, perspective):
    """(points, colours) float32 arrays of the segment end points of the ``_parts`` of several skeletons, the axes
    only in perspective."""
    import numpy as np
    pts, cols = _segments(*_part_arrays(parts, perspective))
    if not pts:
        return np.zeros((0, 3), np.float32), np.zeros((0, 4), np.float32)
    return np.concatenate(pts), np.concatenate(cols)


def _fast_lines(ob, scene, perspective, depsgraph, stick, playing=False, kind=None):
    """(points, colours) lists of float32 arrays of segment end points of skeleton ``ob`` drawn as ``kind`` (default:
    Maya joints, or sticks with ``stick``): the same lines and colours as the per-joint geometry, built in arrays."""
    parts = _parts(ob, scene, depsgraph, kind or ('STICK' if stick else 'OCTAHEDRAL'), playing)
    return _segments(*_part_arrays([parts], perspective))


_ARMS = {}          # view layer pointer -> (layer generation, its armature objects in its object order)
_LAYER_GEN = [0]    # bumped by every update that can add, remove or re-include objects (Scene / Collection), edits


def armatures(view_layer):
    """The armature objects of ``view_layer`` in its object order. Read again only after an update that can add,
    remove, hide or re-include objects (a Scene or Collection update), an edit, undo or a file load: a redraw doesn't
    walk every object of the scene."""
    ptr = view_layer.as_pointer()
    got = _ARMS.get(ptr)
    if got is None or got[0] != _LAYER_GEN[0]:
        if len(_ARMS) > 16:
            _ARMS.clear()
        got = _ARMS[ptr] = (_LAYER_GEN[0], [ob for ob in view_layer.objects if ob.type == 'ARMATURE'])
    return got[1]


def _view_skeletons(context, space):
    """The skeletons this view shows, in the view layer's order (``context.visible_objects``): from the view layer's
    armatures (``armatures``) in a redraw; a context that isn't Blender's lists its own visible objects."""
    if isinstance(context, bpy.types.Context):
        for _try in range(2):
            try:
                return [ob for ob in armatures(context.view_layer)
                        if ob.visible_get() and ob.visible_in_viewport_get(space)]
            except ReferenceError:              # removed since the list was read
                _ARMS.clear()
    return [ob for ob in context.visible_objects if ob.type == 'ARMATURE' and ob.visible_in_viewport_get(space)]


def transform_op():
    """The transform running in some window (move / rotate / scale, a manipulator drag), else None."""
    from ..operators.manip_scale import TRANSFORM_MODALS
    wm = bpy.context.window_manager
    if wm is None:
        return None
    return next((op for w in wm.windows for op in w.modal_operators
                 if op is not None and op.bl_idname.startswith(TRANSFORM_MODALS)), None)


def transforming():
    """A transform runs in some window (move / rotate / scale, a manipulator drag): until it ends only poses and
    object transforms change, so what is kept while playback runs can be kept too."""
    return transform_op() is not None


def _posing():
    """A transform runs in Object or Pose Mode (not Edit Mode: there it moves points and bones)."""
    return getattr(bpy.context, "mode", None) in {'OBJECT', 'POSE'} and transforming()


SCRUB_MODALS = frozenset({"ALLSET_OT_time_scrub", "ANIM_OT_change_frame"})


def scrubbing():
    """The time is being dragged in a Time Slider / timeline (a scrub): until it ends only the frame changes, as
    while playback runs."""
    wm = bpy.context.window_manager
    if wm is None:
        return False
    return any(op is not None and op.bl_idname in SCRUB_MODALS for w in wm.windows for op in w.modal_operators)


def _playing(context):
    """Playback runs, the time is scrubbed or a pose / object is being dragged: the joint lists and control shapes
    read once are used again."""
    screen = getattr(context, "screen", None)
    return (screen is not None and screen.is_animation_playing) or _posing() or scrubbing()


def view_lines(context):
    """(points, colours) float32 arrays of every joint to draw in this view."""
    scene, depsgraph = context.scene, context.view_layer.depsgraph
    playing = _playing(context)
    parts = [_parts(ob, scene, depsgraph, None, playing) for ob in _view_skeletons(context, context.space_data)]
    return _join(parts, context.region_data.is_perspective)


# --- what changed since the lines were built ------------------------------------------------------------------------
# Every depsgraph update and new frame gets a generation (``_GEN``) and a record of what it can have changed:
# ({skeleton pointer: level}, level of every skeleton or None, the Scene changed). Levels: 'pose' (its pose or place),
# 'light' (its pose, selection, mode, names, display type or shown bone collections: an update that changed none of
# its armature's pose or data), 'frame' (a new frame: its pose, and while nothing plays its joint list too), 'edit'
# (anything about it), 'new' (a control shape's own geometry: build it again from scratch). A generation without a
# record (``changed``, undo) counts as 'edit' for every skeleton.

_LEVELS = {None: 0, 'pose': 1, 'light': 2, 'frame': 3, 'edit': 4, 'new': 5}
_TOUCHED = {}       # generation -> record
_SKEL_EDITS = {}    # skeleton object pointer -> updates that could change its joint list ('edit', 'new')
_SKEL_LIGHT = {}    # skeleton object pointer -> 'light' updates (a selection, the active bone, Object / Pose Mode, ...)
_ALL_EDITS = [0]    # changes that could change every skeleton's joint list (``changed``, undo, load)
_DATA_USERS = {}    # armature data pointer -> pointers of the skeletons built from it
_SHAPE_USERS = {}   # custom shape object session uid -> pointers of the skeletons whose controls draw it
_SHAPE_PTRS = set()   # pointers of those custom shape objects


def _top(a, b):
    return a if _LEVELS[a] >= _LEVELS[b] else b


def _note(levels, every=None, scene=False):
    _GEN[0] += 1
    if len(_TOUCHED) > 256:
        _TOUCHED.clear()                   # no redraw consumed them: a missing record counts as everything
    _TOUCHED[_GEN[0]] = (levels, every, scene)


def edit_stamp(ob):
    """Changes when something may have changed skeleton ``ob``'s joints (not its pose), except a 'light' update
    (``light_stamp``): keys what is derived from them (``operators/joint_labels``)."""
    return _ALL_EDITS[0], _SKEL_EDITS.get(ob.as_pointer(), 0)


def light_stamp(ob):
    """Changes with every 'light' update of skeleton ``ob``: an update of its armature without a pose or data change
    (a selection, the active bone, a switch between Object and Pose Mode, a rename, a bone collection shown or
    hidden, a bone's own hide flag). What is derived from the joints checks the names and flags it reads."""
    return _SKEL_LIGHT.get(ob.as_pointer(), 0)


@bpy.app.handlers.persistent
def _depsgraph_post(_scene, depsgraph):
    """Record which skeletons an update can have changed: those it updated (a selection, a pose, an edit) or whose
    control shapes' geometry it changed; a Scene update (selection, visibility) asks every skeleton to check its
    pose and selection. An update that touches no skeleton (a moved mesh, a material) changes no drawn joint. While a
    pose or an object is dragged only poses change: the joint lists and control shapes are kept."""
    try:
        if _posing():
            moved = _moved_skeletons(depsgraph)
            if moved is None:
                _LAYER_GEN[0] += 1
                _note({}, 'pose')
            elif moved:
                _note(dict.fromkeys(moved, 'pose'))
            else:
                _note({})
            return
        got = _touched(depsgraph)
        if got is None:
            changed(shapes=True)
            return
        touched, scene, rebuilt = got
        if not (touched or scene or rebuilt):
            return
        levels = dict(touched)
        levels.update(dict.fromkeys(rebuilt, 'new'))
        for p, level in levels.items():
            counts = _SKEL_LIGHT if level == 'light' else _SKEL_EDITS
            counts[p] = counts.get(p, 0) + 1
        if levels:
            _EDITS[0] += 1
        if scene:
            _LAYER_GEN[0] += 1
        _note(levels, None, scene)
    except (ReferenceError, AttributeError):
        changed(shapes=True)


def _touched(depsgraph):
    """({skeleton an update touched: 'light' / 'edit'}, the Scene changed, skeletons whose control shapes' own
    geometry it changed), or None when it can have changed anything (objects added, removed, linked: a Collection
    update)."""
    touched, rebuilt, scene = {}, set(), False
    for u in depsgraph.updates:
        id_ = u.id
        if isinstance(id_, bpy.types.Object):
            ob = id_.original
            if ob.type == 'ARMATURE':
                # a shading-only update (a material, the world, the object's colour or render visibility) changes no
                # joint; a selection, mode, pose or data change comes with other flags or none
                if not (u.is_updated_shading and not u.is_updated_transform and not u.is_updated_geometry):
                    ptr = ob.as_pointer()
                    touched[ptr] = _top(touched.get(ptr), 'light')
            elif u.is_updated_geometry:     # a control's custom shape is read again (a mesh the rig deforms isn't one)
                uid = ob.session_uid
                _drop_widget(uid)
                rebuilt |= _SHAPE_USERS.get(uid, set())
        elif isinstance(id_, bpy.types.Armature):
            # a pose, a joint's Visibility, a custom shape, a custom property: the armature updates with flags; a
            # selection, the active bone, a rename, the display type or a bone collection shown / hidden: without
            level = 'edit' if u.is_updated_transform or u.is_updated_geometry or u.is_updated_shading else 'light'
            for ptr in _DATA_USERS.get(id_.original.as_pointer(), ()):
                touched[ptr] = _top(touched.get(ptr), level)
        elif isinstance(id_, bpy.types.Scene):
            scene = True
        elif isinstance(id_, bpy.types.Collection):
            return None
        elif _WIDGETS:
            # other data: a custom shape's mesh / curve edited (also when the shape object isn't in the scene)
            ptr = id_.original.as_pointer()
            for uid in [uid for uid, got in _WIDGETS.items() if got[0] == ptr]:
                _drop_widget(uid)
                rebuilt |= _SHAPE_USERS.get(uid, set())
    return touched, scene, rebuilt


def _moved_skeletons(depsgraph):
    """The skeletons a depsgraph update during a drag touched (those whose pose or place follows the dragged
    control: the dragged one, rigs constrained or parented to it), or None when it touched something else that can
    change drawn lines (a control shape's geometry, data that isn't an object)."""
    out = set()
    for u in depsgraph.updates:
        id_ = u.id
        if isinstance(id_, bpy.types.Object):
            if id_.type == 'ARMATURE':
                out.add(id_.original.as_pointer())
                continue
            if id_.original.as_pointer() in _SHAPE_PTRS:
                return None
            continue                    # a mesh deformed by the rig, a prop: not drawn as a joint
        if isinstance(id_, bpy.types.Armature):
            continue                    # comes with its skeleton object
        return None
    return out


def _since(old, key):
    """What changed between the redraws keyed ``old`` and ``key`` (``_world_key``): ({skeleton pointer: level},
    level of every skeleton or None, the Scene changed, a new frame), or None when anything may have (another scene,
    view layer or Joint Tool state, or a generation without a record)."""
    if old is None or old[2:] != key[2:] or key[0] < old[0]:
        return None
    levels, every, scene = {}, None, False
    for gen in range(old[0] + 1, key[0] + 1):
        rec = _TOUCHED.get(gen)
        if rec is None:
            return None
        for p, level in rec[0].items():
            levels[p] = _top(levels.get(p), level)
        every = _top(every, rec[1])
        scene = scene or rec[2]
    return levels, every, scene, old[1] != key[1]


def changed(shapes=False):
    """Something that can change the drawn joints other than a new frame (a Radius typed, a label, a display layer,
    undo): every skeleton checks its joint list again. ``shapes``: the custom shapes' own geometry may have changed
    too (read them again); an edited shape's geometry otherwise reaches the kit as its own update."""
    _GEN[0] += 1
    _EDITS[0] += 1
    _ALL_EDITS[0] += 1
    _LAYER_GEN[0] += 1
    if shapes:
        _WIDGETS.clear()
        _WIDGET_GEN[0] += 1


@bpy.app.handlers.persistent
def _frame_post(*_args):
    _note({}, 'frame')


def _forget():
    _BUILDS.clear()
    _PARTS.clear()
    _PICK.clear()
    _JOINED.clear()
    _COLOURS.clear()
    _PICK_PLAN.clear()
    _NEAREST[0] = None
    _TOUCHED.clear()
    _DATA_USERS.clear()
    _SHAPE_USERS.clear()
    _SHAPE_PTRS.clear()
    _ARMS.clear()
    _WORLD[0] = None


@bpy.app.handlers.persistent
def _reload(*_args):
    changed(shapes=True)
    _LISTS.clear()
    _forget()


_WORLD = [None]   # what the lines in _PARTS / _JOINED were built for: edit generation, frame, scene, view layer, ...
_PARTS = {}       # skeleton object pointer -> its ``_parts``
_PICK = {}        # skeleton object pointer -> the pick lines of its ``_parts`` (``_parts`` ``pick``) or None
_JOINED = {}      # (skeletons drawn, perspective) -> [points, colours, GPU batch or None, its ``_COLOURS`` entry],
                  # shared by the views
_COLOURS = {}     # (skeletons drawn, perspective) -> [the parts' colour arrays, them joined, their GPU vertex buffer
                  # or None]: kept while the skeletons are drawn in the same colours (a pose or a frame changes points)
_BUILDS = {}      # skeleton object pointer -> its ``_Build`` (what its lines were built from)
_SCALE = [None]   # the scene's (Joint Size, radius unit) the builds used


def _world_key(scene, layer):
    from ..operators import joint_preview
    return (_GEN[0], scene.frame_current, scene.as_pointer(), layer.as_pointer(), joint_preview.running(),
            str(joint_preview.STATE.get("current")))


def _mark(dirt, playing):
    """Mark every kept build with what may have changed since it was built (``_since``)."""
    if dirt is None:
        for b in _BUILDS.values():
            b.level = _top(b.level, 'edit')
        return
    levels, every, scene, frame = dirt
    if scene:
        every = _top(every, 'pose')         # a selection / visibility: selections and places are checked
    if frame:
        every = _top(every, 'frame')
    if every == 'frame':
        every = 'pose' if playing else 'edit'        # a new frame without playback: as an edit (keyed Radius, ...)
    for ptr, b in list(_BUILDS.items()):
        level = _top(levels.get(ptr), every)
        if level == 'new':
            del _BUILDS[ptr]
            _PARTS.pop(ptr, None)
            _PICK.pop(ptr, None)
        elif level is not None:
            b.level = _top(b.level, level)


def _register(ob, b):
    """Remember which armature data and custom shapes the build ``b`` of skeleton ``ob`` reads (``_touched``)."""
    ptr = ob.as_pointer()
    _DATA_USERS.setdefault(ob.data.as_pointer(), set()).add(ptr)
    jl = b.registered = b.jl
    if jl is not None:
        for shape in jl.ctrl_shapes:
            _SHAPE_USERS.setdefault(shape.session_uid, set()).add(ptr)
            _SHAPE_PTRS.add(shape.as_pointer())


def _edit_signature(ob):
    """What skeleton ``ob``'s Edit Mode joints are drawn from that can change without an update reaching the kit:
    the edit bones' matrices, ends, sizes, flags and selection, names and order, Radius and Maya frame values, the
    visible bone collections, the active bone, the world matrix, the display type. (A re-parented bone or a bone
    collection assignment comes with an update.)"""
    import numpy as np
    from ..operators import joints
    data = ob.data
    ebs = data.edit_bones
    n = len(ebs)
    out = [data.display_type, tuple(ebs.keys()), ebs.active.name if ebs.active is not None else None,
           tuple(tuple(r) for r in ob.matrix_world)]
    for prop, size, dtype in (("matrix", 16, np.float32), ("head", 3, np.float32), ("tail", 3, np.float32),
                              ("bbone_x", 1, np.float32), ("bbone_z", 1, np.float32),
                              ("head_radius", 1, np.float32), ("tail_radius", 1, np.float32), ("hide", 1, bool),
                              ("select", 1, bool), ("select_head", 1, bool), ("select_tail", 1, bool)):
        a = np.empty(n * size, dtype)
        ebs.foreach_get(prop, a)
        out.append(a.tobytes())
    colls = data.collections_all
    out.append(tuple(c.is_visible_effectively for c in colls))
    if not all(out[-1]):                       # a hidden bone collection hides its bones: who is in one matters
        out.append(tuple(tuple(eb.collections.keys()) for eb in ebs))
    radius, frame = joints.RADIUS, joints.MAYA_FRAME
    out.append(tuple((eb.get(radius), tuple(q) if (q := eb.get(frame)) is not None else None) for eb in ebs))
    return out


def _joined(context):
    """[points, colours, batch] of this view. The lines of each skeleton are kept until something that can change
    them reaches it (``_depsgraph_post`` / a new frame: only the skeletons concerned are looked at again, and of those
    only what changed is built again) and shared by every 3D View that shows the same skeletons in the same
    projection; a skeleton in Edit Mode is built again when its edit bones read differently."""
    space, scene, layer = context.space_data, context.scene, context.view_layer
    playing = _playing(context)
    key = _world_key(scene, layer)
    if _WORLD[0] != key:
        dirt = _since(_WORLD[0], key)
        scale = _radius_scale(scene)
        if scale != _SCALE[0]:
            dirt = None                        # Joint Size / the unit changed: every joint's size
        _WORLD[0] = key
        _SCALE[0] = scale
        _TOUCHED.clear()
        _mark(dirt, playing)
    obs = _view_skeletons(context, space)
    persp = context.region_data.is_perspective
    shown = (tuple(ob.as_pointer() for ob in obs), persp)
    depsgraph = layer.depsgraph
    fresh = False
    if len(_BUILDS) > 64:
        _forget()
    for ob in obs:
        ptr = ob.as_pointer()
        b = _BUILDS.get(ptr)
        if b is None:
            b = _BUILDS[ptr] = _Build()
        if ob.mode == 'EDIT':
            sig = _edit_signature(ob)
            ekey = ('EDIT', ob.data.as_pointer(), getattr(ob.data, "display_type", 'OCTAHEDRAL'))
            if b.level is not None or b.key != ekey or b.sig != sig or ptr not in _PARTS:
                _forget_build(b)
                b.key, b.sig, b.level = ekey, sig, None
                b.parts = _PARTS[ptr] = _parts(ob, scene, depsgraph, None, playing)
                _PICK[ptr] = None
                fresh = True
            continue
        if b.parts is not _PARTS.get(ptr) or b.key is None or b.key[0] == 'EDIT':
            b.level = 'new'                    # Edit Mode left; lines set by a test
        elif b.level is None:
            continue                           # other data, look or bones come with an update (``_parts`` key)
        before = b.parts
        b.sig = None
        pick = []
        _PARTS[ptr] = _parts(ob, scene, depsgraph, None, playing, pick, b)
        _PICK[ptr] = b.pick
        if b.registered is not b.jl:
            _register(ob, b)
        fresh = fresh or b.parts is not before
    if fresh:
        _JOINED.clear()
    hit = _JOINED.get(shown)
    if hit is None:
        hit = _JOINED[shown] = _join_view(shown, [_PARTS[ob.as_pointer()] for ob in obs], persp)
    if len(_CACHE) > 32:
        _CACHE.clear()
    _CACHE[space.as_pointer()] = (key + (persp,), hit[0], hit[1])
    return hit


def _join_view(shown, parts, persp):
    """[points, colours, None, ``_COLOURS`` entry, int32 line index into the points] of the ``_parts`` of the
    skeletons ``shown`` draws: the points joined again, the colours and the line index kept while every part still
    has the same colour array (``_paint``) and line index."""
    import numpy as np
    pts, cols, index = _part_arrays(parts, persp)
    joined = np.concatenate(pts) if pts else np.zeros((0, 3), np.float32)
    held = _COLOURS.get(shown)
    if (held is None or len(held[0]) != len(cols) or any(a is not b for a, b in zip(held[0], cols))
            or any(a is not b for a, b in zip(held[3], index)) or len(held[1]) != len(joined)):
        if len(_COLOURS) > 16:
            _COLOURS.clear()
        lines, start = [], 0
        for p, x in zip(pts, index):
            lines.append((np.arange(len(p), dtype=np.intc) if x is None else x) + np.intc(start))
            start += len(p)
        held = _COLOURS[shown] = [cols, np.concatenate(cols) if cols else np.zeros((0, 4), np.float32), None, index,
                                  np.concatenate(lines) if lines else np.zeros(0, np.intc), None]
    return [joined, held[1], None, held, held[4]]


def joined_segments(hit):
    """(points, colours) of joined lines ``hit`` (``_joined``) as segment end points (what its line index draws)."""
    return hit[0][hit[4]], hit[1][hit[4]]


_FORMATS = {}       # attribute name -> GPU vertex format of that attribute alone


def _vertex_buffer(name, data):
    """GPU vertex buffer of float32 rows ``data`` as the shader attribute ``name`` alone (filled in one copy)."""
    from gpu.types import GPUVertBuf, GPUVertFormat
    fmt = _FORMATS.get(name)
    if fmt is None:
        fmt = _FORMATS[name] = GPUVertFormat()
        fmt.attr_add(id=name, comp_type='F32', len=data.shape[1], fetch_mode='FLOAT')
    vbo = GPUVertBuf(fmt, len(data))
    vbo.attr_fill(name, data)
    return vbo


def _new_batch(hit):
    """GPU batch of joined lines ``hit`` (``_joined``): the colours' vertex buffer and the line index, made once and
    kept with the colours (``_COLOURS``), and one vertex buffer of the points. The colours come first: Blender draws
    a polyline batch with the colour format of its first vertex buffer (gpu_batch.cc, polyline_draw_workaround). The
    polyline shader reads each segment end through the index, so a point shared by several segments gives each the
    same position and colour as when every segment had its own copy (gpu_batch.cc, GPU_batch_bind_as_resources)."""
    from gpu.types import GPUBatch, GPUIndexBuf
    held = hit[3]
    if held[2] is None:
        held[2] = _vertex_buffer("color", held[1])
    if held[5] is None:
        held[5] = GPUIndexBuf(type='LINES', seq=held[4].reshape(-1, 2))
    batch = GPUBatch(type='LINES', buf=held[2], elem=held[5])
    batch.vertbuf_add(_vertex_buffer("pos", hit[0]))
    return batch


def cached_view_lines(context):
    """``view_lines`` kept until a joint can have changed, shared by the views."""
    return joined_segments(_joined(context))


@bpy.app.handlers.persistent
def _save_pre(*_args):
    try:
        release_all()        # a saved file shows Blender's bones when it opens without the kit
    except (ReferenceError, AttributeError, RuntimeError):
        pass


@bpy.app.handlers.persistent
def _save_post(*_args):
    _tick()


def see_through(space):
    """Joints draw over every surface: X-Ray Joints, a wireframe view (no surface hides a joint, like Maya) or
    X-Ray shading."""
    shading = space.shading
    return bool(space.overlay.show_xray_bone or shading.type == 'WIREFRAME' or shading.show_xray)


def _draw():
    context = bpy.context
    try:
        if not is_maya_view(context.space_data, context.window.workspace):
            return
        hit = _joined(context)
    except (ReferenceError, AttributeError, KeyError, ValueError, RuntimeError):
        return
    if not len(hit[4]):
        return
    import gpu
    region = context.region
    sh = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
    gpu.state.depth_test_set('NONE' if see_through(context.space_data) else 'LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    gpu.state.blend_set('ALPHA')
    try:
        sh.uniform_float("viewportSize", (region.width, region.height))
        sh.uniform_float("lineWidth", LINE_PX * context.preferences.system.pixel_size)
        if hit[2] is None:          # one batch per set of lines, drawn by every view that shows them
            hit[2] = _new_batch(hit)
        hit[2].draw(sh)
    finally:
        gpu.state.blend_set('NONE')
        gpu.state.depth_test_set('NONE')


def HANDLERS():
    h = bpy.app.handlers
    return ((h.save_pre, _save_pre), (h.save_post, _save_post), (h.depsgraph_update_post, _depsgraph_post),
            (h.frame_change_post, _frame_post), (h.load_post, _reload), (h.undo_post, _reload),
            (h.redo_post, _reload), (h.animation_playback_pre, _reload))


def register():
    if not _handle:
        _handle.append(bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW'))
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.2, persistent=True)
    for lst, fn in HANDLERS():
        if fn not in lst:
            lst.append(fn)


def unregister():
    for lst, fn in HANDLERS():
        if fn in lst:
            lst.remove(fn)
    _CACHE.clear()
    _LISTS.clear()
    _WIDGETS.clear()
    _SKEL_EDITS.clear()
    _SKEL_LIGHT.clear()
    _FORMATS.clear()
    _forget()
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    while _handle:
        bpy.types.SpaceView3D.draw_handler_remove(_handle.pop(), 'WINDOW')
    try:
        release_all()
    except (ReferenceError, AttributeError, RuntimeError):
        pass
