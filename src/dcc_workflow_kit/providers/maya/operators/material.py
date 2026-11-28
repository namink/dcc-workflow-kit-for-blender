# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya material assignment.

Lighting/Shading > Material Attributes / Assign New / Favorite / Existing Material
 and the same items at the end of the RMB object
menu list. Maya assigns to the selection,
or to the object the RMB menu was opened on when nothing is selected.

- Object assignment = the whole shape gets the material (Maya: the shape joins the
  shading group): one slot, every face/spline index 0.
- Face assignment (mesh edit mode, face select mode, selected faces) = only those
  faces: the material's slot is found or added and their ``material_index`` set.
  A mesh without slots first gets an empty slot so the other faces stay without a material.

New objects get no material (Blender's grey); there is no default material.
"""

import contextlib

import bmesh
import bpy
from bpy.props import BoolProperty, StringProperty

from .. import undo_steps
from .. import update_summary
from .. import compat

SUPPORTED = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}

# Every Maya entry that makes a material (Assign New / Favorite Material, the marking menu, the shelf, Hypershade
# Create, the command line's shadingNode) makes the same thing: Blender's new material, a Principled BSDF with
# Blender's own values and Blender's name (Material, Material.001 ...). Shader values and formulas are Blender's.
# ID property of materials made by older kit versions: the Maya node type they were made as (lambert, blinn,
# rampShader ...). Such a material keeps rendering as it was saved and shows the same Principled BSDF tab.
TYPE_PROP = "allset_type"
# New materials keep their viewport display colour equal to Base Color (the kit's shaded display mode draws it).
SYNC_PROP = "allset_display_sync"
NEW_NAME = "Material"
# Maya surface shader types the command line's shadingNode makes as a new material.
SURFACE_TYPES = ("standardSurface", "aiStandardSurface", "lambert", "blinn", "phong", "phongE", "anisotropic")
# The command line's initialShadingGroup: the shapes (and faces) without a material. Older kit versions marked a
# default material "lambert1" with "allset_default"; such a material is a plain material now.
DEFAULT_GROUP = "initialShadingGroup"
SHADED_TYPES = {'MESH', 'SURFACE'}   # Maya polygon and NURBS surface shapes (curves have no shading group)


# --- data ------------------------------------------------------------------------------------

def new_material():
    """Blender's new material: a Principled BSDF with Blender's values, named by Blender (Material, Material.001)."""
    mat = bpy.data.materials.new(NEW_NAME)
    mat[SYNC_PROP] = True
    compat.ensure_material_nodes(mat)
    sync_display(mat)
    return mat


def maya_type(mat):
    """The Maya node type the command line reports for a material: the type an older kit version recorded, else
    standardSurface for a Principled BSDF material (its attributes take Standard Surface names), else "material"."""
    if mat is None:
        return "material"
    recorded = mat.get(TYPE_PROP)
    if isinstance(recorded, str) and recorded and _principled(mat) is not None:
        return recorded
    return "standardSurface" if _principled(mat) is not None else "material"


# --- the "Maya Diffuse" node of older kit materials -------------------------------------------------------------
# Lambert-family materials made by earlier kit versions have a Mix node (RGBA, MIX, factor = diffuse, A = black,
# B = the colour or texture) in front of Principled Base Color. Such a material keeps rendering as it was saved:
# its Color is the node's B input (``color_socket``), the Attribute Editor shows its Diffuse row, File > Export links
# the colour straight to Base Color while it writes (``diffuse_bypass``), and Lighting/Shading > Convert Old Kit
# Materials (``convert_old``) turns it into a plain Principled BSDF once. New materials have no such node.

DIFFUSE_NODE = "Maya Diffuse"
DIFFUSE_SOCKET = "Diffuse"       # AE / map-button name of the diffuse factor (operators/shading_maps.py)


def _principled(mat):
    if mat is None or mat.node_tree is None:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)


def _ident(sockets, ident):
    return next((s for s in sockets if s.identifier == ident), None)


def diffuse_node(mat):
    """The material's "Maya Diffuse" Mix node, or None."""
    if mat is None or mat.node_tree is None:
        return None
    node = mat.node_tree.nodes.get(DIFFUSE_NODE)
    return node if node is not None and node.type == 'MIX' else None


def color_socket(mat):
    """The socket that is Maya's Color: the diffuse node's B colour when the material has one, else Principled Base
    Color (None without a Principled BSDF)."""
    node = diffuse_node(mat)
    if node is not None:
        return _ident(node.inputs, "B_Color")
    bsdf = _principled(mat)
    return bsdf.inputs.get("Base Color") if bsdf is not None else None


def maya_input(mat, name):
    """A material input by its AE / map-button name: "Base Color" = Maya Color (``color_socket``), DIFFUSE_SOCKET =
    the diffuse factor, else the Principled input of that name."""
    bsdf = _principled(mat)
    if bsdf is None:
        return None
    if name == "Base Color":
        return color_socket(mat)
    if name == DIFFUSE_SOCKET:
        node = diffuse_node(mat)
        return _ident(node.inputs, "Factor_Float") if node is not None else None
    return bsdf.inputs.get(name)


def convert_old(mat):
    """Turn an older kit material's Maya Diffuse node into a plain Principled set-up: whatever feeds the node's
    colour input is linked straight to Base Color, a plain colour becomes colour x diffuse, and the node is removed.
    Returns None (nothing to convert), 'COLOR' or 'TEXTURE' (a linked colour: it now renders without the diffuse
    factor, so it looks brighter)."""
    node, bsdf = diffuse_node(mat), _principled(mat)
    if node is None or bsdf is None or mat.library is not None:
        return None
    tree, base = mat.node_tree, bsdf.inputs["Base Color"]
    b = _ident(node.inputs, "B_Color")
    fac = _ident(node.inputs, "Factor_Float")
    for link in list(base.links):
        if link.from_node == node:
            tree.links.remove(link)
    if b.is_linked:
        tree.links.new(b.links[0].from_socket, base)
        kind = 'TEXTURE'
    else:
        f = 1.0 if fac.is_linked else max(0.0, min(1.0, float(fac.default_value)))
        r, g, bl, a = b.default_value
        base.default_value = (r * f, g * f, bl * f, a)
        kind = 'COLOR'
    tree.nodes.remove(node)
    sync_display(mat)
    return kind


def _sync_base(mat):
    """Keep the Principled Base Color default equal to the Maya colour (B) of a diffuse node; True when written."""
    node, bsdf = diffuse_node(mat), _principled(mat)
    if node is None or bsdf is None:
        return False
    b, base = _ident(node.inputs, "B_Color"), bsdf.inputs["Base Color"]
    if all(abs(x - y) < 1e-6 for x, y in zip(base.default_value, b.default_value)):
        return False
    base.default_value = b.default_value
    return True


@contextlib.contextmanager
def diffuse_bypass():
    """Exchange-format writers (FBX / OBJ / glTF ...) read Base Color's default or an image node linked straight to
    it: for the duration, link whatever feeds each diffuse node's B directly to Base Color (default = the B colour),
    then put the diffuse node back (kit File > Export, operators/file_io_export.write; Blender's own File > Export menu is
    not wrapped)."""
    saved = []
    for mat in bpy.data.materials:
        node, bsdf = diffuse_node(mat), _principled(mat)
        if node is None or bsdf is None or mat.library is not None:
            continue
        base = bsdf.inputs["Base Color"]
        if not base.is_linked or base.links[0].from_node != node:
            continue
        tree, b = mat.node_tree, _ident(node.inputs, "B_Color")
        old = tuple(base.default_value)
        tree.links.remove(base.links[0])
        if b.is_linked:
            tree.links.new(b.links[0].from_socket, base)
        base.default_value = b.default_value
        saved.append((mat, old))
    try:
        yield len(saved)
    finally:
        for mat, old in saved:
            node, bsdf = diffuse_node(mat), _principled(mat)
            if node is None or bsdf is None:
                continue
            base = bsdf.inputs["Base Color"]
            for link in list(base.links):
                mat.node_tree.links.remove(link)
            mat.node_tree.links.new(_ident(node.outputs, "Result_Color"), base)
            base.default_value = old


# --- viewport colour (issue #14) ---------------------------------------------------------------
# Maya's shaded mode (5) draws the material colour. Blender's Solid shading with colour type MATERIAL (the kit's
# display mode SHADED, operators/display.py) draws ``Material.diffuse_color``, the viewport display colour, which
# a Principled Base Color edit (Attribute Editor Color, Blender's material panel) doesn't change. Kit materials
# keep it equal to their colour (Base Color; older kit materials: surfaceShader = Emission Color, rampShader = the
# ramp's mean colour) and transparency (Alpha); materials made in Blender keep Blender's own display colour.

def _maya_colour(mat):
    """(r, g, b, a) the shaded display mode shows for a kit material, or None (not a kit material / no colour)."""
    if mat is None or not (mat.get(TYPE_PROP) or mat.get(SYNC_PROP)) or mat.node_tree is None:
        return None
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        return None
    sock = bsdf.inputs.get("Emission Color") if mat.get(TYPE_PROP) == "surfaceShader" else color_socket(mat)
    if sock is None:
        return None
    if sock.is_linked:
        src = sock.links[0].from_node
        if src.type != 'VALTORGB' or not len(src.color_ramp.elements):
            return None              # a texture: Maya's 5 shows no texture either, keep the display colour
        els = src.color_ramp.elements
        rgb = [sum(e.color[i] for e in els) / len(els) for i in range(3)]
    else:
        rgb = list(sock.default_value[:3])
    alpha = bsdf.inputs.get("Alpha")
    a = 1.0 if alpha is None or alpha.is_linked else float(alpha.default_value)
    return (*rgb, a)


def sync_display(mat):
    """Set a kit material's viewport display colour to its colour; True when it changed."""
    col = _maya_colour(mat)
    if col is None or all(abs(x - y) < 1e-6 for x, y in zip(mat.diffuse_color, col)):
        return False
    mat.diffuse_color = col
    return True


def shading_group_name(mat):
    """Maya's shading group of a material: <material>SG."""
    return f"{mat.name}SG"


_busy = [False]


@bpy.app.handlers.persistent
def _on_depsgraph(scene, depsgraph):
    if _busy[0]:
        return
    if depsgraph.id_type_updated('MATERIAL') or depsgraph.id_type_updated('NODETREE'):
        update_summary.wrote()
        _busy[0] = True
        try:
            for mat in bpy.data.materials:
                if mat.library is None and (mat.get(TYPE_PROP) or mat.get(SYNC_PROP)):
                    sync_display(mat)
                if mat.library is None:
                    _sync_base(mat)
        finally:
            _busy[0] = False


HANDLERS = ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph),)


