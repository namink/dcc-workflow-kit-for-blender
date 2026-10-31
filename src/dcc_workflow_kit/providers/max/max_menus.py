# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format
'3ds Max 2027 main menu bar and viewport label menus, drawn as Blender menus.\n\nLabels, order, separators, submenus and hotkey hints follow the "Main Menu Bar" and\n"Viewport Label Menu Bar" of the installed 3ds Max 2027 Default.mnxb. Entries whose\nlabel could not be resolved are omitted. Every entry runs the closest Blender\noperator; entries without a Blender equivalent stay visible but greyed out.\n\nUse: register CLASSES (the generated Menu classes plus the operator that draws greyed\nentries), then draw ``layout.menu(idname, text=label)`` for each entry of MAIN_MENUS\n(menu bar) or LABEL_MENUS (viewport label menus).\n'
import hashlib
import re
import bpy

class Item:
    """Menu entry. op=None draws it greyed; menu opens an existing Blender menu instead."""
    __slots__ = ('label', 'op', 'props', 'hotkey', 'check', 'menu')

    def __init__(self, label, op=None, props=None, hotkey='', check=None, menu=None):
        (self.label, self.op, self.props) = (label, op, props or {})
        (self.hotkey, self.check, self.menu) = (hotkey, check, menu)

    def __repr__(self):
        return _msg('Item(%r, %r)') % (self.label, self.menu or self.op)

class Sep:
    __slots__ = ()

class Sub:
    """Submenu; idname is assigned when its Menu class is generated."""
    __slots__ = ('label', 'items', 'idname')

    def __init__(self, label, items):
        (self.label, self.items, self.idname) = (label, list(items), '')

    def __repr__(self):
        return _msg('Sub(%r, %d items)') % (self.label, len(self.items))
SEP = Sep()
C_MENUS = {_msg('TOPBAR_MT_file_open_recent')}
ADDON_MENUS = {_msg('BSM_MT_view_cameras'): 'operators', _msg('BSM_MT_view_lights'): 'operators'}
MODE_OPS = {'object.select_all': {'EDIT_MESH': 'mesh.select_all', 'EDIT_CURVE': 'curve.select_all', 'EDIT_SURFACE': 'curve.select_all', 'EDIT_CURVES': 'curves.select_all', 'EDIT_ARMATURE': 'armature.select_all', 'POSE': 'pose.select_all', 'EDIT_LATTICE': 'lattice.select_all', 'EDIT_METABALL': 'mball.select_all', 'EDIT_GREASE_PENCIL': 'grease_pencil.select_all'}}

def _cmd(label, command, hotkey='', check=None):
    return Item(label, 'bsm.max_command', {'command': command}, hotkey, check)

def _mod(label, hotkey=''):
    return Item(label, 'bsm.max_modifier', {'name': label}, hotkey)

def _mods(*labels):
    return [_mod(label) for label in labels]

def _off(*labels):
    return [Item(label) for label in labels]

def _create(label, kind):
    return Item(label, 'bsm.create', {'kind': kind})

def _constraint(label, kind):
    return Item(label, 'bsm.add_constraint', {'kind': kind})

def _view(label, view, hotkey=''):
    return Item(label, 'bsm.view', {'view': view}, hotkey)

def _shade(label, style, hotkey='', check=None):
    return Item(label, 'bsm.viewport_shading', {'style': style}, hotkey, check)

def _editor(label, kind, hotkey=''):
    return Item(label, 'bsm.editor', {'kind': kind}, hotkey)

def _tool(label, tool, hotkey=''):
    return Item(label, 'bsm.tool', {'tool': tool}, hotkey)

def _view3d(context):
    space = getattr(context, 'space_data', None)
    if space is not None and space.type == 'VIEW_3D':
        return space
    screen = getattr(context, 'screen', None)
    for area in screen.areas if screen else ():
        if area.type == 'VIEW_3D':
            return area.spaces.active
    return None

def _overlay(name):
    return lambda context: bool(getattr(getattr(_view3d(context), 'overlay', None), name, False))
_grid_on = _overlay('show_floor')
_stats_on = _overlay('show_stats')
_face_orientation_on = _overlay('show_face_orientation')
_edged_faces_on = _overlay('show_wireframes')

def _wireframe_on(context):
    view = _view3d(context)
    return bool(view and view.shading.type == 'WIREFRAME')

def _snap_on(context):
    return context.scene.tool_settings.use_snap

def _safe_frames_on(context):
    camera = context.scene.camera
    return bool(camera and camera.type == 'CAMERA' and camera.data.show_safe_areas)

def _fullscreen_on(context):
    return bool(context.screen and context.screen.show_fullscreen)
