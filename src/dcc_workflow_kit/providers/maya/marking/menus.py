# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""Maya marking menus as plain data (docs/steps/step_8.md 「계획」 1).

Positions and labels follow Maya's own marking menus. Re-implemented: only labels, radial
positions and the Blender action (same value forms as ``ui/menu_map.py``:
``"op.id"``, ``("op.id", {props})``, ``("v3d", ...)``, ``("tool", id, edit)``,
``("menu", id)``; ``None`` = greyed out). A radial ``Sub`` is a nested marking
menu, a list ``Sub`` a plain submenu.

Kept free of Blender UI so the step-9 marking-menu engine can draw the same
definitions.
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
RADIALS = ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')
DIVIDER = '-'

class Sub:
    """A submenu: ``radial`` {pos: (label, action)}, ``items`` [(label, action) | "-"].

    ``options``: labels whose Maya item has an option box ``[]``
    (Maya's option box items).
    """

    def __init__(self, radial=None, items=(), options=()):
        self.radial = dict(radial or {})
        self.items = list(items)
        self.options = frozenset(options)

class MarkingMenu(Sub):

    def __init__(self, name, label, source, radial=None, items=(), options=()):
        super().__init__(radial, items, options)
        self.name = name
        self.label = label
        self.source = source

def _mod(kind):
    return ('object.modifier_add', {'type': kind})

def _create(kind):
    return ('allset.create', {'kind': kind})

def _orient(kind, slot=0):
    return ('wm.context_set_enum', {'data_path': f'scene.transform_orientation_slots[{slot}].type', 'value': kind})

def _step(kind, mode='TOGGLE'):
    return ('allset.step_snap', {'kind': kind, 'mode': mode})

def _comp(kind):
    return ('allset.mm_component', {'type': kind})
MULTI_CUT = ('tool', 'allset.multi_cut_tool', True)
MERGE_CENTER = ('mesh.merge', {'type': 'CENTER'})
TARGET_WELD = ('tool', 'allset.target_weld_tool', True)
CREASE = ('tool', 'allset.crease_tool', True)
PRESERVE_UVS = ('wm.context_toggle', {'data_path': 'scene.tool_settings.use_transform_correct_face_attributes'})
PRESERVE_CHILDREN = ('wm.context_toggle', {'data_path': 'scene.tool_settings.use_transform_skip_children'})
TOOL_SETTINGS = ('allset.editor_toggle', {'editor': 'TOOL_SETTINGS'})
SMART_DUPLICATE = ('allset.manip_option', {'option': 'SMART_DUPLICATE'})
SMART_EXTRUDE = ('allset.manip_option', {'option': 'SMART_EXTRUDE'})

def _item(path):
    """Run Maya main-menu item ``path`` exactly like the menu (``allset.menu_item``: component / object mode rules,
    Maya warnings, option window as the option box); docs/steps/step_136.md 「계획」 B."""
    return ('item', path)

def _on_object(path):
    """A main-menu item run on the object the RMB menu was opened on (Maya acts on the object under the pointer)."""
    return ('allset.mm_object_item', {'item': path})

def _overlay(prop):
    return ('wm.context_toggle', {'data_path': f'space_data.overlay.{prop}'})
SOFT_EDGE_DISPLAY = _overlay('show_edge_sharp')
PAINT_SELECT = ('tool', 'builtin.select_circle', True)
CIRCULARIZE = _item('Edit Mesh/Circularize')

def _poly(kind):
    return ('allset.mm_poly', {'kind': kind})

def _sym(mode):
    return ('allset.symmetry', {'mode': mode})
SYMMETRY = (_dcc_source('Symmetry'), Sub(radial={'N': (_dcc_source('Symmetry'), _sym('ON')), 'W': (_dcc_source('World'), _sym('ABOUT_WORLD')), 'E': (_dcc_source('Object'), _sym('ABOUT_OBJECT')), 'NE': (_dcc_source('Topology'), _sym('TOPOLOGY')), 'SW': (_dcc_source('X Axis'), _sym('AXIS_X')), 'S': (_dcc_source('Y Axis'), _sym('AXIS_Y')), 'SE': (_dcc_source('Z Axis'), _sym('AXIS_Z'))}))
_FAVORITES = (('Lambert', 'LAMBERT'), ('Blinn', 'BLINN'), ('Phong', 'PHONG'), (_dcc_source('Standard Surface'), 'STANDARD_SURFACE'))

def _material_items():
    """A fresh list per menu, so each menu gets its own submenu class."""
    favorites = [(label, ('allset.shelf_material', {'kind': kind, 'rmb': True})) for (label, kind) in _FAVORITES]
    return [DIVIDER, (_dcc_source('Material Attributes...'), ('allset.material_attributes', {'rmb': True})), DIVIDER, (_dcc_source('Assign New Material...'), ('allset.assign_new_material', {'rmb': True})), (_dcc_source('Assign Favorite Material'), Sub(items=favorites)), (_dcc_source('Assign Existing Material'), ('menu', 'ALLSET_MT_assign_existing_material_rmb'))]
OBJECT_TITLE = '<object>...'

def unavailable():
    """A greyed submenu (▸) whose Maya contents Blender doesn't have."""
    return Sub()

class NodeList(Sub):
    """DG Traversal / Inputs / Outputs: filled from the object when the menu opens (``with_nodes``; Maya fills them
    when the submenu opens). Never greyed: Maya shows the header rows even with no node."""

    def __init__(self, kind):
        super().__init__()
        self.kind = kind

def is_unavailable(action):
    return isinstance(action, Sub) and (not isinstance(action, NodeList)) and (not action.radial) and (not action.items)

def _object_items():
    return [(OBJECT_TITLE, ('allset.object_attributes', {'rmb': True})), DIVIDER, (_dcc_source('Select'), ('allset.mm_component', {'type': 'NONE'})), (_dcc_source('Select All'), _item('Select/All')), (_dcc_source('Deselect All'), _item('Select/Deselect All')), (_dcc_source('Select Hierarchy'), ('allset.mm_select_hierarchy', {})), (_dcc_source('Invert Selection'), _item('Select/Inverse')), DIVIDER, (_dcc_source('Select Similar'), _item('Select/Similar')), DIVIDER, (_dcc_source('Make Live'), _on_object('Modify/Make Live')), DIVIDER, (_dcc_source('DG Traversal'), NodeList('TRAVERSAL')), (_dcc_source('Inputs'), NodeList(_dcc_source('INPUTS'))), (_dcc_source('Outputs'), NodeList('OUTPUTS')), (_dcc_source('Paint'), Sub(items=[(_dcc_source('Paint Skin Weights'), ('paint.weight_paint_toggle', {}))])), (_dcc_source('Metadata'), unavailable()), (_dcc_source('Actions'), Sub(items=[(_dcc_source('Template'), _on_object('Display/Object Display/Template')), (_dcc_source('Untemplate'), _on_object('Display/Object Display/Untemplate')), (_dcc_source('Unparent'), _on_object('Edit/Unparent')), (_dcc_source('Bounding Box'), ('allset.mm_bounding_box', {}))])), (_dcc_source('UV Sets'), ('menu', 'ALLSET_MT_uv_sets_rmb')), (_dcc_source('Color Sets'), ('menu', 'ALLSET_MT_color_sets_rmb')), (_dcc_source('Time Editor'), unavailable()), *_material_items()]