# --- Diffuse of older kit materials ---------------------------------------------------------------------------------

def _get_diffuse(self):
    sock = maya_input(self, DIFFUSE_SOCKET)
    return 1.0 if sock is None else float(sock.default_value)


def _set_diffuse(self, value):
    sock = maya_input(self, DIFFUSE_SOCKET)       # only older kit materials have a diffuse factor
    if sock is not None:
        sock.default_value = max(0.0, min(1.0, value))


MATERIAL_PROPS = ("allset_diffuse",)


def register_props():
    from bpy.props import FloatProperty
    bpy.types.Material.allset_diffuse = FloatProperty(
        name="Diffuse", min=0.0, max=1.0, precision=3, get=_get_diffuse, set=_set_diffuse,
        description="Maya diffuse of a material made by an older kit version: the share of the colour reflected "
                    "(Base Color = Color x Diffuse through its Maya Diffuse node)")


def unregister_props():
    for name in MATERIAL_PROPS:
        if hasattr(bpy.types.Material, name):
            delattr(bpy.types.Material, name)


def register_handlers():
    for lst, fn in HANDLERS:
        if fn not in lst:
            lst.append(fn)


def unregister_handlers():
    for lst, fn in HANDLERS:
        if fn in lst:
            lst.remove(fn)


def targets(context, rmb=False):
    """Objects to assign to: the edited objects, the selection, else (from the RMB
    menu) the object the menu was opened on, like Maya."""
    if context.mode.startswith('EDIT'):
        return [o for o in context.objects_in_mode if o.type in SUPPORTED]
    obs = [o for o in context.selected_objects if o.type in SUPPORTED]
    if not obs and rmb:
        ob = bpy.data.objects.get(getattr(context.window_manager, "allset_mm_target", ""))
        if ob is not None and ob.type in SUPPORTED:
            obs = [ob]
    return obs


