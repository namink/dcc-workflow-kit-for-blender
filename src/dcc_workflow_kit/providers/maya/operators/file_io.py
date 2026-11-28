# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya File > Import / Export All / Export Selection: one file dialog with Files of type and an Options panel
.

Maya opens a single dialog for every format and picks the translator from "Files of type" (or the extension,
"Best Guess" on import); Blender has one operator per format. ``allset.file_dialog`` is that single dialog: the
Blender file browser with this operator's options in its side panel (Maya's Options pane), Files of type at the top
of it, and the Maya presets — a Maya scene is in cm with Y up, so exchange formats get Maya's scale and axes
(``import_args`` / ``export_args``, pure functions the headless tests check) — then runs the format's own operator.

Code: file_io_import (after-import conversion and Maya names), file_io_export (writers with the Maya preset);
this module keeps the formats table, the preset arguments, .blend import / export, the file dialog operators and
re-exports.
"""

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from .. import results
from . import project, units
from .file_io_import import (SCOPE_NAMES, shape_name, maya_free_name, bake_conversion, maya_names,  # noqa: F401
                             after_import, normalise_skin_weights)
from .file_io_export import MAYA_MPU, usd_maya_axes, write, rig_fbx_maya  # noqa: F401

# (id, Files of type label, extension written, file filter)
FORMATS = (
    ('BLEND', "Maya Scenes (.blend)", ".blend", "*.blend"),
    ('FBX', "FBX (.fbx)", ".fbx", "*.fbx"),
    ('OBJ', "OBJ (.obj)", ".obj", "*.obj"),
    ('ABC', "Alembic (.abc)", ".abc", "*.abc"),
    ('USD', "USD (.usd .usda .usdc .usdz)", ".usd", "*.usd;*.usda;*.usdc;*.usdz"),
    ('GLTF', "glTF 2.0 (.glb .gltf)", ".glb", "*.glb;*.gltf"),
)
_BY_ID = {f[0]: f for f in FORMATS}
_EXT = {ext: f[0] for f in FORMATS for ext in f[3].replace("*", "").split(";")}
ALL_GLOB = ";".join(f[3] for f in FORMATS)
IMPORT_TYPES = (('AUTO', "Best Guess (by extension)", "Pick the format from the file's extension (Maya Best Guess)"),
                *((f[0], f[1], "") for f in FORMATS))
EXPORT_TYPES = tuple((f[0], f[1], "") for f in FORMATS)
MODES = (('IMPORT', "Import", "Maya File > Import"), ('EXPORT_ALL', "Export All", "Maya File > Export All"),
         ('EXPORT_SELECTION', "Export Selection", "Maya File > Export Selection"))


# Maya workspace file rules: where the dialog starts per format; the
# others (scenes, FBX, USD, glTF, Best Guess) start in the scenes folder.
FILE_RULES = {'OBJ': "data", 'ABC': os.path.join("cache", "alembic")}


def start_folder(context, fmt):
    """The project folder the dialog opens in for ``fmt`` (made if missing, like Maya's workspace)."""
    root = project.ensure_root(context)
    folder = os.path.join(root, FILE_RULES.get(fmt, "scenes"))
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = root
    return folder


def format_of(path):
    """Format id for a file name ("" if no format reads it)."""
    return _EXT.get(os.path.splitext(path)[1].lower(), "")


def import_args(fmt, k, maya=True):
    """(operator id, kwargs) that import ``fmt`` into a scene where one Maya unit = ``k`` BU (units.maya_unit).

    Maya writes centimetres with Y up: FBX carries its unit and axes and Blender's
    importer converts both itself; OBJ and Alembic have no unit, so their numbers are Maya units (× k) and Y up;
    USD carries metersPerUnit, which Blender converts to metres, so cm files need ×100 to become Maya units.
    Blender's readers leave that conversion on the objects' channels (Rotate X 90, Scale 0.01):
    ``after_import`` moves it into the geometry (FBX's own ``bake_space_transform`` does it there).
    Maya writes frame 1 at FBX time 1/24 s, which Blender already reads as frame 1 (no extra offset).
    OBJ: Maya names the object with ``g`` (no ``o`` line), so groups split the objects.
    """
    if fmt == 'FBX':
        return "import_scene.fbx", ({"bake_space_transform": True, "anim_offset": 0.0} if maya else {})
    if fmt == 'OBJ':
        return "wm.obj_import", ({"global_scale": k, "forward_axis": 'NEGATIVE_Z', "up_axis": 'Y',
                                  "use_split_groups": True} if maya else {})
    if fmt == 'ABC':
        return "wm.alembic_import", ({"scale": k} if maya else {})
    if fmt == 'USD':
        return "wm.usd_import", ({"scale": 100.0 * k, "apply_unit_conversion_scale": True} if maya else {})
    if fmt == 'GLTF':
        return "import_scene.gltf", {}
    raise ValueError(fmt)


def export_args(fmt, k, selection, maya=True):
    """(operator id, kwargs) that write ``fmt`` the way Maya reads it back: centimetres (one Maya unit per
    ``k`` BU), Y up; ``selection`` = only the selected objects (Export Selection).

    Maya must read the same channels the kit shows — no Rotate X -90 / Scale 100 from the axis / unit
    conversion. FBX bakes it into the geometry itself (``bake_space_transform``) and writes the timeline as one
    take (the NLA-strip default wrote no animation without strips); OBJ gets ``g`` lines and Alembic / USD are
    scaled / converted around Blender's writers (``write``, ``after_export``)."""
    if fmt == 'FBX':
        # Blender's FBX writer stores the scene unit (UnitScaleFactor) and Maya converts it to cm on import
        args = {"use_selection": selection}
        if maya:
            args.update(axis_forward='-Z', axis_up='Y', apply_unit_scale=True, global_scale=1.0,
                        apply_scale_options='FBX_SCALE_NONE', add_leaf_bones=False, bake_space_transform=True,
                        bake_anim_use_all_actions=False, bake_anim_use_nla_strips=False,
                        # Maya joints point X down the bone; Maya Y = the bone's
                        # Z, Maya Z = its X (joint_frames.JOINT_AXES, what Orient Joint sets) — '-Y' put Maya Y on the
                        # bone's -X (jointOrient 90 deg off Maya's); Maya exports joints, not the kit's control bones; a key per frame like Maya's bake (also re-composable by fbx_rig)
                        primary_bone_axis='X', secondary_bone_axis='Z', use_armature_deform_only=True,
                        bake_anim_simplify_factor=0.0)
        return "export_scene.fbx", args
    if fmt == 'OBJ':
        args = {"export_selected_objects": selection}
        if maya:
            args.update(global_scale=1.0 / k, forward_axis='NEGATIVE_Z', up_axis='Y')
        return "wm.obj_export", args
    if fmt == 'ABC':
        args = {"selected": selection}
        if maya:
            # Blender's Alembic writer is always Y up; its global_scale lands on the root transforms, so
            # ``write`` scales the objects' geometry / offsets around it (_abc_maya_scale)
            args.update(global_scale=1.0 / k)
        return "wm.alembic_export", args
    if fmt == 'USD':
        args = {"selected_objects_only": selection}
        if maya:
            # one prim per transform + shape like mayaUsd, no "/root" prim, no world dome light ("env_light");
            # axes and units: ``usd_maya_axes`` after the write (Blender's own conversion lands on the prims)
            args.update(root_prim_path="", merge_parent_xform=True, convert_world_material=False)
        return "wm.usd_export", args
    if fmt == 'GLTF':
        return "export_scene.gltf", {"use_selection": selection, "export_yup": True}
    raise ValueError(fmt)


def preset_text(fmt, k, export):
    """One line for the Options panel: what the Maya preset does for this format."""
    if fmt == 'BLEND':
        return "Blender scene: units and axes are kept as they are"
    if fmt == 'GLTF':
        return "glTF is always metres, Y up (no Maya preset)"
    if fmt == 'FBX':
        return "Centimetres, Y up (stored in the FBX)"
    if fmt == 'USD':
        return f"Y up, metersPerUnit {k:g}" if export else "Y up, metersPerUnit converted to Maya units"
    scale = 1.0 / k if export else k
    return f"Y up, scale ×{scale:g} (1 Maya unit = 1 {'file unit' if export else 'scene unit'})"


# --- .blend as a Maya scene file ------------------------------------------------------------------

def multi_skin_meshes(obs):
    """Names of the meshes with more than one skin (Armature modifier with a skeleton)."""
    from . import skin
    return [o.name for o in obs if o.type == 'MESH' and len(skin.armature_modifiers(o)) > 1]


def import_blend(context, path):
    """Maya Import of a Maya scene: the other file's objects join this scene (in a collection named after it)."""
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = list(src.objects)
    coll = bpy.data.collections.new(os.path.splitext(os.path.basename(path))[0])
    context.scene.collection.children.link(coll)
    obs = [ob for ob in dst.objects if ob is not None]
    for ob in obs:
        coll.objects.link(ob)
    return obs


def export_blend(context, path, selection):
    if not selection:
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
        return
    from . import dag
    obs = set(dag.hierarchy(context.selected_objects))     # Maya: the selection with its descendants
    bpy.data.libraries.write(path, obs, fake_user=False, compress=False)


# --- the dialog -------------------------------------------------------------------------------------

def _filter_update(self, context):
    self.filter_glob = ALL_GLOB if self.mode == 'IMPORT' and self.import_type == 'AUTO' else \
        _BY_ID[self.import_type if self.mode == 'IMPORT' else self.export_type][3]
    if self.mode != 'IMPORT' and self.filepath and format_of(self.filepath) != self.export_type:
        self.filepath = bpy.path.ensure_ext(os.path.splitext(self.filepath)[0], _BY_ID[self.export_type][2])


class _FileDialog:
    """Maya file dialog: Files of type and the format options in the side panel, Maya's cm / Y-up presets
    (Maya File > Import / Export All / Export Selection)"""
    bl_options = {'REGISTER', 'UNDO'}
    FIXED = None     # the mode of the menu-item operators (their label is the file browser's button text)

    mode: EnumProperty(items=MODES, name="Mode", options={'SKIP_SAVE'})
    filepath: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'})
    filter_glob: StringProperty(default=ALL_GLOB, options={'HIDDEN', 'SKIP_SAVE'})
    import_type: EnumProperty(items=IMPORT_TYPES, name="Files of type", update=_filter_update)
    export_type: EnumProperty(items=EXPORT_TYPES, name="Files of type", default='FBX', update=_filter_update)
    maya_conversion: BoolProperty(name="Maya Units and Axes", default=True,
                                  description="Convert to / from a Maya scene: centimetres and Y up")
    animation: BoolProperty(name="Animation", default=True, description="Write the animation (FBX, Alembic, USD)")
    # Issue #145: engine-ready skeletons (operators/fbx_skeleton.py)
    deform_only: BoolProperty(name="Deforming Joints Only", default=True,
                              description="FBX: write only the joints that deform the skin (a Rigify rig's DEF "
                                          "bones), parented along the deforming chain; helper and control bones "
                                          "stay out")
    maya_names: BoolProperty(name="Maya-Safe Names", default=True,
                             description="FBX: '-', '.' and other characters Maya can't have in a node name "
                                         "become '_' (DEF-spine.001 -> DEF_spine_001)")
    option_box: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'},
                             description="Maya option box: the Options panel of this dialog")

    @property
    def selection(self):
        return self.mode == 'EXPORT_SELECTION'

    def _fmt(self):
        if self.mode == 'IMPORT':
            return format_of(self.filepath) if self.import_type == 'AUTO' else self.import_type
        return self.export_type

    def invoke(self, context, event):
        if self.FIXED:
            self.mode = self.FIXED
        if self.mode == 'IMPORT':
            name, fmt = "", (None if self.import_type == 'AUTO' else self.import_type)
        else:
            base = os.path.splitext(bpy.path.basename(bpy.data.filepath))[0] or "untitled"
            name, fmt = base + _BY_ID[self.export_type][2], self.export_type
        self.filepath = os.path.join(start_folder(context, fmt), name)
        _filter_update(self, context)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def check(self, context):
        """Keep the file name's extension in step with Files of type (Maya does the same). A folder typed or pasted
        into the file name field opens that folder."""
        space = context.space_data
        if space is not None and space.type == 'FILE_BROWSER' and space.params is not None:
            path = space.params.filename.strip().strip('"')
            if path and ('/' in path or '\\' in path or path in {'.', '..'}):
                folder = os.path.abspath(os.path.join(os.fsdecode(space.params.directory), path))
                if os.path.isdir(folder):
                    # check runs before Blender sanitizes filename separators; return the new browser path.
                    self.filepath = os.path.join(folder, "")
                    return True
        if self.mode == 'IMPORT' or not self.filepath or format_of(self.filepath) == self.export_type:
            return False
        self.filepath = bpy.path.ensure_ext(os.path.splitext(self.filepath)[0], _BY_ID[self.export_type][2])
        return True

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.label(text="Files of type:")
        layout.prop(self, "import_type" if self.mode == 'IMPORT' else "export_type", text="")
        fmt = self._fmt() or 'FBX'
        k = units.maya_unit(context.scene)
        box = layout.box()
        box.label(text="General Options")
        box.prop(self, "maya_conversion")
        sub = box.column()
        sub.enabled = self.maya_conversion
        sub.label(text=preset_text(fmt, k, self.mode != 'IMPORT'))
        if self.mode != 'IMPORT':
            box.label(text="Selection Only", icon='CHECKBOX_HLT' if self.selection else 'CHECKBOX_DEHLT')
            if fmt in ('FBX', 'ABC', 'USD'):
                box = layout.box()
                box.label(text="File Type Specific Options")
                box.prop(self, "animation")
                if fmt == 'FBX':
                    col = box.column()
                    col.enabled = self.maya_conversion
                    col.prop(self, "deform_only")
                    col.prop(self, "maya_names")
        layout.label(text=f"Project: {os.path.basename(project.current_root(context))}", icon='FILE_FOLDER')

    def execute(self, context):
        if self.FIXED:
            self.mode = self.FIXED
        path = bpy.path.abspath(self.filepath)
        fmt = self._fmt()
        if not fmt:
            self.report({'ERROR'}, f"No translator reads {os.path.basename(path)} "
                                   "(Maya .ma / .mb can't be read: export FBX from Maya)")
            return {'CANCELLED'}
        k = units.maya_unit(context.scene)
        try:
            if self.mode == 'IMPORT':
                if not os.path.isfile(path):
                    self.report({'ERROR'}, f"No such file: {path}")
                    return {'CANCELLED'}
                if fmt == 'BLEND':
                    obs = import_blend(context, path)
                    results.result(self, f"Imported {len(obs)} object(s) from {os.path.basename(path)}")
                    return {'FINISHED'}
                op, args = import_args(fmt, k, self.maya_conversion)
                if fmt == 'FBX' and self.maya_conversion:
                    from . import fbx_rig_import
                    if fbx_rig_import.has_skeleton(path):
                        # Blender's reader bakes the conversion into a skinned mesh but leaves it on the armature
                        # (mesh 0.01 x, first_hour #37): read plain, after_import converts
                        args = dict(args, bake_space_transform=False)
                before, mats = set(bpy.data.objects), set(bpy.data.materials)
                mod, name = op.split(".")
                getattr(getattr(bpy.ops, mod), name)('EXEC_DEFAULT', filepath=path, **args)
                if self.maya_conversion:
                    after_import(context, fmt, path, [ob for ob in bpy.data.objects if ob not in before],
                                 [m for m in bpy.data.materials if m not in mats], args)
            else:
                if self.selection and not context.selected_objects:
                    self.report({'WARNING'}, "Nothing selected to export.")
                    return {'CANCELLED'}
                path = bpy.path.ensure_ext(path, _BY_ID[fmt][2]) if format_of(path) != fmt else path
                if fmt == 'BLEND':
                    export_blend(context, path, self.selection)
                    results.result(self, f"Exported {os.path.basename(path)}")
                    return {'FINISHED'}
                op, args = export_args(fmt, k, self.selection, self.maya_conversion)
                args.update(_animation_args(fmt, self.animation))
                # Maya Export Selection writes the selected nodes with everything below them;
                # Blender's writers take only the selected objects
                from . import dag
                from .control_shapes import excluded as shapes_excluded   # no control shape curves
                if self.selection:
                    with dag.selected_hierarchy(context), shapes_excluded(context.scene, context.view_layer):
                        write(context, fmt, path, op, args, self.maya_conversion, k,
                              self.deform_only, self.maya_names)
                else:
                    from . import startup_cameras
                    with startup_cameras.excluded(context.scene, context.view_layer),                             shapes_excluded(context.scene, context.view_layer):
                        write(context, fmt, path, op, args, self.maya_conversion, k,
                              self.deform_only, self.maya_names)
        except RuntimeError as ex:
            self.report({'ERROR'}, str(ex).strip().splitlines()[-1])
            return {'CANCELLED'}
        verb = "Imported" if self.mode == 'IMPORT' else "Exported"
        if self.mode != 'IMPORT':
            many = multi_skin_meshes(context.selected_objects if self.selection else context.scene.objects)
            if many:
                # Blender reads a second Armature modifier back as one, engines keep one skin
                self.report({'WARNING'}, f"{', '.join(many)}: several skin clusters — FBX and game engines keep one "
                                         "skin per mesh")
        results.result(self, f"{verb} {os.path.basename(path)}")
        return {'FINISHED'}


