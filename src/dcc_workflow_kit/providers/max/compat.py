# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
import bpy

def operator_binding(operator, properties):
    properties = dict(properties or {})
    # Upstream 0.8.5 uses capability checks; custom Blender builds may backport operators.
    if operator == 'mesh.loop_multi_select' and 'select_edge_loop_multi' in dir(bpy.ops.mesh) and 'select_edge_ring_multi' in dir(bpy.ops.mesh):
        ring = properties.pop('ring', False)
        operator = 'mesh.select_edge_ring_multi' if ring else 'mesh.select_edge_loop_multi'
    return (operator, properties)
