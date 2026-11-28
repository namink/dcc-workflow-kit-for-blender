# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Outliner tree drawn by the kit inside Blender's Outliner (#348).

Maya's Outliner lists every DAG node as a row: a skeleton's joints are rows under their parent joint
(joint1 > joint2 > joint3), an object parented to a joint sits under that joint, the startup cameras lead the list
and the sets follow it. Blender's Outliner tree is C code Python can't add rows to, and Blender's own rows put a
skeleton's bones one level further down (under the armature data or "Pose"), next to the modifiers and data rows of
every mesh. So in a Maya Outliner the kit hides Blender's rows (``use_filter_object`` off) and draws every row
itself from a Python row model:

- a WINDOW POST_PIXEL handler draws the visible rows only (one triangle batch, one line batch, the names);
- operators placed first in the "Outliner" keymap (click) and the "View2D" keymap (wheel) handle the mouse and
  pass through anywhere but a kit tree;
- the model is rebuilt only when the scene structure (``outliner.structure_version``), the expanded rows or the
  Outliner's filters change — selection, motion and playback draw from the cached rows.

Which Outliners: Maya Outliners as the kit sets them up (``maya_outliner.setup``: View Layer mode, no collection
rows, no mode column). Blender's rows come back (``use_filter_object`` on) before a file is saved and when the kit
is disabled, so a file saved with the kit opens fine without it; they are hidden again after saving and loading.

Rows, in Maya order: the startup cameras the scene has no objects for (persp / top / front / side, hidden so
greyed), the DAG in creation order (``outliner_order``; Display > Sort Alphabetically sorts by name), then
defaultLightSet / defaultObjectSet and the kit sets (their members under them when expanded). A kit skeleton
(``skeleton<N>``) has no row of its own: each root joint is a top row, as in Maya where joint1 is the top node; a
skeleton the user named, or a Rigify rig, is an object row with its root joints under it. Display > Shapes adds the
shape row (object data, e.g. pCubeShape1) under each transform. Display > Children off lists every node flat; the
search field keeps the matching rows and the rows above them.

Expanded rows and the scroll position are session state (``EXPANDED`` / ``SCROLL`` / ``SCROLL_X``): nothing goes
into the scene. Maya's search field is a row the kit draws above the rows (Blender's Outliner header has one row
only); a click on it opens the real field in a popup (``maya_outliner.ALLSET_PT_outliner_search``).

Code: outliner_tree_rows (row model, expanded rows), outliner_tree_select (row selection),
outliner_tree_geometry (row geometry and shapes); this module keeps which Outliners show the tree, the rows
and row states each redraw reads, the draw, the mouse operators and register.
"""

import math

import bpy
from bpy.app.handlers import persistent
from bpy.props import IntProperty

from . import draw_replay
from .draw_replay import call
from .outliner_tree_rows import (ALL_TYPES, CAMERAS, DEFAULT_SETS, EXPANDED, Options, Row, STATS,  # noqa: F401
                                 TYPE_PROPS, WHEEL_ROWS, _Bones, _bump_expand, _cache, _drop_old_heads, _state, build,
                                 default_options, default_set_members, icon_kind, is_kit_skeleton, kit_skeleton_name,
                                 natural_key, options, set_expanded, subtree_keys, tail_rows, type_group)
from .outliner_tree_select import (_keep_hidden, active_row, deselect_all, is_picked, picked_unselectable,  # noqa: F401
                                   select_row, unselectable, visible_signature)
from .outliner_tree_geometry import (CHILD_SELECTED, COLUMNS, ICON_RGB, INSTANCE_RGB, JOINT_RGB, SCROLL,  # noqa: F401
                                     SCROLLBAR, SCROLL_X, SEARCH_ROW, _ICON_PARTS, _draw_restrict, _font_size, _icon,
                                     _quad, _restrict_textures, _triangle, column_xs, eye_x, first_row, page_rows,
                                     restrict_texture, row_index_at, row_rect, scrollbar, shift_x, top, unit)

# The kit tree replaces Blender's rows in Maya Outliners (tests switch it off to see Blender's rows).
ENABLED = True

HOVER = {}                # area pointer -> row under the mouse (drawn lighter, like Blender's Outliner)
SEEN = {}                 # region pointer -> [(kind, label, row on screen, depth)] of the last draw (tests read it)
DRAWN = {}                # region pointer -> [(y0, y1, Row)] of the last draw: where each shown row is
_handle = [None]


# --- which Outliners -----------------------------------------------------------------------------------------------

def wants_tree(space):
    """A Maya Outliner the kit set up (no mode column): the kit draws its rows."""
    if not ENABLED or space is None or getattr(space, "type", None) != 'OUTLINER':
        return False
    from .maya_outliner import is_maya_outliner
    return is_maya_outliner(space) and not space.show_mode_column


def is_tree(space):
    """The kit tree is shown here: a Maya Outliner with Blender's rows hidden."""
    return wants_tree(space) and not space.use_filter_object


