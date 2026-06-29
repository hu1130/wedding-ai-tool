import {
  AlertCircle,
  ArrowDownToLine,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  ImagePlus,
  LockKeyhole,
  Loader2,
  MonitorCheck,
  Play,
  RefreshCw,
  Sparkles,
  Trash2,
  UploadCloud,
  WandSparkles,
  X,
} from "lucide-react";
import { ChangeEvent, DragEvent, useCallback, useEffect, useMemo, useState } from "react";

type UploadSlot = "model" | "dress" | "face";
type TaskStatus = "pending" | "processing" | "completed" | "failed";
type PoseMode = "stable" | "light" | "experimental";

type Task = {
  task_id: string;
  name: string;
  status: TaskStatus;
  progress: number;
  model_file?: string;
  dress_file?: string;
  face_file?: string | null;
  scene: string;
  scene_prompt?: string;
  resolution: string;
  face_swap: boolean;
  pose?: string;
  pose_mode?: PoseMode;
  preserve_face?: boolean;
  generation_mode?: "stable" | "creative";
  parent_task_id?: string | null;
  rerun_index?: number;
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
  { value: "海边", label: "海边日落", tone: "浪漫光影", demoSafe: true },
  { value: "教堂", label: "教堂婚礼", tone: "庄重仪式", demoSafe: true },
  { value: "花园", label: "欧式花园", tone: "柔和自然", demoSafe: true },
  { value: "影棚", label: "高级影棚", tone: "干净稳妥", demoSafe: true },
  { value: "城堡", label: "欧式城堡", tone: "奢华大片", demoSafe: false },
  { value: "中式庭院", label: "中式庭院", tone: "东方雅致", demoSafe: false },
  { value: "森林", label: "森林秘境", tone: "清透仙气", demoSafe: false },
  { value: "天台夜景", label: "天台夜景", tone: "现代高级", demoSafe: false },
  { value: "自定义背景", label: "自定义背景", tone: "自由描述", demoSafe: false },
];

const poses = [
  { value: "保持原姿势", label: "保持原姿势", tone: "保脸保款", mode: "stable" as const, demoSafe: true },
  { value: "正面站姿，双臂自然下垂", label: "正面站姿", tone: "轻动作", mode: "light" as const, demoSafe: true },
  { value: "轻微行走感，裙摆自然展开", label: "行走感", tone: "轻动作", mode: "light" as const, demoSafe: true },
  { value: "微侧身站姿，一只手轻扶裙摆", label: "手扶裙摆", tone: "实验动作", mode: "experimental" as const, demoSafe: false },
  { value: "回眸微笑，身体轻微侧转", label: "回眸", tone: "实验动作", mode: "experimental" as const, demoSafe: false },
  { value: "坐姿，裙摆自然铺开", label: "坐姿", tone: "实验动作", mode: "experimental" as const, demoSafe: false },
];

const demoScenes = new Set(scenes.filter((item) => item.demoSafe).map((item) => item.value));
const poseGroups: { mode: PoseMode; title: string; hint: string }[] = [
  { mode: "stable", title: "稳妥动作", hint: "优先保脸和婚纱款式" },
  { mode: "light", title: "轻动作", hint: "适合老板演示小幅变化" },
  { mode: "experimental", title: "实验动作", hint: "动作更明显，建议多跑挑片" },
];
const poseModeCopy: Record<PoseMode, string> = {
  stable: "稳妥动作",
  light: "轻动作",
  experimental: "实验动作",
};

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
    scene_prompt?: string;
    resolution: string;
    face_swap: boolean;
    pose: string;
    pose_mode: PoseMode;
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
  async rerunTask(taskId: string) {
    const response = await fetch(`/api/task/${taskId}/rerun`, { method: "POST" });
    const data = await readApiJson<{ task_id: string; rerun_index: number }>(response, "重跑任务失败");
    return data;
  },
  async deleteTask(taskId: string) {
    const response = await fetch(`/api/task/${taskId}`, { method: "DELETE" });
    return readApiJson<{ removed_dirs: number; removed_files: number; success: boolean }>(
      response,
      "删除任务失败",
    );
  },
};

