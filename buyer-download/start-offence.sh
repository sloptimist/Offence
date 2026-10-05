#!/bin/sh
cd "$(dirname "$0")" || exit 1
for py in python3.14 python3.13 python3.12 python3; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    "$py" launch.py "$@"
    exit $?
  fi
done
printf '%s\n' 'Install Python 3.12 or newer from python.org, then run this launcher again.'
read -r ignored
