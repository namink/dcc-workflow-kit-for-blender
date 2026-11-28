# SPDX-License-Identifier: GPL-3.0-or-later
"""Operators behind Maya menu items: ``allset.menu_item`` (option box, component / object mode rules, Maya
warnings), greyed items, whole-mesh and component-mode runs, 3D View runs, tool picks and radio values
(``prop_owner`` / ``set_prop``); Ctrl+Shift+click puts an item on the shelf. Drawing is in ``menu_item_draw``.
"""

import json

import bpy
from bpy.props import BoolProperty, StringProperty

from .. import i18n, results, undo_steps
from . import menu_map, notices, option_click
from .menu_option_box import BOX_TIP, modifier_held
from .menu_tree import OPTION_BOXES


def op_polls(target):
    """Blender's poll of operator ``target`` in the current context (True if it can't be asked)."""
    mod, name = target.split(".")
    try:
        return getattr(getattr(bpy.ops, mod), name).poll()
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return True


_WHAT = {"mesh": "mesh components (vertices, edges or faces)", "curve": "curve points (CVs)",
         "armature": "joints (skeleton edit mode)", "pose": "joints (pose mode)", "uv": "UVs (UV Editor)",
         "object": "objects", "anim": "objects to key", "paint": "a mesh", "sculpt": "a mesh"}


def maya_warning(path, target):
    """Maya-style warning for an item Blender can't run on this selection."""
    label = path.rsplit("/", 1)[-1]
    what = _WHAT.get(target.split(".")[0], "what it works on")
    return f"{label}: select {what} first."


def prop_owner(context, target):
    """(owner, attribute) of a ``("prop", target)`` mapping: a path from the context ("space_data.show_handles"),
    "addon_prefs.<name>" = this add-on's preferences, "view3d.<path>" = the 3D View the Display menu acts on
    (``status_line_buttons.view3d_space``; the main menu bar is in the top bar, whose space has no overlays).
    Blender's own preferences are never a target (store review, #40 / #43): such a path has no owner."""
    *parents, attr = target.split(".")
    if parents and parents[0] == "preferences":
        return None, attr
    if parents and parents[0] == "addon_prefs":
        from .. import preferences
        owner, parents = preferences.get(context), parents[1:]
    elif parents and parents[0] == "view3d":
        from .status_line import view3d_space
        owner, parents = view3d_space(context), parents[1:]
    else:
        owner = context
    for name in parents:
        owner = getattr(owner, name, None)
        if owner is None:
            return None, attr
    return (owner, attr) if hasattr(owner, attr) else (None, attr)


def set_prop(context, target, props):
    """Run a ``("prop", ...)`` mapping: toggle the check box or set the radio value."""
    owner, attr = prop_owner(context, target)
    if owner is None:
        return {'CANCELLED'}
    setattr(owner, attr, props["value"] if "value" in props else not getattr(owner, attr))
    return {'FINISHED'}


class ALLSET_OT_menu_set_value(bpy.types.Operator):
    """Maya radio menu item: set this choice"""
    bl_idname = "allset.menu_set_value"
    bl_label = "Set"
    bl_options = {'INTERNAL', 'UNDO'}

    target: StringProperty(options={'SKIP_SAVE'})
    value: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        import ast
        return set_prop(context, self.target, {"value": ast.literal_eval(self.value)})


# --- operators -----------------------------------------------------------------

class ALLSET_OT_menu_unavailable(bpy.types.Operator):
    """Maya menu item without a Blender equivalent in Maya Workflow Kit (always greyed out)"""
    bl_idname = "allset.menu_unavailable"
    bl_label = "Not Available"
    bl_options = {'INTERNAL'}

    item: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return False

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return notices.tooltip(props.item, mapped=False) or _no_equivalent(props.item)

    def execute(self, context):
        return {'CANCELLED'}