class ALLSET_OT_file_dialog(_FileDialog, bpy.types.Operator):
    bl_idname = "allset.file_dialog"
    bl_label = "File"


class ALLSET_OT_file_import(_FileDialog, bpy.types.Operator):
    """Import a file into the scene; Files of type / Best Guess picks the format (Maya File > Import)"""
    bl_idname = "allset.file_import"
    bl_label = "Import"
    FIXED = 'IMPORT'


class ALLSET_OT_file_export_all(_FileDialog, bpy.types.Operator):
    """Export the whole scene in the chosen format (Maya File > Export All)"""
    bl_idname = "allset.file_export_all"
    bl_label = "Export All"
    FIXED = 'EXPORT_ALL'


class ALLSET_OT_file_export_selection(_FileDialog, bpy.types.Operator):
    """Export the selected objects in the chosen format (Maya File > Export Selection)"""
    bl_idname = "allset.file_export_selection"
    bl_label = "Export Selection"
    FIXED = 'EXPORT_SELECTION'


def _animation_args(fmt, on):
    if fmt == 'FBX':
        return {"bake_anim": on}
    if fmt == 'USD':
        return {"export_animation": on}
    if fmt == 'ABC' and not on:
        f = bpy.context.scene.frame_current
        return {"start": f, "end": f}
    return {}


