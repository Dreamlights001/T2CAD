"""Start the API and independent Vite frontend, choosing unused local ports."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def free_port(start):
    for port in range(start, start + 100):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                pass
    raise RuntimeError("No available port")


def main():
    if not (ROOT / "frontend/node_modules").is_dir():
        sys.exit("请先在 frontend 目录执行 npm ci")
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    runtime = logs / "runtime.json"
    if runtime.is_file():
        try:
            saved = json.loads(runtime.read_text())
            os.kill(int(saved["pid"]), 0)
            with urllib.request.urlopen(saved["backend"] + "/api/health", timeout=2) as response:
                health = json.load(response)
            if health.get("service") == "t2cad":
                print(f"T2CAD 已运行: {saved['frontend']}\nAPI 文档: {saved['backend']}/docs", flush=True)
                return
        except (OSError, ValueError, KeyError):
            pass
    api_port, web_port = free_port(8000), free_port(5173)
    env = {**os.environ, "T2CAD_API_PORT": str(api_port), "T2CAD_FRONTEND": f"http://127.0.0.1:{web_port}",
           "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "PYTHONUNBUFFERED": "1"}
    env.pop("PYTHONPATH", None)
    conda_lib = Path(sys.executable).resolve().parents[1] / "lib"
    env["LD_LIBRARY_PATH"] = str(conda_lib) + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    children, handles = [], []

    def stop(*_):
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
        for handle in handles:
            handle.close()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    for name, command, cwd in [
        ("backend", [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(api_port), "--workers", "1"], ROOT),
        ("frontend", ["npm", "run", "dev", "--", "--port", str(web_port), "--strictPort"], ROOT / "frontend"),
    ]:
        handle = (logs / f"{name}.log").open("a", buffering=1)
        handles.append(handle)
        children.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=handle, start_new_session=True))
    info = {"frontend": f"http://127.0.0.1:{web_port}", "backend": f"http://127.0.0.1:{api_port}", "pid": os.getpid()}
    (logs / "runtime.json").write_text(json.dumps(info, indent=2))
    print(f"T2CAD 工作台: {info['frontend']}\nAPI 文档: {info['backend']}/docs\n日志: {logs}\nCtrl+C 停止所有服务。", flush=True)
    try:
        while all(c.poll() is None for c in children):
            time.sleep(1)
        print("服务退出，请检查 logs/backend.log 和 logs/frontend.log", flush=True)
    finally:
        stop()


if __name__ == "__main__":
    main()
