# SPDX-License-Identifier: GPL-3.0-or-later
"""Issue #112: Maya Deform > Tension, Solidify, Sculpt (+ Paint Weights > Tension, Prune Membership >
Sculpt).

Like Maya: the nodes, names, selection, Channel Box rows and option windows of Tension, Solidify and Sculpt.
Blender has none of these deformers, so
each is a Geometry Nodes modifier named like the Maya node (``tension1``) on a shared node group built here (the
pattern of operators/wire_deformer.py); it reads its input from the modifiers above it (Maya: the upstream
deformers) and its weights from the vertex group of its name (weight 1 on the deformed points).
Maya's ``<shape>Orig`` (the rest shape Tension / Solidify compare with) is the mesh's base positions when the deformer
is made, kept in a hidden point attribute ``.allset_rest_<node>`` (component edits made later are Maya tweaks = input,
not rest); a topology change (Delete Non-Deformer History of a bevel, ...) re-takes it with the partner table.

- **Tension** (the node group repeats Maya's Jacobi passes in a
  Repeat zone): partner table per vertex = edge neighbours (strength 1), face diagonals (Shear Strength), bend partners
  (Bend Strength) as hidden INT point attributes ``.allset_tension_p<k>`` = partner · 8 + flags (1 edge, 2 diagonal,
  4 bend, -1 none), computed from the topology in Python (operators can't build variable lists in Geometry Nodes).
  Vertex normals = Maya's corner rule (cross(f[k+h] - p, f[k-h] - p), h = max(1, m // 2 - 1)), recomputed each pass.
- **Solidify**: membership = the vertex group (points selected at creation) picks
  the solid region; Full on the whole mesh = a rigid transform of the rest region onto the input with translation =
  input centroid; Borders on the whole mesh = nothing moves; a region's border ring stays (falloff on) / moves too
  (falloff off); envelope blends linearly. The kit's own model for the rest: the rotation is the least-squares
  (Kabsch / polar) fit, Stabilization Level n divides the angle by 1 + n/2 (Maya: level 2 halves it), the
  border falloff is Blender's Blur Attribute of the inside weights, Scale Mode Edge / Edge Global = uniform scale by
  the region's edge-length ratio (× Scale Envelope), Normal / Tangent Plane Scale scale the normal / tangent part.
- **Sculpt**: sculptor = an Empty ``sculptor1`` (display Sphere, radius 1 Maya unit: Maya's implicit sphere;
  delta scale = maya_unit so the Channel Box shows Maya's Scale 1) and ``sculpt1StretchOrigin`` (plain axes), both at
  the deformed points' bounding-box centre ("Center within selection"); the rule =
  the kit's model (Stretch / Even, Flip / Ring and Project at the sculptor work like Maya); Stretch with the origin
  moved off the sculptor, Flip / Even, Stretch / Ring, scaled sculptors and dropoff type None use the same rule, where
  Maya may differ. Maximum Displacement is a length (× maya_unit) in Stretch / Flip and a
  fraction in Project (Maya: the same attribute).

Delete Non-Deformer History keeps all three (history.is_deformer: every kit deformer in deformers.BASES); Delete
History bakes them. The Maya names / node types / Channel Box rows join deformers.BASES / ATTRS at register.

Code: tension_solidify_sculpt_nodes (the three node groups, kind_of); this module keeps creation, the Tension
partner table and rest positions with their depsgraph handler, Prune Membership > Sculpt, the Channel Box / AE rows,
menu paths and option windows.
"""


import bpy
from bpy.app.handlers import persistent
from bpy.props import EnumProperty
from mathutils import Vector

from .. import results, undo_steps
from .. import update_summary
from . import deformers, units, wire_deformer
from .. import i18n
from .tension_solidify_sculpt_nodes import (VERSION_PROP, VERSION, GROUPS, SLOT, SLOT_COUNT,  # noqa: F401
                                            TENSION_INPUTS, SOLIDIFY_INPUTS, SCULPT_INPUTS, INPUTS, build_tension,
                                            build_sculpt, build_solidify, BUILDERS, group, kind_of)

