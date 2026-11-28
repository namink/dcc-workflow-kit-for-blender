# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya UV Toolkit: a "UV Toolkit" tab in the UV Editor sidebar.

Order of Maya's toolkit: component icons (Vertex · Edge ·
Face | UV · UV Shell), "N object selected", Pick/Marquee · Drag · Tweak/Marquee, Symmetry, Selection / Transform
Constraint, All · Clear · Inverse, then the folded sections Pinning · Select By Type · Soft Selection · Transform · Create ·
Cut and Sew · Unfold · Align and Snap · Arrange and Layout · UV Sets. Buttons run the UV Editor menu items through
``allset.menu_item`` (same command, undo step and option box as the menu) or the kit's toolkit-only commands
(operators/uv_toolkit_ops.py); items Blender has no counterpart for are greyed with a notice. Stack Similar Shells
matches shells of the same shape onto each other. Transform holds Maya's Pivot / Move / Rotate / Scale / Texel
Density areas and Align and Snap its Snap grid (operators/uv_transform.py).
Buttons sit where Maya's do: raised, two to a row, each with its picture, with Maya's names and pairs (Optimize |
Optimize Tool, Stack Shells | Unstack Shells ...); a command with a direction is one button with its U / V (A to B,
AB) choices beside it, like Maya, and the framed areas carry their title at the left.
"""

import bpy

from .. import i18n
from . import notices, uv_toolkit_icons

CATEGORY = "UV Toolkit"
PICK = (("Pick/Marquee", "builtin.select_box"), ("Drag", "builtin.select_circle"), ("Tweak/Marquee", "builtin.select"))
COMPONENTS = (("VERTEX", 'VERTEXSEL', "Vertex"), ("EDGE", 'EDGESEL', "Edge"), ("FACE", 'FACESEL', "Face"))
UVE = "UV Editor"
# button label, UV Editor menu path (relative ones under UV Editor/): Maya's rows of two, None = an empty cell
CREATE = ((i18n.mark("Automatic"), "UV/Automatic"), (i18n.mark("Normal-Based"), f"{UVE}/Create/Normal-based"),
          (i18n.mark("Cylindrical"), "UV/Cylindrical"), (i18n.mark("Planar"), "UV/Planar"),
          (i18n.mark("Spherical"), "UV/Spherical"), (i18n.mark("Best Plane"), "UV/Best Plane"),
          (i18n.mark("Camera-Based"), "UV/Camera-based"), (i18n.mark("Contour Stretch"), "UV/Contour Stretch"))
SELECT_BY_TYPE = (i18n.mark("Back-Facing"), i18n.mark("Front-Facing"), i18n.mark("Overlapping"), i18n.mark("Non-Overlapping"),
                  i18n.mark("Texture Borders"), (i18n.mark("Unmapped"), "Unmapped Faces"))
# Cut and Sew: Maya's groups, then the kit's other Cut/Sew menu items below them
CUT_SEW_GROUPS = (
    ((i18n.mark("Auto-Seams"), "Cut/Sew/Auto Seams"), None),
    ((i18n.mark("Cut"), "Cut/Sew/Cut"), (i18n.mark("Cut Tool"), "Tools/Cut"),
     (i18n.mark("Create UV Shell"), "Cut/Sew/Create UV Shell"),
     (i18n.mark("Create Shell (Grid)"), "Cut/Sew/Create Shell (Grid)")),
    ((i18n.mark("Sew"), "Cut/Sew/Sew"), (i18n.mark("Sew Tool"), "Tools/Sew")),
)
CUT_SEW_MORE = ((i18n.mark("Split"), "Cut/Sew/Split"), (i18n.mark("Move and Sew"), "Cut/Sew/Move and Sew"),
                (i18n.mark("Merge"), "Cut/Sew/Merge"))
STITCH = (i18n.mark("Stitch Together"), "Cut/Sew/Stitch Together")
CUT_SEW = tuple(b for g in CUT_SEW_GROUPS for b in g if b) + CUT_SEW_MORE + (STITCH,)
SNAP = ((i18n.mark("Linear Align"), "Modify/Linear Align"), (i18n.mark("Snap Together"), "Modify/Snap Together"),
        (i18n.mark("Snap and Stack"), "Modify/Snap and Stack"), (i18n.mark("Match Grid"), "Modify/Match Grid"),
        (i18n.mark("Match UVs"), "Modify/Match UVs"), (i18n.mark("Normalize"), "Modify/Normalize"))
ARRANGE_ROWS = ((i18n.mark("Orient Shells"), "Modify/Orient Shells"),
                (i18n.mark("Orient to Edges"), "Modify/Orient Shells to Edges"),
                (i18n.mark("Stack Shells"), "Modify/Stack Shells"), (i18n.mark("Unstack Shells"), "Modify/Unstack Shells"),
                (i18n.mark("Stack and Orient"), "Modify/Stack and Orient Shells"),
                (i18n.mark("Stack Similar"), "Modify/Stack Similar Shells"),
                (i18n.mark("Gather Shells"), "Modify/Gather Shells"),
                (i18n.mark("Randomize Shells"), "Modify/Randomize Shells"))
ARRANGE = ARRANGE_ROWS + ((i18n.mark("Distribute"), "Modify/Distribute Shells"),
                          (i18n.mark("Layout"), "Modify/Layout"), (i18n.mark("Layout Along"), "Modify/Layout Along"),
                          (i18n.mark("Unitize"), "Modify/Unitize"))
# the icon of each button whose label is not its picture's name
ICON_KEY = {"Normal-Based": "Normal-based", "Camera-Based": "Camera-based", "Auto-Seams": "Auto Seams",
            "Create UV Shell": "Create Shell", "Stack Shells": "Stack", "Unstack Shells": "Unstack",
            "Randomize Shells": "Randomize"}
# Maya's six Align pictures: left, middle and right in U, then top, middle and bottom in V
ALIGN = (('U', 'MIN', i18n.mark("Min U")), ('U', 'AVG', i18n.mark("Avg U")), ('U', 'MAX', i18n.mark("Max U")),
         ('V', 'MAX', i18n.mark("Max V")), ('V', 'AVG', i18n.mark("Avg V")), ('V', 'MIN', i18n.mark("Min V")))

GREY = {
    "UV Toolkit/Symmetry": (
        "Mirror UVs", "Blender has no UV symmetry selection: select one side, then UV > Mirror."),
    "UV Toolkit/Selection Constraint": (
        "Select menu", "Blender has no UV selection constraint: use Select > Select Linked / Select Split."),
    "UV Toolkit/Transform Constraint": (
        "Snapping", "Blender has no UV transform constraint: use snapping (UV Editor header magnet)."),
    "UV Toolkit/Scale Step Snap": (
        "UV grid step", "Blender's UV Scale tool steps by the UV grid step (the Move Step Snap value); it has no "
        "separate scale step."),
    "UV Toolkit/Distribute Target": (
        "Distribute arrows", "Distributing shells towards a target shell is not available yet: use the Distribute "
        "arrows."),
    "UV Toolkit/Prevent Negative Scale": (
        "Scale buttons", "Prevent Negative Scale is not available yet."),
}


def _grey(layout, key, text, emboss=False):
    row = layout.row(align=True)
    row.enabled = False
    row.operator("allset.menu_unavailable", text=text, emboss=emboss).item = key


def _icon(key):
    """The kit picture beside toolkit button ``key`` (its English label), like Maya's toolkit (0 = none)."""
    return uv_toolkit_icons.icon(ICON_KEY.get(key, key))


