import {
  ArrowDownToLine,
  Camera,
  CheckCircle2,
  CircleDashed,
  ImagePlus,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Star,
  UploadCloud,
  WandSparkles,
} from "lucide-react";
import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";

type UploadSlot = "model" | "dress";
type AssetCategory = "model" | "dress" | "face" | "pose_reference";
type TaskStatus = "pending" | "processing" | "completed" | "failed";

type UploadState = {
  fileId: string | null;
  assetId: string | null;
  previewUrl: string | null;
  filename: string | null;
  uploading: boolean;
};

type LibraryAsset = {
  asset_id: string;
  category: AssetCategory;
  file_id: string;
  filename: string;
  created_at: string;
  image_url: string;
};

type Task = {
  task_id: string;
  name: string;
  status: TaskStatus;
  progress: number;
  scene: string;
  resolution: string;
  current_step_label?: string;
  output_files: Record<string, boolean>;
  error_message: string;
  created_at: string;
  is_deliverable?: boolean;
};

const emptyUpload: UploadState = {
  fileId: null,
  assetId: null,
  previewUrl: null,
  filename: null,
  uploading: false,
};

const scenes = [
  { value: "海边", label: "海边日落", hint: "暖光、海浪、婚纱大片" },
  { value: "教堂", label: "教堂婚礼", hint: "彩窗、仪式、庄重感" },
  { value: "花园", label: "欧式花园", hint: "花艺、柔光、自然感" },
  { value: "影棚", label: "高级影棚", hint: "干净、稳定、适合验款" },
];

const statusCopy: Record<TaskStatus, string> = {
  pending: "排队中",
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
  async assets(category?: AssetCategory) {
    const query = category ? `?category=${encodeURIComponent(category)}` : "";
    const response = await fetch(`/api/assets${query}`);
    const data = await readApiJson<{ assets: LibraryAsset[] }>(response, "素材库获取失败");
    return data.assets;
  },
  async upload(file: File, category: AssetCategory) {
    const form = new FormData();
    form.append("file", file);
    form.append("category", category);
    const response = await fetch("/api/upload", { method: "POST", body: form });
    const data = await readApiJson<{ file_id?: string; file_path?: string; asset?: LibraryAsset }>(response, "上传失败");
    return { fileId: data.file_id || data.file_path, asset: data.asset };
  },
  async createTask(payload: Record<string, unknown>) {
    const response = await fetch("/api/create-task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return readApiJson<{ task_id: string }>(response, "创建任务失败");
  },
  async tasks() {
    const response = await fetch("/api/tasks?page=1&page_size=40");
    const data = await readApiJson<{ tasks: Task[] }>(response, "任务列表获取失败");
    return data.tasks;
  },
  async markDeliverable(taskId: string, value: boolean) {
    const response = await fetch(`/api/task/${taskId}/deliverable`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_deliverable: value }),
    });
    return readApiJson<{ task: Task }>(response, "更新交付标记失败");
  },
};

function statusIcon(status: TaskStatus) {
  if (status === "completed") return <CheckCircle2 size={16} />;
  if (status === "processing") return <Loader2 size={16} className="spin" />;
  return <CircleDashed size={16} />;
}

function shortName(filename: string) {
  if (/^[0-9a-f]{24,}\.(png|jpe?g|webp)$/i.test(filename)) return `素材 #${filename.slice(0, 8)}`;
  return filename;
}

function latestCompleted(tasks: Task[]) {
  return tasks.find((task) => task.status === "completed" && task.output_files?.final) || null;
}

