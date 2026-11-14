# SPDX-License-Identifier: GPL-3.0-or-later
"""The line from a camera to its aim (and up) node, drawn like Maya in the Maya layout's 3D Views (#299).

Maya draws a thin solid line from a Camera and Aim rig's camera to its aim node, and with Camera, Aim and Up a second
one to its up node, whatever is selected: dark blue, or in the selection colour while the rig's group is selected
(green as the lead, white otherwise). The group's Display Connector turns both lines off.

The Maya layout's views have Blender's relationship lines off (Maya draws no child-to-parent lines), so the kit draws
these lines itself, only for its camera rigs: a camera whose Track To (aim) or Locked Track (up) target is an empty
that shares the camera's parent group. A view whose Relationship Lines overlay is on shows Blender's lines instead.
The group's Display Connector (Attribute Editor > Extra Attributes; the ``allset_display_connector`` custom
property) shows or hides them.
"""

import bpy

DORMANT = (0.0, 4 / 255, 96 / 255)
LEAD = (0x43 / 255, 1.0, 0xa3 / 255)
SELECTED = (1.0, 1.0, 1.0)
LINE_PX = 1.0
CONNECTOR = "allset_display_connector"   # group custom property: draw the rig's lines (missing = on)
RIG_CONSTRAINTS = ('TRACK_TO', 'LOCKED_TRACK')

_handle = []


def mark(group):
    """Give a new rig group its Display Connector switch."""
    group[CONNECTOR] = True
    try:
        group.id_properties_ui(CONNECTOR).update(
            description="Draw the line from the camera to its aim and up nodes in the Maya layout views")
    except (TypeError, AttributeError):
        pass


def rig_targets(cam):
    """The kit rig's aim / up nodes this camera points at (empty if it is not a kit camera rig)."""
    group = cam.parent
    if cam.type != 'CAMERA' or group is None or group.type != 'EMPTY':
        return []
    out = []
    for con in cam.constraints:
        t = getattr(con, "target", None)
        if (con.type in RIG_CONSTRAINTS and con.enabled and t is not None and t.type == 'EMPTY'
                and t.parent == group and t not in out):
            out.append(t)
    return out


def connector_on(group):
    try:
        return bool(group.get(CONNECTOR, True))
    except (TypeError, AttributeError):
        return True


def colour(group, active):
    if group.select_get():
        return LEAD if group == active else SELECTED
    return DORMANT


_CAMERAS = {}       # view layer pointer -> (``objects_version``, its cameras in view layer order)


def cameras(view_layer):
    """The cameras of ``view_layer``, in its object order, looked up again only when objects came or went (an object's
    type never changes): a draw doesn't read every object of the scene."""
    from .outliner import objects_version
    key = objects_version()
    ptr = view_layer.as_pointer()
    got = _CAMERAS.get(ptr)
    if got is None or got[0] != key:
        if len(_CAMERAS) > 8:
            _CAMERAS.clear()
        got = _CAMERAS[ptr] = (key, [ob for ob in view_layer.objects if ob.type == 'CAMERA'])
    return got[1]


def segments(view_layer, space=None, cams=None):
    """[(camera point, target point, colour)] for every visible kit camera rig in this view layer / view. ``cams``:
    the view layer's cameras when known (``cameras``), else every object of the view layer is looked at."""
    active = view_layer.objects.active
    out = []
    for cam in (view_layer.objects if cams is None else cams):
        if cam.type != 'CAMERA':
            continue
        targets = rig_targets(cam)
        if not targets or not connector_on(cam.parent):
            continue
        if not cam.visible_get(view_layer=view_layer, viewport=space):
            continue
        col = colour(cam.parent, active)
        p0 = cam.matrix_world.translation.copy()
        for t in targets:
            if t.visible_get(view_layer=view_layer, viewport=space):
                out.append((p0, t.matrix_world.translation.copy(), col))
    return out


def is_maya_view(space, workspace):
    """A 3D View of the Maya layout with overlays on and Blender's relationship lines off."""
    from . import maya_joints, toolbox
    return (space is not None and workspace is not None and space.type == 'VIEW_3D' and not toolbox.is_toolbox(space)
            and space.overlay.show_overlays and not space.overlay.show_relationship_lines
            and space.show_object_viewport_camera and space.show_object_viewport_empty
            and maya_joints.maya_workspace(workspace))


def _draw():
    context = bpy.context
    try:
        space = context.space_data
        if not is_maya_view(space, context.window.workspace):
            return
        view_layer = context.view_layer
        try:
            segs = segments(view_layer, space, cameras(view_layer))
        except ReferenceError:      # a camera removed before the next depsgraph update: read the view layer again
            _CAMERAS.clear()
            segs = segments(view_layer, space, cameras(view_layer))
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
    _CAMERAS.clear()
