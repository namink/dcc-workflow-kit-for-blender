# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Rows of the Maya viewport panel menus (``ui/panel_menus.py``), the panel toolbar (``ui/panel_toolbar.py``) and the
greyed Status Line widgets (``ui/status_line.py``) as plain data — no ``bpy`` — so ``tools/menu_count.py``,
``tools/menu_consistency.py`` and the step-101 notice rules can walk them like the main menus (step 177; until then
these 36 + 9 greyed items were outside every count, research audit 12 BS2 / BS6, docs/steps/step_173_remaining.md §4).

Item paths (``allset.menu_unavailable`` ``item``, ``notices.PANEL_MENU`` keys): ``Panel menu/<menu>/<sub>/<label>``,
``Panel toolbar/<label>``, ``Status Line/<tooltip>``. Rows: see ``ui/panel_menus.py``.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format

def _sep(label=''):
    return ('sep', label)

def _grey(label):
    return ('grey', label)

def _run(label, op, **props):
    return ('run', label, op, props)

def _tool(label, idname):
    return _run(label, 'wm.tool_set_by_id', name=idname)

def _view(label, view):
    return _run(label, 'allset.hb_view', view=view)
VIEW = [('set', 'SELECT_CAMERA', _dcc_source('Select Camera')), ('set', 'CAMERA_LOCK', _dcc_source('Lock Camera')), _sep(), _run(_dcc_source('Undo View Change'), 'allset.view_history', direction='UNDO'), _run(_dcc_source('Redo View Change'), 'allset.view_history', direction='REDO'), _sep(_dcc_source('Tumble Behaviour')), ('set', 'TUMBLE_SELECTION', _dcc_source('Around Most Recent Selection')), ('set', 'TUMBLE_COI', _dcc_source('Around Center of Interest')), _sep(_dcc_source('Change View')), _run(_dcc_source('Align Camera To Polygon'), 'view3d.view_axis', type='TOP', align_active=True), _run(_dcc_source('Center View of Selection'), 'allset.center_view_selection'), _run(_dcc_source('Default View'), 'allset.view_home'), _run(_dcc_source('Frame All'), 'allset.frame', selected=False), _run(_dcc_source('Frame Selection'), 'allset.frame', selected=True), ('menu', _dcc_source('View Along Axis'), 'ALLSET_MT_panel_view_axis'), _sep(), _run(_dcc_source('Camera Attribute Editor...'), 'allset.camera_attribute_editor'), ('menu', _dcc_source('Camera Tools'), 'ALLSET_MT_panel_camera_tools'), _sep(), _grey(_dcc_source('View Sequence Time'))]
VIEW_AXIS = [_view('X', 'RIGHT'), _view('Y', 'BACK'), _view('Z', 'TOP'), _view('-X', 'LEFT'), _view('-Y', 'FRONT'), _view('-Z', 'BOTTOM')]
CAMERA_TOOLS = [_tool(_dcc_source('Tumble Tool'), 'allset.tumble_tool'), _tool(_dcc_source('Track Tool'), 'allset.track_tool'), _tool(_dcc_source('Dolly Tool'), 'allset.dolly_tool'), _run(_dcc_source('Zoom Tool'), 'view3d.zoom_border'), _grey(_dcc_source('2D Pan/Zoom Tool')), _tool(_dcc_source('Grease Pencil Tool'), 'builtin.annotate'), _sep(), _run(_dcc_source('Roll Tool'), 'view3d.view_roll', type='ANGLE', angle=0.2618), _grey(_dcc_source('Azimuth Elevation Tool')), _grey(_dcc_source('Yaw-Pitch Tool')), _run(_dcc_source('Fly Tool'), 'view3d.fly'), _run(_dcc_source('Walk Tool'), 'view3d.walk')]
SHADING = [('set', 'SHADE_WIRE', _dcc_source('Wireframe')), ('set', 'SHADE_SMOOTH', _dcc_source('Smooth Shade All')), _grey(_dcc_source('Smooth Shade Selected Items')), _grey(_dcc_source('Flat Shade All')), _grey(_dcc_source('Flat Shade Selected Items')), _grey(_dcc_source('Bounding Box')), _grey(_dcc_source('Points')), _sep(), ('set', 'DEFAULT_MATERIAL', _dcc_source('Use Default Material')), ('prop', 'overlay', 'show_wireframes', _dcc_source('Wireframe on Shaded')), ('prop', 'shading', 'show_xray', _dcc_source('X-Ray')), ('prop', 'overlay', 'show_xray_bone', _dcc_source('X-Ray Joints')), _grey(_dcc_source('X-Ray Active Components')), _sep(), _grey(_dcc_source('Interactive Shading')), _sep(), ('prop', 'shading', 'show_backface_culling', _dcc_source('Backface Culling')), _grey(_dcc_source('Smooth Wireframe')), _sep(), ('set', 'HW_TEXTURE', _dcc_source('Hardware Texturing')), _grey(_dcc_source('Hardware Fog')), ('prop', 'shading', 'use_dof', _dcc_source('Depth of Field')), _sep(), ('set', 'APPLY_ALL', _dcc_source('Apply Current to All'))]
LIGHTING = [('set', 'LIGHT_DEFAULT', _dcc_source('Use Default Lighting')), ('set', 'LIGHT_ALL', _dcc_source('Use All Lights')), _grey(_dcc_source('Use Selected Lights')), ('set', 'LIGHT_FLAT', _dcc_source('Use Flat Lighting')), _grey(_dcc_source('Use No Lights')), _sep(), _grey(_dcc_source('Two Sided Lighting')), ('prop', 'shading', 'show_shadows', _dcc_source('Shadows'))]
SHOW_TYPES = ((_dcc_source('Controllers'), None), (_dcc_source('NURBS Curves'), '!SHOW_NURBS_CURVES'), (_dcc_source('NURBS Surfaces'), 'surf'), (_dcc_source('NURBS CVs'), None), (_dcc_source('NURBS Hulls'), None), (_dcc_source('Polygons'), 'mesh'), (_dcc_source('Subdiv Surfaces'), None), (_dcc_source('Planes'), None), (_dcc_source('Lights'), 'light'), (_dcc_source('Cameras'), 'camera'), (_dcc_source('Image Planes'), '!SHOW_IMAGE_PLANES'), (_dcc_source('Joints'), 'armature'), (_dcc_source('IK Handles'), '!SHOW_IK_HANDLES'), (_dcc_source('Deformers'), 'lattice'), (_dcc_source('Dynamics'), None), (_dcc_source('Particle Instancers'), None), (_dcc_source('Fluids'), 'volume'), (_dcc_source('Hair Systems'), 'curves'), (_dcc_source('Follicles'), None), (_dcc_source('nCloths'), None), ('nParticles', None), (_dcc_source('nRigids'), None), (_dcc_source('Dynamic Constraints'), None), (_dcc_source('Locators'), _dcc_source('empty')), (_dcc_source('Dimensions'), None), (_dcc_source('Pivots'), '@show_object_origins'), (_dcc_source('Handles'), None), (_dcc_source('Texture Placements'), None), (_dcc_source('Strokes'), None), (_dcc_source('Motion Trails'), '@show_motion_paths'), (_dcc_source('Plugin Shapes'), None), (_dcc_source('Clip Ghosts'), None), (_dcc_source('Grease Pencil'), 'grease_pencil'))
ALL_TYPES = ('mesh', _dcc_source('curve'), 'surf', 'meta', 'font', 'curves', 'pointcloud', 'volume', 'armature', 'lattice', _dcc_source('empty'), 'grease_pencil', 'camera', 'light', 'speaker', 'light_probe')