def hide_rows(space):
    """Hide Blender's rows of a Maya Outliner (the kit draws them). True when it changed something."""
    if not wants_tree(space):
        return False
    from .maya_outliner import mark
    mark(space)
    if space.use_filter_object:
        space.use_filter_object = False
        return True
    return False


def _outliner_spaces():
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == 'OUTLINER':
                    yield space


def _kit_hidden(space):
    """A Maya Outliner whose Blender rows the kit hid (with the kit on or off)."""
    from .maya_outliner import is_maya_outliner
    return is_maya_outliner(space) and not space.show_mode_column and not space.use_filter_object


def hide_all():
    """Every Maya Outliner of the file shows the kit tree. Returns how many changed."""
    return sum(hide_rows(sp) for sp in _outliner_spaces())


def show_all():
    """Blender's rows back in every Maya Outliner (before saving, on disable). Returns how many changed."""
    n = 0
    for sp in _outliner_spaces():
        if _kit_hidden(sp):
            sp.use_filter_object = True
            n += 1
    return n


@persistent
def _on_save_pre(*_args):
    show_all()


@persistent
def _on_save_post(*_args):
    hide_all()


@persistent
def _on_load_post(*_args):
    _cache.clear()
    SCROLL.clear()
    EXPANDED.clear()
    _bump_expand()
    hide_all()


def _first_hide():
    try:
        hide_all()
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    return None


def rows_for(context, space):
    """The rows of a kit tree: cached head (cameras + DAG) + sets."""
    from .outliner import structure_version
    scene, view_layer = context.scene, context.view_layer
    opts = options(space)
    version = (structure_version(), _state["expand"])
    key = (*version, scene.as_pointer(), view_layer.as_pointer(), opts)
    head = _cache.get(key)
    if head is None:
        reuse = {r: r for h in _cache.values() for r in h}
        _drop_old_heads(version)
        if len(_cache) > 16:
            _cache.clear()
        head = _cache[key] = build(scene, view_layer, opts, reuse=reuse)
    return head + tail_rows(scene, opts)


# --- row state (drawn per visible row) ------------------------------------------------------------------------------

_by_name = {"key": None, "objects": {}, "count": -1, "counted": False}


def _map_names():
    """Map the names again, in the same dict (a redraw that already read it sees the new names)."""
    objects = bpy.data.objects
    mapped = _by_name["objects"]
    mapped.clear()
    # the first object of a name wins, like ``get`` (a linked object can share a local object's name)
    mapped.update(zip(reversed(objects.keys()), reversed(objects.values())))
    _by_name["count"] = len(objects)
    _by_name["counted"] = True


def object_names():
    """{name: object} of the file's objects for the rows being drawn: Blender finds a name by walking every object
    of the file (a quarter of a millisecond per row in a file of 5,000 objects), so the names are mapped once while
    the file's names and objects stay the same (``outliner.structure_version`` / ``objects_version``: a row's object
    can't be removed without them changing, so no removed object is kept). Read it once per redraw and look rows up
    with ``object_named``, which checks what it finds (a linked object found there also checks the object count
    once per redraw)."""
    from .outliner import objects_version, structure_version
    key = (structure_version(), objects_version())
    if _by_name["key"] != key:
        _map_names()
        _by_name["key"] = key
    else:
        _by_name["counted"] = False
    return _by_name["objects"]


def object_named(name, names=None):
    """``bpy.data.objects.get(name)``, from ``names`` (``object_names()``) when the object found there still carries
    the name.

    ``get`` returns the first object of that name in the file's list. A local object found under its own name is
    that one: local data-blocks come first in the list and no two local ones share a name (lib_id.cc
    ``id_sort_by_name``, ``BKE_id_new_name_validate``). A linked object can share its name with a local object or one
    of another library, so for one the map is first made again if objects came or went since it was made (the
    object count, read at most once per redraw); a removed object raises ReferenceError here (its Python object is
    invalidated when it is freed) and the name is looked up again."""
    if names is None:
        names = object_names()
    ob = names.get(name)
    try:
        if ob is not None and ob.name == name:
            if ob.library is None:
                return ob
            if names is _by_name["objects"] and not _by_name["counted"]:
                _by_name["counted"] = True
                if len(bpy.data.objects) != _by_name["count"]:
                    _map_names()
                    return object_named(name, _by_name["objects"])
            return ob
    except ReferenceError:
        pass
    return bpy.data.objects.get(name)


def _pose_or_edit_bone(ob, name):
    if ob.mode == 'EDIT':
        eb = ob.data.edit_bones.get(name)
        return None, eb
    pb = ob.pose.bones.get(name) if ob.pose is not None else None
    return pb, None


