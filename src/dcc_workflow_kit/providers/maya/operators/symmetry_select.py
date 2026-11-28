# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya symmetric selection (#445): with Symmetry on, a component pick in the 3D View also picks its mirror partner.

Maya applies the pick's modifier to the picked components together with their partners: a click selects both, Shift
toggles both, Ctrl removes both, Ctrl+Shift adds both, for clicks, marquees, lassos and the double-click loop (an edge
loop gets its mirrored loop). Grow / Shrink, the Select menu commands and UV picks don't mirror.

- A partner is the component at the mirrored position, within ``TOLERANCE`` (Maya's symmetry tolerance) of it: Object
  mirrors across the object's own axis, World across the world plane through the world origin (a mesh away from that
  plane has no partners), Topology uses Blender's topology mirror of the chosen axis.
- The pick itself stays Blender's: a click runs ``view3d.select`` as a plain replace to learn what is under the mouse,
  a marquee / lasso runs ``view3d.select_box`` / ``select_lasso`` the same way; then the kit writes the result of the
  modifier from the selection before. One undo step.

Entry points: ``allset.select_priority`` (click, first in front of ``view3d.select``), ``allset.select_through``
(marquee / lasso drags, drawn by ``allset.symmetry_drag``), ``edge_marquee.apply_rect`` (the edge marquee) and
``allset.loop_pick`` (double-click).
"""

import bmesh
import bpy
import gpu
from bpy.props import BoolProperty, EnumProperty, IntProperty
from mathutils import kdtree

from .. import compat
from . import symmetry

TOLERANCE = 0.1           # Maya units: how far from the mirrored position a partner may be


# --- state -------------------------------------------------------------------------------------------------------

def applies(context):
    """Symmetry is on and a mesh pick in this 3D View should take the partners too."""
    scene = context.scene
    sym = getattr(scene, "allset_symmetry", None)
    if sym is None or not sym.on or context.mode != 'EDIT_MESH':
        return False
    space = context.space_data
    if space is None or space.type != 'VIEW_3D':
        return False
    from . import uv_components, uv_shell_select
    if uv_components.in_uv_mode(scene) or uv_shell_select.active(context):
        return False             # UV picks don't mirror
    return True


def domain(select_mode):
    """The component kind a pick works on: VERT, EDGE or FACE (the lowest select mode that is on)."""
    vert, edge, _face = select_mode
    return 'VERT' if vert else ('EDGE' if edge else 'FACE')


def _seq(bm, dom):
    seq = bm.verts if dom == 'VERT' else (bm.edges if dom == 'EDGE' else bm.faces)
    seq.ensure_lookup_table()
    return seq


def _meshes(context):
    return [ob for ob in context.objects_in_mode_unique_data if ob.type == 'MESH']


def snapshot(context, dom):
    """{object name: (selected indices, select history)} of the meshes in edit mode."""
    out = {}
    for ob in _meshes(context):
        bm = bmesh.from_edit_mesh(ob.data)
        out[ob.name] = ({i for i, el in enumerate(_seq(bm, dom)) if el.select}, list(bm.select_history))
    return out


def selected(context, dom):
    return {name: sel for name, (sel, _hist) in snapshot(context, dom).items()}


# --- partners ----------------------------------------------------------------------------------------------------

def _vert_partners(ob, bm, sym, wanted):
    """{vertex index: partner vertex index} for the vertices ``wanted``."""
    world = sym.about == 'WORLD'          # Object and Topology: the object's own axes
    m = ob.matrix_world
    pos = [m @ v.co for v in bm.verts] if world else [v.co.copy() for v in bm.verts]
    tree = kdtree.KDTree(len(pos))
    for i, p in enumerate(pos):
        tree.insert(p, i)
    tree.balance()
    from .units import maya_unit
    tol = TOLERANCE * maya_unit()
    ax = symmetry.AXES.index(sym.axis)
    out = {}
    for i in wanted:
        p = pos[i].copy()
        p[ax] = -p[ax]
        _co, j, dist = tree.find(p)
        if j is not None and dist <= tol:
            out[i] = j
    return out


def _partners_by_position(ob, bm, sym, dom, picked):
    bm.verts.index_update()
    seq = _seq(bm, dom)
    if dom == 'VERT':
        vm = _vert_partners(ob, bm, sym, picked)
        return set(vm.values())
    wanted = {v.index for i in picked for v in seq[i].verts}
    vm = _vert_partners(ob, bm, sym, wanted)
    out = set()
    verts = bm.verts
    verts.ensure_lookup_table()
    for i in picked:
        el = seq[i]
        try:
            mv = {vm[v.index] for v in el.verts}
        except KeyError:
            continue             # some corner has no partner
        first = verts[next(iter(mv))]
        links = first.link_edges if dom == 'EDGE' else first.link_faces
        for other in links:
            if {v.index for v in other.verts} == mv:
                out.add(other.index)
                break
    return out


def _partners_by_topology(context, dom, picked, sym):
    """Blender's topology mirror: select exactly ``picked``, mirror it, read the result (the caller writes its own
    selection afterwards). Where it finds fewer partners than picks (a mesh whose topology alone can't tell the sides
    apart, like a subdivided cube) the partners at the mirrored positions join them."""
    for ob in _meshes(context):
        bm = bmesh.from_edit_mesh(ob.data)
        seq = _seq(bm, dom)
        want = picked.get(ob.name, set())
        _write_set(bm, seq, want)
        bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
    try:
        bpy.ops.mesh.select_mirror(axis={sym.axis}, extend=False)
        found = selected(context, dom)
    except RuntimeError:
        found = {}
    for ob in _meshes(context):
        want = picked.get(ob.name)
        if want and len(found.get(ob.name, ())) < len(want):
            bm = bmesh.from_edit_mesh(ob.data)
            found[ob.name] = found.get(ob.name, set()) | _partners_by_position(ob, bm, sym, dom, want)
    return found


def partners(context, dom, picked):
    """{object name: partner indices} of the components ``picked`` ({object name: indices}). Topology mirroring
    goes through the selection: callers write theirs after."""
    sym = context.scene.allset_symmetry
    if sym.about == 'TOPOLOGY':
        return _partners_by_topology(context, dom, picked, sym)
    out = {}
    for ob in _meshes(context):
        want = picked.get(ob.name)
        if want:
            bm = bmesh.from_edit_mesh(ob.data)
            out[ob.name] = _partners_by_position(ob, bm, sym, dom, want)
    return out


# --- writing -------------------------------------------------------------------------------------------------------

def combine(before, hits, mode):
    """The selected set after a pick with Maya's modifiers: SET replaces, ADD adds, SUB removes, XOR toggles."""
    if mode == 'ADD':
        return before | hits
    if mode == 'SUB':
        return before - hits
    if mode == 'XOR':
        return before ^ hits
    return set(hits)


