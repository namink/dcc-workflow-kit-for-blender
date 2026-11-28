# SPDX-License-Identifier: GPL-3.0-or-later
"""Quad Draw's live state while the tool is on: ``STATE`` and the per-view caches behind what is under the mouse
(``component_at``, ``fill_plan``, ``loop_plan``, ``topology_preview``), the stroke symmetry helpers, the preview draw
handlers (``_draw_view``, ``_draw_pixel``), the Retopology overlay of the views the tool owns (``sync_overlays``, put
back around file saves and when the tool is left: ``_watch``) and the undo / load resets. The caches and
``_overlay_saving`` are rebound here, so read them on this module (``quad_draw`` holds no copy).
"""

import math

import bmesh
import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import multi_cut, poly_draw, preselect, quad_draw_symmetry
from .quad_draw_geometry import (DOT_LAYER, _indices, clear_dots, component_loop, dot_layer, dots, fill_face,
                                 width_preview)
from .quad_draw_surface import _screen_xy, _ui_scale, reference_objects, surface_offset

TOOL = "allset.quad_draw_tool"
DRAG_PX = 4.0           # a press that moves less than this is a click
BRUSH_PX = 50.0         # relax brush radius
DOT_RGB = (0.26, 1.0, 0.64)        # selection green #43ffa3 for the dots
FILL_RGB = (0.26, 1.0, 0.64)
LOOP_RGB = (1.0, 0.55, 0.1)
DELETE_RGB = (1.0, 0.2, 0.2)
DOT_SIZE = 8.0
LINE_PX = 2.0


# --- live state -----------------------------------------------------------------------------------------

STATE = {"ob": None, "preview": None, "snap": [], "created": None, "overlays": {}, "timer": False}
_topology_preview=None
_pick_projection = None
_fill_projection = None
_component_loop_cache=None


def loop_plan(context,ob,index):
    """Share one loop traversal between hover, delete and loop tweak."""
    global _component_loop_cache
    c=next((c for candidate,c in preselect.caches(context) if candidate==ob),None)
    if c is None:return None
    key=(c,c.revision,index)
    if _component_loop_cache is not None and _component_loop_cache[0]==key:return _component_loop_cache[1]
    edges=component_loop(c.bm.edges[index])
    plan={'edges':tuple(e.index for e in edges),'verts':tuple(sorted({v.index for e in edges for v in e.verts})),
          'faces':tuple(sorted({f.index for e in edges for f in e.link_faces})),
          'points':[tuple(c.co[v.index]) for e in edges for v in e.verts]}
    _component_loop_cache=key,plan
    return plan


def reset_preview():
    STATE["preview"] = None
    STATE["snap"] = []


def topology_preview(context,ob):
    """One geometry/view-independent correspondence; drawing the panel never walks the mesh."""
    global _topology_preview
    sym=context.scene.allset_symmetry
    if not sym.on or sym.about!='TOPOLOGY':return None
    c=next((c for candidate,c in preselect.caches(context) if candidate==ob),None)
    if c is None:return None
    active=c.bm.select_history.active
    key=(c,getattr(c,'revision',0),sym.axis,sym.allow_partial,tuple(ob.data.get(quad_draw_symmetry.SEED,())),
         active.index if isinstance(active,bmesh.types.BMEdge) else None)
    if _topology_preview is not None and _topology_preview[0]==key:return _topology_preview[1]
    try:
        pairs=quad_draw_symmetry.topology_mapping(ob,c.bm,sym)
        indices={v.index:other.index for v,other in pairs.items()}
        seam_ids=[tuple(v.index for v in e.verts) for e in c.bm.edges if all(pairs.get(v) is v for v in e.verts)]
        seam=[(c.co[a],c.co[b]) for a,b in seam_ids]
        info={'object':ob.name,'pairs':indices,'seam':seam,'seam_ids':seam_ids,'paired':sum(a!=b for a,b in indices.items())//2,
              'unmatched':len(c.co)-len(indices),'message':'' if pairs else 'Pick a seam edge on matching topology'}
    except quad_draw_symmetry.SymmetryError as ex:
        info={'object':ob.name,'pairs':{},'seam':[],'paired':0,'unmatched':len(c.co),'message':str(ex)}
    _topology_preview=key,info;STATE['topology_info']=info
    return info


