# SPDX-License-Identifier: GPL-3.0-or-later
"""Modern Smart Extrude, independent of Maya's legacy Shift-drag extrusion.

A gesture freezes its original mesh and pivot. Every preview starts from that
snapshot; Boolean results never feed back into the sweep. Cancellation and failed
validation restore the original mesh including its component selection.
"""
import math
import time
import uuid

import bmesh
import bpy
from bpy_extras import view3d_utils
from mathutils import Euler, Matrix, Vector
from mathutils.geometry import intersect_line_plane

from . import extrude, hold, pivot, smart_geometry, units
from .. import undo_steps

TOOL = "allset.smart_extrude_tool"
DRAG = None
RECORDS = {}
FIELDS = ('translation', 'rotation', 'scale', 'orientation', 'together')
FRAME_INTERVAL = 1/60


def active(context):
    if context.mode != 'EDIT_MESH' or context.workspace is None:
        return False
    tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
    return tool is not None and tool.idname == TOOL


def frame(context, faces, orientation='COMPONENT'):
    ob = context.edit_object
    mw = ob.matrix_world
    points = [mw @ v.co for v in {v for f in faces for v in f.verts}]
    centre = Vector(tuple((min(p[i] for p in points)+max(p[i] for p in points))*.5 for i in range(3)))
    if context.tool_settings.transform_pivot_point == 'CURSOR':
        centre = context.scene.cursor.location.copy()
    slots = context.scene.transform_orientation_slots
    inherited = next((s for s in slots if s.type == pivot.ORIENT_NAME), None)
    if orientation == 'WORLD':
        axes = Matrix.Identity(3)
    elif orientation == 'OBJECT':
        axes = mw.to_quaternion().to_matrix()
    elif orientation == 'CUSTOM' or (orientation == 'COMPONENT' and inherited is not None):
        axes = (inherited.custom_orientation.matrix.copy() if inherited and inherited.custom_orientation
                else context.scene.cursor.matrix.to_3x3().normalized())
    else:
        normal_matrix = mw.to_3x3().inverted_safe().transposed()
        normal = sum((normal_matrix @ f.normal * f.calc_area() for f in faces), Vector())
        if normal.length < 1e-9:
            raise smart_geometry.GeometryError("Choose a face region with a usable component normal")
        normal.normalize()
        x, y = extrude.face_axes(normal, mw.to_quaternion() @ Vector((1, 0, 0)), Vector((0, 1, 0)))
        axes = Matrix((x, y, normal)).transposed()
    return centre, axes


def selection_state(bm):
    for seq in (bm.verts, bm.edges, bm.faces):
        seq.index_update()
    history = [('VERT' if isinstance(e, bmesh.types.BMVert) else 'EDGE' if isinstance(e, bmesh.types.BMEdge) else 'FACE', e.index)
               for e in bm.select_history]
    return history, bm.faces.active.index if bm.faces.active is not None else None


def replace(ob, source, selection=None):
    """Replace the contents of an edit BMesh without leaving edit mode."""
    mesh = bpy.data.meshes.new(".allset_smart_restore")
    try:
        source.to_mesh(mesh)
        bm = bmesh.from_edit_mesh(ob.data)
        bm.clear()
        bm.from_mesh(mesh)
        if selection is not None:
            history, active_face = selection
            seqs = {'VERT': bm.verts, 'EDGE': bm.edges, 'FACE': bm.faces}
            for seq in seqs.values():
                seq.ensure_lookup_table()
            for kind, index in history:
                if index < len(seqs[kind]):
                    bm.select_history.add(seqs[kind][index])
            if active_face is not None and active_face < len(bm.faces):
                bm.faces.active = bm.faces[active_face]
        else:
            bm.faces.active = next((f for f in bm.faces if f.select), None)
        bmesh.update_edit_mesh(ob.data)
    finally:
        bpy.data.meshes.remove(mesh)


