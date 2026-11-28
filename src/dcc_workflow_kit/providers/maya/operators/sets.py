# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya object sets (Create > Sets, Select > Quick Select Sets, Outliner set rows).

Maya behaviour (names set1, set2 …, selection kept,
``select <set>`` = the members, Quick Select Set = a set with text "gCharacterSet").
Blender has no set node, so a kit set is a collection that is not linked to any scene
(fake user, so it is saved) carrying the ID property ``allset_set`` = its creation number
(Outliner order); its objects are the members — an object can be in several collections, so
the scene tree is untouched.

Like Maya, a set can also hold mesh components (``pCube1.vtx[0:3]``, ``pCube1.e[4]``, ``pCube2.f[1]``), next to whole
objects. They are hidden boolean attributes of the mesh, one per component type (``.allset_set_<id>_vtx`` on the
points, ``_e`` on the edges, ``_f`` on the faces; ``<id>`` = the set's ``allset_set_uid``, so a rename keeps them), so
they are saved with the mesh and follow edits that keep its topology. The objects carrying them are linked to a child
collection of the set (``allset_set_parts``): the set's own objects stay its whole-object members.
"""


import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from .. import results
from . import naming
from .. import i18n

PROP = "allset_set"
TEXT = "allset_set_text"
QUICK = "gCharacterSet"     # Maya's text for Quick Select Sets
UID = "allset_set_uid"      # names the set's component attributes
PARTS = "allset_set_parts"  # marks the child collection of the objects with component members
# Blender attribute domain, Maya component name, BMesh sequence
DOMAINS = (('POINT', "vtx", "verts"), ('EDGE', "e", "edges"), ('FACE', "f", "faces"))


def is_set(coll):
    return coll is not None and coll.get(PROP) is not None


def all_sets():
    """Kit sets in creation order (Maya's Outliner order)."""
    return sorted((c for c in bpy.data.collections if is_set(c)), key=lambda c: (c.get(PROP), c.name))


def quick_sets():
    return [c for c in all_sets() if c.get(TEXT) == QUICK]


def get(name):
    coll = bpy.data.collections.get(name)
    return coll if is_set(coll) else None


def next_name(base="set"):
    """Maya: ``set<N>`` one past the highest, gaps not filled."""
    return f"{base}{naming.next_number(base, {c.name for c in bpy.data.collections})}"


def create(name="", objects=(), text="", parts=None):
    """New set of ``objects`` and the components ``parts`` ({mesh object: {domain: [indices]}})."""
    order = max((c.get(PROP) for c in bpy.data.collections if is_set(c)), default=0) + 1
    coll = bpy.data.collections.new(name or next_name())
    coll.use_fake_user = True      # not in any scene: the fake user keeps it in the file
    coll[PROP] = order
    if text:
        coll[TEXT] = text
    for ob in objects:
        if ob.name not in coll.objects:
            coll.objects.link(ob)
    for ob, comp in (parts or {}).items():
        add_components(coll, ob, comp)
    return coll


def members(coll, scene=None):
    """The set's objects that are in ``scene`` (all of them without a scene)."""
    obs = list(coll.objects)
    if scene is None:
        return obs
    in_scene = set(scene.objects)
    return [ob for ob in obs if ob in in_scene]


# --- component members ----------------------------------------------------------------------------------------------

def _uid(coll):
    uid = coll.get(UID)
    if uid is None:
        import secrets
        uid = coll[UID] = secrets.token_hex(4)
    return uid


def layer_name(coll, domain):
    """The mesh attribute holding the set's components of ``domain`` ('POINT' / 'EDGE' / 'FACE')."""
    short = next(s for d, s, _seq in DOMAINS if d == domain)
    return f".allset_set_{_uid(coll)}_{short}"


def _parts(coll, create_it=False):
    """The child collection of the objects that have component members (None when there is none)."""
    for child in coll.children:
        if child.get(PARTS):
            return child
    if not create_it:
        return None
    child = bpy.data.collections.new(f"{coll.name}Components")
    child[PARTS] = True
    coll.children.link(child)
    return child


def part_objects(coll, scene=None):
    """Objects with component members of the set (in ``scene``)."""
    child = _parts(coll)
    if child is None:
        return []
    obs = list(child.objects)
    if scene is None:
        return obs
    in_scene = set(scene.objects)
    return [ob for ob in obs if ob in in_scene]


def _bm(ob):
    """The BMesh of a mesh in Edit Mode (None in Object Mode)."""
    return bmesh.from_edit_mesh(ob.data) if ob.type == 'MESH' and ob.mode == 'EDIT' else None


def components(coll, ob):
    """{domain: sorted indices} of ``ob``'s components in the set (empty domains left out)."""
    if ob.type != 'MESH':
        return {}
    out = {}
    bm = _bm(ob)
    for domain, _short, seq_name in DOMAINS:
        name = layer_name(coll, domain)
        if bm is not None:
            seq = getattr(bm, seq_name)
            lay = seq.layers.bool.get(name)
            idx = [e.index for e in seq if e[lay]] if lay is not None else []
        else:
            attr = ob.data.attributes.get(name)
            if attr is None or attr.domain != domain or attr.data_type != 'BOOLEAN':
                continue
            import numpy as np
            vals = np.zeros(len(attr.data), bool)
            attr.data.foreach_get("value", vals)
            idx = np.flatnonzero(vals).tolist()
        if idx:
            out[domain] = idx
    return out


def _ranges(ids):
    ids = sorted(set(ids))
    out, i = [], 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
            j += 1
        out.append(f"{ids[i]}" if i == j else f"{ids[i]}:{ids[j]}")
        i = j + 1
    return out


def component_names(coll, ob):
    """Maya names of ``ob``'s components in the set: ``pCube1.vtx[0:3]``, ``pCube1.e[4]``, ``pCube1.f[1]``, …"""
    comp = components(coll, ob)
    return [f"{ob.name}.{short}[{r}]" for domain, short, _seq in DOMAINS for r in _ranges(comp.get(domain, ()))]


def _write(coll, ob, comp, value):
    """Set the set's component flags of ``comp`` ({domain: indices}) on ``ob``'s mesh to ``value``; a layer left
    without any flag is removed. Returns True when ``ob`` still has components in the set."""
    me = ob.data
    bm = _bm(ob)
    left = False
    for domain, _short, seq_name in DOMAINS:
        name = layer_name(coll, domain)
        idx = list(comp.get(domain, ()))
        if bm is not None:
            seq = getattr(bm, seq_name)
            lay = seq.layers.bool.get(name)
            if lay is None:
                if not (value and idx):
                    continue
                lay = seq.layers.bool.new(name)
            seq.ensure_lookup_table()
            n = len(seq)
            for i in idx:
                if 0 <= i < n:
                    seq[i][lay] = value
            if any(e[lay] for e in seq):
                left = True
            else:
                seq.layers.bool.remove(lay)
            continue
        import numpy as np
        attr = me.attributes.get(name)
        if attr is not None and (attr.domain != domain or attr.data_type != 'BOOLEAN'):
            me.attributes.remove(attr)
            attr = None
        if attr is None:
            if not (value and idx):
                continue
            attr = me.attributes.new(name, 'BOOLEAN', domain)
        vals = np.zeros(len(attr.data), bool)
        attr.data.foreach_get("value", vals)
        idx = [i for i in idx if 0 <= i < len(vals)]
        vals[idx] = value
        if vals.any():
            attr.data.foreach_set("value", vals)
            left = True
        else:
            me.attributes.remove(attr)
    if bm is not None:
        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
    return left


def add_components(coll, ob, comp):
    """Add ``ob``'s components ``comp`` ({domain: indices}) to the set (Maya ``sets -add``)."""
    if ob.type != 'MESH' or not any(comp.values()):
        return
    _write(coll, ob, comp, True)
    child = _parts(coll, create_it=True)
    if ob.name not in child.objects:
        child.objects.link(ob)


def remove_components(coll, ob, comp=None):
    """Take ``ob``'s components ``comp`` (None: all of them) out of the set (Maya ``sets -remove``)."""
    child = _parts(coll)
    if child is None or ob.name not in child.objects:
        return
    if comp is None:
        comp = components(coll, ob)
    if ob.type != 'MESH' or not _write(coll, ob, comp, False):
        child.objects.unlink(ob)


def selected_components(ob, select_mode):
    """{domain: indices} of ``ob``'s selected components in Edit Mode, by the select mode (the tool settings' (vertex,
    edge, face) flags) like Maya's component types: vertex mode = the selected vertices, edge mode = edges, face
    mode = faces; with several modes on, a face counts once (not its edges and vertices) and an edge once (not its
    vertices)."""
    bm = _bm(ob)
    if bm is None:
        return {}
    vert_mode, edge_mode, face_mode = select_mode
    out = {}
    taken_e, taken_v = set(), set()
    if face_mode:
        faces = [f for f in bm.faces if f.select]
        if faces:
            out['FACE'] = [f.index for f in faces]
            taken_e = {e.index for f in faces for e in f.edges}
            taken_v = {v.index for f in faces for v in f.verts}
    if edge_mode:
        edges = [e for e in bm.edges if e.select and e.index not in taken_e]
        if edges:
            out['EDGE'] = [e.index for e in edges]
            taken_v |= {v.index for e in edges for v in e.verts}
    if vert_mode:
        verts = [v.index for v in bm.verts if v.select and v.index not in taken_v]
        if verts:
            out['POINT'] = verts
    return out


def gather(context):
    """(whole objects, {mesh: components}) a new set takes from the selection: in Edit Mode the selected components
    of the meshes being edited and the other selected objects, else the selected objects."""
    if context.mode == 'OBJECT':
        return list(context.selected_objects), {}
    if context.mode != 'EDIT_MESH':
        return [], {}
    editing = [ob for ob in context.objects_in_mode if ob.type == 'MESH']
    parts = {}
    select_mode = tuple(context.scene.tool_settings.mesh_select_mode)
    for ob in editing:
        comp = selected_components(ob, select_mode)
        if comp:
            parts[ob] = comp
    return [ob for ob in context.selected_objects if ob not in editing], parts


def _selectable(ob):
    try:
        ob.select_set(ob.select_get())
        return True
    except RuntimeError:       # not in the view layer
        return False


def select_members(context, coll, mode='REPLACE', only=None):
    """Maya ``cmds.select(set, replace / add / toggle=True)``: the members in the view layer; the last one becomes the
    lead. Component members are picked in Edit Mode (``only``: just that object's components)."""
    vl = context.view_layer
    obs = [ob for ob in members(coll, context.scene) if _selectable(ob)] if only is None else []
    parts = [(ob, comp) for ob in part_objects(coll, context.scene)
             if (only is None or ob == only) and ob.type == 'MESH' and _selectable(ob) and ob.visible_get()
             for comp in (components(coll, ob),) if comp]
    if parts:
        _select_components(context, obs, parts, mode)
        return obs + [ob for ob, _comp in parts]
    if context.mode != 'OBJECT' and context.active_object is not None:
        bpy.ops.object.mode_set(mode='OBJECT')
    if mode == 'REPLACE':
        for ob in context.selected_objects:
            ob.select_set(False)
    for ob in obs:
        ob.select_set(not ob.select_get() if mode == 'TOGGLE' else True)
    picked = [ob for ob in obs if ob.select_get()]
    if picked:
        vl.objects.active = picked[-1]
    return obs


_SELECT_MODE = {'POINT': 0, 'EDGE': 1, 'FACE': 2}


def _select_components(context, whole, parts, mode):
    """Edit Mode on the meshes of ``parts`` with their set components picked, in the component mode of those
    components (Blender picks components only in Edit Mode); the whole-object members are picked too, outside Edit
    Mode. Add / Toggle keep what was picked, components included."""
    vl = context.view_layer
    ts = context.scene.tool_settings
    was_edit = context.mode == 'EDIT_MESH'
    editing = [ob for ob in context.objects_in_mode if ob.type == 'MESH'] if was_edit else []
    picked = [ob for ob in context.selected_objects if ob not in editing]
    if context.mode != 'OBJECT' and context.active_object is not None:
        bpy.ops.object.mode_set(mode='OBJECT')
    targets = [ob for ob, _comp in parts]
    keep = [ob for ob in editing if ob not in targets] if mode != 'REPLACE' else []
    for ob in context.selected_objects:
        ob.select_set(False)
    for ob in targets + keep:
        ob.select_set(True)
    vl.objects.active = targets[-1]
    want = [False, False, False]
    for _ob, comp in parts:
        for domain in comp:
            want[_SELECT_MODE[domain]] = True
    if mode != 'REPLACE' and was_edit:
        want = [a or b for a, b in zip(want, ts.mesh_select_mode)]
    ts.mesh_select_mode = want
    bpy.ops.object.mode_set(mode='EDIT')
    from .uv_tools import leave_uv_mode
    leave_uv_mode(context)
    modes = {name for name, on in zip(('VERT', 'EDGE', 'FACE'), want) if on}
    for ob, comp in parts:
        bm = bmesh.from_edit_mesh(ob.data)
        bm.select_mode = modes          # Blender sets only the active mesh's mode from the tool settings
        if mode == 'REPLACE' or ob not in editing:      # a mesh not being edited had no components picked
            for seq in (bm.faces, bm.edges, bm.verts):
                for e in seq:
                    e.select_set(False)
            bm.select_history.clear()
        for domain, _short, seq_name in DOMAINS:
            idx = comp.get(domain)
            if not idx:
                continue
            seq = getattr(bm, seq_name)
            seq.ensure_lookup_table()
            for i in idx:
                if i < len(seq):
                    e = seq[i]
                    e.select_set(not e.select if mode == 'TOGGLE' else True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
    for ob in whole:
        ob.select_set(ob not in picked if mode == 'TOGGLE' else True)
    if mode != 'REPLACE':
        for ob in picked:
            if ob not in whole and ob not in targets:
                ob.select_set(True)
    vl.objects.active = targets[-1]


def add(coll, objects, parts=None):
    for ob in objects:
        if ob.name not in coll.objects:
            coll.objects.link(ob)
    for ob, comp in (parts or {}).items():
        add_components(coll, ob, comp)


def remove(coll, objects, parts=None):
    for ob in objects:
        if ob.name in coll.objects:
            coll.objects.unlink(ob)
    for ob, comp in (parts or {}).items():
        remove_components(coll, ob, comp)


def delete(coll):
    """Delete the set; its objects stay, the component attributes it put on their meshes go."""
    child = _parts(coll)
    if child is not None:
        for ob in list(child.objects):
            remove_components(coll, ob)
        bpy.data.collections.remove(child)
    bpy.data.collections.remove(coll)


# --- operators -----------------------------------------------------------------------------------

class ALLSET_OT_create_set(bpy.types.Operator):
    """New set holding the selected objects"""
    bl_idname = "allset.create_set"
    bl_label = "Set"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Name", description="Set name (empty: set1, set2, ...)", options={'SKIP_SAVE'})
    option_box: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        if self.option_box:   # Maya Create Set Options: the name
            self.name = self.name or next_name()
            return context.window_manager.invoke_props_dialog(self, title="Create Set Options", confirm_text="Create")
        return self.execute(context)

    def execute(self, context):
        whole, parts = gather(context)
        coll = create(self.name, whole, parts=parts)
        results.result(self, f"Result: {coll.name}")
        _refresh(context)
        return {'FINISHED'}


class ALLSET_OT_create_quick_select_set(bpy.types.Operator):
    """New set of the selected objects, also listed under Edit > Quick Select Sets"""
    bl_idname = "allset.create_quick_select_set"
    bl_label = "Create Quick Select Set"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Enter Quick Select Set name", default="Set")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, confirm_text="OK")

    def execute(self, context):
        whole, parts = gather(context)
        coll = create(self.name.strip() or "Set", whole, text=QUICK, parts=parts)
        results.result(self, f"Created Quick Select Set {coll.name}")
        _refresh(context)
        return {'FINISHED'}


class ALLSET_OT_select_set_members(bpy.types.Operator):
    """Select the members of the set (Maya: select <set>)"""
    bl_idname = "allset.select_set_members"
    bl_label = "Select Set Members"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(options={'SKIP_SAVE'})
    mode: EnumProperty(items=(('REPLACE', "Replace", ""), ('ADD', "Add", ""), ('TOGGLE', "Toggle", "")),
                       options={'SKIP_SAVE'})

    def execute(self, context):
        coll = get(self.name or context.window_manager.allset_set_target)
        if coll is None:
            return {'CANCELLED'}
        select_members(context, coll, self.mode)
        return {'FINISHED'}


class ALLSET_OT_set_edit(bpy.types.Operator):
    """Edit a set: add / remove the selected objects, rename, delete, show its members"""
    bl_idname = "allset.set_edit"
    bl_label = "Edit Set"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(options={'SKIP_SAVE'})
    member: StringProperty(options={'SKIP_SAVE'})
    action: EnumProperty(items=(('ADD', "Add Selected Objects", ""), ('REMOVE', "Remove Selected Objects", ""),
                                ('REMOVE_MEMBER', "Remove From Current Set", ""), ('DELETE', "Delete Set", ""),
                                ('RENAME', "Rename", ""), ('EXPAND', "Show Set Members", "")))
    new_name: StringProperty(name="Name", options={'SKIP_SAVE'})

    @classmethod
    @i18n.translated
    def description(cls, context, props):
        return {'ADD': "Add the selected objects to the set", 'REMOVE': "Remove the selected objects from the set",
                'REMOVE_MEMBER': "Remove this object from the set", 'DELETE': "Delete the set (its objects stay)",
                'RENAME': "Rename the set", 'EXPAND': "Show the set's members under it"}[props.action]

    def invoke(self, context, event):
        if self.action == 'RENAME':
            coll = get(self.name or context.window_manager.allset_set_target)
            if coll is None:
                return {'CANCELLED'}
            self.name, self.new_name = coll.name, coll.name
            return context.window_manager.invoke_props_dialog(self, title="Rename Set")
        return self.execute(context)

    def draw(self, context):
        self.layout.prop(self, "new_name")

    def execute(self, context):
        coll = get(self.name or context.window_manager.allset_set_target)
        if coll is None:
            return {'CANCELLED'}
        if self.action == 'ADD':
            add(coll, *gather(context))
        elif self.action == 'REMOVE':
            remove(coll, *gather(context))
        elif self.action == 'REMOVE_MEMBER':
            ob = bpy.data.objects.get(self.member or context.window_manager.allset_set_member)
            if ob is not None:
                remove(coll, [ob])
                remove_components(coll, ob)
        elif self.action == 'DELETE':
            delete(coll)
        elif self.action == 'RENAME':
            if self.new_name.strip():
                coll.name = self.new_name.strip()
        elif self.action == 'EXPAND':
            coll.allset_expanded = not coll.allset_expanded
        _refresh(context)
        return {'FINISHED'}


class ALLSET_MT_quick_select_sets(bpy.types.Menu):
    """Select > Quick Select Sets"""
    bl_label = "Quick Select Sets"
    bl_idname = "ALLSET_MT_quick_select_sets"

    def draw(self, context):
        layout = self.layout
        found = quick_sets()
        if not found:
            row = layout.row()
            row.enabled = False
            row.label(text="No Quick Select Sets")
            return
        for coll in found:
            layout.operator(ALLSET_OT_select_set_members.bl_idname, text=coll.name).name = coll.name


def _refresh(context):
    """Redraw the Outliners (the kit tree draws the set rows) and the 3D Views."""
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type in {'OUTLINER', 'VIEW_3D'}:
                area.tag_redraw()


classes = (ALLSET_OT_create_set, ALLSET_OT_create_quick_select_set, ALLSET_OT_select_set_members,
           ALLSET_OT_set_edit, ALLSET_MT_quick_select_sets)


def register_props():
    bpy.types.Collection.allset_expanded = BoolProperty(
        name="Expanded", description="Set expanded in the Maya Outliner (Show Set Members)", options={'HIDDEN'})
    wm = bpy.types.WindowManager
    wm.allset_set_target = StringProperty(options={'SKIP_SAVE', 'HIDDEN'})   # the set row under an RMB menu
    wm.allset_set_member = StringProperty(options={'SKIP_SAVE', 'HIDDEN'})


def unregister_props():
    del bpy.types.WindowManager.allset_set_member
    del bpy.types.WindowManager.allset_set_target
    del bpy.types.Collection.allset_expanded