# --- file browser: Current Project ------------------------------------------------------------------

class ALLSET_OT_file_goto(bpy.types.Operator):
    """Show this folder in the file browser (Maya file dialog: project folder list)"""
    bl_idname = "allset.file_goto"
    bl_label = "Go to Folder"
    bl_options = {'INTERNAL'}

    path: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and space.type == 'FILE_BROWSER' and space.params is not None

    def execute(self, context):
        if not os.path.isdir(self.path):
            os.makedirs(self.path, exist_ok=True)
        context.space_data.params.directory = os.path.join(self.path, "").encode()
        return {'FINISHED'}


class ALLSET_OT_file_set_project(bpy.types.Operator):
    """Make the folder shown in the file browser the current project (Maya file dialog: Set Project...)"""
    bl_idname = "allset.file_set_project"
    bl_label = "Set Project"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return ALLSET_OT_file_goto.poll(context)

    def execute(self, context):
        folder = os.path.abspath(context.space_data.params.directory.decode())
        # in a project sub-folder (scenes ...) the project is the folder above it
        if os.path.basename(folder.rstrip(os.sep)) in project.FOLDERS and project.is_project(os.path.dirname(folder)):
            folder = os.path.dirname(folder)
        project.create_project(folder)
        project.set_current(folder, context)
        scenes = os.path.join(folder, "scenes", "")
        context.space_data.params.directory = scenes.encode()
        results.result(self, f"Project: {folder}")
        return {'FINISHED'}


classes = (ALLSET_OT_file_dialog, ALLSET_OT_file_import, ALLSET_OT_file_export_all, ALLSET_OT_file_export_selection,
           ALLSET_OT_file_goto, ALLSET_OT_file_set_project)
