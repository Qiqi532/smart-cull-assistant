# Torch / OpenCV 双版本发行 Implementation Plan

> **For agentic workers:** Implement this plan task-by-task in the current task. Do not create commits or push until the user gives final approval.

**Goal:** 保留可独立发行的 Torch 标准版和 OpenCV 轻量版，并修复构建覆盖、安装器混用、轻量包膨胀、测试编码与依赖不可复现问题。

**Architecture:** 两个版本共享 `app_qt.py` 和 `engine/`，由运行时后端选择区分推理行为；发行层使用独立虚拟环境、依赖清单、PyInstaller 工作目录、发行目录和 Inno Setup 脚本。发行契约测试以文本和语法检查锁定双版本隔离规则，真实构建负责验证包内容和启动行为。

**Tech Stack:** Python 3.12、pytest、PyInstaller、PyQt6、OpenCV、MediaPipe、Inno Setup。

---

### Task 1: 添加双版本发行契约测试

**Files:**
- Create: `tests/test_distribution_contracts.py`

- [ ] **Step 1: 写入当前必然失败的契约测试**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_light_build_uses_isolated_environment_and_output():
    script = text("build_dist_lightweight.bat")
    assert ".venv-light\\Scripts\\python.exe" in script
    assert "--distpath dist_light" in script
    assert "--workpath build_light" in script
    assert "installer_lightweight.iss" in script


def test_light_installer_is_separate():
    standard = text("installer.iss")
    light = text("installer_lightweight.iss")
    assert '#define MySourceDir "dist\\光影选片助手"' in standard
    assert '#define MySourceDir "dist_light\\光影选片助手"' in light
    assert "光影选片助手轻量版" in light


def test_light_spec_does_not_collect_entire_packages():
    spec = text("光影选片助手_dist_lightweight.spec")
    assert "collect_submodules" not in spec
    assert "torch" in spec and "excludes" in spec


def test_pytest_config_is_cp936_readable():
    (ROOT / "pytest.ini").read_text(encoding="cp936")


def test_light_requirements_pin_numpy_compatibility():
    req = text("requirements-lightweight.txt")
    assert "numpy>=1.26,<2" in req
    assert "opencv-contrib-python" in req
```

- [ ] **Step 2: 运行测试并确认现状失败**

Run: `.\.venv\Scripts\python.exe -X utf8 -m pytest tests\test_distribution_contracts.py -q`

Expected: FAIL，原因包括缺少轻量安装器/依赖文件、构建路径未隔离和 pytest 配置不可按 CP936 读取。

### Task 2: 隔离构建、依赖和安装器

**Files:**
- Modify: `.gitignore`
- Modify: `build_dist_lightweight.bat`
- Modify: `光影选片助手_dist_lightweight.spec`
- Create: `requirements-lightweight.txt`
- Create: `installer_lightweight.iss`

- [ ] **Step 1: 扩充忽略规则但保留两个 spec**

```gitignore
.venv-light/
build_light/
dist_light/
Output_light/
!光影选片助手_dist.spec
!光影选片助手_dist_lightweight.spec
```

- [ ] **Step 2: 建立轻量依赖清单**

```text
numpy>=1.26,<2
opencv-contrib-python>=4.8,<5
Pillow>=10,<12
mediapipe>=0.10,<0.11
imagehash>=4.3,<5
PyQt6>=6.8,<6.9
rawpy>=0.20,<1
pyinstaller>=6.16,<7
```

- [ ] **Step 3: 修复轻量构建脚本**

将解释器改为 `.venv-light\Scripts\python.exe`，PyInstaller 命令改为：

```bat
"%PY%" -m PyInstaller --noconfirm --clean --distpath dist_light --workpath build_light 光影选片助手_dist_lightweight.spec
```

构建前删除目标应由 PyInstaller 的 `--noconfirm` 处理；脚本只检查 `dist_light`，并提示使用 `installer_lightweight.iss`。

- [ ] **Step 4: 收窄轻量 spec**

删除对所有第三方包的 `collect_submodules()`；只显式保留：

```python
from PyInstaller.utils.hooks import collect_data_files

