# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesh Tools > Connect as a kit tool, like Maya's Connect Tool (#322).

Entering the tool connects the selected components with the tool's Slide / Segments / Pinch: one edge alone gets
edge loops through its ring, edges of one ring are joined between them, two points of one face get a chord (an edge
is cut at its Slide point). Then it waits for clicks: click a vertex or an edge, then another one on the same face,
and they are joined; every further click continues the path from the last point. Ctrl+click an edge connects its
whole edge ring. A middle-drag (Ctrl or not) changes the value the Tool Settings radio picks (Segments by default;
Slide, Pinch) and re-does the last connection with it while the mesh is still as that connection left it; the HUD
shows the value like Maya ("Connect Segments: 1"). Enter / Esc ends the path and makes the last connection final;
a click on a component that shares no face with the last point starts a new path. A click away from the mesh keeps
Blender's selection.
"""

import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

TOOL = "allset.connect_tool"
HINT = ("Connect Tool: click vertices or edges one after another to connect them, Ctrl+click an edge to connect its "
        "ring, middle-drag to change Segments (or Slide / Pinch, see the Tool Settings), Enter / Esc to end the path")
HUD_RGB = (1.0, 1.0, 0.0)      # Maya's yellow HUD text
HUD_PX = 12
SEGMENT_PX = 30                # a middle-drag of this many pixels = one segment more / less (a short drag = one)
DEAD_PX = 4                    # a smaller move changes nothing
SLIDE_PER_PX = 0.005           # Slide 0 .. 1 over 200 px
PINCH_PER_PX = 0.5             # Pinch -100 .. 100 over 400 px
MODE_LABELS = {'SLIDE': "Slide", 'SEGMENTS': "Segments", 'PINCH': "Pinch"}

_path = {}     # the open path: object name, last point (kind, index) and the mesh's counts when it was made
_last = {}     # the last connection a middle-drag re-does: object, pre (BMesh copy), items [(kind, index)], ring,
               # counts (the mesh after it)
_handles = []


def _counts(bm):
    return len(bm.verts), len(bm.edges), len(bm.faces)


def end_path():
    """Enter / Esc: close the path and make the last connection final. True when there was one."""
    was_open = bool(_path) or bool(_last)
    _path.clear()
    forget()
    return was_open


def forget():
    pre = _last.pop("pre", None)
    if pre is not None:
        pre.free()
    _last.clear()


def _faces(el):
    return set(el.link_faces)


def _kind(el):
    return 'VERT' if isinstance(el, bmesh.types.BMVert) else 'EDGE'


def _element(bm, kind, index):
    seq = bm.verts if kind == 'VERT' else bm.edges
    seq.ensure_lookup_table()
    return seq[index] if 0 <= index < len(seq) else None


def _apply(bm, items, values, ring):
    from .poly_maya import connect_items
    slide, segments, pinch = values
    return connect_items(bm, items, 0.0, segments, slide, pinch, ring_lonely=ring)


def _restore(bm, pre):
    """Put the mesh from before the last connection back into ``bm`` (an edit-mode bmesh)."""
    me = bpy.data.meshes.new(".allset_connect_pre")
    try:
        pre.to_mesh(me)
        bm.clear()
        bm.from_mesh(me)
    finally:
        bpy.data.meshes.remove(me)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()


def _connect(ob_name, bm, items, values, ring=True):
    """Connect ``items`` with the tool's ``values`` (slide, segments, pinch) and remember the connection for a
    middle-drag. Returns the result of ``poly_maya.connect_items``."""
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    keys = [(_kind(it), it.index) for it in items]
    pre = bm.copy()
    res = _apply(bm, items, values, ring)
    if not res["made"]:
        pre.free()
        return res
    forget()
    _last.update(object=ob_name, pre=pre, items=keys, ring=ring, counts=_counts(bm))
    return res


def _next_point(bm, res, cur):
    """The vertex the path goes on from: the clicked vertex, or the middle new vertex of the clicked edge."""
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    if isinstance(cur, bmesh.types.BMEdge):
        mids = res["mids"].get(cur) or []
        cur = mids[len(mids) // 2] if mids else None
    if cur is not None and cur.is_valid:
        cur.select = True
        bm.select_flush_mode()
        return cur
    return None


def _start_path(bm, ob_name, kind, index, cur):
    for el in (*bm.verts, *bm.edges, *bm.faces):          # a new path: the clicked component alone
        el.select = False
    cur.select = True
    bm.select_flush_mode()
    _path.update(object=ob_name, point=(kind, index), counts=_counts(bm))


def click(bm, ob_name, kind, index, values=(0.5, 1, 0.0)):
    """One click of the tool on element ``index`` (``kind`` 'VERT' / 'EDGE'). Returns the new edges (empty when the
    click only starts a path)."""
    cur = _element(bm, kind, index)
    if cur is None:
        return []
    prev = None
    if _path.get("object") == ob_name and _path.get("counts") == _counts(bm):
        prev = _element(bm, *_path["point"])
    if prev is None or prev is cur or not (_faces(prev) & _faces(cur)):
        _start_path(bm, ob_name, kind, index, cur)
        return []
    res = _connect(ob_name, bm, [prev, cur], values, ring=False)
    if not res["made"]:
        _start_path(bm, ob_name, kind, index, cur)
        return []
    point = _next_point(bm, res, cur)
    if point is None:
        _path.clear()
    else:
        _path.update(object=ob_name, point=('VERT', point.index), counts=_counts(bm))
    return res["edges"]


def ring(bm, ob_name, index, values=(0.5, 1, 0.0)):
    """Ctrl+click: connect the edge ring through edge ``index`` (Segments loops around Slide)."""
    e = _element(bm, 'EDGE', index)
    if e is None:
        return []
    _path.clear()
    return _connect(ob_name, bm, [e], values, ring=True)["edges"]


def values(s):
    return (s.ct_slide, s.ct_segments, s.ct_pinch)


def redo_last(context):
    """A middle-drag: re-do the last connection with the tool's current Slide / Segments / Pinch. False when there
    is none, or the mesh is not as that connection left it (something else changed it, or it was undone)."""
    name = _last.get("object")
    ob = bpy.data.objects.get(name) if name else None
    if ob is None or ob.type != 'MESH' or ob.mode != 'EDIT':
        return False
    bm = bmesh.from_edit_mesh(ob.data)
    if _counts(bm) != _last["counts"]:
        return False
    from .edge_loops import settings
    _restore(bm, _last["pre"])
    items = [_element(bm, k, i) for k, i in _last["items"]]
    if any(it is None for it in items):
        bmesh.update_edit_mesh(ob.data)
        forget()
        return False
    res = _apply(bm, items, values(settings(context)), _last["ring"])
    _last["counts"] = _counts(bm)
    if _path.get("object") == name:
        point = _next_point(bm, res, items[-1])
        if point is None:
            _path.clear()
        else:
            _path.update(point=('VERT', point.index), counts=_counts(bm))
    bmesh.update_edit_mesh(ob.data)
    return True


# --- middle-drag ---------------------------------------------------------------------------------

def drag_start(s):
    """The value a middle-drag starts from (the one the Tool Settings radio picks)."""
    return {'SLIDE': s.ct_slide, 'SEGMENTS': s.ct_segments, 'PINCH': s.ct_pinch}[s.ct_mode]


def drag_value(s, dx, start):
    """The picked value after a middle-drag of ``dx`` pixels (right = more): Segments by one per 30 px, a short drag
    counting one; Slide 0.005 and Pinch 0.5 per pixel."""
    if s.ct_mode == 'SEGMENTS':
        steps = 0 if abs(dx) <= DEAD_PX else int(math.copysign(max(1, round(abs(dx) / SEGMENT_PX)), dx))
        return max(1, min(100, int(start) + steps))
    if s.ct_mode == 'SLIDE':
        return min(1.0, max(0.0, start + dx * SLIDE_PER_PX))
    return min(100.0, max(-100.0, start + dx * PINCH_PER_PX))


def set_value(s, value):
    if s.ct_mode == 'SEGMENTS':
        s.ct_segments = int(value)
    elif s.ct_mode == 'SLIDE':
        s.ct_slide = value
    else:
        s.ct_pinch = value


def hud_text(s):
    """Maya's HUD line for the tool: "Connect Segments: 1"."""
    value = drag_start(s)
    return f"Connect {MODE_LABELS[s.ct_mode]}: {value:g}"


