# SPDX-License-Identifier: GPL-3.0-or-later
"""Making Set Driven Key curves: Maya auto tangents (``maya_slopes`` / ``maya_auto``), the driver and its curve on a
driven channel (``ensure_driver``, ``set_key``), a second driver turning the channel into a blendWeighted sum whose
inputs sit on one hidden helper Texture (``helper``, ``to_blend``), and the upkeep that keeps them there after
loads, duplicates and deletes (``sync``, ``sync_if_changed``, ``release_all``). Lookups: driven_key_channels.
"""

import bpy

from .driven_key_channels import (HELPER, HELPER_NAME, INPUT_PROP, VAR, Chan, _id_type, _inputs, _reads, _target,
                                  chan, curve_scale, input_value, input_x, is_blend, is_sdk)

from .. import update_summary


# --- curve shape ----------------------------------------------------------------------------------

def maya_slopes(points):
    """Maya 2026 auto tangent slopes of sorted (x, y) keys (driven_key.py module docstring 1): ends and local extremes flat,
    else the neighbours' chord slope; the slope is limited so a handle never passes a neighbour's value (no
    known case reaches the limit)."""
    n = len(points)
    out = [0.0] * n
    for i in range(1, n - 1):
        (x0, y0), (x1, y1), (x2, y2) = points[i - 1], points[i], points[i + 1]
        if (y1 - y0) * (y2 - y1) <= 0.0 or x2 - x0 <= 0.0:
            continue
        s = (y2 - y0) / (x2 - x0)
        lim = min(3.0 * abs(y1 - y0) / max(x1 - x0, 1e-12), 3.0 * abs(y2 - y1) / max(x2 - x1, 1e-12))
        out[i] = max(-lim, min(lim, s))
    return out


def maya_auto(fc):
    """Bezier keys with Maya auto tangents: ALIGNED handles a third of each segment long."""
    kps = fc.keyframe_points
    for kp in kps:
        kp.interpolation = 'BEZIER'
        kp.handle_left_type = kp.handle_right_type = 'ALIGNED'
    fc.update()        # sorts the keys
    pts = [(kp.co[0], kp.co[1]) for kp in kps]
    slopes = maya_slopes(pts)
    n = len(pts)
    for i, kp in enumerate(kps):
        x, y = pts[i]
        dl = (x - pts[i - 1][0]) / 3.0 if i > 0 else ((pts[1][0] - x) / 3.0 if n > 1 else 1.0 / 3.0)
        dr = (pts[i + 1][0] - x) / 3.0 if i + 1 < n else dl
        kp.handle_left = (x - dl, y - slopes[i] * dl)
        kp.handle_right = (x + dr, y + slopes[i] * dr)
    fc.update()


# --- drivers -------------------------------------------------------------------------------------

def _set_target(var, c):
    t = var.targets[0]
    t.id_type = _id_type(c.id)
    t.id = c.id
    t.data_path = c.var_path


def _new_curve(c):
    """An empty driver curve on channel ``c`` (a driver already there is replaced: Maya replaces the connection)."""
    old = c.find()
    if old is not None:
        c.id.animation_data.drivers.remove(old)
    fc = c.id.driver_add(c.path, c.index) if c.index >= 0 else c.id.driver_add(c.path)
    # A new driver curve maps 1:1 — a Generator modifier in 4.5, two keys (0, 0) (1, 1) in 5.x
    #: SDK curves start empty either way.
    for mod in list(fc.modifiers):
        fc.modifiers.remove(mod)
    while len(fc.keyframe_points):
        fc.keyframe_points.remove(fc.keyframe_points[0], fast=True)
    fc.extrapolation = 'CONSTANT'   # Maya infinity Constant (5.x driver curves start LINEAR)
    return fc


def _sdk_curve(c, d, driver_key):
    """A new one-driver SDK curve on ``c`` reading driver channel ``d``."""
    fc = _new_curve(c)
    scale = curve_scale(driver_key)
    if scale != 1.0:   # a simple expression: no Python auto-run needed
        fc.driver.type = 'SCRIPTED'
        fc.driver.expression = f"{VAR}*{scale:g}"
    else:
        fc.driver.type = 'AVERAGE'
    var = fc.driver.variables.new()
    var.name = VAR
    var.type = 'SINGLE_PROP'
    _set_target(var, d)
    return fc


def is_helper(id_):
    return isinstance(id_, bpy.types.Texture) and bool(id_.get(HELPER))


def helpers():
    return [t for t in bpy.data.textures if t.get(HELPER)]


def helper(create=True):
    """The file's input helper: a hidden Texture (no users but its fake one; a NONE texture draws nothing)."""
    tex = next((t for t in helpers() if t.library is None), None)
    if tex is None and create:
        tex = bpy.data.textures.new(HELPER_NAME, 'NONE')
        tex.use_fake_user = True
        tex[HELPER] = 1
    return tex


