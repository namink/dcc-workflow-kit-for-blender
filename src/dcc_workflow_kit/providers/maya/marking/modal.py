# SPDX-License-Identifier: GPL-3.0-or-later
"""Modal operators: the marking menu engine and the hotbox.

``allset.mm_engine``: one marking menu (``marking/menus.py``) drawn with the
GPU, driven by ``engine.Session``. ``allset.hotbox``: Space hold (menu rows,
centre and N/S/E/W zones); a quick tap toggles the pane (Maya hotbox).
Plus the small operators the hotbox zone menus run.
"""

import json
import time
import traceback

import bpy
from bpy.props import EnumProperty, StringProperty

from ..names import PRODUCT
from ..operators import keystate
from ..ui import menu_data, menu_map, menu_sets
from . import draw, engine
from . import menus as mm

BUTTONS = (("RIGHTMOUSE", "RMB", ""), ("LEFTMOUSE", "LMB", ""), ("MIDDLEMOUSE", "MMB", ""))
MOUSE_BUTTONS = {"LEFTMOUSE", "RIGHTMOUSE", "MIDDLEMOUSE"}
_TIMER = 0.05

# Press clock: Blender gives Python no time for the press event, and a press that comes during a slow frame is
# handled only after it, so counting from the handling makes a real flick look too quick (``quick_none_time``).
# A light heartbeat notes when the event loop last ran. A press handled while the beats are late (the loop busy
# since the last beat) is taken to have come at that last beat; one handled right after a gap in the beats (a slow
# frame the heartbeat already came out of) at the beat before the gap.
BEAT = 0.02
STALE = 0.5                  # no beat for this long: the heartbeat is not running
_beats = [0.0, 0.0]          # the two latest heartbeat times


def _beat():
    _beats[0], _beats[1] = _beats[1], time.monotonic()
    return BEAT


def press_time(now, beats=None):
    """When the press being handled at ``now`` most likely came (see the press clock above)."""
    prev, last = beats if beats is not None else _beats
    if not last or now - last > STALE:
        return now           # the heartbeat is not running
    if now - last > 2 * BEAT:
        return last          # the loop was busy since the last beat: the press came in that time
    if 2 * BEAT < last - prev <= STALE:
        return min(now, prev)    # a slow frame just before: the press came in it
    # (a longer gap: the heartbeat had just started or was not running then, so it says nothing about the press)
    return now               # the loop ran on time: handled at once


def held_time(now, handled, beat_then, beats=None):
    """How long the button was down for a release handled at ``now`` whose press was handled at ``handled``, the
    latest beat then being ``beat_then``: with no beat since, both came in during one slow frame and were handled
    together, so the press lasted about the time between handling them (not since the press dated back into that
    frame); else None (counted from the press time)."""
    last = (beats if beats is not None else _beats)[1]
    return now - handled if last == beat_then else None


def register_clock():
    if not bpy.app.timers.is_registered(_beat):
        bpy.app.timers.register(_beat, first_interval=BEAT, persistent=True)


def unregister_clock():
    if bpy.app.timers.is_registered(_beat):
        bpy.app.timers.unregister(_beat)


def _prefs(context):
    from .. import preferences
    return preferences.get(context)


def _params():
    p = engine.Params().scaled(draw.ui_scale())
    try:
        prefs = _prefs(bpy.context)
        p.quick_gestures, p.submenu_guides = prefs.mm_quick_gestures, prefs.mm_submenu_guides
    except (AttributeError, KeyError):
        pass
    return p


# --- running a picked item ------------------------------------------------------------

def poll_action(action):
    """Greyed out? Checked once per (sub)menu when it opens, not per redraw."""
    if action is None:
        return False
    if isinstance(action, mm.Sub):
        return not mm.is_unavailable(action)
    if _is_item(action):
        # a main-menu item: enabled like in the menu; a failing poll gives Maya's warning, not grey
        return action[1] in menu_map.MAP
    kind, target, _props = menu_map.normalize(action)
    if kind not in ("op", "v3d"):
        return True
    mod, name = target.split(".")
    try:
        return bool(getattr(getattr(bpy.ops, mod), name).poll())
    except (AttributeError, RuntimeError, KeyError):
        return False