def tool_active(context):
    from . import preselect
    return context.mode == 'EDIT_MESH' and preselect.tool_id(context) == TOOL


def _draw_hud():
    context = bpy.context
    try:
        if not tool_active(context):
            return
        import blf
        from .edge_loops import settings
        region = context.region
        scale = context.preferences.system.ui_scale or 1.0
        top = 0.0
        if context.preferences.system.use_region_overlap and context.area is not None:
            top = sum(r.height for r in context.area.regions if r.type in {'HEADER', 'TOOL_HEADER'}
                      and r.alignment in {'TOP', 'NONE'})
        text = hud_text(settings(context))
        font = 0
        blf.size(font, HUD_PX * scale)
        w, h = blf.dimensions(font, text)
        blf.color(font, *HUD_RGB, 1.0)
        blf.position(font, (region.width - w) / 2, region.height - top - h - 12 * scale, 0)
        blf.draw(font, text)
    except (ReferenceError, AttributeError, IndexError, ValueError, KeyError):
        pass


def _redraw(context):
    if context.area is not None:
        context.area.tag_redraw()


# --- operators -----------------------------------------------------------------------------------

class ALLSET_OT_connect_click(bpy.types.Operator):
    """Connect Tool click: join this vertex / edge to the last one clicked on the same face (Ctrl: the edge ring)"""
    bl_idname = "allset.connect_click"
    bl_label = "Connect"
    bl_options = {'UNDO'}

    object: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    kind: EnumProperty(items=(('VERT', "Vertex", ""), ('EDGE', "Edge", "")), options={'SKIP_SAVE', 'HIDDEN'})
    index: IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'})
    ring: BoolProperty(name="Ring", description="Connect the whole edge ring", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        from .edge_loops import settings
        ob = bpy.data.objects.get(self.object) if self.object else context.edit_object
        if ob is None or ob.type != 'MESH' or ob.mode != 'EDIT':
            return {'CANCELLED'}
        vals = values(settings(context))
        bm = bmesh.from_edit_mesh(ob.data)
        if self.ring:
            if self.kind != 'EDGE' or not ring(bm, ob.name, self.index, vals):
                return {'CANCELLED'}
        else:
            click(bm, ob.name, self.kind, self.index, vals)
        bmesh.update_edit_mesh(ob.data)
        _redraw(context)
        return {'FINISHED'}

    def invoke(self, context, event):
        from . import mesh_tools as mt
        view = mt._view(context)
        if view is None:
            return {'PASS_THROUGH'}
        mouse = (event.mouse_region_x, event.mouse_region_y)
        radius = mt.PICK_RADIUS * mt._ui_scale()
        objects = mt._mesh_objects(context)
        ob, index, kind = None, -1, 'EDGE'
        if not self.ring:                     # a vertex wins when the click is close to it
            ob, index = mt.pick(view, objects, mouse, 'VERT', radius * 0.6)
            kind = 'VERT'
        if ob is None:
            ob, index = mt.pick(view, objects, mouse, 'EDGE', radius)
            kind = 'EDGE'
        if ob is None:
            return {'PASS_THROUGH'}
        self.object, self.kind, self.index = ob.name, kind, index
        return self.execute(context)


class ALLSET_OT_connect_end(bpy.types.Operator):
    """End the Connect Tool's path and keep the last connection as it is"""
    bl_idname = "allset.connect_end"
    bl_label = "End Connect Path"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'FINISHED'} if end_path() else {'CANCELLED'}

    def invoke(self, context, event):
        return {'FINISHED'} if end_path() else {'PASS_THROUGH'}     # the key goes on when there is no path