_VIEWCUBE = [_cmd(_msg('Show the ViewCube'), 'VIEWCUBE_TOGGLE', hotkey=_msg('Ctrl+Alt+V')), SEP, *_off(_msg('Show For Active View'), _msg('Show For All Views')), SEP, _cmd(_msg('Home'), 'VIEWCUBE_HOME', hotkey=_msg('Ctrl+Alt+H')), SEP, _view(_msg('Orthographic'), 'ORTHO'), _view(_msg('Perspective'), 'PERSP'), SEP, *_off(_msg('Set Current View as Home'), _msg('Set Current View as Front'), _msg('Reset Front')), SEP, Item(_msg('Configure...'))]
_STEERINGWHEELS = [Item(_msg('Toggle SteeringWheels'), hotkey=_msg('Shift+W')), SEP, Item(_msg('View Object Wheel')), Item(_msg('Tour Building Wheel'), hotkey=_msg('Ctrl+Shift+J')), Item(_msg('Full Navigation Wheel')), SEP, *_off(_msg('Mini View Object Wheel'), _msg('Mini Tour Building Wheel'), _msg('Mini Full Navigation Wheel')), SEP, Item(_msg('Configure...'))]
_SHOW_MATERIALS_IN_VIEWPORT_AS = [Item(_msg('Enable Transparency')), SEP, *_off(_msg('Standard Display'), _msg('Standard Display with Maps'), _msg('Hardware Display'), _msg('Hardware Display with Maps'), _msg('Shaded Materials without Maps')), _shade(_msg('Shaded Materials with Maps'), 'MATERIALS_SHADED'), Item(_msg('Realistic Materials without Maps')), _shade(_msg('Realistic Materials with Maps'), 'MATERIALS_REALISTIC'), SEP, Item(_msg('Override Off')), _shade(_msg('Override with UV Checker'), 'UV_CHECKER'), *_off(_msg('Override with Fast Shader'), _msg('Override with Rendering Setting'))]
_XVIEW = [_cmd(_msg('Show Statistics'), 'XVIEW_STATS', hotkey='7', check=_stats_on), _cmd(_msg('Face Orientation'), 'XVIEW_FACE_ORIENTATION', check=_face_orientation_on), Item(_msg('Overlapping Faces')), _cmd(_msg('Open Edges'), 'XVIEW_OPEN_EDGES'), *_off(_msg('Multiple Edges'), _msg('Isolated Vertices'), _msg('Overlapping Vertices'), _msg('T-Vertices'), _msg('Missing UVW Coordinates'), _msg('Flipped UVW Faces'), _msg('Overlapped UVW Faces')), SEP, Item(_msg('Select Results')), SEP, *_off(_msg('See-Through'), _msg('Auto Update'), _msg('Display On Top')), SEP, Item(_msg('Configure...'))]
_VIEWPORT_BACKGROUND = [_cmd(_msg('Gradient Color'), 'BACKGROUND_GRADIENT'), _cmd(_msg('Solid Color'), 'BACKGROUND_SOLID'), SEP, *_off(_msg('Environment Background'), _msg('Custom Image File')), SEP, Item(_msg('Configure Viewport Background...'), hotkey=_msg('Alt+B'))]
MAIN = [(_msg('File'), [Sub(_msg('New'), [Item(_msg('New All'), 'wm.read_homefile', {'use_empty': False}), Item(_msg('New from Template'), menu=_msg('TOPBAR_MT_file_new'))]), Item(_msg('Reset'), 'wm.read_homefile', {'use_empty': False}), Item(_msg('Open...'), 'wm.open_mainfile', hotkey=_msg('Ctrl+O')), Item(_msg('Open Recent'), menu=_msg('TOPBAR_MT_file_open_recent')), Item(_msg('Autobackup'), menu=_msg('TOPBAR_MT_file_recover')), Item(_msg('View Image File...')), SEP, Item(_msg('Save'), 'wm.save_mainfile', hotkey=_msg('Ctrl+S')), Item(_msg('Save As...'), 'wm.save_as_mainfile', hotkey=_msg('Ctrl+Shift+S')), Item(_msg('Save Incremental (+)'), 'wm.save_mainfile', {'incremental': True}, hotkey=_msg('Ctrl+Alt+S')), Item(_msg('Save Copy As...'), 'wm.save_as_mainfile', {'copy': True}), *_off(_msg('Save Selected...'), _msg('Archive...')), SEP, Sub(_msg('Import'), [Item(_msg('Import...'), menu=_msg('TOPBAR_MT_file_import')), Item(_msg('Merge...'), 'wm.append'), *_off(_msg('Replace...'), _msg('Link Revit'), _msg('Link FBX'), _msg('Link AutoCAD'))]), Sub(_msg('Export'), [Item(_msg('Export...'), menu=_msg('TOPBAR_MT_file_export')), *_off(_msg('Export Selected...'), _msg('Publish to DWF...'), _msg('Real-Time Exporter...'))]), Sub(_msg('Send to'), [Sub(_msg('Send to Maya'), []), Sub(_msg('Send to Motion Builder'), []), Sub(_msg('Send to Mudbox'), [])]), Sub(_msg('Reference'), [Item(_msg('XRef Objects...'), 'wm.link'), Item(_msg('XRef Scene...'), 'wm.link'), Item(_msg('Manage Links')), Item(_msg('Asset Tracking Toggle'), menu=_msg('TOPBAR_MT_file_external_data'), hotkey=_msg('Shift+T'))]), Sub(_msg('Project'), [Sub(_msg('Recent Projects'), []), Item(_msg('Set Active Project...')), SEP, *_off(_msg('Create Empty...'), _msg('Create Default...'), _msg('Create From Current...')), SEP, _cmd(_msg('Configure Project Paths...'), 'CONFIGURE_PATHS')]), _cmd(_msg('Summary Info...'), 'SUMMARY_INFO'), Item(_msg('File Properties...')), Item(_msg('Preferences...'), 'screen.userpref_show'), SEP, Item(_msg('Exit'), 'wm.quit_blender')]), (_msg('Edit'), [Item(_msg('Undo Scene Operation'), 'ed.undo', hotkey=_msg('Ctrl+Z')), Item(_msg('Redo Scene Operation'), 'ed.redo', hotkey=_msg('Ctrl+Y')), SEP, _cmd(_msg('Hold'), 'HOLD', hotkey=_msg('Ctrl+H')), _cmd(_msg('Fetch'), 'FETCH', hotkey=_msg('Ctrl+Alt+F')), SEP, _cmd(_msg('Delete'), 'DELETE', hotkey=_msg('Del')), Item(_msg('Clone'), 'bsm.clone', hotkey=_msg('Ctrl+V')), SEP, _tool(_msg('Move'), 'MOVE', hotkey='W'), _tool(_msg('Rotate'), 'ROTATE', hotkey='E'), _tool(_msg('Scale'), 'SCALE'), _cmd(_msg('Placement'), 'PLACEMENT'), Item(_msg('Transform Type-In...'), 'bsm.transform_typein', hotkey='F12'), Item(_msg('Transform Toolbox...')), SEP, Item(_msg('Select All'), 'object.select_all', {'action': 'SELECT'}, hotkey=_msg('Ctrl+A')), Item(_msg('Select None'), 'object.select_all', {'action': 'DESELECT'}, hotkey=_msg('Ctrl+D')), Item(_msg('Select Invert'), 'object.select_all', {'action': 'INVERT'}, hotkey=_msg('Ctrl+I')), SEP, _cmd(_msg('Select Similar'), 'SELECT_SIMILAR', hotkey=_msg('Ctrl+Shift+A')), _cmd(_msg('Select Instances'), 'SELECT_INSTANCES'), Sub(_msg('Select By'), [_cmd(_msg('Name'), 'SELECT_BY_NAME', hotkey='H'), _cmd(_msg('Layer...'), 'SELECT_BY_LAYER'), _cmd(_msg('Color'), 'SELECT_BY_COLOR')]), SEP, Sub(_msg('Selection Region'), [_cmd(_msg('Rectangular Region'), 'SELECT_REGION_RECT'), _cmd(_msg('Circular Region'), 'SELECT_REGION_CIRCLE'), _cmd(_msg('Fence Region'), 'SELECT_REGION_FENCE'), _cmd(_msg('Lasso Region'), 'SELECT_REGION_LASSO'), _cmd(_msg('Paint Selection Region'), 'SELECT_REGION_PAINT'), SEP, _cmd(_msg('Window'), 'SELECT_WINDOW'), _cmd(_msg('Crossing'), 'SELECT_CROSSING')]), SEP, _cmd(_msg('Manage Selection Sets...'), 'MANAGE_SELECTION_SETS'), SEP, _cmd(_msg('Object Properties...'), 'OBJECT_PROPERTIES')]), (_msg('Tools'), [_cmd(_msg('Scene Explorer...'), 'SCENE_EXPLORER'), _cmd(_msg('Layer Explorer...'), 'LAYER_EXPLORER'), Item(_msg('Crease Explorer...')), Sub(_msg('All Global Explorers'), []), Item(_msg('Manage Local Explorers...')), Sub(_msg('Local Scene Explorers'), []), SEP, Sub(_msg('Containers'), [Sub(_msg('Local Content'), []), Sub(_msg('Inherited Content'), [])]), SEP, _cmd(_msg('Isolate Selection'), 'ISOLATE', hotkey=_msg('Alt+Q')), _cmd(_msg('End Isolate'), 'END_ISOLATE'), _cmd(_msg('Zoom Extents On Isolate'), 'ZOOM_EXTENTS_ISOLATE'), SEP, Item(_msg('Display Floater...')), SEP, *_off(_msg('Manage Scene States...'), _msg('Manage Templates...')), SEP, _cmd(_msg('Light Lister...'), 'LIGHT_LISTER'), SEP, _cmd(_msg('Mirror...'), 'MIRROR'), _cmd(_msg('Array...'), 'ARRAY'), Sub(_msg('Align'), [_cmd(_msg('Align...'), 'ALIGN', hotkey=_msg('Alt+A')), _cmd(_msg('Quick Align'), 'QUICK_ALIGN', hotkey=_msg('Shift+A')), Item(_msg('Spacing Tool...'), hotkey=_msg('Shift+I')), Item(_msg('Clone and Align ...')), SEP, _cmd(_msg('Align to View...'), 'ALIGN_TO_VIEW'), Item(_msg('Normal Align...'), hotkey=_msg('Alt+N')), *_off(_msg('Align Camera'), _msg('Place Highlight'))]), _cmd(_msg('Snapshot...'), 'SNAPSHOT'), SEP, Sub(_msg('Flow Studio'), [Item(_msg('Launch Flow Studio'))]), SEP, _cmd(_msg('Rename Objects...'), 'RENAME_OBJECTS'), SEP, *_off(_msg('Assign Vertex Colors...'), _msg('Color Clipboard...'), _msg('Perspective Match...')), SEP, Item(_msg('Viewport Canvas...')), SEP, Sub(_msg('Screen Capture'), [_cmd(_msg('Create Preview Animation...'), 'PREVIEW_ANIMATION', hotkey=_msg('Shift+V')), _cmd(_msg('Capture Still Image...'), 'CAPTURE_STILL'), SEP, _cmd(_msg('Play Preview Animation...'), 'PLAY_PREVIEW'), *_off(_msg('Save Preview Animation As...'), _msg('Open Preview Animation folder...'))]), SEP, Sub(_msg('Grids and Snaps'), [_cmd(_msg('Grid and Snap Settings...'), 'GRID_SNAP_SETTINGS'), SEP, _cmd(_msg('Show Home Grid'), 'SHOW_HOME_GRID', check=_grid_on), *_off(_msg('Activate Home Grid'), _msg('Activate Grid Object'), _msg('Align Grid to View')), SEP, _cmd(_msg('Snaps Toggle'), 'SNAPS_TOGGLE', hotkey='S', check=_snap_on), _cmd(_msg('Angle Snap Toggle'), 'ANGLE_SNAP', hotkey='A'), _cmd(_msg('Percent Snap Toggle'), 'PERCENT_SNAP'), Item(_msg('Enable Axis Constraints in Snaps'), hotkey=_msg('Alt+F3'))]), Sub(_msg('Snap Working Pivot Tools'), [Item(_msg('Place Working Pivot'), hotkey=_msg('Ctrl+Shift+`')), Item(_msg('Selection Pivot'), hotkey=_msg('Alt+Shift+S')), *_off(_msg('Align Working Pivot'), _msg('Reset Working Pivot')), SEP, Item(_msg('Align Pivot To Working Pivot')), SEP, Item(_msg('Place Pivot Bounding Box')), SEP, *_off(_msg('Create Grid From Working Pivot'), _msg('Create Point From Working Pivot'))]), _cmd(_msg('Measure Distance...'), 'MEASURE_DISTANCE'), SEP, Item(_msg('Channel Info...')), Sub(_msg('Mesh Inspector'), _off(_msg('Activate Mesh Inspector'), _msg('Mesh Auto Repair')))]), (_msg('Group'), [_cmd(_msg('Group...'), 'GROUP'), _cmd(_msg('Ungroup'), 'UNGROUP'), SEP, _cmd(_msg('Open'), 'GROUP_OPEN'), _cmd(_msg('Open Recursively'), 'GROUP_OPEN_RECURSIVE'), _cmd(_msg('Close'), 'GROUP_CLOSE'), SEP, _cmd(_msg('Attach'), 'GROUP_ATTACH', hotkey=_msg('Ctrl+U')), _cmd(_msg('Detach'), 'GROUP_DETACH'), SEP, _cmd(_msg('Explode'), 'GROUP_EXPLODE'), SEP, Sub(_msg('Assembly'), [*_off(_msg('Assemble'), _msg('Disassemble')), SEP, *_off(_msg('Open'), _msg('Close')), SEP, *_off(_msg('Attach'), _msg('Detach')), SEP, Item(_msg('Explode'))])]), (_msg('Views'), [_cmd(_msg('Undo View Change'), 'UNDO_VIEW', hotkey=_msg('Shift+Z')), _cmd(_msg('Redo View Change'), 'REDO_VIEW', hotkey=_msg('Shift+Y')), SEP, _cmd(_msg('Active Viewport Settings'), 'VIEWPORT_CONFIG'), _cmd(_msg('Viewports Configuration...'), 'VIEWPORT_CONFIG'), _cmd(_msg('Redraw All Views'), 'REDRAW_ALL', hotkey='`'), SEP, Sub(_msg('Set Active Viewport'), [_view(_msg('Perspective'), 'PERSP', hotkey='P'), _view(_msg('Orthographic'), 'ORTHO', hotkey='U'), _view(_msg('Front'), 'FRONT', hotkey='F'), _view(_msg('Back'), 'BACK'), _view(_msg('Top'), 'TOP', hotkey='T'), _view(_msg('Bottom'), 'BOTTOM'), _view(_msg('Left'), 'LEFT', hotkey='L'), _view(_msg('Right'), 'RIGHT'), SEP, _cmd(_msg('Save Active View'), 'ACTIVE_VIEW_SAVE'), _cmd(_msg('Restore Active View'), 'ACTIVE_VIEW_RESTORE')]), _cmd(_msg('Save Active View'), 'ACTIVE_VIEW_SAVE'), _cmd(_msg('Restore Active View'), 'ACTIVE_VIEW_RESTORE'), SEP, Sub(_msg('ViewCube'), _VIEWCUBE), Sub(_msg('SteeringWheels'), _STEERINGWHEELS), SEP, _cmd(_msg('Create Physical Camera From View'), 'CAMERA_FROM_VIEW', hotkey=_msg('Alt+Shift+C, Ctrl+C')), _cmd(_msg('Create Standard Camera From View'), 'CAMERA_FROM_VIEW', hotkey=_msg('Ctrl+Alt+Shift+C')), SEP, Sub(_msg('Show Materials in Viewport As'), _SHOW_MATERIALS_IN_VIEWPORT_AS), SEP, Sub(_msg('Viewport Lighting and Shadows'), [Item(_msg('Auto Display Selected Lights')), SEP, *_off(_msg('Lock Selected Lights'), _msg('Unlock Selected Lights'))]), SEP, Sub('xView', _XVIEW), SEP, Sub(_msg('Viewport Background'), _VIEWPORT_BACKGROUND), SEP, _cmd(_msg('Show Transform Gizmo'), 'SHOW_GIZMO'), _cmd(_msg('Show Ghosting'), 'SHOW_GHOSTING'), _cmd(_msg('Show Key Times'), 'SHOW_KEY_TIMES'), _cmd(_msg('Shade Selected'), 'SHADE_SELECTED'), Item(_msg('Show Dependencies')), SEP, Item(_msg('Update During Spinner Drag')), Item(_msg('Adaptive Degradation'), hotkey='O'), Item(_msg('Progressive Display')), SEP, _cmd(_msg('Expert Mode'), 'EXPERT_MODE', hotkey=_msg('Ctrl+Alt+X'))]), (_msg('Create'), [Sub(_msg('Standard Primitives'), [_create(_msg('Box'), 'BOX'), _create(_msg('Cone'), 'CONE'), _create(_msg('Sphere'), 'SPHERE'), _create(_msg('GeoSphere'), 'GEOSPHERE'), _create(_msg('Cylinder'), 'CYLINDER'), _create(_msg('Tube'), 'TUBE'), _create(_msg('Torus'), 'TORUS'), _create(_msg('Pyramid'), 'PYRAMID'), _create(_msg('Teapot'), 'TEAPOT'), _create(_msg('Plane'), 'PLANE'), _create(_msg('TextPlus'), 'TEXTPLUS')]), Sub(_msg('Extended Primitives'), [*_off(_msg('Hedra'), _msg('Torus Knot')), _create(_msg('Chamfer Box'), 'CHAMFER_BOX'), _create(_msg('Chamfer Cylinder'), 'CHAMFER_CYL'), Item(_msg('Oil Tank')), _create(_msg('Capsule'), 'CAPSULE'), *_off(_msg('Spindle'), _msg('L-Extrusion'), _msg('Gengon'), _msg('C-Extrusion'), _msg('RingWave'), _msg('Hose'), _msg('Prism'))]), Sub(_msg('AEC Objects'), [*_off(_msg('Foliage'), _msg('Railing'), _msg('Wall')), SEP, *_off(_msg('Pivot Door'), _msg('Sliding Door'), _msg('BiFold Door')), SEP, *_off(_msg('Straight Stair'), _msg('L-Type Stair'), _msg('U-Type Stair'), _msg('Spiral Stair')), SEP, *_off(_msg('Awning Window'), _msg('Casement Window'), _msg('Fixed Window'), _msg('Pivoted Window'), _msg('Sliding Window'), _msg('Projected Window')), SEP, Sub(_msg('MCG Tools'), [Sub(_msg('MCG Controllers'), _off(_msg('MCG LookAt Constraint'), _msg('MCG Ray to Surface Position Constraint'), _msg('MCG Ray to Surface Position and Orientation Constraints'), _msg('MCG Ray to Surface Transform Constraint'), _msg('MCG 1 DOF Rotation Spring Controller'), _msg('MCG 3 DOF Rotation Spring Controller')))])]), Sub(_msg('Compound'), _off(_msg('Morph'), _msg('Scatter'), _msg('Conform'), _msg('Connect'), _msg('BlobMesh'), _msg('ShapeMerge'), _msg('Boolean'), _msg('Terrain'), _msg('Loft'), _msg('Mesher'), _msg('ProBoolean'), _msg('ProCutter'))), Sub(_msg('Particles'), [Item(_msg('Particle Flow Source')), SEP, *_off(_msg('Spray'), _msg('Snow'), _msg('Blizzard'), _msg('PArray'), _msg('PCloud'), _msg('Super Spray'))]), Sub(_msg('Patch Grids'), _off(_msg('Quad Patch'), _msg('Tri Patch'))), Sub('NURBS', [_create(_msg('CV Surface'), 'CV_SURFACE'), _create(_msg('Point Surface'), 'POINT_SURFACE'), SEP, _create(_msg('CV Curve'), 'CV_CURVE'), _create(_msg('Point Curve'), 'POINT_CURVE')]), Sub(_msg('Point Cloud'), []), Sub(_msg('Dynamics'), _off(_msg('Damper'), _msg('Spring'))), SEP, Sub(_msg('Shapes'), [_create(_msg('Line'), 'LINE'), _create(_msg('Rectangle'), 'RECTANGLE'), _create(_msg('Circle'), 'CIRCLE'), _create(_msg('Ellipse'), 'ELLIPSE'), _create(_msg('Arc'), 'ARC'), _create(_msg('Donut'), 'DONUT'), _create(_msg('NGon'), 'NGON'), _create(_msg('Star'), 'STAR'), _create(_msg('Text'), 'TEXT'), _create(_msg('Helix'), 'HELIX'), *_off(_msg('Section'), _msg('Egg'), _msg('Freehand')), SEP, Item(_msg('ShapeBoolean'))]), Sub(_msg('Extended Shapes'), _off(_msg('WRectangle'), _msg('Channel'), _msg('Angle'), _msg('Tee'), _msg('Wide Flange'))), SEP, Sub(_msg('Lights'), [Sub(_msg('Photometric Lights'), [_create(_msg('Target Light'), 'TARGET_LIGHT'), _create(_msg('Free Light'), 'FREE_LIGHT')]), Sub(_msg('Standard Lights'), [_create(_msg('Target Spotlight'), 'TARGET_SPOT'), _create(_msg('Free Spotlight'), 'FREE_SPOT'), _create(_msg('Target Directional'), 'TARGET_DIRECT'), _create(_msg('Directional'), 'FREE_DIRECT'), _create(_msg('Omni'), 'OMNI'), _create(_msg('Skylight'), 'SKYLIGHT'), SEP, Item(_msg('Add Default Lights to Scene'))]), SEP, Item(_msg('Daylight System')), _create(_msg('Sun Positioner'), 'SUN_POSITIONER')]), Sub(_msg('Cameras'), [_create(_msg('Free Camera'), 'FREE_CAMERA'), _create(_msg('Target Camera'), 'TARGET_CAMERA'), _create(_msg('Physical Camera'), 'PHYSICAL_CAMERA'), SEP, _cmd(_msg('Create Physical Camera From View'), 'CAMERA_FROM_VIEW', hotkey=_msg('Alt+Shift+C, Ctrl+C')), _cmd(_msg('Create Standard Camera From View'), 'CAMERA_FROM_VIEW', hotkey=_msg('Ctrl+Alt+Shift+C'))]), SEP, Sub(_msg('Helpers'), [_create(_msg('Dummy'), 'DUMMY'), Item(_msg('Expose Transform')), _create(_msg('Grid'), 'GRID'), _create(_msg('Point'), 'POINT'), Item(_msg('Container')), _create(_msg('Arrow'), 'ARROW'), SEP, _create(_msg('Tape Measure'), 'TAPE'), _create(_msg('Protractor'), 'PROTRACTOR'), _create(_msg('Compass'), 'COMPASS'), SEP, Item(_msg('Camera Point')), SEP, Item(_msg('Influence Helper')), SEP, *_off(_msg('Delegate'), _msg('Crowd')), SEP, Sub(_msg('Atmospherics'), _off(_msg('Box Gizmo'), _msg('Cylinder Gizmo'), _msg('Sphere Gizmo'))), Sub(_msg('Manipulators'), _off(_msg('Slider'), _msg('Plane Angle'), _msg('Cone Angle'))), Sub(_msg('Particle Flow'), _off(_msg('Speed by Icon'), _msg('Find Target'), _msg('Particle Paint'), _msg('Birth Texture'), _msg('Initial State'), _msg('Group Select')))]), Sub(_msg('SpaceWarps'), [Sub(_msg('Forces'), [_create(_msg('Motor'), 'MOTOR'), _create(_msg('Push'), 'PUSH'), _create(_msg('Drag'), 'DRAG'), _create(_msg('Vortex'), 'VORTEX'), _create(_msg('Path Follow'), 'PATH_FOLLOW'), Item(_msg('PBomb')), _create(_msg('Displace'), 'DISPLACE_WARP'), _create(_msg('Gravity'), 'GRAVITY'), _create(_msg('Wind'), 'WIND'), Item(_msg('Motion Field'))]), Sub(_msg('Deflectors'), _off(_msg('POmniFlect'), _msg('SOmniFlect'), _msg('SDeflector'), _msg('UOmniFlect'), _msg('UDeflector'), _msg('Deflector'))), Sub(_msg('Geometric/Deformable'), [*_off(_msg('FFD(Box)'), _msg('FFD(Cyl)'), _msg('Wave'), _msg('Ripple')), _create(_msg('Displace'), 'DISPLACE_WARP'), *_off(_msg('Conform'), _msg('Bomb'))]), Sub(_msg('Modifier-Based'), _off(_msg('Bend'), _msg('Noise'), _msg('Skew'), _msg('Taper'), _msg('Twist'), _msg('Stretch'))), Sub(_msg('Particles & Dynamics'), [Item(_msg('Vector Field'))])]), Sub(_msg('Systems'), [_create(_msg('Bones IK Chain'), 'BONES'), Item(_msg('Biped')), SEP, Item(_msg('Daylight System'))]), SEP, Sub(_msg('Fluids'), [Item(_msg('Liquid'), 'object.quick_liquid'), Item(_msg('Fluid Loader'))])]), (_msg('Modifiers'), [Sub(_msg('Selection Modifiers'), _mods(_msg('FFD Select'), _msg('Mesh Select'), _msg('Patch Select'), _msg('Poly Select'), _msg('Select By Channel'), _msg('Spline Select'), _msg('Volume Select'))), SEP, Sub(_msg('Patch/Spline Editing'), _mods(_msg('Cross Section'), _msg('Delete Patch'), _msg('Delete Spline'), _msg('Edit Patch'), _msg('Edit Spline'), _msg('Spline Chamfer'), _msg('Lathe'), _msg('Normalize Spline'), _msg('Renderable Spline Modifier'), _msg('Surface'), _msg('Sweep'), _msg('Trim/Extend'), _msg('Optimize Spline'), _msg('Spline Mirror'), _msg('Spline Relax'))), Sub(_msg('Mesh Editing'), _mods(_msg('Attribute Transfer'), _msg('Cap Holes'), _msg('Chamfer'), _msg('Delete Mesh'), _msg('Edit Mesh'), _msg('Edit Normals'), _msg('Edit Poly'), _msg('Extrude'), _msg('Face Extrude'), _msg('MultiRes'), _msg('Normal Modifier'), _msg('Optimize'), _msg('ProOptimizer'), _msg('Quadify Mesh'), _msg('Smooth'), _msg('STL Check'), _msg('Symmetry'), _msg('Tessellate'), _msg('Vertex Paint'), _msg('Vertex Weld'), _msg('Weighted Normals'))), SEP, Sub(_msg('Conversion'), _mods(_msg('Turn To Mesh'), _msg('Turn To Patch'), _msg('Turn To Poly'))), SEP, Sub(_msg('Animation'), _mods(_msg('Attribute Holder'), _msg('Flex'), _msg('Linked XForm'), _msg('Melt'), _msg('Morpher'), _msg('Patch Deform'), _msg('Patch Deform (WSM)'), _msg('Path Deform'), _msg('Spline Influence'), _msg('Spline Morph'), _msg('Spline Overlap'), _msg('Path Deform (WSM)'), _msg('Skin'), _msg('Skin Morph'), _msg('Skin Wrap'), _msg('Skin Wrap Patch'), _msg('SplineIk Control'), _msg('Surf Deform'), _msg('Surf Deform (WSM)'))), SEP, Sub(_msg('Cloth'), _mods(_msg('Cloth'), _msg('Garment Maker'), _msg('Welder'))), SEP, Sub(_msg('Hair and Fur'), [_mod(_msg('Hair and Fur (WSM)'))]), SEP, Sub(_msg('UV Coordinates'), _mods(_msg('Camera Map'), _msg('Camera Map (WSM)'), _msg('MapScaler (WSM)'), _msg('Projection'), _msg('Unwrap UVW'), _msg('UVW Map'), _msg('UVW Mapping Add'), _msg('UVW Mapping Clear'), _msg('UVW XForm'))), SEP, Sub(_msg('Cache Tools'), _mods(_msg('Point Cache'), _msg('Point Cache (WSM)'))), SEP, Sub(_msg('Subdivision Surfaces'), _mods(_msg('Crease'), _msg('CreaseSet'), _msg('HSDS Modifier'), _msg('MeshSmooth'), _msg('OpenSubdiv'), _msg('TurboSmooth'))), SEP, Sub(_msg('Free Form Deformers'), _mods(_msg('FFD 2x2x2'), _msg('FFD 3x3x3'), _msg('FFD 4x4x4'), _msg('FFD Box'), _msg('FFD Cylinder'))), SEP, Sub(_msg('Parametric Deformers'), _mods(_msg('Affect Region'), _msg('Bend'), _msg('Conform Modifier'), _msg('Data Channel'), _msg('Displace'), _msg('Lattice'), _msg('Mirror'), _msg('Noise'), _msg('Noise Plus'), _msg('Physique'), _msg('Push'), _msg('Preserve'), _msg('Relax'), _msg('Ripple'), _msg('Shell'), _msg('Slice'), _msg('Skew'), _msg('Stretch'), _msg('Spherify'), _msg('Squeeze'), _msg('Twist'), _msg('Taper'), _msg('Substitute'), _msg('XForm'), _msg('Wave'))), SEP, Sub(_msg('Surface'), _mods(_msg('Disp Approx'), _msg('Displace Mesh (WSM)'), _msg('Material'), _msg('Material By Element'))), SEP, Sub(_msg('NURBS Editing'), _mods(_msg('Disp Approx'), _msg('Surf Deform'), _msg('Surface Select'))), SEP, Sub(_msg('Radiosity'), _mods(_msg('Subdivide'), _msg('Subdivide (WSM)'))), SEP, Sub(_msg('Cameras'), [_mod(_msg('Camera Correction'))])]), (_msg('Animation'), [*_off(_msg('Load Animation...'), _msg('Save Animation...')), SEP, Sub(_msg('IK Solvers'), [*_off(_msg('HI Solver'), _msg('HD Solver'), _msg('IK Limb Solver')), SEP, Item(_msg('SplineIK Solver'))]), SEP, Sub(_msg('Constraints'), [_constraint(_msg('Attachment Constraint'), 'ATTACHMENT'), _constraint(_msg('Surface Constraint'), 'SURFACE'), SEP, _constraint(_msg('Path Constraint'), 'PATH'), _constraint(_msg('Position Constraint'), 'POSITION'), SEP, _constraint(_msg('Link Constraint'), 'LINK'), SEP, _constraint(_msg('LookAt Constraint'), 'LOOKAT'), _constraint(_msg('Orientation Constraint'), 'ORIENTATION')]), SEP, Sub(_msg('Transform Controllers'), [_constraint(_msg('Link Constraint'), 'LINK'), *_off(_msg('Position/Rotation/Scale'), _msg('Script'), _msg('List'))]), Sub(_msg('Position Controllers'), [*_off(_msg('Audio'), _msg('Bezier'), _msg('Expression'), _msg('Linear'), _msg('Motion Capture'), _msg('Noise'), _msg('TCB Position'), _msg('Reaction'), _msg('Spring'), _msg('Script'), 'X Y Z', _msg('List')), SEP, _constraint(_msg('Attachment Constraint'), 'ATTACHMENT'), _constraint(_msg('Path Constraint'), 'PATH'), _constraint(_msg('Position Constraint'), 'POSITION'), _constraint(_msg('Surface Constraint'), 'SURFACE')]), Sub(_msg('Rotation Controllers'), [*_off(_msg('Audio'), _msg('Euler X Y Z'), _msg('Linear'), _msg('Motion Capture'), _msg('Noise'), _msg('TCB Rotation'), _msg('Reaction'), _msg('Script'), _msg('Smooth'), _msg('List')), SEP, _constraint(_msg('LookAt Constraint'), 'LOOKAT'), _constraint(_msg('Orientation Constraint'), 'ORIENTATION')]), Sub(_msg('Scale Controllers'), _off(_msg('Audio'), _msg('Bezier'), _msg('Expression'), _msg('Linear'), _msg('Motion Capture'), _msg('Noise'), _msg('TCB Scale'), _msg('Reaction'), _msg('Script'), 'X Y Z', _msg('List'))), Sub(_msg('MCG Controllers'), _off(_msg('MCG LookAt Constraint'), _msg('MCG Ray to Surface Position Constraint'), _msg('MCG Ray to Surface Position and Orientation Constraints'), _msg('MCG Ray to Surface Transform Constraint'), _msg('MCG 1 DOF Rotation Spring Controller'), _msg('MCG 3 DOF Rotation Spring Controller'))), Sub('CAT', _off(_msg('Capture Animation'), _msg('Pose Mixer'), _msg('Apply Max IK'))), Sub(_msg('MassFX'), [Sub(_msg('Rigid Bodies'), [Item(_msg('Set Selected as Dynamic Rigid Body'), 'rigidbody.objects_add', {'type': 'ACTIVE'}), Item(_msg('Set Selected as Kinematic Rigid Body')), Item(_msg('Set Selected as Static Rigid Body'), 'rigidbody.objects_add', {'type': 'PASSIVE'}), SEP, *_off(_msg('Create Dynamic Ragdoll'), _msg('Create Kinematic Ragdoll'), _msg('Remove Ragdoll'))]), Sub(_msg('Cloth'), [Item(_msg('Create mCloth'), 'object.modifier_add', {'type': 'CLOTH'}), Item(_msg('Remove mCloth'))]), Sub(_msg('Constraints'), [Item(_msg('Create Rigid Constraint'), 'rigidbody.connect', {'con_type': 'FIXED'}), Item(_msg('Create Slide Constraint'), 'rigidbody.connect', {'con_type': 'SLIDER'}), Item(_msg('Create Hinge Constraint'), 'rigidbody.connect', {'con_type': 'HINGE'}), Item(_msg('Create Twist Constraint')), Item(_msg('Create Ball-and-Socket Constraint'), 'rigidbody.connect', {'con_type': 'POINT'}), Item(_msg('Create Universal Constraint'))]), Sub(_msg('Simulation'), [Item(_msg('Play Simulation'), 'screen.animation_play'), Item(_msg('Step Simulation'), 'screen.frame_offset', {'delta': 1}), Item(_msg('Reset Simulation'), 'screen.frame_jump', {'end': False}), SEP, Item(_msg('Bake All Objects'), 'ptcache.bake_all', {'bake': True}), Item(_msg('Bake Selected Objects'), 'rigidbody.bake_to_keyframes'), Item(_msg('Unbake All Objects'), 'ptcache.free_bake_all'), Item(_msg('Unbake Selected Objects'))]), Sub(_msg('Utilities'), [*_off(_msg('Show MassFX Tools'), _msg('Open Dynamics Explorer')), SEP, *_off(_msg('Validate MassFX Scene'), _msg('Export MassFX Scene')), SEP, Item(_msg('Capture Current Transforms')), SEP, Item(_msg('About MassFX'))])]), Sub(_msg('Fluids'), [Item(_msg('Liquid'), 'object.quick_liquid'), *_off(_msg('Fluid Loader'), _msg('Motion Field'), _msg('Simulation View'))]), SEP, Sub(_msg('Offset Controllers'), _off(_msg('Add Offset Controllers'), _msg('Delete Offset Controllers'), _msg('Remove All'))), *_off(_msg('Parameter Editor...'), _msg('Parameter Collector...')), SEP, Sub(_msg('Wire Parameters'), _off(_msg('Wire Parameters...'), _msg('Parameter Wire Dialog...'))), SEP, Item(_msg('Animation Layers...')), SEP, Item(_msg('Reaction Manager...')), SEP, Item(_msg('Bone Tools...')), SEP, *_off(_msg('Set as Skin Pose'), _msg('Assume Skin Pose'), _msg('Skin Pose Mode')), SEP, Item(_msg('Toggle Limits')), SEP, _cmd(_msg('Delete Selected Animation'), 'DELETE_SELECTED_ANIMATION'), SEP, Sub(_msg('Populate'), [Item(_msg('Populate Tools...'))]), Item(_msg('Walkthrough Assistant...')), Sub(_msg('Presets'), [Item(_msg('Load Preset')), SEP, *_off(_msg('Add Scene Preset to Selected'), _msg('Remove Preset from Selected')), SEP, Item(_msg('Create Preset')), SEP, Item(_msg('Remove Preset From Disk'))])]), (_msg('Graph Editors'), [_editor(_msg('Track View - Curve Editor...'), 'GRAPH'), _editor(_msg('Track View - Dope Sheet...'), 'DOPESHEET'), _editor(_msg('New Track View...'), 'GRAPH'), Item(_msg('Delete Track View...')), Sub(_msg('Saved Track Views'), _off(_msg('Saved Track View 1'), _msg('Saved Track View 2'), _msg('Saved Track View 3'), _msg('Saved Track View 4'), _msg('Saved Track View 5'), _msg('Saved Track View 6'), _msg('Saved Track View 7'), _msg('Saved Track View 8'), _msg('Saved Track View 9'), _msg('Saved Track View 10'), _msg('Saved Track View 11'), _msg('Saved Track View 12'), _msg('Saved Track View 13'))), SEP, _cmd(_msg('New Schematic View...'), 'SCHEMATIC_VIEW'), Item(_msg('Delete Schematic View...')), Sub(_msg('Saved Schematic Views'), _off(_msg('Saved Schematic View 1'), _msg('Saved Schematic View 2'), _msg('Saved Schematic View 3'), _msg('Saved Schematic View 4'), _msg('Saved Schematic View 5'), _msg('Saved Schematic View 6'), _msg('Saved Schematic View 7'), _msg('Saved Schematic View 8'), _msg('Saved Schematic View 9'), _msg('Saved Schematic View 10'), _msg('Saved Schematic View 11'), _msg('Saved Schematic View 12'), _msg('Saved Schematic View 13'))), SEP, Item(_msg('Particle View Toggle'), hotkey='6'), SEP, _cmd(_msg('Motion Mixer...'), 'MOTION_MIXER')]), (_msg('Rendering'), [_cmd(_msg('Render'), 'RENDER', hotkey=_msg('Shift+Q, Shift+F9')), *_off(_msg('Render in the Cloud'), _msg('Open Autodesk A360 Gallery')), _editor(_msg('Render Setup...'), 'RENDER', hotkey='F10'), _cmd(_msg('Rendered Frame Window...'), 'RENDERED_FRAME_WINDOW'), SEP, *_off(_msg('Radiosity...'), _msg('Light Tracer...')), SEP, Item(_msg('Scene Converter...')), SEP, _cmd(_msg('Exposure Control...'), 'EXPOSURE'), SEP, _cmd(_msg('Environment...'), 'ENVIRONMENT', hotkey='8'), *_off(_msg('Effects...'), _msg('Raytracer Settings...'), _msg('Raytrace Global Include/Exclude...')), SEP, *_off(_msg('Render to Texture...'), _msg('Render Surface Map...')), SEP, Sub(_msg('Material Editor'), [_editor(_msg('Compact Material Editor...'), 'COMPACT'), _editor(_msg('Slate Material Editor...'), 'MATERIAL')]), Item(_msg('Material/Map Browser...')), _cmd(_msg('Material Explorer...'), 'MATERIAL_EXPLORER'), SEP, Item(_msg('Video Post...')), SEP, Item(_msg('Panorama Exporter...')), _cmd(_msg('Print Size Assistant...'), 'PRINT_SIZE'), SEP, _cmd(_msg('Color Management...'), 'COLOR_MANAGEMENT'), Item(_msg('Compare Media in RAM Player...'))]), (_msg('Customize'), [_cmd(_msg('Customize User Interface...'), 'CUSTOMIZE_UI'), _cmd(_msg('Hotkey Editor...'), 'HOTKEY_EDITOR'), Item(_msg('Menu Editor...')), SEP, *_off(_msg('Load Custom UI Scheme...'), _msg('Save Custom UI Scheme...')), SEP, Item(_msg('Custom Defaults Switcher...')), SEP, *_off(_msg('Revert to Startup UI Layout'), _msg('Lock UI Layout')), SEP, Sub(_msg('Show UI'), [*_off(_msg('Command Panel'), _msg('Ribbon'), _msg('Shared Views'), _msg('Time Slider'), _msg('Viewport Layout Tabs')), SEP, Sub(_msg('Float Viewport'), _off(_msg('Floating Viewport - 2'), _msg('Floating Viewport - 3'))), SEP, *_off(_msg('Main Toolbar'), _msg('Floating Toolbars'))]), Sub(_msg('Show Editors'), [_editor(_msg('Material Editor'), 'MATERIAL_LAST', hotkey='M'), _editor(_msg('Curve Editor'), 'GRAPH'), _editor(_msg('Dope Sheet'), 'DOPESHEET'), *_off(_msg('Max Creation Graph Editor'), _msg('Parameter Editor')), SEP, Item(_msg('Asset Tracking'), menu=_msg('TOPBAR_MT_file_external_data'), hotkey=_msg('Shift+T')), _cmd(_msg('Light Lister'), 'LIGHT_LISTER'), _cmd(_msg('Object Properties'), 'OBJECT_PROPERTIES'), Item(_msg('Particle View'), hotkey='6')]), Sub(_msg('Show Explorers'), [_cmd(_msg('Scene Explorer'), 'SCENE_EXPLORER'), _cmd(_msg('Layer Explorer'), 'LAYER_EXPLORER'), *_off(_msg('Crease Explorer'), _msg('Container Explorer'), _msg('Dynamics Explorer'), _msg('Light Explorer'), _msg('Missing Plug-in Explorer'), _msg('Revit Property Explorer'))]), SEP, _cmd(_msg('Configure Project Paths...'), 'CONFIGURE_PATHS'), _cmd(_msg('Configure User and System Paths...'), 'CONFIGURE_PATHS'), SEP, _cmd(_msg('Units Setup...'), 'UNITS_SETUP'), SEP, _cmd(_msg('Plug-in Manager...'), 'PLUGIN_MANAGER'), SEP, Item(_msg('Preferences...'), 'screen.userpref_show')]), (_msg('Scripting'), [Item(_msg('Install Max Creation Graph (.mcg) Package...')), SEP, *_off(_msg('New Max Creation Graph'), _msg('Open Max Creation Graph...'), _msg('Max Creation Graph Editor')), SEP, *_off(_msg('Create MCG Geometry...'), _msg('Create and Apply MCG Modifier...')), SEP, _cmd(_msg('New Script'), 'NEW_SCRIPT'), _cmd(_msg('Open Script...'), 'OPEN_SCRIPT'), _cmd(_msg('Run Script...'), 'RUN_SCRIPT'), SEP, _cmd(_msg('Scripting Listener...'), 'LISTENER', hotkey='F11'), _cmd(_msg('Scripting Editor...'), 'SCRIPT_EDITOR'), SEP, _cmd(_msg('Macro Recorder'), 'MACRO_RECORDER'), SEP, Item(_msg('Visual MAXScript Editor...')), SEP, Item(_msg('Debugger Dialog...')), SEP, Item(_msg('MAXScript Help...')), SEP, _cmd(_msg('Python Help...'), 'PYTHON_HELP')]), (_msg('Help'), [Item(_msg('Autodesk 3ds Max Help'), 'wm.url_open_preset', {'type': 'MANUAL'}), Item(_msg("What's New"), 'wm.url_open_preset', {'type': 'RELEASE_NOTES'}), Item(_msg('Welcome Screen'), 'wm.splash'), *_off(_msg('Autodesk Learning Resources'), _msg('Plugin Help...')), Sub(_msg('Tutorials'), _off(_msg('3ds Max Learning Channel'), _msg('More Learning Resources'))), Sub(_msg('3ds Max Developer Resources'), [Item(_msg('3ds Max Developer Help'), 'wm.url_open_preset', {'type': 'API'}), Item(_msg('3ds Max SDK Download')), Item(_msg('Autodesk Developer Network'), 'wm.url_open', {'url': 'https://developer.blender.org/docs/'})]), SEP, _cmd(_msg('Search 3ds Max Commands...'), 'SEARCH_COMMANDS', hotkey='X'), SEP, Sub(_msg('3ds Max Communities'), _off(_msg('Join Autodesk Feedback Community'), _msg('Student Community'))), Sub(_msg('Feedback'), [Item(_msg('Report a Problem...'), 'wm.url_open_preset', {'type': 'BUG'}), *_off(_msg('Ideas for 3ds Max'), _msg('Desktop Analytics Program...'))]), Sub(_msg('3ds Max Services and Support'), [Item(_msg('Support Center'), 'wm.url_open', {'url': 'https://www.blender.org/support'}), *_off(_msg('Data Exchange Solutions'), _msg('Certified Hardware'))]), Sub(_msg('3ds Max Resources and Tools'), [Item(_msg('Autodesk App Store'), 'wm.url_open_preset', {'type': 'EXTENSIONS'}), *_off(_msg('FBX Review'), _msg('Character Generator')), Item(_msg('Diagnose Video Hardware'), 'wm.sysinfo'), Item(_msg('Keyboard Shortcut Map'), 'bsm.shortcuts')]), Sub(_msg('Autodesk Product Information'), [Item(_msg('3ds Max Home Page'), 'wm.url_open_preset', {'type': 'BLENDER'}), *_off(_msg('Check for Updates'), _msg('Try Other Autodesk Products')), SEP, Item(_msg('About 3ds Max'), 'wm.splash_about')])])]
VIEWPORT_LABEL = {'PLUS': [Item(_msg('Maximize Viewport Toggle'), 'bsm.quad_view', hotkey=_msg('Alt+W')), Sub(_msg('Active Viewport'), _off(_msg('Active Viewport 1'), _msg('Active Viewport 2'), _msg('Active Viewport 3'), _msg('Active Viewport 4'))), Item(_msg('Disable Viewport'), hotkey=_msg('Ctrl+Shift+D')), SEP, Item(_msg('Presentation Mode'), 'screen.screen_full_area', {'use_hide_panels': True}, hotkey=_msg('Ctrl+Space'), check=_fullscreen_on), SEP, _cmd(_msg('Show Grids'), 'SHOW_HOME_GRID', hotkey='G', check=_grid_on), SEP, Sub(_msg('ViewCube'), _VIEWCUBE), Sub(_msg('SteeringWheels'), _STEERINGWHEELS), SEP, Sub('xView', _XVIEW), SEP, Sub(_msg('Create Preview'), [_cmd(_msg('Capture Still Image...'), 'CAPTURE_STILL'), _cmd(_msg('Create Preview Animation...'), 'PREVIEW_ANIMATION', hotkey=_msg('Shift+V')), SEP, _cmd(_msg('Play Preview Animation...'), 'PLAY_PREVIEW'), Item(_msg('Save Preview Animation As...'))]), SEP, _cmd(_msg('Configure Viewports...'), 'VIEWPORT_CONFIG'), SEP, Item(_msg('2D Pan Zoom Mode')), SEP, Sub(_msg('Float Viewport'), _off(_msg('Floating Viewport - 2'), _msg('Floating Viewport - 3')))], 'POV': [Item(_msg('Cameras'), menu=_msg('BSM_MT_view_cameras')), Item(_msg('Lights'), menu=_msg('BSM_MT_view_lights')), SEP, _view(_msg('Perspective'), 'PERSP', hotkey='P'), _view(_msg('Orthographic'), 'ORTHO', hotkey='U'), _view(_msg('Top'), 'TOP', hotkey='T'), _view(_msg('Bottom'), 'BOTTOM'), _view(_msg('Front'), 'FRONT', hotkey='F'), _view(_msg('Back'), 'BACK'), _view(_msg('Left'), 'LEFT', hotkey='L'), _view(_msg('Right'), 'RIGHT'), SEP, _cmd(_msg('Restore Active View'), 'ACTIVE_VIEW_RESTORE'), _cmd(_msg('Save Active View'), 'ACTIVE_VIEW_SAVE'), SEP, Sub(_msg('Extended Viewports'), [Sub(_msg('Track View'), [Item(_msg('New')), SEP, *_off(_msg('Saved Trackview 1'), _msg('Saved Trackview 2'), _msg('Saved Trackview 3'), _msg('Saved Trackview 4'), _msg('Saved Trackview 5'))]), Sub(_msg('Scene Explorer'), [Item(_msg('New')), SEP, *_off(_msg('Viewport Scene Explorer 1'), _msg('Viewport Scene Explorer 2'), _msg('Viewport Scene Explorer 3'), _msg('Viewport Scene Explorer 4'), _msg('Viewport Scene Explorer 5'), _msg('Viewport Scene Explorer 6'), _msg('Viewport Scene Explorer 7'), _msg('Viewport Scene Explorer 8'), _msg('Viewport Scene Explorer 9'), _msg('Viewport Scene Explorer 10'), _msg('More...'))]), Sub(_msg('Schematic View'), [Item(_msg('New')), SEP, *_off(_msg('Schematic View Save 1'), _msg('Schematic View Save 2'), _msg('Schematic View Save 3'), _msg('Schematic View Save 4'), _msg('Schematic View Save 5'))]), SEP, Sub(_msg('Grid'), _off(_msg('Front'), _msg('Back'), _msg('Top'), _msg('Bottom'), _msg('Left'), _msg('Right'), _msg('Display Planes'))), Item(_msg('Shape')), SEP, *_off(_msg('Extended Views 1'), _msg('Extended Views 2'), _msg('Extended Views 3'), _msg('Extended Views 4'), _msg('Extended Views 5'), _msg('Extended Views 6'), _msg('Extended Views 7'), _msg('Extended Views 8'), _msg('Extended Views 9'), _msg('Extended Views 10'))]), SEP, Item(_msg('Show Safe Frames'), 'wm.context_toggle', {'data_path': 'scene.camera.data.show_safe_areas'}, hotkey=_msg('Shift+F'), check=_safe_frames_on), *_off(_msg('Viewport Clipping'), _msg('Select Viewport Node'), _msg('Select Viewport Node Target')), SEP, _cmd(_msg('Undo Viewport Operation'), 'UNDO_VIEW', hotkey=_msg('Shift+Z')), _cmd(_msg('Redo Viewport Operation'), 'REDO_VIEW', hotkey=_msg('Shift+Y'))], 'PRESET': [_shade(_msg('High Quality'), 'HIGH_QUALITY', hotkey=_msg('Shift+F3')), _shade(_msg('Standard'), 'STANDARD'), _shade(_msg('Performance'), 'PERFORMANCE'), _shade(_msg('DX Mode'), 'DX_MODE'), Item(_msg('User Defined')), SEP, Sub(_msg('Lighting and Shadows'), [_shade(_msg('Illuminate with Default Lights'), 'DEFAULT_LIGHTS'), _shade(_msg('Illuminate with Scene Lights'), 'SCENE_LIGHTS'), Sub(_msg('Scene Lights Control'), [Item(_msg('Auto Display Selected Lights')), SEP, *_off(_msg('Lock Selected Lights'), _msg('Unlock Selected Lights'))]), SEP, Item(_msg('Progressive Skylight')), _shade(_msg('Shadows'), 'SHADOWS')]), Sub(_msg('Materials'), _SHOW_MATERIALS_IN_VIEWPORT_AS), SEP, _cmd(_msg('Viewports Configuration'), 'VIEWPORT_CONFIG'), _cmd(_msg('Active Viewport Settings'), 'VIEWPORT_CONFIG')], 'SHADING': [_shade(_msg('Default Shading'), 'DEFAULT_SHADING'), _shade(_msg('Facets'), 'FACETS'), _shade(_msg('Bounding Box'), 'BOUNDING_BOX'), _shade(_msg('Flat Color'), 'FLAT_COLOR'), _shade(_msg('Hidden Line'), 'HIDDEN_LINE'), _shade(_msg('Clay'), 'CLAY'), Item(_msg('Model Assist')), Sub(_msg('Stylized'), _off(_msg('Graphite'), _msg('Color Pencil'), _msg('Ink'), _msg('Color Ink'), _msg('Acrylic'), _msg('Pastel'), _msg('Tech'))), SEP, _shade(_msg('Wireframe Override'), 'WIREFRAME_OVERRIDE', check=_wireframe_on), _shade(_msg('Edged Faces'), 'EDGED_FACES', check=_edged_faces_on), SEP, Sub(_msg('Display Selected'), [Item(_msg('Display Selected With Edged Faces')), _shade(_msg('Shade Selected Faces'), 'SHADE_SELECTED', hotkey='F2')]), SEP, Sub(_msg('Viewport Background'), _VIEWPORT_BACKGROUND), SEP, _cmd(_msg('Viewport Preferences'), 'VIEWPORT_CONFIG'), Item(_msg('Viewport Filter'))]}

