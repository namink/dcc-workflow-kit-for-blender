# SPDX-License-Identifier: GPL-3.0-or-later
"""Skin Tools window: skin weight layers on a kit skin, like Maya's Skin Tools.

A ``marked_window`` kind "SKIN_TOOLS" (a Properties Tool tab in its own window) drawn by ``ALLSET_PT_skin_tools``:
the skinned mesh and Initialize / Delete Skin Layers, the Layers list (top layer first; add, duplicate, remove,
up / down, Enabled, Opacity, rename), the Influences list (Mask first, then the joints; a click picks what is
painted), the Paint / Set Weights / Mirror tabs and Assign from Closest Joint. The stack and its maths live in
``operators/skin_layers.py`` / ``skin_layers_math.py``.

Once a mesh's layers are initialised, Skin > Paint Skin Weights opens this window instead of starting the classic
paint tool; the window's Paint button paints the active layer.
"""

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty,
                       StringProperty)

from . import marked_window
from ..operators import skin_layers as layers

KIND = "SKIN_TOOLS"
TITLE = "Skin Tools"
TABS = (("PAINT", "Paint", "Paint the active layer"),
        ("SET_WEIGHTS", "Set Weights", "Set, add, scale or smooth weights on the selected vertices"),
        ("MIRROR", "Mirror", "Mirror the active layer from one side of the mesh to the other"))
MODES = (("REPLACE", "Replace", "Set the picked influence (or the mask) to the intensity"),
         ("ADD", "Add", "Add the intensity to the picked influence (or the mask)"),
         ("SCALE", "Scale", "Multiply the picked influence (or the mask) by the intensity"),
         ("SMOOTH", "Smooth", "Blend every influence of the layer (or the mask) toward the neighbouring vertices"))
AXES = (("X", "X", "Mirror across the YZ plane"), ("Y", "Y", "Mirror across the XZ plane"),
        ("Z", "Z", "Mirror across the XY plane"))


def target(context):
    """The skinned mesh the window works on: the active object, else a selected skinned mesh."""
    from ..operators import skin
    try:
        return skin.skinned_mesh(context)
    except AttributeError:
        return None


def redraw(context=None):
    marked_window.redraw(context or bpy.context, KIND)


# --- stored data ----------------------------------------------------------------------------------------------------

def _layer_changed(self, context):
    ob = self.id_data
    try:
        layers.recomposite(ob)
    except (AttributeError, ReferenceError, RuntimeError):
        pass


def _active_changed(self, context):
    ob = self.id_data
    if layers.painting(ob):
        layers.switch_layer(ob, layers._session["uid"])


