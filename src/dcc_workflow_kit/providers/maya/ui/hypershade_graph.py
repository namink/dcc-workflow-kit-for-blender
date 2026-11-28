# SPDX-License-Identifier: GPL-3.0-or-later
"""The Hypershade Graph and the Shader Editor headers: ``allset.hs_graph`` (graph toolbar: input / output
connections, framing, collapse, swatches), ``_node_header`` (Maya's menu bar on the menu strip and the graph
toolbar on the Graph in place of Blender's header), the drawn "Untitled_1" tab (``draw_graph_tab``) and Maya's
Hypershade menus in other Shader Editors (``draw_collapsible``, ``patch_header`` / ``unpatch_header``).
"""

import bpy
from bpy.props import EnumProperty

from . import own_draw
from .hypershade_window import HS, graph_area, is_hypershade, menu_area


# --- Graph: toolbar actions ------------------------------------------------------------------------------------

def _linked(tree, nodes, upstream):
    """Nodes reachable from ``nodes`` against (upstream) or along (downstream) the links."""
    found = set()
    todo = list(nodes)
    while todo:
        n = todo.pop()
        for link in tree.links:
            a, b = (link.to_node, link.from_node) if upstream else (link.from_node, link.to_node)
            if a == n and b not in found:
                found.add(b)
                todo.append(b)
    return found


class ALLSET_OT_hs_graph(bpy.types.Operator):
    """Maya Hypershade graph command, run in the Hypershade's graph (Shader Editor)"""
    bl_idname = "allset.hs_graph"
    bl_label = "Hypershade Graph"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(
        ("UPSTREAM", "Input Connections", "Select and frame the selected nodes' input network"),
        ("BOTH", "Input and Output Connections", "Select and frame the selected nodes' whole network"),
        ("DOWNSTREAM", "Output Connections", "Select and frame the nodes the selected ones feed"),
        ("FRAME_ALL", "Frame All", "Frame the whole graph"),
        ("FRAME_SELECTED", "Frame Selected", "Frame the selected nodes"),
        ("COLLAPSE", "Hide Attributes", "Collapse the selected nodes (Blender: Node > Collapse)"),
        ("CONNECTED", "Show Connected Attributes", "Hide the unconnected sockets of the selected nodes"),
        ("SHOW_ALL", "Show Primary Attributes", "Expand the selected nodes and show all their sockets"),
        ("PREVIEW", "Toggle Swatch Size", "Show / hide the selected nodes' preview swatch"),
    ), name="Action", options={'SKIP_SAVE'})

    def execute(self, context):
        area = context.area if context.area is not None and context.area.type == 'NODE_EDITOR' else None
        area = area or graph_area(context.screen)
        if area is None:
            self.report({'WARNING'}, "Open the Hypershade (Windows > Rendering Editors > Hypershade)")
            return {'CANCELLED'}
        space = area.spaces.active
        tree = space.edit_tree
        if tree is None:
            self.report({'WARNING'}, "No material in the graph")
            return {'CANCELLED'}
        act = self.action
        selected = [n for n in tree.nodes if n.select]
        if act in {"UPSTREAM", "BOTH", "DOWNSTREAM"}:
            start = selected or ([tree.nodes.active] if tree.nodes.active else list(tree.nodes))
            keep = set(start)
            if act != "DOWNSTREAM":
                keep |= _linked(tree, start, True)
            if act != "UPSTREAM":
                keep |= _linked(tree, start, False)
            for n in tree.nodes:
                n.select = n in keep
            act = "FRAME_SELECTED"
        elif act == "SHOW_ALL":
            for n in selected:
                n.hide = False
                for sock in (*n.inputs, *n.outputs):
                    sock.hide = False
            area.tag_redraw()
            return {'FINISHED'}
        ops = {"FRAME_ALL": bpy.ops.node.view_all, "FRAME_SELECTED": bpy.ops.node.view_selected,
               "COLLAPSE": bpy.ops.node.hide_toggle, "CONNECTED": bpy.ops.node.hide_socket_toggle,
               "PREVIEW": bpy.ops.node.preview_toggle}
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if bpy.app.background or region is None:
            return {'FINISHED'}            # selection done; view ops need a drawn region
        with context.temp_override(area=area, region=region, space_data=space):
            ops[act]()
        area.tag_redraw()
        return {'FINISHED'}


