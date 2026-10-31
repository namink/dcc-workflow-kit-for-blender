"""Compile reviewed terminology corrections into exact catalog entries offline."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'localization-review'
SOURCE = ROOT / 'src/dcc_workflow_kit'
max_path = SOURCE / 'locales/max_zh_HANS.json'
maya_path = SOURCE / 'providers/maya/translations_zh_HANS.json'
maxcat = json.loads(max_path.read_text(encoding='utf-8'))
maya = json.loads(maya_path.read_text(encoding='utf-8'))
rejected = json.loads((REVIEW / 'rejected_drafts.json').read_text(encoding='utf-8'))
kept = set(json.loads((REVIEW / 'reviewed_keeps.json').read_text(encoding='utf-8')))
for line in (REVIEW / 'manual_rejected_translations.tsv').read_text(encoding='utf-8').splitlines():
    if not line or line.startswith('#'):
        continue
    number, translated = line.split('\t', 1)
    row = rejected[int(number)]
    if translated == 'KEEP':
        kept.add(row['english'])
    else:
        (maxcat if row['domain'] == 'max' else maya['messages'])[row['english']] = translated

# These are maintenance-time corrections on finite, recorded draft entries.
# No substring substitution runs in Blender, and user names never enter this step.
drafts = json.loads((REVIEW / 'translation_drafts.json').read_text(encoding='utf-8'))
corrected = []
for row in drafts:
    domain, en = row['domain'], row['english']
    table = maxcat if domain == 'max' else maya['messages']
    if en not in table:
        continue
    zh = table[en]
    old = zh
    if domain == 'max':
        for wrong, right in [('花键', '样条线'), ('密钥', '关键点'), ('钥匙', '关键点'),
                             ('全球探索者', '全局资源管理器'), ('全球资源管理器', '全局资源管理器'),
                             ('原理图视图', '示意视图'), ('示意图视图', '示意视图'), ('形状合并', '图形合并')]:
            zh = zh.replace(wrong, right)
        if re.search(r'\bmaps?\b', en, re.I):
            zh = zh.replace('地图', '贴图')
        if re.search(r'\bspline', en, re.I):
            zh = zh.replace('样条纹理', '样条线').replace('样条纹', '样条线')
    else:
        for wrong, right in [('密钥', '关键帧'), ('钥匙', '关键帧'), ('皮肤', '蒙皮'), ('信封', '包络'),
                             ('骨骼封套', '骨骼包络'), ('休息姿势', '静止姿势'), ('混音切线', '混合切线'),
                             ('小玩意儿', 'Gizmo'), ('搅拌机', 'Blender'), ('谐波平均值', '调和平均值')]:
            zh = zh.replace(wrong, right)
        if re.search(r'\bchannels?\b', en, re.I):
            zh = zh.replace('频道', '通道').replace('渠道', '通道')
        if re.search(r'\bmap(?:ping)?\b', en, re.I):
            zh = zh.replace('地图', '映射')
    if zh != old:
        table[en] = zh
        corrected.append({'domain': domain, 'english': en, 'before': old, 'after': zh})

maxcat.update({'Schematic View': '示意视图', 'Schematic View...': '示意视图…', 'Spline': '样条线',
               'Track View - Schematic View': '轨迹视图 - 示意视图', '2D Pan Zoom Mode': '二维平移缩放模式',
               '3 x 2 Sample Windows': '3 × 2 示例窗', '5 x 3 Sample Windows': '5 × 3 示例窗',
               '6 x 4 Sample Windows': '6 × 4 示例窗', 'Alpha': 'Alpha 通道'})
maya['messages'].update({'Enabled': '已启用', 'Disabled': '已禁用', 'Enable': '启用', 'Disable': '禁用',
                         'Lock': '锁定', 'Unlock': '解锁', 'Loaded': '已加载', 'Unloaded': '已卸载',
                         'Locked': '已锁定', 'Unlocked': '已解锁', 'Auto Custom tangents': '自动自定义切线',
                         'Auto Ease tangents': '自动缓动切线', 'Auto Mix tangents': '自动混合切线',
                         'Raw': '原始', 'Sheen Tint': '光泽染色', 'Coat Tint': '涂层染色',
                         'Influence': '影响对象', 'Envelope': '包络', 'Alpha': 'Alpha 通道'})
max_path.write_text(json.dumps(maxcat, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
maya_path.write_text(json.dumps(maya, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(REVIEW / 'reviewed_keeps.json').write_text(json.dumps(sorted(kept), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(REVIEW / 'terminology_corrections.json').write_text(json.dumps(corrected, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Max catalog', len(maxcat), 'Maya catalog', len(maya['messages']), 'recorded terminology corrections', len(corrected))