def row_state(context, row, live_objects, selected_set=None, signature=None, names=None):
    """(selected, active, hidden, live) of a row (``names``: ``object_names()`` read for the redraw)."""
    vl = context.view_layer
    kind = row.kind
    if kind in ('OBJECT', 'SHAPE', 'MEMBER'):
        ob = object_named(row.ob, names)
        if ob is None:
            return False, False, False, False
        posed = ob.type == 'ARMATURE' and ob.mode in ('POSE', 'EDIT') and kind == 'OBJECT'
        try:
            sel = ob.select_get() and not posed
            hidden = not ob.visible_get()
        except RuntimeError:            # not in the view layer
            sel, hidden = False, True
        if not sel and kind != 'SHAPE' and unselectable(ob):
            if signature is None:
                signature = visible_signature(context)
            elif callable(signature):
                signature = signature()
            sel = is_picked(ob, signature)
        act = sel and vl.objects.active == ob and kind != 'SHAPE'
        return sel, act, hidden, ob in live_objects
    if kind == 'JOINT':
        ob = object_named(row.ob, names)
        if ob is None or ob.type != 'ARMATURE':
            return False, False, False, False
        try:
            ob_hidden = not ob.visible_get()
        except RuntimeError:
            ob_hidden = True
        pb, eb = _pose_or_edit_bone(ob, row.sub)
        from . import layer_joints
        ob_hidden = ob_hidden or layer_joints.hidden(ob, row.sub)     # hidden by a display layer
        if eb is not None:
            sel = bool(eb.select_head or eb.select) and ob.mode == 'EDIT'
            act = sel and ob.data.edit_bones.active == eb
            return sel, act, ob_hidden or eb.hide, False
        if pb is None:
            return False, False, ob_hidden, False
        from .channel_box import bone_selected
        from .. import compat
        if ob.mode == 'OBJECT' and row.top:          # a picked kit skeleton = its root joints (Object Mode)
            try:
                sel = ob.select_get()
            except RuntimeError:
                sel = False
            return sel, sel and vl.objects.active == ob, ob_hidden or compat.bone_hidden(pb), False
        sel = ob.mode == 'POSE' and bone_selected(pb)
        act = sel and ob.data.bones.active is not None and ob.data.bones.active.name == row.sub
        return sel, act, ob_hidden or compat.bone_hidden(pb), False
    if kind == 'CAMERA':
        nothing = not context.selected_objects
        hl = nothing and _state["camera"] == row.ob
        return hl, False, not hl, False
    selected = selected_set if selected_set is not None else set(context.selected_objects)
    if kind == 'DEFAULT_SET':
        mem = _default_set_members(row.ob, context.scene)
        return bool(mem) and set(mem) == selected, False, False, False
    if kind == 'SET':
        from ..operators import sets
        coll = sets.get(row.ob)
        mem = sets.members(coll, context.scene) if coll is not None else []
        return bool(mem) and set(mem) == selected, False, False, False
    return False, False, False, False


_lights = {"key": None, "members": []}


def _default_set_members(name, scene):
    """``default_set_members`` for the drawn set rows: the scene's lights are listed again only when objects may
    have come or gone (an object's type never changes)."""
    if name != "defaultLightSet":
        return default_set_members(name, scene)
    from .outliner import objects_version, structure_version
    key = (objects_version(), structure_version(), scene.as_pointer(), len(scene.objects))
    if _lights["key"] != key:
        _lights["members"] = default_set_members(name, scene)
        _lights["key"] = key
    return list(_lights["members"])


def eye_state(row, names=None):
    """True / False = shown / hidden for an object or joint row, None for rows without an eye."""
    from .outliner_tree_edit import eye_state as state
    return state(row, names)


def sort_alpha(space):
    """The Outliner sorts its rows by name (compat: Blender 5.3's sort_method)."""
    from .. import compat
    return compat.outliner_sort_alpha(space)


def set_sort_alpha(space, on):
    from .. import compat
    compat.set_outliner_sort_alpha(space, on)


def column_state(row, col, names=None):
    """True / False = on / off for a row's column, None when the row has none (``names``: ``object_names()``)."""
    if col == 'EYE':
        return eye_state(row, names)
    from .outliner_tree_edit import restrict_state
    return restrict_state(row, col, names)


def selected_ancestors(context, limit=2000):
    """Expanded-state keys of the rows that have a selected object or picked joint below them."""
    from .outliner_tree_edit import ancestors_of, selected_items
    items = selected_items(context)
    if len(items) > limit:
        return set()
    return ancestors_of(items)


def draw():
    context = bpy.context
    space, region, area = context.space_data, context.region, context.area
    if region is None or area is None or region.type != 'WINDOW' or not is_tree(space):
        return
    try:
        _draw(context, space, region, area)
    except ReferenceError:
        pass
    except Exception:                  # a broken draw prints once, not at every redraw
        if not _state.get("draw_error"):
            _state["draw_error"] = True
            import traceback
            traceback.print_exc()