def clear_topology_preview():
    global _topology_preview
    _topology_preview=None;STATE['topology_info']=None;STATE['topology_hover']=None;STATE['topology_preview']=None
    from . import quad_draw_overlay
    quad_draw_overlay.clear_symmetry()


def edit_object(context):
    ob = context.edit_object
    return ob if ob is not None and ob.type == 'MESH' else None


def tool_active(context):
    return context.mode == 'EDIT_MESH' and preselect.tool_id(context) == TOOL


def _reference_visible(context, region, rv3d, point, refs, clearance=0):
    """Reject the far sheet of a live reference, allowing coarse-face display sag."""
    if not refs:
        return True
    from . import live
    xy = _screen_xy(region, rv3d, point)
    if xy is None:
        return False
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, xy)
    delta = point-origin
    distance = delta.length
    if distance < 1e-12:
        return True
    hit = live.ray_hit(context, origin, delta/distance, refs, True)
    offset = abs(surface_offset(context))
    return not hit or (hit[0]-origin).length >= distance-max(1e-5,distance*1e-7)-offset*1.1-clearance


def component_at(context, region, rv3d, mouse, ob, edges_only=False):
    """('VERT', i) / ('EDGE', i, t) / ('FACE', i, local co) of ``ob`` under the mouse (dots are vertices), or None."""
    global _pick_projection
    c = next((c for candidate, c in preselect.caches(context) if candidate == ob), None)
    if c is None:
        return None
    key = (region.width, region.height, tuple(map(tuple, rv3d.perspective_matrix)), _ui_scale(context),getattr(c,'revision',0))
    if _pick_projection is None or _pick_projection[0] is not c or _pick_projection[1] != key:
        xy, front = preselect.project(c.co, rv3d.perspective_matrix, region.width, region.height)
        # A large vertex hit zone steals short edges and small faces. Compute a
        # local radius once per view, retaining the wider Ctrl-loop edge zone.
        import numpy as np
        shortest = np.full(len(xy), np.inf)
        if len(c.edges):
            lengths = np.linalg.norm(xy[c.edges[:,0]]-xy[c.edges[:,1]], axis=1)
            np.minimum.at(shortest, c.edges[:,0], lengths)
            np.minimum.at(shortest, c.edges[:,1], lengths)
        radius = np.minimum(8.0*_ui_scale(context), shortest*.22)
        radius = np.maximum(3.0*_ui_scale(context), radius)
        _pick_projection = c, key, xy, front, radius
    _, _, xy, front, radius = _pick_projection
    cs = [(ob, c)]
    xray = preselect._xray(context.space_data)
    scale = _ui_scale(context)
    refs = reference_objects(context)
    import numpy as np
    if not edges_only:
        distance2 = ((xy - mouse)**2).sum(axis=1)
        near = np.flatnonzero(c.vok & front & (distance2 <= radius**2))
        for j in near[np.argsort(distance2[near])]:
            i = int(j)
            point = Vector(c.co[i])
            if not multi_cut._occluded(cs, region, rv3d, point, xray) and _reference_visible(context,region,rv3d,point,refs):
                return 'VERT', i
    if len(c.edges):
        distance, ts = preselect.segment_distance(mouse, xy[c.edges[:, 0]], xy[c.edges[:, 1]])
        ok = c.eok & front[c.edges[:, 0]] & front[c.edges[:, 1]]
        tolerance = multi_cut.EDGE_PX*scale if edges_only else 5.0*scale
        near = np.flatnonzero(ok & (distance <= tolerance))
        for j in near[np.argsort(distance[near])]:
            i = int(j)
            a, b = (Vector(c.co[k]) for k in c.edges[i])
            point = a.lerp(b,float(ts[i]))
            if not multi_cut._occluded(cs, region, rv3d, point, xray) and _reference_visible(context,region,rv3d,point,refs,(a-b).length*.5):
                return 'EDGE', i, multi_cut.ray_edge_t(region, rv3d, a, b, mouse)
    if not edges_only:
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse)
        hit = c.ray(origin, direction)
        if hit is not None:
            point = origin + direction.normalized()*hit[0]
            f = c.bm.faces[hit[1]]
            clearance = max(((Vector(c.co[e.verts[0].index])-Vector(c.co[e.verts[1].index])).length for e in f.edges),default=0)*.5
            if _reference_visible(context,region,rv3d,point,refs,clearance):
                return 'FACE', hit[1], tuple(c.inv @ point)
    return None


