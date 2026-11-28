# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya manipulator, pivot and snapping keys: X / C / V / J snap holds, B soft select, A tap, D / Insert pivot,
Shift+drag Smart Duplicate, MMB = last handle, Ctrl+LMB / Shift+MMB axis picks, edge slide / along normals,
In-View drag. Run by ``maya_patches.apply`` in ``PATCHES`` order; shared state: ``maya_patches_base``. ``IC:<line>`` = a line of
``$S\\presets\\keyconfig\\keymap_data\\industry_compatible_data.py``.
"""

from . import patch
from .patch import make_event
from .maya_patches_base import ADDED, _PAINT_MODES, _add


# --- 5. Hold keys: X/C/V/J snapping ------------------------------------------
# Maya: snapping only while the key is held, Shift variants identical
# (Maya hotkeys x/X, c/C, v/V, j).
# Paint/sculpt modes keep their own X (brush color flip): they are checked
# before "3D View", so the hold never runs there.


HOLD_KEYS = (("X", "grid"), ("C", "curve"), ("V", "point"), ("J", "step"))


def patch_hold_snap(kd):
    kd.remove("3D View", "wm.context_toggle", type="X")                 # IC:780 snap toggle
    kd.remove("3D View", "wm.call_menu_pie", type="X", shift=True)      # snap pie
    kd.remove("3D View", "wm.call_menu_pie", type="V")                  # view pie
    for km in ("Object Mode", "Mesh", "Curve", "Curves", "Armature", "Metaball"):
        kd.remove(km, "wm.tool_set_by_id", type="C")                     # cursor tool
    for key, name in HOLD_KEYS:
        for shift in (False, True):
            _add(kd, "3D View", "allset.hold", make_event(key, shift=shift), {"name": name},
                 shadows=_PAINT_MODES)


# --- 6. B soft select (tap toggle, hold + LMB drag radius) ------------------

def patch_soft_select(kd):
    for km in ("Object Mode", "Mesh", "Curve", "Curves", "Metaball", "Lattice", "Particle"):
        kd.remove(km, "wm.context_toggle", type="B")                     # IC:2517, IC:3066
    _add(kd, "3D View", "allset.tap_hold", make_event("B"), {"binding": "soft_select"},
         shadows=_PAINT_MODES)
    # UV Editor too (#571): the same tap / hold + drag on the same soft select state
    kd.remove("UV Editor", "wm.context_toggle", type="B")
    _add(kd, "UV Editor", "allset.tap_hold", make_event("B"), {"binding": "soft_select"})


# --- 7. A tap / hold, D hold pivot, Insert pivot toggle ---------------------
# A: tap = FrameAll, hold = marking menu.
# D / Insert: pivot edit while held / toggle.

def patch_tap_hold_and_pivot(kd):
    kd.remove("3D View", "view3d.view_all", type="A")
    _add(kd, "3D View", "allset.tap_hold", make_event("A"), {"binding": "select_all"},
         shadows=("Sculpt",))
    kd.remove("Object Mode", "wm.tool_set_by_id", type="D")              # IC:121 annotate
    _add(kd, "Object Mode", "allset.hold", make_event("D"), {"name": "pivot"})
    _add(kd, "Object Mode", "allset.pivot_toggle", make_event("INSERT"))
    # Pivot picking precedes normal/cursor selection only during custom pivot edit.
    for km in ("3D View", "3D View Tool: Cursor"):
        _add(kd, km, "allset.pivot_pick", make_event("LEFTMOUSE", any=True), first=True)


# --- 21. Shift+drag a manipulator = Smart Duplicate -----------------------------------
# Maya Smart Duplicate. The C transform gizmo runs gizmogroup.gizmo_tweak
# from these keymaps for any Shift/Ctrl (IC:3703-3721); our item goes first, duplicates the selection
# and passes the same event on, so the gizmo moves the copies. Shift held during a transform was
# Blender's precision (IC:3611-3612): Maya has none, so precision moves to Alt.

GIZMO_KEYMAPS = ("Generic Gizmo Maybe Drag", "Generic Gizmo Drag")


def patch_manip_duplicate(kd):
    release_kms = GIZMO_KEYMAPS + ("3D View", "Window")
    for km in release_kms:
        # Where the OS can't tell whether the button is held (not Windows), a Shift press that never became a
        # drag ends on this release (pass-through): the copy / extrusion is taken back as a Shift+click (#265).
        _add(kd, km, "allset.manip_release", make_event("LEFTMOUSE", "RELEASE", any=True), first=True,
             shadows=tuple(k for k in release_kms if k != km))
    for km in GIZMO_KEYMAPS:
        _add(kd, km, "allset.manip_duplicate", make_event("LEFTMOUSE", "PRESS", shift=True),
             first=True)
        # #175: IC's gizmo_tweak CLICK_DRAG allows no Shift (IC:107-110, unlike
        # blender_default.py:500-503 any_except("alt")), and a CLICK_DRAG carries the press's
        # modifiers (wm_event_system.cc 4.5 :3644), so the real Shift+drag matched no gizmo item and
        # the copy / extrusion was taken back. Shift "any". Ctrl "any" too: a drag started with Ctrl held
        # moves the handle with snapping (else it fell through to box select); Alt stays as IC has it.
        found = kd.find(km, "gizmogroup.gizmo_tweak", type="LEFTMOUSE", value="CLICK_DRAG")
        if not found:
            if not patch.STRICT:
                patch.DRIFT.append(f"{km}: no item gizmogroup.gizmo_tweak CLICK_DRAG")
                continue
            raise LookupError(f"{km}: no item gizmogroup.gizmo_tweak CLICK_DRAG")
        for item in found:
            item[1]["shift"] = -1
            item[1]["ctrl"] = -1


# --- 24. MMB drag = the last picked manipulator handle -------------------------------
# Maya manipsRememberActiveHandle. A plain LMB press on the gizmo
# picks the handle (a click is enough; a drag remembers its transform); the tool keymaps' MMB press (IC: free
# transform) uses it.
# The Channel Box MMB slider (patch 14) stays in front.

MMB_TOOLS = (("3D View Tool: Move", "transform.translate", 'TRANSLATE'),
             ("3D View Tool: Rotate", "transform.rotate", 'ROTATE'),
             ("3D View Tool: Scale", "transform.resize", 'RESIZE'))


def patch_active_handle(kd):
    for km in GIZMO_KEYMAPS:
        _add(kd, km, "allset.manip_press", make_event("LEFTMOUSE", "PRESS"), first=True)
    for km, idname, mode in MMB_TOOLS:
        items = kd.items(km)
        old = kd.find(km, idname, type="MIDDLEMOUSE")
        if not old:
            if not patch.STRICT:
                patch.DRIFT.append(f"{km}: no MMB {idname}")
                continue
            raise LookupError(f"{km}: no MMB {idname}")
        at = next(i for i, it in enumerate(items) if it is old[0])
        kd.remove(km, idname, type="MIDDLEMOUSE")
        item = kd.add(km, "allset.manip_mmb", make_event("MIDDLEMOUSE"), {"mode": mode})
        items.remove(item)
        items.insert(at, item)      # same place: after the Channel Box slider
        ADDED.append((km, "allset.manip_mmb", make_event("MIDDLEMOUSE"), {"mode": mode}, (km,)))


# --- 41. Manipulator Ctrl+LMB, Shift+MMB = closest axis ---------------------------------------------
# Ctrl+LMB sits first in the gizmo keymaps (only over a highlighted kit manipulator handle): a Move axis moves in the
# plane of the other two (Ctrl+Drag Snaps preference: the press goes on to the axis' own snapped drag), plane and
# centre handles pass the press on to their snapped drag (the centre also frees the active handle), a Scale axis
# scales the other two. Shift+MMB goes in the Move / Scale tool keymaps (3D View has no Shift+MMB item; IC
# pans with Alt+MMB): a short modal reads the first movement, picks the axis and starts the transform (a CLICK_DRAG
# item never got the simulated MMB drag).

def patch_manip_ctrl(kd):
    for km in GIZMO_KEYMAPS:
        _add(kd, km, "allset.manip_ctrl", make_event("LEFTMOUSE", "PRESS", ctrl=True), first=True)
    for km, _idname, mode in MMB_TOOLS:
        if mode == 'ROTATE':
            continue
        _add(kd, km, "allset.manip_mmb_auto", make_event("MIDDLEMOUSE", "PRESS", shift=True), {"mode": mode},
             shadows=(km,))


def patch_in_view_mmb(kd):
    """Maya: while the In-View Editor shows, a plain middle drag anywhere in the view changes its selected attribute
    (ui/in_view.py, row -1). With a Move / Rotate / Scale / Transform tool and in object mode the Channel Box virtual
    slider item (first there) starts it when no channel is picked; with the other tools of edit mode this item does.
    It passes the event on where no In-View Editor shows and for the emulated Alt drag (3D View, #242)."""
    _add(kd, "Mesh", "allset.inview_drag", make_event("MIDDLEMOUSE"), {"row": -1}, shadows=("3D View",))


# --- Edge slide / along normals with the Move tool (#262, #391, #394); local rotate / scale (#430) ------------
# Maya: Ctrl+Shift+middle-drag with the Move tool slides the selected components along their edges (the Transform
# Constraint setting drives the handles and the plain MMB drag), Ctrl+middle-drag moves them along their normals.
# Outside mesh edit mode the operator's poll fails and the event goes on.

def patch_component_slide(kd):
    _add(kd, "3D View Tool: Move", "allset.component_slide", make_event("MIDDLEMOUSE", "PRESS", shift=True, ctrl=True),
         {"mode": 'EDGE'})
    # Maya: Ctrl+Shift+drag on a Move manipulator handle slides too, on a Rotate / Scale handle it rotates / scales
    # with every vertex kept on one of its edges (#429) (first in the gizmo keymaps; passes the press on outside mesh
    # edit mode, so Ctrl+Shift+drag on a handle elsewhere stays as it was)
    for km in GIZMO_KEYMAPS:
        _add(kd, km, "allset.manip_slide", make_event("LEFTMOUSE", "PRESS", shift=True, ctrl=True), first=True)
        # ... and shows a "slide" label under the mouse while Ctrl+Shift is held over a handle (always passes on)
        for key in ("LEFT_CTRL", "RIGHT_CTRL", "LEFT_SHIFT", "RIGHT_SHIFT"):
            _add(kd, km, "allset.manip_slide_hint", make_event(key, "ANY", any=True))
    # ... also when the mouse comes onto a handle with Ctrl+Shift already held (always passes on)
    _add(kd, "3D View", "allset.manip_slide_hint_move", make_event("MOUSEMOVE", "ANY", any=True),
         shadows=("3D View Generic", "Weight Paint"))
    # Maya: Ctrl+Shift+middle-drag with the Rotate / Scale tool rotates / scales along the active handle with every
    # vertex kept on one of its edges (a Ctrl+Shift+drag on a Rotate / Scale handle does it through manip_slide above)
    _add(kd, "3D View Tool: Rotate", "allset.manip_mmb_edge", make_event("MIDDLEMOUSE", "PRESS", shift=True, ctrl=True),
         {"mode": 'ROTATE'})
    _add(kd, "3D View Tool: Scale", "allset.manip_mmb_edge", make_event("MIDDLEMOUSE", "PRESS", shift=True, ctrl=True),
         {"mode": 'RESIZE'})
    # Maya: Ctrl+middle-drag with the Move tool moves the selected components along their normals
    _add(kd, "3D View Tool: Move", "allset.component_slide", make_event("MIDDLEMOUSE", "PRESS", ctrl=True),
         {"mode": 'NORMAL'})
    # Maya: Ctrl+middle-drag with the Rotate tool turns each selected component group about its own normal (local X),
    # with the Scale tool scales it across its normal (local YZ); outside mesh edit mode the poll fails, the event goes on
    _add(kd, "3D View Tool: Rotate", "allset.component_local", make_event("MIDDLEMOUSE", "PRESS", ctrl=True),
         {"mode": 'ROTATE'})
    _add(kd, "3D View Tool: Scale", "allset.component_local", make_event("MIDDLEMOUSE", "PRESS", ctrl=True),
         {"mode": 'SCALE'})