def _op(layout, idname, text, key=None, **kw):
    """A toolkit button like Maya's: raised, as wide as its cell, its picture at the left edge."""
    return layout.operator(idname, text=text, icon_value=_icon(key or text), **kw)


def _path(path):
    return path if path.startswith(("UV/", UVE)) else f"{UVE}/{path}"


def _item(layout, path, text, key=None):
    """A UV Editor menu item: the same command, undo step and option box (Shift+click) as the menu; greyed while the
    kit has no command for it."""
    from . import menu_map
    path = _path(path)
    cell = layout.row(align=True)
    cell.enabled = path in menu_map.MAP
    _op(cell, "allset.menu_item", text, key).item = path
    return cell


def _pair(layout):
    """One row of Maya's two equal columns: (left cell, right cell)."""
    split = layout.split(factor=0.5, align=True)
    return split.row(align=True), split.row(align=True)


def _quarter(cell):
    """The left half of a right-hand cell (Maya's two quarter-width toggles); the rest of the cell stays empty."""
    split = cell.split(factor=0.5, align=True)
    left = split.row(align=True)
    split.label(text="")
    return left


def _gap(layout):
    """Maya's small gap between groups of buttons."""
    layout.separator(factor=0.4)


def _rows(layout, items):
    """Buttons two to a row in reading order; None = an empty cell."""
    col = layout.column(align=True)
    for i in range(0, len(items), 2):
        cells = _pair(col)
        for cell, it in zip(cells, items[i:i + 2]):
            if it is None:
                cell.label(text="")
            else:
                _item(cell, it[1], it[0])
    return col


