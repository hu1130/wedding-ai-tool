# 阿里云生产部署补齐项

这版已经把正式上线前最容易出问题的能力接到后端主链路：MySQL 业务库、用户中心 SSO 前置结构、OSS、租户隔离、限流、失败重试与日志、图片清理。当前如果用户中心还在建设，可以先把本工具自己的 MySQL 业务库跑通。

## 运行依赖

- `ALIYUN_DASHSCOPE_API_KEY`：通义万相/试衣服务密钥，只放在服务器环境变量，不提交到 Git。
- `DATABASE_URL`：生产必须使用 MySQL，例如阿里云 RDS MySQL。不要在代码或聊天里暴露真实密码。
- `APP_CODE`：本工具应用编码；后续接用户中心时要和用户中心分配值一致。
- `AUTH_ENABLED=false`、`AUTH_MODE=local`：用户中心未完成前的内部测试模式，不要暴露到公网。
- `AUTH_MODE=platform_sso`：用户中心完成后的正式登录模式。
- `USER_CENTER_BASE_URL`、`USER_CENTER_CLIENT_ID`、`USER_CENTER_CLIENT_SECRET`：用户中心 SSO exchange 所需配置，后续再填。
- `OBJECT_STORAGE_MODE=oss`：生产图片存储走阿里云 OSS。
- `AUTH_ENABLED=true`：开启登录保护；用户中心未完成前先保持 `false` 或只做内部 API 联调。
- `RATE_LIMIT_ENABLED=true`：开启上传和生成限流，避免模型调用成本失控。
- `CLEANUP_ENABLED=true`：允许定期清理过期图片和软删除素材记录。

## 数据库和用户中心

原来的 `backend/tasks.json`、`backend/assets.json`、`backend/quality_reviews.json` 已改为业务库持久化。生产使用 MySQL，SQLite 只保留为本地测试 fallback。

- 建表脚本在 `backend/migrations/001_business_mysql.sql`。
- 初始化/校验脚本：`python scripts/init_database.py`。
- MySQL 接入细节见 `docs/mysql-rollout.md`。
- 工具业务库不并入用户中心库，不直连用户中心数据库。
- `terminal_user_binding` 保存用户中心身份和工具本地业务用户的绑定关系。
- `tool_sessions` 保存工具自己的本地会话。
- `tasks`、`assets`、`quality_reviews` 都有 `tenant_id`、`platform_user_id`、`local_user_id` 字段。
- `APP_ENV=production` 时，如果 `DATABASE_URL` 不是 MySQL，服务会拒绝启动。

## 图片存储

上传图片和生成结果都会先保留本地缓存，再写入对象存储。

- 本地开发：`OBJECT_STORAGE_MODE=local`。
- 阿里云生产：`OBJECT_STORAGE_MODE=oss`，并配置 `OSS_ENDPOINT`、`OSS_BUCKET`、`OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET`。
- 结果读取、步骤图读取、导出压缩包都支持本地缓存缺失时回读 OSS。

## 登录隔离

后端已提供简单登录接口：

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

用户中心未完成前，浏览器端内部测试可先保持 `AUTH_ENABLED=false`，所有数据会落到默认 `dev` 用户范围。需要验证同库多用户隔离时，可用后端 `POST /api/auth/login` 做 API 级临时账号测试；C 端正式登录仍等待用户中心 SSO。

生产开启 `AUTH_ENABLED=true` 且 `AUTH_MODE=platform_sso` 后，上传、生成、素材、结果、质量评分等接口都会要求用户中心 SSO 会话。固定账号密码登录只保留给本地开发和临时 API 联调。

SSO 接收路由：

```text
GET /auth/platform?ticket=...
```

处理流程：

1. 接收用户中心一次性 ticket。
2. 后端调用用户中心 `/api/v1/sso/exchange`。
3. 获取可信 `tenant_id`、`platform_user_id`、`roles`、`app_code`。
4. 查找或创建 `terminal_user_binding`。
5. 创建 `tool_sessions` 本地会话。
6. 写入 HttpOnly Cookie 并跳转工具首页。

## 限流

开启 `RATE_LIMIT_ENABLED=true` 后：

- `MAX_UPLOADS_PER_HOUR` 控制上传频率。
- `MAX_CREATE_TASKS_PER_HOUR` 控制每小时生成次数。
- `MAX_CREATE_TASKS_PER_DAY` 控制每日生成次数。

优先按登录用户限流，未登录开发模式下按客户端 IP 限流。

## 重试和日志

生成链路增加了失败记录和自动重试：

- `MAX_TASK_RETRIES` 控制最大重试次数。
- `TASK_RETRY_DELAY_SECONDS` 控制失败后重试间隔。
- 不可重试错误会直接失败，例如文件缺失、参数错误、未实现步骤。
- 日志输出到 stdout，适合容器平台采集。

## 清理策略

清理脚本：

```bash
python scripts/cleanup.py
python scripts/cleanup.py --apply
```

默认是 dry-run。生产建议用阿里云定时任务或服务器 cron 执行 `--apply`，并配置：

- `UPLOAD_RETENTION_DAYS`
- `OUTPUT_RETENTION_DAYS`
- `DELETED_RECORD_RETENTION_DAYS`

清理会保护仍被任务或素材库引用的上传图片，避免误删正在使用的素材。

## 上线前还需要人工确认

- 设置真实域名到 `CORS_ALLOW_ORIGINS`。
- 先在阿里云 RDS MySQL 里执行 `backend/migrations/001_business_mysql.sql`，或运行 `python scripts/init_database.py` 自动建表并校验。
- 在服务器环境变量里填入密钥和 OSS 配置。
- 先配置 `DATABASE_URL`、`APP_CODE`，用户中心 SSO 环境变量等用户中心完成后再补。
- 用户中心完成后，再切换 `AUTH_ENABLED=true`、`AUTH_MODE=platform_sso` 并联调登录入口。
- 用真实阿里云账号跑一次完整链路：上传模特图、上传婚纱图、生成、查看结果、删除、清理 dry-run。
