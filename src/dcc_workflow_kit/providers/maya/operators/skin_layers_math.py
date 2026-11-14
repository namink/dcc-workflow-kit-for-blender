# SPDX-License-Identifier: GPL-3.0-or-later
"""Skin layer maths (no bpy): how a stack of skin weight layers becomes one set of skin weights, like Maya's Skin
Tools.

A layer holds its own weights per vertex and influence, a mask (0..1 per vertex, None = the whole mesh) and an
opacity. Layers are listed top first. The result is built from the bottom up: each enabled layer covers the result
below it by ``mask * opacity``; where the layer's own weights add up to less than 1 the lower result shows through
for the rest (an empty layer changes nothing, a full one with mask 1 and opacity 1 replaces what is below). The final
weights of every vertex that has any weight are normalised to 1.
"""

import numpy as np

EPS = 1e-9


def clamp_rows(w):
    """Rows of ``w`` (V, K) whose sum is above 1 scaled down to 1 (a layer never weighs more than the whole)."""
    w = np.clip(np.asarray(w, dtype=float), 0.0, None)
    s = w.sum(axis=1, keepdims=True)
    return np.divide(w, s, out=w.copy(), where=s > 1.0)


def coverage(mask, opacity, count):
    """Per-vertex alpha of a layer: mask (None = 1) times opacity, clamped to [0, 1]."""
    a = np.ones(count) if mask is None else np.clip(np.asarray(mask, dtype=float), 0.0, 1.0)
    return np.clip(a * float(opacity), 0.0, 1.0)


def composite(layers, count, influences):
    """Final (V, K) weights from ``layers`` = top-first list of dicts {"weights": {influence: (V,)}, "mask": (V,) |
    None, "opacity": float, "enabled": bool}; ``influences`` = the K column names."""
    col = {n: j for j, n in enumerate(influences)}
    r = np.zeros((count, len(influences)))
    for layer in reversed(list(layers)):
        if not layer.get("enabled", True):
            continue
        lw = np.zeros_like(r)
        for name, values in layer.get("weights", {}).items():
            j = col.get(name)
            if j is not None:
                lw[:, j] = np.asarray(values, dtype=float)[:count]
        lw = clamp_rows(lw)
        s = lw.sum(axis=1)
        a = coverage(layer.get("mask"), layer.get("opacity", 1.0), count)
        r = a[:, None] * lw + (1.0 - a * s)[:, None] * r
    return normalize_rows(r)


def normalize_rows(w):
    w = np.asarray(w, dtype=float)
    s = w.sum(axis=1, keepdims=True)
    out = np.divide(w, s, out=np.zeros_like(w), where=s > EPS)
    out[np.abs(out) < 1e-12] = 0.0
    return out


def settle_rows(old, new, changed_cols=None):
    """Layer weights after an edit: on each row where some columns changed from ``old`` to ``new``, the changed
    columns keep their new values (clamped to [0, 1], their total to 1) and the unchanged columns are scaled down to
    fill 1 − changed total only when they weigh more than that (never raised). Rows with no change are kept.
    ``changed_cols`` (K bools) forces which columns count as edited on changed rows."""
    old = np.asarray(old, dtype=float)
    new = np.clip(np.asarray(new, dtype=float), 0.0, 1.0)
    out = new.copy()
    diff = np.abs(new - old) > 1e-7
    rows = np.flatnonzero(diff.any(axis=1))
    for i in rows:
        edited = diff[i] if changed_cols is None else np.asarray(changed_cols, dtype=bool) | diff[i]
        e_total = out[i, edited].sum()
        if e_total > 1.0:
            out[i, edited] /= e_total
            e_total = 1.0
        rest = ~edited
        r_total = out[i, rest].sum()
        room = max(0.0, 1.0 - e_total)
        if r_total > room + 1e-12:
            out[i, rest] *= room / r_total if r_total > 0 else 0.0
    out[np.abs(out) < 1e-12] = 0.0
    return out


def set_value(w, rows, col, mode, intensity):
    """Set Weights on layer weights ``w`` (V, K) for ``rows`` and influence column ``col``: REPLACE = intensity,
    ADD = + intensity, SCALE = × intensity (then ``settle_rows``)."""
    w = np.asarray(w, dtype=float)
    new = w.copy()
    rows = np.asarray(rows, dtype=int)
    if mode == "REPLACE":
        new[rows, col] = intensity
    elif mode == "ADD":
        new[rows, col] = w[rows, col] + intensity
    elif mode == "SCALE":
        new[rows, col] = w[rows, col] * intensity
    else:
        raise ValueError(mode)
    new = np.clip(new, 0.0, 1.0)
    forced = np.zeros(w.shape[1], dtype=bool)
    forced[col] = True
    out = w.copy()
    out[rows] = settle_rows(w[rows], new[rows], forced)
    return out


def smooth(values, neighbours, rows, intensity, iterations=1):
    """Smooth ``values`` ((V,) or (V, K)) on ``rows``: each pass moves a row toward the mean of its neighbours by
    ``intensity``; other rows only feed their values. ``neighbours`` = list of index lists per vertex."""
    v = np.asarray(values, dtype=float).copy()
    rows = [int(i) for i in rows]
    t = float(np.clip(intensity, 0.0, 1.0))
    for _ in range(max(1, int(iterations))):
        cur = v.copy()
        for i in rows:
            nb = neighbours[i]
            if nb:
                v[i] = (1.0 - t) * cur[i] + t * cur[list(nb)].mean(axis=0)
    return v


def mirror_columns(w, partner_rows, column_pair, dst_rows):
    """Mirror layer weights: each destination row ``dst_rows[k]`` takes the weights of ``partner_rows[k]`` with its
    columns renamed by ``column_pair`` (index -> index)."""
    w = np.asarray(w, dtype=float)
    out = w.copy()
    for d, s in zip(dst_rows, partner_rows):
        row = np.zeros(w.shape[1])
        for j in range(w.shape[1]):
            row[column_pair.get(j, j)] += w[s, j]
        out[d] = row
    return out


def closest_joint(distances):
    """Assign from Closest Joint: (V, K) distances -> (V, K) weights, 1 on the nearest column of each row."""
    d = np.asarray(distances, dtype=float)
    out = np.zeros_like(d)
    if d.size:
        out[np.arange(len(d)), d.argmin(axis=1)] = 1.0
    return out
