# SPDX-License-Identifier: GPL-3.0-or-later
"""Render > Render Sequence with its Maya options: renderable cameras and Skip existing frames.

- Each camera has Maya's Renderable check (``Camera.allset_renderable``, kept on the camera data like Maya's
  camera shape attribute; on by default, off for the startup top / front / side cameras of a new Maya scene). It
  shows in the Attribute Editor camera tab (Output Settings) and in the Render Sequence option window.
- Render Sequence with All Render-Enabled Cameras renders the frame range once per renderable camera, one after
  another. With more than one camera each camera's frames go into a folder named after the camera inside the
  output folder (``<folder>/<camera>/<file name>``). The render camera and output path come back afterwards; a
  cancelled render (Esc) stops the cameras still waiting.
- Current Camera renders through one camera; the default is the plain Render Sequence (``allset.render``).
  Alternate Output File Location renders into another folder for this sequence only.
- Skip existing frames is Blender's Overwrite off + Placeholders on (the scene's own output options): a stopped
  sequence picks up where it stopped, and several computers rendering the same range into one folder share it.

While a sequence runs in the interface, Blender renders one camera as one render job; a timer checks every
0.25 s whether that job is over and starts the next camera, and two render handlers only note whether the job
completed or was cancelled (they run on the render thread). Timer and handlers exist only while a sequence runs.
"""

import os

import bpy
from bpy.props import BoolProperty, StringProperty

from .. import live_refs, results

PROP = "allset_renderable"
STORE = "allset_renderable_on"      # the stored value (ID property of the camera data); unset = the camera's default
_BAD = '<>:"/\\|?*'
_INTERVAL = 0.25
# the running sequence: jobs still waiting [(camera name, output path)], what to put back, flags from the handlers
_run = {"jobs": [], "restore": None, "scene": "", "window": 0, "cancelled": False, "completed": False, "done": 0}
# while the Renderable rows draw: the startup top / front / side cameras' data, found once for all the rows
_drawing = []


# --- renderable cameras -----------------------------------------------------------------------------------------

def _startup_data():
    """Pointers of the startup top / front / side cameras' data (one pass over the objects)."""
    from . import startup_cameras
    return {ob.data.as_pointer() for ob in bpy.data.objects
            if ob.type == 'CAMERA' and ob.data is not None and startup_cameras.is_startup(ob)
            and ob.get(startup_cameras.MARK) != "persp"}


def default_renderable(cam):
    """Renderable of a camera never set: on, except the startup top / front / side cameras."""
    return cam.as_pointer() not in (_drawing[-1] if _drawing else _startup_data())


def _renderable_get(cam):
    value = cam.get(STORE)
    return default_renderable(cam) if value is None else bool(value)


def _renderable_set(cam, value):
    cam[STORE] = bool(value)


def is_renderable(ob):
    return ob is not None and ob.type == 'CAMERA' and ob.data is not None and bool(getattr(ob.data, PROP, True))


def _order(ob):
    from . import render_persp, startup_cameras
    if startup_cameras.is_startup(ob):
        return (0, startup_cameras.NAMES.index(ob.get(startup_cameras.MARK)), "")
    if render_persp.is_persp(ob):
        return (0, 0, "")
    return (1, 0, ob.name)


def candidates(scene):
    """The cameras a sequence can render: the startup cameras in Maya's order, persp, then the others by name."""
    from . import render_persp
    obs = [ob for ob in scene.objects if ob.type == 'CAMERA' and ob.data is not None]
    persp = render_persp.persp_camera(create=False)
    if persp is not None and persp not in obs and persp.data is not None:
        obs.append(persp)          # the kit persp is in no collection
    return sorted(obs, key=_order)


def renderable_cameras(scene):
    return [ob for ob in candidates(scene) if is_renderable(ob)]


def draw_settings(layout, scene):
    """Maya's Render Settings > Common values that Render Sequence uses: Skip existing frames (Frame Range) and each
    camera's Renderable check (Renderable Cameras). They are scene data: a change applies at once."""
    from .. import i18n
    layout.column(heading=i18n.mark("Frame Range")).prop(scene, "allset_skip_existing", text="Skip existing frames")
    col = layout.column(heading=i18n.mark("Renderable Cameras"), align=True)
    cams = candidates(scene)
    if not cams:
        col.label(text="(none)")
    _drawing.append(_startup_data())       # each row reads its check while it is made
    try:
        for ob in cams:
            col.prop(ob.data, PROP, text=ob.name)
    finally:
        _drawing.pop()


