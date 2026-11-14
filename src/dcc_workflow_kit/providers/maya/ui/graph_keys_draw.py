# SPDX-License-Identifier: GPL-3.0-or-later
"""Bigger keys in the Graph Editor.

Blender draws Graph Editor keys at the theme's Vertex Size (6 px at UI scale 1), which is hard to see and hard to
grab next to Maya's keys. The kit can't change the theme, so it draws over each key Blender draws, in the key's own
theme colour (Graph Editor WINDOW POST_PIXEL): an unselected key becomes one bigger dot; a selected key gets a rim
around Blender's own dot, so the active key keeps its colour in the middle. Preference ``graph_key_size`` = the key's diameter in pixels
at UI scale 1; 0 leaves Blender's keys alone.

Which keys: the curves Blender lists as visible (``context.visible_fcurves``) whose keys Blender draws: not locked,
keys usable with the curve's modifiers, and only selected curves when Blender's "Only Show Selected F-Curve
Keyframes" preference is on. Positions follow the Graph Editor mapping: NLA tweak time, rotation curves in degrees,
View > Normalize (``ui/graph_layers.py``).

Tangent handles get the same treatment where Blender shows them (View > Show Handles, Bezier segments, only around
selected keys while "Only Selected Keyframes Handles" is on): a handle point becomes a bold ring (``HANDLE_RATIO`` of
the key size, open in the middle so it never reads as a key) in the handle colour, a selected one a little wider in
the selected handle colour. While the kit draws the handles itself (``ui/graph_handles.py``: Blender's are off) the
handle lines are drawn too (grey, selected white, like Maya) and non-weighted handles sit at a fixed length; with
Key Size 0 the points keep Blender's handle size.
"""

import math

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

SEGMENTS = 16              # rim polygon sides
HANDLE_RATIO = 0.8         # handle point diameter / key diameter
# modifier types whose curve keeps editable keys (generators only when additive)
_USABLE_MODIFIERS = {'CYCLES', 'STEPPED', 'NOISE'}


def key_size(context):
    """Kit key diameter in pixels at UI scale 1, 0 = off."""
    from .. import preferences
    try:
        return int(preferences.get(context).graph_key_size)
    except (KeyError, AttributeError):
        return 0


def keys_usable(fc):
    """Blender draws a curve's keys only while its modifiers leave them editable."""
    for m in fc.modifiers:
        if m.mute or not m.active:
            continue
        if m.type in _USABLE_MODIFIERS:
            continue
        if m.type in ('GENERATOR', 'FNGENERATOR') and getattr(m, "use_additive", False):
            continue
        return False
    return True


def draws_keys(fc, only_selected):
    if fc.hide or fc.lock or (fc.group is not None and fc.group.lock):
        return False
    if only_selected and not fc.select:
        return False
    return len(fc.keyframe_points) > 0 and keys_usable(fc)


def _owners(scene):
    """{action pointer: AnimData} of objects in NLA tweak mode (their keys are drawn at scene time)."""
    out = {}
    for ob in scene.objects:
        ad = ob.animation_data
        if ad is not None and ad.use_tweak_mode and ad.action is not None:
            out[ad.action.as_pointer()] = ad
    return out


def _bezier():
    """Keyframe ``interpolation`` 'BEZIER' as ``foreach_get`` reads it (the enum item's number)."""
    if "bezier" not in _ENUM:
        _ENUM["bezier"] = bpy.types.Keyframe.bl_rna.properties["interpolation"].enum_items["BEZIER"].value
    return _ENUM["bezier"]


_ENUM = {}


