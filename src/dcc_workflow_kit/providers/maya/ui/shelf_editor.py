# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya-style Shelf Editor in the kit's floating editor window.

The editor works on a private draft of the existing shelves.json document.
Only Save Changes writes the draft back; Cancel discards it.
"""

import json
import os
import tempfile

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from . import marked_window, shelf, window_places

KIND = "SHELF_EDITOR"
TITLE = "Shelf Editor"

# Shelf Editor layout settings.
# The property list grows with the available window height, within these limits.
PROPERTY_MIN_ROWS = 10
PROPERTY_MAX_ROWS = 40
PROPERTY_ROW_HEIGHT = 22
ADD_MENU_COLUMNS = 2
ICON_PICKER_PAGE_SIZE = 90

_draft = None
_draft_base = None
_loading = False
_OPERATOR_ITEMS = []
_ICON_ITEMS = []
_ICON_HISTORY = []


def _copy_document():
    return json.loads(json.dumps(shelf.user_data()))











def _write_document_atomic(document):
    """Persist a complete shelves.json document atomically and verify the result."""
    path = shelf.store_path()
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n",
                dir=folder, prefix=".shelves-", suffix=".tmp",
                delete=False) as stream:
            temp_path = stream.name
            json.dump(document, stream, indent=1, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())

        with open(temp_path, "r", encoding="utf-8") as stream:
            check = json.load(stream)
        if check != document:
            raise ValueError("Shelf data verification failed before save")

        os.replace(temp_path, path)
        temp_path = None

        with open(path, "r", encoding="utf-8") as stream:
            saved = json.load(stream)
        if saved != document:
            raise ValueError("Saved Shelf data does not match the draft")
        return saved
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _merge_button_lists(base, draft, latest):
    """Merge button sequences while keeping the editor draft authoritative for deletions."""
    from difflib import SequenceMatcher

    base = json.loads(json.dumps(base or []))
    draft = json.loads(json.dumps(draft or []))
    latest = json.loads(json.dumps(latest or []))

    def mapping(source):
        matched = {}
        extras = []
        # Button records are dictionaries, which SequenceMatcher cannot hash.
        # Compare stable JSON signatures while keeping the original records in
        # ``source`` for the merge result below.
        signatures = lambda records: [json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            for record in records]
        matcher = SequenceMatcher(a=signatures(base), b=signatures(source), autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for offset in range(i2 - i1):
                    matched[i1 + offset] = j1 + offset
            elif tag == "replace":
                shared = min(i2 - i1, j2 - j1)
                for offset in range(shared):
                    matched[i1 + offset] = j1 + offset
                # New entries in a replace range are retained as additions.
                extras.extend(source[j1 + shared:j2])
            elif tag == "insert":
                extras.extend(source[j1:j2])
        return matched, extras

    draft_map, _draft_extras = mapping(draft)
    live_map, live_extras = mapping(latest)
    merged = json.loads(json.dumps(draft))

    # Deletions made in the editor are already absent from ``merged`` (a copy of the draft). A record
    # deleted from the live shelf while the editor was open stays deleted when the editor left it
    # unchanged; a record edited in the editor is kept (the edit wins over the live deletion).
    deleted_live = {draft_map[b] for b in range(len(base))
                    if b not in live_map and b in draft_map
                    and draft_map[b] < len(draft) and draft[draft_map[b]] == base[b]}

    # Adopt external edits only where the corresponding draft entry is still unchanged.
    for base_index, live_index in live_map.items():
        draft_index = draft_map.get(base_index)
        if draft_index is None or draft_index >= len(draft) or live_index >= len(latest):
            continue
        if draft[draft_index] == base[base_index] and latest[live_index] != base[base_index]:
            if 0 <= draft_index < len(merged):
                merged[draft_index] = latest[live_index]

    merged = [record for index, record in enumerate(merged) if index not in deleted_live]
    # Preserve external additions (Ctrl+Shift-click, gear menu, settings import).
    merged.extend(json.loads(json.dumps(live_extras)))
    return merged

def _merge_mapping(base, draft, latest):
    """Merge record fields; preserve live values the editor did not modify."""
    result = json.loads(json.dumps(latest))
    missing = object()
    for key in set(base) | set(draft):
        before = base.get(key, missing)
        after = draft.get(key, missing)
        if after == before:
            continue
        if after is missing:
            result.pop(key, None)
        else:
            result[key] = json.loads(json.dumps(after))
    return result


def _merge_shelves(base_shelves, draft_shelves, latest_shelves):
    base_by = {item.get("name"): item for item in base_shelves or []}
    draft_by = {item.get("name"): item for item in draft_shelves or []}
    latest_by = {item.get("name"): item for item in latest_shelves or []}
    merged = []
    for item in draft_shelves or []:
        name = item.get("name")
        before = base_by.get(name)
        latest = latest_by.get(name)
        if before is not None and latest is None:
            # A Shelf deleted from the live settings UI while this editor was open stays deleted.
            continue
        if before is not None and latest is not None:
            current = _merge_mapping(before, item, latest)
            current["buttons"] = _merge_button_lists(
                before.get("buttons", []), item.get("buttons", []), latest.get("buttons", []))
            merged.append(current)
        else:
            merged.append(json.loads(json.dumps(item)))
    for item in latest_shelves or []:
        name = item.get("name")
        if name not in base_by and name not in draft_by:
            merged.append(json.loads(json.dumps(item)))
    return merged


def _merge_documents(base, draft, latest):
    """Three-way merge a Shelf Editor draft with the latest shelves.json document."""
    base, draft, latest = base or {}, draft or {}, latest or {}
    result = json.loads(json.dumps(latest))
    result["shelves"] = _merge_shelves(
        base.get("shelves", []), draft.get("shelves", []), latest.get("shelves", []))
    base_extra = base.get("extra", {}) or {}
    draft_extra = draft.get("extra", {}) or {}
    latest_extra = latest.get("extra", {}) or {}
    extra = json.loads(json.dumps(latest_extra))
    for shelf_id in set(base_extra) | set(draft_extra) | set(latest_extra):
        before = base_extra.get(shelf_id, [])
        after = draft_extra.get(shelf_id, [])
        live = latest_extra.get(shelf_id, [])
        if after != before:
            extra[shelf_id] = _merge_button_lists(before, after, live)
    if extra:
        result["extra"] = extra
    for key in set(base) | set(draft):
        if key in {"shelves", "extra"}:
            continue
        if draft.get(key) != base.get(key):
            if key in draft:
                result[key] = json.loads(json.dumps(draft[key]))
            else:
                result.pop(key, None)
    return result


def _draft_shelves():
    out = [(name, label) for name, label, _buttons in shelf.shelf_data.SHELVES]
    if _draft is not None:
        out.extend((shelf.USER_PREFIX + item["name"], item["name"])
                   for item in _draft.get("shelves", []))
    return out


def _draft_user_shelf(shelf_id):
    if not shelf_id.startswith(shelf.USER_PREFIX) or _draft is None:
        return None
    name = shelf_id[len(shelf.USER_PREFIX):]
    return next((item for item in _draft.get("shelves", []) if item["name"] == name), None)


def _draft_extra(shelf_id, create=False):
    if _draft is None:
        return None
    extra = _draft.get("extra")
    if not isinstance(extra, dict):
        if not create:
            return None
        extra = _draft["extra"] = {}
    if create:
        return extra.setdefault(shelf_id, [])
    return extra.get(shelf_id)


def _draft_buttons(shelf_id, create=False):
    user = _draft_user_shelf(shelf_id)
    if user is not None:
        return user.setdefault("buttons", [])
    if shelf_id.startswith(shelf.USER_PREFIX):
        return None
    if not any(name == shelf_id for name, _label, _buttons in shelf.shelf_data.SHELVES):
        return None
    return _draft_extra(shelf_id, create)


def _factory_rows(shelf_id):
    return shelf.all_buttons(shelf_id) if not shelf_id.startswith(shelf.USER_PREFIX) else []


def _unique_name(base, exclude=None):
    base = (base or "Shelf").strip() or "Shelf"
    names = {item["name"] for item in (_draft or {}).get("shelves", [])
             if item is not exclude}
    if base not in names:
        return base
    index = 2
    while f"{base}{index}" in names:
        index += 1
    return f"{base}{index}"


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


def _wm(context):
    return context.window_manager


_ICON_PICKER_PAGE_KEY = "_allset_shelf_editor_icon_picker_page"


class ALLSET_OT_shelf_editor_icon_page(bpy.types.Operator):
    """Change the page in the currently open Shelf icon picker."""
    bl_idname = "allset.shelf_editor_icon_page"
    bl_label = "Change Icon Page"
    bl_options = {'INTERNAL'}

    direction: IntProperty(default=0, min=-1, max=1, options={'SKIP_SAVE'})
    page_count: IntProperty(default=1, min=1, options={'SKIP_SAVE'})

    def execute(self, context):
        wm = context.window_manager
        current = int(wm.get(_ICON_PICKER_PAGE_KEY, 1))
        wm[_ICON_PICKER_PAGE_KEY] = min(
            max(current + int(self.direction), 1),
            max(int(self.page_count), 1),
        )
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}



ICON_PICKER_GRID_COLUMNS = 18
ICON_PICKER_GRID_ROWS = 20


class ALLSET_PG_shelf_editor_icon_grid_row(bpy.types.PropertyGroup):
    """One horizontal row of icon buttons inside the scrollable picker."""
    icons_json: StringProperty(options={'SKIP_SAVE'})


def _refresh_icon_picker_rows(self, context):
    """Rebuild icon rows after the source or search query changes."""
    if context is None:
        return
    wm = context.window_manager
    collection = getattr(wm, "allset_se_icon_grid_rows", None)
    if collection is None:
        return

    try:
        names = shelf.shelf_icons.icon_names(self.source)
    except (AttributeError, TypeError, ValueError):
        names = []

    query = (self.query or "").casefold()
    if query:
        names = [name for name in names if query in name.casefold()]

    collection.clear()
    columns = ICON_PICKER_GRID_COLUMNS
    for start in range(0, len(names), columns):
        item = collection.add()
        item.icons_json = json.dumps(names[start:start + columns])

    wm.allset_se_icon_grid_rows_index = 0


class ALLSET_UL_shelf_editor_icon_grid(bpy.types.UIList):
    """Native scrollable list with one horizontal strip of icon buttons per row."""
    bl_idname = "ALLSET_UL_shelf_editor_icon_grid"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index, flt_flag=0):
        try:
            names = json.loads(item.icons_json)
        except (TypeError, ValueError):
            names = []

        # Use grid_flow inside each scrollable UIList row. Unlike a plain
        # horizontal row, even_columns makes the icon cells share the full
        # available list width instead of clustering at the left edge.
        grid = layout.grid_flow(
            row_major=True,
            columns=ICON_PICKER_GRID_COLUMNS,
            even_columns=True,
            even_rows=True,
            align=True,
        )
        grid.operator_context = 'EXEC_DEFAULT'
        selected = _wm(context).allset_se_icon

        for column in range(ICON_PICKER_GRID_COLUMNS):
            if column < len(names):
                icon_name = names[column]
                op = grid.operator(
                    ALLSET_OT_shelf_editor_icon_select.bl_idname,
                    text="",
                    emboss=True,
                    depress=(icon_name == selected),
                    **shelf.shelf_icons.icon_ui_kwargs(icon_name),
                )
                op.icon_name = icon_name
            else:
                grid.label(text="")


class ALLSET_OT_shelf_editor_icon_picker(bpy.types.Operator):
    """Browse Blender, PNG, and Maya Workflow Kit shelf icons."""
    bl_idname = "allset.shelf_editor_icon_picker"
    bl_label = "Choose Icon"
    bl_description = "Choose Icon"
    bl_options = {'INTERNAL'}

    query: StringProperty(
        name="Search Icons",
        update=_refresh_icon_picker_rows,
        options={'TEXTEDIT_UPDATE', 'SKIP_SAVE'},
    )
    source: EnumProperty(
        name="Icon Source",
        items=(
            ("ALL", "All Icons", "Blender icons, PNG files, and Maya Workflow Kit drawings"),
            ("BLENDER", "Blender Built-in", "Blender's built-in UI icon identifiers"),
            ("PNG", "PNG Files", "Packaged and user Shelf PNG files"),
            ("MWK", "Maya Workflow Kit", "Procedural icons drawn by Maya Workflow Kit"),
        ),
        default="BLENDER",
        update=_refresh_icon_picker_rows,
        options={'SKIP_SAVE'},
    )
    width: IntProperty(default=640, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        context.window_manager[_ICON_PICKER_PAGE_KEY] = 1
        _refresh_icon_picker_rows(self, context)
        dpi = context.preferences.system.dpi
        scale = context.preferences.system.ui_scale
        self.width = min(max(int(680 * dpi / 72 * scale), 420), context.window.width - 32)
        return context.window_manager.invoke_props_dialog(self, width=self.width)

    def draw(self, context):
        layout = self.layout
        header = layout.row(align=True)
        header.prop(self, "source", text="")
        header.prop(self, "query", text="", icon='VIEWZOOM')
        header.operator(
            ALLSET_OT_shelf_editor_icon_file.bl_idname,
            text="Browse PNG File…",
            icon='FILE_FOLDER',
        )
        wm = _wm(context)
        names = shelf.shelf_icons.icon_names(self.source)
        query = self.query.casefold()
        if query:
            names = [name for name in names if query in name.casefold()]

        history = [name for name in reversed(_ICON_HISTORY)
                   if not query or query in name.casefold()]
        history_box = layout.box()
        history_box.label(text="Recently Used")
        self._draw_icon_history_row(history_box, history[:6], context)

        box = layout.box()
        box.label(text=f"{self._source_label()} ({len(names)} icons)")
        box.template_list(
            ALLSET_UL_shelf_editor_icon_grid.__name__,
            "ALLSET_SHELF_ICON_SCROLL_GRID",
            wm,
            "allset_se_icon_grid_rows",
            wm,
            "allset_se_icon_grid_rows_index",
            rows=ICON_PICKER_GRID_ROWS,
            maxrows=ICON_PICKER_GRID_ROWS,
            type='DEFAULT',
        )

    def _source_label(self):
        return {
            "ALL": "All Icons",
            "BLENDER": "Blender Icons",
            "PNG": "PNG Icons",
            "MWK": "Maya Workflow Kit Icons",
        }[self.source]

    def _draw_icon_history_row(self, layout, names, context):
        """Draw one fixed six-cell row of recently used icon buttons."""
        row = layout.row(align=True)
        grid = row.grid_flow(row_major=True, columns=6,
                             even_columns=True, even_rows=True, align=True)
        grid.operator_context = 'EXEC_DEFAULT'
        selected = _wm(context).allset_se_icon
        for index in range(6):
            icon_name = names[index] if index < len(names) else None
            if icon_name:
                op = grid.operator(
                    ALLSET_OT_shelf_editor_icon_select.bl_idname,
                    text="",
                    emboss=True,
                    depress=(icon_name == selected),
                    **shelf.shelf_icons.icon_ui_kwargs(icon_name),
                )
                op.icon_name = icon_name
            else:
                # Empty cells preserve the same six-column footprint.
                grid.label(text="")

    def _draw_icon_grid(self, layout, names, context):
        # A fixed 18 x 5 page uses the available picker width more efficiently.
        # The page size is 90, preserving the same five-row canvas height.
        columns = 18
        grid = layout.grid_flow(row_major=True, columns=columns,
                                even_columns=True, even_rows=True, align=True)
        selected = _wm(context).allset_se_icon
        grid.operator_context = 'EXEC_DEFAULT'
        for name in names:
            op = grid.operator(
                ALLSET_OT_shelf_editor_icon_select.bl_idname,
                text="",
                emboss=True,
                depress=(name == selected),
                **shelf.shelf_icons.icon_ui_kwargs(name),
            )
            op.icon_name = name

    def execute(self, context):
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_icon_select(bpy.types.Operator):
    """Apply the selected icon to the current Shelf button."""
    bl_idname = "allset.shelf_editor_icon_select"
    bl_label = "Select Shelf Icon"
    bl_description = "Select Shelf Icon"
    bl_options = {'INTERNAL'}

    icon_name: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        if self.icon_name in _ICON_HISTORY:
            _ICON_HISTORY.remove(self.icon_name)
        _ICON_HISTORY.append(self.icon_name)
        del _ICON_HISTORY[:-20]
        _wm(context).allset_se_icon = self.icon_name
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_icon_file(bpy.types.Operator, ImportHelper):
    """Use any PNG file as this Shelf button's icon."""
    bl_idname = "allset.shelf_editor_icon_file"
    bl_label = "Choose PNG Shelf Icon"
    bl_description = "Select a PNG file for the current Shelf button"
    bl_options = {'INTERNAL'}

    filter_glob: StringProperty(default="*.png", options={'HIDDEN'})

    def execute(self, context):
        path = os.path.abspath(bpy.path.abspath(self.filepath))
        if not path.lower().endswith(".png") or not os.path.isfile(path):
            self.report({'WARNING'}, "Choose an existing PNG image")
            return {'CANCELLED'}
        _wm(context).allset_se_icon = path
        if path in _ICON_HISTORY:
            _ICON_HISTORY.remove(path)
        _ICON_HISTORY.append(path)
        del _ICON_HISTORY[:-20]
        _redraw(context)
        return {'FINISHED'}