def instance_keys(context):
    """Row keys of the instance copies (made by Duplicate Special > Instance, still sharing their data) and of the
    instance groups above them; the originals and the groups holding them stay unmarked."""
    from ..operators.duplicate import INSTANCE_TAG, is_instance
    keys = set()
    for ob in context.view_layer.objects:
        if ob.get(INSTANCE_TAG) and is_instance(ob):
            while ob is not None and ob.get(INSTANCE_TAG) and ('O', ob.session_uid) not in keys:
                keys.add(('O', ob.session_uid))
                ob = ob.parent
    return keys


def _draw_instance_tip(prefs, region, u, dy, x, y0, y1, ob_name, by_name):
    """A tooltip box "Instance of <source>" under the hovered instance row (above it at the bottom edge)."""
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader
    from ..operators.duplicate import instance_source
    try:
        ob = object_named(ob_name, by_name)
        source = instance_source(ob) if ob is not None else ""
    except ReferenceError:
        return
    from .. import i18n
    label = bpy.app.translations.pgettext_iface(i18n.mark("Instance of"))
    label = f"{label} {source}" if source else bpy.app.translations.pgettext_iface(i18n.mark("Instance"))
    wcol = prefs.themes[0].user_interface.wcol_tooltip
    pad, w = 0.3 * u, blf.dimensions(0, label)[0]
    bx0 = max(0.0, min(x, region.width - w - 2 * pad))
    by1 = y0 - 2 if y0 - u - 2 >= 0 else y1 + u + 2
    by0 = by1 - u
    tris, tcol = [], []
    _quad(tris, tcol, bx0, by0, bx0 + w + 2 * pad, by1, (*tuple(wcol.outline)[:3], 1.0))
    _quad(tris, tcol, bx0 + 1, by0 + 1, bx0 + w + 2 * pad - 1, by1 - 1, (*tuple(wcol.inner)[:3], 1.0))
    sh = gpu.shader.from_builtin('SMOOTH_COLOR')
    call(batch_for_shader(sh, 'TRIS', {"pos": tris, "color": tcol}).draw, sh)
    call(blf.color, 0, *tuple(wcol.text)[:3], 1.0)
    call(blf.position, 0, round(bx0 + pad), round((by0 + by1) / 2 - dy), 0)
    call(blf.draw, 0, label)


def _draw(context, space, region, area):
    STATS["draws"] += 1
    key = ("outliner", region.as_pointer())
    sig = (region.width, region.height, context.preferences.system.ui_scale, HOVER.get(area.as_pointer()))
    if draw_replay.again(key, sig):     # a window moves: the rows as drawn last
        return
    with draw_replay.recording(key, sig):
        _draw_rows(context, space, region, area)


