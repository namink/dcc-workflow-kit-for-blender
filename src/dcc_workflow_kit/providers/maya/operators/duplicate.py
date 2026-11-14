# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Duplicate (Ctrl+D), Duplicate Special (Ctrl+Shift+D) and Duplicate with
Transform (Shift+D).

Duplicate Special's options start like Maya's (copy, 1 copy, grouped under the parent, translate / rotate 0,
scale 1). Edit > Duplicate Special runs with the saved options and no dialog (its option box sets them); like Maya
it has no Adjust Last Operation panel. Shift+D repeats the move between the last copy and its source. Maya
duplicates the whole subtree; names count up (``pCube1`` -> ``pCube2``). On picked joints (Pose Mode, joint Edit
Mode) all three copy the joints with the joints below them (``joint_duplicate``).

What a copy takes from the original's inputs (#347), like Maya:

- Duplicate (Ctrl+D, Shift+D, Smart Duplicate, ``cmds.duplicate``): only the node itself. The copy's geometry is
  what the original shows now (shape-key mix, skin pose, deformers and modelling modifiers baked in); it has no
  history, deformers, shape keys, animation, drivers or constraints, and its channels keep their current values, so
  nothing the original's inputs do moves it. Materials, display settings (the smooth mesh preview) and children stay.
  Blender modifiers Maya has no match for: one switched off in the viewport stays on the copy as it is (not applied)
  unless it reads another object; Multires stays live with its sculpt detail (the shape-key mix, the deformers above
  it and the pose of the deformers after it that read another object, such as a skin, go into the base mesh, so the
  copy keeps the pose it shows; the other modifiers after it stay live). A Geometry Nodes modifier the user set up
  stays live with its inputs (values, attribute inputs, the objects it reads), and so do the modifiers after it; what
  comes before it is baked, so the node tree gets the same geometry. The kit's own node modifiers (Maya deformers such
  as the wire) are baked. A Subdiv Proxy copy is the cage only, like copying a Maya proxy cage.
- Duplicate Special > Duplicate input graph: the copy gets its own copies of the inputs (modifiers, shape keys,
  drivers, constraints, its creation node and copies of the animation, so it animates on its own).
- Duplicate Special > Duplicate input connections: the copy shares the original's inputs (the same animation drives
  both).
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty, IntProperty
from mathutils import Euler, Quaternion, Vector

from .. import results, undo_steps
from . import naming, prim_history
from .freeze import hierarchy
from .group import make_group

# Last duplicates made by this module: {copy name: source name} (smart transform).
PAIRS = {}

# What a copy takes from the original's inputs (see the module docstring)
PLAIN, INPUT_GRAPH, INPUT_CONNECTIONS = 'PLAIN', 'INPUT_GRAPH', 'INPUT_CONNECTIONS'
# Object types whose points take a shape-key mix and deforming modifiers in place (meshes get a baked mesh)
_POINT_TYPES = {'CURVE', 'SURFACE', 'LATTICE'}


def selected_roots(objects):
    chosen = set(objects)
    out = []
    for ob in objects:
        p = ob.parent
        while p is not None and p not in chosen:
            p = p.parent
        if p is None:
            out.append(ob)
    return out


def copy_subtree(root, instance=False, inputs=PLAIN):
    """Copy ``root`` and its descendants (data copied, or shared for an instance). ``inputs``: what the copies take
    from the originals' inputs (``PLAIN``, ``INPUT_GRAPH``, ``INPUT_CONNECTIONS``; an instance shares its data)."""
    new_of = {}
    for ob in hierarchy([root]):
        new = ob.copy()
        if ob.data is not None and not instance:
            new.data = ob.data.copy()
        if not instance and inputs != INPUT_GRAPH:   # no polyCube1 on pCube2: the creation node is an input
            _drop_creation_node(new)
        for coll in ob.users_collection:
            coll.objects.link(new)
        if ob is not root:
            new.parent = new_of[ob.parent]   # matrix_parent_inverse copied with the object
        naming.apply_maya_name(new, naming.base_name(ob.name), rename_data=not instance)
        new_of[ob] = new
    if not instance:
        copies = list(new_of.values())          # parents first
        if inputs == INPUT_GRAPH:
            _own_inputs(copies)
        elif inputs == PLAIN:
            _plain(bpy.context, copies)
    return new_of[root]


