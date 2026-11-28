# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's Time Slider RMB menu (Cut / Copy / Paste / Delete / Snap, Keys, Tangents, Playback Speed / Looping, Set
Range to, Playblast) and the operator that opens it; items with no Blender counterpart are greyed with a note
(``TIME_NOTICES``). The key actions: ``operators/time_keys``.
"""

import bpy

from .. import i18n
from .time_slider_view import _is_timeline


# Time Slider items with no Blender equivalent: (label, Help Line text)
TIME_NOTICES = {
    "Paste Connect": "Blender pastes keys as they were copied: no connect (offset) paste.",
    "Play Every Frame, Free": "Blender never plays faster than the scene frame rate.",
    "Enabled Clips": "Blender has no Time Editor clips (NLA strips instead).",
}


class ALLSET_OT_time_slider_menu(bpy.types.Operator):
    """Maya Time Slider menu (RMB on the Time Slider)"""
    bl_idname = "allset.time_slider_menu"
    bl_label = "Time Slider Menu"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if not _is_timeline(context):
            return {'PASS_THROUGH'}
        from . import time_slider_bookmarks
        if time_slider_bookmarks.open_menu(context, event):     # on the bookmark strip: Maya's bookmark menu
            return {'FINISHED'}
        bpy.ops.wm.call_menu(name=ALLSET_MT_time_slider.__name__)
        return {'FINISHED'}


# the 3D View keymap whose Delete runs for each edit mode
_MODE_KEYMAP = {"OBJECT": "Object Mode", "EDIT_MESH": "Mesh", "EDIT_CURVE": "Curve", "EDIT_CURVES": "Curves",
                "EDIT_SURFACE": "Curve", "EDIT_ARMATURE": "Armature", "POSE": "Pose", "EDIT_LATTICE": "Lattice",
                "EDIT_METABALL": "Metaball", "EDIT_GREASE_PENCIL": "Grease Pencil Edit Mode"}


def _view_delete(context, key):
    """(operator idname, properties) of the Delete the 3D View runs for ``key`` in the current mode, or None."""
    kc = context.window_manager.keyconfigs.user
    km = kc.keymaps.get(_MODE_KEYMAP.get(context.mode, "")) if kc else None
    if km is None:
        return None
    for kmi in km.keymap_items:
        if (kmi.active and kmi.type == key and kmi.value == 'PRESS' and not kmi.any
                and not (kmi.shift or kmi.ctrl or kmi.alt or kmi.oskey)):
            props = kmi.properties
            kw = {p: getattr(props, p) for p in props.bl_rna.properties.keys()
                  if p != "rna_type" and props.is_property_set(p)} if props else {}
            return kmi.idname, kw
    return None


class ALLSET_OT_time_slider_delete(bpy.types.Operator):
    """Delete over the Time Slider deletes what is selected, as in the viewport (Maya); the keys of a highlighted
    range are deleted from the Time Slider menu"""
    bl_idname = "allset.time_slider_delete"
    bl_label = "Delete"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if not _is_timeline(context):
            return {'PASS_THROUGH'}
        found = _view_delete(context, event.type)
        areas = [a for a in context.window.screen.areas if a.type == 'VIEW_3D']
        if found is None or not areas:
            return {'CANCELLED'}
        area = max(areas, key=lambda a: a.width * a.height)
        region = next(r for r in area.regions if r.type == 'WINDOW')
        idname, kw = found
        mod, name = idname.split(".", 1)
        op = getattr(getattr(bpy.ops, mod), name)
        with context.temp_override(area=area, region=region, space_data=area.spaces.active):
            if not op.poll():
                return {'CANCELLED'}
            result = op('EXEC_DEFAULT', **kw)
        return {'FINISHED'} if 'FINISHED' in result else {'CANCELLED'}


class ALLSET_OT_time_slider_unavailable(bpy.types.Operator):
    """Time Slider item with no Blender equivalent (greyed)"""
    bl_idname = "allset.time_slider_unavailable"
    bl_label = "Not Available"
    bl_options = {'INTERNAL'}

    item: bpy.props.StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return False

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        line = TIME_NOTICES.get(props.item, "")
        if line:
            from . import notices
            notices.show(f"{props.item}: {line}")
        return f"Maya: Time Slider > {props.item}\n{line}"

    def execute(self, context):
        return {'CANCELLED'}


def _keys(layout, action, text=None, **props):
    op = layout.operator("allset.time_keys", text=text)
    op.action = action
    for k, v in props.items():
        setattr(op, k, v)
    return op


def _grey(layout, label):
    layout.operator(ALLSET_OT_time_slider_unavailable.bl_idname, text=label).item = label


class ALLSET_MT_time_slider(bpy.types.Menu):
    """Maya Time Slider menu, in Maya's order"""
    bl_label = "Time Slider"

    def draw(self, context):
        lay = self.layout
        _keys(lay, "CUT", "Cut")
        _keys(lay, "COPY", "Copy")
        lay.menu("ALLSET_MT_time_slider_paste", text="Paste")
        _keys(lay, "DELETE", "Delete")
        _keys(lay, "SNAP", "Snap")
        lay.menu("ALLSET_MT_time_slider_keys", text="Keys")
        lay.menu("ALLSET_MT_time_slider_tangents", text="Tangents")
        lay.separator()
        lay.menu("ALLSET_MT_time_slider_speed", text="Playback Speed")
        lay.menu("ALLSET_MT_time_slider_looping", text="Playback Looping")
        lay.menu("ALLSET_MT_time_slider_range", text="Set Range to")
        lay.separator()
        op = lay.operator("allset.menu_run", text="Playblast...")
        op.op, op.props = "render.opengl", '{"animation": true}'