RMB_MESH = MarkingMenu('RMB_MESH', _dcc_source('Object'), 'maya', radial={'N': (_dcc_source('Edge'), _comp('EDGE')), 'W': (_dcc_source('Vertex'), _comp('VERT')), 'S': (_dcc_source('Face'), _comp('FACE')), 'E': ('UV', Sub(radial={'E': ('UV', ('allset.uv_component', {'mode': 'UV'})), 'S': (_dcc_source('UV Shell'), ('allset.uv_component', {'mode': 'SHELL'}))})), 'SW': (_dcc_source('Vertex Face'), None), 'SE': (_dcc_source('Multi'), _comp('MULTI')), 'NE': (_dcc_source('Object Mode'), ('object.mode_set', {'mode': 'OBJECT'}))}, items=_object_items(), options=(_dcc_source('Select Similar'),))
RMB_CURVE = MarkingMenu('RMB_CURVE', _dcc_source('Curve'), 'maya', radial={'N': (_dcc_source('Curve Point'), None), 'W': (_dcc_source('Control Vertex'), _comp('CV')), 'S': (_dcc_source('Edit Point'), None), 'E': (_dcc_source('Hull'), None), 'NE': (_dcc_source('Object Mode'), ('object.mode_set', {'mode': 'OBJECT'}))}, items=_object_items(), options=(_dcc_source('Select Similar'),))

def with_object_name(menu, name):
    """A copy of ``menu`` whose ``OBJECT_TITLE`` row shows ``name`` (Maya: "pCube1...")."""
    items = [(f'{name}...', e[1]) if e != DIVIDER and e[0] == OBJECT_TITLE else e for e in menu.items]
    if items == menu.items:
        return menu
    return MarkingMenu(menu.name, menu.label, menu.source, menu.radial, items, menu.options)
TITLE_ROW = ('allset.mm_node_label', {})

def _pick(owner, key, replace=False):
    return ('allset.mm_node', {'object': owner, 'key': key, 'replace': replace})

def _node_lines(entries):
    """(items, option labels) of node rows."""
    return ([(label, _pick(owner, key)) for (label, owner, key) in entries], {e[0] for e in entries})

def _history_sub(nodes, future):
    word = _dcc_source('Outputs') if future else _dcc_source('Inputs')
    obj = nodes['object']
    entries = nodes['outputs' if future else 'inputs']
    (rows, options) = _node_lines(entries)
    every = ('allset.mm_node_all', {'object': obj, 'future': future})
    items = [(f'Select All {word}', (every[0], {**every[1], 'action': 'SELECT'})), (f'Enable All {word}', (every[0], {**every[1], 'action': 'ENABLE'})), (f'Disable All {word}', (every[0], {**every[1], 'action': 'DISABLE'})), DIVIDER, *rows]
    if rows:
        items.append(DIVIDER)
    items.append((f'All {word}...', ('allset.mm_node_table', {'object': obj, 'future': future})))
    return Sub(items=items, options=options)

def _traversal_node(name, owner, key, nodes):
    """A node's own traversal submenu: Select <node>; the shape also lists its neighbours (one level)."""
    items = [(f'Select {name}', _pick(owner, key, replace=True))]
    if key == 'S':
        for (title, entries) in ((_dcc_source('History'), nodes['inputs_named']), (_dcc_source('Future'), nodes['future'][1:])):
            if entries:
                items += [DIVIDER, (title, TITLE_ROW)] + [(n, _pick(o, k, replace=True)) for (n, o, k) in entries]
    return Sub(items=items)

def _traversal_sub(nodes):
    obj = nodes['object']
    items = [(f'Select {obj}', _pick(obj, 'T', replace=True))]
    for (title, entries) in ((_dcc_source('History'), nodes['history']), (_dcc_source('Future'), nodes['future'])):
        if entries:
            items += [DIVIDER, (title, TITLE_ROW)]
            items += [(n, _traversal_node(n, o, k, nodes)) for (n, o, k) in entries]
    return Sub(items=items)

def fill(kind, nodes):
    """The filled submenu of NodeList ``kind`` from ``nodes``."""
    nodes = {'inputs': [], 'outputs': [], 'history': [], 'future': [], 'inputs_named': [], **nodes}
    if kind == 'TRAVERSAL':
        return _traversal_sub(nodes)
    return _history_sub(nodes, kind == 'OUTPUTS')

def with_nodes(menu, nodes):
    """A copy of ``menu`` with its NodeList submenus filled from ``nodes`` (None: unchanged)."""
    if not nodes:
        return menu
    items = []
    changed = False
    for e in menu.items:
        if e != DIVIDER and isinstance(e[1], NodeList):
            items.append((e[0], fill(e[1].kind, nodes)))
            changed = True
        else:
            items.append(e)
    if not changed:
        return menu
    return MarkingMenu(menu.name, menu.label, menu.source, menu.radial, items, menu.options)
RMB_EMPTY = MarkingMenu('RMB_EMPTY', _dcc_source('Select'), 'maya', items=[(_dcc_source('Select All'), _item('Select/All')), (_dcc_source('Complete Tool'), None)])

def _pivot_option(option):
    return ('allset.pivot_option', {'option': option})

def _pivot_reset(position=True, orientation=True):
    return ('allset.pivot_reset', {'position': position, 'orientation': orientation})
