# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya camera Fit Resolution Gate (#345): how the render frame sits on the camera's film back.

Maya draws two gates in a view that looks through a camera: the film gate is the film back (Horizontal x Vertical
Film Aperture), the resolution gate is the render frame (the render's width : height) and is what renders. Fit
Resolution Gate places the resolution gate on the film gate: Fill fits it inside the film gate (as wide as the film
gate when the render is wider than the film back, else as tall), Horizontal makes it as wide, Vertical as tall, and
Overscan fits the film gate inside it. Maya cameras have a 36 x 24 mm film back; a camera made with Create > Cameras
starts with Fill, the persp / top / front / side cameras of a new scene and the ``camera`` command start with
Horizontal.

Blender renders the camera frame by Sensor Fit: Horizontal / Vertical match the frame's width / height to Sensor
Width / Height; Auto matches the frame's longer side to Sensor Width and doesn't use Sensor Height (the sensor frame a
camera view draws is then a square). ``Camera.allset_film_fit`` keeps Maya's choice and sets Blender's Sensor Fit to
Horizontal or Vertical from it, so Blender's camera frame (the render) is Maya's resolution gate and Blender's sensor
frame (the kit's Film Gate) is Maya's film gate. Fill and Overscan depend on the render's shape: the kit sets Sensor
Fit again when the render size, pixel aspect, film back or the window's scene changes (msgbus), after a file load,
undo and redo, and before a kit render. A Sensor Fit changed in Blender's own camera properties wins: the camera then
shows that fit (Auto, Horizontal or Vertical). Cameras the kit doesn't make keep their Sensor Fit until a fit is
picked for them.
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import EnumProperty

from .. import i18n

PROP = "allset_film_fit"
STATE = "allset_film_fit_state"
DYNAMIC = ('FILL', 'OVERSCAN')       # the fitted side follows the render's shape
SIDES = ('HORIZONTAL', 'VERTICAL')

# item names Blender / the kit's tables already translate; the tooltips are marked for the translation tables
FITS = [
    ('FILL', "Fill", i18n.mark("The resolution gate (the render) fits inside the film gate: as wide as the film gate "
                               "when the render is wider than the film back, else as tall. Cameras made with "
                               "Create > Cameras start with it, like Maya"), 0),
    ('HORIZONTAL', "Horizontal", i18n.mark("The resolution gate (the render) is as wide as the film gate. The persp, "
                                           "top, front and side cameras of a new scene start with it, like Maya"), 1),
    ('VERTICAL', "Vertical", i18n.mark("The resolution gate (the render) is as tall as the film gate"), 2),
    ('OVERSCAN', "Overscan", i18n.mark("The film gate fits inside the resolution gate (the render)"), 3),
    ('AUTO', "Auto", i18n.mark("Blender's own fit: the render's longer side matches Horizontal Film Aperture and "
                               "Vertical Film Aperture isn't used (the film gate is drawn square)"), 4),
]
_INDEX = {f[0]: f[3] for f in FITS}
_NAMES = {f[3]: f[0] for f in FITS}
# the kit's Fill / Overscan with the Sensor Fit it last set (a different Sensor Fit = changed in Blender: it wins)
_STATES = ['NONE'] + [f"{mode}_{side}" for mode in DYNAMIC for side in SIDES]


# --- Maya's rule -------------------------------------------------------------------------------------------------

def render_aspect(scene):
    """Width : height of the render frame (pixel aspect included, like Blender's camera)."""
    r = scene.render
    return (r.resolution_x * r.pixel_aspect_x) / max(r.resolution_y * r.pixel_aspect_y, 1e-9)


def film_aspect(data):
    return data.sensor_width / max(data.sensor_height, 1e-9)


def fitted_side(fit, film, render):
    """'HORIZONTAL' / 'VERTICAL': the side of the resolution gate that is as long as the film gate's."""
    if fit == 'FILL':
        return 'HORIZONTAL' if render >= film else 'VERTICAL'
    if fit == 'OVERSCAN':
        return 'VERTICAL' if render >= film else 'HORIZONTAL'
    return fit


def gates(hfa, vfa, fit, aspect):
    """Maya's gates on the film back: ((resolution gate width, height), (film gate width, height)), in the units of
    ``hfa`` / ``vfa`` (Horizontal / Vertical Film Aperture); ``aspect`` = the render's width : height."""
    if fitted_side(fit, hfa / max(vfa, 1e-9), aspect) == 'HORIZONTAL':
        res = (hfa, hfa / aspect)
    else:
        res = (vfa * aspect, vfa)
    return res, (hfa, vfa)


# --- the camera's fit --------------------------------------------------------------------------------------------

def _dynamic(data):
    """(mode, side) of a Fill / Overscan camera the kit still fits, else None."""
    state = getattr(data, STATE, 'NONE')
    if state == 'NONE':
        return None
    mode, side = state.split("_", 1)
    return (mode, side) if data.sensor_fit == side else None


def fit_of(data):
    """Maya's Fit Resolution Gate the camera renders with ('AUTO' = Blender's Auto Sensor Fit)."""
    got = _dynamic(data)
    if got is not None:
        return got[0]
    return data.sensor_fit if data.sensor_fit in SIDES else 'AUTO'


def _set_state(data, state):
    # The state property exists only while Maya mode is on; a new Maya scene can be made with it off (the start-up
    # layout), and then Blender's Sensor Fit alone carries the fit.
    if getattr(data, STATE, state) != state:
        setattr(data, STATE, state)


def _write(data, mode, side):
    if data.sensor_fit != side:
        data.sensor_fit = side
    _set_state(data, f"{mode}_{side}" if mode in DYNAMIC else 'NONE')


def set_fit(data, fit, scene=None):
    """Give camera data ``data`` Maya's Fit Resolution Gate ``fit`` (Blender's Sensor Fit follows; Fill / Overscan
    by the render shape of ``scene``, the current scene by default)."""
    if fit in DYNAMIC:
        scene = scene or bpy.context.scene
        aspect = render_aspect(scene) if scene is not None else 16.0 / 9.0
        _write(data, fit, fitted_side(fit, film_aspect(data), aspect))
    elif fit in SIDES:
        _write(data, fit, fit)
    else:
        _set_state(data, 'NONE')
        if data.sensor_fit != 'AUTO':
            data.sensor_fit = 'AUTO'


def sync(scene=None):
    """Set Sensor Fit again on every Fill / Overscan camera for the render shape of ``scene`` (the current scene by
    default). Returns the cameras that changed."""
    scene = scene or bpy.context.scene
    if scene is None:
        return []
    aspect = render_aspect(scene)
    changed = []
    for data in bpy.data.cameras:
        state = getattr(data, STATE, 'NONE')
        if state == 'NONE' or data.library is not None:
            continue
        mode, side = state.split("_", 1)
        if data.sensor_fit != side:         # Sensor Fit changed in Blender's camera properties: it wins
            setattr(data, STATE, 'NONE')
            continue
        new = fitted_side(mode, film_aspect(data), aspect)
        if new != side:
            _write(data, mode, new)
            changed.append(data)
    return changed


def _get(self):
    return _INDEX[fit_of(self)]


def _set(self, value):
    set_fit(self, _NAMES.get(value, 'FILL'))


# --- keeping Fill / Overscan up to date --------------------------------------------------------------------------

_OWNER = object()
_KEYS = ((bpy.types.RenderSettings, "resolution_x"), (bpy.types.RenderSettings, "resolution_y"),
         (bpy.types.RenderSettings, "pixel_aspect_x"), (bpy.types.RenderSettings, "pixel_aspect_y"),
         (bpy.types.Camera, "sensor_width"), (bpy.types.Camera, "sensor_height"), (bpy.types.Window, "scene"))


def _on_change(*_args):
    try:
        sync()
    except (AttributeError, ReferenceError, RuntimeError):
        pass


def _subscribe():
    bpy.msgbus.clear_by_owner(_OWNER)
    for key in _KEYS:
        bpy.msgbus.subscribe_rna(key=key, owner=_OWNER, args=(), notify=_on_change)


@persistent
def _on_load(*_args):
    _on_change()
    _subscribe()         # a file load clears msgbus subscriptions


@persistent
def _on_undo(*_args):
    _on_change()


_HANDLERS = (("load_post", _on_load), ("undo_post", _on_undo), ("redo_post", _on_undo))


def register_props():
    bpy.types.Camera.allset_film_fit_state = EnumProperty(
        items=[(s, s.replace("_", " ").title(), "") for s in _STATES], default='NONE', options={'HIDDEN'})
    bpy.types.Camera.allset_film_fit = EnumProperty(
        name="Fit Resolution Gate", items=FITS, get=_get, set=_set,
        description="How the resolution gate (the render) sits on the film gate (the film back), like Maya; "
                    "Blender's Sensor Fit follows")
    for name, fn in _HANDLERS:
        getattr(bpy.app.handlers, name).append(fn)
    _subscribe()


def unregister_props():
    bpy.msgbus.clear_by_owner(_OWNER)
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name)
        if fn in lst:
            lst.remove(fn)
    for prop in (PROP, STATE):
        if hasattr(bpy.types.Camera, prop):
            delattr(bpy.types.Camera, prop)
