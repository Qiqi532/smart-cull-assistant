# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# 光影选片助手_dist.spec —— 真正"自包含"的 PyInstaller 打包规格（onedir 形态）
#
# 与旧的 光影选片助手.spec（仅打包 launcher.py，运行时还要调 .venv 里的
# python 启动 app_qt.py）不同，本 spec 直接以 app_qt.py 为入口，把全部第三方
# 依赖（torch / transformers / PyQt6 / mediapipe / 等）一并打进 onedir 文件夹，
# 双击 dist/光影选片助手/光影选片助手.exe 即可运行，无需项目 .venv 与源码在场。
#
# 模型权重（CLIP / 闭眼 ViT / MediaPipe）不打包，首次运行时通过 HF 镜像下载到
# exe 目录下的 .hf_cache / .torch_cache（见 dist_runtime_hook.py）。
#
# 用法：build_dist.bat   （内部执行  pyinstaller 光影选片助手_dist.spec）
# =============================================================================

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# 入口脚本：直接打包桌面主程序（不再经 launcher 子进程）。
# 注意：下方注释中的反斜杠仅为 Windows 路径示例说明。
app_script = 'app_qt.py'

# --- 真正被 app_qt.py / engine/* 导入的第三方包（由 grep 确认） -----------------
# 这些包多在函数内延迟 import（torch / transformers / mediapipe / pyiqa 等），
# 静态分析抓不到，必须显式 collect_submodules / collect_data_files 才能打全。
_real_third_party = [
    'torch', 'torchvision',          # 推理引擎（含 CUDA 时一并打包 GPU 版）
    'transformers',                  # CLIP / ViT 闭眼分类器
    'huggingface_hub',               # transformers 动态加载依赖
    'safetensors',                   # transformers 动态加载依赖
    'PyQt6',                         # 桌面原生界面
    'mediapipe',                     # 人脸关键点 / 闭眼 EAR
    'absl',                          # faces.py 顶层 from absl import logging
    'PIL',                           # Pillow
    'numpy',
    'pyiqa',                         # 无参考画质模型（musiq / dbcnn / brisque）
    'cv2',                           # opencv-python
    'imagehash',                     # pHash 感知哈希
]

hiddenimports = []
datas = []
for _pkg in _real_third_party:
    hiddenimports += collect_submodules(_pkg)
    try:
        datas += collect_data_files(_pkg)
    except Exception:
        # 个别包无 data 文件时忽略（不阻断打包）
        pass

# 随包分发的小权重模型（LAION 美学线性头约 3KB，只读，打进 _internal/models）
import os as _os
if _os.path.isdir('models'):
    datas.append(('models', 'models'))

# 兜底：显式列出关键顶层导入，确保 collect_submodules 漏网时仍被包含
hiddenimports += [
    'torch', 'torchvision', 'transformers', 'huggingface_hub', 'safetensors',
    'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets',
    'mediapipe', 'mediapipe.python.solutions.face_mesh',
    'absl', 'absl.logging',
    'PIL', 'PIL.Image',
    'numpy', 'pyiqa', 'cv2', 'imagehash',
]

# 去重
hiddenimports = sorted(set(hiddenimports))

a = Analysis(
    [app_script],
    pathex=['.'],                      # 在项目根目录查找 engine 包与本地模块
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['dist_runtime_hook.py'],  # 打包前重定向 HF/TORCH 缓存目录
    excludes=[
        # 这些包未被任何源码导入，排除以减小体积
        'timm', 'sklearn', 'scipy',
        'matplotlib', 'tensorboard', 'wandb',
        'torchaudio',
        # 环境中同时存在 PyQt5（conda 自带，mediapipe 间接依赖）与 PyQt6，
        # PyInstaller 禁止同时打包两个 Qt 绑定 —— 本应用只用 PyQt6
        'PyQt5', 'PySide2', 'PySide6', 'shiboken2', 'shiboken6',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],                     # onedir：二进制与数据由下方 COLLECT 收集进 _internal，
    exclude_binaries=True,  # 不再重复嵌入 exe（否则 exe 体积翻倍至数 GB）
    name='光影选片助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                        # 大包下关闭 UPX，避免个别二进制损坏/极慢
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                    # 桌面原生窗口，无控制台黑窗
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# onedir 形态：产出 dist/光影选片助手/ 文件夹，整体可独立运行
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='光影选片助手',
)
