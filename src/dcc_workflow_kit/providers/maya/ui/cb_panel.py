# SPDX-License-Identifier: GPL-3.0-or-later
"""Drawing the Channel Box: menu bar, the lead's name line, channel rows with key-state icons, SHAPES, INPUTS
nodes (modifiers, blendShape, creation, constraints) and the empty / joint-placing states.
Entry points: ALLSET_PT_channel_box.body, draw_channel_row, draw_inputs, node_row.
Related: cb_pane.py, ui/maya_dock.py (calls body)."""

import bpy
from bpy.props import StringProperty

from .. import i18n
from . import cb_entry, cb_points, chrome

from .cb_nodes import (_drawing_lead, _field_lead, _field_texts, _generation, component_mode, is_bone, lead,
                       placing_joints, target_count)
from .cb_pane import Lines, ROW_SCALE, _last, _redraw, _reveal, _scroll, _scroll_row, fill_pane, pane_room, window_lines
from .cb_keys import CUSTOM_PREFIX, MAIN, MAIN_BY_KEY, custom_keys, is_hidden, is_locked, row_key
from .cb_inputs import (SHAPE_PROPS, _drawing_sigs, _inputs, _modifier_props, _nth_constraint, _nth_of_type, _virtual,
                        blend_shape_key, blend_shape_node, blend_shape_targets, con_node, constrained_keys,
                        constraint_enabled, constraint_node_name, constraints, is_open, mod_node, pick_node,
                        rebuild_rows, row_for, shape_data, shape_label, weight_name)
from .cb_values import (_held_states, _holding, _holds_states, channel_label, entry_kind, get_value, has_channel,
                        row_state)
from .cb_selection import sel_toggle, selected_channels, selection_column, value_cell
from .cb_menus import ALLSET_OT_cb_rotate_order, MENU_BAR


# Maya's dock is one tab stack with vertical tabs on its right edge: the
# kit's sidebar categories carry Maya's tab names
CATEGORY = "Channel Box / Layer Editor"
AE_CATEGORY = "Attribute Editor"
MTK_CATEGORY = "Modeling Toolkit"


class ALLSET_PT_cb_name(bpy.types.Panel):
    """The Channel Box name editor popover (called by allset.cb_rename only)"""
    bl_space_type = 'TOPBAR'   # dummy, like Blender's TOPBAR_PT_name (F2): only shown through wm.call_panel
    bl_region_type = 'HEADER'
    bl_label = "Rename"
    bl_ui_units_x = 8

    def draw(self, context):
        ob = lead(context)
        if ob is None:
            return
        row = self.layout.row()
        row.activate_init = True
        if component_mode(ob):
            row.prop(ob.data, "name", text="")
        else:
            row.prop(context.scene.allset_cb, "lead_name", text="")


class ALLSET_OT_cb_rename(bpy.types.Operator):
    """Rename this node (click the name, type, Enter)"""
    bl_idname = "allset.cb_rename"
    bl_label = "Rename"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return lead(context) is not None

    def invoke(self, context, event):
        bpy.ops.wm.call_panel(name=ALLSET_PT_cb_name.__name__, keep_open=False)
        return {'FINISHED'}

    def execute(self, context):
        return self.invoke(context, None)


# The empty Channel Box text: three centred lines.
EMPTY_TEXT = (i18n.mark("Select objects in the scene to view,"), i18n.mark("edit and set keyframes on channels"),
              i18n.mark("(attributes)"))


# #156: an unskinned skeleton's joints are edited in Edit mode (W / E / R reposition them); their keyable
# channels are in Pose mode
PLACING_TEXT = (i18n.mark("Editing joints: W / E / R move them,"), i18n.mark("F8 = pose mode (channels and keys)"))
# #155: short enough for the dock at its default width (the longer text was cut at UI scale 1.25)
POSE_HINT = "Ctrl+Tab: joint channels"


def draw_joint_translate(layout, context):
    """Edit-mode joints: the lead joint's name + Translate X / Y / Z text fields (``+=`` entry, display
    units; typing moves the joint, its children follow unless Preserve Children, every Maya frame stays —
    operators/joint_edit.py). Returns the UI units drawn."""
    from ..operators import joint_edit
    _ob, eb = joint_edit.lead_joint(context)
    if eb is None:
        return 0
    layout.label(text=eb.name)
    for a in joint_edit.AXES:
        row = layout.row(align=True)
        split = row.split(factor=0.5, align=True)
        split.label(text=f"Translate {a.upper()}")
        split.prop(context.scene, f"allset_joint_t{a}", text="")
        row.label(text="", icon='BLANK1')
    return 1 + len(joint_edit.AXES)


