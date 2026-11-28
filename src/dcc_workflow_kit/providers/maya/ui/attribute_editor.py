# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Attribute Editor in the 3D View sidebar, sharing the Channel Box dock.

Maya's Attribute Editor.
- Dock mode (``WindowManager.allset_dock``): the sidebar tabs "Channel Box / Layer
  Editor", "Attribute Editor", "Modeling Toolkit" = the tabs of Maya's right dock
 ; Ctrl+A toggles
  (``ShowAttributeEditorOrChannelBox``).
- Node tabs: transform = object, shape = object
  data, one tab per modifier (construction history inputs) and per material.
- Sections and their rows: ``ae_layout`` (Maya template sections, collapse flags
  from Maya's Attribute Editor templates), drawn as ``layout.panel`` sections.
- Joints: in pose mode the node is the lead pose bone (``cb_nodes.lead``): a
  ``joint`` tab (ae_layout.JOINT) plus one tab per constraint node, like Maya's
  ``pCube1_parentConstraint1``.
- Maya's Attribute Editor:
  the kit's last extrusion is a ``polyExtrudeFace`` history tab (``H``), modifiers are tabs with Maya node names
  (``MODIFIER_NODES``), and Maya's AE chrome: menu bar List / Selected / Focus / Attributes / Display / Show / Help,
  Focus / Presets / Show / Hide beside the node name, Notes, and Select / Load Attributes / Copy Tab at the bottom.

Split into ae_nodes (tabs), ae_rows (a tab's body), ae_menus (menu bar), ae_operators; this module draws the panel
and registers the editor. Every name those modules define can still be imported from here.
"""

import bpy
from bpy.props import EnumProperty, StringProperty

from . import channel_box
from .ae_nodes import (  # noqa: F401
    principled, material_type, node_type, MODIFIER_NODES, modifier_node, default_name, history_record, nice_type,
    hidden_types, _constraint_tabs, tabs, _kind, current_tab, tab_target, sections_for, ae_node)
from .ae_rows import (  # noqa: F401
    resolve, _owner, _length, _vector_row, _maya_number_rows, draw_transform_channels, draw_world_pivot, LIMIT_PROPS,
    draw_limit, draw_visibility, JOINT_AXIS_NOTE, joint_orient, draw_joint_orient, draw_joint_stiffness, draw_shading,
    draw_smooth_mesh, draw_type_manipulator, DRAWERS, attr_label, draw_row, SECTION_INDENT,
    section_body, draw_sections, _MOD_SKIP, modifier_props, draw_history, _CON_SKIP, constraint_props, draw_constraint,
    draw_extra, draw_extrude_history, draw_shading_group)
from .ae_menus import (  # noqa: F401
    ATTRIBUTE_NAMES, AE, AE_NOTICES, _recent, RECENT, _remember, _greyed, ALLSET_MT_ae_list, ALLSET_MT_ae_selected,
    ALLSET_MT_ae_focus, ALLSET_MT_ae_attributes, ALLSET_MT_ae_attribute_names, ALLSET_MT_ae_display,
    ALLSET_MT_ae_node_types, ALLSET_MT_ae_show, ALLSET_MT_ae_help, ALLSET_MT_ae_presets, MENU_BAR, MENUS)
from .ae_operators import (  # noqa: F401
    DOCK_ITEMS, DOCK_TABS, dock_mode, set_tab, ALLSET_OT_ae_tab, ALLSET_OT_ae_step, ALLSET_OT_ae_modifier, ALLSET_OT_ae_add_limit,
    ALLSET_OT_ae_select, show_dock, ALLSET_OT_ae_toggle, ALLSET_OT_dock_show, ALLSET_OT_object_attributes, _redraw,
    ALLSET_OT_ae_focus, ALLSET_OT_ae_show_types, ALLSET_OT_ae_hide_type, ALLSET_OT_ae_load, ALLSET_OT_ae_show_node,
    COPY_TABS, copy_tab_target, ALLSET_OT_ae_copy_tab, MODIFIER_TYPES, modifier_owner, ALLSET_OT_ae_blender_modifiers,
    open_pinned_properties)


def content_width(context):
    """Px the dock's panel content spans: region minus Blender's panel margins and the Maya tab strip."""
    region = getattr(context, "region", None)
    if region is None or region.width <= 1:
        return None
    from . import maya_dock
    scale = context.preferences.system.ui_scale or 1.0
    unit = maya_dock._ui_unit(scale, context.preferences.system.pixel_size or 1.0)
    return region.width - 2 * maya_dock.PANEL_MARGIN_U * unit - maya_dock.area_reserved_px(context) - 4 * scale


def text_widths(context, labels, extra_units=None):
    """Px a button needs for each label: the text (Blender's UI font size) plus its margins (0.4 widget unit a side)
    and ``extra_units`` widget units (a menu's arrow)."""
    from . import maya_dock
    scale = context.preferences.system.ui_scale or 1.0
    unit = maya_dock._ui_unit(scale, context.preferences.system.pixel_size or 1.0)
    extra_units = extra_units or [0.0] * len(labels)
    try:
        import blf
        blf.size(0, 11 * scale)
        text = [blf.dimensions(0, t)[0] for t in labels]
    except Exception:
        text = [len(t) * 7 * scale for t in labels]
    return [w + (1.0 + e) * unit for w, e in zip(text, extra_units)]


def wrap_rows(context, labels, equal=True, extra_units=None):
    """``labels`` split into rows that each fit the dock, so no tab / button / menu text is cut ("pCubeS...",
    "Sele...", #104). Maya's AE is wider and scrolls its tab bar; the kit dock can be
    narrower (event-simulated sessions don't fit it, users drag it): rows wrap like a narrow Qt bar.
    ``equal``: an aligned row gives every button the same width, so a row needs n × its widest label; else the
    labels keep their natural widths (left / right aligned rows). Without a region (tests with a fake layout) one
    row."""
    avail = content_width(context) if labels else None
    if avail is None:
        return [list(range(len(labels)))]
    widths = text_widths(context, labels, extra_units)
    rows, cur = [], []
    for i in range(len(labels)):
        trial = cur + [i]
        need = len(trial) * max(widths[j] for j in trial) if equal else sum(widths[j] for j in trial)
        if cur and need > avail:
            rows.append(cur)
            trial = [i]
        cur = trial
    rows.append(cur)
    return rows


def tab_window(widths, avail, current, arrows):
    """Maya's AE tab bar is one Qt tab row that scrolls: the tabs
    [a, b) shown, ``current`` among them, as many as fit in ``avail`` px; when not all fit, ``arrows`` px are kept
    for the ◀ ▶ buttons. Returns (a, b, overflow). Pure (tests/test_step211_fix_batch.py)."""
    n = len(widths)
    if avail is None or sum(widths) <= avail:
        return 0, n, False
    room = avail - arrows
    a = b = min(max(current, 0), n - 1)
    used = widths[a]
    b += 1
    while True:
        grew = False
        if b < n and used + widths[b] <= room:
            used += widths[b]
            b += 1
            grew = True
        if a > 0 and used + widths[a - 1] <= room:
            a -= 1
            used += widths[a]
            grew = True
        if not grew:
            return a, b, True


def draw_tab_strip(layout, context, ob, current):
    """One row of tabs at their text width, left-aligned like Maya's; a dock too narrow for all of them shows the
    ones around the current tab with ◀ ▶ (previous / next tab; Qt's arrows only scroll)."""
    items = tabs(ob)
    labels = [label for _k, label, _t in items]
    keys = [k for k, _l, _t in items]
    cur = keys.index(current) if current in keys else 0
    avail = content_width(context) if labels else None
    if avail is None:
        a, b, over = 0, len(items), False
        widths = None
    else:
        from . import maya_dock
        scale = context.preferences.system.ui_scale or 1.0
        unit = maya_dock._ui_unit(scale, context.preferences.system.pixel_size or 1.0)
        widths = text_widths(context, labels)
        a, b, over = tab_window(widths, avail, cur, 2 * unit)
    row = layout.row(align=True)
    if widths is not None:
        row.alignment = 'LEFT'
    if over:
        prev = row.row(align=True)
        prev.enabled = cur > 0
        prev.operator("allset.ae_tab", text="", icon='TRIA_LEFT').key = keys[max(cur - 1, 0)]
    for i in range(a, b):
        cell = row.row(align=True)
        if widths is not None:
            cell.ui_units_x = widths[i] / unit
        cell.operator("allset.ae_tab", text=labels[i], depress=(keys[i] == current)).key = keys[i]
    if over:
        nxt = row.row(align=True)
        nxt.enabled = cur < len(keys) - 1
        nxt.operator("allset.ae_tab", text="", icon='TRIA_RIGHT').key = keys[min(cur + 1, len(keys) - 1)]


def draw(layout, context, ob):
    """The whole Attribute Editor for ``ob`` (also used by tests with a fake layout)."""
    key = current_tab(context, ob)
    draw_tab_strip(layout, context, ob, key)
    target = tab_target(ob, key)
    if target is None:
        return
    entry = next(t for t in tabs(ob) if t[0] == key)
    draw_head(layout, context, ob, key, target, entry)
    kind = _kind(key)
    if kind == "SG":
        draw_shading_group(layout, key, target)
    elif kind == "C":
        draw_constraint(layout, context, ob, target)
    elif kind == "H":
        draw_extrude_history(layout, context, target)
    elif kind == "CH":
        from . import creation_inputs
        creation_inputs.draw_ae(layout, context, ob)
    elif kind == "M":
        draw_history(layout, context, ob, target)
    else:
        sections, layout_id = sections_for(ob, key)
        draw_sections(layout, context, ob, target, sections, layout_id or "data")
        if isinstance(target, (bpy.types.ID, bpy.types.PoseBone)):
            draw_extra(layout, target, layout_id or "data")
    from . import history_rebind
    history_rebind.draw_controls(layout, ob)
    draw_notes(layout, context, ob, key, entry)
    draw_bottom(layout, context)


def draw_head(layout, context, ob, key, target, entry):
    """Maya's node row: "<type>: [name]" with the in / out arrows, Focus / Presets, Show / Hide
    (tooltips as Maya's)."""
    kind = _kind(key)
    top = layout.row(align=True)
    head = top.row(align=True)
    head.label(text=f"{entry[2]}:")
    if kind in ("SG", "H", "CH"):
        head.label(text=entry[1])
    elif kind == "M" and entry[1] != target.name:
        head.label(text=entry[1])           # the Maya node name (polyBevel31); renaming keeps Blender's name
    else:
        head.prop(target, "name", text="")
    if kind in ("M", "H", "CH"):
        sub = head.row(align=True)
        sub.operator("allset.ae_step", text="", icon='TRIA_LEFT').forward = False
        sub.operator("allset.ae_step", text="", icon='TRIA_RIGHT').forward = True
    # Maya puts Focus / Presets and Show / Hide right of the name field; the narrow dock gets them as one row
    # under it, right-aligned
    buttons = (("op", "allset.ae_focus", "Focus"), ("menu", "ALLSET_MT_ae_presets", "Presets"),
               ("op", "allset.ae_show_types", "Show"), ("op", "allset.ae_hide_type", "Hide"))
    for idx in wrap_rows(context, [b[2] for b in buttons], equal=False,
                         extra_units=[1.0 if b[0] == "menu" else 0.0 for b in buttons]):
        row = layout.row(align=True)
        row.alignment = 'RIGHT'
        for i in idx:
            kind, ident, text = buttons[i]
            if kind == "menu":
                row.menu(ident, text=text)
            else:
                row.operator(ident, text=text)
    return head


NOTES_PROP = "allset_notes"


def notes_owner(ob, key):
    """(ID-property owner, key) where the Notes of a tab live: the node's own datablock / pose bone, or for
    history / constraint nodes (no ID properties in Blender) the object under ``allset_notes:<tab>``."""
    if ob is None:
        return None, NOTES_PROP
    target = tab_target(ob, key)
    if isinstance(target, (bpy.types.ID, bpy.types.PoseBone)):
        return target, NOTES_PROP
    return ob, f"{NOTES_PROP}:{key}"


def _current_node(context):
    ob = ae_node(context)
    return (ob, current_tab(context, ob)) if ob is not None else (None, "")


def _notes_get(_self):
    try:
        ob, key = _current_node(bpy.context)
        owner, prop = notes_owner(ob, key)
        value = owner.get(prop, "") if owner is not None else ""
        return value if isinstance(value, str) else ""
    except (AttributeError, ReferenceError, KeyError):
        return ""


def _notes_set(_self, value):
    ob, key = _current_node(bpy.context)
    owner, prop = notes_owner(ob, key)
    if owner is None:
        return
    if value:
        owner[prop] = value
    elif prop in owner.keys():
        del owner[prop]


def draw_notes(layout, context, ob, key, entry):
    """Maya's Notes box under the sections (Show > Show Notes)."""
    if not context.window_manager.allset_ae_show_notes:
        return
    layout.separator()
    layout.label(text=f"Notes:  {entry[1]}")
    layout.prop(context.scene, "allset_ae_notes", text="")


BOTTOM = (("allset.ae_select", "Select"), ("allset.ae_load", "Load Attributes"), ("allset.ae_copy_tab", "Copy Tab"))


def draw_bottom(layout, context=None):
    """Maya's bottom buttons: Select, Load Attributes, Copy Tab (wrapped when the dock is too narrow); under them
    the kit's way to Blender's whole modifier stack (Add Modifier included)."""
    layout.separator()
    col = layout.column(align=True)
    groups = wrap_rows(context, [t for _o, t in BOTTOM]) if context is not None else [list(range(len(BOTTOM)))]
    for idx in groups:
        row = col.row(align=True)
        for i in idx:
            row.operator(BOTTOM[i][0], text=BOTTOM[i][1])
    col.operator("allset.ae_blender_modifiers", text="Blender Modifiers...")


# --- panels ----------------------------------------------------------------------------------

# --- dock state --------------------------------------------------------------------
# WindowManager.allset_dock = the tab the Maya tab stack shows (Channel Box / Layer Editor, Attribute Editor,
# Modeling Toolkit; ui/maya_dock.py). The stack is its own area and simply redraws.


def _dock_update(self, context):
    from . import maya_dock
    maya_dock.redraw()


def draw_panel(layout, context):
    """The Attribute Editor body of the dock (``cb_panel.ALLSET_PT_dock_attribute_editor``)."""
    if channel_box.placing_joints(context):
        from . import chrome
        chrome.wrapped(layout, channel_box.PLACING_TEXT)
        return
    from . import chrome
    # the dock is narrower than Maya's AE: the bar wraps where it would cut a menu name
    for idx in wrap_rows(context, [label for label, _m in MENU_BAR], equal=False):
        chrome.menu_bar(layout, [MENU_BAR[i] for i in idx])
    ob = ae_node(context)
    if ob is None:
        layout.label(text="make a selection")
        return
    _remember(ob)
    draw(layout, context, ob)


def fits(context, entries):
    """True when a flat menu bar of ``entries`` fits the region (about 7 px a character + 14 px a menu at UI
    scale 1; region width unknown -> True)."""
    region = getattr(context, "region", None)
    if region is None or region.width <= 1:
        return True
    scale = context.preferences.system.ui_scale or 1.0
    need = sum(len(label) * 7 + 14 for label, _m in entries) * scale
    from . import maya_dock     # the dock's vertical tab strip takes the right edge
    return need <= region.width - 20 * scale - maya_dock.area_reserved_px(context)


classes = (ALLSET_OT_ae_tab, ALLSET_OT_ae_step, ALLSET_OT_ae_modifier, ALLSET_OT_ae_add_limit,
           ALLSET_OT_ae_select, ALLSET_OT_ae_toggle, ALLSET_OT_dock_show, ALLSET_OT_object_attributes,
           ALLSET_OT_ae_focus, ALLSET_OT_ae_show_types, ALLSET_OT_ae_hide_type, ALLSET_OT_ae_load,
           ALLSET_OT_ae_copy_tab, ALLSET_OT_ae_blender_modifiers, ALLSET_OT_ae_show_node) + MENUS


def register():
    wm = bpy.types.WindowManager
    wm.allset_dock = EnumProperty(name="Dock", items=DOCK_TABS, options={'SKIP_SAVE'}, update=_dock_update)
    wm.allset_ae_tab = StringProperty(options={'SKIP_SAVE'})
    wm.allset_ae_kind = StringProperty(default="S", options={'SKIP_SAVE'})
    wm.allset_ae_auto_load = bpy.props.BoolProperty(
        name="Auto Load Selected Attributes", default=True, options={'SKIP_SAVE'},
        description="The Attribute Editor follows the selection (off: it keeps showing its node)")
    wm.allset_ae_node = StringProperty(options={'SKIP_SAVE'})
    wm.allset_ae_hidden = StringProperty(options={'SKIP_SAVE'})
    wm.allset_ae_show_notes = bpy.props.BoolProperty(name="Show Notes", default=True, options={'SKIP_SAVE'})
    wm.allset_ae_names = EnumProperty(name="Attribute Names", items=ATTRIBUTE_NAMES, default='NICE',
                                        options={'SKIP_SAVE'})
    bpy.types.Scene.allset_ae_notes = StringProperty(
        name="Notes", get=_notes_get, set=_notes_set, options={'SKIP_SAVE'},
        description="Notes of the node shown (Maya's notes attribute; kept in the file)")
    from . import notices
    notices.PANEL_NOTICES.update(AE_NOTICES)
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    from . import notices
    for k in AE_NOTICES:
        notices.PANEL_NOTICES.pop(k, None)
    _recent.clear()
    del bpy.types.Scene.allset_ae_notes
    wm = bpy.types.WindowManager
    for name in ("allset_ae_names", "allset_ae_show_notes", "allset_ae_hidden", "allset_ae_node",
                 "allset_ae_auto_load"):
        delattr(wm, name)
    del wm.allset_ae_kind
    del wm.allset_ae_tab
    del wm.allset_dock