def _area(layout, title, side=(), stacked=False):
    """Maya's framed areas of Transform, Align and Snap, Arrange and Layout: the title at the left (``stacked``: one
    word per line while it is not translated), the controls to the right of it."""
    box = layout.box()
    split = box.split(factor=0.25)
    t = split.column()
    text = i18n.iface(title)
    for line in (text.split() if stacked and text == title else (text,)):
        t.label(text=line, translate=False)
    for text in side:       # labels of the rows below the title, next to the controls
        row = t.row()
        row.alignment = 'RIGHT'
        row.label(text=text, translate=False)
    return split.column()


# 3 x 3 button grids (Pivot, Move, Snap, Distribute): the glyph points at the place / direction
GLYPHS = {'TOP_LEFT': "↖", 'TOP': "↑", 'TOP_RIGHT': "↗", 'LEFT': "←", 'CENTER': "•",
          'RIGHT': "→", 'BOTTOM_LEFT': "↙", 'BOTTOM': "↓", 'BOTTOM_RIGHT': "↘"}
GRID3 = (('TOP_LEFT', 'TOP', 'TOP_RIGHT'), ('LEFT', 'CENTER', 'RIGHT'), ('BOTTOM_LEFT', 'BOTTOM', 'BOTTOM_RIGHT'))
NUDGE = {'TOP_LEFT': 'UP_LEFT', 'TOP': 'UP', 'TOP_RIGHT': 'UP_RIGHT', 'LEFT': 'LEFT', 'RIGHT': 'RIGHT',
         'BOTTOM_LEFT': 'DOWN_LEFT', 'BOTTOM': 'DOWN', 'BOTTOM_RIGHT': 'DOWN_RIGHT'}
DISTRIBUTE = {'TOP': 'UP', 'LEFT': 'LEFT', 'RIGHT': 'RIGHT', 'BOTTOM': 'DOWN'}


GRID_SIDE = 0.17       # share of a grid with a centre field that each arrow column takes


def _columns(row, side):
    """(left, centre, right) cells of a grid row: the outer two ``side`` of the width each."""
    split = row.split(factor=side)
    left = split.row(align=True)
    split = split.split(factor=(1.0 - 2.0 * side) / (1.0 - side))
    return left, split.row(align=True), split.row(align=True)


GRID_BUTTON = 1.0       # every grid button is this many UI units wide (about square), whatever its column's width


def _button_cell(cell):
    """A grid button's place: GRID_BUTTON wide at the middle of its cell, so all nine are the same size."""
    cell.alignment = 'CENTER'
    sub = cell.row(align=True)
    sub.ui_units_x = GRID_BUTTON
    return sub


def _grid3(layout, op, prop, values=None, middle=None, extra=None):
    """Nine equal buttons of ``op`` with their arrow pictures (``prop`` = the place, or ``values[place]``; a place
    without a value stays empty; ``extra`` = more properties set on every button). With ``middle`` the centre column is
    wider and holds ``middle(row)``; the arrows above and below it keep the size of the others and stand at its
    middle, like Maya's Move arrows around the step field."""
    col = layout.column()
    for places in GRID3:
        row = col.row()
        cells = [row.row() for _ in range(3)] if middle is None else _columns(row, GRID_SIDE)
        for cell, place in zip(cells, places):
            value = place if values is None else values.get(place)
            if middle is not None and place == 'CENTER':
                middle(cell)
                continue
            cell = _button_cell(cell)
            if value is None:
                cell.label(text="")
                continue
            icon = uv_toolkit_icons.icon(f"Grid {place}")
            o = cell.operator(op, text="" if icon else GLYPHS[place], icon_value=icon, translate=False)
            setattr(o, prop, value)
            for k, v in (extra or {}).items():
                setattr(o, k, v)
    return col


