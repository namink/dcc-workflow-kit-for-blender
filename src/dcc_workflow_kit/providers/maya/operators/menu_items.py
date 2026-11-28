# SPDX-License-Identifier: GPL-3.0-or-later
"""Small Maya menu commands Blender has no single operator for.

Each reproduces the Maya result with a few data / bmesh edits: Modify > Naming, Mesh Display > Soften/Harden
Edges, Edit Mesh > Detach / Edit Edge Flow / Wedge, Deform > Nonlinear, Display > Object Display, Mesh Tools >
Sculpting Tools, UV > Assign Checker Shader, the Audio menu, Stereo > Create, and ``menu_note`` for items whose
Maya behaviour already is Blender's (only the notice is shown).

Code: soften_harden_edges (Soften/Harden Edges), edit_mesh_items (Detach / Edit Edge Flow / Wedge), uv_checker
(checker shader and checker display); this module keeps Naming, Nonlinear, Object Display, Sculpting Tools / Paint
Hair Follicles, Audio, Stereo, menu_note, the classes tuple and re-exports.
"""

import re

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector

from .. import results
from .soften_harden_edges import (SMOOTH_BY_ANGLE, ALLSET_OT_soften_harden, giving_way,  # noqa: F401
                                  smooth_by_angle, smooth_by_angle_inputs, smooth_by_angle_mods, soften_harden,
                                  soften_harden_edit)
from .edit_mesh_items import ALLSET_OT_detach, ALLSET_OT_edge_flow, ALLSET_OT_wedge, detach, edge_flow  # noqa: F401
from .uv_checker import (CHECKER_DENSITY, CHECKER_IMAGE, CHECKER_MAT, CHECKER_PREV, DENSITY_NODE,  # noqa: F401
                         ALLSET_OT_checker_density, ALLSET_OT_checker_shader, ALLSET_OT_checker_toggle,
                         _checker_material, checker_density, checker_hide, checker_objects, checker_on,
                         checker_show, set_checker_density)


def _hierarchy(objects):
    """``objects`` and all their descendants, parents first, each once."""
    out, seen = [], set()

    def walk(ob):
        if ob.name in seen:
            return
        seen.add(ob.name)
        out.append(ob)
        for child in ob.children:
            walk(child)
    for ob in objects:
        walk(ob)
    return out


def _rename(ob, fn):
    """Rename the object and (like Maya renames the shape with its transform) its single-user data."""
    ob.name = fn(ob.name)
    data = ob.data
    if data is not None and data.users == 1 and data.library is None:
        data.name = fn(data.name)


# --- Modify > Naming --------------------------------------------------------------------------

class ALLSET_OT_prefix_hierarchy(bpy.types.Operator):
    """Put a prefix in front of the names of the selected objects and everything under them
    (Maya Modify > Prefix Hierarchy Names)"""
    bl_idname = "allset.prefix_hierarchy"
    bl_label = "Prefix Hierarchy Names"
    bl_options = {'REGISTER', 'UNDO'}

    prefix: StringProperty(name="Prefix", default="prefix_")

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if not self.prefix:
            return {'CANCELLED'}
        obs = _hierarchy(context.selected_objects)
        for ob in obs:
            _rename(ob, lambda name: self.prefix + name)
        results.result(self, f"Prefixed {len(obs)} name(s)")
        return {'FINISHED'}


def replace_name(name, search, replace):
    """Maya Search and Replace Names: "Search For" is a regular expression and its first match is replaced, so
    ``$`` adds a suffix and ``^`` a prefix. Text that is not a valid expression is searched as plain text."""
    try:
        pattern = re.compile(search)
    except re.error:
        pattern = re.compile(re.escape(search))
    return pattern.sub(lambda _m: replace, name, count=1)


