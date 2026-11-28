# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya hands in the shader graph (the Hypershade Graph and every Shader Editor showing a material):

- ``allset.hs_tab_create``: Tab = Maya's create-node field. Type a node name, Enter: the node is made where the
  mouse was, selected, nothing hangs on the mouse. Lists Blender's shader nodes (Blender names) and the Maya
  texture / utility nodes the kit builds (Maya names).
- ``node_at`` / ``pick``: the node under the mouse, for the RMB marking menus (``marking.resolve``: empty graph,
  material, texture, utility or output node menus) and ``allset.hs_node_cmd``, the commands those menus run on it.
- ``allset.hs_view_mode``: keys 1 / 2 / 3 / 4 = Maya's view modes (attributes hidden / connected ones / all).

Other node trees (Geometry Nodes, compositor) keep Blender's keys: the operators pass the event through there.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty, StringProperty

from .. import results

_N = "ShaderNode"
# what the RMB menus treat as Maya's node kinds
MENU_EMPTY, MENU_MATERIAL, MENU_TEXTURE, MENU_UTILITY, MENU_OUTPUT = (
    "NODE_EMPTY", "NODE_MATERIAL", "NODE_TEXTURE", "NODE_UTILITY", "NODE_OUTPUT")
# vector / placement nodes: Maya's place2dTexture menu (the texture menu without the file rows)
_PLACEMENT = {_N + n for n in ("Mapping", "TexCoord", "UVMap")}


def shader_space(context):
    """The Shader Editor space of ``context`` showing a material tree, or None."""
    space = getattr(context, "space_data", None)
    if space is None or space.type != 'NODE_EDITOR' or space.tree_type != 'ShaderNodeTree':
        return None
    if getattr(space, "shader_type", 'OBJECT') != 'OBJECT' or space.edit_tree is None:
        return None
    return space


def _scale():
    system = bpy.context.preferences.system
    return (system.dpi or 72) / 72.0


def _absolute(node):
    loc = getattr(node, "location_absolute", None)
    if loc is not None:
        return loc.x, loc.y
    x, y = node.location
    parent = node.parent
    while parent is not None:
        x, y = x + parent.location.x, y + parent.location.y
        parent = parent.parent
    return x, y


def node_rect(node):
    """(left, bottom, right, top) of ``node`` in view coordinates (0 size before Blender drew it)."""
    x, y = _absolute(node)
    w, h = node.dimensions.x / _scale(), node.dimensions.y / _scale()
    return x, y - h, x + w, y


def node_at(tree, x, y):
    """The node drawn at view point (x, y): the topmost one (Blender draws the node list in order, selected last);
    frames only when no other node is there."""
    hits = []
    for i, node in enumerate(tree.nodes):
        left, bottom, right, top = node_rect(node)
        if left <= x <= right and bottom <= y <= top:
            hits.append((node.type != 'FRAME', node.select, i, node))
    if not hits:
        return None
    return max(hits, key=lambda h: h[:3])[3]


def view_point(context, event):
    region = context.region
    return region.view2d.region_to_view(event.mouse_region_x, event.mouse_region_y)


def pick(context, event):
    """The node under the mouse in a material's Shader Editor, or None."""
    space = shader_space(context)
    if space is None or context.region is None or context.region.type != 'WINDOW':
        return None
    x, y = view_point(context, event)
    return node_at(space.edit_tree, x, y)


def menu_kind(node):
    """Which Maya RMB marking menu a node gets."""
    if node is None:
        return MENU_EMPTY
    idname = node.bl_idname
    if idname == _N + "OutputMaterial":
        return MENU_OUTPUT                      # Maya's shading group
    if idname.startswith(_N + "Tex"):
        return MENU_TEXTURE
    if idname in _PLACEMENT:
        return MENU_UTILITY
    if any(s.type == 'SHADER' for s in node.outputs):
        return MENU_MATERIAL
    return MENU_UTILITY


def picked(context):
    """The node the open RMB menu was made for (by name in the current graph), or None."""
    space = shader_space(context)
    name = getattr(context.window_manager, "allset_mm_node", "")
    if space is None or not name:
        return None
    return space.edit_tree.nodes.get(name)


