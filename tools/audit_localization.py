"""Inventory human-facing English and flag missing catalog entries, without changing source."""
import ast
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/dcc_workflow_kit'
OUT = ROOT / 'localization-review'
OUT.mkdir(exist_ok=True)
REVIEWED_KEEPS = set(json.loads((OUT / 'reviewed_keeps.json').read_text(encoding='utf-8'))) if (OUT / 'reviewed_keeps.json').is_file() else set()
BRANDS = {'Blender', 'Blender Max', 'Blender Studio Max', '3ds Max', 'Maya', 'Maya Workflow Kit', 'DCC Workflow Kit',
          'Python', 'MEL', 'Arnold', 'ActiveShade', 'Slate', 'MassFX', 'MAXScript', 'OpenColorIO', 'OpenSubdiv',
          'Blinn', 'Phong', 'Phong E', 'Lambert', 'Rigify', 'HumanIK', 'Bifrost', 'MASH', 'XGen', 'Bullet',
          'nCloth', 'nHair', 'nParticles', 'nRigid', 'nConstraint', 'nCache', 'Nucleus', 'nucleus', 'AgX',
          'ACEScg', 'Filmic', 'Standard', 'TextPlus', 'SpeedTree', 'Alembic', 'OpenVDB', 'USD', 'FBX', 'OBJ',
          'NURBS', 'UV', 'IK', 'FK', 'GPU', 'CPU', 'RGB', 'RGBA', 'HSV', 'HSL', 'sRGB', 'V-Ray',
          'ShaderFX', 'ShaderGraph', 'DirectX', 'OpenGL', 'OSL', 'ART', 'mental ray', 'iray', 'PhysX',
          'CAT', 'Biped', 'MCG', 'ProSound', 'SoundTrax', 'ViewCube', 'MikkTSpace', 'Catmull-Clark'}
# Standard is a translated UI mode, not a product name.
BRANDS.discard('Standard')


def keep_reason(text):
    s = text.strip()
    if text in REVIEWED_KEEPS:
        return 'reviewed_identifier_or_data'
    if re.match(r'^[A-Za-z]:[/\\]', s):
        return 'file_path'
    if re.match(r'^(?:poly[A-Z]|setAttr |reorderDeformers )', s):
        return 'command_echo'
    literal = s
    while re.search(r'\{[^{}]*\}', literal):
        literal = re.sub(r'\{[^{}]*\}', '', literal)
    for brand in ('Maya', 'Blender', '3ds Max'):
        literal = literal.replace(brand, '')
    if not re.search('[A-Za-z]', literal):
        return 'data_only_template'
    if not re.search('[A-Za-z]', s):
        return 'symbol_or_number'
    if s in BRANDS:
        return 'product_or_technical_name'
    if re.fullmatch(r'(?:[!@]?[A-Z][A-Z0-9_]*|[XYZUVWxyzuvw]|[0-9.]+[x%]?|x[0-9.]+)', s):
        return 'identifier_or_unit'
    if re.fullmatch(r'(?:(?:Ctrl|Control|Alt|Shift|Cmd|Meta)\+)+(?:[A-Za-z0-9_`]+|\[|\]|\.|,)(?:, .*)?', s) or re.fullmatch(r'F[0-9]+', s):
        return 'shortcut'
    if s.startswith(('http://', 'https://', 'bsm.', 'allset.', 'bpy.', 'cmds.', 'builtin.', 'wm.', 'mesh.', 'object.', 'view3d.', 'scene.', 'bl_ext.', 'DCCWorkflowKit', 'MWK:', 'ShaderNode', 'GeometryNode', 'CompositorNode')):
        return 'code_or_url'
    if re.fullmatch(r'(?:BSM|ALLSET|DCC|VIEW3D|TOPBAR|NODE|IMAGE|PROPERTIES|GRAPH|DOPESHEET|OUTLINER|UV|OBJECT|MESH|WM|SCENE)_[A-Za-z0-9_]+', s):
        return 'code_identifier'
    if re.fullmatch(r'[0-9]+-[A-Za-z0-9_]+`.*', s):
        return 'max_action_id'
    if re.fullmatch(r'(?:[a-z]+[._])+[a-z0-9_.]+', s) or re.fullmatch(r'[a-z_][a-z0-9_]*', s):
        return 'code_identifier'
    if re.fullmatch(r'(?:Ctrl|Alt|Shift|Mouse|Button)[A-Z][A-Za-z0-9_]*', s):
        return 'event_identifier'
    if re.search(r'\.(?:png|jpe?g|svg|ttf|otf|py|json|toml|blend|wav|dll|exe)$', s, re.I):
        return 'file_name'
    return None


