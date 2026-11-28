# SPDX-License-Identifier: GPL-3.0-or-later
"""Hotbox logic without Blender: the menu rows, centre box, side boxes, zones and zone lines around the cursor
(``HotboxLayout``), the hotbox key's tap / hold timing (``is_tap``, ``HoldKey``, ``restart_too_soon``) and the
press-drag that opens a menu (``menu_drag``). Driven by ``modal.py`` (``allset.hotbox``) through ``engine``."""

from ..names import PRODUCT
from .menu_layout import Params, _inside


# --- hotbox ---------------------------------------------------------------------------

class HotboxLayout:
    """Maya-style hotbox: menu rows above the cursor
    (``rows``, top first), the cursor row (``side`` = left / right boxes beside the centre box), rows under it
    (``below``, top first), zone lines on the diagonals. Sizes at scale 1: row pitch
    35 = box 26 + gap 9; the centre box is the title with padding."""

    ROW_H, ROW_GAP, SIDE_GAP = 26.0, 9.0, 88.0
    LINE_GAP, LINE_LEN = 20.0, 28.0     # zone lines: start past the rows, length per axis

    def __init__(self, rows, center, measure, params=None, style="ALL", scale=1.0, bounds=None,
                 below=(), side=None, title=PRODUCT):
        """``bounds`` = (x0, y0, x1, y1): where the hotbox may draw (the window's screen areas,
        in region pixels); rows are wrapped / moved to stay inside it."""
        self.params = p = (params or Params()).scaled(scale) if scale != 1.0 else (params or Params())
        self.center = center
        self.style = style
        self.bounds = bounds
        self.title = title
        h, gap = self.ROW_H * scale, self.ROW_GAP * scale
        self.row_h = h
        cx, cy = center
        cw = max(measure(title) + 4 * p.pad, 2 * h)
        self.center_rect = (cx - cw / 2, cy - h / 2, cx + cw / 2, cy + h / 2)
        self.labels = []   # (rect, key, label)
        self.bands = []    # row backgrounds (Maya draws each row as one strip)
        self.zone_lines = []
        if style != "ALL":
            return
        width = bounds[2] - bounds[0] if bounds is not None else None
        above = self._wrap(rows, measure, p.pad, width) if width else [list(r) for r in rows]
        under = self._wrap(below, measure, p.pad, width) if width else [list(r) for r in below]
        pitch = h + gap
        blocks = []
        y = cy + h / 2 + gap + (len(above) - 1) * pitch      # bottom of the top-most row
        for row in above:
            blocks.append(("above", self._row(row, measure, p.pad, cx, y, h, bounds)))
            y -= pitch
        y = cy - h / 2 - gap - h
        for row in under:
            blocks.append(("below", self._row(row, measure, p.pad, cx, y, h, bounds)))
            y -= pitch
        if side:
            left, right = side
            if left:
                w = measure(left[1]) + 2 * p.pad
                x1 = self.center_rect[0] - self.SIDE_GAP * scale
                blocks.append(("side", [((x1 - w, cy - h / 2, x1, cy + h / 2), left[0], left[1])]))
            if right:
                w = measure(right[1]) + 2 * p.pad
                x0 = self.center_rect[2] + self.SIDE_GAP * scale
                blocks.append(("side", [((x0, cy - h / 2, x0 + w, cy + h / 2), right[0], right[1])]))
        if bounds is not None:
            blocks = self._fit_blocks(blocks, bounds, gap)
        for _kind, row in blocks:
            if row:
                self.labels.extend(row)
                self.bands.append((min(r[0] for r, _k, _l in row), min(r[1] for r, _k, _l in row),
                                   max(r[2] for r, _k, _l in row), max(r[3] for r, _k, _l in row)))
        self._zone_lines(scale)

    @staticmethod
    def _row(row, measure, pad, cx, y, h, bounds):
        widths = [measure(label) + 2 * pad for _key, label in row]
        total = sum(widths)
        x = cx - total / 2
        if bounds is not None:
            # centred on the cursor like Maya, slid sideways to stay visible
            x = max(bounds[0], min(x, bounds[2] - total))
        out = []
        for (key, label), w in zip(row, widths):
            out.append(((x, y, x + w, y + h), key, label))
            x += w
        return out

    def _fit_blocks(self, blocks, bounds, gap):
        """Rows over the top edge go under the lower rows; rows under the bottom edge go over the upper
        rows (order kept); what still doesn't fit is pushed inside."""
        def span(kind):
            rs = [r for k, row in blocks if k == kind for r, _k, _l in row]
            return (min(r[1] for r in rs), max(r[3] for r in rs)) if rs else None

        def shift(kind, dy):
            return [(k, [((r[0], r[1] + dy, r[2], r[3] + dy), kk, ll) for r, kk, ll in row]) if k == kind else (k, row)
                    for k, row in blocks]
        up, down = span("above"), span("below")
        floor = min(self.center_rect[1], down[0] if down else self.center_rect[1])
        ceil = max(self.center_rect[3], up[1] if up else self.center_rect[3])
        if up and up[1] > bounds[3]:
            dy = floor - gap - up[1]                       # under everything
            if up[0] + dy < bounds[1]:
                dy = bounds[3] - up[1]
            blocks = shift("above", dy)
        elif down and down[0] < bounds[1]:
            dy = ceil + gap - down[0]                      # over everything
            if down[1] + dy > bounds[3]:
                dy = bounds[1] - down[0]
            blocks = shift("below", dy)
        return blocks

    def _zone_lines(self, scale):
        """Maya's four short diagonal lines between the zones, just outside the rows."""
        cx, cy = self.center
        top = max([r[3] for r in self.bands] + [self.center_rect[3]]) - cy
        bottom = cy - min([r[1] for r in self.bands] + [self.center_rect[1]])
        g, n = self.LINE_GAP * scale, self.LINE_LEN * scale
        for sy, ext in ((1, top), (-1, bottom)):
            t0 = ext + g
            for sx in (-1, 1):
                self.zone_lines.append(((cx + sx * t0, cy + sy * t0), (cx + sx * (t0 + n), cy + sy * (t0 + n))))

    @staticmethod
    def _wrap(rows, measure, pad, width):
        """Split rows wider than ``width`` into several (order kept)."""
        out = []
        for row in rows:
            line, used = [], 0.0
            for key, label in row:
                w = measure(label) + 2 * pad
                if line and used + w > width:
                    out.append(line)
                    line, used = [], 0.0
                used += w
                line.append((key, label))
            if line:
                out.append(line)
        return out

    def label_at(self, x, y):
        for rect, key, label in self.labels:
            if _inside(rect, x, y):
                return key
        return None

    def zone(self, x, y):
        """Zone whose marking menu a click at (x, y) opens."""
        if _inside(self.center_rect, x, y):
            return "C"
        if self.style == "CENTER":
            return None
        dx, dy = x - self.center[0], y - self.center[1]
        if abs(dy) >= abs(dx):
            return "N" if dy > 0 else "S"
        return "E" if dx > 0 else "W"


