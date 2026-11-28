# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya object visibility keys: h, Ctrl+H, Alt+H, Shift+H, Ctrl+Shift+H.

Maya hotkeys: h toggles the visibility of the
selection and keeps it selected; Ctrl+H hides the selection, Alt+H the rest;
Shift+H shows the selected hidden objects; Ctrl+Shift+H shows what was hidden last.

Maya's ``visibility`` attribute is ``Object.hide_viewport`` (per object, keyable; the Channel
Box Visibility row reads the same flag): h, Display > Hide / Show and the Channel Box write one
attribute (#26). A display layer's V uses the view-layer flag
(``hide_set``) instead, so it never changes this attribute.

A hidden object can't stay selected in Blender, so Maya's "hidden but still selected" is kept
as an ID property on the object (``KEPT`` = the visible selection left at that moment, as text). ``LAST`` marks
what the latest hide of this operator hid.

Toggle Show/Hide (h) follows Maya's "Toggle Visibility Options": the toggled set is
the selection = the visible selected objects plus the hidden-but-selected ones (``KEPT``). First Selection Independent
(default, 1) flips each object; Dependent (2) gives every one the opposite of the first selected object's visibility.
The saved window value (option_windows.saved("toggle_show_hide")) applies to h and the menu click alike.
"""

import bpy
from bpy.props import EnumProperty

from .. import undo_steps
from .. import i18n
from . import joint_visibility

TOGGLE_KEY = "toggle_show_hide"   # option window key (operators/option_windows_display.py)
KEPT = "allset_kept"              # hidden by h while selected: h / Shift+H bring it back
LAST = "allset_last_hidden"       # hidden by the latest hide: Ctrl+Shift+H brings it back

ACTIONS = (
    ('TOGGLE', "Toggle Visibility", "Maya h: hide the selection and keep it selected, or show it again"),
    ('HIDE', "Hide Selection", "Maya Ctrl+H"),
    ('HIDE_UNSELECTED', "Hide Unselected Objects", "Maya Alt+H"),
    ('SHOW_SELECTED', "Show Selected Objects", "Maya Shift+H"),
    ('SHOW_LAST', "Show Last Hidden", "Maya Ctrl+Shift+H"),
    ('SHOW_ALL', "Show All", "Maya Display > Show > All: every object whose visibility is off"),
    ('HIDE_ALL', "Hide All", "Maya Display > Hide > All: every object"),
    ('HIDE_TYPE', "Hide by Type", "Maya Display > Hide > <type>: every object of the type"),
    ('SHOW_TYPE', "Show by Type", "Maya Display > Show > <type>: every hidden object of the type"),
)

# Maya Display > Hide / Show > <type> (HideNURBSSurfaces, ShowJoints, ...): the kit's node of each Maya type.
GEOMETRY_TYPES = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES', 'POINTCLOUD', 'VOLUME'}


def _deforming(ob):
    from .history import is_deformer
    return ob.type in GEOMETRY_TYPES and any(is_deformer(md) for md in getattr(ob, "modifiers", ()))


def _nonlinear_handles(scene):
    from .history import NONLINEARS
    used = {getattr(md, "origin", None) or getattr(md, "start_position_object", None) or getattr(md, "object", None)
            for o in scene.objects for md in getattr(o, "modifiers", ()) if md.type in NONLINEARS}
    from . import bend_deformer, nonlinear_nodes
    used |= {bend_deformer.handle_of(md) or nonlinear_nodes.handle_of(md) for o in scene.objects
             for md in getattr(o, "modifiers", ())
             if bend_deformer.is_bend(md) or nonlinear_nodes.is_nonlinear(md)}  # a mesh's nonlinear: nodes
    return [ob for ob in scene.objects if ob in used]


def _of_type(*types):
    return lambda scene: [ob for ob in scene.objects if ob.type in types]


def _selector(kind):
    from .by_type import SELECTORS, ik_handles, cluster_handles
    return {
        'GEOMETRY': _of_type(*GEOMETRY_TYPES),
        'NURBS_SURFACES': _of_type('SURFACE'),
        'NURBS_CURVES': _of_type('CURVE'),
        'POLYGONS': _of_type('MESH'),
        'DEFORMING': lambda scene: [ob for ob in scene.objects if _deforming(ob)],
        'KINEMATICS': lambda scene: _of_type('ARMATURE')(scene) + ik_handles(scene),
        'JOINTS': _of_type('ARMATURE'),
        'IK_HANDLES': ik_handles,
        'DEFORMERS': lambda scene: (_of_type('LATTICE')(scene) + cluster_handles(scene)
                                    + _nonlinear_handles(scene)),
        'LATTICES': _of_type('LATTICE'),
        'CLUSTERS': cluster_handles,
        'NONLINEARS': _nonlinear_handles,
        'LIGHTS': _of_type('LIGHT'),
        'CAMERAS': _of_type('CAMERA'),
        'NCLOTHS': SELECTORS['NCLOTHS'],
        'NPARTICLES': SELECTORS['NPARTICLES'],
        'NRIGIDS': SELECTORS['NRIGIDS'],
    }[kind]


KINDS = tuple((k, k.replace("_", " ").title(), "") for k in (
    'NONE', 'GEOMETRY', 'NURBS_SURFACES', 'NURBS_CURVES', 'POLYGONS', 'DEFORMING', 'KINEMATICS', 'JOINTS',
    'IK_HANDLES', 'DEFORMERS', 'LATTICES', 'CLUSTERS', 'NONLINEARS', 'LIGHTS', 'CAMERAS', 'NCLOTHS', 'NPARTICLES',
    'NRIGIDS'))


def of_kind(context, kind):
    """The view layer's objects of a Maya Hide / Show type (scene order, each once)."""
    in_layer = {ob.session_uid for ob in context.view_layer.objects}
    return [ob for ob in dict.fromkeys(_selector(kind)(context.scene)) if ob.session_uid in in_layer]


def _clear(objects, key):
    for ob in objects:
        if key in ob:
            del ob[key]


def _hide(objects, all_objects):
    """Hide ``objects``; they become the "last hidden" set."""
    _clear(all_objects, LAST)
    joint_visibility.clear_last_of(o for o in all_objects if o.type == 'ARMATURE')
    for ob in objects:
        ob.hide_viewport = True
        try:
            ob.select_set(False)
        except RuntimeError:
            pass
        ob[LAST] = True
    return len(objects)


def _signature(view_layer):
    """The visible selection as text: a kept (hidden but selected) object belongs to the selection only
    while the visible selection is still the one left when it was hidden."""
    return "\n".join(sorted(ob.name for ob in view_layer.objects if ob.visible_get() and ob.select_get()))


def _kept(ob, signature):
    value = ob.get(KEPT)
    if value is None:
        return False
    if isinstance(value, str):
        return value == signature
    # a flag from a file saved by an earlier version of the kit records no selection: it belongs to the empty
    # selection only, so h with nothing selected brings the object back and h on another object never does (#336)
    return signature == ""


def _outliner_pick(context, view_layer):
    """Objects picked in the Outliner (a collection row = its objects), or None outside the Outliner."""
    from ..ui import outliner_tree
    if outliner_tree.is_tree(getattr(context, "space_data", None)):
        # the kit's rows: the visible selection and the selection-locked rows picked there (hidden ones are kept)
        locked = [ob for ob in outliner_tree.picked_unselectable(context) if not ob.hide_viewport]
        if not locked:
            return None
        sel = [ob for ob in view_layer.objects if ob is not None and ob.visible_get() and ob.select_get()]
        return sel + [ob for ob in locked if ob not in sel]
    ids = getattr(context, "selected_ids", None)
    if not ids:
        return None
    in_layer = {ob.session_uid for ob in view_layer.objects}
    out, seen = [], set()
    for item in ids:
        if isinstance(item, bpy.types.Object):
            obs = (item,)
        elif isinstance(item, bpy.types.Collection):
            obs = item.all_objects
        else:
            continue
        for ob in obs:
            if ob.session_uid in in_layer and ob.session_uid not in seen:
                seen.add(ob.session_uid)
                out.append(ob)
    return out or None


def _show(objects, view_layer, select=True):
    shown = 0
    for ob in objects:
        ob.hide_viewport = False
        for key in (KEPT, LAST):
            if key in ob:
                del ob[key]
        if not select:
            shown += 1
            continue
        try:
            ob.select_set(True)
        except RuntimeError:   # not selectable in this view layer
            continue
        view_layer.objects.active = view_layer.objects.active or ob
        shown += 1
    return shown


def toggle_dependent():
    """The saved First Selection of Maya's Toggle Visibility Options: True = Dependent (default Independent)."""
    from . import option_windows
    v = option_windows.saved(TOGGLE_KEY) or {}
    return v.get("first_selection") == "Dependent"


def _first(objects, active):
    from .mesh_maya import _first_selected
    return _first_selected(objects, active)


def toggle(context, dependent=False):
    """Maya Toggle Visibility (h) on the selection (visible selected + hidden kept, or the rows picked in
    the Outliner). Returns the count."""
    vl = context.view_layer
    objs = list(vl.objects)
    members = _outliner_pick(context, vl)
    if members is None:
        selected = [ob for ob in objs if ob.visible_get() and ob.select_get()]
        signature = _signature(vl)
        kept = [ob for ob in objs if ob.hide_viewport and _kept(ob, signature)]
        members = selected + [ob for ob in kept if ob not in selected]
    if not members:
        return 0
    if dependent:
        first = _first(members, vl.objects.active if vl.objects.active in members else None)
        show = first.hide_viewport            # every member gets the opposite of the first one's visibility
        to_hide = [] if show else members
        to_show = members if show else []
    else:
        to_hide = [ob for ob in members if not ob.hide_viewport]
        to_show = [ob for ob in members if ob.hide_viewport]
    _clear(objs, KEPT)                        # the selection is now ``members``
    if to_hide:
        _hide(to_hide, objs)
    if to_show:                               # hidden by h while selected: they come back still selected
        _show([ob for ob in to_show if ob.hide_viewport], vl)
    signature = _signature(vl)
    for ob in members:                        # hidden members stay selected (Maya)
        if ob.hide_viewport:
            ob[KEPT] = signature
    return len(members)


def apply(context, action, dependent=None, kind='NONE'):
    """Run ``action`` on the view layer (``kind``: the type of HIDE_TYPE / SHOW_TYPE); returns the number of
    objects changed."""
    if context.mode in joint_visibility.JOINT_MODES:
        return _apply_joints(context, action, kind)
    vl = context.view_layer
    objs = list(vl.objects)
    selected = [ob for ob in objs if ob.visible_get() and ob.select_get()]
    hidden = [ob for ob in objs if ob.hide_viewport]
    if action == 'TOGGLE':
        return toggle(context, toggle_dependent() if dependent is None else dependent)
    if action == 'HIDE':
        return _hide(selected, objs)
    if action == 'HIDE_UNSELECTED':
        # the selection's own hierarchy stays (its children aren't "unselected" objects, and hiding a
        # selected object's parent would hide the selection: Maya draws a node only under visible parents)
        from .dag import hierarchy
        keep = {o.session_uid for o in hierarchy(selected)}
        for ob in selected:
            p = ob.parent
            while p is not None:
                keep.add(p.session_uid)
                p = p.parent
        return _hide([ob for ob in objs if ob.visible_get() and not ob.select_get() and ob.session_uid not in keep],
                     objs)
    if action == 'SHOW_SELECTED':
        act = vl.objects.active
        return _show([ob for ob in hidden if KEPT in ob or ob == act], vl)
    if action == 'SHOW_LAST':        # the last hide may have been joints (Pose / Edit mode)
        return _show([ob for ob in hidden if LAST in ob], vl) + joint_visibility.show_last(context, in_mode=False)
    if action == 'SHOW_ALL':         # hidden joints too
        return _show(hidden, vl, select=False) + joint_visibility.show_all(context)
    if action == 'HIDE_ALL':
        return _hide([ob for ob in objs if not ob.hide_viewport], objs)
    if action == 'HIDE_TYPE':
        return _hide([ob for ob in of_kind(context, kind) if not ob.hide_viewport], objs)
    if action == 'SHOW_TYPE':
        n = _show([ob for ob in of_kind(context, kind) if ob.hide_viewport], vl, select=False)
        return n + (joint_visibility.show_all(context) if kind in joint_visibility.JOINT_KINDS else 0)
    raise ValueError(action)


def _apply_joints(context, action, kind):
    """``apply`` in Pose / Edit mode of a skeleton: the actions work on joints (a hidden joint hides the joints
    below it); objects other than the skeletons being edited follow the Object Mode rules where Maya's command
    covers them too (Hide Unselected, Hide All, Show All, by type)."""
    vl = context.view_layer
    objs = list(vl.objects)
    editing = {o.session_uid for o in joint_visibility.armatures_in_mode(context)}
    others = [ob for ob in objs if ob.session_uid not in editing]
    hidden = [ob for ob in others if ob.hide_viewport]
    if action == 'SHOW_LAST':
        return _show([ob for ob in hidden if LAST in ob], vl) + joint_visibility.show_last(context, in_mode=False)
    if action == 'SHOW_ALL':
        return _show(hidden, vl, select=False) + joint_visibility.show_all(context)
    if action == 'SHOW_TYPE':
        n = _show([ob for ob in of_kind(context, kind) if ob.hide_viewport and ob.session_uid not in editing], vl,
                  select=False)
        return n + (joint_visibility.show_all(context) if kind in joint_visibility.JOINT_KINDS else 0)
    if action in {'HIDE', 'TOGGLE'}:
        if joint_visibility.selection_count(context):
            _clear(objs, LAST)           # the joints are the new "last hidden"
        return joint_visibility.hide(context, action)
    if action == 'SHOW_SELECTED':
        return joint_visibility.hide(context, action)
    if action == 'HIDE_UNSELECTED':
        from .dag import hierarchy
        selected = [ob for ob in objs if ob.visible_get() and ob.select_get()]
        keep = {o.session_uid for o in hierarchy(selected)} | editing
        for ob in selected:
            p = ob.parent
            while p is not None:
                keep.add(p.session_uid)
                p = p.parent
        n = _hide([ob for ob in others if ob.visible_get() and not ob.select_get() and ob.session_uid not in keep],
                  objs)
        return n + joint_visibility.hide(context, action)
    if action == 'HIDE_ALL':
        n = _hide([ob for ob in others if not ob.hide_viewport], objs)
        return n + joint_visibility.hide(context, action)
    if action == 'HIDE_TYPE':
        n = _hide([ob for ob in of_kind(context, kind) if not ob.hide_viewport and ob.session_uid not in editing],
                  objs)
        return n + (joint_visibility.hide(context, action) if kind in joint_visibility.JOINT_KINDS else 0)
    raise ValueError(action)


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_visibility(bpy.types.Operator):
    """Maya object visibility (h, Ctrl+H, Alt+H, Shift+H, Ctrl+Shift+H)"""
    bl_idname = "allset.visibility"
    bl_label = "Maya Visibility"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(name="Action", items=ACTIONS, default='TOGGLE')
    kind: EnumProperty(name="Type", items=KINDS, default='NONE', options={'SKIP_SAVE'})
    # Toggle: Maya's First Selection; SAVED = the Toggle Visibility Options window's value
    behaviour: EnumProperty(name="First Selection", options={'SKIP_SAVE', 'HIDDEN'}, default='SAVED', items=(
        ('SAVED', "Saved", ""), ('INDEPENDENT', "Independent", ""), ('DEPENDENT', "Dependent", "")))

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return dict((a[0], a[2]) for a in ACTIONS)[props.action]

    @classmethod
    def poll(cls, context):
        return context.view_layer is not None and (context.mode == 'OBJECT' or
                                                   context.mode in joint_visibility.JOINT_MODES)

    def execute(self, context):
        vl = context.view_layer
        if context.mode in joint_visibility.JOINT_MODES:
            had_selection = joint_visibility.selection_count(context) > 0
        else:
            had_selection = any(ob.visible_get() and ob.select_get() for ob in vl.objects)
        changed = apply(context, self.action,
                        None if self.behaviour == 'SAVED' else self.behaviour == 'DEPENDENT', self.kind)
        from . import dag
        dag.sync(context.scene, vl)          # a hidden parent hides its children (Maya)
        text = message(self.action, had_selection, changed)
        if text:
            from ..ui import view_message
            view_message.show(context, text)
        return {'FINISHED'}


def message(action, had_selection, changed):
    """Maya's in-view message for a visibility action, or None (Maya's Hide / Toggle
    Visibility messages)."""
    if action == 'HIDE':
        if had_selection:
            return ("Selection <hl>hidden</hl>.\n"
                    "To show it again, select it in the Outliner and press <hl>Shift+H</hl>.")
        return "Nothing is selected to hide."
    if action == 'HIDE_UNSELECTED':
        if changed:
            return ("Unselected objects <hl>hidden</hl>.\n"
                    "To show them, select them in the Outliner and press <hl>Shift+H</hl>.")
        return "No unselected objects to hide."
    if action == 'TOGGLE' and not changed:
        return "Nothing selected to toggle."
    return None


def reveal_components(meshes):
    """Unhide every vertex, edge and face of ``meshes`` (mesh data, object mode); returns how many had hidden ones."""
    n = 0
    for me in meshes:
        changed = False
        for elems in (me.vertices, me.edges, me.polygons):
            flags = [False] * len(elems)
            elems.foreach_get("hide", flags)
            if any(flags):
                elems.foreach_set("hide", [False] * len(elems))
                changed = True
        if changed:
            me.update()
            n += 1
    return n


class ALLSET_OT_show_all_components(bpy.types.Operator):
    """Show every hidden vertex, edge and face of every mesh in the scene, selected or not (Maya Display > Show >
    All Components, also from object mode)"""
    bl_idname = "allset.show_all_components"
    bl_label = "All Components"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        editing = {ob.data for ob in context.objects_in_mode_unique_data} if context.mode == 'EDIT_MESH' else set()
        if editing:
            bpy.ops.mesh.reveal(select=False)         # the meshes in Edit Mode keep their data in the edit mesh
        others = {ob.data for ob in context.view_layer.objects if ob.type == 'MESH'} - editing
        reveal_components(m for m in others if not m.library)
        return {'FINISHED'}


classes = (ALLSET_OT_visibility, ALLSET_OT_show_all_components)
