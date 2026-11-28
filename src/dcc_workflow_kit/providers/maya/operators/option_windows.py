# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya option windows (the □ option box of a menu item).

Maya opens a window per command with its fields (labels right-aligned, field + slider), an Edit menu (Save Settings /
Reset Settings) and three buttons: the command ("Create", "Extrude", ...), Apply (run, keep the window) and Close; the
values are kept between sessions. Fields, labels and defaults (in option_windows_basic and the other
option_windows_* modules) follow Maya's windows.

Each ``Window`` becomes one operator ``allset.opt_<key>`` drawn with ``invoke_props_dialog`` (confirm = the
command's button, Blender's cancel = Close); Apply / Save Settings / Reset Settings are toggle buttons inside the
dialog whose update callbacks act at once and spring back. With Preferences > Option Boxes in Floating Windows the
same fields open in a floating window instead (ui/option_editor.py) with command, Apply, Close, Save Settings and
Reset Settings buttons. ``Window.run`` maps the Maya values onto the kit or
Blender operator. ``find(action)`` ties a window to a menu / marking menu / shelf action, so every option box of
that action opens it, and a plain click uses the saved values once the user has applied or saved them (Maya runs a
menu item with its option values).

Code: option_windows_spec (F / Window and the shared run helpers), option_windows_basic (the first windows); this
module keeps the registry, saved values and the operators.
"""

import json

import bpy
from bpy.props import BoolProperty

from .. import i18n
from . import option_windows_basic, scene_axes
from .option_windows_basic import (_CON_AXES, _FREEZE_RESET, _run_bake, _run_bevel, _run_combine,  # noqa: F401
                                   _run_extrude, _run_group, _run_new_scene, _run_save, _run_set_key,
                                   _run_smart_bevel, _run_smooth, _run_uv_auto, _run_uv_planar)
from .option_windows_spec import (AXIS, UVS, F, Window, _AXES, _NODE_FIELDS, _components,  # noqa: F401
                                  _constraint, _group_axes, _k, _last_constraint, _op, _primitive,
                                  _with_hierarchy)

# --- new scene (first_start reads these here) -------------------------------------------------------

def set_time(scene, text):
    """A Maya Time choice ("24 fps", "29.97 fps") as the scene's frame rate (fps / fps_base)."""
    fps = float(text.split()[0])
    scene.render.fps, scene.render.fps_base = (round(fps), round(fps) / fps)


def scene_units(scene):
    """The working units of ``scene`` (Do not reset working units carries them into the new scene)."""
    us = scene.unit_settings
    return {"system": us.system, "length_unit": us.length_unit, "system_rotation": us.system_rotation,
            "fps": scene.render.fps, "fps_base": scene.render.fps_base}


def new_scene_values():
    """The New Scene Options a new Maya scene gets: the saved option values (None when never saved) and the New
    Scene Time, which is always applied."""
    window = _BY_KEY["new_scene"]
    stored = saved(window.key)
    prefs = _prefs()
    time = getattr(prefs, "new_scene_time", None) if prefs is not None else None
    return {**window.defaults(), "fps": time or window.defaults()["fps"], **(stored or {})}, stored is not None


def apply_new_scene(scene, values, full, before=None):
    """Give a new Maya scene its New Scene Options: the working units (or ``before``, the previous scene's, when Do
    not reset working units is on) and, when ``full`` (options applied or saved), the time ranges."""
    us = scene.unit_settings
    if values["keep_units"]:
        if before:
            us.system, us.length_unit = before["system"], before["length_unit"]
            us.system_rotation = before["system_rotation"]
            scene.render.fps, scene.render.fps_base = before["fps"], before["fps_base"]
    else:
        if full:
            us.length_unit = {"millimeter": 'MILLIMETERS', "centimeter": 'CENTIMETERS', "meter": 'METERS',
                              "inch": 'INCHES', "foot": 'FEET', "yard": 'YARDS'}[values["linear"]]
            if values["linear"] in ("inch", "foot", "yard"):
                us.system = 'IMPERIAL'
            us.system_rotation = 'DEGREES' if values["angular"] == "degrees" else 'RADIANS'
        set_time(scene, values["fps"])
    if full:
        scene.frame_start, scene.frame_end = int(values["anim_start"]), int(values["anim_end"])
        scene.use_preview_range = True
        scene.frame_preview_start, scene.frame_preview_end = int(values["play_start"]), int(values["play_end"])
        scene.frame_current = int(values["play_start"])


