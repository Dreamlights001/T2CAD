"""Real GPU model acceptance run against the running API; no mocked planner."""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import subprocess
import time
from zoneinfo import ZoneInfo

import httpx
import psutil
import cadquery as cq

ROOT = Path(__file__).resolve().parents[1]


def verify_geometry(kind, revision, expected_size, diameter):
    metrics = revision["result"]["metrics"]
    if kind == "plate":
        expected_volume = expected_size[0] * expected_size[1] * expected_size[2] - 4 * math.pi * (diameter/2)**2 * expected_size[2]
    elif kind == "sleeve":
        expected_volume = math.pi * ((18**2 - 10**2) * 45 + (24**2 - 18**2) * 6)
    else:
        expected_volume = math.pi * ((45**2 - 12**2) * 10 + (22**2 - 12**2) * 18 - 4 * 3.5**2 * 10)
    assert all(abs(a-b) < 1e-5 for a,b in zip(metrics["size"], expected_size)), f"包围尺寸不符合要求: {metrics['size']}"
    assert abs(metrics["volume"] - expected_volume) < 1e-3, f"体积不符合要求: {metrics['volume']} vs {expected_volume}"
    shape = cq.importers.importStep(str(Path(revision["folder"]) / "model.step")).val()
    cx = (metrics["bounds"][0] + metrics["bounds"][3]) / 2
    cy = (metrics["bounds"][1] + metrics["bounds"][4]) / 2
    cz = (metrics["bounds"][2] + metrics["bounds"][5]) / 2
    if kind == "plate":
        for sign_x in [-1, 1]:
            for sign_y in [-1, 1]:
                x, y = cx + sign_x * (expected_size[0] / 2 - 12), cy + sign_y * (expected_size[1] / 2 - 12)
                assert not shape.isInside((x, y, cz)), "Expected hole center is solid"
                assert shape.isInside((x + diameter/2 + 0.5, y, cz)), "Expected hole wall missing"
        return "尺寸、体积、四孔位置与孔壁符合预期"
    assert not shape.isInside((cx, cy, cz)), "中心孔未贯通"
    assert shape.isInside((cx + diameter/2 + 1, cy, cz)), "中心孔壁缺失"
    if kind == "flange":
        for dx, dy in [(33, 0), (-33, 0), (0, 33), (0, -33)]:
            assert not shape.isInside((cx+dx, cy+dy, metrics["bounds"][2]+5)), "螺栓孔位置不正确"
    return "包围尺寸、体积、中心孔及孔位符合预期"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.url, timeout=30)
    report = {"date": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "cases": [], "hardware": {}}
    pid = None
    prompts = [
        ("plate", "生成一个长100、宽60、厚8毫米的矩形安装板，四个直径6毫米的通孔，孔中心距相邻的两边均12毫米。不加圆角。", [100, 60, 8], 6),
        ("plate", "把四个孔的孔径改为8毫米，其他参数和孔位置不变。", [100, 60, 8], 8),
        ("plate", "板厚增加到10毫米，其他尺寸及孔位置保持不变。", [100, 60, 10], 8),
        ("plate", "把长度改为120毫米，仍保持孔中心距相邻两边12毫米，其他尺寸不变。", [120, 60, 10], 8),
        ("sleeve", "生成阶梯轴套：主体外径36、内径20、总高45毫米；底部有外径48、厚6毫米的同心底缘，底缘包含在总高45内。中心孔贯穿全部，不加倒角或圆角。", [48,48,45],20),
        ("flange", "生成带颈法兰：盘外径90、厚10毫米；盘顶同心凸台外径44、高18毫米；中心通孔直径24毫米。盘上直径66毫米的分布圆在正X、负X、正Y、负Y方向均匀布置四个直径7毫米的通孔，不加倒角。", [90,90,28],24),
    ]
    start_index = 0
    retry_project = None
    report_file = ROOT / "docs/llm-validation.json"
    if args.resume and report_file.exists():
        report = json.loads(report_file.read_text())
        for case in report["cases"]:
            if case["status"] != "completed":
                break
            start_index += 1
        if start_index < len(report["cases"]):
            retry_project = report["cases"][start_index]["project_id"]
        report.setdefault("previous_failures", []).extend(report["cases"][start_index:])
        report["cases"] = report["cases"][:start_index]
        if report["cases"]:
            pid = report["cases"][-1]["project_id"]
    for case_index, (kind, prompt, expected_size, diameter) in enumerate(prompts[start_index:], start_index):
        if retry_project and case_index == start_index:
            pid = retry_project
            if kind == "sleeve":
                prompt = "纠正上轮轴套。请严格按以下步骤：主体圆柱外径36毫米、高45毫米、origin=[0,0,0]；底缘圆柱外径48毫米、高6毫米、origin=[0,0,0]。两圆柱同底面重叠，不是上下叠放，主体高度不要减去底缘厚度。先union合并两实体，再对合并结果钻直径20毫米的中心通孔。最终外形48×48×45毫米。"
            elif kind == "flange":
                prompt = "纠正上轮法兰：圆盘直径90、高10、origin=[0,0,0]；凸台直径44、高18、origin=[0,0,10]。union合并后钻中心直径24通孔，再用bolt_circle布局半径33、数量4、孔径7，钻四个通孔。最终外形90×90×28毫米。"
        elif kind != "plate" or pid is None:
            pid = client.post("/api/projects", json={"name": "真实模型验收 · " + kind}).json()["id"]
        state = client.get(f"/api/projects/{pid}").json()
        response = client.post(f"/api/projects/{pid}/messages", json={"text": prompt, "base_revision": state["current_revision"]})
        response.raise_for_status()
        jid = response.json()["id"]
        started = time.monotonic()
        while True:
            job = client.get(f"/api/jobs/{jid}").json()
            if job["status"] not in ("queued", "running"):
                break
            if time.monotonic() - started > 1100:
                client.post(f"/api/jobs/{jid}/cancel")
                raise TimeoutError("Real model acceptance job timed out")
            time.sleep(1)
        record = {"project_id": pid, "job_id": jid, "prompt": prompt, "status": job["status"],
                  "seconds": round(time.monotonic() - started, 2), "repairs": sum(e["type"] == "repair" for e in job["events"]),
                  "error": job.get("error"), "verification": "未完成", "inference": [e["data"] for e in job["events"] if e["type"] == "inference"]}
        if job["status"] == "completed":
            state = client.get(f"/api/projects/{pid}").json()
            metrics = state["revision"]["result"]["metrics"]
            record.update({"revision_id": state["current_revision"], "metrics": metrics})
            try:
                record["verification"] = verify_geometry(kind, state["revision"], expected_size, diameter)
            except AssertionError as exc:
                record.update({"status": "verification_failed", "verification": str(exc)})
        report["cases"].append(record)
        report["hardware"] = {"gpu": subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader"], capture_output=True, text=True).stdout.strip(),
                              "ram_used_gb": round(psutil.virtual_memory().used/1024**3, 2), "ram_available_gb": round(psutil.virtual_memory().available/1024**3, 2),
                              "health": client.get("/api/health").json()}
        (ROOT / "docs/llm-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(record, ensure_ascii=False), flush=True)
        if record["status"] != "completed":
            raise RuntimeError("真实模型验收未完成，详见 docs/llm-validation.json")


if __name__ == "__main__":
    main()
