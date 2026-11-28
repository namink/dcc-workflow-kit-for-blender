# SPDX-License-Identifier: GPL-3.0-or-later
"""Where Quad Draw puts points: the Make Live meshes (``reference_objects``) or the construction plane
(``place_point``), the surface under the mouse (``surface_hit``), the closest surface point (``project_point``) and the
Surface Offset (``surface_offset``), plus the screen helpers ``_screen_xy`` / ``_ui_scale`` and the Auto-weld radius
(``_weld_px``).
"""

from bpy_extras import view3d_utils

from . import poly_draw


# --- reference surface ----------------------------------------------------------------------------------

def reference_objects(context):
    """Only explicitly live meshes constrain Quad Draw; otherwise use the construction plane."""
    from . import live
    return live.objects(context.scene)


def surface_offset(context):
    """Offset in Blender units, from the Maya-style scene length-unit field."""
    s = poly_draw.settings(context)
    if not s.qd_offset_on or s.qd_surface_offset == 0:
        return 0.0
    from . import units
    return s.qd_surface_offset * units.maya_unit(context.scene)


def _surface_point(context, hit):
    if hit is None:
        return None
    s = poly_draw.settings(context)
    return hit[0] + hit[1] * surface_offset(context) if s.qd_offset_on else hit[0]


def surface_hit(context, region, rv3d, mouse, refs=None):
    """World point of the reference surface under ``mouse``, or None."""
    refs = reference_objects(context) if refs is None else refs
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse)
    ray = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse).normalized()
    from . import live
    hit = live.ray_hit(context, origin, ray, refs, poly_draw.settings(context).qd_snap_backfaces)
    return _surface_point(context, hit)


def place_point(context, region, rv3d, mouse, refs=None):
    """Where a dot goes: the surface under the mouse; with no reference surface at all, Maya's construction plane."""
    refs = reference_objects(context) if refs is None else refs
    if refs:
        return surface_hit(context, region, rv3d, mouse, refs)
    return poly_draw.construction_point(context, region, rv3d, mouse)


def project_point(context, w, refs=None, region=None, rv3d=None):
    """The closest reference surface point to world ``w`` (``w`` itself without a surface)."""
    refs = reference_objects(context) if refs is None else refs
    # Screen-ray projection follows the visible side of thin/folded surfaces. A nearest-only
    # query can jump to an unrelated sheet behind the point during relax/extend.
    from . import live
    nearest = None
    if refs and region is not None and rv3d is not None:
        base = w
        if surface_offset(context):
            # Project from the surface foot, not from an already offset point.
            # Reusing its shifted screen position adds a sideways drift each time.
            nearest = live.nearest(context, w, refs)
            if nearest is not None:
                base = nearest[0]
        xy = _screen_xy(region, rv3d, base)
        if xy is not None:
            hit = surface_hit(context, region, rv3d, xy, refs)
            if hit is not None:
                return hit
    hit = nearest if nearest is not None else live.nearest(context, w, refs)
    return _surface_point(context, hit) if hit else w


def _ui_scale(context):
    return context.preferences.system.ui_scale or 1.0


def _screen_xy(region, rv3d, w):
    p = view3d_utils.location_3d_to_region_2d(region, rv3d, w)
    return (p.x, p.y) if p is not None else None


def _weld_px(context):
    s = poly_draw.settings(context)
    return float(s.qd_weld_px) if s.qd_auto_weld and not context.scene.allset_soft_select else None