def draw_empty(layout):
    layout.separator(factor=6)
    chrome.wrapped(layout, EMPTY_TEXT)   # empty state
    layout.separator(factor=6)


# --- panel ---------------------------------------------------------------------------------------------

_STATE_ICON = {'KEYED': 'DECORATE_KEYFRAME', 'ANIMATED': 'DECORATE_ANIMATE', 'DRIVEN': 'DECORATE_DRIVER',
               'MUTED': 'MUTE_IPO_ON', 'LAYERED': 'NLA'}
# states drawn red (``alert``); a layer member is Maya teal, which UILayout can't draw: icon only
_ALERT_STATES = {'KEYED', 'ANIMATED', 'DRIVEN', 'MUTED'}


def state_alert(state):
    """A channel state the value cell draws in the key colour (UILayout ``alert``); the Attribute Editor's
    Translate / Rotate / Scale fields use it too."""
    return state in _ALERT_STATES


def _row_label(row, key, selected, sel_owner=None, sel_prop=None):
    sub = row.row(align=True)
    if sel_owner is not None:
        # a toggle of the channel's selection: pressed = Maya's blue name cell; the drag
        # watcher reads it from ``context.property`` (#6)
        # the kit's translation (with the user's translation files) first: Blender's own table knows some of
        # these names (Translate X) and would win over the kit's
        label = channel_label(key)
        sel_toggle(sub, sel_owner, sel_prop, selected, i18n.iface(label) if key in MAIN_BY_KEY else label,
                   translate=key not in MAIN_BY_KEY)
        return
    selected = selected and selection_column() == "NAME"
    op = sub.operator("allset.cb_select_channel", text=channel_label(key), depress=selected,
                      emboss=selected)
    op.key = key


def draw_channel_row(layout, ob, key, value_owner, value_prop, selected, constrained=False,
                     sel_owner=None, sel_prop=None):
    row = layout.row(align=True)
    split = row.split(factor=0.5, align=True)
    _row_label(split, key, selected, sel_owner, sel_prop)
    right = split.row(align=True)
    state = row_state(ob, key)
    right.enabled = not is_locked(ob, key)
    if constrained:
        # Maya draws constrained channels blue: a pressed button is the user's
        # theme selection colour (wcol_tool inner_sel; Blender's factory #4772b3 is blue); UILayout has no other colour.
        text = cb_entry.format_value(get_value(ob, key), entry_kind(ob, key), bpy.context.scene)
        right.operator("allset.cb_select_channel", text=text, depress=True).key = key
        row.label(text="", icon='CONSTRAINT')
        return row
    right.alert = state_alert(state)
    value_cell(right, value_owner, value_prop, selected)
    # Proxy fields get no automatic keyframe colouring: show the lead object's state.
    row.label(text="", icon=_STATE_ICON.get(state, 'BLANK1'))
    return row


def _draw_text_row(layout, context, ob, owner, prop, kind, mod_type="", nth=0, label=None):
    """A SHAPES / INPUTS row: label + text field applied to all selected (else the real prop)."""
    v = _virtual(owner, prop)
    if label is None:
        label = v.label if v is not None else owner.bl_rna.properties[prop].name
    row = row_for(context, ob, kind, prop, mod_type, nth)
    # the channel rows' geometry (draw_channel_row): the name centred in the left half, the field, then the state
    # icon's column, so SHAPES / INPUTS values line up under Translate X ... (Maya: one value column)
    line = layout.row(align=True)
    split = line.split(factor=0.5, align=True)
    if kind in ("SHAPE", "INPUT", "CONSTRAINT") and row is not None:
        # a SHAPES / INPUTS row (a modifier's property, a constraint's target weight) is a channel: selectable name
        # (MMB virtual slider, value drag), keyed / animated state like Translate X
        key = row_key(row)
        sub = split.row(align=True)
        sel_toggle(sub, row, "sel", key in selected_channels(context), label)
        right = split.row(align=True)
        state = row_state(ob, key)
        right.alert = state in _ALERT_STATES
        value_cell(right, row, "text", key in selected_channels(context))
        line.label(text="", icon=_STATE_ICON.get(state, 'BLANK1'))
        return
    name = split.row(align=True)
    name.alignment = 'CENTER'
    name.label(text=label)
    right = split.row(align=True)
    if row is None:
        if v is not None:   # a Maya attribute has no RNA property to draw until the rows are rebuilt
            right.label(text=cb_entry.format_value(v.get(owner), v.kind, context.scene))
        else:
            right.prop(owner, f'["{prop}"]' if kind == "CUSTOM" else prop, text="")
    else:
        right.prop(row, "text", text="")
    line.label(text="", icon='BLANK1')


