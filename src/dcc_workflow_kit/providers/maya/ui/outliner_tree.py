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

Expanded rows and the scroll position are session state (``EXPANDED`` / ``SCROLL``): nothing goes into the scene.
"""

import fnmatch
import math
import re
from collections import namedtuple

import bpy
from bpy.app.handlers import persistent
from bpy.props import IntProperty

# The kit tree replaces Blender's rows in Maya Outliners (tests switch it off to see Blender's rows).
ENABLED = True

Row = namedtuple("Row", "kind ob sub depth kids open label icon key top", defaults=(False,))
# kind: 'CAMERA' (a startup camera the scene has no object for), 'OBJECT', 'JOINT', 'SHAPE', 'DEFAULT_SET', 'SET',
#       'MEMBER'; ob: object / armature / set / camera name; sub: bone name (JOINT), data name (SHAPE), set (MEMBER);
# kids: has an expand arrow; open: expanded; icon: icon kind; key: expanded-state key (None: can't expand);
# top: a kit skeleton's root joint (the skeleton's own row: picked whenever the skeleton object is)
Options = namedtuple("Options", "children sort_alpha shapes types search case complete")

TYPE_PROPS = (('MESH', "use_filter_object_mesh"), ('ARMATURE', "use_filter_object_armature"),
              ('EMPTY', "use_filter_object_empty"), ('LIGHT', "use_filter_object_light"),
              ('CAMERA', "use_filter_object_camera"), ('GREASEPENCIL', "use_filter_object_grease_pencil"),
              ('OTHERS', "use_filter_object_others"))
ALL_TYPES = frozenset(t for t, _p in TYPE_PROPS)
CAMERAS = ("persp", "top", "front", "side")
DEFAULT_SETS = ("defaultLightSet", "defaultObjectSet")
WHEEL_ROWS = 3

EXPANDED = set()          # ('O', object session_uid) / ('B', armature session_uid, bone name)
SCROLL = {}               # area pointer -> first shown row
HOVER = {}                # area pointer -> row under the mouse (drawn lighter, like Blender's Outliner)
SEEN = {}                 # region pointer -> [(kind, label, row on screen, depth)] of the last draw (tests read it)
DRAWN = {}                # region pointer -> [(y0, y1, Row)] of the last draw: where each shown row is
STATS = {"builds": 0, "draws": 0}
_state = {"expand": 0, "camera": ""}
_cache = {}               # (structure, expand, scene, view layer, options) -> head rows
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
    if wants_tree(space) and space.use_filter_object:
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


# --- row model -----------------------------------------------------------------------------------------------------

def options(space):
    types = frozenset(t for t, prop in TYPE_PROPS if getattr(space, prop, True))
    return Options(space.use_filter_children, space.sort_method == "ALPHA", space.use_filter_object_content, types,
                   space.filter_text, space.use_filter_case_sensitive, space.use_filter_complete)


def default_options(**kw):
    base = dict(children=True, sort_alpha=False, shapes=False, types=ALL_TYPES, search="", case=False,
                complete=False)
    base.update(kw)
    return Options(**base)


def type_group(ob):
    return _type_group(ob.type)


def _type_group(t):
    """``type_group`` of an object of type ``t``."""
    if t in ('MESH', 'ARMATURE', 'EMPTY', 'LIGHT', 'CAMERA'):
        return t
    if t in ('GREASEPENCIL', 'GPENCIL'):
        return 'GREASEPENCIL'
    return 'OTHERS'


def natural_key(name):
    """Blender's natural, case-insensitive name order (pCube2 before pCube10)."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t.lower()) for t in re.split(r"(\d+)", name) if t]


def icon_kind(ob):
    from ..operators import create
    from .hypergraph_layout import node_kind
    return node_kind(ob.type, bool(ob.get(create.LOCATOR_PROP)))


def _icon_kinds():
    """``icon_kind`` as a function of (object, its type) for one rows build: the imports are done once, and only an
    empty's kind depends on the locator property (``node_kind``), so only empties read it."""
    from ..operators import create
    from .hypergraph_layout import node_kind
    prop = create.LOCATOR_PROP
    kinds = {}

    def kind(ob, t):
        if t == 'EMPTY':
            return node_kind(t, bool(ob.get(prop)))
        got = kinds.get(t)
        if got is None:
            got = kinds[t] = node_kind(t)
        return got
    return kind


