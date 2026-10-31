"""One-time import of the two local, unmodified upstream baselines."""
import ast
import hashlib
import json
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
PKG = PROJECT / 'src' / 'dcc_workflow_kit'


def change(path, old, new):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise ValueError(f'Missing replacement in {path}: {old[:100]}')
    path.write_text(text.replace(old, new), encoding='utf-8')


def replace_function(path, name, replacement):
    text = path.read_text(encoding='utf-8')
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    lines = text.splitlines(keepends=True)
    lines[node.lineno - 1:node.end_lineno] = [replacement.rstrip() + '\n']
    path.write_text(''.join(lines), encoding='utf-8')


def main():
    providers = PKG / 'providers'
    providers.mkdir(parents=True, exist_ok=True)
    (providers / '__init__.py').write_text('# SPDX-License-Identifier: GPL-3.0-or-later\n', encoding='utf-8')
    records = {}
    for name, source in [('max', WORKSPACE / 'blender-max'),
                         ('maya', WORKSPACE / 'maya-workflow-kit-for-blender-zh/src/allset')]:
        destination = providers / name
        if destination.exists():
            raise SystemExit(f'Refusing to overwrite imported provider: {destination}')
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns(
            '__pycache__', '.git', '.upstream', '*.pyc', 'user_data', 'blender_manifest.toml'))
        records[name] = {str(p.relative_to(source)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in source.rglob('*') if p.is_file() and p.suffix == '.py'}
    (PROJECT / 'UPSTREAM_HASHES.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
    shutil.copy2(WORKSPACE / 'blender-max/LICENSE', PROJECT / 'LICENSE')
    shutil.copy2(WORKSPACE / 'maya-workflow-kit-for-blender-zh/LOCALIZATION.md', PROJECT / 'MAYA_LOCALIZATION.md')
    shutil.copy2(WORKSPACE / 'maya-workflow-kit-for-blender-zh/UPSTREAM.json', PROJECT / 'MAYA_UPSTREAM.json')

    maxroot, maya = providers / 'max', providers / 'maya'
    change(maxroot / 'preferences.py', 'BSM_Preferences(bpy.types.AddonPreferences)', 'BSM_Preferences(bpy.types.PropertyGroup)')
    change(maxroot / 'preferences.py', '    bl_idname = __package__\n', '')
    replace_function(maxroot / 'runtime.py', 'preferences', '''def preferences():
    from ...preferences import get
    try:
        return get().max_settings
    except (KeyError, AttributeError):
        return None''')
    # Ordinary mode changes must never initialize, delete, or retime scene data.
    replace_function(maxroot / 'runtime.py', 'apply_scene_defaults', '''def apply_scene_defaults(context):
    """Workflow changes preserve scene data; scene defaults belong to explicit New commands."""
    return None''')
    replace_function(maxroot / 'runtime.py', 'request', '''def request(on):
    from ...core import request
    request('MAX' if on else 'BLENDER')''')
    # Internal raw API is reserved for the coordinator; legacy public calls use it too.
    change(maxroot / 'runtime.py', 'def set_active(on, layout=True):', 'def _set_active(on, layout=True):')
    with (maxroot / 'runtime.py').open('a', encoding='utf-8') as f:
        f.write('''\n\ndef set_active(on, layout=True):
    from ...core import set_mode
    return set_mode('MAX' if on else 'BLENDER', layout=layout)
''')
    # Startup reconciliation must not toggle a backend outside the coordinator.
    replace_function(maxroot / 'runtime.py', 'reconcile_startup', 'def reconcile_startup():\n    return None')
    change(maxroot / 'runtime.py', '        set_active(False)\n', '        _set_active(False)\n')
    replace_function(maxroot / 'chrome.py', 'draw_topbar', '''def draw_topbar(self, context):
    if context.region.alignment == 'RIGHT':
        from ...ui import draw_controls
        draw_controls(self.layout, context)
    else:
        from .ui import draw_menus
        draw_menus(self, context)''')
    # Avoid layout edits through undocumented Blender memory offsets.
    replace_function(maxroot / 'chrome.py', '_active_region_slot', 'def _active_region_slot(screen):\n    return None')

    change(maya / 'preferences.py', 'ALLSET_AddonPreferences(bpy.types.AddonPreferences)', 'ALLSET_AddonPreferences(bpy.types.PropertyGroup)')
    change(maya / 'preferences.py', '    bl_idname = __package__\n', '')
    replace_function(maya / 'preferences.py', 'get', '''def get(context=None):
    from ...preferences import get as root_preferences
    return root_preferences(context).maya_settings''')
    replace_function(maya / 'switch.py', 'request', '''def request(on, layout=True):
    from ...core import request
    request('MAYA' if on else 'BLENDER', layout=layout)''')
    change(maya / 'switch.py', 'def set_mode(on, layout=True):', 'def _set_mode(on, layout=True):')
    with (maya / 'switch.py').open('a', encoding='utf-8') as f:
        f.write('''\n\ndef set_mode(on, layout=True):
    from ...core import set_mode
    return set_mode('MAYA' if on else 'BLENDER', layout=layout)
''')
    change(maya / 'switch.py', '    bpy.types.TOPBAR_HT_upper_bar.append(draw_topbar_switch)\n', '')
    change(maya / 'switch.py', '    _add_shortcut()\n', '')
    change(maya / 'switch.py', '    bpy.types.TOPBAR_HT_upper_bar.remove(draw_topbar_switch)\n', '')
    # The coordinator owns the persistent Maya layout. Switching preserves its customization.
    change(maya / 'switch.py', '        _delete_workspace(window, name, added)\n', '        pass  # retained for switching back, never delete user layout\n')
    change(maya / 'switch.py', 'for window in _windows()[:1]:', 'for window in _windows():')
    change(maya / 'ui/shelf.py', '    return __package__.rsplit(".", 1)[0]', '    from ....identity import package_id\n    return package_id() #')
    change(maya / 'ui/shelf.py', 'path="icons"', 'path="maya/icons"') if 'path="icons"' in (maya / 'ui/shelf.py').read_text(encoding='utf-8') else None
    change(maya / 'ui/shelf.py', 'return os.path.join(base, "shelves.json")', 'return os.path.join(base, "maya_shelves.json")')
    change(maya / 'ui/kit_icons.py', 'bpy.utils.extension_path_user(__package__.rpartition(".")[0], path="icons", create=True)', 'bpy.utils.extension_path_user(__package__.split(".providers.")[0], path="maya/icons", create=True)')
    change(maya / 'ui/menu_map.py', '    pkg = __package__.rpartition(".")[0]', '    pkg = __package__.split(".providers.")[0]')
    change(maya / 'ui/menu_map.py', '].preferences.{prop}', '].preferences.maya_settings.{prop}')
    change(maya / 'command_line/runner.py', 'top = _PKG.rpartition(".")[0]', 'top = _PKG.split(".providers.")[0]')
    change(maya / 'command_line/runner.py', '].preferences.{target[', '].preferences.maya_settings.{target[')
    # No automatic loading of a replacement startup scene during a UI switch/startup.
    replace_function(maya / 'first_start.py', 'register', '''def register():
    for cls in classes:
        bpy.utils.register_class(cls)''')

    # Data schemas and scene solvers stay registered; interactive hooks are mode-owned.
    operators = maya / 'operators/__init__.py'
    original = operators.read_text(encoding='utf-8')
    tree = ast.parse(original)
    register = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'register')
    unregister = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'unregister')
    service_modules = {'default_light', 'joint_edit', 'maya_lights', 'constrain_interp', 'ik_rp',
                       'material', 'dag', 'anim_snapshot', 'skin_tools_199', 'constrain_199',
                       'graph_curves_203', 'pins_205', 'deformers_205a', 'deformers_205b', 'curves_207'}
    def is_data(stmt):
        call = stmt.value
        if not isinstance(call, ast.Call):
            return False
        fn = call.func
        return (isinstance(fn, ast.Name) and fn.id == '_register_classes' or
                isinstance(fn, ast.Attribute) and (fn.attr == 'register_props' or fn.value.id in service_modules))
    data, interaction = [], []
    for stmt in register.body:
        (data if is_data(stmt) else interaction).append(ast.unparse(stmt))
    off = [ast.unparse(n) for n in unregister.body]
    def inverse(call):
        return call.replace('_register_classes()', '_unregister_classes()').replace('.register', '.unregister')
    # Build explicit, reversible registration steps; original cleanup for caches remains at extension shutdown.
    def block(name, calls):
        pairs = ',\n'.join('        (' + x[:-2] + ', ' + inverse(x)[:-2] + ')' for x in calls)
        return f'def {name}():\n    from ....lifecycle import activate\n    activate(__name__ + ".{name}", [\n{pairs}\n    ])'
    replace_function(operators, 'register', block('register', interaction))
    replace_function(operators, 'unregister', 'def unregister():\n    from ....lifecycle import deactivate\n    deactivate(__name__ + ".register")')
    extra_cleanup = [x for x in off if x not in {inverse(c) for c in data + interaction}]
    with operators.open('a', encoding='utf-8') as f:
        f.write('\n\n' + block('register_data', data) + '\n\n')
        f.write('def unregister_data():\n    from ....lifecycle import deactivate\n    deactivate(__name__ + ".register_data")\n')
        for cleanup in extra_cleanup:
            f.write('    ' + cleanup + '\n')

    # Keep imports isolated in the provider; these roots are not standalone extensions.
    (maya / '__init__.py').write_text('''# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Workflow Kit 0.6.2+zh.2, adapted for DCC Workflow Kit."""
from . import i18n, preferences, switch, operators, ui, command_line, marking, first_start, keymap
MODE = (operators, ui, command_line, marking, first_start, keymap)
''', encoding='utf-8')
    replace_function(maya / 'switch.py', 'register_mode', '''def register_mode():
    from ...lifecycle import activate
    activate(__name__ + '.mode', [(mod.register, mod.unregister) for mod in _mode_modules()])''')
    replace_function(maya / 'switch.py', 'unregister_mode', '''def unregister_mode():
    from ...lifecycle import deactivate
    deactivate(__name__ + '.mode')''')
    print('Imported providers; modified only the independent integration project.')


if __name__ == '__main__':
    main()
