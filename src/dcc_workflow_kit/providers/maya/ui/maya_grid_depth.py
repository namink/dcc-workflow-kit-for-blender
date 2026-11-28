# SPDX-License-Identifier: GPL-3.0-or-later
"""Grid Behind Surfaces (preference, on by default like Maya): in Material Preview and EEVEE Rendered, the visible opaque
meshes are drawn into the depth before the Maya grid (ui/maya_grid.py ``_draw``), so the grid doesn't show through
their seams. ``opaque_material`` decides which surfaces count; the per-object batches and the handlers that drop
them are below."""

import bpy
from bpy.app.handlers import persistent

_depth_batches = {}


def opaque_material(material):
    """Only fill depth for surfaces whose opacity is unambiguous."""
    if material is None:
        return True
    if material.use_backface_culling:
        return False
    from .. import compat
    if not compat.material_uses_nodes(material):
        return material.diffuse_color[3] == 1.0
    output = material.node_tree.get_output_node('EEVEE')
    if output is None or output.inputs['Displacement'].is_linked or output.inputs['Volume'].is_linked:
        return False
    links = output.inputs['Surface'].links
    if len(links) != 1 or links[0].from_node.type != 'BSDF_PRINCIPLED':
        return False
    inputs = links[0].from_node.inputs
    return all(not inputs[name].is_linked and inputs[name].default_value == value
               for name, value in (('Alpha', 1.0), ('Transmission Weight', 0.0)))


# The depth batches are kept per object (session_uid -> (depsgraph pointer, batch or None, time-dependent)) and drawn
# with the live matrix: a move keeps the batch; it is made again when the object's geometry changes
# (``_depth_on_depsgraph``) or, on a frame change, when its geometry can change with time (``_depth_on_frame``).


@persistent
def _clear_depth(*_args):
    _depth_batches.clear()


@persistent
def _depth_on_depsgraph(_scene, depsgraph):
    if not _depth_batches:
        return
    from .. import update_summary
    for update in update_summary.updates(depsgraph, _depth_on_depsgraph):
        if isinstance(update.id, bpy.types.Object):
            if update.is_updated_geometry:
                _depth_batches.pop(update.id.original.session_uid, None)
        elif isinstance(update.id, bpy.types.Material):
            _depth_batches.clear()             # a material's opacity decides which triangles go in
            return


def _animated_material():
    return any(m.animation_data is not None or (m.node_tree is not None and m.node_tree.animation_data is not None)
               for m in bpy.data.materials)


@persistent
def _depth_on_frame(*_args):
    if not _depth_batches:
        return
    if _animated_material():
        _depth_batches.clear()
        return
    for uid in [uid for uid, (_dg, _batch, timed) in _depth_batches.items() if timed]:
        del _depth_batches[uid]


def depth_pass_on():
    """The Grid Behind Surfaces preference (on by default)."""
    from .. import preferences
    try:
        return bool(preferences.get().grid_depth_pass)
    except (KeyError, AttributeError):
        return False


def _draw_mesh_depth(context):
    """Repair EEVEE's depth at mesh seams before the unfiltered grid overlay."""
    space = context.space_data
    shading = space.shading.type
    if not (shading == 'MATERIAL' or (shading == 'RENDERED' and context.scene.render.engine == 'BLENDER_EEVEE')):
        return              # Solid / Wireframe (checked first: the grid draws on every played frame)
    import gpu
    import numpy as np
    from gpu_extras.batch import batch_for_shader
    from .selection_wire import _positions, time_dependent
    depsgraph = context.evaluated_depsgraph_get()
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(True)
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float('color', (0.0, 0.0, 0.0, 0.0))
    # shortcut: non-mesh objects and generated instances retain engine depth; extend if they show the same defect.
    dg = depsgraph.as_pointer()
    drawn = set()
    memo = {}
    for obj in context.visible_objects:
        if obj.type != 'MESH' or obj.display_type in {'WIRE', 'BOUNDS'} or obj.mode == 'EDIT':
            continue
        evaluated = obj.evaluated_get(depsgraph)
        key = obj.session_uid
        drawn.add(key)
        hit = _depth_batches.get(key)
        if hit is None or hit[0] != dg:
            mesh = evaluated.data
            opaque = [opaque_material(s.material) for s in evaluated.material_slots] or [True]
            mesh.calc_loop_triangles()
            indices = np.empty(len(mesh.loop_triangles) * 3, np.int32)
            materials = np.empty(len(mesh.loop_triangles), np.int32)
            mesh.loop_triangles.foreach_get('vertices', indices)
            mesh.loop_triangles.foreach_get('material_index', materials)
            mask = np.array([opaque[i] if i < len(opaque) else False for i in materials])
            triangles = indices.reshape(-1, 3)[mask.astype(bool)]
            hit = _depth_batches[key] = (dg, batch_for_shader(shader, 'TRIS',
                                         {'pos': _positions(mesh).reshape(-1, 3)}, indices=triangles)
                                         if len(triangles) else None, time_dependent(obj, memo))
        batch = hit[1]
        if batch is not None:
            with gpu.matrix.push_pop():
                gpu.matrix.multiply_matrix(evaluated.matrix_world)
                batch.draw(shader)
    if len(_depth_batches) > len(drawn) + 64:      # objects gone or hidden: their batches go
        for uid in [uid for uid in _depth_batches if uid not in drawn]:
            del _depth_batches[uid]


_DEPTH_HANDLERS = (('depsgraph_update_post', _depth_on_depsgraph), ('frame_change_post', _depth_on_frame),
                   ('load_post', _clear_depth), ('undo_post', _clear_depth), ('redo_post', _clear_depth))
