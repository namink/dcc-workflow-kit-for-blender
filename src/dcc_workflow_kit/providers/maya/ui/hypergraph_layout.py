# SPDX-License-Identifier: GPL-3.0-or-later
"""Hypergraph: Hierarchy maths without bpy (tree layout, view transform, hit tests, selection rules, node icons).

Graph space: x to the right, y downwards, one unit = one pixel at zoom 1 and UI scale 1. Region space: Blender's
region pixels (y upwards). Like Maya's Hypergraph hierarchy view, the roots stand side by side, every node's
children sit in the row below it and a parent is centred over its children; a collapsed node hides its subtree.
"""

NODE_W = 128.0       # node box size and spacing (graph units)
NODE_H = 26.0
GAP_X = 18.0
GAP_Y = 40.0
MARGIN = 40.0        # empty border kept around the graph when framing
ZOOM_MIN, ZOOM_MAX = 0.08, 4.0
FRAME_ZOOM_MAX = 1.0


# --- layout ------------------------------------------------------------------------------------------------------

def children_of(nodes):
    """{key: [child keys in list order]} and the root keys (in list order). ``nodes`` = [(key, parent key or None)];
    a parent that is not in the list makes the node a root."""
    keys = {k for k, _p in nodes}
    kids = {k: [] for k, _p in nodes}
    roots = []
    for k, p in nodes:
        if p is not None and p in keys and p != k:
            kids[p].append(k)
        else:
            roots.append(k)
    return kids, roots


def layout(nodes, collapsed=()):
    """{key: (cx, cy)} node centres in graph space for the shown nodes. ``collapsed`` keys keep their own box but
    hide every descendant."""
    kids, roots = children_of(nodes)
    collapsed = set(collapsed)
    pitch_x, pitch_y = NODE_W + GAP_X, NODE_H + GAP_Y
    out = {}
    slot = [0]
    seen = set()

    def place(key, depth):
        seen.add(key)
        shown = [] if key in collapsed else [c for c in kids[key] if c not in seen]
        if not shown:
            x = slot[0] * pitch_x
            slot[0] += 1
        else:
            xs = [place(c, depth + 1) for c in shown]
            x = (xs[0] + xs[-1]) / 2.0
        out[key] = (x, depth * pitch_y)
        return x

    for r in roots:
        if r not in seen:
            place(r, 0)
    return out


def hidden_children(nodes, collapsed):
    """Keys of collapsed nodes that do have children (they get the collapsed mark)."""
    kids, _roots = children_of(nodes)
    return {k for k in collapsed if kids.get(k)}


def bounds(centres):
    """(x0, y0, x1, y1) of all node boxes in graph space, None when empty."""
    if not centres:
        return None
    xs = [c[0] for c in centres.values()]
    ys = [c[1] for c in centres.values()]
    return (min(xs) - NODE_W / 2, min(ys) - NODE_H / 2, max(xs) + NODE_W / 2, max(ys) + NODE_H / 2)


# --- view ----------------------------------------------------------------------------------------------------------

class View:
    """Graph -> region transform: rx = ox + gx * s, ry = oy - gy * s with s = zoom * ui_scale."""

    def __init__(self, zoom=1.0, ox=0.0, oy=0.0, scale=1.0):
        self.zoom, self.ox, self.oy, self.scale = zoom, ox, oy, scale

    @property
    def s(self):
        return self.zoom * self.scale

    def to_region(self, gx, gy):
        return self.ox + gx * self.s, self.oy - gy * self.s

    def to_graph(self, rx, ry):
        return (rx - self.ox) / self.s, (self.oy - ry) / self.s

    def rect(self, centre):
        """Region rect (x0, y0, x1, y1) of the node box centred at graph point ``centre``."""
        x, y = self.to_region(*centre)
        hw, hh = NODE_W * self.s / 2, NODE_H * self.s / 2
        return x - hw, y - hh, x + hw, y + hh

    def zoom_at(self, factor, rx, ry):
        """Zoom by ``factor`` keeping the graph point under region (rx, ry) in place."""
        z = min(ZOOM_MAX, max(ZOOM_MIN, self.zoom * factor))
        f = z / self.zoom
        self.ox = rx - (rx - self.ox) * f
        self.oy = ry - (ry - self.oy) * f
        self.zoom = z

    def pan(self, dx, dy):
        self.ox += dx
        self.oy += dy

    def frame(self, box, width, height, top=0.0):
        """Fit graph ``box`` (x0, y0, x1, y1) into a region of ``width`` x ``height`` px whose top ``top`` px are
        taken (the tool strip)."""
        if box is None:
            return
        avail_w = max(width - 2 * MARGIN * self.scale, 1.0)
        avail_h = max(height - top - 2 * MARGIN * self.scale, 1.0)
        gw, gh = max(box[2] - box[0], 1.0), max(box[3] - box[1], 1.0)
        z = min(avail_w / (gw * self.scale), avail_h / (gh * self.scale), FRAME_ZOOM_MAX)
        self.zoom = min(ZOOM_MAX, max(ZOOM_MIN, z))
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        self.ox = width / 2 - cx * self.s
        self.oy = (height - top) / 2 + cy * self.s


def hit(view, centres, rx, ry):
    """The key of the node box under region point (rx, ry), else None (the last drawn wins)."""
    found = None
    for key, c in centres.items():
        x0, y0, x1, y1 = view.rect(c)
        if x0 <= rx <= x1 and y0 <= ry <= y1:
            found = key
    return found


