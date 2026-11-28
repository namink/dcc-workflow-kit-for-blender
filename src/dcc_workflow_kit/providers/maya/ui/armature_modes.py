# SPDX-License-Identifier: GPL-3.0-or-later
"""Skeleton modes in the 3D View: the optional header mode picker (``allset.armature_mode``, preference
``armature_mode_header``), Pose mode when a skeleton gets picked and Object mode when it is let go
(``_auto_armature_tick``), and watches that leave joint modes on an empty viewport click or when the Outliner
picks another object. Registered by ``toolbox`` (timers, header draw function)."""

import bpy

from .toolbox_column import _enabled, is_toolbox


class ALLSET_OT_armature_mode(bpy.types.Operator):
    """Switch the selected skeleton between Object, Edit, and Pose modes"""
    bl_idname = 'allset.armature_mode'
    bl_label = 'Armature Mode'
    bl_options = {'INTERNAL'}

    mode: bpy.props.EnumProperty(items=[
        ('OBJECT', 'Object Mode', 'Select the entire skeleton'),
        ('EDIT', 'Edit Mode', 'Edit bones and joint positions'),
        ('POSE', 'Pose Mode', 'Select and pose joints'),
    ])

    @classmethod
    def poll(cls, context):
        obj = context.view_layer.objects.active
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        from .status_line import main_view3d
        obj = context.view_layer.objects.active
        if obj is None or obj.type != 'ARMATURE':
            return {'CANCELLED'}
        if obj.mode == self.mode:
            return {'FINISHED'}
        from ..operators import maya_errors
        if self.mode != 'OBJECT' and maya_errors.refuse_hidden(self, obj):     # #187
            return {'CANCELLED'}
        area, region = main_view3d(context.screen)
        try:
            if area is not None and region is not None:
                with context.temp_override(window=context.window, area=area, region=region):
                    bpy.ops.object.mode_set(mode=self.mode)
            else:
                bpy.ops.object.mode_set(mode=self.mode)
        except (RuntimeError, ValueError) as ex:
            self.report({'WARNING'}, f'Unable to switch armature mode: {ex}')
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_MT_armature_modes(bpy.types.Menu):
    """Switch joint/object modes from the main viewport header."""
    bl_idname = 'ALLSET_MT_armature_modes'
    bl_label = 'Armature Mode'

    def draw(self, context):
        obj = context.view_layer.objects.active
        for mode, label, icon in (
            ('OBJECT', 'Object Mode', 'OBJECT_DATAMODE'),
            ('EDIT', 'Edit Mode', 'EDITMODE_HLT'),
            ('POSE', 'Pose Mode', 'POSE_HLT'),
        ):
            row = self.layout.row()
            row.enabled = obj is not None and obj.mode != mode
            row.operator('allset.armature_mode', text=label, icon=icon).mode = mode


def _draw_armature_mode_header(self, context):
    """Prominent, outlined armature mode picker with an explicit chevron. Maya has no mode picker in any version:
    only drawn with the add-on preference ``armature_mode_header`` on."""
    from . import armature_mode_pulse
    from .. import preferences
    armature_mode_pulse.forget(context)
    if not _enabled(context) or not getattr(preferences.get(context), "armature_mode_header", False):
        return
    obj = context.view_layer.objects.active
    if obj is None or obj.type != 'ARMATURE':
        return
    from .status_line import main_view3d
    area, _ = main_view3d(context.screen)
    if context.area != area or is_toolbox(context.space_data):
        return
    mode_label = {'OBJECT': 'OBJECT', 'EDIT': 'EDIT JOINTS', 'POSE': 'POSE JOINTS'}.get(obj.mode, 'JOINT MODE')
    mode_icon = {'OBJECT': 'OBJECT_DATAMODE', 'EDIT': 'EDITMODE_HLT', 'POSE': 'POSE_HLT'}.get(obj.mode, 'ARMATURE_DATA')
    # Header menus normally hide their dropdown affordance; place a chevron
    # explicitly alongside the text, inside a single framed toolbar group.
    frame = self.layout.row(align=True)
    frame.ui_units_x = armature_mode_pulse.CUSTOM_UNITS
    # This control is first in the header, giving its pulse a stable local
    # footprint even in the kit's custom Maya header and narrow viewports.
    armature_mode_pulse.mark(context)
    frame.label(text='', icon='ARMATURE_DATA')
    frame.menu('ALLSET_MT_armature_modes', text=mode_label + '  ▾', icon=mode_icon)