# --- the windows: option_windows_basic first, then the other option_windows_* modules ------------

WINDOWS = list(option_windows_basic.WINDOWS)


def _extend():
    # more windows live in their own modules (they import F / Window from here); Bind Skin and Duplicate
    # Special moved there with every Maya field (option_windows_rig.bind_skin_maya / option_windows_edit)
    from . import (option_windows_curves, option_windows_deform, option_windows_display, option_windows_edit,
                   option_windows_modify, option_windows_render, option_windows_rig, option_windows_surfaces,
                   option_windows_visualize, option_windows_mesh_display)
    WINDOWS.extend(option_windows_rig.WINDOWS + option_windows_edit.WINDOWS + option_windows_deform.WINDOWS
                   + option_windows_display.WINDOWS + option_windows_render.WINDOWS + option_windows_curves.WINDOWS
                   + option_windows_modify.WINDOWS
                   + option_windows_visualize.WINDOWS
                   + option_windows_surfaces.WINDOWS
                   + option_windows_mesh_display.WINDOWS)
    from . import option_windows_misc196, option_windows_prims
    WINDOWS.extend(option_windows_prims.WINDOWS + option_windows_misc196.WINDOWS)
    from . import option_windows_197
    WINDOWS.extend(option_windows_197.WINDOWS)      # Mesh > Cleanup...
    from . import deformers_205a, deformers_205b, pins_205
    WINDOWS.extend(deformers_205a.windows() + deformers_205b.windows() + pins_205.windows())
    from . import option_windows_199
    WINDOWS.extend(option_windows_199.WINDOWS)      # Skin / Constrain tools 2
    from . import option_windows_curves207
    WINDOWS.extend(option_windows_curves207.WINDOWS)    # Bend / Curl / Scale Curvature
    from . import motion_path_228
    WINDOWS.extend(motion_path_228.windows())    # Attach to Motion Path
    from . import option_windows_uv
    WINDOWS.extend(option_windows_uv.WINDOWS)    # UV Editor Unfold / Layout / Straighten UVs / Randomize Shells
    from . import option_windows_uv_edit
    WINDOWS.extend(option_windows_uv_edit.WINDOWS)    # UV Editor Cut/Sew and Modify
    from . import option_windows_trax
    WINDOWS.extend(option_windows_trax.WINDOWS)    # Trax Editor Create Clip
    from . import option_windows_match
    WINDOWS.extend(option_windows_match.WINDOWS)    # Modify > Match Transformations


_extend()
_BY_KEY = {w.key: w for w in WINDOWS}


def find(action):
    """The option window of a menu / marking-menu / shelf action (raw ``menu_map`` value or normalised), or None."""
    from ..ui import menu_map
    if isinstance(action, tuple) and len(action) == 3 and action[0] in ("op", "v3d") and isinstance(action[2], dict):
        s = action
    else:
        s = menu_map.normalize(action)
    if s is None or s[0] not in ("op", "v3d"):
        return None
    target, props = s[1], s[2]
    for w in WINDOWS:
        if w.match is None:
            continue
        op, want = w.match
        if op == target and all(props.get(k) == val for k, val in want.items()):
            return w
    return None


def find_path(path):
    """The option window of a Maya menu path (explicit ``paths`` first, then its menu twin's, then its action). A twin
    (``menu_map.TWINS``) runs the same Maya command, so its box opens the same window (nHair > Modify Curves
    Bend / Curl / Scale Curvature = the Curves windows)."""
    from ..ui import menu_map
    source = menu_map.TWINS.get(path)
    for w in WINDOWS:
        if path in w.paths:
            return w
    for w in WINDOWS:
        if source is not None and source in w.paths:
            return w
    return find(menu_map.MAP.get(path)) if path in menu_map.MAP else None


# --- saved settings (Maya's saved option values -> add-on preferences) ------------------------------

def _prefs():
    from .. import preferences
    try:
        return preferences.get()
    except KeyError:
        return None


AXES_KEY = "_axes"    # in the saved JSON: how its X / Y / Z values read (scene_axes.VERSION); none = the Y-up reading


