# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's middle-mouse node drag in the shader graph (the Hypershade Graph and every Shader Editor showing a
material): MMB-drag a node and drop it on another node = a list of the other node's inputs; the chosen one gets the
dragged node's default (first) output. Ctrl+MMB drop = the default connection without the list: the first free input
of the same kind as that output, else the first free input. Off a node the press passes on (Alt+MMB keeps panning
the view, as in Maya); a drop on empty space or on the node itself does nothing. The nodes and sockets are Blender's.
"""

import bpy
import gpu
from bpy.props import StringProperty
from gpu_extras.batch import batch_for_shader

from .. import results
from . import hypershade_hands as hands

_DRAG = {}          # area pointer -> ((x0, y0), (x1, y1)) region px of the drag line while a drag runs
_handles = []


def default_output(node):
    """The output a dropped node connects from: its first enabled output (Maya connects the dropped node's main
    output)."""
    return next((s for s in node.outputs if s.enabled), None)


def inputs_of(node):
    """The inputs the drop list offers: every enabled input of the target node, in the node's order."""
    return [s for s in node.inputs if s.enabled]


def default_input(node, output):
    """Ctrl+MMB drop: the first free input of the output's kind, else the first free input, else the first input."""
    ins = inputs_of(node)
    free = [s for s in ins if not s.is_linked]
    return next((s for s in free if s.type == output.type), None) or (free[0] if free else None) or (
        ins[0] if ins else None)


def connect(tree, src, dst, identifier):
    """Link ``src``'s default output to ``dst``'s input ``identifier``; the new link (None if impossible)."""
    out = default_output(src)
    inp = next((s for s in dst.inputs if s.identifier == identifier), None)
    if out is None or inp is None or src == dst:
        return None
    return tree.links.new(out, inp)


class ALLSET_OT_hs_connect(bpy.types.Operator):
    """Connect the dragged node's default output to this input (Maya middle-mouse drop)"""
    bl_idname = "allset.hs_connect"
    bl_label = "Connect"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    source: StringProperty(options={'SKIP_SAVE'})
    target: StringProperty(options={'SKIP_SAVE'})
    socket: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        space = hands.shader_space(context)
        if space is None:
            return {'CANCELLED'}
        tree = space.edit_tree
        src, dst = tree.nodes.get(self.source), tree.nodes.get(self.target)
        if src is None or dst is None:
            return {'CANCELLED'}
        link = connect(tree, src, dst, self.socket)
        if link is None:
            return {'CANCELLED'}
        results.result(self, f"{src.name}.{link.from_socket.name} -> {dst.name}.{link.to_socket.name}")
        return {'FINISHED'}


class ALLSET_OT_hs_mmb_drag(bpy.types.Operator):
    """Middle-mouse drag a node onto another to connect them (Maya)"""
    bl_idname = "allset.hs_mmb_drag"
    bl_label = "Drag Node to Connect"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        node = hands.pick(context, event)
        if node is None or node.type == 'FRAME':
            return {'PASS_THROUGH'}         # empty graph, other node trees: the keys behind this one
        self.source = node.name
        self.ctrl = event.ctrl
        self.start = (event.mouse_region_x, event.mouse_region_y)
        self.area = context.area.as_pointer()
        _DRAG[self.area] = (self.start, self.start)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _end(self, context):
        _DRAG.pop(self.area, None)
        if context.area is not None:
            context.area.tag_redraw()

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            _DRAG[self.area] = (self.start, (event.mouse_region_x, event.mouse_region_y))
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._end(context)
            return {'CANCELLED'}
        if event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
            self._end(context)
            self.drop(context, event)
            return {'FINISHED'}
        return {'RUNNING_MODAL'}

    def drop(self, context, event):
        space = hands.shader_space(context)
        if space is None:
            return
        tree = space.edit_tree
        src = tree.nodes.get(self.source)
        dst = hands.pick(context, event)
        if src is None or dst is None or dst == src or dst.type == 'FRAME':
            return
        out = default_output(src)
        if out is None:
            self.report({'WARNING'}, f"{src.name} has no output")
            return
        if self.ctrl or event.ctrl:
            inp = default_input(dst, out)
            if inp is not None:
                bpy.ops.allset.hs_connect(source=src.name, target=dst.name, socket=inp.identifier)
            return
        source, target = src.name, dst.name
        rows = [(s.identifier, s.name, s.is_linked) for s in inputs_of(dst)]

        def draw(menu, _context):
            layout = menu.layout
            for identifier, name, linked in rows:
                op = layout.operator(ALLSET_OT_hs_connect.bl_idname, text=name,
                                     icon='LINKED' if linked else 'NONE')
                op.source, op.target, op.socket = source, target, identifier

        context.window_manager.popup_menu(draw, title=f"{source} -> {target}")


def _draw_line():
    area = bpy.context.area
    seg = _DRAG.get(area.as_pointer()) if area is not None else None
    if seg is None or seg[0] == seg[1]:
        return
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'LINES', {"pos": list(seg)})
    gpu.state.line_width_set(2.0)
    shader.uniform_float("color", (1.0, 0.85, 0.1, 1.0))
    batch.draw(shader)
    gpu.state.line_width_set(1.0)


classes = (ALLSET_OT_hs_connect, ALLSET_OT_hs_mmb_drag)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    _handles.append(bpy.types.SpaceNodeEditor.draw_handler_add(_draw_line, (), 'WINDOW', 'POST_PIXEL'))


def unregister():
    while _handles:
        bpy.types.SpaceNodeEditor.draw_handler_remove(_handles.pop(), 'WINDOW')
    _DRAG.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
