# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Hypergraph: Hierarchy (Windows > General Editors > Hypergraph: Hierarchy, Panels > Hypergraph Panel).

A floating kit window (``marked_window`` kind HYPERGRAPH: a Properties editor on the Tool tab marked by a hidden
tab-flag pair) whose region is drawn by the kit: every object of the scene is a node box, children in the row below
their parent, lines from parent to child. A node is filled with its display layer's colour (the layer collection's
colour tag), else the default node grey; selected nodes are white, the lead (Blender's active object) green; an
icon tells groups (empty transforms) from meshes, joints, cameras, lights, curves and locators.

Joints are nodes of their own, like Maya's: each joint stands under its parent joint (joint1 > joint2 > joint3), an
object parented to a joint stands under that joint, and a skeleton the kit made (``skeleton<N>``) has no node of its
own: its root joints take its place, as in the kit Outliner. A skeleton the user named (or a Rigify rig) is a node
with its root joints under it. Clicking or boxing joints picks those joints (Pose Mode); a selection that mixes joints
and other nodes picks the joints' skeletons as objects.

Mouse and keys (items first in "View2D Buttons List", the region's earliest keymap; they poll False outside a
Hypergraph region):
  LMB on a node = select (Shift toggle, Ctrl remove, Ctrl+Shift add), LMB drag on empty space = marquee,
  click on empty space = select nothing; double-click a node = collapse / expand its children;
  MMB drag a node onto another = parent it there (the selection when the dragged node is selected), onto empty
  space = unparent to the world (world position kept, like Edit > Parent / Unparent);
  Alt+MMB (or MMB on empty space) = track, Alt+RMB = dolly, wheel = zoom at the pointer, F / A = frame the
  selection / everything, RMB = the Hypergraph menu. The strip at the top holds the same commands.

The view (pan / zoom) lives per area in ``VIEWS`` and the collapsed nodes per session in ``COLLAPSED`` (object
``session_uid``): nothing is written into the scene, so the window adds no data to the file and no undo steps of
its own besides selection and parenting.
"""

import math

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty

from . import hypergraph_layout as hl
from . import marked_window
from .. import i18n

KIND = "HYPERGRAPH"
VIEWS = {}            # area pointer -> hypergraph_layout.View
COLLAPSED = set()     # object session_uid
OVERLAY = {"area": 0, "box": None, "drag": None}   # marquee (a, b) / drag (from key, point) in region px
STRIP_PX = 24         # tool strip height (unscaled px)

BACKGROUND = (0.227, 0.227, 0.227, 1.0)
STRIP_BG = (0.165, 0.165, 0.165, 1.0)
BUTTON_BG = (0.32, 0.32, 0.32, 1.0)
NODE_FILL = (0.42, 0.42, 0.42, 1.0)
SELECTED_FILL = (0.92, 0.92, 0.92, 1.0)
LEAD_FILL = (0.263, 1.0, 0.639, 1.0)     # the kit's lead colour (#43ffa3)
OUTLINE = (0.1, 0.1, 0.1, 1.0)
LINE = (0.62, 0.62, 0.62, 1.0)
MARQUEE = (0.85, 0.85, 0.85, 1.0)


# --- scene graph ---------------------------------------------------------------------------------------------------

def _is_shown(ob):
    from ..operators import startup_cameras
    return ob is not None and not startup_cameras.is_startup(ob)


def is_joint(key):
    """``key`` is a joint node's key: ('B', skeleton object session_uid, joint name)."""
    return isinstance(key, tuple)


def graph(scene):
    """(nodes [(key, parent key)], {key: object}) for the scene's objects and joints in Outliner order (creation
    order; joints in Maya child order). An object's key is its ``session_uid``, a joint's ``('B', uid, name)`` with
    its skeleton object as the value. A kit skeleton's object is in ``by`` (selection) but is not a node."""
    from . import outliner_order
    from .outliner_tree_rows import _Bones, is_kit_skeleton
    obs = [o for o in scene.objects if _is_shown(o)]
    big = 1 << 40

    def order(o):
        v = o.get(outliner_order.ORDER)
        return (v if isinstance(v, int) else big, o.name)
    obs.sort(key=order)
    by = {o.session_uid: o for o in obs}
    skel = {}                   # uid -> (_Bones, kit skeleton: its root joints stand for the object)
    for o in obs:
        if o.type == 'ARMATURE' and o.data is not None:
            b = _Bones(o)
            skel[o.session_uid] = (b, is_kit_skeleton(o, b))

    def stands_for(o):
        got = skel.get(o.session_uid)
        return ('B', o.session_uid, got[0].roots[0]) if got is not None and got[1] else o.session_uid

    nodes = []
    for o in obs:
        uid = o.session_uid
        p = o.parent
        if p is None or p.session_uid not in by:
            pk = None
        elif o.parent_type == 'BONE' and p.session_uid in skel and o.parent_bone in skel[p.session_uid][0].names:
            pk = ('B', p.session_uid, o.parent_bone)
        else:
            pk = stands_for(p)
        got = skel.get(uid)
        if got is None or not got[1]:
            nodes.append((uid, pk))
            pk = uid
        if got is None:
            continue
        b = got[0]
        stack = [(r, pk) for r in reversed(b.roots)]
        while stack:
            name, parent = stack.pop()
            k = ('B', uid, name)
            by[k] = o
            nodes.append((k, parent))
            stack.extend((c, k) for c in reversed(b.kids.get(name, ())))
    return nodes, by


def centres(scene):
    nodes, by = graph(scene)
    return hl.layout(nodes, COLLAPSED & set(by)), nodes, by


def is_hypergraph(area):
    return marked_window.kind_of(area) == KIND


def _scale(context=None):
    return (context or bpy.context).preferences.system.ui_scale or 1.0


def strip_height(scale):
    return round(STRIP_PX * scale)


def view_for(area, region, scene, context=None):
    """The area's view, framed on everything the first time."""
    scale = _scale(context)
    v = VIEWS.get(area.as_pointer())
    if v is None:
        v = VIEWS[area.as_pointer()] = hl.View(scale=scale)
        cents, _n, _b = centres(scene)
        v.frame(hl.bounds(cents), region.width, region.height, strip_height(scale))
    elif v.scale != scale:
        v.scale = scale
    return v


def frame(area, region, scene, selected_only=False, context=None):
    v = view_for(area, region, scene, context)
    cents, _nodes, by = centres(scene)
    if selected_only:
        cents = {k: c for k, c in cents.items() if node_state(context or bpy.context, k, by[k])[0]} or cents
    v.frame(hl.bounds(cents), region.width, region.height, strip_height(_scale(context)))
    area.tag_redraw()


def layer_colour(ob, scene):
    """RGB of the object's display layer colour tag (theme collection colour), None when it has none. A kit skeleton
    (its node stands for its root joint, like the kit Outliner's top row) takes its root joint's layer."""
    from . import layer_editor, layer_joints
    coll = layer_editor.layer_of(ob, scene) or layer_joints.root_layer(ob)
    tag = getattr(coll, "color_tag", 'NONE') if coll is not None else 'NONE'
    if not tag or tag == 'NONE':
        return None
    try:
        return tuple(bpy.context.preferences.themes[0].collection_color[int(tag[-2:]) - 1].color)
    except (ValueError, IndexError, AttributeError):
        return None


def node_kind(ob, key=None):
    if key is not None and is_joint(key):
        return 'JOINT'
    from ..operators import create, distance_tool
    return hl.node_kind(ob.type, bool(ob.get(create.LOCATOR_PROP)), distance_tool.is_dimension(ob))


def joint_layer_colour(ob, name):
    """RGB of joint ``name``'s display layer colour tag, None when it has none."""
    from . import layer_joints
    pb = ob.pose.bones.get(name) if ob.pose is not None else None
    coll = layer_joints.layer_of(pb) if pb is not None else None
    tag = getattr(coll, "color_tag", 'NONE') if coll is not None else 'NONE'
    if not tag or tag == 'NONE':
        return None
    try:
        return tuple(bpy.context.preferences.themes[0].collection_color[int(tag[-2:]) - 1].color)
    except (ValueError, IndexError, AttributeError):
        return None


def _bone_hidden(ob, name):
    from .. import compat
    from . import layer_joints
    if layer_joints.hidden(ob, name):
        return True
    if ob.mode == 'EDIT':
        eb = ob.data.edit_bones.get(name)
        return eb is None or eb.hide
    pb = ob.pose.bones.get(name) if ob.pose is not None else None
    return pb is None or compat.bone_hidden(pb)


def node_state(context, key, ob):
    """(selected, lead, hidden) of node ``key`` (object ``ob``, or the skeleton of a joint node)."""
    vl = context.view_layer
    try:
        ob_sel = ob.select_get()
        ob_hidden = not ob.visible_get()
    except RuntimeError:            # not in the view layer
        ob_sel, ob_hidden = False, True
    if not is_joint(key):
        sel = ob_sel and not (ob.type == 'ARMATURE' and ob.mode in ('POSE', 'EDIT'))
        return sel, sel and vl.objects.active == ob, ob_hidden
    name = key[2]
    hidden = ob_hidden or _bone_hidden(ob, name)
    if ob.mode == 'EDIT':
        eb = ob.data.edit_bones.get(name)
        sel = eb is not None and bool(eb.select_head or eb.select)
        return sel, sel and ob.data.edit_bones.active == eb, hidden
    if ob.mode == 'POSE':
        from .channel_box import bone_selected
        pb = ob.pose.bones.get(name)
        sel = pb is not None and bone_selected(pb)
        act = ob.data.bones.active
        return sel, sel and act is not None and act.name == name, hidden
    # Object Mode: a picked kit skeleton = its root joints (the nodes that stand for it)
    from .outliner_tree_rows import _Bones, is_kit_skeleton
    b = _Bones(ob)
    sel = ob_sel and is_kit_skeleton(ob, b) and name in b.roots
    return sel, sel and vl.objects.active == ob, hidden


def redraw_all(context=None):
    wm = (context or bpy.context).window_manager
    for w in wm.windows:
        for a in w.screen.areas:
            if is_hypergraph(a):
                a.tag_redraw()


# --- selection / parenting -----------------------------------------------------------------------------------------

def _object_mode(context, clear=False):
    """Object Mode for an object pick; ``clear`` also unpicks the joints (a replacing pick)."""
    if context.mode != 'OBJECT' and context.view_layer.objects.active is not None:
        from ..operators import joint_selection
        try:
            joint_selection.leave(context, clear_selection=clear)
        except RuntimeError:
            pass


def _pick_joints(context, ob, names, rule, lead=None):
    """Maya selection ``rule`` on joints ``names`` of skeleton ``ob`` (like clicking them in a view), ``lead`` last."""
    from ..operators import joint_selection
    names = [n for n in names if n != lead] + ([lead] if lead in names else [])
    for i, name in enumerate(names):
        if rule == 'REPLACE':
            shift = ctrl = i > 0
        elif rule == 'TOGGLE':
            shift, ctrl = True, False
        elif rule == 'REMOVE':
            shift, ctrl = False, True
        else:
            shift = ctrl = True
        try:
            joint_selection.select(context, ob, name, shift=shift, ctrl=ctrl)
        except (RuntimeError, KeyError):
            pass
    redraw_all(context)


def select(context, by, keys, rule, lead=None):
    """Apply a Maya selection ``rule`` to the nodes ``keys``; ``lead`` becomes the active object when selected.
    Joint nodes of one skeleton pick those joints; joints picked together with other nodes stand for their
    skeleton object (Blender can't select joints and objects together)."""
    joints = [k for k in keys if is_joint(k)]
    if joints and len(joints) == len(keys) and len({k[1] for k in joints}) == 1:
        _pick_joints(context, by[joints[0]], [k[2] for k in joints], rule,
                     lead[2] if lead is not None and is_joint(lead) else None)
        return
    if joints:
        objs = []
        for k in keys:
            k = k[1] if is_joint(k) else k
            if k not in objs:
                objs.append(k)
        keys = objs
        lead = lead[1] if lead is not None and is_joint(lead) else lead
    _object_mode(context, clear=rule == 'REPLACE')
    by = {k: ob for k, ob in by.items() if not is_joint(k)}
    current = [k for k, ob in by.items() if ob.select_get()]
    new = hl.apply_rule(current, keys, rule)
    for k, ob in by.items():
        want = k in new
        if ob.select_get() != want:
            try:
                ob.select_set(want)
            except RuntimeError:       # not in the view layer (excluded collection)
                pass
    vl = context.view_layer
    if lead is not None and lead in new and by[lead].select_get():
        vl.objects.active = by[lead]
    elif vl.objects.active is not None and not vl.objects.active.select_get():
        picked = [k for k in keys if k in new and by[k].select_get()]
        if picked:
            vl.objects.active = by[picked[-1]]
    redraw_all(context)


def _drop_joints(context, by, source, target):
    """MMB drop where a joint is dragged or is the target: the kit Outliner's drop (joints move under a joint of
    their own skeleton, objects go under a joint keeping where they are)."""
    from collections import namedtuple
    from . import outliner_tree_edit
    target_row = namedtuple("Target", "kind ob sub top")
    moving = [k for k in by if node_state(context, k, by[k])[0]] if node_state(context, source, by[source])[0] else []
    if source not in moving:
        moving.append(source)
    dragged = [('JOINT', by[k].name, k[2]) if is_joint(k) else ('OBJECT', by[k].name, "") for k in moving
               if k != target]
    if target is None:
        row = None
    elif is_joint(target):
        row = target_row('JOINT', by[target].name, target[2], False)
    else:
        row = target_row('OBJECT', by[target].name, "", False)
    return outliner_tree_edit.drop(context, dragged, row, 'ON')


def drop(context, by, source, target):
    """MMB drop of node ``source`` on node ``target`` (None = empty space). Returns (changed count, message)."""
    if is_joint(source) or (target is not None and is_joint(target)):
        return _drop_joints(context, by, source, target)
    from ..operators import parenting
    moving = ([k for k, ob in by.items() if not is_joint(k) and ob.select_get()] if by[source].select_get()
              else [source])
    if source not in moving:
        moving.append(source)
    obs = [by[k] for k in moving]
    _object_mode(context)
    if target is None:
        n = parenting.unparent(obs)
        return n, ""
    if target == source:
        return 0, ""
    parent = by[target]
    done, cycles = parenting.parent_maya([o for o in obs if o is not parent], parent)
    msg = f"Cannot parent {parent.name} under its own child" if cycles else ""
    return len(done), msg


# --- drawing -------------------------------------------------------------------------------------------------------

_handle = [None]


def strip_buttons(region, scale):
    import blf
    blf.size(0, 11.0 * scale)
    pad = 10 * scale
    tools = [(key, i18n.iface(label)) for key, label in hl.TOOLS]
    widths = [blf.dimensions(0, label)[0] + 2 * pad for _k, label in tools]
    sh = strip_height(scale)
    rects = hl.strip_rects(widths, region.height - 3 * scale, sh - 6 * scale, x0=6 * scale, gap=4 * scale)
    return [(key, label, r) for (key, label), r in zip(tools, rects)]


def strip_hit(region, scale, x, y):
    if y < region.height - strip_height(scale):
        return None, False
    for key, _label, (x0, y0, x1, y1) in strip_buttons(region, scale):
        if x0 <= x <= x1 and y0 <= y <= y1:
            return key, True
    return None, True


def _shader():
    import gpu
    return gpu.shader.from_builtin('UNIFORM_COLOR')


def _tris(shader, pts, idx, rgba):
    from gpu_extras.batch import batch_for_shader
    batch = batch_for_shader(shader, 'TRIS', {"pos": pts}, indices=idx)
    shader.uniform_float("color", rgba)
    batch.draw(shader)


def _rect(shader, x0, y0, x1, y1, rgba):
    _tris(shader, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], [(0, 1, 2), (0, 2, 3)], rgba)