class Session:
    def __init__(self, context, orientation='COMPONENT', together=True):
        ob = context.edit_object
        if len(context.objects_in_mode_unique_data) != 1:
            raise smart_geometry.GeometryError("Use Smart Extrude on one mesh object at a time; shells may be disconnected")
        if ob.data.shape_keys:
            raise smart_geometry.GeometryError("Smart Extrude changes topology; remove shape keys on a copy first")
        if abs(ob.matrix_world.determinant()) < 1e-12:
            raise smart_geometry.GeometryError("The object has zero scale")
        bm = bmesh.from_edit_mesh(ob.data)
        smart_geometry.validate(bm, input_mesh=True)
        faces = smart_geometry.selected_faces(bm, context.tool_settings.mesh_select_mode)
        if not faces:
            raise smart_geometry.GeometryError("Select faces, edges or vertices first")
        bm.faces.index_update()
        self.centre, self.axes = frame(context, faces if together else faces[:1], orientation)
        self.ob = ob
        self.mw = ob.matrix_world.copy()
        self.unit = units.maya_unit(context.scene)
        self.mode = tuple(context.tool_settings.mesh_select_mode)
        self.selection = selection_state(bm)
        self.pivot_state = (context.tool_settings.transform_pivot_point, hold.COMPONENT.custom,
                            hold.COMPONENT.sel_sig, context.scene.cursor.matrix.copy())
        self.faces = [f.index for f in faces]
        self.pre = bm.copy()
        self.cancel_mesh = None
        self.together = together
        self.orientation = orientation
        self.groups = {f.index: (self.mw @ f.calc_center_median(), frame(context, [f], orientation)[1])
                       for f in faces} if not together else {}

    def transform(self, translation, rotation, scale, factor=1., centre=None, axes=None):
        centre = self.centre if centre is None else centre
        axes = self.axes if axes is None else axes
        local = (Euler(tuple(a*factor for a in rotation), 'XYZ').to_matrix().to_4x4()
                 @ Matrix.Diagonal(Vector(tuple(1+(s-1)*factor for s in scale) + (1.,))))
        delta = Matrix.Translation(axes @ (Vector(translation)*self.unit*factor))
        world = delta @ Matrix.Translation(centre) @ axes.to_4x4() @ local @ axes.transposed().to_4x4() @ Matrix.Translation(-centre)
        return self.mw.inverted() @ world @ self.mw

    def result(self, context, translation, rotation, scale):
        if any(s < .001 for s in scale):
            raise smart_geometry.GeometryError("Smart Extrude scale must stay positive")
        if (Vector(translation).length < 1e-10 and Vector(rotation).length < 1e-10
                and (Vector(scale)-Vector((1, 1, 1))).length < 1e-10):
            return self.pre.copy()
        # Extrusion joins the source and transformed caps directly. Mouse events
        # must not accumulate intermediate rotational sweeps into the topology.
        if self.together:
            transforms = [self.transform(translation, rotation, scale)]
        else:
            matrices = {i: self.transform(translation, rotation, scale, 1., c, a)
                        for i, (c, a) in self.groups.items()}
            transforms = [lambda p, group: matrices[group] @ p]
        return smart_geometry.sweep(context, self.pre, self.faces, transforms,
                                    tuple(self.ob.data.materials), separate=not self.together)

    def show(self, context, translation, rotation, scale):
        result = self.result(context, translation, rotation, scale)
        try:
            replace(self.ob, result)
            context.tool_settings.mesh_select_mode = (False, False, True)
        finally:
            result.free()

    def restore(self, context):
        replace(self.ob, self.cancel_mesh if self.cancel_mesh is not None else self.pre, self.selection)
        context.tool_settings.mesh_select_mode = self.mode
        point, custom, signature, cursor = self.pivot_state
        context.tool_settings.transform_pivot_point = point
        hold.COMPONENT.custom, hold.COMPONENT.sel_sig = custom, signature
        context.scene.cursor.matrix = cursor

    def free(self):
        self.pre.free()
        if self.cancel_mesh is not None:
            self.cancel_mesh.free()

    def clone(self, ob):
        other = object.__new__(Session)
        other.__dict__.update(self.__dict__)
        other.pre = self.pre.copy()
        other.cancel_mesh = None
        other.ob = ob
        return other