PIVOT_EDIT = MarkingMenu('PIVOT_EDIT', _dcc_source('Pivot'), 'maya', radial={'N': (_dcc_source('Pin Component Pivot'), _pivot_option('PIN')), 'S': (_dcc_source('Reset Pivot'), _pivot_reset()), 'NW': (_dcc_source('Snap Pivot Orientation'), _pivot_option('SNAP_ORI')), 'NE': (_dcc_source('Snap Pivot Position'), _pivot_option('SNAP_POS')), 'SW': (_dcc_source('Reset Pivot Orientation'), _pivot_reset(position=False)), 'SE': (_dcc_source('Reset Pivot Position'), _pivot_reset(orientation=False)), 'W': (_dcc_source('Show Orientation Handle'), None), 'E': (_dcc_source('Exit'), ('allset.pivot_exit', {}))}, items=[(_dcc_source('Bake Pivot Orientation'), _item('Modify/Bake Pivot'))])
SOFT_HARD = Sub(radial={'S': (_dcc_source('Toggle Soft Edge Display'), SOFT_EDGE_DISPLAY), 'SE': (_dcc_source('Harden Edge'), 'mesh.mark_sharp'), 'E': (_dcc_source('Soften/Harden'), _item('Mesh Display/Soften/Harden Edges')), 'NE': (_dcc_source('Soften Edge'), ('mesh.mark_sharp', {'clear': True}))}, options={_dcc_source('Soften/Harden')})
SHIFT_OBJECT = MarkingMenu('SHIFT_OBJECT', _dcc_source('Object Tools'), 'maya', radial={'S': (_dcc_source('Extrude'), _item('Edit Mesh/Extrude')), 'SW': (_dcc_source('Insert Edge Loop Tool'), _item('Mesh Tools/Insert Edge Loop')), 'E': (_dcc_source('Append to Polygon Tool'), _item('Mesh Tools/Append to Polygon')), 'NE': (_dcc_source('Fill Holes'), _item('Mesh/Fill Hole')), 'N': (_dcc_source('Target Weld Tool'), TARGET_WELD), 'W': (_dcc_source('Multi-Cut'), MULTI_CUT), 'NW': (_dcc_source('Sculpt Tool'), ('object.mode_set', {'mode': 'SCULPT'})), 'SE': (_dcc_source('Soften/Harden Edges'), Sub(radial={'S': (_dcc_source('Toggle Soft Edge Display'), SOFT_EDGE_DISPLAY), 'SE': (_dcc_source('Harden Edge'), 'object.shade_flat'), 'E': (_dcc_source('Soften/Harden'), 'object.shade_auto_smooth'), 'NE': (_dcc_source('Soften Edge'), 'object.shade_smooth')}, options={_dcc_source('Soften/Harden')}))}, items=[(_dcc_source('Smooth'), _mod('SUBSURF')), (_dcc_source('Subdiv Proxy'), _mod('SUBSURF')), (_dcc_source('Crease Tool'), CREASE), DIVIDER, (_dcc_source('Mirror'), 'allset.mirror'), DIVIDER, (_dcc_source('Triangulate'), _mod('TRIANGULATE')), (_dcc_source('Quadrangulate'), _item('Mesh/Quadrangulate')), (_dcc_source('Reduce'), _mod('DECIMATE')), DIVIDER, (_dcc_source('Separate'), 'allset.separate'), (_dcc_source('Combine'), 'allset.combine'), (_dcc_source('Booleans'), Sub(items=[(_dcc_source('Union'), _item('Mesh/Booleans/Union')), (_dcc_source('Difference'), _item('Mesh/Booleans/Difference (A - B)')), (_dcc_source('Intersection'), _item('Mesh/Booleans/Intersection'))], options={_dcc_source('Union'), _dcc_source('Difference'), _dcc_source('Intersection')})), DIVIDER, (_dcc_source('Quad Draw Tool'), _item('Mesh Tools/Quad Draw'))], options=[_dcc_source('Append to Polygon Tool'), _dcc_source('Combine'), _dcc_source('Crease Tool'), _dcc_source('Insert Edge Loop Tool'), _dcc_source('Mirror'), _dcc_source('Multi-Cut'), _dcc_source('Quad Draw Tool'), _dcc_source('Quadrangulate'), _dcc_source('Reduce'), _dcc_source('Sculpt Tool'), _dcc_source('Smooth'), _dcc_source('Subdiv Proxy'), _dcc_source('Target Weld Tool')])
SHIFT_VERTEX = MarkingMenu('SHIFT_VERTEX', _dcc_source('Vertex Tools'), 'maya', radial={'S': (_dcc_source('Extrude Vertex'), ('v3d', 'mesh.extrude_vertices_move', {})), 'E': (_dcc_source('Chamfer Vertex'), _item('Edit Mesh/Chamfer Vertices')), 'SW': (_dcc_source('Delete Vertex'), 'mesh.dissolve_verts'), 'SE': (_dcc_source('Vertex Normals'), Sub(radial={'S': (_dcc_source('Toggle Vertex Normal Display'), _overlay('show_vertex_normals')), 'NE': (_dcc_source('Average Normals'), 'mesh.average_normals'), 'E': (_dcc_source('Vertex Normal Edit Tool'), _item('Mesh Display/Vertex Normal Edit Tool')), 'SE': (_dcc_source('Set Normals to Face'), 'mesh.set_normals_from_faces')}, options={_dcc_source('Average Normals'), _dcc_source('Set Normals to Face')})), 'N': (_dcc_source('Merge Vertices'), Sub(radial={'NE': (_dcc_source('Merge Vertices'), _item('Edit Mesh/Merge')), 'N': (_dcc_source('Merge Vertices To Center'), MERGE_CENTER), 'S': (_dcc_source('Target Weld Tool'), TARGET_WELD)}, options={_dcc_source('Merge Vertices'), _dcc_source('Target Weld Tool')})), 'NE': (_dcc_source('Average Vertices'), 'mesh.vertices_smooth'), 'W': (_dcc_source('Multi-Cut'), MULTI_CUT), 'NW': (_dcc_source('Paint Select Vertices'), PAINT_SELECT)}, items=[(_dcc_source('Crease Tool'), CREASE), (_dcc_source('Connect Components'), _item('Edit Mesh/Connect')), (_dcc_source('Detach Components'), _item('Edit Mesh/Detach')), (_dcc_source('Connect Tool'), MULTI_CUT), DIVIDER, (_dcc_source('Circularize Vertices'), CIRCULARIZE), (_dcc_source('Reorder Vertices'), None)], options=[_dcc_source('Chamfer Vertex'), _dcc_source('Circularize Vertices'), _dcc_source('Connect Components'), _dcc_source('Connect Tool'), _dcc_source('Crease Tool'), _dcc_source('Extrude Vertex'), _dcc_source('Multi-Cut')])
SHIFT_EDGE = MarkingMenu('SHIFT_EDGE', _dcc_source('Edge Tools'), 'maya', radial={'S': (_dcc_source('Extrude Edge'), ('v3d', 'mesh.extrude_edges_move', {})), 'SW': (_dcc_source('Delete Edge'), 'mesh.dissolve_edges'), 'E': (_dcc_source('Bevel Edge'), _item('Edit Mesh/Bevel')), 'SE': (_dcc_source('Soften/Harden Edges'), SOFT_HARD), 'N': (_dcc_source('Merge/Collapse Edges'), Sub(radial={'NE': (_dcc_source('Merge Border Edges'), 'mesh.remove_doubles'), 'S': (_dcc_source('Target Weld Tool'), TARGET_WELD), 'NW': (_dcc_source('Merge Edge Tool'), None), 'E': (_dcc_source('Collapse Edge'), 'mesh.edge_collapse'), 'N': (_dcc_source('Merge Edges To Center'), MERGE_CENTER)}, options={_dcc_source('Merge Border Edges'), _dcc_source('Target Weld Tool'), _dcc_source('Merge Edge Tool')})), 'NE': (_dcc_source('Flip/Spin Edge'), Sub(radial={'N': (_dcc_source('Flip Triangle Edge'), 'mesh.edge_rotate'), 'E': (_dcc_source('Spin Forward'), ('mesh.edge_rotate', {'use_ccw': False})), 'W': (_dcc_source('Spin Backward'), ('mesh.edge_rotate', {'use_ccw': True}))})), 'W': (_dcc_source('Multi-Cut'), MULTI_CUT), 'NW': (_dcc_source('Paint Select Edges'), PAINT_SELECT)}, items=[(_dcc_source('Crease Tool'), CREASE), (_dcc_source('Insert Edge Loop Tool'), _item('Mesh Tools/Insert Edge Loop')), (_dcc_source('Slide Edge Tool'), _item('Mesh Tools/Slide Edge')), (_dcc_source('Circularize Components'), CIRCULARIZE), (_dcc_source('Edit Edge Flow'), _item('Edit Mesh/Edit Edge Flow')), DIVIDER, (_dcc_source('Add Divisions To Edge'), 'mesh.subdivide'), (_dcc_source('Bridge'), 'mesh.bridge_edge_loops'), (_dcc_source('Fill Hole'), 'mesh.fill_holes'), DIVIDER, (_dcc_source('Connect Components'), _item('Edit Mesh/Connect')), (_dcc_source('Detach Components'), 'mesh.edge_split')], options=[_dcc_source('Add Divisions To Edge'), _dcc_source('Bevel Edge'), _dcc_source('Bridge'), _dcc_source('Circularize Components'), _dcc_source('Connect Components'), _dcc_source('Crease Tool'), _dcc_source('Edit Edge Flow'), _dcc_source('Extrude Edge'), _dcc_source('Insert Edge Loop Tool'), _dcc_source('Multi-Cut'), _dcc_source('Slide Edge Tool')])
SHIFT_FACE = MarkingMenu('SHIFT_FACE', _dcc_source('Face Tools'), 'maya', radial={'N': (_dcc_source('Merge Faces To Center'), MERGE_CENTER), 'S': (_dcc_source('Extrude Face'), ('v3d', 'allset.extrude', {})), 'SW': (_dcc_source('Wedge Face'), _item('Edit Mesh/Wedge')), 'NE': (_dcc_source('Poke Face'), 'mesh.poke'), 'E': (_dcc_source('Bevel Face'), _item('Edit Mesh/Bevel')), 'SE': (_dcc_source('Face Normals'), Sub(radial={'S': (_dcc_source('Toggle Face Normal Display'), _overlay('show_face_normals')), 'NE': (_dcc_source('Reverse Propagate'), _poly('REVERSE_PROPAGATE')), 'SE': (_dcc_source('Conform Normals'), 'mesh.normals_make_consistent'), 'E': (_dcc_source('Reverse Normals'), _item('Mesh Display/Reverse'))}, options={_dcc_source('Reverse Normals')})), 'W': (_dcc_source('Multi-Cut'), MULTI_CUT), 'NW': (_dcc_source('Paint Select Faces'), PAINT_SELECT)}, items=[(_dcc_source('Smooth Faces'), ('mesh.subdivide', {'smoothness': 1.0})), (_dcc_source('Assign Invisible Faces'), None), (_dcc_source('Add Divisions To Faces'), 'mesh.subdivide'), (_dcc_source('Circularize Components'), CIRCULARIZE), (_dcc_source('Triangulate Faces'), 'mesh.quads_convert_to_tris'), (_dcc_source('Quadrangulate Faces'), 'mesh.tris_convert_to_quads'), DIVIDER, (_dcc_source('Bridge Faces'), 'mesh.bridge_edge_loops'), DIVIDER, (_dcc_source('Extract Faces'), ('mesh.separate', {'type': 'SELECTED'})), (_dcc_source('Duplicate Face'), ('v3d', 'mesh.duplicate_move', {})), (_dcc_source('Target Weld Tool'), TARGET_WELD)], options=[_dcc_source('Add Divisions To Faces'), _dcc_source('Assign Invisible Faces'), _dcc_source('Bevel Face'), _dcc_source('Bridge Faces'), _dcc_source('Circularize Components'), _dcc_source('Duplicate Face'), _dcc_source('Extract Faces'), _dcc_source('Extrude Face'), _dcc_source('Multi-Cut'), _dcc_source('Poke Face'), _dcc_source('Smooth Faces'), _dcc_source('Target Weld Tool'), _dcc_source('Wedge Face')])
SHIFT_DEFAULT = MarkingMenu('SHIFT_DEFAULT', _dcc_source('Create'), 'maya', radial={'N': (_dcc_source('Create Polygon Tool'), _item('Mesh Tools/Create Polygon')), 'NE': (_dcc_source('Disc'), _create('DISC')), 'E': (_dcc_source('Sphere'), _create('SPHERE')), 'SE': (_dcc_source('Torus'), _create('TORUS')), 'S': (_dcc_source('Cube'), _create('CUBE')), 'SW': (_dcc_source('Cone'), _create('CONE')), 'W': (_dcc_source('Cylinder'), _create('CYLINDER')), 'NW': (_dcc_source('Plane'), _create('PLANE'))}, items=[(_dcc_source('Platonic Solid'), _create('PLATONIC')), (_dcc_source('Pyramid'), _create('PYRAMID')), (_dcc_source('Prism'), _create('PRISM')), (_dcc_source('Pipe'), _create('PIPE')), (_dcc_source('Helix'), _create('HELIX')), (_dcc_source('Gear'), _create('GEAR')), DIVIDER, (_dcc_source('Type'), _create('TEXT')), (_dcc_source('Quad Draw Tool'), _item('Mesh Tools/Quad Draw'))], options=[_dcc_source('Cone'), _dcc_source('Create Polygon Tool'), _dcc_source('Cube'), _dcc_source('Cylinder'), _dcc_source('Disc'), _dcc_source('Gear'), _dcc_source('Helix'), _dcc_source('Pipe'), _dcc_source('Plane'), _dcc_source('Platonic Solid'), _dcc_source('Prism'), _dcc_source('Pyramid'), _dcc_source('Quad Draw Tool'), _dcc_source('Sphere'), _dcc_source('Torus')])
_CS = 'Select/Convert Selection/'
CTRL_CONVERT = MarkingMenu('CTRL_CONVERT', _dcc_source('Convert Selection'), 'maya', radial={'N': (_dcc_source('To Edges'), Sub(radial={'N': (_dcc_source('To Edges'), _item(_CS + _dcc_source('To Edges'))), 'S': (_dcc_source('To Contained Edges'), _item(_CS + _dcc_source('To Contained Edges'))), 'NW': (_dcc_source('To Contiguous Edges'), _item('Select/Contiguous Edges')), 'NE': (_dcc_source('To Edge Perimeter'), _item(_CS + _dcc_source('To Edge Perimeter')))}, options={_dcc_source('To Contiguous Edges')})), 'NW': (_dcc_source('Shrink Selection'), Sub(radial={'NW': (_dcc_source('Shrink'), _item('Select/Shrink')), 'N': (_dcc_source('Shrink Selection Along Loop'), _item('Select/Shrink Along Loop'))})), 'E': (_dcc_source('To UVs'), Sub(radial={'E': (_dcc_source('To UVs'), _item(_CS + _dcc_source('To UVs'))), 'NE': (_dcc_source('To UV Perimeter'), _item(_CS + _dcc_source('To UV Perimeter')))})), 'SE': (_dcc_source('Edge Loop Utilities'), Sub(radial={'SE': (_dcc_source('To Edge Loop'), _item(_CS + _dcc_source('To Edge Loop'))), 'NE': (_dcc_source('To Edge Loop and Delete'), _poly('LOOP_DELETE')), 'SW': (_dcc_source('To Edge Loop and Duplicate'), _poly('LOOP_DUPLICATE'))})), 'SW': (_dcc_source('Edge Ring Utilities'), Sub(radial={'SW': (_dcc_source('To Edge Ring'), _item(_CS + _dcc_source('To Edge Ring'))), 'SE': (_dcc_source('To Edge Ring and Split'), _poly('RING_SPLIT')), 'NW': (_dcc_source('To Edge Ring and Collapse'), _poly('RING_COLLAPSE'))})), 'S': (_dcc_source('To Faces'), Sub(radial={'S': (_dcc_source('To Faces'), _item(_CS + _dcc_source('To Faces'))), 'N': (_dcc_source('To Contained Faces'), _item(_CS + _dcc_source('To Contained Faces'))), 'SE': (_dcc_source('To Face Perimeter'), _item(_CS + _dcc_source('To Face Perimeter')))})), 'W': (_dcc_source('To Vertices'), Sub(radial={'W': (_dcc_source('To Vertices'), _item(_CS + _dcc_source('To Vertices'))), 'NW': (_dcc_source('To Vertex Perimeter'), _item(_CS + _dcc_source('To Vertex Perimeter')))})), 'NE': (_dcc_source('Grow Selection'), Sub(radial={'NE': (_dcc_source('Grow'), _item('Select/Grow')), 'N': (_dcc_source('Grow Along Loop'), _item('Select/Grow Along Loop'))}))}, items=[(_dcc_source('To Face Path'), _item(_CS + _dcc_source('To Face Path'))), (_dcc_source('To UV Shell'), _item(_CS + _dcc_source('To UV Shell'))), (_dcc_source('To Shell'), _item(_CS + _dcc_source('To Shell'))), (_dcc_source('To Shell Border'), _item(_CS + _dcc_source('To Shell Border'))), DIVIDER, (_dcc_source('Selection Boundary'), 'mesh.region_to_loop')])
OPT_MOVE = MarkingMenu('OPT_MOVE', _dcc_source('Move Options'), 'maya', radial={'NE': (_dcc_source('Component'), _orient('NORMAL', 1)), 'W': (_dcc_source('World'), _orient('GLOBAL', 1)), 'NW': (_dcc_source('Object'), _orient('LOCAL', 1)), 'SE': (_dcc_source('Keep Spacing'), None), 'N': SYMMETRY, 'E': (_dcc_source('Snap'), Sub(radial={'E': (_dcc_source('Discrete Move'), _step('TRANSLATE')), 'SE': (_dcc_source('Vertex'), ('allset.snap_toggle', {'snap': 'POINT'})), 'SW': (_dcc_source('Face Center'), None)})), 'SW': (_dcc_source('Axis'), Sub(radial={'NW': (_dcc_source('Normal'), _orient('NORMAL', 1)), 'W': (_dcc_source('Parent'), _orient('PARENT', 1)), 'NE': (_dcc_source('Along Rotation Axis'), _orient('GIMBAL', 1)), 'N': (_dcc_source('Live Object Axis'), None), 'SW': (_dcc_source('Custom'), None)}))}, items=[(_dcc_source('Smart Extrude'), SMART_EXTRUDE), (_dcc_source('Smart Duplicate'), SMART_DUPLICATE), DIVIDER, (_dcc_source('Preserve UVs'), PRESERVE_UVS), (_dcc_source('Preserve Children'), PRESERVE_CHILDREN), DIVIDER, (_dcc_source('Move Options'), TOOL_SETTINGS)])
OPT_ROTATE = MarkingMenu('OPT_ROTATE', _dcc_source('Rotate Options'), 'maya', radial={'NW': (_dcc_source('Object'), _orient('LOCAL', 2)), 'W': (_dcc_source('World'), _orient('GLOBAL', 2)), 'SW': (_dcc_source('Custom'), Sub(radial={'E': (_dcc_source('Custom'), None), 'NW': (_dcc_source('Reset'), None)})), 'SE': (_dcc_source('Discrete Rotate'), _step('ROTATE')), 'NE': (_dcc_source('Component'), _orient('NORMAL', 2)), 'E': (_dcc_source('Gimbal'), _orient('GIMBAL', 2)), 'N': SYMMETRY}, items=[(_dcc_source('Smart Extrude'), SMART_EXTRUDE), (_dcc_source('Smart Duplicate'), SMART_DUPLICATE), DIVIDER, (_dcc_source('Preserve UVs'), PRESERVE_UVS), (_dcc_source('Preserve Children'), PRESERVE_CHILDREN), DIVIDER, (_dcc_source('Rotate Options'), TOOL_SETTINGS)])
OPT_SCALE = MarkingMenu('OPT_SCALE', _dcc_source('Scale Options'), 'maya', radial={'W': (_dcc_source('World'), _orient('GLOBAL', 3)), 'NW': (_dcc_source('Object'), _orient('LOCAL', 3)), 'NE': (_dcc_source('Component'), _orient('NORMAL', 3)), 'SW': (_dcc_source('Axis'), Sub(radial={'W': (_dcc_source('Parent'), _orient('PARENT', 3)), 'NW': (_dcc_source('Normal'), _orient('NORMAL', 3)), 'N': (_dcc_source('Live Object Axis'), None), 'NE': (_dcc_source('Along Rotation Axis'), _orient('GIMBAL', 3))})), 'E': (_dcc_source('Snap Scale'), _step('RESIZE')), 'SE': (_dcc_source('Relative'), _step('RESIZE', 'RELATIVE')), 'N': SYMMETRY}, items=[(_dcc_source('Smart Extrude'), SMART_EXTRUDE), (_dcc_source('Smart Duplicate'), SMART_DUPLICATE), DIVIDER, (_dcc_source('Preserve UVs'), PRESERVE_UVS), (_dcc_source('Preserve Children'), PRESERVE_CHILDREN), DIVIDER, (_dcc_source('Scale Options'), TOOL_SETTINGS)])
OPT_SELECT = MarkingMenu('OPT_SELECT', _dcc_source('Select Options'), 'maya', radial={'NW': (_dcc_source('Marquee'), ('tool', 'builtin.select_box', False)), 'NE': (_dcc_source('Drag'), ('tool', 'builtin.select', False)), 'E': (_dcc_source('Camera-Based Selection'), ('allset.mm_camera_based', {})), 'SE': (_dcc_source('Clear Selection'), 'allset.mm_clear_selection'), 'W': (_dcc_source('Paint Select'), ('tool', 'builtin.select_circle', False)), 'SW': (_dcc_source('Lasso'), ('tool', 'builtin.select_lasso', False))})
SELECT_ALL = MarkingMenu('SELECT_ALL', _dcc_source('Select All / History'), 'maya', radial={'W': (_dcc_source('Select All Inputs'), None), 'E': (_dcc_source('Select All Outputs'), None), 'N': (_dcc_source('Enable All Outputs'), None), 'S': (_dcc_source('Disable All Outputs'), None), 'NW': (_dcc_source('Delete History'), 'allset.delete_history'), 'NE': (_dcc_source('Delete Non-Deformer History'), ('allset.delete_history', {'non_deformer': True})), 'SE': (_dcc_source('Freeze Transforms'), 'allset.freeze_transform')}, options={_dcc_source('Freeze Transforms')})

