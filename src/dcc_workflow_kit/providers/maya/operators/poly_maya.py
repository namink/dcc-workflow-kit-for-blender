# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Edit Mesh / Mesh Tools commands with Maya's results
(Connect / Merge / Smooth / Symmetrize too).
Circularize, Connect, Make Hole; Connect, Merge, Smooth, Symmetrize. Pure bmesh.
Code: poly_connect (Connect), poly_smooth (Smooth, polySmoothFace), poly_symmetrize (Symmetrize), poly_average
(Average Vertices, polyAverageVertex); this module keeps
Circularize, Make Hole, Merge, the classes tuple and re-exports.
"""

import math

import bmesh
import bpy

from .. import results
# the split-out commands, also read through this module by other operators and the tests
from .poly_connect import CONNECT_WARNING, ALLSET_OT_connect, connect, connect_items  # noqa: F401
from .poly_smooth import SMOOTH, ALLSET_OT_smooth, ALLSET_OT_smooth_edit, smooth, smooth_targets  # noqa: F401
from .poly_average import AVERAGE, ALLSET_OT_average_vertices, ALLSET_OT_average_vertices_edit, average  # noqa: F401
from .poly_symmetrize import (SYMMETRIZE_NO_COMPONENTS, SYMMETRIZE_PROMPT, ALLSET_OT_symmetrize,  # noqa: F401
                              mirror_plane, pick_edge, symmetrize, topo_mirror)


# --- Circularize -------------------------------------------------------------------------------

def _ordered_loops(edges):
    """Closed loops among ``edges`` as ordered vertex lists (open chains are skipped)."""
    adj = {}
    for e in edges:
        a, b = e.verts
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    loops, seen = [], set()
    for start in adj:
        if start in seen or len(adj[start]) != 2:
            continue
        loop, prev, cur = [start], None, start
        ok = True
        while True:
            seen.add(cur)
            nxt = [v for v in adj[cur] if v is not prev]
            if len(adj[cur]) != 2 or not nxt:
                ok = False
                break
            prev, cur = cur, nxt[0]
            if cur is start:
                break
            loop.append(cur)
        if ok and len(loop) >= 3:
            loops.append(loop)
    return loops


def circularize_loop(verts, radial_offset=0.0, twist=0.0, even=True, ref=None, normal=None, keep_lowest=False):
    """Put an ordered vertex loop on a circle: centre = centroid, radius = mean distance in the circle's plane
    (+ ``radial_offset``), evenly spaced keeping the loop's mean angular position, or with ``keep_lowest`` the
    lowest-index vertex keeping its angle (Maya on an edge or vertex loop). The plane's normal is ``normal`` when
    given, else the loop's own (Newell). Options: ``twist`` (radians) turns the loop
    right-handed about ``ref`` (the faces' normal), ``even`` off keeps each vertex's own angle about the centre.
    Returns the loop's normal (oriented like ``ref``) or None."""
    from mathutils import Vector
    n = len(verts)
    if keep_lowest:
        k = min(range(n), key=lambda i: verts[i].index)
        verts = verts[k:] + verts[:k]
    pts = [v.co.copy() for v in verts]
    c = sum(pts, Vector()) / n
    if normal is None:
        normal = _newell(pts)
    normal = normal.copy()
    if normal.length < 1e-12:
        return None
    normal.normalize()
    if ref is not None and ref.length > 1e-12 and normal.dot(ref) < 0:
        normal.negate()
    flat = [p - normal * (p - c).dot(normal) for p in pts]
    radius = sum((p - c).length for p in flat) / n + radial_offset
    u = flat[0] - c
    if u.length < 1e-12:
        u = next(((p - c) for p in flat if (p - c).length > 1e-12), None)
        if u is None:
            return None
    u.normalize()
    w = normal.cross(u)
    ang = [math.atan2((p - c).dot(w), (p - c).dot(u)) for p in flat]
    if even and keep_lowest:
        turn = sum(math.remainder(ang[(i + 1) % n] - ang[i], math.tau) for i in range(n))
        step = (1.0 if turn >= 0 else -1.0) * math.tau / n
        ang = [ang[0] + step * i for i in range(n)]
    elif even:
        turn = sum(math.remainder(ang[(i + 1) % n] - ang[i], math.tau) for i in range(n))
        s = 1.0 if turn >= 0 else -1.0
        step = s * math.tau / n
        off_x = sum(math.cos(ang[i] - step * i) for i in range(n))
        off_y = sum(math.sin(ang[i] - step * i) for i in range(n))
        off = math.atan2(off_y, off_x)
        ang = [off + step * i for i in range(n)]
    for v, t in zip(verts, ang):
        t += twist
        v.co = c + (u * math.cos(t) + w * math.sin(t)) * radius
    return normal


def _newell(pts):
    from mathutils import Vector
    n = Vector()
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        n += Vector(((a.y - b.y) * (a.z + b.z), (a.z - b.z) * (a.x + b.x), (a.x - b.x) * (a.y + b.y)))
    return n


def _index_order_normal(verts):
    """Maya's circle normal for an edge loop: the vertices in index order (not loop order, no wrap-around); each
    neighbouring pair adds cross(a - c, b - c) about the centroid ``c``, except a term pointing 90 degrees or more
    away from the sum so far."""
    from mathutils import Vector
    vs = sorted(verts, key=lambda v: v.index)
    c = sum((v.co for v in vs), Vector()) / len(vs)
    n = Vector()
    for a, b in zip(vs, vs[1:]):
        t = (a.co - c).cross(b.co - c)
        if n.length == 0.0 or n.dot(t) > 0.0:
            n += t
    return n


def _face_regions(faces):
    """The selected faces in groups joined by edges."""
    left, out = set(faces), []
    while left:
        stack = [left.pop()]
        group = set(stack)
        while stack:
            f = stack.pop()
            for e in f.edges:
                for g in e.link_faces:
                    if g in left:
                        left.discard(g)
                        group.add(g)
                        stack.append(g)
        out.append(group)
    return out


def circularize_region(faces, loop, radial_offset=0.0, twist=0.0, even=True, ref=None):
    """Maya Circularize of a block of faces with one border loop (ordered vertices): the circle's centre is the mean
    of all the faces' vertices, its plane's normal the summed area normal of every face touching them (oriented like
    ``ref``), its radius the mean distance of the border vertices in that plane (+ ``radial_offset``). Spread evenly,
    the loop's lowest-index vertex keeps its angle; ``twist`` (radians) turns the loop right-handed about the normal.
    The inner vertices go onto the plane, scale about the centre with the radius and relax twice against the border
    before its even spacing (``_relax_inner``). Returns the normal or None."""
    from mathutils import Vector
    verts = {v for f in faces for v in f.verts}
    c = sum((v.co for v in verts), Vector()) / len(verts)
    around = {g for v in verts for g in v.link_faces}
    normal = sum((_newell([v.co for v in g.verts]) for g in around), Vector())
    if normal.length < 1e-12:
        return None
    normal.normalize()
    if ref is not None and ref.length > 1e-12 and normal.dot(ref) < 0:
        normal.negate()
    k = min(range(len(loop)), key=lambda i: loop[i].index)
    loop = loop[k:] + loop[:k]
    n = len(loop)
    flat = [v.co - normal * (v.co - c).dot(normal) for v in loop]
    base = sum((p - c).length for p in flat) / n
    radius = base + radial_offset
    u = flat[0] - c
    if u.length < 1e-12:
        return None
    u.normalize()
    w = normal.cross(u)
    ang = [math.atan2((p - c).dot(w), (p - c).dot(u)) for p in flat]
    own = list(ang)
    if even:
        turn = sum(math.remainder(ang[(i + 1) % n] - ang[i], math.tau) for i in range(n))
        step = (1.0 if turn >= 0 else -1.0) * math.tau / n
        ang = [ang[0] + step * i for i in range(n)]
    on_loop = set(loop)
    # The inner vertices settle against the border as it is before the even spacing: each border vertex at the
    # radius in its own direction (turned by the twist only when not spread evenly).
    for v, t in zip(loop, own):
        t += 0.0 if even else twist
        v.co = c + (u * math.cos(t) + w * math.sin(t)) * radius
    inner = [v for v in verts if v not in on_loop]
    k = radius / base if base > 1e-12 else 1.0
    for v in inner:                # onto the plane, scaled about the centre with the radius
        v.co = c + (v.co - normal * (v.co - c).dot(normal) - c) * k
    _relax_inner(inner)
    for v, t in zip(loop, ang):
        t += twist
        v.co = c + (u * math.cos(t) + w * math.sin(t)) * radius
    return normal


def _relax_inner(inner, passes=2):
    """Maya's relax of the inner vertices of a circularized block: two passes, each moving every inner vertex to
    the mean of its edge neighbours and then adding the mean of the neighbours' own moves away from where the
    pass started (neighbours on the border or outside the block count as not moving)."""
    from mathutils import Vector
    if not inner:
        return
    start = {v: v.co.copy() for v in inner}
    for _pass in range(passes):
        mean = {v: sum((e.other_vert(v).co for e in v.link_edges), Vector()) / len(v.link_edges) for v in inner}
        move = {v: mean[v] - start[v] for v in inner}
        for v in inner:
            near = [move[o] for o in (e.other_vert(v) for e in v.link_edges) if o in move]
            v.co = mean[v] + sum(near, Vector()) / len(v.link_edges)


def circularize_loops(bm, mode, normal_offset=0.0, radial_offset=0.0, twist=0.0, even=True, divisions=0):
    """The loops Maya circularizes for the current selection: faces -> their border loops, edges / vertices ->
    closed loops of selected edges ('EDGE' / 'VERT'; on both the lowest-index vertex keeps its angle; a vertex
    loop's plane is the summed area normal of every face touching it, an edge loop's comes from its vertices in
    index order, ``_index_order_normal``); ``mode`` 'ALL' = every border loop of the
    mesh. ``divisions`` first splits every
    loop edge (Maya Add Divisions: a 2-division octagon becomes 24 points, radius = their mean distance);
    ``normal_offset`` then moves the loop and the selected faces' inner vertices along the normal. A block of faces
    with one border loop goes through ``circularize_region``. Returns the loop count."""
    from mathutils import Vector

    def loop_edges():
        if mode == 'ALL':
            return [e for e in bm.edges if e.is_boundary]
        if mode == 'FACE':
            return [e for e in bm.edges if sum(f.select for f in e.link_faces) == 1]
        return [e for e in bm.edges if e.select]
    edges = loop_edges()
    if divisions > 0:
        loops0 = _ordered_loops(edges)
        on_loop = {e for lp in loops0 for i, v in enumerate(lp) for e in v.link_edges
                   if e.other_vert(v) is lp[(i + 1) % len(lp)]}
        # edge_split only adds vertices to the faces (subdivide_edges would cut corner patterns into them)
        for e in on_loop:
            a, b = e.verts
            cur, prev = e, a
            for k in range(divisions):
                _ne, nv = bmesh.utils.edge_split(cur, prev, 1.0 / (divisions + 1 - k))
                nv.select = True      # the split pieces keep the edge's selection (BM_edge_split copies it)
                cur = next(x for x in nv.link_edges if x.other_vert(nv) is b)
                prev = nv
        edges = loop_edges()
    bm.verts.index_update()      # circularize_region starts from the lowest-index border vertex
    loops = _ordered_loops(edges)
    faces = [f for f in bm.faces if f.select] if mode == 'FACE' else (list(bm.faces) if mode == 'ALL' else [])
    done = 0
    if mode == 'FACE':
        rest = []
        by_vert = {v: lp for lp in loops for v in lp}
        for region in _face_regions(faces):
            mine = []
            for f in region:
                for v in f.verts:
                    lp = by_vert.get(v)
                    if lp is not None and not any(lp is m for m in mine):
                        mine.append(lp)
            if len(mine) != 1:
                rest += [lp for lp in mine if not any(lp is r for r in rest)]
                continue
            ref = sum((f.normal for f in region), Vector())
            normal = circularize_region(region, mine[0], radial_offset, twist, even, ref)
            done += 1
            if normal is not None and normal_offset:
                for v in {v for f in region for v in f.verts}:
                    v.co += normal * normal_offset
        loops = rest
    for loop in loops:
        ref = Vector()
        for v in loop:
            for f in v.link_faces:
                if mode != 'FACE' or f.select:
                    ref += f.normal
        plane = None
        if mode == 'VERT':          # Maya on a vertex loop: the summed area normal of every face touching it
            plane = sum((_newell([v.co for v in g.verts]) for g in {g for v in loop for g in v.link_faces}), Vector())
        elif mode == 'EDGE':
            plane = _index_order_normal(loop)
        normal = circularize_loop(loop, radial_offset, twist, even, ref, plane, keep_lowest=mode in ('EDGE', 'VERT'))
        if normal is not None and normal_offset:
            inner = {v for f in faces for v in f.verts} if faces else set()
            for v in set(loop) | inner:
                v.co += normal * normal_offset
    return done + len(loops)


class ALLSET_OT_circularize(bpy.types.Operator):
    """Arrange the selected loop of components evenly on a circle (Maya Edit Mesh > Circularize)"""
    bl_idname = "allset.circularize"
    bl_label = "Circularize"
    bl_options = {'REGISTER', 'UNDO'}

    # Maya Polygon Circularize Options, default values
    normal_offset: bpy.props.FloatProperty(name="Normal Offset", default=0.0, subtype='DISTANCE', unit='LENGTH',
                                           options={'SKIP_SAVE'})
    radial_offset: bpy.props.FloatProperty(name="Radial Offset", default=0.0, subtype='DISTANCE', unit='LENGTH',
                                           options={'SKIP_SAVE'})
    twist: bpy.props.FloatProperty(name="Twist", default=0.0, subtype='ANGLE', options={'SKIP_SAVE'})
    evenly_distribute: bpy.props.BoolProperty(name="Evenly Distribute", default=True, options={'SKIP_SAVE'})
    divisions: bpy.props.IntProperty(name="Add Divisions", default=0, min=0, soft_max=10, max=100,
                                     options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        sel = context.tool_settings.mesh_select_mode
        mode = 'FACE' if sel[2] else ('VERT' if sel[0] and not sel[1] else 'EDGE')
        total = 0
        for ob in context.objects_in_mode:
            bm = bmesh.from_edit_mesh(ob.data)
            # the whole mesh selected (object-mode menu run, menu_map.OBJECT_MODE): every border loop
            total += circularize_loops(bm, 'ALL' if all(e.select for e in bm.edges) else mode,
                                       self.normal_offset, self.radial_offset, self.twist, self.evenly_distribute,
                                       self.divisions)
            bmesh.update_edit_mesh(ob.data)
        if not total:
            self.report({'WARNING'}, "Select a closed loop of edges or vertices, or faces")
            return {'CANCELLED'}
        return {'FINISHED'}


# --- Make Hole ---------------------------------------------------------------------------------

MERGE_MODES = ("First", "Middle", "Second", "Project First", "Project Middle", "Project Second", "None")


def _hole_merge(target, stamp, mode):
    """Maya Make Hole Merge mode (polyMergeFacet -mergeMode): First / Middle /
    Second move the stamp, both, or the cut face so their centres meet; Project ... moves along the normal only, onto
    the first face's plane, the middle plane, or the stamp's plane; None leaves both."""
    from mathutils import Vector
    ct, cs = target.calc_center_median(), stamp.calc_center_median()
    if mode in ("First", "Middle", "Second"):
        d = cs - ct
        move_t, move_s = {"First": (Vector(), -d), "Middle": (d / 2, -d / 2), "Second": (d, Vector())}[mode]
    elif mode in ("Project First", "Project Middle", "Project Second"):
        n = (target.normal if mode != "Project Second" else stamp.normal).normalized()
        h = (cs - ct).dot(n)
        move_t, move_s = {"Project First": (Vector(), -n * h), "Project Middle": (n * h / 2, -n * h / 2),
                          "Project Second": (n * h, Vector())}[mode]
    else:
        return
    for v in target.verts:
        v.co += move_t
    for v in stamp.verts:
        v.co += move_s


def make_hole(bm, target, stamp, merge_mode="None"):
    """Cut ``stamp``'s outline into ``target`` (Maya Make Hole; default merge mode None: the stamp keeps its position):
    both faces go, the two loops are bridged with quads. Returns the new faces."""
    _hole_merge(target, stamp, merge_mode)
    outer = list(target.edges)
    inner = list(stamp.edges)
    bmesh.ops.delete(bm, geom=[target, stamp], context='FACES_ONLY')
    res = bmesh.ops.bridge_loops(bm, edges=outer + inner)
    return res["faces"]


class ALLSET_OT_make_hole(bpy.types.Operator):
    """Cut the shape of the active (second) face as a hole into the other selected face of the same mesh
    (Maya Mesh Tools > Make Hole)"""
    bl_idname = "allset.make_hole"
    bl_label = "Make Hole"
    bl_options = {'REGISTER', 'UNDO'}

    merge_mode: bpy.props.EnumProperty(name="Merge mode", default="None", options={'SKIP_SAVE'},
                                       items=[(m, m, "") for m in MERGE_MODES])

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        ob = context.edit_object
        bm = bmesh.from_edit_mesh(ob.data)
        faces = [f for f in bm.faces if f.select]
        stamp = bm.faces.active if bm.faces.active in faces else None
        if len(faces) != 2 or stamp is None:
            self.report({'WARNING'}, "Select the face to cut, then the face whose shape makes the hole")
            return {'CANCELLED'}
        target = faces[0] if faces[1] is stamp else faces[1]
        if set(target.verts) & set(stamp.verts):
            self.report({'WARNING'}, "The two faces must not share vertices")
            return {'CANCELLED'}
        new = make_hole(bm, target, stamp, self.merge_mode)
        for f in new:
            f.select = True
        bmesh.update_edit_mesh(ob.data)
        return {'FINISHED'}


# --- Merge -------------------------------------------------------------------------------------
# Merge with the menu's default options (distance 0.01, always merge two vertices on):
# vertices closer than the threshold merge to the mean of their cluster; exactly two selected vertices merge to their
# midpoint whatever the distance (even across the mesh, then non-manifold). Edge / face selections: the threshold only.

MERGE_THRESHOLD = 0.01


def merge(bm, verts, threshold, always_two=True):
    """Merge ``verts`` the Maya way (``threshold`` in mesh units). Returns the number of vertices removed."""
    verts = list(verts)
    if len(verts) < 2:
        return 0
    if always_two and len(verts) == 2:
        clusters = {verts[0]: [verts[0], verts[1]]}
    else:
        tmap = bmesh.ops.find_doubles(bm, verts=verts, dist=threshold)["targetmap"]
        clusters = {}
        for v, t in tmap.items():
            clusters.setdefault(t, [t]).append(v)
    if not clusters:
        return 0
    from mathutils import Vector
    targetmap = {}
    for t, vs in clusters.items():
        vs = list(dict.fromkeys(vs))
        t.co = sum((v.co for v in vs), Vector()) / len(vs)
        for v in vs:
            if v is not t:
                targetmap[v] = t
    before = len(bm.verts)
    bmesh.ops.weld_verts(bm, targetmap=targetmap)
    return before - len(bm.verts)


def merge_selection(bm, mode, threshold, always_two=True):
    if mode == 'VERT':
        verts = [v for v in bm.verts if v.select]
    else:      # Maya sews border edges within the threshold; a closed mesh's edges stay
        verts = list({v for e in bm.edges if e.select and e.is_boundary for v in e.verts})
        always_two = False
    return merge(bm, verts, threshold, always_two)


def _merge_values():
    """The Merge option window's saved values (Maya runs the menu item with its option values)."""
    from . import option_windows
    v = option_windows.saved("merge") or {}
    return v.get("threshold", MERGE_THRESHOLD), v.get("always_two", True)


class ALLSET_OT_merge(bpy.types.Operator):
    """Merge the selected vertices closer than the threshold to their centre; two vertices always merge
    (Maya Edit Mesh > Merge)"""
    bl_idname = "allset.merge"
    bl_label = "Merge"
    bl_options = {'REGISTER', 'UNDO'}

    threshold: bpy.props.FloatProperty(name="Threshold", default=MERGE_THRESHOLD, min=0.0, soft_max=10.0,
                                       precision=4, options={'SKIP_SAVE'})
    always_two: bpy.props.BoolProperty(name="Always merge for two vertices", default=True, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        from . import units
        if not self.properties.is_property_set("threshold") and not self.properties.is_property_set("always_two"):
            self.threshold, self.always_two = _merge_values()
        dist = self.threshold * units.maya_unit(context.scene)
        sel = context.tool_settings.mesh_select_mode
        mode = 'VERT' if sel[0] else 'EDGE'
        done = 0
        for ob in context.objects_in_mode:
            bm = bmesh.from_edit_mesh(ob.data)
            done += merge_selection(bm, mode, dist, self.always_two)
            bmesh.update_edit_mesh(ob.data)
        if not done:
            results.result(self, "No vertices were merged")
        return {'FINISHED'}


classes = (ALLSET_OT_circularize, ALLSET_OT_connect, ALLSET_OT_make_hole, ALLSET_OT_merge, ALLSET_OT_smooth,
           ALLSET_OT_smooth_edit, ALLSET_OT_symmetrize, ALLSET_OT_average_vertices, ALLSET_OT_average_vertices_edit)