def _lines(shader, pts, rgba):
    if not pts:
        return
    from gpu_extras.batch import batch_for_shader
    batch = batch_for_shader(shader, 'LINES', {"pos": pts})
    shader.uniform_float("color", rgba)
    batch.draw(shader)


def _frame(shader, x0, y0, x1, y1, rgba):
    _lines(shader, [(x0, y0), (x1, y0), (x1, y0), (x1, y1), (x1, y1), (x0, y1), (x0, y1), (x0, y0)], rgba)


def _circle(cx, cy, r, n=16):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _icon(shader, kind, cx, cy, r, rgba):
    for prim in hl.icon_shapes(kind):
        name, a = prim[0], prim[1:]
        if name == "rect":
            _rect(shader, cx + a[0] * r, cy + a[1] * r, cx + a[2] * r, cy + a[3] * r, rgba)
        elif name == "frame":
            _frame(shader, cx + a[0] * r, cy + a[1] * r, cx + a[2] * r, cy + a[3] * r, rgba)
        elif name == "line":
            _lines(shader, [(cx + a[0] * r, cy + a[1] * r), (cx + a[2] * r, cy + a[3] * r)], rgba)
        elif name in ("ring", "disc"):
            pts = _circle(cx + a[0] * r, cy + a[1] * r, a[2] * r)
            if name == "ring":
                _lines(shader, [p for i in range(len(pts)) for p in (pts[i], pts[(i + 1) % len(pts)])], rgba)
            else:
                c = (cx + a[0] * r, cy + a[1] * r)
                _tris(shader, [c] + pts, [(0, i + 1, (i + 1) % len(pts) + 1) for i in range(len(pts))], rgba)
        elif name == "tri":
            _tris(shader, [(cx + a[0] * r, cy + a[1] * r), (cx + a[2] * r, cy + a[3] * r),
                           (cx + a[4] * r, cy + a[5] * r)], [(0, 1, 2)], rgba)


