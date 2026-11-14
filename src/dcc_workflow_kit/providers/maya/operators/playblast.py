# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Playblast: a viewport recording of the playback range, then the player in front.

Maya's Windows > Playblast records the Time Slider range from the active view into a movie and plays it in a
player (View on); its option box sets Time range, Format, Quality, Scale and Save to File with a movie file name.
Blender: ``render.opengl`` (animation) already records the playback (preview) range into the scene's render
output, and Blender's player (a second Blender, ``-a``) plays a movie. The kit points the output at a temporary
folder (or the chosen file) with the playblast's format and scale, closes the render window the recording opened,
starts the player itself so it can bring the player's window to the front (Windows), tells where the movie is,
and puts the scene's render settings back.
"""

import os
import subprocess
import sys
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from .. import results
from .. import compat

MAYA_QUALITY = 70          # Maya Playblast option defaults
MAYA_SCALE = 0.5
FRONT_WAIT_S = 20.0        # how long the kit watches for the player's window after starting it
FRONT_POLL_S = 0.25
MOVIE_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".jpg", ".jpeg", ".png")


def output_dir():
    return os.path.join(bpy.app.tempdir or bpy.path.abspath("//"), "playblast")


def output_path(scene):
    return os.path.join(output_dir(), f"{bpy.path.clean_name(scene.name)}_")


def movie_stem(filepath):
    """Save to File: the render path for the chosen movie file. Blender appends the frame range and the
    extension itself, so a typed extension is dropped."""
    path = bpy.path.abspath(filepath)
    root, ext = os.path.splitext(path)
    return root if ext.lower() in MOVIE_EXTENSIONS else path


def _crf(quality):
    return 'HIGH' if quality >= 85 else 'MEDIUM' if quality >= 55 else 'LOW'


SETTINGS = ("render.filepath", "render.resolution_percentage", "render.image_settings.file_format",
            "render.image_settings.quality", "render.ffmpeg.format", "render.ffmpeg.codec",
            "render.ffmpeg.constant_rate_factor", "use_preview_range", "frame_preview_start", "frame_preview_end",
            "render.image_settings.media_type")


def _get(scene, path):
    owner = scene
    *head, attr = path.split(".")
    for part in head:
        owner = getattr(owner, part)
    return owner, attr


def save_settings(scene):
    return {path: getattr(*_get(scene, path)) for path in SETTINGS}


def restore_settings(scene, saved):
    # media type (5.x), then file format: the ffmpeg values only stick while the format is FFMPEG
    first = ("render.image_settings.media_type", "render.image_settings.file_format")
    order = sorted(saved, key=lambda p: first.index(p) if p in first else len(first))
    for path in order:
        owner, attr = _get(scene, path)
        try:
            setattr(owner, attr, saved[path])
        except (TypeError, ValueError):
            pass


def apply_settings(scene, fmt, quality, scale, frames=None, filepath=None):
    """Point the scene's render output at the playblast: temp folder (or ``filepath``'s stem), format, scale,
    optional frame range."""
    r = scene.render
    r.filepath = movie_stem(filepath) if filepath else output_path(scene)
    r.resolution_percentage = max(1, min(100, round(scale * 100)))
    if fmt == 'MOVIE':
        compat.set_file_format(r.image_settings, 'FFMPEG')
        r.ffmpeg.format = 'MPEG4'
        r.ffmpeg.codec = 'H264'
        r.ffmpeg.constant_rate_factor = _crf(quality)
    else:
        compat.set_file_format(r.image_settings, 'JPEG')
        r.image_settings.quality = quality
    if frames is not None:
        scene.use_preview_range = True
        scene.frame_preview_start, scene.frame_preview_end = frames


def playback_range(scene):
    if scene.use_preview_range:
        return scene.frame_preview_start, scene.frame_preview_end
    return scene.frame_start, scene.frame_end


def movie_path(scene):
    """The file the recording writes with the scene's current render settings (first frame for an image
    sequence)."""
    return bpy.path.abspath(scene.render.frame_path(frame=playback_range(scene)[0], preview=scene.use_preview_range))


def _view3d(context):
    if context.area is not None and context.area.type == 'VIEW_3D':
        region = context.region if context.region and context.region.type == 'WINDOW' else None
        return context.area, region or next(r for r in context.area.regions if r.type == 'WINDOW')
    from ..ui.status_line import main_view3d
    return main_view3d(context.screen)


# --- the render window and the player -------------------------------------------------------------------

def window_ids(wm):
    return {w.as_pointer() for w in wm.windows}


def is_render_window(window):
    """A window Blender opened for a render: every area an Image Editor on the Render Result."""
    areas = list(window.screen.areas)
    if not areas:
        return False
    for area in areas:
        if area.type != 'IMAGE_EDITOR':
            return False
        img = area.spaces.active.image
        if img is None or img.type != 'RENDER_RESULT':
            return False
    return True


def close_render_windows(context, before):
    """Close the render windows that opened since ``before`` (window_ids): the player takes their place."""
    n = 0
    for window in list(context.window_manager.windows):
        if window.as_pointer() in before or not is_render_window(window):
            continue
        with context.temp_override(window=window):
            if bpy.ops.wm.window_close.poll():
                bpy.ops.wm.window_close()
                n += 1
    return n


def player_command(scene, prefs, path, backend=None):
    """Blender's own player on ``path`` (what Blender's Play Rendered Animation starts for its internal
    player); None when the preferences name another player (Blender's operator handles those)."""
    if prefs.filepaths.animation_player_preset != 'INTERNAL':
        return None
    rd = scene.render
    a, b = playback_range(scene)
    cmd = [bpy.app.binary_path]
    if backend:
        cmd += ["--gpu-backend", backend.lower()]
    cmd += ["-a", "-f", str(rd.fps), str(rd.fps_base), "-s", str(a), "-e", str(b), "-j", str(scene.frame_step),
            "-c", str(prefs.system.memory_cache_limit), path]
    return cmd


def _gpu_backend():
    try:
        import gpu
        backend = gpu.platform.backend_type_get()
    except Exception:
        return None
    return backend if backend not in {'NONE', 'UNKNOWN'} else None


def _player_windows(pid):
    """Visible top-level windows of process ``pid`` (Windows)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    user32.EnumWindows(each, 0)
    return found


def bring_to_front(pid, until):
    """Timer: once the player (``pid``) shows a window, make it the foreground window; gives up at ``until``."""
    if sys.platform != "win32":
        return None
    try:
        windows = _player_windows(pid)
    except Exception:
        return None
    if windows:
        import ctypes
        user32 = ctypes.windll.user32
        for hwnd in windows:
            user32.ShowWindow(hwnd, 5)                 # SW_SHOW
            user32.SetForegroundWindow(hwnd)
        return None
    return FRONT_POLL_S if time.monotonic() < until else None


def play(context, path):
    """Start the player on ``path`` and bring its window to the front. Returns the player's pid, or None when
    Blender's own operator was used (another player preset)."""
    cmd = player_command(context.scene, context.preferences, path, _gpu_backend())
    if cmd is None:
        bpy.ops.render.play_rendered_anim()
        return None
    proc = subprocess.Popen(cmd, env=os.environ.copy())
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(proc.pid)
        except Exception:
            pass
        until = time.monotonic() + FRONT_WAIT_S
        bpy.app.timers.register(lambda: bring_to_front(proc.pid, until), first_interval=FRONT_POLL_S)
    return proc.pid


class ALLSET_OT_playblast(bpy.types.Operator):
    """Record the playback range from the viewport and play it (Maya Playblast)"""
    bl_idname = "allset.playblast"
    bl_label = "Playblast"

    time_range: EnumProperty(name="Time Range", items=(('TIME_SLIDER', "Time Slider", "The playback range"),
                                                       ('START_END', "Start/End", "")), default='TIME_SLIDER')
    start: IntProperty(name="Start Time", default=1)
    end: IntProperty(name="End Time", default=120)
    format: EnumProperty(name="Format", items=(('MOVIE', "Movie (MPEG-4)", "Maya avi / qt"),
                                               ('IMAGE', "Image (JPEG sequence)", "")), default='MOVIE')
    quality: IntProperty(name="Quality", default=MAYA_QUALITY, min=1, max=100, subtype='PERCENTAGE')
    scale: FloatProperty(name="Scale", default=MAYA_SCALE, min=0.1, max=1.0)
    view: BoolProperty(name="View", default=True, description="Play the playblast when it is done")
    save_to_file: BoolProperty(name="Save to File", default=False,
                               description="Write the movie to the file below instead of the temporary folder")
    filepath: StringProperty(name="Movie File", subtype='FILE_PATH',
                             description="The movie file (the frame range and the extension are added)")
    option_box: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        if self.option_box:
            a, b = playback_range(context.scene)
            self.start, self.end = a, b
            return context.window_manager.invoke_props_dialog(self, width=360, title="Playblast Options",
                                                              confirm_text="Playblast")
        return self.execute(context)

    def folder(self):
        if self.save_to_file and self.filepath:
            return os.path.dirname(movie_stem(self.filepath))
        return output_dir()

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "time_range", expand=True)
        col = layout.column(align=True)
        col.active = self.time_range == 'START_END'
        col.prop(self, "start")
        col.prop(self, "end")
        layout.prop(self, "view")
        layout.prop(self, "format")
        layout.prop(self, "quality", slider=True)
        layout.prop(self, "scale", slider=True)
        layout.prop(self, "save_to_file")
        sub = layout.column()
        sub.active = self.save_to_file
        sub.prop(self, "filepath")
        folder = self.folder()
        row = layout.row(align=True)
        row.label(text=folder, icon='FILE_FOLDER')
        if os.path.isdir(folder):
            row.operator("wm.path_open", text="", icon='FILEBROWSER').filepath = folder

    def execute(self, context):
        scene = context.scene
        area, region = _view3d(context)
        if area is None:
            self.report({'ERROR'}, "Playblast needs a 3D View")
            return {'CANCELLED'}
        saved = save_settings(scene)
        frames = (self.start, self.end) if self.time_range == 'START_END' else None
        target = self.filepath if self.save_to_file and self.filepath else None
        os.makedirs(os.path.dirname(movie_stem(target)) if target else output_dir(), exist_ok=True)
        before = window_ids(context.window_manager)
        movie = None
        a, b = playback_range(scene)
        try:
            apply_settings(scene, self.format, self.quality, self.scale, frames, target)
            with context.temp_override(area=area, region=region):
                bpy.ops.render.opengl(animation=True)
            movie = movie_path(scene)
            a, b = playback_range(scene)
            if self.view:
                if os.path.exists(movie):
                    close_render_windows(context, before)
                    with context.temp_override(area=area, region=region):
                        play(context, movie)
                else:
                    self.report({'WARNING'}, f"Playblast file not found: {movie}")
        finally:
            restore_settings(scene, saved)
        results.result(self, f"Playblast frames {a}-{b}: {movie}")
        return {'FINISHED'}


classes = (ALLSET_OT_playblast,)
