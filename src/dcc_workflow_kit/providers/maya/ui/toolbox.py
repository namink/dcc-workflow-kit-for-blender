# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Tool Box: the 3D View toolbar shows Maya's tools in every mode.

Maya's Tool Box is a narrow column left of the
Outliner: Select, Lasso, Paint Select, Move, Rotate, Scale, the last non-sacred tool, then quick layout
buttons and an Outliner toggle. Here:

- ``VIEW3D_PT_tools_active.draw`` is wrapped so that, while it draws, ``tools_from_context`` yields the
  Maya list (``maya_tools``). Only drawing is filtered: ``wm.tool_set_by_id`` looks tools up through
  ``tools_from_context`` too, so replacing ``_tools`` would stop the shelf / menus / keys from
  activating tools that are not in the Tool Box (Multi-Cut, Quad Draw, ...). Modes without the Maya
  tools (sculpt and paint modes) keep Blender's list.
- ``ALLSET_PT_toolbox_layouts`` adds the quick layout buttons under the tools.
- The Maya Workflow Kit template has a Tool Box column: a narrow 3D View showing only its toolbar (``is_toolbox``),
  with every object type hidden in that view (nothing drawn behind the tools; box / lasso select there
  touch nothing). A click under the tools reaches that view's WINDOW region and ``view3d.select`` would
  still deselect everything, so ``allset.toolbox_guard`` sits in front of it in the
  "3D View" keymap. Its overlays are off, so the kit's own drawing (grid, view furniture, selection
  wire) skips it as well.

