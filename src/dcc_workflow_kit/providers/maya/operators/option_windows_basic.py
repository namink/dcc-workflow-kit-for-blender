# SPDX-License-Identifier: GPL-3.0-or-later
"""Option windows of the basic Create / Edit / Modify / Mesh / Edit Mesh / Constrain / Key / UV / File commands:
Polygon Cube / Sphere / Cylinder / Cone / Torus / Plane, Group, Freeze / Reset Transformations, Combine, Smooth,
Extrude, Bevel, Smart Bevel, Bridge, Merge, Parent / Point / Orient Constraint, Set Key, Bake Simulation, Planar /
Automatic Mapping, New Scene and Save Scene, with the functions that run them (``_run_*``).

Entry point: ``WINDOWS`` (``option_windows`` lists these first, then the other ``option_windows_*`` modules).
Related: ``option_windows_spec`` (F / Window and the shared run helpers).
"""

import bpy
from mathutils import Vector

from ..preferences import NEW_SCENE_TIMES
from . import scene_axes
from .option_windows_spec import AXIS, UVS, F, Window, _components, _constraint, _op, _primitive, _with_hierarchy

# --- run functions ----------------------------------------------------------------------------------

def _run_group(context, v):
    res = bpy.ops.allset.group('EXEC_DEFAULT')
    grp = context.view_layer.objects.active
    if res == {'FINISHED'} and grp is not None:
        if v["group_under"] == "World" and grp.parent is not None:
            world = grp.matrix_world.copy()
            grp.parent = None
            grp.matrix_world = world
        if v["pivot"] == "Center":
            from .freeze import center_pivot
            center_pivot(context, [grp])
    return res


def _run_combine(context, v):
    objects = [o for o in context.selected_objects if o.type == 'MESH']
    last = context.view_layer.objects.active
    point = last.matrix_world.translation.copy() if last is not None else Vector()
    res = bpy.ops.allset.combine('EXEC_DEFAULT')
    ob = context.view_layer.objects.active
    if res == {'FINISHED'} and ob is not None and v["pivot"] != "Center" and objects:
        from .pivot import match_pivot
        match_pivot(ob, point if v["pivot"] == "Last object" else Vector())
    return res


def _run_smooth(context, v):
    """Maya Smooth with the window's values: real Catmull-Clark geometry (operators/poly_smooth.py)."""
    if context.mode != 'EDIT_MESH' and not any(o.type == 'MESH' for o in context.selected_objects):
        raise RuntimeError("Select a mesh first.")
    return bpy.ops.allset.smooth('EXEC_DEFAULT', divisions=v["levels"])


def _run_bevel(context, v):
    # Maya polyBevel3 with the window's values (allset.bevel, editable afterwards like Ctrl+B)
    fraction = v["offset_type"].startswith("Fractional")
    kw = dict(segments=v["segments"], depth=max(-1.0, min(1.0, v["depth"])), offset_as_fraction=fraction,
              chamfer=v.get("chamfer", True), world_space=v.get("offset_space", True),
              smoothing_angle=max(0.0, min(180.0, v.get("smoothing_angle", 30.0))))
    if fraction:
        kw["fraction"] = max(0.0, min(1.0, v["width"]))
    else:
        kw["offset"] = max(0.0, v["width"])
    if context.mode == 'EDIT_MESH' and tuple(context.scene.tool_settings.mesh_select_mode) == (True, False, False):
        bpy.ops.mesh.select_mode(type='EDGE')       # the window bevels edges (Maya: polyBevel3, not Chamfer)
    if context.mode == 'OBJECT':
        if not any(o.type == 'MESH' for o in context.selected_objects):
            raise RuntimeError("Select a mesh first.")
        return _op("allset.bevel", **kw)            # every edge of the selected meshes, still in object mode
    return _components(context, "allset.bevel", 'EDGE', **kw)


