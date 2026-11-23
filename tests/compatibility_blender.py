"""Run in factory Blender: exercise the version backports and installed keymap RNA."""
import sys
from pathlib import Path
import bpy
import addon_utils

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
addon_utils.enable('dcc_workflow_kit', default_set=True)
from dcc_workflow_kit import core, preferences
from dcc_workflow_kit.providers.maya import compat
from dcc_workflow_kit.providers.maya.keymap import ic_data
from dcc_workflow_kit.providers.max.compat import operator_binding
from dcc_workflow_kit.providers.maya.ui import maya_dock

version = '%d.%d' % bpy.app.version[:2]
for section in ('manual/en', 'api'):
    assert compat.docs_url(f'https://docs.blender.org/{section}/5.2/test.html') == f'https://docs.blender.org/{section}/{version}/test.html'
assert compat.docs_url('https://example.org/5.2/') == 'https://example.org/5.2/'
if bpy.app.version[:2] == (4, 2):
    assert ic_data.data_version() == (4, 2)
    assert operator_binding('mesh.loop_multi_select', {'ring': True}) == ('mesh.loop_multi_select', {'ring': True})
    area = next(a for a in bpy.context.screen.areas if a.type == 'PROPERTIES')
    for role in maya_dock.ROLE_FLAGS:
        assert maya_dock.set_role(area, role)
        assert maya_dock.role(area) == role
    from dcc_workflow_kit.providers.maya.operators import menu_items, uv_tools, weight_paint
    assert menu_items._activate_brush('Draw') == {'FINISHED'}
    assert weight_paint.brush_tool(bpy.context, 'DRAW') == 'builtin_brush.Draw'
    bpy.ops.object.mode_set(mode='EDIT')
    uv_tools.unfold(bpy.context, bpy.context.active_object)
    bpy.ops.object.mode_set(mode='OBJECT')
preferences.get().profile = 'MAYA'
core._pending = None
core.set_mode('MAYA', layout=False)
count = 0
for km in bpy.context.window_manager.keyconfigs.addon.keymaps:
    for item in km.keymap_items:
        if not item.idname:
            continue
        group, name = item.idname.split('.', 1)
        getattr(getattr(bpy.ops, group), name).get_rna_type()
        count += 1
core.set_mode('BLENDER', layout=False)
addon_utils.disable('dcc_workflow_kit', default_set=True)
print('PASS versioned docs, native preset, loop binding, registered keymap operators:', count)
