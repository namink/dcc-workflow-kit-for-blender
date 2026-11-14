# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's wireframe on selected objects over shading (lead light green, other selected white).

Maya draws every edge of a selected object in the selection colour over its shading;
Blender only outlines it.

The kit draws the edges itself (POST_VIEW):
- Blender's own ``Object.show_wire`` mixes a selected object's colour with the theme's dormant wire colour
  by up to ~19 % depending on how the edge faces the view (#37cf95 = 0.81 lead + 0.19 #000460),
  so it can't give Maya's flat colour; it is also ID data (saved, in undo steps) and shared with the
  smooth preview 2 cage wire (operators/display.py ``_WIRE_FLAG``).
- Here: evaluated mesh edges in a cached batch per object (numpy, ~28 ms for 100k polys, rebuilt only when
  the object's geometry changes), drawn with the object matrix and a small depth bias (no z-fighting).
  Nothing is written to the file.
- The colours are kit-fixed: the user's theme ``object_active`` / ``object_selected`` is Blender's
  orange, since the kit ships no theme.
  LEAD / OTHER = Maya's lead / other selected colours.
- #76: in wireframe shading Maya draws unselected objects in a dark blue dormant
  wire colour (DORMANT); Blender draws them in the
  theme's wire colour (#181818 here). The same pass draws them in DORMANT (the "Selection Wireframe"
  preference covers both).
- #91: a frame change (playback, scrubbing, ``frame_set``) evaluates the depsgraph without a
  ``depsgraph_update_post``, so a skinned / nCloth mesh kept the wire of the first evaluated frame. ``frame_change_post``
  drops the batches of objects whose evaluated shape can depend on time (``time_dependent``: modifiers, shape keys,
  animated data); static meshes keep their batch. When Blender evaluates the frame only once (no frame handler
  writes, one depsgraph drawn, no depsgraph update since the last frame) the frame's own update names the objects
  whose shape changed, and only their batches go.
- A selected lattice is drawn too (Blender's own is the theme's orange). Maya draws a selected
  lattice in the same colours as meshes (white, the lead green). Edges = the lattice grid along U / V / W through the evaluated points
  (``co_deform``).
- Maya highlights the whole hierarchy under a selected object: every descendant shape is drawn in the
  colour of its nearest selected ancestor (Maya: group1
  (selected) -> pCube1 white, pCube2 (lead) -> pCube3 green). Without it a child in front of its selected parent hid
  the parent's wire (side view, pCube2 under pCube1 in front of it) — ``highlighted``.
- #330: Rendered shading draws the wire too. Maya highlights a selection in a lit, shadowed view as well,
  and the Maya layout keeps Blender's outline off, so a selection in Rendered shading (EEVEE, Cycles) had no
  highlight at all. The depth test works there: EEVEE writes the view's depth, and for an external engine
  Blender draws a depth pass of the objects while overlays are on. The one rule (``view_draws``) is Blender's
  own for its outline: overlays on. The IPR window's picture turns its overlays off, so it stays clean.
"""

import bpy
from bpy.app.handlers import persistent

TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}
WIRE_TYPES = TYPES | {'LATTICE'}   # selected wire only (the dormant wireframe colour stays mesh / curve types)
DEPTH_BIAS = 1e-4          # Legacy limit; retained for dormant, X-ray and native Make Live wires.
DEPTH_BIAS_PIXELS = 1.0    # At most one pixel of the bounds' projected depth change.
DEPTH_BIAS_MAX_SPAN = 1 / 16
DEPTH_BIAS_THIN_RATIO = 1 / 8
DEPTH_BIAS_THIN_SPAN = 1 / 4
LEAD = "#43ffa3"           # lead (last selected = Blender's active)
OTHER = "#ffffff"          # other selected objects
DORMANT = "#000460"        # unselected polymesh wire in wireframe shading
# the 3D View's per-type visibility (the Tool Box column hides every type, ui/toolbox.is_toolbox)
TYPE_FLAGS = {'MESH': "show_object_viewport_mesh", 'CURVE': "show_object_viewport_curve",
              'SURFACE': "show_object_viewport_surf", 'FONT': "show_object_viewport_font",
              'META': "show_object_viewport_meta"}

_batches = {}              # object session_uid -> (batch, edge count, evaluated bound box: 24 floats or None)
_corners = []              # [(bound boxes, their ``_corner_array``)] of the last redraw
_used = set()              # session_uids whose batch a redraw used since the last frame change
_draws = [0]               # redraws since the last frame change
_updated = [False]         # a depsgraph update came since the last frame change (``_on_frame``)
_handle = []
_shader = []
_many = []                 # [instanced, merged wire shader] (``_shaders``), None for one that can't be made
_ubos = []                 # uniform buffers of the instanced draw, one per INSTANCES objects of a redraw
_last_many = {}            # view region pointer -> what its last instanced redraw drew and computed (``_draw_many``)
_times = []


def _enabled():
    from .. import preferences
    try:
        return preferences.get().maya_selection_wire
    except (KeyError, AttributeError):
        return False


# The position code of every wire shader, the same text in each. ``precise`` keeps its operations in this order, each
# rounded on its own (no fused multiply-add), and GLSL rounds +, - and * correctly, so the one-object shader and the
# many-object ones below give the same position from the same values on any GPU. A backend that can't compile it gets
# the plain code in all of them.
_POSITION = ["precise vec4 p = mvp * vec4(pos, 1.0); p.z -= bias * p.w; gl_Position = p;"]
_PLAIN = "gl_Position = mvp * vec4(pos, 1.0); gl_Position.z -= bias * gl_Position.w;"


def _sh():
    if not _shader:
        import gpu

        def make(position):
            info = gpu.types.GPUShaderCreateInfo()
            info.push_constant('MAT4', 'mvp')
            info.push_constant('VEC4', 'color')
            info.push_constant('FLOAT', 'bias')
            info.vertex_in(0, 'VEC3', 'pos')
            info.fragment_out(0, 'VEC4', 'fragColor')
            info.vertex_source("void main() { " + position + " }")
            info.fragment_source("void main() { fragColor = color; }")
            return gpu.shader.create_from_info(info)
        try:
            _shader.append(make(_POSITION[0]))
        except Exception:      # noqa: BLE001
            _POSITION[0] = _PLAIN
            _shader.append(make(_PLAIN))
    return _shader[0]


INSTANCE_FROM = 64     # from this many highlighted objects, the objects sharing a batch are drawn in one call
INSTANCES = 240        # objects per uniform buffer: 240 matrices + 60 vec4 of offsets = 16,320 bytes (within 16 KB)


def _shaders():
    """(instanced, merged) wire shaders drawing many objects in one call. Each object's matrix and depth offset come
    from a uniform buffer, at the slot of its instance (instanced: the objects sharing a batch) or of its points (merged:
    the points of several objects in one batch, each tagged with its object's slot), and its position is computed with
    the same operations as ``_sh`` (``mvp * vec4(pos, 1.0)``, then ``z -= bias * w``) on the same single-precision
    values. (None, None) when the GPU backend can't make them (each object is drawn by itself), merged None when only
    that one can't be made."""
    if not _many:
        import gpu
        _sh()                  # settles ``_POSITION`` first: all wire shaders compute the position the same way

        def make(index, inputs):
            info = gpu.types.GPUShaderCreateInfo()
            info.typedef_source(f"struct WireInstances {{ mat4 mvp[{INSTANCES}]; vec4 bias[{INSTANCES // 4}]; }};")
            info.uniform_buf(0, "WireInstances", "inst")
            info.push_constant('VEC4', 'color')
            for slot, (kind, name) in enumerate(inputs):
                info.vertex_in(slot, kind, name)
            info.fragment_out(0, 'VEC4', 'fragColor')
            info.vertex_source(f"void main() {{ int i = {index}; mat4 mvp = inst.mvp[i];"
                               " float bias = inst.bias[i / 4][i % 4]; " + _POSITION[0] + " }")
            info.fragment_source("void main() { fragColor = color; }")
            return gpu.shader.create_from_info(info)
        made = []
        for index, inputs in (("gpu_InstanceIndex", (('VEC3', 'pos'),)), ("slot", (('VEC3', 'pos'), ('INT', 'slot')))):
            try:
                made.append(make(index, inputs))
            except Exception:      # noqa: BLE001  (an unsupported backend: draw each object by itself)
                import traceback
                traceback.print_exc()
                made.append(None)
        _many[:] = [made[0], made[1] if made[0] is not None else None]
    return _many[0], _many[1]


def _sh_many():
    return _shaders()[0]


def _ubo(k):
    """The ``k``-th uniform buffer of the instanced draw (made once, filled again each redraw)."""
    while len(_ubos) <= k:
        import gpu
        import numpy as np
        _ubos.append(gpu.types.GPUUniformBuf(np.zeros(INSTANCES * 17, np.float32)))
    return _ubos[k]


def projected_matrices(projection, worlds):
    """(n, 4, 4) float32 ``projection @ world`` (rows) for (n, 4, 4) world matrices: the same single-precision result
    as mathutils' ``Matrix @ Matrix``, which multiplies the floats, adds the products in double precision in the
    order of the inner index and rounds the sum to float. ``worlds`` hold float32 values (in any float type)."""
    import numpy as np
    proj = np.array(projection, np.float32)
    single = worlds.astype(np.float32)
    dot = np.zeros((len(single), 4, 4))
    for item in range(4):        # dot[n, row, col] += float(proj[row, item] * world[n, item, col]), item by item
        dot += (proj[None, :, item, None] * single[:, None, item, :]).astype(np.float64)
    return dot.astype(np.float32)


# Modifiers that only move a mesh's points: an object with no others keeps its edges from frame to frame
DEFORM_ONLY = frozenset({'ARMATURE', 'CAST', 'CURVE', 'DISPLACE', 'HOOK', 'LAPLACIANDEFORM', 'LATTICE', 'MESH_DEFORM',
                         'SHRINKWRAP', 'SIMPLE_DEFORM', 'SMOOTH', 'CORRECTIVE_SMOOTH', 'LAPLACIANSMOOTH',
                         'SURFACE_DEFORM', 'WARP', 'WAVE'})
_edges = {}     # object session_uid -> ((vertex count, edge count), edge indices) of a mesh that only deforms


def keeps_edges(ob):
    """A new frame only moves the evaluated mesh's points (shape keys, armature / lattice / ... modifiers): its edges
    stay the same, so playback reads only the points again (reading the edges took several ms a frame)."""
    return (ob.type == 'MESH' and not getattr(ob, "particle_systems", None)
            and all(m.type in DEFORM_ONLY for m in ob.modifiers))


def _positions(me):
    """(N * 3,) float32 point positions of mesh ``me`` (the position attribute: one copy, not a read per vertex)."""
    import numpy as np
    co = np.empty(len(me.vertices) * 3, np.float32)
    pos = me.attributes.get("position")
    if pos is not None and pos.domain == 'POINT' and pos.data_type == 'FLOAT_VECTOR' and len(pos.data) * 3 == len(co):
        pos.data.foreach_get("vector", co)
    else:
        me.vertices.foreach_get("co", co)
    return co


def _edge_indices(me, count):
    """(count * 2,) C int edge vertex indices of mesh ``me``: its edge attribute in one copy (``edges.foreach_get``
    reads edge by edge, ~3 ms for 25k edges; the attribute into a C ``int`` buffer, ~0.01 ms)."""
    import numpy as np
    ed = np.empty(count * 2, np.intc)
    att = me.attributes.get(".edge_verts")
    if att is not None and att.domain == 'EDGE' and att.data_type == 'INT32_2D' and len(att.data) == count:
        att.data.foreach_get("value", ed)
    else:
        me.edges.foreach_get("vertices", ed)
    return ed


def edges_of(ob, depsgraph):
    """(vertex positions (N, 3) float32, edge indices (E, 2) 32-bit int) of the evaluated object, object space."""
    ev = ob.evaluated_get(depsgraph)
    if ob.type == 'LATTICE':
        return lattice_edges(ev.data)
    if ob.type == 'MESH':
        me, temp = ev.data, False
    else:
        me, temp = ev.to_mesh(), True
    try:
        co = _positions(me)
        size = (len(me.vertices), len(me.edges))
        got = _edges.get(ob.session_uid) if not temp else None
        if got is not None and got[0] == size:
            ed = got[1]
        else:
            ed = _edge_indices(me, size[1]).reshape(-1, 2)
            if not temp and keeps_edges(ob):
                _edges[ob.session_uid] = (size, ed)
            else:
                _edges.pop(ob.session_uid, None)
    finally:
        if temp:
            ev.to_mesh_clear()
    return co.reshape(-1, 3), ed


def lattice_edges(lat):
    """(points (N, 3), edges (E, 2)) of a lattice grid: neighbours along U, V and W, index u + v·U + w·U·V."""
    import numpy as np
    nu, nv, nw = lat.points_u, lat.points_v, lat.points_w
    co = np.empty(len(lat.points) * 3, np.float32)
    lat.points.foreach_get("co_deform", co)
    idx = np.arange(nu * nv * nw, dtype=np.int32).reshape(nw, nv, nu)
    pairs = [np.stack((idx[:, :, :-1].ravel(), idx[:, :, 1:].ravel()), 1),
             np.stack((idx[:, :-1, :].ravel(), idx[:, 1:, :].ravel()), 1),
             np.stack((idx[:-1, :, :].ravel(), idx[1:, :, :].ravel()), 1)]
    return co.reshape(-1, 3), np.concatenate(pairs).astype(np.int32).reshape(-1, 2)


def _bounds(ob, depsgraph):
    """The evaluated bound box as 24 floats (8 corners), or None when it can't be read."""
    try:
        box = tuple(v for corner in ob.evaluated_get(depsgraph).bound_box for v in corner)
    except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError, ReferenceError):
        return None
    return box if len(box) == 24 else None


MERGE_POINTS = 2048       # a wire of at most this many points keeps its points and edges for ``_merged``


def _entry(ob, depsgraph, key=None, shared=None):
    """(batch or None, edge count, bound box, (points, edges) or None) of ``ob``'s wire (``key``: its session_uid when
    known). The bound box is read with the batch: both come from the same evaluated geometry and go together when it
    changes. A small wire also keeps the points and edges its batch was made from (several objects with meshes of
    their own are drawn in one call from them, ``_merged``).

    ``shared``: a dict kept for one redraw. Meshes whose evaluated mesh is the same one (objects sharing a mesh with
    no modifiers) read the same points and edges, so the batch made for the first of them is used for the others
    (thousands of copies of one mesh made one batch each, and could not be drawn together). Each object still reads
    its own bound box."""
    if key is None:
        key = ob.session_uid
    _used.add(key)
    entry = _batches.get(key)
    if entry is None:
        mesh = None
        if shared is not None and ob.type == 'MESH':
            data = ob.evaluated_get(depsgraph).data
            mesh = data.as_pointer() if data is not None else None
            made = shared.get(mesh) if mesh is not None else None
            if made is not None:
                entry = _batches[key] = (made[0], made[1], _bounds(ob, depsgraph), made[3])
                return entry
        from gpu_extras.batch import batch_for_shader
        co, ed = edges_of(ob, depsgraph)
        batch = batch_for_shader(_sh(), 'LINES', {"pos": co}, indices=ed) if len(ed) else None
        entry = _batches[key] = (batch, len(ed), _bounds(ob, depsgraph),
                                 (co, ed) if batch is not None and len(co) <= MERGE_POINTS else None)
        if mesh is not None:
            shared[mesh] = entry
    return entry


def _batch(ob, depsgraph):
    return _entry(ob, depsgraph)[0]


def _view(context):
    space = getattr(context, "space_data", None)
    return space if space is not None and space.type == 'VIEW_3D' else None


def _shown(ob, space):
    """Drawn in this view: the per-view type filter and local view count (``visible_get()`` alone
    ignores them, ``visible_get(viewport=space)`` doesn't)."""
    if isinstance(space, bpy.types.SpaceView3D):
        return ob.visible_get(viewport=space)
    return ob.visible_get()


# Maya Show > Selection Highlighting is per panel (Issue #173). The kit's highlight is this wire; Maya
# Workflow Kit views keep Blender's outline off, so ``show_outline_selected`` can't be the row's state.
# Views with highlighting off = a JSON {area index: Blender outline was on} on their screen (Blender
# spaces / areas take no ID properties; an area index survives save / open).
HILITE_OFF = "allset_hilite_off"


def _off_map(screen):
    import json
    try:
        return json.loads(screen.get(HILITE_OFF) or "{}") if screen is not None else {}
    except (TypeError, ValueError):
        return {}


def _area_index(context, space):
    screen = getattr(context, "screen", None)
    if screen is None or space is None:
        return None
    for i, area in enumerate(screen.areas):
        if area.spaces.active == space:
            return str(i)
    return None


def highlighting(context):
    """Maya Show > Selection Highlighting of this view (the panel menu row ``SELECTION_HILITE``): off = no kit
    selection wire and no Blender outline."""
    space = _view(context)
    if space is None:
        return True
    key = _area_index(context, space)
    return key is None or key not in _off_map(context.screen)


def set_highlighting(context, on):
    """Turn this view's Selection Highlighting on / off; Blender's outline goes with it and comes back as it was."""
    import json
    space = _view(context)
    key = _area_index(context, space)
    if key is None:
        return
    screen = context.screen
    off = _off_map(screen)
    if on and key in off:
        if off.pop(key):
            space.overlay.show_outline_selected = True
    elif not on and key not in off:
        off[key] = bool(space.overlay.show_outline_selected)
        space.overlay.show_outline_selected = False
    if off:
        screen[HILITE_OFF] = json.dumps(off)
    elif HILITE_OFF in screen:
        del screen[HILITE_OFF]


def wire_objects(context):
    """Selected objects that get the wire: object mode, drawable types, visible."""
    space = _view(context)
    return [ob for ob in context.selected_objects
            if ob.type in WIRE_TYPES and ob.mode == 'OBJECT' and _shown(ob, space)]


def children_map():
    r"""{object: [its children]} for every object of the file, each list in ``bpy.data.objects`` order like
    ``Object.children``. ``Object.children`` looks through every object of the file on each call
    ($S\modules\_bpy_types.py:249), so asking it for each object of a big selection grew with selection x scene."""
    kids = {}
    for ob in bpy.data.objects:
        parent = ob.parent
        if parent is not None:
            kids.setdefault(parent, []).append(ob)
    return kids


def highlighted(context, roots_shown=False):
    """[(object, is_lead)]: the selected objects that get the wire plus their descendants (Maya's hierarchy
    highlight), each in the colour of its nearest selected ancestor (itself when selected).

    ``roots_shown``: ``context`` is the 3D View's own (its draw), where ``context.selected_objects`` already holds only
    the objects shown in that view (Blender lists a selected object there only when it is visible in the context's
    3D View, the same test as ``visible_get(viewport=...)``), so the selected objects skip that test."""
    objs, leads, _uids = _highlight(context, roots_shown)
    return list(zip(objs, leads))


_ENUMS = {}


def _enum_values(prop, names):
    """The integer values ``foreach_get`` reads for the identifiers ``names`` of Object enum property ``prop``."""
    key = (prop, names)
    got = _ENUMS.get(key)
    if got is None:
        items = bpy.types.Object.bl_rna.properties[prop].enum_items
        got = _ENUMS[key] = [items[name].value for name in names if name in items]
    return got


_file_index = []           # [(the file's session_uids, their sorting order, the sorted uids)] of the last look-up
_rows_of = []              # [(uids list ``_highlight`` returned, their rows in the file, found)] of the last redraw


def _file_rows(uids):
    """(rows, found) of the objects with session_uids ``uids`` (an int64 array) in ``bpy.data.objects``: one read of
    the file's session_uids into a C ``int`` buffer, each object found by binary search (the sorting is kept while
    the file's objects stay the same)."""
    import numpy as np
    coll = bpy.data.objects
    total = len(coll)
    if not total:
        return np.zeros(len(uids), np.intp), np.zeros(len(uids), bool)
    file_uids = np.empty(total, np.intc)
    coll.foreach_get("session_uid", file_uids)
    last = _file_index[0] if _file_index else None
    if last is not None and np.array_equal(last[0], file_uids):
        order, ordered = last[1], last[2]
    else:
        order = np.argsort(file_uids, kind='stable')
        ordered = file_uids[order]
        _file_index[:] = [(file_uids, order, ordered)]
    rows = order[np.minimum(np.searchsorted(ordered, uids), total - 1)]
    return rows, file_uids[rows] == uids


def _root_flags(roots, uids):
    """(in Object Mode, a wire type) of each selected object, from two reads of the whole file's ``mode`` and
    ``type`` (asking each of thousands of selected objects for them took milliseconds a redraw); objects not found
    in the file are asked one by one."""
    import numpy as np
    rows, found = _file_rows(uids)
    total = len(bpy.data.objects)
    modes = np.empty(total, np.intc)
    types = np.empty(total, np.intc)
    bpy.data.objects.foreach_get("mode", modes)
    bpy.data.objects.foreach_get("type", types)
    in_object = modes[rows] == _enum_values("mode", ("OBJECT",))[0]
    wire_type = np.isin(types[rows], _enum_values("type", tuple(sorted(WIRE_TYPES))))
    for k in np.flatnonzero(~found).tolist():
        in_object[k] = roots[k].mode == 'OBJECT'
        wire_type[k] = roots[k].type in WIRE_TYPES
    return in_object, wire_type, rows, found


ROOT_ARRAYS_FROM = 64      # from this many selected objects their mode / type come from whole-file reads


def _highlight(context, roots_shown=False):
    """``highlighted`` as three lists: objects, is_lead, session_uids. No tuple per object: thousands of selected
    objects made thousands of tuples a redraw, which set off Python's garbage collector every few redraws."""
    if not highlighting(context):
        return [], [], []
    selected = context.selected_objects
    if not selected:
        return [], [], []
    # #173: an armature in Pose / Edit mode is selected for its bones (Maya: a picked control), so its child meshes
    # aren't a selected hierarchy. With no selected object in Object Mode (a posed skeleton) nothing is highlighted:
    # the file's parents (one look through every object) aren't read for nothing on each redraw of a pose drag.
    many = len(selected) >= ROOT_ARRAYS_FROM
    if many:
        import numpy as np
        sel_uids = np.array([ob.session_uid for ob in selected], np.int64)
        in_object, wire_type, rows, found = _root_flags(selected, sel_uids)
        keep = np.flatnonzero(in_object)
        if not keep.size:
            return [], [], []
    else:
        roots = [ob for ob in selected if ob.mode == 'OBJECT']
        root_uids = root_wire = None
        if not roots:
            return [], [], []
    space = _view(context)
    view = space if isinstance(space, bpy.types.SpaceView3D) else None     # ``_shown``
    active = context.view_layer.objects.active
    from ..operators import live
    live_objects = set(live.objects(context.scene))
    kids = children_map()
    if many:
        if roots_shown and not live_objects:
            # no selected object with children: the wire objects are the selected ones of a wire type, in their order
            parents = np.array([parent.session_uid for parent in kids], np.int64)
            if not np.isin(sel_uids[keep], parents).any():
                take = keep[wire_type[keep]]
                uids = sel_uids[take]
                leads = (uids == active.session_uid).tolist() if active is not None else [False] * len(take)
                listed = uids.tolist()
                _rows_of[:] = [(listed, rows[take], found[take])]       # their rows in the file, for this redraw
                return [selected[k] for k in take.tolist()], leads, listed
        roots = [selected[k] for k in keep.tolist()]
        root_uids = sel_uids[keep].tolist()
        root_wire = wire_type[keep].tolist()
    objs, leads, uids = [], [], []
    seen = set()

    def visit(ob, lead):        # a descendant that isn't selected
        if ob in seen:
            return
        seen.add(ob)
        if (ob.type in WIRE_TYPES and ob.mode == 'OBJECT'
                and (ob.visible_get(viewport=view) if view is not None else ob.visible_get())
                and ob not in live_objects):
            objs.append(ob)
            leads.append(lead)
            uids.append(ob.session_uid)
        for child in kids.get(ob, ()):
            if not child.select_get():          # a selected child keeps its own colour (visited as a root)
                visit(child, lead)

    # Each selected object is listed once and is never a descendant visited above (those aren't selected), so the
    # roots need no "seen" check of their own.
    for k, ob in enumerate(roots):
        lead = ob == active
        if ((ob.type in WIRE_TYPES if root_wire is None else root_wire[k])
                and (roots_shown or (ob.visible_get(viewport=view) if view is not None else ob.visible_get()))
                and (not live_objects or ob not in live_objects)):
            objs.append(ob)
            leads.append(lead)
            uids.append(ob.session_uid if root_uids is None else root_uids[k])
        children = kids.get(ob)
        if children:
            for child in children:
                if not child.select_get():
                    visit(child, lead)
    return objs, leads, uids


def dormant_objects(context):
    """Unselected objects that get Maya's dormant wire: wireframe shading, object mode, drawable types shown in this
    view (local view, per-type visibility)."""
    space = context.space_data
    if space is None or space.type != 'VIEW_3D' or space.shading.type != 'WIREFRAME':
        return []
    out = []
    from ..operators import live
    scene = getattr(context, "scene", None)
    live_objects = set(live.objects(scene)) if scene is not None else set()
    for ob in context.visible_objects:
        if ob.type not in TYPES or ob.mode != 'OBJECT' or ob.select_get() or (live_objects and ob in live_objects):
            continue
        if not getattr(space, TYPE_FLAGS[ob.type], True):
            continue
        if space.local_view is not None and not ob.local_view_get(space):
            continue
        out.append(ob)
    return out


def srgb(hex_str):
    """'#rrggbb' -> sRGB floats (r, g, b)."""
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _linear(c):
    from mathutils import Color
    lin = Color(tuple(c)[:3]).from_srgb_to_scene_linear()
    return (lin.r, lin.g, lin.b, 1.0)


def wire_colors():
    """(lead, other) RGBA in scene linear: kit-fixed Maya colours, whatever the user's theme is."""
    return _linear(srgb(LEAD)), _linear(srgb(OTHER))


def dormant_color():
    """Maya's dormant wire RGBA in scene linear."""
    return _linear(srgb(DORMANT))


def frame_ms():
    return sum(_times) / len(_times) * 1000.0 if _times else 0.0


def live_wire_objects(context):
    from ..operators import live
    space = context.space_data
    if space.shading.type != 'WIREFRAME' and not space.overlay.show_wireframes:
        return []
    return [o for o in live.objects(context.scene) if _shown(o, space)]


def depth_bias(ob, depsgraph, projection, viewport):
    """Conservative NDC offset from evaluated bounds and this view's pixel scale.

    No positive floor is safe for an arbitrarily thin / distant object. An
    unusable projection or bounds therefore returns zero rather than falling
    back to the old fixed offset. Bounds are a heuristic, not an occlusion
    guarantee for closely spaced surfaces or unrelated foreground objects.
    """
    import math
    from mathutils import Vector
    try:
        width, height = viewport
        if not all(math.isfinite(v) and v > 0 for v in (width, height)):
            return 0.0
        bounds = tuple(tuple(c) for c in ob.evaluated_get(depsgraph).bound_box)
        if (len(bounds) != 8 or any(len(c) != 3 for c in bounds)
                or not all(math.isfinite(v) for c in bounds for v in c)):
            return 0.0
        matrix = projection @ ob.matrix_world
        xs, ys, depths = [], [], []
        for corner in bounds:
            clip = matrix @ Vector((*corner, 1.0))
            if (not all(math.isfinite(v) for v in clip) or clip.w <= 1e-8
                    or clip.z <= -clip.w or clip.z >= clip.w):
                return 0.0  # Behind the eye, intersecting a clip plane, or unstable.
            xs.append(clip.x / clip.w)
            ys.append(clip.y / clip.w)
            depths.append(clip.z / clip.w)
        if not all(math.isfinite(v) for values in (xs, ys, depths) for v in values):
            return 0.0
        span = max(depths) - min(depths)
        pixels = max(1.0, (max(xs) - min(xs)) * width * 0.5,
                     (max(ys) - min(ys)) * height * 0.5)
        if not math.isfinite(span) or not math.isfinite(pixels) or span <= 0.0:
            return 0.0
        bias = min(DEPTH_BIAS, span * DEPTH_BIAS_MAX_SPAN, span * DEPTH_BIAS_PIXELS / pixels)

        # For a thin box viewed obliquely, its overall depth span includes the
        # long sides. Cap against the projected separation along each thin axis.
        sizes = [max(c[i] for c in bounds) - min(c[i] for c in bounds) for i in range(3)]
        world = ob.matrix_world
        lengths = [math.sqrt(sum((world[row][i] * sizes[i]) ** 2 for row in range(3))) for i in range(3)]
        if not all(math.isfinite(v) for v in lengths):
            return 0.0
        longest = max(lengths)
        for axis, length in enumerate(lengths):
            if length <= 0.0 or length >= longest * DEPTH_BIAS_THIN_RATIO:
                continue
            other_axes = tuple(i for i in range(3) if i != axis)
            separations = [abs(depths[i] - depths[j])
                           for i in range(8) for j in range(i + 1, 8)
                           if bounds[i][axis] != bounds[j][axis]
                           and all(bounds[i][k] == bounds[j][k] for k in other_axes)]
            if not separations:
                return 0.0
            bias = min(bias, min(separations) * DEPTH_BIAS_THIN_SPAN)
        return bias
    except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError):
        return 0.0