def _is_item(action):
    """``("item", "<Maya main menu path>")``: a marking-menu entry that runs that main-menu item."""
    return isinstance(action, tuple) and len(action) == 2 and action[0] == "item"


def hover_notice(session):
    """(key, Help Line text) for the hovered greyed item: its ``notices.MARKING`` notice, or None."""
    from ..ui import notices
    menu = session.stack[0][0].sub        # the root layout's menu (a MarkingMenu)
    item, _opt = session.hover
    if item is None or item.enabled:
        return None
    lay = session.stack[-1][0]
    sub_path = mm.sub_label_path(menu, lay.sub)
    if sub_path is None:
        return None
    key = "/".join(p for p in (menu.name, sub_path, item.label) if p)
    n = notices.MARKING.get(key)
    return (key, f"{item.label}: {n[1]}  (Blender: {n[0]})") if n else None


def run_action(context, action, option=False, path=None):
    """Run a menu action like the Maya menu item (or its option box). An action with an option window
    (``operators/option_windows``) opens it as the option box, and a plain run uses its saved values (a Maya
    menu item runs with its option values); ``path`` = the Maya menu path, for windows tied to a path. A finished
    command is one undo step named after the item (``undo_steps.command``)."""
    from .. import undo_steps
    action = for_this_blender(action)
    outer = undo_steps.depth() == 0
    label = _label(action, path)
    res = undo_steps.command(label, lambda: _run_action(context, action, option, path))
    if outer and isinstance(res, set) and 'FINISHED' in res:
        from ..command_line import runner         # Script Editor History > Echo All Commands
        runner.echo_action(action)
    if outer and not option and isinstance(res, set) and res & {'FINISHED', 'RUNNING_MODAL'}:
        from ..operators import repeat_maya       # Maya G / Recent Commands
        repeat_maya.record(label, action, path, context)
    return res


def for_this_blender(action):
    """``action`` as it runs here: a link to Blender's manual / API / release notes opens the running Blender's pages
    (``compat.docs_url``: the tables name the main target's). Every menu, marking menu, hotbox, option box, shelf and
    repeat run comes through ``run_action``."""
    try:
        kind, target, props = menu_map.normalize(action)
    except (TypeError, ValueError, IndexError, KeyError):
        return action
    if kind == "op" and target == "wm.url_open" and "url" in props:
        from .. import compat
        return (target, dict(props, url=compat.docs_url(props["url"])))
    return action


def _label(action, path):
    if path:
        return path.split("#")[0].rsplit("/", 1)[-1]
    if _is_item(action):
        return action[1].rsplit("/", 1)[-1]
    try:
        return menu_map.normalize(action)[1]
    except (TypeError, ValueError, IndexError):
        return "Maya Command"


