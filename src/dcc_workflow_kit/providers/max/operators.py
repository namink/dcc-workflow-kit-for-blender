# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format, error_text as _dcc_ui_error
import math
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from mathutils import Matrix, Quaternion, Vector
from . import runtime

class Active:

    @classmethod
    def poll(cls, context):
        return runtime.is_active()
_active_region = [0]

def set_active_region(region):
    _active_region[0] = region.as_pointer() if region else 0

def viewport_override(context):
    """The active viewport: the region last clicked (Max's yellow-bordered view)."""
    windows = [context.window] + [w for w in context.window_manager.windows if w != context.window]
    first = None
    for window in windows:
        if window is None or window.scene != context.scene:
            continue
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type != 'WINDOW':
                    continue
                if region.as_pointer() == _active_region[0]:
                    return dict(window=window, area=area, region=region)
                if first is None or (context.area == area and first['area'] != area):
                    first = dict(window=window, area=area, region=region)
    if first is None:
        raise RuntimeError(_msg('No 3D viewport is open'))
    if context.area and context.area.type == 'VIEW_3D' and context.region and (context.region.type == 'WINDOW'):
        return dict(window=context.window, area=context.area, region=context.region)
    return first

class BSM_OT_environment(bpy.types.Operator):
    bl_idname = 'bsm.environment'
    bl_label = _msg('Switch Environment')
    bl_description = _msg('Switch between the original Blender workspace and Blender Max')
    mode: EnumProperty(items=(('BLENDER', _msg('Blender'), ''), ('STUDIO', _msg('Blender Max'), '')), translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        if self.mode == 'STUDIO' and runtime.is_active():
            primary = next((w for w in bpy.data.workspaces if w.get('bsm_primary_workspace')), None)
            if primary:
                context.window.workspace = primary
                return {'FINISHED'}
        runtime.request(self.mode == 'STUDIO')
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')
REGION_TOOLS = {'RECT': 'builtin.select_box', 'CIRCLE': 'builtin.select_circle', 'FENCE': 'builtin.select_lasso', 'LASSO': 'builtin.select_lasso', 'PAINT': 'builtin.select_circle'}

class BSM_OT_tool(Active, bpy.types.Operator):
    bl_idname = 'bsm.tool'
    bl_label = _msg('Select Transform Tool')
    tool: EnumProperty(items=tuple(((x, x.title(), '') for x in ('SELECT', 'MOVE', 'ROTATE', 'SCALE'))), translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        state = context.window_manager.bsm
        state.active_creation = ''
        max_tools = context.mode == 'OBJECT'
        tools = {'SELECT': REGION_TOOLS.get(state.region_type, 'builtin.select_box'), 'MOVE': 'bsm.max_move' if max_tools else 'builtin.move', 'ROTATE': 'bsm.max_rotate' if max_tools else 'builtin.rotate', 'SCALE': 'bsm.max_scale' if max_tools else 'builtin.scale'}
        with context.temp_override(**viewport_override(context)):
            bpy.ops.wm.tool_set_by_id(name=tools[self.tool])
            context.space_data.show_gizmo = True
            context.space_data.show_gizmo_tool = True
        runtime.redraw()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')
VIEW_ROTATIONS = {'TOP': Quaternion((1, 0, 0, 0)), 'BOTTOM': Quaternion((0, 1, 0, 0)), 'FRONT': Quaternion((math.sqrt(0.5), math.sqrt(0.5), 0, 0)), 'BACK': Quaternion((0, 0, math.sqrt(0.5), math.sqrt(0.5))), 'LEFT': Quaternion((0.5, 0.5, -0.5, -0.5)), 'RIGHT': Quaternion((0.5, 0.5, 0.5, 0.5))}

def view_name(r3d):
    """Max viewport label: Top/Front/... for axis views, else Perspective/Orthographic/Camera."""
    if r3d.view_perspective == 'CAMERA':
        camera = bpy.context.scene.camera
        return camera.name if camera else _msg('Camera')
    if r3d.view_perspective == 'ORTHO':
        for (name, rotation) in VIEW_ROTATIONS.items():
            if abs(rotation.dot(r3d.view_rotation)) > 0.9999:
                return name.title()
        return _msg('Orthographic')
    return _msg('Perspective')

class BSM_OT_view(Active, bpy.types.Operator):
    bl_idname = 'bsm.view'
    bl_label = _msg('Viewport Direction')
    view: EnumProperty(items=tuple(((x, x.title(), '') for x in ('FRONT', 'BACK', 'LEFT', 'RIGHT', 'TOP', 'BOTTOM', 'PERSP', 'ORTHO', 'CAMERA'))), translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        from .commands import record_view
        override = viewport_override(context)
        record_view(context, override['area'])
        r3d = override['region'].data
        if self.view == 'PERSP':
            r3d.view_perspective = 'PERSP'
        elif self.view == 'ORTHO':
            r3d.view_perspective = 'ORTHO'
        elif self.view == 'CAMERA':
            if context.scene.camera is None:
                self.report({'WARNING'}, _dcc_ui_text(_msg('No cameras in scene')))
                return {'CANCELLED'}
            r3d.view_perspective = 'CAMERA'
        else:
            r3d.view_rotation = VIEW_ROTATIONS[self.view]
            r3d.view_perspective = 'ORTHO'
        runtime.redraw()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')
VIEW_LIGHT_TYPES = {'SPOT', 'SUN', 'AREA'}

class BSM_OT_view_object(Active, bpy.types.Operator):
    """Look through a camera or a spot/directional light in the active viewport"""
    bl_idname = 'bsm.view_object'
    bl_label = _msg('View Through Object')
    name: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        from .commands import record_view
        obj = context.scene.objects.get(self.name)
        if obj is None or not (obj.type == 'CAMERA' or (obj.type == 'LIGHT' and obj.data.type in VIEW_LIGHT_TYPES)):
            self.report({'WARNING'}, _dcc_ui_text(_dcc_format('{0} is not a camera or a spot/directional light in this scene', self.name)))
            return {'CANCELLED'}
        override = viewport_override(context)
        record_view(context, override['area'])
        r3d = override['region'].data
        if obj.type == 'CAMERA':
            context.scene.camera = obj
            r3d.view_perspective = 'CAMERA'
        else:
            rotation = obj.matrix_world.to_quaternion()
            r3d.view_perspective = 'PERSP'
            r3d.view_rotation = rotation
            r3d.view_location = obj.matrix_world.translation + rotation @ Vector((0, 0, -r3d.view_distance))
        runtime.redraw()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def _view_object_menu(layout, context, objects, empty):
    """Max's POV > Cameras and Lights lists: the scene's objects by name."""
    current = context.scene.camera
    if not objects:
        row = layout.row()
        row.enabled = False
        row.label(text=_dcc_ui_text(empty))
    for obj in sorted(objects, key=lambda o: o.name.lower()):
        icon = 'RADIOBUT_ON' if obj == current else 'OUTLINER_OB_CAMERA' if obj.type == 'CAMERA' else 'OUTLINER_OB_LIGHT'
        layout.operator('bsm.view_object', text=_dcc_ui_text(obj.name), icon=icon).name = obj.name

class BSM_MT_view_cameras(bpy.types.Menu):
    bl_label = _msg('Cameras')

    def draw(self, context):
        _view_object_menu(self.layout, context, [o for o in context.scene.objects if o.type == 'CAMERA'], _msg('No cameras in the scene'))
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_MT_view_lights(bpy.types.Menu):
    bl_label = _msg('Lights')

    def draw(self, context):
        _view_object_menu(self.layout, context, [o for o in context.scene.objects if o.type == 'LIGHT' and o.data.type in VIEW_LIGHT_TYPES], _msg('No spot or directional lights in the scene'))
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_shading(Active, bpy.types.Operator):
    bl_idname = 'bsm.shading'
    bl_label = _msg('Viewport Display')
    mode: EnumProperty(items=(('WIRE', _msg('Wireframe'), ''), ('EDGES', _msg('Edged Faces'), ''), ('GRID', _msg('Grid'), '')), translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        with context.temp_override(**viewport_override(context)):
            space = context.space_data
            if self.mode == 'WIRE':
                space.shading.type = 'SOLID' if space.shading.type == 'WIREFRAME' else 'WIREFRAME'
            elif self.mode == 'EDGES':
                space.overlay.show_wireframes = not space.overlay.show_wireframes
                space.overlay.wireframe_threshold = 1.0
            else:
                show = not space.overlay.show_floor
                space.overlay.show_floor = show
                space.overlay.show_ortho_grid = show
                if context.workspace.get('bsm_primary_workspace'):
                    context.window_manager.bsm.finite_grid = not context.window_manager.bsm.finite_grid
                    space.overlay.show_floor = False
                    space.overlay.show_ortho_grid = False
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_frame_selected(Active, bpy.types.Operator):
    bl_idname = 'bsm.frame_selected'
    bl_label = _msg('Zoom Extents Selected')

    def execute(self, context):
        from .commands import record_view
        override = viewport_override(context)
        record_view(context, override['area'])
        with context.temp_override(**override):
            if context.selected_objects:
                bpy.ops.view3d.view_selected(use_all_regions=False)
            else:
                bpy.ops.view3d.view_all(center=False)
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_maximize(Active, bpy.types.Operator):
    bl_idname = 'bsm.maximize'
    bl_label = _msg('Expert Mode')

    def execute(self, context):
        with context.temp_override(**viewport_override(context)):
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def _window_regions(area):
    return [r for r in area.regions if r.type == 'WINDOW']
QUAD_SLOTS = ('TOP', 'FRONT', 'LEFT', 'PERSP')
_quad_memory = {}

def _view_state(r3d):
    return (r3d.view_location.copy(), r3d.view_rotation.copy(), r3d.view_distance, r3d.view_perspective)

def _quad_slots(area):
    """The four regions of a quad layout by slot, once Blender has laid them out."""
    regions = sorted(_window_regions(area), key=lambda r: (-r.y, r.x))
    if len(regions) != 4 or any((r.data is None for r in regions)) or len({(r.x, r.y) for r in regions}) != 4:
        return None
    return dict(zip(QUAD_SLOTS, sorted(regions[:2], key=lambda r: r.x) + sorted(regions[2:], key=lambda r: r.x)))

class BSM_OT_quad_view(Active, bpy.types.Operator):
    """Maximize Viewport Toggle (Alt+W): one viewport or Max's Top/Front/Left/Perspective"""
    bl_idname = 'bsm.quad_view'
    bl_label = _msg('Maximize Viewport Toggle')

    def execute(self, context):
        override = viewport_override(context)
        (area, region) = (override['area'], override['region'])
        space = area.spaces.active
        if space.region_quadviews:
            slots = _quad_slots(area)
            if slots:
                maximized = next((slot for (slot, r) in slots.items() if r == region), 'PERSP')
                _quad_memory[area.as_pointer()] = ({slot: _view_state(r.data) for (slot, r) in slots.items()}, maximized)
            state = _view_state(region.data)
            with context.temp_override(**override):
                bpy.ops.screen.region_quadview()
            main = space.region_3d
            (main.view_location, main.view_rotation, main.view_distance, main.view_perspective) = state
            set_active_region(None)
        else:
            main = space.region_3d
            persp = (main.view_location.copy(), main.view_rotation.copy(), main.view_distance)
            memory = _quad_memory.pop(area.as_pointer(), None)
            if memory:
                (views, maximized) = memory
                memory = ({**views, maximized: _view_state(main)}, maximized)
            with context.temp_override(**override):
                bpy.ops.screen.region_quadview()
            if not arrange_quad(area, persp, memory):
                attempts = [0]

                def later():
                    attempts[0] += 1
                    try:
                        if arrange_quad(area, persp, memory) or attempts[0] > 20:
                            runtime.redraw()
                            return None
                    except ReferenceError:
                        return None
                    return 0.02
                bpy.app.timers.register(later, first_interval=0.02)
        runtime.redraw()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def arrange_quad(area, persp=None, memory=None):
    """Top (upper left), Front (upper right), Left (lower left), Perspective (lower right);
    with memory ({slot: view state}, maximized slot), the views Alt+W kept instead."""
    space = area.spaces.active
    for r3d in space.region_quadviews:
        r3d.lock_rotation = False
    slots = _quad_slots(area)
    if slots is None:
        return False
    if memory:
        (views, maximized) = memory
        for (slot, region) in slots.items():
            r3d = region.data
            (r3d.view_location, r3d.view_rotation, r3d.view_distance, r3d.view_perspective) = views[slot]
            if slot == maximized:
                set_active_region(region)
        return True
    distance = persp[2] if persp else 15
    for (name, region) in slots.items():
        r3d = region.data
        if name == 'PERSP':
            r3d.view_perspective = 'PERSP'
            if persp:
                (r3d.view_location, r3d.view_rotation, r3d.view_distance) = persp
            set_active_region(region)
        else:
            r3d.view_rotation = VIEW_ROTATIONS[name]
            r3d.view_perspective = 'ORTHO'
            r3d.view_location = persp[0] if persp else (0, 0, 0)
            r3d.view_distance = distance * 0.6
    return True

class BSM_OT_component(Active, bpy.types.Operator):
    bl_idname = 'bsm.component'
    bl_label = _msg('Sub-object Level')
    bl_options = {'REGISTER', 'UNDO'}
    level: IntProperty(default=0, min=0, max=5, translation_context=_msg('DCCWorkflowKit.Max'))

    @classmethod
    def poll(cls, context):
        obj = context.view_layer.objects.active
        return runtime.is_active() and obj is not None and (obj.type == 'MESH')

    def execute(self, context):
        wm = context.window_manager
        obj = context.view_layer.objects.active
        prim = getattr(obj, 'bsm_prim', None)
        if self.level and prim is not None and prim.kind:
            from . import params
            self.report({'INFO'}, _dcc_ui_text(_dcc_format('{0} has no sub-object levels: Convert to Editable Poly first', params.NAMES.get(prim.kind, 'Primitive'))))
            return {'CANCELLED'}
        with context.temp_override(**viewport_override(context)):
            if self.level == 0 or (obj.mode == 'EDIT' and wm.bsm.component == self.level):
                if obj.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
                wm.bsm.component = 0
                runtime.redraw()
                return {'FINISHED'}
            if obj.mode != 'EDIT':
                bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_mode(type={1: 'VERT', 2: 'EDGE', 3: 'EDGE', 4: 'FACE', 5: 'FACE'}[self.level])
            wm.bsm.component = self.level
            wm.bsm.active_modifier = ''
        runtime.redraw()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')
CREATE_KINDS = (('BOX', _msg('Box')), ('CONE', _msg('Cone')), ('SPHERE', _msg('Sphere')), ('GEOSPHERE', _msg('GeoSphere')), ('CYLINDER', _msg('Cylinder')), ('TUBE', _msg('Tube')), ('TORUS', _msg('Torus')), ('PYRAMID', _msg('Pyramid')), ('TEAPOT', _msg('Teapot')), ('PLANE', _msg('Plane')), ('TEXTPLUS', _msg('TextPlus')), ('CHAMFER_BOX', _msg('ChamferBox')), ('CHAMFER_CYL', _msg('ChamferCyl')), ('CAPSULE', _msg('Capsule')), ('BOOLEAN', _msg('Boolean')), ('LINE', _msg('Line')), ('RECTANGLE', _msg('Rectangle')), ('CIRCLE', _msg('Circle')), ('ELLIPSE', _msg('Ellipse')), ('ARC', _msg('Arc')), ('DONUT', _msg('Donut')), ('NGON', _msg('NGon')), ('STAR', _msg('Star')), ('TEXT', _msg('Text')), ('HELIX', _msg('Helix')), ('OMNI', _msg('Omni')), ('TARGET_SPOT', _msg('Target Spot')), ('FREE_SPOT', _msg('Free Spot')), ('TARGET_DIRECT', _msg('Target Direct')), ('FREE_DIRECT', _msg('Free Direct')), ('SKYLIGHT', _msg('Skylight')), ('TARGET_LIGHT', _msg('Target Light')), ('FREE_LIGHT', _msg('Free Light')), ('SUN_POSITIONER', _msg('Sun Positioner')), ('AREA', _msg('Arnold Light')), ('FREE_CAMERA', _msg('Free Camera')), ('TARGET_CAMERA', _msg('Target Camera')), ('PHYSICAL_CAMERA', _msg('Physical Camera')), ('DUMMY', _msg('Dummy')), ('POINT', _msg('Point')), ('GRID', _msg('Grid')), ('ARROW', _msg('Arrow')), ('TAPE', _msg('Tape')), ('PROTRACTOR', _msg('Protractor')), ('COMPASS', _msg('Compass')), ('WIND', _msg('Wind')), ('VORTEX', _msg('Vortex')), ('DRAG', _msg('Drag')), ('PUSH', _msg('Push')), ('MOTOR', _msg('Motor')), ('PATH_FOLLOW', _msg('Path Follow')), ('DISPLACE_WARP', _msg('Displace')), ('GRAVITY', _msg('Gravity')), ('TURBULENCE', _msg('Turbulence')), ('BONES', _msg('Bones')), ('CV_SURFACE', _msg('CV Surf')), ('POINT_SURFACE', _msg('Point Surf')), ('CV_CURVE', _msg('CV Curve')), ('POINT_CURVE', _msg('Point Curve')))
LEGACY = {'EMPTY': 'POINT', 'CAMERA': 'FREE_CAMERA', 'SUN': 'FREE_DIRECT', 'SPOT': 'FREE_SPOT', 'BONE': 'BONES', 'FORCE': 'PUSH'}
UNSUPPORTED = {'TAPE', 'PROTRACTOR'}
NAMES = dict(CREATE_KINDS)
TARGETED = {'TARGET_SPOT', 'TARGET_DIRECT', 'TARGET_LIGHT', 'TARGET_CAMERA', 'PHYSICAL_CAMERA'}
SHAPES = {'LINE', 'RECTANGLE', 'CIRCLE', 'ELLIPSE', 'ARC', 'DONUT', 'NGON', 'STAR', 'HELIX'}
PRIMITIVES = tuple(((k, n, 'NONE') for (k, n) in CREATE_KINDS))

def unique_name(base):
    from .commands import unique_name as unique
    return unique(base.replace(' ', ''))

def _poly(points, closed, name, dimensions='2D'):
    data = bpy.data.curves.new(name, 'CURVE')
    data.dimensions = dimensions
    if dimensions == '2D':
        data.fill_mode = 'NONE'
    for loop in points:
        spline = data.splines.new('POLY')
        spline.points.add(len(loop) - 1)
        for (point, co) in zip(spline.points, loop):
            point.co = (*co, 1)
        spline.use_cyclic_u = closed
    return data

def _circle(radius, count=32, rx=None):
    rx = radius if rx is None else rx
    return [(rx * math.cos(2 * math.pi * i / count), radius * math.sin(2 * math.pi * i / count), 0) for i in range(count)]

def shape_data(kind, name, size=1.0):
    if kind == 'LINE':
        return _poly([[(0, 0, 0), (size, 0, 0)]], False, name)
    if kind == 'RECTANGLE':
        return _poly([[(-size, -size * 0.6, 0), (size, -size * 0.6, 0), (size, size * 0.6, 0), (-size, size * 0.6, 0)]], True, name)
    if kind == 'CIRCLE':
        data = bpy.data.curves.new(name, 'CURVE')
        (data.dimensions, data.fill_mode) = ('2D', 'NONE')
        spline = data.splines.new('BEZIER')
        spline.bezier_points.add(3)
        k = 0.5523 * size
        for (point, (x, y), (hx, hy)) in zip(spline.bezier_points, ((size, 0), (0, size), (-size, 0), (0, -size)), ((0, k), (-k, 0), (0, -k), (k, 0))):
            point.co = (x, y, 0)
            point.handle_left = (x - hx, y - hy, 0)
            point.handle_right = (x + hx, y + hy, 0)
        spline.use_cyclic_u = True
        return data
    if kind == 'ELLIPSE':
        return _poly([_circle(size * 0.6, 48, size)], True, name)
    if kind == 'ARC':
        return _poly([[(size * math.cos(math.pi * i / 24), size * math.sin(math.pi * i / 24), 0) for i in range(25)]], False, name)
    if kind == 'DONUT':
        return _poly([_circle(size), _circle(size * 0.6)], True, name)
    if kind == 'NGON':
        return _poly([_circle(size, 6)], True, name)
    if kind == 'STAR':
        return _poly([[((size if i % 2 == 0 else size * 0.5) * math.cos(math.pi * i / 6), (size if i % 2 == 0 else size * 0.5) * math.sin(math.pi * i / 6), 0) for i in range(12)]], True, name)
    if kind == 'HELIX':
        return _poly([[(size * math.cos(t / 8), size * math.sin(t / 8), t * size * 0.02) for t in range(0, 8 * 16)]], False, name, '3D')
    raise KeyError(kind)

def _target(context, obj, location):
    target = bpy.data.objects.new(obj.name + '.Target', None)
    target.empty_display_type = 'CUBE'
    target.empty_display_size = 0.1
    target.location = location
    (context.collection or context.scene.collection).objects.link(target)
    constraint = obj.constraints.new('TRACK_TO')
    constraint.target = target
    constraint.track_axis = 'TRACK_NEGATIVE_Z'
    constraint.up_axis = 'UP_Y'
    return target

def create_object(context, kind, matrix, size=1.0, target=None):
    """Create one Max object type at ``matrix``; returns the new object."""
    from . import params
    kind = LEGACY.get(kind, kind)
    location = matrix.translation.copy()
    collection = context.collection or context.scene.collection
    name = unique_name(NAMES.get(kind, kind.title()))

    def link(obj):
        collection.objects.link(obj)
        obj.matrix_world = matrix
        return obj
    if kind in params.DEFAULTS:
        return params.new_object(context, kind, matrix)
    if kind in {'CHAMFER_BOX', 'CHAMFER_CYL', 'CAPSULE'}:
        base = {'CHAMFER_BOX': 'BOX', 'CHAMFER_CYL': 'CYLINDER', 'CAPSULE': 'CYLINDER'}[kind]
        obj = params.new_object(context, base, matrix)
        obj.name = obj.data.name = name
        mod = obj.modifiers.new(_msg('Fillet'), 'BEVEL')
        mod.segments = 3 if kind != 'CAPSULE' else 8
        mod.width = 0.1 if kind != 'CAPSULE' else obj.bsm_prim.radius * 0.98
        mod.limit_method = 'ANGLE'
        mod.use_clamp_overlap = True
        return obj
    if kind == 'BOOLEAN':
        obj = context.view_layer.objects.active
        if obj is None or obj.type != 'MESH':
            raise RuntimeError(_msg('Select an operand object for Boolean'))
        obj.modifiers.new(_msg('Boolean'), 'BOOLEAN')
        context.window_manager.bsm.active_modifier = obj.modifiers[-1].name
        return obj
    if kind in {'TEXTPLUS', 'TEXT'}:
        data = bpy.data.curves.new(name, 'FONT')
        data.body = _msg('Text')
        data.size = size
        if kind == 'TEXTPLUS':
            data.extrude = 0.0
        obj = link(bpy.data.objects.new(name, data))
    elif kind in SHAPES:
        obj = link(bpy.data.objects.new(name, shape_data(kind, name, size)))
    elif kind in {'OMNI', 'FREE_LIGHT', 'TARGET_LIGHT'}:
        obj = link(bpy.data.objects.new(name, bpy.data.lights.new(name, 'POINT')))
        obj.data.energy = 1000
    elif kind in {'TARGET_SPOT', 'FREE_SPOT'}:
        obj = link(bpy.data.objects.new(name, bpy.data.lights.new(name, 'SPOT')))
        obj.data.energy = 1000
    elif kind in {'TARGET_DIRECT', 'FREE_DIRECT', 'SUN_POSITIONER'}:
        obj = link(bpy.data.objects.new(name, bpy.data.lights.new(name, 'SUN')))
        if kind == 'SUN_POSITIONER':
            obj.rotation_euler = (math.radians(45), 0, math.radians(30))
    elif kind == 'AREA':
        obj = link(bpy.data.objects.new(name, bpy.data.lights.new(name, 'AREA')))
        obj.data.energy = 500
    elif kind == 'SKYLIGHT':
        world = context.scene.world or bpy.data.worlds.new(_msg('World'))
        context.scene.world = world
        world.color = (1, 1, 1)
        if world.node_tree and world.node_tree.nodes.get(_msg('Background')):
            world.node_tree.nodes[_msg('Background')].inputs[_msg('Color')].default_value = (1, 1, 1, 1)
        raise RuntimeError(_msg('Skylight maps to the scene World background (set to white)'))
    elif kind in {'FREE_CAMERA', 'TARGET_CAMERA', 'PHYSICAL_CAMERA'}:
        obj = link(bpy.data.objects.new(name, bpy.data.cameras.new(name)))
        if context.scene.camera is None:
            context.scene.camera = obj
    elif kind in {'DUMMY', 'POINT', 'ARROW', 'COMPASS'}:
        obj = link(bpy.data.objects.new(name, None))
        obj.empty_display_type = {'DUMMY': 'CUBE', 'POINT': 'PLAIN_AXES', 'ARROW': 'SINGLE_ARROW', 'COMPASS': 'CIRCLE'}[kind]
        obj.empty_display_size = size * 0.5
    elif kind == 'GRID':
        mesh = bpy.data.meshes.new(name)
        import bmesh
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=10, y_segments=10, size=size)
        bm.to_mesh(mesh)
        bm.free()
        obj = link(bpy.data.objects.new(name, mesh))
        obj.display_type = 'WIRE'
        obj.hide_render = True
    elif kind in {'WIND', 'VORTEX', 'DRAG', 'PUSH', 'MOTOR', 'PATH_FOLLOW', 'DISPLACE_WARP', 'GRAVITY', 'TURBULENCE'}:
        obj = link(bpy.data.objects.new(name, None))
        obj.empty_display_type = 'SINGLE_ARROW' if kind in {'WIND', 'GRAVITY', 'PUSH'} else 'CIRCLE'
        obj.empty_display_size = size
        field = {'WIND': 'WIND', 'VORTEX': 'VORTEX', 'DRAG': 'DRAG', 'PUSH': 'FORCE', 'MOTOR': 'VORTEX', 'PATH_FOLLOW': 'GUIDE', 'DISPLACE_WARP': 'TEXTURE', 'GRAVITY': 'FORCE', 'TURBULENCE': 'TURBULENCE'}[kind]
        with context.temp_override(object=obj, active_object=obj):
            bpy.ops.object.forcefield_toggle()
        obj.field.type = field
        if kind == 'GRAVITY':
            obj.field.shape = 'PLANE'
            obj.field.strength = -9.8
    elif kind == 'BONES':
        data = bpy.data.armatures.new(name)
        obj = link(bpy.data.objects.new(name, data))
        context.view_layer.update()
        with context.temp_override(**viewport_override(context), object=obj, active_object=obj, selected_objects=[obj]):
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bone = data.edit_bones.new(_msg('Bone001'))
            (bone.head, bone.tail) = ((0, 0, 0), (0, 0, size))
            bpy.ops.object.mode_set(mode='OBJECT')
    elif kind in {'CV_SURFACE', 'POINT_SURFACE', 'CV_CURVE', 'POINT_CURVE'}:
        with context.temp_override(**viewport_override(context)):
            if kind.endswith('SURFACE'):
                bpy.ops.surface.primitive_nurbs_surface_surface_add(location=location)
            else:
                bpy.ops.curve.primitive_nurbs_curve_add(location=location)
        obj = context.view_layer.objects.active
        obj.name = name
        obj.matrix_world = matrix
    else:
        raise RuntimeError(_dcc_format('{0} is not available in Blender', NAMES.get(kind, kind)))
    if obj.type == 'LIGHT':
        obj['bsm_light'] = kind
    if kind in TARGETED:
        _target(context, obj, target if target is not None else location + matrix.to_3x3() @ Vector((0, 0, -1)) * max(1.0, size * 3))
    for other in context.view_layer.objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj

class BSM_OT_create(Active, bpy.types.Operator):
    bl_idname = 'bsm.create'
    bl_label = _msg('Create Object')
    bl_options = {'REGISTER', 'UNDO'}
    kind: EnumProperty(items=tuple(((x, label, '') for (x, label) in CREATE_KINDS)) + tuple(((k, k.title(), '') for k in LEGACY)), translation_context=_msg('DCCWorkflowKit.Max'))

    @classmethod
    def description(cls, context, properties):
        kind = LEGACY.get(properties.kind, properties.kind)
        return _msg('Not available in Blender') if kind in UNSUPPORTED else _dcc_format('Create {0}', NAMES.get(kind, kind))

    def execute(self, context):
        state = context.window_manager.bsm
        active = context.view_layer.objects.active
        if active and active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            obj = create_object(context, self.kind, Matrix.Translation(context.scene.cursor.location))
        except RuntimeError as error:
            self.report({'WARNING'}, _dcc_ui_error(error))
            return {'CANCELLED'}
        if state.next_name and obj.name != state.next_name:
            obj.name = state.next_name
        obj.color = state.next_color
        from .interactions import next_random_color
        next_random_color(state)
        obj['bsm_primitive'] = LEGACY.get(self.kind, self.kind)
        state.created_this_session = obj.name
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')
MODIFIERS = (('SUBSURF', _msg('TurboSmooth'), ''), ('BEVEL', _msg('Chamfer'), ''), ('SOLIDIFY', _msg('Shell'), ''), ('MIRROR', _msg('Symmetry'), ''), ('ARRAY', _msg('Array'), ''), ('SIMPLE_DEFORM', _msg('Bend'), ''), ('SMOOTH', _msg('Relax'), ''), ('DECIMATE', _msg('ProOptimizer'), ''), ('TRIANGULATE', _msg('Turn To Mesh'), ''), ('BOOLEAN', _msg('Boolean'), ''), ('DISPLACE', _msg('Displace'), ''), ('LATTICE', 'FFD', ''), ('SHRINKWRAP', _msg('Conform'), ''), ('NODES', _msg('Geometry Nodes'), ''))

class BSM_OT_modifier(Active, bpy.types.Operator):
    bl_idname = 'bsm.modifier'
    bl_label = _msg('Add Modifier')
    bl_options = {'REGISTER', 'UNDO'}
    kind: EnumProperty(items=MODIFIERS, translation_context=_msg('DCCWorkflowKit.Max'))

    @classmethod
    def poll(cls, context):
        obj = context.view_layer.objects.active
        return runtime.is_active() and obj and (obj.type in {'MESH', 'CURVE', 'FONT', 'SURFACE'}) and obj.is_editable

    def execute(self, context):
        obj = context.view_layer.objects.active
        try:
            mod = obj.modifiers.new(dict(((a, b) for (a, b, _) in MODIFIERS))[self.kind], self.kind)
        except RuntimeError as error:
            self.report({'WARNING'}, _dcc_ui_error(error))
            return {'CANCELLED'}
        if self.kind == 'SIMPLE_DEFORM':
            mod.deform_method = 'BEND'
        if self.kind == 'BEVEL':
            mod.width = 0.1
        context.window_manager.bsm.active_modifier = mod.name
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_modifier_action(Active, bpy.types.Operator):
    bl_idname = 'bsm.modifier_action'
    bl_label = _msg('Modifier Stack Action')
    bl_options = {'REGISTER', 'UNDO'}
    modifier: StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))
    action: EnumProperty(items=tuple(((x, x.title(), '') for x in ('UP', 'DOWN', 'REMOVE', 'APPLY'))), translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or self.modifier not in obj.modifiers:
            return {'CANCELLED'}
        if self.action == 'APPLY' and obj.mode != 'OBJECT':
            self.report({'WARNING'}, _dcc_ui_text(_msg('Return to Object level to apply a modifier')))
            return {'CANCELLED'}
        op = {'UP': 'modifier_move_up', 'DOWN': 'modifier_move_down', 'REMOVE': 'modifier_remove', 'APPLY': 'modifier_apply'}[self.action]
        try:
            getattr(bpy.ops.object, op)(modifier=self.modifier)
        except RuntimeError as error:
            self.report({'WARNING'}, _dcc_ui_error(error))
            return {'CANCELLED'}
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_clone(Active, bpy.types.Operator):
    bl_idname = 'bsm.clone'
    bl_label = _msg('Clone Options')
    bl_options = {'REGISTER', 'UNDO'}
    kind: EnumProperty(name=_msg('Object'), items=(('COPY', _msg('Copy'), _msg('Independent object data')), ('INSTANCE', _msg('Instance'), _msg('Shared object data')), ('REFERENCE', _msg('Reference'), _msg('Shared object data (Blender has no one-way references)'))), translation_context=_msg('DCCWorkflowKit.Max'))
    controller: EnumProperty(name=_msg('Controller'), items=(('COPY', _msg('Copy'), ''), ('INSTANCE', _msg('Instance'), '')), translation_context=_msg('DCCWorkflowKit.Max'))
    name: StringProperty(name=_msg('Name'), translation_context=_msg('DCCWorkflowKit.Max'))
    count: IntProperty(name=_msg('Number of Copies'), default=1, min=1, max=100, options={'HIDDEN'}, translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        objects = context.selected_objects
        if not objects:
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select objects to clone')))
            return {'CANCELLED'}
        base = objects[0].name.rstrip('0123456789') or objects[0].name
        self.name = unique_name(base)
        return context.window_manager.invoke_props_dialog(self, width=320, title=_msg('Clone Options'))

    def draw(self, context):
        row = self.layout.row()
        column = row.box().column()
        column.label(text=_dcc_ui_text(_msg('Object')))
        column.prop(self, 'kind', expand=True)
        column = row.box().column()
        column.label(text=_dcc_ui_text(_msg('Controller')))
        column.prop(self, 'controller', expand=True)
        self.layout.prop(self, 'name')

    def execute(self, context):
        if context.mode != 'OBJECT' or not context.selected_objects:
            self.report({'WARNING'}, _dcc_ui_text(_msg('Select objects at Object level')))
            return {'CANCELLED'}
        from .commands import clone_object
        source = list(context.selected_objects)
        for obj in source:
            obj.select_set(False)
        first = True
        for _ in range(self.count):
            for obj in source:
                copy = clone_object(context, obj, 'COPY' if self.kind == 'COPY' else 'INSTANCE')
                if self.controller == 'COPY' and copy.animation_data and copy.animation_data.action:
                    copy.animation_data.action = copy.animation_data.action.copy()
                if first and self.name and (len(source) == 1):
                    copy.name = self.name
                first = False
                copy.select_set(True)
                context.view_layer.objects.active = copy
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_select_lock(Active, bpy.types.Operator):
    bl_idname = 'bsm.select_lock'
    bl_label = _msg('Selection Lock Toggle')

    def execute(self, context):
        locked = any(('_bsm_selectable_before_lock' in o for o in context.scene.objects))
        if locked:
            for obj in bpy.data.objects:
                if '_bsm_selectable_before_lock' in obj:
                    obj.hide_select = bool(obj['_bsm_selectable_before_lock'])
                    del obj['_bsm_selectable_before_lock']
        else:
            selected = set(context.selected_objects)
            for obj in context.scene.objects:
                if obj not in selected:
                    obj['_bsm_selectable_before_lock'] = obj.hide_select
                    obj.hide_select = True
        context.window_manager.bsm.selection_locked = not locked
        runtime.redraw()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_editor(Active, bpy.types.Operator):
    bl_idname = 'bsm.editor'
    bl_label = _msg('Open Editor')
    kind: EnumProperty(items=tuple(((x, n, '') for (x, n) in (('MATERIAL', _msg('Slate Material Editor')), ('COMPACT', _msg('Compact Material Editor')), ('MATERIAL_LAST', _msg('Material Editor')), ('GRAPH', _msg('Curve Editor')), ('DOPESHEET', _msg('Dope Sheet')), ('UV', _msg('Edit UVWs')), ('RENDER', _msg('Render Setup')), ('SCENE', _msg('Scene Explorer')), ('CONSOLE', _msg('Scripting Listener'))))), translation_context=_msg('DCCWorkflowKit.Max'))
    floating: BoolProperty(name=_msg('Floating Window'), default=True, translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        from . import editor_host
        kind = self.kind
        prefs = runtime.preferences()
        if kind == 'MATERIAL_LAST':
            kind = prefs.last_material_editor if prefs else context.window_manager.bsm.last_material_editor
        if kind in {'MATERIAL', 'COMPACT'}:
            context.window_manager.bsm.last_material_editor = kind
            if prefs:
                prefs.last_material_editor = kind
        if kind == 'CONSOLE':
            return editor_host.open_native(context, 'CONSOLE', _msg('Scripting Listener'))
        return editor_host.open_editor(context, kind, self.floating)
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_compact_material(Active, bpy.types.Operator):
    bl_idname = 'bsm.compact_material'
    bl_label = _msg('Compact Material Editor')

    def invoke(self, context, event):
        return bpy.ops.bsm.editor(kind='COMPACT')

    def execute(self, context):
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_shortcuts(bpy.types.Operator):
    bl_idname = 'bsm.shortcuts'
    bl_label = _msg('Blender Max Shortcut Reference')

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def execute(self, context):
        return {'FINISHED'}

    def draw(self, context):
        from .keymap import KEY_TABLE
        grid = self.layout.grid_flow(columns=2, even_columns=True)
        for (key, label, *_) in KEY_TABLE:
            row = grid.row()
            row.label(text=_dcc_ui_text(label))
            row.label(text=_dcc_ui_text(key))
        self.layout.label(text=_dcc_ui_text(_msg('MMB pan · Alt+MMB orbit · Ctrl+Alt+MMB zoom · Wheel zoom · Right-click quad menu')))
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_quad_menu(Active, bpy.types.Operator):
    bl_idname = 'bsm.quad_menu'
    bl_label = _msg('Quad Menu')

    def invoke(self, context, event):
        from . import quad
        return quad.open_quad(context, event)

    def execute(self, context):
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def _flatten(context, axis):
    value = [1, 1, 1]
    value[axis] = 0
    bpy.ops.transform.resize(value=value, orient_type='LOCAL', constraint_axis=tuple((i == axis for i in range(3))))

def _material_id(context, select):
    import bmesh
    obj = context.view_layer.objects.active
    bm = bmesh.from_edit_mesh(obj.data)
    index = context.window_manager.bsm.material_id - 1
    for face in bm.faces:
        if select:
            face.select_set(face.material_index == index)
        elif face.select:
            face.material_index = index
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)

def _nurms(context):
    obj = context.view_layer.objects.active
    mod = obj.modifiers.get('NURMS')
    if mod:
        obj.modifiers.remove(mod)
    else:
        mod = obj.modifiers.new('NURMS', 'SUBSURF')
        mod.levels = 1

def _create_shape(context):
    obj = context.view_layer.objects.active
    bpy.ops.mesh.duplicate()
    bpy.ops.mesh.separate(type='SELECTED')
    bpy.ops.object.mode_set(mode='OBJECT')
    shapes = [o for o in context.selected_objects if o != obj]
    for shape in shapes:
        with context.temp_override(active_object=shape, object=shape, selected_objects=[shape], selected_editable_objects=[shape]):
            bpy.ops.object.convert(target='CURVE')
        shape.name = unique_name(_msg('Shape'))
        shape.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')

def _auto_smooth(context):
    bpy.ops.mesh.faces_shade_smooth()
    bpy.ops.mesh.set_sharpness_by_angle(angle=math.radians(30))

def _attach(context):
    return bpy.ops.bsm.pick_object('INVOKE_DEFAULT', purpose='ATTACH')
MESH_COMMANDS = {'EXTRUDE': ('mesh.extrude_region_move', {}), 'EXTRUDE_VERTS': ('mesh.extrude_vertices_move', {}), 'EXTRUDE_EDGES': ('mesh.extrude_edges_move', {}), 'BEVEL': ('mesh.bevel', {'affect': 'EDGES'}), 'CHAMFER': ('mesh.bevel', {'affect': 'EDGES'}), 'CHAMFER_VERTS': ('mesh.bevel', {'affect': 'VERTICES'}), 'BEVEL_POLY': ('mesh.inset', {'depth': 0.0}), 'OUTLINE': ('transform.resize', {}), 'INSET': ('mesh.inset', {}), 'BRIDGE': ('mesh.bridge_edge_loops', {}), 'CONNECT': ('mesh.subdivide', {}), 'CONNECT_EDGES': ('mesh.subdivide_edgering', {'number_cuts': 1}), 'CONNECT_VERTS': ('mesh.vert_connect_path', {}), 'WELD': ('mesh.remove_doubles', {'threshold': 0.001}), 'TARGET_WELD': ('mesh.merge', {'type': 'LAST'}), 'COLLAPSE': ('mesh.merge', {'type': 'CENTER'}), 'DISSOLVE_VERTS': ('mesh.dissolve_verts', {}), 'DISSOLVE_EDGES': ('mesh.dissolve_edges', {}), 'DISSOLVE': ('mesh.dissolve_mode', {}), 'BREAK': ('mesh.edge_split', {'type': 'VERT'}), 'SPLIT_EDGES': ('mesh.edge_split', {'type': 'EDGE'}), 'INSERT_VERTEX': ('mesh.subdivide', {'number_cuts': 1}), 'POKE': ('mesh.poke', {}), 'CREATE_SHAPE': _create_shape, 'TURN': ('mesh.edge_rotate', {'use_ccw': False}), 'CAP': ('mesh.edge_face_add', {}), 'FLIP': ('mesh.flip_normals', {}), 'RETRIANGULATE': ('mesh.beautify_fill', {}), 'QUADRIFY': ('mesh.tris_convert_to_quads', {}), 'REPEAT': ('screen.repeat_last', {}), 'CREATE_FACE': ('mesh.edge_face_add', {}), 'ATTACH': _attach, 'DETACH': ('mesh.separate', {'type': 'SELECTED'}), 'SLICE': ('mesh.bisect', {}), 'CUT': ('mesh.knife_tool', {}), 'LOOPCUT': ('mesh.loopcut_slide', {}), 'MSMOOTH': ('mesh.subdivide', {'smoothness': 1.0}), 'TESSELLATE': ('mesh.subdivide', {'number_cuts': 1}), 'PLANAR': ('transform.resize', {'value': (1, 1, 0), 'orient_type': 'NORMAL', 'constraint_axis': (False, False, True)}), 'FLATTEN_X': lambda c: _flatten(c, 0), 'FLATTEN_Y': lambda c: _flatten(c, 1), 'FLATTEN_Z': lambda c: _flatten(c, 2), 'RELAX': ('mesh.vertices_smooth', {'factor': 0.5}), 'HIDE': ('mesh.hide', {'unselected': False}), 'UNHIDE': ('mesh.reveal', {}), 'HIDE_UNSELECTED': ('mesh.hide', {'unselected': True}), 'DELETE_LOOSE': ('mesh.delete_loose', {}), 'SET_ID': lambda c: _material_id(c, False), 'SELECT_ID': lambda c: _material_id(c, True), 'AUTO_SMOOTH': _auto_smooth, 'CLEAR_SMOOTH': ('mesh.faces_shade_flat', {}), 'NURMS': _nurms, 'SHRINK': ('mesh.select_less', {}), 'GROW': ('mesh.select_more', {}), 'RING': ('mesh.loop_multi_select', {'ring': True}), 'LOOP': ('mesh.loop_multi_select', {'ring': False}), 'NORMALS': ('mesh.normals_make_consistent', {}), 'UV': ('uv.unwrap', {})}
OBJECT_LEVEL = {'NURMS', 'ATTACH', 'REPEAT'}
INTERACTIVE = {'EXTRUDE', 'EXTRUDE_VERTS', 'EXTRUDE_EDGES', 'BEVEL', 'CHAMFER', 'CHAMFER_VERTS', 'BEVEL_POLY', 'OUTLINE', 'INSET', 'SLICE', 'CUT', 'LOOPCUT', 'RELAX'}
RELEASE_CONFIRM = {'mesh.extrude_region_move': _msg('TRANSFORM_OT_translate'), 'mesh.extrude_vertices_move': _msg('TRANSFORM_OT_translate'), 'mesh.extrude_edges_move': _msg('TRANSFORM_OT_translate'), 'mesh.loopcut_slide': _msg('TRANSFORM_OT_edge_slide'), 'mesh.bevel': None, 'mesh.inset': None, 'transform.resize': None}
MESH_ACTIONS = (('EXTRUDE', _msg('Extrude'), 'mesh.extrude_region_move'), ('BEVEL', _msg('Chamfer'), 'mesh.bevel'), ('INSET', _msg('Inset'), 'mesh.inset'), ('BRIDGE', _msg('Bridge'), 'mesh.bridge_edge_loops'), ('CONNECT', _msg('Connect'), 'mesh.subdivide'), ('WELD', _msg('Weld'), 'mesh.remove_doubles'), ('CUT', _msg('Cut'), 'mesh.knife_tool'), ('LOOPCUT', _msg('SwiftLoop'), 'mesh.loopcut_slide'), ('FLIP', _msg('Flip'), 'mesh.flip_normals'), ('NORMALS', _msg('Unify Normals'), 'mesh.normals_make_consistent'), ('DETACH', _msg('Detach'), 'mesh.separate'), ('DISSOLVE', _msg('Remove'), 'mesh.dissolve_mode'), ('RELAX', _msg('Relax'), 'mesh.vertices_smooth'), ('UV', _msg('Unwrap'), 'uv.unwrap'))

class BSM_OT_mesh_action(Active, bpy.types.Operator):
    bl_idname = 'bsm.mesh_action'
    bl_label = _msg('Editable Poly Command')
    bl_options = {'REGISTER', 'UNDO'}
    action: EnumProperty(items=tuple(((x, x.replace('_', ' ').title(), '') for x in MESH_COMMANDS)), translation_context=_msg('DCCWorkflowKit.Max'))
    release_confirm: BoolProperty(name=_msg('Confirm on Release'), description=_msg('Set the amount when the mouse button is released (dragging from the command); otherwise the next click sets it'), options={'SKIP_SAVE', 'HIDDEN'}, translation_context=_msg('DCCWorkflowKit.Max'))

    @classmethod
    def poll(cls, context):
        obj = context.view_layer.objects.active
        return runtime.is_active() and obj is not None and (obj.type == 'MESH')

    def interactive_values(self, context, name, values):
        values = dict(values)
        if name in RELEASE_CONFIRM:
            step = RELEASE_CONFIRM[name]
            if step:
                values[step] = {**values.get(step, {}), 'release_confirm': self.release_confirm}
            else:
                values['release_confirm'] = self.release_confirm
        obj = context.view_layer.objects.active
        if self.action == 'EXTRUDE' and obj.data.total_face_sel:
            values[_msg('TRANSFORM_OT_translate')] = {**values[_msg('TRANSFORM_OT_translate')], 'orient_type': 'NORMAL', 'constraint_axis': (False, False, True)}
        return values

    def execute(self, context):
        if self.action not in OBJECT_LEVEL and context.mode != 'EDIT_MESH':
            self.report({'WARNING'}, _dcc_ui_text(_msg('Choose a sub-object level first (1-5)')))
            return {'CANCELLED'}
        command = MESH_COMMANDS[self.action]
        with context.temp_override(**viewport_override(context)):
            try:
                if callable(command):
                    command(context)
                else:
                    (name, values) = command
                    (group, method) = name.split('.')
                    if self.action in INTERACTIVE:
                        getattr(getattr(bpy.ops, group), method)('INVOKE_DEFAULT', **self.interactive_values(context, name, values))
                    else:
                        getattr(getattr(bpy.ops, group), method)('EXEC_DEFAULT', **values)
            except RuntimeError as error:
                self.report({'WARNING'}, _dcc_ui_error(error).split('\n')[0])
                return {'CANCELLED'}
        runtime.redraw()
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')
CLASSES = (BSM_OT_environment, BSM_OT_tool, BSM_OT_view, BSM_OT_view_object, BSM_MT_view_cameras, BSM_MT_view_lights, BSM_OT_shading, BSM_OT_frame_selected, BSM_OT_maximize, BSM_OT_quad_view, BSM_OT_component, BSM_OT_create, BSM_OT_modifier, BSM_OT_modifier_action, BSM_OT_clone, BSM_OT_select_lock, BSM_OT_editor, BSM_OT_compact_material, BSM_OT_shortcuts, BSM_OT_quad_menu, BSM_OT_mesh_action)
