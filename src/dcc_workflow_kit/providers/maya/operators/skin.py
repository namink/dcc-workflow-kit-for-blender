# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya IK handles and skinning: IK Handle Tool, Pole Vector, Bind / Unbind Skin, Paint Skin Weights, Copy /
Mirror Skin Weights, Copy / Paste Vertex Weights.

Maya rigging: skin = Armature modifier + vertex
groups named after the joints). A Maya joint is a bone's head (or the
tail of a chain end); Blender's IK pulls a bone's tail, so a Maya IK handle on end joint J is an IK
constraint on the bone whose tail is J.

Code: ik_handle (IK Handle Tool, Pole Vector), skin_bind (Bind / Unbind Skin, Reset Default Weights, Move Skinned
Joints), paint_skin_weights, skin_copy_mirror, skin_cluster (shared skin helpers); this module re-exports their
names and lists the operator classes in register order.
"""

from .skin_cluster import (armature_modifier, armature_modifiers, _cb, colorize, influences, JOINT_COLORS, NORMALIZE,
                           normalize_mode, NORMALIZE_PROP, PAINT_SEEN, _skin_part, skinned_mesh)  # noqa: F401
from .ik_handle import (ALLSET_OT_ik_handle, ALLSET_OT_pole_vector, _chain_heads, create_ik, ik_chain,
                        ik_constraints_on, IK_SOLVERS, IK_STATUS, _incoming, joint_position, joints_of, pick_joint,
                        PICK_RADIUS, pole_angle, selected_pair, set_pole, _signed_angle)  # noqa: F401
from .skin_bind import (ALLSET_OT_bind_skin, ALLSET_OT_move_skinned_joints, ALLSET_OT_reset_skin_weights,
                        ALLSET_OT_skin_cluster_answer, ALLSET_OT_skin_cluster_question, ALLSET_OT_unbind_skin,
                        _bind_closest, BIND_METHODS, bind_skin, closest_distance_weights, DROPOFF, hierarchy_candidates,
                        joint_hierarchy, joint_segments, move_skinned_joints, name_skin_cluster, _near_identity,
                        ON_JOINT, QUESTION, question_text, SECOND_SKIN_NOTE, SKINNING, unbind, UNBIND_HISTORY,
                        unpose_mesh)  # noqa: F401
from .paint_skin_weights import (ALLSET_OT_flood_weights, ALLSET_OT_paint_skin_weights, ALLSET_OT_weight_paint_exit,
                                 apply_paint_settings, _brush_set, first_influence, leave_weight_paint, PAINT_BLEND,
                                 PAINT_FIELDS, PAINT_OPERATIONS, PAINT_PROFILES, PROFILE_CURVE,
                                 set_view_tool)  # noqa: F401
from .skin_copy_mirror import (ALLSET_OT_copy_skin_weights, ALLSET_OT_copy_vertex_weights,
                               ALLSET_OT_mirror_skin_weights, ALLSET_OT_paste_vertex_weights, associate, _edit_bmesh,
                               _hierarchy_order, INFLUENCE_ASSOCIATION, mirror_group_names, MIRROR_INFLUENCE,
                               MIRROR_INFLUENCE_2, _mirror_label_partner, mirror_weights, PLANE_AXIS, _reflect,
                               remap_influences, _segment_distance, SURFACE_ASSOCIATION, surface_weights, VERT_MAPPING,
                               _VERTEX_CLIPBOARD)  # noqa: F401


classes = (ALLSET_OT_move_skinned_joints, ALLSET_OT_reset_skin_weights, ALLSET_OT_ik_handle, ALLSET_OT_pole_vector, ALLSET_OT_skin_cluster_question,
           ALLSET_OT_skin_cluster_answer, ALLSET_OT_bind_skin, ALLSET_OT_unbind_skin,
           ALLSET_OT_paint_skin_weights, ALLSET_OT_weight_paint_exit, ALLSET_OT_flood_weights, ALLSET_OT_copy_skin_weights, ALLSET_OT_mirror_skin_weights,
           ALLSET_OT_copy_vertex_weights, ALLSET_OT_paste_vertex_weights)