class ALLSET_OT_menu_item(bpy.types.Operator):
    """Maya menu item with an option box (press and hold: Option Box)"""
    bl_idname = "allset.menu_item"
    bl_label = "Menu Item"
    bl_options = {'INTERNAL'}

    item: StringProperty(options={'SKIP_SAVE'})
    # drawn in a Maya menu (not run from Python / a marking menu): Ctrl+Shift+click adds it to the shelf
    clicked: BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})
    # run by a key the user gave it in the Hotkey Editor: the key's own Ctrl / Shift don't open the option box
    hotkey: BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return True

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        if props.item not in menu_map.MAP:
            return notices.tooltip(props.item, mapped=False) or _no_equivalent(props.item)
        text = notices.tooltip(props.item, mapped=True) or _op_description(props.item)
        if props.item in OPTION_BOXES:
            text += "\n" + i18n.tip(BOX_TIP)
        return text

    def execute(self, context):
        action = menu_map.MAP.get(self.item)
        if action is None:
            results.result(self, f"Maya: {self.item} has no Blender equivalent in Maya Workflow Kit yet")
            return {'CANCELLED'}
        if self.clicked and add_to_shelf_if_asked(self, context, self.item):     # before Shift / Ctrl alone
            return {'FINISHED'}
        if self.item in OPTION_BOXES and not self.hotkey and modifier_held():  # Shift / Ctrl+click = the option box
            return bpy.ops.allset.menu_option_box('INVOKE_DEFAULT', True, item=self.item)
        if self.clicked and self.item in OPTION_BOXES and option_click.on_box(context, self.item):
            return bpy.ops.allset.menu_option_box('INVOKE_DEFAULT', True, item=self.item)    # a click on ❒
        if context.mode == 'EDIT_MESH' and self.item in menu_map.EDIT_MODE:     # component mode
            try:
                return bpy.ops.allset.component_command('EXEC_DEFAULT', True, item=self.item)
            except RuntimeError as ex:      # Blender's own refusal (Select > Similar with nothing selected ...)
                from ..operators import maya_errors
                maya_errors.report_nested(self, ex)
                return {'CANCELLED'}
        rule = menu_map.OBJECT_MODE.get(self.item) if context.mode == 'OBJECT' else None
        if isinstance(rule, str):     # Maya warns and does nothing
            self.report({'WARNING'}, rule)
            return {'CANCELLED'}
        if rule:
            return bpy.ops.allset.menu_whole_mesh('EXEC_DEFAULT', True, item=self.item)
        s = menu_map.spec(self.item)
        if s[0] == "op" and not op_polls(s[1]):
            self.report({'WARNING'}, maya_warning(self.item, s[1]))
            return {'CANCELLED'}
        from ..marking.modal import run_action
        try:
            run_action(context, action, path=self.item)
        except RuntimeError as ex:
            from ..operators import maya_errors
            maya_errors.report_nested(self, ex)       # a Maya Error stays an Error (#152)
            return {'CANCELLED'}
        return {'FINISHED'}


def _no_equivalent(path):
    """Tooltip of a greyed Maya item without a notice, in the tooltip language."""
    return f"Maya: {i18n.path(path, i18n.tip)}\n" + i18n.tip("No Blender equivalent in Maya Workflow Kit yet")


def _op_description(path):
    """Tooltip of a mapped item: its Blender operator's description, else the item's label (tooltip language)."""
    s = menu_map.spec(path)
    if s is not None and s[0] in ("op", "v3d"):
        try:
            mod, name = s[1].split(".")
            text = getattr(getattr(bpy.ops, mod), name).get_rna_type().description
            if text:
                return i18n.tip(text)
        except (AttributeError, KeyError, ValueError):
            pass
    return i18n.tip(path.rsplit('/', 1)[-1])


# Values for commands run on a whole object:
# Bevel fraction 0.5, Chamfer Vertices 0.25 (Blender: percent of the adjacent edge).
WHOLE_MESH_PROPS = {
    "Edit Mesh/Chamfer Vertices": {"offset_type": 'PERCENT', "offset_pct": 25.0, "affect": 'VERTICES'},
    # Circularize: allset.circularize's own defaults apply; the old LoopTools "value" key made every
    # object-mode Circularize raise TypeError
}


