# SPDX-License-Identifier: GPL-3.0-or-later
"""Drawing of the Hypershade panes (``ALLSET_PT_hypershade_pane``): Browser (toolbar, tabs, swatch grid or
list), Create (category tree + node list, ``create_items``), Material Viewer and Property Editor, plus
``PANE_NOTICES`` for the pane controls that are not Maya menu items. Which pane an area is comes from
hypershade_window.py.
"""

import bpy

from . import ae_layout, hypershade_blender
from .hypershade_window import HS, PANE_LABELS, context_pane
from .hypershade_materials import (COLUMNS, MAYA_ONLY_TABS, SORTS, SORT_ICONS, SWATCHES, SWATCH_ICONS, TABS,
                                   browser_items, current, icon_value)
from .hypershade_ops import PICK_PROP


# --- panes ----------------------------------------------------------------------------------------------------

# Create: Maya's category tree (Favorites > Maya > Surface, then Maya > ...) -> Hypershade Create menu
# submenus whose items the list shows (same paths as the Create menu, so menu and pane agree)
CREATE_CATEGORIES = (
    ("FAVORITES", "Favorites", None),
    ("MAYA", "Maya", None),
    ("SURFACE", "Surface", ("Materials",)),
    ("VOLUMETRIC", "Volumetric", ("Volumetric Materials",)),
    ("DISPLACEMENT", "Displacement", ()),
    ("TEX2D", "2D Textures", ("2D Textures",)),
    ("TEX3D", "3D Textures", ("3D Textures",)),
    ("ENV", "Env Textures", ("Environment Textures",)),
    ("OTHER", "Other Textures", ("Layered Texture",)),
    ("LIGHTS", "Lights", ("Lights",)),
    ("UTILITIES", "Utilities", ("General Utilities", "Scalar Utilities", "Switch Utilities", "Color Utilities",
                                "Particle Utilities")),
    ("IMAGE_PLANES", "Image Planes", ("Image Plane",)),
    ("GLOW", "Glow", ("Glow",)),
    ("RENDERING", "Rendering", ("Rendering",)),
    # Blender's own shader nodes: a section beside Maya's, like a renderer's section in Maya's tree
    ("BLENDER", "Blender", None),
    *((key, label, ()) for key, label in hypershade_blender.CATEGORIES),
)
MAYA_KEYS = tuple(c[0] for c in CREATE_CATEGORIES[2:] if c[0] != "BLENDER" and not c[0].startswith("BL_"))
# Maya's Displacement category has no Hypershade Create menu items: greyed (category notice)
DISPLACEMENT = ("C Muscle Shader", "Displacement", "Usd Preview Surface")
# Favorites: Blender's one material (Maya lists its surface shaders here)
FAVORITES = ("New Material",)

# Notices of pane controls that are not Maya menu items (notices.PANEL_NOTICES, filled on register)
PANE_NOTICES = {
    **{f"{HS}/Browser/{t}": ("Not in Blender", f"Blender has no {t.lower()} to list: the {t} tab stays empty.")
       for t in MAYA_ONLY_TABS},
    f"{HS}/Browser/Pause Swatches": ("Material previews", "Blender renders material previews in the background "
                                     "by itself: no pause."),
    f"{HS}/Browser/Show": ("Search field", "Blender's Browser filters by the name in the search field only."),
    f"{HS}/Bins": ("Not in Blender", "Blender has no node bins: the Browser tabs list everything."),
    f"{HS}/Property Editor/Presets": ("Not in Blender", "Blender has no attribute presets for materials."),
}


def _create_menu():
    from . import editor_menu_data
    return dict(editor_menu_data.EDITORS[HS])["Create"]


def _menu_entries(sub):
    """(label, Maya menu path) of the Hypershade Create menu's submenu (or single item) ``sub``, as the menu shows
    them (``menu_tree.children``: the kit's added and left-out entries)."""
    from .menu_tree import children
    for it in _create_menu():
        if it[0] != sub:
            continue
        if len(it) > 1 and isinstance(it[1], list):
            return [(c[0], path) for path, c in children(it[1], f"{HS}/Create/{sub}") if path is not None]
        return [(sub, f"{HS}/Create/{sub}")]
    return []


def create_items(category):
    """(label, Maya menu path) listed by the Create pane for a category (Maya: the category scrolls / filters the
    list; "Maya" = all of them)."""
    if category == 'FAVORITES':
        return [(label, f"{HS}/Create/Materials/{label}") for label in FAVORITES]
    if category == 'MAYA':
        out = []
        for key in MAYA_KEYS:
            out += create_items(key)
        return out
    if category == 'BLENDER' or category.startswith("BL_"):
        return []                  # Blender's nodes: blender_items()
    key, _label, subs = next(c for c in CREATE_CATEGORIES if c[0] == category)
    if key == 'DISPLACEMENT':
        return [(label, f"{HS}/Create/Displacement/{label}") for label in DISPLACEMENT]
    out = []
    for sub in subs:
        out += _menu_entries(sub)
    if key == 'UTILITIES':
        out.sort(key=lambda e: e[0].lower())       # Maya lists the utilities alphabetically, one list
    return out