def _range_fields(layout, tk, prefix):
    for axis in ("u", "v"):
        split = layout.split(factor=0.22, align=True)
        split.label(text=f"{axis.upper()}:")
        row = split.row(align=True)
        row.prop(tk, f"{prefix}_min_{axis}", text="")
        row.prop(tk, f"{prefix}_max_{axis}", text="")


def _step_snap(layout, context, kind, prop=None, grey_key=None):
    """Maya's Step Snap row of a Transform area: on / off (the UV Editor tool's step snapping) and its value."""
    from ..operators import snap_align
    on = snap_align.uv_step_snap_on(context.scene.tool_settings, kind)
    split = layout.split(factor=0.36, align=True)
    split.label(text="Step Snap:")
    row = split.row(align=True)
    row.operator("allset.uv_step_snap", text="On" if on else "Off", depress=on).kind = kind
    if prop is not None:
        sub = row.row(align=True)
        sub.active = on
        sub.prop(context.scene.allset_uv_toolkit, prop, text="")
    elif grey_key is not None:
        sub = row.row(align=True)
        sub.enabled = False
        sub.operator("allset.menu_unavailable", text="1", emboss=True).item = grey_key


def _preset(layout, prop):
    layout.menu(f"ALLSET_MT_uvtk_preset_{prop}", text="", icon='DOWNARROW_HLT')


def _preset_field(layout, owner, prop, factor=0.3):
    """Maya's preset arrow followed by its value field."""
    split = layout.split(factor=factor, align=True)
    _preset(split, prop)
    split.prop(owner, prop, text="")


def _transform(layout, context):
    """Maya UV Toolkit Transform: Pivot, Move (with its Tools), Rotate, Scale and Texel Density
    (operators/uv_transform.py)."""
    tk = context.scene.allset_uv_toolkit
    col = _area(layout, i18n.mark("Pivot"))
    split = col.split(factor=0.45)
    _grid3(split.column(), "allset.uv_pivot", "position")
    right = split.column(align=True)
    right.prop(tk, "pivot_area", expand=True)
    sub = right.column(align=True)
    sub.active = tk.pivot_area == 'UV_AREA'
    _range_fields(sub, tk, "pivot")
    row = col.row(align=True)
    row.operator("allset.uv_pivot_edit", text="Edit Pivot")
    row.operator("allset.uv_pivot_reset", text="Reset")
    # Move: the U / V fields at the left, the arrows around the step field at the right
    col = _area(layout, i18n.mark("Move"), side=("U", "V"))
    split = col.split(factor=0.35)
    fields = split.column(align=True)
    fields.label(text="")
    for axis in ("u", "v"):
        fields.prop(tk, f"position_{axis}", text="")

    def step_field(row):
        _preset_field(row, tk, "nudge", 0.22)
    _grid3(split.column(), "allset.uv_nudge", "direction", NUDGE, middle=step_field)
    _gap(col)
    _step_snap(col, context, 'TRANSLATE', "move_snap_value")
    col.prop(tk, "retain_spacing", text="Retain component spacing")
    split = col.split(factor=0.6, align=True)
    _op(split, "allset.uv_distribute_toolkit", text="Distribute", key="Distribute UVs")
    split.row(align=True).prop(tk, "distribute_axis", expand=True)
    header, body = col.panel("ALLSET_uvtk_tools", default_closed=True)
    header.label(text="Tools")
    if body:
        _rows(body, ((i18n.mark("Grab"), "Tools/Grab"), (i18n.mark("Lattice"), "Tools/Lattice"),
                     (i18n.mark("Pinch"), "Tools/Pinch"), (i18n.mark("Smear"), "Tools/Smear"),
                     (i18n.mark("Symmetrize"), "Tools/Symmetrize"), None))
    col = _area(layout, i18n.mark("Rotate"))
    row = col.row(align=True)
    split = row.split(factor=0.75, align=True)
    _preset_field(split, tk, "rotate_angle", 0.18)
    row = split.row(align=True)
    row.operator("allset.uv_rotate_step", text="", icon='LOOP_BACK').clockwise = False
    row.operator("allset.uv_rotate_step", text="", icon='LOOP_FORWARDS').clockwise = True
    _step_snap(col, context, 'ROTATE', "rotate_snap_value")
    col = _area(layout, i18n.mark("Scale"))
    split = col.split(factor=0.5, align=True)
    _preset_field(split, tk, "scale_factor", 0.3)
    row = split.row(align=True)
    row.operator("allset.uv_scale_step", text="", icon='FULLSCREEN_ENTER').shrink = False
    row.operator("allset.uv_scale_step", text="", icon='FULLSCREEN_EXIT').shrink = True
    row.prop(tk, "scale_u", toggle=True)
    row.prop(tk, "scale_v", toggle=True)
    _step_snap(col, context, 'RESIZE', grey_key="UV Toolkit/Scale Step Snap")
    _grey(col, "UV Toolkit/Prevent Negative Scale", "Prevent Negative Scale")
    split = col.split(factor=0.6, align=True)
    op = _op(split, "allset.uv_flip", text="Flip")
    op.direction = 'HORIZONTAL' if tk.flip_axis == 'U' else 'VERTICAL'
    op.use_options = True
    split.row(align=True).prop(tk, "flip_axis", expand=True)
    s = context.scene.allset_uv
    col = _area(layout, i18n.mark("Texel Density (px/unit)"), stacked=True)
    split = col.split(factor=0.25, align=True)
    split.operator("allset.uv_texel_get", text="Get")
    split = split.split(factor=0.67, align=True)
    _preset_field(split, s, "texel_density", 0.3)
    split.operator("allset.uv_texel_set", text="Set")
    row = col.row(align=True)
    row.label(text="Map Size:")
    row.prop(s, "map_size", text="")


