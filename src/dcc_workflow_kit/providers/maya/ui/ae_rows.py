# SPDX-License-Identifier: GPL-3.0-or-later
"""Attribute Editor tab bodies: the collapsible sections and attribute rows of a tab (from the ``ae_layout``
tables), the special rows (Translate / Rotate / Scale fields, Joint Orient, limits, Smooth Mesh ...) and the
bodies of history, constraint, shading group and Extra Attributes tabs.
Main entry points: ``draw_sections``, ``draw_row``, ``draw_history``, ``draw_constraint``, ``section_body``."""

import math

import bpy

from .. import i18n
from ..operators import display
from . import cb_entry, channel_box
from .ae_nodes import ae_node, modifier_node, nice_type
from .maya_dock_strip import section


# --- drawing --------------------------------------------------------------------------------

def resolve(owner, path):
    """(object, attribute) for a dotted path such as ``overlay.show_face_normals``."""
    *head, attr = path.split(".")
    for part in head:
        owner = getattr(owner, part, None)
        if owner is None:
            return None, attr
    return owner, attr


def _owner(context, ob, target, name):
    if name == "ob":
        return ob
    if name == "data":
        return target
    if name == "view":
        space = context.space_data
        return space if space is not None and space.type == 'VIEW_3D' else None
    if channel_box.is_bone(ob):
        return {"bone": ob.bone, "arm": ob.id_data.data, "armob": ob.id_data}.get(name)
    return None


def _length(context, value):
    us = context.scene.unit_settings
    return bpy.utils.units.to_string(us.system, 'LENGTH', value * us.scale_length, precision=3)


def _vector_row(layout, owner, attr, label):
    """Maya AE float3 row: label, then the three fields side by side."""
    split = layout.split(factor=0.3, align=True)
    split.label(text=label)
    split.row(align=True).prop(owner, attr, text="")


def _maya_number_rows(layout, context, ob):
    """Translate / Rotate / Scale as Maya number fields (no unit, never cut to "62 c", #85): the Channel Box text
    proxies, when ``ob`` is the lead and the only selected node (the proxies type into every selected node, the AE
    edits one). False when that doesn't apply."""
    if channel_box.is_bone(ob) or ob is not channel_box.lead(context) or len(channel_box.targets(context)) != 1:
        return False
    if ob.rotation_mode in {'QUATERNION', 'AXIS_ANGLE'}:
        return False
    cb = context.scene.allset_cb
    col = layout.column(align=True)
    for label, keys in (("Translate", ("tx", "ty", "tz")), ("Rotate", ("rx", "ry", "rz")),
                        ("Scale", ("sx", "sy", "sz"))):
        split = col.split(factor=0.3, align=True)
        split.label(text=label)
        row = split.row(align=True)
        for key in keys:
            # each field its own cell: the Channel Box key colours (keyed / animated / driven / muted) and lock
            cell = row.row(align=True)
            cell.alert = channel_box.state_alert(channel_box.channel_state(ob, key))
            cell.enabled = not channel_box.is_locked(ob, key)
            cell.prop(cb, key + "_text", text="")
    return True


def draw_transform_channels(layout, context, ob):
    if _maya_number_rows(layout, context, ob):
        return
    col = layout.column(align=True)
    _vector_row(col, ob, "location", "Translate")
    if ob.rotation_mode == 'QUATERNION':
        _vector_row(col, ob, "rotation_quaternion", "Rotate")
    elif ob.rotation_mode == 'AXIS_ANGLE':
        _vector_row(col, ob, "rotation_axis_angle", "Rotate")
    else:
        _vector_row(col, ob, "rotation_euler", "Rotate")
    _vector_row(col, ob, "scale", "Scale")


def draw_world_pivot(layout, context, ob):
    col = layout.column(align=True)
    for axis, value in zip("XYZ", ob.matrix_world.translation):
        col.label(text=f"World Rotate Pivot {axis}: {_length(context, value)}")


LIMIT_PROPS = {
    'LIMIT_LOCATION': ("use_min_{a}", "min_{a}", "use_max_{a}", "max_{a}"),
    'LIMIT_SCALE': ("use_min_{a}", "min_{a}", "use_max_{a}", "max_{a}"),
    'LIMIT_ROTATION': ("use_limit_{a}", "min_{a}", "max_{a}"),
}