def _draw_rows(context, space, region, area):
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader
    from . import kit_icons
    from ..operators import live
    prefs = context.preferences
    u = unit(prefs)
    rows = rows_for(context, space)
    n = len(rows)
    first = first_row(area, region, n, u)
    last = min(n, first + top(region, u) // u + 1)
    sx = shift_x(area, rows, u)
    th = prefs.themes[0].outliner
    text = tuple(th.space.text)[:3]
    text_hi = tuple(th.space.text_hi)[:3]
    sel_rgba = (*tuple(th.selected_highlight)[:3], 1.0)
    act_rgba = (*tuple(th.active)[:3], 1.0)
    sel_text = tuple(th.selected_object)[:3]
    act_text = tuple(th.active_object)[:3]
    live_objects = set(live.objects(context.scene))
    selected_set = set(context.selected_objects)
    sig = []

    def signature():
        if not sig:
            sig.append(visible_signature(context))
        return sig[0]
    # Maya: a row with a selected node somewhere below it gets a dim highlight (collapsed or not)
    back = tuple(th.space.back)[:3]
    child_rgba = (*(b + (c - b) * CHILD_SELECTED for b, c in zip(back, sel_rgba[:3])), 1.0)
    above = selected_ancestors(context)
    from .. import preferences
    # instance copies purple with a chain-link badge: an add-on preference (Maya draws them like other objects)
    instances = instance_keys(context) if preferences.get(context).outliner_instance_marks else ()
    by_name = object_names()
    cols = column_xs(space, region, u, n, first)
    tris, tcol, lines, lcol, textures, names, icons = [], [], [], [], [], [], []
    seen, drawn = [], []
    tip = None                 # the hovered instance row: (name x, y0, y1, object name) for its "Instance of" tip
    r_icon = 0.36 * u
    for k in range(first, last):
        row = rows[k]
        j = k - first
        y1 = top(region, u) - j * u
        y0 = y1 - u
        cy = (y0 + y1) / 2.0
        sel, act, hidden, is_live = row_state(context, row, live_objects, selected_set, signature, by_name)
        if sel:
            _quad(tris, tcol, 0, y0, region.width, y1, act_rgba if act else sel_rgba)
        elif row.key is not None and row.key in above:
            _quad(tris, tcol, 0, y0, region.width, y1, child_rgba)
        if HOVER.get(area.as_pointer()) == k:
            _quad(tris, tcol, 0, y0, region.width, y1, (*text_hi, 0.05))
        alpha = 0.5 if hidden and not sel else 1.0      # greyed row: name, icon and column icons
        for col, cx in cols.items():
            # a drawn startup camera (no object) shows a real one's state: selectable, hidden, not rendered
            on = (col == 'SELECT') if row.kind == 'CAMERA' else column_state(row, col, by_name)
            if on is not None:
                icons.append((col, on, int(cx) - u // 2, y0, alpha))
        x = row.depth * u - sx
        if row.kids:
            _triangle(tris, tcol, x + 0.6 * u, cy, u * 0.17, row.open, (*text, 0.8))
        ix = x + 1.5 * u
        if row.icon in ('SET', 'CAMERA_ROW'):
            textures.append(("outliner:SET" if row.icon == 'SET' else "outliner:CAMERA", ix, cy, hidden and not sel))
        else:
            rgb = INSTANCE_RGB if row.key in instances else JOINT_RGB if row.icon == 'JOINT' else ICON_RGB
            _icon(tris, tcol, lines, lcol, row.icon, ix, cy, r_icon * (0.8 if row.kind == 'SHAPE' else 1.0),
                  (*rgb, alpha))
            if row.key in instances:     # chain-link badge on the icon's lower right corner
                bx, by, br = ix + 0.6 * r_icon, cy - 0.55 * r_icon, 0.75 * r_icon
                under = (act_rgba if act else sel_rgba)[:3] if sel else back
                _icon(tris, tcol, lines, lcol, 'INSTANCE_BACK', bx, by, br, (*under, 1.0))
                _icon(tris, tcol, lines, lcol, 'INSTANCE', bx, by, br, (*INSTANCE_RGB, alpha))
                if HOVER.get(area.as_pointer()) == k:
                    tip = (x + 2.25 * u, y0, y1, row.ob)
        if is_live:
            rgb = live.COLOR
        elif act and row.kind in ('OBJECT', 'JOINT'):
            rgb = act_text
        elif sel and row.kind in ('OBJECT', 'JOINT'):
            rgb = sel_text
        elif row.key in instances:
            rgb = INSTANCE_RGB
        else:
            rgb = text_hi if sel else text
        names.append((x + 2.25 * u, cy, row.label, (*rgb, alpha)))
        seen.append((row.kind, row.label, j, row.depth))
        drawn.append((y0, y1, row))
    bar = scrollbar(region, u, n, first)
    if bar is not None:
        x0, x1, b0, b1 = bar
        _quad(tris, tcol, x0, b0, x1, b1, (*text, 0.35))
    # Maya's search field on its own row (drawn; a click opens the real field, ``ALLSET_PT_outliner_search``)
    field = prefs.themes[0].user_interface.wcol_text
    pad = max(2, round(0.15 * u))
    fy0, fy1, fx1 = top(region, u) + pad, region.height - pad, region.width - pad
    _quad(tris, tcol, pad, fy0, fx1, fy1, (*tuple(field.outline)[:3], 1.0))
    _quad(tris, tcol, pad + 1, fy0 + 1, fx1 - 1, fy1 - 1, (*tuple(field.inner)[:3], 1.0))
    fcy, glass = (fy0 + fy1) / 2.0, 0.2 * u       # magnifier: ring + handle
    gx, grgba = pad + 0.6 * u, (*tuple(field.text)[:3], 0.8)
    ring = [(gx + glass * math.cos(a * math.pi / 6), fcy + 1 + glass * math.sin(a * math.pi / 6)) for a in range(13)]
    for a, b in zip(ring, ring[1:]):
        lines.extend((a, b))
    lines.extend(((gx + 0.7 * glass, fcy + 1 - 0.7 * glass), (gx + 1.8 * glass, fcy + 1 - 1.8 * glass)))
    lcol.extend((grgba,) * 26)
    query = space.filter_text
    names.append((pad + 1.3 * u, fcy, query or bpy.app.translations.pgettext_iface("Search..."),
                  (*tuple(field.text)[:3], 1.0 if query else 0.5)))
    call(gpu.state.blend_set, 'ALPHA')
    if tris:
        sh = gpu.shader.from_builtin('SMOOTH_COLOR')
        call(batch_for_shader(sh, 'TRIS', {"pos": tris, "color": tcol}).draw, sh)
    if lines:
        sh = gpu.shader.from_builtin('SMOOTH_COLOR')
        call(batch_for_shader(sh, 'LINES', {"pos": lines, "color": lcol}).draw, sh)
    for name, cx, cy, greyed in textures:
        size = kit_icons.size_for(name, prefs.system.ui_scale)
        kit_icons.draw_texture(name, math.floor(cx - size / 2), math.floor(cy - size / 2), size, greyed)
    _draw_restrict(icons, text, u)
    call(blf.size, 0, _font_size(prefs))
    dy = 0.32 * blf.dimensions(0, "Xg")[1] + 1
    for x, cy, label, rgba in names:
        call(blf.color, 0, *rgba)
        call(blf.position, 0, round(x), round(cy - dy), 0)
        call(blf.draw, 0, label)
    if tip is not None:
        _draw_instance_tip(prefs, region, u, dy, *tip, by_name)
    call(gpu.state.blend_set, 'NONE')
    SEEN[region.as_pointer()] = seen
    DRAWN[region.as_pointer()] = drawn
    for d in (SEEN, DRAWN):
        while len(d) > 32:
            del d[next(iter(d))]


def redraw_rows(context, area):
    """Redraw the kit rows of the Outliner ``area`` after a scroll or a hover change (``context`` = its main region).
    ``area.tag_redraw()`` also redraws the header and makes Blender rebuild its own Outliner tree before drawing (one
    element per object of the view layer, though the kit hides those rows): Blender rebuilds unless the region was
    tagged "no rebuild" (outliner_tree.cc ``outliner_build_tree``), which its own view scrolling does
    (view2d_ops.cc ``view_pan_apply_ex``). A view pan by nothing tags it the same way: the view stays where it is and
    only the rows redraw. The pan also sends a mouse move where the mouse already is (``view_pan_apply_ex``); the
    hover keeps its row for that one (``ALLSET_OT_outliner_tree_hover``), as after a plain redraw."""
    region = context.region
    if region is not None and region.type == 'WINDOW' and context.area == area:
        try:
            if bpy.ops.view2d.pan(deltax=0, deltay=0) == {'FINISHED'}:
                _state["pan_move"] = area.as_pointer()
                return
        except RuntimeError:            # no View2D to pan here
            pass
    area.tag_redraw()


def redraw_outliners(context=None):
    wm = (context or bpy.context).window_manager
    for w in wm.windows:
        for a in w.screen.areas if w.screen else ():
            if a.type == 'OUTLINER':
                a.tag_redraw()


# --- operators -----------------------------------------------------------------------------------------------------

def _poll(context):
    region = context.region
    return region is not None and region.type == 'WINDOW' and is_tree(context.space_data)


def click_mode(event):
    if event.ctrl and event.shift:
        return 'RANGE_ADD'
    return 'TOGGLE' if event.ctrl else 'RANGE' if event.shift else 'REPLACE'


_click = {"key": None, "time": 0.0}


def is_double_click(context, key, now=None):
    """True when this press on row ``key`` follows a press on the same row within the double-click time (the kit
    times it: simulated events carry no double-click, and the press item takes both presses)."""
    import time
    now = time.monotonic() if now is None else now
    limit = context.preferences.inputs.mouse_double_click_time / 1000.0
    double = _click["key"] == key and now - _click["time"] <= limit
    _click.update(key=None if double else key, time=0.0 if double else now)
    return double


DRAG_ROWS = 0.5        # x row height the mouse moves before a press becomes a drag over rows


class ALLSET_OT_outliner_tree_click(bpy.types.Operator):
    """Click a row to select it (Ctrl: toggle, Shift: range, Ctrl+Shift: add), drag over rows to select them, click
    its arrow to expand it (Shift: with everything below), double-click its name to rename it, click empty space to
    select nothing"""
    bl_idname = "allset.outliner_tree_click"
    bl_label = "Outliner Select"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        area, region, space = context.area, context.region, context.space_data
        u = unit(context.preferences)
        rows = rows_for(context, space)
        n = len(rows)
        x, y = event.mouse_region_x, event.mouse_region_y
        if y >= top(region, u):     # the search row: a real text field can only live in a popup
            bpy.ops.wm.call_panel(name="ALLSET_PT_outliner_search", keep_open=False)
            return {'FINISHED'}
        first = first_row(area, region, n, u)
        bar = scrollbar(region, u, n, first)
        self.scrolling = False
        self.column = None
        if bar is not None and bar[0] - 2 <= x <= region.width:
            return self._start_scroll(context, event, bar, n, u)
        k = row_index_at(area, region, y, u, n)
        if k is None:
            _click.update(key=None, time=0.0)
            if event.shift or event.ctrl:
                return {'CANCELLED'}
            deselect_all(context)
            redraw_outliners(context)
            return {'FINISHED'}
        row = rows[k]
        x0 = row.depth * u - shift_x(area, rows, u)
        hit = next((c for c, cx in column_xs(space, region, u, n, first).items() if abs(x - cx) <= 0.5 * u), None)
        if hit is not None and column_state(row, hit) is not None:
            # Blender: the press flips the icon, dragging gives every icon passed (any row, any column) the same
            # state, Shift takes everything below each row too
            _click.update(key=None, time=0.0)
            self.column, self.column_cells, self.column_last, self.u = not column_state(row, hit), {(k, hit)}, (x, y), u
            self._set_column(context, rows, k, hit, event.shift)
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        if row.kids and x0 <= x < x0 + 1.1 * u:
            _click.update(key=None, time=0.0)
            keys = subtree_keys(context, space, row) if event.shift else [row.key]
            set_expanded(keys, not row.open)
            redraw_outliners(context)
            return {'CANCELLED'}           # view only: no undo step (the press is still taken)
        key = (row.kind, row.ob, row.sub)
        # Blender sends a fast second press as DOUBLE_CLICK; simulated events never do, so the kit times presses too
        double = event.value == 'DOUBLE_CLICK' or is_double_click(context, key)
        if double and not (event.shift or event.ctrl):
            _click.update(key=None, time=0.0)
            bpy.ops.allset.outliner_tree_rename('INVOKE_DEFAULT')
            return {'CANCELLED'}           # the first press made the selection (and its undo step)
        self.mode = click_mode(event)
        self.anchor = k if self.mode in ('REPLACE', 'TOGGLE') else active_row(context, rows)
        select_row(context, rows, k, self.mode, anchor=self.anchor)
        redraw_outliners(context)
        # Maya: dragging over rows selects them (from the pressed row)
        self.press_y, self.last, self.dragging, self.u = y, k, False, u
        self.pressed = k
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _drag(self, context, event):
        area, region, space = context.area, context.region, context.space_data
        u = self.u
        y = event.mouse_region_y
        if not self.dragging and abs(y - self.press_y) < DRAG_ROWS * u:
            return
        self.dragging = True
        rows = rows_for(context, space)
        n = len(rows)
        if y >= top(region, u) and SCROLL.get(area.as_pointer(), 0) > 0:      # past the top / bottom: scroll
            SCROLL[area.as_pointer()] -= 1
        elif y < 0:
            SCROLL[area.as_pointer()] = SCROLL.get(area.as_pointer(), 0) + 1
        first = first_row(area, region, n, u)
        yy = min(max(y, 0), top(region, u) - 1)
        k = row_index_at(area, region, yy, u, n)
        if k is None:
            k = n - 1 if yy < top(region, u) / 2 else first
        if k == self.last or n == 0:
            return
        self.last = k
        mode = 'RANGE_ADD' if self.mode in ('TOGGLE', 'RANGE_ADD') else 'RANGE'
        select_row(context, rows, k, mode, anchor=self.pressed)
        redraw_outliners(context)

    def _set_column(self, context, rows, k, col, recursive):
        from .outliner_tree_edit import set_column
        if column_state(rows[k], col) is not None:
            set_column(context, rows[k], col, self.column, recursive)
            redraw_outliners(context)

    def _drag_column(self, context, event):
        area, region, space = context.area, context.region, context.space_data
        rows = rows_for(context, space)
        n, u = len(rows), self.u
        xs = column_xs(space, region, u, n, first_row(area, region, n, u))
        (x0, y0), (x1, y1) = self.column_last, (event.mouse_region_x, event.mouse_region_y)
        self.column_last = (x1, y1)
        steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) * 4 / u))     # a fast move skips no icon
        for i in range(1, steps + 1):
            x, y = x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps
            k = row_index_at(area, region, y, u, n)
            col = next((c for c, cx in xs.items() if abs(x - cx) <= 0.5 * u), None)
            if k is not None and col is not None and (k, col) not in self.column_cells:
                self.column_cells.add((k, col))
                self._set_column(context, rows, k, col, event.shift)

    # the scrollbar: drag the thumb, a click above / below it pages
    def _start_scroll(self, context, event, bar, n, u):
        _x0, _x1, b0, b1 = bar
        region, area = context.region, context.area
        y = event.mouse_region_y
        page = page_rows(region, u)
        key = area.as_pointer()
        if not b0 <= y <= b1:
            SCROLL[key] = SCROLL.get(key, 0) + (page if y < b0 else -page)
            first_row(area, region, n, u)
            area.tag_redraw()
            return {'CANCELLED'}
        self.scrolling = True
        self.grab = (y, SCROLL.get(key, 0), n, u, b1 - b0)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if self.column is not None:
            if event.type == 'MOUSEMOVE':
                self._drag_column(context, event)
            elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE' or event.type == 'ESC':
                return {'FINISHED'}                # one undo step for the press and the drag
            return {'RUNNING_MODAL'}
        if not self.scrolling:
            if event.type == 'MOUSEMOVE':
                self._drag(context, event)
            elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE' or event.type == 'ESC':
                return {'FINISHED'}
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            y0, first0, n, u, thumb = self.grab
            region, area = context.region, context.area
            page = page_rows(region, u)
            span = max(1.0, top(region, u) - thumb)
            SCROLL[area.as_pointer()] = int(round(first0 + (y0 - event.mouse_region_y) / span * (n - page)))
            first_row(area, region, n, u)
            area.tag_redraw()
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE' or event.type in ('ESC', 'RIGHTMOUSE'):
            return {'CANCELLED'}           # view only: no undo step
        return {'RUNNING_MODAL'}


