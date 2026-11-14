# SPDX-License-Identifier: GPL-3.0-or-later
"""Editing in the kit-drawn Maya Outliner tree (``outliner_tree``): rename, reveal, middle-mouse drops, the
visibility column and Delete.

- Rename: a double-click on a row's name or Enter (Maya) opens a small name field over the row; Enter renames
  with the Channel Box name rules (``channel_box.rename_lead``: spaces become "_", a taken name gets its base's next
  number, a transform's shape follows). Joints rename their bone, shape rows the object data, set rows the set.
- Reveal (F, like Maya's Reveal Selected): the rows above the selection open and the Outliner scrolls to it. A joint
  picked outside the Outliner is revealed the same way.
- Middle-mouse drag (``operators/outliner_drag.py`` asks ``drop`` here in a kit tree): onto an object row = parent
  under it, onto a joint row = parent under that joint (objects keep their place; joints of the same skeleton move
  under it), between rows = that row's parent, onto empty space = to the world. A skeleton's root joint stands for
  the skeleton: dropped onto an object row the skeleton goes under that object.
- Display > Visibility Column: an eye at the right of every object / joint row toggles its visibility (the
  Channel Box Visibility channel: ``hide_viewport``; a joint's bone).
- Delete / Backspace: the selected objects with everything below them (Maya Edit > Delete), picked joints with the
  joints below them.
"""

import bpy
from bpy.props import StringProperty

from . import outliner_tree as tree


# --- rename --------------------------------------------------------------------------------------------------------

_rename = {"row": None}       # (kind, ob, sub) of the row the name field edits


def rename_target(row):
    """The data a row's name field edits, or None (drawn rows have nothing behind them)."""
    kind, ob_name, sub = row
    if kind in ('OBJECT', 'MEMBER'):
        return bpy.data.objects.get(ob_name)
    if kind == 'JOINT':
        ob = bpy.data.objects.get(ob_name)
        if ob is None or ob.type != 'ARMATURE':
            return None
        if ob.mode == 'EDIT':
            return ob.data.edit_bones.get(sub)
        return ob.pose.bones.get(sub) if ob.pose is not None else None
    if kind == 'SHAPE':
        ob = bpy.data.objects.get(ob_name)
        return ob.data if ob is not None else None
    if kind == 'SET':
        from ..operators import sets
        return sets.get(ob_name)
    return None


def rename(row, text):
    """Rename what ``row`` = (kind, ob, sub) shows; returns the new name, None when nothing changed."""
    from . import input_line
    target = rename_target(row)
    if target is None:
        return None
    kind = row[0]
    if kind in ('OBJECT', 'MEMBER'):
        from .channel_box import rename_lead
        return rename_lead(target, text)
    name = input_line.clean_name(text)
    if name is None:
        input_line._say(f"Rename: \"{text.strip()}\" is not a valid name (letters, digits and _, "
                        "not starting with a digit).")
        return None
    if name == target.name:
        return None
    old = target.name
    target.name = name
    if kind == 'JOINT':
        ob = bpy.data.objects.get(row[1])
        key = ('B', ob.session_uid, old)
        if key in tree.EXPANDED:
            tree.EXPANDED.discard(key)
            tree.EXPANDED.add(('B', ob.session_uid, target.name))
    tree._bump_expand()
    return target.name


def _name_get(_self):
    row = _rename["row"]
    target = rename_target(row) if row else None
    return target.name if target is not None else ""


def _name_set(_self, value):
    row = _rename["row"]
    if row is None:
        return
    new = rename(row, value)
    if new is not None:
        _rename["row"] = (row[0], new if row[0] in ('OBJECT', 'MEMBER', 'SET') else row[1],
                          new if row[0] == 'JOINT' else row[2])
        tree.redraw_outliners()


class ALLSET_PT_outliner_tree_rename(bpy.types.Panel):
    """The Outliner row name field (opened by allset.outliner_tree_rename only)"""
    bl_space_type = 'TOPBAR'   # like Blender's TOPBAR_PT_name (F2): only shown through wm.call_panel
    bl_region_type = 'HEADER'
    bl_label = "Rename"
    bl_ui_units_x = 10

    def draw(self, context):
        row = self.layout.row()
        row.activate_init = True
        row.prop(context.scene, "allset_tree_name", text="")


