# SPDX-License-Identifier: GPL-3.0-or-later
"""The buttons under the Tool Box's tools (``ALLSET_PT_toolbox_layouts``): Maya's quick layouts (Single
Perspective, Four View; Front/Persp greyed), the Outliner toggle (docks an Outliner beside the column, or closes the
docked / floating one) and command Search in the main viewport; also the Tool Box toggle itself
(``allset.toolbox_toggle``: closes the column or docks it back). Registered by ``toolbox``."""

import bpy

from .. import i18n
from ..operators import view
from .toolbox_column import GAP_PX, OUTLINER_PX, _enabled, is_toolbox


# --- quick layouts (Maya Tool Box) ---------------------------------------------------

class ALLSET_OT_quick_layout(bpy.types.Operator):
    """Maya Tool Box quick layout button"""
    bl_idname = "allset.quick_layout"
    bl_label = "Quick Layout"
    bl_options = {'INTERNAL'}

    layout: bpy.props.EnumProperty(items=(
        ('SINGLE', "Single Perspective View", "One perspective view (Maya quick layout 1)"),
        ('FOUR', "Four View", "Top, perspective, front and side views (Maya quick layout 2)"),
        ('FRONT_PERSP', "Front/Persp", "Front and perspective views side by side (Maya quick layout 3): "
                                       "not available, a Blender 3D View splits only into four"),
    ))

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return {
            "SINGLE": "Single Perspective View", "FOUR": "Four View. " + view.FOUR_VIEW_NOTE,
            "FRONT_PERSP": "Front/Persp: not available (a Blender 3D View splits only into four)"}[props.layout]

    def execute(self, context):
        if self.layout == 'FRONT_PERSP':
            return {'CANCELLED'}
        from .panel_menus import main_region
        from .status_line import main_view3d
        area, _r = main_view3d(context.screen)
        if area is None:
            # no 3D View panel (the one panel left is a Graph Editor ...): the layout itself
            from . import four_view
            done = four_view.set_layout(context, context.window, self.layout == 'FOUR')
            return {'FINISHED'} if done else {'CANCELLED'}
        key = "LAYOUT_SINGLE" if self.layout == 'SINGLE' else "LAYOUT_FOUR"
        with context.temp_override(area=area, region=main_region(area)):
            return bpy.ops.allset.panel_set(key=key)


def outliner_areas(screen):
    return [a for a in (screen.areas if screen else ()) if a.type == 'OUTLINER']


def floating_outliners(context):
    """Other windows that hold only Outliners (Maya's floating Outliner)."""
    return [w for w in context.window_manager.windows
            if w != context.window and w.screen.areas and all(a.type == 'OUTLINER' for a in w.screen.areas)]


def outliner_shown(context):
    """True while the Tool Box Outliner button is on: an Outliner in this window or floating."""
    return bool(outliner_areas(context.screen)) or bool(floating_outliners(context))


def _beside_column(screen):
    """The largest area right of this screen's Tool Box column (where the layout's Outliner docks), or None."""
    column = next((a for a in screen.areas if a.type == 'VIEW_3D' and is_toolbox(a.spaces.active)), None)
    if column is None:
        return None
    edge = column.x + column.width
    near = [a for a in screen.areas if a != column and abs(a.x - edge) <= GAP_PX
            and a.y < column.y + column.height and column.y < a.y + a.height]
    return max(near, key=lambda a: a.width * a.height, default=None)


def dock_outliner(context, window):
    """Split the area right of the Tool Box column (without a column: the main 3D View, e.g. Blender's own layouts)
    and put a Maya Outliner on its left. The new area or None."""
    screen = window.screen
    from . import four_view
    if four_view.is_four(screen) and not bpy.app.background:
        # left of the whole four view, never inside one of its panels (it comes on a later tick)
        return True if four_view.in_one_panel(context, window, lambda ctx, win, _p: dock_outliner(ctx, win)) else None
    area = _beside_column(screen)
    if area is None:
        from .status_line import main_view3d
        area = main_view3d(screen)[0]
    if area is None:
        return None
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    scale = context.preferences.system.ui_scale or 1.0      # 0 in background
    factor = min(0.45, OUTLINER_PX * scale / max(area.width, 1))
    before = {a.as_pointer() for a in screen.areas}
    with context.temp_override(window=window, screen=screen, area=area, region=region):
        if bpy.ops.screen.area_split(direction='VERTICAL', factor=factor) != {'FINISHED'}:
            return None
    new = next((a for a in screen.areas if a.as_pointer() not in before), None)
    if new is None:
        return None
    new.ui_type = 'OUTLINER'
    from . import maya_outliner
    maya_outliner.setup(new.spaces.active)
    return new


