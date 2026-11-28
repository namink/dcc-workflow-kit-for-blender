# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Selection Constraint (#435): the Modeling Toolkit's Selection Constraint and the tool option menus'
Selection Constraints radio items.

Angle: a pick in component mode (click, Shift / Ctrl / Ctrl+Shift click, marquee or lasso) also takes the components
connected to each picked one whose normal is within the Angle tolerance of the picked component's normal, like Maya:
- faces: the face normal, connected through edges;
- edges: the mean of the edge's faces' normals, connected through vertices;
- vertices: the mean of the vertex's faces' normals, connected through edges.
Each normal is compared with the picked component's, not between neighbours, so a slowly bending surface stops
at the tolerance and a flat patch behind a steep fold is not reached. Tolerance 0 keeps the pick as it is.
Only picks in the viewport are constrained; commands that select (Grow, Select All, scripts) are not.

The state is one setting for the session (WindowManager ``allset_sel_constraint`` + ``allset_sel_constraint_angle``,
in degrees). Blender selects first (its click / box / lasso); the kit then grows what that pick changed: the
picks reach ``watch`` from the first-place selection items of ``uv_shell_select``.
"""

import math

import bmesh
import bpy
from bpy.props import EnumProperty, FloatProperty

from .. import live_refs

MODE = "allset_sel_constraint"
ANGLE = "allset_sel_constraint_angle"
MODES = (('OFF', "Off", "Picks select what is under the pointer"),
         ('ANGLE', "Angle", "A pick also selects the connected components whose normal is within the Angle "
                            "tolerance of the picked one's"))
EPS = 1e-6                    # radians: float noise around the tolerance
BOX_OPS = ("VIEW3D_OT_select_box", "VIEW3D_OT_select_lasso", "VIEW3D_OT_select_circle")

_watch = {}


def mode(context):
    wm = context.window_manager
    return getattr(wm, MODE, 'OFF') if wm is not None else 'OFF'


def tolerance(context):
    wm = context.window_manager
    return float(getattr(wm, ANGLE, 0.0)) if wm is not None else 0.0


def active(context):
    """The Angle constraint changes picks: Angle on, a tolerance above 0, a mesh in edit mode."""
    return context.mode == 'EDIT_MESH' and mode(context) == 'ANGLE' and tolerance(context) > 0.0


def _meshes(context):
    return [o for o in (getattr(context, "objects_in_mode_unique_data", None) or ()) if o and o.type == 'MESH']


def domain(context):
    """The component kind picks select: faces, else edges, else vertices (the finest mode shown wins in
    Blender's mixed select modes)."""
    v, e, f = context.scene.tool_settings.mesh_select_mode
    return 'FACE' if f and not (v or e) else 'EDGE' if e and not v else 'VERT' if v else 'FACE'


def _elements(bm, kind):
    return bm.faces if kind == 'FACE' else bm.edges if kind == 'EDGE' else bm.verts


def _mean_normal(faces):
    n = None
    for f in faces:
        n = f.normal.copy() if n is None else n + f.normal
    return n.normalized() if n is not None and n.length > 1e-12 else None


def _normal(el, kind):
    if kind == 'FACE':
        return el.normal
    return _mean_normal(el.link_faces)


def _neighbours(el, kind):
    if kind == 'FACE':
        return {g for e in el.edges for g in e.link_faces if g is not el}
    if kind == 'EDGE':
        return {g for v in el.verts for g in v.link_edges if g is not el}
    return {e.other_vert(el) for e in el.link_edges}


def grow(bm, kind, seeds, degrees):
    """Indices of the components connected to each seed (indices) whose normal is within ``degrees`` of that
    seed's normal, the seeds included. Hidden components are not reached."""
    seq = _elements(bm, kind)
    seq.ensure_lookup_table()
    # exactly at the tolerance: a face stays out, an edge or vertex comes in, like Maya
    limit = math.radians(degrees) + (-EPS if kind == 'FACE' else EPS)
    out = set()
    done = []          # (seed normal, region): a seed inside a region grown from the same normal has that region
    for i in seeds:
        seed = seq[i]
        n0 = _normal(seed, kind)
        out.add(i)
        if n0 is None or n0.length < 1e-12:
            continue
        if any(i in region and n0.angle(n) < 1e-9 for n, region in done):
            continue
        region = {i}
        stack, seen = [seed], {i}
        while stack:
            el = stack.pop()
            for nb in _neighbours(el, kind):
                if nb.index in seen or nb.hide:
                    continue
                seen.add(nb.index)
                n = _normal(nb, kind)
                if n is None or n.length < 1e-12 or n0.angle(n) > limit:
                    continue
                region.add(nb.index)
                stack.append(nb)
        out |= region
        done.append((n0.copy(), region))
    return out


def _selected(bm, kind):
    return {el.index for el in _elements(bm, kind) if el.select}


def write(ob, bm, kind, chosen):
    """Exactly the components ``chosen`` (indices of ``kind``) selected on ``bm``."""
    seq = _elements(bm, kind)
    seq.ensure_lookup_table()
    for s in (bm.verts, bm.edges, bm.faces):
        for el in s:
            el.select = False
    for i in sorted(chosen):
        seq[i].select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)


