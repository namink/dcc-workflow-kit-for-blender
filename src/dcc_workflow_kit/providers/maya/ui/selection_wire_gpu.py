# SPDX-License-Identifier: GPL-3.0-or-later
"""GPU side of the selection wire: the one-object wire shader (``_sh``), the many-object shaders that draw the objects
sharing a batch in one instanced call or several small wires merged into one batch (``_shaders``, uniform buffers
``_ubo``), the single-precision matrix product they use (``projected_matrices``) and the draw-call plan of the
many-object draw (``_plan``, ``_merged``). Related: ``selection_wire`` (draws with them).
"""

_shader = []
_many = []                 # [instanced, merged wire shader] (``_shaders``), None for one that can't be made
_many_smooth = []
_ubos = []                 # uniform buffers of the instanced draw, one per INSTANCES objects of a redraw


# The position code of every wire shader, the same text in each. ``precise`` keeps its operations in this order, each
# rounded on its own (no fused multiply-add), and GLSL rounds +, - and * correctly, so the one-object shader and the
# many-object ones below give the same position from the same values on any GPU. A backend that can't compile it gets
# the plain code in all of them.
_POSITION = ["precise vec4 p = mvp * vec4(pos, 1.0); p.z -= bias * p.w; gl_Position = p;"]
_PLAIN = "gl_Position = mvp * vec4(pos, 1.0); gl_Position.z -= bias * gl_Position.w;"


def _sh():
    if not _shader:
        import gpu

        def make(position):
            info = gpu.types.GPUShaderCreateInfo()
            info.push_constant('MAT4', 'mvp')
            info.push_constant('VEC4', 'color')
            info.push_constant('FLOAT', 'bias')
            info.vertex_in(0, 'VEC3', 'pos')
            info.fragment_out(0, 'VEC4', 'fragColor')
            info.vertex_source("void main() { " + position + " }")
            info.fragment_source("void main() { fragColor = color; }")
            return gpu.shader.create_from_info(info)
        try:
            _shader.append(make(_POSITION[0]))
        except Exception:      # noqa: BLE001
            _POSITION[0] = _PLAIN
            _shader.append(make(_PLAIN))
    return _shader[0]


INSTANCES = 240        # objects per uniform buffer: 240 matrices + 60 vec4 of offsets = 16,320 bytes (within 16 KB)
SMOOTH_FALLBACK = -2


_SMOOTH_VERTEX = """
    vec4 a = mvp * vec4(pos, 1.0);
    vec4 b = mvp * vec4(end_pos, 1.0);
    // Clip the segment before perspective division, including edges crossing the camera.
    float near_a = a.z + a.w;
    float near_b = b.z + b.w;
    edge_distance = 0.0;
    gl_Position = vec4(0.0, 0.0, -2.0, 1.0);
    if (near_a < 0.0 && near_b < 0.0) return;
    if (near_a < 0.0) a = mix(a, b, near_a / (near_a - near_b));
    if (near_b < 0.0) b = mix(b, a, near_b / (near_b - near_a));
    if (a.w <= 0.0 || b.w <= 0.0) return;
    vec2 delta = (b.xy / b.w - a.xy / a.w) * viewportSize;
    float span = length(delta);
    if (span <= 0.0) return;
    vec2 normal = vec2(-delta.y, delta.x) / span;
    // The batch has four vertices per edge, one pixel to either side of its center.
    int corner = gl_VertexID % 4;
    edge_distance = (corner == 0 || corner == 3) ? -1.0 : 1.0;
    gl_Position = corner < 2 ? a : b;
    gl_Position.xy += normal * edge_distance * 2.0 / viewportSize * gl_Position.w;
"""
_SMOOTH_FRAGMENT = """void main() {
    fragColor = vec4(color.rgb, color.a * clamp(1.0 - abs(edge_distance), 0.0, 1.0));
}"""


