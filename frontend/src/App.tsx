import {
  AlertCircle,
  ArrowDownToLine,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  ImagePlus,
  Loader2,
  MonitorCheck,
  Play,
  RefreshCw,
  Sparkles,
  UploadCloud,
  WandSparkles,
  X,
} from "lucide-react";
import { ChangeEvent, DragEvent, useCallback, useEffect, useMemo, useState } from "react";

type UploadSlot = "model" | "dress" | "face";
type TaskStatus = "pending" | "processing" | "completed" | "failed";

type Task = {
  task_id: string;
  name: string;
  status: TaskStatus;
  progress: number;
  scene: string;
  resolution: string;
  face_swap: boolean;
  pose?: string;
  preserve_face?: boolean;
  generation_mode?: "stable" | "creative";
  output_files: Record<string, boolean>;
  error_message: string;
  created_at: string;
  completed_at: string;
  steps: Record<string, string>;
};

type UploadState = {
  fileId: string | null;
  previewUrl: string | null;
  filename: string | null;
  uploading: boolean;
};

const emptyUpload: UploadState = {
  fileId: null,
  previewUrl: null,
  filename: null,
  uploading: false,
};

const scenes = [
  { value: "海边", label: "海边日落", tone: "浪漫光影" },
  { value: "教堂", label: "教堂婚礼", tone: "庄重仪式" },
  { value: "花园", label: "欧式花园", tone: "柔和自然" },
  { value: "中式庭院", label: "中式庭院", tone: "东方雅致" },
  { value: "城堡", label: "欧式城堡", tone: "奢华大片" },
  { value: "森林", label: "森林秘境", tone: "清透仙气" },
];

const poses = [
  { value: "保持原姿势", label: "保持原姿势", tone: "保脸更稳" },
  { value: "正面站姿，双臂自然下垂", label: "正面站姿", tone: "商品展示" },
  { value: "微侧身站姿，一只手轻扶裙摆", label: "手扶裙摆", tone: "婚纱氛围" },
  { value: "轻微行走感，裙摆自然展开", label: "行走感", tone: "动态大片" },
  { value: "回眸微笑，身体轻微侧转", label: "回眸", tone: "情绪表达" },
  { value: "坐姿，裙摆自然铺开", label: "坐姿", tone: "画面丰富" },
];

const slotCopy: Record<UploadSlot, { title: string; subtitle: string; required: boolean }> = {
  model: {
    title: "模特原图",
    subtitle: "建议使用正面全身照，光线干净",
    required: true,
  },
  dress: {
    title: "婚纱图片",
    subtitle: "单件服装图效果更稳定",
    required: true,
  },
  face: {
    title: "客人面部照",
    subtitle: "换脸功能后续开启，当前可先留空",
    required: false,
  },
};

const statusCopy: Record<TaskStatus, string> = {
  pending: "等待中",
  processing: "生成中",
  completed: "已完成",
  failed: "失败",
};

async function readApiJson<T>(response: Response, fallbackMessage: string): Promise<T> {
  const text = await response.text();
  let data: unknown = {};

  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      throw new Error(response.ok ? `${fallbackMessage}：后端返回格式错误` : text);
    }
  }

  if (!response.ok) {
    const detail =
      typeof data === "object" && data && "detail" in data
        ? String((data as { detail?: unknown }).detail)
        : "";
    throw new Error(detail || fallbackMessage);
  }

  return data as T;
}

