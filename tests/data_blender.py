"""Cross-mode data, rollback, localization and full teardown in factory Blender."""
import json
import math
import sys
import traceback
from pathlib import Path
import bpy
import addon_utils
from mathutils import Matrix, Vector

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
report = {'blender': bpy.app.version_string, 'checks': []}


def snapshot():
    types = (bpy.types.Scene, bpy.types.Object, bpy.types.WindowManager, bpy.types.Bone,
             bpy.types.Light, bpy.types.Material, bpy.types.Mesh, bpy.types.Curve, bpy.types.Armature)
    props = {t.__name__: sorted(p.identifier for p in t.bl_rna.properties if p.identifier.startswith(('allset', 'bsm', 'dcc_'))) for t in types}
    handlers = {name: tuple(id(f) for f in getattr(bpy.app.handlers, name)) for name in dir(bpy.app.handlers)
                if isinstance(getattr(bpy.app.handlers, name), list)}
    keys = []
    for kc in bpy.context.window_manager.keyconfigs:
        for km in kc.keymaps:
            keys.append((kc.name, km.name, km.space_type, km.region_type,
                         tuple((i.idname, i.type, i.value, i.active, i.ctrl, i.alt, i.shift) for i in km.keymap_items)))
    return props, handlers, sorted(keys)


def check(name, fn):
    try:
        detail = fn()
        report['checks'].append({'name': name, 'ok': True, 'detail': detail})
        print('PASS', name, flush=True)
    except Exception:
        report['checks'].append({'name': name, 'ok': False, 'error': traceback.format_exc()})
        print('FAIL', name, traceback.format_exc(), flush=True)


baseline = snapshot()
addon_utils.enable('dcc_workflow_kit', default_set=True, persistent=True)
assert addon_utils.check('dcc_workflow_kit')[1]
from dcc_workflow_kit import core, preferences, lifecycle, localization
from dcc_workflow_kit.providers import maya, max as maxp
prefs = preferences.get()


def mode(target):
    core.set_mode('BLENDER', layout=False)
    if target != 'BLENDER':
        prefs.profile = target
    core._pending = None
    core.set_mode(target, layout=False)


def make_data():
    mode('MAX')
    obj = maxp.params.new_object(bpy.context, 'BOX', Matrix.Identity(4), length=2.0, width=3.0, height=4.0)
    obj.name = 'Name'  # Deliberately equals a translatable UI message.
    obj['integration_probe'] = True
    obj.location.x = 1.0
    obj.keyframe_insert('location', frame=1)
    obj.location.x = 3.0
    obj.keyframe_insert('location', frame=12)
    material = bpy.data.materials.new('Shell')
    material.use_nodes = True
    obj.data.materials.append(material)
    for target in ('BLENDER', 'MAYA', 'MAX', 'BLENDER'):
        mode(target)
        obj.bsm_prim.height = 5.0
        assert obj.name == 'Name' and material.name == 'Shell'
        assert max(v.co.z for v in obj.data.vertices) - min(v.co.z for v in obj.data.vertices) > 4.99
        assert obj.animation_data and obj.animation_data.action
    return 'Max parametric geometry, animation and user names survive both providers'


check('cross_mode_parametric_geometry_and_material', make_data)


def ik_data():
    mode('MAYA')
    arm = bpy.data.objects.new('IntegrationRig', bpy.data.armatures.new('IntegrationRig'))
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    b1 = arm.data.edit_bones.new('root')
    b1.head, b1.tail = (0, 0, 0), (0, 0, 2)
    b2 = arm.data.edit_bones.new('elbow')
    b2.head, b2.tail, b2.parent, b2.use_connect = (0, 0, 2), (1, 0, 4), b1, True
    bpy.ops.object.mode_set(mode='OBJECT')
    h = bpy.data.objects.new('IntegrationHandle', None)
    bpy.context.scene.collection.objects.link(h)
    h.location = (1, 0, 4)
    pb = arm.pose.bones['elbow']
    con = pb.constraints.new('IK')
    con.target, con.chain_count = h, 2
    helper = maya.operators.ik_rp.setup(bpy.context, arm, pb, con, h)
    for index, target in enumerate(('BLENDER', 'MAX', 'BLENDER', 'MAYA')):
        mode(target)
        old = helper.matrix_world.translation.copy()
        h['twist'] = (index + 1) * 35.0
        bpy.context.scene.frame_set(index + 2)
        bpy.context.view_layer.update()
        assert (helper.matrix_world.translation - old).length > 1e-4, target
    mode('BLENDER')
    return 'RP IK pole helper responds to twist via actual frame handlers in every interface'


