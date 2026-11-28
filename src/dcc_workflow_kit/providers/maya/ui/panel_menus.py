# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya viewport panel menu bar: View, Shading, Lighting, Show, Renderer, Panels.

Every Maya modelPanel has its own menu bar. Menu contents
follow Maya's panel menus (View, Shading, Lighting,
Show, Renderer, Panels); only labels and order.

Only the menu part of the 3D View header changes: ``VIEW3D_MT_editor_menus.draw_collapsible``
(inherited from ``bpy.types.Menu``, called once by ``VIEW3D_HT_header.draw``,
$S\\startup\\bl_ui\\space_view3d.py:915) is overridden while the add-on is enabled; the
mode selector and the right-hand buttons (Maya's panel icon bar) stay Blender's. Blender's
View / Select / Add / Object ... menus stay reachable under "Blender ▸".

Item forms (one tuple per row):
``("prop", owner, prop, label)`` check box on ``space`` / ``shading`` / ``overlay``;
``("set", key, label)`` ``allset.panel_set`` (radio / toggle state from ``state``);
``("run", label, op, props)`` an operator run in this view's main region;
``("menu", label, idname)``; ``("grey", label)`` no Blender equivalent; ``("sep", label)``.

Code: ``panel_cameras`` (the camera of a view, Look Through, new cameras), ``panel_state`` (state / apply of the
``set`` keys); this module keeps the operators, row drawing, menus, header patch and register. The names used
elsewhere are importable from here too.
"""

import json

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from . import camera_bookmarks

GREY_OP = "allset.menu_unavailable"


# Row tables live in panel_menu_data (bpy-free: menu_count / menu_consistency / notice rules walk them).
from .panel_menu_data import (_view, VIEW, VIEW_AXIS, CAMERA_TOOLS, SHADING, LIGHTING, ALL_TYPES,
                              _show_row, SHOW, ISOLATE, RENDERER, ENGINE_ROWS, PANELS, PANEL_TYPES, LAYOUTS, BAR,  # noqa: F401
                              item_path)
from .. import i18n
# the split-out parts, also read through this module by other UI and the tests
from .panel_cameras import (ALLSET_MT_panel_new_ortho, ALLSET_MT_panel_ortho_new,  # noqa: F401
                            ALLSET_OT_panel_look_through, ALLSET_OT_panel_new_ortho, ALLSET_OT_panel_new_persp,
                            ORTHO_SIDES, _before_look, _cameras, _draw_camera_list, _look_through_panel_camera,
                            _on_undo, _scene_camera_view, _space, _startup_name, camera_locked, enable_in_viewports,
                            has_panel_camera, look_through, panel_camera, restore_camera_less, view_camera)
from .panel_state import (CAMERA_DATA, CAMERA_KEYS, EXPOSURE_LAST, FAILS, FIELD_CHART, GAMMA_LAST,  # noqa: F401
                          GATE_OVERSCAN, RADIO, RAW, RENDER_ENGINES, RES_GATE, SAFE, SET_KEYS, SHOW_HIDDEN, TIPS,
                          TOGGLE_OFF, TOOLBAR_KEYS, TRANSFORM_LAST, _before_render, _safe_on, _sync_safe_margins,
                          _toggle_colour, apply, enter_rendered, leave_rendered, main_region, set_engine,
                          show_ik_handles, state)


# --- state ---------------------------------------------------------------------------

def _owner(space, context, owner):
    if owner == "preferences":
        from .. import preferences
        return preferences.get(context)
    return {"space": space, "shading": space.shading, "overlay": space.overlay}[owner]


class ALLSET_OT_panel_set(bpy.types.Operator):
    """Maya panel menu item for this view"""
    bl_idname = "allset.panel_set"
    bl_label = "Panel Menu Item"
    bl_options = {'INTERNAL', 'UNDO'}

    key: EnumProperty(items=[(k, k.title(), "") for k in
                             dict.fromkeys(SET_KEYS + ["SHOW_ALL", "SHOW_NONE"] + TOOLBAR_KEYS)])
    # panel toolbar button: a second click turns a radio-like mode off again (Maya iconTextCheckBox)
    toggle: BoolProperty(default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _space(context) is not None

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return TIPS.get(props.key, "Maya panel menu item for this view")

    def execute(self, context):
        key = self.key
        if self.toggle and key in TOGGLE_OFF and state(context, key):
            key = TOGGLE_OFF[key]
        if key == "BOOKMARK":             # a command with a result: the new bookmark's name (Maya)
            name = camera_bookmarks.add(context)
            if name is None:
                self.report({'WARNING'}, FAILS[key])
                return {'CANCELLED'}
            from .. import results
            results.result(self, name)
            return {'FINISHED'}
        if not apply(context, key):
            if key in FAILS:
                self.report({'WARNING'}, FAILS[key])
            return {'CANCELLED'}
        return {'FINISHED'}


# rows that change the scene: one undo step named after the command (a Python operator call makes none)
UNDO_RUNS = {"allset.camera_from_view", "allset.image_plane", "allset.image_plane_display",
             "allset.image_plane_delete"}


class ALLSET_OT_panel_run(bpy.types.Operator):
    """Run a Blender operator in this view (Maya panel menu item)"""
    bl_idname = "allset.panel_run"
    bl_label = "Run in This View"
    bl_options = {'INTERNAL'}

    op: StringProperty(options={'SKIP_SAVE'})
    props: StringProperty(default="{}", options={'SKIP_SAVE'})
    tip: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})     # the row's own tooltip (else the command's)

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        if getattr(props, "tip", ""):
            return props.tip
        try:
            mod, name = props.op.split(".")
            return getattr(getattr(bpy.ops, mod), name).get_rna_type().description
        except (ValueError, AttributeError, KeyError):
            return ""

    def execute(self, context):
        area = context.area
        if area is None:
            return {'CANCELLED'}
        mod, name = self.op.split(".")
        op = getattr(getattr(bpy.ops, mod), name)

        def call():
            with context.temp_override(window=context.window, area=area, region=main_region(area)):
                return op('INVOKE_DEFAULT', **json.loads(self.props))
        try:
            if self.op in UNDO_RUNS:
                from .. import undo_steps
                undo_steps.command(op.get_rna_type().name, call)
            else:
                call()
        except RuntimeError as ex:  # poll failed etc.
            self.report({'WARNING'}, str(ex).strip())
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_panel_tear_off(bpy.types.Operator):
    """Open this panel in a new window of its size (a view keeps its camera and display). Tear Off leaves a 3D """     """View in the pane, like Maya; Tear Off Copy keeps the panel there too"""
    bl_idname = "allset.panel_tear_off"
    bl_label = "Tear Off"
    bl_options = {'INTERNAL'}

    copy: BoolProperty(name="Copy", default=True, options={'SKIP_SAVE'},
                       description="Keep the panel in its pane as well (Tear Off Copy)")

    def execute(self, context):
        area = context.area
        if context.window is None or area is None or bpy.app.background:
            return {'CANCELLED'}
        region = main_region(area)
        if region is None:
            return {'CANCELLED'}
        before = set(context.window_manager.windows[:])
        with context.temp_override(window=context.window, area=area, region=region):
            # the copy needs the invoke (exec alone is refused)
            bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
        new = next((w for w in context.window_manager.windows if w not in before), None)
        if new is None:
            return {'CANCELLED'}
        if area.type != 'VIEW_3D':
            from . import window_places
            # Windows > ... opens that editor where this window ends up (Maya remembers an editor window's place)
            window_places.track(new, f"editor:{area.ui_type}")
            if not self.copy:
                area.ui_type = 'VIEW_3D'      # Maya fills the emptied pane with a model panel (#319)
        return {'FINISHED'}


# --- drawing --------------------------------------------------------------------------

def draw_rows(layout, context, rows, idname=""):
    space = _space(context)
    for row in rows:
        kind = row[0]
        if kind == "sep":
            if row[1]:
                layout.separator(type='LINE')
                layout.label(text=row[1])
            else:
                layout.separator()
        elif kind == "grey":
            layout.operator(GREY_OP, text=row[1]).item = item_path(idname, row[1])
        elif kind == "prop":
            _k, owner, prop, label = row
            if space is not None:
                layout.prop(_owner(space, context, owner), prop, text=label)
        elif kind == "set":
            _k, key, label = row
            if key == "RENDER_ENGINE" or key in ENGINE_ROWS:
                # the Renderer Engine Items preference: Eevee / Cycles rows, else one row for the scene's engine
                from .. import preferences
                if (key in ENGINE_ROWS) != bool(preferences.get(context).renderer_engines):
                    continue
            if key == "RENDER_ENGINE":
                label = context.engine.replace("BLENDER_", "").replace("_NEXT", "").title()
            on = state(context, key)
            if on is None:
                icon = 'NONE'
            elif key in RADIO:
                icon = 'RADIOBUT_ON' if on else 'RADIOBUT_OFF'
            else:
                icon = 'CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT'
            layout.operator(ALLSET_OT_panel_set.bl_idname, text=label, icon=icon).key = key
        elif kind == "run":
            _k, label, op, props = row
            p = layout.operator(ALLSET_OT_panel_run.bl_idname, text=label)
            p.op, p.props = op, json.dumps(props)
        elif kind == "menu":
            layout.menu(row[2], text=row[1])


def _menu(idname, label, rows, doc):
    def draw(self, context):
        draw_rows(self.layout, context, rows, idname)
    return type(idname, (bpy.types.Menu,), {"bl_idname": idname, "bl_label": label, "__doc__": doc,
                                            "draw": draw})


class ALLSET_MT_panel_perspective(bpy.types.Menu):
    """Maya Panels > Perspective: the persp view and perspective cameras"""
    bl_idname = "ALLSET_MT_panel_perspective"
    bl_label = "Perspective"

    def draw(self, context):
        draw_rows(self.layout, context, [_view("persp", 'PERSP')])
        _draw_camera_list(self.layout, context, False)
        self.layout.separator()
        self.layout.operator(ALLSET_OT_panel_new_persp.bl_idname, text="New")      # Maya: New under the list (#193)


class ALLSET_MT_panel_orthographic(bpy.types.Menu):
    """Maya Panels > Orthographic: top, front, side and orthographic cameras"""
    bl_idname = "ALLSET_MT_panel_orthographic"
    bl_label = "Orthographic"

    def draw(self, context):
        draw_rows(self.layout, context, [_view("top", 'TOP'), _view("front", 'FRONT'), _view("side", 'RIGHT')])
        _draw_camera_list(self.layout, context, True)
        self.layout.separator()
        self.layout.menu(ALLSET_MT_panel_ortho_new.bl_idname, text="New")      # Maya: New > six sides under the list


class ALLSET_MT_panel_panel(bpy.types.Menu):
    """Maya Panels > Panel: turn this pane into another editor"""
    bl_idname = "ALLSET_MT_panel_panel"
    bl_label = "Panel"

    def draw(self, context):
        for label, ui_type in PANEL_TYPES:
            self.layout.operator("allset.hb_pane", text=label).ui_type = ui_type


class ALLSET_MT_panel_blender(bpy.types.Menu):
    """Blender's own 3D View menus (View, Select, Add, Object ...)"""
    bl_idname = "ALLSET_MT_panel_blender"
    bl_label = "Blender"

    def draw(self, context):
        bpy.types.VIEW3D_MT_editor_menus.draw(self, context)


def draw_bar(layout, context):
    for label, idname in BAR:
        layout.menu(idname, text=label)
    layout.menu(ALLSET_MT_panel_blender.bl_idname, text="Blender")


class ALLSET_MT_panel_bar(bpy.types.Menu):
    """The Maya panel menus folded into one menu (header menus collapsed)"""
    bl_idname = "ALLSET_MT_panel_bar"
    bl_label = "Panel Menus"

    def draw(self, context):
        draw_bar(self.layout, context)


_generated = [
    _menu("ALLSET_MT_panel_view", "View", VIEW, "Maya panel View menu"),
    _menu("ALLSET_MT_panel_view_axis", "View Along Axis", VIEW_AXIS, "Look along a world axis"),
    _menu("ALLSET_MT_panel_camera_tools", "Camera Tools", CAMERA_TOOLS, "Maya camera tools"),
    _menu("ALLSET_MT_panel_shading", "Shading", SHADING, "Maya panel Shading menu"),
    _menu("ALLSET_MT_panel_lighting", "Lighting", LIGHTING, "Maya panel Lighting menu"),
    _menu("ALLSET_MT_panel_show", "Show", SHOW, "Maya panel Show menu"),
    _menu("ALLSET_MT_panel_isolate", "Isolate Select", ISOLATE, "Maya Isolate Select"),
    _menu("ALLSET_MT_panel_renderer", "Renderer", RENDERER, "Maya panel Renderer menu"),
    _menu("ALLSET_MT_panel_panels", "Panels", PANELS, "Maya panel Panels menu"),
    _menu("ALLSET_MT_panel_layouts", "Layouts", LAYOUTS, "Maya panel layouts"),
]

classes = (ALLSET_OT_panel_set, ALLSET_OT_panel_run, ALLSET_OT_panel_tear_off, ALLSET_OT_panel_look_through, ALLSET_OT_panel_new_persp,
           ALLSET_OT_panel_new_ortho, ALLSET_MT_panel_new_ortho, ALLSET_MT_panel_ortho_new,
           ALLSET_MT_panel_perspective, ALLSET_MT_panel_orthographic, ALLSET_MT_panel_panel,
           ALLSET_MT_panel_blender, ALLSET_MT_panel_bar, *_generated)


# --- header patch -----------------------------------------------------------------------

def _enabled(context):
    from .. import preferences
    try:
        return preferences.get(context).maya_panel_menus
    except KeyError:
        return False


def draw_collapsible(cls, context, layout):
    """Replaces Menu.draw_collapsible for VIEW3D_MT_editor_menus (bpy_types.py:1292-1299)."""
    if not _enabled(context):
        return _ORIG(cls, context, layout)
    if context.area.show_menus:
        draw_bar(layout.row(align=True), context)
    else:
        layout.menu(ALLSET_MT_panel_bar.bl_idname, text="", icon='COLLAPSEMENU')


def _ORIG(cls, context, layout):
    return bpy.types.Menu.draw_collapsible.__func__(cls, context, layout)


def patch_header():
    bpy.types.VIEW3D_MT_editor_menus.draw_collapsible = classmethod(draw_collapsible)


def unpatch_header():
    cls = bpy.types.VIEW3D_MT_editor_menus
    if "draw_collapsible" in cls.__dict__:
        del cls.draw_collapsible


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    patch_header()
    bpy.app.handlers.undo_post.append(_on_undo)
    from . import startup_camera_views
    startup_camera_views.register()


def unregister():
    from . import startup_camera_views
    startup_camera_views.unregister()
    if _on_undo in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.remove(_on_undo)
    _before_look.clear()
    unpatch_header()
    from . import curve_controls
    try:
        curve_controls.release_all()
    except Exception:          # restricted context while Blender quits
        pass
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
