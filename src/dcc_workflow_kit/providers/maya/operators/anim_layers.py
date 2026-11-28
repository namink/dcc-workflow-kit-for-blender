# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya animation layers on Blender NLA tracks.

Maya: BaseAnimation = the plain anim curves; an Additive
layer adds weight x its curve (rotations Euler component-wise, scale multiplies: below x layer^weight), an Override
layer replaces ((1 - w) below + w layer); mute drops a layer, solo keeps BaseAnimation + the soloed layers; a key set
on the selected layer is the curve value that makes the result the displayed value.

Blender 4.5 NLA gives the same numbers: BaseAnimation = a REPLACE strip on the bottom track,
Additive = COMBINE (location / Euler add, scale multiplies with influence as exponent), Override = REPLACE, weight =
the strip influence, mute = track mute; strips span a fixed wide range with 1:1 time so every key is evaluated.
Blender's tweak mode evaluates only the tracks below the tweaked one (no Python switch for the upper stack), so keys
are not set through tweak mode: ``key()`` solves the layer value from the composition rule itself.

Layers are scene-wide (``Scene.allset_anim_layers``, first entry BaseAnimation) like Maya's animLayer nodes; every
member object has one NLA track per layer, named like the layer, playing an action ``<layer>_<object>`` marked with
the ID property ``allset_anim_layer``.

