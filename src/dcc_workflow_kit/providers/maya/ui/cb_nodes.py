# SPDX-License-Identifier: GPL-3.0-or-later
"""Channel Box nodes: the objects or pose bones the Channel Box shows and edits (the lead first, then the other
selected nodes), and the scene facts kept between redraws.
Entry points: lead, targets, target_count, selected_bones, field_lead, component_mode.
Related: cb_values.py, channel_box.py."""

import bpy

from .. import compat


# --- nodes: objects or pose bones -------------------------------------------------
# A Maya joint is a pose bone. Pose bones carry the
# same RNA names as objects (location / rotation_euler / scale / lock_* / rotation_mode / ID
# properties); only their animation lives on the armature object (``pose.bones["n"].<path>``).

def is_bone(node):
    return isinstance(node, bpy.types.PoseBone)


def is_root_joint(node):
    """A joint without a parent joint: a Maya root joint (its parent is the world)."""
    return is_bone(node) and node.parent is None


def root_translate(pb):
    """Translate X / Y / Z of a root joint = its position (a root joint at (3, 2, 1) shows Translate
    3 / 2 / 1): rest head + pose offset, armature space, in the kit's Z-up axes
    like every object Translate (operators/joint_edit.joint_translate shows the same in Edit
    mode). Blender keeps a pose bone's offset in the bone's rest axes."""
    b = pb.bone
    return b.head_local + b.matrix_local.to_3x3().normalized() @ pb.location


def set_root_translate(pb, t):
    """Move root joint ``pb`` so ``root_translate`` reads ``t`` (Blender length)."""
    from mathutils import Vector
    b = pb.bone
    pb.location = b.matrix_local.to_3x3().normalized().transposed() @ (Vector(t) - b.head_local)


def bone_selected(pb):
    return pb.select                    # 5.x: the selection is on the pose bone (Bone.select is gone)


def set_bone_selected(pb, state):
    pb.select = state


def active_object(context=None):
    """``context.active_object``, else the view layer's: a depsgraph handler running while a File Browser or
    Preferences window has the context gets no ``active_object`` member."""
    context = context or bpy.context
    if hasattr(context, "active_object"):
        return context.active_object
    view_layer = getattr(context, "view_layer", None)
    return view_layer.objects.active if view_layer is not None else None


def pose_armature(context=None):
    """The active armature when it is in pose mode (= Maya: joints are being picked)."""
    ob = active_object(context)
    return ob if ob is not None and ob.type == 'ARMATURE' and ob.mode == 'POSE' else None


def placing_joints(context=None):
    ob = active_object(context)
    return ob is not None and ob.type == 'ARMATURE' and ob.mode == 'EDIT'


# --- scene facts kept between redraws -------------------------------------------------------------------------------
# The Channel Box asks who the lead is and what drives it many times per redraw (every value field's getter, the
# rename button's poll, the "+N" count, the 10 Hz value watch), so the two answers that need a walk over every object
# of the scene are kept: which objects are skeletons, and which kit deformers a handle drives. The skeletons are found
# again when objects may have come or gone (``outliner.objects_version``), the deformers after any depsgraph update
# that is not a pure move (adding, removing or linking objects and every modifier edit send the Scene in the update),
# an undo / redo and a file load (``_generation``). A kept answer is checked on use: Blender
# hands out one Python object per ID and makes it raise ReferenceError once the ID is removed, and a kept modifier is
# looked up by name on its object again (``bpy.data.objects.get`` would walk the whole list).

_generation = [0]

_skeletons = {}     # view layer pointer -> (objects version, its armature objects in its object order)


def layer_armatures(view_layer):
    """The armature objects of ``view_layer`` in its object order (an object never changes its type). Kept until
    objects may have come or gone (``outliner.objects_version``: a selection, a rename or a move keeps the list)."""
    from .outliner import objects_version
    version = objects_version()
    vkey = view_layer.as_pointer()
    got = _skeletons.get(vkey)
    if got is not None and got[0] == version:
        try:
            for ob in got[1]:
                ob.as_pointer()
            return list(got[1])
        except ReferenceError:
            pass
    obs = [o for o in view_layer.objects if o.type == 'ARMATURE']
    if len(_skeletons) > 8:
        _skeletons.clear()
    _skeletons[vkey] = (version, tuple(obs))
    return obs


def pose_objects(context=None):
    context = context or bpy.context
    arm = pose_armature(context)
    if arm is None:
        return []
    others = [o for o in layer_armatures(context.view_layer) if o is not arm and o.mode == 'POSE']
    return [arm] + others