REST = ".allset_rest_"               # + node name: rest (Maya <shape>Orig) positions
TOPO_PROP = "allset_205a_topo"       # mesh: (verts, edges, loops) the partner table / rest were taken from


# --- topology tables / rest ---------------------------------------------------------------------------------------

def partners(faces, n):
    """[[(partner, flags)]] per vertex: edge neighbours (flag 1), then face diagonals (2) / bend partners (4) — the
    sets of the tension model (diagonals, bend_partners)."""
    nb = [set() for _ in range(n)]
    edge_faces = {}
    for fi, f in enumerate(faces):
        for k in range(len(f)):
            a, c = f[k], f[(k + 1) % len(f)]
            nb[a].add(c)
            nb[c].add(a)
            edge_faces.setdefault((min(a, c), max(a, c)), set()).add(fi)
    dg = [set() for _ in range(n)]
    for f in faces:
        for v in f:
            for u in f:
                if u != v and u not in nb[v]:
                    dg[v].add(u)
    bp = [set() for _ in range(n)]
    for f in faces:
        for k in range(2, len(f) - 1):
            bp[f[0]].add(f[k])
            bp[f[k]].add(f[0])
    for i in range(n):
        for j in nb[i]:
            fij = edge_faces[(min(i, j), max(i, j))]
            for k in nb[j]:
                if k != i and not (edge_faces[(min(j, k), max(j, k))] & fij):
                    bp[i].add(k)
    out = []
    for i in range(n):
        row = [(j, 1) for j in sorted(nb[i])]
        row += [(j, (2 if j in dg[i] else 0) | (4 if j in bp[i] else 0)) for j in sorted(dg[i] | bp[i])]
        out.append(row)
    return out


def _signature(me):
    return [len(me.vertices), len(me.edges), len(me.loops)]


def write_partners(me):
    """The tension partner table of ``me`` as hidden INT point attributes."""
    n = len(me.vertices)
    rows = partners([list(p.vertices) for p in me.polygons], n)
    width = max((len(r) for r in rows), default=0)
    for a in [a.name for a in me.attributes if a.name.startswith(SLOT)]:     # names first: removing shifts them
        me.attributes.remove(me.attributes[a])
    if SLOT_COUNT in me.attributes:
        me.attributes.remove(me.attributes[SLOT_COUNT])
    cnt = me.attributes.new(SLOT_COUNT, 'INT', 'POINT')
    cnt.data.foreach_set("value", [len(r) for r in rows])
    for k in range(width):
        a = me.attributes.new(f"{SLOT}{k}", 'INT', 'POINT')
        a.data.foreach_set("value", [r[k][0] * 8 + r[k][1] if k < len(r) else -1 for r in rows])


def write_rest(me, node):
    """``.allset_rest_<node>`` = the mesh's base positions (Maya's <shape>Orig)."""
    name = REST + node
    if name in me.attributes:
        me.attributes.remove(me.attributes[name])
    a = me.attributes.new(name, 'FLOAT_VECTOR', 'POINT')
    co = [0.0] * (3 * len(me.vertices))
    me.vertices.foreach_get("co", co)
    a.data.foreach_set("vector", co)


def sync(ob):
    """After a topology change (or on a mesh without the tables): partner table and rest positions again; tables of
    removed deformers are dropped. Returns True when the mesh was written."""
    if ob.type != 'MESH' or ob.mode == 'EDIT' or ob.data is None:
        return False
    me = ob.data
    mds = [(md, kind_of(md)) for md in ob.modifiers]
    mds = [(md, k) for md, k in mds if k in ("tension", "solidify")]
    sig = _signature(me)
    changed = list(me.get(TOPO_PROP, [])) != sig
    wrote = False
    if any(k == "tension" for _m, k in mds) and (changed or SLOT_COUNT not in me.attributes):
        write_partners(me)
        wrote = True
    if not any(k == "tension" for _m, k in mds) and SLOT_COUNT in me.attributes:
        for a in [a.name for a in me.attributes if a.name.startswith(SLOT) or a.name == SLOT_COUNT]:
            me.attributes.remove(me.attributes[a])
        wrote = True
    wanted = {REST + md.name for md, _k in mds}
    for md, _k in mds:
        if changed or REST + md.name not in me.attributes:
            write_rest(me, md.name)
            _attr_input(md, "Rest", REST + md.name)
            wrote = True
    for a in [a.name for a in me.attributes if a.name.startswith(REST) and a.name not in wanted]:
        me.attributes.remove(me.attributes[a])
        wrote = True
    if mds and changed:
        me[TOPO_PROP] = sig
    elif not mds and TOPO_PROP in me:
        del me[TOPO_PROP]
    return wrote


