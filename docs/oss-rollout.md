# OSS 图片存储接入说明

这一步只接阿里云 OSS。MySQL 和用户中心可以后续继续处理。

## OSS 里保存什么

- 用户上传的人像、婚纱、参考图：`uploads/...`
- AI 生成结果图：`outputs/<task_id>/...`
- MySQL 只保存文件引用，不保存图片二进制。

## 需要的配置

不要把真实密钥提交到 Git，只写服务器环境变量或本机 `.env`。

```env
OBJECT_STORAGE_MODE=oss
OSS_ENDPOINT=https://oss-cn-xxx.aliyuncs.com
OSS_BUCKET=your-bucket-name
OSS_ACCESS_KEY_ID=your-access-key-id
OSS_ACCESS_KEY_SECRET=your-access-key-secret
OSS_PUBLIC_BASE_URL=
```

`OSS_PUBLIC_BASE_URL` 可选。如果绑定了 CDN 或自定义域名，就填完整 HTTPS 地址；没有就留空，代码会按 bucket + endpoint 生成公开地址。

## 权限要求

当前项目至少需要：

- `PutObject`
- `GetObject`
- `DeleteObject`
- `HeadObject` / 判断对象是否存在

建议先用单独的 RAM 子账号，只授权这个 bucket。

## 验证

配置好 `.env` 后运行：

```powershell
.\.venv\Scripts\python.exe scripts\init_oss.py
```

成功时应看到：

```text
ok=true
deleted=true
```

这个脚本会写入一个很小的临时对象，读回来确认，再删除。不会打印 AccessKey Secret。

## 服务健康检查

启动后访问：

```text
GET /api/health
```

应看到：

```json
{
  "object_storage_mode": "oss"
}
```
