import asyncio
from contextlib import asynccontextmanager
import json
import os
import signal
import shutil
from pathlib import Path
import sys
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
import psutil

from backend import store
from backend.examples import EXAMPLES, PROMPTS
from backend.inference import inference, model_path, SYSTEM, InferenceUnavailable
from backend.schema import Design, MessageRequest, ParameterRequest
from backend.cad_runtime import ENGINE, cad_python, cad_environment

tasks = {}
cancels = {}
queue = asyncio.Lock()
TERMINAL = {"completed", "failed", "cancelled", "interrupted", "clarification"}


@asynccontextmanager
async def lifespan(app):
    store.init()
    yield
    for cancel in cancels.values():
        cancel.set()
    for task in list(tasks.values()):
        task.cancel()
    await asyncio.gather(*list(tasks.values()), return_exceptions=True)
    inference.close()


app = FastAPI(title="T2CAD", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("T2CAD_FRONTEND", "http://127.0.0.1:5173")],
                   allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type", "Last-Event-ID"])


def project(pid):
    row = store.query("SELECT * FROM projects WHERE id=?", (pid,), one=True)
    if not row:
        raise HTTPException(404, "项目不存在")
    return row


def job(jid):
    row = store.query("SELECT * FROM jobs WHERE id=?", (jid,), one=True)
    if not row:
        raise HTTPException(404, "任务不存在")
    return row


class ProjectInput(BaseModel):
    name: str = Field(default="未命名零件", min_length=1, max_length=100)


def project_name(body: ProjectInput) -> str:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "项目名称不能为空")
    return name


@app.get("/api/health")
def health():
    path = model_path()
    memory = psutil.virtual_memory()
    return {"status": "ok", "service": "t2cad", "cad_engine": ENGINE, "cad_python": str(cad_python()), "model_exists": path.is_file(), "model_name": path.name,
            "model_loaded": inference.loaded and (inference.server.alive() if "Qwen3.8" in (inference.active_model or "") else bool(inference.process and inference.process.is_alive())),
            "active_model": inference.active_model, "load_seconds": inference.load_seconds,
            "ram_available_gb": round(memory.available / 1024**3, 2),
            "runtime": "llama-server CUDA / GGUF" if "Qwen3.8" in path.name else "llama-cpp-python CUDA / GGUF",
            "active_jobs": store.query("SELECT * FROM jobs WHERE status IN ('queued','running')")}


@app.get("/api/examples")
def examples():
    return [{"id": key, "name": value["name"], "prompt": PROMPTS[key], "features": len(value["features"])} for key, value in EXAMPLES.items()]


@app.get("/api/projects")
def projects():
    return store.query("SELECT * FROM projects ORDER BY created DESC")


@app.post("/api/projects")
def create_project(body: ProjectInput):
    pid = store.uid()
    store.execute("INSERT INTO projects VALUES(?,?,?,NULL)", (pid, project_name(body), store.now()))
    return project(pid)


@app.patch("/api/projects/{pid}")
def rename_project(pid: str, body: ProjectInput):
    project(pid)
    name = project_name(body)
    if store.query("SELECT id FROM jobs WHERE project_id=? AND status IN ('queued','running')", (pid,)):
        raise HTTPException(409, "项目正在生成，完成后再重命名")
    store.execute("UPDATE projects SET name=? WHERE id=?", (name, pid))
    store.message(pid, "system", f"项目已重命名为“{name}”。")
    return project(pid)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    project(pid)
    if store.query("SELECT id FROM jobs WHERE project_id=? AND status IN ('queued','running')", (pid,)):
        raise HTTPException(409, "项目正在生成，请先停止任务后再删除")
    folders = [Path(row["folder"]) for row in store.query("SELECT folder FROM revisions WHERE project_id=?", (pid,))]
    with store.connection() as db:
        db.execute("DELETE FROM events WHERE job_id IN (SELECT id FROM jobs WHERE project_id=?)", (pid,))
        db.execute("DELETE FROM messages WHERE project_id=?", (pid,))
        db.execute("DELETE FROM jobs WHERE project_id=?", (pid,))
        db.execute("DELETE FROM revisions WHERE project_id=?", (pid,))
        db.execute("DELETE FROM projects WHERE id=?", (pid,))
    for folder in folders:
        try:
            folder.resolve().relative_to((store.DATA / "artifacts").resolve())
        except ValueError:
            continue
        shutil.rmtree(folder, ignore_errors=True)
    return {"id": pid, "deleted": True}


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    data = project(pid)
    data["messages"] = store.query("SELECT * FROM messages WHERE project_id=? ORDER BY id", (pid,))
    data["revisions"] = store.query("SELECT id,created,parent FROM revisions WHERE project_id=? ORDER BY created DESC", (pid,))
    data["revision"] = store.revision(data["current_revision"]) if data["current_revision"] else None
    data["jobs"] = store.query("SELECT * FROM jobs WHERE project_id=? ORDER BY created DESC LIMIT 10", (pid,))
    return data


