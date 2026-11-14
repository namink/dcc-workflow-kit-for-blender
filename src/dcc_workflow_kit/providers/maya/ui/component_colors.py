# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya-style component colours in mesh edit mode.

A mesh in component mode is drawn with these colours (at UI scale 1.0):
every visible edge 1 px hilite #64dcff; vertex mode: unselected vertices #c800c8 at the theme's Vertex Size
(factory 3 px), selected vertices #fdff88 one pixel larger; edge mode: selected edges #e3ac79; face mode:
selected faces a 1-in-4 pixel stipple #e3ac79, no fill.

Blender draws edit meshes with the user's theme (orange / black). The kit ships no theme,
so this POST_VIEW handler draws the Maya colours on top of Blender's own edit-mesh drawing (which stays under it).

Reading the edit mesh: with no modifier shown in edit mode the evaluated object's ``to_mesh()`` is the cage. Its
points, edges, face corners and hidden flags are copied as attribute arrays (a few ms for 100k vertices; a BMesh
Python loop over every element costs ~0.1 s per 20k vertices). Its selection is not used: a selection change
re-evaluates nothing, and the evaluated mesh keeps the selection it had when it was first copied after its last
geometry update. The selection is read from the BMesh instead, and only the flags the select mode draws (vertices,
edges or faces). With a modifier shown in edit mode the evaluated mesh is not the cage, so the cage is read from the
BMesh, only up to ``BMESH_LIMIT`` vertices (bigger meshes keep Blender's drawing).

Arrays and GPU batches are cached per object. A depsgraph update that names the object or its mesh with a geometry
change reads the mesh again; any other update (a click, a box select: selection only) reads only the selection flags
and keeps the points, edges, faces and the batch of every edge. After a click the selection history holds the
picked elements; when they are as many as the selected total, they are the selection and no element is walked. A timer checks the BMesh's element and selection
counts (constant time) for selection changes that came with no depsgraph update; in the UV component it compares the
UV selection itself (UV Editor clicks tag nothing in the 3D View).

Selected faces: Blender's own selected-face tint (theme ``face_select``, drawn when the view's overlay
``show_faces`` is on) sat under the kit stipple and turned the 1-in-4 stipple into a near-opaque orange (pixels between the stipple
dots #9d856b where the unselected face is #747577; Maya keeps the base grey there). In a
Maya layout 3D View, while the kit draws every edited mesh, the view's ``overlay.show_faces`` is switched off (view
data, not preferences; from a timer, never inside the draw) and switched back when the kit stops drawing there
(preference off, mesh over ``BMESH_LIMIT``) and on unregister. Views the kit didn't switch are left alone.

