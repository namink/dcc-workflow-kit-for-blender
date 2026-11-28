# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Ctrl+G group and Edit > Ungroup.

Edit > Group default options (under Parent, Preserve position, pivot at the origin)
creates the group under the common parent with its pivot at the origin; with
nothing selected it makes an empty group. Names are ``group1``, ``group2``, ...

Blender form: an Empty is the group transform. Children are parented the Maya
way: world transform kept, ``matrix_parent_inverse``
left at identity so the child's local values are relative to the group.
"""

from contextlib import nullcontext

import bpy
from mathutils import Matrix

from .. import results
from . import units


def hidden_groups(context):
    """Selected group transforms omitted by the viewport's Locators filter."""
    space = getattr(context, "space_data", None)
    if (space is None or space.type != 'VIEW_3D'
            or getattr(space, "show_object_viewport_empty", True)):
        return []
    selected = context.selected_objects
    groups = [ob for ob in context.view_layer.objects.selected if ob.type == 'EMPTY' and ob not in selected]
    if not groups:
        return []
    view_layer = context.view_layer
    with bpy.context.temp_override(area=None, region=None):
        groups = [ob for ob in groups if ob.visible_get(view_layer=view_layer)]
    return [ob for ob in groups if not space.local_view or ob.local_view_get(space)]


def selected_objects(context):
    return context.selected_objects + hidden_groups(context)


def selection_context(context):
    """Let transforms operate on groups without displaying their locator axes or selecting children."""
    groups = hidden_groups(context) if context.mode == 'OBJECT' else []
    if not groups:
        return nullcontext()
    return context.temp_override(selected_objects=context.selected_objects + groups,
                                 selected_editable_objects=list(context.selected_editable_objects) +
                                 [ob for ob in groups if ob.is_editable and not ob.hide_select])


class ALLSET_OT_group_transform(bpy.types.Operator):
    """Drag the selected group's transform with its locator axes hidden"""
    bl_idname = "allset.group_transform"
    bl_label = "Transform Group"
    bl_options = {'INTERNAL'}

    operation: bpy.props.EnumProperty(items=[(n, n.title(), "") for n in ('translate', 'rotate', 'trackball')])
    constraint_axis: bpy.props.BoolVectorProperty(size=3)
    orient_type: bpy.props.StringProperty(default='GLOBAL')
    orient_axis: bpy.props.EnumProperty(items=[(a, a, "") for a in 'XYZ'], default='Z')
    orient_matrix_type: bpy.props.StringProperty(default='GLOBAL')
    orient_matrix: bpy.props.FloatVectorProperty(size=(3, 3), subtype='MATRIX')
    release_confirm: bpy.props.BoolProperty(default=True)

    def invoke(self, context, _event):
        kwargs = {name: getattr(self, name) for name in self.properties.keys() if name != 'operation'}
        with selection_context(context):
            res = getattr(bpy.ops.transform, self.operation)('INVOKE_DEFAULT', **kwargs)
        return {'FINISHED'} if res & {'RUNNING_MODAL', 'FINISHED'} else {'CANCELLED'}


def next_group_name(names):
    """Maya's next ``groupN`` given existing object names: one past the highest (no gap filling)."""
    from . import naming
    return f"group{naming.next_number('group', set(names))}"


def common_parent(objects):
    parents = {ob.parent for ob in objects}
    return parents.pop() if len(parents) == 1 else None


def set_parent_keep_world(child, parent, frame=None):
    """Parent while keeping the world matrix; the parent inverse is ``frame`` (the parent's Maya frame,
    ``freeze.frame_inverse``) or the identity."""
    world = child.matrix_world.copy()
    child.parent = parent
    child.matrix_parent_inverse = Matrix.Identity(4) if frame is None else frame
    child.matrix_world = world


def scene_collections(view_layer):
    """The collections of ``view_layer`` that hold its objects: the scene collection and every collection below it
    that isn't excluded (a kit set or the Display Layers collections are not among them)."""
    out, stack = [], [view_layer.layer_collection]
    while stack:
        lc = stack.pop()
        if lc.exclude:
            continue
        out.append(lc.collection)
        stack.extend(reversed(list(lc.children)))
    return out


