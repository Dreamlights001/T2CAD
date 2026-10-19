import os
from pathlib import Path
import sys

from backend.store import ROOT

ENGINE = "earthtojake/text-to-cad / cadgen 0.7.24 / build123d"


def cad_python():
    configured = os.getenv("T2CAD_CAD_PYTHON")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(sys.executable).resolve().parents[2] / "T2CAD-CAD/bin/python"


def cad_environment():
    python = cad_python()
    environment = {**os.environ, "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2",
                   "CADGEN_DAEMON": "0", "CADGEN_TELEMETRY": "0", "CADGEN_UPDATE_CHECK": "0",
                   "CADGEN_CACHE_DIR": str(ROOT / "data/cadgen-cache")}
    environment.pop("PYTHONPATH", None)
    environment["LD_LIBRARY_PATH"] = str(python.parents[1] / "lib")
    return environment
