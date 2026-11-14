# SPDX-License-Identifier: GPL-3.0-or-later
"""Joint Tool feedback in the 3D Views (#230): what the Joint Tool has placed so far and where the next joint goes.

While the tool runs one POST_PIXEL handler draws, in every 3D View but the Tool Box column:

- each joint of this run (and the joint it branches from) as a joint circle, the bones between them as wedges from
  the parent's circle to the child (like Maya's joints); the current joint — the one the next click attaches to —
  in the lead green, the others and their bones in Maya's unselected joint colour (dark violet);
- like Maya, nothing follows the pointer while no button is held: the next joint appears on the press. Before the
  first click, pointing at an existing joint (a click branches from it) highlights that joint.
- joints are drawn at world size like Maya's (half the joint Radius x Joint Size). In the Maya layout's views the
  kit's Maya joint drawing (``ui/maya_joints.py``) shows the skeleton instead, with the same colours.

The handler keeps no Blender data: the operator writes ``STATE`` (object name, joint names, region pointer, world
point) and the draw looks the skeleton up by name.
"""

import math

import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector


LEAD = (0x43 / 255, 1.0, 0xa3 / 255)       # Maya's lead (last selected) green
UNSELECTED = (0x26 / 255, 0.0, 0x43 / 255)  # Maya's unselected joint colour: the joints placed before the current one
LINE_PX = 1.5
CIRCLE_SEGMENTS = 24

STATE = {
    "ob": None,          # skeleton object name
    "names": [],         # joints placed in this run, in order
    "top": None,         # existing joint the run branches from
    "current": None,     # joint the next click attaches to
    "region": 0,         # pointer of the WINDOW region under the mouse
    "point": None,       # world point a click there would place (tuple)
    "branch": None,      # (object name, joint name) a first click would branch from
    "dragging": False,
}
_handles = []


def start():
    reset()
    if not _handles:
        _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL'))


def stop():
    reset()
    while _handles:
        bpy.types.SpaceView3D.draw_handler_remove(_handles.pop(), 'WINDOW')


def reset():
    STATE.update(ob=None, names=[], top=None, current=None, region=0, point=None, branch=None, dragging=False)


def running():
    return bool(_handles)


def redraw(window):
    """Tag every 3D View of ``window`` (a live window) for redraw."""
    if window is None or window.screen is None:
        return
    for area in window.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


# --- drawing ---------------------------------------------------------------------------------

def _heads(ob):
    """{joint name: world head} of ``ob`` (edit bones while in edit mode)."""
    mw = ob.matrix_world
    if ob.mode == 'EDIT':
        return {eb.name: mw @ eb.head for eb in ob.data.edit_bones}
    return {b.name: mw @ b.head_local for b in ob.data.bones}


def _parents(ob):
    if ob.mode == 'EDIT':
        return {eb.name: (eb.parent.name if eb.parent else None) for eb in ob.data.edit_bones}
    return {b.name: (b.parent.name if b.parent else None) for b in ob.data.bones}


def _radius_px(region, rv3d, world, r):
    """Screen radius of a joint circle of world radius ``r`` at ``world`` (Maya: pure world size)."""
    right = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
    p = view3d_utils.location_3d_to_region_2d(region, rv3d, world)
    q = view3d_utils.location_3d_to_region_2d(region, rv3d, world + right * r)
    return (q - p).length if p is not None and q is not None else 0.0


def _world_radius(ob, name):
    from ..ui import maya_joints
    bones = ob.data.edit_bones if ob.mode == 'EDIT' else ob.data.bones
    bone = bones.get(name)
    if bone is None:
        return 0.0
    return maya_joints.drawn_radius(bone, bpy.context.scene, max(ob.matrix_world.to_scale()))