def _run_action(context, action, option, path):
    if _is_item(action):
        # The main-menu item itself (allset.menu_item: component / object mode rules, Maya warnings); its option box
        # is the menu's (option window / dialog for that path).
        if option and action[1] in menu_map.MAP:
            return run_action(context, menu_map.MAP[action[1]], option=True, path=action[1])
        return bpy.ops.allset.menu_item(item=action[1])
    from ..operators import option_windows
    window = option_windows.find_path(path) if path else option_windows.find(action)
    if window is not None:
        if option:
            mod, name = window.idname.split(".")
            return getattr(getattr(bpy.ops, mod), name)('INVOKE_DEFAULT')
        if window.click_saved and option_windows.saved(window.key) is not None:
            res = option_windows.run_saved(window, context)
            if isinstance(res, str):
                raise RuntimeError(res)
            return res
    kind, target, props = menu_map.normalize(action)
    if kind == "prop":     # a Maya check / radio item
        return menu_sets.set_prop(context, target, props)
    if kind == "menu":
        from ..ui import option_click
        option_click.forget_called(context)       # opened at a pointer the kit doesn't note: no ❒ zone
        return bpy.ops.wm.call_menu(name=target)
    if kind == "pie":
        return bpy.ops.wm.call_menu_pie(name=target)
    if kind == "tool":
        res = bpy.ops.allset.menu_tool(
            tool=target,
            edit=props.get("edit", False),
            space_type=props.get("space_type", "VIEW_3D"),
            mode=props.get("mode", "ANY"),
            object_type=props.get("object_type", "ANY"),
        )
        if option:  # tool + its settings (Tool Settings window)
            bpy.ops.allset.editor_toggle(editor='TOOL_SETTINGS', show=True)
        return res
    if kind == "v3d" and (context.area is None or context.area.type != 'VIEW_3D'):
        return bpy.ops.allset.menu_run(op=target, props=json.dumps(props))
    if target == "wm.tool_set_by_id" and props.get("space_type") == 'IMAGE_EDITOR':
        # a UV Editor tool picked over another editor (main UV menu over the 3D View): set it in the UV Editor
        from ..operators import uv_components
        if not uv_components.in_uv_editor(context):
            return uv_components.set_uv_editor_tool(context, props["name"])
    mod, name = target.split(".")
    op = getattr(getattr(bpy.ops, mod), name)
    if target == "object.modifier_add":
        # Maya commands run as a modifier: Maya's Error for a selection they don't take (#152), and no
        # Python TypeError when Blender has no such modifier for the active object type
        from ..operators import maya_errors
        maya_errors.check_modifier(context, props.get("type"))
        try:
            return _call(op, option, props)
        except TypeError:
            raise RuntimeError(maya_errors.wrong_type_warning(props.get("type"))) from None
    return _call(op, option, props)


def _call(op, option, props):
    if option and "option_box" in op.get_rna_type().properties:
        # the operator has its own Maya options window (invoke_props_dialog)
        return op('INVOKE_DEFAULT', option_box=True, **props)
    if option:
        # Maya's option box opens the command's settings: Blender's Adjust Last Operation, which needs the operator
        # registered, so it is called with undo=True (its own undo step)
        from .. import undo_steps
        res = op('INVOKE_DEFAULT', True, **props)
        undo_steps.mark_pushed()
    else:
        res = op('INVOKE_DEFAULT', **props)
    if option and res == {'FINISHED'}:
        try:
            bpy.ops.screen.redo_last('INVOKE_DEFAULT')
        except RuntimeError:
            pass
    return res


# Ctrl+RMB convert menu: also opened on a mesh in object mode (marking/__init__.resolve).
CONVERT_FROM_OBJECT = "CTRL_CONVERT"


# --- marking menu engine --------------------------------------------------------------