def _attr_input(md, name, attribute):
    from .. import compat
    compat.gn_input_attribute(md, wire_deformer.ident(md, name), attribute)


# --- creation ---------------------------------------------------------------------------------------------------

DEFAULTS = {
    # Tension Options (default values)
    'TENSION': {"iterations": 10, "step": 0.5, "pin_border": True, "relative": 0.0, "inward": 0.0, "outward": 0.0,
                "squash": 1.0, "stretch": 1.0, "shear": 0.0, "bend": 0.0},
    # Solidify Options (default values)
    'SOLIDIFY': {"attachment": "Borders", "stabilization": 0, "border_falloff": True, "falloff_iterations": 2},
    # Sculpt Options (default values)
    'SCULPT': {"mode": "Stretch", "inside_mode": "Even", "max_displacement": 0.1, "dropoff_type": "Linear",
               "dropoff_distance": 1.0, "centered": True},
}
SCULPT_MODES = ("Flip", "Project", "Stretch")      # Maya enum 0 / 1 / 2
INSIDE_MODES = ("Ring", "Even")
DROPOFF_TYPES = ("None", "Linear")


def _meshes(context):
    items = [(ob, idx) for ob, idx in deformers._deformed(context) if ob.type == 'MESH']
    if not items:
        raise RuntimeError("Select a mesh to deform.")
    return items


def _add_node(ob, name, kind, idx):
    """The GN modifier ``name`` + its weights vertex group (weight 1 on the deformed points)."""
    vg = deformers._weights(ob, name, idx)
    md = ob.modifiers.new(name, 'NODES')
    md.node_group = group(kind)
    _attr_input(md, "Weight", vg)
    if kind in ("tension", "solidify"):
        sync(ob)
    return md


def _set(md, values):
    for key, v in values.items():
        wire_deformer.set_(md, key, v)


def _tension(context, v):
    items = _meshes(context)
    name = deformers.new_name("tension")
    for ob, idx in items:
        md = _add_node(ob, name, "tension", idx)
        _set(md, {"Smoothing Iterations": int(v["iterations"]), "Smoothing Step": float(v["step"]),
                  "Pin Border Vertices": bool(v["pin_border"]), "Relative": float(v["relative"]),
                  "Inward Constraint": float(v["inward"]), "Outward Constraint": float(v["outward"]),
                  "Squash Constraint": float(v["squash"]), "Stretch Constraint": float(v["stretch"]),
                  "Shear Strength": float(v["shear"]), "Bend Strength": float(v["bend"])})
    obs = [ob for ob, _i in items]
    deformers._select_only(context, obs, obs[0])                 # Maya: pCube1, tension1
    return obs[0]


def _solidify(context, v):
    items = _meshes(context)
    name = deformers.new_name("solidify")
    for ob, idx in items:
        md = _add_node(ob, name, "solidify", idx)
        _set(md, {"Attachment Mode": 1 if v["attachment"] == "Full" else 0,
                  "Stabilization Level": int(v["stabilization"]), "Use Border Falloff": bool(v["border_falloff"]),
                  "Border Falloff Blur": int(v["falloff_iterations"])})
    obs = [ob for ob, _i in items]
    deformers._select_only(context, obs, obs[0])                 # Maya: pCube1, solidify1
    return obs[0]