class ALLSET_OT_search_replace_names(bpy.types.Operator):
    """Replace text in object names: in the selected hierarchies, the selection only, or every object
    (Maya Modify > Search and Replace Names)"""
    bl_idname = "allset.search_replace_names"
    bl_label = "Search and Replace Names"
    bl_options = {'REGISTER', 'UNDO'}

    search: StringProperty(name="Search For", description="Text to find; like Maya, $ = the end of the name "
                           "(adds a suffix), ^ = the start (adds a prefix), . = any character")
    replace: StringProperty(name="Replace With")
    scope: EnumProperty(name="Operation", default='HIERARCHY', items=(
        ('HIERARCHY', "Hierarchy", "The selected objects and everything under them"),
        ('SELECTED', "Selected", "Only the selected objects"),
        ('ALL', "All", "Every object in the scene")))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if not self.search:
            self.report({'WARNING'}, "Nothing to search for")
            return {'CANCELLED'}
        if self.scope == 'ALL':
            obs = list(context.scene.objects)
        elif self.scope == 'SELECTED':
            obs = list(context.selected_objects)
        else:
            obs = _hierarchy(context.selected_objects)
        n = 0
        for ob in obs:
            if replace_name(ob.name, self.search, self.replace) != ob.name:
                _rename(ob, lambda name: replace_name(name, self.search, self.replace))
                n += 1
        results.result(self, f"Renamed {n} object(s)")
        return {'FINISHED'}


# --- Deform > Nonlinear -----------------------------------------------------------------------

NONLINEAR = (('BEND', "Bend", "Maya bend1: Simple Deform Bend"),
             ('TAPER', "Flare", "Maya flare1: Simple Deform Taper"),
             ('STRETCH', "Squash", "Maya squash1: Simple Deform Stretch"),
             ('TWIST', "Twist", "Maya twist1: Simple Deform Twist"))
_NONLINEAR_NAME = {'BEND': "bend", 'TAPER': "flare", 'STRETCH': "squash", 'TWIST': "twist"}
_DEFORMABLE = {'MESH', 'CURVE', 'SURFACE', 'LATTICE'}


