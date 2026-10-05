"""Build a source-based buyer download from an explicit public-file allowlist."""
from pathlib import Path
import hashlib
import json
import zipfile

root = Path(__file__).resolve().parents[1]
out = root / '.startos' / 'offence-buyer.zip'
out.parent.mkdir(exist_ok=True)
names = ['launch.py', 'Start-Offence.command', 'Start-Offence.cmd', 'start-offence.sh',
         'buyer-requirements.lock', 'README.md']
files = [(root / 'buyer-download' / name, Path('offence-buyer') / name) for name in names]
files += [(p, Path('offence-buyer/offence') / p.name) for p in (root / 'offence').iterdir()
          if p.is_file() and p.suffix in {'.py', '.html', '.js', '.css'}]
files += [(root / 'LICENSE', Path('offence-buyer/LICENSE'))]
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for path, name in sorted(files):
        z.write(path, name)
print(json.dumps({'file': str(out), 'bytes': out.stat().st_size,
                  'sha256': hashlib.sha256(out.read_bytes()).hexdigest(), 'files': len(files)}))
