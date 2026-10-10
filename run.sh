#!/usr/bin/env bash
# ./run.sh <wav_folder> [options] -> out/results.json + out/results/<id>.json + out/snippets/. See run.py --help.
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
exec "$PY" run.py "$@"
