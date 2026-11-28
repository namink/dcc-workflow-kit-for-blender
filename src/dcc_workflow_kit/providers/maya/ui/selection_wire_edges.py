# SPDX-License-Identifier: GPL-3.0-or-later
"""The wire of an evaluated object: point positions and edge indices read in one copy each (``edges_of``), a
lattice's U / V / W grid (``lattice_edges``), and the edges of a mesh that only deforms, kept between frames
(``keeps_edges``, ``_edges``) so playback reads only its points. Related: ``selection_wire`` (batches, handlers).
"""

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
        if me is None:
            # no splines, or Geometry Nodes that leave no curve or mesh (only instances): no wire to draw
            import numpy as np
            ev.to_mesh_clear()
            return np.empty((0, 3), np.float32), np.empty((0, 2), np.intc)
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