def _sculpt(context, v):
    items = _meshes(context)
    lo, hi = deformers._bounds(items)
    name = deformers.new_name("sculpt")
    u = units.maya_unit(context.scene)
    n = 1
    taken = {o.name for o in bpy.data.objects}
    while f"sculptor{n}" in taken:
        n += 1
    centre = (lo + hi) / 2 if v["centered"] else Vector()
    sculptor = deformers._link(context, bpy.data.objects.new(f"sculptor{n}", None))
    sculptor.empty_display_type = 'SPHERE'          # Maya implicitSphere sphereShape1, radius 1
    sculptor.empty_display_size = 1.0
    origin = deformers._link(context, bpy.data.objects.new(f"{name}StretchOrigin", None))
    origin.empty_display_type = 'PLAIN_AXES'
    origin.empty_display_size = 1.0
    for e in (sculptor, origin):
        e.delta_scale = (u, u, u)                   # Maya units: Channel Box Scale 1 (like ffd1Lattice)
        e.location = centre
    context.view_layer.update()
    for ob, idx in items:
        md = _add_node(ob, name, "sculpt", idx)
        _set(md, {"Sculptor": sculptor, "Stretch Origin": origin, "Mode": SCULPT_MODES.index(v["mode"]),
                  "Inside Mode": INSIDE_MODES.index(v["inside_mode"]),
                  "Maximum Displacement": float(v["max_displacement"]),
                  "Dropoff Type": DROPOFF_TYPES.index(v["dropoff_type"]),
                  "Dropoff Distance": float(v["dropoff_distance"]), "Unit": float(u)})
    deformers._select_only(context, [sculptor], sculptor)       # Maya: sculptor1
    return sculptor


def create(context, kind, values=None):
    """Make Maya deformer ``kind`` (TENSION / SOLIDIFY / SCULPT) on the selection with ``values`` (option window
    values; missing = the default). Raises RuntimeError with a Maya-style message when the selection doesn't fit."""
    v = {**DEFAULTS[kind], **(values or {})}
    return {'TENSION': _tension, 'SOLIDIFY': _solidify, 'SCULPT': _sculpt}[kind](context, v)


KINDS = tuple((k, k.title(), "") for k in DEFAULTS)


class ALLSET_OT_deformer_tss(bpy.types.Operator):
    """Make a Maya Tension / Solidify / Sculpt deformer on the selection (Maya Deform menu)"""
    bl_idname = "allset.deformer_tss"
    bl_label = "Create Deformer"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(items=KINDS, name="Deformer", options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, properties):
        return {'TENSION': "Keep the edge lengths of the deformed mesh (Maya Deform > Tension)",
                'SOLIDIFY': "Keep a region of the deformed mesh rigid (Maya Deform > Solidify)",
                'SCULPT': "Push the mesh with a sphere (Maya Deform > Sculpt)"}.get(properties.kind, "")

    def execute(self, context):
        from . import option_windows
        window = next((w for w in option_windows.WINDOWS if w.match == (self.bl_idname, {"kind": self.kind})), None)
        values = option_windows.saved(window.key) if window is not None else None
        try:
            create(context, self.kind, values)
        except RuntimeError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


# --- Prune Membership > Sculpt -------------------------------------------------------------------------------------

def sculpt_targets(context):
    """[(mesh object, sculpt modifier)] for the selection: selected meshes' sculpt nodes, and the nodes a selected
    sculptor / stretch origin drives."""
    sel = set(context.selected_objects) | ({context.active_object} if context.active_object else set())
    out = []
    for ob in bpy.data.objects:
        for md in getattr(ob, "modifiers", ()):
            if kind_of(md) != "sculpt":
                continue
            if ob in sel or wire_deformer.get(md, "Sculptor") in sel or wire_deformer.get(md, "Stretch Origin") in sel:
                out.append((ob, md))
    return out


