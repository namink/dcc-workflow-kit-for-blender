# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender version differences in one place.

Supported: Blender 5.2 LTS (the main target) and 5.3, each checked by every test; 5.0.x / 5.1.x still install
(0.6.2 is the last version for Blender 4.5, and the 4.5 paths are gone). Every check of "which Blender is this"
lives here; feature code calls these helpers and stays the same on every version.
"""

import re
from operator import attrgetter

import bpy

VERSION = tuple(bpy.app.version[:2])
TARGET = (5, 2)                         # main target (Blender 5.2 LTS)
SUPPORTED = ((5, 2), (5, 3))            # the supported minors
STRICT_VERSIONS = SUPPORTED             # keymap patches must all apply to these minors' IC data
IS_TARGET = VERSION == TARGET
IS_STRICT = VERSION in STRICT_VERSIONS
# A Scene value typed into a button in mesh edit mode gets its own undo step from 5.3 on (5.2 skips that step)
UI_UNDO_FOR_SCENE_IN_EDIT = VERSION >= (5, 3)


# --- Help links ------------------------------------------------------------------------------------------------------
# The kit's tables name the main target's Blender manual / API / release notes (".../5.2/..."); a link opens the pages
# of the running Blender when it is a supported one (5.3 -> 5.3), else the main target's.
DOCS_VERSION = "%d.%d" % (VERSION if VERSION in SUPPORTED else TARGET)
_DOCS_LINK = re.compile(r"(docs\.blender\.org/(?:manual/[A-Za-z_]+|api)|developer\.blender\.org/docs/release_notes)"
                        r"/\d+\.\d+/")


def docs_url(url):
    """``url`` with the version of a Blender manual / API / release notes link set to ``DOCS_VERSION``; any other
    link as it is."""
    return _DOCS_LINK.sub(lambda m: f"{m.group(1)}/{DOCS_VERSION}/", url)


# Properties tab flags newer than 4.5: the Maya Workflow Kit template is still a 4.5-saved file
# and opens in 5.x with them on, so they carry no meaning in a kit dock's role (ui/maya_dock_roles.role).
# Only the flags this Blender has: 5.3 added the Compositor tab.
_LATER_TABS = ("show_properties_strip", "show_properties_strip_modifier", "show_properties_compositor")
LATER_PROPERTIES_TABS = frozenset(n for n in _LATER_TABS if n in bpy.types.SpaceProperties.bl_rna.properties)


# --- Outliner sort -----------------------------------------------------------------------------------------------
# Blender 5.3 replaced the Outliner's use_sort_alpha bool with the sort_method enum (ALPHA / CUSTOM / NONE).

def outliner_sort_alpha(space):
    """The Outliner sorts its rows by name."""
    return space.sort_method == 'ALPHA' if hasattr(space, "sort_method") else space.use_sort_alpha


def set_outliner_sort_alpha(space, on):
    """Sort by name, or keep the rows in their own order (off)."""
    if hasattr(space, "sort_method"):
        space.sort_method = 'ALPHA' if on else 'NONE'
    else:
        space.use_sort_alpha = on


def draw_outliner_sort(layout, space):
    """The sort row of a menu: 5.3's enum as a submenu row (``layout.prop`` would split the menu in two), else the
    Sort Alphabetically check box."""
    if hasattr(space, "sort_method"):
        layout.prop_menu_enum(space, "sort_method")
    else:
        layout.prop(space, "use_sort_alpha", text="Sort Alphabetically")


def primitive_add_args(add, kw):
    """``kw`` for the add operator ``add``: Blender 5.3 renamed text_add's ``radius`` to ``size``."""
    if "radius" in kw and "radius" not in add.get_rna_type().properties:
        kw["size"] = kw.pop("radius")
    return kw