def _tan(kind):
    return ('allset.set_tangent', {'kind': kind})

def _key(action):
    return ('allset.key_edit', {'action': action})
KEY_TANGENT = MarkingMenu('KEY_TANGENT', _dcc_source('Keyframe / Tangents'), 'maya', radial={'W': (_dcc_source('Keys'), Sub(radial={'N': (_dcc_source('Delete Keys'), _key('DELETE')), 'NE': (_dcc_source('Convert to Key'), _key('TO_KEY')), 'E': (_dcc_source('Paste Keys'), _key('PASTE')), 'NW': (_dcc_source('Convert to Breakdown'), _key('TO_BREAKDOWN')), 'S': (_dcc_source('Copy Keys'), _key('COPY')), 'SW': (_dcc_source('Remove Inbetween'), _key('REMOVE_INBETWEEN')), 'W': (_dcc_source('Cut Keys'), _key('CUT')), 'SE': (_dcc_source('Add Inbetween'), _key('ADD_INBETWEEN'))})), 'E': (_dcc_source('Tangents'), Sub(radial={'N': (_dcc_source('Spline'), _tan('SPLINE')), 'E': (_dcc_source('Flat'), _tan('FLAT')), 'S': (_dcc_source('Linear'), _tan('LINEAR')), 'W': (_dcc_source('Clamped'), _tan('CLAMPED')), 'NW': (_dcc_source('Stepped'), _tan('STEPPED')), 'SW': (_dcc_source('Stepped Next'), _tan('STEPPED_NEXT')), 'SE': (_dcc_source('Plateau'), _tan('PLATEAU')), 'NE': (_dcc_source('Fixed'), _tan('FIXED'))}))})

