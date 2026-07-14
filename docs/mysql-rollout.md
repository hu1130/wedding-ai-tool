# MySQL 业务库接入说明

这一步只接本工具自己的业务库，不依赖用户中心。用户中心完成后再切换 `AUTH_MODE=platform_sso`。

## 要落 MySQL 的数据

- `tasks`：生成任务、进度、输入参数、输出文件引用。
- `assets`：用户上传素材、婚纱素材、软删除状态。
- `quality_reviews`：质量评分。
- `storage_meta`：旧 JSON 迁移标记等内部元数据。
- `business_logs`：业务日志。
- `terminal_user_binding`、`tool_sessions`：后续用户中心登录会用到，当前先建好不影响使用。

图片二进制不进 MySQL。上传图和结果图放本地或 OSS，MySQL 只保存文件引用。

## 阿里云 RDS 准备

在 RDS 或 DMS 里创建一个本工具专用库，例如：

```sql
CREATE DATABASE wedding_ai_tool
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;
```

生产账号最少需要这些权限：

```sql
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX
ON wedding_ai_tool.*
TO 'wedding_ai_tool_app'@'%';
```

真实用户名、密码、内网地址不要写进代码或文档。

## 环境变量

PowerShell 本地联调示例：

```powershell
$env:DATABASE_URL="mysql+pymysql://USER:PASSWORD@HOST:3306/wedding_ai_tool?charset=utf8mb4"
$env:APP_ENV="production"
$env:AUTH_ENABLED="false"
$env:AUTH_MODE="local"
```

用户中心未完成前，浏览器端内部测试建议先保持 `AUTH_ENABLED=false`。如果要测后端本地账号登录，只用于 API/后台联调，不作为 C 端正式登录页。

## 初始化和校验

推荐用脚本初始化并校验业务表：

```powershell
.\.venv\Scripts\python.exe scripts\init_database.py
```

成功时会输出：

```text
database=mysql
ok=true
missing_tables=
```

也可以手工执行：

```text
backend/migrations/001_business_mysql.sql
```

## 验证服务是否真的连 MySQL

启动后访问：

```text
GET /api/health
```

返回里应看到：

```json
{
  "database": "mysql"
}
```

如果仍然是 `sqlite-local`，说明当前进程没有读到 `DATABASE_URL`，需要检查服务器环境变量或重启服务。
