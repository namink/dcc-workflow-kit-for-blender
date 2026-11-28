# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Layer Editor (Display Layers) wrapped on collections.

Maya's Layer Editor.
A display layer is a child collection of a "Display Layers" collection that
is excluded from every view layer, so layers are membership lists that do
not change the scene hierarchy or visibility by themselves. The layer state
is an override on its member objects that never changes their own Maya
attributes (#26; the object's visibility is ``hide_viewport``):
  V (visible)  -> the view-layer flag (``hide_set``)
  T (template) -> unselectable, wireframe; R (reference) -> unselectable
                  (the member's own display type / selectability are kept in ``OWN`` and put back)
  P (playback) -> off: members hidden (view-layer flag) while animation plays
An object belongs to at most one display layer, like Maya. Like V, T and R reach every object below a member
(``operators/dag.py`` marks those with ``INHERITED``); a Template or Reference above wins over the object's own layer.

A joint picked in a view is a member of its own (``ui/layer_joints.py``): the layer's state reaches the joint and
everything below it through the kit's joint drawing and picking, never through the skeleton object; a kit skeleton
picked as a whole stands for its root joints. Layers of older files that hold a skeleton object keep it.

Code: ``display_layers`` (layer data, override, playback), ``layer_editor_anim`` (Anim tab); this module keeps the
operators, the Display tab (list, menus, RMB menu), the dock panel and register / unregister; the names used
elsewhere are importable from here too.
"""


import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty

from .. import compat, i18n
from . import chrome, layer_joints
# the split-out parts, also read through this module by other UI and the tests
from .display_layers import (ROOT_NAME, TYPES, TYPE_LETTER, ALLSET_PG_layer, root, layers,  # noqa: F401
                             display_order, move_layer, layer_of, next_layer_name, OWN, INHERITED, _layer_hide,
                             _restore_display, display_kind, apply_display, apply_object, apply_layer,
                             selected_nodes, add_nodes, remove_nodes, new_layer, add_objects, remove_objects,
                             empty_layer, delete_layer, active_layer, on_playback_pre, on_playback_post)
from .layer_editor_anim import (ANIM_LAYER_MENU, ANIM_TOOLBAR, ANIM_TOGGLES, GREY_WITH_BASE,  # noqa: F401
                                ANIM_ROW_MENU, ROW_ON_BASE, draw_anim_layer_items, draw_anim_layer_mode,
                                anim_layer_row, draw_anim_row_menu, anim_display_order, draw_anim_tab)


# --- operators -----------------------------------------------------------------------------------

class _LayerOp:
    bl_options = {'REGISTER', 'UNDO'}


class ALLSET_OT_layer_new(_LayerOp, bpy.types.Operator):
    """Create a display layer (optionally with the selected objects)"""
    bl_idname = "allset.layer_new"
    bl_label = "New Layer"

    selected: BoolProperty(name="Assign Selected", default=False)

    def execute(self, context):
        nodes = selected_nodes(context) if self.selected else ((), None, ())
        coll = new_layer(context.scene, *nodes)
        context.scene.allset_layer_index = layers(context.scene).index(coll)
        return {'FINISHED'}


class ALLSET_OT_layer_assign(_LayerOp, bpy.types.Operator):
    """Add (or remove) the selected objects to the active display layer"""
    bl_idname = "allset.layer_assign"
    bl_label = "Add Selected Objects"

    remove: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return active_layer(context) is not None

    def execute(self, context):
        coll = active_layer(context)
        fn = remove_nodes if self.remove else add_nodes
        fn(context.scene, coll, *selected_nodes(context))
        return {'FINISHED'}


class ALLSET_OT_layer_select(_LayerOp, bpy.types.Operator):
    """Select the objects of the active display layer"""
    bl_idname = "allset.layer_select"
    bl_label = "Select Objects"

    @classmethod
    def poll(cls, context):
        return active_layer(context) is not None

    def execute(self, context):
        coll = active_layer(context)
        select_members(context, coll, layer_joints.members(coll, context.scene))
        return {'FINISHED'}


def select_members(context, coll, joints):
    """Maya Select Objects: only the members are picked (not what is below them), also in a Template or Reference
    layer or a hidden one. Objects Blender can't select (Template / Reference, hidden) stay picked the way the kit
    Outliner keeps them (``outliner_tree_select._keep_hidden``). Member joints alone: Pose Mode on their skeletons, the last
    member the lead; with objects the skeletons are selected in Object Mode with the member joints picked on them."""
    from ..operators import joint_selection
    from . import outliner_tree
    from .channel_box import set_bone_selected
    if joints or context.mode != 'OBJECT':
        joint_selection.leave(context, clear_selection=True)
    view_layer = context.view_layer
    objects = [ob for ob in view_layer.objects if ob.name in coll.objects]
    locked = [ob for ob in objects if outliner_tree.unselectable(ob)]
    for ob in view_layer.objects:
        if ob.select_get():
            ob.select_set(False)
    last = None
    for ob in (*(o for o in objects if o not in locked), *joints):
        try:
            ob.select_set(True)
            last = ob
        except RuntimeError:           # not in the view layer / hidden
            continue
    for arm, names in joints.items():
        for pb in arm.pose.bones:
            set_bone_selected(pb, pb.name in names)
        arm.data.bones.active = arm.data.bones.get(names[-1])
    view_layer.objects.active = last if last is not None else (locked[-1] if locked else None)
    outliner_tree._keep_hidden(context, locked, replace=True)
    if not objects and last is not None and last.type == 'ARMATURE':
        try:
            bpy.ops.object.mode_set(mode='POSE')    # every selected skeleton (several: multi-object Pose Mode)
        except RuntimeError:                         # a skeleton an older layer hides: the joints stay picked
            pass


class ALLSET_OT_layer_delete(_LayerOp, bpy.types.Operator):
    """Delete the active display layer (its objects stay, back to normal display)"""
    bl_idname = "allset.layer_delete"
    bl_label = "Delete Layer"

    @classmethod
    def poll(cls, context):
        return active_layer(context) is not None

    def execute(self, context):
        delete_layer(context.scene, active_layer(context))
        context.scene.allset_layer_index = max(0, context.scene.allset_layer_index - 1)
        return {'FINISHED'}


class ALLSET_OT_layer_cycle_type(_LayerOp, bpy.types.Operator):
    """Cycle display type: normal -> template (T) -> reference (R)"""
    bl_idname = "allset.layer_cycle_type"
    bl_label = "Cycle Layer Type"

    layer: bpy.props.StringProperty()

    def execute(self, context):
        coll = bpy.data.collections.get(self.layer)
        if coll is None:
            return {'CANCELLED'}
        order = [t[0] for t in TYPES]
        st = coll.allset_layer
        st.display_type = order[(order.index(st.display_type) + 1) % len(order)]
        return {'FINISHED'}


class ALLSET_OT_layer_toggle(_LayerOp, bpy.types.Operator):
    """Toggle the layer's visibility (V) or playback (P)"""
    bl_idname = "allset.layer_toggle"
    bl_label = "Toggle Layer"

    layer: bpy.props.StringProperty()
    attr: EnumProperty(items=(("visible", "Visible", "Maya V"), ("playback", "Playback", "Maya P")))

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return ("Visibility (Maya V): show or hide the layer's objects" if props.attr == "visible" else
                "Playback (Maya P): show the layer's objects while animation plays")

    def execute(self, context):
        coll = bpy.data.collections.get(self.layer)
        if coll is None:
            return {'CANCELLED'}
        st = coll.allset_layer
        setattr(st, self.attr, not getattr(st, self.attr))
        return {'FINISHED'}


class ALLSET_OT_layer_move(_LayerOp, bpy.types.Operator):
    """Move the selected layer up or down in the list (Maya Layer Editor arrows)"""
    bl_idname = "allset.layer_move"
    bl_label = "Move Layer"

    direction: EnumProperty(items=(("UP", "Up", "Move selection up in list"),
                                   ("DOWN", "Down", "Move selection down in list")))

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return f"Move selection {props.direction.lower()} in list"

    @classmethod
    def poll(cls, context):
        return active_layer(context) is not None

    def execute(self, context):
        coll = active_layer(context)
        move_layer(context.scene, coll, -1 if self.direction == "UP" else 1)
        context.scene.allset_layer_index = layers(context.scene).index(coll)
        return {'FINISHED'}


class ALLSET_OT_layer_empty(_LayerOp, bpy.types.Operator):
    """Remove every object from the selected layer (Maya Empty the Layer)"""
    bl_idname = "allset.layer_empty"
    bl_label = "Empty the Layer"

    @classmethod
    def poll(cls, context):
        return active_layer(context) is not None

    def execute(self, context):
        empty_layer(context.scene, active_layer(context))
        return {'FINISHED'}


class ALLSET_OT_layer_set_type(_LayerOp, bpy.types.Operator):
    """Set the selected layer's display type (Maya Set Selected Layers)"""
    bl_idname = "allset.layer_set_type"
    bl_label = "Set Layer Type"

    display_type: EnumProperty(items=TYPES)

    @classmethod
    def poll(cls, context):
        return active_layer(context) is not None

    def execute(self, context):
        active_layer(context).allset_layer.display_type = self.display_type
        return {'FINISHED'}


# --- UI ------------------------------------------------------------------------------------------

# Maya layer row: three 20x14 boxes V / P / type with 3 px gaps, a 16x14
# colour swatch, then the name as plain text, rows 20 px: boxes one UI unit wide in a left-aligned row (natural
# widths, small gaps).
BOX_UNITS = 1.4
SWATCH_UNITS = 0.9


class ALLSET_UL_layers(bpy.types.UIList):
    """Maya display layer rows: newest on top (``order``), click = select the layer, double-click = rename"""

    def filter_items(self, context, data, propname):
        items = list(getattr(data, propname))
        flags = [self.bitflag_filter_item if c.allset_layer.is_layer else 0 for c in items]
        # neworder[i] = display position of item i: highest order first (Maya lists the newest layer on top)
        ranked = sorted(range(len(items)), key=lambda i: (-items[i].allset_layer.order, -i))
        neworder = [0] * len(items)
        for pos, i in enumerate(ranked):
            neworder[i] = pos
        return flags, neworder

    def draw_filter(self, context, layout):
        pass   # Maya's layer list has no filter / sort options

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        st = item.allset_layer
        row = layout.row(align=False)
        boxes = row.row(align=True)
        boxes.alignment = 'LEFT'           # natural widths: fixed boxes, the name takes the rest
        for attr, letter in (("visible", "V"), ("playback", "P")):
            cell = boxes.row(align=True)
            cell.ui_units_x = BOX_UNITS
            op = cell.operator("allset.layer_toggle", text=letter if getattr(st, attr) else " ")
            op.layer, op.attr = item.name, attr
            boxes.separator(factor=0.3)
        cell = boxes.row(align=True)
        cell.ui_units_x = BOX_UNITS
        cell.operator("allset.layer_cycle_type", text=TYPE_LETTER[st.display_type]).layer = item.name
        sw = boxes.row(align=True)
        sw.ui_units_x = SWATCH_UNITS
        sw.prop(item, "color_tag", text="", icon_only=True, emboss=False)
        row.prop(item, "name", text="", emboss=False)


LAYER_MENU = (   # Maya's layer RMB menu
    ("allset.layer_assign", "Add Selected Objects", {"remove": False}),
    ("allset.layer_assign", "Remove Selected Objects", {"remove": True}),
    ("allset.layer_select", "Select Objects", {}),
    None,
    ("allset.layer_set_type", "Set Normal", {"display_type": "NORMAL"}),
    ("allset.layer_set_type", "Set Template", {"display_type": "TEMPLATE"}),
    ("allset.layer_set_type", "Set Reference", {"display_type": "REFERENCE"}),
    None,
    ("allset.layer_empty", "Empty the Layer", {}),
    ("allset.layer_delete", "Delete Layer", {}),
)


def draw_layer_items(layout):
    for entry in LAYER_MENU:
        if entry is None:
            layout.separator()
            continue
        idname, text, props = entry
        op = layout.operator(idname, text=text)
        for k, v in props.items():
            setattr(op, k, v)


class ALLSET_MT_le_layers(bpy.types.Menu):
    """Maya Layer Editor Layers menu"""
    bl_label = "Layers"

    def draw(self, context):
        lay = self.layout
        if context.window_manager.allset_le_tab == 'ANIM':
            draw_anim_layer_items(lay, context)
            draw_anim_layer_mode(lay, context)
            return
        lay.operator("allset.layer_new", text="Create Empty Layer").selected = False
        lay.operator("allset.layer_new", text="Create Layer from Selected").selected = True
        lay.separator()
        draw_layer_items(lay)


def is_layer_button(context):
    """The button under the mouse belongs to a display layer row (for its RMB menu): one of its boxes, its
    name / colour, or the row itself (Blender's list row button, whose property is the list's active index)."""
    op = getattr(context, "button_operator", None)
    if op is not None and op.bl_rna.identifier in ("ALLSET_OT_layer_toggle", "ALLSET_OT_layer_cycle_type"):
        return True
    ptr = getattr(context, "button_pointer", None)
    if isinstance(ptr, bpy.types.Collection) and getattr(ptr.allset_layer, "is_layer", False):
        return True
    return is_layer_row(context)


def is_layer_row(context):
    prop = getattr(context, "button_prop", None)
    return prop is not None and getattr(prop, "identifier", "") == "allset_layer_index"


def draw_button_menu(self, context):
    """Maya's layer RMB menu on top of Blender's button context menu (a C menu, not a keymap item)."""
    row = anim_layer_row(context)
    if row is not None:
        draw_anim_row_menu(self.layout, context, row)
        self.layout.separator()
        return
    if not is_layer_button(context):
        return
    if is_layer_row(context):
        # the row button carries no layer: the items act on the current (highlighted) layer, named here
        sel = active_layer(context)
        if sel is not None:
            self.layout.label(text=sel.name, icon='OUTLINER_COLLECTION')
    draw_layer_items(self.layout)
    self.layout.separator()


class ALLSET_MT_le_options(bpy.types.Menu):
    """Maya Layer Editor Options menu"""
    bl_label = "Options"

    def draw(self, context):
        for label in ("Make New Layers Current", "Add New Objects to Current Layer", "Auto Overwrite",
                      "Show Namespace"):
            chrome.grey(self.layout, label)


class ALLSET_MT_le_help(bpy.types.Menu):
    bl_label = "Help"

    def draw(self, context):
        self.layout.operator("wm.url_open", text="Help on Display Layers (Blender collections)").url = \
            compat.docs_url(HELP_URL)


HELP_URL = "https://docs.blender.org/manual/en/5.2/scene_layout/collections/collections.html"
# Maya Layer Editor: tabs Display / Anim, menu bar Layers / Options / Help,
# toolbar on the right.
TABS = (('DISPLAY', "Display", "Display layers"), ('ANIM', "Anim", "Animation layers"))
MENU_BAR = (("Layers", "ALLSET_MT_le_layers"), ("Options", "ALLSET_MT_le_options"), ("Help", "ALLSET_MT_le_help"))


class ALLSET_PT_layer_editor(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Channel Box / Layer Editor"   # not registered (ui/maya_dock.py draws it)
    bl_label = "Layer Editor"
    bl_order = 1
    bl_options = {'HIDE_HEADER'}   # Maya: tabs + menu bar, no collapsible panel title

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        wm = context.window_manager
        sdk = getattr(wm, "allset_sdk", None)
        if sdk is not None and sdk.open:
            from . import set_driven_key   # the Set Driven Key window takes the Layer Editor's place
            set_driven_key.draw(layout, context)
            return
        layout.separator(type='LINE')   # Maya's splitter between Channel Box and Layer Editor
        # Maya: slim tabs on the left, not a
        # full-width switch
        tabs = layout.row(align=True)
        tabs.alignment = 'LEFT'
        tabs.scale_y = 0.9
        for ident, label, _tip in TABS:
            tabs.prop_enum(wm, "allset_le_tab", ident, text=f"  {i18n.iface(label)}  ", translate=False)
        chrome.menu_bar(layout, MENU_BAR)
        if wm.allset_le_tab == 'ANIM':
            draw_anim_tab(layout, context)    # Maya animation layers on NLA tracks
            return
        # Maya's toolbar, right-aligned, frameless icon buttons in Maya's order: move up, move down, create
        # empty layer, create layer from selected (Maya Layer Editor)
        row = layout.row(align=True)
        row.alignment = 'RIGHT'
        row.emboss = 'NONE'
        # kit-drawn Maya icons (#23; Blender's icon until the glyph is made)
        from .kit_icons import button
        for direction, icon in (("UP", 'TRIA_UP_BAR'), ("DOWN", 'TRIA_DOWN_BAR')):
            button(row, "allset.layer_move", f"layer:{direction}", icon, text="").direction = direction
        button(row, "allset.layer_new", "layer:NEW_EMPTY", 'ADD', text="").selected = False
        button(row, "allset.layer_new", "layer:NEW_SELECTED", 'COLLECTION_NEW', text="").selected = True
        # Maya shows the (empty) layer list area even with no layers: an empty
        # list over the scene collection's children (the filter keeps display layers only).
        r = root(scene)
        owner = r if r is not None else scene.collection
        layout.template_list("ALLSET_UL_layers", "", owner, "children", scene, "allset_layer_index",
                             rows=list_rows(context), sort_lock=True)


def list_rows(context):
    """Layer list rows that fill the dock to the bottom (Maya's Layer Editor pane is the dock's lower part,
    cb_pane.CB_SHARE)."""
    from .channel_box import _round_half_up, cb_share
    region = context.region
    if region is None or region.type not in {'UI', 'WINDOW'}:   # the dock is a Properties WINDOW
        return 8
    u = _round_half_up(18.0 * context.preferences.system.ui_scale) + 2 * context.preferences.system.pixel_size
    return max(3, int((1.0 - cb_share(region, u)) * region.height / max(u, 1)) - 5)


classes = (ALLSET_PG_layer, ALLSET_OT_layer_new, ALLSET_OT_layer_assign, ALLSET_OT_layer_select,
           ALLSET_OT_layer_delete, ALLSET_OT_layer_cycle_type, ALLSET_OT_layer_toggle, ALLSET_OT_layer_move,
           ALLSET_OT_layer_empty, ALLSET_OT_layer_set_type, ALLSET_UL_layers,
           ALLSET_MT_le_layers, ALLSET_MT_le_options, ALLSET_MT_le_help)
# ALLSET_PT_layer_editor is drawn under the Channel Box by ui/maya_dock.py, not registered as a panel.


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Collection.allset_layer = PointerProperty(type=ALLSET_PG_layer)
    layer_joints.register()
    bpy.types.Scene.allset_layer_index = IntProperty(options={'HIDDEN'})
    bpy.types.WindowManager.allset_le_tab = EnumProperty(name="Layer Editor Tab", items=TABS,
                                                           options={'SKIP_SAVE'})
    bpy.app.handlers.animation_playback_pre.append(on_playback_pre)
    bpy.app.handlers.animation_playback_post.append(on_playback_post)
    bpy.types.UI_MT_button_context_menu.prepend(draw_button_menu)


def unregister():
    bpy.types.UI_MT_button_context_menu.remove(draw_button_menu)
    bpy.app.handlers.animation_playback_post.remove(on_playback_post)
    bpy.app.handlers.animation_playback_pre.remove(on_playback_pre)
    del bpy.types.WindowManager.allset_le_tab
    del bpy.types.Scene.allset_layer_index
    layer_joints.unregister()
    del bpy.types.Collection.allset_layer
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
