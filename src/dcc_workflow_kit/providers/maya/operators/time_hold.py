# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Time Slider MMB: move the time without updating the scene.

In Maya a middle-mouse click or drag on the Time Slider changes the current time but leaves every animated
attribute at the value it had, so the pose can be keyed at another frame with S. Blender always evaluates the
animation when the frame changes, so the kit takes a snapshot of every animated channel when the button goes
down and writes it back after each frame change. The values then stay until the next ordinary time change,
like Maya's.
"""
import bpy

from .. import compat

# bpy.data collections whose IDs can carry animation
ID_COLLECTIONS = ("scenes", "worlds", "objects", "meshes", "curves", "armatures", "cameras", "lights",
                  "materials", "shape_keys", "lattices", "node_groups", "textures", "metaballs", "speakers",
                  "lightprobes", "grease_pencils", "hair_curves", "pointclouds", "volumes", "particles")


def split_path(path):
    """(parent path, kind, name) of an RNA data path: kind 'attr' (name = attribute), 'key' (string key, e.g. an
    ID property or a named collection item) or 'index' (int). The parent path is '' for the ID itself."""
    quote, depth, dot, bracket = None, 0, -1, -1
    i = 0
    while i < len(path):
        c = path[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "[":
            if depth == 0:
                bracket = i
            depth += 1
        elif c == "]":
            depth -= 1
        elif c == "." and depth == 0:
            dot = i
        i += 1
    if path.endswith("]") and bracket > dot:
        inner = path[bracket + 1:-1]
        if inner[:1] in "\"'":
            name = inner[1:-1].replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
            return path[:bracket], "key", name
        return path[:bracket], "index", int(inner)
    return path[:dot] if dot >= 0 else "", "attr", path[dot + 1:]


def _channels(anim_id):
    """(data path, array index) of every F-curve that animates the ID: its action and its NLA strips."""
    ad = anim_id.animation_data
    fcs = list(compat.id_fcurves(anim_id))
    for track in ad.nla_tracks:
        if track.mute:
            continue
        for strip in track.strips:
            if strip.action is not None:
                fcs.extend(compat.action_fcurves(strip.action, getattr(strip, "action_slot", None)))
    return {(fc.data_path, fc.array_index) for fc in fcs}


def _read(anim_id, path, index):
    try:
        value = anim_id.path_resolve(path)
    except (ValueError, AttributeError, TypeError):
        return None
    if isinstance(value, (bool, int, float)):
        return value
    try:
        return value[index]
    except (TypeError, IndexError, KeyError):
        return None


def _write(anim_id, path, index, value):
    if _read(anim_id, path, index) == value:
        return False
    try:
        current = anim_id.path_resolve(path)
        if not isinstance(current, (bool, int, float)):
            current[index] = value          # a live array (location, rotation, colour ...)
            return True
        parent, kind, name = split_path(path)
        owner = anim_id.path_resolve(parent) if parent else anim_id
        if kind == "attr":
            setattr(owner, name, value)
        else:
            owner[name] = value
        return True
    except (ValueError, AttributeError, TypeError, KeyError, IndexError):
        return False


def snapshot():
    """Every animated channel's current value: [(id, data path, index, value)]."""
    out = []
    for attr in ID_COLLECTIONS:
        for anim_id in getattr(bpy.data, attr, ()):
            if getattr(anim_id, "animation_data", None) is None:
                continue
            for path, index in sorted(_channels(anim_id)):
                value = _read(anim_id, path, index)
                if value is not None:
                    out.append((anim_id, path, index, value))
    return out


def restore(snap):
    """Write the snapshot back (only values that changed). Count of channels written."""
    n = 0
    for anim_id, path, index, value in snap:
        try:
            n += _write(anim_id, path, index, value)
        except ReferenceError:      # the ID was removed meanwhile
            pass
    return n


def move_time(scene, frame, snap):
    """Go to ``frame`` without changing the scene: evaluate the frame, then put the held values back."""
    scene.frame_set(int(frame))
    restore(snap)
