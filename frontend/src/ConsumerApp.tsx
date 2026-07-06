import {
  ArrowDownToLine,
  Camera,
  Check,
  ChevronRight,
  Download,
  Eye,
  HelpCircle,
  ImagePlus,
  Loader2,
  LockKeyhole,
  RefreshCw,
  Sparkles,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { ChangeEvent, CSSProperties, useCallback, useEffect, useMemo, useState } from "react";

type ConsumerRoute = "tryon" | "works" | "help";
type AssetCategory = "model" | "dress" | "face" | "pose_reference";
type TaskStatus = "pending" | "processing" | "completed" | "failed";
type StepKey = "upload" | "dress" | "generate" | "save";

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
  output_files: Record<string, boolean>;
  error_message: string;
  created_at: string;
};

type UploadState = {
  fileId: string | null;
  assetId: string | null;
  previewUrl: string | null;
  filename: string | null;
  uploading: boolean;
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

type ConsumerAppProps = {
  route: ConsumerRoute;
  onNavigate: (route: ConsumerRoute) => void;
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
    value: "教堂",
    label: "教堂",
    prompt: "教堂婚礼场景，彩色玻璃窗，柔和自然光，真实婚纱摄影质感，保留人物脸部特征和婚纱款式",
  },
  {
    value: "花园",
    label: "花园",
    prompt: "欧式花园婚纱摄影，浅色花艺背景，柔光，真实摄影质感，保留人物脸部特征和婚纱款式",
  },
  {
    value: "海边",
    label: "海边",
    prompt: "海边夕阳婚纱摄影，柔和逆光，真实摄影质感，保留人物脸部特征和婚纱款式",
  },
  {
    value: "影棚",
    label: "影棚",
    prompt: "高级影棚婚纱摄影，干净浅色背景，专业布光，真实摄影质感，保留人物脸部特征和婚纱款式",
  },
];

const poses = ["保持原姿势", "正面站姿", "自然站姿"];

const dressNames = [
  "缎面拖尾",
  "蕾丝鱼尾",
  "法式轻纱",
  "宫廷大摆",
  "一字领缎面",
  "简约蕾丝",
  "花朵轻纱",
  "极简缎面",
];

const steps: Array<{ key: StepKey; label: string }> = [
  { key: "upload", label: "上传照片" },
  { key: "dress", label: "选择婚纱" },
  { key: "generate", label: "生成试穿" },
  { key: "save", label: "保存作品" },
];

const stepOrder: Record<StepKey, number> = {
  upload: 0,
  dress: 1,
  generate: 2,
  save: 3,
};

async function readApiJson<T>(response: Response, fallbackMessage: string): Promise<T> {
  const text = await response.text();
  let data: unknown = {};

  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      throw new Error(response.ok ? `${fallbackMessage}：服务返回内容无法读取` : text);
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
  async assets(category?: AssetCategory) {
    const query = category ? `?category=${encodeURIComponent(category)}` : "";
    const response = await fetch(`/api/assets${query}`);
    const data = await readApiJson<{ assets: LibraryAsset[] }>(response, "素材读取失败");
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
    return readApiJson<{ task_id: string }>(response, "生成请求没有提交成功");
  },
  async tasks() {
    const response = await fetch("/api/tasks?page=1&page_size=60");
    const data = await readApiJson<{ tasks: Task[] }>(response, "作品读取失败");
    return data.tasks;
  },
  async deleteTask(taskId: string) {
    const response = await fetch(`/api/task/${taskId}`, { method: "DELETE" });
    return readApiJson<{ success: boolean }>(response, "删除失败");
  },
};

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function dressTitle(asset: LibraryAsset | null, assets: LibraryAsset[]) {
  if (!asset) return "未选择";
  const index = Math.max(0, assets.findIndex((item) => item.asset_id === asset.asset_id));
  return dressNames[index % dressNames.length];
}

function workTitle(task: Task) {
  if (task.name?.includes("/")) {
    return task.name.split("/").map((item) => item.trim()).filter(Boolean).join(" / ");
  }
  return task.scene ? `婚纱试穿 / ${task.scene}` : "婚纱试穿照";
}

function isCompletedWork(task: Task) {
  return task.status === "completed" && Boolean(task.output_files?.final);
}

