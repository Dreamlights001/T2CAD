"""Verify real Qwen3.8 helical planning, handedness changes and exported replay."""
import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from backend.cad_runtime import cad_environment, cad_python
from backend.cadgen_engine import number


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    report = {"model": "Qwen3.8-27B", "cases": []}
    with httpx.Client(base_url=args.url, timeout=30, trust_env=False) as client:
        response = client.post("/api/projects", json={"name": "Qwen3.8 斜齿轮验收"})
        response.raise_for_status()
        pid = response.json()["id"]
        for prompt, beta in [
            ("生成一个模数2、齿数17、厚度20毫米，alpha20度，beta15度的圆柱斜齿轮，内孔直径12。", 15),
            ("把螺旋角改为-15度，改成左旋，其他尺寸和中心通孔保持不变。", -15),
        ]:
            base = client.get(f"/api/projects/{pid}").json()["current_revision"]
            response = client.post(f"/api/projects/{pid}/messages", json={"text": prompt, "base_revision": base})
            response.raise_for_status()
            jid = response.json()["id"]
            started, last = time.monotonic(), None
            while time.monotonic()-started < 950:
                job = client.get(f"/api/jobs/{jid}").json()
                state = job["events"][-1]["type"] if job["events"] else job["status"]
                if state != last:
                    print(jid, state, round(time.monotonic()-started, 1), flush=True)
                    last = state
                if job["status"] not in ("running", "queued"):
                    break
                time.sleep(1)
            else:
                client.post(f"/api/jobs/{jid}/cancel")
                raise TimeoutError("斜齿轮真实模型验收超时")
            assert job["status"] == "completed", job.get("error")
            health = client.get("/api/health").json()
            assert health["active_model"] == "Qwen3.8-27B-Q4_K_M.gguf"
            assert not any(e["type"] == "model_fallback" for e in job["events"])
            revision = client.get(f"/api/projects/{pid}").json()["revision"]
            design, result = revision["design"], revision["result"]
            parameters = {p["name"]: p["value"] for p in design["parameters"]}
            gear = next(f for f in design["features"] if f["op"] == "gear")
            bore = next(f for f in design["features"] if f["op"] == "hole")
            for key, value in {"module": 2, "teeth": 17, "height": 20, "pressure_angle": 20, "helix_angle": beta}.items():
                assert number(gear["args"][key], parameters) == value
            assert number(bore["args"]["diameter"], parameters) == 12
            spec = result["metrics"]["gear"]
            assert spec["module_system"] == "normal"
            assert spec["helix_angle"] == beta
            assert spec["hand"] == ("right" if beta > 0 else "left")
            assert abs(spec["pitch_diameter"]-34/math.cos(math.radians(beta))) < 1e-8
            assert abs(spec["twist_angle"]-math.degrees(40*math.tan(math.radians(beta))/spec["pitch_diameter"])) < 1e-8
            assert result["step_readback"] and result["mesh"]["watertight"]
            assert abs(result["metrics"]["size"][2]-20) < 1e-5
            assert result["engine"].startswith("earthtojake/text-to-cad")
            for ext in ("step", "stl", "glb", "py"):
                response = client.get(result["artifact_base"]+"/model."+ext)
                response.raise_for_status()
                assert len(response.content) > 100
            with tempfile.TemporaryDirectory(prefix="helical-replay-") as temporary:
                folder = Path(temporary)
                source = folder / "model.py"
                shutil.copyfile(Path(revision["folder"]) / "model.py", source)
                replay = subprocess.run([str(cad_python()), str(source), "--force"], cwd=folder,
                                        env=cad_environment(), capture_output=True, text=True, timeout=180)
                assert replay.returncode == 0, replay.stderr[-4000:]
                rebuilt = json.loads((folder / "model.result.json").read_text())
                error = abs(rebuilt["metrics"]["volume"]-result["metrics"]["volume"])/result["metrics"]["volume"]
                assert error < 1e-7
            case = {"prompt": prompt, "project_id": pid, "job_id": jid, "revision_id": revision["id"],
                    "seconds": round(time.monotonic()-started, 2), "model": health["active_model"],
                    "load_seconds": health["load_seconds"], "metrics": result["metrics"], "engine": result["engine"],
                    "script_relative_volume_error": error,
                    "repairs": [e["data"] for e in job["events"] if e["type"] == "repair"], "verified": True}
            report["cases"].append(case)
            (ROOT / "docs/helical-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print("PASS", json.dumps(case, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
