# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Freeze Transformations, Reset Transformations and Center Pivot.

The Maya pivot is the
Blender origin; ``delta_location`` plays the part of Maya's pivot offset
(``rotatePivot``/``rotatePivotTranslate``), so the
channels the Channel Box shows (``location``/``rotation``/``scale``) can read
0/0/1 while the pivot stays where it was.

- Freeze = ``cmds.makeIdentity(apply=True, t=1, r=1, s=1, pn=1)``
  bakes into the data, keeps world positions
  and the pivot, applies to the whole hierarchy below the selection. Like Maya, groups and locators
  zero their rotate and scale too, cameras / lights / joints and instances are not frozen, and the
  children of a frozen object get their values in its frame: their parent inverse takes its pivot
  offset out (``frame_inverse``), so they read like Maya's after the freeze, after Unparent and after
  a pivot move.
- Reset = Modify > Reset Transformations: channels back to
  0/0/1 and the pivot back to the frame origin; the geometry stays where the last freeze left it.
- Center Pivot = ``cmds.xform(centerPivots=True)``: pivot to the
  bounding box centre; vertices, translate and children stay.
"""

import bpy
from bpy.props import BoolProperty
from mathutils import Matrix, Vector

from .. import i18n, results

# Object types whose data can absorb a matrix (``ID.transform``).
BAKE_TYPES = {'MESH', 'CURVE', 'SURFACE', 'LATTICE', 'META'}
# Maya freezes rotate and scale of these too (geometry; groups and locators have nothing to bake) ...
FREEZE_TYPES = BAKE_TYPES | {'EMPTY'}
# ... and leaves these as they are (under a frozen parent they only take its change, to stay in place)
KEEP_TYPES = {'CAMERA', 'LIGHT', 'ARMATURE', 'LIGHT_PROBE', 'SPEAKER'}
EPS = 1e-6


def _is_identity(m):
    return all(abs(m[i][j] - (1.0 if i == j else 0.0)) < EPS for i in range(4) for j in range(4))


def _same(a, b):
    return all(abs(a[i][j] - b[i][j]) < EPS for i in range(4) for j in range(4))


def _drives(ob):
    """``ob`` is a handle something else follows: a modifier or constraint (also a bone's) points to it."""
    def points(item):
        return any(p.type == 'POINTER' and getattr(item, p.identifier, None) is ob for p in item.bl_rna.properties)
    for o in bpy.data.objects:
        if any(points(md) for md in o.modifiers) or any(points(c) for c in o.constraints):
            return True
        if o.pose is not None and any(points(c) for pb in o.pose.bones for c in pb.constraints):
            return True
    return False


def plain_empty(ob):
    """A group or locator: an Empty whose rotate and scale Freeze can zero like Maya (it draws axes only and nothing
    follows it; an image plane, a collection instancer or a deformer / IK handle keeps them)."""
    return (ob.type == 'EMPTY' and ob.empty_display_type != 'IMAGE' and ob.instance_type == 'NONE'
            and not _drives(ob))


def frame_inverse(ob):
    """Parent inverse that makes children's values relative to ``ob``'s Maya frame: its pivot offset
    (``delta_location``) taken out, so a frozen group's children read like Maya's (a pivot moved away from the
    frame doesn't move them). Identity when ``ob`` keeps a rotation or scale (the offset is only exact without)."""
    m = ob.matrix_basis.to_3x3()
    if any(abs(m[i][j] - (1.0 if i == j else 0.0)) > EPS for i in range(3) for j in range(3)):
        return Matrix.Identity(4)
    return Matrix.Translation(-Vector(ob.delta_location))


def hierarchy(objects):
    """Selected roots (no selected ancestor) and all their descendants, parents first."""
    chosen = set(objects)
    roots = []
    for ob in objects:
        p = ob.parent
        while p is not None and p not in chosen:
            p = p.parent
        if p is None:
            roots.append(ob)
    out, stack = [], list(reversed(roots))
    while stack:
        ob = stack.pop()
        out.append(ob)
        stack.extend(sorted(ob.children, key=lambda o: o.name, reverse=True))
    return out


def parents_first(objects):
    """``objects`` ordered so that a parent comes before its descendants."""
    def depth(ob):
        d, p = 0, ob.parent
        while p is not None:
            d, p = d + 1, p.parent
        return d
    return sorted(objects, key=depth)


def parent_frame(ob, w_old, w_new):
    """Matrix that maps ``ob.matrix_basis`` to world, after any parent change in ``w_new``.

    Taken from the object itself (``W @ basis⁻¹``), so object, bone and vertex
    parents and the parent inverse are all covered.
    """
    frame = w_old[ob] @ ob.matrix_basis.inverted_safe()
    p = ob.parent
    if p is not None and p in w_new:
        frame = w_new[p] @ w_old[p].inverted_safe() @ frame
    return frame


def clear_rotation(ob):
    ob.rotation_euler = (0.0, 0.0, 0.0)
    ob.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    ob.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
    ob.delta_rotation_euler = (0.0, 0.0, 0.0)
    ob.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)