def node_row(lines, ob, node, label, tip="", active=True):
    """An INPUTS node name: Maya's indented, flat, click-to-expand row. Returns (row or None, expanded)."""
    opened = is_open(ob, node)
    if isinstance(lines, Lines):
        lines.marks[node] = lines.n
    row = lines.row()
    if row is not None:
        name = row.row(align=True)
        name.alignment = 'LEFT'
        name.active = active
        name.separator(factor=1.5)
        op = name.operator(ALLSET_OT_cb_node_toggle.bl_idname, text=label, emboss=False)
        op.node = node
        op.tip = tip
    return row, opened


class ALLSET_OT_cb_node_toggle(bpy.types.Operator):
    """Show or hide this node's attributes (Maya: click the node name in INPUTS)"""
    bl_idname = "allset.cb_node_toggle"
    bl_label = "Expand Node"
    bl_options = {'INTERNAL'}     # no undo step: Maya's expansion is UI state

    node: StringProperty(options={'SKIP_SAVE'})
    tip: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return props.tip or cls.__doc__

    def execute(self, context):
        ob = lead(context)
        if ob is None or not self.node:
            return {'CANCELLED'}
        pick_node(ob, self.node, not is_open(ob, self.node))
        rebuild_rows(context)
        _redraw(context.window)
        return {'FINISHED'}


def _draw_component_lines(lines, context, ob):
    """Component mode under the shape's name: the CVs line / table (points selected), then INPUTS."""
    cb_points.draw(lines, context, ob)
    draw_inputs(lines, context, ob)


def _draw_lines(lines, context, ob, cb, sel, blue):
    """Every Channel Box line under the lead's name: channels, SHAPES, INPUTS (collapsed nodes)."""
    for key, _label, _path, _idx, kind in MAIN:
        if is_hidden(ob, key):
            continue
        if kind == "ROT" and not has_channel(ob, key):
            continue
        r = lines.row()
        if r is not None:
            draw_channel_row(r, ob, key, cb, key + "_text", key in sel, key in blue, cb, key + "_sel")
    if not has_channel(ob, "rx"):
        r = lines.row()
        if r is not None:
            r.label(text=f"Rotation mode {ob.rotation_mode}")
        r = lines.row()
        if r is not None:
            r.prop(ob, "rotation_quaternion" if ob.rotation_mode == 'QUATERNION' else "rotation_axis_angle", text="")
        r = lines.row()
        if r is not None:
            r.operator(ALLSET_OT_cb_rotate_order.bl_idname, text="Rotate Order XYZ").order = 'XYZ'
    for name in custom_keys(ob):
        key = CUSTOM_PREFIX + name
        if is_hidden(ob, key):
            continue
        r = lines.row()
        if r is None:
            continue
        row = row_for(context, ob, "CUSTOM", name)
        if row is not None:
            draw_channel_row(r, ob, key, row, "text", key in sel, sel_owner=row, sel_prop="sel")
        else:
            draw_channel_row(r, ob, key, ob, f'["{name}"]', key in sel)
    # #165: a joint's Radius under Visibility (Maya joint.radius, non-keyable; operators/joint_display.py)
    if is_bone(ob) and hasattr(ob.bone, "allset_joint_radius"):
        r = lines.row()
        if r is not None:
            split = r.row(align=True).split(factor=0.5, align=True)
            split.alignment = 'RIGHT'
            split.label(text="Radius")
            split.prop(ob.bone, "allset_joint_radius", text="")
            r.label(text="", icon='BLANK1')

    # SHAPES: the shape name is a rename field (Maya); camera / light / locator shapes show
    # their attributes expanded
    data = shape_data(ob)
    if data is not None:
        r = lines.row()
        if r is not None:
            r.label(text="SHAPES")
        r = lines.row()
        if r is not None:
            # Maya draws the shape row as a darker full-width bar (its rename field,
            # #373737): an embossed field
            r.separator(factor=1.5)
            if data is ob:      # a locator: its shape name follows the transform's (locator1 -> locatorShape1)
                from ..command_line import cmds_shim
                r.label(text=cmds_shim.shape_of(ob) or "")
            else:
                r.prop(data, "name", text="")
        for prop in SHAPE_PROPS.get(ob.type, ()):
            if hasattr(data, prop) or _virtual(data, prop) is not None:
                r = lines.row()
                if r is not None:
                    _draw_text_row(r, context, ob, data, prop, "SHAPE", label=shape_label(ob, prop))

    draw_inputs(lines, context, ob)