def _cut_sew(layout, context):
    tk = context.scene.allset_uv_toolkit
    for group in CUT_SEW_GROUPS:
        col = _rows(layout, group)
        _gap(layout)
    left, right = _pair(col)        # Stitch Together closes the Sew group
    _op(left, "allset.uv_stitch_together", text="Stitch Together").order = tk.stitch_order
    right.prop(tk, "stitch_order", expand=True)
    _gap(layout)
    col = _rows(layout, CUT_SEW_MORE)
    left, right = _pair(col)
    _op(left, "allset.cut_sew_tool_set", text="3D Cut and Sew Tool")
    right.label(text="")


def _unfold(layout, context):
    tk = context.scene.allset_uv_toolkit
    col = layout.column(align=True)
    for name, tool in ((i18n.mark("Optimize"), i18n.mark("Optimize Tool")),
                       (i18n.mark("Unfold"), i18n.mark("Unfold Tool"))):
        left, right = _pair(col)
        _item(left, f"Modify/{name}", text=name)        # Shift+click: the options, like the menu
        _item(right, f"Tools/{name}", text=tool)
    left, right = _pair(col)
    _op(left, "allset.uv_unfold_along", text="Unfold Along").axis = tk.unfold_axis
    _quarter(right).prop(tk, "unfold_axis", expand=True)
    _gap(layout)
    from ..operators import uv_toolkit_ops
    col = layout.column(align=True)
    left, right = _pair(col)
    op = _op(left, "allset.uv_straighten_uvs", text="Straighten UVs")
    op.axis, op.tolerance = uv_toolkit_ops.straighten_axis(context), tk.straighten_tolerance
    split = right.split(factor=0.5, align=True)
    split.prop(tk, "straighten_tolerance", text="")
    sub = split.row(align=True)
    sub.prop(tk, "straighten_u", toggle=True)
    sub.prop(tk, "straighten_v", toggle=True)
    left, right = _pair(col)
    _item(left, "Modify/Straighten Shell", text="Straighten Shell")
    _item(right, "Modify/Straighten Border", text="Straighten Border")


def _align_snap(layout, context):
    tk = context.scene.allset_uv_toolkit
    col = _area(layout, i18n.mark("Align"))
    row = col.row(align=True)
    for axis, where, label in ALIGN:      # Maya's row of six pictures; the label is the tooltip
        icon = _icon(f"Align {axis} {where}")
        op = row.operator("allset.uv_align_to", text="" if icon else label, icon_value=icon)
        op.axis, op.where = axis, where
    text, path = SNAP[0]
    _item(col.split(factor=0.75), path, text)
    col = _area(layout, i18n.mark("Snap"))
    split = col.split(factor=0.45)
    _grid3(split.column(), "allset.uv_snap_shells", "position")
    _range_fields(split.column(align=True), tk, "snap")
    group = col.column(align=True)
    split = group.split(factor=0.75, align=True)
    _op(split, "allset.uv_snap_together", text="Snap Together").method = tk.snap_order
    split.row(align=True).prop(tk, "snap_order", expand=True)
    text, path = SNAP[2]
    _item(group.split(factor=0.75, align=True), path, text)
    _gap(col)
    group = col.column(align=True)
    for text, path in SNAP[3:5]:
        _item(group.split(factor=0.75, align=True), path, text)
    split = group.split(factor=0.75, align=True)
    along = 'UV' if tk.normalize_u == tk.normalize_v else ('U' if tk.normalize_u else 'V')
    _op(split, "allset.uv_normalize", text="Normalize").along = along
    sub = split.row(align=True)
    sub.prop(tk, "normalize_u", toggle=True)
    sub.prop(tk, "normalize_v", toggle=True)


