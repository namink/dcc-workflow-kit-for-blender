# SPDX-License-Identifier: GPL-3.0-or-later
"""Option boxes of the Render menu.

- Render > Render Sequence ❒ = Maya's "Render Sequence (Current Frame)" window: Current Camera (the default renders
  like the plain menu item: the scene camera, else persp placed where the view looks from), All Render-Enabled
  Cameras (every Renderable camera, each into its own folder; operators/render_cameras.py) and Alternate Output File
  Location (another folder for this sequence only). Under the fields the window shows the Render Settings values the
  sequence uses: each camera's Renderable check and Skip existing frames (scene data, changed at once). The other
  Maya fields have no Blender part.
- Render Current Frame / Batch Render run Blender's own render and have no kit window. Render Current Frame ❒ / IPR
  Render Current Frame ❒ open no window in Maya either: the Help Line reads 'Renderer "<name>" does not provide
  render options.' — ``NO_OPTIONS`` (option_windows.ALLSET_OT_option_generic).

``WINDOWS`` is appended by option_windows._extend.
"""

import bpy
from bpy.props import EnumProperty, StringProperty

from .option_windows import F, Window

# Maya's warning for an option box its renderer has no window for; {name} = the render engine
NO_OPTIONS = {"Render/Render Current Frame": 'Renderer "{name}" does not provide render options.',
              "Render/IPR Render Current Frame": 'Renderer "{name}" does not provide IPR options.'}
ENGINE_NAMES = {'BLENDER_EEVEE_NEXT': "EEVEE", 'BLENDER_EEVEE': "EEVEE", 'CYCLES': "Cycles",
                'BLENDER_WORKBENCH': "Workbench"}


def engine_name(scene):
    return ENGINE_NAMES.get(scene.render.engine, scene.render.engine.title())


def no_options_text(path, scene):
    """Maya's Help Line warning for ``path``'s option box, or None when it has a window."""
    text = NO_OPTIONS.get(path)
    return text.format(name=engine_name(scene)) if text else None



_ITEMS = []     # the Current Camera items (kept: Blender reads the strings after the callback returns)


def _cameras(_self, context):
    """Maya's Current Camera combo: the camera of the plain Render Sequence first, then the scene's cameras."""
    from . import render_cameras, render_persp
    scene = getattr(context, "scene", None)
    first = "persp"
    if scene is not None and not render_persp.needs_camera(scene):
        first = f"{scene.camera.name} (scene camera)"
    items = [("persp", first, "The camera of the plain Render Sequence: the scene camera, else persp placed where "
                              "the view looks from")]
    for ob in render_cameras.candidates(scene) if scene is not None else ():
        if not render_persp.is_persp(ob):
            items.append((ob.name, ob.name, ""))
    _ITEMS[:] = items
    return _ITEMS


class FCamera(F):
    """Maya's Current Camera combo (items read when the window draws)."""

    def __init__(self, name, label):
        super().__init__(name, label, "camera", "persp")

    def prop(self):
        return EnumProperty(name=self.label.rstrip(":"), items=_cameras)


class FPath(F):
    """A folder field (Maya: text field + folder button)."""

    def __init__(self, name, label):
        super().__init__(name, label, "path", "")

    def prop(self):
        return StringProperty(name=self.label.rstrip(":"), default="", subtype='DIR_PATH')


def _run_sequence(context, v):
    camera = v.get("camera") or "persp"
    return bpy.ops.allset.render_sequence('INVOKE_DEFAULT', camera="" if camera == "persp" else camera,
                                          output=v.get("output") or "", all_cameras=bool(v.get("all_cameras")))


def _sequence_enabled(values, name):
    """Current Camera is greyed while All Render-Enabled Cameras is on (like Maya)."""
    return not (name == "camera" and bool(values.get("all_cameras")))


def _draw_render_settings(layout, context):
    """The Render Settings values the sequence uses (the same rows as Render Settings > Common)."""
    from . import render_cameras
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    box = layout.box()
    box.label(text="Render Settings", icon='SCENE_DATA')
    render_cameras.draw_settings(box, scene)


WINDOWS = [
    Window("render_sequence", "Render Sequence (Current Frame)", "Render Sequence and Close",
           ("allset.render_sequence", {}), [
               FCamera("camera", "Current Camera:"),
               F("all_cameras", "", "bool", False, text="All Render-Enabled Cameras"),
               FPath("output", "Alternate Output File Location:")], _run_sequence, paths=("Render/Render Sequence",),
           apply_text="Render Sequence", enabled=_sequence_enabled, extra=_draw_render_settings,
           missing=("All Render-Enabled Layers", "Render Region", "Ignore Local Overrides",
                    "Render View Options: Add to Render View")),
]
