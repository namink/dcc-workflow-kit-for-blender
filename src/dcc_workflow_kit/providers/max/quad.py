# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
from .i18n import msg as _msg, display as _dcc_ui_text, format_message as _dcc_format, error_text as _dcc_ui_error
"The Default Viewport Quad: four quadrants drawn around the cursor.\n\nQuadrant titles, item order and colours follow 3ds Max 2027's Default.qmnxb and\nDefaultUI.qop (tools 1 top-left, display top-right, transform bottom-right,\ntools 2 bottom-left). Items nearest the centre come first in each quadrant.\n"
import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from . import runtime
from .operators import INTERACTIVE
TITLE_BG = (0.235, 0.235, 0.235, 1)
TITLE_TEXT = (0.6, 0.6, 0.6, 1)
ITEM_BG = (0.275, 0.275, 0.275, 1)
ITEM_TEXT = (0.624, 0.624, 0.624, 1)
LAST_TEXT = (1, 1, 1, 1)
HIGHLIGHT_BG = (0.235, 0.51, 0.863, 1)
BORDER = (0, 0, 0, 1)
DISABLED = (0.137, 0.137, 0.137, 1)
(ROW, ITEM_SIZE, TITLE_SIZE) = (12.4, 8.5, 8.0)
(TEXT_LEFT, RIGHT_GUTTER, MARKER) = (14.0, 11.5, 10.0)
SEP = None
_state = None
_handle = None
_shader = None
_last = {}

def I(label, op=None, enabled=True, option=None, call=None, **props):
    """An item running an operator or call(context); option is (operator, properties)
    behind Max's dialog box on the right. Items with neither are shown disabled."""
    return {'label': label, 'op': op, 'props': props, 'call': call, 'option': option, 'enabled': enabled and (op is not None or call is not None)}

def S(label, items):
    return {'label': label, 'items': items, 'enabled': any((i and i['enabled'] for i in items))}

def _editable_poly(obj):
    return obj is not None and obj.type == 'MESH' and (not (getattr(obj, 'bsm_prim', None) and obj.bsm_prim.kind))

