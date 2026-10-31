"""Compile exact local translation memories and finite whole-label variants offline."""
import gettext
import json
import re
from pathlib import Path
from audit_localization import keep_reason

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/dcc_workflow_kit'
OUT = ROOT / 'localization-review'
with Path('C:/Program Files/Blender Foundation/Blender 5.2/5.2/datafiles/locale/zh_HANS/LC_MESSAGES/blender.mo').open('rb') as f:
    blender = gettext.GNUTranslations(f)
maya_path = SOURCE / 'providers/maya/translations_zh_HANS.json'
max_path = SOURCE / 'locales/max_zh_HANS.json'
maya = json.loads(maya_path.read_text(encoding='utf-8'))
maxcat = json.loads(max_path.read_text(encoding='utf-8'))
ambiguous = {'Shell', 'Frame', 'Set', 'Key', 'Track', 'Scale', 'Point', 'Parent', 'Orient', 'Normal', 'Wire', 'Action',
             'Chamfer', 'Bevel', 'Extrude', 'Freeze', 'History', 'Command Panel', 'Modifier Stack', 'Attribute Editor',
             'Quad Menu', 'Marking Menu', 'Channel Box', 'Curve Editor', 'Graph Editor', 'Dope Sheet'}


def direct(s, domain):
    local = maxcat if domain == 'max' else maya['messages']
    other = maya['messages'] if domain == 'max' else maxcat
    if s in local and local[s] != s:
        return local[s]
    translated = blender.gettext(s)
    if translated != s and re.search('[\u3400-\u9fff]', translated):
        return translated
    if s not in ambiguous and s in other and other[s] != s:
        return other[s]


def derive(s, domain, depth=0):
    if depth > 3:
        return None
    result = direct(s, domain)
    if result:
        return result
    stripped = s.strip()
    if stripped != s:
        value = derive(stripped, domain, depth + 1)
        if value:
            return s[:len(s) - len(s.lstrip())] + value + s[len(s.rstrip()):]
    for suffix, replacement in [('...', '…'), ('…', '…'), (':', '：')]:
        if s.endswith(suffix):
            value = derive(s[:-len(suffix)], domain, depth + 1)
            if value:
                return value.rstrip('：:…') + replacement
    number = re.fullmatch(r'(.+?)( \d+| [XYZUVW]| [0-9.]+%)', s)
    if number:
        value = derive(number[1], domain, depth + 1)
        if value:
            return value + number[2]
    for prefix, zh in [('Create ', '创建'), ('Add ', '添加'), ('Delete ', '删除'), ('Remove ', '移除'),
                       ('Select ', '选择'), ('Show ', '显示'), ('Hide ', '隐藏'), ('Enable ', '启用'),
                       ('Disable ', '禁用'), ('Import ', '导入'), ('Export ', '导出'), ('Copy ', '复制'),
                       ('Paste ', '粘贴'), ('Reset ', '重置'), ('Lock ', '锁定'), ('Unlock ', '解锁'),
                       ('Bake ', '烘焙'), ('Align ', '对齐'), ('Apply ', '应用'), ('Edit ', '编辑'),
                       ('Clear ', '清除'), ('Load ', '加载'), ('Save ', '保存'), ('Current ', '当前'),
                       ('Selected ', '选定'), ('Default ', '默认'), ('New ', '新'), ('All ', '全部'),
                       ('Custom ', '自定义'), ('Active ', '活动'), ('Automatic ', '自动'), ('Auto ', '自动')]:
        if s.startswith(prefix):
            value = derive(s[len(prefix):], domain, depth + 1)
            if value:
                return zh + value
    for suffix, zh in [(' Options', '选项'), (' Settings', '设置'), (' Tool', '工具'), (' Editor', '编辑器'),
                       (' Mode', '模式'), (' Type', '类型'), (' Parameters', '参数'), (' Attributes', '属性')]:
        if s.endswith(suffix):
            value = derive(s[:-len(suffix)], domain, depth + 1)
            if value:
                return value + zh
    return None


def fill_known_candidates():
    for domain, local, path in [('max', maxcat, max_path), ('maya', maya['messages'], maya_path)]:
        audit = json.loads((OUT / f'{domain}_audit.json').read_text(encoding='utf-8'))
        candidates = {r['english'] for r in audit['missing']}
        # Add ordinary data-table labels and tips, excluding command paths, raw IDs and debug code.
        if domain == 'maya':
            for row in audit['additional_candidates']:
                s = row['english']
                filenames = [r['file'].rsplit('/', 1)[-1] for r in row['occurrences']]
                if all(name in {'ic_4_5.py', 'ic_5_2.py', 'hotkey_data.py', 'hotkey_rows.py', 'shelf_data.py',
                                'shelf_icons.py', 'menu_map.py', 'editor_menu_map.py', 'mapping.py'} for name in filenames):
                    continue
                if re.search(r'\b(?:[A-Z][A-Z0-9_]*_(?:OT|MT|PT|HT|UL|GT|GGT)_\w+)\b', s) or '\\' in s or '\n' in s:
                    continue
                if '/' in s and not re.search(r'\s/\s', s):
                    continue
                if re.fullmatch(r'[A-Z][A-Za-z0-9]*', s) and re.search(r'[a-z][A-Z]', s) and not s.endswith(('Editor', 'Tool', 'Curve', 'Light')):
                    continue
                candidates.add(s)
        for _ in range(3):
            for s in sorted(candidates):
                if s in local or keep_reason(s):
                    continue
                value = derive(s, domain)
                if value:
                    local[s] = value
        remaining = sorted(s for s in candidates if not keep_reason(s) and (s not in local or local[s] == s))
        (OUT / f'{domain}_remaining_snapshot.json').write_text(json.dumps(remaining, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if domain == 'max':
            path.write_text(json.dumps(local, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        else:
            path.write_text(json.dumps(maya, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(domain, 'catalog', len(local), 'remaining', len(remaining), 'characters', sum(map(len, remaining)))


if __name__ == '__main__':
    fill_known_candidates()
