# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Outliner order: creation order numbers (#117).

Maya lists DAG nodes in creation order (a re-parented node last among its new siblings). The kit's Outliner tree
(``ui/outliner_tree.py``) sorts every sibling list by the object ID property ``allset_dag_order``: given when the kit
first sees an object, in link order (Blender appends new objects, so link order is creation order); the startup
cameras have -4 .. -1 so they lead. ``numbers`` computes the order without writing (the tree orders rows while
drawing), a timer writes the numbers of new objects once the structure changed, so a file keeps its order.
"""

import bpy

ORDER = "allset_dag_order"
INTERVAL = 0.25
_state = {"busy": False}


def sibling_lists(objects, key):
    """{parent or None: [children sorted by ``key``]} among ``objects`` (a parent outside them = top level)."""
    names = {o.name for o in objects}
    groups = {}
    for ob in objects:
        parent = ob.parent if ob.parent is not None and ob.parent.name in names else None
        groups.setdefault(parent.name if parent else None, []).append(ob)
    for obs in groups.values():
        obs.sort(key=key)
    return groups


def numbers(objects):
    """[(object, creation order number)]: ``allset_dag_order``, and for objects without one the next numbers in link
    order. Writes nothing (the kit Outliner tree orders rows while drawing).

    A duplicate carries its original's number (Blender copies ID properties, #217): of the objects sharing a number
    the oldest ID (lowest ``session_uid``) keeps it and the others count as new — Maya puts a duplicate last among its
    siblings."""
    holder = {}
    for ob in objects:
        n = ob.get(ORDER)
        if n is not None and (n not in holder or ob.session_uid < holder[n].session_uid):
            holder[n] = ob
    top = max(-1, max(holder, default=-1))
    out = []
    for ob in objects:
        n = ob.get(ORDER)
        if n is None or holder[n] is not ob:
            top += 1
            n = top
        out.append((ob, n))
    return out


def number_new(objects, rotate=True):
    """Write ``numbers`` into the objects that have none (or share their original's, a duplicate)."""
    for ob, n in numbers(objects):
        if ob.get(ORDER) != n:
            ob[ORDER] = n


def to_end(objects, scene):
    """Maya puts a re-parented node last among its new siblings: give ``objects`` the next numbers."""
    others = list(scene.objects)
    number_new(others)
    top = max((o.get(ORDER, -1) for o in others), default=-1)
    for ob in objects:
        top += 1
        ob[ORDER] = top


def place(scene, view_layer, moved, ref, after, reordered):
    """Maya Outliner MMB between rows: ``moved`` right before / after ``ref`` among ``ref``'s siblings (creation
    order numbers swapped among that list). ``reordered`` = outliner_drag.reordered. Returns False when ``ref`` has
    no sibling list."""
    number_new(list(scene.objects))
    sib = sibling_lists(list(scene.objects), key=lambda o: o.get(ORDER, 0))
    group = next((g for g in sib.values() if ref in g), None)
    if group is None:
        return False
    names = [o.name for o in group]
    shown = reordered(names, [o.name for o in moved], ref.name, after)
    values = sorted(o.get(ORDER, 0) for o in group)
    for name, v in zip(shown, values):
        bpy.data.objects[name][ORDER] = v
    from . import outliner
    outliner._bump()            # an ID property write tags nothing: the tree re-sorts on the version
    return True


def sync(scene, view_layer=None, rotate=None):
    """Number the scene's new objects. Returns True when it wrote a number."""
    objects = list(scene.objects)
    before = [o.get(ORDER) for o in objects]
    number_new(objects)
    return before != [o.get(ORDER) for o in objects]


def _tick():
    if _state["busy"]:
        return INTERVAL
    context = bpy.context
    try:
        from .outliner import structure_version
        scene = context.scene
        if scene is None:
            return INTERVAL
        version = (structure_version(), scene.as_pointer())
        if version == _state.get("synced"):
            return INTERVAL
        _state["busy"] = True
        sync(scene)
        _state["synced"] = version
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    finally:
        _state["busy"] = False
    return INTERVAL


def register():
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=INTERVAL, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