# Track active-object transitions rather than forcing Pose Mode continuously.
# This leaves the user free to switch to Edit/Object manually in the dropdown.
_last_armature_target = {}
_AUTO_MODE_TICK = 0.18


def _auto_armature_tick():
    if bpy.app.background:
        return None
    try:
        for window in bpy.context.window_manager.windows:
            screen = window.screen
            if not screen:
                continue
            from .status_line import main_view3d
            area, region = main_view3d(screen)
            key = window.as_pointer()
            if area is None or region is None:
                _last_armature_target.pop(key, None)
                continue
            with bpy.context.temp_override(window=window, area=area, region=region):
                ctx = bpy.context
                if not _enabled(ctx):
                    _last_armature_target.pop(key, None)
                    continue
                ob = ctx.view_layer.objects.active
                target = ob.as_pointer() if ob and ob.type == 'ARMATURE' and ob.select_get() else None
                if key not in _last_armature_target:
                    _last_armature_target[key] = target
                    continue
                previous = _last_armature_target[key]
                if target == previous:
                    continue
                _last_armature_target[key] = target
                if target is not None and ob.mode == 'OBJECT':
                    from ..operators import joint_selection
                    try:
                        # #156: the Move tool on an unskinned skeleton then switches it to
                        # Edit mode (joint_selection.sync_tool_mode, tool_keys watch)
                        bpy.ops.object.mode_set(mode='POSE')
                    except (RuntimeError, ValueError):
                        pass
                    else:
                        # B4: a skeleton picked from the Outliner / Select All shows its root joint
                        if joint_selection.select_roots_if_empty(ob):
                            for a in window.screen.areas:
                                a.tag_redraw()
                elif target is None and ob and (ob.mode == 'POSE' or (ob.type == 'ARMATURE' and ob.mode == 'EDIT')):
                    try:
                        bpy.ops.object.mode_set(mode='OBJECT')
                    except (RuntimeError, ValueError):
                        pass
    except (RuntimeError, ReferenceError, AttributeError):
        pass
    return _AUTO_MODE_TICK


def _click_hits_joint(context, obj, x, y):
    """Whether a viewport click is on a visible armature bone (screen pixels).

    Unlike checking selection flags, this also handles Blender retaining edit-bone
    selection when the user clicks a blank part of the viewport.
    """
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    from mathutils import Vector

    region = context.region
    space = context.space_data
    if not space or space.type != 'VIEW_3D' or region.type != 'WINDOW':
        return True  # Never change modes if the target region is uncertain.
    rv3d = space.region_3d
    if rv3d is None:
        return True
    def shown(bone):    # hidden bone collections hide their bones too (#171: ORG / MCH bones gave false hits)
        return not (bone.collections and not any(c.is_visible_effectively for c in bone.collections))
    if obj.mode == 'EDIT':
        segments = ((b.head, b.tail) for b in obj.data.edit_bones if not b.hide and shown(b))
    else:
        segments = ((b.head, b.tail) for b in obj.pose.bones if not b.bone.hide and shown(b.bone))

    point = Vector((x, y))
    # Bone handles have nonzero screen size; allow a modest hit margin.
    margin = 15.0 * context.preferences.system.ui_scale
    margin_sq = margin * margin
    matrix = obj.matrix_world
    for head, tail in segments:
        p = location_3d_to_region_2d(region, rv3d, matrix @ head)
        q = location_3d_to_region_2d(region, rv3d, matrix @ tail)
        if p is None or q is None:
            continue
        delta = q - p
        fraction = max(0.0, min(1.0, (point - p).dot(delta) / max(delta.length_squared, 1e-9)))
        if (point - (p + fraction * delta)).length_squared <= margin_sq:
            return True
    return False