_PAIRS = [(i, j) for i in range(8) for j in range(i + 1, 8)]     # every two corners of a bound box
ARRAY_FROM = 8      # from this many objects on ``depth_biases`` computes in arrays (fewer: one by one is quicker)
_NO_BOX = [0.0] * 24
_NO_MATRIX = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


FILE_READ_FROM = 1 / 32    # ``world_matrices`` reads the whole file's matrices from this share of its objects on


def world_matrices(objects, uids=None):
    """(n, 4, 4) float64 world matrices (rows) of ``objects`` and an (n,) bool array: readable. Many objects: all of
    the file's matrices come in one ``foreach_get`` (in columns, like Blender's ``float[4][4]``), each row found by
    session_uid; flattening each object's Matrix in Python cost a few microseconds an object, tens of milliseconds for
    thousands of selected objects. A few objects of a big file: one by one. ``uids``: the objects' session_uids when
    known. Integer buffers are C ``int`` (``np.intc``): ``foreach_get`` copies into a buffer of another type code one
    item at a time."""
    import numpy as np
    n = len(objects)
    ok = np.ones(n, bool)
    worlds = np.zeros((n, 4, 4))
    missing = list(range(n))
    coll = bpy.data.objects
    total = len(coll)
    if n and total and n >= total * FILE_READ_FROM:
        try:
            want = np.array([ob.session_uid for ob in objects] if uids is None else uids, np.int64)
        except (AttributeError, ReferenceError):
            want = None
        if want is not None:
            flat = np.empty(total * 16, np.float32)
            coll.foreach_get("matrix_world", flat)
            known = _rows_of[0] if _rows_of and _rows_of[0][0] is uids else None
            rows, found = (known[1], known[2]) if known is not None else _file_rows(want)
            worlds = flat.reshape(total, 4, 4).transpose(0, 2, 1)[rows].astype(np.float64)
            missing = np.flatnonzero(~found).tolist()
    for k in missing:          # one by one, or not one of the file's objects
        try:
            mat = [v for row in objects[k].matrix_world for v in row]
        except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError, ReferenceError):
            mat = None
        if mat is None or len(mat) != 16:
            ok[k] = False
            mat = _NO_MATRIX
        worlds[k] = np.array(mat, np.float64).reshape(4, 4)
    return worlds, ok


