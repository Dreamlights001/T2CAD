"""Project-owned CUDA llama.cpp process, with bounded loading and cancellation."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import httpx

from backend.store import ROOT


class LlamaServer:
    def __init__(self):
        self.process = None
        self.log = None
        self.url = None
        self.key = None
        self.path = None
        self.load_seconds = None
        self.ready = False

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()
        self.process = self.log = None
        self.ready = False

    def alive(self):
        return self.process is not None and self.process.poll() is None

    async def cancellable(self, operation, cancel, timeout):
        task = asyncio.create_task(operation)
        stopped = asyncio.create_task(cancel.wait())
        try:
            done, _ = await asyncio.wait([task, stopped], timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if stopped in done:
                raise asyncio.CancelledError()
            if task not in done:
                raise TimeoutError("Qwen3.8 请求超时，请查看 logs/llama-server.log")
            return await task
        except BaseException:
            self.close()
            raise
        finally:
            task.cancel()
            stopped.cancel()
            await asyncio.gather(task, stopped, return_exceptions=True)

    async def start(self, path, cancel, notify):
        binary = Path(os.getenv("T2CAD_LLAMA_SERVER", ROOT / "runtime/llama.cpp/bin/llama-server"))
        if not binary.is_file():
            raise RuntimeError("缺少 Qwen3.8 CUDA 运行时，请执行 bash scripts/install_llama_server.sh")
        self.close()
        self.path = Path(path)
        self.key = secrets.token_urlsafe(32)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        folder = ROOT / "logs"
        folder.mkdir(exist_ok=True)
        self.log = (folder / "llama-server.log").open("a", buffering=1)
        env = {**os.environ, "LD_LIBRARY_PATH": str(binary.parent.resolve()) + ":" + str(Path(sys.prefix) / "lib") + ":" + os.environ.get("LD_LIBRARY_PATH", "")}
        args = [str(binary), "--model", str(path), "--host", "127.0.0.1", "--port", str(port),
                "--api-key", self.key, "--alias", "qwen3.8-local", "--parallel", "1", "--gpu-layers", "99",
                "--ctx-size", os.getenv("T2CAD_CONTEXT", "8192"), "--batch-size", "256", "--ubatch-size", "128",
                "--threads", "4", "--flash-attn", "on", "--load-mode", "none", "--no-warmup", "--no-webui",
                "--jinja", "--chat-template-kwargs", '{"enable_thinking":false}', "--reasoning-budget", "0"]
        notify("model_loading", {"message": "正在加载 Qwen3.8 CUDA 运行时", "filename": Path(path).name, "runtime": "llama-server"})
        started = time.monotonic()
        self.process = subprocess.Popen(args, env=env, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log)

        async def wait_ready():
            async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
                while True:
                    if not self.alive():
                        raise RuntimeError("Qwen3.8 运行时已退出，请查看 logs/llama-server.log")
                    try:
                        response = await client.get(self.url + "/health")
                        if response.status_code == 200:
                            return
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.5)

        await self.cancellable(wait_ready(), cancel, float(os.getenv("T2CAD_MODEL_LOAD_TIMEOUT", "600")))
        self.ready = True
        self.load_seconds = round(time.monotonic() - started, 2)
        notify("model_ready", {"model": self.path.name, "load_seconds": self.load_seconds, "runtime": "llama-server"})

    async def generate(self, path, messages, schema, cancel, notify):
        if not self.alive() or not self.ready:
            await self.start(path, cancel, notify)
        notify("planning", {"message": "Qwen3.8 正在规划参数与建模特征", "model": self.path.name})
        started = time.monotonic()

        async def request():
            async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(300, connect=5)) as client:
                response = await client.post(self.url + "/v1/chat/completions",
                    headers={"Authorization": "Bearer " + self.key}, json={
                        "model": "qwen3.8-local", "messages": messages, "stream": False,
                        "temperature": 0.3, "top_p": 0.85, "max_tokens": 4096,
                        "chat_template_kwargs": {"enable_thinking": False},
                        "response_format": {"type": "json_schema", "json_schema": {"name": "cad_plan", "schema": schema}},
                    })
                if response.status_code != 200:
                    raise RuntimeError(f"Qwen3.8 请求失败 ({response.status_code}): {response.text[:1200]}")
                result = response.json()
                choice = result["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise ValueError("Qwen3.8 输出超出预算，请缩减本轮建模要求")
                content = choice["message"].get("content") or ""
                return {"type": "result", "response": json.loads(content), "usage": result.get("usage", {}),
                        "seconds": round(time.monotonic() - started, 2), "model": self.path.name, "runtime": "llama-server"}

        return await self.cancellable(request(), cancel, 310)
