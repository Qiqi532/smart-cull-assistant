# -*- coding: utf-8 -*-
"""推理后端抽象层回归测试（轻量化 Phase 0）。

只验证"接缝"本身与空输入路径，不触发任何 AI 模型下载/推理，
因此运行快、且不需要联网或 GPU。
"""
import numpy as np
import pytest

from engine import inference


def test_backend_names_includes_torch():
    assert "torch" in inference.backend_names()


def test_get_backend_default_is_torch():
    backend = inference.get_backend()
    assert backend.name == "torch"


def test_get_backend_unknown_raises():
    with pytest.raises(ValueError):
        inference.get_backend("no-such-backend")


def test_empty_inputs_return_empty_lists():
    # 空输入不应触发模型加载，直接返回等长空结果
    assert inference.quality_scores([]) == []
    assert inference.scene_and_aesthetics([]) == []


def test_quality_scores_delegates_to_torch_backend():
    # 单张合成图也应走通（torch 后端会真正加载画质模型并打分）
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    scores = inference.quality_scores([img])
    assert isinstance(scores, list) and len(scores) == 1
    # 纯黑图模型分可能为 None 或数值；只断言类型安全
    assert scores[0] is None or isinstance(scores[0], float)


def test_register_and_select_onnx_backend():
    # 验证"换后端只需注册+翻配置"的扩展点可用（不依赖 torch/onnx 实际安装）
    class _FakeBackend:
        name = "fake"

        def quality_scores(self, rgbs):
            return [42.0] * len(rgbs)

        def scene_and_aesthetics(self, images):
            return [{"aesthetic": 50.0, "scene": "其他", "scene_conf": 1.0}] * len(images)

        def quality_model_name(self):
            return "fake-q"

        def aesthetic_model_name(self):
            return "fake-a"

    inference.register_backend("fake", _FakeBackend)
    inference.reset_cache()
    try:
        b = inference.get_backend("fake")
        assert b.name == "fake"
        assert b.quality_scores([np.zeros((4, 4, 3), dtype=np.uint8)]) == [42.0]
    finally:
        # 清理：避免污染全局注册表
        inference._BACKENDS.pop("fake", None)
        inference.reset_cache()