_WORD_ONES = 0x0101010101010101     # eight numpy booleans read as one 64-bit word, all True


def _all_rows(flags):
    """``flags.all(axis=1)`` of an (n, 8 k) bool array, eight booleans read as one 64-bit word (numpy reduces a short
    axis row by row, a fraction of a millisecond a call for thousands of rows)."""
    import numpy as np
    words = np.ascontiguousarray(flags).reshape(len(flags), -1).view(np.uint64)
    out = words[:, 0] == np.uint64(_WORD_ONES)
    for j in range(1, words.shape[1]):
        out &= words[:, j] == np.uint64(_WORD_ONES)
    return out


def _fold_rows(fn, values):
    """``values.max(axis=1)`` / ``values.min(axis=1)`` (``fn``: ``np.maximum`` / ``np.minimum``) of an (n, m) array,
    one column at a time. The same value, NaN included; only the sign of a zero result can differ from numpy's
    reduction, and the depth offset never depends on it (a zero span or size gives the same result either way)."""
    out = values[:, 0].copy()
    for j in range(1, values.shape[1]):
        fn(out, values[:, j], out=out)
    return out


def _corner_array(boxes):
    """(corners, unread, homogeneous corners, finite, sizes) of ``boxes`` (24 floats each, None = unreadable): (n, 8, 3)
    float64 corners, the indices of the unreadable boxes, the corners with a fourth coordinate 1, which boxes are
    finite, and each box's size along x, y and z. The same box tuples as last time (the same objects with unchanged
    geometry, e.g. every redraw of an orbit) give the arrays made last time."""
    import operator
    from itertools import chain
    import numpy as np
    last = _corners[0] if _corners else None
    if last is not None and len(last[0]) == len(boxes) and all(map(operator.is_, last[0], boxes)):
        return last[1]
    n = len(boxes)
    corners = np.fromiter(chain.from_iterable(_NO_BOX if box is None else box for box in boxes),
                          np.float64, n * 24).reshape(n, 8, 3)
    unread = [k for k, box in enumerate(boxes) if box is None]
    with np.errstate(all='ignore'):
        sizes = np.stack([_fold_rows(np.maximum, corners[:, :, i]) - _fold_rows(np.minimum, corners[:, :, i])
                          for i in range(3)], axis=1)
    got = (corners, unread, np.concatenate((corners, np.ones((n, 8, 1))), axis=2),
           _all_rows(np.isfinite(corners).reshape(n, 24)), sizes)
    _corners[:] = [(list(boxes), got)]
    return got


