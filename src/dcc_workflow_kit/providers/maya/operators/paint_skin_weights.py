# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Paint Skin Weights on Blender weight paint: entering with the skeleton posable and the first influence
picked, the tool option values applied to the brush and unified paint settings (``apply_paint_settings``), Flood, and
leaving for Select / Move / Rotate / Scale (``leave_weight_paint``, ``allset.weight_paint_exit``). The paint workspace
itself is weight_paint.py.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty

from .. import compat
from . import units
from .skin_cluster import (NORMALIZE, NORMALIZE_PROP, PAINT_SEEN, armature_modifier, influences, normalize_mode,
                           show_pose_in_components, skinned_mesh)

PAINT_WIRE = "allset_paint_wire"     # mesh ID prop: Paint Skin Weights turned its wireframe on once


# --- Paint Skin Weights --------------------------------------------------------------------------

def first_influence(mesh):
    """The influence Maya hilites first: the skeleton's joints depth first from the root (armature bone order for
    siblings), the first that is an influence."""
    mod = armature_modifier(mesh)
    if mod is None or mod.object is None:
        return None
    groups = {vg.name: vg for vg in influences(mesh, mod)}
    todo = [b for b in mod.object.data.bones if b.parent is None]
    while todo:
        b = todo.pop(0)
        if b.name in groups:
            return groups[b.name]
        todo[0:0] = list(b.children)
    return None


def leave_weight_paint(context):
    """Release paint and its helper skeleton; retain the painted mesh as the selection."""
    if context.mode != 'PAINT_WEIGHT':
        return False
    mesh = context.active_object
    mod = armature_modifier(mesh) if mesh is not None else None
    arm = mod.object if mod is not None else None
    bpy.ops.object.mode_set(mode='OBJECT')
    if arm is not None and arm.name in context.view_layer.objects:
        if arm.mode == 'POSE':
            context.view_layer.objects.active = arm
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            finally:
                context.view_layer.objects.active = mesh
        arm.select_set(False)
    if mesh is not None:
        mesh.select_set(True)
        context.view_layer.objects.active = mesh
    return True


def set_view_tool(context, name):
    """Tool changes from the dock/menu also target the real modeling viewport."""
    from ..ui.status_line import main_view3d
    area, region = main_view3d(context.screen)
    if area is not None and region is not None:
        with context.temp_override(window=context.window, area=area, region=region):
            return bpy.ops.wm.tool_set_by_id(name=name, space_type='VIEW_3D')
    return bpy.ops.wm.tool_set_by_id(name=name, space_type='VIEW_3D')


