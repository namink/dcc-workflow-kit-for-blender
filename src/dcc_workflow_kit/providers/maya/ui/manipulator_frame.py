# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the Maya manipulator sits and how its axes point: the selected points in Object / Edit Mode (meshes,
lattices, curves and surfaces), the centre for Blender's pivot point setting (``center_of``), the per-tool orientation
(``slot_type``, ``axes_of``, ``gimbal_axes``), pivot edit mode (``pivot_edit``, ``pivot_axes``) and ``pivot_frame``,
which operators use for Shift+MMB axis picks, snapping and scaling. Re-exported by manipulator.py.
"""

import bmesh
from mathutils import Matrix, Vector

# Orientation slot per tool kind (Blender: 0 default, 1 move, 2 rotate, 3 scale).
SLOT = {'TRANSLATE': 1, 'ROTATE': 2, 'RESIZE': 3}


# --- where and how the manipulator sits --------------------------------------------------------

def _lattice_points(ob):
    """Selected, shown points of a lattice in edit mode, in object space (where the transform moves them)."""
    return [p.co_deform.copy() for p in ob.data.points if p.select and not getattr(p, "hide", False)]


def _curve_points(ob):
    """Selected, shown control points of a curve / surface in edit mode, in object space: Bezier keys and handles
    (each by its own selection, like Blender's transform), NURBS / poly CVs."""
    out = []
    for spline in ob.data.splines:
        if spline.type == 'BEZIER':
            for bp in spline.bezier_points:
                if bp.hide:
                    continue
                for flag, co in ((bp.select_control_point, bp.co), (bp.select_left_handle, bp.handle_left),
                                 (bp.select_right_handle, bp.handle_right)):
                    if flag:
                        out.append(co.copy())
        else:
            out += [p.co.xyz for p in spline.points if p.select and not p.hide]
    return out


def _edit_points(context):
    """World positions of the selected vertices of the meshes (or points of the lattices) in edit mode, and the
    active element's centre (or None)."""
    pts, active = [], None
    obs = context.objects_in_mode_unique_data or ([context.edit_object] if context.edit_object else [])
    for ob in obs:
        if ob is not None and ob.type in ('LATTICE', 'CURVE', 'SURFACE'):
            mw = ob.matrix_world
            pts += [mw @ co for co in (_lattice_points(ob) if ob.type == 'LATTICE' else _curve_points(ob))]
            continue
        if ob is None or ob.type != 'MESH':
            continue
        bm = bmesh.from_edit_mesh(ob.data)
        mw = ob.matrix_world
        pts += [mw @ v.co for v in bm.verts if v.select and not v.hide]
        if ob == context.edit_object and active is None:
            el = bm.select_history.active
            if isinstance(el, bmesh.types.BMVert):
                active = mw @ el.co
            elif isinstance(el, bmesh.types.BMEdge):
                active = mw @ ((el.verts[0].co + el.verts[1].co) / 2)
            elif isinstance(el, bmesh.types.BMFace):
                active = mw @ el.calc_center_median()
    return pts, active


def _object_points(context):
    from ..operators import group           # groups whose locator axes are hidden keep their handles
    obs = group.selected_objects(context)
    active = context.view_layer.objects.active
    act = active.matrix_world.translation.copy() if active is not None and active in obs else None
    return [ob.matrix_world.translation.copy() for ob in obs], act


def center_of(points, active, pivot_point, cursor):
    """Manipulator position for Blender's pivot point setting (what the transform uses)."""
    if not points:
        return None
    if pivot_point == 'CURSOR':
        return cursor.copy()
    if pivot_point == 'ACTIVE_ELEMENT' and active is not None:
        return active
    if pivot_point == 'BOUNDING_BOX_CENTER':
        lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        return (lo + hi) / 2
    total = Vector()
    for p in points:
        total += p
    return total / len(points)


def slot_type(scene, kind):
    """Orientation type the manipulator of ``kind`` uses (a per-tool slot, else the default)."""
    slots = scene.transform_orientation_slots
    t = slots[SLOT[kind]].type
    return slots[0].type if t == 'DEFAULT' else t


def pivot_frame(context, kind):
    """(centre, 3x3 axes, orientation type) of the manipulator of ``kind``: where it draws and how its axes point
    (Shift+MMB picks one of these axes). Centre None = nothing selected."""
    scene = context.scene
    otype = slot_type(scene, kind)
    if context.mode != 'OBJECT':
        pts, act = _edit_points(context)
    else:
        pts, act = _object_points(context)
    center = follow_centre(context, center_of(pts, act, scene.tool_settings.transform_pivot_point,
                                              scene.cursor.location))
    if pivot_edit(context) and context.active_object is not None:
        from ..operators import pivot
        return center, pivot_axes(context), pivot.ORIENT_NAME
    return center, axes_of(context, otype, context.region_data), otype


def follow_centre(context, center):
    """``center`` plus the offset of a Move drag a placed component pivot has not followed yet (it moves with the
    components, operators/pivot_follow.py): the manipulator goes along with them during the drag."""
    if center is None or context.mode != 'EDIT_MESH':
        return center
    from ..operators import pivot_follow
    offset = pivot_follow.pending(context)
    return center if offset is None else center + offset


def pivot_axes(context):
    """World axes of the pivot being edited: the lead object's pivot, or the component pivot (the 3D cursor)."""
    if context.mode == 'EDIT_MESH':
        return context.scene.cursor.matrix.to_3x3().normalized()
    from ..operators import pivot
    return pivot.axes_for(context.active_object)


def _edit_normal_axes(context):
    """Approximation of Blender's NORMAL orientation of the selection."""
    ob = context.edit_object
    if ob is None or ob.type != 'MESH':
        return None
    bm = bmesh.from_edit_mesh(ob.data)
    n = Vector()
    faces = [f for f in bm.faces if f.select]
    for f in faces:
        n += f.normal
    if n.length < 1e-9:
        for v in bm.verts:
            if v.select:
                n += v.normal
    if n.length < 1e-9:
        return None
    nm = ob.matrix_world.to_3x3().inverted_safe().transposed()
    z = (nm @ n).normalized()
    edges = [e for e in bm.edges if e.select] or [e for f in faces for e in f.edges]
    t = None
    if edges:
        e = max(edges, key=lambda e: e.calc_length())
        t = ob.matrix_world.to_3x3() @ (e.verts[1].co - e.verts[0].co)
        t = t - z * t.dot(z)
    if t is None or t.length < 1e-9:
        t = Vector((0, 0, 1)) if abs(z.z) < 0.9 else Vector((0, 1, 0))
        t = t - z * t.dot(z)
    y = t.normalized()
    x = y.cross(z).normalized()
    return Matrix((x, y, z)).transposed()


def axes_of(context, otype, rv3d=None):
    """3x3 world axes of an orientation type (columns = X, Y, Z)."""
    ident = Matrix.Identity(3)
    active = context.view_layer.objects.active
    if otype == 'GLOBAL':
        return ident
    if otype == 'VIEW' and rv3d is not None:
        return rv3d.view_rotation.to_matrix()
    if otype == 'CURSOR':
        return context.scene.cursor.matrix.to_3x3().normalized()
    if otype == 'NORMAL' and context.mode == 'EDIT_MESH':
        m = _edit_normal_axes(context)
        if m is not None:
            return m
    if otype == 'PARENT':
        if active is not None and active.parent is not None:
            return active.parent.matrix_world.to_3x3().normalized()
        return ident
    if otype in ('LOCAL', 'NORMAL', 'GIMBAL'):
        return active.matrix_world.to_3x3().normalized() if active is not None else ident
    custom = context.scene.transform_orientation_slots[0].custom_orientation
    for slot in context.scene.transform_orientation_slots:
        if slot.type == otype and slot.custom_orientation is not None:
            custom = slot.custom_orientation
            break
    if custom is not None and custom.name == otype:
        return custom.matrix.copy().normalized()
    return ident


def _axis_rot(axis):
    """Rotation taking local +Z to the frame axis ``axis``."""
    if axis == 'X':
        return Matrix.Rotation(1.5707963267948966, 3, 'Y')
    if axis == 'Y':
        return Matrix.Rotation(-1.5707963267948966, 3, 'X')
    return Matrix.Identity(3)


def _ring_rot(axes, axis):
    """Rotation taking local +Z to column ``axis`` of ``axes`` (which need not be orthogonal: Gimbal rings)."""
    z = axes.col['XYZ'.index(axis)].normalized()
    return z.to_track_quat('Z', 'Y').to_matrix()


def gimbal_axes(ob):
    """World axes (columns X, Y, Z) of ``ob``'s Euler rotation channels: each axis turned by the rotations applied
    after it. Quaternion / axis-angle rotations have no gimbal: the object's own axes."""
    mode = ob.rotation_mode
    if mode not in ('XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'):
        return ob.matrix_world.to_3x3().normalized()
    parent = (ob.matrix_world @ ob.matrix_basis.inverted_safe()).to_3x3().normalized()
    e = ob.rotation_euler
    cols = [None, None, None]
    m = parent.copy()
    for axis in reversed(mode):          # the last applied rotation turns the earlier axes
        i = 'XYZ'.index(axis)
        cols[i] = m.col[i].copy()
        m = m @ Matrix.Rotation(e[i], 3, axis)
    return Matrix((cols[0], cols[1], cols[2])).transposed()


def pivot_edit(context):
    """A pivot is being edited (D / Insert): the object pivot (Affect Only Origins) or the component pivot."""
    if context.mode == 'OBJECT':
        return context.scene.tool_settings.use_transform_data_origin
    if context.mode == 'EDIT_MESH':
        from ..operators import hold
        return hold.COMPONENT.on
    return False


def _has_selection(context):
    if context.mode == 'OBJECT':
        from ..operators import group
        return bool(group.selected_objects(context))
    for ob in context.objects_in_mode_unique_data or ():
        if ob.type == 'MESH' and ob.data.total_vert_sel:
            return True
        if ob.type == 'LATTICE' and _lattice_points(ob):
            return True
        if ob.type in ('CURVE', 'SURFACE') and _curve_points(ob):
            return True
    return False
