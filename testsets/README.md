# 测试集总览

这个目录用于固定回归测试，不用于临时上传素材。

## 测试集

- `wedding-v1/`：小基线，适合快速确认核心链路。
- `wedding-v2-expanded/`：扩展集，适合验证款式还原、人脸稳定、背景和动作可控。

## 推荐入口

完整流程见：

- `docs/testset-workflow.md`
- `docs/quality-scorecard.md`
- `docs/demo-release-checklist.md`

## 常用命令

快速检查：

```powershell
.\.venv\Scripts\python.exe testsets\wedding-v2-expanded\run_testset.py --ids W2-001,W2-004,W2-013
```

动作专项：

```powershell
.\.venv\Scripts\python.exe testsets\wedding-v2-expanded\run_testset.py --ids W2-013,W2-014,W2-015,W2-016,W2-017,W2-018,W2-019,W2-020
```

完整回归：

```powershell
.\.venv\Scripts\python.exe testsets\wedding-v2-expanded\run_testset.py
```
