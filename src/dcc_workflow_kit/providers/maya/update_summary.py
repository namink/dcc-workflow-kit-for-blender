# SPDX-License-Identifier: GPL-3.0-or-later
"""One pass over a depsgraph update for every kit handler that reads it.

Blender calls each ``depsgraph_update_post`` handler of a round with the same update, and a pass over
``depsgraph.updates`` walks every data-block the depsgraph holds. ``_round_start`` (first in the list) and
``_round_end`` (last) mark a round; the first kit handler that asks (``updates``) walks the update once and keeps the
entries, the kit handlers after it get the same entries.

The kept entries are only given while nothing between the handler that walked and the one that asks can have changed
the update: Blender reads each data-block's flags as the update is walked, so a handler that tags a data-block during
the round adds it to what the handlers after it see, and one that evaluates the depsgraph again
(``view_layer.update()`` runs a nested round) leaves the rest of the round an empty update. So every handler in
between must be declared here: ``READERS`` write nothing during a round, ``REPORTERS`` call ``wrote()`` before they
write. Any other handler (another add-on's, a test's, a kit handler listed in ``WRITERS`` or not listed) makes the
next asker walk again, as do ``wrote()`` and the end of a nested round. Outside a round (a handler called directly, a
stand-in depsgraph) and when the asker isn't in the list, ``updates`` is ``depsgraph.updates`` itself.

``ENABLED`` False (``ALLSET_UPDATE_SUMMARY=0``): every asker walks the update itself. ``CHECK``
(``ALLSET_UPDATE_SUMMARY_CHECK=1``): each reuse is compared with a new walk; a difference goes to ``MISMATCHES`` (and
is printed) and the new walk is used."""

import operator
import os

import bpy
from bpy.app.handlers import persistent

ENABLED = os.environ.get("ALLSET_UPDATE_SUMMARY", "1") != "0"
CHECK = os.environ.get("ALLSET_UPDATE_SUMMARY_CHECK", "") == "1"
RECOMPUTE = True        # False only in tests: keep the entries across every handler (what the rules above prevent)
MISMATCHES = []         # (asking handler, entries kept, entries of a new walk) found by CHECK
STATS = {"walks": 0, "reuses": 0}
_MAX_MISMATCHES = 100

_PACKAGE = __name__.rsplit(".", 1)[0]

# Kit depsgraph_update_post handlers that write nothing to the file during a round (they keep caches, counters or
# timers of their own), as "<module under the package>:<function>".
READERS = frozenset((
    "ui.outliner:_on_update_first", "ui.layer_joints:_on_depsgraph", "ui.channel_box:_on_scene_change",
    "operators.constrain_multi:_on_depsgraph", "operators.blend_shapes_227:_on_depsgraph",
    "operators.surfaces_maya:_on_depsgraph", "operators.pick_order:_on_depsgraph", "operators.bridge_curve:changed",
    "operators.model_history:changed", "operators.tool_keys:_on_depsgraph", "operators.pivot_follow:_on_depsgraph",
    "operators.autosave:_on_change", "operators.preselect:invalidate", "operators.cut_sew:_invalidate",
    "operators.outliner_drag:_on_depsgraph", "operators.undo_pairs:_on_depsgraph", "operators.auto_key:_on_depsgraph",
    "operators.anim_snapshot:_on_depsgraph", "operators.graph_curves_203:_on_depsgraph", "ui.outliner:_on_depsgraph",
    "ui.time_slider:_drop_held", "ui.selection_wire:_on_depsgraph", "ui.maya_joints:_depsgraph_post",
    "ui.component_colors:_on_depsgraph", "ui.ghosting:_on_depsgraph", "ui.weight_numbers:_on_depsgraph",
    "ui.uv_display:_invalidate", "ui.uv_shell_preview:_invalidate", "ui.uv_hud:_invalidate",
    "ui.graph_keys_draw:_on_depsgraph", "ui.component_editor:_on_depsgraph", "ui.hypergraph:_on_depsgraph",
    "operators.skin_layers:on_depsgraph", "ui.soft_overlay:_on_depsgraph", "command_line.undo_text:_on_depsgraph",
    "operators.joint_marquee:_count", "ui.maya_grid_depth:_depth_on_depsgraph",
    "ui.distance_dimensions:_on_depsgraph", "ui.editor_chrome:_drop_stats_on_keys"))

