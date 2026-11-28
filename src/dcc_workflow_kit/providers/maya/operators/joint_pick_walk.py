# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya pick walk on joints (arrow keys, ``allset.pick_walk_joint``): ``walk_bone`` follows controller tags where they
are set, else (preference) a Rigify rig's ORG hierarchy or the bones shown by their bone collections, else the plain
hierarchy; siblings in Maya child order, wrapping at the ends. Controller tag names ``CONTROLLER`` /
``CONTROLLER_PARENT`` (operators/controllers.py); ``joints`` re-exports these names.
"""

import re

import bpy
from bpy.props import EnumProperty

from .. import undo_steps
from .joint_common import _cb, child_order_key


# Maya's pick walk walks the DAG and
# goes into hidden nodes; with controller tags it follows the controller
# hierarchy. Kit controller tags live on data Bones (operators/controllers.py). An untagged armature treats
# bones whose bone collections are all hidden as "not a control" and walks past them (preference
# pick_walk_skip_hidden_collections; Maya walks into hidden display layers — kit difference). Bones
# hidden one by one (h) are walked into like Maya.
CONTROLLER = "allset_controller"
CONTROLLER_PARENT = "allset_controller_parent"


def _by_name(bones):
    """Siblings in Maya child order (the name is historical: it used to sort by name)."""
    return sorted(bones, key=child_order_key)


def _wrap(sibs, bone, direction):
    names = [b.name for b in sibs]
    if len(sibs) < 2 or bone.name not in names:
        return bone
    return sibs[(names.index(bone.name) + (1 if direction == "RIGHT" else -1)) % len(sibs)]


def collection_hidden(bone):
    """The bone is in bone collections and none of them is shown (a bone in no collection is always shown)."""
    cols = bone.collections
    return len(cols) > 0 and not any(c.is_visible_effectively for c in cols)


def has_controllers(arm):
    """The armature data has kit controller tags (Control > Tag As Controller / Parent Controller)."""
    return any(b.get(CONTROLLER) for b in arm.bones)


def controller_parent(bone):
    name = bone.get(CONTROLLER_PARENT)
    return bone.id_data.bones.get(name) if name else None


def controller_children(bone):
    return _by_name(b for b in bone.id_data.bones if b.get(CONTROLLER_PARENT) == bone.name)


def _dag_walk(bone, direction):
    if direction == "UP":
        return bone.parent or bone
    if direction == "DOWN":
        kids = _by_name(bone.children)
        return kids[0] if kids else bone
    sibs = bone.parent.children if bone.parent else [b for b in bone.id_data.bones if b.parent is None]
    return _wrap(_by_name(sibs), bone, direction)


def _controller_walk(bone, direction):
    """Maya's controller rule: the controller hierarchy where it is set, else the DAG."""
    up = controller_parent(bone)
    if direction == "UP":
        return up or bone.parent or bone
    if direction == "DOWN":
        kids = controller_children(bone)
        return kids[0] if kids else _dag_walk(bone, "DOWN")
    if up is not None:
        return _wrap(controller_children(up), bone, direction)
    return _dag_walk(bone, direction)


def visible_ancestor(bone):
    """Nearest ancestor not hidden by its bone collections, or None."""
    p = bone.parent
    while p is not None and collection_hidden(p):
        p = p.parent
    return p


def visible_below(bones):
    """Nearest descendants not hidden by collections under ``bones`` (depth-first, each level sorted by name)."""
    out = []
    for b in _by_name(bones):
        if collection_hidden(b):
            out.extend(visible_below(b.children))
        else:
            out.append(b)
    return out


def _visible_walk(bone, direction):
    if direction == "UP":
        return visible_ancestor(bone) or bone
    if direction == "DOWN":
        kids = visible_below(bone.children)
        return kids[0] if kids else bone
    up = visible_ancestor(bone)
    sibs = visible_below(up.children if up is not None
                         else [b for b in bone.id_data.bones if b.parent is None])
    if bone.name not in {b.name for b in sibs}:      # the bone itself is hidden by a collection
        return _dag_walk(bone, direction)
    return _wrap(sibs, bone, direction)


# Issue #145: in a Rigify rig 63 % of the controls hang on hidden MCH
# bones, so the nearest shown ancestor of upper_arm_fk.L is tweak_spine.003, not shoulder.L. The
# Rigify rule (ORG hierarchy projection): a generated rig (data property ``rig_id``) without kit tags gets
# controller parents computed from its ORG bones (never stored, so Tag / Parent Controller still win): control C ->
# its ORG twin (C's name without the variant word: upper_arm_fk.L -> ORG-upper_arm.L, tweak_spine.003 ->
# ORG-spine.003) -> up the ORG parents to the first one with a shown control twin, same variant first
# (upper_arm_fk.L -> shoulder.L, forearm_fk.L -> upper_arm_fk.L, tweak_spine.003 -> tweak_spine.002). Controls with no
# ORG twin (torso, chest, hand_ik.L ...) keep the shown-ancestor rule.
_VARIANTS = ("_fk", "_ik", "_tweak", "_master", "_parent")
_RIGIFY_MAPS = {}


def is_rigify_rig(arm):
    return bool(arm.get("rig_id")) and any(b.name.startswith("ORG-") for b in arm.bones)