function ImageWithFallback({ alt, className, src }: { alt: string; className?: string; src: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div className={`consumer-image-fallback ${className || ""}`}>
        <ImagePlus size={22} />
        <span>图片暂时无法显示</span>
      </div>
    );
  }
  return <img alt={alt} className={className} src={src} onError={() => setFailed(true)} />;
}

export function ConsumerApp({ route, onNavigate }: ConsumerAppProps) {
  const [step, setStep] = useState<StepKey>("upload");
  const [photo, setPhoto] = useState<UploadState>(emptyUpload);
  const [selectedDress, setSelectedDress] = useState<LibraryAsset | null>(null);
  const [modelAssets, setModelAssets] = useState<LibraryAsset[]>([]);
  const [dressAssets, setDressAssets] = useState<LibraryAsset[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [selectedScene, setSelectedScene] = useState(scenes[0].value);
  const [selectedPose, setSelectedPose] = useState(poses[0]);
  const [notice, setNotice] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const selectedSceneItem = scenes.find((item) => item.value === selectedScene) || scenes[0];
  const completedWorks = useMemo(() => tasks.filter(isCompletedWork), [tasks]);
  const activeTask = useMemo(
    () => tasks.find((task) => task.task_id === activeTaskId) || null,
    [activeTaskId, tasks],
  );
  const latestWork = completedWorks[0] || null;
  const resultTask = activeTask && isCompletedWork(activeTask) ? activeTask : latestWork;
  const selectedDressName = dressTitle(selectedDress, dressAssets);

  const fetchAssets = useCallback(async () => {
    const [models, dresses] = await Promise.all([api.assets("model"), api.assets("dress")]);
    setModelAssets(models);
    setDressAssets(dresses);
    setSelectedDress((current) => current || dresses[0] || null);
  }, []);

  const fetchTasks = useCallback(async () => {
    const nextTasks = await api.tasks();
    setTasks(nextTasks);
  }, []);

  useEffect(() => {
    fetchAssets().catch((error) => setNotice(error instanceof Error ? error.message : "素材读取失败"));
    fetchTasks().catch(() => undefined);
  }, [fetchAssets, fetchTasks]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      fetchTasks().catch(() => undefined);
    }, activeTaskId ? 2500 : 8000);
    return () => window.clearInterval(timer);
  }, [activeTaskId, fetchTasks]);

  useEffect(() => {
    if (!activeTask) return;
    if (activeTask.status === "completed" && activeTask.output_files?.final) {
      setStep("save");
      return;
    }
    if (activeTask.status === "failed") {
      setNotice("这次没有生成成功，请换张更清晰的照片或重新生成。");
      setStep("dress");
    }
  }, [activeTask]);

  async function handlePhotoInput(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setNotice("请选择图片文件");
      return;
    }

    const previewUrl = URL.createObjectURL(file);
    setPhoto({
      fileId: null,
      assetId: null,
      previewUrl,
      filename: file.name,
      uploading: true,
    });

    try {
      const { fileId, asset } = await api.upload(file, "model");
      if (!fileId) throw new Error("上传失败，请重新选择照片");
      setPhoto({
        fileId,
        assetId: asset?.asset_id || null,
        previewUrl,
        filename: file.name,
        uploading: false,
      });
      await fetchAssets();
    } catch (error) {
      URL.revokeObjectURL(previewUrl);
      setPhoto(emptyUpload);
      setNotice(error instanceof Error ? error.message : "上传失败");
    }
  }

  function useSamplePhoto(asset: LibraryAsset) {
    setPhoto({
      fileId: asset.file_id,
      assetId: asset.asset_id,
      previewUrl: asset.image_url,
      filename: asset.filename,
      uploading: false,
    });
  }

  async function startGeneration() {
    if (!photo.fileId || !selectedDress) {
      setNotice("请先上传照片并选择婚纱");
      return;
    }
    setCreating(true);
    setNotice(null);
    setStep("generate");
    try {
      const created = await api.createTask({
        name: `${selectedDressName} / ${selectedSceneItem.label}`,
        model_file: photo.fileId,
        dress_file: selectedDress.file_id,
        clothing_type: "wedding_gown",
        scene: selectedSceneItem.value,
        scene_prompt: selectedSceneItem.prompt,
        resolution: "1k",
        face_swap: false,
        pose: selectedPose,
        pose_mode: "stable",
        preserve_face: true,
        generation_mode: "stable",
      });
      setActiveTaskId(created.task_id);
      await fetchTasks();
    } catch (error) {
      setStep("dress");
      setNotice(error instanceof Error ? error.message : "生成请求没有提交成功");
    } finally {
      setCreating(false);
    }
  }

  async function deleteWork(task: Task) {
    if (!window.confirm("确定删除这张作品吗？")) return;
    setDeletingId(task.task_id);
    try {
      await api.deleteTask(task.task_id);
      setTasks((current) => current.filter((item) => item.task_id !== task.task_id));
      if (activeTaskId === task.task_id) setActiveTaskId(null);
      setNotice("作品已删除");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  }

  function resetTryOn() {
    setActiveTaskId(null);
    setStep(photo.fileId ? "dress" : "upload");
    onNavigate("tryon");
  }

  return (
    <main className="consumer-shell">
      <ConsumerNav route={route} onNavigate={onNavigate} onStart={resetTryOn} />
      {route === "works" ? (
        <WorksPage
          deletingId={deletingId}
          works={completedWorks}
          onDelete={deleteWork}
          onStart={resetTryOn}
        />
      ) : route === "help" ? (
        <HelpPage onStart={resetTryOn} />
      ) : (
        <>
          <StepProgress step={step} />
          {step === "upload" && (
            <UploadStep
              modelAssets={modelAssets}
              photo={photo}
              onFile={handlePhotoInput}
              onNext={() => setStep("dress")}
              onSample={useSamplePhoto}
            />
          )}
          {step === "dress" && (
            <DressStep
              dressAssets={dressAssets}
              photo={photo}
              selectedDress={selectedDress}
              selectedDressName={selectedDressName}
              selectedPose={selectedPose}
              selectedScene={selectedScene}
              onBack={() => setStep("upload")}
              onDress={setSelectedDress}
              onGenerate={startGeneration}
              onPose={setSelectedPose}
              onScene={setSelectedScene}
            />
          )}
          {step === "generate" && (
            <GenerateStep
              activeTask={activeTask}
              creating={creating}
              photo={photo}
              selectedDress={selectedDress}
              selectedDressName={selectedDressName}
              selectedPose={selectedPose}
              selectedScene={selectedSceneItem.label}
              onCancel={() => setStep("dress")}
            />
          )}
          {step === "save" && (
            <SaveStep
              photo={photo}
              resultTask={resultTask}
              selectedDress={selectedDress}
              selectedDressName={selectedDressName}
              selectedScene={selectedSceneItem.label}
              onStart={resetTryOn}
              onWorks={() => onNavigate("works")}
            />
          )}
        </>
      )}

      {notice && (
        <button className="consumer-toast" onClick={() => setNotice(null)} type="button">
          {notice}
        </button>
      )}
    </main>
  );
}