# Kit depsgraph_update_post handlers that call ``wrote()`` before anything they write during a round (most write only
# what differs, so a round with nothing to change keeps the walk).
REPORTERS = frozenset((
    "operators.constrain_interp:_on_update", "operators.ik_rp:_on_update", "operators.live:changed",
    "operators.driven_key:_after_update", "operators.graph_key_menu:_keys_depsgraph",
    "operators.symmetry:_on_depsgraph", "operators.soft_select:_on_depsgraph", "operators.pivot:_on_depsgraph",
    "operators.material:_on_depsgraph", "operators.dag:_on_depsgraph", "operators.graph_weights:_on_depsgraph",
    "operators.skin_tools_199:_sync_sum_modifiers", "operators.constrain_199:_on_depsgraph",
    "operators.pins_205:_on_depsgraph", "operators.deformers_205b:_on_depsgraph",
    "operators.deformers_205a:_on_depsgraph", "operators.curves_207:_on_depsgraph",
    "operators.type_manip:_on_depsgraph", "operators.playback_maya:_on_depsgraph", "ui.channel_box:_on_depsgraph",
    "operators.bend_deformer:_on_update", "operators.ik_fk_control:_on_update"))

# Kit depsgraph_update_post handlers that can write during a round without saying so: the handlers after them walk
# the update again, as after any handler that isn't declared.
WRITERS = frozenset()


class Update:
    """One entry of a depsgraph update as ``depsgraph.updates`` gives it: the evaluated data-block and its flags."""

    __slots__ = ("id", "is_updated_geometry", "is_updated_transform", "is_updated_shading")

    def __init__(self, u):
        self.id = u.id
        self.is_updated_geometry = u.is_updated_geometry
        self.is_updated_transform = u.is_updated_transform
        self.is_updated_shading = u.is_updated_shading


class Summary:
    """The entries of one walk over a round's update; ``made_at``: the list position of the handler that walked;
    ``look``: the ``depsgraph_filter.Look`` of these entries, made at its first use."""

    __slots__ = ("updates", "made_at", "look")

    def __init__(self, updates, made_at):
        self.updates = updates
        self.made_at = made_at
        self.look = None


class _Round:
    __slots__ = ("depsgraph", "summary", "plan")

    def __init__(self, depsgraph):
        self.depsgraph = depsgraph      # Blender passes this same object to every handler of the round
        self.summary = None
        self.plan = None


_rounds = []                    # the running rounds, innermost last (a handler can start a nested one)
_plan_cache = [None]            # (handlers, {id(handler): position}, declared-or-not prefix counts)


def key(fn):
    """``"<module under the package>:<function>"`` of a kit handler, None for anything else."""
    f = getattr(fn, "__func__", fn)
    mod = getattr(f, "__module__", "") or ""
    if not mod.startswith(_PACKAGE + "."):
        return None
    return mod[len(_PACKAGE) + 1:] + ":" + (getattr(f, "__name__", "") or "")


def _declared(fn):
    if fn is _round_start or fn is _round_end:
        return True
    k = key(fn)
    return k is not None and (k in READERS or k in REPORTERS)