def _other_object_under_click(context, armature, x, y):
    """Find another selectable scene mesh under a viewport click.

    Blender's regular object picking cannot change the active object while an
    armature is in Edit Mode. Ray-cast instead, then switch mode before selecting.
    """
    from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
    from mathutils import Vector

    region = context.region
    rv3d = context.space_data.region_3d
    coord = Vector((x, y))
    origin = region_2d_to_origin_3d(region, rv3d, coord)
    direction = region_2d_to_vector_3d(region, rv3d, coord)
    depsgraph = context.evaluated_depsgraph_get()
    hit, _point, _normal, _index, obj, _matrix = context.scene.ray_cast(
        depsgraph, origin, direction, distance=1.0e6)
    if not hit or obj is None:
        return None
    original = getattr(obj, 'original', obj)
    if original == armature or not original.visible_get(view_layer=context.view_layer):
        return None
    if original.name not in context.view_layer.objects or original.hide_select:
        return None
    return original


class ALLSET_OT_pose_empty_click(bpy.types.Operator):
    """Exit joint modes on an actual empty click in the main 3D viewport."""
    bl_idname = 'allset.pose_empty_click'
    bl_label = 'Maya Joint Empty Click Watch'
    bl_options = {'INTERNAL'}
    _area_ptr = None
    _press = None

    def invoke(self, context, event):
        self._area_ptr = context.area.as_pointer()
        self._press = None
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if not _enabled(context) or context.area is None or context.area.as_pointer() != self._area_ptr:
            _pose_watch_areas.discard(self._area_ptr)
            return {'CANCELLED'}
        if event.type != 'LEFTMOUSE':
            return {'PASS_THROUGH'}
        from ..operators import joint_selection
        # Move Skinned Joints handles clicks in the viewport keymap.
        if joint_selection.moving_skinned(context):
            self._press = None
            return {'PASS_THROUGH'}
        # A click, not a box-select, drag, or transform-gizmo movement.
        if event.value == 'PRESS':
            self._press = (event.mouse_region_x, event.mouse_region_y) if (
                context.region and context.region.type == 'WINDOW'
                and not (event.shift or event.ctrl or event.alt or event.oskey)) else None
            return {'PASS_THROUGH'}
        if event.value != 'RELEASE':
            return {'PASS_THROUGH'}
        press = self._press
        self._press = None
        if press is None or context.region is None or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        x, y = event.mouse_region_x, event.mouse_region_y
        if min(x, y) < 0 or x >= context.region.width or y >= context.region.height:
            return {'PASS_THROUGH'}
        if (x - press[0]) ** 2 + (y - press[1]) ** 2 > 36:
            return {'PASS_THROUGH'}

        # pointers, looked up when the timer runs: the window may close in between (#36)
        win_ptr, area_ptr = context.window.as_pointer(), context.area.as_pointer()

        def check():
            from .. import live_refs
            win, area = live_refs.find_area(area_ptr, win_ptr)
            try:
                if area is None:
                    return None
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                if region is None:
                    return None
                with bpy.context.temp_override(window=win, area=area, region=region):
                    ctx = bpy.context
                    obj = ctx.view_layer.objects.active
                    # Pose mode: select_priority decides every click (a control stays in Pose; #171 —
                    # head-tail lines missed custom-shape controls and dropped Pose ~60 ms after the pick)
                    if (obj is not None and obj.type == 'ARMATURE' and obj.mode == 'EDIT'
                            and not joint_selection.moving_skinned(ctx)):
                        # Give joints priority even if a mesh is visible behind them.
                        if not _click_hits_joint(ctx, obj, x, y):
                            other = _other_object_under_click(ctx, obj, x, y)
                            bpy.ops.object.mode_set(mode='OBJECT')
                            if other is not None:
                                # Edit Mode locks Blender's normal object selection.
                                # Explicitly transfer selection after leaving the mode.
                                for selected in tuple(ctx.selected_objects):
                                    selected.select_set(False)
                                other.select_set(True)
                                ctx.view_layer.objects.active = other
                            area.tag_redraw()
            except (ReferenceError, RuntimeError, AttributeError, TypeError, ValueError):
                pass
            return None
        # Delay until Blender's own selection event has finished.
        bpy.app.timers.register(check, first_interval=0.06)
        return {'PASS_THROUGH'}


_pose_watch_areas = set()


