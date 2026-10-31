"""Add exact/case/punctuation variants reported by real Blender RNA registration."""
import gettext
import json
import re
from collections import defaultdict
from pathlib import Path
from audit_localization import keep_reason
from prepare_translation_drafts import derive

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/dcc_workflow_kit'
REVIEW = ROOT / 'localization-review'
report = json.loads((REVIEW / 'native_labels_untranslated.json').read_text(encoding='utf-8'))
maya_path = SOURCE / 'providers/maya/translations_zh_HANS.json'
max_path = SOURCE / 'locales/max_zh_HANS.json'
maya = json.loads(maya_path.read_text(encoding='utf-8'))
maxcat = json.loads(max_path.read_text(encoding='utf-8'))
with Path('C:/Program Files/Blender Foundation/Blender 5.2/5.2/datafiles/locale/zh_HANS/LC_MESSAGES/blender.mo').open('rb') as f:
    blender = gettext.GNUTranslations(f)
native = defaultdict(set)
for key, value in blender._catalog.items():
    if isinstance(key, str) and isinstance(value, str) and re.search('[\u3400-\u9fff]', value):
        native[key.rsplit('\x04', 1)[-1].casefold()].add(value)
kept = set(json.loads((REVIEW / 'reviewed_keeps.json').read_text(encoding='utf-8')))
pending = []
for domain in ('max', 'maya'):
    table = maxcat if domain == 'max' else maya['messages']
    memory = defaultdict(set)
    for key, value in table.items():
        if key != value:
            memory[key.strip().casefold()].add(value.strip())
    added = 0
    for en in sorted({r['english'] for r in report[domain]}):
        if keep_reason(en) or re.fullmatch(r'(?:[+-]?[XYZUVW]|(?:[0-9.]+\s*[x×]\s*)*[0-9.]+|HD \d+|[124]k Square|\.(?:bmp|tga|tiff))', en.strip()) or en.strip() in {'Ctrl', 'Alt', 'Shift', 'Esc', 'NTSC 4d', 'CCIR 601/Quantel NTSC', 'CCIR PAL/Quantel PAL'}:
            kept.add(en)
            continue
        if en in table and table[en] != en:
            continue
        candidates = [en, en.strip(), en.strip().replace('_', ' ')]
        translated = None
        for candidate in candidates:
            values = memory.get(candidate.casefold(), set())
            native_values = native.get(candidate.casefold(), set())
            translated = next(iter(values)) if len(values) == 1 else next(iter(native_values)) if len(native_values) == 1 else derive(candidate, domain)
            if translated:
                break
        if translated:
            table[en] = en[:len(en) - len(en.lstrip())] + translated
            added += 1
        else:
            pending.append({'domain': domain, 'english': en})
    print(domain, 'native variants added:', added)
for entries in maya['contexts'].values():
    for en, value in entries.items():
        if en == value and en not in kept and maya['messages'].get(en, en) != en:
            entries[en] = maya['messages'][en]
maya_path.write_text(json.dumps(maya, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
max_path.write_text(json.dumps(maxcat, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(REVIEW / 'reviewed_keeps.json').write_text(json.dumps(sorted(kept), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(REVIEW / 'native_pending_snapshot.json').write_text(json.dumps(pending, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
for i, row in enumerate(pending):
    print(i, row['domain'], ascii(row['english']))