def own_annotations(cls):
    """The annotations ``cls`` itself declares (not inherited), on every Python Blender runs.

    Python 3.14 (PEP 649 / 749, used by Linux distribution builds of Blender such as CachyOS, Issue #176) evaluates
    class annotations lazily: a class body no longer has a ``__annotations__`` name to read or update, and
    ``cls.__dict__`` holds ``__annotate__`` instead of ``__annotations__``. ``annotationlib`` (3.14+) evaluates them;
    older Pythons keep the dict in the class namespace."""
    try:
        import annotationlib
    except ImportError:
        return dict(cls.__dict__.get("__annotations__", {}))
    return dict(annotationlib.get_annotations(cls))


def has_op(module, name):
    """Does this Blender have the operator? (``bpy.ops.<mod>.<name>`` returns a wrapper for any name.)"""
    try:
        getattr(module, name).get_rna_type()
        return True
    except (AttributeError, KeyError):
        return False


def strips(sequence_editor):
    """The sequencer's top-level strips (5.0 removed ``sequences``)."""
    return sequence_editor.strips


def fcurve_owners(action):
    """Collections holding the action's F-curves: every channelbag of the layered action (5.0 removed the legacy
    ``Action.fcurves`` / ``Action.groups``)."""
    owners = []
    for layer in action.layers:
        for strip in layer.strips:
            owners.extend(getattr(strip, "channelbags", ()))
    return owners


def action_fcurves(action, slot=None):
    """F-curves of the action for one slot (``slot`` None = every slot), a list."""
    if action is None:
        return []
    if slot is not None:
        bag = channelbag(action, slot)
        return list(bag.fcurves) if bag is not None else []
    return [fc for owner in fcurve_owners(action) for fc in owner.fcurves]


def channelbag(action, slot):
    """The channelbag of ``slot`` (None when the slot has no keys yet)."""
    from bpy_extras.anim_utils import action_get_channelbag_for_slot
    return action_get_channelbag_for_slot(action, slot)


def id_fcurves(anim_id):
    """F-curves the ID's animation_data plays (its action's assigned slot), a list."""
    ad = getattr(anim_id, "animation_data", None)
    if ad is None or ad.action is None:
        return []
    slot = ad.action_slot
    return action_fcurves(ad.action, slot) if slot is not None else []


def id_fcurve_collection(anim_id):
    """The collection (with ``find`` / ``new`` / ``remove``) of the ID's slot F-curves, or None."""
    ad = getattr(anim_id, "animation_data", None)
    if ad is None or ad.action is None:
        return None
    slot = ad.action_slot
    if slot is None:
        return None
    bag = channelbag(ad.action, slot)
    return bag.fcurves if bag is not None else None


# --- Timeline ------------------------------------------------------------------------------
# Blender 5.x: the Timeline is a Dope Sheet mode; the timeline header is DOPESHEET_HT_editor_buttons.draw_header and
# DOPESHEET_MT_editor_menus with ``mode == 'TIMELINE'`` ($S52\startup\bl_ui\space_dopesheet.py:198-230, :395-412).

def timeline_header_classes():
    """(class whose ``draw_header`` draws the timeline buttons, class whose ``draw_collapsible`` draws
    the timeline menus)."""
    from bl_ui import space_dopesheet
    return space_dopesheet.DOPESHEET_HT_editor_buttons, space_dopesheet.DOPESHEET_MT_editor_menus


# --- UV select mode -------------------------------------------------------------------------
# 5.x: uv_select_mode is VERTEX / EDGE / FACE and island selection is the separate ``use_uv_select_island``.

def uv_island_mode(ts):
    return ts.use_uv_select_island


def set_uv_island_mode(ts, island):
    """Island (Maya shell) selection on, or plain UV (vertex) selection."""
    if not island:
        ts.uv_select_mode = 'VERTEX'
    ts.use_uv_select_island = island


# --- Render output format -------------------------------------------------------------------
# 5.x: ImageFormatSettings.media_type (IMAGE / MULTI_LAYER_IMAGE / VIDEO) picks which file formats exist;
# 'FFMPEG' needs media_type 'VIDEO' first.

def set_file_format(image_settings, fmt):
    image_settings.media_type = ('VIDEO' if fmt == 'FFMPEG' else
                                 'MULTI_LAYER_IMAGE' if fmt == 'OPEN_EXR_MULTILAYER' else 'IMAGE')
    image_settings.file_format = fmt