function ConsumerNav({
  onNavigate,
  onStart,
  route,
}: {
  onNavigate: (route: ConsumerRoute) => void;
  onStart: () => void;
  route: ConsumerRoute;
}) {
  return (
    <header className="consumer-nav">
      <button className="consumer-brand" onClick={onStart} type="button">
        <span className="consumer-brand-mark" aria-hidden="true" />
        <strong>婚纱 AI 试穿</strong>
      </button>
      <nav aria-label="主导航">
        <button className={route === "tryon" ? "active" : ""} onClick={onStart} type="button">
          开始试穿
        </button>
        <button className={route === "works" ? "active" : ""} onClick={() => onNavigate("works")} type="button">
          我的作品
        </button>
        <button className={route === "help" ? "active" : ""} onClick={() => onNavigate("help")} type="button">
          帮助
        </button>
      </nav>
    </header>
  );
}

function StepProgress({ step }: { step: StepKey }) {
  const activeIndex = stepOrder[step];
  return (
    <ol className="consumer-steps" aria-label="试穿流程">
      {steps.map((item, index) => {
        const done = index < activeIndex;
        const active = index === activeIndex;
        return (
          <li className={active ? "active" : done ? "done" : ""} key={item.key}>
            <span>{done ? <Check size={16} /> : index + 1}</span>
            <strong>{item.label}</strong>
          </li>
        );
      })}
    </ol>
  );
}

