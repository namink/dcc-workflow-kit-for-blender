# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's Joint Tool (``allset.joint_tool``): clicks / drags in a 3D View place joints (each a child of the last), a
click on a joint's drawn sphere branches from it, Z / Shift+Z undo / redo inside the tool, Enter / Q / W / E / R finish
(orient, radius, optional IK handle). Building blocks other code reuses: ``new_skeleton``, ``add_joint``,
``move_joint``, ``finish``, ``click_point``, ``view_under``, ``joint_sphere_radius``, ``pick_branch_joint``.
"""

import json

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from .. import results
from . import joint_preview, naming, scene_axes, units
from .joint_common import SKELETON_BASE, _cb, next_joint_name, stamp_last
from .joint_frames import RADIUS, orient_new


STATUS = "Joint Tool: click to place, drag to position. Click a joint to branch. Enter finishes"


# --- placing joints ---------------------------------------------------------------------------

def click_point(region, rv3d, coord):
    """World point for a click (Maya Joint Tool depth): an orthographic view places on the view plane
    through the origin, a perspective view on the ground (z = 0), else at the origin's depth."""
    origin = Vector((0.0, 0.0, 0.0))
    if rv3d.is_perspective:
        start = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        ray = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        if abs(ray.z) > 1e-6:
            t = -start.z / ray.z
            if t > 0:
                return start + ray * t
    return view3d_utils.region_2d_to_location_3d(region, rv3d, coord, origin)


def new_skeleton(context):
    """``skeleton1``: an armature at the origin, selected, active, in edit mode."""
    arm = bpy.data.armatures.new(SKELETON_BASE)
    ob = bpy.data.objects.new(SKELETON_BASE, arm)
    context.view_layer.active_layer_collection.collection.objects.link(ob)
    naming.apply_maya_name(ob, SKELETON_BASE, rename_data=False)
    arm.name = ob.name
    if context.active_object is not None and context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for other in context.selected_objects:
        other.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    return ob


def add_joint(ob, point, parent_name=None, up=Vector((0.0, 0.0, 1.0)), length=1.0):
    """Add a joint (edit bone) at world ``point`` under ``parent_name``; returns its name (the parent's
    name when the click repeats the parent's position). An end joint parent gets its tail moved here."""
    ebs = ob.data.edit_bones
    p = ob.matrix_world.inverted() @ Vector(point)
    parent = ebs.get(parent_name) if parent_name else None
    if parent is not None and (p - parent.head).length < 1e-6:
        return parent.name
    eb = ebs.new(next_joint_name())
    eb.inherit_scale = 'NONE'      # Maya segmentScaleCompensate on (the default; Blender 4.5)
    stamp_last(eb)                 # Maya child order = creation order
    eb.head = p
    if parent is None:
        eb.tail = p + Vector(up).normalized() * length
        return eb.name
    seg = p - parent.head
    if len(parent.children) == 0:
        parent.tail = p                      # the parent was an end joint: it now reaches this one
    eb.parent = parent
    eb.use_connect = (parent.tail - p).length < 1e-6
    eb.tail = p + seg.normalized() * seg.length * 0.5
    return eb.name


def move_joint(ob, name, point, up=Vector((0.0, 0.0, 1.0)), length=1.0):
    """Move the end joint ``name`` (just placed by ``add_joint``) to world ``point`` with the same rules: the bone
    from its parent follows when connected, its own tail keeps half the parent segment (a root: ``length`` along
    ``up``). A point on the parent joint itself is skipped (no zero-length bone). True when moved."""
    eb = ob.data.edit_bones.get(name)
    if eb is None:
        return False
    p = ob.matrix_world.inverted() @ Vector(point)
    parent = eb.parent
    if parent is None:
        eb.head = p
        eb.tail = p + Vector(up).normalized() * length
        return True
    seg = p - parent.head
    if seg.length < 1e-6:
        return False
    if eb.use_connect:
        parent.tail = p
    eb.head = p
    eb.tail = p + seg * 0.5
    return True


def finish(context, ob, names, top=None):
    """Pose mode, new joints rotate XYZ. Maya 2026 selects the top of the branch just made: the
    new chain's root, or ``top`` = the existing joint the chain branched from."""
    if ob.mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
    cb = _cb()
    for pb in ob.pose.bones:
        if pb.name in names:
            pb.rotation_mode = 'XYZ'
        cb.set_bone_selected(pb, False)
    head = top or (names[0] if names else None)
    pb = ob.pose.bones.get(head) if head else None
    if pb is not None:
        cb.set_bone_selected(pb, True)
        ob.data.bones.active = pb.bone


