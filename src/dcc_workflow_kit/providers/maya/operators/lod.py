# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Edit > LOD (Level of Detail): Create LOD Group, Generate LOD Meshes, Ungroup LOD Group.

Like Maya 2026:

- Create LOD Group: a ``LOD_Group_<N>`` node with one ``LOD_<i>`` transform per selected top-level object (that
  object under it); no selection = 3 empty levels. A selected object with a parent is refused. The group is selected
  (after Generate LOD Meshes too).
- Generate LOD Meshes (the menu item: 1 level, 33.3% of the vertices removed): the selection goes under ``LOD_0`` of
  a new group (or the group it is already in), ``LOD_1`` gets reduced duplicates (with history).
- Ungroup LOD Group (the group or one of its levels selected): every level's objects go to the group's parent and
  are selected; the levels and the group are deleted. An object inside a level alone is refused.

Blender has no LOD switching: the group is an Empty and every level stays visible. The reduction is a live
Decimate modifier (Maya's polyReduce history); its ratio is of faces, Maya's percentage is of vertices.
"""

import bpy

from .. import results
from . import naming

GROUP, LEVEL = "allset_lod_group", "allset_lod_level"
REDUCE = 100.0 / 3.0          # Maya's first generated level: 33.3% of the vertices removed


def _empty(context, name, parent=None):
    ob = bpy.data.objects.new(name, None)
    (parent.users_collection[0] if parent else context.collection).objects.link(ob)
    ob.parent = parent
    return ob


def _parent_keep(ob, parent):
    world = ob.matrix_world.copy()
    ob.parent = parent
    ob.matrix_world = world


def lod_group_of(ob):
    while ob is not None:
        if ob.get(GROUP):
            return ob
        ob = ob.parent
    return None


def level(group, i):
    return next((c for c in group.children if c.get(LEVEL) == i), None)


def create_group(context, objects, merge=False):
    """A new LOD group holding ``objects`` (one level each, or all in LOD_0 when ``merge``); the group."""
    taken = {o.name for o in bpy.data.objects}
    group = _empty(context, f"LOD_Group_{naming.next_number('LOD_Group_', taken)}")
    group[GROUP] = True
    n = (1 if merge else len(objects)) if objects else 3
    for i in range(n):
        lv = _empty(context, f"LOD_{i}", group)
        lv[LEVEL] = i
        for ob in (objects if merge else objects[i:i + 1]):
            _parent_keep(ob, lv)
    return group


def generate(context, objects):
    """Maya Generate LOD Meshes, level 1: reduced duplicates of LOD_0's meshes under LOD_1; the new meshes."""
    groups = {lod_group_of(o) for o in objects} - {None}
    if len(groups) > 1:
        raise ValueError("The selection is in more than one LOD group.")
    group = groups.pop() if groups else create_group(context, objects, merge=True)
    zero = level(group, 0)
    one = level(group, 1)
    if one is None:
        one = _empty(context, "LOD_1", group)
        one[LEVEL] = 1
    for c in list(one.children):
        bpy.data.objects.remove(c)
    out = []
    for src in [c for c in zero.children if c.type == 'MESH']:
        dup = src.copy()
        dup.data = src.data.copy()
        one.users_collection[0].objects.link(dup)
        dup.parent = one
        dup.matrix_parent_inverse = src.matrix_parent_inverse.copy()
        naming.apply_maya_name(dup, naming.base_name(src.name))
        mod = dup.modifiers.new("polyReduce1", 'DECIMATE')
        mod.ratio = 1.0 - REDUCE / 100.0
        out.append(dup)
    return out


def picked_group(ob):
    """The LOD group of a selected group or level transform (Maya ungroups from those), else None."""
    if ob.get(GROUP):
        return ob
    if ob.get(LEVEL) is not None and ob.parent is not None and ob.parent.get(GROUP):
        return ob.parent
    return None


def ungroup(group):
    """Maya Ungroup LOD Group: every level's objects to the group's parent (world place kept), the level transforms
    and the group deleted; returns the objects moved."""
    moved = []
    for lv in list(group.children):
        for ob in list(lv.children):
            _parent_keep(ob, group.parent)
            moved.append(ob)
        if lv.get(LEVEL) is not None:
            bpy.data.objects.remove(lv)
        else:                                   # not a level: kept, like the objects
            _parent_keep(lv, group.parent)
            moved.append(lv)
    bpy.data.objects.remove(group)
    return moved


def _select_only(context, objects):
    context.view_layer.update()         # objects made / removed just now: the view layer first, then the selection
    for o in list(context.view_layer.objects.selected):
        o.select_set(False)
    for o in objects:
        o.select_set(True)
    if objects:
        context.view_layer.objects.active = objects[0]


class ALLSET_OT_lod(bpy.types.Operator):
    """Maya Edit > LOD: group the selection as levels of detail, add reduced duplicates, or ungroup"""
    bl_idname = "allset.lod"
    bl_label = "LOD (Level of Detail)"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=(('CREATE', "Create LOD Group", ""),
                                          ('GENERATE', "Generate LOD Meshes", ""),
                                          ('UNGROUP', "Ungroup LOD Group", "")), options={'SKIP_SAVE'})

    def execute(self, context):
        sel = sorted(context.selected_objects, key=lambda o: o.name)
        act = context.view_layer.objects.active
        if act in sel:      # Blender's active = Maya's last pick: keep the others first, by name
            sel.remove(act)
            sel.append(act)
        if self.action == 'UNGROUP':
            # like Maya: the LOD group or one of its level transforms; an object inside a level is not enough
            groups = {picked_group(o) for o in sel} - {None}
            if not sel or not groups:
                self.report({'ERROR'}, "Nothing selected." if not sel else
                            "Select a LOD group or one of its levels: nothing ungrouped.")
                return {'CANCELLED'}
            moved = []
            for g in groups:
                moved += ungroup(g)
            _select_only(context, moved)
            return {'FINISHED'}
        if self.action == 'CREATE':
            sel = [o for o in sel if o.type != 'CAMERA']
            for o in sel:
                if o.parent is not None:
                    self.report({'ERROR'}, f"{o.name} has a parent: only top-level objects can be LOD levels.")
                    return {'CANCELLED'}
            group = create_group(context, sel)
            _select_only(context, [group])          # Maya selects the new LOD group
            results.result(self, group.name)
            return {'FINISHED'}
        meshes = [o for o in sel if o.type == 'MESH']
        if not meshes:
            self.report({'ERROR'}, "Select meshes to generate LOD meshes.")
            return {'CANCELLED'}
        try:
            out = generate(context, meshes)
        except ValueError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        group = lod_group_of(meshes[0])
        if group is not None:
            _select_only(context, [group])
        results.result(self, f"{len(out)} LOD mesh(es)")
        return {'FINISHED'}


classes = (ALLSET_OT_lod,)
