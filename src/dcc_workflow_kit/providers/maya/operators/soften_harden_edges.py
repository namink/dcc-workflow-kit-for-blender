# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Mesh Display > Soften/Harden Edges (``allset.soften_harden``).

Edges whose faces meet below the angle turn soft, the rest hard, and the faces shade smooth. A Smooth by Angle
modifier that would turn the result back gives way (``giving_way``, ``soften_harden_edit``), with Maya-like undo steps
in component mode. Entry points ``soften_harden``, ``smooth_by_angle``, ``smooth_by_angle_inputs``; menu_items
re-exports them.
"""

import math

import bmesh
import bpy
from bpy.props import BoolProperty, FloatProperty

from .. import undo_steps


# --- Mesh Display > Soften/Harden Edges -------------------------------------------------------

def soften_harden(bm, angle, edges=None):
    """Maya polySoftEdge: an edge whose faces meet at less than ``angle`` degrees is soft, the rest hard;
    the faces shade smooth (Soften/Harden on an object = every edge, angle 30)."""
    limit = math.radians(angle) + 1e-6
    for e in (bm.edges if edges is None else edges):
        e.smooth = len(e.link_faces) != 2 or e.calc_face_angle(0.0) <= limit
    for e in (bm.edges if edges is None else edges):
        for f in e.link_faces:
            f.smooth = True


# Blender's Shade Auto Smooth adds a "Smooth by Angle" Geometry Nodes modifier (pinned last in the stack) that sets
# the edge sharpness again after every other change: it hardens each soft edge whose faces meet at more than its
# angle, so a soft edge written into the mesh stayed hard on screen (#342). Maya's newer soften / harden wins over
# the older one, so the command takes its place.
SMOOTH_BY_ANGLE = "Smooth by Angle"


def _group_name(name):
    head, dot, tail = name.rpartition(".")
    return head if dot and tail.isdigit() else name


def smooth_by_angle_mods(ob):
    """The object's Smooth by Angle modifiers, in stack order."""
    return [md for md in ob.modifiers if md.type == 'NODES' and md.node_group is not None
            and _group_name(md.node_group.name) == SMOOTH_BY_ANGLE]


def smooth_by_angle_inputs(md):
    """(Angle in radians, Ignore Sharpness) of a Smooth by Angle modifier."""
    from .. import compat
    values = {}
    for item in md.node_group.interface.items_tree:
        if getattr(item, "in_out", None) == 'INPUT' and item.name in ("Angle", "Ignore Sharpness"):
            value = compat.gn_input_get(md, item.identifier)
            values[item.name] = getattr(item, "default_value", None) if value is None else value
    angle = values.get("Angle")
    return (math.radians(30.0) if angle is None else float(angle)), bool(values.get("Ignore Sharpness", False))


def smooth_by_angle(bm, angle, ignore):
    """Write what a Smooth by Angle modifier shows into ``bm``: a soft edge (any edge with ``ignore``) stays soft when
    its faces meet at ``angle`` radians or less and all of them shade smooth, else it turns hard; then every face
    shades smooth."""
    bm.normal_update()
    for e in bm.edges:
        if ignore or e.smooth:
            e.smooth = e.calc_face_angle(0.0) <= angle and (ignore or all(f.smooth for f in e.link_faces))
    for f in bm.faces:
        f.smooth = True


def _flags(bm):
    return [e.smooth for e in bm.edges], [f.smooth for f in bm.faces]


def _set_flags(bm, flags):
    for e, s in zip(bm.edges, flags[0]):
        e.smooth = s
    for f, s in zip(bm.faces, flags[1]):
        f.smooth = s


def giving_way(ob, bm, angle, edges=None):
    """The Smooth by Angle modifiers (shown in the viewport) that would turn one of ``edges`` (None = every edge)
    back after Soften / Harden on ``bm``; empty when the result shows as it is. ``bm`` keeps its flags."""
    mods = [md for md in smooth_by_angle_mods(ob) if md.show_viewport]
    if not mods:
        return []
    bm.edges.index_update()
    targets = [e.index for e in (bm.edges if edges is None else edges)]
    before = _flags(bm)
    soften_harden(bm, angle, edges)
    want = _flags(bm)
    for md in mods:
        smooth_by_angle(bm, *smooth_by_angle_inputs(md))
    shown = _flags(bm)
    _set_flags(bm, before)
    return [] if all(shown[0][i] == want[0][i] for i in targets) else mods


def soften_harden_edit(ob, bm, angle, edges=None):
    """Soften / harden ``edges`` (None = every edge) of ``bm`` (the mesh of ``ob``) so the result shows. A Smooth by
    Angle modifier that would turn one of those edges back gives way: what it shows is written into every edge first
    (the other edges keep their look), then it is removed."""
    for md in giving_way(ob, bm, angle, edges):
        smooth_by_angle(bm, *smooth_by_angle_inputs(md))
        ob.modifiers.remove(md)
    soften_harden(bm, angle, edges)


