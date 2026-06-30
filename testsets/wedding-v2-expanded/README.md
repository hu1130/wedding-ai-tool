# Wedding V2 Expanded 扩展测试集

这个目录是比 `wedding-v1` 更大的测试集。`wedding-v1` 保留为小基线；`wedding-v2-expanded` 用来做更全面的效果回归。

## 内容

- 6 张模特图：正面、侧身、深色背景、多体型、成熟模特等。
- 6 张婚纱图：A 字裙、鱼尾、长袖蓬裙、缎面蓬裙、极简直身、披肩蕾丝。
- 7 张动作参考图：正面、行走、手扶裙摆、坐姿、捧花、回眸、台阶。
- 24 条测试用例：基础款式、背景、动作、自定义背景、2K 抽检。

## 推荐跑法

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

完整回归会真实创建 24 个任务，会消耗阿里云调用。日常调参建议先跑 3 到 8 个关键用例。

## 评分

按 `scorecard.csv` 记录每条任务的：

- `face_score`
- `dress_score`
- `pose_score`
- `background_score`
- `overall_score`

每项 1 到 5 分。老板演示候选图至少满足：

- `face_score >= 4`
- `dress_score >= 4`
- 稳妥/轻动作 `pose_score >= 3`
- 实验动作不能出现严重崩脸、两条裙子、多手、多腿、短裙替代拖地婚纱
