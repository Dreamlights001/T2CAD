import time
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from backend import store
from backend.main import app
from backend.inference import inference, InferenceUnavailable
from backend.examples import EXAMPLES, f
from backend.schema import Design


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    with TestClient(app) as client:
        yield client


def wait(client, jid):
    deadline = time.monotonic() + 190
    while time.monotonic() < deadline:
        row = client.get(f"/api/jobs/{jid}").json()
        if row["status"] not in ("queued", "running"):
            return row
        time.sleep(0.1)
    pytest.fail("job timeout")


def test_version_parameters_exports_and_restore(client):
    pid = client.post("/api/projects", json={"name": "测试"}).json()["id"]
    jid = client.post(f"/api/projects/{pid}/examples/plate").json()["id"]
    assert wait(client, jid)["status"] == "completed"
    project = client.get(f"/api/projects/{pid}").json()
    first = project["current_revision"]
    base = project["revision"]["result"]["artifact_base"]
    for file in ["model.step", "model.stl", "model.glb", "model.py", "design.json"]:
        response = client.get(base + "/" + file)
        assert response.status_code == 200 and len(response.content) > 100
    assert client.get(base + "/worker.log").status_code == 404
    second_job = client.patch(f"/api/projects/{pid}/parameters", json={"values": {"hole_d": 8}, "base_revision": first}).json()["id"]
    assert wait(client, second_job)["status"] == "completed"
    second = client.get(f"/api/projects/{pid}").json()["current_revision"]
    assert second != first
    changes = client.get(f"/api/projects/{pid}").json()["revision"]["result"]["changes"]
    assert changes["parameters"] == [{"name": "hole_d", "label": "孔径", "before": 6, "after": 8}]
    assert client.patch(f"/api/projects/{pid}/parameters", json={"values": {"hole_d": 9}, "base_revision": first}).status_code == 409
    bad_job = client.patch(f"/api/projects/{pid}/parameters", json={"values": {"hole_d": -2}, "base_revision": second}).json()["id"]
    assert wait(client, bad_job)["status"] == "failed"
    assert client.get(f"/api/projects/{pid}").json()["current_revision"] == second
    assert client.post(f"/api/projects/{pid}/restore/{first}").status_code == 200
    assert client.get(f"/api/projects/{pid}").json()["current_revision"] == first
    events = client.get(f"/api/jobs/{jid}").json()["events"]
    cursor = events[-2]["id"]
    response = client.get(f"/api/jobs/{jid}/events?after={cursor}")
    assert '"type": "completed"' in response.text
    assert '"type": "feature"' not in response.text


def test_restart_marks_unfinished_jobs(client):
    pid = client.post("/api/projects", json={}).json()["id"]
    store.execute("INSERT INTO jobs VALUES(?,?,?,?,?,NULL)", ("restart", pid, "running", store.now(), None))
    store.init()
    assert client.get("/api/jobs/restart").json()["status"] == "interrupted"


def test_cancel_preserves_version(client):
    pid = client.post("/api/projects", json={}).json()["id"]
    jid = client.post(f"/api/projects/{pid}/examples/flange").json()["id"]
    client.post(f"/api/jobs/{jid}/cancel")
    assert wait(client, jid)["status"] == "cancelled"
    assert client.get(f"/api/projects/{pid}").json()["current_revision"] is None


def test_execution_feedback_repairs_geometry(client, monkeypatch):
    calls = []

    async def generate(messages, cancel, notify):
        calls.append(deepcopy(messages))
        design = deepcopy(EXAMPLES["plate"])
        design["expected_size"] = ["null", None, 8] if len(calls) == 1 else [None, None, 8]
        if len(calls) == 1:
            design["features"].append(f("bad_radius", "测试圆角错误", "fillet", radius=1000))
        return {"response": {"action": "build", "summary": "反馈修复测试", "design": design}, "seconds": 0, "usage": {}}

    monkeypatch.setattr(inference, "generate", generate)
    pid = client.post("/api/projects", json={}).json()["id"]
    jid = client.post(f"/api/projects/{pid}/messages", json={"text": "生成安装板"}).json()["id"]
    result = wait(client, jid)
    assert result["status"] == "completed"
    assert len(calls) == 2 and "bad_radius" in calls[1][-1]["content"]
    assert any(e["type"] == "repair" for e in result["events"])
    errors = [e["data"]["message"] for e in result["events"] if e["type"] == "repair"]
    assert all("Traceback" not in error for error in errors)


@pytest.mark.parametrize("unknown", [None, "null", " NULL "])
def test_unknown_target_size_is_normalized(unknown):
    design = deepcopy(EXAMPLES["plate"])
    design["expected_size"] = [unknown, unknown, 8]
    assert Design.model_validate(design).expected_size == [None, None, 8]


@pytest.mark.parametrize("target", ["missing", "sqrt(8)", "", "1/0", -8])
def test_invalid_target_size_is_rejected_before_geometry(target):
    design = deepcopy(EXAMPLES["plate"])
    design["expected_size"] = [None, None, target]
    with pytest.raises(ValueError, match="expected_size"):
        Design.model_validate(design)


