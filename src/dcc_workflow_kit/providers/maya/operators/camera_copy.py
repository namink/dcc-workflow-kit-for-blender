# SPDX-License-Identifier: GPL-3.0-or-later
"""View > Create Camera From View (Ctrl+Shift+C): a copy of the camera the view looks through, like Maya.

Maya copies the view's camera: every camera setting (Fit Resolution Gate, film back, focal length or orthographic
width, Overscan, near / far clip, film offset, Renderable ...) and its place in the world. The copy is named after
that camera with the next free number (persp -> persp1, top -> top1, shot3 -> shot4) and its shape ``<name>Shape``;
the view then looks through the copy, the selection stays as it was, and it is one undo step.

The persp / top / front / side views of the Maya layout are Blender's own views, not camera objects. Their camera is
the scene's startup camera of that view (its settings; a new scene camera's when the scene has none) seen from where
the view looks: the view's focal length (Blender's viewport lens is on a 72 mm sensor) and clip planes, or for an
orthographic view its width. An orthographic copy sits 1000.1 units out like Maya's top / front / side cameras, so
it sees everything the view shows. Blender's bottom / back / left views give bottom1 / back1 / left1, a view along
no axis persp1.
"""

import bpy
from mathutils import Matrix, Vector

from . import film_fit, framing, naming, render_cameras, startup_cameras, units
from .key_batch import VIEW_SENSOR, camera_matrix

ORTHO_DISTANCE = 1000.1          # Maya's top / front / side cameras sit this far out from the origin
# the direction an orthographic view looks (Blender world) -> its Maya camera name
SIDES = (("top", (0.0, 0.0, -1.0)), ("bottom", (0.0, 0.0, 1.0)), ("front", (0.0, 1.0, 0.0)),
         ("back", (0.0, -1.0, 0.0)), ("side", (-1.0, 0.0, 0.0)), ("left", (1.0, 0.0, 0.0)))


def view_name(rv3d):
    """Maya camera name of a Blender view: top / bottom / front / back / side / left for an orthographic view along
    an axis, else persp."""
    if rv3d.view_perspective != 'ORTHO':
        return "persp"
    forward = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
    return next((name for name, axis in SIDES if forward.dot(Vector(axis)) > 0.999), "persp")


def base_of(ob):
    """The name a copy of camera ``ob`` is numbered from: ``persp1`` -> persp, ``Camera.001`` -> Camera."""
    return ob.get(startup_cameras.MARK) or naming.base_name(ob.name)


def ortho_eye(centre, forward, distance):
    """Where an orthographic camera looking along ``forward`` at ``centre`` sits: on its view axis, ``distance`` out
    from the plane through the world origin (Maya's top camera: 1000.1 up, over wherever the view is panned)."""
    forward, centre = Vector(forward).normalized(), Vector(centre)
    return centre - forward * (centre.dot(forward) + distance)


def copy_name(base):
    """Maya's name of a copy: ``base`` + one past the highest number in use, also free as ``<name>Shape``."""
    naming.drop_orphans(bpy.data.objects, base)
    taken = {o.name for o in bpy.data.objects}
    shapes = {d.name for d in bpy.data.cameras if not naming.orphan(d)}
    n = naming.next_number(base, taken)
    while f"{base}{n}" in taken or f"{base}{n}Shape" in shapes:
        n += 1
    stale = bpy.data.cameras.get(f"{base}{n}Shape")
    if stale is not None:            # left by a deleted camera: Blender drops it on save anyway
        bpy.data.cameras.remove(stale)
    return f"{base}{n}"


def _startup_data(scene, name):
    ob = next((o for o in startup_cameras.cameras(scene) if o.get(startup_cameras.MARK) == name), None)
    return ob.data if ob is not None else None


def _new_data(scene):
    """The settings of a new scene's camera: 35 mm on a 36 x 24 mm film back, Fit Horizontal, Maya clip planes."""
    data = bpy.data.cameras.new("cameraShape")
    data.lens = startup_cameras.MAYA_LENS
    data.sensor_width, data.sensor_height = startup_cameras.MAYA_FILM_MM, startup_cameras.MAYA_FILM_H_MM
    film_fit.set_fit(data, 'HORIZONTAL', scene)
    clip = units.clip(scene)
    data.clip_start, data.clip_end = clip["clip_start"], clip["clip_end"]
    return data


def _place_from_view(ob, space, rv3d, unit):
    data = ob.data
    if rv3d.view_perspective == 'ORTHO':
        data.type = 'ORTHO'
        data.ortho_scale = rv3d.view_distance * VIEW_SENSOR / space.lens       # what the view shows across
        forward = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
        eye = ortho_eye(rv3d.view_location, forward, ORTHO_DISTANCE * unit)
        ob.matrix_world = Matrix.LocRotScale(eye, rv3d.view_rotation, None)
    else:
        data.type = 'PERSP'
        data.lens = space.lens * data.sensor_width / VIEW_SENSOR
        data.clip_start, data.clip_end = space.clip_start, space.clip_end
        # from view_location / rotation / distance: rv3d.view_matrix is only recomputed when the view draws
        ob.matrix_world = camera_matrix(framing.view_matrix(rv3d.view_location, rv3d.view_rotation,
                                                            rv3d.view_distance))


def make(context, space, rv3d, source, maya_naming=True):
    """The copy of the view's camera, linked to the active collection and not selected; ``source`` = the object the
    view looks through, None for a Blender persp / orthographic view."""
    scene = context.scene
    unit = units.maya_unit(scene)
    if source is not None:
        base = base_of(source)
        settings = source.data if source.type == 'CAMERA' else None
    else:
        base = view_name(rv3d)
        settings = _startup_data(scene, base)
    if settings is not None:
        data = settings.copy()
        # Renderable as the source's (a startup top / front / side camera's is off, a copy's would be on)
        data[render_cameras.STORE] = bool(getattr(settings, render_cameras.PROP, True))
        if data.animation_data is not None:
            data.animation_data_clear()             # the copy keeps the values it has now
    else:
        data = _new_data(scene)
    if settings is None or source is None or startup_cameras.is_startup(source):
        data.display_size = unit                    # the hidden startup cameras keep Blender's 1 m size
    name = copy_name(base) if maya_naming else base
    data.name = f"{name}Shape" if maya_naming else name
    ob = bpy.data.objects.new(name, data)
    context.collection.objects.link(ob)
    if source is not None:
        ob.matrix_world = source.matrix_world.copy()
    else:
        _place_from_view(ob, space, rv3d, unit)
    return ob