def set_rotation(ob, quat):
    """Rotation channels = ``quat`` in the object's rotation mode, deltas cleared."""
    ob.delta_rotation_euler = (0.0, 0.0, 0.0)
    ob.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    if ob.rotation_mode == 'QUATERNION':
        ob.rotation_quaternion = quat
    elif ob.rotation_mode == 'AXIS_ANGLE':
        axis, angle = quat.to_axis_angle()
        ob.rotation_axis_angle = (angle, *axis)
    else:
        ob.rotation_euler = quat.to_euler(ob.rotation_mode, ob.rotation_euler)


def bake_into_data(ob, matrix):
    """``ob.data.transform(matrix)`` (single user first); keeps normals pointing out."""
    copied = False
    if ob.data.users > 1:
        ob.data = ob.data.copy()
        copied = True
    if ob.type == 'META':
        ob.data.transform(matrix)
    else:
        ob.data.transform(matrix, shape_keys=True)
    if ob.type == 'MESH' and matrix.to_3x3().determinant() < 0:
        ob.data.flip_normals()  # Maya preserve normals (-pn 1)
    return copied


def freeze(objects, translate=True, rotate=True, scale=True, refuse=()):
    """Freeze ``objects`` and their descendants. Returns (frozen count, data copies, objects not frozen).

    ``refuse``: objects left as they are with everything below them, like Maya's instances; one under a frozen parent
    takes the parent's change into its channels so it stays in place."""
    obs = hierarchy(objects)
    w_old = {ob: ob.matrix_world.copy() for ob in obs}
    w_new = {}
    framed = {}             # fully frozen object -> its children's parent inverse (its Maya frame)
    copies = 0
    skipped, refused = set(), []
    for ob in obs:
        p = ob.parent
        reframe = framed.get(p) if ob.parent_type == 'OBJECT' else None
        if reframe is not None:     # like Maya, the values become relative to the frozen parent's frame
            frame = w_new[p] @ reframe
            moved = True
        else:
            frame = parent_frame(ob, w_old, w_new)
            moved = p in w_new and not _same(w_new[p], w_old[p])
        b_eff = frame.inverted_safe() @ w_old[ob] if moved else ob.matrix_basis.copy()
        keep = ob.type in KEEP_TYPES
        if p in skipped or ob in refuse or keep:
            if p not in skipped:
                if not keep:
                    refused.append(ob)
                if moved:
                    if reframe is not None:
                        ob.matrix_parent_inverse = reframe
                    ob.matrix_basis = b_eff
            if not keep or p in skipped:    # below an instance nothing is frozen; below a camera / light it is
                skipped.add(ob)
            w_new[ob] = w_old[ob]
            continue
        if reframe is not None:
            ob.matrix_parent_inverse = reframe
        bake = ob.type in BAKE_TYPES and ob.data is not None
        full = bake or (ob.type in FREEZE_TYPES and plain_empty(ob))
        t, q, s = b_eff.decompose()

        if translate:
            ob.location = (0.0, 0.0, 0.0)
            ob.delta_location = t           # the pivot stays (Maya rotatePivot)
        else:
            if moved:   # Maya carries the pivot offset into the parent's new frame like the translate
                carry = (frame.inverted_safe() @ w_old[ob] @ ob.matrix_basis.inverted_safe()).to_3x3()
                ob.delta_location = carry @ Vector(ob.delta_location)
            ob.location = t - Vector(ob.delta_location)
        if rotate and full:
            clear_rotation(ob)
        elif moved:
            set_rotation(ob, q)
        if scale and full:
            ob.scale = ob.delta_scale = (1.0, 1.0, 1.0)
        elif moved:
            ob.scale = s
            ob.delta_scale = (1.0, 1.0, 1.0)

        b_new = ob.matrix_basis.copy()
        d = b_new.inverted_safe() @ b_eff
        if bake and not _is_identity(d):
            copies += bake_into_data(ob, d)
        w_new[ob] = frame @ b_new
        if full and translate and rotate and scale:
            framed[ob] = frame_inverse(ob)
    kept = sum(1 for ob in obs if ob.type in KEEP_TYPES and ob not in skipped)
    return len(obs) - len(skipped) - kept, copies, refused


