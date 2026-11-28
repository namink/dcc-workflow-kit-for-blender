# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya UV Editor > Modify > Optimize, the maths (numpy, no bpy): relax the distortion of one UV shell against its 3D
surface.

What Optimize does (like Maya):
- Every UV that is not held moves; held UVs (pinned ones, and the UVs outside the selection) stay where they are, so
  a partly selected shell relaxes only its selected part against the rest. The shell border is not held: it moves
  like any other UV.
- A shell with no held UV keeps its UV area and one of its UVs stays exactly where it was (the kit keeps the first
  UV, in UV order); the rest of the shell may turn a little around it, as the relaxing turns it.
- Each iteration takes every triangle's current UV shape, finds the nearest undistorted copy of its 3D shape (turned,
  at the shell's UV scale) and moves the UVs so that all triangles get as close to those copies as possible at once
  (a local / global "as rigid as possible" step). A shell that is evenly squashed or stretched comes back undistorted
  in one iteration; uneven distortion halves roughly with each iteration.
- Surfangle (0-1) weighs keeping the 3D surface area of each triangle (1) against keeping only its angles (0).
- Prevent triangle flips: a step that would leave more triangles turned over than before is shortened until it
  does not.
- Iterations 0, or Power below 100, leave the UVs as they are.

Legacy (relax), the other method: every free UV moves toward the weighted average of its neighbours (``relax``).
Pin UV border (on by default) keeps the shell borders, Pin UVs keeps the selected or the unselected UVs; Edge
weights Uniform (default) or World space (the 3D shape: cotangent weights); Maximum iterations (default 5) = the solver
steps, the result after many steps is the fully relaxed layout.
"""

import math

import numpy as np

_CG_STEPS = 400          # conjugate-gradient steps of one global solve (warm started, stops at the tolerance)
_CG_TOL = 1e-10
_WEIGHT_MIN, _WEIGHT_MAX = 1e-2, 1e2   # cotangent weights kept positive (obtuse / degenerate triangles)
_FLIP_HALVINGS = 10


def _frames(P, T):
    """Each triangle's 3D corners in its own plane (corner 0 at the origin, corner 1 on +x): (m, 3, 2), areas (m,)."""
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    e1, e2 = b - a, c - a
    l1 = np.linalg.norm(e1, axis=1)
    n = np.cross(e1, e2)
    area2 = np.linalg.norm(n, axis=1)
    ok = (l1 > 1e-12) & (area2 > 1e-18)
    x = np.zeros((len(T), 3, 2))
    l1s = np.where(ok, l1, 1.0)
    ex = e1 / l1s[:, None]
    ny = np.cross(n / np.where(ok, area2, 1.0)[:, None], ex)
    x[:, 1, 0] = l1
    x[:, 2, 0] = np.einsum("ij,ij->i", e2, ex)
    x[:, 2, 1] = np.einsum("ij,ij->i", e2, ny)
    return x, area2 / 2, ok


def _uv_signed_areas(U, T):
    a, b, c = U[T[:, 0]], U[T[:, 1]], U[T[:, 2]]
    e1, e2 = b - a, c - a
    return (e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) / 2


# edge k of a triangle runs from corner _EI[k] to corner _EJ[k], opposite corner k
_EI = np.array([1, 2, 0])
_EJ = np.array([2, 0, 1])


def _cotangents(x, exact=False):
    """(m, 3) cotangent of each corner's angle (the weight of the opposite edge). Kept positive unless ``exact``:
    then right and obtuse corners keep their zero / negative weight, so every triangle counts by its area."""
    out = np.empty(x.shape[:2])
    for k in range(3):
        u = x[:, _EI[k]] - x[:, k]
        v = x[:, _EJ[k]] - x[:, k]
        cross = np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])
        out[:, k] = np.einsum("ij,ij->i", u, v) / np.maximum(cross, 1e-18)
    if exact:
        return np.clip(out / 2, -_WEIGHT_MAX, _WEIGHT_MAX)
    return np.clip(out / 2, _WEIGHT_MIN, _WEIGHT_MAX)