class ALLSET_OT_outliner_tree_hover(bpy.types.Operator):
    """Light up the Outliner row under the mouse"""
    bl_idname = "allset.outliner_tree_hover"
    bl_label = "Outliner Hover"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.region is not None and context.region.type == 'WINDOW'

    def invoke(self, context, event):
        if _poll(context):
            area, region = context.area, context.region
            xy = (event.mouse_x, event.mouse_y)
            moved, _state["hover_xy"] = xy != _state.get("hover_xy"), xy
            if _state.pop("pan_move", None) == area.as_pointer() and not moved:
                return {'PASS_THROUGH'}     # the mouse move a ``redraw_rows`` pan sends: the mouse did not move
            rows = rows_for(context, context.space_data)
            k = row_index_at(area, region, event.mouse_region_y, unit(context.preferences), len(rows))
            if HOVER.get(area.as_pointer()) != k:
                HOVER[area.as_pointer()] = k
                redraw_rows(context, area)
        return {'PASS_THROUGH'}


class ALLSET_OT_outliner_tree_scroll(bpy.types.Operator):
    """Scroll the Maya Outliner rows"""
    bl_idname = "allset.outliner_tree_scroll"
    bl_label = "Outliner Scroll"
    bl_options = {'INTERNAL'}

    rows: IntProperty(options={'SKIP_SAVE'})     # + down, - up; 0 with page: a page

    page: IntProperty(options={'SKIP_SAVE'})     # +1 page down, -1 page up

    @classmethod
    def poll(cls, context):
        return context.region is not None and context.region.type == 'WINDOW'

    def invoke(self, context, event):
        if not _poll(context):
            return {'PASS_THROUGH'}
        return self.execute(context)

    def execute(self, context):
        if not _poll(context):
            return {'CANCELLED'}
        area, region, space = context.area, context.region, context.space_data
        u = unit(context.preferences)
        n = len(rows_for(context, space))
        step = self.rows + self.page * page_rows(region, u)
        key = area.as_pointer()
        SCROLL[key] = SCROLL.get(key, 0) + step
        first_row(area, region, n, u)
        redraw_rows(context, area)
        return {'FINISHED'}


