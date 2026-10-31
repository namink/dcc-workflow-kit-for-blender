"""Selected original Maya tests executed against the integrated provider."""
import importlib
import importlib.util
import json
import sys
import traceback
import types
from pathlib import Path
import bpy
import addon_utils

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
addon_utils.enable('dcc_workflow_kit', default_set=True)
import dcc_workflow_kit as root
root.preferences.get().profile = 'MAYA'
root.core._pending = None
root.core.set_mode('MAYA', layout=False)
kit = types.ModuleType('kit')
kit.MODULE = 'dcc_workflow_kit.providers.maya'
kit.fcurves = root.maya.compat.id_fcurve_collection
sys.modules['kit'] = kit
results = []
for filename in ('test_step129_marking_bounds.py', 'test_step166_menu_consistency.py'):
    path = PROJECT / 'tests/upstream/tests' / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, test in vars(module).items():
        if not name.startswith('test_') or not callable(test):
            continue
        try:
            test()
            results.append({'name': filename + ':' + name, 'ok': True})
            print('PASS', name, flush=True)
        except Exception:
            results.append({'name': filename + ':' + name, 'ok': False, 'error': traceback.format_exc()})
            print('FAIL', name, traceback.format_exc(), flush=True)
root.core.set_mode('BLENDER', layout=False)
addon_utils.disable('dcc_workflow_kit', default_set=True)
out = PROJECT / 'test-results' / f'upstream-{bpy.app.version_string.replace(" ", "-")}.json'
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
if any(not r['ok'] for r in results):
    raise SystemExit(1)
