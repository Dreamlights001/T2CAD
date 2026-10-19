"""Live regression: Qwen3.8 plans CAD, then modifies that saved design."""
import argparse
import json
from pathlib import Path
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    report = {"model": "Qwen3.8-27B", "cases": []}
    with httpx.Client(base_url=args.url, timeout=30, trust_env=False) as client:
        created = client.post("/api/projects", json={"name": "Qwen3.8 修复验收"})
        created.raise_for_status()
        pid = created.json()["id"]
        for text, thickness in [("生成一个模数2、齿数17、厚度20毫米的圆柱直齿轮，不需要内孔。", 20),
                                ("把齿轮厚度改为15毫米，模数2和齿数17保持不变，不要加孔。", 15)]:
            base = client.get(f"/api/projects/{pid}").json()["current_revision"]
            response = client.post(f"/api/projects/{pid}/messages", json={"text": text, "base_revision": base})
            response.raise_for_status()
            jid = response.json()["id"]
            start = time.monotonic()
            last = None
            while time.monotonic() - start < 950:
                job = client.get(f"/api/jobs/{jid}").json()
                state = job["events"][-1]["type"] if job["events"] else job["status"]
                if state != last:
                    print(jid, state, round(time.monotonic() - start, 1), flush=True)
                    last = state
                if job["status"] not in ("running", "queued"):
                    break
                time.sleep(1)
            else:
                client.post(f"/api/jobs/{jid}/cancel")
                raise TimeoutError("Qwen3.8 acceptance timed out")
            health = client.get("/api/health").json()
            case = {"prompt": text, "job_id": jid, "project_id": pid, "status": job["status"],
                    "seconds": round(time.monotonic() - start, 2), "health": health, "error": job.get("error"),
                    "inference": [e["data"] for e in job["events"] if e["type"] == "inference"],
                    "fallbacks": [e for e in job["events"] if e["type"] == "model_fallback"]}
            report["cases"].append(case)
            (ROOT / "docs/qwen38-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            assert job["status"] == "completed", job.get("error")
            assert health["active_model"] == "Qwen3.8-27B-Q4_K_M.gguf", health
            assert not case["fallbacks"]
            revision = client.get(f"/api/projects/{pid}").json()["revision"]
            assert abs(revision["result"]["metrics"]["size"][2] - thickness) < 1e-5
            gear = next(f for f in revision["design"]["features"] if f["op"] == "gear")
            parameters = {p["name"]: p["value"] for p in revision["design"]["parameters"]}
            from backend.cadgen_engine import number
            assert number(gear["args"]["module"], parameters) == 2
            assert number(gear["args"]["teeth"], parameters) == 17
            assert revision["result"].get("engine", "").startswith("earthtojake/text-to-cad")
            folder = Path(revision["folder"])
            for name in ["model.step", "model.FCStd", "model.stl"]:
                assert (folder / name).stat().st_size > 100
            case["revision_id"] = revision["id"]
            case["metrics"] = revision["result"]["metrics"]
            case["verified"] = True
            (ROOT / "docs/qwen38-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print("PASS", json.dumps(case, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    main()