def _circle(c, r):
    pts = [Vector((c.x + r * math.cos(2 * math.pi * i / CIRCLE_SEGMENTS),
                   c.y + r * math.sin(2 * math.pi * i / CIRCLE_SEGMENTS))) for i in range(CIRCLE_SEGMENTS)]
    return [q for i in range(CIRCLE_SEGMENTS) for q in (pts[i], pts[(i + 1) % CIRCLE_SEGMENTS])]


def _wedge(a, ra, b):
    """Two lines from the sides of the circle (a, ra) to b: Maya's bone outline."""
    d = b - a
    if d.length <= ra:
        return []
    n = Vector((-d.y, d.x)).normalized() * ra
    return [a + n, b, a - n, b]


def _lines(shader, segs, color, alpha=1.0):
    if not segs:
        return
    shader.uniform_float("color", (*color, alpha))
    batch_for_shader(shader, 'LINES', {"pos": [(p.x, p.y, 0.0) for p in segs]}).draw(shader)


TOOL = "ALLSET_OT_joint_tool"
_stale = []


def _tool_running(context):
    wm = getattr(context, "window_manager", None)
    return wm is not None and any(op.bl_idname == TOOL for w in wm.windows for op in w.modal_operators)


def _drop_stale():
    _stale.clear()
    if not _tool_running(bpy.context):
        stop()
    return None


def _draw():
    try:
        if not _tool_running(bpy.context):
            # the tool ended without its own cleanup (a file load, a closed window): drop the handler after this draw
            if not _stale:
                _stale.append(True)
                bpy.app.timers.register(_drop_stale, first_interval=0.0)
            return
        _draw_region(bpy.context)
    except (ReferenceError, AttributeError, ValueError, KeyError):
        pass


def _draw_region(context):
    from ..ui import maya_joints, toolbox
    if toolbox.is_toolbox(context.space_data) or maya_joints.is_maya_view(context.space_data, context.window.workspace):
        return
    region, rv3d = context.region, context.region_data
    if region is None or rv3d is None:
        return
    scale = context.preferences.system.ui_scale or 1.0
    ob = bpy.data.objects.get(STATE["ob"]) if STATE["ob"] else None
    heads = _heads(ob) if ob is not None and ob.type == 'ARMATURE' else {}
    parents = _parents(ob) if heads else {}

    def to2d(world):
        return view3d_utils.location_3d_to_region_2d(region, rv3d, world)

    shown = [n for n in ([STATE["top"]] if STATE["top"] else []) + list(STATE["names"]) if n in heads]
    spots = {}
    for n in shown:
        p = to2d(heads[n])
        if p is not None:
            spots[n] = (p, _radius_px(region, rv3d, heads[n], _world_radius(ob, n)))
    white, green = [], []
    for n, (p, r) in spots.items():
        (green if n == STATE["current"] else white).extend(_circle(p, r))
        par = parents.get(n)
        if par in spots and n in STATE["names"]:
            white.extend(_wedge(spots[par][0], spots[par][1], p))
    branch_ring = []
    here = STATE["region"] == region.as_pointer() and not STATE["dragging"]
    if here and STATE["branch"]:
        arm = bpy.data.objects.get(STATE["branch"][0])
        bone = arm.data.bones.get(STATE["branch"][1]) if arm is not None and arm.type == 'ARMATURE' else None
        if bone is not None:
            w = arm.matrix_world @ bone.head_local
            p = to2d(w)
            if p is not None:
                r = max(_radius_px(region, rv3d, w, _world_radius(arm, bone.name)), 3.0 * scale)
                branch_ring = _circle(p, r) + _circle(p, r + 2.0 * scale)
    if not (white or green or branch_ring):
        return
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_float("lineWidth", LINE_PX * scale)
    _lines(shader, white, UNSELECTED)
    _lines(shader, green, LEAD)
    _lines(shader, branch_ring, LEAD)
    gpu.state.blend_set('NONE')


def unregister_handlers():
    """Drop a running tool's preview (``operators.unregister``)."""
    if bpy.app.timers.is_registered(_drop_stale):
        bpy.app.timers.unregister(_drop_stale)
    _stale.clear()
    stop()
