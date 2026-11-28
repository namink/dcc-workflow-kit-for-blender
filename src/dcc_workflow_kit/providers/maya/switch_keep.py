# SPDX-License-Identifier: GPL-3.0-or-later
"""The Maya layout's panels across a switch to Blender and back, and across saving and opening the file (#458).

A switch to Blender takes the Maya layout workspace out of the file (#282, #307) and a switch back appends a fresh one,
so the panels the user made (the viewport split into more panels, the Four View) and each panel's settings
(background, grid and the other overlays, shading, the view) would start over. Like a Maya scene, which keeps its
panel layout and each panel's display settings, the switch to Blender keeps them as JSON on the file's Blender
workspaces (``KEY``, one record per Maya template workspace; saved with the file, no area pointers); the switch back
lays the main viewport out again in the fresh workspace (Blender's ``screen.area_split``, one split per tick: a new
area gets its size on the next tick) and gives each panel its settings back, then opens the Four View again when it
was on. A Maya workspace that stayed in the file (a Maya Workflow Kit file) keeps its panels: only its Four View,
folded by the switch, comes back. GUI only (``screen.area_split`` needs a window).
"""

import json

import bpy

from . import live_refs
from .switch_layout import _forget_timer, _timers, is_maya_workspace, template_of

KEY = "allset_maya_panels"
TICK = 0.05
TRIES = 80
_TOL = 0.01            # of the screen size: the border between two areas (a few px)


# --- record --------------------------------------------------------------------------------------------------------

def _bounds(areas):
    x0 = min(a.x for a in areas)
    y0 = min(a.y for a in areas)
    x1 = max(a.x + a.width for a in areas)
    y1 = max(a.y + a.height for a in areas)
    return x0, y0, max(x1 - x0, 1), max(y1 - y0, 1)


def _norm(r, bounds):
    """Window px rect (x0, y0, x1, y1) as shares of the screen ``bounds`` (x, y, w, h)."""
    bx, by, bw, bh = bounds
    return [round((r[0] - bx) / bw, 4), round((r[1] - by) / bh, 4), round((r[2] - bx) / bw, 4),
            round((r[3] - by) / bh, 4)]


def _data(area):
    from .ui import four_view
    data = four_view.capture_area(area)
    data.pop("isolate", None)          # Isolate Select ends with the switch (the local view goes with its area)
    return data


def capture(window):
    """The record of the Maya workspace ``window`` shows: every area but the Tool Box column (rect as shares of the
    screen, editor type and 3D View settings), the Four View as the one panel it folds into. None when the window
    shows no Maya template workspace (or no UI)."""
    if bpy.app.background or window is None:
        return None
    ws, screen = window.workspace, window.screen
    if not is_maya_workspace(ws) or screen is None:
        return None
    template = template_of(ws)
    if template is None:
        return None
    from .ui import four_view
    areas = four_view._areas(screen)
    if not areas:
        return None
    bounds = _bounds(screen.areas)
    block = four_view.block(screen)
    in_block = {a.as_pointer() for a in block.values()}
    out = []
    for a in areas:
        if a.as_pointer() not in in_block:
            out.append({"rect": _norm(four_view.rect(a), bounds), "data": _data(a)})
    if block:
        out.append({"rect": _norm(four_view.union(four_view.rect(a) for a in block.values()), bounds),
                    "data": _data(block["persp"]), "four": True})
    return {"template": template, "areas": out, "four": bool(block)}


def add_four_view(record, window):
    """The Four View's own record (its panels' settings and proportions, ``four_view.PROP``) once it is folded."""
    if record is None or window is None or window.screen is None:
        return
    from .ui import four_view
    value = window.screen.get(four_view.PROP)
    if isinstance(value, str):
        record["four_view"] = value