# --- bmesh ----------------------------------------------------------------------------------
# 5.2 renamed pointmerge_facedata's ``vert_snap`` to ``vert_target`` (bmesh.ops docstring).

def pointmerge_facedata(bm, verts, target):
    import bmesh
    key = "vert_target" if "vert_target" in (bmesh.ops.pointmerge_facedata.__doc__ or "") else "vert_snap"
    return bmesh.ops.pointmerge_facedata(bm, verts=verts, **{key: target})


# --- UV selection in bmesh ------------------------------------------------------------------
# 5.x: one UV selection per loop, ``loop.uv_select_vert`` / ``uv_select_edge`` (BMLoopUV has only uv / pin_uv,
# 5.x). ``uv`` (the UV layer) stays in the signatures for the callers.

def uv_vert_selected(loop, uv):
    return loop.uv_select_vert


def uv_vert_selected_reader():
    """``uv_vert_selected`` as one getter for ``map`` over many loops (no Python call per loop)."""
    return attrgetter("uv_select_vert")


def uv_edge_selected(loop, uv):
    return loop.uv_select_edge


def uv_edge_selected_reader():
    """``uv_edge_selected`` as one getter for ``map`` over many loops (no Python call per loop)."""
    return attrgetter("uv_select_edge")


def set_uv_vert_selected(loop, uv, value):
    loop.uv_select_vert = value


def set_uv_edge_selected(loop, uv, value):
    loop.uv_select_edge = value


def set_uv_face_selected(face, uv, value):
    """A face's UVs picked / unpicked with UV Sync Selection off: its loops, and the face's own flag
    (``BMFace.uv_select``, which a UV select-mode change flushes back to the loops)."""
    for loop in face.loops:
        loop.uv_select_vert = value
        loop.uv_select_edge = value
    face.uv_select = value


def uv_selection_on_loops(bm, synced):
    """The UV Editor shows the per-loop UV selection (``uv_edge_selected``) rather than the mesh selection: always
    with UV Sync Selection off, and with it on while 5.x keeps a UV selection of its own (``uv_select_sync_valid``)."""
    return not synced or getattr(bm, "uv_select_sync_valid", False)


def uv_sync_from_mesh(bm):
    """After the mesh selection was written with UV Sync Selection on: 5.x keeps a UV selection of its own while
    ``uv_select_sync_valid``, and the UV Editor draws that one, so it is refreshed from the mesh selection (#245)."""
    if getattr(bm, "uv_select_sync_valid", False):
        bm.uv_select_sync_from_mesh()


# --- Refilling an edit-mode BMesh ------------------------------------------------------------------
# ``BMesh.clear()`` also empties the BMesh's own select mode, and ``from_mesh`` doesn't set it again. 5.3's
# edit-mode click selection reads that mode (5.2 reads the tool settings): with it empty a click on a face, edge or
# vertex picks nothing (and deselects) until the select mode is set again (#380); ``select_flush_mode`` flushes
# nothing on every version. Every kit path that refills a BMesh goes through these.

_SELECT_MODE_NAMES = ('VERT', 'EDGE', 'FACE')


def bmesh_select_mode(bm):
    """The select mode ``bm`` should keep: its own, else (an edit-mode BMesh already emptied) the scene's mesh select
    mode."""
    mode = set(bm.select_mode)
    if not mode and bm.is_wrapped:
        ts = getattr(getattr(bpy.context, "scene", None), "tool_settings", None)
        if ts is not None:
            mode = {name for name, on in zip(_SELECT_MODE_NAMES, ts.mesh_select_mode) if on}
    return mode


def clear_bmesh(bm):
    """``bm.clear()`` keeping its select mode (see above)."""
    mode = bmesh_select_mode(bm)
    bm.clear()
    if mode:
        bm.select_mode = mode


def refill_bmesh(bm, me):
    """Replace the contents of ``bm`` (often the edit-mode BMesh) by mesh ``me``, keeping its select mode."""
    clear_bmesh(bm)
    mode = set(bm.select_mode)
    bm.from_mesh(me)
    if mode:
        bm.select_mode = mode


