"""Run a CAD source/validation program in the isolated cadgen environment."""
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.cad_runtime import cad_python, cad_environment

if len(sys.argv) < 2:
    sys.exit("用法: python scripts/run_cad.py <模型.py 或验证脚本> [参数]")
if not cad_python().is_file():
    sys.exit("请先执行 bash scripts/install_cad.sh")
raise SystemExit(subprocess.call([str(cad_python()), *sys.argv[1:]], env=cad_environment()))