class _System:
    """The global step's linear system over the free UVs (a weighted graph Laplacian, matrix-free)."""

    def __init__(self, T, w, free, n):
        ii = T[:, _EI].ravel()
        jj = T[:, _EJ].ravel()
        ww = w.ravel()
        self.ii, self.jj, self.ww, self.n = ii, jj, ww, n
        self.free = free
        diag = np.bincount(ii, ww, n) + np.bincount(jj, ww, n)
        self.diag = np.maximum(diag, 1e-18)

    def apply(self, X):
        """Laplacian @ X for (n, 2) X."""
        d = (X[self.ii] - X[self.jj]) * self.ww[:, None]
        out = np.zeros_like(X)
        for c in range(2):
            out[:, c] = np.bincount(self.ii, d[:, c], self.n) - np.bincount(self.jj, d[:, c], self.n)
        return out

    def solve(self, B, X0, steps=_CG_STEPS):
        """Laplacian @ X = B on the free UVs, the held ones fixed at X0 (Jacobi-preconditioned conjugate gradient)."""
        free = self.free
        X = X0.copy()
        R = B - self.apply(X)
        R[~free] = 0.0
        if not free.any():
            return X
        if free.all():
            R -= R.mean(axis=0)       # no held UV: the system only knows the shape, not where it sits
        Z = R / self.diag[:, None]
        Pd = Z.copy()
        rz = np.einsum("ij,ij->j", R, Z)
        ref = max(float(np.einsum("ij,ij->", B, B)), 1e-30)
        for _ in range(steps):
            if float(np.einsum("ij,ij->", R, R)) <= _CG_TOL * ref:
                break
            AP = self.apply(Pd)
            AP[~free] = 0.0
            denom = np.einsum("ij,ij->j", Pd, AP)
            alpha = np.where(np.abs(denom) > 1e-30, rz / np.where(np.abs(denom) > 1e-30, denom, 1.0), 0.0)
            X += Pd * alpha
            R -= AP * alpha
            if free.all():
                R -= R.mean(axis=0)
            Z = R / self.diag[:, None]
            rz_new = np.einsum("ij,ij->j", R, Z)
            beta = np.where(rz > 1e-30, rz_new / np.where(rz > 1e-30, rz, 1.0), 0.0)
            Pd = Z + Pd * beta
            rz = rz_new
        return X


def _targets(U, T, x, w, surfangle):
    """Local step: per triangle the 2x2 map (a turn, scaled toward the triangle's own size as Surfangle drops) that
    brings its 3D shape closest to its current UV shape."""
    J = np.zeros((len(T), 2, 2))
    norm = np.zeros(len(T))
    for k in range(3):
        du = U[T[:, _EI[k]]] - U[T[:, _EJ[k]]]
        dx = x[:, _EI[k]] - x[:, _EJ[k]]
        J += w[:, k, None, None] * du[:, :, None] * dx[:, None, :]
        norm += w[:, k] * np.einsum("ij,ij->i", dx, dx)
    a = J[:, 0, 0] + J[:, 1, 1]
    b = J[:, 1, 0] - J[:, 0, 1]
    r = np.hypot(a, b)
    rs = np.where(r > 1e-30, r, 1.0)
    cos, sin = np.where(r > 1e-30, a / rs, 1.0), np.where(r > 1e-30, b / rs, 0.0)
    scale = np.ones(len(T))
    if surfangle < 1.0:
        s = r / np.maximum(norm, 1e-30)            # the triangle's best-fit size against its 3D shape
        scale = np.where(s > 1e-12, s, 1.0) ** (1.0 - surfangle)
    L = np.empty((len(T), 2, 2))
    L[:, 0, 0], L[:, 0, 1] = cos * scale, -sin * scale
    L[:, 1, 0], L[:, 1, 1] = sin * scale, cos * scale
    return L


def _rhs(T, x, w, L, n):
    B = np.zeros((n, 2))
    for k in range(3):
        i, j = T[:, _EI[k]], T[:, _EJ[k]]
        dx = x[:, _EI[k]] - x[:, _EJ[k]]
        v = np.einsum("tab,tb->ta", L, dx) * w[:, k, None]
        for c in range(2):
            B[:, c] += np.bincount(i, v[:, c], n) - np.bincount(j, v[:, c], n)
    return B


def _flipped(U, T, sign, ok):
    return ok & (_uv_signed_areas(U, T) * sign <= 0)