blendShape weights (a mesh's shape key values) join layers through their own node like Maya's blendShape node: the
mesh's Key datablock gets the NLA tracks (Channel Box > Channels > Add to Selected Layers with weights selected).
``layer_ids`` = the objects plus the Key datablocks of their meshes.

Display: Maya's Graph Editor, Dope Sheet and Time Slider show the
keys of the layers selected in the Anim tab, the Channel Box marks layer members teal. A layered object's active
action is the selected layer's strip action (BaseAnimation when the object is not in it) at action influence 0: the
NLA result is unchanged, and every reader of the active action (Graph Editor,
Dope Sheet, compat.id_fcurves, the kit's key readers) sees that layer's curves.

Code: anim_layer_tracks (layer list, NLA tracks, sync / show), anim_layer_members (attribute membership),
anim_layer_keys (composition, keys); this module keeps the Layer Editor operators, Zero Key / Merge Layers, the
scene properties and re-exports the names of those modules.
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, IntProperty, StringProperty

from . import naming
from .anim_layer_tracks import (add_object, _add_track, BASE, blend_node, display_layer, ensure_base, ensure_list,
                                _evaluate, _fcurve, has_layers, is_scale, layer_curves, layer_ids, layers, _leaf, MARK,
                                members, _new_action, order_tracks, remove_object, restore_strip_state, SCALE_PATHS,
                                selected, selected_layers, _set_influence, show, show_base, _slot, _strip, strip_state,
                                strip_weight, sync, tracks, weight_curve, WIDE)  # noqa: F401
from .anim_layer_members import (add_attrs, _attr_record, ATTRS, base_curve, BONE, bone_of, bone_path, channel_key,
                                 hidden_base_curves, is_member, member_bones, member_keys, member_of_layer,
                                 remove_attrs, _set_attr_record, target_layer)  # noqa: F401
from .anim_layer_keys import (below_value, compose, compose_quaternion, key, key_pose_bone, key_quaternion, _new_fcurve,
                              _quat_layers, _quat_power, result, settle_base, solve, _steps)  # noqa: F401


def unique_name(scene, base="AnimLayer"):
    """Maya ``AnimLayer<N>``: one past the highest, gaps not filled."""
    return f"{base}{naming.next_number(base, {e.name for e in layers(scene)})}"


# --- operators -------------------------------------------------------------------------------------

def _sync_update(self, context):
    sync(context.scene)


def _index_update(self, context):
    show(self)


@persistent
def _load_post(_dummy):
    """Files layered by older kit versions have no active action: show the selected layer."""
    for scene in bpy.data.scenes:
        if len(layers(scene)):
            show(scene)


class ALLSET_PG_anim_layer(bpy.types.PropertyGroup):
    weight: FloatProperty(name="Weight", default=1.0, min=0.0, max=1.0, update=_sync_update,
                          description="Maya layer weight (NLA strip influence)")
    mute: BoolProperty(name="Mute", update=_sync_update, description="Mute layer")
    solo: BoolProperty(name="Solo", update=_sync_update, description="Solo layer (BaseAnimation stays)")
    lock: BoolProperty(name="Lock", update=_sync_update, description="Lock layer: no keys")
    override: BoolProperty(name="Override", update=_sync_update,
                           description="Override the layers below (else Additive)")
    picked: BoolProperty(name="Selected", options={'HIDDEN'},
                         description="Selected in the Layer Editor (Ctrl / Shift click)")


def _layer_entry(scene, name=""):
    """The layer a single-layer command acts on: ``name`` (the layer row's right-click menu) or the selected
    one."""
    if name:
        return next((e for e in layers(scene) if e.name == name), None)
    return selected(scene)


ROW_LAYER = dict(options={'SKIP_SAVE', 'HIDDEN'}, description="Act on this layer only (layer right-click menu)")


def _layer_objects(context):
    return [ob for ob in context.selected_objects if ob.type in {'MESH', 'CURVE', 'SURFACE', 'EMPTY', 'ARMATURE',
                                                               'LIGHT', 'CAMERA', 'LATTICE', 'META', 'FONT'}]


def _selected_joints(context, ob):
    """Selected joints of an armature in pose mode (Maya: the joint nodes picked), else []."""
    if ob.type != 'ARMATURE' or ob.mode != 'POSE':
        return []
    from ..ui import channel_box as cb
    return [pb.name for pb in ob.pose.bones if cb.bone_selected(pb)]


def add_selected(context, layer):
    """Maya Create Layer from Selected / Add Selected Objects: objects join whole, joints in pose mode one by one."""
    for ob in _layer_objects(context):
        bones = _selected_joints(context, ob)
        if bones:
            add_attrs(context.scene, ob, layer, [BONE + n for n in bones])
        else:
            add_object(context.scene, ob, layer)


class ALLSET_OT_anim_layer_create(bpy.types.Operator):
    """Create an animation layer, empty or with the selected objects (Maya Create Empty Layer / Create Layer from
    Selected)"""
    bl_idname = "allset.anim_layer_create"
    bl_label = "Create Animation Layer"
    bl_options = {'UNDO'}

    from_selected: BoolProperty(default=False, options={'SKIP_SAVE'})

    def execute(self, context):
        scene = context.scene
        ls = ensure_list(scene)
        e = ls.add()
        e.name = unique_name(scene)
        scene.allset_anim_layer_index = len(ls) - 1
        if self.from_selected:
            add_selected(context, e.name)
        sync(scene)
        return {'FINISHED'}


class ALLSET_OT_anim_layer_members(bpy.types.Operator):
    """Add the selected objects to the selected layer, or remove them (Maya Add / Remove Selected Objects)"""
    bl_idname = "allset.anim_layer_members"
    bl_label = "Layer Members"
    bl_options = {'UNDO'}

    add: BoolProperty(default=True, options={'SKIP_SAVE'})
    layer: StringProperty(**ROW_LAYER)

    def execute(self, context):
        e = _layer_entry(context.scene, self.layer)
        if e is None or e.name == BASE:
            self.report({'WARNING'}, "Select an animation layer")
            return {'CANCELLED'}
        if self.add:
            add_selected(context, e.name)
        else:
            for ob in _layer_objects(context):
                bones = _selected_joints(context, ob)
                if bones:
                    remove_attrs(context.scene, ob, e.name, [BONE + n for n in bones])
                else:
                    remove_object(context.scene, ob, e.name)
        sync(context.scene)
        return {'FINISHED'}


class ALLSET_OT_anim_layer_attrs(bpy.types.Operator):
    """Add the Channel Box's selected channels to the selected animation layer, or remove them (Maya Channel Box >
    Channels > Add to / Remove From Selected Layers)"""
    bl_idname = "allset.anim_layer_attrs"
    bl_label = "Selected Layers"
    bl_options = {'UNDO'}

    add: BoolProperty(default=True, options={'SKIP_SAVE'})

    def execute(self, context):
        from ..ui import channel_box as cb
        scene = context.scene
        e = selected(scene)
        if e is None or e.name == BASE:
            self.report({'WARNING'}, "Select an animation layer")
            return {'CANCELLED'}
        keys = cb.selected_channels(context)
        obs = [ob for ob in _layer_objects(context)]
        if not keys or not obs:
            self.report({'WARNING'}, "Select attributes in the Channel Box")
            return {'CANCELLED'}
        for ob in obs:
            mine = [k for k in keys if cb.has_channel(ob, k)]
            weights = [k for k in mine if cb.is_blend_key(k)]
            node = blend_node(ob) if weights else None
            if node is not None:
                # Maya: blendShape weights join the layer on the blendShape node, not on the mesh's transform
                (add_attrs if self.add else remove_attrs)(scene, node, e.name, weights)
            mine = [k for k in mine if not cb.is_blend_key(k)]
            if mine:
                (add_attrs if self.add else remove_attrs)(scene, ob, e.name, mine)
        sync(scene)
        return {'FINISHED'}


class ALLSET_OT_anim_layer_delete(bpy.types.Operator):
    """Delete the selected animation layer and its keys (Maya Delete Layer)"""
    bl_idname = "allset.anim_layer_delete"
    bl_label = "Delete Animation Layer"
    bl_options = {'UNDO'}

    layer: StringProperty(**ROW_LAYER)

    def execute(self, context):
        scene = context.scene
        e = _layer_entry(scene, self.layer)
        if e is None or e.name == BASE:
            self.report({'WARNING'}, "BaseAnimation can't be deleted")
            return {'CANCELLED'}
        name = e.name
        for ob in members(scene, name):
            remove_object(scene, ob, name)
        ls = layers(scene)
        ls.remove(next(i for i, x in enumerate(ls) if x.name == name))
        scene.allset_anim_layer_index = max(0, min(scene.allset_anim_layer_index, len(ls) - 1))
        sync(scene)
        return {'FINISHED'}


def _identity(path):
    return 1.0 if is_scale(path) else 0.0


def zero_key(scene, obs, frame=None):
    """Maya Zero Key Layer (``cmds.setKeyframe(identity=True,
    inTangentType="flat")``): an identity key on every member channel of the selected layer at ``frame`` (an existing
    key's value is overwritten, its tangents kept; a new key's in tangent is flat). Returns the number of keys, None for
    BaseAnimation."""
    e = selected(scene)
    if e is None or e.name == BASE:
        return None
    frame = scene.frame_current if frame is None else frame
    from ..ui import channel_box as cb
    n = 0
    for ob in obs:
        if e.name not in tracks(ob):
            continue
        act = _strip(tracks(ob)[e.name]).action
        for k in member_keys(ob, e.name):
            path, idx, _kind = cb.channel_path(k)
            try:
                v = ob.path_resolve(path)
                v = v[idx] if idx >= 0 else v
            except (ValueError, TypeError, IndexError):
                continue
            if isinstance(v, bool):       # visibility is not layered by the kit's NLA tracks
                continue
            idx = max(idx, 0)
            fc = _fcurve(act, path, idx) or _new_fcurve(ob, act, path, idx)
            if fc is None:
                continue
            old = next((kp for kp in fc.keyframe_points if abs(kp.co.x - frame) < 1e-4), None)
            if old is not None:
                d = _identity(path) - old.co.y
                old.co.y += d
                old.handle_left.y += d
                old.handle_right.y += d
            else:
                kp = fc.keyframe_points.insert(frame, _identity(path))
                kp.handle_left_type = 'FREE'
                kp.handle_left.y = kp.co.y
            fc.update()
            n += 1
        ob.update_tag(refresh={'TIME'})
    return n


def merge_down(scene, layer):
    """Maya Merge Layers with BaseAnimation and ``layer`` selected (default options:
    bake every frame, delete the merged layer): each member channel of ``layer`` gets a BaseAnimation curve keyed on
    every whole frame of the object's key range with the result of Base + ``layer``; non-member channels keep their
    keys; the layer is deleted."""
    if layer == BASE:
        return False
    for ob in members(scene, layer):
        base_act = _strip(tracks(ob)[BASE]).action
        curves = layer_curves(ob, BASE) + layer_curves(ob, layer)
        xs = [kp.co.x for fc in curves for kp in fc.keyframe_points]
        if not xs:
            continue
        frames = range(int(round(min(xs))), int(round(max(xs))) + 1)
        info = {e.name: e for e in layers(scene)}
        lay = tracks(ob)[layer]
        st = _strip(lay)
        mode = 'REPLACE' if info[layer].override else None
        w = 0.0 if info[layer].mute else (st.influence if st.use_animated_influence else 1.0)
        baked = {}
        for fc in layer_curves(ob, layer):
            path, idx = fc.data_path, fc.array_index
            if not is_member(ob, layer, path, idx):
                continue
            m = mode or ('MUL' if is_scale(path) else 'ADD')
            bfc = _fcurve(base_act, path, idx)
            rest = _identity(path)     # NLA starts a channel no lower strip animates from its default (see key())
            vals = []
            for f in frames:
                below = bfc.evaluate(f) if bfc is not None else rest
                vals.append(compose([(m, w, fc.evaluate(f))], below))
            baked[(path, idx)] = vals
        for (path, idx), vals in baked.items():
            bfc = _fcurve(base_act, path, idx) or _new_fcurve(ob, base_act, path, idx)
            if bfc is None:
                continue
            bfc.keyframe_points.clear()
            bfc.keyframe_points.add(len(vals))
            for kp, f, v in zip(bfc.keyframe_points, frames, vals):
                kp.co = (f, v)
                kp.interpolation = 'BEZIER'
                kp.handle_left_type = kp.handle_right_type = 'AUTO_CLAMPED'
            bfc.update()
        remove_object(scene, ob, layer)
        ob.update_tag(refresh={'TIME'})
    ls = layers(scene)
    i = next((i for i, x in enumerate(ls) if x.name == layer), None)
    if i is not None:
        ls.remove(i)
    scene.allset_anim_layer_index = 0
    sync(scene)
    return True


class ALLSET_OT_anim_layer_zero_key(bpy.types.Operator):
    """Set an identity key on the selected layer's attributes at the current time (Maya Zero Key Layer)"""
    bl_idname = "allset.anim_layer_zero_key"
    bl_label = "Zero Key Layer"
    bl_options = {'UNDO'}

    def execute(self, context):
        n = zero_key(context.scene, _layer_objects(context))
        if n is None:
            self.report({'WARNING'}, "Cannot set an identity key on BaseAnimation")
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_anim_layer_merge(bpy.types.Operator):
    """Merge the selected layer into BaseAnimation, baking every frame (Maya Merge Layers with BaseAnimation and
    the layer selected)"""
    bl_idname = "allset.anim_layer_merge"
    bl_label = "Merge Layers"
    bl_options = {'UNDO'}

    layer: StringProperty(**ROW_LAYER)

    def execute(self, context):
        e = _layer_entry(context.scene, self.layer)
        if e is None or e.name == BASE:
            self.report({'WARNING'}, "Select an animation layer to merge into BaseAnimation")
            return {'CANCELLED'}
        merge_down(context.scene, e.name)
        return {'FINISHED'}


class ALLSET_OT_anim_layer_select(bpy.types.Operator):
    """Make this the selected layer: keys go to it (Maya click on a layer; Ctrl+click adds / removes, Shift+click
    selects a range)"""
    bl_idname = "allset.anim_layer_select"
    bl_label = "Select Animation Layer"
    bl_options = {'INTERNAL'}

    index: IntProperty(options={'SKIP_SAVE'})
    toggle: BoolProperty(options={'SKIP_SAVE'}, description="Ctrl: add / remove this layer")
    extend_range: BoolProperty(options={'SKIP_SAVE'}, description="Shift: select the range up to this layer")

    def invoke(self, context, event):
        from . import keystate
        self.toggle = event.ctrl or any(keystate.is_down(k) for k in ("LEFT_CTRL", "RIGHT_CTRL"))
        self.extend_range = not self.toggle and (
            event.shift or any(keystate.is_down(k) for k in ("LEFT_SHIFT", "RIGHT_SHIFT")))
        return self.execute(context)

    def execute(self, context):
        from . import anim_layers_204
        anim_layers_204.pick(context.scene, self.index, toggle=self.toggle, extend=self.extend_range)
        anim_layers_204.redraw(context)
        return {'FINISHED'}


classes = (ALLSET_PG_anim_layer, ALLSET_OT_anim_layer_create, ALLSET_OT_anim_layer_members, ALLSET_OT_anim_layer_attrs,
           ALLSET_OT_anim_layer_delete, ALLSET_OT_anim_layer_select, ALLSET_OT_anim_layer_zero_key,
           ALLSET_OT_anim_layer_merge)


def register_props():
    bpy.types.Scene.allset_anim_layers = CollectionProperty(type=ALLSET_PG_anim_layer)
    bpy.types.Scene.allset_anim_layer_index = IntProperty(name="Selected Layer", default=0, min=0,
                                                          update=_index_update)
    bpy.app.handlers.load_post.append(_load_post)


def unregister_props():
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    del bpy.types.Scene.allset_anim_layer_index
    del bpy.types.Scene.allset_anim_layers
