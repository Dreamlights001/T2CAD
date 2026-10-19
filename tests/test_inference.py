import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.inference import Inference, InferenceUnavailable


def test_default_does_not_fall_back_when_qwen38_file_is_missing(tmp_path, monkeypatch):
    from backend.inference import model_path
    monkeypatch.delenv("T2CAD_MODEL_PATH", raising=False)
    monkeypatch.setattr("backend.inference.MODEL_DIR", tmp_path)
    (tmp_path / "Qwen3-14B-Q4_K_M.gguf").touch()
    assert model_path().name == "Qwen3.8-27B-Q4_K_M.gguf"


def test_missing_dependency_reports_setup_error_before_loading():
    notified = []
    with patch("backend.inference.model_path", return_value=Path("Qwen3-14B-Q4_K_M.gguf")), patch("backend.inference.importlib.util.find_spec", return_value=None):
        with pytest.raises(InferenceUnavailable, match="未安装"):
            asyncio.run(Inference().generate([], asyncio.Event(), lambda *args: notified.append(args)))
    assert notified == []


def test_qwen38_uses_server_and_records_actual_model(tmp_path, monkeypatch):
    path = tmp_path / "Qwen3.8-27B-Q4_K_M.gguf"
    path.touch()
    engine = Inference()
    monkeypatch.setattr("backend.inference.model_path", lambda: path)

    async def generate(*args):
        assert args[0] == path
        engine.server.load_seconds = 2.5
        return {"response": {"action": "clarify", "summary": "尺寸？", "design": None}, "model": path.name}

    monkeypatch.setattr(engine.server, "generate", generate)
    result = asyncio.run(engine.generate([], asyncio.Event(), lambda *a: None))
    assert result["model"] == engine.active_model == path.name
    assert engine.loaded and engine.load_seconds == 2.5


def test_qwen38_failure_does_not_silently_load_14b(tmp_path, monkeypatch):
    path = tmp_path / "Qwen3.8-27B-Q4_K_M.gguf"
    path.touch()
    engine = Inference()
    monkeypatch.setattr("backend.inference.model_path", lambda: path)

    async def fail(*args):
        raise RuntimeError("CUDA failed")

    monkeypatch.setattr(engine.server, "generate", fail)
    with pytest.raises(InferenceUnavailable, match="CUDA failed"):
        asyncio.run(engine.generate([], asyncio.Event(), lambda *a: None))
    assert not engine.loaded and engine.active_model is None


@pytest.mark.parametrize("cancelled", [True, False])
def test_server_load_cancel_and_timeout_release_process(cancelled, monkeypatch):
    from backend.llama_server import LlamaServer
    server = LlamaServer()
    closed = []
    monkeypatch.setattr(server, "close", lambda: closed.append(True))

    async def run():
        cancel = asyncio.Event()
        if cancelled:
            cancel.set()
        with pytest.raises(asyncio.CancelledError if cancelled else TimeoutError):
            await server.cancellable(asyncio.sleep(10), cancel, 0.01)

    asyncio.run(run())
    assert closed == [True]