@app.get("/api/revisions/{rid}")
def get_revision(rid: str):
    row = store.revision(rid)
    if not row:
        raise HTTPException(404, "版本不存在")
    return row


@app.post("/api/projects/{pid}/restore/{rid}")
def restore(pid: str, rid: str):
    project(pid)
    row = get_revision(rid)
    if row["project_id"] != pid:
        raise HTTPException(404, "版本不属于该项目")
    if store.query("SELECT id FROM jobs WHERE project_id=? AND status IN ('queued','running')", (pid,)):
        raise HTTPException(409, "请先停止当前生成任务")
    store.execute("UPDATE projects SET current_revision=?,name=? WHERE id=?", (rid, row["design"]["name"], pid))
    store.message(pid, "system", "已切换到历史版本，可以继续修改。")
    return get_project(pid)


def launch(pid, base, text, design=None, source="llm"):
    p = project(pid)
    if p["current_revision"] != base:
        raise HTTPException(409, "当前版本已变化，请刷新后重新提交")
    if store.query("SELECT id FROM jobs WHERE project_id=? AND status IN ('queued','running')", (pid,)):
        raise HTTPException(409, "该项目已有进行中的任务")
    jid = store.uid()
    store.execute("INSERT INTO jobs VALUES(?,?,?,?,?,NULL)", (jid, pid, "queued", store.now(), base))
    store.message(pid, "user", text)
    store.event(jid, "queued", {"message": "等待执行", "source": source})
    cancels[jid] = asyncio.Event()
    tasks[jid] = asyncio.create_task(run_job(jid, text, design, source))
    return job(jid)


@app.post("/api/projects/{pid}/messages")
async def send_message(pid: str, body: MessageRequest):
    return launch(pid, body.base_revision, body.text)


@app.post("/api/projects/{pid}/examples/{key}")
async def example_job(pid: str, key: str):
    if key not in EXAMPLES:
        raise HTTPException(404, "示例不存在")
    return launch(pid, project(pid)["current_revision"], "运行内置示例：" + EXAMPLES[key]["name"], EXAMPLES[key], "example")


@app.patch("/api/projects/{pid}/parameters")
async def parameters(pid: str, body: ParameterRequest):
    p = project(pid)
    if not p["current_revision"] or p["current_revision"] != body.base_revision:
        raise HTTPException(409, "参数修改所基于的版本已变化")
    design = store.revision(body.base_revision)["design"]
    known = {item["name"] for item in design["parameters"]}
    if set(body.values) - known:
        raise HTTPException(422, "参数名不存在")
    for param in design["parameters"]:
        if param["name"] in body.values:
            param["value"] = body.values[param["name"]]
    try:
        Design.model_validate(design)
    except Exception as exc:
        raise HTTPException(422, str(exc))
    return launch(pid, body.base_revision, "参数修改：" + json.dumps(body.values, ensure_ascii=False), design, "parameters")


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    data = job(jid)
    data["events"] = [{**e, "data": json.loads(e["data"])} for e in store.query("SELECT * FROM events WHERE job_id=? ORDER BY id", (jid,))]
    return data


@app.post("/api/jobs/{jid}/cancel")
async def cancel_job(jid: str):
    job(jid)
    if jid in cancels:
        cancels[jid].set()
        tasks[jid].cancel()
    return {"status": "requested"}