def _fit(blf, text, width):
    if blf.dimensions(0, text)[0] <= width:
        return text
    while text and blf.dimensions(0, text + "...")[0] > width:
        text = text[:-1]
    return text + "..." if text else ""


def draw():
    context = bpy.context
    area, region = context.area, context.region
    if region is None or region.type != 'WINDOW' or not is_hypergraph(area):
        return
    import blf
    import gpu
    scene = context.scene
    scale = _scale(context)
    view = view_for(area, region, scene, context)
    cents, nodes, by = centres(scene)
    shader = _shader()
    gpu.state.blend_set('ALPHA')
    _rect(shader, 0, 0, region.width, region.height, BACKGROUND)

    # parent -> child lines
    pts = []
    for key, parent in nodes:
        if key in cents and parent in cents:
            px, py = view.to_region(*cents[parent])
            cx, cy = view.to_region(*cents[key])
            pts += [(px, py - hl.NODE_H * view.s / 2), (cx, cy + hl.NODE_H * view.s / 2)]
    _lines(shader, pts, LINE)

    marked = hl.hidden_children(nodes, COLLAPSED)
    font = 11.0 * view.s
    blf.size(0, max(font, 1.0))
    for key, c in cents.items():
        ob = by[key]
        x0, y0, x1, y1 = view.rect(c)
        if x1 < 0 or x0 > region.width or y1 < 0 or y0 > region.height:
            continue
        joint = is_joint(key)
        layer = joint_layer_colour(ob, key[2]) if joint else layer_colour(ob, scene)
        selected, lead, hidden = node_state(context, key, ob)
        fill = LEAD_FILL if lead else SELECTED_FILL if selected else (
            (*layer, 1.0) if layer is not None else NODE_FILL)
        if hidden and not selected:
            fill = (fill[0] * 0.6, fill[1] * 0.6, fill[2] * 0.6, 1.0)
        _rect(shader, x0, y0, x1, y1, fill)
        if layer is not None and selected:          # the layer colour stays visible as a stripe
            _rect(shader, x0, y0, x0 + max(3.0, 5 * view.s), y1, (*layer, 1.0))
        _frame(shader, x0, y0, x1, y1, OUTLINE)
        ink = hl.text_colour(fill)
        h = y1 - y0
        _icon(shader, node_kind(ob, key), x0 + h / 2 + 2 * view.s, (y0 + y1) / 2, h * 0.3, ink)
        if key in marked:                            # collapsed: a triangle under the box
            cx, r = (x0 + x1) / 2, 5 * view.s
            _tris(shader, [(cx - r, y0 - 2 * view.s), (cx + r, y0 - 2 * view.s), (cx, y0 - 2 * view.s - r)],
                  [(0, 1, 2)], LINE)
        if font >= 4.0:
            tx = x0 + h + 4 * view.s
            text = _fit(blf, key[2] if joint else ob.name, x1 - tx - 4 * view.s)
            blf.color(0, *ink)
            blf.position(0, round(tx), round((y0 + y1) / 2 - font * 0.35), 0)
            blf.draw(0, text)

    ptr = area.as_pointer()
    if OVERLAY["area"] == ptr and OVERLAY["box"] is not None:
        (ax, ay), (bx, by_) = OVERLAY["box"]
        _rect(shader, min(ax, bx), min(ay, by_), max(ax, bx), max(ay, by_), (1.0, 1.0, 1.0, 0.08))
        _frame(shader, ax, ay, bx, by_, MARQUEE)
    if OVERLAY["area"] == ptr and OVERLAY["drag"] is not None:
        key, (mx, my) = OVERLAY["drag"]
        if key in cents:
            sx, sy = view.to_region(*cents[key])
            _lines(shader, [(sx, sy), (mx, my)], LEAD_FILL)

    if not cents:
        blf.size(0, 12.0 * scale)
        blf.color(0, 0.7, 0.7, 0.7, 1.0)
        blf.position(0, 20 * scale, region.height / 2, 0)
        blf.draw(0, i18n.iface("No objects in the scene"))

    # the tool strip
    sh = strip_height(scale)
    _rect(shader, 0, region.height - sh, region.width, region.height, STRIP_BG)
    buttons = strip_buttons(region, scale)
    for _key, label, (x0, y0, x1, y1) in buttons:
        _rect(shader, x0, y0, x1, y1, BUTTON_BG)
        blf.size(0, 11.0 * scale)
        blf.color(0, 0.9, 0.9, 0.9, 1.0)
        blf.position(0, round(x0 + 10 * scale), round((y0 + y1) / 2 - 4 * scale), 0)
        blf.draw(0, label)
    gpu.state.blend_set('NONE')