class ALLSET_PG_skin_layer(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", default="Layer")
    uid: IntProperty(options={'HIDDEN'})
    enabled: BoolProperty(name="Enabled", default=True, update=_layer_changed,
                          description="Use this layer in the skin's weights")
    opacity: FloatProperty(name="Opacity", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=_layer_changed,
                           description="How much this layer covers the layers below it")


class ALLSET_PG_skin_layers(bpy.types.PropertyGroup):
    layers: CollectionProperty(type=ALLSET_PG_skin_layer)
    active_index: IntProperty(name="Active Layer", default=0, update=_active_changed)
    initialized: BoolProperty(default=False, options={'HIDDEN'})
    vert_count: IntProperty(default=0, options={'HIDDEN'})
    influence: StringProperty(name="Influence", description="The joint painted and set on the active layer")
    paint_mask: BoolProperty(name="Mask", default=False,
                             description="Paint and set the active layer's mask instead of a joint")


# --- operators ------------------------------------------------------------------------------------------------------

class _OnSkin:
    @classmethod
    def poll(cls, context):
        return layers.skinned(target(context))


class _OnLayers:
    @classmethod
    def poll(cls, context):
        ob = target(context)
        return layers.skinned(ob) and layers.is_initialized(ob)


def _check_topology(op, ob):
    if not layers.topology_ok(ob):
        op.report({'WARNING'}, "The mesh's vertices changed since the skin layers were made: initialize them again")
        return False
    return True


class ALLSET_OT_skin_tools(bpy.types.Operator):
    """Open Skin Tools: skin weight layers with masks, painting, set weights and mirror (like Maya's Skin Tools)"""
    bl_idname = "allset.skin_tools"
    bl_label = "Skin Tools"

    def execute(self, context):
        if context.window is None:
            return {'CANCELLED'}
        if marked_window.open_window(context, KIND) is None:
            from . import window_places
            if not window_places.deferred():
                self.report({'ERROR'}, "Could not open the Skin Tools window")
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_skin_layers_init(_OnSkin, bpy.types.Operator):
    """Make the skin's layer stack: a base layer holding the current weights"""
    bl_idname = "allset.skin_layers_init"
    bl_label = "Initialize Skin Layers"
    bl_options = {'UNDO'}

    def execute(self, context):
        ob = target(context)
        layers.initialize(ob)
        redraw(context)
        return {'FINISHED'}


class ALLSET_OT_skin_layers_delete(_OnLayers, bpy.types.Operator):
    """Remove the layer stack; the skin keeps its current weights (Paint Skin Weights is the classic tool again)"""
    bl_idname = "allset.skin_layers_delete"
    bl_label = "Delete Skin Layers"
    bl_options = {'UNDO'}

    def execute(self, context):
        layers.delete_layers(target(context))
        redraw(context)
        return {'FINISHED'}


class ALLSET_OT_skin_layer_add(_OnLayers, bpy.types.Operator):
    """Create an empty layer above the active one"""
    bl_idname = "allset.skin_layer_add"
    bl_label = "Create Layer"
    bl_options = {'UNDO'}

    duplicate: BoolProperty(name="Duplicate", default=False, options={'SKIP_SAVE'},
                            description="Copy the active layer instead of making an empty one")

    def execute(self, context):
        ob = target(context)
        if not _check_topology(self, ob):
            return {'CANCELLED'}
        layers.add_layer(ob, copy_of=layers.active_layer(ob) if self.duplicate else None)
        layers.recomposite(ob)
        redraw(context)
        return {'FINISHED'}


class ALLSET_OT_skin_layer_remove(_OnLayers, bpy.types.Operator):
    """Delete the active layer (the last layer stays)"""
    bl_idname = "allset.skin_layer_remove"
    bl_label = "Delete Layer"
    bl_options = {'UNDO'}

    def execute(self, context):
        ob = target(context)
        if not layers.remove_layer(ob, layers.state(ob).active_index):
            self.report({'WARNING'}, "The last layer can't be deleted: use Delete Skin Layers")
            return {'CANCELLED'}
        layers.refresh_after_edit(ob)
        redraw(context)
        return {'FINISHED'}


class ALLSET_OT_skin_layer_move(_OnLayers, bpy.types.Operator):
    """Move the active layer up or down the stack"""
    bl_idname = "allset.skin_layer_move"
    bl_label = "Move Layer"
    bl_options = {'UNDO'}

    direction: EnumProperty(items=(("UP", "Up", "Move the layer up (over more layers)"),
                                   ("DOWN", "Down", "Move the layer down")), default="UP", options={'SKIP_SAVE'})

    def execute(self, context):
        ob = target(context)
        st = layers.state(ob)
        if not layers.move_layer(ob, st.active_index, -1 if self.direction == "UP" else 1):
            return {'CANCELLED'}
        layers.recomposite(ob)
        redraw(context)
        return {'FINISHED'}


class ALLSET_OT_skin_tools_pick(_OnLayers, bpy.types.Operator):
    """Paint and set this influence on the active layer"""
    bl_idname = "allset.skin_tools_pick"
    bl_label = "Pick Influence"
    bl_options = {'UNDO'}

    name: StringProperty(options={'SKIP_SAVE'})
    mask: BoolProperty(default=False, options={'SKIP_SAVE'})

    def execute(self, context):
        ob = target(context)
        st = layers.state(ob)
        st.paint_mask = self.mask
        if not self.mask:
            st.influence = self.name
        if layers.painting(ob):
            layers.pick_working(ob, layers.WORK_MASK if self.mask else layers.WORK + self.name)
        redraw(context)
        return {'FINISHED'}


class ALLSET_OT_skin_tools_paint(_OnLayers, bpy.types.Operator):
    """Paint the active layer (the picked influence or the mask); click again to stop painting"""
    bl_idname = "allset.skin_tools_paint"
    bl_label = "Paint"
    bl_options = {'UNDO'}

    def execute(self, context):
        ob = target(context)
        if layers.painting(ob):
            layers.stop_paint(ob)
            if ob.mode == 'WEIGHT_PAINT':
                from ..operators import skin
                win = context.window_manager.windows[0] if context.window_manager.windows else None
                if win is not None:
                    with context.temp_override(window=win, screen=win.screen):
                        skin.leave_weight_paint(bpy.context)
                else:
                    skin.leave_weight_paint(context)
            redraw(context)
            return {'FINISHED'}
        if not _check_topology(self, ob):
            return {'CANCELLED'}
        if not layers.start_paint(context, ob):
            self.report({'WARNING'}, "Could not start painting")
            return {'CANCELLED'}
        redraw(context)
        return {'FINISHED'}


class ALLSET_OT_skin_tools_set_weights(_OnLayers, bpy.types.Operator):
    """Apply the Set Weights mode and intensity to the active layer on the selected vertices (all when none)"""
    bl_idname = "allset.skin_tools_set_weights"
    bl_label = "Apply"
    bl_options = {'UNDO'}

    def execute(self, context):
        ob = target(context)
        if not _check_topology(self, ob):
            return {'CANCELLED'}
        wm = context.window_manager
        from ..operators import skin_basics
        rows = layers.target_rows(ob)          # read before leaving Edit mode (the selection)
        with skin_basics._ObjectData(ob):
            if layers.painting(ob):
                layers.sync(ob)
            done = layers.set_weights(ob, wm.allset_st_mode, wm.allset_st_intensity, wm.allset_st_iterations,
                                      rows=rows)
        if not done:
            self.report({'WARNING'}, "Pick an influence first")
            return {'CANCELLED'}
        redraw(context)
        return {'FINISHED'}


class ALLSET_OT_skin_tools_mirror(_OnLayers, bpy.types.Operator):
    """Mirror the active layer's weights and mask from one side to the other (joints paired by label, then by
    place)"""
    bl_idname = "allset.skin_tools_mirror"
    bl_label = "Mirror"
    bl_options = {'UNDO'}

    def execute(self, context):
        ob = target(context)
        if not _check_topology(self, ob):
            return {'CANCELLED'}
        wm = context.window_manager
        from ..operators import skin_basics
        with skin_basics._ObjectData(ob):
            if layers.painting(ob):
                layers.sync(ob)
            n = layers.mirror_layer(ob, "XYZ".index(wm.allset_st_axis), wm.allset_st_positive)
        from .. import results
        results.result(self, f"Mirrored the layer on {n} vertices")
        redraw(context)
        return {'FINISHED'}


class ALLSET_OT_skin_tools_assign_closest(_OnLayers, bpy.types.Operator):
    """Assign from Closest Joint: on the active layer each selected vertex (all when none) weighs 1 on its nearest
    joint"""
    bl_idname = "allset.skin_tools_assign_closest"
    bl_label = "Assign from Closest Joint"
    bl_options = {'UNDO'}

    def execute(self, context):
        ob = target(context)
        if not _check_topology(self, ob):
            return {'CANCELLED'}
        from ..operators import skin_basics
        rows = layers.target_rows(ob)
        with skin_basics._ObjectData(ob):
            if layers.painting(ob):
                layers.sync(ob)
            layers.assign_closest(ob, rows=rows)
        redraw(context)
        return {'FINISHED'}


# --- the window -----------------------------------------------------------------------------------------------------

class ALLSET_UL_skin_layers(bpy.types.UIList):
    """Skin layers, top layer first"""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.prop(item, "name", text="", emboss=False)
        sub = row.row(align=True)
        sub.ui_units_x = 3.5
        sub.prop(item, "opacity", text="")


def _draw_layers(layout, ob):
    st = layers.state(ob)
    box = layout.box()
    box.label(text="Layers")
    row = box.row()
    row.template_list("ALLSET_UL_skin_layers", "", st, "layers", st, "active_index", rows=4)
    side = row.column(align=True)
    side.operator("allset.skin_layer_add", text="", icon='ADD')
    side.operator("allset.skin_layer_add", text="", icon='DUPLICATE').duplicate = True
    side.operator("allset.skin_layer_remove", text="", icon='REMOVE')
    side.separator()
    side.operator("allset.skin_layer_move", text="", icon='TRIA_UP').direction = "UP"
    side.operator("allset.skin_layer_move", text="", icon='TRIA_DOWN').direction = "DOWN"


def _draw_influences(layout, ob):
    st = layers.state(ob)
    lay = layers.active_layer(ob)
    box = layout.box()
    box.label(text="Influences")
    col = box.column(align=True)
    mask_text = "Mask" if lay is None or lay.get("mask") is not None else "Mask (not painted: whole layer)"
    op = col.operator("allset.skin_tools_pick", text=mask_text, icon='MOD_MASK', depress=st.paint_mask)
    op.mask = True
    for name in layers.influence_names(ob):
        row = col.row(align=True)
        depth = layers.joint_depth(ob, name)
        if depth:
            row.separator(factor=min(depth, 8) * 1.0)
        op = row.operator("allset.skin_tools_pick", text=name, icon='BONE_DATA',
                          depress=not st.paint_mask and st.influence == name)
        op.name = name


def _draw_tab(layout, context, ob):
    wm = context.window_manager
    layout.row(align=True).prop(wm, "allset_st_tab", expand=True)
    box = layout.box()
    tab = wm.allset_st_tab
    if tab == "PAINT":
        on = layers.painting(ob)
        box.operator("allset.skin_tools_paint", text="Stop Painting" if on else "Paint", icon='BRUSH_DATA',
                     depress=on)
        from .. import compat
        ups = compat.unified_paint_settings(context.scene.tool_settings, "weight_paint")
        col = box.column(align=True)
        col.prop(ups, "weight", text="Value")
        col.prop(ups, "strength", text="Opacity")
        lay = layers.active_layer(ob)
        what = "Mask" if layers.state(ob).paint_mask else (layers.state(ob).influence or "-")
        box.label(text=f"Painting: {lay.name if lay else '-'} / {what}")
    elif tab == "SET_WEIGHTS":
        box.row(align=True).prop(wm, "allset_st_mode", expand=True)
        box.prop(wm, "allset_st_intensity")
        if wm.allset_st_mode == "SMOOTH":
            box.prop(wm, "allset_st_iterations")
        box.operator("allset.skin_tools_set_weights")
    else:
        box.row(align=True).prop(wm, "allset_st_axis", expand=True)
        box.prop(wm, "allset_st_positive")
        box.operator("allset.skin_tools_mirror")


class ALLSET_PT_skin_tools(bpy.types.Panel):
    """Skin Tools (a marked Properties Tool tab in its own window)"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_label = "Skin Tools"
    bl_options = {'HIDE_HEADER'}
    bl_order = -300

    @classmethod
    def poll(cls, context):
        return marked_window.context_kind(context) == KIND

    def draw(self, context):
        layout = self.layout
        ob = target(context)
        if not layers.skinned(ob):
            layout.label(text="Select a skinned mesh (Skin > Bind Skin first)")
            layout.operator("allset.marked_window_close", text="Close")
            return
        head = layout.row()
        head.label(text=ob.name, icon='MESH_DATA')
        if not layers.is_initialized(ob):
            layout.label(text="The skin has no layers yet")
            layout.operator("allset.skin_layers_init", icon='RENDERLAYERS')
            layout.operator("allset.marked_window_close", text="Close")
            return
        head.operator("allset.skin_layers_delete", text="", icon='TRASH')
        if not layers.topology_ok(ob):
            layout.label(text="The mesh's vertices changed: initialize the layers again", icon='ERROR')
            layout.operator("allset.skin_layers_init", icon='RENDERLAYERS')
        _draw_layers(layout, ob)
        _draw_influences(layout, ob)
        layout.operator("allset.skin_tools_assign_closest", icon='CON_KINEMATIC')
        _draw_tab(layout, context, ob)
        layout.operator("allset.marked_window_close", text="Close")


classes = (ALLSET_PG_skin_layer, ALLSET_PG_skin_layers, ALLSET_OT_skin_tools, ALLSET_OT_skin_layers_init,
           ALLSET_OT_skin_layers_delete, ALLSET_OT_skin_layer_add, ALLSET_OT_skin_layer_remove,
           ALLSET_OT_skin_layer_move, ALLSET_OT_skin_tools_pick, ALLSET_OT_skin_tools_paint,
           ALLSET_OT_skin_tools_set_weights, ALLSET_OT_skin_tools_mirror, ALLSET_OT_skin_tools_assign_closest,
           ALLSET_UL_skin_layers, ALLSET_PT_skin_tools)

WM_PROPS = ("allset_st_tab", "allset_st_mode", "allset_st_intensity", "allset_st_iterations", "allset_st_axis",
            "allset_st_positive")


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    setattr(bpy.types.Object, layers.PROP, PointerProperty(type=ALLSET_PG_skin_layers))
    wm = bpy.types.WindowManager
    wm.allset_st_tab = EnumProperty(name="Skin Tools Tab", items=TABS, default="PAINT")
    wm.allset_st_mode = EnumProperty(name="Mode", items=MODES, default="REPLACE")
    wm.allset_st_intensity = FloatProperty(name="Intensity", default=1.0, min=0.0, max=1.0, subtype='FACTOR',
                                           description="Value set, added or multiplied; Smooth: how far each pass "
                                                       "moves toward the neighbours")
    wm.allset_st_iterations = IntProperty(name="Iterations", default=1, min=1, max=100,
                                          description="Smooth passes")
    wm.allset_st_axis = EnumProperty(name="Mirror Axis", items=AXES, default="X")
    wm.allset_st_positive = BoolProperty(name="Positive to Negative", default=True,
                                         description="Copy the + side onto the - side (off: the other way)")
    bpy.app.handlers.depsgraph_update_post.append(layers.on_depsgraph)
    bpy.app.handlers.load_post.append(layers.on_load)


def unregister():
    for lst, fn in ((bpy.app.handlers.depsgraph_update_post, layers.on_depsgraph),
                    (bpy.app.handlers.load_post, layers.on_load)):
        while fn in lst:
            lst.remove(fn)
    if bpy.app.timers.is_registered(layers._tick):
        bpy.app.timers.unregister(layers._tick)
    ob = layers.session_object()
    if ob is not None:
        try:
            layers.remove_working(ob)
        except (AttributeError, ReferenceError, RuntimeError):
            pass
    layers._end_session()
    for name in WM_PROPS:
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
    if hasattr(bpy.types.Object, layers.PROP):
        delattr(bpy.types.Object, layers.PROP)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
