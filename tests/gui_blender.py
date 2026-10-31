"""Disposable GUI process. Never attach this test to a user's working session."""
import json
import os
from importlib import import_module
import sys
import traceback
from pathlib import Path
import bpy
import addon_utils

PROJECT = Path(__file__).resolve().parents[1]
MODULE = os.environ.get('DCC_TEST_MODULE', 'dcc_workflow_kit')
QUICK = os.environ.get('DCC_GUI_QUICK') == '1'
MULTI_STEPS = 0 if QUICK else 8
OUT = PROJECT / 'test-results' / ('gui-' + bpy.app.version_string.replace(' ', '-') + ('-installed' if MODULE.startswith('bl_ext.') else '') + ('-quick' if QUICK else ''))
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(PROJECT / 'src'))
results = []
step = 0
snapshot = None
window = None
preference_window = None
cycles = [('MAX', 'MAX'), ('MAX', 'BLENDER'), ('MAYA', 'MAYA'), ('MAYA', 'BLENDER'),
          ('MAX', 'MAX'), ('MAX', 'BLENDER'), ('MAYA', 'MAYA'), ('MAYA', 'BLENDER')]
if QUICK:
    cycles = cycles[2:4] if os.environ.get('DCC_GUI_PROFILE') == 'MAYA' else cycles[:2]


def signature():
    s = bpy.context.scene
    return (sorted((o.name, o.type, tuple(o.location)) for o in s.objects),
            s.frame_start, s.frame_end, s.render.fps, s.unit_settings.scale_length)


def finish():
    (OUT / 'report.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    bpy.ops.wm.quit_blender()


def tick():
    global step, snapshot, window, preference_window
    try:
        if step == 0:
            window = bpy.context.window_manager.windows[0]
            with bpy.context.temp_override(window=window):
                addon_utils.enable(MODULE, default_set=True, persistent=True)
                assert addon_utils.check(MODULE)[1]
                bpy.context.preferences.view.language = 'zh_HANS'
                bpy.context.preferences.view.use_translate_interface = True
                bpy.context.preferences.view.show_splash = False
                snapshot = signature()
            results.append({'name': 'enable_gui', 'ok': True})
        elif step <= len(cycles) * 2:
            index = (step - 1) // 2
            profile, target = cycles[index]
            module = import_module(MODULE)
            core, preferences = module.core, module.preferences
            with bpy.context.temp_override(window=window):
                if step % 2:
                    preferences.get().profile = profile
                    core.request(target)
                else:
                    assert not core.busy()
                    assert core.current() == target, preferences.get().last_error
                    assert not preferences.get().last_error, preferences.get().last_error
                    assert snapshot == signature(), (snapshot, signature())
                    if target == 'MAX':
                        assert window.workspace.get('bsm_primary_workspace')
                    if target == 'MAYA':
                        maya = import_module(MODULE + ".providers.maya")
                        assert maya.switch.is_maya_workspace(window.workspace)
                    if target == 'BLENDER':
                        assert not core._foreign(window.workspace)
                    bpy.ops.screen.screenshot(filepath=str(OUT / f'{index:02d}-{target}.png'))
                    results.append({'name': f'cycle_{index}_{target}', 'ok': True,
                                    'workspace': window.workspace.name})
                    print('GUI PASS', target, flush=True)
        elif step <= len(cycles) * 2 + MULTI_STEPS:
            module = import_module(MODULE)
            core, preferences = module.core, module.preferences
            phase = step - len(cycles) * 2
            with bpy.context.temp_override(window=window):
                if phase == 1:
                    bpy.ops.wm.window_new()
                if phase % 2:
                    target = {1: 'MAX', 3: 'BLENDER', 5: 'MAYA', 7: 'BLENDER'}[phase]
                    if target != 'BLENDER':
                        preferences.get().profile = target
                    core.request(target)
                else:
                    target = {2: 'MAX', 4: 'BLENDER', 6: 'MAYA', 8: 'BLENDER'}[phase]
                    assert core.current() == target, preferences.get().last_error
                    assert not core.busy()
                    for w in bpy.context.window_manager.windows:
                        if target == 'MAX':
                            assert w.workspace.get('bsm_primary_workspace')
                        elif target == 'MAYA':
                            assert module.maya.switch.is_maya_workspace(w.workspace)
                        else:
                            assert not core._foreign(w.workspace)
                    assert snapshot == signature()
                    results.append({'name': 'multiwindow_' + target + '_' + str(phase), 'ok': True})
                    if phase == 8:
                        extra = next(w for w in bpy.context.window_manager.windows if w != window)
                        with bpy.context.temp_override(window=extra):
                            bpy.ops.wm.window_close()
        elif step == len(cycles) * 2 + MULTI_STEPS + 1:
            with bpy.context.temp_override(window=window):
                bpy.context.preferences.active_section = 'ADDONS'
                bpy.ops.screen.userpref_show()
                preference_window = next(w for w in bpy.context.window_manager.windows if w != window)
                bpy.context.window_manager.addon_search = 'DCC Workflow Kit'
                try:
                    bpy.ops.preferences.addon_expand(module=MODULE)
                except RuntimeError:
                    pass
        elif step == len(cycles) * 2 + MULTI_STEPS + 2:
            with bpy.context.temp_override(window=preference_window):
                bpy.ops.screen.screenshot(filepath=str(OUT / 'preferences.png'))
                bpy.ops.wm.window_close()
            results.append({'name': 'preferences_draw', 'ok': True})
        else:
            lifecycle = import_module(MODULE + ".lifecycle")
            with bpy.context.temp_override(window=window):
                addon_utils.disable(MODULE, default_set=True)
                assert not lifecycle.owners(), lifecycle.owners()
                assert snapshot == signature()
            results.append({'name': 'disable_gui', 'ok': True})
            finish()
            return None
        step += 1
        return 2.0
    except Exception:
        results.append({'name': f'step_{step}', 'ok': False, 'error': traceback.format_exc()})
        print('GUI FAIL', traceback.format_exc(), flush=True)
        finish()
        return None


bpy.app.timers.register(tick, first_interval=2.0)