def _run_smart_bevel(context, v):
    # Maya 2027 polySmartBevel with the window's values (allset.smart_bevel, editable afterwards)
    from .smart_bevel import FILTER_KEYS
    kw = dict(width=max(0.0, v["width"]), segments=max(1, v["segments"]), depth=max(-1.0, min(1.0, v["depth"])),
              limit_width=v.get("limit_width", True), filter=FILTER_KEYS.get(v.get("filter"), 'SELECTED'),
              filter_angle=max(0.0, min(180.0, v.get("filter_angle", 30.0))),
              set_border_hard=v.get("set_border_hard", False),
              smoothing_angle=max(0.0, min(180.0, v.get("smoothing_angle", 30.0))),
              weld_opposing_arcs=max(0.0, v.get("weld_opposing_arcs", 0.0)),
              weld_all_arcs=max(0.0, v.get("weld_all_arcs", 0.0)))
    if context.mode == 'EDIT_MESH' and tuple(context.scene.tool_settings.mesh_select_mode) == (True, False, False):
        bpy.ops.mesh.select_mode(type='EDGE')       # the window bevels edges
    return _components(context, "allset.smart_bevel", 'EDGE', **kw)


def _run_extrude(context, v):
    def go():
        # Curve: Selected / Generated: along the curve with Taper / Twist (Maya passes them in every case; without
        # a curve they change nothing)
        return bpy.ops.allset.extrude('EXEC_DEFAULT', thickness=v["thickness"], offset=v["offset"],
                                        divisions=v["divisions"], curve=v.get("curve", "Selected").upper(),
                                        taper=v.get("taper", 1.0), twist=v.get("twist", 0.0))
    if context.mode == 'EDIT_MESH':
        return go()
    meshes = [o for o in context.selected_objects if o.type == 'MESH']
    if not meshes:
        raise RuntimeError("Select faces (or a mesh) to extrude.")
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        bpy.ops.mesh.select_mode(type='FACE')
        bpy.ops.mesh.select_all(action='SELECT')
        return go()
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')


def _run_set_key(context, v):
    return _with_hierarchy(context, v["hierarchy"] == "Below", lambda: bpy.ops.allset.set_key('EXEC_DEFAULT'))


def _run_bake(context, v):
    # Maya's bakeResults rules (operators/bake_maya.py). Keep unbaked keys = keys outside the range,
    # never constraint deletion
    return bpy.ops.allset.bake_simulation(
        'EXEC_DEFAULT', hierarchy_below=v["hierarchy"] == "Below", use_time_slider=v["time_range"] == "Time Slider",
        start=int(round(v["start"])), end=int(round(v["end"])), sample_by=max(1, int(round(v["sample_by"]))),
        keep_unbaked=bool(v["keep_unbaked"]), disable_implicit=bool(v["disable_implicit"]))


def _run_uv_planar(context, v):
    # X / Y / Z axis: allset.uv_planar projects along the scene axis (and takes the picked UV faces in UV mode)
    axis = {"X axis": 'X', "Y axis": 'Y', "Z axis": 'Z'}
    if v["fit"] == "Best plane" or v["project_from"] == "Camera":
        return bpy.ops.allset.uv_planar('EXEC_DEFAULT', axis='NORMAL')
    obs = [o for o in (context.objects_in_mode if context.mode == 'EDIT_MESH' else context.selected_objects)
           if o.type == 'MESH']
    if not obs:
        raise RuntimeError("Select faces (or a mesh) to project.")
    return bpy.ops.allset.uv_planar('EXEC_DEFAULT', axis=axis[v["project_from"]])


def _run_uv_auto(context, v):
    # Maya polyAutoProjection in bmesh (operators/uv_projection.auto_project); handles object mode itself.
    return bpy.ops.allset.uv_automatic('EXEC_DEFAULT', planes=v["planes"], spacing=v["spacing"])


def _run_new_scene(context, v):
    values = dict(v)

    def later():
        from .. import first_start
        first_start.new_maya_scene(values)     # the Maya layout file bundled in the extension + these options
        return None
    # Maya's Save Changes prompt first (#57); never load a file inside a running operator
    #: save_prompt runs it from a timer
    from ..ui import save_prompt
    save_prompt.ask(context, later)
    return {'FINISHED'}


def _run_save(context, v):
    if v["incremental"] and bpy.data.filepath:
        return bpy.ops.allset.increment_save('EXEC_DEFAULT')
    if not bpy.data.filepath:
        return bpy.ops.allset.save_scene_as('INVOKE_DEFAULT')
    return bpy.ops.wm.save_mainfile('EXEC_DEFAULT', compress=v["compressed"])


