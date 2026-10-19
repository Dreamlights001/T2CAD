"""Adapter around the upstream MLYengineering/Text2CAD FreeCAD runner.

The upstream runner is intentionally kept as the execution authority: it performs
contract checks, runs FreeCAD headlessly, saves FCStd/STEP, and reports stdout,
stderr, timeout, and CAD status. Local Qwen planning stays in inference.py.
"""
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
FREECAD_CMD = os.getenv("FREECAD_CMD", "/home/dlts/.local/opt/freecad/squashfs-root/usr/bin/freecadcmd")


def run_freecad_script(script: str, run_id: str, output_folder: Path):
    os.environ["FREECAD_CMD"] = FREECAD_CMD
    os.environ["CAD_WORKDIR"] = str(output_folder / "text2cad_runs")
    os.environ.setdefault("OCC_PY", os.environ.get("T2CAD_OCC_PY", ""))
    from vendor.text2cad.run_freecad import run_freecad_script as upstream_run

    result = upstream_run(script, run_id)
    run_dir = Path(result["out_dir"])
    for source, target in (("result.step", "model.step"), ("result.FCStd", "model.FCStd")):
        path = run_dir / source
        if path.is_file():
            shutil.copy2(path, output_folder / target)
    return result
