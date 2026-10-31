# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Maya UV Toolkit: a "UV Toolkit" tab in the UV Editor sidebar (docs/steps/step_66.md 「계획」 4).

Order of Maya's toolkit: component icons (Vertex · Edge ·
Face | UV · UV Shell), "N object selected", Pick/Marquee · Drag · Tweak/Marquee, Symmetry, Selection / Transform
Constraint, All · Clear · Inverse, then the folded sections Pinning · Select By Type · Soft Selection · Transform · Create ·
Cut and Sew · Unfold · Align and Snap · Arrange and Layout · UV Sets. Buttons run the kit's Maya commands
(operators/uv_tools.py) or Blender's UV operators; items Blender has no counterpart for are greyed with a notice.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from ..i18n import tr as _zh, enum_items as _zh_enum, native as _zh_native
import math
import bpy
from . import notices
CATEGORY = _dcc_source('UV Toolkit')
PICK = ((_dcc_source('Pick/Marquee'), 'builtin.select_box'), (_dcc_source('Drag'), 'builtin.select_circle'), (_dcc_source('Tweak/Marquee'), 'builtin.select'))
COMPONENTS = (('VERTEX', 'VERTEXSEL', _dcc_source('Vertex')), ('EDGE', 'EDGESEL', _dcc_source('Edge')), ('FACE', 'FACESEL', _dcc_source('Face')))
CREATE = (_dcc_source('Automatic'), _dcc_source('Planar'), _dcc_source('Cylindrical'), _dcc_source('Spherical'), _dcc_source('Camera-based'))
GREY = {'UV Toolkit/Symmetry': (_dcc_source('Mirror UVs'), _dcc_source('Blender has no UV symmetry selection: select one side, then UV > Mirror.')), 'UV Toolkit/Selection Constraint': (_dcc_source('Select menu'), _dcc_source('Blender has no UV selection constraint: use Select > Select Linked / Select Split.')), 'UV Toolkit/Transform Constraint': (_dcc_source('Snapping'), _dcc_source('Blender has no UV transform constraint: use snapping (UV Editor header magnet).')), 'UV Toolkit/Select By Type/Back-Facing': (_dcc_source('Select Overlap'), _dcc_source("Blender can't select back-facing UVs directly: Select Overlap finds stacked shells.")), 'UV Toolkit/Select By Type/Texture Borders': (_dcc_source('Seams'), _dcc_source('Shell borders are seams in Blender: Select > Select Linked, or mark seams from islands.')), 'UV Toolkit/Unfold/Straighten': (_dcc_source('Follow Active Quads'), _dcc_source('Blender straightens a grid of quads from the active one: UV > Follow Active Quads.'))}

def _grey(layout, key, text):
    row = layout.row()
    row.enabled = False
    row.operator('allset.menu_unavailable', text=_zh(text, 'MWK:ui/uv_toolkit.py:43'), emboss=False).item = key

def _section(layout, idname, label, default_closed=True):
    (header, body) = layout.panel(idname, default_closed=default_closed)
    header.label(text=_zh(label, 'MWK:ui/uv_toolkit.py:48'))
    return body

def current_component(context):
    ts = context.scene.tool_settings
    if not ts.use_uv_select_sync:
        from .. import compat
        return 'SHELL' if compat.uv_island_mode(ts) else 'UV'
    (v, e, f) = ts.mesh_select_mode
    return 'FACE' if f and (not (v or e)) else 'EDGE' if e and (not v) else 'VERTEX'

def _tool_id(context):
    try:
        tool = context.workspace.tools.from_space_image_mode('UV', create=False)
    except (AttributeError, TypeError):
        return ''
    return tool.idname if tool else ''