class ALLSET_OT_outliner_tree_pan(bpy.types.Operator):
    """Pan the Maya Outliner rows in both directions (Maya: Alt+middle-drag, like a 2D view)"""
    bl_idname = "allset.outliner_tree_pan"
    bl_label = "Outliner Pan"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.region is not None and context.region.type == 'WINDOW'

    def invoke(self, context, event):
        if not _poll(context):
            return {'PASS_THROUGH'}
        key = context.area.as_pointer()
        self.start = (event.mouse_x, event.mouse_y, SCROLL_X.get(key, 0), SCROLL.get(key, 0))
        context.window.cursor_modal_set('SCROLL_XY')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def pan(self, context, dx, dy):
        """Move the rows by (dx, dy) pixels from where the drag started (+x right, +y up)."""
        x0, y0, sx0, first0 = self.start
        area, region = context.area, context.region
        u = unit(context.preferences)
        rows = rows_for(context, context.space_data)
        key = area.as_pointer()
        SCROLL_X[key] = sx0 - dx
        SCROLL[key] = first0 + round(dy / u)
        shift_x(area, rows, u)
        first_row(area, region, len(rows), u)
        redraw_rows(context, area)

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self.pan(context, event.mouse_x - self.start[0], event.mouse_y - self.start[1])
        elif event.type in ('ESC', 'RIGHTMOUSE'):
            self.pan(context, 0, 0)
            context.window.cursor_modal_restore()
            return {'CANCELLED'}
        elif event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
            context.window.cursor_modal_restore()
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


