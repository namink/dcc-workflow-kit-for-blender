# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws a Maya editor's icon row from ``editor_icon_data``: buttons that run an action, toggle a property or open
a submenu, greyed buttons with their notice, the groups that don't fit behind a » menu, and the Stats fields (the
selected keys' time / value). Entry points ``draw_icons``, ``icon_groups``, ``shown_groups``, ``_stats_get`` /
``_stats_set``.
"""

import bpy
import numpy as np
from bpy.props import StringProperty

from .. import i18n
from . import graph_icons, menu_map, menu_sets
from .editor_kinds import GE, DS
from .editor_icon_data import ICONS, NOTICES


def _icon_spec(editor, key):
    return next((it for it in ICONS[editor] if isinstance(it, tuple) and it[0] == key), None)


def _submenu(editor, sub):
    return menu_sets.SUBMENU_IDS.get(f"{editor}/{sub}")


_GROUPS = {}     # editor -> its icon groups (the icon data never changes while the kit runs)


def icon_groups(editor):
    """The icon row split at Maya's separators: lists of items (spec tuples, "STATS", "IMAGE", "UVMAP"). Worked out
    once per editor (a Graph Editor's toolbar row redraws on every played frame); callers only read them."""
    got = _GROUPS.get(editor)
    if got is None:
        got = _GROUPS[editor] = _split_groups(editor)
    return got


def _split_groups(editor):
    groups, cur = [], []
    for it in ICONS[editor]:
        if it == "|":
            if cur:
                groups.append(cur)
            cur = []
        else:
            cur.append(it)
    if cur:
        groups.append(cur)
    return groups


STATS_UNITS = (2.0, 3.5, 3.5)       # "Stats" label, time field, value field (ui_units_x sub-rows)
SEP_UNITS = 0.3                     # Blender's separator in a header row
FOLD = (GE, DS)                     # editors whose toolbar row folds into » when the area is too narrow


def group_px(group, u):
    """Px width of one icon group (aligned row of buttons / the Stats fields), its trailing separator included."""
    from .toolbar_fit import px
    w = 0
    for it in group:
        if it == "STATS":
            w += sum(px(k, u) for k in STATS_UNITS)
        else:
            w += u
    return w + px(SEP_UNITS, u)


def shown_groups(context, editor):
    """How many leading icon groups fit the toolbar row; the rest go behind Maya's » button."""
    groups = icon_groups(editor)
    region = getattr(context, "region", None)
    if editor not in FOLD or region is None or getattr(region, "type", None) != 'FOOTER' or region.width <= 1:
        return len(groups)
    from . import toolbar_fit
    system = context.preferences.system
    scale = system.ui_scale or 1.0
    key = (editor, region.width, scale, system.pixel_size)
    got = _FITS.get(key)
    if got is None:
        if len(_FITS) > 32:
            _FITS.clear()
        u = toolbar_fit.unit(scale, system.pixel_size)
        got = _FITS[key] = toolbar_fit.fit_widths([group_px(g, u) for g in groups], region.width, scale,
                                                  system.pixel_size)
    return got


_FITS = {}       # (editor, footer width, UI scale, pixel size) -> how many groups fit


# area pointer -> (editor, index of the first group behind ») written while the toolbar draws (no ID data written)
_FIRST_HIDDEN = {}


def _draw_stats(layout, context, menu=False):
    scene = context.scene
    if menu:
        layout.prop(scene, "allset_key_time")
        layout.prop(scene, "allset_key_value")
        return
    sub = layout.row(align=True)
    lab = sub.row(align=True)
    lab.ui_units_x = STATS_UNITS[0]
    lab.label(text="Stats")
    for prop, units in (("allset_key_time", STATS_UNITS[1]), ("allset_key_value", STATS_UNITS[2])):
        col = sub.row(align=True)
        col.ui_units_x = units
        col.prop(scene, prop, text="")
    sub.separator()


def draw_icons(layout, context, editor):
    groups = icon_groups(editor)
    n = shown_groups(context, editor)
    area = getattr(context, "area", None)
    if area is not None:
        _FIRST_HIDDEN[area.as_pointer()] = (editor, n)
    for k, group in enumerate(groups[:n]):
        row = layout.row(align=True) if any(isinstance(it, tuple) for it in group) else None
        for it in group:
            if it == "STATS":
                _draw_stats(layout, context)
            elif it == "IMAGE":
                sima = context.space_data
                layout.template_ID(sima, "image", new="image.new", open="image.open")
            elif it == "UVMAP":
                ob = context.edit_object
                if ob is not None and ob.type == 'MESH' and ob.data.uv_layers.active is not None:
                    sub = layout.row()
                    sub.ui_units_x = 5
                    sub.prop(ob.data.uv_layers.active, "name", text="", icon='GROUP_UVS')
            else:
                _draw_icon(row, context, editor, it)
        if k < len(groups) - 1 and row is not None:
            row.separator()
    if n >= len(groups):
        return
    # Maya's overflow arrow at the right end: the groups that don't fit, in a menu (Maya's button order kept)
    from . import status_icons, toolbar_fit
    layout.separator_spacer()
    sub = layout.row(align=True)
    sub.ui_units_x = toolbar_fit.MORE_UNITS
    icon = status_icons.icon("pt_more") if "pt_more" in status_icons.EXTRA else 0
    if icon:
        sub.menu(ALLSET_MT_editor_more.bl_idname, text="", icon_value=icon)
    else:
        sub.menu(ALLSET_MT_editor_more.bl_idname, text="»")


class ALLSET_MT_editor_more(bpy.types.Menu):
    """More toolbar buttons: the ones that don't fit this editor's width"""
    bl_idname = "ALLSET_MT_editor_more"
    bl_label = "More Buttons"

    def draw(self, context):
        area = context.area
        editor, first = _FIRST_HIDDEN.get(area.as_pointer(), (None, 0)) if area is not None else (None, 0)
        if editor not in ICONS:
            return
        layout = self.layout
        for k, group in enumerate(icon_groups(editor)[first:]):
            if k:
                layout.separator()
            for it in group:
                if it == "STATS":
                    _draw_stats(layout, context, menu=True)
                elif isinstance(it, tuple):
                    _draw_icon(layout, context, editor, it, text=it[3])


def _icon_args(editor, key, icon):
    """Button icon keywords: the kit-drawn picture of ``key`` when there is one, else Blender's icon."""
    value = graph_icons.icon_value(editor, key) if editor in (GE, DS) else 0
    return {"icon_value": value} if value else {"icon": icon}


def _draw_icon(row, context, editor, it, text=""):
    key, icon, action, _tip = it
    ic = _icon_args(editor, key, icon)
    if action is None:
        row.operator(ALLSET_OT_editor_icon_unavailable.bl_idname, text=text, **ic).key = f"{editor}|{key}"
        return
    if action[0] == "submenu":
        idname = _submenu(editor, action[1])
        if idname:
            row.menu(idname, text=text, **ic)
        return
    if action[0] in ("prop", "channels"):
        owner, attr = menu_sets.prop_owner(context, action[1])
        if owner is None:
            row.operator(ALLSET_OT_editor_icon_unavailable.bl_idname, text=text, **ic).key = f"{editor}|{key}"
            return
        if action[0] == "channels":
            row.prop(owner, attr, text=text, icon_only=not text)
            return
        props = action[2]
        if "value" not in props:
            row.prop(owner, attr, text=text, toggle=True, **ic)
            return
        current = getattr(owner, attr)
        value = props["value"]
        on = abs(current - value) < 1e-6 if isinstance(value, float) else current == value
        op = row.operator(menu_sets.ALLSET_OT_menu_set_value.bl_idname, text=text, depress=on, **ic)
        op.target, op.value = action[1], repr(value)
        return
    on = _toggle_state(context, key)
    row.operator(ALLSET_OT_editor_icon.bl_idname, text=text, depress=bool(on), **ic).key = f"{editor}|{key}"


def _toggle_state(context, key):
    """Pressed state of icon buttons that run a toggle operator (Maya iconTextCheckBox), None otherwise."""
    if key == "checker_tiles":
        from ..operators import menu_items
        return menu_items.checker_on(context)
    return None


class ALLSET_OT_editor_icon(bpy.types.Operator):
    """Maya editor icon-row button"""
    bl_idname = "allset.editor_icon"
    bl_label = "Editor Button"
    bl_options = {'INTERNAL'}

    key: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        editor, _sep, key = props.key.partition("|")
        it = _icon_spec(editor, key) if editor in ICONS else None
        if it is None:
            return ""
        s = menu_map.normalize(it[2])
        target = f"\nBlender: {s[1]}" if s and s[0] in ("op", "v3d") else ""
        return i18n.compose("Maya: {item}", item=i18n.tip(it[3])) + target

    def execute(self, context):
        editor, _sep, key = self.key.partition("|")
        it = _icon_spec(editor, key) if editor in ICONS else None
        if it is None or it[2] is None:
            return {'CANCELLED'}
        from ..marking.modal import run_action
        try:
            run_action(context, it[2])
        except RuntimeError as ex:
            self.report({'WARNING'}, str(ex).strip().splitlines()[-1])
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_editor_icon_unavailable(bpy.types.Operator):
    """Maya editor button without a Blender counterpart (always greyed out)"""
    bl_idname = "allset.editor_icon_unavailable"
    bl_label = "Not Available"
    bl_options = {'INTERNAL'}

    key: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return False

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        editor, _sep, key = props.key.partition("|")
        it = _icon_spec(editor, key) if editor in ICONS else None
        tip = it[3] if it else key
        sub, line = NOTICES.get(key, ("", i18n.mark("Not in this Blender editor.")))
        tip, sub, line = i18n.tip(tip), i18n.tip(sub), i18n.tip(line)
        if sub:
            return i18n.compose("Maya: {item} (greyed)  →  {substitute}", item=tip, substitute=sub) + "\n" + line
        return i18n.compose("Maya: {item} (greyed)", item=tip) + "\n" + line

    def execute(self, context):
        return {'CANCELLED'}


# --- Stats fields: the selected key's time / value (Maya Graph Editor / Dope Sheet icon row) -----------------------

def _kind(fc):
    tail = fc.data_path.rsplit(".", 1)[-1]
    return "LENGTH" if tail in {"location", "delta_location"} else \
        "ROTATION" if tail in {"rotation_euler", "delta_rotation_euler"} else "NONE"


def selected_points(context):
    """[(fcurve, keyframe point)] selected in the editor the context belongs to (Graph Editor / Dope Sheet)."""
    out = []
    for fc in getattr(context, "editable_fcurves", None) or ():
        out += [(fc, kp) for kp in fc.keyframe_points if kp.select_control_point]
    return out


_STATS = {}     # (area pointer, field) -> the Stats text while playback runs (``_stats_get``)


def drop_stats(*_args):
    """Playback starts or stops, a key changes (an Action update), a file loads: the Stats are read again."""
    _STATS.clear()


def _stats_get(field):
    axis = 0 if field == "time" else 1

    def get(scene):
        # Playing changes neither which keys are selected nor their time / value (a key set while playing updates
        # its Action, which drops the kept text): the text found on the first played frame is shown again instead
        # of reading every listed curve's keys on every frame (the editor's toolbar row redraws on each one).
        context = bpy.context
        screen = getattr(context, "screen", None)
        key = None
        if screen is not None and screen.is_animation_playing:
            area = getattr(context, "area", None)
            key = (area.as_pointer() if area is not None else 0, field)
            got = _STATS.get(key)
            if got is not None:
                return got
        text = read(scene)
        if key is not None:
            if len(_STATS) > 64:
                _STATS.clear()
            _STATS[key] = text
        return text

    def read(scene):
        from . import cb_entry
        first, values = None, set()
        for fc in getattr(bpy.context, "editable_fcurves", None) or ():
            kps = fc.keyframe_points
            n = len(kps)
            if not n:
                continue
            sel = np.empty(n, dtype=bool)
            kps.foreach_get("select_control_point", sel)
            if not sel.any():
                continue
            co = np.empty(n * 2, dtype=np.float64)
            kps.foreach_get("co", co)
            picked = co[axis::2][sel]
            if first is None:
                first = (fc, float(picked[0]))
            # the rounded values of the selected keys (equal values round alike)
            values.update(round(float(v), 6) for v in (picked if np.isnan(picked).any() else np.unique(picked)))
            if len(values) > 1:
                return "-"          # Maya shows a blank field for several values; "-" = mixed
        if first is None:
            return ""
        fc, value = first
        if field == "time":
            return cb_entry.fmt_number(value)
        return cb_entry.format_value(value, _kind(fc), scene)
    return get


def _stats_set(field):
    def set_(scene, text):
        from . import cb_entry
        for fc, kp in selected_points(bpy.context):
            old = kp.co.x if field == "time" else kp.co.y
            try:
                new = cb_entry.parse_entry(text, old, "NONE" if field == "time" else _kind(fc), scene)
            except (ValueError, TypeError):
                return
            d = new - old
            axis = 0 if field == "time" else 1
            for v in (kp.co, kp.handle_left, kp.handle_right):
                v[axis] += d
            fc.update()
    return set_
