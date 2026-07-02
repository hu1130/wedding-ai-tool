# 婚纱 AI 试衣工具

面向婚纱电商和影楼试片流程的 AI 图片生成工具。当前版本支持上传模特图、婚纱图、可选客人脸部照，调用阿里云 DashScope 完成 AI 试衣、场景生成和最终交付图预览。

## 功能

- 上传模特原图、婚纱图片、可选客人面部照
- 上传素材会自动进入轻量素材库，前端可按模特、婚纱、动作参考、人脸分类复用
- 可选上传动作参考图，用于手扶裙摆、坐姿、回眸等动作控制测试
- 服装类型字段已预留；当前版本只开放婚纱模式，其他服装类型需单独扩展提示词规则
- 选择海边、教堂、花园、影棚、天台夜景等场景，也支持 240 字以内自定义背景描述
- 支持自定义动作/姿势提示词
- 动作分为稳妥动作、轻动作、实验动作；动作变化会走更适合长裙参考的生成链路
- 支持稳定模式：锁定试衣人物和婚纱，只生成无人婚礼背景并合成最终图
- 支持自由模式：整图重绘，动作更自由，但人脸和婚纱一致性风险更高
- 支持 1K、2K 分辨率任务
- 前端任务列表实时轮询进度
- 前端支持一次创建 1、3、5 个生成任务，用于批量出图和挑片
- 后端 FastAPI 接口，前端 Vite + React + TypeScript

## 本地启动

### 1. 安装后端依赖

```powershell
cd C:\path\to\wedding-ai-tool
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

### 2. 配置阿里云 DashScope Key

复制 `.env.example` 为 `.env` 后填入自己的 Key。后端启动时会自动读取项目根目录的 `.env`，真实 `.env` 已被 `.gitignore` 排除，不会提交到 GitHub。

```powershell
Copy-Item .env.example .env
notepad .env
```

也可以直接在当前终端设置临时环境变量：

```powershell
$env:ALIYUN_DASHSCOPE_API_KEY="你的 DashScope API Key"
```

### 3. 构建前端

```powershell
cd frontend
npm install
npm run build
cd ..
```

### 4. 启动服务

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

浏览器访问：

```text
http://127.0.0.1:8000
```

默认打开正式交付前端；需要进入完整测试台时访问：

```text
http://127.0.0.1:8000?view=test
```

## 验证命令

提交或演示前建议至少跑下面两项：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
cd frontend
npm run build
cd ..
```

当前任务列表会返回 `current_step` 和 `current_step_label`，前端会直接展示“等待队列 / AI试衣 / 场景生成 / 整理输出 / 已完成 / 失败步骤”，便于演示和排查。

## 常用接口

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/api/health` | GET | 健康检查 |
| `/api/upload` | POST | 上传图片 |
| `/api/assets` | GET | 获取素材库列表 |
| `/api/assets/{asset_id}/image` | GET | 获取素材预览图 |
| `/api/assets/{asset_id}` | DELETE | 从素材库移除记录，不删除已生成任务 |
| `/api/create-task` | POST | 创建单个生成任务 |
| `/api/batch-create` | POST | 批量创建任务 |
| `/api/tasks` | GET | 获取任务列表 |
| `/api/task/{task_id}` | GET | 查询任务详情 |
| `/api/task/{task_id}/result` | GET | 获取最终结果 |
| `/api/task/{task_id}` | DELETE | 删除任务记录、生成图和未被其他任务使用的上传素材 |

## 目录结构

```text
wedding-ai-tool/
  backend/        FastAPI 后端、任务队列、AI 服务调用
  frontend/       React 前端源码
  frontend/dist/  已构建前端，后端会优先托管这个目录
  testsets/       固定测试集、动作参考图、测试矩阵和打分表
```

固定婚纱测试集：

- `testsets/wedding-v1/`：小基线，3 张模特图、3 张婚纱图、4 张动作参考图和 12 条回归测试用例。
- `testsets/wedding-v2-expanded/`：扩展集，6 张模特图、6 张婚纱图、7 张动作参考图和 24 条回归测试用例。

## 注意事项

- 不要把真实 API Key 写进代码或提交到 GitHub。
- `uploads/`、`outputs/`、任务记录和日志都是本地运行数据，默认不会提交。
- 阿里云试衣模型会有一定随机性，婚纱细节和人脸一致性不能保证 100% 复刻；老板演示建议优先使用“稳定模式”。