@app.get("/api/jobs/{jid}/events")
async def event_stream(jid: str, request: Request, after: int = 0):
    job(jid)
    try:
        cursor = max(after, int(request.headers.get("last-event-id", "0")))
    except ValueError:
        raise HTTPException(400, "无效事件序号")

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            rows = store.query("SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id", (jid, cursor))
            for row in rows:
                cursor = row["id"]
                data = {"id": cursor, "job_id": jid, "project_id": job(jid)["project_id"], "type": row["type"], "data": json.loads(row["data"])}
                yield f"id: {cursor}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            if job(jid)["status"] in TERMINAL:
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/artifacts/{jid}/{attempt}/{filename}")
def artifact(jid: str, attempt: int, filename: str):
    job(jid)
    if filename not in {"design.json", "result.json", "model.step", "model.FCStd", "model.stl", "model.glb", "model.py"} and not (filename.startswith("step-") and filename.endswith(".stl") and filename[5:-4].isdigit()):
        raise HTTPException(404, "文件不存在")
    folder = store.DATA / "artifacts" / jid / str(attempt)
    path = folder / filename
    if not path.is_file():
        raise HTTPException(404, "文件尚未生成")
    return FileResponse(path, filename=filename)


async def compile_design(jid, attempt, design, cancel):
    folder = store.DATA / "artifacts" / jid / str(attempt)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "design.json").write_text(json.dumps(design, ensure_ascii=False, indent=2))
    python = cad_python()
    if not python.is_file():
        raise RuntimeError("缺少 cadgen 独立环境，请运行 bash scripts/install_cad.sh")
    env = cad_environment()
    stderr = (folder / "worker.log").open("w")
    process = await asyncio.create_subprocess_exec(str(python), "-m", "backend.cad_worker", str(folder),
                    cwd=store.ROOT, stdout=asyncio.subprocess.PIPE, stderr=stderr, env=env, start_new_session=True)
    result, error = None, None
    measurements = []
    try:
        async with asyncio.timeout(180):
            while line := await process.stdout.readline():
                if cancel.is_set():
                    raise asyncio.CancelledError()
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item["type"] == "feature":
                    measurements.append({"id": item["data"]["feature"]["id"], "bounds": item["data"]["metrics"]["bounds"]})
                    item["data"]["url"] = f"/api/artifacts/{jid}/{attempt}/{item['data']['file']}"
                    store.event(jid, "feature", item["data"])
                elif item["type"] == "complete":
                    result = item["data"]
                elif item["type"] == "error":
                    error = item["data"]["message"]
            await process.wait()
        if process.returncode or result is None:
            raise RuntimeError((error or "CAD 子进程失败，请查看该任务的 worker.log") + "\n各特征实际包围盒[xmin,ymin,zmin,xmax,ymax,zmax]: " + json.dumps(measurements[-8:], ensure_ascii=False))
        result["artifact_base"] = f"/api/artifacts/{jid}/{attempt}"
        return folder, result
    finally:
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
        stderr.close()


