# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Skin > Bake Deformation to Skin Weights... (``allset.bake_deformation``): per vertex the destination skin's
weights are the least-squares fit (w >= 0, sum 1: ``simplex_lsq``) of linear blend skinning to the source mesh's
deformed points while each shared joint turns +-45 degrees about X / Y / Z (``bake_weights``, ``apply_weights``).
"""

import math

import bpy
from bpy.props import IntProperty
from mathutils import Matrix

from .. import results
from . import skin
from .skin_weight_access import _skin_armature, influence_names

# --- Bake Deformation to Skin Weights ------------------------------------------------------------------------------
BAKE_ANGLE = 45.0          # degrees: each joint +-45 about its X / Y / Z axes (see the module doc)


def simplex_lsq(Q, c, tol=1e-12):
    """argmin_w 1/2 w'Qw - c'w subject to w >= 0, sum(w) = 1 (primal active set, Nocedal-Wright 16.3)."""
    import numpy as np
    n = len(c)
    # start at the best single influence (feasible vertex of the simplex)
    obj = 0.5 * np.diag(Q) - c
    free = [int(np.argmin(obj))]
    w = np.zeros(n)
    w[free[0]] = 1.0
    for _ in range(4 * n + 20):
        k = len(free)
        K = np.zeros((k + 1, k + 1))
        K[:k, :k] = Q[np.ix_(free, free)]
        K[:k, k] = 1.0
        K[k, :k] = 1.0
        sol = np.linalg.lstsq(K, np.append(c[free], 1.0), rcond=None)[0]
        target = np.zeros(n)
        target[free] = sol[:k]
        p = target - w
        if np.abs(p).max() > tol:
            neg = [i for i in free if p[i] < -tol]
            alpha = 1.0
            block = None
            for i in neg:
                a = -w[i] / p[i]
                if a < alpha:
                    alpha, block = a, i
            w = w + alpha * p
            if block is not None:
                w[block] = 0.0
                free.remove(block)
            continue
        g = Q @ w - c
        nu = -g[free].mean()
        mu = g + nu
        out = [i for i in range(n) if i not in free]
        if not out:
            break
        j = min(out, key=lambda i: mu[i])
        if mu[j] >= -1e-10 * (1.0 + abs(nu)):
            break
        free.append(j)
    w = np.clip(w, 0.0, None)
    s = w.sum()
    return w / s if s > 0 else w


def _pose_bones_matching(src_arm, dst_arm, dst_names):
    """[(name, src pose bone, dst pose bone)] for the destination influences the source skeleton also has."""
    out = []
    for name in dst_names:
        sp = src_arm.pose.bones.get(name)
        dp = dst_arm.pose.bones.get(name)
        if sp is not None and dp is not None:
            out.append((name, sp, dp))
    return out


def _deformed_world(ob, depsgraph):
    import numpy as np
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    try:
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
    finally:
        ev.to_mesh_clear()
    mw = np.array(ev.matrix_world)
    return co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]


def _skin_matrices(arm, bones):
    import numpy as np
    mw = arm.matrix_world
    return np.array([np.array(mw @ pb.matrix @ (mw @ pb.bone.matrix_local).inverted()) for _n, _s, pb in bones])


def bake_weights(context, src, dst, max_influences=3, angle=BAKE_ANGLE):
    """Fit ``dst``'s skin weights to ``src``'s deformation (see the module doc); returns (names, weights (V, J))."""
    import numpy as np
    src_arm, dst_arm = _skin_armature(src), _skin_armature(dst)
    bones = _pose_bones_matching(src_arm, dst_arm, influence_names(dst) or [
        b.name for b in dst_arm.data.bones if b.use_deform])
    if not bones:
        raise ValueError("The source and destination skeletons share no joint")
    saved = {pb: pb.matrix_basis.copy() for arm in {src_arm, dst_arm} for pb in arm.pose.bones}
    previews = [m for m in src.modifiers if m.show_viewport and m.type in {'SUBSURF', 'MULTIRES'}
                and m.name.startswith("Maya Smooth")]
    for m in previews:
        m.show_viewport = False
    try:
        for pb in saved:
            pb.matrix_basis = Matrix.Identity(4)
        context.view_layer.update()
        dg = context.evaluated_depsgraph_get()
        rest = _deformed_world(src, dg)
        if len(rest) != len(dst.data.vertices):
            raise ValueError("The source and destination meshes need the same vertex count")
        samples, mats = [], []
        a = math.radians(angle)
        for name, sp, dp in bones:
            for axis in "XYZ":
                for sign in (1.0, -1.0):
                    rot = Matrix.Rotation(sign * a, 4, axis)
                    sp.matrix_basis = rot
                    dp.matrix_basis = rot
                    context.view_layer.update()
                    samples.append(_deformed_world(src, context.evaluated_depsgraph_get()))
                    mats.append(_skin_matrices(dst_arm, bones))
                    sp.matrix_basis = Matrix.Identity(4)
                    dp.matrix_basis = Matrix.Identity(4)
    finally:
        for pb, m in saved.items():
            pb.matrix_basis = m
        for m in previews:
            m.show_viewport = True
        context.view_layer.update()
    S = np.stack(samples)                         # (F, V, 3)
    M = np.stack(mats)                            # (F, J, 4, 4)
    ph = np.concatenate([rest, np.ones((len(rest), 1))], axis=1)
    nj = len(bones)
    W = np.zeros((len(rest), nj))
    for v in range(len(rest)):
        X = np.einsum('fjab,b->fja', M, ph[v])[..., :3]          # (F, J, 3): each joint's motion of the rest point
        A = X.transpose(0, 2, 1).reshape(-1, nj)                   # rows (frame, xyz), columns joints
        b = S[:, v, :].reshape(-1)
        W[v] = simplex_lsq(A.T @ A, A.T @ b)
        if 0 < max_influences < np.count_nonzero(W[v] > 0):
            keep = np.argsort(-W[v])[:max_influences]
            sub = simplex_lsq((A.T @ A)[np.ix_(keep, keep)], (A.T @ b)[keep])
            W[v] = 0.0
            W[v, keep] = sub
    return [n for n, _s, _d in bones], W


def apply_weights(mesh, names, W):
    import numpy as np
    every = list(range(len(mesh.data.vertices)))
    for j, name in enumerate(names):
        vg = mesh.vertex_groups.get(name) or mesh.vertex_groups.new(name=name)
        vg.remove(every)
        col = W[:, j]
        for value in np.unique(col):
            if value > 0.0:
                vg.add(np.flatnonzero(col == value).tolist(), float(value), 'REPLACE')


class ALLSET_OT_bake_deformation(bpy.types.Operator):
    """Maya Skin > Bake Deformation to Skin Weights...: fit the destination skin's weights to the source mesh's whole
    deformation (skin + deformers) over each joint's range of motion (select the source, then the destination)"""
    bl_idname = "allset.bake_deformation"
    bl_label = "Bake Deformation to Skin Weights"
    bl_options = {'REGISTER', 'UNDO'}

    max_influences: IntProperty(name="Max influences", default=3, min=1, max=50)    # default like Maya

    def execute(self, context):
        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        act = context.active_object
        if len(meshes) != 2 or act not in meshes:
            self.report({'WARNING'}, "Select the source mesh, then the destination mesh")
            return {'CANCELLED'}
        dst = act
        src = next(o for o in meshes if o is not dst)
        if _skin_armature(src) is None:
            self.report({'WARNING'}, f"{src.name} has no skin: bind the source mesh to its skeleton first")
            return {'CANCELLED'}
        if context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if _skin_armature(dst) is None:          # the destination gets the source skeleton (Maya needs a skin there)
            skin.bind_skin(context, _skin_armature(src), [dst], max_influences=self.max_influences)
        try:
            names, W = bake_weights(context, src, dst, self.max_influences)
        except ValueError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        apply_weights(dst, names, W)
        dst.data.update()
        results.result(self, f"Baked {src.name}'s deformation into {dst.name}'s skin weights")
        return {'FINISHED'}
