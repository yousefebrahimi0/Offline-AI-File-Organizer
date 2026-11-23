#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' "Python 3.9+ is required. Install it from python.org."
  exit 1
fi
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[gui]"
exec offline-ai-organizer-gui
