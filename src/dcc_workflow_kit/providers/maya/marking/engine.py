# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya marking menu and hotbox logic, without Blender.

Coordinates are region pixels (y up, as Blender's ``mouse_region_*``). Text
width comes from a ``measure(text) -> width`` callback (``blf`` in Blender, a
character count in tests), so everything here is testable headless.

Maya behaviour: radial slots, list
under the ring, hotbox zones and rows, press/release,
tap vs hold.

Code: ``menu_layout`` (Params, Layout, direction), ``ring_fit`` (fit_ring), ``hotbox_engine`` (HotboxLayout,
HoldKey, is_tap); this module keeps ``Session``, one marking menu interaction, and re-exports the rest.
"""

import math

from .gesture_recognition import GestureRecognizer
# the split-out parts, also read through this module by draw.py, modal.py and the tests
from .menu_layout import (_SECTORS, _UNIT, MASK_CHECKS, TOGGLE_OPS, Item, Layout, Params, _inside,  # noqa: F401
                          direction, is_toggle)
from .ring_fit import MIN_COLUMN_ROWS, _rel_edges, _settle_list, fit_ring  # noqa: F401
from .hotbox_engine import (MENU_DRAG, RELEASE_GRACE, TAP_TIME, UP_TIME, HoldKey, HotboxLayout,  # noqa: F401
                            is_tap, menu_drag, restart_too_soon)


def _segment_meets(rect, dx, dy):
    """The segment from (0, 0) to (dx, dy) runs through the rectangle (x0, y0, x1, y1): a segment that only grazes
    a corner does not count (the point itself on the box is ``_inside``)."""
    lo, hi = 0.0, 1.0
    for d, a, b in ((dx, rect[0], rect[2]), (dy, rect[1], rect[3])):
        if abs(d) < 1e-12:
            if not a < 0.0 < b:
                return False
            continue
        t0, t1 = sorted((a / d, b / d))
        lo, hi = max(lo, t0), min(hi, t1)
    return hi - lo > 1e-9


class Session:
    """One marking-menu interaction.

    ``press``-driven: created on the button press at ``origin``; feed
    ``move`` / ``release`` / ``click``. ``result`` becomes
    ``("RUN", item, option)`` or ``("CANCEL", None, False)``; ``None`` while open.
    """

    def __init__(self, menu, origin, t0, measure, params=None, enabled=None, bounds=None, edges=()):
        """``bounds`` = (x0, y0, x1, y1): the visible part of the region; list
        submenus that would cross it are moved inside. ``edges`` = area
        border bands in region pixels (``fit_ring``)."""
        self.params = params or Params()
        self.bounds = bounds
        self.edges = tuple(edges) if bounds is not None else ()
        root = Layout(menu, measure, self.params, enabled, getattr(menu, "name", None))
        self.press = origin
        if bounds is not None:
            fit_ring(root, origin, bounds, self.edges)
        self.measure = measure
        self.enabled = enabled
        self.t0 = t0
        self.stack = [(root, origin)]
        # Per stack level: the item of the level below that opened it, when it is a list row's cascade (a Qt
        # menu submenu beside the row): the menus under a cascade stay drawn and hit-tested. In-place
        # radial submenus (None) replace the menu, like Maya's.
        self.openers = [None]
        self.via = [None]             # per stack level: the item of the level below that opened it (every kind)
        self._closed = None           # the item whose submenu Esc closed: it doesn't reopen on hover
        self.mode = "PRESS"           # "PRESS" (button held) | "CLICK" (menu stays open)
        self.pos = self.press
        self.trail = [self.press]
        self.hover = (None, False)
        self.result = None
        self.max_dist = 0.0
        self._dwell = None            # (level, time) since the pointer rests on the centre that level opened from
        self._rest = None             # (radial submenu item, time, (x, y)): the pointer resting on it (opens it)
        # when the menu was first drawn (a rest before that counts from then)
        self._shown_at = None if self.params.quick_gestures else t0 + self.params.show_delay
        self.time = t0                # of the last pointer event
        # Quick Gestures option: the last pointer move, whether the menu was drawn (stays), whether a hidden mark
        # entered a radial submenu (it stays hidden till the release), the route's menus [(centre, name)] and the
        # heading of the stroke on the top level
        self._last_move = t0
        self._shown = False
        self._fast_marking = False
        self.route = [(origin, getattr(menu, "label", "") or "")]
        self._gesture = GestureRecognizer()
        self._gesture.reset(origin, t0)

    # -- state --------------------------------------------------------------
    @property
    def layout(self):
        return self.stack[-1][0]

    @property
    def center(self):
        return self.stack[-1][1]

    def visible(self, t):
        """Draw the menu? Not during a quick stroke (mark without looking). Quick Gestures option: not while the
        pointer keeps moving - a pause of ``show_delay`` shows it for the rest of the interaction - and not after a
        hidden mark entered a submenu."""
        if not self.params.quick_gestures:
            return self.mode == "CLICK" or len(self.stack) > 1 or t - self.t0 >= self.params.show_delay
        if self.mode == "CLICK":
            return True
        if self._fast_marking:
            return False
        if not self._shown and t - self._last_move >= self.params.show_delay:
            self._shown = True
            self._shown_at = self._last_move + self.params.show_delay
        return self._shown

    def _rel(self, x, y):
        return x - self.center[0], y - self.center[1]

    def layers(self):
        """[(layout, centre, (hovered item, on option box))] to draw, bottom first: the top menu and, under an
        open cascade, the menus it hangs from (their hovered row = the cascade's opener)."""
        top = len(self.stack) - 1
        level = top
        while self.openers[level] is not None:
            level -= 1
        out = []
        for k in range(level, top + 1):
            lay, center = self.stack[k]
            out.append((lay, center, self.hover if k == top else (self.openers[k + 1], False)))
        return out

    def _push(self, item, at, cascade=False):
        owner = next((lay for lay, _c in reversed(self.stack) if item in lay.items), None)
        path = f"{owner.path}/{item.label}" if owner is not None and owner.path else None
        layout = Layout(item.sub, self.measure, self.params, self.enabled, path)
        if self.bounds is not None and layout.items and not layout.radial:
            at = self._inside_bounds(layout, at)
        elif self.bounds is not None and layout.items:
            fit_ring(layout, at, self.bounds, self.edges)   # in-place radial: centre = pointer
        self.stack.append((layout, at))
        self.openers.append(item if cascade else None)
        self.via.append(item)
        self.hover = (None, False)
        self._rest = None
        if self.params.quick_gestures:
            if self.mode == "PRESS" and not self._shown and not cascade:
                self._fast_marking = True
                self.route.append((at, item.label))
            self._gesture.reset(at, self.time)      # the submenu's own strokes start where it opened

    def _pop_to(self, level):
        del self.stack[level + 1:]
        del self.openers[level + 1:]
        del self.via[level + 1:]
        self._rest = None
        if self.params.quick_gestures:
            self._gesture.reset(self.stack[-1][1], self.time)

    def _leave_sub(self, x, y, items=True):
        """Back out of an in-place radial submenu: with nothing of it under the pointer and the pointer back
        inside the ring of the menu it opened from, it closes and that menu is there again, like Maya's. Its own
        items are looked at first, so a submenu item lying toward the parent keeps it open and the way back is an
        empty sector. Not for a list row's cascade (hovering another row of its menu closes that). The line is the
        ring radius less the dead zone from the parent's centre, and nearer for a submenu that opened inside the
        ring (a click on the inner part of a box), so it never closes on the spot. Returns True when one closed."""
        if len(self.stack) < 2 or self.openers[-1] is not None:
            return False
        p = self.params
        (_parent, (px, py)), (sub, (sx, sy)) = self.stack[-2], self.stack[-1]
        if math.hypot(x - px, y - py) >= min(p.radius, math.hypot(sx - px, sy - py)) - p.dead:
            return False
        if items and sub.hit(x - sx, y - sy, wedges=True)[0] is not None:
            return False     # an item of the submenu lies that way (its box, or an item in that 45° sector)
        self._pop_to(len(self.stack) - 2)
        return True

    def _dwell_back(self, x, y, t):
        """Back out of an in-place radial submenu whose item lies toward the menu it opened from (``_leave_sub``
        only goes back through an empty sector): the pointer resting within ``anchor_r`` of that menu's centre,
        off the submenu's boxes and away from its own centre, for ``return_dwell`` s closes it. A quick stroke
        through that centre (a two-stroke mark) never rests long enough. Returns True when one closed."""
        top = len(self.stack) - 1
        if top < 1 or self.openers[top] is not None:
            self._dwell = None
            return False
        p = self.params
        lay, (cx, cy) = self.stack[top]
        px, py = self.stack[top - 1][1]
        if math.hypot(x - px, y - py) > p.anchor_r or math.hypot(x - cx, y - cy) < p.anchor_r \
                or lay.hit(x - cx, y - cy, rects_only=True)[0] is not None:
            self._dwell = None
            return False
        if self._dwell is None or self._dwell[0] != top:
            self._dwell = (top, t)
        if t - self._dwell[1] < p.return_dwell:
            return False
        self._dwell = None
        self._pop_to(top - 1)
        return True

    def anchors(self):
        """[(parent centre, submenu centre)] for each open in-place radial submenu, bottom first: draw.py links
        them and rings the parent centre (the way back)."""
        return [(self.stack[k - 1][1], self.stack[k][1]) for k in range(1, len(self.stack))
                if self.openers[k] is None]

    def dwell_progress(self, t):
        """(parent centre, 0..1) while the pointer rests on the centre the top submenu goes back to, else None."""
        if self._dwell is None or self._dwell[0] != len(self.stack) - 1:
            return None
        return self.stack[self._dwell[0] - 1][1], min(1.0, (t - self._dwell[1]) / self.params.return_dwell)

    def tick(self, t):
        """Timer: a rest on a radial submenu item opens it, a rest on a parent centre closes the submenu, without a
        mouse move. True when the menu changed or a return rest runs."""
        opened = self._open_rested(t)
        if self._dwell is None or not self.params.submenu_guides:
            return opened
        self.move(*self.pos, t)
        return True

    @staticmethod
    def _may_open(item, dx, dy):
        """The pointer is where a rest opens the highlighted radial ``item``'s submenu, like Maya: its box lies on the
        straight line from the menu centre to the pointer (on the box, or beyond it seen from the centre - also
        beside the list under the ring - but not short of it or off its far corner)."""
        return _inside(item.rect, dx, dy) or _segment_meets(item.rect, dx, dy)

    def _keep_rest(self, item, x, y, t):
        """Note the pointer resting on radial submenu ``item`` (None: on nothing that opens); a move farther than
        ``rest_slop`` from where the rest began starts it again."""
        if item is None:
            self._rest = None
        elif (self._rest is None or self._rest[0] is not item
              or math.hypot(x - self._rest[2][0], y - self._rest[2][1]) > self.params.rest_slop):
            self._rest = (item, t, (x, y))

    def _open_rested(self, t):
        """Open the submenu of the radial item the pointer has rested on for ``open_dwell`` s while the menu is drawn
        (a rest that began before the menu was drawn counts from then), centred where the pointer is, like Maya."""
        if self._rest is None or self.result is not None:
            return False
        item, since, _at = self._rest
        if self.hover[0] is not item or item not in self.layout.items or not self.visible(t):
            return False
        start = max(since, self._shown_at if self._shown_at is not None else t)
        if t - start < self.params.open_dwell:
            return False
        self._push(item, self.pos)
        return True

    def _hit_stack(self, x, y):
        """(level, item, on option box) under (x, y): the top menu first (directions included); when it has
        nothing there and is a cascade, the boxes / rows of the menus it hangs from (#5: dragging on
        down the list after passing a submenu row closed the whole menu)."""
        top = len(self.stack) - 1
        lay, (cx, cy) = self.stack[top]
        item, opt = lay.hit(x - cx, y - cy)
        if item is None and self.hover[0] in lay.radial.values() and lay.below_list(x - cx, y - cy):
            item, opt = self.hover[0], False   # Maya: a radial item stays highlighted beside / below the list
        level = top
        while item is None and self.openers[level] is not None:
            level -= 1
            lay, (cx, cy) = self.stack[level]
            item, opt = lay.hit(x - cx, y - cy, rects_only=True)
            if item is not None:
                return level, item, opt
        return top, item, opt

    def _inside_bounds(self, layout, at):
        """Shift a list submenu up / left so all its rows are inside ``bounds``."""
        x0, y0, x1, y1 = self.bounds
        lx0 = min(it.rect[0] for it in layout.items)
        ly0 = min(it.rect[1] for it in layout.items)
        lx1 = max(it.rect[2] for it in layout.items)
        ly1 = max(it.rect[3] for it in layout.items)
        x, y = at
        x = max(x0 - lx0, min(x, x1 - lx1))
        y = min(y1 - ly1, max(y, y0 - ly0))
        if self.edges:
            x, y = self._around_edges(layout, (x, y))
        return (x, y)

    def _around_edges(self, layout, at):
        """A list submenu's rows off the area border bands (``_settle_list``): a row that would overlap a
        horizontal band goes below it; when that runs the rows past the window bottom they move up (as far as the
        top allows) before wrapping into a second column."""
        x0, y0, x1, y1 = self.bounds
        x, y = at
        rows = layout.items
        _settle_list(rows, max(it.rect[3] for it in rows), y0 - y, x0 - x, x1 - x, self.params.list_gap / 2,
                     _rel_edges(self.edges, x, y), lift=y1 - y)
        return at

    # -- input ----------------------------------------------------------------
    def move(self, x, y, t):
        self.pos = (x, y)
        self.time = t
        self.trail.append((x, y))
        ox, oy = self.press
        self.max_dist = max(self.max_dist, math.hypot(x - ox, y - oy))
        quick = self.params.quick_gestures and self.mode == "PRESS" and not self.visible(t)
        heading = None
        if self.params.quick_gestures:
            self._last_move = t     # after visible(t): a pause before this move has shown the menu
            heading = self._gesture.update(x, y, t)
        if quick:
            # a hidden mark: only the radial items, by the stroke's heading (outside the dead zone) - list rows and
            # option boxes the stroke passes over are not picked
            lay, (cx, cy) = self.stack[-1]
            if math.hypot(x - cx, y - cy) < self.params.dead:
                heading = None
            level, item, opt = len(self.stack) - 1, lay.radial.get(heading) if heading else None, False
        else:
            level, item, opt = self._hit_stack(x, y)
        while (item is None or not quick) and self._leave_sub(x, y, items=not quick):
            level, item, opt = self._hit_stack(x, y)
        if self.params.submenu_guides and self._dwell_back(x, y, t):
            level, item, opt = self._hit_stack(x, y)
        if level < len(self.stack) - 1:
            if item is self.openers[level + 1]:
                # back on the row whose cascade is open: keep it (close deeper ones)
                self._pop_to(level + 1)
                self.hover = (item, opt)
                return
            self._pop_to(level)   # another row of a menu under the cascade: the cascade closes
        dx, dy = self._rel(x, y)
        self.hover = (item, opt)
        if self._closed is not None and item is not self._closed:
            self._closed = None   # the pointer left the item whose submenu Esc closed: it may open again
        if item is None or item.sub is None or not item.enabled or item is self._closed:
            self._rest = None
            return
        if item.kind == "radial":
            if quick:
                # a hidden mark enters a radial submenu once it reaches the ring in that item's sector (also the
                # second stroke of a zig-zag mark)
                if math.hypot(dx, dy) >= self.params.radius and heading == item.key:
                    self._push(item, (x, y))
                return
            # Maya: a rest on it opens it (tick), a stroke that keeps moving goes over it
            self._keep_rest(item if self._may_open(item, dx, dy) else None, x, y, t)
            return
        self._rest = None
        if item.kind == "list" and _inside(item.rect, dx, dy):
            # a list row's submenu opens on hover, beside the row (a Qt menu cascade)
            self._push(item, (self.center[0] + item.rect[2], self.center[1] + item.rect[3]), cascade=True)

    def release(self, x, y, t, held=None):
        """The button that opened the menu was released. ``held``: how long the button was down for the quick-click
        test, when the caller knows it better than ``t - t0`` (the press and the release handled together after a
        slow frame: ``t0`` is dated back into that frame, the click was still quick)."""
        if self.mode != "PRESS":
            return self.result
        self.move(x, y, t)
        held = t - self.t0 if held is None else held
        item, opt = self.hover
        if len(self.stack) == 1 and t - self.t0 < self.params.mark_time and (
                (item is not None and item.kind == "list")
                or (item is None and self.layout.below_list(*self._rel(x, y)))):
            item, opt = self.layout.nearest_radial(*self._rel(x, y)), False   # a mark: its direction, not the row
        if len(self.stack) == 1 and self.max_dist < self.params.dead and held < self.params.click_time \
                and item is None:
            # quick click: the menu stays up
            self._click_mode(t)
            return None
        if len(self.stack) == 1 and t - self.t0 < self.params.quick_none_time and not self.params.quick_gestures:
            return self._cancel()     # released right after the press: nothing runs, like Maya
        if item is not None and item.sub is None:
            return self._finish(item, opt)
        if (item is not None and item.sub is not None and item.kind == "radial" and len(self.stack) == 1
                and not self.params.quick_gestures and not self.visible(t)):
            # a mark goes into a radial submenu where it crosses the item (its box centre) and the rest of the stroke
            # picks in there, like Maya's compound marks: a flick on past the item runs the submenu's item that way
            # (Ctrl+RMB flick left = To Vertices > To Vertices). A short flick that ends before the item's box centre
            # goes on in the item's own direction, however short it is (outside the dead zone): a quick flick left
            # is To Vertices > To Vertices too
            r = item.rect
            dx, dy = self._rel(x, y)
            ux, uy = _UNIT[item.key]
            cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
            if dx * ux + dy * uy < cx * ux + cy * uy:
                way = item.key
            else:
                way = direction(dx - cx, dy - cy, self.params.dead) or item.key
            self._push(item, self.center)
            leaf = self.layout.radial.get(way)
            if leaf is not None and leaf.sub is None:
                return self._finish(leaf, False)
            return self._cancel()
        if item is not None and item.sub is not None and item.kind != "radial":
            self._click_mode(t)   # released on a list row's submenu: keep it open to pick from
            return None
        # nothing there, or a radial submenu that didn't open (no rest on it): nothing runs, the menu closes (Maya)
        return self._cancel()

    def _click_mode(self, t):
        self.mode = "CLICK"       # drawn from now on
        self._shown_at = t if self._shown_at is None else min(self._shown_at, t)

    def click(self, x, y, t):
        """A button press while in click mode."""
        self.move(x, y, t)
        item, opt = self.hover
        if item is None:
            return self._cancel()
        if item.sub is not None:
            if len(self.stack) and self.layout.sub is not item.sub:
                self._push(item, (x, y), cascade=item.kind == "list")
            return None
        return self._finish(item, opt)

    def cancel(self):
        return self._cancel()

    def escape(self):
        """Esc: an open submenu closes and the menu it opened from is there again, with what it has under the
        pointer hovered (the closed submenu doesn't reopen until the pointer leaves its item); at the top menu
        the whole menu closes. ``None`` while the menu stays open."""
        if len(self.stack) < 2:
            return self._cancel()
        self._closed = self.via[-1]
        self._pop_to(len(self.stack) - 2)
        self.move(*self.pos, self.time)
        return None

    def _finish(self, item, opt):
        if not item.enabled:
            return self._cancel()
        self.result = ("RUN", item, opt)
        return self.result

    def _cancel(self):
        self.result = ("CANCEL", None, False)
        return self.result
