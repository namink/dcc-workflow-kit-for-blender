"""Draft missing public UI messages, preserving placeholders and domain terminology.

This is an explicit maintenance command, never a runtime add-on dependency.
Only the English strings in localization-review/*_remaining_snapshot.json are sent.
"""
import concurrent.futures
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from audit_localization import keep_reason, BRANDS

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'localization-review'
TECHNICAL = BRANDS | {'Cycles', 'EEVEE', 'Physical Material', 'Principled BSDF', 'mCloth', 'mParticles',
                     'gPoly', 'Iray', 'Euler', 'Bezier', 'MAXtoA', 'OpenEXR', 'DCC', 'JSON', 'XML', 'CSV'}
TERMS = {
    'max': {'Command Panel': '命令面板', 'Modifier Stack': '修改器堆栈', 'Quad Menu': '四元菜单',
            'Working Pivot': '工作轴心', 'Pivot': '轴心', 'Material Editor': '材质编辑器',
            'Scene Explorer': '场景资源管理器', 'Layer Explorer': '层资源管理器', 'Track View': '轨迹视图',
            'Curve Editor': '曲线编辑器', 'Dope Sheet': '摄影表', 'Sub-object': '子对象', 'sub-object': '子对象',
            'Editable Poly': '可编辑多边形', 'Editable Mesh': '可编辑网格', 'Editable Spline': '可编辑样条线',
            'Space Warp': '空间扭曲', 'space warp': '空间扭曲', 'UVW Map': 'UVW 贴图', 'Unwrap UVW': 'UVW 展开',
            'Skin Pose': '蒙皮姿势', 'Smoothing Groups': '平滑组', 'Key Filters': '关键点过滤器',
            'Selection Set': '选择集', 'Viewport': '视口', 'viewport': '视口', 'Spinner': '微调器'},
    'maya': {'Channel Box': '通道盒', 'Attribute Editor': '属性编辑器', 'Graph Editor': '曲线图编辑器',
             'Dope Sheet': '摄影表', 'Marking Menu': '标记菜单', 'Hotbox': '热盒', 'Construction History': '构建历史',
             'Freeze Transformations': '冻结变换', 'Blend Shape': '混合变形', 'blend shape': '混合变形',
             'blendShape': 'blendShape', 'Set Driven Key': '设置驱动关键帧', 'UV Shell': 'UV 壳',
             'Skin Weights': '蒙皮权重', 'skin weights': '蒙皮权重', 'Bind Pose': '绑定姿势',
             'bind pose': '绑定姿势', 'bind poses': '绑定姿势', 'Pole Vector': '极向量',
             'Motion Trail': '运动轨迹', 'motion path': '运动路径', 'motion paths': '运动路径',
             'Paint Skin Weights': '绘制蒙皮权重', 'Dependency Graph': '依存关系图', 'deformer': '变形器',
             'deformers': '变形器', 'Pivot': '枢轴', 'pivot': '枢轴', 'influence': '影响对象',
             'influences': '影响对象', 'breakdown': '受控关键点', 'breakdowns': '受控关键点',
             'Playblast': '播放预览', 'tool shelf': '工具架', 'keyframe': '关键帧',
             'Shape Key': '形态键', 'shape keys': '形态键', 'shape key': '形态键'}
}

COMMON_TERMS = {'Bezier': '贝塞尔', 'World': '世界', 'world': '世界', 'Vertex': '顶点', 'vertex': '顶点',
                'Vertices': '顶点', 'vertices': '顶点', 'Bone': '骨骼', 'bone': '骨骼',
                'Joint': '关节', 'joint': '关节', 'joints': '关节', 'Skin': '蒙皮', 'skin': '蒙皮',
                'UVs': 'UV', 'Normals': '法线', 'normals': '法线', 'Tangent': '切线', 'tangent': '切线',
                'Tangents': '切线', 'tangents': '切线', 'Material': '材质', 'material': '材质',
                'Materials': '材质', 'materials': '材质', 'Texture': '纹理', 'texture': '纹理',
                'Mesh': '网格', 'mesh': '网格', 'Meshes': '网格', 'meshes': '网格',
                'Camera': '摄影机', 'camera': '摄影机', 'Cameras': '摄影机', 'cameras': '摄影机',
                'Object': '对象', 'object': '对象', 'Objects': '对象', 'objects': '对象',
                'Selection': '选择', 'selection': '选择', 'Controller': '控制器', 'controller': '控制器',
                'Controllers': '控制器', 'controllers': '控制器'}
for domain in TERMS:
    TERMS[domain] = {**COMMON_TERMS, **TERMS[domain]}
TERMS['max'].update({'Time Configuration': '时间配置', 'Sample Windows': '示例窗',
                     'Edged Faces': '边面', 'Key': '关键点', 'key': '关键点', 'Keys': '关键点', 'keys': '关键点',
                     'Explorer': '资源管理器', 'Explorers': '资源管理器', 'Map': '贴图', 'Maps': '贴图',
                     'map': '贴图', 'maps': '贴图', 'Modifier': '修改器', 'modifier': '修改器',
                     'Modifiers': '修改器', 'modifiers': '修改器', 'Rollout': '卷展栏',
                     'Normals': '法线', 'Geosphere': '几何球体', 'Gizmo': 'Gizmo'})