def draw_limit(layout, context, ob, kind):
    con = next((c for c in ob.constraints if c.type == kind), None)
    if con is None:
        layout.operator("allset.ae_add_limit", text=f"Add {kind.replace('_', ' ').title()}").type = kind
        return
    for a in "xyz":
        row = layout.row(align=True)
        for pattern in LIMIT_PROPS[kind]:
            row.prop(con, pattern.format(a=a))


def draw_visibility(layout, context, ob):
    if channel_box.is_bone(ob):
        layout.prop(ob.bone, "hide", text="Visibility", invert_checkbox=True)
    else:
        layout.prop(ob, "hide_viewport", text="Visibility", invert_checkbox=True)


JOINT_AXIS_NOTE = "Bone Y points to the child joint (Maya Primary Axis X)"


def joint_orient(pb):
    """Maya jointOrient (radians, xyz) from the joints' Maya frames (bone axes turned by
    ``allset_maya_frame``; a top joint in Maya's world axes)."""
    from ..operators import joints
    bone = pb.bone
    frame = joints.maya_bone_frame(bone)
    parent = joints.maya_bone_frame(bone.parent) if bone.parent is not None else joints.armature_world(pb.id_data)
    return (parent.transposed() @ frame).to_euler('XYZ')


def draw_joint_orient(layout, context, pb):
    split = layout.split(factor=0.3, align=True)
    split.label(text="Joint Orient")
    row = split.row(align=True)
    for v in joint_orient(pb):
        row.label(text=cb_entry.fmt_number(math.degrees(v)))   # Maya numbers: no "-0"
    from . import notices
    notices.tip(row, JOINT_AXIS_NOTE)    # a tooltip, not a Blender sentence in the AE


def draw_joint_stiffness(layout, context, pb):
    split = layout.split(factor=0.3, align=True)
    split.label(text="Stiffness")
    row = split.row(align=True)
    for a in "xyz":
        row.prop(pb, f"ik_stiffness_{a}", text="")


def draw_shading(layout, context, ob):
    row = layout.row(align=True)
    row.operator("object.shade_smooth", text="Soften (Smooth)")
    row.operator("object.shade_flat", text="Harden (Flat)")
    layout.operator("object.shade_auto_smooth", text="Soften by Angle")


def draw_smooth_mesh(layout, context, ob):
    row = layout.row(align=True)
    for level, label in ((1, "1 Off"), (2, "2 Cage"), (3, "3 Smooth")):
        row.operator("allset.smooth_preview", text=label).level = level
    sub = display.preview_modifier(ob, create=False)
    if sub is not None:
        layout.prop(sub, "levels", text="Division Levels")
        layout.prop(sub, "render_levels", text="Render Levels")


def draw_type_manipulator(layout, context, ob):
    """Type Manipulator on / off for this type, and putting characters back (operators/type_manip.py)."""
    from ..operators import type_manip
    if ob is None or ob.type != 'FONT':
        return
    on = type_manip.handle_of(ob) is not None
    row = layout.row(align=True)
    row.operator("allset.type_manipulator", text="Type Manipulator", depress=on)
    sub = row.row(align=True)
    sub.enabled = type_manip.modifier(ob) is not None
    sub.operator("allset.type_reset", text="Reset Character").all = False
    sub.operator("allset.type_reset", text="Reset All").all = True


DRAWERS = {"transform_channels": draw_transform_channels, "world_pivot": draw_world_pivot,
           "visibility": draw_visibility, "shading": draw_shading, "smooth_mesh": draw_smooth_mesh,
           "joint_orient": draw_joint_orient, "joint_stiffness": draw_joint_stiffness,
           "type_manipulator": draw_type_manipulator}


def attr_label(context, label, ident):
    """The row label for Display > Attribute Names: Nice (the label), Long (the property id), Short (its initials)."""
    mode = getattr(context.window_manager, "allset_ae_names", 'NICE')
    if mode == 'NICE' or not ident:
        return label
    if mode == 'LONG':
        return ident
    parts = [p for p in ident.split("_") if p]
    return "".join(p[0] for p in parts) if len(parts) > 1 else ident[:3]


