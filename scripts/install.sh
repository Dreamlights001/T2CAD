#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CONDA_BIN="${CONDA_EXE:-$HOME/miniconda3/bin/conda}"
if ! "$CONDA_BIN" env list --json | "$CONDA_BIN" run -n base python -c 'import json,sys; sys.exit(not any(p.endswith("/T2CAD") for p in json.load(sys.stdin)["envs"]))'; then
  "$CONDA_BIN" create -n T2CAD python=3.11 pip -y --override-channels -c conda-forge
fi
"$CONDA_BIN" run --no-capture-output -n T2CAD python -m pip install -r requirements.txt
"$CONDA_BIN" run --no-capture-output -n T2CAD bash scripts/install_inference.sh
"$CONDA_BIN" run --no-capture-output -n T2CAD bash scripts/install_llama_server.sh
bash scripts/install_cad.sh
npm --prefix frontend ci
"$CONDA_BIN" run --no-capture-output -n T2CAD python scripts/download_model.py
"$CONDA_BIN" run --no-capture-output -n T2CAD python scripts/check_environment.py
