"""Build a directly installable Blender extension ZIP without developer artifacts."""
import ast
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/dcc_workflow_kit'
VERSION = re.search(r'^version\s*=\s*"([^"]+)"', (SOURCE / 'blender_manifest.toml').read_text(encoding='utf-8'), re.M)[1]
DEST = ROOT / f'dist/dcc-workflow-kit-{VERSION}.zip'


def main():
    DEST.parent.mkdir(exist_ok=True)
    paths = []
    with zipfile.ZipFile(DEST, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(SOURCE.rglob('*')):
            rel = path.relative_to(SOURCE)
            if not path.is_file() or '__pycache__' in rel.parts or path.suffix in {'.pyc', '.blend1'} or 'user_data' in rel.parts:
                continue
            data = path.read_bytes()
            if path.suffix == '.py':
                ast.parse(data, filename=str(rel))
            if rel.as_posix() == '__init__.py':
                text = data.decode('utf-8')
                tree = ast.parse(text)
                lines = text.splitlines(keepends=True)
                for node in reversed(tree.body):
                    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'bl_info' for t in node.targets):
                        lines[node.lineno - 1:node.end_lineno] = []
                data = ''.join(lines).encode('utf-8')
            archive.writestr(rel.as_posix(), data)
            paths.append(rel.as_posix())
        for name in ('LICENSE', 'THIRD_PARTY.md', 'README.md', 'LOCALIZATION_REPORT.md', 'MAYA_LOCALIZATION.md', 'MAYA_UPSTREAM.json'):
            archive.write(ROOT / name, name)
    with zipfile.ZipFile(DEST) as archive:
        assert archive.testzip() is None
        assert 'blender_manifest.toml' in archive.namelist()
    digest = hashlib.sha256(DEST.read_bytes()).hexdigest()
    DEST.with_suffix('.zip.sha256').write_text(digest + '  ' + DEST.name + '\n', encoding='ascii')
    print(json.dumps({'zip': str(DEST), 'source_files': len(paths), 'bytes': DEST.stat().st_size, 'sha256': digest}, indent=2))


if __name__ == '__main__':
    main()
