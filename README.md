# 📷 光影选片助手 Smart Cull Assistant

本地 AI 智能选片工具：**废片剔除 → 相似分组 → 场景自适应评分 → 最佳帧推荐 → 不确定甄选**。
照片全程本地处理、不上传；GUI 为 **PyQt6 桌面原生窗口**（无浏览器、无参数面板），算法核心在 `engine/`（纯 Python，可独立命令行调试）。

> MVP 落地版（v0.2.0）。设计文档见上级目录 `PRD_智能选片工具/`。

---

## ✨ 功能

| 能力 | 说明 |
| --- | --- |
| 自动废片剔除 | 模糊（拉普拉斯方差）、过曝/欠曝（直方图占比）、**闭眼**（MediaPipe EAR + ViT 分类器融合）、高度重复 |
| 相似分组 | EXIF 时间戳连拍分组 + pHash 感知哈希（并查集合并，覆盖跨机位相似） |
| 场景自适应 | CLIP 分类：人像/风光/建筑/街拍/宠物/静物/其他，不同场景用不同权重 |
| 最佳帧推荐 | 组内综合评分（清晰/曝光/美学/人脸），Top1 自动 5 星 |
| 不确定甄选 | 无明确胜者（分差小/帕累托冲突/场景置信低）时进入人工甄选（A/B/C/D 选择） |
| 一键导出 | CSV 清单 + 复制保留文件到导出目录 |

### 人工复核快捷键（Photo Mechanic 风格）
```
0-5 标星 · P 保留 / X 排除 · A/B/C/D 选候选 · Tab/→ 下一组 · ← 上一组 · Esc 退出
```
复核页还有「总览排行榜」：全局综合分排序、星级/废片/场景/推荐帧过滤、多字段排序、**场景手动修正入口**（写库持久，重分析不被覆盖）。

---

## 🏗 架构

```
app_qt.py               PyQt6 桌面原生四阶段向导（①导入→②自动分析→③人工复核→④确认导出）
launcher.py             打包启动器（双击 exe → 直接弹出桌面窗口，无浏览器/黑窗）
engine/
  config.py            全项目可调参数唯一来源（阈值/权重/模型名/路径，界面与引擎同源）
  log.py               统一日志（控制台 + 文件 smart_cull.log）
  loader.py            目录扫描、JPEG/PNG/RAW 解码、EXIF、缩略图缓存
  quality.py           模糊/曝光检测 + BRISQUE 无参考质量分（pyiqa）
  faces.py             MediaPipe 人脸 + 闭眼 EAR + ViT 分类器融合
  aesthetics.py        CLIP 美学评分（LAION-Aesthetics 线性头，GPU 优先）
  scene.py             CLIP 场景分类（人像/风光/其他）
  similarity.py        pHash 相似、连拍分组、并查集聚类
  scorer.py            场景自适应评分、废片判定、最佳帧 + 不确定甄选
  store.py             SQLite 索引（WAL + 事务化 + 断点续跑辅助）
  pipeline.py          端到端编排（流式内存控制、线程池、断点续跑、增量、进度回调）
scripts/benchmark.py   性能分段基准脚本
tests/                 pytest 单元测试 + 端到端冒烟
start.bat             Windows 一键启动
```

### 数据流
```
扫描目录 → 逐张：质量/BRISQUE/phash/人脸（流式+线程池，逐张落库）
       → CLIP 批量：美学+场景（逐批回写）
       → 相似聚类 → 组内场景自适应评分 → 废片/最佳帧/不确定甄选 → 全量入库
```

---

## 🚀 安装与运行

### 环境要求
- Windows / macOS / Linux，Python 3.10+（本项目在 Windows 11 + Python 3.12 验证）
- **GPU 可选**：有 NVIDIA GPU（CUDA）更快；无 GPU 自动降级 CPU（慢但可用）

### 安装
```bash
# 1) 建虚拟环境（可选，推荐；本项目 .venv 复用 Anaconda base 以省 GPU torch 下载）
python -m venv --system-site-packages .venv
# 2) 安装依赖
.\.venv\Scripts\python.exe -m pip install --cache-dir .pip_cache -r requirements.txt
```

### 运行（二选一）
```bash
# 方式 A：Windows 一键启动（自动用 .venv、模型缓存重定向到项目内）
start.bat

# 方式 B：命令行
.\.venv\Scripts\python.exe app_qt.py
```
双击 exe 或运行脚本后直接弹出**原生桌面窗口**：选择照片文件夹（原生文件夹对话框）→ 点「开始分析」→ 自动进入复核/导出。

