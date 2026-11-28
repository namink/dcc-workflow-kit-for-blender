# SPDX-License-Identifier: GPL-3.0-or-later
"""Ties the kit manipulator to Blender's Move / Rotate / Scale tools: the active tool and its kind (``active_tool``,
``tool_kind``), the swap of the tools' gizmo group for ``ALLSET_GGT_xform`` (``patch_tools`` / ``unpatch_tools``;
``ensure_tools`` sets stale tools up again from a timer and on file load) and Maya's Move / Rotate / Scale Settings
drawn in the active tool panel (``draw_tool_settings``). Registered and re-exported by manipulator.py.
"""

import bpy

from .manipulator_frame import SLOT, pivot_edit

GROUP = "ALLSET_GGT_xform"
MODES = ('OBJECT', 'EDIT_MESH', 'EDIT_LATTICE', 'EDIT_CURVE', 'EDIT_SURFACE')
TOOLS = {"builtin.move": 'TRANSLATE', "builtin.rotate": 'ROTATE', "builtin.scale": 'RESIZE'}
KINDS = {"builtin.move": 'TRANSLATE', "builtin.rotate": 'ROTATE', "builtin.scale": 'RESIZE'}


def active_tool(context):
    if context.mode not in MODES:
        return None
    try:
        return context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    except (AttributeError, TypeError):
        return None


def tool_kind(context):
    tool = active_tool(context)
    if tool is None or tool.widget != GROUP:
        return None
    if pivot_edit(context) and (tool.idname == 'builtin.rotate'
                                or (tool.idname == 'builtin.scale' and context.mode == 'EDIT_MESH')):
        return 'TRANSLATE'      # like Maya: Rotate (and Scale on components) edit the pivot with the Move handles
    return TOOLS.get(tool.idname)


# --- Tool Settings: Maya Move / Rotate / Scale Settings --------

TITLES = {'TRANSLATE': "Move Settings", 'ROTATE': "Rotate Settings", 'RESIZE': "Scale Settings"}


def draw_tool_settings(self, context):
    """Appended to the active tool panel (the Status Line / W-menu Tool Settings popup)."""
    tool = active_tool(context)
    kind = KINDS.get(tool.idname) if tool is not None else None
    if kind is None:
        return
    from ..operators import snap_align
    scene = context.scene
    ts = scene.tool_settings
    layout = self.layout
    layout.separator()
    layout.label(text=TITLES[kind])
    col = layout.column(align=True)
    col.prop(scene.transform_orientation_slots[SLOT[kind]], "type", text="Axis Orientation")
    col.prop(ts, "transform_pivot_point", text="Pivot")
    if kind == 'RESIZE':
        from .. import preferences
        row = col.row()
        row.enabled = context.mode == 'EDIT_MESH'
        row.prop(preferences.get(context), 'prevent_negative_scale')
    row = layout.row(align=True)
    row.label(text="Step Snap")
    mode = snap_align.step_snap_mode(ts, kind)
    for m in ('OFF', 'RELATIVE', 'ABSOLUTE'):
        cell = row.row(align=True)
        # Move offers Absolute only with World axes (Maya)
        cell.enabled = m != 'ABSOLUTE' or snap_align.absolute_offered(scene, kind)
        op = cell.operator("allset.step_snap", text=m.title(), depress=mode == m)
        op.kind, op.mode = kind, m
    if kind == 'ROTATE':
        layout.prop(ts, "snap_angle_increment_3d", text="Step")
    elif kind == 'RESIZE':
        layout.label(text="Step: 0.1")
    else:
        # Blender's increment is the grid step: 1 Maya unit in the Maya Workflow Kit template.
        layout.label(text="Step: one grid unit", icon='SNAP_INCREMENT')
    if kind == 'TRANSLATE':
        # Blender snapping always keeps the selection's spacing (on by default, like Maya; off = not possible).
        layout.label(text="Retain Component Spacing", icon='CHECKBOX_HLT')
    if context.mode == 'OBJECT':
        layout.label(text="Pivot")
        row = layout.row(align=True)
        row.operator("allset.pivot_toggle", text="Edit Pivot", icon='OBJECT_ORIGIN',
                     depress=ts.use_transform_data_origin)
        row.operator("allset.reset_pivot", text="Reset")
        row.operator("allset.bake_pivot", text="Bake")


