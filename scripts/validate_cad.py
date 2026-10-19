import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cadgen import read_step
import trimesh
from backend.examples import EXAMPLES
from backend.cad_runtime import ENGINE, cad_environment


def main():
    output = ROOT / "data/validation"
    output.mkdir(parents=True, exist_ok=True)
    report = {"date": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "engine": ENGINE, "examples": []}
    for key, design in EXAMPLES.items():
        folder = output / key
        folder.mkdir(exist_ok=True)
        (folder / "design.json").write_text(json.dumps(design, ensure_ascii=False))
        start = time.monotonic()
        done = subprocess.run([sys.executable, "-m", "backend.cad_worker", str(folder)], cwd=ROOT, env=cad_environment(), capture_output=True, text=True, timeout=180)
        if done.returncode:
            raise RuntimeError(done.stdout + done.stderr)
        result = json.loads((folder / "result.json").read_text())
        shape = read_step(folder / "model.step")
        mesh = trimesh.load(str(folder / "model.stl"), force="mesh")
        glb = trimesh.load(str(folder / "model.glb"), force="mesh")
        expected_glb = [result["metrics"]["size"][i] / 1000 for i in (0, 2, 1)]
        assert all(abs(a-b) < 0.0001 for a,b in zip(glb.extents, expected_glb))
        replay = folder / "standalone.py"
        replay.write_text((folder / "model.py").read_text())
        subprocess.run([sys.executable, str(replay)], cwd="/tmp", env=cad_environment(), check=True, capture_output=True, timeout=180)
        replay_shape = read_step(folder / "standalone.step")
        record = {"id": key, "name": design["name"], "features": len(design["features"]), "size_mm": result["metrics"]["size"],
                  "volume_mm3": shape.volume, "valid_step": shape.is_valid, "watertight_stl": mesh.is_watertight,
                  "step_relative_volume_error": abs(shape.volume - result["metrics"]["volume"]) / shape.volume,
                  "script_relative_volume_error": abs(shape.volume - replay_shape.volume) / shape.volume,
                  "worker_seconds": result["elapsed"], "validation_seconds": round(time.monotonic() - start, 2),
                  "files": {ext: (folder / ("model." + ext)).stat().st_size for ext in ["step", "stl", "glb", "py"]}}
        assert record["valid_step"] and record["watertight_stl"]
        assert record["step_relative_volume_error"] < 1e-7 and record["script_relative_volume_error"] < 1e-7
        report["examples"].append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs/cad-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
