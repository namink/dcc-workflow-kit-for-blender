# SPDX-License-Identifier: GPL-3.0-or-later
"""What a kit skin is (Maya's skinCluster): the mesh's Armature modifier with a skeleton (``armature_modifier`` /
``armature_modifiers``, the Weight Blended half left out), its joint influences (``influences``, ``skinned_mesh``),
the normalize mode kept on the mesh (``NORMALIZE_PROP``, ``normalize_mode``) and the skeleton's joint colours
(``colorize``). Shared by ik_handle, skin_bind, paint_skin_weights and skin_copy_mirror; ``skin`` re-exports it.
"""


def _cb():
    from ..ui import channel_box
    return channel_box


def _skin_part(m):
    from .skin_method import is_part     # Weight Blended's DQ half is part of the skin, not a second one
    return is_part(m)


def armature_modifier(mesh):
    return next((m for m in mesh.modifiers if m.type == 'ARMATURE' and m.object is not None and not _skin_part(m)),
                None)


def armature_modifiers(mesh):
    """Every skin (Armature modifier with a skeleton) of a mesh, stack order = Maya's skinCluster chain from the
    first bound (the kit makes one, a received file may hold more — shown read-only)."""
    return [m for m in getattr(mesh, "modifiers", ()) if m.type == 'ARMATURE' and m.object is not None
            and not _skin_part(m)]


def is_weight_sum(m):
    from .skin_normalize_weights import is_part     # Normalize Weights Disable / Enable: part of the skin
    return is_part(m)


def off_the_cage(m):
    """A skin modifier (Armature with a skeleton, or its weight sum) not shown on the posed edit cage."""
    return (((m.type == 'ARMATURE' and m.object is not None) or is_weight_sum(m))
            and not (m.show_in_editmode and m.show_on_cage))


def show_pose_in_components(mesh):
    """Maya draws a skinned mesh's components on the posed mesh: the skin's Armature modifiers (and the weight sum
    after them) stay on in edit mode, on the edit cage (component selection and edits on the posed vertices)."""
    for m in getattr(mesh, "modifiers", ()):
        if off_the_cage(m):
            m.show_in_editmode = True
            m.show_on_cage = True


# Maya Bind Skin options the kit honours: Normalize weights is kept on the
# mesh (Interactive = Blender's Auto Normalize while painting), Colorize skeleton = a bone colour per joint
# (Unbind Skin's "Remove joint colors" takes them away), Remove unused influences = drop joints that weigh nothing.
NORMALIZE_PROP = "allset_normalize"
NORMALIZE = (("NONE", "None", "Weights are left as painted"),
             ("INTERACTIVE", "Interactive", "Painting a joint takes weight from the others (Blender Auto Normalize)"),
             ("POST", "Post", "Weights are normalised when the skin is used, not while painting"))
JOINT_COLORS = tuple(f"THEME{i:02d}" for i in range(1, 16))


def colorize(arm, on=True):
    """Maya Colorize skeleton: each joint its own colour (Blender bone colour palettes), or back to none."""
    for i, bone in enumerate(arm.data.bones):
        bone.color.palette = JOINT_COLORS[i % len(JOINT_COLORS)] if on else 'DEFAULT'


def normalize_mode(mesh):
    return mesh.get(NORMALIZE_PROP, "INTERACTIVE")


def skinned_mesh(context):
    ob = context.active_object
    if ob is not None and ob.type == 'MESH' and armature_modifier(ob):
        return ob
    return next((o for o in context.selected_objects if o.type == 'MESH' and armature_modifier(o)), None)


def influences(mesh, mod=None):
    """Vertex groups that are joints of the mesh's skeleton (Maya: the skinCluster influences); ``mod`` = one skin."""
    mod = mod or armature_modifier(mesh)
    if mod is None:
        return []
    bones = {b.name for b in mod.object.data.bones}
    return [vg for vg in mesh.vertex_groups if vg.name in bones]


PAINT_SEEN = "allset_paint_seen"      # the mesh's skin was painted once (Maya: keep the picked influence)