class Keys:
    """The keys Blender draws in one Graph Editor, read once: the curves Blender lists as visible whose keys it draws
    (``draws_keys``), every curve's keys one after another, positions in view space (frame, display value: NLA tweak
    time, degrees, View > Normalize). ``fcurves`` the curves, ``factors`` [(offset, factor)] their value mapping,
    ``start`` each curve's first key index (+ the key count), ``co`` (n, 2) key positions, ``select`` selected keys.
    With ``handles``: ``left`` / ``right`` (n, 2) handle positions, ``select_left`` / ``select_right`` handle flags,
    ``bezier`` the key's own segment is Bezier."""

    def __init__(self, context, space, handles=False):
        from .graph_layers import normalization, value_factor
        scene = context.scene
        only_selected = bool(getattr(context.preferences.edit, "show_only_selected_curve_keyframes", False))
        normalize = bool(getattr(space, "use_normalization", False))
        tweak = _owners(scene)
        self.fcurves, self.factors, counts = [], [], []
        for fc in getattr(context, "visible_fcurves", None) or ():
            if draws_keys(fc, only_selected):
                self.fcurves.append(fc)
                counts.append(len(fc.keyframe_points))
        self.start = np.zeros(len(counts) + 1, dtype=np.int64)
        np.cumsum(counts, out=self.start[1:])
        n = int(self.start[-1])
        props = [("co", 2, np.float32), ("select_control_point", 1, bool)]
        if handles:
            props += [("handle_left", 2, np.float32), ("handle_right", 2, np.float32),
                      ("select_left_handle", 1, bool), ("select_right_handle", 1, bool), ("interpolation", 1, np.int32)]
        raw = {name: np.empty(n * width, dtype=dt) for name, width, dt in props}
        offs, facs, tweaked = np.zeros(len(counts)), np.ones(len(counts)), []
        for i, fc in enumerate(self.fcurves):
            a, b = int(self.start[i]), int(self.start[i + 1])
            kps = fc.keyframe_points
            for name, width, _dt in props:
                kps.foreach_get(name, raw[name][a * width:b * width])
            off, k = normalization(fc) if normalize else (0.0, value_factor(scene, fc))
            self.factors.append((off, k))
            offs[i], facs[i] = off, k
            ad = tweak.get(fc.id_data.as_pointer()) if tweak and fc.id_data is not None else None
            if ad is not None:
                tweaked.append((a, b, ad))
        # float32 values widen exactly to float64: the same numbers Blender writes into a float64 array
        off_key, fac_key = np.repeat(offs, counts), np.repeat(facs, counts)

        def view(name):
            co = raw[name].astype(np.float64).reshape(n, 2)
            co[:, 1] = (co[:, 1] + off_key) * fac_key
            for a, b, ad in tweaked:
                co[a:b, 0] = [ad.nla_tweak_strip_time_to_scene(x) for x in co[a:b, 0]]
            return co
        self.co = view("co")
        self.select = raw["select_control_point"]
        self.handles = handles
        if handles:
            self.left, self.right = view("handle_left"), view("handle_right")
            self.select_left, self.select_right = raw["select_left_handle"], raw["select_right_handle"]
            self.bezier = raw["interpolation"] == _bezier()

    def __len__(self):
        return len(self.co)

    def curve_of_key(self):
        """Curve index of every key."""
        return np.repeat(np.arange(len(self.fcurves)), np.diff(self.start))

    def handle_sides(self, near_selected):
        """(left shown, right shown) per key: Blender shows a key's left handle when the segment before it is Bezier
        (a curve's first key: its own segment), its right handle when its own segment is Bezier; with "Only Selected
        Keyframes Handles" only around selected keys / handles."""
        left = np.empty_like(self.bezier)
        if len(left):
            left[1:] = self.bezier[:-1]
            first = self.start[:-1]
            left[first] = self.bezier[first]
        right = self.bezier.copy()
        if near_selected:
            any_sel = self.select | self.select_left | self.select_right
            left, right = left & any_sel, right & any_sel
        return left, right

    def handle_rows(self, left_on, right_on):
        """(key index, side) of the shown handles in Blender's order: per curve its left handles, then its right
        ones, each by key."""
        rows = np.concatenate([np.nonzero(left_on)[0], np.nonzero(right_on)[0]])
        sides = np.concatenate([np.zeros(int(left_on.sum()), dtype=int), np.ones(int(right_on.sum()), dtype=int)])
        order = np.lexsort((rows, sides, self.curve_of_key()[rows]))
        return rows[order], sides[order]

    def handle_ends(self, rows, sides):
        """View-space handle positions of (key, side) rows."""
        return np.where((sides == 0)[:, None], self.left[rows], self.right[rows])


# --- reading once per view drag -----------------------------------------------------------------------------------
# While the user pans / zooms a Graph Editor (a view navigation operator runs modal in the window) no key can be
# edited or selected, so the keys read on the first draw of that drag are drawn again at the new view; any depsgraph
# update (a script or timer editing curves: setting a curve or key property tags its Action) or a draw with no
# navigation running reads them again.

NAV_OPS = {"VIEW2D_OT_pan", "VIEW2D_OT_zoom", "VIEW2D_OT_scroller_activate", "VIEW2D_OT_ndof",
           "VIEW2D_OT_smoothview", "ALLSET_OT_nav_2d"}
