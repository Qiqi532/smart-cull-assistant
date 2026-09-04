# 更新日志 CHANGELOG

本项目的版本演进记录。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

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
