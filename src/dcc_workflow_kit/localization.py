# SPDX-License-Identifier: GPL-3.0-or-later
"""Context-separated English/Chinese UI messages; scene names are never translated."""
import json
from pathlib import Path
import bpy

CONTEXT = 'DCCWorkflowKit'
MAX_CONTEXT = 'DCCWorkflowKit.Max'
_catalogs = {}
_registered = False


def is_chinese():
    view = bpy.context.preferences.view
    language = view.language if view.language != 'DEFAULT' else bpy.app.translations.locale
    return view.use_translate_interface and language.lower().replace('-', '_') in {'zh_hans', 'zh_cn'}


def catalog(domain='common'):
    if domain not in _catalogs:
        path = Path(__file__).with_name('locales') / f'{domain}_zh_HANS.json'
        _catalogs[domain] = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    return _catalogs[domain]


def tr(text, domain='common'):
    return catalog(domain).get(text, text) if is_chinese() else text


def native(text):
    return text


def register():
    global _registered
    entries = {}
    for domain, context in [('common', CONTEXT), ('max', MAX_CONTEXT)]:
        entries.update({(context, key): value for key, value in catalog(domain).items()})
    bpy.app.translations.register(__name__, {'zh_HANS': entries, 'zh_CN': dict(entries)})
    _registered = True


def unregister():
    global _registered
    if _registered:
        bpy.app.translations.unregister(__name__)
    _registered = False
