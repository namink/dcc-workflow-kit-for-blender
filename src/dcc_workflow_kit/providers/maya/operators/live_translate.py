# SPDX-License-Identifier: GPL-3.0-or-later
"""Move centre/plane handles onto the explicit live meshes, never unrelated geometry."""
import math

import bpy
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector

from . import component_scale, hold, live, units

DRAG = None


def enabled(context):
    if context.mode not in {'OBJECT', 'EDIT_MESH'} or not live.objects(context.scene):
        return False
    if hold.COMPONENT.on or context.tool_settings.use_transform_data_origin:
        return False
    # Explicit grid/curve/vertex snap requests retain Blender's native transform.
    ts = context.tool_settings
    if ts.use_snap and set(ts.snap_elements)-{'INCREMENT', 'FACE_PROJECT'}:
        return False
    return any(not live.contains(context.scene, o) for o in context.selected_objects)


def start(context, kwargs, button='LEFTMOUSE'):
    if enabled(context) and sum(kwargs.get('constraint_axis', ())) != 1:
        return bpy.ops.allset.live_translate('INVOKE_DEFAULT', release_event=button, **kwargs)
    from . import pivot
    pivot.origins_for_groups(context)
    return bpy.ops.transform.translate('INVOKE_DEFAULT', **kwargs)


