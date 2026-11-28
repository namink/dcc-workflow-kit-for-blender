# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Skin > Export Weight Maps... / Import Weights Maps...: a ``<name>.weightMap`` text file plus one grey image
per weighted influence drawn in UV space (``export_weight_maps``); import clears the listed skins' weights, samples
each image at the vertex UVs and normalises (``import_weight_maps``). Operators ``allset.export_weight_maps`` /
``allset.import_weight_maps``.
"""

import os

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from .. import results
from .skin_weight_access import _Weights, _skin_armature, influence_names, skinned_meshes

# --- Weight maps ---------------------------------------------------------------------------------------------------
# Maya Export Skin Weight Maps file types; Blender writes these (IFF / SGI / Alias / SoftImage ... aren't Blender formats).
MAP_FORMATS = (("PNG", "PNG", "png"), ("TIFF", "TIFF", "tiff"), ("JPEG", "JPEG", "jpg"), ("TARGA", "Targa", "tga"),
               ("BMP", "Windows Bitmap", "bmp"))
MAP_EXT = {k: e for k, _l, e in MAP_FORMATS}
MAP_HEADER = "// Exported skin weight map file\n// \n"


def map_file_name(taken, base, skin_name, inf, count):
    """Maya's map file names: ``<skin>_<influence>`` (short names), ``_<count>`` when taken,
    ``<base>_<count>`` when longer than 100 characters."""
    def short(name):
        pipe = name.split("|")[-1]
        colon = name.split(":")[-1]
        return colon if ":" in name and len(colon) < len(pipe) else pipe
    out = f"{short(skin_name)}_{short(inf)}"
    if out in taken:
        out += f"_{count}"
    if len(out) > 100:
        out = f"{base}_{count}"
    return out


def map_paths(filepath):
    """(<dir>/<name>.weightMap, <dir>/<name>): Maya's export paths (name = text before the first '.')."""
    folder, fn = os.path.split(filepath)
    base = fn.split(".")[0] or "skinMap"
    return os.path.join(folder, base + ".weightMap"), os.path.join(folder, base), base


def _uv_raster(mesh, width, height):
    """(face triangle index per pixel (-1 = none), barycentrics (H, W, 3), triangle vertex indices (T, 3)) of the
    mesh's active UV map; pixel (i, j) centre = ((i + .5) / W, (j + .5) / H), row 0 at v = 0 (Blender's order)."""
    import numpy as np
    me = mesh.data
    uv = me.uv_layers.active
    me.calc_loop_triangles()
    tris = me.loop_triangles
    nt = len(tris)
    loops = np.empty(nt * 3, dtype=np.int64)
    tris.foreach_get("loops", loops)
    verts = np.empty(nt * 3, dtype=np.int64)
    tris.foreach_get("vertices", verts)
    uvs = np.empty(len(me.loops) * 2)
    uv.data.foreach_get("uv", uvs)
    tuv = uvs.reshape(-1, 2)[loops].reshape(nt, 3, 2) * (width, height) - 0.5    # in pixel-centre coordinates
    tri_of = np.full((height, width), -1, dtype=np.int64)
    bary = np.zeros((height, width, 3))
    for t in range(nt):
        a, b, c = tuv[t]
        lo = np.floor(np.minimum(np.minimum(a, b), c)).astype(int)
        hi = np.ceil(np.maximum(np.maximum(a, b), c)).astype(int)
        x0, y0 = max(lo[0], 0), max(lo[1], 0)
        x1, y1 = min(hi[0], width - 1), min(hi[1], height - 1)
        if x1 < x0 or y1 < y0:
            continue
        det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(det) < 1e-12:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        l1 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / det
        l2 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / det
        l3 = 1.0 - l1 - l2
        inside = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
        yy, xx = ys[inside], xs[inside]
        tri_of[yy, xx] = t
        bary[yy, xx] = np.stack([l1[inside], l2[inside], l3[inside]], axis=1)
    return tri_of, bary, verts.reshape(nt, 3)