def _show_row(label, target):
    if target is None:
        return _grey(label)
    if target.startswith('@'):
        return ('prop', 'overlay', target[1:], label)
    if target.startswith('!'):
        return ('set', target[1:], label)
    return ('prop', 'space', f'show_object_viewport_{target}', label)
SHOW = [('menu', _dcc_source('Isolate Select'), 'ALLSET_MT_panel_isolate'), _sep(), ('set', 'SHOW_ALL', _dcc_source('All')), ('set', 'SHOW_NONE', _dcc_source('None')), _sep(), *[_show_row(label, t) for (label, t) in SHOW_TYPES], _sep(), ('prop', 'space', 'show_gizmo', _dcc_source('Manipulators')), ('set', 'GRID', _dcc_source('Grid')), ('prop', 'overlay', 'show_text', 'HUD'), _grey(_dcc_source('Hold-Outs')), ('set', 'SELECTION_HILITE', _dcc_source('Selection Highlighting'))]
ISOLATE = [_run(_dcc_source('View Selected'), 'allset.isolate')]
RENDERER = [('set', 'RENDER_VP2', _dcc_source('Viewport 2.0')), _grey(_dcc_source('Legacy Default Viewport')), _grey(_dcc_source('Legacy High Quality Viewport')), _sep(), ('set', 'RENDER_ENGINE', '{engine}')]
PANELS = [('menu', _dcc_source('Perspective'), 'ALLSET_MT_panel_perspective'), _grey(_dcc_source('Stereo')), ('menu', _dcc_source('Orthographic'), 'ALLSET_MT_panel_orthographic'), _run(_dcc_source('Look Through Selected'), 'allset.panel_look_through'), _grey(_dcc_source('Camera Set')), _sep(), ('menu', _dcc_source('Panel'), 'ALLSET_MT_panel_panel'), _grey(_dcc_source('Hypergraph Panel')), ('menu', _dcc_source('Layouts'), 'ALLSET_MT_panel_layouts'), _grey(_dcc_source('Saved Layouts')), _sep(), _run(_dcc_source('Tear Off...'), 'allset.open_editor', ui_type='VIEW_3D'), _run(_dcc_source('Tear Off Copy...'), 'allset.open_editor', ui_type='VIEW_3D'), _sep(), _grey(_dcc_source('Panel Editor...'))]
PANEL_TYPES = ((_dcc_source('Outliner'), 'OUTLINER'), (_dcc_source('Graph Editor'), 'FCURVES'), (_dcc_source('Dope Sheet'), 'DOPESHEET'), (_dcc_source('Node Editor'), 'ShaderNodeTree'), (_dcc_source('UV Editor'), 'UV'), (_dcc_source('Model Panel'), 'VIEW_3D'), (_dcc_source('Script Editor'), 'TEXT_EDITOR'))
LAYOUTS = [('set', 'LAYOUT_SINGLE', _dcc_source('Single Perspective View')), ('set', 'LAYOUT_FOUR', _dcc_source('Four View'))]
BAR = ((_dcc_source('View'), 'ALLSET_MT_panel_view'), (_dcc_source('Shading'), 'ALLSET_MT_panel_shading'), (_dcc_source('Lighting'), 'ALLSET_MT_panel_lighting'), (_dcc_source('Show'), 'ALLSET_MT_panel_show'), (_dcc_source('Renderer'), 'ALLSET_MT_panel_renderer'), (_dcc_source('Panels'), 'ALLSET_MT_panel_panels'))
TOOLBAR = ((('cam_select', 'set', 'SELECT_CAMERA', _dcc_source('Select Camera')), ('cam_lock', 'set', 'CAMERA_LOCK', _dcc_source('Lock Camera')), ('cam_attr', 'run', ('allset.camera_attribute_editor', {}), _dcc_source('Camera Attributes')), ('bookmark', 'grey', None, _dcc_source('Bookmarks')), ('image_plane', 'run', ('allset.create', {'kind': 'IMAGE_PLANE'}), _dcc_source('Image Plane')), ('pan_zoom', 'grey', None, _dcc_source('2D Pan/Zoom')), ('grease', 'run', ('wm.tool_set_by_id', {'name': 'builtin.annotate'}), _dcc_source('Grease Pencil (Blender: Annotate tool)'))), ((_dcc_source('grid'), 'set', 'GRID', _dcc_source('Grid')), ('film_gate', 'set', 'FILM_GATE', _dcc_source('Film Gate')), ('res_gate', 'grey', None, _dcc_source('Resolution Gate')), ('gate_mask', 'set', 'GATE_MASK', _dcc_source('Gate Mask')), ('field_chart', 'grey', None, _dcc_source('Field Chart')), ('safe_action', 'set', 'SAFE_ACTION', _dcc_source('Safe Action')), ('safe_title', 'set', 'SAFE_TITLE', _dcc_source('Safe Title'))), (('wire', 'set', 'SHADE_WIRE', _dcc_source('Wireframe')), ('smooth', 'set', 'SHADE_SMOOTH', _dcc_source('Smooth Shade All')), ('default_mat', 'set', 'DEFAULT_MATERIAL', _dcc_source('Use Default Material')), ('wire_on_shaded', 'prop', ('overlay', 'show_wireframes'), _dcc_source('Wireframe on Shaded')), ('textured', 'set', 'HW_TEXTURE', _dcc_source('Textured')), ('all_lights', 'set', 'LIGHT_ALL', _dcc_source('Use All Lights')), ('shadows', 'prop', ('shading', 'show_shadows'), _dcc_source('Shadows'))), (('ssao', 'prop', ('shading', 'show_cavity'), _dcc_source('Screen Space Ambient Occlusion (Blender: cavity)')), ('motion_blur', 'grey', None, _dcc_source('Motion Blur')), ('aa', 'grey', None, _dcc_source('Multisample Anti-aliasing')), ('dof', 'prop', ('shading', 'use_dof'), _dcc_source('Depth of Field'))), (('isolate', 'set', 'ISOLATE', _dcc_source('Isolate Select')), ('xray', 'prop', ('shading', 'show_xray'), _dcc_source('X-Ray')), ('xray_comp', 'grey', None, _dcc_source('X-Ray Active Components')), ('xray_joints', 'prop', ('overlay', 'show_xray_bone'), _dcc_source('X-Ray Joints'))))
MENUS = {'ALLSET_MT_panel_view': (_dcc_source('View'), VIEW), 'ALLSET_MT_panel_view_axis': (_dcc_source('View/View Along Axis'), VIEW_AXIS), 'ALLSET_MT_panel_camera_tools': (_dcc_source('View/Camera Tools'), CAMERA_TOOLS), 'ALLSET_MT_panel_shading': (_dcc_source('Shading'), SHADING), 'ALLSET_MT_panel_lighting': (_dcc_source('Lighting'), LIGHTING), 'ALLSET_MT_panel_show': (_dcc_source('Show'), SHOW), 'ALLSET_MT_panel_isolate': (_dcc_source('Show/Isolate Select'), ISOLATE), 'ALLSET_MT_panel_renderer': (_dcc_source('Renderer'), RENDERER), 'ALLSET_MT_panel_panels': (_dcc_source('Panels'), PANELS), 'ALLSET_MT_panel_layouts': (_dcc_source('Panels/Layouts'), LAYOUTS)}
(MENU_PREFIX, TOOLBAR_PREFIX) = (_dcc_source('Panel menu/'), _dcc_source('Panel toolbar/'))
STATUS_LINE = (_dcc_source('Status Line/Select by hierarchy'), _dcc_source('Status Line/Select by handle object type'), _dcc_source('Status Line/Select by dynamic object type'), _dcc_source('Status Line/Snap to projected center'), _dcc_source('Status Line/Snap to view planes'), _dcc_source('Status Line/Render Setup'), _dcc_source('Status Line/Pause Viewport 2.0'), _dcc_source('Status Line/Show or hide the Character Controls'))
COMMANDS = {_dcc_source('Tumble Tool'): 'TumbleTool', _dcc_source('Track Tool'): _dcc_source('TrackTool'), _dcc_source('Dolly Tool'): 'DollyTool', _dcc_source('Center View of Selection'): 'CenterViewOfSelection', _dcc_source('Default View'): 'GoToDefaultView'}

