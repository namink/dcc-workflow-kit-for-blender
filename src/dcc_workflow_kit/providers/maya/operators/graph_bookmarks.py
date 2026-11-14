# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Graph Editor List > Bookmarks: keep the objects (or the curves) the Graph Editor shows as a bookmark set.

Like Maya a bookmark is a set named Bookmark, Bookmark1, Bookmark2 ... (no name is asked):

- Bookmark Current Objects makes a set of the objects the Graph Editor lists now.
- Bookmark Selected Curves makes a set of the selected curves' objects that remembers those curves.
- Remove All Bookmarks deletes the bookmark sets.

The sets are kit sets (``operators/sets``: Outliner set rows, saved with the file) marked with the set text
``TEXT``; a curve bookmark keeps its curves in the collection ID property ``CURVES`` ("object<TAB>path<TAB>index").
Selecting a bookmark set selects its objects, so an auto-loading Graph Editor shows them, like picking a bookmark in
Maya. The List > Bookmarks menu also lists the bookmarks: choosing one loads it into that Graph Editor like List >
Load Selected Objects (a curve bookmark shows only its curves).
"""

import bpy
from bpy.props import EnumProperty, StringProperty

from . import sets
from .. import i18n

TEXT = "bookmarkAnimCurves"
CURVES = "allset_bookmark_curves"
LOADED_MARK = "allset_bookmark"      # on the editor's kit list: the bookmark last loaded into it


def bookmarks(scene=None):
    """The bookmark sets, in creation order."""
    return [c for c in sets.all_sets() if c.get(sets.TEXT) == TEXT]


def curves_of(coll):
    out = []
    for text in coll.get(CURVES, ()):
        ob, path, index = text.split("\t")
        out.append((ob, path, int(index)))
    return out


def next_name():
    """Maya: Bookmark, then Bookmark1, Bookmark2 ..."""
    used = {c.name for c in bpy.data.collections}
    if "Bookmark" not in used:
        return "Bookmark"
    n = 1
    while f"Bookmark{n}" in used:
        n += 1
    return f"Bookmark{n}"


def _space(context):
    from ..ui import editor_chrome
    space = getattr(context, "space_data", None)
    return space if editor_chrome.is_graph(space) else None


def current_objects(context, space):
    """Objects the Graph Editor lists now."""
    from ..ui import editor_chrome
    return list(editor_chrome.listed_objects(context, space))


def selected_curves(context):
    """[(object, data path, index)] of the selected curves the Graph Editor shows."""
    out = []
    for fc in getattr(context, "visible_fcurves", None) or ():
        if not fc.select:
            continue
        owner = fc.id_data
        if isinstance(owner, bpy.types.Action):
            obs = [ob for ob in context.scene.objects if ob.animation_data and ob.animation_data.action == owner]
        else:
            obs = [owner] if isinstance(owner, bpy.types.Object) else []
        out += [(ob.name, fc.data_path, fc.array_index) for ob in obs]
    return out


def make(objects, curves=()):
    coll = sets.create(next_name(), objects, text=TEXT)
    if curves:
        coll[CURVES] = [f"{o}\t{p}\t{i}" for o, p, i in curves]
    return coll


def load(context, space, coll):
    """Show a bookmark in the Graph Editor: its objects as the loaded list; a curve bookmark shows only its curves."""
    from ..ui import editor_chrome as ec
    curves = curves_of(coll)
    names = [ob.name for ob in sets.members(coll, context.scene)]
    ds = ec._ds(space)
    lst = ec.kit_list(space) or ec._new_list()
    lst[ec.LOADED] = names
    lst[LOADED_MARK] = coll.name
    lst[ec.BONES] = []
    lst[ec.AUTO] = False
    ds.filter_collection = lst
    ds.show_only_selected = False
    ec.sync_space(context, space)
    if curves:
        from .. import compat
        keep = set(curves)
        for n in names:
            for fc in compat.id_fcurves(context.scene.objects[n]):
                shown = (n, fc.data_path, fc.array_index) in keep
                fc.hide = not shown
                fc.select = shown
    return names


def loaded(context, space):
    """The bookmark set the editor shows, like a selected set in Maya's Graph Editor list: the one last loaded, while
    the list still holds just its objects; else None."""
    from ..ui import editor_chrome as ec
    lst = ec.kit_list(space)
    names = ec.loaded_names(space)
    if lst is None or names is None:
        return None
    coll = bpy.data.collections.get(lst.get(LOADED_MARK, ""))
    if coll is None or coll.get(sets.TEXT) != TEXT:
        return None
    return coll if sorted(ob.name for ob in sets.members(coll, context.scene)) == sorted(names) else None


class ALLSET_OT_graph_bookmark(bpy.types.Operator):
    """Maya Graph Editor List > Bookmarks"""
    bl_idname = "allset.graph_bookmark"
    bl_label = "Bookmark"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(
        ('OBJECTS', "Bookmark Current Objects", "Keep the objects the Graph Editor lists now as a bookmark set"),
        ('CURVES', "Bookmark Selected Curves", "Keep the selected curves as a bookmark set"),
        ('LOAD', "Load Bookmark", "Show the bookmark's objects (or curves) in the Graph Editor"),
        ('REMOVE_ALL', "Remove All Bookmarks", "Delete every Graph Editor bookmark set")),
        default='OBJECTS', options={'SKIP_SAVE', 'HIDDEN'})
    name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return props.bl_rna.properties["action"].enum_items[props.action].description

    @classmethod
    def poll(cls, context):
        return _space(context) is not None

    def execute(self, context):
        space = _space(context)
        if self.action == 'REMOVE_ALL':
            for coll in bookmarks():
                sets.delete(coll)
        elif self.action == 'LOAD':
            coll = next((c for c in bookmarks() if c.name == self.name), None)
            if coll is None:
                return {'CANCELLED'}
            load(context, space, coll)
        elif self.action == 'OBJECTS':
            obs = current_objects(context, space)
            if not obs:
                self.report({'WARNING'}, "Select objects to bookmark")
                return {'CANCELLED'}
            make(obs)
        else:
            curves = selected_curves(context)
            if not curves:
                self.report({'WARNING'}, "Select curves to bookmark")
                return {'CANCELLED'}
            names = list(dict.fromkeys(c[0] for c in curves))
            make([context.scene.objects[n] for n in names], curves)
        from ..ui import editor_chrome
        editor_chrome._redraw_editors(context)
        return {'FINISHED'}


class ALLSET_MT_graph_bookmarks(bpy.types.Menu):
    """Maya Graph Editor List > Bookmarks: the bookmark commands, then the bookmark sets to load"""
    bl_label = "Bookmarks"

    def draw(self, context):
        lay = self.layout
        for action, label in (('OBJECTS', "Bookmark Current Objects"), ('CURVES', "Bookmark Selected Curves"),
                              ('REMOVE_ALL', "Remove All Bookmarks")):
            lay.operator("allset.graph_bookmark", text=label).action = action
        items = bookmarks()
        if items:
            lay.separator()
            for coll in items:
                op = lay.operator("allset.graph_bookmark", text=coll.name, translate=False,
                                  icon='FCURVE' if coll.get(CURVES) else 'OBJECT_DATA')
                op.action, op.name = 'LOAD', coll.name


classes = (ALLSET_OT_graph_bookmark, ALLSET_MT_graph_bookmarks)