def _old_orient_joint(values):
    w = values.get("world")
    if isinstance(w, str) and len(w) == 2:
        axis, sign = scene_axes.signed_from_yup(w[0], w[1])
        values["world"] = axis + sign


# operator option values kept with the windows' ("op_" + operator key, joints._save_options)
_OLD_OPS = {"op_orient_joint": _old_orient_joint,
            "op_mirror_joints": lambda values: scene_axes.old_plane(values, "plane")}


def migrate(data):
    """Saved option values written while the windows read X / Y / Z in the Y-up frame -> scene axes, so every saved
    choice keeps its result (Axis Y = upright becomes Axis Z, Duplicate Special Translate 0 1 0 becomes 0 0 1; an
    aim Up vector 0 1 0 on an object becomes its own 0 0 1)."""
    out = {}
    version = data.get(AXES_KEY, 1)
    for key, values in data.items():
        if key == AXES_KEY or not isinstance(values, dict):
            continue
        values = dict(values)
        window = _BY_KEY.get(key)
        if version < 2:
            if window is not None:
                for f in window.fields:
                    if f.old is not None and f.name in values:
                        f.old(values, f.name)
                if window.old_axes is not None:
                    window.old_axes(values)
            if key in _OLD_OPS:
                _OLD_OPS[key](values)
        if version < 3 and key in _OLD_LOCAL:
            _OLD_LOCAL[key](values)
        out[key] = values
    out[AXES_KEY] = scene_axes.VERSION
    return out


def _old_aim_vectors(values):
    for name in ("aim_vector", "up_vector"):
        scene_axes.old_vector(values, name)


# saved before the aim / motion path vectors read the node's own axes (version 2): an object's Y-up reading
_OLD_LOCAL = {"aim_constraint": _old_aim_vectors, "normal_constraint": _old_aim_vectors,
              "tangent_constraint": _old_aim_vectors,
              "motion_path_attach": lambda v: (scene_axes.old_local_axis(v, "front_axis", "inverse_front"),
                                               scene_axes.old_local_axis(v, "up_axis", "inverse_up"))}


def _load(prefs):
    """The saved option values {key: values} (older Y-up values already turned into scene axes)."""
    try:
        data = json.loads(prefs.option_settings) if prefs is not None and prefs.option_settings else {}
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    if data and data.get(AXES_KEY, 1) < scene_axes.VERSION:
        data = migrate(data)
    return data


def saved(key):
    prefs = _prefs()
    out = _load(prefs).get(key) if key != AXES_KEY else None
    window = _BY_KEY.get(key)
    if out is not None and window is not None:
        out = {**out, **_pref_values(window, prefs, out)}
    return out


def current(key):
    """The values a plain click of ``key``'s command uses: the saved ones over the window's defaults."""
    return {**_BY_KEY[key].defaults(), **(saved(key) or {})}


def _pref_values(window, prefs, stored=()):
    """The window's fields kept in add-on preferences; a value saved with the options before the preference
    existed stays until the preference is set."""
    return {name: getattr(prefs, attr) for name, attr in window.pref_fields.items()
            if hasattr(prefs, attr) and (name not in stored or prefs.is_property_set(attr))}


def store(key, values):
    prefs = _prefs()
    if prefs is None:
        return
    data = _load(prefs)
    data[AXES_KEY] = scene_axes.VERSION
    window = _BY_KEY.get(key)
    for name, attr in (window.pref_fields if window is not None else {}).items():
        if not hasattr(prefs, attr):
            continue
        if values is None:
            prefs.property_unset(attr)       # Reset Settings: the preference's default too
        elif name in values and getattr(prefs, attr) != values[name]:
            setattr(prefs, attr, values[name])
    if values is None:
        data.pop(key, None)
    else:
        data[key] = {k: v for k, v in values.items() if window is None or k not in window.pref_fields}
    prefs.option_settings = json.dumps(data)
    # Python-set add-on preferences don't mark the preferences changed: Auto-Save Preferences would skip them
    bpy.context.preferences.is_dirty = True


def values_of(window, holder):
    out = {}
    for f in window.fields:
        val = getattr(holder, f.name)
        out[f.name] = tuple(val) if f.kind.startswith("vec") or f.kind == 'angle3' else val
    return out


