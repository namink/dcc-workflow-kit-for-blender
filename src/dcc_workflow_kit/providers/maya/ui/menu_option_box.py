# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya option boxes: ``option_kind`` (what an item's box opens), ``allset.menu_option_box``, and the
press-and-hold menu ``ALLSET_MT_option_box`` (pointer put on its row; the Maya menu closed before the option window
opens); ``modifier_held`` for Shift / Ctrl+click. Items with a box are drawn by ``menu_item_draw``.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from .. import compat, i18n, results
from . import draw_safe, menu_map
from .menu_tree import BOX_MARK

# A second button on a Blender menu line breaks consecutive lines into a staircase (checked again
# with row / split / column / grid_flow lines), so the item stays one button:
# its label ends with Maya's box mark, click = the command, press and hold = "Option Box" = the option window
# (``operators/option_windows.py``) or the command's own settings. Since #82 the hold needs no drag:
# the pointer is put on the hold menu's "Option Box" row, so letting go runs it.
BOX_TIP = i18n.mark("❒ Option box: click the box, or press and hold the item (or Shift / Ctrl+click)")


# --- opening the option box by holding (#82) ----------------------------------------------------------
# Blender 4.5 (interface_handlers.cc / interface_layout.cc ui_item_menu_hold): a held
# ``operator_menu_hold`` button opens its hold menu after BUTTON_AUTO_OPEN_THRESH (0.2 s) *below* the button, as a
# popup of its own; letting go outside it cancels it, so before #82 the user had to drag onto its row. Python
# can't tell where on the item a click landed, Shift / Ctrl / Alt+click run nothing in event simulation, and an
# option window opened from a timer while the menus are open leaves them open under it. So:
# 1. when the hold menu opens, the pointer goes onto its (taller) "Option Box" row: letting go runs it;
# 2. the Maya menu the item was in is still open then (Blender closes only the hold menu), so the option box first
#    moves the pointer to the far side of the window (Blender closes a menu the mouse left, UI_BLOCK_MOVEMOUSE_QUIT;
#    checked in a normal GUI Blender: event simulation gets no event from a warp), then after AWAY_TICK puts it back
#    and opens the option window there.
HOLD_ROW_SCALE = 1.5        # the hold menu's row height in menu rows: room for where the pointer sat on the item
HOLD_WARP_PX = 28           # pointer move at UI scale 1: item row centre -> hold row centre (23 px + half the taller row)
HOLD_ROOM_PX = 60           # less room than this under the pointer: Blender opens the hold menu above the item
AWAY_TICK = 0.05            # s the pointer stays away while Blender closes the menu
LAST_WARP = []              # the pointer moves of the last hold / close: (move, window x, y), for tests
_hold = {"t": -1.0, "back": None}


def modifier_held():
    """Shift or Ctrl physically down (the OS key state; Blender gives a menu item no event)."""
    from ..operators import keystate
    return any(keystate.is_down(k) for k in ("LEFT_SHIFT", "RIGHT_SHIFT", "LEFT_CTRL", "RIGHT_CTRL"))


def _point_at_hold_row_later(context):
    """After the hold menu opened, put the pointer on its Option Box row (once per hold: a refresh redraws it)."""
    import time
    from .. import live_refs
    win = context.window
    now = time.monotonic()
    if win is None or now - _hold["t"] < 0.5:
        return
    _hold["t"] = now
    ptr = win.as_pointer()

    def later():
        from ..operators import keystate
        w = live_refs.window(ptr)
        if w is None or keystate.is_down('LEFTMOUSE') is False:      # already let go: the hold menu is gone
            return None
        with bpy.context.temp_override(window=w):
            bpy.ops.allset.option_box_point('INVOKE_DEFAULT', move='HOLD_ROW')
        return None
    bpy.app.timers.register(later, first_interval=0.0)


def _close_menu_then_open(context, item):
    """Close the Maya menu still open under the hold menu, then open ``item``'s option box where the pointer was."""
    from .. import live_refs
    if context.window is None:
        return
    wp = context.window.as_pointer()
    ap = context.area.as_pointer() if context.area else 0
    rp = context.region.as_pointer() if context.region else 0
    # away right now: Blender queues a mouse move after closing the hold menu, built from the pointer position, and
    # where the pointer was is the Maya menu's next row - a submenu there opens, and Blender never mouse-outs a menu
    # while a newer one is open (interface_handlers.cc ui_mouse_motion_towards_check "annoying fix").
    # Blender 5.x (menu_close_leave off, its default) closes menus only on a click: no warp, the option window
    # opens over the Maya menu (compat.menus_close_on_leave).
    away = compat.menus_close_on_leave(context.preferences)
    if away:
        with bpy.context.temp_override(window=context.window):
            bpy.ops.allset.option_box_point('INVOKE_DEFAULT', move='AWAY')

    def later():
        w = live_refs.window(wp)
        if w is None:
            return None
        if away:
            with bpy.context.temp_override(window=w):
                bpy.ops.allset.option_box_point('INVOKE_DEFAULT', move='BACK')
        area = live_refs.area(ap, w)
        region = live_refs.region(area, rp)
        with bpy.context.temp_override(window=w, area=area, region=region):
            bpy.ops.allset.menu_option_box('INVOKE_DEFAULT', item=item)
        return None
    bpy.app.timers.register(later, first_interval=AWAY_TICK)