def depth_biases(objects, depsgraph, projection, viewport, boxes=None, uids=None, worlds=None):
    """``depth_bias`` of each of ``objects`` (a list of floats): the same rule, computed for many objects at once in
    arrays (hundreds of selected objects took tens of milliseconds a redraw one by one). ``boxes``: each object's
    evaluated bound box as 24 floats (None: unreadable) when the caller has them already (``_entry``); ``uids``: the
    objects' session_uids when known; ``worlds``: their ``world_matrices`` when read already."""
    n = len(objects)
    if n < ARRAY_FROM:
        return [depth_bias(ob, depsgraph, projection, viewport) for ob in objects]
    return _biases_array(objects, depsgraph, projection, viewport, boxes, uids, worlds).tolist()


def _biases_array(objects, depsgraph, projection, viewport, boxes=None, uids=None, worlds=None):
    """``depth_biases`` of many objects as a float64 array."""
    import math
    import numpy as np
    n = len(objects)
    width, height = viewport
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        return np.zeros(n)
    worlds, ok = world_matrices(objects, uids) if worlds is None else (worlds[0], worlds[1].copy())
    corners, unread, homogeneous, finite, sizes = _corner_array(
        [_bounds(ob, depsgraph) for ob in objects] if boxes is None else boxes)
    ok[unread] = False
    return _biases_rows(worlds, ok, corners, homogeneous, finite, sizes, projection, width, height)