class ALLSET_OT_outliner_tree_rename(bpy.types.Operator):
    """Rename the row: double-click its name, or Enter for the selected row"""
    bl_idname = "allset.outliner_tree_rename"
    bl_label = "Rename"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.region is not None and context.region.type == 'WINDOW'

    def invoke(self, context, event):
        if not tree._poll(context):
            return {'PASS_THROUGH'}
        rows = tree.rows_for(context, context.space_data)
        if event is not None and event.type == 'LEFTMOUSE':
            u = tree.unit(context.preferences)
            k = tree.row_index_at(context.area, context.region, event.mouse_region_y, u, len(rows))
        else:
            k = tree.active_row(context, rows)
        if k is None:
            return {'CANCELLED'}
        r = rows[k]
        if rename_target((r.kind, r.ob, r.sub)) is None:
            return {'CANCELLED'}
        _rename["row"] = (r.kind, r.ob, r.sub)
        bpy.ops.wm.call_panel(name=ALLSET_PT_outliner_tree_rename.__name__, keep_open=False)
        return {'FINISHED'}


# --- reveal --------------------------------------------------------------------------------------------------------

def _bone_keys(ob, name):
    """Expanded keys of the joints above joint ``name`` of skeleton ``ob``."""
    data = ob.data
    coll = data.edit_bones if data.is_editmode else data.bones
    b = coll.get(name)
    keys = []
    p = b.parent if b is not None else None
    while p is not None:
        keys.append(('B', ob.session_uid, p.name))
        p = p.parent
    return keys


def ancestor_keys(ob, bone=None, cache=None):
    """Expanded keys of every row above object ``ob`` (or its joint ``bone``); ``cache`` = {armature: bone info}
    shared across calls."""
    cache = {} if cache is None else cache
    keys = []
    if bone:
        keys += _bone_keys(ob, bone)
        if not _kit_skeleton(ob, cache):
            keys.append(('O', ob.session_uid))
    return keys + _object_chain(ob, cache)


def ancestors_of(items, cache=None):
    """The set of ``ancestor_keys`` of every (object, joint) of ``items``, each object's own chain read once and a
    joint's parents only up to a joint already walked (hundreds of picked joints share their parents); an item whose
    keys can't be read adds none, as with ``ancestor_keys``."""
    cache = {} if cache is None else cache
    out, chains, walked = set(), {}, {}
    for ob, bone in items:
        try:
            keys, names = [], ()
            if bone:
                done = walked.get(ob.as_pointer(), ())
                names = _bone_parents_until(ob, bone, done)
                uid = ob.session_uid
                keys += [('B', uid, n) for n in names]
                if not _kit_skeleton(ob, cache):
                    keys.append(('O', uid))
            ptr = ob.as_pointer()
            chain = chains.get(ptr)
            if chain is None:
                chain = chains[ptr] = _object_chain(ob, cache)
            keys += chain
        except (AttributeError, ReferenceError):
            continue
        out.update(keys)
        if names:
            walked.setdefault(ob.as_pointer(), set()).update(names)
    return out


def _bone_parents_until(ob, name, done):
    """Names of the joints above joint ``name`` of skeleton ``ob``, upward, stopping before one in ``done`` (its own
    parents were walked already)."""
    data = ob.data
    coll = data.edit_bones if data.is_editmode else data.bones
    b = coll.get(name)
    out = []
    p = b.parent if b is not None else None
    while p is not None:
        n = p.name
        if n in done:
            break
        out.append(n)
        p = p.parent
    return out


def _object_chain(ob, cache):
    """Expanded keys of the rows above object ``ob`` itself (its parents, joints it hangs under)."""
    keys = []
    p, child = ob.parent, ob
    while p is not None:
        if child.parent_type == 'BONE' and p.type == 'ARMATURE' and child.parent_bone:
            keys.append(('B', p.session_uid, child.parent_bone))
            keys += _bone_keys(p, child.parent_bone)
            if not _kit_skeleton(p, cache):
                keys.append(('O', p.session_uid))
        elif _kit_skeleton(p, cache):
            # an object under a kit skeleton hangs under its first root joint
            roots = _info(p, cache).roots
            if roots:
                keys.append(('B', p.session_uid, roots[0]))
        else:
            keys.append(('O', p.session_uid))
        child, p = p, p.parent
    return keys