def test_gear_addendum_circle_is_not_locked_as_a_bounding_box(client, monkeypatch):
    calls = 0

    async def generate(messages, cancel, notify):
        nonlocal calls
        calls += 1
        design = {"name": "17齿齿轮", "parameters": [],
                  "features": [f("gear", "直齿轮", "gear", module=2, teeth=17, height=20)],
                  "expected_size": [38, 38, 20] if calls == 1 else [None, None, 20]}
        return {"response": {"action": "build", "summary": "齿顶圆尺寸回归", "design": design}}

    monkeypatch.setattr(inference, "generate", generate)
    pid = client.post("/api/projects", json={}).json()["id"]
    jid = client.post(f"/api/projects/{pid}/messages", json={"text": "模数2、17齿、厚20"}).json()["id"]
    result = wait(client, jid)
    assert result["status"] == "completed", result.get("error")
    assert calls == 2
    assert any("齿顶圆直径" in e["data"].get("message", "") for e in result["events"] if e["type"] == "repair")


@pytest.mark.parametrize("teeth,size,valid", [(17, [38, None, 20], False), (18, [40, None, 20], True),
                                             (18, [None, 40, 20], False), (20, [44, 44, 20], True)])
def test_gear_bounding_box_precheck_respects_tooth_symmetry(teeth, size, valid):
    design = {"name": "轴向包围盒", "parameters": [], "expected_size": size,
              "features": [f("gear", "直齿轮", "gear", module=2, teeth=teeth, height=20)]}
    if valid:
        assert Design.model_validate(design).expected_size == size
    else:
        with pytest.raises(ValueError, match="齿顶圆直径"):
            Design.model_validate(design)


def test_gear_with_quoted_null_dimensions_completes_without_repair(client, monkeypatch):
    design = {
        "name": "圆柱直齿轮", "expected_size": ["null", "null", "height"],
        "parameters": [{"name": name, "label": label, "value": value, "unit": unit} for name, label, value, unit in
                       [("module", "模数", 2, "mm"), ("teeth", "齿数", 17, "count"), ("height", "厚度", 20, "mm")]],
        "features": [f("gear", "圆柱直齿轮", "gear", module="module", teeth="teeth", height="height")],
    }

    async def generate(messages, cancel, notify):
        return {"response": {"action": "build", "summary": "齿轮空尺寸回归", "design": design}}

    monkeypatch.setattr(inference, "generate", generate)
    pid = client.post("/api/projects", json={}).json()["id"]
    jid = client.post(f"/api/projects/{pid}/messages", json={"text": "模数2、17齿、厚20，无孔"}).json()["id"]
    result = wait(client, jid)
    assert result["status"] == "completed", result.get("error")
    assert not any(e["type"] == "repair" for e in result["events"])
    revision = client.get(f"/api/projects/{pid}").json()["revision"]
    assert revision["design"]["expected_size"] == [None, None, "height"]
    assert revision["result"]["metrics"]["size"][2] == pytest.approx(20, abs=1e-5)


def test_helical_gear_exports_and_parametric_helix_change(client, monkeypatch):
    design = {
        "name": "带孔斜齿轮", "expected_size": [None, None, "h"],
        "parameters": [{"name": name, "label": name, "value": value, "unit": unit} for name, value, unit in
                       [("m", 2, "mm"), ("z", 17, "count"), ("h", 20, "mm"), ("alpha", 20, "deg"), ("beta", 15, "deg"), ("bore", 12, "mm")]],
        "features": [f("gear", "斜齿轮", "gear", module="m", teeth="z", height="h", pressure_angle="alpha", helix_angle="beta", module_system="normal"),
                     f("bore", "中心孔", "hole", diameter="bore")],
    }

    async def generate(messages, cancel, notify):
        return {"response": {"action": "build", "summary": "法向制斜齿轮", "design": design}}

    monkeypatch.setattr(inference, "generate", generate)
    pid = client.post("/api/projects", json={}).json()["id"]
    jid = client.post(f"/api/projects/{pid}/messages", json={"text": "模数2，17齿，厚20，alpha20，beta15，孔12"}).json()["id"]
    assert wait(client, jid)["status"] == "completed"
    revision = client.get(f"/api/projects/{pid}").json()["revision"]
    assert revision["result"]["metrics"]["gear"]["helix_angle"] == 15
    assert revision["result"]["step_readback"] and revision["result"]["mesh"]["watertight"]
    for ext in ("step", "stl", "glb", "py"):
        response = client.get(revision["result"]["artifact_base"]+"/model."+ext)
        assert response.status_code == 200 and len(response.content) > 100
    jid = client.patch(f"/api/projects/{pid}/parameters", json={"values": {"beta": -15}, "base_revision": revision["id"]}).json()["id"]
    assert wait(client, jid)["status"] == "completed"
    changed = client.get(f"/api/projects/{pid}").json()["revision"]
    assert changed["result"]["metrics"]["gear"]["hand"] == "left"
    assert changed["result"]["metrics"]["gear"]["helix_angle"] == -15