# --- Bone visibility ------------------------------------------------------------------------
# 5.x: a bone is hidden in pose / object mode by ``PoseBone.hide``; ``Bone.hide`` only hides the edit bone
# (api notes).

def bone_hidden(pb):
    return pb.hide


def set_bone_hidden(pb, hidden):
    pb.hide = hidden


def timeline_marker_menu():
    """The Timeline's Marker menu: DOPESHEET_MT_marker ($S52 space_dopesheet.py:573)."""
    return "DOPESHEET_MT_marker"


def save_dialog_args(op):
    """Extra arguments Blender's own Ctrl+S / Ctrl+Shift+S items pass: 5.2 adds
    ``show_save_modified_images_dialog`` (IC keymap data); none in 5.0 / 5.1."""
    props = op.get_rna_type().properties
    return {"show_save_modified_images_dialog": True} if "show_save_modified_images_dialog" in props else {}


def read_region_row(fb, region, y):
    """One framebuffer row of the region (``read_color``), or None when ``y`` is outside it: 5.1+ raises on
    out-of-bounds reads (api notes)."""
    y = int(y)
    if not 0 <= y < region.height or region.width <= 0:
        return None
    try:
        return fb.read_color(0, y, region.width, 1, 4, 0, 'UBYTE')
    except ValueError:
        return None


def flat_buffer(buf):
    """``buf`` (a ``gpu.types.Buffer``) as one dimension, so ``numpy.frombuffer`` takes it: 5.0 exports a buffer
    of more than one dimension as not C-contiguous (BufferError). The bytes stay as they are; any other buffer
    (no ``dimensions``) is returned unchanged."""
    dims = getattr(buf, "dimensions", None)
    if dims is None or isinstance(dims, int):
        return buf
    n = 1
    for d in dims:
        n *= d
    buf.dimensions = n
    return buf


# --- Materials ------------------------------------------------------------------------------
# 5.0: every material uses nodes; ``Material.use_nodes`` is deprecated (prints a warning when set). The helpers
# stay so callers keep one spelling.

def ensure_material_nodes(mat):
    pass


def material_uses_nodes(mat):
    return mat is not None and mat.node_tree is not None


# --- Worlds ---------------------------------------------------------------------------------
# Like materials (5.0: ``use_nodes`` deprecated, every World has its tree).

def ensure_world_nodes(world):
    """Turn the World's nodes on; True when this call turned them on (never: 5.x worlds always use nodes)."""
    return False


def release_world_nodes(world):
    pass


# --- Lights ---------------------------------------------------------------------------------
# 5.1: every light has a node tree; ``Light.use_nodes`` is deprecated (warns when read or set).
LIGHT_ALWAYS_NODES = VERSION >= (5, 1)


def ensure_light_nodes(light):
    """Turn the light's nodes on; True when this call turned them on (5.0)."""
    if LIGHT_ALWAYS_NODES or light.use_nodes:
        return False
    light.use_nodes = True
    return True


def release_light_nodes(light):
    """Turn off nodes ``ensure_light_nodes`` turned on (no-op where every light uses nodes)."""
    if not LIGHT_ALWAYS_NODES:
        light.use_nodes = False


def toolbar_back(theme):
    """The 3D View toolbar / sidebar background of the user's theme (read only — the kit never writes a theme):
    ``regions.sidebars.back`` (5.0 theme migration table)."""
    return theme.regions.sidebars.back


# --- GPU image shader -----------------------------------------------------------------------
# Kit textures (shelf icons) hold scene-linear colours. From 5.0 the builtin 'IMAGE' shader draws the values as they
# are and the converting shader is 'IMAGE_SCENE_LINEAR_TO_REC709_SRGB' (5.0 Python API notes, GPU).
LINEAR_IMAGE_SHADER = 'IMAGE_SCENE_LINEAR_TO_REC709_SRGB'