def quadrants(context):
    obj = context.view_layer.objects.active
    state = context.window_manager.bsm
    space = context.space_data
    local = space is not None and getattr(space, 'local_view', None) is not None
    edit = context.mode == 'EDIT_MESH'
    level = state.component if edit else 0
    selected = bool(context.selected_objects)
    display = [I(_msg('Show Motion Paths'), 'object.paths_calculate') if selected else SEP, SEP, I(_msg('Manage State Sets...')), S(_msg('State Sets'), [I(_msg('Manage State Sets...'))]), SEP, I(_msg('Hide Selection'), 'object.hide_view_set', unselected=False), I(_msg('Hide Unselected'), 'object.hide_view_set', unselected=True), I(_msg('Unhide All'), 'object.hide_view_clear'), I(_msg('Unhide by Name'), 'bsm.select_from_scene', purpose='UNHIDE'), SEP, I(_msg('Freeze Selection'), 'bsm.toolbar_action', action='FREEZE'), I(_msg('Unfreeze All'), 'bsm.toolbar_action', action='UNFREEZE'), SEP, I(_msg('Zoom Extents On Isolate'), 'bsm.max_command', command='ZOOM_EXTENTS_ISOLATE'), I(_msg('End Isolate'), 'bsm.max_command', local, command='END_ISOLATE'), I(_msg('Isolate Selection'), 'bsm.max_command', bool(context.selected_objects) and (not local), command='ISOLATE'), SEP, S(_msg('Viewport Lighting and Shadows'), [I(_msg('Auto Display Selected Lights'), 'bsm.viewport_shading', style='SCENE_LIGHTS'), SEP, I(_msg('Lock Selected Lights')), I(_msg('Unlock Selected Lights'))])]
    convert = [I(_msg('Convert to Editable Spline'), 'bsm.stack_action', bool(obj) and obj.type in {'MESH', 'FONT', 'CURVE'}, action='CONVERT_SPLINE'), I(_msg('Convert to Editable Mesh'), 'bsm.stack_action', bool(obj), action='CONVERT_POLY'), I(_msg('Convert to Editable Poly'), 'bsm.stack_action', bool(obj), action='CONVERT_POLY'), I(_msg('Convert to Deformable gPoly')), I(_msg('Convert to Editable Patch')), I(_msg('Convert to NURBS'))]
    typein = lambda tool: ('bsm.transform_typein_tool', {'tool': tool})
    transform = [I(_msg('Move'), 'bsm.tool', option=typein('MOVE'), tool='MOVE'), I(_msg('Rotate'), 'bsm.tool', option=typein('ROTATE'), tool='ROTATE'), I(_msg('Scale'), 'bsm.tool', option=typein('SCALE'), tool='SCALE'), I(_msg('Placement'), 'bsm.place_surface', not edit), I(_msg('Select'), 'bsm.tool', tool='SELECT'), I(_msg('Select Similar'), 'bsm.max_command', selected, command='SELECT_SIMILAR'), SEP, I(_msg('Place Working Pivot'), 'wm.tool_set_by_id', selected, name='builtin.cursor'), I(_msg('Align Working Pivot'), 'view3d.snap_cursor_to_selected', selected), I(_msg('Reset Working Pivot'), 'view3d.snap_cursor_to_center'), S(_msg('Snap Pivot'), [I(_msg('Pivot to Bounding Box'), 'object.origin_set', not edit, type='ORIGIN_GEOMETRY'), I(_msg('Pivot to Working Pivot'), 'object.origin_set', not edit, type='ORIGIN_CURSOR')]), SEP, I(_msg('Clone'), 'bsm.clone', bool(context.selected_objects) and (not edit)), SEP, I(_msg('Object Properties...'), 'bsm.object_properties', bool(obj)), SEP, I(_msg('Curve Editor...'), 'bsm.editor', kind='GRAPH'), I(_msg('Dope Sheet...'), 'bsm.editor', kind='DOPESHEET'), I(_msg('Wire Parameters...')), SEP, S(_msg('Convert To:'), convert) if selected else SEP]
    (tools1, tools2) = ([], [])
    if _editable_poly(obj):
        tools1 += [S(_msg('Sub-objects'), [I(_msg('Top-level'), 'bsm.component', level=0), I(_msg('Vertex'), 'bsm.component', level=1), I(_msg('Edge'), 'bsm.component', level=2), I(_msg('Border'), 'bsm.component', level=3), I(_msg('Polygon'), 'bsm.component', level=4), I(_msg('Element'), 'bsm.component', level=5)]), SEP]
        if edit:
            tools1 += [I(_msg('Convert to Vertex'), 'mesh.select_mode', type='VERT', use_expand=True), I(_msg('Convert to Edge'), 'mesh.select_mode', type='EDGE', use_expand=True), I(_msg('Convert to Face'), 'mesh.select_mode', type='FACE', use_expand=True), SEP]
        tools1 += [I(_msg('Repeat'), 'screen.repeat_last'), SEP, I(_msg('Quickslice'), 'bsm.mesh_action', edit, action='SLICE'), I(_msg('Cut'), 'bsm.mesh_action', edit, action='CUT'), SEP, I(_msg('Attach'), 'bsm.mesh_action', action='ATTACH'), I(_msg('Collapse'), 'bsm.mesh_action', edit, action='COLLAPSE'), I(_msg('Hide Unselected'), 'bsm.mesh_action', edit, action='HIDE_UNSELECTED'), SEP, I(_msg('Ignore Backfacing'), 'bsm.ignore_backfacing'), I(_msg('NURMS Toggle'), 'bsm.mesh_action', action='NURMS')]
        m = lambda label, action, ok=True: I(label, 'bsm.mesh_action', edit and ok, action=action)
        by_level = {1: [m(_msg('Create'), 'CREATE_FACE'), SEP, m(_msg('Remove'), 'DISSOLVE_VERTS'), m(_msg('Break'), 'BREAK'), m(_msg('Connect'), 'CONNECT_VERTS'), SEP, m(_msg('Extrude'), 'EXTRUDE_VERTS'), m(_msg('Chamfer'), 'CHAMFER_VERTS'), SEP, m(_msg('Weld'), 'WELD'), m(_msg('Target Weld'), 'TARGET_WELD')], 2: [m(_msg('Create'), 'CREATE_FACE'), SEP, m(_msg('Remove'), 'DISSOLVE_EDGES'), m(_msg('Split'), 'SPLIT_EDGES'), m(_msg('Connect'), 'CONNECT_EDGES'), m(_msg('Insert Vertex'), 'INSERT_VERTEX'), SEP, m(_msg('Extrude'), 'EXTRUDE_EDGES'), m(_msg('Chamfer'), 'CHAMFER'), SEP, m(_msg('Weld'), 'WELD'), m(_msg('Target Weld'), 'TARGET_WELD'), SEP, I(_msg('Edit Triangulation')), m(_msg('Create Shape'), 'CREATE_SHAPE')], 3: [m(_msg('Insert Vertex'), 'INSERT_VERTEX'), m(_msg('Cap'), 'CAP'), m(_msg('Connect'), 'CONNECT_EDGES'), SEP, m(_msg('Extrude'), 'EXTRUDE_EDGES'), m(_msg('Chamfer'), 'CHAMFER'), SEP, m(_msg('Create Shape'), 'CREATE_SHAPE')], 4: [m(_msg('Insert Vertex'), 'POKE'), SEP, m(_msg('Extrude'), 'EXTRUDE'), m(_msg('Bevel'), 'BEVEL_POLY'), m(_msg('Outline'), 'OUTLINE'), m(_msg('Inset'), 'INSET'), SEP, I(_msg('Hinge from Edge')), I(_msg('Extrude along Spline')), SEP, I(_msg('Edit Triangulation')), m(_msg('Flip Normals'), 'FLIP')]}
        by_level[5] = by_level[4]
        tools2 = by_level.get(level, [])
    elif obj is not None and obj.type in {'LIGHT', 'CAMERA'}:
        target = next((c.target for c in obj.constraints if c.type == 'TRACK_TO' and c.target), None)
        if obj.type == 'LIGHT':
            tools1 += [I(_msg('Light On') if obj.hide_render else _msg('Light Off'), 'bsm.toggle_render_visibility'), I(_msg('Shadows'), 'wm.context_toggle', data_path='object.data.use_shadow')]
        if target:
            tools1 += [I(_msg('Select Target'), 'bsm.select_named', name=target.name)]
        if obj.type == 'CAMERA':
            tools1 += [I(_msg('Set Active Camera'), 'view3d.object_as_camera')]
    quads = {'TL': (_msg('tools 1'), tools1), 'TR': ('display', display), 'BR': ('transform', transform), 'BL': (_msg('tools 2'), tools2)}
    return {key: (title, tidy(items)) for (key, (title, items)) in quads.items()}