# --- headers: menu strip and Graph -----------------------------------------------------------------------------

@own_draw.kit_draw("NODE_HT_header")
def _node_header(self, context):
    """``NODE_HT_header``'s own draw while the kit is on: in a Hypershade window the menu strip shows Maya's menu
    bar, the Graph Maya's graph toolbar; elsewhere Blender's header."""
    from . import editor_chrome, editor_menu_data, menu_sets, own_draw
    area = context.area
    screen = context.screen
    if editor_chrome.enabled(context) and area is not None and is_hypershade(screen):
        layout = self.layout
        if area == menu_area(screen):
            row = layout.row(align=True)
            for i, (title, _items) in enumerate(editor_menu_data.EDITORS[HS]):
                row.menu(menu_sets.editor_menu_idname(HS, i), text=title)
            return
        if area == graph_area(screen):
            editor_chrome.draw_icons(layout, context, HS)
            layout.separator_spacer()
            layout.menu(editor_chrome._BLENDER[HS].bl_idname, text="Blender")
            layout.prop(context.space_data, "pin", text="", emboss=False)
            return
    return own_draw.original("NODE_HT_header", _node_header)(self, context)


TAB_TEXT = "Untitled_1"
TAB_BACK = (68 / 255, 68 / 255, 68 / 255, 1.0)     # Maya's current tab #444444
TAB_STRIP = (55 / 255, 55 / 255, 55 / 255, 1.0)    # tab row #373737
TAB_INK = (0.78, 0.78, 0.78, 1.0)


def draw_graph_tab():
    """Maya's graph tab row ("Untitled_1") over the top of the Hypershade Graph (node editors have no tool header
    region to hold a tab row)."""
    context = bpy.context
    area = context.area
    if area is None or area.type != 'NODE_EDITOR' or graph_area(context.screen) != area:
        return
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader
    region = context.region
    s = context.preferences.system.ui_scale or 1.0
    h = round(20 * s)
    top = region.height
    font = 0
    blf.size(font, 11 * s)
    tw = blf.dimensions(font, TAB_TEXT)[0]
    w = round(tw + 34 * s)
    x0 = round(6 * s)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')

    def rect(x, y, rw, rh, color):
        batch = batch_for_shader(shader, 'TRIS', {"pos": ((x, y), (x + rw, y), (x + rw, y + rh), (x, y + rh))},
                                 indices=((0, 1, 2), (0, 2, 3)))
        shader.uniform_float("color", color)
        batch.draw(shader)
    gpu.state.blend_set('ALPHA')
    rect(0, top - h, region.width, h, TAB_STRIP)
    rect(x0, top - h, w, h, TAB_BACK)
    blf.color(font, *TAB_INK)
    blf.position(font, x0 + 8 * s, top - h + 6 * s, 0)
    blf.draw(font, TAB_TEXT)
    blf.position(font, x0 + w - 14 * s, top - h + 6 * s, 0)
    blf.draw(font, "×")
    blf.position(font, x0 + w + 12 * s, top - h + 6 * s, 0)
    blf.draw(font, "+")
    gpu.state.blend_set('NONE')


# --- Maya menu bar in other Shader Editor headers ---------------------------------------------------------------

def draw_collapsible(cls, context, layout):
    """``NODE_MT_editor_menus.draw_collapsible`` while the kit is on: Maya's Hypershade menus in a Shader Editor."""
    from . import editor_chrome
    space = context.space_data
    if editor_chrome.enabled(context) and getattr(space, "tree_type", "") == 'ShaderNodeTree':
        return editor_chrome.draw_menus(layout, context, "Hypershade")
    return bpy.types.Menu.draw_collapsible.__func__(cls, context, layout)


def patch_header():
    bpy.types.NODE_MT_editor_menus.draw_collapsible = classmethod(draw_collapsible)


def unpatch_header():
    cls = bpy.types.NODE_MT_editor_menus
    if "draw_collapsible" in cls.__dict__:
        del cls.draw_collapsible