class ALLSET_OT_mm_engine(bpy.types.Operator):
    """Maya marking menu: drag in a direction and release, flick, or click"""
    bl_idname = "allset.mm_engine"
    bl_label = "Marking Menu"
    bl_options = {'INTERNAL'}

    menu: StringProperty(options={'SKIP_SAVE'})
    button: EnumProperty(items=BUTTONS, options={'SKIP_SAVE'})
    # Where the button went down (region pixels). Callers pass the press position: the
    # event a nested invoke gets is the window's latest state, which may already have
    # moved on (seen with simulated events in the GUI tests).
    origin: bpy.props.IntVectorProperty(size=2, default=(-1, -1), options={'SKIP_SAVE'})

    def invoke(self, context, event):
        region = context.region
        if self.menu not in mm.MENUS or region is None or region.type != 'WINDOW':
            return {'CANCELLED'}
        if draw.ACTIVE:  # another menu/hotbox is up: never stack two
            return {'CANCELLED'}
        origin = tuple(self.origin) if self.origin[0] >= 0 else (event.mouse_region_x, event.mouse_region_y)
        menu = mm.MENUS[self.menu]
        target = getattr(context.window_manager, "allset_mm_target", "") or             (context.active_object.name if context.active_object else "")
        joint = getattr(context.window_manager, "allset_mm_joint", "")
        menu = mm.with_object_name(menu, joint if joint and self.menu == "RMB_JOINT" else target)
        if self.menu.startswith("NODE_"):
            from ..ui import hypershade_hands      # the graph node's name, type and Inputs / Outputs
            menu = hypershade_hands.fill_menu(menu, context)
        if any(e != mm.DIVIDER and isinstance(e[1], mm.NodeList) for e in menu.items):
            from . import rmb_nodes      # DG Traversal / Inputs / Outputs of that object
            menu = mm.with_nodes(menu, rmb_nodes.nodes(bpy.data.objects.get(target)) if target else None)
        menu = mm.with_materials(menu, mm.scene_material_names())    # Assign Existing Material
        from . import live_label
        menu = mm.relabel(menu, live_label)
        # Drawn over the whole window like Maya's menus: bounds = the window's editors.
        # Rows / boxes stay off the area borders Blender draws over every region.
        bounds = draw.window_bounds(context.window, region)
        edges = draw.window_edges(context.window, region)
        # Ctrl+RMB on a mesh in object mode: Maya converts the whole object, so the items are live and
        # run after entering component mode with everything selected (_finish).
        self._from_object = self.menu == CONVERT_FROM_OBJECT and context.mode == 'OBJECT'
        enabled = (lambda a: a is not None and not mm.is_unavailable(a)) if self._from_object else poll_action
        handled = time.monotonic()
        self._handled = (handled, _beats[1])
        self._session = engine.Session(menu, origin, press_time(handled),
                                       draw.measure, _params(), enabled, bounds, edges)
        self._region = region
        self._shown = False
        self._pending = None   # (button, result): click-mode pick waiting for the release
        draw.activate(context.window, region, session=self._session)
        self._timer = context.window_manager.event_timer_add(_TIMER, window=context.window)
        context.window_manager.modal_handler_add(self)
        draw.redraw()
        return {'RUNNING_MODAL'}

    def _show_notice(self):
        """A greyed item under the mouse puts its notice in the Help Line, like a greyed main-menu item's tooltip
       ."""
        found = hover_notice(self._session)
        key = found[0] if found else None
        if key is not None and key != getattr(self, "_notice", None):
            from ..ui import notices
            notices.show(found[1])
        self._notice = key

    def _cleanup(self, context):
        if getattr(self, "_timer", None) is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        draw.redraw()
        draw.ACTIVE.clear()

    def _finish(self, context, result):
        self._cleanup(context)
        verb, item, option = result
        if verb != "RUN":
            return {'CANCELLED'}
        try:
            if getattr(self, "_from_object", False) and context.mode == 'OBJECT':
                from ..operators import maya_errors
                if maya_errors.refuse_hidden(self, context.view_layer.objects.active):     # #187
                    return {'FINISHED'}
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
            run_action(context, item.action, option)
        except RuntimeError as ex:
            from ..operators import maya_errors
            maya_errors.report_nested(self, ex)       # a Maya Error stays an Error (#152)
        return {'FINISHED'}

    def modal(self, context, event):
        s = self._session
        try:
            x, y, now = event.mouse_region_x, event.mouse_region_y, time.monotonic()
            res = None
            pending = self._pending
            if pending is not None:
                # Click mode picked on a press: run on that button's release, so a popup the
                # item opens (Assign Existing Material) doesn't get the release and pick its
                # first row. Maya menu items also run on release.
                button, picked = pending
                released = event.type == button and event.value == 'RELEASE'
                if released or (event.type == 'TIMER' and keystate.is_down(button) is False):
                    self._pending = None
                    return self._finish(context, picked)
                return {'RUNNING_MODAL'}
            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
                s.move(x, y, now)
                draw.redraw()
                self._show_notice()
            elif event.type == self.button and event.value == 'RELEASE':
                res = s.release(x, y, now, held_time(now, *self._handled))
                draw.redraw()
            elif event.type in MOUSE_BUTTONS and event.value == 'PRESS' and s.mode == "CLICK":
                res = s.click(x, y, now)
                if res is not None and res[0] == "RUN":
                    self._pending, res = (event.type, res), None
                    draw.redraw()
                    draw.ACTIVE.clear()   # the menu goes away now; the item runs on release
                draw.redraw()
            elif event.type == 'ESC' and event.value == 'PRESS':
                res = s.escape()      # an open submenu closes first; the whole menu at the top level
                draw.redraw()
            elif event.type == 'WINDOW_DEACTIVATE':
                res = s.cancel()
            elif event.type == 'TIMER':
                if s.tick(now):   # a rest on a parent centre goes back without a mouse move
                    draw.redraw()
                if s.mode == "PRESS" and keystate.is_down(self.button) is False:
                    res = s.release(*s.pos, now)  # the release went to someone else
                elif not self._shown and s.visible(now):
                    self._shown = True
                    draw.redraw()  # show after the delay without a mouse move
            if res is not None:
                return self._finish(context, res)
            return {'RUNNING_MODAL'}
        except Exception:
            traceback.print_exc()
            self._cleanup(context)
            return {'CANCELLED'}