def group_collection(context, objects):
    """Where a new group goes: the collection its members share (the first member's order decides between several),
    else the active collection (Blender has collections, Maya doesn't: the group stays with its members)."""
    usable = scene_collections(context.view_layer)
    usable_set = set(usable)
    if objects:
        shared = set(objects[0].users_collection)
        for ob in objects[1:]:
            shared &= set(ob.users_collection)
        for coll in objects[0].users_collection:
            if coll in shared and coll in usable_set:
                return coll
    active = context.collection
    return active if active in usable_set else context.scene.collection


def make_group(context, objects):
    """Create a Maya-style group over ``objects``. Returns the new Empty."""
    objects = list(objects)
    parent = common_parent(objects) if objects else None
    collection = group_collection(context, objects)

    grp = bpy.data.objects.new(next_group_name(o.name for o in bpy.data.objects), None)
    grp.empty_display_type = 'PLAIN_AXES'
    # 1 Maya unit, like a Create locator
    grp.empty_display_size = units.maya_unit(context.scene)
    collection.objects.link(grp)
    if parent is not None:
        # Under the common parent with an identity local transform, so the
        # group pivot sits at the parent's origin (Maya zeroPivot).
        from .freeze import frame_inverse
        grp.parent = parent
        grp.matrix_parent_inverse = frame_inverse(parent)     # a frozen parent's frame, like Maya
    grp.matrix_basis = Matrix.Identity(4)
    context.view_layer.update()

    from . import skin_follow
    for ob in objects:
        if ob.type == 'ARMATURE':
            skin_follow.ensure(ob)      # its skin moves with the group (meshes bound before the kit's follow)
        set_parent_keep_world(ob, grp)
    return grp


def frame_inverse(ob):
    from .freeze import frame_inverse as frame
    return frame(ob)


def ungroup(context, groups, world=False, preserve=True):
    """Maya Edit > Ungroup (default Ungroup under Parent, Preserve position on): each group's
    children move under the group's parent (``world``: to the world; the world when it has none) keeping their world
    transform, then the group goes. Preserve position off keeps each child's local values instead, so the child
    moves by the group's transform (grp t 0 5 0, child t 1 2 3 -> child t 1 2 3 under the new parent).
    A selected object that has data of its own (a mesh with
    children) only loses its children. Returns the moved children; like Maya they are listed last among their new
    siblings, in the order they had in the group (Outliner order, ui/outliner_order.py)."""
    from ..ui import outliner_order
    scene = context.scene
    moved = []
    for grp in groups:
        if scene is not None:
            outliner_order.number_new(list(scene.objects))
        kids = sorted(grp.children, key=lambda o: o.get(outliner_order.ORDER, 0))
        target = None if world else grp.parent
        for child in kids:
            if not preserve:
                local = child.matrix_parent_inverse @ child.matrix_basis
                frame = frame_inverse(target) if target is not None else Matrix.Identity(4)
                child.parent = target
                child.matrix_parent_inverse = frame         # values in the new parent's frame, like Maya
                child.matrix_basis = frame.inverted_safe() @ local
            elif target is not None:
                set_parent_keep_world(child, target, frame_inverse(target))
            else:
                world_m = child.matrix_world.copy()
                child.parent = None
                child.matrix_world = world_m
        moved.extend(kids)
        if scene is not None and kids:
            outliner_order.to_end(kids, scene)
        if grp.type == 'EMPTY':
            bpy.data.objects.remove(grp)
    return moved