def run(window, context, values):
    """Run ``window``'s command with ``values`` (Maya values, defaults filled in)."""
    v = {**window.defaults(), **(values or {})}
    try:
        res = window.run(context, v)
    except RuntimeError as ex:
        return str(ex).strip().splitlines()[-1]
    return res


def run_saved(window, context):
    return run(window, context, saved(window.key))


# --- the operators --------------------------------------------------------------------------------

_PATHS = {}


def _menu_path(window):
    """The first main-menu path whose action opens ``window`` (windows bound by action, not by path)."""
    if window.key not in _PATHS:
        from ..ui import menu_map
        _PATHS[window.key] = next((p for p, a in menu_map.MAP.items()
                                   if not p.startswith(("Graph Editor/", "Dope Sheet/", "UV Editor/"))
                                   and find(a) is window), None)
    return _PATHS[window.key]


def _record(window, context, res):
    """A window command that ran is Maya's last command (G repeats it with the saved values)."""
    if not window.click_saved or isinstance(res, str) or not (isinstance(res, set) and 'FINISHED' in res):
        return
    from ..ui import menu_map
    path = window.paths[0] if window.paths else _menu_path(window)
    action = menu_map.MAP.get(path) if path else window.match
    if action is None:
        return
    from . import repeat_maya
    repeat_maya.record(path.rsplit("/", 1)[-1] if path else window.title, action, path, context)


def _apply_update(window):
    def update(self, context):
        if not self.apply_now:
            return
        apply_run = getattr(window, "apply_run", None)   # a window whose Apply isn't its command
        if apply_run is not None:
            res = apply_run(context, {**window.defaults(), **values_of(window, self)})
        else:
            res = run(window, context, values_of(window, self))
        store(window.key, values_of(window, self))
        if apply_run is None:
            _record(window, context, res)
        self.apply_now = False
        if isinstance(res, str):
            from ..ui import notices
            notices.show(f"{window.title}: {res}")
    return update


def _save_update(window):
    def update(self, context):
        if self.save_now:
            store(window.key, values_of(window, self))
            self.save_now = False
    return update


def _reset_update(window):
    def update(self, context):
        if self.reset_now:
            for f in window.fields:
                setattr(self, f.name, f.default)
            store(window.key, None)
            self.reset_now = False
    return update


def _make(window):
    ann = {f.name: f.prop() for f in window.fields}
    ann["apply_now"] = BoolProperty(name="Apply", options={'SKIP_SAVE'}, update=_apply_update(window),
                                    description="Run with these settings and keep the window open (Maya Apply)")
    ann["save_now"] = BoolProperty(name="Save Settings", options={'SKIP_SAVE'}, update=_save_update(window),
                                   description="Keep these settings for next time (Maya Edit > Save Settings)")
    ann["reset_now"] = BoolProperty(name="Reset Settings", options={'SKIP_SAVE'}, update=_reset_update(window),
                                    description="Back to the default settings (like Maya's Edit > Reset Settings)")

    def invoke(self, context, event):
        if window.key == "paint_skin_weights":
            return bpy.ops.allset.weight_workspace('INVOKE_DEFAULT')
        prefs = _prefs()
        stored = saved(window.key) or {}
        for name, val in {**stored, **(_pref_values(window, prefs, stored) if prefs else {})}.items():
            if name in ann:
                try:
                    setattr(self, name, val)
                except (TypeError, ValueError):
                    pass
        from .. import preferences
        if preferences.get(context).option_boxes_floating:
            return bpy.ops.allset.option_editor_open(key=window.key, values=json.dumps(values_of(window, self)))
        return context.window_manager.invoke_props_dialog(self, width=window.width, title=window.title,
                                                          confirm_text=window.action)

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.prop(self, "save_now", toggle=True)
        row.prop(self, "reset_now", toggle=True)
        layout.separator()
        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        draw_fields(window, col, self)
        layout.separator()
        layout.prop(self, "apply_now", toggle=True, text=window.apply_text)

    def execute(self, context):
        values = values_of(window, self)
        store(window.key, values)        # Maya keeps the option values of a command that ran
        res = run(window, context, values)
        if isinstance(res, str):
            self.report({'WARNING'}, res)
            return {'CANCELLED'}
        _record(window, context, res)
        return {'FINISHED'} if res is None or 'FINISHED' in res else {'CANCELLED'}

    return type(f"ALLSET_OT_opt_{window.key}", (bpy.types.Operator,), {
        "__annotations__": ann, "bl_idname": window.idname, "bl_label": window.title,
        "bl_description": f"Maya {window.title}", "bl_options": {'UNDO'},    # no redo panel
        "invoke": invoke, "draw": draw, "execute": execute})


