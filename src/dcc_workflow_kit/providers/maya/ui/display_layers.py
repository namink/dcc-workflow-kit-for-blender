# SPDX-License-Identifier: GPL-3.0-or-later
"""Display layer data on collections: the excluded "Display Layers" collection and its layers (``layers``,
``display_order``, ``new_layer``, ``delete_layer``), objects and joints as members (``add_nodes``, ``remove_nodes``,
``layer_of``, ``selected_nodes``), the V / T / R override on members that never changes their own settings
(``apply_layer``, ``apply_display``, ``OWN``, ``INHERITED``) and the Playback (P) handlers. UI: ``layer_editor``.
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, IntProperty

from .. import compat
from . import layer_joints
from ..operators import naming

ROOT_NAME = "Display Layers"
TYPES = (("NORMAL", "Normal", "Selectable, normal display"),
         ("TEMPLATE", "Template", "Unselectable, wireframe (Maya T)"),
         ("REFERENCE", "Reference", "Unselectable (Maya R)"))
TYPE_LETTER = {"NORMAL": " ", "TEMPLATE": "T", "REFERENCE": "R"}


def _update(self, context):
    coll = self.id_data
    if self.is_layer:
        apply_layer(coll)


class ALLSET_PG_layer(bpy.types.PropertyGroup):
    is_layer: BoolProperty(options={'HIDDEN'})
    visible: BoolProperty(name="Visible", default=True, update=_update,
                          description="Show the layer's objects (Maya V)")
    playback: BoolProperty(name="Playback", default=True, update=_update,
                           description="Show the layer's objects during playback (Maya P)")
    display_type: EnumProperty(name="Display Type", items=TYPES, default="NORMAL", update=_update)
    # list position: Maya lists the newest layer on top and Move Up / Down reorders (Maya Layer Editor)
    order: IntProperty(options={'HIDDEN'})


# --- data helpers -------------------------------------------------------------------------------

def root(scene, create=False):
    coll = scene.collection.children.get(ROOT_NAME)
    if coll is None and create:
        coll = bpy.data.collections.new(ROOT_NAME)
        scene.collection.children.link(coll)
        for vl in scene.view_layers:
            lc = vl.layer_collection.children.get(coll.name)
            if lc is not None:
                lc.exclude = True
    return coll


def layers(scene):
    r = root(scene)
    return [c for c in r.children if c.allset_layer.is_layer] if r else []


def display_order(scene):
    """Layers top to bottom as Maya lists them: highest ``order`` (newest) first."""
    ls = layers(scene)
    return sorted(ls, key=lambda c: (-c.allset_layer.order, -ls.index(c)))


def move_layer(scene, coll, delta):
    """Move ``coll`` ``delta`` rows down the list (-1 = up)."""
    seq = display_order(scene)
    i = seq.index(coll)
    j = max(0, min(len(seq) - 1, i + delta))
    if i == j:
        return False
    seq.insert(j, seq.pop(i))
    for n, c in enumerate(reversed(seq)):
        c.allset_layer.order = n + 1
    return True


def layer_of(ob, scene):
    for coll in layers(scene):
        if ob.name in coll.objects:
            return coll
    return None


def next_layer_name():
    """Maya ``layer<N>``: one past the highest, gaps not filled."""
    return f"layer{naming.next_number('layer', {c.name for c in bpy.data.collections})}"


OWN = "allset_layer_own"   # the member's own display_type / hide_select while a layer overrides them
INHERITED = "allset_layer_inherited"   # TEMPLATE / REFERENCE an object takes from a layer above it


def _layer_hide(ob, hidden):
    """The layer's V / P: the view-layer flag, never the object's own visibility (hide_viewport)."""
    for vl in bpy.context.scene.view_layers if bpy.context.scene else ():
        try:
            if ob.hide_get(view_layer=vl) != hidden:
                ob.hide_set(hidden, view_layer=vl)
        except RuntimeError:   # not in this view layer
            pass


def _override_display(ob, display_type, unselectable):
    if OWN not in ob:
        ob[OWN] = {"display_type": ob.display_type, "hide_select": bool(ob.hide_select)}
    if ob.display_type != display_type:
        ob.display_type = display_type
    if ob.hide_select != unselectable:
        ob.hide_select = unselectable


def _restore_display(ob):
    own = ob.get(OWN)
    if own is None:
        return
    ob.display_type = own.get("display_type", 'TEXTURED')
    ob.hide_select = bool(own.get("hide_select", False))
    del ob[OWN]


def display_kind(ob, scene):
    """TEMPLATE / REFERENCE of the object's own display layer, None for no layer or a Normal one."""
    coll = layer_of(ob, scene)
    kind = coll.allset_layer.display_type if coll is not None else "NORMAL"
    return None if kind == "NORMAL" else kind


def apply_display(ob, kind):
    """Template (wireframe, unselectable), Reference (unselectable) or, for None, the object's own display."""
    if kind is None:
        _restore_display(ob)
        return
    own = ob.get(OWN)
    own_type = own.get("display_type", ob.display_type) if own is not None else ob.display_type
    _override_display(ob, 'WIRE' if kind == "TEMPLATE" else own_type, True)


def apply_object(ob, layer):
    """Apply a layer's state to one member (None = back to the object's own state). Maya: a display layer is an
    override (drawOverride) that never changes the node's own attributes (#26). A Template / Reference from a layer
    above (``INHERITED``) wins over the member's own layer."""
    if layer is None:
        _layer_hide(ob, False)
        apply_display(ob, ob.get(INHERITED))
        return
    st = layer.allset_layer
    _layer_hide(ob, not st.visible)
    apply_display(ob, ob.get(INHERITED) or (None if st.display_type == "NORMAL" else st.display_type))