def closed_line_points(points):
    """``points`` with the first one again at the end: drawn as a 'LINE_STRIP' they make the closed outline. 5.3
    leaves out the side from the last point back to the first of a 'LINE_LOOP' batch; the strip draws the same lines
    on every version."""
    pts = list(points)
    return pts + pts[:1]


def closed_line_batch(shader, points):
    """A batch for ``shader`` drawing the closed outline through ``points`` (see ``closed_line_points``)."""
    from gpu_extras.batch import batch_for_shader
    return batch_for_shader(shader, 'LINE_STRIP', {"pos": closed_line_points(points)})


# --- Unified paint settings -----------------------------------------------------------------
def scene_annotation(scene):
    """The scene's annotation data (the 3D View's Annotate tool): ``Scene.annotation`` (5.2), else the older
    ``Scene.grease_pencil`` when it still holds annotation data."""
    gp = getattr(scene, "annotation", None)
    if gp is None:
        gp = getattr(scene, "grease_pencil", None)
        if gp is not None and not hasattr(gp, "layers"):
            gp = None
    return gp


# 5.0+: each paint mode has its own unified paint settings (``tool_settings.weight_paint.unified_paint_settings``)
# and the scene size is ``unprojected_size``, a diameter (5.0.1 / 5.2.3: "Diameter of brush in Blender
# units", #90).
def unified_paint_settings(ts, paint="weight_paint"):
    """The unified paint settings that apply to paint mode ``paint`` (a ToolSettings member name)."""
    return getattr(ts, paint).unified_paint_settings


def unprojected_radius(ups):
    """The brush radius in scene units."""
    return ups.unprojected_size / 2.0


def set_unprojected_radius(ups, radius):
    ups.unprojected_size = radius * 2.0


# --- Brush falloff curve ----------------------------------------------------------------------
# 5.0+: ``curve_distance_falloff_preset`` / ``curve_distance_falloff``.
def brush_falloff_props(brush):
    """(preset property, curve property) names of the brush's distance falloff."""
    return "curve_distance_falloff_preset", "curve_distance_falloff"


# --- Menus closing when the mouse leaves ----------------------------------------------------
# 5.0 keeps menus and popups open until a click, with the preference ``PreferencesView.menu_close_leave`` (default
# off) for closing a menu the mouse left (5.0 release notes, user interface, 5953ff318c; seen on 5.2.3). Python
# has no call that closes a popup and the kit never writes preferences, so with the 5.x default a held
# option box can't close the Maya menu under it.
def menus_close_on_leave(prefs):
    return prefs.view.menu_close_leave


# --- Geometry Nodes modifier inputs --------------------------------------------------------------------
# 5.0 – 5.1 keep a Geometry Nodes modifier's inputs as ID properties on the modifier (``md[socket identifier]``,
# ``<identifier>_use_attribute`` / ``_attribute_name``); 5.2 moved them to ``md.properties.inputs.<identifier>``
# with ``value``, ``type`` ('VALUE' / 'ATTRIBUTE') and ``attribute_name``, and ``md[key] = value`` raises
# (5.2.3).
GN_INPUT_STRUCT = "properties" in bpy.types.NodesModifier.bl_rna.properties


def _gn_input(md, key):
    return getattr(md.properties.inputs, key, None)


def gn_input_get(md, key):
    """The value of input ``key`` (socket identifier) of the Geometry Nodes modifier ``md``, or None."""
    if GN_INPUT_STRUCT:
        item = _gn_input(md, key)
        return item.value if item is not None else None
    return md[key] if key in md else None


def gn_input_set(md, key, value):
    if GN_INPUT_STRUCT:
        item = _gn_input(md, key)
        if item is not None:
            item.value = value
        return
    md[key] = value


def gn_input_path(key):
    """The data path, on the modifier, of the value of input ``key`` (what a key on that input animates)."""
    if GN_INPUT_STRUCT:
        return f"properties.inputs.{key}.value"
    return f'["{key}"]'


def gn_input_attribute(md, key, attribute):
    """Make input ``key`` read the named attribute ``attribute`` (a vertex group) instead of a value."""
    if GN_INPUT_STRUCT:
        item = _gn_input(md, key)
        if item is not None:
            item.type = 'ATTRIBUTE'
            item.attribute_name = attribute
        return
    md[f"{key}_use_attribute"] = True
    md[f"{key}_attribute_name"] = attribute


