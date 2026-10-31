"""Run with --factory-startup and isolated BLENDER_USER_RESOURCES."""
import json
import sys
import traceback
from pathlib import Path
import bpy
import addon_utils

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
report = {'blender': bpy.app.version_string, 'checks': []}


def check(name, fn):
    try:
        detail = fn()
        report['checks'].append({'name': name, 'ok': True, 'detail': detail})
        print('PASS', name, flush=True)
    except Exception:
        report['checks'].append({'name': name, 'ok': False, 'error': traceback.format_exc()})
        print('FAIL', name, traceback.format_exc(), flush=True)


def enable():
    addon_utils.enable('dcc_workflow_kit', default_set=True, persistent=True)
    assert addon_utils.check('dcc_workflow_kit')[1]


check('enable', enable)
if report['checks'][-1]['ok']:
    from dcc_workflow_kit import core, preferences, lifecycle, localization
    from dcc_workflow_kit.providers import maya, max as maxp
    def signature():
        scene = bpy.context.scene
        return (sorted((o.name, o.type, tuple(o.location)) for o in scene.objects),
                scene.frame_start, scene.frame_end, scene.render.fps, scene.render.fps_base,
                scene.unit_settings.system, scene.unit_settings.scale_length,
                sorted((m.name, m.users) for m in bpy.data.materials))
    initial = signature()
    def modes():
        prefs = preferences.get()
        for _ in range(3):
            for profile in ('MAX', 'MAYA'):
                core.set_mode('BLENDER', layout=False)
                prefs.profile = profile
                # Discard the profile-change timer: synchronous test owns progression.
                core._pending = None
                core.set_mode(profile, layout=False)
                assert core.current() == profile
                assert maxp.runtime.is_active() == (profile == 'MAX')
                assert maya.switch.is_on() == (profile == 'MAYA')
                assert initial == signature(), (profile, initial, signature())
                core.set_mode('BLENDER', layout=False)
                assert initial == signature()
        return '3 cycles per profile; factory objects, timing, units and materials unchanged'
    check('mode_cycles_preserve_scene', modes)
    def services():
        assert maya.operators.ik_rp._on_update in bpy.app.handlers.frame_change_post
        assert maya.operators.constrain_interp._on_update in bpy.app.handlers.depsgraph_update_post
        assert hasattr(bpy.types.Object, 'bsm_prim')
        assert hasattr(bpy.types.Scene, 'bsm_material_slots')
        assert not maya.keymap.is_applied()
        assert not maxp.keymap._owned_items
        return 'scene solvers and data schemas retained in Blender; mode keymaps removed'
    check('services_retained_interaction_removed', services)
    def translation():
        view = bpy.context.preferences.view
        view.language = 'zh_HANS'
        view.use_translate_interface = True
        assert localization.tr('Workflow Pair') == '工作流组合'
        assert maya.i18n.tr('Channel Box') == '\u901a\u9053\u76d2'
        view.use_translate_interface = False
        assert localization.tr('Workflow Pair') == 'Workflow Pair'
        assert maya.i18n.tr('Channel Box') == 'Channel Box'
        view.language = 'en_US'
    check('live_language_switch', translation)
    def disable():
        addon_utils.disable('dcc_workflow_kit', default_set=True)
        assert not addon_utils.check('dcc_workflow_kit')[1]
        assert not hasattr(bpy.types.Object, 'bsm_prim')
        assert not lifecycle.owners(), lifecycle.owners()
        assert maya.operators.ik_rp._on_update not in bpy.app.handlers.frame_change_post
        return 'all recorded registrations removed'
    check('disable_cleanup', disable)
    check('enable_again', enable)
    check('disable_again', disable)

out = PROJECT / 'test-results' / f'smoke-{bpy.app.version_string.replace(" ", "-")}.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
if any(not item['ok'] for item in report['checks']):
    raise SystemExit(1)