def _vertex_weights(mesh, name):
    import numpy as np
    vg = mesh.vertex_groups[name]
    w = np.zeros(len(mesh.data.vertices))
    for v in mesh.data.vertices:
        for g in v.groups:
            if g.group == vg.index:
                w[v.index] = g.weight
    return w


def export_weight_maps(meshes, filepath, width=512, height=512, file_format="PNG"):
    """Write the .weightMap file and one image per weighted influence; returns (map file, image paths)."""
    import numpy as np
    map_file, folder, base = map_paths(filepath)
    ext = MAP_EXT[file_format]
    rows, taken = [], []
    for mesh in meshes:
        if mesh.data.uv_layers.active is None:
            raise ValueError(f"{mesh.name} has no UVs: weight maps are drawn in UV space")
        for inf in influence_names(mesh):
            if not _vertex_weights(mesh, inf).any():          # weighted influences only
                continue
            name = map_file_name(taken, base, mesh.name, inf, len(taken))
            taken.append(name)
            rows.append((mesh, inf, f"{name}.{ext}"))
    with open(map_file, "w", encoding="utf-8") as f:
        f.write(MAP_HEADER)
        for mesh, inf, img in rows:
            f.write(f"{mesh.name}\t{inf}\t{img}\n")
    os.makedirs(folder, exist_ok=True)
    paths = []
    raster = {}
    for mesh, inf, img in rows:
        if mesh.name not in raster:
            raster[mesh.name] = _uv_raster(mesh, width, height)
        tri_of, bary, tv = raster[mesh.name]
        w = _vertex_weights(mesh, inf)
        val = np.where(tri_of >= 0, (bary * w[tv[np.maximum(tri_of, 0)]]).sum(axis=2), 0.0)
        val = np.clip(val, 0.0, 1.0)
        px = np.empty((height, width, 4), dtype=np.float32)
        px[..., 0] = px[..., 1] = px[..., 2] = val
        px[..., 3] = 1.0
        image = bpy.data.images.new(".allset_weight_map", width, height, alpha=False)
        try:
            image.pixels.foreach_set(px.ravel())
            path = os.path.join(folder, img)
            image.filepath_raw = path
            image.file_format = file_format
            image.save()
            paths.append(path)
        finally:
            bpy.data.images.remove(image)
    return map_file, paths


def _sample(px, uv):
    """Bilinear sample (pixel centres, clamped edges) of grey ``px`` (H, W) at ``uv`` (N, 2)."""
    import numpy as np
    h, w = px.shape
    x = np.clip(uv[:, 0] * w - 0.5, 0, w - 1)
    y = np.clip(uv[:, 1] * h - 0.5, 0, h - 1)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    fx, fy = x - x0, y - y0
    return (px[y0, x0] * (1 - fx) * (1 - fy) + px[y0, x1] * fx * (1 - fy) + px[y1, x0] * (1 - fx) * fy
            + px[y1, x1] * fx * fy)


def _vertex_uvs(mesh):
    """Each vertex's UV (its first face corner, Maya's artisan samples one UV per vertex)."""
    import numpy as np
    me = mesh.data
    uvs = np.empty(len(me.loops) * 2)
    me.uv_layers.active.data.foreach_get("uv", uvs)
    lv = np.empty(len(me.loops), dtype=np.int64)
    me.loops.foreach_get("vertex_index", lv)
    out = np.zeros((len(me.vertices), 2))
    seen = np.zeros(len(me.vertices), dtype=bool)
    for li in range(len(lv) - 1, -1, -1):          # reversed: the first corner wins
        out[lv[li]] = uvs[2 * li:2 * li + 2]
        seen[lv[li]] = True
    return out, seen