def _info(ob, cache):
    got = cache.get(ob)
    if got is None:
        got = cache[ob] = tree._Bones(ob)
    return got


def _kit_skeleton(ob, cache=None):
    if ob is None or ob.type != 'ARMATURE' or not tree.kit_skeleton_name(ob):
        return False             # any other armature: no need to read its joints
    return tree.is_kit_skeleton(ob, _info(ob, {} if cache is None else cache))


def selected_items(context):
    """[(object, bone name or None)] picked now: joints of the active skeleton in Pose / Edit Mode, else objects."""
    ob = context.view_layer.objects.active
    if ob is not None and ob.type == 'ARMATURE' and ob.mode in ('POSE', 'EDIT'):
        if ob.mode == 'POSE':
            from .channel_box import bone_selected
            names = [pb.name for pb in ob.pose.bones if bone_selected(pb)]
        else:
            names = [eb.name for eb in ob.data.edit_bones if eb.select_head or eb.select]
        active = ob.data.bones.active if ob.mode == 'POSE' else ob.data.edit_bones.active
        if active is not None and active.name in names:
            names.remove(active.name)
            names.append(active.name)          # the lead last
        return [(ob, n) for n in names]
    items = [(o, None) for o in context.selected_objects]
    if ob is not None and (ob, None) in items:
        items.remove((ob, None))
        items.append((ob, None))
    return items