def _biases_rows(worlds, ok, corners, homogeneous, finite, sizes, projection, width, height):
    """The depth offsets of the rows given (``ok``: readable so far, changed in place). Every operation works row by
    row, so the offsets of some rows alone are the ones the whole set gives them."""
    import numpy as np
    n = len(worlds)
    with np.errstate(all='ignore'):
        ok &= finite & _all_rows(np.isfinite(worlds).reshape(n, 16))
        clip = np.einsum('nij,nkj->nki', np.array(projection, np.float64) @ worlds, homogeneous)
        w, z = clip[..., 3], clip[..., 2]
        # behind the eye, intersecting a clip plane, or unstable
        ok &= (_all_rows(np.isfinite(clip).reshape(n, 32)) & _all_rows(w > 1e-8) & _all_rows(z > -w)
               & _all_rows(z < w))
        xs, ys, depths = clip[..., 0] / w, clip[..., 1] / w, z / w
        ok &= _all_rows(np.isfinite(xs)) & _all_rows(np.isfinite(ys)) & _all_rows(np.isfinite(depths))
        span = _fold_rows(np.maximum, depths) - _fold_rows(np.minimum, depths)
        pixels = np.maximum(np.maximum(1.0, (_fold_rows(np.maximum, xs) - _fold_rows(np.minimum, xs)) * width * 0.5),
                            (_fold_rows(np.maximum, ys) - _fold_rows(np.minimum, ys)) * height * 0.5)
        ok &= np.isfinite(span) & np.isfinite(pixels) & (span > 0.0)
        bias = np.minimum(np.minimum(DEPTH_BIAS, span * DEPTH_BIAS_MAX_SPAN), span * DEPTH_BIAS_PIXELS / pixels)
        # a thin box viewed obliquely: cap against the projected separation along each thin axis
        lengths = np.sqrt(((worlds[:, :3, :3] * sizes[:, None, :]) ** 2).sum(axis=1))
        finite_lengths = np.isfinite(lengths)
        ok &= finite_lengths[:, 0] & finite_lengths[:, 1] & finite_lengths[:, 2]
        longest = _fold_rows(np.maximum, lengths)
        a = np.array([p[0] for p in _PAIRS])
        b = np.array([p[1] for p in _PAIRS])
        for axis in range(3):
            thin = np.flatnonzero((lengths[:, axis] > 0.0) & (lengths[:, axis] < longest * DEPTH_BIAS_THIN_RATIO))
            if not thin.size:      # no thin box along this axis: nothing to cap
                continue
            others = [i for i in range(3) if i != axis]
            c, d = corners[thin], depths[thin]
            along = ((c[:, a, axis] != c[:, b, axis])
                     & (c[:, a, others[0]] == c[:, b, others[0]])
                     & (c[:, a, others[1]] == c[:, b, others[1]]))
            found = along.any(1)
            ok[thin] &= found
            least = np.where(along, np.abs(d[:, a] - d[:, b]), np.inf).min(1)
            bias[thin] = np.where(found, np.minimum(bias[thin], least * DEPTH_BIAS_THIN_SPAN), bias[thin])
    return np.where(ok, bias, 0.0)