# ---------------------------------------------------------------------------------------------------- Tab field

_items_keep = []


def _tab_items(_self, _context):
    """Every node Tab can make: Blender's shader nodes by Blender name, then the kit's Maya nodes by Maya name."""
    if _items_keep:
        return _items_keep
    from . import hypershade_blender, editor_menu_map
    out, seen = [], set()
    for idname, label in hypershade_blender.items("BLENDER"):
        key = "BL|" + idname
        out.append((key, label, f"Blender node {label}"))
        seen.add(key)
    for path, action in sorted(editor_menu_map.MAP.items()):
        if not path.startswith(f"{editor_menu_map.HS}/Create/") or not isinstance(action, tuple):
            continue
        if action[0] != "allset.hs_node":
            continue
        props = action[1]
        label = props.get("label") or path.rsplit("/", 1)[-1]
        key = "MY|" + "|".join((props["node_type"], props.get("operation", ""), label))
        if key in seen:
            continue
        seen.add(key)
        out.append((key, label, f"Maya {label} (Blender {props['node_type'][len(_N):]})"))
    out.sort(key=lambda it: it[1].lower())
    _items_keep.extend(out)
    return _items_keep


def make_node(tree, key, location):
    """Add the node ``key`` (a Tab item) to ``tree`` with its top-left corner at ``location``; it becomes the only
    selected node and the active one. Returns it."""
    kind, rest = key.split("|", 1)
    label, operation = "", ""
    if kind == "MY":
        idname, operation, label = rest.split("|", 2)
    else:
        idname = rest
    node = tree.nodes.new(idname)
    if label:
        node.label = label
    if operation and hasattr(node, "operation"):
        node.operation = operation
    node.location = location
    for n in tree.nodes:
        n.select = n == node
    tree.nodes.active = node
    return node


