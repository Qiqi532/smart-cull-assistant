# -*- coding: utf-8 -*-
"""quality.py 单测：模糊/曝光判定、BRISQUE 饱和中性化保护。"""
from __future__ import annotations

import numpy as np

from engine import quality


def _arr(shape, value):
    return np.full(shape, value, dtype=np.uint8)


def test_flat_image_is_low_blur():
    """纯色平滑图拉普拉斯方差应接近 0（明显低于废片阈值 60）。"""
    v = quality.blur_score_from_gray(_arr((256, 256), 128))
    assert v < quality.BLUR_WASTE_THRESHOLD


def test_noisy_image_high_blur():
    """随机噪声图拉普拉斯方差应显著高于废片阈值。"""
    rng = np.random.default_rng(0)
    v = quality.blur_score_from_gray(rng.integers(0, 256, (256, 256)).astype(np.uint8))
    assert v > quality.BLUR_WASTE_THRESHOLD


def test_white_overexposed():
    """全白图应判为严重过曝（over > 0.5）。"""
    gray = _arr((256, 256), 255)
    over, under = quality.exposure_ratio_from_gray(gray)
    assert over > quality.EXPO_WASTE_RATIO
    assert under < quality.EXPO_WASTE_RATIO


def test_black_underexposed():
    """全黑图应判为严重欠曝（under > 0.5）。"""
    gray = _arr((256, 256), 0)
    over, under = quality.exposure_ratio_from_gray(gray)
    assert over < quality.EXPO_WASTE_RATIO
    assert under > quality.EXPO_WASTE_RATIO


def test_analyze_image_array_shape():
    """analyze_image_array 对合法 RGB 输入返回四指标。"""
    rgb = np.full((32, 32, 3), 200, dtype=np.uint8)
    r = quality.analyze_image_array(rgb)
    assert set(r) >= {"blur_score", "over", "under", "noise"}


def test_analyze_image_array_none():
    """空输入不抛异常，返回全 0。"""
    r = quality.analyze_image_array(None)
    assert r["blur_score"] == 0.0


def test_brisque_saturation_protection():
    """BRISQUE ≥80 时应返回中性 0.5（防扁平插画误判为模糊）。"""
    # norm_quality 的饱和保护在 scorer 中实现，这里验证阈值常量一致
    from engine import scorer
    assert scorer.BRISQUE_SATURATED == 80.0
    assert scorer.norm_quality(90.0) == 0.5
    assert scorer.norm_quality(None) == 0.5
    # 正常范围内：分值越低质量越好
    assert scorer.norm_quality(10.0) > scorer.norm_quality(40.0)