def sculpt_influence(md, points, ob_matrix):
    """Indices of ``points`` (object space) the sculpt node can move (weights and envelope aside): inside the sphere,
    or within the dropoff distance of it (Project: of its radial surface point)."""
    get = wire_deformer.get
    sculptor = get(md, "Sculptor")
    if sculptor is None:
        return set()
    M = ob_matrix.inverted() @ sculptor.matrix_world
    Minv = M.inverted()
    dd = float(get(md, "Dropoff Distance")) * float(get(md, "Unit"))
    linear = int(get(md, "Dropoff Type")) == 1
    project = int(get(md, "Mode")) == 1
    out = set()
    for i, p in enumerate(points):
        q = Minv @ p
        rq = q.length
        if rq < 1.0 or not linear and project:
            out.add(i)
            continue
        if project:
            dist = (p - M @ (q / rq)).length
            if dist <= dd:
                out.add(i)
            continue
        dist = (rq - 1.0) * (M.to_3x3() @ (q / rq)).length
        if (dist < dd) if linear else (dist <= dd):
            out.add(i)
    return out


def _input_points(context, ob, md):
    """Object-space positions the modifier ``md`` receives (the modifiers above it evaluated)."""
    shown = {m.name: m.show_viewport for m in ob.modifiers}
    after = False
    for m in ob.modifiers:
        if m == md:
            after = True
        if after:
            m.show_viewport = False
    try:
        dg = context.evaluated_depsgraph_get()
        dg.update()
        me = ob.evaluated_get(dg).to_mesh()
        pts = [v.co.copy() for v in me.vertices]
        ob.evaluated_get(dg).to_mesh_clear()
    finally:
        for m in ob.modifiers:
            m.show_viewport = shown[m.name]
    if len(pts) != len(ob.data.vertices):
        pts = [v.co.copy() for v in ob.data.vertices]
    return pts


def prune_sculpt(context):
    """Maya ``cmds.sculpt(edit=True, prune=True)``: the points the sculptor can't reach leave the node's vertex group.
    Returns the count."""
    n = 0
    for ob, md in sculpt_targets(context):
        vg = ob.vertex_groups.get(md.name)
        if vg is None:
            continue
        keep = sculpt_influence(md, _input_points(context, ob, md), ob.matrix_world)
        drop = [v.index for v in ob.data.vertices if v.index not in keep
                and any(g.group == vg.index for g in v.groups)]
        if drop:
            vg.remove(drop)
            n += len(drop)
    return n


@undo_steps.no_redo_panel
class ALLSET_OT_prune_sculpt(bpy.types.Operator):
    """Remove the points the sculptor can't reach from the sculpt deformer (Maya Deform > Prune Membership > Sculpt)"""
    bl_idname = "allset.prune_sculpt"
    bl_label = "Prune Membership"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from . import deform_edit
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if not sculpt_targets(context):
            self.report({'WARNING'}, "Select a sculpt deformer, its sculptor or the deformed object.")
            return {'CANCELLED'}
        n = prune_sculpt(context)
        if not n:
            results.result(self, deform_edit.PRUNE_NONE)
            return {'CANCELLED'}
        results.result(self, f"{n} points pruned")
        return {'FINISHED'}


classes = (ALLSET_OT_deformer_tss, ALLSET_OT_prune_sculpt)


# --- Maya names / Channel Box rows (joined into deformers.BASES / ATTRS at register) ----------------------------------

def _gn(name, cast=float):
    def get(md):
        v = wire_deformer.get(md, name)
        return cast(v) if v is not None else cast(0)

    def set_(md, v):
        wire_deformer.set_(md, name, cast(v))
    return get, set_


def _attrs(rows):
    return [deformers.Attr(key, label, kind, *_gn(name, int if kind == "INT" else bool if kind == "BOOL" else float))
            for key, label, kind, name in rows]


