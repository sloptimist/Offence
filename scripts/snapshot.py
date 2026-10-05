"""Record the exact nonignored source tree without creating a Git commit."""
from pathlib import Path
import hashlib
import json
import re
import subprocess

root = Path(__file__).resolve().parents[1]
paths = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--cached', '--others',
                                 '--exclude-standard'], text=True).splitlines()
files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(set(paths))}
version = re.search(r"version: '([^']+)'", (root / 'startos/versions/index.ts').read_text()).group(1)
tree_hash = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
record = {'version': version, 'tree_sha256': tree_hash, 'files': files}
output = root / '.startos/source-snapshot.json'
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(record, indent=2) + '\n')
print(f'{version}: {len(files)} source files; SHA-256 {tree_hash}')