def _mask(kind):
    return ('allset.component_mask', {'kind': kind})
SELECT_COMPONENT = MarkingMenu('SELECT_COMPONENT', _dcc_source('Component Pick Mask'), 'maya', radial={'N': (_dcc_source('Points'), Sub(radial={'N': (_dcc_source('All Points'), None), 'E': (_dcc_source('CVs'), None), 'SE': (_dcc_source('Poly Vertices'), _mask('VERT')), 'S': (_dcc_source('Lattice Points'), None), 'W': (_dcc_source('Particles'), None), 'SW': (_dcc_source('Subdiv Mesh Points'), None)})), 'NE': (_dcc_source('Parm Points'), Sub(radial={'NE': (_dcc_source('All Parm Points'), None), 'E': (_dcc_source('Edit Points'), None), 'S': (_dcc_source('Curve Points'), None), 'W': (_dcc_source('Surface Points'), None), 'SW': (_dcc_source('Subdiv Mesh UVs'), None)})), 'E': (_dcc_source('Lines'), Sub(radial={'E': (_dcc_source('All Lines'), None), 'S': (_dcc_source('Poly Edges'), _mask('EDGE')), 'W': (_dcc_source('Isoparms'), None), 'N': (_dcc_source('Trim Edges'), None), 'SE': (_dcc_source('Springs'), None)})), 'SE': (_dcc_source('Faces'), _mask('FACE')), 'S': (_dcc_source('Hulls'), None), 'SW': (_dcc_source('Pivots'), Sub(radial={'SW': (_dcc_source('All Pivots'), None), 'NW': (_dcc_source('Rotate Pivots'), None), 'NE': (_dcc_source('Scale Pivots'), None), 'SE': (_dcc_source('Joint Pivots'), None)})), 'W': (_dcc_source('Handles'), None), 'NW': (_dcc_source('Misc.'), Sub(radial={'NW': (_dcc_source('All Misc'), None), 'E': (_dcc_source('Local Rotation Axes'), None), 'S': (_dcc_source('Image Planes'), None)}))}, items=[(_dcc_source('All Components on'), _mask('ALL')), (_dcc_source('All Components off'), None), DIVIDER, (_dcc_source('Save to shelf'), None), DIVIDER, (_dcc_source('Select Objects'), ('object.mode_set', {'mode': 'OBJECT'}))])