def fill_plan(context, region, rv3d, mouse, ob):
    """(ring of vertex indices, world points) for a Shift+click at ``mouse``, or None."""
    global _fill_projection
    from .quad_draw_fill import ScreenFill
    c = next((c for candidate,c in preselect.caches(context) if candidate==ob),None)
    if c is None:
        return None
    key=(region.width,region.height,tuple(map(tuple,rv3d.perspective_matrix)),getattr(c,'revision',0))
    if _fill_projection is None or _fill_projection[0] is not c or _fill_projection[1]!=key:
        xy,front=preselect.project(c.co,rv3d.perspective_matrix,region.width,region.height)
        if c.arrays is not None:
            counts,candidates,shown,groups=c.arrays[4:]
            allowed=c.vok&front&candidates
            groups=[ids[shown[fi]&front[ids].all(axis=1)] for fi,ids in groups]
            screen=ScreenFill(xy,allowed,c.edges,counts,(),world=c.co,groups=groups)
        else:
            allowed=[not v.hide and bool(front[v.index]) and (v.is_boundary or not v.link_faces) for v in c.bm.verts]
            counts=[len(e.link_faces) for e in c.bm.edges]
            faces=[tuple(v.index for v in f.verts) for f in c.bm.faces if not f.hide and all(front[v.index] for v in f.verts)]
            screen=ScreenFill(xy,allowed,c.edges,counts,faces,world=c.co)
        _fill_projection=c,key,screen
    screen=_fill_projection[2]
    refs=reference_objects(context)
    def visible(i):
        point=Vector(c.co[i])
        if multi_cut._occluded([(ob,c)],region,rv3d,point,False):
            return False
        return _reference_visible(context,region,rv3d,point,refs)
    ring=screen.plan(mouse,visible)
    if ring is None:
        return None
    if context.scene.allset_symmetry.on and context.scene.allset_symmetry.about=='TOPOLOGY':
        info=topology_preview(context,ob)
        if info and any(c.bm.verts[i].link_faces and i not in info['pairs'] for i in ring):return None
        from . import quad_draw_reference
        points=[]
        try:
            for i in ring:
                other=info['pairs'].get(i) if info else None
                points.append(ob.matrix_world@c.bm.verts[other].co if other is not None else
                              ob.matrix_world@quad_draw_reference.point(context,ob,c.bm.verts[i].co,'XYZ'.index(context.scene.allset_symmetry.axis)))
        except quad_draw_symmetry.SymmetryError as ex:
            if info:info['message']=str(ex)
            STATE['topology_preview']=None
            return None
        STATE['topology_preview']=('FILL',points)

    return list(ring),[Vector(c.co[i]) for i in ring]


def apply_fill(ob, ring):
    """Make the fill face through vertex indices ``ring`` (``fill_plan``); its dots become plain vertices. Returns the
    face or None."""
    bm = bmesh.from_edit_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    verts = [bm.verts[i] for i in ring]
    face = fill_face(bm, verts)
    if face is None:
        return None
    lay = dot_layer(bm)
    for v in face.verts:
        if lay is not None:
            v[lay] = 0
    for el in (*bm.verts, *bm.edges, *bm.faces):
        el.select = False
    bmesh.update_edit_mesh(ob.data)
    preselect.invalidate()
    return face


def _begin_symmetry(operator,context,ob,coordinate_only=False):
    bm=bmesh.from_edit_mesh(ob.data)
    dot_layer(bm,create=True)  # adding custom data can invalidate BMesh wrappers
    if context.scene.allset_symmetry.on:quad_draw_symmetry.ensure_identity(bm)
    try:
        info=topology_preview(context,ob)
        operator._sym=quad_draw_symmetry.begin(context,ob,bm,coordinate_only=coordinate_only,mapping=info['pairs'] if info and info['pairs'] else None)
        return True
    except quad_draw_symmetry.SymmetryError as ex:
        operator.report({'WARNING'},str(ex))
        operator._sym=None
        return False


