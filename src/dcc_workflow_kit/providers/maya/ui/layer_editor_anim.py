# SPDX-License-Identifier: GPL-3.0-or-later
"""The Layer Editor's Anim tab: animation layer rows with Lock / Solo / Mute, the toolbar and the selected layer's
Weight (``draw_anim_tab``), its Layers menu (``draw_anim_layer_items``, ``draw_anim_layer_mode``) and the layer
row right-click menu (``anim_layer_row``, ``draw_anim_row_menu``). Draw only; operators: operators/anim_layers*.py.
"""


def draw_anim_layer_mode(layout, context):
    """Maya's Override / Additive choice for the selected layer (its layer menu), as two check items."""
    from ..operators import anim_layers
    sel = anim_layers.selected(context.scene)
    if sel is None or sel.name == anim_layers.BASE:
        return
    layout.separator()
    layout.prop(sel, "override", text="Override")
    layout.prop(sel, "override", text="Additive", invert_checkbox=True)


# Maya Anim tab Layers menu (Maya order and labels): the items the kit's
# NLA layers carry (operators/anim_layers.py, operators/anim_layers_204.py). Zero Key Layer is a Maya
# toolbar button (also on the kit toolbar), kept here after Merge Layers.
ANIM_LAYER_MENU = (
    ("allset.anim_layer_create", "Create Empty Layer", {"from_selected": False}),
    ("allset.anim_layer_create", "Create Layer from Selected", {"from_selected": True}),
    None,
    ("allset.anim_layer_members", "Add Selected Objects", {"add": True}),
    ("allset.anim_layer_members", "Remove Selected Objects", {"add": False}),
    ("allset.anim_layer_extract", "Extract Selected Objects", {}),
    None,
    ("allset.anim_layer_duplicate", "Duplicate Layer", {"no_animation": False}),
    ("allset.anim_layer_duplicate", "Duplicate Layer (No Animation)", {"no_animation": True}),
    ("allset.anim_layer_merge", "Merge Layers", {}),
    ("allset.anim_layer_zero_key", "Zero Key Layer", {}),
    None,
    ("allset.anim_layer_extract", "Extract Non-Layered Animation for Selected Objects", {"base": True}),
    ("allset.anim_layer_extract", "Extract Non-Layered Animation for All Objects", {"all_objects": True}),
    None,
    ("allset.anim_layer_delete", "Delete", {}),
    ("allset.anim_layer_empty", "Empty", {}),
    ("allset.anim_layer_delete_empty", "Delete Empty Layers", {}),
)
# Maya's Anim tab toolbar, left part (Zero Key / Zero Weight / Full Weight buttons;
# Blender icons until kit glyphs are drawn)
ANIM_TOOLBAR = (
    ("allset.anim_layer_zero_key", 'KEYFRAME', {}),
    ("allset.anim_layer_key_weight", 'KEY_DEHLT', {"weight": 0.0}),
    ("allset.anim_layer_key_weight", 'KEY_HLT', {"weight": 1.0}),
)
# Maya's row buttons, left of the name: Lock, Solo, Mute (24 px pitch,
# BaseAnimation only Lock); icons (off, on) instead of Maya's padlock / rectangle / circle-slash images
ANIM_TOGGLES = (("lock", ('UNLOCKED', 'LOCKED')), ("solo", ('SOLO_OFF', 'SOLO_ON')),
                ("mute", ('MUTE_IPO_OFF', 'MUTE_IPO_ON')))


# Maya greys these Layers menu items while BaseAnimation is among the selected layers
# (Add / Remove Selected Objects, Select Objects, Select Branch / Layer Node,
# Export, Membership, Attribute Editor, Delete, Empty, Delete Empty Layers, Layer Mode). With no layer selected Maya
# enables everything; the kit always has a selected layer.
GREY_WITH_BASE = ("Add Selected Objects", "Remove Selected Objects", "Delete", "Empty", "Delete Empty Layers")
# Layer row right-click menu: the Layers menu without
# the Create / Extract Non-Layered items, plus Lock / Mute / Solo; on BaseAnimation only Extract, Duplicate x2, Merge
# and Lock stay enabled. Exclusive solo, Select Objects / All / Branch / Layer Node, Export, Membership and Attribute
# Editor are not in the kit (remaining).
ANIM_ROW_MENU = (
    ("allset.anim_layer_members", "Add Selected Objects", {"add": True}),
    ("allset.anim_layer_members", "Remove Selected Objects", {"add": False}),
    ("allset.anim_layer_extract", "Extract Selected Objects", {}),
    None,
    ("allset.anim_layer_duplicate", "Duplicate Layer", {"no_animation": False}),
    ("allset.anim_layer_duplicate", "Duplicate Layer (No Animation)", {"no_animation": True}),
    ("allset.anim_layer_merge", "Merge Layers", {}),
    None,
    ("lock", "Lock", None),
    ("mute", "Mute", None),
    ("solo", "Solo", None),
    None,
    ("allset.anim_layer_delete", "Delete", {}),
    ("allset.anim_layer_empty", "Empty", {}),
    ("allset.anim_layer_delete_empty", "Delete Empty Layers", {}),
)
ROW_ON_BASE = ("Extract Selected Objects", "Duplicate Layer", "Duplicate Layer (No Animation)", "Merge Layers", "Lock")


def _base_selected(context):
    from ..operators import anim_layers_204
    return anim_layers_204.base_selected(context.scene)