class ALLSET_OT_menu_whole_mesh(bpy.types.Operator):
    """Run a component command on every component of the selected meshes (Maya does that for an object
    selection) and come back to object mode, as one undo step"""
    bl_idname = "allset.menu_whole_mesh"
    bl_label = "Menu Item on Whole Mesh"
    bl_options = {'INTERNAL', 'REGISTER', 'UNDO'}

    item: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        return run_whole_mesh(self, context, self.item)


def run_whole_mesh(op_self, context, item, settings=None):
    """Run the component command of ``item`` on every component of the selected meshes and come back to object
    mode; ``settings`` = the command's own values (its option box's Adjust Last Operation)."""
    rule = menu_map.OBJECT_MODE.get(item)
    s = menu_map.spec(item)
    meshes = [ob for ob in context.selected_objects if ob.type == 'MESH']
    if not isinstance(rule, tuple) or s is None or s[0] not in ("op", "v3d"):
        return {'CANCELLED'}
    if not meshes:
        op_self.report({'WARNING'}, "Nothing selected.")
        return {'CANCELLED'}
    view_layer = context.view_layer
    if view_layer.objects.active not in meshes:
        view_layer.objects.active = meshes[0]
    mod, name = s[1].split(".")
    props = {**s[2], **WHOLE_MESH_PROPS.get(item, {}), **(settings or {})}
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        bpy.ops.mesh.select_mode(type=rule[1])
        bpy.ops.mesh.select_all(action='SELECT')
        op = getattr(getattr(bpy.ops, mod), name)
        if s[0] == "v3d" and not op.poll():
            # Blender runs it only in a 3D View (Camera-based maps from the view): the largest one, as the
            # menu item does in component mode (allset.menu_run)
            window, area, region = _view3d(context)
            if area is None:
                raise RuntimeError(i18n.tip(NO_3D_VIEW))
            with context.temp_override(window=window, screen=window.screen, area=area, region=region):
                op('EXEC_DEFAULT', **props)
        else:
            op('EXEC_DEFAULT', **props)
    except (RuntimeError, TypeError) as ex:
        op_self.report({'WARNING'}, str(ex).strip().splitlines()[-1])
        return {'CANCELLED'}
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    return {'FINISHED'}


# --- option box of a whole-mesh item in object mode ---------------------------------------------------------------
# Maya's option box of such an item runs the command on the whole object with the command's settings. The kit shows
# those settings in Adjust Last Operation, so each item gets an operator that carries a copy of its command's
# properties and runs the command on the whole mesh (made at register time: the commands must be registered first).

WHOLE_MESH_OPTIONS = {}         # Maya menu path -> bl_idname of its whole-mesh option operator
_whole_mesh_classes = []


def _copy_property(p):
    """A bpy.props definition with the settings of the registered property ``p`` (None: a kind not copied)."""
    common = {"name": p.name, "description": p.description}
    flags = set()
    if p.is_hidden:
        flags.add('HIDDEN')
    if p.is_skip_save:
        flags.add('SKIP_SAVE')
    if p.type == 'ENUM':
        items = [(e.identifier, e.name, e.description, e.icon, e.value) for e in p.enum_items]
        if not items:
            return None
        if p.is_enum_flag:
            flags.add('ENUM_FLAG')
            return bpy.props.EnumProperty(items=items, default=set(p.default_flag), options=flags, **common)
        default = p.default if any(i[0] == p.default for i in items) else items[0][0]
        return bpy.props.EnumProperty(items=items, default=default, options=flags, **common)
    if p.type == 'STRING':
        return bpy.props.StringProperty(default=p.default, options=flags, **common)
    array = p.is_array and p.array_length > 0
    if p.type == 'BOOLEAN':
        if array:
            return bpy.props.BoolVectorProperty(size=p.array_length, default=tuple(p.default_array),
                                                subtype=p.subtype, options=flags, **common)
        return bpy.props.BoolProperty(default=p.default, options=flags, **common)
    if p.type not in {'INT', 'FLOAT'}:
        return None
    limits = {"min": p.hard_min, "max": p.hard_max, "soft_min": p.soft_min, "soft_max": p.soft_max, "step": p.step}
    if p.type == 'INT':
        if array:
            return bpy.props.IntVectorProperty(size=p.array_length, default=tuple(p.default_array),
                                               subtype=p.subtype, options=flags, **limits, **common)
        return bpy.props.IntProperty(default=p.default, subtype=p.subtype, options=flags, **limits, **common)
    limits["precision"] = p.precision
    if array:
        return bpy.props.FloatVectorProperty(size=p.array_length, default=tuple(p.default_array),
                                             subtype=p.subtype, unit=p.unit, options=flags, **limits, **common)
    return bpy.props.FloatProperty(default=p.default, subtype=p.subtype, unit=p.unit, options=flags, **limits,
                                   **common)


