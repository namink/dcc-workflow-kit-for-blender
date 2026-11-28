# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Constrain > UV Pin and Proximity Pin: ``uv_pin`` / ``proximity_pin`` pin transforms (or new locators) to a
mesh with a Copy Transforms constraint named like the Maya node (``uvPin1``) that follows a hidden helper empty;
the operators ``allset.uv_pin`` / ``allset.proximity_pin`` and their option windows (``windows``). Helper keys and
``update`` are in pin_update.py, the surface math in pin_geometry.py.
"""

import bmesh
import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty

from .. import results, undo_steps
from . import deformers, units
from .pin_geometry import Geo
from .pin_update import (AXES, AXIS_ITEMS, ENVELOPE, GEOM, INPUT, INPUT_MATRIX, KIND, MODE, NODE, OFFSET, OFFSET_O,
                         OFFSET_T, OWNER, UV, _rescan, helpers, update)

# Messages
MSG_GEOMETRY = "Must select geometry before adding this constraint."
MSG_OUTPUT_MODE = "Output mode does not work with this creation mode"
MSG_NO_COMPONENTS = "No components were selected: no uvPin node created"
MSG_NOT_IMPLEMENTED = "Not yet implemented..."
MSG_IO = "Existing transform cannot be used as both an input and output."
MSG_INHERIT = "Inherit transform has been turned off for {0}"
MSG_AXIS = "The normal axis and the tangent axis lie on the same line: pick a different normal axis."
HINT_UV = ("Select the geometry to pin to, then Shift-select the objects to pin (each takes the closest UV), "
           "or select components of the geometry to pin at their UVs.")
HINT_PROX = "Select geometry to constrain to and then Shift + select objects to be constrained."


# --- creating pins ----------------------------------------------------------------------------------------------

def _maya_unique(base):
    """Maya naming of ``-n base``: ``base`` when free, else ``base1``, ``base2`` ..."""
    taken = {o.name for o in bpy.data.objects}
    if base not in taken:
        return base
    n = 1
    while f"{base}{n}" in taken:
        n += 1
    return f"{base}{n}"


def new_node(kind):
    """``<kind>N`` with N the lowest number no pin node / object uses (Maya: uvPin1, uvPin2 ...)."""
    used = {h.get(NODE) for h in helpers()} | {o.name for o in bpy.data.objects}
    n = 1
    while f"{kind}{n}" in used:
        n += 1
    return f"{kind}{n}"


def _link_like(ob, other, context):
    cols = list(getattr(other, "users_collection", ())) or [context.scene.collection]
    cols[0].objects.link(ob)


def _empty(context, name, like, display='PLAIN_AXES', size=None):
    ob = bpy.data.objects.new(_maya_unique(name), None)
    ob.empty_display_type = display
    ob.empty_display_size = units.maya_unit(context.scene) if size is None else size
    _link_like(ob, like, context)
    return ob


def _clear_channels(ob):
    """Maya clears the pinned transform: translate / rotate / shear 0, scale 1 (the pin drives the transform)."""
    ob.location = (0.0, 0.0, 0.0)
    ob.rotation_euler = (0.0, 0.0, 0.0)
    ob.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    ob.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
    ob.scale = (1.0, 1.0, 1.0)


def _pin_output(context, kind, node, i, owner, geom, props):
    """Helper empty + the Copy Transforms on ``owner`` (Maya: node output -> offsetParentMatrix)."""
    h = bpy.data.objects.new(f"{node}Output{i}", None)
    h.empty_display_size = 0.0
    h.hide_viewport = h.hide_render = h.hide_select = True
    h[KIND], h[NODE], h[OWNER], h[GEOM] = kind, node, owner, geom
    for k, v in props.items():
        h[k] = v
    _link_like(h, owner, context)
    _rescan()
    _clear_channels(owner)
    con = owner.constraints.new('COPY_TRANSFORMS')
    con.name = node
    con.target = h
    con.mix_mode = 'BEFORE_FULL'
    return h


def _axes(normal_axis, tangent_axis):
    na, ta = AXIS_ITEMS.index(normal_axis), AXIS_ITEMS.index(tangent_axis)
    if na % 3 == ta % 3:
        raise RuntimeError(MSG_AXIS)
    return [na, ta]


def _geometry_and_targets(context):
    """(geometry, transforms) in Maya selection order: the geometry = a selected mesh that isn't the active object
    (the first by name when there are several, operators/modify_maya.selection_order), the transforms = the rest."""
    from .modify_maya import selection_order
    obs = selection_order(context)
    lead = obs[-1] if obs and obs[-1] is context.view_layer.objects.active else None
    geom = next((o for o in obs if o is not lead and o.type == 'MESH'), None)
    if geom is None:
        return None, []
    return geom, [o for o in obs if o is not geom]


def _component_uvs(ob):
    """Maya's UVs of the selection on a mesh in edit mode: vertices -> their UV, faces -> mean corner UV, edges -> mid
    of the two vertices' UVs (the vertex UV = its first face corner)."""
    bm = bmesh.from_edit_mesh(ob.data)
    uvl = bm.loops.layers.uv.active
    if uvl is None:
        return []

    def vuv(v):
        for lp in v.link_loops:
            return tuple(lp[uvl].uv)
        return None
    out = []
    mode = bm.select_mode
    if 'VERT' in mode:
        out += [vuv(v) for v in bm.verts if v.select]
    elif 'EDGE' in mode:
        for e in bm.edges:
            if e.select:
                a, b = vuv(e.verts[0]), vuv(e.verts[1])
                if a and b:
                    out.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    else:
        for f in bm.faces:
            if f.select:
                us = [tuple(lp[uvl].uv) for lp in f.loops]
                out.append((sum(u for u, _v in us) / len(us), sum(v for _u, v in us) / len(us)))
    return [u for u in out if u is not None]