def _component(kind):
    return ('allset.component_mode', {'type': kind})
SELECT_POLYGON = MarkingMenu('SELECT_POLYGON', _dcc_source('Polygon Components'), 'maya', radial={'N': (_dcc_source('Vertices'), _component('VERT')), 'E': (_dcc_source('Edges'), _component('EDGE')), 'S': (_dcc_source('Faces'), _component('FACE')), 'W': (_dcc_source('UVs'), ('allset.uv_component', {'mode': 'UV'}))})

def _pane(ui_type):
    return ('allset.hb_pane', {'ui_type': ui_type})

def _ui(element):
    return ('allset.hb_ui', {'element': element})

def _mask(preset):
    return ('allset.hb_mask', {'preset': preset})

def _view(view):
    return ('allset.hb_view', {'view': view})
SHADING_WS = ('allset.hb_workspace', {'name': _dcc_source('Shading')})
ANIMATION_WS = ('allset.hb_workspace', {'name': _dcc_source('Animation')})
HB_NORTH = MarkingMenu('HB_NORTH', _dcc_source('Panel Layouts'), 'maya', radial={'N': (_dcc_source('Single Perspective'), ('allset.hb_single', {})), 'NE': (_dcc_source('Hypershade/Render/Persp'), SHADING_WS), 'SE': (_dcc_source('Hypershade/Outliner/Persp'), SHADING_WS), 'E': (_dcc_source('Hypershade/Persp'), SHADING_WS), 'S': (_dcc_source('Toggle Outliner'), _item('Windows/Outliner')), 'SW': (_dcc_source('Persp/Graph/Outliner'), ANIMATION_WS), 'W': (_dcc_source('Persp/Graph'), ANIMATION_WS), 'NW': (_dcc_source('Persp/Relationship Editor'), None)})
HB_SOUTH = MarkingMenu('HB_SOUTH', _dcc_source('Panel Types'), 'maya', radial={'N': (_dcc_source('Outliner'), _pane('OUTLINER')), 'E': (_dcc_source('Graph Editor'), _pane('FCURVES')), 'SE': (_dcc_source('Dope Sheet'), _pane('DOPESHEET')), 'S': (_dcc_source('Hypergraph'), _pane('OUTLINER')), 'SW': (_dcc_source('Node Editor'), _pane('ShaderNodeTree')), 'W': (_dcc_source('Hypershade'), _pane('ShaderNodeTree')), 'NW': (_dcc_source('Render View'), _pane('IMAGE_EDITOR')), 'NE': (_dcc_source('Set Editor'), _pane('OUTLINER'))})
HB_EAST = MarkingMenu('HB_EAST', _dcc_source('UI Elements'), 'maya', radial={'N': (_dcc_source('Help Line'), _ui('HELP_LINE')), 'NE': (_dcc_source('Status Line'), _ui('STATUS_LINE')), 'E': (_dcc_source('Attributes'), Sub(radial={'E': (_dcc_source('Channel Box'), _ui('CHANNEL_BOX')), 'S': (_dcc_source('Layer Editor'), _ui('CHANNEL_BOX')), 'W': (_dcc_source('Attribute Editor'), _ui('ATTRIBUTE')), 'N': (_dcc_source('Tool Settings'), _ui('TOOL_SETTINGS'))})), 'SE': (_dcc_source('Tool Box'), _ui('TOOLBOX')), 'S': (_dcc_source('Time Slider'), None), 'SW': (_dcc_source('Range Slider'), None), 'W': (_dcc_source('Shelf'), ('allset.shelf_strip_toggle', {})), 'NW': (_dcc_source('Command Line'), _ui('COMMAND_LINE'))})
HB_WEST = MarkingMenu('HB_WEST', _dcc_source('Selection Masks'), 'maya', radial={'N': (_dcc_source('NURBS Mask'), _mask('NURBS')), 'NE': (_dcc_source('Hierarchy'), None), 'E': (_dcc_source('Animation Mask'), _mask('ANIMATION')), 'SE': (_dcc_source('Deformations Mask'), _mask('DEFORMATIONS')), 'S': (_dcc_source('Dynamics Mask'), None), 'SW': (_dcc_source('Polygons Mask'), _mask('POLYGONS')), 'W': (_dcc_source('Rendering Mask'), _mask('RENDERING')), 'NW': (_dcc_source('Object/Components'), 'object.editmode_toggle')}, items=[(_dcc_source('All Objects'), _mask('ALL'))])
HB_CENTER = MarkingMenu('HB_CENTER', _dcc_source('Views'), 'maya', radial={'N': (_dcc_source('Perspective View'), _view('PERSP')), 'E': (_dcc_source('Side View'), _view('RIGHT')), 'S': (_dcc_source('Front View'), _view('FRONT')), 'W': (_dcc_source('Top View'), _view('TOP')), 'NW': (_dcc_source('Left View'), _view('LEFT')), 'SW': (_dcc_source('Back View'), _view('BACK')), 'SE': (_dcc_source('Bottom View'), _view('BOTTOM'))}, items=[(_dcc_source('Hotbox Style'), Sub(items=[(_dcc_source('Zones and Menu Rows'), ('allset.hb_style', {'style': 'ALL'})), (_dcc_source('Zones Only'), ('allset.hb_style', {'style': 'ZONES'})), (_dcc_source('Center Zone Only'), ('allset.hb_style', {'style': 'CENTER'}))]))])
HOTBOX_ZONES = {'N': HB_NORTH, 'S': HB_SOUTH, 'E': HB_EAST, 'W': HB_WEST, 'C': HB_CENTER}

