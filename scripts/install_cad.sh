#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CONDA_BIN="${CONDA_EXE:-$HOME/miniconda3/bin/conda}"
if ! "$CONDA_BIN" env list --json | "$CONDA_BIN" run -n base python -c 'import json,sys;sys.exit(not any(p.endswith("/T2CAD-CAD") for p in json.load(sys.stdin)["envs"]))'; then
  "$CONDA_BIN" create -n T2CAD-CAD python=3.11 pip -y --override-channels -c conda-forge
fi
"$CONDA_BIN" run --no-capture-output -n T2CAD-CAD python -m pip install -r requirements-cad.txt
env -u PYTHONPATH "$CONDA_BIN" run --no-capture-output -n T2CAD-CAD python -c 'import cadgen; from cadgen import build123d as bd; print("cadgen",cadgen.__version__,"shape volume",bd.Box(1,2,3).volume)'