def optimize(P, U, T, held, iterations=1, surfangle=1.0, prevent_flips=True, steps=1, keep_centre=False):
    """Relax one shell. ``P`` (n, 3) the 3D point of each UV, ``U`` (n, 2) the UVs, ``T`` (m, 3) triangles over UV
    indices, ``held`` (n,) bool = UVs that must not move. ``iterations`` = Maya's Iterations (``steps`` local / global
    steps each). ``keep_centre``: a shell with nothing held keeps the mean of its UVs in place instead of one UV.
    Returns the new (n, 2) UVs."""
    P = np.asarray(P, float)
    U0 = np.asarray(U, float)
    T = np.asarray(T, int)
    held = np.asarray(held, bool)
    n = len(U0)
    if iterations <= 0 or n == 0 or len(T) == 0 or held.all():
        return U0.copy()
    x, area3, ok = _frames(P, T)
    T, x, area3, ok = T[ok], x[ok], area3[ok], np.ones(int(ok.sum()), bool)
    if not len(T):
        return U0.copy()
    used = np.zeros(n, bool)
    used[T.ravel()] = True
    held = held | ~used          # a UV on no usable triangle stays
    sa0 = _uv_signed_areas(U0, T)
    uv_area = float(np.abs(sa0).sum())
    total3 = float(area3.sum())
    if uv_area <= 1e-18 or total3 <= 1e-18:
        return U0.copy()
    x = x * math.sqrt(uv_area / total3)          # the 3D shapes at the shell's UV scale
    orient = 1.0 if float(sa0.sum()) >= 0 else -1.0
    if orient < 0:
        x = x.copy()
        x[:, :, 1] *= -1.0                       # a mirrored shell relaxes toward mirrored copies
    sign = orient                                # a triangle against the shell's own winding is turned over
    w = _cotangents(x)
    system = _System(T, w, ~held, n)
    U = U0.copy()
    for _ in range(max(1, int(iterations)) * max(1, int(steps))):
        L = _targets(U, T, x, w, surfangle)
        new = system.solve(_rhs(T, x, w, L, n), U)
        if prevent_flips:
            # no step may leave more triangles turned over than before it (on a clean shell: none at all)
            base = int(_flipped(U, T, sign, ok).sum())
            t = 1.0
            for _h in range(_FLIP_HALVINGS):
                trial = U + (new - U) * t
                if int(_flipped(trial, T, sign, ok).sum()) <= base:
                    new = trial
                    break
                t *= 0.5
            else:
                break
        U = new
    if not held.any():
        U = _keep_centre(U0, U, T, used) if keep_centre else _keep_place(U0, U, T)
    U[held] = U0[held]
    return U


def _keep_centre(U0, U, T, used):
    """A shell with nothing held: its UV area as before, with the mean of its UVs back where it was."""
    a0 = float(np.abs(_uv_signed_areas(U0, T)).sum())
    a1 = float(np.abs(_uv_signed_areas(U, T)).sum())
    k = math.sqrt(a0 / a1) if a1 > 1e-18 else 1.0
    c0, c1 = U0[used].mean(0), U[used].mean(0)
    out = U.copy()
    out[used] = c0 + (U[used] - c1) * k
    return out


def _keep_place(U0, U, T, anchor=0):
    """A shell with nothing held: its UV area as before, with the UV ``anchor`` back where it was (the shell keeps
    the turn the solve gave it)."""
    a0 = float(np.abs(_uv_signed_areas(U0, T)).sum())
    a1 = float(np.abs(_uv_signed_areas(U, T)).sum())
    k = math.sqrt(a0 / a1) if a1 > 1e-18 else 1.0
    return U0[anchor] + (U - U[anchor]) * k


# --- Legacy (relax) ------------------------------------------------------------------------------------------------

def relax_weights(P, faces, world_space):
    """{(i, j): weight} of the UV edges. Uniform: every edge of a face weighs 1. World space: each face is cut into
    a fan of triangles from its first corner and every triangle edge gets half the cotangent of the opposite 3D
    angle (summed over the triangles that share it)."""
    W = {}
    for f in faces:
        n = len(f)
        if not world_space:
            for k in range(n):
                a, b = f[k], f[(k + 1) % n]
                W[(a, b) if a < b else (b, a)] = 1.0
            continue
        for k in range(1, n - 1):
            tri = (f[0], f[k], f[k + 1])
            for c in range(3):
                o, a, b = tri[c], tri[(c + 1) % 3], tri[(c + 2) % 3]
                u, v = P[a] - P[o], P[b] - P[o]
                cross = float(np.linalg.norm(np.cross(u, v)))
                if cross < 1e-18:
                    continue
                key = (a, b) if a < b else (b, a)
                W[key] = W.get(key, 0.0) + float(np.dot(u, v)) / cross / 2
    return W


