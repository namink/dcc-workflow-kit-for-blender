# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Shelf: factory shelves as Blender operator buttons, user shelves of Python
scripts, drawn under the Status Line in a thin "Maya strip" area.

Maya's shelf behaviour, tab order and buttons.

- The strip is an Image Editor area marked by the hidden Mask ``.AllsetStrip``
  (``space.mask``): its header row draws the Status Line, its tool header row the
  shelf. The Maya Workflow Kit template uses two header-only areas instead, the strip
  without its tool header and a shelf row marked ``.AllsetShelf`` whose header draws
  the shelf: Blender keeps every area at least one header high, so both rows follow
  the UI scale (a two-row area of fixed height lost its tool header at scale 1.25).
- The shelf row is a 64 px shelf: its header = the shelf
  tabs, its WINDOW region = 32 px kit-made colour icons (``shelf_icons``) drawn and clicked as gizmos
  (``ALLSET_GGT_shelf``: a gizmo map runs before the image editor's tool keymap, gives hover and the
  operator's tooltip). Click = command; a second click within the double-click time or Ctrl+click =
  options (Adjust Last Operation), like Maya's doubleClickCommand. ``IMAGE_HT_header.draw`` / ``IMAGE_HT_tool_header.draw`` are swapped while
  the add-on is enabled and restored on unregister; unmarked Image Editors draw as
  usual.
- Factory buttons: ``shelf_data`` (generated) + ``shelf_map`` (Blender action, icon),
  run with ``marking.modal.run_action``. Click = command, double-click (or Ctrl+click)
  = options (Adjust Last Operation of that run), like Maya's doubleClickCommand.
- User shelves: ``shelves.json`` in the extension's user directory; a button runs
  its Python script (Maya ``-sourceType python``).
- Every factory button keeps its Maya slot. Buttons without a
  Blender action are drawn greyed; their tooltip and a click show the notice (``button_notice``) in the
  Help Line, like greyed Maya menu items.
- Ctrl+Shift+click on a Maya menu item adds a button for it to the shelf shown (as Maya does),
  factory tabs included. A menu button is ``{"label", "icon", "script": "", "menu":
  <Maya menu path>}`` and runs that path like the menu; on a factory tab it is stored in ``shelves.json``
  ``"extra"[<shelf id>]`` and drawn after the factory slots, so every factory button keeps its Maya slot.

Code: ``shelf_strip`` (the rows, sizes), ``shelf_store`` (contents, ``shelves.json``), ``shelf_run`` (running a
button), ``shelf_edit_ops`` (operators that change shelves), ``shelf_header`` (header buttons and menus),
``shelf_paint`` (GPU drawing); this module keeps the icon-row layout and scrolling, the icon-row drawing, the gizmos,
the Image Editor header swap and register / unregister, and re-exports the names of the others.
"""

import bpy
from bpy.props import IntProperty

from .. import i18n
from . import draw_replay, own_draw, shelf_data, shelf_icons

from .shelf_strip import (MARKER, SHELF_MARKER, STRIP_PX, is_strip, is_shelf_row, is_kit_row, strip_area,
                          shelf_row_area, marker_mask, make_strip, ALLSET_OT_shelf_strip_toggle, ICON_PX, PITCH_PX,
                          LEFT_PX, TAB_PX, TAB_LEFT_PX, TAB_PAD_PX, TAB_FONT_PX, STRIP_LEFT_PX, SEP_PX)  # noqa: F401
from .shelf_store import (USER_PREFIX, DEFAULT_USER, _user, _package, store_path, user_data, save_user, reload_user,
                          user_shelf, factory_extras, editable_buttons, button_record, factory_count, menu_label,
                          add_menu_item, shelves, all_buttons, button_labels, button_index, factory_buttons, current,
                          set_current)  # noqa: F401
from .shelf_run import (ShelfContextError, _run_in_editor_space, OPTIONS_TIP, record_tooltip, button_notice,
                        button_tooltip, run_script, DOUBLE_CLICK_S, _last_click, ALLSET_OT_shelf_button, _by_action,
                        menu_path_of, take_back_run, option_box)  # noqa: F401
from .shelf_edit_ops import (ALLSET_OT_shelf_select, ALLSET_OT_shelf_step, ALLSET_OT_shelf_new, ALLSET_OT_shelf_delete,
                             _valid_icon, ALLSET_OT_shelf_add_button, ALLSET_OT_shelf_edit_button,
                             ALLSET_OT_shelf_remove_button, ALLSET_MT_shelf_add_action, ALLSET_OT_shelf_add_action,
                             ALLSET_OT_shelf_add_last_command, _redraw, _deferred_redraw, schedule_redraw)  # noqa: F401
from .shelf_header import ALLSET_MT_shelf_tabs, ALLSET_MT_shelf_settings, draw_shelf, draw_shelf_tabs  # noqa: F401
from .shelf_paint import (_SHELF_SHADERS, _SHELF_BATCHES, _draw_rect, _theme_colour, _separator_colours, _hover_colour,
                          TAB_DIM, draw_tab_row, _hover, _tab_rects, tab_rects, _draw_tabs, _gear_tex, shelf_icons_gear,
                          _triangle, CHECKED_COLOUR, _checked)  # noqa: F401


_factory_cache = {}


def icon_buttons(context, cur=None):
    """(shelf id, [(button index, label, shelf colour key, mapped)]) of the current shelf (``cur``: the current shelf
    id already read), in Maya order (greyed buttons keep their slot)."""
    cur = current(context) if cur is None else cur
    if cur.startswith(USER_PREFIX):
        s = user_shelf(cur[len(USER_PREFIX):]) or {"buttons": []}
        return cur, [(i, b["label"], None, _record_mapped(b)) for i, b in enumerate(s["buttons"])]
    if cur not in _factory_cache:
        _factory_cache[cur] = [(i, label, cur, action is not None) for i, label, action, _icon in all_buttons(cur)]
    extras = factory_extras(cur)
    if not extras:
        return cur, _factory_cache[cur]
    n = len(_factory_cache[cur])          # added buttons after the Maya slots
    return cur, _factory_cache[cur] + [(n + k, b["label"], None, _record_mapped(b)) for k, b in enumerate(extras)]


def _record_mapped(b):
    if not b.get("menu"):
        return True
    from . import menu_map
    return b["menu"] in menu_map.MAP


def slot_button(context, slot):
    cur, buttons = icon_buttons(context)
    return (cur, buttons[slot]) if 0 <= slot < len(buttons) else (cur, None)


class ALLSET_OT_shelf_button_menu(bpy.types.Operator):
    """Open the actions for the shelf button under the pointer"""
    bl_idname = "allset.shelf_button_menu"
    bl_label = "Shelf Button Menu"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if not is_shelf_row(getattr(context, "space_data", None)) or context.region is None \
                or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        cur, buttons = icon_buttons(context)
        scale = context.preferences.system.ui_scale or 1.0
        for slot, button in enumerate(buttons):
            x, y, size = icon_rect(context.region, slot, scale)
            if x <= event.mouse_region_x < x + size and y <= event.mouse_region_y < y + size:
                index = button[0]
                record = button_record(cur, index)
                editable_index = index if cur.startswith(USER_PREFIX) else index - len(all_buttons(cur))

                def draw(menu, _context):
                    layout = menu.layout
                    layout.operator_context = 'INVOKE_DEFAULT'
                    op = layout.operator(ALLSET_OT_shelf_button.bl_idname, text="Open")
                    op.shelf, op.index = cur, index
                    row = layout.column()
                    row.enabled = record is not None
                    op = row.operator("allset.shelf_editor_open", text="Edit")
                    op.shelf_id, op.index = cur, editable_index
                    op = row.operator(ALLSET_OT_shelf_remove_button.bl_idname, text="Delete")
                    op.shelf, op.index = cur, editable_index

                context.window_manager.popover(draw, ui_units_x=10)
                return {'FINISHED'}
        return {'PASS_THROUGH'}


class ALLSET_OT_shelf_slot(bpy.types.Operator):
    """Shelf icon"""
    bl_idname = "allset.shelf_slot"
    bl_label = "Shelf Button"
    bl_options = {'INTERNAL'}

    slot: IntProperty()

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        cur, b = slot_button(context, props.slot)
        if b is None:
            return ""
        rec = button_record(cur, b[0])
        if rec is not None and (rec.get("menu") or rec.get("type") in {"action", "separator"}):
            return record_tooltip(rec)
        if cur.startswith(USER_PREFIX) or rec is not None:
            return f"{b[1]} (shelf)"
        return button_tooltip(cur, b[1], b[3])

    def invoke(self, context, event):
        cur, b = slot_button(context, self.slot)
        if b is None:
            return {'CANCELLED'}
        return bpy.ops.allset.shelf_button('INVOKE_DEFAULT', shelf=cur, index=b[0])


def _space_of(region):
    """The space of the area holding ``region`` (gizmo / draw contexts give it directly; tests pass bare regions)."""
    space = getattr(bpy.context, "space_data", None)
    area = getattr(bpy.context, "area", None)
    if area is not None and any(r == region for r in area.regions):
        return space
    for window in bpy.context.window_manager.windows:
        for a in window.screen.areas:
            if any(r == region for r in a.regions):
                return a.spaces.active
    return None


def tabs_in_window(space):
    """The shelf row draws its tab strip itself (no header region)."""
    return space is not None and is_shelf_row(space) and not space.show_region_header


def _gaps(cur=None):
    cur = current(bpy.context) if cur is None else cur
    return () if cur.startswith(USER_PREFIX) else shelf_data.GAPS.get(cur, ())


# Maya's shelf is a flow of rows one row high — buttons that don't fit wrap to the next row, a 12 px
# vertical scroll bar with up / down arrows sits at the right, the wheel over the icons moves one row
# (Maya: scroll bar page = single row 35 px, wheel = 1 row).
SCROLL_PX = 12
SCROLL_RIGHT_PX = 16     # gap between the scroll bar and the area's right edge
_row = {}      # shelf id -> first row shown


def row_layout(width, count, scale, gaps=(), left=STRIP_LEFT_PX, separators=()):
    """[(row, x)] for ``count`` slots in a row ``width`` px wide (scroll bar excluded): Maya's flow — a slot that
    would cross the right edge starts the next row; a separator gap before it counts only inside a row."""
    out = []
    x0 = left * scale
    limit = width - (SCROLL_PX + SCROLL_RIGHT_PX + 2) * scale
    row, x = 0, x0
    gaps = set(gaps)
    separators = set(separators)
    for slot in range(count):
        if slot in gaps and x > x0:
            x += SEP_PX * scale
        is_separator = slot in separators
        slot_width = 8 if is_separator else ICON_PX
        pitch = 12 if is_separator else PITCH_PX
        if x > x0 and x + slot_width * scale > limit:
            row, x = row + 1, x0
        out.append((row, x))
        x += pitch * scale
    return out


def _is_separator(record):
    return bool(record and (record.get("type") == "separator"
                            or (record.get("action") or {}).get("type") == "separator"))


def _separator_slots(cur, buttons):
    """Slots of ``buttons`` (``icon_buttons``) that are separators: only user-made buttons can be, so the stored
    records are read once (the Maya slots of a factory shelf have none)."""
    records = editable_buttons(cur) or []
    if not records:
        return frozenset()
    first = 0 if cur.startswith(USER_PREFIX) else factory_count(cur)
    out = set()
    for slot, (index, _label, _colour, _mapped) in enumerate(buttons):
        k = index - first
        if 0 <= k < len(records) and _is_separator(records[k]):
            out.add(slot)
    return frozenset(out)


def _plan(region, scale, cur=None):
    """(shelf id, tabs in the window, [(row, x)] per slot, buttons, separator slots) of the current shelf in
    ``region`` (``cur``: the current shelf id already read): read once and used for every slot of one redraw or one
    pick."""
    space = _space_of(region)
    tabs = tabs_in_window(space)
    cur, buttons = icon_buttons(bpy.context, cur)
    separator_slots = _separator_slots(cur, buttons)
    lay = row_layout(getattr(region, "width", 10 ** 6), len(buttons), scale, _gaps(cur) if tabs else (),
                     STRIP_LEFT_PX if tabs else LEFT_PX, separators=separator_slots)
    return cur, tabs, lay, buttons, separator_slots


def _layout(region, scale):
    return _plan(region, scale)[:3]


def rows_of(region, scale, plan=None):
    """(rows, first row shown) of the current shelf in ``region`` (``plan``: a ``_plan`` already read)."""
    cur, _tabs, lay = plan[:3] if plan is not None else _layout(region, scale)
    rows = (lay[-1][0] + 1) if lay else 1
    first = max(0, min(_row.get(cur, 0), rows - 1))
    return rows, first


def scroll_shelf(context, delta):
    """Move the current shelf ``delta`` rows (clamped); True when it moved."""
    region = context.region
    cur = current(context)
    rows, first = rows_of(region, context.preferences.system.ui_scale or 1.0)
    new = max(0, min(first + delta, rows - 1))
    _row[cur] = new
    region.tag_redraw()
    return new != first


def icon_rect(region, slot, scale):
    """(x, y, size) of ``slot`` in region pixels; a slot on another row than the one shown is placed past the right
    edge (not drawn, not picked)."""
    cur, tabs, lay = _layout(region, scale)
    _cur, buttons = icon_buttons(bpy.context)
    return _plan_rect((cur, tabs, lay, buttons, _separator_slots(cur, buttons)), region, slot, scale)


def _plan_rect(plan, region, slot, scale):
    """``icon_rect`` from a layout ``_plan`` already read."""
    cur, tabs, lay, buttons, separators = plan
    top = round(TAB_PX * scale) if tabs else 0
    is_separator = 0 <= slot < len(buttons) and slot in separators
    size = min((8 if is_separator else ICON_PX) * scale, region.height - top - 4)
    y = round((region.height - top - size) / 2)   # whole pixels keep icons sharp
    off = getattr(region, "width", 0) + 10 ** 6
    if slot >= len(lay):           # past the last button (tests ask for empty slots)
        return off, y, size
    row, x = lay[slot]
    rows = lay[-1][0] + 1
    if row != max(0, min(_row.get(cur, 0), rows - 1)):
        return off, y, size
    return x, y, size


def scroll_rects(region, scale, plan=None):
    """(up, down) rects (x0, y0, x1, y1) of the scroll bar's arrows, or () when every button fits in one row
    (``plan``: a ``_plan`` already read)."""
    rows, _first = rows_of(region, scale, plan)
    if rows <= 1:
        return ()
    tabs = plan[1] if plan is not None else tabs_in_window(_space_of(region))
    top = round(TAB_PX * scale) if tabs else 0
    # off the area's top-right corner: Blender's split / join action zone there takes the click before any region
    # (with --debug-handlers only "Screen Editing" sees the press)
    x1 = region.width - round(SCROLL_RIGHT_PX * scale)
    x0 = x1 - round(SCROLL_PX * scale)
    y0, y1 = round(2 * scale), region.height - top - round(2 * scale)
    mid = (y0 + y1) // 2
    return ((x0, mid, x1, y1), (x0, y0, x1, mid))


def _separators(region, s, count, plan=None):
    """x of each Maya separator before ``count`` drawn icons."""
    out = []
    plan = plan or _plan(region, s)
    for g in _gaps(plan[0]):
        if g < count:
            x, _y, size = _plan_rect(plan, region, g, s)
            out.append(x - (PITCH_PX - ICON_PX + SEP_PX) * s / 2)
    return out


def draw_row():
    """POST_PIXEL of image editors: the shelf icon row (background, hover box, icons; the tab strip when the row has
    no header). The gizmos only pick (draw handlers draw in plain region pixels; gizmo drawing in the image editor
    does not show)."""
    context = bpy.context
    if not is_shelf_row(context.space_data):
        return
    from . import status_line_row
    status_line_row.check(context)          # Status Line on again: the row comes back over the shelf
    region = context.region
    s = context.preferences.system.ui_scale
    key = ("shelf", region.as_pointer())
    sig = (region.width, region.height, s, _hover.get(region.as_pointer()))
    if draw_replay.again(key, sig):     # a window moves: the row as drawn last
        return
    with draw_replay.recording(key, sig):
        _draw_row(context, region, s)


def _draw_row(context, region, s):
    base = _theme_colour(context)
    _draw_rect(0, 0, region.width, region.height, base)
    tabs = tabs_in_window(context.space_data)
    cur = current(context)          # read once for the whole redraw
    if tabs:
        _draw_tabs(context, region, base, cur)
    plan = _plan(region, s, cur)
    _cur, buttons, separators = plan[0], plan[3], plan[4]
    hover = _hover.get(region.as_pointer())
    shown = 0
    for slot, (index, label, colour_key, mapped) in enumerate(buttons[:SLOTS]):
        x, y, size = _plan_rect(plan, region, slot, s)
        if x > region.width:
            continue                  # another row
        shown = slot + 1
        if slot in separators:
            # Keep the slot narrow, but draw a divider at nearly the full button height.
            separator_height = min(ICON_PX * s, region.height - (TAB_PX * s if tabs else 0) - 4)
            separator_y = (region.height - (TAB_PX * s if tabs else 0) - separator_height) / 2
            cx = x + size / 2
            dark, light = _separator_colours(base)
            _draw_rect(cx - s, separator_y, max(1.0, s), separator_height, dark)
            _draw_rect(cx, separator_y, max(1.0, s), separator_height, light)
            continue
        if _checked(context, button_record(_cur, index)):
            _draw_rect(x - 2, y - 2, size + 4, size + 4, CHECKED_COLOUR)
        if slot == hover:
            _draw_rect(x - 2, y - 2, size + 4, size + 4, _hover_colour(base, mapped))
        if colour_key is None:
            tex = _user_texture(_cur, index, label, not mapped, shelf_icons.texture_size(size))
        else:
            tex = shelf_icons.texture(label, colour_key, greyed=not mapped, size=shelf_icons.texture_size(size),
                                      index=index)
        _draw_rect(x, y, size, size, None, tex)
    if tabs:
        dark, light = _separator_colours(base)
        for x in _separators(region, s, shown, plan):   # Maya: a raised vertical rule in a 12 px gap
            _draw_rect(x - s, round(4 * s), max(1.0, s), size + 2 * s, dark)
            _draw_rect(x, round(4 * s), max(1.0, s), size + 2 * s, light)
    _draw_scroll_bar(region, s, base, plan)


def _draw_scroll_bar(region, s, base, plan=None):
    """The shelf scroll bar (12 px, ▲ / ▼) while the shelf has more than one row; an
    arrow is dimmed at its end (``plan``: the redraw's ``_plan``)."""
    plan = plan or _plan(region, s)
    rects = scroll_rects(region, s, plan)
    if not rects:
        return
    rows, first = rows_of(region, s, plan)
    up, down = rects
    _draw_rect(up[0], down[1], up[2] - up[0], up[3] - down[1], tuple(max(0.0, c - 0.06) for c in base[:3]) + (1.0,))
    hover = _hover.get(region.as_pointer())
    for i, (r, on) in enumerate(((up, first > 0), (down, first < rows - 1))):
        if hover == ("scroll", i) and on:
            _draw_rect(r[0], r[1], r[2] - r[0], r[3] - r[1], _hover_colour(base, True))
        grey = 0.75 if on else 0.4
        _triangle((r[0] + r[2]) / 2, (r[1] + r[3]) / 2, 3.5 * s, i == 0, (grey, grey, grey, 1.0))


def _user_texture(shelf_id, index, label, greyed, size):
    """Icon of a user-made button. A menu button shows the menu item's kit picture (``menu_icon_data``:
    the same command's shelf drawing, else its Status Line / Tool Box / menu drawing), else Maya's command button
    with the label's initials (Maya: the item's image, else a default command icon with a label)."""
    rec = button_record(shelf_id, index)
    if rec:
        chosen_icon = rec.get("icon", "SCRIPT")
        if chosen_icon not in {"", "NONE", "SCRIPT"}:
            custom_texture = shelf_icons.icon_gpu_texture(chosen_icon, greyed=greyed, size=size)
            if custom_texture is not None:
                return custom_texture
    path = rec.get("menu") if rec else None
    if path:
        from . import menu_icon_data, menu_icons
        pic = menu_icon_data.ICONS.get(path)
        if pic is not None and pic[0] == "shelf":
            return shelf_icons.texture(pic[2], pic[1], greyed=greyed, size=size, index=pic[3])
        if pic is not None:
            return shelf_icons.texture_of(("menu",) + tuple(pic), lambda n: menu_icons.picture(pic, n),
                                          greyed=greyed, size=size)
    return shelf_icons.texture(label, None, greyed=greyed, size=size)


class ALLSET_GT_shelf_tab(bpy.types.Gizmo):
    """Tab strip slot ``slot`` of ``tab_rects`` (the shelf menu, the gear, a tab): picking only, drawn by
    ``draw_row``; clicking runs allset.shelf_tab."""
    bl_idname = "ALLSET_GT_shelf_tab"
    __slots__ = ("slot",)

    def setup(self):
        self.slot = 0

    def draw(self, context):
        pass

    def test_select(self, context, location):
        if not tabs_in_window(context.space_data):
            return -1
        key = context.region.as_pointer()
        rects = _tab_rects.get(key) or tab_rects(context, context.region)
        hit = self.slot < len(rects) and rects[self.slot][0] <= location[0] <= rects[self.slot][2] \
            and rects[self.slot][1] <= location[1] <= rects[self.slot][3]
        tag = ("tab", rects[self.slot][4]) if self.slot < len(rects) else None
        if hit:
            if _hover.get(key) != tag:
                _hover[key] = tag
                context.region.tag_redraw()
            return 0
        if tag is not None and _hover.get(key) == tag:
            _hover.pop(key, None)
            context.region.tag_redraw()
        return -1


class ALLSET_OT_shelf_tab(bpy.types.Operator):
    """Shelf tab strip: show this shelf, or open the shelf menu"""
    bl_idname = "allset.shelf_tab"
    bl_label = "Shelf Tab"
    bl_options = {'INTERNAL'}

    slot: IntProperty()

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        rects = _tab_rects.get(context.region.as_pointer()) if context.region else None
        action = rects[props.slot][4] if rects and props.slot < len(rects) else ""
        if action == "menu":
            return "Shelf menu: choose a shelf"
        if action == "gear":
            return "Shelf editor: new / delete shelf, add / edit / remove buttons"
        return f"Show the {dict(shelves()).get(action, action)} shelf"

    def invoke(self, context, event):
        rects = _tab_rects.get(context.region.as_pointer()) if context.region else None
        if not rects or self.slot >= len(rects):
            return {'CANCELLED'}
        action = rects[self.slot][4]
        if action in {"menu", "gear"} and event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # Open after release so the opening click cannot choose a menu item.
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        _hover.pop(context.region.as_pointer(), None)
        if action == "menu":
            bpy.ops.wm.call_menu(name=ALLSET_MT_shelf_tabs.bl_idname)
        elif action == "gear":
            # Popovers have no last-item memory that could put Delete Shelf under the cursor.
            context.window_manager.popover(ALLSET_MT_shelf_settings.draw, ui_units_x=14)
        else:
            set_current(context, action)
            _redraw(context)
        return {'FINISHED'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE', 'WINDOW_DEACTIVATE'}:
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            rects = _tab_rects.get(context.region.as_pointer()) if context.region else None
            if not rects or self.slot >= len(rects):
                return {'CANCELLED'}
            x0, y0, x1, y1, _ = rects[self.slot]
            if not (x0 <= event.mouse_region_x <= x1 and y0 <= event.mouse_region_y <= y1):
                return {'CANCELLED'}
            return self.invoke(context, event)
        return {'RUNNING_MODAL'}


TAB_SLOTS = 24


class ALLSET_GT_shelf_icon(bpy.types.Gizmo):
    """Shelf slot ``slot`` (the current shelf's button there): picking only, drawn by ``draw_row``;
    clicking runs allset.shelf_slot (its target operator). A fixed pool, so switching shelves needs
    no rebuild."""
    bl_idname = "ALLSET_GT_shelf_icon"
    __slots__ = ("slot",)

    def setup(self):
        self.slot = 0

    def draw(self, context):
        pass

    def test_select(self, context, location):
        key = context.region.as_pointer()
        hit = slot_button(context, self.slot)[1] is not None
        if hit and tabs_in_window(context.space_data) \
                and location[1] > context.region.height - TAB_PX * context.preferences.system.ui_scale:
            hit = False
        if hit:
            x, y, size = icon_rect(context.region, self.slot, context.preferences.system.ui_scale)
            hit = x <= location[0] <= x + size and y <= location[1] <= y + size
        if hit:
            if _hover.get(key) != self.slot:
                _hover[key] = self.slot
                context.region.tag_redraw()
            return 0
        if _hover.get(key) == self.slot:
            _hover.pop(key, None)
            context.region.tag_redraw()
        return -1


class ALLSET_GT_shelf_scroll(bpy.types.Gizmo):
    """The shelf scroll bar's up (slot 0) / down (slot 1) arrow: picking only, drawn by ``draw_row``. Gizmos come
    before the image editor's tool keymap (its Sample tool took plain clicks)."""
    bl_idname = "ALLSET_GT_shelf_scroll"
    __slots__ = ("slot",)

    def setup(self):
        self.slot = 0

    def draw(self, context):
        pass

    def test_select(self, context, location):
        key = context.region.as_pointer()
        rects = scroll_rects(context.region, context.preferences.system.ui_scale or 1.0)
        r = rects[self.slot] if rects else None
        tag = ("scroll", self.slot)
        if r is not None and r[0] <= location[0] <= r[2] and r[1] <= location[1] <= r[3]:
            if _hover.get(key) != tag:
                _hover[key] = tag
                context.region.tag_redraw()
            return 0
        if _hover.get(key) == tag:
            _hover.pop(key, None)
            context.region.tag_redraw()
        return -1


class ALLSET_OT_shelf_scroll(bpy.types.Operator):
    """Scroll the shelf one row (Maya: the shelf's scroll bar / the mouse wheel over the icons)"""
    bl_idname = "allset.shelf_scroll"
    bl_label = "Scroll Shelf"
    bl_options = {'INTERNAL'}

    delta: IntProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if not is_shelf_row(getattr(context, "space_data", None)) or context.region is None \
                or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}        # the items sit first in "Image": any other image editor zooms / samples
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and (event.ctrl or event.shift or event.alt):
            return {'PASS_THROUGH'}
        return self.execute(context)

    def execute(self, context):
        if context.region is None:
            return {'CANCELLED'}
        scroll_shelf(context, self.delta)
        return {'FINISHED'}


SLOTS = 64   # more than the largest factory shelf (Poly Modeling, 37 buttons)


class ALLSET_GGT_shelf(bpy.types.GizmoGroup):
    bl_idname = "ALLSET_GGT_shelf"
    bl_label = "Maya Shelf"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        return is_shelf_row(context.space_data)

    def setup(self, context):
        for slot in range(SLOTS):
            gz = self.gizmos.new(ALLSET_GT_shelf_icon.bl_idname)
            gz.slot = slot
            gz.target_set_operator(ALLSET_OT_shelf_slot.bl_idname).slot = slot
        for slot in range(TAB_SLOTS):
            gz = self.gizmos.new(ALLSET_GT_shelf_tab.bl_idname)
            gz.slot = slot
            gz.target_set_operator(ALLSET_OT_shelf_tab.bl_idname).slot = slot
        for slot, delta in ((0, -1), (1, 1)):          # the scroll bar's arrows
            gz = self.gizmos.new(ALLSET_GT_shelf_scroll.bl_idname)
            gz.slot = slot
            gz.target_set_operator(ALLSET_OT_shelf_scroll.bl_idname).delta = delta


@own_draw.kit_draw("IMAGE_HT_header")
def _draw_image_header(self, context):
    if is_strip(context.space_data):
        from . import status_line_row
        status_line_row.check(context)      # Status Line off: the row goes (another workspace's screen too)
        if not status_line_row.wanted(context):
            return None
        from .status_line import draw_status_line
        return draw_status_line(self.layout, context)
    if is_shelf_row(context.space_data):
        return draw_shelf_tabs(self.layout, context)
    from .editor_chrome import draw_uv_header   # Maya UV Editor menu bar
    if draw_uv_header(self, context):
        return None
    from .render_view import draw_header   # Render View Keep / Remove Image: first, like Maya's
    draw_header(self.layout, context)       # toolbar, so a small render window doesn't clip them
    return own_draw.original("IMAGE_HT_header", _draw_image_header)(self, context)


@own_draw.kit_draw("IMAGE_HT_tool_header")
def _draw_image_tool_header(self, context):
    if is_strip(context.space_data):
        from . import status_line_row
        status_line_row.check(context)
        return draw_shelf(self.layout, context)
    from .editor_chrome import draw_uv_tool_header   # Maya UV Editor icon row
    if draw_uv_tool_header(self, context):
        return None
    return own_draw.original("IMAGE_HT_tool_header", _draw_image_tool_header)(self, context)


def patch_image_headers():
    """Blender's own Image Editor header draws only: others' appended items keep drawing."""
    own_draw.swap("IMAGE_HT_header", _draw_image_header)
    own_draw.swap("IMAGE_HT_tool_header", _draw_image_tool_header)


def unpatch_image_headers():
    own_draw.restore("IMAGE_HT_header", _draw_image_header)
    own_draw.restore("IMAGE_HT_tool_header", _draw_image_tool_header)


classes = (ALLSET_OT_shelf_button, ALLSET_OT_shelf_select, ALLSET_OT_shelf_step,
           ALLSET_OT_shelf_new, ALLSET_OT_shelf_delete, ALLSET_OT_shelf_add_button,
           ALLSET_OT_shelf_edit_button, ALLSET_OT_shelf_remove_button,
           ALLSET_MT_shelf_add_action, ALLSET_OT_shelf_add_action, ALLSET_OT_shelf_add_last_command,
           ALLSET_OT_shelf_strip_toggle, ALLSET_MT_shelf_tabs, ALLSET_MT_shelf_settings,
           ALLSET_OT_shelf_button_menu,
           ALLSET_OT_shelf_slot, ALLSET_GT_shelf_icon, ALLSET_GT_shelf_tab, ALLSET_OT_shelf_tab,
           ALLSET_GT_shelf_scroll, ALLSET_OT_shelf_scroll, ALLSET_GGT_shelf)


_handle = []


def settle_rows():
    """Shelf rows of files made by older versions: switch the image navigation gizmo off (it sat, undrawn, under the
    scroll bar and took its clicks); a strip or shelf row an older shelf UV Editor button switched to the UV Editor
    goes back to showing the strip. Run from a timer / load_post, never from drawing."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            space = area.spaces.active
            if area.type != 'IMAGE_EDITOR' or not is_kit_row(space):
                continue
            if space.mode != 'VIEW':
                space.mode = 'VIEW'
                area.tag_redraw()
            if is_shelf_row(space) and space.show_gizmo_navigate:
                space.show_gizmo_navigate = False


def _settle_later():
    try:
        settle_rows()
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    return None


@bpy.app.handlers.persistent
def _on_load(_dummy):
    if not bpy.app.timers.is_registered(_settle_later):
        bpy.app.timers.register(_settle_later, first_interval=0.1)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    patch_image_headers()
    _handle.append((bpy.types.SpaceImageEditor.draw_handler_add(draw_row, (), 'WINDOW', 'POST_PIXEL'), 'WINDOW'))
    _handle.append((bpy.types.SpaceImageEditor.draw_handler_add(draw_tab_row, (), 'HEADER', 'POST_PIXEL'),
                    'HEADER'))
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.timers.register(_settle_later, first_interval=0.1)


def unregister():
    from . import status_line_row
    status_line_row.stop()
    if bpy.app.timers.is_registered(_deferred_redraw):
        bpy.app.timers.unregister(_deferred_redraw)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if bpy.app.timers.is_registered(_settle_later):
        bpy.app.timers.unregister(_settle_later)
    while _handle:
        bpy.types.SpaceImageEditor.draw_handler_remove(*_handle.pop())
    shelf_icons.clear()
    _SHELF_BATCHES.clear()
    _SHELF_SHADERS.clear()
    _factory_cache.clear()
    _hover.clear()
    _tab_rects.clear()
    _gear_tex.clear()
    _last_click.clear()
    _by_action.clear()
    _row.clear()
    unpatch_image_headers()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    _user.clear()