def instanced(ob):
    """An instance Freeze leaves alone, like Maya: an object sharing its data with another one, or a group made by
    (or copied by) Duplicate Special > Instance."""
    from .duplicate import INSTANCE_TAG, is_instance
    if ob.data is not None:
        return is_instance(ob)
    if ob.get(INSTANCE_TAG):
        return True
    return any(o.data is None and o.get(INSTANCE_TAG) == ob.name for o in bpy.data.objects)


def reset(objects, translate=True, rotate=True, scale=True):
    """Maya Reset Transformations: translate / rotate / scale back to 0 / 0 / 1; with translate the pivot goes back
    to the frame origin too (the geometry and the children stay; the geometry is then where the last freeze left
    it)."""
    for ob in parents_first(objects):
        d = Vector(ob.delta_location)
        if translate and d.length > EPS:
            # the pivot offset goes into the data (its place in the frame, as the last freeze left it) and out of
            # the children's parent inverse, so they keep their values in the frame
            if ob.type in BAKE_TYPES and ob.data is not None:
                bake_into_data(ob, Matrix.Translation(d))
            ob.delta_location = (0.0, 0.0, 0.0)
            for ch in ob.children:
                if ch.parent_type == 'OBJECT':
                    ch.matrix_parent_inverse = Matrix.Translation(d) @ ch.matrix_parent_inverse
        if translate:
            ob.location = (0.0, 0.0, 0.0)
        if rotate:
            ob.rotation_euler = (0.0, 0.0, 0.0)
            ob.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            ob.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
        if scale:
            ob.scale = (1.0, 1.0, 1.0)
    return len(objects)


def _bbox_center(corners):
    lo = Vector(tuple(min(c[i] for c in corners) for i in range(3)))
    hi = Vector(tuple(max(c[i] for c in corners) for i in range(3)))
    return (lo + hi) / 2


def _box_corners(lo, hi):
    return [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]