### 📦 打包成 exe（Windows 软件形态）

> **关于「启动器 / PowerShell」的常见疑问**
> `start.bat` 与旧版 `build_exe.bat` 产物（`光影选片助手.exe` = launcher 形态）**全程是纯 Windows BAT / cmd.exe，没有任何 PowerShell**（无 `Set-Location`/`Write-Host` 等 cmdlet）。
> 旧版 exe 的"额外一层"并非 PowerShell，而是：它本质上是个**启动器**——双击后由 exe 再调起项目 `.venv\Scripts\python.exe app_qt.py` 子进程运行。也就是说它**必须和项目 `.venv` + 源码放在一起**才能用。若你讨厌的就是这层"必须带源码/.venv"的依赖，请看下方**方案 B（自包含 onedir 构建）**，那才是真正脱离源码、可直接分发的路径。

#### 方案 A：开发态启动器（需 .venv，体积小、启动快）
```bash
# 1) 开发期一键启动（需已建 .venv 并完成依赖安装）
start.bat

# 2) 打包成"启动器" exe（约 8.5MB，仍需 .venv 在场）
build_exe.bat
#    产物 dist\光影选片助手.exe 复制到项目根目录（与 app_qt.py 同级）后双击即用
```
- exe 复用项目 `.venv`（torch/transformers 等大依赖不重复打包，避免 4GB+ 单文件与 30s+ 解压启动）；首次使用前需按上文完成依赖安装。

#### 方案 B：自包含 onedir 构建（**无需 .venv，可直接分发**）★推荐分发
把全部依赖（torch / transformers / PyQt6 / mediapipe / 等）一并打进一个文件夹，双击 `光影选片助手.exe` 即可运行，**不要求源码或 .venv 在场**：
```bash
# 一键打包自包含 onedir（首次约 3~8 分钟，体积较大）
build_dist.bat
# 可选：构建后额外生成 zip 压缩包
set ZIP=1 & build_dist.bat
```
- 产物：`dist\光影选片助手\` 文件夹（含 `光影选片助手.exe` + 全部依赖）。**整个文件夹拷贝到任意 Windows 机器双击即用**，无需 Python、无需 `.venv`。
- 模型权重（CLIP / 闭眼 ViT / MediaPipe）**不打包**，首次运行经 HF 镜像自动下载到 exe 目录下的 `.hf_cache` / `.torch_cache`（由 `dist_runtime_hook.py` 重定向，不落 C 盘）。
- 对应规格：`光影选片助手_dist.spec`（入口直接是 `app_qt.py`，`hiddenimports`/`collect_submodules`/`collect_data_files` 已覆盖延迟导入的 torch/transformers/mediapipe 等）。

#### 方案 C：制作安装包（单文件 setup.exe，含卸载）
用 [Inno Setup](https://jrsoftware.org/isdl.php) 把方案 B 的 `dist\光影选片助手\` 封装为安装程序：
```bash
# 1) 先有方案 B 产物 dist\光影选片助手\
# 2) 用 Inno Setup Compiler 打开 installer.iss 并编译（或命令行 ISCC.exe installer.iss）
# 3) 产出 Output\光影选片助手_setup.exe
```
- 安装后提供**桌面快捷方式 + 开始菜单项 + 标准卸载**；卸载时默认清理 `.hf_cache`/`.torch_cache` 模型缓存（见 `installer.iss`）。
- 提示：模型会下载进安装目录，建议安装到有写入权限的位置（默认 `Program Files` 下程序运行时会在安装目录写缓存；如受限可装到用户目录）。

### GPU 与降级说明
- 有 CUDA GPU：CLIP / BRISQUE 自动用 GPU，速度最快；
- 无 GPU / 驱动异常：自动回退 CPU，功能不变、仅更慢；
- `engine/aesthetics.py` 未找到 LAION 美学头时自动降级为「CLIP 提示词打分」；
- `rawpy` 未安装时自动跳过 RAW 扩展名，不影响 JPEG/PNG 全流程；
- 闭眼分类器（dima806）加载失败时自动退化为「仅 EAR」判定。

### 模型缓存（不落 C 盘）
首次运行从 HuggingFace Hub 自动下载 CLIP / 闭眼 ViT / MediaPipe 权重，缓存于项目内
`.hf_cache` / `.torch_cache`（`start.bat` 已重定向）。离线可复用已缓存权重。

---

## 🧪 测试数据

```bash
# 演示集（28 张，含人像/风光/闭眼/相似组）
python make_demo_data.py