def _records(ws):
    try:
        value = json.loads(ws.get(KEY) or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def store(records):
    """Keep ``records`` on every Blender workspace of the file (whichever the user goes on to show, the switch back
    finds them there, also after the file is saved and opened again)."""
    records = [r for r in records if r]
    if not records:
        return
    for ws in bpy.data.workspaces:
        if ws.library is not None or is_maya_workspace(ws):
            continue
        have = _records(ws)
        for r in records:
            have[r["template"]] = r
        ws[KEY] = json.dumps(have)


def find(template, first=None):
    """The record kept for Maya template workspace ``template``: on ``first`` (the workspace the window showed), else
    on any Blender workspace of the file."""
    for ws in ([first] if first is not None else []) + list(bpy.data.workspaces):
        if ws is None or is_maya_workspace(ws):
            continue
        rec = _records(ws).get(template)
        if isinstance(rec, dict) and isinstance(rec.get("areas"), list):
            return rec
    return None


# --- the layout again ----------------------------------------------------------------------------------------------

def plan(items):
    """A split tree for ``items`` ([(rect shares, record)]): ("leaf", record) or ("split", direction, factor, low,
    high) — low is the left / bottom part. Areas Blender can't make by splits (joined into an L) leave the largest
    panel alone."""
    if len(items) == 1:
        return ("leaf", items[0][1])
    for axis, direction in ((0, 'VERTICAL'), (1, 'HORIZONTAL')):
        lo = min(r[axis] for r, _d in items)
        hi = max(r[axis + 2] for r, _d in items)
        for edge in sorted({r[axis + 2] for r, _d in items}):
            low = [it for it in items if it[0][axis + 2] <= edge + _TOL]
            high = [it for it in items if it[0][axis] >= edge - _TOL]
            if not low or not high or len(low) + len(high) != len(items):
                continue
            cut = (max(r[axis + 2] for r, _d in low) + min(r[axis] for r, _d in high)) / 2
            factor = min(0.95, max(0.05, (cut - lo) / max(hi - lo, 1e-6)))
            if abs(factor - 0.5) < 1e-4:
                factor = 0.4999            # Blender's side rule (the smaller part is the new area) needs an off-middle
            return ("split", direction, factor, plan(low), plan(high))
    largest = max(items, key=lambda it: (it[0][2] - it[0][0]) * (it[0][3] - it[0][1]))
    return ("leaf", largest[1])


def main_panel(screen):
    """The largest 3D View panel (the Tool Box column is none)."""
    from .ui import four_view
    panes = four_view.panes(screen)
    return max(panes, key=lambda a: a.width * a.height) if panes else None


def _tree(record, screen, main):
    """The split tree of the recorded areas that lie in ``main`` (the fresh workspace's viewport)."""
    from .ui import four_view
    m = _norm(four_view.rect(main), _bounds(screen.areas))
    items = []
    for entry in record.get("areas", ()):
        r = entry.get("rect")
        if not (isinstance(r, list) and len(r) == 4):
            continue
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        if m[0] <= cx <= m[2] and m[1] <= cy <= m[3]:
            items.append((r, entry))
    return plan(items) if items else None


def _apply_leaf(context, area, entry):
    """``area`` shows the recorded panel: its editor type and its 3D View settings. False while a new 3D View has
    no view data yet (next tick)."""
    from .ui import four_view
    data = entry.get("data") or {}
    want = data.get("ui_type")
    if want and area.ui_type != want:
        try:
            area.ui_type = want
        except (TypeError, ValueError):
            pass
    if area.type == 'VIEW_3D' and "shading" in data:
        space = area.spaces.active
        if space.region_3d is None:
            return False
        four_view.apply(space, data, context.scene)
    area.tag_redraw()
    return True


def _step(context, window, queue, done):
    """One tick of the rebuild: each queued area is split (once it has a size) or gets its panel's settings."""
    from .ui import four_view
    screen = window.screen
    alive = {a.as_pointer(): a for a in screen.areas}
    out = []
    for ptr, node in queue:
        area = alive.get(ptr)
        if area is None:
            continue
        if node[0] == "leaf":
            if not _apply_leaf(context, area, node[1]):
                out.append((ptr, node))
            elif node[1].get("four"):
                done["four"] = ptr
            continue
        _kind, direction, factor, low, high = node
        if area.width <= 1 or area.height <= 1:
            out.append((ptr, node))
            continue
        new = four_view._split(context, window, area, direction, factor)
        if new is None:                    # too small to split: the larger part's panel only
            out.append((ptr, low if factor >= 0.5 else high))
            continue
        small_low = factor < 0.5           # the new area is the smaller part
        out.append((new.as_pointer() if small_low else ptr, low))
        out.append((ptr if small_low else new.as_pointer(), high))
    return out


def _reopen_four(context, window, ptr, record):
    from .ui import four_view
    screen = window.screen
    if four_view.is_four(screen):
        return
    area = next((a for a in screen.areas if a.as_pointer() == ptr), None) if ptr else None
    if area is None:
        area = four_view.single(screen) or main_panel(screen)
    if area is None:
        return
    value = record.get("four_view")
    if isinstance(value, str):
        st = four_view.state(screen)
        try:
            kept = json.loads(value)
        except (TypeError, ValueError):
            kept = {}
        if isinstance(kept, dict):
            st.update({k: v for k, v in kept.items() if k in ("panes", "split", "single")})
            st["on"] = False
            screen[four_view.PROP] = json.dumps(st)
    four_view.enter(context, area, window)


def restore(window, ws, record, fresh):
    """Lay ``ws`` (shown in ``window`` from the next event loop) out as ``record`` says: ``fresh`` (a workspace just
    appended from the template) gets its viewport split and its panels' settings again; a workspace that stayed in
    the file only its Four View. Runs from a timer once the window shows ``ws``."""
    if record is None or window is None or ws is None or bpy.app.background or not (fresh or record.get("four")):
        return
    win_ptr, name = window.as_pointer(), ws.name
    st = {"queue": None, "left": TRIES, "done": {}}

    def tick():
        st["left"] -= 1
        win = live_refs.window(win_ptr)
        target = bpy.data.workspaces.get(name)
        if win is None or target is None or st["left"] < 0:
            _forget_timer(tick)
            return None
        screen = win.screen
        if win.workspace != target or screen is None or not screen.areas:
            return TICK
        try:
            with bpy.context.temp_override(window=win, screen=screen):
                if st["queue"] is None:
                    main = main_panel(screen)
                    if main is None or main.width <= 1 or main.height <= 1:
                        return TICK
                    tree = _tree(record, screen, main) if fresh else None
                    st["queue"] = [(main.as_pointer(), tree)] if tree is not None else []
                    return TICK
                if st["queue"]:
                    st["queue"] = _step(bpy.context, win, st["queue"], st["done"])
                    return TICK
                if record.get("four"):
                    _reopen_four(bpy.context, win, st["done"].get("four"), record)
        except (ReferenceError, RuntimeError) as ex:
            print("Maya Workflow Kit: Maya panels not laid out again:", ex)
        _forget_timer(tick)
        return None
    _timers.append(tick)
    bpy.app.timers.register(tick, first_interval=TICK)