class ALLSET_MT_time_slider_paste(bpy.types.Menu):
    bl_label = "Paste"

    def draw(self, context):
        _keys(self.layout, "PASTE", "Paste")
        _grey(self.layout, "Paste Connect")


class ALLSET_MT_time_slider_keys(bpy.types.Menu):
    bl_label = "Keys"

    def draw(self, context):
        for action, label in (("TO_KEY", "Convert to Key"), ("TO_BREAKDOWN", "Convert to Breakdown"),
                              ("ADD_INBETWEEN", "Add Inbetween"), ("REMOVE_INBETWEEN", "Remove Inbetween")):
            _keys(self.layout, action, label)


class ALLSET_MT_time_slider_tangents(bpy.types.Menu):
    bl_label = "Tangents"

    def draw(self, context):
        for kind in ("SPLINE", "LINEAR", "CLAMPED", "STEPPED", "FLAT", "PLATEAU", "AUTO"):
            _keys(self.layout, "TANGENT", kind.title(), tangent=kind)


class ALLSET_MT_time_slider_speed(bpy.types.Menu):
    bl_label = "Playback Speed"

    def draw(self, context):
        lay = self.layout
        lay.prop_enum(context.scene, "sync_mode", 'FRAME_DROP', text="Real-time")
        _grey(lay, "Play Every Frame, Free")
        lay.prop_enum(context.scene, "sync_mode", 'NONE', text="Play Every Frame, Max Real-time")


class ALLSET_MT_time_slider_looping(bpy.types.Menu):
    bl_label = "Playback Looping"

    def draw(self, context):
        lay = self.layout
        for value, label in (('ONCE', "Once"), ('OSCILLATE', "Oscillate"), ('CONTINUOUS', "Continuous")):
            lay.prop_enum(context.scene, "allset_playback_loop", value, text=label)


class ALLSET_MT_time_slider_range(bpy.types.Menu):
    bl_label = "Set Range to"

    def draw(self, context):
        lay = self.layout
        for mode, label in (("START_END", "Start/End"), ("MIN_MAX", "Min/Max"), ("SELECTED", "Selected"),
                            ("SOUND", "Sound Length")):
            lay.operator("allset.time_set_range", text=label).mode = mode
        _grey(lay, "Enabled Clips")


TIME_SLIDER_MENUS = (ALLSET_MT_time_slider, ALLSET_MT_time_slider_paste, ALLSET_MT_time_slider_keys,
                     ALLSET_MT_time_slider_tangents, ALLSET_MT_time_slider_speed,
                     ALLSET_MT_time_slider_looping, ALLSET_MT_time_slider_range)