def _set_message(context, message):
    _wm(context).allset_se_message = message


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


def _load_button(context, index):
    """Load one draft button into the transient editor fields.

    Reset every field first so values from a previously selected button can
    never leak into the next button's editor state.
    """
    global _loading
    wm = _wm(context)
    shelf_id = wm.allset_se_shelf
    buttons = _draft_buttons(shelf_id) or []
    _loading = True
    try:
        # Reset the complete transient form, not only fields used by the
        # incoming button type. All of these properties are SKIP_SAVE data.
        wm.allset_se_index = -1
        wm.allset_se_label = ""
        wm.allset_se_icon = "SCRIPT"
        wm.allset_se_type = "PYTHON"
        wm.allset_se_script = "import bpy\n\nbpy.ops.mesh.primitive_cube_add()"
        wm.allset_se_menu = ""
        wm.allset_se_operator = "mesh.primitive_cube_add"
        wm.allset_se_props = ""
        wm.allset_se_tooltip = ""
        wm.allset_se_action_id = "VIEW3D_MT_view"
        wm.allset_se_action_code = ""
        wm.allset_se_space_type = "AUTO"
        wm.allset_se_required_mode = "AUTO"
        wm.allset_se_object_type = "AUTO"
        wm.allset_se_tool_space_type = "AUTO"
        wm.allset_se_tool_mode = "AUTO"

        if not 0 <= index < len(buttons):
            return

        button = buttons[index]
        action = button.get("action") or {}
        wm.allset_se_index = index
        wm.allset_se_label = button.get("label", "Button")
        wm.allset_se_icon = button.get("icon", "SCRIPT")
        wm.allset_se_tooltip = button.get("tooltip", "")
        wm.allset_se_space_type = action.get(
            "space_type", button.get("space_type", "AUTO")
        )
        wm.allset_se_required_mode = action.get(
            "required_mode", action.get("mode", button.get("required_mode", "AUTO"))
        )
        wm.allset_se_object_type = action.get(
            "object_type", button.get("object_type", "AUTO")
        )
        if button.get("type") == "separator" or action.get("type") == "separator":
            wm.allset_se_type = "SEPARATOR"
        elif button.get("menu"):
            wm.allset_se_type = "MAYA_MENU_ITEM"
            wm.allset_se_menu = button["menu"]
        elif button.get("operator"):
            wm.allset_se_type = "OPERATOR"
            wm.allset_se_operator = button["operator"]
            wm.allset_se_props = _operator_props_to_body(button.get("props", {}))
        elif button.get("type") == "action":
            kind = action.get("type", "operator")
            wm.allset_se_action_id = action.get("id", "")
            wm.allset_se_action_code = action.get("code", "")
            wm.allset_se_props = _operator_props_to_body(action.get("properties", {}))
            if kind == "operator":
                wm.allset_se_type = "OPERATOR"
                wm.allset_se_operator = action.get("id", "")
            elif kind == "maya_menu":
                wm.allset_se_type = "MAYA_MENU_ITEM"
                wm.allset_se_menu = action.get("id", "")
            elif kind == "python":
                wm.allset_se_type = "PYTHON"
                wm.allset_se_script = action.get("code", "")
            elif kind == "tool":
                wm.allset_se_type = "TOOL"
                wm.allset_se_tool_space_type = action.get("space_type", "AUTO")
                wm.allset_se_tool_mode = action.get(
                    "required_mode", action.get("mode", "AUTO")
                )
            elif kind in {"blender_menu", "pie_menu"}:
                wm.allset_se_type = "MENU"
            elif kind == "ui_operator":
                # Legacy UI Operator records remain editable as ordinary Operators.
                wm.allset_se_type = "OPERATOR"
                wm.allset_se_operator = action.get("id", "")
            else:
                wm.allset_se_type = "PYTHON"
                wm.allset_se_script = action.get("code", "")
        else:
            # Legacy script buttons remain readable; Apply writes action.python.
            wm.allset_se_type = "PYTHON"
            wm.allset_se_script = button.get("script", "")
    finally:
        _loading = False