def _sync_symmetry(operator,context,finish=False):
    sym=getattr(operator,'_sym',None)
    if sym is None:return True
    try:
        sym.sync()
    except (quad_draw_symmetry.SymmetryError,ValueError,ReferenceError) as ex:
        sym.rollback();operator._sym=None
        operator.report({'WARNING'},str(ex))
        ob=bpy.data.objects.get(operator._ob)
        if ob is not None:bmesh.update_edit_mesh(ob.data)
        preselect.invalidate()
        return False
    _indices(sym.bm)
    if getattr(sym,'disabled_reason',None):operator.report({'WARNING'},sym.disabled_reason)
    if finish:
        sym.close();operator._sym=None
    return True


def _close_symmetry(operator):
    sym=getattr(operator,'_sym',None)
    if sym is not None:sym.close()
    operator._sym=None


def _commit_weld(operator,bm,magnet,source):
    sym=getattr(operator,'_sym',None)
    if sym is None:return magnet.commit(bm,source)
    bm.verts.ensure_lookup_table()
    targets={source[i]:bm.verts[t] for i,t in magnet.pairs.items() if i in source}
    targets.update(sym.seam_targets())
    return sym.weld(targets) if targets else 0


# --- drawing --------------------------------------------------------------------------------------------

def _lines(region, pts, rgb, px, alpha=1.0):
    if len(pts) < 2:
        return
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_float("lineWidth", px)
    shader.uniform_float("color", (*rgb, alpha))
    batch_for_shader(shader, 'LINES', {"pos": pts}).draw(shader)


def _points(pts, rgb, px):
    if not pts:
        return
    shader = gpu.shader.from_builtin('POINT_UNIFORM_COLOR')
    gpu.state.point_size_set(px)
    shader.uniform_float("color", (*rgb, 1.0))
    batch_for_shader(shader, 'POINTS', {"pos": pts}).draw(shader)


def _ring_lines(pts):
    pts = [tuple(p) for p in pts]
    return [q for a, b in zip(pts, pts[1:] + pts[:1]) for q in (a, b)]


def _draw_view():
    context = bpy.context
    try:
        if not tool_active(context):
            # Give native shading back on the first inactive-view redraw, rather
            # than waiting for the slower mesh/dot cleanup timer.
            if ((STATE['overlays'] or _overlay_save_runtime) and not _overlay_saving
                    and context.space_data is not None and context.space_data.type == 'VIEW_3D'):
                if _release_overlay(context.space_data) and context.area is not None:
                    context.area.tag_redraw()
            return
        from ..ui import toolbox
        if toolbox.is_toolbox(context.space_data):
            return
        region = context.region
        scale = _ui_scale(context)
        from . import quad_draw_overlay
        quad_draw_overlay.draw(context)
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        pv = STATE["preview"]
        _points([tuple(p) for p in STATE["snap"]], FILL_RGB, DOT_SIZE*1.5*scale)
        previews=[pv] if pv is not None else []
        if pv is not None and pv[0]=='FILL' and context.scene.allset_symmetry.on and context.scene.allset_symmetry.about=='TOPOLOGY':
            mirrored=STATE.get('topology_preview')
            if mirrored is not None:previews.append(mirrored)
        ob=edit_object(context)
        sym=context.scene.allset_symmetry
        ob=edit_object(context)
        if pv is not None and ob is not None and sym.on and sym.about!='TOPOLOGY' and pv[0] in {'FILL','LOOP','EXTEND','TAB','DELETE'}:
            transform=ob.matrix_world@quad_draw_symmetry.reflection(ob,sym.about,'XYZ'.index(sym.axis))@ob.matrix_world.inverted_safe()
            kind,data=pv
            reflected=[tuple(transform@Vector(p)) for p in data] if kind!='LOOP' else [[tuple(transform@Vector(p)) for p in segment] for segment in data]
            previews.append((kind,reflected))
        for pv in previews:
            kind, data = pv
            if kind == 'FILL':
                _lines(region, _ring_lines(data), FILL_RGB, LINE_PX * scale)
            elif kind == 'LOOP':
                _lines(region, [tuple(p) for s in data for p in s], LOOP_RGB, LINE_PX * scale)
            elif kind in ('DELETE', 'TAB'):
                rgb = DELETE_RGB if kind == 'DELETE' else LOOP_RGB
                pts = [tuple(p) for p in data]
                if len(pts) == 1:
                    _points(pts, rgb, DOT_SIZE * 1.5 * scale)
                elif len(pts) == 2:
                    _lines(region, pts, rgb, LINE_PX * 2 * scale)
                else:
                    _lines(region, _ring_lines(pts), rgb, LINE_PX * 2 * scale)
            elif kind == 'EXTEND':
                _lines(region, [tuple(p) for p in data], FILL_RGB, LINE_PX * scale)
        ob = edit_object(context)
        if ob is not None:
            mw = ob.matrix_world
            bm = bmesh.from_edit_mesh(ob.data)     # keep the wrapper alive while its vertices are read
            _points([tuple(mw @ v.co) for v in dots(bm)], DOT_RGB, DOT_SIZE * scale)
        gpu.state.blend_set('NONE')
    except (ReferenceError, AttributeError, IndexError, ValueError, KeyError):
        pass


