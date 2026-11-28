# SPDX-License-Identifier: GPL-3.0-or-later
"""UV shells (Blender UV islands) and the UV selection, on bmesh: ``islands`` (faces that share UVs across their
edges), ``selected_faces`` / ``selected_edges`` / ``target_islands`` / ``picked_anywhere`` (sync or per-corner UV
selection), shell centre / bounds / area, ``_edit_meshes`` and ``_with_faces`` / ``with_faces_of`` (run a Blender UV
operator on exactly some faces). Shared by every uv_* operator module; ``uv_tools`` re-exports all of it.
"""

import bmesh
from mathutils import Vector

from .. import compat

EPS = 1e-5           # UVs closer than this are one UV
NUDGE = 2e-4         # how far Cut moves the smaller side (0.2 px on a 1024 map)


# --- selection and islands (bmesh) ------------------------------------------------------------------

def _same(a, b):
    return abs(a.x - b.x) <= EPS and abs(a.y - b.y) <= EPS


def _uv_at(face, vert, uv):
    for loop in face.loops:
        if loop.vert is vert:
            return loop[uv].uv
    return None


def islands(bm, uv, faces=None, seams=False):
    """Lists of faces that share UVs across their edges (Blender's islands; ``seams``: a seam also splits)."""
    faces = list(bm.faces if faces is None else faces)
    index = {f: i for i, f in enumerate(faces)}
    parent = list(range(len(faces)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for e in {e for f in faces for e in f.edges}:
        if seams and e.seam:
            continue
        fs = [f for f in e.link_faces if f in index]
        for i in range(1, len(fs)):
            a, b = fs[0], fs[i]
            if all(_same(_uv_at(a, v, uv), _uv_at(b, v, uv)) for v in e.verts):
                ra, rb = find(index[a]), find(index[b])
                if ra != rb:
                    parent[rb] = ra
    groups = {}
    for f, i in index.items():
        groups.setdefault(find(i), []).append(f)
    return list(groups.values())


def sync(context):
    return context.scene.tool_settings.use_uv_select_sync


def selected_faces(bm, uv, synced):
    if synced:
        return [f for f in bm.faces if f.select and not f.hide]
    return [f for f in bm.faces if f.select and not f.hide and all(compat.uv_vert_selected(l, uv) for l in f.loops)]


def selected_edges(bm, uv, synced):
    if synced:
        return [e for e in bm.edges if e.select and not e.hide]
    out = set()
    for f in bm.faces:
        if f.hide or not f.select:
            continue
        for loop in f.loops:
            if compat.uv_edge_selected(loop, uv):
                out.add(loop.edge)
    return list(out)


def _picked_faces(bm, uv, synced):
    if synced:
        # like Maya: a selected face, else the faces around a selected edge (edge mode) or vertex (vertex mode)
        mode = bm.select_mode
        if 'VERT' in mode:
            return {f for f in bm.faces if not f.hide and any(v.select for v in f.verts)}
        if 'EDGE' in mode:
            return {f for f in bm.faces if not f.hide and any(e.select for e in f.edges)}
        return {f for f in bm.faces if f.select and not f.hide}
    return {f for f in bm.faces if f.select and not f.hide and any(compat.uv_vert_selected(l, uv) for l in f.loops)}


def target_islands(bm, uv, synced, fallback=True):
    """Shells touched by the selection (faces, else any selected UV), or every shell (``fallback``)."""
    every = islands(bm, uv, [f for f in bm.faces if not f.hide])
    picked = _picked_faces(bm, uv, synced)
    chosen = [isl for isl in every if picked & set(isl)]
    return chosen or (every if fallback else [])


def picked_anywhere(context, synced=None):
    """True when some UV / face is selected in any mesh in edit mode: then the commands that work on "the selected
    shells, all when none are selected" leave the other meshes alone."""
    synced = sync(context) if synced is None else synced
    for ob in _edit_meshes(context):
        bm = bmesh.from_edit_mesh(ob.data)
        uv = bm.loops.layers.uv.active
        if uv is not None and _picked_faces(bm, uv, synced):
            return True
    return False


def _island_loops(island):
    return [loop for f in island for loop in f.loops]


def uv_centre(island, uv):
    loops = _island_loops(island)
    return sum((l[uv].uv for l in loops), Vector((0.0, 0.0))) / max(len(loops), 1)


def uv_bounds(island, uv):
    us = [l[uv].uv for l in _island_loops(island)]
    lo = Vector((min(u.x for u in us), min(u.y for u in us)))
    hi = Vector((max(u.x for u in us), max(u.y for u in us)))
    return lo, hi


# --- a Blender UV operator on chosen faces (Unfold / Layout / Contour Stretch) ----------------------

def selection_state(bm):
    """The mesh and UV selection of ``bm`` and whether Blender's own UV selection (UV Sync Selection) is in use."""
    return ([v.select for v in bm.verts], [e.select for e in bm.edges], [f.select for f in bm.faces],
            [f.uv_select for f in bm.faces],
            [(l.uv_select_vert, l.uv_select_edge) for f in bm.faces for l in f.loops],
            getattr(bm, "uv_select_sync_valid", None))


def restore_selection(bm, state):
    verts, edges, faces, face_uv, loops, sync_valid = state
    # faces first: a face's flag sets its edges and vertices too
    for seq, flags in ((bm.faces, faces), (bm.edges, edges), (bm.verts, verts)):
        for el, on in zip(seq, flags):
            el.select = on
    for f, on in zip(bm.faces, face_uv):
        f.uv_select = on
    for l, (vert, edge) in zip((l for f in bm.faces for l in f.loops), loops):
        l.uv_select_vert = vert
        l.uv_select_edge = edge
    if sync_valid is not None:
        bm.uv_select_sync_valid = sync_valid


def _with_faces(context, ob, faces, call):
    """Run ``call`` with UV sync on and exactly ``faces`` of ``ob`` selected (Blender's unwrap / pack use that), then put
    the selection, the UV selection and sync back, like Maya keeps the selection through its UV commands. Those
    Blender operators work on every mesh in edit mode: the other meshes have nothing selected meanwhile (their
    picked faces were unwrapped / packed on their own, tearing them off their shells). Blender's own UV selection
    is set aside meanwhile, so the operators read the face selection."""
    return with_faces_of(context, {ob: [f.index for f in faces]}, call)


def with_faces_of(context, picks, call):
    """``_with_faces`` for several meshes at once: ``picks`` = {object: face indices}; every other mesh in edit mode
    has nothing selected meanwhile (one Blender pack then lays all the picked shells out together)."""
    ts = context.scene.tool_settings
    old_sync = ts.use_uv_select_sync
    old_mode = tuple(ts.mesh_select_mode)
    want = {o.data.as_pointer(): set(idx) for o, idx in picks.items()}
    meshes = list(picks) + [o for o in _edit_meshes(context) if o.data.as_pointer() not in want]
    saved = [(o, selection_state(bmesh.from_edit_mesh(o.data))) for o in meshes]
    ts.use_uv_select_sync = True
    ts.mesh_select_mode = (False, False, True)     # an edge / vertex mode would let Blender take more faces
    for o in meshes:
        bm = bmesh.from_edit_mesh(o.data)
        bm.faces.index_update()
        mine = want.get(o.data.as_pointer(), ())
        for f in bm.faces:
            f.select_set(False)
        for f in bm.faces:
            if f.index in mine:
                f.select_set(True)
        if hasattr(bm, "uv_select_sync_valid"):
            bm.uv_select_sync_valid = False
        bmesh.update_edit_mesh(o.data)
    try:
        return call()
    finally:
        ts.mesh_select_mode = old_mode
        ts.use_uv_select_sync = old_sync
        for o, state in saved:
            restore_selection(bmesh.from_edit_mesh(o.data), state)
            bmesh.update_edit_mesh(o.data)


# --- UV area, meshes in edit mode --------------------------------------------------------------------

def _uv_area(face, uv):
    pts = [l[uv].uv for l in face.loops]
    return abs(sum(pts[i].x * pts[i - 1].y - pts[i - 1].x * pts[i].y for i in range(len(pts)))) / 2


def _edit_meshes(context):
    return [o for o in getattr(context, "objects_in_mode_unique_data", ()) if o.type == 'MESH']
