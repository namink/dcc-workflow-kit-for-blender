# SPDX-License-Identifier: GPL-3.0-or-later
"""Create > Sweep Mesh as a live node: ``sweepMeshCreator1`` (issue #238).

Maya's Sweep Mesh keeps a ``sweepMeshCreator`` node between the curve and the mesh: its profile (Poly / Rectangle /
Line / Arc / Wave and their sizes), the profile's scale / rotation / offset, twist, taper, caps and the interpolation
along the curve stay editable in the Attribute Editor and the Channel Box INPUTS, and editing the curve updates the
mesh. Blender has no such node, so the kit's ``sweep1`` is a mesh object whose shape comes from a Geometry Nodes
modifier named like the Maya node (``sweepMeshCreator1``) on a shared node group built here:

    Object Info (the curve, relative) -> interpolation (Index Switch of four resamplings) -> radius = taper ramp,
    tilt += twist ramp -> Curve to Mesh with the profile (Index Switch of five profile curves, scaled / turned /
    moved) -> Flip Faces (Reverse Normals)

The modifier ignores the object's own mesh, so ``sweep1`` sits at the origin and the curve is read in that space:
moving / editing the curve moves the sweep, moving ``sweep1`` moves it on top. Profile sizes are in Maya units
(``Unit`` = the scene's Maya unit). Delete History bakes the mesh (it is history, not a deformer); deleting the curve
bakes every sweep it drives first, so the mesh stays like in Maya. With Construction History off the mesh is baked
at once.

Interpolation (the rings along the curve): Start to End = Steps segments over the whole curve; EP to EP = Steps
segments per span (Blender evaluates a NURBS span in ``resolution`` segments); Distance = one ring per Distance;
Precision = more segments per span as the value rises (1 + Precision / 10, rounded up).
"""

import bpy

from .. import compat
from . import deformers, units, wire_deformer

GROUP = ".Allset Sweep Mesh"
VERSION_PROP = "allset_sweep_version"
VERSION = 1
NODE = "sweepMeshCreator"
FINE = 16                      # evaluated segments per span before an even resampling

PROFILES = ("Poly", "Rectangle", "Line", "Arc", "Wave")
POLY_TYPES = ("Circle", "Star")
INTERPOLATIONS = ("Start to End", "EP to EP", "Distance", "Precision")
ENUMS = {"Profile Type": PROFILES, "Poly Type": POLY_TYPES, "Interpolation Mode": INTERPOLATIONS}