class _Bones:
    """An armature's joints: the bone list (edit bones in Edit Mode), roots and children by name, in Maya child
    order (``joints.child_order_key``: creation order, a re-parented joint last)."""

    def __init__(self, ob, sort_alpha=False):
        from ..operators.joints import CHILD_ORDER
        data = ob.data
        self.coll = data.edit_bones if data.is_editmode else data.bones
        index = {}
        stamp = {}
        kids = {}
        roots = []
        for i, b in enumerate(self.coll):
            index[b.name] = i
            s = b.get(CHILD_ORDER)
            stamp[b.name] = float(s) if s is not None else float(i)
            parent = b.parent
            (kids.setdefault(parent.name, []) if parent is not None else roots).append(b.name)
        key = natural_key if sort_alpha else stamp.__getitem__
        self.roots = sorted(roots, key=key)
        self.kids = {n: sorted(v, key=key) for n, v in kids.items()}
        self.names = set(index)


def kit_skeleton_name(ob):
    """``ob`` is an armature named like a skeleton the kit made (``skeleton<N>``, ``skeleton<N>.001``)."""
    from ..operators import joints
    if ob.type != 'ARMATURE' or not ob.name.startswith(joints.SKELETON_BASE):
        return False
    tail = ob.name[len(joints.SKELETON_BASE):].split(".")[0]
    return not tail or tail.isdigit()


def is_kit_skeleton(ob, bones):
    """A skeleton the kit named (``skeleton<N>``) with a root joint: Maya's root joint is its top node, so the
    skeleton gets no row of its own."""
    return kit_skeleton_name(ob) and bool(bones.roots)


def _matcher(opts):
    text = opts.search
    if not text:
        return None
    pattern = text if opts.complete else f"*{text}*"
    if opts.case:
        return lambda label: fnmatch.fnmatchcase(label, pattern)
    pattern = pattern.lower()
    return lambda label: fnmatch.fnmatchcase(label.lower(), pattern)


def build(scene, view_layer, opts, expand_all=False, reuse=None):
    """Startup camera + DAG rows of ``view_layer`` for the filters ``opts`` (an ``Options``).

    ``reuse``: {row: row} of rows built before; a new row equal to one of them is that row. A rebuild after an edit
    then makes new rows only for what changed: Python's garbage collector counts every row that lives on as a new
    long-lived object, and enough of those start a full pass over every object."""
    from ..operators import startup_cameras
    from . import outliner_order
    STATS["builds"] += 1
    keep = (reuse or {}).get
    match = _matcher(opts)
    flat = not opts.children
    open_all = expand_all or flat or match is not None
    shown = opts.types
    layer = [o for o in view_layer.objects if o is not None]    # None: a base removed since the last sync
    in_layer = set(layer)
    if opts.sort_alpha:
        def order(o):
            return natural_key(o.name)
    else:
        numbers = dict(outliner_order.numbers(list(scene.objects)))
        big = 1 << 40

        def order(o):
            return (numbers.get(o, big), o.name)
    bones = {}

    def bones_of(ob):
        got = bones.get(ob)
        if got is None:
            got = bones[ob] = _Bones(ob, opts.sort_alpha)
        return got

    hidden = "allset_hidden_in_outliner"      # Maya Hide In Outliner (outliner_tree_edit.HIDDEN)
    kids, bone_kids, roots = {}, {}, []
    for ob in layer:
        if ob.get(hidden):
            continue
        p = ob.parent
        if p is None or p not in in_layer:
            roots.append(ob)
        elif ob.parent_type == 'BONE' and p.type == 'ARMATURE' and ob.parent_bone in bones_of(p).names:
            bone_kids.setdefault((p, ob.parent_bone), []).append(ob)
        else:
            kids.setdefault(p, []).append(ob)
    for d in (kids, bone_kids):
        for v in d.values():
            v.sort(key=order)
    roots.sort(key=order)

    def node(kind, ob_name, sub, depth, key, label, icon, children, type_ok=True, top=False):
        """Rows of one node and what's under it; ``children(depth)`` -> rows of its children."""
        has = children is not None
        is_open = has and (open_all or key in EXPANDED)
        below = children(depth if flat or not type_ok else depth + 1) if is_open or (has and not type_ok) else []
        if not type_ok:          # filtered out by Show: its children take its place
            return below
        if match is not None and not match(label) and not below:
            return []
        row = Row(kind, ob_name, sub, 0 if flat else depth, has and not flat, is_open, label, icon, key, top)
        return [keep(row, row)] + below

    def visit_bone(ob, b, name, depth, extra=(), top=False):
        child_names = b.kids.get(name, ())
        objs = list(bone_kids.get((ob, name), ())) + list(extra)

        def children(d):
            rows = []
            for c in child_names:
                rows += visit_bone(ob, b, c, d)
            for o in objs:
                rows += visit(o, d)
            return rows
        return node('JOINT', ob.name, name, depth, ('B', ob.session_uid, name), name, 'JOINT',
                    children if child_names or objs else None, 'ARMATURE' in shown, top)

    kind_of = _icon_kinds()

    def visit(ob, depth):
        t = ob.type
        b = bones_of(ob) if t == 'ARMATURE' else None
        obj_kids = kids.get(ob, ())
        if b is not None and is_kit_skeleton(ob, b):
            rows = []
            for i, root in enumerate(b.roots):
                rows += visit_bone(ob, b, root, depth, obj_kids if i == 0 else (), top=True)
            return rows
        shape = opts.shapes and ob.data is not None and t not in ('ARMATURE', 'EMPTY')
        roots_b = b.roots if b is not None else ()
        name = ob.name
        icon = kind_of(ob, t)
        type_ok = _type_group(t) in shown
        if not (shape or roots_b or obj_kids):
            # = node() of a row without children: no arrow, never open
            if not type_ok or (match is not None and not match(name)):
                return []
            row = Row('OBJECT', name, "", 0 if flat else depth, False, False, name, icon, ('O', ob.session_uid), False)
            return [keep(row, row)]

        def children(d):
            rows = []
            if shape:
                label = ob.data.name
                if match is None or match(label):
                    row = Row('SHAPE', name, label, 0 if flat else d, False, False, label, icon, None)
                    rows.append(keep(row, row))
            for r in roots_b:
                rows += visit_bone(ob, b, r, d)
            for o in obj_kids:
                rows += visit(o, d)
            return rows
        return node('OBJECT', name, "", depth, ('O', ob.session_uid), name, icon, children, type_ok)

    rows = []
    real = startup_cameras.names(scene)
    if 'CAMERA' in shown:
        for name in CAMERAS:
            if name not in real and (match is None or match(name)):
                row = Row('CAMERA', name, "", 0, False, False, name, 'CAMERA_ROW', None)
                rows.append(keep(row, row))
    for ob in roots:
        rows += visit(ob, 0)
    return rows