def _plain(value):
    """An operator property value as a plain Python value (arrays as tuples)."""
    if isinstance(value, (str, set, bool, int, float)):
        return value
    return tuple(value)


def _whole_mesh_option_class(index, path, target):
    mod, name = target.split(".")
    try:
        rna = getattr(getattr(bpy.ops, mod), name).get_rna_type()
    except (AttributeError, KeyError):
        return None
    if not any(p.identifier != "rna_type" and not p.is_hidden for p in rna.properties):
        return None         # no settings: the option box opens the window saying Blender has none
    annotations = {}
    for p in rna.properties:
        if p.identifier != "rna_type":
            prop = _copy_property(p)
            if prop is not None:
                annotations[p.identifier] = prop

    def execute(self, context):
        settings = {k: _plain(getattr(self, k)) for k in annotations if self.properties.is_property_set(k)}
        return run_whole_mesh(self, context, path, settings)

    return type(f"ALLSET_OT_whole_mesh_option_{index}", (bpy.types.Operator,), {
        "__doc__": f"{rna.name} on every component of the selected meshes, with its settings",
        "bl_idname": f"allset.whole_mesh_option_{index}",
        "bl_label": rna.name,
        "bl_translation_context": rna.translation_context,
        "bl_options": {'REGISTER', 'UNDO', 'INTERNAL'},
        "__annotations__": annotations,
        "execute": execute,
    })


def register_whole_mesh_options():
    for path, rule in menu_map.OBJECT_MODE.items():
        s = menu_map.spec(path)
        if not isinstance(rule, tuple) or s is None or s[0] not in ("op", "v3d"):
            continue
        cls = _whole_mesh_option_class(len(_whole_mesh_classes), path, s[1])
        if cls is not None:
            bpy.utils.register_class(cls)
            _whole_mesh_classes.append(cls)
            WHOLE_MESH_OPTIONS[path] = cls.bl_idname


def unregister_whole_mesh_options():
    for cls in reversed(_whole_mesh_classes):
        bpy.utils.unregister_class(cls)
    _whole_mesh_classes.clear()
    WHOLE_MESH_OPTIONS.clear()


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_component_command(bpy.types.Operator):
    """A Maya Edit / Select / Modify command in component mode, run the way Maya runs it there
    (``menu_map.EDIT_MODE``)"""
    bl_idname = "allset.component_command"
    bl_label = "Maya Command in Component Mode"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    item: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return _op_description(props.item)

    def execute(self, context):
        rule = menu_map.EDIT_MODE.get(self.item)
        if rule is None:
            return {'CANCELLED'}
        kind, label = rule[0], self.item.rsplit("/", 1)[-1]
        if kind == "warn":
            self.report({'WARNING'}, rule[1])
            return {'CANCELLED'}
        if kind == "none":
            results.result(self, f"{label}: works on objects; in component mode Maya leaves it alone "
                                  "(F8 = object mode)")
            return {'CANCELLED'}
        from ..marking.modal import run_action
        try:
            with undo_steps.nested():          # this operator is the undo step (UNDO)
                if kind == "run":
                    run_action(context, rule[1], path=self.item)
                elif kind == "object":
                    bpy.ops.object.mode_set(mode='OBJECT')
                    run_action(context, rule[1], path=self.item)
                elif kind == "owner":
                    _run_on_owners(context, rule[1], self.item)
        except RuntimeError as ex:
            from ..operators import maya_errors
            maya_errors.report_nested(self, ex)
            return {'CANCELLED'}
        return {'FINISHED'}