def _poll(context):
    # Poll can't see ``rmb``: the object under the last RMB menu counts too (Maya doesn't
    # grey these items either; without a target the operator reports and cancels).
    return bool(targets(context, rmb=True))


def _face_mode(context):
    return context.mode == 'EDIT_MESH' and context.tool_settings.mesh_select_mode[2]


def assign_object(ob, mat):
    """The whole object gets ``mat``; returns its slot index (0)."""
    data = ob.data
    if ob.type == 'MESH':
        if ob.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(data)
            for f in bm.faces:
                f.material_index = 0
            bmesh.update_edit_mesh(data)
        else:
            data.polygons.foreach_set("material_index", [0] * len(data.polygons))
    elif ob.type in {'CURVE', 'SURFACE'}:
        for spline in data.splines:
            spline.material_index = 0
    data.materials.clear()
    data.materials.append(mat)
    ob.active_material_index = 0
    ob.active_material = mat  # also right for object-linked slots
    return 0


def assign_faces(ob, mat):
    """Selected faces of an edited mesh get ``mat``; returns the slot index, or None
    when no face is selected."""
    bm = bmesh.from_edit_mesh(ob.data)
    faces = [f for f in bm.faces if f.select]
    if not faces:
        return None
    slots = ob.material_slots
    index = next((i for i, s in enumerate(slots) if s.material == mat), None)
    if index is None:
        if not slots:   # the rest of the mesh stays without a material (an empty slot)
            ob.data.materials.append(None)
        ob.data.materials.append(mat)
        index = len(ob.material_slots) - 1
        bm = bmesh.from_edit_mesh(ob.data)
        faces = [f for f in bm.faces if f.select]
    for f in faces:
        f.material_index = index
    bmesh.update_edit_mesh(ob.data)
    return index


