# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Blue Pencil on Blender's annotations (Visualize > Blue Pencil = the Annotate tool).

Like Maya:
- Blue Pencil frames are the annotation's drawn frames (every shown layer of the scene's annotation). The Time
  Slider marks each one with a light blue triangle (``FRAME_RGB``, 8 x 11 px at UI scale 1.0, its upright edge 2 px
  right of the frame's tick, standing on the ticks' bottom end: ``time_slider._draw_blue_pencil``).
- Alt+< / Alt+> go to the previous / next frame and wrap around at the ends (``allset.blue_pencil_frame``).
- Ghost Previous / Ghost Next (on, 3 frames each; add-on preferences ``bp_ghost_*``): the drawings of the nearest
  frames before / after the one on screen are drawn in their own colour at opacity 0.4 * (n + 1 - k) / n for the
  k-th of n, and not while the animation plays. The kit draws these ghosts itself; Blender's own onion skin settings
  of the layers are left as they are.
- While an annotate tool is active, Tool Settings shows Maya's Pencil / Line / Eraser tools and the ghost settings.
"""

import bpy

from .. import compat

FRAME_RGB = (0x63 / 255, 0xab / 255, 0xd4 / 255, 1.0)    # the Time Slider frame triangle
MARK_W, MARK_H, MARK_GAP = 8.0, 11.0, 2.0                 # px at UI scale 1.0
GHOST_ALPHA = 0.4                                         # the nearest ghost; farther ones fade linearly
GHOST_RANGE = (1, 10)
# (label, Blender tool) of Maya's Blue Pencil tools that Blender's annotations have
TOOLS = (("Pencil", "builtin.annotate"), ("Line", "builtin.annotate_line"), ("Eraser", "builtin.annotate_eraser"))
TOOL_IDS = frozenset({"builtin.annotate", "builtin.annotate_line", "builtin.annotate_polygon",
                      "builtin.annotate_eraser"})

_handles = []


# --- frames (pure rules) -------------------------------------------------------------------------------------------

def shown_layers(gp):
    return [lay for lay in gp.layers if not lay.annotation_hide] if gp is not None else []


def frame_numbers(scene):
    """Sorted frame numbers of the Blue Pencil frames (all shown layers)."""
    return sorted({f.frame_number for lay in shown_layers(compat.scene_annotation(scene)) for f in lay.frames})


def jump_target(frames, current, forward):
    """The frame Alt+> (``forward``) / Alt+< goes to from ``current``: the next / previous one, wrapping around at the
    ends; None without frames."""
    if not frames:
        return None
    if forward:
        later = [f for f in frames if f > current]
        return later[0] if later else frames[0]
    earlier = [f for f in frames if f < current]
    return earlier[-1] if earlier else frames[-1]


def ghost_frames(frames, current, n_prev, n_next):
    """([(frame, k)], [(frame, k)]): the n_prev frames before and the n_next frames after the frame shown at
    ``current`` (the last one at or before it), nearest first (k = 1, 2, ...). Before the first frame nothing is
    shown, so only the next ones are ghosts."""
    frames = sorted(frames)
    shown = [f for f in frames if f <= current]
    ref = shown[-1] if shown else None
    before = [f for f in frames if ref is not None and f < ref][::-1][:max(0, n_prev)]
    after = [f for f in frames if (f > ref if ref is not None else f > current)][:max(0, n_next)]
    return [(f, k + 1) for k, f in enumerate(before)], [(f, k + 1) for k, f in enumerate(after)]


def ghost_alpha(k, n):
    """Opacity of the k-th of n ghosts on one side."""
    return GHOST_ALPHA * (n + 1 - k) / n if n > 0 else 0.0


def ghost_settings(prefs):
    """(previous frames, next frames) to ghost; 0 = that side is off."""
    if prefs is None:
        return 0, 0
    prev = prefs.bp_ghost_previous_frames if prefs.bp_ghost_previous else 0
    nxt = prefs.bp_ghost_next_frames if prefs.bp_ghost_next else 0
    return prev, nxt


# --- Alt+< / Alt+> ---------------------------------------------------------------------------------------------------

class ALLSET_OT_blue_pencil_frame(bpy.types.Operator):
    """Go to the next or previous Blue Pencil (annotation) frame (Maya Next / Previous Blue Pencil Frame)"""
    bl_idname = "allset.blue_pencil_frame"
    bl_label = "Blue Pencil Frame"

    next: bpy.props.BoolProperty(name="Next", default=True, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        scene = context.scene
        target = jump_target(frame_numbers(scene), scene.frame_current, self.next)
        if target is None:
            return {'CANCELLED'}
        scene.frame_current = target
        return {'FINISHED'}


# --- Tool Settings -----------------------------------------------------------------------------------------------------

def _prefs():
    from .. import preferences
    try:
        return preferences.get()
    except KeyError:
        return None


def draw_settings(layout, context, tool_id):
    """The Blue Pencil section of the Tool Settings while an annotate tool is active."""
    header, body = layout.panel("allset_ts_blue_pencil", default_closed=False)
    header.label(text="Blue Pencil")
    if body is None:
        return
    row = body.row(align=True)
    for label, idname in TOOLS:
        op = row.operator("wm.tool_set_by_id", text=label, depress=tool_id == idname)
        op.name = idname
        op.space_type = 'VIEW_3D'
    prefs = _prefs()
    if prefs is None:
        return
    col = body.column(align=True)
    for side in ("previous", "next"):
        row = col.row(align=True)
        row.prop(prefs, f"bp_ghost_{side}")
        sub = row.row(align=True)
        sub.active = getattr(prefs, f"bp_ghost_{side}")
        sub.prop(prefs, f"bp_ghost_{side}_frames", text="Frames")


# --- ghosts ------------------------------------------------------------------------------------------------------------

def _playing(context):
    screen = getattr(context, "screen", None)
    return screen is not None and screen.is_animation_playing


def ghost_strokes(scene, space_2d):
    """[(points, rgba, width, in_front)] of the ghost strokes to draw: 3D strokes (``space_2d`` False, world
    coordinates) or view strokes (True, coordinates in % of the region)."""
    n_prev, n_next = ghost_settings(_prefs())
    if not (n_prev or n_next):
        return []
    out = []
    for lay in shown_layers(compat.scene_annotation(scene)):
        by_number = {f.frame_number: f for f in lay.frames}
        before, after = ghost_frames(by_number, scene.frame_current, n_prev, n_next)
        rgb = tuple(lay.color)[:3]
        width = max(1, lay.thickness)
        for side, n in ((before, n_prev), (after, n_next)):
            for number, k in side:
                alpha = ghost_alpha(k, n) * lay.annotation_opacity
                for stroke in by_number[number].strokes:
                    if (stroke.display_mode == '2DSPACE') != space_2d or stroke.display_mode == '2DIMAGE':
                        continue
                    pts = [tuple(p.co) for p in stroke.points]
                    if len(pts) > 1:
                        out.append((pts, (*rgb, alpha), width, lay.show_in_front))
    return out


def _view_ok(context):
    space = context.space_data
    return space is not None and space.type == 'VIEW_3D' and space.overlay.show_overlays \
        and getattr(space.overlay, "show_annotation", True) and not _playing(context)


def _draw_lines(strokes, to_px=None):
    import gpu
    from gpu_extras.batch import batch_for_shader
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    region = bpy.context.region
    scale = bpy.context.preferences.system.ui_scale or 1.0
    gpu.state.blend_set('ALPHA')
    shader.uniform_float("viewportSize", (region.width, region.height))
    for pts, rgba, width, in_front in strokes:
        if to_px is not None:
            pts = [to_px(p) for p in pts]
        else:
            gpu.state.depth_test_set('NONE' if in_front else 'LESS_EQUAL')
        segs = []
        for a, b in zip(pts, pts[1:]):
            segs += [a, b]
        shader.uniform_float("lineWidth", width * scale)
        shader.uniform_float("color", rgba)
        batch_for_shader(shader, 'LINES', {"pos": segs}).draw(shader)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


def _draw_3d():
    context = bpy.context
    if not _view_ok(context):
        return
    strokes = ghost_strokes(context.scene, False)
    if strokes:
        _draw_lines(strokes)


def _draw_2d():
    context = bpy.context
    if not _view_ok(context):
        return
    strokes = ghost_strokes(context.scene, True)
    if strokes:
        w, h = context.region.width, context.region.height
        _draw_lines([(pts, rgba, width, True) for pts, rgba, width, _f in strokes],
                    to_px=lambda p: (p[0] / 100.0 * w, p[1] / 100.0 * h))


classes = (ALLSET_OT_blue_pencil_frame,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw_3d, (), 'WINDOW', 'POST_VIEW'))
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw_2d, (), 'WINDOW', 'POST_PIXEL'))


def unregister():
    while _handles:
        bpy.types.SpaceView3D.draw_handler_remove(_handles.pop(), 'WINDOW')
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
