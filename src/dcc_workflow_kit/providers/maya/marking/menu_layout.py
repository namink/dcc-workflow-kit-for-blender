# SPDX-License-Identifier: GPL-3.0-or-later
"""Marking menu geometry without Blender: sizes at UI scale 1 (``Params``), the radial sector of a stroke
(``direction``), the item rectangles of one (sub)menu around its centre (``Layout``, ``Item``: radial boxes and the
list under the ring), which items are check boxes (``is_toggle``) and which show a command picture left of their
label (``icon_data``, like Maya). Used by ``engine`` (``Session``) and
``hotbox_engine``; ``draw.py`` reads them through ``engine``."""

import math

from . import icon_data
from . import menus as mm


# Sector order for atan2 angles (0 = east, counter-clockwise, 45 degrees each).
_SECTORS = ("E", "NE", "N", "NW", "W", "SW", "S", "SE")
_UNIT = {name: (math.cos(math.radians(45 * i)), math.sin(math.radians(45 * i)))
         for i, name in enumerate(_SECTORS)}


class Params:
    """Sizes in pixels at UI scale 1 (``scaled`` multiplies them)."""
    # Radial ring = Maya's (#99):
    # N / S box centres and E / W near sides ``radius`` from the press point, diagonal boxes with their corner at
    # (±d, ±d), d = radius·cos 45°; boxes 21 px high, text + 2 × 25 px wide (+ 5 with an option box).
    radius = 55.0          # centre -> radial item anchor
    dead = 12.0            # no direction inside this (= Blender pie_menu_threshold): click mode, back-out, marks
    pick_dead = 10.0       # this near the centre or nearer nothing is highlighted or picked
    item_h = 22.0          # list rows
    pad = 8.0              # text padding inside a list row / hotbox label
    opt_w = 16.0           # option box square
    list_gap = 10.0
    ring_h = 21.0          # radial box height
    ring_pad = 25.0        # text padding inside a radial box (a submenu arrow sits in the right one)
    ring_opt = 5.0         # extra radial box width for an option box
    ring_list_gap = 21.0   # ring bottom -> list top
    # A command picture left of the label (like Maya): ``icon`` px square, in a radial box ``icon_pad`` from its left
    # side (in the left text padding), in a list ``list_icon_pad`` from the row's left; ``icon_gap`` to the text. A
    # list with a picture on any row keeps the picture column on every row, so the labels stay in one column.
    icon = 16.0
    icon_pad = 5.0
    list_icon_pad = 4.0
    icon_gap = 5.0
    show_delay = 0.15      # s before the menu is drawn: faster strokes are "marks"
    click_time = 0.25      # s: a shorter press-release in the dead zone = click mode
    # A quick release is a mark, like Maya: the radial item of its direction, never a list row it ends on (a mark that
    # ends on a radial submenu item runs nothing; one that goes on past it picks in that submenu, by the direction
    # from the item's box centre). The kit counts a release sooner than ``mark_time`` s after the press.
    mark_time = 0.11
    # A release right after the press runs nothing at all, like Maya, also on a radial leaf item (a quick click in the
    # centre still keeps the menu up; not with the Quick Gestures option). The kit's window: ``quick_none_time`` s.
    quick_none_time = 0.10
    # A radial item's submenu opens when the pointer rests on it (its box, or beyond the box seen from the centre)
    # while the menu is drawn, like Maya: a stroke that keeps moving goes over it, so the list under the ring and the
    # other side of the ring stay reachable. The kit's rest: ``open_dwell`` s, moving less than ``rest_slop`` px.
    open_dwell = 0.1
    rest_slop = 2.0
    # Options (add-on preferences, both off by default; marking/modal.py copies them in):
    # quick_gestures (mm_quick_gestures): the menu stays hidden while the pointer keeps moving and shows after a
    # pause of ``show_delay`` (then stays); a radial submenu entered by a hidden mark stays hidden too; a hidden mark
    # picks radial items only, by the stroke's heading (gesture_recognition.py), and draw.py shows the names of the
    # submenus it passed. Off: the menu shows ``show_delay`` after the press and once a submenu opens.
    quick_gestures = False
    # submenu_guides (mm_submenu_guides): a radial submenu is linked to the centre it opened from, with a ring there;
    # resting within ``anchor_r`` of it for ``return_dwell`` s goes back to that menu (``Session._dwell_back``); the
    # line from the centre to the pointer shows only near a centre.
    submenu_guides = False
    anchor_r = 33.0
    return_dwell = 0.7

    SIZES = ("radius", "dead", "pick_dead", "item_h", "pad", "opt_w", "list_gap", "ring_h", "ring_pad", "ring_opt",
             "ring_list_gap", "anchor_r", "rest_slop", "icon", "icon_pad", "list_icon_pad", "icon_gap")
    FLAGS = ("show_delay", "click_time", "mark_time", "quick_none_time", "return_dwell", "quick_gestures",
             "submenu_guides", "open_dwell")

    def scaled(self, k):
        p = Params()
        for name in self.SIZES:
            setattr(p, name, getattr(self, name) * k)
        for name in self.FLAGS:
            setattr(p, name, getattr(self, name))
        return p