check('maya_ik_evaluates_in_blender_and_max', ik_data)


def rollback():
    mode('BLENDER')
    prefs.profile = 'MAYA'
    core._pending = None
    before = snapshot()
    original = maya.marking.register
    def fail():
        raise RuntimeError('INJECTED_MODE_FAILURE')
    maya.marking.register = fail
    try:
        try:
            core.set_mode('MAYA', layout=False)
        except RuntimeError as ex:
            assert 'INJECTED_MODE_FAILURE' in str(ex)
        else:
            raise AssertionError('Injected failure was ignored')
        assert core.current() == 'BLENDER'
        assert not maya.switch.is_on()
        assert not maya.keymap.is_applied()
        assert 'INJECTED_MODE_FAILURE' in prefs.last_error
    finally:
        maya.marking.register = original
    assert snapshot() == before, 'Mode initialization leaked state after rollback'
    mode('MAYA')
    mode('BLENDER')
    return 'Partial UI initialization rolls back; subsequent Maya switch succeeds'


check('partial_initialization_rollback', rollback)


def language():
    from dcc_workflow_kit.providers.max.i18n import msg, display, format_message
    bpy.context.preferences.view.language = 'zh_HANS'
    bpy.context.preferences.view.use_translate_interface = True
    marked = msg('Command Panel')
    assert str(marked) == 'Command Panel'
    assert display(marked) == '\u547d\u4ee4\u9762\u677f'
    assert display('Command Panel') == 'Command Panel'
    assert display('Name') == 'Name'
    assert display(msg('Shell')) == '\u58f3'
    assert maya.i18n.tr('UV Shell') == 'UV \u58f3'
    formatted = format_message('{0} Nodes, {1} Wires', 2, 3)
    assert display(formatted) == '2 \u4e2a\u8282\u70b9\uff0c3 \u6761\u8fde\u7ebf'
    bpy.context.preferences.view.language = 'en_US'
    assert display(marked) == 'Command Panel'
    assert display(formatted) == '2 Nodes, 3 Wires'
    return 'Live translation affects source messages only; runtime names stay unchanged'


check('translation_context_and_user_data', language)


def save_open():
    mode('BLENDER')
    path = PROJECT / 'test-results' / f'cross-mode-{bpy.app.version[0]}-{bpy.app.version[1]}.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    bpy.ops.wm.open_mainfile(filepath=str(path))
    obj = bpy.data.objects['Name']
    assert obj.bsm_prim.kind == 'BOX'
    assert abs(obj.bsm_prim.height - 5.0) < 1e-6
    assert obj.animation_data.action
    assert bpy.data.objects['IntegrationHandle'].get(maya.operators.ik_rp.HELPER)
    before = obj.dimensions.z
    obj.bsm_prim.height = 6.0
    bpy.context.view_layer.update()
    assert obj.dimensions.z > before
    return 'Saved .blend reopens with both backends data and functioning Max parameters'


check('save_reopen_data', save_open)


def teardown():
    core._pending = None
    addon_utils.disable('dcc_workflow_kit', default_set=True)
    after = snapshot()
    assert baseline == after, '\n'.join(f'Part {i}: before/after differs' for i in range(3) if baseline[i] != after[i])
    assert not lifecycle.owners()
    return 'Exact keymap/handler/property baseline restored after extension disable'


check('full_teardown_baseline', teardown)
out = PROJECT / 'test-results' / f'data-{bpy.app.version_string.replace(" ", "-")}.json'
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
if any(not t['ok'] for t in report['checks']):
    raise SystemExit(1)
