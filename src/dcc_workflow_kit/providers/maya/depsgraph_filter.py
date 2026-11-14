# SPDX-License-Identifier: GPL-3.0-or-later
"""#191: cheap tests on a depsgraph update, so handlers that scan the whole scene skip updates that can't
change what they look at. Blender's ``depsgraph.updates`` per kind of edit (5.2):

- move / rotate / scale, playback: the Object (or its data) with ``is_updated_transform``;
- mesh / curve edits: the data (or the evaluated Object) with ``is_updated_geometry``;
- rename, custom properties, parent pointer written from Python: the Object with no flag;
- selection, active object, ``hide_set``: the Scene only;
- parent / unparent: Scene + Objects; add / delete / link / hide_viewport: Scene + Collection + Objects;
- edit-mode bone add / rename: the Armature data.

A pass over ``depsgraph.updates`` walks every ID the depsgraph holds (about 0.3 ms with 5,000 objects), so a handler
reads it once (``Look``) and answers what it can from ``depsgraph.id_type_updated`` first: the type of every entry
is flagged there (a flag can also be set with no entry of that type: a selection flags OBJECT)."""

import bpy


def only_motion(depsgraph):
    """True when every update is a transform or geometry change of a non-Scene / non-Collection ID — nothing that
    adds, removes, renames, re-parents, hides or selects."""
    if depsgraph is None:
        return False
    seen = False
    for u in depsgraph.updates:
        seen = True
        if isinstance(u.id, (bpy.types.Scene, bpy.types.Collection)):
            return False
        if not (u.is_updated_transform or u.is_updated_geometry):
            return False
    return seen


def only_scene(depsgraph):
    """True when the update is the Scene alone (selection, active object, ``hide_set``)."""
    if depsgraph is None or not depsgraph.id_type_updated('SCENE'):
        return False                    # no Scene entry: not a selection
    seen = False
    for u in depsgraph.updates:
        seen = True
        if not isinstance(u.id, bpy.types.Scene):
            return False
    return seen


class Look:
    """One pass over a depsgraph update: its entries (evaluated ID, moved = a transform or geometry change) and the
    ``only_scene`` / ``only_motion`` answers, for a handler that tests several things on the same update."""

    __slots__ = ("entries", "scene_only", "motion", "collection", "armature")

    def __init__(self, depsgraph):
        entries = []
        scene_only = motion = True
        collection = armature = False
        for u in depsgraph.updates:
            id_ = u.id
            moved = u.is_updated_transform or u.is_updated_geometry
            entries.append((id_, moved))
            if isinstance(id_, bpy.types.Scene):
                motion = False
                continue
            scene_only = False
            if isinstance(id_, bpy.types.Collection):
                collection, motion = True, False
                continue
            if isinstance(id_, bpy.types.Armature):
                armature = True
            if not moved:
                motion = False
        self.entries = entries
        self.scene_only = bool(entries) and scene_only      # = only_scene
        self.motion = bool(entries) and motion              # = only_motion
        self.collection = collection                        # a Collection entry
        self.armature = armature                            # an Armature data entry

    def outliner_skip(self):
        """= ``outliner_skip`` of the same update."""
        return not self.armature and (self.scene_only or self.motion)


def outliner_skip(depsgraph):
    """The kit Outliner's rows (names, parents, membership, bones) can't change: motion only, or the Scene alone. An
    Armature data update (edit-mode bones) always counts."""
    if depsgraph is None:
        return False
    return Look(depsgraph).outliner_skip()


def structure_changed(depsgraph):
    """Objects may have been added or removed: a Scene or Collection update."""
    if depsgraph is None:
        return True
    return depsgraph.id_type_updated('SCENE') or depsgraph.id_type_updated('COLLECTION')