class ALLSET_PT_uv_toolkit(bpy.types.Panel):
    bl_translation_context = 'MWK:ui/uv_toolkit.py:73'
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_label = _zh_native('UV Toolkit', 'MWK:ui/uv_toolkit.py:73')
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and space.mode == 'UV'

    def draw(self, context):
        layout = self.layout
        editing = context.mode == 'EDIT_MESH'
        comp = current_component(context) if editing else None
        from . import editor_menu_data, menu_sets
        bar = layout.row(align=True)
        for (i, (title, _items)) in enumerate(editor_menu_data.EDITORS[_dcc_source('UV Toolkit')]):
            bar.menu(menu_sets.editor_menu_idname(_dcc_source('UV Toolkit'), i), text=_zh(title, 'MWK:ui/uv_toolkit.py:88'))
        row = layout.row(align=True)
        row.scale_x = row.scale_y = 1.3
        for (mode, icon, label) in COMPONENTS:
            row.operator('allset.uv_component', text=_dcc_display(''), icon=icon, depress=comp == mode).mode = mode
        row.separator()
        row.operator('allset.uv_component', text=_dcc_display(''), icon='UV_VERTEXSEL', depress=comp == 'UV').mode = 'UV'
        row.operator('allset.uv_component', text=_dcc_display(''), icon='UV_ISLANDSEL', depress=comp == 'SHELL').mode = 'SHELL'
        n = len([o for o in getattr(context, 'objects_in_mode_unique_data', ()) if o.type == 'MESH'])
        layout.label(text=_zh(f"{n} object{('s' if n != 1 else '')} selected" if editing else 'No mesh in edit mode', 'MWK:ui/uv_toolkit.py:97'))
        col = layout.column(align=True)
        tid = _tool_id(context)
        for (label, tool) in PICK:
            op = col.operator('wm.tool_set_by_id', text=_zh(label, 'MWK:ui/uv_toolkit.py:101'), depress=tid == tool, icon='RADIOBUT_ON' if tid == tool else 'RADIOBUT_OFF')
            (op.name, op.space_type) = (tool, 'IMAGE_EDITOR')
        for name in (_dcc_source('Symmetry'), _dcc_source('Selection Constraint'), _dcc_source('Transform Constraint')):
            _grey(layout, f'UV Toolkit/{name}', f'{name}: Off')
        row = layout.row(align=True)
        for (label, action) in ((_dcc_source('All'), 'SELECT'), (_dcc_source('Clear'), 'DESELECT'), (_dcc_source('Inverse'), 'INVERT')):
            row.operator('uv.select_all', text=_zh(label, 'MWK:ui/uv_toolkit.py:108')).action = action
        if not editing:
            return
        self._sections(layout, context)

    def _sections(self, layout, context):
        s = context.scene.allset_uv
        ts = context.scene.tool_settings
        body = _section(layout, 'ALLSET_uvtk_pin', _dcc_source('Pinning'))
        if body:
            row = body.row(align=True)
            row.operator('uv.pin', text=_zh('Pin', 'MWK:ui/uv_toolkit.py:119'))
            row.operator('uv.pin', text=_zh('Unpin', 'MWK:ui/uv_toolkit.py:120')).clear = True
            row.operator('uv.pin', text=_zh('Invert', 'MWK:ui/uv_toolkit.py:121')).invert = True
        body = _section(layout, 'ALLSET_uvtk_type', _dcc_source('Select By Type'))
        if body:
            body.operator('uv.select_overlap', text=_zh('Overlapping', 'MWK:ui/uv_toolkit.py:124'))
            _grey(body, 'UV Toolkit/Select By Type/Back-Facing', _dcc_source('Back-Facing'))
            _grey(body, 'UV Toolkit/Select By Type/Texture Borders', _dcc_source('Texture Borders'))
        body = _section(layout, 'ALLSET_uvtk_soft', _dcc_source('Soft Selection'))
        if body:
            body.prop(ts, 'use_proportional_edit', text=_zh('Soft Select', 'MWK:ui/uv_toolkit.py:129'))
            sub = body.column()
            sub.active = ts.use_proportional_edit
            sub.prop(ts, 'proportional_size', text=_zh('Falloff radius (UV)', 'MWK:ui/uv_toolkit.py:132'))
            sub.prop(ts, 'proportional_edit_falloff', text=_zh('Falloff curve', 'MWK:ui/uv_toolkit.py:133'))
        body = _section(layout, 'ALLSET_uvtk_transform', _dcc_source('Transform'))
        if body:
            box = body.column(align=True)
            box.label(text=_zh('Texel Density (px/unit)', 'MWK:ui/uv_toolkit.py:137'))
            box.prop(s, 'map_size')
            row = box.row(align=True)
            row.prop(s, 'texel_density', text=_dcc_display(''))
            row.operator('allset.uv_texel_get', text=_zh('Get', 'MWK:ui/uv_toolkit.py:141'))
            row.operator('allset.uv_texel_set', text=_zh('Set', 'MWK:ui/uv_toolkit.py:142'))
            row = body.row(align=True)
            op = row.operator('transform.mirror', text=_zh('Flip U', 'MWK:ui/uv_toolkit.py:144'))
            op.constraint_axis = (True, False, False)
            op = row.operator('transform.mirror', text=_zh('Flip V', 'MWK:ui/uv_toolkit.py:146'))
            op.constraint_axis = (False, True, False)
            row = body.row(align=True)
            row.operator('transform.rotate', text=_zh('Rotate -90', 'MWK:ui/uv_toolkit.py:149')).value = -math.pi / 2
            row.operator('transform.rotate', text=_zh('Rotate +90', 'MWK:ui/uv_toolkit.py:150')).value = math.pi / 2
        body = _section(layout, 'ALLSET_uvtk_create', _dcc_source('Create'))
        if body:
            grid = body.grid_flow(columns=2, align=True)
            for label in CREATE:
                grid.operator('allset.menu_item', text=_zh(label, 'MWK:ui/uv_toolkit.py:155')).item = f'UV/{label}'
        body = _section(layout, 'ALLSET_uvtk_cut', _dcc_source('Cut and Sew'), default_closed=False)
        if body:
            row = body.row(align=True)
            row.operator('allset.uv_cut', text=_zh('Cut', 'MWK:ui/uv_toolkit.py:159'))
            row.operator('allset.uv_sew', text=_zh('Sew', 'MWK:ui/uv_toolkit.py:160'))
            row = body.row(align=True)
            row.operator('allset.uv_create_shell', text=_zh('Create UV Shell', 'MWK:ui/uv_toolkit.py:162'))
            row.operator('allset.uv_move_sew', text=_zh('Move and Sew', 'MWK:ui/uv_toolkit.py:163'))
            body.operator('allset.cut_sew_tool_set', text=_zh('3D Cut and Sew Tool', 'MWK:ui/uv_toolkit.py:164'))
        body = _section(layout, 'ALLSET_uvtk_unfold', _dcc_source('Unfold'), default_closed=False)
        if body:
            row = body.row(align=True)
            row.operator('allset.uv_unfold', text=_zh('Unfold', 'MWK:ui/uv_toolkit.py:168'))
            row.operator('uv.minimize_stretch', text=_zh('Optimize', 'MWK:ui/uv_toolkit.py:169'))
            _grey(body, 'UV Toolkit/Unfold/Straighten', _dcc_source('Straighten'))
        body = _section(layout, 'ALLSET_uvtk_align', _dcc_source('Align and Snap'))
        if body:
            row = body.row(align=True)
            row.operator('uv.align', text=_zh('Align U', 'MWK:ui/uv_toolkit.py:174')).axis = 'ALIGN_X'
            row.operator('uv.align', text=_zh('Align V', 'MWK:ui/uv_toolkit.py:175')).axis = 'ALIGN_Y'
            row = body.row(align=True)
            row.operator('allset.uv_snap_together', text=_zh('Snap Together', 'MWK:ui/uv_toolkit.py:177'))
            row.operator('allset.uv_snap_stack', text=_zh('Snap and Stack', 'MWK:ui/uv_toolkit.py:178'))
        body = _section(layout, 'ALLSET_uvtk_layout', _dcc_source('Arrange and Layout'), default_closed=False)
        if body:
            body.operator('allset.uv_layout', text=_zh('Layout', 'MWK:ui/uv_toolkit.py:181'))
            body.prop(s, 'shell_padding', text=_zh('Shell Padding (px)', 'MWK:ui/uv_toolkit.py:182'))
            row = body.row(align=True)
            row.operator('allset.uv_orient_shells', text=_zh('Orient Shells', 'MWK:ui/uv_toolkit.py:184'))
            row.operator('allset.uv_orient_edges', text=_zh('Orient to Edges', 'MWK:ui/uv_toolkit.py:185'))
            row = body.row(align=True)
            row.operator('allset.uv_stack', text=_zh('Stack', 'MWK:ui/uv_toolkit.py:187'))
            row.operator('allset.uv_unstack', text=_zh('Unstack', 'MWK:ui/uv_toolkit.py:188'))
            row = body.row(align=True)
            row.operator('allset.uv_distribute', text=_zh('Distribute', 'MWK:ui/uv_toolkit.py:190'))
            row.operator('allset.uv_normalize', text=_zh('Normalize', 'MWK:ui/uv_toolkit.py:191'))
        ob = context.edit_object
        body = _section(layout, 'ALLSET_uvtk_sets', _dcc_source('UV Sets'))
        if body and ob is not None and (ob.type == 'MESH'):
            me = ob.data
            body.template_list('MESH_UL_uvmaps', '', me, 'uv_layers', me.uv_layers, 'active_index', rows=2)
classes = (ALLSET_PT_uv_toolkit,)

def register():
    notices.PANEL_NOTICES.update(GREY)
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    for key in GREY:
        notices.PANEL_NOTICES.pop(key, None)