def draw_title(layout, name):
    """Maya's panel title bar: the panel name between dotted grips."""
    from .maya_dock import HANDLE
    row = layout.row()
    row.alignment = 'CENTER'
    row.label(text=f"{HANDLE}  {PANE_LABELS[name]}  {HANDLE}")


def _greyed(layout, key, text="", icon='NONE'):
    sub = layout.row(align=True)
    sub.enabled = False
    sub.operator("allset.menu_unavailable", text=text, icon=icon).item = key


def draw_browser(layout, context):
    wm = context.window_manager
    # Maya's Browser toolbar: pause | as icons / list | swatch sizes | sort | search (+ Show)
    bar = layout.row(align=False)
    sub = bar.row(align=True)
    _greyed(sub, f"{HS}/Browser/Pause Swatches", icon='PAUSE')
    sub = bar.row(align=True)
    for key in ("ICONS", "LIST"):
        sub.prop_enum(wm, "allset_hs_swatch", key, text="", icon=SWATCH_ICONS[key])
    sub = bar.row(align=True)
    for key in ("SMALL", "MEDIUM", "LARGE", "XLARGE"):
        sub.prop_enum(wm, "allset_hs_swatch", key, text="", icon=SWATCH_ICONS[key])
    sub = bar.row(align=True)
    for key, _l, _d in SORTS:
        sub.prop_enum(wm, "allset_hs_sort", key, text="", icon=SORT_ICONS[key])
    sub.prop(wm, "allset_hs_reverse", text="", icon='SORT_DESC', toggle=True)
    sub = bar.row(align=True)
    sub.prop(wm, "allset_hs_filter", text="", icon='VIEWZOOM', placeholder="Search...")
    _greyed(sub, f"{HS}/Browser/Show", text="Show")
    # the ten Maya tabs (the last three greyed)
    tabs = layout.row(align=True)
    tabs.prop(wm, "allset_hs_tab", expand=True)
    for t in MAYA_ONLY_TABS:
        _greyed(tabs, f"{HS}/Browser/{t}", text=t)
    tab = wm.allset_hs_tab
    items = browser_items(context, tab)
    text = wm.allset_hs_filter.strip().lower()
    if text:
        items = [it for it in items if text in it[1].lower()]
    if not items:
        layout.label(text=f"No {dict((t[0], t[1]) for t in TABS)[tab].lower()} in the scene")
        return
    cur = current(context)
    size = next(s for s in SWATCHES if s[0] == wm.allset_hs_swatch)
    region = context.region
    s = context.preferences.system.ui_scale or 1.0
    if size[3] == 0.0:       # As List
        col = layout.column(align=True)
        for key, label, icon, _t in items:
            _item_button(col, tab, key, label, icon, cur, list_row=True)
        return
    cell = size[3] * 20 * s + 12
    width = region.width if region is not None else 300
    columns = max(1, min(24, int(width // cell))) if region is not None else COLUMNS
    grid = layout.grid_flow(row_major=True, columns=columns, even_columns=True, align=False)
    for key, label, icon, _t in items:
        col = grid.column(align=True)
        value = icon_value(icon) if isinstance(icon, str) else layout.icon(icon)
        col.template_icon(icon_value=value, scale=size[3])
        _item_button(col, tab, key, label, icon, cur)


def _item_button(layout, tab, key, label, icon, cur, list_row=False):
    picked = (tab in {'MATERIALS', 'SHADING_GROUPS'} and cur is not None and key == cur.name)
    if tab == 'MATERIALS':
        kw = {"icon_value": layout.icon(icon)} if list_row else {}
        mat = bpy.data.materials.get(key)
        if mat is not None and mat.library is None:
            # a property button, not an operator one: the hovered property is the only button a keymap operator
            # can read (``context.property``; ``button_operator`` and ``context_pointer_set`` don't reach keymap
            # handlers) -- the MMB swatch drag (ui/hs_drag.py) needs to know the swatch
            layout.prop(mat, PICK_PROP, text=label, toggle=True, **kw)
            return
        op = layout.operator("allset.hs_pick", text=label, depress=picked, **kw)
        op.material = key
        return
    kw = {}
    if list_row:
        kw = {"icon": icon} if isinstance(icon, str) else {"icon_value": layout.icon(icon)}
    op = layout.operator("allset.hs_item", text=label, depress=picked, **kw)
    op.tab, op.key = tab, key


def draw_create(layout, context):
    from . import menu_sets
    wm = context.window_manager
    layout.prop(wm, "allset_hs_create_filter", text="", icon='VIEWZOOM', placeholder="Search...")
    split = layout.split(factor=0.32)
    left = split.column(align=True)
    for key, label, subs in CREATE_CATEGORIES:
        if subs is None:           # tree roots: Favorites, Maya, Blender
            left.prop_enum(wm, "allset_hs_create_cat", key, text=label, icon='DISCLOSURE_TRI_DOWN')
        else:
            left.prop_enum(wm, "allset_hs_create_cat", key, text="    " + label)
    right = split.column(align=True)
    text = wm.allset_hs_create_filter.strip().lower()
    items = create_items('MAYA' if text else wm.allset_hs_create_cat)
    if text:
        items = [it for it in items if text in it[0].lower()]
    seen = set()
    for label, path in items:
        if path in seen:
            continue
        seen.add(path)
        menu_sets.draw_item(right, path, label)
    category = wm.allset_hs_create_cat
    blender = hypershade_blender.items('BLENDER' if text else category)         if text or category == 'BLENDER' or category.startswith("BL_") else []
    if text:
        blender = [it for it in blender if text in it[1].lower()]
    for idname, label in blender:
        hypershade_blender.draw_item(right, idname, label)
    if not items and not blender:
        right.label(text="No node type matches")
    # Maya's bottom tab row: Create | Bins
    tabs = layout.row(align=True)
    tabs.operator("allset.hs_noop", text="Create", depress=True)
    _greyed(tabs, f"{HS}/Bins", text="Bins")


def draw_viewer(layout, context):
    mat = current(context)
    row = layout.row(align=True)
    engine = context.scene.render.engine
    names = {e.identifier: e.name for e in context.scene.render.bl_rna.properties["engine"].enum_items}
    row.label(text=names.get(engine, engine), icon='SHADING_RENDERED')
    if mat is None:
        layout.label(text="Pick a material in the Browser")
        return
    row.prop(mat, "preview_render_type", text="")
    row.prop(mat, "use_preview_world", text="", icon='WORLD')
    if engine == 'BLENDER_WORKBENCH':
        layout.label(text="Workbench draws no material previews: switch the render engine to EEVEE or Cycles",
                     icon='INFO')
        return
    layout.template_preview(mat, show_buttons=False)


def draw_property_editor(layout, context):
    from . import attribute_editor
    mat = current(context)
    if mat is None:
        layout.label(text="Pick a material")
        return
    node = shown_node(mat)
    tab = layout.row(align=True)
    tab.alignment = 'LEFT'
    if node is not None:
        # Maya: the Property Editor shows the node picked in the Graph; its material stays one click away
        tab.operator("allset.hs_pick", text=mat.name).material = mat.name
        tab.operator("allset.hs_noop", text=node.name, depress=True)
        draw_node(layout, context, node)
        return
    tab.operator("allset.hs_noop", text=mat.name, depress=True)
    name = attribute_editor.material_type(mat)
    head = layout.row(align=True)
    head.label(text=f"{name}:")
    head.prop(mat, "name", text="")
    _greyed(head, f"{HS}/Property Editor/Presets", text="Presets")
    sections = ae_layout.BY_KIND[name][0]
    attribute_editor.draw_sections(layout, context, None, mat, sections, f"hs_{name}")


# nodes that are the material itself in the Property Editor (Maya's surface shader and shading group)
_MATERIAL_NODES = {'BSDF_PRINCIPLED', 'OUTPUT_MATERIAL', 'FRAME', 'REROUTE'}


def shown_node(mat):
    """The graph node the Property Editor shows instead of the material: the material's active node while it is
    selected, unless it is the material's own shader or output (those show the material)."""
    tree = mat.node_tree if mat is not None else None
    node = tree.nodes.active if tree is not None else None
    if node is None or not node.select or node.type in _MATERIAL_NODES:
        return None
    return node


def draw_node(layout, context, node):
    """A graph node in the Property Editor: "<type>: [name]", then the node's own settings and its unconnected
    inputs, as Blender's node draws them (the node itself is Blender's)."""
    head = layout.row(align=True)
    head.label(text=f"{node.label or node.bl_label}:")
    head.prop(node, "name", text="")
    col = layout.column()
    node.draw_buttons_ext(context, col)
    for inp in node.inputs:
        if inp.is_linked or not inp.enabled or inp.hide_value or not hasattr(inp, "default_value"):
            continue
        col.prop(inp, "default_value", text=inp.name)


class ALLSET_OT_hs_noop(bpy.types.Operator):
    """Current tab"""
    bl_idname = "allset.hs_noop"
    bl_label = "Tab"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'CANCELLED'}


class ALLSET_PT_hypershade_pane(bpy.types.Panel):
    """A Hypershade pane: Browser, Create, Material Viewer or Property Editor (a marked Properties Tool tab)"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"           # = drawn by the Properties Tool tab
    bl_label = "Hypershade"
    bl_options = {'HIDE_HEADER'}
    bl_order = -300

    @classmethod
    def poll(cls, context):
        return context_pane(context) is not None

    def draw(self, context):
        layout = self.layout
        name = context_pane(context)
        draw_title(layout, name)
        if name == 'BROWSER':
            draw_browser(layout, context)
            cur = current(context)
            row = layout.row()
            row.enabled = cur is not None
            op = row.operator("allset.assign_material", text="Assign Material To Selection", icon='MATERIAL')
            op.material = cur.name if cur is not None else ""
        elif name == 'CREATE':
            draw_create(layout, context)
        elif name == 'VIEWER':
            draw_viewer(layout, context)
        else:
            draw_property_editor(layout, context)