_nav = {"gen": 0, "quiet": 0, "keys": {}}       # depsgraph updates, draws with no navigation, region -> (key, Keys)


def _navigation(context):
    """Pointer of the View2D navigation operator running modal in the context's window, else None."""
    window = getattr(context, "window", None)
    for op in getattr(window, "modal_operators", None) or ():
        if op is not None and op.bl_idname in NAV_OPS:
            return op.as_pointer()
    return None


def drawn_keys(context, space, region, handles):
    """``Keys`` of this Graph Editor region for one draw (kept while a view drag runs)."""
    op = _navigation(context)
    if op is None:
        _nav["quiet"] += 1
        _nav["keys"].clear()
        return Keys(context, space, handles)
    edit = context.preferences.edit
    key = (op, _nav["quiet"], _nav["gen"], space.as_pointer(), context.scene.as_pointer(), handles,
           bool(getattr(edit, "show_only_selected_curve_keyframes", False)),
           bool(getattr(space, "use_normalization", False)), context.scene.unit_settings.system_rotation)
    hit = _nav["keys"].get(region.as_pointer())
    if hit is not None and hit[0] == key:
        return hit[1]
    keys = Keys(context, space, handles)
    _nav["keys"][region.as_pointer()] = (key, keys)
    return keys


@bpy.app.handlers.persistent
def _on_depsgraph(*_args):
    _nav["gen"] += 1


@bpy.app.handlers.persistent
def _on_load(*_args):
    _nav["gen"] += 1
    _nav["keys"].clear()


def key_points(context, space, keys=None):
    """(unselected, selected) arrays of key positions in Graph Editor view space (frame, value)."""
    keys = Keys(context, space) if keys is None else keys
    return keys.co[~keys.select], keys.co[keys.select]


def handle_points(context, space, keys=None):
    """(unselected, selected) arrays of tangent handle positions in Graph Editor view space (frame, value)."""
    empty = np.zeros((0, 2))
    from .graph_handles import shows_handles
    if not shows_handles(space):
        return empty, empty
    keys = Keys(context, space, handles=True) if keys is None or not keys.handles else keys
    near_selected = bool(getattr(space, "use_only_selected_keyframe_handles", False))
    rows, sides = keys.handle_rows(*keys.handle_sides(near_selected))
    if not len(rows):
        return empty, empty
    co = keys.handle_ends(rows, sides)
    picked = np.where(sides == 0, keys.select_left[rows], keys.select_right[rows])
    return co[~picked], co[picked]


def view_map(region):
    """(x0, y0, sx, sy): region pixel = (view - x0 / y0) x sx / sy."""
    v2d = region.view2d
    x0, y0 = v2d.region_to_view(0, 0)
    x1, y1 = v2d.region_to_view(region.width, region.height)
    sx = region.width / (x1 - x0) if x1 != x0 else 0.0
    sy = region.height / (y1 - y0) if y1 != y0 else 0.0
    return x0, y0, sx, sy


def to_region(region, pts):
    """View-space points -> region pixels (the view is a linear map of the region)."""
    x0, y0, sx, sy = view_map(region)
    out = np.empty_like(pts)
    out[:, 0] = (pts[:, 0] - x0) * sx
    out[:, 1] = (pts[:, 1] - y0) * sy
    return out


def _in_region(centres, r_out, margin, width, height):
    if width is not None and len(centres):
        m = r_out + margin
        keep = (centres[:, 0] > -m) & (centres[:, 0] < width + m) & (centres[:, 1] > -m) & (centres[:, 1] < height + m)
        centres = centres[keep]
    return centres


def _ring(r_in, r_out):
    """(inner, outer) corner points of a ring, (SEGMENTS + 1, 2) each (the last = the first, turned once around)."""
    a = np.linspace(0.0, 2.0 * math.pi, SEGMENTS + 1)
    ca, sa = np.cos(a), np.sin(a)
    return np.stack([ca * r_in, sa * r_in], axis=1), np.stack([ca * r_out, sa * r_out], axis=1)


CORNERS = 2 * (SEGMENTS + 1)        # corner points of one ring (inner, then outer)


