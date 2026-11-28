# SPDX-License-Identifier: GPL-3.0-or-later
"""Row model of the kit's Maya Outliner tree: ``Row`` / ``Options``, the startup camera and DAG rows of a view layer
for the Outliner's filters (``build``: joints under their parent joint, Display > Shapes / Children / Sort, the
search), the set rows (``tail_rows``), expanded rows (``EXPANDED``, ``set_expanded``, ``subtree_keys``) and the
tree's shared session state (``_state``, the rows cache). Rows per redraw: outliner_tree.rows_for.
"""

import fnmatch
import re
from collections import namedtuple

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
STATS = {"builds": 0, "draws": 0}
_state = {"expand": 0, "camera": ""}
_cache = {}               # (structure, expand, scene, view layer, options) -> head rows


# --- row model -----------------------------------------------------------------------------------------------------

def options(space):
    from .. import compat           # Blender's sort flag differs by version (this module is otherwise bpy-free)
    types = frozenset(t for t, prop in TYPE_PROPS if getattr(space, prop, True))
    return Options(space.use_filter_children, compat.outliner_sort_alpha(space), space.use_filter_object_content,
                   types, space.filter_text, space.use_filter_case_sensitive, space.use_filter_complete)


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
    from ..operators import create, distance_tool
    from .hypergraph_layout import node_kind
    return node_kind(ob.type, bool(ob.get(create.LOCATOR_PROP)), distance_tool.is_dimension(ob))


def _icon_kinds():
    """``icon_kind`` as a function of (object, its type) for one rows build: the imports are done once, and only an
    empty's kind depends on its properties (locator, distance dimension: ``node_kind``), so only empties read them."""
    from ..operators import create, distance_tool
    from .hypergraph_layout import node_kind
    prop = create.LOCATOR_PROP
    is_dimension = distance_tool.is_dimension
    kinds = {}

    def kind(ob, t):
        if t == 'EMPTY':
            return node_kind(t, bool(ob.get(prop)), is_dimension(ob))
        got = kinds.get(t)
        if got is None:
            got = kinds[t] = node_kind(t)
        return got
    return kind


class _Bones:
    """An armature's joints: the bone list (edit bones in Edit Mode), roots and children by name, in Maya child
    order (``joint_common.child_order_key``: creation order, a re-parented joint last)."""

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
        parts = sets.part_objects(coll, scene)
        opened = bool(mem or parts) and (coll.allset_expanded or match is not None)
        below = [Row('MEMBER', ob.name, coll.name, 1, False, False, ob.name, icon_kind(ob), None) for ob in mem
                 if match is None or match(ob.name)] if opened else []
        # component members: one row per Maya name (pCube1.vtx[0:3]); the row's object is the mesh
        below += [Row('MEMBER', ob.name, coll.name, 1, False, False, label, icon_kind(ob), None) for ob in parts
                  for label in sets.component_names(coll, ob) if match is None or match(label)] if opened else []
        if match is not None and not match(coll.name) and not below:
            continue
        rows.append(Row('SET', coll.name, "", 0, bool(mem or parts), opened, coll.name, 'SET', ('S', coll.name)))
        rows += below
    return rows


def _bump_expand():
    _state["expand"] += 1


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


def default_set_members(name, scene):
    """defaultLightSet = every light in the scene; defaultObjectSet is empty in a new scene."""
    if name == "defaultLightSet":
        return [ob for ob in scene.objects if ob.type == 'LIGHT']
    return []
