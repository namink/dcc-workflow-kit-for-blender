"""Mark translatable source literals without translating runtime user data.

The marker stores the unchanged English value. Only UI output boundaries translate
it. RNA/operation IDs, comparisons and object names retain their original values.
Run once after import_sources.py; edit the catalog afterwards without rerunning.
"""
import ast
import gettext
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / 'src/dcc_workflow_kit/providers/max'
LOCALES = PROJECT / 'src/dcc_workflow_kit/locales'


def main():
    with Path('C:/Program Files/Blender Foundation/Blender 5.2/5.2/datafiles/locale/zh_HANS/LC_MESSAGES/blender.mo').open('rb') as f:
        blender = gettext.GNUTranslations(f)
    terms = json.loads((PROJECT / 'terminology/max_overrides.json').read_text(encoding='utf-8'))
    catalog = {}
    candidates = set()
    parsed = {}
    for path in ROOT.glob('*.py'):
        if path.name in {'i18n.py', 'compat.py'}:
            continue
        text = path.read_text(encoding='utf-8')
        tree = ast.parse(text)
        parsed[path] = (text, tree)
        docs = {id(node.body[0].value) for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body and
                isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                s = node.value
                if any(c.islower() for c in s) and len(s) > 1:
                    candidates.add(s)
    for value in sorted(candidates):
        translated = terms.get(value, blender.gettext(value))
        if translated != value and any('\u3400' <= c <= '\u9fff' for c in translated):
            catalog[value] = translated
    catalog.update(terms)
    LOCALES.mkdir(exist_ok=True)
    (LOCALES / 'max_zh_HANS.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (PROJECT / 'terminology/max_untranslated_literals.json').write_text(
        json.dumps(sorted(candidates - set(catalog)), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    class Marker(ast.NodeTransformer):
        def visit_Expr(self, node):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node  # docstrings
            return self.generic_visit(node)

        def visit_JoinedStr(self, node):
            # Dynamic UI strings are handled separately; do not replace pieces of f-strings.
            return node

        def visit_Constant(self, node):
            if isinstance(node.value, str) and node.value in catalog:
                return ast.copy_location(ast.Call(func=ast.Name(id='_msg', ctx=ast.Load()), args=[node], keywords=[]), node)
            return node

        def visit_Call(self, node):
            node = self.generic_visit(node)
            fn = node.func
            # These boundaries receive source markers as well as user strings.
            # display() translates only a marker, leaving all user strings untouched.
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == 'blf' and fn.attr in {'draw', 'dimensions'} and len(node.args) > 1:
                node.args[1] = ast.Call(func=ast.Name(id='_dcc_ui_text', ctx=ast.Load()), args=[node.args[1]], keywords=[])
            if isinstance(fn, ast.Attribute) and fn.attr in {'label', 'operator', 'menu', 'prop', 'prop_enum', 'popover', 'panel'}:
                for kw in node.keywords:
                    if kw.arg == 'text':
                        kw.value = ast.Call(func=ast.Name(id='_dcc_ui_text', ctx=ast.Load()), args=[kw.value], keywords=[])
            # Contexts keep Max terminology separate from Maya and Blender defaults.
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ''
            if name.endswith('Property') and not any(kw.arg == 'translation_context' for kw in node.keywords):
                node.keywords.append(ast.keyword(arg='translation_context', value=ast.Constant('DCCWorkflowKit.Max')))
            if isinstance(fn, ast.Attribute) and fn.attr == 'report' and len(node.args) > 1:
                node.args[1] = ast.Call(func=ast.Name(id='_dcc_ui_text', ctx=ast.Load()), args=[node.args[1]], keywords=[])
            return node

        def visit_ClassDef(self, node):
            node = self.generic_visit(node)
            if any(isinstance(s, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'bl_label' for t in s.targets) for s in node.body):
                node.body.append(ast.Assign(targets=[ast.Name(id='bl_translation_context', ctx=ast.Store())], value=ast.Constant('DCCWorkflowKit.Max')))
            return node

    for path, (original, tree) in parsed.items():
        result = Marker().visit(tree)
        # str(value) in drawing would otherwise strip the source marker too soon.
        if path.name == 'surfaces.py':
            for node in ast.walk(result):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '_dcc_ui_text' and node.args and isinstance(node.args[0], ast.Call) and isinstance(node.args[0].func, ast.Name) and node.args[0].func.id == 'str':
                    node.args[0] = node.args[0].args[0]
        ast.fix_missing_locations(result)
        imports = 'from .i18n import msg as _msg, display as _dcc_ui_text\n'
        header = '# SPDX-License-Identifier: GPL-3.0-or-later\n# Adapted for unified lifecycle and context-aware localization; original English data identifiers retained.\n'
        path.write_text(header + imports + ast.unparse(result) + '\n', encoding='utf-8')
    print(json.dumps({'catalog_entries': len(catalog), 'source_literals_with_translation': len(candidates & set(catalog)),
                      'other_literals_for_review': len(candidates - set(catalog))}))


if __name__ == '__main__':
    main()