def _new_input(c, value):
    """A hidden blendWeighted input property on the input helper, numbered one past the highest (Maya)."""
    tex = helper()
    taken = [int(k[len(INPUT_PROP):]) for k in tex.keys()
             if k.startswith(INPUT_PROP) and k[len(INPUT_PROP):].isdigit()]
    name = f"{INPUT_PROP}{max(taken) + 1 if taken else 0}"
    tex[name] = float(value)
    attr = f'["{name}"]'
    return Chan(tex, attr, -1, tex, attr, tex)


def _copy_var(src, dst):
    dst.name = src.name
    dst.type = src.type
    for a, b in zip(src.targets, dst.targets):
        if src.type == 'SINGLE_PROP':
            b.id_type = a.id_type
        b.id = a.id
        b.data_path = a.data_path
        b.bone_target = a.bone_target
        b.transform_type = a.transform_type
        b.transform_space = a.transform_space
        b.rotation_mode = a.rotation_mode


def _copy_curve(src, dst):
    n = len(src.keyframe_points)
    dst.keyframe_points.add(n)
    for a, b in zip(src.keyframe_points, dst.keyframe_points):
        b.co = a.co
        b.interpolation = a.interpolation
        b.handle_left_type, b.handle_right_type = a.handle_left_type, a.handle_right_type
        b.handle_left, b.handle_right = a.handle_left, a.handle_right
    dst.extrapolation = src.extrapolation
    dst.auto_smoothing = src.auto_smoothing
    dst.driver.type = src.driver.type
    dst.driver.expression = src.driver.expression
    dst.update()


def _blend_var(blend, inp):
    names = {v.name for v in blend.driver.variables}
    name = VAR if VAR not in names else next(f"{VAR}{i}" for i in range(1, 10000) if f"{VAR}{i}" not in names)
    var = blend.driver.variables.new()
    var.name = name
    var.type = 'SINGLE_PROP'
    _set_target(var, inp)
    return var


def _add_input(c, blend, d, driver_key):
    inp = _new_input(c, 0.0)
    fc = _sdk_curve(inp, d, driver_key)
    _blend_var(blend, inp)
    return fc


def to_blend(c, fc):
    """Move a one-driver SDK curve onto a hidden input property; the channel gets a SUM driver over it."""
    inp = _new_input(c, input_value(fc))
    moved = _new_curve(inp)
    _copy_curve(fc, moved)
    var = moved.driver.variables.new()
    var.name = VAR
    var.type = 'SINGLE_PROP'
    src = _target(fc)
    t = var.targets[0]
    t.id_type = src.id_type
    t.id = src.id
    t.data_path = src.data_path
    blend = _new_curve(c)          # removes the old channel driver
    blend.driver.type = 'SUM'
    _blend_var(blend, inp)
    return blend


def ensure_driver(driven, key, driver_node, driver_key):
    """The kit SDK curve of ``driven``.``key`` that reads ``driver_node``.``driver_key`` (made when missing;
    a second driver turns the channel into a Maya blendWeighted sum)."""
    c = chan(driven, key)
    d = chan(driver_node, driver_key)
    fc = c.find()
    if is_sdk(fc) and not is_blend(fc):
        if _reads(fc, d):
            return fc
        fc = to_blend(c, fc)
    if is_blend(fc):
        move_inputs(fc)       # an older file's inputs on the driven ID itself (normally done on load)
        for _var, inp in _inputs(fc):
            if is_sdk(inp) and _reads(inp, d):
                return inp
        return _add_input(c, fc, d, driver_key)
    return _sdk_curve(c, d, driver_key)


def set_key(driven, key, driver_node, driver_key):
    """One Set Driven Key key: (driver value, driven value) on the driven channel's curve for this driver."""
    c = chan(driven, key)
    y = c.get()          # held by a muted driver while posing, else the driven value
    fc = ensure_driver(driven, key, driver_node, driver_key)
    channel = c.find()
    if channel != fc:   # a blendWeighted input: the others' current values stay added
        y -= sum(input_value(f) for _v, f in _inputs(channel) if is_sdk(f) and f != fc)
    x = input_x(fc)
    for kp in fc.keyframe_points:
        if abs(kp.co[0] - x) < 1e-6:
            kp.co[1] = y
            break
    else:
        fc.keyframe_points.insert(x, y, options={'FAST'})
    maya_auto(fc)
    for f in (fc, channel):
        f.mute = False
        f.driver.is_valid = True
    return fc


def key_xs(fcs):
    return sorted({round(kp.co[0], 6) for fc in fcs for kp in fc.keyframe_points})


def step_to(xs, current, direction):
    """The key x after (NEXT) or before (PREVIOUS) ``current``, or None."""
    if direction == 'NEXT':
        return next((x for x in xs if x > current + 1e-6), None)
    return next((x for x in reversed(xs) if x < current - 1e-6), None)


def all_sdk_curves():
    for idb in (*bpy.data.objects, *bpy.data.shape_keys, *helpers()):
        ad = idb.animation_data
        if ad is None:
            continue
        for fc in ad.drivers:
            if is_sdk(fc):
                yield fc