# 合成测试集（44 张：模糊/过曝/欠曝/人像/风光/连拍）
python make_test_data.py

# 性能集（1000 张：连拍/相似/废片，带 EXIF 时间戳）
python make_perf_data.py 1000
```

## ✅ 自动化测试

```bash
# 单元测试（48 个：quality/similarity/faces/scorer/store/pipeline）
python -m pytest tests

# 端到端冒烟（构造含连拍/模糊/过曝/清晰的图片集，跑通全链，较慢）
python -m pytest tests -m e2e
```

---

## ⚡ 性能基准（实测）

**测试机**：Windows 11 · Python 3.12.12 · **NVIDIA GeForce RTX 4060 Laptop GPU**（CUDA）
**数据集**：`data/perf` 1000 张（1920×1080 级合成 JPEG/PNG，含连拍/废片/相似）

### 首轮完整分析（含模型加载 + 缩略图 + 推理）

| 阶段 | 耗时 | 占比 |
| --- | --- | --- |
| 扫描 | 4 ms | 0.0% |
| 读取元数据 | 6.37 s | 10.5% |
| 质量与哈希（BRISQUE+人脸+质量） | 28.48 s | 46.7% |
| 美学与场景（CLIP，GPU 批量） | 25.90 s | 42.5% |
| 相似聚类（pHash 复用） | 151 ms | 0.2% |
| 评分与甄选 | 30 ms | 0.0% |
| **合计** | **61.0 s** | — |

- **验收对照**：1000 张 GPU ≤5 min → **61.0 s 通过**；CPU ≤15 min 未测（无 CPU 机），理论 ~4-6 min（CPU 推理为 GPU 4-8 倍）。
- **增量分析**（mtime 未变，重复导入同目录）：**0.44 s**（只做聚类+评分，不重算任何图片）。
- **缩略图缓存**：首次 200 张 2.01 s；二次访问（缓存命中）0.03 s → 5000 张目录启动远低于 20 s。

### 断点续跑
阶段一/阶段二结果**逐张/逐批实时落库**（SQLite WAL 单事务）。分析中途断电/异常重启后，
只补算缺失部分（不从头再来）。实测：人为清掉 1 张的阶段一字段后重跑，`new_analyzed=1`。

### 手动抽样检查（人工一致性）
建议按「模糊 / 曝光 / 闭眼 / 相似组」每类抽 5-10 张人工复核，记录与引擎判定的一致率。
本项目 demo 集 28 张人工抽样：模糊、过曝、闭眼判定与预期一致；相似组边界场景
（时间戳缺失、极低对比度）建议以人工为准。

---

## 🔒 许可

- 项目代码：**Apache-2.0**（见 `LICENSE`）
- 第三方模型权重各有独立许可，逐项清单见 **`NOTICE.md`**（CLIP=MIT、LAION-Aesthetics 头=Apache-2.0、
  MediaPipe=Apache-2.0、dima806 闭眼分类器=Apache-2.0、pyiqa=Apache-2.0）

## 📄 更新日志
见 `CHANGELOG.md`。

---

## ❓ FAQ

**Q：分析很慢？**
先确认窗口底部状态栏显示「✅ GPU 推理」。无 GPU 时 CPU 全流程约 4-6 分钟/千张属正常。

**Q：为什么有的相似组进了「待甄选」？**
组内 Top1-Top2 综合分差小于 3、或维度互有胜负、或场景置信度低时，算法不替你拍板，
进入人工甄选（A/B/C/D 选一张）。

**Q：场景识别错了怎么办？**
「总览排行榜」里每张照片有场景下拉框，改成正确场景即可；该修正写入数据库，
重新分析不会被自动识别覆盖。

**Q：会把我照片传到网上吗？**
不会。所有处理在本机完成，仅在模型权重缺失时联网下载一次模型。

**Q：RAW 支持吗？**
扩展名识别已内置；安装 `rawpy` 后自动启用。未安装时仅处理 JPEG/PNG，不影响主流程。

**Q：能不能导出 Lightroom/Photo Mechanic 可读的星级？**
当前 MVP 提供 CSV 清单 + 复制原文件。XMP 星级写回（需 pyexiv2）列为后续路线。