class ALLSET_OT_option_box_point(bpy.types.Operator):
    """Move the pointer for a held option box: onto the hold menu's row, away (closes the menu) and back"""
    bl_idname = "allset.option_box_point"
    bl_label = "Point for Option Box"
    bl_options = {'INTERNAL'}

    move: EnumProperty(items=[('HOLD_ROW', "Hold Row", ""), ('AWAY', "Away", ""), ('BACK', "Back", "")],
                       options={'SKIP_SAVE'})

    def invoke(self, context, event):      # called from a timer: the event is the window's latest state
        win = context.window
        scale = context.preferences.system.ui_scale or 1.0
        x, y = event.mouse_x, event.mouse_y
        if self.move == 'HOLD_ROW':
            step = round(HOLD_WARP_PX * scale)
            y = y - step if y >= HOLD_ROOM_PX * scale else y + step
            LAST_WARP[:] = []
        elif self.move == 'AWAY':
            _hold["back"] = (x, y)
            x = 2 if x > win.width // 2 else win.width - 3     # the far side: outside the menu and its safety margin
        else:
            if _hold["back"] is None:
                return {'CANCELLED'}
            x, y = _hold["back"]
            _hold["back"] = None
        win.cursor_warp(x, y)
        LAST_WARP.append((self.move, x, y))
        return {'FINISHED'}


class ALLSET_MT_option_box(bpy.types.Menu):
    """The option box of the Maya menu item that was held"""
    bl_idname = "ALLSET_MT_option_box"
    bl_label = "Option Box"

    def draw(self, context):
        props = getattr(context, "button_operator", None)
        layout = self.layout
        layout.scale_y = HOLD_ROW_SCALE
        op = draw_safe.op(layout, ALLSET_OT_menu_option_box.bl_idname, text="Option Box" + BOX_MARK)
        op.item = getattr(props, "item", "")
        op.from_hold = True
        _point_at_hold_row_later(context)


class ALLSET_OT_menu_option_box(bpy.types.Operator):
    """Maya option box: the command's option window"""
    bl_idname = "allset.menu_option_box"
    bl_label = "Option Box"
    bl_options = {'INTERNAL'}

    item: StringProperty(options={'SKIP_SAVE'})
    from_hold: BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})     # run from a hold menu: close the Maya menu first

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        from ..operators import option_windows
        label = props.item.rsplit('/', 1)[-1]
        if props.item not in menu_map.MAP:
            return f"{label} options (greyed: no Blender equivalent in Maya Workflow Kit)"
        w = option_windows.find_path(props.item)
        if w is not None:
            return w.title
        kind = option_kind(props.item)
        if kind == "tool":
            return f"{label}: the tool and its Tool Settings"
        return f"{label} Options: run, then its settings (Adjust Last Operation)"

    def execute(self, context):
        action = menu_map.MAP.get(self.item)
        if action is None:
            results.result(self, f"Maya: {self.item} has no Blender equivalent in Maya Workflow Kit yet")
            return {'CANCELLED'}
        if self.from_hold and not bpy.app.background:
            _close_menu_then_open(context, self.item)
            return {'FINISHED'}
        if option_kind(self.item) == "generic":
            return bpy.ops.allset.option_generic('INVOKE_DEFAULT', item=self.item)
        from ..marking.modal import run_action
        whole = _whole_mesh_option(context, self.item)
        if whole is not None:
            action, path = whole, None      # object mode: the command on the whole mesh, with its settings
        else:
            path = self.item
        try:
            run_action(context, action, option=True, path=path)
        except RuntimeError as ex:
            from ..operators import maya_errors
            maya_errors.report_nested(self, ex)
            return {'CANCELLED'}
        return {'FINISHED'}


def _whole_mesh_option(context, path):
    """(bl_idname, props) of the whole-mesh option operator of ``path`` in object mode (``menu_map.OBJECT_MODE``:
    Maya runs the command on every component of the selected meshes), else None."""
    from .menu_item_ops import WHOLE_MESH_OPTIONS, WHOLE_MESH_PROPS
    idname = WHOLE_MESH_OPTIONS.get(path)
    if idname is None or context.mode != 'OBJECT' or option_kind(path) != "redo":
        return None
    s = menu_map.spec(path)
    return idname, {**s[2], **WHOLE_MESH_PROPS.get(path, {})}


def option_kind(path):
    """What a mapped item's option box opens: "window" (a kit / Maya option window), "dialog" (the operator's own
    options window or file dialog), "tool" (tool + Tool Settings), "redo" (run + Adjust Last Operation with the
    operator's settings), "generic" (a window saying Blender has no settings for it), "menu"; "none" = unmapped."""
    from ..operators import option_windows
    s = menu_map.spec(path)
    if s is None:
        return "none"
    if option_windows.find_path(path) is not None:
        return "window"
    kind, target, _props = s
    if kind == "tool":
        return "tool"
    if kind in ("menu", "pie"):
        return "menu"
    if target in ("render.render", "allset.render"):
        return "generic"          # Blender's render reads Render Settings; it has no options of its own to adjust
    mod, name = target.split(".")
    try:
        rna = getattr(getattr(bpy.ops, mod), name).get_rna_type()
    except (AttributeError, KeyError):
        return "none"
    if "option_box" in rna.properties or "filepath" in rna.properties:
        return "dialog"
    shown = [p for p in rna.properties if p.identifier != "rna_type" and not p.is_hidden]
    return "redo" if shown else "generic"     # allset.option_generic: a window that says Blender has none
