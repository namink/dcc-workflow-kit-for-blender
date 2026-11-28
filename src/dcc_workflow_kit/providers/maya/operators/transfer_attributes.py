# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesh > Transfer Attributes (#554), like Maya: the last selected mesh (Blender's active object) takes vertex
positions, vertex normals, UV sets and color sets from the other selected mesh. The transfer stays live as
construction history: a Data Transfer modifier (normals, UVs, colors) and, for positions, a Shrinkwrap modifier
(nearest surface point) on the target, with the source as their object.

The Transfer Attributes Options window has Maya's rows and starts at Vertex position Off, Vertex normal Off,
UV Sets All, Color Sets All, Sample space World, Search method Closest to point. Transferred normals are one normal
per vertex, read from the source surface at the closest point (interpolated), so a hard-edged target takes the
source's smooth shading. Options Blender has no way to sample by (UV sample space, Mirroring, Flip UVs, Color
borders) are shown greyed.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty

from .. import results
from .modify_maya import selection_order

ERR_SELECT = "Transfer Attributes: Select at least one source surface, then the target surface."
ERR_UV_SPACE = "Transfer Attributes: UV sample space is not available in Blender. Use World, Local or Component."

_ONOFF = (('OFF', "Off", ""), ('ON', "On", ""))
_SETS = (('OFF', "Off", ""), ('CURRENT', "Current", ""), ('ALL', "All", ""))


def _targets(context):
    """(sources, target): Maya's last selected mesh is the target, the others are sources."""
    obs = [o for o in selection_order(context) if o.type == 'MESH']
    if len(obs) < 2 or obs[-1] is not context.view_layer.objects.active:
        return [], None
    return obs[:-1], obs[-1]


def loop_mapping(sample_space, search_method):
    if sample_space in ('COMPONENT', 'TOPOLOGY'):
        return 'TOPOLOGY'
    return 'POLYINTERP_LNORPROJ' if search_method == 'ALONG_NORMAL' else 'POLYINTERP_NEAREST'


def _data_transfer(target, source, name, world):
    dt = target.modifiers.new(name, 'DATA_TRANSFER')
    dt.object = source
    dt.use_object_transform = world
    return dt


def add_transfer(context, source, target, positions, normals, uv_sets, color_sets, sample_space, search_method):
    """Add the modifiers that carry the transfer to ``target``; returns their names."""
    made = []
    world = sample_space != 'LOCAL'
    if positions and sample_space in ('WORLD', 'LOCAL'):
        sw = target.modifiers.new("Transfer Attributes Positions", 'SHRINKWRAP')
        sw.wrap_method = 'NEAREST_SURFACEPOINT'
        sw.target = source
        made.append(sw.name)
    mapping = loop_mapping(sample_space, search_method)
    if normals:
        # one normal per vertex, read where the vertex is: Blender's projection along a normal would use each face
        # corner's own normal and split a hard-edged target's vertices
        dt = _data_transfer(target, source, "Transfer Attributes Normals", world)
        dt.use_loop_data = True
        dt.data_types_loops = {'CUSTOM_NORMAL'}
        dt.loop_mapping = 'TOPOLOGY' if mapping == 'TOPOLOGY' else 'POLYINTERP_NEAREST'
        made.append(dt.name)
    if uv_sets != 'OFF' or color_sets != 'OFF':
        dt = _data_transfer(target, source, "Transfer Attributes", world)
        dt.use_loop_data = True
        dt.data_types_loops = ({'UV'} if uv_sets != 'OFF' else set()) | (
            {'COLOR_CORNER'} if color_sets != 'OFF' else set())
        dt.loop_mapping = mapping
        if color_sets != 'OFF':
            dt.use_vert_data = True
            dt.data_types_verts = {'COLOR_VERTEX'}
            dt.vert_mapping = 'TOPOLOGY' if mapping == 'TOPOLOGY' else 'POLYINTERP_NEAREST'
        for kind, mode in (("uv", uv_sets), ("vcol_loop", color_sets), ("vcol_vert", color_sets)):
            if mode == 'OFF':
                continue
            setattr(dt, f"layers_{kind}_select_src", 'ALL' if mode == 'ALL' else 'ACTIVE')
            setattr(dt, f"layers_{kind}_select_dst", 'NAME' if mode == 'ALL' else 'ACTIVE')
        made.append(dt.name)
        # the target gets the UV / color layers the source has (Maya makes the missing sets)
        with context.temp_override(object=target, active_object=target, selected_objects=[target],
                                   selected_editable_objects=[target]):
            try:
                bpy.ops.object.datalayout_transfer(modifier=dt.name)
            except RuntimeError:
                pass
    return made


