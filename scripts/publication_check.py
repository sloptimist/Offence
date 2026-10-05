"""Read-only publication gate. Reports locations, never matching secret values."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--private-rules', type=Path, help='Ignored local JSON array of forbidden identifying strings')
args = parser.parse_args()
files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root).decode().split('\0')
blocked = []
patterns = [
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{50,}\b'),
    re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b'),
]
private = json.loads(args.private_rules.read_text()) if args.private_rules else []
for name in sorted(set(files) - {''}):
    path = root / name
    if (any(part in {'.private','.startos','.git','data','node_modules','.venv','__pycache__'} for part in Path(name).parts)
            or name.endswith(('.s9pk','.pem','.macaroon','.sqlite','.log')) or Path(name).name.startswith('.env')):
        blocked.append((name, 'private or generated file'))
        continue
    if path.is_symlink() and not path.resolve().is_relative_to(root):
        blocked.append((name, 'external symlink'))
        continue
    data = path.read_bytes()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        continue
    for number, line in enumerate(text.splitlines(), 1):
        if any(p.search(line) for p in patterns):
            blocked.append((name, f'possible credential at line {number}'))
        if any(term.casefold() in line.casefold() for term in private):
            blocked.append((name, f'private identifier at line {number}'))
print(json.dumps({'candidate_files':len(set(files)-{''}), 'findings':blocked}, indent=2))
sys.exit(bool(blocked))
