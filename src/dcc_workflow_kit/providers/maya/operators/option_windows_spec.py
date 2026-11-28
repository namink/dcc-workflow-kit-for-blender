# SPDX-License-Identifier: GPL-3.0-or-later
"""The option-window spec every ``option_windows_*`` module builds its windows from: ``F`` (one Maya field: kind,
label, default, range) and ``Window`` (title, command button, menu action it belongs to, fields, run function), plus
the run helpers windows share (``_components``, ``_constraint``, ``_primitive``, ``_with_hierarchy``) and the Axis /
Create UVs fields (``AXIS``, ``UVS``). ``option_windows`` re-exports all of it and keeps the registry and operators.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty
from mathutils import Matrix

from . import scene_axes, units

# --- spec -------------------------------------------------------------------------------------------


class F:
    """One Maya field: ``kind`` float / length (× maya_unit) / int / bool / enum / vec3 / vec3len / angle3."""

    def __init__(self, name, label, kind, default, items=None, lo=None, hi=None, text=None, heading=None, old=None):
        self.name, self.label, self.kind, self.default = name, label, kind, default
        self.items, self.lo, self.hi, self.text, self.heading = items, lo, hi, text, heading
        # old(values, name): turns this field's value saved with the Y-up reading into scene axes (scene_axes)
        self.old = old

    def prop(self):
        kw = {"name": self.label.rstrip(":"), "default": self.default}
        if self.kind in ("float", "length"):
            kw.update(soft_min=self.lo if self.lo is not None else -1e6, soft_max=self.hi if self.hi is not None else 1e6,
                      precision=4, step=10)
            return FloatProperty(**kw)
        if self.kind == "int":
            return IntProperty(min=self.lo if self.lo is not None else 0, soft_max=self.hi or 100, **kw)
        if self.kind == "bool":
            return BoolProperty(**kw)
        if self.kind == "enum":
            return EnumProperty(items=[(i, i, "") for i in self.items], **kw)
        if self.kind in {"curve", "ramp"}:
            return StringProperty(**kw)
        return FloatVectorProperty(size=3, precision=4, **kw)


class Window:
    def __init__(self, key, title, action, match, fields, run, paths=(), missing=(), width=440, apply_text="Apply",
                 click_saved=True, pref_fields=None, enabled=None, extra=None, old_axes=None):
        self.key, self.title, self.action = key, title, action
        # old_axes(values): turns option values saved while the window read X / Y / Z in the Y-up frame into scene
        # axes in place (scene_axes)
        self.old_axes = old_axes
        # field -> add-on preference that keeps its value (shown and set elsewhere too), not the saved option values
        self.pref_fields = dict(pref_fields or {})
        # a plain menu click runs the window's command with the saved values (Maya); False = the click keeps running
        # the menu's own action (Display > Grid toggles the grid, its window only sets how it looks)
        self.click_saved = click_saved
        self.apply_text = apply_text  # Maya's middle button (Offset Edge Loop: "Enter Tool")
        self.match = match            # (operator id, props subset) of the menu action this window belongs to
        self.fields, self.run, self.paths = fields, run, tuple(paths)
        self.missing = tuple(missing)   # Maya fields Blender has no equivalent for (drawn greyed, one line)
        self.width = width
        self.enabled = enabled
        # extra(layout, context): drawn under the fields (values that live in the scene, not saved option values)
        self.extra = extra

    @property
    def idname(self):
        return f"allset.opt_{self.key}"

    def defaults(self):
        return {f.name: f.default for f in self.fields}


# --- shared run helpers -----------------------------------------------------------------------------

def _k(context):
    return units.maya_unit(context.scene)


# Axis choice (scene axes) -> the creation node's axis, which the node keeps in the Y-up frame (prim_history)
_AXES = {a: scene_axes.to_yup(v) for a, v in (("X", (1.0, 0.0, 0.0)), ("Y", (0.0, 1.0, 0.0)), ("Z", (0.0, 0.0, 1.0)))}
# option window field -> Maya creation node attribute (the window fills the node, operators/prim_history.py)
_NODE_FIELDS = {
    'CUBE': {"width": "width", "height": "height", "depth": "depth", "width_div": "subdivisionsWidth",
             "height_div": "subdivisionsHeight", "depth_div": "subdivisionsDepth"},
    'SPHERE': {"radius": "radius", "axis_div": "subdivisionsAxis", "height_div": "subdivisionsHeight"},
    'CYLINDER': {"radius": "radius", "height": "height", "axis_div": "subdivisionsAxis",
                 "height_div": "subdivisionsHeight", "cap_div": "subdivisionsCaps", "round_cap": "roundCap"},
    'CONE': {"radius": "radius", "height": "height", "axis_div": "subdivisionsAxis", "height_div": "subdivisionsHeight",
             "cap_div": "subdivisionsCap", "round_cap": "roundCap"},
    'TORUS': {"radius": "radius", "section_radius": "sectionRadius", "twist": "twist", "axis_div": "subdivisionsAxis",
              "height_div": "subdivisionsHeight"},
    'PLANE': {"width": "width", "height": "height", "width_div": "subdivisionsWidth",
              "height_div": "subdivisionsHeight"},
}


def _primitive(kind):
    def run(context, v):
        from .option_windows_prims import _create
        over = {node: v[field] for field, node in _NODE_FIELDS[kind].items() if field in v}
        ax = _AXES.get(v.get("axis", "Z"), _AXES["Z"])
        over.update(axisX=ax[0], axisY=ax[1], axisZ=ax[2], createUVs=int(bool(v.get("create_uvs", True))))
        return _create(context, kind, over)     # at the origin, or drawn with Interactive Creation
    return run


def _op(op_id, **kw):
    mod, name = op_id.split(".")
    return getattr(getattr(bpy.ops, mod), name)('EXEC_DEFAULT', **kw)


def _components(context, op_id, select_mode, **kw):
    """Run an edit-mode mesh command; from object mode on every component of the selected meshes (Maya)."""
    if context.mode == 'EDIT_MESH':
        return _op(op_id, **kw)
    meshes = [o for o in context.selected_objects if o.type == 'MESH']
    if not meshes:
        raise RuntimeError("Select a mesh first.")
    if context.view_layer.objects.active not in meshes:
        context.view_layer.objects.active = meshes[0]
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        bpy.ops.mesh.select_mode(type=select_mode)
        bpy.ops.mesh.select_all(action='SELECT')
        return _op(op_id, **kw)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')


def _with_hierarchy(context, below, fn):
    """Maya Hierarchy: Selected / Below (the selection plus everything under it while ``fn`` runs)."""
    if not below:
        return fn()
    from .freeze import hierarchy
    extra = [o for o in hierarchy(context.selected_objects) if not o.select_get()]
    for o in extra:
        o.select_set(True)
    try:
        return fn()
    finally:
        for o in extra:
            o.select_set(False)


def _last_constraint(context):
    pb = context.active_pose_bone if context.mode == 'POSE' else None
    owner = pb if pb is not None else context.active_object
    return owner.constraints[-1] if owner is not None and owner.constraints else None


def _group_axes(cons, ctype, v):
    """Constraint axes on every Blender constraint of a kit multi-target group: the parent group's Copy
    Location members take Translate, its Copy Rotation members Rotate (X / Y / Z = the scene axes)."""
    for con in cons:
        if ctype == 'CHILD_OF':
            pre = "all_t" if con.type == 'COPY_LOCATION' else "all_r"
            keys = ("tx", "ty", "tz") if con.type == 'COPY_LOCATION' else ("rx", "ry", "rz")
            con.use_x, con.use_y, con.use_z = (v[pre] or v[k] for k in keys)
        else:
            con.use_x, con.use_y, con.use_z = (v["all"] or v[k] for k in ("x", "y", "z"))


def _constraint(ctype):
    def run(context, v):
        from . import constrain_multi
        res = bpy.ops.allset.constrain('EXEC_DEFAULT', type=ctype, weight=v["weight"],
                                       maintain_offset='ON' if v["maintain_offset"] else 'OFF')
        con = _last_constraint(context)
        if res != {'FINISHED'} or con is None:
            return res
        mb = constrain_multi.member(con)
        if mb is not None:
            # a multi-target node: Maintain offset and Weight were applied when it was built (weights = W0, W1 ...)
            _group_axes(constrain_multi.members(mb.owner, mb.group), ctype, v)
            return res
        constrain_multi.set_weight(con, v["weight"])     # Maya: any weight above 0 = fully on the target
        if ctype == 'CHILD_OF':
            if not v["maintain_offset"]:
                con.inverse_matrix = Matrix.Identity(4)      # snap like Maya without Maintain offset
            con.use_location_x = v["all_t"] or v["tx"]
            con.use_location_y = v["all_t"] or v["ty"]
            con.use_location_z = v["all_t"] or v["tz"]
            con.use_rotation_x = v["all_r"] or v["rx"]
            con.use_rotation_y = v["all_r"] or v["ry"]
            con.use_rotation_z = v["all_r"] or v["rz"]
        else:
            con.use_x, con.use_y, con.use_z = (v["all"] or v[k] for k in ("x", "y", "z"))
            if v["maintain_offset"]:
                if ctype == 'COPY_LOCATION':
                    con.use_offset = True
                else:
                    con.mix_mode = 'OFFSET'
        return res
    return run


# --- shared fields (the primitive windows) ---------------------------------------------------------

AXIS = F("axis", "Axis:", "enum", "Z", items=("X", "Y", "Z"), old=scene_axes.old_axis)
UVS = F("create_uvs", "Texture mapping:", "bool", True, text="Create UVs")