# --- input helper upkeep ----------------------------------------------------------------

def _split_prop(path):
    """'pose.bones["j"]["allset_sdk_0"]' -> ('pose.bones["j"]', 'allset_sdk_0'); None when not an input path."""
    i = path.rfind('["')
    if i < 0 or not path.endswith('"]'):
        return None
    name = path[i + 2:-2]
    return (path[:i], name) if name.startswith(INPUT_PROP) else None


def _editable(id_):
    return id_ is not None and id_.library is None and getattr(id_, "override_library", None) is None


def _move_input(var, remove_old):
    """Give one blendWeighted input its own property on the file's helper: the value, the input's SDK curve and
    the summing variable move there. ``remove_old`` drops the old property and curve (a shared input keeps them)."""
    t = var.targets[0]
    old_id, path = t.id, t.data_path
    split = _split_prop(path)
    if old_id is None or split is None:
        return False
    prefix, name = split
    try:
        struct = old_id.path_resolve(prefix) if prefix else old_id
        value = struct[name]
    except (KeyError, ValueError):
        return False
    ad = old_id.animation_data
    old_fc = ad.drivers.find(path) if ad is not None else None
    inp = _new_input(None, value)
    if old_fc is not None:
        new_fc = _new_curve(inp)
        _copy_curve(old_fc, new_fc)
        for v in old_fc.driver.variables:
            _copy_var(v, new_fc.driver.variables.new())
        new_fc.mute = old_fc.mute
    t.id_type = 'TEXTURE'
    t.id = inp.id
    t.data_path = inp.var_path
    if remove_old and _editable(old_id):
        if old_fc is not None:
            ad.drivers.remove(old_fc)
        del struct[name]
    return True


def move_inputs(blend):
    """Move the inputs of a summed channel that still sit on another ID than the file's helper (an older file, a
    second helper brought in by append / paste); returns how many moved."""
    if not _editable(blend.id_data):
        return 0
    main = helper(create=False)
    n = 0
    for var in blend.driver.variables:
        t = var.targets[0]
        if t.id is None or (main is not None and t.id == main):
            continue
        n += _move_input(var, remove_old=not is_helper(t.id))
        main = helper(create=False)
    if n:
        blend.driver.is_valid = True
    return n


def _blend_curves():
    for idb in (*bpy.data.objects, *bpy.data.shape_keys):
        ad = idb.animation_data
        if ad is None:
            continue
        for fc in ad.drivers:
            if is_blend(fc):
                yield fc


def sync():
    """Keep every blendWeighted input on the file's helper, one channel per input (a duplicated object's summed
    channel gets copies of the inputs it shares with the original), and drop inputs no channel reads.
    Returns (moved, copied, dropped). Pushes no undo step: it runs on load and after object additions / removals."""
    moved = copied = dropped = 0
    blends = list(_blend_curves())
    for fc in blends:
        moved += move_inputs(fc)
    seen = set()
    for fc in blends:
        own = _editable(fc.id_data)
        for var in fc.driver.variables:
            t = var.targets[0]
            if t.id is None:
                continue
            key = (t.id.as_pointer(), t.data_path)
            if key in seen and own:
                copied += _move_input(var, remove_old=False)
                key = (t.id.as_pointer(), t.data_path)
            seen.add(key)
    for tex in helpers():
        if not _editable(tex):
            continue
        ad = tex.animation_data
        for name in [k for k in tex.keys() if k.startswith(INPUT_PROP)]:
            path = f'["{name}"]'
            if (tex.as_pointer(), path) in seen:
                continue
            fc = ad.drivers.find(path) if ad is not None else None
            if fc is not None:
                ad.drivers.remove(fc)
            del tex[name]
            dropped += 1
        if ad is not None:      # input curves whose property is gone
            for fc in [f for f in ad.drivers if (tex.as_pointer(), f.data_path) not in seen]:
                ad.drivers.remove(fc)
        if not any(k.startswith(INPUT_PROP) for k in tex.keys()):
            bpy.data.textures.remove(tex)
    return moved, copied, dropped


_COUNTS = [None]


def _counts():
    return len(bpy.data.objects), len(bpy.data.shape_keys), len(bpy.data.textures)


def sync_if_changed():
    """``sync`` when data-blocks were added or removed since the last look (duplicate, delete, append, paste)."""
    now = _counts()
    if now == _COUNTS[0]:
        return None
    if helpers() or any(True for _ in _old_layout()):
        update_summary.wrote()
        out = sync()
    else:
        out = (0, 0, 0)
    _COUNTS[0] = _counts()
    return out


def _old_layout():
    for fc in _blend_curves():
        if any(not is_helper(v.targets[0].id) for v in fc.driver.variables):
            yield fc


def release_all():
    """Unmute every kit SDK driver muted for posing; returns how many."""
    n = 0
    for fc in all_sdk_curves():
        if fc.mute:
            fc.mute = False
            n += 1
    return n
