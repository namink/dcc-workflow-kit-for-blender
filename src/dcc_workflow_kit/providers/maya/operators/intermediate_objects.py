# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Deform > Display / Hide Intermediate Objects: Display adds a child object ``<shape>Orig`` that shares a
deformed object's undeformed mesh (no modifiers) and selects it; Hide deletes it and selects the deformed objects.
Entry points ``display_intermediate``, ``hide_intermediate``, ``is_intermediate`` and
``allset.intermediate_objects`` (registered through pins_205.py).
"""

import bpy
from bpy.props import BoolProperty
from mathutils import Matrix

from .. import i18n, results, undo_steps
from . import deformers
from .pin_create import _link_like

INTERMEDIATE_OF = "allset_intermediate_of"
MSG_NO_DEFORMABLE = "No deformable object is selected."
MSG_ALREADY_OFF = "Display is already toggled off."
MSG_ALREADY_ON = "Display is already toggled on."
MSG_FOUND_NONE = "Found no intermediate objects."


# --- intermediate objects ------------------------------------------------------------------------------------

_SHAPED = {'MESH', 'CURVE', 'SURFACE', 'LATTICE'}


def is_intermediate(ob):
    """``ob`` stands for a Maya intermediate object: the kit's ``<shape>Orig`` display of a deformed object's
    original shape (made by Display Intermediate Objects)."""
    try:
        return isinstance(ob.get(INTERMEDIATE_OF), bpy.types.Object)
    except (ReferenceError, AttributeError):
        return False


def intermediates_of(ob):
    return [o for o in bpy.data.objects if is_intermediate(o) and o.get(INTERMEDIATE_OF) == ob]


def is_deformed(ob):
    """Maya gives ``ob`` an Orig shape: it has a deformer (history.is_deformer: kit deformers, skin, ...)."""
    if ob.type not in _SHAPED or ob.data is None:
        return False
    from . import history
    from . import display
    return any(history.is_deformer(md) and not display.is_preview(md) for md in ob.modifiers)


def _make_orig(context, ob):
    orig = bpy.data.objects.new(f"{ob.data.name}Orig", ob.data)
    orig[INTERMEDIATE_OF] = ob
    _link_like(orig, ob, context)
    orig.parent = ob
    orig.matrix_parent_inverse = Matrix.Identity(4)
    return orig


def display_intermediate(context):
    """Maya displayInterObjects 0. Returns the shown intermediate objects (selected)."""
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    sel = list(context.selected_objects)
    if not sel:
        raise RuntimeError(MSG_NO_DEFORMABLE)
    shown, already = [], 0
    for ob in sel:
        if is_intermediate(ob):
            already += 1
            continue
        if not is_deformed(ob):
            continue
        if intermediates_of(ob):
            already += 1
            continue
        shown.append(_make_orig(context, ob))
    if not shown:
        raise RuntimeError(MSG_ALREADY_ON if already else MSG_FOUND_NONE)
    context.view_layer.update()
    deformers._select_only(context, shown, shown[-1])
    return shown


def hide_intermediate(context):
    """Maya displayInterObjects 1. Returns (the deformed objects (selected), number of intermediate objects hidden)."""
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    sel = list(context.selected_objects)
    if not sel:
        raise RuntimeError(MSG_NO_DEFORMABLE)
    owners, hidden, already = [], 0, 0
    for ob in sel:
        owner = ob.get(INTERMEDIATE_OF) if is_intermediate(ob) else ob
        if owner is None or owner in owners:
            continue
        origs = intermediates_of(owner)
        if not origs:
            if is_deformed(owner):
                already += 1
            continue
        for o in origs:
            bpy.data.objects.remove(o, do_unlink=True)
            hidden += 1
        owners.append(owner)
    if not hidden:
        raise RuntimeError(MSG_ALREADY_OFF if already else MSG_FOUND_NONE)
    deformers._select_only(context, owners, owners[-1])
    return owners, hidden


@undo_steps.no_redo_panel
class ALLSET_OT_intermediate_objects(bpy.types.Operator):
    """Display / hide the original (undeformed) shape of the selected deformed objects (Maya Deform > Display /
    Hide Intermediate Objects)"""
    bl_idname = "allset.intermediate_objects"
    bl_label = "Intermediate Objects"
    bl_options = {'REGISTER', 'UNDO'}

    show: BoolProperty(name="Display", default=True, options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return "Display intermediate objects" if props.show else "Hide intermediate objects"

    def execute(self, context):
        try:
            n = len(display_intermediate(context)) if self.show else hide_intermediate(context)[1]
        except RuntimeError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        results.result(self, f"Toggled {'on' if self.show else 'off'} {n} objects.")
        return {'FINISHED'}
