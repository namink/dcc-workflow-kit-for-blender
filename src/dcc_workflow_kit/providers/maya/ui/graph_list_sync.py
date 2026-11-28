# SPDX-License-Identifier: GPL-3.0-or-later
"""Keeps Blender's Graph Editor / Dope Sheet filters in step with the Maya list: the kit list collection set as the
editor's Collection filter, curves the kit hides, Load / Add Selected Objects and Auto Load, and ``sync`` (timer and
menu entry); ``release_all`` undoes it on disable.
"""

import bpy

from .editor_kinds import enabled, is_graph, is_dope
from .editor_headers import setup_toolbar_row, release_toolbar_rows
from .graph_channels import _bone_name, object_curves, shape_key, one_pass
from .graph_list import (AUTO, BONES, LIST_MARK, LOADED, ATTR_FILTERS, _ds, _is_dope_space, _object_kinds, _pinned,
                         _pinned_nodes, _selected_objects, _character_members, attr_filters, auto_load, kit_list,
                         listed_curves, listed_objects, loaded_names, row_objects, upstream_curves)


# Blender: a Graph Editor / Dope Sheet draws the objects its own filters let through (Only Show Selected, the
# Collection filter ``dopesheet.filter_collection``). A list Blender's selection filter can't express (loaded, plus
# pinned owners / hierarchy / upstream curve owners / character members, only IK handles) is a kit collection
# (ID prop ``allset_list``, no scene, fake user: one per editor, saved with the file like Maya's panel state) set as
# that editor's Collection filter, Only Show Selected off; its members follow the rules from graph_view's 0.25 s
# timer (``sync``). Curves Blender then draws that the Maya list doesn't show (unpinned curves of a pinned curve's
# node, joints not loaded, attributes filtered out) are hidden (``fc.hide``) and shown again when they're listed
# (``_kit_hidden``). Driven channels (driver curves: Maya driven key / expression) are listed like keyed ones: Blender
# draws drivers only in the Graph Editor's Drivers mode, so those rows have no curve in F-Curve mode.
_kit_hidden = set()            # (id kind, id name, data path, index) of curves the kit hid


def drawn_objects(context, space):
    """Objects Blender must draw for this editor (None = every object): the list's objects plus the owners of
    pinned curves, of upstream curves (Graph Editor) and the members of listed character nodes (a set node has no
    channels)."""
    obs = row_objects(context, space)
    if obs is None:
        return None
    extra = []
    if not _is_dope_space(space):
        extra += [n.id_data if isinstance(n, bpy.types.PoseBone) else n for n in _pinned_nodes()
                  if isinstance(n, (bpy.types.Object, bpy.types.PoseBone))]
        extra += [owner for owner, _fc in upstream_curves(context, space) if isinstance(owner, bpy.types.Object)]
    if _object_kinds() & {"sets", "characters"}:
        extra += _character_members(context)
    extra = [o for o in dict.fromkeys(extra) if o not in obs]
    if extra:
        in_scene = set(context.scene.objects)
        extra = [o for o in extra if o in in_scene]
    return obs + extra


def needs_kit_list(context, space):
    """Can Blender's own filters show this list (all, or exactly the selection)? Else the kit list."""
    if loaded_names(space) is not None or "ik" in _object_kinds():
        return True
    obs = drawn_objects(context, space)
    return obs is not None and (not auto_load(space) or set(obs) != set(_selected_objects(context)))


def _new_list():
    coll = bpy.data.collections.new(".AllsetList")
    coll.use_fake_user = True          # in no scene: kept in the file like Maya's editor panel state
    coll[LIST_MARK] = 1
    return coll


def _drop_list(coll):
    if coll is not None and coll.get(LIST_MARK) and coll.users <= 1:
        bpy.data.collections.remove(coll)


def sync_space(context, space):
    """Put Blender's filters of one Graph Editor / Dope Sheet in step with its Maya list; True when changed."""
    ds = _ds(space)
    if ds is None:
        return False
    coll = kit_list(space)
    if coll is None and getattr(ds, "filter_collection", None) is not None:
        return False                   # the user's own Collection filter: left alone
    if not needs_kit_list(context, space):
        if coll is None:
            return False
        auto = coll.get(LOADED) is None and bool(coll.get(AUTO, False))
        ds.filter_collection = None
        ds.show_only_selected = auto
        _drop_list(coll)
        return True
    changed = False
    if coll is None:
        auto = bool(ds.show_only_selected)
        coll = _new_list()
        coll[AUTO] = auto
        ds.filter_collection = coll
        changed = True
    if ds.show_only_selected:
        if coll.get(LOADED) is None:
            coll[AUTO] = True
        ds.show_only_selected = False
        changed = True
    obs = drawn_objects(context, space)
    want = set(context.scene.objects if obs is None else obs)
    have = set(coll.objects)
    for ob in have - want:
        coll.objects.unlink(ob)
    for ob in want - have:
        coll.objects.link(ob)
    return changed or want != have