# --- tool widget swap ---------------------------------------------------------------------------

_saved = {}   # mode -> original tool list


def _swap_items(items):
    out = []
    for it in items:
        if isinstance(it, tuple) and not hasattr(it, "idname"):
            out.append(tuple(_swap_items(it)))
        elif getattr(it, "idname", None) in TOOLS and getattr(it, "widget", None) == "VIEW3D_GGT_xform_gizmo":
            out.append(it._replace(widget=GROUP))
        else:
            out.append(it)
    return out


def _panel():
    from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active
    return VIEW3D_PT_tools_active


def patch_tools():
    cls = _panel()
    for mode in MODES:
        if mode in _saved:
            continue
        items = cls._tools[mode]
        _saved[mode] = items
        cls._tools[mode] = type(items)(_swap_items(items))


def unpatch_tools():
    cls = _panel()
    for mode, items in _saved.items():
        cls._tools[mode] = items
    _saved.clear()


def _find_item(mode, idname):
    cls = _panel()
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
    for item, _index in ToolSelectPanelHelper._tools_flatten_with_tool_index(
            cls.tools_from_context(bpy.context, mode=mode)):
        if item is not None and item.idname == idname:
            return item
    return None


def resetup(tool, mode, widget=None):
    """Set ``tool`` (a WorkSpaceTool of ``mode``) up again from the current ToolDef: the gizmo
    group a tool uses is copied at activation, so a swapped ToolDef needs this."""
    item = _find_item(mode, tool.idname)
    if item is None:
        return False
    fallback = _find_item(mode, tool.idname_fallback) if tool.idname_fallback else None
    keymap_fallback = (fallback and fallback.keymap and fallback.keymap[0]) or ""
    if keymap_fallback:
        keymap_fallback += " (fallback)"
    tool.setup(idname=item.idname, keymap=item.keymap[0] if item.keymap is not None else "",
               cursor=item.cursor or 'DEFAULT', options=item.options or set(),
               gizmo_group=(item.widget or "") if widget is None else widget, brush_type=item.brush_type or 'ANY',
               data_block=item.data_block or "", operator=item.operator or "", index=tool.index,
               idname_fallback=tool.idname_fallback, keymap_fallback=keymap_fallback)
    return True


def refresh_pivot_tool(context):
    """Rotate shows the pivot edit handles during D / Insert and its rings again after (``tool_kind``, same gizmo
    group): only a tool still carrying another group is set up again."""
    tool = active_tool(context)
    if context.mode == 'OBJECT' and stale(tool, bool(_saved)):
        resetup(tool, context.mode)


def stale(tool, patched):
    """True when an active transform tool still carries the other gizmo group."""
    if tool is None or tool.idname not in TOOLS:
        return False
    want = GROUP if patched else "VIEW3D_GGT_xform_gizmo"
    return tool.widget != want


def ensure_tools(patched=True):
    """Set up again every workspace's Move/Rotate/Scale tool whose gizmo group is stale."""
    done = 0
    for ws in bpy.data.workspaces:
        for mode in MODES:
            try:
                tool = ws.tools.from_space_view3d_mode(mode, create=False)
            except (TypeError, RuntimeError):
                continue
            if stale(tool, patched):
                try:
                    done += resetup(tool, mode)
                except (TypeError, RuntimeError, AttributeError) as ex:
                    print("allset: tool setup failed", tool.idname, ex)
    return done


def _ensure_timer():
    try:
        ensure_tools(bool(_saved))
    except (ReferenceError, AttributeError):
        pass
    return 0.5 if _saved else None


@bpy.app.handlers.persistent
def _on_load_post(_dummy):
    ensure_tools(bool(_saved))