def _picked(bm, whole):
    return None if whole else ([e for e in bm.edges if e.select] or None)


def _deselect(bm):
    for seq in (bm.verts, bm.edges, bm.faces):
        for el in seq:
            el.select = False


class ALLSET_OT_soften_harden(bpy.types.Operator):
    """Soften edges whose faces meet at less than the angle, harden the rest: the selected edges in
    component mode, every edge of the selected meshes in object mode (Maya Mesh Display > Soften/Harden)"""
    bl_idname = "allset.soften_harden"
    bl_label = "Soften/Harden Edges"
    # no UNDO: the command pushes its own undo steps (_through_object_mode), and Blender's Adjust Last Operation would
    # take back only part of them
    bl_options = {'REGISTER'}

    angle: FloatProperty(name="Angle", default=30.0, min=0.0, max=180.0,
                         description="Default 30: faces at a smaller angle shade smooth across the edge")
    option_box: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})
    # Quad Draw's options menu: every edge of the edited mesh, then nothing stays selected
    whole: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return any(ob.type == 'MESH' for ob in _meshes(context))

    def invoke(self, context, event):
        if self.option_box:
            return context.window_manager.invoke_props_dialog(self)
        return self.execute(context)

    def label(self):
        """The undo step name: the Maya menu item this angle is."""
        return {180.0: "Soften Edge", 0.0: "Harden Edge"}.get(round(self.angle, 4), self.bl_label)

    def execute(self, context):
        obs = _meshes(context)
        edit = [ob for ob in obs if ob.mode == 'EDIT']
        if any(self._gives_way(ob) for ob in edit):
            if self._through_object_mode(context, edit):
                undo_steps.mark_pushed()          # its last undo step is the command's own
                return {'FINISHED'}
        else:
            for ob in obs:
                if ob.mode == 'EDIT':
                    bm = bmesh.from_edit_mesh(ob.data)
                    soften_harden(bm, self.angle, _picked(bm, self.whole))
                    if self.whole:
                        _deselect(bm)
                    bmesh.update_edit_mesh(ob.data)
                else:
                    # every edge gets its new state: nothing older decides the shading any more (Blender's Shade
                    # Smooth / Shade Flat remove Smooth by Angle too)
                    for md in smooth_by_angle_mods(ob):
                        ob.modifiers.remove(md)
                    self._mesh_edit(ob, lambda bm: soften_harden(bm, self.angle))
        if undo_steps.depth() == 0:      # a Maya menu command pushes its step itself when it finished
            undo_steps.push(self.label())
        return {'FINISHED'}

    def _gives_way(self, ob):
        bm = bmesh.from_edit_mesh(ob.data)
        return bool(giving_way(ob, bm, self.angle, _picked(bm, self.whole)))

    @staticmethod
    def _mesh_edit(ob, fn):
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        fn(bm)
        bm.to_mesh(ob.data)
        bm.free()
        ob.data.update()

    def _through_object_mode(self, context, objects):
        """Component mode, and a Smooth by Angle modifier has to give way. An edit-mode undo step holds only the mesh,
        so the change runs in object mode between undo steps that hold everything: the state before (object mode,
        then the same in edit mode), then the result (object mode) as the command's own step, and component mode
        again. One Ctrl+Z lands on the edit-mode state before: the edges and the modifier come back together, in
        component mode with the same selection; Shift+Z lands on the result and goes back to component mode. Undo
        History lists the two steps before the result as "Object Mode" and "Edit Mode", like Tab's steps.
        True when the command's undo step was pushed."""
        from . import undo_pairs
        from ..command_line import undo_text
        scene, label = context.scene, self.label()
        names = [ob.name for ob in objects]
        bpy.ops.object.mode_set(mode='OBJECT')
        pushed = True
        try:
            undo_pairs.push_through(scene, undo_pairs.OBJECT_MODE_STEP, undo_pairs.BEFORE)
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.ed.undo_push(message=undo_pairs.EDIT_MODE_STEP)
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:          # no undo here (no window): just the change
            pushed = False
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

        def change(ob, bm):
            soften_harden_edit(ob, bm, self.angle, _picked(bm, self.whole))
            if self.whole:
                _deselect(bm)
        for ob in objects:
            self._mesh_edit(ob, lambda bm, ob=ob: change(ob, bm))
        result = undo_pairs.fingerprint(names)
        if pushed:
            try:
                undo_pairs.push_through(scene, label, undo_pairs.AFTER)
                undo_text.pushed(label)
            except RuntimeError:
                pushed = False
        bpy.ops.object.mode_set(mode='EDIT')
        if pushed:
            undo_pairs.arm(names, result)
        return pushed


def _meshes(context):
    if context.mode == 'EDIT_MESH':
        return [ob for ob in context.objects_in_mode if ob.type == 'MESH']
    return [ob for ob in context.selected_objects if ob.type == 'MESH']
