"""Language, data protection and newly completed native labels in factory Blender."""
import importlib
import json
import sys
import traceback
from pathlib import Path
import bpy
import addon_utils

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools')]
from audit_localization import keep_reason
view = bpy.context.preferences.view
view.language = 'en_US'
view.use_translate_interface = True
addon_utils.enable('dcc_workflow_kit', default_set=True)
import dcc_workflow_kit as kit
kit.preferences.get().profile = 'MAYA'
kit.core._pending = None
kit.core.set_mode('MAYA', layout=False)
maya = kit.maya.i18n
max_l10n = importlib.import_module('dcc_workflow_kit.providers.max.i18n')
results = []


def check(name, fn):
    try:
        value = fn()
        results.append({'name': name, 'ok': True, 'detail': value})
        print('PASS', name, flush=True)
    except Exception:
        results.append({'name': name, 'ok': False, 'error': traceback.format_exc()})
        print('FAIL', name, traceback.format_exc(), flush=True)


def native_dictionary():
    prefix = '    ' + maya.source_message('Animation')
    assert str(prefix) == '    Animation'
    assert maya._translate(prefix) == '    动画'
    assert maya.display_message(prefix) == '    Animation'
    kit.maya.i18n.refresh()
    unresolved = [(context, str(text)) for context, texts in maya._native_texts.items() for text in texts
                  if not keep_reason(text) and maya._translate(text, context) == text]
    assert not unresolved, unresolved[:20]
    return 'Native Chinese dictionaries are complete even when registered in English'


check('native_dictionary_built_in_english', native_dictionary)


def source_data_english():
    from dcc_workflow_kit.providers.maya.ui import input_line
    assert input_line.MODES[0][0] == 'ABS'
    assert str(input_line.MODES[0][1]) == 'Absolute Transform'
    assert str(maya.source_message('Channel Box')) == 'Channel Box'
    from dcc_workflow_kit.providers.maya.operators import startup_cameras
    from dcc_workflow_kit.providers.maya.ui import outliner_sets
    assert startup_cameras.NAMES == ('persp', 'top', 'front', 'side')
    assert all(type(name) is str for name in startup_cameras.NAMES)
    assert all(type(name) is str for name in outliner_sets.CAMERAS)
    return 'RNA metadata, enum IDs and source data retain English values'


check('source_metadata_stays_english', source_data_english)


def chinese_live():
    view.language = 'zh_HANS'
    view.use_translate_interface = True
    assert maya.tr('Absolute Transform') == '绝对变换'
    assert maya.tr('Bend amount') == '弯曲量'
    assert maya.tr('Channel_Box') == '通道盒'
    assert maya.tr('Camera-Based Selection off').startswith('基于摄影机的选择')
    assert 'off' not in maya.tr('Camera-Based Selection off')
    assert maya.display_message(maya.source_message('Loaded')) == '已加载'
    assert maya.tr('TOP', 'DCC.Maya.ViewCube') == '顶'
    assert max_l10n.display(max_l10n.msg('Working Pivot')) == '工作轴心'
    assert max_l10n.display(max_l10n.msg('Spline Chamfer')) == '样条线切角'
    assert maya.display_message('Name') == 'Name'
    assert max_l10n.display('Shell') == 'Shell'
    assert maya.display_message(maya.source_message('Animation') + ' / ' + 'Name') == '动画 / Name'
    from dcc_workflow_kit.providers.maya.ui import cb_entry
    assert cb_entry.format_value(True, 'BOOL', bpy.context.scene) == '开'
    assert cb_entry.parse_entry('关', True, 'BOOL', bpy.context.scene) is False
    from dcc_workflow_kit.providers.maya.ui import shelf
    user_label = shelf.display_shelf_label(shelf.USER_PREFIX + 'Animation', maya.source_message('Animation'))
    assert type(user_label) is str and user_label == 'Animation'
    assert maya.display_message(user_label) == 'Animation'
    assert shelf.display_shelf_label('Animation', 'Animation') == '动画'
    return 'Chinese UI uses domain terms and preserves unmarked runtime names'


check('additional_chinese_labels_and_safe_names', chinese_live)


def native_rna():
    contexts = [c for c, texts in maya._native_texts.items() if 'Absolute Transform' in texts]
    assert contexts
    assert all(bpy.app.translations.pgettext_iface('Absolute Transform', c) == '绝对变换' for c in contexts)
    assert bpy.app.translations.pgettext_iface('Command Panel', 'DCCWorkflowKit.Max') == '命令面板'
    return 'Actual Blender translation registry resolves the new native labels'


check('actual_native_translation_registry', native_rna)


def format_and_language():
    value = max_l10n.format_message('Created {0} key(s) at frame {1}', 3, 12)
    assert max_l10n.display(value) == '已在第 12 帧创建 3 个关键点'
    tagged_error = RuntimeError(max_l10n.msg('Create {0}').format('Name'))
    assert max_l10n.error_text(tagged_error) == '创建Name'
    value2 = maya.source_message('Isolate select set: %d face%s%s') % (2, '', '')
    assert maya.display_message(value2) == '隔离选择集：2 个面'
    view.use_translate_interface = False
    assert max_l10n.display(value) == 'Created 3 key(s) at frame 12'
    assert maya.display_message(value2) == 'Isolate select set: 2 face'
    view.use_translate_interface = True
    view.language = 'en_US'
    assert maya.tr('Bend amount') == 'Bend amount'
    assert max_l10n.display(value) == 'Created 3 key(s) at frame 12'
    return 'Numeric/printf fields survive Chinese, interface-off and English round trips'


check('dynamic_fields_and_language_roundtrip', format_and_language)
kit.core.set_mode('BLENDER', layout=False)
addon_utils.disable('dcc_workflow_kit', default_set=True)
out = ROOT / 'test-results' / f'localization-{bpy.app.version_string.replace(" ", "-")}.json'
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
if any(not r['ok'] for r in results):
    raise SystemExit(1)
