# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit Mesh > Duplicate (Maya's Duplicate Face, a polyChipOff node with Duplicate on).

Like Maya: the selected faces are copied in place and the copies are selected. Keep Faces Together (on by default,
like Maya) keeps copied faces that share a vertex joined at one copied vertex; off: each face is a piece of its own.
Offset moves every edge of each copy inward in the face's plane (negative: outward). The node's
manipulator, In-View Editor and Channel Box INPUTS (operators/extrude_record.py records, the extrude manipulator)
then move the copies: Local Translate / Local Rotate / Local Scale act on each copy in its own frame (Z = its
normal, X = world X projected into it) about its own centre, Translate / Rotate / Scale act in world space about
the centre of the selected faces' bounding box. Order: local scale, offset, local rotate, local translate, then
world scale, rotate and translate. A vertex the joined copies share takes the mean of where each of its faces puts it.

Duplicate Options: Separate duplicated faces (on by default, like Maya) splits the mesh into one object per piece
afterwards (Mesh > Separate: the pieces become ``polySurfaceN`` under a group with the mesh's name); the copies are
then selected with the Move Tool, so the manipulator moves them. Off: the copies stay in the mesh with the node's
manipulator. Offset is the window's second value.
"""

import bmesh
import bpy
from bpy.props import BoolProperty, FloatProperty
from mathutils import Euler, Matrix, Vector

from .. import undo_steps
from . import extrude, move_component, units

AXES = move_component.AXES
FIELDS = move_component.WORLD + move_component.LOCAL_T + move_component.LOCAL_RS + ("offset",)
LABELS = dict(move_component.LABELS, offset="Offset")
DEFAULTS = {f: (1.0 if "scale" in f else 0.0) for f in FIELDS}
IN_VIEW = ("offset",) + move_component.LOCAL_T
NOTHING = "polyChipOff works only on polygonal faces."


def _inset(points, normal, amount):
    """Corners of a polygon after moving each edge ``amount`` inward in its plane (negative: outward)."""
    n = len(points)
    out = []
    for i, p in enumerate(points):
        prev_p, next_p = points[i - 1], points[(i + 1) % n]
        e1, e2 = (p - prev_p), (next_p - p)
        if e1.length < 1e-12 or e2.length < 1e-12:
            out.append(p.copy())
            continue
        in1, in2 = normal.cross(e1.normalized()), normal.cross(e2.normalized())
        d = 1.0 + in1.dot(in2)
        out.append(p + (in1 + in2) * (amount / d) if d > 1e-6 else p + in1 * amount)
    return out


def duplicate(bm, params, unit=1.0, matrix=None, direction=extrude.WORLD_X, fallback=extrude.MAYA_Z,
              keep_faces_together=True):
    """Copy the selected faces of ``bm`` as separate pieces, select the copies and place them by ``params`` (lengths
    in Maya units, ``unit`` = mesh length of one; ``matrix`` = the object's world matrix; ``direction`` /
    ``fallback`` = world X / Maya Z in mesh space). Returns the copies' vertices."""
    faces = [f for f in bm.faces if f.select and not f.hide]
    if not faces:
        return []
    g = lambda k: params.get(k, DEFAULTS[k])            # noqa: E731
    mw = matrix if matrix is not None else Matrix.Identity(4)
    inv = mw.inverted_safe()
    world = [mw @ v.co for f in faces for v in f.verts]
    lo = Vector(tuple(min(p[i] for p in world) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in world) for i in range(3)))
    pivot_w = (lo + hi) / 2
    copies = []
    shared = {}
    for f in faces:
        if keep_faces_together:
            verts = [shared.get(v) or shared.setdefault(v, bm.verts.new(v.co, v)) for v in f.verts]
        else:
            verts = [bm.verts.new(v.co, v) for v in f.verts]
        nf = bm.faces.new(verts, f)
        for old, new in zip(f.loops, nf.loops):
            new.copy_from(old)
        copies.append(nf)
    for seq in (bm.verts, bm.edges, bm.faces):
        for el in seq:
            el.select = False
    for nf in copies:
        nf.select_set(True)
    bm.select_flush(True)
    bm.normal_update()
    local_r = Euler([g(f"local_rotate_{a}") * 3.141592653589793 / 180.0 for a in AXES], 'XYZ').to_matrix()
    local_s = Matrix.Diagonal([g(f"local_scale_{a}") for a in AXES])
    world_rs = (Euler([g(f"rotate_{a}") * 3.141592653589793 / 180.0 for a in AXES], 'XYZ').to_matrix()
                @ Matrix.Diagonal([g(f"scale_{a}") for a in AXES]))
    shift = Vector([g(f"translate_{a}") for a in AXES]) * unit
    lt = Vector([g(f) for f in move_component.LOCAL_T]) * unit
    offset = g("offset") * unit
    placed = {}                 # copied vertex -> its place from each of its faces
    for nf in copies:
        normal = nf.normal.copy()
        x, y = extrude.face_axes(normal, direction, fallback)
        frame = Matrix((x, y, normal)).transposed()      # local -> mesh (columns X, Y, Z)
        rot = frame @ local_r @ frame.transposed()
        points = [v.co.copy() for v in nf.verts]
        centre = sum(points, Vector()) / len(points)
        scale = frame @ local_s @ frame.transposed()
        points = [centre + scale @ (p - centre) for p in points]
        if offset:
            points = _inset(points, normal, offset)
        centre = sum(points, Vector()) / len(points)
        move = x * lt.x + y * lt.y + normal * lt.z
        for v, p in zip(nf.verts, points):
            placed.setdefault(v, []).append(centre + rot @ (p - centre) + move)
    moved = []
    for v, ps in placed.items():
        p = sum(ps, Vector()) / len(ps)
        v.co = inv @ (pivot_w + world_rs @ (mw @ p - pivot_w) + shift)
        moved.append(v)
    bm.normal_update()
    return moved


