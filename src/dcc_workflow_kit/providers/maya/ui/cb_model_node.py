# SPDX-License-Identifier: GPL-3.0-or-later
"""The kit's recorded modeling node (polyExtrudeFace1, polyBevel1 ...) in Channel Box INPUTS: which node the lead
object shows (``cb_record``), its rows as WindowManager text proxies (``ALLSET_PG_history``; an edit is one undo step
through ``allset.model_channel_entry``) and the node row draw (``draw_cb_node``).
Related: in_view.py, cb_panel.py, node_attributes.py, channel_box.py.
"""

import bpy
from bpy.props import StringProperty

# every spec is registered before ALL_FIELDS / ALLSET_PG_history read them
from ..operators import bevel_maya, extrude  # noqa: F401  bevel_maya: registers polyBevel
from ..operators import uv_tools  # noqa: F401  registers the polyAutoProj spec
from ..operators import move_component  # noqa: F401  registers the polyMoveFace / Edge / Vertex specs
from ..operators import extrude_curve  # noqa: F401  registers the extrusion along a curve


# --- Channel Box INPUTS ------------------------------------------------------------------------------

# every field of every recorded node (Channel Box text proxies: edge / vertex extrusion, bevel)
ALL_FIELDS = tuple(dict.fromkeys(f for spec in extrude.SPECS.values() for f in spec.fields))


def cb_record(context, ob):
    """The lead object's last extrusion for Channel Box INPUTS (any selection), or None."""
    if ob is None:
        return None
    rec = (extrude.object_record(ob) if ob is not getattr(context, 'edit_object', None)
           else extrude.current(ob))
    if rec is not None:
        from ..operators import model_history
        selected = model_history.selected(ob)
        return (selected if selected is not None and not hasattr(selected, 'creation')
                and selected.history_id != rec.history_id else rec)
    return None


def _lead(context):
    return getattr(context, "edit_object", None) or getattr(context, "active_object", None)


def _text_get(field):
    def get(_self):
        rec = cb_record(bpy.context, _lead(bpy.context))
        if rec is None or field not in rec.params:
            return ""
        from . import node_attributes
        node = node_attributes.for_record(bpy.context, _lead(bpy.context), rec)
        return node_attributes.format_value(node, field, bpy.context.scene)
    return get


def _text_set(field):
    def set_(_self, text):
        context = bpy.context
        rec = cb_record(context, _lead(context))
        if rec is None or field not in rec.params:
            return
        from . import channel_box
        bpy.ops.allset.model_channel_entry('EXEC_DEFAULT', True,
                                           key=channel_box.model_key(rec, field), text=text)
    return set_


class ALLSET_OT_model_channel_entry(bpy.types.Operator):
    """Apply typed modeling channels and compatible selected channels as one undo step"""
    bl_idname = 'allset.model_channel_entry'
    bl_label = 'Edit Node Attributes'
    bl_options = {'INTERNAL', 'UNDO'}
    key: StringProperty(options={'SKIP_SAVE'})
    text: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        from . import channel_box
        count = channel_box.apply_entry(self.key, self.text, context)
        return {'FINISHED'} if count else {'CANCELLED'}


class ALLSET_PG_history(bpy.types.PropertyGroup):
    __annotations__ = {f"{f}_text": StringProperty(name=next(s.labels[f] for s in extrude.SPECS.values()
                                                             if f in s.fields),
                                                   get=_text_get(f), set=_text_set(f), options={'SKIP_SAVE'})
                       for f in ALL_FIELDS}


HISTORY_TIP = "Blender keeps no edit-mode history: only the last operation can be changed here."
CHAIN_TIP = "Edit this recorded modeling node and replay its downstream operations."   # Persistent Modeling History


def draw_cb_node(layout, context, rec):
    """The polyExtrudeFace node in Channel Box INPUTS; the Blender notice is the node name's
    tooltip (no Blender sentences in Maya windows). Collapsed until its name is clicked, like Maya
   ."""
    from . import channel_box
    lines = channel_box.as_lines(layout)
    ob = channel_box.lead(context)
    from ..operators import model_history
    tip = CHAIN_TIP if model_history.enabled() else HISTORY_TIP
    _row, opened = channel_box.node_row(lines, ob, channel_box.history_node(rec.name), rec.name, tip=tip)
    if not opened:
        return
    hist = context.window_manager.allset_history
    from . import node_attributes
    node = node_attributes.for_record(context, ob, rec)
    for field in rec.spec.fields:
        row = lines.row()
        if row is None:
            continue
        split = row.split(factor=0.5, align=True)
        key = channel_box.model_key(rec, field)
        split.operator('allset.cb_select_channel', text=rec.spec.labels[field], emboss=False,
                       depress=key in channel_box.selected_channels(context)).key = key
        values = split.row()
        values.enabled = node_attributes.editable(node, field)
        values.prop(hist, f"{field}_text", text="")
    if rec.spec.kind == 'BRIDGE':
        row = lines.row()
        if row is not None:
            from . import bridge_editor
            bridge_editor.draw_controls(row.column(), node)