# --- output paths -----------------------------------------------------------------------------------------------

def folder_name(name):
    """A camera name usable as one folder name."""
    clean = "".join("_" if c in _BAD or ord(c) < 32 else c for c in name).strip(" .")
    return clean or "camera"


def camera_output(filepath, name):
    """Render output path ``filepath`` with a folder for camera ``name`` before its file name part."""
    i = max(filepath.rfind("/"), filepath.rfind("\\"))
    sep = filepath[i] if i >= 0 else "/"
    return f"{filepath[:i + 1]}{folder_name(name)}{sep}{filepath[i + 1:]}"


def alternate_path(scene, folder):
    """The output path with its folder replaced by ``folder`` (the file name part is kept)."""
    return os.path.join(bpy.path.abspath(folder), bpy.path.basename(scene.render.filepath) or "")


def plan(scene, base_path):
    """[(camera, output path)] of an All Render-Enabled Cameras sequence."""
    cams = renderable_cameras(scene)
    if len(cams) <= 1:
        return [(ob, base_path) for ob in cams]
    return [(ob, camera_output(base_path, ob.name)) for ob in cams]


# --- the sequence -----------------------------------------------------------------------------------------------

def running():
    return bpy.app.timers.is_registered(_tick)


def _saver(scene):
    """Put the scene's render camera and output path back (looked up by name: safe after undo)."""
    name, path = scene.name, scene.render.filepath
    cam = scene.camera.name if scene.camera is not None else ""

    def restore():
        sc = bpy.data.scenes.get(name)
        if sc is None:
            return
        sc.render.filepath = path
        sc.camera = bpy.data.objects.get(cam) if cam else None
    return restore


def _setup(scene, ob, path):
    scene.camera = ob
    scene.render.filepath = path


def _on_cancel(*_args):
    _run["cancelled"] = True        # (render thread: only a flag)


def _on_complete(*_args):
    _run["completed"] = True        # (render thread: only a flag)


def _handlers(add):
    for lst, fn in ((bpy.app.handlers.render_cancel, _on_cancel), (bpy.app.handlers.render_complete, _on_complete)):
        if add and fn not in lst:
            lst.append(fn)
        elif not add and fn in lst:
            lst.remove(fn)


def _launch(scene):
    """Start Blender's render job of the frame range for the scene's current camera; False when it didn't start."""
    window = live_refs.window(_run["window"]) or (live_refs.windows() or [None])[0]
    if window is None:
        return False
    try:
        with bpy.context.temp_override(window=window, scene=scene):
            res = bpy.ops.render.render('INVOKE_DEFAULT', animation=True, scene=scene.name)
    except RuntimeError:
        return False
    return 'CANCELLED' not in res


def _start_next():
    """Start the next camera's render job; False (and the sequence ends) when none is left or it didn't start."""
    scene = bpy.data.scenes.get(_run["scene"])
    while scene is not None and _run["jobs"] and not _run["cancelled"]:
        name, path = _run["jobs"].pop(0)
        ob = bpy.data.objects.get(name)
        if ob is None or ob.type != 'CAMERA':
            continue
        _setup(scene, ob, path)
        _run["completed"] = False
        if not _launch(scene):
            break
        _run["done"] += 1
        return True
    _finish()
    return False


def _tick():
    if bpy.app.is_job_running('RENDER'):
        return _INTERVAL
    # the job is over: a cancel, or an end without Blender's render-complete call (an error), stops the sequence
    if _run["cancelled"] or not _run["completed"] or not _run["jobs"]:
        _finish()
        return None
    return _INTERVAL if _start_next() else None


def _finish():
    _run["jobs"] = []
    restore, _run["restore"] = _run["restore"], None
    if restore is not None:
        try:
            restore()
        except (ReferenceError, RuntimeError, AttributeError):
            pass
    _handlers(False)
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)


def stop():
    """End a running sequence now (the render job already running goes on)."""
    _finish()


def begin(context, jobs):
    """Render ``jobs`` [(camera, output path)] one render job after another; False when the first didn't start."""
    scene = context.scene
    _run.update(jobs=[(ob.name, path) for ob, path in jobs], restore=_saver(scene), scene=scene.name,
                window=live_refs.pointer(context.window), cancelled=False, completed=False, done=0)
    _handlers(True)
    if not _start_next():
        return False
    bpy.app.timers.register(_tick, first_interval=_INTERVAL)
    return True


