# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Four View = four real 3D View panels (Issue #148).

Blender's Quad View splits one 3D View region in four: one header, one shading / overlay set for all four panes. A
Maya model panel has its own camera, shading, Show settings and panel menu bar, so the kit's four view is four 3D
View *areas* (``screen.area_split`` three times), each with its own ``SpaceView3D``:

    top   | persp
    ------+------
    front | side

Blender's split rules (``hypershade_layout`` docstring): HORIZONTAL with
factor > 0.5 puts the new area on top, VERTICAL with factor < 0.5 on the left — so the panels' places are known
without reading rects (areas get their rects one tick after a split).

Space tap / Panels > Layouts > Single Perspective View leave the four view by joining the other three areas into the
panel under the mouse (or the persp panel) with ``screen.area_join`` (GUI only).
A panel of the four view is never split for anything else: a dock (Tool Settings, the Channel Box stack, the Outliner,
a docked editor, the shelf) goes beside the whole four view and a kit window's place is carved out of the whole view,
both with the four view folded into one panel for a moment (``in_one_panel``; a Space tap waits meanwhile).
A panel of the four view may be any editor (Graph Editor, render view, Outliner ...), like a Maya panel: the four view
is the 2 x 2 block of areas inside the rectangle recorded on the screen (``rect``, window px), whatever their editor
types, and each role keeps its editor type across four <-> one. Outside that block a Space tap maximizes the pane.
Each panel's settings (shading, overlays, object types shown, lens / clip, camera) are kept per *role* (top / persp /
front / side) as JSON in the Screen ID property ``allset_four_view`` — saved with the file, never area pointers
(#36) — and put back when the four view comes back, like Maya's panels keep theirs. Blender Quad View is not used.
"""

import json
import math

import bpy
from mathutils import Euler, Quaternion

PROP = "allset_four_view"
ROLES = ("top", "persp", "front", "side")
# (column, row from the top) of each role in Maya's Four View
SLOTS = {"top": (0, 0), "persp": (1, 0), "front": (0, 1), "side": (1, 1)}
# Blender view rotations of Maya's ortho cameras (Maya side looks from +X = Blender Right view)
AXIS = {"top": Quaternion(), "front": Euler((math.pi / 2, 0.0, 0.0)).to_quaternion(),
        "side": Euler((math.pi / 2, 0.0, math.pi / 2)).to_quaternion()}
# Shading of a new four view, like Maya: every panel Smooth Shade All (= Blender Solid)
DEFAULT_SHADING = {"top": 'SOLID', "persp": 'SOLID', "front": 'SOLID', "side": 'SOLID'}
SPLITS = (0.5001, 0.4999)            # HORIZONTAL (new on top), VERTICAL (new on the left)
# Blender's area_split makes the smaller part the new area: HORIZONTAL above 0.5 = new on top, VERTICAL below 0.5 =
# new on the left. The four view's own proportions (``state["split"]``: bottom row share, top row's left share,
# bottom row's left share) are kept across four <-> one, like Maya's panel layout keeps its pane sizes.

_SPACE_PROPS = ("lens", "clip_start", "clip_end", "use_local_camera", "lock_camera")
_SKIP = {"rna_type"}


# --- the record on the screen --------------------------------------------------------------------------------------

def state(screen):
    try:
        return json.loads(screen.get(PROP) or "{}")
    except (TypeError, ValueError):
        return {}


def _save_state(screen, st):
    screen[PROP] = json.dumps(st)


def is_four(screen):
    return screen is not None and bool(block(screen))


def panes(screen):
    """The 3D View panels of ``screen`` (the Tool Box column is not a panel)."""
    from .toolbox import is_toolbox
    return [a for a in screen.areas if a.type == 'VIEW_3D' and not is_toolbox(a.spaces.active)]


def _areas(screen):
    """Every area that can be a panel: any editor but the Tool Box column."""
    from .toolbox import is_toolbox
    return [a for a in screen.areas if not (a.type == 'VIEW_3D' and is_toolbox(a.spaces.active))]


# --- the block by places (pure: anything with x / y / width / height) ---------------------------------------------

GAP = 6                              # px between neighbouring areas at UI scale 1 (border + pixel size), with room


def border_gap():
    """Px allowed between neighbouring areas: the area border grows with the UI scale (and the screen's DPI), e.g.
    3 px at scale 1 but 9 px at scale 2 — with a fixed tolerance a high-DPI four view was not found and every Space
    tap split it again (#302)."""
    try:
        scale = bpy.context.preferences.system.ui_scale
    except AttributeError:
        scale = 1.0
    return max(GAP, math.ceil(GAP * scale))


def rect(a):
    """(x0, y0, x1, y1) of an area, window px, y up."""
    return (a.x, a.y, a.x + a.width, a.y + a.height)


def union(rects):
    rects = list(rects)
    return (min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects))


def overlap(r, q):
    """Area of the intersection of two rects."""
    w = min(r[2], q[2]) - max(r[0], q[0])
    h = min(r[3], q[3]) - max(r[1], q[1])
    return w * h if w > 0 and h > 0 else 0


def _size(r):
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def grids(areas, gap=None):
    """Every 2 x 2 group of ``areas`` that fills a rectangle: [{role: area}] (top / persp over front / side; the
    middle edges of the two rows may differ). ``gap``: px allowed between neighbours (default: by the UI scale)."""
    tol = border_gap() if gap is None else gap

    def near(a, b):
        return abs(a - b) <= tol
    out = []
    for tl in areas:
        t = rect(tl)
        for tr in areas:
            r = rect(tr)
            if tr is tl or not (near(r[0], t[2]) and near(r[3], t[3])):
                continue
            for bl in areas:
                b = rect(bl)
                if bl is tl or bl is tr or not (near(b[0], t[0]) and near(b[3], t[1])):
                    continue
                for br in areas:
                    q = rect(br)
                    if br is tl or br is tr or br is bl:
                        continue
                    if near(q[0], b[2]) and near(q[2], r[2]) and near(q[1], b[1]) and near(q[3], r[1]):
                        out.append({"top": tl, "persp": tr, "front": bl, "side": br})
    return out


def best(candidates, recorded):
    """The candidate (a {role: area} grid, or one area) covering most of the ``recorded`` rect; None when none covers
    at least half of it (and, for one area, when less than half of the area lies inside it)."""
    if not recorded:
        return None
    want = _size(recorded)
    found, most = None, 0
    for c in candidates:
        r = union(rect(a) for a in c.values()) if isinstance(c, dict) else rect(c)
        o = overlap(r, recorded)
        if o * 2 < want or (not isinstance(c, dict) and o * 2 < _size(r)):
            continue
        if o > most:
            found, most = c, o
    return found


def block(screen):
    """{role: area} of the four view on ``screen`` (any editor types), {} when it shows no four view."""
    if screen is None:
        return {}
    st = state(screen)
    if not st.get("on"):
        return {}
    if st.get("rect"):
        return best(grids(_areas(screen)), st["rect"]) or {}
    return roles(screen, panes(screen))          # a record without a rect: four 3D View panels


def single(screen):
    """The one panel the four view was folded into (by the recorded rect), else None."""
    st = state(screen) if screen is not None else {}
    if st.get("on") or not st.get("rect"):
        return None
    return best(_areas(screen), st["rect"])


def roles(screen, areas=None):
    """{role: area} of a four view: the block on ``screen``, or ``areas`` by their places (GUI: rects)."""
    if areas is None:
        return block(screen)
    if len(areas) != 4:
        return {}
    cx = sum(a.x + a.width / 2 for a in areas) / 4
    cy = sum(a.y + a.height / 2 for a in areas) / 4
    out = {}
    for a in areas:
        col = 0 if a.x + a.width / 2 < cx else 1
        row = 0 if a.y + a.height / 2 > cy else 1           # Blender y goes up
        role = next(r for r, s in SLOTS.items() if s == (col, row))
        out.setdefault(role, a)
    return out if len(out) == 4 else {}


# --- panel settings -------------------------------------------------------------------------------------------------

def _props(struct):
    out = {}
    for p in struct.bl_rna.properties:
        if p.is_readonly or p.identifier in _SKIP or p.type in ('POINTER', 'COLLECTION'):
            continue
        v = getattr(struct, p.identifier)
        if p.type == 'ENUM' and p.is_enum_flag:
            v = sorted(v)
        elif not isinstance(v, (str, int, float, bool)):
            try:
                v = [float(x) for x in v]
            except TypeError:
                continue
        out[p.identifier] = v
    return out


def _apply_props(struct, values, first=("type",)):
    flags = {p.identifier for p in struct.bl_rna.properties if p.type == 'ENUM' and p.is_enum_flag}
    for key in (*[k for k in first if k in values], *[k for k in values if k not in first]):
        try:
            setattr(struct, key, set(values[key]) if key in flags else values[key])
        except (AttributeError, TypeError, ValueError):
            pass                     # a value this Blender / scene can't take (a studio light that went away ...)


def capture(space):
    """One panel's settings: shading, overlays, object types shown, lens / clip and the camera (the view, and the
    camera object it looks through with its camera zoom / offset)."""
    rv3d = space.region_3d
    view = {}
    if rv3d is not None:
        view = {"perspective": rv3d.view_perspective, "rotation": list(rv3d.view_rotation),
                "location": list(rv3d.view_location), "distance": rv3d.view_distance,
                "side": bool(rv3d.is_orthographic_side_view),
                "camera": space.camera.name if space.camera is not None else "",
                "camera_zoom": rv3d.view_camera_zoom, "camera_offset": list(rv3d.view_camera_offset)}
    shown = {p.identifier: getattr(space, p.identifier) for p in space.bl_rna.properties
             if p.identifier.startswith("show_object_viewport_")}
    return {"shading": _props(space.shading), "overlay": _props(space.overlay),
            "space": {k: getattr(space, k) for k in _SPACE_PROPS}, "shown": shown, "view": view}


def capture_area(area, view_layer=None):
    """One panel's record: its editor type, plus the 3D View settings when it is a 3D View (with the objects its
    Isolate Select shows)."""
    out = {"ui_type": area.ui_type}
    if area.type == 'VIEW_3D':
        out.update(capture(area.spaces.active))
        out["isolate"] = isolated(area.spaces.active, view_layer or bpy.context.view_layer)
    return out


# --- Isolate Select per panel ---------------------------------------------------------------------------------------
# Isolate Select (Ctrl+1) belongs to a Maya panel and stays with it when the layout changes. In Blender it is the 3D
# View's local view, which a split copy of the view doesn't get and which ends with its area, so the four view
# records each panel's isolated objects and makes the local view again in the area that shows that panel.

def isolated(space, view_layer):
    """Names of the objects Isolate Select shows in 3D View ``space``; None when the view isolates nothing."""
    if space is None or space.local_view is None or view_layer is None:
        return None
    out = []
    for ob in view_layer.objects:
        try:
            if ob is not None and ob.local_view_get(space):
                out.append(ob.name)
        except RuntimeError:
            pass
    return out


def _localview(context, window, area):
    region = _window_region(area)
    if region is None:
        return False
    with context.temp_override(window=window, screen=window.screen, area=area, region=region,
                               space_data=area.spaces.active):
        try:
            return bpy.ops.view3d.localview(frame_selected=False) == {'FINISHED'}
        except RuntimeError:
            return False


def set_isolation(context, window, area, names):
    """``area``'s Isolate Select shows exactly the objects ``names`` (None or none left: no Isolate Select). The
    selection, the active object and the camera stay as they are."""
    if window is None or area is None or area.type != 'VIEW_3D':
        return
    space = area.spaces.active
    view_layer = window.view_layer
    obs = [ob for ob in view_layer.objects if ob is not None]
    want = set(names or ())
    if not any(ob.name in want for ob in obs):
        if space.local_view is not None:
            _localview(context, window, area)          # leaves it (the view stays where it is)
        return
    if space.local_view is None:
        editing = any(ob.mode == 'EDIT' for ob in obs)
        selection = [(ob, ob.select_get(view_layer=view_layer)) for ob in obs]
        active = view_layer.objects.active
        if not editing:              # Blender's local view takes the selected objects (in Edit Mode the edited ones)
            for ob in obs:
                try:
                    ob.select_set(ob.name in want, view_layer=view_layer)
                except RuntimeError:
                    pass
        ok = _localview(context, window, area)
        for ob, was in selection:
            try:
                ob.select_set(was, view_layer=view_layer)
            except RuntimeError:
                pass
        if view_layer.objects.active != active:
            view_layer.objects.active = active
        if not ok or space.local_view is None:
            return
    for ob in obs:
        try:
            if ob.local_view_get(space) != (ob.name in want):
                ob.local_view_set(space, ob.name in want)
        except RuntimeError:
            pass
    area.tag_redraw()


def _saved_camera(space, view, scene):
    """The camera a recorded panel looks through: its own camera (by name, set on the panel again), else the scene's
    active camera; None when that camera is gone."""
    if not space.use_local_camera:
        return scene.camera if scene is not None else None
    ob = scene.objects.get(view.get("camera") or "") if scene is not None else None
    if ob is not None:
        space.camera = ob            # only while the view has its own camera: else this sets the scene camera
    return ob


def apply(space, data, scene=None):
    """Put a recorded panel back. A panel that looked through a camera looks through it again, with its camera zoom
    / offset, like a Maya panel keeps its camera; when that camera is gone it shows the perspective view."""
    _apply_props(space.shading, data.get("shading", {}))
    _apply_props(space.overlay, data.get("overlay", {}), first=())
    _apply_props(space, {**data.get("space", {}), **data.get("shown", {})}, first=())
    view, rv3d = data.get("view"), space.region_3d
    if view and rv3d is not None:
        cam = _saved_camera(space, view, scene or bpy.context.scene)
        rv3d.view_perspective = view["perspective"] if view["perspective"] != 'CAMERA' else 'PERSP'
        rv3d.view_rotation = Quaternion(view["rotation"])
        rv3d.view_location = view["location"]
        rv3d.view_distance = view["distance"]
        if view["perspective"] == 'ORTHO':
            rv3d.is_orthographic_side_view = view["side"]
        elif view["perspective"] == 'CAMERA' and cam is not None:
            rv3d.view_perspective = 'CAMERA'
            rv3d.view_camera_zoom = view.get("camera_zoom", rv3d.view_camera_zoom)
            rv3d.view_camera_offset = view.get("camera_offset", tuple(rv3d.view_camera_offset))


def default(space, role, scene):
    """A panel showing Maya's startup camera for ``role`` (persp = Maya's new-scene persp)."""
    from ..operators import units, view
    space.shading.type = DEFAULT_SHADING[role]
    # Blender's area split copies the whole view: a panel split off a view that looks through camera1 would look
    # through camera1 again for View > Cameras > Active Camera. A new panel starts with the scene's camera.
    space.use_local_camera = False
    space.lock_camera = False
    from .. import preferences
    if preferences.get().material_preview_hdri:
        # Blender's Material Preview look (Maya's view has neither): the HDRI as the background, look-dev spheres
        space.shading.use_scene_world = False
        space.shading.studiolight_background_alpha = 1.0
        space.overlay.show_look_dev = True
    rv3d = space.region_3d
    if rv3d is None:
        return
    if role == "persp":
        rv3d.view_perspective = 'PERSP'
        view.home_view(rv3d, units.maya_unit(scene))
        return
    rv3d.view_perspective = 'ORTHO'
    rv3d.view_rotation = AXIS[role]
    rv3d.view_location = (0.0, 0.0, 0.0)
    rv3d.view_distance = view.maya_ortho_distance(space, scene)
    rv3d.is_orthographic_side_view = True


# --- four <-> one ---------------------------------------------------------------------------------------------------

def _window_region(area):
    return next((r for r in area.regions if r.type == 'WINDOW'), None)


def _split(context, window, area, direction, factor):
    screen = window.screen
    before = {a.as_pointer() for a in screen.areas}
    with context.temp_override(window=window, screen=screen, area=area, region=_window_region(area)):
        try:
            if bpy.ops.screen.area_split(direction=direction, factor=factor) != {'FINISHED'}:
                return None
        except RuntimeError:         # poll failed (a maximized pane, an area too small to split)
            return None
    return next((a for a in screen.areas if a.as_pointer() not in before), None)


def _place(context, role, area, saved, window=None):
    """``area`` shows the panel of ``role``: its editor type, and for a 3D View its settings (else Maya's camera)."""
    data = saved.get(role) or {}
    want = data.get("ui_type", 'VIEW_3D')
    if area.ui_type != want:
        try:
            area.ui_type = want
        except (TypeError, ValueError):
            area.ui_type = 'VIEW_3D'
    if area.type == 'VIEW_3D':
        space = area.spaces.active
        if space.region_3d is None:
            if window is not None:
                _place_later(window.as_pointer(), area.as_pointer(), role)   # a new 3D View: region data next tick
        elif "shading" in data:
            apply(space, data, context.scene)
        else:
            default(space, role, context.scene)
        set_isolation(context, window or context.window, area, data.get("isolate"))
    area.tag_redraw()


def _place_later(win_ptr, area_ptr, role):
    from .. import live_refs

    def tick():
        window, area = live_refs.find_area(area_ptr, win_ptr)
        if window is not None and area is not None and area.type == 'VIEW_3D' \
                and area.spaces.active.region_3d is not None:
            _place(bpy.context, role, area, state(window.screen).get("panes", {}), window)
        return None
    bpy.app.timers.register(tick, first_interval=0.0)


def _factor(f, default):
    """A split factor kept off the middle (Blender's side rule needs it) and off the edges."""
    try:
        f = min(0.85, max(0.15, float(f)))
    except (TypeError, ValueError):
        return default
    if abs(f - 0.5) < 1e-4:
        f = default
    return f


def proportions(placed):
    """[bottom row share, top row's left share, bottom row's left share] of a four view {role: area}: where each
    border lies across the panel it splits, in the terms ``screen.area_split`` takes its factor in (``enter``), so a
    four view made again from them has the same borders. Shares of the panels' own sizes would leave out the pixels
    of the borders and moved a border by a pixel on every Space round trip.

    An area's rect lies ``pad`` px inside its edges on every side, the window's edges too (half the gap between two
    neighbours). Blender puts a split ``round(factor * size)`` px from the split area's first edge; the share is
    taken against a size half a pixel short of that, so it rounds back to the same border."""
    t, p, f, s = placed["top"], placed["persp"], placed["front"], placed["side"]

    def share(lo, cut, after, hi):
        """``lo`` .. ``cut``: the first panel (px, end excluded), ``after`` .. ``hi``: the second one."""
        pad = max(0, (after - cut + 1) // 2)
        v0, v1, line = lo - pad, hi - 1 + pad, cut - 1 + pad
        return round((line - v0) / max(v1 - v0 + 0.5, 1.0), 4)
    return [share(f.y, f.y + f.height, t.y, t.y + t.height),
            share(t.x, t.x + t.width, p.x, p.x + p.width),
            share(f.x, f.x + f.width, s.x, s.x + s.width)]


def factors(st):
    """(HORIZONTAL factor, top row VERTICAL factor, bottom row VERTICAL factor) of the four view recorded in ``st``."""
    y, xt, xb = (st.get("split") or [SPLITS[0], SPLITS[1], SPLITS[1]])[:3]
    return _factor(y, SPLITS[0]), _factor(xt, SPLITS[1]), _factor(xb, SPLITS[1])


def enter(context, area, window=None, whole=None):
    """``area`` (one panel, any editor) becomes the four view, in the proportions it had (``factors``). Returns the
    roles placed now ({} when it can't split: always in background mode, where a split-off area stays 0 x 0).
    ``whole``: the panel's rect when its own is not laid out yet (a panel joined in this call keeps its old rect until
    the screen is next laid out; splitting goes by the screen's corners, not by that rect).

    Splits: ``area`` into its two rows, then the row ``area`` keeps into left / right, then the other row (the area
    the first split made already has its size) — all in this call, so the screen never shows a half-made four view;
    a row without a size yet is split from a timer one tick later (``_split_row_later``; pointers only, #36)."""
    window = window or context.window
    screen = window.screen
    if bpy.app.background:
        return {}
    st = state(screen)
    saved = st.get("panes", {})
    single = st.get("single", "persp")
    saved[single] = {**saved.get(single, {}), **capture_area(area, window.view_layer)}
    whole = list(whole or rect(area))
    fy, ft, fb = factors(st)
    other = _split(context, window, area, 'HORIZONTAL', fy)
    if other is None:
        return {}
    other_is_top = fy > 0.5                       # the new area is the smaller row
    f_now, roles_now, f_later, roles_later = ((fb, ("front", "side"), ft, ("top", "persp")) if other_is_top
                                              else (ft, ("top", "persp"), fb, ("front", "side")))
    new = _split(context, window, area, 'VERTICAL', f_now)
    if new is None:
        return {}
    left, right = (new, area) if f_now < 0.5 else (area, new)
    placed = {roles_now[0]: left, roles_now[1]: right, roles_later[1]: other}    # the other row: one panel so far
    st.update(on=True, panes=saved, rect=whole)
    _save_state(screen, st)
    third = _split(context, window, other, 'VERTICAL', f_later) if other.width > 1 and other.height > 1 else None
    if third is not None:
        placed[roles_later[0]], placed[roles_later[1]] = (third, other) if f_later < 0.5 else (other, third)
    for role, a in placed.items():
        _place(context, role, a, saved, window)
    if third is None:
        _split_row_later(window.as_pointer(), other.as_pointer(), f_later, roles_later)
    return placed


def _split_row_later(win_ptr, row_ptr, factor, roles_lr, tries=20):
    from .. import live_refs

    def tick():
        window, row = live_refs.find_area(row_ptr, win_ptr)
        if window is None or row is None:
            return None                                    # the window / panel went away
        if row.width < 2 or row.height < 2:
            nonlocal tries
            tries -= 1
            return 0.05 if tries > 0 else None
        new = _split(bpy.context, window, row, 'VERTICAL', factor)
        if new is not None:
            left, right = (new, row) if factor < 0.5 else (row, new)
            saved = state(window.screen).get("panes", {})
            _place(bpy.context, roles_lr[0], left, saved, window)
            _place(bpy.context, roles_lr[1], right, saved, window)
        return None
    bpy.app.timers.register(tick, first_interval=0.0)


def remember(screen):
    """Keep the four panels' settings on the screen (Maya's panels keep theirs across layouts)."""
    placed = roles(screen)
    if not placed:
        return {}
    st = state(screen)
    saved = st.get("panes", {})
    for role, a in placed.items():
        saved[role] = {**saved.get(role, {}), **capture_area(a)}     # a Graph Editor keeps its old 3D settings
        if a.type != 'VIEW_3D':
            saved[role].pop("isolate", None)
    st["panes"] = saved
    st["rect"] = list(union(rect(a) for a in placed.values()))
    st["split"] = proportions(placed)
    _save_state(screen, st)
    return placed


def leave(context, keep=None, window=None, role=None):
    """Back to one panel: ``keep`` (an area of the four view) or the panel of ``role`` stays. GUI only."""
    window = window or context.window
    screen = window.screen
    placed = remember(screen)
    st = state(screen)
    if not placed:
        st["on"] = False
        _save_state(screen, st)
        return None
    if keep is None or keep.as_pointer() not in {a.as_pointer() for a in placed.values()}:
        keep = placed[role or "persp"]
    keep_role = next(r for r, a in placed.items() if a == keep)
    if bpy.app.background:           # screen.area_join crashes without a UI
        return None
    keep_ptr = keep.as_pointer()
    for a in placed.values():        # the panels that go away leave Isolate Select (kept in their record)
        if a != keep:
            set_isolation(context, window, a, None)
    _join_into(context, window, placed, keep_role)
    kept = next((a for a in screen.areas if a.as_pointer() == keep_ptr), None)
    st.update(on=False, single=keep_role)
    _save_state(screen, st)
    if kept is not None:
        kept.tag_redraw()
    return kept


ROWS = (("top", "persp"), ("front", "side"))


def _centre(*areas):
    x0 = min(a.x for a in areas)
    y0 = min(a.y for a in areas)
    x1 = max(a.x + a.width for a in areas)
    y1 = max(a.y + a.height for a in areas)
    return (x0 + x1) // 2, (y0 + y1) // 2


def _join(context, window, source_xy, target_xy):
    """``screen.area_join``: the area at ``source_xy`` takes over the one at ``target_xy`` (window px; same props in
    4.5 / 5.0 / 5.2)."""
    with context.temp_override(window=window, screen=window.screen):
        try:
            return bpy.ops.screen.area_join(source_xy=source_xy, target_xy=target_xy) == {'FINISHED'}
        except RuntimeError:
            return False


def _join_into(context, window, placed, keep_role):
    """The four panels back into the kept one, joined only with each other (``screen.area_close`` gave a closing
    panel to whichever neighbour shared its edge — the Outliner / Properties column took half the viewport).
    The other row first, then the kept panel takes its row mate, then the other row."""
    mine = next(r for r in ROWS if keep_role in r)
    other = next(r for r in ROWS if keep_role not in r)
    mate = next(r for r in mine if r != keep_role)
    k, m = placed[keep_role], placed[mate]
    o0, o1 = placed[other[0]], placed[other[1]]
    keep_c, mate_c = _centre(k), _centre(m)
    other_c = _centre(o0, o1)
    _join(context, window, _centre(o0), _centre(o1))
    _join(context, window, keep_c, mate_c)
    _join(context, window, keep_c, other_c)


def tap(context, area=None, window=None):
    """Maya Space tap over ``area``: in the four view the panel under the mouse (any editor) stays alone; the panel
    the four view was folded into (or any 3D View panel) becomes the four view again. Returns 'single' / 'four' when
    done, 'failed' when Blender refused the split / join (or the four view is folded for a moment, ``busy``), None
    when ``area`` is no panel of the layout (the caller maximizes it)."""
    window = window or context.window
    area = area or context.area
    from .toolbox import is_toolbox
    if window is None or area is None or (area.type == 'VIEW_3D' and is_toolbox(area.spaces.active)):
        return None
    if busy(window):
        return "failed"
    screen = window.screen
    four = block(screen)
    if four:
        if area.as_pointer() not in {a.as_pointer() for a in four.values()}:
            return None
        if bpy.app.background:
            return "failed"          # screen.area_join needs the Blender window
        return "single" if leave(context, keep=area, window=window) is not None else "failed"
    one = single(screen)
    if area.type != 'VIEW_3D' and (one is None or one.as_pointer() != area.as_pointer()):
        return None
    return "four" if enter(context, area, window) else "failed"


def toggle(context, area=None, window=None):
    """Maya Space tap: four view -> the panel under the mouse alone; one panel -> the four view again."""
    window = window or context.window
    area = area or context.area
    got = tap(context, area, window)
    if got == "four":
        return block(window.screen)
    if got == "single":
        return area
    return None


def set_layout(context, window, four, area=None):
    """Panels > Layouts / Tool Box quick layouts: Four View (``four``) or Single Perspective View. A four view is
    never split again and one panel never joined again. Returns the four view's roles / the single panel, None when
    nothing could be done."""
    from .toolbox import is_toolbox
    screen = window.screen
    if area is not None and area.type == 'VIEW_3D' and is_toolbox(area.spaces.active):
        area = None
    if four:
        placed = block(screen)
        if placed:
            return placed
        target = single(screen) or area
        return (enter(context, target, window) or None) if target is not None else None
    if is_four(screen):
        kept = leave(context, window=window, role="persp")
    else:
        kept = single(screen) or area
    if kept is not None and kept.type != 'VIEW_3D':
        kept.ui_type = 'VIEW_3D'          # Maya Single Perspective View = the persp camera's panel
    return kept


# --- docks and kit windows beside the whole four view ----------------------------------------------------------

_folded = set()          # window pointers whose four view is folded into one panel for a moment


def busy(window):
    return window is not None and window.as_pointer() in _folded


def fold(context, window, keep=None):
    """Fold the four view of ``window`` into one panel for a moment (``keep``: the panel that stays, else persp). The
    panel, or None. ``unfold`` brings the four view back."""
    kept = leave(context, keep=keep, window=window, role=None if keep is not None else "persp")
    if kept is not None:
        _folded.add(window.as_pointer())
    return kept


def unfold(context, window, panel, whole=None):
    """The four view again in ``panel`` (``fold``); its panels get their settings back. ``whole``: the panel's rect
    when it was just joined (``enter``). ``busy`` until the four view is whole."""
    ptr = window.as_pointer()
    if panel is None or is_four(window.screen) or not enter(context, panel, window, whole):
        _folded.discard(ptr)
        return
    release_when_whole(window)


def release_when_whole(window, tries=25):
    """``busy`` ends once the screen shows four whole panels again (areas changed in a call get their rects when the
    screen is next laid out, between ticks)."""
    from .. import live_refs
    ptr = window.as_pointer()
    left = [tries]

    def whole():
        win = live_refs.window(ptr)
        left[0] -= 1
        if win is None or len(block(win.screen)) == 4 or left[0] <= 0:
            _folded.discard(ptr)
            return None
        return 0.02
    bpy.app.timers.register(whole, first_interval=0.0)


def in_one_panel(context, window, action, keep=None):
    """Run ``action(context, window, panel)`` with the four view folded into one panel, then open the four view again
    in that panel, with its proportions. Used for a dock beside the whole four view, never inside one of its panels.
    The folded panel gets its size on the next tick (the action sizes the dock from it), and the action and the new
    four view run in that tick; the four view's last row is split one tick later (``enter``): two ticks folded.
    False when the four view could not be folded."""
    from .. import live_refs
    kept = fold(context, window, keep)
    if kept is None:
        return False
    win_ptr, kept_ptr = live_refs.pointer(window), kept.as_pointer()

    def again():
        win, panel = live_refs.find_area(kept_ptr, win_ptr or None)
        win = win or live_refs.window(win_ptr)
        try:
            if win is not None:
                with bpy.context.temp_override(window=win):
                    unfold(bpy.context, win, panel)
            else:
                _folded.discard(win_ptr)
        except (ReferenceError, RuntimeError):
            _folded.discard(win_ptr)
        return None

    def act():
        win, panel = live_refs.find_area(kept_ptr, win_ptr or None)
        if panel is None:
            _folded.discard(win_ptr)
            return None
        try:
            with bpy.context.temp_override(window=win):
                action(bpy.context, win, panel)
        except (ReferenceError, RuntimeError):
            pass
        return again()                 # the panel the action split keeps its place: the four view now
    bpy.app.timers.register(act, first_interval=0.0)
    return True


def beside(screen, area):
    """True when ``area`` (not a panel) shares most of one side of the four view on ``screen``: a dock column or row
    beside the whole view."""
    four = block(screen) if screen is not None else {}
    if not four or area is None or area.as_pointer() in {a.as_pointer() for a in four.values()}:
        return False
    r, q, gap = union(rect(a) for a in four.values()), rect(area), border_gap()

    def shared(lo0, hi0, lo1, hi1):
        return min(hi0, hi1) - max(lo0, lo1)
    if abs(q[2] - r[0]) <= gap or abs(q[0] - r[2]) <= gap:            # left / right of the view
        return shared(q[1], q[3], r[1], r[3]) > 0.6 * (r[3] - r[1])
    if abs(q[3] - r[1]) <= gap or abs(q[1] - r[3]) <= gap:            # below / above it
        return shared(q[0], q[2], r[0], r[2]) > 0.6 * (r[2] - r[0])
    return False


def pane_of(screen, area):
    """True when ``area`` is one of the panels of the four view on ``screen``."""
    return area is not None and area.as_pointer() in {a.as_pointer() for a in block(screen).values()}


def collapse_all(context):
    """Every four view back to its persp panel (switching to Blender / disabling: the user's screen as it was)."""
    if bpy.app.background:
        return 0
    n = 0
    for window in context.window_manager.windows:
        if is_four(window.screen):
            if leave(context, window=window, role="persp") is not None:
                n += 1
    return n
