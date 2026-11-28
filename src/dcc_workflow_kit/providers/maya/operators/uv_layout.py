# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya UV Editor > Modify > Layout with its option window's settings, on Blender's Pack Islands.

The settings (field names of the Layout Options window, operators/option_windows_uv.py):
- Shell Pre-Rotation: Off / Horizontal / Vertical (each shell first turned to its smallest box, then its long side
  along U or V) / Align X, Y, Z to V (that axis of the object points up the V direction in each shell).
- Shell Pre-Scaling: Preserve 3D Ratios (shells first scaled to their 3D size ratio: one texel density; default),
  Off and Preserve UV Ratios (shells keep their UV size ratio).
- Rotate Shells (off by default): the packer may turn shells, in steps of 90 degrees when Rotation Steps is a
  multiple of 90, freely otherwise.
- Texture Map Size + Padding Units (pixels / UV) + Shell Padding (between shells) + Tile Padding (kept free inside
  the packing region's border); pixels are pixels of the map across the region's width, like Maya.
- Packing Region: Full square (0-1), the halves and quarters of it, or Custom (U / V from - to).
- Scale Mode: Uniform (the packed shells scaled as one to fill the region; default), Off (shells keep their size,
  only moved), Non-Uniform (then stretched along U and V to fill the region).
- Multiple Objects: Pack Together (all meshes' shells in one layout, none overlapping; default) or Pack Separately
  (each mesh laid out on its own over the whole region).
- Stack Similar: shells of the same shape are stacked on each other first and stay stacked in the layout.
- Shell Distribution + Tiles U / V: with more than one tile the shells spread over the UDIM tiles (1001 = the 0-1
  square, then along U and up V): Distribute shares them out by count in shell order, Shell Centers keeps each shell in
  the tile its centre is in. Each tile is packed and filled on its own (the packing region and paddings repeat in
  every tile).
"""

import math

import bmesh
import bpy
from mathutils import Vector

from .uv_islands import _island_loops, uv_bounds, with_faces_of

REGIONS = {
    "Full square": (0.0, 1.0, 0.0, 1.0), "Top half": (0.0, 1.0, 0.5, 1.0), "Top left": (0.0, 0.5, 0.5, 1.0),
    "Top right": (0.5, 1.0, 0.5, 1.0), "Bottom half": (0.0, 1.0, 0.0, 0.5), "Bottom left": (0.0, 0.5, 0.0, 0.5),
    "Bottom right": (0.5, 1.0, 0.0, 0.5), "Left half": (0.0, 0.5, 0.0, 1.0), "Right half": (0.5, 1.0, 0.0, 1.0),
}
MAP_SIZES = ("4096", "2048", "1024", "512", "256", "128", "64", "32", "Custom")
PRE_ROTATE = ("Off", "Horizontal", "Vertical", "Align X to V", "Align Y to V", "Align Z to V")
PRE_SCALE = ("Off", "Preserve 3D Ratios", "Preserve UV Ratios")
SCALE_MODES = ("Off", "Uniform", "Non-Uniform")
MULTI = ("Pack Together (non-overlapping)", "Pack Separately (overlapping)")
DISTRIBUTIONS = ("Distribute", "Shell Centers")


def region(v):
    """(min U, max U, min V, max V) of the packing region; an empty custom region = the 0-1 square."""
    if v["region"] != "Custom":
        return REGIONS.get(v["region"], REGIONS["Full square"])
    box = (v["region_min_u"], v["region_max_u"], v["region_min_v"], v["region_max_v"])
    return box if box[0] < box[1] and box[2] < box[3] else REGIONS["Full square"]


def map_size(v):
    return max(int(v["custom_size"]) if v["map_size"] == "Custom" else int(v["map_size"]), 1)


def paddings(v):
    """(shell padding, tile padding) in UV units: pixels are pixels of the map across the region's width."""
    lo_u, hi_u, _lo_v, _hi_v = region(v)
    k = (hi_u - lo_u) / map_size(v) if v["padding_units"] == "Pixels" else 1.0
    return max(v["shell_padding"], 0.0) * k, max(v["tile_padding"], 0.0) * k


# --- UVs of the picked faces ---------------------------------------------------------------------------------------

def _faces(ob, idx):
    bm = bmesh.from_edit_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    return bm, bm.loops.layers.uv.verify(), [bm.faces[i] for i in idx]


def _transform(group, fn):
    """``fn(uv) -> uv`` on every UV of the picked faces of every mesh in ``group`` ({object: face indices})."""
    for ob, idx in group.items():
        bm, uv, faces = _faces(ob, idx)
        for f in faces:
            for loop in f.loops:
                loop[uv].uv = fn(loop[uv].uv.copy())
        bmesh.update_edit_mesh(ob.data)


def _bounds(group):
    lo, hi = Vector((math.inf, math.inf)), Vector((-math.inf, -math.inf))
    for ob, idx in group.items():
        _bm, uv, faces = _faces(ob, idx)
        if faces:
            a, b = uv_bounds(faces, uv)
            lo, hi = Vector((min(lo.x, a.x), min(lo.y, a.y))), Vector((max(hi.x, b.x), max(hi.y, b.y)))
    return lo, hi


def _turn_long_side(group, along_u):
    """Each shell a quarter turn about its box centre when its long side doesn't run along U (``along_u``) / V."""
    from .uv_islands import islands
    for ob, idx in group.items():
        bm, uv, faces = _faces(ob, idx)
        for isl in islands(bm, uv, faces):
            lo, hi = uv_bounds(isl, uv)
            w, h = hi.x - lo.x, hi.y - lo.y
            if (h > w + 1e-9) if along_u else (w > h + 1e-9):
                c = (lo + hi) / 2
                for loop in _island_loops(isl):
                    d = loop[uv].uv - c
                    loop[uv].uv = c + Vector((-d.y, d.x))
        bmesh.update_edit_mesh(ob.data)


def _stack_similar(group):
    from . import uv_modify
    from .uv_islands import islands
    from .uv_shells import _index_loops
    for ob, idx in group.items():
        bm, uv, faces = _faces(ob, idx)
        _index_loops(bm)
        pts, where = uv_modify.all_points(bm, uv)
        if uv_modify.stack_similar(islands(bm, uv, faces), uv, pts, where):
            bmesh.update_edit_mesh(ob.data)


# --- Layout ----------------------------------------------------------------------------------------------------------

def _pre_transform(context, group, v):
    rot = v["pre_rotate"]
    if rot in ("Horizontal", "Vertical"):
        with_faces_of(context, group, lambda: bpy.ops.uv.align_rotation(method='AUTO'))
        _turn_long_side(group, rot == "Horizontal")
    elif rot.startswith("Align "):
        axis = rot.split()[1]
        with_faces_of(context, group, lambda: bpy.ops.uv.align_rotation(method='GEOMETRY', axis=axis))
    if v["pre_scale"] == "Preserve 3D Ratios":
        with_faces_of(context, group, lambda: bpy.ops.uv.average_islands_scale())


def _pack(context, group, v, tile=(0, 0)):
    lo_u, hi_u, lo_v, hi_v = region(v)
    lo_u, hi_u, lo_v, hi_v = lo_u + tile[0], hi_u + tile[0], lo_v + tile[1], hi_v + tile[1]
    shell_pad, tile_pad = paddings(v)
    # the tile padding stays free inside the region's border
    lo_u, hi_u = lo_u + min(tile_pad, (hi_u - lo_u) / 2 - 1e-6), hi_u - min(tile_pad, (hi_u - lo_u) / 2 - 1e-6)
    lo_v, hi_v = lo_v + min(tile_pad, (hi_v - lo_v) / 2 - 1e-6), hi_v - min(tile_pad, (hi_v - lo_v) / 2 - 1e-6)
    w, h = hi_u - lo_u, hi_v - lo_v
    rotate = v["rotate"]
    # Blender packs into the 0-1 square: the shells are packed squeezed by the region's aspect and stretched back,
    # which is exact while shells keep their orientation; turned shells go into the region's largest square instead
    sw, sh = (w, h) if not rotate else (min(w, h), min(w, h))
    # moved to the 0-1 tile first (Blender packs into the UDIM tile nearest the shells), and inside it unless the
    # shells keep their size
    lo, hi = _bounds(group)
    fit = 1.0 if v["scale_mode"] == "Off" else max((hi.x - lo.x) / sw, (hi.y - lo.y) / sh, 1e-9)
    _transform(group, lambda p: Vector(((p.x - lo.x) / sw / fit, (p.y - lo.y) / sh / fit)))
    step = v["rotate_step"]
    # Scale Mode Off: the shells keep their size and are only placed
    kw = {"rotate": rotate, "scale": v["scale_mode"] != "Off", "merge_overlap": v["stack_similar"],
          "margin_method": 'FRACTION', "margin": shell_pad / math.sqrt(sw * sh)}
    if rotate:
        kw["rotate_method"] = 'CARDINAL' if step > 0 and abs(step / 90.0 - round(step / 90.0)) < 1e-6 else 'ANY'
    with_faces_of(context, group, lambda: bpy.ops.uv.pack_islands(**kw))
    if v["scale_mode"] == "Non-Uniform":
        lo, hi = _bounds(group)
        bw, bh = max(hi.x - lo.x, 1e-9), max(hi.y - lo.y, 1e-9)
        fw, fh = w / sw, h / sh       # the whole region (turned shells: its largest square stretched to it)
        _transform(group, lambda p: Vector(((p.x - lo.x) / bw * fw, (p.y - lo.y) / bh * fh)))
    _transform(group, lambda p: Vector((lo_u + p.x * sw, lo_v + p.y * sh)))


def _shells(group):
    """[(object, face indices of one shell, UV area, UV box centre)] in object and face order."""
    from .uv_islands import islands, _uv_area
    out = []
    for ob, idx in group.items():
        _bm, uv, faces = _faces(ob, idx)
        for isl in islands(_bm, uv, faces):
            isl.sort(key=lambda f: f.index)
            lo, hi = uv_bounds(isl, uv)
            out.append((ob, [f.index for f in isl], sum(_uv_area(f, uv) for f in isl), (lo + hi) / 2))
    out.sort(key=lambda s: (list(group).index(s[0]), s[1][0]))
    return out


def tiles_of(shells, v):
    """{(tile U, tile V): [shells]}: how the shells spread over the Tiles U x Tiles V UDIM tiles (tile (0, 0) = the
    0-1 square). Distribute: in shell order, runs of (shells + 1) // tiles shells (at least one) go to the tiles in
    turn, along U first, starting again at the first tile when the shells are not used up (shell sizes do not
    matter); Shell Centers: each shell stays in the tile its centre is in, and the shells outside
    the tiles go together into the tile below the first one."""
    nu, nv = max(int(v.get("tiles_u", 1)), 1), max(int(v.get("tiles_v", 1)), 1)
    out = {}
    if v.get("distribution", DISTRIBUTIONS[0]) == DISTRIBUTIONS[1]:
        for s in shells:
            t = (math.floor(s[3].x), math.floor(s[3].y))
            if not (0 <= t[0] < nu and 0 <= t[1] < nv):
                t = (0, -1)
            out.setdefault(t, []).append(s)
        return out
    n = nu * nv
    per_tile = max((len(shells) + 1) // n, 1)
    for i, s in enumerate(shells):
        k = i // per_tile % n
        out.setdefault((k % nu, k // nu), []).append(s)
    return out


def _pack_tiles(context, group, v):
    """Pack ``group``: into the packing region of one tile, or spread over several UDIM tiles (each tile packed on
    its own and filled, like Maya)."""
    if max(int(v.get("tiles_u", 1)), 1) * max(int(v.get("tiles_v", 1)), 1) == 1:
        _pack(context, group, v)
        return
    for tile, shells in tiles_of(_shells(group), v).items():
        sub = {}
        for ob, idx, _a, _c in shells:
            sub.setdefault(ob, []).extend(idx)
        _pack(context, sub, v, tile)


def layout(context, picks, v):
    """Maya Layout with the option values ``v`` on ``picks`` ({object: face indices}). Returns the number of meshes
    laid out."""
    picks = {ob: idx for ob, idx in picks.items() if idx}
    if not picks:
        return 0
    together = v["multi"] == MULTI[0]
    groups = [picks] if together else [{ob: idx} for ob, idx in picks.items()]
    for group in groups:
        if v["stack_similar"]:
            _stack_similar(group)
        _pre_transform(context, group, v)
        _pack_tiles(context, group, v)
    return len(picks)
