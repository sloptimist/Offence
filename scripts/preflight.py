"""Read-only release checks. Never stages, commits, signs, or deploys."""
from pathlib import Path
import re
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], text=True, capture_output=True)

version = re.search(r"version: '([^']+)'", (ROOT / 'startos/versions/index.ts').read_text()).group(1)
blockers = []
if git('rev-parse', '--verify', 'HEAD').returncode:
    print('Warning: uncommitted initial tree; source snapshot required, no commit or push performed.')
snapshot = ROOT / '.startos/source-snapshot.json'
if not snapshot.exists():
    blockers.append('Missing source snapshot; run scripts/snapshot.py before packaging.')
else:
    recorded = json.loads(snapshot.read_text())
    paths = git('ls-files', '--cached', '--others', '--exclude-standard').stdout.splitlines()
    actual = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(set(paths))}
    if actual != recorded.get('files') or recorded.get('version') != version:
        blockers.append('Source or version changed since snapshot; refresh it before packaging.')
tracked = git('ls-files').stdout.splitlines()
if any(p.endswith(('.key.pem', '.macaroon', '.s9pk')) or p.startswith(('data/', '.startos/', '.private/')) for p in tracked):
    blockers.append('A secret, runtime file, or package artifact is tracked.')
for path in ['.startos/build.key.pem', 'data/identity.key', 'test.s9pk', 'node_modules/a', '.venv/a', '.private/operator.json', 'offence/__pycache__/a.pyc']:
    if git('check-ignore', path).returncode:
        blockers.append(f'Missing ignore rule: {path}')
last = ROOT / '.startos/last-packed-version'
if last.exists() and last.read_text().strip() == version:
    blockers.append('Version was already packed; increment the package revision.')
print('Version:', version)
print('Remote:', git('remote', '-v').stdout.strip() or '(none configured)')
print('Working tree:\n' + git('status', '--short').stdout.strip())
print('Verdict:', 'NO-GO' if blockers else 'GO')
for blocker in blockers:
    print('-', blocker)
sys.exit(bool(blockers))
