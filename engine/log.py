# -*- coding: utf-8 -*-
"""
log.py —— 统一日志（控制台 + 文件）

设计：
    - 单例配置，避免 Streamlit 反复 rerun 时重复添加 handler；
    - 日志文件默认 <项目根>/smart_cull.log（不落 C 盘）；
    - 只记录分析进度、模型加载、异常与耗时，不打印敏感信息（路径中的
      用户名等不做转义，属本地单机日志；如需脱敏可在 format 中处理）。
"""
from __future__ import annotations

import logging
import os
import warnings

from .config import LOG_FILE

# 环境适配：Anaconda base 的 bottleneck（NumPy 1.x 编译）被 pandas 作为可选依赖
# 导入时会抛“NumPy 2.x 二进制不兼容”警告（pandas errors="warn"，不影响运行）。
# 这里在 log 初始化前注册过滤，保持日志干净。
warnings.filterwarnings("ignore", message=".*A module that was compiled using NumPy 1.x cannot be run.*")

_ROOT = "smartcull"
_configured = False


def _setup():
    """初始化根 logger（幂等）。"""
    global _configured
    if _configured:
        return
    _configured = True
    root = logging.getLogger(_ROOT)
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    # 控制台
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)
    # 文件（失败不阻塞，如日志目录不可写）
    try:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass


def get_logger(name: str = "engine") -> logging.Logger:
    """获取子 logger：smartcull.<name>。"""
    _setup()
    return logging.getLogger(f"{_ROOT}.{name}")


def set_level(level: int):
    """动态调整日志级别（调试用）。"""
    logging.getLogger(_ROOT).setLevel(level)