def path_label(label):
    """A label as a path part: a "/" in it ("2D Pan/Zoom Tool") becomes U+2215 so paths still split on "/"."""
    return label.replace('/', '∕')

def item_path(idname, label):
    """``allset.menu_unavailable`` item of a greyed row ``label`` in menu ``idname``."""
    prefix = f'{MENU_PREFIX}{MENUS[idname][0]}/' if idname in MENUS else MENU_PREFIX
    return prefix + path_label(label)

def toolbar_path(label):
    return TOOLBAR_PREFIX + path_label(label)

def leaves():
    """[(family, path, working)] of every panel menu row that is a command (not a submenu / separator), every panel
    toolbar button and every greyed Status Line widget. family = "Panel menus" / "Panel toolbar" / "Status Line"."""
    out = []
    for (idname, (_prefix, rows)) in MENUS.items():
        for row in rows:
            if row[0] in ('sep', 'menu'):
                continue
            label = row[1] if row[0] in ('grey', 'run') else row[-1]
            out.append((_dcc_source('Panel menus'), item_path(idname, label), row[0] != 'grey'))
    for group in TOOLBAR:
        for (_glyph, kind, _data, label) in group:
            out.append((_dcc_source('Panel toolbar'), toolbar_path(label), kind != 'grey'))
    out += [(_dcc_source('Status Line greys'), p, False) for p in STATUS_LINE]
    return out