def view_draws(space):
    """This 3D View gets the selection wire: overlays on, in every shading mode (Solid, Material Preview and
    Rendered alike, as Blender's own outline). A view with overlays off, like the IPR picture, draws nothing."""
    return bool(space.overlay.show_overlays)


def _draw_many(sh, objs, leads, uids, depsgraph, projection, viewport, xray, colors, view_key=None):
    """The selected wire of many objects: objects sharing a batch drawn in one instanced call, their matrices and depth
    offsets in uniform buffers (thousands of objects took thousands of draw calls, uniform uploads and matrix products
    a redraw). Each object gets the same single-precision matrix and offset as one by one (``projected_matrices``,
    ``depth_biases``), and the picture is the same: the wire writes no depth, so only the order of differently coloured
    wires matters, and the runs of one colour keep their order (inside a run every wire has the same colour)."""
    import math
    import operator
    import numpy as np
    n = len(objs)
    get = _batches.get
    entries = [get(uid) for uid in uids]
    _used.update(uids)
    if None in entries:
        shared = {}
        for k in [k for k, e in enumerate(entries) if e is None]:
            entries[k] = _entry(objs[k], depsgraph, uids[k], shared)
    last = _last_many.get(view_key)
    # the same objects with the same batches as this view's last instanced redraw (an orbit, a playback frame): the
    # same bound boxes and drawing order
    if (last is None or last["uids"] != uids or last["leads"] != leads
            or not all(map(operator.is_, last["entries"], entries))):
        boxes = None if xray else [e[2] if len(e) > 2 else _bounds(ob, depsgraph) for ob, e in zip(objs, entries)]
        # draw order: runs of one colour in their order, inside a run the objects of one batch together
        batch_ids = np.array([0 if e[0] is None else id(e[0]) for e in entries], np.int64)
        is_lead = np.array(leads, bool)
        runs = np.concatenate(([0], np.cumsum(is_lead[1:] != is_lead[:-1])))
        order = np.lexsort((batch_ids, runs))
        order = order[batch_ids[order] != 0]
        run_of, batch_of = runs[order], batch_ids[order]
        starts = np.flatnonzero(np.concatenate(([True], (run_of[1:] != run_of[:-1])
                                                | (batch_of[1:] != batch_of[:-1]))))
        last = {"uids": uids, "leads": leads, "entries": entries, "boxes": boxes, "order": order,
                "plan": _plan(entries, leads, order, run_of.tolist(), starts.tolist(),
                              np.append(starts[1:], len(order)).tolist())}
        if len(_last_many) >= 8:
            _last_many.clear()
        _last_many[view_key] = last
    elif not xray and last["boxes"] is None:
        last["boxes"] = [e[2] if len(e) > 2 else _bounds(ob, depsgraph) for ob, e in zip(objs, entries)]
    order = last["order"]
    m = len(order)
    if not m:
        return
    worlds, ok = world_matrices(objs, uids)
    proj = np.array(projection, np.float32)
    key = (bool(xray), tuple(viewport), proj.tobytes())
    rows = None
    if last.get("key") == key and last["ok"].tobytes() == ok.tobytes():
        # the same view: only the objects whose matrix moved (bit for bit) are computed again, each row as before
        rows = np.flatnonzero(~_all_rows((worlds.view(np.uint64) == last["worlds"].view(np.uint64)).reshape(n, 16)))
        matrices, biases = last["matrices"], last["biases"]
        if rows.size:
            matrices[rows] = projected_matrices(projection, worlds[rows])
            width, height = viewport
            if not xray and all(math.isfinite(v) and v > 0 for v in (width, height)):
                corners, unread, homogeneous, finite, sizes = _corner_array(last["boxes"])
                readable = ok.copy()
                readable[unread] = False
                biases[rows] = _biases_rows(worlds[rows], readable[rows], corners[rows], homogeneous[rows],
                                            finite[rows], sizes[rows], projection, width, height)
    else:
        matrices = projected_matrices(projection, worlds)
        biases = np.full(n, DEPTH_BIAS) if xray else _biases_array(objs, depsgraph, projection, viewport,
                                                                   last["boxes"], uids, (worlds, ok))
    last.update(key=key, ok=ok, worlds=worlds, matrices=matrices, biases=biases)
    for k in np.flatnonzero(~ok).tolist():     # unreadable here: as one by one (which raises the same way)
        matrices[k] = np.array(projection @ objs[k].matrix_world, np.float32)
    columns = matrices.transpose(0, 2, 1)[order].reshape(m, 16)       # the shader's mat4: columns
    offsets = biases[order].astype(np.float32)                         # as ``uniform_float``: double to float
    data = np.zeros(INSTANCES * 17, np.float32)
    filled, bound, color = -1, None, {}
    merged_sh = _shaders()[1]
    for _run, chunk, lead, batch, first, count in last["plan"]:
        shader = sh if first >= 0 else merged_sh
        want = colors[0] if lead else colors[1]
        if color.get(id(shader)) is not want:
            color[id(shader)] = want
            shader.uniform_float("color", want)
        if chunk != filled:
            lo, hi = chunk * INSTANCES, min(m, (chunk + 1) * INSTANCES)
            data[:] = 0.0
            data[:(hi - lo) * 16] = columns[lo:hi].ravel()
            data[INSTANCES * 16:INSTANCES * 16 + hi - lo] = offsets[lo:hi]
            _ubo(chunk).update(data)
            filled = chunk
        if bound != (chunk, id(shader)):
            shader.uniform_block("inst", _ubo(chunk))
            bound = (chunk, id(shader))
        if first >= 0:
            batch.draw_instanced(shader, instance_start=first, instance_count=count)
        else:
            batch.draw(shader)