def reveal(context, area, region, space, items):
    """Open the rows above ``items`` [(object, bone)] and scroll the Outliner to the lead (the last one) when it is
    out of view. Returns the lead's row index or None."""
    keys = []
    for ob, bone in items:
        keys += ancestor_keys(ob, bone)
    if keys:
        tree.set_expanded(keys, True)
    if not items:
        return None
    ob, bone = items[-1]
    rows = tree.rows_for(context, space)
    k = next((i for i, r in enumerate(rows) if r.ob == ob.name and (
        (bone is not None and r.kind == 'JOINT' and r.sub == bone) or
        (bone is None and r.kind == 'OBJECT') or
        (bone is None and r.kind == 'JOINT' and r.top))), None)
    if k is None:
        return None
    u = tree.unit(context.preferences)
    first = tree.first_row(area, region, len(rows), u)
    page = tree.page_rows(region, u)
    if not first <= k < first + page:
        tree.SCROLL[area.as_pointer()] = max(0, k - page // 2)
        tree.first_row(area, region, len(rows), u)
    area.tag_redraw()
    return k


def reveal_all(context, items=None):
    """Reveal the selection in every kit tree; returns how many trees did."""
    done = 0
    items = selected_items(context) if items is None else items
    for window in context.window_manager.windows:
        screen = window.screen
        for area in screen.areas if screen is not None else ():
            if area.type != 'OUTLINER' or not tree.is_tree(area.spaces.active):
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue
            with context.temp_override(window=window, area=area, region=region):
                if reveal(bpy.context, area, region, area.spaces.active, items) is not None:
                    done += 1
    return done


class ALLSET_OT_outliner_tree_reveal(bpy.types.Operator):
    """Open the rows above the selection and scroll to it (Maya Reveal Selected)"""
    bl_idname = "allset.outliner_tree_reveal"
    bl_label = "Reveal Selected"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.region is not None and context.region.type == 'WINDOW'

    def invoke(self, context, event):
        if not tree._poll(context):
            return {'PASS_THROUGH'}
        return self.execute(context)

    def execute(self, context):
        if not tree._poll(context):
            return {'CANCELLED'}
        reveal(context, context.area, context.region, context.space_data, selected_items(context))
        return {'FINISHED'}


# --- middle-mouse drops ---------------------------------------------------------------------------------------------

def _activate(context, ob):
    """Make skeleton ``ob`` the active object (for edit-mode joint parenting)."""
    vl = context.view_layer
    if vl.objects.active == ob:
        return True
    if context.mode != 'OBJECT' and vl.objects.active is not None:
        bpy.ops.object.mode_set(mode='OBJECT')
    try:
        ob.select_set(True)
    except RuntimeError:
        return False
    vl.objects.active = ob
    return True


def parent_to_bone(objects, arm, bone):
    """Parent ``objects`` under joint ``bone`` of ``arm`` keeping where they are. Returns those parented."""
    from ..operators import parenting
    done = []
    for ob in objects:
        if ob is arm or parenting.is_ancestor(ob, arm):
            continue
        world = ob.matrix_world.copy()
        ob.parent = arm
        ob.parent_type = 'BONE'
        ob.parent_bone = bone
        ob.matrix_parent_inverse.identity()
        bpy.context.view_layer.update()
        ob.matrix_world = world
        done.append(ob)
    if done:
        parenting._to_end(done)
    return done


def _reorder_joints(arm, names, target, after):
    """Put joints ``names`` right before / after joint ``target`` among its siblings (Maya child order stamps)."""
    from ..operators.joints import CHILD_ORDER
    data = arm.data
    coll = data.edit_bones if data.is_editmode else data.bones
    t = coll.get(target)
    if t is None:
        return
    sibs = [b for b in coll if b.parent == t.parent]
    index = {b.name: i for i, b in enumerate(coll)}
    sibs.sort(key=lambda b: float(b.get(CHILD_ORDER)) if b.get(CHILD_ORDER) is not None else float(index[b.name]))
    order = [b.name for b in sibs if b.name not in names]
    i = order.index(target) + (1 if after else 0) if target in order else len(order)
    order[i:i] = [n for n in names if n in {b.name for b in sibs}]
    base = max([len(coll)] + [float(b.get(CHILD_ORDER)) for b in coll if b.get(CHILD_ORDER) is not None]) + 1.0
    for j, name in enumerate(order):
        coll[name][CHILD_ORDER] = base + j


def drop(context, dragged, target, where):
    """Maya Outliner middle-mouse drop of ``dragged`` [(kind, ob, sub)] on ``target`` (a Row or None = empty space)
    at ``where`` ('ON' / 'BEFORE' / 'AFTER'). Returns (changed, message)."""
    try:
        return _drop(context, dragged, target, where)
    finally:
        tree._bump_expand()          # order numbers / child order stamps are ID properties: nothing tags an update


def _drop(context, dragged, target, where):
    from ..operators import joints, outliner_drag
    from . import outliner_order
    objs = [bpy.data.objects[o] for k, o, _s in dragged if k in ('OBJECT', 'MEMBER') and o in bpy.data.objects]
    jts = [(bpy.data.objects[o], s) for k, o, s in dragged if k == 'JOINT' and o in bpy.data.objects]
    changed, msg = 0, ""
    # joints: a kit skeleton's root joints stand for the skeleton object
    skel = []
    rest = []
    for arm, name in jts:
        b = tree._Bones(arm)
        if tree.is_kit_skeleton(arm, b) and name in b.roots:
            if arm not in skel:
                skel.append(arm)
        else:
            rest.append((arm, name))
    if target is not None and target.kind in ('SET', 'MEMBER'):
        # onto a set (or one of its members): Maya adds the dropped objects to that set
        from ..operators import sets
        coll = sets.get(target.ob if target.kind == 'SET' else target.sub)
        if coll is None:
            return 0, ""
        for ob in objs + skel:
            if ob.name not in coll.objects:
                coll.objects.link(ob)
                changed += 1
        return changed, msg
    if target is not None and target.kind in ('CAMERA', 'DEFAULT_SET', 'SHAPE'):
        return 0, ""            # nothing behind a drawn row; a shape can't hold children
    if target is None:
        # empty space: to the world
        if objs or skel:
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            changed += len(outliner_drag.reparent(objs + skel, None)[0])
        for arm in {a for a, _n in rest}:
            names = [n for a, n in rest if a == arm]
            if _activate(context, arm):
                changed += joints.parent_joints(arm, names, None)
        return changed, msg
    t_ob = bpy.data.objects.get(target.ob)
    if t_ob is None:
        return 0, ""
    if target.kind == 'OBJECT' or (target.kind == 'JOINT' and where != 'ON' and target.top):
        # onto an object row (or between top rows): Maya parent (between = that row's parent, placed there)
        if target.kind == 'JOINT':
            t_parent, t_ref = t_ob.parent, t_ob
        else:
            t_parent = t_ob if where == 'ON' else t_ob.parent
            t_ref = t_ob
        if rest:
            msg = "A joint inside a skeleton can't go under an object: drop its root joint to move the skeleton"
        movers = [o for o in objs + skel if o is not t_ob]
        if not movers:
            return changed, msg
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        context.view_layer.update()
        to_move = [o for o in movers if o.parent != t_parent or o.parent_type == 'BONE']
        done, cycles = outliner_drag.reparent(to_move, t_parent)
        if cycles:
            msg = "Skipped (the drop target is their descendant): " + ", ".join(o.name for o in cycles)
        changed += len(done)
        if where != 'ON':
            keep = [o for o in movers if o not in cycles]
            if outliner_order.place(context.scene, context.view_layer, keep, t_ref, where == 'AFTER',
                                    outliner_drag.reordered):
                changed += 1
        return changed, msg
    # a joint row
    arm, bone = t_ob, target.sub
    data = arm.data
    coll = data.edit_bones if data.is_editmode else data.bones
    tb = coll.get(bone)
    if tb is None:
        return 0, ""
    parent_bone = bone if where == 'ON' else (tb.parent.name if tb.parent is not None else None)
    if objs or skel:
        movers = [o for o in objs + skel if o is not arm]
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        context.view_layer.update()
        if parent_bone is None:
            done, _c = outliner_drag.reparent(movers, arm.parent)
            changed += len(done)
        else:
            changed += len(parent_to_bone(movers, arm, parent_bone))
    same = [n for a, n in rest if a == arm] + [n for a in skel if a == arm for n in tree._Bones(a).roots]
    other = [n for a, n in rest if a != arm]
    if other:
        msg = "Joints can only move under a joint of their own skeleton"
    if same:
        if _activate(context, arm):
            if parent_bone is not None or where != 'ON':
                changed += joints.parent_joints(arm, [n for n in same if n != parent_bone], parent_bone)
                if where != 'ON':
                    _reorder_joints(arm, same, bone, where == 'AFTER')
    return changed, msg


# --- visibility column ----------------------------------------------------------------------------------------------

def toggle_eye(context, row):
    """Flip the visibility of an object row (``hide_viewport``, Maya's visibility) or a joint row (its bone)."""
    ob = bpy.data.objects.get(row.ob)
    if ob is None:
        return False
    if row.kind == 'JOINT':
        # Maya: a joint's Visibility hides everything below it too, without changing the children's own Visibility
        # (ui/layer_joints.state); the eye sets this joint only
        from .. import compat
        from . import layer_joints
        if ob.mode == 'EDIT':
            eb = ob.data.edit_bones.get(row.sub)
            if eb is None:
                return False
            eb.hide = not eb.hide
        else:
            pb = ob.pose.bones.get(row.sub) if ob.pose is not None else None
            if pb is None:
                return False
            compat.set_bone_hidden(pb, not compat.bone_hidden(pb))
        layer_joints.bump()
        from ..operators import dag
        dag.sync(context.scene, context.view_layer)       # objects under the joints follow them
        return True
    if row.kind in ('OBJECT', 'MEMBER', 'SHAPE'):
        ob.hide_viewport = not ob.hide_viewport
        from ..operators import dag
        dag.sync(context.scene, context.view_layer)       # Maya hides what is below a hidden node
        return True
    return False


def eye_state(row, names=None):
    """True / False = shown / hidden for rows with an eye, None for rows without (``names``:
    ``outliner_tree.object_names()`` read for the redraw)."""
    ob = tree.object_named(row.ob, names) if row.kind in ('OBJECT', 'JOINT', 'MEMBER') else None
    if ob is None:
        return None
    if row.kind == 'JOINT':
        from .. import compat
        if ob.mode == 'EDIT':
            eb = ob.data.edit_bones.get(row.sub)
            return None if eb is None else not eb.hide
        pb = ob.pose.bones.get(row.sub) if ob.pose is not None else None
        return None if pb is None else not compat.bone_hidden(pb)
    return not ob.hide_viewport


# --- delete --------------------------------------------------------------------------------------------------------

def delete_selected(context):
    """Maya Edit > Delete from the Outliner: objects with everything below them, picked joints with the joints
    below them. Returns what was deleted (count)."""
    ob = context.view_layer.objects.active
    if ob is not None and ob.type == 'ARMATURE' and ob.mode in ('POSE', 'EDIT'):
        from ..operators import joints
        names = [n for _o, n in selected_items(context)]
        if not names:
            return 0
        with joints._InEditMode(ob) as ebs:
            gone = joints.with_descendants(ebs, names)
            for name in gone:
                eb = ebs.get(name)
                if eb is not None:
                    ebs.remove(eb)
        # Maya deletes what hangs below the joints too: objects parented to a deleted joint
        below = [o for o in context.scene.objects if o.parent == ob and o.parent_type == 'BONE'
                 and o.parent_bone in gone]
        if below:
            from ..operators import dag
            dag.delete_hierarchy(context, below)
        return len(gone)
    extra = [o for o in tree.picked_unselectable(context) if o not in context.selected_objects]
    if not context.selected_objects and not extra:
        return 0
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    n = len(context.selected_objects) + len(extra)
    if context.selected_objects:
        bpy.ops.allset.delete()
    if extra:
        from ..operators import dag
        dag.delete_hierarchy(context, [o for o in extra if o.name in bpy.data.objects])
    return n


# --- keys: pick walk ------------------------------------------------------------------------------------------------

class ALLSET_OT_outliner_tree_walk(bpy.types.Operator):
    """Pick walk from the selection, like Maya's Outliner arrow keys: Up = parent, Down = child, Left / Right =
    previous / next sibling"""
    bl_idname = "allset.outliner_tree_walk"
    bl_label = "Pick Walk"
    bl_options = {'INTERNAL'}

    direction: bpy.props.EnumProperty(items=(("UP", "Up", ""), ("DOWN", "Down", ""), ("LEFT", "Left", ""),
                                             ("RIGHT", "Right", "")), options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.region is not None and context.region.type == 'WINDOW'

    def invoke(self, context, event):
        if not tree._poll(context):
            return {'PASS_THROUGH'}
        if context.mode == 'POSE':
            result = bpy.ops.allset.pick_walk_joint('EXEC_DEFAULT', True, direction=self.direction)
        elif context.mode == 'OBJECT' and context.selected_objects:
            result = bpy.ops.allset.pick_walk('EXEC_DEFAULT', True, direction=self.direction)
        else:
            return {'CANCELLED'}
        tree.redraw_outliners(context)
        return result


# --- RMB: the Outliner menu -----------------------------------------------------------------------------------------

HIDDEN = "allset_hidden_in_outliner"     # Maya Hide In Outliner: the node (and what's below it) has no row


class ALLSET_OT_outliner_tree_hide(bpy.types.Operator):
    """Hide the selected objects from the Outliner (they stay in the scene), or show them in it again"""
    bl_idname = "allset.outliner_tree_hide"
    bl_label = "Hide In Outliner"
    bl_options = {'REGISTER', 'UNDO'}

    hide: bpy.props.BoolProperty(default=True, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        for ob in context.selected_objects:
            if self.hide:
                ob[HIDDEN] = True
            elif HIDDEN in ob:
                del ob[HIDDEN]
        tree._bump_expand()
        tree.redraw_outliners(context)
        return {'FINISHED'}


class ALLSET_OT_outliner_tree_show_all(bpy.types.Operator):
    """Show every object type in this Outliner (Maya Show > Show All)"""
    bl_idname = "allset.outliner_tree_show_all"
    bl_label = "Show All"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'OUTLINER'

    def execute(self, context):
        space = context.space_data
        for _t, prop in tree.TYPE_PROPS:
            if hasattr(space, prop):
                setattr(space, prop, True)
        return {'FINISHED'}


class ALLSET_MT_outliner_tree_sets(bpy.types.Menu):
    bl_label = "Sets"

    def draw(self, context):
        layout = self.layout
        layout.operator("allset.create_set", text="Create Set")
        layout.operator("allset.create_quick_select_set", text="Create Quick Select Set...")
        if not context.selected_objects:
            return
        layout.separator()
        layout.menu(ALLSET_MT_outliner_tree_add_set.__name__)
        layout.menu(ALLSET_MT_outliner_tree_remove_set.__name__)


class ALLSET_MT_outliner_tree_add_set(bpy.types.Menu):
    bl_label = "Add Selection to Set"

    def draw(self, context):
        from ..operators import sets
        for coll in sets.all_sets():
            op = self.layout.operator("allset.set_edit", text=coll.name)
            op.name, op.action = coll.name, 'ADD'


class ALLSET_MT_outliner_tree_remove_set(bpy.types.Menu):
    bl_label = "Remove Selection from Set"

    def draw(self, context):
        from ..operators import sets
        picked = set(context.selected_objects)
        for coll in sets.all_sets():
            if picked & set(coll.objects):
                op = self.layout.operator("allset.set_edit", text=coll.name)
                op.name, op.action = coll.name, 'REMOVE'


class ALLSET_MT_outliner_tree_hide(bpy.types.Menu):
    bl_label = "Hide In Outliner"

    def draw(self, context):
        self.layout.operator(ALLSET_OT_outliner_tree_hide.bl_idname, text="Hide").hide = True
        self.layout.operator(ALLSET_OT_outliner_tree_hide.bl_idname, text="Unhide").hide = False


class ALLSET_MT_outliner_tree(bpy.types.Menu):
    """Maya's Outliner right-click menu (the same on every row and on empty space)"""
    bl_label = "Outliner"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_REGION_WIN'
        space = context.space_data
        if space is not None and space.type == 'OUTLINER':
            layout.prop(space, "use_filter_object_content", text="Shapes")
        layout.separator()
        layout.operator(ALLSET_OT_outliner_tree_reveal.bl_idname, text="Reveal Selected")
        layout.menu(ALLSET_MT_outliner_tree_hide.__name__)
        layout.separator()
        layout.menu(ALLSET_MT_outliner_tree_sets.__name__)
        layout.separator()
        layout.menu("ALLSET_MT_outliner_display", text="Display")
        layout.menu("ALLSET_MT_outliner_show", text="Show")


class ALLSET_OT_outliner_tree_menu(bpy.types.Operator):
    """Maya's Outliner right-click menu; on a set row, the set's menu"""
    bl_idname = "allset.outliner_tree_menu"
    bl_label = "Outliner Menu"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.region is not None and context.region.type == 'WINDOW'

    def invoke(self, context, event):
        if not tree._poll(context):
            return {'PASS_THROUGH'}
        rows = tree.rows_for(context, context.space_data)
        u = tree.unit(context.preferences)
        k = tree.row_index_at(context.area, context.region, event.mouse_region_y, u, len(rows))
        row = rows[k] if k is not None else None
        if row is not None and row.kind in ('SET', 'MEMBER'):
            # the kit's set menu (Select Set Members, Show Set Members, Add / Remove, Rename, Delete Set)
            wm = context.window_manager
            wm.allset_set_target = row.ob if row.kind == 'SET' else row.sub
            wm.allset_set_member = row.ob if row.kind == 'MEMBER' else ""
            bpy.ops.wm.call_menu(name="ALLSET_MT_outliner_set")
            return {'FINISHED'}
        bpy.ops.wm.call_menu(name=ALLSET_MT_outliner_tree.__name__)
        return {'FINISHED'}


class ALLSET_OT_outliner_tree_delete(bpy.types.Operator):
    """Delete the selection and everything below it (Maya Edit > Delete)"""
    bl_idname = "allset.outliner_tree_delete"
    bl_label = "Delete"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return tree._poll(context)

    def execute(self, context):
        n = delete_selected(context)
        tree.redraw_outliners(context)
        return {'FINISHED'} if n else {'CANCELLED'}


classes = (ALLSET_PT_outliner_tree_rename, ALLSET_OT_outliner_tree_rename, ALLSET_OT_outliner_tree_reveal,
           ALLSET_OT_outliner_tree_walk, ALLSET_OT_outliner_tree_hide, ALLSET_OT_outliner_tree_show_all,
           ALLSET_MT_outliner_tree_sets, ALLSET_MT_outliner_tree_add_set, ALLSET_MT_outliner_tree_remove_set,
           ALLSET_MT_outliner_tree_hide, ALLSET_MT_outliner_tree, ALLSET_OT_outliner_tree_menu,
           ALLSET_OT_outliner_tree_delete)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.allset_tree_name = StringProperty(
        name="Name", get=_name_get, set=_name_set, options={'SKIP_SAVE'},
        description="The row's name: Enter renames it")


def unregister():
    del bpy.types.Scene.allset_tree_name
    _rename["row"] = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
