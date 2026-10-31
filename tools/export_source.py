"""Archive editable source and build/test scripts; omit disposable Blender state."""
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / 'src/dcc_workflow_kit/blender_manifest.toml').read_text(encoding='utf-8'), re.M)[1]
DEST = ROOT / f'dist/dcc-workflow-kit-{VERSION}-source.zip'
with zipfile.ZipFile(DEST, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for path in sorted(ROOT.rglob('*')):
        rel = path.relative_to(ROOT)
        if not path.is_file() or any(p in {'dist', 'test-results', '__pycache__', '.git', 'user_data'} for p in rel.parts):
            continue
        if path.suffix in {'.pyc', '.blend1'}:
            continue
        z.write(path, 'dcc-workflow-kit/' + rel.as_posix())
with zipfile.ZipFile(DEST) as z:
    assert z.testzip() is None
sha = hashlib.sha256(DEST.read_bytes()).hexdigest()
DEST.with_suffix('.zip.sha256').write_text(sha + '  ' + DEST.name + '\n', encoding='ascii')
print(json.dumps({'source_zip': str(DEST), 'bytes': DEST.stat().st_size, 'sha256': sha}, indent=2))
