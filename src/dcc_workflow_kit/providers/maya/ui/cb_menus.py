# SPDX-License-Identifier: GPL-3.0-or-later
"""The Channel Box menu bar (Channels, Edit, Object, Show, Settings, Freeze) and the Channels menu commands (key,
breakdown, mute, delete, break connections, lock, hide, keyable, duplicate values).
Entry points: MENU_BAR, CHANNEL_OPS, ALLSET_MT_cb_channels, ALLSET_OT_cb_make_lead.
Related: cb_channels.py (more Channels commands)."""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from .. import results
from . import chrome

from .cb_nodes import lead, pose_armature, pose_objects, set_bone_selected, targets
from .cb_keys import (HIDDEN_PROP, NONKEYABLE_PROP, _flag_list, _set_flag_list, is_blend_key, is_input_key, is_keyable,
                      is_locked, set_locked)
from .cb_values import (channel_fcurves, curve_owner, driver, get_value, has_channel, keyframe, remove_channel_curves,
                        set_value)
from .cb_selection import _visible_channels, selected_channels


class _ChannelAction:
    """Base: acts on selected channels of all target objects."""
    bl_options = {'REGISTER', 'UNDO'}
    use_all = False  # True: every visible channel when nothing is selected

    @classmethod
    def poll(cls, context):
        return lead(context) is not None

    def channel_keys(self, context, ob):
        sel = selected_channels(context)
        if not sel and self.use_all:
            return _visible_channels(ob)
        return [k for k in sel if has_channel(ob, k)]

    def execute(self, context):
        count = 0
        for ob in targets(context):
            for key in self.channel_keys(context, ob):
                count += bool(self.act(context, ob, key))
        results.result(self, f"{self.bl_label}: {count} channel(s)")
        return {'FINISHED'}


def _op(idname, label, doc, act, use_all=False, **props):
    cls = type(f"ALLSET_OT_{idname}", (_ChannelAction, bpy.types.Operator), {
        "bl_idname": f"allset.{idname}", "bl_label": label, "__doc__": doc,
        "act": act, "use_all": use_all, "__annotations__": props})
    return cls


def _act_key(self, context, ob, key):
    return is_keyable(ob, key) and keyframe(ob, key)


def _act_breakdown(self, context, ob, key):
    return is_keyable(ob, key) and keyframe(ob, key, 'BREAKDOWN')


def _act_mute(self, context, ob, key):
    curves = channel_fcurves(ob, key)
    for fc in curves:
        fc.mute = self.mute
    return bool(curves)


def _act_delete(self, context, ob, key):
    return remove_channel_curves(ob, key)


def _act_break(self, context, ob, key):
    done = _act_delete(self, context, ob, key)
    dr = driver(ob, key)
    if dr is not None:
        owner = curve_owner(ob, key) if is_blend_key(key) or is_input_key(key) else ob.id_data
        owner.animation_data.drivers.remove(dr)
        done = True
    return done


def _act_lock(self, context, ob, key):
    return set_locked(ob, key, self.lock)


def _act_hide(self, context, ob, key):
    if self.lock:
        set_locked(ob, key, True)
    _set_flag_list(ob, HIDDEN_PROP, _flag_list(ob, HIDDEN_PROP) + [key])
    return True


def _act_keyable(self, context, ob, key):
    keys = [k for k in _flag_list(ob, NONKEYABLE_PROP) if k != key]
    if not self.keyable:
        keys.append(key)
    _set_flag_list(ob, NONKEYABLE_PROP, keys)
    return True


def _act_duplicate(self, context, ob, key):
    ld = lead(context)
    if ob == ld or not has_channel(ld, key) or is_locked(ob, key):
        return False
    set_value(ob, key, get_value(ld, key))
    return True


CHANNEL_OPS = (
    _op("cb_key_selected", "Key Selected", "Set a key on the selected channels", _act_key),
    _op("cb_key_all", "Key All Keyable", "Set a key on every keyable channel", _act_key, use_all=True),
    _op("cb_breakdown_selected", "Breakdown Selected", "Set a breakdown key on the selected channels",
        _act_breakdown),
    _op("cb_mute", "Mute Selected", "Mute or unmute the animation of the selected channels", _act_mute,
        mute=BoolProperty(default=True)),
    _op("cb_delete_keys", "Delete Selected", "Delete the animation curves of the selected channels",
        _act_delete),
    _op("cb_break_connections", "Break Connections",
        "Remove the animation curve or driver feeding the selected channels", _act_break),
    _op("cb_lock", "Lock Selected", "Lock or unlock the selected channels", _act_lock,
        lock=BoolProperty(default=True)),
    _op("cb_hide", "Hide Selected", "Hide the selected channels from the Channel Box", _act_hide,
        lock=BoolProperty(default=False)),
    _op("cb_keyable", "Make Selected Keyable", "Make the selected channels keyable or nonkeyable",
        _act_keyable, keyable=BoolProperty(default=True)),
    _op("cb_duplicate_values", "Duplicate Values",
        "Copy the lead object's values of the selected channels to the other selected objects",
        _act_duplicate),
)