def _write_set(bm, seq, final):
    for i, el in enumerate(seq):           # deselect first: then the components that stay selected keep their corners
        if el.select and i not in final and not el.hide:
            el.select_set(False)
    for i in final:
        el = seq[i]
        if not el.hide:
            el.select_set(True)
    bm.select_flush_mode()


def apply(context, dom, before, picked, mode, active=None):
    """Write ``mode`` applied with the picked components and their partners onto ``before`` (``snapshot``).
    ``active``: {object name: element} the pick made active. Returns True when some selection changed."""
    mirrored = partners(context, dom, picked)
    changed = False
    for ob in _meshes(context):
        sel, hist = before.get(ob.name, (set(), []))
        hits = set(picked.get(ob.name, ())) | mirrored.get(ob.name, set())
        final = combine(sel, hits, mode)
        bm = bmesh.from_edit_mesh(ob.data)
        seq = _seq(bm, dom)
        _write_set(bm, seq, final)
        final_now = {i for i, el in enumerate(seq) if el.select}
        lead = (active or {}).get(ob.name)
        keep = [] if mode == 'SET' else [h for h in hist if h.is_valid and h.select]
        bm.select_history.clear()
        for h in keep:
            if h is not lead:
                bm.select_history.add(h)
        if lead is not None and lead.is_valid and lead.select:
            bm.select_history.add(lead)
        bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
        changed = changed or final_now != sel
    return changed


