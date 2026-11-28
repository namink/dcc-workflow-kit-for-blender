# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Mesh > Smooth as real Catmull-Clark geometry on the selected faces or meshes (``smooth``, ``smooth_targets``),
kept as an editable ``polySmoothFace`` history node: ``SMOOTH`` is its extrude_spec.Spec (made once, at import),
``allset.smooth`` records it, ``allset.smooth_edit`` changes its Divisions from Channel Box INPUTS. The Smooth option
window runs ``allset.smooth`` (option_windows_basic.py). Imported through poly_maya.py.
"""

import bmesh
import bpy

from .. import undo_steps


# --- Smooth ------------------------------------------------------------------------------------
# Smooth with the menu's default options (divisions 1, continuity 1, keep border / selection border,
# OpenSubdiv "sharp edges and corners"): Catmull-Clark on the chosen faces. A vertex moves
# only when all its faces are smoothed (mesh-border vertices along the border curve, corners stay); edges between two
# smoothed faces get the Catmull-Clark edge point, other edges their midpoint. Unsmoothed neighbours keep the new
# midpoints as extra vertices (Maya's n-gons).

def _smooth_once(bm, faces):
    from mathutils import Vector
    S = set(faces)
    fp = {f: f.calc_center_median() for f in S}
    edges = {e for f in S for e in f.edges}
    ep = {}
    for e in edges:
        a, b = e.verts[0].co, e.verts[1].co
        lf = e.link_faces
        if len(lf) == 2 and lf[0] in S and lf[1] in S:
            ep[e] = (a + b + fp[lf[0]] + fp[lf[1]]) / 4.0
        else:
            ep[e] = (a + b) / 2.0
    vp = {}
    for v in {v for f in S for v in f.verts}:
        lf = v.link_faces
        if not all(f in S for f in lf):
            continue
        if v.is_boundary:
            border = [e for e in v.link_edges if e.is_boundary]
            if len(border) == 2 and len(lf) > 1:
                o = [e.other_vert(v).co for e in border]
                vp[v] = v.co * 0.75 + (o[0] + o[1]) * 0.125
            continue
        n = len(v.link_edges)
        q = sum((fp[f] for f in lf), Vector()) / len(lf)
        r = sum(((e.verts[0].co + e.verts[1].co) / 2.0 for e in v.link_edges), Vector()) / n
        vp[v] = (q + 2.0 * r + (n - 3) * v.co) / n
    uv_layers = list(bm.loops.layers.uv)
    plan = []
    for f in S:
        loops = list(f.loops)
        uvs = [[lp[layer].uv.copy() for layer in uv_layers] for lp in loops]
        plan.append((f, [lp.vert for lp in loops], [lp.edge for lp in loops], uvs))
    mid = {}
    for e in sorted(edges, key=lambda e: e.index):
        _ne, nv = bmesh.utils.edge_split(e, e.verts[0], 0.5)
        mid[e] = nv
    new_faces = []
    for f, corners, f_edges, uvs in plan:
        n = len(corners)
        c = bm.verts.new(fp[f])
        cuv = [sum((u[k] for u in uvs), uvs[0][k] * 0) / n for k in range(len(uv_layers))]
        for i in range(n):
            prev = (i - 1) % n
            quad = (corners[i], mid[f_edges[i]], c, mid[f_edges[prev]])
            nf = bm.faces.new(quad, f)
            nf.select = True
            new_faces.append(nf)
            for k, layer in enumerate(uv_layers):
                ls = list(nf.loops)
                ls[0][layer].uv = uvs[i][k]
                ls[1][layer].uv = (uvs[i][k] + uvs[(i + 1) % n][k]) / 2.0
                ls[2][layer].uv = cuv[k]
                ls[3][layer].uv = (uvs[i][k] + uvs[prev][k]) / 2.0
    bmesh.ops.delete(bm, geom=[p[0] for p in plan], context='FACES_ONLY')
    for v, co in vp.items():
        v.co = co
    for e, v in mid.items():
        v.co = ep[e]
    return new_faces


def smooth(bm, faces, divisions=1):
    """Maya Smooth on ``faces`` (``divisions`` levels). Returns the new faces (selected)."""
    faces = list(faces)
    for _ in range(max(0, divisions)):
        if not faces:
            break
        faces = _smooth_once(bm, faces)
    bm.normal_update()
    return faces


def smooth_targets(bm):
    """The faces Maya smooths for the component selection: selected faces, else the faces of the selected edges,
    else of the selected vertices, else the whole mesh."""
    faces = [f for f in bm.faces if f.select]
    if faces:
        return faces
    edges = [e for e in bm.edges if e.select]
    if edges:
        return list({f for e in edges for f in e.link_faces})
    verts = [v for v in bm.verts if v.select]
    if verts:
        return list({f for v in verts for f in v.link_faces})
    return list(bm.faces)


# polySmoothFace history node (#204): Maya's Mesh > Smooth leaves polySmoothFace1 in Channel Box INPUTS with its
# Divisions editable. Like the kit's extrude / bevel nodes it is the last kit operation on the mesh (operators/extrude_record.py
# records), editable while the mesh is still its result, in component and object mode. The kit's Catmull-Clark has no
# Method / Continuity switch, so Divisions is its only row.

def _build_smooth(bm, params, unit):
    targets = smooth_targets(bm)
    for el in (*bm.verts, *bm.edges, *bm.faces):
        el.select = False
    faces = smooth(bm, targets, int(params["divisions"]))
    bm.select_flush_mode()
    return list({v for f in faces if f.is_valid for v in f.verts})


def _smooth_spec():
    from . import extrude
    return extrude.add_spec(extrude.Spec(
        'SMOOTH', "polySmoothFace", ("divisions",), {"divisions": "Divisions"}, {"divisions": 1},
        {"divisions": "INT"}, None, "smooth_edit", _build_smooth, in_view=False))


SMOOTH = _smooth_spec()


class ALLSET_OT_smooth(bpy.types.Operator):
    """Smooth the selected faces (component mode) or the selected meshes with real Catmull-Clark geometry
    (Maya Mesh > Smooth): change its Divisions in Channel Box INPUTS (polySmoothFace)"""
    bl_idname = "allset.smooth"
    bl_label = "Smooth"
    bl_options = {'REGISTER', 'UNDO'}

    divisions: bpy.props.IntProperty(name="Division levels", default=1, min=0, soft_max=4, max=6)

    @classmethod
    def poll(cls, context):
        if context.mode == 'EDIT_MESH':
            return True
        return context.mode == 'OBJECT' and any(o.type == 'MESH' for o in context.selected_objects)

    def execute(self, context):
        from . import extrude, units
        unit = units.maya_unit(context.scene)
        params = {"divisions": self.divisions}
        if context.mode == 'EDIT_MESH':
            for ob in context.objects_in_mode_unique_data:
                if ob.type != 'MESH':
                    continue
                bm = bmesh.from_edit_mesh(ob.data)
                if extrude.record_new(context, ob, bm, SMOOTH, params, unit) is None:
                    bmesh.update_edit_mesh(ob.data)
            return {'FINISHED'}
        done = set()
        for ob in context.selected_objects:
            if ob.type != 'MESH' or ob.data in done:
                continue
            done.add(ob.data)
            extrude.record_object(context, ob, SMOOTH, params, unit)
        return {'FINISHED'}


@undo_steps.no_redo_panel      # no Adjust Last Operation (Maya has none)
class ALLSET_OT_smooth_edit(bpy.types.Operator):
    """Change the last Smooth (Maya: edit the polySmoothFace node). Blender keeps no history, so only the last one
    can be changed"""
    bl_idname = "allset.smooth_edit"
    bl_label = "polySmoothFace"
    bl_options = {'REGISTER', 'UNDO'}

    divisions: bpy.props.IntProperty(name="Divisions", default=1, min=0, max=6, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}

    def execute(self, context):
        from . import extrude, units
        params = {"divisions": self.divisions}
        if context.mode == 'OBJECT':
            ok = extrude.edit_from_object_mode(context, "smooth_edit", lambda _spec: params)
            return {'FINISHED'} if ok else {'CANCELLED'}
        unit = units.maya_unit(context.scene)
        done = 0
        for ob in context.objects_in_mode_unique_data:
            rec = extrude.RECORDS.get(ob.name)
            if rec is not None and rec.spec is SMOOTH and rec.pre is not None and (
                    rec.live or extrude.current(ob) is not None):
                done += bool(extrude.run(ob, rec, params, unit))
        return {'FINISHED'} if done else {'CANCELLED'}