def import_weight_maps(filepath):
    """Read a .weightMap file (+ its image folder) into the skins it names; returns the (skin, influence) pairs set."""
    import numpy as np
    map_file, folder, _base = map_paths(filepath)
    if not os.path.isfile(map_file):
        map_file = filepath
    lines = []
    with open(map_file, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) == 3:                     # Maya's map file rows (comment lines have other counts)
                lines.append(parts)
    skins = []
    for skin_name, _inf, _img in lines:
        ob = bpy.data.objects.get(skin_name)
        if ob is not None and ob.type == 'MESH' and _skin_armature(ob) is not None and ob not in skins:
            skins.append(ob)
    for ob in skins:                                # Maya pruneWeights 1.1: every weight goes
        io = _Weights(ob)
        groups = {vg.name: vg.index for vg in ob.vertex_groups}
        for n in influence_names(ob):
            gi = groups[n]
            for v in io.bm.verts:
                if gi in v[io.layer]:
                    v[io.layer][gi] = 0.0
        io.flush()
    done = []
    for skin_name, inf, img in lines:
        ob = bpy.data.objects.get(skin_name)
        path = os.path.join(folder, img)
        if ob not in skins or not os.path.isfile(path) or inf not in influence_names(ob):
            continue
        if ob.data.uv_layers.active is None:
            continue
        image = bpy.data.images.load(path, check_existing=False)
        try:
            w, h = image.size
            raw = np.empty(w * h * 4, dtype=np.float32)
            image.pixels.foreach_get(raw)
        finally:
            bpy.data.images.remove(image)
        px = raw.reshape(h, w, 4)
        grey = px[..., 0] * 0.299 + px[..., 1] * 0.587 + px[..., 2] * 0.114
        uv, seen = _vertex_uvs(ob)
        vals = np.where(seen, _sample(grey, uv), 0.0)
        vg = ob.vertex_groups[inf]
        for vi, value in enumerate(vals):
            vg.add([vi], float(value), 'REPLACE')
        done.append((ob.name, inf))
    for ob in skins:                                # normalizeWeights back + skinPercent -normalize true
        names = influence_names(ob)
        idx = {ob.vertex_groups[n].index for n in names}
        for v in ob.data.vertices:
            gs = [g for g in v.groups if g.group in idx]
            total = sum(g.weight for g in gs)
            if total > 0.0:
                for g in gs:
                    g.weight = g.weight / total
        ob.data.update()
    return done


class ALLSET_OT_export_weight_maps(bpy.types.Operator):
    """Maya Skin > Export Weight Maps...: one grey image per joint in UV space and a .weightMap file listing them"""
    bl_idname = "allset.export_weight_maps"
    bl_label = "Export Weight Maps"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH', default="", options={'SKIP_SAVE'})
    filter_glob: StringProperty(default="*.weightMap", options={'HIDDEN'})
    size_x: IntProperty(name="Map size X", default=512, min=1, max=8192)
    size_y: IntProperty(name="Map size Y", default=512, min=1, max=8192)
    file_format: EnumProperty(name="Image format", items=[(k, l, f".{e}") for k, l, e in MAP_FORMATS], default="PNG")

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = "skinMap.weightMap"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        meshes = skinned_meshes(context)
        if not meshes:
            self.report({'ERROR'}, "Select skinned objects to export their weight maps")      # Maya's error text
            return {'CANCELLED'}
        if not self.filepath:
            self.report({'ERROR'}, "No file name")
            return {'CANCELLED'}
        try:
            map_file, paths = export_weight_maps(meshes, bpy.path.abspath(self.filepath), self.size_x, self.size_y,
                                                 self.file_format)
        except (ValueError, OSError) as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        results.result(self, f"Exported {len(paths)} weight maps: {map_file}")
        return {'FINISHED'}


class ALLSET_OT_import_weight_maps(bpy.types.Operator):
    """Maya Skin > Import Weights Maps...: set the skins' weights from a .weightMap file and its images"""
    bl_idname = "allset.import_weight_maps"
    bl_label = "Import Weight Maps"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH', default="", options={'SKIP_SAVE'})
    filter_glob: StringProperty(default="*.weightMap", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.filepath or not os.path.isfile(bpy.path.abspath(self.filepath)):
            self.report({'ERROR'}, f"Unable to open file {self.filepath}")         # Maya's error text
            return {'CANCELLED'}
        if context.active_object is not None and context.active_object.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            done = import_weight_maps(bpy.path.abspath(self.filepath))
        except (ValueError, OSError) as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        if not done:
            self.report({'WARNING'}, "No skinned object or influence of the file was found")
            return {'CANCELLED'}
        results.result(self, f"Imported {len(done)} weight maps")
        return {'FINISHED'}