def _op_rna(idname):
    (module, _, name) = idname.partition('.')
    try:
        return getattr(getattr(bpy.ops, module), name).get_rna_type()
    except (AttributeError, KeyError):
        return None

def _menu_exists(name):
    return name in C_MENUS or hasattr(bpy.types, name)

def _resolve(item, context):
    """Operator idname to run for this entry now, or None when it cannot run as specified."""
    if not item.op:
        return None
    op = MODE_OPS.get(item.op, {}).get(getattr(context, 'mode', ''), item.op)
    rna = _op_rna(op)
    if rna is None:
        return None
    for (key, value) in item.props.items():
        prop = rna.properties.get(key)
        if prop is None or (prop.type == 'ENUM' and len(prop.enum_items) and (value not in prop.enum_items.keys())):
            return None
    return op

def _checked(item, context):
    try:
        return bool(item.check(context))
    except Exception:
        return False

def _set_props(kmi):
    props = kmi.properties
    if props is None:
        return {}
    return {p.identifier: getattr(props, p.identifier) for p in props.bl_rna.properties if p.identifier != 'rna_type' and props.is_property_set(p.identifier)}

def _blender_shortcuts(context, ops):
    """(op, props) pairs Blender itself will annotate with a shortcut in this menu.

    Approximates Blender's lookup: window/screen keymaps, plus the keymaps of the area
    the menu was opened from (3D View also searches the object/mesh mode keymaps).
    """
    keyconfig = context.window_manager.keyconfigs.user
    if not keyconfig or not ops:
        return []
    area = getattr(context, 'area', None)
    space = area.type if area else None
    names = {_msg('Window'), _msg('Screen')} | ({_msg('Object Mode'), _msg('Mesh')} if space == 'VIEW_3D' else set())
    found = []
    for keymap in keyconfig.keymaps:
        if keymap.name in names or (space and keymap.space_type == space):
            found.extend(((kmi.idname, _set_props(kmi)) for kmi in keymap.keymap_items if kmi.active and kmi.idname in ops))
    return found