class ALLSET_OT_ungroup(bpy.types.Operator):
    """Move the children of the selected groups up one level and delete the groups (Maya Ungroup)"""
    bl_idname = "allset.ungroup"
    bl_label = "Ungroup"
    bl_options = {'REGISTER', 'UNDO'}

    under: bpy.props.EnumProperty(
        name="Ungroup Under", options={'SKIP_SAVE'},
        items=(('PARENT', "Parent", "Under the group's parent (Maya Ungroup Options, default)"),
               ('WORLD', "World", "At the top of the hierarchy")))
    preserve_position: bpy.props.BoolProperty(
        name="Preserve Position", default=True, options={'SKIP_SAVE'},
        description="Keep the children where they are (off = keep their local values)")

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(ob.children for ob in context.selected_objects)

    def execute(self, context):
        groups = [ob for ob in context.selected_objects if ob.children]
        # Innermost first, so nested selected groups hand their children up step by step.
        groups.sort(key=_depth, reverse=True)
        moved = ungroup(context, groups, self.under == 'WORLD', self.preserve_position)
        context.view_layer.update()
        for ob in moved:
            if ob.name in context.view_layer.objects:
                ob.select_set(True)
        if moved:
            context.view_layer.objects.active = moved[0]
        results.result(self, f"Ungrouped {len(groups)} group(s)")
        return {'FINISHED'}


def _depth(ob):
    n = 0
    while ob.parent is not None:
        ob, n = ob.parent, n + 1
    return n


# A joint inside a bone chain can't be given a group parent here (a bone's parent is another bone of its skeleton).
CHILD_JOINT_WARNING = ("Cannot group joint {name}: only the top (root) joints of a skeleton can go under a group. "
                       "Select the root joint to group the whole skeleton.")
SOME_ROOTS_WARNING = ("Cannot group joint {name} alone: its skeleton has other root joints ({others}) that would move "
                      "with it. Select every root joint of the skeleton.")


def joint_selection(context):
    """Selected joints as ``(skeletons, warning)``: the armature objects whose root joints are picked (pose mode,
    or skeleton edit mode), or a warning text when a picked joint can't be grouped on its own."""
    from . import joints
    skeletons = []
    for ob in context.view_layer.objects:
        if ob is None or ob.type != 'ARMATURE' or ob.mode not in {'POSE', 'EDIT'}:
            continue
        picked = joints.selected_joint_names(ob)
        if not picked:
            continue
        bones = ob.data.edit_bones if ob.mode == 'EDIT' else ob.data.bones
        for name in picked:
            bone = bones.get(name)
            if bone is not None and bone.parent is not None:
                return [], CHILD_JOINT_WARNING.format(name=name)
        roots = [b.name for b in bones if b.parent is None]
        others = [n for n in roots if n not in picked]
        if others:
            return [], SOME_ROOTS_WARNING.format(name=picked[0], others=", ".join(others))
        skeletons.append(ob)
    return skeletons, None


class ALLSET_OT_group(bpy.types.Operator):
    """Group the selected objects under a new transform (Maya Ctrl+G). With root joints selected their skeleton
    goes under the group"""
    bl_idname = "allset.group"
    bl_label = "Group"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE', 'EDIT_ARMATURE'} and context.view_layer is not None

    def execute(self, context):
        skeletons, in_mode = [], set()
        if context.mode != 'OBJECT':
            skeletons, warning = joint_selection(context)
            if warning:
                self.report({'WARNING'}, warning)
                return {'CANCELLED'}
            # a skeleton in pose / edit mode counts through its picked joints only
            in_mode = {ob for ob in context.view_layer.objects if ob is not None and ob.mode != 'OBJECT'}
            bpy.ops.object.mode_set(mode='OBJECT')      # Maya selects the new group (an object)
        objects = skeletons + [ob for ob in context.selected_objects if ob not in in_mode]
        grp = make_group(context, objects)
        for ob in context.selected_objects:
            ob.select_set(False)
        grp.select_set(True)
        context.view_layer.objects.active = grp
        results.result(self, f"Result: {grp.name}")       # Maya: "// Result: group1 //" (the group command's return)
        from ..ui import view_message
        # Maya Edit > Group: success, or an empty group with "select objects first".
        view_message.show(context, f"<hl>{grp.name}</hl> grouped." if objects else
                          f"Nothing selected: <hl>{grp.name}</hl> is empty. <hl>Select</hl> objects before grouping.")
        return {'FINISHED'}


classes = (ALLSET_OT_group, ALLSET_OT_ungroup, ALLSET_OT_group_transform)