def _drop_creation_node(new):
    for idb in (new, new.data):
        for key in (prim_history.KEY, prim_history.PART):
            if idb is not None and key in idb:
                del idb[key]


# --- Duplicate input graph: the copy's own inputs ------------------------------------------------------------

def _anim_ids(ob):
    """The copy's own IDs that can carry animation: the object, its data and the data's shape keys."""
    out = [ob]
    if ob.data is not None:
        out.append(ob.data)
        keys = getattr(ob.data, "shape_keys", None)
        if keys is not None:
            out.append(keys)
    return out


def _own_action(action, made):
    """One copy of ``action`` per duplicate (IDs that shared it share the copy, each with its own slot)."""
    if action not in made:
        made[action] = action.copy()
    return made[action]


def _set_action(holder, action, made):
    """Give ``holder`` (animation data or an NLA strip) a copy of ``action`` on the slot of the same name."""
    slot = getattr(holder, "action_slot", None)
    ident = slot.identifier if slot is not None else None
    holder.action = _own_action(action, made)
    if ident is not None and hasattr(holder, "action_slot"):
        new_slot = next((s for s in holder.action.slots if s.identifier == ident), None)
        if new_slot is not None and holder.action_slot != new_slot:
            holder.action_slot = new_slot


def _own_inputs(copies):
    """Duplicate input graph: the copies keep their modifiers, shape keys, drivers and constraints (Blender copies
    them with the object and data) and get copies of the animation, so they animate on their own; a creation node
    (polyCube1) becomes the copy's own (polyCube2)."""
    made = {}
    for new in copies:
        for idb in _anim_ids(new):
            ad = idb.animation_data
            if ad is None:
                continue
            if ad.action is not None:
                _set_action(ad, ad.action, made)
            for track in ad.nla_tracks:
                for strip in track.strips:
                    if strip.action is not None:
                        _set_action(strip, strip.action, made)
        owner = prim_history.owner_of(new)
        if owner is not None and prim_history.KEY in owner and owner in (new, new.data):
            node = owner[prim_history.KEY]
            node["name"] = prim_history._next_name(node["type"])


# --- Duplicate: the node itself ----------------------------------------------------------------------------

def _history_records(new):
    """Kit records that rebuild a shape from its inputs (modelling history, a loft's curves): not on a plain copy."""
    from . import model_history, surfaces_maya
    if surfaces_maya.LOFT_KEY in new:
        del new[surfaces_maya.LOFT_KEY]
    if new.type == 'MESH':
        for key in (model_history.KEY, model_history.BASE):
            if key in new.data:
                del new.data[key]


KEEP, DROP, BAKE = 'KEEP', 'DROP', 'BAKE'     # what a plain copy does with a modifier (_plan)
# Modifiers that only move points (they keep the points and faces): after Multires, the ones that read another
# object (a skin, a lattice, a hook) can pose the base mesh under the sculpt instead
_DEFORM_ONLY = {'ARMATURE', 'CAST', 'CORRECTIVE_SMOOTH', 'CURVE', 'DISPLACE', 'HOOK', 'LAPLACIANDEFORM',
                'LAPLACIANSMOOTH', 'LATTICE', 'MESH_CACHE', 'MESH_DEFORM', 'SHRINKWRAP', 'SIMPLE_DEFORM', 'SMOOTH',
                'SURFACE_DEFORM', 'WARP', 'WAVE'}


def _reads_other(md):
    """The modifier reads another object or collection: an Armature's skeleton, a Hook's handle, a Boolean's cutter,
    a mirror object, an object input of Geometry Nodes ..."""
    ids = (bpy.types.Object, bpy.types.Collection)

    def points(struct):
        for prop in struct.bl_rna.properties:
            if prop.type == 'POINTER' and isinstance(getattr(struct, prop.identifier, None), ids):
                return True
        return False

    if points(md):
        return True
    for prop in md.bl_rna.properties:             # UV Project's projectors
        if prop.type == 'COLLECTION' and any(points(item) for item in getattr(md, prop.identifier, ())):
            return True
    if md.type == 'NODES' and md.node_group is not None:
        from .. import compat
        for item in md.node_group.interface.items_tree:
            if (getattr(item, "in_out", None) == 'INPUT'
                    and getattr(item, "socket_type", "") in {'NodeSocketObject', 'NodeSocketCollection'}
                    and compat.gn_input_get(md, item.identifier) is not None):
                return True
    return False