def _draw_pixel():
    context = bpy.context
    try:
        if not tool_active(context):
            return
        from ..ui import toolbox
        if toolbox.is_toolbox(context.space_data):
            return
        from . import quad_draw_overlay
        quad_draw_overlay.draw_front(context)
        pv = STATE["preview"]
        if pv is not None and pv[0] == 'WIDTH':
            width = poly_draw.settings(context).qd_strip_width * _ui_scale(context)
            gpu.state.blend_set('ALPHA')
            _lines(context.region, [(*p, 0.0) for p in width_preview(pv[1], width)], FILL_RGB,
                   LINE_PX * _ui_scale(context))
            gpu.state.blend_set('NONE')
            return
        if pv is None or pv[0] != 'BRUSH':
            return
        region = context.region
        cx, cy, r = pv[1]
        pts = [(cx + r * math.cos(a * math.tau / 48), cy + r * math.sin(a * math.tau / 48), 0.0) for a in range(48)]
        gpu.state.blend_set('ALPHA')
        _lines(region, [q for a, b in zip(pts, pts[1:] + pts[:1]) for q in (a, b)], FILL_RGB, 1.5, 0.8)
        gpu.state.blend_set('NONE')
    except (ReferenceError, AttributeError, IndexError, ValueError):
        pass


def _redraw(context):
    if context.area is not None:
        context.area.tag_redraw()


def _view_ok(context):
    r = context.region
    return r is not None and r.type == 'WINDOW' and context.region_data is not None


def _mouse(event):
    return (event.mouse_region_x, event.mouse_region_y)


# --- the Retopology overlay of the owned views, the watcher ---------------------------------------------

# Save the user's overlay values, never the tool's temporary display in a .blend.
_overlay_saving = False
_overlay_save_runtime = {}


def _overlay_values(space):
    ov = space.overlay
    return ov.show_retopology, ov.show_faces, ov.retopology_offset


def _set_overlay_values(space, values):
    ov = space.overlay
    for name, value in zip(('show_retopology', 'show_faces', 'retopology_offset'), values):
        if getattr(ov, name) != value:
            setattr(ov, name, value)


def _release_overlay(space):
    ptr = space.as_pointer()
    original = STATE['overlays'].pop(ptr, None)
    _overlay_save_runtime.pop(ptr, None)
    if original is None:
        return False
    _set_overlay_values(space, original)
    return True


def _overlay_space(ptr):
    # A workspace may have become inactive since the snapshot was captured.
    # Resolve pointers again; retaining RNA references across file/window changes is unsafe.
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == 'VIEW_3D' and space.as_pointer() == ptr:
                    return space
    return None


