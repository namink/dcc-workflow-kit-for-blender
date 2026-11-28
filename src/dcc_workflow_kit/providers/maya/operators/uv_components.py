# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya UV components on Blender's UV Editor: ``allset.uv_component`` (open the UV Editor, Vertex / Edge / Face / UV /
UV Edge / UV Face / UV Shell), the kit's UV component mode per scene (``in_uv_mode``), the mesh selection kept across
it (``remember_mesh_selection``, ``leave_uv_mode``), ``find_uv_editor`` / ``prepare`` and ``mesh_selection_wanted``
(which selection a UV edge command reads). The UV Shell mask itself is operators/uv_shell_select.py.
"""

import bmesh
import bpy
from bpy.app.handlers import persistent
from bpy.props import EnumProperty

from .. import compat
from .uv_islands import _edit_meshes, picked_anywhere, sync


def _in_uv_editor(context):
    from ..ui import shelf          # the Status Line / Shelf strips are Image Editors too, never the UV Editor
    area = getattr(context, "area", None)
    return area is not None and area.ui_type == 'UV' and not shelf.is_kit_row(area.spaces.active)


def mesh_selection_wanted(context):
    """True when a UV edge / UV command reads the mesh selection (else the per-corner UV selection). Maya has one
    component selection for the viewport and the UV Editor: with UV Sync Selection off, a command run outside the
    UV Editor and outside the kit's UV component mode (the main UV menu or the hotbox in the 3D View) takes the
    edges / vertices the 3D View shows selected when no UV is picked."""
    if sync(context):
        return True
    if in_uv_mode(context.scene) or _in_uv_editor(context):
        return False
    return not picked_anywhere(context, synced=False)


# --- UV Editor and UV components --------------------------------------------------------------------

COMPONENTS = (('VERTEX', "Vertex", "Mesh vertices (UV Sync Selection on)"),
              ('EDGE', "Edge", "Mesh edges (UV Sync Selection on)"),
              ('FACE', "Face", "Mesh faces (UV Sync Selection on)"),
              ('UV', "UV", "UVs picked apart from the mesh (UV Sync Selection off)"),
              ('UV_EDGE', "UV Edge", "UV edges picked apart from the mesh (UV Sync Selection off)"),
              ('UV_FACE', "UV Face", "UV faces picked apart from the mesh (UV Sync Selection off)"),
              ('SHELL', "UV Shell", "Maya UV Shell mask: a click / box picks whole UV shells (faces), 3D View and UV Editor"),
              ('OPEN', "Open", "Only open the UV Editor"))

# UV-only components: Blender's UV select mode with UV Sync Selection off
UV_SELECT_MODES = {'UV': 'VERTEX', 'UV_EDGE': 'EDGE', 'UV_FACE': 'FACE'}



def find_uv_editor(context):
    from ..ui import shelf          # the Status Line / Shelf strips are Image Editors too, never the UV Editor
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.ui_type == 'UV' and not shelf.is_kit_row(area.spaces.active):
                return win, area
    return None, None


def in_uv_editor(context):
    from ..ui import shelf
    area = context.area
    return area is not None and area.ui_type == 'UV' and not shelf.is_kit_row(area.spaces.active)


def set_uv_editor_tool(context, idname, tries=20):
    """Pick the UV Editor tool ``idname`` from anywhere (a menu run over the 3D View, the shelf): the tool is set in
    the open UV Editor, which opens first when there is none (the UV tool works in the UV Editor)."""
    win, area = find_uv_editor(context)
    if area is None:
        res = bpy.ops.allset.open_editor(ui_type='UV')
        if 'FINISHED' not in res:
            return res
        win, area = find_uv_editor(context)
    if area is None:
        # the new window opens on a later tick: set the tool once it is there
        def later(left=[tries]):
            w, a = find_uv_editor(bpy.context)
            if a is not None:
                _tool_set_in(w, a, idname)
                return None
            left[0] -= 1
            return 0.1 if left[0] > 0 else None
        bpy.app.timers.register(later, first_interval=0.1)
        return {'FINISHED'}
    return _tool_set_in(win, area, idname)


def _tool_set_in(win, area, idname):
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
        return bpy.ops.wm.tool_set_by_id(name=idname, space_type='IMAGE_EDITOR')


def prepare(context):
    """Edit mode on the active mesh with UV Sync Selection on (the UVs show in the UV Editor at once)."""
    ob = context.view_layer.objects.active
    if ob is None or ob.type != 'MESH':
        return False
    if ob.mode != 'EDIT' and not ob.visible_get():
        return False            # a hidden mesh can't enter Edit Mode: the UV Editor just opens
    if ob.mode != 'EDIT':
        if not ob.select_get():
            ob.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
    sync_on(context.scene.tool_settings)
    return True


def sync_on(ts):
    """UV Sync Selection on, the UV selection drawn the way the component takes UVs (``match_sticky``)."""
    ts.use_uv_select_sync = True
    match_sticky(ts)


def match_sticky(ts):
    """With UV Sync Selection on, the UVs a pick shows as selected, like Maya's components: a picked vertex / edge is
    drawn (and used) on every shell that has it (sticky Shared Vertex), a picked face shows only its own UVs
    (Blender's sticky Shared Location, which keeps the clicked shell's UVs apart). Call after a mesh select mode
    change; nothing while UV Sync Selection is off."""
    if not ts.use_uv_select_sync:
        return
    vert, edge, _face = ts.mesh_select_mode
    ts.uv_sticky_select_mode = 'SHARED_VERTEX' if vert or edge else 'SHARED_LOCATION'


# Blender's own ways of changing the select mode (header buttons, keys in Blender mode, a script) keep the sticky
# mode matched too
_WATCH = object()


def _on_select_mode():
    try:
        match_sticky(bpy.context.scene.tool_settings)
    except (AttributeError, ReferenceError):
        pass


def _subscribe():
    bpy.msgbus.clear_by_owner(_WATCH)
    for name in ("mesh_select_mode", "use_uv_select_sync"):
        bpy.msgbus.subscribe_rna(key=(bpy.types.ToolSettings, name), owner=_WATCH, args=(), notify=_on_select_mode)


@persistent
def _on_load(*_args):
    _subscribe()


def register_sticky_watch():
    _subscribe()
    bpy.app.handlers.load_post.append(_on_load)


def unregister_sticky_watch():
    bpy.msgbus.clear_by_owner(_WATCH)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)


def sync_off(ts):
    """UV Sync Selection off for the kit's UV components; sticky back to Blender's Shared Location (UVs at one place
    of one vertex are picked together)."""
    ts.use_uv_select_sync = False
    ts.uv_sticky_select_mode = 'SHARED_LOCATION'


# Maya keeps each component type's selection: F12 (UV) and back to F9 / F10 / F11 shows the vertices / edges / faces
# selected before. Kit UV mode selects every face (sync off draws only selected faces' UVs), so the mesh selection
# from before it is kept here and put back when a mesh component mode comes back (issue #80).
_MESH_SELECTION = {}     # object name -> ((verts, edges, faces) counts, selected vert / edge / face indices)

# Scenes the kit's UV component (F12, the UV / UV Edge / UV Face / island modes) put in UV mode: the 3D View then
# shows the UV selection. UV Sync Selection off alone doesn't mean UV mode (the Maya layout scene starts with it off).
_UV_MODE = set()         # scene pointers


def in_uv_mode(scene):
    """The kit's UV component mode is on in ``scene`` (and UV Sync Selection is still off)."""
    return (scene is not None and scene.as_pointer() in _UV_MODE
            and not scene.tool_settings.use_uv_select_sync)