def _user_nodes(md):
    """A Geometry Nodes modifier the user set up: a node group that isn't one of the kit's own (the kit's node
    groups, for Maya deformers and display, have names starting with ".Allset")."""
    return (md.type == 'NODES' and md.node_group is not None
            and not md.node_group.name.lower().startswith(".allset"))


def _live_from(new):
    """Index of the first user Geometry Nodes modifier shown in the viewport (len of the stack when none): it and
    the modifiers after it stay live on a plain copy."""
    mods = list(new.modifiers)
    return next((i for i, md in enumerate(mods) if md.show_viewport and _user_nodes(md)), len(mods))


def _plan(new):
    """What a plain copy does with each of its modifiers, by name:

    - KEEP: the kit's display modifiers; one switched off in the viewport (not applied, Maya has no such thing).
    - DROP: one switched off that reads another object (a plain copy has no connections); Subdiv Proxy's Subsurf
      (Maya's smooth side is an object of its own, so the copy is the cage).
    - BAKE: the rest, what the view shows (Maya's history and deformers).

    Multires keeps its sculpt detail only on the base mesh it was made on, so a mesh with Multires keeps Multires and
    every modifier after it live, except a deformer that reads another object: its pose goes into the base (BAKE,
    acting on the base mesh) and it goes; another modifier after it that reads another object goes too. The ones
    above Multires don't change the base's points and faces (Blender's rule) and bake into the base.

    A Geometry Nodes modifier the user set up (Maya has no such thing) is a procedural setup that baking would lose:
    it stays live with its inputs (values, attribute inputs, the objects it reads), switched off or not. The first
    one shown in the viewport and every modifier after it stay live (KEEP); the ones before it bake, so the node tree
    gets the same geometry as on the original. The kit's own node modifiers (Maya deformers) bake like the others."""
    from .display import is_preview
    from .global_keys4 import subdiv_proxy
    proxy = subdiv_proxy(new) if new.type == 'MESH' else None
    live = _live_from(new)
    out = {}
    for i, md in enumerate(new.modifiers):
        if is_preview(md):
            out[md.name] = KEEP
        elif proxy is not None and md.name == proxy.name:
            out[md.name] = DROP
        elif not md.show_viewport:
            out[md.name] = KEEP if _user_nodes(md) or not _reads_other(md) else DROP
        elif i >= live:
            out[md.name] = KEEP
        else:
            out[md.name] = BAKE
    first = _multires_index(new)
    if first is not None:
        for md in list(new.modifiers)[first:live]:
            if out[md.name] == BAKE and not (md.type in _DEFORM_ONLY and _reads_other(md)):
                out[md.name] = DROP if _reads_other(md) else KEEP
    return out


def _multires_index(new):
    if new.type != 'MESH':
        return None
    return next((i for i, md in enumerate(new.modifiers) if md.type == 'MULTIRES'), None)


def _remove(new, names):
    for name in names:
        md = new.modifiers.get(name)
        if md is not None:
            new.modifiers.remove(md)


def _needs_evaluation(new):
    if new.constraints:
        return True
    if new.type == 'MESH' or new.type in _POINT_TYPES:
        return BAKE in _plan(new).values() or getattr(new.data, "shape_keys", None) is not None
    if new.type == 'ARMATURE' and new.pose is not None:
        return any(pb.constraints for pb in new.pose.bones)
    return False


def _bake_mesh(context, new):
    """The copy's mesh = what it shows now without the modifiers it keeps or drops (_plan); the follow of its skin
    goes into the points (its channels stay), like Delete History."""
    from . import history, skin_follow
    from .global_keys4 import forget_proxy
    plan = _plan(new)
    bake = [name for name, what in plan.items() if what == BAKE]
    drop = [name for name, what in plan.items() if what == DROP]
    keys = new.data.shape_keys is not None
    if _multires_index(new) is not None:
        if bake or keys:
            _bake_base(context, new, bake)
    elif bake or keys:
        history._bake(context, new, keep={name for name, what in plan.items() if what != BAKE})
    _remove(new, drop)
    skin_follow.detach(new, keep_shape=True)
    forget_proxy(new)


