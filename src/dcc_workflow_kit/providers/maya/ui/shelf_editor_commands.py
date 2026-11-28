# SPDX-License-Identifier: GPL-3.0-or-later
"""Command ids for Shelf Editor buttons: search lists of Blender operators, Maya menu items, Blender menus and tools
(``operator_search``, ``menu_search``, ``action_id_search``, ``icon_search``), the check of operator property
overrides against the operator's own properties (``_validate_operator_properties``) and the JSON text of the
Operator Properties field. Related: shelf_editor_buttons.py."""

import json

import bpy

from . import shelf


_OPERATOR_ITEMS = []


def _operator_ids():
    global _OPERATOR_ITEMS
    if not _OPERATOR_ITEMS:
        found = set()
        try:
            for module_name in dir(bpy.ops):
                if module_name.startswith("_"):
                    continue
                module = getattr(bpy.ops, module_name)
                for op_name in dir(module):
                    if op_name.startswith("_"):
                        continue
                    identifier = f"{module_name}.{op_name}"
                    try:
                        getattr(module, op_name).get_rna_type()
                    except (AttributeError, RuntimeError, TypeError):
                        continue
                    found.add(identifier)
        except (AttributeError, RuntimeError, TypeError):
            pass
        _OPERATOR_ITEMS[:] = sorted(found)
    return _OPERATOR_ITEMS


def _draw_operator_rna(layout, identifier):
    """Show the selected Operator's RNA schema as guidance without inventing UI properties."""
    if not identifier or "." not in identifier:
        return
    try:
        module, name = identifier.split(".", 1)
        rna = getattr(getattr(bpy.ops, module), name).get_rna_type()
    except (AttributeError, RuntimeError, TypeError):
        layout.label(text="Operator RNA is unavailable", icon="INFO")
        return
    box = layout.box()
    box.label(text=f"{rna.name} — RNA Properties", icon="PROPERTIES")
    shown = 0
    for prop in rna.properties:
        if prop.identifier in {"rna_type", "name"} or prop.is_readonly:
            continue
        description = (prop.description or prop.name or prop.identifier).replace("\n", " ")
        layout_row = box.row(align=True)
        layout_row.label(text=prop.name or prop.identifier)
        layout_row.label(text=prop.type.title())
        shown += 1
        if shown >= 8:
            break
    if shown == 0:
        box.label(text="No configurable properties")
    box.label(text="Overrides are stored as JSON; omitted properties use Operator defaults.", icon="INFO")


def _validate_operator_properties(identifier, values):
    """Validate JSON overrides against the registered Blender Operator RNA schema."""
    module, name = identifier.split(".", 1)
    rna = getattr(getattr(bpy.ops, module), name).get_rna_type()
    definitions = {prop.identifier: prop for prop in rna.properties
                   if prop.identifier not in {"rna_type", "name"} and not prop.is_readonly}
    unknown = sorted(set(values) - set(definitions))
    if unknown:
        return f"Unknown {rna.name} property: {', '.join(unknown)}"
    for key, value in values.items():
        prop = definitions[key]
        expected = {"BOOLEAN": bool, "INT": int, "FLOAT": (int, float),
                    "STRING": str, "ENUM": str}.get(prop.type)
        is_array = getattr(prop, "is_array", False)
        if is_array:
            if not isinstance(value, (list, tuple)) or len(value) != prop.array_length:
                return f"{key} must be an array of length {prop.array_length}"
            if prop.type == "BOOLEAN" and any(type(item) is not bool for item in value):
                return f"{key} must contain boolean values"
            if prop.type == "INT" and any(type(item) is not int for item in value):
                return f"{key} must contain integer values"
            if prop.type == "FLOAT" and any(type(item) not in (int, float) for item in value):
                return f"{key} must contain numeric values"
            if prop.type not in {"BOOLEAN", "INT", "FLOAT"}:
                return f"{key} uses an unsupported Operator property type: {prop.type.lower()}"
            continue
        if expected and (type(value) not in expected if isinstance(expected, tuple) else type(value) is not expected):
            return f"{key} must be {prop.type.lower()}"
        if prop.type == "ENUM" and value not in {item.identifier for item in prop.enum_items}:
            return f"{key} must be one of the registered enum values"
        if expected is None:
            return f"{key} uses an unsupported Operator property type: {prop.type.lower()}"
        if prop.type in {"INT", "FLOAT"} and type(value) in (int, float):
            if value < prop.hard_min or value > prop.hard_max:
                return f"{key} must be between {prop.hard_min:g} and {prop.hard_max:g}"
    return ""


def operator_search(self, context, edit_text):
    query = (edit_text or "").lower()
    return [item for item in _operator_ids() if query in item.lower()][:80]


def menu_search(self, context, edit_text):
    from . import menu_map
    query = (edit_text or "").lower()
    return [item for item in sorted(menu_map.MAP) if query in item.lower()][:80]


def icon_search(self, context, edit_text):
    return shelf.shelf_icons.icon_search(self, context, edit_text)