def uv_pin(context, setup='TRANSFORMS', output='CURRENT', normal_axis="X", tangent_axis="Y"):
    """Maya UV Pin. Returns (node name, [pinned objects], [inherit warnings])."""
    axes = _axes(normal_axis, tangent_axis)
    if setup == 'COMPONENTS' and output == 'CURRENT':
        raise RuntimeError(MSG_OUTPUT_MODE)
    depsgraph = context.evaluated_depsgraph_get()
    if setup == 'COMPONENTS':
        geom = context.edit_object if context.mode == 'EDIT_MESH' else None
        if geom is None or geom.type != 'MESH':
            raise RuntimeError(MSG_GEOMETRY)
        uvs = _component_uvs(geom)
        bpy.ops.object.mode_set(mode='OBJECT')
        if not uvs:
            raise RuntimeError(MSG_NO_COMPONENTS)
        targets = [None] * len(uvs)
    else:
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        geom, targets = _geometry_and_targets(context)
        if geom is None:
            raise RuntimeError(MSG_GEOMETRY)
        if not targets:
            raise RuntimeError(HINT_UV)
        uvs = None
    geo = Geo(geom, depsgraph)
    if not geo.ok or geo.tuv is None:
        raise RuntimeError(f"{geom.name} has no UVs to pin to.")
    node = new_node("uvPin")
    pinned, inherit = [], []
    for i, target in enumerate(targets):
        if uvs is not None:
            uv = uvs[i]
        else:
            hit = geo.closest(np.array(target.matrix_world.translation, dtype=np.float64))
            if hit is None:
                continue
            uv = geo.uv_at(hit)
        if output != 'CURRENT':
            target = _empty(context, "pinOutput", geom, size=None if output == 'LOCATOR' else 0.0)
        else:
            inherit.append(target.name)          # Maya turns inheritsTransform off on every pinned transform
        _pin_output(context, "uvPin", node, i, target, geom, {UV: list(uv), AXES: axes, MODE: "uv"})
        pinned.append(target)
    update(depsgraph)
    context.view_layer.update()
    return node, pinned, inherit


