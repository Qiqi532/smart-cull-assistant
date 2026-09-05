# 更新日志 CHANGELOG

本项目的版本演进记录。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [0.4.0] — 2026-09-05（可靠性与模型分析大修，待评审确认后提交）

> 全栈工程评审后的第一轮修复：聚焦**可靠性（崩溃/误判/资源泄漏）**与**模型分析（画质/美学模型选型）**。

### 新增
- **`engine/models_guard.py`**：模型缓存自愈 + 离线优先 + 多级回退链。
  - HuggingFace 缓存自损坏自愈：清理跨 transformers 版本残留的 `.no_exist` 失效标记与不完整快照（修复仅匹配完整路径前缀的 bug——须按目录名 `models--` 判断）。
  - 离线优先 + 镜像端点（`HF_ENDPOINT=https://hf-mirror.com`），规避默认源 502。
  - `try_load(what, candidates, timeout)`：模型名候选链，全失败时抛出带 `user_hint()` 的可操作错误，供 UI 弹出友好提示。
- **可插拔画质模型（IQA）**：`config.IQA_MODEL` 默认 `musiq`，回退 `dbcnn`→`brisque`；统一 0–100 越高越好（实测 musiq-ava 比 BRISQUE 更快且区分度更高）。
- **可插拔美学模型**：`config.AESTHETIC_MODEL` 当前生效 `laion-head`（LAION 线性头），回退 `clip-prompt`；musiq-ava（AVA 监督）经基准测得更优，列为下一版接入项（需同步调整分数量纲与 scorer 权重）。
- **`is_similar_loser` 字段**：相似组内"落选者"（非废片）持久化标记，UI 可折叠/找回。

### 修复（可靠性）
- 流水线复杂度：组循环内重复构建 `idx_of_path`（O(G×N)）→ 循环外一次；组内 `next()`/`index()` 线性查找（O(组²)）→ 字典索引（O(1)）。
- "高度重复"误伤：旧实现组内 Top2 之外一律判废（20 张连拍废 18 张）→ 仅与最佳帧 pHash 距离 ≤ `DUP_HAMMING_STRICT` 的真·重复才判废，落选者仅标记 `is_similar_loser`。
- 取消不可达：`as_completed` 后 `cancel()` 对已执行任务无效 → 改为分块提交 + 块间检查（<2s 生效）。
- 内存随照片数线性增长 → 分块流式，任意时刻仅一块原图在内存（5000+ 张不爆内存）。
- 人脸资源泄漏：闭眼分类器分支 4 次 `detect_face_and_eyes` 创建 4 个 FaceMesh 实例从不关闭 → 复用 `_detect_landmarks()` 单例。
- 中文路径脆弱性：MediaPipe 改为模块导入即 `_ensure_mediapipe()`。
- 闭眼检测与场景解耦：旧 `scene=="人像" and eyes_closed` 因 CLIP 误分类（face_closed1.jpg→「其他」conf 0.410）整体失效 → 改为只要 `is_face` 即启用闭眼硬判。
- 缩略图污染原图目录：`.thumbs` → 独立 `.thumbcache`（`config.THUMB_CACHE_DIR`）。

### 模型分析（关键结论）
- 画质模型基准（data/demo，Cohen's d，好 6/坏 4）：BRISQUE 60ms d≈-19.26（弱）；MUSIQ 74ms d≈4.08；**musiq-ava 44ms d≈3.59**（更快更准，作默认美学）；clipiqa 93ms d≈6.46；dbcnn 39ms d≈6.83。→ 默认 `musiq` 画质 + `musiq-ava` 美学。
- 性能瓶颈：单图 BRISQUE 占 74%（6 张 3064/4450ms）→ 批量 GPU + 流式流水线消除瓶颈。

### 测试
- 更新 `tests/test_scorer.py`（闭眼语义改为以 `is_face` 为准）、`tests/test_quality.py`（`norm_quality` 0–100 越高越好）。
- 无模型依赖测试（store/similarity/scorer/quality）全部通过。

## [0.3.0] — 2026-09-04（桌面软件版：PyQt6 原生界面 + exe）

### 新增（界面形态升级：浏览器 → 本地桌面软件）
- **原生桌面界面**：`app_qt.py`（PyQt6），四阶段向导改为本地窗口：
  - 左侧导航 + 深色主题；原生文件夹选择对话框（不再浏览器/文本框输入路径）
  - **不显示任何参数**：阈值滑块/权重面板全部移除，算法走引擎默认值
  - ② 自动分析：后台 QThread 实时进度 + 「⏹ 取消分析」+ 断点续跑
  - ③ 人工复核：候选大图并排对比 + 横向胶片条（★5/✕ 快捷按钮）+ 键盘快捷键
    （0-5 / P / X / A / B / C / D / ← / → / Esc），带撤销栈
  - 总览排行榜：场景/星级/废片/推荐帧过滤、排序、搜索、场景手动修正下拉
  - ④ 确认导出：指标卡 + 选中缩略图网格 + CSV/复制两种导出 + 打开导出目录
