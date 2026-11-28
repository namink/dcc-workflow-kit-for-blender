# SPDX-License-Identifier: GPL-3.0-or-later
"""The bend handle drawn like Maya in the Maya layout's 3D Views (#379).

Maya draws a bend deformer's handle in the handle's space: a straight line along its length from Low Bound to High
Bound, the same line bent by the Curvature (so the view shows which way and how far the bend goes), and a short line
from the handle's centre towards the side it bends to, 0.2 handle units long per radian of Curvature. Dark blue, or in
the selection colour while the handle is selected (green as the lead, white otherwise).

The kit handle is an empty (its arrow is what a click picks); the kit draws these lines over it for each kit bend of a
visible handle (operators/bend_deformer.py; a Simple Deform bend made like Maya on a lattice / curve / surface too).
"""

import bpy

DORMANT = (0.0, 4 / 255, 96 / 255)
LEAD = (0x43 / 255, 1.0, 0xa3 / 255)
SELECTED = (1.0, 1.0, 1.0)
LINE_PX = 1.0

_handle = []
_BENDS = {}         # view layer pointer -> (``objects_version``, ((handle, owner object, modifier name), ...))


def _scan(view_layer):
    """(handle, owner, modifier name) of every kit bend whose handle is in ``view_layer``."""
    from ..operators import deformers
    out = []
    for ob in view_layer.objects:
        for md in getattr(ob, "modifiers", ()):
            if deformers.base_of(md) != "bend":
                continue
            if md.type == 'SIMPLE_DEFORM' and md.deform_axis != 'Y':
                continue                            # a bend of earlier versions: Blender's own angle, no Maya lines
            h = deformers.handle_of(md)
            if h is not None and h.type == 'EMPTY':
                out.append((h, ob, md.name))
    return tuple(out)


def bends(view_layer):
    """The kit bends of ``view_layer``, looked up again only when objects came or went (a bend makes its handle)."""
    from .outliner import objects_version
    key = objects_version()
    ptr = view_layer.as_pointer()
    got = _BENDS.get(ptr)
    if got is None or got[0] != key:
        if len(_BENDS) > 8:
            _BENDS.clear()
        got = _BENDS[ptr] = (key, _scan(view_layer))
    return got[1]


def values(md):
    """(Curvature in radians, Low Bound, High Bound) of kit bend modifier ``md``."""
    from ..operators import bend_deformer, deformers
    if md.type == 'SIMPLE_DEFORM':
        return deformers.sd_bend_values(md)
    c, lo, hi = (bend_deformer.get(md, n) for n in ("Curvature", "Low Bound", "High Bound"))
    return float(c or 0.0), float(lo if lo is not None else -1.0), float(hi if hi is not None else 1.0)


def colour(handle, active):
    if handle.select_get():
        return LEAD if handle == active else SELECTED
    return DORMANT


def segments(view_layer, space=None, found=None):
    """[(world point, world point, colour)] of every visible kit bend handle in this view layer / view."""
    from ..operators import bend_deformer
    active = view_layer.objects.active
    out = []
    drawn = set()
    for h, ob, name in (bends(view_layer) if found is None else found):
        md = ob.modifiers.get(name)
        if md is None or h.as_pointer() in drawn or not h.visible_get(view_layer=view_layer, viewport=space):
            continue
        drawn.add(h.as_pointer())        # one handle driving several objects draws once (the same values)
        m = h.matrix_world
        col = colour(h, active)
        for a, b in bend_deformer.handle_lines(*values(md)):
            out.append((m @ a, m @ b, col))
    return out


def is_maya_view(space, workspace):
    """A 3D View of the Maya layout with overlays and empties shown."""
    from . import maya_joints, toolbox
    return (space is not None and workspace is not None and space.type == 'VIEW_3D' and not toolbox.is_toolbox(space)
            and space.overlay.show_overlays and space.show_object_viewport_empty
            and maya_joints.maya_workspace(workspace))


def _draw():
    context = bpy.context
    try:
        view_layer = context.view_layer
        found = bends(view_layer)
        if not found:               # the usual case first: no kit bend, nothing more is read in this draw
            return
        space = context.space_data
        if not is_maya_view(space, context.window.workspace):
            return
        try:
            segs = segments(view_layer, space, found)
        except ReferenceError:      # an object removed before the next depsgraph update: read the view layer again
            _BENDS.clear()
            segs = segments(view_layer, space)
    except (ReferenceError, AttributeError, KeyError, ValueError, RuntimeError, TypeError):
        return
    if not segs:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    pts, cols = [], []
    for p0, p1, c in segs:
        pts += [p0, p1]
        cols += [(*c, 1.0), (*c, 1.0)]
    region = context.region
    shading = space.shading
    sh = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
    gpu.state.depth_test_set('NONE' if shading.type == 'WIREFRAME' or shading.show_xray else 'LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    gpu.state.blend_set('ALPHA')
    try:
        sh.uniform_float("viewportSize", (region.width, region.height))
        sh.uniform_float("lineWidth", LINE_PX * context.preferences.system.pixel_size)
        batch_for_shader(sh, 'LINES', {"pos": pts, "color": cols}).draw(sh)
    finally:
        gpu.state.blend_set('NONE')
        gpu.state.depth_test_set('NONE')


def register():
    if not _handle:
        _handle.append(bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW'))


def unregister():
    while _handle:
        bpy.types.SpaceView3D.draw_handler_remove(_handle.pop(), 'WINDOW')
    _BENDS.clear()