def source_text(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {'_msg', '_dcc_source', '_dcc_display', '_dcc_format', '_zh', '_zh_native', 'tr', 'native', 'format_message'} and node.args:
        return source_text(node.args[0])
    if isinstance(node, ast.JoinedStr):
        result = ''
        for item in node.values:
            if isinstance(item, ast.Constant):
                result += item.value
            else:
                result += '{' + ast.unparse(item.value)
                if item.conversion != -1:
                    result += '!' + chr(item.conversion)
                if item.format_spec:
                    result += ':' + ''.join(p.value if isinstance(p, ast.Constant) else '{' + ast.unparse(p.value) + '}' for p in item.format_spec.values)
                result += '}'
        return result
    return None


def main():
    report = {}
    for domain in ('max', 'maya'):
        root = SOURCE / 'providers' / domain
        path = SOURCE / 'locales/max_zh_HANS.json' if domain == 'max' else root / 'translations_zh_HANS.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        messages = data if domain == 'max' else data['messages']
        contexts = {} if domain == 'max' else data.get('contexts', {})
        entries = defaultdict(list)
        unwrapped = []
        broad = defaultdict(list)
        for file in sorted(root.rglob('*.py')):
            if file.name in {'i18n.py', 'compat.py'}:
                continue
            tree = ast.parse(file.read_text(encoding='utf-8'))
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            docs = {id(node.body[0].value) for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
            def add(node, kind):
                value = source_text(node)
                if value and re.search('[A-Za-z]', value):
                    ref = {'file': file.relative_to(SOURCE).as_posix(), 'line': node.lineno, 'kind': kind}
                    if ref not in entries[value]:
                        entries[value].append(ref)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
                    if fn in {'_msg', '_dcc_source', '_dcc_format', '_zh', '_zh_native'} and node.args:
                        add(node.args[0], 'message_boundary')
                    for kw in node.keywords:
                        if kw.arg in {'text', 'title', 'heading', 'confirm_text', 'apply_text', 'placeholder'}:
                            add(kw.value, 'display_keyword')
                            if isinstance(kw.value, (ast.Constant, ast.JoinedStr)) and source_text(kw.value) and not keep_reason(source_text(kw.value)):
                                unwrapped.append({'file': file.relative_to(SOURCE).as_posix(), 'line': kw.value.lineno, 'text': source_text(kw.value), 'function': fn})
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs and not isinstance(parents.get(node), ast.JoinedStr):
                    s = node.value
                    if len(s) < 250 and s[:1].isupper() and re.search('[a-z]', s) and not keep_reason(s):
                        broad[s].append({'file': file.relative_to(SOURCE).as_posix(), 'line': node.lineno})
        missing = []
        kept = []
        for text, occurrences in sorted(entries.items()):
            reason = keep_reason(text)
            translated = messages.get(text)
            if reason:
                kept.append({'english': text, 'reason': reason})
            elif translated is None or translated == text:
                missing.append({'english': text, 'occurrences': occurrences})
        broad_missing = [{'english': text, 'occurrences': occurrences} for text, occurrences in sorted(broad.items()) if text not in messages]
        result = {'catalog_entries': len(messages), 'observed_messages': len(entries), 'missing': missing,
                  'kept': kept, 'unwrapped_display_sites': unwrapped, 'additional_candidates': broad_missing}
        report[domain] = result
        (OUT / f'{domain}_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(domain, json.dumps({'catalog': len(messages), 'observed': len(entries), 'missing': len(missing),
                                 'kept': len(kept), 'unwrapped_sites': len(unwrapped), 'additional_candidates': len(broad_missing),
                                 'missing_chars': sum(len(r['english']) for r in missing)}))
    return report


if __name__ == '__main__':
    main()