class ALLSET_OT_cb_show_all(bpy.types.Operator):
    """Show every hidden channel again"""
    bl_idname = "allset.cb_show_all"
    bl_label = "Show All Channels"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for ob in targets(context):
            _set_flag_list(ob, HIDDEN_PROP, [])
        return {'FINISHED'}


# --- menus -------------------------------------------------------------------------------------------

class ALLSET_MT_cb_channels(bpy.types.Menu):
    """Maya Channel Box Channels menu (RMB anywhere in the Channel Box)"""
    bl_label = "Channels"

    def draw(self, context):
        from .. import preferences
        lay = self.layout
        lay.operator("allset.cb_key_selected")
        lay.operator("allset.cb_key_all")
        lay.operator("allset.cb_breakdown_selected")
        lay.operator("allset.cb_breakdown_all")
        lay.operator("allset.cb_mute", text="Mute Selected").mute = True
        lay.operator("allset.cb_mute_all", text="Mute All").mute = True
        lay.operator("allset.cb_mute", text="Unmute Selected").mute = False
        lay.operator("allset.cb_mute_all", text="Unmute All").mute = False
        lay.separator()
        prefs = preferences.get(context)
        lay.prop(prefs, "cb_sync_graph", text="Sync Selection in Graph Editor")
        lay.prop(prefs, "cb_sync_timeline", text="Sync Timeline Display")
        lay.separator()
        lay.operator("allset.cb_clipboard", text="Cut Selected").action = "CUT"
        lay.operator("allset.cb_clipboard", text="Copy Selected").action = "COPY"
        lay.operator("allset.cb_clipboard", text="Paste Selected").action = "PASTE"
        lay.operator("allset.cb_delete_keys")
        lay.separator()
        lay.operator("allset.cb_duplicate_values")
        lay.menu(ALLSET_MT_cb_freeze.__name__)
        lay.separator()
        lay.operator("allset.cb_break_connections")
        lay.operator("allset.cb_select_connection")
        lay.separator()
        lay.operator("allset.cb_lock", text="Lock Selected").lock = True
        lay.operator("allset.cb_lock", text="Unlock Selected").lock = False
        lay.operator("allset.cb_hide", text="Hide Selected").lock = False
        lay.operator("allset.cb_hide", text="Lock and Hide Selected").lock = True
        lay.operator("allset.cb_show_all")
        lay.operator("allset.cb_keyable", text="Make Selected Nonkeyable").keyable = False
        lay.operator("allset.cb_keyable", text="Make Selected Keyable").keyable = True
        lay.separator()
        # the selected animation layer's attributes (operators/anim_layers.py, Maya animLayer -attribute)
        lay.operator("allset.anim_layer_attrs", text="Add to Selected Layers").add = True
        lay.operator("allset.anim_layer_attrs", text="Remove From Selected Layers").add = False
        lay.separator()
        lay.operator("allset.cb_deselect_channels")


class ALLSET_MT_cb_freeze(bpy.types.Menu):
    """Maya Channels > Freeze (makeIdentity -apply on the chosen channels)"""
    bl_label = "Freeze"

    def draw(self, context):
        lay = self.layout
        for text, t, r, sc in (("Translate", True, False, False), ("Rotate", False, True, False),
                               ("Scale", False, False, True), ("All", True, True, True)):
            op = lay.operator("allset.freeze_transform", text=text)
            op.translate, op.rotate, op.scale = t, r, sc


class ALLSET_MT_cb_settings(bpy.types.Menu):
    bl_label = "Settings"

    def draw(self, context):
        from .. import preferences
        prefs = preferences.get(context)
        lay = self.layout
        lay.label(text="Virtual slider speed")
        lay.prop(prefs, "cb_speed", expand=True)
        lay.prop(prefs, "cb_hyperbolic")
        lay.separator()
        lay.prop(prefs, "cb_radius_hierarchy")
        lay.prop(prefs, 'cb_manipulators', text='Manipulators')


