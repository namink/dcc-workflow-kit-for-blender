# SPDX-License-Identifier: GPL-3.0-or-later
"""What the Status Line buttons do: selection masks (kept across File > New / Open), Object / Component selection
mode, snap toggles (kept across undo / redo), the symmetry list, Render Settings / Light Editor / IPR. Also the 3D
View lookups the kit shares (``main_view3d``, ``view3d_space``, ``all_view3d_spaces``). Drawn and registered by
status_line.py, which also re-exports these names.
"""

import bpy
from bpy.props import EnumProperty

from . import draw_safe
from .. import i18n

# --- 3D View helpers ----------------------------------------------------------------

def main_view3d(screen=None):
    """(area, WINDOW region) of the largest 3D View in ``screen`` (or the active screen)."""
    screen = screen or bpy.context.screen
    best = None
    for area in (screen.areas if screen else ()):
        if area.type == 'VIEW_3D' and (best is None or area.width * area.height > best.width * best.height):
            best = area
    if best is None:
        return None, None
    return best, next((r for r in best.regions if r.type == 'WINDOW'), None)


def view3d_space(context):
    """The 3D View a Maya Display item reads and sets: the one the menu is drawn in, else the largest of
    the screen (the main menu bar is in the top bar), else the largest of the first window that has one (a kit
    window such as Normals Size has none of its own). Maya keeps polygon display on the meshes; Blender keeps it on
    each 3D View's overlays. None without a 3D View."""
    space = getattr(context, "space_data", None)
    if space is not None and space.type == 'VIEW_3D':
        return space
    area, _region = main_view3d(getattr(context, "screen", None))
    wm = getattr(context, "window_manager", None)
    for window in (wm.windows if wm is not None and area is None else ()):
        area, _region = main_view3d(window.screen)
        if area is not None:
            break
    return area.spaces.active if area is not None else None


def all_view3d_spaces():
    """Every 3D View space in every screen (Maya selection masks are global)."""
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    yield space


# --- selection masks -------------------------------------------

# Maya object mask -> Blender SpaceView3D.show_object_select_<type>; None = no equivalent.
OBJECT_MASKS = (
    ("HANDLES", "Select by handle object type", 'RESTRICT_SELECT_OFF', None),
    ("JOINTS", "Select by joint object type (armatures)", 'OUTLINER_OB_ARMATURE', ("armature",)),
    ("CURVES", "Select by curve object type", 'OUTLINER_OB_CURVE', ("curve", "font", "curves")),
    ("SURFACES", "Select by surface object type (meshes, NURBS)", 'OUTLINER_OB_MESH',
     ("mesh", "surf", "meta", "pointcloud", "volume")),
    ("DEFORMERS", "Select by deformation object type (lattices)", 'OUTLINER_OB_LATTICE', ("lattice",)),
    ("DYNAMICS", "Select by dynamic object type", 'OUTLINER_OB_FORCE_FIELD', None),
    ("RENDERING", "Select by rendering object type (cameras, lights)", 'OUTLINER_OB_LIGHT',
     ("camera", "light")),
    ("MISC", "Select by miscellaneous object type (locators, empties)", 'OUTLINER_OB_EMPTY',
     ("empty", "speaker", "light_probe", "grease_pencil")),
)
_MASK_TYPES = {m[0]: m[3] for m in OBJECT_MASKS}


def mask_on(space, group):
    return all(getattr(space, f"show_object_select_{t}") for t in _MASK_TYPES[group])


def set_mask(group, value):
    for space in all_view3d_spaces():
        for t in _MASK_TYPES[group]:
            setattr(space, f"show_object_select_{t}", value)


class ALLSET_OT_select_mask(bpy.types.Operator):
    """Toggle whether this kind of object can be selected (all 3D Views)"""
    bl_idname = "allset.select_mask"
    bl_label = "Selection Mask"
    bl_options = {'INTERNAL'}

    group: EnumProperty(items=[(m[0], m[0].title(), m[1]) for m in OBJECT_MASKS if m[3]])

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return next(m[1] for m in OBJECT_MASKS if m[0] == props.group)

    def execute(self, context):
        area, _r = main_view3d(context.screen)
        spaces = [area.spaces.active] if area else list(all_view3d_spaces())[:1]
        if not spaces:
            return {'CANCELLED'}
        set_mask(self.group, not mask_on(spaces[0], self.group))
        return {'FINISHED'}