def compare_inputs(node):
    """The (A, B) input sockets of a ``FunctionNodeCompare`` for its current data type. 5.0 – 5.1 keep every type's
    sockets on the node (A / B float first, then ``A_INT`` / ``B_INT`` ...; the others unavailable); 5.2 keeps only
    the current type's two (an index 2 raised IndexError). Looked up by identifier, else the first two."""
    suffix = {'INT': "_INT", 'VECTOR': "_VEC3", 'RGBA': "_COL", 'STRING': "_STR"}.get(node.data_type, "")
    by_id = {s.identifier: s for s in node.inputs}
    a, b = by_id.get("A" + suffix), by_id.get("B" + suffix)
    if a is not None and b is not None:
        return a, b
    return node.inputs[0], node.inputs[1]


# --- Top bar: where the first menu of the Maya menu bar opens ------------------------------------------
# Option box click model (ui/option_click.py): top bar region left -> the first Maya menu's pulldown,
# in widget units: 1.25 on 5.0 – 5.2 (gui_step183_option_click at UI 1.0 = 25 px of 20, UI 1.25 = 31 px
# of 25 on 5.0.1 / 5.1.2 / 5.2.3).
MENU_BAR_LEAD_UNITS = 1.25



# --- Mesh selection attributes ----------------------------------------------------------------------------------
# Blender 5.0.1 (5.2.3 makes a BOOLEAN): computing a mesh's edges (``Mesh.from_pydata`` with no
# edges, ``Mesh.update(calc_edges=True)``) while it has a ``.select_vert`` attribute creates ``.select_edge`` as an
# EDGE **INT32_2D** attribute (the ``.edge_verts`` layout). Blender then crashes on reading it as a selection:
# writing ``MeshEdge.select`` (rna_MeshEdge_select_set), leaving weight paint (mesh_select_vert_flush), and edit mode
# gets a garbage edge selection. Feature check by type: a selection attribute that is not BOOLEAN on its domain is
# dropped and rebuilt from the vertex selection.
_SELECT_ATTRS = ((".select_vert", 'POINT'), (".select_edge", 'EDGE'), (".select_poly", 'FACE'))


def repair_selection_attributes(mesh):
    """Replace wrongly typed selection attributes (Blender 5.0.1 calc_edges bug) by BOOLEAN ones derived from the
    vertex selection. Returns True when something was repaired. Object mode / non-edit meshes only."""
    bad = [(a.name, d) for n, d in _SELECT_ATTRS for a in mesh.attributes
           if a.name == n and (a.data_type != 'BOOLEAN' or a.domain != d)]
    if not bad:
        return False
    import numpy as np
    for name, _domain in bad:
        for a in [a for a in mesh.attributes if a.name == name]:
            mesh.attributes.remove(a)
    vsel = np.zeros(len(mesh.vertices), bool)
    if len(vsel):
        mesh.vertices.foreach_get("select", vsel)
    for name, domain in bad:
        if name == ".select_vert":
            continue                      # absent = nothing selected
        a = mesh.attributes.new(name, 'BOOLEAN', domain)
        if name == ".select_edge":
            ev = np.zeros(2 * len(mesh.edges), np.int32)
            mesh.edges.foreach_get("vertices", ev)
            ev = ev.reshape(-1, 2)
            values = vsel[ev[:, 0]] & vsel[ev[:, 1]] if len(ev) else np.zeros(0, bool)
        else:
            values = np.array([all(vsel[i] for i in p.vertices) for p in mesh.polygons], bool)
        a.data.foreach_set("value", values.tolist())
    mesh.update()
    return True


def mesh_from_pydata(mesh, vertices, edges, faces):
    """``Mesh.from_pydata`` + the Blender 5.0.1 selection-attribute repair above (use it whenever edges are left for
    Blender to compute)."""
    mesh.from_pydata(vertices, edges, faces)
    repair_selection_attributes(mesh)