class ALLSET_OT_transfer_attributes(bpy.types.Operator):
    """Maya Transfer Attributes: the last selected mesh takes vertex positions, normals, UV sets and color sets
    from the other selected mesh, live (press and hold the menu item for the Transfer Attributes Options)"""
    bl_idname = "allset.transfer_attributes"
    bl_label = "Transfer Attributes"
    bl_options = {'REGISTER', 'UNDO'}

    positions: EnumProperty(name="Vertex position", items=_ONOFF, default='OFF')
    normals: EnumProperty(name="Vertex normal", items=_ONOFF, default='OFF')
    uv_sets: EnumProperty(name="UV Sets", items=_SETS, default='ALL')
    color_sets: EnumProperty(name="Color Sets", items=_SETS, default='ALL')
    sample_space: EnumProperty(name="Sample space", default='WORLD',
                               items=(('WORLD', "World", ""), ('LOCAL', "Local", ""), ('UV', "UV", ""),
                                      ('COMPONENT', "Component", ""), ('TOPOLOGY', "Topology", "")))
    mirroring: EnumProperty(name="Mirroring", default='OFF',
                            items=(('OFF', "Off", ""), ('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", "")))
    flip_uvs: EnumProperty(name="Flip UVs", default='OFF', items=(('OFF', "Off", ""), ('U', "U", ""), ('V', "V", "")))
    color_borders: EnumProperty(name="Color borders", default='PRESERVE',
                                items=(('IGNORE', "Ignore", ""), ('PRESERVE', "Preserve", "")))
    search_method: EnumProperty(name="Search method", default='CLOSEST_POINT',
                                items=(('ALONG_NORMAL', "Closest along normal", ""),
                                       ('CLOSEST_POINT', "Closest to point", "")))
    option_box: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def invoke(self, context, event):
        if self.option_box:   # Maya option box: the Transfer Attributes Options window
            return context.window_manager.invoke_props_dialog(self, title="Transfer Attributes Options",
                                                              confirm_text="Transfer", width=540)
        return self.execute(context)

    def draw(self, context):
        lay = self.layout
        lay.use_property_split = True
        lay.label(text="Attributes To Transfer")
        for name in ("positions", "normals", "uv_sets", "color_sets"):
            lay.row().prop(self, name, expand=True)
        lay.label(text="Attribute Settings")
        # label | buttons split by hand: Blender 5.3 wraps a five-item expanded enum under property split
        split = lay.split(factor=0.4)
        split.alignment = 'RIGHT'
        split.label(text="Sample space")
        row = split.row()
        row.use_property_split = False
        row.prop(self, "sample_space", expand=True)
        for name in ("mirroring", "flip_uvs", "color_borders"):
            row = lay.row()
            row.enabled = False         # Blender's Data Transfer has no mirrored or flipped sampling
            row.prop(self, name, expand=True)
        lay.row().prop(self, "search_method", expand=True)

    def execute(self, context):
        sources, target = _targets(context)
        if target is None:
            self.report({'ERROR'}, ERR_SELECT)
            return {'CANCELLED'}
        if self.sample_space == 'UV':
            self.report({'ERROR'}, ERR_UV_SPACE)
            return {'CANCELLED'}
        source = sources[0]
        if len(sources) > 1:
            self.report({'WARNING'}, f"Transfer Attributes: Blender transfers from one source; using {source.name}")
        made = add_transfer(context, source, target, self.positions == 'ON', self.normals == 'ON', self.uv_sets,
                            self.color_sets, self.sample_space, self.search_method)
        if not made:
            results.result(self, "Transfer Attributes: nothing to transfer (every attribute is Off)")
            return {'CANCELLED'}
        results.result(self, f"Transfer Attributes: {target.name} from {source.name}")
        return {'FINISHED'}


classes = (ALLSET_OT_transfer_attributes,)