def tail_rows(scene, opts):
    """defaultLightSet / defaultObjectSet and the kit sets (members under an expanded set)."""
    from ..operators import sets
    match = _matcher(opts)
    rows = [Row('DEFAULT_SET', n, "", 0, False, False, n, 'SET', None) for n in DEFAULT_SETS
            if match is None or match(n)]
    for coll in sets.all_sets():
        mem = sets.members(coll, scene)
        opened = bool(mem) and (coll.allset_expanded or match is not None)
        below = [Row('MEMBER', ob.name, coll.name, 1, False, False, ob.name, icon_kind(ob), None) for ob in mem
                 if match is None or match(ob.name)] if opened else []
        if match is not None and not match(coll.name) and not below:
            continue
        rows.append(Row('SET', coll.name, "", 0, bool(mem), opened, coll.name, 'SET', ('S', coll.name)))
        rows += below
    return rows


def _bump_expand():
    _state["expand"] += 1


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


def _drop_old_heads(version):
    """Forget the heads of an older structure or expanded state. Both numbers only go up, so no Outliner asks for
    those rows again; kept, a big scene's old heads would pile up (thousands of rows each) for Python's garbage
    collector to walk on every full pass."""
    for k in [k for k in _cache if k[:2] != version]:
        del _cache[k]


def subtree_keys(context, space, row):
    """Expanded-state keys of ``row`` and everything below it (Shift+click on an arrow)."""
    rows = build(context.scene, context.view_layer, options(space)._replace(search="", children=True),
                 expand_all=True)
    out = []
    start = next((i for i, r in enumerate(rows) if r.kind == row.kind and r.ob == row.ob and r.sub == row.sub), None)
    if start is None:
        return [row.key] if row.key else []
    for r in rows[start:]:
        if r is not rows[start] and r.depth <= row.depth:
            break
        if r.kids and r.key is not None:
            out.append(r.key)
    return out