# Maya keeps its selection masks across File > New / Open (they are session state).
# Blender keeps the object select filters in each file's screens and the mesh
# select mode in its scene, so a load would replace them: remember them before the load and put them back after.
MASK_FLAGS = tuple(sorted({t for m in OBJECT_MASKS if m[3] for t in m[3]}))
_carried = {}


def session_masks(context=None):
    """The current masks: {type: selectable} of the main 3D View and the mesh select mode (or None)."""
    context = context or bpy.context
    area, _r = main_view3d(context.screen) if context.screen else (None, None)
    space = area.spaces.active if area else next(iter(all_view3d_spaces()), None)
    scene = context.scene
    if space is None and scene is None:
        return None
    return {"objects": {t: getattr(space, f"show_object_select_{t}") for t in MASK_FLAGS} if space else None,
            "mesh": tuple(scene.tool_settings.mesh_select_mode) if scene else None}


def apply_masks(masks):
    if not masks:
        return
    if masks["objects"]:
        for space in all_view3d_spaces():
            for t, value in masks["objects"].items():
                setattr(space, f"show_object_select_{t}", value)
    if masks["mesh"]:
        for scene in bpy.data.scenes:
            scene.tool_settings.mesh_select_mode = masks["mesh"]


@bpy.app.handlers.persistent
def _masks_before_load(*_args):
    try:
        _carried["masks"] = session_masks()
    except (AttributeError, ReferenceError):
        _carried.pop("masks", None)


@bpy.app.handlers.persistent
def _masks_after_load(*_args):
    apply_masks(_carried.pop("masks", None))

# --- selection mode -----------------------------------------------

class ALLSET_OT_select_mode(bpy.types.Operator):
    """Maya selection mode: Object (object mode) or Component (edit mode)"""
    bl_idname = "allset.select_mode"
    bl_label = "Selection Mode"
    bl_options = {'UNDO'}

    mode: EnumProperty(items=(("OBJECT", "Object", "Select by object type (object mode)"),
                              ("COMPONENT", "Component", "Select by component type (edit mode)")))

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return {"OBJECT": "Select by object type (Object Mode)",
                "COMPONENT": "Select by component type (Edit Mode)"}[props.mode]

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        target = 'OBJECT' if self.mode == "OBJECT" else 'EDIT'
        if context.active_object.mode != target:
            from ..operators import maya_errors
            if target == 'EDIT' and maya_errors.refuse_hidden(self, context.active_object):     # #187
                return {'CANCELLED'}
            bpy.ops.object.mode_set(mode=target)
        return {'FINISHED'}


# --- snapping (hold keys share these settings: operators/hold.py) ----

SNAPS = (
    ("GRID", "Snap to grids (hold X)", 'SNAP_GRID', {'GRID'}),
    ("CURVE", "Snap to curves (hold C)", 'SNAP_EDGE', {'EDGE'}),
    ("POINT", "Snap to points (hold V)", 'SNAP_VERTEX', {'VERTEX'}),
    ("PROJECTED", "Snap to projected center", 'PIVOT_MEDIAN', None),
    ("PLANE", "Snap to view planes", 'VIEW_PERSPECTIVE', None),
    ("LIVE", "Snap to the surface under the cursor (Make Live)", 'SNAP_FACE', {'FACE_PROJECT'}),
)
_SNAP_ELEMENTS = {s[0]: s[3] for s in SNAPS}


def snap_on(ts, name):
    elements = _SNAP_ELEMENTS[name]
    return elements is not None and ts.use_snap and elements <= set(ts.snap_elements)


def toggle_snap(ts, name):
    """Status Line snap button: add/remove its element; snapping off when none is left."""
    current = set(ts.snap_elements) if ts.use_snap else set()
    elements = _SNAP_ELEMENTS[name]
    new = current - elements if snap_on(ts, name) else current | elements
    if new:
        ts.snap_elements = new
        ts.use_snap = True
        # Maya snaps the Move tool whenever a snap button is on: an Affect flag left off (Step Snap Off in
        # older kit files, or a file saved that way) would make the button look on while nothing snaps (#139)
        from ..operators import snap_align
        snap_align.settle_affect(ts)
    else:
        ts.use_snap = False


