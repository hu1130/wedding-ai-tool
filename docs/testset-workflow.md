# 标准测试集流程

当前项目已有两套测试集：

- `testsets/wedding-v1/`：小基线，用于快速确认基础能力没有坏。
- `testsets/wedding-v2-expanded/`：扩展集，用于覆盖更多人脸、款式、背景和动作。

## 推荐测试节奏

### 每次改前端

只跑构建和后端单测，不需要消耗 AI 生成额度。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
cd frontend
npm run build
cd ..
```

### 每次改提示词或生成链路

先跑 3 张快速检查：

```powershell
.\.venv\Scripts\python.exe testsets\wedding-v2-expanded\run_testset.py --ids W2-001,W2-004,W2-013
```

重点看：

- 人脸是否像本人
- 婚纱是否拖地、是否变短
- 背景是否融合自然
- 是否出现两条裙子、贴脸、多手、多腿

### 每次准备演示

跑稳定候选：

```powershell
.\.venv\Scripts\python.exe testsets\wedding-v2-expanded\run_testset.py --ids W2-001,W2-004,W2-007,W2-008,W2-022
```

这些用例风险较低，适合挑选老板演示图。

### 每次做动作优化

跑动作专项：

```powershell
.\.venv\Scripts\python.exe testsets\wedding-v2-expanded\run_testset.py --ids W2-013,W2-014,W2-015,W2-016,W2-017,W2-018,W2-019,W2-020
```

动作专项的目标不是全部完美，而是找出动作控制的稳定边界。

## 通过标准

演示候选图最低标准：

- 人脸：4 分及以上
- 款式：4 分及以上
- 动作：稳定/轻动作 3 分及以上
- 背景：3 分及以上
- 总体：4 分及以上

不通过的硬性问题：

- 人脸明显变成另一个人
- 婚纱由拖地变短裙
- 出现两条裙子
- 脸像抠图贴上去
- 多手、多腿、断手、断脚
- 背景遮挡主体

## 记录方式

优先在正式前端的成片预览弹窗里直接保存质量评分。

也可以继续使用测试集里的 `scorecard.csv` 做离线记录。
