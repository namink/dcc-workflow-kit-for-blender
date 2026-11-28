# SPDX-License-Identifier: GPL-3.0-or-later
"""Commands of the kit Hotkey Editor that are not menu items (#537 - #539): the UV Toolkit's buttons (Align, Unfold
Along, Straighten, Move / Rotate / Scale steps, Flip, Distribute, Layout Along ...), the viewport's X-Ray toggles and
the editor window toggles (#541).
In Maya these buttons have no command of their own, so a Maya user binds them with a script of their own; the kit
lists them ready to bind under Custom Scripts. X-Ray (Toggle) is Maya's own command of that name.

Pure Python (no bpy). Each entry: (command, label, category, operator idname, properties); the idname "toggle"
switches the on / off setting ``data_path`` of the editor under the mouse (X-Ray). A property value
"@name" is read from the UV Toolkit's setting of that name when the key is pressed (the Straighten tolerance, the
Distribute spacing), so the key does what the button does with the toolkit's current values.
``allset.hotkey_command`` (ui/hotkey_editor.py) runs an entry by its command name."""

TOOLKIT = "Custom Scripts.UV Toolkit"
VIEWPORT = "Custom Scripts.Viewport"
WINDOWS = "Custom Scripts.Windows"

_MOVE = (("Up", 'UP'), ("Down", 'DOWN'), ("Left", 'LEFT'), ("Right", 'RIGHT'), ("Up Left", 'UP_LEFT'),
         ("Up Right", 'UP_RIGHT'), ("Down Left", 'DOWN_LEFT'), ("Down Right", 'DOWN_RIGHT'))
_ALIGN = (("Min U", 'U', 'MIN'), ("Avg U", 'U', 'AVG'), ("Max U", 'U', 'MAX'),
          ("Min V", 'V', 'MIN'), ("Avg V", 'V', 'AVG'), ("Max V", 'V', 'MAX'))
_DISTRIBUTE = (("Up", 'UP'), ("Down", 'DOWN'), ("Left", 'LEFT'), ("Right", 'RIGHT'))
# the nine Pivot and Snap buttons (operators/uv_transform.POSITIONS)
_PLACES = (("Top Left", 'TOP_LEFT'), ("Top", 'TOP'), ("Top Right", 'TOP_RIGHT'), ("Left", 'LEFT'),
           ("Center", 'CENTER'), ("Right", 'RIGHT'), ("Bottom Left", 'BOTTOM_LEFT'), ("Bottom", 'BOTTOM'),
           ("Bottom Right", 'BOTTOM_RIGHT'))