class ALLSET_OT_connect_drag(bpy.types.Operator):
    """Middle-drag in the Connect Tool: change the value picked in its Tool Settings (Segments by default, or
    Slide / Pinch) and re-do the last connection with it; Esc / right-click puts the value back"""
    bl_idname = "allset.connect_drag"
    bl_label = "Connect Drag"
    bl_options = {'UNDO', 'BLOCKING'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def invoke(self, context, event):
        from .edge_loops import settings
        s = settings(context)
        self._x0 = event.mouse_x
        self._start = drag_start(s)
        self._value = self._start
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _set(self, context, value):
        from .edge_loops import settings
        s = settings(context)
        if value == self._value:
            return
        self._value = value
        set_value(s, value)
        redo_last(context)
        _redraw(context)

    def modal(self, context, event):
        from .edge_loops import settings
        if event.type == 'MOUSEMOVE':
            self._set(context, drag_value(settings(context), event.mouse_x - self._x0, self._start))
            return {'RUNNING_MODAL'}
        if event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._set(context, self._start)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class ALLSET_OT_connect_tool_enter(bpy.types.Operator):
    """Maya Mesh Tools > Connect: connect the selected vertices / edges, then click components to connect them"""
    bl_idname = "allset.connect_tool_enter"
    bl_label = "Connect Tool"
    bl_options = {'REGISTER', 'UNDO'}

    slide: FloatProperty(name="Slide", default=-1.0, min=-1.0, max=1.0, options={'SKIP_SAVE'})
    segments: IntProperty(name="Segments", default=0, min=0, max=100, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return context.mode == 'EDIT_MESH' or (context.mode == 'OBJECT' and ob is not None and ob.type == 'MESH')

    def execute(self, context):
        from .edge_loops import settings
        s = settings(context)
        if self.slide >= 0.0:               # the option window's values become the tool's
            s.ct_slide = self.slide
        if self.segments > 0:
            s.ct_segments = self.segments
        end_path()
        if context.mode == 'OBJECT':
            if not context.active_object.visible_get():
                self.report({'WARNING'}, f"{context.active_object.name} is hidden: show it first")
                return {'CANCELLED'}
            bpy.ops.object.mode_set(mode='EDIT')
        else:                                # Maya: the components selected before the tool are connected
            v, e, _f = context.tool_settings.mesh_select_mode
            if v or e:
                for ob in context.objects_in_mode:
                    bm = bmesh.from_edit_mesh(ob.data)
                    items = [x for x in (bm.verts if v else bm.edges) if x.select]
                    if items and _connect(ob.name, bm, items, values(s), ring=True)["made"]:
                        bmesh.update_edit_mesh(ob.data)
        try:
            bpy.ops.wm.tool_set_by_id(name=TOOL, space_type='VIEW_3D')
        except (RuntimeError, TypeError):
            pass                             # no 3D View (headless / another editor): the operation still ran
        self.report({'INFO'}, HINT)
        return {'FINISHED'}


classes = (ALLSET_OT_connect_click, ALLSET_OT_connect_end, ALLSET_OT_connect_drag, ALLSET_OT_connect_tool_enter)


def register_handlers():
    if not _handles:
        _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw_hud, (), 'WINDOW', 'POST_PIXEL'))


def unregister_handlers():
    while _handles:
        bpy.types.SpaceView3D.draw_handler_remove(_handles.pop(), 'WINDOW')
    end_path()