def draw_inputs(lines, context, ob):
    """INPUTS, newest first; every node starts collapsed (Maya).
    Maya treats Smooth Mesh Preview as a shape display attribute, not an input node."""
    inputs = _inputs(ob)
    cons = constraints(ob)
    from . import in_view
    last = in_view.cb_record(context, ob)    # the last kit extrusion = Maya's newest history node
    from ..operators import model_history
    modeled = model_history.records(ob) if last is not None else []
    from . import creation_inputs
    created = creation_inputs.has_node(ob)   # the primitive's creation node, oldest history
    key = blend_shape_key(ob)                # the mesh's blendShape node (#204)
    if not (inputs or cons or last is not None or created or key is not None):
        return
    r = lines.row()
    if r is not None:
        r.label(text="INPUTS")
    if model_history.pending(ob) is not None:
        row = lines.row()
        if row is not None:
            from . import history_rebind
            history_rebind.draw_controls(row.column(), ob)
    if modeled:
        for record in reversed(modeled):
            in_view.draw_cb_node(lines, context, record)
    elif last is not None:
        in_view.draw_cb_node(lines, context, last)
    from . import attribute_editor
    for mod in inputs:
        # the Maya node name the Attribute Editor shows (Blender's automatic "Armature" = skinCluster1, #97)
        try:
            label = attribute_editor.modifier_node(ob, mod)[0]
        except ValueError:      # a deformer on another object (lattice / handle INPUTS)
            label = mod.name
        row, opened = node_row(lines, ob, mod_node(mod), label)
        if row is not None:
            row.prop(mod, "show_viewport", text="")
        if opened:
            for prop in _modifier_props(mod):
                r = lines.row()
                if r is not None:
                    _draw_text_row(r, context, ob, mod, prop, "INPUT", mod.type, _nth_of_type(ob, mod))
    if key is not None:
        # shape keys are evaluated before every modifier: below the modifiers, above the creation node (Maya:
        # polyBevel1, blendShape1, polyCube1)
        draw_blend_shape(lines, context, ob, key)
    if created:
        creation_inputs.draw_cb(lines, context, ob)
    from ..operators import constrain_multi
    for con in cons:
        mb = constrain_multi.member(con, ob)
        if mb is not None:
            if constrain_multi.is_head(con, ob):
                _draw_group(lines, context, ob, con, mb)
            continue
        # Maya constraint node + its target weight
        row, opened = node_row(lines, ob, con_node(ob, con), constraint_node_name(ob, con),
                               active=constraint_enabled(con))
        if row is not None and hasattr(con, "enabled"):
            row.prop(con, "enabled", text="")
        if opened:
            r = lines.row()
            if r is not None:
                _draw_text_row(r, context, ob, con, "influence", "CONSTRAINT", con.type,
                               _nth_constraint(ob, con), label=weight_name(con))


def draw_blend_shape(lines, context, ob, key):
    """Maya's blendShape node in INPUTS: Envelope, then one weight row per target named after it. Blender has no
    envelope: it reads 1, like the Shape Editor."""
    _row, opened = node_row(lines, ob, blend_shape_node(key), key.name)
    if not opened:
        return
    rows = [("Envelope", None)] + [(kb.name, kb) for kb in blend_shape_targets(key)]
    for label, kb in rows:
        r = lines.row()
        if r is None:
            continue
        line = r.row(align=True)
        split = line.split(factor=0.5, align=True)
        if kb is None:
            name = split.row(align=True)
            name.alignment = 'CENTER'
            name.label(text=label)
            right = split.row(align=True)
            right.enabled = False
            right.label(text=cb_entry.format_value(1.0, "NONE", context.scene))
            line.label(text="", icon='BLANK1')
            continue
        row = row_for(context, ob, "BLEND", kb.name)
        if row is None:     # rows not rebuilt yet: the real value
            name = split.row(align=True)
            name.alignment = 'CENTER'
            name.label(text=label)
            split.row(align=True).prop(kb, "value", text="")
            line.label(text="", icon='BLANK1')
            continue
        # a target weight is a channel like Translate X: selectable name, keyed / animated state (Key Selected)
        key = row_key(row)
        sub = split.row(align=True)
        sel_toggle(sub, row, "sel", key in selected_channels(context), label)
        right = split.row(align=True)
        state = row_state(ob, key)
        right.alert = state in _ALERT_STATES
        value_cell(right, row, "text", key in selected_channels(context))
        line.label(text="", icon=_STATE_ICON.get(state, 'BLANK1'))


