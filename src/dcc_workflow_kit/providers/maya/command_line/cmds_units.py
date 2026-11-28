# SPDX-License-Identifier: GPL-3.0-or-later
"""maya.cmds look-alike: ``currentUnit``. The working units are the scene's display units: linear = the scene
length unit (``LINEAR``; Blender has no yard), angle = the rotation unit (``ANGLE``), time = the frame rate
(``TIME`` names or ``<n>fps``). A new time unit keeps the time ranges in seconds, rounded to whole frames
(``_set_fps``). Re-exported by cmds_misc.py for cmds_shim.py."""

import re

import bpy

from .cmds_shim import _Flags

# --- currentUnit -----------------------------------------------------------------------------------------------------

# Maya linear unit -> (full name, Blender length unit, unit system); Blender has no yard
LINEAR = {"mm": ("millimeter", 'MILLIMETERS', 'METRIC'), "cm": ("centimeter", 'CENTIMETERS', 'METRIC'),
          "m": ("meter", 'METERS', 'METRIC'), "km": ("kilometer", 'KILOMETERS', 'METRIC'),
          "in": ("inch", 'INCHES', 'IMPERIAL'), "ft": ("foot", 'FEET', 'IMPERIAL'),
          "mi": ("mile", 'MILES', 'IMPERIAL')}
_LINEAR_BY_UNIT = {v[1]: k for k, v in LINEAR.items()}
ANGLE = {"deg": ("degree", 'DEGREES'), "rad": ("radian", 'RADIANS')}
# Maya time units (frames per second); "<n>fps" names work too
TIME = {"game": 15.0, "film": 24.0, "pal": 25.0, "ntsc": 30.0, "show": 48.0, "palf": 50.0, "ntscf": 60.0,
        "sec": 1.0, "millisec": 1000.0, "23.976fps": 24000 / 1001, "29.97fps": 30000 / 1001,
        "29.97df": 30000 / 1001, "47.952fps": 48000 / 1001, "59.94fps": 60000 / 1001}
_FPS = re.compile(r"^(\d+(?:\.\d+)?)fps$")


def _linear_key(text):
    text = str(text)
    if text in LINEAR:
        return text
    found = next((k for k, v in LINEAR.items() if v[0] == text), None)
    if found is None:
        raise RuntimeError(f"currentUnit: unknown or unsupported linear unit '{text}' (Blender has no yard)")
    return found


def _current_linear(scene):
    us = scene.unit_settings
    if us.system == 'NONE':
        return "cm"      # 1 BU = 1 Maya unit, cm
    if us.length_unit == 'ADAPTIVE':
        return "m" if us.system == 'METRIC' else "ft"
    return _LINEAR_BY_UNIT.get(us.length_unit, "cm")


def _fps(scene):
    return scene.render.fps / (scene.render.fps_base or 1.0)


def _time_name(fps):
    found = next((k for k, v in TIME.items() if abs(v - fps) < 1e-3 and not k.endswith("df")), None)
    return found or f"{fps:g}fps"


def _time_fps(text):
    text = str(text)
    if text in TIME:
        return TIME[text]
    m = _FPS.match(text)
    if m:
        return float(m.group(1))
    raise RuntimeError(f"currentUnit: unknown or unsupported time unit '{text}'")


def _set_range(scene, start_attr, end_attr, start, end):
    """Set a Blender frame range without Blender pushing the other end (start <= end)."""
    setattr(scene, end_attr, max(end, start, getattr(scene, start_attr)))
    setattr(scene, start_attr, start)
    setattr(scene, end_attr, max(end, start))


def _set_fps(scene, fps):
    """Maya keeps the time ranges in seconds when the time unit changes, so the frame numbers scale with
    the rate; Blender frames are whole, so the kit rounds (keys stay where they are)."""
    old = _fps(scene)
    ratio = fps / old if old else 1.0
    r = scene.render
    r.fps = max(1, int(round(fps)))
    r.fps_base = r.fps / fps
    if abs(ratio - 1.0) < 1e-9:
        return
    sc = scene
    _set_range(sc, "frame_start", "frame_end", int(round(sc.frame_start * ratio)), int(round(sc.frame_end * ratio)))
    _set_range(sc, "frame_preview_start", "frame_preview_end", int(round(sc.frame_preview_start * ratio)),
               int(round(sc.frame_preview_end * ratio)))
    sc.frame_set(int(round((sc.frame_current + sc.frame_subframe) * ratio)))


def currentUnit(*args, **kwargs):
    """Maya working units = the scene's display units: linear = ``unit_settings.length_unit`` (the kit's numbers
    follow it: 100 cm reads 1.0 in m), angle = ``system_rotation``, time = the frame rate. Setting returns the full
    linear / angle name or the time name; a multi-flag set returns the last one's."""
    f = _Flags("currentUnit", kwargs)
    query = f.get("query", "q", False)
    linear = f.get("linear", "l")
    angle = f.get("angle", "a")
    time = f.get("time", "t")
    full = f.get("fullName", "f", False)
    f.get("updateAnimation", "ua", True)
    f.done()
    if args:
        raise TypeError("currentUnit takes no objects")
    scene = bpy.context.scene
    if query:
        if angle:
            key = "rad" if scene.unit_settings.system_rotation == 'RADIANS' else "deg"
            return ANGLE[key][0] if full else key
        if time:
            return _time_name(_fps(scene))
        key = _current_linear(scene)
        return LINEAR[key][0] if full else key
    result = None
    if linear is not None:
        key = _linear_key(linear)
        full_name, unit, system = LINEAR[key]
        us = scene.unit_settings
        if us.system != system:
            us.system = system
        us.length_unit = unit
        result = full_name
    if angle is not None:
        key = str(angle)
        key = key if key in ANGLE else next((k for k, v in ANGLE.items() if v[0] == key), None)
        if key is None:
            raise RuntimeError(f"currentUnit: unknown angle unit '{angle}'")
        scene.unit_settings.system_rotation = ANGLE[key][1]
        result = ANGLE[key][0]
    if time is not None:
        _set_fps(scene, _time_fps(time))
        result = _time_name(_fps(scene))
    return result
