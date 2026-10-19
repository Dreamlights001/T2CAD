#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
T2CAD_GEOM_PY="${T2CAD_CAD_PYTHON:-$HOME/miniconda3/envs/T2CAD-CAD/bin/python}"
env -u PYTHONPATH PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 CADGEN_TELEMETRY=0 CADGEN_UPDATE_CHECK=0 CADGEN_DAEMON=0 OPENBLAS_NUM_THREADS=2 "$T2CAD_GEOM_PY" -m pytest tests/test_engine.py -q "$@"
env -u PYTHONPATH PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_api.py tests/test_inference.py -q "$@"
