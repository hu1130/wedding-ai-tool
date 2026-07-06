import {
  AlertCircle,
  ArrowDownToLine,
  CheckCircle2,
  CircleDashed,
  Eye,
  ImagePlus,
  Loader2,
  PackageCheck,
  RefreshCw,
  ShieldCheck,
  Star,
  Trash2,
  UploadCloud,
  WandSparkles,
  Wifi,
  WifiOff,
  X,
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
  scene_prompt?: string;
  resolution: string;
  pose?: string;
  pose_mode?: "stable" | "light" | "experimental";
  preserve_face?: boolean;
  generation_mode?: "stable" | "creative";
  parent_task_id?: string | null;
  rerun_index?: number;
  is_deliverable?: boolean;
  current_step_label?: string;
  output_files: Record<string, boolean>;
  error_message: string;
  created_at: string;
};

type QualityReview = {
  task_id: string;
  face_score: number;
  dress_score: number;
  pose_score: number;
  background_score: number;
  overall_score: number;
  pass_result: boolean;
  notes: string;
  reviewer: string;
  created_at: string;
  updated_at: string;
};

type QualityReviewPayload = {
  face_score: number;
  dress_score: number;
  pose_score: number;
  background_score: number;
  overall_score?: number;
  pass_result?: boolean;
  notes: string;
  reviewer?: string;
};

type CreateTaskPayload = {
  name: string;
  model_file: string;
  dress_file: string;
  clothing_type: "wedding_gown";
  scene: string;
  scene_prompt: string;
  resolution: "1k";
  face_swap: false;
  pose: string;
  pose_mode: "stable";
  preserve_face: true;
  generation_mode: "stable";
};

const emptyUpload: UploadState = {
  fileId: null,
  assetId: null,
  previewUrl: null,
  filename: null,
  uploading: false,
};

const scenes = [
  {
    value: "海边",
    label: "海边",
    detail: "夕阳、海浪、暖光",
    prompt: "海边夕阳婚纱摄影，柔和逆光，真实摄影质感，保留人物脸部特征和婚纱款式",
  },
  {
    value: "教堂",
    label: "教堂",
    detail: "彩窗、仪式、庄重",
    prompt: "教堂婚礼场景，彩色玻璃窗，柔和自然光，真实婚纱摄影，保留人物脸部特征和婚纱款式",
  },
  {
    value: "花园",
    label: "花园",
    detail: "花艺、自然、轻盈",
    prompt: "欧式花园婚纱摄影，浅色花艺背景，柔光，真实摄影质感，保留人物脸部特征和婚纱款式",
  },
  {
    value: "影棚",
    label: "影棚",
    detail: "干净、控光、稳定",
    prompt: "高级影棚婚纱摄影，干净浅色背景，专业布光，真实摄影质感，保留人物脸部特征和婚纱款式",
  },
];

const statusCopy: Record<TaskStatus, string> = {
  pending: "等待中",
  processing: "生成中",
  completed: "已完成",
  failed: "失败",
};

const qualityScoreLabels: Array<{ key: keyof Pick<QualityReviewPayload, "face_score" | "dress_score" | "pose_score" | "background_score">; label: string }> = [
  { key: "face_score", label: "人脸" },
  { key: "dress_score", label: "款式" },
  { key: "pose_score", label: "动作" },
  { key: "background_score", label: "背景" },
];

const slotCopy: Record<UploadSlot, { title: string; hint: string; category: AssetCategory }> = {
  model: {
    title: "模特原图",
    hint: "建议正面全身、光线干净",
    category: "model",
  },
  dress: {
    title: "婚纱款式",
    hint: "单件婚纱图更利于款式还原",
    category: "dress",
  },
};