def local_box(ob):
    """(lo, hi) of ``ob``'s own data and all its descendants, axis-aligned in ``ob``'s space, or None (nothing to
    centre on). Like Maya, level by level: each child's box (with everything below it) is made axis-aligned in its
    parent's space, a box of boxes."""
    kids, order, stack = {}, [], [ob]
    while stack:
        o = stack.pop()
        order.append(o)
        kids[o] = list(o.children)
        stack.extend(kids[o])
    boxes = {}
    for o in reversed(order):                 # every child before its parent
        pts = [Vector(v) for v in o.bound_box] if o.type in BAKE_TYPES and o.data is not None else []
        below = [(ch, boxes[ch]) for ch in kids[o] if boxes.get(ch) is not None]
        if below:
            inv = o.matrix_world.inverted_safe()
            for ch, (lo, hi) in below:
                to_parent = inv @ ch.matrix_world
                pts.extend(to_parent @ c for c in _box_corners(lo, hi))
        boxes[o] = (Vector(tuple(min(p[i] for p in pts) for i in range(3))),
                    Vector(tuple(max(p[i] for p in pts) for i in range(3)))) if pts else None
    return boxes[ob]


def local_center(ob):
    """Bounding-box centre in ``ob``'s local space, or None (nothing to centre on).

    Like Maya, the box holds ``ob``'s own data and all its descendants', in ``ob``'s own space (``local_box``).
    """
    box = local_box(ob)
    return None if box is None else (box[0] + box[1]) / 2


def shift_pivot(ob, c):
    """Move ``ob``'s origin by the local offset ``c``: data, translate and children stay (like Maya, the children
    keep their values too: the parent inverse takes the move)."""
    w_old = {ob: ob.matrix_world.copy()}
    for ch in ob.children:
        w_old[ch] = ch.matrix_world.copy()
    lin = ob.matrix_basis.to_3x3()
    ob.delta_location = Vector(ob.delta_location) + lin @ c
    if ob.type in BAKE_TYPES and ob.data is not None:
        bake_into_data(ob, Matrix.Translation(-c))
    w_new = {ob: w_old[ob] @ Matrix.Translation(c)}
    for ch in ob.children:
        if ch.parent_type == 'OBJECT':
            ch.matrix_parent_inverse = Matrix.Translation(-c) @ ch.matrix_parent_inverse
            continue
        frame = parent_frame(ch, w_old, w_new)
        b_new = frame.inverted_safe() @ w_old[ch]
        diff = b_new.translation - ch.matrix_basis.translation
        ch.delta_location = Vector(ch.delta_location) + diff


def center_pivot(context, objects):
    done = 0
    for ob in parents_first(objects):
        context.view_layer.update()  # bound_box / matrix_world after the previous object
        c = local_center(ob)
        if c is None or c.length < EPS:
            continue
        shift_pivot(ob, c)
        done += 1
    return done


class _SelectedObjectsOp:
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def objects(self, context):
        obs = list(context.selected_objects)
        if not obs:
            self.report({'WARNING'}, "Nothing selected")
        return obs


class ALLSET_OT_freeze_transform(_SelectedObjectsOp, bpy.types.Operator):
    """Bake translate/rotate/scale into the geometry: the channels read 0/0/1 and the
    pivot stays in place (Maya Modify > Freeze Transformations)"""
    bl_idname = "allset.freeze_transform"
    bl_label = "Freeze Transformations"

    translate: BoolProperty(name="Translate", default=True)
    rotate: BoolProperty(name="Rotate", default=True)
    scale: BoolProperty(name="Scale", default=True)

    def execute(self, context):
        from .duplicate import unshare
        from .group import selected_objects
        obs = selected_objects(context)       # with groups a 3D View hides by its Locators filter
        if not obs:
            self.report({'WARNING'}, "Nothing selected")
            return {'CANCELLED'}
        from .. import preferences
        refuse = ()
        if preferences.get(context).unshare_instances:     # an instance becomes a plain object, then freezes
            copies = unshare(obs)
        else:                                               # like Maya: an instance is not frozen (a warning)
            copies = 0
            refuse = {ob for ob in hierarchy(obs) if instanced(ob)}
        count, baked, refused = freeze(obs, self.translate, self.rotate, self.scale, refuse)
        copies += baked
        if refused:
            self.report({'WARNING'}, i18n.compose("Not frozen, an instance shares its geometry: {names}",
                                                  names=", ".join(ob.name for ob in refused)))
        msg = f"Froze {count} object(s)"
        if copies:
            msg += f"; {copies} shared data block(s) made single user"
        results.result(self, msg)
        return {'FINISHED'}


