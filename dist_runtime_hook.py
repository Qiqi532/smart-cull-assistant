# -*- coding: utf-8 -*-
"""
dist_runtime_hook.py —— 自包含分发包的 PyInstaller 运行时钩子（runtime hook）

该文件由 光影选片助手_dist.spec 的 runtime_hooks 加载，在应用程序主模块
（app_qt.py）被 import *之前* 执行。作用：把 HuggingFace / torch 的模型缓存
重定向到 exe 所在目录下的 .hf_cache / .torch_cache 子文件夹，使整个
dist\光影选片助手\ 文件夹可"拎包即走"，模型权重不落 C 盘、也不依赖项目根目录。

注意：本文件是纯 Python，不引入任何 PowerShell 或外部脚本依赖。
"""
import os
import sys


def _app_dir() -> str:
    """返回 exe 所在目录（onedir 形态下即 dist\光影选片助手\）。"""
    if getattr(sys, "frozen", False):
        # 打包后：sys.executable 指向 <exe_dir>/光影选片助手.exe
        return os.path.dirname(os.path.abspath(sys.executable))
    # 未打包（开发态直接 import 本文件时）回退到项目根目录
    return os.path.dirname(os.path.abspath(__file__))


_app = _app_dir()

# 仅在用户/系统未显式设置时才写入，允许用户用系统环境变量覆盖。
os.environ.setdefault("HF_HOME", os.path.join(_app, ".hf_cache"))
os.environ.setdefault("HF_HUB_CACHE", os.path.join(_app, ".hf_cache", "hub"))
os.environ.setdefault("TORCH_HOME", os.path.join(_app, ".torch_cache"))
os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(_app, ".hf_cache", "hub"))
os.environ.setdefault("PYTHONPYCACHEPREFIX", os.path.join(_app, "pycache"))

# 若已配置镜像（hf-mirror.com），保持透传；未配置则默认走国内镜像，便于首次下载。
if not os.environ.get("HF_ENDPOINT"):
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