async function readApiJson<T>(response: Response, fallbackMessage: string): Promise<T> {
  const text = await response.text();
  let data: unknown = {};

  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      throw new Error(response.ok ? `${fallbackMessage}：后端返回内容不是 JSON` : text);
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
    const data = await readApiJson<{ file_id?: string; file_path?: string; asset?: LibraryAsset }>(
      response,
      "上传失败",
    );
    return { fileId: data.file_id || data.file_path, asset: data.asset };
  },
  async createTask(payload: CreateTaskPayload) {
    const response = await fetch("/api/create-task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return readApiJson<{ task_id: string }>(response, "创建任务失败");
  },
  async tasks() {
    const response = await fetch("/api/tasks?page=1&page_size=50");
    const data = await readApiJson<{ tasks: Task[] }>(response, "任务列表获取失败");
    return data.tasks;
  },
  async markDeliverable(taskId: string, value: boolean) {
    const response = await fetch(`/api/task/${taskId}/deliverable`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_deliverable: value }),
    });
    const data = await readApiJson<{ task: Task }>(response, "更新交付标记失败");
    return data.task;
  },
  async getQualityReview(taskId: string) {
    const response = await fetch(`/api/task/${taskId}/quality-review`);
    const data = await readApiJson<{ review: QualityReview | null }>(response, "获取质量评分失败");
    return data.review;
  },
  async saveQualityReview(taskId: string, payload: QualityReviewPayload) {
    const response = await fetch(`/api/task/${taskId}/quality-review`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await readApiJson<{ review: QualityReview }>(response, "保存质量评分失败");
    return data.review;
  },
  async deleteTask(taskId: string) {
    const response = await fetch(`/api/task/${taskId}`, { method: "DELETE" });
    return readApiJson<{ success: boolean }>(response, "删除任务失败");
  },
  async deleteAsset(assetId: string) {
    const response = await fetch(`/api/assets/${assetId}`, { method: "DELETE" });
    return readApiJson<{ success: boolean }>(response, "删除素材失败");
  },
  async exportDeliverables() {
    const response = await fetch("/api/deliverables/export");
    if (!response.ok) {
      const text = await response.text();
      let message = "导出交付包失败";
      if (text) {
        try {
          const data = JSON.parse(text) as { detail?: unknown };
          message = data.detail ? String(data.detail) : message;
        } catch {
          message = text;
        }
      }
      throw new Error(message);
    }

    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    return {
      blob: await response.blob(),
      filename: match?.[1] || "wedding-deliverables.zip",
    };
  },
};

function statusIcon(status: TaskStatus) {
  if (status === "completed") return <CheckCircle2 size={15} />;
  if (status === "failed") return <AlertCircle size={15} />;
  if (status === "processing") return <Loader2 size={15} className="spin" />;
  return <CircleDashed size={15} />;
}

function taskDisplayName(task: Task) {
  const name = task.name?.trim();
  if (!name || /^\?+$/.test(name)) return `任务 ${task.task_id}`;
  return name;
}

function taskSceneLabel(task: Pick<Task, "scene" | "scene_prompt">) {
  if (task.scene === "自定义背景" && task.scene_prompt?.trim()) {
    return task.scene_prompt.trim();
  }
  return task.scene || "未记录";
}

function taskFailureMessage(task: Pick<Task, "error_message">) {
  return task.error_message?.trim() || "生成失败，请检查素材、网络或后端配置。";
}