def open_menu(menu_name, button, origin=None):
    """Engine or pie, per the "Marking Menu Style" preference (pies as fallback)."""
    from . import pie_idname
    if _prefs(bpy.context).marking_menu_style == 'PIE':
        return bpy.ops.wm.call_menu_pie(name=pie_idname(menu_name))   # a user-edited menu has its own
    kw = {"origin": origin} if origin is not None else {}
    return bpy.ops.allset.mm_engine('INVOKE_DEFAULT', menu=menu_name, button=button, **kw)


# --- hotbox ---------------------------------------------------------------------------

def hotbox_rows(context, area_type=None):
    """(rows above, cursor row sides, rows below) like Maya's hotbox:
    common menus (+ Cache, Help), the 3D View's panel menus, then the menu set rows (every set when
    Hotbox Controls > Show All Menu Sets is on, the default like Maya; else the current one)."""
    prefs = _prefs(context)

    def row(names):
        return [(menu_sets.menu_idname(n), menu_data.MENUS[n][0]) for n in names if n in menu_data.MENUS]
    above = [row(menu_sets._SET_MENUS[menu_sets.COMMON_SET] + menu_sets._ALWAYS_MENUS)]
    if (area_type or (context.area.type if context.area else None)) == 'VIEW_3D':
        from ..ui import panel_menus
        above.append([(idname, label) for label, idname in panel_menus.BAR])
    sides = (("RECENT", "Recent Commands"), ("CONTROLS", "Hotbox Controls"))
    sets = [sid for sid, _l, _d in menu_sets.SET_ITEMS] if prefs.hotbox_all_sets else [prefs.menu_set]
    below = [r for r in (row(menu_sets._SET_MENUS.get(sid, ())) for sid in sets) if r]
    return above, sides, below


def pane_tap(context):
    """Maya Space tap over any editor: a panel of the four view stays alone, the panel left alone becomes the four
    view again; a pane outside the layout is maximized, and a maximized pane goes back to its layout. Blender
    refusing the split / join shows an in-view message instead of raising out of the hotbox."""
    from ..ui import four_view, view_message
    screen = context.screen
    try:
        if screen is not None and (screen.show_fullscreen or screen.name.endswith("-nonnormal")):
            bpy.ops.screen.back_to_previous()
            return
        got = four_view.tap(context, context.area, context.window)
        if got is None:
            bpy.ops.screen.screen_full_area()
        elif got == "failed":
            view_message.show(context, "This panel can't be split into the four view here")
    except RuntimeError:             # an operator's poll failed
        view_message.show(context, "Space: this pane can't be maximized here")


_LAST_HOLD_END = [None]   # monotonic time the last hotbox hold ended (hotbox_engine.restart_too_soon)