def _plan(handlers_list):
    """Positions of the handlers of ``depsgraph_update_post`` and, for each position, how many handlers before it
    are not declared; kept while the list holds the same handlers."""
    got = _plan_cache[0]
    if got is not None and len(got[0]) == len(handlers_list) and all(map(operator.is_, got[0], handlers_list)):
        return got
    handlers = tuple(handlers_list)
    index = {}
    undeclared = [0]
    n = 0
    for i, fn in enumerate(handlers):
        index[id(fn)] = None if id(fn) in index else i      # listed twice: no one place to ask from
        if not _declared(fn):
            n += 1
        undeclared.append(n)
    got = _plan_cache[0] = (handlers, index, undeclared)
    return got


def _walk(depsgraph):
    STATS["walks"] += 1
    return tuple(map(Update, depsgraph.updates))


def _signature(entries):
    return [(u.id.as_pointer(), u.is_updated_geometry, u.is_updated_transform, u.is_updated_shading)
            for u in entries]


def shared(depsgraph, me):
    """The round's ``Summary`` as handler ``me`` (the function in ``depsgraph_update_post``) may use it, walked
    again when needed; None outside a round, when switched off or when ``me`` has no one place in the list."""
    if not ENABLED or not _rounds or depsgraph is None:
        return None
    rnd = _rounds[-1]
    if rnd.depsgraph is not depsgraph:
        return None
    lst = bpy.app.handlers.depsgraph_update_post
    plan = rnd.plan
    if plan is None or len(plan[0]) != len(lst):
        plan = rnd.plan = _plan(lst)
    pos = plan[1].get(id(me))
    if pos is None or lst[pos] is not me:
        plan = rnd.plan = _plan(lst)
        pos = plan[1].get(id(me))
        if pos is None:
            return None
    summary = rnd.summary
    if summary is not None and RECOMPUTE:
        made = summary.made_at
        undeclared = plan[2]
        if pos < made or undeclared[max(pos, made + 1)] != undeclared[made]:
            summary = None              # an undeclared handler ran since the walk (or ``me`` itself isn't declared)
    if summary is None:
        summary = rnd.summary = Summary(_walk(depsgraph), pos)
        return summary
    STATS["reuses"] += 1
    if CHECK:
        fresh = _walk(depsgraph)
        if _signature(fresh) != _signature(summary.updates):
            if len(MISMATCHES) < _MAX_MISMATCHES:
                MISMATCHES.append((key(me), _signature(summary.updates), _signature(fresh)))
            print("allset update summary: kept entries differ from a new walk at", key(me))
            summary = rnd.summary = Summary(fresh, pos)
    return summary


def updates(depsgraph, me):
    """What ``depsgraph.updates`` gives handler ``me`` now: the round's shared entries (``Update``) when they are
    still right, else ``depsgraph.updates`` itself."""
    summary = shared(depsgraph, me)
    return depsgraph.updates if summary is None else summary.updates


def wrote():
    """A declared handler is about to write to the file during the round: the handlers after it walk again."""
    if _rounds and RECOMPUTE:
        _rounds[-1].summary = None


@persistent
def _round_start(_scene, depsgraph=None):
    if len(_rounds) > 16:           # rounds whose end never ran (the end handler was taken out of the list)
        _rounds.clear()
    _rounds.append(_Round(depsgraph))


@persistent
def _round_end(_scene, depsgraph=None):
    for i in range(len(_rounds) - 1, -1, -1):
        if _rounds[i].depsgraph is depsgraph:
            del _rounds[i:]
            break
    if _rounds:
        # this was a nested round (a handler evaluated the depsgraph again): the outer round's update was cleared
        _rounds[-1].summary = None


def register():
    lst = bpy.app.handlers.depsgraph_update_post
    if _round_start not in lst:
        lst.insert(0, _round_start)
    if _round_end not in lst:
        lst.append(_round_end)


def unregister():
    lst = bpy.app.handlers.depsgraph_update_post
    while _round_start in lst:
        lst.remove(_round_start)
    while _round_end in lst:
        lst.remove(_round_end)
    _rounds.clear()
    _plan_cache[0] = None
    MISMATCHES.clear()