def _uvc(mode):
    return ('allset.uv_component', {'mode': mode})
UV_OPS = [(_dcc_source('Cut UV Edges'), 'allset.uv_cut'), (_dcc_source('Sew UV Edges'), 'allset.uv_sew'), (_dcc_source('Unfold'), 'allset.uv_unfold'), (_dcc_source('Layout'), 'allset.uv_layout')]
UV_EDITOR_RMB = MarkingMenu('UV_EDITOR_RMB', _dcc_source('UV Editor'), 'maya', radial={'S': (_dcc_source('Face'), _uvc('FACE')), 'N': (_dcc_source('Edge'), _uvc('EDGE')), 'E': ('UV', _uvc('UV')), 'W': (_dcc_source('Vertex'), _uvc('VERTEX')), 'NW': (_dcc_source('UV Shell'), _uvc('SHELL'))}, items=[*UV_OPS, DIVIDER, (_dcc_source('Select All'), ('uv.select_all', {'action': 'SELECT'})), (_dcc_source('Pin'), 'uv.pin'), (_dcc_source('Unpin'), ('uv.pin', {'clear': True}))])
UV_MAPPING = Sub(radial={'N': (_dcc_source('Planar'), 'allset.uv_planar'), 'NE': (_dcc_source('Normal-Based'), 'allset.uv_planar'), 'E': (_dcc_source('Camera-Based'), ('v3d', 'uv.project_from_view', {})), 'SE': (_dcc_source('Cylindrical'), ('v3d', 'uv.cylinder_project', {})), 'S': (_dcc_source('Best Plane'), _item('UV/Best Plane')), 'SW': (_dcc_source('Spherical'), ('v3d', 'uv.sphere_project', {})), 'W': (_dcc_source('Contour Stretch'), _item('UV/Contour Stretch')), 'NW': (_dcc_source('Automatic'), _item('UV/Automatic'))})
GRAB_UV = _item('UV Editor/Tools/Grab')
_UV_TAIL = [(_dcc_source('Texture Borders'), ('allset.uv_display', {'mode': 'TEXTURE_BORDERS'})), DIVIDER, (_dcc_source('UV Editor'), ('allset.uv_component', {'mode': 'OPEN'})), (_dcc_source('UV Set Editor'), _item('UV/UV Set Editor'))]
SHIFT_UV = MarkingMenu('SHIFT_UV', _dcc_source('UV Tools'), 'maya', radial={'N': (_dcc_source('Mapping'), UV_MAPPING), 'NE': (_dcc_source('3D Grab UV Tool'), GRAB_UV), 'E': (_dcc_source('Sew UVs'), 'allset.uv_sew'), 'SE': (_dcc_source('Create UV Shell'), 'allset.uv_create_shell'), 'S': (_dcc_source('Merge UVs'), 'allset.uv_merge'), 'SW': (_dcc_source('Delete UVs'), 'allset.uv_delete'), 'W': (_dcc_source('Cut UVs'), 'allset.uv_cut'), 'NW': (_dcc_source('3D Cut and Sew UV Tool'), 'allset.cut_sew_tool_set')}, items=[(_dcc_source('Auto Seams'), _item('UV/Auto Seams')), *_UV_TAIL])
SHIFT_UV_SHELL = MarkingMenu('SHIFT_UV_SHELL', _dcc_source('UV Shell Tools'), 'maya', radial={'N': (_dcc_source('Mapping'), UV_MAPPING), 'NE': (_dcc_source('3D Grab UV Tool'), GRAB_UV), 'E': (_dcc_source('Optimize'), 'uv.minimize_stretch'), 'SE': (_dcc_source('Flip'), ('transform.mirror', {'constraint_axis': (True, False, False)})), 'S': (_dcc_source('Auto Seams'), _item('UV/Auto Seams')), 'SW': (_dcc_source('Layout'), 'allset.uv_layout'), 'W': (_dcc_source('Unfold'), 'allset.uv_unfold'), 'NW': (_dcc_source('3D Cut and Sew UV Tool'), 'allset.cut_sew_tool_set')}, items=list(_UV_TAIL))
MENUS = {m.name: m for m in (RMB_MESH, RMB_CURVE, RMB_EMPTY, PIVOT_EDIT, SHIFT_OBJECT, SHIFT_VERTEX, SHIFT_EDGE, SHIFT_FACE, SHIFT_DEFAULT, CTRL_CONVERT, OPT_MOVE, OPT_ROTATE, OPT_SCALE, OPT_SELECT, SELECT_ALL, HB_NORTH, HB_SOUTH, HB_EAST, HB_WEST, HB_CENTER, UV_EDITOR_RMB, SHIFT_UV, SHIFT_UV_SHELL, KEY_TANGENT, SELECT_COMPONENT, SELECT_POLYGON)}
TOOL_OPTIONS = {'builtin.move': 'OPT_MOVE', 'builtin.rotate': 'OPT_ROTATE', 'builtin.scale': 'OPT_SCALE', 'builtin.transform': 'OPT_MOVE'}
SELECT_OPTIONS = 'OPT_SELECT'

