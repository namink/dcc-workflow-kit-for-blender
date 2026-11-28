# SPDX-License-Identifier: GPL-3.0-or-later
"""Paint Skin Weights settings: one property group of options per weight action, made from the native operator's own
options (``ACTIONS``, ``_FIELDS``), the workspace settings on the window manager (``ALLSET_PG_weight_workspace``,
read with ``state``), ``active`` (weight painting a mesh) and the brush helpers (``viewport``, ``brush_kind``,
``activate_brush``). The operators: weight_paint; Flood: weight_paint_flood."""
from contextlib import contextmanager

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty,
                       StringProperty)

from .. import compat
from . import skin

# Each native operation keeps its own settings, including all scalar operator options.
ACTIONS = {
    'SET': ('Set Weight', 'paint.weight_set'),
    'NORMALIZE_ALL': ('Normalize All', 'object.vertex_group_normalize_all'),
    'NORMALIZE': ('Normalize Influence', 'object.vertex_group_normalize'),
    'MIRROR': ('Mirror Weights', 'object.vertex_group_mirror'),
    'INVERT': ('Invert Weights', 'object.vertex_group_invert'),
    'CLEAN': ('Prune Small Weights', 'object.vertex_group_clean'),
    'QUANTIZE': ('Quantize Weights', 'object.vertex_group_quantize'),
    'LEVELS': ('Weight Levels', 'object.vertex_group_levels'),
    'SMOOTH': ('Smooth Weights', 'object.vertex_group_smooth'),
    'LIMIT': ('Limit Influences', 'object.vertex_group_limit_total'),
    'TRANSFER': ('Transfer Weights', 'object.data_transfer'),
    'AUTO': ('Automatic Weights', 'paint.weight_from_bones'),
    'ENVELOPE': ('Bone Envelope Weights', 'paint.weight_from_bones'),
}
SCOPE = [('ACTIVE', 'Active influence', 'Only the active vertex group'),
         ('BONE_SELECT', 'Selected joints', 'Groups belonging to selected pose bones'),
         ('BONE_DEFORM', 'Deform joints', 'All deforming bone groups'),
         ('ALL', 'All groups', 'All vertex groups, including non-joint groups')]
TRANSFER_FIELDS = {'vert_mapping', 'use_create', 'use_object_transform', 'use_auto_transform',
                   'use_max_distance', 'max_distance', 'ray_radius', 'layers_select_src',
                   'layers_select_dst', 'mix_mode', 'mix_factor'}


def native(name):
    module, op = name.split('.')
    return getattr(getattr(bpy.ops, module), op)


def _annotation(prop, action):
    kw = {'name': prop.name, 'description': prop.description}
    if prop.identifier == 'group_select_mode':
        return EnumProperty(**kw, items=SCOPE[1:] if action in {'NORMALIZE_ALL', 'LIMIT'} else SCOPE,
                            default='BONE_DEFORM' if action in {'NORMALIZE_ALL', 'LIMIT'} else 'ACTIVE')
    if prop.type == 'BOOLEAN':
        return BoolProperty(**kw, default=prop.default)
    if prop.type in {'INT', 'FLOAT'} and not prop.is_array:
        kw.update(default=prop.default, min=prop.hard_min, max=prop.hard_max)
        return (IntProperty if prop.type == 'INT' else FloatProperty)(**kw)
    if prop.type == 'ENUM':
        items = [(e.identifier, e.name, e.description) for e in prop.enum_items if e.identifier]
        if items and not prop.is_enum_flag:
            return EnumProperty(**kw, items=items, default=prop.default)
    return None


_SETTING_CLASSES = []
_FIELDS = {}
for _key, (_label, _op) in ACTIONS.items():
    _ann = {}
    for _p in native(_op).get_rna_type().properties:
        if _p.identifier == 'rna_type' or (_key == 'TRANSFER' and _p.identifier not in TRANSFER_FIELDS):
            continue
        _a = _annotation(_p, _key)
        if _a is not None:
            _ann[_p.identifier] = _a
    if _key == 'TRANSFER':
        _ann['source'] = PointerProperty(name='Source mesh', type=bpy.types.Object,
                                        poll=lambda self, ob: ob.type == 'MESH')
    _FIELDS[_key] = tuple(_ann)
    _SETTING_CLASSES.append(type('ALLSET_PG_weight_' + _key.lower(), (bpy.types.PropertyGroup,),
                                {'__annotations__': _ann, '__module__': __name__}))