def set_expanded(keys, state):
    for key in keys:
        if key is None:
            continue
        if key[0] == 'S':
            from ..operators import sets
            coll = sets.get(key[1])
            if coll is not None:
                coll.allset_expanded = state
            continue
        if state:
            EXPANDED.add(key)
        else:
            EXPANDED.discard(key)
    _bump_expand()


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


def visible_signature(context):
    """The visible selection as text (``visibility._signature``) from the context's selection."""
    return "\n".join(sorted(o.name for o in context.selected_objects if o.visible_get()))


def _kept(ob, signature):
    """A hidden object that still counts as selected (Maya: hidden by h while selected, or picked hidden in the
    Outliner; ``visibility.KEPT``)."""
    from ..operators import visibility
    return ob.hide_viewport and visibility.KEPT in ob and visibility._kept(ob, signature)


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


def default_set_members(name, scene):
    """defaultLightSet = every light in the scene; defaultObjectSet is empty in a new scene."""
    if name == "defaultLightSet":
        return [ob for ob in scene.objects if ob.type == 'LIGHT']
    return []


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


# --- geometry ------------------------------------------------------------------------------------------------------

def unit(prefs=None):
    """Blender's Outliner row height UI_UNIT_Y in pixels."""
    system = (prefs or bpy.context.preferences).system
    return int(int(18.0 * system.ui_scale + 0.5) + 2 * system.pixel_size)


def _font_size(prefs):
    styles = prefs.ui_styles
    points = getattr(styles[0].widget, "points", 11.0) if len(styles) else 11.0
    return points * prefs.system.ui_scale