def tidy(items):
    """SetRemoveRedundantSeparators: no separator at either end or next to another."""
    out = []
    for item in items:
        if item is SEP and (not out or out[-1] is SEP):
            continue
        out.append(item)
    while out and out[-1] is SEP:
        out.pop()
    return out

def _shader_get():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _shader

def _rect(x, y, w, h, color):
    shader = _shader_get()
    batch = batch_for_shader(shader, 'TRIS', {'pos': [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]}, indices=[(0, 1, 2), (0, 2, 3)])
    shader.bind()
    shader.uniform_float('color', color)
    batch.draw(shader)
_fonts = {}

def _font(bold=False):
    """Arial, the quad menu face in DefaultUI.qop (titles render bold in Max 2027);
    the panel font if it is missing."""
    from ...localization import is_chinese
    if is_chinese():
        return 0
    import os
    from pathlib import Path
    from .surfaces import font, load_font
    path = Path(os.environ.get('WINDIR', _msg('C:/Windows'))) / _msg('Fonts') / ('arialbd.ttf' if bold else 'arial.ttf')
    return load_font(_fonts, bold, path, lambda : font(bold))

def _text(value, x, y, color, size, bold=False):
    f = _font(bold)
    blf.size(f, size)
    blf.position(f, x, y, 0)
    blf.color(f, *color)
    blf.draw(f, _dcc_ui_text(value))

