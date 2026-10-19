import { useCallback, useEffect, useRef, useState } from "react";
import {
  Box,
  ChevronRight,
  Plus,
  Layers,
  MessageSquare,
  SlidersHorizontal,
  Send,
  Square,
  Download,
  Check,
  Circle,
  Cpu,
  FileCode2,
  RotateCcw,
  Play,
  Pause,
  ChevronLeft,
  GitBranch,
  X,
  AlertCircle,
  LoaderCircle,
  FolderOpen,
  Braces,
  Cable,
  CircleDot,
  PanelLeftClose,
  PanelLeftOpen,
  List,
  Pencil,
  Trash2,
} from "lucide-react";
import Viewer from "./Viewer";
import type {
  Design,
  Example,
  Health,
  Job,
  JobEvent,
  Parameter,
  Project,
  Step,
} from "./types";

async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch("/api" + path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw Error(
      typeof error.detail === "string"
        ? error.detail
        : JSON.stringify(error.detail),
    );
  }
  return response.json();
}
const terminal = [
  "completed",
  "failed",
  "cancelled",
  "interrupted",
  "clarification",
];
const opLabels: Record<string, string> = {
  box: "基础体",
  cylinder: "圆柱",
  gear: "齿轮",
  extrude: "拉伸",
  revolve: "旋转",
  cut_extrude: "切除",
  hole: "钻孔",
  union: "合并",
  cut: "布尔差",
  intersect: "求交",
  fillet: "圆角",
  chamfer: "倒角",
  linear_pattern: "线性阵列",
  polar_pattern: "圆周阵列",
};
const eventLabels: Record<string, string> = {
  queued: "任务排队",
  model_loading: "加载权重",
  model_ready: "模型就绪",
  model_fallback: "模型回退",
  planning: "规划设计",
  plan: "执行方案",
  feature: "特征完成",
  repair: "修复错误",
  inference: "推理完成",
  completed: "保存完成",
  failed: "生成失败",
  cancelled: "已停止",
  clarification: "等待补充",
};

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]),
    [current, setCurrent] = useState<Project | null>(null),
    [examples, setExamples] = useState<Example[]>([]),
    [health, setHealth] = useState<Health | null>(null);
  const [tab, setTab] = useState<"chat" | "params" | "history">("chat"),
    [input, setInput] = useState(""),
    [error, setError] = useState("");
  const [job, setJob] = useState<Job | null>(null),
    [events, setEvents] = useState<JobEvent[]>([]),
    [liveSteps, setLiveSteps] = useState<Step[]>([]),
    [liveDesign, setLiveDesign] = useState<Design | null>(null);
  const [selected, setSelected] = useState(-1),
    [playing, setPlaying] = useState(false),
    [exportOpen, setExportOpen] = useState(false),
    [examplesOpen, setExamplesOpen] = useState(false),
    [projectsOpen, setProjectsOpen] = useState(false),
    [editingProjectId, setEditingProjectId] = useState<string | null>(null),
    [editingProjectName, setEditingProjectName] = useState(""),
    [deletingProjectId, setDeletingProjectId] = useState<string | null>(null),
    [sidebar, setSidebar] = useState(true),
    [values, setValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const stream = useRef<EventSource | null>(null),
    chatBottom = useRef<HTMLDivElement>(null),
    currentId = useRef<string | null>(null);
  const busy = !!job && !terminal.includes(job.status);
  const revision = current?.revision;
  const steps = liveSteps.length ? liveSteps : revision?.result.steps || [];
  const design = liveDesign || revision?.design;
  const index =
      selected < 0 ? steps.length - 1 : Math.min(selected, steps.length - 1),
    step = steps[index];
  const modelUrl =
    step?.url ||
    (step && revision
      ? `${revision.result.artifact_base}/${step.file}`
      : undefined);
  const refreshList = useCallback(
    async () => {
      const list = await api<Project[]>("/projects");
      setProjects(list);
      return list;
    },
    [],
  );
  const refreshProject = useCallback(
    async (id: string) => {
      const p = await api<Project>(`/projects/${id}`);
      if (currentId.current === id) setCurrent(p);
      await refreshList();
      return p;
    },
    [refreshList],
  );
  const monitor = useCallback(
    (j: Job, pid: string) => {
      stream.current?.close();
      setJob(j);
      setEvents([]);
      setLiveSteps([]);
      setLiveDesign(null);
      setSelected(-1);
      setPlaying(false);
      const es = new EventSource(`/api/jobs/${j.id}/events`);
      stream.current = es;
      es.onmessage = (event) => {
        const e = JSON.parse(event.data) as JobEvent;
        if (currentId.current !== pid) return;
        setEvents((prev) =>
          prev.some((x) => x.id === e.id) ? prev : [...prev, e],
        );
        if (e.type === "plan") {
          setLiveDesign(e.data.design);
          setLiveSteps([]);
          setSelected(-1);
        }
        if (e.type === "feature")
          setLiveSteps((prev) => [
            ...prev.filter((s) => s.index !== e.data.index),
            e.data as Step,
          ]);
        if (terminal.includes(e.type)) {
          es.close();
          setJob({ ...j, status: e.type });
          refreshProject(pid)
            .then(() => {
              setLiveSteps([]);
              setLiveDesign(null);
              setSelected(-1);
            })
            .catch((err) => setError(err.message));
          api<Health>("/health")
            .then(setHealth)
            .catch(() => {});
        }
      };
      es.onerror = () => {
        api<Job>(`/jobs/${j.id}`)
          .then((state) => {
            if (terminal.includes(state.status)) {
              es.close();
              setJob(state);
              refreshProject(pid);
              setLiveSteps([]);
              setLiveDesign(null);
            }
          })
          .catch(() => setError("连接已断开，正在尝试恢复"));
      };
    },
    [refreshProject],
  );
  const openProject = useCallback(
    async (id: string) => {
      stream.current?.close();
      currentId.current = id;
      localStorage.setItem("t2cad-project", id);
      setLiveSteps([]);
      setLiveDesign(null);
      setEvents([]);
      setJob(null);
      setSelected(-1);
      setPlaying(false);
      const p = await refreshProject(id);
      const active = p.jobs.find((j) => !terminal.includes(j.status));
      if (active) monitor(active, id);
    },
    [refreshProject, monitor],
  );
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api<Project[]>("/projects"),
      api<Example[]>("/examples"),
      api<Health>("/health"),
    ])
      .then(([ps, es, h]) => {
        if (cancelled) return;
        setProjects(ps);
        setExamples(es);
        setHealth(h);
        const saved = localStorage.getItem("t2cad-project");
        if (ps.length)
          openProject(ps.find((p) => p.id === saved)?.id || ps[0].id);
      })
      .catch((e) => setError(e.message));
    const timer = setInterval(
      () =>
        api<Health>("/health")
          .then(setHealth)
          .catch(() => {}),
      15000,
    );
    return () => {
      cancelled = true;
      clearInterval(timer);
      stream.current?.close();
    };
  }, [openProject]);
  useEffect(() => {
    setValues(
      Object.fromEntries(
        (revision?.design.parameters || []).map((p) => [
          p.name,
          String(p.value),
        ]),
      ),
    );
  }, [revision?.id]);
  useEffect(() => {
    chatBottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [current?.messages.length, events.length, tab]);
  useEffect(() => {
    if (!playing || !steps.length) return;
    const timer = setInterval(
      () =>
        setSelected((prev) => {
          const next = prev < 0 ? 0 : prev + 1;
          if (next >= steps.length) {
            setPlaying(false);
            return steps.length - 1;
          }
          return next;
        }),
      1200,
    );
    return () => clearInterval(timer);
  }, [playing, steps.length]);
  const newProject = async () => {
    const p = await api<Project>("/projects", "POST", { name: "未命名零件" });
    await openProject(p.id);
    return p.id;
  };
  const submit = async (text = input) => {
    if (!text.trim() || busy || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const pid = current?.id || (await newProject());
      const j = await api<Job>(`/projects/${pid}/messages`, "POST", {
        text,
        base_revision: current?.current_revision || null,
      });
      setInput("");
      setTab("chat");
      await refreshProject(pid);
      monitor(j, pid);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };
  const runExample = async (example: Example) => {
    setSubmitting(true);
    setError("");
    try {
      const pid = await newProject();
      const j = await api<Job>(
        `/projects/${pid}/examples/${example.id}`,
        "POST",
      );
      setExamplesOpen(false);
      await refreshProject(pid);
      monitor(j, pid);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };
  const applyParameters = async () => {
    if (!current || !revision) return;
    setSubmitting(true);
    setError("");
    try {
      const numeric = Object.fromEntries(
        Object.entries(values).map(([k, v]) => {
          if (v.trim() === "" || !Number.isFinite(Number(v)))
            throw Error("请输入有效数值");
          return [k, Number(v)];
        }),
      );
      const j = await api<Job>(`/projects/${current.id}/parameters`, "PATCH", {
        values: numeric,
        base_revision: revision.id,
      });
      await refreshProject(current.id);
      monitor(j, current.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };
  const restore = async (id: string) => {
    if (!current) return;
    try {
      await api(`/projects/${current.id}/restore/${id}`, "POST");
      setSelected(-1);
      await refreshProject(current.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const startRename = (p: Project) => {
    setDeletingProjectId(null);
    setEditingProjectId(p.id);
    setEditingProjectName(p.name);
  };
  const renameProject = async (id: string) => {
    const name = editingProjectName.trim();
    if (!name) {
      setError("项目名称不能为空");
      return;
    }
    try {
      await api<Project>(`/projects/${id}`, "PATCH", { name });
      setEditingProjectId(null);
      await refreshProject(id);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const deleteProject = async (id: string) => {
    try {
      await api(`/projects/${id}`, "DELETE");
      const deletingCurrent = currentId.current === id;
      if (deletingCurrent) {
        stream.current?.close();
        currentId.current = null;
        localStorage.removeItem("t2cad-project");
        setCurrent(null);
        setJob(null);
        setEvents([]);
        setLiveSteps([]);
        setLiveDesign(null);
      }
      setDeletingProjectId(null);
      const remaining = await refreshList();
      if (deletingCurrent && remaining.length) await openProject(remaining[0].id);
      if (!remaining.length) setProjectsOpen(false);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const download = (file: string) => {
    if (!revision) return;
    const a = document.createElement("a");
    a.href = `${revision.result.artifact_base}/${file}`;
    a.download = file;
    a.click();
    setExportOpen(false);
  };
  const activeEvent = events.at(-1);
  const paramsChanged = revision?.design.parameters.some(
    (p) => values[p.name] !== String(p.value),
  );
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-icon">
            <Box size={23} />
          </span>
          <strong>T2CAD</strong>
          <span className="brand-caption">设计工作台</span>
        </div>
        <div className="top-project">
          <span className="top-separator" />
          <FolderOpen size={15} />
          <span>{current?.name || "新建项目"}</span>
          {revision && (
            <span className="version-label">
              v
              {current!.revisions.findIndex((r) => r.id === revision.id) >= 0
                ? current!.revisions.length -
                  current!.revisions.findIndex((r) => r.id === revision.id)
                : 1}
            </span>
          )}
        </div>
        <div className="top-actions">
          <span className="local-badge">
            <i className="dot" />
            本地运行
          </span>
          <button
            className="quiet-button"
            onClick={() => setExamplesOpen(true)}
          >
            <Layers size={15} />
            示例库
          </button>
          <div className="export-wrap">
            <button
              className="primary-button"
              disabled={!revision}
              onClick={() => setExportOpen(!exportOpen)}
            >
              <Download size={15} />
              导出
              <ChevronRight size={13} className="rotate-down" />
            </button>
            {exportOpen && (
              <div className="export-menu">
                {[
                  ["model.step", "STEP · 精确实体"],
                  ["model.FCStd", "FCStd · FreeCAD 原生"],
                  ["model.stl", "STL · 三角网格"],
                  ["model.glb", "GLB · 三维场景"],
                  ["model.py", "Python · 重建脚本"],
                  ["design.json", "JSON · 参数与特征"],
                ].map(([file, label]) => (
                  <button key={file} onClick={() => download(file)}>
                    <Download size={14} />
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </header>
      {error && (
        <div className="error-banner">
          <AlertCircle size={16} />
          <span>{error}</span>
          <button title="关闭错误" onClick={() => setError("")}>
            <X size={16} />
          </button>
        </div>
      )}
      <div className={`workspace ${sidebar ? "" : "collapsed"}`}>
        <aside className="left-panel">
          <div className="panel-heading">
            <span>项目浏览器</span>
            <button
              title="收起侧栏"
              aria-label="收起侧栏"
              onClick={() => setSidebar(false)}
            >
              <PanelLeftClose size={16} />
            </button>
          </div>
          <div className="project-picker">
            <select
              aria-label="选择项目"
              value={current?.id || ""}
              onChange={(e) =>
                openProject(e.target.value).catch((e) => setError(e.message))
              }
            >
              <option value="" disabled>
                选择项目
              </option>
              {projects.map((p) => (
                <option value={p.id} key={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <button
              title="管理项目"
              aria-label="管理项目"
              onClick={() => {
                setEditingProjectId(null);
                setDeletingProjectId(null);
                setProjectsOpen(true);
              }}
            >
              <List size={17} />
            </button>
            <button
              title="新建项目"
              aria-label="新建项目"
              disabled={submitting}
              onClick={() => newProject().catch((e) => setError(e.message))}
            >
              <Plus size={18} />
            </button>
          </div>
          <div className="tree-heading">
            <Layers size={14} />
            <span>特征历史</span>
            <span className="count">{design?.features.length || 0}</span>
          </div>
          <div className="feature-tree">
            {design?.features.map((feature, i) => (
              <button
                className={`feature-row ${index === i ? "selected" : ""}`}
                key={feature.id}
                disabled={i >= steps.length}
                onClick={() => {
                  setSelected(i);
                  setPlaying(false);
                }}
              >
                <span className="tree-line" />
                <span className="feature-icon">
                  {i < steps.length ? (
                    <Check size={13} />
                  ) : (
                    <Circle size={12} />
                  )}
                </span>
                <span className="feature-name">
                  {feature.name}
                  <small>{opLabels[feature.op] || feature.op}</small>
                </span>
                <span className="feature-number">
                  {String(i + 1).padStart(2, "0")}
                </span>
              </button>
            ))}
            {!design && (
              <div className="tree-empty">
                <Layers size={24} />
                <span>暂无特征</span>
              </div>
            )}
          </div>
          <div className="left-bottom">
            <div className="panel-heading">
              <span>模型属性</span>
              <Box size={14} />
            </div>
            <dl>
              <dt>类型</dt>
              <dd>参数化实体</dd>
              <dt>单位</dt>
              <dd>毫米 / mm</dd>
              <dt>体积</dt>
              <dd>
                {step ? (step.metrics.volume / 1000).toFixed(2) + " cm³" : "—"}
              </dd>
              <dt>表面积</dt>
              <dd>
                {step ? (step.metrics.area / 100).toFixed(2) + " cm²" : "—"}
              </dd>
              <dt>有效性</dt>
              <dd className="valid">{step ? "通过" : "—"}</dd>
            </dl>
            <div className="kernel-label">
              <CircleDot size={13} />
              OpenCascade · B-Rep
            </div>
          </div>
        </aside>
        <main className="center-panel">
          <div className="center-toolbar">
            {!sidebar && (
              <button
                title="展开侧栏"
                aria-label="展开侧栏"
                onClick={() => setSidebar(true)}
              >
                <PanelLeftOpen size={17} />
              </button>
            )}
            <div className="center-tab">
              <Box size={15} />
              三维模型
            </div>
            <span className="toolbar-status">
              {busy ? (
                <>
                  <LoaderCircle size={13} className="spin" />
                  {eventLabels[activeEvent?.type || "queued"]}
                </>
              ) : revision ? (
                <>
                  <Check size={13} />
                  已保存
                </>
              ) : (
                "就绪"
              )}
            </span>
          </div>
          <Viewer
            url={modelUrl}
            metrics={step?.metrics}
            title={design?.name || ""}
            busy={busy}
          />
          <div className="timeline">
            <div className="timeline-title">
              <span>建模过程</span>
              <span>
                {steps.length
                  ? `${index + 1} / ${design?.features.length || steps.length}`
                  : "0 / 0"}
              </span>
              <div className="timeline-actions">
                <button
                  title="上一步"
                  aria-label="上一步"
                  disabled={!steps.length || index <= 0}
                  onClick={() => {
                    setPlaying(false);
                    setSelected(Math.max(0, index - 1));
                  }}
                >
                  <ChevronLeft size={17} />
                </button>
                <button
                  title={playing ? "暂停回放" : "播放建模过程"}
                  aria-label={playing ? "暂停回放" : "播放建模过程"}
                  disabled={!steps.length || busy}
                  onClick={() => {
                    if (!playing && index === steps.length - 1) setSelected(0);
                    setPlaying(!playing);
                  }}
                >
                  {playing ? <Pause size={16} /> : <Play size={16} />}
                </button>
                <button
                  title="下一步"
                  aria-label="下一步"
                  disabled={!steps.length || index >= steps.length - 1}
                  onClick={() => {
                    setPlaying(false);
                    setSelected(index + 1);
                  }}
                >
                  <ChevronRight size={17} />
                </button>
              </div>
            </div>
            <input
              aria-label="建模步骤"
              type="range"
              min={0}
              max={Math.max(0, steps.length - 1)}
              value={Math.max(index, 0)}
              disabled={!steps.length}
              onChange={(e) => {
                setSelected(Number(e.target.value));
                setPlaying(false);
              }}
            />
            <div className="timeline-caption">
              <span>{step?.feature.name || "等待建模"}</span>
              <span>{step ? `${step.elapsed.toFixed(2)} s` : "—"}</span>
            </div>
          </div>
        </main>
        <aside className="right-panel">
          <nav className="right-tabs">
            <button
              className={tab === "chat" ? "active" : ""}
              onClick={() => setTab("chat")}
            >
              <MessageSquare size={15} />
              设计对话
            </button>
            <button
              className={tab === "params" ? "active" : ""}
              onClick={() => setTab("params")}
            >
              <SlidersHorizontal size={15} />
              参数
            </button>
            <button
              className={tab === "history" ? "active" : ""}
              onClick={() => setTab("history")}
            >
              <GitBranch size={15} />
              版本
            </button>
          </nav>
          {tab === "chat" && (
            <>
              <div className="conversation">
                <div className="model-heading">
                  <span className="model-avatar">
                    <Cpu size={18} />
                  </span>
                  <div>
                      <strong>
                        {(health?.active_model || health?.model_name)?.includes("Qwen3.8")
                          ? "Qwen3.8 · 27B"
                          : "Qwen3 · 14B 回退"}
                      </strong>
                    <small>
                      GGUF Q4_K_M <i />{" "}
                      {health?.model_loaded
                        ? "GPU 已加载"
                        : health?.model_exists
                          ? "权重已就绪"
                          : "权重未就绪"}
                    </small>
                  </div>
                  <span className="tiny-badge">LOCAL</span>
                </div>
                {!current?.messages.length && (
                  <div className="starter">
                    <h2>开始一个新零件</h2>
                    <div className="starter-examples">
                      {examples.map((e) => (
                        <button key={e.id} onClick={() => setInput(e.prompt)}>
                          <Box size={16} />
                          <span>{e.name}</span>
                          <ChevronRight size={14} />
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {current?.messages.map((message) => (
                  <div className={`message ${message.role}`} key={message.id}>
                    <div className="message-role">
                      {message.role === "user"
                        ? "你"
                        : message.role === "assistant"
                          ? "T2CAD"
                          : "项目记录"}
                      <span>
                        {new Date(message.created).toLocaleTimeString("zh-CN", {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    </div>
                    <div className="message-content">{message.content}</div>
                  </div>
                ))}
                {!!events.length && (
                  <div className="event-log">
                    <div className="event-log-title">
                      <Cable size={13} />
                      <span>执行记录</span>
                      {busy && <LoaderCircle className="spin" size={13} />}
                    </div>
                    {events
                      .filter((e) => !["queued", "inference"].includes(e.type))
                      .map((e) => (
                        <div
                          key={e.id}
                          className={`event-item ${e.type === "failed" || e.type === "repair" ? "warning" : ""}`}
                        >
                          <span className="event-dot" />
                          <div>
                            <strong>
                              {eventLabels[e.type] || e.type}
                              {e.type === "feature"
                                ? ` · ${e.data.feature.name}`
                                : ""}
                            </strong>
                            <p>
                              {e.data.message ||
                                e.data.summary ||
                                (e.type === "model_ready"
                                  ? `加载 ${e.data.load_seconds}s`
                                  : e.type === "feature"
                                    ? `${e.data.metrics.size.map((n: number) => n.toFixed(1)).join(" × ")} mm`
                                    : "")}
                            </p>
                          </div>
                        </div>
                      ))}
                  </div>
                )}
                <div ref={chatBottom} />
              </div>
              <div className="composer">
                <textarea
                  aria-label="设计需求"
                  placeholder="描述零件、尺寸，或修改当前设计…"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit();
                  }}
                />
                <div className="composer-bottom">
                  <span>
                    <i className="dot" />
                    本地推理
                  </span>
                  {busy ? (
                    <button
                      className="stop-button"
                      onClick={() =>
                        api(`/jobs/${job!.id}/cancel`, "POST").catch((e) =>
                          setError(e.message),
                        )
                      }
                    >
                      <Square size={13} />
                      停止
                    </button>
                  ) : (
                    <button
                      className="send-button"
                      title="发送需求"
                      aria-label="发送需求"
                      disabled={!input.trim() || submitting}
                      onClick={() => submit()}
                    >
                      {submitting ? (
                        <LoaderCircle size={17} className="spin" />
                      ) : (
                        <Send size={17} />
                      )}
                    </button>
                  )}
                </div>
              </div>
            </>
          )}
          {tab === "params" && (
            <div className="parameter-panel">
              <div className="section-label">
                设计参数 <span>{revision?.design.parameters.length || 0}</span>
              </div>
              {revision?.design.parameters.map((p: Parameter) => (
                <label className="parameter-field" key={p.name}>
                  <span>
                    {p.label}
                    <small>{p.name}</small>
                  </span>
                  <div>
                    <input
                      aria-label={p.label}
                      type="number"
                      step="any"
                      disabled={busy}
                      value={values[p.name] ?? p.value}
                      onChange={(e) =>
                        setValues({ ...values, [p.name]: e.target.value })
                      }
                    />
                    <span>{p.unit}</span>
                  </div>
                </label>
              ))}
              {!revision && (
                <div className="panel-empty">
                  <SlidersHorizontal size={28} />
                  暂无设计参数
                </div>
              )}
              <button
                className="primary-button full-width"
                disabled={!paramsChanged || busy || submitting}
                onClick={applyParameters}
              >
                <RotateCcw size={15} />
                重新计算
              </button>
              {step && (
                <>
                  <div className="section-label spaced">
                    当前特征 <span>{step.feature.id}</span>
                  </div>
                  <pre className="args-view">
                    {JSON.stringify(step.feature.args, null, 2)}
                  </pre>
                  <div className="section-label spaced">实测包围尺寸</div>
                  <dl className="measurement-list">
                    {["X", "Y", "Z"].map((a, i) => (
                      <div key={a}>
                        <dt>{a}</dt>
                        <dd>{step.metrics.size[i].toFixed(3)} mm</dd>
                      </div>
                    ))}
                  </dl>
                </>
              )}
            </div>
          )}
          {tab === "history" && (
            <div className="history-panel">
              {revision?.result.changes && (
                <div className="revision-diff">
                  <div className="section-label">相对父版本的变化</div>
                  {revision.result.changes.parameters.map((change) => (
                    <div key={change.name}>
                      <span>{change.label}</span>
                      <code>
                        {change.before ?? "新增"} → {change.after ?? "移除"}
                      </code>
                    </div>
                  ))}
                  {(
                    [
                      ["added", "新增"],
                      ["removed", "移除"],
                      ["modified", "修改"],
                    ] as const
                  ).map(([key, label]) =>
                    revision.result.changes![key].map((name) => (
                      <div key={key + name}>
                        <span>{label}特征</span>
                        <span>{name}</span>
                      </div>
                    )),
                  )}
                </div>
              )}
              <div className="section-label">
                保存的版本 <span>{current?.revisions.length || 0}</span>
              </div>
              {current?.revisions.map((r, i) => (
                <div
                  key={r.id}
                  className={`revision-item ${r.id === revision?.id ? "current" : ""}`}
                >
                  <div className="revision-icon">
                    <GitBranch size={17} />
                  </div>
                  <div>
                    <strong>
                      版本 {current.revisions.length - i}
                      {r.id === revision?.id && <span>当前</span>}
                    </strong>
                    <small>{new Date(r.created).toLocaleString("zh-CN")}</small>
                    <code>{r.id.slice(0, 8)}</code>
                  </div>
                  <button
                    title="切换到此版本"
                    aria-label={`切换到版本${current.revisions.length - i}`}
                    disabled={busy || r.id === revision?.id}
                    onClick={() => restore(r.id)}
                  >
                    <RotateCcw size={15} />
                  </button>
                </div>
              ))}
              {!current?.revisions.length && (
                <div className="panel-empty">
                  <GitBranch size={28} />
                  暂无保存版本
                </div>
              )}
            </div>
          )}
        </aside>
      </div>
      <footer className="statusbar">
        <span>
          <i className="dot" />
          T2CAD <b>1.0</b>
        </span>
        <span>
          {busy
            ? "正在生成"
            : revision?.result.source === "example"
              ? "内置示例"
              : revision
                ? "参数化设计"
                : "就绪"}
        </span>
        <span className="status-right">
          <Cpu size={12} />
          {health ? `可用内存 ${health.ram_available_gb} GB` : "连接后端…"}
          <span className="status-divider" />
          <Braces size={12} />
          Python / CadQuery
        </span>
      </footer>
      {examplesOpen && (
        <div className="modal-backdrop" onClick={() => setExamplesOpen(false)}>
          <section
            className="example-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <h2>零件示例库</h2>
                <span>预设参数化案例</span>
              </div>
              <button title="关闭示例库" onClick={() => setExamplesOpen(false)}>
                <X size={20} />
              </button>
            </div>
            {examples.map((e, i) => (
              <div className="example-item" key={e.id}>
                <span className="example-number">0{i + 1}</span>
                <div>
                  <h3>{e.name}</h3>
                  <p>{e.features} 个特征 · mm</p>
                </div>
                <button
                  className="quiet-button"
                  disabled={busy || submitting}
                  onClick={() => runExample(e)}
                >
                  <Play size={14} />
                  运行示例
                </button>
                <button
                  title="作为大模型需求"
                  aria-label={`用大模型生成${e.name}`}
                  onClick={() => {
                    setInput(e.prompt);
                    setExamplesOpen(false);
                    setTab("chat");
                  }}
                >
                  <MessageSquare size={17} />
                </button>
              </div>
            ))}
          </section>
        </div>
      )}
      {projectsOpen && (
        <div className="modal-backdrop" onClick={() => setProjectsOpen(false)}>
          <section className="project-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h2>项目管理</h2>
                <span>重命名或删除本地零件项目</span>
              </div>
              <button title="关闭项目管理" onClick={() => setProjectsOpen(false)}>
                <X size={20} />
              </button>
            </div>
            <div className="project-manager-list">
              {projects.map((p) => (
                <div className={`project-manager-item ${p.id === current?.id ? "current" : ""}`} key={p.id}>
                  {editingProjectId === p.id ? (
                    <input
                      autoFocus
                      aria-label="项目名称"
                      value={editingProjectName}
                      onChange={(e) => setEditingProjectName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") renameProject(p.id);
                        if (e.key === "Escape") setEditingProjectId(null);
                      }}
                    />
                  ) : (
                    <button className="project-manager-name" onClick={() => { setProjectsOpen(false); openProject(p.id).catch((e) => setError(e.message)); }}>
                      <FolderOpen size={16} />
                      <span>{p.name}</span>
                      {p.id === current?.id && <small>当前</small>}
                    </button>
                  )}
                  <div className="project-manager-actions">
                    {editingProjectId === p.id ? (
                      <>
                        <button title="保存名称" aria-label="保存名称" onClick={() => renameProject(p.id)}><Check size={15} /></button>
                        <button title="取消重命名" aria-label="取消重命名" onClick={() => setEditingProjectId(null)}><X size={15} /></button>
                      </>
                    ) : deletingProjectId === p.id ? (
                      <>
                        <span className="delete-prompt">确认删除？</span>
                        <button className="danger-button" title="确认删除项目" aria-label="确认删除项目" onClick={() => deleteProject(p.id)}><Check size={15} /></button>
                        <button title="取消删除" aria-label="取消删除" onClick={() => setDeletingProjectId(null)}><X size={15} /></button>
                      </>
                    ) : (
                      <>
                        <button title="重命名项目" aria-label={`重命名${p.name}`} disabled={p.id === current?.id && busy} onClick={() => startRename(p)}><Pencil size={15} /></button>
                        <button title="删除项目" aria-label={`删除${p.name}`} disabled={p.id === current?.id && busy} onClick={() => { setEditingProjectId(null); setDeletingProjectId(p.id); }}><Trash2 size={15} /></button>
                      </>
                    )}
                  </div>
                </div>
              ))}
              {!projects.length && <div className="panel-empty"><FolderOpen size={28} />暂无项目</div>}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