def _plan(entries, leads, order, run_of, starts, ends):
    """The draw calls of ``_draw_many``: [(run, uniform buffer, is_lead, batch, first instance, instance count)], first
    instance -1 for a ``_merged`` batch. Objects sharing a batch are one instanced call per uniform buffer they fill;
    the objects of a colour run with small meshes of their own are one merged call per buffer. Runs stay in order."""
    pieces, singles = [], {}
    merge = _shaders()[1] is not None
    for start, end in zip(starts, ends):
        entry = entries[order[start]]
        lead = leads[order[start]]
        if merge and end - start == 1 and len(entry) > 3 and entry[3] is not None:
            chunk = start // INSTANCES
            singles.setdefault((run_of[start], chunk, lead), []).append((start - chunk * INSTANCES, entry))
            continue
        while start < end:
            chunk = start // INSTANCES
            stop = min(end, (chunk + 1) * INSTANCES)
            pieces.append((run_of[start], chunk, lead, entry[0], start - chunk * INSTANCES, stop - start))
            start = stop
    for (run, chunk, lead), members in singles.items():
        if len(members) == 1:
            pieces.append((run, chunk, lead, members[0][1][0], members[0][0], 1))
        else:
            pieces.append((run, chunk, lead, _merged(members), -1, 0))
    pieces.sort(key=lambda piece: (piece[0], piece[1]))
    return pieces


def _merged(members):
    """One batch of the wires of several objects [(slot in the uniform buffer, entry)]: their points and edges as each
    object's own batch has them, each point tagged with its object's slot (``_shaders`` merged shader)."""
    import numpy as np
    from gpu_extras.batch import batch_for_shader
    points, edges, slots, base = [], [], [], 0
    for slot, entry in members:
        co, ed = entry[3]
        points.append(co)
        edges.append(np.asarray(ed, np.int64) + base)
        slots.append(np.full(len(co), slot, np.intc))
        base += len(co)
    return batch_for_shader(_shaders()[1], 'LINES', {"pos": np.concatenate(points), "slot": np.concatenate(slots)},
                            indices=np.concatenate(edges).astype(np.intc))


def _draw():
    context = bpy.context
    _draws[0] += 1
    space, rv3d = context.space_data, context.region_data
    if rv3d is None or not view_draws(space):
        return
    if (not context.selected_objects and space.shading.type != 'WIREFRAME'
            and not space.overlay.show_wireframes):
        return              # no selected wire, no dormant wire, no Make Live wire
    from ..operators import live
    live_obs = live_wire_objects(context)
    objs, leads, uids = _highlight(context, roots_shown=True) if _enabled() else ([], [], [])
    dormant = dormant_objects(context) if _enabled() else []
    if not objs and not dormant and not live_obs:
        return
    import time
    import gpu
    t0 = time.perf_counter()
    # the colours are sRGB, this shader writes the 3D View's linear framebuffer as is (#43ffa3 drew as
    # #8bffd0 without the conversion; built-in shaders convert by themselves)
    lead, other = wire_colors()
    # view_layer.depsgraph: already evaluated for this redraw; evaluated_depsgraph_get() inside a draw
    # callback re-evaluates and broke a timer-set region flag (gui_step11 Ctrl+A sidebar)
    depsgraph = context.view_layer.depsgraph
    sh = _sh()
    # X-ray wireframe (Blender's default in wireframe shading) shows the hidden edges too, like Maya's wireframe
    xray = space.shading.type == 'WIREFRAME' and space.shading.show_xray_wireframe
    gpu.state.depth_test_set('NONE' if xray else 'LESS_EQUAL')
    try:
        gpu.state.depth_mask_set(False)
        sh.bind()
        sh.uniform_float("bias", DEPTH_BIAS)
        pm = rv3d.perspective_matrix
        if dormant:
            sh.uniform_float("color", dormant_color())
            for ob in dormant:
                batch = _batch(ob, depsgraph)
                if batch is not None:
                    sh.uniform_float("mvp", pm @ ob.matrix_world)
                    batch.draw(sh)
        region = context.region
        many = _sh_many() if len(objs) >= INSTANCE_FROM else None
        if many is not None:
            many.bind()
            _draw_many(many, objs, leads, uids, depsgraph, pm, (region.width, region.height), xray, (lead, other),
                       region.as_pointer())
            sh.bind()
        elif objs:
            entries = [_entry(ob, depsgraph, uid) for ob, uid in zip(objs, uids)]
            biases = [DEPTH_BIAS] * len(objs) if xray else depth_biases(
                objs, depsgraph, pm, (region.width, region.height),
                boxes=[e[2] if len(e) > 2 else _bounds(ob, depsgraph) for ob, e in zip(objs, entries)], uids=uids)
            uniform, color = sh.uniform_float, None
            for ob, is_lead, entry, bias in zip(objs, leads, entries, biases):
                batch = entry[0]
                if batch is None:
                    continue
                uniform("bias", bias)
                uniform("mvp", pm @ ob.matrix_world)
                if color is not (lead if is_lead else other):      # the same colour as the last object: still set
                    color = lead if is_lead else other
                    uniform("color", color)
                batch.draw(sh)
        sh.uniform_float("bias", DEPTH_BIAS)  # preserve 0.7 Make Live pass behavior
        sh.uniform_float('color', _linear(live.COLOR))
        for ob in live_obs:
            batch = _batch(ob, depsgraph)
            if batch is not None:
                sh.uniform_float('mvp', pm @ ob.matrix_world)
                batch.draw(sh)
    finally:
        gpu.state.depth_test_set('NONE')
    _times.append(time.perf_counter() - t0)
    if len(_times) > 120:
        del _times[0]


def _callback():
    try:
        _draw()
    except Exception:  # never let a draw error repeat every frame
        import traceback
        traceback.print_exc()
        _remove_handler()


def _remove_handler():
    while _handle:
        bpy.types.SpaceView3D.draw_handler_remove(_handle.pop(), 'WINDOW')


@persistent
def _on_depsgraph(_scene, depsgraph):
    """Drop the cached batch of objects whose geometry changed (edits, modifiers, shape keys). Their edges go too,
    unless only the points can have moved: a mesh that only deforms (``keeps_edges``) re-evaluated with no update of
    its own mesh data — its skeleton or lattice moved (a moved rig re-read every child mesh's edges each step)."""
    if not _batches and not _edges:
        return
    _updated[0] = True
    data_updated = None
    for update in depsgraph.updates:
        if update.is_updated_geometry and isinstance(update.id, bpy.types.Object):
            ob = update.id.original
            _batches.pop(ob.session_uid, None)
            if ob.session_uid not in _edges:
                continue
            if data_updated is None:
                data_updated = {u.id.original.as_pointer() for u in depsgraph.updates
                                if not isinstance(u.id, bpy.types.Object)}
            if ob.data is None or ob.data.as_pointer() in data_updated or not keeps_edges(ob):
                _edges.pop(ob.session_uid, None)