def view_under(window, x, y):
    """(area, WINDOW region) of the 3D View under window position x, y (not the Tool Box column)."""
    from ..ui import toolbox
    if window is None:
        return None
    for area in window.screen.areas:
        if area.type != 'VIEW_3D' or toolbox.is_toolbox(area.spaces.active):
            continue
        for region in area.regions:
            if region.type == 'WINDOW' and region.x <= x < region.x + region.width \
                    and region.y <= y < region.y + region.height:
                return area, region
    return None


# Maya Joint Tool settings the kit honours: Secondary Axis Y with
# Secondary Axis World Orientation + up (Joint Tool default; the scene's +Z here), Create IK handle off. Blender bones point their Y at the
# child (= Maya Primary Axis X); a joint's Maya Y / Z = the bone's Z / X (rig_tools.local_axis).
SECONDARY_AXES = (("X", "X", "Maya X is the primary axis: not allowed"), ("Y", "Y", "The bone's Z axis"),
                  ("Z", "Z", "The bone's X axis"), ("NONE", "None", "Leave the bone roll as placed"))
# Maya world axis (Y-up) -> Blender world vector (Z-up: X -> X, Y -> Z, Z -> -Y)
WORLD_AXES = {"X": Vector((1.0, 0.0, 0.0)), "Y": Vector((0.0, 0.0, 1.0)), "Z": Vector((0.0, -1.0, 0.0))}


# A Joint Tool click inside a joint's drawn sphere branches from it (Maya 2026: the hit area is the drawn sphere,
# not a fixed radius). Blender draws an octahedral bone's joint as a sphere of radius
# JOINT_SPHERE x the bone length (a connected head: the incoming bone's tail sphere; Blender's bone point shape);
# the floor is Maya's click box (select_priority.RADIUS_PX), also the whole hit area of Stick bones.
JOINT_SPHERE = 0.05
BRANCH_MIN_PX = 5.0


def joint_sphere_radius(arm, bone):
    """World radius of the sphere Blender draws at ``bone``'s head (0 when it draws none: Stick / B-Bone / ...)."""
    scale = max(arm.matrix_world.to_scale())
    maya = bone.get(RADIUS)
    if maya is not None:     # the Maya joint radius (Joint Tool variable bone size) is the click sphere
        # x Display > Animation > Joint Size (Maya jointDisplayScale); the armature's own scale leaves it alone
        from .joint_display import joint_size, skeleton_scale
        size = joint_size(bpy.context.scene)
        return float(maya) * units.radius_unit(bpy.context.scene) * skeleton_scale(arm) * size
    if arm.data.display_type != 'OCTAHEDRAL':
        return 0.0
    src = bone.parent if bone.parent is not None and bone.use_connect else bone
    return JOINT_SPHERE * src.length * scale


def pick_branch_joint(region, rv3d, armatures, coord, floor):
    """(armature, bone name) whose head sphere holds ``coord`` (screen px), nearest first; None."""
    from bpy_extras import view3d_utils
    right = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
    best, best_d = None, None
    for arm in armatures:
        for bone in arm.data.bones:
            if bone.hide or (bone.collections and not any(c.is_visible_effectively for c in bone.collections)):
                continue
            head = arm.matrix_world @ bone.head_local
            p = view3d_utils.location_3d_to_region_2d(region, rv3d, head)
            if p is None:
                continue
            r = joint_sphere_radius(arm, bone)
            edge = view3d_utils.location_3d_to_region_2d(region, rv3d, head + right * r) if r > 0 else None
            radius = max(floor, (edge - p).length if edge is not None else 0.0)
            d = (Vector(coord) - p).length
            if d <= radius and (best_d is None or d < best_d):
                best, best_d = (arm, bone.name), d
    return best


