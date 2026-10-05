"""StartOS-owned, offline migration before the unprivileged daemon starts."""
import os
from pathlib import Path
import stat
import sys

UID = 10001
LEGACY = ("identity.key", "offence.sqlite", "offence.sqlite-wal", "offence.sqlite-shm", "buyer")


def prepare(root, uid=UID, gid=UID):
    root = Path(root)
    runtime = root / "runtime"
    if root.is_symlink() or runtime.is_symlink():
        raise ValueError("Unsafe runtime directory")
    root.chmod(0o755)
    runtime.mkdir(mode=0o700, exist_ok=True)
    # Validate before moving or changing ownership. Never follow service-created links.
    candidates = [runtime, *(root / name for name in LEGACY)]
    entries = []
    for base in candidates:
        if base.is_symlink():
            raise ValueError("Symlinks are not allowed in runtime migration")
        if not base.exists():
            continue
        paths = [base, *base.rglob("*")] if base.is_dir() else [base]
        for path in paths:
            mode = path.lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)) or path.stat().st_nlink > 1 and path.is_file():
                raise ValueError("Unsafe runtime file")
        entries.extend(paths)
    for name in LEGACY:
        source, target = root / name, runtime / name
        if source.exists() and target.exists():
            raise ValueError("Conflicting old and migrated state; refusing overwrite")
    for name in LEGACY:
        source = root / name
        if source.exists():
            source.rename(runtime / name)
    for path in [runtime, *runtime.rglob("*")]:
        os.chown(path, uid, gid, follow_symlinks=False)
        path.chmod(0o700 if path.is_dir() else 0o600)
    config = root / "config.json"
    if config.is_symlink():
        raise ValueError("Unsafe configuration file")
    if config.exists():
        config.chmod(0o644)


if __name__ == "__main__":
    prepare(sys.argv[1])