def _select_only(context, objects):
    for ob in context.scene.objects:
        try:
            ob.select_set(ob in objects)
        except RuntimeError:          # not in the view layer
            pass


def _run_on_owners(context, action, path):
    """Run ``action`` in object mode on the objects whose components are being edited, then come back to component
    mode on the same objects with their components still selected (Maya keeps the component selection)."""
    from ..marking.modal import run_action
    owners = list(context.objects_in_mode)
    active = context.view_layer.objects.active
    bpy.ops.object.mode_set(mode='OBJECT')
    _select_only(context, owners)
    try:
        run_action(context, action, path=path)
    finally:
        _select_only(context, owners)
        context.view_layer.objects.active = active
        bpy.ops.object.mode_set(mode='EDIT')


# --- Ctrl+Shift+click: the item to the current shelf -------------------------------------------------
# Maya: Shift+Ctrl+click on a menu item adds it to the current shelf; Maya's
# Maya appends a shelf button with the item's label / annotation / image (running the item's command)
# to the shelf tab shown, factory tabs included, and prints nothing. The kit button runs
# the path like the menu (``shelf_store.add_menu_item``, ``marking.modal.run_action(("item", path))``).

def ctrl_shift_held():
    """Ctrl and Shift both physically down (OS key state; unknown = not held)."""
    from ..operators import keystate

    def down(keys):
        return any(keystate.is_down(k) for k in keys)
    return down(("LEFT_SHIFT", "RIGHT_SHIFT")) and down(("LEFT_CTRL", "RIGHT_CTRL"))


def add_to_shelf_if_asked(op, context, path):
    """With Ctrl+Shift held, put a button for Maya menu item ``path`` on the current shelf instead of running it;
    True if it did. Only mapped Maya menu paths (marking-menu pies pass their own labels)."""
    if not path or path not in menu_map.MAP or not ctrl_shift_held():
        return False
    from . import shelf
    _shelf_id, tab, button = shelf.add_menu_item(context, path)
    results.result(op, f"{button['label']} added to the {tab} shelf")
    return True


def _call(op_id, props):
    mod, name = op_id.split(".")
    return getattr(getattr(bpy.ops, mod), name)('INVOKE_DEFAULT', **props)


NO_3D_VIEW = i18n.mark("No 3D View to run this in")


def _view3d(context):
    """(window, area, WINDOW region) of the largest 3D View of the window the menu runs in, else of any window (a
    separate UV Editor window has none of its own); (None, None, None) without one."""
    from .status_line import main_view3d
    windows = list(context.window_manager.windows)
    if context.window in windows:
        windows.remove(context.window)
        windows.insert(0, context.window)
    best = (None, None, None)
    for k, window in enumerate(windows):
        area, region = main_view3d(window.screen)
        if area is not None and (best[1] is None or area.width * area.height > best[1].width * best[1].height):
            best = (window, area, region)
        if k == 0 and best[1] is not None:
            break
    return best


