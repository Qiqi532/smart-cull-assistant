# -*- coding: utf-8 -*-
"""
inference.py —— 推理后端抽象层（轻量化 Phase 0 接缝）

目的：把"需要 torch / transformers / pyiqa 的深度学习推理"从业务流水线里隔离出来，
统一收敛到本模块。后续换轻量后端（ONNX Runtime / 纯 OpenCV 启发式）时，
**只需新增一个 Backend 实现并把 config.INFERENCE_BACKEND 切过去**，
pipeline.py 与 scorer.py 等业务代码完全不用动。

当前默认后端 torch_backend（沿用既有 quality.py / aesthetics.py，行为不变）。

设计要点：
  * 本模块在 import 时不引入 torch；torch 仅在具体后端方法内部按需 import，
    这样未来 onnx 后端即使在无 torch 的环境也能 import 本模块。
  * 后端实例惰性创建并缓存（AI 模型是单例，避免重复加载）。
"""
from __future__ import annotations

import sys
from typing import Protocol, runtime_checkable

import numpy as np
from PIL import Image


@runtime_checkable
class InferenceBackend(Protocol):
    """推理后端协议：所有后端必须实现以下方法。"""
    name: str

    def quality_scores(self, rgbs: list[np.ndarray]) -> list[float | None]:
        """批量画质分（0-100，越高越好）；模型不可用时返回等长 None 列表。"""
        ...

    def scene_and_aesthetics(self, images: list[Image.Image]) -> list[dict]:
        """批量美学 + 场景；返回 [{aesthetic, scene, scene_conf}, ...]。"""
        ...

    def quality_model_name(self) -> str:
        """当前生效画质模型名（参与 AI 模型签名，变更触发全量重算）。"""
        ...

    def aesthetic_model_name(self) -> str:
        """当前生效美学模型名（参与 AI 模型签名）。"""
        ...


class TorchBackend:
    """默认后端：复用既有 quality.py / aesthetics.py（torch + pyiqa + CLIP）。

    行为与改造前完全一致——quality_scores 走 quality.iqa_score_batch，
    scene_and_aesthetics 走 aesthetics.analyze_batch。
    """

    name = "torch"

    def __init__(self):
        # 延迟 import：避免无 torch 环境 import 本模块即失败
        from . import quality as _quality
        from .aesthetics import analyze_batch, aesthetic_model_name

        self._quality = _quality
        self._analyze_batch = analyze_batch
        self._aesthetic_model_name = aesthetic_model_name

    def quality_scores(self, rgbs: list[np.ndarray]) -> list[float | None]:
        if not rgbs:
            return []
        return self._quality.iqa_score_batch(rgbs)

    def scene_and_aesthetics(self, images: list[Image.Image]) -> list[dict]:
        if not images:
            return []
        return self._analyze_batch(images)

    def quality_model_name(self) -> str:
        return self._quality.quality_model_name()

    def aesthetic_model_name(self) -> str:
        return self._aesthetic_model_name()


# 后端注册表（Phase 1 用 register_backend 接入 onnx 后端）
_BACKENDS: dict[str, type] = {"torch": TorchBackend}
_CACHE: dict[str, InferenceBackend] = {}


def register_backend(name: str, cls: type) -> None:
    """接入新后端（如 ONNX）：register_backend('onnx', OnnxBackend)。"""
    _BACKENDS[name] = cls


def backend_names() -> list[str]:
    return list(_BACKENDS.keys())


def get_backend(name: str | None = None) -> InferenceBackend:
    """返回当前生效后端（按 config.INFERENCE_BACKEND，默认 torch），惰性缓存。"""
    from . import config

    name = name or config.INFERENCE_BACKEND
    if name not in _BACKENDS:
        raise ValueError(f"未知推理后端 {name!r}，可选：{backend_names()}")
    if name not in _CACHE:
        _CACHE[name] = _BACKENDS[name]()
    return _CACHE[name]


# ---- 业务侧统一入口（pipeline / scorer 等只调这些）----
def quality_scores(rgbs: list[np.ndarray]) -> list[float | None]:
    return get_backend().quality_scores(rgbs)


def scene_and_aesthetics(images: list[Image.Image]) -> list[dict]:
    return get_backend().scene_and_aesthetics(images)


def quality_model_name() -> str:
    return get_backend().quality_model_name()


def aesthetic_model_name() -> str:
    return get_backend().aesthetic_model_name()


def reset_cache() -> None:
    """测试 / 运行期重新加载模型时用。"""
    _CACHE.clear()


if __name__ == "__main__":
    print("可用后端：", backend_names())
    print("当前后端：", get_backend().name)
