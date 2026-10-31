"""Connect additional catalog messages at display boundaries; preserve English data IDs."""
import ast
import json
from pathlib import Path
from audit_localization import source_text

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/dcc_workflow_kit/providers/maya'
CATALOG = SOURCE / 'translations_zh_HANS.json'
data = json.loads(CATALOG.read_text(encoding='utf-8'))
messages = data['messages']
changed = []
new_templates = {}


class Integrate(ast.NodeTransformer):
    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node
        return self.generic_visit(node)

    def visit_Call(self, node):
        name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
        if name in {'_dcc_source', '_dcc_format'}:
            return node
        # Existing _zh calls already translate at display time, and native() must
        # collect English RNA metadata. Preserve their original argument shape.
        if name in {'_zh', '_zh_native', '_zh_enum'}:
            return node
        node = self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr in {'label', 'operator', 'menu', 'prop', 'prop_enum', 'popover', 'popup_menu', 'invoke_confirm', 'header_text_set'}:
            for kw in node.keywords:
                if kw.arg in {'text', 'title', 'confirm_text'}:
                    if not (isinstance(kw.value, ast.Call) and isinstance(kw.value.func, ast.Name) and kw.value.func.id in {'_zh', '_dcc_display'}):
                        kw.value = self.display_expression(kw.value)
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'blf' and node.func.attr in {'draw', 'dimensions'} and len(node.args) > 1:
            node.args[1] = self.display_expression(node.args[1])
        return node

    def display_expression(self, value):
        if isinstance(value, ast.JoinedStr):
            original = source_text(value)
            template, args = '', []
            translated = messages.get(original)
            for part in value.values:
                if isinstance(part, ast.Constant):
                    template += part.value.replace('{', '{{').replace('}', '}}')
                else:
                    spec = ''
                    if part.format_spec:
                        if not all(isinstance(x, ast.Constant) for x in part.format_spec.values):
                            return value
                        spec = ':' + ''.join(x.value for x in part.format_spec.values)
                    conversion = '!' + chr(part.conversion) if part.conversion != -1 else ''
                    placeholder = '{' + str(len(args)) + conversion + spec + '}'
                    old = '{' + ast.unparse(part.value) + conversion + spec + '}'
                    template += placeholder
                    if translated:
                        translated = translated.replace(old, placeholder)
                    args.append(part.value)
            if translated:
                new_templates[template] = translated
            value = ast.Call(func=ast.Name(id='_dcc_format', ctx=ast.Load()), args=[ast.Constant(template)] + args, keywords=[])
        return ast.Call(func=ast.Name(id='_dcc_display', ctx=ast.Load()), args=[value], keywords=[])

    def visit_JoinedStr(self, node):
        # Do not touch code-bearing f-strings outside an actual display boundary.
        return node

    def visit_Constant(self, node):
        if isinstance(node.value, str) and node.value in messages and messages[node.value] != node.value:
            return ast.copy_location(ast.Call(func=ast.Name(id='_dcc_source', ctx=ast.Load()), args=[node], keywords=[]), node)
        return node


for path in sorted(SOURCE.rglob('*.py')):
    if path.name in {'i18n.py', 'compat.py'} or path == SOURCE / '__init__.py':
        continue
    original = path.read_text(encoding='utf-8')
    if 'source_message as _dcc_source' in original:
        continue
    tree = Integrate().visit(ast.parse(original))
    relative = path.relative_to(SOURCE)
    level = len(relative.parts)
    at = 1 if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) else 0
    while at < len(tree.body) and isinstance(tree.body[at], ast.ImportFrom) and tree.body[at].module == '__future__':
        at += 1
    tree.body.insert(at, ast.ImportFrom(module='i18n', names=[ast.alias(name='source_message', asname='_dcc_source'),
                                                            ast.alias(name='display_message', asname='_dcc_display'),
                                                            ast.alias(name='format_message', asname='_dcc_format')], level=level))
    ast.fix_missing_locations(tree)
    header = '# SPDX-License-Identifier: GPL-3.0-or-later\n# Simplified Chinese localization by namink; additional display integration 2026-10-31.\n'
    path.write_text(header + ast.unparse(tree) + '\n', encoding='utf-8')
    changed.append(relative.as_posix())
messages.update(new_templates)
CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Integrated additional display boundaries in', len(changed), 'files; numeric display templates:', len(new_templates))