def forget_uv_mode():
    """After a file load: scene pointers may be reused."""
    _UV_MODE.clear()


def _counts(bm):
    return len(bm.verts), len(bm.edges), len(bm.faces)


def remember_mesh_selection(context):
    _MESH_SELECTION.clear()
    for ob in _edit_meshes(context):
        bm = bmesh.from_edit_mesh(ob.data)
        _MESH_SELECTION[ob.name] = (_counts(bm), [v.index for v in bm.verts if v.select],
                                    [e.index for e in bm.edges if e.select], [f.index for f in bm.faces if f.select])


def forget_mesh_selection():
    _MESH_SELECTION.clear()


def leave_uv_mode(context):
    """Maya F9 / F10 / F11 after F12 / Alt+F12: UV Sync Selection back on and the mesh selection from before UV mode
    back (when the mesh still has the same element counts)."""
    ts = context.scene.tool_settings
    _UV_MODE.discard(context.scene.as_pointer())
    from . import uv_shell_select
    was_shell = uv_shell_select.flag(context)
    uv_shell_select.set_flag(context, False)      # another component mode ends the UV Shell mask
    if ts.use_uv_select_sync and not was_shell:
        sync_on(ts)
        return
    sync_on(ts)
    for ob in _edit_meshes(context):
        saved = _MESH_SELECTION.get(ob.name)
        bm = bmesh.from_edit_mesh(ob.data)
        if saved is None or saved[0] != _counts(bm):
            continue
        seqs = (bm.verts, bm.edges, bm.faces)
        for seq in seqs:      # all off first: a face's / edge's ``select = False`` also drops its vertices
            for el in seq:
                el.select = False
        for seq, chosen in zip(seqs, saved[1:]):
            seq.ensure_lookup_table()
            for i in chosen:
                seq[i].select = True
        bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
    _MESH_SELECTION.clear()