class ALLSET_OT_live_translate(bpy.types.Operator):
    """Move along the live surface; centre and plane handles project to live meshes only"""
    bl_idname = 'allset.live_translate'
    bl_label = 'Move on Live Surface'
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    value: bpy.props.FloatVectorProperty(size=3, subtype='TRANSLATION', options={'HIDDEN', 'SKIP_SAVE'})
    constraint_axis: bpy.props.BoolVectorProperty(size=3, options={'HIDDEN', 'SKIP_SAVE'})
    orient_type: bpy.props.StringProperty(default='GLOBAL', options={'HIDDEN', 'SKIP_SAVE'})
    orient_matrix_type: bpy.props.StringProperty(default='GLOBAL', options={'HIDDEN', 'SKIP_SAVE'})
    orient_matrix: bpy.props.FloatVectorProperty(size=(3, 3), subtype='MATRIX', default=((1, 0, 0), (0, 1, 0), (0, 0, 1)), options={'HIDDEN', 'SKIP_SAVE'})
    release_confirm: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    release_event: bpy.props.EnumProperty(items=(('LEFTMOUSE', 'Left', ''), ('MIDDLEMOUSE', 'Middle', '')),
                                        default='LEFTMOUSE', options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return enabled(context)

    def _capture(self, context):
        from ..ui import manipulator
        if context.mode == 'OBJECT':
            for ob in context.selected_objects:
                if live.contains(context.scene, ob):
                    ob.select_set(False)
            if live.contains(context.scene, context.active_object):
                context.view_layer.objects.active = next(iter(context.selected_objects), None)
        self._centre, _, _ = manipulator.pivot_frame(context, 'TRANSLATE')
        if self._centre is None:
            raise ValueError('Select something outside the live reference to move')
        self._targets = live.objects(context.scene)
        self._frame = (Matrix(self.orient_matrix) if self.orient_type == 'GLOBAL' and self.properties.is_property_set('orient_matrix')
                       else manipulator.axes_of(context, self.orient_type, context.region_data))
        self.orient_type = self.orient_matrix_type = 'GLOBAL'
        self.orient_matrix = self._frame
        self._mesh = component_scale.Snapshot(context) if context.mode == 'EDIT_MESH' else None
        nodes = set(context.selected_objects)
        for ob in list(nodes):
            nodes.update(ob.children_recursive)
        self._objects = [(ob, ob.location.copy(), ob.matrix_parent_inverse.copy()) for ob in nodes] if self._mesh is None else []
        self._step, self._baseline = hold.step_state(context.tool_settings, 'TRANSLATE')
        self._unit = units.maya_unit(context.scene)

    def _restore(self, context):
        if self._mesh is not None:
            self._mesh.restore()
        else:
            for ob, location, parent_inverse in self._objects:
                ob.location = location
                ob.matrix_parent_inverse = parent_inverse
            context.view_layer.update()

    def apply(self, context, point):
        if not all(math.isfinite(v) for v in point):
            raise ValueError('Live surface position must be finite')
        self._restore(context)
        ts = context.tool_settings
        value = point-self._centre
        if bpy.ops.transform.translate('EXEC_DEFAULT', False, value=value,
                orient_type='GLOBAL', snap=False, use_proportional_edit=ts.use_proportional_edit,
                proportional_edit_falloff=ts.proportional_edit_falloff, proportional_size=ts.proportional_size,
                use_proportional_connected=ts.use_proportional_connected,
                use_proportional_projected=ts.use_proportional_projected) != {'FINISHED'}:
            raise ValueError('Blender could not move this selection')
        self.value = value

    def execute(self, context):
        try:
            self._capture(context)
            hit = live.nearest(context, self._centre+Vector(self.value), self._targets)
            if hit is None:
                raise ValueError('The live meshes have no usable surface')
            self.apply(context, hit[0])
        except (ValueError, RuntimeError) as ex:
            if hasattr(self, '_objects'):
                self._restore(context)
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        finally:
            self._free()
        return {'FINISHED'}

    def _free(self):
        if getattr(self, '_mesh', None) is not None:
            self._mesh.entries.clear()
        self._objects = []

    def invoke(self, context, event):
        global DRAG
        try:
            self._capture(context)
        except (ValueError, RuntimeError) as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        projected = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, self._centre)
        if projected is None:
            self._free()
            return {'CANCELLED'}
        self._mouse_offset = Vector((event.mouse_region_x, event.mouse_region_y))-projected
        self._raw = self._anchor = self._anchor_raw = Vector()
        self._precision, self._text = event.shift, ''
        self._mouse = (event.mouse_region_x, event.mouse_region_y)
        DRAG = self
        from . import manip
        manip.HANDLES['TRANSLATE'] = (dict(constraint_axis=tuple(self.constraint_axis), orient_type='GLOBAL',
                                          orient_matrix_type='GLOBAL', orient_matrix=self._frame.copy())
                                      if any(self.constraint_axis) else None)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _update(self, context, event):
        mouse = Vector(self._mouse)-self._mouse_offset
        origin = view3d_utils.region_2d_to_origin_3d(context.region, context.region_data, mouse)
        direction = view3d_utils.region_2d_to_vector_3d(context.region, context.region_data, mouse)
        hit = live.ray_hit(context, origin, direction, self._targets)
        if hit is None:
            return  # off the live meshes: keep the accepted preview
        raw = hit[0]-self._centre
        if event.shift != self._precision:
            self._anchor, self._anchor_raw, self._precision = self._raw.copy(), raw.copy(), event.shift
        self._raw = self._anchor+(raw-self._anchor_raw)*(.1 if self._precision else 1.)
        delta = self._raw
        if self._step or (self._baseline != event.ctrl):
            local = self._frame.inverted_safe() @ delta
            delta = self._frame @ Vector(tuple(round(v/self._unit)*self._unit for v in local))
        if self._text:
            try:
                axis = next((i for i, on in enumerate(self.constraint_axis) if on), 0)
                delta = self._frame.col[axis]*float(self._text)*self._unit
            except ValueError:
                return
        nearest = live.nearest(context, self._centre+delta, self._targets)
        if nearest:
            self.apply(context, nearest[0])
            context.area.header_text_set('Move on Live Surface · J: Steps · Shift: Precision · Esc: Cancel')
            live.redraw()

    def _end(self, context, cancel=False):
        global DRAG
        if cancel:
            self._restore(context)
        DRAG = None
        self._free()
        context.area.header_text_set(None)
        live.redraw()
        return {'CANCELLED'} if cancel else {'FINISHED'}

    def cancel(self, context):
        self._end(context, True)

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            return self._end(context, True)
        if ((event.type == self.release_event and event.value == 'RELEASE') or
                (event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS')):
            return self._end(context)
        try:
            if event.type == 'MOUSEMOVE':
                self._mouse = (event.mouse_region_x, event.mouse_region_y)
                self._update(context, event)
            elif event.type == 'J' and event.value in {'PRESS', 'RELEASE'}:
                if not event.is_repeat:
                    self._step = event.value == 'PRESS'
                    self._update(context, event)
            elif event.type == 'BACK_SPACE' and event.value == 'PRESS':
                self._text = self._text[:-1]
                self._update(context, event)
            elif event.value == 'PRESS' and getattr(event, 'unicode', '') and event.unicode in '0123456789.-':
                self._text += event.unicode
                self._update(context, event)
        except (ValueError, RuntimeError) as ex:
            self.report({'WARNING'}, str(ex))
            return self._end(context, True)
        return {'RUNNING_MODAL'}


classes = (ALLSET_OT_live_translate,)