def _shaders(smooth=False):
    """(instanced, merged) wire shaders drawing many objects in one call. Each object's matrix and depth offset come
    from a uniform buffer, at the slot of its instance (instanced: the objects sharing a batch) or of its points (merged:
    the points of several objects in one batch, each tagged with its object's slot), and its position is computed with
    the same operations as ``_sh`` (``mvp * vec4(pos, 1.0)``, then ``z -= bias * w``) on the same single-precision
    values. (None, None) when the GPU backend can't make them (each object is drawn by itself), merged None when only
    that one can't be made."""
    shaders = _many_smooth if smooth else _many
    if not shaders:
        import gpu
        _sh()                  # settles ``_POSITION`` first: all wire shaders compute the position the same way

        def make(index, inputs):
            info = gpu.types.GPUShaderCreateInfo()
            info.typedef_source(f"struct WireInstances {{ mat4 mvp[{INSTANCES}]; vec4 bias[{INSTANCES // 4}]; }};")
            info.uniform_buf(0, "WireInstances", "inst")
            info.push_constant('VEC4', 'color')
            for slot, (kind, name) in enumerate(inputs):
                info.vertex_in(slot, kind, name)
            info.fragment_out(0, 'VEC4', 'fragColor')
            if smooth:
                info.push_constant('VEC2', 'viewportSize')
                info.vertex_in(len(inputs), 'VEC3', 'end_pos')
                interface = gpu.types.GPUStageInterfaceInfo('selection_wire_edge')
                interface.no_perspective('FLOAT', 'edge_distance')
                info.vertex_out(interface)
            vertex = _SMOOTH_VERTEX if smooth else "float bias = inst.bias[i / 4][i % 4]; " + _POSITION[0]
            info.vertex_source(f"void main() {{ int i = {index}; mat4 mvp = inst.mvp[i];"
                               + vertex + " }")
            info.fragment_source(_SMOOTH_FRAGMENT if smooth else "void main() { fragColor = color; }")
            return gpu.shader.create_from_info(info)
        made = []
        for index, inputs in (("gpu_InstanceIndex", (('VEC3', 'pos'),)), ("slot", (('VEC3', 'pos'), ('INT', 'slot')))):
            try:
                made.append(make(index, inputs))
            except Exception:      # noqa: BLE001  (an unsupported backend: draw each object by itself)
                import traceback
                traceback.print_exc()
                made.append(None)
        shaders[:] = [made[0], made[1] if made[0] is not None else None]
    return shaders[0], shaders[1]


def _sh_many(smooth=False):
    return _shaders(smooth)[0]


def draw_smooth(projection, objects, leads, entries, biases, colors):
    """Draw the cached edge batches with Blender's antialiased polyline shader."""
    import gpu

    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    blend = gpu.state.blend_get()
    try:
        gpu.state.blend_set('ALPHA')
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            shader.bind()
            shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
            shader.uniform_float("lineWidth", 1.0)
            shader.uniform_bool("lineSmooth", True)
            for ob, is_lead, entry, bias in zip(objects, leads, entries, biases):
                batch = entry[0]
                if batch is None:
                    continue
                mvp = projection @ ob.matrix_world
                mvp[2] -= float(bias) * mvp[3]
                gpu.matrix.load_projection_matrix(mvp)
                shader.uniform_float("color", colors[0 if is_lead else 1])
                batch.draw(shader)
    finally:
        shader.uniform_bool("lineSmooth", False)
        gpu.state.blend_set(blend)


def _ubo(k):
    """The ``k``-th uniform buffer of the instanced draw (made once, filled again each redraw)."""
    while len(_ubos) <= k:
        import gpu
        import numpy as np
        _ubos.append(gpu.types.GPUUniformBuf(np.zeros(INSTANCES * 17, np.float32)))
    return _ubos[k]


def projected_matrices(projection, worlds):
    """(n, 4, 4) float32 ``projection @ world`` (rows) for (n, 4, 4) world matrices: the same single-precision result
    as mathutils' ``Matrix @ Matrix``, which multiplies the floats, adds the products in double precision in the
    order of the inner index and rounds the sum to float. ``worlds`` hold float32 values (in any float type)."""
    import numpy as np
    proj = np.array(projection, np.float32)
    single = worlds.astype(np.float32)
    dot = np.zeros((len(single), 4, 4))
    for item in range(4):        # dot[n, row, col] += float(proj[row, item] * world[n, item, col]), item by item
        dot += (proj[None, :, item, None] * single[:, None, item, :]).astype(np.float64)
    return dot.astype(np.float32)