class ALLSET_OT_hotbox(bpy.types.Operator):
    """Maya hotbox: hold Space; click a menu name, or click a zone for its marking menu.
    A quick tap toggles the pane"""
    bl_idname = "allset.hotbox"
    bl_label = "Hotbox"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        region = context.region
        if event.is_repeat or region is None or region.type != 'WINDOW' or draw.ACTIVE:
            return {'CANCELLED'}
        now = time.monotonic()
        if engine.restart_too_soon(_LAST_HOLD_END[0], now):
            return {'CANCELLED'}      # the PRESS half of a release + press repeat pair (#174)
        prefs = _prefs(context)
        self._key = event.type
        self._t0 = now
        self._hold = engine.HoldKey(now)
        self._clicked = False
        self._pressed = None          # (menu key, press point, button) of a press on a menu name
        self._region = region
        center = (event.mouse_region_x, event.mouse_region_y)
        above, sides, below = hotbox_rows(context)
        self._layout = engine.HotboxLayout(above, center, draw.measure, style=prefs.hotbox_style,
                                           scale=draw.ui_scale(), bounds=draw.window_bounds(context.window, region),
                                           below=below, side=sides, title=PRODUCT)
        draw.activate(context.window, region, hotbox=self._layout, hover=None)
        self._timer = context.window_manager.event_timer_add(_TIMER, window=context.window)
        context.window_manager.modal_handler_add(self)
        draw.redraw()
        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        _LAST_HOLD_END[0] = time.monotonic()
        draw.redraw()
        draw.ACTIVE.clear()

    def _release(self, context):
        end = self._hold.end if self._hold.end is not None else time.monotonic()
        self._cleanup(context)
        if engine.is_tap(self._t0, end, self._clicked):
            pane_tap(context)
        return {'FINISHED'}

    def _open_pressed(self, context, event):
        key = self._pressed[0]
        self._cleanup(context)
        # the menu opens at the pointer: note where, for its option boxes (ui/option_click.py)
        from ..ui import option_click
        option_click.note_called(context, getattr(getattr(bpy.types, key, None), "bl_label", key), event.mouse_x)
        self._open_label(key)
        return {'FINISHED'}

    def modal(self, context, event):
        try:
            x, y = event.mouse_region_x, event.mouse_region_y
            now = time.monotonic()
            if event.type == self._key:
                # a RELEASE ends the hold only if no PRESS follows within the grace (repeats sent as pairs, #174)
                if event.value == 'RELEASE':
                    self._hold.release(now)
                elif event.value == 'PRESS':
                    self._hold.press(now)
                return {'RUNNING_MODAL'}
            if self._pressed is not None:
                # #174: a click on a menu name opens the menu on the RELEASE, so the popup never gets that
                # release (Blender opens a menu with a row under the pointer and a release runs that row); a press that
                # drags away opens it at once, for a press-drag-release onto a row (the kit's earlier behaviour).
                if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
                    if engine.menu_drag(self._pressed[1], (x, y), draw.ui_scale()):
                        return self._open_pressed(context, event)
                    return {'RUNNING_MODAL'}
                if event.type == self._pressed[2] and event.value == 'RELEASE':
                    if self._layout.label_at(x, y) == self._pressed[0]:
                        return self._open_pressed(context, event)
                    self._pressed = None          # released elsewhere: nothing
                    return {'RUNNING_MODAL'}
            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
                hover = self._layout.label_at(x, y)
                if hover != draw.ACTIVE.get("hover"):
                    draw.ACTIVE["hover"] = hover
                    draw.redraw()
                return {'RUNNING_MODAL'}
            if event.type in MOUSE_BUTTONS and event.value == 'PRESS':
                self._clicked = True
                key = self._layout.label_at(x, y)
                if key is not None:
                    self._pressed = (key, (x, y), event.type)
                    return {'RUNNING_MODAL'}
                zone = self._layout.zone(x, y)
                if zone is not None:
                    self._cleanup(context)  # the zone's marking menu takes over
                    open_menu(mm.HOTBOX_ZONES[zone].name, event.type, (x, y))
                    return {'FINISHED'}
                return {'RUNNING_MODAL'}
            if event.type == 'ESC' and event.value == 'PRESS' or event.type == 'WINDOW_DEACTIVATE':
                self._cleanup(context)
                return {'CANCELLED'}
            if event.type == 'TIMER' and self._pressed is None and self._hold.tick(now, keystate.is_down(self._key)):
                return self._release(context)
            return {'RUNNING_MODAL'}
        except Exception:
            traceback.print_exc()
            self._cleanup(context)
            return {'CANCELLED'}

    @staticmethod
    def _open_label(key):
        if key == "RECENT":   # Maya HotboxRecentMenu: the repeatLast history
            bpy.ops.wm.call_menu(name="ALLSET_MT_recent_commands")
        elif key == "CONTROLS":
            bpy.ops.wm.call_menu(name=ALLSET_MT_hotbox_controls.bl_idname)
        else:
            bpy.ops.wm.call_menu(name=key)


