"""Emit self-contained model programs using cadgen's supported source entrypoint."""
import json
from pathlib import Path


def model_source(design):
    engine = Path(__file__).with_name("cadgen_engine.py").read_text()
    setup = '''import os
import json
os.environ["CADGEN_TELEMETRY"] = "0"
os.environ["CADGEN_UPDATE_CHECK"] = "0"
os.environ["CADGEN_DAEMON"] = "0"
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
'''
    footer = '''
import json
from pathlib import Path
import time
from cadgen import build123d as bd
from cadgen import step, stl, glb, read_step

HERE = Path(__file__).resolve().parent
STEM = Path(__file__).stem

@step(out=Path(__file__).with_suffix(".step"))
@stl(out=Path(__file__).with_suffix(".stl"), mesh_tolerance=3e-4, mesh_angular_tolerance=0.1)
@glb(out=Path(__file__).with_suffix(".glb"), mesh_tolerance=3e-4, mesh_angular_tolerance=0.1)
def model():
    started = time.monotonic()
    steps = []
    for i, (feature, shape, metrics) in enumerate(build(DESIGN)):
        filename = f"step-{i:02d}.stl"
        bd.export_stl(shape, HERE / filename, tolerance=0.03, angular_tolerance=0.1)
        item = {"index": i, "feature": feature, "file": filename,
                "metrics": metrics, "elapsed": round(time.monotonic() - started, 3)}
        steps.append(item)
        print(json.dumps({"type": "feature", "data": item}, ensure_ascii=False), flush=True)
    if metrics["solids"] != 1:
        raise CADFailure("最终零件必须为一个连通实体；请合并相接零件或检查间隙")
    (HERE / (STEM + ".history.json")).write_text(json.dumps(steps, ensure_ascii=False, indent=2))
    return shape

if __name__ == "__main__":
    started = time.monotonic()
    model()
    steps = json.loads((HERE / (STEM + ".history.json")).read_text())
    saved = read_step(Path(__file__).with_suffix(".step"))
    measured = shape_metrics(saved)
    planned = steps[-1]["metrics"]
    if abs(measured["volume"] - planned["volume"]) > max(1e-5, planned["volume"]*1e-7):
        raise CADFailure("cadgen STEP 回读与生成几何体积不一致")
    measured["dimensions"] = planned.get("dimensions", [])
    if "gear" in planned:
        measured["gear"] = planned["gear"]
    result = {"steps": steps, "metrics": measured, "elapsed": round(time.monotonic() - started, 3),
              "engine": "earthtojake/text-to-cad / cadgen 0.7.24 / build123d",
              "exports": ["step", "stl", "glb", "py", "json"], "step_readback": True}
    (HERE / (STEM + ".result.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2))
'''
    return setup + engine + "\nDESIGN = json.loads(" + repr(json.dumps(design, ensure_ascii=False)) + ")\n" + footer