class ALLSET_OT_weight_paint_exit(bpy.types.Operator):
    """Leave Paint Skin Weights and activate Maya's Select, Move, Rotate, or Scale tool"""
    bl_idname = "allset.weight_paint_exit"
    bl_label = "Leave Paint Skin Weights"
    bl_options = {'REGISTER', 'UNDO'}

    tool: EnumProperty(items=(
        ('builtin.select_box', 'Select', 'Q: leave painting and select objects'),
        ('builtin.move', 'Move', 'W: leave painting and move objects'),
        ('builtin.rotate', 'Rotate', 'E: leave painting and rotate objects'),
        ('builtin.scale', 'Scale', 'R: leave painting and scale objects'),
    ), default='builtin.select_box', options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'PAINT_WEIGHT'

    def execute(self, context):
        leave_weight_paint(context)
        return set_view_tool(context, self.tool)


# Maya Paint Skin Weights Tool settings with a Blender meaning; the window
# (operators/option_windows_rig.py) passes them, a plain menu click leaves the brush as the user set it in the dock.
PAINT_OPERATIONS = (("REPLACE", "Replace", "Blender brush blend Mix"), ("ADD", "Add", "Blender brush blend Add"),
                    ("SCALE", "Scale", "Blender brush blend Multiply"), ("SMOOTH", "Smooth", "Blender's Blur tool"))
PAINT_BLEND = {"REPLACE": 'MIX', "ADD": 'ADD', "SCALE": 'MUL'}
PAINT_PROFILES = (("GAUSSIAN", "Gaussian", "Smooth falloff"), ("SOFT", "Soft", "Sphere falloff"),
                  ("SOLID", "Solid", "Constant: no falloff"))
PROFILE_CURVE = {"GAUSSIAN": 'SMOOTH', "SOFT": 'SPHERE', "SOLID": 'CONSTANT'}
PAINT_FIELDS = ("operation", "profile", "normalize", "opacity", "value", "radius", "screen_projection",
                "show_wireframe", "xray_joints")


def _brush_set(brush, name, value):
    """Set a weight paint brush setting; False when the brush can't be edited (a linked asset)."""
    try:
        setattr(brush, name, value)
        return True
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return False


def _maya_start(context, first):
    """Maya's Paint Skin Weights paints one influence with a Paint operation (Replace by default) at the tool's
    Opacity. Blender 5.3 starts new scenes (and 5.2 files) with an accumulating low-strength Add brush and Multi-Paint
    on: the tool starts with the Replace draw brush instead of that brush, and with Multi-Paint off the ``first`` time
    it opens on a skin (afterwards Multi-Paint stays as the user sets it)."""
    ts = context.tool_settings
    if first and compat.MULTIPAINT_STARTS_ON:
        ts.use_multipaint = False
    if compat.is_adding_start_brush(ts.weight_paint.brush):
        from .weight_paint import activate_brush
        try:
            activate_brush(context, 'DRAW', 'MIX', essentials=True)
        except (RuntimeError, TypeError):
            pass


def apply_paint_settings(context, mesh, arm, v):
    """Maya tool values ``v`` (PAINT_FIELDS) -> the weight paint tool, brush, unified settings and overlays.
    Returns the names Blender refused (e.g. a brush that is a linked asset)."""
    ts = context.tool_settings
    ups = compat.unified_paint_settings(ts, "weight_paint")
    refused = []
    if v["operation"] == "SMOOTH":
        try:
            from .weight_paint import activate_brush
            activate_brush(context, 'BLUR')
        except (RuntimeError, TypeError):
            refused.append("operation")
    else:
        try:
            from .weight_paint import activate_brush
            activate_brush(context, 'DRAW')
        except (RuntimeError, TypeError):
            pass
    brush = ts.weight_paint.brush
    if brush is not None:
        if v["operation"] in PAINT_BLEND and not _brush_set(brush, "blend", PAINT_BLEND[v["operation"]]):
            refused.append("operation")
        curve_prop = compat.brush_falloff_props(brush)[0]
        if not _brush_set(brush, curve_prop, PROFILE_CURVE[v["profile"]]):
            refused.append("profile")
    # Maya Value / Opacity / Radius(U) are tool settings: Blender's unified paint settings hold them for every brush
    for name in compat.UNIFIED_NAMES:
        compat.set_unified(ups, brush, name, True)
    ups.weight = max(0.0, min(1.0, v["value"]))
    ups.strength = max(0.0, min(1.0, v["opacity"]))
    if v["screen_projection"]:
        ups.use_locked_size = 'VIEW'
    else:
        ups.use_locked_size = 'SCENE'            # Maya's radius is a world size (cm) unless Screen projection is on
        compat.set_unprojected_radius(ups, max(1e-4, v["radius"] * units.maya_unit(context.scene)))
    if v["normalize"] is not None:              # None: deformer weights, never normalized
        mesh[NORMALIZE_PROP] = v["normalize"]
        ts.use_auto_normalize = v["normalize"] == "INTERACTIVE"
    else:
        ts.use_auto_normalize = False
    space = context.space_data
    if space is not None and space.type == 'VIEW_3D':
        space.overlay.show_paint_wire = v["show_wireframe"]
    if arm is not None:
        arm.show_in_front = v["xray_joints"]
    return refused


class ALLSET_OT_paint_skin_weights(bpy.types.Operator):
    """Maya Paint Skin Weights: weight paint the skinned mesh with its skeleton posable (Ctrl+click picks a joint)"""
    bl_idname = "allset.paint_skin_weights"
    bl_label = "Paint Skin Weights"
    bl_options = {'REGISTER', 'UNDO'}

    operation: EnumProperty(name="Paint operation", items=PAINT_OPERATIONS, default="REPLACE", options={'SKIP_SAVE'})
    profile: EnumProperty(name="Profile", items=PAINT_PROFILES, default="SOFT", options={'SKIP_SAVE'})
    normalize: EnumProperty(name="Normalize Weights", items=NORMALIZE, default="INTERACTIVE", options={'SKIP_SAVE'})
    opacity: FloatProperty(name="Opacity", default=1.0, min=0.0, max=1.0, options={'SKIP_SAVE'})
    value: FloatProperty(name="Value", default=1.0, min=0.0, max=1.0, options={'SKIP_SAVE'})
    radius: FloatProperty(name="Radius(U)", default=1.0, min=0.0001, options={'SKIP_SAVE'})
    screen_projection: BoolProperty(name="Screen projection", default=False, options={'SKIP_SAVE'})
    show_wireframe: BoolProperty(name="Show wireframe", default=True, options={'SKIP_SAVE'})
    xray_joints: BoolProperty(name="XRay Joints", default=True, options={'SKIP_SAVE'})
    settings: BoolProperty(name="Apply Tool Settings", default=False, options={'SKIP_SAVE', 'HIDDEN'},
                           description="Apply the Maya tool settings above (the option window); a plain click keeps "
                                       "the brush as it is")
    classic: BoolProperty(name="Classic Tool", default=False, options={'SKIP_SAVE', 'HIDDEN'},
                          description="Start the paint tool even when the mesh has skin layers (Skin Tools paints "
                                      "through it)")

    def _settings(self, context, mesh):
        if not self.settings:
            return
        refused = apply_paint_settings(context, mesh, armature_modifier(mesh).object,
                                       {k: getattr(self, k) for k in PAINT_FIELDS})
        if refused:
            self.report({'WARNING'}, "Blender kept its own " + ", ".join(refused) + " (the brush is a linked asset)")

    def execute(self, context):
        if context.mode == 'PAINT_WEIGHT':
            if self.settings:               # the option window while painting: new settings, stay in the tool
                mesh = context.active_object
                if mesh is not None and armature_modifier(mesh):
                    self._settings(context, mesh)
                return {'FINISHED'}
            leave_weight_paint(context)
            set_view_tool(context, 'builtin.select_box')
            return {'FINISHED'}
        mesh = skinned_mesh(context)
        if mesh is None:
            self.report({'WARNING'}, "Select a skinned mesh (Skin > Bind Skin first)")
            return {'CANCELLED'}
        # like Maya's Skin Tools: once the skin has layers, Paint Skin Weights opens Skin Tools (its Paint button
        # paints a layer); the option window still sets up the classic tool
        from . import skin_layers
        if not self.classic and not self.settings and skin_layers.is_initialized(mesh):
            try:
                return bpy.ops.allset.skin_tools()
            except RuntimeError as ex:
                self.report({'WARNING'}, str(ex))
                return {'CANCELLED'}
        arm = armature_modifier(mesh).object
        if context.active_object is not None and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for ob in context.selected_objects:
            ob.select_set(False)
        arm.select_set(True)
        mesh.select_set(True)
        context.view_layer.objects.active = mesh
        # the skeleton goes to pose mode with it. Blender brings back the tool last used in weight paint: a Select
        # mode's select tool stays in paint here, unlike the Tool Box's Select
        from ..ui import toolbox
        toolbox.KEEP_PAINT[0] = True
        try:
            bpy.ops.paint.weight_paint_toggle()
        finally:
            toolbox.KEEP_PAINT[0] = False
        show_pose_in_components(mesh)                    # component mode keeps the pose (Maya)
        current = context.workspace.tools.from_space_view3d_mode('PAINT_WEIGHT', create=False)
        # Older sessions may have left a selection/transform tool remembered
        # inside paint mode. Re-entering the paint tool must restore a brush.
        from ..ui.toolbox import MAYA_TOOLS
        if current is None or not current.idname or current.idname in MAYA_TOOLS:
            set_view_tool(context, 'builtin.brush')
        # Maya hilites the first influence (joint1, the skeleton's root) the first time the tool opens on a skin and
        # keeps the picked one afterwards. Bind Skin leaves
        # Blender's last made group (the last joint) active: the first entry picks by hierarchy (#146).
        first = first_influence(mesh)
        seen = bool(mesh.get(PAINT_SEEN))
        if first is not None and (mesh.vertex_groups.active is None or not seen):
            mesh.vertex_groups.active_index = first.index
        _maya_start(context, not seen)
        mesh[PAINT_SEEN] = True
        if not mesh.get(PAINT_WIRE):                     # the wireframe is on when painting starts, like Maya
            from ..ui.status_line import main_view3d
            area, _region = main_view3d(context.screen)
            if area is not None:
                area.spaces.active.overlay.show_paint_wire = True
            mesh[PAINT_WIRE] = True
        # Maya keeps a vertex selection made before the tool and floods only it
        # (Maya): Blender shows that selection only with the vertex
        # mask on. A full selection is the whole mesh anyway, so the mask stays as it was then.
        shown = [v.select for v in mesh.data.vertices if not v.hide]
        if any(shown) and not all(shown) and not mesh.data.use_paint_mask:
            mesh.data.use_paint_mask_vertex = True
        # Maya Bind Skin makes the skinCluster with Normalize Weights = Interactive (normalizeWeights 1): painting a
        # joint takes weight from the others so every vertex keeps a total of 1 (#20). Blender's factory
        # Auto Normalize is off; Skin > Normalize Weights > Disable still turns it off while painting. The skin's own
        # mode comes from Bind Skin's Normalize weights.
        context.tool_settings.use_auto_normalize = normalize_mode(mesh) == "INTERACTIVE"
        self._settings(context, mesh)
        return {'FINISHED'}


class ALLSET_OT_flood_weights(bpy.types.Operator):
    """Flood the current operation and opacity into the active influence, respecting masks and locked weights"""
    bl_idname = "allset.flood_weights"
    bl_label = "Flood"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return context.mode == 'PAINT_WEIGHT' and ob is not None and ob.vertex_groups.active is not None

    def execute(self, context):
        from .weight_paint import flood
        try:
            return flood(context)
        except (ValueError, RuntimeError) as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