def set_auto_load(context, space, on):
    """Maya Auto Load on: the list follows the selection (a loaded list is dropped); off: the list shown now is
    frozen (Maya's locked copy: selecting other objects no longer changes it)."""
    ds = _ds(space)
    if ds is None:
        return
    if not on:
        if auto_load(space):
            load_selected(context, space)
        return
    coll = kit_list(space)
    if coll is not None:
        if LOADED in coll:
            del coll[LOADED]
        if BONES in coll:
            del coll[BONES]
        coll[AUTO] = bool(on)
        ds.show_only_selected = False
    else:
        ds.show_only_selected = bool(on)
    sync_space(context, space)


def _selected_bones(context):
    from . import channel_box
    out = []
    for ob in _selected_objects(context):
        if ob.type == 'ARMATURE' and ob.mode == 'POSE' and ob.pose is not None:
            out += [f"{ob.name}\t{pb.name}" for pb in ob.pose.bones if channel_box.bone_selected(pb)]
    return out


def load_selected(context, space, add=False):
    """Maya List > Load Selected Objects (``add`` = Add Selected Objects): a fixed list, Auto Load off."""
    ds = _ds(space)
    if ds is None:
        return []
    names = loaded_names(space)
    bones = list(kit_list(space).get(BONES, ())) if names is not None else []
    if add and names is None:          # adding to the list shown now
        names = [ob.name for ob in listed_objects(context, space)]
    if not add or names is None:
        names, bones = [], []
    sel = _selected_objects(context)
    names += [ob.name for ob in sel if ob.name not in names]
    bones += [b for b in _selected_bones(context) if b not in bones]
    if not add:
        bones = _selected_bones(context)
    coll = kit_list(space) or _new_list()
    coll[LOADED] = names
    coll[BONES] = bones
    coll[AUTO] = False
    ds.filter_collection = coll
    ds.show_only_selected = False
    sync_space(context, space)
    return names


# --- keeping Blender's drawing in step with the Maya list ----------------------------------------------------------

def editor_spaces(context):
    """[(window, area, space)] of every Maya Graph Editor (F-Curves) and Dope Sheet (not the Timeline)."""
    out = []
    for w in context.window_manager.windows:
        if w.screen is None:
            continue
        for a in w.screen.areas:
            sp = a.spaces.active
            if is_graph(sp) or is_dope(sp):
                out.append((w, a, sp))
    return out


def _curve_key(owner, fc):
    return ("KEY" if isinstance(owner, bpy.types.Key) else "OBJECT", owner.name, fc.data_path, fc.array_index)


def _resolve_curve(key):
    kind, name, path, idx = key
    owner = (bpy.data.shape_keys if kind == "KEY" else bpy.data.objects).get(name)
    if owner is None:
        return None
    return next((fc for fc in object_curves(owner) if fc.data_path == path and fc.array_index == idx), None)


def _drawn_curves(context, space):
    """{curve key: fcurve} Blender draws in this Graph Editor (by object; joints only selected ones while Blender's
    Only Show Selected filters them)."""
    from . import channel_box
    obs = drawn_objects(context, space)
    if obs is None:
        obs = list(context.scene.objects)
    native_auto = bool(_ds(space).show_only_selected)
    out = {}
    for ob in obs:
        for fc in object_curves(ob):
            if native_auto and ob.type == 'ARMATURE' and ob.pose is not None:
                name = _bone_name(fc.data_path)
                pb = ob.pose.bones.get(name) if name is not None else None
                if pb is not None and not channel_box.bone_selected(pb):
                    continue
            out[_curve_key(ob, fc)] = fc
        key = shape_key(ob)
        if key is not None:
            for fc in object_curves(key):
                out[_curve_key(key, fc)] = fc
    return out