class ALLSET_OT_reset_transform(_SelectedObjectsOp, bpy.types.Operator):
    """Set translate/rotate/scale back to 0/0/1, i.e. to the last frozen state
    (Maya Modify > Reset Transformations)"""
    bl_idname = "allset.reset_transform"
    bl_label = "Reset Transformations"

    translate: BoolProperty(name="Translate", default=True)
    rotate: BoolProperty(name="Rotate", default=True)
    scale: BoolProperty(name="Scale", default=True)

    def execute(self, context):
        obs = self.objects(context)
        if not obs:
            return {'CANCELLED'}
        reset(obs, self.translate, self.rotate, self.scale)
        return {'FINISHED'}


COMPONENT_MODES = {'EDIT_MESH', 'EDIT_CURVE', 'EDIT_SURFACE', 'EDIT_LATTICE'}


def selected_points(ob):
    """Local coordinates of the selected points (vertices, CVs, lattice points) of ``ob``'s data, read in object
    mode (the edit data has been written back)."""
    data = ob.data
    if ob.type == 'MESH':
        return [v.co.copy() for v in data.vertices if v.select and not v.hide]
    if ob.type in ('CURVE', 'SURFACE'):
        pts = []
        for spline in data.splines:
            pts += [Vector(p.co) for p in spline.bezier_points if p.select_control_point]
            pts += [Vector(p.co[:3]) for p in spline.points if p.select]
        return pts
    if ob.type == 'LATTICE':
        return [Vector(p.co_deform) for p in data.points if p.select]
    return []


def center_pivot_components(context):
    """Maya Center Pivot in component mode: each object whose components are selected gets its pivot on the centre
    of their bounding box; with no component selected every edited object centres on its whole bounding box. Ends
    in object mode with those objects selected, as Maya does. Returns the objects."""
    from . import hold
    if hold.COMPONENT.on:
        hold.COMPONENT.finish(context)
    edited = [ob for ob in context.objects_in_mode if ob.type in BAKE_TYPES]
    active = context.view_layer.objects.active
    bpy.ops.object.mode_set(mode='OBJECT')
    if hold.COMPONENT.custom:
        hold.COMPONENT.leave_edit(context)      # a component pivot ends with component mode
    picked = {ob: selected_points(ob) for ob in edited}
    targets = [ob for ob in edited if picked[ob]] or edited
    for ob in parents_first(targets):
        context.view_layer.update()
        pts = picked[ob]
        c = _bbox_center(pts) if pts else local_center(ob)
        if c is not None and c.length >= EPS:
            shift_pivot(ob, c)
    for ob in context.selected_objects:
        ob.select_set(False)
    for ob in targets:
        ob.select_set(True)
    if targets and active not in targets:
        context.view_layer.objects.active = targets[0]
    return targets


class ALLSET_OT_center_pivot(_SelectedObjectsOp, bpy.types.Operator):
    """Move the pivot (origin) to the centre of the bounding box without moving the
    geometry or changing translate (Maya Modify > Center Pivot)"""
    # In component mode the box is the selected components' (center_pivot_components).
    bl_idname = "allset.center_pivot"
    bl_label = "Center Pivot"

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' or context.mode in COMPONENT_MODES

    def execute(self, context):
        if context.mode in COMPONENT_MODES:
            if not center_pivot_components(context):
                self.report({'WARNING'}, "Nothing selected")
                return {'CANCELLED'}
            return {'FINISHED'}
        obs = self.objects(context)
        if not obs:
            return {'CANCELLED'}
        center_pivot(context, obs)
        return {'FINISHED'}


classes = (ALLSET_OT_freeze_transform, ALLSET_OT_reset_transform, ALLSET_OT_center_pivot)