def _width(value, size, bold=False):
    f = _font(bold)
    blf.size(f, size)
    return blf.dimensions(f, _dcc_ui_text(value))[0]

def _column_width(state, item_lists):
    u = state['u']
    labels = [i['label'] for items in item_lists for i in items if i]
    return max([_width(l, ITEM_SIZE * u) for l in labels] + [60 * u]) + (TEXT_LEFT + RIGHT_GUTTER) * u

def layout(state, region):
    """Compute item rectangles in region pixels, keeping the whole quad inside the region.

    Every quadrant has the same width and every row the same height (SetUseUniformQuadWidth,
    SetUseUniformItemHeight); separators are lines between rows and take no height."""
    u = state['u']
    row = round(ROW * u)
    (cx, cy) = state['center']
    quads = state['quads']
    w = round(_column_width(state, [items for (_, items) in quads.values()]))
    heights = {k: sum((row for i in items if i)) for (k, (t, items)) in quads.items()}
    left = w if quads['TL'][1] or quads['BL'][1] else 0
    right = w if quads['TR'][1] or quads['BR'][1] else 0
    up = max(heights['TL'], heights['TR']) + row
    down = max(heights['BL'], heights['BR']) + row
    cx = round(min(max(cx, left + 2), region.width - right - 2))
    cy = round(min(max(cy, down + 2), region.height - up - 2))
    state['center'] = (cx, cy)
    rects = []
    for (key, (title, items)) in quads.items():
        if not items:
            continue
        x = cx - w if key in {'TL', 'BL'} else cx
        if key in {'TL', 'TR'}:
            y = cy
            rects.append(('TITLE', key, title, x, y, w, row))
            y += row
            for item in items:
                rects.append(('ITEM', key, item, x, y, w, row) if item else ('SEP', key, None, x, y, w, 0))
                y += row if item else 0
        else:
            top = cy
            rects.append(('TITLE', key, title, x, top - row, w, row))
            top -= row
            for item in items:
                rects.append(('ITEM', key, item, x, top - row, w, row) if item else ('SEP', key, None, x, top, w, 0))
                top -= row if item else 0
    state['rects'] = rects
    return rects

def _submenu_rects(state, parent):
    (kind, key, item, x, y, w, h) = parent
    u = state['u']
    row = round(ROW * u)
    children = tidy(item['items'])
    width = round(_column_width(state, [children]))
    sx = x + w if key in {'TR', 'BR'} else x - width
    rects = []
    sy = y
    for child in children:
        rects.append(('SUB', key, child, sx, sy, width, row) if child else ('SEP', key, None, sx, sy + row, width, 0))
        sy -= row if child else 0
    return rects

