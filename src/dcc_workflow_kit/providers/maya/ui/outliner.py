# SPDX-License-Identifier: GPL-3.0-or-later
"""The scene-structure version the kit's Outliner tree (``ui/outliner_tree.py``) and other structure caches key on.

``structure_version`` goes up whenever names, parents, membership or bones may have changed: every depsgraph update
the row check doesn't skip (``depsgraph_filter.outliner_skip``: motion only, or the Scene alone — a selection; also a
joint selection and the steps of a move in Object / Pose Mode), a file load, undo and redo. Code that derives something from the scene's structure keeps it until this changes.

``objects_version`` goes up only when objects may have come or gone (a Collection flag on the update, load, undo,
redo): lists of objects picked from the whole scene by type or custom property key on it.
"""

import bpy
from bpy.app.handlers import persistent

from .. import depsgraph_filter

_state = {"version": 0, "objects": 0}


def _bump():
    _state["version"] += 1


def structure_version():
    """Goes up whenever names, parents, membership or bones may have changed (any update the row check doesn't skip,
    load, undo, redo): code that derives something from the scene's structure keeps it until this changes."""
    return _state["version"]


def objects_version():
    """Goes up whenever objects may have been added to or removed from the file, a scene, a collection or a view layer:
    a depsgraph update that flags Collections (add, delete, link, unlink, duplicate — also during a move —, a
    collection's exclude or hide; parenting and constraint edits flag them too), load, undo and redo. Current for
    every kit depsgraph handler of the same update (its handler runs first). An object made in no collection
    (``bpy.data.objects.new`` alone) flags no Collection: code that makes one drops what it keeps on this itself."""
    return _state["objects"]


def _objects_changed():
    _state["objects"] += 1


_SKELETONS = {}     # skeleton object pointer -> ``_skeleton_rows`` when last seen


def _skeleton_rows(ob):
    """What of skeleton ``ob`` the structure holds outside Edit Mode (bones are re-parented only there): its name,
    parent and Outliner flag, and its joints' names in order."""
    p = ob.parent
    return (ob.name, p.as_pointer() if p is not None else 0, ob.parent_type, ob.parent_bone,
            bool(ob.get("allset_hidden_in_outliner")), tuple(ob.pose.bones.keys()) if ob.pose is not None else ())


def _joint_selection_only(scene, look):
    """The update (``depsgraph_filter.Look``) can't change the structure: a joint selection (it updates the skeleton
    and its data, Blender re-evaluates the meshes it deforms) — every skeleton it touched holds the same names,
    parent and joints as when last seen; anything else it touched only moved or was re-evaluated. The skeletons come
    from the update itself; only when an armature's data has users the update doesn't hold (another object, a fake
    user) are the scene's objects read."""
    if look is None or scene is None:
        return False
    touched = {}            # armature data pointer -> skeleton objects of the update using it
    users = {}              # armature data pointer -> how many objects can use it (users less a fake user)
    for id_, moved in look.entries:
        if isinstance(id_, bpy.types.Scene):
            continue
        if isinstance(id_, bpy.types.Armature):
            if id_.is_editmode:
                return False
            arm = id_.original
            ptr = arm.as_pointer()
            touched.setdefault(ptr, [])
            users[ptr] = arm.users - int(arm.use_fake_user)
            continue
        if not isinstance(id_, bpy.types.Object):
            return False
        if id_.type == 'ARMATURE':
            ob = id_.original
            data = ob.data
            ptr = data.as_pointer() if data is not None else 0
            touched.setdefault(ptr, []).append(ob)
            if data is not None:
                users[ptr] = data.users - int(data.use_fake_user)
        elif not moved:
            return False                # renamed, re-parented, a custom property: not a motion
    if not touched:
        return False
    if all(ptr and len(obs) >= users.get(ptr, len(obs) + 1) for ptr, obs in touched.items()):
        skeletons = [ob for obs in touched.values() for ob in obs]
    else:
        skeletons = [ob for ob in scene.objects if ob.type == 'ARMATURE' and ob.data is not None
                     and ob.data.as_pointer() in touched]
    same = True
    for ob in skeletons:
        sig = _skeleton_rows(ob)
        if _SKELETONS.get(ob.as_pointer()) != sig:
            same = False
            if len(_SKELETONS) > 256:
                _SKELETONS.clear()
            _SKELETONS[ob.as_pointer()] = sig
    return same


def _posing():
    """A move / rotate / scale runs in Object or Pose Mode: until it ends only poses and transforms change (every
    step of a pose drag updates the skeleton's data)."""
    from . import maya_joints
    return getattr(bpy.context, "mode", None) in {'OBJECT', 'POSE'} and maya_joints.transforming()


@persistent
def _on_depsgraph(scene, depsgraph):
    # #191: the rows are names / parents / membership / bones — a move, a mesh edit or a selection change can't
    # change them (one pass over the update for every test). A running move / rotate / scale keeps the structure
    # whatever the update holds, so it is asked first: each of its steps skips the pass over the update.
    try:
        posing = _posing()
    except (ReferenceError, AttributeError):
        posing = None
    if posing:
        return
    look = depsgraph_filter.Look(depsgraph) if depsgraph is not None else None
    if look is not None and look.outliner_skip():
        return
    if posing is not None:
        try:
            if _joint_selection_only(scene, look):
                return
        except (ReferenceError, AttributeError):
            pass
    _bump()


@persistent
def _on_update_first(_scene, depsgraph=None):
    """``objects_version``: inserted first among the depsgraph handlers. ``id_type_updated`` reads one flag (no pass
    over the update)."""
    if depsgraph is None or depsgraph.id_type_updated('COLLECTION'):
        _objects_changed()


@persistent
def _on_undo(_dummy):
    _SKELETONS.clear()
    _bump()
    _objects_changed()


@persistent
def _on_load(_dummy):
    _SKELETONS.clear()
    _bump()
    _objects_changed()


_HANDLERS = ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph), (bpy.app.handlers.load_post, _on_load),
             (bpy.app.handlers.undo_post, _on_undo), (bpy.app.handlers.redo_post, _on_undo))


def register():
    for handlers, fn in _HANDLERS:
        if fn not in handlers:
            handlers.append(fn)
    first = bpy.app.handlers.depsgraph_update_post
    if _on_update_first not in first:
        first.insert(0, _on_update_first)
    _bump()
    _objects_changed()


def unregister():
    for handlers, fn in _HANDLERS + ((bpy.app.handlers.depsgraph_update_post, _on_update_first),):
        while fn in handlers:
            handlers.remove(fn)
    _SKELETONS.clear()