# (socket, socket type, default, min, max): angles in degrees, lengths in Maya units
INPUTS = (
    ("Curve", 'NodeSocketObject', None, None, None),
    ("Unit", 'NodeSocketFloat', 1.0, 0.0, None),
    ("Profile Type", 'NodeSocketInt', 0, 0, len(PROFILES) - 1),
    ("Poly Type", 'NodeSocketInt', 0, 0, len(POLY_TYPES) - 1),
    ("Poly Sides", 'NodeSocketInt', 8, 3, 256),
    ("Poly Radius", 'NodeSocketFloat', 1.0, 0.0, None),
    ("Inner Radius", 'NodeSocketFloat', 0.5, 0.0, None),
    ("Rectangle Width", 'NodeSocketFloat', 2.0, 0.0, None),
    ("Rectangle Height", 'NodeSocketFloat', 2.0, 0.0, None),
    ("Corner Radius", 'NodeSocketFloat', 0.0, 0.0, None),
    ("Corner Segments", 'NodeSocketInt', 4, 1, 64),
    ("Line Length", 'NodeSocketFloat', 2.0, 0.0, None),
    ("Arc Angle", 'NodeSocketFloat', 180.0, 1.0, 360.0),
    ("Arc Radius", 'NodeSocketFloat', 1.0, 0.0, None),
    ("Arc Segments", 'NodeSocketInt', 8, 1, 256),
    ("Wave Amplitude", 'NodeSocketFloat', 0.25, None, None),
    ("Wave Cycles", 'NodeSocketFloat', 2.0, 0.0, None),
    ("Wave Offset", 'NodeSocketFloat', 0.0, None, None),
    ("Wave Length", 'NodeSocketFloat', 2.0, 0.0, None),
    ("Wave Segments", 'NodeSocketInt', 16, 1, 512),
    ("Scale Profile", 'NodeSocketFloat', 1.0, 0.0, None),
    ("Scale Profile X", 'NodeSocketFloat', 1.0, None, None),
    ("Scale Profile Y", 'NodeSocketFloat', 1.0, None, None),
    ("Rotate Profile", 'NodeSocketFloat', 0.0, None, None),
    ("Translate Profile X", 'NodeSocketFloat', 0.0, None, None),
    ("Translate Profile Y", 'NodeSocketFloat', 0.0, None, None),
    ("Twist", 'NodeSocketFloat', 0.0, None, None),
    ("Taper", 'NodeSocketFloat', 1.0, None, None),
    ("Interpolation Mode", 'NodeSocketInt', 1, 0, len(INTERPOLATIONS) - 1),
    ("Interpolation Steps", 'NodeSocketInt', 5, 1, 1000),
    ("Interpolation Precision", 'NodeSocketFloat', 75.0, 0.0, 100.0),
    ("Interpolation Distance", 'NodeSocketFloat', 1.0, 0.0001, None),
    ("Caps", 'NodeSocketBool', False, None, None),
    ("Reverse Normals", 'NodeSocketBool', False, None, None),
)
DEFAULTS = {name: default for name, _t, default, _lo, _hi in INPUTS if default is not None}


# --- node group -------------------------------------------------------------------------------------------------

def _menu(node, socket, prop, value, prop_value):
    """Set a node option that Blender keeps as a menu socket (5.x) or a node property."""
    s = node.inputs.get(socket)
    if s is not None and s.bl_idname == 'NodeSocketMenu':
        s.default_value = value
    else:
        setattr(node, prop, prop_value)