BASES = {"tension": ('NODES', "tension"), "solidify": ('NODES', "solidify"), "sculpt": ('NODES', "sculpt")}
# keyable rows (Channel Box INPUTS), default order
ATTR_ROWS = {
    "tension": [("envelope", "Envelope", "NONE", "Envelope"),
                ("smoothingIterations", "Smoothing Iterations", "INT", "Smoothing Iterations"),
                ("smoothingStep", "Smoothing Step", "NONE", "Smoothing Step"),
                ("inwardConstraint", "Inward Constraint", "NONE", "Inward Constraint"),
                ("outwardConstraint", "Outward Constraint", "NONE", "Outward Constraint"),
                ("squashConstraint", "Squash Constraint", "NONE", "Squash Constraint"),
                ("stretchConstraint", "Stretch Constraint", "NONE", "Stretch Constraint"),
                ("relative", "Relative", "NONE", "Relative")],
    "solidify": [("envelope", "Envelope", "NONE", "Envelope"), ("normalScale", "Normal Scale", "NONE", "Normal Scale"),
                 ("tangentPlaneScale", "Tangent Plane Scale", "NONE", "Tangent Plane Scale"),
                 ("scaleEnvelope", "Scale Envelope", "NONE", "Scale Envelope")],
    "sculpt": [("envelope", "Envelope", "NONE", "Envelope"),
               ("maximumDisplacement", "Maximum Displacement", "NONE", "Maximum Displacement"),
               ("dropoffDistance", "Dropoff Distance", "NONE", "Dropoff Distance")],
}

# AE "<Type> Attributes": the keyable rows, then the node's other attributes
AE_EXTRA = {"tension": ("Shear Strength", "Bend Strength", "Pin Border Vertices"),
            "solidify": ("Attachment Mode", "Stabilization Level", "Use Border Falloff", "Border Falloff Blur",
                         "Scale Mode"),
            "sculpt": ("Mode", "Inside Mode", "Dropoff Type", "Sculptor", "Stretch Origin")}


def _draw_input(layout, md, socket, label):
    from .. import compat
    key = wire_deformer.ident(md, socket)
    if key is None:
        return
    if compat.GN_INPUT_STRUCT:
        item = compat._gn_input(md, key)
        if item is not None:
            layout.prop(item, "value", text=label)
        return
    layout.prop(md, f'["{key}"]', text=label)


def draw_ae(layout, md):
    """Draw a Tension / Solidify / Sculpt node's Maya attributes in its AE tab; False for other modifiers."""
    kind = kind_of(md)
    if kind is None or deformers.base_of(md) != kind:
        return False
    for _key, label, _k, socket in ATTR_ROWS[kind]:
        _draw_input(layout, md, socket, label)
    for socket in AE_EXTRA[kind]:
        _draw_input(layout, md, socket, socket)
    return True


# Maya menu paths -> kit actions (merged into ui/menu_map.py)
MENU = {
    "Deform/Tension": ("allset.deformer_tss", {"kind": 'TENSION'}),
    "Deform/Solidify": ("allset.deformer_tss", {"kind": 'SOLIDIFY'}),
    "Deform/Sculpt": ("allset.deformer_tss", {"kind": 'SCULPT'}),
    "Deform/Paint Weights/Tension": ("allset.paint_deformer_weights", {"kind": "tension"}),
    "Deform/Prune Membership/Sculpt": "allset.prune_sculpt",
}


# --- Maya option windows (appended by operators/option_windows._extend) ----------------------------------------------