def relax(U, W, held, iterations=5):
    """Legacy (relax): ``iterations`` conjugate-gradient steps (u and v solved as one system) toward the weighted
    average of the neighbours, from the current UVs; ``held`` UVs stay. Returns the new (n, 2) UVs."""
    U0 = np.asarray(U, float)
    held = np.asarray(held, bool)
    out = U0.copy()
    free = np.flatnonzero(~held)
    if not len(free) or iterations <= 0 or not W:
        return out
    pos = -np.ones(len(U0), int)
    pos[free] = np.arange(len(free))
    m = len(free)
    diag = np.zeros(m)
    rows, cols, vals = [], [], []
    B = np.zeros((m, 2))
    for (a, b), w in W.items():
        for p, q in ((a, b), (b, a)):
            if pos[p] < 0:
                continue
            diag[pos[p]] += w
            if pos[q] >= 0:
                rows.append(pos[p])
                cols.append(pos[q])
                vals.append(-w)
            else:
                B[pos[p]] += w * U0[q]
    rows, cols, vals = np.array(rows, int), np.array(cols, int), np.array(vals, float)

    def apply(X):
        Y = X * diag[:, None]
        if len(vals):
            for c in range(2):
                Y[:, c] += np.bincount(rows, vals * X[cols, c], m)
        return Y

    X = U0[free].copy()
    R = B - apply(X)
    Pd = R.copy()
    rr = float((R * R).sum())
    for _ in range(int(iterations)):
        if rr < 1e-30:
            break
        AP = apply(Pd)
        denom = float((Pd * AP).sum())
        if abs(denom) < 1e-30:
            break
        alpha = rr / denom
        X += alpha * Pd
        R -= alpha * AP
        rr_new = float((R * R).sum())
        Pd = R + (rr_new / rr) * Pd
        rr = rr_new
    out[free] = X
    return out


# --- Unfold Along U / V -----------------------------------------------------------------------------------------

_ALONG_STEPS = 5000


def unfold_along(P, U, T, k, free):
    """Unfold along one UV axis (``k`` 0 = U, 1 = V): the other coordinate of every UV stays, the free UVs move along
    ``k`` and the held ones stay. Each triangle wants to be an undistorted copy of its 3D shape at the scale its fixed
    coordinate already has there (a strip whose V spans its 3D height gets the full 3D width in U), turned the way
    the shell faces; the solve runs to the end, so a second run changes nothing. A shell with no held UV keeps its
    mean along ``k``. Returns the new coordinate ``k`` of every UV, or None when no triangle has a 3D shape."""
    P = np.asarray(P, float)
    U = np.asarray(U, float)
    T = np.asarray(T, int).reshape(-1, 3)
    free = np.asarray(free, bool)
    if not len(T) or not free.any():
        return None
    x, _area, ok = _frames(P, T)
    if not ok.any():
        return None
    T, x = T[ok], x[ok]
    o = 1 - k
    # gradient of the fixed coordinate in each triangle's plane
    f = U[T, o]
    d1, d2 = f[:, 1] - f[:, 0], f[:, 2] - f[:, 0]
    x1, x2x, x2y = x[:, 1, 0], x[:, 2, 0], x[:, 2, 1]
    gx = d1 / x1
    gy = (d2 - gx * x2x) / x2y
    sign = 1.0 if _uv_signed_areas(U, T).sum() >= 0.0 else -1.0
    # the moving coordinate's gradient: the fixed one turned a quarter (U from V: clockwise, V from U: counter)
    tx, ty = (gy, -gx) if k == 0 else (-gy, gx)
    tx, ty = tx * sign, ty * sign
    w = _cotangents(x, exact=True)
    n = len(U)
    B = np.zeros((n, 2))
    for e in range(3):
        dx = x[:, _EI[e]] - x[:, _EJ[e]]
        t = w[:, e] * (tx * dx[:, 0] + ty * dx[:, 1])
        B[:, 0] += np.bincount(T[:, _EI[e]], t, n) - np.bincount(T[:, _EJ[e]], t, n)
    X0 = np.zeros((n, 2))
    X0[:, 0] = U[:, k]
    X = _System(T, w, free, n).solve(B, X0, _ALONG_STEPS)
    out = X[:, 0]
    if free.all():
        out = out + (U[:, k].mean() - out.mean())
    return out