# --- the windows (labels / defaults) ------------------------------

_FREEZE_RESET = lambda kind: [F("translate", f"{kind}:", "bool", True, text="Translate"),   # noqa: E731
                              F("rotate", "", "bool", True, text="Rotate"), F("scale", "", "bool", True, text="Scale")]
_CON_AXES = [F("all", "Constraint axes:", "bool", True, text="All"), F("x", "", "bool", False, text="X"),
             F("y", "", "bool", False, text="Y"), F("z", "", "bool", False, text="Z"),
             F("weight", "Weight:", "float", 1.0, lo=0.0, hi=1.0)]


def _old_con_axes(v):
    scene_axes.old_swap(v, "y", "z")

WINDOWS = [
    Window("poly_cube", "Polygon Cube Options", "Create", ("allset.create", {"kind": 'CUBE'}), [
        F("width", "Width:", "length", 1.0, lo=0.0001, hi=100), F("height", "Height:", "length", 1.0, lo=0.0001, hi=100),
        F("depth", "Depth:", "length", 1.0, lo=0.0001, hi=100),
        F("width_div", "Width divisions:", "int", 1, lo=1, hi=50), F("height_div", "Height divisions:", "int", 1, lo=1, hi=50),
        F("depth_div", "Depth divisions:", "int", 1, lo=1, hi=50), AXIS, UVS], _primitive('CUBE'),
        missing=("Normalize", "Collectively / Each face separately", "Preserve aspect ratio")),
    Window("poly_sphere", "Polygon Sphere Options", "Create", ("allset.create", {"kind": 'SPHERE'}), [
        F("radius", "Radius:", "length", 1.0, lo=0.0001, hi=100), F("axis_div", "Axis divisions:", "int", 20, lo=3, hi=200),
        F("height_div", "Height divisions:", "int", 20, lo=3, hi=200), AXIS, UVS], _primitive('SPHERE'),
        missing=("Pinched / Sawtooth at poles",)),
    Window("poly_cylinder", "Polygon Cylinder Options", "Create", ("allset.create", {"kind": 'CYLINDER'}), [
        F("radius", "Radius:", "length", 1.0, lo=0.0001, hi=100), F("height", "Height:", "length", 2.0, lo=0.0001, hi=100),
        F("axis_div", "Axis divisions:", "int", 20, lo=3, hi=200), F("height_div", "Height divisions:", "int", 1, lo=1, hi=100),
        F("cap_div", "Cap divisions:", "int", 1, lo=0, hi=100), F("round_cap", "", "bool", False, text="Round cap"),
        AXIS, UVS], _primitive('CYLINDER'), missing=("Normalize", "Preserve aspect ratio")),
    Window("poly_cone", "Polygon Cone Options", "Create", ("allset.create", {"kind": 'CONE'}), [
        F("radius", "Radius:", "length", 1.0, lo=0.0001, hi=100), F("height", "Height:", "length", 2.0, lo=0.0001, hi=100),
        F("axis_div", "Axis divisions:", "int", 20, lo=3, hi=200), F("height_div", "Height divisions:", "int", 1, lo=1, hi=100),
        F("cap_div", "Cap divisions:", "int", 0, lo=0, hi=100), F("round_cap", "", "bool", False, text="Round cap"),
        AXIS, UVS], _primitive('CONE'), missing=("Normalize", "Preserve aspect ratio")),
    Window("poly_torus", "Polygon Torus Options", "Create", ("allset.create", {"kind": 'TORUS'}), [
        F("radius", "Radius:", "length", 1.0, lo=0.0001, hi=100),
        F("section_radius", "Section Radius:", "length", 0.5, lo=0.0001, hi=100),
        F("twist", "Twist:", "float", 0.0, lo=-360, hi=360),
        F("axis_div", "Axis divisions:", "int", 20, lo=3, hi=200), F("height_div", "Height divisions:", "int", 20, lo=3, hi=200),
        AXIS, UVS], _primitive('TORUS')),
    Window("poly_plane", "Polygon Plane Options", "Create", ("allset.create", {"kind": 'PLANE'}), [
        F("width", "Width:", "length", 1.0, lo=0.0001, hi=100), F("height", "Height:", "length", 1.0, lo=0.0001, hi=100),
        F("width_div", "Width divisions:", "int", 10, lo=1, hi=200), F("height_div", "Height divisions:", "int", 10, lo=1, hi=200),
        AXIS, UVS], _primitive('PLANE'), missing=("Preserve aspect ratio",)),
    Window("group", "Group Options", "Group", ("allset.group", {}), [
        F("group_under", "Group under:", "enum", "Parent", items=("Parent", "World")),
        F("pivot", "Group pivot:", "enum", "Origin", items=("Center", "Origin"))], _run_group),
    Window("freeze", "Freeze Transformations Options", "Freeze Transform", ("allset.freeze_transform", {}),
           _FREEZE_RESET("Freeze"),
           lambda c, v: bpy.ops.allset.freeze_transform('EXEC_DEFAULT', translate=v["translate"],
                                                          rotate=v["rotate"], scale=v["scale"]),
           missing=("Joint orient", "Lock normals", "Preserve normals")),
    Window("reset", "Reset Transformations Options", "Reset Transform", ("allset.reset_transform", {}),
           _FREEZE_RESET("Reset"),
           lambda c, v: bpy.ops.allset.reset_transform('EXEC_DEFAULT', translate=v["translate"],
                                                         rotate=v["rotate"], scale=v["scale"])),
    Window("combine", "Combine Options", "Combine", ("allset.combine", {}), [
        F("pivot", "Pivot Position:", "enum", "Center", items=("Center", "Last object", "World origin"))],
        _run_combine, missing=("Merge UV Sets", "Combine Skinning")),
    Window("smooth", "Smooth Options", "Smooth", None, [
        F("levels", "Division levels:", "int", 1, lo=0, hi=6)], _run_smooth,
        # the kit always smooths with the default options, like Maya: sharp edges and corners, selection border kept
        paths=("Mesh/Smooth",), missing=("Exponentially / Linearly", "Maya Catmull-Clark", "Propagate Edge Hardness",
                                        "Vertex Boundary: Sharp edges", "Smooth UVs: off", "Map borders",
                                        "Preserve: Geometry / Selection borders")),
    Window("extrude", "Extrude Face Options", "Extrude", ("allset.extrude", {}), [
        F("divisions", "Divisions:", "int", 1, lo=1, hi=50), F("offset", "Offset:", "float", 0.0),
        F("thickness", "Thickness:", "float", 0.0),
        F("curve", "Curve:", "enum", "Selected", items=("None", "Selected", "Generated")),
        F("taper", "Taper:", "float", 1.0, lo=0.0, hi=15.0), F("twist", "Twist:", "float", 0.0, lo=-180.0, hi=180.0)],
        _run_extrude, missing=("Smoothing angle",),
        enabled=lambda values, name: name not in ("taper", "twist") or values["curve"] != "None"),
    Window("bevel", "Bevel Options", "Bevel", None, [
        F("offset_type", "Offset type:", "enum", "Fractional (prevents inside out bevels)",
          items=("Fractional (prevents inside out bevels)", "Absolute")),
        F("offset_space", "Offset space:", "bool", True, text="World (Ignore scaling on object)"),
        F("width", "Width:", "float", 0.5, lo=0.0, hi=1.0), F("segments", "Segments:", "int", 1, lo=1, hi=50),
        F("depth", "Depth:", "float", 1.0, lo=-1.0, hi=1.0), F("chamfer", "Chamfer:", "bool", True, text="Chamfer"),
        F("smoothing_angle", "Smoothing angle:", "float", 30.0, lo=0.0, hi=180.0)],
        _run_bevel,
        paths=("Edit Mesh/Bevel",), missing=("Mitering / Miter Along", "Automatically fit bevel to object")),
    Window("smart_bevel", "Smart Bevel Options", "Smart Bevel", None, [
        F("width", "Width:", "float", 0.2, lo=0.0), F("segments", "Segments:", "int", 1, lo=1, hi=50),
        F("depth", "Depth:", "float", 0.5, lo=-1.0, hi=1.0),
        F("limit_width", "Limit width:", "bool", True, text="Keep the width below what the mesh allows"),
        F("filter", "Filter:", "enum", "Selected Edges", items=("Selected Edges", "Hard Edges", "Edges by Angle")),
        F("filter_angle", "Filter angle:", "float", 30.0, lo=0.0, hi=180.0),
        F("set_border_hard", "Border edges:", "bool", False, text="Set Border Edges to Hard"),
        F("smoothing_angle", "Smoothing angle:", "float", 30.0, lo=0.0, hi=180.0),
        F("weld_opposing_arcs", "Weld opposing arcs:", "float", 0.0, lo=0.0),
        F("weld_all_arcs", "Weld all arcs:", "float", 0.0, lo=0.0)],
        _run_smart_bevel,
        paths=("Edit Mesh/Smart Bevel",), missing=("Cutback Relaxation", "Remove Isolated Arcs")),
    Window("bridge", "Bridge Options", "Bridge", None, [
        F("curve_type", "Bridge type:", "enum", "Linear path",
          items=("Linear path", "Smooth path", "Smooth path + curve")),
        F("divisions", "Divisions:", "int", 5, lo=0, hi=100),
        F("twist_angle", "Twist:", "float", 0, lo=-360, hi=360), F("taper", "Taper:", "float", 1, lo=0, hi=3),
        F("twist", "Bridge offset:", "int", 0, lo=-100, hi=100),
        F("direction", "Direction:", "enum", "Automatic", items=("Automatic", "Manual")),
        F("source_direction", "Source:", "enum", "Along normal", items=("Along normal", "Opposite normal")),
        F("target_direction", "Target:", "enum", "Along normal", items=("Along normal", "Opposite normal")),
        F("smoothing_angle", "Smoothing angle:", "float", 30, lo=0, hi=180),
        F("input_curve", "Path curve:", "curve", ""),
        F("taper_curve", "Taper curve:", "ramp", '[[0.0,1.0,1],[1.0,1.0,1]]')],
        lambda c, v: _components(c, "allset.bridge", 'EDGE', divisions=v["divisions"],
                                 bridge_offset=v["twist"],
                                 curve_type=("Linear path", "Smooth path", "Smooth path + curve").index(v["curve_type"]),
                                 twist_angle=v["twist_angle"], taper=v["taper"],
                                 direction=int(v['direction'] == 'Manual'),
                                 source_direction=int(v['source_direction'] == 'Opposite normal'),
                                 target_direction=int(v['target_direction'] == 'Opposite normal'),
                                 smoothing_angle=v['smoothing_angle'], input_curve=v['input_curve'],
                                 taper_curve=v['taper_curve']),
        paths=("Edit Mesh/Bridge",),
        enabled=lambda values, name: ((name not in {"twist_angle", "taper", "taper_curve"}
                                       or values["curve_type"] != "Linear path")
                                      and (name != 'input_curve' or values['curve_type'] == 'Smooth path + curve')
                                      and (name not in {'source_direction', 'target_direction'}
                                           or values['direction'] == 'Manual'))),
    Window("merge", "Merge Vertices Options", "Merge", None, [
        F("threshold", "Threshold:", "length", 0.01, lo=0.0, hi=1.0),
        F("always_two", "", "bool", True, text="Always merge for two vertices")],
        lambda c, v: _components(c, "allset.merge", 'VERT', threshold=v["threshold"], always_two=v["always_two"]),
        paths=("Edit Mesh/Merge",)),
    Window("parent_constraint", "Parent Constraint Options", "Add", ("allset.constrain", {"type": 'CHILD_OF'}), [
        F("maintain_offset", "Maintain offset:", "bool", True),
        F("all_t", "Translate:", "bool", True, text="All"), F("tx", "", "bool", False, text="X"),
        F("ty", "", "bool", False, text="Y"), F("tz", "", "bool", False, text="Z"),
        F("all_r", "Rotate:", "bool", True, text="All"), F("rx", "", "bool", False, text="X"),
        F("ry", "", "bool", False, text="Y"), F("rz", "", "bool", False, text="Z"),
        F("weight", "Weight:", "float", 1.0, lo=0.0, hi=1.0)], _constraint('CHILD_OF'),
        missing=("Decompose near object", "Animation Layer"),
        old_axes=lambda v: (scene_axes.old_swap(v, "ty", "tz"), scene_axes.old_swap(v, "ry", "rz"))),
    Window("point_constraint", "Point Constraint Options", "Add", ("allset.constrain", {"type": 'COPY_LOCATION'}),
           [F("maintain_offset", "Maintain offset:", "bool", False)] + _CON_AXES, _constraint('COPY_LOCATION'),
           missing=("Offset", "Animation Layer"), old_axes=_old_con_axes),
    Window("orient_constraint", "Orient Constraint Options", "Add", ("allset.constrain", {"type": 'COPY_ROTATION'}),
           [F("maintain_offset", "Maintain offset:", "bool", False)] + _CON_AXES, _constraint('COPY_ROTATION'),
           missing=("Offset", "Animation Layer"), old_axes=_old_con_axes),
    Window("set_key", "Set Key Options", "Set Key", ("allset.set_key", {}), [
        F("hierarchy", "Hierarchy:", "enum", "Selected", items=("Selected", "Below"))], _run_set_key,
        missing=("Set keys on: manipulator handles", "Set keys at: Prompt", "Set IK/FK keys", "Channels: From Channel Box",
                 "Control points", "Shapes")),
    Window("bake_simulation", "Bake Simulation Options", "Bake", ("allset.bake_simulation", {}), [
        F("hierarchy", "Hierarchy:", "enum", "Selected", items=("Selected", "Below")),
        F("time_range", "Time range:", "enum", "Time Slider", items=("Time Slider", "Start/End")),
        F("start", "Start time:", "float", 0.0), F("end", "End time:", "float", 10.0),
        F("sample_by", "Sample by:", "float", 1.0, lo=1.0, hi=100.0),
        F("keep_unbaked", "Keep unbaked keys:", "bool", True),
        F("disable_implicit", "Disable implicit control:", "bool", True)], _run_bake,
        missing=("Channels: From Channel Box", "Bake To: New Layer", "Smart Bake", "Sparse curve bake")),
    Window("uv_planar", "Planar Mapping Options", "Project", ("allset.uv_planar", {}), [
        F("fit", "Fit projection to:", "enum", "Bounding box", items=("Best plane", "Bounding box")),
        F("project_from", "Project from:", "enum", "X axis", items=("X axis", "Y axis", "Z axis", "Camera"))],
        _run_uv_planar, paths=("UV/Planar",), missing=("Keep image width/height ratio", "Insert projection before deformers",
                                                       "Create new UV Set")),
    Window("uv_automatic", "Polygon Automatic Mapping Options", "Project", ("allset.uv_automatic", {}), [
        F("planes", "Planes:", "enum", "6", items=("3", "4", "5", "6", "8", "12")),
        F("spacing", "Percentage space:", "float", 0.2, lo=0.0, hi=5.0)], _run_uv_auto, paths=("UV/Automatic",),
        missing=("Optimize for", "Shell layout / Scale mode / Shell stacking", "Create new UV set")),
    Window("new_scene", "New Scene Options", "New", None, [
        F("keep_units", "", "bool", False, text="Do not reset working units"),
        F("linear", "Linear:", "enum", "centimeter", items=("millimeter", "centimeter", "meter", "inch", "foot", "yard")),
        F("angular", "Angular:", "enum", "degrees", items=("degrees", "radians")),
        F("fps", "Time:", "enum", "24 fps", items=NEW_SCENE_TIMES),
        F("play_start", "Playback start:", "int", 1, lo=-100000), F("play_end", "Playback end:", "int", 120, lo=-100000),
        F("anim_start", "Animation start:", "int", 1, lo=-100000), F("anim_end", "Animation end:", "int", 200, lo=-100000)],
        _run_new_scene, paths=("File/New Scene",), pref_fields={"fps": "new_scene_time"}, missing=("Enable default scene", "Show the Compass", "Color Management enabled")),
    Window("save_scene", "Save Scene Options", "Save Scene", None, [
        F("incremental", "", "bool", False, text="Incremental save"),
        F("compressed", "", "bool", False, text="Compressed save")], _run_save, paths=("File/Save Scene",),
        missing=("Limit incremental saves", "Save Thumbnail/Playblast", "USD edits")),
]
