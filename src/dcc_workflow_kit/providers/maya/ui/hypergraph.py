# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Hypergraph: Hierarchy (Windows > General Editors > Hypergraph: Hierarchy, Panels > Hypergraph Panel).

A floating kit window (``marked_window`` kind HYPERGRAPH: a Properties editor on the Tool tab marked by a hidden
tab-flag pair) whose region is drawn by the kit: every object of the scene is a node box, children in the row below
their parent, lines from parent to child. A node is filled with its display layer's colour (the layer collection's
colour tag), else the default node grey; selected nodes are white, the lead (Blender's active object) green; an
icon tells groups (empty transforms) from meshes, joints, cameras, lights, curves and locators.

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


def graph(scene):
    """(nodes [(key, parent key)], {key: object}) for the scene's objects in Outliner order (creation order)."""
    from . import outliner_order
    obs = [o for o in scene.objects if _is_shown(o)]
    big = 1 << 40

    def order(o):
        v = o.get(outliner_order.ORDER)
        return (v if isinstance(v, int) else big, o.name)
    obs.sort(key=order)
    by = {o.session_uid: o for o in obs}
    nodes = [(o.session_uid, o.parent.session_uid if o.parent is not None and o.parent.session_uid in by else None)
             for o in obs]
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
        cents = {k: c for k, c in cents.items() if by[k].select_get()} or cents
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


def node_kind(ob):
    from ..operators import create
    return hl.node_kind(ob.type, bool(ob.get(create.LOCATOR_PROP)))


def redraw_all(context=None):
    wm = (context or bpy.context).window_manager
    for w in wm.windows:
        for a in w.screen.areas:
            if is_hypergraph(a):
                a.tag_redraw()


# --- selection / parenting -----------------------------------------------------------------------------------------

def _object_mode(context):
    if context.mode != 'OBJECT' and context.view_layer.objects.active is not None:
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass


def select(context, by, keys, rule, lead=None):
    """Apply a Maya selection ``rule`` to the nodes ``keys``; ``lead`` becomes the active object when selected."""
    _object_mode(context)
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


def drop(context, by, source, target):
    """MMB drop of node ``source`` on node ``target`` (None = empty space). Returns (changed count, message)."""
    from ..operators import parenting
    moving = [k for k, ob in by.items() if ob.select_get()] if by[source].select_get() else [source]
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
    widths = [blf.dimensions(0, label)[0] + 2 * pad for _k, label in hl.TOOLS]
    sh = strip_height(scale)
    rects = hl.strip_rects(widths, region.height - 3 * scale, sh - 6 * scale, x0=6 * scale, gap=4 * scale)
    return [(key, label, r) for (key, label), r in zip(hl.TOOLS, rects)]


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

    active = context.view_layer.objects.active
    marked = hl.hidden_children(nodes, COLLAPSED)
    font = 11.0 * view.s
    blf.size(0, max(font, 1.0))
    for key, c in cents.items():
        ob = by[key]
        x0, y0, x1, y1 = view.rect(c)
        if x1 < 0 or x0 > region.width or y1 < 0 or y0 > region.height:
            continue
        layer = layer_colour(ob, scene)
        selected = ob.select_get()
        fill = LEAD_FILL if selected and ob == active else SELECTED_FILL if selected else (
            (*layer, 1.0) if layer is not None else NODE_FILL)
        if not ob.visible_get() and not selected:
            fill = (fill[0] * 0.6, fill[1] * 0.6, fill[2] * 0.6, 1.0)
        _rect(shader, x0, y0, x1, y1, fill)
        if layer is not None and selected:          # the layer colour stays visible as a stripe
            _rect(shader, x0, y0, x0 + max(3.0, 5 * view.s), y1, (*layer, 1.0))
        _frame(shader, x0, y0, x1, y1, OUTLINE)
        ink = hl.text_colour(fill)
        h = y1 - y0
        _icon(shader, node_kind(ob), x0 + h / 2 + 2 * view.s, (y0 + y1) / 2, h * 0.3, ink)
        if key in marked:                            # collapsed: a triangle under the box
            cx, r = (x0 + x1) / 2, 5 * view.s
            _tris(shader, [(cx - r, y0 - 2 * view.s), (cx + r, y0 - 2 * view.s), (cx, y0 - 2 * view.s - r)],
                  [(0, 1, 2)], LINE)
        if font >= 4.0:
            tx = x0 + h + 4 * view.s
            text = _fit(blf, ob.name, x1 - tx - 4 * view.s)
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
        blf.draw(0, "No objects in the scene")

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


def unregister():
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    if _handle[0] is not None:
        bpy.types.SpaceProperties.draw_handler_remove(_handle[0], 'WINDOW')
        _handle[0] = None
    VIEWS.clear()
    OVERLAY.update(area=0, box=None, drag=None)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