# Blender does not expose a Python API listing every registered Menu/Pie class or
# every Tool, so augment the runtime subclass scan with a curated set of the
# commonly used identifiers. A user can still type any valid ID (validated on Apply).
_KNOWN_MENUS = (
    "VIEW3D_MT_editor_menus", "VIEW3D_MT_view", "VIEW3D_MT_add", "VIEW3D_MT_object",
    "VIEW3D_MT_object_relations", "VIEW3D_MT_object_constraints", "VIEW3D_MT_select_object",
    "VIEW3D_MT_pose", "VIEW3D_MT_pose_relations", "VIEW3D_MT_armature", "VIEW3D_MT_armature_select",
    "VIEW3D_MT_edit_mesh", "VIEW3D_MT_edit_mesh_vertices", "VIEW3D_MT_edit_mesh_edges",
    "VIEW3D_MT_edit_mesh_faces", "VIEW3D_MT_edit_mesh_select", "VIEW3D_MT_edit_curve",
    "VIEW3D_MT_editor_menus", "VIEW3D_MT_marker", "VIEW3D_MT_object_parent",
    "GRAPH_MT_editor_menus", "GRAPH_MT_view", "GRAPH_MT_channel", "GRAPH_MT_key", "GRAPH_MT_marker",
    "DOPESHEET_MT_editor_menus", "DOPESHEET_MT_view", "DOPESHEET_MT_key", "DOPESHEET_MT_marker",
    "NLA_MT_editor_menus", "NLA_MT_view", "NLA_MT_strips", "NLA_MT_marker",
    "IMAGE_MT_editor_menus", "IMAGE_MT_view", "IMAGE_MT_image", "IMAGE_MT_mask", "IMAGE_MT_marker",
    "NODE_MT_editor_menus", "NODE_MT_view", "NODE_MT_node", "NODE_MT_select",
    "OUTLINER_MT_editor_menus", "OUTLINER_MT_view", "OUTLINER_MT_object",
    "CONSOLE_MT_editor_menus", "CONSOLE_MT_console",
    "FILEBROWSER_MT_editor_menus", "FILEBROWSER_MT_view", "FILEBROWSER_MT_context",
    "ASSETBROWSER_MT_editor_menus", "ASSETBROWSER_MT_view", "ASSETBROWSER_MT_asset",
    "SEQUENCER_MT_editor_menus", "SEQUENCER_MT_view", "SEQUENCER_MT_strip",
    "CLIP_MT_editor_menus", "CLIP_MT_view", "CLIP_MT_track", "CLIP_MT_mask",
    "TEXT_MT_editor_menus", "TEXT_MT_view", "TEXT_MT_edit", "TEXT_MT_text",
    "TOPBAR_MT_file", "TOPBAR_MT_edit", "TOPBAR_MT_render", "TOPBAR_MT_window", "TOPBAR_MT_help",
)
_KNOWN_TOOLS = (
    "builtin.select", "builtin.select_box", "builtin.select_circle", "builtin.select_lasso",
    "builtin.move", "builtin.rotate", "builtin.scale", "builtin.transform",
    "builtin.cursor", "builtin.measure", "builtin.primitive_cube_add",
    "builtin.primitive_cylinder_add", "builtin.primitive_cone_add", "builtin.primitive_uv_sphere_add",
    "builtin.extrude_region", "builtin.bevel", "builtin.inset", "builtin.knife",
    "builtin.poly_build", "builtin.poly_quads", "builtin.rip_region", "builtin.shrink_fatten",
    "builtin.edge_face_add", "builtin.subdivide",
)


def _runtime_menu_ids():
    """bl_idnames reachable through the Python subclass tree (broad; misses some RNA-registered bl_ui menus)."""
    out = set()
    def walk(cls):
        for sub in cls.__subclasses__():
            idn = getattr(sub, "bl_idname", None)
            if idn:
                out.add(idn)
            walk(sub)
    walk(bpy.types.Menu)
    return out


def _runtime_tool_ids():
    """Return bl_idnames exposed by registered Python WorkSpaceTool subclasses."""
    out = set()
    seen = set()

    def walk(cls):
        try:
            subclasses = cls.__subclasses__()
        except (AttributeError, TypeError):
            return
        for sub in subclasses:
            if sub in seen:
                continue
            seen.add(sub)
            idn = getattr(sub, "bl_idname", None)
            if isinstance(idn, str) and idn:
                out.add(idn)
            walk(sub)

    try:
        walk(bpy.types.WorkSpaceTool)
    except (AttributeError, TypeError, RuntimeError):
        pass
    return out


def _tool_candidates(extra=()):
    """Combine built-in Tool IDs with IDs from registered custom Workspace Tools."""
    try:
        found = _runtime_tool_ids()
    except Exception:
        found = set()
    found.update(_KNOWN_TOOLS)
    found.update(extra)
    return sorted(found)


def _menu_candidates(extra=()):
    try:
        found = _runtime_menu_ids()
    except Exception:
        found = set()
    found.update(_KNOWN_MENUS)
    found.update(extra)
    return sorted(found)


def _filter(items, query, limit=80):
    q = (query or "").lower()
    return [item for item in items if q in item.lower()][:limit]


def action_id_search(self, context, edit_text):
    """Search Menu, Tool, or Operator identifiers for the selected command type."""
    kind = context.window_manager.allset_se_type
    if kind == "MENU":
        return _filter(_menu_candidates(), edit_text)
    if kind == "TOOL":
        return _filter(_tool_candidates(), edit_text)
    if kind == "OPERATOR":
        return _filter(_operator_ids(), edit_text)
    return _filter(_menu_candidates(), edit_text)


def _operator_props_to_body(value):
    """Convert stored operator properties into JSON members for the brace-wrapped editor."""
    if isinstance(value, str):
        parsed = json.loads(value or "{}")
    else:
        parsed = value if value is not None else {}
    if not isinstance(parsed, dict):
        raise ValueError("Stored Operator Properties must be a JSON object")
    return ",\\n".join(
        json.dumps(key, ensure_ascii=False) + ": " + json.dumps(item, ensure_ascii=False)
        for key, item in parsed.items()
    )


def _parse_operator_props_body(value):
    """Parse JSON object members entered in the Operator Properties field."""
    body = (value or "").strip()
    if not body:
        return {}
    parsed = json.loads("{" + body + "}")
    if not isinstance(parsed, dict):
        raise ValueError("Operator Properties must contain JSON object members")
    return parsed
