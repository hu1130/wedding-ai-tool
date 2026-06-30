# Wedding V1 固定测试集

这个测试集用于每次改代码或改提示词后复测，重点看三件事：

- 款式还原：婚纱轮廓、裙长、袖型、腰线、蕾丝/纱面纹理是否保留。
- 人脸稳定：五官、脸型、发型、肤色和光线是否接近原模特。
- 动作可控：动作参考图是否生效，同时不能复制参考图的人脸、衣服和背景。

## 目录

```text
testsets/wedding-v1/
  models/       模特输入图
  dresses/      婚纱款式图
  pose_refs/    动作参考图
  contact-sheet.jpg
  testset.json
  scorecard.csv
```

## 使用方法

1. 打开本地页面 `http://127.0.0.1:8000`。
2. 按 `testset.json` 里的 `scenarios` 逐条上传对应素材。
3. 有 `pose_ref` 的用例，要上传“动作参考图”。
4. 生成完成后，把结果按 `scorecard.csv` 打分。
5. 每次代码优化后，至少跑 `WED-001` 到 `WED-010`；`WED-012` 是 2K 抽检，不必每轮都跑。

也可以用脚本自动提交任务：

```powershell
.\.venv\Scripts\python.exe testsets\wedding-v1\run_testset.py --limit 3
.\.venv\Scripts\python.exe testsets\wedding-v1\run_testset.py --ids WED-001,WED-007,WED-008
```

脚本会生成 `submitted-tasks.csv`，里面记录每条测试用例对应的任务 ID。

## 评分标准

每项 1 到 5 分：

- 5：可演示或可交付
- 4：小瑕疵，可接受
- 3：有明显问题，但还能判断方向
- 2：问题严重，需要重跑或调参
- 1：失败，不可用

核心通过线：

- `face_score >= 4`
- `dress_score >= 4`
- 稳妥/轻动作：`pose_score >= 3`
- 实验动作：允许 `pose_score >= 2`，但不能严重崩脸或两条裙子
- 不能出现水印、文字、明显多余人物、两条裙子、短裙替代拖地婚纱

## 建议跑法

- 老板演示前：只跑低风险和中风险用例，优先 `WED-001` 到 `WED-008`。
- 动作优化时：重点跑 `WED-007` 到 `WED-010`。
- 款式优化时：重点跑 `WED-001`、`WED-002`、`WED-003`、`WED-006`。
- 背景优化时：重点跑 `WED-004`、`WED-005`、`WED-006`、`WED-011`。
