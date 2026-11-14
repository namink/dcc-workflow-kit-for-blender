# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya's Universal Manipulator as a 3D View tool (Ctrl+T, Modify > Transformation Tools > Universal Manipulator).

Object Mode: a box around the selection with light blue corner boxes (scale), an axis-coloured arrow pair at the
middle of each edge (rotate about that edge), move arrows and a circle at the centre, and the box's length beside
one edge of each axis (click it to type a length). Handles on the far side of the box (the corner farthest from
the view and its three edges) are not drawn, like Maya. The drags are operators/universal_manip.py.
Component modes keep Blender's Transform tool.
"""

import bpy
from bpy.types import Gizmo, GizmoGroup
from mathutils import Matrix, Vector

from . import manipulator as mp
from ..operators import universal_manip as um

GROUP = "ALLSET_GGT_universal_manip"
HANDLE = "ALLSET_GT_um_handle"
BOX = "ALLSET_GT_um_box"
LABEL = "ALLSET_GT_um_label"

CORNER_HALF = 0.04        # corner boxes, in manipulator arrow units (manipulator.ARROW_PX)
ROT_HALF = 0.11           # rotate arrow pair: half length
ROT_CONE_LEN, ROT_CONE_R = 0.05, 0.025
MOVE_SCALE = 0.55         # centre move arrows: this part of the Move tool's arrows
CIRCLE_R = 0.07
BOX_COLOUR = (0.85, 0.85, 0.85)
LABEL_COLOUR = (1.0, 1.0, 1.0)
LABEL_PX = 12             # text size at UI scale 1
LABEL_GAP = 16            # px between the edge and its number (clear of the edge arrows)
FIELD = (0.1, 0.1, 0.1, 0.85)           # a length being typed
FIELD_SELECTED = (0.2, 0.35, 0.6, 0.9)  # ... while the shown length is still selected (the first key replaces it)


def shapes(kind):
    """(draw shapes, pick shape) of a handle, in arrow units."""
    if kind == 'CORNER':
        return [('TRIS', mp._box((0, 0, 0), CORNER_HALF))], ('TRIS', mp._box((0, 0, 0), CORNER_HALF * 1.8))
    if kind == 'ROTATE':
        base = ROT_HALF - ROT_CONE_LEN
        up = mp._cone(base, ROT_HALF, ROT_CONE_R)
        down = [(x, y, -z) for x, y, z in up]
        line = [(0, 0, -base), (0, 0, base)]
        return ([('LINES', line), ('TRIS', up + down)],
                ('TRIS', mp._bar(-ROT_HALF, ROT_HALF, ROT_CONE_R * 1.6)))
    if kind == 'CIRCLE':
        return [('LINES', mp._ring(CIRCLE_R, 32))], ('TRIS', mp._disc(CIRCLE_R * 1.3, 24))
    if kind == 'ARROW':
        return mp.shapes('ARROW')
    raise ValueError(kind)


# A Universal Manipulator handle: custom shape, picked with a fatter invisible one.
class ALLSET_GT_um_handle(Gizmo):
    bl_idname = HANDLE

    __slots__ = ("draw_shapes", "pick_shape", "handle_kind", "handle_role", "handle_index")

    def build(self, kind):
        self.handle_kind = kind
        draw, pick = shapes(kind)
        self.draw_shapes = [self.new_custom_shape(t, v) for t, v in draw]
        self.pick_shape = self.new_custom_shape(*pick)

    def draw(self, context):
        for sh in getattr(self, "draw_shapes", ()):
            self.draw_custom_shape(sh)

    def draw_select(self, context, select_id):
        sh = getattr(self, "pick_shape", None)
        if sh is not None:
            self.draw_custom_shape(sh, select_id=select_id)


def _edge_points(frame, lo, hi):
    out = []
    for e in range(12):
        axis, _sides = um.edge_spec(e)
        mid = um.edge_mid(lo, hi, e)
        a, b = mid.copy(), mid.copy()
        a[axis], b[axis] = lo[axis], hi[axis]
        out += [tuple(frame @ a), tuple(frame @ b)]
    return out


# The box outline (drawn only, never picked).
class ALLSET_GT_um_box(Gizmo):
    bl_idname = BOX

    __slots__ = ("lines",)

    def draw(self, context):
        import gpu
        from gpu_extras.batch import batch_for_shader
        pts = getattr(self, "lines", None)
        if not pts:
            return
        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
        shader.uniform_float("lineWidth", 1.0 * context.preferences.system.ui_scale)
        shader.uniform_float("color", (*self.color[:3], self.alpha))
        batch_for_shader(shader, 'LINES', {"pos": pts}).draw(shader)
        gpu.state.blend_set('NONE')


# The box length beside an edge: drawn as text in region pixels, picked by its rectangle.
class ALLSET_GT_um_label(Gizmo):
    bl_idname = LABEL

    __slots__ = ("text", "xy", "handle_role", "handle_index")

    def _size(self, context, text=None):
        import blf
        scale = context.preferences.system.ui_scale
        blf.size(0, LABEL_PX * scale)
        w, h = blf.dimensions(0, (getattr(self, "text", "") if text is None else text) or "0")
        return w, h, scale

    def draw(self, context):
        import blf
        import gpu
        xy = getattr(self, "xy", None)
        editing = um.EDIT.get("axis") == getattr(self, "handle_index", None)
        text = (um.EDIT.get("text", "") + "|") if editing else getattr(self, "text", "")
        if xy is None or not text:
            return
        w, h, scale = self._size(context, text)
        vw, vh = gpu.state.viewport_get()[2:]
        ortho = Matrix(((2.0 / vw, 0, 0, -1.0), (0, 2.0 / vh, 0, -1.0), (0, 0, -1.0, 0), (0, 0, 0, 1.0)))
        colour = self.color_highlight if self.is_highlight else self.color
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(ortho)
            if editing:         # a field: dark box, the typed text (selected while untouched)
                from gpu_extras.batch import batch_for_shader
                pad = 3 * scale
                x0, y0, x1, y1 = xy[0] - w / 2 - pad, xy[1] - h / 2 - pad, xy[0] + w / 2 + pad, xy[1] + h / 2 + pad
                shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                fill = FIELD_SELECTED if um.EDIT.get("fresh") else FIELD
                gpu.state.blend_set('ALPHA')
                shader.bind()
                shader.uniform_float("color", fill)
                batch_for_shader(shader, 'TRIS', {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1),
                                                          (x0, y1)]}).draw(shader)
                gpu.state.blend_set('NONE')
                colour = LABEL_COLOUR
            blf.color(0, *colour[:3], 1.0)
            blf.position(0, xy[0] - w / 2, xy[1] - h / 2, 0)
            blf.draw(0, text)

    def test_select(self, context, location):
        xy = getattr(self, "xy", None)
        if xy is None:
            return -1
        w, h, scale = self._size(context)
        pad = 3 * scale
        if abs(location[0] - xy[0]) <= w / 2 + pad and abs(location[1] - xy[1]) <= h / 2 + pad:
            return 0
        return -1


def _active(context):
    return mp.active_tool(context)


def label_edges(frame, lo, hi, depth, px):
    """{axis: edge index} of the edge each length is written beside: of the two edges of that axis nearest to the
    view, the lower one on screen (the outer one for ties)."""
    out = {}
    c_px = px(frame @ um.centre(lo, hi))
    for axis in range(3):
        cand = []
        for e in range(axis * 4, axis * 4 + 4):
            mid = frame @ um.edge_mid(lo, hi, e)
            p = px(mid)
            if p is None:
                continue
            cand.append((depth(mid), e, p))
        if not cand:
            continue
        cand.sort()
        near = cand[:2]
        if len(near) == 2 and abs(near[0][2][1] - near[1][2][1]) > 2.0:
            near.sort(key=lambda c: c[2][1])
        elif len(near) == 2 and c_px is not None:
            near.sort(key=lambda c: -abs(c[2][0] - c_px[0]))
        out[axis] = near[0][1]
    return out


def label_xy(mid, centre_px, a, b, gap, half=(0.0, 0.0)):
    """Where a length is written: its text (half width / height ``half``) ``gap`` px from its edge's middle, across
    the edge, away from the box centre (straight away from the centre for an edge seen end-on)."""
    ox, oy = mid[0] - centre_px[0], mid[1] - centre_px[1]
    nx = ny = 0.0
    if a is not None and b is not None:
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = (dx * dx + dy * dy) ** 0.5
        if ln > 4.0:
            nx, ny = -dy / ln, dx / ln
            if nx * ox + ny * oy < 0:
                nx, ny = -nx, -ny
    if nx == 0.0 and ny == 0.0:
        ln = (ox * ox + oy * oy) ** 0.5 or 1.0
        nx, ny = ox / ln, oy / ln
    reach = gap + abs(nx) * half[0] + abs(ny) * half[1]
    return mid[0] + nx * reach, mid[1] + ny * reach


class ALLSET_GGT_universal_manip(GizmoGroup):
    bl_idname = GROUP
    bl_label = "Universal Manipulator"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT', 'TOOL_FALLBACK_KEYMAP'}

    @classmethod
    def setup_keymap(cls, keyconfig):
        # click (the lengths) and drag (the handles), any modifier: Ctrl / Shift change a corner drag
        return keyconfig.keymaps.new(name="Generic Gizmo Click Drag", space_type='EMPTY', region_type='WINDOW')

    @classmethod
    def poll(cls, context):
        space = context.space_data
        if space is None or space.type != 'VIEW_3D' or not space.show_gizmo or not space.show_gizmo_tool:
            return False
        if context.mode not in {'OBJECT', 'EDIT_MESH'}:
            return False
        tool = _active(context)
        return tool is not None and tool.idname == um.TOOL and um.ready(context)

    def setup(self, context):
        colours = mp.axis_colours()
        self.box = self.gizmos.new(BOX)
        self.box.hide_select = True
        self.box.color = BOX_COLOUR
        self.box.alpha = 1.0
        self.corners, self.edges, self.arrows, self.labels = [], [], [], []
        for i in range(8):
            gz = self._handle('CORNER', mp.CENTER_IDLE)
            gz.target_set_operator("allset.um_scale").corner = i
            gz.handle_role, gz.handle_index = 'CORNER', i
            self.corners.append(gz)
        for e in range(12):
            gz = self._handle('ROTATE', colours['XYZ'[um.edge_spec(e)[0]]])
            gz.target_set_operator("allset.um_rotate").edge = e
            gz.handle_role, gz.handle_index = 'EDGE', e
            self.edges.append(gz)
        for i in range(3):
            gz = self._handle('ARROW', colours['XYZ'[i]])
            gz.handle_role, gz.handle_index = 'MOVE', i
            self.arrows.append(gz)
        self.circle = self._handle('CIRCLE', mp.CENTER_IDLE)
        self.circle.handle_role, self.circle.handle_index = 'MOVE_VIEW', None
        props = self.circle.target_set_operator("transform.translate")
        props.orient_type = 'VIEW'
        props.release_confirm = True
        for i in range(3):
            gz = self.gizmos.new(LABEL)
            gz.use_tooltip = False
            gz.color = LABEL_COLOUR
            gz.color_highlight = mp.YELLOW
            gz.alpha = gz.alpha_highlight = 1.0
            gz.use_draw_modal = True           # the field shows while its length is typed
            gz.handle_role, gz.handle_index = 'LABEL', i
            gz.target_set_operator("allset.um_size").axis = 'XYZ'[i]
            self.labels.append(gz)
        self._frame_for = None

    def _handle(self, kind, colour):
        gz = self.gizmos.new(HANDLE)
        gz.build(kind)
        gz.use_draw_scale = True
        gz.use_draw_modal = True
        gz.use_tooltip = False                 # Maya manipulators show no tooltip
        gz.line_width = 1.5
        gz.color = colour
        gz.color_highlight = mp.YELLOW
        gz.alpha = gz.alpha_highlight = 1.0
        return gz

    def _bind_moves(self, frame):
        sig = tuple(v for row in frame for v in row)
        if self._frame_for == sig or any(gz.is_modal for gz in self.gizmos):
            return
        for i, gz in enumerate(self.arrows):
            props = gz.target_set_operator("transform.translate")
            props.constraint_axis = tuple(k == i for k in range(3))
            props.orient_type = 'GLOBAL'
            props.orient_matrix_type = 'GLOBAL'
            props.orient_matrix = frame
            props.release_confirm = True
        self._frame_for = sig

    def _hide_all(self):
        for gz in self.gizmos:
            gz.hide = True

    def draw_prepare(self, context):
        region, rv3d = context.region, context.region_data
        box = um.box_of(context)
        if box is None or rv3d is None:
            self._hide_all()
            return
        frame, lo, hi = box
        self._bind_moves(frame)
        from bpy_extras.view3d_utils import location_3d_to_region_2d
        view_inv = rv3d.view_matrix
        view_dir = rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))     # toward the viewer

        def depth(p):
            return -(view_inv @ p).z

        def px(p):
            q = location_3d_to_region_2d(region, rv3d, p)
            return None if q is None else (q[0], q[1])

        s = mp.scale_basis(context)
        corners_w = [frame @ um.corner_point(lo, hi, i) for i in range(8)]
        far = max(range(8), key=lambda i: depth(corners_w[i]))
        flat = any(hi[i] - lo[i] < um.TINY for i in range(3))
        hidden_edges = set() if flat else set(um.edges_at_corner(far))
        rot = frame.to_4x4()
        self.box.hide = False
        self.box.lines = _edge_points(frame, lo, hi)
        self.box.matrix_basis = Matrix.Identity(4)
        for i, gz in enumerate(self.corners):
            gz.hide = i == far and not flat
            gz.scale_basis = s
            gz.matrix_basis = Matrix.Translation(corners_w[i]) @ rot
        pivot = um.rotate_pivot(context, frame, lo, hi)
        for e, gz in enumerate(self.edges):
            axis, _sides = um.edge_spec(e)
            mid = frame @ um.edge_mid(lo, hi, e)
            t = um.tangent(frame.col[axis], mid, pivot, view_dir)
            gz.hide = e in hidden_edges or t.length < 0.5
            gz.scale_basis = s
            if not gz.hide:
                z = t
                x = frame.col[axis].normalized()
                y = z.cross(x)
                m = Matrix((x, y, z)).transposed().to_4x4()
                gz.matrix_basis = Matrix.Translation(mid) @ m
        c = frame @ um.centre(lo, hi)
        for i, gz in enumerate(self.arrows):
            gz.hide = False
            gz.scale_basis = s * MOVE_SCALE
            gz.matrix_basis = Matrix.Translation(c) @ (frame @ mp._axis_rot('XYZ'[i])).to_4x4()
        self.circle.hide = False
        self.circle.scale_basis = s
        self.circle.matrix_basis = Matrix.Translation(c) @ rv3d.view_rotation.to_matrix().to_4x4()
        from ..operators.units import maya_unit
        unit = maya_unit(context.scene)
        where = label_edges(frame, lo, hi, depth, px)
        c_px = px(c)
        for i, gz in enumerate(self.labels):
            e = where.get(i)
            p = px(frame @ um.edge_mid(lo, hi, e)) if e is not None else None
            if p is None or c_px is None:
                gz.hide, gz.xy = True, None
                continue
            ends = []
            for side in (lo[i], hi[i]):
                q = um.edge_mid(lo, hi, e)
                q[i] = side
                ends.append(px(frame @ q))
            gap = LABEL_GAP * context.preferences.system.ui_scale
            gz.hide = False
            gz.text = f"{(hi[i] - lo[i]) / unit:.3f}"
            w, h, _scale = gz._size(context)
            gz.xy = label_xy(p, c_px, ends[0], ends[1], gap, (w / 2, h / 2))
            gz.matrix_basis = Matrix.Translation(c)


def draw_settings(context, layout, _tool):
    s = um.settings(context)
    layout.prop(s, "space", expand=True)
    layout.prop(s, "rotate_around", expand=True)
    if context.region.type != 'TOOL_HEADER':
        layout.operator("allset.um_reset")


class ALLSET_TL_universal_manip(bpy.types.WorkSpaceTool):
    """Maya Universal Manipulator."""
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = um.TOOL
    bl_label = "Universal Manipulator"
    bl_description = ("Box around the selection: drag a corner to scale (Ctrl: about the centre, Shift: evenly), "
                      "the arrows on an edge to rotate, the centre to move; click a length to type it")
    bl_icon = "ops.transform.transform"
    bl_widget = GROUP
    bl_keymap = None

    @staticmethod
    def draw_settings(context, layout, tool):
        draw_settings(context, layout, tool)


class ALLSET_TL_universal_manip_mesh(ALLSET_TL_universal_manip):
    '''Maya Universal Manipulator on mesh components (the same tool in a component mode).'''
    bl_context_mode = 'EDIT_MESH'


classes = (ALLSET_GT_um_handle, ALLSET_GT_um_box, ALLSET_GT_um_label, ALLSET_GGT_universal_manip)
TOOLS = (ALLSET_TL_universal_manip, ALLSET_TL_universal_manip_mesh)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    for tool in TOOLS:
        bpy.utils.register_tool(tool, after={"builtin.transform"})


def unregister():
    for tool in reversed(TOOLS):
        bpy.utils.unregister_tool(tool)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
