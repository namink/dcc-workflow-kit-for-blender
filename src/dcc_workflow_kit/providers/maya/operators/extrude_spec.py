# SPDX-License-Identifier: GPL-3.0-or-later
"""What the kit records per Maya modeling node: ``Spec`` (one node kind: fields, labels, defaults, Channel Box kinds,
arrow field, edit operator, build function), the ``SPECS`` registry (``add_spec``), ``BuildResult`` and the
polyExtrudeFace spec ``FACE`` with its field tables. Related: extrude.py (operators), extrude_edge_vertex.py,
bevel_maya.py and the other ``add_spec`` users.
"""

from mathutils import Vector

NODE = "polyExtrudeFace"
COUNTER = "allset_polyExtrudeFace"     # scene ID property: Maya numbers nodes per scene
FIELDS = ("thickness", "local_translate_z", "offset", "divisions", "keep_faces_together")
LABELS = {"thickness": "Thickness", "local_translate_z": "Local Translate Z", "offset": "Offset",
          "divisions": "Divisions", "keep_faces_together": "Keep Faces Together"}
DEFAULTS = {"thickness": 0.0, "local_translate_z": 0.0, "offset": 0.0, "divisions": 1, "keep_faces_together": True}
# polyExtrudeFace attributes only the manipulator handles set: not In-View / Channel Box rows
# (local handles, then the rotate rings and the world-axes handles of the manipulator's world / local switch)
MANIP_FIELDS = ("local_translate_x", "local_translate_y", "local_scale_x", "local_scale_y", "local_scale_z",
                *(f"local_rotate_{a}" for a in "xyz"),
                *(f"{t}_{a}" for t in ("translate", "rotate", "scale") for a in "xyz"))
MANIP_LABELS = {f: " ".join(w.capitalize() for w in f.split("_")) for f in MANIP_FIELDS}
MANIP_DEFAULTS = {f: (1.0 if "scale" in f else 0.0) for f in MANIP_FIELDS}
DEFAULTS.update(MANIP_DEFAULTS)
# Maya world X / Z in Blender world (Y-up -> Z-up: Maya Z = Blender -Y)
WORLD_X, MAYA_Z = Vector((1.0, 0.0, 0.0)), Vector((0.0, -1.0, 0.0))
NOTICE = "Edit-mode operations have no history in Blender: only the last one can be changed here."


class Spec:
    """One kind of Maya modeling node the kit records (edge / vertex extrusion, bevel).

    ``hidden`` = values ``build`` reads that show no row; ``view_fields`` = the In-View Editor rows (default: all); ``with_object``: ``build`` also gets ``ob=``.
    ``kinds`` = Channel Box text kind per field (cb_entry: "NONE" float, "INT", "BOOL"); ``arrow`` = the field the
    In-View manipulator arrow drags (None: no arrow); ``edit_op`` = the operator that rebuilds the node with new
    values (one undo step); ``build(bm, params, unit)`` (not FACE) -> the vertices to track."""

    def __init__(self, kind, node, fields, labels, defaults, kinds, arrow, edit_op, build=None, node_type=None,
                 manip=(), in_view=True, object_check=None, pre_uv=False, hidden=(), with_object=False,
                 view_fields=None, component=None, full_manip=False,
                 choices=None, enabled=None, atomic=False, preview=None, prepare=None, cleanup=None,
                 object_note=None):
        self.view_fields = tuple(view_fields if view_fields is not None else fields)   # In-View Editor rows
        self.component = component             # 'FACE' / 'EDGE' / 'VERTEX': where its manipulator points
        self.full_manip = full_manip           # every Local Translate / Local Scale handle (else only its arrow)
        self.prepare = prepare                 # (context, ob, record, params) -> params before a build
        self.cleanup = cleanup                 # (ob, old params, new params) after a failed build
        self.choices = choices or {}           # ENUM field -> (labels, values)
        self.enabled = enabled                 # (params, field) -> False greys the field out
        self.atomic = atomic                   # a failed build leaves the mesh as it was
        self.preview = preview                 # (ob, record, params, unit) -> True when it moved vertices only
        self.hidden = tuple(hidden)            # values build reads that have no row (an option-window setting)
        self.with_object = with_object         # build(bm, params, unit, ob=...) also gets the object
        self.pre_uv = pre_uv                   # a rerun on the same mesh also needs the same UVs (UV projections)
        self.in_view = in_view                 # the In-View Editor shows it (not a UV projection)
        self.object_check = object_check       # (ob, rec) -> the object-mode mesh is still the node's result
        self.object_note = object_note         # (ob) after an object-mode rebuild: remember what object_check reads
        self.node_type = node_type or node     # Maya node type (the AE history tab title)
        self.kind, self.node, self.fields, self.labels = kind, node, tuple(fields), dict(labels)
        self.manip = tuple(manip)              # values only the manipulator sets: not shown as rows
        self.defaults, self.kinds, self.arrow, self.edit_op, self.build = dict(defaults), dict(kinds), arrow, \
            edit_op, build

    @property
    def all_fields(self):
        return self.fields + self.manip

    @property
    def counter(self):
        return "allset_" + self.node


SPECS = {}


class BuildResult(list):
    """Tracked vertices with optional backend data for coordinate-only previews."""
    def __init__(self, vertices, preview_data):
        super().__init__(vertices)
        self.preview_data = preview_data


def add_spec(spec):
    SPECS[spec.kind] = spec
    return spec


FACE = add_spec(Spec('FACE', NODE, FIELDS, dict(LABELS, **MANIP_LABELS), DEFAULTS,
                     dict({"thickness": "NONE", "local_translate_z": "NONE", "offset": "NONE", "divisions": "INT",
                           "keep_faces_together": "BOOL"}, **{k: "NONE" for k in MANIP_FIELDS}),
                     "local_translate_z", "extrude_edit", manip=MANIP_FIELDS))