def _normalize_get(self):
    return bpy.context.tool_settings.use_auto_normalize


def _normalize_set(self, value):
    bpy.context.tool_settings.use_auto_normalize = value
    mesh = bpy.context.active_object
    if mesh is not None and mesh.type == 'MESH':
        mesh[skin.NORMALIZE_PROP] = 'INTERACTIVE' if value else 'NONE'


def _normalize_mode_get(self):
    mesh = bpy.context.active_object
    ids = [k for k, _l, _d in skin.NORMALIZE]
    if mesh is not None and mesh.type == 'MESH' and mesh.get(skin.NORMALIZE_PROP) in ids:
        if mesh[skin.NORMALIZE_PROP] != 'INTERACTIVE' or bpy.context.tool_settings.use_auto_normalize:
            return ids.index(mesh[skin.NORMALIZE_PROP])
    return ids.index('INTERACTIVE' if bpy.context.tool_settings.use_auto_normalize else 'NONE')


def _normalize_mode_set(self, value):
    """Maya Normalize Weights Off / Interactive / Post: Interactive = Blender Auto Normalize; Post = weights left as
    painted and normalised by the deformation (Blender's Armature modifier divides by the weight sum)."""
    key = skin.NORMALIZE[value][0]
    bpy.context.tool_settings.use_auto_normalize = key == 'INTERACTIVE'
    mesh = bpy.context.active_object
    if mesh is not None and mesh.type == 'MESH':
        mesh[skin.NORMALIZE_PROP] = key


def _numbers_update(self, context):
    for area in context.screen.areas if context.screen else ():
        if area.type == 'VIEW_3D':
            area.tag_redraw()


class ALLSET_PG_weight_workspace(bpy.types.PropertyGroup):
    search: StringProperty(name='Find influence', options={'TEXTEDIT_UPDATE'})
    # Maya 2026 Sort: Alphabetically (natural order) / By Hierarchy (default) / Flat
    sort: EnumProperty(name='Sort', items=[('NAME', 'Alphabetically', 'Natural name order (joint2 before joint10)'),
                                         ('HIERARCHY', 'By Hierarchy', 'Joint hierarchy order'),
                                         ('INDEX', 'Flat', 'Influence order, no hierarchy')], default='HIERARCHY')
    paint_tool: StringProperty(default='', options={'HIDDEN'})
    # Select mode's selection shape (Box like Maya's marquee, or a Lasso); kept for the next Select mode
    select_shape: StringProperty(default='BOX', options={'HIDDEN'})
    show_all: BoolProperty(name='Include non-joint groups', default=False)
    locked_only: BoolProperty(name='Locked influences only', default=False)
    auto_normalize: BoolProperty(name='Auto normalize',
                                 description='Keep deform weights normalized while painting; remembered for this skin',
                                 get=_normalize_get, set=_normalize_set)
    # Tool Settings frames in Maya 2024+ order (Skin Clusters / Influences / Brush / Visualization / Stroke /
    # Stylus Pressure / Display), then the Blender-only extras (ui/paint_weights.SECTIONS)
    # frame defaults: Skin Clusters collapsed, Influences / Brush /
    # Visualization open, Stroke / Stylus Pressure / Display collapsed
    show_skin_clusters: BoolProperty(default=False)
    show_influences: BoolProperty(default=True)
    show_brush: BoolProperty(default=True)
    show_visualization: BoolProperty(default=True)
    show_stroke: BoolProperty(default=False)
    show_pressure: BoolProperty(default=False)
    show_display: BoolProperty(default=False)
    show_commands: BoolProperty(default=False)
    show_mask: BoolProperty(default=False)
    status: StringProperty(default='')
    # Maya 2026 fields the kit keeps itself (ctx_defaults)
    skin_cluster: IntProperty(name='Skin Cluster', default=0, min=0,
                              description='The skin cluster (Armature modifier) whose influences the list shows')
    normalize_mode: EnumProperty(name='Normalize Weights', items=skin.NORMALIZE, get=_normalize_mode_get,
                                 set=_normalize_mode_set)
    weight_type: EnumProperty(name='Weight Type', items=[('SKIN', 'Skin Weight', 'Paint the skin weights'),
                                                        ('DQ', 'DQ Blend Weight', 'Blender has no per-vertex dual '
                                                         'quaternion blend weight')], default='SKIN')
    min_value: FloatProperty(name='Min', default=0.0, min=0.0, max=1.0, description='Lowest weight Flood writes')
    max_value: FloatProperty(name='Max', default=1.0, min=0.0, max=1.0, description='Highest weight Flood writes')
    show_numbers: BoolProperty(name='Show Numbers', default=False, update=_numbers_update,
                               description="Draw the painted influence's weight at every vertex")
    number_places: IntProperty(name='Decimal Places', default=2, min=1, max=4)
    number_color: FloatVectorProperty(name='Number Color', subtype='COLOR', size=3, min=0.0, max=1.0,
                                      default=(1.0, 1.0, 0.0))
    number_color_ramp: BoolProperty(name='Color Ramp', default=False,
                                    description='Colour the numbers by weight (0 = Min color, 1 = Max color)')
    number_min_color: FloatVectorProperty(name='Weight 0', subtype='COLOR', size=3, min=0.0, max=1.0,
                                          default=(1.0, 1.0, 1.0))
    number_max_color: FloatVectorProperty(name='Weight 1', subtype='COLOR', size=3, min=0.0, max=1.0,
                                          default=(0.0, 0.0, 0.0))