class ALLSET_MT_cb_edit(bpy.types.Menu):
    """Maya Channel Box Edit menu"""
    bl_label = "Edit"

    def draw(self, context):
        lay = self.layout
        chrome.grey(lay, "Expressions...")
        lay.operator("allset.sdk_window", text="Set Driven Key...")
        lay.operator("allset.open_editor", text="Graph Editor").ui_type = 'FCURVES'
        chrome.grey(lay, "Channel Control...")
        chrome.grey(lay, "Connection Editor")
        lay.operator("allset.dock_show", text="Attribute Editor").dock = 'ATTRIBUTE_EDITOR'
        lay.operator("allset.material_attributes", text="Material Attributes...")
        lay.separator()
        lay.operator("allset.add_attribute", text="Add Attribute...")
        lay.operator("allset.edit_attribute", text="Edit Attribute...")
        chrome.grey(lay, "Duplicate Attribute")
        lay.operator("allset.delete_attribute", text="Delete Attributes")
        lay.separator()
        lay.operator(ALLSET_OT_cb_make_lead.bl_idname, text="Select Node").only = True
        lay.operator("allset.delete", text="Delete Node")
        lay.operator("allset.delete_history", text="Delete History")
        lay.separator()
        lay.menu("ALLSET_MT_cb_settings", text="Settings")
        chrome.grey(lay, "Channel Names")


class ALLSET_OT_cb_make_lead(bpy.types.Operator):
    """Make this object the lead (Maya Channel Box Object menu: select -add)"""
    bl_idname = "allset.cb_make_lead"
    bl_label = "Lead Object"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    name: StringProperty(options={'SKIP_SAVE'})
    only: BoolProperty(name="Only", description="Select only this object", options={'SKIP_SAVE'})

    def execute(self, context):
        if pose_armature(context):
            return self._bone(context)
        ob = context.scene.objects.get(self.name) if self.name else context.active_object
        if ob is None:
            return {'CANCELLED'}
        if self.only:
            for other in context.selected_objects:
                other.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        return {'FINISHED'}

    def _bone(self, context):
        bones = [pb for arm in pose_objects(context) for pb in arm.pose.bones]
        pb = next((b for b in bones if b.name == self.name), None) if self.name else lead(context)
        if pb is None:
            return {'CANCELLED'}
        if self.only:
            for other in bones:
                set_bone_selected(other, False)
        set_bone_selected(pb, True)
        pb.id_data.data.bones.active = pb.bone
        return {'FINISHED'}


class ALLSET_OT_cb_rotate_order(bpy.types.Operator):
    """Set the rotate order (Blender converts the rotation, the pose stays): Maya channels need Euler"""
    bl_idname = "allset.cb_rotate_order"
    bl_label = "Rotate Order"
    bl_options = {'REGISTER', 'UNDO'}

    order: EnumProperty(name="Rotate Order", items=[(m, m, "") for m in
                                                    ('XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX')])

    @classmethod
    def poll(cls, context):
        return lead(context) is not None

    def execute(self, context):
        for node in targets(context):
            node.rotation_mode = self.order
        return {'FINISHED'}


class ALLSET_MT_cb_object(bpy.types.Menu):
    """Maya Channel Box Object menu: the selected objects (joints in pose mode), picking one makes it
    the lead"""
    bl_label = "Object"

    def draw(self, context):
        lay = self.layout
        obs = targets(context)
        if not obs:
            chrome.grey(lay, "Nothing selected")
        ld = lead(context)
        for ob in obs[:10]:
            lay.operator(ALLSET_OT_cb_make_lead.bl_idname, text=ob.name,
                         icon='LAYER_ACTIVE' if ob == ld else 'BLANK1').name = ob.name


class ALLSET_MT_cb_show(bpy.types.Menu):
    """Maya Channel Box Show menu"""
    bl_label = "Show"

    def draw(self, context):
        lay = self.layout
        lay.operator("allset.cb_show_all", text="All")
        lay.separator()
        for label in ("Assets", "Attribute Type Filters"):
            chrome.grey(lay, label)


# Maya Channel Box menu bar, left to right.
MENU_BAR = (("Channels", "ALLSET_MT_cb_channels"), ("Edit", "ALLSET_MT_cb_edit"),
            ("Object", "ALLSET_MT_cb_object"), ("Show", "ALLSET_MT_cb_show"))