def assign(context, mat, obs):
    """Assign ``mat`` the Maya way; returns {object name: slot index}."""
    done = {}
    faces = _face_mode(context)
    for ob in obs:
        index = assign_faces(ob, mat) if faces and ob.type == 'MESH' and ob.mode == 'EDIT' else None
        done[ob.name] = assign_object(ob, mat) if index is None else index
    return done


def _show_in_ae(context, done):
    """Point the Attribute Editor's tab at the assigned material (Maya shows a new
    material in the AE, AEpopupWhenCreatingShaders)."""
    from ..ui import attribute_editor
    ob = context.active_object
    if ob is None or ob.name not in done:
        ob = bpy.data.objects.get(next(iter(done)))
    attribute_editor.set_tab(context, f"MAT:{done[ob.name]}")


# --- operators -------------------------------------------------------------------------------

_RMB = BoolProperty(name="From RMB Menu", options={'HIDDEN', 'SKIP_SAVE'},
                    description="Use the object under the RMB menu when nothing is selected")


# A Maya shader type of an older call (a saved shelf button, a custom marking menu): accepted and ignored, every
# entry makes the same new material.
_KIND = StringProperty(name="Type", options={'HIDDEN', 'SKIP_SAVE'})


def create_and_assign(op, context):
    obs = targets(context, op.rmb)
    if not obs:
        op.report({'WARNING'}, "Select objects or faces to assign a material to")
        return {'CANCELLED'}
    mat = new_material()
    _show_in_ae(context, assign(context, mat, obs))
    return {'FINISHED'}


class ALLSET_OT_shelf_material(bpy.types.Operator):
    """Create a new material (Blender's Principled BSDF) and assign it to the selected objects or faces (Maya
    shelf material button, Assign Favorite Material)"""
    bl_idname = "allset.shelf_material"
    bl_label = "New Material"
    bl_options = {'REGISTER', 'UNDO'}

    kind: _KIND
    rmb: _RMB

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def execute(self, context):
        return create_and_assign(self, context)


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_assign_new_material(bpy.types.Operator):
    """Create a new material (Blender's Principled BSDF) and assign it to the selected objects or faces
    (Maya Assign New Material, Shift+T)"""
    bl_idname = "allset.assign_new_material"
    bl_label = "Assign New Material"
    bl_options = {'REGISTER', 'UNDO'}

    kind: _KIND
    rmb: _RMB

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def execute(self, context):
        return create_and_assign(self, context)


class ALLSET_OT_assign_material(bpy.types.Operator):
    """Assign this material to the selected objects or faces (Maya Assign Existing Material)"""
    bl_idname = "allset.assign_material"
    bl_label = "Assign Existing Material"
    bl_options = {'REGISTER', 'UNDO'}

    material: StringProperty(name="Material", options={'SKIP_SAVE'})
    rmb: _RMB

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def execute(self, context):
        mat = bpy.data.materials.get(self.material)
        obs = targets(context, self.rmb)
        if mat is None or not obs:
            self.report({'WARNING'}, "Select objects or faces and a material")
            return {'CANCELLED'}
        assign(context, mat, obs)
        return {'FINISHED'}