def in_box(view, centres, a, b):
    """Keys whose node box touches the region rectangle spanned by points ``a`` and ``b``."""
    bx0, bx1 = sorted((a[0], b[0]))
    by0, by1 = sorted((a[1], b[1]))
    out = []
    for key, c in centres.items():
        x0, y0, x1, y1 = view.rect(c)
        if x1 >= bx0 and x0 <= bx1 and y1 >= by0 and y0 <= by1:
            out.append(key)
    return out


# --- selection -------------------------------------------------------------------------------------------------------

def select_rule(shift, ctrl):
    """Maya's click / marquee modifiers: plain = replace, Shift = toggle, Ctrl = remove, Ctrl+Shift = add."""
    if shift and ctrl:
        return 'ADD'
    if shift:
        return 'TOGGLE'
    if ctrl:
        return 'REMOVE'
    return 'REPLACE'


def apply_rule(current, picked, rule):
    current, picked = set(current), set(picked)
    if rule == 'REPLACE':
        return picked
    if rule == 'TOGGLE':
        return current ^ picked
    if rule == 'REMOVE':
        return current - picked
    return current | picked


def would_cycle(parents, child, target):
    """True when ``target`` is ``child`` or lies under it (``parents`` = {key: parent key})."""
    k = target
    while k is not None:
        if k == child:
            return True
        k = parents.get(k)
    return False


# --- tool strip ---------------------------------------------------------------------------------------------------

TOOLS = (("FRAME_ALL", "Frame All"), ("FRAME_SELECTED", "Frame Selection"),
         ("EXPAND_ALL", "Expand All"), ("COLLAPSE_ALL", "Collapse All"))


def strip_rects(widths, top, height, x0=6.0, gap=4.0):
    """Region rects (x0, y0, x1, y1) of the tool strip buttons of the given text widths, left to right under
    region y ``top``."""
    out, x = [], x0
    for w in widths:
        out.append((x, top - height, x + w, top))
        x += w + gap
    return out


# --- node icons ----------------------------------------------------------------------------------------------------

def node_kind(ob_type, is_locator=False):
    if ob_type == 'EMPTY':
        return 'LOCATOR' if is_locator else 'GROUP'
    return {'MESH': 'MESH', 'CURVE': 'CURVE', 'SURFACE': 'SURFACE', 'ARMATURE': 'JOINT', 'CAMERA': 'CAMERA',
            'LIGHT': 'LIGHT', 'LATTICE': 'LATTICE'}.get(ob_type, 'OTHER')


def icon_shapes(kind):
    """Primitives of a node icon in a [-1, 1] box: ("rect", x0, y0, x1, y1) filled, ("frame", x0, y0, x1, y1),
    ("line", ax, ay, bx, by), ("ring", cx, cy, r), ("disc", cx, cy, r), ("tri", ax, ay, bx, by, cx, cy)."""
    if kind == 'GROUP':      # an empty transform: a hollow box with a corner bracket
        return [("frame", -0.8, -0.8, 0.8, 0.8), ("line", -0.35, 0.35, 0.35, 0.35), ("line", 0.35, 0.35, 0.35, -0.35)]
    if kind == 'MESH':       # a cube: front face and the top / side edges
        return [("rect", -0.9, -0.9, 0.35, 0.35), ("line", -0.9, 0.35, -0.35, 0.9), ("line", -0.35, 0.9, 0.9, 0.9),
                ("line", 0.9, 0.9, 0.9, -0.35), ("line", 0.9, -0.35, 0.35, -0.9), ("line", 0.35, 0.35, 0.9, 0.9)]
    if kind == 'CURVE':
        return [("line", -0.9, -0.6, -0.4, 0.5), ("line", -0.4, 0.5, 0.1, -0.4), ("line", 0.1, -0.4, 0.5, 0.6),
                ("line", 0.5, 0.6, 0.9, 0.0)]
    if kind == 'SURFACE':
        return [("frame", -0.8, -0.6, 0.8, 0.6), ("line", -0.25, -0.6, -0.25, 0.6), ("line", 0.3, -0.6, 0.3, 0.6),
                ("line", -0.8, 0.0, 0.8, 0.0)]
    if kind == 'JOINT':      # a joint ball with a bone
        return [("ring", -0.45, 0.45, 0.4), ("line", -0.15, 0.15, 0.85, -0.85), ("disc", 0.7, -0.7, 0.18)]
    if kind == 'CAMERA':
        return [("rect", -0.9, -0.5, 0.3, 0.5), ("tri", 0.3, 0.0, 0.9, 0.55, 0.9, -0.55)]
    if kind == 'LIGHT':      # a bulb with rays
        return [("disc", 0.0, 0.0, 0.42), ("line", 0.0, 0.62, 0.0, 0.95), ("line", 0.0, -0.62, 0.0, -0.95),
                ("line", 0.62, 0.0, 0.95, 0.0), ("line", -0.62, 0.0, -0.95, 0.0)]
    if kind == 'LOCATOR':
        return [("line", -0.9, 0.0, 0.9, 0.0), ("line", 0.0, -0.9, 0.0, 0.9), ("line", -0.5, -0.5, 0.5, 0.5)]
    if kind == 'LATTICE':
        return [("frame", -0.8, -0.8, 0.8, 0.8), ("line", 0.0, -0.8, 0.0, 0.8), ("line", -0.8, 0.0, 0.8, 0.0)]
    return [("tri", 0.0, 0.8, 0.8, 0.0, 0.0, -0.8), ("tri", 0.0, 0.8, -0.8, 0.0, 0.0, -0.8)]


def text_colour(fill):
    """Dark text on a light fill, light text on a dark one."""
    lum = 0.2126 * fill[0] + 0.7152 * fill[1] + 0.0722 * fill[2]
    return (0.05, 0.05, 0.05, 1.0) if lum > 0.5 else (0.92, 0.92, 0.92, 1.0)