function UploadStep({
  modelAssets,
  onFile,
  onNext,
  onSample,
  photo,
}: {
  modelAssets: LibraryAsset[];
  onFile: (event: ChangeEvent<HTMLInputElement>) => void;
  onNext: () => void;
  onSample: (asset: LibraryAsset) => void;
  photo: UploadState;
}) {
  return (
    <section className="consumer-upload-page">
      <div className="consumer-upload-main">
        <div className="consumer-section-title">
          <span>第一步</span>
          <h1>上传你的照片</h1>
          <p>建议上传正面全身照，光线清晰时试穿效果更自然。</p>
        </div>

        <label className={photo.previewUrl ? "consumer-upload-card has-image" : "consumer-upload-card"}>
          {photo.previewUrl ? (
            <ImageWithFallback alt="你的照片" src={photo.previewUrl} />
          ) : (
            <div>
              <UploadCloud size={34} />
              <strong>选择照片</strong>
              <span>支持 JPG / PNG</span>
            </div>
          )}
          <input accept="image/*" onChange={onFile} type="file" />
        </label>

        <div className="consumer-upload-actions">
          <label className="consumer-secondary-upload">
            <UploadCloud size={16} />
            {photo.previewUrl ? "重新上传" : "选择照片"}
            <input accept="image/*" onChange={onFile} type="file" />
          </label>
          <button disabled={!photo.fileId || photo.uploading} onClick={onNext} type="button">
            {photo.uploading ? <Loader2 className="spin" size={17} /> : <ChevronRight size={17} />}
            下一步：选择婚纱
          </button>
        </div>

        {modelAssets.length > 0 && (
          <div className="consumer-sample-strip">
            <span>没有合适照片？先用示例体验</span>
            <div>
              {modelAssets.slice(0, 4).map((asset) => (
                <button key={asset.asset_id} onClick={() => onSample(asset)} type="button">
                  <ImageWithFallback alt="示例照片" src={asset.image_url} />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <aside className="consumer-help-panel">
        <h2>拍照建议</h2>
        <div className="consumer-tip-list">
          <TipCard title="正面全身" text="尽量露出完整身体轮廓，方便婚纱自然贴合。" />
          <TipCard title="光线清晰" text="避免太暗、逆光或严重模糊的照片。" />
          <TipCard title="背景简洁" text="干净背景更利于生成稳定的试穿效果。" />
        </div>
        <div className="consumer-privacy-note">
          <LockKeyhole size={17} />
          <span>照片仅用于生成试穿效果，可随时删除。</span>
        </div>
      </aside>
    </section>
  );
}

function TipCard({ text, title }: { text: string; title: string }) {
  return (
    <article>
      <span aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{text}</p>
      </div>
    </article>
  );
}

function DressStep({
  dressAssets,
  onBack,
  onDress,
  onGenerate,
  onPose,
  onScene,
  photo,
  selectedDress,
  selectedDressName,
  selectedPose,
  selectedScene,
}: {
  dressAssets: LibraryAsset[];
  onBack: () => void;
  onDress: (asset: LibraryAsset) => void;
  onGenerate: () => void;
  onPose: (pose: string) => void;
  onScene: (scene: string) => void;
  photo: UploadState;
  selectedDress: LibraryAsset | null;
  selectedDressName: string;
  selectedPose: string;
  selectedScene: string;
}) {
  return (
    <section className="consumer-dress-page">
      <aside className="consumer-choice-side">
        <div className="consumer-mini-card">
          <div className="consumer-mini-head">
            <strong>你的照片</strong>
            <Check size={17} />
          </div>
          {photo.previewUrl ? (
            <ImageWithFallback alt="你的照片" src={photo.previewUrl} />
          ) : (
            <div className="consumer-image-fallback">未上传</div>
          )}
          <button onClick={onBack} type="button">
            重新上传
          </button>
        </div>

        <div className="consumer-settings-card">
          <strong>更多设置</strong>
          <label>
            <span>场景</span>
            <select value={selectedScene} onChange={(event) => onScene(event.target.value)}>
              {scenes.map((scene) => (
                <option key={scene.value} value={scene.value}>
                  {scene.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>姿势</span>
            <select value={selectedPose} onChange={(event) => onPose(event.target.value)}>
              {poses.map((pose) => (
                <option key={pose} value={pose}>
                  {pose}
                </option>
              ))}
            </select>
          </label>
        </div>
      </aside>

      <div className="consumer-dress-main">
        <div className="consumer-section-title">
          <span>第二步</span>
          <h1>选择喜欢的婚纱</h1>
          <p>选择一款婚纱，系统会生成试穿效果。</p>
        </div>
        <div className="consumer-dress-grid">
          {dressAssets.length === 0 ? (
            <div className="consumer-empty-card">暂无婚纱款式，请先上传婚纱素材。</div>
          ) : (
            dressAssets.slice(0, 8).map((asset, index) => {
              const active = selectedDress?.asset_id === asset.asset_id;
              return (
                <button
                  className={active ? "active" : ""}
                  key={asset.asset_id}
                  onClick={() => onDress(asset)}
                  type="button"
                >
                  <ImageWithFallback alt={dressNames[index % dressNames.length]} src={asset.image_url} />
                  <span>{dressNames[index % dressNames.length]}</span>
                  {active && <em>已选择</em>}
                </button>
              );
            })
          )}
        </div>
      </div>

      <aside className="consumer-preview-side">
        <h2>试穿预览</h2>
        <div className="consumer-preview-frame">
          {photo.previewUrl ? (
            <ImageWithFallback alt="试穿预览" src={photo.previewUrl} />
          ) : (
            <div className="consumer-preview-empty">上传照片后查看预览</div>
          )}
        </div>
        <p>
          已选择：你的照片 + {selectedDressName} + {selectedScene}
        </p>
        <button disabled={!photo.fileId || !selectedDress} onClick={onGenerate} type="button">
          <Sparkles size={18} />
          生成试穿照
        </button>
        <button className="ghost" type="button">
          先看看示例
        </button>
      </aside>
    </section>
  );
}

function GenerateStep({
  activeTask,
  creating,
  onCancel,
  photo,
  selectedDress,
  selectedDressName,
  selectedPose,
  selectedScene,
}: {
  activeTask: Task | null;
  creating: boolean;
  onCancel: () => void;
  photo: UploadState;
  selectedDress: LibraryAsset | null;
  selectedDressName: string;
  selectedPose: string;
  selectedScene: string;
}) {
  const progress = Math.max(8, Math.min(activeTask?.progress || (creating ? 12 : 68), 99));
  return (
    <section className="consumer-generating-page">
      <aside className="consumer-selected-panel">
        <h2>已选择</h2>
        <SelectionCard image={photo.previewUrl} title="你的照片" />
        <SelectionCard image={selectedDress?.image_url || null} title={`婚纱：${selectedDressName}`} />
        <SelectionCard title={`场景：${selectedScene}`} text={`姿势：${selectedPose}`} />
        <button onClick={onCancel} type="button">
          返回修改
        </button>
      </aside>

      <div className="consumer-generating-main">
        <div className="consumer-section-title centered">
          <span>第三步</span>
          <h1>正在生成你的试穿照</h1>
          <p>正在合成婚纱效果，请稍等片刻。</p>
        </div>
        <div className="consumer-loading-frame">
          <div className="consumer-progress-ring" style={{ "--progress": `${progress}%` } as CSSProperties}>
            <span>{Math.round(progress)}%</span>
          </div>
          <p>通常需要几十秒，请不要关闭页面。</p>
        </div>
        <div className="consumer-progress-line">
          <span style={{ width: `${progress}%` }} />
        </div>
      </div>

      <aside className="consumer-after-panel">
        <h2>生成完成后</h2>
        <ul>
          <li>
            <Check size={16} />
            查看试穿效果
          </li>
          <li>
            <Download size={16} />
            保存高清图片
          </li>
          <li>
            <Camera size={16} />
            加入我的作品
          </li>
        </ul>
        <button disabled type="button">
          保存作品
        </button>
      </aside>
    </section>
  );
}

function SelectionCard({ image, text, title }: { image?: string | null; text?: string; title: string }) {
  return (
    <article className="consumer-selection-card">
      {image ? <ImageWithFallback alt={title} src={image} /> : <Camera size={22} />}
      <div>
        <strong>{title}</strong>
        {text && <span>{text}</span>}
      </div>
    </article>
  );
}

function SaveStep({
  onStart,
  onWorks,
  photo,
  resultTask,
  selectedDress,
  selectedDressName,
  selectedScene,
}: {
  onStart: () => void;
  onWorks: () => void;
  photo: UploadState;
  resultTask: Task | null;
  selectedDress: LibraryAsset | null;
  selectedDressName: string;
  selectedScene: string;
}) {
  return (
    <section className="consumer-save-page">
      <aside className="consumer-selected-panel">
        <h2>本次选择</h2>
        <SelectionCard image={photo.previewUrl} title="你的照片" />
        <SelectionCard image={selectedDress?.image_url || null} title={`婚纱：${selectedDressName}`} />
        <SelectionCard title={`场景：${selectedScene}`} />
        <button onClick={onStart} type="button">
          换一款婚纱
        </button>
      </aside>

      <div className="consumer-result-main">
        <div className="consumer-section-title centered">
          <span>第四步</span>
          <h1>你的试穿照已生成</h1>
          <p>{selectedDressName} / {selectedScene}</p>
        </div>
        <div className="consumer-result-frame">
          {resultTask ? (
            <ImageWithFallback alt="生成的婚纱试穿照" src={`/api/task/${resultTask.task_id}/result`} />
          ) : (
            <div className="consumer-preview-empty">生成完成后会显示在这里</div>
          )}
        </div>
      </div>

      <aside className="consumer-save-actions">
        <h2>保存作品</h2>
        <a
          className={!resultTask ? "disabled" : ""}
          href={resultTask ? `/api/task/${resultTask.task_id}/result` : undefined}
          download
        >
          <ArrowDownToLine size={17} />
          下载高清图片
        </a>
        <button onClick={onStart} type="button">
          <RefreshCw size={17} />
          再生成一张
        </button>
        <button onClick={onWorks} type="button">
          <Eye size={17} />
          查看我的作品
        </button>
        <p>作品已保存，你可以随时删除。</p>
      </aside>
    </section>
  );
}

function WorksPage({
  deletingId,
  onDelete,
  onStart,
  works,
}: {
  deletingId: string | null;
  onDelete: (task: Task) => void;
  onStart: () => void;
  works: Task[];
}) {
  return (
    <section className="consumer-works-page">
      <div className="consumer-page-head">
        <div>
          <span>我的作品</span>
          <h1>查看和保存你生成过的婚纱试穿照</h1>
        </div>
        <button onClick={onStart} type="button">
          <Sparkles size={17} />
          再生成一张
        </button>
      </div>

      <div className="consumer-tabs" aria-label="作品筛选">
        <button className="active" type="button">全部</button>
        <button type="button">已保存</button>
        <button type="button">最近生成</button>
      </div>

      {works.length === 0 ? (
        <div className="consumer-empty-works">
          <ImagePlus size={34} />
          <strong>还没有作品</strong>
          <span>上传照片并选择婚纱后，就可以生成第一张试穿照。</span>
          <button onClick={onStart} type="button">开始试穿</button>
        </div>
      ) : (
        <div className="consumer-work-grid">
          {works.map((work, index) => (
            <article key={work.task_id}>
              <ImageWithFallback alt={workTitle(work)} src={`/api/task/${work.task_id}/result`} />
              <div>
                <strong>{workTitle(work)}</strong>
                <span>{formatDate(work.created_at)}</span>
              </div>
              {index === 0 && <em>新生成</em>}
              <div className="consumer-work-actions">
                <a href={`/api/task/${work.task_id}/result`} target="_blank" rel="noreferrer">
                  查看
                </a>
                <a href={`/api/task/${work.task_id}/result`} download>
                  下载
                </a>
                <button disabled={deletingId === work.task_id} onClick={() => onDelete(work)} type="button">
                  {deletingId === work.task_id ? <Loader2 className="spin" size={14} /> : <Trash2 size={14} />}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
      <p className="consumer-bottom-note">你可以随时删除作品。</p>
    </section>
  );
}

function HelpPage({ onStart }: { onStart: () => void }) {
  return (
    <section className="consumer-help-page">
      <div className="consumer-section-title centered">
        <span>帮助</span>
        <h1>怎样获得更自然的试穿效果</h1>
        <p>按下面的建议准备照片和婚纱图，效果会更稳定。</p>
      </div>
      <div className="consumer-help-grid">
        <TipCard title="照片要清晰" text="尽量选择正面全身照，避免遮挡脸部和身体轮廓。" />
        <TipCard title="婚纱要完整" text="单件婚纱图更利于还原款式、裙摆和细节。" />
        <TipCard title="可以多生成" text="同一张照片可以尝试不同婚纱，保留满意的一张。" />
      </div>
      <button onClick={onStart} type="button">
        <Sparkles size={17} />
        开始试穿
      </button>
    </section>
  );
}