def draw_row(layout, context, ob, target, row):
    kind = row[0]
    if kind == "prop":
        _k, owner_name, path, label = row
        owner, attr = resolve(_owner(context, ob, target, owner_name), path)
        if owner is not None and hasattr(owner, attr):
            layout.prop(owner, attr, text=attr_label(context, label, attr))
    elif kind == "draw":
        name = row[1]
        if name.startswith("limit:"):
            draw_limit(layout, context, ob, name[6:])
        else:
            DRAWERS[name](layout, context, ob)
    elif kind in {"socket", "maya"}:
        if kind == "maya":
            _k, maya_prop, label, socket = row
        else:
            _k, socket, label = row
            maya_prop = None
        from ..operators import material as _material
        # the Principled input; on an older kit material "Base Color" = its Maya Diffuse node's colour input
        inp = _material.maya_input(target, socket)
        if inp is None:
            return       # e.g. Diffuse: only an older kit material's Maya Diffuse node has it
        row = layout.row(align=True)
        if inp.is_linked:
            source = inp.links[0].from_node
            row.label(text=f"{label}: connected ({source.name})")
        elif maya_prop is not None and hasattr(target, maya_prop):
            row.prop(target, maya_prop, text=label)          # Maya's number, converted (#71)
        elif hasattr(inp, "default_value"):
            row.prop(inp, "default_value", text=label)
        else:
            row.label(text=label)
        # Maya's map (checker) button: Create Render Node / Break Connection (operators/shading_maps.py)
        op = row.operator("allset.ae_map", text="", icon='TEXTURE')
        op.material, op.socket = target.name, socket
        if inp.is_linked and source.type == 'TEX_IMAGE':
            # Maya file node's Image Name with its folder button
            layout.template_ID(source, "image", new="image.new", open="image.open")
    elif kind == "missing":
        _k, label, note = row
        sub = layout.row()
        sub.enabled = False
        sub.label(text=f"{label}: {note}")


SECTION_INDENT = 1.2     # separator factor in front of an open section's content area (under the header arrow)


def section_body(body):
    """The content of an open Attribute Editor section: Maya draws it inset under the section header, in a content
    area of its own shade (2 px in from each side, one step off the editor's grey;
    #194). The box starts under the section's disclosure arrow, gives the content area its shade and frame; the
    column is what the rows go into."""
    row = body.row()
    row.separator(factor=SECTION_INDENT)
    return row.box().column()


def draw_sections(layout, context, ob, target, sections, layout_id, prefix=""):
    for sec in sections:
        body = section(layout, f"allset_ae_{layout_id}_{prefix}{sec.name}", sec.name, default_closed=not sec.open)
        if body is None:
            continue
        col = section_body(body)
        for row in sec.rows:
            draw_row(col, context, ob, target, row)
        if sec.subs:
            draw_sections(col, context, ob, target, sec.subs, layout_id, f"{prefix}{sec.name}/")


# RNA properties of every modifier that are not the node's own attributes.
_MOD_SKIP = {"rna_type", "name", "type", "show_viewport", "show_render", "show_in_editmode",
             "show_on_cage", "show_expanded", "is_active", "is_override_data_editable",
             "use_apply_on_spline", "use_pin_to_last", "persistent_uid", "execution_time"}


def modifier_props(md):
    out = []
    for p in md.bl_rna.properties:
        ident = p.identifier
        if ident in _MOD_SKIP or p.is_readonly or p.type == 'COLLECTION' or ident.startswith("open_"):
            continue
        out.append(ident)
    return out


def draw_history(layout, context, ob, md):
    body = section(layout, f"allset_ae_history_{md.type}", f"{nice_type(modifier_node(ob, md)[1])} History")
    if body is not None:
        col = section_body(body)
        col.prop(md, "show_viewport", text="Enabled (Node State)")
        from ..operators import bend_deformer, deformers_205a, deformers_205b, nonlinear_nodes, sweep_mesh
        # Tension / Solidify / Sculpt, Morph / Jiggle, a mesh's nonlinears and sweepMeshCreator draw their Maya
        # attributes
        drawn = (deformers_205a.draw_ae(col, md) or deformers_205b.draw_ae(col, md) or bend_deformer.draw_ae(col, md)
                 or nonlinear_nodes.draw_ae(col, md) or sweep_mesh.draw_ae(col, md))
        if md.type == 'ARMATURE' and hasattr(ob, "allset_skinning_method"):
            col.prop(ob, "allset_skinning_method")       # Maya skinCluster Skinning Method
        for ident in ([] if drawn else modifier_props(md)):
            col.prop(md, ident, text=attr_label(context, md.bl_rna.properties[ident].name, ident))
    row = layout.row(align=True)
    op = row.operator("allset.ae_modifier", text="Delete History")
    op.modifier, op.action = md.name, 'APPLY'
    op = row.operator("allset.ae_modifier", text="Delete", icon='X')
    op.modifier, op.action = md.name, 'REMOVE'