def _render_now(op, scene, jobs):
    """Render ``jobs`` one after another and wait for each (scripts, background Blender)."""
    restore = _saver(scene)
    try:
        for ob, path in jobs:
            _setup(scene, ob, path)
            if 'CANCELLED' in bpy.ops.render.render('EXEC_DEFAULT', animation=True):
                return False
    except RuntimeError as ex:
        op.report({'ERROR'}, str(ex))
        return False
    finally:
        restore()
    return True


def _place_persp(context, scene, cams):
    """persp renders from where the view looks (Maya's persp camera is the view), unless the view is a camera's."""
    from . import render_persp
    space, rv3d = render_persp.find_view(context)
    if rv3d is None or rv3d.view_perspective == 'CAMERA':
        return
    for ob in cams:
        if render_persp.is_persp(ob):
            render_persp.match_view(ob, space, rv3d, scene)


class ALLSET_OT_render_sequence(bpy.types.Operator):
    """Render the frame range like Maya's Render > Render Sequence: through the scene camera (without one: persp,
    placed where the view looks from), or with All Render-Enabled Cameras through every Renderable camera, each into
    its own folder"""
    bl_idname = "allset.render_sequence"
    bl_label = "Render Sequence"
    bl_options = {'REGISTER'}

    camera: StringProperty(name="Camera", default="", options={'SKIP_SAVE', 'HIDDEN'})
    output: StringProperty(name="Output", default="", options={'SKIP_SAVE', 'HIDDEN'})
    all_cameras: BoolProperty(name="All Render-Enabled Cameras", default=False, options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def _render(self, context, how):
        from . import film_fit, render_persp
        scene = context.scene
        if running() or bpy.app.is_job_running('RENDER'):
            self.report({'WARNING'}, "A render is already running")
            return {'CANCELLED'}
        base = alternate_path(scene, self.output) if self.output else scene.render.filepath
        if self.all_cameras:
            cams = renderable_cameras(scene)
            if not cams:
                self.report({'WARNING'}, "No renderable cameras: turn on Renderable for a camera")
                return {'CANCELLED'}
            _place_persp(context, scene, cams)
            jobs = plan(scene, base)
        else:
            picked = bpy.data.objects.get(self.camera) if self.camera else None
            if picked is None or picked.type != 'CAMERA':
                if not self.output:
                    return bpy.ops.allset.render(how, animation=True)      # the plain Render Sequence
                picked = render_persp.render_camera(context) if render_persp.needs_camera(scene) else scene.camera
            jobs = [(picked, base)]
        film_fit.sync(scene)        # Fill / Overscan cameras fit this render's shape (Fit Resolution Gate)
        names = ", ".join(ob.name for ob, _path in jobs)
        if how == 'INVOKE_DEFAULT' and context.window is not None and not bpy.app.background:
            if not begin(context, jobs):
                return {'CANCELLED'}
            results.result(self, f"Rendering through {names}")
            return {'FINISHED'}
        if not _render_now(self, scene, jobs):
            return {'CANCELLED'}
        results.result(self, f"Rendered through {names}")
        return {'FINISHED'}

    def invoke(self, context, event):
        return self._render(context, 'INVOKE_DEFAULT')

    def execute(self, context):
        return self._render(context, 'EXEC_DEFAULT')


# --- Skip existing frames ---------------------------------------------------------------------------------------

def _skip_get(scene):
    return not scene.render.use_overwrite


def _skip_set(scene, value):
    scene.render.use_overwrite = not value
    scene.render.use_placeholder = bool(value)


classes = (ALLSET_OT_render_sequence,)


def register_props():
    bpy.types.Camera.allset_renderable = BoolProperty(
        name="Renderable", get=_renderable_get, set=_renderable_set,
        description="Render Sequence with All Render-Enabled Cameras renders this camera (like Maya)")
    bpy.types.Scene.allset_skip_existing = BoolProperty(
        name="Skip existing frames", get=_skip_get, set=_skip_set,
        description="Animation renders leave frames whose image already exists and mark the frame being rendered "
                    "with an empty file, so a render can resume and several computers can share a frame range "
                    "(Blender's Overwrite off, Placeholders on)")


def unregister_props():
    try:
        _finish()
    except AttributeError:          # restricted context while Blender quits
        _run.update(jobs=[], restore=None)
    del bpy.types.Scene.allset_skip_existing
    del bpy.types.Camera.allset_renderable
