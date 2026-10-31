"""Apply validated exact entries and reviewed overrides; never modify identifiers."""
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'localization-review'
SOURCE = ROOT / 'src/dcc_workflow_kit'
maya_path = SOURCE / 'providers/maya/translations_zh_HANS.json'
max_path = SOURCE / 'locales/max_zh_HANS.json'
maya = json.loads(maya_path.read_text(encoding='utf-8'))
maxcat = json.loads(max_path.read_text(encoding='utf-8'))
spec = importlib.util.spec_from_file_location('translation_validator', SOURCE / 'providers/maya/i18n.py')
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)
rows = json.loads((REVIEW / 'translation_drafts.json').read_text(encoding='utf-8'))
errors = json.loads((REVIEW / 'translation_errors.json').read_text(encoding='utf-8'))
kept = set()
manual = []
for line in (REVIEW / 'manual_error_translations.tsv').read_text(encoding='utf-8').splitlines():
    if not line or line.startswith('#'):
        continue
    number, translated = line.split('\t', 1)
    entry = errors[int(number)]
    if translated == 'KEEP':
        kept.add(entry['english'])
    else:
        manual.append({**entry, 'chinese': translated, 'origin': 'Individually translated and reviewed'})
rows += manual
rejected = []
applied = Counter()
for row in rows:
    en, zh, domain = row['english'], row['chinese'], row['domain']
    if '\n' in zh and '\n' not in en:
        rejected.append({**row, 'reason': 'Unexpected multiline result'})
        continue
    if re.search(r'ZXQPH\d+QXZ|^\d{6}\s*[|｜]|\n\s*\d{6}', zh, re.M):
        rejected.append({**row, 'reason': 'Unresolved translation marker'})
        continue
    source_parts, target_parts = validation._parse(en), validation._parse(zh)
    if '{' in en and len(re.findall('[A-Za-z]', ''.join(p[0] for p in source_parts))) >= 3:
        try:
            validation._Template(en, zh)
        except (ValueError, re.error) as error:
            rejected.append({**row, 'reason': 'Template: ' + str(error)})
            continue
    percent = r'%(?:\([^)]+\))?[#0 +\-]*\d*(?:\.\d+)?[a-zA-Z]'
    if Counter(re.findall(percent, en)) != Counter(re.findall(percent, zh)):
        rejected.append({**row, 'reason': 'Printf fields changed'})
        continue
    (maxcat if domain == 'max' else maya['messages'])[en] = zh
    applied[domain] += 1
for context in maya.get('contexts', {}).values():
    # Preserve intentional contextual translations; only replace untranslated echoes.
    for en, zh in context.items():
        if en == zh and en in maya['messages']:
            context[en] = maya['messages'][en]
max_path.write_text(json.dumps(maxcat, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
maya_path.write_text(json.dumps(maya, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(REVIEW / 'reviewed_keeps.json').write_text(json.dumps(sorted(kept), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(REVIEW / 'rejected_drafts.json').write_text(json.dumps(rejected, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Applied:', dict(applied), 'reviewed identifiers:', len(kept), 'rejected:', len(rejected))
