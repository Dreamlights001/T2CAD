import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.inference import model_path
from backend.cad_runtime import cad_python, cad_environment

checks = {}
for package in ["fastapi", "pydantic", "trimesh", "llama-cpp-python"]:
    try:
        checks[package] = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        checks[package] = "MISSING"
try:
    from backend.runtime import load_cuda_runtime
    load_cuda_runtime()
    from llama_cpp import llama_supports_gpu_offload
    checks["cuda_backend"] = llama_supports_gpu_offload()
except Exception as exc:
    checks["cuda_backend"] = str(exc)
checks["python"] = sys.version
checks["model"] = str(model_path())
checks["model_exists"] = model_path().is_file()
checks["qwen38_runtime_exists"] = (Path(__file__).resolve().parents[1] / "runtime/llama.cpp/bin/llama-server").is_file()
checks["cad_python"] = str(cad_python())
try:
    probe = subprocess.run([str(cad_python()), "-c", "import json,importlib.metadata as m; from cadgen import build123d as bd; print(json.dumps({'versions': {p:m.version(p) for p in ['cadgen','build123d','bd-warehouse','cadquery-ocp-novtk']}, 'box_volume':bd.Box(1,2,3).volume}))"],
                           env=cad_environment(), capture_output=True, text=True, timeout=60, check=True)
    checks["cad"] = json.loads(probe.stdout)
    checks["cad_ok"] = abs(checks["cad"]["box_volume"] - 6) < 1e-7
except Exception as exc:
    checks["cad_ok"] = False
    checks["cad_error"] = str(exc)
checks["gpu"] = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
print(json.dumps(checks, ensure_ascii=False, indent=2))
runtime_ok = checks["qwen38_runtime_exists"] if "Qwen3.8" in model_path().name else checks["cuda_backend"] is True
sys.exit(0 if runtime_ok and checks["model_exists"] and checks["cad_ok"] and "MISSING" not in checks.values() else 1)