def _window_uses_quad_draw(win):
    ob = win.view_layer.objects.active
    if ob is None or ob.type != 'MESH' or ob.mode != 'EDIT':
        return False
    tool = win.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
    return tool is not None and tool.idname == TOOL


def _overlay_owner_active(ptr):
    from ..ui import toolbox
    for win in bpy.context.window_manager.windows:
        if not _window_uses_quad_draw(win):
            continue
        for area in win.screen.areas:
            space = area.spaces.active
            if area.type == 'VIEW_3D' and space.as_pointer() == ptr and not toolbox.is_toolbox(space):
                return True
    return False


def _apply_overlay(space, original):
    faces = original[1] and not poly_draw.settings().qd_mesh_color_on
    _set_overlay_values(space, (True, faces, 0.0))


def sync_overlays(context=None):
    """Apply display overrides only while drawing; save handlers suspend them."""
    if _overlay_saving:
        return
    if context is not None:
        from ..ui import toolbox
        if not tool_active(context) or toolbox.is_toolbox(context.space_data):
            return
        space = context.space_data
        ptr = space.as_pointer()
        if ptr not in STATE['overlays']:
            # A saved workspace can resume Quad Draw without invoking Start.
            STATE['overlays'][ptr] = _overlay_values(space)
            ob = edit_object(context)
            name = ob.name if ob else None
            if STATE['ob'] != name:
                STATE['created'] = None
            STATE.update(ob=name, timer=True)
            if not bpy.app.timers.is_registered(_watch):
                bpy.app.timers.register(_watch, first_interval=0.5)
        _apply_overlay(space, STATE['overlays'][ptr])
        return
    for ptr, original in STATE['overlays'].items():
        space = _overlay_space(ptr)
        if space is not None:
            _apply_overlay(space, original)


@bpy.app.handlers.persistent
def _overlay_save_pre(*_args):
    global _overlay_saving
    if _overlay_saving:
        return
    _overlay_saving = True
    _overlay_save_runtime.clear()
    for ptr, original in STATE['overlays'].items():
        space = _overlay_space(ptr)
        if space is not None:
            _overlay_save_runtime[ptr] = _overlay_values(space)
            _set_overlay_values(space, original)


@bpy.app.handlers.persistent
def _overlay_save_post(*_args):
    """Resume the visible tool after successful saves and save failures alike."""
    global _overlay_saving
    pending = dict(_overlay_save_runtime)
    _overlay_save_runtime.clear()
    _overlay_saving = False
    for ptr, runtime in pending.items():
        space = _overlay_space(ptr)
        original = STATE['overlays'].get(ptr)
        if space is None or original is None:
            continue
        if _overlay_owner_active(ptr):
            _set_overlay_values(space, runtime)
        else:
            _set_overlay_values(space, original)
            STATE['overlays'].pop(ptr, None)


def _restore_inactive_overlays():
    for ptr, original in list(STATE['overlays'].items()):
        if _overlay_owner_active(ptr):
            continue
        space = _overlay_space(ptr)
        if space is not None:
            _set_overlay_values(space, original)
        STATE['overlays'].pop(ptr, None)
        _overlay_save_runtime.pop(ptr, None)


def _restore_overlays():
    global _overlay_saving
    for ptr, original in list(STATE['overlays'].items()):
        space = _overlay_space(ptr)
        if space is not None:
            _set_overlay_values(space, original)
    STATE['overlays'].clear()
    _overlay_save_runtime.clear()
    _overlay_saving = False
    global _pick_projection, _fill_projection, _topology_preview,_component_loop_cache
    _component_loop_cache=None
    _pick_projection = None
    _fill_projection = None
    _topology_preview=None;STATE['topology_info']=None;STATE['topology_hover']=None;STATE['topology_preview']=None
    STATE["snap"] = []
    from . import quad_draw_overlay
    quad_draw_overlay.clear()
    from . import quad_draw_relax
    quad_draw_relax.clear();STATE['relax_area']=None;STATE['delete_edges']=None
    from . import quad_draw_reference
    quad_draw_reference.clear()
    preselect.invalidate()