class ALLSET_OT_material_attributes(bpy.types.Operator):
    """Show the object's material in the Attribute Editor (Maya Material Attributes)"""
    bl_idname = "allset.material_attributes"
    bl_label = "Material Attributes"

    rmb: _RMB

    @staticmethod
    def _object(context, rmb):
        if rmb:
            ob = bpy.data.objects.get(getattr(context.window_manager, "allset_mm_target", ""))
            if ob is not None:
                return ob
        return context.active_object

    @classmethod
    def poll(cls, context):
        ob = cls._object(context, True)
        return ob is not None and any(s.material for s in ob.material_slots)

    def execute(self, context):
        from ..ui import attribute_editor
        ob = self._object(context, self.rmb)
        if ob is None:
            return {'CANCELLED'}
        slots = ob.material_slots
        i = ob.active_material_index
        if i >= len(slots) or slots[i].material is None:
            i = next((n for n, s in enumerate(slots) if s.material), None)
        if i is None:
            self.report({'WARNING'}, f"{ob.name} has no material")
            return {'CANCELLED'}
        if context.active_object is not ob and context.view_layer.objects.get(ob.name):
            context.view_layer.objects.active = ob
        attribute_editor.show_dock(context, 'ATTRIBUTE_EDITOR')
        attribute_editor.set_tab(context, f"MAT:{i}")
        for area in context.screen.areas if context.screen else ():
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'FINISHED'}


class ALLSET_OT_convert_old_materials(bpy.types.Operator):
    """Turn the materials made by older kit versions into plain Principled BSDF materials: the Maya Diffuse node in
    front of Base Color is removed (a plain colour keeps its look, a texture now shows at full brightness)"""
    bl_idname = "allset.convert_old_materials"
    bl_label = "Convert Old Kit Materials"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        done = {'COLOR': 0, 'TEXTURE': 0}
        for mat in bpy.data.materials:
            kind = convert_old(mat)
            if kind is not None:
                done[kind] += 1
        total = done['COLOR'] + done['TEXTURE']
        from .. import results
        if not total:
            results.result(self, "No old kit materials to convert")
            return {'CANCELLED'}
        msg = f"Converted {total} material(s) to plain Principled BSDF"
        if done['TEXTURE']:
            msg += (f"; {done['TEXTURE']} with a texture on Color now show it at full brightness "
                    "(brighter than before)")
        if done['TEXTURE']:
            self.report({'WARNING'}, msg)
        else:
            results.result(self, msg)
        return {'FINISHED'}


# --- menus -----------------------------------------------------------------------------------

class ALLSET_MT_assign_favorite_material(bpy.types.Menu):
    """Create a new material and assign it (Maya Assign Favorite Material: Blender has one material, the Principled
    BSDF)"""
    bl_idname = "ALLSET_MT_assign_favorite_material"
    bl_label = "Assign Favorite Material"
    rmb = False

    def draw(self, context):
        op = self.layout.operator("allset.shelf_material", text="New Material", icon='MATERIAL')
        op.rmb = self.rmb


class ALLSET_MT_assign_existing_material(bpy.types.Menu):
    """Assign a material of the scene (Maya Assign Existing Material)"""
    bl_idname = "ALLSET_MT_assign_existing_material"
    bl_label = "Assign Existing Material"
    rmb = False

    def draw(self, context):
        mats = sorted((m for m in bpy.data.materials if not m.is_grease_pencil), key=lambda m: m.name.lower())
        if not mats:
            self.layout.label(text="No materials in the scene")
            return
        for mat in mats:
            op = self.layout.operator("allset.assign_material", text=mat.name, icon='MATERIAL')
            op.material = mat.name
            op.rmb = self.rmb


class ALLSET_MT_assign_existing_material_rmb(ALLSET_MT_assign_existing_material):
    """Assign a material of the scene to the selection or the object under the RMB menu"""
    bl_idname = "ALLSET_MT_assign_existing_material_rmb"
    rmb = True


classes = (ALLSET_OT_shelf_material, ALLSET_OT_assign_new_material, ALLSET_OT_assign_material,
           ALLSET_OT_material_attributes, ALLSET_OT_convert_old_materials, ALLSET_MT_assign_favorite_material,
           ALLSET_MT_assign_existing_material, ALLSET_MT_assign_existing_material_rmb)
