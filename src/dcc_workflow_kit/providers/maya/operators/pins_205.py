# SPDX-License-Identifier: GPL-3.0-or-later
"""Issue #112: Constrain > UV Pin / Proximity Pin, Deform > Display / Hide Intermediate Objects,
Deform > Wrap > Add / Remove Influence.

Maya behaviour (Maya's option windows):

- UV Pin: default = Pin locations
  *Transforms*, Output *Existing Transform*, Normal axis X, Tangent axis Y, UV set "" (current), Normalize isoparms on.
  The geometry is selected first, then the transforms. For each transform the UV at the closest point of the
  geometry becomes an input of one uvPin node (``uvPin1``); the transform's translate /
  rotate / scale are cleared, the node's output matrix drives its offsetParentMatrix
  and inheritsTransform is turned off ("Inherit transform has been turned off for [...]"). Components mode (option)
  pins new ``pinOutput`` transforms / locators to the selected vertices' UVs, faces' mean UV, edges' mid UV;
  with Existing Transform it errors "Output mode does not work with this creation mode".
- Proximity Pin: default = Setup Transforms,
  Output Existing Transform, Input *New Locator*, Maintain offset on, Mode Edge, axes X / Y. One proximityPin node; per
  transform a ``pinInput`` locator holding the transform's matrix relative to the geometry, the transform cleared and
  driven by the node. Components setup: "Not yet implemented...".

The kit: a pinned transform gets a Copy Transforms constraint named like the Maya node (``uvPin1``) in mode Before
Original (Full) — world = pin matrix @ own channels, Maya's offsetParentMatrix with inheritsTransform off (the
"Inherit transform has been turned off" warning lists every pinned existing transform, like Maya) — targeting a hidden
helper empty that a depsgraph / frame handler keeps at the pin matrix (the pattern of operators/constrain_199.py). The
pin matrix follows Maya's rules: quad locations are bilinear (s, t), normal = blend of Maya vertex normals (unit
face-normal average), tangent = dP/du of the face's first triangle; UV Pin = the frame at the stored UV on the deformed
mesh; Proximity Pin = the closest point of the *original* mesh to pinInput at every evaluation, output = F1 · F0⁻¹ ·
input (Offset Translation 0 = on the surface, Offset Orientation 0 = Edge / UV orientation, Envelope = slerp / lerp
towards the input). Deformed points = the evaluated mesh when its topology equals the mesh's (the smooth preview: its
first vertices).

Intermediate objects: Maya's intermediate object of a deformed shape is its
``<shape>Orig`` (every mesh deformer adds one); Display sets intermediateObject 0
on it and selects it, Hide sets it back and selects the deformed objects. Blender keeps the undeformed mesh as the
object's own data, so the kit shows it as a child object ``<shape>Orig`` sharing that mesh with no modifiers (edits
to it edit the original shape, like Maya) and deletes it on Hide. Base wires / pin and constraint helpers
are not intermediate objects in Maya (curve1BaseWire = a hidden transform) and stay as they are.

Wrap influences (Maya's Wrap deformer): the deformed surfaces are selected, the influence last. Blender's
Surface Deform reads one target, so every extra influence is one more Surface Deform ``wrap1Influence<k>`` (+ its Hook
``wrap1Influence<k>Base`` like wrap1Base) and each wrapped point follows the influence nearest to it (its weight moves to
that influence's vertex group; Maya blends influences by distance). Removing the last influence removes
the wrap node (Maya keeps an empty wrap1).

Code: pin_geometry (surface frames), pin_update (helper keys, pin matrix, ``update``), pin_create (UV / Proximity
Pin and their option windows), intermediate_objects, wrap_influence; this module keeps the depsgraph / frame / load
handlers, the classes tuple and re-exports the names of those modules.
"""

import bpy

from .pin_geometry import Geo  # noqa: F401
from .pin_update import (AXES, AXIS_ITEMS, ENVELOPE, GEOM, INPUT, INPUT_MATRIX, KIND, MODE, NODE, OFFSET, OFFSET_O,
                         OFFSET_T, OWNER, PIN_TYPES, UV, _rescan, _state, geometry_of, helper_of, helpers,
                         node_name, offsets, pin_matrix, pin_type, update)  # noqa: F401
from .pin_create import (ALLSET_OT_proximity_pin, ALLSET_OT_uv_pin, HINT_PROX, HINT_UV, MSG_AXIS, MSG_GEOMETRY,
                         MSG_INHERIT, MSG_IO, MSG_NO_COMPONENTS, MSG_NOT_IMPLEMENTED, MSG_OUTPUT_MODE, WINDOWS,
                         _axes, new_node, proximity_pin, uv_pin, windows)  # noqa: F401
from .intermediate_objects import (ALLSET_OT_intermediate_objects, INTERMEDIATE_OF, MSG_ALREADY_OFF,
                                   MSG_ALREADY_ON, MSG_FOUND_NONE, MSG_NO_DEFORMABLE, display_intermediate,
                                   hide_intermediate, intermediates_of, is_deformed, is_intermediate)  # noqa: F401
from .wrap_influence import (ALLSET_OT_wrap_influence, MSG_NO_WRAP, MSG_WRAP_INFLUENCE, MSG_WRAP_SELECT,
                             add_wrap_influence, remove_wrap_influence, wrap_influence)  # noqa: F401


@bpy.app.handlers.persistent
def _on_depsgraph(scene, depsgraph):
    update(depsgraph)


@bpy.app.handlers.persistent
def _on_frame(scene, depsgraph=None):
    update(depsgraph)


@bpy.app.handlers.persistent
def _on_load(*_args):
    _rescan()


_HANDLERS = (("depsgraph_update_post", _on_depsgraph), ("frame_change_post", _on_frame),
             ("load_post", _on_load), ("undo_post", _on_load), ("redo_post", _on_load))


def register_handlers():
    for attr, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, attr)
        if fn not in lst:
            lst.append(fn)


def unregister_handlers():
    for attr, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, attr)
        if fn in lst:
            lst.remove(fn)
    _rescan()


classes = (ALLSET_OT_uv_pin, ALLSET_OT_proximity_pin, ALLSET_OT_intermediate_objects, ALLSET_OT_wrap_influence)