class ALLSET_OT_snap_toggle(bpy.types.Operator):
    """Toggle a Maya snap mode"""
    bl_idname = "allset.snap_toggle"
    bl_label = "Snap Toggle"
    # Maya's snap toggles are not undoable (snapMode pushes no undo step):
    # no undo step here, and undo / redo keep the current snap state (``_keep_snap_pre`` / ``_keep_snap_post``)
    bl_options = {'INTERNAL'}

    snap: EnumProperty(items=[(s[0], s[0].title(), s[1]) for s in SNAPS if s[3]])

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return next(s[1] for s in SNAPS if s[0] == props.snap)

    def execute(self, context):
        toggle_snap(context.scene.tool_settings, self.snap)
        return {'FINISHED'}


# Blender's memfile undo restores the scene's tool settings with everything else, so an undo after a snap toggle
# would switch the snap back (Issue #155). The state from before the undo / redo is put back from a 0 s
# timer like the current frame (ui/time_slider.py ``restore_frame``).
_KEEP_SNAP = {}


@bpy.app.handlers.persistent
def _keep_snap_pre(*_args):
    scene = bpy.context.scene
    if scene is not None:
        ts = scene.tool_settings
        _KEEP_SNAP["state"] = (scene.name, ts.use_snap, set(ts.snap_elements))


@bpy.app.handlers.persistent
def _keep_snap_post(*_args):
    if "state" in _KEEP_SNAP and not bpy.app.timers.is_registered(restore_snap):
        bpy.app.timers.register(restore_snap, first_interval=0.0)


def restore_snap():
    """Put the Status Line snap state from before the undo / redo back (None: timer done)."""
    name, on, elements = _KEEP_SNAP.pop("state", (None, None, None))
    scene = bpy.context.scene
    if scene is None or scene.name != name:
        return None
    ts = scene.tool_settings
    if elements and set(ts.snap_elements) != elements:
        ts.snap_elements = elements
    if ts.use_snap != on:
        ts.use_snap = on
    return None


_SNAP_UNDO_HANDLERS = (("undo_pre", _keep_snap_pre), ("redo_pre", _keep_snap_pre),
                       ("undo_post", _keep_snap_post), ("redo_post", _keep_snap_post))


# --- symmetry (operators/symmetry.py) ------

class ALLSET_MT_symmetry(bpy.types.Menu):
    """Maya symmetry modes (Status Line ▾ list)"""
    bl_idname = "ALLSET_MT_symmetry"
    bl_label = "Symmetry"

    def draw(self, context):
        from ..operators import symmetry
        current = symmetry.mode_of(symmetry.state(context.scene))
        layout = self.layout
        for mode, text in symmetry.MODES:
            draw_safe.op(layout, "allset.symmetry", text=text,
                         icon='RADIOBUT_ON' if mode == current else 'RADIOBUT_OFF').mode = mode


def draw_symmetry(layout, context):
    """▾ list with the mode text + a toggle that is blue (pressed) while symmetry is on.

    Maya: LMB ▾ = list, MMB = toggle, the text box turns blue when on.
    A Blender menu button has no MMB action, so the toggle is its own button.
    """
    from ..operators import symmetry
    sym = symmetry.state(context.scene)
    row = layout.row(align=True)
    draw_safe.op(row, "allset.symmetry", text="", icon='MOD_MIRROR', depress=sym.on).mode = "TOGGLE"
    sub = row.row(align=True)
    sub.ui_units_x = 6
    sub.menu(ALLSET_MT_symmetry.bl_idname, text=symmetry.label(sym), icon='DOWNARROW_HLT')


TRANSFORM_TOOLS = ("builtin.move", "builtin.rotate", "builtin.scale", "builtin.transform",
                   "builtin.select", "builtin.select_box", "builtin.select_circle", "builtin.select_lasso")


def draw_tool_symmetry(self, context):
    """Maya Move/Rotate/Scale Tool Settings "Symmetry Settings" (edit mesh only)."""
    if context.mode != 'EDIT_MESH':
        return
    tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    if tool is None or tool.idname not in TRANSFORM_TOOLS:
        return
    layout = self.layout
    layout.separator()
    layout.label(text="Symmetry Settings")
    draw_symmetry(layout, context)