def test_repair_cannot_remove_known_target_dimensions(client, monkeypatch):
    calls = 0

    async def generate(messages, cancel, notify):
        nonlocal calls
        calls += 1
        design = deepcopy(EXAMPLES["plate"])
        design["expected_size"] = [100, 60, 8] if calls == 1 else ["null", "null", 8]
        if calls == 1:
            design["features"].append(f("bad", "错误圆角", "fillet", radius=1000))
        return {"response": {"action": "build", "summary": "尺寸保护回归", "design": design}}

    monkeypatch.setattr(inference, "generate", generate)
    pid = client.post("/api/projects", json={}).json()["id"]
    jid = client.post(f"/api/projects/{pid}/messages", json={"text": "100×60×8安装板"}).json()["id"]
    result = wait(client, jid)
    assert result["status"] == "failed" and "expected_size" in result["error"]


def test_clarification_saves_no_geometry(client, monkeypatch):
    async def generate(messages, cancel, notify):
        return {"response": {"action": "clarify", "summary": "请提供内径和外径", "design": None}}
    monkeypatch.setattr(inference, "generate", generate)
    pid = client.post("/api/projects", json={}).json()["id"]
    jid = client.post(f"/api/projects/{pid}/messages", json={"text": "生成轴套"}).json()["id"]
    assert wait(client, jid)["status"] == "clarification"
    assert client.get(f"/api/projects/{pid}").json()["current_revision"] is None


def test_missing_inference_dependency_is_not_retried(client, monkeypatch):
    calls = 0

    async def generate(messages, cancel, notify):
        nonlocal calls
        calls += 1
        raise InferenceUnavailable("未安装 llama-cpp-python")

    monkeypatch.setattr(inference, "generate", generate)
    pid = client.post("/api/projects", json={}).json()["id"]
    jid = client.post(f"/api/projects/{pid}/messages", json={"text": "生成安装板"}).json()["id"]
    result = wait(client, jid)
    assert result["status"] == "failed" and calls == 1
    assert not any(e["type"] == "repair" for e in result["events"])


def test_repair_cannot_silently_change_parameters(client, monkeypatch):
    calls = 0

    async def generate(messages, cancel, notify):
        nonlocal calls
        calls += 1
        design = deepcopy(EXAMPLES["plate"])
        if calls == 1:
            design["features"].append(f("bad_radius", "失败特征", "fillet", radius=1000))
        else:
            design["parameters"][0]["value"] = 90
        return {"response": {"action": "build", "summary": "错误修复", "design": design}}

    monkeypatch.setattr(inference, "generate", generate)
    pid = client.post("/api/projects", json={}).json()["id"]
    jid = client.post(f"/api/projects/{pid}/messages", json={"text": "长度必须100毫米"}).json()["id"]
    result = wait(client, jid)
    assert result["status"] == "failed" and "不得改变" in result["error"]
    assert client.get(f"/api/projects/{pid}").json()["current_revision"] is None


def test_project_can_be_renamed_and_name_survives_new_revision(client):
    pid = client.post("/api/projects", json={"name": "初始名称"}).json()["id"]
    renamed = client.patch(f"/api/projects/{pid}", json={"name": "齿轮样件"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "齿轮样件"
    jid = client.post(f"/api/projects/{pid}/examples/plate").json()["id"]
    assert wait(client, jid)["status"] == "completed"
    assert client.get(f"/api/projects/{pid}").json()["name"] == "齿轮样件"
    assert client.patch(f"/api/projects/{pid}", json={"name": "  "}).status_code == 422


def test_project_rename_is_rejected_while_generating(client):
    pid = client.post("/api/projects", json={}).json()["id"]
    jid = client.post(f"/api/projects/{pid}/examples/plate").json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"name": "处理中"}).status_code == 409
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 200
    assert wait(client, jid)["status"] == "cancelled"


def test_project_delete_cleans_records_and_artifacts(client):
    pid = client.post("/api/projects", json={"name": "待删除"}).json()["id"]
    jid = client.post(f"/api/projects/{pid}/examples/plate").json()["id"]
    assert wait(client, jid)["status"] == "completed"
    revision = client.get(f"/api/projects/{pid}").json()["revision"]
    folder = revision["folder"]
    assert client.delete(f"/api/projects/{pid}").json() == {"id": pid, "deleted": True}
    assert client.get(f"/api/projects/{pid}").status_code == 404
    assert client.get(f"/api/jobs/{jid}").status_code == 404
    assert not __import__("pathlib").Path(folder).exists()


def test_project_delete_is_rejected_while_generating(client):
    pid = client.post("/api/projects", json={}).json()["id"]
    jid = client.post(f"/api/projects/{pid}/examples/plate").json()["id"]
    assert client.delete(f"/api/projects/{pid}").status_code == 409
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 200
    assert wait(client, jid)["status"] == "cancelled"