hiddenimports = [
    "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets",
    "mediapipe.python.solutions.face_mesh",
    "absl.logging", "PIL.Image", "cv2", "imagehash",
]
datas = collect_data_files("mediapipe")
```

继续排除 Torch、Transformers、pyiqa、TensorFlow、测试和文档工具。

- [ ] **Step 5: 新增独立轻量安装器**

复制标准安装器结构，但使用：

```iss
#define MyAppName "光影选片助手轻量版"
#define MyAppNameEn "Lumina Select Lightweight"
#define MySourceDir "dist_light\光影选片助手"
#define MyOutputDir "Output_light"
```

设置独立 `AppId`、`DefaultDirName` 和 `OutputBaseFilename`，保证可与标准版并存。

- [ ] **Step 6: 重跑契约测试**

Run: `.\.venv\Scripts\python.exe -X utf8 -m pytest tests\test_distribution_contracts.py -q`

Expected: 所有契约测试 PASS。

### Task 3: 修复测试编码和双版本文档

**Files:**
- Modify: `pytest.ini`
- Modify: `requirements.txt`
- Modify: `README.md`

- [ ] **Step 1: 将 pytest 配置改为 ASCII 可读**

```ini
[pytest]
testpaths = tests
markers =
    e2e: end-to-end smoke test (loads inference backend and may run slowly)
addopts = -m "not e2e"
```

- [ ] **Step 2: 明确标准版依赖与环境假设**

在 `requirements.txt` 中显式约束 NumPy/MediaPipe/OpenCV/Pillow/PyQt6，并保留 Torch 推理依赖；README 说明标准版若复用已配置的 CUDA Torch 可使用 `--system-site-packages`，全新环境则需先按 PyTorch 平台说明安装匹配的 Torch。

- [ ] **Step 3: 重写 README 双版本章节**

分别给出：

```powershell
python -m venv --system-site-packages .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

python -m venv .venv-light
.\.venv-light\Scripts\python.exe -m pip install -r requirements-lightweight.txt
```

列明两个构建脚本、输出目录、安装器、能力差异和已验证体积；自动化测试命令使用默认 `python -m pytest`，验证 CP936 环境无需 `-X utf8`。

- [ ] **Step 4: 运行默认编码测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_distribution_contracts.py -q`

Expected: PASS，不出现 `UnicodeDecodeError`。

### Task 4: 创建纯净轻量环境并完成发行验收

**Files:**
- Generated and ignored: `.venv-light/`
- Generated and ignored: `build_light/`
- Generated and ignored: `dist_light/`

- [ ] **Step 1: 创建独立虚拟环境并安装依赖**

Run: `D:\Anaconda\python.exe -m venv .venv-light`

Run: `.\.venv-light\Scripts\python.exe -m pip install --cache-dir .pip_cache -r requirements-lightweight.txt`

Expected: 安装成功；`.\.venv-light\Scripts\python.exe -m pip check` 输出 `No broken requirements found.`

- [ ] **Step 2: 运行轻量源码测试**

Run: `$env:LUMINA_INFERENCE_BACKEND='heuristic'; .\.venv-light\Scripts\python.exe -m pytest tests -m "not e2e" -q`

Run: `$env:LUMINA_INFERENCE_BACKEND='heuristic'; .\.venv-light\Scripts\python.exe -m pytest tests\test_e2e_smoke.py -m e2e -q`

Expected: 常规测试和端到端测试全部通过。

- [ ] **Step 3: 构建轻量版**

Run: `.\.venv-light\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist_light --workpath build_light 光影选片助手_dist_lightweight.spec`

Expected: `dist_light\光影选片助手\光影选片助手.exe` 存在，标准版 `dist` 未被修改。

- [ ] **Step 4: 检查包内容与体积**

确认产物内没有 `torch`、`transformers`、`pyiqa`、`tensorflow`、`pytest` 或 `sphinx`。记录文件数和 MiB，并将真实数据写回 README。

- [ ] **Step 5: 试启动打包态程序**

隐藏启动轻量 exe，等待 5 秒；确认进程仍存活且无 `crash.log` 后结束测试进程。

- [ ] **Step 6: 最终回归**

Run: `.\.venv\Scripts\python.exe -m compileall -q app_qt.py engine tests`

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`

Run: `git diff --check`

Expected: 编译和测试通过，diff 无空白错误，Git 仅包含本轮有意修改；不 commit、不 push。