_VARIANT_RE = re.compile(r"(_fk|_ik|_tweak|_master|_parent)(?=\.|$)")


def _split_variant(name):
    """(ORG base name, variant) of a Rigify control name: upper_arm_fk.L -> (upper_arm.L, '_fk'),
    f_index.01_master.L -> (f_index.01.L, '_master'), tweak_spine.003 -> (spine.003, 'tweak_')."""
    if name.startswith("tweak_"):
        return name[len("tweak_"):], "tweak_"
    m = _VARIANT_RE.search(name)
    if m is None:
        return name, ""
    return name[:m.start()] + name[m.end():], m.group(1)


def _with_variant(base, v):
    if v == "tweak_":
        return ["tweak_" + base]
    cuts = [i for i, ch in enumerate(base) if ch == "."] + [len(base)]
    return [base[:i] + v + base[i:] for i in cuts]


def _twin_names(base, variant):
    """Control names for ORG base ``base``: the same variant first, then the plain name, then the others."""
    out = _with_variant(base, variant) if variant else []
    out.append(base)
    for v in (*_VARIANTS, "tweak_"):
        if v != variant:
            out += _with_variant(base, v)
    return out


def rigify_parents(arm):
    """{control name: controller parent name or None} of a Rigify rig (shown controls only; cached per state)."""
    shown = {b.name for b in arm.bones if not collection_hidden(b) and not b.name.startswith(("ORG-", "MCH-", "DEF-"))}
    key = (hash(tuple(b.name for b in arm.bones)),
           tuple(sorted(c.name for c in arm.collections_all if c.is_visible_effectively)))
    got = _RIGIFY_MAPS.get(arm.name)
    if got is not None and got[0] == key:
        return got[1]
    bones = arm.bones
    out = {}
    for name in shown:
        base, variant = _split_variant(name)
        org = bones.get("ORG-" + base)
        parent = None
        p = org.parent if org is not None else None
        while p is not None and parent is None:
            if p.name.startswith("ORG-"):
                parent = next((n for n in _twin_names(p.name[4:], variant) if n in shown and n != name), None)
            p = p.parent
        if parent is None:
            up = visible_ancestor(bones[name])
            parent = up.name if up is not None else None
        out[name] = parent
    for name in list(out):                      # a loop (not expected) makes that control a root
        seen, cur = set(), name
        while cur is not None and cur not in seen:
            seen.add(cur)
            cur = out.get(cur)
        if cur is not None:
            out[name] = None
    _RIGIFY_MAPS[arm.name] = (key, out)
    return out


def _mapped_walk(bone, direction, parents):
    bones = bone.id_data.bones
    if bone.name not in parents:                    # a hidden helper selected by hand: plain DAG
        return _dag_walk(bone, direction)
    up = parents[bone.name]
    if direction == "UP":
        return bones[up] if up is not None else bone
    if direction == "DOWN":
        kids = _by_name(bones[n] for n, p in parents.items() if p == bone.name)
        return kids[0] if kids else bone
    sibs = _by_name(bones[n] for n, p in parents.items() if p == up)
    return _wrap(sibs, bone, direction)


def walk_bone(bone, direction, skip_hidden=False):
    """Bone reached from ``bone`` (data Bone) by a Maya arrow key (Up / Down / Left / Right, siblings wrap).

    Controller-tagged armature = the controller rule; else ``skip_hidden`` (the preference) walks a Rigify rig's
    controls by its ORG hierarchy and other armatures past bones hidden by their bone collections; else
    the plain DAG (parent, first child by name, siblings by name)."""
    if has_controllers(bone.id_data):
        return _controller_walk(bone, direction)
    if skip_hidden and is_rigify_rig(bone.id_data):
        return _mapped_walk(bone, direction, rigify_parents(bone.id_data))
    if skip_hidden:
        return _visible_walk(bone, direction)
    return _dag_walk(bone, direction)


def _skip_hidden_pref(context):
    from .. import preferences
    try:
        return preferences.get(context).pick_walk_skip_hidden_collections
    except (KeyError, AttributeError):
        return True


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_pick_walk_joint(bpy.types.Operator):
    """Walk the joint selection through the skeleton (Maya arrow keys)"""
    bl_idname = "allset.pick_walk_joint"
    bl_label = "Pick Walk Joint"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=(("UP", "Up", ""), ("DOWN", "Down", ""), ("LEFT", "Left", ""),
                                   ("RIGHT", "Right", "")), name="Direction")

    @classmethod
    def poll(cls, context):
        return context.mode == 'POSE' and _cb().lead(context) is not None

    def execute(self, context):
        cb = _cb()
        lead = cb.lead(context)
        skip = _skip_hidden_pref(context)
        picked = []
        for pb in cb.targets(context):
            to = walk_bone(pb.bone, self.direction, skip)
            key = (pb.id_data.name, to.name)
            if key not in picked:
                picked.append(key)
        for arm in cb.pose_objects(context):
            for pb in arm.pose.bones:
                cb.set_bone_selected(pb, False)
        for arm_name, bone_name in picked:
            cb.set_bone_selected(bpy.data.objects[arm_name].pose.bones[bone_name], True)
        if lead is not None:
            lead.id_data.data.bones.active = walk_bone(lead.bone, self.direction, skip)
        return {'FINISHED'}