def world_bounds(objects):
    pts = [ob.matrix_world @ Vector(c) for ob in objects for c in ob.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


class ALLSET_OT_nonlinear(bpy.types.Operator):
    """Add a nonlinear deformer to the selected objects: Simple Deform with Maya's neutral start value, deforming
    around the handle ``<type>NHandle`` at the objects' bounding-box centre (Maya Deform > Nonlinear)"""
    bl_idname = "allset.nonlinear"
    bl_label = "Nonlinear Deformer"
    bl_options = {'REGISTER', 'UNDO'}

    method: EnumProperty(items=NONLINEAR, name="Type")

    @classmethod
    def poll(cls, context):
        return any(ob.type in _DEFORMABLE for ob in context.selected_objects)

    def execute(self, context):
        base = _NONLINEAR_NAME[self.method]
        obs = [ob for ob in context.selected_objects if ob.type in _DEFORMABLE]
        names = {md.name for ob in bpy.data.objects for md in ob.modifiers} | {o.name for o in bpy.data.objects}
        n = 1
        while f"{base}{n}" in names or f"{base}{n}Handle" in names:
            n += 1
        # Maya: the handle sits at the bounding-box centre, pointing
        # up (Maya +Y = Blender +Z), scaled to half the height; low / high bound -1 / 1 = the whole object.
        lo, hi = world_bounds(obs)
        handle = bpy.data.objects.new(f"{base}{n}Handle", None)
        context.view_layer.active_layer_collection.collection.objects.link(handle)
        handle.empty_display_type = 'SINGLE_ARROW'
        handle.empty_display_size = 1.0
        handle.location = (lo + hi) / 2
        half = max((hi.z - lo.z) / 2, 1e-6)
        handle.scale = (half, half, half)
        for ob in obs:
            md = ob.modifiers.new(f"{base}{n}", 'SIMPLE_DEFORM')
            md.deform_method = self.method
            md.deform_axis = 'Z'
            md.origin = handle
            md.angle = 0.0
            md.factor = 0.0
        return {'FINISHED'}


# --- Display > Object Display -----------------------------------------------------------------

TEMPLATE_PROP = "allset_template"
DISPLAY = (('TEMPLATE', "Template", "Grey wireframe that can't be selected in the view"),
           ('UNTEMPLATE', "Untemplate", "Undo Template (on the selection, else on every templated object)"),
           ('BBOX', "Bounding Box", "Draw as a bounding box"),
           ('NO_BBOX', "No Bounding Box", "Draw the geometry again"))


class ALLSET_OT_object_display(bpy.types.Operator):
    """Maya Display > Object Display: template / bounding box display of the selected objects"""
    bl_idname = "allset.object_display"
    bl_label = "Object Display"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(items=DISPLAY, name="Display")

    def execute(self, context):
        obs = list(context.selected_objects)
        if self.kind == 'UNTEMPLATE':
            obs = [ob for ob in obs if ob.get(TEMPLATE_PROP)] or \
                [ob for ob in context.scene.objects if ob.get(TEMPLATE_PROP)]
        if not obs:
            self.report({'WARNING'}, "Nothing selected.")
            return {'CANCELLED'}
        for ob in obs:
            if self.kind == 'TEMPLATE':
                ob[TEMPLATE_PROP] = ob.display_type
                ob.display_type = 'WIRE'
                ob.select_set(False)
                ob.hide_select = True
            elif self.kind == 'UNTEMPLATE':
                ob.hide_select = False
                ob.display_type = ob.get(TEMPLATE_PROP) or 'TEXTURED'
                del ob[TEMPLATE_PROP]
            elif self.kind == 'BBOX':
                ob.display_type = 'BOUNDS'
            elif ob.display_type == 'BOUNDS':
                ob.display_type = 'TEXTURED'
        return {'FINISHED'}


# --- Mesh Tools > Sculpting Tools -------------------------------------------------------------

SCULPT_LIBRARY = "brushes/essentials_brushes-mesh_sculpt.blend/Brush/"


class ALLSET_OT_sculpt_tool(bpy.types.Operator):
    """Sculpt the active mesh with this brush (Maya Mesh Tools > Sculpting Tools)"""
    bl_idname = "allset.sculpt_tool"
    bl_label = "Sculpting Tool"
    bl_options = {'REGISTER', 'UNDO'}

    brush: StringProperty(name="Brush", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'MESH'

    def execute(self, context):
        ob = context.active_object
        if context.mode != 'SCULPT' and not ob.visible_get():
            # Maya switches the tool without a check; Blender can't
            # sculpt a hidden object, so the kit says so and stays in object mode
            self.report({'WARNING'}, f"{ob.name} is hidden: show it (Display > Show) to sculpt it.")
            return {'CANCELLED'}
        if context.mode != 'SCULPT':
            bpy.ops.object.mode_set(mode='SCULPT')
        try:
            res = _activate_brush(self.brush)
        except RuntimeError as ex:
            if context.window is None:
                self.report({'WARNING'}, str(ex).strip().splitlines()[-1])
                return {'CANCELLED'}
            # 5.2: right after the switch to sculpt mode the brush operator may still see the old mode
            # ("wrong object mode", GUI): the timer below tries again
            res = {'CANCELLED'}
        if res != {'FINISHED'} and context.window is not None:
            # The essentials library loads in the background on the first use in a session (GUI:
            # the operator cancels with "Asset loading is unfinished"): try again for a few seconds.
            _retry_brush(self.brush)
        return {'FINISHED'}



class ALLSET_OT_paint_hair_follicles(bpy.types.Operator):
    """Paint hair on the selected mesh (Maya nHair > Paint Hair Follicles; Blender: a hair Curves object on that
    surface, groomed in Sculpt mode)"""
    bl_idname = "allset.paint_hair_follicles"
    bl_label = "Paint Hair Follicles"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Maya switches to the Paint Hair Follicles tool for any selection, a mesh included
        # (Maya). Blender grows hair as a Curves object attached to a surface mesh:
        # the mesh's hair (its first Curves object) or a new empty one, then Sculpt mode.
        ob = context.active_object
        if ob is not None and ob.mode != 'OBJECT' and ob.type != 'CURVES':
            bpy.ops.object.mode_set(mode='OBJECT')
        if ob is not None and ob.type == 'MESH':
            hair = next((o for o in context.scene.objects
                         if o.type == 'CURVES' and getattr(o.data, "surface", None) is ob), None)
            if hair is None:
                bpy.ops.object.curves_empty_hair_add(align='WORLD', location=ob.matrix_world.translation)
                hair = context.view_layer.objects.active
            else:
                for o in context.selected_objects:
                    o.select_set(False)
                hair.select_set(True)
                context.view_layer.objects.active = hair
            ob = hair
        if ob is None or ob.type != 'CURVES':
            self.report({'WARNING'}, "Paint Hair Follicles: select a mesh to paint hair on.")
            return {'CANCELLED'}
        if not ob.visible_get():
            self.report({'WARNING'}, f"{ob.name} is hidden: show it (Display > Show) to paint hair.")
            return {'CANCELLED'}
        if ob.mode != 'SCULPT_CURVES':
            bpy.ops.object.mode_set(mode='SCULPT_CURVES')
        results.result(self, f"Paint Hair Follicles on {ob.name}")
        return {'FINISHED'}


BRUSH_RETRY_S, BRUSH_RETRIES = 0.2, 25


def _activate_brush(brush, window=None, library=SCULPT_LIBRARY):
    """``brush.asset_activate`` in a 3D View of the window when there is one: 5.2 checks the mode there and refuses
    from another editor (a shelf button: "Unable to activate brush, wrong object mode", GUI)."""
    window = window or bpy.context.window
    area = next((a for a in window.screen.areas if a.type == 'VIEW_3D'), None) if window else None
    region = next((r for r in area.regions if r.type == 'WINDOW'), None) if area else None
    kwargs = dict(asset_library_type='ESSENTIALS', relative_asset_identifier=library + brush)
    if region is None:
        return bpy.ops.brush.asset_activate(**kwargs)
    with bpy.context.temp_override(window=window, area=area, region=region):
        return bpy.ops.brush.asset_activate(**kwargs)


def _retry_brush(brush, library=SCULPT_LIBRARY, mode='SCULPT'):
    left = [BRUSH_RETRIES]

    def tick():
        left[0] -= 1
        win = bpy.context.window_manager.windows[0] if bpy.context.window_manager.windows else None
        if win is None or bpy.context.mode != mode:
            return None
        try:
            done = _activate_brush(brush, win, library) == {'FINISHED'}
        except RuntimeError:
            done = False
        return None if done or left[0] <= 0 else BRUSH_RETRY_S
    bpy.app.timers.register(tick, first_interval=BRUSH_RETRY_S)


# --- Generate > Interactive Grooming Tools ----------------------------------------------------

CURVES_LIBRARY = "brushes/essentials_brushes-curve_sculpt.blend/Brush/"


class ALLSET_OT_groom_brush(bpy.types.Operator):
    """Groom the hair with this hair sculpt brush (Maya Generate > Interactive Grooming Tools)"""
    bl_idname = "allset.groom_brush"
    bl_label = "Grooming Tool"
    bl_options = {'REGISTER', 'UNDO'}

    brush: StringProperty(name="Brush", options={'SKIP_SAVE'})

    def execute(self, context):
        # same target as Paint Hair Follicles: the hair Curves object, or the selected mesh's hair (made if missing)
        if context.mode != 'SCULPT_CURVES' and bpy.ops.allset.paint_hair_follicles() != {'FINISHED'}:
            self.report({'WARNING'}, "Select a hair Curves object or the mesh it grows on.")
            return {'CANCELLED'}
        try:
            res = _activate_brush(self.brush, library=CURVES_LIBRARY)
        except RuntimeError as ex:
            if context.window is None:
                self.report({'WARNING'}, str(ex).strip().splitlines()[-1])
                return {'CANCELLED'}
            res = {'CANCELLED'}
        if res != {'FINISHED'} and context.window is not None:
            _retry_brush(self.brush, CURVES_LIBRARY, 'SCULPT_CURVES')
        return {'FINISHED'}


# --- Audio ------------------------------------------------------------------------------------

def _strips(scene, create=False):
    if scene.sequence_editor is None:
        if not create:
            return None
        scene.sequence_editor_create()
    from .. import compat
    return compat.strips(scene.sequence_editor)


class ALLSET_OT_import_audio(bpy.types.Operator, ImportHelper):
    """Import a sound at the start of the time slider; it plays with the scene (Maya Audio > Import Audio)"""
    bl_idname = "allset.import_audio"
    bl_label = "Import Audio"
    bl_options = {'REGISTER', 'UNDO'}

    filter_glob: StringProperty(default="*.wav;*.mp3;*.ogg;*.flac;*.aif;*.aiff;*.m4a", options={'HIDDEN'})

    def execute(self, context):
        import os
        scene = context.scene
        strips = _strips(scene, create=True)
        try:
            strip = strips.new_sound(os.path.basename(self.filepath), self.filepath, 1, scene.frame_start)
        except RuntimeError as ex:
            self.report({'ERROR'}, str(ex).strip())
            return {'CANCELLED'}
        results.result(self, f"Imported {strip.name}")
        return {'FINISHED'}


class ALLSET_OT_delete_sounds(bpy.types.Operator):
    """Delete the scene's sounds (Maya Audio > Delete Sounds)"""
    bl_idname = "allset.delete_sounds"
    bl_label = "Delete Sounds"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        strips = _strips(context.scene)
        sounds = [s for s in strips if s.type == 'SOUND'] if strips is not None else []
        for s in sounds:
            strips.remove(s)
        results.result(self, f"Deleted {len(sounds)} sound(s)")
        return {'FINISHED'}


# --- Stereo > Create --------------------------------------------------------------------------

class ALLSET_OT_stereo_camera(bpy.types.Operator):
    """Create a stereo camera: a Maya camera with Blender's stereoscopy (Views) turned on
    (Maya Stereo > Create > Stereo Camera)"""
    bl_idname = "allset.stereo_camera"
    bl_label = "Stereo Camera"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from . import create
        ob = create.create(context, 'CAMERA', maya_naming=False)
        from . import naming
        naming.apply_maya_name(ob, "stereoCamera")
        render = context.scene.render
        render.use_multiview = True
        render.views_format = 'STEREO_3D'
        return {'FINISHED'}


# --- notice-only items ------------------------------------------------------------------------

class ALLSET_OT_menu_note(bpy.types.Operator):
    """Maya item whose behaviour already is Blender's: shows the notice"""
    bl_idname = "allset.menu_note"
    bl_label = "Note"
    bl_options = {'INTERNAL'}

    item: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        from ..ui import notices
        n = notices.notice(self.item)
        if n:
            notices.show(f"{self.item.rsplit('/', 1)[-1]}: {n[1]}")
            results.result(self, n[1])
        return {'FINISHED'}


classes = (ALLSET_OT_prefix_hierarchy, ALLSET_OT_search_replace_names, ALLSET_OT_soften_harden,
           ALLSET_OT_detach, ALLSET_OT_edge_flow, ALLSET_OT_wedge, ALLSET_OT_nonlinear,
           ALLSET_OT_object_display, ALLSET_OT_sculpt_tool, ALLSET_OT_checker_shader, ALLSET_OT_checker_toggle, ALLSET_OT_checker_density, ALLSET_OT_import_audio,
           ALLSET_OT_delete_sounds, ALLSET_OT_stereo_camera, ALLSET_OT_menu_note, ALLSET_OT_paint_hair_follicles,
           ALLSET_OT_groom_brush)