class ALLSET_OT_skinned_handle_click(bpy.types.Operator):
    """Keep editing skinned joints when Blender picks a transform handle."""
    bl_idname = 'allset.skinned_handle_click'
    bl_label = 'Move Skinned Joints Handle Click'
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        from ..operators import joint_selection, manip
        return joint_selection.moving_skinned(context) and manip.from_xform_gizmo(context)

    def invoke(self, context, _event):
        # Consume a handle click before it reaches viewport selection.
        return {'FINISHED'}


def _ensure_pose_watch():
    if bpy.app.background:
        return None
    try:
        for window in bpy.context.window_manager.windows:
            from .status_line import main_view3d
            area, region = main_view3d(window.screen)
            if area is None or region is None:
                continue
            ptr = area.as_pointer()
            if ptr in _pose_watch_areas:
                continue
            with bpy.context.temp_override(window=window, area=area, region=region):
                if _enabled(bpy.context):
                    bpy.ops.allset.pose_empty_click('INVOKE_DEFAULT')
                    _pose_watch_areas.add(ptr)
    except (RuntimeError, ReferenceError, AttributeError):
        pass
    return 1.0


# Outliner clicks occur in a separate editor, so the viewport's modal click
# watcher cannot detect them. Observe actual Outliner object-row selection.
_outliner_watch_areas = set()


class ALLSET_OT_joint_outliner_select(bpy.types.Operator):
    """Leave armature joint mode when a different object is picked in the Outliner."""
    bl_idname = 'allset.joint_outliner_select'
    bl_label = 'Maya Joint Outliner Selection Watch'
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        self._area_ptr = context.area.as_pointer()
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        area = context.area
        if (area is None or area.as_pointer() != self._area_ptr
                or area.type != 'OUTLINER' or not _enabled(context)):
            _outliner_watch_areas.discard(self._area_ptr)
            return {'CANCELLED'}
        if event.type != 'LEFTMOUSE' or event.value != 'RELEASE':
            return {'PASS_THROUGH'}
        if context.region is None or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        # pointers, looked up when the timer runs: the window may close in between (#36)
        win_ptr, area_ptr = context.window.as_pointer(), area.as_pointer()

        # Blender updates selected_ids on completion of the Outliner click.
        def after_selection():
            from .. import live_refs
            win, area = live_refs.find_area(area_ptr, win_ptr)
            try:
                if area is None or area.type != 'OUTLINER':
                    return None
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                if region is None:
                    return None
                with bpy.context.temp_override(window=win, area=area, region=region):
                    ctx = bpy.context
                    if not _enabled(ctx):
                        return None
                    selected = [item for item in ctx.selected_ids if isinstance(item, bpy.types.Object)]
                    if len(selected) != 1:
                        return None
                    target = selected[0]
                    active = ctx.view_layer.objects.active
                    if (active is None or active.type != 'ARMATURE'
                            or active.mode not in {'EDIT', 'POSE'} or target == active
                            or target.name not in ctx.view_layer.objects
                            or target.hide_select):
                        return None
                    from .status_line import main_view3d
                    view, view_region = main_view3d(win.screen)
                    if view is None or view_region is None:
                        return None
                    with bpy.context.temp_override(window=win, area=view, region=view_region):
                        bpy.ops.object.mode_set(mode='OBJECT')
                        for ob in tuple(ctx.view_layer.objects.selected):
                            ob.select_set(False)
                        target.select_set(True)
                        ctx.view_layer.objects.active = target
                        _last_armature_target[win.as_pointer()] = None
                        view.tag_redraw()
                    area.tag_redraw()
            except (RuntimeError, ReferenceError, AttributeError, TypeError, ValueError):
                pass
            return None
        bpy.app.timers.register(after_selection, first_interval=0.06)
        return {'PASS_THROUGH'}


def _ensure_outliner_watch():
    if bpy.app.background:
        return None
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type != 'OUTLINER' or area.as_pointer() in _outliner_watch_areas:
                    continue
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                if region is None:
                    continue
                with bpy.context.temp_override(window=win, area=area, region=region):
                    if _enabled(bpy.context):
                        bpy.ops.allset.joint_outliner_select('INVOKE_DEFAULT')
                        _outliner_watch_areas.add(area.as_pointer())
    except (RuntimeError, ReferenceError, AttributeError):
        pass
    return 1.0