def draw_anim_layer_items(layout, context=None):
    grey = context is not None and _base_selected(context)
    for entry in ANIM_LAYER_MENU:
        if entry is None:
            layout.separator()
            continue
        idname, text, props = entry
        line = layout
        if grey and text in GREY_WITH_BASE:
            line = layout.row()
            line.enabled = False
        op = line.operator(idname, text=text)
        for k, v in props.items():
            setattr(op, k, v)


def draw_anim_layer_mode(layout, context):
    """Maya's Override / Additive choice for the selected layer (its layer menu), as two check items (greyed while
    BaseAnimation is among the selected layers)."""
    from ..operators import anim_layers
    sel = anim_layers.selected(context.scene)
    if sel is None or sel.name == anim_layers.BASE:
        return
    layout.separator()
    col = layout.column()
    col.enabled = not _base_selected(context)
    col.prop(sel, "override", text="Override")
    col.prop(sel, "override", text="Additive", invert_checkbox=True)


def anim_layer_row(context):
    """The animation layer entry whose Layer Editor row is under the mouse (name button or its Lock / Solo / Mute
    toggle), for the row's right-click menu; None elsewhere."""
    scene = getattr(context, "scene", None)
    ls = getattr(scene, "allset_anim_layers", None)
    if ls is None or not len(ls):
        return None
    op = getattr(context, "button_operator", None)
    if op is not None and op.bl_rna.identifier == "ALLSET_OT_anim_layer_select":
        i = op.index
        return ls[i] if 0 <= i < len(ls) else None
    ptr = getattr(context, "button_pointer", None)
    if ptr is not None and getattr(ptr, "bl_rna", None) is not None and \
            ptr.bl_rna.identifier == "ALLSET_PG_anim_layer":
        return next((e for e in ls if e.name == ptr.name), None)
    return None


def draw_anim_row_menu(layout, context, entry):
    """Maya's layer right-click menu: the selected layers when the clicked row is selected, else that row only."""
    from ..operators import anim_layers
    picked = {e.name for e in anim_layers.selected_layers(context.scene)}
    layer = "" if entry.name in picked else entry.name
    base = entry.name == anim_layers.BASE
    grey_base = anim_layers.BASE in (picked if not layer else {layer})
    for item in ANIM_ROW_MENU:
        if item is None:
            layout.separator()
            continue
        idname, text, props = item
        line = layout.row()
        if (base or grey_base) and text not in ROW_ON_BASE:
            line.enabled = False
        if props is None:                   # Lock / Mute / Solo of the clicked row
            if base and idname != "lock":
                line.enabled = False
            line.prop(entry, idname, text=text)
            continue
        op = line.operator(idname, text=text)
        for k, v in props.items():
            setattr(op, k, v)
        if layer and idname != "allset.anim_layer_delete_empty":
            op.layer = layer
    if not base:
        layout.separator()
        col = layout.column()
        col.enabled = not grey_base
        col.prop(entry, "override", text="Override")
        col.prop(entry, "override", text="Additive", invert_checkbox=True)


def anim_display_order(scene):
    """Indices of ``Scene.allset_anim_layers`` as Maya lists them: top layer first, BaseAnimation last."""
    return list(reversed(range(len(getattr(scene, "allset_anim_layers", ())))))


def draw_anim_tab(layout, context):
    """Maya's Anim tab: toolbar (Create Empty Layer, Create Layer from Selected), the layer rows (name = select,
    M / S / L), then Weight and Additive / Override of the selected layer. Draw only: nothing is written here
    (the list gets BaseAnimation from the operators)."""
    from ..operators import anim_layers
    from .kit_icons import button
    scene = context.scene
    bar = layout.row(align=True)
    left = bar.row(align=True)
    left.alignment = 'LEFT'
    left.emboss = 'NONE'
    for idname, icon, props in ANIM_TOOLBAR:
        op = left.operator(idname, text="", icon=icon)
        for k, v in props.items():
            setattr(op, k, v)
    row = bar.row(align=True)
    row.alignment = 'RIGHT'
    row.emboss = 'NONE'
    button(row, "allset.anim_layer_create", "layer:NEW_EMPTY", 'ADD', text="").from_selected = False
    button(row, "allset.anim_layer_create", "layer:NEW_SELECTED", 'COLLECTION_NEW', text="").from_selected = True
    ls = anim_layers.layers(scene)
    if not len(ls):
        return
    sel = anim_layers.selected(scene)
    picked = {e.name for e in anim_layers.selected_layers(scene)}     # Ctrl / Shift selection
    col = layout.column(align=True)
    for i in anim_display_order(scene):
        e = ls[i]
        line = col.row(align=True)
        base = e.name == anim_layers.BASE
        for attr, icons in ANIM_TOGGLES:
            cell = line.row(align=True)
            if base and attr != "lock":            # Maya: BaseAnimation has only Lock (empty Solo / Mute slots)
                cell.label(text="", icon='BLANK1')
                continue
            cell.prop(e, attr, text="", icon=icons[bool(getattr(e, attr))], toggle=True)
        name = line.row(align=True)
        name.active = not e.mute                 # a muted layer's name reads greyed (#666666)
        name.operator("allset.anim_layer_select", text=e.name, depress=e.name in picked).index = i
    if sel is None:
        return
    layout.separator(factor=0.5)
    # Maya's bottom row: "Weight" field + slider, greyed while BaseAnimation is selected (anim180 state d);
    # Additive / Override is Maya's layer menu choice (Layers menu here)
    # Maya's K is a small square button right of the slider, not half the row
    w = layout.split(factor=0.88, align=True)
    slider = w.row(align=True)
    slider.enabled = sel.name != anim_layers.BASE
    slider.prop(sel, "weight", slider=True)
    w.operator("allset.anim_layer_key_weight", text="K").current = True     # Maya's K: key the weight