# --- operators -------------------------------------------------------------------------------------------------------

def _poll(context):
    region = context.region
    return region is not None and region.type == 'WINDOW' and is_hypergraph(context.area)


def run_tool(context, key):
    area, region, scene = context.area, context.region, context.scene
    if key == 'FRAME_ALL':
        frame(area, region, scene, context=context)
    elif key == 'FRAME_SELECTED':
        frame(area, region, scene, selected_only=True, context=context)
    elif key in ('EXPAND_ALL', 'COLLAPSE_ALL'):
        set_all_collapsed(scene, key == 'COLLAPSE_ALL')
        redraw_all(context)


def set_all_collapsed(scene, collapse):
    COLLAPSED.clear()
    if collapse:
        nodes, _by = graph(scene)
        COLLAPSED.update(p for _k, p in nodes if p is not None)


def toggle_collapsed(key):
    if key in COLLAPSED:
        COLLAPSED.discard(key)
    else:
        COLLAPSED.add(key)


def _hit(context, x, y):
    view = view_for(context.area, context.region, context.scene, context)
    cents, _nodes, by = centres(context.scene)
    return view, cents, by, hl.hit(view, cents, x, y)


_LAST_CLICK = {"key": None, "time": 0.0}


def is_double_click(context, key, now=None):
    """True when this press on node ``key`` follows a press on the same node within the double-click time (the
    kit times it itself: a double-click no keymap item takes comes back to the press item as a press)."""
    import time
    now = time.monotonic() if now is None else now
    limit = context.preferences.inputs.mouse_double_click_time / 1000.0
    double = _LAST_CLICK["key"] == key and now - _LAST_CLICK["time"] <= limit
    _LAST_CLICK.update(key=None if double else key, time=0.0 if double else now)
    return double