def signature(bm):
    """Detect intervening edits, UV/material changes and a new selection before reusing a node."""
    bm.verts.index_update()
    uv_layers = list(bm.loops.layers.uv.values())
    return hash((tuple((tuple(v.co), v.select, v.hide) for v in bm.verts),
                 tuple((tuple(v.index for v in e.verts), e.select, e.hide, e.seam, e.smooth) for e in bm.edges),
                 tuple((tuple(v.index for v in f.verts), f.select, f.hide, f.material_index, f.smooth,
                        tuple(tuple(lp[layer].uv) for lp in f.loops for layer in uv_layers)) for f in bm.faces)))


def current(context):
    ob = context.edit_object
    rec = RECORDS.get(ob.name) if ob is not None else None
    if rec is None or rec['uid'] != ob.data.session_uid or rec['session'].mw != ob.matrix_world:
        return None
    sig = signature(bmesh.from_edit_mesh(ob.data))
    return next(((rec, params) for state, params in reversed(rec['states']) if state == sig), None)


def remember(context, session, op, previous=None):
    params = {key: tuple(getattr(op, key)) for key in ('translation', 'rotation', 'scale')}
    sig = signature(bmesh.from_edit_mesh(session.ob.data))
    rec = previous
    if rec is None:
        old = RECORDS.pop(session.ob.name, None)
        if old is not None:
            old['session'].free()
        rec = {'uid': session.ob.data.session_uid, 'session': session.clone(session.ob), 'states': [],
               'token': uuid.uuid4().hex}
        RECORDS[session.ob.name] = rec
    if hasattr(op, 'node_id'):
        op.node_id = rec['token']
    rec['states'].append((sig, params))
    rec.setdefault('display_states', []).append((display_signature(bmesh.from_edit_mesh(session.ob.data)), params))
    del rec['states'][:-32]
    del rec['display_states'][:-32]


def display_signature(bm):
    return hash((len(bm.verts), len(bm.edges), len(bm.faces),
                 tuple(tuple(tuple(v.co) for v in f.verts) for f in bm.faces if f.select)))


def display(context):
    ob = context.edit_object
    rec = RECORDS.get(ob.name) if ob else None
    if (rec is None or rec['uid'] != ob.data.session_uid or rec['session'].mw != ob.matrix_world
            or rec['session'].orientation != context.scene.allset_smart_extrude.orientation):
        return None
    sig = display_signature(bmesh.from_edit_mesh(ob.data))
    return next(((rec['session'], params) for state, params in reversed(rec['display_states']) if state == sig), None)


@bpy.app.handlers.persistent
def clear(*_args):
    for rec in RECORDS.values():
        rec['session'].free()
    RECORDS.clear()


def _props():
    return {
        'translation': bpy.props.FloatVectorProperty(name="Translate", size=3, default=(0, 0, 0)),
        'rotation': bpy.props.FloatVectorProperty(name="Rotate", size=3, subtype='EULER', default=(0, 0, 0)),
        'scale': bpy.props.FloatVectorProperty(name="Scale", size=3, default=(1, 1, 1), min=.001),
        'orientation': bpy.props.EnumProperty(name="Orientation", items=(
            ('COMPONENT', "Component", "Selected face normal; inherit an edited pivot frame"),
            ('OBJECT', "Object", "Object axes"), ('WORLD', "World", "World axes"),
            ('CUSTOM', "Custom Pivot", "Edited pivot orientation or 3D cursor orientation")), default='COMPONENT'),
        'together': bpy.props.BoolProperty(name="Keep Faces Together", default=True),
    }


class _Props:
    __annotations__ = _props()


def record(context, op):
    from . import repeat_maya
    props = {k: tuple(getattr(op, k)) if k in {'translation', 'rotation', 'scale'} else getattr(op, k)
             for k in FIELDS}
    repeat_maya.record("Smart Extrude", ("v3d", "allset.smart_extrude", props), context=context)