def _text_width(context):
    """Width function in the menu font, or None when text cannot be measured."""
    try:
        import blf
        prefs = context.preferences
        blf.size(0, prefs.ui_styles[0].widget.points * (prefs.system.ui_scale or 1.0))
        if blf.dimensions(0, _dcc_ui_text('    '))[0] <= 0:
            return None
        return lambda text: blf.dimensions(0, _dcc_ui_text(text))[0]
    except Exception:
        return None

def _display_texts(context, items):
    """Labels with Max hotkey hints padded into one aligned column (Blender menus have no API for it)."""
    entries = [item for item in items if not isinstance(item, Sep)]
    hinted = [item for item in entries if isinstance(item, Item) and item.hotkey]
    if not hinted:
        return {}
    shown = _blender_shortcuts(context, {item.op for item in hinted if item.op})
    hinted = [item for item in hinted if (item.op, item.props) not in shown]
    width = _text_width(context) if hinted else None
    if width is None:
        return {id(item): item.label + '    ' + item.hotkey for item in hinted}
    column = max((width(item.label) for item in entries)) + width('    ')
    (space, fine) = (width(' '), width('\u200a'))
    texts = {}
    for item in hinted:
        need = column - width(item.label)
        count = max(1, int(need // space))
        rest = need - count * space
        texts[id(item)] = item.label + ' ' * count + ('\u200a' * int(round(rest / fine)) if 0 < fine < space else '') + item.hotkey
    return texts

class BSM_OT_max_menu_unavailable(bpy.types.Operator):
    """No Blender equivalent for this 3ds Max command"""
    bl_idname = 'bsm.max_menu_unavailable'
    bl_label = _msg('Not Available')
    bl_options = {'INTERNAL'}
    reason: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'}, translation_context=_msg('DCCWorkflowKit.Max'))

    @classmethod
    def poll(cls, context):
        return False

    @classmethod
    def description(cls, context, properties):
        return properties.reason or cls.__doc__

    def execute(self, context):
        return {'CANCELLED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def _greyed(layout):
    row = layout.row()
    row.enabled = False
    return row

def _unavailable(layout, text, reason=''):
    if _op_rna(BSM_OT_max_menu_unavailable.bl_idname) is None:
        _greyed(layout).label(text=_dcc_ui_text(text), translate=False)
    else:
        layout.operator(BSM_OT_max_menu_unavailable.bl_idname, text=_dcc_ui_text(text), translate=False).reason = reason

def draw_items(layout, items, context=None):
    """Draw entries into a menu layout: separators, submenus, greyed fallbacks, hints and checkboxes."""
    context = context or bpy.context
    texts = _display_texts(context, items)
    for item in items:
        if isinstance(item, Sep):
            layout.separator()
            continue
        text = texts.get(id(item), item.label)
        if isinstance(item, Sub):
            if item.idname:
                (layout if item.items else _greyed(layout)).menu(item.idname, text=_dcc_ui_text(text), translate=False)
            else:
                _unavailable(layout, text)
        elif item.menu:
            if _menu_exists(item.menu):
                layout.menu(item.menu, text=_dcc_ui_text(text), translate=False)
            else:
                _unavailable(layout, text, _msg('Blender menu %s is not available') % item.menu)
        else:
            op = _resolve(item, context)
            if op is None:
                _unavailable(layout, text, _msg('Needs %s, which is not available') % item.op if item.op else '')
                continue
            icon = ('CHECKBOX_HLT' if _checked(item, context) else 'CHECKBOX_DEHLT') if item.check else 'NONE'
            props = layout.operator(op, text=_dcc_ui_text(text), icon=icon, translate=False)
            for (key, value) in item.props.items():
                setattr(props, key, value)
_PREFIX = _msg('BSM_MT_max_')

def _idname(path, used):
    slug = re.sub('[^0-9a-z]+', '_', '_'.join(path).lower()).strip('_')
    name = _PREFIX + slug
    if len(name) > 60 or name in used:
        digest = hashlib.md5('/'.join(path).encode('utf-8')).hexdigest()[:6]
        name = _PREFIX + slug[:60 - len(_PREFIX) - 7].rstrip('_') + '_' + digest
    return name

def _menu_class(idname, label, items):

    def draw(self, context):
        draw_items(self.layout, items, context)
    return type(idname, (bpy.types.Menu,), {'bl_idname': idname, 'bl_label': label, 'draw': draw, 'bsm_items': items, 'bl_translation_context': 'DCCWorkflowKit.Max'})

def _build(path, label, items, used, classes):
    idname = _idname(path, used)
    used.add(idname)
    classes.append(_menu_class(idname, label, items))
    for item in items:
        if isinstance(item, Sub):
            if item.idname:
                raise ValueError(_msg('Sub %r is used twice; give each place its own Sub') % item.label)
            item.idname = _build(path + (item.label,), item.label, item.items, used, classes)
    return idname
_LABEL_TITLES = {'PLUS': _msg('Views - General Viewport Label Menu'), 'POV': _msg('Views - POV Viewport Label Menu'), 'PRESET': _msg('Views - Shading Viewport Nitrous Label Menu'), 'SHADING': _msg('Views - Viewport Preferences')}
(_used, _classes) = (set(), [])
MAIN_MENUS = [(_build((label,), label, items, _used, _classes), label) for (label, items) in MAIN]
LABEL_MENUS = {key: _build(('vp', key), _LABEL_TITLES[key], items, _used, _classes) for (key, items) in VIEWPORT_LABEL.items()}
CLASSES = (BSM_OT_max_menu_unavailable,) + tuple(_classes)
del _used, _classes