def pick_mode(shift, ctrl):
    """Maya modifiers as a select mode: plain replaces, Shift toggles, Ctrl removes, Ctrl+Shift adds."""
    return {(True, False): 'XOR', (False, True): 'SUB', (True, True): 'ADD'}.get((bool(shift), bool(ctrl)), 'SET')


# --- click ---------------------------------------------------------------------------------------------------------

def click(context, event):
    """A click pick with its partners (``allset.select_priority``). Returns True when the selection changed."""
    dom = domain(context.tool_settings.mesh_select_mode)
    before = snapshot(context, dom)
    try:
        bpy.ops.view3d.select(deselect_all=True, location=(event.mouse_region_x, event.mouse_region_y))
    except RuntimeError:
        return False
    picked = selected(context, dom)
    active = {}
    for ob in _meshes(context):
        el = bmesh.from_edit_mesh(ob.data).select_history.active
        if el is not None:
            active[ob.name] = el
    mode = pick_mode(event.shift, event.ctrl)
    if mode == 'SUB':
        active = {}
    return apply(context, dom, before, picked, mode, active)


def after_pick(context, before, dom, mode):
    """A pick that already ran (the double-click loop / shell): add the partners of what it picked. SET takes the
    whole new selection as the pick, the other modes what it added."""
    now = selected(context, dom)
    picked = {name: (sel if mode == 'SET' else sel - before.get(name, (set(), []))[0]) for name, sel in now.items()}
    active = {}
    for ob in _meshes(context):
        el = bmesh.from_edit_mesh(ob.data).select_history.active
        if el is not None:
            active[ob.name] = el
    if mode == 'SET':
        base = {name: (set(), []) for name in now}
    else:
        base = {name: (now[name], hist) for name, (_sel, hist) in before.items() if name in now}
    return apply(context, dom, base, picked, 'SET' if mode == 'SET' else 'ADD', active)


# --- marquee / lasso ---------------------------------------------------------------------------------------------

def _xray_on(context):
    """Set the view's X-ray flag for one Blender box / lasso call when the marquee selects hidden components (like
    ``allset.select_through``). Returns what to put back."""
    from . import marquee
    from .. import preferences
    try:
        through = preferences.get().select_through
    except KeyError:
        through = False
    shading = context.space_data.shading
    flag, alpha = marquee._attrs(shading)
    if not through or getattr(shading, flag):
        return None
    old = getattr(shading, alpha)
    setattr(shading, flag, True)
    setattr(shading, alpha, 1.0)
    return shading, flag, alpha, old


def _xray_off(saved):
    if saved is not None:
        shading, flag, alpha, old = saved
        setattr(shading, flag, False)
        setattr(shading, alpha, old)


def region_pick(context, mode, rect=None, path=None):
    """A marquee (``rect`` region px x0, y0, x1, y1) or lasso (``path`` region px points) with its partners."""
    dom = domain(context.tool_settings.mesh_select_mode)
    before = snapshot(context, dom)
    saved = _xray_on(context)
    try:
        if rect is not None:
            x0, y0, x1, y1 = (int(round(v)) for v in rect)
            bpy.ops.view3d.select_box(xmin=x0, xmax=x1, ymin=y0, ymax=y1, mode='SET', wait_for_input=False)
        else:
            bpy.ops.view3d.select_lasso(path=[{"name": "", "loc": p, "time": 0.0} for p in path], mode='SET')
    except RuntimeError:
        pass
    finally:
        _xray_off(saved)
    picked = selected(context, dom)
    return apply(context, dom, before, picked, mode)