def _option_box(rect, u):
    (kind, key, item, x, y, w, h) = rect
    size = round(7 * u)
    return (x + w - size - round(2 * u), y + (h - size) // 2, size)

def _thick(u):
    return max(1, round(u))

def _line(x, y, w, u):
    _rect(x, y - _thick(u) // 2, w, _thick(u), BORDER)

def draw():
    state = _state
    context = bpy.context
    if state is None or context.region is None or context.region.as_pointer() != state['region']:
        return
    region = context.region
    rects = layout(state, region)
    u = state['u']
    (size, title_size) = (ITEM_SIZE * u, TITLE_SIZE * u)
    gpu.state.blend_set('ALPHA')
    hover = state.get('hover')
    sub = state.get('submenu')
    for column in (rects, _submenu_rects(state, sub) if sub else []):
        boxes = [r for r in column if r[0] != 'SEP']
        b = _thick(u)
        for (kind, key, item, x, y, w, h) in boxes:
            _rect(x - b, y - b, w + 2 * b, h + 2 * b, BORDER)
        for rect in boxes:
            (kind, key, item, x, y, w, h) = rect
            if kind == 'TITLE':
                _rect(x, y, w, h, TITLE_BG)
                marker = round(MARKER * u)
                _rect(x if key in {'TR', 'BR'} else x + w - marker, y, marker, h, HIGHLIGHT_BG)
                tw = _width(item, title_size, True)
                _text(item, x + w - tw - 2 * u if key in {'TR', 'BR'} else x + 2 * u, y + (h - title_size * 0.7) / 2, TITLE_TEXT, title_size, True)
                continue
            hot = rect == hover or (sub is not None and rect[2] is sub[2])
            lit = hot and item['enabled']
            _rect(x, y, w, h, HIGHLIGHT_BG if lit else ITEM_BG)
            last = item['enabled'] and _last.get((state['name'], key)) == item['label']
            color = LAST_TEXT if lit or last else ITEM_TEXT if item['enabled'] else DISABLED
            _text(item['label'], x + TEXT_LEFT * u, y + (h - size * 0.7) / 2, color, size)
            mark = LAST_TEXT if lit else BORDER
            if 'items' in item:
                (ax, ay, ah) = (x + w - 6 * u, y + h / 2, 3.2 * u)
                _triangle(((ax - ah * 0.9, ay + ah), (ax - ah * 0.9, ay - ah), (ax + ah * 0.55, ay)), mark)
            elif item.get('option'):
                (bx, by, bs) = _option_box(rect, u)
                inset = max(1, round(u * 0.6))
                _rect(bx, by, bs, bs, mark)
                _rect(bx + inset, by + inset, bs - 2 * inset, bs - 2 * inset - max(2, round(1.6 * u)), HIGHLIGHT_BG if lit else ITEM_BG)
        for (kind, key, item, x, y, w, h) in column:
            if kind == 'SEP':
                _line(x, y, w, u)
        if column is rects:
            for (kind, key, item, x, y, w, h) in column:
                if kind == 'TITLE':
                    _line(x, state['center'][1], w, u)
    gpu.state.blend_set('NONE')

def _triangle(points, color):
    shader = _shader_get()
    batch = batch_for_shader(shader, 'TRIS', {'pos': list(points)})
    shader.bind()
    shader.uniform_float('color', color)
    batch.draw(shader)

def _hit(state, x, y):
    candidates = (_submenu_rects(state, state['submenu']) if state.get('submenu') else []) + state.get('rects', [])
    for rect in candidates:
        (kind, key, item, rx, ry, w, h) = rect
        if kind in {'ITEM', 'SUB'} and rx <= x < rx + w and (ry <= y < ry + h):
            return rect
    return None

def close():
    global _state, _handle
    if _handle is not None:
        (space, handle) = _handle
        space.draw_handler_remove(handle, 'WINDOW')
        _handle = None
    _state = None
    runtime.redraw()

class BSM_OT_quad_modal(bpy.types.Operator):
    bl_idname = 'bsm.quad_modal'
    bl_label = _msg('Quad Menu')

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        state = _state
        if state is None:
            return {'FINISHED'}
        area = next((a for a in context.window.screen.areas if a.as_pointer() == state['area']), None)
        region = next((r for r in area.regions if r.as_pointer() == state['region']), None) if area else None
        if region is None:
            close()
            return {'CANCELLED'}
        (x, y) = (event.mouse_x - region.x, event.mouse_y - region.y)
        pending = state.get('pending')
        if pending is not None:
            if event.type == 'MOUSEMOVE':
                (px, py) = pending['xy']
                limit = context.preferences.inputs.drag_threshold_mouse * context.preferences.system.ui_scale
                if (x - px) ** 2 + (y - py) ** 2 < limit ** 2:
                    return {'RUNNING_MODAL'}
                return self.run(context, area, region, pending, True)
            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                return self.run(context, area, region, pending, False)
            if event.type == 'ESC' or (event.type == 'RIGHTMOUSE' and event.value == 'PRESS'):
                close()
                return {'CANCELLED'}
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            hit = _hit(state, x, y)
            if hit != state.get('hover'):
                state['hover'] = hit
                if hit and hit[0] == 'ITEM':
                    state['submenu'] = hit if 'items' in hit[2] and hit[2]['enabled'] else None
                area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type in {'ESC'} or (event.type == 'RIGHTMOUSE' and event.value == 'PRESS'):
            close()
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            hit = _hit(state, x, y)
            if hit is None:
                close()
                return {'CANCELLED'}
            item = hit[2]
            if 'items' in item or not item['enabled']:
                return {'RUNNING_MODAL'}
            _last[state['name'], hit[1]] = item['label']
            (operator, props, call) = (item['op'], item['props'], item['call'])
            if item.get('option'):
                (bx, by, bs) = _option_box(hit, state['u'])
                if bx - 2 <= x < bx + bs + 2:
                    ((operator, props), call) = (item['option'], None)
            command = {'operator': operator, 'props': props, 'call': call, 'xy': (x, y)}
            if call is None and operator == 'bsm.mesh_action' and (props.get('action') in INTERACTIVE):
                state['pending'] = command
                return {'RUNNING_MODAL'}
            return self.run(context, area, region, command)
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            close()
            return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}

    def run(self, context, area, region, command, release_confirm=None):
        close()
        (operator, props, call) = (command['operator'], command['props'], command['call'])
        if release_confirm is not None:
            props = {**props, 'release_confirm': release_confirm}
        with context.temp_override(window=context.window, area=area, region=region):
            try:
                if call is not None:
                    call(context)
                else:
                    (group, method) = operator.split('.')
                    getattr(getattr(bpy.ops, group), method)('INVOKE_DEFAULT', **props)
            except RuntimeError as error:
                self.report({'WARNING'}, _dcc_ui_error(error).split('\n')[0])
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_transform_typein_tool(bpy.types.Operator):
    bl_idname = 'bsm.transform_typein_tool'
    bl_label = _msg('Transform Type-In')
    bl_description = _msg('Choose the transform and open its Type-In dialog, like the option box in Max')
    tool: bpy.props.StringProperty(default='MOVE', translation_context=_msg('DCCWorkflowKit.Max'))

    def invoke(self, context, event):
        bpy.ops.bsm.tool(tool=self.tool)
        return bpy.ops.bsm.transform_typein('INVOKE_DEFAULT')
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_ignore_backfacing(bpy.types.Operator):
    bl_idname = 'bsm.ignore_backfacing'
    bl_label = _msg('Ignore Backfacing')

    def execute(self, context):
        context.space_data.shading.show_xray = not context.space_data.shading.show_xray
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_toggle_render_visibility(bpy.types.Operator):
    bl_idname = 'bsm.toggle_render_visibility'
    bl_label = _msg('Light On/Off')
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if obj:
            obj.hide_render = not obj.hide_render
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

class BSM_OT_select_named(bpy.types.Operator):
    bl_idname = 'bsm.select_named'
    bl_label = _msg('Select Object')
    bl_options = {'REGISTER', 'UNDO'}
    name: bpy.props.StringProperty(translation_context=_msg('DCCWorkflowKit.Max'))

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is None:
            return {'CANCELLED'}
        for other in context.view_layer.objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}
    bl_translation_context = _msg('DCCWorkflowKit.Max')