class _B(wire_deformer._B):
    def switch(self, kind, cond, false, true):
        n = self.node("GeometryNodeSwitch", input_type=kind)
        self._in(n.inputs["Switch"], cond)
        self._in(n.inputs["False"], false)
        self._in(n.inputs["True"], true)
        return n.outputs[0]

    def index_switch(self, index, items, kind='GEOMETRY'):
        n = self.node("GeometryNodeIndexSwitch", data_type=kind)
        while len(n.index_switch_items) < len(items):
            n.index_switch_items.new()
        self._in(n.inputs["Index"], index)
        for i, v in enumerate(items):
            self._in(n.inputs[i + 1], v)
        return n.outputs[0]

    def combine(self, x, y, z):
        n = self.node("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self._in(n.inputs[i], v)
        return n.outputs[0]

    def factor(self):
        return self.node("GeometryNodeSplineParameter").outputs["Factor"]

    def resolution(self, curve, res):
        n = self.node("GeometryNodeSetSplineResolution")
        self.link(curve, n.inputs["Curve"])
        self._in(n.inputs["Resolution"], res)
        return n.outputs[0]

    def resample(self, curve, mode, count=None, length=None):
        n = self.node("GeometryNodeResampleCurve")
        _menu(n, "Mode", "mode", mode.title(), mode.upper())
        self.link(curve, n.inputs["Curve"])
        if count is not None:
            self._in(n.inputs["Count"], count)
        if length is not None:
            self._in(n.inputs["Length"], length)
        return n.outputs[0]

    def set_position(self, geo, offset=None, position=None):
        n = self.node("GeometryNodeSetPosition")
        self.link(geo, n.inputs["Geometry"])
        if offset is not None:
            self._in(n.inputs["Offset"], offset)
        if position is not None:
            self._in(n.inputs["Position"], position)
        return n.outputs[0]

    def position(self):
        return self.node("GeometryNodeInputPosition").outputs[0]


def _profiles(b, I):                          # noqa: E741
    """The five profile curves (Maya units, in the XY plane, centred on the origin)."""
    # Poly: a circle of Poly Sides points; Star = twice the points, every second one at Inner Radius
    star = b.math('GREATER_THAN', I["Poly Type"], 0.5)
    circle = b.node("GeometryNodeCurvePrimitiveCircle")
    b._in(circle.inputs["Resolution"], b.math('MULTIPLY', I["Poly Sides"], b.math('ADD', star, 1.0)))
    b._in(circle.inputs["Radius"], I["Poly Radius"])
    odd = b.math('FLOORED_MODULO', b.node("GeometryNodeInputIndex").outputs[0], 2.0)
    inner = b.math('DIVIDE', I["Inner Radius"], b.math('MAXIMUM', I["Poly Radius"], 1e-6))
    k = b.math('ADD', 1.0, b.math('MULTIPLY', b.math('MULTIPLY', star, odd), b.math('SUBTRACT', inner, 1.0)))
    poly = b.set_position(circle.outputs["Curve"], position=b.vmath('SCALE', b.position(), scale=k))
    # Rectangle (corners rounded by Corner Radius in Corner Segments when it is above 0)
    quad = b.node("GeometryNodeCurvePrimitiveQuadrilateral")
    b._in(quad.inputs["Width"], I["Rectangle Width"])
    b._in(quad.inputs["Height"], I["Rectangle Height"])
    fillet = b.node("GeometryNodeFilletCurve")
    _menu(fillet, "Mode", "mode", "Poly", 'POLY')
    b.link(quad.outputs["Curve"], fillet.inputs["Curve"])
    b._in(fillet.inputs["Radius"], I["Corner Radius"])
    b._in(fillet.inputs["Count"], I["Corner Segments"])
    fillet.inputs["Limit Radius"].default_value = True
    rect = b.switch('GEOMETRY', b.math('GREATER_THAN', I["Corner Radius"], 1e-6), quad.outputs["Curve"],
                    fillet.outputs["Curve"])
    # Line along X
    line = b.node("GeometryNodeCurvePrimitiveLine")
    half = b.math('MULTIPLY', I["Line Length"], 0.5)
    b._in(line.inputs["Start"], b.combine(b.math('MULTIPLY', half, -1.0), 0.0, 0.0))
    b._in(line.inputs["End"], b.combine(half, 0.0, 0.0))
    # Arc round the origin, centred on +Y
    arc = b.node("GeometryNodeCurveArc", mode='RADIUS')
    sweep = b.math('RADIANS', I["Arc Angle"])
    b._in(arc.inputs["Resolution"], b.math('ADD', I["Arc Segments"], 1.0))     # points
    b._in(arc.inputs["Radius"], I["Arc Radius"])
    b._in(arc.inputs["Start Angle"], b.math('SUBTRACT', 1.5707963267948966, b.math('MULTIPLY', sweep, 0.5)))
    b._in(arc.inputs["Sweep Angle"], sweep)
    # Wave: a line along X in Wave Segments, Y = amplitude · sin(2π (cycles · t + offset))
    wline = b.node("GeometryNodeCurvePrimitiveLine")
    whalf = b.math('MULTIPLY', I["Wave Length"], 0.5)
    b._in(wline.inputs["Start"], b.combine(b.math('MULTIPLY', whalf, -1.0), 0.0, 0.0))
    b._in(wline.inputs["End"], b.combine(whalf, 0.0, 0.0))
    wres = b.resample(wline.outputs["Curve"], "count", count=b.math('ADD', I["Wave Segments"], 1.0))
    phase = b.math('MULTIPLY', b.math('ADD', b.math('MULTIPLY', I["Wave Cycles"], b.factor()), I["Wave Offset"]),
                   6.283185307179586)
    wave = b.set_position(wres, offset=b.combine(0.0, b.math('MULTIPLY', I["Wave Amplitude"],
                                                              b.math('SINE', phase)), 0.0))
    return [poly, rect, line.outputs["Curve"], arc.outputs["Curve"], wave]


def _path(b, I):                              # noqa: E741
    """The curve, resampled by the interpolation mode."""
    info = b.node("GeometryNodeObjectInfo", transform_space='RELATIVE')
    b.link(I["Curve"], info.inputs["Object"])
    curve = info.outputs["Geometry"]
    steps = I["Interpolation Steps"]
    fine = b.resolution(curve, FINE)
    start_end = b.resample(fine, "count", count=b.math('ADD', steps, 1.0))
    ep = b.resample(b.resolution(curve, steps), "evaluated")
    distance = b.resample(fine, "length", length=b.math('MULTIPLY', I["Interpolation Distance"], I["Unit"]))
    per_span = b.math('ADD', 1.0, b.math('CEIL', b.math('DIVIDE', I["Interpolation Precision"], 10.0)))
    precision = b.resample(b.resolution(curve, per_span), "evaluated")
    path = b.index_switch(I["Interpolation Mode"], [start_end, ep, distance, precision])
    # taper: radius 1 at the start to Taper at the end; twist: tilt grows by Twist (degrees) along the curve
    t = b.factor()
    rad = b.node("GeometryNodeSetCurveRadius")
    b.link(path, rad.inputs["Curve"])
    b._in(rad.inputs["Radius"], b.math('ADD', 1.0, b.math('MULTIPLY', b.math('SUBTRACT', I["Taper"], 1.0), t)))
    tilt = b.node("GeometryNodeSetCurveTilt")
    b.link(rad.outputs[0], tilt.inputs["Curve"])
    old = b.node("GeometryNodeInputCurveTilt").outputs[0]
    b._in(tilt.inputs["Tilt"], b.math('ADD', old, b.math('MULTIPLY', b.math('RADIANS', I["Twist"]), t)))
    return tilt.outputs[0]


def build_group():
    ng = bpy.data.node_groups.new(GROUP, 'GeometryNodeTree')
    ng[VERSION_PROP] = VERSION
    ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    for name, stype, default, lo, hi in INPUTS:
        s = ng.interface.new_socket(name, in_out='INPUT', socket_type=stype)
        if default is not None:
            s.default_value = default
        if lo is not None:
            s.min_value = lo
        if hi is not None:
            s.max_value = hi
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    b = _B(ng)
    I = b.node("NodeGroupInput").outputs                     # noqa: E741
    gout = b.node("NodeGroupOutput")
    profile = b.index_switch(I["Profile Type"], _profiles(b, I))
    xf = b.node("GeometryNodeTransform")
    b.link(profile, xf.inputs["Geometry"])
    s = b.math('MULTIPLY', I["Scale Profile"], I["Unit"])
    b._in(xf.inputs["Scale"], b.combine(b.math('MULTIPLY', s, I["Scale Profile X"]),
                                        b.math('MULTIPLY', s, I["Scale Profile Y"]), 1.0))
    euler = b.combine(0.0, 0.0, b.math('RADIANS', I["Rotate Profile"]))
    b._in(xf.inputs["Rotation"], euler)
    b._in(xf.inputs["Translation"], b.combine(b.math('MULTIPLY', I["Translate Profile X"], I["Unit"]),
                                              b.math('MULTIPLY', I["Translate Profile Y"], I["Unit"]), 0.0))
    cm = b.node("GeometryNodeCurveToMesh")
    b.link(_path(b, I), cm.inputs["Curve"])
    b.link(xf.outputs["Geometry"], cm.inputs["Profile Curve"])
    b._in(cm.inputs["Fill Caps"], I["Caps"])
    if cm.inputs.get("Scale") is not None:          # 5.x scales the profile by this input, not by the radius
        b.link(b.node("GeometryNodeInputRadius").outputs[0], cm.inputs["Scale"])
    flip = b.node("GeometryNodeFlipFaces")
    b.link(cm.outputs["Mesh"], flip.inputs["Mesh"])
    b._in(flip.inputs["Selection"], I["Reverse Normals"])
    b.link(flip.outputs["Mesh"], gout.inputs[0])
    return ng


def group():
    ng = bpy.data.node_groups.get(GROUP)
    if ng is not None and ng.bl_idname == 'GeometryNodeTree' and ng.get(VERSION_PROP) == VERSION:
        return ng
    if ng is not None:
        ng.name = GROUP + ".old"
    return build_group()


# --- the node -------------------------------------------------------------------------------------------------

get, set_ = wire_deformer.get, wire_deformer.set_


def is_sweep(md):
    return (md.type == 'NODES' and md.node_group is not None and md.node_group.name.startswith(GROUP)
            and md.name.startswith(NODE))


def sweeps(ob):
    return [md for md in getattr(ob, "modifiers", ()) if is_sweep(md)]


def sweeps_of_curve(curve):
    """[(object, modifier)] of the sweeps ``curve`` drives."""
    return [(ob, md) for ob in bpy.data.objects for md in sweeps(ob) if get(md, "Curve") == curve]


def _next_name():
    from . import naming
    taken = {md.name for o in bpy.data.objects for md in getattr(o, "modifiers", ())}
    return f"{NODE}{naming.next_number(NODE, taken)}"


def create(context, curve, values=None):
    """``sweep1`` (mesh ``sweepShape1``) with a live ``sweepMeshCreator1`` on ``curve``; returns the object."""
    from . import curve_tools, material, prim_history
    me = bpy.data.meshes.new("sweepShape")
    ob = bpy.data.objects.new("sweep", me)
    curve_tools._link_new(context, ob, "sweep", select=False)
    md = ob.modifiers.new(_next_name(), 'NODES')
    md.node_group = group()
    set_(md, "Curve", curve)
    set_(md, "Unit", float(units.maya_unit(context.scene)))
    for name, value in (values or {}).items():
        set_(md, name, value)
    material.give_default(ob)
    if not prim_history.history_on(context):
        bake(context, ob)
    return ob


def bake(context, ob):
    """Make ``ob``'s sweeps plain mesh (Delete History of the node)."""
    from . import history
    context.view_layer.update()
    history._bake(context, ob, keep={m.name for m in ob.modifiers if not is_sweep(m)})


def release(context, curves):
    """Before ``curves`` are deleted: the sweeps they drive become plain meshes (Maya keeps the mesh)."""
    gone = set(curves)
    for ob in {o for c in curves if getattr(c, "type", None) == 'CURVE' for o, _md in sweeps_of_curve(c)}:
        if ob not in gone:
            bake(context, ob)


# --- Channel Box INPUTS / Attribute Editor --------------------------------------------------------------------

def _gn(name, cast=float):
    def get_(md):
        v = get(md, name)
        return cast(v) if v is not None else cast(0)

    def set__(md, v):
        set_(md, name, cast(v))
    return get_, set__


# Channel Box INPUTS rows: (Maya attribute, label, entry kind, socket)
ATTR_ROWS = (
    ("profilePolySides", "Profile Poly Sides", "INT", "Poly Sides"),
    ("scaleProfile", "Scale Profile", "NONE", "Scale Profile"),
    ("rotateProfile", "Rotate Profile", "NONE", "Rotate Profile"),
    ("twist", "Twist", "NONE", "Twist"),
    ("taper", "Taper", "NONE", "Taper"),
    ("interpolationSteps", "Interpolation Steps", "INT", "Interpolation Steps"),
    ("interpolationPrecision", "Interpolation Precision", "NONE", "Interpolation Precision"),
    ("interpolationDistance", "Interpolation Distance", "NONE", "Interpolation Distance"),
    ("capsEnable", "Caps", "BOOL", "Caps"),
)


def attrs():
    return [deformers.Attr(key, label, kind, *_gn(sock, int if kind == "INT" else bool if kind == "BOOL" else float))
            for key, label, kind, sock in ATTR_ROWS]


# AE sections: (title, [(socket, label)]); a profile section shows only for its profile type
_PROFILE_ROWS = {
    0: [("Poly Type", "Poly Type"), ("Poly Sides", "Profile Poly Sides"), ("Poly Radius", "Radius"),
        ("Inner Radius", "Inner Radius")],
    1: [("Rectangle Width", "Width"), ("Rectangle Height", "Height"), ("Corner Radius", "Corner Radius"),
        ("Corner Segments", "Corner Segments")],
    2: [("Line Length", "Length")],
    3: [("Arc Angle", "Angle"), ("Arc Radius", "Radius"), ("Arc Segments", "Segments")],
    4: [("Wave Amplitude", "Amplitude"), ("Wave Cycles", "Cycles"), ("Wave Offset", "Offset"),
        ("Wave Length", "Length"), ("Wave Segments", "Segments")],
}
_TRANSFORM_ROWS = [("Scale Profile", "Scale Profile"), ("Scale Profile X", "Scale Profile X"),
                   ("Scale Profile Y", "Scale Profile Y"), ("Rotate Profile", "Rotate Profile"),
                   ("Translate Profile X", "Translate Profile X"), ("Translate Profile Y", "Translate Profile Y"),
                   ("Twist", "Twist"), ("Taper", "Taper")]
_INTERP_ROWS = {0: [("Interpolation Steps", "Steps")], 1: [("Interpolation Steps", "Steps")],
                2: [("Interpolation Distance", "Distance")], 3: [("Interpolation Precision", "Precision")]}


def _draw_input(layout, md, socket, label):
    key = wire_deformer.ident(md, socket)
    if key is None:
        return
    if socket in ENUMS:
        row = layout.row(align=True)
        row.label(text=label)
        cur = get(md, socket)
        for i, text in enumerate(ENUMS[socket]):
            op = row.operator("allset.gn_deformer_enum", text=text, depress=cur == i)
            op.object, op.modifier, op.socket, op.value = md.id_data.name, md.name, socket, i
        return
    if compat.GN_INPUT_STRUCT:
        item = compat._gn_input(md, key)
        if item is not None:
            layout.prop(item, "value", text=label)
        return
    layout.prop(md, f'["{key}"]', text=label)


def draw_ae(layout, md):
    """The node's attributes in its AE tab (Profile, Transform, Interpolation, Caps); False for other modifiers."""
    if not is_sweep(md):
        return False
    layout.label(text="Profile")
    _draw_input(layout, md, "Profile Type", "Profile Type")
    kind = int(get(md, "Profile Type") or 0)
    for socket, label in _PROFILE_ROWS.get(kind, ()):
        _draw_input(layout, md, socket, label)
    layout.separator()
    layout.label(text="Transform")
    for socket, label in _TRANSFORM_ROWS:
        _draw_input(layout, md, socket, label)
    layout.separator()
    layout.label(text="Interpolation")
    _draw_input(layout, md, "Interpolation Mode", "Mode")
    for socket, label in _INTERP_ROWS.get(int(get(md, "Interpolation Mode") or 0), ()):
        _draw_input(layout, md, socket, label)
    layout.separator()
    _draw_input(layout, md, "Caps", "Caps")
    _draw_input(layout, md, "Reverse Normals", "Reverse Normals")
    return True


def register():
    deformers.BASES[NODE] = ('NODES', NODE)
    deformers.ATTRS[NODE] = attrs()


def unregister():
    deformers.BASES.pop(NODE, None)
    deformers.ATTRS.pop(NODE, None)