function StatusIcon({ status }: { status: TaskStatus }) {
  if (status === "completed") return <CheckCircle2 size={16} />;
  if (status === "failed") return <AlertCircle size={16} />;
  if (status === "processing") return <Loader2 size={16} className="spin" />;
  return <CircleDashed size={16} />;
}

function taskDisplayName(task: Task) {
  const name = task.name?.trim();
  if (!name || /^\?+$/.test(name)) return `任务 ${task.task_id}`;
  return name;
}

function taskSeriesRoot(task: Task) {
  return task.parent_task_id || task.task_id;
}

function taskVersionLabel(task: Task) {
  return `V${task.rerun_index || 1}`;
}

function taskSceneSummary(task: Pick<Task, "scene" | "scene_prompt">) {
  const prompt = task.scene_prompt?.trim();
  if (task.scene === "自定义背景" && prompt) return `自定义背景：${prompt}`;
  return task.scene;
}

export function App() {
  const [uploads, setUploads] = useState<Record<UploadSlot, UploadState>>({
    model: emptyUpload,
    dress: emptyUpload,
    face: emptyUpload,
  });
  const [scene, setScene] = useState("海边");
  const [customScenePrompt, setCustomScenePrompt] = useState("");
  const [pose, setPose] = useState("保持原姿势");
  const [customPose, setCustomPose] = useState("");
  const [preserveFace, setPreserveFace] = useState(true);
  const [generationMode, setGenerationMode] = useState<"stable" | "creative">("stable");
  const [resolution, setResolution] = useState("1k");
  const [demoMode, setDemoMode] = useState(true);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [health, setHealth] = useState<"checking" | "ok" | "down">("checking");
  const [toast, setToast] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [rerunningTaskId, setRerunningTaskId] = useState<string | null>(null);

  const selectedScene = useMemo(
    () => scenes.find((item) => item.value === scene) || scenes[0],
    [scene],
  );
  const scenePrompt = scene === "自定义背景" ? customScenePrompt.trim() : "";
  const sceneSummary = scenePrompt ? `自定义背景：${scenePrompt}` : selectedScene.label;
  const selectedPose = useMemo(
    () => poses.find((item) => item.value === pose) || poses[0],
    [pose],
  );
  const posePrompt = customPose.trim() || pose;
  const poseMode: PoseMode = customPose.trim() ? "experimental" : selectedPose.mode;
  const poseModeLabel = poseModeCopy[poseMode];
  const selectedVersions = useMemo(() => {
    if (!selectedTask) return [];
    const rootId = taskSeriesRoot(selectedTask);
    return tasks
      .filter((task) => task.task_id === rootId || task.parent_task_id === rootId)
      .sort((a, b) => (a.rerun_index || 1) - (b.rerun_index || 1));
  }, [selectedTask, tasks]);

  const fetchTasks = useCallback(async () => {
    try {
      const nextTasks = await api.tasks();
      setTasks(nextTasks);
      setSelectedTask((current) =>
        current ? nextTasks.find((task) => task.task_id === current.task_id) || null : current,
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

  useEffect(() => {
    if (!demoMode) return;
    setGenerationMode("stable");
    setResolution("1k");
    setPreserveFace(true);
    setPose("保持原姿势");
    setCustomPose("");
    setCustomScenePrompt("");
    setScene((current) => (demoScenes.has(current) ? current : "海边"));
  }, [demoMode]);

  function setDemoScene(nextScene: string) {
    if (demoMode && !demoScenes.has(nextScene)) {
      setToast("老板演示模式只开放海边、教堂、花园、影棚四个稳定场景");
      return;
    }
    setScene(nextScene);
    if (nextScene !== "自定义背景") setCustomScenePrompt("");
  }

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
    if (scene === "自定义背景" && !scenePrompt) {
      setToast("请填写自定义背景描述，或选择一个预设背景");
      return;
    }

    setCreating(true);
    try {
      await api.createTask({
        model_file: modelFile,
        dress_file: dressFile,
        face_file: uploads.face.fileId,
        scene,
        scene_prompt: scenePrompt,
        resolution,
        face_swap: false,
        pose: posePrompt,
        pose_mode: poseMode,
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

  async function handleRerunTask(task: Task) {
    if (task.status === "processing") {
      setToast("任务正在生成中，完成或失败后再重跑");
      return;
    }

    setRerunningTaskId(task.task_id);
    try {
      const result = await api.rerunTask(task.task_id);
      setToast(`已创建 V${result.rerun_index}，正在生成`);
      const nextTasks = await api.tasks();
      setTasks(nextTasks);
      const nextTask = nextTasks.find((item) => item.task_id === result.task_id);
      if (nextTask) setSelectedTask(nextTask);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "重跑任务失败");
    } finally {
      setRerunningTaskId(null);
    }
  }

  async function handleDeleteTask(task: Task) {
    if (task.status === "processing") {
      setToast("任务正在生成中，完成或失败后再删除");
      return;
    }

    const ok = window.confirm(`确定删除「${taskDisplayName(task)}」吗？任务记录、生成图和未被其他任务使用的上传素材都会删除。`);
    if (!ok) return;

    setDeletingTaskId(task.task_id);
    try {
      await api.deleteTask(task.task_id);
      setToast("任务已删除");
      setSelectedTask((current) => (current?.task_id === task.task_id ? null : current));
      await fetchTasks();
    } catch (error) {
      setToast(error instanceof Error ? error.message : "删除任务失败");
    } finally {
      setDeletingTaskId(null);
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

          <div className={demoMode ? "demo-card active" : "demo-card"}>
            <div className="demo-card-copy">
              <LockKeyhole size={20} />
              <div>
                <strong>老板演示模式</strong>
                <span>锁定稳定生成、1K 预览、保脸优先和安全场景，优先避免脸变、裙子变。</span>
              </div>
            </div>
            <button
              className={demoMode ? "switch-button active" : "switch-button"}
              onClick={() => setDemoMode((value) => !value)}
              type="button"
            >
              {demoMode ? "演示中" : "自定义"}
            </button>
          </div>

          <div className="setting-block">
            <label>拍摄场景</label>
            <div className="scene-grid">
              {scenes.map((item) => (
                <button
                  className={[
                    "scene-card",
                    item.value === scene ? "active" : "",
                    demoMode && !demoScenes.has(item.value) ? "disabled" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  key={item.value}
                  onClick={() => setDemoScene(item.value)}
                  disabled={demoMode && !demoScenes.has(item.value)}
                >
                  <strong>{item.label}</strong>
                  <span>{item.tone}</span>
                  <em>{item.demoSafe ? "演示安全" : "自由测试"}</em>
                </button>
              ))}
            </div>
            <textarea
              className="scene-textarea"
              value={customScenePrompt}
              onChange={(event) => setCustomScenePrompt(event.target.value.slice(0, 240))}
              disabled={demoMode || scene !== "自定义背景"}
              placeholder="自定义背景，例如：法式酒店旋转楼梯，暖色吊灯，浅金色花艺，真实婚礼摄影光线"
            />
            <div className="field-hint">
              {scene === "自定义背景"
                ? `${customScenePrompt.length}/240，描述背景和光线，不要写换脸、改裙子这类要求`
                : "预设背景会自动使用更稳的婚纱摄影提示词"}
            </div>
          </div>

          <div className="setting-block pose-block">
            <label>动作 / 姿势</label>
            <div className="pose-group-list">
              {poseGroups.map((group) => (
                <div className="pose-group" key={group.mode}>
                  <div className="pose-group-head">
                    <strong>{group.title}</strong>
                    <span>{group.hint}</span>
                  </div>
                  <div className="scene-grid pose-grid">
                    {poses
                      .filter((item) => item.mode === group.mode)
                      .map((item) => (
                        <button
                          className={[
                            "scene-card",
                            "pose-card",
                            item.value === pose && !customPose.trim() ? "active" : "",
                            demoMode && !item.demoSafe ? "disabled" : "",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                          key={item.value}
                          onClick={() => {
                            if (demoMode && !item.demoSafe) {
                              setToast("老板演示模式只开放保持原姿势、正面站姿和行走感");
                              return;
                            }
                            setPose(item.value);
                            setCustomPose("");
                          }}
                          disabled={demoMode && !item.demoSafe}
                        >
                          <strong>{item.label}</strong>
                          <span>{item.tone}</span>
                          <em>{poseModeCopy[item.mode]}</em>
                        </button>
                      ))}
                  </div>
                </div>
              ))}
            </div>
            <input
              className="pose-input"
              value={customPose}
              onChange={(event) => setCustomPose(event.target.value)}
              disabled={demoMode}
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
                  onClick={() => {
                    if (demoMode && item !== "1k") return;
                    setResolution(item);
                  }}
                  disabled={demoMode && item !== "1k"}
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
              onClick={() => {
                if (demoMode) return;
                setPreserveFace((value) => !value);
              }}
              disabled={demoMode}
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
                onClick={() => {
                  if (demoMode) return;
                  setGenerationMode("creative");
                }}
                disabled={demoMode}
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
              <span>{demoMode ? "当前方案 · 演示锁定" : "当前方案"}</span>
              <strong>
                {sceneSummary} / {resolution.toUpperCase()} / {poseModeLabel} / {posePrompt} /{" "}
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
              tasks.map((task) => {
                const deleting = deletingTaskId === task.task_id;
                const canDelete = task.status !== "processing";
                const sceneInfo = taskSceneSummary(task);

                return (
                  <div className="task-row" key={task.task_id}>
                  <button className="task-open-button" onClick={() => setSelectedTask(task)} type="button">
                    <span className={`status-pill ${task.status}`}>
                      <StatusIcon status={task.status} />
                      {statusCopy[task.status]}
                    </span>
                    <div className="task-main">
                      <strong>
                        {taskDisplayName(task)}
                        <span className="version-badge">{taskVersionLabel(task)}</span>
                      </strong>
                      <span title={sceneInfo}>
                        {sceneInfo} / {task.resolution.toUpperCase()} / 进度 {Math.round(task.progress)}%
                      </span>
                    </div>
                    <div className="progress-track">
                      <span style={{ width: `${Math.max(4, Math.min(task.progress, 100))}%` }} />
                    </div>
                  </button>
                  <button
                    aria-label="删除任务"
                    className="icon-danger-button"
                    disabled={deleting || !canDelete}
                    onClick={() => handleDeleteTask(task)}
                    title={canDelete ? "删除任务与文件" : "生成中暂不能删除"}
                    type="button"
                  >
                    {deleting ? <Loader2 size={16} className="spin" /> : <Trash2 size={16} />}
                  </button>
                </div>
              );
            })
          )}
        </div>
      </section>

      {selectedTask && (
        <ResultDialog
          deleting={deletingTaskId === selectedTask.task_id}
          rerunning={rerunningTaskId === selectedTask.task_id}
          task={selectedTask}
          versions={selectedVersions}
          onClose={() => setSelectedTask(null)}
          onDelete={handleDeleteTask}
          onRerun={handleRerunTask}
          onSelectVersion={setSelectedTask}
        />
      )}

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

function ResultDialog({
  deleting,
  rerunning,
  task,
  versions,
  onClose,
  onDelete,
  onRerun,
  onSelectVersion,
}: {
  deleting: boolean;
  rerunning: boolean;
  task: Task;
  versions: Task[];
  onClose: () => void;
  onDelete: (task: Task) => void;
  onRerun: (task: Task) => void;
  onSelectVersion: (task: Task) => void;
}) {
  const sceneInfo = taskSceneSummary(task);
  const comparisonImages = [
    { key: "model", label: "模特原图", src: `/api/task/${task.task_id}/input/model` },
    { key: "dress", label: "婚纱款式", src: `/api/task/${task.task_id}/input/dress` },
    { key: "final", label: "最终交付图", src: `/api/task/${task.task_id}/result` },
  ];
  const imageSteps = [
    { key: "dress", label: "款式/试衣步骤" },
    { key: "scene", label: "场景生成结果" },
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
            <h2>{taskDisplayName(task)}</h2>
          </div>
          <button onClick={onClose} aria-label="关闭结果">
            <X size={22} />
          </button>
        </div>

        <div className="task-config-strip">
          <span>
            背景 <strong>{sceneInfo}</strong>
          </span>
          <span>
            动作 <strong>{task.pose || "保持原姿势"}</strong>
          </span>
          <span>
            动作模式 <strong>{poseModeCopy[task.pose_mode || "stable"]}</strong>
          </span>
          <span>
            规格 <strong>{task.resolution.toUpperCase()}</strong>
          </span>
          <span>
            模式 <strong>{task.generation_mode === "creative" ? "自由重绘" : "保款式稳定"}</strong>
          </span>
          <span>
            人脸 <strong>{task.preserve_face ? "保脸优先" : "自由生成"}</strong>
          </span>
        </div>

        {versions.length > 0 && (
          <div className="version-strip">
            <div>
              <span className="section-kicker">版本挑片</span>
              <strong>同一组素材可以多次重跑，保留最好的一版</strong>
            </div>
            <div className="version-list">
              {versions.map((version) => (
                <button
                  className={version.task_id === task.task_id ? "version-chip active" : "version-chip"}
                  key={version.task_id}
                  onClick={() => onSelectVersion(version)}
                  type="button"
                >
                  <span>{taskVersionLabel(version)}</span>
                  <small>{statusCopy[version.status]}</small>
                </button>
              ))}
            </div>
          </div>
        )}

        {task.status === "failed" ? (
          <div className="error-box">
            <AlertCircle size={20} />
            <span>{task.error_message || "生成失败，请检查素材或后端配置。"}</span>
          </div>
        ) : (
          <>
            <div className="comparison-strip">
              <div className="comparison-heading">
                <span className="section-kicker">交付对比</span>
                <strong>老板一眼看懂：原模特、原婚纱、最终图</strong>
              </div>
              <div className="comparison-grid">
                {comparisonImages.map((item) => (
                  <div className="comparison-card" key={item.key}>
                    <strong>{item.label}</strong>
                    {item.key === "final" && !task.output_files?.final ? (
                      <div className="result-empty">暂未生成</div>
                    ) : (
                      <img src={item.src} alt={item.label} />
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="process-results">
              <div className="comparison-heading compact">
                <span className="section-kicker">过程文件</span>
                <strong>用于排查款式、场景和最终图差异</strong>
              </div>
              <div className="result-grid">
                {imageSteps.map((step) => (
                  <div className="result-card" key={step.key}>
                    <strong>{step.label}</strong>
                    {task.output_files?.[step.key] ? (
                      <img src={`/api/task/${task.task_id}/step/${step.key}`} alt={step.label} />
                    ) : (
                      <div className="result-empty">暂未生成</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

        <div className="dialog-actions">
          {task.output_files?.final && (
            <a className="download-button" href={`/api/task/${task.task_id}/result`} download>
              <ArrowDownToLine size={18} />
              下载最终图
            </a>
          )}
          <button
            className="rerun-button"
            disabled={rerunning || task.status === "processing"}
            onClick={() => onRerun(task)}
            type="button"
          >
            {rerunning ? <Loader2 size={18} className="spin" /> : <RefreshCw size={18} />}
            重跑一版
          </button>
          <button
            className="delete-button"
            disabled={deleting || task.status === "processing"}
            onClick={() => onDelete(task)}
            type="button"
          >
            {deleting ? <Loader2 size={18} className="spin" /> : <Trash2 size={18} />}
            删除这一组
          </button>
        </div>
      </div>
    </div>
  );
}