const api = {
  async health() {
    const response = await fetch("/api/health");
    return readApiJson(response, "后端连接失败");
  },
  async upload(file: File) {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch("/api/upload", { method: "POST", body: form });
    const data = await readApiJson<{ file_id?: string; file_path?: string }>(response, "上传失败");
    return data.file_id || data.file_path;
  },
  async createTask(payload: {
    model_file: string;
    dress_file: string;
    face_file?: string | null;
    scene: string;
    resolution: string;
    face_swap: boolean;
    pose: string;
    preserve_face: boolean;
    generation_mode: "stable" | "creative";
  }) {
    const response = await fetch("/api/create-task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await readApiJson<{ task_id: string }>(response, "创建任务失败");
    return data.task_id as string;
  },
  async tasks() {
    const response = await fetch("/api/tasks?page=1&page_size=50");
    const data = await readApiJson<{ tasks: Task[] }>(response, "任务列表获取失败");
    return data.tasks as Task[];
  },
};

function StatusIcon({ status }: { status: TaskStatus }) {
  if (status === "completed") return <CheckCircle2 size={16} />;
  if (status === "failed") return <AlertCircle size={16} />;
  if (status === "processing") return <Loader2 size={16} className="spin" />;
  return <CircleDashed size={16} />;
}

export function App() {
  const [uploads, setUploads] = useState<Record<UploadSlot, UploadState>>({
    model: emptyUpload,
    dress: emptyUpload,
    face: emptyUpload,
  });
  const [scene, setScene] = useState("海边");
  const [pose, setPose] = useState("保持原姿势");
  const [customPose, setCustomPose] = useState("");
  const [preserveFace, setPreserveFace] = useState(true);
  const [generationMode, setGenerationMode] = useState<"stable" | "creative">("stable");
  const [resolution, setResolution] = useState("1k");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [health, setHealth] = useState<"checking" | "ok" | "down">("checking");
  const [toast, setToast] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const selectedScene = useMemo(
    () => scenes.find((item) => item.value === scene) || scenes[0],
    [scene],
  );
  const posePrompt = customPose.trim() || pose;

  const fetchTasks = useCallback(async () => {
    try {
      const nextTasks = await api.tasks();
      setTasks(nextTasks);
      setSelectedTask((current) =>
        current ? nextTasks.find((task) => task.task_id === current.task_id) || current : current,
      );
    } catch (error) {
      console.error(error);
    }
  }, []);

  useEffect(() => {
    api
      .health()
      .then(() => setHealth("ok"))
      .catch(() => setHealth("down"));
    fetchTasks();
    const timer = window.setInterval(fetchTasks, 3000);
    return () => window.clearInterval(timer);
  }, [fetchTasks]);

  async function handleUpload(slot: UploadSlot, file: File) {
    if (!file.type.startsWith("image/")) {
      setToast("请选择图片文件");
      return;
    }

    const previewUrl = URL.createObjectURL(file);
    setUploads((current) => ({
      ...current,
      [slot]: { fileId: null, previewUrl, filename: file.name, uploading: true },
    }));

    try {
      const fileId = await api.upload(file);
      setUploads((current) => ({
        ...current,
        [slot]: { fileId, previewUrl, filename: file.name, uploading: false },
      }));
    } catch (error) {
      URL.revokeObjectURL(previewUrl);
      setUploads((current) => ({ ...current, [slot]: emptyUpload }));
      setToast(error instanceof Error ? error.message : "上传失败");
    }
  }

  async function createTask() {
    const modelFile = uploads.model.fileId;
    const dressFile = uploads.dress.fileId;
    if (!modelFile || !dressFile) {
      setToast("请先上传模特原图和婚纱图片");
      return;
    }

    setCreating(true);
    try {
      await api.createTask({
        model_file: modelFile,
        dress_file: dressFile,
        face_file: uploads.face.fileId,
        scene,
        resolution,
        face_swap: false,
        pose: posePrompt,
        preserve_face: preserveFace,
        generation_mode: generationMode,
      });
      setToast("任务已提交，正在生成");
      await fetchTasks();
    } catch (error) {
      setToast(error instanceof Error ? error.message : "创建任务失败");
    } finally {
      setCreating(false);
    }
  }

  const completedCount = tasks.filter((task) => task.status === "completed").length;
  const activeCount = tasks.filter((task) => ["pending", "processing"].includes(task.status)).length;

  return (
    <main className="studio-shell">
      <section className="hero-panel">
        <div className="hero-copy">
          <div className="eyebrow">
            <Sparkles size={16} />
            婚纱影像 AI 创作台
          </div>
          <h1>把一张模特图，变成可交付的婚纱大片。</h1>
          <p>
            上传模特与婚纱素材，选择拍摄场景，系统自动完成试衣、场景生成与结果归档。
          </p>
          <div className="hero-actions">
            <button className="primary-action" onClick={createTask} disabled={creating}>
              {creating ? <Loader2 size={18} className="spin" /> : <Play size={18} />}
              开始生成
            </button>
            <button className="ghost-action" onClick={fetchTasks}>
              <RefreshCw size={17} />
              刷新任务
            </button>
          </div>
        </div>

        <div className="process-rail" aria-label="生成流程">
          {["素材", "试衣", "场景", "交付"].map((label, index) => (
            <div className="rail-step" key={label}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{label}</strong>
              {index < 3 && <ChevronRight size={18} />}
            </div>
          ))}
        </div>
      </section>

      <section className="status-row">
        <MetricCard label="后端状态" value={health === "ok" ? "已连接" : health === "down" ? "未连接" : "检测中"} tone={health} />
        <MetricCard label="任务总数" value={String(tasks.length)} tone="neutral" />
        <MetricCard label="进行中" value={String(activeCount)} tone="processing" />
        <MetricCard label="已交付" value={String(completedCount)} tone="completed" />
      </section>

      <section className="workspace-grid">
        <div className="panel upload-panel">
          <div className="section-head">
            <div>
              <span className="section-kicker">素材</span>
              <h2>上传创作素材</h2>
            </div>
            <UploadCloud size={22} />
          </div>
          <div className="upload-stack">
            {(Object.keys(slotCopy) as UploadSlot[]).map((slot) => (
              <UploadCard
                key={slot}
                slot={slot}
                state={uploads[slot]}
                onFile={handleUpload}
              />
            ))}
          </div>
        </div>

        <div className="panel settings-panel">
          <div className="section-head">
            <div>
              <span className="section-kicker">参数</span>
              <h2>生成设置</h2>
            </div>
            <WandSparkles size={22} />
          </div>

          <div className="setting-block">
            <label>拍摄场景</label>
            <div className="scene-grid">
              {scenes.map((item) => (
                <button
                  className={item.value === scene ? "scene-card active" : "scene-card"}
                  key={item.value}
                  onClick={() => setScene(item.value)}
                >
                  <strong>{item.label}</strong>
                  <span>{item.tone}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="setting-block pose-block">
            <label>动作 / 姿势</label>
            <div className="scene-grid pose-grid">
              {poses.map((item) => (
                <button
                  className={item.value === pose && !customPose.trim() ? "scene-card active" : "scene-card"}
                  key={item.value}
                  onClick={() => {
                    setPose(item.value);
                    setCustomPose("");
                  }}
                >
                  <strong>{item.label}</strong>
                  <span>{item.tone}</span>
                </button>
              ))}
            </div>
            <input
              className="pose-input"
              value={customPose}
              onChange={(event) => setCustomPose(event.target.value)}
              placeholder="也可以自定义动作，例如：双手捧花，微侧身，看向镜头"
            />
          </div>

          <div className="setting-line">
            <div>
              <label>输出规格</label>
              <p>{resolution === "1k" ? "适合快速预览与老板演示" : "适合更高清的交付图"}</p>
            </div>
            <div className="segmented">
              {["1k", "2k"].map((item) => (
                <button
                  key={item}
                  className={resolution === item ? "active" : ""}
                  onClick={() => setResolution(item)}
                >
                  {item.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <div className="setting-line">
            <div>
              <label>保脸优先</label>
              <p>尽量保留原模特五官、脸型、发型和表情，减少场景生成改脸。</p>
            </div>
            <button
              className={preserveFace ? "switch-button active" : "switch-button"}
              onClick={() => setPreserveFace((value) => !value)}
              type="button"
            >
              {preserveFace ? "已开启" : "已关闭"}
            </button>
          </div>

          <div className="setting-line muted">
            <div>
              <label>生成模式</label>
              <p>
                {generationMode === "stable"
                  ? "稳定模式会锁定人物和婚纱，只生成背景并合成，适合老板演示。"
                  : "自由模式会整图重绘，动作更自由，但脸和婚纱更容易变化。"}
              </p>
            </div>
            <div className="segmented mode-segmented">
              <button
                className={generationMode === "stable" ? "active" : ""}
                onClick={() => setGenerationMode("stable")}
                type="button"
              >
                稳定
              </button>
              <button
                className={generationMode === "creative" ? "active" : ""}
                onClick={() => setGenerationMode("creative")}
                type="button"
              >
                自由
              </button>
            </div>
          </div>

          <div className="setting-line muted">
            <div>
              <label>客人换脸</label>
              <p>后端接口预留中，当前演示默认关闭。</p>
            </div>
            <span className="soon-badge">后续开放</span>
          </div>

          <div className="review-card">
            <MonitorCheck size={20} />
            <div>
              <span>当前方案</span>
              <strong>
                {selectedScene.label} / {resolution.toUpperCase()} / {posePrompt} /{" "}
                {generationMode === "stable" ? "保款式稳定" : "自由重绘"} / {preserveFace ? "保脸优先" : "自由生成"}
              </strong>
            </div>
          </div>
        </div>
      </section>

      <section className="panel tasks-panel">
        <div className="section-head">
          <div>
            <span className="section-kicker">队列</span>
            <h2>生成任务</h2>
          </div>
          <button className="small-button" onClick={fetchTasks}>
            <RefreshCw size={16} />
            更新
          </button>
        </div>

        <div className="task-list">
          {tasks.length === 0 ? (
            <div className="empty-state">
              <ImagePlus size={28} />
              <strong>还没有生成任务</strong>
              <span>上传素材后，点击开始生成即可创建第一条任务。</span>
            </div>
          ) : (
            tasks.map((task) => (
              <button className="task-row" key={task.task_id} onClick={() => setSelectedTask(task)}>
                <span className={`status-pill ${task.status}`}>
                  <StatusIcon status={task.status} />
                  {statusCopy[task.status]}
                </span>
                <div className="task-main">
                  <strong>{task.name || `任务 ${task.task_id}`}</strong>
                  <span>
                    {task.scene} / {task.resolution.toUpperCase()} / 进度 {Math.round(task.progress)}%
                  </span>
                </div>
                <div className="progress-track">
                  <span style={{ width: `${Math.max(4, Math.min(task.progress, 100))}%` }} />
                </div>
              </button>
            ))
          )}
        </div>
      </section>

      {selectedTask && <ResultDialog task={selectedTask} onClose={() => setSelectedTask(null)} />}

      {toast && (
        <div className="toast" role="status">
          <span>{toast}</span>
          <button onClick={() => setToast(null)}>
            <X size={16} />
          </button>
        </div>
      )}
    </main>
  );
}

function MetricCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "ok" | "down" | "checking" | "neutral" | "processing" | "completed";
}) {
  return (
    <div className={`metric-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function UploadCard({
  slot,
  state,
  onFile,
}: {
  slot: UploadSlot;
  state: UploadState;
  onFile: (slot: UploadSlot, file: File) => void;
}) {
  const copy = slotCopy[slot];

  function handleInput(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) onFile(slot, file);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (file) onFile(slot, file);
  }

  return (
    <label
      className={state.previewUrl ? "upload-card has-preview" : "upload-card"}
      onDrop={handleDrop}
      onDragOver={(event) => event.preventDefault()}
    >
      <input type="file" accept="image/*" onChange={handleInput} />
      {state.previewUrl ? (
        <img src={state.previewUrl} alt={copy.title} />
      ) : (
        <div className="upload-placeholder">
          <ImagePlus size={24} />
          <span>点击或拖入图片</span>
        </div>
      )}
      <div className="upload-meta">
        <div>
          <strong>
            {copy.title}
            {copy.required && <em>*</em>}
          </strong>
          <span>{state.filename || copy.subtitle}</span>
        </div>
        {state.uploading ? <Loader2 size={18} className="spin" /> : state.fileId ? <CheckCircle2 size={18} /> : null}
      </div>
    </label>
  );
}

function ResultDialog({ task, onClose }: { task: Task; onClose: () => void }) {
  const imageSteps = [
    { key: "dress", label: "AI 试衣结果" },
    { key: "scene", label: "场景/背景结果" },
    { key: "final", label: "最终交付图" },
  ];

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <div className="result-dialog">
        <div className="dialog-head">
          <div>
            <span className={`status-pill ${task.status}`}>
              <StatusIcon status={task.status} />
              {statusCopy[task.status]}
            </span>
            <h2>{task.name || `任务 ${task.task_id}`}</h2>
          </div>
          <button onClick={onClose} aria-label="关闭结果">
            <X size={22} />
          </button>
        </div>

        {task.status === "failed" ? (
          <div className="error-box">
            <AlertCircle size={20} />
            <span>{task.error_message || "生成失败，请检查素材或后端配置。"}</span>
          </div>
        ) : (
          <div className="result-grid">
            {imageSteps.map((step) => (
              <div className="result-card" key={step.key}>
                <strong>{step.label}</strong>
                {task.output_files?.[step.key] ? (
                  <img src={`/api/task/${task.task_id}/${step.key === "final" ? "result" : `step/${step.key}`}`} alt={step.label} />
                ) : (
                  <div className="result-empty">暂未生成</div>
                )}
              </div>
            ))}
          </div>
        )}

        {task.output_files?.final && (
          <a className="download-button" href={`/api/task/${task.task_id}/result`} download>
            <ArrowDownToLine size={18} />
            下载最终图
          </a>
        )}
      </div>
    </div>
  );
}