def walk(sub, path):
    """Yield (path, label, action) for every entry, depth first; Sub actions included."""
    for pos in RADIALS:
        if pos in sub.radial:
            (label, action) = sub.radial[pos]
            yield (f'{path}/{pos}', label, action)
            if isinstance(action, Sub):
                yield from walk(action, f'{path}/{pos}')
    for (i, entry) in enumerate(sub.items):
        if entry == DIVIDER:
            continue
        (label, action) = entry
        yield (f'{path}/{i}', label, action)
        if isinstance(action, Sub):
            yield from walk(action, f'{path}/{i}')

def label_walk(sub, path):
    """Like ``walk`` with label paths ("SHIFT_FACE/Face Normals/Reverse Propagate"): the keys of
    ``ui/notices.MARKING`` (step 136)."""
    for pos in RADIALS:
        if pos in sub.radial:
            (label, action) = sub.radial[pos]
            yield (f'{path}/{label}', label, action)
            if isinstance(action, Sub):
                yield from label_walk(action, f'{path}/{label}')
    for entry in sub.items:
        if entry == DIVIDER:
            continue
        (label, action) = entry
        yield (f'{path}/{label}', label, action)
        if isinstance(action, Sub):
            yield from label_walk(action, f'{path}/{label}')

def is_greyed(action):
    """Drawn greyed whatever the context: no action, or an empty submenu."""
    return action is None or is_unavailable(action)

def greyed_entries():
    """[(label path, label)] of every greyed entry of every menu."""
    return [(p, label) for (name, menu) in MENUS.items() for (p, label, a) in label_walk(menu, name) if is_greyed(a)]

def sub_label_path(menu, sub):
    """Label path of submenu ``sub`` inside ``menu`` ("" for the menu itself), or None."""
    if sub is menu:
        return ''
    for (path, _label, action) in label_walk(menu, ''):
        if action is sub:
            return path.lstrip('/')
    return None