def _start_draft(context):
    global _draft, _draft_base
    if _draft is None:
        shelf.reload_user()
        _draft = _copy_document()
        _draft_base = _copy_document()
    elif marked_window.find_window(context, KIND) is None:
        # Closing the native floating window must not silently discard the in-memory draft.
        # Reconcile any Shelf changes made through the gear menu while the editor was closed.
        shelf.reload_user()
        latest = _copy_document()
        if _draft != (_draft_base or latest):
            _draft = _merge_documents(_draft_base or latest, _draft, latest)
        else:
            # Independent copy: never alias _draft to the document that becomes _draft_base,
            # otherwise a later Apply would mutate the base and the first Save's three-way
            # merge would revert the just-applied change.
            _draft = json.loads(json.dumps(latest))
        _draft_base = json.loads(json.dumps(latest))
    wm = _wm(context)
    current = shelf.current(context)
    valid = {identifier for identifier, _label in _draft_shelves()}
    wm.allset_se_shelf = current if current in valid else _draft_shelves()[0][0]
    wm.allset_se_message = ""
    _load_button(context, -1)


def open_editor(context):
    _start_draft(context)
    # Use the requested 800 x 1000 Maya-style default independent of the source 3D View size.
    # A one-time marker migrates older oversized saved rectangles while preserving
    # any user-resized dimensions on subsequent launches.
    from . import window_places
    if context.window is not None:
        place_kind = f"marked:{KIND}"
        size_marker = f"{place_kind}_SIZE_V4"
        if window_places.place(size_marker) is None:
            source = context.window
            width, height = 800, 1000
            x = source.x + max(20, (source.width - width) // 2)
            y = source.y + max(20, (source.height - height) // 2)
            window_places.remember(place_kind, (x, y, width, height))
            window_places.remember(size_marker, (2, 0, 0, 0))
        elif window_places.place(place_kind) is None:
            source = context.window
            width, height = 800, 1000
            x = source.x + max(20, (source.width - width) // 2)
            y = source.y + max(20, (source.height - height) // 2)
            window_places.remember(place_kind, (x, y, width, height))
    window = marked_window.open_window(context, KIND)
    if window is None:
        return None
    for area in window.screen.areas:
        area.tag_redraw()
    return window


def _redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


class ALLSET_OT_shelf_editor_open(bpy.types.Operator):
    """Open the Maya-style floating Shelf Editor"""
    bl_idname = "allset.shelf_editor_open"
    bl_label = "Shelf Editor"

    def execute(self, context):
        if open_editor(context) is None:
            # A compact editor area may need to be carved across timer ticks.
            # In that case the opening operator is intentionally re-run later;
            # do not report a failure for this deferred first pass.
            from . import window_places
            if window_places.deferred():
                return {'FINISHED'}
            self.report({'ERROR'}, "Could not open the Shelf Editor window")
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_select_shelf(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_select_shelf"
    bl_label = "Select Shelf"
    bl_options = {'INTERNAL'}

    shelf_id: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        wm = _wm(context)
        if self.shelf_id not in {identifier for identifier, _label in _draft_shelves()}:
            return {'CANCELLED'}
        wm.allset_se_shelf = self.shelf_id
        wm.allset_se_shelves_index = next(
            (index for index, (shelf_id, _label) in enumerate(_draft_shelves())
             if shelf_id == self.shelf_id),
            wm.allset_se_shelves_index,
        )
        _load_button(context, -1)
        _set_message(context, "")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_select_button(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_select_button"
    bl_label = "Select Button"
    bl_options = {'INTERNAL'}

    index: IntProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        wm = _wm(context)
        _load_button(context, self.index)

        # Keep the native UIList active row aligned with the selected editable
        # button. Factory rows are read-only and must not retain the active-row
        # highlight when a custom button is selected.
        for row_index, item in enumerate(wm.allset_se_items):
            if not item.is_factory and item.button_index == self.index:
                wm.allset_se_list_index = row_index
                break

        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_add_shelf(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_add_shelf"
    bl_label = "New Shelf"

    name: StringProperty(name="Shelf Name", default="Custom")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300)

    def execute(self, context):
        global _draft
        if _draft is None:
            return {'CANCELLED'}
        name = _unique_name(self.name)
        _draft.setdefault("shelves", []).append({"name": name, "buttons": []})
        _wm(context).allset_se_shelf = shelf.USER_PREFIX + name
        _load_button(context, -1)
        _set_message(context, f"Created shelf: {name} (not saved yet)")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_rename_shelf(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_rename_shelf"
    bl_label = "Rename Shelf"

    name: StringProperty(name="New Name")

    @classmethod
    def poll(cls, context):
        return _draft_user_shelf(_wm(context).allset_se_shelf) is not None

    def invoke(self, context, event):
        self.name = _wm(context).allset_se_shelf[len(shelf.USER_PREFIX):]
        return context.window_manager.invoke_props_dialog(self, width=300)

    def execute(self, context):
        wm = _wm(context)
        item = _draft_user_shelf(wm.allset_se_shelf)
        if item is None:
            return {'CANCELLED'}
        old_id = wm.allset_se_shelf
        name = _unique_name(self.name, exclude=item)
        item["name"] = name
        wm.allset_se_shelf = shelf.USER_PREFIX + name
        _set_message(context, f"Renamed {old_id} to {name} (not saved yet)")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_duplicate_shelf(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_duplicate_shelf"
    bl_label = "Duplicate Shelf"

    def execute(self, context):
        item = _draft_user_shelf(_wm(context).allset_se_shelf)
        if item is None:
            self.report({'WARNING'}, "Only user shelves can be duplicated")
            return {'CANCELLED'}
        duplicate = json.loads(json.dumps(item))
        duplicate["name"] = _unique_name(item["name"] + " Copy")
        _draft["shelves"].append(duplicate)
        _wm(context).allset_se_shelf = shelf.USER_PREFIX + duplicate["name"]
        _load_button(context, -1)
        _set_message(context, f"Duplicated shelf: {duplicate['name']} (not saved yet)")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_delete_shelf(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_delete_shelf"
    bl_label = "Delete Shelf"

    @classmethod
    def poll(cls, context):
        return (_draft_user_shelf(_wm(context).allset_se_shelf) is not None
                and len((_draft or {}).get("shelves", [])) > 1)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        wm = _wm(context)
        item = _draft_user_shelf(wm.allset_se_shelf)
        if item is None:
            return {'CANCELLED'}
        _draft["shelves"].remove(item)
        wm.allset_se_shelf = _draft_shelves()[0][0]
        _load_button(context, -1)
        _set_message(context, "Shelf deleted from the draft (not saved yet)")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_move_shelf(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_move_shelf"
    bl_label = "Move Shelf"

    direction: EnumProperty(items=(("UP", "Up", ""), ("DOWN", "Down", "")))

    def execute(self, context):
        wm = _wm(context)
        item = _draft_user_shelf(wm.allset_se_shelf)
        if item is None:
            return {'CANCELLED'}
        items = _draft["shelves"]
        index = items.index(item)
        target = index + (-1 if self.direction == "UP" else 1)
        if not 0 <= target < len(items):
            return {'CANCELLED'}
        items[index], items[target] = items[target], items[index]
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_add_button(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_add_button"
    bl_label = "Add Button"

    def execute(self, context):
        wm = _wm(context)
        buttons = _draft_buttons(wm.allset_se_shelf, create=True)
        if buttons is None:
            self.report({'WARNING'}, "This shelf does not accept custom buttons")
            return {'CANCELLED'}
        buttons.append({"label": "New Button", "icon": "SCRIPT", "script": "print('Hello')"})
        _load_button(context, len(buttons) - 1)
        _set_message(context, "New button added to the draft; edit its properties")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_MT_shelf_editor_add_action(bpy.types.Menu):
    bl_idname = "ALLSET_MT_shelf_editor_add_action"
    bl_label = "Add Shelf Button"

    def draw(self, context):
        flow = self.layout.column_flow(columns=ADD_MENU_COLUMNS, align=True)
        choices = (
            ("OPERATOR", "Operator", "CONSOLE", "Blender Operator"),
            ("MAYA_MENU_ITEM", "Maya Menu Item", "LINENUMBERS_ON", "Maya Workflow Kit menu path"),
            ("MENU", "Menu", "MENU_PANEL", "Blender native Menu or MayaWorkflow Menu ID"),
            ("TOOL", "Tool", "TOOL_SETTINGS", "Activate a Blender Tool"),
            ("PYTHON", "Python", "CONSOLE", "Python command"),
            ("SEPARATOR", "Separator", "REMOVE", "Visual separator"),
        )
        for kind, label, icon, tip in choices:
            op = flow.operator(
                ALLSET_OT_shelf_editor_create_action.bl_idname,
                text=label,
                icon=icon,
            )
            op.action_type = kind
            op.help_text = tip


class ALLSET_OT_shelf_editor_create_action(bpy.types.Operator):
    """Create a Shelf button using the selected command type."""
    bl_idname = "allset.shelf_editor_create_action"
    bl_label = "Add Shelf Button"
    bl_description = "Create a Shelf button using the selected command type."

    action_type: StringProperty(options={'HIDDEN'})
    help_text: StringProperty(options={'HIDDEN'})
    label: StringProperty(name="Label", default="New Button")
    icon: StringProperty(name="Icon", default="SCRIPT", search=icon_search)
    tooltip: StringProperty(name="Tooltip")
    target: StringProperty(name="Command / ID", search=action_id_search)
    code: StringProperty(
        name="Python",
        default="import bpy\\n\\nbpy.ops.mesh.primitive_cube_add()",
    )
    properties_json: StringProperty(name="Operator Properties", default="{}")

    @classmethod
    def description(cls, context, properties):
        return properties.help_text or "Add a Shelf button using the selected command type."

    def invoke(self, context, event):
        if self.action_type == "OPERATOR":
            self.label = "Add Cube"
            self.icon = "MESH_CUBE"
            self.target = "mesh.primitive_cube_add"
        elif self.action_type == "MAYA_MENU_ITEM":
            self.label = "Create Cube"
            self.target = "Create/Polygon Primitives/Cube"
        elif self.action_type == "MENU":
            self.label = "View Menu"
            self.target = "VIEW3D_MT_view"
        elif self.action_type == "TOOL":
            self.label = "Move Tool"
            self.target = "builtin.move"
        elif self.action_type == "PYTHON":
            self.label = "Python: Add Cube"
            self.code = "import bpy\\n\\nbpy.ops.mesh.primitive_cube_add()"
        return self.execute(context)

    def execute(self, context):
        buttons = _draft_buttons(_wm(context).allset_se_shelf, create=True)
        if buttons is None:
            self.report({'WARNING'}, "This shelf does not accept custom buttons")
            return {'CANCELLED'}

        record = {
            "label": self.label.strip() or "New Button",
            "icon": shelf._valid_icon(self.icon),
            "tooltip": self.tooltip.strip(),
        }
        kind = self.action_type
        if kind == "SEPARATOR":
            record["label"] = "Separator"
            record["icon"] = "NONE"
            record.update(type="separator", action={"type": "separator"})
        elif kind == "OPERATOR":
            record.update(type="action", action={
                "type": "operator",
                "id": self.target.strip() or "mesh.primitive_cube_add",
                "properties": json.loads(self.properties_json or "{}"),
                "space_type": "VIEW_3D",
            })
        elif kind == "MAYA_MENU_ITEM":
            record["menu"] = self.target.strip() or "Create/Polygon Primitives/Cube"
            record["space_type"] = "VIEW_3D"
        elif kind == "MENU":
            record.update(type="action", action={
                "type": "blender_menu",
                "id": self.target.strip() or "VIEW3D_MT_view",
                "space_type": "VIEW_3D",
            })
        elif kind == "TOOL":
            record.update(type="action", action={
                "type": "tool",
                "id": self.target.strip() or "builtin.move",
                "space_type": "VIEW_3D",
            })
        elif kind == "PYTHON":
            code = self.code.strip() or "import bpy\\n\\nbpy.ops.mesh.primitive_cube_add()"
            record.update(type="action", action={"type": "python", "code": code})
        else:
            return {'CANCELLED'}

        buttons.append(record)
        _load_button(context, len(buttons) - 1)
        _set_message(context, f"Added {record['label']} to draft; edit its properties below")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_apply_button(bpy.types.Operator):
    """Apply edited Shelf button properties without changing unrelated button data."""
    bl_idname = "allset.shelf_editor_apply_button"
    bl_label = "Apply Button Changes"

    def execute(self, context):
        wm = _wm(context)
        buttons = _draft_buttons(wm.allset_se_shelf, create=True)
        index = wm.allset_se_index
        if buttons is None or not 0 <= index < len(buttons):
            self.report({'WARNING'}, "Select a custom button first")
            return {'CANCELLED'}

        old = buttons[index]
        record = dict(old)
        label = wm.allset_se_label.strip() or "Button"
        record["label"] = label
        record["icon"] = shelf._valid_icon(wm.allset_se_icon)
        record["tooltip"] = wm.allset_se_tooltip.strip()
        kind = wm.allset_se_type
        space_type = wm.allset_se_space_type

        if kind == "SEPARATOR":
            record["icon"] = "NONE"
            record.pop("menu", None)
            record.pop("script", None)
            record.pop("operator", None)
            record.pop("props", None)
            record.pop("space_type", None)
            record.update(type="separator", action={"type": "separator"})
        elif kind == "MAYA_MENU_ITEM":
            from . import menu_map
            path = wm.allset_se_menu.strip()
            if path not in menu_map.MAP:
                self.report({'WARNING'}, "Choose a valid Maya menu item")
                return {'CANCELLED'}
            record["menu"] = path
            record["space_type"] = space_type
            record["required_mode"] = wm.allset_se_required_mode
            record["object_type"] = wm.allset_se_object_type
            record.pop("script", None)
            record.pop("type", None)
            record.pop("action", None)
            record.pop("operator", None)
            record.pop("props", None)
        elif kind == "MENU":
            target = wm.allset_se_action_id.strip()
            if not target or bpy.types.Menu.bl_rna_get_subclass_py(target) is None:
                self.report({'WARNING'}, "Choose a registered Blender or MayaWorkflow Menu ID")
                return {'CANCELLED'}
            record.pop("menu", None)
            record.pop("script", None)
            record.update(type="action", action={
                "type": "blender_menu",
                "id": target,
                "space_type": space_type,
                "required_mode": wm.allset_se_required_mode,
                "object_type": wm.allset_se_object_type,
            })
        elif kind == "OPERATOR":
            op_id = wm.allset_se_operator.strip()
            if op_id not in _operator_ids():
                self.report({'WARNING'}, "Choose a valid Blender Operator")
                return {'CANCELLED'}
            # Operator parameters are edited as JSON members between UI-supplied braces.
            # An empty field means no explicit overrides: {}.
            try:
                props = _parse_operator_props_body(wm.allset_se_props)
            except (TypeError, ValueError) as ex:
                self.report({'WARNING'}, f"Operator Properties must be valid JSON: {ex}")
                return {'CANCELLED'}
            if not isinstance(props, dict):
                self.report({'WARNING'}, "Operator Properties must be a JSON object, for example {}")
                return {'CANCELLED'}
            problem = _validate_operator_properties(op_id, props)
            if problem:
                self.report({'WARNING'}, problem)
                return {'CANCELLED'}
            record.pop("menu", None)
            record.pop("script", None)
            record.pop("operator", None)
            record.pop("props", None)
            record.update(type="action", action={
                "type": "operator",
                "id": op_id,
                "properties": props,
                "space_type": space_type,
                "required_mode": wm.allset_se_required_mode,
                "object_type": wm.allset_se_object_type,
            })
        elif kind == "PYTHON":
            code = wm.allset_se_script
            if not code.strip():
                self.report({'WARNING'}, "Python command cannot be empty")
                return {'CANCELLED'}
            record.pop("menu", None)
            record.pop("script", None)
            record.pop("operator", None)
            record.pop("props", None)
            record.update(type="action", action={"type": "python", "code": code})
        elif kind == "TOOL":
            target = wm.allset_se_action_id.strip()
            if not target:
                self.report({'WARNING'}, "Enter a Tool ID")
                return {'CANCELLED'}
            record.pop("menu", None)
            record.pop("script", None)
            record.update(type="action", action={
                "type": "tool",
                "id": target,
                "space_type": wm.allset_se_tool_space_type,
                "required_mode": wm.allset_se_tool_mode,
                "object_type": wm.allset_se_object_type,
            })
        else:
            self.report({'WARNING'}, "Unsupported Shelf button type")
            return {'CANCELLED'}

        # Commit the record to the draft before refreshing any transient UI.
        # Keep the selected button index stable and immediately rebuild the
        # visible Shelf Contents rows so the first Apply is reflected at once.
        buttons[index] = record

        # The contents UIList is a cached WindowManager collection. Updating
        # _draft alone does not guarantee that its label/icon rows are refreshed
        # during this operator execution.
        _sync_contents_list(wm, wm.allset_se_shelf)
        _sync_properties_list(wm)

        _set_message(context, f"Updated: {label} (not saved yet)")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_delete_button(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_delete_button"
    bl_label = "Delete Button"

    def execute(self, context):
        wm = _wm(context)
        buttons = _draft_buttons(wm.allset_se_shelf) or []
        index = wm.allset_se_index
        if not 0 <= index < len(buttons):
            return {'CANCELLED'}
        del buttons[index]
        _load_button(context, min(index, len(buttons) - 1))
        _set_message(context, "Button deleted from the draft (not saved yet)")
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_move_button(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_move_button"
    bl_label = "Move Button"

    direction: EnumProperty(items=(("UP", "Up", ""), ("DOWN", "Down", "")))

    def execute(self, context):
        wm = _wm(context)
        buttons = _draft_buttons(wm.allset_se_shelf) or []
        index = wm.allset_se_index
        target = index + (-1 if self.direction == "UP" else 1)
        if not 0 <= index < len(buttons) or not 0 <= target < len(buttons):
            return {'CANCELLED'}
        buttons[index], buttons[target] = buttons[target], buttons[index]
        _load_button(context, target)
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_save(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_save"
    bl_label = "Save Changes"

    def execute(self, context):
        global _draft, _draft_base
        if _draft is None:
            return {'CANCELLED'}

        wm = _wm(context)
        active = wm.allset_se_shelf

        # Save must commit the currently visible form into the in-memory draft
        # first. The editor fields are transient WindowManager properties and
        # are intentionally not written by _write_document_atomic(). Reuse the
        # same validation and record-building path as the explicit Apply button
        # so icons, labels, tooltips, command data and Operator properties all
        # follow identical rules.
        if 0 <= wm.allset_se_index < len(_draft_buttons(active) or []):
            apply_result = bpy.ops.allset.shelf_editor_apply_button()
            if 'CANCELLED' in apply_result:
                _set_message(context, "Save cancelled: current button changes were not applied")
                _redraw(context)
                return {'CANCELLED'}

        # Freeze the editor state before touching the live shelf cache.  The
        # draft is deliberately independent from shelf._user, but keeping an
        # immutable snapshot here also prevents a refresh from replacing the
        # only copy of newly added factory-shelf extras.
        draft_snapshot = json.loads(json.dumps(_draft))
        base_snapshot = json.loads(json.dumps(_draft_base or {}))

        try:
            # Read the latest on-disk document.  When nobody changed the file
            # outside this editor, persist the draft verbatim; only invoke the
            # three-way merge when a genuine external change is detected.
            shelf.reload_user()
            latest = _copy_document()
            if latest == base_snapshot:
                merged = draft_snapshot
            else:
                merged = _merge_documents(base_snapshot, draft_snapshot, latest)

            saved = _write_document_atomic(merged)

            # Verify the editor's changed factory extras survived the merge
            # and disk round-trip before replacing the in-memory draft.
            draft_extra = draft_snapshot.get("extra", {}) or {}
            base_extra = base_snapshot.get("extra", {}) or {}
            saved_extra = saved.get("extra", {}) or {}
            for shelf_id, buttons in draft_extra.items():
                if buttons != base_extra.get(shelf_id, []):
                    if saved_extra.get(shelf_id, []) != merged.get("extra", {}).get(shelf_id, []):
                        raise ValueError(
                            f"Factory shelf '{shelf_id}' extras failed save verification"
                        )

            # Update the existing cache object in place because other shelf
            # UI callbacks may already hold references to it.
            shelf._user.clear()
            shelf._user.update(saved)

        except Exception as ex:
            # Keep the editor draft and its visible list intact on failure.
            self.report({'ERROR'}, f"Could not save Shelf data: {ex}")
            _set_message(context, f"Save failed; draft kept: {ex}")
            _redraw(context)
            return {'CANCELLED'}

        # Only after the verified write succeeds may the draft be replaced.
        _draft = json.loads(json.dumps(saved))
        _draft_base = json.loads(json.dumps(saved))

        valid = {identifier for identifier, _label in shelf.shelves()}
        if active in valid:
            shelf.set_current(context, active)

        # Rebuild the transient UIList from the committed document now, rather
        # than relying on a later draw to notice a stale signature.
        _sync_shelves_list(wm)
        _sync_contents_list(wm, active)
        if 0 <= wm.allset_se_index < len(_draft_buttons(active) or []):
            _load_button(context, wm.allset_se_index)
        else:
            _load_button(context, -1)

        saved_count = len(_draft_buttons(active) or [])
        _set_message(context, f"Shelf changes saved ({saved_count} custom button(s) on this shelf)")
        shelf.shelf_icons.invalidate_gpu_textures()
        _redraw(context)
        # The first save of a session needs a second redraw frame once the
        # operator has returned (GPU texture release/create lifecycle); harmless
        # on every later save.
        shelf.schedule_redraw()
        return {'FINISHED'}


class ALLSET_OT_shelf_editor_cancel(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_cancel"
    bl_label = "Discard Changes"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        global _draft, _draft_base
        shelf.reload_user()
        _draft = _copy_document()
        _draft_base = _copy_document()
        wm = _wm(context)
        valid = {identifier for identifier, _label in _draft_shelves()}
        wm.allset_se_shelf = shelf.current(context) if shelf.current(context) in valid else _draft_shelves()[0][0]
        _load_button(context, -1)
        _set_message(context, "Unsaved changes discarded")
        _redraw(context)
        return {'FINISHED'}



class ALLSET_PG_shelf_editor_list_item(bpy.types.PropertyGroup):
    """Transient row data used by the scrollable Shelf Contents list."""
    label: StringProperty()
    icon: StringProperty(default="NONE")
    button_index: IntProperty(default=-1)
    is_factory: BoolProperty(default=False)
    shelf_id: StringProperty()
    field: StringProperty()
    row_kind: StringProperty(default="FIELD")


class ALLSET_UL_shelf_editor_shelves(bpy.types.UIList):
    """Independent scrollable list of shelves."""
    bl_idname = "ALLSET_UL_shelf_editor_shelves"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index=0, flt_flag=0):
        row = layout.row(align=True)
        selected = data.allset_se_shelf == item.shelf_id
        op = row.operator(
            ALLSET_OT_shelf_editor_select_shelf.bl_idname,
            text=item.label,
            icon='RADIOBUT_ON' if selected else 'RADIOBUT_OFF',
            depress=selected,
        )
        op.shelf_id = item.shelf_id


class ALLSET_UL_shelf_editor_properties(bpy.types.UIList):
    """Fixed-height, independently scrollable Button Properties editor."""
    bl_idname = "ALLSET_UL_shelf_editor_properties"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index=0, flt_flag=0):
        if item.row_kind == "INFO":
            layout.label(text=item.label, icon='INFO')
            return
        if item.field and hasattr(data, item.field):
            if item.field == "allset_se_icon":
                row = layout.row(align=True)
                row.prop(data, item.field, text=item.label)
                row.operator(
                    ALLSET_OT_shelf_editor_icon_picker.bl_idname,
                    text="",
                    **shelf.shelf_icons.icon_ui_kwargs(data.allset_se_icon or "SCRIPT"),
                )
                return
            layout.prop(data, item.field, text=item.label)


class ALLSET_UL_shelf_editor_contents(bpy.types.UIList):
    """Keep long Shelf Contents lists scrollable without scrolling the editor footer."""
    bl_idname = "ALLSET_UL_shelf_editor_contents"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index=0, flt_flag=0):
        row = layout.row(align=True)
        if item.is_factory:
            # Factory rows may carry a procedural MWK icon identifier. Blender's
            # ``icon`` argument only accepts built-in enum identifiers, so resolve
            # custom preview icons through the preview collection instead.
            icon_kwargs = shelf.shelf_icons.icon_ui_kwargs(
                item.icon if item.icon != 'NONE' else 'DOT')
            row.label(text=item.label, **icon_kwargs)
            row.label(text="Factory", icon='LOCKED')
            return

        icon_kwargs = shelf.shelf_icons.icon_ui_kwargs(item.icon if item.icon != 'NONE' else 'DOT')
        op = row.operator(
            ALLSET_OT_shelf_editor_select_button.bl_idname,
            text=item.label,
            depress=data.allset_se_index == item.button_index,
            **icon_kwargs,
        )
        op.index = item.button_index
        if data.allset_se_index == item.button_index:
            controls = row.row(align=True)
            move_up = controls.operator(ALLSET_OT_shelf_editor_move_button.bl_idname,
                                        text="", icon='TRIA_UP')
            move_up.direction = "UP"
            move_down = controls.operator(ALLSET_OT_shelf_editor_move_button.bl_idname,
                                          text="", icon='TRIA_DOWN')
            move_down.direction = "DOWN"
            controls.operator(ALLSET_OT_shelf_editor_delete_button.bl_idname,
                              text="", icon='TRASH')


def _sync_contents_list(wm, shelf_id):
    """Refresh transient UIList data only when the visible rows actually change."""
    rows = []
    if shelf_id.startswith(shelf.USER_PREFIX):
        for index, button in enumerate(_draft_buttons(shelf_id) or []):
            rows.append((button.get("label", "Button"),
                         shelf._valid_icon(button.get("icon", "SCRIPT")),
                         index, False))
    else:
        for index, label, _action, icon in _factory_rows(shelf_id):
            if shelf.shelf_icons.icon_for(label, shelf_id, index) is not None:
                icon = f"MWK:{shelf_id}/{label}#{index}"
            rows.append((label, icon, -1, True))
        for index, button in enumerate(_draft_buttons(shelf_id) or []):
            rows.append((button.get("label", "Button"),
                         shelf._valid_icon(button.get("icon", "SCRIPT")),
                         index, False))

    signature = repr((shelf_id, rows))
    current_rows = [(item.label, item.icon, item.button_index, item.is_factory)
                    for item in wm.allset_se_items]
    if wm.allset_se_items_signature == signature and current_rows == rows:
        return
    collection = wm.allset_se_items
    collection.clear()
    for label, icon, button_index, is_factory in rows:
        item = collection.add()
        item.label = label
        item.icon = icon
        item.button_index = button_index
        item.is_factory = is_factory
    wm.allset_se_items_signature = signature
    wm.allset_se_list_index = min(wm.allset_se_list_index, max(0, len(rows) - 1))


def _sync_shelves_list(wm):
    """Refresh shelf rows while preserving the independent scroll position."""
    rows = _draft_shelves()
    signature = repr(rows)
    if wm.allset_se_shelves_signature == signature:
        return
    collection = wm.allset_se_shelves
    collection.clear()
    for shelf_id, label in rows:
        item = collection.add()
        item.shelf_id = shelf_id
        item.label = label
        item.icon = 'RADIOBUT_OFF'
    wm.allset_se_shelves_signature = signature
    selected_index = next((index for index, (shelf_id, _label) in enumerate(rows)
                           if shelf_id == wm.allset_se_shelf), 0)
    wm.allset_se_shelves_index = min(selected_index, max(0, len(rows) - 1))


def _sync_properties_list(wm):
    """Build the fixed editor fields; Operator Properties remain plain JSON."""
    rows = [
        ("FIELD", "allset_se_label", "Label"),
        ("FIELD", "allset_se_icon", "Icon"),
        ("FIELD", "allset_se_type", "Command Type"),
    ]
    kind = wm.allset_se_type
    if kind == "PYTHON":
        rows.append(("FIELD", "allset_se_script", "Python"))
    elif kind == "MAYA_MENU_ITEM":
        rows.extend((
            ("FIELD", "allset_se_menu", "Maya Menu Item"),
            ("FIELD", "allset_se_space_type", "Editor Space"),
        ))
    elif kind == "MENU":
        rows.extend((
            ("FIELD", "allset_se_action_id", "Menu ID"),
            ("INFO", "", "Blender native Menu or MayaWorkflow Menu · XXX_MT_xxx"),
            ("FIELD", "allset_se_space_type", "Editor Space"),
            ("FIELD", "allset_se_required_mode", "Required Mode"),
            ("FIELD", "allset_se_object_type", "Object Type"),
        ))
    elif kind == "OPERATOR":
        rows.extend((
            ("FIELD", "allset_se_operator", "Operator ID"),
            ("FIELD", "allset_se_props", "Operator Properties (JSON)"),
            ("INFO", "", "Leave empty to use the Operator default properties."),
            ("FIELD", "allset_se_space_type", "Editor Space"),
            ("FIELD", "allset_se_required_mode", "Required Mode"),
            ("FIELD", "allset_se_object_type", "Object Type"),
        ))
    elif kind == "TOOL":
        rows.extend((
            ("FIELD", "allset_se_action_id", "Tool ID"),
            ("INFO", "", "Built-in tools and registered custom Workspace Tools are searchable; other IDs can be entered manually."),
            ("FIELD", "allset_se_tool_space_type", "Tool Editor"),
            ("FIELD", "allset_se_tool_mode", "Required Mode"),
            ("FIELD", "allset_se_object_type", "Object Type"),
        ))

    rows.append(("FIELD", "allset_se_tooltip", "Tooltip"))
    signature = repr((wm.allset_se_index, kind, wm.allset_se_operator,
                      wm.allset_se_action_id, rows))
    if wm.allset_se_properties_signature == signature:
        return

    collection = wm.allset_se_properties
    collection.clear()
    for row_kind, field, label in rows:
        item = collection.add()
        item.row_kind = row_kind
        item.field = field
        item.label = label

    wm.allset_se_properties_signature = signature
    wm.allset_se_properties_index = 0


class ALLSET_PT_shelf_editor(bpy.types.Panel):
    """Maya-style Shelf Editor shown in the kit's dedicated floating editor window"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_label = TITLE
    bl_options = {'HIDE_HEADER'}
    bl_order = -310

    @classmethod
    def poll(cls, context):
        return marked_window.context_kind(context) == KIND

    def draw(self, context):
        global _draft
        wm = _wm(context)
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        if _draft is None:
            layout.label(text="Shelf Editor session is not initialized", icon='ERROR')
            layout.operator(ALLSET_OT_shelf_editor_open.bl_idname, text="Reopen Editor")
            return

        header = layout.row(align=True)
        header.label(text="Shelf Editor", icon='TOOL_SETTINGS')

        layout.separator()
        split = layout.split(factor=0.38, align=True)
        left = split.column(align=True)
        left.label(text="Shelves", icon='FILE_FOLDER')
        _sync_shelves_list(wm)
        # A: fixed-height scroll viewport. Match B's framed template_list so
        # both columns have the same visible row count and viewport height.
        shelf_list_box = left.box()
        shelf_list_box.template_list(
            ALLSET_UL_shelf_editor_shelves.bl_idname,
            "shelf_editor_shelves",
            wm,
            "allset_se_shelves",
            wm,
            "allset_se_shelves_index",
            rows=14,
            maxrows=14,
            type='DEFAULT',
        )
        left.separator()
        shelf_tools = left.row(align=True)
        shelf_tools.alignment = 'LEFT'
        shelf_tools.operator(ALLSET_OT_shelf_editor_add_shelf.bl_idname, text="", icon='ADD')
        if _draft_user_shelf(wm.allset_se_shelf) is not None:
            shelf_tools.operator(ALLSET_OT_shelf_editor_rename_shelf.bl_idname, text="", icon='GREASEPENCIL')
            shelf_tools.operator(ALLSET_OT_shelf_editor_duplicate_shelf.bl_idname, text="", icon='DUPLICATE')
            shelf_tools.operator(ALLSET_OT_shelf_editor_delete_shelf.bl_idname, text="", icon='TRASH')
            op = shelf_tools.operator(ALLSET_OT_shelf_editor_move_shelf.bl_idname, text="", icon='TRIA_UP')
            op.direction = "UP"
            op = shelf_tools.operator(ALLSET_OT_shelf_editor_move_shelf.bl_idname, text="", icon='TRIA_DOWN')
            op.direction = "DOWN"

        right = split.column(align=True)
        right.label(text="Shelf Contents", icon='PRESET')
        shelf_id = wm.allset_se_shelf
        _sync_contents_list(wm, shelf_id)
        list_box = right.box()
        list_box.template_list(
            ALLSET_UL_shelf_editor_contents.bl_idname,
            "shelf_contents",
            wm,
            "allset_se_items",
            wm,
            "allset_se_list_index",
            rows=14,
            maxrows=14,
            type='DEFAULT',
        )

        # Native popup menu: selecting a type creates the draft item directly.
        # The popup does not occupy layout space or change A/B/C/D dimensions.
        right.menu(
            ALLSET_MT_shelf_editor_add_action.bl_idname,
            text="Add Button",
            icon='ADD',
        )

        layout.separator()
        help_row = layout.row(align=True)
        help_row.label(text="Quick Add: Ctrl+Shift-click a Maya menu item", icon='INFO')
        help_row.label(text="Add Button opens the visual command chooser")
        # The C viewport fills the remaining editor height, while its own
        # UIList remains independently scrollable. Reserve two UI rows for D:
        # one row of breathing room plus the Save / Discard button row.
        region = context.region
        ui_scale = max(1.0, context.preferences.system.ui_scale)
        has_selection = wm.allset_se_index >= 0
        top_fixed_px = (92 + 16 * 22 + 38) * ui_scale
        help_px = 24 * ui_scale
        message_px = (24 * ui_scale) if wm.allset_se_message else 0.0
        footer_px = 2 * 22 * ui_scale
        property_chrome_px = (28 + 28) * ui_scale if has_selection else 0.0
        bottom_gap_px = 8 * ui_scale
        row_px = PROPERTY_ROW_HEIGHT * ui_scale
        if has_selection:
            property_rows = int((float(region.height) - top_fixed_px - help_px
                                 - message_px - footer_px - property_chrome_px
                                 - bottom_gap_px) / row_px)
            property_rows = max(PROPERTY_MIN_ROWS,
                                min(PROPERTY_MAX_ROWS, property_rows))
            box = layout.box()
            box.label(text="Button Properties", icon='PREFERENCES')
            _sync_properties_list(wm)
            box.template_list(
                ALLSET_UL_shelf_editor_properties.bl_idname,
                "shelf_editor_properties",
                wm,
                "allset_se_properties",
                wm,
                "allset_se_properties_index",
                rows=property_rows,
                maxrows=property_rows,
                type='DEFAULT',
            )
            box.operator(ALLSET_OT_shelf_editor_apply_button.bl_idname,
                         text="Apply to Draft", icon='CHECKMARK')

        if wm.allset_se_message:
            layout.separator()
            layout.label(text=wm.allset_se_message, icon='INFO')

        # Keep D at the bottom with a two-row reserve. C consumes the available
        # height above it instead of remaining a short seven-row panel.
        top_rows = 16
        property_rows_for_footer = property_rows if has_selection else 0
        estimated_content = (92 + top_rows * 22 + 38 + help_px / ui_scale
                             + (56 + property_rows_for_footer * 22 if has_selection else 0)
                             + (message_px / ui_scale) + 2 * 22 + 8) * ui_scale
        available = max(0.0, float(region.height) - estimated_content)
        layout.separator(factor=available / (6.0 * ui_scale))
        footer = layout.row(align=True)
        footer.alignment = 'RIGHT'
        footer.operator(ALLSET_OT_shelf_editor_save.bl_idname, text="Save", icon='FILE_TICK')
        footer.operator(ALLSET_OT_shelf_editor_cancel.bl_idname, text="Discard", icon='LOOP_BACK')


classes = (
    ALLSET_OT_shelf_editor_open,
    ALLSET_OT_shelf_editor_icon_page,
    ALLSET_PG_shelf_editor_icon_grid_row,
    ALLSET_UL_shelf_editor_icon_grid,
    ALLSET_OT_shelf_editor_icon_picker,
    ALLSET_OT_shelf_editor_icon_select,
    ALLSET_OT_shelf_editor_icon_file,
    ALLSET_OT_shelf_editor_select_shelf,
    ALLSET_OT_shelf_editor_select_button,
    ALLSET_OT_shelf_editor_add_shelf,
    ALLSET_OT_shelf_editor_rename_shelf,
    ALLSET_OT_shelf_editor_duplicate_shelf,
    ALLSET_OT_shelf_editor_delete_shelf,
    ALLSET_OT_shelf_editor_move_shelf,
    ALLSET_OT_shelf_editor_add_button,
    ALLSET_MT_shelf_editor_add_action,
    ALLSET_OT_shelf_editor_create_action,
    ALLSET_OT_shelf_editor_apply_button,
    ALLSET_OT_shelf_editor_delete_button,
    ALLSET_OT_shelf_editor_move_button,
    ALLSET_OT_shelf_editor_save,
    ALLSET_OT_shelf_editor_cancel,
    ALLSET_PG_shelf_editor_list_item,
    ALLSET_UL_shelf_editor_shelves,
    ALLSET_UL_shelf_editor_properties,
    ALLSET_UL_shelf_editor_contents,
    ALLSET_PT_shelf_editor,
)

_WM_PROPS = (
    "allset_se_shelf", "allset_se_index", "allset_se_label", "allset_se_icon",
    "allset_se_type", "allset_se_script", "allset_se_menu", "allset_se_operator",
    "allset_se_props", "allset_se_tooltip", "allset_se_message",
    "allset_se_action_id", "allset_se_action_code", "allset_se_space_type",
    "allset_se_tool_space_type", "allset_se_tool_mode",
    "allset_se_required_mode", "allset_se_object_type",
    "allset_se_items", "allset_se_items_signature", "allset_se_list_index",
    "allset_se_shelves", "allset_se_shelves_signature", "allset_se_shelves_index",
    "allset_se_properties", "allset_se_properties_signature", "allset_se_properties_index",
    "allset_se_icon_grid_rows", "allset_se_icon_grid_rows_index",
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.allset_se_shelf = StringProperty(options={'SKIP_SAVE'})
    wm.allset_se_index = IntProperty(default=-1, options={'SKIP_SAVE'})
    wm.allset_se_label = StringProperty(name="Label", options={'SKIP_SAVE'})
    wm.allset_se_icon = StringProperty(name="Icon", search=shelf.shelf_icons.icon_search, options={'SKIP_SAVE'})
    wm.allset_se_type = EnumProperty(
        name="Command Type",
        items=(
            ("OPERATOR", "Blender Operator", "Run a Blender Operator"),
            ("MAYA_MENU_ITEM", "Maya Menu Item", "Run a Maya Workflow Kit menu item"),
            ("MENU", "Menu", "Open a Blender native or MayaWorkflow Menu by Menu ID"),
            ("TOOL", "Tool", "Activate a Blender Tool"),
            ("PYTHON", "Python", "Run a Python command"),
            ("SEPARATOR", "Separator", "Visual separator"),
        ),
        options={'SKIP_SAVE'},
    )
    wm.allset_se_script = StringProperty(name="Python", options={'SKIP_SAVE'})
    wm.allset_se_menu = StringProperty(name="Maya Menu Item", search=menu_search, options={'SKIP_SAVE'})
    wm.allset_se_operator = StringProperty(name="Blender Operator", search=operator_search, options={'SKIP_SAVE'})
    wm.allset_se_props = StringProperty(name="Operator Properties", default="", options={'SKIP_SAVE'})
    wm.allset_se_tooltip = StringProperty(name="Tooltip", options={'SKIP_SAVE'})
    wm.allset_se_message = StringProperty(options={'SKIP_SAVE'})
    wm.allset_se_action_id = StringProperty(
        name="Menu / Tool ID",
        search=action_id_search,
        description="Menu: Blender native Menu or MayaWorkflow Menu, e.g. XXX_MT_xxx",
        options={'SKIP_SAVE'},
    )
    wm.allset_se_action_code = StringProperty(name="Action Code", options={'SKIP_SAVE'})
    wm.allset_se_space_type = EnumProperty(
        name="Editor Space",
        items=(
            ("AUTO", "Auto", "Infer the appropriate editor from the selected action"),
            ("ANY", "Any Editor", "Do not require a specific editor"),
            ("VIEW_3D", "3D View", "Execute in a 3D View"),
            ("IMAGE_EDITOR", "Image / UV Editor", "Execute in an Image or UV Editor"),
            ("NODE_EDITOR", "Node Editor", "Execute in a Node Editor"),
            ("GRAPH_EDITOR", "Graph Editor", "Execute in a Graph Editor"),
            ("DOPESHEET_EDITOR", "Dope Sheet", "Execute in a Dope Sheet"),
            ("NLA_EDITOR", "NLA Editor", "Execute in an NLA Editor"),
            ("SEQUENCE_EDITOR", "Video Sequencer", "Execute in the Video Sequencer"),
            ("CLIP_EDITOR", "Movie Clip Editor", "Execute in a Movie Clip Editor"),
            ("TEXT_EDITOR", "Text Editor", "Execute in a Text Editor"),
            ("CONSOLE", "Python Console", "Execute in the Python Console"),
            ("OUTLINER", "Outliner", "Execute in the Outliner"),
        ),
        default="AUTO",
        options={'SKIP_SAVE'},
    )
    wm.allset_se_tool_space_type = EnumProperty(
        name="Editor",
        items=(
            ("AUTO", "Auto", "Infer the appropriate editor from the Tool ID"),
            ("VIEW_3D", "3D View", "Activate the tool in the 3D View"),
            ("IMAGE_EDITOR", "UV Editor", "Activate the tool in the UV Editor"),
        ),
        default="AUTO",
        options={'SKIP_SAVE'},
    )
    wm.allset_se_tool_mode = EnumProperty(
        name="Required Mode",
        description="Infer the required mode automatically, or explicitly restrict execution",
        items=(
            ("AUTO", "Auto", "Infer the mode from the Tool ID"),
            ("ANY", "Any Mode", "Do not require a specific mode"),
            ("OBJECT", "Object Mode", "Require Object Mode"),
            ("EDIT_MESH", "Mesh Edit Mode", "Require Mesh Edit Mode"),
            ("SCULPT", "Sculpt Mode", "Require Sculpt Mode"),
            ("PAINT_VERTEX", "Vertex Paint", "Require Vertex Paint Mode"),
            ("PAINT_WEIGHT", "Weight Paint", "Require Weight Paint Mode"),
            ("PAINT_TEXTURE", "Texture Paint", "Require Texture Paint Mode"),
            ("EDIT_CURVE", "Curve Edit Mode", "Require Curve Edit Mode"),
            ("SCULPT_CURVES", "Curves Sculpt Mode", "Require Curves Sculpt Mode"),
            ("EDIT_ARMATURE", "Armature Edit Mode", "Require Armature Edit Mode"),
            ("POSE", "Pose Mode", "Require Pose Mode"),
            ("EDIT_LATTICE", "Lattice Edit Mode", "Require Lattice Edit Mode"),
            ("EDIT_METABALL", "Metaball Edit Mode", "Require Metaball Edit Mode"),
            ("EDIT_SURFACE", "Surface Edit Mode", "Require Surface Edit Mode"),
            ("EDIT_TEXT", "Text Edit Mode", "Require Text Edit Mode"),
            ("PARTICLE", "Particle Edit Mode", "Require Particle Edit Mode"),
            ("EDIT_GREASE_PENCIL", "Grease Pencil Edit Mode", "Require Grease Pencil Edit Mode"),
            ("SCULPT_GREASE_PENCIL", "Grease Pencil Sculpt", "Require Grease Pencil Sculpt Mode"),
            ("PAINT_GREASE_PENCIL", "Grease Pencil Draw", "Require Grease Pencil Draw Mode"),
            ("WEIGHT_GREASE_PENCIL", "Grease Pencil Weight Paint", "Require Grease Pencil Weight Paint Mode"),
            ("VERTEX_GREASE_PENCIL", "Grease Pencil Vertex Paint", "Require Grease Pencil Vertex Paint Mode"),
        ),
        default="AUTO",
        options={'SKIP_SAVE'},
    )
    wm.allset_se_required_mode = EnumProperty(
        name="Required Mode",
        description="Infer the required mode from the selected action, or set a specific mode",
        items=(
            ("AUTO", "Auto", "Infer a compatible mode from the action"),
            ("ANY", "Any Mode", "Do not require a specific mode"),
            ("OBJECT", "Object Mode", "Require Object Mode"),
            ("EDIT_MESH", "Mesh Edit Mode", "Require Mesh Edit Mode"),
            ("SCULPT", "Sculpt Mode", "Require Sculpt Mode"),
            ("PAINT_VERTEX", "Vertex Paint", "Require Vertex Paint Mode"),
            ("PAINT_WEIGHT", "Weight Paint", "Require Weight Paint Mode"),
            ("PAINT_TEXTURE", "Texture Paint", "Require Texture Paint Mode"),
            ("EDIT_CURVE", "Curve Edit Mode", "Require Curve Edit Mode"),
            ("SCULPT_CURVES", "Curves Sculpt Mode", "Require Curves Sculpt Mode"),
            ("EDIT_ARMATURE", "Armature Edit Mode", "Require Armature Edit Mode"),
            ("POSE", "Pose Mode", "Require Pose Mode"),
            ("EDIT_LATTICE", "Lattice Edit Mode", "Require Lattice Edit Mode"),
            ("EDIT_METABALL", "Metaball Edit Mode", "Require Metaball Edit Mode"),
            ("EDIT_SURFACE", "Surface Edit Mode", "Require Surface Edit Mode"),
            ("EDIT_TEXT", "Text Edit Mode", "Require Text Edit Mode"),
            ("PARTICLE", "Particle Edit Mode", "Require Particle Edit Mode"),
            ("EDIT_GREASE_PENCIL", "Grease Pencil Edit Mode", "Require Grease Pencil Edit Mode"),
            ("SCULPT_GREASE_PENCIL", "Grease Pencil Sculpt", "Require Grease Pencil Sculpt Mode"),
            ("PAINT_GREASE_PENCIL", "Grease Pencil Draw", "Require Grease Pencil Draw Mode"),
            ("WEIGHT_GREASE_PENCIL", "Grease Pencil Weight Paint", "Require Grease Pencil Weight Paint Mode"),
            ("VERTEX_GREASE_PENCIL", "Grease Pencil Vertex Paint", "Require Grease Pencil Vertex Paint Mode"),
        ),
        default="AUTO",
        options={'SKIP_SAVE'},
    )
    wm.allset_se_object_type = EnumProperty(
        name="Object Type",
        description="Infer the compatible object type, or restrict execution to a specific type",
        items=(
            ("AUTO", "Auto", "Infer a compatible object type from the action"),
            ("ANY", "Any Object", "Do not require a specific active object type"),
            ("MESH", "Mesh", "Require an active Mesh object"),
            ("CURVE", "Curve", "Require an active Curve object"),
            ("SURFACE", "Surface", "Require an active Surface object"),
            ("META", "Metaball", "Require an active Metaball object"),
            ("FONT", "Text", "Require an active Text object"),
            ("ARMATURE", "Armature", "Require an active Armature object"),
            ("LATTICE", "Lattice", "Require an active Lattice object"),
            ("GPENCIL", "Grease Pencil (Legacy)", "Require a legacy Grease Pencil object"),
            ("GREASEPENCIL", "Grease Pencil", "Require a Grease Pencil object"),
            ("EMPTY", "Empty", "Require an Empty object"),
        ),
        default="AUTO",
        options={'SKIP_SAVE'},
    )
    wm.allset_se_items = bpy.props.CollectionProperty(type=ALLSET_PG_shelf_editor_list_item,
                                                       options={'SKIP_SAVE'})
    wm.allset_se_items_signature = StringProperty(options={'SKIP_SAVE'})
    wm.allset_se_list_index = IntProperty(default=0, options={'SKIP_SAVE'})
    wm.allset_se_shelves = bpy.props.CollectionProperty(type=ALLSET_PG_shelf_editor_list_item,
                                                         options={'SKIP_SAVE'})
    wm.allset_se_shelves_signature = StringProperty(options={'SKIP_SAVE'})
    wm.allset_se_shelves_index = IntProperty(default=0, options={'SKIP_SAVE'})
    wm.allset_se_properties = bpy.props.CollectionProperty(type=ALLSET_PG_shelf_editor_list_item,
                                                            options={'SKIP_SAVE'})
    wm.allset_se_properties_signature = StringProperty(options={'SKIP_SAVE'})
    wm.allset_se_properties_index = IntProperty(default=0, options={'SKIP_SAVE'})
    wm.allset_se_icon_grid_rows = bpy.props.CollectionProperty(
        type=ALLSET_PG_shelf_editor_icon_grid_row,
        options={'SKIP_SAVE'},
    )
    wm.allset_se_icon_grid_rows_index = IntProperty(default=0, options={'SKIP_SAVE'})
    marked_window.KINDS[KIND] = ("show_properties_scene", "show_properties_data")
    window_places.STRICT.add(f"marked:{KIND}")


def unregister():
    global _draft, _draft_base
    _draft = None
    _draft_base = None
    marked_window.KINDS.pop(KIND, None)
    window_places.STRICT.discard(f"marked:{KIND}")
    for name in _WM_PROPS:
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