def _plan(entries, leads, order, run_of, starts, ends, smooth=False):
    """The draw calls of ``_draw_many``: [(run, uniform buffer, is_lead, batch, first instance, instance count)], first
    instance -1 for a ``_merged`` batch. Objects sharing a batch are one instanced call per uniform buffer they fill;
    the objects of a colour run with small meshes of their own are one merged call per buffer. Runs stay in order.
    The smoothed plan uses the built-in line shader for large meshes, whose entry retains only its GPU line batch."""
    pieces, singles = [], {}
    instanced, merged = _shaders(smooth)
    strips = {}

    def instance_batch(row):
        batch = entries[row][0]
        if not smooth:
            return batch
        if id(batch) not in strips:
            strips[id(batch)] = _strip_batch(instanced, *entries[row][3])
        return strips[id(batch)]

    for start, end in zip(starts, ends):
        row = order[start]
        entry = entries[row]
        lead = leads[row]
        retained_geometry = len(entry) > 3 and entry[3] is not None
        if smooth and not retained_geometry:
            pieces.append((run_of[start], start // INSTANCES, lead, order[start:end], SMOOTH_FALLBACK, 0))
            continue
        if merged is not None and end - start == 1 and retained_geometry:
            chunk = start // INSTANCES
            singles.setdefault((run_of[start], chunk, lead), []).append((start - chunk * INSTANCES, row))
            continue
        batch = instance_batch(row)
        while start < end:
            chunk = start // INSTANCES
            stop = min(end, (chunk + 1) * INSTANCES)
            pieces.append((run_of[start], chunk, lead, batch, start - chunk * INSTANCES, stop - start))
            start = stop
    for (run, chunk, lead), members in singles.items():
        if len(members) == 1:
            slot, row = members[0]
            pieces.append((run, chunk, lead, instance_batch(row), slot, 1))
        else:
            pieces.append((run, chunk, lead, _merged([(slot, entries[row]) for slot, row in members], smooth), -1, 0))
    pieces.sort(key=lambda piece: (piece[0], piece[1]))
    return pieces


def _strip_batch(shader, points, edges, slots=None):
    """Cache each edge's endpoints on four vertices, expanded into a strip in the vertex shader."""
    import numpy as np
    from gpu_extras.batch import batch_for_shader

    attrs = {"pos": np.repeat(points[edges[:, 0]], 4, axis=0),
             "end_pos": np.repeat(points[edges[:, 1]], 4, axis=0)}
    if slots is not None:
        attrs["slot"] = np.repeat(slots[edges[:, 0]], 4)
    triangles = np.arange(len(edges), dtype=np.intc)[:, None, None] * 4
    triangles = triangles + np.array(((0, 2, 1), (0, 3, 2)), dtype=np.intc)
    return batch_for_shader(shader, 'TRIS', attrs, indices=triangles.reshape(-1, 3))


def _merged(members, smooth=False):
    """One batch of the wires of several objects [(slot in the uniform buffer, entry)]: their points and edges as each
    object's own batch has them, each point tagged with its object's slot (``_shaders`` merged shader)."""
    import numpy as np
    from gpu_extras.batch import batch_for_shader
    points, edges, slots, base = [], [], [], 0
    for slot, entry in members:
        co, ed = entry[3]
        points.append(co)
        edges.append(np.asarray(ed, np.int64) + base)
        slots.append(np.full(len(co), slot, np.intc))
        base += len(co)
    points, slots, edges = np.concatenate(points), np.concatenate(slots), np.concatenate(edges).astype(np.intc)
    shader = _shaders(smooth)[1]
    if smooth:
        return _strip_batch(shader, points, edges, slots)
    return batch_for_shader(shader, 'LINES', {"pos": points, "slot": slots}, indices=edges)
