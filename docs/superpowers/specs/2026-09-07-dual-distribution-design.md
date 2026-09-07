# Torch / OpenCV 双版本发行设计

## 目标

在同一代码库内长期保留两个可独立构建、安装和运行的 Windows 版本：

- **标准版（Torch）**：保留 PyTorch、Transformers、pyiqa 与模型推理，优先保证选片精度。
- **轻量版（OpenCV）**：固定使用 `HeuristicBackend`，不包含 Torch、Transformers、pyiqa 或在线模型下载，优先保证体积、启动速度和离线可用性。

两个版本共享 `app_qt.py` 与 `engine/` 业务代码，但依赖环境、构建目录、发行目录和安装脚本互相隔离，任何构建都不得覆盖另一个版本。

## 版本边界

| 项目 | Torch 标准版 | OpenCV 轻量版 |
| --- | --- | --- |
| 推理后端 | `torch` | `heuristic` |
| 开发环境 | `.venv` | `.venv-light` |
| 依赖清单 | `requirements.txt` | `requirements-lightweight.txt` |
| PyInstaller spec | `光影选片助手_dist.spec` | `光影选片助手_dist_lightweight.spec` |
| 工作目录 | `build` | `build_light` |
| 发行目录 | `dist` | `dist_light` |
| 构建脚本 | `build_dist.bat` | `build_dist_lightweight.bat` |
| 安装脚本 | `installer.iss` | `installer_lightweight.iss` |

轻量版运行时钩子必须在导入 `engine.config` 前设置 `LUMINA_INFERENCE_BACKEND=heuristic`。标准版继续使用默认的 `torch` 后端。

## 依赖设计

`requirements-lightweight.txt` 只声明 GUI、图像处理、人脸检测和基础文件格式依赖，并约束 MediaPipe 所需的 NumPy 兼容范围。轻量构建使用不继承系统包的 `.venv-light`，避免从 Anaconda base 意外收集 SciPy、Sphinx、Torch 等包。

`requirements.txt` 继续服务标准版，并显式说明其包含深度学习依赖。README 分别给出两个环境的创建、安装、源码启动和打包命令。

## 构建设计

`build_dist_lightweight.bat` 必须显式传入：

```bat
--distpath dist_light --workpath build_light
```

脚本只检查和压缩 `dist_light\光影选片助手`，不得读写标准版的 `dist\光影选片助手`。

轻量 spec 不再对 PyQt6、NumPy、Pillow、OpenCV 和 MediaPipe 执行无差别的全包 `collect_submodules()`。仅保留应用真实导入的 PyQt6 模块、MediaPipe FaceMesh 所需模块和 MediaPipe 模型数据；其余依赖交给 PyInstaller 官方 hook 解析。构建后检查不得包含 Torch、Transformers、pyiqa、TensorFlow、pytest 或 Sphinx。

## 安装设计

保留 `installer.iss` 作为 Torch 标准版安装器。新增 `installer_lightweight.iss`，固定读取 `dist_light\光影选片助手`，使用不同的 `AppId`、应用显示名、安装目录和安装包文件名，允许两个版本并存安装。

## 测试与验收

完成修改后执行以下门禁：

1. 默认 Windows 中文环境直接运行 `python -m pytest tests`，不得再因 `pytest.ini` 编码失败。
2. 常规测试全部通过；设置 `LUMINA_INFERENCE_BACKEND=heuristic` 后端到端测试通过。
3. Torch 与 heuristic 后端选择测试通过，模型签名不同并能触发数据库重分析语义。
4. GUI 离屏启动成功，主窗口和四个页面可创建。
5. 轻量 spec 在 `.venv-light` 中构建成功，输出只进入 `build_light` / `dist_light`。
6. 轻量 exe 启动后稳定存活，无 `crash.log`。
7. 轻量产物不包含深度学习框架或开发文档工具；体积以本机实测为准写回 README，不保留未经验证的约 150 MB 承诺。
8. `pip check` 在 `.venv-light` 中通过。

## 错误处理

- 缺少 `.venv-light` 时，轻量构建脚本给出创建和安装命令并退出，不回退到 `.venv`。
- PyInstaller 构建失败时保留日志并返回非零退出码，不把旧产物误报为本轮成功。
- 安装器编译前检查对应版本的发行目录；标准版与轻量版均不得静默使用另一版本产物。

## 非目标

- 本轮不调整选片评分算法和 GUI 交互。
- 本轮不合并两个安装器，也不制作自动选择 CPU/GPU 的统一安装包。
- 本轮不执行 Git commit、GitHub push 或发布 Release；完成修复与本地验收后等待用户确认。