Edges: Maya draws a thin hilite wire with crisp orange selected edges.
Kit primitives keep Maya's hard edges as ``sharp_edge``, so
Blender drew its theme sharp-edge colour (factory #00ffff) about 3 px wide around the kit's line (at UI 1.25,
cross-section of a silhouette edge: 519a9a 00dfdf 008a8a with the kit's 64dbff only in the middle) and the selected
edge looked like an orange sliver inside a thick cyan band. ``overlay.show_edge_sharp`` is now switched off with
``show_faces`` (Maya has no sharp-edge colour); Blender's plain edit edge left under the kit line is 2 px (474747 333333),
so the hilite line is 1.5 px x UI scale (2 px at 1.25, nothing of Blender's left; 1 px left a dark pixel beside it).
The lines also failed the depth test on one side of a silhouette edge (bias 0.0005): ``DEPTH_BIAS`` 0.002 for the
hilite wire, ``EDGE_SEL_BIAS`` 0.003 for selected edges, drawn last and 2 px so they stay on top.

UV mode (the kit's F12 UV component, UV Sync Selection off): like Maya, the 3D View shows the UV selection, not the
mesh selection (the kit selects every face so the UV Editor shows all UVs). Every vertex is drawn as a point,
vertices with a selected UV in the selected-vertex colour; no selected edges or face stipple.

Vertices are drawn with Blender's point shader: the plain uniform-colour shader ignores the point size on Vulkan and
Metal (every vertex became a single dark pixel there and the theme's Vertex Size did nothing).
"""

from operator import attrgetter

import bpy
import numpy as np

HILITE = "#64dcff"          # the object being edited, every edge
VERT = "#c800c8"            # unselected vertices
VERT_SEL = "#fdff88"        # selected vertices
EDGE_SEL = "#e3ac79"        # selected edges
FACE_SEL = "#e3ac79"        # selected face stipple
VERT_PX = 3.0               # pixel sizes at UI scale 1.0 when the theme vertex size can't be read
VERT_SEL_PX = 4.0           # selected = theme vertex size + 1 (Blender's factory 3 gives Maya's 3 / 4)
LINE_PX = 1.5               # thin lines; 1.5 x UI scale just covers Blender's own 2 px edit edge
EDGE_SEL_PX = 2.0           # selected edges a little wider, drawn over the hilite wire
BMESH_LIMIT = 50000         # cage read from the BMesh (modifiers shown in edit mode) only up to this many vertices
DEPTH_BIAS = 0.002          # relative pull toward the camera: 0.0005 lost the line's far side on silhouettes
EDGE_SEL_BIAS = 0.003       # selected edges in front of the hilite wire
FACE_BIAS = 0.0005          # selected face stipple
POINT_BIAS = 0.003          # vertices: Blender's own edit vertices write depth well in front of the surface

_handle = []
OVERLAY_OFF = ("show_faces", "show_edge_sharp")   # Blender edit-mesh overlays under the Maya look
_faces_off = set()          # (space pointer, overlay prop) the kit switched off (restored on unregister)
_pending = {}               # (space pointer, overlay prop) -> value the timer writes
_shader = {}
_cache = {}                 # (object pointer, mesh pointer) -> _State
_dirty = set()              # object / mesh names a geometry update touched since the last read
_dirty_sel = set()          # object / mesh names any other update touched (only the selection can have changed)
_times = []
_selection_snapshot = {}       # edit-mesh selection signatures for changes with no depsgraph notification
_POLL_INTERVAL = 0.15
_SELECT = attrgetter("select")
# foreach_get copies an int attribute in one block only into a C int array; numpy's int32 is a C long on Windows
# and is filled element by element (~25 ms instead of ~0.1 ms for 200k edges).
_INT = np.intc


# --- pure helpers (tests/test_step134_selection.py) -----------------------------------------------

def srgb(hex_str):
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


class MeshArrays:
    """Edit cage arrays: co (n, 3) float32 object space, edges (e, 2) int32, per element select / hide bools,
    polygons as loop_start / loop_total into corner_vert."""
    __slots__ = ("co", "edges", "vsel", "vhide", "esel", "ehide", "fsel", "fhide", "loop_start", "loop_total",
                 "corner_vert")

    def __init__(self, co, edges, vsel=None, vhide=None, esel=None, ehide=None, fsel=None, fhide=None,
                 loop_start=None, loop_total=None, corner_vert=None):
        self.co = np.asarray(co, dtype=np.float32).reshape(-1, 3)
        self.edges = np.asarray(edges, dtype=np.int32).reshape(-1, 2)
        n, e = len(self.co), len(self.edges)
        f = 0 if loop_start is None else len(loop_start)

        def flags(a, k):
            return np.zeros(k, bool) if a is None else np.asarray(a, dtype=bool).reshape(-1)
        self.vsel, self.vhide = flags(vsel, n), flags(vhide, n)
        self.esel, self.ehide = flags(esel, e), flags(ehide, e)
        self.fsel, self.fhide = flags(fsel, f), flags(fhide, f)
        self.loop_start = np.zeros(0, np.int32) if loop_start is None else np.asarray(loop_start, np.int32)
        self.loop_total = np.zeros(0, np.int32) if loop_total is None else np.asarray(loop_total, np.int32)
        self.corner_vert = np.zeros(0, np.int32) if corner_vert is None else np.asarray(corner_vert, np.int32)


def point_sizes(theme_size):
    """(unselected, selected) vertex sizes at UI scale 1.0 for the theme's Vertex Size."""
    try:
        size = float(theme_size)
    except (TypeError, ValueError):
        return VERT_PX, VERT_SEL_PX
    if size <= 0:
        return VERT_PX, VERT_SEL_PX
    return size, size + 1.0


def theme_point_sizes(context):
    try:
        return point_sizes(context.preferences.themes[0].view_3d.vertex_size)
    except (AttributeError, IndexError):
        return VERT_PX, VERT_SEL_PX


def fan_triangles(loop_start, loop_total, corner_vert, mask):
    """Vertex index triangles (t, 3) of the polygons in ``mask``, fanned from each polygon's first corner."""
    start = np.asarray(loop_start, np.int64)[mask]
    total = np.asarray(loop_total, np.int64)[mask]
    ntri = np.maximum(total - 2, 0)
    if not len(ntri) or ntri.sum() == 0:
        return np.zeros((0, 3), np.int32)
    first = np.repeat(start, ntri)
    # i = 1 .. total-2 within each polygon
    offs = np.arange(ntri.sum()) - np.repeat(np.cumsum(ntri) - ntri, ntri) + 1
    cv = np.asarray(corner_vert, np.int64)
    return np.stack([cv[first], cv[first + offs], cv[first + offs + 1]], axis=1).astype(np.int32)


def layers(m, select_mode, uv=False, wire=True):
    """What to draw for the Maya component look: dict of index arrays into ``m.co``.

    edges: every visible edge (hilite; left out with ``wire`` False: it doesn't depend on the selection);
    verts / verts_sel (vertex mode); edges_sel (edge mode); tris (face mode, selected visible faces). Hidden elements
    are never drawn. ``uv``: UV mode — points only, ``m.vsel`` holds the vertices with a selected UV."""
    vert_mode, edge_mode, face_mode = (True, False, False) if uv else (bool(x) for x in select_mode)
    vis_e = ~m.ehide
    out = {"edges": m.edges[vis_e]} if wire else {}
    if vert_mode:
        vis = ~m.vhide
        out["verts"] = np.flatnonzero(vis & ~m.vsel).astype(np.int32)
        out["verts_sel"] = np.flatnonzero(vis & m.vsel).astype(np.int32)
    if edge_mode:
        out["edges_sel"] = m.edges[vis_e & m.esel]
    if face_mode:
        out["tris"] = fan_triangles(m.loop_start, m.loop_total, m.corner_vert, m.fsel & ~m.fhide)
    return out


def face_overlay_action(want_off, show_faces, ours):
    """What to do with a view's ``overlay.show_faces``: (value to write or None, kit owns the switch afterwards).

    ``want_off``: the kit draws the Maya face look in this view; ``ours``: the kit switched it off earlier. Only a
    switch the kit made is ever undone."""
    if want_off:
        return (False if show_faces else None), (ours or show_faces)
    if ours:
        return True, False
    return None, False


def use_evaluated(modifiers):
    """True when the evaluated edit mesh is the cage: no modifier is shown in edit mode."""
    return not any(md.show_viewport and md.show_in_editmode for md in modifiers)


def readable(n_verts, evaluated):
    """Whether the kit draws this mesh: the evaluated read is always fast, the BMesh read only up to BMESH_LIMIT."""
    return evaluated or n_verts <= BMESH_LIMIT


# --- reading the edit mesh -------------------------------------------------------------------------

def _attr(me, name, count):
    a = me.attributes.get(name)
    out = np.zeros(count, bool)
    if a is not None and count:
        a.data.foreach_get("value", out)
    return out


def _positions(me, n):
    co = np.empty(n * 3, np.float32)
    a = me.attributes.get("position")
    if a is not None and a.domain == 'POINT' and a.data_type == 'FLOAT_VECTOR':
        a.data.foreach_get("vector", co)
    else:
        me.vertices.foreach_get("co", co)
    return co


def _ints(me, name, count, fallback):
    """Int attribute ``name`` as a C int array (one block copy), else ``fallback(out)`` fills it."""
    out = np.empty(count, _INT)
    a = me.attributes.get(name)
    if count and a is not None and a.data_type in {'INT', 'INT32_2D'}:
        a.data.foreach_get("value", out)
    elif count:
        fallback(out)
    return out


def read_evaluated(ob, depsgraph, faces=True):
    """MeshArrays of the evaluated edit mesh (no edit-mode modifiers: this is the cage); polygons only with
    ``faces`` (face select mode). Its selection flags are as they were at the last geometry update: use the BMesh's."""
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    try:
        n, e = len(me.vertices), len(me.edges)
        f, l = (len(me.polygons), len(me.loops)) if faces else (0, 0)
        co = _positions(me, n)
        ed = _ints(me, ".edge_verts", e * 2, lambda out: me.edges.foreach_get("vertices", out))
        ls = np.empty(f, _INT)
        if f:
            me.polygons.foreach_get("loop_start", ls)
        lt = np.diff(np.append(ls, l)).astype(np.int32)           # face corners are stored face by face
        cv = _ints(me, ".corner_vert", l, lambda out: me.loops.foreach_get("vertex_index", out))
        return MeshArrays(co, ed, _attr(me, ".select_vert", n), _attr(me, ".hide_vert", n),
                          _attr(me, ".select_edge", e), _attr(me, ".hide_edge", e),
                          _attr(me, ".select_poly", f), _attr(me, ".hide_poly", f), ls, lt, cv)
    finally:
        ev.to_mesh_clear()


def read_bmesh(bm):
    """MeshArrays of the BMesh cage (Python loops: small meshes only)."""
    from itertools import chain
    bm.verts.index_update()
    n, e = len(bm.verts), len(bm.edges)
    co = np.fromiter(chain.from_iterable(v.co for v in bm.verts), np.float32, 3 * n)
    ed = np.fromiter(chain.from_iterable((x.verts[0].index, x.verts[1].index) for x in bm.edges), np.int32, 2 * e)
    lt = np.fromiter((len(f.verts) for f in bm.faces), np.int32, len(bm.faces))
    ls = (np.cumsum(lt) - lt).astype(np.int32)
    cv = np.fromiter(chain.from_iterable((v.index for v in f.verts) for f in bm.faces), np.int32, int(lt.sum()))
    hide = attrgetter("hide")
    return MeshArrays(co, ed, _flags(bm.verts), np.fromiter(map(hide, bm.verts), bool, n),
                      _flags(bm.edges), np.fromiter(map(hide, bm.edges), bool, e),
                      _flags(bm.faces), np.fromiter(map(hide, bm.faces), bool, len(bm.faces)), ls, lt, cv)


def _flags(seq):
    """Select flags of a BMesh element sequence (one Python pass, the cheapest the BMesh API allows)."""
    return np.fromiter(map(_SELECT, seq), bool, len(seq))


def _kind_flags(me, bm, kind):
    """Select flags of the vertices ('v'), edges ('e') or faces ('f') of an edit mesh.

    A click leaves the picked element in the selection history. When the history's selected elements of this type
    are as many as the mesh's selected total (kept by the BMesh), they are exactly the selection: no pass over every
    element. Otherwise (a box select, select more: nothing in the history) one pass."""
    import bmesh
    seq, total, cls = {"v": (bm.verts, me.total_vert_sel, bmesh.types.BMVert),
                       "e": (bm.edges, me.total_edge_sel, bmesh.types.BMEdge),
                       "f": (bm.faces, me.total_face_sel, bmesh.types.BMFace)}[kind]
    history = bm.select_history
    if total <= len(history):
        seq.index_update()
        picked = {ele.index for ele in history if isinstance(ele, cls) and ele.select}
        if len(picked) == total:
            out = np.zeros(len(seq), bool)
            out[list(picked)] = True
            return out
    return _flags(seq)


def selection_kinds(select_mode, uv=False):
    """The selection flags the Maya look draws: 'v' vertices, 'e' edges, 'f' faces; 'uv' the UV selection."""
    if uv:
        return {"uv"}
    return {k for k, on in zip("vef", select_mode) if on}


def counts_signature(me, bm):
    """Element and selection counts of an edit mesh, read in constant time (the BMesh keeps the selected totals)."""
    return (len(bm.verts), len(bm.edges), len(bm.faces), me.total_vert_sel, me.total_edge_sel, me.total_face_sel)


class _State:
    __slots__ = ("arrays", "faces", "batches", "bkey", "name", "me_name", "uv", "op", "sel", "wire", "counts")

    def __init__(self, ob):
        self.arrays = None
        self.uv = False
        self.faces = False          # arrays hold the polygons (read only in face select mode)
        self.batches = None         # batches that depend on the selection, for bkey
        self.bkey = None
        self.wire = None            # the batch of every visible edge (geometry only)
        self.name = ob.name
        self.me_name = ob.data.name
        self.op = 0                 # the transform running when the arrays were read in full (0: none)
        self.sel = set()            # selection_kinds whose flags in arrays are current
        self.counts = None          # (vertices, edges, faces) of the BMesh the arrays were read from


def _transform_ptr():
    """Pointer of the transform running in some window (move / rotate / scale, slide, a manipulator drag), else 0.
    Until it ends only point positions change: topology, selection and hidden elements stay as they were."""
    from . import maya_joints
    try:
        op = maya_joints.transform_op()
    except (AttributeError, ReferenceError, RuntimeError):
        return 0
    return op.as_pointer() if op is not None else 0


NAVIGATION = ("VIEW3D_OT_rotate", "VIEW3D_OT_move", "VIEW3D_OT_zoom", "VIEW3D_OT_dolly", "VIEW3D_OT_fly",
              "VIEW3D_OT_walk")


def _navigating():
    """A view tumble / track / dolly / fly runs in some window (it selects nothing until it ends)."""
    try:
        return any(op is not None and op.bl_idname in NAVIGATION for w in bpy.context.window_manager.windows
                   for op in w.modal_operators)
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def _coordinates(ob, depsgraph, bm, n):
    """The cage's point positions ((n, 3) float32) of an edit mesh whose topology is unchanged, or None when the
    count no longer matches. Read from the evaluated mesh when it is the cage (one array copy), else from the BMesh."""
    if use_evaluated(ob.modifiers):
        ev = ob.evaluated_get(depsgraph)
        me = ev.to_mesh()
        try:
            if len(me.vertices) != n:
                return None
            return _positions(me, n).reshape(-1, 3)
        finally:
            ev.to_mesh_clear()
    if len(bm.verts) != n:
        return None
    from itertools import chain
    return np.fromiter(chain.from_iterable(v.co for v in bm.verts), np.float32, 3 * n).reshape(-1, 3)


# --- drawing ---------------------------------------------------------------------------------------

def _enabled():
    from .. import preferences
    try:
        return preferences.get().maya_component_colors
    except (KeyError, AttributeError):
        return False


def _builtin(name):
    if name not in _shader:
        import gpu
        _shader[name] = gpu.shader.from_builtin(name)
    return _shader[name]


def _stipple():
    if "stipple" not in _shader:
        import gpu
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant('MAT4', 'ModelViewProjectionMatrix')
        info.push_constant('VEC4', 'color')
        info.vertex_in(0, 'VEC3', 'pos')
        info.fragment_out(0, 'VEC4', 'fragColor')
        info.vertex_source("void main() { gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0); }")
        # Maya's face stipple: one pixel in every 2 x 2 block
        info.fragment_source("void main() { ivec2 p = ivec2(gl_FragCoord.xy);"
                             " if (((p.x | p.y) & 1) != 0) { discard; } fragColor = color; }")
        _shader["stipple"] = gpu.shader.create_from_info(info)
    return _shader["stipple"]


def _linear(hex_str):
    from mathutils import Color
    c = Color(srgb(hex_str)).from_srgb_to_scene_linear()
    return (c.r, c.g, c.b, 1.0)


def _batches(st, select_mode):
    """Draw list in order: selected face stipple, every edge (hilite), selected edges, vertices, selected vertices.
    The every-edge batch is kept while only the selection changes."""
    from gpu_extras.batch import batch_for_shader
    m = st.arrays
    poly = _builtin('POLYLINE_UNIFORM_COLOR')

    def lines(out, idx, color, width, kind='LINES'):
        if len(idx):
            out.append((kind, poly, batch_for_shader(poly, 'LINES', {"pos": m.co[idx.reshape(-1)]}), color, width))
    if st.wire is None:
        st.wire = []
        lines(st.wire, m.edges[~m.ehide], srgb(HILITE) + (1.0,), LINE_PX)
    key = (st.uv,) + tuple(bool(x) for x in select_mode)
    if st.batches is None or st.bkey != key:
        lay = layers(m, select_mode, st.uv, wire=False)
        dots = _builtin('POINT_UNIFORM_COLOR')   # Vulkan / Metal size points only with a point shader
        front, back = [], []

        def points(idx, color, size):
            if len(idx):
                back.append(('POINTS', dots, batch_for_shader(dots, 'POINTS', {"pos": m.co[idx]}), color, size))
        if "tris" in lay and len(lay["tris"]):
            sh = _stipple()
            front.append(('TRIS', sh, batch_for_shader(sh, 'TRIS', {"pos": m.co}, indices=lay["tris"]),
                          _linear(FACE_SEL), 0.0))
        if "edges_sel" in lay:
            lines(back, lay["edges_sel"], srgb(EDGE_SEL) + (1.0,), EDGE_SEL_PX, 'LINES_SEL')
        if "verts" in lay:
            points(lay["verts"], srgb(VERT) + (1.0,), 0)          # size index into theme_point_sizes
            points(lay["verts_sel"], srgb(VERT_SEL) + (1.0,), 1)
        st.batches, st.bkey = (front, back), key
    front, back = st.batches
    return front + st.wire + back


def _biased_projection(rv3d, bias):
    import gpu
    from mathutils import Matrix
    p = Matrix(gpu.matrix.get_projection_matrix())
    if rv3d is not None and rv3d.is_perspective:
        p[2][3] -= bias * abs(p[2][3])
    else:
        p[2][3] -= bias * 0.1
    return p


def _xray(space):
    sh = space.shading
    return sh.show_xray_wireframe if sh.type == 'WIREFRAME' else sh.show_xray


def edit_objects(context):
    return [ob for ob in (context.objects_in_mode_unique_data or ()) if ob is not None and ob.type == 'MESH'
            and ob.visible_get()]


def uv_selected_verts(bm):
    """Per vertex: one of its UVs is selected, among the faces the UV Editor shows (selected, not hidden)."""
    from .. import compat
    out = np.zeros(len(bm.verts), bool)
    uv = bm.loops.layers.uv.active
    if uv is None:
        return out
    bm.verts.index_update()
    for f in bm.faces:
        if f.select and not f.hide:
            for lp in f.loops:
                if compat.uv_vert_selected(lp, uv):
                    out[lp.vert.index] = True
    return out


def _read(st, ob, depsgraph, bm, faces, uv):
    """Read the cage of ``ob`` in full into ``st`` (selection flags: see _select); False when the kit leaves this
    mesh to Blender's drawing."""
    n = len(bm.verts)
    evaluated = use_evaluated(ob.modifiers)
    if not readable(n, evaluated) or (uv and n > BMESH_LIMIT):
        return False
    arrays, current = None, set()
    if evaluated:
        arrays = read_evaluated(ob, depsgraph, faces)
        if (len(arrays.co) != n or len(arrays.edges) != len(bm.edges)
                or (faces and len(arrays.loop_start) != len(bm.faces))):
            arrays = None           # not this BMesh's evaluation (the depsgraph wasn't evaluated since a change)
    if arrays is None:
        if n > BMESH_LIMIT:
            return False
        arrays, faces, current = read_bmesh(bm), True, {"v", "e", "f"}
    st.arrays, st.faces, st.uv, st.sel = arrays, faces, uv, current
    st.batches = st.bkey = st.wire = None
    st.counts = (n, len(bm.edges), len(bm.faces))
    return True


def _select(st, me, bm, need):
    """Make the selection flags in ``need`` (selection_kinds) current: read from the BMesh, the evaluated mesh's
    selection stays as it was at its last geometry update."""
    missing = need - st.sel
    if not missing:
        return
    m = st.arrays
    if "uv" in missing:
        m.vsel = uv_selected_verts(bm)
        m.esel = np.zeros(len(m.esel), bool)
        m.fsel = np.zeros(len(m.fsel), bool)
        st.sel = {"uv"}
    else:
        if "v" in missing:
            m.vsel = _kind_flags(me, bm, "v")
        if "e" in missing:
            m.esel = _kind_flags(me, bm, "e")
        if "f" in missing and st.faces:
            m.fsel = _kind_flags(me, bm, "f")
        st.sel |= missing
    st.batches, st.bkey = None, None


def state(ob, depsgraph, faces=True, uv=False, select_mode=None):
    """Up-to-date cached arrays of ``ob`` (None when the kit leaves this mesh to Blender's drawing); ``faces``:
    the polygons are needed too (face select mode); ``uv``: UV mode (points show the UV selection);
    ``select_mode``: only the selection flags this select mode draws are made current (None: every flag).

    A geometry update reads the mesh again; any other update (selection only) reads only the selection flags and
    keeps the points, edges, faces and the batch of every edge."""
    import bmesh
    key = (ob.as_pointer(), ob.data.as_pointer())
    st = _cache.get(key)
    if st is None or st.name != ob.name or st.me_name != ob.data.name:
        st = _cache[key] = _State(ob)
    names = (ob.name, ob.data.name)
    need = selection_kinds((True, True, True) if select_mode is None else select_mode, uv)
    full = (st.arrays is None or names[0] in _dirty or names[1] in _dirty or (faces and not st.faces)
            or st.uv != uv)
    touched = names[0] in _dirty_sel or names[1] in _dirty_sel
    if not full and not touched and need <= st.sel:
        return st
    bm = bmesh.from_edit_mesh(ob.data)
    # During a transform only the points move: the arrays read in full once in this transform keep their edges,
    # faces, selection and hidden flags, and get the new positions.
    op = _transform_ptr()
    same_transform = op and st.op == op and st.arrays is not None and (st.faces or not faces) and st.uv == uv
    if full:
        co = _coordinates(ob, depsgraph, bm, len(st.arrays.co)) if same_transform else None
        if co is not None:
            st.arrays.co = co
            st.batches = st.bkey = st.wire = None
        else:
            if not _read(st, ob, depsgraph, bm, faces, uv):
                st.arrays = None
                return None
            st.op = op
    elif touched and not same_transform:
        if st.counts != (len(bm.verts), len(bm.edges), len(bm.faces)):
            # elements came or went with no geometry update: read in full
            if not _read(st, ob, depsgraph, bm, faces, uv):
                st.arrays = None
                return None
            st.op = op
        else:
            st.sel = set()
    _select(st, ob.data, bm, need)
    # The selection poll compares with what was drawn last
    if uv:
        if len(bm.verts) <= BMESH_LIMIT:
            bm.verts.index_update()
            bm.edges.index_update()
            bm.faces.index_update()
            _selection_snapshot[key] = _selection_signature(bm, True)
    else:
        _selection_snapshot[key] = counts_signature(ob.data, bm)
    return st


def _maya_layout(context):
    from .panel_toolbar import maya_screen          # the Maya layout or a panel torn off it
    return maya_screen(context)


def _apply_pending():
    from .. import live_refs
    todo = dict(_pending)
    _pending.clear()
    for (ptr, prop), value in todo.items():
        _w, area, space = live_refs.find_space(ptr)
        if space is not None and getattr(space.overlay, prop) != value:
            setattr(space.overlay, prop, value)
            area.tag_redraw()
    return None


def _face_overlay(context, space, kit_draws):
    """Switch the OVERLAY_OFF overlays of this view off while the kit draws the Maya look in a Maya layout view."""
    want_off = kit_draws and _maya_layout(context)
    for prop in OVERLAY_OFF:
        key = (space.as_pointer(), prop)
        value, ours = face_overlay_action(want_off, getattr(space.overlay, prop), key in _faces_off)
        if ours:
            _faces_off.add(key)
        else:
            _faces_off.discard(key)
        if value is not None and _pending.get(key) != value:
            _pending[key] = value
            if not bpy.app.timers.is_registered(_apply_pending):
                bpy.app.timers.register(_apply_pending, first_interval=0.0)


def _draw():
    context = bpy.context
    if context.mode != 'EDIT_MESH':
        return
    space, rv3d, region = context.space_data, context.region_data, context.region
    if rv3d is None or space is None or region is None or not space.overlay.show_overlays:
        return
    if not _enabled():
        if _faces_off:
            _face_overlay(context, space, False)
        if _cache or _selection_snapshot:
            _forget()               # nothing is kept up to date while off: read afresh when switched back on
        return
    from . import toolbox
    if toolbox.is_toolbox(space):
        return
    obs = edit_objects(context)
    if not obs:
        return
    import time
    import gpu
    t0 = time.perf_counter()
    depsgraph = context.view_layer.depsgraph
    select_mode = tuple(context.tool_settings.mesh_select_mode)
    uv = uv_mode(context)
    states = []
    for ob in obs:
        st = state(ob, depsgraph, select_mode[2] and not uv, uv, select_mode)
        if st is not None:
            states.append((ob, st))
    names = {ob.name for ob in obs} | {ob.data.name for ob in obs}
    _dirty.difference_update(names)
    _dirty_sel.difference_update(names)
    live = {(ob.as_pointer(), ob.data.as_pointer()) for ob in obs}
    for k in [k for k in _cache if k not in live]:
        del _cache[k]
    _face_overlay(context, space, len(states) == len(obs))
    if not states:
        return
    scale = context.preferences.system.ui_scale or 1.0
    vert_px = theme_point_sizes(context)
    gpu.state.depth_test_set('NONE' if _xray(space) else 'LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    proj = {'LINES': _biased_projection(rv3d, DEPTH_BIAS), 'TRIS': _biased_projection(rv3d, FACE_BIAS),
            'LINES_SEL': _biased_projection(rv3d, EDGE_SEL_BIAS), 'POINTS': _biased_projection(rv3d, POINT_BIAS)}
    gpu.matrix.push_projection()
    try:
        for ob, st in states:
            with gpu.matrix.push_pop():
                gpu.matrix.multiply_matrix(ob.matrix_world)
                for kind, sh, batch, color, size in _batches(st, select_mode):
                    gpu.matrix.load_projection_matrix(proj[kind])
                    sh.bind()
                    sh.uniform_float("color", color)
                    if kind == 'POINTS':
                        gpu.state.point_size_set(max(1.0, round(vert_px[size] * scale)))
                    elif kind in ('LINES', 'LINES_SEL'):
                        sh.uniform_float("viewportSize", (region.width, region.height))
                        sh.uniform_float("lineWidth", size * scale)
                    batch.draw(sh)
        gpu.state.point_size_set(1.0)
    finally:
        gpu.matrix.pop_projection()
        gpu.state.depth_test_set('NONE')
    _times.append(time.perf_counter() - t0)
    if len(_times) > 120:
        del _times[0]


def frame_ms():
    return sum(_times) / len(_times) * 1000.0 if _times else 0.0


def _callback():
    try:
        _draw()
    except Exception:
        # A transient graphics-context error must not permanently disable
        # highlighting until the entire add-on is reloaded.
        import traceback
        traceback.print_exc()


def _remove_handler():
    while _handle:
        bpy.types.SpaceView3D.draw_handler_remove(_handle.pop(), 'WINDOW')


def uv_mode(context):
    """The 3D View shows the UV selection: mesh edit mode in the kit's UV component (F12; UV Sync Selection off)."""
    from ..operators import uv_tools
    try:
        return context.mode == 'EDIT_MESH' and uv_tools.in_uv_mode(context.scene)
    except AttributeError:
        return False


def _selection_signature(bm, uv=False):
    """Selection *membership*, not only counts (replace / add / subtract all matter); one Python pass over every
    element. In UV mode the UV selection counts too (UV Editor clicks tag nothing in the 3D View), so the UV mode
    poll compares this; the mesh selection is followed through depsgraph updates and counts_signature."""
    sig = (len(bm.verts), len(bm.edges), len(bm.faces),
           tuple(v.index for v in bm.verts if v.select),
           tuple(e.index for e in bm.edges if e.select),
           tuple(f.index for f in bm.faces if f.select))
    if uv:
        sig += (uv, tuple(np.flatnonzero(uv_selected_verts(bm)).tolist()))
    return sig


def _poll_selection():
    """Redraw the Maya overlay when a component selection changed with no depsgraph update.

    Blender's selection operators send one (a selection-only update, see _on_depsgraph), so outside the UV
    component this compares only element and selection counts (constant time); in the UV component it compares the
    UV selection itself, up to BMESH_LIMIT vertices."""
    if not _handle:
        return None
    if not _enabled():
        return _POLL_INTERVAL          # nothing drawn
    if _transform_ptr() or _navigating():
        return _POLL_INTERVAL          # a transform or a view drag changes no selection
    try:
        import bmesh
        seen = set()
        changed = False
        wm = bpy.context.window_manager
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                with bpy.context.temp_override(window=window, area=area):
                    ctx = bpy.context
                    if ctx.mode != 'EDIT_MESH':
                        continue
                    for ob in edit_objects(ctx):
                        key = (ob.as_pointer(), ob.data.as_pointer())
                        if key in seen:
                            continue
                        seen.add(key)
                        bm = bmesh.from_edit_mesh(ob.data)
                        if uv_mode(ctx):
                            # Avoid scanning unusually large edit meshes on a UI timer.
                            if len(bm.verts) > BMESH_LIMIT:
                                continue
                            bm.verts.index_update()
                            bm.edges.index_update()
                            bm.faces.index_update()
                            sig = _selection_signature(bm, True)
                        else:
                            sig = counts_signature(ob.data, bm)
                        if _selection_snapshot.get(key) != sig:
                            _selection_snapshot[key] = sig
                            _dirty_sel.update((ob.name, ob.data.name))
                            changed = True
        for key in tuple(_selection_snapshot):
            if key not in seen:
                del _selection_snapshot[key]
        if changed:
            for window in wm.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError):
        pass  # transient area/mode changes while switching Blender screens
    return _POLL_INTERVAL


@bpy.app.handlers.persistent
def _on_depsgraph(_scene=None, depsgraph=None):
    """Mark what an update touched: a geometry update (points, elements, hidden flags, select mode; edit-mesh
    operators and ``bmesh.update_edit_mesh`` send one) -> read again; any other (a click, a box select, select
    more / less: a selection-only update; an object move) -> only the selection flags."""
    if depsgraph is None or not _cache:
        return
    for u in depsgraph.updates:
        if isinstance(u.id, (bpy.types.Mesh, bpy.types.Object)):
            name = u.id.original.name if u.id.original is not None else u.id.name
            (_dirty if u.is_updated_geometry else _dirty_sel).add(name)


def _forget():
    _cache.clear()
    _dirty.clear()
    _dirty_sel.clear()
    _selection_snapshot.clear()


@bpy.app.handlers.persistent
def _on_reload(*_args):
    _forget()


@bpy.app.handlers.persistent
def _on_load(*_args):
    from ..operators import uv_tools
    uv_tools.forget_uv_mode()
    _on_reload()


_HANDLERS = (("depsgraph_update_post", _on_depsgraph), ("undo_post", _on_reload), ("redo_post", _on_reload),
             ("load_post", _on_load))


def register():
    for name, fn in _HANDLERS:
        getattr(bpy.app.handlers, name).append(fn)
    _handle.append(bpy.types.SpaceView3D.draw_handler_add(_callback, (), 'WINDOW', 'POST_VIEW'))
    if not bpy.app.timers.is_registered(_poll_selection):
        bpy.app.timers.register(_poll_selection, first_interval=_POLL_INTERVAL, persistent=True)


def unregister():
    _remove_handler()
    if bpy.app.timers.is_registered(_poll_selection):
        bpy.app.timers.unregister(_poll_selection)
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name)
        if fn in lst:
            lst.remove(fn)
    if bpy.app.timers.is_registered(_apply_pending):
        bpy.app.timers.unregister(_apply_pending)
    _pending.clear()
    for key in list(_faces_off):
        _pending[key] = True
    _faces_off.clear()
    _apply_pending()
    _forget()
    _shader.clear()
    _times.clear()