def apply_layer(coll):
    for ob in coll.objects:
        apply_object(ob, coll)
    layer_joints.bump()             # member joints and the joints below them (kit drawing / picking)
    from ..operators import dag
    dag.sync()                      # a hidden layer hides its members' children too (Maya)


def selected_nodes(context):
    """The selection as Maya nodes for a display layer: (objects, {skeleton: [joint names]}, skeletons picked as a
    whole). A joint picked in a view is a node (Pose Mode, or Edit Mode with the Move tool; in Object Mode the joints
    still picked on a skeleton selected with other objects). A kit skeleton picked as a whole stands for its root
    joints (Maya's top node of a skeleton is its root joint); another skeleton (a Rigify rig) is an object."""
    from ..operators import joint_selection
    from . import outliner_tree
    from .channel_box import bone_selected
    objects, joints, whole = [], {}, []
    for ob in context.selected_objects:
        if ob.type != 'ARMATURE' or ob.pose is None:
            objects.append(ob)
            continue
        pbs = ob.pose.bones
        if ob.mode == 'EDIT':
            names = [eb.name for eb in joint_selection._edit_picked(ob) if eb.name in pbs]
        else:
            names = [pb.name for pb in pbs if bone_selected(pb) and not compat.bone_hidden(pb)
                     and not joint_selection._collection_hidden(pb.bone)]
        if not names and ob.mode != 'EDIT':
            bones = outliner_tree._Bones(ob)
            if outliner_tree.is_kit_skeleton(ob, bones):
                names = [n for n in bones.roots if n in pbs]
                whole.append(ob)
        if names:
            joints[ob] = names
        else:
            objects.append(ob)
    return objects, joints, whole


def add_nodes(scene, coll, objects=(), joints=None, whole=()):
    """``add_objects`` for the objects; the joints move into ``coll`` (from any other layer). A kit skeleton picked
    as a whole is its root joints: an older file's layer holding the skeleton object lets it go."""
    add_objects(scene, coll, objects)
    for ob in whole if joints else ():
        old = layer_of(ob, scene)
        if old is not None:
            old.objects.unlink(ob)
            apply_object(ob, None)
    for ob, names in (joints or {}).items():
        for n in names:
            pb = ob.pose.bones.get(n)
            if pb is not None:
                layer_joints.set_layer(pb, coll)
    _members_changed()


def remove_nodes(scene, coll, objects=(), joints=None, whole=()):
    """``remove_objects`` for the objects; the joints of ``coll`` leave it (a skeleton picked as a whole: its root
    joints, and the skeleton object when an older file's layer holds it)."""
    remove_objects(scene, coll, [*objects, *(ob for ob in whole if ob.name in coll.objects)])
    for ob, names in (joints or {}).items():
        for n in names:
            pb = ob.pose.bones.get(n)
            if pb is not None and layer_joints.layer_of(pb) == coll:
                layer_joints.set_layer(pb, None)
    _members_changed()


def _members_changed():
    layer_joints.bump()
    from ..operators import dag
    dag.sync()                      # what is below the members follows them (Maya)


def new_layer(scene, objects=(), joints=None, whole=()):
    top = max((c.allset_layer.order for c in layers(scene)), default=0)
    coll = bpy.data.collections.new(next_layer_name())
    root(scene, create=True).children.link(coll)
    coll.allset_layer.is_layer = True
    coll.allset_layer.order = top + 1
    add_nodes(scene, coll, objects, joints, whole)
    return coll


def add_objects(scene, coll, objects):
    for ob in objects:
        old = layer_of(ob, scene)
        if old is not None and old != coll:
            old.objects.unlink(ob)
        if ob.name not in coll.objects:
            coll.objects.link(ob)
        apply_object(ob, coll)


def remove_objects(scene, coll, objects):
    for ob in objects:
        if ob.name in coll.objects:
            coll.objects.unlink(ob)
            apply_object(ob, None)


def empty_layer(scene, coll):
    remove_objects(scene, coll, list(coll.objects))
    remove_nodes(scene, coll, joints=layer_joints.members(coll, scene))


def delete_layer(scene, coll):
    empty_layer(scene, coll)
    bpy.data.collections.remove(coll)


def active_layer(context):
    ls = layers(context.scene)
    i = context.scene.allset_layer_index
    return ls[i] if 0 <= i < len(ls) else None


# --- playback (P) -------------------------------------------------------------------------------

_hidden_for_playback = []


@persistent
def on_playback_pre(scene, *_args):
    _hidden_for_playback.clear()
    joints = False
    for coll in layers(scene):
        st = coll.allset_layer
        if st.visible and not st.playback:
            for ob in coll.objects:
                _layer_hide(ob, True)
                _hidden_for_playback.append(ob.name)
            joints = joints or bool(layer_joints.members(coll, scene))
    layer_joints.set_playing(True)  # member joints of a layer with Playback off: hidden while playing
    if joints:
        _playback_dag(scene)


@persistent
def on_playback_post(scene, *_args):
    for name in _hidden_for_playback:
        ob = bpy.data.objects.get(name)
        if ob is not None:
            _layer_hide(ob, False)
    _hidden_for_playback.clear()
    layer_joints.set_playing(False)
    if layer_joints.has_members(scene):
        _playback_dag(scene)


def _playback_dag(scene):
    """Objects under joints of a layer with Playback off follow them."""
    from ..operators import dag
    try:
        dag.sync(scene)
    except (ReferenceError, RuntimeError, AttributeError):
        pass