export function ClientApp({ onOpenTestStudio }: { onOpenTestStudio: () => void }) {
  const [uploads, setUploads] = useState<Record<UploadSlot, UploadState>>({
    model: emptyUpload,
    dress: emptyUpload,
  });
  const [assets, setAssets] = useState<LibraryAsset[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [scene, setScene] = useState("海边");
  const [creating, setCreating] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [health, setHealth] = useState<"checking" | "ok" | "down">("checking");
  const [markingTaskId, setMarkingTaskId] = useState<string | null>(null);

  const fetchTasks = useCallback(async () => {
    try {
      setTasks(await api.tasks());
    } catch (error) {
      console.error(error);
    }
  }, []);

  const fetchAssets = useCallback(async () => {
    try {
      setAssets(await api.assets());
    } catch (error) {
      console.error(error);
    }
  }, []);

  useEffect(() => {
    api.health().then(() => setHealth("ok")).catch(() => setHealth("down"));
    fetchAssets();
    fetchTasks();
    const timer = window.setInterval(fetchTasks, 3500);
    return () => window.clearInterval(timer);
  }, [fetchAssets, fetchTasks]);

  const heroTask = useMemo(() => latestCompleted(tasks), [tasks]);
  const activeTask = tasks.find((task) => task.status === "processing" || task.status === "pending");
  const deliverableCount = tasks.filter((task) => task.is_deliverable).length;
  const modelAssets = assets.filter((asset) => asset.category === "model").slice(0, 8);
  const dressAssets = assets.filter((asset) => asset.category === "dress").slice(0, 8);

  async function handleUpload(slot: UploadSlot, file: File) {
    if (!file.type.startsWith("image/")) {
      setToast("请选择图片文件");
      return;
    }

    const previewUrl = URL.createObjectURL(file);
    setUploads((current) => ({
      ...current,
      [slot]: { fileId: null, assetId: null, previewUrl, filename: file.name, uploading: true },
    }));

    try {
      const { fileId, asset } = await api.upload(file, slot);
      if (!fileId) throw new Error("上传失败：后端没有返回文件 ID");
      setUploads((current) => ({
        ...current,
        [slot]: {
          fileId,
          assetId: asset?.asset_id || null,
          previewUrl,
          filename: file.name,
          uploading: false,
        },
      }));
      await fetchAssets();
    } catch (error) {
      URL.revokeObjectURL(previewUrl);
      setUploads((current) => ({ ...current, [slot]: emptyUpload }));
      setToast(error instanceof Error ? error.message : "上传失败");
    }
  }

  function selectAsset(slot: UploadSlot, asset: LibraryAsset) {
    setUploads((current) => ({
      ...current,
      [slot]: {
        fileId: asset.file_id,
        assetId: asset.asset_id,
        previewUrl: asset.image_url,
        filename: asset.filename,
        uploading: false,
      },
    }));
  }

  async function createTask() {
    if (!uploads.model.fileId || !uploads.dress.fileId) {
      setToast("先选择模特图和婚纱图");
      return;
    }

    setCreating(true);
    try {
      await api.createTask({
        name: `演示生成 / ${scene}`,
        model_file: uploads.model.fileId,
        dress_file: uploads.dress.fileId,
        clothing_type: "wedding_gown",
        scene,
        scene_prompt: "",
        resolution: "1k",
        face_swap: false,
        pose: "保持原姿势",
        pose_mode: "stable",
        preserve_face: true,
        generation_mode: "stable",
      });
      setToast("已提交生成任务");
      await fetchTasks();
    } catch (error) {
      setToast(error instanceof Error ? error.message : "创建任务失败");
    } finally {
      setCreating(false);
    }
  }

  async function toggleDeliverable(task: Task) {
    if (task.status !== "completed" || !task.output_files?.final) return;

    setMarkingTaskId(task.task_id);
    try {
      const { task: updated } = await api.markDeliverable(task.task_id, !task.is_deliverable);
      setTasks((current) => current.map((item) => (item.task_id === updated.task_id ? updated : item)));
      setToast(updated.is_deliverable ? "已加入交付包" : "已移出交付包");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "更新交付标记失败");
    } finally {
      setMarkingTaskId(null);
    }
  }

  return (
    <main className="client-shell">
      <header className="client-topbar">
        <div>
          <span className="client-mark">WEDDING AI</span>
          <strong>婚纱影像交付台</strong>
        </div>
        <div className="client-topbar-actions">
          <span className={`client-health ${health}`}>{health === "ok" ? "后端已连接" : health === "down" ? "后端未连接" : "检测中"}</span>
          <button onClick={onOpenTestStudio} type="button">测试台</button>
        </div>
      </header>

      <section className="client-board">
        <aside className="client-builder">
          <div className="client-section-title">
            <span>01 / 选片</span>
            <h1>选一位模特，配一件婚纱。</h1>
          </div>

          <VisualPicker
            assets={modelAssets}
            state={uploads.model}
            title="模特原图"
            slot="model"
            onFile={handleUpload}
            onSelect={selectAsset}
          />
          <VisualPicker
            assets={dressAssets}
            state={uploads.dress}
            title="婚纱款式"
            slot="dress"
            onFile={handleUpload}
            onSelect={selectAsset}
          />
        </aside>

        <section className="client-stage">
          <div className="client-stage-head">
            <div>
              <span>02 / 成片预览</span>
              <h2>{heroTask ? "最新生成结果" : "等待第一张成片"}</h2>
            </div>
            <button className="client-refresh" onClick={fetchTasks} type="button">
              <RefreshCw size={16} />
              刷新
            </button>
          </div>

          <div className="client-preview">
            {heroTask ? (
              <img src={`/api/task/${heroTask.task_id}/result`} alt="最新生成结果" />
            ) : (
              <div className="client-preview-empty">
                <Camera size={34} />
                <strong>生成完成后，最终图会显示在这里。</strong>
              </div>
            )}
          </div>

          <div className="client-scenes">
            {scenes.map((item) => (
              <button
                className={scene === item.value ? "active" : ""}
                key={item.value}
                onClick={() => setScene(item.value)}
                type="button"
              >
                <strong>{item.label}</strong>
                <span>{item.hint}</span>
              </button>
            ))}
          </div>

          <div className="client-generate-row">
            <div>
              <ShieldCheck size={18} />
              <span>稳定模式 / 保脸优先 / 1K 预览</span>
            </div>
            <button className="client-generate" disabled={creating} onClick={createTask} type="button">
              {creating ? <Loader2 size={18} className="spin" /> : <WandSparkles size={18} />}
              开始生成
            </button>
          </div>
        </section>

        <aside className="client-queue">
          <div className="client-section-title compact">
            <span>03 / 交付</span>
            <h2>任务与交付包</h2>
          </div>

          <div className="client-stats">
            <div>
              <span>生成中</span>
              <strong>{activeTask ? "1" : "0"}</strong>
            </div>
            <div>
              <span>可交付</span>
              <strong>{deliverableCount}</strong>
            </div>
          </div>

          <div className="client-task-list">
            {tasks.length === 0 ? (
              <div className="client-task-empty">
                <Sparkles size={22} />
                <span>还没有任务。选择素材后开始生成。</span>
              </div>
            ) : (
              tasks.slice(0, 8).map((task) => (
                <div className="client-task-card" key={task.task_id}>
                  <span className={`client-task-status ${task.status}`}>
                    {statusIcon(task.status)}
                    {statusCopy[task.status]}
                  </span>
                  <div>
                    <strong>{task.name || `任务 ${task.task_id}`}</strong>
                    <small>{task.current_step_label || task.scene} / {Math.round(task.progress)}%</small>
                  </div>
                  {task.output_files?.final && (
                    <div className="client-task-actions">
                      <a href={`/api/task/${task.task_id}/result`} download title="下载最终图">
                        <ArrowDownToLine size={15} />
                      </a>
                      <button
                        className={task.is_deliverable ? "active" : ""}
                        disabled={markingTaskId === task.task_id}
                        onClick={() => toggleDeliverable(task)}
                        title={task.is_deliverable ? "移出交付包" : "加入交付包"}
                        type="button"
                      >
                        {markingTaskId === task.task_id ? <Loader2 size={15} className="spin" /> : <Star size={15} />}
                      </button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </aside>
      </section>

      {toast && (
        <div className="client-toast" role="status" onClick={() => setToast(null)}>
          {toast}
        </div>
      )}
    </main>
  );
}

function VisualPicker({
  assets,
  onFile,
  onSelect,
  slot,
  state,
  title,
}: {
  assets: LibraryAsset[];
  onFile: (slot: UploadSlot, file: File) => void;
  onSelect: (slot: UploadSlot, asset: LibraryAsset) => void;
  slot: UploadSlot;
  state: UploadState;
  title: string;
}) {
  function handleInput(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) onFile(slot, file);
  }

  return (
    <section className="client-picker">
      <div className="client-picker-head">
        <strong>{title}</strong>
        <label>
          <UploadCloud size={15} />
          上传
          <input accept="image/*" type="file" onChange={handleInput} />
        </label>
      </div>

      <div className="client-current-pick">
        {state.previewUrl ? (
          <img src={state.previewUrl} alt={title} />
        ) : (
          <div>
            <ImagePlus size={22} />
            <span>从素材库选择，或上传新图。</span>
          </div>
        )}
        <small>{state.uploading ? "上传中..." : state.filename ? shortName(state.filename) : "未选择"}</small>
      </div>

      <div className="client-asset-strip">
        {assets.length === 0 ? (
          <span>暂无历史素材</span>
        ) : (
          assets.map((asset) => (
            <button
              className={state.assetId === asset.asset_id ? "active" : ""}
              key={asset.asset_id}
              onClick={() => onSelect(slot, asset)}
              title={asset.filename}
              type="button"
            >
              <img src={asset.image_url} alt={asset.filename} />
            </button>
          ))
        )}
      </div>
    </section>
  );
}