function shortFileName(filename: string | null) {
  if (!filename) return "未选择";
  if (/^[0-9a-f]{20,}\.(png|jpe?g|webp)$/i.test(filename)) return `素材 #${filename.slice(0, 8)}`;
  return filename;
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function latestCompleted(tasks: Task[]) {
  return tasks.find((task) => task.status === "completed" && task.output_files?.final) || null;
}

function currentGeneratingTask(tasks: Task[]) {
  return tasks.find((task) => task.status === "processing" || task.status === "pending") || null;
}

function mostRecentFailure(tasks: Task[]) {
  return tasks.find((task) => task.status === "failed") || null;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function ClientApp({ onOpenTestStudio }: { onOpenTestStudio: () => void }) {
  const [uploads, setUploads] = useState<Record<UploadSlot, UploadState>>({
    model: emptyUpload,
    dress: emptyUpload,
  });
  const [assets, setAssets] = useState<LibraryAsset[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [scene, setScene] = useState(scenes[0].value);
  const [creating, setCreating] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [health, setHealth] = useState<"checking" | "ok" | "down">("checking");
  const [notice, setNotice] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [previewTask, setPreviewTask] = useState<Task | null>(null);
  const [markingTaskId, setMarkingTaskId] = useState<string | null>(null);
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [deletingAssetId, setDeletingAssetId] = useState<string | null>(null);

  const fetchTasks = useCallback(async () => {
    try {
      setTasks(await api.tasks());
    } catch (error) {
      console.error(error);
      setNotice(error instanceof Error ? error.message : "任务列表获取失败");
    }
  }, []);

  const fetchAssets = useCallback(async () => {
    try {
      setAssets(await api.assets());
    } catch (error) {
      console.error(error);
      setNotice(error instanceof Error ? error.message : "素材库获取失败");
    }
  }, []);

  useEffect(() => {
    api.health()
      .then(() => setHealth("ok"))
      .catch(() => setHealth("down"));
    fetchAssets();
    fetchTasks();
    const timer = window.setInterval(fetchTasks, 3000);
    return () => window.clearInterval(timer);
  }, [fetchAssets, fetchTasks]);

  const selectedScene = useMemo(
    () => scenes.find((item) => item.value === scene) || scenes[0],
    [scene],
  );
  const modelAssets = assets.filter((asset) => asset.category === "model").slice(0, 12);
  const dressAssets = assets.filter((asset) => asset.category === "dress").slice(0, 12);
  const heroTask = latestCompleted(tasks);
  const activeTask = currentGeneratingTask(tasks);
  const failedTask = mostRecentFailure(tasks);
  const recentTasks = tasks.slice(0, 5);
  const deliverableCount = tasks.filter((task) => task.is_deliverable).length;
  const missingItems = [
    !uploads.model.fileId ? "模特原图" : "",
    !uploads.dress.fileId ? "婚纱款式" : "",
  ].filter(Boolean);
  const canGenerate = missingItems.length === 0 && !creating && !activeTask;
  const generateHint =
    missingItems.length > 0
      ? `请先选择 ${missingItems.join("、")}`
      : activeTask
        ? `当前任务：${activeTask.current_step_label || statusCopy[activeTask.status]} / ${Math.round(activeTask.progress)}%`
        : "同一组素材可以多次重跑，保留最好的一版";

  async function handleUpload(slot: UploadSlot, file: File) {
    if (!file.type.startsWith("image/")) {
      setNotice("请选择图片文件");
      return;
    }

    const previewUrl = URL.createObjectURL(file);
    setUploads((current) => ({
      ...current,
      [slot]: {
        fileId: null,
        assetId: null,
        previewUrl,
        filename: file.name,
        uploading: true,
      },
    }));

    try {
      const { fileId, asset } = await api.upload(file, slotCopy[slot].category);
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
      setNotice(`${slotCopy[slot].title}已上传`);
      await fetchAssets();
    } catch (error) {
      URL.revokeObjectURL(previewUrl);
      setUploads((current) => ({ ...current, [slot]: emptyUpload }));
      setNotice(error instanceof Error ? error.message : "上传失败");
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
    if (!canGenerate || !uploads.model.fileId || !uploads.dress.fileId) return;

    setCreating(true);
    setNotice(null);
    try {
      await api.createTask({
        name: `婚纱试衣 / ${selectedScene.label}`,
        model_file: uploads.model.fileId,
        dress_file: uploads.dress.fileId,
        clothing_type: "wedding_gown",
        scene: selectedScene.value,
        scene_prompt: selectedScene.prompt,
        resolution: "1k",
        face_swap: false,
        pose: "保持原姿势",
        pose_mode: "stable",
        preserve_face: true,
        generation_mode: "stable",
      });
      setNotice("任务已提交");
      await fetchTasks();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "创建任务失败");
    } finally {
      setCreating(false);
    }
  }

  async function toggleDeliverable(task: Task) {
    if (task.status !== "completed" || !task.output_files?.final) {
      setNotice("只有已完成的最终图可以标记为可交付");
      return;
    }

    setMarkingTaskId(task.task_id);
    try {
      const updated = await api.markDeliverable(task.task_id, !task.is_deliverable);
      setTasks((current) => current.map((item) => (item.task_id === updated.task_id ? updated : item)));
      setPreviewTask((current) => (current?.task_id === updated.task_id ? updated : current));
      setNotice(updated.is_deliverable ? "已加入交付包" : "已移出交付包");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "更新交付标记失败");
    } finally {
      setMarkingTaskId(null);
    }
  }

  async function deleteTask(task: Task) {
    if (task.status === "processing") {
      setNotice("生成中的任务暂不能删除");
      return;
    }
    if (!window.confirm(`确定删除「${taskDisplayName(task)}」吗？`)) return;

    setDeletingTaskId(task.task_id);
    try {
      await api.deleteTask(task.task_id);
      setTasks((current) => current.filter((item) => item.task_id !== task.task_id));
      setPreviewTask((current) => (current?.task_id === task.task_id ? null : current));
      setNotice("任务已删除");
      await fetchTasks();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除任务失败");
    } finally {
      setDeletingTaskId(null);
    }
  }

  async function deleteAsset(slot: UploadSlot, asset: LibraryAsset) {
    if (!window.confirm(`确定删除素材「${shortFileName(asset.filename)}」吗？`)) return;

    setDeletingAssetId(asset.asset_id);
    try {
      await api.deleteAsset(asset.asset_id);
      setAssets((current) => current.filter((item) => item.asset_id !== asset.asset_id));
      setUploads((current) => {
        if (current[slot].assetId !== asset.asset_id) return current;
        return { ...current, [slot]: emptyUpload };
      });
      setNotice("素材已从素材库删除");
      await fetchAssets();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除素材失败");
    } finally {
      setDeletingAssetId(null);
    }
  }

  async function exportDeliverables() {
    if (deliverableCount === 0) return;
    setExporting(true);
    try {
      const { blob, filename } = await api.exportDeliverables();
      downloadBlob(blob, filename);
      setNotice(`已导出 ${deliverableCount} 张可交付图`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "导出交付包失败");
    } finally {
      setExporting(false);
    }
  }

  return (
    <main className="product-shell">
      <header className="product-topbar">
        <div className="product-brand">婚纱 AI 交付台</div>
        <div className="product-mode-tags" aria-label="当前模式">
          <span>稳定演示模式</span>
          <span>保脸优先</span>
          <span>1K 高清</span>
        </div>
        <div className="product-top-actions">
          <span className={`product-health ${health}`}>
            {health === "ok" ? <Wifi size={14} /> : <WifiOff size={14} />}
            {health === "ok" ? "后端在线" : health === "down" ? "后端离线" : "检测中"}
          </span>
          <button className="product-quiet-button" onClick={onOpenTestStudio} type="button">
            进入测试台
          </button>
        </div>
      </header>

      <section className="product-layout">
        <aside className="product-left-panel" aria-label="素材选择">
          <MaterialPicker
            assets={modelAssets}
            deletingAssetId={deletingAssetId}
            state={uploads.model}
            slot="model"
            onDelete={deleteAsset}
            onFile={handleUpload}
            onSelect={selectAsset}
          />
          <MaterialPicker
            assets={dressAssets}
            deletingAssetId={deletingAssetId}
            state={uploads.dress}
            slot="dress"
            onDelete={deleteAsset}
            onFile={handleUpload}
            onSelect={selectAsset}
          />
        </aside>

        <section className="product-stage" aria-label="成片预览">
          <div className="product-stage-head">
            <div>
              <span>成片预览</span>
              <h1>{heroTask ? taskDisplayName(heroTask) : "等待生成第一张成片"}</h1>
            </div>
            <button className="product-icon-button" onClick={fetchTasks} type="button" title="刷新任务">
              <RefreshCw size={17} />
            </button>
          </div>

          <div className="product-preview-frame">
            {heroTask ? (
              <ImageWithFallback
                alt="最新最终交付图"
                fallback="最终图无法读取"
                src={`/api/task/${heroTask.task_id}/result`}
              />
            ) : (
              <div className="product-empty-preview">
                <span>暗房预览</span>
                <strong>选择模特和婚纱后开始生成</strong>
                <small>生成完成后，最终交付图会显示在这里。</small>
              </div>
            )}
          </div>

          <div className="product-source-strip">
            <SourcePreview label="模特原图" state={uploads.model} />
            <SourcePreview label="婚纱款式" state={uploads.dress} />
            <div className="product-source-note">
              <ShieldCheck size={16} />
              <span>当前固定为保脸优先和保款式稳定，适合老板演示。</span>
            </div>
          </div>

          <div className="product-scene-bar" aria-label="场景选择">
            {scenes.map((item) => (
              <button
                className={scene === item.value ? "active" : ""}
                key={item.value}
                onClick={() => setScene(item.value)}
                type="button"
              >
                <strong>{item.label}</strong>
                <span>{item.detail}</span>
              </button>
            ))}
          </div>

          <div className="product-generate-panel">
            <button className="product-generate-button" disabled={!canGenerate} onClick={createTask} type="button">
              {creating || activeTask ? <Loader2 size={18} className="spin" /> : <WandSparkles size={18} />}
              {activeTask ? "生成中" : "开始生成"}
            </button>
            <div className="product-generate-meta">
              <span>{generateHint}</span>
              {(activeTask || creating) && (
                <div className="product-progress-track">
                  <span style={{ width: `${Math.max(6, Math.min(activeTask?.progress || 8, 100))}%` }} />
                </div>
              )}
              {failedTask && (
                <p className="product-inline-error">最近失败：{taskFailureMessage(failedTask)}</p>
              )}
            </div>
          </div>
        </section>

        <aside className="product-right-panel" aria-label="任务管理与交付">
          <div className="product-delivery-head">
            <div>
              <span>任务管理与交付</span>
              <strong>{deliverableCount} 张可交付</strong>
            </div>
            <PackageCheck size={21} />
          </div>

          <div className="product-task-list">
            {recentTasks.length === 0 ? (
              <div className="product-empty-task">还没有任务，先从左侧选择素材。</div>
            ) : (
              recentTasks.map((task) => (
                <TaskCard
                  deleting={deletingTaskId === task.task_id}
                  key={task.task_id}
                  marking={markingTaskId === task.task_id}
                  task={task}
                  onDelete={deleteTask}
                  onOpen={setPreviewTask}
                  onToggleDeliverable={toggleDeliverable}
                />
              ))
            )}
          </div>

          <button className="product-view-all" disabled={tasks.length <= 5} onClick={() => setDrawerOpen(true)} type="button">
            查看全部任务
          </button>

          <button
            className="product-export-button"
            disabled={deliverableCount === 0 || exporting}
            onClick={exportDeliverables}
            type="button"
          >
            {exporting ? <Loader2 size={17} className="spin" /> : <ArrowDownToLine size={17} />}
            导出交付包
          </button>
          <p className="product-export-note">交付包包含全部可交付最终图和选片清单。</p>
        </aside>
      </section>

      {drawerOpen && (
        <div className="product-drawer-backdrop" role="dialog" aria-modal="true">
          <aside className="product-drawer">
            <div className="product-drawer-head">
              <div>
                <span>全部任务</span>
                <strong>{tasks.length} 条记录</strong>
              </div>
              <button className="product-icon-button" onClick={() => setDrawerOpen(false)} type="button" aria-label="关闭">
                <X size={18} />
              </button>
            </div>
            <div className="product-drawer-list">
              {tasks.map((task) => (
                <TaskCard
                  deleting={deletingTaskId === task.task_id}
                  key={task.task_id}
                  marking={markingTaskId === task.task_id}
                  task={task}
                  onDelete={deleteTask}
                  onOpen={setPreviewTask}
                  onToggleDeliverable={toggleDeliverable}
                />
              ))}
            </div>
          </aside>
        </div>
      )}

      {previewTask && (
        <TaskPreviewDialog
          deleting={deletingTaskId === previewTask.task_id}
          marking={markingTaskId === previewTask.task_id}
          task={previewTask}
          onClose={() => setPreviewTask(null)}
          onDelete={deleteTask}
          onToggleDeliverable={toggleDeliverable}
        />
      )}

      {notice && (
        <button className="product-notice" onClick={() => setNotice(null)} type="button">
          {notice}
        </button>
      )}
    </main>
  );
}

function MaterialPicker({
  assets,
  deletingAssetId,
  onDelete,
  onFile,
  onSelect,
  slot,
  state,
}: {
  assets: LibraryAsset[];
  deletingAssetId: string | null;
  onDelete: (slot: UploadSlot, asset: LibraryAsset) => void;
  onFile: (slot: UploadSlot, file: File) => void;
  onSelect: (slot: UploadSlot, asset: LibraryAsset) => void;
  slot: UploadSlot;
  state: UploadState;
}) {
  function handleInput(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) onFile(slot, file);
    event.target.value = "";
  }

  return (
    <section className="product-material-block">
      <div className="product-material-head">
        <div>
          <strong>{slotCopy[slot].title}</strong>
          <span>{slotCopy[slot].hint}</span>
        </div>
        <label className="product-upload-button">
          <UploadCloud size={15} />
          上传
          <input accept="image/*" onChange={handleInput} type="file" />
        </label>
      </div>

      <div className="product-selected-material">
        {state.previewUrl ? (
          <ImageWithFallback alt={slotCopy[slot].title} fallback="素材无法读取" src={state.previewUrl} />
        ) : (
          <div className="product-material-empty">
            <ImagePlus size={22} />
            <span>选择素材或上传新图</span>
          </div>
        )}
        <small title={state.filename || ""}>
          {state.uploading ? "上传中..." : shortFileName(state.filename)}
        </small>
      </div>

      <div className="product-thumb-grid">
        {assets.length === 0 ? (
          <div className="product-thumb-empty">暂无素材</div>
        ) : (
          assets.map((asset) => (
            <div className="product-thumb-item" key={asset.asset_id}>
              <button
                className={state.assetId === asset.asset_id ? "active" : ""}
                onClick={() => onSelect(slot, asset)}
                title={asset.filename}
                type="button"
              >
                <ImageWithFallback alt={asset.filename} fallback="无法读取" src={asset.image_url} />
              </button>
              <button
                className="product-thumb-delete"
                disabled={deletingAssetId === asset.asset_id}
                onClick={() => onDelete(slot, asset)}
                title="删除素材"
                type="button"
              >
                {deletingAssetId === asset.asset_id ? <Loader2 size={12} className="spin" /> : <Trash2 size={12} />}
              </button>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function SourcePreview({ label, state }: { label: string; state: UploadState }) {
  return (
    <div className="product-source-preview">
      <span>{label}</span>
      <div>
        {state.previewUrl ? (
          <ImageWithFallback alt={label} fallback="图片无法读取" src={state.previewUrl} />
        ) : (
          <small>未选择</small>
        )}
      </div>
    </div>
  );
}

function TaskCard({
  deleting,
  marking,
  onDelete,
  onOpen,
  onToggleDeliverable,
  task,
}: {
  deleting: boolean;
  marking: boolean;
  onDelete: (task: Task) => void;
  onOpen: (task: Task) => void;
  onToggleDeliverable: (task: Task) => void;
  task: Task;
}) {
  const canUseFinal = task.status === "completed" && task.output_files?.final;
  return (
    <article className={`product-task-card ${task.status}`}>
      <div className="product-task-topline">
        <span className={`product-status ${task.status}`}>
          {statusIcon(task.status)}
          {statusCopy[task.status]}
        </span>
        <span>{Math.round(task.progress)}%</span>
      </div>
      <strong title={taskDisplayName(task)}>{taskDisplayName(task)}</strong>
      <div className="product-task-meta">
        <span>{taskSceneLabel(task)}</span>
        <span>{formatTime(task.created_at)}</span>
      </div>
      <div className="product-progress-track">
        <span style={{ width: `${Math.max(4, Math.min(task.progress, 100))}%` }} />
      </div>
      {task.status === "failed" && <p className="product-task-error">{taskFailureMessage(task)}</p>}
      <div className="product-task-actions">
        <button onClick={() => onOpen(task)} type="button" title={canUseFinal ? "查看成片" : "查看任务详情"}>
          <Eye size={15} />
          查看
        </button>
        {canUseFinal && (
          <>
          <a href={`/api/task/${task.task_id}/result`} download title="下载成片原图">
            <ArrowDownToLine size={15} />
            下载
          </a>
          <button
            className={task.is_deliverable ? "active" : ""}
            disabled={marking}
            onClick={() => onToggleDeliverable(task)}
            title={task.is_deliverable ? "取消可交付" : "标记可交付"}
            type="button"
          >
            {marking ? <Loader2 size={15} className="spin" /> : <Star size={15} />}
            {task.is_deliverable ? "已交付" : "可交付"}
          </button>
          </>
        )}
      </div>
      <button
        className="product-delete-task"
        disabled={deleting || task.status === "processing"}
        onClick={() => onDelete(task)}
        title={task.status === "processing" ? "生成中暂不能删除" : "删除任务"}
        type="button"
      >
        {deleting ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />}
      </button>
    </article>
  );
}

function TaskPreviewDialog({
  deleting,
  marking,
  onClose,
  onDelete,
  onToggleDeliverable,
  task,
}: {
  deleting: boolean;
  marking: boolean;
  onClose: () => void;
  onDelete: (task: Task) => void;
  onToggleDeliverable: (task: Task) => void;
  task: Task;
}) {
  const canUseFinal = task.status === "completed" && task.output_files?.final;
  const [review, setReview] = useState<QualityReview | null>(null);
  const [scores, setScores] = useState({
    face_score: 4,
    dress_score: 4,
    pose_score: 3,
    background_score: 4,
  });
  const [notes, setNotes] = useState("");
  const [reviewMessage, setReviewMessage] = useState<string | null>(null);
  const [savingReview, setSavingReview] = useState(false);

  useEffect(() => {
    let active = true;
    setReview(null);
    setReviewMessage(null);
    api
      .getQualityReview(task.task_id)
      .then((nextReview) => {
        if (!active) return;
        if (nextReview) {
          setReview(nextReview);
          setScores({
            face_score: nextReview.face_score,
            dress_score: nextReview.dress_score,
            pose_score: nextReview.pose_score,
            background_score: nextReview.background_score,
          });
          setNotes(nextReview.notes || "");
        } else {
          setScores({
            face_score: 4,
            dress_score: 4,
            pose_score: task.pose_mode === "experimental" ? 3 : 4,
            background_score: 4,
          });
          setNotes("");
        }
      })
      .catch((error) => {
        if (active) setReviewMessage(error instanceof Error ? error.message : "评分读取失败");
      });

    return () => {
      active = false;
    };
  }, [task.pose_mode, task.task_id]);

  async function saveQualityReview() {
    setSavingReview(true);
    setReviewMessage(null);
    try {
      const saved = await api.saveQualityReview(task.task_id, {
        ...scores,
        notes,
        reviewer: "demo",
      });
      setReview(saved);
      setReviewMessage(saved.pass_result ? "已保存：可进入演示候选" : "已保存：暂不建议演示");
    } catch (error) {
      setReviewMessage(error instanceof Error ? error.message : "评分保存失败");
    } finally {
      setSavingReview(false);
    }
  }

  return (
    <div className="product-preview-backdrop" role="dialog" aria-modal="true">
      <section className="product-preview-dialog">
        <div className="product-preview-dialog-head">
          <div>
            <span className={`product-status ${task.status}`}>
              {statusIcon(task.status)}
              {statusCopy[task.status]}
            </span>
            <h2>{taskDisplayName(task)}</h2>
            <p>{taskSceneLabel(task)} / {task.resolution.toUpperCase()} / {Math.round(task.progress)}%</p>
          </div>
          <button className="product-icon-button" onClick={onClose} type="button" aria-label="关闭预览">
            <X size={18} />
          </button>
        </div>

        <div className="product-preview-dialog-image">
          {canUseFinal ? (
            <ImageWithFallback
              alt="最终成片"
              fallback="最终图无法读取"
              src={`/api/task/${task.task_id}/result`}
            />
          ) : task.status === "failed" ? (
            <div className="product-preview-error">
              <AlertCircle size={24} />
              <strong>生成没有完成</strong>
              <span>{taskFailureMessage(task)}</span>
            </div>
          ) : (
            <div className="product-preview-error">
              <Loader2 size={24} className={task.status === "processing" ? "spin" : ""} />
              <strong>{task.current_step_label || statusCopy[task.status]}</strong>
              <span>生成完成后这里会显示最终成片。</span>
            </div>
          )}
        </div>

        <div className="product-quality-panel">
          <div className="product-quality-head">
            <div>
              <strong>质量评分</strong>
              <span>{review ? `上次评分 ${review.overall_score}/5` : "用于筛选演示候选图"}</span>
            </div>
            {review && (
              <span className={review.pass_result ? "product-quality-pass" : "product-quality-fail"}>
                {review.pass_result ? "可演示" : "待优化"}
              </span>
            )}
          </div>
          <div className="product-quality-grid">
            {qualityScoreLabels.map((item) => (
              <label key={item.key}>
                <span>{item.label}</span>
                <select
                  value={scores[item.key]}
                  onChange={(event) =>
                    setScores((current) => ({ ...current, [item.key]: Number(event.target.value) }))
                  }
                >
                  {[1, 2, 3, 4, 5].map((score) => (
                    <option key={score} value={score}>
                      {score} 分
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          <textarea
            className="product-quality-notes"
            maxLength={240}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="记录问题：例如脸像贴上去、裙摆变短、背景遮挡、动作不稳。"
            value={notes}
          />
          <div className="product-quality-actions">
            <button disabled={savingReview} onClick={saveQualityReview} type="button">
              {savingReview ? <Loader2 size={15} className="spin" /> : <CheckCircle2 size={15} />}
              保存评分
            </button>
            {reviewMessage && <span>{reviewMessage}</span>}
          </div>
        </div>

        <div className="product-preview-dialog-actions">
          {canUseFinal && (
            <a className="product-preview-download" href={`/api/task/${task.task_id}/result`} download>
              <ArrowDownToLine size={16} />
              下载原图
            </a>
          )}
          <button
            className={task.is_deliverable ? "product-preview-deliverable active" : "product-preview-deliverable"}
            disabled={marking || !canUseFinal}
            onClick={() => onToggleDeliverable(task)}
            type="button"
          >
            {marking ? <Loader2 size={16} className="spin" /> : <Star size={16} />}
            {task.is_deliverable ? "取消可交付" : "标记可交付"}
          </button>
          <button
            className="product-preview-delete"
            disabled={deleting || task.status === "processing"}
            onClick={() => onDelete(task)}
            type="button"
          >
            {deleting ? <Loader2 size={16} className="spin" /> : <Trash2 size={16} />}
            删除任务
          </button>
        </div>
      </section>
    </div>
  );
}

function ImageWithFallback({
  alt,
  fallback,
  src,
}: {
  alt: string;
  fallback: string;
  src: string;
}) {
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [src]);

  if (failed) {
    return (
      <div className="product-image-fallback">
        <AlertCircle size={18} />
        <span>{fallback}</span>
      </div>
    );
  }

  return <img alt={alt} src={src} onError={() => setFailed(true)} />;
}