def _bake_base(context, new, bake):
    """Multires: the shape-key mix, the modifiers above Multires and the posing deformers after it (``bake``) act on
    the base mesh alone; their result goes into its points, so the sculpt detail stays valid on top of them."""
    later = [md for md in list(new.modifiers)[_multires_index(new):] if md.name not in bake]
    shown = {md.name: md.show_viewport for md in later}
    for md in later:
        md.show_viewport = False
    try:
        base = new.evaluated_get(context.evaluated_depsgraph_get()).data
        same = (len(base.vertices), len(base.loops)) == (len(new.data.vertices), len(new.data.loops))
        co = [0.0] * (3 * len(base.vertices))
        base.vertices.foreach_get("co", co)
    finally:
        for name, show in shown.items():
            new.modifiers[name].show_viewport = show
    if not same:         # only when a modifier above Multires changes the faces: no pose, and no connections
        _remove(new, [name for name in bake if _reads_other(new.modifiers[name])])
        return
    if new.data.shape_keys is not None:
        new.shape_key_clear()
    new.data.vertices.foreach_set("co", co)
    new.data.update()
    _remove(new, bake)


def _bake_points(context, new):
    """Curves, surfaces and lattices: the shape-key mix and the deforming modifiers go into the points (a modifier
    that builds new geometry can't be applied to them and stays); switched-off modifiers as in _plan."""
    plan = _plan(new)
    with context.temp_override(object=new, active_object=new, selected_objects=[new],
                               selected_editable_objects=[new]):
        if getattr(new.data, "shape_keys", None) is not None:
            bpy.ops.object.shape_key_remove(all=True, apply_mix=True)
        for name, what in plan.items():
            if what == BAKE:
                try:
                    bpy.ops.object.modifier_apply(modifier=name)
                except RuntimeError:
                    pass
    _remove(new, [name for name, what in plan.items() if what == DROP])


def _hold_pose(context, arm):
    """An armature copy holds the pose its bone constraints give now in the bones' own channels (Maya's joints keep
    their values; IK handles and constraints are separate nodes), then loses the constraints."""
    pbs = [pb for pb in arm.pose.bones if pb.constraints]
    if not pbs:
        return
    ev = arm.evaluated_get(context.evaluated_depsgraph_get())
    basis = {pb.name: ev.convert_space(pose_bone=pb, matrix=pb.matrix, from_space='POSE', to_space='LOCAL')
             for pb in ev.pose.bones}
    for pb in arm.pose.bones:
        for con in list(pb.constraints):
            pb.constraints.remove(con)
        pb.matrix_basis = basis[pb.name]


def _hold_place(context, new):
    """The copy stays where its constraints put it now, without them."""
    if not new.constraints:
        return
    mw = new.evaluated_get(context.evaluated_depsgraph_get()).matrix_world.copy()
    new.constraints.clear()
    new.matrix_world = mw


class _evaluated:
    """While plain copies are made, the ones that need their evaluated result (``copies``) are evaluated like their
    originals (same inputs still). A copy the view layer leaves out (switched off in the viewport by Hide, in a
    collection switched off or excluded, in another scene's collection) is shown and linked into the scene's
    collection meanwhile, then put back: a hidden child's copy is made like a shown child's and stays hidden."""

    def __init__(self, context, copies):
        self.context, self.copies, self.shown, self.linked = context, copies, [], []

    def __enter__(self):
        if not self.copies:
            return self
        view_layer = self.context.view_layer
        view_layer.update()
        dg = self.context.evaluated_depsgraph_get()
        left_out = [new for new in self.copies if not new.evaluated_get(dg).is_evaluated]
        if left_out:
            coll = self.context.scene.collection
            for new in left_out:
                if new.hide_viewport:
                    new.hide_viewport = False
                    self.shown.append(new)
                if new.name not in coll.objects:
                    coll.objects.link(new)
                    self.linked.append(new)
            view_layer.update()
        return self

    def __exit__(self, *_exc):
        coll = self.context.scene.collection
        for new in self.linked:
            coll.objects.unlink(new)
        for new in self.shown:
            new.hide_viewport = True
        if self.shown or self.linked:
            self.context.view_layer.update()      # update handlers see the copies hidden again
        return False