def rim_vertices(centres, r_in, r_out, margin=0.0, width=None, height=None):
    """float32 corner points of the rings ``rims`` draws (``CORNERS`` per kept centre): each the float64 sum
    rounded once to float32, the numbers ``rims`` lists."""
    centres = _in_region(centres, r_out, margin, width, height)
    inner, outer = _ring(r_in, r_out)
    corners = np.concatenate([inner, outer])
    out = np.empty((len(centres), CORNERS, 2), dtype=np.float32)
    np.add(np.asarray(centres, dtype=np.float64)[:, None, :], corners[None, :, :], out=out, casting='unsafe')
    return out.reshape(-1, 2)


def rim_indices(rings):
    """int32 triangle indices of ``rings`` rings into their ``rim_vertices``: the triangles ``rims`` lists, in its
    order."""
    s = np.arange(SEGMENTS, dtype=np.int32)
    i0, i1, o0, o1 = s, s + 1, SEGMENTS + 1 + s, SEGMENTS + 2 + s
    one = np.stack([np.stack([i0, o0, o1], axis=1), np.stack([i0, o1, i1], axis=1)], axis=1).reshape(-1, 3)
    tris = one[None, :, :] + (np.arange(rings, dtype=np.int32) * np.int32(CORNERS))[:, None, None]
    return tris.reshape(-1, 3)