def draw_fields(window, layout, holder):
    """The same field schema drives command operators and their modeless option editors."""
    layout.use_property_split = True
    layout.use_property_decorate = False
    fields = list(window.fields)
    values = values_of(window, holder) if window.enabled is not None else None
    i = 0
    while i < len(fields):
        f = fields[i]
        if f.kind == "bool" and f.text in ("X", "Y", "Z"):
            # Maya puts the X / Y / Z check boxes of a constraint on one line
            split = layout.split(factor=0.4)       # Blender's property split: label column 40 %
            split.label(text="")
            row = split.row()
            row.use_property_split = False
            while i < len(fields) and fields[i].kind == "bool" and fields[i].text in ("X", "Y", "Z"):
                row.prop(holder, fields[i].name, text=fields[i].text)
                i += 1
            continue
        i += 1
        cell = layout
        if window.enabled is not None:
            cell = layout.column()
            cell.enabled = window.enabled(values, f.name)
        if f.kind == "bool":
            cell.column(heading=f.label.rstrip(":")).prop(holder, f.name, text=f.text or "")
            continue
        elif f.kind == "enum":
            # an enum without a label is Maya's combo beside the row above (Joint Tool " + "): a drop-down, as
            # expanded buttons without a label Blender stacks it as empty bars
            cell.row().prop(holder, f.name, text=f.label.rstrip(":") or " ",
                           expand=bool(f.label) and len(f.items) <= 4)
        elif f.kind == "curve":
            cell.prop_search(holder, f.name, bpy.data, 'objects', text=f.label.rstrip(':'))
        elif f.kind == "ramp":
            if not isinstance(holder, bpy.types.Operator):   # the graph edits the floating window's values
                cell.operator('allset.bridge_ramp', text='Edit Taper Curve').options = True
        else:
            cell.prop(holder, f.name, text=f.label.rstrip(":"))
    if window.extra is not None:
        window.extra(layout, bpy.context)
    draw_missing(window, layout)


def draw_missing(window, layout):
    """The greyed "Not in Blender" lines, indented (the kit translates each line before its indent)."""
    if window.missing:
        sub = layout.column(align=True)
        sub.enabled = False
        sub.label(text="Not in Blender:")
        for name in window.missing:
            sub.label(text="    " + i18n.iface(name), translate=False)


class ALLSET_OT_option_generic(bpy.types.Operator):
    """Option box of a Maya command whose settings Blender has no equivalent for: the window says so and runs
    the command (Maya: every option box opens a window)"""
    bl_idname = "allset.option_generic"
    bl_label = "Options"
    bl_options = {'INTERNAL'}

    item: bpy.props.StringProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        from .option_windows_render import no_options_text
        text = no_options_text(self.item, context.scene)
        if text:                    # Maya opens no window for these: its Help Line warning
            self.report({'WARNING'}, text)
            return {'CANCELLED'}
        label = self.item.rsplit("/", 1)[-1].rstrip(".").split("#")[0]
        return context.window_manager.invoke_props_dialog(self, width=400, title=f"{label} Options",
                                                          confirm_text=label)

    def draw(self, context):
        from ..ui import chrome, notices
        n = notices.notice(self.item)
        text = ("Maya's settings for this command have no Blender equivalent: it runs with Blender's own."
                + (f" {n[1]}" if n else ""))
        chrome.paragraph(self.layout, context, text, width=380)

    def execute(self, context):
        from ..ui import menu_map
        from ..marking.modal import run_action
        action = menu_map.MAP.get(self.item)
        if action is None:
            return {'CANCELLED'}
        try:
            run_action(context, action, path=self.item)
        except RuntimeError as ex:
            from . import maya_errors
            maya_errors.report_nested(self, ex)       # a Maya Error stays an Error
            return {'CANCELLED'}
        return {'FINISHED'}


classes = tuple(_make(w) for w in WINDOWS) + (ALLSET_OT_option_generic,)