TERMS['maya'].update({'Key': '关键帧', 'key': '关键帧', 'Keys': '关键帧', 'keys': '关键帧',
                      'Curve': '曲线', 'curve': '曲线', 'Curves': '曲线', 'curves': '曲线',
                      'BlendShape': '混合变形', 'Deformer': '变形器', 'Deformers': '变形器',
                      'Influence': '影响对象', 'Influences': '影响对象', 'Envelope': '包络', 'envelope': '包络'})


def protect(text, domain):
    values = []
    def slot(value):
        name = f'ZXQPH{len(values):03d}QXZ'
        values.append(value)
        return name
    # Code-bearing interpolation expressions and printf placeholders are opaque.
    text = re.sub(r'\{[^{}]*\}|%(?:\([^)]+\))?[#0 +\-]*\d*(?:\.\d+)?[a-zA-Z]', lambda m: slot(m.group(0)), text)
    names = {name: name for name in TECHNICAL}
    names.update(TERMS[domain])
    if re.search(r'\b(?:Press|press|keyboard|Keyboard|shortcut|hotkey)\b', text):
        for word in ('Key', 'Keys', 'key', 'keys'):
            names[word] = '按键'
    pattern = re.compile(r'(?<![A-Za-z0-9_])(' + '|'.join(re.escape(k) for k in sorted(names, key=len, reverse=True)) + r')(?![A-Za-z0-9_])')
    text = pattern.sub(lambda m: slot(names[m.group(0)]), text)
    return text.replace('\n', ' ZXQNEWLINEQXZ '), values


def restore(text, values):
    text = text.replace('ZXQNEWLINEQXZ', '\n')
    for index, value in enumerate(values):
        pattern = re.compile(r'ZXQPH\s*' + f'{index:03d}' + r'\s*QXZ', re.I)
        if not pattern.search(text):
            raise ValueError('A protected placeholder was lost')
        text = pattern.sub(lambda m: value, text)
    if re.search(r'ZXQPH\d+QXZ|\n\s*\d{6}\s*$', text):
        raise ValueError('Unresolved translation placeholder')
    return text.strip()


def translate(batch):
    prepared = []
    for item in batch:
        text, values = protect(item['english'], item['domain'])
        prepared.append((item, text, values))
    query = '\n'.join(f"{item['id']:06d} | {text}" for item, text, _ in prepared)
    url = 'https://m.youdao.com/translate?' + urllib.parse.urlencode({'inputtext': query, 'type': 'EN2ZH_CN'})
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=25) as response:
        page = response.read().decode('utf-8')
    match = re.search(r'<ul[^>]+id=["\']translateResult["\'][^>]*>(.*?)</ul>', page, re.S)
    if not match:
        raise ValueError('Translation service returned no text result')
    translated = html.unescape(re.sub(r'<[^>]*>', '', match.group(1))).strip()
    sections = list(re.finditer(r'(?m)^\s*(\d{1,6})\s*[|｜]\s*', translated))
    rows = {}
    for i, marker in enumerate(sections):
        end = sections[i + 1].start() if i + 1 < len(sections) else len(translated)
        rows[int(marker[1])] = translated[marker.end():end].strip()
    results = []
    for item, _, values in prepared:
        if item['id'] not in rows:
            results.append({**item, 'error': 'Translated row index missing'})
            continue
        try:
            value = restore(rows[item['id']], values)
            if not re.search('[\u3400-\u9fff]', value) and not keep_reason(item['english']):
                raise ValueError('No Chinese translation returned')
            results.append({**item, 'chinese': value, 'origin': 'Public translation draft with protected terminology; review required'})
        except ValueError as error:
            results.append({**item, 'error': str(error), 'draft': rows[item['id']]})
    time.sleep(0.25)
    return results


def main():
    cache_path = REVIEW / 'translation_drafts.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else []
    done = {(r['domain'], r['english']) for r in cache if 'chinese' in r}
    pending = []
    for domain in ('max', 'maya'):
        data = json.loads((REVIEW / f'{domain}_remaining_snapshot.json').read_text(encoding='utf-8'))
        for text in data:
            if (domain, text) not in done and not keep_reason(text):
                pending.append({'id': len(pending), 'domain': domain, 'english': text})
    batches, current, size = [], [], 0
    for item in pending:
        protected_length = len(protect(item['english'], item['domain'])[0]) + 15
        if size + protected_length > 420 and current:
            batches.append(current)
            current, size = [], 0
        current.append(item)
        size += protected_length
    if current:
        batches.append(current)
    print('Pending rows:', len(pending), 'batches:', len(batches), flush=True)
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(translate, batch): i for i, batch in enumerate(batches)}
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                rows = future.result()
                cache.extend(r for r in rows if 'chinese' in r)
                errors.extend(r for r in rows if 'error' in r)
            except Exception as error:
                errors.extend({**item, 'error': str(error)} for item in batches[index])
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print('Batch', index + 1, 'finished; cached', len(cache), 'errors', len(errors), flush=True)
    (REVIEW / 'translation_errors.json').write_text(json.dumps(errors, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Draft pass complete:', len(cache), 'translated,', len(errors), 'need manual translation', flush=True)


if __name__ == '__main__':
    main()