class ALLSET_OT_menu_run(bpy.types.Operator):
    """Run a Blender operator in the largest 3D View (for Maya menu items)"""
    bl_idname = "allset.menu_run"
    bl_label = "Run in 3D View"
    bl_options = {'INTERNAL'}

    op: StringProperty(options={'SKIP_SAVE'})
    props: StringProperty(default="{}", options={'SKIP_SAVE'})
    item: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})       # the Maya menu path (drawn in a menu)
    space_type: StringProperty(default='VIEW_3D', options={'SKIP_SAVE'})
    mode: StringProperty(default="ANY", options={'SKIP_SAVE'})
    object_type: StringProperty(default="ANY", options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        try:
            mod, name = props.op.split(".")
            return getattr(getattr(bpy.ops, mod), name).get_rna_type().description
        except (ValueError, AttributeError, KeyError):
            return ""

    def execute(self, context):
        if add_to_shelf_if_asked(self, context, self.item):
            return {'FINISHED'}
        window, area, region = _view3d(context)
        if area is None:
            self.report({'ERROR'}, i18n.tip(NO_3D_VIEW))
            return {'CANCELLED'}
        try:
            with context.temp_override(window=window, screen=window.screen, area=area, region=region):
                _call(self.op, json.loads(self.props))
        except RuntimeError as ex:  # poll failed etc.
            text = str(ex).strip()
            # a Maya-style line instead of Blender's "poll() failed, context is incorrect"
            self.report({'WARNING'}, maya_warning(self.op, self.op) if "poll()" in text else text)
            return {'CANCELLED'}
        return {'FINISHED'}


# Object Mode kit tools whose menu item picks a Blender tool in component modes (Maya Universal Manipulator).
COMPONENT_TWIN = {}       # tools a component mode swaps for another (none: the Universal Manipulator works on components too)


class ALLSET_OT_menu_tool(bpy.types.Operator):
    """Switch the 3D View tool (for Maya menu items that pick a tool)"""
    bl_idname = "allset.menu_tool"
    bl_label = "Set Tool"
    bl_options = {'INTERNAL'}

    tool: StringProperty(options={'SKIP_SAVE'})
    edit: BoolProperty(description="Enter mesh edit (component) mode first", options={'SKIP_SAVE'})
    space_type: StringProperty(default='VIEW_3D', options={'SKIP_SAVE'})
    mode: StringProperty(default="ANY", options={'SKIP_SAVE'})
    object_type: StringProperty(default="ANY", options={'SKIP_SAVE'})
    item: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})       # the Maya menu path (drawn in a menu)

    def execute(self, context):
        if add_to_shelf_if_asked(self, context, self.item):
            return {'FINISHED'}
        ob = context.active_object
        required_object_type = (self.object_type or "ANY").upper()
        if required_object_type not in {"ANY", "AUTO"}:
            if ob is None or ob.type != required_object_type:
                self.report({'WARNING'}, f"This tool requires an active {required_object_type} object.")
                return {'CANCELLED'}
        if self.edit:
            if ob is None or ob.type != 'MESH':
                self.report({'ERROR'}, "Select a mesh first")
                return {'CANCELLED'}
            if context.mode != 'EDIT_MESH' and not ob.visible_get():
                self.report({'WARNING'}, f"{ob.name} is hidden: show it first")
                return {'CANCELLED'}
            if context.mode != 'EDIT_MESH':
                # its own undo step: Ctrl+Z after the tool's first edit must stay in edit mode
                bpy.ops.object.mode_set('EXEC_DEFAULT', True, mode='EDIT')
        required_mode = (self.mode or "ANY").upper()
        if required_mode != "ANY":
            if self.space_type == 'IMAGE_EDITOR':
                space = context.space_data
                current_mode = getattr(space, "mode", "") if space else ""
            else:
                current_mode = context.mode
            if current_mode != required_mode:
                self.report(
                    {'WARNING'},
                    f"This tool requires {required_mode} mode. "
                    f"Switch to the required mode in the {self.space_type} editor and try again."
                )
                return {'CANCELLED'}
        try:
            target_space = self.space_type
            if target_space in {"", "AUTO", "ANY"}:
                target_space = context.area.type if context.area else "VIEW_3D"
            if target_space not in {"VIEW_3D", "IMAGE_EDITOR"}:
                self.report({'WARNING'}, f"Tool activation is not supported in {target_space}.")
                return {'CANCELLED'}
            tool = self.tool
            if target_space == 'VIEW_3D' and context.mode != 'OBJECT':
                tool = COMPONENT_TWIN.get(tool, tool)
            if target_space == 'VIEW_3D':
                from ..operators import joint_selection
                joint_selection.tool_picked(context, tool, again=True)    # ends Move Skinned Joints
            result = bpy.ops.wm.tool_set_by_id(name=tool, space_type=target_space)
        except RuntimeError as ex:
            self.report({'WARNING'}, str(ex).strip())
            return {'CANCELLED'}
        if 'CANCELLED' in result:
            self.report({'WARNING'}, f"Tool '{self.tool}' is not available in the current editor/mode.")
            return {'CANCELLED'}
        return {'FINISHED'}