class ALLSET_MT_hotbox_controls(bpy.types.Menu):
    """Hotbox Controls (Maya hotbox): menu sets, rows, style"""
    bl_idname = "ALLSET_MT_hotbox_controls"
    bl_label = "Hotbox Controls"

    def draw(self, context):
        prefs = _prefs(context)
        layout = self.layout
        layout.prop(prefs, "menu_set", expand=True)
        layout.separator()
        layout.prop(prefs, "hotbox_all_sets")
        layout.prop(prefs, "hotbox_style", expand=True)
        layout.separator()
        layout.prop(prefs, "marking_menu_style", expand=True)


# --- hotbox zone actions -------------------------------------------------------------------

def _view3d(context):
    area = context.area
    if area is None:
        return None, None
    if area.type != 'VIEW_3D':
        area.ui_type = 'VIEW_3D'  # Maya turns the pane into a 3D view panel
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    return area, region


_persp_views = {}  # area pointer -> (rotation, location, distance) of the last perspective view


class ALLSET_OT_hb_view(bpy.types.Operator):
    """Switch the pane to a Maya camera view (Maya hotbox centre zone)"""
    bl_idname = "allset.hb_view"
    bl_label = "Switch View"
    bl_options = {'INTERNAL'}

    view: EnumProperty(items=[(v, v.title(), "") for v in
                              ("PERSP", "TOP", "FRONT", "RIGHT", "LEFT", "BACK", "BOTTOM")])

    def execute(self, context):
        area, region = _view3d(context)
        if area is None:
            return {'CANCELLED'}
        rv3d = area.spaces.active.region_3d
        key = area.as_pointer()
        if self.view == "PERSP":
            saved = _persp_views.get(key)
            if saved:
                rv3d.view_rotation, rv3d.view_location, rv3d.view_distance = saved
            rv3d.view_perspective = 'PERSP'
            return {'FINISHED'}
        if rv3d.view_perspective == 'PERSP':
            _persp_views[key] = (rv3d.view_rotation.copy(), rv3d.view_location.copy(), rv3d.view_distance)
        with context.temp_override(area=area, region=region):
            bpy.ops.view3d.view_axis(type=self.view)
        return {'FINISHED'}


class ALLSET_OT_hb_pane(bpy.types.Operator):
    """Turn the pane under the hotbox into another editor (Maya hotbox South zone)"""
    bl_idname = "allset.hb_pane"
    bl_label = "Switch Panel Type"
    bl_options = {'INTERNAL'}

    ui_type: StringProperty()

    def execute(self, context):
        if context.area is None:
            return {'CANCELLED'}
        from ..ui import shelf
        if shelf.is_kit_row(context.area.spaces.active):
            return {'CANCELLED'}        # the Status Line / Shelf strip is not a panel
        try:
            context.area.ui_type = self.ui_type
        except TypeError:
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_hb_single(bpy.types.Operator):
    """Single Perspective layout: leave four views"""
    bl_idname = "allset.hb_single"
    bl_label = "Single Perspective"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        area, region = _view3d(context)
        if area is None:
            return {'CANCELLED'}
        from ..ui import four_view                 # the persp panel stays, the others close
        if four_view.is_four(context.window.screen):
            four_view.set_layout(context, context.window, False)
        return {'FINISHED'}