def _plain(context, copies):
    """Maya Duplicate: each copy is the node itself, as the original shows now, with nothing that drives it."""
    with _evaluated(context, [new for new in copies if _needs_evaluation(new)]):
        for new in copies:                      # parents first
            if new.type == 'MESH':
                _bake_mesh(context, new)
            elif new.type in _POINT_TYPES:
                _bake_points(context, new)
            elif new.type == 'ARMATURE' and new.pose is not None:
                _hold_pose(context, new)
            _hold_place(context, new)
            for idb in _anim_ids(new):         # the channels keep the values they have now
                if idb.animation_data is not None:
                    idb.animation_data_clear()
            _drop_creation_node(new)           # also on a baked mesh
            _history_records(new)


def offset_channels(ob, k, translate, rotate, scale):
    """k-th copy: channels t + k*T, r + k*R, s * S^k (Maya cumulative offsets)."""
    ob.location = Vector(ob.location) + k * Vector(translate)
    q = Euler(tuple(k * a for a in rotate)).to_quaternion()
    if ob.rotation_mode == 'QUATERNION':
        ob.rotation_quaternion = q @ ob.rotation_quaternion
    elif ob.rotation_mode == 'AXIS_ANGLE':
        angle, *axis = ob.rotation_axis_angle
        axis, angle = (q @ Quaternion(axis, angle)).to_axis_angle()
        ob.rotation_axis_angle = (angle, *axis)
    else:
        ob.rotation_euler = tuple(a + k * b for a, b in zip(ob.rotation_euler, rotate))
    ob.scale = tuple(a * b ** k for a, b in zip(ob.scale, scale))


def _select(context, objects):
    for ob in context.selected_objects:
        ob.select_set(False)
    for ob in objects:
        ob.select_set(True)
    if objects:
        context.view_layer.objects.active = objects[-1]


def duplicate(context, instance=False):
    """Copy every selected root with its subtree in place, Maya names; returns the copies (Maya Duplicate: the
    geometry as it shows now, no inputs). Records source pairs so a following Shift+D repeats the move between them."""
    roots = selected_roots(context.selected_objects)
    made, pairs = [], {}
    for root in roots:
        new = copy_subtree(root, instance)
        made.append(new)
        pairs[new.name] = root.name
    PAIRS.clear()
    PAIRS.update(pairs)
    _select(context, made)
    return made