def open_menu(context, event, quads, name):
    """Show a quad menu ({'TL': (title, items), ...}) around the cursor in this area's main
    region: the viewport, or an editor canvas (Image Editor area)."""
    global _state, _handle
    from .surfaces import scale
    (area, region) = (context.area, context.region)
    spaces = {'VIEW_3D': bpy.types.SpaceView3D, 'IMAGE_EDITOR': bpy.types.SpaceImageEditor}
    if area is None or area.type not in spaces or region is None or (region.type != 'WINDOW'):
        return {'CANCELLED'}
    close()
    _state = {'name': name, 'area': area.as_pointer(), 'region': region.as_pointer(), 'u': scale(), 'center': (event.mouse_x - region.x, event.mouse_y - region.y), 'quads': {key: (title, tidy(items)) for (key, (title, items)) in quads.items()}, 'hover': None, 'submenu': None}
    space = spaces[area.type]
    _handle = (space, space.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL'))
    area.tag_redraw()
    bpy.ops.bsm.quad_modal('INVOKE_DEFAULT')
    return {'FINISHED'}

def open_quad(context, event):
    if context.area is None or context.area.type != 'VIEW_3D':
        return {'CANCELLED'}
    return open_menu(context, event, quadrants(context), 'viewport')
CLASSES = (BSM_OT_quad_modal, BSM_OT_transform_typein_tool, BSM_OT_ignore_backfacing, BSM_OT_toggle_render_visibility, BSM_OT_select_named)