def set_component(context, mode):
    """'SHELL' = Maya's UV Shell mask (operators/uv_shell_select.py); 'ISLAND' = Blender's UV island
    selection in the UV Editor (UV Sync off; Move UV Shell)."""
    from . import uv_shell_select
    ts = context.scene.tool_settings
    if mode == 'SHELL':
        _UV_MODE.discard(context.scene.as_pointer())
        if not _MESH_SELECTION:       # from a mesh component mode: F9 / F10 / F11 bring its selection back (#80)
            remember_mesh_selection(context)
        uv_shell_select.enter(context)
        return
    uv_shell_select.set_flag(context, False)
    if mode in ('VERTEX', 'EDGE', 'FACE'):
        leave_uv_mode(context)
        ts.mesh_select_mode = (mode == 'VERTEX', mode == 'EDGE', mode == 'FACE')
        match_sticky(ts)
    elif mode in ('UV', 'UV_EDGE', 'UV_FACE', 'ISLAND'):
        sync_off(ts)
        _UV_MODE.add(context.scene.as_pointer())
        # the 3D View shows UVs as points now: Blender's face select mode would add its face centre dots (X-ray,
        # wireframe), which Maya's UV mode doesn't show. F9 / F10 / F11 set the mesh mode again on the way out.
        if ts.mesh_select_mode[2] and not ts.mesh_select_mode[0]:
            ts.mesh_select_mode = (True, False, False)
        compat.set_uv_island_mode(ts, mode == 'ISLAND')
        if mode in UV_SELECT_MODES:
            ts.uv_select_mode = UV_SELECT_MODES[mode]
        # without sync Blender draws only the selected faces' UVs: Maya shows them all
        for ob in _edit_meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            for f in bm.faces:
                if not f.hide:
                    f.select_set(True)
            bmesh.update_edit_mesh(ob.data)


class ALLSET_OT_uv_component(bpy.types.Operator):
    """Maya UV components: open the UV Editor (once) and pick Vertex / Edge / Face / UV / UV Shell there.
    Blender picks UVs in the UV Editor only"""
    bl_idname = "allset.uv_component"
    bl_label = "UV Component"
    bl_options = {'UNDO'}

    mode: EnumProperty(items=COMPONENTS, name="Component", default='UV')

    @classmethod
    def poll(cls, context):
        ob = context.view_layer.objects.active if context.view_layer else None
        target = getattr(context.window_manager, "allset_mm_target", "")
        return (ob is not None and ob.type == 'MESH') or bool(target)

    def execute(self, context):
        target = bpy.data.objects.get(getattr(context.window_manager, "allset_mm_target", "") or "")
        if target is not None and target.type == 'MESH' and context.mode == 'OBJECT':
            for o in context.selected_objects:
                if o is not target:
                    o.select_set(False)
            target.select_set(True)
            context.view_layer.objects.active = target
        ts = context.scene.tool_settings
        ob = context.view_layer.objects.active
        if ob is not None and ob.type == 'MESH' and ob.mode != 'EDIT' and not ob.visible_get():
            # a hidden object: Maya converts silently; Blender can't enter
            # edit mode on it, so only the component type is set
            if self.mode in ('VERTEX', 'EDGE', 'FACE'):
                ts.mesh_select_mode = (self.mode == 'VERTEX', self.mode == 'EDGE', self.mode == 'FACE')
            return {'FINISHED'}
        # coming from a mesh component mode (or object mode): keep its selection for F9 / F10 / F11 (#80)
        remember = self.mode in ('UV', 'UV_EDGE', 'UV_FACE') and (context.mode != 'EDIT_MESH' or ts.use_uv_select_sync)
        if self.mode in ('VERTEX', 'EDGE', 'FACE') and context.mode == 'EDIT_MESH':
            leave_uv_mode(context)     # before prepare() turns UV Sync Selection on
        if not prepare(context):
            self.report({'WARNING'}, "Select a mesh")
            return {'CANCELLED'}
        if remember:
            remember_mesh_selection(context)
        # open the editor first: its prepare() turns UV Sync Selection on, which undid F12's UV mode the first time
        # (issue #80)
        # Maya's UV Shell mask picks shells in the 3D View too: no UV Editor needed
        if (self.mode != 'SHELL' and find_uv_editor(context)[1] is None and context.window is not None
                and not bpy.app.background):
            bpy.ops.allset.open_editor(ui_type='UV')
        if self.mode != 'OPEN':
            set_component(context, self.mode)
        return {'FINISHED'}