# Constraint properties that are not the Maya constraint node's own attributes.
_CON_SKIP = {"rna_type", "name", "type", "show_expanded", "is_valid", "active", "is_override_data_editable",
             "is_override_data_local", "mute", "enabled", "influence", "error_location", "error_rotation"}


def constraint_props(con):
    return [p.identifier for p in con.bl_rna.properties
            if p.identifier not in _CON_SKIP and not p.is_readonly and p.type != 'COLLECTION']


def draw_constraint(layout, context, node, con):
    """A Maya constraint node tab: target weight (= influence), then the constraint's settings."""
    body = section(layout, f"allset_ae_constraint_{con.type}",
                   f"{channel_box.maya_constraint_type(con, con.type.title())} Attributes")
    if body is not None:
        col = section_body(body)
        if hasattr(con, "enabled"):
            col.prop(con, "enabled", text="Enabled (Node State)")
        from ..operators import constrain_multi
        owner = constrain_multi.owner_of(con)
        prop = constrain_multi.single_weight(con, owner)
        if prop is not None:        # a one-target constraint's own weight (the influence follows it)
            col.prop(owner, f'["{bpy.utils.escape_identifier(prop)}"]', text=channel_box.weight_name(con))
        else:
            col.prop(con, "influence", text=channel_box.weight_name(con))
        for ident in constraint_props(con):
            col.prop(con, ident, text=attr_label(context, con.bl_rna.properties[ident].name, ident))


def draw_extra(layout, owner, layout_id):
    keys = [k for k in owner.keys() if not k.startswith(("_", "allset_", "cycles"))]
    body = section(layout, f"allset_ae_{layout_id}_extra", i18n.mark("Extra Attributes"), default_closed=True)
    if body is None:
        return
    body = section_body(body)
    from .camera_aim_lines import CONNECTOR       # a camera rig group's Display Connector (#299)
    connector = CONNECTOR in owner.keys()
    if not keys and not connector:
        body.label(text="(none)")
    for k in sorted(keys):
        body.prop(owner, f'["{k}"]', text=k)
    if connector:
        body.prop(owner, f'["{CONNECTOR}"]', text="Display Connector")


def draw_extrude_history(layout, context, rec):
    """The polyExtrudeFace tab: Maya's "Poly Extrude Face History" with the kit record's values (the same text
    proxies as Channel Box INPUTS, ui/cb_model_node.py); also polyExtrudeEdge / Vertex and polyBevel3."""
    body = section(layout, "allset_ae_history_extrude", f"{nice_type(rec.spec.node_type)} History")
    if body is None:
        return
    hist = context.window_manager.allset_history
    col = section_body(body).column(align=True)
    from . import node_attributes
    node = node_attributes.for_record(context, ae_node(context), rec)
    for field in rec.spec.fields:
        split = col.split(factor=0.42, align=True)
        split.label(text=attr_label(context, rec.spec.labels[field], field))
        cell = split.row()
        cell.enabled = node is not None and node_attributes.editable(node, field)
        cell.prop(hist, f"{field}_text", text="")
    if rec.spec.kind == 'BRIDGE':
        from . import bridge_editor
        bridge_editor.draw_controls(col, node)


def draw_shading_group(layout, key, mat):
    """Maya's shading group tab (AEshadingEngineTemplate: Shading Group Attributes): the surface material opens
    its own tab; Blender has no volume / displacement slots of their own on a shading group."""
    box = section(layout, "ae_shading_group", i18n.mark("Shading Group Attributes"))
    if box is None:
        return
    box = section_body(box)
    row = box.row(align=True)
    row.label(text="Surface Material")
    row.operator("allset.ae_tab", text=mat.name, icon='MATERIAL').key = "MAT:" + key.split(":", 1)[1]
    for label in ("Volume Material", "Displacement Mat."):
        row = box.row(align=True)
        row.active = False
        row.label(text=label)
        row.label(text="")