def _draw_group(lines, context, ob, con, mb):
    """A kit multi-target constraint = one Maya node: its state toggles every member, its rows are the target weights
    <target>W0, W1 ... (operators/constrain_multi.py)."""
    from ..operators import constrain_multi
    on = constraint_enabled(con)
    row, opened = node_row(lines, ob, con_node(ob, con), constraint_node_name(ob, con), active=on)
    if row is not None:
        op = row.operator("allset.constraint_group_enable", text="", emboss=False,
                          icon='CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT')
        op.object = ob.id_data.name
        op.bone = ob.name if is_bone(ob) else ""
        op.group = mb.group
    if opened:
        if constrain_multi.group_type(con, ob) in ("orientConstraint", "parentConstraint"):
            r = lines.row()
            if r is not None:
                _draw_interp_row(r, ob, mb.group)
        for prop, label in constrain_multi.weights(ob, mb.group):
            if prop not in ob.keys():
                continue
            r = lines.row()
            if r is not None:
                _draw_text_row(r, context, ob, ob, prop, "CUSTOM", label=label)


def _draw_interp_row(layout, ob, group):
    """Maya's keyable Interp Type of an orient / parent constraint (enum, default Average; #168)."""
    from ..operators import constrain_interp
    mode = constrain_interp.mode_of(ob, group)
    line = layout.row(align=True)
    split = line.split(factor=0.5, align=True)
    name = split.row(align=True)
    name.alignment = 'CENTER'
    name.label(text="Interp Type")
    right = split.row(align=True)
    right.context_pointer_set("allset_interp_owner", ob)
    right.context_string_set("allset_interp_group", group)
    right.menu(ALLSET_MT_cb_interp.bl_idname,
               text=constrain_interp.NAMES[constrain_interp.SHORTEST if mode is None else mode])
    line.label(text="", icon='BLANK1')


class ALLSET_MT_cb_interp(bpy.types.Menu):
    bl_idname = "ALLSET_MT_cb_interp"
    bl_label = "Interp Type"

    def draw(self, context):
        from ..operators import constrain_interp
        owner = getattr(context, "allset_interp_owner", None)
        group = getattr(context, "allset_interp_group", "")
        if owner is None or not group:
            return
        for i, n in enumerate(constrain_interp.NAMES):
            op = self.layout.operator("allset.constraint_interp", text=n)
            op.object = owner.id_data.name
            op.bone = owner.name if is_bone(owner) else ""
            op.group = group
            op.mode = str(i)