def proximity_pin(context, setup='TRANSFORMS', output='CURRENT', input_='LOCATOR', maintain_offset=True,
                  mode='EDGE', normal_axis="X", tangent_axis="Y"):
    """Maya Proximity Pin. Returns (node name, [pinned objects], [pinInput objects], [inherit warnings])."""
    axes = _axes(normal_axis, tangent_axis)
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    geom, targets = _geometry_and_targets(context)
    if geom is None:
        raise RuntimeError(MSG_GEOMETRY)
    if input_ == 'CURRENT' and output == 'CURRENT':
        raise RuntimeError(MSG_IO)
    if setup == 'COMPONENTS':
        raise RuntimeError(MSG_NOT_IMPLEMENTED)
    if not targets:
        raise RuntimeError(HINT_PROX)
    depsgraph = context.evaluated_depsgraph_get()
    geo = Geo(geom, depsgraph)
    if not geo.ok:
        raise RuntimeError(MSG_GEOMETRY)
    node = new_node("proximityPin")
    gm = geom.matrix_world.inverted_safe()
    pinned, inputs, inherit = [], [], []
    for i, target in enumerate(targets):
        rel = gm @ target.matrix_world          # Maya matchTransform to the geometry: the input in geometry space
        on = 1.0 if maintain_offset else 0.0
        props = {OFFSET: bool(maintain_offset), OFFSET_T: on, OFFSET_O: on, ENVELOPE: 1.0, AXES: axes,
                 MODE: "uv" if mode == 'UV' else "edge"}
        if input_ == 'MATRIX':
            props[INPUT_MATRIX] = [x for row in rel for x in row]
        else:
            inp = _empty(context, "pinInput", geom, size=None if input_ == 'LOCATOR' else 0.0)
            inp.matrix_world = rel
            props[INPUT] = inp
            inputs.append(inp)
        if output != 'CURRENT':
            target = _empty(context, "pinOutput", geom, size=None if output == 'LOCATOR' else 0.0)
        else:
            inherit.append(target.name)          # Maya turns inheritsTransform off on every pinned transform
        _pin_output(context, "proximityPin", node, i, target, geom, props)
        pinned.append(target)
    update(depsgraph)
    context.view_layer.update()
    for o in inputs:
        o.select_set(True)                       # Maya selects the created nodes
    return node, pinned, inputs, inherit


_AXIS_ENUM = [(a, a, "") for a in AXIS_ITEMS]
_OUTPUTS = [('CURRENT', "Existing Transform", ""), ('NULL', "New Transform", ""), ('LOCATOR', "New Locator", "")]


@undo_steps.no_redo_panel
class ALLSET_OT_uv_pin(bpy.types.Operator):
    """Constrains one or more objects to the UVs of a deforming target object (Maya Constrain > UV Pin): select the
    geometry, then the transforms"""
    bl_idname = "allset.uv_pin"
    bl_label = "UV Pin"
    bl_options = {'REGISTER', 'UNDO'}

    setup: EnumProperty(name="Pin locations", items=[('COMPONENTS', "Components", ""), ('TRANSFORMS', "Transforms", "")],
                        default='TRANSFORMS', options={'SKIP_SAVE'})
    output: EnumProperty(name="Output", items=_OUTPUTS, default='CURRENT', options={'SKIP_SAVE'})
    normal_axis: EnumProperty(name="Normal axis", items=_AXIS_ENUM, default="X", options={'SKIP_SAVE'})
    tangent_axis: EnumProperty(name="Tangent axis", items=_AXIS_ENUM, default="Y", options={'SKIP_SAVE'})

    def execute(self, context):
        try:
            node, pinned, inherit = uv_pin(context, self.setup, self.output, self.normal_axis, self.tangent_axis)
        except RuntimeError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        if inherit:
            self.report({'WARNING'}, MSG_INHERIT.format(inherit))
        if self.output != 'CURRENT':
            deformers._select_only(context, pinned, pinned[-1] if pinned else None)
        results.result(self, node)
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_proximity_pin(bpy.types.Operator):
    """Keeps objects on a deforming surface at the spot nearest to each, optionally with their current offset (Maya
    Constrain > Proximity Pin): select the geometry, then the objects to constrain"""
    bl_idname = "allset.proximity_pin"
    bl_label = "Proximity Pin"
    bl_options = {'REGISTER', 'UNDO'}

    setup: EnumProperty(name="Setup mode", items=[('COMPONENTS', "Components", ""), ('TRANSFORMS', "Transforms", "")],
                        default='TRANSFORMS', options={'SKIP_SAVE'})
    output: EnumProperty(name="Output", items=_OUTPUTS, default='CURRENT', options={'SKIP_SAVE'})
    input: EnumProperty(name="Input", items=_OUTPUTS + [('MATRIX', "Matrix", "")], default='LOCATOR',
                        options={'SKIP_SAVE'})
    maintain_offset: BoolProperty(name="Maintain offset", default=True, options={'SKIP_SAVE'})
    mode: EnumProperty(name="Mode", items=[('EDGE', "Edge", ""), ('UV', "UV", "")], default='EDGE',
                       options={'SKIP_SAVE'})
    normal_axis: EnumProperty(name="Normal axis", items=_AXIS_ENUM, default="X", options={'SKIP_SAVE'})
    tangent_axis: EnumProperty(name="Tangent axis", items=_AXIS_ENUM, default="Y", options={'SKIP_SAVE'})

    def execute(self, context):
        try:
            node, pinned, _inputs, inherit = proximity_pin(
                context, self.setup, self.output, self.input, self.maintain_offset, self.mode, self.normal_axis,
                self.tangent_axis)
        except RuntimeError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        if inherit:
            self.report({'WARNING'}, MSG_INHERIT.format(inherit))
        results.result(self, node)
        return {'FINISHED'}


