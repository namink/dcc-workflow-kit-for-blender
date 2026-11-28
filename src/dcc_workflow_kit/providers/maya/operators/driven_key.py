# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Set Driven Key (Key > Set Driven Key > Set... / Go to Previous / Go to Next).

Maya's result is an animCurveUU from the driver attribute to the driven one.
Blender equivalent: a driver on the driven
channel (one variable ``sdk`` reading the driver channel, type AVERAGE = the variable) whose
F-curve has keys (driver value, driven value) — the same curve shape.
Values are raw RNA values (radians, metres), so the mapping is the one the user posed.

Blender writes a driver's result back over a typed value at the next update,
so while the Set Driven Key window is open, a Channel Box edit of a channel driven by a kit SDK
driver mutes that driver until Key (which records the pose) or Close (which drops it).
The window state lives on the WindowManager like a Maya window (not undoable, not saved).

Maya 2026 behaviour:
1. Curve shape = Maya 2026 ``auto`` tangents written by the kit (``maya_auto``): end keys flat, a key between two
   neighbours gets the slope (y[i+1] - y[i-1]) / (x[i+1] - x[i-1]), a local extreme is flat (sdk_three_keys: the
   middle key's slope is 9 = 90 / 10; sdk_four_keys_overshoot: both inner keys flat). Blender's own handle modes
   (Auto / Auto Clamped, with or without Continuous Acceleration) give other shapes,
   so the handles are ALIGNED at a third of each segment with that slope. Pre / post infinity Constant.
2. A second driver on the same driven channel = Maya ``blendWeighted`` (the inputs are **added**, sdk_two_drivers):
   every driver's curve sits on a hidden float ID property ``allset_sdk_<n>`` of the file's input helper (
   its own kit SDK driver, variable ``sdk``), and the channel's driver becomes a SUM over variables ``sdk``, ``sdk1`` ...
   reading those properties (``is_blend``). Key on a summed channel keys that driver's input so the sum equals the
   posed value (posed - the other inputs' current values; Maya keys one blendWeighted input).
3. Driven nodes besides objects / joints (Maya: any keyable attribute): a mesh's blendShape (its shape Key ID, one
   attribute per target = key block ``value``) and constraint nodes (Maya ``<target>W0`` = ``influence``, or the
   owner's ``allset_w_<constraint>`` weight property when a multi-target constraint group or a one-target
   constraint with its own weight, constrain_multi.ensure_single_weight, keeps one).
   Their values are not Channel Box channels, so posing them is held through msgbus (``_watch``), not WRITE_HOOKS.

#186: Blender doesn't order a driver that writes an ID property against another driver of the same ID
that reads it, so a SUM over inputs kept on the driven ID itself read a stale input now and then. The hidden inputs
live on their own data-block instead (like Maya's blendWeighted node): one hidden Texture per file (``helper``,
type NONE, fake user, marked ``HELPER``). Older files are moved over on load (``sync``), inputs a copied object
shares with its original get their own copy, and inputs no channel reads any more are dropped.

Code: driven_key_channels (nodes, channels, finding SDK curves), driven_key_drivers (making SDK curves, blendWeighted
inputs and their upkeep); this module keeps the window state, holding posed values, the operators and register.
"""

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty

from .. import results
from ..ui import channel_box as cb
from .driven_key_channels import (VAR, INPUT_PROP, SHAPE, WEIGHT, WEIGHT_PROP, HELPER, HELPER_NAME,  # noqa: F401
                                  node_of, item_node, is_key, is_constraint, constraint_owner, node_ref, store,
                                  node_label, extra_nodes, channels, attr_label, Chan, chan, raw_value,
                                  set_raw_value, _id_type, is_sdk, is_blend, sdk_fcurve, input_curves,
                                  driver_curve, LENGTH_KEYS, curve_scale, fcurve_scale, input_x, input_value)
from .driven_key_drivers import (maya_slopes, maya_auto, is_helper, helpers, helper, to_blend,  # noqa: F401
                                 ensure_driver, set_key, key_xs, step_to, all_sdk_curves, move_inputs, sync,
                                 _COUNTS, sync_if_changed, release_all)


# --- window state ----------------------------------------------------------------------------------

class ALLSET_PG_sdk_node(bpy.types.PropertyGroup):
    object: PointerProperty(type=bpy.types.Object)
    bone: StringProperty()
    kind: StringProperty()     # '' object / joint, 'KEY' its blendShape, 'CON' its constraint ``sub``
    sub: StringProperty()


class ALLSET_PG_sdk_item(bpy.types.PropertyGroup):
    key: StringProperty()      # channel key (channel_box, or SHAPE / WEIGHT)
    label: StringProperty()


class ALLSET_PG_sdk(bpy.types.PropertyGroup):
    open: BoolProperty(name="Set Driven Key")
    driver: PointerProperty(type=ALLSET_PG_sdk_node)
    driver_attr: StringProperty()
    driven: CollectionProperty(type=ALLSET_PG_sdk_node)
    driven_index: IntProperty()
    driven_attrs: StringProperty()          # comma-separated channel keys
    # rows of the scrolling attribute lists (UIList needs collections); rebuilt by refresh_items()
    driver_items: CollectionProperty(type=ALLSET_PG_sdk_item)
    driver_items_index: IntProperty()
    driven_items: CollectionProperty(type=ALLSET_PG_sdk_item)
    driven_items_index: IntProperty()


def state(context=None):
    return (context or bpy.context).window_manager.allset_sdk


def driver_node(st):
    return item_node(st.driver)


def driven_nodes(st):
    return [n for n in (item_node(i) for i in st.driven) if n is not None]


def driven_keys(st):
    return [k for k in st.driven_attrs.split(",") if k]


def _fill(items, node, selected):
    items.clear()
    first = -1
    for i, key in enumerate(channels(node) if node is not None else ()):
        item = items.add()
        item.key, item.label = key, attr_label(node, key)
        if first < 0 and key in selected:
            first = i
    return max(first, 0)


def refresh_items(st):
    """Rebuild the attribute rows; the lists scroll to the first selected attribute."""
    st.driver_items_index = _fill(st.driver_items, driver_node(st), {st.driver_attr})
    nodes = driven_nodes(st)
    node = nodes[min(st.driven_index, len(nodes) - 1)] if nodes else None
    st.driven_items_index = _fill(st.driven_items, node, set(driven_keys(st)))


def hold_driven(node, key):
    """cb_values.set_value hook: keep a typed value on a channel the SDK window drives."""
    try:
        st = state()
    except AttributeError:
        return
    if not st.open:
        return
    fc = sdk_fcurve(node, key)
    if fc is not None:
        fc.mute = True


# Blend shape weights and constraint weights are posed outside the Channel Box (Shape Editor, AE, Properties), so no
# WRITE_HOOKS call reaches us: an RNA subscription on each loaded driven value of those nodes mutes its SDK driver
# the same way. Driver results are written without an RNA update, so they don't publish (GUI unverified).
_MSG = object()


def _on_posed(id_name, id_kind, path, index):
    st = state()
    if not st.open:
        return
    coll = bpy.data.shape_keys if id_kind == 'KEY' else bpy.data.objects
    idb = coll.get(id_name)
    ad = idb.animation_data if idb is not None else None
    fc = ad.drivers.find(path, index=max(index, 0)) if ad is not None else None
    if is_sdk(fc) and not fc.mute:
        fc.mute = True


# #146: msgbus notifies on the next event-loop pass, so a value typed into a blend
# shape / constraint weight and keyed before that pass met a depsgraph update first, and the unmuted driver wrote its
# result over it (the key became (90, 0)). The driven values seen after each update are kept; an update that finds a
# value changed since (= typed, not driven) mutes that SDK driver first — depsgraph_update_pre runs before drivers.
_SEEN = {}


def _loaded_chans(st):
    for node in driven_nodes(st):
        if not (is_key(node) or is_constraint(node)):
            continue
        for key in channels(node):
            c = chan(node, key)
            if c is not None and not c.attr.startswith('["'):
                yield c


def _remember(st):
    _SEEN.clear()
    for c in _loaded_chans(st):
        _SEEN[(c.id.name, c.path, c.index)] = c.get()


@bpy.app.handlers.persistent
def _before_update(_scene, _depsgraph=None):
    try:
        st = state()
    except (AttributeError, ReferenceError):
        return
    if not st.open or not _SEEN:
        return
    for c in _loaded_chans(st):
        seen = _SEEN.get((c.id.name, c.path, c.index))
        if seen is None or abs(c.get() - seen) < 1e-9:
            continue
        fc = c.find()
        if is_sdk(fc) and not fc.mute:
            fc.mute = True


@bpy.app.handlers.persistent
def _after_update(_scene, _depsgraph=None):
    try:
        sync_if_changed()
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    try:
        st = state()
    except (AttributeError, ReferenceError):
        return
    if st.open:
        _remember(st)
    elif _SEEN:
        _SEEN.clear()


def _watch(st):
    bpy.msgbus.clear_by_owner(_MSG)
    if st.open:
        _remember(st)
    else:
        _SEEN.clear()
    if not st.open:
        return
    for node in driven_nodes(st):
        if not (is_key(node) or is_constraint(node)):
            continue
        for key in channels(node):
            c = chan(node, key)
            if c is None or c.attr.startswith('["'):
                continue
            bpy.msgbus.subscribe_rna(key=c.struct.path_resolve(c.attr, False), owner=_MSG,
                                     args=(c.id.name, _id_type(c.id), c.path, c.index), notify=_on_posed)


def _redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# --- operators -----------------------------------------------------------------------------------

class ALLSET_OT_sdk_window(bpy.types.Operator):
    """Maya Set Driven Key window: load a driver and driven channels, pose, Key (Key > Set Driven Key > Set...)"""
    bl_idname = "allset.sdk_window"
    bl_label = "Set Driven Key"

    def execute(self, context):
        st = state(context)
        st.open = True
        if hasattr(bpy.ops.allset, "dock_show"):
            try:   # the window is drawn under the Channel Box in the sidebar dock
                bpy.ops.allset.dock_show(dock='CHANNEL_BOX')
            except RuntimeError:
                context.window_manager.allset_dock = 'CHANNEL_BOX'
        _watch(st)
        _redraw(context)
        return {'FINISHED'}


def blend_pick(node, sel):
    """(shape Key, its SDK keys) for the blendShape weight channels (``bw:<target>``) picked in the Channel Box on
    an object: Set Driven Key lists those weights under the blendShape node. (None, []) when none is picked."""
    names = [k[len(cb.BLEND_PREFIX):] for k in sel if cb.is_blend_key(k)]
    if not names or cb.is_bone(node) or is_key(node) or is_constraint(node):
        return None, []
    key = getattr(getattr(node, "data", None), "shape_keys", None)
    if key is None:
        return None, []
    have = set(channels(key))
    return key, [SHAPE + n for n in names if SHAPE + n in have]


class ALLSET_OT_sdk_load(bpy.types.Operator):
    """Load the lead (Driver) or every selected object / joint (Driven, with its blendShape and constraint
    nodes); the channels selected in the Channel Box become the selected attributes"""
    bl_idname = "allset.sdk_load"
    bl_label = "Load"

    which: EnumProperty(items=(('DRIVER', "Driver", ""), ('DRIVEN', "Driven", "")), options={'SKIP_SAVE'})

    def execute(self, context):
        st = state(context)
        sel = cb.selected_channels(context)
        if self.which == 'DRIVER':
            node = cb.lead(context)
            if node is None:
                self.report({'WARNING'}, "Select the driver object (or joint) first")
                return {'CANCELLED'}
            avail = channels(node)
            picked = next((k for k in sel if k in avail), "")
            key, weights = blend_pick(node, sel)
            if not picked and weights:      # a picked blendShape weight drives: the blendShape node is the driver
                store(st.driver, key, node)
                picked = weights[0]
            else:
                store(st.driver, node)
            st.driver_attr = picked
        else:
            nodes = cb.targets(context)
            if not nodes:
                self.report({'WARNING'}, "Select the driven objects (or joints) first")
                return {'CANCELLED'}
            st.driven.clear()
            for node in nodes:
                store(st.driven.add(), node)
                for extra in extra_nodes(node):
                    store(st.driven.add(), extra, node if is_key(extra) else None)
            st.driven_index = 0
            avail = set(channels(nodes[0]))
            picked = [k for k in sel if k in avail]
            key, weights = blend_pick(nodes[0], sel)
            if not picked and weights:      # picked blendShape weights: their node is the one shown
                st.driven_index = next((i for i, n in enumerate(driven_nodes(st)) if n == key), 0)
                picked = weights
            st.driven_attrs = ",".join(picked)
        refresh_items(st)
        _watch(st)
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_sdk_pick(bpy.types.Operator):
    """Pick an attribute (Driven: Ctrl adds / removes) or a driven node in the Set Driven Key lists"""
    bl_idname = "allset.sdk_pick"
    bl_label = "Pick"
    bl_options = {'INTERNAL'}

    which: EnumProperty(items=(('DRIVER', "Driver", ""), ('DRIVEN', "Driven", ""), ('NODE', "Node", "")),
                        options={'SKIP_SAVE'})
    key: StringProperty(options={'SKIP_SAVE'})
    index: IntProperty(options={'SKIP_SAVE'})
    toggle: BoolProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.toggle = self.toggle or event.ctrl or event.shift
        return self.execute(context)

    def execute(self, context):
        st = state(context)
        if self.which == 'DRIVER':
            st.driver_attr = self.key
        elif self.which == 'NODE':
            st.driven_index = self.index
            refresh_items(st)
        else:
            keys = driven_keys(st)
            if self.toggle:
                keys = [k for k in keys if k != self.key] if self.key in keys else keys + [self.key]
            else:
                keys = [self.key]
            st.driven_attrs = ",".join(keys)
        _redraw(context)
        return {'FINISHED'}


class ALLSET_OT_sdk_key(bpy.types.Operator):
    """Key: record (driver value, driven value) for every loaded driven attribute"""
    bl_idname = "allset.sdk_key"
    bl_label = "Key"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        st = state(context)
        return driver_node(st) is not None and st.driver_attr and driven_nodes(st) and driven_keys(st)

    def execute(self, context):
        st = state(context)
        drv = driver_node(st)
        count = 0
        for node in driven_nodes(st):
            if node == drv:
                continue
            avail = set(channels(node))
            for key in driven_keys(st):
                if key in avail:
                    set_key(node, key, drv, st.driver_attr)
                    count += 1
        context.view_layer.update()
        results.result(self, f"Set Driven Key: {count} key(s) at {cb.channel_label(st.driver_attr)} = "
                              f"{raw_value(drv, st.driver_attr):g}")
        return {'FINISHED'}


class ALLSET_OT_sdk_go(bpy.types.Operator):
    """Set the driver to the previous / next driven key (Key > Set Driven Key > Go to Previous / Next)"""
    bl_idname = "allset.sdk_go"
    bl_label = "Go to Driven Key"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=(('PREVIOUS', "Previous", ""), ('NEXT', "Next", "")), options={'SKIP_SAVE'})

    def execute(self, context):
        st = state(context)
        drv = driver_node(st)
        fcs = [fc for node in driven_nodes(st) for key in driven_keys(st)
               if (fc := driver_curve(node, key, drv, st.driver_attr)) is not None] if drv is not None else []
        if not fcs:
            self.report({'WARNING'}, "Load a driver and driven attributes with keys (Set Driven Key window)")
            return {'CANCELLED'}
        scale = fcurve_scale(fcs[0])
        x = step_to(key_xs(fcs), raw_value(drv, st.driver_attr) * scale, self.direction)
        if x is None:
            results.result(self, "No more driven keys")
            return {'CANCELLED'}
        release_all()
        set_raw_value(drv, st.driver_attr, x / scale)
        context.view_layer.update()
        return {'FINISHED'}


class ALLSET_OT_sdk_close(bpy.types.Operator):
    """Close the Set Driven Key window (driven values posed but not keyed go back to the curve)"""
    bl_idname = "allset.sdk_close"
    bl_label = "Close"

    def execute(self, context):
        st = state(context)
        st.open = False
        _watch(st)
        release_all()
        context.view_layer.update()
        _redraw(context)
        return {'FINISHED'}


@bpy.app.handlers.persistent
def _on_load(_dummy):
    _COUNTS[0] = None
    sync_if_changed()        # an older file's inputs move to the helper (no undo step of its own)
    release_all()
    try:
        _watch(state())      # a file load clears msgbus
    except (AttributeError, ReferenceError):
        pass


classes = (ALLSET_PG_sdk_node, ALLSET_PG_sdk_item, ALLSET_PG_sdk, ALLSET_OT_sdk_window, ALLSET_OT_sdk_load, ALLSET_OT_sdk_pick,
           ALLSET_OT_sdk_key, ALLSET_OT_sdk_go, ALLSET_OT_sdk_close)


def register_props():
    bpy.types.WindowManager.allset_sdk = PointerProperty(type=ALLSET_PG_sdk, options={'SKIP_SAVE'})
    cb.WRITE_HOOKS.append(hold_driven)
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.handlers.depsgraph_update_pre.append(_before_update)
    bpy.app.handlers.depsgraph_update_post.append(_after_update)
    _COUNTS[0] = None
    bpy.app.timers.register(_first_sync, first_interval=0.0)   # the open file (register can't edit data)


def _first_sync():
    try:
        sync_if_changed()
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    return None


def unregister_props():
    if bpy.app.timers.is_registered(_first_sync):
        bpy.app.timers.unregister(_first_sync)
    bpy.msgbus.clear_by_owner(_MSG)
    bpy.app.handlers.load_post.remove(_on_load)
    for lst, fn in ((bpy.app.handlers.depsgraph_update_pre, _before_update),
                    (bpy.app.handlers.depsgraph_update_post, _after_update)):
        if fn in lst:
            lst.remove(fn)
    _SEEN.clear()
    if hold_driven in cb.WRITE_HOOKS:
        cb.WRITE_HOOKS.remove(hold_driven)
    del bpy.types.WindowManager.allset_sdk