def snapshot(context):
    """Selection before a pick: {object name: (component count, selected indices)} for the pick's kind."""
    kind = domain(context)
    out = {}
    for ob in _meshes(context):
        bm = bmesh.from_edit_mesh(ob.data)
        out[ob.name] = (len(_elements(bm, kind)), _selected(bm, kind))
    return kind, out


def apply(context, kind, before, degrees, shift=False, ctrl=False):
    """After Blender's pick, with Maya's modifier rule: plain = the picked components grown (replace), Ctrl+Shift =
    what was added grown, Ctrl = the grown region of what was removed taken away, Shift (toggle) = both."""
    changed = False
    for ob in _meshes(context):
        if ob.name not in before:
            continue
        n, was = before[ob.name]
        bm = bmesh.from_edit_mesh(ob.data)
        if len(_elements(bm, kind)) != n:
            continue
        now = _selected(bm, kind)
        added, removed = now - was, was - now
        if not added and not removed:
            continue
        if not shift and not ctrl:
            after = grow(bm, kind, now, degrees)
        else:
            after = now
            if added and not (ctrl and not shift):
                after = after | grow(bm, kind, added, degrees)
            if removed and (ctrl or shift) and not (ctrl and shift):
                after = after - grow(bm, kind, removed, degrees)
        if after != now:
            write(ob, bm, kind, after)
            changed = True
    return changed


def _box_running():
    try:
        return any(op.bl_idname in BOX_OPS for w in bpy.context.window_manager.windows
                   for op in live_refs.running_modals(w))
    except (AttributeError, ReferenceError):
        return False


def _tick():
    st = _watch.get("state")
    if st is None:
        return None
    st["ticks"] += 1
    if _box_running() and st["ticks"] < 400:      # a marquee / lasso is still being drawn (20 s cap)
        return 0.05
    _watch.pop("state", None)
    try:
        if active(bpy.context) and domain(bpy.context) == st["kind"]:
            apply(bpy.context, st["kind"], st["before"], tolerance(bpy.context), st["shift"], st["ctrl"])
    except (ReferenceError, AttributeError, RuntimeError):
        pass
    return None


def watch(context, event):
    """A pick starts (the first-place click / drag items): note the selection; Blender's pick runs next and the
    kit grows its result on the next timer tick."""
    if not active(context):
        return
    space = context.space_data
    if space is None or space.type != 'VIEW_3D':
        return
    kind, before = snapshot(context)
    _watch["state"] = {"kind": kind, "before": before, "ticks": 0, "shift": event.shift, "ctrl": event.ctrl}
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.01)


def register_props():
    bpy.types.WindowManager.allset_sel_constraint = EnumProperty(
        name="Selection Constraint", items=MODES, default='OFF',
        description="Maya selection constraint for picks in component mode")
    bpy.types.WindowManager.allset_sel_constraint_angle = FloatProperty(
        name="Angle", min=0.0, max=180.0, default=0.0, precision=1,
        description="Angle tolerance in degrees: a pick also selects the connected components whose normal is "
                    "within this angle of the picked one's (0 = only what is picked)")


def unregister_props():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _watch.clear()
    del bpy.types.WindowManager.allset_sel_constraint_angle
    del bpy.types.WindowManager.allset_sel_constraint
