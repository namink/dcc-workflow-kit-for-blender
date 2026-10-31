"""Exercise extension identity and file migration using the installed ZIP only."""
import importlib
import json
import sys
import traceback
from pathlib import Path
import bpy
import addon_utils

PROJECT = Path(__file__).resolve().parents[1]
MODULE = 'bl_ext.user_default.dcc_workflow_kit'
REPORT = []


def check(name, fn):
    try:
        detail = fn()
        REPORT.append({'name': name, 'ok': True, 'detail': detail})
        print('PASS', name, flush=True)
    except Exception:
        REPORT.append({'name': name, 'ok': False, 'error': traceback.format_exc()})
        print('FAIL', name, traceback.format_exc(), flush=True)


addon_utils.enable(MODULE, default_set=True, persistent=True)
assert addon_utils.check(MODULE)[1]
root = importlib.import_module(MODULE)


def identity():
    assert root.identity.package_id() == MODULE
    assert 'extensions' in str(Path(root.__file__).resolve())
    assert 'dcc_workflow_kit' not in sys.modules, 'Source-package import contaminated installed test'
    prefs = root.preferences.get()
    assert prefs.max_settings and prefs.maya_settings
    assert root.maya.preferences.get().as_pointer() == prefs.maya_settings.as_pointer()
    return str(Path(root.__file__).resolve())


check('installed_identity_and_settings', identity)


def shelf_import():
    from importlib import import_module
    identity = import_module(MODULE + '.identity')
    source = PROJECT / 'test-results/import-probe.json'
    user = {'shelves': [{'name': '用户工具架 Name', 'buttons': [{'label': 'Shell', 'command': 'print("保留原样")'}]}]}
    source.write_text(json.dumps(user, ensure_ascii=False), encoding='utf-8')
    original_bytes = source.read_bytes()
    dest = Path(identity.user_path()) / 'maya_shelves.json'
    dest.parent.mkdir(exist_ok=True, parents=True)
    dest.write_text('{"shelves": []}', encoding='utf-8')
    assert root.migration.import_shelves(source) == 1
    assert root.migration.import_shelves(source) == 0
    actual = json.loads(dest.read_text(encoding='utf-8'))
    assert actual == user
    assert source.read_bytes() == original_bytes
    assert dest.with_suffix('.json.backup').exists()
    assert root.maya.ui.shelf.store_path() == str(dest)
    source.write_text('{"invalid": true}', encoding='utf-8')
    before = dest.read_bytes()
    try:
        root.migration.import_shelves(source)
    except ValueError:
        pass
    else:
        raise AssertionError('Invalid shelf input accepted')
    assert dest.read_bytes() == before
    return 'Names/scripts preserved; duplicate imports skip; source untouched; backup retained; invalid input rejected'


check('non_destructive_shelf_import', shelf_import)


def dynamic_preferences():
    prefs = root.preferences.get()
    prefs.profile = 'MAYA'
    root.core._pending = None
    root.core.set_mode('MAYA', layout=False)
    operator, props = root.maya.ui.menu_map._kit_pref('show_help_line')
    previous = prefs.maya_settings.show_help_line
    # Blender returns CANCELLED for successful non-undoable preference toggles.
    assert bpy.ops.wm.context_toggle(**props) in ({'FINISHED'}, {'CANCELLED'})
    assert prefs.maya_settings.show_help_line != previous
    assert bpy.ops.wm.context_toggle(**props) in ({'FINISHED'}, {'CANCELLED'})
    assert prefs.maya_settings.show_help_line == previous
    root.core.set_mode('BLENDER', layout=False)
    return props['data_path']


check('nested_settings_menu_data_path', dynamic_preferences)


def cleanup():
    addon_utils.disable(MODULE, default_set=True)
    assert not root.lifecycle.owners()
    assert not root.maya.switch.is_on()
    return 'Installed extension cleanly disables'


check('installed_cleanup', cleanup)
out = PROJECT / 'test-results' / f'installed-{bpy.app.version_string.replace(" ", "-")}.json'
out.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
if any(not r['ok'] for r in REPORT):
    raise SystemExit(1)