def _close_windows_later(pointers):
    from .. import live_refs

    def tick():
        for ptr in pointers:
            win = live_refs.window(ptr)
            if win is not None:
                with bpy.context.temp_override(window=win):
                    bpy.ops.wm.window_close()
        return None
    bpy.app.timers.register(tick, first_interval=0.0)


class ALLSET_OT_toggle_outliner(bpy.types.Operator):
    """Open or close the Outliner panel"""
    bl_idname = "allset.toggle_outliner"
    bl_label = "Outliner"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        window = context.window
        if window is None:
            return {'CANCELLED'}
        screen = window.screen
        docked = outliner_areas(screen)
        if docked:
            if bpy.app.background:      # screen.area_close hangs without a UI
                return {'CANCELLED'}
            from .maya_dock_windows import close_area      # beside the four view: the view stays four panels
            close_area(context, window, docked[0])
            return {'FINISHED'}
        floating = floating_outliners(context)
        if floating:
            _close_windows_later([w.as_pointer() for w in floating])
            return {'FINISHED'}
        if dock_outliner(context, window) is not None:
            return {'FINISHED'}
        # no 3D View to dock beside (a maximized view ...): the Outliner opens in its own window
        return bpy.ops.allset.open_editor(ui_type='OUTLINER')


# --- the Tool Box itself (Maya Windows > UI Elements > Tool Box) --------------------------------------------------

def toolbox_area(screen):
    """This screen's Tool Box column, or None."""
    return next((a for a in (screen.areas if screen else ()) if a.type == 'VIEW_3D' and is_toolbox(a.spaces.active)),
                None)


def kit_layout(screen):
    """True for a kit layout (it has the Tool Box column, the Status Line strip or the shelf row), where the Tool Box
    is the column; in other layouts it is the main 3D View's toolbar."""
    from .shelf_strip import shelf_row_area, strip_area
    return toolbox_area(screen) is not None or strip_area(screen) is not None or shelf_row_area(screen) is not None


def toolbox_shown(screen):
    """True while ``screen`` shows the Tool Box: the column in a kit layout, else the main 3D View's toolbar."""
    if screen is None:
        return False
    if kit_layout(screen):
        return toolbox_area(screen) is not None
    from .status_line import main_view3d
    area = main_view3d(screen)[0]
    return area is not None and area.spaces.active.show_region_toolbar


def make_column(space):
    """Turn a 3D View space into the Tool Box column (= the template's column, ``is_toolbox``)."""
    space.show_region_toolbar = True
    space.show_region_header = False
    space.show_region_tool_header = False
    space.show_region_ui = False
    space.show_gizmo = False
    space.overlay.show_overlays = False
    for name in dir(space):
        if name.startswith("show_object_viewport_"):
            setattr(space, name, False)


def _column_target(screen):
    """The area the column is split off: the docked Outliner left of the main 3D View, else that view."""
    from .status_line import main_view3d
    view = main_view3d(screen)[0]
    if view is None:
        return None
    left = [a for a in outliner_areas(screen) if abs(a.x + a.width - view.x) <= GAP_PX
            and a.y < view.y + view.height and view.y < a.y + a.height]
    return min(left, key=lambda a: a.x, default=view)


def dock_toolbox(context, window):
    """Split a Tool Box column off the left of the Outliner (or the main 3D View). The new area, True when it comes
    on a later tick (beside a four view), or None."""
    screen = window.screen
    from . import four_view
    if four_view.is_four(screen) and not bpy.app.background:
        return True if four_view.in_one_panel(context, window, lambda ctx, win, _p: dock_toolbox(ctx, win)) else None
    area = _column_target(screen)
    if area is None:
        return None
    from .toolbox_column import column_width, settle
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    # a few px over one toolbar column (an area edge snaps to a grid; narrower, Blender hides the tools): the
    # rest is drawn in the toolbar colour (settle)
    factor = min(0.45, (column_width(context) + GAP_PX) / max(area.width, 1))
    before = {a.as_pointer() for a in screen.areas}
    with context.temp_override(window=window, screen=screen, area=area, region=region):
        if bpy.ops.screen.area_split(direction='VERTICAL', factor=factor) != {'FINISHED'}:
            return None
    new = next((a for a in screen.areas if a.as_pointer() not in before), None)
    if new is None:
        return None
    if new.x > area.x:              # the column is the left piece
        new, area = area, new
    if new.type != 'VIEW_3D':       # split off the Outliner: the Outliner keeps the right piece
        new.type = 'VIEW_3D'
        area.type = 'OUTLINER'
        from . import maya_outliner
        maya_outliner.setup(area.spaces.active)
    make_column(new.spaces.active)
    settle(new.spaces.active, context.preferences)
    return new