class ALLSET_OT_hb_workspace(bpy.types.Operator):
    """Switch to a workspace (Maya panel layouts with Hypershade or Graph Editor)"""
    bl_idname = "allset.hb_workspace"
    bl_label = "Switch Layout"
    bl_options = {'INTERNAL'}

    name: StringProperty()

    def execute(self, context):
        ws = bpy.data.workspaces.get(self.name)
        if ws is None:
            self.report({'WARNING'}, f"No '{self.name}' workspace in this file")
            return {'CANCELLED'}
        context.window.workspace = ws
        return {'FINISHED'}


UI_ELEMENTS = ("HELP_LINE", "STATUS_LINE", "COMMAND_LINE", "CHANNEL_BOX", "ATTRIBUTE",
               "TOOL_SETTINGS", "TOOLBOX")
_PREF_ELEMENTS = {"HELP_LINE": "show_help_line", "STATUS_LINE": "show_status_line",
                  "COMMAND_LINE": "show_command_line"}


class ALLSET_OT_hb_ui(bpy.types.Operator):
    """Show or hide a Maya UI element (Maya hotbox East zone)"""
    bl_idname = "allset.hb_ui"
    bl_label = "Toggle UI Element"
    bl_options = {'INTERNAL'}

    element: EnumProperty(items=[(e, e.replace("_", " ").title(), "") for e in UI_ELEMENTS])

    def execute(self, context):
        if self.element in _PREF_ELEMENTS:
            prefs = _prefs(context)
            attr = _PREF_ELEMENTS[self.element]
            setattr(prefs, attr, not getattr(prefs, attr))
            return {'FINISHED'}
        if self.element == "TOOLBOX":
            # the Tool Box column in a kit layout, else the main 3D View's toolbar (ui/toolbox_layouts.py)
            return bpy.ops.allset.toolbox_toggle()
        return bpy.ops.allset.editor_toggle(editor=self.element)


# Exclusive selection-mask presets (Maya's selection mask presets).
MASK_PRESETS = {
    "ALL": None,
    "POLYGONS": {"mesh"},
    "NURBS": {"curve", "surf", "font", "curves"},
    "RENDERING": {"camera", "light", "light_probe"},
    "DEFORMATIONS": {"lattice", "armature"},
    "ANIMATION": {"armature", "empty"},
}
_ALL_TYPES = ("mesh", "curve", "surf", "meta", "font", "curves", "pointcloud", "volume", "armature",
              "lattice", "empty", "grease_pencil", "camera", "light", "speaker", "light_probe")


class ALLSET_OT_hb_mask(bpy.types.Operator):
    """Only this kind of object can be selected (Maya selection mask preset)"""
    bl_idname = "allset.hb_mask"
    bl_label = "Selection Mask Preset"
    bl_options = {'INTERNAL'}

    preset: EnumProperty(items=[(k, k.title(), "") for k in MASK_PRESETS])

    def execute(self, context):
        from ..ui.status_line import all_view3d_spaces
        keep = MASK_PRESETS[self.preset]
        for space in all_view3d_spaces():
            for t in _ALL_TYPES:
                setattr(space, f"show_object_select_{t}", keep is None or t in keep)
        return {'FINISHED'}


class ALLSET_OT_hb_style(bpy.types.Operator):
    """Hotbox style: zones and menu rows, zones only, or centre only (Maya hotbox centre zone)"""
    bl_idname = "allset.hb_style"
    bl_label = "Hotbox Style"
    bl_options = {'INTERNAL'}

    style: EnumProperty(items=(("ALL", "Zones and Menu Rows", ""), ("ZONES", "Zones Only", ""),
                               ("CENTER", "Center Zone Only", "")))

    def execute(self, context):
        _prefs(context).hotbox_style = self.style
        return {'FINISHED'}


classes = (ALLSET_OT_mm_engine, ALLSET_OT_hotbox, ALLSET_MT_hotbox_controls, ALLSET_OT_hb_view,
           ALLSET_OT_hb_pane, ALLSET_OT_hb_single, ALLSET_OT_hb_workspace, ALLSET_OT_hb_ui,
           ALLSET_OT_hb_mask, ALLSET_OT_hb_style)
