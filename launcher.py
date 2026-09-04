# -*- coding: utf-8 -*-
"""
launcher.py —— 光影选片助手 Windows 启动器（PyInstaller 打包入口，桌面软件形态）

双击 exe → 直接弹出原生桌面窗口（app_qt.py，PyQt6），无浏览器、无控制台黑窗：
  - 定位项目根目录（exe 所在位置）
  - 优先用项目 .venv 的 Python；缺失时回退到系统 python 并弹窗提示
  - 把 HF/TORCH 模型缓存重定向到项目内（不落 C 盘）

构建：build_exe.bat（已内置 .\\venv pyinstaller 命令）。
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys


def _msg(title: str, text: str):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception:
        print(text)


def _root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _pick_python(root: str) -> str:
    venv_py = os.path.join(root, ".venv", "Scripts", "python.exe")
    if os.path.isfile(venv_py):
        return venv_py
    return shutil.which("python") or ""


def main() -> int:
    root = _root()
    py = _pick_python(root)
    if not py:
        _msg("光影选片助手", "未找到 Python 环境。\n\n请先创建项目 .venv 并安装依赖（见 README），"
                            "或将 exe 放到项目根目录后重试。")
        return 1

    env = dict(os.environ)
    env.update({
        "HF_HOME": os.path.join(root, ".hf_cache"),
        "HF_HUB_CACHE": os.path.join(root, ".hf_cache", "hub"),
        "TORCH_HOME": os.path.join(root, ".torch_cache"),
        "TRANSFORMERS_CACHE": os.path.join(root, ".hf_cache", "hub"),
        "PYTHONPYCACHEPREFIX": os.path.join(root, "pycache"),
    })

    try:
        rc = subprocess.call([py, os.path.join(root, "app_qt.py")], cwd=root, env=env)
    except FileNotFoundError:
        _msg("光影选片助手", "找不到 app_qt.py，请把 exe 放到项目根目录。")
        return 1
    except KeyboardInterrupt:
        rc = 0
    return rc


if __name__ == "__main__":
    sys.exit(main())