def _build(bm, params, unit, ob=None):
    axes = extrude.mesh_axes(ob) if ob is not None else {}
    return duplicate(bm, params, unit, ob.matrix_world if ob is not None else None, **axes)


SPEC = extrude.add_spec(extrude.Spec(
    'CHIP_OFF', "polyChipOff", FIELDS, {f: LABELS[f] for f in FIELDS}, dict(DEFAULTS), {f: "NONE" for f in FIELDS},
    "local_translate_z", "duplicate_face_edit", _build, with_object=True, view_fields=IN_VIEW, component='FACE',
    full_manip=True))


COPY = "allset_duplicate_copy"     # face attribute marking the copies while the mesh is separated


def _separate_copies(context, obs):
    """Separate duplicated faces: every mesh in ``obs`` split into one object per piece; the copies (the pieces
    with the ``COPY`` mark) end up selected and active, in object mode with the Move Tool."""
    from . import mesh_maya
    bpy.ops.object.mode_set(mode='OBJECT')
    copies = []
    for ob in obs:
        _grp, pieces = mesh_maya.separate(context, ob)
        for piece in pieces:
            attr = piece.data.attributes.get(COPY)
            if attr is None:
                continue
            if any(d.value for d in attr.data):
                copies.append(piece)
            piece.data.attributes.remove(attr)
    for o in context.selected_objects:
        o.select_set(False)
    for p in copies:
        p.select_set(True)
    if copies:
        context.view_layer.objects.active = copies[0]
    _move_tool(context)
    return copies


def _move_tool(context):
    """Maya shows a manipulator after the command: the Move Tool in the 3D Views of the window."""
    win = context.window
    if win is None:
        return
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            with context.temp_override(window=win, area=area, region=region):
                try:
                    bpy.ops.wm.tool_set_by_id(name="builtin.move")
                except RuntimeError:
                    pass
            return


class ALLSET_OT_duplicate_face(bpy.types.Operator):
    """Copy the selected faces in place (Maya Edit Mesh > Duplicate): each face a piece of its own, moved with the
    manipulator; press and hold the menu item for the Duplicate Face Options"""
    bl_idname = "allset.duplicate_face"
    bl_label = "Duplicate"
    bl_options = {'REGISTER', 'UNDO'}

    separate: BoolProperty(name="Separate duplicated faces", default=True,
                           description="Make each copied piece an object of its own")
    offset: FloatProperty(name="Offset", default=0.0, soft_min=-2.0, soft_max=2.0, min=-100.0, max=100.0,
                          description="Move the edges of each copy inward (negative: outward), in Maya units")
    option_box: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}

    def invoke(self, context, event):
        if self.option_box:
            return context.window_manager.invoke_props_dialog(self, title="Duplicate Face Options",
                                                              confirm_text="Duplicate", width=360)
        return self.execute(context)

    def draw(self, context):
        lay = self.layout
        lay.use_property_split = True
        col = lay.column(heading="Settings")
        col.prop(self, "separate")
        col.prop(self, "offset")

    def execute(self, context):
        if context.mode != 'EDIT_MESH':
            self.report({'WARNING'}, NOTHING)
            return {'CANCELLED'}
        unit = units.maya_unit(context.scene)
        params = dict(DEFAULTS, offset=self.offset)
        done = []
        for ob in context.objects_in_mode_unique_data:
            if ob.type != 'MESH':
                continue
            bm = bmesh.from_edit_mesh(ob.data)
            if not any(f.select and not f.hide for f in bm.faces):
                continue
            if self.separate:
                _build(bm, params, unit, ob)
                mark = bm.faces.layers.int.get(COPY) or bm.faces.layers.int.new(COPY)
                for f in bm.faces:
                    f[mark] = int(f.select)
                bmesh.update_edit_mesh(ob.data)
                done.append(ob)
            elif extrude.record_new(context, ob, bm, SPEC, params, unit) is not None:
                done.append(ob)
        if not done:
            self.report({'WARNING'}, NOTHING)
            return {'CANCELLED'}
        if self.separate:
            _separate_copies(context, done)
        return {'FINISHED'}


def _edit_props():
    return {f: FloatProperty(name=LABELS[f], default=DEFAULTS[f], options={'SKIP_SAVE'},
                             description=LABELS[f] + (" (degrees)" if "rotate" in f else ""))
            for f in FIELDS}


class _EditProps:
    __annotations__ = _edit_props()


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_duplicate_face_edit(_EditProps, bpy.types.Operator):
    """Change the last Duplicate (Maya: edit the polyChipOff node). Blender keeps no edit-mode history, so only the
    last one can be changed"""
    bl_idname = "allset.duplicate_face_edit"
    bl_label = "polyChipOff"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}

    def _params(self, spec):
        return {f: getattr(self, f) for f in spec.fields}

    def execute(self, context):
        if context.mode == 'OBJECT':
            ok = extrude.edit_from_object_mode(context, "duplicate_face_edit", self._params)
            return {'FINISHED'} if ok else {'CANCELLED'}
        unit = units.maya_unit(context.scene)
        done = 0
        for ob in context.objects_in_mode_unique_data:
            rec = extrude.RECORDS.get(ob.name)
            if rec is not None and rec.spec is SPEC and rec.pre is not None and (
                    rec.live or extrude.current(ob) is not None):
                done += bool(extrude.run(ob, rec, self._params(rec.spec), unit))
        if not done:
            self.report({'WARNING'}, "No Duplicate to change: " + extrude.NOTICE)
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (ALLSET_OT_duplicate_face, ALLSET_OT_duplicate_face_edit)