def _undo_fallback(context, window, screen):
    """The main view's toolbar the kit showed while the column was too narrow goes with the column."""
    from . import layout_fit
    from .status_line import main_view3d
    if screen.name not in layout_fit._fallback:
        return
    layout_fit._fallback.discard(screen.name)
    main = main_view3d(screen)[0]
    if main is not None:
        with context.temp_override(window=window, screen=screen, area=main):
            main.spaces.active.show_region_toolbar = False


def toggle_toolbox(context, window):
    """Show or hide the Tool Box (Maya Windows > UI Elements > Tool Box). True = shown after, None = nothing done."""
    screen = window.screen
    from .status_line import main_view3d
    if not kit_layout(screen):
        area = main_view3d(screen)[0]
        if area is None:
            return None
        space = area.spaces.active
        with context.temp_override(window=window, screen=screen, area=area):
            space.show_region_toolbar = not space.show_region_toolbar
        return space.show_region_toolbar
    column = toolbox_area(screen)
    if column is not None:
        from .maya_dock_windows import close_area
        _undo_fallback(context, window, screen)
        return False if close_area(context, window, column) else None
    return True if dock_toolbox(context, window) is not None else None


class ALLSET_OT_toolbox_toggle(bpy.types.Operator):
    """Show or hide the Tool Box"""
    bl_idname = "allset.toolbox_toggle"
    bl_label = "Tool Box"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        from .maya_dock_windows import main_window
        from .status_line import main_view3d
        window = context.window
        if window is not None and main_view3d(window.screen)[0] is None:
            window = main_window(context.window_manager)   # run from the Preferences window or another editor window
        if window is None or bpy.app.background:     # screen.area_close hangs without a UI
            return {'CANCELLED'}
        from .. import live_refs
        win_ptr = live_refs.pointer(window)

        # run after the operator: a toolbar flag set from inside it stayed as it was (marking/modal.py hb_ui), and
        # a menu or the Preferences window may own the context now
        def later():
            win = live_refs.window(win_ptr)
            if win is not None:
                with bpy.context.temp_override(window=win, screen=win.screen):
                    toggle_toolbox(bpy.context, win)
            return None
        bpy.app.timers.register(later, first_interval=0.0)
        return {'FINISHED'}


class ALLSET_OT_viewport_search(bpy.types.Operator):
    """Open Blender command search using the actual modeling viewport, not the tool strip."""
    bl_idname = "allset.viewport_search"
    bl_label = "Search Commands"
    bl_description = "Search Blender commands in the main modeling viewport (F3)"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        from .status_line import main_view3d
        area, region = main_view3d(context.screen)
        if area is None or region is None:
            self.report({'WARNING'}, "No modeling viewport found")
            return {'CANCELLED'}
        # Search uses its invocation context for poll and dispatch. The narrow
        # dedicated toolbox is itself a VIEW_3D but has no useful model region.
        with context.temp_override(window=context.window, area=area, region=region):
            return bpy.ops.wm.search_menu('INVOKE_DEFAULT')

    def execute(self, context):
        return self.invoke(context, None)


class ALLSET_PT_toolbox_layouts(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_label = "Quick Layouts"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        return _enabled(context)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.scale_y = 1.75   # = the tool buttons (ToolSelectPanelHelper.draw_cls scale_y)
        # kit-drawn Maya layout icons (#23; Blender's icon until the glyph is made)
        from .kit_icons import button
        op = ALLSET_OT_quick_layout.bl_idname
        button(col, op, "layout:SINGLE", 'VIEW_PERSPECTIVE', text="").layout = 'SINGLE'
        button(col, op, "layout:FOUR", 'VIEW_ORTHO', text="").layout = 'FOUR'
        sub = col.row()
        sub.enabled = False   # Front/Persp needs a two-pane split: no Blender equivalent
        button(sub, op, "layout:FRONT_PERSP", 'SPLIT_VERTICAL', text="").layout = 'FRONT_PERSP'
        col.separator()
        # Maya's Outliner check box: shows / hides the Outliner (pressed while one is shown)
        button(col, ALLSET_OT_toggle_outliner.bl_idname, "layout:OUTLINER", 'OUTLINER', text="",
               depress=outliner_shown(context))
        # Maya 2022.1+: the Search icon under the layout / Outliner buttons, after a divider (Maya 2022.1 Tool Box);
        # it opens Blender's command search (Maya Ctrl+F = SearchEngine).
        col.separator()
        col.operator_context = 'INVOKE_DEFAULT'
        col.operator('allset.viewport_search', text='', icon='VIEWZOOM')