# === Blender 5.3: weight paint brushes, paint panels, theme header text ==========================================

# --- "Use unified" switches ------------------------------------------------------------------------------------
# Up to 5.2 the switches that make a paint mode's brushes share one size / strength / weight belong to the mode's
# unified paint settings (``UnifiedPaintSettings.use_unified_*``). 5.3 moved them onto each brush
# (``Brush.use_unified_*``, size on and strength / weight off in the essentials brushes); the unified settings keep
# the shared values, and their old switches are deprecated and change nothing.
BRUSH_UNIFIED_SWITCHES = "use_unified_size" in bpy.types.Brush.bl_rna.properties
UNIFIED_NAMES = ("size", "strength", "weight")


def unified_switch_owner(ups, brush):
    """The struct whose ``use_unified_<name>`` switches decide what ``brush`` shares: the brush (5.3; None without a
    brush), else the paint mode's unified settings ``ups``."""
    return brush if BRUSH_UNIFIED_SWITCHES else ups


def unified_on(ups, brush, name):
    """Does ``brush`` use the shared ``name`` ('size', 'strength' or 'weight') of ``ups``?"""
    owner = unified_switch_owner(ups, brush)
    return owner is not None and bool(getattr(owner, "use_unified_" + name))


def unified_value_owner(ups, brush, name):
    """Where strokes of ``brush`` read ``name`` (and where the kit writes it): ``ups`` when shared or without a
    brush, else the brush."""
    return ups if brush is None or unified_on(ups, brush, name) else brush


def set_unified(ups, brush, name, on):
    """Share ``name`` across the paint mode's brushes (``on``) or not; False when Blender refused (no brush, or a
    brush that can't be edited)."""
    owner = unified_switch_owner(ups, brush)
    if owner is None:
        return False
    try:
        setattr(owner, "use_unified_" + name, on)
        return True
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return False


def unified_switches(ups, brush):
    """{name: shared} of ``brush`` for size / strength / weight, or None when there is no brush to read."""
    if BRUSH_UNIFIED_SWITCHES and brush is None:
        return None
    return {name: unified_on(ups, brush, name) for name in UNIFIED_NAMES}


def keep_unified_switches(ups, brush, switches):
    """After the kit changed the brush: ``brush`` shares what the previous one shared (``unified_switches`` read
    before the change). Up to 5.2 the switches belong to the paint mode and already stay."""
    if not BRUSH_UNIFIED_SWITCHES or brush is None or not switches:
        return
    for name, on in switches.items():
        if unified_on(ups, brush, name) != on:
            set_unified(ups, brush, name, on)


# --- Weight paint brush asset shelf ----------------------------------------------------------------------------
# Up to 5.2 the weight paint brushes' asset shelf (``VIEW3D_AST_brush_weight_paint``) is hidden by default: a 3D View
# shows it only once the user opens it. 5.3 gave it the default-visible option of the other paint modes' shelves: the
# first time a view is in Weight Paint, Blender opens the shelf under it.
WEIGHT_SHELF_TYPE = "VIEW3D_AST_brush_weight_paint"


def weight_shelf_shown_first():
    """The weight paint brush shelf type when Blender opens it the first time a view is in Weight Paint (5.3), else
    None."""
    cls = getattr(bpy.types, WEIGHT_SHELF_TYPE, None)
    return cls if cls is not None and 'DEFAULT_VISIBLE' in getattr(cls, "bl_options", ()) else None


# --- Essentials weight paint brushes -------------------------------------------------------------------------
# 5.3 renamed the essentials draw brush "Paint" (blend Mix, strength 1) to "Set Weight" and gives new scenes, and
# files that painted with "Paint", "Add Weight" (blend Add, strength 0.05, accumulating); 5.0 - 5.2 start with "Paint".
WEIGHT_BRUSH_ASSETS = {'DRAW': "Set Weight" if VERSION >= (5, 3) else "Paint", 'BLUR': "Blur",
                       'AVERAGE': "Average", 'SMEAR': "Smear"}