def page_rows(region, u):
    return max(1, region.height // u)


def first_row(area, region, n, u):
    """First shown row of ``area`` (scroll), clamped so the last page is full."""
    top = max(0, n - page_rows(region, u))
    first = min(max(0, SCROLL.get(area.as_pointer(), 0)), top)
    SCROLL[area.as_pointer()] = first
    return first


def row_index_at(area, region, y, u, n):
    """Row under region y, or None (below the last row)."""
    if y < 0 or y >= region.height:
        return None
    k = first_row(area, region, n, u) + int((region.height - 1 - y) // u)
    return k if 0 <= k < n else None


def row_rect(area, region, k, u, n):
    """(y0, y1) region pixels of row ``k`` (it may lie outside the region)."""
    j = k - first_row(area, region, n, u)
    y1 = region.height - j * u
    return y1 - u, y1


SCROLLBAR = 0.35      # x UI unit: the scrollbar width at the right edge


def scrollbar(region, u, n, first):
    """(x0, x1, thumb y0, thumb y1) of the scrollbar, or None when every row fits."""
    page = page_rows(region, u)
    if n <= page:
        return None
    h = region.height
    thumb = max(u, h * page / n)
    y1 = h - (h - thumb) * first / max(1, n - page)
    x1 = region.width - 2
    return x1 - max(4, round(SCROLLBAR * u)), x1, y1 - thumb, y1


# --- drawing -------------------------------------------------------------------------------------------------------

def _quad(pos, col, x0, y0, x1, y1, rgba):
    pos.extend(((x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)))
    col.extend((rgba,) * 6)


_ICON_PARTS = {}          # (kind, cx, cy, r, rgba) -> the icon's (tris, tcol, lines, lcol) made by ``_icon_parts``


def _icon(tris, tcol, lines, lcol, kind, cx, cy, r, rgba):
    """Add a node icon's shapes; an icon drawn at the same place and colour before reuses the points made then."""
    key = (kind, cx, cy, r, rgba)
    got = _ICON_PARTS.get(key)
    if got is None:
        made = ([], [], [], [])
        _icon_parts(*made, kind, cx, cy, r, rgba)
        if len(_ICON_PARTS) > 1024:
            _ICON_PARTS.clear()
        got = _ICON_PARTS[key] = tuple(tuple(m) for m in made)
    tris.extend(got[0])
    tcol.extend(got[1])
    lines.extend(got[2])
    lcol.extend(got[3])


def _icon_parts(tris, tcol, lines, lcol, kind, cx, cy, r, rgba):
    from .hypergraph_layout import icon_shapes
    for prim in icon_shapes(kind):
        name, a = prim[0], prim[1:]
        if name == "rect":
            _quad(tris, tcol, cx + a[0] * r, cy + a[1] * r, cx + a[2] * r, cy + a[3] * r, rgba)
        elif name == "frame":
            x0, y0, x1, y1 = cx + a[0] * r, cy + a[1] * r, cx + a[2] * r, cy + a[3] * r
            lines.extend(((x0, y0), (x1, y0), (x1, y0), (x1, y1), (x1, y1), (x0, y1), (x0, y1), (x0, y0)))
            lcol.extend((rgba,) * 8)
        elif name == "line":
            lines.extend(((cx + a[0] * r, cy + a[1] * r), (cx + a[2] * r, cy + a[3] * r)))
            lcol.extend((rgba,) * 2)
        elif name in ("ring", "disc"):
            ox, oy, rr = cx + a[0] * r, cy + a[1] * r, a[2] * r
            pts = [(ox + rr * math.cos(2 * math.pi * i / 12), oy + rr * math.sin(2 * math.pi * i / 12))
                   for i in range(12)]
            for i in range(12):
                p, q = pts[i], pts[(i + 1) % 12]
                if name == "ring":
                    lines.extend((p, q))
                    lcol.extend((rgba,) * 2)
                else:
                    tris.extend(((ox, oy), p, q))
                    tcol.extend((rgba,) * 3)
        elif name == "tri":
            tris.extend(((cx + a[0] * r, cy + a[1] * r), (cx + a[2] * r, cy + a[3] * r),
                         (cx + a[4] * r, cy + a[5] * r)))
            tcol.extend((rgba,) * 3)


def _triangle(tris, tcol, cx, cy, r, down, rgba):
    if down:
        pts = ((cx - r, cy + r * 0.5), (cx + r, cy + r * 0.5), (cx, cy - r * 0.7))
    else:
        pts = ((cx - r * 0.5, cy + r), (cx - r * 0.5, cy - r), (cx + r * 0.7, cy))
    tris.extend(pts)
    tcol.extend((rgba,) * 3)


ICON_RGB = (0.741, 0.741, 0.741)      # kit icon grey
JOINT_RGB = (0.282, 0.667, 0.710)     # kit icon teal
CHILD_SELECTED = 0.33                 # share of the selection highlight on a row with a selected node below it


def _eye(tris, tcol, lines, lcol, cx, cy, u, shown, rgba):
    """An eye (open: outline + pupil; closed: the lower lid only)."""
    rx, ry = 0.36 * u, 0.2 * u
    n = 12
    upper = [(cx - rx + 2 * rx * i / n, cy + ry * math.sin(math.pi * i / n)) for i in range(n + 1)]
    lower = [(cx - rx + 2 * rx * i / n, cy - ry * math.sin(math.pi * i / n)) for i in range(n + 1)]
    for pts in ((upper, lower) if shown else (lower,)):
        for i in range(n):
            lines.extend((pts[i], pts[i + 1]))
            lcol.extend((rgba,) * 2)
    if shown:
        r = 0.1 * u
        pts = [(cx + r * math.cos(2 * math.pi * i / 10), cy + r * math.sin(2 * math.pi * i / 10)) for i in range(10)]
        for i in range(10):
            tris.extend(((cx, cy), pts[i], pts[(i + 1) % 10]))
            tcol.extend((rgba,) * 3)


def eye_x(region, u, n, first):
    """Centre x of the visibility column (Display > Visibility Column), left of the scrollbar."""
    bar = scrollbar(region, u, n, first)
    right = bar[0] if bar is not None else region.width
    return right - 0.9 * u


def eye_state(row, names=None):
    """True / False = shown / hidden for an object or joint row, None for rows without an eye."""
    from .outliner_tree_edit import eye_state as state
    return state(row, names)


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


def _draw(context, space, region, area):
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader
    from . import kit_icons
    from ..operators import live
    STATS["draws"] += 1
    prefs = context.preferences
    u = unit(prefs)
    rows = rows_for(context, space)
    n = len(rows)
    first = first_row(area, region, n, u)
    last = min(n, first + region.height // u + 1)
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
    by_name = object_names()
    eyes = space.show_restrict_column_hide
    ex = eye_x(region, u, n, first) if eyes else 0.0
    tris, tcol, lines, lcol, textures, names = [], [], [], [], [], []
    seen, drawn = [], []
    r_icon = 0.36 * u
    for k in range(first, last):
        row = rows[k]
        j = k - first
        y1 = region.height - j * u
        y0 = y1 - u
        cy = (y0 + y1) / 2.0
        sel, act, hidden, is_live = row_state(context, row, live_objects, selected_set, signature, by_name)
        if sel:
            _quad(tris, tcol, 0, y0, region.width, y1, act_rgba if act else sel_rgba)
        elif row.key is not None and row.key in above:
            _quad(tris, tcol, 0, y0, region.width, y1, child_rgba)
        if HOVER.get(area.as_pointer()) == k:
            _quad(tris, tcol, 0, y0, region.width, y1, (*text_hi, 0.05))
        if eyes:
            shown = eye_state(row, by_name)
            if shown is not None:
                _eye(tris, tcol, lines, lcol, ex, cy, u, shown, (*text, 0.9 if shown else 0.45))
        x = row.depth * u
        alpha = 0.5 if hidden and not sel else 1.0
        if row.kids:
            _triangle(tris, tcol, x + 0.6 * u, cy, u * 0.17, row.open, (*text, 0.8))
        ix = x + 1.5 * u
        if row.icon in ('SET', 'CAMERA_ROW'):
            textures.append(("outliner:SET" if row.icon == 'SET' else "outliner:CAMERA", ix, cy, hidden and not sel))
        else:
            rgb = JOINT_RGB if row.icon == 'JOINT' else ICON_RGB
            _icon(tris, tcol, lines, lcol, row.icon, ix, cy, r_icon * (0.8 if row.kind == 'SHAPE' else 1.0),
                  (*rgb, alpha))
        if is_live:
            rgb = live.COLOR
        elif act and row.kind in ('OBJECT', 'JOINT'):
            rgb = act_text
        elif sel and row.kind in ('OBJECT', 'JOINT'):
            rgb = sel_text
        else:
            rgb = text_hi if sel else text
        names.append((x + 2.25 * u, cy, row.label, (*rgb, alpha)))
        seen.append((row.kind, row.label, j, row.depth))
        drawn.append((y0, y1, row))
    bar = scrollbar(region, u, n, first)
    if bar is not None:
        x0, x1, b0, b1 = bar
        _quad(tris, tcol, x0, b0, x1, b1, (*text, 0.35))
    gpu.state.blend_set('ALPHA')
    if tris:
        sh = gpu.shader.from_builtin('SMOOTH_COLOR')
        batch_for_shader(sh, 'TRIS', {"pos": tris, "color": tcol}).draw(sh)
    if lines:
        sh = gpu.shader.from_builtin('SMOOTH_COLOR')
        batch_for_shader(sh, 'LINES', {"pos": lines, "color": lcol}).draw(sh)
    for name, cx, cy, greyed in textures:
        size = kit_icons.size_for(name, prefs.system.ui_scale)
        kit_icons.draw_texture(name, math.floor(cx - size / 2), math.floor(cy - size / 2), size, greyed)
    blf.size(0, _font_size(prefs))
    dy = 0.32 * blf.dimensions(0, "Xg")[1] + 1
    for x, cy, label, rgba in names:
        blf.color(0, *rgba)
        blf.position(0, round(x), round(cy - dy), 0)
        blf.draw(0, label)
    gpu.state.blend_set('NONE')
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


# --- selection -----------------------------------------------------------------------------------------------------

def _select(ob, state=True):
    try:
        ob.select_set(state)
        return True
    except RuntimeError:      # not in the view layer
        return False


def _object_mode(context, clear):
    from ..operators import joint_selection
    if context.mode != 'OBJECT' and context.view_layer.objects.active is not None:
        try:
            joint_selection.leave(context, clear_selection=clear)
        except RuntimeError:
            pass


def _keep_hidden(context, obs, replace):
    """Objects Blender can't select (hidden, or selection-locked like a live surface) stay picked when their row is
    picked: a hidden one gets the visibility module's kept mark for the visible selection left now, so h / Shift+H
    act on it like on Maya's hidden-but-selected nodes, and every one is remembered with that visible selection
    (``picked``: Delete, the live list). ``replace`` drops every other pick first."""
    from ..operators import visibility
    if replace:
        visibility._clear(list(context.view_layer.objects), visibility.KEPT)
    signature = visible_signature(context)
    names = set() if replace or _state.get("picks", ("", set()))[0] != signature else set(_state["picks"][1])
    for ob in obs:
        if ob.hide_viewport:
            ob[visibility.KEPT] = signature
        names.add(ob.name)
    _state["picks"] = (signature, names)


def _drop_kept(obs):
    from ..operators import visibility
    visibility._clear(obs, visibility.KEPT)
    sig, names = _state.get("picks", ("", set()))
    _state["picks"] = (sig, names - {ob.name for ob in obs})


def unselectable(ob):
    """Blender can't select this object (hidden or selection-locked): its row is picked through ``_keep_hidden``."""
    try:
        return not ob.visible_get() or ob.hide_select
    except RuntimeError:
        return True


def is_picked(ob, signature):
    """An unselectable object picked in the Outliner while the visible selection is still ``signature``."""
    if _kept(ob, signature):
        return True
    sig, names = _state.get("picks", ("", set()))
    return sig == signature and ob.name in names


def picked_unselectable(context):
    """The unselectable objects picked in a kit Outliner tree (Blender's Outliner keeps such rows highlighted; the
    kit's tree keeps them here while the visible selection stays the same)."""
    signature = visible_signature(context)
    sig, names = _state.get("picks", ("", set()))
    if sig != signature:
        return []
    return [ob for ob in (bpy.data.objects.get(n) for n in sorted(names)) if ob is not None]


def deselect_all(context):
    """Maya: a click on empty Outliner space selects nothing."""
    _object_mode(context, True)
    for ob in context.selected_objects:
        _select(ob, False)
    _keep_hidden(context, (), True)
    _state["camera"] = ""


def active_row(context, rows):
    """Index of the row of the active object / joint (the range anchor), or None."""
    ob = context.view_layer.objects.active
    if ob is None:
        return None
    bone = None
    if ob.type == 'ARMATURE' and ob.mode == 'POSE' and ob.data.bones.active is not None:
        bone = ob.data.bones.active.name
    elif ob.type == 'ARMATURE' and ob.mode == 'EDIT' and ob.data.edit_bones.active is not None:
        bone = ob.data.edit_bones.active.name
    for i, r in enumerate(rows):
        if r.ob != ob.name:
            continue
        if bone is not None and r.kind == 'JOINT' and r.sub == bone:
            return i
        if bone is None and (r.kind == 'OBJECT' or (r.kind == 'JOINT' and r.top)):   # a kit skeleton = its root row
            return i
    return None


def _pick_joint(context, ob, name, add):
    """Pick joint ``name`` the way a viewport click does (Pose Mode, or Edit Mode with the Move tool on an unskinned
    skeleton); ``add`` keeps the joints already picked."""
    from ..operators import joint_selection
    try:
        joint_selection.select(context, ob, name, shift=add, ctrl=add)
        return True
    except (RuntimeError, KeyError):
        return False


def select_row(context, rows, index, mode, anchor=None):
    """Maya Outliner selection of row ``index``: 'REPLACE' (click), 'TOGGLE' (Ctrl), 'RANGE' (Shift, from
    ``anchor``), 'RANGE_ADD' (Ctrl+Shift). The pick order (``operators/pick_order``: Maya's selection list, the
    last pick leads) is brought up to date before and after, like after one of Blender's own Outliner clicks."""
    from ..operators import pick_order
    pick_order.ordered(context)
    try:
        _select_row(context, rows, index, mode, anchor)
    finally:
        pick_order.ordered(context)


def _select_row(context, rows, index, mode, anchor=None):
    from ..operators import sets
    row = rows[index]
    vl = context.view_layer
    kind = row.kind
    if kind == 'CAMERA':
        _object_mode(context, mode == 'REPLACE')
        if mode == 'REPLACE':
            for o in context.selected_objects:
                _select(o, False)
        _state["camera"] = row.ob
        return
    _state["camera"] = ""
    if kind == 'DEFAULT_SET':
        _object_mode(context, mode == 'REPLACE')
        mem = [o for o in default_set_members(row.ob, context.scene) if sets._selectable(o)]
        if mode == 'REPLACE':
            for o in context.selected_objects:
                _select(o, False)
        for o in mem:
            _select(o, not o.select_get() if mode == 'TOGGLE' else True)
        if mem and mem[-1].select_get():
            vl.objects.active = mem[-1]
        return
    if kind == 'SET':
        coll = sets.get(row.ob)
        if coll is not None:
            sets.select_members(context, coll, {'TOGGLE': 'TOGGLE', 'RANGE': 'ADD', 'RANGE_ADD': 'ADD'}.get(
                mode, 'REPLACE'))
        return
    ranged = mode in ('RANGE', 'RANGE_ADD') and anchor is not None and 0 <= anchor < len(rows)
    span = rows[min(anchor, index):max(anchor, index) + 1] if ranged else ()
    # a range over joints of one skeleton picks those joints; a range that also holds other rows picks objects (a
    # joint row then stands for its skeleton: Blender can't pick joints and objects together)
    joints_only = ranged and all(r.kind == 'JOINT' and r.ob == row.ob for r in span)
    if kind == 'JOINT' and (not ranged or joints_only):
        ob = bpy.data.objects.get(row.ob)
        if ob is None or ob.type != 'ARMATURE':
            return
        if mode == 'TOGGLE':
            from ..operators import joint_selection
            try:
                joint_selection.select(context, ob, row.sub, shift=True, ctrl=False)
            except (RuntimeError, KeyError):
                pass
            return
        if ranged:
            names = [r.sub for r in span if r.sub != row.sub]
            add = mode == 'RANGE_ADD'
            for name in names:
                add = _pick_joint(context, ob, name, add) or add
            _pick_joint(context, ob, row.sub, add)
            return
        _pick_joint(context, ob, row.sub, mode == 'RANGE_ADD')
        return
    # OBJECT / SHAPE / MEMBER rows pick their object
    ob = bpy.data.objects.get(row.ob)
    if ob is None:
        return
    _object_mode(context, mode in ('REPLACE', 'RANGE'))
    hidden = unselectable(ob)
    if mode == 'TOGGLE':
        if hidden:          # a hidden / locked row: picked / unpicked through the kept mark
            if is_picked(ob, visible_signature(context)):
                _drop_kept([ob])
            else:
                _keep_hidden(context, [ob], False)
                vl.objects.active = ob
            return
        kept = picked_unselectable(context)
        if _select(ob, not ob.select_get()) and ob.select_get():
            vl.objects.active = ob
        _keep_hidden(context, kept, False)          # the visible selection changed: hidden picks stay picked
        return
    if ranged:
        if mode == 'RANGE':
            for o in context.selected_objects:
                _select(o, False)
        else:
            kept = picked_unselectable(context)
        picked_hidden = []
        for r in span:
            if r.kind in ('OBJECT', 'SHAPE', 'MEMBER', 'JOINT'):
                o = bpy.data.objects.get(r.ob)
                if o is None:
                    continue
                if unselectable(o):
                    picked_hidden.append(o)
                else:
                    _select(o)
        _keep_hidden(context, picked_hidden + (kept if mode == 'RANGE_ADD' else []), mode == 'RANGE')
        if ob.select_get() or hidden:
            vl.objects.active = ob
        return
    if mode != 'RANGE_ADD':
        for o in context.selected_objects:
            if o != ob:
                _select(o, False)
    if hidden:
        _keep_hidden(context, [ob], mode != 'RANGE_ADD')
        vl.objects.active = ob
        return
    if mode != 'RANGE_ADD':
        _keep_hidden(context, (), True)
    if _select(ob):
        vl.objects.active = ob


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
        first = first_row(area, region, n, u)
        bar = scrollbar(region, u, n, first)
        self.scrolling = False
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
        x0 = row.depth * u
        on_eye = space.show_restrict_column_hide and abs(x - eye_x(region, u, n, first)) <= 0.55 * u
        if on_eye and eye_state(row) is not None:
            from .outliner_tree_edit import toggle_eye
            _click.update(key=None, time=0.0)
            done = toggle_eye(context, row)
            redraw_outliners(context)
            return {'FINISHED'} if done else {'CANCELLED'}
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
        if y >= region.height and SCROLL.get(area.as_pointer(), 0) > 0:      # past the top / bottom: scroll
            SCROLL[area.as_pointer()] -= 1
        elif y < 0:
            SCROLL[area.as_pointer()] = SCROLL.get(area.as_pointer(), 0) + 1
        first = first_row(area, region, n, u)
        yy = min(max(y, 0), region.height - 1)
        k = row_index_at(area, region, yy, u, n)
        if k is None:
            k = n - 1 if yy < region.height / 2 else first
        if k == self.last or n == 0:
            return
        self.last = k
        mode = 'RANGE_ADD' if self.mode in ('TOGGLE', 'RANGE_ADD') else 'RANGE'
        select_row(context, rows, k, mode, anchor=self.pressed)
        redraw_outliners(context)

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
            span = max(1.0, region.height - thumb)
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


classes = (ALLSET_OT_outliner_tree_click, ALLSET_OT_outliner_tree_hover, ALLSET_OT_outliner_tree_scroll)


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
    HOVER.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