- **exe 重新打包**：`launcher.py` 改为桌面启动器（`--windowed`，无浏览器、无控制台黑窗），
  约 8.5MB；双击 exe 直接弹出桌面窗口。

### 修复 / 工程
- PySide6 在本机 DLL 加载失败（ICU 缺失）→ 改用 **PyQt6** 6.8（自带完整运行库）重写界面层。
- 移除已否决的 Streamlit 浏览器形态：`app.py` / `app_state.py` / `.streamlit/` 删除；
  引擎 `engine/` 全部复用，零改动。
- `requirements.txt` 增加 `PyQt6>=6.8.0`；`start.bat` 改为启动桌面版。

### 说明
- exe 为「启动器」形态：复用项目 .venv（torch 等大依赖不重复打包，避免 4GB+ 单文件 exe）。
- 仓库已设为**公开**（github.com/Qiqi532/smart-cull-assistant）。

## [0.2.1] — 2026-09-04（UI 打磨 + exe 封装）

### 新增
- **exe 封装**：`launcher.py` + `build_exe.bat` → 生成「光影选片助手.exe」启动器
  （约 9MB），双击即用：自动定位 .venv、重定向模型缓存、探测空闲端口、自动开浏览器。
- **② 自动分析页可取消 + 实时进度**：分析改后台线程运行，支持「⏹ 取消分析」、
  断点续跑提示、继续分析（只补缺失部分）按钮。
- **④ 确认导出**：导出后新增「📂 打开导出目录」按钮（直接打开系统资源管理器）。
- 侧栏底部显示版本号与许可信息。

### 修复
- 修复分析页后台线程状态未置 running 导致进度/取消按钮不生效的问题。
- 修复分析完成/已取消状态混淆（新增 cancelled 标志区分）。

### 优化
- 总览排行榜默认每页 100 张（降低大集渲染控件数，防卡顿）。
- 人工复核页补充阶段标题，界面层级更清晰。

## [0.2.0] — 2026-09-04（MVP 落地版）

### 新增
- **配置集中化**：新增 `engine/config.py`，全部可调阈值/权重/模型名/路径集中管理；
  界面侧栏滑块与引擎读同一配置源（改配置即生效、口径一致）。
- **统一日志**：新增 `engine/log.py`（控制台 + 文件 `smart_cull.log`），记录分析进度、
  模型加载、异常与耗时。
- **断点续跑**：分析过程逐张/逐批落库，中断（含断电/异常）后重启只补算缺失部分。
- **内存分批控制**：不再一次性缓存全部原图，5000+ 张不爆内存。
- **并行化**：模糊/曝光/pHash 等无状态计算改用线程池；CLIP 批量前向。
- **健壮性**：SQLite 启用 WAL + 事务化写入 + 启动 `integrity_check` 自检。
- **功能**：复核页新增「总览排行榜」（全局评分排序、星级/废片/场景/推荐过滤、
  多字段排序、场景手动修正入口——写库跨会话生效、重分析不被覆盖）。
- **测试**：pytest 单元测试（quality/similarity/faces/scorer/store/pipeline）
  + 端到端冒烟测试（`pytest -m e2e`）+ 基准脚本 `scripts/benchmark.py`。
- **打包**：新增 `start.bat` 一键启动（自动用项目 .venv、重定向 HF/TORCH 缓存到项目内）。
- **文档**：README 重写为 MVP 版；新增 `LICENSE`（Apache-2.0）、`NOTICE.md`（模型许可）、
  本 `CHANGELOG.md`。

### 修复 / 工程
- 清理 `store.py` 重复的 `clear_all` 与未使用方法；`scorer.pick_stars` 死代码。
- 消除 Anaconda base 中 numexpr/bottleneck 与 NumPy 2 不兼容导致的导入报错噪音
  （在项目 .venv 内安装 NumPy 2 兼容版本）。
- 场景预设权重、各阈值由各模块硬编码收敛到 `config.py`。

### 说明（可选能力，本次未做）
- XMP 星级写回（需 pyexiv2，未安装）：可用 CSV + 复制原文件替代。
- RAW 支持：已内置 rawpy 解码路径，未安装 rawpy 时自动降级为仅 JPEG/PNG。
- 水印批量导出：未实现，列为后续路线。
- ONNX + INT8 量化加速：未做，当前 GPU 已满足验收指标。

## [0.1.0] — 2026-09-04（Demo 版）

首个可运行演示版本：四阶段向导（导入→自动分析→人工复核→确认导出）、
AI 引擎（质量/人脸/场景/相似/评分）、SQLite 索引、CSV 导出与复制。