def _arrange(layout, context):
    tk = context.scene.allset_uv_toolkit
    col = _area(layout, i18n.mark("Distribute"))
    split = col.split(factor=0.7)

    def factor_field(row):
        row.prop(tk, "distribute_factor", text="")
    _grid3(split.column(), "allset.uv_distribute", "direction", DISTRIBUTE, middle=factor_field,
           extra={"padding": tk.distribute_factor})
    right = split.column()
    right.label(text="")
    _grey(right, "UV Toolkit/Distribute Target", "Target", emboss=True)
    _rows(layout, ARRANGE_ROWS)
    _gap(layout)
    col = layout.column(align=True)
    left, right = _pair(col)
    _op(left, "allset.uv_measure", text="Measure", key="Measure Pixel Distance")
    right.prop(tk, "measure_type", text="")
    left, right = _pair(col)
    left.label(text="")
    box = right.box()
    box.scale_y = 0.6
    box.label(text=f"{tk.measure_result:g}", translate=False)
    _gap(layout)
    col = layout.column(align=True)
    left, right = _pair(col)
    _item(left, "Modify/Layout", text="Layout")        # Shift+click: the Layout options (padding, map size ...)
    _item(right, "Modify/Unitize", text="Unitize")
    left, right = _pair(col)
    _op(left, "allset.uv_layout_along", text="Layout Along").direction = tk.layout_axis
    _quarter(right).prop(tk, "layout_axis", expand=True)


def _section(layout, idname, label, default_closed=True):
    header, body = layout.panel(idname, default_closed=default_closed)
    header.label(text=label)
    return body


def current_component(context):
    from ..operators import uv_shell_select
    if uv_shell_select.active(context):
        return 'SHELL'
    ts = context.scene.tool_settings
    if not ts.use_uv_select_sync:
        from .. import compat
        if compat.uv_island_mode(ts):
            return 'SHELL'
        return {'EDGE': 'UV_EDGE', 'FACE': 'UV_FACE'}.get(ts.uv_select_mode, 'UV')
    v, e, f = ts.mesh_select_mode
    return 'FACE' if f and not (v or e) else 'EDGE' if e and not v else 'VERTEX'


def _tool_id(context):
    try:
        tool = context.workspace.tools.from_space_image_mode('UV', create=False)
    except (AttributeError, TypeError):
        return ""
    return tool.idname if tool else ""