def time_dependent(ob, data_memo=None):
    """Can the evaluated geometry change with the frame? Modifiers (armature / cloth / lattice / nodes ...), shape
    keys, animated object data. Object transforms don't matter: the batch is drawn with the live matrix.
    ``data_memo``: a dict kept for one frame, so the object data shared by many objects is asked once.

    Particle systems aren't asked about on their own: they come with a ParticleSystem modifier (counted above), and a
    particle system leaves the mesh's points and edges as they are (the modifier only reads them,
    source/blender/modifiers/intern/MOD_particlesystem.cc ``deform_verts``)."""
    if ob.modifiers:
        return True
    data = ob.data
    if data is None:
        return False
    if data_memo is not None:
        got = data_memo.get(data)
        if got is None:
            got = data_memo[data] = (getattr(data, "shape_keys", None) is not None
                                     or data.animation_data is not None)
        return got
    if getattr(data, "shape_keys", None) is not None or data.animation_data is not None:
        return True
    return False


# The kit's frame change handlers that write nothing to the file during a frame change (they clear a cache or start a
# timer), as "<module under the package>:<function>".
_FRAME_READERS = frozenset((
    "operators.live:frame_changed", "operators.auto_key:_on_frame", "operators.playback_maya:_on_frame",
    "ui.time_slider:_drop_keys", "ui.maya_joints:_frame_post", "ui.ghosting:_on_frame", "ui.selection_wire:_on_frame"))
_PACKAGE = __name__.rsplit(".ui.", 1)[0]


def _idle_writer(key, scene, count):
    """Does the kit frame change handler ``key`` write nothing on this frame change? False when it may write. Each
    test is the handler's own early return; a handler that looks for its helpers again when the file's objects came or
    went (``count``: a one-item list for the object count, read once) counts as idle only while its last look is
    current and found none."""
    if key == "operators.point_keys:_on_frame":
        from ..operators import point_keys
        return not point_keys._editing_meshes()
    if key == "operators.playback_maya:_on_frame_stepped":
        from ..operators import playback_maya
        return not playback_maya.active(scene)
    if key == "operators.constrain_interp:_on_update":
        from ..operators import constrain_interp
        return not constrain_interp._state["armed"]
    if not count:
        count.append(len(bpy.data.objects))
    if key == "operators.ik_rp:_on_frame":
        from .outliner import objects_version
        from ..operators import ik_rp as rp
        return (isinstance(rp._found[1], list) and not rp._found[1] and rp._count[0] == count[0]
                and rp._found[0] == (objects_version(), count[0]))
    if key in ("operators.constrain_199:_on_frame", "operators.pins_205:_on_frame"):
        from ..operators import constrain_199, pins_205
        state = (constrain_199 if key.startswith("operators.constrain_199") else pins_205)._state
        names = state.get("names")
        return isinstance(names, set) and not names and state.get("count") == count[0]
    return False


def _frame_writers_idle(scene):
    """Can nothing in ``frame_change_post`` write during this frame change? Any handler that isn't the kit's own
    counts as one that may write."""
    count = []
    for fn in bpy.app.handlers.frame_change_post:
        f = getattr(fn, "__func__", fn)
        mod = getattr(f, "__module__", "") or ""
        if not mod.startswith(_PACKAGE + "."):
            return False
        key = mod[len(_PACKAGE) + 1:] + ":" + getattr(f, "__name__", "")
        if key not in _FRAME_READERS and not _idle_writer(key, scene, count):
            return False
    return True


def _windows():
    wm = bpy.context.window_manager
    return wm.windows if wm is not None else ()


def _only_depsgraph(scene, depsgraph):
    """Is ``depsgraph`` the one every window draws? A window on another view layer or scene has a depsgraph of its
    own, which evaluates the new frame later with no handler at all (it finds the time changed and evaluates again:
    source/blender/depsgraph/intern/eval/depsgraph_eval.cc ``DEG_evaluate_on_refresh``; no data was flagged, so
    ``scene_graph_update_tagged`` in source/blender/blenkernel/intern/scene.cc calls no ``depsgraph_update_post``).
    A render's depsgraph isn't drawn either."""
    if depsgraph.mode != 'VIEWPORT':
        return False
    layer = depsgraph.view_layer
    for win in _windows():
        if win.scene != scene or win.view_layer != layer:
            return False
    return True


@persistent
def _on_frame(scene, _depsgraph=None):
    """Drop the batches of time-dependent objects so the next redraw reads this frame's evaluated mesh (#91); a mesh
    that only deforms keeps its edges (``keeps_edges``).

    After a redraw, the batches no redraw used since the last frame change go first (they are made again, from the
    geometry of that time, when an object is drawn again): a selection that was let go doesn't keep thousands of
    objects to be asked about on every frame of playback."""
    if _draws[0]:
        for uid in [uid for uid in _batches if uid not in _used]:
            del _batches[uid]
            _edges.pop(uid, None)
        _used.clear()
        _draws[0] = 0
    updated = _updated[0]
    _updated[0] = False
    if not _batches:
        return
    if (not updated and _depsgraph is not None and _only_depsgraph(scene, _depsgraph)
            and _frame_writers_idle(scene)):
        # Nothing writes during this frame change, so Blender evaluates the frame once and its update lists every
        # object whose evaluated shape changed (each evaluated part of an ID adds its flag to the update:
        # source/blender/depsgraph/intern/eval/deg_eval_flush.cc ``flush_editors_id_update``). A handler that writes
        # makes Blender evaluate a second time without telling Python (source/blender/blenkernel/intern/scene.cc
        # ``BKE_scene_graph_update_for_newframe_ex``): then every time-dependent object is asked about, below. So is
        # every one after a depsgraph update since the last frame change: a ``depsgraph_update_post`` handler that
        # wrote had Blender evaluate again unseen too (``scene_graph_update_tagged``), and this frame change drops
        # what that may have left behind.
        for update in _depsgraph.updates:
            if update.is_updated_geometry and isinstance(update.id, bpy.types.Object):
                ob = update.id.original
                uid = ob.session_uid
                if uid in _batches:
                    del _batches[uid]
                    if not keeps_edges(ob):
                        _edges.pop(uid, None)
        return
    import numpy as np
    objects = scene.objects
    uids = np.empty(len(objects), np.intc)
    objects.foreach_get("session_uid", uids)          # one read, instead of asking each object of the scene
    kept = np.isin(uids, np.fromiter(_batches, np.int64, len(_batches))).tolist()
    memo = {}
    for ob, uid, has in zip(objects, uids.tolist(), kept):
        if has and time_dependent(ob, memo):
            del _batches[uid]
            if not keeps_edges(ob):
                _edges.pop(uid, None)


@persistent
def _on_reload(*_args):
    _batches.clear()
    _edges.clear()
    _updated[0] = False
    _corners.clear()
    _used.clear()
    _last_many.clear()
    _file_index.clear()
    _rows_of.clear()


_HANDLERS = (("depsgraph_update_post", _on_depsgraph), ("frame_change_post", _on_frame), ("undo_post", _on_reload), ("redo_post", _on_reload),
             ("load_post", _on_reload))


def register():
    for name, fn in _HANDLERS:
        getattr(bpy.app.handlers, name).append(fn)
    _handle.append(bpy.types.SpaceView3D.draw_handler_add(_callback, (), 'WINDOW', 'POST_VIEW'))


def unregister():
    _remove_handler()
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name)
        if fn in lst:
            lst.remove(fn)
    _batches.clear()
    _edges.clear()
    _corners.clear()
    _used.clear()
    _draws[0] = 0
    _updated[0] = False
    _last_many.clear()
    _file_index.clear()
    _rows_of.clear()
    _shader.clear()
    _many.clear()
    _ubos.clear()
    _times.clear()
