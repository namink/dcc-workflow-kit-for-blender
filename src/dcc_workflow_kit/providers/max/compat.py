# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
import bpy

def operator_binding(operator, properties):
    properties = dict(properties or {})
    if bpy.app.version >= (5, 1, 0) and operator == 'mesh.loop_multi_select':
        ring = properties.pop('ring', False)
        operator = 'mesh.select_edge_ring_multi' if ring else 'mesh.select_edge_loop_multi'
    return (operator, properties)