classes = (ALLSET_OT_outliner_tree_click, ALLSET_OT_outliner_tree_hover, ALLSET_OT_outliner_tree_scroll,
           ALLSET_OT_outliner_tree_pan)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    _handle[0] = bpy.types.SpaceOutliner.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')
    for handlers, fn in ((bpy.app.handlers.save_pre, _on_save_pre), (bpy.app.handlers.save_post, _on_save_post),
                         (bpy.app.handlers.load_post, _on_load_post)):
        if fn not in handlers:
            handlers.append(fn)
    if not bpy.app.timers.is_registered(_first_hide):
        bpy.app.timers.register(_first_hide, first_interval=0.0)


def unregister():
    if bpy.app.timers.is_registered(_first_hide):
        bpy.app.timers.unregister(_first_hide)
    for handlers, fn in ((bpy.app.handlers.save_pre, _on_save_pre), (bpy.app.handlers.save_post, _on_save_post),
                         (bpy.app.handlers.load_post, _on_load_post)):
        while fn in handlers:
            handlers.remove(fn)
    try:
        show_all()
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    if _handle[0] is not None:
        bpy.types.SpaceOutliner.draw_handler_remove(_handle[0], 'WINDOW')
        _handle[0] = None
    _cache.clear()
    _ICON_PARTS.clear()
    SEEN.clear()
    DRAWN.clear()
    SCROLL.clear()
    SCROLL_X.clear()
    HOVER.clear()
    _restrict_textures.clear()      # Blender's column icons as GPU textures
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