def sync_hidden(context, spaces):
    """Hide the curves Blender draws that no Maya list shows; show again the ones the kit hid once listed. Only
    while a kit list, an attribute filter or a pin is in play (or the kit still has curves hidden)."""
    graphs = [sp for sp in spaces if is_graph(sp)]
    active = _pinned or attr_filters() or any(kit_list(sp) is not None for sp in graphs)
    if not (active or _kit_hidden):
        return 0
    want, listed = {}, set()
    for sp in graphs if active else ():
        drawn = _drawn_curves(context, sp)
        shown = {fc.as_pointer() for fc in listed_curves(context, sp)}
        for key, fc in drawn.items():
            if fc.as_pointer() in shown:
                listed.add(key)
            else:
                want[key] = fc
    n = 0
    for key, fc in want.items():
        if key not in listed and not fc.hide:
            fc.hide = True
            _kit_hidden.add(key)
            n += 1
    for key in list(_kit_hidden):
        if key in want and key not in listed:
            continue
        _kit_hidden.discard(key)
        fc = _resolve_curve(key)
        if fc is not None and fc.hide:
            fc.hide = False
            n += 1
    return n


def sync(context):
    """Every Graph Editor / Dope Sheet: Blender's filters follow its Maya list (graph_view's timer, menu items)."""
    if not enabled(context):
        return
    found = list(editor_spaces(context))
    spaces = [sp for _w, _a, sp in found]
    changed = False
    for window, area, sp in found:
        if (is_graph(sp) or is_dope(sp)) and setup_toolbar_row(window, area):
            changed = True
    with one_pass():
        for sp in spaces:
            changed |= sync_space(context, sp)
        changed |= bool(sync_hidden(context, spaces))
    if changed:
        _redraw_editors(context)


def _redraw_editors(context):
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type in {'GRAPH_EDITOR', 'DOPESHEET_EDITOR'}:
                area.tag_redraw()


def release_all():
    """Disable: every editor back to Blender's own filters, kit lists removed, hidden curves shown, pins dropped."""
    try:
        spaces = [sp for _w, _a, sp in editor_spaces(bpy.context)]
    except (AttributeError, ReferenceError):
        spaces = []
    for sp in spaces:
        coll = kit_list(sp)
        if coll is not None:
            auto = coll.get(LOADED) is None and bool(coll.get(AUTO, False))
            sp.dopesheet.filter_collection = None
            sp.dopesheet.show_only_selected = auto
    for coll in [c for c in bpy.data.collections if c.get(LIST_MARK)]:
        bpy.data.collections.remove(coll)
    for key in _kit_hidden:
        fc = _resolve_curve(key)
        if fc is not None:
            fc.hide = False
    _kit_hidden.clear()
    _pinned.clear()
    release_toolbar_rows()


class ALLSET_OT_graph_list(bpy.types.Operator):
    """Maya List > Load Selected Objects (replace the list) / Add Selected Objects (add to it): the list stays
    when the selection changes (only while Auto Load Selected Objects is off)"""
    bl_idname = "allset.graph_list"
    bl_label = "Load Selected Objects"
    bl_options = {'UNDO'}

    action: bpy.props.EnumProperty(items=(("LOAD", "Load", "Load the selected objects"),
                                          ("ADD", "Add", "Add the selected objects")),
                                   default="LOAD", options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        # Maya greys Load / Add Selected Objects while Auto Load is on
        space = getattr(context, "space_data", None)
        if _ds(space) is None:
            return False
        if auto_load(space):
            cls.poll_message_set("Auto Load Selected Objects is on")
            return False
        return True

    def execute(self, context):
        load_selected(context, context.space_data, add=self.action == "ADD")
        _redraw_editors(context)
        return {'FINISHED'}


class ALLSET_OT_graph_attr_clear(bpy.types.Operator):
    """Clear the attribute filters: every animated attribute is listed again (Maya Show > Attributes > Clear
    Below)"""
    bl_idname = "allset.graph_attr_clear"
    bl_label = "Clear Below"
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        return _ds(getattr(context, "space_data", None)) is not None

    def execute(self, context):
        context.space_data.dopesheet.filter_text = ""
        wm = context.window_manager
        for f in ATTR_FILTERS:
            setattr(wm, "allset_attr_" + f, False)
        return {'FINISHED'}


def _auto_get(_wm):
    return auto_load(getattr(bpy.context, "space_data", None))


def _auto_set(_wm, value):
    space = getattr(bpy.context, "space_data", None)
    if _ds(space) is not None:
        set_auto_load(bpy.context, space, value)
        _redraw_editors(bpy.context)


def _filters_changed(_self, context):
    try:
        sync(context)
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    _redraw_editors(context)
