import bpy
import addon_utils
from importlib import import_module

name = 'bl_ext.user_default.dcc_workflow_kit'
addon_utils.enable(name, default_set=True)
assert addon_utils.check(name)[1]
kit = import_module(name)
view = bpy.context.preferences.view
view.language = 'zh_HANS'
view.use_translate_interface = True
prefs = kit.preferences.get()
prefs.profile = 'MAYA'
kit.core._pending = None
kit.core.set_mode('MAYA', layout=False)
i18n = kit.maya.i18n
assert i18n.iface('Absolute Transform') == '绝对变换'
assert i18n.iface('Keep Faces Together') == '保持面的连接性'
assert i18n.iface('Assign Material To Viewport Selection') != 'Assign Material To Viewport Selection'
assert i18n.iface('Pick/Marquee', i18n.CTX_SELECT_STYLE)
count = len(bpy.data.materials)
assert bpy.ops.allset.hs_shader(node_type='ShaderNodeBsdfDiffuse') == {'FINISHED'}
assert len(bpy.data.materials) == count + 1
assert any(n.bl_idname == 'ShaderNodeBsdfDiffuse' for mat in bpy.data.materials if mat.node_tree for n in mat.node_tree.nodes)
bpy.data.objects['Cube'].name = 'Graph Network'
assert bpy.context.object.name == 'Graph Network'
assert kit.max_provider.__version__ == '0.8.5'
view.language = 'en_US'
assert i18n.iface('Absolute Transform') == 'Absolute Transform'
kit.core.set_mode('BLENDER', layout=False)
addon_utils.disable(name, default_set=True)
assert not kit.lifecycle.owners()
print('PASS installed upstream Hypershade material creation, Chinese labels, language round trip and unchanged object name', flush=True)