async def run_job(jid, text, direct_design, source):
    info = job(jid)
    pid, base = info["project_id"], info["base_revision"]
    project_label = project(pid)["name"]
    cancel = cancels[jid]
    started = time.monotonic()
    notify = lambda kind, data: store.event(jid, kind, data)
    acquired = False
    try:
        async with queue:
            acquired = True
            if cancel.is_set():
                raise asyncio.CancelledError()
            store.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
            revision = store.revision(base) if base else None
            history = store.query("SELECT role,content FROM messages WHERE project_id=? AND role IN ('user','assistant') ORDER BY id DESC LIMIT 6", (pid,))
            current = json.dumps(revision["design"], ensure_ascii=False) if revision else "无"
            context = "当前设计（唯一真实状态）: " + current + "\n近期对话（仅供理解需求）: " + json.dumps(list(reversed(history)), ensure_ascii=False)
            messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": context + "\n本轮要求: " + text}]
            initial_parameters = None
            initial_dimensions = None
            summary = "内置示例已完成。" if source == "example" else "已按参数重新生成。"
            for attempt in range(3 if direct_design is None else 1):
                response = None
                try:
                    if direct_design is None:
                        output = await inference.generate(messages, cancel, notify)
                        response = output["response"]
                        notify("inference", {k: v for k, v in output.items() if k != "response"})
                        summary = response["summary"]
                        if response["action"] == "clarify":
                            store.message(pid, "assistant", summary)
                            store.execute("UPDATE jobs SET status='clarification' WHERE id=?", (jid,))
                            notify("clarification", {"message": summary})
                            return
                        design = Design.model_validate(response["design"]).model_dump()
                        values = {p["name"]: p["value"] for p in design["parameters"]}
                        if initial_parameters is not None:
                            if design.get("expected_size") != initial_dimensions:
                                raise ValueError("自动修复不得改变目标外形尺寸 expected_size，请修正几何特征。")
                            changes = [name for name, value in initial_parameters.items() if values.get(name) != value]
                            if changes:
                                raise ValueError("自动修复不得改变或删除原方案尺寸参数: " + ", ".join(changes) + "。请修正特征或向用户澄清。")
                        else:
                            initial_parameters = values
                            initial_dimensions = design.get("expected_size")
                    else:
                        design = Design.model_validate(direct_design).model_dump()
                    notify("plan", {"summary": summary, "design": design, "attempt": attempt, "source": source})
                    folder, result = await compile_design(jid, attempt, design, cancel)
                    if cancel.is_set():
                        raise asyncio.CancelledError()
                    rid = store.uid()
                    result["total_seconds"] = round(time.monotonic() - started, 2)
                    result["source"] = source
                    result["attempts"] = attempt + 1
                    if revision:
                        old_params = {p["name"]: p for p in revision["design"]["parameters"]}
                        new_params = {p["name"]: p for p in design["parameters"]}
                        old_features = {f["id"]: f for f in revision["design"]["features"]}
                        new_features = {f["id"]: f for f in design["features"]}
                        result["changes"] = {
                            "parameters": [{"name": key, "label": new_params.get(key, old_params.get(key))["label"], "before": old_params.get(key, {}).get("value"), "after": new_params.get(key, {}).get("value")}
                                           for key in sorted(old_params.keys() | new_params.keys()) if old_params.get(key, {}).get("value") != new_params.get(key, {}).get("value")],
                            "added": [f["name"] for key, f in new_features.items() if key not in old_features],
                            "removed": [f["name"] for key, f in old_features.items() if key not in new_features],
                            "modified": [f["name"] for key, f in new_features.items() if key in old_features and f != old_features[key]],
                        }
                    with store.connection() as db:
                        db.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?,?)", (rid, pid, store.now(), json.dumps(design, ensure_ascii=False), json.dumps(result, ensure_ascii=False), str(folder), base))
                        name = design["name"] if project_label in ("未命名零件", "新建项目") else project_label
                        db.execute("UPDATE projects SET current_revision=?,name=? WHERE id=?", (rid, name, pid))
                        db.execute("UPDATE jobs SET status='completed' WHERE id=?", (jid,))
                    store.message(pid, "assistant", summary + f"\n几何校验通过，完成 {len(design['features'])} 个特征。")
                    notify("completed", {"revision_id": rid, "result": result, "message": "模型已保存"})
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if direct_design is not None or attempt == 2 or isinstance(exc, (FileNotFoundError, TimeoutError, InferenceUnavailable)):
                        raise
                    notify("repair", {"message": str(exc), "attempt": attempt + 1})
                    messages = messages[:2]
                    if response:
                        messages.append({"role": "assistant", "content": json.dumps(response, ensure_ascii=False)})
                    messages.append({"role": "user", "content": "执行错误: " + str(exc) + "\n请修正完整设计，保留用户明确要求的尺寸；若要求矛盾请澄清。"})
    except asyncio.CancelledError:
        store.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (jid,))
        notify("cancelled", {"message": "任务已停止，保留上一成功版本"})
        # A cancelled pipe request must not become the next task's response.
        if source == "llm" and acquired:
            inference.close()
    except Exception as exc:
        store.execute("UPDATE jobs SET status='failed',error=? WHERE id=?", (str(exc), jid))
        store.message(pid, "assistant", "本轮生成未完成：" + str(exc) + "\n已保留上一成功版本。")
        notify("failed", {"message": str(exc)})
    finally:
        cancels.pop(jid, None)
        tasks.pop(jid, None)