Code: ``toolbox_column`` (column identity, look, width), ``layout_fit`` (layout sizes per UI scale),
``toolbox_layouts`` (layout / Outliner / Search buttons), ``armature_modes`` (skeleton mode picker and watches).
This module keeps the toolbar's Maya tool list, the double-click Tool Settings, the click guard and register /
unregister; the names used elsewhere are importable from here too.
"""

import bpy
from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active as TOOLBAR

from ..operators import tool_keys
from . import kit_wraps
# the split-out parts, also read through this module by other UI, the tests and tools
from .toolbox_column import (GAP_PX, OUTLINER_PX, RETINA_EXTRA_PX, TOOLBAR_PX, _enabled,  # noqa: F401
                             column_width, is_toolbox, settle)
from .layout_fit import (ALLSET_OT_fit_columns, DOCK_MAX_PX, DOCK_MAYA_PX, FIT_WINDOW,  # noqa: F401
                         LONG_LABELS, MIN_VIEW_PX, SHELF_PX, TIME_SLIDER_PX, WIDE_KINDS, _FIT_TICK, _armed,
                         _dock_target, _drawn, _fit_after_load, _fit_tick, _running, _state, _tab_target, _unit,
                         auto_warp, dock_need, dock_width, fit_columns, note_scale, tab_changed, text_px,
                         time_slider_area)
from .toolbox_layouts import (ALLSET_OT_quick_layout, ALLSET_OT_toggle_outliner,  # noqa: F401
                              ALLSET_OT_toolbox_toggle,                               ALLSET_OT_viewport_search, ALLSET_PT_toolbox_layouts, dock_outliner,
                              floating_outliners, outliner_areas, outliner_shown)
from .armature_modes import (ALLSET_MT_armature_modes, ALLSET_OT_armature_mode,  # noqa: F401
                             ALLSET_OT_joint_outliner_select, ALLSET_OT_pose_empty_click, ALLSET_OT_skinned_handle_click,
                             _auto_armature_tick, _draw_armature_mode_header, _ensure_outliner_watch,
                             _ensure_pose_watch, _last_armature_target, _other_object_under_click, _outliner_watch_areas,
                             _pose_watch_areas)

# Maya Tool Box order: Select, Lasso, Paint Select, Move, Rotate, Scale.
MAYA_TOOLS = ("builtin.select_box", "builtin.select_lasso", "builtin.select_circle",
              "builtin.move", "builtin.rotate", "builtin.scale")

_saved = {}
_drawing = [False]
# True while Maya's Skin Paint Mode (Select / Paint Select) sets a select tool inside weight paint: those
# tools then stay in paint instead of leaving it like the Tool Box's Select / Move / ... (operators/weight_paint.py)
KEEP_PAINT = [False]


def _flat(items):
    for item in items:
        if type(item) is tuple:
            yield from (i for i in item if i is not None)
        elif item is not None:
            yield item


def maya_tools(blender_items, mode):
    """The Tool Box for one mode from Blender's tool items (ToolDefs, groups, None), or None when the
    mode lacks the Maya tools. The last slot is the last non-sacred tool used in that mode (Maya's
    last non-sacred tool; tool_keys.LAST, the Y key's memory). Tools other add-ons registered for the mode
    follow, so they stay reachable."""
    by_id = {t.idname: t for t in _flat(blender_items)}
    picked = [by_id[i] for i in MAYA_TOOLS if i in by_id]
    if not any(t.idname == "builtin.move" for t in picked):
        return None
    out = picked + [None]
    last = tool_keys.LAST.get(mode)
    if last in by_id and last not in MAYA_TOOLS:
        out.append(by_id[last])
    others = [t for t in by_id.values() if is_other_addon_tool(t.idname) and t.idname != last]
    if others:     # tools other add-ons registered stay in the toolbar, after the Maya tools
        out += ([] if out[-1] is None else [None]) + others
    return out


def is_other_addon_tool(idname):
    """A tool another add-on registered (not one of Blender's, not one of the kit's)."""
    return not (idname.startswith("builtin") or idname.startswith("allset."))


def kit_icons_on(items, context):
    """The Tool Box column's Maya tools with the kit-drawn Maya icons (#23): each ToolDef copy names a
    kit-only icon that ``kit_icons.tool_icon_name`` put into Blender's toolbar icon cache. Only the drawn copy
    changes (tool switching looks tools up by idname); the last-tool slot and tools without a kit glyph keep
    Blender's icon."""
    from . import kit_icons
    out = []
    for item in items:
        name = kit_icons.tool_icon_name(item.idname, context) if item is not None and item.idname in MAYA_TOOLS             else None
        out.append(item._replace(icon=name) if name else item)
    return out


def _tools_from_context(cls, context, mode=None):
    original = _saved["tools_from_context"].__func__
    if _drawing[0] and mode is None:
        items = list(original(cls, context))
        if context.mode == 'PAINT_WEIGHT':
            # Maya's global selection/transform tools leave Artisan painting.
            # Blender hides some of these tools in paint mode; draw their
            # Object-mode definitions and release paint before activation.
            paint_items = list(_flat(items))
            object_items = list(original(cls, context, mode='OBJECT'))
            maya = maya_tools(object_items, 'OBJECT')
            if maya is not None:
                current = context.workspace.tools.from_space_view3d_mode('PAINT_WEIGHT', create=False)
                brush = next((t for t in paint_items if current is not None and t.idname == current.idname), None)
                if brush is not None and brush.idname not in MAYA_TOOLS:
                    maya.append(brush)
        else:
            maya = maya_tools(items, context.mode)
        if maya is not None:
            if is_toolbox(context.space_data):
                maya = kit_icons_on(maya, context)
            yield from maya
            return
    yield from original(cls, context, mode)


# --- double-click a tool = its Tool Settings (#3; Maya Tool Box) -------------------------------------
# A toolbar icon is a UI button: a double click never reaches a keymap, but each click runs wm.tool_set_by_id, whose
# execute imports bl_ui.space_toolsystem_common.activate_by_id when it runs ($S\startup\bl_operators\wm.py:2338-2347;
# a DOUBLE_CLICK the button doesn't take comes back as a PRESS). That module function is wrapped: the same tool set
# twice from a 3D View toolbar button within the double-click time opens the Tool Settings. A toolbar button runs its
# operator in the view's WINDOW region like a key does, so the toolbar's layout carries a context member
# (``_draw_begin``: ``context_pointer_set``) that only its buttons' operators see.

TOOLBAR_MEMBER = "allset_toolbar"
_last_click = [None, 0.0]     # (tool idname, time.monotonic()) of the last toolbar click


def note_tool_click(context, idname, now=None):
    """Remember a tool set from a toolbar button; True when it completes a double click (then forgotten)."""
    import time
    if getattr(context, TOOLBAR_MEMBER, None) is None:     # a key / menu / script: never a double click
        _last_click[:] = [None, 0.0]
        return False
    now = time.monotonic() if now is None else now
    limit = context.preferences.inputs.mouse_double_click_time / 1000.0
    hit = _last_click[0] == idname and 0.0 <= now - _last_click[1] <= limit
    _last_click[:] = [None, 0.0] if hit else [idname, now]
    return hit


def _show_tool_settings_later(window):
    ptr = window.as_pointer() if window is not None else 0

    def later():
        from . import tool_dock
        wm = bpy.context.window_manager
        win = next((w for w in wm.windows if w.as_pointer() == ptr), None) or (wm.windows[0] if wm.windows else None)
        if win is None:
            return None
        try:
            with bpy.context.temp_override(window=win):
                tool_dock.show(bpy.context)
        except (RuntimeError, ReferenceError, TypeError):
            pass
        return None
    bpy.app.timers.register(later, first_interval=0.0)


def _make_tools_from_context(previous, on):
    """The class method put in place of ``tools_from_context`` (``kit_wraps``): with Maya mode off (another add-on
    kept it inside its own wrapper) it only calls what it wrapped."""
    original = previous.__func__

    def tools_from_context(cls, context, mode=None):
        if not on():
            yield from original(cls, context, mode)
            return
        yield from _tools_from_context(cls, context, mode)
    return classmethod(tools_from_context)


def _end_move_skinned(context, idname):
    """A tool picked in a 3D View (the toolbar, the Tool Box, a key or menu entry) ends Skin > Move Skinned Joints,
    like picking another tool in Maya; a toolbar click on the active tool ends it too."""
    from ..operators import joint_selection
    try:
        joint_selection.tool_picked(context, idname, again=getattr(context, TOOLBAR_MEMBER, None) is not None)
    except (AttributeError, RuntimeError, ReferenceError, TypeError):
        pass


def _make_activate_by_id(original, on=lambda: True):
    def activate_by_id(context, space_type, idname, *, as_fallback=False):
        if not on():
            return original(context, space_type, idname, as_fallback=as_fallback)
        if (space_type == 'VIEW_3D' and context.mode == 'PAINT_WEIGHT'
                and idname in MAYA_TOOLS and not as_fallback and not KEEP_PAINT[0]):
            from ..operators.skin import leave_weight_paint
            leave_weight_paint(context)
        if space_type == 'VIEW_3D' and not as_fallback:
            _end_move_skinned(context, idname)
        done = original(context, space_type, idname, as_fallback=as_fallback)
        if done and space_type == 'VIEW_3D' and note_tool_click(context, idname):
            _show_tool_settings_later(getattr(context, "window", None))
        return done
    activate_by_id._allset_wrapped = True
    return activate_by_id


def _draw_begin(self, context):
    """Prepended to the toolbar's draw: Blender's own draw (ToolSelectPanelHelper.draw) lists the Maya tools while
    the flag is on. A prepend / append pair, not a replaced draw. Also marks the toolbar's buttons for the
    double-click watch, and notes the window's own UI scale for the layout fit."""
    _drawing[0] = _enabled(context)
    note_scale(context)
    if context.space_data is not None and context.space_data.type == 'VIEW_3D':
        self.layout.context_pointer_set(TOOLBAR_MEMBER, context.space_data)


def _draw_end(self, context):
    _drawing[0] = False


class ALLSET_OT_toolbox_guard(bpy.types.Operator):
    """Ignore clicks under the Tool Box column's tools (they would deselect everything)"""
    bl_idname = "allset.toolbox_guard"
    bl_label = "Tool Box Click"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return {'FINISHED'} if is_toolbox(context.space_data) else {'PASS_THROUGH'}


classes = (ALLSET_OT_toolbox_guard, ALLSET_OT_fit_columns, ALLSET_OT_quick_layout, ALLSET_OT_toggle_outliner, ALLSET_OT_toolbox_toggle, ALLSET_OT_viewport_search, ALLSET_OT_armature_mode, ALLSET_MT_armature_modes, ALLSET_OT_pose_empty_click, ALLSET_OT_skinned_handle_click, ALLSET_OT_joint_outliner_select, ALLSET_PT_toolbox_layouts)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    # another add-on that wraps these while Maya mode is on keeps its wrapper when Maya mode goes off (#449)
    _saved["tools_from_context"] = TOOLBAR.__dict__["tools_from_context"]
    kit_wraps.wrap(TOOLBAR, "tools_from_context", _make_tools_from_context)
    TOOLBAR.prepend(_draw_begin)
    bpy.types.VIEW3D_HT_header.prepend(_draw_armature_mode_header)
    if not bpy.app.background:
        from .. import keymap
        from ..keymap.maya_patches_manip import GIZMO_KEYMAPS
        # Run the same undoable selection operator in the clicked viewport with either keymap preset.
        item = keymap.add_item('3D View', 'allset.select_priority', 'LEFTMOUSE', 'CLICK',
                               space_type='VIEW_3D', head=True)
        if item is not None:
            item.properties.skinned_only = True
        # Handle clicks belong to Move Skinned Joints with either keymap preset.
        for name in GIZMO_KEYMAPS:
            keymap.add_item(name, ALLSET_OT_skinned_handle_click.bl_idname, 'LEFTMOUSE', 'CLICK', head=True)
        bpy.app.timers.register(_auto_armature_tick, first_interval=0.5, persistent=True)
        bpy.app.timers.register(_ensure_pose_watch, first_interval=1.0, persistent=True)
        bpy.app.timers.register(_ensure_outliner_watch, first_interval=1.0, persistent=True)
    TOOLBAR.append(_draw_end)
    from bl_ui import space_toolsystem_common as stc
    kit_wraps.wrap(stc, "activate_by_id", _make_activate_by_id)
    if not bpy.app.background and not bpy.app.timers.is_registered(_fit_tick):
        bpy.app.timers.register(_fit_tick, first_interval=_FIT_TICK, persistent=True)
    bpy.app.handlers.load_post.append(_fit_after_load)


def unregister():
    _running[0] = False
    _tab_target.clear()
    _drawn.clear()
    _last_armature_target.clear()
    _pose_watch_areas.clear()
    _outliner_watch_areas.clear()
    for timer in (_auto_armature_tick, _ensure_pose_watch, _ensure_outliner_watch):
        if bpy.app.timers.is_registered(timer):
            bpy.app.timers.unregister(timer)
    if _fit_after_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_fit_after_load)
    if bpy.app.timers.is_registered(_fit_tick):
        bpy.app.timers.unregister(_fit_tick)
    kit_wraps.unwrap(TOOLBAR, "tools_from_context")
    _saved.pop("tools_from_context", None)
    from bl_ui import space_toolsystem_common as stc
    kit_wraps.unwrap(stc, "activate_by_id")
    _last_click[:] = [None, 0.0]
    bpy.types.VIEW3D_HT_header.remove(_draw_armature_mode_header)
    TOOLBAR.remove(_draw_begin)
    TOOLBAR.remove(_draw_end)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