class ALLSET_OT_hs_tab_create(bpy.types.Operator):
    """Create a node: type its name (Maya's Tab field in the Hypershade / Node Editor)"""
    bl_idname = "allset.hs_tab_create"
    bl_label = "Create Node"
    bl_options = {'UNDO'}
    bl_property = "node"

    node: EnumProperty(name="Node", items=_tab_items)
    location: FloatVectorProperty(size=2, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        if shader_space(context) is None or context.region is None or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        self.location = view_point(context, event)
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        space = shader_space(context)
        if space is None:
            return {'CANCELLED'}
        try:
            node = make_node(space.edit_tree, self.node, tuple(self.location))
        except (RuntimeError, ValueError, KeyError):
            self.report({'ERROR'}, "Blender can't make that node")
            return {'CANCELLED'}
        results.result(self, f"Created {node.label or node.name}")
        return {'FINISHED'}


# ---------------------------------------------------------------------------------------------------- view modes

def set_view_mode(nodes, mode):
    """Maya's node view modes on ``nodes``: SIMPLE = attributes hidden (collapsed), CONNECTED = only connected
    attributes, ALL = every attribute."""
    for node in nodes:
        node.hide = mode == 'SIMPLE'
        for sock in (*node.inputs, *node.outputs):
            if mode == 'CONNECTED':
                sock.hide = not sock.is_linked
            elif mode == 'ALL':
                sock.hide = False


class ALLSET_OT_hs_view_mode(bpy.types.Operator):
    """Maya's node view mode (keys 1 / 2 / 3 / 4) for the selected nodes, or every node when none is selected"""
    bl_idname = "allset.hs_view_mode"
    bl_label = "Node View Mode"
    bl_options = {'UNDO'}

    mode: EnumProperty(items=(("SIMPLE", "Hide Attributes", "Collapse the nodes"),
                              ("CONNECTED", "Show Connected Attributes", "Show only connected sockets"),
                              ("ALL", "Show All Attributes", "Show every socket")), name="Mode")

    def invoke(self, context, event):
        if shader_space(context) is None:
            return {'PASS_THROUGH'}
        return self.execute(context)

    def execute(self, context):
        space = shader_space(context)
        if space is None:
            return {'CANCELLED'}
        tree = space.edit_tree
        nodes = [n for n in tree.nodes if n.select] or list(tree.nodes)
        set_view_mode(nodes, self.mode)
        if context.area is not None:
            context.area.tag_redraw()
        return {'FINISHED'}


# ---------------------------------------------------------------------------------------------------- node commands

def _upstream(tree, node):
    from .hypershade_graph import _linked
    return _linked(tree, [node], True)


def _downstream(tree, node):
    from .hypershade_graph import _linked
    return _linked(tree, [node], False)


def _material(context):
    from .hypershade_materials import current
    space = shader_space(context)
    if space is not None and space.id is not None and isinstance(space.id, bpy.types.Object):
        mat = space.id.active_material
        if mat is not None and mat.node_tree == space.edit_tree:
            return mat
    mat = current(context)
    if mat is None and space is not None:
        mat = next((m for m in bpy.data.materials if m.node_tree == space.edit_tree), None)
    return mat


class ALLSET_OT_hs_node_cmd(bpy.types.Operator):
    """Maya graph marking menu command on the node the menu was opened over"""
    bl_idname = "allset.hs_node_cmd"
    bl_label = "Hypershade Node Command"
    bl_options = {'UNDO'}

    action: EnumProperty(items=(
        ("ASSIGN", "Assign Material To Viewport Selection", "Assign this material to the selected objects or faces"),
        ("SELECT_OBJECTS", "Select Objects with Material", "Select the objects that use this material"),
        ("FRAME_OBJECTS", "Frame Objects with Material", "Select and frame the objects that use this material"),
        ("REFRESH", "Refresh Swatch", "Render this material's preview again"),
        ("RENAME", "Rename", "Rename the node"),
        ("SWATCH", "Toggle Swatch Size", "Show / hide the node's preview"),
        ("SELECT_SWATCH", "Toggle Selection Swatch Size", "Show / hide the selected nodes' previews"),
        ("SHOW_ALL", "Show All Attributes", "Show every socket of the node"),
        ("SELECT_INPUTS", "Select All Inputs", "Select the nodes feeding this one"),
        ("SELECT_OUTPUTS", "Select All Outputs", "Select the nodes this one feeds"),
        ("SELECT_NODE", "Select", "Select one node"),
        ("RELOAD", "Reload Image File", "Read the image file again"),
        ("EDIT_TEXTURE", "Edit Texture", "Open the image in the image editor set in the Preferences"),
        ("STREAM_BOTH", "Select Upstream and Downstream", "Select the node's whole network"),
        ("STREAM_UP", "Select Upstream", "Select the nodes feeding this one and it"),
        ("STREAM_DOWN", "Select Downstream", "Select the nodes this one feeds and it"),
        ("GRAPH_BOTH", "Regraph Upstream and Downstream", "Select and frame the node's whole network"),
        ("GRAPH_UP", "Regraph Upstream", "Select and frame the nodes feeding this one"),
        ("GRAPH_DOWN", "Regraph Downstream", "Select and frame the nodes this one feeds"),
        ("ALL_INPUTS_SELECT", "Select All Inputs", "Select the node and every node feeding it"),
        ("ALL_INPUTS_ENABLE", "Enable All Inputs", "Unmute the node and every node feeding it"),
        ("ALL_INPUTS_DISABLE", "Disable All Inputs", "Mute the node and every node feeding it"),
        ("ALL_OUTPUTS_SELECT", "Select All Outputs", "Select the node and every node it feeds"),
        ("ALL_OUTPUTS_ENABLE", "Enable All Outputs", "Unmute the node and every node it feeds"),
        ("ALL_OUTPUTS_DISABLE", "Disable All Outputs", "Mute the node and every node it feeds"),
        ("HELP", "Help", "Open Blender's manual page for this node"),
    ), name="Action", options={'SKIP_SAVE'})
    node: StringProperty(name="Node", options={'SKIP_SAVE'})
    selected: BoolProperty(name="Selected Nodes", description="Act on the selected nodes (a key), not the node "
                           "under the marking menu", options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if shader_space(context) is None:
            return {'PASS_THROUGH'}          # other node trees keep Blender's keys
        return self.execute(context)

    def execute(self, context):
        space = shader_space(context)
        if space is None:
            return {'CANCELLED'}
        tree = space.edit_tree
        if self.selected:
            node = None
        else:
            node = tree.nodes.get(self.node) if self.node else picked(context)
        act = self.action
        if act == "SELECT_SWATCH" and node is None:
            chosen = [n for n in tree.nodes if n.select]
            if chosen:
                show = not chosen[0].show_preview
                for n in chosen:
                    n.show_preview = show
            return {'FINISHED'}
        if act.startswith("ALL_") and node is not None:
            group = _upstream(tree, node) if "INPUTS" in act else _downstream(tree, node)
            group.add(node)
            if act.endswith("SELECT"):
                for n in tree.nodes:
                    n.select = n in group
                tree.nodes.active = node
            else:
                for n in group:
                    if n.bl_idname != _N + "OutputMaterial":
                        n.mute = act.endswith("DISABLE")
            return {'FINISHED'}
        if act == "HELP" and node is not None:
            try:
                return bpy.ops.wm.doc_view_manual(doc_id=f"bpy.types.{node.bl_idname}")
            except RuntimeError:
                self.report({'WARNING'}, "No manual page for this node")
                return {'CANCELLED'}
        if act in {"GRAPH_BOTH", "GRAPH_UP", "GRAPH_DOWN"}:
            if node is not None:  # else the selected nodes
                for n in tree.nodes:
                    n.select = n == node
                tree.nodes.active = node
            action = {"GRAPH_BOTH": "BOTH", "GRAPH_UP": "UPSTREAM", "GRAPH_DOWN": "DOWNSTREAM"}[act]
            return bpy.ops.allset.hs_graph(action=action)
        if act in {"STREAM_BOTH", "STREAM_UP", "STREAM_DOWN"} and node is None:
            start = [n for n in tree.nodes if n.select] or ([tree.nodes.active] if tree.nodes.active else [])
        elif node is None:
            self.report({'WARNING'}, "No node under the menu")
            return {'CANCELLED'}
        else:
            start = [node]
        if act in {"ASSIGN", "SELECT_OBJECTS", "FRAME_OBJECTS", "REFRESH"}:
            mat = _material(context)
            if mat is None:
                self.report({'WARNING'}, "No material in the graph")
                return {'CANCELLED'}
            if act == "ASSIGN":
                return bpy.ops.allset.assign_material(material=mat.name)
            if act == "REFRESH":
                mat.preview_ensure()
                mat.update_tag()
                return {'FINISHED'}
            hits = [o for o in context.view_layer.objects if any(s.material == mat for s in o.material_slots)]
            for o in context.view_layer.objects:
                o.select_set(o in hits)
            if hits:
                context.view_layer.objects.active = hits[0]
            if act == "FRAME_OBJECTS" and hits:
                _frame_in_views(context)
            return {'FINISHED'}
        if act == "RENAME":
            for n in tree.nodes:
                n.select = n == node
            tree.nodes.active = node
            return bpy.ops.wm.call_panel('INVOKE_DEFAULT', name="TOPBAR_PT_name", keep_open=False)
        if act in {"SWATCH", "SHOW_ALL"}:
            if act == "SWATCH":
                node.show_preview = not node.show_preview
            else:
                set_view_mode([node], 'ALL')
            return {'FINISHED'}
        if act == "SELECT_SWATCH":
            chosen = [n for n in tree.nodes if n.select] or [node]
            show = not chosen[0].show_preview
            for n in chosen:
                n.show_preview = show
            return {'FINISHED'}
        if act in {"RELOAD", "EDIT_TEXTURE"}:
            image = getattr(node, "image", None)
            if image is None:
                self.report({'WARNING'}, "The node has no image")
                return {'CANCELLED'}
            if act == "RELOAD":
                image.reload()
                return {'FINISHED'}
            try:
                return bpy.ops.image.external_edit(filepath=bpy.path.abspath(image.filepath))
            except RuntimeError as exc:
                self.report({'WARNING'}, str(exc).splitlines()[-1])
                return {'CANCELLED'}
        keep = set(start)
        if act == "SELECT_NODE":
            pass
        elif act == "SELECT_INPUTS":
            keep = _upstream(tree, node)
        elif act == "SELECT_OUTPUTS":
            keep = _downstream(tree, node)
        else:
            from .hypershade_graph import _linked
            if act != "STREAM_DOWN":
                keep |= _linked(tree, start, True)
            if act != "STREAM_UP":
                keep |= _linked(tree, start, False)
        for n in tree.nodes:
            n.select = n in keep
        if keep:
            tree.nodes.active = node if node in keep else next(iter(keep))
        if context.area is not None:
            context.area.tag_redraw()
        return {'FINISHED'}


def _frame_in_views(context):
    """Frame the selected objects in every 3D View of the window (Maya frames them in the viewport)."""
    window = context.window
    for area in window.screen.areas if window else ():
        if area.type != 'VIEW_3D':
            continue
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None:
            continue
        with context.temp_override(window=window, area=area, region=region):
            try:
                bpy.ops.view3d.view_selected()
            except RuntimeError:
                pass


def inputs_outputs(tree, node):
    """{"inputs": [(label, node name)], "outputs": [...]} = the node itself, then the nodes feeding / fed by it (Maya's
    Inputs / Outputs submenus list them by their type's name, the node first)."""
    def label(n):
        return n.label or n.bl_rna.name
    ins = [node] + sorted(_upstream(tree, node) - {node}, key=lambda n: n.name)
    outs = [node] + sorted(_downstream(tree, node) - {node}, key=lambda n: n.name)
    return {"inputs": [(label(n), n.name) for n in ins], "outputs": [(label(n), n.name) for n in outs]}


def fill_menu(menu, context):
    """A copy of graph marking menu ``menu`` for the node under it: its name in the title row, its type in the Help
    row, its connected nodes in Inputs / Outputs."""
    from ..marking import menus as mm
    space = shader_space(context)
    node = picked(context)
    if node is None or space is None:
        return menu
    lists = inputs_outputs(space.edit_tree, node)

    def node_sub(kind):
        word = "Inputs" if kind == "GRAPH_INPUTS" else "Outputs"
        key = "INPUTS" if kind == "GRAPH_INPUTS" else "OUTPUTS"
        rows = [(label, ("allset.hs_node_cmd", {"action": "SELECT_NODE", "node": name}))
                for label, name in lists["inputs" if key == "INPUTS" else "outputs"]]
        return mm.Sub(items=[(f"Select All {word}", ("allset.hs_node_cmd", {"action": f"ALL_{key}_SELECT"})),
                             (f"Enable All {word}", ("allset.hs_node_cmd", {"action": f"ALL_{key}_ENABLE"})),
                             (f"Disable All {word}", ("allset.hs_node_cmd", {"action": f"ALL_{key}_DISABLE"})),
                             mm.DIVIDER, *rows])

    items = []
    for e in menu.items:
        if e == mm.DIVIDER:
            items.append(e)
        elif e[0] == mm.NODE_TITLE:
            items.append((f"{node.name}...", e[1]))
        elif e[0] == mm.NODE_HELP:
            items.append((f'Help on "{node.bl_rna.name}"', e[1]))
        elif isinstance(e[1], mm.GraphNodes):
            items.append((e[0], node_sub(e[1].kind)))
        else:
            items.append(e)
    return mm.MarkingMenu(menu.name, menu.label, menu.source, menu.radial, items, menu.options)


classes = (ALLSET_OT_hs_tab_create, ALLSET_OT_hs_view_mode, ALLSET_OT_hs_node_cmd)


def register():
    bpy.types.WindowManager.allset_mm_node = StringProperty(
        name="Marking Menu Node", options={'SKIP_SAVE'},
        description="The graph node the open RMB marking menu acts on")
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.WindowManager.allset_mm_node
    _items_keep.clear()