class ALLSET_PT_channel_box(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_label = "Channel Box"
    bl_order = 0
    bl_options = {'HIDE_HEADER'}   # Maya: a menu bar, no collapsible panel title

    # Not registered: ui/maya_dock.ALLSET_PT_maya_dock draws ``body`` in the Maya dock areas.

    def draw(self, context):
        units = ALLSET_PT_channel_box.body(self.layout, context)
        fill_pane(self.layout, context, units)

    @staticmethod
    def body(layout, context):
        """``_body``; while it draws, every row's value field asks for the lead: it is found once (drawing can't
        change the selection), and in a dock region kept for the fields' reads until the region has drawn
        (``field_lead``). While a move runs the rows' key states are kept (``row_state``)."""
        _drawing_lead[:] = [lead(context)]
        _drawing_sigs.clear()
        _field_texts.clear()
        region, area = context.region, context.area
        if region is not None and region.type == 'WINDOW' and area is not None and area.type == 'PROPERTIES':
            _field_lead[:] = [region.as_pointer(), _generation[0], _drawing_lead[0]]
        else:
            _field_lead.clear()
        _holding[0] = _holds_states(context)
        if not _holding[0]:
            _held_states.clear()
        try:
            return ALLSET_PT_channel_box._body(layout, context)
        finally:
            _drawing_lead.clear()
            _drawing_sigs.clear()
            _holding[0] = False

    @staticmethod
    def _body(layout, context):
        """Draw the Channel Box; returns its height in UI units (estimate, for the CB_SHARE pane). The row above it
        (Maya's title / tab row) is the dock's handle + tab row (ui/maya_dock.py)."""
        # Early-return views (paint tools, no selection, joint placement) use
        # native region scrolling and must not retain an old virtual-row range.
        if context.area is not None:
            _last.pop(context.area.as_pointer(), None)
        # a dock narrower than Maya's Channel Box (user-sized, or not fitted yet) wraps the menu bar instead of
        # cutting "Channels" to "Chann..." (same rule as the AE bar)
        from .attribute_editor import wrap_rows
        rows = wrap_rows(context, [label for label, _m in MENU_BAR], equal=False)
        for idx in rows:
            chrome.menu_bar(layout, [MENU_BAR[i] for i in idx])
        units = 1.0 + len(rows)
        # Paint Skin Weights: the Channel Box stays the Channel Box (no Maya version puts paint UI here, PR #125
        # check 9c); the paint settings are the Tool Settings dock (ui/tool_settings.draw_dock)
        if placing_joints(context):
            # armature edit mode = joint placement (#160): the lead joint's Maya Translate
            # (position in the parent's Maya frame) is typed here like Maya's Channel Box
            extra = draw_joint_translate(layout, context)
            layout.separator(factor=2)
            chrome.wrapped(layout, PLACING_TEXT)
            return units + 0.5 + extra + len(PLACING_TEXT)
        ob = lead(context)
        comp = component_mode(ob)
        if ob is None or (comp and not cb_points.has_selection(ob)):
            # Maya: component mode with nothing selected = the empty Channel Box too
            draw_empty(layout)
            return units + 4.2 + len(EMPTY_TEXT)
        units += 1.0
        cb = context.scene.allset_cb
        sel = set(selected_channels(context))
        head = layout.row(align=True)
        # Maya: the lead's name as plain text; a click edits it (a borderless Blender text field would need a
        # double-click)
        name = head.row(align=True)
        name.alignment = 'LEFT'
        if comp:
            # Maya component mode: the shape node, then INPUTS — no transform channels, no SHAPES header
            # (as Maya)
            name.operator(ALLSET_OT_cb_rename.bl_idname, text=ob.data.name, emboss=False, translate=False)
            args = (context, ob)
            draw = _draw_component_lines
        else:
            name.operator(ALLSET_OT_cb_rename.bl_idname, text=ob.name, emboss=False, translate=False)
            args = (context, ob, cb, sel, constrained_keys(ob))
            draw = _draw_lines
        n = target_count(context)
        if n > 1:
            head.label(text=f"+{n - 1}")
        if not is_bone(ob) and ob.type == 'ARMATURE' and ob.mode == 'OBJECT':
            hint = layout.row()
            hint.active = False
            hint.label(text=POSE_HINT)
            units += 1.0
        count = Lines(None)
        draw(count, *args)      # first pass: how many lines (also resets the expansion on a new lead)
        area = context.area
        ptr = area.as_pointer() if area is not None else 0
        start = _scroll.get(ptr, 0)
        if _reveal["node"] in count.marks:
            # a node picked from the RMB Inputs / Outputs list: scroll it to the top of the Channel Box
            # part, like Maya shows the selected node's attributes
            start = count.marks[_reveal["node"]]
            _reveal["node"] = None
        first, limit, over = window_lines(count.n, pane_room(context, units), start)
        if over:
            _scroll[ptr] = first
        col = layout.column(align=True)
        # Maya channel rows are 16 px with 11 px text; Blender rows are 20 px at scale 1.0.
        col.scale_y = ROW_SCALE
        lines = Lines(col, first, limit)
        draw(lines, *args)
        shown = lines.shown
        if over:
            _scroll_row(head, first, limit, count.n)
        _last[ptr] = (first, count.n, limit)
        return units + shown * ROW_SCALE + 0.3


class ALLSET_PT_dock_attribute_editor(bpy.types.Panel):
    """Maya Attribute Editor tab of the dock"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = AE_CATEGORY
    bl_label = "Attribute Editor"
    bl_order = 0
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        from . import attribute_editor
        attribute_editor.draw_panel(self.layout, context)


class ALLSET_PT_dock_modeling_toolkit(bpy.types.Panel):
    """Maya Modeling Toolkit tab of the dock"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = MTK_CATEGORY
    bl_label = "Modeling Toolkit"
    bl_order = 0
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        from . import modeling_toolkit
        modeling_toolkit.draw(self.layout, context)