def _picked(context):
    """(pose bones, indices of the picked shown ones) per posed armature. The flags are read in one call per
    armature: the Channel Box and the Time Slider ask on every redraw, a rig has hundreds of bones."""
    import numpy as np
    for arm in pose_objects(context):
        bones = arm.pose.bones
        n = len(bones)
        if not n:
            continue
        sel = np.zeros(n, dtype=bool)
        hide = np.zeros(n, dtype=bool)
        bones.foreach_get("select", sel)        # = bone_selected
        bones.foreach_get("hide", hide)         # = compat.bone_hidden
        yield bones, np.flatnonzero(sel & ~hide)


def selected_bones(context=None):
    """The picked, shown pose bones of the posed armatures (armature order, then bone order)."""
    return [bones[int(i)] for bones, idx in _picked(context) for i in idx]


_drawing_lead = []     # [the lead] while the Channel Box draws (ALLSET_PT_channel_box.body)
# [dock region pointer, _generation, the lead] from the Channel Box's draw until that region has drawn: Blender reads
# every value field again after the panel's draw returns (it ends and draws the block), each read asking for the lead
_field_lead = []
# channel key -> the text of its value field, for the reads of one Channel Box draw (the same span as the lead above:
# Blender reads each field two or three times per redraw, and nothing can change a value while a region draws)
_field_texts = {}


def _in_draw():
    """True inside the span of one Channel Box draw (``field_lead``'s draw-time lead)."""
    if _drawing_lead:
        return True
    if _field_lead and _field_lead[1] == _generation[0]:
        region = getattr(bpy.context, "region", None)
        return region is not None and region.as_pointer() == _field_lead[0]
    return False


def field_lead():
    """The lead for a Channel Box value field's getter. During the dock region's draw it is the one the Channel Box
    found when it drew (the selection can't change while a region draws); any other caller (Python, an operator,
    another region, after a scene change) finds it again."""
    if _drawing_lead:
        return _drawing_lead[0]
    if _in_draw():
        return _field_lead[2]
    return lead()


def _end_field_reads():
    _field_lead.clear()
    _field_texts.clear()


def region_drawn():
    """A Properties region finished drawing (ui/maya_dock.py's POST_PIXEL callback): the draw-time lead ends."""
    _end_field_reads()


def lead(context=None):
    """The Maya lead: the active object, or in pose mode the active (selected) pose bone."""
    if context is None and _drawing_lead:
        return _drawing_lead[0]
    context = context or bpy.context
    arm = pose_armature(context)
    if arm is None:
        return active_object(context)
    act = arm.data.bones.active
    pb = arm.pose.bones.get(act.name) if act is not None else None
    if pb is not None and bone_selected(pb) and not compat.bone_hidden(pb):
        return pb
    # = selected_bones(context)[0], without a Python object for every picked bone
    for bones, idx in _picked(context):
        if len(idx):
            return bones[int(idx[0])]
    return None


def targets(context=None):
    """Lead + selected objects / pose bones (lead first), like Maya's selection list."""
    context = context or bpy.context
    nodes = selected_bones(context) if pose_armature(context) else list(context.selected_objects)
    ld = lead(context)
    if ld is not None:
        nodes = [ld] + [n for n in nodes if n != ld]
    return nodes


def target_count(context=None):
    """``len(targets(context))`` without building the list (the Channel Box's "+N" on every redraw). In Pose Mode
    the lead is one of the picked bones; an active object that isn't selected is a target too."""
    context = context or bpy.context
    if pose_armature(context):
        return sum(len(idx) for _bones, idx in _picked(context))
    obs = context.selected_objects
    ld = lead(context)
    return len(obs) + int(ld is not None and ld not in obs)


def full_path(node, path):
    """Animation data path of ``path`` on the node's ID (the armature object for a bone)."""
    if not is_bone(node):
        return path
    return None if path == "hide_viewport" else node.path_from_id(path)   # bone visibility: Bone.hide


COMPONENT_TYPES = {'MESH', 'CURVE', 'SURFACE', 'LATTICE'}


def component_mode(ob):
    """Maya component mode on the lead: a mesh / curve / surface / lattice object in edit mode (armature edit mode is
    joint placement, PLACING_TEXT)."""
    return ob is not None and not is_bone(ob) and ob.type in COMPONENT_TYPES and ob.mode == 'EDIT'