class ALLSET_OT_duplicate(bpy.types.Operator):
    """Duplicate the selection in place with its children: the geometry as it shows now, without history,
    deformers, shape keys or animation; copies are named the Maya way (pCube1 -> pCube2, pCubeShape2) and
    selected (Maya Edit > Duplicate, Ctrl+D)"""
    bl_idname = "allset.duplicate"
    bl_label = "Duplicate"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE', 'EDIT_ARMATURE'}

    def execute(self, context):
        if context.mode != 'OBJECT':
            from . import joint_duplicate          # picked joints (Pose Mode, joint Edit Mode)
            made = joint_duplicate.duplicate(context)
        else:
            made = duplicate(context)
        if not made:
            self.report({'WARNING'}, "Nothing selected")
            return {'CANCELLED'}
        return {'FINISHED'}


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_duplicate_special(bpy.types.Operator):
    """Duplicate with options: copies or instances, number of copies, offsets per
    copy, where to put them, the copies' own or shared inputs (Maya Edit > Duplicate Special)"""
    bl_idname = "allset.duplicate_special"
    bl_label = "Duplicate Special"
    bl_options = {'REGISTER', 'UNDO'}

    geometry_type: EnumProperty(
        name="Geometry Type",
        items=(('COPY', "Copy", "Copy the geometry"),
               ('INSTANCE', "Instance", "Share the geometry (Blender linked duplicate)")))
    group_under: EnumProperty(
        name="Group Under",
        items=(('PARENT', "Parent", "Same parent as the original"),
               ('WORLD', "World", "At the top of the hierarchy"),
               ('NEW_GROUP', "New Group", "Under a new group")))
    translate: FloatVectorProperty(name="Translate", subtype='TRANSLATION', unit='LENGTH')
    rotate: FloatVectorProperty(name="Rotate", subtype='EULER', unit='ROTATION')
    scale: FloatVectorProperty(name="Scale", default=(1.0, 1.0, 1.0), subtype='XYZ')
    copies: IntProperty(name="Number of Copies", default=1, min=1, soft_max=100, max=10000)
    input_graph: BoolProperty(
        name="Duplicate Input Graph",
        description="Each copy gets its own copies of the inputs: modifiers, shape keys, drivers, constraints and "
                    "its own animation. Offsets apply to plain copies only")
    input_connections: BoolProperty(
        name="Duplicate Input Connections",
        description="Each copy shares the original's inputs: the same animation drives both. Offsets apply to "
                    "plain copies only")

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE', 'EDIT_ARMATURE'}

    def execute(self, context):
        if context.mode != 'OBJECT':
            return self._joints(context)
        roots = selected_roots(context.selected_objects)
        if not roots:
            self.report({'WARNING'}, "Nothing selected")
            return {'CANCELLED'}
        instance = self.geometry_type == 'INSTANCE'
        inputs = (PLAIN if instance else INPUT_GRAPH if self.input_graph
                  else INPUT_CONNECTIONS if self.input_connections else PLAIN)
        made, pairs = [], {}
        for root in roots:
            for k in range(1, self.copies + 1):
                new = copy_subtree(root, instance, inputs)
                if inputs == PLAIN:       # Maya: no offsets for copies with their inputs
                    offset_channels(new, k, self.translate, self.rotate, self.scale)
                made.append(new)
                if self.copies == 1:
                    pairs[new.name] = root.name
        context.view_layer.update()
        if self.group_under == 'WORLD':
            from .parenting import unparent
            unparent(made)
        elif self.group_under == 'NEW_GROUP':
            grp = make_group(context, made)
            made = [grp]
        PAIRS.clear()
        PAIRS.update(pairs)
        _select(context, made)
        return {'FINISHED'}

    def _joints(self, context):
        """Picked joints (Pose Mode, joint Edit Mode): copies with the joints below them; a joint can't be an
        instance, a group can't hold a joint and a joint copy takes no inputs, so those copy plainly (and say so)."""
        from . import joint_duplicate
        notes = []
        if self.geometry_type == 'INSTANCE':
            notes.append("joints have no instances: copied")
        if self.group_under == 'NEW_GROUP':
            notes.append("a group can't hold joints: the copies stay under the parent")
        plain = not (self.input_graph or self.input_connections)
        if not plain:
            notes.append("joint copies take no inputs")
        under = joint_duplicate.WORLD if self.group_under == 'WORLD' else joint_duplicate.PARENT
        place = joint_duplicate.offsets_place(self.translate, self.rotate, self.scale, under) if plain else None
        made = joint_duplicate.duplicate(context, count=self.copies, place=place, under=under)
        if not made:
            self.report({'WARNING'}, "Nothing selected")
            return {'CANCELLED'}
        if notes:
            results.result(self, "Duplicate Special: " + "; ".join(notes))
        return {'FINISHED'}


class ALLSET_OT_duplicate_with_transform(bpy.types.Operator):
    """Duplicate and repeat the transform between the last duplicate and its source,
    so repeated use builds an array (Maya Edit > Duplicate with Transform, Shift+D)"""
    bl_idname = "allset.duplicate_with_transform"
    bl_label = "Duplicate with Transform"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE', 'EDIT_ARMATURE'}

    def execute(self, context):
        if context.mode != 'OBJECT':
            from . import joint_duplicate          # picked joints (Pose Mode, joint Edit Mode)
            if not joint_duplicate.duplicate_with_transform(context):
                self.report({'WARNING'}, "Nothing selected")
                return {'CANCELLED'}
            return {'FINISHED'}
        roots = selected_roots(context.selected_objects)
        if not roots:
            self.report({'WARNING'}, "Nothing selected")
            return {'CANCELLED'}
        context.view_layer.update()
        made, pairs = [], {}
        for ob in roots:
            src = bpy.data.objects.get(PAIRS.get(ob.name, ""))
            new = copy_subtree(ob)
            if src is not None and src is not ob:
                delta = ob.matrix_world @ src.matrix_world.inverted_safe()
                new.matrix_world = delta @ ob.matrix_world
            made.append(new)
            pairs[new.name] = ob.name
        PAIRS.clear()
        PAIRS.update(pairs)
        _select(context, made)
        return {'FINISHED'}


classes = (ALLSET_OT_duplicate, ALLSET_OT_duplicate_special, ALLSET_OT_duplicate_with_transform)
