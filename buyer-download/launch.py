"""Bootstrap a private virtual environment from this download's pinned lockfile."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import venv

if sys.version_info < (3, 12):
    raise SystemExit('Install Python 3.12 or newer from python.org, then run this launcher again.')
root = Path(__file__).resolve().parent
venv_dir = root / '.buyer-venv'
python = venv_dir / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
lockfile = root / 'buyer-requirements.lock'
fingerprint = hashlib.sha256(lockfile.read_bytes()).hexdigest()
stamp = venv_dir / 'offence-dependencies.sha256'
if not python.exists():
    print('Creating the buyer environment in this extracted folder.', flush=True)
    venv.EnvBuilder(with_pip=True).create(venv_dir)
if not stamp.exists() or stamp.read_text() != fingerprint:
    print('Installing pinned Python dependencies from PyPI. No wallet or payment is configured.', flush=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                    '-r', str(lockfile)], check=True)
    subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
    stamp.write_text(fingerprint)
os.chdir(root)
raise SystemExit(subprocess.call([str(python), '-m', 'offence.buyer_launcher', *sys.argv[1:]]))
