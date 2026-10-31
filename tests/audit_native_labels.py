"""Inspect actual registered Blender RNA labels in an isolated factory process."""
import json
import sys
from pathlib import Path
import bpy
import addon_utils

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools')]
from audit_localization import keep_reason
addon_utils.enable('dcc_workflow_kit', default_set=True)
import dcc_workflow_kit as kit
kit.preferences.get().profile = 'MAYA'
kit.core._pending = None
kit.core.set_mode('MAYA', layout=False)
kit.maya.i18n.refresh()
result = {'maya': [], 'max': []}
for context, texts in kit.maya.i18n._native_texts.items():
    for text in texts:
        if keep_reason(text):
            continue
        translated = kit.maya.i18n._translate(text, context)
        if translated == text:
            result['maya'].append({'english': str(text), 'context': context})
from dcc_workflow_kit.localization import catalog
maxcat = catalog('max')
for cls in (*kit.max_provider.CLASSES, *kit.max_provider.params.CLASSES):
    if not getattr(cls, 'is_registered', False):
        continue
    values = []
    for attr in ('bl_label', 'bl_description'):
        value = getattr(cls, attr, None)
        if isinstance(value, str):
            values.append((value, cls.__name__ + '.' + attr))
    for name in getattr(cls, '__annotations__', {}):
        prop = cls.bl_rna.properties.get(name)
        if prop is None:
            continue
        values += [(prop.name, cls.__name__ + '.' + name), (prop.description, cls.__name__ + '.' + name)]
        if prop.type == 'ENUM':
            values += [(value.name, cls.__name__ + '.' + name) for value in prop.enum_items]
            values += [(value.description, cls.__name__ + '.' + name) for value in prop.enum_items]
    for value, context in values:
        if value and not keep_reason(value) and maxcat.get(value, value) == value:
            result['max'].append({'english': str(value), 'context': context})
kit.core.set_mode('BLENDER', layout=False)
addon_utils.disable('dcc_workflow_kit', default_set=True)
out = ROOT / 'localization-review/native_labels_untranslated.json'
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print('Registered native untranslated labels:', {key: len(value) for key, value in result.items()})
