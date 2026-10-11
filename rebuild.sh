#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p work-tmp.noindex
export TMPDIR="$PWD/work-tmp.noindex"
RUNTIME="${NETWORK_LAB_PYTHON:-.venv/bin/python}"
if [ ! -x "$RUNTIME" ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.lock
  RUNTIME=.venv/bin/python
fi
export PYTHONPATH="$PWD/src"
"$RUNTIME" scripts/verify_inputs.py
"$RUNTIME" -m network_lab.experiment "$@"
"$RUNTIME" scripts/frequency_checks.py
"$RUNTIME" scripts/render.py
"$RUNTIME" scripts/check_artifacts.py