def rim_mesh(centres, r_in, r_out, margin=0.0, width=None, height=None):
    """(float32 vertices, int32 triangle indices) of the rings ``rims`` lists: the same triangles in the same
    order from a third of the vertices."""
    verts = rim_vertices(centres, r_in, r_out, margin, width, height)
    return verts, rim_indices(len(verts) // CORNERS)


def rims(centres, r_in, r_out, margin=0.0, width=None, height=None):
    """Triangles of a ring (r_in .. r_out) around every centre; centres outside the region (+ r_out) are skipped."""
    centres = _in_region(centres, r_out, margin, width, height)
    if not len(centres):
        return np.zeros((0, 2), dtype=np.float32)
    inner, outer = _ring(r_in, r_out)
    i0, i1, o0, o1 = inner[:-1], inner[1:], outer[:-1], outer[1:]
    quad = np.stack([i0, o0, o1, i0, o1, i1], axis=1).reshape(-1, 2)     # (S * 6, 2)
    tris = centres[:, None, :] + quad[None, :, :]
    return tris.reshape(-1, 2).astype(np.float32)


def radii(context, size):
    """(inner, outer) rim radius in pixels: inside = a little within Blender's own key, outside = the kit size."""
    scale = context.preferences.system.ui_scale or 1.0      # 0 in background
    theme = context.preferences.themes[0].graph_editor
    blender = theme.vertex_size * scale / 2.0
    return max(0.0, blender - 1.0), size * scale / 2.0


def handle_radii(context, size):
    """(ring inner, ring outer, selected ring outer) radius in pixels of the kit handle points (Blender draws a 1.5 px
    ring of the theme's handle vertex size x 1.4, scaled by the pixel size)."""
    system = context.preferences.system
    scale = system.ui_scale or 1.0
    curves = context.preferences.themes[0].common.curves
    blender = 1.4 * curves.handle_vertex_size * max(1.0, float(system.pixel_size or 1.0)) / 2.0
    outer = size * HANDLE_RATIO * scale / 2.0
    return max(0.0, min(blender - 1.5, outer - 2.0 * scale)), outer, outer + 0.5 * scale


def _rgba(c):
    c = tuple(c)
    return c if len(c) == 4 else c + (1.0,)


def blender_handle_radii(context):
    """(ring inner, ring outer) radius in pixels of a handle point at Blender's own size (Key Size 0)."""
    system = context.preferences.system
    curves = context.preferences.themes[0].common.curves
    outer = 1.4 * curves.handle_vertex_size * max(1.0, float(system.pixel_size or 1.0)) / 2.0
    return max(0.0, outer - 1.5), outer


# --- drawing --------------------------------------------------------------------------------------------------------
# What the kit draws is a list of items (primitive, vertices, colour, line width, triangle indices) turned into GPU
# batches. A ring is drawn from its 2 x (SEGMENTS + 1) corner points with indices: the same triangles ``rims``
# lists, a third of the vertices.

def _line_item(segments, colour, width):
    return ('LINES', segments.astype(np.float32), tuple(colour), width, None)


def _rim_item(centres, inner, outer, colour, region, cull):
    """A ring item, or None when no ring is left (``cull``: centres outside the region skipped)."""
    if not len(centres) or outer <= inner:
        return None
    if cull:
        verts = rim_vertices(centres, inner, outer, width=region.width, height=region.height)
    else:
        verts = rim_vertices(centres, inner, outer)
    return ('RINGS', verts, _rgba(colour), None, len(verts) // CORNERS) if len(verts) else None


def kit_handle_items(context, region, space, size, keys=None, cull=True):
    """Handle lines and points the kit draws while Blender's are off (``graph_handles``), in drawing order."""
    from . import graph_handles
    h = graph_handles.Handles(context, space, region, keys=keys)
    if not len(h):
        return []
    if size > 0:
        h_in, h_out, h_dot = handle_radii(context, size)
    else:
        h_in, h_out = blender_handle_radii(context)
        h_dot = h_out
    curves = context.preferences.themes[0].common.curves
    width = max(1.0, context.preferences.system.ui_scale or 1.0)
    items = []
    for picked, colour in ((False, graph_handles.LINE_RGBA), (True, graph_handles.LINE_SEL_RGBA)):
        m = h.selected == picked
        seg = np.empty((int(m.sum()) * 2, 2))
        seg[0::2], seg[1::2] = h.key_px[m], h.end_px[m]
        if len(seg):
            items.append(_line_item(seg, colour, width))
    for picked, colour, outer in ((False, curves.handle_vertex, h_out), (True, curves.handle_vertex_select, h_dot)):
        item = _rim_item(h.end_px[h.selected == picked], h_in, outer, colour, region, cull)
        if item is not None:
            items.append(item)
    return items


def key_items(context, region, space, size, kit_handles, keys=None, cull=True):
    """Key rims (and the handle points Blender shows while the kit doesn't draw the handles), in drawing order."""
    try:
        r_in, r_out = radii(context, size)
        if r_out <= r_in:
            return []
        unsel, sel = key_points(context, space, keys)
    except (AttributeError, ReferenceError, TypeError, ValueError):
        return []
    try:
        if kit_handles:                         # drawn with the kit's handles
            raise ValueError
        h_unsel, h_sel = handle_points(context, space, keys)
        h_in, h_out, h_dot = handle_radii(context, size)
    except (AttributeError, ReferenceError, TypeError, ValueError):
        h_unsel = h_sel = np.zeros((0, 2))
        h_in = h_out = h_dot = 0.0
    theme = context.preferences.themes[0].graph_editor
    curves = context.preferences.themes[0].common.curves
    items = []
    for pts, colour, inner, outer in ((h_unsel, curves.handle_vertex, h_in, h_out),
                                      (h_sel, curves.handle_vertex_select, h_in, h_dot),
                                      (unsel, theme.vertex, 0.0, r_out), (sel, theme.vertex_select, r_in, r_out)):
        if not len(pts) or outer <= inner:
            continue
        item = _rim_item(to_region(region, pts), inner, outer, colour, region, cull)
        if item is not None:
            items.append(item)
    return items


_ring_index = {}       # ring count -> GPU index buffer of that many rings (the pattern depends on the count only)


def _ring_batch(shader, verts, rings):
    """A TRIS batch of ``rings`` rings (``rim_vertices``) with a kept index buffer: the vertex format
    ``batch_for_shader`` makes for 2D positions."""
    from gpu.types import GPUBatch, GPUIndexBuf, GPUVertBuf, GPUVertFormat
    ibo = _ring_index.get(rings)
    if ibo is None:
        while len(_ring_index) >= 4:
            _ring_index.pop(next(iter(_ring_index)))
        ibo = _ring_index[rings] = GPUIndexBuf(type='TRIS', seq=rim_indices(rings))
    fmt = GPUVertFormat()
    for name, attr_type in shader.attrs_info_get():
        int_type = attr_type not in {'FLOAT', 'VEC2', 'VEC3', 'VEC4', 'MAT3', 'MAT4'}
        fmt.attr_add(id=name, comp_type='I32' if int_type else 'F32', len=2, fetch_mode='INT' if int_type else 'FLOAT')
    vbo = GPUVertBuf(fmt, len(verts))
    vbo.attr_fill("pos", verts)
    return GPUBatch(type='TRIS', buf=vbo, elem=ibo)


def _batches(items):
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    out = []
    for kind, verts, colour, width, rings in items:
        batch = _ring_batch(shader, verts, rings) if kind == 'RINGS' else \
            batch_for_shader(shader, kind, {"pos": verts})
        out.append((batch, colour, width))
    return out


def _draw_batches(batches, shift=None):
    if not batches:
        return
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    if shift is not None:
        gpu.matrix.push()
        gpu.matrix.translate(shift)
    try:
        for batch, colour, width in batches:
            if width is not None:
                gpu.state.line_width_set(width)
            shader.uniform_float("color", colour)
            batch.draw(shader)
            if width is not None:
                gpu.state.line_width_set(1.0)
    finally:
        if shift is not None:
            gpu.matrix.pop()
        gpu.state.blend_set('NONE')


def draw_kit_handles(context, region, space, size):
    """Handle lines and points the kit draws while Blender's are off (``graph_handles``)."""
    _draw_batches(_batches(kit_handle_items(context, region, space, size)))


# While a view drag runs, the batches of the drag's first frame are drawn again moved by the pan: keys and
# fixed-length tangents are a rigid image of the view while its scale stays. A scale change (zoom), another look or
# other keys (``drawn_keys``) draw anew. Batches kept for a drag hold every key, also the ones outside the region, so
# the pan can bring them in.
_drag = {}          # region pointer -> (Keys, look, view map, batches)
_SCALE_TOL = 1e-6   # relative view scale change that is float rounding of a pan (the view rectangle is float32)


def _look(context, space, size, kit_handles):
    from .graph_handles import shows_handles
    prefs = context.preferences
    theme, curves = prefs.themes[0].graph_editor, prefs.themes[0].common.curves
    return (size, kit_handles, shows_handles(space), bool(getattr(space, "use_only_selected_keyframe_handles", False)),
            prefs.system.ui_scale, prefs.system.pixel_size, theme.vertex_size, curves.handle_vertex_size,
            tuple(theme.vertex), tuple(theme.vertex_select), tuple(curves.handle_vertex),
            tuple(curves.handle_vertex_select))


def panned(old, new):
    """Pixel shift (x, y) from one view map (``view_map``) to another, or None when the scale changed."""
    x0, y0, sx, sy = old
    nx0, ny0, nsx, nsy = new
    if abs(nsx - sx) > _SCALE_TOL * abs(sx) or abs(nsy - sy) > _SCALE_TOL * abs(sy):
        return None
    return ((x0 - nx0) * sx, (y0 - ny0) * sy)


def draw():
    context = bpy.context
    region = context.region
    space = context.space_data
    if region is None or region.type != 'WINDOW' or space is None or space.type != 'GRAPH_EDITOR' \
            or space.mode != 'FCURVES':
        return
    from . import editor_chrome, graph_handles
    if not editor_chrome.enabled(context):
        return
    size = key_size(context)
    kit_handles = graph_handles.owns(space)
    if not kit_handles and size <= 0:
        return
    ptr = region.as_pointer()
    try:
        keys = drawn_keys(context, space, region, graph_handles.shows_handles(space) and (kit_handles or size > 0))
    except (AttributeError, ReferenceError, TypeError, ValueError):
        _drag.pop(ptr, None)
        return
    nav = _navigation(context) is not None
    if not nav:
        _drag.clear()
    look = _look(context, space, size, kit_handles) if nav else None
    mapping = view_map(region)
    kept = _drag.get(ptr)
    if kept is not None and kept[0] is keys and kept[1] == look:
        shift = panned(kept[2], mapping)
        if shift is not None:
            _draw_batches(kept[3], shift)
            return
    items = []
    if kit_handles:
        try:
            items += kit_handle_items(context, region, space, size, keys, cull=not nav)
        except (AttributeError, ReferenceError, TypeError, ValueError, IndexError):
            pass
    if size > 0:
        items += key_items(context, region, space, size, kit_handles, keys, cull=not nav)
    batches = _batches(items)
    if nav:
        _drag[ptr] = (keys, look, mapping, batches)
    _draw_batches(batches)


_handle = []


_HANDLERS = (("depsgraph_update_post", _on_depsgraph), ("load_post", _on_load), ("undo_post", _on_load),
             ("redo_post", _on_load))


def register():
    _handle.append(bpy.types.SpaceGraphEditor.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL'))
    for name, fn in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn not in handlers:
            handlers.append(fn)


def unregister():
    while _handle:
        bpy.types.SpaceGraphEditor.draw_handler_remove(_handle.pop(), 'WINDOW')
    for name, fn in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn in handlers:
            handlers.remove(fn)
    _nav["keys"].clear()
    _drag.clear()
    _ring_index.clear()