def _windows():
    from .option_windows import F, Window
    from .option_windows_deform import ADVANCED

    def run(kind):
        def go(context, v):
            create(context, kind, v)
            return {'FINISHED'}
        return go
    match = "allset.deformer_tss"
    return [
        # Tension Options: Create / Apply / Close
        Window("deform_tension", "Tension Options", "Create", (match, {"kind": 'TENSION'}), [
            F("iterations", "Smoothing iterations:", "int", 10, lo=0, hi=100),
            F("step", "Smoothing step:", "float", 0.5, lo=0.0, hi=1.0),
            F("pin_border", "", "bool", True, text="Pin border vertices"),
            F("relative", "Relative:", "float", 0.0, lo=0.0, hi=1.0),
            F("inward", "Inward constraint:", "float", 0.0, lo=0.0, hi=1.0, heading="Constraints"),
            F("outward", "Outward constraint:", "float", 0.0, lo=0.0, hi=1.0),
            F("squash", "Squash constraint:", "float", 1.0, lo=0.0, hi=1.0),
            F("stretch", "Stretch constraint:", "float", 1.0, lo=0.0, hi=1.0),
            F("shear", "Shear strength:", "float", 0.0, lo=0.0, hi=1.0),
            F("bend", "Bend strength:", "float", 0.0, lo=0.0, hi=1.0)], run('TENSION'),
            paths=("Deform/Tension",), missing=ADVANCED),
        # Solidify Options
        Window("deform_solidify", "Solidify Options", "Create", (match, {"kind": 'SOLIDIFY'}), [
            F("attachment", "Attachment mode:", "enum", "Borders", items=("Borders", "Full")),
            F("stabilization", "Stabilization Level:", "int", 0, lo=0, hi=100),
            F("border_falloff", "", "bool", True, text="Use border falloff"),
            F("falloff_iterations", "Falloff iterations:", "int", 2, lo=0, hi=100)], run('SOLIDIFY'),
            paths=("Deform/Solidify",), missing=ADVANCED),
        # Sculpt Options (default values)
        Window("deform_sculpt", "Sculpt Options", "Create", (match, {"kind": 'SCULPT'}), [
            F("mode", "Mode:", "enum", "Stretch", items=SCULPT_MODES),
            F("inside_mode", "Inside mode:", "enum", "Even", items=INSIDE_MODES),
            F("max_displacement", "Max displacement:", "float", 0.1, lo=0.0, hi=10.0),
            F("dropoff_type", "Dropoff type:", "enum", "Linear", items=DROPOFF_TYPES),
            F("dropoff_distance", "Dropoff distance:", "float", 1.0, lo=0.0, hi=20.0),
            F("centered", "", "bool", True, text="Center within selection", heading="Positioning")], run('SCULPT'),
            paths=("Deform/Sculpt",),
            missing=("Group sculptor with locator (the sculptor and its origin stay separate Empties)",
                     "Use secondary NURBS or polygon object (the sculptor is a sphere)")),
    ]


WINDOWS = []          # filled by windows() when option_windows._extend asks (avoids an import cycle at load)


def windows():
    if not WINDOWS:
        WINDOWS.extend(_windows())
        # Deform > Paint Weights > Tension ❒ = Maya's Paint Attributes Tool, like the other Paint Weights boxes
        from .option_windows import Window
        from .option_windows_deform import PAINT_FIELDS, PAINT_MISSING, _paint
        WINDOWS.append(Window("paint_weights_tension", "Paint Attributes Tool", "Paint", None, PAINT_FIELDS(),
                              _paint("tension"), paths=("Deform/Paint Weights/Tension",), missing=PAINT_MISSING))
    return WINDOWS


# --- register --------------------------------------------------------------------------------------------------------

@persistent
def _on_depsgraph(scene, depsgraph):
    seen = set()
    obs = []
    for upd in update_summary.updates(depsgraph, _on_depsgraph):
        idb = getattr(upd.id, "original", upd.id)
        if isinstance(idb, bpy.types.Object):
            obs.append(idb)
        elif isinstance(idb, bpy.types.Mesh):          # a new / replaced mesh (Delete History swaps ob.data)
            obs.extend(o for o in scene.objects if o.data == idb)
    for ob in obs:
        if ob.type != 'MESH' or ob.name in seen:
            continue
        seen.add(ob.name)
        me = ob.data
        if (any(kind_of(md) in ("tension", "solidify") for md in ob.modifiers) or TOPO_PROP in me
                or SLOT_COUNT in me.attributes or any(a.name.startswith(REST) for a in me.attributes)):
            update_summary.wrote()
            try:
                sync(ob)
            except (AttributeError, ReferenceError, RuntimeError):
                pass


def register_handlers():
    deformers.BASES.update(BASES)
    deformers.ATTRS.update({k: _attrs(rows) for k, rows in ATTR_ROWS.items()})
    if _on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)


def unregister_handlers():
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    for k in BASES:
        deformers.BASES.pop(k, None)
        deformers.ATTRS.pop(k, None)