class ALLSET_OT_joint_tool(bpy.types.Operator):
    """Maya Joint Tool: click in a view to place joints (each one a child of the last), Enter to finish"""
    bl_idname = "allset.joint_tool"
    bl_label = "Joint Tool"
    bl_options = {'UNDO'}

    secondary_axis: EnumProperty(name="Secondary Axis", items=SECONDARY_AXES, default="Y")
    secondary_world: EnumProperty(name="Secondary Axis World Orientation",
                                  items=[(a, a, f"The scene's {a} axis") for a in ("X", "Y", "Z")], default="Z")
    secondary_sign: EnumProperty(name="Sign", items=(("+", "+", ""), ("-", "-", "")), default="+")
    # Maya 2025+ Joint Tool default: auto orient secondary on; Orient Joint to World =
    # no orientation
    auto_secondary: BoolProperty(name="Auto orient secondary axis", default=True)
    orient_world: BoolProperty(name="Orient Joint to World", default=False)
    create_ik: BoolProperty(name="Create IK handle", default=False)
    ik_solver: EnumProperty(name="Current solver",
                            items=(("RP", "Rotate-Plane Solver", ""), ("SC", "Single-Chain Solver", "")), default="RP")
    ik_solver_enable: BoolProperty(name="Solver enable", default=True)
    ik_weight: FloatProperty(name="Weight", default=1.0, min=0.01, max=1.0)
    points: StringProperty(options={'SKIP_SAVE', 'HIDDEN'},
                           description="JSON list of world points: place these joints without clicks (scripts)")

    def execute(self, context):
        """Without clicks: a new skeleton with a joint at each of ``points``."""
        try:
            pts = [Vector(p) for p in json.loads(self.points)] if self.points else []
        except (ValueError, TypeError):
            pts = []
        if not pts:
            self.report({'WARNING'}, "Joint Tool: click in a view to place joints")
            return {'CANCELLED'}
        ob = new_skeleton(context)
        names, parent = [], None
        for p in pts:
            name = add_joint(ob, p, parent, length=units.maya_unit(context.scene))
            if name != parent:
                names.append(name)
            parent = name
        self._names, self._ob = names, ob
        return self._finish(context)

    def invoke(self, context, event):
        if context.window is None:
            return {'CANCELLED'}
        # Maya never branches from a joint selected before the tool starts (joint1 selected, two
        # clicks -> an unparented chain); clicking an existing joint with the tool does
        # (``_branch_from``).
        self._names, self._ob, self._parent, self._top = [], None, None, None
        self._placed, self._redo = [], []   # joints placed by this tool run, newest last / undone ones
        self._swallow = False
        self._drag = None          # (joint name, area pointer, region pointer) while the button is held
        self._cursor = False
        context.workspace.status_text_set(STATUS)
        from .. import command_line
        command_line.MODAL_HELP[self.bl_idname] = STATUS
        joint_preview.start()
        self._hover(context, event)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _end(self, context):
        context.workspace.status_text_set(None)
        joint_preview.stop()
        self._set_cursor(context, False)
        joint_preview.redraw(context.window)

    def _set_cursor(self, context, on):
        """Crosshair while the pointer is over a 3D View (where a click places a joint)."""
        if on == self._cursor or context.window is None:
            return
        if on:
            context.window.cursor_modal_set('CROSSHAIR')
        else:
            context.window.cursor_modal_restore()
        self._cursor = on

    def _sync_preview(self):
        st = joint_preview.STATE
        try:
            st["ob"] = self._ob.name if self._ob is not None else None
        except ReferenceError:
            st["ob"] = None
        st["names"] = list(self._names)
        st["top"] = self._top
        st["current"] = self._parent

    def _hover(self, context, event):
        """Preview state for the pointer: where a click would place the next joint, or the joint it would branch
        from."""
        st = joint_preview.STATE
        st["dragging"] = self._drag is not None
        hit = view_under(context.window, event.mouse_x, event.mouse_y) if context.window is not None else None
        self._set_cursor(context, hit is not None)
        if hit is None:
            st.update(region=0, point=None, branch=None)
        else:
            _area, region = hit
            coord = (event.mouse_x - region.x, event.mouse_y - region.y)
            branch = None
            if self._ob is None:
                arms = [o for o in context.view_layer.objects if o is not None and o.type == 'ARMATURE' and o.visible_get()]
                scale = context.preferences.system.ui_scale or 1.0
                if arms:
                    found = pick_branch_joint(region, region.data, arms, coord, BRANCH_MIN_PX * scale)
                    branch = (found[0].name, found[1]) if found else None
            point = click_point(region, region.data, coord)
            st.update(region=region.as_pointer(), point=tuple(point), branch=branch)
        self._sync_preview()
        joint_preview.redraw(context.window)

    def _drag_to(self, context, event):
        """Move the joint placed by the press with the pointer (Maya: the joint follows until release)."""
        from .. import live_refs
        name, area_ptr, region_ptr = self._drag
        area = live_refs.area(area_ptr, context.window)
        region = live_refs.region(area, region_ptr)
        if region is None or self._ob is None:
            return
        rv3d = region.data
        coord = (event.mouse_x - region.x, event.mouse_y - region.y)
        point = click_point(region, rv3d, coord)
        up = rv3d.view_rotation @ Vector((0.0, 1.0, 0.0))
        move_joint(self._ob, name, point, up=up, length=units.maya_unit(context.scene))
        joint_preview.redraw(context.window)

    def _place(self, context, event):
        hit = view_under(context.window, event.mouse_x, event.mouse_y)
        if hit is None:
            return False
        area, region = hit
        rv3d = region.data
        coord = (event.mouse_x - region.x, event.mouse_y - region.y)
        self._drag = None
        if self._ob is None and self._branch_from(context, area, region, coord):
            return True
        point = click_point(region, rv3d, coord)
        up = rv3d.view_rotation @ Vector((0.0, 1.0, 0.0))
        self._redo.clear()
        name = self._add_at(context, area, region, point, up)
        if name is not None:
            self._drag = (name, area.as_pointer(), region.as_pointer())
        return True

    def _add_at(self, context, area, region, point, up):
        """Place the next joint at world ``point``; returns its name (None when the click repeats the current
        joint). Each placed joint is remembered so undo inside the tool can take it back."""
        created = self._ob is None
        if created:
            with context.temp_override(window=context.window, area=area, region=region):
                self._ob = new_skeleton(context)
        if self._ob.mode != 'EDIT':
            with context.temp_override(window=context.window, area=area, region=region):
                bpy.ops.object.mode_set(mode='EDIT')
        parent = self._ob.data.edit_bones.get(self._parent) if self._parent else None
        tail = parent.tail.copy() if parent is not None and len(parent.children) == 0 else None
        name = add_joint(self._ob, point, self._parent, up=up, length=units.maya_unit(context.scene))
        if name == self._parent:
            return None
        self._names.append(name)
        self._placed.append((name, self._parent, tail, Vector(point), Vector(up), created))
        self._parent = name
        area.tag_redraw()
        return name

    def _undo_joint(self, context):
        """Undo inside the tool (like Maya): take back the last joint this run placed; the skeleton goes when its
        first joint does. The tool keeps running."""
        if not self._placed or self._ob is None:
            return
        name, parent, tail, point, up, created = self._placed.pop()
        self._drag = None
        hit = self._any_view(context)
        override = dict(window=context.window, area=hit[0], region=hit[1]) if hit else dict(window=context.window)
        ob = self._ob
        with context.temp_override(**override):
            if ob.mode != 'EDIT':
                bpy.ops.object.mode_set(mode='EDIT')
            ebs = ob.data.edit_bones
            eb = ebs.get(name)
            if eb is not None:
                ebs.remove(eb)
            pe = ebs.get(parent) if parent else None
            if pe is not None and tail is not None:
                pe.tail = tail
            if name in self._names:
                self._names.remove(name)
            self._parent = parent
            self._redo.append((point, up))
            if created:
                bpy.ops.object.mode_set(mode='OBJECT')
                arm = ob.data
                bpy.data.objects.remove(ob)
                if arm.users == 0:
                    bpy.data.armatures.remove(arm)
                self._ob, self._parent, self._names, self._placed = None, None, [], []
        if hit:
            hit[0].tag_redraw()

    def _redo_joint(self, context):
        """Redo inside the tool: place the joint the last undo took back."""
        if not self._redo:
            return
        point, up = self._redo.pop()
        hit = self._any_view(context)
        if hit is not None:
            self._add_at(context, hit[0], hit[1], point, up)

    def _check_alive(self):
        """The skeleton or its joints can be removed behind the tool (Edit > Undo, a script): forget what is
        gone instead of touching removed data."""
        if self._ob is None:
            return
        try:
            ebs = self._ob.data.edit_bones if self._ob.mode == 'EDIT' else None
        except ReferenceError:
            self._names, self._ob, self._parent, self._top = [], None, None, None
            self._placed, self._redo, self._drag = [], [], None
            return
        if ebs is None:
            return
        self._names = [n for n in self._names if n in ebs]
        self._placed = [e for e in self._placed if e[0] in ebs]
        if self._parent is not None and self._parent not in ebs:
            self._parent = self._names[-1] if self._names else self._top
        if self._drag is not None and self._drag[0] not in ebs:
            self._drag = None

    def _branch_from(self, context, area, region, coord):
        """The first click on an existing joint: the new joints go under it (Maya Joint Tool). True when hit."""
        arms = [o for o in context.view_layer.objects if o is not None and o.type == 'ARMATURE' and o.visible_get()]
        scale = context.preferences.system.ui_scale or 1.0
        hit = pick_branch_joint(region, region.data, arms, coord, BRANCH_MIN_PX * scale) if arms else None
        if hit is None:
            return False
        arm, name = hit
        with context.temp_override(window=context.window, area=area, region=region):
            if context.mode != 'OBJECT' and context.active_object is not None:
                bpy.ops.object.mode_set(mode='OBJECT')
            for o in context.selected_objects:
                o.select_set(False)
            arm.select_set(True)
            context.view_layer.objects.active = arm
            bpy.ops.object.mode_set(mode='EDIT')
        self._ob, self._parent, self._top = arm, name, name
        area.tag_redraw()
        return True

    def modal(self, context, event):
        self._check_alive()
        if event.value == 'PRESS' and event.type in {'Z', 'Y'} and not (event.alt or event.oskey):
            plain = not (event.ctrl or event.shift)
            if (event.type == 'Z' and (plain or (event.ctrl and not event.shift))):
                self._undo_joint(context)
                self._hover(context, event)
                return {'RUNNING_MODAL'}
            if (event.type == 'Z' and event.shift) or (event.type == 'Y' and event.ctrl and not event.shift):
                self._redo_joint(context)
                self._hover(context, event)
                return {'RUNNING_MODAL'}
        # Maya 2026 ends the tool on Enter / Q / W / E / R with the branch top selected; Enter and Q leave the Select
        # Tool, W / E / R their tool.
        enter = event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS'
        if enter or (event.type in {'Q', 'W', 'E', 'R'} and event.value == 'PRESS'
                     and not (event.alt or event.ctrl or event.shift or event.oskey)):
            result = self._done(context)
            tool = {'Q': 'builtin.select_box', 'W': 'builtin.move',
                    'E': 'builtin.rotate', 'R': 'builtin.scale'}.get(event.type, 'builtin.select_box')
            hit = view_under(context.window, event.mouse_x, event.mouse_y) or self._any_view(context)
            if hit is not None and 'FINISHED' in result:
                with context.temp_override(window=context.window, area=hit[0], region=hit[1]):
                    bpy.ops.wm.tool_set_by_id(name=tool)
                # this command picked the Pose-mode tool itself; the one-tool carry must not
                # replace it with the placing mode's Select tool on the first Pose visit
                from . import tool_keys
                tool_keys._seen[context.mode] = tool
                tool_keys._mode[0] = context.mode
            return result
        if event.type == 'ESC' and event.value == 'PRESS':
            if not self._names:
                self._end(context)
                return {'CANCELLED'}
            return self._done(context)
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            if self._drag is not None:
                self._drag_to(context, event)
                return {'RUNNING_MODAL'}
            self._hover(context, event)
            return {'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS' and not (event.alt or event.ctrl or event.shift or event.oskey):
                if self._place(context, event):
                    self._swallow = True
                    self._hover(context, event)
                    return {'RUNNING_MODAL'}
            elif event.value == 'RELEASE' and self._swallow:
                self._swallow = False
                if self._drag is not None:
                    self._drag_to(context, event)
                    self._drag = None
                self._hover(context, event)
                return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    @staticmethod
    def _any_view(context):
        from ..ui import toolbox
        if context.window is None:          # no window (background, #158)
            return None
        return next(((a, r) for a in context.window.screen.areas
                     if a.type == 'VIEW_3D' and not toolbox.is_toolbox(a.spaces.active)
                     for r in a.regions if r.type == 'WINDOW'), None)

    def _done(self, context):
        self._end(context)
        if self._ob is None or not self._names:
            return {'CANCELLED'}
        hit = self._any_view(context)
        override = dict(window=context.window, area=hit[0], region=hit[1]) if hit else dict(window=context.window)
        with context.temp_override(**override):
            return self._finish(context)

    def _finish(self, context):
        ob, names = self._ob, self._names
        try:
            world, sign = scene_axes.signed_to_yup(self.secondary_world, self.secondary_sign)
            orient_new(ob, names, self.secondary_axis, world, sign, self.auto_secondary, self.orient_world)
        except RuntimeError as ex:
            self.report({'WARNING'}, str(ex))
        finish(context, ob, names, getattr(self, "_top", None))
        msg = f"Created {len(names)} joint(s) in {ob.name}"
        if self.create_ik and len(names) >= 2:
            from .skin import create_ik
            handle = create_ik(context, ob, (names[0], 'HEAD'), (names[-1], 'HEAD'), self.ik_solver,
                               self.ik_solver_enable, self.ik_weight)
            if handle is not None:
                msg += f" and {handle.name}"
        results.result(self, msg)
        return {'FINISHED'}