def drag_takes(context):
    """The kit draws this marquee / lasso itself: Symmetry is on in a mesh's edit mode."""
    region = context.region
    return applies(context) and region is not None and region.type == 'WINDOW' and context.region_data is not None


def start_drag(context, event):
    """Start ``allset.symmetry_drag`` from the drag that ``event`` (a LMB CLICK_DRAG) began."""
    try:
        tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    except (AttributeError, RuntimeError):
        tool = None
    shape = 'LASSO' if tool is not None and tool.idname == "builtin.select_lasso" else 'BOX'
    x = getattr(event, "mouse_prev_press_x", event.mouse_x) - context.region.x
    y = getattr(event, "mouse_prev_press_y", event.mouse_y) - context.region.y
    bpy.ops.allset.symmetry_drag('INVOKE_DEFAULT', shape=shape, x=x, y=y, shift=event.shift, ctrl=event.ctrl)


class ALLSET_OT_symmetry_drag(bpy.types.Operator):
    """Marquee or lasso with Symmetry on: the components inside and their mirror partners (Shift toggles, Ctrl
    removes, Ctrl+Shift adds)"""
    bl_idname = "allset.symmetry_drag"
    bl_label = "Box Select"
    bl_options = {'INTERNAL'}

    shape: EnumProperty(items=(('BOX', "Box", ""), ('LASSO', "Lasso", "")), options={'HIDDEN', 'SKIP_SAVE'})
    x: IntProperty(options={'HIDDEN', 'SKIP_SAVE'})
    y: IntProperty(options={'HIDDEN', 'SKIP_SAVE'})
    shift: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})
    ctrl: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        if not drag_takes(context):
            return {'CANCELLED'}
        self._pts = [(self.x, self.y), (event.mouse_region_x, event.mouse_region_y)]
        self._region = context.region
        self._handle = context.space_data.draw_handler_add(self._draw, (), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        self._region.tag_redraw()
        return {'RUNNING_MODAL'}

    def _outline(self):
        if self.shape == 'BOX':
            (x0, y0), (x1, y1) = self._pts[0], self._pts[-1]
            return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        return self._pts

    def _draw(self):
        if bpy.context.region != self._region:
            return
        loop = self._outline()
        if len(loop) < 2:
            return
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        for width, color in ((3.0, (0.0, 0.0, 0.0, 0.6)), (1.0, (1.0, 1.0, 1.0, 0.9))):
            gpu.state.line_width_set(width)
            shader.uniform_float("color", color)
            compat.closed_line_batch(shader, loop).draw(shader)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')

    def _stop(self, context):
        context.space_data.draw_handler_remove(self._handle, 'WINDOW')
        self._region.tag_redraw()

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            p = (event.mouse_region_x, event.mouse_region_y)
            if self.shape == 'BOX':
                self._pts[-1] = p
            elif p != self._pts[-1]:
                self._pts.append(p)
            self._region.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._stop(context)
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            p = (event.mouse_region_x, event.mouse_region_y)
            if self.shape == 'BOX':
                self._pts[-1] = p
            elif p != self._pts[-1]:
                self._pts.append(p)
            self._stop(context)
            mode = pick_mode(self.shift, self.ctrl)
            with context.temp_override(region=self._region):
                if self.shape == 'BOX':
                    (x0, y0), (x1, y1) = self._pts[0], self._pts[-1]
                    rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
                    done = region_pick(bpy.context, mode, rect=rect)
                elif len(self._pts) >= 3:
                    done = region_pick(bpy.context, mode, path=self._pts)
                else:
                    done = False
            if done:
                bpy.ops.ed.undo_push(message="Box Select" if self.shape == 'BOX' else "Lasso Select")
            for area in context.screen.areas if context.screen else ():
                area.tag_redraw()
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


classes = (ALLSET_OT_symmetry_drag,)
