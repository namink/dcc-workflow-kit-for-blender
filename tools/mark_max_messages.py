"""Keep English source messages marked; catalog edits need no further code edits."""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDER = ROOT / 'src/dcc_workflow_kit/providers/max'
messages = set()


class Mark(ast.NodeTransformer):
    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node
        return self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in {'_msg', '_dcc_format'}:
            if isinstance(node.args[0], ast.Constant):
                messages.add(node.args[0].value)
            return node
        return self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str) and re.search('[a-z]', node.value) and (node.value[:1].isupper() or ' ' in node.value) and not any(x in node.value for x in ('\n', '\\', '.blend', '.py', '<', '>', '=')):
            messages.add(node.value)
            return ast.copy_location(ast.Call(func=ast.Name(id='_msg', ctx=ast.Load()), args=[node], keywords=[]), node)
        return node

    def visit_JoinedStr(self, node):
        if not any(isinstance(x, ast.Constant) and isinstance(x.value, str) and re.search('[A-Za-z]', x.value) for x in node.values):
            return node
        template, values = '', []
        for part in node.values:
            if isinstance(part, ast.Constant):
                template += str(part.value).replace('{', '{{').replace('}', '}}')
            else:
                spec = ''
                if part.format_spec:
                    if not all(isinstance(x, ast.Constant) for x in part.format_spec.values):
                        return node
                    spec = ':' + ''.join(x.value for x in part.format_spec.values)
                conversion = '!' + chr(part.conversion) if part.conversion != -1 else ''
                template += '{' + str(len(values)) + conversion + spec + '}'
                values.append(part.value)
        messages.add(template)
        return ast.copy_location(ast.Call(func=ast.Name(id='_dcc_format', ctx=ast.Load()), args=[ast.Constant(template)] + values, keywords=[]), node)


for path in PROVIDER.glob('*.py'):
    if path.name in {'i18n.py', 'compat.py'}:
        continue
    source = path.read_text(encoding='utf-8')
    tree = Mark().visit(ast.parse(source))
    ast.fix_missing_locations(tree)
    text = ast.unparse(tree)
    text = text.replace('display as _dcc_ui_text', 'display as _dcc_ui_text, format_message as _dcc_format')
    path.write_text('# SPDX-License-Identifier: GPL-3.0-or-later\n# Adapted for DCC Workflow Kit.\n' + text + '\n', encoding='utf-8')
(ROOT / 'terminology/max_source_messages.json').write_text(json.dumps(sorted(messages), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Marked source messages:', len(messages))