# One settings group per Paint Weights action (above). Python 3.14 has no ``__annotations__`` name in a class body to
# update (PEP 649; Issue #176: "name '__annotations__' is not defined" on CachyOS right after install), so they are
# merged in after the class body, before registration.
ALLSET_PG_weight_workspace.__annotations__ = {
    **compat.own_annotations(ALLSET_PG_weight_workspace),
    **{key.lower(): PointerProperty(type=cls) for key, cls in zip(ACTIONS, _SETTING_CLASSES)}}


def state(context):
    return context.window_manager.allset_weight_workspace


def active(context):
    ob = context.active_object
    return context.mode == 'PAINT_WEIGHT' and ob is not None and ob.type == 'MESH'


@contextmanager
def viewport(context):
    from ..ui.status_line import main_view3d
    area, region = main_view3d(context.screen)
    if area is None or region is None:
        raise RuntimeError('Open a 3D View to paint skin weights')
    with context.temp_override(window=context.window, area=area, region=region):
        yield bpy.context


def brush_kind(brush):
    return getattr(brush, 'weight_brush_type', getattr(brush, 'weight_tool', 'DRAW')) if brush else ''


def brush_tool(context, kind):
    from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active as tools
    ids = [t.idname for entry in tools.tools_from_context(context)
           for t in (entry if type(entry) is tuple else (entry,)) if t is not None]
    suffix = {'BLUR': 'blur', 'AVERAGE': 'average', 'SMEAR': 'smear'}.get(kind)
    return next((name for name in ids if suffix and name.lower() == 'builtin_brush.' + suffix), 'builtin.brush')


def activate_brush(context, kind='DRAW', blend=None, essentials=False):
    """The weight brush of ``kind`` in the main 3D View (the current brush when it has that kind, else the essentials
    brush; ``essentials``: always the essentials brush), with ``blend`` set. Raises RuntimeError."""
    with viewport(context) as ctx:
        wp = ctx.tool_settings.weight_paint
        # what the brush shares (Value / Opacity / Radius) stays the same after the switch, like a Maya tool setting
        shared = compat.unified_switches(wp.unified_paint_settings, wp.brush)
        bpy.ops.wm.tool_set_by_id(name=brush_tool(ctx, kind))
        brush = wp.brush
        if essentials or brush is None or brush_kind(brush) != kind:
            bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS',
                                         relative_asset_identifier=compat.weight_brush_asset(kind))
            brush = wp.brush
        if brush is None or brush_kind(brush) != kind:
            raise RuntimeError('Choose a compatible weight brush from Brush Assets')
        compat.keep_unified_switches(wp.unified_paint_settings, brush, shared)
        if blend is not None and not skin._brush_set(brush, 'blend', blend):
            raise RuntimeError('This brush is read-only; make an editable copy from Brush Assets')
        return brush