def _end_overlay(context):
    OVERLAY["box"] = OVERLAY["drag"] = None
    context.area.tag_redraw()


class ALLSET_OT_hypergraph(bpy.types.Operator):
    """Open the Hypergraph: the scene hierarchy as a graph of nodes (Maya Windows > General Editors >
    Hypergraph: Hierarchy)"""
    bl_idname = "allset.hypergraph"
    bl_label = "Hypergraph: Hierarchy"

    def execute(self, context):
        if context.window is None:
            return {'CANCELLED'}
        window = marked_window.open_window(context, KIND)
        if window is None:
            from . import window_places
            if not window_places.deferred():     # opens on a later tick
                self.report({'ERROR'}, "Could not open the Hypergraph window")
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_hg_click(bpy.types.Operator):
    """Hypergraph: click a node to select it (Shift toggle, Ctrl remove, Ctrl+Shift add), drag on empty space to
    select the nodes in the marquee"""
    bl_idname = "allset.hg_click"
    bl_label = "Hypergraph Select"
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        x, y = event.mouse_region_x, event.mouse_region_y
        tool, on_strip = strip_hit(context.region, _scale(context), x, y)
        if on_strip:
            if tool is not None:
                run_tool(context, tool)
            return {'CANCELLED'}       # view only: no undo step (the press is still taken)
        _view, _cents, by, key = _hit(context, x, y)
        self.rule = hl.select_rule(event.shift, event.ctrl)
        if key is not None:
            if is_double_click(context, key):
                nodes, _by = graph(context.scene)
                if any(p == key for _k, p in nodes):
                    toggle_collapsed(key)
                    context.area.tag_redraw()
                    return {'CANCELLED'}   # view only: no undo step
            select(context, by, [key], self.rule, lead=key)
            return {'FINISHED'}
        _LAST_CLICK.update(key=None, time=0.0)
        self.start = (x, y)
        OVERLAY.update(area=context.area.as_pointer(), box=((x, y), (x, y)), drag=None)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        x, y = event.mouse_region_x, event.mouse_region_y
        if event.type == 'MOUSEMOVE':
            OVERLAY["box"] = (self.start, (x, y))
            context.area.tag_redraw()
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            _end_overlay(context)
            view, cents, by, _key = _hit(context, x, y)
            if abs(x - self.start[0]) < 4 and abs(y - self.start[1]) < 4:
                keys = []          # a click on empty space
                if self.rule != 'REPLACE':
                    return {'CANCELLED'}
            else:
                keys = hl.in_box(view, cents, self.start, (x, y))
            select(context, by, keys, self.rule, lead=keys[-1] if keys else None)
            return {'FINISHED'}
        elif event.type in {'ESC', 'RIGHTMOUSE'}:
            _end_overlay(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class ALLSET_OT_hg_mmb(bpy.types.Operator):
    """Hypergraph: middle-mouse drag a node onto another to parent it there, onto empty space to unparent it;
    Alt+middle-mouse drag tracks the view"""
    bl_idname = "allset.hg_mmb"
    bl_label = "Hypergraph Drag"
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        x, y = event.mouse_region_x, event.mouse_region_y
        _view, _cents, _by, key = _hit(context, x, y)
        self.prev = (x, y)
        self.key = None if event.alt else key
        if self.key is not None:
            OVERLAY.update(area=context.area.as_pointer(), drag=(self.key, (x, y)), box=None)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        x, y = event.mouse_region_x, event.mouse_region_y
        if event.type == 'MOUSEMOVE':
            if self.key is None:
                view = view_for(context.area, context.region, context.scene, context)
                view.pan(x - self.prev[0], y - self.prev[1])
            else:
                OVERLAY["drag"] = (self.key, (x, y))
            self.prev = (x, y)
            context.area.tag_redraw()
        elif event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
            if self.key is None:
                return {'CANCELLED'}
            _end_overlay(context)
            _view, _cents, by, target = _hit(context, x, y)
            if self.key not in by:
                return {'CANCELLED'}
            n, msg = drop(context, by, self.key, target)
            if msg:
                self.report({'WARNING'}, msg)
            redraw_all(context)
            return {'FINISHED'} if n else {'CANCELLED'}
        elif event.type in {'ESC', 'RIGHTMOUSE'}:
            _end_overlay(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class ALLSET_OT_hg_rmb(bpy.types.Operator):
    """Hypergraph: Alt+right-mouse drag dollies the view, a right-click opens the Hypergraph menu"""
    bl_idname = "allset.hg_rmb"
    bl_label = "Hypergraph Dolly"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        if not event.alt:
            bpy.ops.wm.call_menu(name=ALLSET_MT_hypergraph.bl_idname)
            return {'FINISHED'}
        self.origin = (event.mouse_region_x, event.mouse_region_y)
        self.prev = self.origin
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        x, y = event.mouse_region_x, event.mouse_region_y
        if event.type == 'MOUSEMOVE':
            d = (x - self.prev[0]) + (y - self.prev[1])
            view = view_for(context.area, context.region, context.scene, context)
            view.zoom_at(math.exp(d * 0.006), *self.origin)
            self.prev = (x, y)
            context.area.tag_redraw()
        elif event.type == 'RIGHTMOUSE' and event.value == 'RELEASE' or event.type == 'ESC':
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


class ALLSET_OT_hg_zoom(bpy.types.Operator):
    """Hypergraph: zoom at the pointer"""
    bl_idname = "allset.hg_zoom"
    bl_label = "Hypergraph Zoom"
    bl_options = {'INTERNAL'}

    direction: EnumProperty(items=(('IN', "In", ""), ('OUT', "Out", "")), options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def invoke(self, context, event):
        view = view_for(context.area, context.region, context.scene, context)
        f = 1.15 if self.direction == 'IN' else 1 / 1.15
        view.zoom_at(f, event.mouse_region_x, event.mouse_region_y)
        context.area.tag_redraw()
        return {'FINISHED'}


class ALLSET_OT_hg_frame(bpy.types.Operator):
    """Hypergraph: frame the selected nodes (F) or every node (A)"""
    bl_idname = "allset.hg_frame"
    bl_label = "Frame"
    bl_options = {'INTERNAL'}

    all: BoolProperty(name="All", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def execute(self, context):
        run_tool(context, 'FRAME_ALL' if self.all else 'FRAME_SELECTED')
        return {'FINISHED'}


class ALLSET_OT_hg_collapse_all(bpy.types.Operator):
    """Hypergraph: collapse or expand every node"""
    bl_idname = "allset.hg_collapse_all"
    bl_label = "Collapse All"
    bl_options = {'INTERNAL'}

    collapse: BoolProperty(name="Collapse", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def execute(self, context):
        run_tool(context, 'COLLAPSE_ALL' if self.collapse else 'EXPAND_ALL')
        return {'FINISHED'}


class ALLSET_MT_hypergraph(bpy.types.Menu):
    bl_idname = "ALLSET_MT_hypergraph"
    bl_label = "Hypergraph"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'EXEC_REGION_WIN'
        layout.operator(ALLSET_OT_hg_frame.bl_idname, text="Frame All").all = True
        layout.operator(ALLSET_OT_hg_frame.bl_idname, text="Frame Selection").all = False
        layout.separator()
        layout.operator(ALLSET_OT_hg_collapse_all.bl_idname, text="Expand All").collapse = False
        layout.operator(ALLSET_OT_hg_collapse_all.bl_idname, text="Collapse All").collapse = True


@persistent
def _on_depsgraph(_scene, _depsgraph=None):
    try:
        redraw_all()
    except (AttributeError, ReferenceError):
        pass


classes = (ALLSET_OT_hypergraph, ALLSET_OT_hg_click, ALLSET_OT_hg_mmb, ALLSET_OT_hg_rmb,
           ALLSET_OT_hg_zoom, ALLSET_OT_hg_frame, ALLSET_OT_hg_collapse_all, ALLSET_MT_hypergraph)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    _handle[0] = bpy.types.SpaceProperties.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    marked_window.AREA_STATE.append(VIEWS)        # the view stays when the window comes to the front


def unregister():
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    if _handle[0] is not None:
        bpy.types.SpaceProperties.draw_handler_remove(_handle[0], 'WINDOW')
        _handle[0] = None
    if VIEWS in marked_window.AREA_STATE:
        marked_window.AREA_STATE.remove(VIEWS)
    VIEWS.clear()
    OVERLAY.update(area=0, box=None, drag=None)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