TAP_TIME = 0.4  # Maya hotbox tap time


def is_tap(press_t, release_t, clicked):
    """Space released quickly without picking anything = pane toggle (Maya's Space tap)."""
    return not clicked and release_t - press_t < TAP_TIME


# #174: a held Space must keep the hotbox up whatever the input path sends while the key is down. Some
# send auto-repeat as RELEASE + PRESS pairs (X11 without detectable repeat, remote / remapping input; with
# simulated pairs the hold ended at each RELEASE and a fast pair toggled Four View), and
# Windows' key state can read "up" for a moment. Kit design: a RELEASE ends the hold only when no PRESS
# follows within RELEASE_GRACE; the key-state fallback ends it only after "up" readings span UP_TIME with no key event;
# a new hotbox doesn't start within RELEASE_GRACE of the last one ending.
RELEASE_GRACE = 0.12
UP_TIME = 0.15
MENU_DRAG = 4.0     # px (x UI scale): a press on a hotbox menu name that moves this far opens the menu to drag into


class HoldKey:
    """The hold of the hotbox key from its first PRESS: ``press(t)`` / ``release(t)`` for its key events,
    ``tick(t, down)`` with the OS key state (None = unknown) -> True when the hold is over. ``end`` = when it ended
    (the final release), for ``is_tap``."""

    def __init__(self, t0):
        self.t0 = t0
        self.released = None      # time of a RELEASE not yet followed by a PRESS
        self.last_event = t0
        self.up_since = None
        self.end = None

    def press(self, t):
        self.last_event = t
        if self.released is not None and t - self.released <= RELEASE_GRACE:
            self.released = None  # a repeat delivered as release + press: still held

    def release(self, t):
        self.last_event = t
        self.released = t

    def tick(self, t, down):
        if self.released is not None and t - self.released > RELEASE_GRACE:
            self.end = self.released
            return True
        if down is False:
            if self.up_since is None:
                self.up_since = t
            if t - self.up_since >= UP_TIME and t - self.last_event >= UP_TIME:
                self.end = self.up_since    # the release was eaten elsewhere
                return True
        else:
            self.up_since = None
        return False


def restart_too_soon(last_end, t):
    """A hotbox key PRESS right after the last hold ended belongs to that hold (a release + press repeat pair)."""
    return last_end is not None and 0.0 <= t - last_end <= RELEASE_GRACE


def menu_drag(press_xy, xy, scale=1.0):
    """The pointer moved far enough from a press on a menu name to open that menu for a press-drag-release."""
    return (xy[0] - press_xy[0]) ** 2 + (xy[1] - press_xy[1]) ** 2 >= (MENU_DRAG * scale) ** 2