_WEIGHT_START_BRUSH = "Add Weight" if VERSION >= (5, 3) else ""


def weight_brush_asset(kind):
    """The essentials weight paint brush asset (``brushes/...mesh_weight.blend/Brush/<name>``) of brush ``kind``."""
    return "brushes/essentials_brushes-mesh_weight.blend/Brush/" + WEIGHT_BRUSH_ASSETS[kind]


def is_adding_start_brush(brush):
    """Is ``brush`` the essentials brush 5.3 starts weight painting with ("Add Weight"), still adding (blend Add)?
    Always False up to 5.2, whose start brush mixes."""
    return (bool(_WEIGHT_START_BRUSH) and brush is not None and brush.name == _WEIGHT_START_BRUSH
            and brush.library is not None and getattr(brush, "blend", '') == 'ADD')


# 5.3 also starts new scenes with Weight Paint's Multi-Paint (and Auto-Normalize) on; 5.0 - 5.2 with both off.
MULTIPAINT_STARTS_ON = bool(bpy.types.ToolSettings.bl_rna.properties["use_multipaint"].default)


# --- Paint panels the kit draws inside its own panels --------------------------------------------------------------
def weight_falloff_panel():
    """Blender's paint panel class that draws a weight brush's falloff curve and falloff shape: 5.3's Shape panel
    (its Falloff panel no longer has the shape and is not shown for weight paint), else the Falloff panel."""
    from bl_ui import properties_paint_common as paint_common
    shape = getattr(paint_common, "ShapePanel", None)
    supports = getattr(paint_common, "supports_shape_panel", None)
    if shape is not None and (supports is None or supports('PAINT_WEIGHT')):
        return shape
    return paint_common.FalloffPanel


# --- Timeline keying popover ------------------------------------------------------------------------------------
def keying_popover():
    """The Timeline popover with the keying set and new-keyframe settings: 5.3's "Keyframing" popover (those settings
    plus Auto Keying, as sub-panels sized by it), else the "Keyframing Settings" panel of 5.0 - 5.2."""
    return "TIME_PT_keyframing" if hasattr(bpy.types, "TIME_PT_keyframing") else "TIME_PT_keyframing_settings"


# --- Theme header text -----------------------------------------------------------------------------------------
def header_text_colours(space_theme):
    """(text, highlighted text) RGB of an editor's header in the user's theme (read only): ``header_text`` /
    ``header_text_hi`` up to 5.2; 5.3 dropped them and draws header text with the editor's ``text`` / ``text_hi``."""
    if hasattr(space_theme, "header_text"):
        return tuple(space_theme.header_text)[:3], tuple(space_theme.header_text_hi)[:3]
    return tuple(space_theme.text)[:3], tuple(space_theme.text_hi)[:3]


# Graph Editor value axis: Blender 5.3 draws length curves in the scene's length unit (Unit Scale included), so a
# curve of 0.05 BU reads 5 in a centimetre scene; earlier versions draw lengths as stored. Rotations are in degrees on
# both.
GRAPH_LENGTH_UNITS = VERSION >= (5, 3)
_LENGTH_SIZE = {"KILOMETERS": 1000.0, "METERS": 1.0, "CENTIMETERS": 0.01, "MILLIMETERS": 0.001,
                "MICROMETERS": 1e-6, "MILES": 1609.344, "FEET": 0.3048, "INCHES": 0.0254, "THOU": 0.0000254}


def graph_length_factor(unit_settings):
    """Graph Editor display value per stored value of a length curve (1.0 where lengths are drawn as stored): the
    scene's Unit Scale over its length unit; Adaptive = metres (metric) / feet (imperial); no unit system = 1."""
    if not GRAPH_LENGTH_UNITS or unit_settings is None or unit_settings.system == 'NONE':
        return 1.0
    unit = unit_settings.length_unit
    if unit == 'ADAPTIVE':
        size = 1.0 if unit_settings.system == 'METRIC' else 0.3048
    else:
        size = _LENGTH_SIZE.get(unit, 1.0)
    return (unit_settings.scale_length or 1.0) / size