# --- Maya option windows (UV Pin / Proximity Pin Options) — appended by operators/option_windows._extend ------------

def _windows():
    from .option_windows import F, Window
    axes = list(AXIS_ITEMS)
    outputs = ("Existing Transform", "New Transform", "New Locator")
    out_key = {"Existing Transform": 'CURRENT', "New Transform": 'NULL', "New Locator": 'LOCATOR', "Matrix": 'MATRIX'}

    def run_uv(context, v):
        return bpy.ops.allset.uv_pin('EXEC_DEFAULT', setup=v["setup"].upper(), output=out_key[v["output"]],
                                     normal_axis=v["normal_axis"], tangent_axis=v["tangent_axis"])

    def run_prox(context, v):
        return bpy.ops.allset.proximity_pin(
            'EXEC_DEFAULT', setup=v["setup"].upper(), output=out_key[v["output"]], input=out_key[v["input"]],
            maintain_offset=v["maintain_offset"], mode=v["mode"].upper(), normal_axis=v["normal_axis"],
            tangent_axis=v["tangent_axis"])
    return [
        # Maya's UV Pin Options: default values and labels
        Window("uv_pin", "UV Pin Options", "Add", ("allset.uv_pin", {}),
               [F("setup", "Pin locations", "enum", "Transforms", items=("Components", "Transforms"),
                  heading="Connections"),
                F("output", "Output", "enum", "Existing Transform", items=outputs),
                F("normal_axis", "Normal axis", "enum", "X", items=axes, heading="Coordinate System"),
                F("tangent_axis", "Tangent axis", "enum", "Y", items=axes)],
               run_uv, paths=("Constrain/UV Pin",),
               missing=("Output: Matrix", "UV set name (the active UV map)", "Normalize isoparms (NURBS)")),
        # Maya's Proximity Pin Options
        Window("proximity_pin", "Proximity Pin Options", "Add", ("allset.proximity_pin", {}),
               [F("setup", "Setup mode", "enum", "Transforms", items=("Components", "Transforms"),
                  heading="Connections"),
                F("output", "Output", "enum", "Existing Transform", items=outputs),
                F("input", "Input", "enum", "New Locator", items=outputs + ("Matrix",)),
                F("maintain_offset", "", "bool", True, text="Maintain offset"),
                F("mode", "Mode", "enum", "Edge", items=("Edge", "UV"), heading="Coordinate System"),
                F("normal_axis", "Normal axis", "enum", "X", items=axes),
                F("tangent_axis", "Tangent axis", "enum", "Y", items=axes)],
               run_prox, paths=("Constrain/Proximity Pin",),
               missing=("Output: Matrix", "UV set name (the active UV map)")),
    ]


WINDOWS = []          # filled by windows() when option_windows._extend asks (avoids an import cycle at load)


def windows():
    if not WINDOWS:
        WINDOWS.extend(_windows())
    return WINDOWS
