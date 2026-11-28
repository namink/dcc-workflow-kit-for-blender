# SPDX-License-Identifier: GPL-3.0-or-later
"""Whole-file reads for the selection wire of thousands of objects: an object's row in ``bpy.data.objects`` by
session_uid (``_file_rows``; the sorted index is kept while the file's objects stay the same), Object enum values for
``foreach_get`` (``_enum_values``) and the world matrices of many objects in one read (``world_matrices``).
Related: ``selection_wire`` (``_highlight`` keeps its rows in ``_rows_of`` for ``world_matrices``).
"""

import bpy


_ENUMS = {}


def _enum_values(prop, names):
    """The integer values ``foreach_get`` reads for the identifiers ``names`` of Object enum property ``prop``."""
    key = (prop, names)
    got = _ENUMS.get(key)
    if got is None:
        items = bpy.types.Object.bl_rna.properties[prop].enum_items
        got = _ENUMS[key] = [items[name].value for name in names if name in items]
    return got


_file_index = []           # [(the file's session_uids, their sorting order, the sorted uids)] of the last look-up
_rows_of = []              # [(uids list ``_highlight`` returned, their rows in the file, found)] of the last redraw


def _file_rows(uids):
    """(rows, found) of the objects with session_uids ``uids`` (an int64 array) in ``bpy.data.objects``: one read of
    the file's session_uids into a C ``int`` buffer, each object found by binary search (the sorting is kept while
    the file's objects stay the same)."""
    import numpy as np
    coll = bpy.data.objects
    total = len(coll)
    if not total:
        return np.zeros(len(uids), np.intp), np.zeros(len(uids), bool)
    file_uids = np.empty(total, np.intc)
    coll.foreach_get("session_uid", file_uids)
    last = _file_index[0] if _file_index else None
    if last is not None and np.array_equal(last[0], file_uids):
        order, ordered = last[1], last[2]
    else:
        order = np.argsort(file_uids, kind='stable')
        ordered = file_uids[order]
        _file_index[:] = [(file_uids, order, ordered)]
    rows = order[np.minimum(np.searchsorted(ordered, uids), total - 1)]
    return rows, file_uids[rows] == uids


_NO_MATRIX = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


FILE_READ_FROM = 1 / 32    # ``world_matrices`` reads the whole file's matrices from this share of its objects on


def world_matrices(objects, uids=None):
    """(n, 4, 4) float64 world matrices (rows) of ``objects`` and an (n,) bool array: readable. Many objects: all of
    the file's matrices come in one ``foreach_get`` (in columns, like Blender's ``float[4][4]``), each row found by
    session_uid; flattening each object's Matrix in Python cost a few microseconds an object, tens of milliseconds for
    thousands of selected objects. A few objects of a big file: one by one. ``uids``: the objects' session_uids when
    known. Integer buffers are C ``int`` (``np.intc``): ``foreach_get`` copies into a buffer of another type code one
    item at a time."""
    import numpy as np
    n = len(objects)
    ok = np.ones(n, bool)
    worlds = np.zeros((n, 4, 4))
    missing = list(range(n))
    coll = bpy.data.objects
    total = len(coll)
    if n and total and n >= total * FILE_READ_FROM:
        try:
            want = np.array([ob.session_uid for ob in objects] if uids is None else uids, np.int64)
        except (AttributeError, ReferenceError):
            want = None
        if want is not None:
            flat = np.empty(total * 16, np.float32)
            coll.foreach_get("matrix_world", flat)
            known = _rows_of[0] if _rows_of and _rows_of[0][0] is uids else None
            rows, found = (known[1], known[2]) if known is not None else _file_rows(want)
            worlds = flat.reshape(total, 4, 4).transpose(0, 2, 1)[rows].astype(np.float64)
            missing = np.flatnonzero(~found).tolist()
    for k in missing:          # one by one, or not one of the file's objects
        try:
            mat = [v for row in objects[k].matrix_world for v in row]
        except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError, ReferenceError):
            mat = None
        if mat is None or len(mat) != 16:
            ok[k] = False
            mat = _NO_MATRIX
        worlds[k] = np.array(mat, np.float64).reshape(4, 4)
    return worlds, ok