def direction(dx, dy, dead):
    """Radial sector of a vector, or None inside the dead zone."""
    if math.hypot(dx, dy) < dead:
        return None
    angle = math.degrees(math.atan2(dy, dx)) % 360.0
    return _SECTORS[int((angle + 22.5) // 45) % 8]


class Item:
    __slots__ = ("label", "action", "kind", "key", "rect", "opt_rect", "enabled", "sub", "option", "icon", "icon_x",
                 "text_x")

    def __init__(self, label, action, kind, key, rect, opt_rect, enabled, option, icon=None, icon_x=0.0, text_x=0.0):
        self.label = label
        self.action = action
        self.kind = kind              # "radial" | "list"
        self.key = key                # radial name or list index
        self.rect = rect              # (x0, y0, x1, y1), relative to the layout centre
        self.opt_rect = opt_rect      # option box rect or None
        self.enabled = enabled
        self.sub = action if isinstance(action, mm.Sub) else None
        self.option = option
        self.icon = icon              # icon_data picture drawn left of the label, or None
        self.icon_x = icon_x          # picture's left / text start, from the rect's left side
        self.text_x = text_x

    def __repr__(self):
        return f"Item({self.label!r}, {self.key!r})"


def _inside(rect, x, y):
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


TOGGLE_OPS = ("wm.context_toggle", "allset.prevent_negative_scale", "allset.xform_constraint", "allset.manip_option", "allset.symmetry", "allset.component_mask",
              "allset.pivot_option", "allset.mm_camera_based", "allset.uv_step_snap")
# Shift+Q pick mask: Poly Vertices / Poly Edges / Faces are check boxes, "All Components on" is a command.
MASK_CHECKS = ("VERT", "EDGE", "FACE")


def is_toggle(action):
    """An on/off item (Maya check box menu item): shows its state in the menu."""
    if not (isinstance(action, tuple) and len(action) == 2 and action[0] in TOGGLE_OPS):
        return False
    return action[0] != "allset.component_mask" or action[1].get("kind") in MASK_CHECKS


class Layout:
    """Item rectangles of one (sub)menu around its centre (Maya placement)."""

    def __init__(self, sub, measure, params, enabled=None, path=None):
        """``path``: the menu id and the labels leading to ``sub`` (``menus.label_walk``), which picks the item
        pictures (``icon_data``); None = no pictures."""
        self.sub = sub
        self.path = path
        self.params = p = params

        def icon(label):
            return icon_data.ICONS.get(f"{path}/{label}") if path else None

        enabled = enabled or (lambda action: action is not None and not mm.is_unavailable(action))
        self.radial = {}
        self.items = []
        h = p.item_h
        for key in mm.RADIALS:
            if key not in sub.radial:
                continue
            label, action = sub.radial[key]
            opt = label in sub.options and action is not None and not isinstance(action, mm.Sub)
            pic = icon(label)
            item = Item(label, action, "radial", key,
                        self.ring_rect(key, measure(self.ring_text(label, action)), opt, pic is not None),
                        None, enabled(action), opt, pic, p.icon_pad,
                        p.icon_pad + p.icon + p.icon_gap if pic is not None else p.ring_pad)
            item.opt_rect = self._opt(item.rect, opt)
            self.radial[key] = item
            self.items.append(item)
        # Linear list under the ring (or from the centre when there is no ring).
        rows = [e for e in sub.items]
        if rows:
            widths = [measure(self._text(e[0], e[1])) for e in rows if e != mm.DIVIDER]
            pics = {i: icon(e[0]) for i, e in enumerate(rows) if e != mm.DIVIDER}
            text_x = p.list_icon_pad + p.icon + p.icon_gap if any(v is not None for v in pics.values()) else p.pad
            w = max(widths or [0]) + text_x + p.pad + p.opt_w
            if self.radial:
                top = min([it.rect[1] for it in self.radial.values()] + [-p.radius]) - p.ring_list_gap
                x0 = -w / 2
            else:
                top = h / 2
                x0 = p.dead
            y = top
            for i, entry in enumerate(rows):
                if entry == mm.DIVIDER:
                    y -= p.list_gap / 2
                    continue
                label, action = entry
                opt = label in sub.options and action is not None and not isinstance(action, mm.Sub)
                rect = (x0, y - h, x0 + w, y)
                self.items.append(Item(label, action, "list", i, rect, self._opt(rect, opt),
                                       enabled(action), opt, pics[i], p.list_icon_pad, text_x))
                y -= h

    def ring_rect(self, key, text_w, opt=False, icon=False):
        """Rect of the radial box ``key`` whose text is ``text_w`` wide: Maya's placement.
        y is up here, so N is +y. ``icon``: a picture left of the text takes the left padding's place."""
        p = self.params
        r, h = p.radius, p.ring_h
        d = r * math.cos(math.radians(45.0))
        left = p.icon_pad + p.icon + p.icon_gap if icon else p.ring_pad
        w = text_w + left + p.ring_pad + (p.ring_opt if opt else 0.0)
        if key in ("N", "S"):
            x0 = -w / 2
            cy = r if key == "N" else -r
            return (x0, cy - h / 2, x0 + w, cy + h / 2)
        x0 = r if key == "E" else -r - w if key == "W" else d if key in ("NE", "SE") else -d - w
        if key in ("E", "W"):
            y0 = -h / 2
        else:   # diagonal: the outer side on the diagonal anchor, the box hanging towards the horizontal axis
            y0 = d - h if key in ("NE", "NW") else -d
        return (x0, y0, x0 + w, y0 + h)

    @staticmethod
    def has_arrow(action):
        """A submenu item: Maya draws a ▸ at the box / row's right (a Blender ("menu", id) opens as one too)."""
        return isinstance(action, mm.Sub) or (isinstance(action, tuple) and action[0] == "menu")

    @staticmethod
    def ring_text(label, action):
        """Text that sizes a radial box: the arrow lives in the right padding,
        toggles keep room for their check box."""
        return label + ("    " if is_toggle(action) and not Layout.has_arrow(action) else "")

    @staticmethod
    def _text(label, action):
        # Toggles keep room on the right for their check box (draw.py).
        # A Blender menu ("menu", id) opens as a submenu too (e.g. Assign Existing Material).
        return label + (" ▸" if Layout.has_arrow(action) else "    " if is_toggle(action) else "")

    def _opt(self, rect, on):
        if not on:
            return None
        s = self.params.opt_w
        return (rect[2] - s, rect[1] + (rect[3] - rect[1] - s) / 2,
                rect[2], rect[1] + (rect[3] - rect[1] + s) / 2)

    def hit(self, dx, dy, rects_only=False, wedges=False):
        """(item, on_option_box) under a point relative to the centre, or (None, False).

        Rectangles win (list rows, option boxes, radial boxes); otherwise, outside the dead zone, the radial item
        whose box centre lies in the direction nearest to the pointer's, like Maya: the sectors follow the boxes
        (a wide diagonal box takes more of the side next to it) and every direction has an item, also in a menu
        with few; below the top of the list under the ring, nothing off its rows (``Session`` keeps a radial item
        highlighted there when the pointer comes to it from that item). Not with ``rects_only``;
        ``wedges``: the item of the pointer's 45° sector, None for an empty one.
        """
        for it in self.items:
            if it.opt_rect and _inside(it.opt_rect, dx, dy):
                return it, True
            if _inside(it.rect, dx, dy):
                return it, False
        if rects_only:
            return None, False
        if wedges:
            d = direction(dx, dy, self.params.dead)
            return (self.radial[d], False) if d in self.radial else (None, False)
        if self.below_list(dx, dy):
            return None, False     # below the top of the list only its rows count, like Maya
        return self.nearest_radial(dx, dy), False

    def below_list(self, dx, dy):
        """(dx, dy) lies below the top of the list hanging under the ring, across the whole menu's width (not
        when there is no ring or the list was moved beside it to fit the area)."""
        rows = [it.rect[3] for it in self.items if it.kind == "list"]
        ring = [it.rect[1] for it in self.items if it.kind == "radial"]
        return bool(rows and ring) and max(rows) <= min(ring) and dy < max(rows)

    def nearest_radial(self, dx, dy):
        """The radial item whose box centre direction is nearest to (dx, dy) (ties: the first in N, NE, E, ...
        order), or None within ``pick_dead`` of the centre or with no radial items."""
        if math.hypot(dx, dy) <= self.params.pick_dead:
            return None
        a = math.atan2(dy, dx)
        best, best_d = None, None
        for it in self.items:
            if it.kind != "radial":
                continue
            r = it.rect
            d = abs((math.atan2((r[1] + r[3]) / 2, (r[0] + r[2]) / 2) - a + math.pi) % (2 * math.pi) - math.pi)
            if best_d is None or d < best_d - 1e-9:
                best, best_d = it, d
        return best
