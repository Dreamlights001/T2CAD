import json
import os
from pathlib import Path
import signal
import time

ROOT = Path(__file__).resolve().parents[1]
runtime = ROOT / "logs/runtime.json"
try:
    saved = json.loads(runtime.read_text())
    pid = int(saved["pid"])
    process = Path(f"/proc/{pid}")
    if process.joinpath("cwd").resolve() != ROOT or "scripts/start.py" not in process.joinpath("cmdline").read_text():
        raise RuntimeError("记录中的 PID 不属于本项目启动器，未发送停止信号")
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        if not process.exists():
            break
        status = process.joinpath("status").read_text()
        if any(line.startswith("State:") and "Z" in line for line in status.splitlines()):
            break
        time.sleep(0.2)
    print("T2CAD 停止请求已完成。")
except FileNotFoundError:
    print("没有找到正在运行的 T2CAD 启动器。")