# --- render -----------------------------------------------------------

def _properties_area(screen):
    """A Properties editor of ``screen`` that is not the Tool Settings dock."""
    from . import maya_dock, tool_dock
    return next((a for a in (screen.areas if screen else ())
                 if a.type == 'PROPERTIES' and not tool_dock.is_dock(a) and maya_dock.role(a) is None), None)


def show_properties(screen, context_name):
    """Switch a Properties editor to a tab; False if the screen has none."""
    area = _properties_area(screen)
    if area is None:
        return False
    try:
        area.spaces.active.context = context_name
    except TypeError:  # tab not available (no active object etc.)
        return False
    return True


class ALLSET_OT_render_settings(bpy.types.Operator):
    """Open Blender's render settings (Properties > Render) in a new window, like Maya's Render Settings window"""
    bl_idname = "allset.render_settings"
    bl_label = "Render Settings"

    def execute(self, context):
        from ..operators import menu_extras
        from . import window_places
        window = context.window
        area = max(window.screen.areas, key=lambda a: a.width * a.height, default=None) if window else None
        if area is not None:
            new = menu_extras.open_window(context, area, "render_settings")
            if new is not None:
                new.screen.areas[0].ui_type = 'PROPERTIES'
                menu_extras.properties_tab_later(new, 'RENDER')
                return {'FINISHED'}
            if window_places.deferred():     # opens on a later tick
                return {'FINISHED'}
        # no new window (background): switch a Properties editor of the screen instead
        return {'FINISHED'} if show_properties(context.screen, 'RENDER') else {'CANCELLED'}


class ALLSET_OT_light_editor(bpy.types.Operator):
    """Open an Outliner window that lists only the scene's lights (Blender has no Light Editor)"""
    bl_idname = "allset.light_editor"
    bl_label = "Light Editor"

    def execute(self, context):
        from ..operators import menu_extras
        from . import window_places
        window = context.window
        area = max(window.screen.areas, key=lambda a: a.width * a.height, default=None) if window else None
        if area is None:
            return {'CANCELLED'}
        new = menu_extras.open_window(context, area, "light_editor")
        if new is None:
            if not window_places.deferred():     # opens on a later tick
                self.report({'ERROR'}, "Could not open a new window")
            return {'CANCELLED'}
        target = new.screen.areas[0]
        target.ui_type = 'OUTLINER'
        space = target.spaces.active
        space.display_mode = 'VIEW_LAYER'
        space.use_filter_object = True
        for name in ("mesh", "armature", "empty", "camera", "others", "grease_pencil"):
            if hasattr(space, "use_filter_object_" + name):
                setattr(space, "use_filter_object_" + name, False)
        space.use_filter_object_light = True
        return {'FINISHED'}


class ALLSET_OT_ipr_toggle(bpy.types.Operator):
    """IPR: interactive render in its own window, looking where the main view looks; click again to close it"""
    bl_idname = "allset.ipr_toggle"
    bl_label = "IPR Render"

    def execute(self, context):
        from . import ipr_window, window_places
        if ipr_window.is_open():
            ipr_window.close()
            return {'FINISHED'}
        area, _r = main_view3d(context.screen)
        if area is None:
            return {'CANCELLED'}
        if context.window is None or bpy.app.background:
            ipr_toggle(area.spaces.active)       # no window to open: the viewport itself
            return {'FINISHED'}
        if ipr_window.open_window(context, area) is None:
            if not window_places.deferred():     # opens on a later tick
                self.report({'ERROR'}, "Could not open a new window")
            return {'CANCELLED'}
        return {'FINISHED'}


def _ipr_on(space):
    """The Status Line IPR button looks pressed while the IPR window is open (no window: the viewport's Rendered)."""
    from . import ipr_window
    if ipr_window.is_open():
        return True
    return bool(space) and bpy.app.background and space.shading.type == 'RENDERED'


def ipr_toggle(space):
    """IPR on = Rendered shading; off = the shading the view had before (Wireframe stays Wireframe, #24)."""
    from . import panel_menus
    if space.shading.type == 'RENDERED':
        panel_menus.leave_rendered(space)
    else:
        panel_menus.enter_rendered(space)