def _active_anywhere():
    from ..ui import toolbox
    wm = bpy.context.window_manager
    for win in wm.windows if wm else ():
        if _window_uses_quad_draw(win) and any(
                area.type == 'VIEW_3D' and not toolbox.is_toolbox(area.spaces.active)
                for area in win.screen.areas):
            return True
    return False


def _watch():
    """While Quad Draw is the tool, nothing; once left: overlays back, an untouched new mesh removed, dots gone."""
    if _overlay_saving:
        return 0.5
    try:
        _restore_inactive_overlays()
        if _active_anywhere():
            return 0.5
    except (ReferenceError, AttributeError):
        pass
    _restore_overlays()
    STATE["preview"] = None
    _drop_dots(STATE["ob"])
    name = STATE["created"]
    STATE["created"] = None
    ob = bpy.data.objects.get(name) if name else None
    if ob is not None and ob.mode != 'EDIT' and ob.type == 'MESH' and not ob.data.vertices:
        me = ob.data
        bpy.data.objects.remove(ob)
        if me.users == 0:
            bpy.data.meshes.remove(me)
    STATE["timer"] = False
    return None


def _drop_dots(name):
    """Leaving Quad Draw clears its dots and the dot layer (Maya's dots live only in the tool)."""
    ob = bpy.data.objects.get(name) if name else None
    if ob is None or ob.type != 'MESH':
        return
    me = ob.data
    if ob.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(me)
        clear_dots(bm)
        for name in (DOT_LAYER,)+( () if quad_draw_symmetry.SEED in me else (quad_draw_symmetry.IDENTITY,)):
            lay=bm.verts.layers.int.get(name)
            if lay is not None:bm.verts.layers.int.remove(lay)
        bmesh.update_edit_mesh(me)
        return
    if DOT_LAYER not in me.attributes and quad_draw_symmetry.IDENTITY not in me.attributes:
        return
    bm = bmesh.new()
    bm.from_mesh(me)
    if clear_dots(bm):
        bm.to_mesh(me)
    bm.free()
    for name in (DOT_LAYER,)+( () if quad_draw_symmetry.SEED in me else (quad_draw_symmetry.IDENTITY,)):
        attr = me.attributes.get(name)
        if attr is not None:me.attributes.remove(attr)


# --- undo / load resets ---------------------------------------------------------------------------------

@bpy.app.handlers.persistent
def _geometry_reset(_dummy):
    global _pick_projection,_fill_projection,_topology_preview,_component_loop_cache
    _component_loop_cache=None
    _pick_projection=_fill_projection=None
    _topology_preview=None;STATE['topology_info']=None;STATE['topology_hover']=None;STATE['topology_preview']=None
    STATE['preview']=None;STATE['snap']=[]
    from . import quad_draw_overlay
    quad_draw_overlay.clear();preselect.invalidate()
    from . import quad_draw_relax
    quad_draw_relax.clear();STATE['relax_area']=None;STATE['delete_edges']=None
    from . import quad_draw_reference
    quad_draw_reference.clear()


@bpy.app.handlers.persistent
def _file_reset(_dummy):
    _restore_overlays();_geometry_reset(None)
    STATE.update(ob=None,created=None,timer=False)
    if bpy.app.timers.is_registered(_watch):bpy.app.timers.unregister(_watch)


@bpy.app.handlers.persistent
def _restore_topology_state(_dummy):
    """Edit Undo restores custom data, but does not restore Scene/ID properties."""
    ob=edit_object(bpy.context)
    if ob is None:return
    state=bpy.context.scene.allset_symmetry
    if state.about!='TOPOLOGY':return
    bm=bmesh.from_edit_mesh(ob.data);flags=bm.verts.layers.int.get(quad_draw_symmetry.SEED_LAYER)
    if flags is None:return
    ids=quad_draw_symmetry.seed_ids(ob,bm)
    enabled=len(ids)==2 and any(v[flags]&2 for v in bm.verts)
    if len(ids)==2:ob.data[quad_draw_symmetry.SEED]=list(ids)
    elif quad_draw_symmetry.SEED in ob.data:del ob.data[quad_draw_symmetry.SEED]
    state.on=enabled
    from . import symmetry
    symmetry.apply(state,[ob]);clear_topology_preview()
