"""Three isolated processes: prepare, verify Blender, verify selected Max workflow."""
import importlib
import json
import os
import traceback
from pathlib import Path
import bpy
import addon_utils

MODULE = 'bl_ext.user_default.dcc_workflow_kit'
PHASE = os.environ['DCC_STARTUP_PHASE']
PROJECT = Path(__file__).resolve().parents[1]


def record(ok, **kwargs):
    (PROJECT / 'test-results' / f'startup-{PHASE}.json').write_text(
        json.dumps({'phase': PHASE, 'ok': ok, **kwargs}, ensure_ascii=False, indent=2), encoding='utf-8')


if PHASE == 'prepare':
    addon_utils.enable(MODULE, default_set=True, persistent=True)
    root = importlib.import_module(MODULE)
    prefs = root.preferences.get()
    prefs.profile = 'MAX'
    prefs.startup = 'BLENDER'
    # Simulate saved per-backend flags from a former active session.
    prefs.max_settings.enabled_mode = True
    prefs.maya_settings.maya_mode = True
    bpy.ops.wm.save_userpref()
    record(True)
else:
    def verify():
        try:
            root = importlib.import_module(MODULE)
            assert addon_utils.check(MODULE)[1], 'Extension not restored from isolated saved preferences'
            expected = 'BLENDER' if PHASE == 'blender' else 'MAX'
            assert root.core.current() == expected, (expected, root.core.current(), root.preferences.get().last_error)
            assert not root.core.busy()
            assert {o.name for o in bpy.context.scene.objects} == {'Cube', 'Camera', 'Light'}
            if expected == 'BLENDER':
                assert not root.max_provider.runtime.is_active()
                assert not root.maya.switch.is_on()
                root.preferences.get().startup = 'SELECTED'
                bpy.ops.wm.save_userpref()
            else:
                assert bpy.context.window_manager.windows[0].workspace.get('bsm_primary_workspace')
            record(True, current=root.core.current(), objects=sorted(o.name for o in bpy.context.scene.objects))
        except Exception:
            record(False, error=traceback.format_exc())
        bpy.ops.wm.quit_blender()
        return None
    bpy.app.timers.register(verify, first_interval=5.0)