@undo_steps.no_redo_panel
class ALLSET_OT_smart_extrude(_Props, bpy.types.Operator):
    """Smart Extrude: grow, carve and stitch intersecting faces in the same mesh"""
    bl_idname = "allset.smart_extrude"
    bl_label = "Smart Extrude"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def invoke(self, context, event):
        if any(self.properties.is_property_set(k) for k in ('translation', 'rotation', 'scale')):
            return self.execute(context)
        extrude.dismiss(context)
        old = RECORDS.pop(context.edit_object.name, None)
        if old:
            old['session'].free()
        bpy.ops.wm.tool_set_by_id(name=TOOL, space_type='VIEW_3D')
        return {'FINISHED'}

    def execute(self, context):
        session = None
        try:
            session = Session(context, self.orientation, self.together)
            session.show(context, self.translation, self.rotation, self.scale)
            remember(context, session, self)
        except (smart_geometry.GeometryError, RuntimeError) as ex:
            if session:
                session.restore(context)
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        finally:
            if session:
                session.free()
        extrude.dismiss(context)
        record(context, self)
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_smart_extrude_drag(_Props, bpy.types.Operator):
    """Drag a Smart Extrude handle; J snaps, type a value, Esc restores the mesh"""
    bl_idname = "allset.smart_extrude_drag"
    bl_label = "Smart Extrude"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    kind: bpy.props.EnumProperty(items=(('TRANSLATE', "Move", ""), ('ROTATE', "Rotate", ""), ('SCALE', "Scale", "")))
    axis: bpy.props.IntProperty(default=2, min=-1, max=2)
    node_id: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and context.region_data is not None

    def execute(self, context):
        """Blender can re-execute a registered modal operator after undoing it."""
        ob = context.edit_object
        rec = RECORDS.get(ob.name)
        if rec is None or rec['uid'] != ob.data.session_uid or rec['token'] != self.node_id:
            self.report({'WARNING'}, "This Smart Extrude node is no longer available; start a new Smart Extrude")
            return {'CANCELLED'}
        session = rec['session'].clone(ob)
        session.cancel_mesh = bmesh.from_edit_mesh(ob.data).copy()
        session.selection = selection_state(bmesh.from_edit_mesh(ob.data))
        try:
            session.show(context, self.translation, self.rotation, self.scale)
            remember(context, session, self, rec)
            record(context, self)
        except (smart_geometry.GeometryError, RuntimeError) as ex:
            session.restore(context)
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        finally:
            session.free()
        return {'FINISHED'}

    def _screen_basis(self, context):
        """Freeze a linear screen-to-axis mapping for the entire gesture.

        A perspective ray/axis closest-point solve has a pole at the axis's
        vanishing point. Switching to another solve there made a long inward
        drag jump back towards zero. Use the start depth throughout instead.
        """
        axis = self._drag_axes.col[max(0, self.axis)]
        centre = self._drag_centre
        region, rv = context.region, context.region_data
        a = view3d_utils.location_3d_to_region_2d(region, rv, centre)
        if a is None:
            raise smart_geometry.GeometryError("Place the Smart Extrude pivot in front of the view")
        world_pixel = (view3d_utils.region_2d_to_location_3d(region, rv, a+Vector((1, 0)), centre)-centre).length
        b = view3d_utils.location_3d_to_region_2d(region, rv, centre+axis*world_pixel)
        projected = b-a if b is not None else Vector((0, 0))
        self._screen_axis = projected.normalized() if projected.length > 1e-5 else Vector((0, 1))
        self._world_per_pixel = world_pixel/max(projected.length, .1)

    def _value(self, context, event):
        dx = event.mouse_region_x - self._mouse[0]
        dy = event.mouse_region_y - self._mouse[1]
        if self.kind == 'TRANSLATE':
            value = Vector((dx, dy)).dot(self._screen_axis)*self._world_per_pixel/self._session.unit
        elif self.kind == 'ROTATE':
            mouse = (event.mouse_region_x, event.mouse_region_y)
            vector = self._vector(context, event)
            if mouse != self._last_mouse:
                if vector is not None and self._last_vector is not None:
                    normal = self._drag_axes.col[self.axis]
                    self._drag_angle += math.atan2(normal.dot(self._last_vector.cross(vector)), self._last_vector.dot(vector))
                else:
                    self._drag_angle += ((mouse[0]-self._last_mouse[0])+(mouse[1]-self._last_mouse[1]))*.01
                self._last_mouse, self._last_vector = mouse, vector
            value = self._drag_angle
        else:
            distance = Vector((dx, dy)).dot(self._screen_axis) if self.axis >= 0 else dx
            value = 1 + distance*.01
        if event.shift != self._precision:
            self._precision_raw, self._precision_anchor = value, self._precision_value
            self._precision = event.shift
        value = self._precision_anchor + (value-self._precision_raw)*(.1 if self._precision else 1.)
        self._precision_value = value
        if self._step_held or (self._baseline_step != event.ctrl):
            increment = context.tool_settings.snap_angle_increment_3d if self.kind == 'ROTATE' else .1 if self.kind == 'SCALE' else 1.
            if increment > 1e-9:
                value = round(value/increment)*increment
        if self._text:
            try:
                value = float(self._text)
                if self.kind == 'ROTATE':
                    value = math.radians(value)
            except ValueError:
                pass
        return value

    def _vector(self, context, event):
        mouse = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(context.region, context.region_data, mouse)
        direction = view3d_utils.region_2d_to_vector_3d(context.region, context.region_data, mouse)
        hit = intersect_line_plane(origin, origin+direction, self._drag_centre, self._drag_axes.col[max(0, self.axis)])
        if hit is None or (hit-self._drag_centre).length < 1e-6:
            return None
        return (hit-self._drag_centre).normalized()

    def _update(self, context, event):
        value = self._value(context, event)
        for key, values in self._start.items():
            setattr(self, key, values)
        attr = {'TRANSLATE': 'translation', 'ROTATE': 'rotation', 'SCALE': 'scale'}[self.kind]
        values = list(getattr(self, attr))
        if self.kind == 'TRANSLATE':
            offset = self._session.axes.transposed() @ self._drag_axes.col[self.axis] * value
            values = Vector(values) + offset
        elif self.kind == 'ROTATE':
            values = (Euler(tuple(values), 'XYZ').to_matrix() @ Matrix.Rotation(value, 3, 'XYZ'[self.axis])).to_euler('XYZ')
        elif self.axis < 0:
            values = [max(.001, value)*s for s in values]
        else:
            values[self.axis] *= max(.001, value)
        setattr(self, attr, values)
        self._pending = True
        if self._error is None:
            self._display_params = {key: tuple(getattr(self, key)) for key in self._start}
        context.area.tag_redraw()
        context.area.header_text_set(f"Smart Extrude · {self.kind.title()} {'XYZ'[self.axis] if self.axis >= 0 else 'All'}: "
                                     f"{math.degrees(value) if self.kind == 'ROTATE' else value:.3f} · J: Snap · Type: Value · Esc: Cancel")

    def _preview(self, context):
        if not self._pending:
            return
        start = time.monotonic()
        try:
            self._session.show(context, self.translation, self.rotation, self.scale)
            self._accepted = {key: tuple(getattr(self, key)) for key in self._start}
            self._display_params = self._accepted
            self._error = None
        except (smart_geometry.GeometryError, RuntimeError) as ex:
            self._error = str(ex)
            self._display_params = self._accepted
        self._pending = False
        self._last_time = time.monotonic()
        self._interval = max(FRAME_INTERVAL, min(.1, (self._last_time-start)*.25))
        context.area.tag_redraw()

    def _end(self, context, cancel=False):
        global DRAG
        if not cancel:
            self._preview(context)
            if self._error:
                for key, value in self._accepted.items():
                    setattr(self, key, value)
                self.report({'WARNING'}, self._error + "; kept the last valid preview")
            if all(tuple(getattr(self, key)) == tuple(value) for key, value in self._start.items()):
                cancel = True
        if cancel:
            self._session.restore(context)
        else:
            remember(context, self._session, self, self._previous)
            record(context, self)
        context.window_manager.event_timer_remove(self._timer)
        context.area.header_text_set(None)
        self._session.free()
        DRAG = None
        context.area.tag_redraw()
        return {'CANCELLED'} if cancel else {'FINISHED'}

    def invoke(self, context, event):
        global DRAG
        settings = context.scene.allset_smart_extrude
        self.orientation, self.together = settings.orientation, settings.together
        try:
            old = current(context)
            self._previous = (old[0] if old and old[0]['session'].together == self.together
                              and old[0]['session'].orientation == self.orientation else None)
            if self._previous is not None:
                self._session = self._previous['session'].clone(context.edit_object)
                self._start = old[1]
                self._session.cancel_mesh = bmesh.from_edit_mesh(context.edit_object.data).copy()
                self._session.mode = tuple(context.tool_settings.mesh_select_mode)
                self._session.selection = selection_state(bmesh.from_edit_mesh(context.edit_object.data))
                self._session.pivot_state = (context.tool_settings.transform_pivot_point, hold.COMPONENT.custom,
                                             hold.COMPONENT.sel_sig, context.scene.cursor.matrix.copy())
            else:
                self._session = Session(context, self.orientation, self.together)
                self._start = {'translation': (0, 0, 0), 'rotation': (0, 0, 0), 'scale': (1, 1, 1)}
        except smart_geometry.GeometryError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        self._mouse = (event.mouse_region_x, event.mouse_region_y)
        for key, value in self._start.items():
            setattr(self, key, value)
        self._drag_axes = self._session.axes @ Euler(self._start['rotation'], 'XYZ').to_matrix()
        self._drag_centre = self._session.centre + self._session.axes @ (Vector(self._start['translation'])*self._session.unit)
        try:
            self._screen_basis(context)
        except smart_geometry.GeometryError as ex:
            self._session.free()
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        self._accepted = dict(self._start)
        self._display_params = self._accepted
        self._last_mouse, self._last_vector = self._mouse, self._vector(context, event)
        self._drag_angle = 0.
        self._precision = event.shift
        self._precision_raw = self._precision_anchor = self._precision_value = 1. if self.kind == 'SCALE' else 0.
        self._text, self._error = '', None
        self._step_held, self._baseline_step = hold.step_state(context.tool_settings, 'RESIZE' if self.kind == 'SCALE' else self.kind)
        self._last_time, self._interval, self._pending = 0., FRAME_INTERVAL, False
        self._timer = context.window_manager.event_timer_add(FRAME_INTERVAL, window=context.window)
        DRAG = self
        extrude.dismiss(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            return self._end(context, True)
        if ((event.type == 'LEFTMOUSE' and event.value == 'RELEASE')
                or (event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS')):
            if event.type == 'LEFTMOUSE':
                self._update(context, event)
            return self._end(context)
        if event.type == 'J' and event.value in {'PRESS', 'RELEASE'}:
            self._step_held = event.value == 'PRESS'
            self._update(context, event)
        elif event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value in {'PRESS', 'RELEASE'}:
            self._update(context, event)
        elif event.type in {'X', 'Y', 'Z'} and event.value == 'PRESS':
            self.axis = 'XYZ'.index(event.type)
            self._screen_basis(context)
            self._last_mouse, self._last_vector = (event.mouse_region_x, event.mouse_region_y), self._vector(context, event)
            self._drag_angle = 0.
            self._precision = event.shift
            self._precision_raw = self._precision_anchor = self._precision_value = 1. if self.kind == 'SCALE' else 0.
            self._update(context, event)
        elif event.value == 'PRESS' and (event.type == 'BACK_SPACE' or getattr(event, 'unicode', '') in '0123456789.-' and getattr(event, 'unicode', '')):
            self._text = self._text[:-1] if event.type == 'BACK_SPACE' else self._text+event.unicode
            self._update(context, event)
        elif event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._update(context, event)
        if self._pending and time.monotonic()-self._last_time >= self._interval:
            self._preview(context)
        return {'RUNNING_MODAL'}


class ALLSET_PG_smart_extrude(_Props, bpy.types.PropertyGroup):
    pass


classes = (ALLSET_OT_smart_extrude, ALLSET_OT_smart_extrude_drag, ALLSET_PG_smart_extrude)


def register_props():
    bpy.types.Scene.allset_smart_extrude = bpy.props.PointerProperty(type=ALLSET_PG_smart_extrude)
    bpy.app.handlers.load_pre.append(clear)


def unregister_props():
    clear()
    if clear in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(clear)
    del bpy.types.Scene.allset_smart_extrude