COMMANDS = (
    *((f"UVToolkitPivot{label.replace(' ', '')}", f"UV Pivot {label}", TOOLKIT, "allset.uv_pivot",
       {"position": p}) for label, p in _PLACES),
    ("UVToolkitEditPivot", "Edit UV Pivot", TOOLKIT, "allset.uv_pivot_edit", {}),
    ("UVToolkitResetPivot", "Reset UV Pivot", TOOLKIT, "allset.uv_pivot_reset", {}),
    *((f"UVToolkitMove{d.title().replace('_', '')}", f"Move UVs {label}", TOOLKIT, "allset.uv_nudge",
       {"direction": d}) for label, d in _MOVE),
    ("UVToolkitRotateCounterclockwise", "Rotate UVs Counterclockwise", TOOLKIT, "allset.uv_rotate_step",
     {"clockwise": False}),
    ("UVToolkitRotateClockwise", "Rotate UVs Clockwise", TOOLKIT, "allset.uv_rotate_step", {"clockwise": True}),
    ("UVToolkitScaleUp", "Scale UVs Up", TOOLKIT, "allset.uv_scale_step", {"shrink": False}),
    ("UVToolkitScaleDown", "Scale UVs Down", TOOLKIT, "allset.uv_scale_step", {"shrink": True}),
    ("UVToolkitFlipU", "Flip U", TOOLKIT, "allset.uv_flip", {"direction": 'HORIZONTAL'}),
    ("UVToolkitFlipV", "Flip V", TOOLKIT, "allset.uv_flip", {"direction": 'VERTICAL'}),
    *((f"UVToolkitAlign{label.replace(' ', '')}", f"Align {label}", TOOLKIT, "allset.uv_align_to",
       {"axis": axis, "where": where}) for label, axis, where in _ALIGN),
    *((f"UVToolkitSnap{label.replace(' ', '')}", f"Snap Shells {label}", TOOLKIT, "allset.uv_snap_shells",
       {"position": p}) for label, p in _PLACES),
    ("UVToolkitUnfoldAlongU", "Unfold Along U", TOOLKIT, "allset.uv_unfold_along", {"axis": 'U'}),
    ("UVToolkitUnfoldAlongV", "Unfold Along V", TOOLKIT, "allset.uv_unfold_along", {"axis": 'V'}),
    ("UVToolkitStraightenU", "Straighten UVs U", TOOLKIT, "allset.uv_straighten_uvs",
     {"axis": 'U', "tolerance": "@straighten_tolerance"}),
    ("UVToolkitStraightenV", "Straighten UVs V", TOOLKIT, "allset.uv_straighten_uvs",
     {"axis": 'V', "tolerance": "@straighten_tolerance"}),
    ("UVToolkitStraightenUV", "Straighten UVs UV", TOOLKIT, "allset.uv_straighten_uvs",
     {"axis": 'UV', "tolerance": "@straighten_tolerance"}),
    ("UVToolkitNormalizeU", "Normalize U", TOOLKIT, "allset.uv_normalize", {"along": 'U'}),
    ("UVToolkitNormalizeV", "Normalize V", TOOLKIT, "allset.uv_normalize", {"along": 'V'}),
    *((f"UVToolkitDistribute{label}", f"Distribute Shells {label}", TOOLKIT, "allset.uv_distribute",
       {"direction": d, "padding": "@distribute_factor"}) for label, d in _DISTRIBUTE),
    ("UVToolkitLayoutAlongU", "Layout Along U", TOOLKIT, "allset.uv_layout_along", {"direction": 'U'}),
    ("UVToolkitLayoutAlongV", "Layout Along V", TOOLKIT, "allset.uv_layout_along", {"direction": 'V'}),
    ("UVToolkitMeasure", "Measure UVs", TOOLKIT, "allset.uv_measure", {}),
    ("UVToolkitTexelGet", "Get Texel Density", TOOLKIT, "allset.uv_texel_get", {}),
    ("UVToolkitTexelSet", "Set Texel Density", TOOLKIT, "allset.uv_texel_set", {}),
    ("ViewportXRayToggle", "X-Ray (Toggle)", "Other items.Modeling Toolkit", "toggle",
     {"data_path": "space_data.shading.show_xray"}),
    ("ViewportXRayJointsToggle", "X-Ray Joints (Toggle)", VIEWPORT, "toggle",
     {"data_path": "space_data.overlay.show_xray_bone"}),
    # #541: open the editor's window, or close it when it is open in a window of its own (operators/window_toggle.py
    # holds the editors; this list is plain data)
    *((f"Toggle{label.replace(' ', '')}Window", f"{label} Window (Toggle)", WINDOWS, "allset.window_toggle",
       {"window": key}) for key, label in (
        ('UV_EDITOR', "UV Editor"), ('OUTLINER', "Outliner"), ('HYPERSHADE', "Hypershade"),
        ('GRAPH_EDITOR', "Graph Editor"), ('DOPE_SHEET', "Dope Sheet"), ('TRAX_EDITOR', "Trax Editor"),
        ('NODE_EDITOR', "Node Editor"), ('SPREAD_SHEET', "Attribute Spread Sheet"))),
)

BY_COMMAND = {c[0]: c for c in COMMANDS}