class ALLSET_PT_uv_toolkit(bpy.types.Panel):
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    bl_label = "UV Toolkit"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and space.mode == 'UV'

    def draw(self, context):
        layout = self.layout
        editing = context.mode == 'EDIT_MESH'
        comp = current_component(context) if editing else None
        from . import editor_menu_data, menu_sets
        bar = layout.row(align=True)    # the toolkit's own menu bar: Options / Help
        for i, (title, _items) in enumerate(editor_menu_data.EDITORS["UV Toolkit"]):
            bar.menu(menu_sets.editor_menu_idname("UV Toolkit", i), text=title)
        row = layout.row(align=True)
        row.scale_x = row.scale_y = 1.3
        for mode, icon, label in COMPONENTS:
            row.operator("allset.uv_component", text="", icon=icon, depress=comp == mode).mode = mode
        row.separator()
        for mode, icon in (('UV', 'UV_VERTEXSEL'), ('UV_EDGE', 'UV_EDGESEL'), ('UV_FACE', 'UV_FACESEL')):
            row.operator("allset.uv_component", text="", icon=icon, depress=comp == mode).mode = mode
        row.operator("allset.uv_component", text="", icon='UV_ISLANDSEL', depress=comp == 'SHELL').mode = 'SHELL'
        n = len([o for o in getattr(context, "objects_in_mode_unique_data", ()) if o.type == 'MESH'])
        row = layout.row()
        row.alignment = 'CENTER'
        row.label(text=f"{n} object{'s' if n != 1 else ''} selected" if editing else "No mesh in edit mode")
        col = layout.column(align=True)
        tid = _tool_id(context)
        for label, tool in PICK:
            op = col.operator("wm.tool_set_by_id", text=label, text_ctxt=i18n.CTX_SELECT_STYLE, depress=tid == tool,
                              icon='RADIOBUT_ON' if tid == tool else 'RADIOBUT_OFF')
            op.name, op.space_type = tool, 'IMAGE_EDITOR'
        _gap(layout)
        col = layout.column(align=True)
        for name in ("Symmetry", "Selection Constraint", "Transform Constraint"):     # Maya's label: [Off]
            split = col.split(factor=0.5, align=True)
            split.label(text=f"{name}:")
            _grey(split, f"UV Toolkit/{name}", "Off", emboss=True)
        _gap(layout)
        row = layout.row(align=True)
        for label, action in (("All", 'SELECT'), ("Clear", 'DESELECT'), ("Inverse", 'INVERT')):
            row.operator("uv.select_all", text=label).action = action
        row = layout.row(align=True)
        row.alignment = 'CENTER'
        row.operator("uv.select_less", text="", icon='REMOVE')
        row.operator("uv.select_more", text="", icon='ADD')
        if not editing:
            return
        self._sections(layout, context)

    def _sections(self, layout, context):
        ts = context.scene.tool_settings
        body = _section(layout, "ALLSET_uvtk_pin", "Pinning")
        if body:
            col = body.column(align=True)
            left, right = _pair(col)
            _op(left, "uv.pin", text="Pin")
            _item(right, "Tools/Pin", text="Pin Tool")
            left, right = _pair(col)
            _op(left, "uv.pin", text="Invert Pinning").invert = True
            right.label(text="")
            _gap(body)
            left, right = _pair(body)
            _op(left, "uv.pin", text="Unpin").clear = True
            _op(right, "allset.uv_unpin_all", text="Unpin All")
        body = _section(layout, "ALLSET_uvtk_type", "Select By Type")
        if body:
            _rows(body, [(it, f"Select/{it}") if isinstance(it, str) else (it[0], f"Select/{it[1]}")
                         for it in SELECT_BY_TYPE])
        body = _section(layout, "ALLSET_uvtk_soft", "Soft Selection")
        if body:
            row = body.row()
            row.label(text="Soft Select:")
            on = ts.use_proportional_edit
            row.prop(ts, "use_proportional_edit", text="", emboss=False,
                     icon='CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT')
            row = body.row(align=True)
            row.active = ts.use_proportional_edit
            split = row.split(factor=0.4, align=True)
            split.prop(ts, "proportional_edit_falloff", text="")
            split.prop(ts, "proportional_size", text="")
        body = _section(layout, "ALLSET_uvtk_transform", "Transform")
        if body:
            _transform(body, context)
        body = _section(layout, "ALLSET_uvtk_create", "Create")
        if body:
            _rows(body, CREATE)
        body = _section(layout, "ALLSET_uvtk_cut", "Cut and Sew")
        if body:
            _cut_sew(body, context)
        body = _section(layout, "ALLSET_uvtk_unfold", "Unfold")
        if body:
            _unfold(body, context)
        body = _section(layout, "ALLSET_uvtk_align", "Align and Snap")
        if body:
            _align_snap(body, context)
        body = _section(layout, "ALLSET_uvtk_layout", "Arrange and Layout")
        if body:
            _arrange(body, context)
        ob = context.edit_object
        body = _section(layout, "ALLSET_uvtk_sets", "UV Sets")
        if body and ob is not None and ob.type == 'MESH':
            me = ob.data
            body.template_list("MESH_UL_uvmaps", "", me, "uv_layers", me.uv_layers, "active_index", rows=2)


classes = (ALLSET_PT_uv_toolkit,)


def register():
    notices.PANEL_NOTICES.update(GREY)
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    uv_toolkit_icons.unregister()
    for key in GREY:
        notices.PANEL_NOTICES.pop(key, None)
